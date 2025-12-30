import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  SafeAreaView,
  StatusBar,
  Platform,
  Alert,
  Switch,
  Modal,
  TextInput,
  KeyboardAvoidingView,
  Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';
import * as Notifications from 'expo-notifications';
import * as Location from 'expo-location';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useRouter } from 'expo-router';
import { WebView } from 'react-native-webview';
import * as Linking from 'expo-linking';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const { width: SCREEN_WIDTH } = Dimensions.get('window');

// Configure notifications
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

interface TrainArrival {
  time: string;  // Hora real de llegada
  scheduled_time?: string;  // Hora programada original
  origin: string;
  train_type: string;
  train_number: string;
  platform?: string;
  status?: string;
  delay_minutes?: number;  // Minutos de retraso
}

interface PeakHourInfo {
  start_hour: string;
  end_hour: string;
  count: number;
}

interface StationData {
  station_id: string;
  station_name: string;
  arrivals: TrainArrival[];
  total_next_30min: number;
  total_next_60min: number;
  is_winner_30min: boolean;
  is_winner_60min: boolean;
  peak_hour?: PeakHourInfo;
}

interface TrainComparison {
  atocha: StationData;
  chamartin: StationData;
  winner_30min: string;
  winner_60min: string;
  last_update: string;
  is_night_time?: boolean;
  message?: string;
}

interface FlightArrival {
  time: string;  // Hora real de llegada
  scheduled_time?: string;  // Hora programada
  origin: string;
  flight_number: string;
  airline: string;
  terminal: string;
  gate?: string;
  status?: string;
  delay_minutes?: number;  // Minutos de retraso (negativo si adelantado)
}

interface TerminalData {
  terminal: string;
  arrivals: FlightArrival[];
  total_next_30min: number;
  total_next_60min: number;
  is_winner_30min: boolean;
  is_winner_60min: boolean;
}

interface FlightComparison {
  terminals: { [key: string]: TerminalData };
  winner_30min: string;
  winner_60min: string;
  last_update: string;
}

interface HotStreet {
  street_name: string;
  count: number;
  last_activity: string;
  latitude: number;
  longitude: number;
}

interface StreetActivity {
  id: string;
  user_id: string;
  username: string;
  action: string;  // "load", "unload", "station_entry", "station_exit", "terminal_entry", "terminal_exit"
  latitude: number;
  longitude: number;
  street_name: string;
  location_name?: string;  // Name of station or terminal
  created_at: string;
  duration_minutes?: number;  // Duration for completed activities (unload)
  distance_km?: number;  // Distance traveled for unload (from load point)
}

interface StreetWorkData {
  // Hottest street (only load/unload)
  hottest_street: string | null;
  hottest_street_lat: number | null;
  hottest_street_lng: number | null;
  hottest_count: number;
  hottest_percentage: number | null;
  hottest_total_loads: number;
  hottest_distance_km: number | null;
  hot_streets: HotStreet[];
  
  // Hottest station (based on weighted score)
  hottest_station: string | null;
  hottest_station_count: number;
  hottest_station_lat: number | null;
  hottest_station_lng: number | null;
  hottest_station_score: number | null;
  hottest_station_avg_load_time: number | null;
  hottest_station_arrivals: number | null;
  hottest_station_exits: number | null;
  hottest_station_future_arrivals: number | null;
  hottest_station_low_arrivals_alert: boolean;
  
  // Hottest terminal (based on weighted score)
  hottest_terminal: string | null;
  hottest_terminal_count: number;
  hottest_terminal_lat: number | null;
  hottest_terminal_lng: number | null;
  hottest_terminal_score: number | null;
  hottest_terminal_avg_load_time: number | null;
  hottest_terminal_arrivals: number | null;
  hottest_terminal_exits: number | null;
  hottest_terminal_future_arrivals: number | null;
  hottest_terminal_low_arrivals_alert: boolean;
  
  // Taxi status for hottest locations
  hottest_station_taxi_status?: string | null;
  hottest_station_taxi_time?: string | null;
  hottest_station_taxi_reporter?: string | null;
  hottest_terminal_taxi_status?: string | null;
  hottest_terminal_taxi_time?: string | null;
  hottest_terminal_taxi_reporter?: string | null;
  
  // Exits by location in previous window
  exits_by_station: { [key: string]: number };
  exits_by_terminal: { [key: string]: number };
  
  recent_activities: StreetActivity[];
  total_loads: number;
  total_unloads: number;
  total_station_entries: number;
  total_station_exits: number;
  total_terminal_entries: number;
  total_terminal_exits: number;
  last_update: string;
}

interface TaxiStatusData {
  [key: string]: {
    location_type: string;
    location_name: string;
    taxi_status: string;
    reported_at: string;
    reported_by: string;
  };
}

interface QueueStatusData {
  [key: string]: {
    location_type: string;
    location_name: string;
    queue_status: string;
    reported_at: string;
    reported_by: string;
  };
}

interface HotStreet {
  street_name: string;
  count: number;
  last_activity: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}

interface User {
  id: string;
  username: string;
  phone: string | null;
  role: string;
}

interface CheckInStatus {
  is_checked_in: boolean;
  location_type: string | null;
  location_name: string | null;
  entry_time: string | null;
}

type GpsApp = 'google' | 'waze';

export default function TransportMeter() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<'trains' | 'flights' | 'street'>('trains');
  const [trainData, setTrainData] = useState<TrainComparison | null>(null);
  const [flightData, setFlightData] = useState<FlightComparison | null>(null);
  const [streetData, setStreetData] = useState<StreetWorkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [timeWindow, setTimeWindow] = useState<30 | 60>(60);
  const [checkInStatus, setCheckInStatus] = useState<CheckInStatus | null>(null);
  const [checkInLoading, setCheckInLoading] = useState(false);
  const [hasActiveLoad, setHasActiveLoad] = useState(false);  // For load/unload toggle
  const [gpsApp, setGpsApp] = useState<GpsApp>('google');
  const [showSettings, setShowSettings] = useState(false);
  const [shift, setShift] = useState<'all' | 'day' | 'night'>('all');
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [pushToken, setPushToken] = useState<string | null>(null);
  const [taxiStatus, setTaxiStatus] = useState<TaxiStatusData>({});
  const [queueStatus, setQueueStatus] = useState<QueueStatusData>({});

  // Auth states
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);

  // Emergency SOS states
  const [showSosModal, setShowSosModal] = useState(false);
  const [myActiveAlert, setMyActiveAlert] = useState<{
    alert_id: string;
    alert_type: string;
    latitude: number;
    longitude: number;
  } | null>(null);
  const [activeAlerts, setActiveAlerts] = useState<Array<{
    alert_id: string;
    user_id: string;
    username: string;
    alert_type: string;
    latitude: number;
    longitude: number;
    created_at: string;
    is_own: boolean;
  }>>([]);
  const [showAlertNotification, setShowAlertNotification] = useState(false);
  const [sendingAlert, setSendingAlert] = useState(false);

  // Street fare calculation states
  const [showStreetFareModal, setShowStreetFareModal] = useState(false);
  const [streetDestinationAddress, setStreetDestinationAddress] = useState('');
  const [streetAddressSuggestions, setStreetAddressSuggestions] = useState<Array<{
    address: string;
    latitude: number;
    longitude: number;
  }>>([]);
  const [streetSelectedAddress, setStreetSelectedAddress] = useState<{
    address: string;
    latitude: number;
    longitude: number;
  } | null>(null);
  const [streetFareResult, setStreetFareResult] = useState<{
    distance_km: number;
    fare_min: number;
    fare_max: number;
    is_night_or_weekend: boolean;
    base_fare: number;
    per_km_rate: number;
  } | null>(null);
  const [streetSearchingAddresses, setStreetSearchingAddresses] = useState(false);
  const [streetCalculatingFare, setStreetCalculatingFare] = useState(false);
  const streetSearchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const streetDestinationInputRef = useRef<any>(null);

  // Street work states
  const [currentLocation, setCurrentLocation] = useState<{latitude: number, longitude: number} | null>(null);
  const [currentStreet, setCurrentStreet] = useState<string>('');
  const [streetLoading, setStreetLoading] = useState(false);
  const [locationPermission, setLocationPermission] = useState(false);

  // Define all functions first
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

  const handleLogin = async () => {
    if (!loginUsername || !loginPassword) {
      Alert.alert('Error', 'Ingresa usuario y contraseña');
      return;
    }

    setLoginLoading(true);
    try {
      const response = await axios.post(`${API_BASE}/api/auth/login`, {
        username: loginUsername,
        password: loginPassword
      });

      const { access_token, user } = response.data;
      await AsyncStorage.setItem('token', access_token);
      await AsyncStorage.setItem('user', JSON.stringify(user));
      
      setCurrentUser(user);
      setLoginUsername('');
      setLoginPassword('');
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Usuario o contraseña incorrectos');
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = async () => {
    await AsyncStorage.removeItem('token');
    await AsyncStorage.removeItem('user');
    setCurrentUser(null);
  };

  // Load GPS preference on mount
  const loadGpsPreference = async () => {
    try {
      const savedGps = await AsyncStorage.getItem('gps_app');
      if (savedGps === 'waze' || savedGps === 'google') {
        setGpsApp(savedGps);
      }
    } catch (error) {
      console.log('Error loading GPS preference:', error);
    }
  };

  // Save GPS preference
  const saveGpsPreference = async (app: GpsApp) => {
    try {
      await AsyncStorage.setItem('gps_app', app);
      setGpsApp(app);
      Alert.alert('✓', `GPS cambiado a ${app === 'google' ? 'Google Maps' : 'Waze'}`);
    } catch (error) {
      console.log('Error saving GPS preference:', error);
    }
  };

  const registerForPushNotifications = async () => {
    try {
      const { status: existingStatus } = await Notifications.getPermissionsAsync();
      let finalStatus = existingStatus;

      if (existingStatus !== 'granted') {
        const { status } = await Notifications.requestPermissionsAsync();
        finalStatus = status;
      }

      if (finalStatus !== 'granted') {
        return;
      }

      const tokenData = await Notifications.getExpoPushTokenAsync({
        projectId: 'transport-meter',
      });
      setPushToken(tokenData.data);
    } catch (error) {
      console.log('Error getting push token:', error);
    }
  };

  const toggleNotifications = async () => {
    if (!pushToken) {
      Alert.alert('Error', 'No se pudo obtener el token de notificaciones');
      return;
    }

    try {
      if (notificationsEnabled) {
        await axios.delete(`${API_BASE}/api/notifications/unsubscribe/${pushToken}`);
      } else {
        await axios.post(`${API_BASE}/api/notifications/subscribe`, {
          push_token: pushToken,
          train_alerts: true,
          flight_alerts: true,
          threshold: 10,
        });
      }
      setNotificationsEnabled(!notificationsEnabled);
    } catch (error) {
      console.error('Error toggling notifications:', error);
    }
  };

  // Get current location and street name
  const getCurrentLocation = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Error', 'Se necesita permiso de ubicación');
        return null;
      }
      setLocationPermission(true);

      const location = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High
      });
      const coords = {
        latitude: location.coords.latitude,
        longitude: location.coords.longitude
      };
      setCurrentLocation(coords);

      // Get street name - always try backend Nominatim first (more reliable)
      let street = 'Calle desconocida';
      const token = await AsyncStorage.getItem('token');
      
      // Try backend Nominatim first (more reliable)
      try {
        const geoResponse = await axios.get(`${API_BASE}/api/geocode/reverse`, {
          params: { lat: coords.latitude, lng: coords.longitude },
          headers: { Authorization: `Bearer ${token}` },
          timeout: 5000
        });
        if (geoResponse.data.street && geoResponse.data.street !== 'Calle desconocida') {
          street = geoResponse.data.street;
        }
      } catch (backendError) {
        console.log('Backend geocode failed, trying expo location');
      }
      
      // Fallback to Expo Location if backend failed
      if (street === 'Calle desconocida') {
        try {
          const addresses = await Location.reverseGeocodeAsync(coords);
          if (addresses.length > 0) {
            const addr = addresses[0];
            const expoStreet = addr.street || addr.name || addr.district;
            if (expoStreet && expoStreet !== 'null' && expoStreet.trim() !== '') {
              street = expoStreet;
            }
          }
        } catch (geoError) {
          console.log('Expo geocoding also failed');
        }
      }
      
      setCurrentStreet(street);
      return { ...coords, street };
    } catch (error) {
      console.error('Error getting location:', error);
      Alert.alert('Error', 'No se pudo obtener la ubicación');
      return null;
    }
  };

  // Register street activity (load or unload)
  const registerActivity = async (action: 'load' | 'unload') => {
    // For 'load' action, open GPS immediately (before waiting for location/API)
    if (action === 'load') {
      openGpsApp();
    }
    
    setStreetLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const locationData = await getCurrentLocation();
      
      if (!locationData) {
        setStreetLoading(false);
        return;
      }

      const response = await axios.post(`${API_BASE}/api/street/activity`, {
        action,
        latitude: locationData.latitude,
        longitude: locationData.longitude,
        street_name: locationData.street
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      // Update active load state
      setHasActiveLoad(response.data.has_active_load);

      Alert.alert(
        '✓',
        `${action === 'load' ? 'Carga' : 'Descarga'} registrada en ${locationData.street}`
      );
      
      // Refresh street data
      fetchStreetData();
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo registrar la actividad');
    } finally {
      setStreetLoading(false);
    }
  };

  // Fetch check-in status
  const fetchCheckInStatus = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get<CheckInStatus>(`${API_BASE}/api/checkin/status`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setCheckInStatus(response.data);
    } catch (error) {
      console.error('Error fetching check-in status:', error);
    }
  }, []);

  // Fetch taxi status (filtered by time window)
  const fetchTaxiStatus = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/taxi/status?minutes=${timeWindow}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setTaxiStatus(response.data);
    } catch (error) {
      console.log('Error fetching taxi status:', error);
    }
  }, [timeWindow]);

  // Fetch queue status (people waiting) (filtered by time window)
  const fetchQueueStatus = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/queue/status?minutes=${timeWindow}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setQueueStatus(response.data);
    } catch (error) {
      console.log('Error fetching queue status:', error);
    }
  }, [timeWindow]);

  // Emergency alert functions
  const fetchActiveAlerts = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      if (!token) return;
      
      const response = await axios.get(`${API_BASE}/api/emergency/alerts`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      const alerts = response.data.alerts || [];
      setActiveAlerts(alerts);
      
      // Check if there are alerts from other users
      const otherAlerts = alerts.filter((a: any) => !a.is_own);
      if (otherAlerts.length > 0 && !showAlertNotification) {
        setShowAlertNotification(true);
      } else if (otherAlerts.length === 0) {
        setShowAlertNotification(false);
      }
    } catch (error) {
      console.log('Error fetching alerts:', error);
    }
  }, [showAlertNotification]);

  const fetchMyAlert = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      if (!token) return;
      
      const response = await axios.get(`${API_BASE}/api/emergency/my-alert`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (response.data.has_active_alert) {
        setMyActiveAlert(response.data.alert);
      } else {
        setMyActiveAlert(null);
      }
    } catch (error) {
      console.log('Error fetching my alert:', error);
    }
  }, []);

  const sendEmergencyAlert = async (alertType: 'companions' | 'companions_police') => {
    console.log('sendEmergencyAlert called, currentLocation:', currentLocation);
    
    // Try to get fresh location if we don't have one
    let alertLocation = currentLocation;
    
    if (!alertLocation) {
      try {
        console.log('No current location, trying to get fresh location...');
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === 'granted') {
          const loc = await Location.getCurrentPositionAsync({
            accuracy: Location.Accuracy.High
          });
          alertLocation = {
            latitude: loc.coords.latitude,
            longitude: loc.coords.longitude
          };
          setCurrentLocation(alertLocation);
          console.log('Got fresh location:', alertLocation);
        }
      } catch (error) {
        console.log('Error getting fresh location:', error);
      }
    }
    
    // If still no location, use Madrid center as fallback
    if (!alertLocation) {
      console.log('Using Madrid center as fallback location');
      alertLocation = { latitude: 40.4168, longitude: -3.7038 };
    }
    
    await doSendAlert(alertType, alertLocation);
  };

  const doSendAlert = async (alertType: 'companions' | 'companions_police', location: {latitude: number, longitude: number}) => {
    setSendingAlert(true);
    console.log('Sending emergency alert:', alertType, location);
    
    try {
      const token = await AsyncStorage.getItem('token');
      console.log('Token obtained:', token ? 'yes' : 'no');
      
      const response = await axios.post(`${API_BASE}/api/emergency/alert`, {
        alert_type: alertType,
        latitude: location.latitude,
        longitude: location.longitude
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      console.log('Alert response:', response.data);
      
      if (response.data.alert_id) {
        setMyActiveAlert({
          alert_id: response.data.alert_id,
          alert_type: alertType,
          latitude: location.latitude,
          longitude: location.longitude
        });
        
        setShowSosModal(false);
        
        // If police option, open phone dialer with 112
        if (alertType === 'companions_police') {
          // Try to open tel:112 on all platforms
          try {
            const phoneUrl = 'tel:112';
            const canOpen = await Linking.canOpenURL(phoneUrl);
            console.log('Can open tel:112:', canOpen);
            
            if (canOpen) {
              await Linking.openURL(phoneUrl);
            } else {
              // Fallback: show alert with number
              Alert.alert(
                '🚨 LLAMA AL 112',
                'Marca este número de emergencia: 112',
                [{ text: 'Entendido' }]
              );
            }
          } catch (phoneError) {
            console.log('Error opening phone:', phoneError);
            Alert.alert(
              '🚨 LLAMA AL 112',
              'No se pudo abrir el teléfono automáticamente.\n\nMarca manualmente: 112',
              [{ text: 'Entendido' }]
            );
          }
          
          // Show confirmation after a delay
          setTimeout(() => {
            Alert.alert('✅ Alerta enviada', 'Tus compañeros han sido notificados. Recuerda llamar al 112.');
          }, 1000);
        } else {
          Alert.alert('✅ Alerta enviada', 'Tus compañeros han sido notificados de tu situación.');
        }
      }
      
      // Force refresh alerts
      fetchActiveAlerts();
      
    } catch (error: any) {
      console.log('Error sending alert:', error);
      console.log('Error details:', error.response?.data || error.message);
      Alert.alert('Error', 'No se pudo enviar la alerta. Intenta de nuevo.');
    } finally {
      setSendingAlert(false);
    }
  };

  const resolveEmergencyAlert = async () => {
    if (!myActiveAlert) return;
    
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/emergency/resolve/${myActiveAlert.alert_id}`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      setMyActiveAlert(null);
      Alert.alert('Resuelto', 'Tu alerta ha sido marcada como resuelta.');
    } catch (error) {
      console.log('Error resolving alert:', error);
      Alert.alert('Error', 'No se pudo resolver la alerta.');
    }
  };

  const openAlertLocation = async (latitude: number, longitude: number, username: string) => {
    // Open GPS with exact coordinates for emergency location
    try {
      if (gpsApp === 'waze') {
        // Waze with coordinates - navigate directly to the point
        await Linking.openURL(`https://waze.com/ul?ll=${latitude},${longitude}&navigate=yes`);
      } else {
        // Google Maps with coordinates
        if (Platform.OS === 'ios') {
          const canOpen = await Linking.canOpenURL('comgooglemaps://');
          if (canOpen) {
            await Linking.openURL(`comgooglemaps://?daddr=${latitude},${longitude}&directionsmode=driving`);
            return;
          }
        } else if (Platform.OS === 'android') {
          const canOpen = await Linking.canOpenURL('google.navigation:');
          if (canOpen) {
            await Linking.openURL(`google.navigation:q=${latitude},${longitude}&mode=d`);
            return;
          }
        }
        // Fallback to web Google Maps with coordinates
        await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}&travelmode=driving`);
      }
    } catch (err) {
      console.error('Error opening GPS for alert location:', err);
      // Final fallback
      if (gpsApp === 'waze') {
        await Linking.openURL(`https://waze.com/ul?ll=${latitude},${longitude}&navigate=yes`);
      } else {
        await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${latitude},${longitude}&travelmode=driving`);
      }
    }
  };

  // ============ STREET FARE CALCULATION FUNCTIONS ============
  
  // Search street addresses with debounce
  const searchStreetAddresses = async (query: string) => {
    if (query.length < 3) {
      setStreetAddressSuggestions([]);
      return;
    }
    
    setStreetSearchingAddresses(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(`${API_BASE}/api/search-addresses`, {
        query,
        city: 'Madrid'
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      if (response.data.suggestions) {
        setStreetAddressSuggestions(response.data.suggestions);
      }
    } catch (error) {
      console.log('Error searching addresses:', error);
    } finally {
      setStreetSearchingAddresses(false);
    }
  };

  // Handle street address input change with debounce
  const handleStreetAddressChange = (text: string) => {
    setStreetDestinationAddress(text);
    setStreetSelectedAddress(null);
    setStreetFareResult(null);
    
    if (streetSearchTimeoutRef.current) {
      clearTimeout(streetSearchTimeoutRef.current);
    }
    
    streetSearchTimeoutRef.current = setTimeout(() => {
      const normalizedText = normalizeSpanishNumbers(text);
      if (normalizedText !== text) {
        setStreetDestinationAddress(normalizedText);
      }
      searchStreetAddresses(normalizedText);
    }, 500);
  };

  // Select a street address suggestion
  const selectStreetAddress = (suggestion: typeof streetAddressSuggestions[0]) => {
    setStreetSelectedAddress(suggestion);
    setStreetDestinationAddress(suggestion.address);
    setStreetAddressSuggestions([]);
  };

  // Calculate street fare based on distance and time
  const calculateStreetFare = async () => {
    if (!streetSelectedAddress || !currentLocation) {
      Alert.alert('Error', 'Selecciona una dirección de destino');
      return;
    }
    
    setStreetCalculatingFare(true);
    try {
      // Calculate distance using Haversine formula (approximate)
      const R = 6371; // Earth's radius in km
      const lat1 = currentLocation.latitude * Math.PI / 180;
      const lat2 = streetSelectedAddress.latitude * Math.PI / 180;
      const dLat = (streetSelectedAddress.latitude - currentLocation.latitude) * Math.PI / 180;
      const dLon = (streetSelectedAddress.longitude - currentLocation.longitude) * Math.PI / 180;
      
      const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                Math.cos(lat1) * Math.cos(lat2) *
                Math.sin(dLon/2) * Math.sin(dLon/2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      const distance_km = R * c;
      
      // Add 20% for real road distance (streets are not straight lines)
      const adjusted_distance = distance_km * 1.2;
      
      // Determine if it's night/weekend fare
      const now = new Date();
      const hour = now.getHours();
      const dayOfWeek = now.getDay(); // 0 = Sunday, 6 = Saturday
      
      const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
      const isNightTime = hour >= 21 || hour < 6;
      const isNightOrWeekend = isWeekend || isNightTime;
      
      let base_fare: number;
      let per_km_rate: number;
      
      if (isNightOrWeekend) {
        // Night/Weekend fare: 3.20€ + 1.50€/km
        base_fare = 3.20;
        per_km_rate = 1.50;
      } else {
        // Day fare (Mon-Fri 6:00-21:00): 2.50€ + 1.20€/km
        base_fare = 2.50;
        per_km_rate = 1.20;
      }
      
      const fare_min = base_fare + (adjusted_distance * per_km_rate);
      const fare_max = fare_min * 1.05; // +5%
      
      setStreetFareResult({
        distance_km: adjusted_distance,
        fare_min: fare_min,
        fare_max: fare_max,
        is_night_or_weekend: isNightOrWeekend,
        base_fare: base_fare,
        per_km_rate: per_km_rate
      });
      
    } catch (error) {
      console.log('Error calculating fare:', error);
      Alert.alert('Error', 'No se pudo calcular la tarifa');
    } finally {
      setStreetCalculatingFare(false);
    }
  };

  // Open GPS for street fare destination
  const openStreetFareGps = () => {
    if (streetSelectedAddress) {
      openGpsNavigation(
        streetSelectedAddress.latitude,
        streetSelectedAddress.longitude,
        streetSelectedAddress.address
      );
    }
  };

  // Close street fare modal and register load activity
  const handleStreetFareComplete = async () => {
    // Register the load activity
    await registerActivity('load');
    
    // Open GPS if we have a destination
    if (streetSelectedAddress) {
      openStreetFareGps();
    }
    
    // Close modal and reset state
    setShowStreetFareModal(false);
    setStreetDestinationAddress('');
    setStreetAddressSuggestions([]);
    setStreetSelectedAddress(null);
    setStreetFareResult(null);
  };

  // Taxi question state (for entry)
  const [showTaxiQuestion, setShowTaxiQuestion] = useState(false);
  const [pendingCheckIn, setPendingCheckIn] = useState<{
    locationType: 'station' | 'terminal';
    locationName: string;
  } | null>(null);

  // Queue question state (for exit - people waiting)
  const [showQueueQuestion, setShowQueueQuestion] = useState(false);
  const [pendingCheckOut, setPendingCheckOut] = useState<{
    locationType: 'station' | 'terminal';
    locationName: string;
  } | null>(null);

  // Destination/Fare modal state (for terminal exit)
  const [showDestinationModal, setShowDestinationModal] = useState(false);
  const [destinationAddress, setDestinationAddress] = useState('');
  const [addressSuggestions, setAddressSuggestions] = useState<Array<{
    address: string;
    latitude: number;
    longitude: number;
    is_inside_m30: boolean;
  }>>([]);
  const [searchingAddresses, setSearchingAddresses] = useState(false);
  const [selectedAddress, setSelectedAddress] = useState<{
    address: string;
    latitude: number;
    longitude: number;
    is_inside_m30: boolean;
  } | null>(null);
  const [fareResult, setFareResult] = useState<{
    tarifa: string;
    suplemento: string;
    isInsideM30: boolean;
    latitude: number;
    longitude: number;
    addressName: string;
  } | null>(null);
  const [calculatingFare, setCalculatingFare] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const destinationInputRef = React.useRef<any>(null);
  const searchTimeoutRef = React.useRef<any>(null);

  // Function to convert Spanish number words to digits
  const normalizeSpanishNumbers = (text: string): string => {
    const numberWords: { [key: string]: string } = {
      // Unidades
      'cero': '0', 'uno': '1', 'una': '1', 'dos': '2', 'tres': '3', 'cuatro': '4',
      'cinco': '5', 'seis': '6', 'siete': '7', 'ocho': '8', 'nueve': '9',
      'diez': '10', 'once': '11', 'doce': '12', 'trece': '13', 'catorce': '14',
      'quince': '15', 'dieciséis': '16', 'dieciseis': '16', 'diecisiete': '17',
      'dieciocho': '18', 'diecinueve': '19',
      // Decenas
      'veinte': '20', 'veintiuno': '21', 'veintiuna': '21', 'veintidos': '22', 'veintidós': '22',
      'veintitres': '23', 'veintitrés': '23', 'veinticuatro': '24', 'veinticinco': '25',
      'veintiseis': '26', 'veintiséis': '26', 'veintisiete': '27', 'veintiocho': '28',
      'veintinueve': '29', 'treinta': '30', 'cuarenta': '40', 'cincuenta': '50',
      'sesenta': '60', 'setenta': '70', 'ochenta': '80', 'noventa': '90',
      // Centenas
      'cien': '100', 'ciento': '100', 'doscientos': '200', 'doscientas': '200',
      'trescientos': '300', 'trescientas': '300', 'cuatrocientos': '400', 'cuatrocientas': '400',
      'quinientos': '500', 'quinientas': '500', 'seiscientos': '600', 'seiscientas': '600',
      'setecientos': '700', 'setecientas': '700', 'ochocientos': '800', 'ochocientas': '800',
      'novecientos': '900', 'novecientas': '900',
      // Otros
      'primero': '1', 'primera': '1', 'segundo': '2', 'segunda': '2',
      'tercero': '3', 'tercera': '3', 'cuarto': '4', 'cuarta': '4',
      'quinto': '5', 'quinta': '5', 'sexto': '6', 'sexta': '6',
      'séptimo': '7', 'septimo': '7', 'séptima': '7', 'septima': '7',
      'octavo': '8', 'octava': '8', 'noveno': '9', 'novena': '9',
      'décimo': '10', 'decimo': '10', 'décima': '10', 'decima': '10',
    };
    
    let result = text.toLowerCase();
    
    // Handle compound numbers like "treinta y uno" -> "31"
    result = result.replace(/treinta y uno/gi, '31').replace(/treinta y una/gi, '31');
    result = result.replace(/treinta y dos/gi, '32').replace(/treinta y tres/gi, '33');
    result = result.replace(/treinta y cuatro/gi, '34').replace(/treinta y cinco/gi, '35');
    result = result.replace(/treinta y seis/gi, '36').replace(/treinta y siete/gi, '37');
    result = result.replace(/treinta y ocho/gi, '38').replace(/treinta y nueve/gi, '39');
    
    result = result.replace(/cuarenta y uno/gi, '41').replace(/cuarenta y una/gi, '41');
    result = result.replace(/cuarenta y dos/gi, '42').replace(/cuarenta y tres/gi, '43');
    result = result.replace(/cuarenta y cuatro/gi, '44').replace(/cuarenta y cinco/gi, '45');
    result = result.replace(/cuarenta y seis/gi, '46').replace(/cuarenta y siete/gi, '47');
    result = result.replace(/cuarenta y ocho/gi, '48').replace(/cuarenta y nueve/gi, '49');
    
    result = result.replace(/cincuenta y uno/gi, '51').replace(/cincuenta y una/gi, '51');
    result = result.replace(/cincuenta y dos/gi, '52').replace(/cincuenta y tres/gi, '53');
    result = result.replace(/cincuenta y cuatro/gi, '54').replace(/cincuenta y cinco/gi, '55');
    result = result.replace(/cincuenta y seis/gi, '56').replace(/cincuenta y siete/gi, '57');
    result = result.replace(/cincuenta y ocho/gi, '58').replace(/cincuenta y nueve/gi, '59');
    
    result = result.replace(/sesenta y uno/gi, '61').replace(/sesenta y una/gi, '61');
    result = result.replace(/sesenta y dos/gi, '62').replace(/sesenta y tres/gi, '63');
    result = result.replace(/sesenta y cuatro/gi, '64').replace(/sesenta y cinco/gi, '65');
    result = result.replace(/sesenta y seis/gi, '66').replace(/sesenta y siete/gi, '67');
    result = result.replace(/sesenta y ocho/gi, '68').replace(/sesenta y nueve/gi, '69');
    
    result = result.replace(/setenta y uno/gi, '71').replace(/setenta y una/gi, '71');
    result = result.replace(/setenta y dos/gi, '72').replace(/setenta y tres/gi, '73');
    result = result.replace(/setenta y cuatro/gi, '74').replace(/setenta y cinco/gi, '75');
    result = result.replace(/setenta y seis/gi, '76').replace(/setenta y siete/gi, '77');
    result = result.replace(/setenta y ocho/gi, '78').replace(/setenta y nueve/gi, '79');
    
    result = result.replace(/ochenta y uno/gi, '81').replace(/ochenta y una/gi, '81');
    result = result.replace(/ochenta y dos/gi, '82').replace(/ochenta y tres/gi, '83');
    result = result.replace(/ochenta y cuatro/gi, '84').replace(/ochenta y cinco/gi, '85');
    result = result.replace(/ochenta y seis/gi, '86').replace(/ochenta y siete/gi, '87');
    result = result.replace(/ochenta y ocho/gi, '88').replace(/ochenta y nueve/gi, '89');
    
    result = result.replace(/noventa y uno/gi, '91').replace(/noventa y una/gi, '91');
    result = result.replace(/noventa y dos/gi, '92').replace(/noventa y tres/gi, '93');
    result = result.replace(/noventa y cuatro/gi, '94').replace(/noventa y cinco/gi, '95');
    result = result.replace(/noventa y seis/gi, '96').replace(/noventa y siete/gi, '97');
    result = result.replace(/noventa y ocho/gi, '98').replace(/noventa y nueve/gi, '99');
    
    // Replace individual number words (sorted by length to avoid partial replacements)
    const sortedWords = Object.keys(numberWords).sort((a, b) => b.length - a.length);
    for (const word of sortedWords) {
      const regex = new RegExp(`\\b${word}\\b`, 'gi');
      result = result.replace(regex, numberWords[word]);
    }
    
    // Capitalize first letter
    if (result.length > 0) {
      result = result.charAt(0).toUpperCase() + result.slice(1);
    }
    
    return result;
  };

  // Search addresses with debounce
  const searchAddresses = async (query: string) => {
    if (query.length < 3) {
      setAddressSuggestions([]);
      return;
    }
    
    setSearchingAddresses(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(`${API_BASE}/api/search-addresses`, {
        query,
        city: 'Madrid'
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      setAddressSuggestions(response.data.suggestions || []);
    } catch (error) {
      console.log('Error searching addresses:', error);
      setAddressSuggestions([]);
    } finally {
      setSearchingAddresses(false);
    }
  };

  // Handle address input change with debounce
  const handleAddressChange = (text: string) => {
    setDestinationAddress(text);
    setSelectedAddress(null);
    setFareResult(null);
    
    // Clear previous timeout
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    
    // Set new timeout for search - normalize numbers before searching
    searchTimeoutRef.current = setTimeout(() => {
      const normalizedText = normalizeSpanishNumbers(text);
      // Update the input if normalization changed something
      if (normalizedText !== text) {
        setDestinationAddress(normalizedText);
      }
      searchAddresses(normalizedText);
    }, 500);
  };

  // Select address from suggestions
  const selectAddress = (suggestion: typeof addressSuggestions[0]) => {
    setSelectedAddress(suggestion);
    setDestinationAddress(suggestion.address);
    setAddressSuggestions([]);
    
    // Calculate fare immediately
    calculateFareFromAddress(suggestion);
  };

  // Voice input function with number normalization
  const startVoiceInput = () => {
    if (Platform.OS === 'web') {
      // Use Web Speech API on web
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.lang = 'es-ES';
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;
        
        recognition.onstart = () => {
          setIsListening(true);
        };
        
        recognition.onresult = (event: any) => {
          const rawTranscript = event.results[0][0].transcript;
          // Normalize Spanish numbers to digits
          const normalizedTranscript = normalizeSpanishNumbers(rawTranscript);
          setDestinationAddress(normalizedTranscript);
          setIsListening(false);
          // Search for addresses after voice input
          searchAddresses(normalizedTranscript);
        };
        
        recognition.onerror = () => {
          setIsListening(false);
          Alert.alert('Error', 'No se pudo reconocer la voz. Intenta de nuevo.');
        };
        
        recognition.onend = () => {
          setIsListening(false);
        };
        
        recognition.start();
      } else {
        Alert.alert('No disponible', 'El reconocimiento de voz no está disponible en este navegador.');
      }
    } else {
      // On mobile, focus the input and show a hint to use the keyboard's voice input
      if (destinationInputRef.current) {
        destinationInputRef.current.focus();
      }
      Alert.alert(
        '🎤 Dictado por voz',
        'Usa el botón de micrófono en tu teclado para dictar la dirección.',
        [{ text: 'Entendido' }]
      );
    }
  };

  // Handle check-in/check-out with questions
  const handleCheckIn = async (locationType: 'station' | 'terminal', locationName: string, action: 'entry' | 'exit') => {
    if (checkInLoading) return;
    
    // For 'exit' action, show queue question modal
    if (action === 'exit') {
      setPendingCheckOut({ locationType, locationName });
      setShowQueueQuestion(true);
      return;
    }
    
    // For 'entry' action, show taxi question modal
    setPendingCheckIn({ locationType, locationName });
    setShowTaxiQuestion(true);
  };

  // Handle queue answer (for exit)
  const handleQueueAnswer = async (answer: string | null) => {
    setShowQueueQuestion(false);
    if (pendingCheckOut) {
      await performCheckIn(pendingCheckOut.locationType, pendingCheckOut.locationName, 'exit', null, answer);
      
      // If terminal exit, show destination modal for fare calculation
      if (pendingCheckOut.locationType === 'terminal') {
        setShowDestinationModal(true);
        setDestinationAddress('');
        setAddressSuggestions([]);
        setSelectedAddress(null);
        setFareResult(null);
      } else {
        // For stations, just open GPS
        setPendingCheckOut(null);
        openGpsApp();
      }
    }
  };

  // Calculate fare from selected address
  const calculateFareFromAddress = (address: { latitude: number; longitude: number; address: string; is_inside_m30: boolean }) => {
    // Get current time and day
    const now = new Date();
    const hour = now.getHours();
    const dayOfWeek = now.getDay(); // 0 = Sunday, 6 = Saturday
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const isDaytime = hour >= 6 && hour < 21;
    
    let tarifa: string;
    let suplemento: string;
    
    if (address.is_inside_m30) {
      tarifa = 'Tarifa 4';
      suplemento = '33';
    } else {
      // Outside M30
      if (!isWeekend && isDaytime) {
        // Weekday daytime (6:00-21:00)
        tarifa = 'Tarifa 3 + Tarifa 1 cambio automático';
        suplemento = '22 + Tarifa 1';
      } else {
        // Weekday night (21:00-6:00) or weekend
        tarifa = 'Tarifa 3 + Tarifa 2 cambio automático';
        suplemento = '22 + Tarifa 2';
      }
    }
    
    setFareResult({ 
      tarifa, 
      suplemento, 
      isInsideM30: address.is_inside_m30,
      latitude: address.latitude,
      longitude: address.longitude,
      addressName: address.address
    });
  };

  // Calculate fare based on destination (manual search)
  const calculateFare = async () => {
    if (!destinationAddress.trim()) return;
    
    // If already selected from suggestions, use that
    if (selectedAddress) {
      calculateFareFromAddress(selectedAddress);
      return;
    }
    
    setCalculatingFare(true);
    try {
      // Search for addresses first
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(`${API_BASE}/api/search-addresses`, {
        query: destinationAddress,
        city: 'Madrid'
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      const suggestions = response.data.suggestions || [];
      
      if (suggestions.length === 0) {
        Alert.alert('Error', 'No se encontraron direcciones. Por favor, verifica y corrige la dirección.');
        return;
      }
      
      if (suggestions.length === 1) {
        // Only one result, use it directly
        selectAddress(suggestions[0]);
      } else {
        // Multiple results, show suggestions
        setAddressSuggestions(suggestions);
      }
    } catch (error) {
      console.error('Error calculating fare:', error);
      Alert.alert('Error', 'No se pudo buscar la dirección. Verifica la dirección.');
    } finally {
      setCalculatingFare(false);
    }
  };

  // Old calculate fare function - keeping for backward compatibility
  const calculateFareOld = async () => {
    if (!destinationAddress.trim()) return;
    
    setCalculatingFare(true);
    try {
      // Geocode the destination address
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(`${API_BASE}/api/geocode-address`, {
        address: destinationAddress,
        city: 'Madrid'
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      const { is_inside_m30, latitude, longitude, address } = response.data;
      
      // Get current time and day
      const now = new Date();
      const hour = now.getHours();
      const dayOfWeek = now.getDay(); // 0 = Sunday, 6 = Saturday
      const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
      const isDaytime = hour >= 6 && hour < 21;
      
      let tarifa: string;
      let suplemento: string;
      
      if (is_inside_m30) {
        tarifa = 'Tarifa 4';
        suplemento = '33';
      } else {
        // Outside M30
        if (!isWeekend && isDaytime) {
          // Weekday daytime (6:00-21:00)
          tarifa = 'Tarifa 3 + Tarifa 1 cambio automático';
          suplemento = '22 + Tarifa 1';
        } else {
          // Weekday night (21:00-6:00) or weekend
          tarifa = 'Tarifa 3 + Tarifa 2 cambio automático';
          suplemento = '22 + Tarifa 2';
        }
      }
      
      setFareResult({ 
        tarifa, 
        suplemento, 
        isInsideM30: is_inside_m30,
        latitude,
        longitude,
        addressName: address
      });
    } catch (error) {
      console.error('Error calculating fare:', error);
      Alert.alert('Error', 'No se pudo calcular la tarifa. Verifica la dirección.');
    } finally {
      setCalculatingFare(false);
    }
  };

  // Navigate to destination with GPS
  const navigateToDestination = () => {
    if (fareResult) {
      openGpsNavigation(fareResult.latitude, fareResult.longitude, fareResult.addressName);
    }
    setShowDestinationModal(false);
    setDestinationAddress('');
    setFareResult(null);
    setPendingCheckOut(null);
  };

  // Close destination modal and open GPS (without destination)
  const closeDestinationModal = () => {
    setShowDestinationModal(false);
    setDestinationAddress('');
    setFareResult(null);
    setPendingCheckOut(null);
    openGpsApp();
  };

  // Handle taxi answer (for entry)
  const handleTaxiAnswer = (answer: string | null) => {
    setShowTaxiQuestion(false);
    if (pendingCheckIn) {
      performCheckIn(pendingCheckIn.locationType, pendingCheckIn.locationName, 'entry', answer, null);
      setPendingCheckIn(null);
    }
  };

  // Actual check-in logic
  const performCheckIn = async (locationType: 'station' | 'terminal', locationName: string, action: 'entry' | 'exit', taxiAnswer: string | null, queueAnswer: string | null = null) => {
    setCheckInLoading(true);
    try {
      // Get current location
      let location = currentLocation;
      if (!location) {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === 'granted') {
          const loc = await Location.getCurrentPositionAsync({});
          location = {
            latitude: loc.coords.latitude,
            longitude: loc.coords.longitude
          };
          setCurrentLocation(location);
        }
      }
      
      if (!location) {
        Alert.alert('Error', 'No se pudo obtener la ubicación GPS');
        setCheckInLoading(false);
        return;
      }
      
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(`${API_BASE}/api/checkin`, {
        location_type: locationType,
        location_name: locationName,
        action: action,
        latitude: location.latitude,
        longitude: location.longitude,
        taxi_status: taxiAnswer,
        queue_status: queueAnswer
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Update check-in status
      if (response.data.is_checked_in) {
        setCheckInStatus({
          is_checked_in: true,
          location_type: locationType,
          location_name: locationName,
          entry_time: new Date().toISOString()
        });
      } else {
        setCheckInStatus({
          is_checked_in: false,
          location_type: null,
          location_name: null,
          entry_time: null
        });
      }
      
      Alert.alert('✓', response.data.message);
      
      // Refresh street data to show new activity
      fetchStreetData();
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo registrar');
    } finally {
      setCheckInLoading(false);
    }
  };

  // Fetch load status (for load/unload toggle button)
  const fetchLoadStatus = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/street/load-status`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setHasActiveLoad(response.data.has_active_load);
    } catch (error) {
      console.error('Error fetching load status:', error);
    }
  }, []);

  // Fetch street work data - only called manually or on interval, not on every location change
  const fetchStreetData = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      
      // Build params with user location if available
      const params: any = { minutes: timeWindow };
      if (currentLocation) {
        params.user_lat = currentLocation.latitude;
        params.user_lng = currentLocation.longitude;
        params.max_distance_km = 4.0;  // ~5 min by car
      }
      
      const response = await axios.get<StreetWorkData>(`${API_BASE}/api/street/data`, {
        params,
        headers: { Authorization: `Bearer ${token}` }
      });
      setStreetData(response.data);
      
      // Also fetch load status
      await fetchLoadStatus();
    } catch (error) {
      console.error('Error fetching street data:', error);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeWindow, fetchLoadStatus]); // currentLocation excluded to prevent constant refetching - location is read at call time

  const fetchData = useCallback(async () => {
    if (!currentUser) return; // Don't fetch if not logged in
    try {
      if (activeTab === 'trains') {
        // Fetch trains with retry for Chamartín
        let retryCount = 0;
        const maxRetries = 5;
        let trainResponse: TrainComparison | null = null;
        
        while (retryCount < maxRetries) {
          const response = await axios.get<TrainComparison>(`${API_BASE}/api/trains`, {
            params: { shift }
          });
          
          trainResponse = response.data;
          
          // Check if Chamartín has data
          const chamartinHasData = response.data.chamartin?.arrivals?.length > 0;
          
          if (chamartinHasData) {
            console.log(`[Trains] Chamartín data received (${response.data.chamartin.arrivals.length} trains)`);
            break;
          }
          
          retryCount++;
          console.log(`[Trains] Chamartín sin datos, reintentando (${retryCount}/${maxRetries})...`);
          
          if (retryCount < maxRetries) {
            // Wait 2 seconds before retrying
            await new Promise(resolve => setTimeout(resolve, 2000));
          }
        }
        
        if (trainResponse) {
          setTrainData(trainResponse);
          
          if (trainResponse.chamartin?.arrivals?.length === 0) {
            console.log('[Trains] Chamartín: No se pudieron obtener datos después de varios intentos');
          }
        }
      } else if (activeTab === 'flights') {
        const response = await axios.get<FlightComparison>(`${API_BASE}/api/flights`);
        setFlightData(response.data);
      } else if (activeTab === 'street') {
        await fetchStreetData();
        await fetchTaxiStatus();
        await fetchQueueStatus();
      }
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [activeTab, shift, currentUser, timeWindow, fetchStreetData, fetchTaxiStatus, fetchQueueStatus]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchData();
  }, [fetchData]);

  // Check for existing session on mount
  useEffect(() => {
    checkExistingSession();
    loadGpsPreference();
  }, []);

  // Heartbeat to keep backend alive (every 30 seconds)
  useEffect(() => {
    const keepAlive = async () => {
      try {
        await axios.get(`${API_BASE}/api/health`);
        console.log('[Heartbeat] Backend alive');
      } catch (error) {
        console.log('[Heartbeat] Backend may be sleeping, waking up...');
      }
    };

    // Initial ping
    keepAlive();
    
    // Ping every 30 seconds to keep backend awake
    const heartbeatInterval = setInterval(keepAlive, 30000);
    
    return () => clearInterval(heartbeatInterval);
  }, []);

  // Register for notifications
  useEffect(() => {
    if (currentUser) {
      registerForPushNotifications();
    }
  }, [currentUser]);

  // Fetch check-in status when user logs in
  useEffect(() => {
    if (currentUser) {
      fetchCheckInStatus();
    }
  }, [currentUser, fetchCheckInStatus]);

  // Fetch data when logged in or when time window changes
  useEffect(() => {
    if (currentUser) {
      setLoading(true);
      fetchData();

      // Auto-refresh every 30 seconds for real-time data
      const interval = setInterval(fetchData, 30000);
      return () => clearInterval(interval);
    }
  }, [activeTab, fetchData, currentUser, timeWindow]);

  // Request location permission and track location - ALWAYS (for emergency alerts)
  useEffect(() => {
    let isMounted = true;
    let intervalId: NodeJS.Timeout | null = null;
    
    const updateLocation = async () => {
      try {
        const location = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.High
        });
        if (isMounted) {
          setCurrentLocation({
            latitude: location.coords.latitude,
            longitude: location.coords.longitude
          });
          console.log('Location updated:', location.coords.latitude, location.coords.longitude);
        }
      } catch (error) {
        console.log('Location update error:', error);
      }
    };
    
    const startLocationTracking = async () => {
      // Request location permission as soon as user logs in
      if (currentUser) {
        try {
          console.log('Requesting location permission...');
          const { status } = await Location.requestForegroundPermissionsAsync();
          console.log('Location permission status:', status);
          
          if (status !== 'granted') {
            Alert.alert(
              'Permiso de ubicación',
              'Para usar la función de emergencia y otras características, necesitamos acceso a tu ubicación.',
              [
                { text: 'Entendido' }
              ]
            );
            return;
          }
          if (!isMounted) return;
          setLocationPermission(true);
          
          // Get initial location immediately
          await updateLocation();
          
          // Start polling for location updates every 10 seconds (works on all platforms)
          intervalId = setInterval(updateLocation, 10000);
          
        } catch (error) {
          console.error('Error starting location tracking:', error);
        }
      }
    };
    
    startLocationTracking();
    
    // Cleanup
    return () => {
      isMounted = false;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [currentUser]);

  // Poll for emergency alerts every 10 seconds
  useEffect(() => {
    if (!currentUser) return;
    
    // Initial fetch
    fetchActiveAlerts();
    fetchMyAlert();
    
    // Set up polling
    const alertInterval = setInterval(() => {
      fetchActiveAlerts();
      fetchMyAlert();
    }, 10000); // Check every 10 seconds
    
    return () => {
      clearInterval(alertInterval);
    };
  }, [currentUser, fetchActiveAlerts, fetchMyAlert]);

  const formatLastUpdate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString('es-ES', { 
      hour: '2-digit', 
      minute: '2-digit',
      timeZone: 'Europe/Madrid'
    });
  };

  // Format time for taxi status display
  const formatTime = (isoString: string | null | undefined) => {
    if (!isoString) return '';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString('es-ES', { 
        hour: '2-digit', 
        minute: '2-digit',
        timeZone: 'Europe/Madrid'
      });
    } catch {
      return '';
    }
  };

  // Show loading while checking auth
  if (!authChecked) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor="#0F172A" />
        <View style={styles.authLoadingContainer}>
          <ActivityIndicator size="large" color="#6366F1" />
          <Text style={styles.authLoadingText}>Cargando...</Text>
        </View>
      </SafeAreaView>
    );
  }

  // Show login screen if not authenticated
  if (!currentUser) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar barStyle="light-content" backgroundColor="#0F172A" />
        <KeyboardAvoidingView 
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.loginScreenContainer}
        >
          <View style={styles.loginScreenContent}>
            {/* Logo/Header */}
            <View style={styles.loginHeader}>
              <View style={styles.loginLogoContainer}>
                <Ionicons name="train" size={40} color="#6366F1" />
                <Ionicons name="airplane" size={40} color="#10B981" style={{ marginLeft: -10 }} />
              </View>
              <Text style={styles.loginAppTitle}>TransportMeter</Text>
              <Text style={styles.loginAppSubtitle}>Frecuencia de llegadas en Madrid</Text>
            </View>

            {/* Login Form */}
            <View style={styles.loginFormContainer}>
              <Text style={styles.loginFormTitle}>Iniciar Sesión</Text>
              
              <View style={styles.inputContainer}>
                <Ionicons name="person-outline" size={20} color="#64748B" style={styles.inputIcon} />
                <TextInput
                  style={styles.loginScreenInput}
                  placeholder="Nombre de usuario"
                  placeholderTextColor="#64748B"
                  value={loginUsername}
                  onChangeText={setLoginUsername}
                  autoCapitalize="none"
                />
              </View>

              <View style={styles.inputContainer}>
                <Ionicons name="lock-closed-outline" size={20} color="#64748B" style={styles.inputIcon} />
                <TextInput
                  style={styles.loginScreenInput}
                  placeholder="Contraseña"
                  placeholderTextColor="#64748B"
                  value={loginPassword}
                  onChangeText={setLoginPassword}
                  secureTextEntry
                />
              </View>

              <TouchableOpacity 
                style={styles.loginScreenButton}
                onPress={handleLogin}
                disabled={loginLoading}
              >
                {loginLoading ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : (
                  <>
                    <Ionicons name="log-in-outline" size={20} color="#FFFFFF" />
                    <Text style={styles.loginScreenButtonText}>Entrar</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>

            {/* Footer */}
            <Text style={styles.loginFooter}>
              Acceso solo para usuarios registrados
            </Text>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    );
  }

  const renderStationCard = (station: StationData, stationKey: string) => {
    const isWinner = timeWindow === 30 ? station.is_winner_30min : station.is_winner_60min;
    const arrivals = timeWindow === 30 ? station.total_next_30min : station.total_next_60min;
    const stationShortName = stationKey === 'atocha' ? 'Atocha' : 'Chamartín';
    const taxiExits = streetData?.exits_by_station?.[stationShortName] || 0;

    // Filter arrivals to only show those within the selected time window
    const now = new Date();
    const filteredArrivals = station.arrivals.filter(arrival => {
      try {
        const [hours, minutes] = arrival.time.split(':').map(Number);
        const arrivalDate = new Date();
        arrivalDate.setHours(hours, minutes, 0, 0);
        
        // Handle day rollover
        if (arrivalDate.getTime() < now.getTime() - 2 * 60 * 60 * 1000) {
          arrivalDate.setDate(arrivalDate.getDate() + 1);
        }
        
        const diffMinutes = (arrivalDate.getTime() - now.getTime()) / (1000 * 60);
        return diffMinutes >= 0 && diffMinutes <= timeWindow;
      } catch {
        return false;
      }
    });

    return (
      <View
        key={stationKey}
        style={[
          styles.stationCard,
          isWinner && styles.winnerCard,
        ]}
      >
        {isWinner && (
          <View style={styles.winnerBadge}>
            <Ionicons name="trophy" size={16} color="#FFFFFF" />
            <Text style={styles.winnerBadgeText}>MÁS FRECUENCIA</Text>
          </View>
        )}
        <View style={styles.stationHeader}>
          <Ionicons name="train" size={28} color={isWinner ? '#F59E0B' : '#6366F1'} />
          <Text style={[styles.stationName, isWinner && styles.winnerText]}>
            {stationShortName}
          </Text>
        </View>
        <View style={styles.arrivalCount}>
          <Text style={[styles.arrivalNumber, isWinner && styles.winnerNumber]}>
            {arrivals}
          </Text>
          <Text style={styles.arrivalLabel}>
            trenes en {timeWindow} min
          </Text>
        </View>
        
        {/* Salidas de taxistas en ventana anterior */}
        <View style={styles.taxiExitsContainer}>
          <Ionicons name="car" size={18} color="#10B981" />
          <Text style={styles.taxiExitsText}>
            {taxiExits} salidas taxi (vent. anterior)
          </Text>
        </View>
        
        {/* Hora pico del día */}
        {station.peak_hour && (
          <View style={styles.peakHourContainer}>
            <Ionicons name="time" size={16} color="#F59E0B" />
            <Text style={styles.peakHourText}>
              Hora pico: {station.peak_hour.start_hour} - {station.peak_hour.end_hour}
            </Text>
            <View style={styles.peakHourCount}>
              <Text style={styles.peakHourCountText}>{station.peak_hour.count}</Text>
            </View>
          </View>
        )}
        
        {/* Lista de llegadas - muestra filtradas o las primeras si es horario nocturno */}
        <View style={styles.arrivalsList}>
          {(filteredArrivals.length > 0 ? filteredArrivals : station.arrivals).slice(0, 5).map((arrival, index) => (
            <View key={index} style={styles.arrivalItem}>
              <View style={styles.arrivalTime}>
                <Text style={[
                  styles.timeText,
                  arrival.delay_minutes && arrival.delay_minutes > 0 && styles.delayedTimeText
                ]}>
                  {arrival.time}
                </Text>
                {arrival.delay_minutes && arrival.delay_minutes > 0 && arrival.scheduled_time && (
                  <Text style={styles.scheduledTimeText}>
                    ({arrival.scheduled_time})
                  </Text>
                )}
              </View>
              <View style={styles.arrivalInfo}>
                <View style={styles.trainTypeRow}>
                  <Text style={styles.trainType}>{arrival.train_type}</Text>
                  {arrival.delay_minutes && arrival.delay_minutes > 0 && (
                    <View style={styles.delayBadge}>
                      <Text style={styles.delayText}>+{arrival.delay_minutes}'</Text>
                    </View>
                  )}
                </View>
                <Text style={styles.originText} numberOfLines={1}>
                  {arrival.origin}
                </Text>
              </View>
              <View style={styles.platformBadge}>
                <Text style={styles.platformText}>
                  {arrival.platform || '-'}
                </Text>
              </View>
            </View>
          ))}
        </View>
        
        {/* Check-in/Check-out Button */}
        {checkInStatus?.is_checked_in && checkInStatus.location_type === 'station' && checkInStatus.location_name === stationShortName ? (
          <TouchableOpacity
            style={[styles.checkInButton, styles.checkOutButton]}
            onPress={() => handleCheckIn('station', stationShortName, 'exit')}
            disabled={checkInLoading}
          >
            <Ionicons name="exit-outline" size={20} color="#FFFFFF" />
            <Text style={styles.checkInButtonText}>
              {checkInLoading ? 'Registrando...' : 'SALIR DE ESTACIÓN'}
            </Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={styles.checkInButton}
            onPress={() => handleCheckIn('station', stationShortName, 'entry')}
            disabled={checkInLoading || (checkInStatus?.is_checked_in || false)}
          >
            <Ionicons name="enter-outline" size={20} color="#FFFFFF" />
            <Text style={styles.checkInButtonText}>
              {checkInLoading ? 'Registrando...' : 'ENTRAR EN ESTACIÓN'}
            </Text>
          </TouchableOpacity>
        )}
        
        {/* Taxi status display */}
        {taxiStatus[`station_${stationShortName}`] && (
          <View style={styles.taxiStatusContainer}>
            <Ionicons name="car" size={16} color="#F59E0B" />
            <Text style={styles.taxiStatusText}>
              Taxis: {taxiStatus[`station_${stationShortName}`].taxi_status === 'poco' ? '🟢 Pocos' : 
                     taxiStatus[`station_${stationShortName}`].taxi_status === 'normal' ? '🟡 Normal' : '🔴 Muchos'}
            </Text>
            <Text style={styles.taxiTimeText}>
              ({formatTime(taxiStatus[`station_${stationShortName}`].reported_at)} por {taxiStatus[`station_${stationShortName}`].reported_by})
            </Text>
          </View>
        )}
        
        {/* Queue status display (people waiting) */}
        {queueStatus[`station_${stationShortName}`] && (
          <View style={styles.queueStatusContainer}>
            <Ionicons name="people" size={16} color="#6366F1" />
            <Text style={styles.taxiStatusText}>
              Gente: {queueStatus[`station_${stationShortName}`].queue_status === 'poco' ? '🔴 Poca' : 
                     queueStatus[`station_${stationShortName}`].queue_status === 'normal' ? '🟡 Normal' : '🟢 Mucha'}
            </Text>
            <Text style={styles.taxiTimeText}>
              ({formatTime(queueStatus[`station_${stationShortName}`].reported_at)} por {queueStatus[`station_${stationShortName}`].reported_by})
            </Text>
          </View>
        )}
      </View>
    );
  };

  // Terminal groups configuration
  const terminalGroups = [
    { name: 'T1', terminals: ['T1'], zoneName: 'Zona T1' },
    { name: 'T2-T3', terminals: ['T2', 'T3'], zoneName: 'Zona T2-T3' },
    { name: 'T4-T4S', terminals: ['T4', 'T4S'], zoneName: 'Zona T4-T4S' },
  ];

  // Render terminal card similar to station card (horizontal layout with flights below)
  const renderTerminalCard = (group: { name: string; terminals: string[]; zoneName: string }) => {
    if (!flightData) return null;
    
    // Calculate totals for the group
    let total30min = 0;
    let total60min = 0;
    let allArrivals: FlightArrival[] = [];
    
    group.terminals.forEach(terminalName => {
      const terminal = flightData.terminals[terminalName];
      if (terminal) {
        total30min += terminal.total_next_30min;
        total60min += terminal.total_next_60min;
        allArrivals = [...allArrivals, ...terminal.arrivals];
      }
    });
    
    // Filter arrivals to only show those within the selected time window
    const now = new Date();
    const filteredArrivals = allArrivals.filter(arrival => {
      try {
        const [hours, minutes] = arrival.time.split(':').map(Number);
        const arrivalDate = new Date();
        arrivalDate.setHours(hours, minutes, 0, 0);
        
        // Handle day rollover (if arrival time is before current time by more than 2 hours, it's tomorrow)
        if (arrivalDate.getTime() < now.getTime() - 2 * 60 * 60 * 1000) {
          arrivalDate.setDate(arrivalDate.getDate() + 1);
        }
        
        const diffMinutes = (arrivalDate.getTime() - now.getTime()) / (1000 * 60);
        return diffMinutes >= 0 && diffMinutes <= timeWindow;
      } catch {
        return false;
      }
    });
    
    // Sort filtered arrivals by time
    filteredArrivals.sort((a, b) => a.time.localeCompare(b.time));
    
    const arrivals = timeWindow === 30 ? total30min : total60min;
    
    // Determine if this group is the winner
    const groupTotals = terminalGroups.map(g => {
      let t30 = 0, t60 = 0;
      g.terminals.forEach(t => {
        const term = flightData.terminals[t];
        if (term) {
          t30 += term.total_next_30min;
          t60 += term.total_next_60min;
        }
      });
      return { name: g.name, total30: t30, total60: t60 };
    });
    
    const maxTotal = timeWindow === 30 
      ? Math.max(...groupTotals.map(g => g.total30))
      : Math.max(...groupTotals.map(g => g.total60));
    
    const isWinner = arrivals === maxTotal && arrivals > 0;
    
    // Check-in status for this group
    const isCheckedInHere = checkInStatus?.is_checked_in && 
      checkInStatus.location_type === 'terminal' && 
      group.terminals.includes(checkInStatus.location_name || '');

    // Get taxi exits for this terminal group
    const taxiExits = streetData?.exits_by_terminal?.[group.zoneName] || 0;
    const terminalKey = group.terminals[0];

    return (
      <View
        key={group.name}
        style={[
          styles.stationCard,
          isWinner && styles.winnerCard,
        ]}
      >
        {isWinner && (
          <View style={styles.winnerBadge}>
            <Ionicons name="trophy" size={16} color="#FFFFFF" />
            <Text style={styles.winnerBadgeText}>MÁS FRECUENCIA</Text>
          </View>
        )}
        <View style={styles.stationHeader}>
          <Ionicons name="airplane" size={28} color={isWinner ? '#F59E0B' : '#3B82F6'} />
          <Text style={[styles.stationName, isWinner && styles.winnerText]}>
            {group.zoneName}
          </Text>
        </View>
        <View style={styles.arrivalCount}>
          <Text style={[styles.arrivalNumber, isWinner && styles.winnerNumber]}>
            {arrivals}
          </Text>
          <Text style={styles.arrivalLabel}>
            vuelos en {timeWindow} min
          </Text>
        </View>
        
        {/* Salidas de taxistas en ventana anterior */}
        <View style={styles.taxiExitsContainer}>
          <Ionicons name="car" size={18} color="#10B981" />
          <Text style={styles.taxiExitsText}>
            {taxiExits} salidas taxi (vent. anterior)
          </Text>
        </View>
        
        {/* Taxi status display */}
        {taxiStatus[`terminal_${terminalKey}`] && (
          <View style={styles.taxiStatusContainer}>
            <Ionicons name="car" size={16} color="#F59E0B" />
            <Text style={styles.taxiStatusText}>
              Taxis: {taxiStatus[`terminal_${terminalKey}`].taxi_status === 'poco' ? '🟢 Pocos' : 
                     taxiStatus[`terminal_${terminalKey}`].taxi_status === 'normal' ? '🟡 Normal' : '🔴 Muchos'}
            </Text>
            <Text style={styles.taxiTimeText}>
              ({formatTime(taxiStatus[`terminal_${terminalKey}`].reported_at)} por {taxiStatus[`terminal_${terminalKey}`].reported_by})
            </Text>
          </View>
        )}
        
        {/* Queue status display (people waiting) */}
        {queueStatus[`terminal_${terminalKey}`] && (
          <View style={styles.queueStatusContainer}>
            <Ionicons name="people" size={16} color="#6366F1" />
            <Text style={styles.taxiStatusText}>
              Gente: {queueStatus[`terminal_${terminalKey}`].queue_status === 'poco' ? '🔴 Poca' : 
                     queueStatus[`terminal_${terminalKey}`].queue_status === 'normal' ? '🟡 Normal' : '🟢 Mucha'}
            </Text>
            <Text style={styles.taxiTimeText}>
              ({formatTime(queueStatus[`terminal_${terminalKey}`].reported_at)} por {queueStatus[`terminal_${terminalKey}`].reported_by})
            </Text>
          </View>
        )}
        
        {/* Flight arrivals list */}
        <View style={styles.arrivalsList}>
          {filteredArrivals.slice(0, 5).map((flight, index) => (
            <View key={index} style={styles.arrivalItem}>
              <View style={styles.arrivalTime}>
                <Text style={[
                  styles.timeText,
                  flight.delay_minutes && flight.delay_minutes > 0 && styles.delayedTimeText
                ]}>
                  {flight.time}
                </Text>
                {flight.delay_minutes && flight.delay_minutes > 0 && flight.scheduled_time && (
                  <Text style={styles.scheduledTimeText}>
                    ({flight.scheduled_time})
                  </Text>
                )}
              </View>
              <View style={styles.arrivalInfo}>
                <View style={styles.trainTypeRow}>
                  <Text style={styles.trainType}>{flight.flight_number}</Text>
                  {flight.delay_minutes && flight.delay_minutes > 0 && (
                    <View style={styles.delayBadge}>
                      <Text style={styles.delayText}>+{flight.delay_minutes}'</Text>
                    </View>
                  )}
                </View>
                <Text style={styles.originText} numberOfLines={1}>
                  {flight.origin}
                </Text>
              </View>
              <View style={[styles.platformBadge, { backgroundColor: '#3B82F622' }]}>
                <Text style={[styles.platformText, { color: '#3B82F6' }]}>
                  {flight.terminal}
                </Text>
              </View>
            </View>
          ))}
        </View>
        
        {/* Check-in/Check-out Button */}
        {isCheckedInHere ? (
          <TouchableOpacity
            style={[styles.checkInButton, styles.checkOutButton]}
            onPress={() => handleCheckIn('terminal', checkInStatus?.location_name || terminalKey, 'exit')}
            disabled={checkInLoading}
          >
            <Ionicons name="exit-outline" size={20} color="#FFFFFF" />
            <Text style={styles.checkInButtonText}>
              {checkInLoading ? 'Registrando...' : 'SALIR DE TERMINAL'}
            </Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={[styles.checkInButton, { backgroundColor: '#3B82F6' }]}
            onPress={() => handleCheckIn('terminal', terminalKey, 'entry')}
            disabled={checkInLoading || (checkInStatus?.is_checked_in || false)}
          >
            <Ionicons name="enter-outline" size={20} color="#FFFFFF" />
            <Text style={styles.checkInButtonText}>
              {checkInLoading ? 'Registrando...' : 'ENTRAR EN TERMINAL'}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    );
  };

  // Keep old function for reference but won't be used
  const renderTerminalGroupCard = (group: { name: string; terminals: string[]; zoneName: string }) => {
    return renderTerminalCard(group);
  };

  const renderFlightsList = () => {
    if (!flightData) return null;

    // Get all terminals with flights, sorted by arrival count
    const terminalsWithFlights = Object.entries(flightData.terminals)
      .filter(([_, data]) => data.arrivals.length > 0)
      .sort((a, b) => {
        const countA = timeWindow === 30 ? a[1].total_next_30min : a[1].total_next_60min;
        const countB = timeWindow === 30 ? b[1].total_next_30min : b[1].total_next_60min;
        return countB - countA;
      });

    if (terminalsWithFlights.length === 0) {
      return (
        <View style={styles.flightsList}>
          <Text style={styles.noFlightsText}>No hay vuelos próximos</Text>
        </View>
      );
    }

    return (
      <View style={styles.flightsListContainer}>
        {terminalsWithFlights.map(([terminal, terminalData]) => (
          <View key={terminal} style={styles.flightsList}>
            <Text style={styles.flightsListTitle}>
              Próximas llegadas - Terminal {terminal}
            </Text>
            {terminalData.arrivals.slice(0, 5).map((flight, index) => (
              <View key={index} style={styles.flightItem}>
                <View style={styles.flightTime}>
                  <Text style={[
                    styles.flightTimeText,
                    flight.delay_minutes && flight.delay_minutes > 0 && styles.delayedTimeText
                  ]}>
                    {flight.time}
                  </Text>
                  {flight.delay_minutes && flight.delay_minutes > 0 && flight.scheduled_time && (
                    <Text style={styles.scheduledTimeText}>
                      ({flight.scheduled_time})
                    </Text>
                  )}
                </View>
                <View style={styles.flightInfo}>
                  <View style={styles.trainTypeRow}>
                    <Text style={styles.flightNumber}>{flight.flight_number}</Text>
                    {flight.delay_minutes && flight.delay_minutes > 0 && (
                      <View style={styles.delayBadge}>
                        <Text style={styles.delayText}>+{flight.delay_minutes}'</Text>
                      </View>
                    )}
                    {flight.delay_minutes && flight.delay_minutes < 0 && (
                      <View style={[styles.delayBadge, styles.earlyBadge]}>
                        <Text style={styles.earlyText}>{flight.delay_minutes}'</Text>
                      </View>
                    )}
                  </View>
                  <Text style={styles.flightOrigin} numberOfLines={1}>
                    {flight.origin}
                  </Text>
                  <Text style={styles.flightAirline}>{flight.airline}</Text>
                </View>
                <View style={styles.flightStatus}>
                  <Text style={[
                    styles.statusText,
                    flight.status === 'En hora' && styles.statusOnTime,
                    flight.status === 'Retrasado' && styles.statusDelayed,
                    flight.status === 'Adelantado' && styles.statusEarly,
                  ]}>
                    {flight.status}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        ))}
      </View>
    );
  };

  // Generate map HTML for WebView
  const generateMapHtml = () => {
    const center = currentLocation || { latitude: 40.4168, longitude: -3.7038 }; // Madrid center
    const markers = streetData?.hot_streets || [];
    
    return `
      <!DOCTYPE html>
      <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <style>
          body { margin: 0; padding: 0; }
          #map { width: 100%; height: 100vh; }
          .custom-popup { font-size: 14px; }
        </style>
      </head>
      <body>
        <div id="map"></div>
        <script>
          var map = L.map('map').setView([${center.latitude}, ${center.longitude}], 13);
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap'
          }).addTo(map);
          
          ${markers.map((m, i) => `
            L.circleMarker([${m.latitude}, ${m.longitude}], {
              radius: ${Math.min(20, 8 + m.count * 2)},
              fillColor: '${i === 0 ? '#EF4444' : '#6366F1'}',
              color: '#fff',
              weight: 2,
              opacity: 1,
              fillOpacity: 0.8
            }).addTo(map).bindPopup('<div class="custom-popup"><b>${m.street_name}</b><br>${m.count} actividades</div>');
          `).join('')}
          
          ${currentLocation ? `
            L.marker([${currentLocation.latitude}, ${currentLocation.longitude}])
              .addTo(map)
              .bindPopup('Tu ubicación');
          ` : ''}
        </script>
      </body>
      </html>
    `;
  };

  // Render map component (WebView for mobile, iframe for web)
  const renderMap = () => {
    const center = currentLocation || { latitude: 40.4168, longitude: -3.7038 };
    const markers = streetData?.hot_streets || [];
    
    if (Platform.OS === 'web') {
      // Use iframe for web with marker on current location
      const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${center.longitude - 0.02}%2C${center.latitude - 0.01}%2C${center.longitude + 0.02}%2C${center.latitude + 0.01}&layer=mapnik&marker=${center.latitude}%2C${center.longitude}`;
      return (
        <View style={styles.mapContainer}>
          <iframe
            src={mapUrl}
            style={{ width: '100%', height: '100%', border: 0 }}
            title="Map"
            key={`map-${center.latitude.toFixed(5)}-${center.longitude.toFixed(5)}`}
          />
          <View style={styles.mapOverlay}>
            <View style={styles.locationIndicator}>
              <View style={styles.locationDot} />
              <Text style={styles.locationIndicatorText}>
                📍 Siguiendo ubicación
              </Text>
            </View>
            {markers.length > 0 && (
              <Text style={styles.mapOverlayText}>
                {markers.length} zonas activas
              </Text>
            )}
          </View>
          {currentLocation && (
            <View style={styles.coordsDisplay}>
              <Text style={styles.coordsText}>
                Lat: {currentLocation.latitude.toFixed(6)}
              </Text>
              <Text style={styles.coordsText}>
                Lng: {currentLocation.longitude.toFixed(6)}
              </Text>
            </View>
          )}
        </View>
      );
    }
    
    // Use WebView for mobile
    return (
      <View style={styles.mapContainer}>
        <WebView
          source={{ html: generateMapHtml() }}
          style={styles.map}
          scrollEnabled={false}
        />
      </View>
    );
  };

  // Open GPS app without destination (just open the app)
  const openGpsApp = async () => {
    try {
      if (gpsApp === 'waze') {
        // Use Waze Universal Link - automatically opens app if installed
        // On mobile, this will open Waze app directly
        await Linking.openURL('https://waze.com/ul');
      } else {
        // Google Maps - try app scheme first on mobile
        if (Platform.OS === 'ios') {
          const canOpen = await Linking.canOpenURL('comgooglemaps://');
          if (canOpen) {
            await Linking.openURL('comgooglemaps://');
            return;
          }
        } else if (Platform.OS === 'android') {
          const canOpen = await Linking.canOpenURL('google.navigation:');
          if (canOpen) {
            await Linking.openURL('google.navigation:');
            return;
          }
        }
        // Fallback to web
        await Linking.openURL('https://www.google.com/maps');
      }
    } catch (err) {
      console.error('Error opening GPS app:', err);
      // Final fallback
      if (gpsApp === 'waze') {
        await Linking.openURL('https://waze.com');
      } else {
        await Linking.openURL('https://www.google.com/maps');
      }
    }
  };

  // Open GPS app for navigation (Google Maps or Waze) with destination address
  const openGpsNavigation = async (lat: number, lng: number, placeName: string) => {
    try {
      // Encode the address for URL - use address instead of coordinates for better accuracy
      const encodedAddress = encodeURIComponent(placeName);
      
      if (gpsApp === 'waze') {
        // Waze Universal Link with address search - more accurate than coordinates
        // q parameter searches for the address text
        await Linking.openURL(`https://waze.com/ul?q=${encodedAddress}&navigate=yes`);
      } else {
        // Google Maps with address
        if (Platform.OS === 'ios') {
          const canOpen = await Linking.canOpenURL('comgooglemaps://');
          if (canOpen) {
            await Linking.openURL(`comgooglemaps://?daddr=${encodedAddress}&directionsmode=driving`);
            return;
          }
        } else if (Platform.OS === 'android') {
          const canOpen = await Linking.canOpenURL('google.navigation:');
          if (canOpen) {
            await Linking.openURL(`google.navigation:q=${encodedAddress}&mode=d`);
            return;
          }
        }
        // Fallback to web Google Maps with address
        await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${encodedAddress}&travelmode=driving`);
      }
    } catch (err) {
      console.error('Error opening GPS navigation:', err);
      const encodedAddress = encodeURIComponent(placeName);
      // Final fallback to web versions with address
      if (gpsApp === 'waze') {
        await Linking.openURL(`https://waze.com/ul?q=${encodedAddress}&navigate=yes`);
      } else {
        await Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${encodedAddress}&travelmode=driving`);
      }
    }
  };

  const renderStreetContent = () => {
    // Safety check - if no streetData yet, show loading
    if (!streetData) {
      return (
        <View style={styles.streetContainer}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#3B82F6" />
            <Text style={styles.loadingText}>Cargando datos de calle...</Text>
          </View>
        </View>
      );
    }
    
    return (
      <View style={styles.streetContainer}>
        {/* === CALLE CALIENTE === */}
        <View style={styles.hottestStreetCard}>
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="car" size={24} color="#10B981" />
            <Text style={styles.hottestStreetTitle}>
              {currentLocation ? 'Calle caliente más cercana' : 'Calle caliente'}
            </Text>
          </View>
          <Text style={styles.hottestStreetName}>
            {streetData.hottest_street || 'Sin datos aún'}
          </Text>
          {streetData.hottest_street && streetData.hottest_count > 0 && (
            <View style={styles.hottestStreetInfo}>
              <Text style={styles.hottestStreetCount}>
                {streetData.hottest_count} cargas ({(streetData.hottest_percentage || 0).toFixed(1)}% de {streetData.hottest_total_loads || 0} totales)
              </Text>
              {streetData.hottest_distance_km != null && (
                <View style={styles.distanceBadge}>
                  <Ionicons name="location" size={14} color="#10B981" />
                  <Text style={styles.distanceText}>
                    {streetData.hottest_distance_km.toFixed(1)} km
                  </Text>
                </View>
              )}
            </View>
          )}
          
          {/* Range indicator: 75m before and 75m after */}
          {streetData.hottest_street && streetData.hottest_street_lat && (
            <View style={styles.rangeIndicator}>
              <Ionicons name="resize-outline" size={16} color="#6B7280" />
              <Text style={styles.rangeText}>
                Zona activa: 75m ↔ 75m (150m total)
              </Text>
            </View>
          )}
          
          {/* Navigate to Google Maps button */}
          {streetData.hottest_street && streetData.hottest_street_lat && streetData.hottest_street_lng && (
            <TouchableOpacity
              style={styles.navigateButton}
              onPress={() => openGpsNavigation(
                streetData.hottest_street_lat,
                streetData.hottest_street_lng,
                streetData.hottest_street
              )}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Ir con GPS</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* === ESTACIÓN CALIENTE === */}
        <View style={[styles.hottestStreetCard, styles.stationHotCard]}>
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="train" size={24} color="#3B82F6" />
            <Text style={styles.hottestStreetTitle}>Estación caliente</Text>
            {streetData?.hottest_station_score !== null && streetData?.hottest_station_score !== undefined && (
              <View style={styles.scoreBadge}>
                <Text style={styles.scoreBadgeText}>{streetData.hottest_station_score.toFixed(0)}%</Text>
              </View>
            )}
          </View>
          <Text style={styles.hottestStreetName}>
            {streetData?.hottest_station || 'Sin datos aún'}
          </Text>
          {streetData?.hottest_station && (
            <View style={styles.scoreDetailsContainer}>
              <View style={styles.scoreDetailItem}>
                <Ionicons name="time-outline" size={14} color="#9CA3AF" />
                <Text style={styles.scoreDetailText}>
                  {streetData.hottest_station_avg_load_time || 0} min carga
                </Text>
              </View>
              <View style={styles.scoreDetailItem}>
                <Ionicons name="train-outline" size={14} color="#9CA3AF" />
                <Text style={styles.scoreDetailText}>
                  {streetData.hottest_station_arrivals || 0} llegadas
                </Text>
              </View>
              <View style={styles.scoreDetailItem}>
                <Ionicons name="exit-outline" size={14} color="#9CA3AF" />
                <Text style={styles.scoreDetailText}>
                  {streetData.hottest_station_exits || 0} salidas
                </Text>
              </View>
            </View>
          )}
          
          {/* Alert for low train arrivals */}
          {streetData?.hottest_station_low_arrivals_alert && (
            <View style={styles.lowArrivalsAlert}>
              <Ionicons name="warning" size={18} color="#F59E0B" />
              <Text style={styles.lowArrivalsAlertText}>
                ⚠️ Pocos trenes: Solo {streetData.hottest_station_future_arrivals || 0} llegadas próximas
              </Text>
            </View>
          )}
          
          {/* Taxi status display for hot station */}
          {streetData?.hottest_station_taxi_status && streetData?.hottest_station_taxi_time && (
            <View style={styles.taxiStatusContainerSmall}>
              <Ionicons name="car" size={14} color="#F59E0B" />
              <Text style={styles.taxiStatusTextSmall}>
                {streetData.hottest_station_taxi_status === 'poco' ? '🟢 Pocos' : 
                 streetData.hottest_station_taxi_status === 'normal' ? '🟡 Normal' : '🔴 Muchos'}
              </Text>
              <Text style={styles.taxiTimeTextSmall}>
                {formatTime(streetData.hottest_station_taxi_time)} por {streetData.hottest_station_taxi_reporter}
              </Text>
            </View>
          )}
          
          {streetData?.hottest_station && (
            <TouchableOpacity
              style={[styles.navigateButton, styles.navigateButtonStation]}
              onPress={() => openGpsApp()}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Abrir GPS</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* === TERMINAL CALIENTE === */}
        <View style={[styles.hottestStreetCard, styles.terminalHotCard]}>
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="airplane" size={24} color="#8B5CF6" />
            <Text style={styles.hottestStreetTitle}>Terminal caliente</Text>
            {streetData?.hottest_terminal_score !== null && streetData?.hottest_terminal_score !== undefined && (
              <View style={[styles.scoreBadge, styles.scoreBadgeTerminal]}>
                <Text style={styles.scoreBadgeText}>{streetData.hottest_terminal_score.toFixed(0)}%</Text>
              </View>
            )}
          </View>
          <Text style={styles.hottestStreetName}>
            {streetData?.hottest_terminal || 'Sin datos aún'}
          </Text>
          {streetData?.hottest_terminal && (
            <View style={styles.scoreDetailsContainer}>
              <View style={styles.scoreDetailItem}>
                <Ionicons name="time-outline" size={14} color="#9CA3AF" />
                <Text style={styles.scoreDetailText}>
                  {streetData.hottest_terminal_avg_load_time || 0} min carga
                </Text>
              </View>
              <View style={styles.scoreDetailItem}>
                <Ionicons name="airplane-outline" size={14} color="#9CA3AF" />
                <Text style={styles.scoreDetailText}>
                  {streetData.hottest_terminal_arrivals || 0} llegadas
                </Text>
              </View>
              <View style={styles.scoreDetailItem}>
                <Ionicons name="exit-outline" size={14} color="#9CA3AF" />
                <Text style={styles.scoreDetailText}>
                  {streetData.hottest_terminal_exits || 0} salidas
                </Text>
              </View>
            </View>
          )}
          
          {/* Alert for low flight arrivals */}
          {streetData?.hottest_terminal_low_arrivals_alert && (
            <View style={styles.lowArrivalsAlert}>
              <Ionicons name="warning" size={18} color="#F59E0B" />
              <Text style={styles.lowArrivalsAlertText}>
                ⚠️ Pocos vuelos: Solo {streetData.hottest_terminal_future_arrivals || 0} llegadas próximas
              </Text>
            </View>
          )}
          
          {/* Taxi status display for hot terminal */}
          {streetData?.hottest_terminal_taxi_status && streetData?.hottest_terminal_taxi_time && (
            <View style={styles.taxiStatusContainerSmall}>
              <Ionicons name="car" size={14} color="#F59E0B" />
              <Text style={styles.taxiStatusTextSmall}>
                {streetData.hottest_terminal_taxi_status === 'poco' ? '🟢 Pocos' : 
                 streetData.hottest_terminal_taxi_status === 'normal' ? '🟡 Normal' : '🔴 Muchos'}
              </Text>
              <Text style={styles.taxiTimeTextSmall}>
                {formatTime(streetData.hottest_terminal_taxi_time)} por {streetData.hottest_terminal_taxi_reporter}
              </Text>
            </View>
          )}
          
          {streetData?.hottest_terminal && (
            <TouchableOpacity
              style={[styles.navigateButton, styles.navigateButtonTerminal]}
              onPress={() => openGpsApp()}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Abrir GPS</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* Map */}
        {renderMap()}

        {/* Single Toggle Button for Load/Unload */}
        <View style={styles.streetButtonsContainer}>
          {hasActiveLoad ? (
            <TouchableOpacity
              style={[styles.streetButtonLarge, styles.unloadButtonLarge]}
              onPress={() => registerActivity('unload')}
              disabled={streetLoading}
            >
              {streetLoading ? (
                <ActivityIndicator color="#FFFFFF" size="large" />
              ) : (
                <>
                  <Ionicons name="arrow-up-circle" size={40} color="#FFFFFF" />
                  <Text style={styles.streetButtonTextLarge}>DESCARGADO</Text>
                  <Text style={styles.streetButtonHint}>Toca para registrar descarga</Text>
                </>
              )}
            </TouchableOpacity>
          ) : (
            <TouchableOpacity
              style={[styles.streetButtonLarge, styles.loadButtonLarge]}
              onPress={() => setShowStreetFareModal(true)}
              disabled={streetLoading}
            >
              {streetLoading ? (
                <ActivityIndicator color="#FFFFFF" size="large" />
              ) : (
                <>
                  <Ionicons name="arrow-down-circle" size={40} color="#FFFFFF" />
                  <Text style={styles.streetButtonTextLarge}>CARGADO</Text>
                  <Text style={styles.streetButtonHint}>Toca para calcular tarifa</Text>
                </>
              )}
            </TouchableOpacity>
          )}
          
          {/* Refresh Button */}
          <TouchableOpacity
            style={styles.streetRefreshButton}
            onPress={() => {
              setRefreshing(true);
              fetchStreetData().finally(() => setRefreshing(false));
            }}
            disabled={refreshing}
          >
            <Ionicons name="refresh" size={24} color="#FFFFFF" />
          </TouchableOpacity>
        </View>

        {/* Stats */}
        <View style={styles.streetStatsContainer}>
          <View style={styles.streetStatCard}>
            <Text style={styles.streetStatNumber}>{streetData?.total_loads || 0}</Text>
            <Text style={styles.streetStatLabel}>Cargas</Text>
          </View>
          <View style={styles.streetStatCard}>
            <Text style={styles.streetStatNumber}>{streetData?.total_unloads || 0}</Text>
            <Text style={styles.streetStatLabel}>Descargas</Text>
          </View>
        </View>
        <View style={styles.streetStatsContainer}>
          <View style={[styles.streetStatCard, styles.streetStatCardSmall]}>
            <Ionicons name="train" size={16} color="#3B82F6" />
            <Text style={styles.streetStatNumberSmall}>{streetData?.total_station_entries || 0}</Text>
            <Text style={styles.streetStatLabelSmall}>Estaciones</Text>
          </View>
          <View style={[styles.streetStatCard, styles.streetStatCardSmall]}>
            <Ionicons name="airplane" size={16} color="#3B82F6" />
            <Text style={styles.streetStatNumberSmall}>{streetData?.total_terminal_entries || 0}</Text>
            <Text style={styles.streetStatLabelSmall}>Terminales</Text>
          </View>
        </View>

        {/* Recent Activity */}
        {streetData?.recent_activities && streetData.recent_activities.length > 0 && (
          <View style={styles.recentActivityContainer}>
            <Text style={styles.recentActivityTitle}>Actividad reciente</Text>
            {streetData.recent_activities.slice(0, 10).map((activity, index) => {
              // Determine icon and color based on action type
              let iconName: keyof typeof Ionicons.glyphMap = 'help-circle';
              let iconColor = '#94A3B8';
              let actionLabel = '';
              
              switch (activity.action) {
                case 'load':
                  iconName = 'arrow-down-circle';
                  iconColor = '#10B981';
                  actionLabel = 'Carga';
                  break;
                case 'unload':
                  iconName = 'arrow-up-circle';
                  iconColor = '#F59E0B';
                  actionLabel = 'Descarga';
                  break;
                case 'station_entry':
                  iconName = 'enter';
                  iconColor = '#3B82F6';
                  actionLabel = 'Entrada estación';
                  break;
                case 'station_exit':
                  iconName = 'exit';
                  iconColor = '#8B5CF6';
                  actionLabel = 'Salida estación';
                  break;
                case 'terminal_entry':
                  iconName = 'airplane';
                  iconColor = '#3B82F6';
                  actionLabel = 'Entrada terminal';
                  break;
                case 'terminal_exit':
                  iconName = 'airplane-outline';
                  iconColor = '#8B5CF6';
                  actionLabel = 'Salida terminal';
                  break;
              }
              
              // Format time
              const activityTime = new Date(activity.created_at);
              const timeString = activityTime.toLocaleTimeString('es-ES', { 
                hour: '2-digit', 
                minute: '2-digit' 
              });
              
              return (
                <View key={index} style={styles.activityItem}>
                  <View style={styles.activityTimeColumn}>
                    <Text style={styles.activityTimeText}>{timeString}</Text>
                    {/* Show duration and distance for unload activities */}
                    {activity.action === 'unload' && (
                      <>
                        {activity.duration_minutes !== undefined && activity.duration_minutes !== null && (
                          <View style={styles.durationBadge}>
                            <Ionicons name="time-outline" size={10} color="#10B981" />
                            <Text style={styles.durationText}>{activity.duration_minutes}min</Text>
                          </View>
                        )}
                        {activity.distance_km !== undefined && activity.distance_km !== null && (
                          <View style={styles.distanceBadgeSmall}>
                            <Ionicons name="navigate-outline" size={10} color="#6366F1" />
                            <Text style={styles.distanceTextSmall}>{activity.distance_km}km</Text>
                          </View>
                        )}
                      </>
                    )}
                  </View>
                  <Ionicons name={iconName} size={24} color={iconColor} />
                  <View style={styles.activityInfo}>
                    <Text style={styles.activityAction}>{actionLabel}</Text>
                    <Text style={styles.activityStreet} numberOfLines={1}>
                      {activity.location_name || activity.street_name}
                    </Text>
                    <Text style={styles.activityUser}>{activity.username}</Text>
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor="#0F172A" />

      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerTop}>
          <Text style={styles.headerTitle}>TransportMeter</Text>
          <View style={styles.headerActions}>
            {/* Admin Button - only for admins */}
            {currentUser?.role === 'admin' && (
              <TouchableOpacity 
                style={styles.adminButton}
                onPress={() => router.push('/admin')}
              >
                <Ionicons name="shield" size={18} color="#F59E0B" />
              </TouchableOpacity>
            )}
            {/* Settings Button */}
            <TouchableOpacity 
              style={styles.settingsButton}
              onPress={() => setShowSettings(true)}
            >
              <Ionicons name="settings-outline" size={20} color="#94A3B8" />
            </TouchableOpacity>
            {/* User Button */}
            <TouchableOpacity 
              style={styles.userButton}
              onPress={handleLogout}
            >
              <Ionicons name="person" size={16} color="#6366F1" />
              <Text style={styles.usernameText}>{currentUser?.username}</Text>
              <Ionicons name="log-out-outline" size={16} color="#EF4444" />
            </TouchableOpacity>
            <View style={styles.notificationToggle}>
              <Ionicons
                name={notificationsEnabled ? 'notifications' : 'notifications-outline'}
                size={20}
                color={notificationsEnabled ? '#F59E0B' : '#94A3B8'}
              />
              <Switch
                value={notificationsEnabled}
                onValueChange={toggleNotifications}
                trackColor={{ false: '#334155', true: '#F59E0B' }}
                thumbColor="#FFFFFF"
                style={styles.switch}
              />
            </View>
          </View>
        </View>
        <Text style={styles.headerSubtitle}>
          Frecuencia de llegadas en Madrid
        </Text>
      </View>

      {/* Tab Selector */}
      <View style={styles.tabContainer}>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'trains' && styles.activeTabTrains]}
          onPress={() => setActiveTab('trains')}
        >
          <Ionicons
            name="train"
            size={20}
            color={activeTab === 'trains' ? '#FFFFFF' : '#94A3B8'}
          />
          <Text
            style={[
              styles.tabText,
              activeTab === 'trains' && styles.activeTabText,
            ]}
          >
            Trenes
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'flights' && styles.activeTabFlights]}
          onPress={() => setActiveTab('flights')}
        >
          <Ionicons
            name="airplane"
            size={20}
            color={activeTab === 'flights' ? '#FFFFFF' : '#94A3B8'}
          />
          <Text
            style={[
              styles.tabText,
              activeTab === 'flights' && styles.activeTabText,
            ]}
          >
            Aviones
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, activeTab === 'street' && styles.activeTabStreet]}
          onPress={() => setActiveTab('street')}
        >
          <Ionicons
            name="car"
            size={20}
            color={activeTab === 'street' ? '#FFFFFF' : '#94A3B8'}
          />
          <Text
            style={[
              styles.tabText,
              activeTab === 'street' && styles.activeTabText,
            ]}
          >
            Calle
          </Text>
        </TouchableOpacity>
      </View>

      {/* Time Window Selector with SOS Button */}
      <View style={styles.timeWindowContainer}>
        <Text style={styles.timeWindowLabel}>Ventana de tiempo:</Text>
        <View style={styles.timeWindowButtons}>
          <TouchableOpacity
            style={[
              styles.timeWindowButton,
              timeWindow === 30 && styles.activeTimeWindow,
            ]}
            onPress={() => setTimeWindow(30)}
          >
            <Text
              style={[
                styles.timeWindowText,
                timeWindow === 30 && styles.activeTimeWindowText,
              ]}
            >
              30 min
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.timeWindowButton,
              timeWindow === 60 && styles.activeTimeWindow,
            ]}
            onPress={() => setTimeWindow(60)}
          >
            <Text
              style={[
                styles.timeWindowText,
                timeWindow === 60 && styles.activeTimeWindowText,
              ]}
            >
              60 min
            </Text>
          </TouchableOpacity>
        </View>
        
        {/* SOS Button - always visible */}
        <TouchableOpacity
          style={[
            styles.sosButton,
            myActiveAlert && styles.sosButtonActive
          ]}
          onPress={() => myActiveAlert ? setShowSosModal(true) : setShowSosModal(true)}
        >
          <Ionicons 
            name={myActiveAlert ? "alert-circle" : "shield-checkmark-outline"} 
            size={18} 
            color={myActiveAlert ? "#FFFFFF" : "#9CA3AF"} 
          />
        </TouchableOpacity>
      </View>

      {/* Shift Selector - Only for trains */}
      {activeTab === 'trains' && (
        <View style={styles.shiftContainer}>
          <Text style={styles.shiftLabel}>Turno:</Text>
          <View style={styles.shiftButtons}>
            <TouchableOpacity
              style={[
                styles.shiftButton,
                shift === 'day' && styles.activeShiftDay,
              ]}
              onPress={() => setShift('day')}
            >
              <Ionicons
                name="sunny"
                size={16}
                color={shift === 'day' ? '#FFFFFF' : '#F59E0B'}
              />
              <Text
                style={[
                  styles.shiftText,
                  shift === 'day' && styles.activeShiftText,
                ]}
              >
                Diurno
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.shiftButton,
                shift === 'all' && styles.activeShiftAll,
              ]}
              onPress={() => setShift('all')}
            >
              <Ionicons
                name="time"
                size={16}
                color={shift === 'all' ? '#FFFFFF' : '#6366F1'}
              />
              <Text
                style={[
                  styles.shiftText,
                  shift === 'all' && styles.activeShiftText,
                ]}
              >
                Todo
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.shiftButton,
                shift === 'night' && styles.activeShiftNight,
              ]}
              onPress={() => setShift('night')}
            >
              <Ionicons
                name="moon"
                size={16}
                color={shift === 'night' ? '#FFFFFF' : '#8B5CF6'}
              />
              <Text
                style={[
                  styles.shiftText,
                  shift === 'night' && styles.activeShiftText,
                ]}
              >
                Nocturno
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Content */}
      <ScrollView
        style={styles.content}
        contentContainerStyle={styles.contentContainer}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#6366F1"
          />
        }
      >
        {loading ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#6366F1" />
            <Text style={styles.loadingText}>Cargando datos...</Text>
          </View>
        ) : activeTab === 'trains' && trainData ? (
          <>
            <View style={styles.lastUpdateRow}>
              <View style={styles.lastUpdate}>
                <Ionicons name="time-outline" size={14} color="#64748B" />
                <Text style={styles.lastUpdateText}>
                  Actualizado: {formatLastUpdate(trainData.last_update)}
                </Text>
              </View>
              <TouchableOpacity 
                style={styles.refreshButton} 
                onPress={onRefresh}
                disabled={refreshing}
              >
                <Ionicons 
                  name="refresh" 
                  size={18} 
                  color={refreshing ? "#64748B" : "#6366F1"} 
                />
                <Text style={[styles.refreshText, refreshing && styles.refreshTextDisabled]}>
                  {refreshing ? 'Actualizando...' : 'Actualizar'}
                </Text>
              </TouchableOpacity>
            </View>
            {trainData.message && (
              <View style={styles.nightTimeMessage}>
                <Ionicons name="information-circle" size={16} color="#F59E0B" />
                <Text style={styles.nightTimeText}>{trainData.message}</Text>
              </View>
            )}
            <View style={styles.comparisonContainer}>
              {renderStationCard(trainData.atocha, 'atocha')}
              <View style={styles.vsSeparator}>
                <Text style={styles.vsText}>VS</Text>
              </View>
              {renderStationCard(trainData.chamartin, 'chamartin')}
            </View>
          </>
        ) : activeTab === 'flights' && flightData ? (
          <>
            <View style={styles.lastUpdateWithRefresh}>
              <View style={styles.lastUpdate}>
                <Ionicons name="time-outline" size={14} color="#64748B" />
                <Text style={styles.lastUpdateText}>
                  Actualizado: {formatLastUpdate(flightData.last_update)}
                </Text>
              </View>
              <TouchableOpacity
                style={styles.refreshButtonSmall}
                onPress={onRefresh}
                disabled={refreshing}
              >
                <Ionicons name="refresh" size={18} color="#3B82F6" />
              </TouchableOpacity>
            </View>
            <Text style={styles.sectionTitle}>Zonas de Carga - Madrid Barajas</Text>
            {/* T1 */}
            {renderTerminalCard(terminalGroups[0])}
            {/* T2-T3 */}
            {renderTerminalCard(terminalGroups[1])}
            {/* T4-T4S */}
            {renderTerminalCard(terminalGroups[2])}
          </>
        ) : activeTab === 'street' ? (
          renderStreetContent()
        ) : (
          <View style={styles.errorContainer}>
            <Ionicons name="alert-circle-outline" size={48} color="#EF4444" />
            <Text style={styles.errorText}>Error al cargar datos</Text>
            <TouchableOpacity style={styles.retryButton} onPress={onRefresh}>
              <Text style={styles.retryButtonText}>Reintentar</Text>
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>

      {/* Footer Info */}
      <View style={styles.footer}>
        <Text style={styles.footerText}>
          Datos basados en horarios de ADIF y AENA
        </Text>
      </View>

      {/* Settings Modal */}
      {showSettings && (
        <View style={styles.modalOverlay}>
          <View style={styles.settingsModal}>
            <View style={styles.settingsHeader}>
              <Text style={styles.settingsTitle}>Ajustes</Text>
              <TouchableOpacity onPress={() => setShowSettings(false)}>
                <Ionicons name="close" size={24} color="#FFFFFF" />
              </TouchableOpacity>
            </View>
            
            <View style={styles.settingsSection}>
              <Text style={styles.settingsSectionTitle}>GPS Externo</Text>
              <Text style={styles.settingsDescription}>
                Elige la aplicación para navegación
              </Text>
              
              <View style={styles.gpsOptions}>
                <TouchableOpacity
                  style={[
                    styles.gpsOption,
                    gpsApp === 'google' && styles.gpsOptionActive
                  ]}
                  onPress={() => saveGpsPreference('google')}
                >
                  <Ionicons 
                    name="logo-google" 
                    size={28} 
                    color={gpsApp === 'google' ? '#FFFFFF' : '#94A3B8'} 
                  />
                  <Text style={[
                    styles.gpsOptionText,
                    gpsApp === 'google' && styles.gpsOptionTextActive
                  ]}>
                    Google Maps
                  </Text>
                  {gpsApp === 'google' && (
                    <Ionicons name="checkmark-circle" size={20} color="#10B981" />
                  )}
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[
                    styles.gpsOption,
                    gpsApp === 'waze' && styles.gpsOptionActive
                  ]}
                  onPress={() => saveGpsPreference('waze')}
                >
                  <Ionicons 
                    name="navigate" 
                    size={28} 
                    color={gpsApp === 'waze' ? '#FFFFFF' : '#94A3B8'} 
                  />
                  <Text style={[
                    styles.gpsOptionText,
                    gpsApp === 'waze' && styles.gpsOptionTextActive
                  ]}>
                    Waze
                  </Text>
                  {gpsApp === 'waze' && (
                    <Ionicons name="checkmark-circle" size={20} color="#10B981" />
                  )}
                </TouchableOpacity>
              </View>
            </View>
            
            <TouchableOpacity 
              style={styles.settingsCloseButton}
              onPress={() => setShowSettings(false)}
            >
              <Text style={styles.settingsCloseButtonText}>Cerrar</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Taxi Question Modal */}
      {showTaxiQuestion && (
        <View style={styles.modalOverlay}>
          <View style={styles.taxiQuestionModal}>
            <View style={styles.taxiQuestionHeader}>
              <Ionicons name="car" size={40} color="#F59E0B" />
              <Text style={styles.taxiQuestionTitle}>🚕 ¿Cuántos taxis hay?</Text>
              <Text style={styles.taxiQuestionSubtitle}>
                Entrando a {pendingCheckIn?.locationName}
              </Text>
            </View>
            
            <View style={styles.taxiOptions}>
              <TouchableOpacity
                style={[styles.taxiOption, styles.taxiOptionPoco]}
                onPress={() => handleTaxiAnswer('poco')}
              >
                <Text style={styles.taxiOptionEmoji}>🟢</Text>
                <Text style={styles.taxiOptionText}>Pocos</Text>
              </TouchableOpacity>
              
              <TouchableOpacity
                style={[styles.taxiOption, styles.taxiOptionNormal]}
                onPress={() => handleTaxiAnswer('normal')}
              >
                <Text style={styles.taxiOptionEmoji}>🟡</Text>
                <Text style={styles.taxiOptionText}>Normal</Text>
              </TouchableOpacity>
              
              <TouchableOpacity
                style={[styles.taxiOption, styles.taxiOptionMucho]}
                onPress={() => handleTaxiAnswer('mucho')}
              >
                <Text style={styles.taxiOptionEmoji}>🔴</Text>
                <Text style={styles.taxiOptionText}>Muchos</Text>
              </TouchableOpacity>
            </View>
            
            <TouchableOpacity
              style={styles.taxiSkipButton}
              onPress={() => handleTaxiAnswer(null)}
            >
              <Text style={styles.taxiSkipButtonText}>No sé / Omitir</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Queue Question Modal (for exit - people waiting) */}
      {showQueueQuestion && (
        <View style={styles.modalOverlay}>
          <View style={styles.taxiQuestionModal}>
            <View style={styles.taxiQuestionHeader}>
              <Ionicons name="people" size={40} color="#6366F1" />
              <Text style={styles.taxiQuestionTitle}>👥 ¿Cuánta gente hay esperando?</Text>
              <Text style={styles.taxiQuestionSubtitle}>
                Saliendo de {pendingCheckOut?.locationName}
              </Text>
            </View>
            
            <View style={styles.taxiOptions}>
              <TouchableOpacity
                style={[styles.taxiOption, styles.queueOptionPoco]}
                onPress={() => handleQueueAnswer('poco')}
              >
                <Text style={styles.taxiOptionEmoji}>🔴</Text>
                <Text style={styles.taxiOptionText}>Poca</Text>
              </TouchableOpacity>
              
              <TouchableOpacity
                style={[styles.taxiOption, styles.queueOptionNormal]}
                onPress={() => handleQueueAnswer('normal')}
              >
                <Text style={styles.taxiOptionEmoji}>🟡</Text>
                <Text style={styles.taxiOptionText}>Normal</Text>
              </TouchableOpacity>
              
              <TouchableOpacity
                style={[styles.taxiOption, styles.queueOptionMucho]}
                onPress={() => handleQueueAnswer('mucho')}
              >
                <Text style={styles.taxiOptionEmoji}>🟢</Text>
                <Text style={styles.taxiOptionText}>Mucha</Text>
              </TouchableOpacity>
            </View>
            
            <TouchableOpacity
              style={styles.taxiSkipButton}
              onPress={() => handleQueueAnswer(null)}
            >
              <Text style={styles.taxiSkipButtonText}>No sé / Omitir</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Destination & Fare Modal (for terminal exit) */}
      {showDestinationModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.destinationModal}>
            <View style={styles.destinationHeader}>
              <Ionicons name="location" size={40} color="#3B82F6" />
              <Text style={styles.destinationTitle}>📍 ¿A dónde vas?</Text>
              <Text style={styles.destinationSubtitle}>
                Introduce la dirección de destino
              </Text>
            </View>
            
            <View style={styles.destinationInputContainer}>
              <TextInput
                ref={destinationInputRef}
                style={styles.destinationInputWithMic}
                placeholder="Ej: Calle Gran Vía 1, Madrid"
                placeholderTextColor="#6B7280"
                value={destinationAddress}
                onChangeText={handleAddressChange}
                autoFocus={true}
                multiline={false}
              />
              <TouchableOpacity
                style={[styles.micButton, isListening && styles.micButtonActive]}
                onPress={startVoiceInput}
                disabled={isListening}
              >
                <Ionicons 
                  name={isListening ? "mic" : "mic-outline"} 
                  size={24} 
                  color={isListening ? "#FFFFFF" : "#3B82F6"} 
                />
              </TouchableOpacity>
            </View>
            
            {isListening && (
              <View style={styles.listeningIndicator}>
                <ActivityIndicator size="small" color="#3B82F6" />
                <Text style={styles.listeningText}>Escuchando...</Text>
              </View>
            )}
            
            {/* Address Suggestions List */}
            {searchingAddresses && (
              <View style={styles.searchingContainer}>
                <ActivityIndicator size="small" color="#3B82F6" />
                <Text style={styles.searchingText}>Buscando direcciones...</Text>
              </View>
            )}
            
            {addressSuggestions.length > 0 && !fareResult && (
              <ScrollView style={styles.suggestionsContainer} nestedScrollEnabled>
                {addressSuggestions.map((suggestion, index) => (
                  <TouchableOpacity
                    key={index}
                    style={styles.suggestionItem}
                    onPress={() => selectAddress(suggestion)}
                  >
                    <Ionicons 
                      name={suggestion.is_inside_m30 ? "location" : "location-outline"} 
                      size={20} 
                      color={suggestion.is_inside_m30 ? "#10B981" : "#F59E0B"} 
                    />
                    <View style={styles.suggestionTextContainer}>
                      <Text style={styles.suggestionAddress} numberOfLines={2}>
                        {suggestion.address}
                      </Text>
                      <Text style={[
                        styles.suggestionM30Status,
                        { color: suggestion.is_inside_m30 ? '#10B981' : '#F59E0B' }
                      ]}>
                        {suggestion.is_inside_m30 ? '📍 Dentro M30' : '📍 Fuera M30'}
                      </Text>
                    </View>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}
            
            <TouchableOpacity
              style={[styles.calculateButton, (calculatingFare || addressSuggestions.length > 0) && styles.calculateButtonDisabled]}
              onPress={calculateFare}
              disabled={calculatingFare || !destinationAddress.trim() || addressSuggestions.length > 0}
            >
              {calculatingFare ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : (
                <>
                  <Ionicons name="calculator" size={20} color="#FFFFFF" />
                  <Text style={styles.calculateButtonText}>Calcular Tarifa</Text>
                </>
              )}
            </TouchableOpacity>
            
            {fareResult && (
              <View style={styles.fareResultContainer}>
                <View style={[
                  styles.fareResultBox,
                  fareResult.isInsideM30 ? styles.fareInsideM30 : styles.fareOutsideM30
                ]}>
                  <Text style={styles.fareLocationText}>
                    {fareResult.isInsideM30 ? '📍 Dentro de la M30' : '📍 Fuera de la M30'}
                  </Text>
                  <Text style={styles.fareMainText}>{fareResult.tarifa}</Text>
                  <View style={styles.fareDivider} />
                  <Text style={styles.fareSupplementText}>{fareResult.suplemento}</Text>
                </View>
                
                {/* Navigate to destination button */}
                <TouchableOpacity
                  style={styles.navigateToDestButton}
                  onPress={navigateToDestination}
                >
                  <Ionicons name="navigate" size={22} color="#FFFFFF" />
                  <Text style={styles.navigateToDestButtonText}>Ir al destino</Text>
                </TouchableOpacity>
              </View>
            )}
            
            <TouchableOpacity
              style={styles.destinationCloseButton}
              onPress={closeDestinationModal}
            >
              <Ionicons name="close-circle" size={20} color="#FFFFFF" />
              <Text style={styles.destinationCloseButtonText}>
                {fareResult ? 'Cerrar sin navegar' : 'Omitir y abrir GPS'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* SOS Modal */}
      {showSosModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.sosModalContent}>
            {myActiveAlert ? (
              // User has active alert - show resolve option
              <>
                <View style={styles.sosActiveHeader}>
                  <Ionicons name="alert-circle" size={50} color="#EF4444" />
                  <Text style={styles.sosActiveTitle}>Alerta Activa</Text>
                </View>
                <Text style={styles.sosActiveDescription}>
                  Tu alerta de emergencia está activa. Tus compañeros pueden ver tu ubicación.
                </Text>
                <TouchableOpacity
                  style={styles.sosResolveButton}
                  onPress={resolveEmergencyAlert}
                >
                  <Ionicons name="checkmark-circle" size={24} color="#FFFFFF" />
                  <Text style={styles.sosResolveButtonText}>Ya estoy bien - Resolver alerta</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.sosCancelButton}
                  onPress={() => setShowSosModal(false)}
                >
                  <Text style={styles.sosCancelButtonText}>Cerrar</Text>
                </TouchableOpacity>
              </>
            ) : (
              // No active alert - show question
              <>
                <Text style={styles.sosTitle}>¿Estás bien?</Text>
                <Text style={styles.sosDescription}>
                  Selecciona una opción si necesitas ayuda
                </Text>
                
                <TouchableOpacity
                  style={styles.sosOptionOk}
                  onPress={() => setShowSosModal(false)}
                >
                  <Ionicons name="checkmark-circle" size={28} color="#10B981" />
                  <Text style={styles.sosOptionOkText}>Sí, todo bien</Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[styles.sosOptionAlert, sendingAlert && styles.sosOptionDisabled]}
                  onPress={() => sendEmergencyAlert('companions')}
                  disabled={sendingAlert}
                >
                  <Ionicons name="people" size={28} color="#F59E0B" />
                  <View style={styles.sosOptionTextContainer}>
                    <Text style={styles.sosOptionAlertText}>No, avisar compañeros</Text>
                    <Text style={styles.sosOptionAlertSubtext}>
                      Notificar a otros taxistas de tu ubicación
                    </Text>
                  </View>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[styles.sosOptionEmergency, sendingAlert && styles.sosOptionDisabled]}
                  onPress={() => sendEmergencyAlert('companions_police')}
                  disabled={sendingAlert}
                >
                  <Ionicons name="call" size={28} color="#EF4444" />
                  <View style={styles.sosOptionTextContainer}>
                    <Text style={styles.sosOptionEmergencyText}>No, compañeros + Policía</Text>
                    <Text style={styles.sosOptionEmergencySubtext}>
                      Notificar compañeros y llamar al 112
                    </Text>
                  </View>
                </TouchableOpacity>
                
                {sendingAlert && (
                  <ActivityIndicator size="small" color="#3B82F6" style={{ marginTop: 10 }} />
                )}
              </>
            )}
          </View>
        </View>
      )}

      {/* Street Fare Modal */}
      {showStreetFareModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.destinationModalContent}>
            <Text style={styles.destinationTitle}>💵 Calcular Tarifa</Text>
            <Text style={styles.destinationSubtitle}>
              Introduce la dirección de destino
            </Text>
            
            <View style={styles.destinationInputContainer}>
              <TextInput
                ref={streetDestinationInputRef}
                style={styles.destinationInputWithMic}
                placeholder="Ej: Calle Gran Vía 1, Madrid"
                placeholderTextColor="#6B7280"
                value={streetDestinationAddress}
                onChangeText={handleStreetAddressChange}
                autoFocus={true}
                multiline={false}
              />
              <TouchableOpacity
                style={styles.micButton}
                onPress={() => {
                  if (Platform.OS === 'web') {
                    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
                    if (SpeechRecognition) {
                      const recognition = new SpeechRecognition();
                      recognition.lang = 'es-ES';
                      recognition.interimResults = false;
                      recognition.onresult = (event: any) => {
                        const transcript = normalizeSpanishNumbers(event.results[0][0].transcript);
                        setStreetDestinationAddress(transcript);
                        searchStreetAddresses(transcript);
                      };
                      recognition.start();
                    }
                  } else {
                    Alert.alert('🎤 Dictado por voz', 'Usa el botón de micrófono en tu teclado.');
                  }
                }}
              >
                <Ionicons name="mic-outline" size={24} color="#3B82F6" />
              </TouchableOpacity>
            </View>
            
            {/* Searching indicator */}
            {streetSearchingAddresses && (
              <View style={styles.searchingContainer}>
                <ActivityIndicator size="small" color="#3B82F6" />
                <Text style={styles.searchingText}>Buscando direcciones...</Text>
              </View>
            )}
            
            {/* Address Suggestions */}
            {streetAddressSuggestions.length > 0 && !streetFareResult && (
              <ScrollView style={styles.suggestionsContainer} nestedScrollEnabled>
                {streetAddressSuggestions.map((suggestion, index) => (
                  <TouchableOpacity
                    key={index}
                    style={styles.suggestionItem}
                    onPress={() => selectStreetAddress(suggestion)}
                  >
                    <Ionicons name="location" size={20} color="#3B82F6" />
                    <View style={styles.suggestionTextContainer}>
                      <Text style={styles.suggestionAddress} numberOfLines={2}>
                        {suggestion.address}
                      </Text>
                    </View>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}
            
            {/* Calculate Button */}
            <TouchableOpacity
              style={[
                styles.calculateButton, 
                (streetCalculatingFare || !streetSelectedAddress) && styles.calculateButtonDisabled
              ]}
              onPress={calculateStreetFare}
              disabled={streetCalculatingFare || !streetSelectedAddress}
            >
              {streetCalculatingFare ? (
                <ActivityIndicator size="small" color="#FFFFFF" />
              ) : (
                <>
                  <Ionicons name="calculator" size={20} color="#FFFFFF" />
                  <Text style={styles.calculateButtonText}>Calcular Tarifa</Text>
                </>
              )}
            </TouchableOpacity>
            
            {/* Fare Result */}
            {streetFareResult && (
              <View style={styles.streetFareResultContainer}>
                <View style={styles.streetFareBox}>
                  <Text style={styles.streetFareType}>
                    {streetFareResult.is_night_or_weekend ? '🌙 Tarifa Nocturna/Fin de semana' : '☀️ Tarifa Diurna (L-V 6:00-21:00)'}
                  </Text>
                  
                  <View style={styles.streetFareRates}>
                    <Text style={styles.streetFareRateText}>
                      Base: {streetFareResult.base_fare.toFixed(2)}€ + {streetFareResult.per_km_rate.toFixed(2)}€/km
                    </Text>
                  </View>
                  
                  <View style={styles.streetFarePriceRange}>
                    <Text style={styles.streetFarePrice}>
                      {streetFareResult.fare_min.toFixed(2)}€ - {streetFareResult.fare_max.toFixed(2)}€
                    </Text>
                  </View>
                  
                  <View style={styles.streetFareDistance}>
                    <Ionicons name="navigate" size={16} color="#6B7280" />
                    <Text style={styles.streetFareDistanceText}>
                      {streetFareResult.distance_km.toFixed(1)} km aproximados
                    </Text>
                  </View>
                  
                  <Text style={styles.streetFareWarning}>
                    ⚠️ Verifica los kilómetros con el GPS durante el trayecto
                  </Text>
                </View>
                
                {/* Navigate and Register Button */}
                <TouchableOpacity
                  style={styles.streetFareNavigateButton}
                  onPress={handleStreetFareComplete}
                >
                  <Ionicons name="navigate" size={24} color="#FFFFFF" />
                  <Text style={styles.streetFareNavigateText}>Abrir GPS e Ir</Text>
                </TouchableOpacity>
              </View>
            )}
            
            {/* Close/Cancel Button */}
            <TouchableOpacity
              style={styles.destinationCloseButton}
              onPress={() => {
                setShowStreetFareModal(false);
                setStreetDestinationAddress('');
                setStreetAddressSuggestions([]);
                setStreetSelectedAddress(null);
                setStreetFareResult(null);
              }}
            >
              <Ionicons name="close-circle" size={20} color="#FFFFFF" />
              <Text style={styles.destinationCloseButtonText}>Cancelar</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Alert Notification Banner (when other user has emergency) */}
      {activeAlerts.filter(a => !a.is_own).length > 0 && (
        <View style={styles.alertNotificationBanner}>
          {activeAlerts.filter(a => !a.is_own).map((alert) => (
            <View key={alert.alert_id} style={styles.alertNotificationItem}>
              <View style={styles.alertNotificationHeader}>
                <Ionicons 
                  name={alert.alert_type === 'companions_police' ? "warning" : "alert-circle"} 
                  size={24} 
                  color={alert.alert_type === 'companions_police' ? "#EF4444" : "#F59E0B"} 
                />
                <Text style={styles.alertNotificationTitle}>
                  {alert.alert_type === 'companions_police' ? '🚨 EMERGENCIA' : '⚠️ Compañero en problemas'}
                </Text>
              </View>
              <Text style={styles.alertNotificationText}>
                {alert.username} necesita ayuda
              </Text>
              <View style={styles.alertNotificationActions}>
                <TouchableOpacity
                  style={styles.alertNavigateButton}
                  onPress={() => openAlertLocation(alert.latitude, alert.longitude, alert.username)}
                >
                  <Ionicons name="navigate" size={18} color="#FFFFFF" />
                  <Text style={styles.alertNavigateButtonText}>Ir a su ubicación</Text>
                </TouchableOpacity>
                {alert.alert_type === 'companions_police' && (
                  <TouchableOpacity
                    style={styles.alertCallButton}
                    onPress={async () => {
                      try {
                        const phoneUrl = 'tel:112';
                        const canOpen = await Linking.canOpenURL(phoneUrl);
                        if (canOpen) {
                          await Linking.openURL(phoneUrl);
                        } else {
                          Alert.alert('🚨 LLAMA AL 112', 'Marca este número de emergencia: 112');
                        }
                      } catch (error) {
                        Alert.alert('🚨 LLAMA AL 112', 'Marca manualmente: 112');
                      }
                    }}
                  >
                    <Ionicons name="call" size={18} color="#FFFFFF" />
                    <Text style={styles.alertCallButtonText}>Llamar 112</Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>
          ))}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0F172A',
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: Platform.OS === 'android' ? 40 : 10,
    paddingBottom: 15,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
  headerSubtitle: {
    fontSize: 14,
    color: '#94A3B8',
    marginTop: 4,
  },
  headerActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  userSection: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  adminButton: {
    padding: 8,
    backgroundColor: '#F59E0B22',
    borderRadius: 8,
  },
  userButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  usernameText: {
    color: '#6366F1',
    fontSize: 13,
    fontWeight: '500',
  },
  loginButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  loginButtonText: {
    color: '#6366F1',
    fontSize: 13,
    fontWeight: '500',
  },
  notificationToggle: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  switch: {
    marginLeft: 8,
    transform: [{ scaleX: 0.8 }, { scaleY: 0.8 }],
  },
  loginModalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  loginModalContent: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 20,
    width: '100%',
    maxWidth: 350,
  },
  loginModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
  },
  loginModalTitle: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: '600',
  },
  settingsButton: {
    padding: 8,
    marginRight: 8,
  },
  settingsModal: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 20,
    width: '90%',
    maxWidth: 400,
  },
  settingsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
    paddingBottom: 15,
  },
  settingsTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: 'bold',
  },
  settingsSection: {
    marginBottom: 20,
  },
  settingsSectionTitle: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 5,
  },
  settingsDescription: {
    color: '#94A3B8',
    fontSize: 13,
    marginBottom: 15,
  },
  gpsOptions: {
    gap: 10,
  },
  gpsOption: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 15,
    gap: 12,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  gpsOptionActive: {
    borderColor: '#10B981',
    backgroundColor: '#10B98120',
  },
  gpsOptionText: {
    flex: 1,
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '500',
  },
  gpsOptionTextActive: {
    color: '#FFFFFF',
  },
  settingsCloseButton: {
    backgroundColor: '#6366F1',
    borderRadius: 10,
    padding: 15,
    alignItems: 'center',
  },
  settingsCloseButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  loginInput: {
    backgroundColor: '#0F172A',
    borderRadius: 10,
    padding: 15,
    color: '#FFFFFF',
    fontSize: 16,
    marginBottom: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  loginSubmitButton: {
    backgroundColor: '#6366F1',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 5,
  },
  loginSubmitText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  tabContainer: {
    flexDirection: 'row',
    paddingHorizontal: 20,
    gap: 12,
  },
  tab: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#1E293B',
    gap: 8,
  },
  activeTabTrains: {
    backgroundColor: '#6366F1',
  },
  activeTabFlights: {
    backgroundColor: '#10B981',
  },
  activeTabStreet: {
    backgroundColor: '#F59E0B',
  },
  tabText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#94A3B8',
  },
  activeTabText: {
    color: '#FFFFFF',
  },
  timeWindowContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 15,
    gap: 12,
  },
  timeWindowLabel: {
    color: '#94A3B8',
    fontSize: 14,
  },
  timeWindowButtons: {
    flexDirection: 'row',
    backgroundColor: '#1E293B',
    borderRadius: 8,
    padding: 4,
  },
  timeWindowButton: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 6,
  },
  activeTimeWindow: {
    backgroundColor: '#334155',
  },
  timeWindowText: {
    color: '#64748B',
    fontSize: 14,
    fontWeight: '500',
  },
  activeTimeWindowText: {
    color: '#FFFFFF',
  },
  shiftContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingBottom: 10,
    gap: 12,
  },
  shiftLabel: {
    color: '#94A3B8',
    fontSize: 14,
  },
  shiftButtons: {
    flexDirection: 'row',
    backgroundColor: '#1E293B',
    borderRadius: 8,
    padding: 4,
    gap: 4,
  },
  shiftButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 6,
    gap: 6,
  },
  activeShiftDay: {
    backgroundColor: '#F59E0B',
  },
  activeShiftAll: {
    backgroundColor: '#6366F1',
  },
  activeShiftNight: {
    backgroundColor: '#8B5CF6',
  },
  shiftText: {
    color: '#64748B',
    fontSize: 13,
    fontWeight: '500',
  },
  activeShiftText: {
    color: '#FFFFFF',
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    paddingHorizontal: 20,
    paddingBottom: 20,
  },
  lastUpdateWithRefresh: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  refreshButtonSmall: {
    padding: 8,
    backgroundColor: '#1E293B',
    borderRadius: 8,
  },
  lastUpdateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 15,
    paddingHorizontal: 5,
  },
  lastUpdate: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  lastUpdateText: {
    color: '#64748B',
    fontSize: 12,
  },
  refreshButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    gap: 6,
  },
  refreshText: {
    color: '#6366F1',
    fontSize: 12,
    fontWeight: '500',
  },
  refreshTextDisabled: {
    color: '#64748B',
  },
  nightTimeMessage: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1E293B',
    borderRadius: 10,
    padding: 12,
    marginBottom: 15,
    gap: 8,
    borderWidth: 1,
    borderColor: '#F59E0B',
  },
  nightTimeText: {
    color: '#F59E0B',
    fontSize: 12,
    flex: 1,
    textAlign: 'center',
  },
  comparisonContainer: {
    gap: 15,
  },
  stationCard: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 20,
    borderWidth: 3,
    borderColor: '#4B5563',
    marginBottom: 35,
    marginTop: 20,
    marginHorizontal: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 8,
  },
  winnerCard: {
    borderColor: '#F59E0B',
    backgroundColor: '#1E293B',
  },
  winnerBadge: {
    position: 'absolute',
    top: -12,
    right: 20,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#F59E0B',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 4,
  },
  winnerBadgeFlight: {
    top: -10,
    right: 10,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  winnerBadgeText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: 'bold',
  },
  stationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginBottom: 15,
  },
  stationName: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
  winnerText: {
    color: '#F59E0B',
  },
  arrivalCount: {
    alignItems: 'center',
    marginBottom: 15,
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 15,
  },
  peakHourContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 10,
    padding: 12,
    marginBottom: 15,
    gap: 8,
    borderWidth: 1,
    borderColor: '#F59E0B33',
  },
  peakHourText: {
    color: '#F59E0B',
    fontSize: 13,
    fontWeight: '500',
    flex: 1,
  },
  peakHourCount: {
    backgroundColor: '#F59E0B',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 4,
    minWidth: 32,
    alignItems: 'center',
  },
  peakHourCountText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: 'bold',
  },
  arrivalNumber: {
    fontSize: 48,
    fontWeight: 'bold',
    color: '#6366F1',
  },
  winnerNumber: {
    color: '#F59E0B',
  },
  arrivalLabel: {
    fontSize: 14,
    color: '#94A3B8',
    marginTop: 4,
  },
  arrivalsList: {
    gap: 8,
  },
  arrivalItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 8,
    padding: 10,
  },
  arrivalTime: {
    backgroundColor: '#334155',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  timeText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  arrivalInfo: {
    flex: 1,
    marginLeft: 12,
  },
  trainTypeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  trainType: {
    color: '#6366F1',
    fontSize: 12,
    fontWeight: '600',
  },
  delayBadge: {
    backgroundColor: '#EF444433',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  earlyBadge: {
    backgroundColor: '#10B98133',
  },
  delayText: {
    color: '#EF4444',
    fontSize: 11,
    fontWeight: '700',
  },
  earlyText: {
    color: '#10B981',
    fontSize: 11,
    fontWeight: '700',
  },
  delayedTimeText: {
    color: '#EF4444',
  },
  scheduledTimeText: {
    color: '#64748B',
    fontSize: 10,
    textDecorationLine: 'line-through',
  },
  originText: {
    color: '#FFFFFF',
    fontSize: 14,
  },
  platformBadge: {
    backgroundColor: '#6366F1',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
    minWidth: 36,
    alignItems: 'center',
  },
  platformText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: 'bold',
  },
  vsSeparator: {
    alignItems: 'center',
    paddingVertical: 5,
  },
  vsText: {
    color: '#64748B',
    fontSize: 18,
    fontWeight: 'bold',
  },
  sectionTitle: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 15,
    textAlign: 'center',
  },
  terminalsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
    justifyContent: 'center',
  },
  terminalGroupsContainer: {
    flexDirection: 'row',
    gap: 10,
    justifyContent: 'space-between',
    marginBottom: 10,
  },
  terminalGroupCard: {
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 15,
    alignItems: 'center',
    flex: 1,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  terminalGroupName: {
    color: '#10B981',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  terminalGroupTerminals: {
    flexDirection: 'row',
    gap: 6,
    marginBottom: 4,
  },
  terminalGroupTerminalText: {
    color: '#64748B',
    fontSize: 11,
    backgroundColor: '#334155',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  terminalCard: {
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 15,
    alignItems: 'center',
    width: '30%',
    minWidth: 90,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  winnerTerminalCard: {
    borderColor: '#F59E0B',
  },
  terminalName: {
    color: '#10B981',
    fontSize: 16,
    fontWeight: 'bold',
  },
  winnerTerminalText: {
    color: '#F59E0B',
  },
  terminalCount: {
    color: '#FFFFFF',
    fontSize: 28,
    fontWeight: 'bold',
    marginVertical: 4,
  },
  winnerTerminalCount: {
    color: '#F59E0B',
  },
  terminalLabel: {
    color: '#94A3B8',
    fontSize: 12,
  },
  flightsList: {
    marginTop: 15,
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 15,
  },
  flightsListContainer: {
    gap: 15,
  },
  flightsListTitle: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 15,
  },
  noFlightsText: {
    color: '#94A3B8',
    fontSize: 14,
    textAlign: 'center',
    padding: 20,
  },
  flightItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  flightTime: {
    backgroundColor: '#10B981',
    borderRadius: 6,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  flightTimeText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  flightInfo: {
    flex: 1,
    marginLeft: 12,
  },
  flightNumber: {
    color: '#10B981',
    fontSize: 14,
    fontWeight: '600',
  },
  flightOrigin: {
    color: '#FFFFFF',
    fontSize: 14,
  },
  flightAirline: {
    color: '#94A3B8',
    fontSize: 12,
  },
  flightStatus: {
    alignItems: 'center',
    minWidth: 70,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '500',
    color: '#94A3B8',
  },
  statusOnTime: {
    color: '#10B981',
  },
  statusDelayed: {
    color: '#EF4444',
  },
  statusEarly: {
    color: '#3B82F6',
  },
  flightGate: {
    alignItems: 'center',
  },
  gateLabel: {
    color: '#64748B',
    fontSize: 10,
  },
  gateText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 100,
  },
  loadingText: {
    color: '#94A3B8',
    marginTop: 15,
    fontSize: 16,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 100,
  },
  errorText: {
    color: '#EF4444',
    fontSize: 16,
    marginTop: 15,
  },
  retryButton: {
    marginTop: 20,
    backgroundColor: '#6366F1',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  retryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  footer: {
    paddingVertical: 12,
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#1E293B',
  },
  footerText: {
    color: '#64748B',
    fontSize: 11,
  },
  // Auth loading screen
  authLoadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  authLoadingText: {
    color: '#94A3B8',
    marginTop: 15,
    fontSize: 16,
  },
  // Login screen styles
  loginScreenContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  loginScreenContent: {
    width: '100%',
    maxWidth: 400,
    alignItems: 'center',
  },
  loginHeader: {
    alignItems: 'center',
    marginBottom: 40,
  },
  loginLogoContainer: {
    flexDirection: 'row',
    marginBottom: 15,
  },
  loginAppTitle: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#FFFFFF',
    marginBottom: 8,
  },
  loginAppSubtitle: {
    fontSize: 14,
    color: '#94A3B8',
    textAlign: 'center',
  },
  loginFormContainer: {
    width: '100%',
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 25,
    marginBottom: 20,
  },
  loginFormTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: '#FFFFFF',
    textAlign: 'center',
    marginBottom: 25,
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 10,
    marginBottom: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  inputIcon: {
    padding: 15,
  },
  loginScreenInput: {
    flex: 1,
    padding: 15,
    paddingLeft: 0,
    color: '#FFFFFF',
    fontSize: 16,
  },
  loginScreenButton: {
    flexDirection: 'row',
    backgroundColor: '#6366F1',
    borderRadius: 10,
    paddingVertical: 15,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 10,
    gap: 10,
  },
  loginScreenButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  loginFooter: {
    color: '#64748B',
    fontSize: 12,
    textAlign: 'center',
  },
  // Street work styles
  streetContainer: {
    flex: 1,
  },
  hottestStreetCard: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 20,
    marginBottom: 15,
    borderWidth: 2,
    borderColor: '#EF4444',
  },
  hottestStreetHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  hottestStreetTitle: {
    color: '#EF4444',
    fontSize: 16,
    fontWeight: '600',
  },
  hottestStreetName: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  hottestStreetCount: {
    color: '#94A3B8',
    fontSize: 14,
    textAlign: 'center',
    marginTop: 5,
  },
  hottestStreetInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    marginTop: 8,
  },
  distanceBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#10B98133',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    gap: 4,
  },
  distanceText: {
    color: '#10B981',
    fontSize: 13,
    fontWeight: '600',
  },
  rangeIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#374151',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
    marginTop: 8,
    gap: 6,
  },
  rangeText: {
    color: '#9CA3AF',
    fontSize: 11,
    fontWeight: '500',
  },
  navigateButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#3B82F6',
    borderRadius: 12,
    paddingVertical: 14,
    marginTop: 15,
    gap: 8,
  },
  navigateButtonStation: {
    backgroundColor: '#3B82F6',
  },
  navigateButtonTerminal: {
    backgroundColor: '#8B5CF6',
  },
  navigateButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  stationHotCard: {
    borderLeftWidth: 4,
    borderLeftColor: '#3B82F6',
  },
  terminalHotCard: {
    borderLeftWidth: 4,
    borderLeftColor: '#8B5CF6',
  },
  scoreBadge: {
    backgroundColor: '#3B82F6',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    marginLeft: 'auto',
  },
  scoreBadgeTerminal: {
    backgroundColor: '#8B5CF6',
  },
  scoreBadgeText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '700',
  },
  scoreDetailsContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 12,
    marginTop: 8,
    marginBottom: 4,
  },
  scoreDetailItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  scoreDetailText: {
    color: '#9CA3AF',
    fontSize: 12,
  },
  lowArrivalsAlert: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FEF3C7',
    borderWidth: 1,
    borderColor: '#F59E0B',
    borderRadius: 8,
    padding: 10,
    marginTop: 8,
    gap: 8,
  },
  lowArrivalsAlertText: {
    color: '#92400E',
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
  },
  taxiExitsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#10B98122',
    padding: 8,
    borderRadius: 6,
    marginTop: 8,
    gap: 6,
  },
  taxiExitsText: {
    color: '#10B981',
    fontSize: 13,
    fontWeight: '500',
  },
  taxiExitsContainerSmall: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#10B98122',
    padding: 4,
    borderRadius: 4,
    marginTop: 4,
    gap: 4,
  },
  taxiExitsTextSmall: {
    color: '#10B981',
    fontSize: 11,
    fontWeight: '500',
  },
  taxiStatusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    padding: 10,
    borderRadius: 8,
    marginTop: 8,
    gap: 8,
  },
  queueStatusContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    padding: 10,
    borderRadius: 8,
    marginTop: 8,
    gap: 8,
    borderLeftWidth: 3,
    borderLeftColor: '#6366F1',
  },
  taxiStatusText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '600',
  },
  taxiTimeText: {
    color: '#9CA3AF',
    fontSize: 11,
  },
  taxiStatusContainerSmall: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    padding: 6,
    borderRadius: 6,
    marginTop: 6,
    gap: 4,
  },
  queueStatusContainerSmall: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    padding: 6,
    borderRadius: 6,
    marginTop: 6,
    gap: 4,
    borderLeftWidth: 2,
    borderLeftColor: '#6366F1',
  },
  taxiStatusTextSmall: {
    fontSize: 12,
  },
  taxiTimeTextSmall: {
    color: '#9CA3AF',
    fontSize: 9,
  },
  checkInButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#10B981',
    borderRadius: 10,
    paddingVertical: 12,
    marginTop: 15,
    gap: 8,
  },
  checkOutButton: {
    backgroundColor: '#EF4444',
  },
  checkInButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
  },
  checkInButtonSmall: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#10B981',
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginTop: 10,
    gap: 4,
  },
  checkOutButtonSmall: {
    backgroundColor: '#EF4444',
  },
  checkInButtonTextSmall: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '700',
  },
  mapContainer: {
    height: 250,
    borderRadius: 16,
    overflow: 'hidden',
    marginBottom: 15,
    backgroundColor: '#1E293B',
  },
  map: {
    flex: 1,
  },
  modalOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1000,
  },
  mapOverlay: {
    position: 'absolute',
    bottom: 10,
    left: 10,
    backgroundColor: 'rgba(15, 23, 42, 0.9)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    flexDirection: 'column',
    gap: 4,
  },
  mapOverlayText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '500',
  },
  locationIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  locationDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#22C55E',
  },
  locationIndicatorText: {
    color: '#22C55E',
    fontSize: 11,
    fontWeight: '600',
  },
  coordsDisplay: {
    position: 'absolute',
    top: 10,
    right: 10,
    backgroundColor: 'rgba(15, 23, 42, 0.85)',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 6,
  },
  coordsText: {
    color: '#9CA3AF',
    fontSize: 10,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  streetButtonsContainer: {
    flexDirection: 'row',
    gap: 15,
    marginBottom: 15,
    alignItems: 'center',
  },
  streetButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 20,
    borderRadius: 16,
    gap: 10,
  },
  streetButtonLarge: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 25,
    borderRadius: 16,
    gap: 8,
  },
  loadButtonLarge: {
    backgroundColor: '#10B981',
  },
  unloadButtonLarge: {
    backgroundColor: '#F59E0B',
  },
  streetButtonTextLarge: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: 'bold',
  },
  streetButtonHint: {
    color: 'rgba(255,255,255,0.7)',
    fontSize: 12,
  },
  streetRefreshButton: {
    backgroundColor: '#3B82F6',
    padding: 15,
    borderRadius: 12,
    marginLeft: 10,
  },
  loadButton: {
    backgroundColor: '#10B981',
  },
  unloadButton: {
    backgroundColor: '#F59E0B',
  },
  streetButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: 'bold',
  },
  streetStatsContainer: {
    flexDirection: 'row',
    gap: 15,
    marginBottom: 10,
  },
  streetStatCard: {
    flex: 1,
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 15,
    alignItems: 'center',
  },
  streetStatCardSmall: {
    padding: 10,
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  streetStatNumber: {
    color: '#FFFFFF',
    fontSize: 32,
    fontWeight: 'bold',
  },
  streetStatNumberSmall: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
  },
  streetStatLabel: {
    color: '#94A3B8',
    fontSize: 14,
    marginTop: 4,
  },
  streetStatLabelSmall: {
    color: '#94A3B8',
    fontSize: 12,
  },
  recentActivityContainer: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 15,
  },
  recentActivityTitle: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 15,
  },
  activityItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    gap: 10,
  },
  activityTimeColumn: {
    alignItems: 'center',
    minWidth: 50,
  },
  activityTimeText: {
    color: '#6366F1',
    fontSize: 13,
    fontWeight: 'bold',
  },
  durationBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#10B98133',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    marginTop: 4,
    gap: 2,
  },
  durationText: {
    color: '#10B981',
    fontSize: 10,
    fontWeight: '600',
  },
  distanceBadgeSmall: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#6366F133',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    marginTop: 2,
    gap: 2,
  },
  distanceTextSmall: {
    color: '#6366F1',
    fontSize: 10,
    fontWeight: '600',
  },
  activityInfo: {
    flex: 1,
  },
  activityAction: {
    color: '#94A3B8',
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  activityStreet: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '500',
  },
  activityUser: {
    color: '#64748B',
    fontSize: 11,
  },
  taxiQuestionModal: {
    backgroundColor: '#1E293B',
    borderRadius: 20,
    padding: 24,
    width: '90%',
    maxWidth: 400,
    alignItems: 'center',
  },
  taxiQuestionHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  taxiQuestionTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '700',
    marginTop: 12,
  },
  taxiQuestionSubtitle: {
    color: '#94A3B8',
    fontSize: 14,
    marginTop: 4,
  },
  taxiOptions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    width: '100%',
  },
  taxiOption: {
    flex: 1,
    alignItems: 'center',
    padding: 16,
    borderRadius: 12,
    backgroundColor: '#374151',
  },
  taxiOptionPoco: {
    borderWidth: 2,
    borderColor: '#10B981',
  },
  taxiOptionNormal: {
    borderWidth: 2,
    borderColor: '#F59E0B',
  },
  taxiOptionMucho: {
    borderWidth: 2,
    borderColor: '#EF4444',
  },
  // Queue options (gente esperando) - colores invertidos: poca=malo(rojo), mucha=bueno(verde)
  queueOptionPoco: {
    borderWidth: 2,
    borderColor: '#EF4444',
  },
  queueOptionNormal: {
    borderWidth: 2,
    borderColor: '#F59E0B',
  },
  queueOptionMucho: {
    borderWidth: 2,
    borderColor: '#10B981',
  },
  taxiOptionEmoji: {
    fontSize: 32,
    marginBottom: 8,
  },
  taxiOptionText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  taxiSkipButton: {
    marginTop: 20,
    padding: 12,
  },
  taxiSkipButtonText: {
    color: '#94A3B8',
    fontSize: 14,
  },
  // Destination Modal Styles
  destinationModal: {
    backgroundColor: '#1E293B',
    borderRadius: 20,
    padding: 25,
    width: '90%',
    maxWidth: 400,
    alignItems: 'center',
  },
  destinationHeader: {
    alignItems: 'center',
    marginBottom: 20,
  },
  destinationTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: 'bold',
    marginTop: 10,
    textAlign: 'center',
  },
  destinationSubtitle: {
    color: '#94A3B8',
    fontSize: 14,
    marginTop: 8,
    textAlign: 'center',
  },
  destinationInputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    marginBottom: 15,
    gap: 10,
  },
  destinationInputWithMic: {
    flex: 1,
    backgroundColor: '#374151',
    borderRadius: 12,
    padding: 16,
    fontSize: 16,
    color: '#FFFFFF',
    borderWidth: 2,
    borderColor: '#4B5563',
  },
  destinationInput: {
    backgroundColor: '#374151',
    borderRadius: 12,
    padding: 16,
    fontSize: 16,
    color: '#FFFFFF',
    width: '100%',
    borderWidth: 2,
    borderColor: '#4B5563',
    marginBottom: 15,
  },
  micButton: {
    width: 50,
    height: 50,
    borderRadius: 25,
    backgroundColor: '#374151',
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: '#3B82F6',
  },
  micButtonActive: {
    backgroundColor: '#3B82F6',
    borderColor: '#3B82F6',
  },
  listeningIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 15,
    gap: 8,
  },
  listeningText: {
    color: '#3B82F6',
    fontSize: 14,
  },
  searchingContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 15,
    gap: 8,
  },
  searchingText: {
    color: '#94A3B8',
    fontSize: 14,
  },
  suggestionsContainer: {
    maxHeight: 180,
    backgroundColor: '#1E293B',
    borderRadius: 12,
    marginBottom: 15,
    borderWidth: 1,
    borderColor: '#374151',
  },
  suggestionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#374151',
    gap: 12,
  },
  suggestionTextContainer: {
    flex: 1,
  },
  suggestionAddress: {
    color: '#FFFFFF',
    fontSize: 14,
  },
  suggestionM30Status: {
    fontSize: 12,
    marginTop: 4,
  },
  calculateButton: {
    backgroundColor: '#3B82F6',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    paddingHorizontal: 20,
    borderRadius: 12,
    width: '100%',
    gap: 8,
  },
  calculateButtonDisabled: {
    opacity: 0.6,
  },
  calculateButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  fareResultContainer: {
    width: '100%',
    marginTop: 20,
  },
  fareResultBox: {
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
    borderWidth: 3,
  },
  fareInsideM30: {
    backgroundColor: '#10B98122',
    borderColor: '#10B981',
  },
  fareOutsideM30: {
    backgroundColor: '#F59E0B22',
    borderColor: '#F59E0B',
  },
  fareLocationText: {
    color: '#94A3B8',
    fontSize: 14,
    marginBottom: 10,
  },
  fareMainText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  fareDivider: {
    height: 1,
    backgroundColor: '#4B5563',
    width: '80%',
    marginVertical: 12,
  },
  fareSupplementText: {
    color: '#F59E0B',
    fontSize: 20,
    fontWeight: 'bold',
  },
  navigateToDestButton: {
    backgroundColor: '#3B82F6',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 12,
    width: '100%',
    marginTop: 15,
    gap: 10,
  },
  navigateToDestButtonText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
  },
  destinationCloseButton: {
    backgroundColor: '#64748B',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 12,
    paddingHorizontal: 20,
    borderRadius: 12,
    width: '100%',
    marginTop: 15,
    gap: 8,
  },
  destinationCloseButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '500',
  },
  // Street Fare styles
  streetFareResultContainer: {
    width: '100%',
    marginTop: 15,
  },
  streetFareBox: {
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#374151',
  },
  streetFareType: {
    fontSize: 14,
    color: '#F59E0B',
    fontWeight: '600',
    marginBottom: 10,
    textAlign: 'center',
  },
  streetFareRates: {
    backgroundColor: '#374151',
    borderRadius: 8,
    padding: 10,
    marginBottom: 12,
  },
  streetFareRateText: {
    color: '#D1D5DB',
    fontSize: 13,
    textAlign: 'center',
  },
  streetFarePriceRange: {
    alignItems: 'center',
    marginBottom: 10,
  },
  streetFarePrice: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#10B981',
  },
  streetFareDistance: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    marginBottom: 10,
  },
  streetFareDistanceText: {
    color: '#9CA3AF',
    fontSize: 14,
  },
  streetFareWarning: {
    color: '#F59E0B',
    fontSize: 12,
    textAlign: 'center',
    fontStyle: 'italic',
  },
  streetFareNavigateButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#10B981',
    paddingVertical: 14,
    paddingHorizontal: 20,
    borderRadius: 12,
    marginTop: 12,
    gap: 10,
  },
  streetFareNavigateText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  // SOS Button styles
  sosButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#374151',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 10,
  },
  sosButtonActive: {
    backgroundColor: '#EF4444',
  },
  // SOS Modal styles
  sosModalContent: {
    backgroundColor: '#1E293B',
    borderRadius: 20,
    padding: 24,
    width: '90%',
    maxWidth: 400,
    alignItems: 'center',
  },
  sosTitle: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#FFFFFF',
    marginBottom: 8,
  },
  sosDescription: {
    fontSize: 14,
    color: '#9CA3AF',
    marginBottom: 24,
    textAlign: 'center',
  },
  sosOptionOk: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#065F46',
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12,
    width: '100%',
    marginBottom: 12,
    gap: 12,
  },
  sosOptionOkText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: '600',
  },
  sosOptionAlert: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#78350F',
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12,
    width: '100%',
    marginBottom: 12,
    gap: 12,
  },
  sosOptionTextContainer: {
    flex: 1,
  },
  sosOptionAlertText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  sosOptionAlertSubtext: {
    color: '#D1D5DB',
    fontSize: 12,
    marginTop: 2,
  },
  sosOptionEmergency: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#7F1D1D',
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12,
    width: '100%',
    gap: 12,
  },
  sosOptionEmergencyText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  sosOptionEmergencySubtext: {
    color: '#FCA5A5',
    fontSize: 12,
    marginTop: 2,
  },
  sosOptionDisabled: {
    opacity: 0.5,
  },
  sosActiveHeader: {
    alignItems: 'center',
    marginBottom: 16,
  },
  sosActiveTitle: {
    fontSize: 22,
    fontWeight: 'bold',
    color: '#EF4444',
    marginTop: 8,
  },
  sosActiveDescription: {
    fontSize: 14,
    color: '#D1D5DB',
    textAlign: 'center',
    marginBottom: 20,
  },
  sosResolveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#10B981',
    paddingVertical: 16,
    paddingHorizontal: 24,
    borderRadius: 12,
    width: '100%',
    justifyContent: 'center',
    gap: 10,
    marginBottom: 12,
  },
  sosResolveButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  sosCancelButton: {
    paddingVertical: 12,
    paddingHorizontal: 24,
  },
  sosCancelButtonText: {
    color: '#9CA3AF',
    fontSize: 14,
  },
  // Alert notification banner styles
  alertNotificationBanner: {
    position: 'absolute',
    top: 100,
    left: 10,
    right: 10,
    zIndex: 1000,
  },
  alertNotificationItem: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    marginBottom: 10,
    borderWidth: 2,
    borderColor: '#EF4444',
  },
  alertNotificationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginBottom: 8,
  },
  alertNotificationTitle: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: 'bold',
  },
  alertNotificationText: {
    color: '#D1D5DB',
    fontSize: 14,
    marginBottom: 12,
  },
  alertNotificationActions: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 10,
  },
  alertNavigateButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#3B82F6',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 8,
    gap: 6,
  },
  alertNavigateButtonText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '600',
  },
  alertCallButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#EF4444',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 8,
    gap: 6,
  },
  alertCallButtonText: {
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '600',
  },
  alertDismissButton: {
    alignItems: 'center',
    paddingVertical: 8,
  },
  alertDismissText: {
    color: '#9CA3AF',
    fontSize: 13,
  },
});
