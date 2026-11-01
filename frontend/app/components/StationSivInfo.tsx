import React, { useState } from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export interface StationAlert {
  id: string;
  level: string;
  header: string;
  text: string;
}

interface Props {
  stationKey: string;
  source?: string | null;
  dataTime?: string | null;
  cancelledCount?: number;
  alerts?: StationAlert[];
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

export const StationSivInfo = ({ stationKey, source, dataTime, cancelledCount = 0, alerts = [] }: Props) => {
  if (source !== 'siv') return null;
  return (
    <View testID={`siv-info-${stationKey}`} style={{ marginTop: 8, marginBottom: 4 }}>
      {cancelledCount > 0 && (
        <View
          testID={`siv-cancelled-${stationKey}`}
          style={{ flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', backgroundColor: '#EF444422', borderColor: '#EF4444', borderWidth: 1, borderRadius: 12, paddingHorizontal: 10, paddingVertical: 3 }}
        >
          <Ionicons name="close-circle" size={13} color="#EF4444" />
          <Text style={{ color: '#EF4444', fontSize: 12, fontWeight: '800', marginLeft: 4 }}>
            {cancelledCount} {cancelledCount === 1 ? 'cancelado' : 'cancelados'}
          </Text>
        </View>
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
