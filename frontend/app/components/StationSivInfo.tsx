import React, { useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export interface StationAlert {
  id: string;
  level: string;
  header: string;
  text: string;
}

export interface CancelledTrain {
  scheduled_time: string;
  day_label?: string;
  origin: string;
  train_type: string;
  train_number: string;
  operator: string;
}

interface Props {
  stationKey: string;
  source?: string | null;
  dataTime?: string | null;
  cancelledCount?: number;
  alerts?: StationAlert[];
  cancelledTrains?: CancelledTrain[];
}

const levelColor = (level: string) =>
  level === 'severe' || level === 'very_severe' ? '#EF4444' : level === 'warning' ? '#F59E0B' : '#60A5FA';

const formatHHMM = (iso?: string | null) => {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' });
};

const AlertRow = ({ alert, testID }: { alert: StationAlert; testID: string }) => {
  const [open, setOpen] = useState(false);
  const color = levelColor(alert.level);
  return (
    <TouchableOpacity
      testID={testID}
      onPress={() => setOpen(o => !o)}
      activeOpacity={0.8}
      style={{ borderLeftWidth: 3, borderLeftColor: color, backgroundColor: '#1E293B', borderRadius: 6, paddingVertical: 6, paddingHorizontal: 8, marginTop: 6 }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Ionicons name="megaphone-outline" size={13} color={color} />
        <Text style={{ color: '#E2E8F0', fontSize: 12, fontWeight: '700', marginLeft: 6, flex: 1 }} numberOfLines={open ? undefined : 2}>
          {alert.header || 'Aviso'}
        </Text>
        <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={13} color="#94A3B8" />
      </View>
      {open && !!alert.text && (
        <Text style={{ color: '#CBD5E1', fontSize: 11, marginTop: 4, lineHeight: 16 }}>{alert.text}</Text>
      )}
    </TouchableOpacity>
  );
};

const CancelledList = ({ stationKey, count, trains }: { stationKey: string; count: number; trains: CancelledTrain[] }) => {
  const [open, setOpen] = useState(false);
  return (
    <TouchableOpacity
      testID={`siv-cancelled-${stationKey}`}
      onPress={() => setOpen(o => !o)}
      activeOpacity={0.8}
      style={{ borderLeftWidth: 3, borderLeftColor: '#EF4444', backgroundColor: '#1E293B', borderRadius: 6, paddingVertical: 6, paddingHorizontal: 8, marginTop: 6 }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Ionicons name="close-circle" size={13} color="#EF4444" />
        <Text style={{ color: '#EF4444', fontSize: 12, fontWeight: '800', marginLeft: 6, flex: 1 }}>
          {count} {count === 1 ? 'tren cancelado' : 'trenes cancelados'}
        </Text>
        <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={13} color="#94A3B8" />
      </View>
      {open && trains.map((t, i) => (
        <View key={`${t.train_number}-${i}`} testID={`siv-cancelled-train-${stationKey}-${i}`} style={{ flexDirection: 'row', alignItems: 'center', marginTop: 6 }}>
          <View style={{ width: 48 }}>
            <Text style={{ color: '#E2E8F0', fontSize: 12, fontWeight: '800', textDecorationLine: 'line-through' }}>{t.scheduled_time}</Text>
            {!!t.day_label && <Text style={{ color: '#F59E0B', fontSize: 9, fontWeight: '700' }}>{t.day_label}</Text>}
          </View>
          <Text style={{ color: '#CBD5E1', fontSize: 11, fontWeight: '700', width: 92 }} numberOfLines={1}>
            {t.train_type} {t.train_number}
          </Text>
          <Text style={{ color: '#94A3B8', fontSize: 11, flex: 1 }} numberOfLines={1}>
            {t.origin}{t.operator ? ` · ${t.operator}` : ''}
          </Text>
        </View>
      ))}
    </TouchableOpacity>
  );
};

export const StationSivInfo = ({ stationKey, source, dataTime, cancelledCount = 0, alerts = [], cancelledTrains = [] }: Props) => {
  if (source !== 'siv') return null;
  return (
    <View testID={`siv-info-${stationKey}`} style={{ marginTop: 8, marginBottom: 4 }}>
      {cancelledCount > 0 && (
        <CancelledList stationKey={stationKey} count={cancelledCount} trains={cancelledTrains} />
      )}
      {alerts.slice(0, 3).map((a, i) => (
        <AlertRow key={a.id || i} alert={a} testID={`siv-alert-${stationKey}-${i}`} />
      ))}
      <Text testID={`siv-source-${stationKey}`} style={{ color: '#64748B', fontSize: 10, marginTop: 6 }}>
        Fuente: paneles de la estación de Adif{dataTime ? ` · ${formatHHMM(dataTime)}` : ''}
      </Text>
    </View>
  );
};
