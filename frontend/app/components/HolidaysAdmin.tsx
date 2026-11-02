import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Holiday = { date: string; name: string; source: string; disabled?: boolean };

const headers = async () => ({ Authorization: `Bearer ${await AsyncStorage.getItem('token')}` });

export const HolidaysAdmin: React.FC = () => {
  const [items, setItems] = useState<Holiday[]>([]);
  const [newDate, setNewDate] = useState('');
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const year = new Date().getFullYear();

  const load = useCallback(async () => {
    const r = await axios.get(`${API_BASE}/api/license-rest/holidays?year=${year}`, { headers: await headers() });
    setItems(r.data.holidays);
  }, [year]);

  useEffect(() => { load().catch(() => {}); }, [load]);

  const run = async (fn: () => Promise<any>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      await load();
      setMsg(ok);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || 'Error');
    } finally {
      setBusy(false);
    }
  };

  const add = () => run(async () => {
    await axios.post(`${API_BASE}/api/license-rest/holidays`, { date: newDate.trim(), name: newName.trim() || 'Festivo' }, { headers: await headers() });
    setNewDate('');
    setNewName('');
  }, 'Festivo añadido');

  const remove = (d: string) => run(async () => {
    await axios.delete(`${API_BASE}/api/license-rest/holidays/${d}`, { headers: await headers() });
  }, 'Festivo desactivado');

  const sync = () => run(async () => {
    await axios.post(`${API_BASE}/api/license-rest/holidays/sync`, {}, { headers: await headers() });
  }, 'Calendario sincronizado con datos.madrid.es');

  return (
    <View testID="holidays-admin" style={{ backgroundColor: '#1E293B', borderRadius: 14, padding: 14, margin: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <Ionicons name="calendar" size={20} color="#F59E0B" />
        <Text style={{ color: '#F1F5F9', fontSize: 17, fontWeight: '800', flex: 1 }}>Festivos {year} (libranzas)</Text>
        <TouchableOpacity testID="holidays-sync-btn" onPress={sync} disabled={busy} style={{ padding: 6 }}>
          <Ionicons name="refresh" size={20} color="#60A5FA" />
        </TouchableOpacity>
      </View>
      <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 10 }}>
        Se sincronizan cada semana desde el calendario laboral del Ayuntamiento. Puedes añadir o quitar excepciones.
      </Text>
      {items.map(h => (
        <View key={h.date} testID={`holiday-row-${h.date}`} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderBottomWidth: 1, borderColor: '#334155', opacity: h.disabled ? 0.45 : 1 }}>
          <Text style={{ color: '#F1F5F9', width: 96, fontWeight: '700' }}>{h.date}</Text>
          <Text style={{ color: '#CBD5E1', flex: 1 }} numberOfLines={1}>
            {h.name}{h.disabled ? ' (desactivado)' : ''}
          </Text>
          {!h.disabled && (
            <TouchableOpacity testID={`holiday-remove-${h.date}`} onPress={() => remove(h.date)} disabled={busy} style={{ padding: 4 }}>
              <Ionicons name="trash-outline" size={18} color="#EF4444" />
            </TouchableOpacity>
          )}
        </View>
      ))}
      <View style={{ flexDirection: 'row', gap: 8, marginTop: 12 }}>
        <TextInput testID="holiday-date-input" value={newDate} onChangeText={setNewDate} placeholder="AAAA-MM-DD" placeholderTextColor="#64748B" style={input} />
        <TextInput testID="holiday-name-input" value={newName} onChangeText={setNewName} placeholder="Nombre" placeholderTextColor="#64748B" style={[input, { flex: 1 }]} />
        <TouchableOpacity testID="holiday-add-btn" onPress={add} disabled={busy || !newDate} style={{ backgroundColor: '#F59E0B', borderRadius: 8, paddingHorizontal: 14, justifyContent: 'center' }}>
          {busy ? <ActivityIndicator color="#0F172A" /> : <Text style={{ color: '#0F172A', fontWeight: '800' }}>Añadir</Text>}
        </TouchableOpacity>
      </View>
      {msg && <Text testID="holidays-msg" style={{ color: '#FBBF24', marginTop: 8 }}>{msg}</Text>}
    </View>
  );
};

const input = { backgroundColor: '#0F172A', color: '#F1F5F9', borderRadius: 8, borderWidth: 1, borderColor: '#334155', paddingHorizontal: 10, paddingVertical: 8, minWidth: 110 };
