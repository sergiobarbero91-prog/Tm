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
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { calculateEstimatedFare, type FareResult } from '../utils/fareEstimator';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const CLIENT_TOKEN_KEY = 'emisora_client_token';
const CLIENT_INFO_KEY = 'emisora_client_info';

type ClientInfo = {
  id: string;
  phone: string;
  first_name: string;
  last_name: string;
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
  const [rideType, setRideType] = useState<'asap' | 'scheduled'>('asap');
  const [schedDate, setSchedDate] = useState('');
  const [schedTime, setSchedTime] = useState('');
  const [passengers, setPassengers] = useState('1');
  const [creating, setCreating] = useState(false);

  const [rides, setRides] = useState<Ride[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  // Estimated fare (recomputed on-demand by pressing "Ver precio")
  const [fareEstimate, setFareEstimate] = useState<FareResult | null>(null);
  const [fareLoading, setFareLoading] = useState(false);
  const [fareError, setFareError] = useState<string | null>(null);

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
      setRides(r.data || []);
    } catch (e) {
      // token might have expired
    } finally {
      setRefreshing(false);
    }
  }, [client, authHeaders]);

  useEffect(() => {
    refreshRides();
    if (!client) return;
    const t = setInterval(refreshRides, 15000);
    return () => clearInterval(t);
  }, [client, refreshRides]);

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
      if (rideType === 'scheduled') {
        // Compose ISO in local time; backend interprets as UTC (naive → utc)
        const iso = new Date(`${schedDate}T${schedTime}:00`).toISOString();
        body.scheduled_at = iso;
      }
      await axios.post(`${API_BASE}/api/rides/rides`, body, { headers: await authHeaders() });
      setOrigin('');
      setDestination('');
      setSchedDate('');
      setSchedTime('');
      setPassengers('1');
      await refreshRides();
      notify('Servicio solicitado correctamente');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo crear el servicio');
    } finally {
      setCreating(false);
    }
  };

  const handleCancel = async (id: string) => {
    if (Platform.OS === 'web' && typeof window !== 'undefined') {
      // eslint-disable-next-line no-alert
      if (!window.confirm('¿Cancelar este servicio?')) return;
    }
    try {
      await axios.post(`${API_BASE}/api/rides/rides/${id}/cancel`, {}, { headers: await authHeaders() });
      await refreshRides();
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
          <TouchableOpacity onPress={handleLogout} testID="emisora-logout-btn">
            <Ionicons name="log-out-outline" size={22} color="#94A3B8" />
          </TouchableOpacity>
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
            <View style={{ flexDirection: 'row', gap: 8, marginBottom: 10 }}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Fecha</Text>
                <TextInput
                  style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155' }}
                  placeholder="YYYY-MM-DD"
                  placeholderTextColor="#475569"
                  value={schedDate}
                  onChangeText={setSchedDate}
                  testID="emisora-sched-date"
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Hora</Text>
                <TextInput
                  style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155' }}
                  placeholder="HH:MM"
                  placeholderTextColor="#475569"
                  value={schedTime}
                  onChangeText={setSchedTime}
                  testID="emisora-sched-time"
                />
              </View>
            </View>
          )}

          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Recogida</Text>
          <TextInput
            style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 10 }}
            placeholder="Dirección de recogida"
            placeholderTextColor="#475569"
            value={origin}
            onChangeText={setOrigin}
            testID="emisora-origin-input"
          />
          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Destino</Text>
          <TextInput
            style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 10 }}
            placeholder="A dónde vas"
            placeholderTextColor="#475569"
            value={destination}
            onChangeText={setDestination}
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
                <Text style={{ color: '#3B82F6', marginTop: 6, fontSize: 12 }}>
                  <Ionicons name="person" size={11} /> Taxista: {r.accepted_by_driver_name}
                </Text>
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
              {r.status === 'pending' && (
                <TouchableOpacity onPress={() => handleCancel(r.id)} style={{ marginTop: 8, alignSelf: 'flex-start', paddingVertical: 6, paddingHorizontal: 10, borderRadius: 8, borderWidth: 1, borderColor: '#EF4444' }} testID={`emisora-cancel-${r.id}`}>
                  <Text style={{ color: '#EF4444', fontSize: 12, fontWeight: '700' }}>Cancelar</Text>
                </TouchableOpacity>
              )}
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
};

export default EmisoraClient;
