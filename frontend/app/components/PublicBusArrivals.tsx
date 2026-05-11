import React, { useState, useEffect } from 'react';
import { View, Text, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export const PublicBusArrivals = () => {
  const [busData, setBusData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchBuses = async () => {
      try {
        const res = await axios.get(`${API_BASE}/api/buses`);
        setBusData(res.data);
      } catch {
        // Silently fail
      } finally {
        setLoading(false);
      }
    };
    fetchBuses();
  }, []);

  if (loading) {
    return (
      <View style={{ marginTop: 16, alignItems: 'center', paddingVertical: 10 }}>
        <ActivityIndicator color="#6366F1" size="small" />
      </View>
    );
  }

  if (!busData) return null;

  const renderStation = (station: any, label: string) => {
    const isWinner = station.is_winner_60min;
    const arrivals = station.arrivals?.slice(0, 3) || [];
    return (
      <View style={{
        backgroundColor: isWinner ? 'rgba(245, 158, 11, 0.15)' : 'transparent',
        borderRadius: 8,
        padding: 8,
        marginBottom: 8,
        borderWidth: isWinner ? 1 : 0,
        borderColor: 'rgba(245, 158, 11, 0.3)',
      }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
          <Text style={{ color: isWinner ? '#F59E0B' : '#CBD5E1', fontSize: 13, fontWeight: '600', flex: 1 }}>
            {isWinner ? '\u{1F525} ' : ''}{label}
          </Text>
          <View style={{ backgroundColor: isWinner ? '#F59E0B' : '#475569', borderRadius: 8, paddingHorizontal: 6, paddingVertical: 2 }}>
            <Text style={{ color: isWinner ? '#0F172A' : '#CBD5E1', fontSize: 10, fontWeight: '700' }}>
              {station.total_next_60min} en 60min
            </Text>
          </View>
        </View>
        {arrivals.map((bus: any, idx: number) => (
          <View key={idx} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 2, paddingLeft: 8 }}>
            <Text style={{ color: '#94A3B8', fontSize: 12, width: 42 }}>{bus.time}</Text>
            <Text style={{ color: '#818CF8', fontSize: 12, fontWeight: '600', width: 55 }}>{bus.bus_company}</Text>
            <Text style={{ color: '#64748B', fontSize: 11, flex: 1 }} numberOfLines={1}>{bus.origin}</Text>
          </View>
        ))}
      </View>
    );
  };

  return (
    <View style={{ marginTop: 16, marginBottom: 8 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
        <Ionicons name="bus" size={18} color="#6366F1" />
        <Text style={{ color: '#6366F1', fontSize: 14, fontWeight: '700', marginLeft: 8 }}>
          Estaciones de autobuses
        </Text>
      </View>
      {renderStation(busData.avenida_america, 'Av. América (ALSA)')}
      {renderStation(busData.estacion_sur, 'Estación Sur (Avanza)')}
    </View>
  );
};
