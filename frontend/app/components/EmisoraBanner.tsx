/**
 * EmisoraBanner — persistent live status strip for drivers.
 *
 * Sits below the header action buttons. Shows three counters and a shortcut
 * to open the Emisora / Reservas tab so the taxista can never miss a new
 * request while browsing other sections.
 *
 * Counters:
 *   - "Para mi": rides reserved exclusively for this driver (assigned scope,
 *     still pending).
 *   - "Activas": rides this driver already accepted (accepted + in_progress).
 *   - "ASAP": open ASAP offers available to anyone.
 *
 * When a NEW ride enters (assigned or open offer) the banner flashes and a
 * short "ping" plays. Tapping the shortcut jumps to the Reservas tab.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { View, Text, TouchableOpacity, Animated, Platform, Easing } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Ride = {
  id: string;
  ride_type: 'asap' | 'scheduled';
  status: 'pending' | 'accepted' | 'in_progress' | 'completed' | 'cancelled';
  dispatch_scope: 'assigned' | 'open';
};

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
    /* swallow */
  }
};

interface Props {
  onGoToEmisora: () => void;
  /** Set to true when the reservations tab is already open — silences flashing */
  isEmisoraOpen?: boolean;
}

export const EmisoraBanner: React.FC<Props> = ({ onGoToEmisora, isEmisoraOpen = false }) => {
  const [assignedCount, setAssignedCount] = useState(0);
  const [activeCount, setActiveCount] = useState(0);
  const [asapCount, setAsapCount] = useState(0);
  const [hasNew, setHasNew] = useState(false);

  const seenAssignedIds = useRef<Set<string>>(new Set());
  const seenAsapIds = useRef<Set<string>>(new Set());
  const firstLoad = useRef(true);
  const flash = useRef(new Animated.Value(0)).current;

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  const triggerFlash = useCallback(() => {
    setHasNew(true);
    Animated.sequence([
      Animated.timing(flash, { toValue: 1, duration: 220, easing: Easing.out(Easing.quad), useNativeDriver: false }),
      Animated.timing(flash, { toValue: 0.4, duration: 400, useNativeDriver: false }),
      Animated.timing(flash, { toValue: 1, duration: 220, useNativeDriver: false }),
      Animated.timing(flash, { toValue: 0.4, duration: 400, useNativeDriver: false }),
      Animated.timing(flash, { toValue: 1, duration: 220, useNativeDriver: false }),
    ]).start();
  }, [flash]);

  const refresh = useCallback(async () => {
    try {
      const headers = await authHeaders();
      if (!('Authorization' in headers)) return; // not logged in
      const [aRes, oRes, actRes] = await Promise.all([
        axios.get(`${API_BASE}/api/rides/driver/assigned`, { headers }).catch(() => ({ data: [] })),
        axios.get(`${API_BASE}/api/rides/driver/offers`, { headers }).catch(() => ({ data: [] })),
        axios.get(`${API_BASE}/api/rides/driver/active`, { headers }).catch(() => ({ data: [] })),
      ]);
      const assigned: Ride[] = aRes.data || [];
      const offers: Ride[] = oRes.data || [];
      const active: Ride[] = actRes.data || [];
      const asapOffers = offers.filter(r => r.ride_type === 'asap');

      if (!firstLoad.current) {
        const newAssigned = assigned.filter(r => !seenAssignedIds.current.has(r.id));
        const newAsap = asapOffers.filter(r => !seenAsapIds.current.has(r.id));
        if ((newAssigned.length > 0 || newAsap.length > 0) && !isEmisoraOpen) {
          playPing();
          triggerFlash();
        }
      }
      seenAssignedIds.current = new Set(assigned.map(r => r.id));
      seenAsapIds.current = new Set(asapOffers.map(r => r.id));
      firstLoad.current = false;

      setAssignedCount(assigned.length);
      setActiveCount(active.length);
      setAsapCount(asapOffers.length);
    } catch {
      /* silent */
    }
  }, [authHeaders, isEmisoraOpen, triggerFlash]);

  // Reset the "new" flag whenever the taxista opens the reservations tab
  useEffect(() => {
    if (isEmisoraOpen) setHasNew(false);
  }, [isEmisoraOpen]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  const handleGo = () => {
    setHasNew(false);
    onGoToEmisora();
  };

  const bgColor = flash.interpolate({
    inputRange: [0, 1],
    outputRange: ['#1E293B', '#7F1D1D'], // slate → red flash
  });
  const borderColor = flash.interpolate({
    inputRange: [0, 1],
    outputRange: ['#334155', '#F59E0B'],
  });

  return (
    <Animated.View
      testID="emisora-banner"
      style={{
        marginHorizontal: 12,
        marginBottom: 8,
        borderRadius: 12,
        paddingVertical: 8,
        paddingHorizontal: 12,
        backgroundColor: bgColor as any,
        borderWidth: 1,
        borderColor: borderColor as any,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1, flexWrap: 'wrap', gap: 8 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
          <Ionicons name="radio" size={14} color="#F59E0B" />
          <Text style={{ color: '#F59E0B', fontWeight: '800', fontSize: 11, letterSpacing: 0.5 }}>
            EMISORA
          </Text>
        </View>

        <Pill label="Para mí" value={assignedCount} color="#8B5CF6" testID="emisora-banner-assigned" />
        <Pill label="Activas" value={activeCount} color="#10B981" testID="emisora-banner-active" />
        <Pill label="ASAP" value={asapCount} color="#EF4444" testID="emisora-banner-asap" pulse={asapCount > 0 && !isEmisoraOpen} />
      </View>

      <TouchableOpacity
        onPress={handleGo}
        testID="emisora-banner-open"
        style={{
          backgroundColor: hasNew ? '#EF4444' : '#F59E0B',
          paddingVertical: 6,
          paddingHorizontal: 10,
          borderRadius: 8,
          flexDirection: 'row',
          alignItems: 'center',
          gap: 4,
        }}
      >
        <Ionicons name={hasNew ? 'notifications' : 'arrow-forward'} size={13} color="#0F172A" />
        <Text style={{ color: '#0F172A', fontSize: 12, fontWeight: '800' }}>
          {hasNew ? '¡Nuevo!' : 'Ver'}
        </Text>
      </TouchableOpacity>
    </Animated.View>
  );
};

const Pill: React.FC<{ label: string; value: number; color: string; testID?: string; pulse?: boolean }> = ({
  label,
  value,
  color,
  testID,
  pulse,
}) => {
  const opacity = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    if (!pulse) {
      opacity.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.4, duration: 500, useNativeDriver: false }),
        Animated.timing(opacity, { toValue: 1, duration: 500, useNativeDriver: false }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [pulse, opacity]);

  const dim = value === 0;
  return (
    <Animated.View
      testID={testID}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: dim ? '#0F172A' : `${color}22`,
        borderWidth: 1,
        borderColor: dim ? '#334155' : color,
        paddingVertical: 3,
        paddingHorizontal: 8,
        borderRadius: 999,
        opacity,
      }}
    >
      <Text style={{ color: dim ? '#64748B' : color, fontSize: 11, fontWeight: '700' }}>
        {label}
      </Text>
      <Text style={{ color: dim ? '#64748B' : '#F1F5F9', fontSize: 12, fontWeight: '900', marginLeft: 6 }}>
        {value}
      </Text>
    </Animated.View>
  );
};

export default EmisoraBanner;
