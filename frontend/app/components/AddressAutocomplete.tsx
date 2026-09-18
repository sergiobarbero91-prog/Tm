/**
 * AddressAutocomplete — text input with live Madrid suggestions.
 *
 * Debounces the query (300 ms), calls the shared backend endpoint
 * `/api/rides/address-suggestions`, and renders a dropdown of up to 6
 * suggestions. If `onUseLocation` is provided it renders a "Usar mi
 * ubicación" chip that reverse-geocodes the browser's GPS.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ActivityIndicator, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Suggestion = { address: string; lat: number; lon: number };

type Props = {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** AsyncStorage key holding the JWT. 'token' for driver, 'emisora_client_token' for client. */
  tokenKey: string;
  /** When set, a "Usar mi ubicación" button appears above the input. */
  onUseLocation?: () => Promise<{ lat: number; lon: number } | null>;
  testID?: string;
};

export const AddressAutocomplete: React.FC<Props> = ({
  value,
  onChange,
  placeholder,
  tokenKey,
  onUseLocation,
  testID,
}) => {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [locBusy, setLocBusy] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Suppress a fetch that would just echo the value we just applied from a suggestion click.
  const skipNextRef = useRef(false);

  const fetchSuggestions = useMemo(
    () => async (q: string) => {
      if (q.trim().length < 3) {
        setSuggestions([]);
        return;
      }
      setLoading(true);
      try {
        const tk = await AsyncStorage.getItem(tokenKey);
        if (!tk) return;
        const r = await axios.post(
          `${API_BASE}/api/rides/address-suggestions`,
          { query: q.trim() },
          { headers: { Authorization: `Bearer ${tk}` }, timeout: 6000 },
        );
        setSuggestions(r.data?.suggestions || []);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    },
    [tokenKey],
  );

  useEffect(() => {
    if (skipNextRef.current) {
      skipNextRef.current = false;
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchSuggestions(value);
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [value, fetchSuggestions]);

  const pick = (s: Suggestion) => {
    skipNextRef.current = true;
    onChange(s.address);
    setSuggestions([]);
    setOpen(false);
  };

  const handleUseLocation = async () => {
    if (!onUseLocation) return;
    setLocBusy(true);
    try {
      const coords = await onUseLocation();
      if (!coords) return;
      const tk = await AsyncStorage.getItem(tokenKey);
      if (!tk) return;
      const r = await axios.get(`${API_BASE}/api/rides/reverse-geocode`, {
        params: { lat: coords.lat, lon: coords.lon },
        headers: { Authorization: `Bearer ${tk}` },
        timeout: 6000,
      });
      const addr = r.data?.address;
      if (addr) {
        skipNextRef.current = true;
        onChange(addr);
        setSuggestions([]);
      }
    } catch {
      /* silent */
    } finally {
      setLocBusy(false);
    }
  };

  return (
    <View style={{ marginBottom: 10, position: 'relative', zIndex: 5 }}>
      {onUseLocation && (
        <TouchableOpacity
          onPress={handleUseLocation}
          disabled={locBusy}
          testID={`${testID || 'addr'}-use-location`}
          style={{
            flexDirection: 'row', alignItems: 'center', gap: 6,
            alignSelf: 'flex-start',
            paddingVertical: 4, paddingHorizontal: 8,
            borderRadius: 999,
            backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#334155',
            marginBottom: 6,
          }}
        >
          {locBusy ? (
            <ActivityIndicator size="small" color="#F59E0B" />
          ) : (
            <Ionicons name="locate" size={12} color="#F59E0B" />
          )}
          <Text style={{ color: '#F59E0B', fontSize: 11, fontWeight: '700' }}>
            Usar mi ubicación
          </Text>
        </TouchableOpacity>
      )}
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <TextInput
          value={value}
          onChangeText={t => {
            onChange(t);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          placeholderTextColor="#475569"
          testID={testID}
          style={{
            flex: 1,
            backgroundColor: '#0F172A', borderRadius: 10, padding: 12,
            color: '#F1F5F9', borderWidth: 1, borderColor: '#334155',
          }}
        />
        {loading && (
          <ActivityIndicator size="small" color="#F59E0B" style={{ position: 'absolute', right: 10 }} />
        )}
      </View>
      {open && suggestions.length > 0 && (
        <View
          testID={`${testID || 'addr'}-suggestions`}
          style={{
            marginTop: 4,
            backgroundColor: '#0F172A',
            borderRadius: 10,
            borderWidth: 1,
            borderColor: '#334155',
            overflow: 'hidden',
            // Overlap the following field on web so the dropdown feels floating.
            ...(Platform.OS === 'web' ? { position: 'absolute', top: 52, left: 0, right: 0, zIndex: 20 } : {}),
          }}
        >
          {suggestions.map((s, idx) => (
            <TouchableOpacity
              key={`${s.address}-${idx}`}
              onPress={() => pick(s)}
              testID={`${testID || 'addr'}-suggestion-${idx}`}
              style={{
                paddingVertical: 10, paddingHorizontal: 12,
                borderBottomWidth: idx === suggestions.length - 1 ? 0 : 1,
                borderBottomColor: '#1E293B',
                flexDirection: 'row', alignItems: 'center', gap: 8,
              }}
            >
              <Ionicons name="location" size={14} color="#F59E0B" />
              <Text style={{ color: '#F1F5F9', fontSize: 13, flex: 1 }} numberOfLines={1}>
                {s.address}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      )}
    </View>
  );
};

export default AddressAutocomplete;
