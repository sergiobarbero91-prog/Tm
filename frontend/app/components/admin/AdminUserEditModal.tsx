/**
 * AdminUserEditModal — modal completo para que un admin edite un usuario:
 *   - Datos: nombre, licencia, email, telefono, turno, rol
 *   - Gestion de licencias del propietario (añadir / eliminar filas)
 *   - Cambio de contrasena (opcional, en la misma pantalla)
 */
import React, { useEffect, useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView, Modal, Platform,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { RideHistoryList } from './RideHistoryList';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const ROLES: Array<{ value: string; label: string; color: string }> = [
  { value: 'user',        label: 'Usuario',      color: '#64748B' },
  { value: 'conductor',   label: 'Conductor',    color: '#3B82F6' },
  { value: 'propietario', label: 'Propietario',  color: '#8B5CF6' },
  { value: 'moderator',   label: 'Moderador',    color: '#F59E0B' },
  { value: 'admin',       label: 'Admin',        color: '#EF4444' },
];

const SHIFTS: Array<{ value: string; label: string }> = [
  { value: 'all',   label: 'Todos' },
  { value: 'day',   label: 'Dia' },
  { value: 'night', label: 'Noche' },
];

type Licencia = { numero: string; alias: string | null };

type UserDoc = {
  id: string;
  username: string;
  full_name?: string | null;
  license_number?: string | null;
  phone?: string | null;
  email?: string | null;
  role: string;
  preferred_shift?: string;
  licencias?: Licencia[] | null;
};

interface Props {
  visible: boolean;
  user: UserDoc | null;
  onClose: () => void;
  onSaved: () => void;
}

const notify = (msg: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    // eslint-disable-next-line no-alert
    window.alert(msg);
  }
};

export const AdminUserEditModal: React.FC<Props> = ({ visible, user, onClose, onSaved }) => {
  const [full_name, setFullName] = useState('');
  const [license_number, setLicense] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('user');
  const [preferred_shift, setShift] = useState('all');
  const [licencias, setLicencias] = useState<Licencia[]>([]);
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<'data' | 'history'>('data');

  useEffect(() => {
    if (!user) return;
    setFullName(user.full_name || '');
    setLicense(user.license_number || '');
    setPhone(user.phone || '');
    setEmail(user.email || '');
    setRole(user.role || 'user');
    setShift(user.preferred_shift || 'all');
    setLicencias(user.licencias || []);
    setNewPassword('');
  }, [user]);

  const authHeaders = async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  };

  const addLicencia = () => setLicencias(prev => [...prev, { numero: '', alias: null }]);
  const removeLicencia = (idx: number) => setLicencias(prev => prev.filter((_, i) => i !== idx));
  const setLic = (idx: number, patch: Partial<Licencia>) =>
    setLicencias(prev => prev.map((l, i) => i === idx ? { ...l, ...patch } : l));

  const save = async () => {
    if (!user) return;
    setBusy(true);
    try {
      const headers = await authHeaders();
      const payload: any = {
        full_name: full_name.trim(),
        license_number: license_number.trim() || null,
        phone: phone.trim() || null,
        email: email.trim() || null,
        role,
        preferred_shift,
      };
      // Solo enviamos licencias si el rol es propietario o ya tenia licencias
      if (role === 'propietario' || licencias.length > 0) {
        payload.licencias = licencias
          .filter(l => (l.numero || '').trim())
          .map(l => ({ numero: l.numero.trim(), alias: (l.alias || '').trim() || null }));
      }
      await axios.put(`${API_BASE}/api/admin/users/${user.id}`, payload, { headers });

      if (newPassword.trim()) {
        if (newPassword.trim().length < 4) {
          notify('La contrasena debe tener al menos 4 caracteres');
          setBusy(false);
          return;
        }
        await axios.put(
          `${API_BASE}/api/admin/users/${user.id}/password`,
          { new_password: newPassword.trim() },
          { headers },
        );
      }
      onSaved();
      onClose();
      notify('Usuario actualizado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo guardar');
    } finally {
      setBusy(false);
    }
  };

  if (!user) return null;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: '#0008', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
        <View style={{ width: '100%', maxWidth: 520, backgroundColor: '#0F172A', borderRadius: 14, padding: 18, borderWidth: 1, borderColor: '#334155' }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <View>
              <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800' }}>Editar usuario</Text>
              <Text style={{ color: '#94A3B8', fontSize: 12 }}>@{user.username}</Text>
            </View>
            <TouchableOpacity onPress={onClose} testID="admin-user-edit-close">
              <Ionicons name="close" size={22} color="#94A3B8" />
            </TouchableOpacity>
          </View>

          {/* Tabs */}
          <View style={{ flexDirection: 'row', gap: 6, marginBottom: 10 }}>
            <TouchableOpacity
              onPress={() => setTab('data')}
              testID="admin-user-tab-data"
              style={{
                flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center',
                backgroundColor: tab === 'data' ? '#3B82F6' : '#1E293B',
                borderWidth: 1, borderColor: tab === 'data' ? '#3B82F6' : '#334155',
              }}
            >
              <Text style={{ color: tab === 'data' ? '#FFF' : '#94A3B8', fontWeight: '800', fontSize: 12 }}>Datos</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setTab('history')}
              testID="admin-user-tab-history"
              style={{
                flex: 1, paddingVertical: 8, borderRadius: 8, alignItems: 'center',
                backgroundColor: tab === 'history' ? '#3B82F6' : '#1E293B',
                borderWidth: 1, borderColor: tab === 'history' ? '#3B82F6' : '#334155',
              }}
            >
              <Text style={{ color: tab === 'history' ? '#FFF' : '#94A3B8', fontWeight: '800', fontSize: 12 }}>Historial</Text>
            </TouchableOpacity>
          </View>

          {tab === 'history' ? (
            <RideHistoryList endpoint={`admin/users/${user.id}/rides`} perspective="driver" />
          ) : (
          <>
          <ScrollView style={{ maxHeight: 520 }}>
            {/* Basic fields */}
            <Field label="Nombre completo" value={full_name} onChange={setFullName} testID="admin-user-edit-full-name" />
            <Field label="Licencia principal" value={license_number} onChange={setLicense} testID="admin-user-edit-license" keyboard="numeric" />
            <Field label="Telefono" value={phone} onChange={setPhone} testID="admin-user-edit-phone" />
            <Field label="Email" value={email} onChange={setEmail} testID="admin-user-edit-email" />

            {/* Role */}
            <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 6, marginBottom: 4 }}>Rol</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
              {ROLES.map(r => (
                <TouchableOpacity
                  key={r.value}
                  onPress={() => setRole(r.value)}
                  testID={`admin-user-edit-role-${r.value}`}
                  style={{
                    paddingVertical: 6, paddingHorizontal: 10, borderRadius: 999,
                    backgroundColor: role === r.value ? r.color : '#1E293B',
                    borderWidth: 1, borderColor: role === r.value ? r.color : '#334155',
                  }}
                >
                  <Text style={{ color: role === r.value ? '#FFF' : '#94A3B8', fontSize: 12, fontWeight: '700' }}>
                    {r.label}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Shift */}
            <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 6, marginBottom: 4 }}>Turno preferido</Text>
            <View style={{ flexDirection: 'row', gap: 6, marginBottom: 10 }}>
              {SHIFTS.map(s => (
                <TouchableOpacity
                  key={s.value}
                  onPress={() => setShift(s.value)}
                  testID={`admin-user-edit-shift-${s.value}`}
                  style={{
                    paddingVertical: 6, paddingHorizontal: 10, borderRadius: 999,
                    backgroundColor: preferred_shift === s.value ? '#334155' : '#1E293B',
                    borderWidth: 1, borderColor: preferred_shift === s.value ? '#F1F5F9' : '#334155',
                  }}
                >
                  <Text style={{ color: '#F1F5F9', fontSize: 12, fontWeight: '700' }}>{s.label}</Text>
                </TouchableOpacity>
              ))}
            </View>

            {/* Licencias — solo relevantes para propietario, pero permitimos gestionarlas siempre */}
            <View style={{ marginTop: 6, marginBottom: 10 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <Text style={{ color: '#94A3B8', fontSize: 12 }}>
                  Licencias {role === 'propietario' && '(propietario)'}
                </Text>
                <TouchableOpacity onPress={addLicencia} testID="admin-user-edit-add-licencia">
                  <Text style={{ color: '#10B981', fontSize: 12, fontWeight: '800' }}>+ Añadir</Text>
                </TouchableOpacity>
              </View>
              {licencias.length === 0 && (
                <Text style={{ color: '#64748B', fontStyle: 'italic', fontSize: 12 }}>Sin licencias añadidas.</Text>
              )}
              {licencias.map((l, idx) => (
                <View
                  key={idx}
                  testID={`admin-user-edit-licencia-row-${idx}`}
                  style={{ flexDirection: 'row', gap: 6, marginBottom: 6, alignItems: 'center' }}
                >
                  <TextInput
                    value={l.numero}
                    onChangeText={v => setLic(idx, { numero: v })}
                    placeholder="Numero"
                    placeholderTextColor="#64748B"
                    keyboardType="numeric"
                    testID={`admin-user-edit-licencia-num-${idx}`}
                    style={{ flex: 1, backgroundColor: '#1E293B', color: '#F1F5F9', paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: '#334155' }}
                  />
                  <TextInput
                    value={l.alias || ''}
                    onChangeText={v => setLic(idx, { alias: v })}
                    placeholder="Alias (opcional)"
                    placeholderTextColor="#64748B"
                    testID={`admin-user-edit-licencia-alias-${idx}`}
                    style={{ flex: 1, backgroundColor: '#1E293B', color: '#F1F5F9', paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: '#334155' }}
                  />
                  <TouchableOpacity
                    onPress={() => removeLicencia(idx)}
                    testID={`admin-user-edit-licencia-remove-${idx}`}
                    style={{ padding: 6 }}
                  >
                    <Ionicons name="trash-outline" size={18} color="#EF4444" />
                  </TouchableOpacity>
                </View>
              ))}
            </View>

            {/* Password */}
            <Field
              label="Nueva contrasena (dejar en blanco para no cambiar)"
              value={newPassword}
              onChange={setNewPassword}
              secure
              testID="admin-user-edit-new-password"
            />
          </ScrollView>

          <TouchableOpacity
            onPress={save}
            disabled={busy}
            testID="admin-user-edit-save"
            style={{ marginTop: 10, backgroundColor: '#3B82F6', paddingVertical: 12, borderRadius: 10, alignItems: 'center' }}
          >
            {busy ? <ActivityIndicator color="#FFF" /> : <Text style={{ color: '#FFF', fontWeight: '800' }}>Guardar cambios</Text>}
          </TouchableOpacity>
          </>
          )}
        </View>
      </View>
    </Modal>
  );
};

const Field: React.FC<{
  label: string; value: string; onChange: (v: string) => void;
  secure?: boolean; keyboard?: 'default' | 'numeric'; testID?: string;
}> = ({ label, value, onChange, secure, keyboard, testID }) => (
  <View style={{ marginBottom: 8 }}>
    <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>{label}</Text>
    <TextInput
      value={value}
      onChangeText={onChange}
      secureTextEntry={secure}
      keyboardType={keyboard || 'default'}
      autoCapitalize="none"
      testID={testID}
      style={{ backgroundColor: '#1E293B', color: '#F1F5F9', paddingHorizontal: 10, paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: '#334155' }}
    />
  </View>
);

export default AdminUserEditModal;
