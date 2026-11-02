import React, { useEffect, useState } from 'react';
import { Modal, View, Text, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export type TrustedRide = {
  id: string;
  origin: string;
  destination: string;
  client_name: string;
  passengers: number;
  ride_type: 'asap' | 'scheduled';
  scheduled_at: string | null;
  exclusive_until: string;
};

interface Props {
  ride: TrustedRide;
  onAccept: () => Promise<void>;
  onRelease: () => Promise<void>;
  onLater: () => void;
}

const left = (iso: string) => Math.max(0, Math.floor((new Date(iso).getTime() - Date.now()) / 1000));

// Full-screen alert so the driver can't miss a request from a client they invited
export const TrustedRideAlert = ({ ride, onAccept, onRelease, onLater }: Props) => {
  const [secs, setSecs] = useState(left(ride.exclusive_until));
  const [busy, setBusy] = useState<'accept' | 'release' | null>(null);

  useEffect(() => {
    const t = setInterval(() => setSecs(left(ride.exclusive_until)), 1000);
    return () => clearInterval(t);
  }, [ride.exclusive_until]);

  const run = async (kind: 'accept' | 'release', fn: () => Promise<void>) => {
    setBusy(kind);
    try { await fn(); } finally { setBusy(null); }
  };
  const mm = String(Math.floor(secs / 60)).padStart(2, '0');
  const ss = String(secs % 60).padStart(2, '0');
  const btn = { paddingVertical: 14, borderRadius: 12, alignItems: 'center' as const, flexDirection: 'row' as const, justifyContent: 'center' as const, gap: 8 };

  return (
    <Modal transparent animationType="fade" visible onRequestClose={onLater}>
      <View style={{ flex: 1, backgroundColor: 'rgba(2,6,23,0.85)', justifyContent: 'center', padding: 20 }}>
        <View testID="trusted-ride-alert" style={{ backgroundColor: '#0F172A', borderRadius: 18, borderWidth: 2, borderColor: '#F59E0B', padding: 20 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Ionicons name="star" size={22} color="#F59E0B" />
            <Text style={{ color: '#F59E0B', fontSize: 13, fontWeight: '900', letterSpacing: 0.6 }}>TU CLIENTE TE PIDE UN TAXI</Text>
          </View>
          <Text style={{ color: '#F1F5F9', fontSize: 22, fontWeight: '900', marginTop: 10 }}>{ride.client_name || 'Cliente'}</Text>
          <Text style={{ color: '#E2E8F0', fontSize: 15, fontWeight: '700', marginTop: 12 }}>{ride.origin}</Text>
          <Text style={{ color: '#94A3B8', fontSize: 14, marginTop: 2 }}>→ {ride.destination}</Text>
          <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 6 }}>
            {ride.ride_type === 'asap' ? 'Lo antes posible' : new Date(ride.scheduled_at || '').toLocaleString('es-ES')} · {ride.passengers} pax
          </Text>
          <View style={{ backgroundColor: '#F59E0B22', borderRadius: 10, padding: 12, marginTop: 14, alignItems: 'center' }}>
            <Text style={{ color: '#FCD34D', fontSize: 12 }}>Solo para ti durante</Text>
            <Text testID="trusted-ride-countdown" style={{ color: '#F59E0B', fontSize: 34, fontWeight: '900' }}>{mm}:{ss}</Text>
            <Text style={{ color: '#94A3B8', fontSize: 11 }}>Después pasa al resto de taxistas</Text>
          </View>
          <TouchableOpacity testID="trusted-ride-accept" disabled={!!busy} onPress={() => run('accept', onAccept)} style={{ ...btn, backgroundColor: '#10B981', marginTop: 16 }}>
            {busy === 'accept' ? <ActivityIndicator color="#FFF" /> : <Ionicons name="checkmark-circle" size={20} color="#FFF" />}
            <Text style={{ color: '#FFF', fontWeight: '900', fontSize: 16 }}>Aceptar servicio</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="trusted-ride-release" disabled={!!busy} onPress={() => run('release', onRelease)} style={{ ...btn, borderWidth: 1, borderColor: '#EF4444', marginTop: 10 }}>
            {busy === 'release' && <ActivityIndicator color="#EF4444" />}
            <Text style={{ color: '#EF4444', fontWeight: '800' }}>No puedo: pasarlo al resto</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="trusted-ride-later" onPress={onLater} style={{ alignItems: 'center', paddingTop: 12 }}>
            <Text style={{ color: '#94A3B8', fontSize: 13 }}>Decidir luego (sigue en "Para mí")</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
};
