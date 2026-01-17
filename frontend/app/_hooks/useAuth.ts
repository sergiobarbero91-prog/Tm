// =============================================================================
// useAuth Hook - TaxiDash Madrid
// =============================================================================
import { useState, useEffect, useCallback } from 'react';
import { Alert } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import Constants from 'expo-constants';
import { User } from '../types';

const API_BASE = Constants.expoConfig?.extra?.EXPO_PUBLIC_BACKEND_URL || 
                 process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface UseAuthReturn {
  currentUser: User | null;
  isLoading: boolean;
  authChecked: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  register: (data: RegisterData) => Promise<boolean>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<boolean>;
  updateProfile: (data: Partial<User>) => Promise<boolean>;
  refreshToken: () => Promise<void>;
}

interface RegisterData {
  username: string;
  password: string;
  full_name: string;
  license_number: string;
  phone?: string;
  preferred_shift?: string;
}

export const useAuth = (): UseAuthReturn => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  // Check existing session on mount
  useEffect(() => {
    checkExistingSession();
  }, []);

  // Set up token refresh interval
  useEffect(() => {
    if (!currentUser) return;

    const refreshInterval = setInterval(() => {
      refreshToken();
    }, 20 * 60 * 1000); // Refresh every 20 minutes

    return () => clearInterval(refreshInterval);
  }, [currentUser]);

  const checkExistingSession = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const userStr = await AsyncStorage.getItem('user');
      if (token && userStr) {
        const user = JSON.parse(userStr);
        setCurrentUser(user);
      }
    } catch (error) {
      console.error('Error checking session:', error);
    } finally {
      setAuthChecked(true);
    }
  };

  const login = useCallback(async (username: string, password: string): Promise<boolean> => {
    if (!username || !password) {
      Alert.alert('Error', 'Ingresa usuario y contraseña');
      return false;
    }

    setIsLoading(true);
    try {
      const response = await axios.post(`${API_BASE}/api/auth/login`, {
        username,
        password
      });

      const { access_token, user } = response.data;
      await AsyncStorage.setItem('token', access_token);
      await AsyncStorage.setItem('user', JSON.stringify(user));
      
      setCurrentUser(user);
      return true;
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Usuario o contraseña incorrectos');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    await AsyncStorage.removeItem('token');
    await AsyncStorage.removeItem('user');
    setCurrentUser(null);
  }, []);

  const register = useCallback(async (data: RegisterData): Promise<boolean> => {
    if (!data.username || !data.password || !data.full_name || !data.license_number) {
      Alert.alert('Error', 'Por favor completa los campos obligatorios');
      return false;
    }

    if (data.password.length < 4) {
      Alert.alert('Error', 'La contraseña debe tener al menos 4 caracteres');
      return false;
    }

    if (!/^\d+$/.test(data.license_number)) {
      Alert.alert('Error', 'El número de licencia debe contener solo dígitos');
      return false;
    }

    setIsLoading(true);
    try {
      const response = await axios.post(`${API_BASE}/api/auth/register`, {
        username: data.username,
        password: data.password,
        full_name: data.full_name,
        license_number: data.license_number,
        phone: data.phone || null,
        preferred_shift: data.preferred_shift || 'all'
      });

      const { access_token, user } = response.data;
      await AsyncStorage.setItem('token', access_token);
      await AsyncStorage.setItem('user', JSON.stringify(user));
      
      setCurrentUser(user);
      Alert.alert('¡Bienvenido!', `Registro exitoso, ${user.full_name}`);
      return true;
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al registrar usuario');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string): Promise<boolean> => {
    if (!currentPassword || !newPassword) {
      Alert.alert('Error', 'Por favor completa todos los campos');
      return false;
    }

    if (newPassword.length < 4) {
      Alert.alert('Error', 'La nueva contraseña debe tener al menos 4 caracteres');
      return false;
    }

    setIsLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/auth/change-password`, {
        current_password: currentPassword,
        new_password: newPassword
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Contraseña actualizada correctamente');
      return true;
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al cambiar contraseña');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const updateProfile = useCallback(async (data: Partial<User>): Promise<boolean> => {
    setIsLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.put(`${API_BASE}/api/auth/profile`, data, {
        headers: { Authorization: `Bearer ${token}` }
      });

      const updatedUser = response.data.user;
      await AsyncStorage.setItem('user', JSON.stringify(updatedUser));
      setCurrentUser(updatedUser);
      
      Alert.alert('Éxito', 'Perfil actualizado correctamente');
      return true;
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al actualizar perfil');
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refreshToken = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      if (!token) return;

      const response = await axios.post(`${API_BASE}/api/auth/refresh-token`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (response.data.access_token) {
        await AsyncStorage.setItem('token', response.data.access_token);
        console.log('[Auth] Token refreshed successfully');
      }
    } catch (error) {
      console.log('[Auth] Token refresh failed:', error);
    }
  }, []);

  return {
    currentUser,
    isLoading,
    authChecked,
    login,
    logout,
    register,
    changePassword,
    updateProfile,
    refreshToken,
  };
};

export default useAuth;
