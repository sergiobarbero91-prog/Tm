/**
 * PoiPanel — Puntos de Interés tab content.
 *
 * Shows the closest POI per type from the driver's current position:
 * hospital con urgencias, farmacia 24 h, gasolinera 24 h, ocio nocturno,
 * estanco 24 h y discoteca (más los tipos custom que agreguen admin/mod).
 * Admin/moderator ven un botón flotante para crear/editar tipos y sitios.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator, Modal, TextInput, Platform, ScrollView, Alert, Switch } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import { AddressAutocomplete } from './AddressAutocomplete';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

type PoiType = {
  id: string;
  key: string;
  label: string;
  icon: string;
  manual_only: boolean;
  builtin: boolean;
};

type Poi = {
  id: string;
  type_key: string;
  name: string;
  address?: string | null;
  lat: number;
  lon: number;
  notes?: string | null;
  is_seed: boolean;
  distance_km?: number;
};

type NearbyEntry = { type: PoiType; closest: Poi | null };

const openExternalUrl = (url: string) => {
  if (Platform.OS === 'web' && typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const Linking = require('react-native').Linking;
    Linking.openURL(url);
  } catch { /* ignore */ }
};

const googleMapsUrl = (p: Poi) =>
  `https://www.google.com/maps/dir/?api=1&destination=${p.lat},${p.lon}&travelmode=driving`;

const wazeUrl = (p: Poi) => `https://waze.com/ul?ll=${p.lat},${p.lon}&navigate=yes`;

const navUrl = (p: Poi, nav: 'google_maps' | 'waze') =>
  nav === 'waze' ? wazeUrl(p) : googleMapsUrl(p);

export const PoiPanel: React.FC<{ isStaff: boolean; preferredNavigator?: 'google_maps' | 'waze' }> = ({ isStaff, preferredNavigator = 'google_maps' }) => {
  const [pos, setPos] = useState<{ lat: number; lon: number } | null>(null);
  const [entries, setEntries] = useState<NearbyEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [locError, setLocError] = useState<string | null>(null);

  // Admin/mod management modal
  const [adminOpen, setAdminOpen] = useState(false);
  const [types, setTypes] = useState<PoiType[]>([]);
  const [pois, setPois] = useState<Poi[]>([]);
  const [activeTypeKey, setActiveTypeKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [addSiteMode, setAddSiteMode] = useState(false);
  const [editingSiteId, setEditingSiteId] = useState<string | null>(null);
  const [addTypeMode, setAddTypeMode] = useState(false);
  const [siteForm, setSiteForm] = useState({ name: '', address: '', lat: '', lon: '', notes: '' });
  const [typeForm, setTypeForm] = useState({ key: '', label: '', icon: 'location', manual_only: false });

  const authHeaders = useCallback(async () => {
    const tk = await AsyncStorage.getItem('token');
    return tk ? { Authorization: `Bearer ${tk}` } : {};
  }, []);

  useEffect(() => {
    if (Platform.OS !== 'web' || typeof navigator === 'undefined' || !navigator.geolocation) {
      setLocError('Tu navegador no soporta geolocalización');
      setLoading(false);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      p => setPos({ lat: p.coords.latitude, lon: p.coords.longitude }),
      err => { setLocError(err?.message || 'No se pudo obtener la ubicación'); setLoading(false); },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 },
    );
  }, []);

  const refreshNearby = useCallback(async () => {
    if (!pos) return;
    setLoading(true);
    try {
      const r = await axios.get(`${API_BASE}/api/pois/nearby`, {
        params: { lat: pos.lat, lon: pos.lon },
        headers: await authHeaders(),
      });
      setEntries(r.data || []);
    } catch { /* silent */ } finally { setLoading(false); }
  }, [pos, authHeaders]);

  useEffect(() => { refreshNearby(); }, [refreshNearby]);

  const openAdmin = async () => {
    setAdminOpen(true);
    try {
      const [tRes, pRes] = await Promise.all([
        axios.get(`${API_BASE}/api/pois/types`, { headers: await authHeaders() }),
        axios.get(`${API_BASE}/api/pois`, { headers: await authHeaders() }),
      ]);
      setTypes(tRes.data || []);
      setPois(pRes.data || []);
      setActiveTypeKey(tRes.data?.[0]?.key || null);
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'No se pudo cargar el catálogo');
    }
  };

  const submitType = async () => {
    if (typeForm.key.trim().length < 2 || typeForm.label.trim().length < 2) return;
    setBusy(true);
    try {
      const r = await axios.post(`${API_BASE}/api/pois/types`, typeForm, { headers: await authHeaders() });
      setTypes([...types, r.data]);
      setActiveTypeKey(r.data.key);
      setAddTypeMode(false);
      setTypeForm({ key: '', label: '', icon: 'location', manual_only: false });
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'No se pudo crear el tipo');
    } finally { setBusy(false); }
  };

  const submitSite = async () => {
    if (!activeTypeKey) return;
    const lat = parseFloat(siteForm.lat), lon = parseFloat(siteForm.lon);
    if (isNaN(lat) || isNaN(lon) || siteForm.name.trim().length < 2) {
      Alert.alert('Error', 'Nombre, latitud y longitud son obligatorios');
      return;
    }
    setBusy(true);
    try {
      if (editingSiteId) {
        const r = await axios.put(`${API_BASE}/api/pois/${editingSiteId}`, {
          name: siteForm.name, address: siteForm.address || null,
          lat, lon, notes: siteForm.notes || null,
        }, { headers: await authHeaders() });
        setPois(pois.map(p => (p.id === editingSiteId ? r.data : p)));
      } else {
        const r = await axios.post(`${API_BASE}/api/pois`, {
          type_key: activeTypeKey, name: siteForm.name, address: siteForm.address || null,
          lat, lon, notes: siteForm.notes || null,
        }, { headers: await authHeaders() });
        setPois([r.data, ...pois]);
      }
      setSiteForm({ name: '', address: '', lat: '', lon: '', notes: '' });
      setAddSiteMode(false);
      setEditingSiteId(null);
      refreshNearby();
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'No se pudo guardar el sitio');
    } finally { setBusy(false); }
  };

  const startEditSite = (p: Poi) => {
    setEditingSiteId(p.id);
    setActiveTypeKey(p.type_key);
    setSiteForm({
      name: p.name,
      address: p.address || '',
      lat: String(p.lat),
      lon: String(p.lon),
      notes: p.notes || '',
    });
    setAddSiteMode(true);
  };

  const deleteSite = async (id: string) => {
    if (Platform.OS === 'web' && !window.confirm('¿Borrar este sitio?')) return;
    try {
      await axios.delete(`${API_BASE}/api/pois/${id}`, { headers: await authHeaders() });
      setPois(pois.filter(p => p.id !== id));
      refreshNearby();
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'No se pudo borrar');
    }
  };

  const deleteType = async (t: PoiType) => {
    if (t.builtin) return;
    if (Platform.OS === 'web' && !window.confirm(`¿Borrar el tipo "${t.label}" y todos sus sitios?`)) return;
    try {
      await axios.delete(`${API_BASE}/api/pois/types/${t.id}`, { headers: await authHeaders() });
      setTypes(types.filter(x => x.id !== t.id));
      setPois(pois.filter(p => p.type_key !== t.key));
      refreshNearby();
    } catch (e: any) {
      Alert.alert('Error', e?.response?.data?.detail || 'No se pudo borrar el tipo');
    }
  };

  const filteredPois = useMemo(
    () => pois.filter(p => p.type_key === activeTypeKey),
    [pois, activeTypeKey],
  );

  if (loading && !entries.length) {
    return (
      <View style={{ padding: 24, alignItems: 'center' }}>
        <ActivityIndicator color="#6366F1" />
        <Text style={{ color: '#94A3B8', marginTop: 10 }}>Buscando puntos cercanos…</Text>
      </View>
    );
  }
  if (locError) {
    return (
      <View style={{ padding: 20 }}>
        <Text style={{ color: '#F59E0B', fontWeight: '700' }}>Permiso de ubicación necesario</Text>
        <Text style={{ color: '#94A3B8', marginTop: 6 }}>{locError}</Text>
      </View>
    );
  }

  return (
    <View style={{ padding: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <Text style={{ color: '#F1F5F9', fontSize: 16, fontWeight: '800' }}>Puntos de interés cerca</Text>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          <TouchableOpacity onPress={refreshNearby} disabled={loading} testID="poi-refresh" style={{ padding: 6 }}>
            <Ionicons name={loading ? 'sync' : 'refresh'} size={18} color="#94A3B8" />
          </TouchableOpacity>
          {isStaff && (
            <TouchableOpacity onPress={openAdmin} testID="poi-admin-btn" style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, backgroundColor: '#F59E0B' }}>
              <Ionicons name="options" size={14} color="#0F172A" />
              <Text style={{ color: '#0F172A', fontWeight: '800', fontSize: 12 }}>Gestionar</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>

      {entries.map(e => (
        <View key={e.type.key} testID={`poi-card-${e.type.key}`} style={{ backgroundColor: '#1E293B', borderRadius: 12, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: '#334155' }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: '#0F172A', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#F59E0B' }}>
              <Ionicons name={(e.type.icon || 'location') as any} size={16} color="#F59E0B" />
            </View>
            <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 13, flex: 1 }}>{e.type.label}</Text>
            {e.closest?.distance_km != null && (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, backgroundColor: '#0F172A', borderWidth: 1, borderColor: '#10B981' }}>
                <Ionicons name="navigate" size={10} color="#10B981" />
                <Text style={{ color: '#10B981', fontSize: 10, fontWeight: '800' }}>
                  {e.closest.distance_km < 1 ? `${Math.round(e.closest.distance_km * 1000)} m` : `${e.closest.distance_km.toFixed(1)} km`}
                </Text>
              </View>
            )}
          </View>
          {e.closest ? (
            <>
              <Text style={{ color: '#F1F5F9', fontSize: 14, fontWeight: '700' }}>{e.closest.name}</Text>
              {e.closest.address && (
                <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 2 }}>{e.closest.address}</Text>
              )}
              <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
                <TouchableOpacity
                  onPress={() => openExternalUrl(navUrl(e.closest as Poi, preferredNavigator))}
                  style={{ flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, borderRadius: 8, backgroundColor: '#0F172A', borderWidth: 1, borderColor: preferredNavigator === 'waze' ? '#8B5CF6' : '#3B82F6' }}
                  testID={`poi-nav-${e.type.key}`}
                >
                  <Ionicons name={preferredNavigator === 'waze' ? 'navigate-circle' : 'map'} size={14} color={preferredNavigator === 'waze' ? '#8B5CF6' : '#3B82F6'} />
                  <Text style={{ color: preferredNavigator === 'waze' ? '#8B5CF6' : '#3B82F6', fontWeight: '800', fontSize: 12 }}>
                    Navegar con {preferredNavigator === 'waze' ? 'Waze' : 'Google Maps'}
                  </Text>
                </TouchableOpacity>
              </View>
            </>
          ) : (
            <Text style={{ color: '#64748B', fontStyle: 'italic', fontSize: 12 }}>
              {e.type.manual_only ? 'Los administradores aún no han añadido sitios.' : 'Sin datos por ahora.'}
            </Text>
          )}
        </View>
      ))}

      {/* Admin management modal */}
      <Modal visible={adminOpen} transparent animationType="fade" onRequestClose={() => setAdminOpen(false)}>
        <View style={{ flex: 1, backgroundColor: '#000A', alignItems: 'center', justifyContent: 'center', padding: 12 }}>
          <View style={{ width: '100%', maxWidth: 620, maxHeight: '92%', backgroundColor: '#0F172A', borderRadius: 14, padding: 16, borderWidth: 1, borderColor: '#334155' }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <Text style={{ color: '#F1F5F9', fontWeight: '800', fontSize: 16 }}>Gestionar Puntos de Interés</Text>
              <TouchableOpacity onPress={() => setAdminOpen(false)} testID="poi-admin-close">
                <Ionicons name="close" size={22} color="#94A3B8" />
              </TouchableOpacity>
            </View>

            {/* Type selector */}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
              <View style={{ flexDirection: 'row', gap: 6 }}>
                {types.map(t => (
                  <TouchableOpacity
                    key={t.id}
                    onPress={() => setActiveTypeKey(t.key)}
                    onLongPress={() => !t.builtin && deleteType(t)}
                    testID={`poi-type-chip-${t.key}`}
                    style={{ paddingVertical: 6, paddingHorizontal: 10, borderRadius: 999, backgroundColor: activeTypeKey === t.key ? '#F59E0B' : '#1E293B', borderWidth: 1, borderColor: activeTypeKey === t.key ? '#F59E0B' : '#334155', flexDirection: 'row', alignItems: 'center', gap: 4 }}
                  >
                    <Ionicons name={(t.icon || 'location') as any} size={12} color={activeTypeKey === t.key ? '#0F172A' : '#94A3B8'} />
                    <Text style={{ color: activeTypeKey === t.key ? '#0F172A' : '#F1F5F9', fontSize: 12, fontWeight: '700' }}>{t.label}</Text>
                    {!t.builtin && (
                      <Ionicons name="trash-outline" size={11} color={activeTypeKey === t.key ? '#0F172A' : '#EF4444'} />
                    )}
                  </TouchableOpacity>
                ))}
                <TouchableOpacity
                  onPress={() => setAddTypeMode(true)}
                  testID="poi-add-type-chip"
                  style={{ paddingVertical: 6, paddingHorizontal: 10, borderRadius: 999, backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#10B981', flexDirection: 'row', alignItems: 'center', gap: 4 }}
                >
                  <Ionicons name="add" size={13} color="#10B981" />
                  <Text style={{ color: '#10B981', fontSize: 12, fontWeight: '800' }}>Nuevo tipo</Text>
                </TouchableOpacity>
              </View>
            </ScrollView>

            {/* New type form */}
            {addTypeMode && (
              <View style={{ backgroundColor: '#020617', borderRadius: 10, padding: 10, marginBottom: 10, borderWidth: 1, borderColor: '#334155' }}>
                <Text style={{ color: '#F59E0B', fontWeight: '800', marginBottom: 6, fontSize: 12 }}>Crear tipo</Text>
                <TextInput value={typeForm.key} onChangeText={v => setTypeForm({ ...typeForm, key: v.toLowerCase().replace(/[^a-z0-9_]/g, '') })} placeholder="clave (ej: taxi_stand)" placeholderTextColor="#475569" testID="poi-type-key" style={{ backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, marginBottom: 6, fontSize: 12 }} />
                <TextInput value={typeForm.label} onChangeText={v => setTypeForm({ ...typeForm, label: v })} placeholder="Etiqueta (ej: Parada de taxi)" placeholderTextColor="#475569" testID="poi-type-label" style={{ backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, marginBottom: 6, fontSize: 12 }} />
                <TextInput value={typeForm.icon} onChangeText={v => setTypeForm({ ...typeForm, icon: v })} placeholder="Icono Ionicons (ej: car)" placeholderTextColor="#475569" testID="poi-type-icon" style={{ backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, marginBottom: 6, fontSize: 12 }} />
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Switch value={typeForm.manual_only} onValueChange={v => setTypeForm({ ...typeForm, manual_only: v })} />
                  <Text style={{ color: '#94A3B8', fontSize: 12 }}>Solo manual (sin auto-seed)</Text>
                </View>
                <View style={{ flexDirection: 'row', gap: 6 }}>
                  <TouchableOpacity onPress={() => setAddTypeMode(false)} style={{ flex: 1, padding: 8, borderRadius: 6, borderWidth: 1, borderColor: '#334155', alignItems: 'center' }}>
                    <Text style={{ color: '#94A3B8', fontWeight: '700', fontSize: 12 }}>Cancelar</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={submitType} disabled={busy} testID="poi-type-submit" style={{ flex: 1, padding: 8, borderRadius: 6, backgroundColor: '#F59E0B', alignItems: 'center', opacity: busy ? 0.6 : 1 }}>
                    <Text style={{ color: '#0F172A', fontWeight: '800', fontSize: 12 }}>Crear tipo</Text>
                  </TouchableOpacity>
                </View>
              </View>
            )}

            {/* Add site button */}
            {activeTypeKey && !addSiteMode && (
              <TouchableOpacity onPress={() => setAddSiteMode(true)} testID="poi-add-site-btn" style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 8, borderRadius: 8, backgroundColor: '#1E293B', borderWidth: 1, borderColor: '#10B981', marginBottom: 10 }}>
                <Ionicons name="add-circle" size={16} color="#10B981" />
                <Text style={{ color: '#10B981', fontWeight: '800', fontSize: 12 }}>Añadir sitio</Text>
              </TouchableOpacity>
            )}

            {/* Add site form */}
            {addSiteMode && (
              <View style={{ backgroundColor: '#020617', borderRadius: 10, padding: 10, marginBottom: 10, borderWidth: 1, borderColor: '#334155' }}>
                <Text style={{ color: '#10B981', fontWeight: '800', marginBottom: 6, fontSize: 12 }}>
                  {editingSiteId ? 'Editar sitio' : 'Añadir sitio'}
                </Text>
                <TextInput value={siteForm.name} onChangeText={v => setSiteForm({ ...siteForm, name: v })} placeholder="Nombre" placeholderTextColor="#475569" testID="poi-site-name" style={{ backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, marginBottom: 6, fontSize: 12 }} />
                <AddressAutocomplete
                  value={siteForm.address}
                  onChange={v => setSiteForm({ ...siteForm, address: v })}
                  onPick={s => setSiteForm({ ...siteForm, address: s.address, lat: String(s.lat), lon: String(s.lon) })}
                  placeholder="Dirección (busca o escribe)"
                  tokenKey="token"
                  testID="poi-site-address"
                />
                <View style={{ flexDirection: 'row', gap: 6, marginBottom: 6 }}>
                  <TextInput value={siteForm.lat} onChangeText={v => setSiteForm({ ...siteForm, lat: v })} placeholder="Latitud" placeholderTextColor="#475569" testID="poi-site-lat" style={{ flex: 1, backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, fontSize: 12 }} />
                  <TextInput value={siteForm.lon} onChangeText={v => setSiteForm({ ...siteForm, lon: v })} placeholder="Longitud" placeholderTextColor="#475569" testID="poi-site-lon" style={{ flex: 1, backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, fontSize: 12 }} />
                </View>
                <TextInput value={siteForm.notes} onChangeText={v => setSiteForm({ ...siteForm, notes: v })} placeholder="Notas (opcional)" placeholderTextColor="#475569" style={{ backgroundColor: '#0F172A', color: '#F1F5F9', padding: 8, borderRadius: 6, marginBottom: 6, fontSize: 12 }} />
                <View style={{ flexDirection: 'row', gap: 6 }}>
                  <TouchableOpacity onPress={() => { setAddSiteMode(false); setEditingSiteId(null); setSiteForm({ name: '', address: '', lat: '', lon: '', notes: '' }); }} style={{ flex: 1, padding: 8, borderRadius: 6, borderWidth: 1, borderColor: '#334155', alignItems: 'center' }}>
                    <Text style={{ color: '#94A3B8', fontWeight: '700', fontSize: 12 }}>Cancelar</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={submitSite} disabled={busy} testID="poi-site-submit" style={{ flex: 1, padding: 8, borderRadius: 6, backgroundColor: '#10B981', alignItems: 'center', opacity: busy ? 0.6 : 1 }}>
                    <Text style={{ color: '#0F172A', fontWeight: '800', fontSize: 12 }}>
                      {editingSiteId ? 'Actualizar sitio' : 'Guardar sitio'}
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>
            )}

            {/* Sites list */}
            <ScrollView style={{ maxHeight: 320 }}>
              {filteredPois.length === 0 && (
                <Text style={{ color: '#64748B', fontStyle: 'italic', fontSize: 12, textAlign: 'center', paddingVertical: 20 }}>
                  Sin sitios en esta categoría todavía.
                </Text>
              )}
              {filteredPois.map(p => (
                <View key={p.id} testID={`poi-row-${p.id}`} style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: '#1E293B', borderRadius: 8, padding: 10, marginBottom: 6, borderWidth: 1, borderColor: p.is_seed ? '#334155' : '#10B981' }}>
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: '#F1F5F9', fontWeight: '700', fontSize: 13 }}>{p.name}</Text>
                    {p.address && <Text style={{ color: '#94A3B8', fontSize: 11 }}>{p.address}</Text>}
                    <Text style={{ color: '#64748B', fontSize: 10 }}>
                      {p.lat.toFixed(4)}, {p.lon.toFixed(4)} · {p.is_seed ? 'seed' : 'manual'}
                    </Text>
                  </View>
                  <TouchableOpacity onPress={() => startEditSite(p)} testID={`poi-edit-${p.id}`} style={{ padding: 6 }}>
                    <Ionicons name="create-outline" size={16} color="#F59E0B" />
                  </TouchableOpacity>
                  <TouchableOpacity onPress={() => deleteSite(p.id)} testID={`poi-delete-${p.id}`} style={{ padding: 6 }}>
                    <Ionicons name="trash-outline" size={16} color="#EF4444" />
                  </TouchableOpacity>
                </View>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
};

export default PoiPanel;
