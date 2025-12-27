import React, { useState, useEffect, useCallback } from 'react';
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
  duration_minutes?: number;  // Duration for completed activities
}

interface StreetWorkData {
  // Hottest street (only load/unload)
  hottest_street: string | null;
  hottest_street_lat: number | null;
  hottest_street_lng: number | null;
  hottest_count: number;
  hottest_distance_km: number | null;
  hot_streets: HotStreet[];
  
  // Hottest station (based on exits)
  hottest_station: string | null;
  hottest_station_count: number;
  hottest_station_lat: number | null;
  hottest_station_lng: number | null;
  
  // Hottest terminal (based on exits)
  hottest_terminal: string | null;
  hottest_terminal_count: number;
  hottest_terminal_lat: number | null;
  hottest_terminal_lng: number | null;
  
  recent_activities: StreetActivity[];
  total_loads: number;
  total_unloads: number;
  total_station_entries: number;
  total_station_exits: number;
  total_terminal_entries: number;
  total_terminal_exits: number;
  last_update: string;
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
  const [shift, setShift] = useState<'all' | 'day' | 'night'>('all');
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [pushToken, setPushToken] = useState<string | null>(null);

  // Auth states
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);

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

      const location = await Location.getCurrentPositionAsync({});
      const coords = {
        latitude: location.coords.latitude,
        longitude: location.coords.longitude
      };
      setCurrentLocation(coords);

      // Get street name using reverse geocoding
      const addresses = await Location.reverseGeocodeAsync(coords);
      if (addresses.length > 0) {
        const addr = addresses[0];
        const street = addr.street || addr.name || 'Calle desconocida';
        setCurrentStreet(street);
        return { ...coords, street };
      }
      return { ...coords, street: 'Calle desconocida' };
    } catch (error) {
      console.error('Error getting location:', error);
      Alert.alert('Error', 'No se pudo obtener la ubicación');
      return null;
    }
  };

  // Register street activity (load or unload)
  const registerActivity = async (action: 'load' | 'unload') => {
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

  // Handle check-in/check-out
  const handleCheckIn = async (locationType: 'station' | 'terminal', locationName: string, action: 'entry' | 'exit') => {
    if (checkInLoading) return;
    
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
        longitude: location.longitude
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

  // Fetch street work data
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
  }, [timeWindow, currentLocation, fetchLoadStatus]);

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
      }
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [activeTab, shift, currentUser, timeWindow, fetchStreetData]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchData();
  }, [fetchData]);

  // Check for existing session on mount
  useEffect(() => {
    checkExistingSession();
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

      // Auto-refresh every 2 minutes
      const interval = setInterval(fetchData, 120000);
      return () => clearInterval(interval);
    }
  }, [activeTab, fetchData, currentUser, timeWindow]);

  // Get user location when switching to street tab
  useEffect(() => {
    if (activeTab === 'street' && currentUser && !currentLocation) {
      getCurrentLocation();
    }
  }, [activeTab, currentUser]);

  const formatLastUpdate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString('es-ES', { 
      hour: '2-digit', 
      minute: '2-digit',
      timeZone: 'Europe/Madrid'
    });
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
        
        <View style={styles.arrivalsList}>
          {station.arrivals.slice(0, 5).map((arrival, index) => (
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
      </View>
    );
  };

  // Terminal groups configuration
  const terminalGroups = [
    { name: 'T1', terminals: ['T1'], zoneName: 'Zona T1' },
    { name: 'T2-T3', terminals: ['T2', 'T3'], zoneName: 'Zona T2-T3' },
    { name: 'T4-T4S', terminals: ['T4', 'T4S'], zoneName: 'Zona T4-T4S' },
  ];

  const renderTerminalGroupCard = (group: { name: string; terminals: string[]; zoneName: string }) => {
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

    return (
      <View
        key={group.name}
        style={[
          styles.terminalGroupCard,
          isWinner && styles.winnerTerminalCard,
        ]}
      >
        {isWinner && (
          <View style={[styles.winnerBadge, styles.winnerBadgeFlight]}>
            <Ionicons name="trophy" size={14} color="#FFFFFF" />
            <Text style={styles.winnerBadgeText}>TOP</Text>
          </View>
        )}
        <Text style={[styles.terminalGroupName, isWinner && styles.winnerTerminalText]}>
          {group.zoneName}
        </Text>
        <View style={styles.terminalGroupTerminals}>
          {group.terminals.map(t => (
            <Text key={t} style={styles.terminalGroupTerminalText}>{t}</Text>
          ))}
        </View>
        <Text style={[styles.terminalCount, isWinner && styles.winnerTerminalCount]}>
          {arrivals}
        </Text>
        <Text style={styles.terminalLabel}>vuelos</Text>
        
        {/* Check-in/Check-out Button for Terminal Group */}
        {isCheckedInHere ? (
          <TouchableOpacity
            style={[styles.checkInButtonSmall, styles.checkOutButtonSmall]}
            onPress={() => handleCheckIn('terminal', checkInStatus?.location_name || group.terminals[0], 'exit')}
            disabled={checkInLoading}
          >
            <Ionicons name="exit-outline" size={16} color="#FFFFFF" />
            <Text style={styles.checkInButtonTextSmall}>SALIR</Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity
            style={styles.checkInButtonSmall}
            onPress={() => handleCheckIn('terminal', group.terminals[0], 'entry')}
            disabled={checkInLoading || (checkInStatus?.is_checked_in || false)}
          >
            <Ionicons name="enter-outline" size={16} color="#FFFFFF" />
            <Text style={styles.checkInButtonTextSmall}>ENTRAR</Text>
          </TouchableOpacity>
        )}
      </View>
    );
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
      // Use iframe for web
      const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${center.longitude - 0.05}%2C${center.latitude - 0.03}%2C${center.longitude + 0.05}%2C${center.latitude + 0.03}&layer=mapnik&marker=${center.latitude}%2C${center.longitude}`;
      return (
        <View style={styles.mapContainer}>
          <iframe
            src={mapUrl}
            style={{ width: '100%', height: '100%', border: 0 }}
            title="Map"
          />
          {markers.length > 0 && (
            <View style={styles.mapOverlay}>
              <Text style={styles.mapOverlayText}>
                📍 {markers.length} zonas activas
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

  // Open Google Maps for navigation
  const openGoogleMaps = (lat: number, lng: number, streetName: string) => {
    const url = Platform.select({
      ios: `maps://app?daddr=${lat},${lng}&dirflg=d`,
      android: `google.navigation:q=${lat},${lng}&mode=d`,
      default: `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`
    });
    
    Linking.openURL(url as string).catch(err => {
      // Fallback to web Google Maps if app not available
      Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`);
    });
  };

  const renderStreetContent = () => {
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
            {streetData?.hottest_street || 'Sin datos aún'}
          </Text>
          {streetData?.hottest_count > 0 && (
            <View style={styles.hottestStreetInfo}>
              <Text style={styles.hottestStreetCount}>
                {streetData.hottest_count} cargas/descargas en {timeWindow} min
              </Text>
              {streetData.hottest_distance_km !== null && streetData.hottest_distance_km !== undefined && (
                <View style={styles.distanceBadge}>
                  <Ionicons name="location" size={14} color="#10B981" />
                  <Text style={styles.distanceText}>
                    {streetData.hottest_distance_km.toFixed(1)} km
                  </Text>
                </View>
              )}
            </View>
          )}
          
          {/* Navigate to Google Maps button */}
          {streetData?.hottest_street && streetData?.hottest_street_lat && streetData?.hottest_street_lng && (
            <TouchableOpacity
              style={styles.navigateButton}
              onPress={() => openGoogleMaps(
                streetData.hottest_street_lat!,
                streetData.hottest_street_lng!,
                streetData.hottest_street!
              )}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Ir con Google Maps</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* === ESTACIÓN CALIENTE === */}
        <View style={[styles.hottestStreetCard, styles.stationCard]}>
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="train" size={24} color="#3B82F6" />
            <Text style={styles.hottestStreetTitle}>Estación caliente</Text>
          </View>
          <Text style={styles.hottestStreetName}>
            {streetData?.hottest_station || 'Sin datos aún'}
          </Text>
          {streetData?.hottest_station_count > 0 && (
            <Text style={styles.hottestStreetCount}>
              {streetData.hottest_station_count} salidas en {timeWindow} min
            </Text>
          )}
          
          {streetData?.hottest_station && streetData?.hottest_station_lat && streetData?.hottest_station_lng && (
            <TouchableOpacity
              style={[styles.navigateButton, styles.navigateButtonStation]}
              onPress={() => openGoogleMaps(
                streetData.hottest_station_lat!,
                streetData.hottest_station_lng!,
                streetData.hottest_station!
              )}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Ir con Google Maps</Text>
            </TouchableOpacity>
          )}
        </View>

        {/* === TERMINAL CALIENTE === */}
        <View style={[styles.hottestStreetCard, styles.terminalHotCard]}>
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="airplane" size={24} color="#8B5CF6" />
            <Text style={styles.hottestStreetTitle}>Terminal caliente</Text>
          </View>
          <Text style={styles.hottestStreetName}>
            {streetData?.hottest_terminal || 'Sin datos aún'}
          </Text>
          {streetData?.hottest_terminal_count > 0 && (
            <Text style={styles.hottestStreetCount}>
              {streetData.hottest_terminal_count} salidas en {timeWindow} min
            </Text>
          )}
          
          {streetData?.hottest_terminal && streetData?.hottest_terminal_lat && streetData?.hottest_terminal_lng && (
            <TouchableOpacity
              style={[styles.navigateButton, styles.navigateButtonTerminal]}
              onPress={() => openGoogleMaps(
                streetData.hottest_terminal_lat!,
                streetData.hottest_terminal_lng!,
                streetData.hottest_terminal!
              )}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Ir con Google Maps</Text>
            </TouchableOpacity>
          )}
              )}
            >
              <Ionicons name="navigate" size={20} color="#FFFFFF" />
              <Text style={styles.navigateButtonText}>Ir con Google Maps</Text>
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
              onPress={() => registerActivity('load')}
              disabled={streetLoading}
            >
              {streetLoading ? (
                <ActivityIndicator color="#FFFFFF" size="large" />
              ) : (
                <>
                  <Ionicons name="arrow-down-circle" size={40} color="#FFFFFF" />
                  <Text style={styles.streetButtonTextLarge}>CARGADO</Text>
                  <Text style={styles.streetButtonHint}>Toca para registrar carga</Text>
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
                    {activity.duration_minutes !== undefined && activity.duration_minutes !== null && (
                      <View style={styles.durationBadge}>
                        <Ionicons name="time-outline" size={10} color="#10B981" />
                        <Text style={styles.durationText}>{activity.duration_minutes}min</Text>
                      </View>
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
                <Ionicons name="settings" size={18} color="#F59E0B" />
              </TouchableOpacity>
            )}
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

      {/* Time Window Selector */}
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
            <View style={styles.terminalGroupsContainer}>
              {terminalGroups.map(group => renderTerminalGroupCard(group))}
            </View>
            {renderFlightsList()}
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
    borderWidth: 2,
    borderColor: 'transparent',
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
  navigateButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
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
  mapOverlay: {
    position: 'absolute',
    bottom: 10,
    left: 10,
    backgroundColor: 'rgba(15, 23, 42, 0.9)',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
  },
  mapOverlayText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '500',
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
});
