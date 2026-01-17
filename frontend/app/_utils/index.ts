// =============================================================================
// UTILITIES - TaxiDash Madrid
// =============================================================================

/**
 * Format a date/time string to a readable format
 */
export const formatTime = (dateString: string): string => {
  const date = new Date(dateString);
  return date.toLocaleTimeString('es-ES', { 
    hour: '2-digit', 
    minute: '2-digit' 
  });
};

/**
 * Format a date to a readable format
 */
export const formatDate = (dateString: string): string => {
  const date = new Date(dateString);
  return date.toLocaleDateString('es-ES', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric'
  });
};

/**
 * Format a date with time
 */
export const formatDateTime = (dateString: string): string => {
  const date = new Date(dateString);
  return date.toLocaleString('es-ES', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
};

/**
 * Get relative time (hace X minutos)
 */
export const getRelativeTime = (dateString: string): string => {
  const now = new Date();
  const date = new Date(dateString);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  
  if (diffMins < 1) return 'ahora';
  if (diffMins < 60) return `hace ${diffMins} min`;
  
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `hace ${diffHours}h`;
  
  const diffDays = Math.floor(diffHours / 24);
  return `hace ${diffDays}d`;
};

/**
 * Check if current time is night or weekend (for fare calculation)
 */
export const isNightOrWeekend = (): boolean => {
  const now = new Date();
  const hour = now.getHours();
  const dayOfWeek = now.getDay(); // 0 = Sunday, 6 = Saturday
  
  const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
  const isNightTime = hour >= 21 || hour < 6;
  
  return isWeekend || isNightTime;
};

/**
 * Format currency (euros)
 */
export const formatCurrency = (amount: number): string => {
  return amount.toFixed(2).replace('.', ',') + '€';
};

/**
 * Format distance in km
 */
export const formatDistance = (km: number): string => {
  if (km < 1) {
    return `${Math.round(km * 1000)} m`;
  }
  return `${km.toFixed(1)} km`;
};

/**
 * Calculate haversine distance between two coordinates
 */
export const haversineDistance = (
  lat1: number, 
  lon1: number, 
  lat2: number, 
  lon2: number
): number => {
  const R = 6371; // Earth's radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = 
    Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
};

/**
 * Truncate string with ellipsis
 */
export const truncate = (str: string, maxLength: number): string => {
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength - 3) + '...';
};

/**
 * Capitalize first letter
 */
export const capitalize = (str: string): string => {
  return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
};

/**
 * Generate a unique ID
 */
export const generateId = (): string => {
  return Date.now().toString(36) + Math.random().toString(36).substr(2);
};

/**
 * Delay utility for async operations
 */
export const delay = (ms: number): Promise<void> => {
  return new Promise(resolve => setTimeout(resolve, ms));
};

/**
 * Safe JSON parse with fallback
 */
export const safeJsonParse = <T>(json: string, fallback: T): T => {
  try {
    return JSON.parse(json);
  } catch {
    return fallback;
  }
};

/**
 * Format duration in minutes to readable string
 */
export const formatDuration = (minutes: number): string => {
  if (minutes < 60) {
    return `${Math.round(minutes)} min`;
  }
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  if (mins === 0) {
    return `${hours}h`;
  }
  return `${hours}h ${mins}min`;
};

/**
 * Get action emoji for activity
 */
export const getActionEmoji = (action: string): string => {
  const emojiMap: { [key: string]: string } = {
    'load': '🟢',
    'unload': '🔴',
    'station_entry': '🚉',
    'station_exit': '🚕',
    'terminal_entry': '✈️',
    'terminal_exit': '🚕',
  };
  return emojiMap[action] || '📍';
};

/**
 * Get action label for activity
 */
export const getActionLabel = (action: string): string => {
  const labelMap: { [key: string]: string } = {
    'load': 'Carga',
    'unload': 'Descarga',
    'station_entry': 'Entrada estación',
    'station_exit': 'Salida estación',
    'terminal_entry': 'Entrada terminal',
    'terminal_exit': 'Salida terminal',
  };
  return labelMap[action] || action;
};
