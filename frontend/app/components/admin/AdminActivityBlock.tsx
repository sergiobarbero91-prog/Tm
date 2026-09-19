/**
 * AdminActivityBlock — shows a user's/client's usage hours per period
 * (today, week, month) plus an expandable "Ver historial de servicios"
 * that reveals the `RideHistoryList`.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { RideHistoryList } from './RideHistoryList';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type PeriodStats = { active_users: number; total_hours: number };

type Activity = {
  kind: 'user' | 'client';
  periods: { day: PeriodStats; week: PeriodStats; month: PeriodStats };
  last_seen: string | null;
  rides_count: number;
};

const fmtHours = (h: number) => {
  if (h < 1) return `${Math.round(h * 60)} min`;
  return `${h.toFixed(h < 10 ? 1 : 0)} h`;
};

const Tile: React.FC<{ label: string; hours: number; color: string; testID?: string }> = ({ label, hours, color, testID }) => (
  <View testID={testID} style={{ flex: 1, backgroundColor: `${color}20`, borderRadius: 10, padding: 10, alignItems: 'center', borderWidth: 1, borderColor: `${color}55` }}>
    <Text style={{ color, fontSize: 10, fontWeight: '700', letterSpacing: 0.5 }}>{label}</Text>
    <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800', marginTop: 2 }}>{fmtHours(hours)}</Text>
  </View>
);

export const AdminActivityBlock: React.FC<{ userId: string; ridesKind: 'driver' | 'client' }> = ({ userId, ridesKind }) => {
  const [act, setAct] = useState<Activity | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const fetchIt = useCallback(async () => {
    setLoading(true);
    try {
      const tk = await AsyncStorage.getItem('token');
      const r = await axios.get(`${API_BASE}/api/admin/activity/user/${userId}`, {
        headers: { Authorization: `Bearer ${tk}` },
      });
      setAct(r.data);
    } catch {
      setAct(null);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { fetchIt(); }, [fetchIt]);

  if (loading) return <ActivityIndicator color="#6366F1" style={{ marginVertical: 12 }} />;
  if (!act) return <Text style={{ color: '#EF4444', fontSize: 12 }}>Sin datos de actividad</Text>;

  return (
    <View style={{ marginTop: 12 }} testID="admin-activity-block">
      <Text style={{ color: '#94A3B8', fontSize: 12, fontWeight: '700', marginBottom: 6 }}>Tiempo de uso</Text>
      <View style={{ flexDirection: 'row', gap: 6, marginBottom: 6 }}>
        <Tile label="HOY" hours={act.periods.day.total_hours} color="#F59E0B" testID="activity-tile-day" />
        <Tile label="SEMANA" hours={act.periods.week.total_hours} color="#6366F1" testID="activity-tile-week" />
        <Tile label="MES" hours={act.periods.month.total_hours} color="#10B981" testID="activity-tile-month" />
      </View>
      {act.last_seen && (
        <Text style={{ color: '#64748B', fontSize: 11 }}>
          Ultima actividad: {new Date(act.last_seen).toLocaleString('es-ES')}
        </Text>
      )}
      <TouchableOpacity
        onPress={() => setExpanded(x => !x)}
        testID="admin-activity-toggle-rides"
        style={{ flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 10, marginTop: 6 }}
      >
        <Ionicons name={expanded ? 'chevron-down' : 'chevron-forward'} size={14} color="#6366F1" />
        <Text style={{ color: '#6366F1', fontSize: 13, fontWeight: '700' }}>
          Historial de servicios ({act.rides_count})
        </Text>
      </TouchableOpacity>
      {expanded && (
        <RideHistoryList
          endpoint={`admin/activity/user/${userId}/rides`}
          perspective={ridesKind}
        />
      )}
    </View>
  );
};

export default AdminActivityBlock;
