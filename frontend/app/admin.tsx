import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Modal,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';

const API_BASE = Constants.expoConfig?.extra?.EXPO_PUBLIC_BACKEND_URL || '';

interface User {
  id: string;
  username: string;
  phone: string | null;
  role: string;
  created_at: string;
}

export default function AdminScreen() {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [showChangeOwnPasswordModal, setShowChangeOwnPasswordModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  // Form states
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [newRole, setNewRole] = useState('user');
  const [editPhone, setEditPhone] = useState('');
  const [editRole, setEditRole] = useState('');
  const [changePassword, setChangePassword] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [ownNewPassword, setOwnNewPassword] = useState('');

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const storedToken = await AsyncStorage.getItem('token');
      const storedUser = await AsyncStorage.getItem('user');
      
      if (!storedToken || !storedUser) {
        router.replace('/');
        return;
      }

      const user = JSON.parse(storedUser);
      if (user.role !== 'admin') {
        Alert.alert('Error', 'No tienes permisos de administrador');
        router.replace('/');
        return;
      }

      setToken(storedToken);
      setCurrentUser(user);
      await fetchUsers(storedToken);
    } catch (error) {
      router.replace('/');
    }
  };

  const fetchUsers = async (authToken: string) => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_BASE}/api/admin/users`, {
        headers: { Authorization: `Bearer ${authToken}` }
      });
      setUsers(response.data);
    } catch (error: any) {
      Alert.alert('Error', 'No se pudieron cargar los usuarios');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await AsyncStorage.removeItem('token');
    await AsyncStorage.removeItem('user');
    router.replace('/');
  };

  const handleCreateUser = async () => {
    if (!newUsername || !newPassword) {
      Alert.alert('Error', 'Nombre de usuario y contraseña son obligatorios');
      return;
    }

    try {
      await axios.post(`${API_BASE}/api/admin/users`, {
        username: newUsername,
        password: newPassword,
        phone: newPhone || null,
        role: newRole
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Usuario creado correctamente');
      setShowCreateModal(false);
      setNewUsername('');
      setNewPassword('');
      setNewPhone('');
      setNewRole('user');
      await fetchUsers(token!);
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo crear el usuario');
    }
  };

  const handleUpdateUser = async () => {
    if (!selectedUser) return;

    try {
      await axios.put(`${API_BASE}/api/admin/users/${selectedUser.id}`, {
        phone: editPhone || null,
        role: editRole
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Usuario actualizado correctamente');
      setShowEditModal(false);
      setSelectedUser(null);
      await fetchUsers(token!);
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo actualizar el usuario');
    }
  };

  const handleChangePassword = async () => {
    if (!selectedUser || !changePassword) {
      Alert.alert('Error', 'Ingresa la nueva contraseña');
      return;
    }

    try {
      await axios.put(`${API_BASE}/api/admin/users/${selectedUser.id}/password`, {
        new_password: changePassword
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Contraseña actualizada correctamente');
      setShowPasswordModal(false);
      setSelectedUser(null);
      setChangePassword('');
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo cambiar la contraseña');
    }
  };

  const handleChangeOwnPassword = async () => {
    if (!currentPassword || !ownNewPassword) {
      Alert.alert('Error', 'Completa todos los campos');
      return;
    }

    try {
      await axios.put(`${API_BASE}/api/auth/password`, {
        current_password: currentPassword,
        new_password: ownNewPassword
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Tu contraseña ha sido actualizada');
      setShowChangeOwnPasswordModal(false);
      setCurrentPassword('');
      setOwnNewPassword('');
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo cambiar la contraseña');
    }
  };

  const handleDeleteUser = async (user: User) => {
    Alert.alert(
      'Confirmar eliminación',
      `¿Estás seguro de eliminar al usuario "${user.username}"?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            try {
              await axios.delete(`${API_BASE}/api/admin/users/${user.id}`, {
                headers: { Authorization: `Bearer ${token}` }
              });
              Alert.alert('Éxito', 'Usuario eliminado');
              await fetchUsers(token!);
            } catch (error: any) {
              Alert.alert('Error', error.response?.data?.detail || 'No se pudo eliminar el usuario');
            }
          }
        }
      ]
    );
  };

  const openEditModal = (user: User) => {
    setSelectedUser(user);
    setEditPhone(user.phone || '');
    setEditRole(user.role);
    setShowEditModal(true);
  };

  const openPasswordModal = (user: User) => {
    setSelectedUser(user);
    setChangePassword('');
    setShowPasswordModal(true);
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backButton}>
          <Ionicons name="arrow-back" size={24} color="#FFFFFF" />
        </TouchableOpacity>
        <Text style={styles.headerTitle}>Panel de Administración</Text>
        <TouchableOpacity onPress={handleLogout} style={styles.logoutButton}>
          <Ionicons name="log-out-outline" size={24} color="#EF4444" />
        </TouchableOpacity>
      </View>

      {/* Admin Actions */}
      <View style={styles.actionsContainer}>
        <TouchableOpacity 
          style={styles.actionButton}
          onPress={() => setShowCreateModal(true)}
        >
          <Ionicons name="person-add" size={20} color="#FFFFFF" />
          <Text style={styles.actionButtonText}>Crear Usuario</Text>
        </TouchableOpacity>
        <TouchableOpacity 
          style={[styles.actionButton, styles.actionButtonSecondary]}
          onPress={() => setShowChangeOwnPasswordModal(true)}
        >
          <Ionicons name="key" size={20} color="#6366F1" />
          <Text style={[styles.actionButtonText, styles.actionButtonTextSecondary]}>Mi Contraseña</Text>
        </TouchableOpacity>
      </View>

      {/* Users List */}
      <ScrollView style={styles.content} showsVerticalScrollIndicator={false}>
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#6366F1" />
          </View>
        ) : (
          users.map((user) => (
            <View key={user.id} style={styles.userCard}>
              <View style={styles.userInfo}>
                <View style={styles.userHeader}>
                  <Ionicons 
                    name={user.role === 'admin' ? 'shield' : 'person'} 
                    size={20} 
                    color={user.role === 'admin' ? '#F59E0B' : '#6366F1'} 
                  />
                  <Text style={styles.username}>{user.username}</Text>
                  <View style={[
                    styles.roleBadge,
                    user.role === 'admin' && styles.adminBadge
                  ]}>
                    <Text style={styles.roleText}>
                      {user.role === 'admin' ? 'Admin' : 'Usuario'}
                    </Text>
                  </View>
                </View>
                {user.phone && (
                  <View style={styles.phoneContainer}>
                    <Ionicons name="call-outline" size={14} color="#94A3B8" />
                    <Text style={styles.phoneText}>{user.phone}</Text>
                  </View>
                )}
              </View>
              <View style={styles.userActions}>
                <TouchableOpacity 
                  style={styles.iconButton}
                  onPress={() => openEditModal(user)}
                >
                  <Ionicons name="create-outline" size={20} color="#6366F1" />
                </TouchableOpacity>
                <TouchableOpacity 
                  style={styles.iconButton}
                  onPress={() => openPasswordModal(user)}
                >
                  <Ionicons name="key-outline" size={20} color="#F59E0B" />
                </TouchableOpacity>
                {user.id !== currentUser?.id && (
                  <TouchableOpacity 
                    style={styles.iconButton}
                    onPress={() => handleDeleteUser(user)}
                  >
                    <Ionicons name="trash-outline" size={20} color="#EF4444" />
                  </TouchableOpacity>
                )}
              </View>
            </View>
          ))
        )}
      </ScrollView>

      {/* Create User Modal */}
      <Modal visible={showCreateModal} transparent animationType="slide">
        <KeyboardAvoidingView 
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalOverlay}
        >
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Crear Usuario</Text>
            
            <TextInput
              style={styles.input}
              placeholder="Nombre de usuario"
              placeholderTextColor="#64748B"
              value={newUsername}
              onChangeText={setNewUsername}
              autoCapitalize="none"
            />
            <TextInput
              style={styles.input}
              placeholder="Contraseña"
              placeholderTextColor="#64748B"
              value={newPassword}
              onChangeText={setNewPassword}
              secureTextEntry
            />
            <TextInput
              style={styles.input}
              placeholder="Teléfono (opcional)"
              placeholderTextColor="#64748B"
              value={newPhone}
              onChangeText={setNewPhone}
              keyboardType="phone-pad"
            />
            
            <View style={styles.roleSelector}>
              <TouchableOpacity
                style={[styles.roleOption, newRole === 'user' && styles.roleOptionActive]}
                onPress={() => setNewRole('user')}
              >
                <Text style={[styles.roleOptionText, newRole === 'user' && styles.roleOptionTextActive]}>
                  Usuario
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.roleOption, newRole === 'admin' && styles.roleOptionActive]}
                onPress={() => setNewRole('admin')}
              >
                <Text style={[styles.roleOptionText, newRole === 'admin' && styles.roleOptionTextActive]}>
                  Admin
                </Text>
              </TouchableOpacity>
            </View>

            <View style={styles.modalActions}>
              <TouchableOpacity 
                style={styles.cancelButton}
                onPress={() => setShowCreateModal(false)}
              >
                <Text style={styles.cancelButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={styles.confirmButton}
                onPress={handleCreateUser}
              >
                <Text style={styles.confirmButtonText}>Crear</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Edit User Modal */}
      <Modal visible={showEditModal} transparent animationType="slide">
        <KeyboardAvoidingView 
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalOverlay}
        >
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Editar Usuario</Text>
            <Text style={styles.modalSubtitle}>{selectedUser?.username}</Text>
            
            <TextInput
              style={styles.input}
              placeholder="Teléfono"
              placeholderTextColor="#64748B"
              value={editPhone}
              onChangeText={setEditPhone}
              keyboardType="phone-pad"
            />
            
            <View style={styles.roleSelector}>
              <TouchableOpacity
                style={[styles.roleOption, editRole === 'user' && styles.roleOptionActive]}
                onPress={() => setEditRole('user')}
              >
                <Text style={[styles.roleOptionText, editRole === 'user' && styles.roleOptionTextActive]}>
                  Usuario
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.roleOption, editRole === 'admin' && styles.roleOptionActive]}
                onPress={() => setEditRole('admin')}
              >
                <Text style={[styles.roleOptionText, editRole === 'admin' && styles.roleOptionTextActive]}>
                  Admin
                </Text>
              </TouchableOpacity>
            </View>

            <View style={styles.modalActions}>
              <TouchableOpacity 
                style={styles.cancelButton}
                onPress={() => setShowEditModal(false)}
              >
                <Text style={styles.cancelButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={styles.confirmButton}
                onPress={handleUpdateUser}
              >
                <Text style={styles.confirmButtonText}>Guardar</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Change Password Modal (Admin changing other's password) */}
      <Modal visible={showPasswordModal} transparent animationType="slide">
        <KeyboardAvoidingView 
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalOverlay}
        >
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Cambiar Contraseña</Text>
            <Text style={styles.modalSubtitle}>{selectedUser?.username}</Text>
            
            <TextInput
              style={styles.input}
              placeholder="Nueva contraseña"
              placeholderTextColor="#64748B"
              value={changePassword}
              onChangeText={setChangePassword}
              secureTextEntry
            />

            <View style={styles.modalActions}>
              <TouchableOpacity 
                style={styles.cancelButton}
                onPress={() => setShowPasswordModal(false)}
              >
                <Text style={styles.cancelButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={styles.confirmButton}
                onPress={handleChangePassword}
              >
                <Text style={styles.confirmButtonText}>Cambiar</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Change Own Password Modal */}
      <Modal visible={showChangeOwnPasswordModal} transparent animationType="slide">
        <KeyboardAvoidingView 
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalOverlay}
        >
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>Cambiar Mi Contraseña</Text>
            
            <TextInput
              style={styles.input}
              placeholder="Contraseña actual"
              placeholderTextColor="#64748B"
              value={currentPassword}
              onChangeText={setCurrentPassword}
              secureTextEntry
            />
            <TextInput
              style={styles.input}
              placeholder="Nueva contraseña"
              placeholderTextColor="#64748B"
              value={ownNewPassword}
              onChangeText={setOwnNewPassword}
              secureTextEntry
            />

            <View style={styles.modalActions}>
              <TouchableOpacity 
                style={styles.cancelButton}
                onPress={() => setShowChangeOwnPasswordModal(false)}
              >
                <Text style={styles.cancelButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={styles.confirmButton}
                onPress={handleChangeOwnPassword}
              >
                <Text style={styles.confirmButtonText}>Cambiar</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0F172A',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 15,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  backButton: {
    padding: 5,
  },
  headerTitle: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '600',
  },
  logoutButton: {
    padding: 5,
  },
  actionsContainer: {
    flexDirection: 'row',
    paddingHorizontal: 20,
    paddingVertical: 15,
    gap: 10,
  },
  actionButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#6366F1',
    paddingVertical: 12,
    borderRadius: 10,
    gap: 8,
  },
  actionButtonSecondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: '#6366F1',
  },
  actionButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  actionButtonTextSecondary: {
    color: '#6366F1',
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 50,
  },
  userCard: {
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 15,
    marginBottom: 10,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  userInfo: {
    flex: 1,
  },
  userHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  username: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  roleBadge: {
    backgroundColor: '#334155',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
  },
  adminBadge: {
    backgroundColor: '#F59E0B33',
  },
  roleText: {
    color: '#94A3B8',
    fontSize: 11,
    fontWeight: '500',
  },
  phoneContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    marginTop: 5,
  },
  phoneText: {
    color: '#94A3B8',
    fontSize: 13,
  },
  userActions: {
    flexDirection: 'row',
    gap: 5,
  },
  iconButton: {
    padding: 8,
    backgroundColor: '#0F172A',
    borderRadius: 8,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 20,
    width: '100%',
    maxWidth: 400,
  },
  modalTitle: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: '600',
    textAlign: 'center',
    marginBottom: 5,
  },
  modalSubtitle: {
    color: '#94A3B8',
    fontSize: 14,
    textAlign: 'center',
    marginBottom: 20,
  },
  input: {
    backgroundColor: '#0F172A',
    borderRadius: 10,
    padding: 15,
    color: '#FFFFFF',
    fontSize: 16,
    marginBottom: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  roleSelector: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 20,
  },
  roleOption: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: '#0F172A',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#334155',
  },
  roleOptionActive: {
    backgroundColor: '#6366F1',
    borderColor: '#6366F1',
  },
  roleOptionText: {
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: '500',
  },
  roleOptionTextActive: {
    color: '#FFFFFF',
  },
  modalActions: {
    flexDirection: 'row',
    gap: 10,
  },
  cancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 10,
    backgroundColor: '#334155',
    alignItems: 'center',
  },
  cancelButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  confirmButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 10,
    backgroundColor: '#6366F1',
    alignItems: 'center',
  },
  confirmButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
});
