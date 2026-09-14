/**
 * AdminClients — panel para que un admin gestione clientes de la Emisora.
 *
 * Renderiza dentro del tab Admin. Endpoints usados:
 *   GET    /api/admin/clients
 *   GET    /api/admin/clients/search?q=...
 *   POST   /api/admin/clients
 *   PUT    /api/admin/clients/{id}
 *   PUT    /api/admin/clients/{id}/password
 *   DELETE /api/admin/clients/{id}
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, TouchableOpacity, TextInput, ActivityIndicator, ScrollView,
  Modal, Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type Client = {
  id: string;
  phone: string;
  first_name: string;
  last_name: string;
  email: string | null;
  associated_driver_id: string | null;
  associated_driver_name: string | null;
  has_password: boolean;
  created_at: string;
  updated_at: string | null;
};

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

export const AdminClients: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);
  const [query, setQuery] = useState('');

  const [createOpen, setCreateOpen] = useState(false);
  const [createBusy, setCreateBusy] = useState(false);
  const [form, setForm] = useState({ phone: '+34', first_name: '', last_name: '', email: '', password: '' });

  const [editing, setEditing] = useState<Client | null>(null);
  const [editBusy, setEditBusy] = useState(false);
  const [editForm, setEditForm] = useState({ phone: '', first_name: '', last_name: '', email: '', new_password: '' });

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  const refresh = useCallback(async (q?: string) => {
    setLoading(true);
    try {
      const headers = await authHeaders();
      const url = q && q.trim()
        ? `${API_BASE}/api/admin/clients/search?q=${encodeURIComponent(q.trim())}`
        : `${API_BASE}/api/admin/clients`;
      const r = await axios.get(url, { headers });
      setClients(r.data || []);
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'Error cargando clientes');
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => { refresh(); }, [refresh]);

  const doCreate = async () => {
    if (!form.phone.startsWith('+') || form.phone.length < 8) return notify('Telefono en formato +34...');
    if (!form.first_name.trim() || !form.last_name.trim()) return notify('Nombre y apellido son obligatorios');
    setCreateBusy(true);
    try {
      const headers = await authHeaders();
      await axios.post(`${API_BASE}/api/admin/clients`, {
        phone: form.phone.trim(),
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        email: form.email.trim() || null,
        password: form.password.trim() || null,
      }, { headers });
      setCreateOpen(false);
      setForm({ phone: '+34', first_name: '', last_name: '', email: '', password: '' });
      await refresh(query);
      notify('Cliente creado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo crear');
    } finally {
      setCreateBusy(false);
    }
  };

  const openEdit = (c: Client) => {
    setEditing(c);
    setEditForm({
      phone: c.phone,
      first_name: c.first_name,
      last_name: c.last_name,
      email: c.email || '',
      new_password: '',
    });
  };

  const doUpdate = async () => {
    if (!editing) return;
    setEditBusy(true);
    try {
      const headers = await authHeaders();
      await axios.put(`${API_BASE}/api/admin/clients/${editing.id}`, {
        phone: editForm.phone.trim(),
        first_name: editForm.first_name.trim(),
        last_name: editForm.last_name.trim(),
        email: editForm.email.trim() || null,
      }, { headers });
      if (editForm.new_password.trim()) {
        if (editForm.new_password.trim().length < 4) {
          notify('La contrasena debe tener al menos 4 caracteres');
          setEditBusy(false);
          return;
        }
        await axios.put(`${API_BASE}/api/admin/clients/${editing.id}/password`, {
          new_password: editForm.new_password.trim(),
        }, { headers });
      }
      setEditing(null);
      await refresh(query);
      notify('Cliente actualizado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo actualizar');
    } finally {
      setEditBusy(false);
    }
  };

  const doDelete = async (c: Client) => {
    if (!confirmWeb(`¿Eliminar cliente ${c.first_name} ${c.last_name} (${c.phone})?`)) return;
    try {
      const headers = await authHeaders();
      await axios.delete(`${API_BASE}/api/admin/clients/${c.id}`, { headers });
      await refresh(query);
      notify('Cliente eliminado');
    } catch (e: any) {
      notify(e?.response?.data?.detail || 'No se pudo eliminar');
    }
  };

  return (
    <View style={{ padding: 12 }} testID="admin-clients">
      {/* Header */}
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Ionicons name="people-circle" size={22} color="#F59E0B" />
          <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 18 }}>Clientes ({clients.length})</Text>
        </View>
        <TouchableOpacity
          onPress={() => setCreateOpen(true)}
          testID="admin-clients-create-btn"
          style={{ backgroundColor: '#10B981', paddingVertical: 8, paddingHorizontal: 12, borderRadius: 8, flexDirection: 'row', alignItems: 'center', gap: 4 }}
        >
          <Ionicons name="add" size={16} color="#0F172A" />
          <Text style={{ color: '#0F172A', fontWeight: '800', fontSize: 12 }}>Nuevo cliente</Text>
        </TouchableOpacity>
      </View>

      {/* Search */}
      <View style={{ flexDirection: 'row', gap: 8, marginBottom: 12 }}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={() => refresh(query)}
          placeholder="Buscar por telefono, nombre o email..."
          placeholderTextColor="#64748B"
          testID="admin-clients-search-input"
          style={{ flex: 1, backgroundColor: '#1E293B', color: '#F1F5F9', paddingHorizontal: 12, paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: '#334155' }}
        />
        <TouchableOpacity onPress={() => refresh(query)} style={{ backgroundColor: '#334155', paddingHorizontal: 12, justifyContent: 'center', borderRadius: 8 }}>
          <Ionicons name="search" size={18} color="#F1F5F9" />
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator color="#F59E0B" />
      ) : clients.length === 0 ? (
        <Text style={{ color: '#64748B', fontStyle: 'italic', marginTop: 12 }}>Sin clientes.</Text>
      ) : (
        clients.map(c => (
          <View
            key={c.id}
            testID={`admin-client-row-${c.id}`}
            style={{ backgroundColor: '#1E293B', borderRadius: 10, padding: 12, marginBottom: 8, borderLeftWidth: 3, borderLeftColor: c.has_password ? '#10B981' : '#F59E0B' }}
          >
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: '#F1F5F9', fontWeight: '800' }}>{c.first_name} {c.last_name}</Text>
                <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 2 }}>
                  <Ionicons name="call" size={11} color="#94A3B8" /> {c.phone}
                </Text>
                {c.email && (
                  <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 2 }}>
                    <Ionicons name="mail" size={11} color="#94A3B8" /> {c.email}
                  </Text>
                )}
                {c.associated_driver_name && (
                  <Text style={{ color: '#8B5CF6', fontSize: 11, marginTop: 4 }}>
                    Taxista asociado: {c.associated_driver_name}
                  </Text>
                )}
                {!c.has_password && (
                  <Text style={{ color: '#F59E0B', fontSize: 11, marginTop: 4 }}>Sin contrasena</Text>
                )}
              </View>
              <View style={{ flexDirection: 'row', gap: 6 }}>
                <TouchableOpacity
                  onPress={() => openEdit(c)}
                  testID={`admin-client-edit-${c.id}`}
                  style={{ padding: 6, borderRadius: 6, backgroundColor: '#334155' }}
                >
                  <Ionicons name="create-outline" size={16} color="#3B82F6" />
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => doDelete(c)}
                  testID={`admin-client-delete-${c.id}`}
                  style={{ padding: 6, borderRadius: 6, backgroundColor: '#334155' }}
                >
                  <Ionicons name="trash-outline" size={16} color="#EF4444" />
                </TouchableOpacity>
              </View>
            </View>
          </View>
        ))
      )}

      {/* ------------------------ CREATE MODAL ------------------------ */}
      <Modal visible={createOpen} transparent animationType="fade" onRequestClose={() => setCreateOpen(false)}>
        <View style={{ flex: 1, backgroundColor: '#0008', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 460, backgroundColor: '#0F172A', borderRadius: 14, padding: 18, borderWidth: 1, borderColor: '#334155' }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800' }}>Nuevo cliente</Text>
              <TouchableOpacity onPress={() => setCreateOpen(false)}>
                <Ionicons name="close" size={22} color="#94A3B8" />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 480 }}>
              <FormField label="Telefono (E.164)" value={form.phone} onChange={v => setForm({ ...form, phone: v })} testID="admin-client-form-phone" />
              <FormField label="Nombre" value={form.first_name} onChange={v => setForm({ ...form, first_name: v })} testID="admin-client-form-first-name" />
              <FormField label="Apellido" value={form.last_name} onChange={v => setForm({ ...form, last_name: v })} testID="admin-client-form-last-name" />
              <FormField label="Email (opcional)" value={form.email} onChange={v => setForm({ ...form, email: v })} testID="admin-client-form-email" />
              <FormField label="Contrasena (opcional)" value={form.password} onChange={v => setForm({ ...form, password: v })} secure testID="admin-client-form-password" />
            </ScrollView>
            <TouchableOpacity
              onPress={doCreate}
              disabled={createBusy}
              testID="admin-client-form-submit"
              style={{ marginTop: 8, backgroundColor: '#10B981', paddingVertical: 12, borderRadius: 10, alignItems: 'center' }}
            >
              {createBusy ? <ActivityIndicator color="#0F172A" /> : <Text style={{ color: '#0F172A', fontWeight: '800' }}>Crear</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* ------------------------ EDIT MODAL ------------------------ */}
      <Modal visible={!!editing} transparent animationType="fade" onRequestClose={() => setEditing(null)}>
        <View style={{ flex: 1, backgroundColor: '#0008', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 460, backgroundColor: '#0F172A', borderRadius: 14, padding: 18, borderWidth: 1, borderColor: '#334155' }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800' }}>Editar cliente</Text>
              <TouchableOpacity onPress={() => setEditing(null)}>
                <Ionicons name="close" size={22} color="#94A3B8" />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 480 }}>
              <FormField label="Telefono" value={editForm.phone} onChange={v => setEditForm({ ...editForm, phone: v })} testID="admin-client-edit-phone" />
              <FormField label="Nombre" value={editForm.first_name} onChange={v => setEditForm({ ...editForm, first_name: v })} testID="admin-client-edit-first-name" />
              <FormField label="Apellido" value={editForm.last_name} onChange={v => setEditForm({ ...editForm, last_name: v })} testID="admin-client-edit-last-name" />
              <FormField label="Email" value={editForm.email} onChange={v => setEditForm({ ...editForm, email: v })} testID="admin-client-edit-email" />
              <FormField label="Nueva contrasena (dejar en blanco para no cambiar)" value={editForm.new_password} onChange={v => setEditForm({ ...editForm, new_password: v })} secure testID="admin-client-edit-password" />
            </ScrollView>
            <TouchableOpacity
              onPress={doUpdate}
              disabled={editBusy}
              testID="admin-client-edit-submit"
              style={{ marginTop: 8, backgroundColor: '#3B82F6', paddingVertical: 12, borderRadius: 10, alignItems: 'center' }}
            >
              {editBusy ? <ActivityIndicator color="#FFF" /> : <Text style={{ color: '#FFF', fontWeight: '800' }}>Guardar</Text>}
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    </View>
  );
};

const FormField: React.FC<{
  label: string; value: string; onChange: (v: string) => void;
  secure?: boolean; testID?: string;
}> = ({ label, value, onChange, secure, testID }) => (
  <View style={{ marginBottom: 10 }}>
    <Text style={{ color: '#94A3B8', fontSize: 12, marginBottom: 4 }}>{label}</Text>
    <TextInput
      value={value}
      onChangeText={onChange}
      secureTextEntry={secure}
      autoCapitalize="none"
      testID={testID}
      style={{ backgroundColor: '#1E293B', color: '#F1F5F9', paddingHorizontal: 12, paddingVertical: 10, borderRadius: 8, borderWidth: 1, borderColor: '#334155' }}
    />
  </View>
);

export default AdminClients;
