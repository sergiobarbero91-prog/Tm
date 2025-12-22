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
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';
import * as Notifications from 'expo-notifications';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

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
  time: string;
  origin: string;
  train_type: string;
  train_number: string;
  platform?: string;
  status?: string;
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
  time: string;
  origin: string;
  flight_number: string;
  airline: string;
  terminal: string;
  gate?: string;
  status?: string;
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

export default function TransportMeter() {
  const [activeTab, setActiveTab] = useState<'trains' | 'flights'>('trains');
  const [trainData, setTrainData] = useState<TrainComparison | null>(null);
  const [flightData, setFlightData] = useState<FlightComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [timeWindow, setTimeWindow] = useState<30 | 60>(60);
  const [shift, setShift] = useState<'all' | 'day' | 'night'>('all');
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [pushToken, setPushToken] = useState<string | null>(null);

  // Register for notifications
  useEffect(() => {
    registerForPushNotifications();
  }, []);

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

  const fetchData = useCallback(async () => {
    try {
      if (activeTab === 'trains') {
        const response = await axios.get<TrainComparison>(`${API_BASE}/api/trains`, {
          params: { shift }
        });
        setTrainData(response.data);
      } else {
        const response = await axios.get<FlightComparison>(`${API_BASE}/api/flights`);
        setFlightData(response.data);
      }
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [activeTab, shift]);

  useEffect(() => {
    setLoading(true);
    fetchData();

    // Auto-refresh every 2 minutes
    const interval = setInterval(fetchData, 120000);
    return () => clearInterval(interval);
  }, [activeTab, fetchData]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchData();
  }, [fetchData]);

  const formatLastUpdate = (isoString: string) => {
    const date = new Date(isoString);
    return date.toLocaleTimeString('es-ES', { 
      hour: '2-digit', 
      minute: '2-digit',
      timeZone: 'Europe/Madrid'
    });
  };

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
                <Text style={styles.timeText}>{arrival.time}</Text>
              </View>
              <View style={styles.arrivalInfo}>
                <Text style={styles.trainType}>{arrival.train_type}</Text>
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
      </View>
    );
  };

  const renderTerminalCard = (terminal: TerminalData) => {
    const isWinner = timeWindow === 30 ? terminal.is_winner_30min : terminal.is_winner_60min;
    const arrivals = timeWindow === 30 ? terminal.total_next_30min : terminal.total_next_60min;

    return (
      <View
        key={terminal.terminal}
        style={[
          styles.terminalCard,
          isWinner && styles.winnerTerminalCard,
        ]}
      >
        {isWinner && (
          <View style={[styles.winnerBadge, styles.winnerBadgeFlight]}>
            <Ionicons name="trophy" size={14} color="#FFFFFF" />
            <Text style={styles.winnerBadgeText}>TOP</Text>
          </View>
        )}
        <Text style={[styles.terminalName, isWinner && styles.winnerTerminalText]}>
          {terminal.terminal}
        </Text>
        <Text style={[styles.terminalCount, isWinner && styles.winnerTerminalCount]}>
          {arrivals}
        </Text>
        <Text style={styles.terminalLabel}>vuelos</Text>
      </View>
    );
  };

  const renderFlightsList = () => {
    if (!flightData) return null;

    const winnerTerminal = timeWindow === 30 ? flightData.winner_30min : flightData.winner_60min;
    const winnerData = flightData.terminals[winnerTerminal];

    return (
      <View style={styles.flightsList}>
        <Text style={styles.flightsListTitle}>
          Próximas llegadas - Terminal {winnerTerminal}
        </Text>
        {winnerData.arrivals.slice(0, 6).map((flight, index) => (
          <View key={index} style={styles.flightItem}>
            <View style={styles.flightTime}>
              <Text style={styles.flightTimeText}>{flight.time}</Text>
            </View>
            <View style={styles.flightInfo}>
              <Text style={styles.flightNumber}>{flight.flight_number}</Text>
              <Text style={styles.flightOrigin} numberOfLines={1}>
                {flight.origin}
              </Text>
              <Text style={styles.flightAirline}>{flight.airline}</Text>
            </View>
            <View style={styles.flightGate}>
              <Text style={styles.gateLabel}>Puerta</Text>
              <Text style={styles.gateText}>{flight.gate || '-'}</Text>
            </View>
          </View>
        ))}
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
            <View style={styles.lastUpdate}>
              <Ionicons name="time-outline" size={14} color="#64748B" />
              <Text style={styles.lastUpdateText}>
                Actualizado: {formatLastUpdate(flightData.last_update)}
              </Text>
            </View>
            <Text style={styles.sectionTitle}>Terminales - Madrid Barajas</Text>
            <View style={styles.terminalsGrid}>
              {Object.values(flightData.terminals).map(renderTerminalCard)}
            </View>
            {renderFlightsList()}
          </>
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
    fontSize: 28,
    fontWeight: 'bold',
    color: '#FFFFFF',
  },
  headerSubtitle: {
    fontSize: 14,
    color: '#94A3B8',
    marginTop: 4,
  },
  notificationToggle: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  switch: {
    marginLeft: 8,
    transform: [{ scaleX: 0.8 }, { scaleY: 0.8 }],
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
  trainType: {
    color: '#6366F1',
    fontSize: 12,
    fontWeight: '600',
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
    marginTop: 20,
    backgroundColor: '#1E293B',
    borderRadius: 16,
    padding: 15,
  },
  flightsListTitle: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 15,
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
});
