/**
 * RatePrompt — post-ride rating modal.
 *
 * Reused by both `EmisoraClient` (rating the taxista) and
 * `EmisoraDriverSection` (rating the cliente). 5 stars + optional comment.
 * Persists ride IDs already prompted in AsyncStorage so a refresh doesn't
 * re-show the prompt endlessly.
 */
import React, { useState } from 'react';
import { View, Text, TouchableOpacity, TextInput, Modal, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export const PROMPTED_RIDES_KEY = 'rated_or_dismissed_rides';

export const markPrompted = async (rideId: string) => {
  try {
    const raw = await AsyncStorage.getItem(PROMPTED_RIDES_KEY);
    const set = new Set<string>(raw ? JSON.parse(raw) : []);
    set.add(rideId);
    // Keep the list bounded to the last 200 rides.
    const arr = Array.from(set).slice(-200);
    await AsyncStorage.setItem(PROMPTED_RIDES_KEY, JSON.stringify(arr));
  } catch {
    /* silent */
  }
};

export const loadPromptedRides = async (): Promise<Set<string>> => {
  try {
    const raw = await AsyncStorage.getItem(PROMPTED_RIDES_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
};

type Props = {
  visible: boolean;
  rideId: string | null;
  counterpartLabel: string;
  tokenKey: string;
  onClose: (rated: boolean) => void;
};

export const RatePrompt: React.FC<Props> = ({ visible, rideId, counterpartLabel, tokenKey, onClose }) => {
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setStars(0);
    setComment('');
    setError(null);
  };

  const submit = async () => {
    if (!rideId) return;
    if (stars < 1) {
      setError('Elige una puntuación');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const tk = await AsyncStorage.getItem(tokenKey);
      await axios.post(
        `${API_BASE}/api/rides/rides/${rideId}/rate`,
        { stars, comment: comment.trim() || null },
        { headers: { Authorization: `Bearer ${tk}` }, timeout: 8000 },
      );
      await markPrompted(rideId);
      reset();
      onClose(true);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'No se pudo enviar la valoración');
    } finally {
      setBusy(false);
    }
  };

  const dismiss = async () => {
    if (rideId) await markPrompted(rideId);
    reset();
    onClose(false);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={dismiss}>
      <View style={{ flex: 1, backgroundColor: '#000A', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
        <View
          testID="rate-prompt-card"
          style={{ width: '100%', maxWidth: 380, backgroundColor: '#0F172A', borderRadius: 16, padding: 20, borderWidth: 1, borderColor: '#334155' }}
        >
          <View style={{ alignItems: 'center', marginBottom: 12 }}>
            <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: '#1E293B', alignItems: 'center', justifyContent: 'center', marginBottom: 8, borderWidth: 1, borderColor: '#F59E0B' }}>
              <Ionicons name="star" size={28} color="#F59E0B" />
            </View>
            <Text style={{ color: '#F1F5F9', fontSize: 17, fontWeight: '800', textAlign: 'center' }}>
              ¿Qué tal el viaje?
            </Text>
            <Text style={{ color: '#94A3B8', fontSize: 13, textAlign: 'center', marginTop: 4 }}>
              Valora a {counterpartLabel}
            </Text>
          </View>

          {/* Star row */}
          <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 6, marginBottom: 12 }}>
            {[1, 2, 3, 4, 5].map(n => (
              <TouchableOpacity
                key={n}
                onPress={() => setStars(n)}
                testID={`rate-prompt-star-${n}`}
                hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}
              >
                <Ionicons
                  name={n <= stars ? 'star' : 'star-outline'}
                  size={36}
                  color={n <= stars ? '#F59E0B' : '#475569'}
                />
              </TouchableOpacity>
            ))}
          </View>

          <TextInput
            value={comment}
            onChangeText={setComment}
            placeholder="Comentario opcional"
            placeholderTextColor="#475569"
            multiline
            maxLength={400}
            testID="rate-prompt-comment"
            style={{ backgroundColor: '#020617', borderWidth: 1, borderColor: '#334155', borderRadius: 10, padding: 10, color: '#F1F5F9', fontSize: 13, minHeight: 60, marginBottom: 12, textAlignVertical: 'top' }}
          />

          {error && (
            <Text style={{ color: '#EF4444', fontSize: 12, marginBottom: 8, textAlign: 'center' }} testID="rate-prompt-error">
              {error}
            </Text>
          )}

          <View style={{ flexDirection: 'row', gap: 8 }}>
            <TouchableOpacity
              onPress={dismiss}
              disabled={busy}
              testID="rate-prompt-skip"
              style={{ flex: 1, paddingVertical: 12, borderRadius: 10, borderWidth: 1, borderColor: '#334155', alignItems: 'center' }}
            >
              <Text style={{ color: '#94A3B8', fontWeight: '700' }}>Ahora no</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={submit}
              disabled={busy}
              testID="rate-prompt-submit"
              style={{ flex: 1, paddingVertical: 12, borderRadius: 10, backgroundColor: '#F59E0B', alignItems: 'center', opacity: busy ? 0.6 : 1 }}
            >
              {busy ? (
                <ActivityIndicator color="#0F172A" />
              ) : (
                <Text style={{ color: '#0F172A', fontWeight: '800' }}>Enviar</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
};

export default RatePrompt;
