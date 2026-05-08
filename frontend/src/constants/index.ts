// =============================================================================
// CONSTANTS - TaxiDash Madrid
// =============================================================================

// Terminal Groups for Airport
export const TERMINAL_GROUPS = [
  { name: 'T1', terminals: ['T1'], zoneName: 'T1' },
  { name: 'T2-T3', terminals: ['T2', 'T3'], zoneName: 'T2-T3' },
  { name: 'T4-T4S', terminals: ['T4', 'T4S'], zoneName: 'T4-T4S' },
];

// Station coordinates
export const STATION_COORDS: { [key: string]: { lat: number; lng: number } } = {
  'Atocha': { lat: 40.4055, lng: -3.6883 },
  'Chamartín': { lat: 40.4720, lng: -3.6822 },
};

// Terminal coordinates
export const TERMINAL_COORDS: { [key: string]: { lat: number; lng: number } } = {
  'T1': { lat: 40.4676, lng: -3.5701 },
  'T2': { lat: 40.4693, lng: -3.5660 },
  'T3': { lat: 40.4654, lng: -3.5708 },
  'T4': { lat: 40.4719, lng: -3.5626 },
  'T4S': { lat: 40.4857, lng: -3.5920 },
};

// Airport detection bounding box
export const AIRPORT_BOUNDS = {
  LAT_MIN: 40.46,
  LAT_MAX: 50.50,
  LNG_MIN: -3.60,
  LNG_MAX: -3.55,
};

// Fare constants
export const FARE_RATES = {
  // Tarifa 1 - Diurna (L-V 06:00-21:00)
  T1_BASE: 2.55,
  T1_PER_KM: 1.40,
  
  // Tarifa 2 - Nocturna/Festivos
  T2_BASE: 3.20,
  T2_PER_KM: 1.60,
  
  // Tarifa 3 - Aeropuerto -> Fuera M30
  T3_BASE: 22.00,
  T3_KM_INCLUDED: 9.0,
  
  // Tarifa 4 - Aeropuerto <-> M30 (FIJO)
  T4_FIXED: 33.00,
  
  // Tarifa 7 - Estaciones -> Cualquier destino (excepto aeropuerto)
  T7_BASE: 8.00,
  T7_KM_INCLUDED: 1.4,
};

// Radio channels
export const RADIO_CHANNELS = [
  { id: 1, name: 'General' },
  { id: 2, name: 'Aeropuerto' },
  { id: 3, name: 'Estaciones' },
  { id: 4, name: 'Centro' },
  { id: 5, name: 'Norte' },
  { id: 6, name: 'Sur' },
  { id: 7, name: 'Este' },
  { id: 8, name: 'Oeste' },
  { id: 9, name: 'Emergencias' },
  { id: 10, name: 'Eventos' },
  { id: 11, name: 'T1' },
  { id: 12, name: 'T2-T3' },
  { id: 13, name: 'T4-T4S' },
  { id: 14, name: 'Atocha' },
  { id: 15, name: 'Chamartín' },
];

// API refresh intervals (in ms)
export const REFRESH_INTERVALS = {
  TRAINS: 30000,       // 30 seconds
  FLIGHTS: 30000,      // 30 seconds
  STREET_DATA: 30000,  // 30 seconds
  TAXI_STATUS: 30000,  // 30 seconds
  HEALTH_CHECK: 60000, // 1 minute
  EMERGENCY: 10000,    // 10 seconds
  CHAT: 5000,          // 5 seconds
  SESSION_REFRESH: 20 * 60 * 1000, // 20 minutes
};

// Color palette
export const COLORS = {
  primary: '#6366F1',
  secondary: '#8B5CF6',
  success: '#10B981',
  warning: '#F59E0B',
  danger: '#EF4444',
  info: '#3B82F6',
  
  background: '#0F172A',
  backgroundLight: '#1E293B',
  backgroundLighter: '#334155',
  
  text: '#FFFFFF',
  textMuted: '#94A3B8',
  textDark: '#64748B',
  
  border: '#334155',
  borderLight: 'rgba(255,255,255,0.1)',
};

// Status colors
export const STATUS_COLORS = {
  free: '#10B981',      // Green - Libre
  moderate: '#F59E0B',  // Yellow - Normal
  busy: '#EF4444',      // Red - Lleno
};
