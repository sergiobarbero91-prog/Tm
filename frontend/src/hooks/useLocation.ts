// =============================================================================
// useLocation Hook - TaxiDash Madrid
// GPS and location services
// =============================================================================
import { useState, useCallback, useEffect } from 'react';
import { Alert, Linking, Platform } from 'react-native';
import * as Location from 'expo-location';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { GpsApp } from '../types';

interface LocationCoords {
  latitude: number;
  longitude: number;
}

interface UseLocationReturn {
  currentLocation: LocationCoords | null;
  locationPermission: boolean;
  gpsApp: GpsApp;
  isLoadingLocation: boolean;
  getCurrentLocation: () => Promise<LocationCoords | null>;
  openNavigationApp: (latitude: number, longitude: number, label?: string) => void;
  setPreferredGpsApp: (app: GpsApp) => Promise<void>;
}

export const useLocation = (): UseLocationReturn => {
  const [currentLocation, setCurrentLocation] = useState<LocationCoords | null>(null);
  const [locationPermission, setLocationPermission] = useState(false);
  const [gpsApp, setGpsApp] = useState<GpsApp>('google');
  const [isLoadingLocation, setIsLoadingLocation] = useState(false);

  // Load GPS preference on mount
  useEffect(() => {
    loadGpsPreference();
    requestLocationPermission();
  }, []);

  const loadGpsPreference = async () => {
    try {
      const savedApp = await AsyncStorage.getItem('gpsApp');
      if (savedApp === 'google' || savedApp === 'waze') {
        setGpsApp(savedApp);
      }
    } catch (error) {
      console.error('Error loading GPS preference:', error);
    }
  };

  const requestLocationPermission = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      setLocationPermission(status === 'granted');
    } catch (error) {
      console.error('Error requesting location permission:', error);
    }
  };

  const getCurrentLocation = useCallback(async (): Promise<LocationCoords | null> => {
    setIsLoadingLocation(true);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      
      if (status !== 'granted') {
        Alert.alert(
          'Permiso de ubicación',
          'Necesitamos acceso a tu ubicación para registrar la actividad.',
          [
            { text: 'Cancelar', style: 'cancel' },
            { text: 'Abrir Ajustes', onPress: () => Linking.openSettings() }
          ]
        );
        return null;
      }

      setLocationPermission(true);
      
      const location = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });

      const coords = {
        latitude: location.coords.latitude,
        longitude: location.coords.longitude,
      };

      setCurrentLocation(coords);
      return coords;
    } catch (error) {
      console.error('Error getting location:', error);
      Alert.alert('Error', 'No se pudo obtener tu ubicación. Verifica que el GPS esté activado.');
      return null;
    } finally {
      setIsLoadingLocation(false);
    }
  }, []);

  const openNavigationApp = useCallback((latitude: number, longitude: number, label?: string) => {
    const encodedLabel = encodeURIComponent(label || 'Destino');
    
    let url: string;
    
    if (gpsApp === 'waze') {
      url = `https://waze.com/ul?ll=${latitude},${longitude}&navigate=yes`;
    } else {
      // Google Maps
      if (Platform.OS === 'ios') {
        url = `comgooglemaps://?daddr=${latitude},${longitude}&directionsmode=driving`;
      } else if (Platform.OS === 'android') {
        url = `google.navigation:q=${latitude},${longitude}`;
      } else {
        url = `https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}`;
      }
    }

    Linking.canOpenURL(url)
      .then((supported) => {
        if (supported) {
          Linking.openURL(url);
        } else {
          // Fallback to web
          const webUrl = gpsApp === 'waze'
            ? `https://waze.com/ul?ll=${latitude},${longitude}&navigate=yes`
            : `https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}`;
          Linking.openURL(webUrl);
        }
      })
      .catch((error) => {
        console.error('Error opening navigation:', error);
        Alert.alert('Error', 'No se pudo abrir la aplicación de navegación');
      });
  }, [gpsApp]);

  const setPreferredGpsApp = useCallback(async (app: GpsApp) => {
    try {
      await AsyncStorage.setItem('gpsApp', app);
      setGpsApp(app);
    } catch (error) {
      console.error('Error saving GPS preference:', error);
    }
  }, []);

  return {
    currentLocation,
    locationPermission,
    gpsApp,
    isLoadingLocation,
    getCurrentLocation,
    openNavigationApp,
    setPreferredGpsApp,
  };
};

export default useLocation;
