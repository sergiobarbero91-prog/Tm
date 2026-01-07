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
import { Audio } from 'expo-av';

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
  // Weighted score fields
  score_30min?: number;
  score_60min?: number;
  past_30min?: number;  // Arrivals in past 15 min (half of 30)
  past_60min?: number;  // Arrivals in past 30 min (half of 60)
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
  // Weighted score fields
  score_30min?: number;
  score_60min?: number;
  past_30min?: number;
  past_60min?: number;
}

interface FlightComparison {
  terminals: { [key: string]: TerminalData };
  winner_30min: string;
  winner_60min: string;
  last_update: string;
  message?: string;
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
  full_name: string | null;
  license_number: string | null;
  phone: string | null;
  role: string;
  preferred_shift: string;
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
  const [activeTab, setActiveTab] = useState<'trains' | 'flights' | 'street' | 'events' | 'admin'>('street');
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
  
  // Station alerts states (sin taxis / barandilla)
  const [stationAlerts, setStationAlerts] = useState<{
    alerts: any[];
    stations_with_alerts: string[];
    terminals_with_alerts: string[];
  }>({ alerts: [], stations_with_alerts: [], terminals_with_alerts: [] });
  const [reportingAlert, setReportingAlert] = useState(false);
  const [alertTimerTick, setAlertTimerTick] = useState(0); // For real-time alert timer updates
  const [alertsFetchedAt, setAlertsFetchedAt] = useState<number>(Date.now()); // When alerts were last fetched
  
  // Time range selector states
  const [selectedTimeRange, setSelectedTimeRange] = useState<string>('now');
  const [showTimeRangeDropdown, setShowTimeRangeDropdown] = useState(false);
  
  // Dropdown selector states
  const [showPageDropdown, setShowPageDropdown] = useState(false);
  const [showShiftDropdown, setShowShiftDropdown] = useState(false);

  // Events states
  const [eventsData, setEventsData] = useState<any[]>([]);
  const [showAddEventModal, setShowAddEventModal] = useState(false);
  const [newEventLocation, setNewEventLocation] = useState('');
  const [newEventDescription, setNewEventDescription] = useState('');
  const [newEventTime, setNewEventTime] = useState('');
  const [eventLoading, setEventLoading] = useState(false);

  // Admin Panel states
  const [adminUsers, setAdminUsers] = useState<User[]>([]);
  const [adminLoading, setAdminLoading] = useState(false);
  const [showCreateUserModal, setShowCreateUserModal] = useState(false);
  const [showEditUserModal, setShowEditUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [newUserUsername, setNewUserUsername] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserRole, setNewUserRole] = useState<'user' | 'moderator' | 'admin'>('user');
  const [newUserPhone, setNewUserPhone] = useState('');
  
  // Admin Panel - Search and Stats
  const [adminSearchQuery, setAdminSearchQuery] = useState('');
  const [adminSearchResults, setAdminSearchResults] = useState<User[]>([]);
  const [adminSearching, setAdminSearching] = useState(false);
  const [adminStats, setAdminStats] = useState<{total_users: number; active_last_month: number; online_now: number} | null>(null);
  const [showUsersList, setShowUsersList] = useState(false);
  
  // Admin Panel - Blocked Users Management
  const [showBlockedUsers, setShowBlockedUsers] = useState(false);
  const [blockedUsersData, setBlockedUsersData] = useState<{
    total_blocked: number;
    alert_blocks: number;
    chat_blocks: number;
    permanent_blocks: number;
    blocked_users: Array<{
      id: string;
      username: string;
      full_name?: string;
      license_number?: string;
      // Alert fraud
      alert_fraud_count: number;
      alert_blocked_until?: string;
      last_fraud_at?: string;
      alert_block_status: string;
      alert_hours_remaining?: number;
      // Chat abuse
      chat_abuse_count: number;
      chat_blocked_until?: string;
      last_chat_abuse_at?: string;
      last_chat_abuse_message?: string;
      chat_block_status: string;
      chat_hours_remaining?: number;
      // Combined
      block_reasons: string[];
    }>;
  } | null>(null);
  const [blockedUsersLoading, setBlockedUsersLoading] = useState(false);

  // Auth states
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);
  
  // Registration states
  const [showRegister, setShowRegister] = useState(false);
  const [registerUsername, setRegisterUsername] = useState('');
  const [registerPassword, setRegisterPassword] = useState('');
  const [registerPasswordConfirm, setRegisterPasswordConfirm] = useState('');
  const [registerFullName, setRegisterFullName] = useState('');
  const [registerLicenseNumber, setRegisterLicenseNumber] = useState('');
  const [registerPhone, setRegisterPhone] = useState('');
  const [registerPreferredShift, setRegisterPreferredShift] = useState<'all' | 'day' | 'night'>('all');
  const [registerLoading, setRegisterLoading] = useState(false);
  
  // Profile editing states
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [profileFullName, setProfileFullName] = useState('');
  const [profileLicenseNumber, setProfileLicenseNumber] = useState('');
  const [profilePhone, setProfilePhone] = useState('');
  const [profilePreferredShift, setProfilePreferredShift] = useState<'all' | 'day' | 'night'>('all');
  const [profileLoading, setProfileLoading] = useState(false);
  
  // Password change states
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  const [passwordChangeLoading, setPasswordChangeLoading] = useState(false);

  // Chat states
  const [showChatModal, setShowChatModal] = useState(false);
  const [chatChannels, setChatChannels] = useState<Array<{
    id: string;
    name: string;
    icon: string;
    description: string;
    can_write: boolean;
  }>>([]);
  const [activeChannel, setActiveChannel] = useState<string>('global');
  const [chatMessages, setChatMessages] = useState<Array<{
    id: string;
    user_id: string;
    username: string;
    full_name: string | null;
    message: string;
    created_at: string;
  }>>([]);
  const [chatMessage, setChatMessage] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [canWriteChat, setCanWriteChat] = useState(true);

  // Radio states
  const [showRadioDropdown, setShowRadioDropdown] = useState(false);
  const [radioChannels, setRadioChannels] = useState<Array<{
    channel: number;
    channel_name: string;
    user_count: number;
    is_busy: boolean;
  }>>([]);
  const [radioChannel, setRadioChannel] = useState<number>(1);
  const [radioConnected, setRadioConnected] = useState(false);
  const [radioMuted, setRadioMuted] = useState(false);
  const [radioTransmitting, setRadioTransmitting] = useState(false);
  const [radioUsers, setRadioUsers] = useState<Array<{
    user_id: string;
    username: string;
    full_name?: string;
    is_transmitting: boolean;
  }>>([]);
  const [radioWs, setRadioWs] = useState<WebSocket | null>(null);
  const [radioChannelBusy, setRadioChannelBusy] = useState(false);
  const [radioTransmittingUser, setRadioTransmittingUser] = useState<string | null>(null);

  // License Alerts states
  const [showAlertsModal, setShowAlertsModal] = useState(false);
  const [showCreateAlertModal, setShowCreateAlertModal] = useState(false);
  const [licenseAlerts, setLicenseAlerts] = useState<Array<{
    id: string;
    sender_full_name: string;
    sender_license: string;
    alert_type: string;
    message: string;
    is_read: boolean;
    created_at: string;
  }>>([]);
  const [alertsUnreadCount, setAlertsUnreadCount] = useState(0);
  const [alertTargetLicense, setAlertTargetLicense] = useState('');
  const [alertType, setAlertType] = useState<'lost_item' | 'general'>('lost_item');
  const [alertMessage, setAlertMessage] = useState('');
  const [alertLoading, setAlertLoading] = useState(false);
  const [licenseSuggestions, setLicenseSuggestions] = useState<Array<{
    license_number: string;
    full_name: string;
    username: string;
  }>>([]);
  const [selectedRecipient, setSelectedRecipient] = useState<{
    license_number: string;
    full_name: string;
  } | null>(null);
  const [searchingLicense, setSearchingLicense] = useState(false);

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

  // Handle registration
  const handleRegister = async () => {
    if (!registerUsername || !registerPassword || !registerFullName || !registerLicenseNumber) {
      Alert.alert('Error', 'Por favor completa los campos obligatorios: usuario, contraseña, nombre y licencia');
      return;
    }

    if (registerPassword !== registerPasswordConfirm) {
      Alert.alert('Error', 'Las contraseñas no coinciden');
      return;
    }

    if (registerPassword.length < 4) {
      Alert.alert('Error', 'La contraseña debe tener al menos 4 caracteres');
      return;
    }

    if (!/^\d+$/.test(registerLicenseNumber)) {
      Alert.alert('Error', 'El número de licencia debe contener solo dígitos');
      return;
    }

    setRegisterLoading(true);
    try {
      const response = await axios.post(`${API_BASE}/api/auth/register`, {
        username: registerUsername,
        password: registerPassword,
        full_name: registerFullName,
        license_number: registerLicenseNumber,
        phone: registerPhone || null,
        preferred_shift: registerPreferredShift
      });

      const { access_token, user } = response.data;
      await AsyncStorage.setItem('token', access_token);
      await AsyncStorage.setItem('user', JSON.stringify(user));
      
      setCurrentUser(user);
      
      // Clear registration form
      setRegisterUsername('');
      setRegisterPassword('');
      setRegisterPasswordConfirm('');
      setRegisterFullName('');
      setRegisterLicenseNumber('');
      setRegisterPhone('');
      setRegisterPreferredShift('all');
      setShowRegister(false);
      
      Alert.alert('¡Bienvenido!', `Registro exitoso, ${user.full_name}`);
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al registrar usuario');
    } finally {
      setRegisterLoading(false);
    }
  };

  // Change password function
  const handleChangePassword = async () => {
    if (!currentPassword || !newPassword || !newPasswordConfirm) {
      Alert.alert('Error', 'Por favor completa todos los campos');
      return;
    }

    if (newPassword !== newPasswordConfirm) {
      Alert.alert('Error', 'Las contraseñas nuevas no coinciden');
      return;
    }

    if (newPassword.length < 4) {
      Alert.alert('Error', 'La contraseña debe tener al menos 4 caracteres');
      return;
    }

    setPasswordChangeLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.put(`${API_BASE}/api/auth/password`, {
        current_password: currentPassword,
        new_password: newPassword
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Contraseña actualizada correctamente');
      setShowChangePasswordModal(false);
      setCurrentPassword('');
      setNewPassword('');
      setNewPasswordConfirm('');
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al cambiar la contraseña');
    } finally {
      setPasswordChangeLoading(false);
    }
  };

  // Open profile modal with current user data
  const openProfileModal = () => {
    if (currentUser) {
      setProfileFullName(currentUser.full_name || '');
      setProfileLicenseNumber(currentUser.license_number || '');
      setProfilePhone(currentUser.phone || '');
      setProfilePreferredShift((currentUser.preferred_shift as 'all' | 'day' | 'night') || 'all');
      setShowProfileModal(true);
    }
  };

  // Update profile
  const handleUpdateProfile = async () => {
    if (!profileFullName || !profileLicenseNumber) {
      Alert.alert('Error', 'Nombre y licencia son obligatorios');
      return;
    }

    if (!/^\d+$/.test(profileLicenseNumber)) {
      Alert.alert('Error', 'El número de licencia debe contener solo dígitos');
      return;
    }

    setProfileLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.put(`${API_BASE}/api/auth/profile`, {
        full_name: profileFullName,
        license_number: profileLicenseNumber,
        phone: profilePhone || null,
        preferred_shift: profilePreferredShift
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      const updatedUser = response.data;
      setCurrentUser(updatedUser);
      await AsyncStorage.setItem('user', JSON.stringify(updatedUser));
      
      setShowProfileModal(false);
      Alert.alert('✓', 'Perfil actualizado correctamente');
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al actualizar perfil');
    } finally {
      setProfileLoading(false);
    }
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
    
    // Normalize Spanish numbers immediately for display
    const normalizedText = normalizeSpanishNumbers(text);
    if (normalizedText !== text) {
      setStreetDestinationAddress(normalizedText);
    }
    
    // Reduced debounce time from 500ms to 300ms for faster response
    streetSearchTimeoutRef.current = setTimeout(() => {
      searchStreetAddresses(normalizedText);
    }, 300);
  };

  // Select a street address suggestion
  const selectStreetAddress = (suggestion: typeof streetAddressSuggestions[0]) => {
    setStreetSelectedAddress(suggestion);
    setStreetDestinationAddress(suggestion.address);
    setStreetAddressSuggestions([]);
  };

  // Calculate street fare based on distance and time
  const calculateStreetFare = async () => {
    if (!streetSelectedAddress) {
      Alert.alert('Error', 'Selecciona una dirección de destino');
      return;
    }
    
    // Use current location or Madrid center as fallback
    const fromLocation = currentLocation || { latitude: 40.4168, longitude: -3.7038 };
    
    setStreetCalculatingFare(true);
    try {
      // Get auth token
      const authToken = await AsyncStorage.getItem('token');
      
      // Call backend to get real route distance using OSRM
      let distance_km: number;
      let routeSource = 'osrm';
      
      try {
        const routeResponse = await axios.post(`${API_BASE}/api/calculate-route-distance`, {
          origin_lat: fromLocation.latitude,
          origin_lng: fromLocation.longitude,
          dest_lat: streetSelectedAddress.latitude,
          dest_lng: streetSelectedAddress.longitude
        }, {
          headers: { Authorization: `Bearer ${authToken}` },
          timeout: 15000
        });
        
        if (routeResponse.data.success) {
          distance_km = routeResponse.data.distance_km;
          routeSource = routeResponse.data.source;
          console.log(`Route calculated via ${routeSource}: ${distance_km}km (straight line: ${routeResponse.data.straight_line_km}km)`);
        } else {
          throw new Error('Route calculation failed');
        }
      } catch (routeError) {
        console.log('OSRM route failed, using local Haversine fallback:', routeError);
        
        // Fallback: Calculate distance using Haversine formula with 1.3x urban factor
        const R = 6371; // Earth's radius in km
        const lat1 = fromLocation.latitude * Math.PI / 180;
        const lat2 = streetSelectedAddress.latitude * Math.PI / 180;
        const dLat = (streetSelectedAddress.latitude - fromLocation.latitude) * Math.PI / 180;
        const dLon = (streetSelectedAddress.longitude - fromLocation.longitude) * Math.PI / 180;
        
        const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                  Math.cos(lat1) * Math.cos(lat2) *
                  Math.sin(dLon/2) * Math.sin(dLon/2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        const straight_line_km = R * c;
        
        // Apply urban route factor of 1.3 (typical for Madrid)
        distance_km = straight_line_km * 1.3;
        routeSource = 'haversine_estimated';
      }
      
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
        // Night (21:00-6:00) or Weekend: 3.20€ + 1.60€/km
        base_fare = 3.20;
        per_km_rate = 1.60;
      } else {
        // Weekday (Mon-Fri 6:00-21:00): 2.55€ + 1.40€/km
        base_fare = 2.55;
        per_km_rate = 1.40;
      }
      
      const base_calculation = base_fare + (distance_km * per_km_rate);
      const fare_min = base_calculation * 1.02; // +2%
      const fare_max = base_calculation * 1.07; // +7%
      
      setStreetFareResult({
        distance_km: distance_km,
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
    // First, open GPS with destination (before anything else)
    if (streetSelectedAddress) {
      openGpsNavigation(
        streetSelectedAddress.latitude,
        streetSelectedAddress.longitude,
        streetSelectedAddress.address
      );
    }
    
    // Then register the load activity (without opening GPS again)
    await registerActivityWithoutGps('load');
    
    // Close modal and reset state
    setShowStreetFareModal(false);
    setStreetDestinationAddress('');
    setStreetAddressSuggestions([]);
    setStreetSelectedAddress(null);
    setStreetFareResult(null);
  };

  // Register activity without opening GPS (for use after fare calculation)
  const registerActivityWithoutGps = async (action: 'load' | 'unload') => {
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

      // Don't show alert to avoid interrupting GPS navigation
      // Refresh street data in background
      fetchStreetData();
    } catch (error: any) {
      console.log('Error registering activity:', error);
    } finally {
      setStreetLoading(false);
    }
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
  const selectAddress = async (suggestion: typeof addressSuggestions[0]) => {
    setSelectedAddress(suggestion);
    setDestinationAddress(suggestion.address);
    setAddressSuggestions([]);
    
    // Calculate fare immediately
    setCalculatingFare(true);
    await calculateFareFromAddress(suggestion);
    setCalculatingFare(false);
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
      
      // Show destination modal for fare calculation (both terminals and stations)
      setShowDestinationModal(true);
      setDestinationAddress('');
      setAddressSuggestions([]);
      setSelectedAddress(null);
      setFareResult(null);
    }
  };

  // Calculate fare from selected address (for terminal or station exit)
  const calculateFareFromAddress = async (address: { latitude: number; longitude: number; address: string; is_inside_m30: boolean }) => {
    // Get current time and day
    const now = new Date();
    const hour = now.getHours();
    const dayOfWeek = now.getDay(); // 0 = Sunday, 6 = Saturday
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const isDaytime = hour >= 6 && hour < 21;
    const isNightOrWeekend = isWeekend || !isDaytime;
    
    const per_km_rate = isNightOrWeekend ? 1.60 : 1.40;
    const locationType = pendingCheckOut?.locationType || 'terminal';
    
    let tarifa: string;
    let suplemento: string;
    
    if (locationType === 'station') {
      // STATION FARE: 8€ for first 1.4 km + per km rate after that
      try {
        // Get coordinates of the station
        const stationName = pendingCheckOut?.locationName || 'Atocha';
        const stationCoords = stationName === 'Chamartín' 
          ? { lat: 40.4722, lng: -3.6825 }  // Chamartín
          : { lat: 40.4065, lng: -3.6895 }; // Atocha
        
        const token = await AsyncStorage.getItem('token');
        const routeResponse = await axios.post(`${API_BASE}/api/calculate-route-distance`, {
          origin_lat: stationCoords.lat,
          origin_lng: stationCoords.lng,
          dest_lat: address.latitude,
          dest_lng: address.longitude
        }, {
          headers: { Authorization: `Bearer ${token}` },
          timeout: 15000
        });
        
        const distance_km = routeResponse.data.distance_km || 0;
        
        // First 1.4 km included in base fare of 8€
        const extra_km = Math.max(0, distance_km - 1.4);
        const extra_fare = extra_km * per_km_rate;
        const base_total = 8 + extra_fare;
        
        // Calculate range: +2% to +7%
        const fare_min = base_total * 1.02;
        const fare_max = base_total * 1.07;
        
        if (extra_km > 0) {
          tarifa = isNightOrWeekend ? 'Tarifa Estación + T2' : 'Tarifa Estación + T1';
          suplemento = `${fare_min.toFixed(2)}€ - ${fare_max.toFixed(2)}€`;
        } else {
          tarifa = 'Tarifa Estación';
          const min_base = 8 * 1.02;
          const max_base = 8 * 1.07;
          suplemento = `${min_base.toFixed(2)}€ - ${max_base.toFixed(2)}€`;
        }
      } catch (error) {
        console.log('Error calculating distance for station fare:', error);
        tarifa = isNightOrWeekend ? 'Tarifa Estación + T2' : 'Tarifa Estación + T1';
        suplemento = isNightOrWeekend ? '8€ + 1,60€/km (después de 1,4km)' : '8€ + 1,40€/km (después de 1,4km)';
      }
    } else {
      // TERMINAL/AIRPORT FARE
      if (address.is_inside_m30) {
        // Inside M30: Fixed fare of 33€ (no range)
        tarifa = 'Tarifa Fija';
        suplemento = '33,00€';
      } else {
        // Outside M30: 22€ for first 9 km + per km rate after that
        try {
          // Get distance from airport (T4) to destination
          const airportLat = 40.4719; // T4 coordinates
          const airportLng = -3.5357;
          
          const token = await AsyncStorage.getItem('token');
          const routeResponse = await axios.post(`${API_BASE}/api/calculate-route-distance`, {
            origin_lat: airportLat,
            origin_lng: airportLng,
            dest_lat: address.latitude,
            dest_lng: address.longitude
          }, {
            headers: { Authorization: `Bearer ${token}` },
            timeout: 15000
          });
          
          const distance_km = routeResponse.data.distance_km || 0;
          
          // First 9 km included in base fare of 22€
          const extra_km = Math.max(0, distance_km - 9);
          const extra_fare = extra_km * per_km_rate;
          const base_total = 22 + extra_fare;
          
          // Calculate range: +2% to +7%
          const fare_min = base_total * 1.02;
          const fare_max = base_total * 1.07;
          
          if (extra_km > 0) {
            tarifa = isNightOrWeekend ? 'Tarifa 3 + Tarifa 2' : 'Tarifa 3 + Tarifa 1';
            suplemento = `${fare_min.toFixed(2)}€ - ${fare_max.toFixed(2)}€`;
          } else {
            tarifa = 'Tarifa 3';
            const min_base = 22 * 1.02;
            const max_base = 22 * 1.07;
            suplemento = `${min_base.toFixed(2)}€ - ${max_base.toFixed(2)}€`;
          }
        } catch (error) {
          console.log('Error calculating distance for airport fare:', error);
          tarifa = isNightOrWeekend ? 'Tarifa 3 + Tarifa 2' : 'Tarifa 3 + Tarifa 1';
          suplemento = isNightOrWeekend ? '22€ + 1,60€/km (después de 9km)' : '22€ + 1,40€/km (después de 9km)';
        }
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
      setCalculatingFare(true);
      await calculateFareFromAddress(selectedAddress);
      setCalculatingFare(false);
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
      
      // If a specific time range is selected (not "now"), calculate start_time and end_time
      console.log(`[Street] Current selectedTimeRange: ${selectedTimeRange}`);
      if (selectedTimeRange !== 'now') {
        // Regenerate options to get current hour context
        const now = new Date();
        const currentHour = now.getHours();
        
        let targetStartHour: number | null = null;
        let targetEndHour: number | null = null;
        let hoursOffset = 0;
        
        if (selectedTimeRange.startsWith('past-')) {
          const pastIndex = parseInt(selectedTimeRange.replace('past-', ''));
          hoursOffset = -pastIndex;
          targetStartHour = (currentHour + hoursOffset + 24) % 24;
          targetEndHour = (targetStartHour + 1) % 24;
        } else if (selectedTimeRange.startsWith('future-')) {
          const futureIndex = parseInt(selectedTimeRange.replace('future-', ''));
          hoursOffset = futureIndex;
          targetStartHour = (currentHour + hoursOffset) % 24;
          targetEndHour = (targetStartHour + 1) % 24;
        }
        
        if (targetStartHour !== null && targetEndHour !== null) {
          const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
          
          // Calculate the start time for the selected hour slot
          let startDate = new Date(today);
          startDate.setHours(targetStartHour, 0, 0, 0);
          
          let endDate = new Date(today);
          endDate.setHours(targetEndHour, 0, 0, 0);
          
          // Handle day boundary
          if (targetEndHour === 0) {
            endDate.setDate(endDate.getDate() + 1);
          }
          
          // Adjust for past/future days
          if (hoursOffset < 0) {
            // Past: if startDate is in the future, subtract a day
            if (startDate > now) {
              startDate.setDate(startDate.getDate() - 1);
              endDate.setDate(endDate.getDate() - 1);
            }
          } else if (hoursOffset > 0) {
            // Future: if startDate is in the past (more than 12h ago), add a day
            const hoursDiff = (now.getTime() - startDate.getTime()) / (1000 * 60 * 60);
            if (hoursDiff > 12) {
              startDate.setDate(startDate.getDate() + 1);
              endDate.setDate(endDate.getDate() + 1);
            }
          }
          
          params.start_time = startDate.toISOString();
          params.end_time = endDate.toISOString();
          console.log(`[Street] Fetching data for time range: ${startDate.toLocaleString()} to ${endDate.toLocaleString()}`);
        }
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
  }, [timeWindow, selectedTimeRange, fetchLoadStatus]); // currentLocation excluded to prevent constant refetching - location is read at call time

  // Fetch station alerts (sin taxis / barandilla)
  const fetchStationAlerts = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE}/api/station-alerts/active`);
      setStationAlerts(response.data);
      setAlertsFetchedAt(Date.now()); // Record when we fetched the alerts
    } catch (error) {
      console.error('Error fetching station alerts:', error);
    }
  }, []);

  // Report station alert
  const reportStationAlert = async (locationType: string, locationName: string, alertType: 'sin_taxis' | 'barandilla') => {
    if (reportingAlert) return;
    
    setReportingAlert(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/station-alerts/report`, {
        location_type: locationType,
        location_name: locationName,
        alert_type: alertType
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Refresh alerts
      await fetchStationAlerts();
      
      const alertLabel = alertType === 'sin_taxis' ? 'Sin taxis' : 'Barandilla';
      Alert.alert('Aviso enviado', `${alertLabel} reportado para ${locationName}. Durará 5 minutos.`);
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al enviar el aviso');
    } finally {
      setReportingAlert(false);
    }
  };

  // Cancel an alert by location
  const cancelStationAlert = async (locationType: string, locationName: string, alertType: string) => {
    if (reportingAlert) return;
    
    setReportingAlert(true);
    try {
      const token = await SecureStore.getItemAsync('userToken');
      if (!token) {
        Alert.alert('Error', 'Debes iniciar sesión');
        setReportingAlert(false);
        return;
      }
      
      const response = await axios.post(`${API_BASE}/api/station-alerts/cancel-by-location`, {
        location_type: locationType,
        location_name: locationName,
        alert_type: alertType
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Refresh alerts
      await fetchStationAlerts();
      
      // Check if fraud was detected and show appropriate message
      if (response.data.fraud_detected) {
        Alert.alert(
          '⚠️ Aviso Incorrecto Detectado',
          'El aviso ha sido cerrado. El usuario que lo reportó ha sido notificado.\n\nRecuerda: Los avisos deben reflejar la situación real para ayudar a todos los compañeros.',
          [{ text: 'Entendido' }]
        );
      } else {
        Alert.alert('Alerta cerrada', 'La alerta ha sido cerrada correctamente.');
      }
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al cerrar la alerta');
    } finally {
      setReportingAlert(false);
    }
  };

  // Check if user can close an alert (not the reporter within first minute)
  const canUserCloseAlert = (alert: any) => {
    if (!currentUser) return false;
    
    // If user is NOT the reporter, they can always close
    if (alert.reported_by !== currentUser.id) return true;
    
    // If user IS the reporter, check if 1 minute has passed
    const elapsedSinceFetch = Math.floor((Date.now() - alertsFetchedAt) / 1000);
    const actualSecondsAgo = alert.seconds_ago + elapsedSinceFetch;
    
    return actualSecondsAgo >= 60;
  };

  // Get remaining seconds before user can close their own alert
  const getSecondsUntilCanClose = (alert: any) => {
    if (!currentUser || alert.reported_by !== currentUser.id) return 0;
    
    const elapsedSinceFetch = Math.floor((Date.now() - alertsFetchedAt) / 1000);
    const actualSecondsAgo = alert.seconds_ago + elapsedSinceFetch;
    
    return Math.max(0, 60 - actualSecondsAgo);
  };

  // Get alert info for a specific location
  const getLocationAlerts = (locationType: string, locationName: string) => {
    const normalizedName = locationType === 'station' ? locationName.toLowerCase() : locationName;
    return stationAlerts.alerts.filter(
      alert => alert.location_type === locationType && alert.location_name === normalizedName
    );
  };

  // Format seconds ago as "Xm Xs" - calculates real-time based on backend seconds_ago + elapsed time
  const formatSecondsAgo = (backendSecondsAgo: number, _createdAt?: string) => {
    // Calculate how many seconds have passed since we fetched the alerts
    const elapsedSinceFetch = Math.floor((Date.now() - alertsFetchedAt) / 1000);
    
    // Total seconds = backend's seconds_ago + time elapsed since fetch
    let actualSeconds = backendSecondsAgo + elapsedSinceFetch;
    
    // Prevent negative values
    if (actualSeconds < 0) actualSeconds = 0;
    
    // Cap at 5 minutes (300 seconds) since alerts expire after 5 min
    if (actualSeconds > 300) actualSeconds = 300;
    
    // Add alertTimerTick to trigger re-render
    const _ = alertTimerTick;
    
    const mins = Math.floor(actualSeconds / 60);
    const secs = actualSeconds % 60;
    if (mins > 0) {
      return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
  };

  // Fetch events data
  const fetchEventsData = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/events`, {
        params: { shift },
        headers: { Authorization: `Bearer ${token}` }
      });
      setEventsData(response.data.events || []);
    } catch (error) {
      console.error('Error fetching events:', error);
    }
  }, [shift]);

  // Create new event
  const createEvent = async () => {
    if (!newEventLocation.trim() || !newEventDescription.trim() || !newEventTime.trim()) {
      Alert.alert('Error', 'Por favor, rellena todos los campos');
      return;
    }
    
    // Validate time format
    const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/;
    if (!timeRegex.test(newEventTime)) {
      Alert.alert('Error', 'Formato de hora inválido. Usa HH:MM');
      return;
    }
    
    setEventLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/events`, {
        location: newEventLocation.trim(),
        description: newEventDescription.trim(),
        event_time: newEventTime.trim()
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Reset form and close modal
      setNewEventLocation('');
      setNewEventDescription('');
      setNewEventTime('');
      setShowAddEventModal(false);
      
      // Refresh events
      fetchEventsData();
    } catch (error: any) {
      console.error('Error creating event:', error);
      Alert.alert('Error', error.response?.data?.detail || 'Error al crear el evento');
    } finally {
      setEventLoading(false);
    }
  };

  // Vote on event
  const voteEvent = async (eventId: string, voteType: 'like' | 'dislike') => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(`${API_BASE}/api/events/${eventId}/vote`, {
        vote_type: voteType
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Update local state
      setEventsData(prev => prev.map(event => 
        event.event_id === eventId 
          ? { ...event, likes: response.data.likes, dislikes: response.data.dislikes, user_vote: response.data.user_vote }
          : event
      ));
    } catch (error) {
      console.error('Error voting:', error);
    }
  };

  // Delete event
  const deleteEvent = async (eventId: string) => {
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.delete(`${API_BASE}/api/events/${eventId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Remove from local state
      setEventsData(prev => prev.filter(event => event.event_id !== eventId));
    } catch (error: any) {
      console.error('Error deleting event:', error);
      Alert.alert('Error', error.response?.data?.detail || 'Error al eliminar el evento');
    }
  };

  // ========== ADMIN FUNCTIONS ==========
  
  // Fetch all users (admin only)
  const fetchAdminUsers = useCallback(async () => {
    if (currentUser?.role !== 'admin') return;
    
    setAdminLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/admin/users`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setAdminUsers(response.data);
    } catch (error: any) {
      console.error('Error fetching users:', error);
      Alert.alert('Error', 'No se pudieron cargar los usuarios');
    } finally {
      setAdminLoading(false);
    }
  }, [currentUser?.role]);

  // Fetch admin stats
  const fetchAdminStats = useCallback(async () => {
    if (currentUser?.role !== 'admin') return;
    
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/admin/stats`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setAdminStats(response.data);
    } catch (error: any) {
      console.error('Error fetching admin stats:', error);
    }
  }, [currentUser?.role]);

  // Search users (admin only)
  const searchUsers = useCallback(async (query: string) => {
    if (currentUser?.role !== 'admin' || !query.trim()) {
      setAdminSearchResults([]);
      return;
    }
    
    setAdminSearching(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/admin/search`, {
        headers: { Authorization: `Bearer ${token}` },
        params: { q: query.trim() }
      });
      setAdminSearchResults(response.data);
    } catch (error: any) {
      console.error('Error searching users:', error);
      setAdminSearchResults([]);
    } finally {
      setAdminSearching(false);
    }
  }, [currentUser?.role]);

  // Debounced search
  useEffect(() => {
    if (adminSearchQuery.length >= 1) {
      const timer = setTimeout(() => {
        searchUsers(adminSearchQuery);
      }, 300);
      return () => clearTimeout(timer);
    } else {
      setAdminSearchResults([]);
    }
  }, [adminSearchQuery, searchUsers]);

  // Fetch blocked users (admin only)
  const fetchBlockedUsers = useCallback(async () => {
    if (currentUser?.role !== 'admin') return;
    
    setBlockedUsersLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/admin/blocked-users`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setBlockedUsersData(response.data);
    } catch (error: any) {
      console.error('Error fetching blocked users:', error);
    } finally {
      setBlockedUsersLoading(false);
    }
  }, [currentUser?.role]);

  // Unblock a user (admin only)
  const unblockUser = async (userId: string) => {
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/admin/users/${userId}/unblock`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      Alert.alert('Usuario desbloqueado', 'El usuario puede volver a enviar avisos.');
      fetchBlockedUsers();
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'Error al desbloquear usuario');
    }
  };

  // Reset fraud count for a user (admin only)
  const resetFraudCount = async (userId: string) => {
    Alert.alert(
      'Resetear contador',
      '¿Estás seguro de que quieres resetear el contador de fraudes? El usuario podrá volver a enviar avisos sin historial.',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Resetear',
          style: 'destructive',
          onPress: async () => {
            try {
              const token = await AsyncStorage.getItem('token');
              await axios.post(`${API_BASE}/api/admin/users/${userId}/reset-fraud`, {}, {
                headers: { Authorization: `Bearer ${token}` }
              });
              Alert.alert('Contador reseteado', 'El contador de fraudes ha sido reseteado a 0.');
              fetchBlockedUsers();
            } catch (error: any) {
              Alert.alert('Error', error.response?.data?.detail || 'Error al resetear contador');
            }
          }
        }
      ]
    );
  };

  // Send heartbeat periodically to update last_seen
  useEffect(() => {
    if (!currentUser) return;
    
    const sendHeartbeat = async () => {
      try {
        const token = await AsyncStorage.getItem('token');
        if (token) {
          await axios.post(`${API_BASE}/api/auth/heartbeat`, {}, {
            headers: { Authorization: `Bearer ${token}` }
          });
        }
      } catch (error) {
        // Silently ignore heartbeat errors
      }
    };
    
    // Send immediately and then every 2 minutes
    sendHeartbeat();
    const interval = setInterval(sendHeartbeat, 120000);
    
    return () => clearInterval(interval);
  }, [currentUser]);

  // Create new user (admin only)
  const createUser = async () => {
    if (!newUserUsername.trim() || !newUserPassword.trim()) {
      Alert.alert('Error', 'Usuario y contraseña son obligatorios');
      return;
    }

    setAdminLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/admin/users`, {
        username: newUserUsername.trim(),
        password: newUserPassword,
        role: newUserRole,
        phone: newUserPhone.trim() || null
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Usuario creado correctamente');
      setShowCreateUserModal(false);
      setNewUserUsername('');
      setNewUserPassword('');
      setNewUserRole('user');
      setNewUserPhone('');
      fetchAdminUsers();
    } catch (error: any) {
      console.error('Error creating user:', error);
      Alert.alert('Error', error.response?.data?.detail || 'Error al crear usuario');
    } finally {
      setAdminLoading(false);
    }
  };

  // Update user role (admin only)
  const updateUserRole = async (userId: string, newRole: string) => {
    setAdminLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.put(`${API_BASE}/api/admin/users/${userId}`, {
        role: newRole
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('Éxito', 'Rol actualizado correctamente');
      setShowEditUserModal(false);
      setEditingUser(null);
      fetchAdminUsers();
    } catch (error: any) {
      console.error('Error updating user:', error);
      Alert.alert('Error', error.response?.data?.detail || 'Error al actualizar usuario');
    } finally {
      setAdminLoading(false);
    }
  };

  // Delete user (admin only)
  const deleteUser = async (userId: string, username: string) => {
    Alert.alert(
      'Eliminar Usuario',
      `¿Estás seguro de que quieres eliminar a "${username}"?`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            setAdminLoading(true);
            try {
              const token = await AsyncStorage.getItem('token');
              await axios.delete(`${API_BASE}/api/admin/users/${userId}`, {
                headers: { Authorization: `Bearer ${token}` }
              });

              Alert.alert('Éxito', 'Usuario eliminado');
              fetchAdminUsers();
            } catch (error: any) {
              console.error('Error deleting user:', error);
              Alert.alert('Error', error.response?.data?.detail || 'Error al eliminar usuario');
            } finally {
              setAdminLoading(false);
            }
          }
        }
      ]
    );
  };

  // Get role badge color
  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'admin': return '#EF4444';
      case 'moderator': return '#F59E0B';
      default: return '#6B7280';
    }
  };

  // Get role display name
  const getRoleDisplayName = (role: string) => {
    switch (role) {
      case 'admin': return 'Administrador';
      case 'moderator': return 'Moderador';
      default: return 'Usuario';
    }
  };

  // ========== RADIO FUNCTIONS ==========
  
  // Fetch radio channels
  const fetchRadioChannels = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/radio/channels`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setRadioChannels(response.data.channels);
    } catch (error) {
      console.error('Error fetching radio channels:', error);
    }
  }, []);

  // Connect to radio channel via WebSocket
  const connectToRadioChannel = useCallback(async (channel: number) => {
    try {
      const token = await AsyncStorage.getItem('token');
      if (!token) return;

      // Close existing connection
      if (radioWs) {
        radioWs.close();
      }

      // Create WebSocket URL
      const wsProtocol = API_BASE.startsWith('https') ? 'wss' : 'ws';
      const wsHost = API_BASE.replace(/^https?:\/\//, '');
      const wsUrl = `${wsProtocol}://${wsHost}/api/radio/ws/${channel}?token=${token}`;

      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log(`Radio: Connected to channel ${channel}`);
        setRadioConnected(true);
        setRadioChannel(channel);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'channel_status') {
            setRadioUsers(data.users || []);
            setRadioChannelBusy(data.transmitting_user !== null);
            setRadioTransmittingUser(data.transmitting_user);
          } else if (data.type === 'transmission_status') {
            if (!data.success && data.message === 'Canal ocupado') {
              Alert.alert('Radio', 'El canal está ocupado. Espera a que termine la transmisión.');
            }
          } else if (data.type === 'audio') {
            // Handle incoming audio
            if (!radioMuted) {
              playReceivedAudio(data.audio_data);
            }
          }
        } catch (e) {
          console.error('Radio: Error parsing message', e);
        }
      };

      ws.onclose = () => {
        console.log('Radio: Disconnected');
        setRadioConnected(false);
        setRadioUsers([]);
        setRadioChannelBusy(false);
        setRadioTransmittingUser(null);
      };

      ws.onerror = (error) => {
        console.error('Radio: WebSocket error', error);
      };

      setRadioWs(ws);
    } catch (error) {
      console.error('Error connecting to radio:', error);
      Alert.alert('Error', 'No se pudo conectar al canal de radio');
    }
  }, [radioWs, radioMuted]);

  // Disconnect from radio
  const disconnectFromRadio = useCallback(() => {
    if (radioWs) {
      radioWs.close();
      setRadioWs(null);
    }
    setRadioConnected(false);
    setRadioUsers([]);
    setRadioTransmitting(false);
  }, [radioWs]);

  // Start transmitting (push to talk - press)
  const startRadioTransmission = useCallback(() => {
    if (!radioWs || !radioConnected || radioChannelBusy) return;
    
    radioWs.send(JSON.stringify({ type: 'start_transmission' }));
    setRadioTransmitting(true);
    
    // Start recording audio here (will implement with expo-av)
    startRecordingAudio();
  }, [radioWs, radioConnected, radioChannelBusy]);

  // Stop transmitting (push to talk - release)
  const stopRadioTransmission = useCallback(() => {
    if (!radioWs || !radioConnected) return;
    
    radioWs.send(JSON.stringify({ type: 'stop_transmission' }));
    setRadioTransmitting(false);
    
    // Stop recording and send audio
    stopRecordingAudio();
  }, [radioWs, radioConnected]);

  // Placeholder functions for audio (will implement with expo-av)
  const startRecordingAudio = async () => {
    // TODO: Implement audio recording with expo-av
    console.log('Radio: Start recording audio');
  };

  const stopRecordingAudio = async () => {
    // TODO: Implement stop recording and send audio
    console.log('Radio: Stop recording audio');
  };

  const playReceivedAudio = async (audioData: string) => {
    // TODO: Implement audio playback with expo-av
    console.log('Radio: Received audio data');
  };

  // Toggle radio connection
  const toggleRadioConnection = useCallback(() => {
    if (radioConnected) {
      disconnectFromRadio();
    } else {
      connectToRadioChannel(radioChannel);
    }
  }, [radioConnected, radioChannel, connectToRadioChannel, disconnectFromRadio]);

  // Change radio channel
  const changeRadioChannel = useCallback((channel: number) => {
    setRadioChannel(channel);
    if (radioConnected) {
      // Reconnect to new channel
      connectToRadioChannel(channel);
    }
  }, [radioConnected, connectToRadioChannel]);

  // ========== CHAT FUNCTIONS ==========
  
  // Fetch available chat channels
  const fetchChatChannels = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/chat/channels`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setChatChannels(response.data.channels);
    } catch (error) {
      console.error('Error fetching chat channels:', error);
    }
  }, []);

  // Fetch messages for a channel
  const fetchChatMessages = useCallback(async (channel: string) => {
    setChatLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/chat/${channel}/messages`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setChatMessages(response.data.messages);
      setCanWriteChat(response.data.can_write);
    } catch (error: any) {
      console.error('Error fetching chat messages:', error);
      if (error.response?.status === 403) {
        Alert.alert('Acceso denegado', 'No tienes acceso a este canal');
      }
    } finally {
      setChatLoading(false);
    }
  }, []);

  // Send a chat message
  const sendChatMessage = async () => {
    if (!chatMessage.trim() || !canWriteChat) return;
    
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.post(
        `${API_BASE}/api/chat/${activeChannel}/messages`,
        { message: chatMessage.trim() },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      // Add message to local state
      setChatMessages(prev => [...prev, response.data.message]);
      setChatMessage('');
    } catch (error: any) {
      console.error('Error sending message:', error);
      const detail = error.response?.data?.detail || '';
      
      // Check if blocked from chat
      if (error.response?.status === 403 && detail.includes('mensajes indebidos')) {
        Alert.alert(
          '⚠️ Chat Bloqueado',
          `${detail}\n\n` +
          'Recuerda que los mensajes del chat deben ser respetuosos y útiles para la comunidad. ' +
          'Los mensajes indebidos perjudican a todos los compañeros.',
          [{ text: 'Entendido', style: 'default' }]
        );
      } else {
        Alert.alert('Error', detail || 'No se pudo enviar el mensaje');
      }
    }
  };

  // Delete a chat message (mods and admins only)
  const deleteChatMessage = async (messageId: string) => {
    Alert.alert(
      'Eliminar mensaje',
      '¿Estás seguro de que quieres eliminar este mensaje?',
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Eliminar',
          style: 'destructive',
          onPress: async () => {
            try {
              const token = await AsyncStorage.getItem('token');
              await axios.delete(
                `${API_BASE}/api/chat/${activeChannel}/messages/${messageId}`,
                { headers: { Authorization: `Bearer ${token}` } }
              );
              
              // Remove from local state
              setChatMessages(prev => prev.filter(msg => msg.id !== messageId));
            } catch (error: any) {
              console.error('Error deleting message:', error);
              Alert.alert('Error', error.response?.data?.detail || 'No se pudo eliminar el mensaje');
            }
          }
        }
      ]
    );
  };

  // Check if user can delete messages (mods and admins)
  const canDeleteMessages = () => {
    return currentUser?.role === 'admin' || currentUser?.role === 'moderator';
  };

  // Block user for inappropriate message (mods and admins)
  const blockUserForMessage = async (messageId: string, username: string) => {
    Alert.alert(
      '🚫 Bloquear Usuario',
      `¿Estás seguro de que quieres bloquear a @${username} por mensaje indebido?\n\nEl mensaje será eliminado y el usuario recibirá una penalización según su historial.`,
      [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Bloquear',
          style: 'destructive',
          onPress: async () => {
            try {
              const token = await AsyncStorage.getItem('token');
              const response = await axios.post(
                `${API_BASE}/api/chat/${activeChannel}/messages/${messageId}/block-user`,
                {},
                { headers: { Authorization: `Bearer ${token}` } }
              );
              
              // Remove message from local state
              setChatMessages(prev => prev.filter(msg => msg.id !== messageId));
              
              // Show penalty info
              const penaltyInfo = response.data.penalty_info;
              Alert.alert(
                '✅ Usuario Bloqueado',
                `@${penaltyInfo.username} ha sido bloqueado.\n\n` +
                `📊 Avisos acumulados: ${penaltyInfo.abuse_count}\n` +
                `⏱️ ${penaltyInfo.penalty_message}`,
                [{ text: 'Entendido' }]
              );
            } catch (error: any) {
              console.error('Error blocking user:', error);
              Alert.alert('Error', error.response?.data?.detail || 'No se pudo bloquear al usuario');
            }
          }
        }
      ]
    );
  };

  // Switch chat channel
  const switchChannel = (channelId: string) => {
    setActiveChannel(channelId);
    fetchChatMessages(channelId);
  };

  // Open chat modal
  const openChatModal = () => {
    fetchChatChannels();
    fetchChatMessages(activeChannel);
    setShowChatModal(true);
  };

  // Get channel icon
  const getChannelIcon = (iconName: string) => {
    switch (iconName) {
      case 'chatbubbles': return 'chatbubbles';
      case 'megaphone': return 'megaphone';
      case 'shield': return 'shield';
      default: return 'chatbubble';
    }
  };

  // ========== LICENSE ALERTS FUNCTIONS ==========

  // Fetch unread alerts count
  const fetchAlertsUnreadCount = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/alerts/license/unread-count`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setAlertsUnreadCount(response.data.unread_count);
    } catch (error) {
      console.error('Error fetching unread count:', error);
    }
  }, []);

  // Fetch received alerts
  const fetchLicenseAlerts = useCallback(async () => {
    setAlertLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/alerts/license/received`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setLicenseAlerts(response.data.alerts);
      setAlertsUnreadCount(response.data.unread_count);
    } catch (error) {
      console.error('Error fetching alerts:', error);
    } finally {
      setAlertLoading(false);
    }
  }, []);

  // Search for licenses (autocomplete)
  const searchLicenses = async (query: string) => {
    if (!query || query.length < 1) {
      setLicenseSuggestions([]);
      return;
    }

    setSearchingLicense(true);
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/alerts/license/search?q=${query}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setLicenseSuggestions(response.data.results);
    } catch (error) {
      console.error('Error searching licenses:', error);
      setLicenseSuggestions([]);
    } finally {
      setSearchingLicense(false);
    }
  };

  // Handle license input change with debounce
  const handleLicenseInputChange = (text: string) => {
    setAlertTargetLicense(text);
    setSelectedRecipient(null); // Clear selection when typing
    
    // Debounce search
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      searchLicenses(text);
    }, 300);
  };

  // Select a recipient from suggestions
  const selectRecipient = (recipient: { license_number: string; full_name: string }) => {
    setSelectedRecipient(recipient);
    setAlertTargetLicense(recipient.license_number);
    setLicenseSuggestions([]);
  };

  // Send alert to another taxi driver
  const sendLicenseAlert = async () => {
    if (!selectedRecipient) {
      Alert.alert('Error', 'Debes seleccionar un destinatario de la lista de sugerencias');
      return;
    }

    if (!alertMessage.trim()) {
      Alert.alert('Error', 'Debes escribir un mensaje');
      return;
    }

    setAlertLoading(true);
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.post(`${API_BASE}/api/alerts/license`, {
        target_license: selectedRecipient.license_number,
        alert_type: alertType,
        message: alertMessage.trim()
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });

      Alert.alert('✓ Alerta enviada', `Tu alerta ha sido enviada a ${selectedRecipient.full_name}`);
      setShowCreateAlertModal(false);
      setAlertTargetLicense('');
      setAlertMessage('');
      setAlertType('lost_item');
      setSelectedRecipient(null);
      setLicenseSuggestions([]);
    } catch (error: any) {
      Alert.alert('Error', error.response?.data?.detail || 'No se pudo enviar la alerta');
    } finally {
      setAlertLoading(false);
    }
  };

  // Mark alert as read
  const markAlertRead = async (alertId: string) => {
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.put(`${API_BASE}/api/alerts/license/${alertId}/read`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Update local state
      setLicenseAlerts(prev => prev.map(a => 
        a.id === alertId ? { ...a, is_read: true } : a
      ));
      setAlertsUnreadCount(prev => Math.max(0, prev - 1));
    } catch (error) {
      console.error('Error marking alert read:', error);
    }
  };

  // Mark all alerts as read
  const markAllAlertsRead = async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.put(`${API_BASE}/api/alerts/license/read-all`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Update local state
      setLicenseAlerts(prev => prev.map(a => ({ ...a, is_read: true })));
      setAlertsUnreadCount(0);
    } catch (error) {
      console.error('Error marking all read:', error);
    }
  };

  // Delete alert
  const deleteLicenseAlert = async (alertId: string) => {
    try {
      const token = await AsyncStorage.getItem('token');
      await axios.delete(`${API_BASE}/api/alerts/license/${alertId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Update local state
      const alert = licenseAlerts.find(a => a.id === alertId);
      setLicenseAlerts(prev => prev.filter(a => a.id !== alertId));
      if (alert && !alert.is_read) {
        setAlertsUnreadCount(prev => Math.max(0, prev - 1));
      }
    } catch (error) {
      console.error('Error deleting alert:', error);
    }
  };

  // Open alerts modal
  const openAlertsModal = () => {
    fetchLicenseAlerts();
    setShowAlertsModal(true);
  };

  // Get alert type display
  const getAlertTypeDisplay = (type: string) => {
    switch (type) {
      case 'lost_item': return { icon: 'cube-outline', label: 'Objeto perdido', color: '#F59E0B' };
      case 'general': return { icon: 'information-circle-outline', label: 'Aviso', color: '#6366F1' };
      default: return { icon: 'alert-circle-outline', label: 'Alerta', color: '#EF4444' };
    }
  };

  // Generate time range options (12 hours back and 12 hours forward)
  const generateTimeRangeOptions = () => {
    const options: Array<{ id: string; label: string; startHour: number; endHour: number }> = [];
    const now = new Date();
    const currentHour = now.getHours();
    
    // Add "Ahora" option
    options.push({
      id: 'now',
      label: 'Ahora',
      startHour: currentHour,
      endHour: currentHour + 1
    });
    
    // Add past 12 hours (from oldest to newest)
    for (let i = 12; i >= 1; i--) {
      let hour = currentHour - i;
      if (hour < 0) hour += 24;
      const nextHour = (hour + 1) % 24;
      options.push({
        id: `past-${i}`,
        label: `${hour.toString().padStart(2, '0')}:00 - ${nextHour.toString().padStart(2, '0')}:00`,
        startHour: hour,
        endHour: nextHour
      });
    }
    
    // Sort: put "Ahora" first, then past hours from newest to oldest
    const nowOption = options.find(o => o.id === 'now')!;
    const pastOptions = options.filter(o => o.id.startsWith('past-')).reverse();
    
    // Add future 12 hours
    const futureOptions: typeof options = [];
    for (let i = 1; i <= 12; i++) {
      const hour = (currentHour + i) % 24;
      const nextHour = (hour + 1) % 24;
      futureOptions.push({
        id: `future-${i}`,
        label: `${hour.toString().padStart(2, '0')}:00 - ${nextHour.toString().padStart(2, '0')}:00`,
        startHour: hour,
        endHour: nextHour
      });
    }
    
    // Final order: Past (oldest first), Now, Future
    return [...pastOptions.reverse(), nowOption, ...futureOptions];
  };

  const timeRangeOptions = generateTimeRangeOptions();

  // Get display label for selected time range
  const getSelectedTimeRangeLabel = () => {
    if (selectedTimeRange === 'now') return 'Ahora';
    const option = timeRangeOptions.find(o => o.id === selectedTimeRange);
    return option ? option.label : 'Ahora';
  };

  // Calculate time range parameters for API calls
  const getTimeRangeParams = useCallback(() => {
    if (selectedTimeRange === 'now') {
      return {};
    }
    
    const now = new Date();
    const currentHour = now.getHours();
    
    let targetStartHour: number | null = null;
    let targetEndHour: number | null = null;
    let hoursOffset = 0;
    
    if (selectedTimeRange.startsWith('past-')) {
      const pastIndex = parseInt(selectedTimeRange.replace('past-', ''));
      hoursOffset = -pastIndex;
      targetStartHour = (currentHour + hoursOffset + 24) % 24;
      targetEndHour = (targetStartHour + 1) % 24;
    } else if (selectedTimeRange.startsWith('future-')) {
      const futureIndex = parseInt(selectedTimeRange.replace('future-', ''));
      hoursOffset = futureIndex;
      targetStartHour = (currentHour + hoursOffset) % 24;
      targetEndHour = (targetStartHour + 1) % 24;
    }
    
    if (targetStartHour === null || targetEndHour === null) {
      return {};
    }
    
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    
    // Calculate the start time for the selected hour slot
    let startDate = new Date(today);
    startDate.setHours(targetStartHour, 0, 0, 0);
    
    let endDate = new Date(today);
    endDate.setHours(targetEndHour, 0, 0, 0);
    
    // Handle day boundary
    if (targetEndHour === 0) {
      endDate.setDate(endDate.getDate() + 1);
    }
    
    // Adjust for past/future days
    if (hoursOffset < 0) {
      // Past: if startDate is in the future, subtract a day
      if (startDate > now) {
        startDate.setDate(startDate.getDate() - 1);
        endDate.setDate(endDate.getDate() - 1);
      }
    } else if (hoursOffset > 0) {
      // Future: if startDate is in the past (more than 12h ago), add a day
      const hoursDiff = (now.getTime() - startDate.getTime()) / (1000 * 60 * 60);
      if (hoursDiff > 12) {
        startDate.setDate(startDate.getDate() + 1);
        endDate.setDate(endDate.getDate() + 1);
      }
    }
    
    return {
      start_time: startDate.toISOString(),
      end_time: endDate.toISOString()
    };
  }, [selectedTimeRange]);

  const fetchData = useCallback(async () => {
    if (!currentUser) return; // Don't fetch if not logged in
    try {
      // Get time range parameters for historical queries
      const timeParams = getTimeRangeParams();
      const isHistorical = Object.keys(timeParams).length > 0;
      
      if (isHistorical) {
        console.log(`[Data] Using time range params:`, timeParams);
      }
      
      if (activeTab === 'trains') {
        // Fetch trains with retry for Chamartín
        let retryCount = 0;
        const maxRetries = 5;
        let trainResponse: TrainComparison | null = null;
        
        while (retryCount < maxRetries) {
          const response = await axios.get<TrainComparison>(`${API_BASE}/api/trains`, {
            params: { shift, ...timeParams }
          });
          
          trainResponse = response.data;
          
          // Check if Chamartín has data (for real-time queries, retry if no data)
          const chamartinHasData = response.data.chamartin?.arrivals?.length > 0;
          
          // For historical queries, don't retry if no data (data may simply not exist)
          if (chamartinHasData || isHistorical) {
            console.log(`[Trains] Chamartín data received (${response.data.chamartin?.arrivals?.length || 0} trains)`);
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
          
          if (trainResponse.chamartin?.arrivals?.length === 0 && !isHistorical) {
            console.log('[Trains] Chamartín: No se pudieron obtener datos después de varios intentos');
          }
        }
      } else if (activeTab === 'flights') {
        const response = await axios.get<FlightComparison>(`${API_BASE}/api/flights`, {
          params: timeParams
        });
        setFlightData(response.data);
      } else if (activeTab === 'street') {
        // Fetch all street data in parallel for faster loading
        await Promise.all([
          fetchStreetData(),
          fetchTaxiStatus(),
          fetchQueueStatus()
        ]);
      } else if (activeTab === 'events') {
        await fetchEventsData();
      } else if (activeTab === 'admin') {
        await Promise.all([
          fetchAdminUsers(),
          fetchAdminStats()
        ]);
      }
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [activeTab, shift, currentUser, timeWindow, selectedTimeRange, getTimeRangeParams, fetchStreetData, fetchTaxiStatus, fetchQueueStatus, fetchEventsData, fetchAdminUsers, fetchAdminStats]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchData();
  }, [fetchData]);

  // Cleanup timeouts on unmount to prevent DOM errors
  useEffect(() => {
    return () => {
      // Clear search timeouts
      if (streetSearchTimeoutRef.current) {
        clearTimeout(streetSearchTimeoutRef.current);
        streetSearchTimeoutRef.current = null;
      }
      if (searchTimeoutRef.current) {
        clearTimeout(searchTimeoutRef.current);
        searchTimeoutRef.current = null;
      }
    };
  }, []);

  // Refetch data when time range changes (applies to street, trains, and flights)
  useEffect(() => {
    if (currentUser && selectedTimeRange) {
      if (activeTab === 'street') {
        console.log(`[TimeRange] Selected time range changed to: ${selectedTimeRange} for Street`);
        fetchStreetData();
      } else if (activeTab === 'trains' || activeTab === 'flights') {
        console.log(`[TimeRange] Selected time range changed to: ${selectedTimeRange} for ${activeTab}`);
        fetchData();
      }
    }
  }, [selectedTimeRange, currentUser, activeTab, fetchStreetData, fetchData]);

  // Fetch station alerts periodically
  useEffect(() => {
    if (!currentUser) return;
    
    fetchStationAlerts();
    
    // Refresh every 10 seconds to update timers
    const interval = setInterval(() => {
      fetchStationAlerts();
    }, 10000);
    
    return () => clearInterval(interval);
  }, [currentUser, fetchStationAlerts]);

  // Real-time timer tick for alert countdowns (every 1 second)
  useEffect(() => {
    if (stationAlerts.alerts.length > 0) {
      const timerInterval = setInterval(() => {
        setAlertTimerTick(prev => prev + 1);
      }, 1000);
      
      return () => clearInterval(timerInterval);
    }
  }, [stationAlerts.alerts.length]);

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

  // Fetch license alerts unread count periodically
  useEffect(() => {
    if (currentUser) {
      fetchAlertsUnreadCount();
      
      // Refresh unread count every 30 seconds
      const interval = setInterval(() => {
        fetchAlertsUnreadCount();
      }, 30000);
      return () => clearInterval(interval);
    }
  }, [currentUser, fetchAlertsUnreadCount]);

  // Fetch data when logged in or when time window changes
  useEffect(() => {
    if (currentUser) {
      setLoading(true);
      fetchData();

      // Auto-refresh every 30 seconds for real-time data
      const interval = setInterval(() => {
        fetchData();
      }, 30000);
      return () => clearInterval(interval);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, currentUser, timeWindow]); // fetchData excluded to prevent infinite loops

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
          <ScrollView 
            contentContainerStyle={styles.loginScreenContent}
            showsVerticalScrollIndicator={false}
          >
            {/* Logo/Header */}
            <View style={styles.loginHeader}>
              <View style={styles.loginLogoContainer}>
                <Ionicons name="car" size={44} color="#F59E0B" />
              </View>
              <Text style={styles.loginAppTitle}>TaxiDash Madrid</Text>
              <Text style={styles.loginAppSubtitle}>
                {showRegister ? 'Crear cuenta nueva' : 'Herramienta para taxistas'}
              </Text>
            </View>

            {!showRegister ? (
              /* Login Form */
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

                <TouchableOpacity 
                  style={styles.switchAuthButton}
                  onPress={() => setShowRegister(true)}
                >
                  <Text style={styles.switchAuthText}>
                    ¿No tienes cuenta? <Text style={styles.switchAuthLink}>Regístrate aquí</Text>
                  </Text>
                </TouchableOpacity>
              </View>
            ) : (
              /* Registration Form */
              <View style={styles.loginFormContainer}>
                <Text style={styles.loginFormTitle}>Crear Cuenta</Text>
                
                <View style={styles.inputContainer}>
                  <Ionicons name="person-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.loginScreenInput}
                    placeholder="Nombre de usuario *"
                    placeholderTextColor="#64748B"
                    value={registerUsername}
                    onChangeText={setRegisterUsername}
                    autoCapitalize="none"
                  />
                </View>

                <View style={styles.inputContainer}>
                  <Ionicons name="lock-closed-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.loginScreenInput}
                    placeholder="Contraseña *"
                    placeholderTextColor="#64748B"
                    value={registerPassword}
                    onChangeText={setRegisterPassword}
                    secureTextEntry
                  />
                </View>

                <View style={styles.inputContainer}>
                  <Ionicons name="lock-closed" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.loginScreenInput}
                    placeholder="Confirmar contraseña *"
                    placeholderTextColor="#64748B"
                    value={registerPasswordConfirm}
                    onChangeText={setRegisterPasswordConfirm}
                    secureTextEntry
                  />
                </View>
                {registerPassword && registerPasswordConfirm && registerPassword !== registerPasswordConfirm && (
                  <Text style={styles.passwordMismatchText}>Las contraseñas no coinciden</Text>
                )}

                <View style={styles.inputContainer}>
                  <Ionicons name="id-card-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.loginScreenInput}
                    placeholder="Nombre completo *"
                    placeholderTextColor="#64748B"
                    value={registerFullName}
                    onChangeText={setRegisterFullName}
                  />
                </View>

                <View style={styles.inputContainer}>
                  <Ionicons name="document-text-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.loginScreenInput}
                    placeholder="Número de licencia *"
                    placeholderTextColor="#64748B"
                    value={registerLicenseNumber}
                    onChangeText={setRegisterLicenseNumber}
                    keyboardType="numeric"
                  />
                </View>

                <View style={styles.inputContainer}>
                  <Ionicons name="call-outline" size={20} color="#64748B" style={styles.inputIcon} />
                  <TextInput
                    style={styles.loginScreenInput}
                    placeholder="Teléfono (opcional)"
                    placeholderTextColor="#64748B"
                    value={registerPhone}
                    onChangeText={setRegisterPhone}
                    keyboardType="phone-pad"
                  />
                </View>

                <View style={styles.registerShiftSection}>
                  <Text style={styles.registerShiftLabel}>Turno de preferencia</Text>
                  <View style={styles.registerShiftButtons}>
                    <TouchableOpacity
                      style={[
                        styles.registerShiftButton,
                        registerPreferredShift === 'day' && styles.registerShiftButtonActiveDay
                      ]}
                      onPress={() => setRegisterPreferredShift('day')}
                    >
                      <Ionicons name="sunny" size={18} color={registerPreferredShift === 'day' ? '#FFFFFF' : '#F59E0B'} />
                      <Text style={[
                        styles.registerShiftButtonText,
                        registerPreferredShift === 'day' && styles.registerShiftButtonTextActive
                      ]}>Día</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.registerShiftButton,
                        registerPreferredShift === 'all' && styles.registerShiftButtonActiveAll
                      ]}
                      onPress={() => setRegisterPreferredShift('all')}
                    >
                      <Ionicons name="time" size={18} color={registerPreferredShift === 'all' ? '#FFFFFF' : '#6366F1'} />
                      <Text style={[
                        styles.registerShiftButtonText,
                        registerPreferredShift === 'all' && styles.registerShiftButtonTextActive
                      ]}>Todo</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.registerShiftButton,
                        registerPreferredShift === 'night' && styles.registerShiftButtonActiveNight
                      ]}
                      onPress={() => setRegisterPreferredShift('night')}
                    >
                      <Ionicons name="moon" size={18} color={registerPreferredShift === 'night' ? '#FFFFFF' : '#8B5CF6'} />
                      <Text style={[
                        styles.registerShiftButtonText,
                        registerPreferredShift === 'night' && styles.registerShiftButtonTextActive
                      ]}>Noche</Text>
                    </TouchableOpacity>
                  </View>
                </View>

                <TouchableOpacity 
                  style={[styles.loginScreenButton, styles.registerButton]}
                  onPress={handleRegister}
                  disabled={registerLoading}
                >
                  {registerLoading ? (
                    <ActivityIndicator color="#FFFFFF" />
                  ) : (
                    <>
                      <Ionicons name="person-add-outline" size={20} color="#FFFFFF" />
                      <Text style={styles.loginScreenButtonText}>Crear Cuenta</Text>
                    </>
                  )}
                </TouchableOpacity>

                <TouchableOpacity 
                  style={styles.switchAuthButton}
                  onPress={() => setShowRegister(false)}
                >
                  <Text style={styles.switchAuthText}>
                    ¿Ya tienes cuenta? <Text style={styles.switchAuthLink}>Inicia sesión</Text>
                  </Text>
                </TouchableOpacity>
              </View>
            )}

            {/* Footer */}
            <Text style={styles.loginFooter}>
              {showRegister ? '* Campos obligatorios' : 'Acceso solo para usuarios registrados'}
            </Text>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    );
  }

  const renderStationCard = (station: StationData, stationKey: string) => {
    const isWinner = timeWindow === 30 ? station.is_winner_30min : station.is_winner_60min;
    const futureArrivals = timeWindow === 30 ? station.total_next_30min : station.total_next_60min;
    const pastArrivals = timeWindow === 30 ? (station.past_30min || 0) : (station.past_60min || 0);
    const score = timeWindow === 30 ? (station.score_30min || 0) : (station.score_60min || 0);
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

    // Get alerts for this station
    const stationAlertsData = getLocationAlerts('station', stationKey);
    const hasStationAlerts = stationAlertsData.length > 0;
    
    return (
      <View
        key={stationKey}
        style={[
          styles.stationCard,
          isWinner && styles.winnerCard,
          hasStationAlerts && styles.stationAlertCard,
        ]}
      >
        {/* Alert badges at top-left */}
        {hasStationAlerts && (
          <View style={styles.alertBadgesContainer}>
            {stationAlertsData.map((alert, idx) => (
                <View key={idx} style={[
                  styles.alertBadge,
                  alert.alert_type === 'sin_taxis' ? styles.alertBadgeSinTaxis : styles.alertBadgeBarandilla
                ]}>
                  <Ionicons 
                    name={alert.alert_type === 'sin_taxis' ? 'car-outline' : 'warning'} 
                    size={14} 
                    color="#FFFFFF" 
                  />
                  <Text style={styles.alertBadgeText}>
                    {alert.alert_type === 'sin_taxis' ? 'SIN TAXIS' : 'BARANDILLA'}
                  </Text>
                  <Text style={styles.alertBadgeTime}>{formatSecondsAgo(alert.seconds_ago, alert.created_at)}</Text>
                </View>
              ))}
            </View>
        )}
        
        {/* Winner badge always shown when isWinner */}
        {isWinner && (
          <View style={styles.winnerBadge}>
            <Ionicons name="trophy" size={16} color="#FFFFFF" />
            <Text style={styles.winnerBadgeText}>MÁS FRECUENCIA</Text>
          </View>
        )}
        <View style={styles.stationHeader}>
          <Ionicons name="train" size={28} color={hasStationAlerts ? '#EF4444' : (isWinner ? '#F59E0B' : '#6366F1')} />
          <Text style={[styles.stationName, isWinner && styles.winnerText, hasStationAlerts && { color: '#EF4444' }]}>
            {stationShortName}
          </Text>
        </View>
        
        {/* Formato: XA - YP (Anteriores - Posteriores) */}
        <View style={styles.arrivalCount}>
          <View style={styles.arrivalScoreRow}>
            <Text style={[styles.arrivalNumberSmall, { color: '#F59E0B' }]}>
              {pastArrivals}<Text style={styles.arrivalSuffix}>A</Text>
            </Text>
            <Text style={styles.arrivalDivider}> - </Text>
            <Text style={[styles.arrivalNumberSmall, { color: '#10B981' }]}>
              {futureArrivals}<Text style={styles.arrivalSuffix}>P</Text>
            </Text>
          </View>
          <Text style={styles.arrivalLabel}>
            trenes ({timeWindow === 30 ? '15' : '30'}min ant. / {timeWindow}min post.)
          </Text>
          <View style={styles.scoreContainer}>
            <Ionicons name="analytics" size={14} color="#6366F1" />
            <Text style={styles.scoreText}>Score: {score.toFixed(1)}</Text>
          </View>
        </View>
        
        {/* Alert buttons */}
        <View style={styles.alertButtonsRow}>
          <TouchableOpacity 
            style={[styles.alertButton, styles.alertButtonSinTaxis]}
            onPress={() => reportStationAlert('station', stationKey, 'sin_taxis')}
            disabled={reportingAlert}
          >
            <Ionicons name="car-outline" size={16} color="#FFFFFF" />
            <Text style={styles.alertButtonText}>Sin taxis</Text>
          </TouchableOpacity>
          <TouchableOpacity 
            style={[styles.alertButton, styles.alertButtonBarandilla]}
            onPress={() => reportStationAlert('station', stationKey, 'barandilla')}
            disabled={reportingAlert}
          >
            <Ionicons name="warning" size={16} color="#FFFFFF" />
            <Text style={styles.alertButtonText}>Barandilla</Text>
          </TouchableOpacity>
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
    let past30min = 0;
    let past60min = 0;
    let score30min = 0;
    let score60min = 0;
    let allArrivals: FlightArrival[] = [];
    
    group.terminals.forEach(terminalName => {
      const terminal = flightData.terminals[terminalName];
      if (terminal) {
        total30min += terminal.total_next_30min;
        total60min += terminal.total_next_60min;
        past30min += terminal.past_30min || 0;
        past60min += terminal.past_60min || 0;
        score30min += terminal.score_30min || 0;
        score60min += terminal.score_60min || 0;
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
    
    const futureArrivals = timeWindow === 30 ? total30min : total60min;
    const pastArrivals = timeWindow === 30 ? past30min : past60min;
    const score = timeWindow === 30 ? score30min : score60min;
    
    // Determine if this group is the winner based on weighted score
    const groupTotals = terminalGroups.map(g => {
      let s30 = 0, s60 = 0;
      g.terminals.forEach(t => {
        const term = flightData.terminals[t];
        if (term) {
          s30 += term.score_30min || 0;
          s60 += term.score_60min || 0;
        }
      });
      return { name: g.name, score30: s30, score60: s60 };
    });
    
    const maxScore = timeWindow === 30 
      ? Math.max(...groupTotals.map(g => g.score30))
      : Math.max(...groupTotals.map(g => g.score60));
    
    const isWinner = score === maxScore && score > 0;
    
    // Check-in status for this group
    const isCheckedInHere = checkInStatus?.is_checked_in && 
      checkInStatus.location_type === 'terminal' && 
      group.terminals.includes(checkInStatus.location_name || '');

    // Get taxi exits for this terminal group
    const taxiExits = streetData?.exits_by_terminal?.[group.zoneName] || 0;
    const terminalKey = group.terminals[0];
    
    // Get alerts for this terminal group
    const terminalAlerts = group.terminals.flatMap(t => getLocationAlerts('terminal', t));
    const hasTerminalAlerts = terminalAlerts.length > 0;

    return (
      <View
        key={group.name}
        style={[
          styles.stationCard,
          isWinner && styles.winnerCard,
          hasTerminalAlerts && styles.stationAlertCard,
        ]}
      >
        {/* Alert badges at top */}
        {hasTerminalAlerts && (
          <View style={styles.alertBadgesContainer}>
            {terminalAlerts.map((alert, idx) => (
              <View key={idx} style={[
                styles.alertBadge,
                alert.alert_type === 'sin_taxis' ? styles.alertBadgeSinTaxis : styles.alertBadgeBarandilla
              ]}>
                <Ionicons 
                  name={alert.alert_type === 'sin_taxis' ? 'car-outline' : 'warning'} 
                  size={14} 
                  color="#FFFFFF" 
                />
                <Text style={styles.alertBadgeText}>
                  {alert.alert_type === 'sin_taxis' ? 'SIN TAXIS' : 'BARANDILLA'}
                </Text>
                <Text style={styles.alertBadgeTime}>{formatSecondsAgo(alert.seconds_ago, alert.created_at)}</Text>
              </View>
            ))}
          </View>
        )}
        
        {/* Winner badge always shown when isWinner */}
        {isWinner && (
          <View style={styles.winnerBadge}>
            <Ionicons name="trophy" size={16} color="#FFFFFF" />
            <Text style={styles.winnerBadgeText}>MÁS FRECUENCIA</Text>
          </View>
        )}
        <View style={styles.stationHeader}>
          <Ionicons name="airplane" size={28} color={hasTerminalAlerts ? '#EF4444' : (isWinner ? '#F59E0B' : '#3B82F6')} />
          <Text style={[styles.stationName, isWinner && styles.winnerText, hasTerminalAlerts && { color: '#EF4444' }]}>
            {group.zoneName}
          </Text>
        </View>
        
        {/* Formato: XA - YP (Anteriores - Posteriores) */}
        <View style={styles.arrivalCount}>
          <View style={styles.arrivalScoreRow}>
            <Text style={[styles.arrivalNumberSmall, { color: '#F59E0B' }]}>
              {pastArrivals}<Text style={styles.arrivalSuffix}>A</Text>
            </Text>
            <Text style={styles.arrivalDivider}> - </Text>
            <Text style={[styles.arrivalNumberSmall, { color: '#10B981' }]}>
              {futureArrivals}<Text style={styles.arrivalSuffix}>P</Text>
            </Text>
          </View>
          <Text style={styles.arrivalLabel}>
            vuelos ({timeWindow === 30 ? '15' : '30'}min ant. / {timeWindow}min post.)
          </Text>
          <View style={styles.scoreContainer}>
            <Ionicons name="analytics" size={14} color="#6366F1" />
            <Text style={styles.scoreText}>Score: {score.toFixed(1)}</Text>
          </View>
        </View>
        
        {/* Alert buttons */}
        <View style={styles.alertButtonsRow}>
          <TouchableOpacity 
            style={[styles.alertButton, styles.alertButtonSinTaxis]}
            onPress={() => reportStationAlert('terminal', terminalKey, 'sin_taxis')}
            disabled={reportingAlert}
          >
            <Ionicons name="car-outline" size={16} color="#FFFFFF" />
            <Text style={styles.alertButtonText}>Sin taxis</Text>
          </TouchableOpacity>
          <TouchableOpacity 
            style={[styles.alertButton, styles.alertButtonBarandilla]}
            onPress={() => reportStationAlert('terminal', terminalKey, 'barandilla')}
            disabled={reportingAlert}
          >
            <Ionicons name="warning" size={16} color="#FFFFFF" />
            <Text style={styles.alertButtonText}>Barandilla</Text>
          </TouchableOpacity>
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
  // Using stable key to avoid DOM errors from iframe recreation
  const renderMap = () => {
    const center = currentLocation || { latitude: 40.4168, longitude: -3.7038 };
    const markers = streetData?.hot_streets || [];
    
    if (Platform.OS === 'web') {
      // Use iframe for web with marker on current location
      // Round to 3 decimals (~100m) for stable key to avoid constant iframe recreation
      const stableKey = `map-${center.latitude.toFixed(3)}-${center.longitude.toFixed(3)}`;
      const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${center.longitude - 0.02}%2C${center.latitude - 0.01}%2C${center.longitude + 0.02}%2C${center.latitude + 0.01}&layer=mapnik&marker=${center.latitude}%2C${center.longitude}`;
      
      return (
        <View style={styles.mapContainer}>
          <iframe
            src={mapUrl}
            style={{ width: '100%', height: '100%', border: 0 }}
            title="Map"
            key={stableKey}
            loading="lazy"
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
    // Open GPS navigation app with destination coordinates
    // URLs for each GPS app - these are Universal Links that open the native app
    const wazeUrl = `https://waze.com/ul?ll=${lat},${lng}&navigate=yes`;
    const googleMapsUrl = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`;
    
    try {
      // For WEB (including mobile Chrome) - redirect to Universal Link
      // This will open the native app if installed (Waze/Google Maps)
      if (Platform.OS === 'web') {
        const url = gpsApp === 'waze' ? wazeUrl : googleMapsUrl;
        if (typeof window !== 'undefined') {
          // Use location.href to redirect - this triggers the native app to open
          window.location.href = url;
        }
        return;
      }
      
      // For iOS native app
      if (Platform.OS === 'ios') {
        if (gpsApp === 'waze') {
          try {
            await Linking.openURL(`waze://?ll=${lat},${lng}&navigate=yes`);
          } catch {
            await Linking.openURL(wazeUrl);
          }
        } else {
          try {
            await Linking.openURL(`comgooglemaps://?daddr=${lat},${lng}&directionsmode=driving`);
          } catch {
            try {
              await Linking.openURL(`maps://?daddr=${lat},${lng}&dirflg=d`);
            } catch {
              await Linking.openURL(googleMapsUrl);
            }
          }
        }
        return;
      }
      
      // For Android native app
      if (Platform.OS === 'android') {
        if (gpsApp === 'waze') {
          try {
            await Linking.openURL(`waze://?ll=${lat},${lng}&navigate=yes`);
          } catch {
            await Linking.openURL(wazeUrl);
          }
        } else {
          try {
            await Linking.openURL(`google.navigation:q=${lat},${lng}&mode=d`);
          } catch {
            try {
              await Linking.openURL(`geo:${lat},${lng}?q=${lat},${lng}(${encodeURIComponent(placeName)})`);
            } catch {
              await Linking.openURL(googleMapsUrl);
            }
          }
        }
        return;
      }
      
      // Fallback
      await Linking.openURL(gpsApp === 'waze' ? wazeUrl : googleMapsUrl);
    } catch (err) {
      console.error('Error opening GPS navigation:', err);
      const url = gpsApp === 'waze' ? wazeUrl : googleMapsUrl;
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        window.location.href = url;
      } else {
        await Linking.openURL(url);
      }
    }
  };

  // Open GPS app without any destination - just launch the preferred GPS app
  const openGpsAppOnly = async () => {
    // URLs to just open the GPS app without destination
    const wazeUrl = 'https://waze.com/ul';
    const googleMapsUrl = 'https://www.google.com/maps';
    
    try {
      if (Platform.OS === 'web') {
        const url = gpsApp === 'waze' ? wazeUrl : googleMapsUrl;
        if (typeof window !== 'undefined') {
          window.open(url, '_blank');
        }
        return;
      }
      
      if (Platform.OS === 'ios') {
        if (gpsApp === 'waze') {
          try {
            await Linking.openURL('waze://');
          } catch {
            await Linking.openURL(wazeUrl);
          }
        } else {
          try {
            await Linking.openURL('comgooglemaps://');
          } catch {
            try {
              await Linking.openURL('maps://');
            } catch {
              await Linking.openURL(googleMapsUrl);
            }
          }
        }
        return;
      }
      
      if (Platform.OS === 'android') {
        if (gpsApp === 'waze') {
          try {
            await Linking.openURL('waze://');
          } catch {
            await Linking.openURL(wazeUrl);
          }
        } else {
          try {
            await Linking.openURL('google.navigation:');
          } catch {
            try {
              await Linking.openURL('geo:');
            } catch {
              await Linking.openURL(googleMapsUrl);
            }
          }
        }
        return;
      }
      
      // Fallback
      await Linking.openURL(gpsApp === 'waze' ? wazeUrl : googleMapsUrl);
    } catch (err) {
      console.error('Error opening GPS app:', err);
      const url = gpsApp === 'waze' ? wazeUrl : googleMapsUrl;
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        window.open(url, '_blank');
      } else {
        await Linking.openURL(url);
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
        <View style={[styles.hottestStreetCard, styles.stationHotCard, 
          // Apply alert styling if station has alerts
          streetData?.hottest_station && getLocationAlerts('station', streetData.hottest_station.toLowerCase()).length > 0 && styles.hottestCardWithAlert
        ]}>
          {/* Station Alert Badge */}
          {streetData?.hottest_station && (() => {
            const stationKey = streetData.hottest_station.toLowerCase();
            const alerts = getLocationAlerts('station', stationKey);
            if (alerts.length > 0) {
              return (
                <View style={styles.hottestAlertBadgesContainer}>
                  {alerts.map((alert, idx) => (
                    <View key={idx} style={[
                      styles.alertBadge,
                      alert.alert_type === 'sin_taxis' ? styles.alertBadgeSinTaxis : styles.alertBadgeBarandilla
                    ]}>
                      <Ionicons 
                        name={alert.alert_type === 'sin_taxis' ? 'car-outline' : 'warning'} 
                        size={12} 
                        color="#FFFFFF" 
                      />
                      <Text style={styles.alertBadgeText}>
                        {alert.alert_type === 'sin_taxis' ? 'SIN TAXIS' : 'BARANDILLA'}
                      </Text>
                      <Text style={styles.alertBadgeTime}>{formatSecondsAgo(alert.seconds_ago, alert.created_at)}</Text>
                    </View>
                  ))}
                </View>
              );
            }
            return null;
          })()}
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="train" size={24} color={
              streetData?.hottest_station && getLocationAlerts('station', streetData.hottest_station.toLowerCase()).length > 0 
                ? '#EF4444' 
                : '#3B82F6'
            } />
            <Text style={[styles.hottestStreetTitle, 
              streetData?.hottest_station && getLocationAlerts('station', streetData.hottest_station.toLowerCase()).length > 0 && { color: '#EF4444' }
            ]}>Estación caliente</Text>
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
          
          {/* GPS button or Close Alert button */}
          {streetData?.hottest_station && (() => {
            const stationKey = streetData.hottest_station.toLowerCase();
            const alerts = getLocationAlerts('station', stationKey);
            
            if (alerts.length > 0) {
              // Show close alert buttons for each active alert
              return (
                <View style={styles.closeAlertButtonsContainer}>
                  {alerts.map((alert, idx) => {
                    const canClose = canUserCloseAlert(alert);
                    const secondsUntilCanClose = getSecondsUntilCanClose(alert);
                    
                    return (
                      <TouchableOpacity
                        key={idx}
                        style={[
                          styles.closeAlertButton,
                          alert.alert_type === 'sin_taxis' ? styles.closeAlertButtonSinTaxis : styles.closeAlertButtonBarandilla,
                          !canClose && styles.closeAlertButtonDisabled
                        ]}
                        onPress={() => {
                          if (canClose) {
                            cancelStationAlert('station', stationKey, alert.alert_type);
                          } else {
                            Alert.alert('Espera', `Debes esperar ${secondsUntilCanClose}s para cerrar tu propia alerta`);
                          }
                        }}
                        disabled={reportingAlert}
                      >
                        <Ionicons name="close-circle" size={18} color="#FFFFFF" />
                        <Text style={styles.closeAlertButtonText}>
                          Cerrar {alert.alert_type === 'sin_taxis' ? 'Sin Taxis' : 'Barandilla'}
                          {!canClose && ` (${secondsUntilCanClose}s)`}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              );
            }
            
            // No alerts, show GPS button
            return (
              <TouchableOpacity
                style={[styles.navigateButton, styles.navigateButtonStation]}
                onPress={() => openGpsAppOnly()}
              >
                <Ionicons name="navigate" size={20} color="#FFFFFF" />
                <Text style={styles.navigateButtonText}>Ir con GPS</Text>
              </TouchableOpacity>
            );
          })()}
        </View>

        {/* === TERMINAL CALIENTE === */}
        <View style={[styles.hottestStreetCard, styles.terminalHotCard,
          // Apply alert styling if terminal has alerts
          streetData?.hottest_terminal && (() => {
            // Extract terminal key (e.g., "T4-T4S" -> check T4 and T4S)
            const terminalName = streetData.hottest_terminal;
            const terminalKeys = terminalName.includes('-') 
              ? terminalName.split('-').map((t: string) => t.trim())
              : [terminalName];
            const hasAlerts = terminalKeys.some((t: string) => getLocationAlerts('terminal', t).length > 0);
            return hasAlerts ? styles.hottestCardWithAlert : null;
          })()
        ]}>
          {/* Terminal Alert Badge */}
          {streetData?.hottest_terminal && (() => {
            const terminalName = streetData.hottest_terminal;
            const terminalKeys = terminalName.includes('-') 
              ? terminalName.split('-').map((t: string) => t.trim())
              : [terminalName];
            const alerts = terminalKeys.flatMap((t: string) => getLocationAlerts('terminal', t));
            if (alerts.length > 0) {
              return (
                <View style={styles.hottestAlertBadgesContainer}>
                  {alerts.map((alert, idx) => (
                    <View key={idx} style={[
                      styles.alertBadge,
                      alert.alert_type === 'sin_taxis' ? styles.alertBadgeSinTaxis : styles.alertBadgeBarandilla
                    ]}>
                      <Ionicons 
                        name={alert.alert_type === 'sin_taxis' ? 'car-outline' : 'warning'} 
                        size={12} 
                        color="#FFFFFF" 
                      />
                      <Text style={styles.alertBadgeText}>
                        {alert.alert_type === 'sin_taxis' ? 'SIN TAXIS' : 'BARANDILLA'}
                      </Text>
                      <Text style={styles.alertBadgeTime}>{formatSecondsAgo(alert.seconds_ago, alert.created_at)}</Text>
                    </View>
                  ))}
                </View>
              );
            }
            return null;
          })()}
          <View style={styles.hottestStreetHeader}>
            <Ionicons name="airplane" size={24} color={
              streetData?.hottest_terminal && (() => {
                const terminalName = streetData.hottest_terminal;
                const terminalKeys = terminalName.includes('-') 
                  ? terminalName.split('-').map((t: string) => t.trim())
                  : [terminalName];
                return terminalKeys.some((t: string) => getLocationAlerts('terminal', t).length > 0) ? '#EF4444' : '#8B5CF6';
              })()
            } />
            <Text style={[styles.hottestStreetTitle,
              streetData?.hottest_terminal && (() => {
                const terminalName = streetData.hottest_terminal;
                const terminalKeys = terminalName.includes('-') 
                  ? terminalName.split('-').map((t: string) => t.trim())
                  : [terminalName];
                return terminalKeys.some((t: string) => getLocationAlerts('terminal', t).length > 0) ? { color: '#EF4444' } : null;
              })()
            ]}>Terminal caliente</Text>
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
          
          {/* GPS button or Close Alert button for terminal */}
          {streetData?.hottest_terminal && (() => {
            const terminalName = streetData.hottest_terminal;
            const terminalKeys = terminalName.includes('-') 
              ? terminalName.split('-').map((t: string) => t.trim())
              : [terminalName];
            const alerts = terminalKeys.flatMap((t: string) => getLocationAlerts('terminal', t));
            
            if (alerts.length > 0) {
              // Show close alert buttons for each active alert
              return (
                <View style={styles.closeAlertButtonsContainer}>
                  {alerts.map((alert, idx) => {
                    const canClose = canUserCloseAlert(alert);
                    const secondsUntilCanClose = getSecondsUntilCanClose(alert);
                    
                    return (
                      <TouchableOpacity
                        key={idx}
                        style={[
                          styles.closeAlertButton,
                          alert.alert_type === 'sin_taxis' ? styles.closeAlertButtonSinTaxis : styles.closeAlertButtonBarandilla,
                          !canClose && styles.closeAlertButtonDisabled
                        ]}
                        onPress={() => {
                          if (canClose) {
                            cancelStationAlert('terminal', alert.location_name, alert.alert_type);
                          } else {
                            Alert.alert('Espera', `Debes esperar ${secondsUntilCanClose}s para cerrar tu propia alerta`);
                          }
                        }}
                        disabled={reportingAlert}
                      >
                        <Ionicons name="close-circle" size={18} color="#FFFFFF" />
                        <Text style={styles.closeAlertButtonText}>
                          Cerrar {alert.alert_type === 'sin_taxis' ? 'Sin Taxis' : 'Barandilla'}
                          {!canClose && ` (${secondsUntilCanClose}s)`}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
              );
            }
            
            // No alerts, show GPS button
            return (
              <TouchableOpacity
                style={[styles.navigateButton, styles.navigateButtonTerminal]}
                onPress={() => openGpsAppOnly()}
              >
                <Ionicons name="navigate" size={20} color="#FFFFFF" />
                <Text style={styles.navigateButtonText}>Ir con GPS</Text>
              </TouchableOpacity>
            );
          })()}
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
          <View style={styles.headerLeft}>
            {/* Radio Button */}
            <TouchableOpacity 
              style={[
                styles.radioButton,
                radioConnected && styles.radioButtonConnected,
                radioTransmitting && styles.radioButtonTransmitting
              ]}
              onPress={() => {
                fetchRadioChannels();
                setShowRadioDropdown(!showRadioDropdown);
              }}
            >
              <Ionicons 
                name="radio" 
                size={20} 
                color={radioTransmitting ? '#FFFFFF' : (radioConnected ? '#10B981' : '#94A3B8')} 
              />
              {radioConnected && (
                <Text style={styles.radioChannelBadge}>{radioChannel}</Text>
              )}
            </TouchableOpacity>
            <Ionicons name="car" size={24} color="#F59E0B" />
          </View>
          <View style={styles.headerActions}>
            {/* Alerts Button */}
            <TouchableOpacity 
              style={[
                styles.alertsButton,
                alertsUnreadCount > 0 && styles.alertsButtonActive
              ]}
              onPress={openAlertsModal}
            >
              <Ionicons 
                name={alertsUnreadCount > 0 ? "notifications" : "notifications-outline"} 
                size={20} 
                color={alertsUnreadCount > 0 ? "#FFFFFF" : "#94A3B8"} 
              />
            </TouchableOpacity>
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

      {/* Radio Dropdown */}
      {showRadioDropdown && (
        <View style={styles.radioDropdownContainer}>
          <View style={styles.radioDropdown}>
            {/* Header */}
            <View style={styles.radioDropdownHeader}>
              <Ionicons name="radio" size={24} color="#10B981" />
              <Text style={styles.radioDropdownTitle}>Radio Walkie-Talkie</Text>
              <TouchableOpacity onPress={() => setShowRadioDropdown(false)}>
                <Ionicons name="close" size={24} color="#9CA3AF" />
              </TouchableOpacity>
            </View>

            {/* Channel Selector */}
            <View style={styles.radioChannelSelector}>
              <Text style={styles.radioSectionLabel}>Canal</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.radioChannelScroll}>
                {radioChannels.map((ch) => (
                  <TouchableOpacity
                    key={ch.channel}
                    style={[
                      styles.radioChannelButton,
                      radioChannel === ch.channel && styles.radioChannelButtonActive,
                      ch.is_busy && styles.radioChannelButtonBusy
                    ]}
                    onPress={() => changeRadioChannel(ch.channel)}
                  >
                    <Text style={[
                      styles.radioChannelButtonText,
                      radioChannel === ch.channel && styles.radioChannelButtonTextActive
                    ]}>
                      {ch.channel}
                    </Text>
                    {ch.user_count > 0 && (
                      <View style={styles.radioChannelUserCount}>
                        <Text style={styles.radioChannelUserCountText}>{ch.user_count}</Text>
                      </View>
                    )}
                  </TouchableOpacity>
                ))}
              </ScrollView>
              <Text style={styles.radioChannelName}>
                {radioChannels.find(c => c.channel === radioChannel)?.channel_name || `Canal ${radioChannel}`}
              </Text>
            </View>

            {/* Users in channel */}
            {radioConnected && radioUsers.length > 0 && (
              <View style={styles.radioUsersSection}>
                <Text style={styles.radioSectionLabel}>En este canal ({radioUsers.length})</Text>
                <View style={styles.radioUsersList}>
                  {radioUsers.map((user) => (
                    <View key={user.user_id} style={[
                      styles.radioUserBadge,
                      user.is_transmitting && styles.radioUserBadgeTransmitting
                    ]}>
                      <Ionicons 
                        name={user.is_transmitting ? "mic" : "person"} 
                        size={12} 
                        color={user.is_transmitting ? "#FFFFFF" : "#9CA3AF"} 
                      />
                      <Text style={[
                        styles.radioUserName,
                        user.is_transmitting && styles.radioUserNameTransmitting
                      ]}>
                        {user.full_name || user.username}
                      </Text>
                    </View>
                  ))}
                </View>
              </View>
            )}

            {/* Control Buttons */}
            <View style={styles.radioControlsRow}>
              {/* Connect/Disconnect */}
              <TouchableOpacity
                style={[
                  styles.radioControlButton,
                  radioConnected ? styles.radioControlButtonDisconnect : styles.radioControlButtonConnect
                ]}
                onPress={toggleRadioConnection}
              >
                <Ionicons 
                  name={radioConnected ? "power" : "power-outline"} 
                  size={24} 
                  color="#FFFFFF" 
                />
                <Text style={styles.radioControlButtonText}>
                  {radioConnected ? 'Desconectar' : 'Conectar'}
                </Text>
              </TouchableOpacity>

              {/* Mute */}
              <TouchableOpacity
                style={[
                  styles.radioControlButton,
                  styles.radioControlButtonMute,
                  radioMuted && styles.radioControlButtonMuteActive
                ]}
                onPress={() => setRadioMuted(!radioMuted)}
                disabled={!radioConnected}
              >
                <Ionicons 
                  name={radioMuted ? "volume-mute" : "volume-high"} 
                  size={24} 
                  color={radioConnected ? "#FFFFFF" : "#6B7280"} 
                />
                <Text style={[
                  styles.radioControlButtonText,
                  !radioConnected && { color: '#6B7280' }
                ]}>
                  {radioMuted ? 'Silenciado' : 'Sonido'}
                </Text>
              </TouchableOpacity>
            </View>

            {/* Push to Talk Button */}
            <TouchableOpacity
              style={[
                styles.radioPTTButton,
                !radioConnected && styles.radioPTTButtonDisabled,
                radioTransmitting && styles.radioPTTButtonActive,
                radioChannelBusy && !radioTransmitting && styles.radioPTTButtonBusy
              ]}
              onPressIn={radioConnected && !radioChannelBusy ? startRadioTransmission : undefined}
              onPressOut={radioConnected ? stopRadioTransmission : undefined}
              disabled={!radioConnected}
            >
              <Ionicons 
                name="mic" 
                size={48} 
                color={radioTransmitting ? "#FFFFFF" : (radioConnected ? "#10B981" : "#6B7280")} 
              />
              <Text style={[
                styles.radioPTTText,
                !radioConnected && { color: '#6B7280' },
                radioTransmitting && { color: '#FFFFFF' }
              ]}>
                {radioTransmitting ? 'TRANSMITIENDO...' : 
                 radioChannelBusy ? 'CANAL OCUPADO' :
                 radioConnected ? 'MANTENER PARA HABLAR' : 'CONECTAR PRIMERO'}
              </Text>
            </TouchableOpacity>

            {/* Transmitting user info */}
            {radioChannelBusy && radioTransmittingUser && !radioTransmitting && (
              <View style={styles.radioTransmittingInfo}>
                <Ionicons name="mic" size={16} color="#F59E0B" />
                <Text style={styles.radioTransmittingText}>
                  {radioUsers.find(u => u.user_id === radioTransmittingUser)?.full_name || 
                   radioUsers.find(u => u.user_id === radioTransmittingUser)?.username || 
                   'Alguien'} está hablando...
                </Text>
              </View>
            )}
          </View>
        </View>
      )}

      {/* Tab Selector */}
      {/* NEW: Dropdowns Row - Page and Shift selectors */}
      <View style={styles.dropdownsRow}>
        {/* Page Dropdown */}
        <TouchableOpacity
          style={styles.dropdownSelector}
          onPress={() => {
            setShowPageDropdown(true);
            setShowShiftDropdown(false);
            setShowTimeRangeDropdown(false);
          }}
        >
          <Ionicons
            name={
              activeTab === 'trains' ? 'train' :
              activeTab === 'flights' ? 'airplane' :
              activeTab === 'street' ? 'car' :
              activeTab === 'events' ? 'calendar' :
              'shield-checkmark'
            }
            size={18}
            color="#6366F1"
          />
          <Text style={styles.dropdownSelectorText}>
            {activeTab === 'trains' ? 'Trenes' :
             activeTab === 'flights' ? 'Aviones' :
             activeTab === 'street' ? 'Calle' :
             activeTab === 'events' ? 'Eventos' :
             'Admin'}
          </Text>
          <Ionicons name="chevron-down" size={16} color="#94A3B8" />
        </TouchableOpacity>
        
        {/* Shift Dropdown - visible for trains only, but space reserved */}
        <TouchableOpacity
          style={[
            styles.dropdownSelector,
            activeTab !== 'trains' && styles.dropdownSelectorHidden
          ]}
          onPress={() => {
            if (activeTab === 'trains') {
              setShowShiftDropdown(true);
              setShowPageDropdown(false);
              setShowTimeRangeDropdown(false);
            }
          }}
          disabled={activeTab !== 'trains'}
        >
          <Ionicons
            name={shift === 'day' ? 'sunny' : shift === 'night' ? 'moon' : 'time'}
            size={18}
            color={shift === 'day' ? '#F59E0B' : shift === 'night' ? '#8B5CF6' : '#6366F1'}
          />
          <Text style={styles.dropdownSelectorText}>
            {shift === 'day' ? 'Diurno' : shift === 'night' ? 'Nocturno' : 'Todos'}
          </Text>
          <Ionicons name="chevron-down" size={16} color="#94A3B8" />
        </TouchableOpacity>
        
        {/* Chat Button */}
        <TouchableOpacity
          style={styles.chatButtonCompact}
          onPress={openChatModal}
        >
          <Ionicons name="chatbubbles" size={20} color="#FFFFFF" />
        </TouchableOpacity>
        
        {/* SOS Button */}
        <TouchableOpacity
          style={[
            styles.sosButtonCompact,
            myActiveAlert && styles.sosButtonActive
          ]}
          onPress={() => setShowSosModal(true)}
        >
          <Ionicons 
            name={myActiveAlert ? "alert-circle" : "shield-checkmark-outline"} 
            size={18} 
            color={myActiveAlert ? "#FFFFFF" : "#9CA3AF"} 
          />
        </TouchableOpacity>
      </View>
      
      {/* Time Range Row with 30/60 buttons inside */}
      <View style={styles.timeRangeRow}>
        {/* Time Window Buttons (30/60) */}
        <View style={styles.timeWindowButtonsInline}>
          <TouchableOpacity
            style={[
              styles.timeWindowButtonSmall,
              timeWindow === 30 && styles.activeTimeWindowSmall,
            ]}
            onPress={() => setTimeWindow(30)}
          >
            <Text
              style={[
                styles.timeWindowTextSmall,
                timeWindow === 30 && styles.activeTimeWindowTextSmall,
              ]}
            >
              30m
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.timeWindowButtonSmall,
              timeWindow === 60 && styles.activeTimeWindowSmall,
            ]}
            onPress={() => setTimeWindow(60)}
          >
            <Text
              style={[
                styles.timeWindowTextSmall,
                timeWindow === 60 && styles.activeTimeWindowTextSmall,
              ]}
            >
              60m
            </Text>
          </TouchableOpacity>
        </View>
        
        {/* Time Range Dropdown */}
        <TouchableOpacity
          style={[
            styles.timeRangeDropdownFull,
            selectedTimeRange !== 'now' && styles.timeRangeDropdownFullActive
          ]}
          onPress={() => {
            setShowTimeRangeDropdown(true);
            setShowPageDropdown(false);
            setShowShiftDropdown(false);
          }}
        >
          <Ionicons 
            name="time-outline" 
            size={18} 
            color={selectedTimeRange !== 'now' ? "#10B981" : "#F59E0B"} 
          />
          <Text style={[
            styles.timeRangeDropdownTextFull,
            selectedTimeRange !== 'now' && styles.timeRangeDropdownTextFullActive
          ]}>
            {getSelectedTimeRangeLabel()}
          </Text>
          <Ionicons 
            name="chevron-down" 
            size={16} 
            color={selectedTimeRange !== 'now' ? "#10B981" : "#94A3B8"} 
          />
        </TouchableOpacity>
      </View>
      
      {/* Page Dropdown Modal */}
      <Modal
        visible={showPageDropdown}
        transparent
        animationType="fade"
        onRequestClose={() => setShowPageDropdown(false)}
      >
        <TouchableOpacity
          style={styles.dropdownOverlay}
          activeOpacity={1}
          onPress={() => setShowPageDropdown(false)}
        >
          <View style={styles.dropdownMenu}>
            <Text style={styles.dropdownMenuTitle}>Seleccionar Página</Text>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, activeTab === 'trains' && styles.dropdownMenuItemActive]}
              onPress={() => {
                if (activeTab !== 'trains') {
                  setLoading(true);
                  setActiveTab('trains');
                }
                setShowPageDropdown(false);
              }}
            >
              <Ionicons name="train" size={20} color={activeTab === 'trains' ? '#6366F1' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, activeTab === 'trains' && styles.dropdownMenuItemTextActive]}>Trenes</Text>
              {activeTab === 'trains' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, activeTab === 'flights' && styles.dropdownMenuItemActive]}
              onPress={() => {
                if (activeTab !== 'flights') {
                  setLoading(true);
                  setActiveTab('flights');
                }
                setShowPageDropdown(false);
              }}
            >
              <Ionicons name="airplane" size={20} color={activeTab === 'flights' ? '#6366F1' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, activeTab === 'flights' && styles.dropdownMenuItemTextActive]}>Aviones</Text>
              {activeTab === 'flights' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, activeTab === 'street' && styles.dropdownMenuItemActive]}
              onPress={() => {
                if (activeTab !== 'street') {
                  setLoading(true);
                  setActiveTab('street');
                }
                setShowPageDropdown(false);
              }}
            >
              <Ionicons name="car" size={20} color={activeTab === 'street' ? '#6366F1' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, activeTab === 'street' && styles.dropdownMenuItemTextActive]}>Calle</Text>
              {activeTab === 'street' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, activeTab === 'events' && styles.dropdownMenuItemActive]}
              onPress={() => {
                if (activeTab !== 'events') {
                  setLoading(true);
                  setActiveTab('events');
                }
                setShowPageDropdown(false);
              }}
            >
              <Ionicons name="calendar" size={20} color={activeTab === 'events' ? '#6366F1' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, activeTab === 'events' && styles.dropdownMenuItemTextActive]}>Eventos</Text>
              {activeTab === 'events' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
            
            {currentUser?.role === 'admin' && (
              <TouchableOpacity
                style={[styles.dropdownMenuItem, activeTab === 'admin' && styles.dropdownMenuItemActive]}
                onPress={() => {
                  if (activeTab !== 'admin') {
                    setLoading(true);
                    setActiveTab('admin');
                  }
                  setShowPageDropdown(false);
                }}
              >
                <Ionicons name="shield-checkmark" size={20} color={activeTab === 'admin' ? '#6366F1' : '#94A3B8'} />
                <Text style={[styles.dropdownMenuItemText, activeTab === 'admin' && styles.dropdownMenuItemTextActive]}>Admin</Text>
                {activeTab === 'admin' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
              </TouchableOpacity>
            )}
          </View>
        </TouchableOpacity>
      </Modal>
      
      {/* Shift Dropdown Modal */}
      <Modal
        visible={showShiftDropdown}
        transparent
        animationType="fade"
        onRequestClose={() => setShowShiftDropdown(false)}
      >
        <TouchableOpacity
          style={styles.dropdownOverlay}
          activeOpacity={1}
          onPress={() => setShowShiftDropdown(false)}
        >
          <View style={styles.dropdownMenu}>
            <Text style={styles.dropdownMenuTitle}>Seleccionar Turno</Text>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, shift === 'all' && styles.dropdownMenuItemActive]}
              onPress={() => {
                setShift('all');
                setShowShiftDropdown(false);
              }}
            >
              <Ionicons name="time" size={20} color={shift === 'all' ? '#6366F1' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, shift === 'all' && styles.dropdownMenuItemTextActive]}>Todos los turnos</Text>
              {shift === 'all' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, shift === 'day' && styles.dropdownMenuItemActive]}
              onPress={() => {
                setShift('day');
                setShowShiftDropdown(false);
              }}
            >
              <Ionicons name="sunny" size={20} color={shift === 'day' ? '#F59E0B' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, shift === 'day' && styles.dropdownMenuItemTextActive]}>Diurno (05:00 - 17:00)</Text>
              {shift === 'day' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
            
            <TouchableOpacity
              style={[styles.dropdownMenuItem, shift === 'night' && styles.dropdownMenuItemActive]}
              onPress={() => {
                setShift('night');
                setShowShiftDropdown(false);
              }}
            >
              <Ionicons name="moon" size={20} color={shift === 'night' ? '#8B5CF6' : '#94A3B8'} />
              <Text style={[styles.dropdownMenuItemText, shift === 'night' && styles.dropdownMenuItemTextActive]}>Nocturno (17:00 - 05:00)</Text>
              {shift === 'night' && <Ionicons name="checkmark" size={20} color="#6366F1" />}
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      </Modal>

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
                {refreshing ? (
                  <ActivityIndicator size="small" color="#6366F1" />
                ) : (
                  <Ionicons name="refresh" size={18} color="#6366F1" />
                )}
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
            <View style={styles.lastUpdateRow}>
              <View style={styles.lastUpdate}>
                <Ionicons name="time-outline" size={14} color="#64748B" />
                <Text style={styles.lastUpdateText}>
                  Actualizado: {formatLastUpdate(flightData.last_update)}
                </Text>
              </View>
              <TouchableOpacity 
                style={styles.refreshButton} 
                onPress={onRefresh}
                disabled={refreshing}
              >
                {refreshing ? (
                  <ActivityIndicator size="small" color="#3B82F6" />
                ) : (
                  <Ionicons name="refresh" size={18} color="#3B82F6" />
                )}
                <Text style={[styles.refreshText, refreshing && styles.refreshTextDisabled]}>
                  {refreshing ? 'Actualizando...' : 'Actualizar'}
                </Text>
              </TouchableOpacity>
            </View>
            {flightData.message && (
              <View style={styles.nightTimeMessage}>
                <Ionicons name="information-circle" size={16} color="#F59E0B" />
                <Text style={styles.nightTimeText}>{flightData.message}</Text>
              </View>
            )}
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
        ) : activeTab === 'events' ? (
          <View style={styles.eventsContainer}>
            {/* Add Event Button */}
            <TouchableOpacity 
              style={styles.addEventButton}
              onPress={() => setShowAddEventModal(true)}
            >
              <Ionicons name="add-circle" size={24} color="#FFFFFF" />
              <Text style={styles.addEventButtonText}>Añadir Evento</Text>
            </TouchableOpacity>

            {/* Events List */}
            {eventsData.length === 0 ? (
              <View style={styles.noEventsContainer}>
                <Ionicons name="calendar-outline" size={64} color="#4B5563" />
                <Text style={styles.noEventsText}>No hay eventos para hoy</Text>
                <Text style={styles.noEventsSubtext}>Sé el primero en añadir un evento</Text>
              </View>
            ) : (
              eventsData.map((event) => (
                <View key={event.event_id} style={styles.eventCard}>
                  <View style={styles.eventHeader}>
                    <View style={styles.eventTimeContainer}>
                      <Ionicons name="time" size={18} color="#6366F1" />
                      <Text style={styles.eventTime}>{event.event_time}</Text>
                    </View>
                    <Text style={styles.eventUsername}>@{event.username}</Text>
                  </View>
                  
                  <View style={styles.eventBody}>
                    <View style={styles.eventLocationRow}>
                      <Ionicons name="location" size={18} color="#F59E0B" />
                      <Text style={styles.eventLocation}>{event.location}</Text>
                    </View>
                    <Text style={styles.eventDescription}>{event.description}</Text>
                  </View>

                  <View style={styles.eventFooter}>
                    <View style={styles.eventVotes}>
                      <TouchableOpacity 
                        style={[
                          styles.voteButton,
                          event.user_vote === 'like' && styles.voteButtonActive
                        ]}
                        onPress={() => voteEvent(event.event_id, 'like')}
                      >
                        <Ionicons 
                          name="thumbs-up" 
                          size={20} 
                          color={event.user_vote === 'like' ? '#10B981' : '#9CA3AF'} 
                        />
                        <Text style={[
                          styles.voteCount,
                          event.user_vote === 'like' && styles.voteCountActive
                        ]}>{event.likes}</Text>
                      </TouchableOpacity>

                      <TouchableOpacity 
                        style={[
                          styles.voteButton,
                          event.user_vote === 'dislike' && styles.voteButtonActiveDislike
                        ]}
                        onPress={() => voteEvent(event.event_id, 'dislike')}
                      >
                        <Ionicons 
                          name="thumbs-down" 
                          size={20} 
                          color={event.user_vote === 'dislike' ? '#EF4444' : '#9CA3AF'} 
                        />
                        <Text style={[
                          styles.voteCount,
                          event.user_vote === 'dislike' && styles.voteCountActiveDislike
                        ]}>{event.dislikes}</Text>
                      </TouchableOpacity>
                    </View>

                    {event.can_delete && (
                      <TouchableOpacity 
                        style={styles.deleteEventButton}
                        onPress={() => {
                          if (Platform.OS === 'web') {
                            if (window.confirm('¿Estás seguro de que quieres eliminar este evento?')) {
                              deleteEvent(event.event_id);
                            }
                          } else {
                            Alert.alert(
                              'Eliminar evento',
                              '¿Estás seguro de que quieres eliminar este evento?',
                              [
                                { text: 'Cancelar', style: 'cancel' },
                                { text: 'Eliminar', style: 'destructive', onPress: () => deleteEvent(event.event_id) }
                              ]
                            );
                          }
                        }}
                      >
                        <Ionicons name="trash-outline" size={18} color="#EF4444" />
                      </TouchableOpacity>
                    )}
                  </View>
                </View>
              ))
            )}
          </View>
        ) : activeTab === 'admin' ? (
          <View style={styles.adminContainer}>
            {/* Admin Header */}
            <View style={styles.adminHeader}>
              <View style={styles.adminHeaderTitle}>
                <Ionicons name="shield-checkmark" size={28} color="#EF4444" />
                <Text style={styles.adminTitle}>Panel de Administración</Text>
              </View>
            </View>

            {/* Stats Cards */}
            <View style={styles.adminStatsRow}>
              <View style={[styles.adminStatCard, { backgroundColor: '#6366F120' }]}>
                <Ionicons name="people" size={24} color="#6366F1" />
                <Text style={styles.adminStatNumber}>{adminStats?.total_users || 0}</Text>
                <Text style={styles.adminStatLabel}>Registrados</Text>
              </View>
              <View style={[styles.adminStatCard, { backgroundColor: '#F59E0B20' }]}>
                <Ionicons name="calendar" size={24} color="#F59E0B" />
                <Text style={styles.adminStatNumber}>{adminStats?.active_last_month || 0}</Text>
                <Text style={styles.adminStatLabel}>Activos (mes)</Text>
              </View>
              <View style={[styles.adminStatCard, { backgroundColor: '#10B98120' }]}>
                <Ionicons name="radio-button-on" size={24} color="#10B981" />
                <Text style={styles.adminStatNumber}>{adminStats?.online_now || 0}</Text>
                <Text style={styles.adminStatLabel}>En línea</Text>
              </View>
            </View>

            {/* Search Bar */}
            <View style={styles.adminSearchContainer}>
              <View style={styles.adminSearchInputWrapper}>
                <Ionicons name="search" size={20} color="#9CA3AF" />
                <TextInput
                  style={styles.adminSearchInput}
                  placeholder="Buscar por nombre o licencia..."
                  placeholderTextColor="#6B7280"
                  value={adminSearchQuery}
                  onChangeText={setAdminSearchQuery}
                  autoCapitalize="none"
                />
                {adminSearchQuery.length > 0 && (
                  <TouchableOpacity onPress={() => setAdminSearchQuery('')}>
                    <Ionicons name="close-circle" size={20} color="#6B7280" />
                  </TouchableOpacity>
                )}
              </View>
            </View>

            {/* Action Buttons */}
            <View style={styles.adminActionsRow}>
              <TouchableOpacity 
                style={styles.adminActionButton}
                onPress={() => setShowCreateUserModal(true)}
              >
                <Ionicons name="person-add" size={20} color="#FFFFFF" />
                <Text style={styles.adminActionButtonText}>Crear Usuario</Text>
              </TouchableOpacity>
              <TouchableOpacity 
                style={[styles.adminActionButton, styles.adminActionButtonSecondary]}
                onPress={() => setShowUsersList(!showUsersList)}
              >
                <Ionicons name={showUsersList ? "chevron-up" : "list"} size={20} color="#6366F1" />
                <Text style={[styles.adminActionButtonText, { color: '#6366F1' }]}>
                  {showUsersList ? 'Ocultar Lista' : 'Ver Todos'}
                </Text>
              </TouchableOpacity>
            </View>
            
            {/* Blocked Users Button */}
            <TouchableOpacity 
              style={[styles.adminBlockedUsersButton, showBlockedUsers && styles.adminBlockedUsersButtonActive]}
              onPress={() => {
                setShowBlockedUsers(!showBlockedUsers);
                if (!showBlockedUsers && !blockedUsersData) {
                  fetchBlockedUsers();
                }
              }}
            >
              <View style={styles.adminBlockedUsersButtonContent}>
                <Ionicons name="ban" size={22} color={showBlockedUsers ? '#FFFFFF' : '#EF4444'} />
                <Text style={[styles.adminBlockedUsersButtonText, showBlockedUsers && { color: '#FFFFFF' }]}>
                  Gestión de Bloqueos
                </Text>
              </View>
              <Ionicons name={showBlockedUsers ? "chevron-up" : "chevron-down"} size={20} color={showBlockedUsers ? '#FFFFFF' : '#EF4444'} />
            </TouchableOpacity>

            {/* Blocked Users Section */}
            {showBlockedUsers && (
              <View style={styles.blockedUsersSection}>
                {blockedUsersLoading ? (
                  <View style={styles.blockedUsersLoading}>
                    <ActivityIndicator color="#EF4444" />
                    <Text style={styles.blockedUsersLoadingText}>Cargando usuarios bloqueados...</Text>
                  </View>
                ) : blockedUsersData ? (
                  <>
                    {/* Blocked Users Stats */}
                    <View style={styles.blockedUsersStatsRow}>
                      <View style={[styles.blockedUserStatCard, { backgroundColor: '#EF444420' }]}>
                        <Text style={styles.blockedUserStatNumber}>{blockedUsersData.total_blocked}</Text>
                        <Text style={styles.blockedUserStatLabel}>Bloqueados</Text>
                      </View>
                      <View style={[styles.blockedUserStatCard, { backgroundColor: '#F59E0B20' }]}>
                        <Text style={styles.blockedUserStatNumber}>{blockedUsersData.alert_blocks}</Text>
                        <Text style={styles.blockedUserStatLabel}>Por Avisos</Text>
                      </View>
                      <View style={[styles.blockedUserStatCard, { backgroundColor: '#8B5CF620' }]}>
                        <Text style={styles.blockedUserStatNumber}>{blockedUsersData.chat_blocks}</Text>
                        <Text style={styles.blockedUserStatLabel}>Por Chat</Text>
                      </View>
                    </View>

                    {/* Refresh Button */}
                    <TouchableOpacity 
                      style={styles.blockedUsersRefreshButton}
                      onPress={fetchBlockedUsers}
                    >
                      <Ionicons name="refresh" size={18} color="#9CA3AF" />
                      <Text style={styles.blockedUsersRefreshText}>Actualizar lista</Text>
                    </TouchableOpacity>

                    {/* Blocked Users List */}
                    {blockedUsersData.blocked_users.length === 0 ? (
                      <View style={styles.noBlockedUsers}>
                        <Ionicons name="checkmark-circle" size={48} color="#10B981" />
                        <Text style={styles.noBlockedUsersText}>No hay usuarios bloqueados</Text>
                      </View>
                    ) : (
                      blockedUsersData.blocked_users.map((user) => {
                        const hasActiveAlertBlock = user.alert_block_status === 'temporary' || user.alert_block_status === 'permanent';
                        const hasActiveChatBlock = user.chat_block_status === 'temporary' || user.chat_block_status === 'permanent';
                        const isPermanent = user.alert_block_status === 'permanent' || user.chat_block_status === 'permanent';
                        
                        return (
                          <View key={user.id} style={[
                            styles.blockedUserCard,
                            isPermanent && styles.blockedUserCardPermanent,
                            !isPermanent && (hasActiveAlertBlock || hasActiveChatBlock) && styles.blockedUserCardTemporary,
                            !hasActiveAlertBlock && !hasActiveChatBlock && styles.blockedUserCardExpired
                          ]}>
                            <View style={styles.blockedUserHeader}>
                              <View style={styles.blockedUserInfo}>
                                <Text style={styles.blockedUserName}>{user.full_name || user.username}</Text>
                                <Text style={styles.blockedUserUsername}>@{user.username}</Text>
                                {user.license_number && (
                                  <Text style={styles.blockedUserLicense}>Licencia: {user.license_number}</Text>
                                )}
                              </View>
                              {/* Block reason badges */}
                              <View style={styles.blockReasonBadges}>
                                {user.block_reasons?.includes('avisos_fraudulentos') && (
                                  <View style={[styles.blockReasonBadge, { backgroundColor: '#F59E0B' }]}>
                                    <Ionicons name="warning" size={10} color="#FFFFFF" />
                                    <Text style={styles.blockReasonBadgeText}>Avisos</Text>
                                  </View>
                                )}
                                {user.block_reasons?.includes('mensajes_indebidos') && (
                                  <View style={[styles.blockReasonBadge, { backgroundColor: '#8B5CF6' }]}>
                                    <Ionicons name="chatbubble" size={10} color="#FFFFFF" />
                                    <Text style={styles.blockReasonBadgeText}>Chat</Text>
                                  </View>
                                )}
                                {isPermanent && (
                                  <View style={[styles.blockReasonBadge, { backgroundColor: '#7F1D1D' }]}>
                                    <Text style={styles.blockReasonBadgeText}>🚫 PERMANENTE</Text>
                                  </View>
                                )}
                              </View>
                            </View>
                            
                            {/* Alert fraud stats */}
                            {user.alert_fraud_count > 0 && (
                              <View style={styles.blockedUserStatsSection}>
                                <Text style={styles.blockedUserStatsSectionTitle}>📍 Avisos fraudulentos</Text>
                                <View style={styles.blockedUserStats}>
                                  <View style={styles.blockedUserStatItem}>
                                    <Ionicons name="warning" size={14} color="#F59E0B" />
                                    <Text style={styles.blockedUserStatText}>
                                      {user.alert_fraud_count} avisos
                                    </Text>
                                  </View>
                                  {hasActiveAlertBlock && user.alert_hours_remaining && (
                                    <View style={styles.blockedUserStatItem}>
                                      <Ionicons name="time" size={14} color="#EF4444" />
                                      <Text style={styles.blockedUserStatText}>
                                        {user.alert_hours_remaining}h restantes
                                      </Text>
                                    </View>
                                  )}
                                </View>
                              </View>
                            )}
                            
                            {/* Chat abuse stats */}
                            {user.chat_abuse_count > 0 && (
                              <View style={styles.blockedUserStatsSection}>
                                <Text style={styles.blockedUserStatsSectionTitle}>💬 Mensajes indebidos</Text>
                                <View style={styles.blockedUserStats}>
                                  <View style={styles.blockedUserStatItem}>
                                    <Ionicons name="chatbubble" size={14} color="#8B5CF6" />
                                    <Text style={styles.blockedUserStatText}>
                                      {user.chat_abuse_count} mensajes
                                    </Text>
                                  </View>
                                  {hasActiveChatBlock && user.chat_hours_remaining && (
                                    <View style={styles.blockedUserStatItem}>
                                      <Ionicons name="time" size={14} color="#EF4444" />
                                      <Text style={styles.blockedUserStatText}>
                                        {user.chat_hours_remaining}h restantes
                                      </Text>
                                    </View>
                                  )}
                                  {user.last_chat_abuse_message && (
                                    <Text style={styles.blockedUserAbuseMessage} numberOfLines={1}>
                                      "{user.last_chat_abuse_message}"
                                    </Text>
                                  )}
                                </View>
                              </View>
                            )}
                            
                            <View style={styles.blockedUserActions}>
                              {(hasActiveAlertBlock || hasActiveChatBlock) && (
                                <TouchableOpacity 
                                  style={styles.unblockButton}
                                  onPress={() => unblockUser(user.id)}
                                >
                                  <Ionicons name="lock-open" size={16} color="#10B981" />
                                  <Text style={styles.unblockButtonText}>Desbloquear</Text>
                                </TouchableOpacity>
                              )}
                              <TouchableOpacity 
                                style={styles.resetFraudButton}
                                onPress={() => resetFraudCount(user.id)}
                              >
                                <Ionicons name="refresh" size={16} color="#F59E0B" />
                                <Text style={styles.resetFraudButtonText}>Resetear</Text>
                              </TouchableOpacity>
                            </View>
                          </View>
                        );
                      })
                    )}
                  </>
                ) : (
                  <TouchableOpacity 
                    style={styles.blockedUsersLoadButton}
                    onPress={fetchBlockedUsers}
                  >
                    <Text style={styles.blockedUsersLoadButtonText}>Cargar usuarios bloqueados</Text>
                  </TouchableOpacity>
                )}
              </View>
            )}

            {/* Search Results */}
            {adminSearchQuery.length > 0 && (
              <View style={styles.adminSearchResults}>
                <Text style={styles.adminSectionTitle}>
                  Resultados de búsqueda {adminSearching && '...'}
                </Text>
                {adminSearchResults.length === 0 && !adminSearching ? (
                  <Text style={styles.adminNoResults}>No se encontraron usuarios</Text>
                ) : (
                  adminSearchResults.map((user: any) => (
                    <View key={user.id} style={styles.userCard}>
                      <View style={styles.userCardHeader}>
                        <View style={styles.userInfo}>
                          <View style={styles.userAvatarContainer}>
                            <Ionicons name="person-circle" size={40} color="#6B7280" />
                            {user.is_online && <View style={styles.onlineIndicator} />}
                          </View>
                          <View style={styles.userDetails}>
                            <Text style={styles.userName}>{user.full_name || user.username}</Text>
                            <Text style={styles.userLicense}>
                              {user.license_number ? `Licencia: ${user.license_number}` : user.username}
                            </Text>
                            <View style={[styles.roleBadge, { backgroundColor: getRoleBadgeColor(user.role) }]}>
                              <Text style={styles.roleBadgeText}>{getRoleDisplayName(user.role)}</Text>
                            </View>
                          </View>
                        </View>
                        
                        {user.id !== currentUser?.id && (
                          <View style={styles.userActions}>
                            <TouchableOpacity
                              style={styles.editUserButton}
                              onPress={() => {
                                setEditingUser(user);
                                setShowEditUserModal(true);
                              }}
                            >
                              <Ionicons name="create-outline" size={20} color="#3B82F6" />
                            </TouchableOpacity>
                            <TouchableOpacity
                              style={styles.deleteUserButton}
                              onPress={() => deleteUser(user.id, user.username)}
                            >
                              <Ionicons name="trash-outline" size={20} color="#EF4444" />
                            </TouchableOpacity>
                          </View>
                        )}
                      </View>
                    </View>
                  ))
                )}
              </View>
            )}

            {/* Users List (collapsible) */}
            {showUsersList && adminSearchQuery.length === 0 && (
              <>
                <Text style={styles.adminSectionTitle}>Todos los usuarios</Text>
                {adminLoading ? (
                  <View style={styles.loadingContainer}>
                    <ActivityIndicator size="large" color="#EF4444" />
                    <Text style={styles.loadingText}>Cargando usuarios...</Text>
                  </View>
                ) : adminUsers.length === 0 ? (
                  <View style={styles.noEventsContainer}>
                    <Ionicons name="people-outline" size={64} color="#4B5563" />
                    <Text style={styles.noEventsText}>No hay usuarios</Text>
                  </View>
                ) : (
                  adminUsers.map((user: any) => (
                    <View key={user.id} style={styles.userCard}>
                      <View style={styles.userCardHeader}>
                        <View style={styles.userInfo}>
                          <View style={styles.userAvatarContainer}>
                            <Ionicons name="person-circle" size={40} color="#6B7280" />
                            {user.is_online && <View style={styles.onlineIndicator} />}
                          </View>
                          <View style={styles.userDetails}>
                            <Text style={styles.userName}>{user.full_name || user.username}</Text>
                            <Text style={styles.userLicense}>
                              {user.license_number ? `Licencia: ${user.license_number}` : `@${user.username}`}
                            </Text>
                            <View style={[styles.roleBadge, { backgroundColor: getRoleBadgeColor(user.role) }]}>
                              <Text style={styles.roleBadgeText}>{getRoleDisplayName(user.role)}</Text>
                            </View>
                          </View>
                        </View>
                        
                        {user.id !== currentUser?.id && (
                          <View style={styles.userActions}>
                            <TouchableOpacity
                              style={styles.editUserButton}
                              onPress={() => {
                                setEditingUser(user);
                                setShowEditUserModal(true);
                              }}
                            >
                              <Ionicons name="create-outline" size={20} color="#3B82F6" />
                            </TouchableOpacity>
                            <TouchableOpacity
                              style={styles.deleteUserButton}
                              onPress={() => deleteUser(user.id, user.username)}
                            >
                              <Ionicons name="trash-outline" size={20} color="#EF4444" />
                            </TouchableOpacity>
                          </View>
                        )}
                      </View>
                      
                      {user.phone && (
                        <View style={styles.userPhone}>
                          <Ionicons name="call-outline" size={14} color="#9CA3AF" />
                          <Text style={styles.userPhoneText}>{user.phone}</Text>
                        </View>
                      )}
                    </View>
                  ))
                )}
              </>
            )}
          </View>
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
            
            {/* Profile Section */}
            <View style={styles.settingsSection}>
              <Text style={styles.settingsSectionTitle}>Mi Perfil</Text>
              <TouchableOpacity
                style={styles.profileButton}
                onPress={() => {
                  setShowSettings(false);
                  openProfileModal();
                }}
              >
                <View style={styles.profileButtonContent}>
                  <Ionicons name="person-circle" size={40} color="#6366F1" />
                  <View style={styles.profileButtonInfo}>
                    <Text style={styles.profileButtonName}>
                      {currentUser?.full_name || currentUser?.username}
                    </Text>
                    <Text style={styles.profileButtonLicense}>
                      {currentUser?.license_number ? `Licencia: ${currentUser.license_number}` : 'Completar perfil'}
                    </Text>
                  </View>
                </View>
                <Ionicons name="chevron-forward" size={22} color="#64748B" />
              </TouchableOpacity>
              
              {/* Change Password Button */}
              <TouchableOpacity
                style={styles.changePasswordButton}
                onPress={() => {
                  setShowSettings(false);
                  setShowChangePasswordModal(true);
                }}
              >
                <View style={styles.profileButtonContent}>
                  <Ionicons name="key" size={32} color="#F59E0B" />
                  <View style={styles.profileButtonInfo}>
                    <Text style={styles.profileButtonName}>Cambiar Contraseña</Text>
                    <Text style={styles.profileButtonLicense}>Actualizar credenciales de acceso</Text>
                  </View>
                </View>
                <Ionicons name="chevron-forward" size={22} color="#64748B" />
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

      {/* Profile Edit Modal */}
      {showProfileModal && (
        <View style={styles.modalOverlay}>
          <ScrollView contentContainerStyle={styles.profileModalScrollContainer}>
            <View style={styles.profileModal}>
              <View style={styles.profileModalHeader}>
                <Ionicons name="person-circle" size={60} color="#6366F1" />
                <Text style={styles.profileModalTitle}>Mi Perfil</Text>
                <Text style={styles.profileModalSubtitle}>@{currentUser?.username}</Text>
              </View>
              
              <View style={styles.profileForm}>
                <View style={styles.profileInputGroup}>
                  <Text style={styles.profileInputLabel}>Nombre completo *</Text>
                  <TextInput
                    style={styles.profileInput}
                    value={profileFullName}
                    onChangeText={setProfileFullName}
                    placeholder="Tu nombre completo"
                    placeholderTextColor="#6B7280"
                  />
                </View>
                
                <View style={styles.profileInputGroup}>
                  <Text style={styles.profileInputLabel}>Número de licencia *</Text>
                  <TextInput
                    style={styles.profileInput}
                    value={profileLicenseNumber}
                    onChangeText={setProfileLicenseNumber}
                    placeholder="Solo números"
                    placeholderTextColor="#6B7280"
                    keyboardType="numeric"
                  />
                </View>
                
                <View style={styles.profileInputGroup}>
                  <Text style={styles.profileInputLabel}>Teléfono</Text>
                  <TextInput
                    style={styles.profileInput}
                    value={profilePhone}
                    onChangeText={setProfilePhone}
                    placeholder="Tu número de teléfono"
                    placeholderTextColor="#6B7280"
                    keyboardType="phone-pad"
                  />
                </View>
                
                <View style={styles.profileInputGroup}>
                  <Text style={styles.profileInputLabel}>Turno de preferencia</Text>
                  <View style={styles.profileShiftSelector}>
                    <TouchableOpacity
                      style={[
                        styles.profileShiftOption,
                        profilePreferredShift === 'day' && styles.profileShiftOptionActiveDay
                      ]}
                      onPress={() => setProfilePreferredShift('day')}
                    >
                      <Ionicons name="sunny" size={20} color={profilePreferredShift === 'day' ? '#FFFFFF' : '#F59E0B'} />
                      <Text style={[
                        styles.profileShiftOptionText,
                        profilePreferredShift === 'day' && styles.profileShiftOptionTextActive
                      ]}>Día</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.profileShiftOption,
                        profilePreferredShift === 'all' && styles.profileShiftOptionActiveAll
                      ]}
                      onPress={() => setProfilePreferredShift('all')}
                    >
                      <Ionicons name="time" size={20} color={profilePreferredShift === 'all' ? '#FFFFFF' : '#6366F1'} />
                      <Text style={[
                        styles.profileShiftOptionText,
                        profilePreferredShift === 'all' && styles.profileShiftOptionTextActive
                      ]}>Todo</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={[
                        styles.profileShiftOption,
                        profilePreferredShift === 'night' && styles.profileShiftOptionActiveNight
                      ]}
                      onPress={() => setProfilePreferredShift('night')}
                    >
                      <Ionicons name="moon" size={20} color={profilePreferredShift === 'night' ? '#FFFFFF' : '#8B5CF6'} />
                      <Text style={[
                        styles.profileShiftOptionText,
                        profilePreferredShift === 'night' && styles.profileShiftOptionTextActive
                      ]}>Noche</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
              
              <View style={styles.profileButtons}>
                <TouchableOpacity
                  style={styles.profileCancelButton}
                  onPress={() => setShowProfileModal(false)}
                >
                  <Text style={styles.profileCancelButtonText}>Cancelar</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={styles.profileSaveButton}
                  onPress={handleUpdateProfile}
                  disabled={profileLoading}
                >
                  {profileLoading ? (
                    <ActivityIndicator color="#FFFFFF" size="small" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                      <Text style={styles.profileSaveButtonText}>Guardar</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          </ScrollView>
        </View>
      )}

      {/* Change Password Modal */}
      {showChangePasswordModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.changePasswordModal}>
            <View style={styles.changePasswordHeader}>
              <Ionicons name="key" size={48} color="#F59E0B" />
              <Text style={styles.changePasswordTitle}>Cambiar Contraseña</Text>
              <Text style={styles.changePasswordSubtitle}>
                Ingresa tu contraseña actual y la nueva contraseña
              </Text>
            </View>

            <View style={styles.changePasswordForm}>
              <View style={styles.inputContainer}>
                <Ionicons name="lock-closed-outline" size={20} color="#64748B" style={styles.inputIcon} />
                <TextInput
                  style={styles.loginScreenInput}
                  placeholder="Contraseña actual"
                  placeholderTextColor="#64748B"
                  value={currentPassword}
                  onChangeText={setCurrentPassword}
                  secureTextEntry
                />
              </View>

              <View style={styles.inputContainer}>
                <Ionicons name="key-outline" size={20} color="#64748B" style={styles.inputIcon} />
                <TextInput
                  style={styles.loginScreenInput}
                  placeholder="Nueva contraseña"
                  placeholderTextColor="#64748B"
                  value={newPassword}
                  onChangeText={setNewPassword}
                  secureTextEntry
                />
              </View>

              <View style={styles.inputContainer}>
                <Ionicons name="key" size={20} color="#64748B" style={styles.inputIcon} />
                <TextInput
                  style={styles.loginScreenInput}
                  placeholder="Confirmar nueva contraseña"
                  placeholderTextColor="#64748B"
                  value={newPasswordConfirm}
                  onChangeText={setNewPasswordConfirm}
                  secureTextEntry
                />
              </View>
              
              {newPassword && newPasswordConfirm && newPassword !== newPasswordConfirm && (
                <Text style={styles.passwordMismatchText}>Las contraseñas no coinciden</Text>
              )}
            </View>

            <View style={styles.changePasswordButtons}>
              <TouchableOpacity
                style={styles.changePasswordCancelButton}
                onPress={() => {
                  setShowChangePasswordModal(false);
                  setCurrentPassword('');
                  setNewPassword('');
                  setNewPasswordConfirm('');
                }}
              >
                <Text style={styles.changePasswordCancelText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.changePasswordSaveButton,
                  (!currentPassword || !newPassword || !newPasswordConfirm || newPassword !== newPasswordConfirm) && styles.changePasswordSaveButtonDisabled
                ]}
                onPress={handleChangePassword}
                disabled={passwordChangeLoading || !currentPassword || !newPassword || !newPasswordConfirm || newPassword !== newPasswordConfirm}
              >
                {passwordChangeLoading ? (
                  <ActivityIndicator color="#FFFFFF" size="small" />
                ) : (
                  <>
                    <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                    <Text style={styles.changePasswordSaveText}>Guardar</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      )}

      {/* License Alerts Modal */}
      {showAlertsModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.alertsModal}>
            {/* Alerts Header */}
            <View style={styles.alertsModalHeader}>
              <View style={styles.alertsModalTitleRow}>
                <Ionicons name="notifications" size={24} color="#F59E0B" />
                <Text style={styles.alertsModalTitle}>Mis Alertas</Text>
              </View>
              <View style={styles.alertsModalActions}>
                {alertsUnreadCount > 0 && (
                  <TouchableOpacity 
                    style={styles.markAllReadButton}
                    onPress={markAllAlertsRead}
                  >
                    <Text style={styles.markAllReadText}>Marcar todo leído</Text>
                  </TouchableOpacity>
                )}
                <TouchableOpacity onPress={() => setShowAlertsModal(false)}>
                  <Ionicons name="close" size={24} color="#FFFFFF" />
                </TouchableOpacity>
              </View>
            </View>

            {/* Create Alert Button */}
            <TouchableOpacity
              style={styles.createAlertButton}
              onPress={() => setShowCreateAlertModal(true)}
            >
              <Ionicons name="add-circle" size={20} color="#FFFFFF" />
              <Text style={styles.createAlertButtonText}>Enviar Alerta</Text>
            </TouchableOpacity>

            {/* Alerts List */}
            <ScrollView style={styles.alertsListContainer}>
              {alertLoading ? (
                <View style={styles.alertsLoadingContainer}>
                  <ActivityIndicator size="large" color="#F59E0B" />
                </View>
              ) : licenseAlerts.length === 0 ? (
                <View style={styles.alertsEmptyContainer}>
                  <Ionicons name="checkmark-circle-outline" size={64} color="#4B5563" />
                  <Text style={styles.alertsEmptyText}>No tienes alertas</Text>
                  <Text style={styles.alertsEmptySubtext}>Las alertas que te envíen aparecerán aquí</Text>
                </View>
              ) : (
                licenseAlerts.map((alert) => {
                  const typeInfo = getAlertTypeDisplay(alert.alert_type);
                  return (
                    <TouchableOpacity
                      key={alert.id}
                      style={[
                        styles.alertCard,
                        !alert.is_read && styles.alertCardUnread
                      ]}
                      onPress={() => !alert.is_read && markAlertRead(alert.id)}
                    >
                      <View style={styles.alertCardHeader}>
                        <View style={[styles.alertTypeBadge, { backgroundColor: typeInfo.color }]}>
                          <Ionicons name={typeInfo.icon as any} size={14} color="#FFFFFF" />
                          <Text style={styles.alertTypeBadgeText}>{typeInfo.label}</Text>
                        </View>
                        <TouchableOpacity
                          style={styles.deleteAlertButton}
                          onPress={() => deleteLicenseAlert(alert.id)}
                        >
                          <Ionicons name="trash-outline" size={16} color="#EF4444" />
                        </TouchableOpacity>
                      </View>
                      
                      <Text style={styles.alertMessage}>{alert.message}</Text>
                      
                      <View style={styles.alertSenderInfo}>
                        <Text style={styles.alertSenderText}>
                          De: {alert.sender_full_name} (Licencia: {alert.sender_license})
                        </Text>
                        <Text style={styles.alertTimeText}>
                          {new Date(alert.created_at).toLocaleString('es-ES', {
                            day: '2-digit',
                            month: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit'
                          })}
                        </Text>
                      </View>
                      
                      {!alert.is_read && (
                        <View style={styles.unreadBadge}>
                          <Text style={styles.unreadBadgeText}>NUEVA</Text>
                        </View>
                      )}
                    </TouchableOpacity>
                  );
                })
              )}
            </ScrollView>
          </View>
        </View>
      )}

      {/* Create Alert Modal */}
      {showCreateAlertModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.createAlertModal}>
            <View style={styles.createAlertHeader}>
              <Ionicons name="send" size={40} color="#F59E0B" />
              <Text style={styles.createAlertTitle}>Enviar Alerta</Text>
              <Text style={styles.createAlertSubtitle}>Envía una alerta a otro taxista</Text>
            </View>

            <View style={styles.createAlertForm}>
              <View style={styles.createAlertInputGroup}>
                <Text style={styles.createAlertLabel}>📝 Buscar por número de licencia</Text>
                <View style={styles.licenseSearchContainer}>
                  <TextInput
                    style={[
                      styles.createAlertInput,
                      selectedRecipient && styles.licenseInputSelected
                    ]}
                    placeholder="Escribe el número de licencia..."
                    placeholderTextColor="#6B7280"
                    value={alertTargetLicense}
                    onChangeText={handleLicenseInputChange}
                    keyboardType="numeric"
                    maxLength={20}
                  />
                  {searchingLicense && (
                    <ActivityIndicator size="small" color="#F59E0B" style={styles.licenseSearchSpinner} />
                  )}
                </View>
                
                {/* Selected recipient indicator */}
                {selectedRecipient && (
                  <View style={styles.selectedRecipientBadge}>
                    <Ionicons name="checkmark-circle" size={16} color="#10B981" />
                    <Text style={styles.selectedRecipientText}>
                      {selectedRecipient.full_name} (Licencia: {selectedRecipient.license_number})
                    </Text>
                    <TouchableOpacity onPress={() => {
                      setSelectedRecipient(null);
                      setAlertTargetLicense('');
                    }}>
                      <Ionicons name="close-circle" size={18} color="#EF4444" />
                    </TouchableOpacity>
                  </View>
                )}
                
                {/* Suggestions list */}
                {licenseSuggestions.length > 0 && !selectedRecipient && (
                  <View style={styles.licenseSuggestionsContainer}>
                    {licenseSuggestions.map((suggestion) => (
                      <TouchableOpacity
                        key={suggestion.license_number}
                        style={styles.licenseSuggestionItem}
                        onPress={() => selectRecipient(suggestion)}
                      >
                        <Ionicons name="person" size={18} color="#F59E0B" />
                        <View style={styles.suggestionInfo}>
                          <Text style={styles.suggestionName}>{suggestion.full_name}</Text>
                          <Text style={styles.suggestionLicense}>Licencia: {suggestion.license_number}</Text>
                        </View>
                      </TouchableOpacity>
                    ))}
                  </View>
                )}
                
                {/* No results message */}
                {alertTargetLicense.length > 0 && 
                 licenseSuggestions.length === 0 && 
                 !selectedRecipient && 
                 !searchingLicense && (
                  <View style={styles.noSuggestionsContainer}>
                    <Ionicons name="search" size={20} color="#6B7280" />
                    <Text style={styles.noSuggestionsText}>
                      No se encontró ningún taxista con esa licencia
                    </Text>
                  </View>
                )}
              </View>

              <View style={styles.createAlertInputGroup}>
                <Text style={styles.createAlertLabel}>🏷️ Tipo de alerta</Text>
                <View style={styles.alertTypeSelector}>
                  <TouchableOpacity
                    style={[
                      styles.alertTypeOption,
                      alertType === 'lost_item' && styles.alertTypeOptionActiveLost
                    ]}
                    onPress={() => setAlertType('lost_item')}
                  >
                    <Ionicons name="cube-outline" size={18} color={alertType === 'lost_item' ? '#FFFFFF' : '#F59E0B'} />
                    <Text style={[
                      styles.alertTypeOptionText,
                      alertType === 'lost_item' && styles.alertTypeOptionTextActive
                    ]}>Objeto perdido</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[
                      styles.alertTypeOption,
                      alertType === 'general' && styles.alertTypeOptionActiveGeneral
                    ]}
                    onPress={() => setAlertType('general')}
                  >
                    <Ionicons name="information-circle-outline" size={18} color={alertType === 'general' ? '#FFFFFF' : '#6366F1'} />
                    <Text style={[
                      styles.alertTypeOptionText,
                      alertType === 'general' && styles.alertTypeOptionTextActive
                    ]}>Aviso</Text>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={styles.createAlertInputGroup}>
                <Text style={styles.createAlertLabel}>💬 Mensaje</Text>
                <TextInput
                  style={[styles.createAlertInput, styles.createAlertTextArea]}
                  placeholder="Describe el objeto perdido o el aviso..."
                  placeholderTextColor="#6B7280"
                  value={alertMessage}
                  onChangeText={setAlertMessage}
                  multiline
                  numberOfLines={4}
                  maxLength={500}
                />
              </View>
            </View>

            <View style={styles.createAlertButtons}>
              <TouchableOpacity
                style={styles.createAlertCancelButton}
                onPress={() => {
                  setShowCreateAlertModal(false);
                  setAlertTargetLicense('');
                  setAlertMessage('');
                  setAlertType('lost_item');
                  setSelectedRecipient(null);
                  setLicenseSuggestions([]);
                }}
              >
                <Text style={styles.createAlertCancelButtonText}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.createAlertSendButton,
                  (!selectedRecipient || !alertMessage.trim()) && styles.createAlertSendButtonDisabled
                ]}
                onPress={sendLicenseAlert}
                disabled={alertLoading || !selectedRecipient || !alertMessage.trim()}
              >
                {alertLoading ? (
                  <ActivityIndicator size="small" color="#FFFFFF" />
                ) : (
                  <>
                    <Ionicons name="send" size={18} color="#FFFFFF" />
                    <Text style={styles.createAlertSendButtonText}>Enviar</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      )}

      {/* Chat Modal */}
      {showChatModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.chatModal}>
            {/* Chat Header */}
            <View style={styles.chatHeader}>
              <Text style={styles.chatTitle}>💬 Chat</Text>
              <TouchableOpacity onPress={() => setShowChatModal(false)}>
                <Ionicons name="close" size={24} color="#FFFFFF" />
              </TouchableOpacity>
            </View>

            {/* Channel Tabs */}
            <View style={styles.chatChannelTabs}>
              {chatChannels.map((channel) => (
                <TouchableOpacity
                  key={channel.id}
                  style={[
                    styles.chatChannelTab,
                    activeChannel === channel.id && styles.chatChannelTabActive
                  ]}
                  onPress={() => switchChannel(channel.id)}
                >
                  <Ionicons 
                    name={getChannelIcon(channel.icon) as any}
                    size={16} 
                    color={activeChannel === channel.id ? '#FFFFFF' : '#94A3B8'} 
                  />
                  <Text style={[
                    styles.chatChannelTabText,
                    activeChannel === channel.id && styles.chatChannelTabTextActive
                  ]}>
                    {channel.name}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Messages Area */}
            <ScrollView 
              style={styles.chatMessagesContainer}
              contentContainerStyle={styles.chatMessagesContent}
            >
              {chatLoading ? (
                <View style={styles.chatLoadingContainer}>
                  <ActivityIndicator size="large" color="#6366F1" />
                </View>
              ) : chatMessages.length === 0 ? (
                <View style={styles.chatEmptyContainer}>
                  <Ionicons name="chatbubble-ellipses-outline" size={48} color="#4B5563" />
                  <Text style={styles.chatEmptyText}>No hay mensajes aún</Text>
                  <Text style={styles.chatEmptySubtext}>¡Sé el primero en escribir!</Text>
                </View>
              ) : (
                chatMessages.map((msg) => (
                  <View 
                    key={msg.id} 
                    style={[
                      styles.chatMessage,
                      msg.user_id === currentUser?.id && styles.chatMessageOwn
                    ]}
                  >
                    <View style={styles.chatMessageHeader}>
                      <Text style={styles.chatMessageUsername}>
                        {msg.full_name || msg.username}
                      </Text>
                      <View style={styles.chatMessageHeaderRight}>
                        <Text style={styles.chatMessageTime}>
                          {new Date(msg.created_at).toLocaleTimeString('es-ES', { 
                            hour: '2-digit', 
                            minute: '2-digit' 
                          })}
                        </Text>
                        {/* Action buttons for mods/admins */}
                        {canDeleteMessages() && msg.user_id !== currentUser?.id && (
                          <TouchableOpacity
                            style={styles.chatBlockButton}
                            onPress={() => blockUserForMessage(msg.id, msg.username)}
                          >
                            <Ionicons name="ban" size={14} color="#F59E0B" />
                          </TouchableOpacity>
                        )}
                        {canDeleteMessages() && (
                          <TouchableOpacity
                            style={styles.chatDeleteButton}
                            onPress={() => deleteChatMessage(msg.id)}
                          >
                            <Ionicons name="trash-outline" size={14} color="#EF4444" />
                          </TouchableOpacity>
                        )}
                      </View>
                    </View>
                    <Text style={styles.chatMessageText}>{msg.message}</Text>
                  </View>
                ))
              )}
            </ScrollView>

            {/* Input Area */}
            {canWriteChat ? (
              <View style={styles.chatInputContainer}>
                <TextInput
                  style={styles.chatInput}
                  placeholder="Escribe un mensaje..."
                  placeholderTextColor="#6B7280"
                  value={chatMessage}
                  onChangeText={setChatMessage}
                  multiline
                  maxLength={1000}
                />
                <TouchableOpacity
                  style={[
                    styles.chatSendButton,
                    !chatMessage.trim() && styles.chatSendButtonDisabled
                  ]}
                  onPress={sendChatMessage}
                  disabled={!chatMessage.trim()}
                >
                  <Ionicons name="send" size={20} color="#FFFFFF" />
                </TouchableOpacity>
              </View>
            ) : (
              <View style={styles.chatReadOnlyBanner}>
                <Ionicons name="lock-closed" size={16} color="#9CA3AF" />
                <Text style={styles.chatReadOnlyText}>
                  Solo moderadores pueden escribir en este canal
                </Text>
              </View>
            )}
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

      {/* Add Event Modal */}
      {showAddEventModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.addEventModal}>
            <View style={styles.addEventHeader}>
              <Ionicons name="calendar" size={48} color="#EC4899" />
              <Text style={styles.addEventTitle}>Nuevo Evento</Text>
              <Text style={styles.addEventSubtitle}>Comparte información con tus compañeros</Text>
            </View>
            
            <View style={styles.addEventForm}>
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>📍 Ubicación</Text>
                <TextInput
                  style={styles.addEventInput}
                  placeholder="Ej: Gran Vía, Puerta del Sol..."
                  placeholderTextColor="#6B7280"
                  value={newEventLocation}
                  onChangeText={setNewEventLocation}
                  maxLength={100}
                />
              </View>
              
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>📝 Descripción</Text>
                <TextInput
                  style={[styles.addEventInput, styles.addEventTextArea]}
                  placeholder="¿Qué está pasando? Ej: Mucho tráfico, obras, evento especial..."
                  placeholderTextColor="#6B7280"
                  value={newEventDescription}
                  onChangeText={setNewEventDescription}
                  multiline
                  numberOfLines={4}
                  maxLength={500}
                />
              </View>
              
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>🕐 Hora (HH:MM)</Text>
                <View style={styles.addEventTimeInput}>
                  <TextInput
                    style={styles.addEventTimeTextInput}
                    placeholder="Ej: 14:30"
                    placeholderTextColor="#6B7280"
                    value={newEventTime}
                    onChangeText={(text) => {
                      // Auto format time input
                      let cleaned = text.replace(/[^\d]/g, '');
                      if (cleaned.length >= 3) {
                        cleaned = cleaned.slice(0, 2) + ':' + cleaned.slice(2, 4);
                      }
                      setNewEventTime(cleaned);
                    }}
                    keyboardType="numeric"
                    maxLength={5}
                  />
                  <Ionicons name="time-outline" size={22} color="#6B7280" />
                </View>
              </View>
              
              <View style={styles.addEventButtons}>
                <TouchableOpacity
                  style={styles.addEventCancelButton}
                  onPress={() => {
                    setShowAddEventModal(false);
                    setNewEventLocation('');
                    setNewEventDescription('');
                    setNewEventTime('');
                  }}
                >
                  <Text style={styles.addEventCancelButtonText}>Cancelar</Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[
                    styles.addEventSubmitButton,
                    (!newEventLocation.trim() || !newEventDescription.trim() || !newEventTime.trim()) && styles.addEventSubmitButtonDisabled
                  ]}
                  onPress={createEvent}
                  disabled={eventLoading || !newEventLocation.trim() || !newEventDescription.trim() || !newEventTime.trim()}
                >
                  {eventLoading ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                      <Text style={styles.addEventSubmitButtonText}>Publicar</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </View>
      )}

      {/* Create User Modal (Admin) */}
      {showCreateUserModal && (
        <View style={styles.modalOverlay}>
          <View style={styles.addEventModal}>
            <View style={styles.addEventHeader}>
              <Ionicons name="person-add" size={48} color="#EF4444" />
              <Text style={styles.addEventTitle}>Crear Usuario</Text>
              <Text style={styles.addEventSubtitle}>Añade un nuevo usuario al sistema</Text>
            </View>
            
            <View style={styles.addEventForm}>
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>👤 Nombre de usuario</Text>
                <TextInput
                  style={styles.addEventInput}
                  placeholder="Ej: taxista1"
                  placeholderTextColor="#6B7280"
                  value={newUserUsername}
                  onChangeText={setNewUserUsername}
                  autoCapitalize="none"
                  maxLength={50}
                />
              </View>
              
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>🔒 Contraseña</Text>
                <TextInput
                  style={styles.addEventInput}
                  placeholder="Contraseña"
                  placeholderTextColor="#6B7280"
                  value={newUserPassword}
                  onChangeText={setNewUserPassword}
                  secureTextEntry
                  maxLength={100}
                />
              </View>

              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>📞 Teléfono (opcional)</Text>
                <TextInput
                  style={styles.addEventInput}
                  placeholder="Ej: 600123456"
                  placeholderTextColor="#6B7280"
                  value={newUserPhone}
                  onChangeText={setNewUserPhone}
                  keyboardType="phone-pad"
                  maxLength={20}
                />
              </View>
              
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>🏷️ Rol</Text>
                <View style={styles.roleSelector}>
                  <TouchableOpacity
                    style={[styles.roleOption, newUserRole === 'user' && styles.roleOptionActive]}
                    onPress={() => setNewUserRole('user')}
                  >
                    <Text style={[styles.roleOptionText, newUserRole === 'user' && styles.roleOptionTextActive]}>Usuario</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.roleOption, newUserRole === 'moderator' && styles.roleOptionActiveMod]}
                    onPress={() => setNewUserRole('moderator')}
                  >
                    <Text style={[styles.roleOptionText, newUserRole === 'moderator' && styles.roleOptionTextActive]}>Moderador</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.roleOption, newUserRole === 'admin' && styles.roleOptionActiveAdmin]}
                    onPress={() => setNewUserRole('admin')}
                  >
                    <Text style={[styles.roleOptionText, newUserRole === 'admin' && styles.roleOptionTextActive]}>Admin</Text>
                  </TouchableOpacity>
                </View>
              </View>
              
              <View style={styles.addEventButtons}>
                <TouchableOpacity
                  style={styles.addEventCancelButton}
                  onPress={() => {
                    setShowCreateUserModal(false);
                    setNewUserUsername('');
                    setNewUserPassword('');
                    setNewUserRole('user');
                    setNewUserPhone('');
                  }}
                >
                  <Text style={styles.addEventCancelButtonText}>Cancelar</Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={[
                    styles.adminSubmitButton,
                    (!newUserUsername.trim() || !newUserPassword.trim()) && styles.addEventSubmitButtonDisabled
                  ]}
                  onPress={createUser}
                  disabled={adminLoading || !newUserUsername.trim() || !newUserPassword.trim()}
                >
                  {adminLoading ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                      <Text style={styles.addEventSubmitButtonText}>Crear</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </View>
      )}

      {/* Edit User Role Modal (Admin) */}
      {showEditUserModal && editingUser && (
        <View style={styles.modalOverlay}>
          <View style={styles.addEventModal}>
            <View style={styles.addEventHeader}>
              <Ionicons name="create" size={48} color="#3B82F6" />
              <Text style={styles.addEventTitle}>Cambiar Rol</Text>
              <Text style={styles.addEventSubtitle}>Usuario: {editingUser.username}</Text>
            </View>
            
            <View style={styles.addEventForm}>
              <View style={styles.addEventInputGroup}>
                <Text style={styles.addEventLabel}>🏷️ Nuevo Rol</Text>
                <View style={styles.roleSelector}>
                  <TouchableOpacity
                    style={[styles.roleOption, editingUser.role === 'user' && styles.roleOptionActive]}
                    onPress={() => setEditingUser({...editingUser, role: 'user'})}
                  >
                    <Text style={[styles.roleOptionText, editingUser.role === 'user' && styles.roleOptionTextActive]}>Usuario</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.roleOption, editingUser.role === 'moderator' && styles.roleOptionActiveMod]}
                    onPress={() => setEditingUser({...editingUser, role: 'moderator'})}
                  >
                    <Text style={[styles.roleOptionText, editingUser.role === 'moderator' && styles.roleOptionTextActive]}>Moderador</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.roleOption, editingUser.role === 'admin' && styles.roleOptionActiveAdmin]}
                    onPress={() => setEditingUser({...editingUser, role: 'admin'})}
                  >
                    <Text style={[styles.roleOptionText, editingUser.role === 'admin' && styles.roleOptionTextActive]}>Admin</Text>
                  </TouchableOpacity>
                </View>
              </View>
              
              <View style={styles.addEventButtons}>
                <TouchableOpacity
                  style={styles.addEventCancelButton}
                  onPress={() => {
                    setShowEditUserModal(false);
                    setEditingUser(null);
                  }}
                >
                  <Text style={styles.addEventCancelButtonText}>Cancelar</Text>
                </TouchableOpacity>
                
                <TouchableOpacity
                  style={styles.adminSubmitButton}
                  onPress={() => updateUserRole(editingUser.id, editingUser.role)}
                  disabled={adminLoading}
                >
                  {adminLoading ? (
                    <ActivityIndicator size="small" color="#FFFFFF" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                      <Text style={styles.addEventSubmitButtonText}>Guardar</Text>
                    </>
                  )}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </View>
      )}

      {/* Time Range Selector Modal */}
      {showTimeRangeDropdown && (
        <Modal
          visible={showTimeRangeDropdown}
          transparent={true}
          animationType="fade"
          onRequestClose={() => setShowTimeRangeDropdown(false)}
        >
          <TouchableOpacity 
            style={styles.modalOverlay}
            activeOpacity={1}
            onPress={() => setShowTimeRangeDropdown(false)}
          >
            <TouchableOpacity 
              activeOpacity={1} 
              style={styles.timeRangeModal}
              onPress={(e) => e.stopPropagation()}
            >
              <View style={styles.timeRangeModalHeader}>
                <Ionicons name="time" size={24} color="#F59E0B" />
                <Text style={styles.timeRangeModalTitle}>Seleccionar Franja Horaria</Text>
              </View>
              <Text style={styles.timeRangeModalSubtitle}>
                Elige un rango de tiempo para ver datos históricos o predicciones
              </Text>
              
              <ScrollView 
                style={styles.timeRangeModalScroll}
                showsVerticalScrollIndicator={true}
              >
                {/* Section: Now */}
                <View style={styles.timeRangeSectionHeader}>
                  <Ionicons name="radio-button-on" size={14} color="#F59E0B" />
                  <Text style={styles.timeRangeSectionTitle}>Tiempo Real</Text>
                </View>
                
                {timeRangeOptions.filter(o => o.id === 'now').map((option) => (
                  <TouchableOpacity
                    key={option.id}
                    style={[
                      styles.timeRangeModalOption,
                      selectedTimeRange === option.id && styles.timeRangeModalOptionSelected
                    ]}
                    onPress={() => {
                      setSelectedTimeRange(option.id);
                      setShowTimeRangeDropdown(false);
                    }}
                  >
                    <View style={styles.timeRangeModalOptionContent}>
                      <Ionicons name="radio-button-on" size={18} color="#F59E0B" />
                      <Text style={[
                        styles.timeRangeModalOptionText,
                        selectedTimeRange === option.id && styles.timeRangeModalOptionTextSelected
                      ]}>
                        {option.label}
                      </Text>
                    </View>
                    {selectedTimeRange === option.id && (
                      <Ionicons name="checkmark-circle" size={20} color="#10B981" />
                    )}
                  </TouchableOpacity>
                ))}
                
                {/* Section: Past */}
                <View style={styles.timeRangeSectionHeader}>
                  <Ionicons name="arrow-back-circle-outline" size={14} color="#6B7280" />
                  <Text style={styles.timeRangeSectionTitle}>Pasado (Historial)</Text>
                </View>
                
                {timeRangeOptions.filter(o => o.id.startsWith('past-')).map((option) => (
                  <TouchableOpacity
                    key={option.id}
                    style={[
                      styles.timeRangeModalOption,
                      selectedTimeRange === option.id && styles.timeRangeModalOptionSelected
                    ]}
                    onPress={() => {
                      setSelectedTimeRange(option.id);
                      setShowTimeRangeDropdown(false);
                    }}
                  >
                    <View style={styles.timeRangeModalOptionContent}>
                      <Ionicons name="arrow-back-circle-outline" size={18} color="#6B7280" />
                      <Text style={[
                        styles.timeRangeModalOptionText,
                        selectedTimeRange === option.id && styles.timeRangeModalOptionTextSelected
                      ]}>
                        {option.label}
                      </Text>
                    </View>
                    {selectedTimeRange === option.id && (
                      <Ionicons name="checkmark-circle" size={20} color="#10B981" />
                    )}
                  </TouchableOpacity>
                ))}
                
                {/* Section: Future */}
                <View style={styles.timeRangeSectionHeader}>
                  <Ionicons name="arrow-forward-circle-outline" size={14} color="#3B82F6" />
                  <Text style={styles.timeRangeSectionTitle}>Futuro (Predicciones)</Text>
                </View>
                
                {timeRangeOptions.filter(o => o.id.startsWith('future-')).map((option) => (
                  <TouchableOpacity
                    key={option.id}
                    style={[
                      styles.timeRangeModalOption,
                      selectedTimeRange === option.id && styles.timeRangeModalOptionSelected
                    ]}
                    onPress={() => {
                      setSelectedTimeRange(option.id);
                      setShowTimeRangeDropdown(false);
                    }}
                  >
                    <View style={styles.timeRangeModalOptionContent}>
                      <Ionicons name="arrow-forward-circle-outline" size={18} color="#3B82F6" />
                      <Text style={[
                        styles.timeRangeModalOptionText,
                        selectedTimeRange === option.id && styles.timeRangeModalOptionTextSelected
                      ]}>
                        {option.label}
                      </Text>
                    </View>
                    {selectedTimeRange === option.id && (
                      <Ionicons name="checkmark-circle" size={20} color="#10B981" />
                    )}
                  </TouchableOpacity>
                ))}
              </ScrollView>
              
              <TouchableOpacity
                style={styles.timeRangeModalCloseButton}
                onPress={() => setShowTimeRangeDropdown(false)}
              >
                <Text style={styles.timeRangeModalCloseButtonText}>Cerrar</Text>
              </TouchableOpacity>
            </TouchableOpacity>
          </TouchableOpacity>
        </Modal>
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
          <View style={styles.destinationModal}>
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
  // NEW: Dropdown styles
  dropdownsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 8,
  },
  dropdownSelector: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    gap: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  dropdownSelectorHidden: {
    opacity: 0.3,
  },
  dropdownSelectorText: {
    flex: 1,
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '500',
  },
  chatButtonCompact: {
    backgroundColor: '#6366F1',
    padding: 10,
    borderRadius: 10,
  },
  sosButtonCompact: {
    backgroundColor: '#1E293B',
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#374151',
  },
  timeRangeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingBottom: 12,
    gap: 8,
  },
  timeWindowButtonsInline: {
    flexDirection: 'row',
    backgroundColor: '#1E293B',
    borderRadius: 10,
    padding: 4,
    gap: 4,
  },
  timeWindowButtonSmall: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
  },
  activeTimeWindowSmall: {
    backgroundColor: '#6366F1',
  },
  timeWindowTextSmall: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
  },
  activeTimeWindowTextSmall: {
    color: '#FFFFFF',
  },
  timeRangeDropdownFull: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    gap: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  timeRangeDropdownFullActive: {
    borderColor: '#10B981',
    backgroundColor: '#10B98115',
  },
  timeRangeDropdownTextFull: {
    flex: 1,
    color: '#94A3B8',
    fontSize: 14,
    fontWeight: '500',
  },
  timeRangeDropdownTextFullActive: {
    color: '#10B981',
  },
  dropdownOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  dropdownMenu: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 8,
    width: '100%',
    maxWidth: 320,
    borderWidth: 1,
    borderColor: '#334155',
  },
  dropdownMenuTitle: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
    marginBottom: 4,
  },
  dropdownMenuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderRadius: 10,
    gap: 12,
  },
  dropdownMenuItemActive: {
    backgroundColor: '#6366F120',
  },
  dropdownMenuItemText: {
    flex: 1,
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '500',
  },
  dropdownMenuItemTextActive: {
    color: '#6366F1',
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
  activeTabEvents: {
    backgroundColor: '#EC4899',
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
  // Station/Terminal Alert Card Styles
  stationAlertCard: {
    borderColor: '#EF4444',
    backgroundColor: '#1E293B',
  },
  alertBadgesContainer: {
    position: 'absolute',
    top: -12,
    left: 20,
    right: 80,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    zIndex: 10,
  },
  alertBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    gap: 5,
  },
  alertBadgeSinTaxis: {
    backgroundColor: '#EF4444',
  },
  alertBadgeBarandilla: {
    backgroundColor: '#F59E0B',
  },
  alertBadgeText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: 'bold',
  },
  alertBadgeTime: {
    color: '#FFFFFF',
    fontSize: 9,
    opacity: 0.8,
  },
  alertButtonsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 10,
    marginTop: 12,
    marginBottom: 8,
  },
  alertButton: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    gap: 6,
  },
  alertButtonSinTaxis: {
    backgroundColor: '#DC262680',
    borderWidth: 1,
    borderColor: '#EF4444',
  },
  alertButtonBarandilla: {
    backgroundColor: '#D9770680',
    borderWidth: 1,
    borderColor: '#F59E0B',
  },
  alertButtonText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: '600',
  },
  // Close alert button styles
  closeAlertButtonsContainer: {
    flexDirection: 'column',
    gap: 8,
    marginTop: 10,
  },
  closeAlertButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 10,
    gap: 8,
  },
  closeAlertButtonSinTaxis: {
    backgroundColor: '#DC2626',
  },
  closeAlertButtonBarandilla: {
    backgroundColor: '#D97706',
  },
  closeAlertButtonDisabled: {
    opacity: 0.5,
  },
  closeAlertButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
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
  // New styles for XA - YP format
  arrivalScoreRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'center',
  },
  arrivalNumberSmall: {
    fontSize: 36,
    fontWeight: 'bold',
  },
  arrivalSuffix: {
    fontSize: 16,
    fontWeight: '600',
    opacity: 0.8,
  },
  arrivalDivider: {
    fontSize: 24,
    color: '#64748B',
    marginHorizontal: 8,
  },
  scoreContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#6366F115',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginTop: 8,
    gap: 6,
  },
  scoreText: {
    color: '#6366F1',
    fontSize: 14,
    fontWeight: '600',
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
  // Alert styles for hottest cards in Street tab
  hottestCardWithAlert: {
    borderColor: '#EF4444',
    borderLeftColor: '#EF4444',
  },
  hottestAlertBadgesContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 10,
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
  // Time Range Dropdown styles
  timeRangeContainer: {
    position: 'relative',
    zIndex: 100,
  },
  timeRangeDropdownButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#1E293B',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#334155',
  },
  timeRangeDropdownButtonActive: {
    borderColor: '#10B981',
    backgroundColor: '#064E3B',
  },
  timeRangeDropdownText: {
    color: '#E2E8F0',
    fontSize: 13,
    fontWeight: '500',
  },
  timeRangeDropdownTextActive: {
    color: '#10B981',
  },
  timeRangeDropdownMenu: {
    position: 'absolute',
    top: '100%',
    right: 0,
    marginTop: 6,
    backgroundColor: '#1E293B',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#334155',
    width: 200,
    maxHeight: 300,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 10,
    zIndex: 1000,
  },
  timeRangeDropdownScroll: {
    maxHeight: 290,
  },
  timeRangeOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  timeRangeOptionSelected: {
    backgroundColor: '#064E3B',
  },
  timeRangeOptionNow: {
    backgroundColor: '#1E3A5F',
  },
  timeRangeOptionContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  timeRangeOptionText: {
    color: '#E2E8F0',
    fontSize: 14,
    fontWeight: '500',
  },
  timeRangeOptionTextSelected: {
    color: '#10B981',
    fontWeight: '600',
  },
  timeRangeOptionTextPast: {
    color: '#9CA3AF',
  },
  timeRangeOptionTextFuture: {
    color: '#60A5FA',
  },
  timeRangeOptionTextNow: {
    color: '#F59E0B',
    fontWeight: '600',
  },
  // Time Range Modal styles
  timeRangeModal: {
    backgroundColor: '#1E293B',
    borderRadius: 20,
    padding: 20,
    width: '90%',
    maxWidth: 400,
    maxHeight: '80%',
  },
  timeRangeModalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    marginBottom: 8,
  },
  timeRangeModalTitle: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: '700',
  },
  timeRangeModalSubtitle: {
    color: '#9CA3AF',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 16,
  },
  timeRangeModalScroll: {
    maxHeight: 400,
  },
  timeRangeSectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 4,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
    marginTop: 8,
  },
  timeRangeSectionTitle: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  timeRangeModalOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    paddingHorizontal: 12,
    borderRadius: 10,
    marginVertical: 2,
  },
  timeRangeModalOptionSelected: {
    backgroundColor: '#064E3B',
  },
  timeRangeModalOptionContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  timeRangeModalOptionText: {
    color: '#E2E8F0',
    fontSize: 15,
    fontWeight: '500',
  },
  timeRangeModalOptionTextSelected: {
    color: '#10B981',
    fontWeight: '600',
  },
  timeRangeModalCloseButton: {
    backgroundColor: '#374151',
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 16,
  },
  timeRangeModalCloseButtonText: {
    color: '#E2E8F0',
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
  // Events Tab Styles
  eventsContainer: {
    flex: 1,
    paddingHorizontal: 15,
    paddingBottom: 20,
  },
  addEventButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#EC4899',
    borderRadius: 12,
    paddingVertical: 14,
    marginBottom: 20,
    gap: 8,
    shadowColor: '#EC4899',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 5,
  },
  addEventButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  noEventsContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 60,
  },
  noEventsText: {
    color: '#9CA3AF',
    fontSize: 18,
    fontWeight: '600',
    marginTop: 16,
  },
  noEventsSubtext: {
    color: '#6B7280',
    fontSize: 14,
    marginTop: 8,
  },
  eventCard: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#334155',
  },
  eventHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  eventTimeContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  eventTime: {
    color: '#6366F1',
    fontSize: 16,
    fontWeight: '700',
  },
  eventUsername: {
    color: '#9CA3AF',
    fontSize: 13,
  },
  eventBody: {
    marginBottom: 12,
  },
  eventLocationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 8,
  },
  eventLocation: {
    color: '#F59E0B',
    fontSize: 15,
    fontWeight: '600',
    flex: 1,
  },
  eventDescription: {
    color: '#E2E8F0',
    fontSize: 14,
    lineHeight: 20,
  },
  eventFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#334155',
  },
  eventVotes: {
    flexDirection: 'row',
    gap: 16,
  },
  voteButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#0F172A',
  },
  voteButtonActive: {
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
  },
  voteButtonActiveDislike: {
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
  },
  voteCount: {
    color: '#9CA3AF',
    fontSize: 14,
    fontWeight: '600',
  },
  voteCountActive: {
    color: '#10B981',
  },
  voteCountActiveDislike: {
    color: '#EF4444',
  },
  deleteEventButton: {
    padding: 12,
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderRadius: 8,
    marginLeft: 8,
  },
  // Add Event Modal
  addEventModal: {
    backgroundColor: '#1E293B',
    borderRadius: 24,
    padding: 24,
    width: '90%',
    maxWidth: 400,
  },
  addEventHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  addEventTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '700',
    marginTop: 12,
  },
  addEventSubtitle: {
    color: '#9CA3AF',
    fontSize: 14,
    marginTop: 4,
  },
  addEventForm: {
    gap: 16,
  },
  addEventInputGroup: {
    gap: 6,
  },
  addEventLabel: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
    marginLeft: 4,
  },
  addEventInput: {
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 14,
    color: '#FFFFFF',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  addEventTextArea: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  addEventTimeInput: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0F172A',
    borderRadius: 12,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: '#334155',
  },
  addEventTimeTextInput: {
    flex: 1,
    padding: 14,
    color: '#FFFFFF',
    fontSize: 15,
  },
  addEventButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 8,
  },
  addEventCancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#334155',
    alignItems: 'center',
  },
  addEventCancelButtonText: {
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '600',
  },
  addEventSubmitButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#EC4899',
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  addEventSubmitButtonDisabled: {
    backgroundColor: '#4B5563',
  },
  addEventSubmitButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  // Admin Panel Styles
  activeTabAdmin: {
    backgroundColor: '#EF4444',
  },
  adminContainer: {
    flex: 1,
    paddingHorizontal: 15,
    paddingBottom: 20,
  },
  adminHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  adminHeaderTitle: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  adminTitle: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: '700',
  },
  // Admin Stats Row
  adminStatsRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 16,
  },
  adminStatCard: {
    flex: 1,
    alignItems: 'center',
    padding: 12,
    borderRadius: 12,
    gap: 4,
  },
  adminStatNumber: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: '700',
  },
  adminStatLabel: {
    color: '#94A3B8',
    fontSize: 11,
    fontWeight: '500',
    textAlign: 'center',
  },
  // Admin Search
  adminSearchContainer: {
    marginBottom: 12,
  },
  adminSearchInputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1E293B',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    gap: 10,
    borderWidth: 1,
    borderColor: '#334155',
  },
  adminSearchInput: {
    flex: 1,
    color: '#FFFFFF',
    fontSize: 15,
  },
  // Admin Action Buttons
  adminActionsRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 16,
  },
  adminActionButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#EF4444',
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
    gap: 8,
  },
  adminActionButtonSecondary: {
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#6366F1',
  },
  adminActionButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  // Blocked Users Management Button
  adminBlockedUsersButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#EF4444',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginBottom: 16,
  },
  adminBlockedUsersButtonActive: {
    backgroundColor: '#EF4444',
  },
  adminBlockedUsersButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  adminBlockedUsersButtonText: {
    color: '#EF4444',
    fontSize: 15,
    fontWeight: '600',
  },
  // Blocked Users Section
  blockedUsersSection: {
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: '#374151',
  },
  blockedUsersLoading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    paddingVertical: 20,
  },
  blockedUsersLoadingText: {
    color: '#9CA3AF',
    fontSize: 14,
  },
  blockedUsersStatsRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 16,
  },
  blockedUserStatCard: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 12,
    borderRadius: 8,
  },
  blockedUserStatNumber: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: 'bold',
  },
  blockedUserStatLabel: {
    color: '#9CA3AF',
    fontSize: 11,
    marginTop: 2,
  },
  blockedUsersRefreshButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 8,
    marginBottom: 12,
  },
  blockedUsersRefreshText: {
    color: '#9CA3AF',
    fontSize: 13,
  },
  noBlockedUsers: {
    alignItems: 'center',
    paddingVertical: 30,
  },
  noBlockedUsersText: {
    color: '#6B7280',
    fontSize: 14,
    marginTop: 10,
  },
  blockedUserCard: {
    backgroundColor: '#0F172A',
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#374151',
  },
  blockedUserCardPermanent: {
    borderColor: '#7F1D1D',
    backgroundColor: '#7F1D1D20',
  },
  blockedUserCardTemporary: {
    borderColor: '#F59E0B',
    backgroundColor: '#F59E0B10',
  },
  blockedUserCardExpired: {
    borderColor: '#374151',
    opacity: 0.7,
  },
  blockedUserHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 10,
  },
  blockedUserInfo: {
    flex: 1,
  },
  blockedUserName: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '600',
  },
  blockedUserUsername: {
    color: '#6B7280',
    fontSize: 13,
    marginTop: 2,
  },
  blockedUserLicense: {
    color: '#9CA3AF',
    fontSize: 12,
    marginTop: 4,
  },
  blockedUserStatusBadge: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 20,
    backgroundColor: '#374151',
  },
  blockedStatusPermanent: {
    backgroundColor: '#7F1D1D',
  },
  blockedStatusTemporary: {
    backgroundColor: '#78350F',
  },
  blockedStatusExpired: {
    backgroundColor: '#1F2937',
  },
  blockedUserStatusText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '600',
  },
  blockedUserStats: {
    flexDirection: 'row',
    gap: 16,
    marginBottom: 12,
  },
  blockedUserStatItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  blockedUserStatText: {
    color: '#9CA3AF',
    fontSize: 12,
  },
  // New blocked user styles
  blockReasonBadges: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 4,
    alignItems: 'flex-end',
  },
  blockReasonBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 8,
  },
  blockReasonBadgeText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: '600',
  },
  blockedUserStatsSection: {
    marginBottom: 8,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#374151',
  },
  blockedUserStatsSectionTitle: {
    color: '#9CA3AF',
    fontSize: 11,
    fontWeight: '600',
    marginBottom: 6,
  },
  blockedUserAbuseMessage: {
    color: '#6B7280',
    fontSize: 11,
    fontStyle: 'italic',
    marginTop: 4,
  },
  blockedUserActions: {
    flexDirection: 'row',
    gap: 10,
    paddingTop: 10,
    borderTopWidth: 1,
    borderTopColor: '#374151',
  },
  unblockButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: '#10B98120',
    borderWidth: 1,
    borderColor: '#10B981',
  },
  unblockButtonText: {
    color: '#10B981',
    fontSize: 13,
    fontWeight: '600',
  },
  resetFraudButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: '#F59E0B20',
    borderWidth: 1,
    borderColor: '#F59E0B',
  },
  resetFraudButtonText: {
    color: '#F59E0B',
    fontSize: 13,
    fontWeight: '600',
  },
  blockedUsersLoadButton: {
    alignItems: 'center',
    paddingVertical: 16,
  },
  blockedUsersLoadButtonText: {
    color: '#6366F1',
    fontSize: 14,
    fontWeight: '600',
  },
  // Admin Search Results
  adminSearchResults: {
    marginBottom: 16,
  },
  adminSectionTitle: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 12,
    marginTop: 8,
  },
  adminNoResults: {
    color: '#6B7280',
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: 20,
  },
  // User Avatar with Online Indicator
  userAvatarContainer: {
    position: 'relative',
  },
  onlineIndicator: {
    position: 'absolute',
    bottom: 0,
    right: 0,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#10B981',
    borderWidth: 2,
    borderColor: '#1E293B',
  },
  userLicense: {
    color: '#94A3B8',
    fontSize: 12,
  },
  // Legacy styles kept for compatibility
  addUserButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#EF4444',
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: 10,
    gap: 8,
  },
  addUserButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  userCard: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#334155',
  },
  userCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  userInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  userDetails: {
    gap: 6,
  },
  userName: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  roleBadge: {
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  roleBadgeText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  userActions: {
    flexDirection: 'row',
    gap: 8,
  },
  editUserButton: {
    padding: 8,
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    borderRadius: 8,
  },
  deleteUserButton: {
    padding: 8,
    backgroundColor: 'rgba(239, 68, 68, 0.2)',
    borderRadius: 8,
  },
  userPhone: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#334155',
  },
  userPhoneText: {
    color: '#9CA3AF',
    fontSize: 14,
  },
  roleSelector: {
    flexDirection: 'row',
    gap: 8,
  },
  roleOption: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 8,
    backgroundColor: '#0F172A',
    borderRadius: 10,
    alignItems: 'center',
    borderWidth: 2,
    borderColor: 'transparent',
  },
  roleOptionActive: {
    backgroundColor: 'rgba(107, 114, 128, 0.3)',
    borderColor: '#6B7280',
  },
  roleOptionActiveMod: {
    backgroundColor: 'rgba(245, 158, 11, 0.3)',
    borderColor: '#F59E0B',
  },
  roleOptionActiveAdmin: {
    backgroundColor: 'rgba(239, 68, 68, 0.3)',
    borderColor: '#EF4444',
  },
  roleOptionText: {
    color: '#9CA3AF',
    fontSize: 13,
    fontWeight: '600',
  },
  roleOptionTextActive: {
    color: '#FFFFFF',
  },
  adminSubmitButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#EF4444',
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  // Registration styles
  switchAuthButton: {
    marginTop: 20,
    alignItems: 'center',
  },
  switchAuthText: {
    color: '#94A3B8',
    fontSize: 14,
  },
  switchAuthLink: {
    color: '#6366F1',
    fontWeight: '600',
  },
  registerButton: {
    backgroundColor: '#10B981',
  },
  registerShiftSection: {
    marginTop: 8,
    marginBottom: 8,
  },
  registerShiftLabel: {
    color: '#94A3B8',
    fontSize: 13,
    marginBottom: 10,
    marginLeft: 4,
  },
  registerShiftButtons: {
    flexDirection: 'row',
    gap: 10,
  },
  registerShiftButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 12,
    backgroundColor: '#1E293B',
    borderRadius: 10,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  registerShiftButtonActiveDay: {
    backgroundColor: 'rgba(245, 158, 11, 0.2)',
    borderColor: '#F59E0B',
  },
  registerShiftButtonActiveAll: {
    backgroundColor: 'rgba(99, 102, 241, 0.2)',
    borderColor: '#6366F1',
  },
  registerShiftButtonActiveNight: {
    backgroundColor: 'rgba(139, 92, 246, 0.2)',
    borderColor: '#8B5CF6',
  },
  registerShiftButtonText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
  },
  registerShiftButtonTextActive: {
    color: '#FFFFFF',
  },
  // Profile button in settings
  profileButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1E293B',
    borderRadius: 12,
    padding: 14,
    marginTop: 10,
  },
  profileButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  profileButtonInfo: {
    gap: 2,
  },
  profileButtonName: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  profileButtonLicense: {
    color: '#9CA3AF',
    fontSize: 13,
  },
  // Profile Modal styles
  profileModalScrollContainer: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  profileModal: {
    backgroundColor: '#1E293B',
    borderRadius: 24,
    padding: 24,
    width: '100%',
    maxWidth: 400,
  },
  profileModalHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  profileModalTitle: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: '700',
    marginTop: 12,
  },
  profileModalSubtitle: {
    color: '#9CA3AF',
    fontSize: 14,
    marginTop: 4,
  },
  // Change Password Modal styles
  changePasswordModal: {
    backgroundColor: '#1E293B',
    borderRadius: 24,
    padding: 24,
    width: '90%',
    maxWidth: 400,
  },
  changePasswordHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  changePasswordTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '700',
    marginTop: 12,
  },
  changePasswordSubtitle: {
    color: '#9CA3AF',
    fontSize: 14,
    marginTop: 8,
    textAlign: 'center',
  },
  changePasswordForm: {
    gap: 12,
    marginBottom: 24,
  },
  changePasswordButtons: {
    flexDirection: 'row',
    gap: 12,
  },
  changePasswordCancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#0F172A',
    alignItems: 'center',
  },
  changePasswordCancelText: {
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '600',
  },
  changePasswordSaveButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#10B981',
  },
  changePasswordSaveButtonDisabled: {
    backgroundColor: '#374151',
    opacity: 0.6,
  },
  changePasswordSaveText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  changePasswordButton: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    marginTop: 12,
    borderWidth: 1,
    borderColor: '#F59E0B40',
  },
  passwordMismatchText: {
    color: '#EF4444',
    fontSize: 13,
    textAlign: 'center',
    marginTop: 4,
  },
  profileForm: {
    gap: 16,
  },
  profileInputGroup: {
    gap: 6,
  },
  profileInputLabel: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
    marginLeft: 4,
  },
  profileInput: {
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 14,
    color: '#FFFFFF',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  profileShiftSelector: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 4,
  },
  profileShiftOption: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 12,
    backgroundColor: '#0F172A',
    borderRadius: 10,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  profileShiftOptionActiveDay: {
    backgroundColor: 'rgba(245, 158, 11, 0.2)',
    borderColor: '#F59E0B',
  },
  profileShiftOptionActiveAll: {
    backgroundColor: 'rgba(99, 102, 241, 0.2)',
    borderColor: '#6366F1',
  },
  profileShiftOptionActiveNight: {
    backgroundColor: 'rgba(139, 92, 246, 0.2)',
    borderColor: '#8B5CF6',
  },
  profileShiftOptionText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
  },
  profileShiftOptionTextActive: {
    color: '#FFFFFF',
  },
  profileButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 24,
  },
  profileCancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#334155',
    alignItems: 'center',
  },
  profileCancelButtonText: {
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '600',
  },
  profileSaveButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#6366F1',
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  profileSaveButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  // Chat styles
  chatButton: {
    backgroundColor: '#6366F1',
    borderRadius: 10,
    padding: 10,
    marginRight: 10,
  },
  chatModal: {
    backgroundColor: '#1E293B',
    borderRadius: 20,
    width: '95%',
    maxWidth: 500,
    height: '80%',
    maxHeight: 600,
    overflow: 'hidden',
  },
  chatHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  chatTitle: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: '700',
  },
  chatChannelTabs: {
    flexDirection: 'row',
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  chatChannelTab: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 14,
    borderRadius: 20,
    backgroundColor: '#0F172A',
  },
  chatChannelTabActive: {
    backgroundColor: '#6366F1',
  },
  chatChannelTabText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
  },
  chatChannelTabTextActive: {
    color: '#FFFFFF',
  },
  chatMessagesContainer: {
    flex: 1,
  },
  chatMessagesContent: {
    padding: 16,
    gap: 12,
  },
  chatLoadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 40,
  },
  chatEmptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 40,
  },
  chatEmptyText: {
    color: '#9CA3AF',
    fontSize: 16,
    fontWeight: '600',
    marginTop: 12,
  },
  chatEmptySubtext: {
    color: '#6B7280',
    fontSize: 14,
    marginTop: 4,
  },
  chatMessage: {
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 12,
    maxWidth: '85%',
    alignSelf: 'flex-start',
  },
  chatMessageOwn: {
    backgroundColor: '#4F46E5',
    alignSelf: 'flex-end',
  },
  chatMessageHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
    gap: 12,
  },
  chatMessageHeaderRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  chatMessageUsername: {
    color: '#F59E0B',
    fontSize: 12,
    fontWeight: '700',
  },
  chatMessageTime: {
    color: '#6B7280',
    fontSize: 11,
  },
  chatDeleteButton: {
    padding: 4,
    borderRadius: 4,
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
  },
  chatBlockButton: {
    padding: 4,
    borderRadius: 4,
    backgroundColor: 'rgba(245, 158, 11, 0.1)',
    marginRight: 4,
  },
  chatMessageText: {
    color: '#E2E8F0',
    fontSize: 14,
    lineHeight: 20,
  },
  chatInputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: 12,
    gap: 10,
    borderTopWidth: 1,
    borderTopColor: '#334155',
  },
  chatInput: {
    flex: 1,
    backgroundColor: '#0F172A',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: '#FFFFFF',
    fontSize: 14,
    maxHeight: 100,
    borderWidth: 1,
    borderColor: '#334155',
  },
  chatSendButton: {
    backgroundColor: '#6366F1',
    borderRadius: 20,
    padding: 12,
  },
  chatSendButtonDisabled: {
    backgroundColor: '#4B5563',
  },
  chatReadOnlyBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    padding: 14,
    backgroundColor: '#0F172A',
    borderTopWidth: 1,
    borderTopColor: '#334155',
  },
  chatReadOnlyText: {
    color: '#9CA3AF',
    fontSize: 13,
  },
  // License Alerts styles
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  // Radio styles
  radioButton: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 8,
    borderRadius: 10,
    backgroundColor: '#1E293B',
    borderWidth: 1,
    borderColor: '#334155',
    gap: 4,
  },
  radioButtonConnected: {
    borderColor: '#10B981',
    backgroundColor: '#10B98120',
  },
  radioButtonTransmitting: {
    borderColor: '#EF4444',
    backgroundColor: '#EF4444',
  },
  radioChannelBadge: {
    color: '#10B981',
    fontSize: 12,
    fontWeight: 'bold',
  },
  radioDropdownContainer: {
    position: 'absolute',
    top: 100,
    left: 10,
    right: 10,
    zIndex: 1000,
  },
  radioDropdown: {
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: '#334155',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 10,
  },
  radioDropdownHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 16,
  },
  radioDropdownTitle: {
    flex: 1,
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
    marginLeft: 10,
  },
  radioSectionLabel: {
    color: '#9CA3AF',
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 8,
  },
  radioChannelSelector: {
    marginBottom: 16,
  },
  radioChannelScroll: {
    marginBottom: 8,
  },
  radioChannelButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#0F172A',
    borderWidth: 2,
    borderColor: '#334155',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
  },
  radioChannelButtonActive: {
    borderColor: '#10B981',
    backgroundColor: '#10B98120',
  },
  radioChannelButtonBusy: {
    borderColor: '#F59E0B',
  },
  radioChannelButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: 'bold',
  },
  radioChannelButtonTextActive: {
    color: '#10B981',
  },
  radioChannelUserCount: {
    position: 'absolute',
    top: -4,
    right: -4,
    backgroundColor: '#6366F1',
    borderRadius: 10,
    minWidth: 18,
    height: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radioChannelUserCountText: {
    color: '#FFFFFF',
    fontSize: 10,
    fontWeight: 'bold',
  },
  radioChannelName: {
    color: '#6B7280',
    fontSize: 12,
    textAlign: 'center',
  },
  radioUsersSection: {
    marginBottom: 16,
    padding: 12,
    backgroundColor: '#0F172A',
    borderRadius: 10,
  },
  radioUsersList: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  radioUserBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#1E293B',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#334155',
  },
  radioUserBadgeTransmitting: {
    backgroundColor: '#10B981',
    borderColor: '#10B981',
  },
  radioUserName: {
    color: '#9CA3AF',
    fontSize: 12,
  },
  radioUserNameTransmitting: {
    color: '#FFFFFF',
    fontWeight: 'bold',
  },
  radioControlsRow: {
    flexDirection: 'row',
    gap: 12,
    marginBottom: 16,
  },
  radioControlButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#0F172A',
    borderWidth: 1,
    borderColor: '#334155',
  },
  radioControlButtonConnect: {
    backgroundColor: '#10B98120',
    borderColor: '#10B981',
  },
  radioControlButtonDisconnect: {
    backgroundColor: '#EF444420',
    borderColor: '#EF4444',
  },
  radioControlButtonMute: {
    backgroundColor: '#0F172A',
    borderColor: '#334155',
  },
  radioControlButtonMuteActive: {
    backgroundColor: '#F59E0B20',
    borderColor: '#F59E0B',
  },
  radioControlButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  radioPTTButton: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 24,
    borderRadius: 16,
    backgroundColor: '#0F172A',
    borderWidth: 3,
    borderColor: '#10B981',
  },
  radioPTTButtonDisabled: {
    borderColor: '#334155',
    backgroundColor: '#0F172A',
  },
  radioPTTButtonActive: {
    backgroundColor: '#10B981',
    borderColor: '#10B981',
  },
  radioPTTButtonBusy: {
    borderColor: '#F59E0B',
    backgroundColor: '#F59E0B20',
  },
  radioPTTText: {
    color: '#10B981',
    fontSize: 14,
    fontWeight: 'bold',
    marginTop: 8,
  },
  radioTransmittingInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 12,
    padding: 10,
    backgroundColor: '#F59E0B20',
    borderRadius: 10,
  },
  radioTransmittingText: {
    color: '#F59E0B',
    fontSize: 13,
  },
  alertsButton: {
    padding: 8,
    borderRadius: 8,
    backgroundColor: 'transparent',
  },
  alertsButtonActive: {
    backgroundColor: '#F59E0B',
  },
  alertsModal: {
    backgroundColor: '#1E293B',
    borderRadius: 20,
    width: '95%',
    maxWidth: 500,
    height: '85%',
    maxHeight: 650,
    overflow: 'hidden',
  },
  alertsModalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#334155',
  },
  alertsModalTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  alertsModalTitle: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: '700',
  },
  alertsModalActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  markAllReadButton: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    backgroundColor: '#334155',
    borderRadius: 8,
  },
  markAllReadText: {
    color: '#94A3B8',
    fontSize: 12,
    fontWeight: '600',
  },
  createAlertButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginHorizontal: 16,
    marginVertical: 12,
    paddingVertical: 12,
    backgroundColor: '#F59E0B',
    borderRadius: 12,
  },
  createAlertButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '700',
  },
  alertsListContainer: {
    flex: 1,
    paddingHorizontal: 16,
  },
  alertsLoadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
  },
  alertsEmptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
  },
  alertsEmptyText: {
    color: '#9CA3AF',
    fontSize: 18,
    fontWeight: '600',
    marginTop: 16,
  },
  alertsEmptySubtext: {
    color: '#6B7280',
    fontSize: 14,
    marginTop: 8,
    textAlign: 'center',
  },
  alertCard: {
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
    borderLeftWidth: 3,
    borderLeftColor: '#334155',
  },
  alertCardUnread: {
    borderLeftColor: '#F59E0B',
    backgroundColor: '#1E293B',
  },
  alertCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  alertTypeBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 12,
  },
  alertTypeBadgeText: {
    color: '#FFFFFF',
    fontSize: 11,
    fontWeight: '700',
  },
  deleteAlertButton: {
    padding: 6,
  },
  alertMessage: {
    color: '#E2E8F0',
    fontSize: 14,
    lineHeight: 20,
    marginBottom: 10,
  },
  alertSenderInfo: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  alertSenderText: {
    color: '#9CA3AF',
    fontSize: 12,
  },
  alertTimeText: {
    color: '#6B7280',
    fontSize: 11,
  },
  unreadBadge: {
    position: 'absolute',
    top: 10,
    right: 10,
    backgroundColor: '#EF4444',
    paddingVertical: 2,
    paddingHorizontal: 6,
    borderRadius: 4,
  },
  unreadBadgeText: {
    color: '#FFFFFF',
    fontSize: 9,
    fontWeight: '700',
  },
  // Create Alert Modal
  createAlertModal: {
    backgroundColor: '#1E293B',
    borderRadius: 24,
    padding: 24,
    width: '90%',
    maxWidth: 400,
  },
  createAlertHeader: {
    alignItems: 'center',
    marginBottom: 24,
  },
  createAlertTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '700',
    marginTop: 12,
  },
  createAlertSubtitle: {
    color: '#9CA3AF',
    fontSize: 14,
    marginTop: 4,
  },
  createAlertForm: {
    gap: 16,
  },
  createAlertInputGroup: {
    gap: 6,
  },
  createAlertLabel: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
    marginLeft: 4,
  },
  createAlertInput: {
    backgroundColor: '#0F172A',
    borderRadius: 12,
    padding: 14,
    color: '#FFFFFF',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#334155',
  },
  createAlertTextArea: {
    minHeight: 100,
    textAlignVertical: 'top',
  },
  alertTypeSelector: {
    flexDirection: 'row',
    gap: 10,
  },
  alertTypeOption: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingVertical: 12,
    backgroundColor: '#0F172A',
    borderRadius: 10,
    borderWidth: 2,
    borderColor: 'transparent',
  },
  alertTypeOptionActiveLost: {
    backgroundColor: 'rgba(245, 158, 11, 0.2)',
    borderColor: '#F59E0B',
  },
  alertTypeOptionActiveGeneral: {
    backgroundColor: 'rgba(99, 102, 241, 0.2)',
    borderColor: '#6366F1',
  },
  alertTypeOptionText: {
    color: '#94A3B8',
    fontSize: 13,
    fontWeight: '600',
  },
  alertTypeOptionTextActive: {
    color: '#FFFFFF',
  },
  createAlertButtons: {
    flexDirection: 'row',
    gap: 12,
    marginTop: 20,
  },
  createAlertCancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#334155',
    alignItems: 'center',
  },
  createAlertCancelButtonText: {
    color: '#94A3B8',
    fontSize: 16,
    fontWeight: '600',
  },
  createAlertSendButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#F59E0B',
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  createAlertSendButtonDisabled: {
    backgroundColor: '#4B5563',
  },
  createAlertSendButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  // License search styles
  licenseSearchContainer: {
    position: 'relative',
  },
  licenseInputSelected: {
    borderColor: '#10B981',
    borderWidth: 2,
  },
  licenseSearchSpinner: {
    position: 'absolute',
    right: 14,
    top: 14,
  },
  selectedRecipientBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 8,
    padding: 10,
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#10B981',
  },
  selectedRecipientText: {
    flex: 1,
    color: '#10B981',
    fontSize: 13,
    fontWeight: '600',
  },
  licenseSuggestionsContainer: {
    marginTop: 8,
    backgroundColor: '#0F172A',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#334155',
    maxHeight: 180,
    overflow: 'hidden',
  },
  licenseSuggestionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: '#1E293B',
  },
  suggestionInfo: {
    flex: 1,
  },
  suggestionName: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  suggestionLicense: {
    color: '#9CA3AF',
    fontSize: 12,
    marginTop: 2,
  },
  noSuggestionsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginTop: 10,
    padding: 14,
    backgroundColor: '#0F172A',
    borderRadius: 8,
  },
  noSuggestionsText: {
    color: '#6B7280',
    fontSize: 13,
  },
});
