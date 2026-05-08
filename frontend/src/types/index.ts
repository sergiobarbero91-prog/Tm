// =============================================================================
// TYPES - TaxiDash Madrid
// =============================================================================

export interface TrainArrival {
  time: string;
  scheduled_time?: string;
  origin: string;
  train_type: string;
  train_number: string;
  platform?: string;
  status?: string;
  delay_minutes?: number;
}

export interface PeakHourInfo {
  start_hour: string;
  end_hour: string;
  count: number;
}

export interface StationData {
  station_id: string;
  station_name: string;
  arrivals: TrainArrival[];
  total_next_30min: number;
  total_next_60min: number;
  is_winner_30min: boolean;
  is_winner_60min: boolean;
  peak_hour?: PeakHourInfo;
  score_30min?: number;
  score_60min?: number;
  past_30min?: number;
  past_60min?: number;
}

export interface TrainComparison {
  atocha: StationData;
  chamartin: StationData;
  winner_30min: string;
  winner_60min: string;
  last_update: string;
  is_night_time?: boolean;
  message?: string;
}

export interface FlightArrival {
  time: string;
  scheduled_time?: string;
  origin: string;
  flight_number: string;
  airline: string;
  terminal: string;
  gate?: string;
  status?: string;
  delay_minutes?: number;
}

export interface TerminalData {
  terminal: string;
  arrivals: FlightArrival[];
  total_next_30min: number;
  total_next_60min: number;
  is_winner_30min: boolean;
  is_winner_60min: boolean;
  score_30min?: number;
  score_60min?: number;
  past_30min?: number;
  past_60min?: number;
}

export interface FlightComparison {
  terminals: { [key: string]: TerminalData };
  winner_30min: string;
  winner_60min: string;
  last_update: string;
  message?: string;
}

export interface HotStreet {
  street_name: string;
  count: number;
  last_activity: string;
  latitude: number;
  longitude: number;
  distance_km?: number | null;
}

export interface StreetActivity {
  id: string;
  user_id: string;
  username: string;
  action: string;
  latitude: number;
  longitude: number;
  street_name: string;
  location_name?: string;
  created_at: string;
  duration_minutes?: number;
  distance_km?: number;
}

export interface StreetWorkData {
  hottest_street: string | null;
  hottest_street_lat: number | null;
  hottest_street_lng: number | null;
  hottest_count: number;
  hottest_percentage: number | null;
  hottest_total_loads: number;
  hottest_distance_km: number | null;
  hot_streets: HotStreet[];
  
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
  
  hottest_station_taxi_status?: string | null;
  hottest_station_taxi_time?: string | null;
  hottest_station_taxi_reporter?: string | null;
  hottest_terminal_taxi_status?: string | null;
  hottest_terminal_taxi_time?: string | null;
  hottest_terminal_taxi_reporter?: string | null;
  
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

export interface TaxiStatusData {
  [key: string]: {
    location_type: string;
    location_name: string;
    taxi_status: string;
    reported_at: string;
    reported_by: string;
  };
}

export interface QueueStatusData {
  [key: string]: {
    location_type: string;
    location_name: string;
    queue_status: string;
    reported_at: string;
    reported_by: string;
  };
}

export interface User {
  id: string;
  username: string;
  full_name: string | null;
  license_number: string | null;
  phone: string | null;
  role: string;
  preferred_shift: string;
}

export interface CheckInStatus {
  is_checked_in: boolean;
  location_type: string | null;
  location_name: string | null;
  entry_time: string | null;
}

export type GpsApp = 'google' | 'waze';

export type TabType = 'trains' | 'flights' | 'street' | 'events' | 'admin';

export interface EmergencyAlert {
  id: string;
  user_id: string;
  username: string;
  full_name?: string;
  license_number?: string;
  alert_type: 'companions' | 'companions_police';
  latitude: number;
  longitude: number;
  created_at: string;
  resolved_at?: string;
  status: 'active' | 'resolved';
}

export interface StationAlert {
  id: string;
  location_type: string;
  location_name: string;
  alert_type: 'sin_taxis' | 'barandilla';
  reported_by: string;
  reporter_username: string;
  created_at: string;
  cancelled_at?: string;
  cancelled_by?: string;
  is_active: boolean;
}

export interface LicenseAlert {
  id: string;
  title: string;
  message: string;
  created_by: string;
  created_at: string;
  priority: 'normal' | 'high' | 'urgent';
}

export interface ChatMessage {
  id: string;
  user_id: string;
  username: string;
  message: string;
  created_at: string;
}

export interface EventData {
  id: string;
  title: string;
  description?: string;
  location: string;
  latitude?: number;
  longitude?: number;
  start_time: string;
  end_time?: string;
  expected_taxis?: number;
  created_by: string;
  created_at: string;
}

export interface FareResult {
  tarifa: string;
  suplemento: string;
  isInsideM30: boolean;
  latitude: number;
  longitude: number;
  addressName: string;
}

export interface StreetFareResult {
  distance_km: number;
  fare_min: number;
  fare_max: number;
  is_night_or_weekend: boolean;
  base_fare: number;
  per_km_rate: number;
}

export interface AddressSuggestion {
  latitude: number;
  longitude: number;
  address: string;
  is_inside_m30: boolean;
}
