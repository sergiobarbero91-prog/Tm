/**
 * RideHistoryPanel — pantalla reutilizable de historial de viajes.
 *
 * Usa endpoints:
 *   GET  /api/rides/client/history         (si viewerRole = 'client')
 *   GET  /api/rides/driver/history         (si viewerRole = 'driver')
 *   POST /api/rides/rides/{id}/rate        (calificar contraparte)
 *   POST /api/rides/rides/{id}/report      (crear reporte de moderacion)
 *   POST /api/rides/blocks                 (bloquear contraparte)
 *   GET  /api/rides/blocks                 (para mostrar quien esta bloqueado)
 *   DELETE /api/rides/blocks/{id}          (desbloquear)
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, TouchableOpacity, ActivityIndicator, ScrollView, Modal, TextInput, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Ride = {
  id: string;
  origin: string;
  destination: string;
  ride_type: 'asap' | 'scheduled';
  status: string;
  created_at: string;
  counterpart_id: string | null;
  counterpart_name: string | null;
  my_rating: number | null;
  their_rating: number | null;
};

type BlockRow = { blocked_id: string; blocked_role: string; label: string };

const notify = (msg: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    // eslint-disable-next-line no-alert
    window.alert(msg);
  }
};

const confirmWeb = (msg: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    // eslint-disable-next-line no-alert
    return window.confirm(msg);
  }
  return true;
};

const STATUS_COLORS: Record<string, string> = {
  pending: '#F59E0B',
  accepted: '#3B82F6',
  in_progress: '#8B5CF6',
  completed: '#10B981',
  cancelled: '#94A3B8',
};
const STATUS_LABEL: Record<string, string> = {
  pending: 'Pendiente',
  accepted: 'Aceptado',
  in_progress: 'En curso',
  completed: 'Finalizado',
  cancelled: 'Cancelado',
};

interface Props {
  viewerRole: 'client' | 'driver';
  onClose?: () => void;
}

const Stars: React.FC<{ value: number | null; onChange?: (v: number) => void; small?: boolean }> = ({ value, onChange, small }) => {
  const size = small ? 14 : 26;
  return (
    <View style={{ flexDirection: 'row', gap: 2 }}>
      {[1, 2, 3, 4, 5].map(n => (
        <TouchableOpacity key={n} onPress={onChange ? () => onChange(n) : undefined} disabled={!onChange} testID={`star-${n}`}>
          <Ionicons name={value && n <= value ? 'star' : 'star-outline'} size={size} color="#F59E0B" />
        </TouchableOpacity>
      ))}
    </View>
  );
};

export const RideHistoryPanel: React.FC<Props> = ({ viewerRole, onClose }) => {
  const [rides, setRides] = useState<Ride[]>([]);
  const [blocks, setBlocks] = useState<BlockRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [rateFor, setRateFor] = useState<Ride | null>(null);
  const [rateStars, setRateStars] = useState(0);
  const [rateComment, setRateComment] = useState('');
  const [rateBusy, setRateBusy] = useState(false);

  const [reportFor, setReportFor] = useState<Ride | null>(null);
  const [reportType, setReportType] = useState('other');
  const [reportDesc, setReportDesc] = useState('');
  const [reportBusy, setReportBusy] = useState(false);

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const endpoint = viewerRole === 'client' ? 'client/history' : 'driver/history';
      const [rr, bb] = await Promise.all([
        axios.get(`${API_BASE}/api/rides/${endpoint}`, { headers }),
        axios.get(`${API_BASE}/api/rides/blocks`, { headers }),
      ]);
      setRides(rr.data || []);
      setBlocks(bb.data || []);
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'Error cargando historial');
    } finally {
      setLoading(false);
    }
  }, [viewerRole, authHeaders]);

  useEffect(() => { refresh(); }, [refresh]);

  const blockedSet = useMemo(() => new Set(blocks.map(b => b.blocked_id)), [blocks]);

  const openRate = (r: Ride) => {
    setRateFor(r);
    setRateStars(r.my_rating || 0);
    setRateComment('');
  };
  const doRate = async () => {
    if (!rateFor || rateStars < 1) return;
    setRateBusy(true);
    try {
      const headers = await authHeaders();
      await axios.post(`${API_BASE}/api/rides/rides/${rateFor.id}/rate`, { stars: rateStars, comment: rateComment.trim() || null }, { headers });
      setRateFor(null);
      await refresh();
      notify('Calificacion enviada');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo calificar');
    } finally {
      setRateBusy(false);
    }
  };

  const openReport = (r: Ride) => {
    setReportFor(r);
    setReportType('other');
    setReportDesc('');
  };
  const doReport = async () => {
    if (!reportFor) return;
    if (reportDesc.trim().length < 10) return notify('La descripcion debe tener al menos 10 caracteres');
    setReportBusy(true);
    try {
      const headers = await authHeaders();
      await axios.post(`${API_BASE}/api/rides/rides/${reportFor.id}/report`, {
        report_type: reportType,
        description: reportDesc.trim(),
      }, { headers });
      setReportFor(null);
      notify('Reporte enviado. Un moderador lo revisara.');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo enviar');
    } finally {
      setReportBusy(false);
    }
  };

  const doBlock = async (r: Ride) => {
    if (!r.counterpart_id) return;
    if (!confirmWeb(`Bloquear a ${r.counterpart_name || 'este usuario'}? No volveras a coincidir con el/ella.`)) return;
    try {
      const headers = await authHeaders();
      await axios.post(`${API_BASE}/api/rides/blocks`, {
        target_id: r.counterpart_id,
        target_role: viewerRole === 'client' ? 'driver' : 'client',
      }, { headers });
      await refresh();
      notify('Usuario bloqueado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo bloquear');
    }
  };

  const doUnblock = async (id: string) => {
    try {
      const headers = await authHeaders();
      await axios.delete(`${API_BASE}/api/rides/blocks/${id}`, { headers });
      await refresh();
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo desbloquear');
    }
  };

  return (
    <View style={{ padding: 12 }} testID="ride-history-panel">
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Ionicons name="time" size={20} color="#F59E0B" />
          <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16 }}>
            {viewerRole === 'client' ? 'Mis viajes' : 'Historial de viajes'}
          </Text>
        </View>
        {onClose && (
          <TouchableOpacity onPress={onClose} testID="ride-history-close">
            <Ionicons name="close" size={22} color="#94A3B8" />
          </TouchableOpacity>
        )}
      </View>

      {blocks.length > 0 && (
        <View style={{ marginBottom: 10, padding: 8, backgroundColor: '#1E293B', borderRadius: 8 }}>
          <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>Bloqueados ({blocks.length})</Text>
          {blocks.map(b => (
            <View key={b.blocked_id} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 4 }}>
              <Text style={{ color: '#F1F5F9', fontSize: 13 }}>{b.label}</Text>
              <TouchableOpacity onPress={() => doUnblock(b.blocked_id)} testID={`unblock-${b.blocked_id}`}>
                <Text style={{ color: '#10B981', fontSize: 12, fontWeight: '700' }}>Desbloquear</Text>
              </TouchableOpacity>
            </View>
          ))}
        </View>
      )}

      {loading ? <ActivityIndicator color="#F59E0B" /> : rides.length === 0 ? (
        <Text style={{ color: '#64748B', fontStyle: 'italic', padding: 12, textAlign: 'center' }}>Sin viajes.</Text>
      ) : (
        <ScrollView style={{ maxHeight: 520 }}>
          {rides.map(r => {
            const canRate = ['completed', 'in_progress'].includes(r.status) && !!r.counterpart_id;
            const canAct = !!r.counterpart_id;
            const isBlocked = r.counterpart_id ? blockedSet.has(r.counterpart_id) : false;
            const color = STATUS_COLORS[r.status] || '#94A3B8';
            return (
              <View key={r.id} testID={`history-item-${r.id}`} style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 12, marginBottom: 8, borderLeftWidth: 3, borderLeftColor: color }}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 }}>
                  <Text style={{ color, fontWeight: '800', fontSize: 11 }}>{STATUS_LABEL[r.status] || r.status.toUpperCase()} · {r.ride_type === 'asap' ? 'ASAP' : 'RESERVA'}</Text>
                  <Text style={{ color: '#94A3B8', fontSize: 11 }}>{r.created_at ? new Date(r.created_at).toLocaleDateString('es-ES') : ''}</Text>
                </View>
                <Text style={{ color: '#F1F5F9', fontSize: 13, fontWeight: '700' }}>{r.origin}</Text>
                <Text style={{ color: '#94A3B8', fontSize: 12 }}>→ {r.destination}</Text>
                {r.counterpart_name && (
                  <Text style={{ color: '#8B5CF6', fontSize: 12, marginTop: 4 }}>
                    <Ionicons name={viewerRole === 'client' ? 'car' : 'person'} size={11} /> {r.counterpart_name}
                    {isBlocked && ' · BLOQUEADO'}
                  </Text>
                )}
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 8 }}>
                  <View>
                    <Text style={{ color: '#94A3B8', fontSize: 10 }}>Mi calificacion</Text>
                    <Stars value={r.my_rating} small />
                  </View>
                  <View>
                    <Text style={{ color: '#94A3B8', fontSize: 10 }}>Recibida</Text>
                    <Stars value={r.their_rating} small />
                  </View>
                </View>
                {canAct && (
                  <View style={{ flexDirection: 'row', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
                    {canRate && (
                      <TouchableOpacity onPress={() => openRate(r)} testID={`rate-btn-${r.id}`} style={{ paddingVertical: 5, paddingHorizontal: 8, backgroundColor: '#F59E0B', borderRadius: 6 }}>
                        <Text style={{ color: '#0F172A', fontSize: 11, fontWeight: '800' }}>
                          {r.my_rating ? '★ Editar' : '★ Calificar'}
                        </Text>
                      </TouchableOpacity>
                    )}
                    <TouchableOpacity onPress={() => openReport(r)} testID={`report-btn-${r.id}`} style={{ paddingVertical: 5, paddingHorizontal: 8, backgroundColor: '#0F172A', borderRadius: 6, borderWidth: 1, borderColor: '#EF4444' }}>
                      <Text style={{ color: '#EF4444', fontSize: 11, fontWeight: '800' }}>⚠ Reportar</Text>
                    </TouchableOpacity>
                    {!isBlocked ? (
                      <TouchableOpacity onPress={() => doBlock(r)} testID={`block-btn-${r.id}`} style={{ paddingVertical: 5, paddingHorizontal: 8, backgroundColor: '#0F172A', borderRadius: 6, borderWidth: 1, borderColor: '#94A3B8' }}>
                        <Text style={{ color: '#94A3B8', fontSize: 11, fontWeight: '800' }}>🚫 Bloquear</Text>
                      </TouchableOpacity>
                    ) : (
                      <TouchableOpacity onPress={() => r.counterpart_id && doUnblock(r.counterpart_id)} style={{ paddingVertical: 5, paddingHorizontal: 8, backgroundColor: '#0F172A', borderRadius: 6, borderWidth: 1, borderColor: '#10B981' }}>
                        <Text style={{ color: '#10B981', fontSize: 11, fontWeight: '800' }}>Desbloquear</Text>
                      </TouchableOpacity>
                    )}
                  </View>
                )}
              </View>
            );
          })}
        </ScrollView>
      )}

      {/* Rate modal */}
      <Modal visible={!!rateFor} transparent animationType="fade" onRequestClose={() => setRateFor(null)}>
        <View style={{ flex: 1, backgroundColor: '#0009', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 400, backgroundColor: '#0F172A', borderRadius: 14, padding: 18, borderWidth: 1, borderColor: '#334155' }}>
            <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16, marginBottom: 12 }}>
              Calificar a {rateFor?.counterpart_name || 'contraparte'}
            </Text>
            <View style={{ alignItems: 'center', marginBottom: 12 }}>
              <Stars value={rateStars} onChange={setRateStars} />
            </View>
            <TextInput
              value={rateComment}
              onChangeText={setRateComment}
              placeholder="Comentario opcional"
              placeholderTextColor="#475569"
              multiline
              testID="rate-comment"
              style={{ backgroundColor: '#1E293B', color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', borderRadius: 8, padding: 10, minHeight: 60, marginBottom: 12 }}
            />
            <View style={{ flexDirection: 'row', gap: 6 }}>
              <TouchableOpacity onPress={() => setRateFor(null)} style={{ flex: 1, backgroundColor: '#334155', paddingVertical: 10, borderRadius: 8, alignItems: 'center' }}>
                <Text style={{ color: '#F1F5F9', fontWeight: '700' }}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={doRate} disabled={rateBusy || rateStars < 1} testID="rate-submit" style={{ flex: 1, backgroundColor: '#F59E0B', paddingVertical: 10, borderRadius: 8, alignItems: 'center' }}>
                {rateBusy ? <ActivityIndicator color="#0F172A" /> : <Text style={{ color: '#0F172A', fontWeight: '800' }}>Enviar</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Report modal */}
      <Modal visible={!!reportFor} transparent animationType="fade" onRequestClose={() => setReportFor(null)}>
        <View style={{ flex: 1, backgroundColor: '#0009', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 460, backgroundColor: '#0F172A', borderRadius: 14, padding: 18, borderWidth: 1, borderColor: '#334155' }}>
            <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16, marginBottom: 12 }}>
              Reportar servicio
            </Text>
            <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 8 }}>Motivo</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
              {[
                { id: 'harassment', label: 'Acoso' },
                { id: 'inappropriate', label: 'Comportamiento inadecuado' },
                { id: 'false_info', label: 'Info falsa' },
                { id: 'spam', label: 'Spam' },
                { id: 'other', label: 'Otro' },
              ].map(t => (
                <TouchableOpacity
                  key={t.id}
                  onPress={() => setReportType(t.id)}
                  testID={`report-type-${t.id}`}
                  style={{
                    paddingVertical: 5, paddingHorizontal: 8, borderRadius: 999,
                    backgroundColor: reportType === t.id ? '#EF4444' : '#1E293B',
                    borderWidth: 1, borderColor: reportType === t.id ? '#EF4444' : '#334155',
                  }}
                >
                  <Text style={{ color: '#F1F5F9', fontSize: 11, fontWeight: '700' }}>{t.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
            <TextInput
              value={reportDesc}
              onChangeText={setReportDesc}
              placeholder="Descripcion (min. 10 caracteres). Se enviara a moderadores."
              placeholderTextColor="#475569"
              multiline
              testID="report-desc"
              style={{ backgroundColor: '#1E293B', color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', borderRadius: 8, padding: 10, minHeight: 100, marginBottom: 12 }}
            />
            <View style={{ flexDirection: 'row', gap: 6 }}>
              <TouchableOpacity onPress={() => setReportFor(null)} style={{ flex: 1, backgroundColor: '#334155', paddingVertical: 10, borderRadius: 8, alignItems: 'center' }}>
                <Text style={{ color: '#F1F5F9', fontWeight: '700' }}>Cancelar</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={doReport} disabled={reportBusy} testID="report-submit" style={{ flex: 1, backgroundColor: '#EF4444', paddingVertical: 10, borderRadius: 8, alignItems: 'center' }}>
                {reportBusy ? <ActivityIndicator color="#FFF" /> : <Text style={{ color: '#FFF', fontWeight: '800' }}>Enviar reporte</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
};

export default RideHistoryPanel;
