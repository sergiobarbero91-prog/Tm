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
import { RideHistoryPanel } from './RideHistoryPanel';
import { RatingBadge, useUserRatings } from './RatingBadge';
import { RatePrompt, loadPromptedRides } from './RatePrompt';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Ride = {
  id: string;
  origin: string;
  destination: string;
  ride_type: 'asap' | 'scheduled';
  scheduled_at: string | null;
  status: 'pending' | 'accepted' | 'in_progress' | 'completed' | 'cancelled';
  dispatch_scope: 'assigned' | 'open';
  client_id: string;
  client_name: string;
  client_phone: string;
  passengers: number;
  notes: string | null;
  accepted_by_driver_id: string | null;
  accepted_by_driver_name: string | null;
  accepted_by_driver_phone: string | null;
  created_at: string;
  distance_km?: number | null;
  origin_lat?: number | null;
  origin_lon?: number | null;
};

const openTel = (phone: string | null | undefined) => {
  if (!phone) return;
  const clean = phone.replace(/\s+/g, '');
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.location.href = `tel:${clean}`;
  } else {
    // React Native fallback via Linking (already available via expo-linking)
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const Linking = require('react-native').Linking;
      Linking.openURL(`tel:${clean}`);
    } catch {
      // ignore
    }
  }
};

const openExternalUrl = (url: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Linking = require('react-native').Linking;
    Linking.openURL(url);
  } catch {
    /* ignore */
  }
};

const googleMapsUrl = (r: { origin: string; origin_lat?: number | null; origin_lon?: number | null }): string => {
  const dest =
    r.origin_lat != null && r.origin_lon != null
      ? `${r.origin_lat},${r.origin_lon}`
      : r.origin;
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(dest)}&travelmode=driving`;
};

const googleMapsToDestUrl = (r: { destination: string }): string =>
  `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(r.destination)}&travelmode=driving`;

const wazeUrl = (r: { origin: string; origin_lat?: number | null; origin_lon?: number | null }): string => {
  if (r.origin_lat != null && r.origin_lon != null) {
    return `https://waze.com/ul?ll=${r.origin_lat},${r.origin_lon}&navigate=yes`;
  }
  return `https://waze.com/ul?q=${encodeURIComponent(r.origin)}&navigate=yes`;
};

const wazeToDestUrl = (r: { destination: string }): string =>
  `https://waze.com/ul?q=${encodeURIComponent(r.destination)}&navigate=yes`;

type QrInfo = {
  token: string;
  url: string;
  driver_id: string;
  driver_name: string;
  verification_code: string;
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
  const [historyOpen, setHistoryOpen] = useState(false);

  const [assigned, setAssigned] = useState<Ride[]>([]);
  const [offers, setOffers] = useState<Ride[]>([]);
  const [active, setActive] = useState<Ride[]>([]);
  const [loading, setLoading] = useState(false);

  // Post-ride rating prompt state (fires after driver taps "Finalizar")
  const [ratePromptRide, setRatePromptRide] = useState<Ride | null>(null);
  const promptedRidesRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    loadPromptedRides().then(s => {
      promptedRidesRef.current = s;
    });
  }, []);

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

  // Also keep the ride type + destination + a distance hint so drivers can
  // triage quickly.
  const driverPosRef = useRef<{ lat: number; lon: number } | null>(null);

  // Ask the browser for the driver's location once on mount and refresh it
  // opportunistically. Failure is silent — offers just fall back to the
  // default chronological order.
  useEffect(() => {
    if (Platform.OS !== 'web' || typeof navigator === 'undefined' || !navigator.geolocation) return;
    const grab = () => {
      navigator.geolocation.getCurrentPosition(
        pos => {
          driverPosRef.current = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        },
        () => { /* silent */ },
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 },
      );
    };
    grab();
    const t = setInterval(grab, 60000);
    return () => clearInterval(t);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const pos = driverPosRef.current;
      const [aRes, oRes, actRes] = await Promise.all([
        axios.get(`${API_BASE}/api/rides/driver/assigned`, { headers }),
        axios.get(`${API_BASE}/api/rides/driver/offers`, {
          headers,
          params: pos ? { lat: pos.lat, lon: pos.lon } : undefined,
        }),
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

  // Fetch client ratings for every visible ride so we can display the badge.
  const clientIds = React.useMemo(
    () => [...assigned, ...offers, ...active].map(r => r.client_id),
    [assigned, offers, active],
  );
  const ratings = useUserRatings(clientIds, 'token');

  const totalBadge = assigned.length + offers.length;

  const accept = async (id: string) => {
    try {
      const r = await axios.post(`${API_BASE}/api/rides/rides/${id}/accept`, {}, { headers: await authHeaders() });
      await refresh();
      // Show a very visible reminder + immediate call option
      const clientName = r.data?.client_name || 'el cliente';
      const clientPhone = r.data?.client_phone || '';
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        const call = window.confirm(
          `✅ Servicio aceptado.\n\nLlama a ${clientName} (${clientPhone}) ahora mismo para confirmar la recogida.\n\n¿Quieres marcar su número?`
        );
        if (call && clientPhone) {
          openTel(clientPhone);
        }
      } else {
        notify(`Servicio aceptado. Llama a ${clientName} al ${clientPhone} para confirmar la recogida.`);
      }
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
      const r = await axios.post(`${API_BASE}/api/rides/rides/${id}/complete`, {}, { headers: await authHeaders() });
      const ride = r.data as Ride;
      await refresh();
      if (ride && !promptedRidesRef.current.has(ride.id)) {
        setRatePromptRide(ride);
      }
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
            {typeof r.distance_km === 'number' && (
              <View
                testID={`emisora-driver-distance-${r.id}`}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, backgroundColor: '#0F172A', borderWidth: 1, borderColor: '#10B981' }}
              >
                <Ionicons name="navigate" size={10} color="#10B981" />
                <Text style={{ color: '#10B981', fontSize: 10, fontWeight: '800' }}>
                  {r.distance_km < 1 ? `${Math.round(r.distance_km * 1000)} m` : `${r.distance_km.toFixed(1)} km`}
                </Text>
              </View>
            )}
          </View>
          <Text style={{ color: '#94A3B8', fontSize: 11 }}>{r.passengers} pax</Text>
        </View>
        <Text style={{ color: '#F1F5F9', fontWeight: '700' }}>{r.origin}</Text>
        <Text style={{ color: '#94A3B8', fontSize: 12 }}>→ {r.destination}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
          <Text style={{ color: '#60A5FA', fontSize: 12 }}>
            <Ionicons name="person" size={11} /> {r.client_name} · {r.client_phone}
          </Text>
          <RatingBadge rating={ratings[r.client_id]} testID={`emisora-driver-client-rating-${r.id}`} />
        </View>

        {/* Persistent "call client" reminder when the driver has accepted the ride */}
        {variant === 'active' && r.client_phone ? (
          <View
            testID={`emisora-driver-call-cta-${r.id}`}
            style={{
              marginTop: 10,
              backgroundColor: '#064E3B',
              borderRadius: 10,
              borderWidth: 1,
              borderColor: '#10B981',
              padding: 10,
            }}
          >
            <Text style={{ color: '#6EE7B7', fontWeight: '800', fontSize: 12, marginBottom: 6 }}>
              📞 Llama al cliente para confirmar la recogida
            </Text>
            <TouchableOpacity
              onPress={() => openTel(r.client_phone)}
              style={{ backgroundColor: '#10B981', paddingVertical: 10, borderRadius: 8, alignItems: 'center', flexDirection: 'row', justifyContent: 'center', gap: 6 }}
              testID={`emisora-driver-call-${r.id}`}
            >
              <Ionicons name="call" size={16} color="#FFF" />
              <Text style={{ color: '#FFF', fontWeight: '800' }}>Llamar a {r.client_name.split(' ')[0] || 'cliente'} · {r.client_phone}</Text>
            </TouchableOpacity>
          </View>
        ) : null}

        {/* Route to client — open Google Maps or Waze with pickup coords */}
        <View style={{ flexDirection: 'row', gap: 8, marginTop: 10 }}>
          <TouchableOpacity
            onPress={() => openExternalUrl(googleMapsUrl(r))}
            style={{ flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 8, backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#3B82F6' }}
            testID={`emisora-driver-gmaps-${r.id}`}
          >
            <Ionicons name="map" size={14} color="#3B82F6" />
            <Text style={{ color: '#3B82F6', fontWeight: '800', fontSize: 12 }}>Google Maps</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => openExternalUrl(wazeUrl(r))}
            style={{ flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 8, backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#8B5CF6' }}
            testID={`emisora-driver-waze-${r.id}`}
          >
            <Ionicons name="navigate-circle" size={14} color="#8B5CF6" />
            <Text style={{ color: '#8B5CF6', fontWeight: '800', fontSize: 12 }}>Waze</Text>
          </TouchableOpacity>
        </View>

        {/* Route to DESTINATION — only for in-progress rides */}
        {r.status === 'in_progress' && (
          <>
            <Text style={{ color: '#64748B', fontSize: 10, marginTop: 8, textAlign: 'center' }}>
              Ir al destino
            </Text>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 4 }}>
              <TouchableOpacity
                onPress={() => openExternalUrl(googleMapsToDestUrl(r))}
                style={{ flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 8, backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#10B981' }}
                testID={`emisora-driver-gmaps-dest-${r.id}`}
              >
                <Ionicons name="flag" size={14} color="#10B981" />
                <Text style={{ color: '#10B981', fontWeight: '800', fontSize: 12 }}>Maps destino</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => openExternalUrl(wazeToDestUrl(r))}
                style={{ flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 8, backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#F59E0B' }}
                testID={`emisora-driver-waze-dest-${r.id}`}
              >
                <Ionicons name="flag-outline" size={14} color="#F59E0B" />
                <Text style={{ color: '#F59E0B', fontWeight: '800', fontSize: 12 }}>Waze destino</Text>
              </TouchableOpacity>
            </View>
          </>
        )}

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
            onPress={() => setHistoryOpen(true)}
            style={{ backgroundColor: '#0F172A', paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderColor: '#334155' }}
            testID="emisora-driver-history-btn"
          >
            <Ionicons name="time-outline" size={16} color="#94A3B8" />
            <Text style={{ color: '#94A3B8', fontWeight: '800', fontSize: 12 }}>Historial</Text>
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

      {/* History modal */}
      <Modal visible={historyOpen} transparent animationType="fade" onRequestClose={() => setHistoryOpen(false)}>
        <View style={{ flex: 1, backgroundColor: '#0009', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 560, backgroundColor: '#0F172A', borderRadius: 14, borderWidth: 1, borderColor: '#334155' }}>
            <RideHistoryPanel viewerRole="driver" onClose={() => setHistoryOpen(false)} />
          </View>
        </View>
      </Modal>

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

      {/* Post-ride rating prompt */}
      <RatePrompt
        visible={!!ratePromptRide}
        rideId={ratePromptRide?.id || null}
        counterpartLabel={ratePromptRide?.client_name || 'el cliente'}
        tokenKey="token"
        onClose={rated => {
          if (ratePromptRide) {
            promptedRidesRef.current.add(ratePromptRide.id);
          }
          setRatePromptRide(null);
          if (rated) refresh();
        }}
      />

      {/* QR modal */}
      <Modal visible={qrModalOpen} transparent animationType="fade" onRequestClose={() => setQrModalOpen(false)}>
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.85)', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <View style={{ backgroundColor: '#0F172A', borderRadius: 16, padding: 22, alignItems: 'center', maxWidth: 400, width: '100%' }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', width: '100%', alignItems: 'center', marginBottom: 14 }}>
              <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 18 }}>Alta de cliente</Text>
              <TouchableOpacity onPress={() => setQrModalOpen(false)} testID="emisora-driver-qr-close">
                <Ionicons name="close-circle" size={28} color="#94A3B8" />
              </TouchableOpacity>
            </View>
            {qr ? (
              <>
                <View style={{ backgroundColor: '#FFFFFF', padding: 14, borderRadius: 12, marginBottom: 14 }}>
                  <QRCode value={qr.url} size={200} />
                </View>
                <Text style={{ color: '#94A3B8', textAlign: 'center', fontSize: 12, marginBottom: 10 }}>
                  1. El cliente escanea este QR con la cámara.
                </Text>
                <Text style={{ color: '#94A3B8', textAlign: 'center', fontSize: 12, marginBottom: 6 }}>
                  2. Le dictas este código para verificarlo:
                </Text>
                <View style={{ backgroundColor: '#F59E0B', paddingHorizontal: 24, paddingVertical: 14, borderRadius: 12, marginBottom: 14 }}>
                  <Text
                    testID="emisora-driver-verification-code"
                    style={{ color: '#0F172A', fontSize: 34, fontWeight: '900', letterSpacing: 8 }}
                    selectable
                  >
                    {qr.verification_code}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={async () => {
                    setQrBusy(true);
                    try {
                      const r = await axios.post(`${API_BASE}/api/rides/driver/qr/rotate`, {}, { headers: await authHeaders() });
                      const origin = (typeof window !== 'undefined' ? window.location.origin : '');
                      const finalUrl = r.data.url?.startsWith('http') ? r.data.url : `${origin}${r.data.url}`;
                      setQr({ ...r.data, url: finalUrl });
                    } catch (e: any) {
                      notify(e?.response?.data?.detail || 'No se pudo rotar el código');
                    } finally {
                      setQrBusy(false);
                    }
                  }}
                  disabled={qrBusy}
                  style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 8, paddingHorizontal: 12, borderRadius: 8, borderWidth: 1, borderColor: '#F59E0B' }}
                  testID="emisora-driver-rotate-code"
                >
                  <Ionicons name="refresh" size={14} color="#F59E0B" />
                  <Text style={{ color: '#F59E0B', fontWeight: '700', fontSize: 12 }}>Generar nuevo código</Text>
                </TouchableOpacity>
                <Text style={{ color: '#64748B', fontSize: 10, marginTop: 12, textAlign: 'center' }} selectable>{qr.url}</Text>
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
