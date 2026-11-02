import React, { useCallback, useEffect, useState } from 'react';
import { View, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const listeners = new Set<() => void>();
export const notifyLicenseChanged = () => listeners.forEach(fn => fn());

type RestStatus = {
  rest_soon?: boolean;
  minutes_to_rest?: number;
  known: boolean;
  can_work: boolean | null;
  label?: string;
  reason?: string;
  in_shift: boolean;
  shift_label: string;
};

export const LicenseRestBanner: React.FC = () => {
  const [st, setSt] = useState<RestStatus | null>(null);

  const load = useCallback(async () => {
    try {
      const tk = await AsyncStorage.getItem('token');
      if (!tk) return;
      const r = await axios.get(`${API_BASE}/api/license-rest/me`, { headers: { Authorization: `Bearer ${tk}` } });
      setSt(r.data);
    } catch {
      // keep last value
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    listeners.add(load);
    return () => { clearInterval(id); listeners.delete(load); };
  }, [load]);

  if (!st) return null;

  if (!st.known) {
    return (
      <View testID="license-rest-banner" style={[box, { backgroundColor: '#1E293B', borderColor: '#475569' }]}>
        <Ionicons name="id-card-outline" size={26} color="#94A3B8" />
        <View style={{ flex: 1 }}>
          <Text testID="license-rest-title" style={[title, { color: '#E2E8F0' }]}>Libranza desconocida</Text>
          <Text style={sub}>Añade tu número de licencia en tu perfil para saber si puedes trabajar.</Text>
        </View>
      </View>
    );
  }

  const ok = !!st.can_work;
  return (
    <View
      testID="license-rest-banner"
      style={[box, { backgroundColor: ok ? '#052E1B' : '#3B0A0A', borderColor: ok ? '#10B981' : '#EF4444' }]}
    >
      <Ionicons name={ok ? 'checkmark-circle' : 'close-circle'} size={30} color={ok ? '#10B981' : '#EF4444'} />
      <View style={{ flex: 1 }}>
        <Text testID="license-rest-title" style={[title, { color: ok ? '#6EE7B7' : '#FCA5A5' }]}>
          {ok ? 'Puedes trabajar' : 'Hoy libras'}
        </Text>
        <Text testID="license-rest-label" style={sub}>
          {ok ? st.label : `${st.label} (${st.reason})`}
        </Text>
        {ok && st.rest_soon && (
          <Text testID="license-rest-soon" style={[sub, { color: '#FBBF24', fontWeight: '700' }]}>
            Empiezas a librar en {st.minutes_to_rest} min: planifica tus últimas carreras
          </Text>
        )}
        {ok && !st.in_shift && (
          <Text testID="license-rest-shift" style={[sub, { color: '#FBBF24' }]}>
            Fuera de tu turno preferido: {st.shift_label}
          </Text>
        )}
      </View>
    </View>
  );
};

const box = {
  flexDirection: 'row' as const,
  alignItems: 'center' as const,
  gap: 12,
  borderWidth: 1,
  borderRadius: 14,
  padding: 14,
  marginHorizontal: 12,
  marginTop: 10,
  marginBottom: 4,
};
const title = { fontSize: 18, fontWeight: '800' as const };
const sub = { color: '#CBD5E1', fontSize: 13, marginTop: 2 };
