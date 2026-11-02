import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const MONTHS = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
const WEEK = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
const COLORS: Record<string, string> = { weekly: '#EF4444', weekend: '#3B82F6', holiday: '#A855F7' };
const LEGEND: [string, string][] = [['weekly', 'Semanal (06:00–06:00)'], ['weekend', 'Fin de semana (07:00–20:00)'], ['holiday', 'Festivo (07:00–20:00)']];

type RestDay = { date: string; kind: string; reason: string; start: string; end: string; ends_next_day: boolean };

export const LicenseCalendar: React.FC<{ licenseNumber?: string | null }> = ({ licenseNumber }) => {
  const now = new Date();
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 });
  const [days, setDays] = useState<RestDay[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const tk = await AsyncStorage.getItem('token');
      const r = await axios.get(`${API_BASE}/api/license-rest/calendar?year=${ym.y}&month=${ym.m}`, { headers: { Authorization: `Bearer ${tk}` } });
      setDays(r.data.days);
    } catch {
      setDays([]);
    } finally {
      setLoading(false);
    }
  }, [ym]);

  useEffect(() => { load(); }, [load, licenseNumber]);

  const shift = (delta: number) => {
    setSelected(null);
    setYm(({ y, m }) => {
      const t = m + delta;
      return t < 1 ? { y: y - 1, m: 12 } : t > 12 ? { y: y + 1, m: 1 } : { y, m: t };
    });
  };

  if (!licenseNumber) {
    return (
      <View testID="license-calendar" style={card}>
        <Text style={{ color: '#94A3B8' }}>Añade tu número de licencia para ver tu calendario de libranzas.</Text>
      </View>
    );
  }

  const pad = (n: number) => String(n).padStart(2, '0');
  const first = new Date(ym.y, ym.m - 1, 1);
  const offset = (first.getDay() + 6) % 7;
  const total = new Date(ym.y, ym.m, 0).getDate();
  const cells: (number | null)[] = [...Array(offset).fill(null), ...Array.from({ length: total }, (_, i) => i + 1)];
  const byDate = (iso: string) => days.filter(d => d.date === iso);
  const todayIso = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const selectedRests = selected ? byDate(selected) : [];

  return (
    <View testID="license-calendar" style={card}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
        <Ionicons name="calendar-outline" size={18} color="#F59E0B" />
        <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16, flex: 1, marginLeft: 6 }}>Mis libranzas</Text>
        <TouchableOpacity testID="license-calendar-prev" onPress={() => shift(-1)} style={{ padding: 4 }}>
          <Ionicons name="chevron-back" size={20} color="#CBD5E1" />
        </TouchableOpacity>
        <Text testID="license-calendar-month" style={{ color: '#F1F5F9', fontWeight: '700', width: 120, textAlign: 'center' }}>
          {MONTHS[ym.m - 1]} {ym.y}
        </Text>
        <TouchableOpacity testID="license-calendar-next" onPress={() => shift(1)} style={{ padding: 4 }}>
          <Ionicons name="chevron-forward" size={20} color="#CBD5E1" />
        </TouchableOpacity>
      </View>
      <View style={{ flexDirection: 'row' }}>
        {WEEK.map(w => <Text key={w} style={{ flex: 1, textAlign: 'center', color: '#64748B', fontSize: 12, fontWeight: '700' }}>{w}</Text>)}
      </View>
      {loading ? <ActivityIndicator color="#F59E0B" style={{ marginVertical: 20 }} /> : (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {cells.map((d, i) => {
            if (!d) return <View key={`e${i}`} style={{ width: '14.28%', height: 40 }} />;
            const iso = `${ym.y}-${pad(ym.m)}-${pad(d)}`;
            const rests = byDate(iso);
            return (
              <TouchableOpacity
                key={iso}
                testID={`license-calendar-day-${iso}`}
                onPress={() => setSelected(iso === selected ? null : iso)}
                style={{ width: '14.28%', height: 40, alignItems: 'center', justifyContent: 'center' }}
              >
                <View style={{
                  width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center',
                  backgroundColor: rests.length ? COLORS[rests[0].kind] + '33' : 'transparent',
                  borderWidth: iso === selected ? 2 : iso === todayIso ? 1 : 0,
                  borderColor: iso === selected ? '#F59E0B' : '#94A3B8',
                }}>
                  <Text style={{ color: rests.length ? COLORS[rests[0].kind] : '#CBD5E1', fontWeight: rests.length ? '800' : '500' }}>{d}</Text>
                </View>
                {rests.length > 1 && <View style={{ position: 'absolute', bottom: 2, width: 5, height: 5, borderRadius: 3, backgroundColor: COLORS[rests[1].kind] }} />}
              </TouchableOpacity>
            );
          })}
        </View>
      )}
      {selected && (
        <View testID="license-calendar-detail" style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 10, marginTop: 8 }}>
          <Text style={{ color: '#F1F5F9', fontWeight: '700', marginBottom: 4 }}>{selected.split('-').reverse().join('/')}</Text>
          {selectedRests.length === 0 ? (
            <Text style={{ color: '#6EE7B7' }}>Puedes trabajar todo el día (sin libranza que empiece este día).</Text>
          ) : selectedRests.map(r => (
            <Text key={r.kind} style={{ color: COLORS[r.kind], fontWeight: '700' }}>
              {r.reason[0].toUpperCase() + r.reason.slice(1)}: {r.start} – {r.end}{r.ends_next_day ? ' del día siguiente' : ''}
            </Text>
          ))}
        </View>
      )}
      <View style={{ marginTop: 10, gap: 4 }}>
        {LEGEND.map(([k, label]) => (
          <View key={k} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: COLORS[k] }} />
            <Text style={{ color: '#94A3B8', fontSize: 12 }}>{label}</Text>
          </View>
        ))}
      </View>
    </View>
  );
};

const card = { backgroundColor: '#1E293B', borderRadius: 12, padding: 14, marginTop: 12 };
