import React, { useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  TextInput,
  ActivityIndicator,
  Platform,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface FareCalcResult {
  tarifa: string;
  suplemento: string;
  fare_min?: number;
  fare_max?: number;
  distance_km?: number;
  details?: string;
}

interface PublicFareCalculatorProps {
  styles: any;
}

export const PublicFareCalculator: React.FC<PublicFareCalculatorProps> = ({ styles }) => {
  const [fareCalcOriginType, setFareCalcOriginType] = useState<'terminal' | 'station' | 'street'>('terminal');
  const [fareCalcOrigin, setFareCalcOrigin] = useState<string>('T1');
  const [fareCalcStreetAddress, setFareCalcStreetAddress] = useState<string>('');
  const [fareCalcDestAddress, setFareCalcDestAddress] = useState<string>('');
  const [fareCalcLoading, setFareCalcLoading] = useState<boolean>(false);
  const [fareCalcResult, setFareCalcResult] = useState<FareCalcResult | null>(null);

  // Calculate fare based on origin type and destination
  const calculatePublicFare = async () => {
    if (fareCalcLoading) return;
    
    // Validate inputs
    if (fareCalcOriginType === 'street' && !fareCalcStreetAddress.trim()) {
      if (Platform.OS === 'web') {
        alert('Introduce una dirección de origen');
      } else {
        Alert.alert('Error', 'Introduce una dirección de origen');
      }
      return;
    }
    
    if (!fareCalcDestAddress.trim()) {
      if (Platform.OS === 'web') {
        alert('Introduce una dirección de destino');
      } else {
        Alert.alert('Error', 'Introduce una dirección de destino');
      }
      return;
    }
    
    setFareCalcLoading(true);
    setFareCalcResult(null);
    
    try {
      // Get current hour to determine T1 vs T2
      // T1: Laborables 6:00-21:00 → 2,50€ bajada + 1,40€/km
      // T2: Festivos y laborables 21:00-6:00 → 3,20€ bajada + 1,60€/km
      const now = new Date();
      const hour = now.getHours();
      const day = now.getDay();
      const isNight = hour >= 21 || hour < 6;
      const isWeekend = day === 0 || day === 6;
      const isTarifa2 = isNight || isWeekend;
      const tarifaBase = isTarifa2 ? 'Tarifa 2' : 'Tarifa 1';
      const per_km_rate = isTarifa2 ? 1.60 : 1.40;
      const bajada_bandera = isTarifa2 ? 3.20 : 2.50;
      
      // Terminal coordinates
      const terminalCoords: { [key: string]: { lat: number; lng: number } } = {
        'T1': { lat: 40.4676, lng: -3.5701 },
        'T2': { lat: 40.4693, lng: -3.5660 },
        'T3': { lat: 40.4654, lng: -3.5708 },
        'T4': { lat: 40.4719, lng: -3.5626 },
      };
      
      // Station coordinates
      const stationCoords: { [key: string]: { lat: number; lng: number } } = {
        'Atocha': { lat: 40.4055, lng: -3.6883 },
        'Chamartín': { lat: 40.4720, lng: -3.6822 },
      };
      
      // Helper to calculate distance between two points
      const haversine = (lat1: number, lon1: number, lat2: number, lon2: number) => {
        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                  Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                  Math.sin(dLon/2) * Math.sin(dLon/2);
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      };
      
      let originCoords: { lat: number; lng: number } | null = null;
      let isAirport = false;
      let isStation = false;
      
      // Get origin coordinates
      if (fareCalcOriginType === 'terminal') {
        originCoords = terminalCoords[fareCalcOrigin] || terminalCoords['T4'];
        isAirport = true;
      } else if (fareCalcOriginType === 'station') {
        originCoords = stationCoords[fareCalcOrigin] || stationCoords['Atocha'];
        isStation = true;
      } else {
        // Geocode street address
        try {
          const geocodeResponse = await axios.get(`${API_BASE}/api/geocode/forward`, {
            params: { address: fareCalcStreetAddress + ', Madrid, Spain' },
            timeout: 10000
          });
          if (geocodeResponse.data?.latitude && geocodeResponse.data?.longitude) {
            originCoords = { lat: geocodeResponse.data.latitude, lng: geocodeResponse.data.longitude };
          }
        } catch (e) {
          console.log('Geocode origin error:', e);
        }
      }
      
      if (!originCoords) {
        throw new Error('No se pudo encontrar la dirección de origen');
      }
      
      // Geocode destination
      let destCoords: { lat: number; lng: number } | null = null;
      try {
        const geocodeResponse = await axios.get(`${API_BASE}/api/geocode/forward`, {
          params: { address: fareCalcDestAddress + ', Madrid, Spain' },
          timeout: 10000
        });
        if (geocodeResponse.data?.latitude && geocodeResponse.data?.longitude) {
          destCoords = { lat: geocodeResponse.data.latitude, lng: geocodeResponse.data.longitude };
        }
      } catch (e) {
        console.log('Geocode dest error:', e);
      }
      
      if (!destCoords) {
        throw new Error('No se pudo encontrar la dirección de destino');
      }
      
      // Check if destination is inside M30 (use the is_inside_m30 from geocoding response)
      let isDestInsideM30 = false;
      try {
        const geocodeCheckResponse = await axios.get(`${API_BASE}/api/geocode/forward`, {
          params: { address: fareCalcDestAddress + ', Madrid, Spain' },
          timeout: 10000
        });
        isDestInsideM30 = geocodeCheckResponse.data?.is_inside_m30 ?? false;
      } catch (e) {
        console.log('M30 check error, using default:', e);
      }
      
      // Get route distance
      let distance_km = 0;
      try {
        const routeResponse = await axios.post(`${API_BASE}/api/calculate-route-distance`, {
          origin_lat: originCoords.lat,
          origin_lng: originCoords.lng,
          dest_lat: destCoords.lat,
          dest_lng: destCoords.lng
        }, { timeout: 15000 });
        distance_km = routeResponse.data.distance_km || 0;
      } catch (e) {
        // Fallback to straight line distance * 1.3
        distance_km = haversine(originCoords.lat, originCoords.lng, destCoords.lat, destCoords.lng) * 1.3;
      }
      
      let tarifa = '';
      let suplemento = '';
      let fare_min = 0;
      let fare_max = 0;
      let details = '';
      
      // Apply fare rules
      if (isStation) {
        // TARIFA 7: Estación/IFEMA → Cualquier destino
        // Base 8€ (cubre primeros 1,4km), resto con tarifa horaria SIN bajada de bandera
        const TARIFA_7_BASE = 8.00;
        const TARIFA_7_KM_FRANCHISE = 1.4;
        const extra_km = Math.max(0, distance_km - TARIFA_7_KM_FRANCHISE);
        // Solo km extra, sin bajada de bandera
        const total = TARIFA_7_BASE + (extra_km * per_km_rate);
        fare_min = total;
        fare_max = total * 1.05;
        
        if (extra_km > 0) {
          tarifa = `Tarifa 7 + ${tarifaBase}`;
          details = `Base 8€ (1,4km incluidos) + ${extra_km.toFixed(1)}km × ${per_km_rate.toFixed(2)}€/km`;
        } else {
          tarifa = 'Tarifa 7';
          details = 'Base 8€ (primeros 1,4km incluidos)';
        }
        suplemento = `${fare_min.toFixed(2)}€ - ${fare_max.toFixed(2)}€`;
      }
      else if (isAirport && isDestInsideM30) {
        // TARIFA 4: Aeropuerto ↔ Dentro M30 = FIJO 33€
        tarifa = 'Tarifa 4 (Fija)';
        suplemento = '33,00€';
        fare_min = 33;
        fare_max = 33;
        details = 'Tarifa fija aeropuerto ↔ dentro de M30';
      }
      else if (isAirport && !isDestInsideM30) {
        // TARIFA 3: Aeropuerto → Fuera M30
        // Base 22€ (cubre primeros 9km), resto con tarifa horaria SIN bajada de bandera
        const TARIFA_3_BASE = 22.00;
        const TARIFA_3_KM_FRANCHISE = 9;
        const extra_km = Math.max(0, distance_km - TARIFA_3_KM_FRANCHISE);
        // Solo km extra, sin bajada de bandera
        const total = TARIFA_3_BASE + (extra_km * per_km_rate);
        fare_min = total;
        fare_max = total * 1.05;
        
        if (extra_km > 0) {
          tarifa = `Tarifa 3 + ${tarifaBase}`;
          details = `Base 22€ (9km incluidos) + ${extra_km.toFixed(1)}km × ${per_km_rate.toFixed(2)}€/km`;
        } else {
          tarifa = 'Tarifa 3';
          details = 'Base 22€ (primeros 9km incluidos)';
        }
        suplemento = `${fare_min.toFixed(2)}€ - ${fare_max.toFixed(2)}€`;
      }
      else {
        // TARIFA 1/2: Calle normal - bajada de bandera + km
        const total = bajada_bandera + (distance_km * per_km_rate);
        fare_min = total;
        fare_max = total * 1.05;
        tarifa = tarifaBase;
        details = `Bajada bandera ${bajada_bandera.toFixed(2)}€ + ${distance_km.toFixed(1)}km × ${per_km_rate.toFixed(2)}€/km`;
        suplemento = `${fare_min.toFixed(2)}€ - ${fare_max.toFixed(2)}€`;
      }
      
      setFareCalcResult({
        tarifa,
        suplemento,
        fare_min,
        fare_max,
        distance_km,
        details
      });
      
    } catch (error: any) {
      const message = error.message || 'Error al calcular la tarifa';
      if (Platform.OS === 'web') {
        alert(`${message}`);
      } else {
        Alert.alert('Error', message);
      }
    } finally {
      setFareCalcLoading(false);
    }
  };

  return (
    <View style={styles.publicFaresContainer} data-testid="public-fare-calculator">
      <View style={styles.publicFaresHeader}>
        <Ionicons name="calculator" size={24} color="#10B981" />
        <Text style={styles.publicFaresTitle}>Calculadora de Tarifas</Text>
      </View>
      
      {/* Origin Type Selector */}
      <Text style={[styles.faresSectionTitle, { marginBottom: 8 }]}>Origen</Text>
      <View style={styles.faresOriginTypeSelector}>
        <TouchableOpacity
          style={[styles.faresOriginTypeBtn, fareCalcOriginType === 'terminal' && styles.faresOriginTypeBtnActive]}
          onPress={() => {
            setFareCalcOriginType('terminal');
            setFareCalcOrigin('T1');
            setFareCalcResult(null);
          }}
        >
          <Ionicons name="airplane" size={18} color={fareCalcOriginType === 'terminal' ? '#FFFFFF' : '#94A3B8'} />
          <Text style={[styles.faresOriginTypeBtnText, fareCalcOriginType === 'terminal' && styles.faresOriginTypeBtnTextActive]}>Terminal</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.faresOriginTypeBtn, fareCalcOriginType === 'station' && styles.faresOriginTypeBtnActive]}
          onPress={() => {
            setFareCalcOriginType('station');
            setFareCalcOrigin('Atocha');
            setFareCalcResult(null);
          }}
        >
          <Ionicons name="train" size={18} color={fareCalcOriginType === 'station' ? '#FFFFFF' : '#94A3B8'} />
          <Text style={[styles.faresOriginTypeBtnText, fareCalcOriginType === 'station' && styles.faresOriginTypeBtnTextActive]}>Estación</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.faresOriginTypeBtn, fareCalcOriginType === 'street' && styles.faresOriginTypeBtnActive]}
          onPress={() => {
            setFareCalcOriginType('street');
            setFareCalcResult(null);
          }}
        >
          <Ionicons name="location" size={18} color={fareCalcOriginType === 'street' ? '#FFFFFF' : '#94A3B8'} />
          <Text style={[styles.faresOriginTypeBtnText, fareCalcOriginType === 'street' && styles.faresOriginTypeBtnTextActive]}>Calle</Text>
        </TouchableOpacity>
      </View>
      
      {/* Location Selector */}
      {fareCalcOriginType === 'terminal' && (
        <View style={[styles.faresLocationSelector, { marginTop: 10, marginBottom: 16 }]}>
          {['T1', 'T2', 'T3', 'T4'].map((t) => (
            <TouchableOpacity
              key={t}
              style={[styles.faresLocationBtn, fareCalcOrigin === t && styles.faresLocationBtnActive]}
              onPress={() => { setFareCalcOrigin(t); setFareCalcResult(null); }}
            >
              <Text style={[styles.faresLocationBtnText, fareCalcOrigin === t && styles.faresLocationBtnTextActive]}>{t}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
      
      {fareCalcOriginType === 'station' && (
        <View style={[styles.faresLocationSelector, { marginTop: 10, marginBottom: 16 }]}>
          {['Atocha', 'Chamartín'].map((s) => (
            <TouchableOpacity
              key={s}
              style={[styles.faresLocationBtn, fareCalcOrigin === s && styles.faresLocationBtnActive]}
              onPress={() => { setFareCalcOrigin(s); setFareCalcResult(null); }}
            >
              <Text style={[styles.faresLocationBtnText, fareCalcOrigin === s && styles.faresLocationBtnTextActive]}>{s}</Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
      
      {fareCalcOriginType === 'street' && (
        <View style={[styles.faresInputContainer, { marginTop: 10, marginBottom: 16 }]}>
          <Ionicons name="location-outline" size={18} color="#64748B" style={{ marginRight: 8 }} />
          <TextInput
            style={styles.faresInput}
            placeholder="Dirección origen (ej: Gran Vía 32)"
            placeholderTextColor="#64748B"
            value={fareCalcStreetAddress}
            onChangeText={(text) => { setFareCalcStreetAddress(text); setFareCalcResult(null); }}
          />
        </View>
      )}
      
      {/* Destination */}
      <Text style={[styles.faresSectionTitle, { marginBottom: 8 }]}>Destino</Text>
      <View style={[styles.faresInputContainer, { marginBottom: 16 }]}>
        <Ionicons name="flag-outline" size={18} color="#64748B" style={{ marginRight: 8 }} />
        <TextInput
          style={styles.faresInput}
          placeholder="Dirección destino (ej: Calle Alcalá 100)"
          placeholderTextColor="#64748B"
          value={fareCalcDestAddress}
          onChangeText={(text) => { setFareCalcDestAddress(text); setFareCalcResult(null); }}
        />
      </View>
      
      {/* Calculate Button */}
      <TouchableOpacity
        style={[styles.faresCalculateBtn, fareCalcLoading && styles.faresCalculateBtnDisabled]}
        onPress={calculatePublicFare}
        disabled={fareCalcLoading}
      >
        {fareCalcLoading ? (
          <ActivityIndicator color="#FFFFFF" />
        ) : (
          <>
            <Ionicons name="calculator" size={20} color="#FFFFFF" />
            <Text style={styles.faresCalculateBtnText}>Calcular</Text>
          </>
        )}
      </TouchableOpacity>
      
      {/* Result */}
      {fareCalcResult && (
        <View style={[styles.faresResultCard, { marginTop: 16 }]}>
          <View style={styles.faresResultRow}>
            <Text style={styles.faresResultLabel}>Tarifa:</Text>
            <Text style={styles.faresResultValue}>{fareCalcResult.tarifa}</Text>
          </View>
          <View style={styles.faresResultDivider} />
          <View style={styles.faresResultRow}>
            <Text style={styles.faresResultLabel}>Precio:</Text>
            <Text style={styles.faresResultPrice}>{fareCalcResult.suplemento}</Text>
          </View>
          {fareCalcResult.distance_km && fareCalcResult.distance_km > 0 && (
            <>
              <View style={styles.faresResultDivider} />
              <View style={styles.faresResultRow}>
                <Text style={styles.faresResultLabel}>Distancia:</Text>
                <Text style={styles.faresResultValue}>{fareCalcResult.distance_km.toFixed(1)} km</Text>
              </View>
            </>
          )}
          {fareCalcResult.details && (
            <Text style={styles.faresResultDetails}>{fareCalcResult.details}</Text>
          )}
        </View>
      )}
    </View>
  );
};

export default PublicFareCalculator;
