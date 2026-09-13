/**
 * EmisoraDriverSection — Driver-side of the Emisora (Uber-like) module.
 *
 * Renders inside the existing Reservations tab. Shows:
 *   - a "Generar QR" button that lets the taxista onboard clients into
 *     their circle (their scheduled reservations get pre-assigned).
 *   - a live list of rides currently reserved for this driver
 *     (dispatch_scope == "assigned").
 *   - a live list of open offers available to any driver online.
 *   - accept/start/complete controls with in-app sound + badge notifications
 *     for new rides while the tab is mounted.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import QRCode from 'react-qr-code';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Ride = {
  id: string;
  origin: string;
  destination: string;
  ride_type: 'asap' | 'scheduled';
  scheduled_at: string | null;
  status: 'pending' | 'accepted' | 'in_progress' | 'completed' | 'cancelled';
  dispatch_scope: 'assigned' | 'open';
  client_name: string;
  client_phone: string;
  passengers: number;
  notes: string | null;
  accepted_by_driver_id: string | null;
  accepted_by_driver_name: string | null;
  created_at: string;
};

type QrInfo = {
  token: string;
  url: string;
  driver_id: string;
  driver_name: string;
};

const notify = (msg: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    // eslint-disable-next-line no-alert
    window.alert(msg);
  }
};

// Short "ping" sound built with WebAudio so we don't ship an mp3.
const playPing = () => {
  if (Platform.OS !== 'web' || typeof window === 'undefined') return;
  try {
    const AudioCtx: any = (window as any).AudioContext || (window as any).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(660, ctx.currentTime + 0.18);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.4);
  } catch {
    // swallow
  }
};

export const EmisoraDriverSection: React.FC = () => {
  const [qrModalOpen, setQrModalOpen] = useState(false);
  const [qr, setQr] = useState<QrInfo | null>(null);
  const [qrBusy, setQrBusy] = useState(false);

  const [assigned, setAssigned] = useState<Ride[]>([]);
  const [offers, setOffers] = useState<Ride[]>([]);
  const [active, setActive] = useState<Ride[]>([]);
  const [loading, setLoading] = useState(false);

  // Track previously known ride ids so we can ping only when new ones arrive.
  const seenAssignedIds = useRef<Set<string>>(new Set());
  const seenOfferIds = useRef<Set<string>>(new Set());
  const firstLoad = useRef(true);

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  const openQr = async () => {
    setQrBusy(true);
    try {
      const r = await axios.post(`${API_BASE}/api/rides/driver/qr`, {}, { headers: await authHeaders() });
      // Build absolute URL for the QR content so it works when scanned outside the app.
      const origin = (typeof window !== 'undefined' ? window.location.origin : '');
      const finalUrl = r.data.url?.startsWith('http') ? r.data.url : `${origin}${r.data.url}`;
      setQr({ ...r.data, url: finalUrl });
      setQrModalOpen(true);
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo generar el QR');
    } finally {
      setQrBusy(false);
    }
  };

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const [aRes, oRes, actRes] = await Promise.all([
        axios.get(`${API_BASE}/api/rides/driver/assigned`, { headers }),
        axios.get(`${API_BASE}/api/rides/driver/offers`, { headers }),
        axios.get(`${API_BASE}/api/rides/driver/active`, { headers }),
      ]);
      const nextAssigned: Ride[] = aRes.data || [];
      const nextOffers: Ride[] = oRes.data || [];
      const nextActive: Ride[] = actRes.data || [];

      // In-app notification: ping when new rides appear (skip first load).
      if (!firstLoad.current) {
        const newAssigned = nextAssigned.filter(r => !seenAssignedIds.current.has(r.id));
        const newOffers = nextOffers.filter(r => !seenOfferIds.current.has(r.id));
        if (newAssigned.length > 0 || newOffers.length > 0) {
          playPing();
        }
      }
      seenAssignedIds.current = new Set(nextAssigned.map(r => r.id));
      seenOfferIds.current = new Set(nextOffers.map(r => r.id));
      firstLoad.current = false;

      setAssigned(nextAssigned);
      setOffers(nextOffers);
      setActive(nextActive);
    } catch {
      // Silent; user might not be logged in yet
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  const totalBadge = assigned.length + offers.length;

  const accept = async (id: string) => {
    try {
      await axios.post(`${API_BASE}/api/rides/rides/${id}/accept`, {}, { headers: await authHeaders() });
      await refresh();
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo aceptar');
    }
  };
  const startRide = async (id: string) => {
    try {
      await axios.post(`${API_BASE}/api/rides/rides/${id}/start`, {}, { headers: await authHeaders() });
      await refresh();
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo iniciar');
    }
  };
  const complete = async (id: string) => {
    try {
      await axios.post(`${API_BASE}/api/rides/rides/${id}/complete`, {}, { headers: await authHeaders() });
      await refresh();
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo completar');
    }
  };
  const releaseAssigned = async (id: string) => {
    try {
      await axios.post(`${API_BASE}/api/rides/rides/${id}/reject`, {}, { headers: await authHeaders() });
      await refresh();
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo liberar');
    }
  };

  const RideCard = ({ r, variant }: { r: Ride; variant: 'assigned' | 'offer' | 'active' }) => {
    const isAsap = r.ride_type === 'asap';
    const when = isAsap
      ? 'ASAP'
      : (r.scheduled_at ? new Date(r.scheduled_at).toLocaleString('es-ES', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '');
    return (
      <View
        testID={`emisora-driver-ride-${r.id}`}
        style={{
          backgroundColor: '#0F172A',
          borderRadius: 10,
          padding: 12,
          marginBottom: 8,
          borderWidth: 1,
          borderColor: isAsap ? '#F59E0B' : '#334155',
        }}
      >
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            {isAsap && <Ionicons name="flash" size={14} color="#F59E0B" />}
            <Text style={{ color: isAsap ? '#F59E0B' : '#94A3B8', fontWeight: '800', fontSize: 12 }}>{when}</Text>
          </View>
          <Text style={{ color: '#94A3B8', fontSize: 11 }}>{r.passengers} pax</Text>
        </View>
        <Text style={{ color: '#F1F5F9', fontWeight: '700' }}>{r.origin}</Text>
        <Text style={{ color: '#94A3B8', fontSize: 12 }}>→ {r.destination}</Text>
        <Text style={{ color: '#60A5FA', fontSize: 12, marginTop: 4 }}>
          <Ionicons name="person" size={11} /> {r.client_name} · {r.client_phone}
        </Text>

        <View style={{ flexDirection: 'row', gap: 8, marginTop: 10 }}>
          {variant !== 'active' && (
            <TouchableOpacity
              onPress={() => accept(r.id)}
              style={{ flex: 1, backgroundColor: '#10B981', paddingVertical: 8, borderRadius: 8, alignItems: 'center' }}
              testID={`emisora-driver-accept-${r.id}`}
            >
              <Text style={{ color: '#FFF', fontWeight: '800', fontSize: 12 }}>Aceptar</Text>
            </TouchableOpacity>
          )}
          {variant === 'assigned' && (
            <TouchableOpacity
              onPress={() => releaseAssigned(r.id)}
              style={{ flex: 1, backgroundColor: '#1E293B', paddingVertical: 8, borderRadius: 8, alignItems: 'center', borderWidth: 1, borderColor: '#EF4444' }}
              testID={`emisora-driver-release-${r.id}`}
            >
              <Text style={{ color: '#EF4444', fontWeight: '700', fontSize: 12 }}>Liberar</Text>
            </TouchableOpacity>
          )}
          {variant === 'active' && r.status === 'accepted' && (
            <TouchableOpacity
              onPress={() => startRide(r.id)}
              style={{ flex: 1, backgroundColor: '#8B5CF6', paddingVertical: 8, borderRadius: 8, alignItems: 'center' }}
              testID={`emisora-driver-start-${r.id}`}
            >
              <Text style={{ color: '#FFF', fontWeight: '800', fontSize: 12 }}>Iniciar</Text>
            </TouchableOpacity>
          )}
          {variant === 'active' && r.status === 'in_progress' && (
            <TouchableOpacity
              onPress={() => complete(r.id)}
              style={{ flex: 1, backgroundColor: '#10B981', paddingVertical: 8, borderRadius: 8, alignItems: 'center' }}
              testID={`emisora-driver-complete-${r.id}`}
            >
              <Text style={{ color: '#FFF', fontWeight: '800', fontSize: 12 }}>Finalizar</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    );
  };

  return (
    <View style={{ backgroundColor: '#1E293B', borderRadius: 14, padding: 14, marginTop: 8, marginBottom: 16, borderWidth: 1, borderColor: '#334155' }} testID="emisora-driver-section">
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Ionicons name="radio" size={18} color="#F59E0B" />
          <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 15 }}>Emisora</Text>
          {totalBadge > 0 && (
            <View style={{ backgroundColor: '#EF4444', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 }}>
              <Text style={{ color: '#FFF', fontSize: 11, fontWeight: '800' }} testID="emisora-driver-badge">{totalBadge}</Text>
            </View>
          )}
        </View>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <TouchableOpacity onPress={refresh} disabled={loading} style={{ padding: 6 }} testID="emisora-driver-refresh">
            <Ionicons name={loading ? 'sync' : 'refresh'} size={18} color="#94A3B8" />
          </TouchableOpacity>
          <TouchableOpacity
            onPress={openQr}
            disabled={qrBusy}
            style={{ backgroundColor: '#F59E0B', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, flexDirection: 'row', alignItems: 'center', gap: 4 }}
            testID="emisora-driver-qr-btn"
          >
            {qrBusy ? <ActivityIndicator color="#0F172A" size="small" /> : <Ionicons name="qr-code" size={16} color="#0F172A" />}
            <Text style={{ color: '#0F172A', fontWeight: '800', fontSize: 12 }}>QR clientes</Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* Active rides section */}
      {active.length > 0 && (
        <View style={{ marginBottom: 10 }}>
          <Text style={{ color: '#8B5CF6', fontWeight: '800', fontSize: 12, marginBottom: 6 }}>EN CURSO ({active.length})</Text>
          {active.map(r => <RideCard key={r.id} r={r} variant="active" />)}
        </View>
      )}

      {/* Assigned to me */}
      <Text style={{ color: '#3B82F6', fontWeight: '800', fontSize: 12, marginBottom: 6 }}>
        RESERVADAS PARA MÍ {assigned.length > 0 ? `(${assigned.length})` : ''}
      </Text>
      {assigned.length === 0 && (
        <Text style={{ color: '#64748B', fontStyle: 'italic', fontSize: 12, marginBottom: 8 }}>Nada por ahora.</Text>
      )}
      {assigned.map(r => <RideCard key={r.id} r={r} variant="assigned" />)}

      {/* Open offers */}
      <Text style={{ color: '#F59E0B', fontWeight: '800', fontSize: 12, marginTop: 6, marginBottom: 6 }}>
        OFERTAS ABIERTAS {offers.length > 0 ? `(${offers.length})` : ''}
      </Text>
      {offers.length === 0 && (
        <Text style={{ color: '#64748B', fontStyle: 'italic', fontSize: 12 }}>Sin ofertas ahora mismo.</Text>
      )}
      {offers.map(r => <RideCard key={r.id} r={r} variant="offer" />)}

      {/* QR modal */}
      <Modal visible={qrModalOpen} transparent animationType="fade" onRequestClose={() => setQrModalOpen(false)}>
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.85)', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <View style={{ backgroundColor: '#0F172A', borderRadius: 16, padding: 22, alignItems: 'center', maxWidth: 380, width: '100%' }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', width: '100%', alignItems: 'center', marginBottom: 14 }}>
              <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 18 }}>Tu QR de clientes</Text>
              <TouchableOpacity onPress={() => setQrModalOpen(false)} testID="emisora-driver-qr-close">
                <Ionicons name="close-circle" size={28} color="#94A3B8" />
              </TouchableOpacity>
            </View>
            {qr ? (
              <>
                <View style={{ backgroundColor: '#FFFFFF', padding: 14, borderRadius: 12, marginBottom: 12 }}>
                  <QRCode value={qr.url} size={220} />
                </View>
                <Text style={{ color: '#94A3B8', textAlign: 'center', fontSize: 13, marginBottom: 4 }}>
                  Enséñale este código a tu cliente. Al escanearlo se registrará asociado a tu cuenta y sus reservas te llegarán primero (hasta 6h antes del servicio).
                </Text>
                <Text style={{ color: '#64748B', fontSize: 11, marginTop: 6 }} selectable>{qr.url}</Text>
              </>
            ) : (
              <ActivityIndicator color="#F59E0B" />
            )}
          </View>
        </View>
      </Modal>
    </View>
  );
};

export default EmisoraDriverSection;
