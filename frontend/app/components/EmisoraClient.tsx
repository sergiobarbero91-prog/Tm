/**
 * EmisoraClient — full-screen experience for the "Cliente" role.
 *
 * Handles OTP-based auth (dev mode accepts 123456 while Twilio creds are
 * empty), ride request (ASAP or scheduled) and live status of the client's
 * own rides. Isolated in a component to avoid bloating index.tsx further.
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  TextInput,
  ScrollView,
  ActivityIndicator,
  Platform,
  Modal,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { calculateEstimatedFare, type FareResult } from '../utils/fareEstimator';
import { DateTimePicker } from './DateTimePicker';
import { RideHistoryPanel } from './RideHistoryPanel';
import { RatingBadge, useUserRatings } from './RatingBadge';
import { AddressAutocomplete } from './AddressAutocomplete';
import { RatePrompt, loadPromptedRides } from './RatePrompt';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const CLIENT_TOKEN_KEY = 'emisora_client_token';
const CLIENT_INFO_KEY = 'emisora_client_info';

type ClientInfo = {
  id: string;
  phone: string;
  first_name: string;
  last_name: string;
  email?: string | null;
  associated_driver_id: string | null;
};

type Ride = {
  id: string;
  origin: string;
  destination: string;
  ride_type: 'asap' | 'scheduled';
  scheduled_at: string | null;
  status: 'pending' | 'accepted' | 'in_progress' | 'completed' | 'cancelled';
  dispatch_scope: 'assigned' | 'open';
  accepted_by_driver_id: string | null;
  accepted_by_driver_name: string | null;
  accepted_by_driver_phone: string | null;
  passengers: number;
  created_at: string;
};

const notify = (msg: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    // eslint-disable-next-line no-alert
    window.alert(msg);
  }
};

const openTel = (phone: string | null | undefined) => {
  if (!phone) return;
  const clean = phone.replace(/\s+/g, '');
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.location.href = `tel:${clean}`;
  } else {
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const Linking = require('react-native').Linking;
      Linking.openURL(`tel:${clean}`);
    } catch {
      // ignore
    }
  }
};

export const EmisoraClient: React.FC<{ onBack: () => void; qrToken?: string | null }> = ({ onBack, qrToken }) => {
  const [loading, setLoading] = useState(true);
  const [client, setClient] = useState<ClientInfo | null>(null);
  const [associatedDriverName, setAssociatedDriverName] = useState<string | null>(null);

  // Auth flow state (driver-code, NOT SMS)
  const [authMode, setAuthMode] = useState<'signup' | 'login'>('signup');
  const [phone, setPhone] = useState('+34');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [password, setPassword] = useState('');
  const [signupEmail, setSignupEmail] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  // Ride creation state
  const [origin, setOrigin] = useState('');
  const [destination, setDestination] = useState('');
  const [originCoords, setOriginCoords] = useState<{ lat: number; lon: number } | null>(null);
  const [rideType, setRideType] = useState<'asap' | 'scheduled'>('asap');
  const [schedDate, setSchedDate] = useState('');
  const [schedTime, setSchedTime] = useState('');
  const [passengers, setPassengers] = useState('1');
  const [creating, setCreating] = useState(false);

  const [rides, setRides] = useState<Ride[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  // Post-ride rating prompt
  const [ratePromptRide, setRatePromptRide] = useState<Ride | null>(null);
  const promptedRidesRef = React.useRef<Set<string>>(new Set());
  const prevRideStatusRef = React.useRef<Map<string, string>>(new Map());
  const ratePromptFirstLoadRef = React.useRef(true);
  React.useEffect(() => {
    loadPromptedRides().then(s => {
      promptedRidesRef.current = s;
    });
  }, []);

  // Estimated fare (recomputed on-demand by pressing "Ver precio")
  const [fareEstimate, setFareEstimate] = useState<FareResult | null>(null);
  const [fareLoading, setFareLoading] = useState(false);
  const [fareError, setFareError] = useState<string | null>(null);

  // Client profile edit modal
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileForm, setProfileForm] = useState({ first_name: '', last_name: '', phone: '', email: '', new_password: '' });
  const [profileBusy, setProfileBusy] = useState(false);

  // Frequent addresses (one-tap re-use)
  const [frequentAddresses, setFrequentAddresses] = useState<Array<{ address: string; uses: number }>>([]);

  // Ride history modal
  const [historyOpen, setHistoryOpen] = useState(false);

  // Restore session on mount
  useEffect(() => {
    (async () => {
      try {
        const tk = await AsyncStorage.getItem(CLIENT_TOKEN_KEY);
        const raw = await AsyncStorage.getItem(CLIENT_INFO_KEY);
        if (tk && raw) {
          setClient(JSON.parse(raw));
        }
      } catch {}
      setLoading(false);
    })();
  }, []);

  // Look up associated driver name from QR (before login)
  useEffect(() => {
    if (!qrToken) return;
    (async () => {
      try {
        const r = await axios.get(`${API_BASE}/api/rides/qr/${qrToken}/info`);
        setAssociatedDriverName(r.data?.driver_name || null);
      } catch {}
    })();
  }, [qrToken]);

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem(CLIENT_TOKEN_KEY);
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  const refreshRides = useCallback(async () => {
    if (!client) return;
    setRefreshing(true);
    try {
      const r = await axios.get(`${API_BASE}/api/rides/rides/mine`, { headers: await authHeaders() });
      const nextRides: Ride[] = r.data || [];
      // Detect rides that JUST completed and were not yet prompted for rating.
      // Skip the very first refresh so we don't ambush the user with historical rides.
      if (!ratePromptFirstLoadRef.current && !ratePromptRide) {
        const prev = prevRideStatusRef.current;
        const justCompleted = nextRides.find(nr => {
          if (nr.status !== 'completed') return false;
          if (promptedRidesRef.current.has(nr.id)) return false;
          const prevStatus = prev.get(nr.id);
          return prevStatus && prevStatus !== 'completed';
        });
        if (justCompleted) setRatePromptRide(justCompleted);
      }
      const nextMap = new Map<string, string>();
      nextRides.forEach(nr => nextMap.set(nr.id, nr.status));
      prevRideStatusRef.current = nextMap;
      ratePromptFirstLoadRef.current = false;
      setRides(nextRides);
    } catch (e) {
      // token might have expired
    } finally {
      setRefreshing(false);
    }
  }, [client, authHeaders, ratePromptRide]);

  const refreshFrequentAddresses = useCallback(async () => {
    if (!client) return;
    try {
      const r = await axios.get(`${API_BASE}/api/rides/client/frequent-addresses?limit=6`, { headers: await authHeaders() });
      setFrequentAddresses(r.data || []);
    } catch {
      /* silent */
    }
  }, [client, authHeaders]);

  useEffect(() => {
    refreshRides();
    refreshFrequentAddresses();
    if (!client) return;
    const t = setInterval(refreshRides, 15000);
    return () => clearInterval(t);
  }, [client, refreshRides, refreshFrequentAddresses]);

  // Fetch ratings of every taxista who accepted one of my rides.
  const driverIds = React.useMemo(
    () => rides.map(r => r.accepted_by_driver_id).filter((x): x is string => !!x),
    [rides],
  );
  const driverRatings = useUserRatings(driverIds, CLIENT_TOKEN_KEY);

  // Fetch the CLIENT's own rating to show in their profile modal.
  const myIds = React.useMemo(() => (client?.id ? [client.id] : []), [client?.id]);
  const myRatingsMap = useUserRatings(myIds, CLIENT_TOKEN_KEY);
  const myRating = client?.id ? myRatingsMap[client.id] : undefined;

  const handleAuthenticate = async () => {
    setAuthError(null);
    if (!qrToken) {
      setAuthError('Necesitas escanear el QR de un taxista para registrarte. Pídele al taxista que te lo enseñe.');
      return;
    }
    if (!phone.startsWith('+') || phone.length < 8) {
      setAuthError('Introduce tu teléfono con prefijo (ej. +34611223344)');
      return;
    }
    if (!firstName || !lastName) {
      setAuthError('Escribe tu nombre y apellido');
      return;
    }
    if (!/^\d{6}$/.test(verificationCode)) {
      setAuthError('El código son 6 dígitos que verás en la pantalla del taxista');
      return;
    }
    if (password && password.length < 4) {
      setAuthError('La contraseña debe tener al menos 4 caracteres');
      return;
    }
    setAuthBusy(true);
    try {
      const r = await axios.post(`${API_BASE}/api/rides/client/authenticate`, {
        phone,
        first_name: firstName,
        last_name: lastName,
        qr_token: qrToken,
        verification_code: verificationCode,
        password: password || null,
        email: signupEmail || null,
      });
      await AsyncStorage.setItem(CLIENT_TOKEN_KEY, r.data.access_token);
      await AsyncStorage.setItem(CLIENT_INFO_KEY, JSON.stringify(r.data.client));
      setClient(r.data.client);
    } catch (e: any) {
      setAuthError(e?.response?.data?.detail || 'No se pudo iniciar sesión');
    } finally {
      setAuthBusy(false);
    }
  };

  const handleLogin = async () => {
    setAuthError(null);
    if (!phone.startsWith('+') || phone.length < 8) {
      setAuthError('Introduce tu teléfono con prefijo (ej. +34611223344)');
      return;
    }
    if (!password || password.length < 4) {
      setAuthError('Escribe tu contraseña');
      return;
    }
    setAuthBusy(true);
    try {
      const r = await axios.post(`${API_BASE}/api/rides/client/login`, { phone, password });
      await AsyncStorage.setItem(CLIENT_TOKEN_KEY, r.data.access_token);
      await AsyncStorage.setItem(CLIENT_INFO_KEY, JSON.stringify(r.data.client));
      setClient(r.data.client);
    } catch (e: any) {
      setAuthError(e?.response?.data?.detail || 'No se pudo iniciar sesión');
    } finally {
      setAuthBusy(false);
    }
  };

  // If the user landed via a driver's QR, default to signup mode.
  useEffect(() => {
    if (qrToken) setAuthMode('signup');
  }, [qrToken]);

  const handleLogout = async () => {
    await AsyncStorage.multiRemove([CLIENT_TOKEN_KEY, CLIENT_INFO_KEY]);
    setClient(null);
    setRides([]);
    setVerificationCode('');
    setPassword('');
    setPhone('+34');
    setFirstName('');
    setLastName('');
  };

  const handleCreateRide = async () => {
    if (!origin.trim() || !destination.trim()) {
      notify('Rellena origen y destino');
      return;
    }
    if (rideType === 'scheduled' && (!schedDate || !schedTime)) {
      notify('Indica fecha y hora del servicio');
      return;
    }
    setCreating(true);
    try {
      const body: any = {
        origin: origin.trim(),
        destination: destination.trim(),
        ride_type: rideType,
        passengers: parseInt(passengers, 10) || 1,
      };
      if (originCoords) {
        body.origin_lat = originCoords.lat;
        body.origin_lon = originCoords.lon;
      }
      if (rideType === 'scheduled') {
        // Compose ISO in local time; backend interprets as UTC (naive → utc)
        const iso = new Date(`${schedDate}T${schedTime}:00`).toISOString();
        body.scheduled_at = iso;
      }
      await axios.post(`${API_BASE}/api/rides/rides`, body, { headers: await authHeaders() });
      setOrigin('');
      setDestination('');
      setOriginCoords(null);
      setSchedDate('');
      setSchedTime('');
      setPassengers('1');
      await refreshRides();
      await refreshFrequentAddresses();
      notify('Servicio solicitado correctamente');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo crear el servicio');
    } finally {
      setCreating(false);
    }
  };

  const openProfile = () => {
    if (!client) return;
    setProfileForm({
      first_name: client.first_name || '',
      last_name: client.last_name || '',
      phone: client.phone || '',
      email: client.email || '',
      new_password: '',
    });
    setProfileOpen(true);
  };

  const saveProfile = async () => {
    if (!client) return;
    setProfileBusy(true);
    try {
      const payload: any = {
        first_name: profileForm.first_name.trim(),
        last_name: profileForm.last_name.trim(),
        phone: profileForm.phone.trim(),
        email: profileForm.email.trim() || null,
      };
      if (profileForm.new_password.trim()) {
        if (profileForm.new_password.trim().length < 4) {
          notify('La contraseña debe tener al menos 4 caracteres');
          setProfileBusy(false);
          return;
        }
        payload.new_password = profileForm.new_password.trim();
      }
      const r = await axios.put(`${API_BASE}/api/rides/client/profile`, payload, { headers: await authHeaders() });
      const updated: ClientInfo = { ...client, ...r.data };
      setClient(updated);
      await AsyncStorage.setItem(CLIENT_INFO_KEY, JSON.stringify(updated));
      setProfileOpen(false);
      notify('Perfil actualizado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo guardar');
    } finally {
      setProfileBusy(false);
    }
  };


  const handleCancel = async (id: string, isAccepted: boolean) => {
    const msg = isAccepted
      ? 'Un taxista ya aceptó tu servicio. Si cancelas ahora, se le avisará. ¿Cancelar de todas formas?'
      : '¿Cancelar este servicio?';
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      // eslint-disable-next-line no-alert
      if (!window.confirm(msg)) return;
    }
    try {
      await axios.post(`${API_BASE}/api/rides/rides/${id}/cancel`, {}, { headers: await authHeaders() });
      await refreshRides();
      notify('Servicio cancelado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo cancelar');
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: '#0F172A', alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator size="large" color="#F59E0B" />
      </View>
    );
  }

  // Header used across all client screens
  const Header = ({ title, right }: { title: string; right?: React.ReactNode }) => (
    <View style={{ flexDirection: 'row', alignItems: 'center', padding: 16, borderBottomWidth: 1, borderBottomColor: '#1E293B', backgroundColor: '#0F172A' }}>
      <TouchableOpacity onPress={onBack} style={{ marginRight: 12 }} testID="emisora-back-btn">
        <Ionicons name="arrow-back" size={22} color="#F1F5F9" />
      </TouchableOpacity>
      <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 18, flex: 1 }}>{title}</Text>
      {right}
    </View>
  );

  // ─────────── UNAUTHENTICATED ───────────
  if (!client) {
    const hasQr = !!qrToken;
    return (
      <View style={{ flex: 1, backgroundColor: '#0F172A' }}>
        <Header title="Solicitar taxi" />
        <ScrollView contentContainerStyle={{ padding: 20 }}>
          <View style={{ alignItems: 'center', marginBottom: 18 }}>
            <View style={{ width: 68, height: 68, borderRadius: 34, backgroundColor: '#F59E0B', alignItems: 'center', justifyContent: 'center', marginBottom: 10 }}>
              <Ionicons name="car-sport" size={36} color="#0F172A" />
            </View>
            <Text style={{ color: '#F1F5F9', fontSize: 22, fontWeight: '800' }}>Pide tu taxi</Text>
          </View>

          {/* Segmented switch: Ya tengo cuenta / Primera vez */}
          <View style={{ flexDirection: 'row', backgroundColor: '#1E293B', borderRadius: 12, padding: 4, marginBottom: 18 }}>
            <TouchableOpacity
              onPress={() => { setAuthMode('login'); setAuthError(null); }}
              style={{ flex: 1, backgroundColor: authMode === 'login' ? '#F59E0B' : 'transparent', borderRadius: 8, paddingVertical: 10, alignItems: 'center' }}
              testID="emisora-mode-login"
            >
              <Text style={{ color: authMode === 'login' ? '#0F172A' : '#94A3B8', fontWeight: '700', fontSize: 13 }}>Ya tengo cuenta</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => { setAuthMode('signup'); setAuthError(null); }}
              style={{ flex: 1, backgroundColor: authMode === 'signup' ? '#F59E0B' : 'transparent', borderRadius: 8, paddingVertical: 10, alignItems: 'center' }}
              testID="emisora-mode-signup"
            >
              <Text style={{ color: authMode === 'signup' ? '#0F172A' : '#94A3B8', fontWeight: '700', fontSize: 13 }}>Primera vez</Text>
            </TouchableOpacity>
          </View>

          {associatedDriverName && authMode === 'signup' && (
            <View style={{ marginBottom: 12, backgroundColor: '#1E293B', borderRadius: 10, padding: 10, borderWidth: 1, borderColor: '#F59E0B' }}>
              <Text style={{ color: '#F1F5F9', fontSize: 13 }}>
                Vas a quedar asociado al taxista <Text style={{ fontWeight: '700', color: '#F59E0B' }}>{associatedDriverName}</Text>
              </Text>
            </View>
          )}
          {!hasQr && authMode === 'signup' && (
            <View style={{ marginBottom: 12, backgroundColor: '#7F1D1D', borderRadius: 10, padding: 10, borderWidth: 1, borderColor: '#EF4444' }}>
              <Text style={{ color: '#FEE2E2', fontSize: 13, textAlign: 'center' }}>
                Para registrarte pídele al taxista que te enseñe su QR y escanéalo con la cámara del móvil.
              </Text>
            </View>
          )}

          <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>Teléfono</Text>
          <TextInput
            style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12, fontSize: 16 }}
            placeholder="+34611223344"
            placeholderTextColor="#64748B"
            value={phone}
            onChangeText={setPhone}
            keyboardType="phone-pad"
            testID="emisora-phone-input"
          />

          {authMode === 'signup' && (
            <>
              <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>Nombre</Text>
              <TextInput
                style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12 }}
                placeholder="Tu nombre"
                placeholderTextColor="#64748B"
                value={firstName}
                onChangeText={setFirstName}
                testID="emisora-firstname-input"
              />
              <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>Apellido</Text>
              <TextInput
                style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12 }}
                placeholder="Tu apellido"
                placeholderTextColor="#64748B"
                value={lastName}
                onChangeText={setLastName}
                testID="emisora-lastname-input"
              />
              <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>Código del taxista (6 dígitos)</Text>
              <TextInput
                style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: hasQr ? '#F59E0B' : '#334155', marginBottom: 12, fontSize: 22, textAlign: 'center', letterSpacing: 10, fontWeight: '700' }}
                placeholder="000000"
                placeholderTextColor="#475569"
                value={verificationCode}
                onChangeText={t => setVerificationCode(t.replace(/\D/g, '').slice(0, 6))}
                keyboardType="number-pad"
                maxLength={6}
                testID="emisora-code-input"
              />
              <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>
                Email <Text style={{ color: '#64748B', fontSize: 11 }}>(opcional, para recuperar contraseña)</Text>
              </Text>
              <TextInput
                style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12 }}
                placeholder="tu@email.com"
                placeholderTextColor="#64748B"
                value={signupEmail}
                onChangeText={setSignupEmail}
                keyboardType="email-address"
                autoCapitalize="none"
                testID="emisora-signup-email-input"
              />
            </>
          )}

          <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>
            Contraseña {authMode === 'signup' && <Text style={{ color: '#64748B', fontSize: 11 }}>(opcional pero recomendado)</Text>}
          </Text>
          <TextInput
            style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12, fontSize: 16 }}
            placeholder={authMode === 'signup' ? 'Elige una contraseña para poder volver' : 'Tu contraseña'}
            placeholderTextColor="#64748B"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            testID="emisora-password-input"
          />

          {authError && (
            <View style={{ backgroundColor: '#7F1D1D', borderRadius: 8, padding: 10, marginBottom: 8, borderWidth: 1, borderColor: '#EF4444' }}>
              <Text style={{ color: '#FEE2E2', fontSize: 13 }}>{authError}</Text>
            </View>
          )}
          <TouchableOpacity
            onPress={authMode === 'signup' ? handleAuthenticate : handleLogin}
            disabled={authBusy || (authMode === 'signup' && !hasQr)}
            style={{ backgroundColor: (authMode === 'login' || hasQr) ? '#F59E0B' : '#334155', padding: 14, borderRadius: 10, alignItems: 'center' }}
            testID={authMode === 'signup' ? 'emisora-authenticate-btn' : 'emisora-login-btn'}
          >
            {authBusy ? <ActivityIndicator color="#0F172A" /> : <Text style={{ color: '#0F172A', fontWeight: '800' }}>{authMode === 'signup' ? 'Crear cuenta' : 'Entrar'}</Text>}
          </TouchableOpacity>

          {authMode === 'login' && (
            <TouchableOpacity
              onPress={async () => {
                if (Platform.OS !== 'web' || typeof window === 'undefined') return;
                const emailPrompt = window.prompt('Introduce el email de tu cuenta:');
                if (!emailPrompt) return;
                try {
                  await axios.post(`${API_BASE}/api/rides/client/forgot-password`, { email: emailPrompt.trim() });
                  window.alert(
                    'Si esa cuenta tiene email asociado te acabamos de enviar un enlace. ' +
                    'Si no lo recibes en unos minutos, pídele al taxista un código nuevo y crea otra contraseña desde ahí.'
                  );
                } catch (e: any) {
                  window.alert(e?.response?.data?.detail || 'No se pudo enviar');
                }
              }}
              style={{ padding: 12, alignItems: 'center' }}
              testID="emisora-forgot-password-btn"
            >
              <Text style={{ color: '#94A3B8', fontSize: 13, textDecorationLine: 'underline' }}>
                ¿Olvidaste tu contraseña?
              </Text>
            </TouchableOpacity>
          )}
        </ScrollView>
      </View>
    );
  }

  // ─────────── AUTHENTICATED ───────────
  const statusLabel = (r: Ride) => {
    switch (r.status) {
      case 'pending': return { text: 'Buscando taxista', color: '#F59E0B' };
      case 'accepted': return { text: 'Taxista asignado', color: '#3B82F6' };
      case 'in_progress': return { text: 'En camino', color: '#8B5CF6' };
      case 'completed': return { text: 'Finalizado', color: '#10B981' };
      case 'cancelled': return { text: 'Cancelado', color: '#94A3B8' };
    }
  };

  return (
    <View style={{ flex: 1, backgroundColor: '#0F172A' }}>
      <Header
        title={`Hola, ${client.first_name}`}
        right={
          <View style={{ flexDirection: 'row', gap: 12 }}>
            <TouchableOpacity onPress={() => setHistoryOpen(true)} testID="emisora-history-btn">
              <Ionicons name="time-outline" size={22} color="#94A3B8" />
            </TouchableOpacity>
            <TouchableOpacity onPress={openProfile} testID="emisora-profile-btn">
              <Ionicons name="person-circle-outline" size={22} color="#94A3B8" />
            </TouchableOpacity>
            <TouchableOpacity onPress={handleLogout} testID="emisora-logout-btn">
              <Ionicons name="log-out-outline" size={22} color="#94A3B8" />
            </TouchableOpacity>
          </View>
        }
      />
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        {/* NEW RIDE CARD */}
        <View style={{ backgroundColor: '#1E293B', borderRadius: 14, padding: 16, marginBottom: 20, borderWidth: 1, borderColor: '#334155' }}>
          <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16, marginBottom: 12 }}>Nuevo servicio</Text>

          <View style={{ flexDirection: 'row', gap: 8, marginBottom: 12 }}>
            <TouchableOpacity
              onPress={() => setRideType('asap')}
              style={{ flex: 1, backgroundColor: rideType === 'asap' ? '#F59E0B' : '#0F172A', borderRadius: 10, padding: 12, alignItems: 'center', borderWidth: 1, borderColor: rideType === 'asap' ? '#F59E0B' : '#334155' }}
              testID="emisora-type-asap"
            >
              <Ionicons name="flash" size={18} color={rideType === 'asap' ? '#0F172A' : '#F59E0B'} />
              <Text style={{ color: rideType === 'asap' ? '#0F172A' : '#F1F5F9', fontWeight: '700', marginTop: 4 }}>Lo antes posible</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setRideType('scheduled')}
              style={{ flex: 1, backgroundColor: rideType === 'scheduled' ? '#F59E0B' : '#0F172A', borderRadius: 10, padding: 12, alignItems: 'center', borderWidth: 1, borderColor: rideType === 'scheduled' ? '#F59E0B' : '#334155' }}
              testID="emisora-type-scheduled"
            >
              <Ionicons name="calendar" size={18} color={rideType === 'scheduled' ? '#0F172A' : '#F59E0B'} />
              <Text style={{ color: rideType === 'scheduled' ? '#0F172A' : '#F1F5F9', fontWeight: '700', marginTop: 4 }}>Reserva</Text>
            </TouchableOpacity>
          </View>

          {rideType === 'scheduled' && (
            <DateTimePicker
              date={schedDate}
              time={schedTime}
              onChangeDate={setSchedDate}
              onChangeTime={setSchedTime}
            />
          )}

          {frequentAddresses.length > 0 && (
            <View style={{ marginBottom: 10 }} testID="emisora-frequent-addresses">
              <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 6 }}>
                <Ionicons name="star" size={11} color="#F59E0B" /> Frecuentes
              </Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6 }}>
                {frequentAddresses.map(fa => (
                  <View
                    key={fa.address}
                    testID={`freq-chip-${fa.address}`}
                    style={{
                      flexDirection: 'row', alignItems: 'center',
                      backgroundColor: '#0F172A', borderRadius: 999, paddingLeft: 10, paddingRight: 4, paddingVertical: 3,
                      borderWidth: 1, borderColor: '#334155',
                    }}
                  >
                    <Text
                      numberOfLines={1}
                      style={{ color: '#F1F5F9', fontSize: 12, maxWidth: 160, marginRight: 6 }}
                    >
                      {fa.address}
                    </Text>
                    <TouchableOpacity
                      onPress={() => setOrigin(fa.address)}
                      testID={`freq-chip-origin-${fa.address}`}
                      style={{ backgroundColor: '#10B981', borderRadius: 999, padding: 4, marginRight: 3 }}
                    >
                      <Ionicons name="arrow-up" size={12} color="#0F172A" />
                    </TouchableOpacity>
                    <TouchableOpacity
                      onPress={() => setDestination(fa.address)}
                      testID={`freq-chip-dest-${fa.address}`}
                      style={{ backgroundColor: '#3B82F6', borderRadius: 999, padding: 4 }}
                    >
                      <Ionicons name="arrow-down" size={12} color="#FFF" />
                    </TouchableOpacity>
                  </View>
                ))}
              </ScrollView>
            </View>
          )}

          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Recogida</Text>
          <AddressAutocomplete
            value={origin}
            onChange={v => {
              setOrigin(v);
              // Typing invalidates any previously-picked coordinates so we
              // don't attach stale coords to the ride.
              if (originCoords) setOriginCoords(null);
            }}
            onPick={s => setOriginCoords({ lat: s.lat, lon: s.lon })}
            placeholder="Dirección de recogida"
            tokenKey={CLIENT_TOKEN_KEY}
            testID="emisora-origin-input"
            onUseLocation={async () => {
              if (Platform.OS !== 'web' || typeof navigator === 'undefined' || !navigator.geolocation) {
                notify('Tu navegador no soporta geolocalización');
                return null;
              }
              try {
                const coords: { lat: number; lon: number } = await new Promise((resolve, reject) => {
                  navigator.geolocation.getCurrentPosition(
                    pos => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
                    err => reject(err),
                    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
                  );
                });
                return coords;
              } catch (e: any) {
                notify(e?.message || 'No se pudo obtener la ubicación');
                return null;
              }
            }}
          />
          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Destino</Text>
          <AddressAutocomplete
            value={destination}
            onChange={setDestination}
            placeholder="A dónde vas"
            tokenKey={CLIENT_TOKEN_KEY}
            testID="emisora-destination-input"
          />
          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Pasajeros</Text>
          <TextInput
            style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 14 }}
            placeholder="1"
            placeholderTextColor="#475569"
            value={passengers}
            onChangeText={t => setPassengers(t.replace(/\D/g, ''))}
            keyboardType="number-pad"
            testID="emisora-passengers-input"
          />

          {/* Estimated fare */}
          <TouchableOpacity
            onPress={async () => {
              setFareError(null);
              setFareEstimate(null);
              if (!origin.trim() || !destination.trim()) {
                setFareError('Escribe origen y destino primero');
                return;
              }
              setFareLoading(true);
              try {
                // Use scheduled time when applicable so night/weekend surcharge applies correctly
                const at =
                  rideType === 'scheduled' && schedDate && schedTime
                    ? new Date(`${schedDate}T${schedTime}:00`)
                    : new Date();
                const est = await calculateEstimatedFare(origin.trim(), destination.trim(), at);
                setFareEstimate(est);
              } catch (e: any) {
                setFareError(e?.message || 'No se pudo calcular la tarifa');
              } finally {
                setFareLoading(false);
              }
            }}
            disabled={fareLoading}
            style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 12, borderWidth: 1, borderColor: '#334155', flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, marginBottom: 10 }}
            testID="emisora-estimate-fare-btn"
          >
            {fareLoading ? (
              <ActivityIndicator color="#F59E0B" size="small" />
            ) : (
              <>
                <Ionicons name="calculator" size={16} color="#F59E0B" />
                <Text style={{ color: '#F59E0B', fontWeight: '700' }}>Ver precio estimado</Text>
              </>
            )}
          </TouchableOpacity>
          {fareError && (
            <Text style={{ color: '#F87171', marginBottom: 10, fontSize: 12 }}>{fareError}</Text>
          )}
          {fareEstimate && (
            <View
              testID="emisora-fare-estimate"
              style={{ backgroundColor: '#064E3B', borderRadius: 10, padding: 12, borderWidth: 1, borderColor: '#10B981', marginBottom: 12 }}
            >
              <Text style={{ color: '#6EE7B7', fontSize: 12, fontWeight: '700', marginBottom: 4 }}>{fareEstimate.tarifa}</Text>
              <Text style={{ color: '#F1F5F9', fontSize: 22, fontWeight: '900' }}>
                {fareEstimate.fare_min.toFixed(2)}€
                {fareEstimate.fare_max > fareEstimate.fare_min && ` – ${fareEstimate.fare_max.toFixed(2)}€`}
              </Text>
              <Text style={{ color: '#94A3B8', fontSize: 11, marginTop: 4 }}>{fareEstimate.details}</Text>
              <Text style={{ color: '#64748B', fontSize: 10, marginTop: 2 }}>
                Distancia estimada: {fareEstimate.distance_km.toFixed(1)} km · precio orientativo
              </Text>
            </View>
          )}

          <TouchableOpacity
            onPress={handleCreateRide}
            disabled={creating}
            style={{ backgroundColor: '#F59E0B', padding: 14, borderRadius: 10, alignItems: 'center' }}
            testID="emisora-create-ride-btn"
          >
            {creating ? <ActivityIndicator color="#0F172A" /> : (
              <Text style={{ color: '#0F172A', fontWeight: '800' }}>Solicitar taxi</Text>
            )}
          </TouchableOpacity>
        </View>

        {/* HISTORY */}
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16 }}>Mis servicios</Text>
          <TouchableOpacity onPress={refreshRides} testID="emisora-refresh-rides">
            <Ionicons name={refreshing ? 'sync' : 'refresh'} size={20} color="#94A3B8" />
          </TouchableOpacity>
        </View>

        {rides.length === 0 && (
          <Text style={{ color: '#64748B', fontStyle: 'italic', marginTop: 8 }}>Aún no has pedido ningún servicio.</Text>
        )}

        {rides.map(r => {
          const s = statusLabel(r);
          return (
            <View key={r.id} style={{ backgroundColor: '#1E293B', borderRadius: 12, padding: 14, marginBottom: 10, borderLeftWidth: 4, borderLeftColor: s.color }} testID={`emisora-ride-${r.id}`}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text style={{ color: s.color, fontWeight: '800', fontSize: 12 }}>{s.text.toUpperCase()}</Text>
                <Text style={{ color: '#94A3B8', fontSize: 11 }}>{r.ride_type === 'asap' ? 'ASAP' : new Date(r.scheduled_at || '').toLocaleString('es-ES')}</Text>
              </View>
              <Text style={{ color: '#F1F5F9', fontWeight: '700' }}>{r.origin}</Text>
              <Text style={{ color: '#94A3B8', fontSize: 12 }}>→ {r.destination}</Text>
              {r.accepted_by_driver_name && (
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                  <Text style={{ color: '#3B82F6', fontSize: 12 }}>
                    <Ionicons name="person" size={11} /> Taxista: {r.accepted_by_driver_name}
                  </Text>
                  {r.accepted_by_driver_id && (
                    <RatingBadge
                      rating={driverRatings[r.accepted_by_driver_id]}
                      testID={`emisora-driver-rating-${r.id}`}
                    />
                  )}
                </View>
              )}
              {(r.status === 'accepted' || r.status === 'in_progress') && r.accepted_by_driver_phone && (
                <TouchableOpacity
                  onPress={() => openTel(r.accepted_by_driver_phone)}
                  style={{ marginTop: 10, backgroundColor: '#10B981', paddingVertical: 10, borderRadius: 8, alignItems: 'center', flexDirection: 'row', justifyContent: 'center', gap: 6 }}
                  testID={`emisora-call-driver-${r.id}`}
                >
                  <Ionicons name="call" size={16} color="#FFF" />
                  <Text style={{ color: '#FFF', fontWeight: '800' }}>Llamar al taxista · {r.accepted_by_driver_phone}</Text>
                </TouchableOpacity>
              )}
              {(r.status === 'pending' || r.status === 'accepted') && (
                <TouchableOpacity onPress={() => handleCancel(r.id, r.status === 'accepted')} style={{ marginTop: 8, alignSelf: 'flex-start', paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8, borderWidth: 1, borderColor: '#EF4444' }} testID={`emisora-cancel-${r.id}`}>
                  <Text style={{ color: '#EF4444', fontSize: 12, fontWeight: '700' }}>Cancelar</Text>
                </TouchableOpacity>
              )}
            </View>
          );
        })}
      </ScrollView>

      {/* Ride history modal */}
      <Modal visible={historyOpen} transparent animationType="fade" onRequestClose={() => setHistoryOpen(false)}>
        <View style={{ flex: 1, backgroundColor: '#0009', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 560, backgroundColor: '#0F172A', borderRadius: 14, borderWidth: 1, borderColor: '#334155' }}>
            <RideHistoryPanel viewerRole="client" onClose={() => setHistoryOpen(false)} />
          </View>
        </View>
      </Modal>

      {/* Post-ride rating prompt */}
      <RatePrompt
        visible={!!ratePromptRide}
        rideId={ratePromptRide?.id || null}
        counterpartLabel={ratePromptRide?.accepted_by_driver_name || 'tu taxista'}
        tokenKey={CLIENT_TOKEN_KEY}
        onClose={rated => {
          if (ratePromptRide) {
            promptedRidesRef.current.add(ratePromptRide.id);
          }
          setRatePromptRide(null);
          if (rated) refreshRides();
        }}
      />

      {/* Client profile edit modal */}
      <Modal visible={profileOpen} transparent animationType="fade" onRequestClose={() => setProfileOpen(false)}>
        <View style={{ flex: 1, backgroundColor: '#0008', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 460, backgroundColor: '#0F172A', borderRadius: 14, padding: 18, borderWidth: 1, borderColor: '#334155' }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800' }}>Mi perfil</Text>
                <RatingBadge rating={myRating} testID="emisora-client-my-rating" />
              </View>
              <TouchableOpacity onPress={() => setProfileOpen(false)} testID="emisora-profile-close">
                <Ionicons name="close" size={22} color="#94A3B8" />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 460 }}>
              <ProfileField label="Nombre" value={profileForm.first_name} onChange={v => setProfileForm({ ...profileForm, first_name: v })} testID="emisora-profile-first-name" />
              <ProfileField label="Apellido" value={profileForm.last_name} onChange={v => setProfileForm({ ...profileForm, last_name: v })} testID="emisora-profile-last-name" />
              <ProfileField label="Telefono (E.164)" value={profileForm.phone} onChange={v => setProfileForm({ ...profileForm, phone: v })} testID="emisora-profile-phone" />
              <ProfileField label="Email" value={profileForm.email} onChange={v => setProfileForm({ ...profileForm, email: v })} testID="emisora-profile-email" />
              <ProfileField
                label="Nueva contrasena (dejar en blanco para no cambiar)"
                value={profileForm.new_password}
                onChange={v => setProfileForm({ ...profileForm, new_password: v })}
                secure
                testID="emisora-profile-password"
              />
            </ScrollView>
            <TouchableOpacity
              onPress={saveProfile}
              disabled={profileBusy}
              testID="emisora-profile-save"
              style={{ marginTop: 10, backgroundColor: '#F59E0B', paddingVertical: 12, borderRadius: 10, alignItems: 'center' }}
            >
              {profileBusy ? <ActivityIndicator color="#0F172A" /> : <Text style={{ color: '#0F172A', fontWeight: '800' }}>Guardar cambios</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
};

const ProfileField: React.FC<{
  label: string; value: string; onChange: (v: string) => void;
  secure?: boolean; testID?: string;
}> = ({ label, value, onChange, secure, testID }) => (
  <View style={{ marginBottom: 10 }}>
    <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>{label}</Text>
    <TextInput
      value={value}
      onChangeText={onChange}
      secureTextEntry={secure}
      autoCapitalize="none"
      testID={testID}
      style={{ backgroundColor: '#1E293B', color: '#F1F5F9', paddingHorizontal: 10, paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: '#334155' }}
    />
  </View>
);

export default EmisoraClient;
