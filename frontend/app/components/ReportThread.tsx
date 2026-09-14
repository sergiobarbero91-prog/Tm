/**
 * ReportThread — hilo bidireccional entre reporter y staff.
 *
 * Se usa desde:
 *   • Dashboard moderador/admin al hacer click en un reporte
 *   • "Mis reportes" del usuario que reporto
 *
 * El componente sabe hacer:
 *   • cargar mensajes (marca como leidos)
 *   • enviar mensaje (con textarea + boton)
 *   • polling cada 15s cuando esta abierto
 *   • Staff-only: cambiar estado (in_progress / awaiting_reporter / resolved)
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, TouchableOpacity, TextInput, ScrollView, ActivityIndicator, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Msg = {
  id: string;
  sender_username: string;
  sender_role: string | null;
  body: string;
  is_system: boolean;
  created_at: string | null;
};

type ReportDetail = {
  id: string;
  reporter_username: string;
  reported_username?: string | null;
  report_type_name: string;
  description: string;
  status: string;
  status_name: string;
  message_count: number;
  unread_for_viewer: number;
  moderator_username?: string | null;
  admin_username?: string | null;
};

interface Props {
  reportId: string;
  /** Current viewer role — used to hide staff-only controls */
  viewerRole: string;
  onClose?: () => void;
  /** Notify parent when messages arrive / status changes so counters can refresh */
  onUpdate?: () => void;
}

const STATUS_COLORS: Record<string, string> = {
  pending_mod: '#F59E0B',
  pending_admin: '#8B5CF6',
  in_progress: '#3B82F6',
  awaiting_reporter: '#F59E0B',
  resolved: '#10B981',
  approved: '#10B981',
  rejected: '#94A3B8',
};

const isStaffRole = (r?: string) => r === 'moderator' || r === 'admin';

export const ReportThread: React.FC<Props> = ({ reportId, viewerRole, onClose, onUpdate }) => {
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [text, setText] = useState('');
  const [busyStatus, setBusyStatus] = useState(false);
  const scrollRef = useRef<ScrollView>(null);

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  const refresh = useCallback(async () => {
    try {
      const headers = await authHeaders();
      const [d, m] = await Promise.all([
        axios.get(`${API_BASE}/api/moderation/reports/${reportId}`, { headers }),
        axios.get(`${API_BASE}/api/moderation/reports/${reportId}/messages`, { headers }),
      ]);
      setDetail(d.data);
      setMsgs(m.data.messages || []);
      onUpdate?.();
    } catch (e) {
      // silent — leave state
    } finally {
      setLoading(false);
    }
  }, [reportId, authHeaders, onUpdate]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    // auto-scroll to bottom when messages update
    setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 60);
  }, [msgs.length]);

  const send = async () => {
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    try {
      const headers = await authHeaders();
      await axios.post(
        `${API_BASE}/api/moderation/reports/${reportId}/messages`,
        { body },
        { headers },
      );
      setText('');
      await refresh();
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'No se pudo enviar';
      if (Platform.OS === 'web') {
        // eslint-disable-next-line no-alert
        window.alert(msg);
      }
    } finally {
      setSending(false);
    }
  };

  const changeStatus = async (status: 'in_progress' | 'awaiting_reporter' | 'resolved') => {
    if (busyStatus) return;
    if (status === 'resolved' && Platform.OS === 'web') {
      // eslint-disable-next-line no-alert
      if (!window.confirm('¿Marcar el reporte como resuelto? Se cerrará el hilo.')) return;
    }
    setBusyStatus(true);
    try {
      const headers = await authHeaders();
      await axios.put(
        `${API_BASE}/api/moderation/reports/${reportId}/status`,
        { status },
        { headers },
      );
      await refresh();
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'No se pudo actualizar';
      if (Platform.OS === 'web') {
        // eslint-disable-next-line no-alert
        window.alert(msg);
      }
    } finally {
      setBusyStatus(false);
    }
  };

  if (loading) return <View style={{ padding: 20, alignItems: 'center' }}><ActivityIndicator color="#F59E0B" /></View>;
  if (!detail) return <Text style={{ color: '#EF4444', padding: 12 }}>Reporte no accesible.</Text>;

  const closed = ['approved', 'rejected', 'resolved'].includes(detail.status);
  const staff = isStaffRole(viewerRole);

  return (
    <View style={{ backgroundColor: '#0F172A', borderRadius: 12, borderWidth: 1, borderColor: '#334155', padding: 12 }} testID="report-thread">
      {/* Header */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <View style={{ flex: 1 }}>
          <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 14 }}>
            {detail.report_type_name}
          </Text>
          <Text style={{ color: '#94A3B8', fontSize: 12 }}>
            Reporta @{detail.reporter_username}
            {detail.reported_username ? ` · sobre @${detail.reported_username}` : ''}
          </Text>
          <View style={{ marginTop: 4, alignSelf: 'flex-start', backgroundColor: `${STATUS_COLORS[detail.status] || '#94A3B8'}22`, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, borderWidth: 1, borderColor: STATUS_COLORS[detail.status] || '#94A3B8' }}>
            <Text style={{ color: STATUS_COLORS[detail.status] || '#94A3B8', fontSize: 10, fontWeight: '800' }}>
              {detail.status_name.toUpperCase()}
            </Text>
          </View>
        </View>
        {onClose && (
          <TouchableOpacity onPress={onClose} testID="report-thread-close">
            <Ionicons name="close" size={22} color="#94A3B8" />
          </TouchableOpacity>
        )}
      </View>

      {/* Original description */}
      <View style={{ backgroundColor: '#1E293B', borderRadius: 8, padding: 10, marginBottom: 10 }}>
        <Text style={{ color: '#F1F5F9', fontSize: 13 }}>{detail.description}</Text>
      </View>

      {/* Messages */}
      <ScrollView
        ref={scrollRef}
        style={{ maxHeight: 320, marginBottom: 10 }}
        testID="report-thread-messages"
      >
        {msgs.length === 0 && (
          <Text style={{ color: '#64748B', fontStyle: 'italic', padding: 8, textAlign: 'center' }}>
            Todavia no hay mensajes. Puedes iniciar la conversacion.
          </Text>
        )}
        {msgs.map(m => {
          if (m.is_system) {
            return (
              <View key={m.id} style={{ alignItems: 'center', marginVertical: 6 }}>
                <View style={{ backgroundColor: '#0F172A', borderColor: '#334155', borderWidth: 1, borderRadius: 999, paddingVertical: 3, paddingHorizontal: 10 }}>
                  <Text style={{ color: '#94A3B8', fontSize: 11, fontStyle: 'italic' }}>
                    {m.body}
                  </Text>
                </View>
              </View>
            );
          }
          const mine = isStaffRole(m.sender_role) === staff;
          const bubbleBg = isStaffRole(m.sender_role) ? '#3B82F6' : '#1E293B';
          return (
            <View
              key={m.id}
              style={{ alignItems: mine ? 'flex-end' : 'flex-start', marginVertical: 4 }}
            >
              <View style={{ maxWidth: '85%', backgroundColor: bubbleBg, borderRadius: 10, padding: 8 }}>
                <Text style={{ color: '#F1F5F9', fontSize: 11, fontWeight: '800' }}>
                  {m.sender_username} {isStaffRole(m.sender_role) ? '· Soporte' : ''}
                </Text>
                <Text style={{ color: '#F1F5F9', fontSize: 13 }}>{m.body}</Text>
                <Text style={{ color: '#CBD5E1', fontSize: 9, marginTop: 2, textAlign: 'right' }}>
                  {m.created_at ? new Date(m.created_at).toLocaleString('es-ES', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' }) : ''}
                </Text>
              </View>
            </View>
          );
        })}
      </ScrollView>

      {/* Composer */}
      {closed ? (
        <View style={{ padding: 10, backgroundColor: '#1E293B', borderRadius: 8 }}>
          <Text style={{ color: '#94A3B8', textAlign: 'center', fontStyle: 'italic' }}>
            Este reporte esta cerrado. No se pueden enviar mensajes.
          </Text>
        </View>
      ) : (
        <View style={{ flexDirection: 'row', gap: 6 }}>
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder="Escribe tu mensaje..."
            placeholderTextColor="#475569"
            multiline
            testID="report-thread-input"
            style={{ flex: 1, backgroundColor: '#1E293B', borderRadius: 8, padding: 10, color: '#F1F5F9', borderWidth: 1, borderColor: '#334155', minHeight: 40, maxHeight: 100 }}
          />
          <TouchableOpacity
            onPress={send}
            disabled={sending || !text.trim()}
            testID="report-thread-send"
            style={{ backgroundColor: text.trim() ? '#F59E0B' : '#334155', paddingHorizontal: 14, borderRadius: 8, justifyContent: 'center' }}
          >
            {sending
              ? <ActivityIndicator color="#0F172A" />
              : <Ionicons name="send" size={18} color={text.trim() ? '#0F172A' : '#64748B'} />
            }
          </TouchableOpacity>
        </View>
      )}

      {/* Staff-only status controls */}
      {staff && !closed && (
        <View style={{ flexDirection: 'row', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
          <TouchableOpacity
            disabled={busyStatus}
            onPress={() => changeStatus('awaiting_reporter')}
            testID="report-status-awaiting"
            style={{ backgroundColor: '#1E293B', borderColor: '#F59E0B', borderWidth: 1, borderRadius: 8, paddingVertical: 6, paddingHorizontal: 10 }}
          >
            <Text style={{ color: '#F59E0B', fontSize: 12, fontWeight: '700' }}>Esperando usuario</Text>
          </TouchableOpacity>
          <TouchableOpacity
            disabled={busyStatus}
            onPress={() => changeStatus('in_progress')}
            testID="report-status-inprogress"
            style={{ backgroundColor: '#1E293B', borderColor: '#3B82F6', borderWidth: 1, borderRadius: 8, paddingVertical: 6, paddingHorizontal: 10 }}
          >
            <Text style={{ color: '#3B82F6', fontSize: 12, fontWeight: '700' }}>En curso</Text>
          </TouchableOpacity>
          {viewerRole === 'admin' && (
            <TouchableOpacity
              disabled={busyStatus}
              onPress={() => changeStatus('resolved')}
              testID="report-status-resolved"
              style={{ backgroundColor: '#10B981', borderRadius: 8, paddingVertical: 6, paddingHorizontal: 10 }}
            >
              <Text style={{ color: '#0F172A', fontSize: 12, fontWeight: '800' }}>Marcar resuelto</Text>
            </TouchableOpacity>
          )}
        </View>
      )}
    </View>
  );
};

export default ReportThread;
