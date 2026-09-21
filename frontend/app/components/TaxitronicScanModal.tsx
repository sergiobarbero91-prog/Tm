/**
 * TaxitronicScanModal
 * -------------------
 * Full review UI for the fail-safe Taxitronic OCR pipeline.
 *
 * Flow expected from the parent screen:
 *   1. Parent captures a photo (camera or file input) and hands us the `File`.
 *   2. This modal POSTs it to `/api/tickets/taxitronic/scan`.
 *   3. It renders the returned evidence — per-field value, confidence bar,
 *      and flags (format / consensus / math).
 *   4. Any field can be corrected inline. Corrections are tracked so the
 *      backend can audit `user_edited_fields`.
 *   5. On confirm we POST to `/api/tickets/taxitronic/confirm`.
 *
 * Design principles:
 *   - Never lie about confidence. Green only when accepted AND overall > 0.85.
 *   - Never silently save a math mismatch — big amber banner + block confirm
 *     until user acknowledges via checkbox.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Modal, Platform, ScrollView, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';

const API_BASE = (
  (typeof process !== 'undefined' && (process as any).env?.EXPO_PUBLIC_BACKEND_URL) ||
  (typeof process !== 'undefined' && (process as any).env?.REACT_APP_BACKEND_URL) ||
  ''
);

// ─────────────────────────── Types (mirror backend ScanResult) ───────────────────────────
type FieldEvidence = {
  value: any;
  raw_text: string | null;
  ocr_confidence: number;      // 0..1
  format_valid: boolean;
  consensus: boolean;
  validation_valid: boolean;
  final_confidence: number;    // 0..1
  notes: string[];
};

type ValidationBlock = {
  total_matches: boolean | null;
  period_total_matches: boolean | null;
  distance_validated: boolean;
  time_validated: boolean;
  errors: string[];
};

type ScanResult = {
  document_type: 'taxitronic_partial';
  status: 'accepted' | 'needs_confirmation' | 'rejected';
  overall_confidence: number;
  fields: Record<string, FieldEvidence>;
  ticket: Record<string, any>;
  totals: Record<string, any>;
  distance: Record<string, any>;
  time: Record<string, any>;
  deleted: number | null;
  period: Record<string, any>;
  validation: ValidationBlock;
  warnings: string[];
  debug: Record<string, any>;
};

// ─────────────────────────── Constants ───────────────────────────
// Human labels for every field we support. Grouped for the UI sections.
const SECTIONS: { title: string; keys: [string, string][] }[] = [
  {
    title: 'Ticket',
    keys: [
      ['fecha', 'Fecha y hora'],
      ['licencia', 'Licencia'],
    ],
  },
  {
    title: 'Totales acumulados',
    keys: [
      ['num_servicios', 'Nº Servicios'],
      ['carreras', 'Carreras (€)'],
      ['suplementos', 'Suplementos (€)'],
      ['total', 'Total (€)'],
      ['borrados', 'Borrados'],
    ],
  },
  {
    title: 'Bloque P (turno)',
    keys: [
      ['p_num_servicios', 'P Nº Servicios'],
      ['p_carreras', 'P Carreras (€)'],
      ['p_suplementos', 'P Suplementos (€)'],
      ['p_total', 'P Total (€)'],
    ],
  },
  {
    title: 'Distancia (raw — unidad por confirmar)',
    keys: [
      ['dist_total', 'Distancia total'],
      ['dist_ocupado', 'Ocupado'],
      ['dist_libre', 'Libre'],
      ['dist_off', 'OFF'],
      ['p_dist_total', 'P Total'],
      ['p_dist_ocupado', 'P Ocupado'],
      ['p_dist_libre', 'P Libre'],
      ['p_dist_off', 'P OFF'],
    ],
  },
  {
    title: 'Tiempo (raw — unidad por confirmar)',
    keys: [
      ['tiempo_ocupado', 'Ocupado'],
      ['tiempo_on', 'On'],
      ['p_tiempo_ocupado', 'P Ocupado'],
      ['p_tiempo_on', 'P On'],
    ],
  },
];

const STATUS_META: Record<ScanResult['status'], { color: string; label: string; icon: 'checkmark-circle'|'warning'|'close-circle' }> = {
  accepted:            { color: '#10B981', label: 'ACEPTADO',       icon: 'checkmark-circle' },
  needs_confirmation:  { color: '#F59E0B', label: 'NECESITA REVISIÓN', icon: 'warning' },
  rejected:            { color: '#EF4444', label: 'RECHAZADO',      icon: 'close-circle' },
};

// ─────────────────────────── Props ───────────────────────────
type Props = {
  visible: boolean;
  photoFile: File | null;                 // provided by parent (web File)
  onClose: () => void;
  onSaved?: (id: string) => void;
  authHeaders: () => Promise<Record<string, string>>;
};

// ─────────────────────────── Component ───────────────────────────
export function TaxitronicScanModal({ visible, photoFile, onClose, onSaved, authHeaders }: Props) {
  const [state, setState] = useState<'idle' | 'scanning' | 'reviewing' | 'saving' | 'saved' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});   // key → new raw string
  const [mathAck, setMathAck] = useState(false);

  // Reset internal state whenever a new photo arrives.
  useEffect(() => {
    if (visible && photoFile) {
      setState('scanning');
      setError(null);
      setScan(null);
      setEdits({});
      setMathAck(false);
      runScan();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, photoFile]);

  async function runScan() {
    if (!photoFile) return;
    try {
      const headers = await authHeaders();
      const fd = new FormData();
      fd.append('photo', photoFile);
      const r = await axios.post<ScanResult>(`${API_BASE}/api/tickets/taxitronic/scan`, fd, {
        headers, timeout: 90_000, maxContentLength: 25 * 1024 * 1024, maxBodyLength: 25 * 1024 * 1024,
      });
      setScan(r.data);
      setState('reviewing');
    } catch (e: any) {
      setError(_friendly(e));
      setState('error');
    }
  }

  const mathBlocked = useMemo(() => {
    if (!scan) return false;
    const v = scan.validation;
    return (v.total_matches === false || v.period_total_matches === false) && !mathAck;
  }, [scan, mathAck]);

  function getDisplayValue(key: string): string {
    if (edits[key] !== undefined) return edits[key];
    if (!scan) return '';
    // Prefer normalised value; fall back to raw_text.
    const ev = scan.fields[key];
    if (ev?.value !== undefined && ev.value !== null) {
      if (typeof ev.value === 'object') return JSON.stringify(ev.value);
      return String(ev.value);
    }
    return ev?.raw_text || '';
  }

  async function handleConfirm() {
    if (!scan) return;
    // Apply edits back to the top-level ergonomic sections so the backend
    // stores the driver-confirmed values.
    const merged = _applyEdits(scan, edits);
    setState('saving');
    try {
      const headers = await authHeaders();
      const r = await axios.post<{ id: string }>(`${API_BASE}/api/tickets/taxitronic/confirm`, {
        status: scan.status,
        ticket: merged.ticket,
        totals: merged.totals,
        distance: merged.distance,
        time: merged.time,
        deleted: merged.deleted,
        period: merged.period,
        overall_confidence: scan.overall_confidence,
        user_edited_fields: Object.keys(edits),
      }, { headers, timeout: 20_000 });
      setState('saved');
      onSaved?.(r.data.id);
      // Small delay so the "saved" tick is visible.
      setTimeout(() => onClose(), 900);
    } catch (e: any) {
      setError(_friendly(e));
      setState('error');
    }
  }

  const meta = scan ? STATUS_META[scan.status] : null;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.overlay} data-testid="taxitronic-scan-modal">
        <View style={styles.card}>
          {/* Header */}
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Escaneo Taxitronic</Text>
              <Text style={styles.subtitle}>OCR + validación matemática · fail-safe</Text>
            </View>
            <TouchableOpacity onPress={onClose} data-testid="taxitronic-close" style={styles.iconBtn}>
              <Ionicons name="close" size={20} color="#94A3B8" />
            </TouchableOpacity>
          </View>

          {/* Body */}
          {state === 'scanning' && (
            <View style={styles.centerPad} data-testid="taxitronic-scanning">
              <ActivityIndicator size="large" color="#6366F1" />
              <Text style={styles.hint}>Procesando imagen…</Text>
              <Text style={styles.hintSmall}>Detectando ticket, corrigiendo perspectiva, ejecutando OCR sobre 4 variantes.</Text>
            </View>
          )}

          {state === 'error' && (
            <View style={styles.centerPad} data-testid="taxitronic-error">
              <Ionicons name="alert-circle" size={40} color="#EF4444" />
              <Text style={styles.errorText}>{error}</Text>
              <TouchableOpacity onPress={runScan} style={styles.retryBtn} data-testid="taxitronic-retry">
                <Text style={styles.retryText}>Reintentar</Text>
              </TouchableOpacity>
            </View>
          )}

          {(state === 'reviewing' || state === 'saving' || state === 'saved') && scan && meta && (
            <ScrollView style={{ maxHeight: 560 }} contentContainerStyle={{ paddingBottom: 12 }}>
              {/* Status banner */}
              <View style={[styles.banner, { backgroundColor: meta.color + '22', borderColor: meta.color }]}>
                <Ionicons name={meta.icon} size={22} color={meta.color} />
                <View style={{ flex: 1, marginLeft: 10 }}>
                  <Text style={[styles.bannerLabel, { color: meta.color }]}>{meta.label}</Text>
                  <Text style={styles.bannerSub}>Confianza global {(scan.overall_confidence * 100).toFixed(0)}%</Text>
                </View>
              </View>

              {/* Math validation banner */}
              <MathBanner v={scan.validation} onAck={setMathAck} ack={mathAck} />

              {/* Field sections */}
              {SECTIONS.map(section => (
                <View key={section.title} style={styles.section}>
                  <Text style={styles.sectionTitle}>{section.title}</Text>
                  {section.keys.map(([key, label]) => {
                    const ev = scan.fields[key];
                    if (!ev) return (
                      <FieldRow key={key} label={label} testid={`ticket-field-${key}`} missing />
                    );
                    return (
                      <FieldRow
                        key={key}
                        label={label}
                        testid={`ticket-field-${key}`}
                        value={getDisplayValue(key)}
                        onChange={txt => setEdits(prev => ({ ...prev, [key]: txt }))}
                        ev={ev}
                      />
                    );
                  })}
                </View>
              ))}

              {/* Warnings (folded) */}
              {scan.warnings.length > 0 && (
                <View style={styles.warnBox} data-testid="taxitronic-warnings">
                  <Text style={styles.warnTitle}>Avisos</Text>
                  {scan.warnings.slice(0, 6).map((w, i) => (
                    <Text key={i} style={styles.warnItem}>· {w}</Text>
                  ))}
                </View>
              )}
            </ScrollView>
          )}

          {/* Footer actions */}
          {(state === 'reviewing' || state === 'saving' || state === 'saved') && scan && (
            <View style={styles.footer}>
              <TouchableOpacity onPress={onClose} style={styles.secondaryBtn} data-testid="taxitronic-discard">
                <Text style={styles.secondaryBtnText}>Descartar</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={handleConfirm}
                disabled={mathBlocked || state === 'saving' || state === 'saved' || scan.status === 'rejected'}
                style={[
                  styles.primaryBtn,
                  (mathBlocked || state === 'saving' || scan.status === 'rejected') && { opacity: 0.45 },
                ]}
                data-testid="taxitronic-confirm"
              >
                {state === 'saving' ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : state === 'saved' ? (
                  <Ionicons name="checkmark" size={20} color="#FFFFFF" />
                ) : (
                  <Text style={styles.primaryBtnText}>Confirmar y guardar</Text>
                )}
              </TouchableOpacity>
            </View>
          )}
        </View>
      </View>
    </Modal>
  );
}

// ─────────────────────────── Sub-components ───────────────────────────
function MathBanner({ v, ack, onAck }: { v: ValidationBlock; ack: boolean; onAck: (b: boolean) => void }) {
  const totalFail = v.total_matches === false;
  const periodFail = v.period_total_matches === false;
  if (!totalFail && !periodFail) {
    return (
      <View style={[styles.mathOk]} data-testid="taxitronic-math-ok">
        <Ionicons name="checkmark-circle" size={16} color="#10B981" />
        <Text style={styles.mathOkText}>
          Validación matemática correcta {v.total_matches ? '· Total ✓' : ''}
          {v.period_total_matches ? ' · P Total ✓' : ''}
        </Text>
      </View>
    );
  }
  return (
    <View style={styles.mathBad} data-testid="taxitronic-math-fail">
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Ionicons name="warning" size={20} color="#F59E0B" />
        <Text style={styles.mathBadTitle}>Discrepancia matemática detectada</Text>
      </View>
      {totalFail && <Text style={styles.mathBadItem}>· Carreras + Suplementos ≠ Total</Text>}
      {periodFail && <Text style={styles.mathBadItem}>· P Carreras + P Suplementos ≠ P Total</Text>}
      <TouchableOpacity
        onPress={() => onAck(!ack)}
        style={[styles.ackRow, ack && { borderColor: '#F59E0B' }]}
        data-testid="taxitronic-math-ack"
      >
        <View style={[styles.checkbox, ack && { backgroundColor: '#F59E0B', borderColor: '#F59E0B' }]}>
          {ack && <Ionicons name="checkmark" size={14} color="#FFFFFF" />}
        </View>
        <Text style={styles.ackText}>He revisado los importes y quiero guardarlos igualmente</Text>
      </TouchableOpacity>
    </View>
  );
}

function FieldRow({ label, value, onChange, ev, missing, testid }: {
  label: string; testid: string;
  value?: string; onChange?: (txt: string) => void;
  ev?: FieldEvidence; missing?: boolean;
}) {
  if (missing) {
    return (
      <View style={styles.row} data-testid={testid}>
        <Text style={styles.rowLabel}>{label}</Text>
        <View style={styles.rowValueMissing}>
          <Text style={styles.missingText}>no detectado</Text>
        </View>
      </View>
    );
  }
  const conf = ev?.final_confidence ?? 0;
  const barColor = conf > 0.85 ? '#10B981' : conf > 0.55 ? '#F59E0B' : '#EF4444';
  return (
    <View style={styles.row} data-testid={testid}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowLabel}>{label}</Text>
        <View style={styles.flags}>
          {ev?.format_valid ? <Chip color="#10B981" label="formato" /> : <Chip color="#EF4444" label="formato" />}
          {ev?.consensus && <Chip color="#10B981" label="consenso" />}
          {ev && !ev.validation_valid && <Chip color="#F59E0B" label="math" />}
        </View>
        <View style={styles.confBar}>
          <View style={{ height: 4, width: `${Math.round(conf * 100)}%`, backgroundColor: barColor, borderRadius: 4 }} />
        </View>
      </View>
      <TextInput
        value={value}
        onChangeText={onChange}
        style={styles.input}
        data-testid={`${testid}-input`}
      />
    </View>
  );
}

function Chip({ color, label }: { color: string; label: string }) {
  return (
    <View style={{ paddingHorizontal: 6, paddingVertical: 1, borderRadius: 6, backgroundColor: color + '22', marginRight: 4 }}>
      <Text style={{ color, fontSize: 9, fontWeight: '700' }}>{label}</Text>
    </View>
  );
}

// ─────────────────────────── Helpers ───────────────────────────
function _friendly(e: any): string {
  const status = e?.response?.status;
  const detail = e?.response?.data?.detail;
  if (status === 401 || status === 403) return 'Sesión expirada. Vuelve a iniciar sesión.';
  if (status === 413) return 'Foto demasiado grande. Prueba con una versión comprimida.';
  if (status === 415) return 'Formato de imagen no soportado.';
  if (detail) return String(detail);
  if (e?.message) return e.message;
  return 'Error inesperado';
}

/** Merge the user edits back into the ergonomic sections of the scan. */
function _applyEdits(scan: ScanResult, edits: Record<string, string>) {
  const clone: any = {
    ticket: { ...scan.ticket },
    totals: { ...scan.totals },
    distance: { ...scan.distance },
    time: { ...scan.time },
    deleted: scan.deleted,
    period: { ...scan.period },
  };
  const FIELD_TO_PATH: Record<string, [string, string]> = {
    fecha: ['ticket', 'date_time'],   // handled specially below
    licencia: ['ticket', 'license'],
    num_servicios: ['totals', 'services'],
    carreras: ['totals', 'careers'],
    suplementos: ['totals', 'supplements'],
    total: ['totals', 'total'],
    borrados: ['deleted', ''],
    dist_total: ['distance', 'total_raw'],
    dist_ocupado: ['distance', 'occupied_raw'],
    dist_libre: ['distance', 'free_raw'],
    dist_off: ['distance', 'off_raw'],
    tiempo_ocupado: ['time', 'occupied_raw'],
    tiempo_on: ['time', 'on_raw'],
    p_num_servicios: ['period', 'services'],
    p_carreras: ['period', 'careers'],
    p_suplementos: ['period', 'supplements'],
    p_total: ['period', 'total'],
    p_dist_total: ['period', 'distance_total_raw'],
    p_dist_ocupado: ['period', 'distance_occupied_raw'],
    p_dist_libre: ['period', 'distance_free_raw'],
    p_dist_off: ['period', 'distance_off_raw'],
    p_tiempo_ocupado: ['period', 'time_occupied_raw'],
    p_tiempo_on: ['period', 'time_on_raw'],
  };
  for (const [k, raw] of Object.entries(edits)) {
    if (k === 'fecha') {
      // Try to split "YYYY-MM-DD HH:MM" or "DD/MM/YY HH:MM".
      const m = raw.match(/(\d{4}-\d{2}-\d{2}|\d{2}\/\d{2}\/\d{2,4})\s*(\d{1,2}:\d{2})?/);
      if (m) {
        clone.ticket.date = m[1];
        if (m[2]) clone.ticket.time = m[2];
      }
      continue;
    }
    const path = FIELD_TO_PATH[k];
    if (!path) continue;
    const [section, prop] = path;
    if (section === 'deleted') { clone.deleted = _numOrNull(raw); continue; }
    clone[section][prop] = _numOrNull(raw);
  }
  return clone;
}

function _numOrNull(s: string): number | null {
  if (!s || !s.trim()) return null;
  const cleaned = s.replace(/\./g, '').replace(/,/g, '.');   // Spanish → JS
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

// ─────────────────────────── Styles (inline object — RN Web friendly) ───────────────────────────
const styles: any = {
  overlay:      { flex: 1, backgroundColor: 'rgba(15,23,42,0.75)', alignItems: 'center', justifyContent: 'center', padding: 16 },
  card:         { width: '100%', maxWidth: 640, backgroundColor: '#0F172A', borderRadius: 16, padding: 16, borderWidth: 1, borderColor: 'rgba(148,163,184,0.15)' },
  header:       { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  title:        { color: '#E2E8F0', fontSize: 16, fontWeight: '800' },
  subtitle:     { color: '#64748B', fontSize: 11, marginTop: 2 },
  iconBtn:      { padding: 6, borderRadius: 999, backgroundColor: 'rgba(148,163,184,0.08)' },
  centerPad:    { alignItems: 'center', paddingVertical: 32, gap: 8 },
  hint:         { color: '#CBD5E1', fontSize: 14, fontWeight: '600', marginTop: 8 },
  hintSmall:    { color: '#64748B', fontSize: 11, textAlign: 'center', maxWidth: 380 },
  errorText:    { color: '#F87171', fontSize: 13, textAlign: 'center', maxWidth: 420 },
  retryBtn:     { marginTop: 10, paddingHorizontal: 20, paddingVertical: 10, borderRadius: 10, backgroundColor: '#6366F1' },
  retryText:    { color: '#FFFFFF', fontWeight: '700' },
  banner:       { flexDirection: 'row', alignItems: 'center', padding: 12, borderRadius: 12, borderWidth: 1, marginBottom: 10 },
  bannerLabel:  { fontSize: 13, fontWeight: '800', letterSpacing: 0.5 },
  bannerSub:    { color: '#94A3B8', fontSize: 11, marginTop: 2 },
  mathOk:       { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: 'rgba(16,185,129,0.10)', paddingVertical: 8, paddingHorizontal: 10, borderRadius: 10, marginBottom: 10 },
  mathOkText:   { color: '#34D399', fontSize: 12, fontWeight: '600' },
  mathBad:      { padding: 12, borderRadius: 12, borderWidth: 1, borderColor: 'rgba(245,158,11,0.4)', backgroundColor: 'rgba(245,158,11,0.10)', marginBottom: 10, gap: 4 },
  mathBadTitle: { color: '#FBBF24', fontSize: 13, fontWeight: '700' },
  mathBadItem:  { color: '#FCD34D', fontSize: 12, marginLeft: 28 },
  ackRow:       { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 8, borderWidth: 1, borderColor: 'transparent', marginTop: 4 },
  checkbox:     { width: 18, height: 18, borderRadius: 4, borderWidth: 1.5, borderColor: '#94A3B8', alignItems: 'center', justifyContent: 'center' },
  ackText:      { color: '#E2E8F0', fontSize: 12, flex: 1 },
  section:      { marginBottom: 14 },
  sectionTitle: { color: '#94A3B8', fontSize: 11, fontWeight: '800', letterSpacing: 0.5, textTransform: 'uppercase', marginBottom: 6 },
  row:          { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 8 },
  rowLabel:     { color: '#CBD5E1', fontSize: 12, fontWeight: '600' },
  rowValueMissing: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: 'rgba(239,68,68,0.15)' },
  missingText:  { color: '#F87171', fontSize: 11, fontWeight: '600' },
  flags:        { flexDirection: 'row', gap: 4, marginTop: 3 },
  confBar:      { height: 4, backgroundColor: 'rgba(148,163,184,0.15)', borderRadius: 4, marginTop: 4, overflow: 'hidden' },
  input:        { width: 130, backgroundColor: '#1E293B', color: '#E2E8F0', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, borderWidth: 1, borderColor: 'rgba(148,163,184,0.15)' },
  warnBox:      { padding: 10, borderRadius: 10, backgroundColor: 'rgba(148,163,184,0.08)', marginTop: 6 },
  warnTitle:    { color: '#94A3B8', fontSize: 11, fontWeight: '700', marginBottom: 4 },
  warnItem:     { color: '#64748B', fontSize: 11 },
  footer:       { flexDirection: 'row', gap: 8, marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: 'rgba(148,163,184,0.15)' },
  secondaryBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, alignItems: 'center', backgroundColor: 'rgba(148,163,184,0.10)' },
  secondaryBtnText: { color: '#CBD5E1', fontWeight: '700' },
  primaryBtn:   { flex: 2, paddingVertical: 12, borderRadius: 10, alignItems: 'center', backgroundColor: '#10B981' },
  primaryBtnText:{ color: '#FFFFFF', fontWeight: '800', letterSpacing: 0.5 },
};

export default TaxitronicScanModal;
