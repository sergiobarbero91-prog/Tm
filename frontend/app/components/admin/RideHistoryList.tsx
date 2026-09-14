/**
 * RideHistoryList — lista de viajes cargada por endpoint,
 * reutilizada en el modal de editar conductor y en el de editar cliente.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Ride = {
  id: string;
  origin: string;
  destination: string;
  ride_type: 'asap' | 'scheduled';
  scheduled_at: string | null;
  status: string;
  client_name: string;
  client_phone: string;
  accepted_by_driver_name: string | null;
  passengers: number;
  created_at: string;
};

const STATUS_COLORS: Record<string, string> = {
  pending: '#F59E0B',
  accepted: '#3B82F6',
  in_progress: '#8B5CF6',
  completed: '#10B981',
  cancelled: '#94A3B8',
};

const STATUS_LABELS: Record<string, string> = {
  pending: 'Pendiente',
  accepted: 'Aceptado',
  in_progress: 'En curso',
  completed: 'Finalizado',
  cancelled: 'Cancelado',
};

interface Props {
  /** Full API path AFTER /api/, e.g. "admin/users/xxx/rides" */
  endpoint: string;
  /** perspective changes the top label ("Cliente" vs "Taxista aceptante") */
  perspective: 'client' | 'driver';
}

export const RideHistoryList: React.FC<Props> = ({ endpoint, perspective }) => {
  const [loading, setLoading] = useState(true);
  const [rides, setRides] = useState<Ride[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const tk = await AsyncStorage.getItem('token');
      const r = await axios.get(`${API_BASE}/api/${endpoint}`, { headers: tk ? { Authorization: `Bearer ${tk}` } : {} });
      setRides(r.data || []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Error cargando historial');
    } finally {
      setLoading(false);
    }
  }, [endpoint]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <View style={{ padding: 12, alignItems: 'center' }}><ActivityIndicator color="#F59E0B" /></View>;
  }
  if (error) {
    return <Text style={{ color: '#EF4444', padding: 12 }}>{error}</Text>;
  }
  if (rides.length === 0) {
    return <Text style={{ color: '#64748B', fontStyle: 'italic', padding: 12 }}>Sin viajes registrados.</Text>;
  }

  return (
    <ScrollView style={{ maxHeight: 360 }} testID="ride-history-scroll">
      {rides.map(r => {
        const color = STATUS_COLORS[r.status] || '#94A3B8';
        const label = STATUS_LABELS[r.status] || r.status;
        const when = r.ride_type === 'asap'
          ? new Date(r.created_at).toLocaleString('es-ES')
          : (r.scheduled_at ? new Date(r.scheduled_at).toLocaleString('es-ES') : '');
        return (
          <View
            key={r.id}
            testID={`ride-history-item-${r.id}`}
            style={{ backgroundColor: '#1E293B', borderRadius: 8, padding: 10, marginBottom: 6, borderLeftWidth: 3, borderLeftColor: color }}
          >
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
              <Text style={{ color, fontWeight: '800', fontSize: 11 }}>
                {label.toUpperCase()} · {r.ride_type === 'asap' ? 'ASAP' : 'RESERVA'}
              </Text>
              <Text style={{ color: '#94A3B8', fontSize: 11 }}>{when}</Text>
            </View>
            <Text style={{ color: '#F1F5F9', fontSize: 13, fontWeight: '700' }}>{r.origin}</Text>
            <Text style={{ color: '#94A3B8', fontSize: 12 }}>→ {r.destination}</Text>
            <Text style={{ color: '#8B5CF6', fontSize: 11, marginTop: 4 }}>
              <Ionicons name={perspective === 'client' ? 'car' : 'person'} size={10} />
              {' '}
              {perspective === 'client'
                ? (r.accepted_by_driver_name || 'Sin taxista asignado')
                : `${r.client_name} · ${r.client_phone}`}
              {r.passengers > 1 && ` · ${r.passengers} pax`}
            </Text>
          </View>
        );
      })}
    </ScrollView>
  );
};

export default RideHistoryList;
