/**
 * RatingBadge + useUserRatings hook
 *
 * Small, self-contained pill that shows "⭐ 4.7 (12)" or "Sin valoraciones".
 * Reused by EmisoraDriverSection (to show client ratings) and by
 * EmisoraClient (to show the assigned taxista's rating).
 */
import React, { useEffect, useRef, useState } from 'react';
import { View, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export type UserRating = { avg: number | null; count: number };
export type UserRatingMap = Record<string, UserRating>;

/**
 * Fetches average rating (last 50) for a set of user IDs.
 * Debounces to a single request when the list changes.
 *
 * @param userIds  Array of user IDs (drivers or clients).
 * @param tokenKey AsyncStorage key that holds the JWT to authenticate.
 *                 Use 'token' for drivers, 'emisora_client_token' for clients.
 */
export const useUserRatings = (userIds: (string | null | undefined)[], tokenKey: string): UserRatingMap => {
  const [map, setMap] = useState<UserRatingMap>({});
  const lastKey = useRef<string>('');

  useEffect(() => {
    const cleaned = Array.from(new Set(userIds.filter((x): x is string => !!x))).sort();
    const key = cleaned.join(',');
    if (!cleaned.length) {
      if (lastKey.current !== '') {
        setMap({});
        lastKey.current = '';
      }
      return;
    }
    if (key === lastKey.current) return;
    lastKey.current = key;
    let cancelled = false;
    (async () => {
      try {
        const tk = await AsyncStorage.getItem(tokenKey);
        if (!tk) return;
        const r = await axios.post(
          `${API_BASE}/api/rides/rating-summary`,
          { user_ids: cleaned },
          { headers: { Authorization: `Bearer ${tk}` } },
        );
        if (!cancelled) setMap(prev => ({ ...prev, ...(r.data || {}) }));
      } catch {
        /* silent — badges just won't render */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userIds, tokenKey]);

  return map;
};

export const RatingBadge: React.FC<{ rating: UserRating | undefined; testID?: string }> = ({ rating, testID }) => {
  if (!rating || !rating.count || rating.avg == null) {
    return (
      <View
        testID={testID}
        style={{
          flexDirection: 'row',
          alignItems: 'center',
          gap: 3,
          paddingHorizontal: 6,
          paddingVertical: 2,
          borderRadius: 6,
          backgroundColor: '#1E293B',
          borderWidth: 1,
          borderColor: '#334155',
        }}
      >
        <Ionicons name="star-outline" size={10} color="#64748B" />
        <Text style={{ color: '#64748B', fontSize: 10, fontWeight: '700' }}>Sin valoraciones</Text>
      </View>
    );
  }
  const avg = rating.avg;
  // Colour tiers: green ≥4.5, amber ≥3.5, red <3.5.
  const color = avg >= 4.5 ? '#10B981' : avg >= 3.5 ? '#F59E0B' : '#EF4444';
  return (
    <View
      testID={testID}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        gap: 3,
        paddingHorizontal: 6,
        paddingVertical: 2,
        borderRadius: 6,
        backgroundColor: '#0F172A',
        borderWidth: 1,
        borderColor: color,
      }}
    >
      <Ionicons name="star" size={11} color={color} />
      <Text style={{ color, fontSize: 11, fontWeight: '800' }}>{avg.toFixed(1)}</Text>
      <Text style={{ color: '#94A3B8', fontSize: 10, fontWeight: '600' }}>({rating.count})</Text>
    </View>
  );
};

export default RatingBadge;
