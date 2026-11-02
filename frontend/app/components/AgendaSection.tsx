import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator, Linking } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

export interface AgendaEvent {
  uid: string;
  source: string;
  name: string;
  place: string;
  date: string;
  start: string;
  end: string;
  start_at: string;
  end_at: string;
  category: string;
  hot: boolean;
  url?: string;
}

const FILTERS: [string, string, string[]][] = [
  ['todo', 'Todo', []],
  ['futbol', 'Deportes', ['futbol', 'deporte']],
  ['concierto', 'Conciertos', ['concierto', 'musica']],
  ['feria', 'Ferias', ['feria']],
  ['cultura', 'Cultura', ['cultura', 'fiesta']],
];
const CAT_ICON: Record<string, any> = { futbol: 'football', deporte: 'basketball', concierto: 'musical-notes', musica: 'musical-notes', feria: 'business', cultura: 'color-palette', fiesta: 'sparkles' };
const DIAS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

const dayLabel = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  const day = new Date(y, m - 1, d);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((day.getTime() - today.getTime()) / 86400000);
  if (diff === 0) return 'Hoy';
  if (diff === 1) return 'Mañana';
  return `${DIAS[day.getDay()]} ${d} ${MESES[m - 1]}`;
};

const EventRow = ({ e, now }: { e: AgendaEvent; now: number }) => {
  const live = new Date(e.start_at).getTime() <= now;
  return (
    <TouchableOpacity
      testID={`agenda-event-${e.uid}`}
      disabled={!e.url}
      onPress={() => e.url && Linking.openURL(e.url)}
      activeOpacity={0.8}
      style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderTopWidth: 1, borderTopColor: 'rgba(148,163,184,0.12)' }}
    >
      <View style={{ width: 50 }}>
        <Text style={{ color: live ? '#10B981' : '#F1F5F9', fontSize: 14, fontWeight: '800' }}>{live ? 'Ahora' : e.start}</Text>
        <Text style={{ color: '#64748B', fontSize: 10 }}>hasta {e.end}</Text>
      </View>
      <Ionicons name={CAT_ICON[e.category] || 'calendar'} size={16} color={e.hot ? '#F59E0B' : '#94A3B8'} style={{ marginRight: 8 }} />
      <View style={{ flex: 1 }}>
        <Text style={{ color: '#F1F5F9', fontSize: 13, fontWeight: '700' }} numberOfLines={3}>{e.name}</Text>
        <View style={{ flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}>
          <Text style={{ color: '#94A3B8', fontSize: 11 }} numberOfLines={1}>{e.place}</Text>
          {e.hot && (
            <View testID={`agenda-hot-${e.uid}`} style={{ backgroundColor: '#F59E0B22', borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1 }}>
              <Text style={{ color: '#F59E0B', fontSize: 9, fontWeight: '800' }}>ALTA DEMANDA</Text>
            </View>
          )}
        </View>
      </View>
    </TouchableOpacity>
  );
};

export const AgendaSection = ({ apiBase }: { apiBase: string }) => {
  const [events, setEvents] = useState<AgendaEvent[] | null>(null);
  const [filter, setFilter] = useState('todo');
  const [allDays, setAllDays] = useState(false);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const r = await axios.get(`${apiBase}/api/events/agenda`, { params: { days: 7 }, headers: token ? { Authorization: `Bearer ${token}` } : {} });
      setEvents(r.data.events || []);
      setError(false);
    } catch {
      setError(true);
    }
  }, [apiBase]);

  useEffect(() => { load(); }, [load]);

  const cats = FILTERS.find(f => f[0] === filter)?.[2] || [];
  const list = (events || []).filter(e => !cats.length || cats.includes(e.category));
  const days: { date: string; items: AgendaEvent[] }[] = [];
  list.forEach(e => {
    const last = days[days.length - 1];
    if (last && last.date === e.date) last.items.push(e); else days.push({ date: e.date, items: [e] });
  });
  const shown = allDays ? days : days.slice(0, 2);
  const now = Date.now();

  return (
    <View testID="agenda-section" style={{ marginBottom: 16, backgroundColor: '#1E293B', borderRadius: 14, padding: 14 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
        <Ionicons name="calendar" size={18} color="#6366F1" />
        <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800', marginLeft: 8, flex: 1 }}>Agenda de Madrid</Text>
        <TouchableOpacity testID="agenda-refresh" onPress={load}><Ionicons name="refresh" size={18} color="#94A3B8" /></TouchableOpacity>
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
        {FILTERS.map(([k, label]) => (
          <TouchableOpacity
            key={k}
            testID={`agenda-filter-${k}`}
            onPress={() => setFilter(k)}
            style={{ paddingHorizontal: 10, paddingVertical: 5, borderRadius: 14, backgroundColor: filter === k ? '#6366F1' : 'rgba(15,23,42,0.6)' }}
          >
            <Text style={{ color: filter === k ? '#FFFFFF' : '#CBD5E1', fontSize: 12, fontWeight: '700' }}>{label}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {events === null && !error && <ActivityIndicator color="#6366F1" style={{ marginVertical: 16 }} />}
      {error && <Text style={{ color: '#EF4444', fontSize: 12, marginVertical: 8 }}>No se pudo cargar la agenda</Text>}
      {events !== null && !days.length && <Text style={{ color: '#94A3B8', fontSize: 12, marginVertical: 8 }}>Sin eventos próximos</Text>}
      {shown.map(d => (
        <View key={d.date} testID={`agenda-day-${d.date}`} style={{ marginTop: 8 }}>
          <Text style={{ color: '#6366F1', fontSize: 12, fontWeight: '800', letterSpacing: 0.5, marginBottom: 2 }}>
            {dayLabel(d.date).toUpperCase()} · {d.items.length}
          </Text>
          {d.items.map(e => <EventRow key={e.uid} e={e} now={now} />)}
        </View>
      ))}
      {days.length > 2 && (
        <TouchableOpacity testID="agenda-toggle-days" onPress={() => setAllDays(v => !v)} style={{ alignItems: 'center', paddingTop: 10 }}>
          <Text style={{ color: '#6366F1', fontSize: 13, fontWeight: '700' }}>{allDays ? 'Ver menos' : `Ver los próximos ${days.length - 2} días`}</Text>
        </TouchableOpacity>
      )}
      <Text style={{ color: '#64748B', fontSize: 10, marginTop: 10 }}>
        Fuentes: fútbol (ESPN), Movistar Arena, Palacio Vistalegre, La Riviera, IFEMA y agenda del Ayuntamiento (datos.madrid.es)
      </Text>
    </View>
  );
};
