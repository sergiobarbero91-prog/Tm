/**
 * ResetPasswordScreen — landing when the user opens the "reset your password"
 * email link (?reset_token=…&role=client|driver).
 *
 * Accepts the token from URL params, calls the appropriate backend endpoint
 * and lets the user pick a new password. Works for both drivers and clients.
 */
import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ActivityIndicator, ScrollView, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Props = {
  token: string;
  role: 'driver' | 'client';
  onDone: () => void;
};

export const ResetPasswordScreen: React.FC<Props> = ({ token, role, onDone }) => {
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setError(null);
    if (pw.length < 4) {
      setError('La contraseña debe tener al menos 4 caracteres');
      return;
    }
    if (pw !== pw2) {
      setError('Las contraseñas no coinciden');
      return;
    }
    setBusy(true);
    try {
      const path = role === 'client' ? '/api/rides/client/reset-password' : '/api/auth/reset-password';
      await axios.post(`${API_BASE}${path}`, { token, new_password: pw });
      setDone(true);
      // Strip the token from the URL so it can't be reused visually
      if (Platform.OS === 'web' && typeof window !== 'undefined') {
        try {
          window.history.replaceState({}, '', window.location.pathname);
        } catch {}
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'No se pudo cambiar la contraseña');
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <View style={{ flex: 1, backgroundColor: '#0F172A', padding: 24, alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: '#10B981', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
          <Ionicons name="checkmark" size={44} color="#0F172A" />
        </View>
        <Text style={{ color: '#F1F5F9', fontWeight: '900', fontSize: 22, marginBottom: 8 }}>Contraseña actualizada</Text>
        <Text style={{ color: '#94A3B8', textAlign: 'center', marginBottom: 24 }}>
          Ya puedes iniciar sesión con la nueva contraseña.
        </Text>
        <TouchableOpacity
          onPress={onDone}
          style={{ backgroundColor: '#F59E0B', paddingHorizontal: 24, paddingVertical: 12, borderRadius: 10 }}
          testID="reset-done-continue"
        >
          <Text style={{ color: '#0F172A', fontWeight: '800' }}>Ir a iniciar sesión</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <ScrollView style={{ flex: 1, backgroundColor: '#0F172A' }} contentContainerStyle={{ padding: 24, paddingTop: 60 }}>
      <View style={{ alignItems: 'center', marginBottom: 24 }}>
        <View style={{ width: 68, height: 68, borderRadius: 34, backgroundColor: '#F59E0B', alignItems: 'center', justifyContent: 'center', marginBottom: 12 }}>
          <Ionicons name="lock-closed" size={34} color="#0F172A" />
        </View>
        <Text style={{ color: '#F1F5F9', fontWeight: '900', fontSize: 22 }}>Nueva contraseña</Text>
        <Text style={{ color: '#94A3B8', fontSize: 13, marginTop: 6, textAlign: 'center' }}>
          {role === 'client' ? 'Cuenta de cliente' : 'Cuenta de taxista'}
        </Text>
      </View>

      <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>Nueva contraseña</Text>
      <TextInput
        style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12, fontSize: 16 }}
        placeholder="Escribe una contraseña"
        placeholderTextColor="#64748B"
        value={pw}
        onChangeText={setPw}
        secureTextEntry
        testID="reset-password-input"
      />
      <Text style={{ color: '#94A3B8', fontSize: 13, marginBottom: 6 }}>Repite la contraseña</Text>
      <TextInput
        style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 14, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', marginBottom: 12, fontSize: 16 }}
        placeholder="Repite la contraseña"
        placeholderTextColor="#64748B"
        value={pw2}
        onChangeText={setPw2}
        secureTextEntry
        testID="reset-password2-input"
      />

      {error && (
        <View style={{ backgroundColor: '#7F1D1D', borderRadius: 8, padding: 10, marginBottom: 12, borderWidth: 1, borderColor: '#EF4444' }}>
          <Text style={{ color: '#FEE2E2', fontSize: 13 }}>{error}</Text>
        </View>
      )}

      <TouchableOpacity
        onPress={submit}
        disabled={busy}
        style={{ backgroundColor: '#F59E0B', padding: 14, borderRadius: 10, alignItems: 'center', marginBottom: 8 }}
        testID="reset-submit-btn"
      >
        {busy ? <ActivityIndicator color="#0F172A" /> : <Text style={{ color: '#0F172A', fontWeight: '800' }}>Cambiar contraseña</Text>}
      </TouchableOpacity>

      <TouchableOpacity onPress={onDone} style={{ padding: 10, alignItems: 'center' }} testID="reset-cancel-btn">
        <Text style={{ color: '#94A3B8', fontSize: 13 }}>Cancelar</Text>
      </TouchableOpacity>
    </ScrollView>
  );
};

export default ResetPasswordScreen;
