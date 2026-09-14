/**
 * DateTimePicker — selector de fecha y hora amigable.
 *
 * En web usa <input type="date"> y <input type="time"> nativos, que abren
 * el calendario y reloj del navegador (macOS/iOS/Android/Windows).
 * En native fall-back a TextInput (formato YYYY-MM-DD / HH:MM).
 *
 * Añade chips rapidos: Hoy, Mañana, Pasado + preajustes horarios (mañana 08:00,
 * tarde 14:00, noche 22:00) para reservas comunes de taxi.
 */
import React from 'react';
import { View, Text, TouchableOpacity, Platform, TextInput } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);

const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

interface Props {
  date: string;                 // YYYY-MM-DD
  time: string;                 // HH:MM
  onChangeDate: (v: string) => void;
  onChangeTime: (v: string) => void;
  minDate?: string;             // YYYY-MM-DD (default: today)
}

export const DateTimePicker: React.FC<Props> = ({ date, time, onChangeDate, onChangeTime, minDate }) => {
  const today = new Date();
  const tomorrow = new Date(today.getTime() + 24 * 60 * 60 * 1000);
  const dayAfter = new Date(today.getTime() + 48 * 60 * 60 * 1000);

  const min = minDate || iso(today);

  const isWeb = Platform.OS === 'web';

  const Chip = ({ label, active, onPress, testID }: any) => (
    <TouchableOpacity
      onPress={onPress}
      testID={testID}
      style={{
        paddingVertical: 6, paddingHorizontal: 10, borderRadius: 999,
        backgroundColor: active ? '#F59E0B' : '#1E293B',
        borderWidth: 1, borderColor: active ? '#F59E0B' : '#334155',
      }}
    >
      <Text style={{ color: active ? '#0F172A' : '#F1F5F9', fontSize: 12, fontWeight: '700' }}>{label}</Text>
    </TouchableOpacity>
  );

  const dateStr = date || '';
  const timeStr = time || '';

  return (
    <View style={{ marginBottom: 12 }}>
      {/* Quick date chips */}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        <Chip label="Hoy" active={dateStr === iso(today)} onPress={() => onChangeDate(iso(today))} testID="dtp-today" />
        <Chip label="Mañana" active={dateStr === iso(tomorrow)} onPress={() => onChangeDate(iso(tomorrow))} testID="dtp-tomorrow" />
        <Chip label="Pasado" active={dateStr === iso(dayAfter)} onPress={() => onChangeDate(iso(dayAfter))} testID="dtp-dayafter" />
      </View>

      {/* Quick time chips */}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        <Chip label="08:00" active={timeStr === '08:00'} onPress={() => onChangeTime('08:00')} testID="dtp-morning" />
        <Chip label="14:00" active={timeStr === '14:00'} onPress={() => onChangeTime('14:00')} testID="dtp-noon" />
        <Chip label="22:00" active={timeStr === '22:00'} onPress={() => onChangeTime('22:00')} testID="dtp-night" />
      </View>

      {/* Native inputs (web) or fallback (native) */}
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>
            <Ionicons name="calendar" size={12} color="#94A3B8" /> Fecha
          </Text>
          {isWeb ? (
            // @ts-ignore — React Native Web renders unknown web-only props onto <input>
            <input
              type="date"
              value={dateStr}
              min={min}
              onChange={(e: any) => onChangeDate(e.target.value)}
              data-testid="emisora-sched-date"
              style={{
                background: '#0F172A',
                color: '#F1F5F9',
                border: '1px solid #334155',
                borderRadius: 10,
                padding: 12,
                fontSize: 14,
                fontFamily: 'inherit',
                width: '100%',
                boxSizing: 'border-box',
                colorScheme: 'dark',
              } as any}
            />
          ) : (
            <TextInput
              value={dateStr}
              onChangeText={onChangeDate}
              placeholder="YYYY-MM-DD"
              placeholderTextColor="#475569"
              testID="emisora-sched-date"
              style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155' }}
            />
          )}
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>
            <Ionicons name="time" size={12} color="#94A3B8" /> Hora
          </Text>
          {isWeb ? (
            // @ts-ignore
            <input
              type="time"
              value={timeStr}
              onChange={(e: any) => onChangeTime(e.target.value)}
              data-testid="emisora-sched-time"
              style={{
                background: '#0F172A',
                color: '#F1F5F9',
                border: '1px solid #334155',
                borderRadius: 10,
                padding: 12,
                fontSize: 14,
                fontFamily: 'inherit',
                width: '100%',
                boxSizing: 'border-box',
                colorScheme: 'dark',
              } as any}
            />
          ) : (
            <TextInput
              value={timeStr}
              onChangeText={onChangeTime}
              placeholder="HH:MM"
              placeholderTextColor="#475569"
              testID="emisora-sched-time"
              style={{ backgroundColor: '#0F172A', borderRadius: 10, padding: 12, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155' }}
            />
          )}
        </View>
      </View>
    </View>
  );
};

export default DateTimePicker;
