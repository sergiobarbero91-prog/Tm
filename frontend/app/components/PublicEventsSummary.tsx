import React, { useState, useEffect } from 'react';
import { View, Text, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

const parseSummaryToSections = (text: string) => {
  const sections: { title: string; content: string; hasEvent: boolean }[] = [];
  const strategicTips: string[] = [];

  // Split by ### headers
  const parts = text.split(/###\s*/);

  for (const part of parts) {
    if (!part.trim()) continue;

    const lines = part.trim().split('\n');
    const title = lines[0].replace(/\*\*/g, '').trim();
    const body = lines.slice(1).join('\n').trim();

    // Check if this is the strategic suggestions section
    if (/sugerencia|estratég/i.test(title)) {
      // Extract numbered tips
      const tipMatches = body.match(/\d+\.\s+\*\*[^*]+\*\*[^]*?(?=\n\d+\.|\n\*\*Nota|\n$|$)/g);
      if (tipMatches) {
        for (const tip of tipMatches) {
          // Clean markdown
          const cleaned = tip
            .replace(/\*\*/g, '')
            .replace(/\*/g, '')
            .replace(/\n\s+/g, ' ')
            .trim();
          strategicTips.push(cleaned);
        }
      }
    } else if (/wizink|ifema|estadio|teatro|palacio|gran vía/i.test(title)) {
      const hasEvent = !/sin eventos? confirmad|no se registr|no hay|ausencia/i.test(body);
      // Get the key info line
      let summary = '';
      const statusMatch = body.match(/\*\*([^*]+)\*\*/);
      if (statusMatch) {
        summary = statusMatch[1].trim();
      }
      // Get impact line
      const impactMatch = body.match(/\*\*Impacto[^*]*\*\*:\s*([^\n]+)/);
      if (impactMatch) {
        summary += summary ? ' — ' + impactMatch[1].trim() : impactMatch[1].trim();
      }
      sections.push({ title, content: summary, hasEvent });
    }
  }

  return { sections, strategicTips };
};

export const PublicEventsSummary = () => {
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [dayName, setDayName] = useState('');

  useEffect(() => {
    const fetchSummary = async () => {
      try {
        const res = await axios.get(`${API_BASE}/api/events/daily-summary-public`);
        if (res.data?.success && res.data?.summary) {
          setSummary(res.data.summary);
          setDayName(res.data.day_name || '');
        }
      } catch {
        // Silently fail
      } finally {
        setLoading(false);
      }
    };
    fetchSummary();
  }, []);

  if (loading) {
    return (
      <View style={{
        backgroundColor: 'rgba(30, 41, 59, 0.8)',
        borderRadius: 16,
        padding: 20,
        marginBottom: 20,
        borderWidth: 1,
        borderColor: 'rgba(71, 85, 105, 0.5)',
        alignItems: 'center',
      }}>
        <ActivityIndicator color="#8B5CF6" />
      </View>
    );
  }

  if (!summary) return null;

  const { sections, strategicTips } = parseSummaryToSections(summary);

  return (
    <View style={{
      backgroundColor: 'rgba(30, 41, 59, 0.8)',
      borderRadius: 16,
      padding: 16,
      marginBottom: 20,
      borderWidth: 1,
      borderColor: 'rgba(139, 92, 246, 0.3)',
    }}>
      <Text style={{
        color: '#94A3B8',
        fontSize: 12,
        fontWeight: '600',
        marginBottom: 12,
        textAlign: 'center',
        textTransform: 'uppercase',
        letterSpacing: 1,
      }}>
        Eventos y zonas calientes
      </Text>

      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 12 }}>
        <Ionicons name="calendar" size={18} color="#8B5CF6" />
        <Text style={{ color: '#8B5CF6', fontSize: 14, fontWeight: '700', marginLeft: 8 }}>
          Resumen del {dayName || 'dia'}
        </Text>
      </View>

      {/* Event venues status */}
      {sections.length > 0 && (
        <View style={{ marginBottom: 12 }}>
          {sections.map((section, idx) => (
            <View key={idx} style={{
              flexDirection: 'row',
              alignItems: 'flex-start',
              paddingVertical: 6,
              paddingHorizontal: 8,
              marginBottom: 4,
              backgroundColor: section.hasEvent ? 'rgba(245, 158, 11, 0.1)' : 'transparent',
              borderRadius: 8,
              borderLeftWidth: 3,
              borderLeftColor: section.hasEvent ? '#F59E0B' : '#475569',
            }}>
              <Text style={{ color: section.hasEvent ? '#F59E0B' : '#64748B', fontSize: 14, marginRight: 6 }}>
                {section.hasEvent ? '\u25CF' : '\u25CB'}
              </Text>
              <View style={{ flex: 1 }}>
                <Text style={{ color: section.hasEvent ? '#F59E0B' : '#CBD5E1', fontSize: 13, fontWeight: '600' }}>
                  {section.title}
                </Text>
                <Text style={{ color: '#94A3B8', fontSize: 11, marginTop: 2 }}>
                  {section.content}
                </Text>
              </View>
            </View>
          ))}
        </View>
      )}

      {/* Strategic zones with time stamps */}
      {strategicTips.length > 0 && (
        <View style={{
          backgroundColor: 'rgba(139, 92, 246, 0.08)',
          borderRadius: 10,
          padding: 12,
          borderWidth: 1,
          borderColor: 'rgba(139, 92, 246, 0.2)',
        }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
            <Ionicons name="flame" size={16} color="#F59E0B" />
            <Text style={{ color: '#F59E0B', fontSize: 13, fontWeight: '700', marginLeft: 6 }}>
              Zonas calientes hoy
            </Text>
          </View>
          {strategicTips.map((tip, idx) => (
            <View key={idx} style={{
              flexDirection: 'row',
              alignItems: 'flex-start',
              marginBottom: 6,
              paddingLeft: 4,
            }}>
              <Text style={{ color: '#8B5CF6', fontSize: 12, fontWeight: '700', marginRight: 6, marginTop: 1 }}>
                {idx + 1}.
              </Text>
              <Text style={{ color: '#CBD5E1', fontSize: 12, lineHeight: 17, flex: 1 }}>
                {tip.replace(/^\d+\.\s*/, '')}
              </Text>
            </View>
          ))}
        </View>
      )}

      <Text style={{
        color: '#64748B',
        fontSize: 10,
        textAlign: 'center',
        fontStyle: 'italic',
        marginTop: 10,
      }}>
        Generado por IA. Inicia sesion para ver el informe completo.
      </Text>
    </View>
  );
};
