import React from 'react';
import { View, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

interface Terminal {
  name: string;
  arrivals_60min: number;
  is_hot: boolean;
  flights: Array<{ time: string; origin: string }>;
}

interface PublicSummary {
  terminals: { [key: string]: Terminal };
}

interface AirportTerminalsGroupedProps {
  publicSummary: PublicSummary;
}

export const AirportTerminalsGrouped: React.FC<AirportTerminalsGroupedProps> = ({ publicSummary }) => {
  return (
    <View style={{ marginBottom: 16 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
        <Ionicons name="airplane" size={18} color="#22D3EE" />
        <Text style={{ color: '#22D3EE', fontSize: 14, fontWeight: '700', marginLeft: 8 }}>
          Aeropuerto Barajas
        </Text>
      </View>
      
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
        {/* T1 */}
        {publicSummary.terminals['T1'] && (() => {
          const terminal = publicSummary.terminals['T1'];
          const isHot = terminal.is_hot;
          return (
            <View style={{ 
              backgroundColor: isHot ? 'rgba(34, 211, 238, 0.15)' : 'rgba(71, 85, 105, 0.3)',
              borderRadius: 8,
              padding: 8,
              minWidth: '30%',
              flex: 1,
              borderWidth: isHot ? 1 : 0,
              borderColor: 'rgba(34, 211, 238, 0.3)',
            }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text style={{ color: isHot ? '#22D3EE' : '#CBD5E1', fontSize: 12, fontWeight: '700' }}>
                  {isHot ? '🔥 ' : ''}T1
                </Text>
                <Text style={{ color: isHot ? '#22D3EE' : '#94A3B8', fontSize: 10, fontWeight: '600' }}>
                  {terminal.arrivals_60min} en 60m
                </Text>
              </View>
              {terminal.flights.slice(0, 1).map((flight: any, idx: number) => (
                <Text key={idx} style={{ color: '#64748B', fontSize: 10 }} numberOfLines={1}>
                  {flight.time} - {flight.origin}
                </Text>
              ))}
            </View>
          );
        })()}
        
        {/* T2-T3 Combined */}
        {(publicSummary.terminals['T2'] || publicSummary.terminals['T3']) && (() => {
          const t2 = publicSummary.terminals['T2'];
          const t3 = publicSummary.terminals['T3'];
          const totalArrivals = (t2?.arrivals_60min || 0) + (t3?.arrivals_60min || 0);
          const isHot = t2?.is_hot || t3?.is_hot;
          const flights = [...(t2?.flights || []), ...(t3?.flights || [])].sort((a: any, b: any) => a.time.localeCompare(b.time));
          return (
            <View style={{ 
              backgroundColor: isHot ? 'rgba(34, 211, 238, 0.15)' : 'rgba(71, 85, 105, 0.3)',
              borderRadius: 8,
              padding: 8,
              minWidth: '30%',
              flex: 1,
              borderWidth: isHot ? 1 : 0,
              borderColor: 'rgba(34, 211, 238, 0.3)',
            }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text style={{ color: isHot ? '#22D3EE' : '#CBD5E1', fontSize: 12, fontWeight: '700' }}>
                  {isHot ? '🔥 ' : ''}T2-T3
                </Text>
                <Text style={{ color: isHot ? '#22D3EE' : '#94A3B8', fontSize: 10, fontWeight: '600' }}>
                  {totalArrivals} en 60m
                </Text>
              </View>
              {flights.slice(0, 1).map((flight: any, idx: number) => (
                <Text key={idx} style={{ color: '#64748B', fontSize: 10 }} numberOfLines={1}>
                  {flight.time} - {flight.origin}
                </Text>
              ))}
            </View>
          );
        })()}
        
        {/* T4-T4S Combined */}
        {(publicSummary.terminals['T4'] || publicSummary.terminals['T4S']) && (() => {
          const t4 = publicSummary.terminals['T4'];
          const t4s = publicSummary.terminals['T4S'];
          const totalArrivals = (t4?.arrivals_60min || 0) + (t4s?.arrivals_60min || 0);
          const isHot = t4?.is_hot || t4s?.is_hot;
          const flights = [...(t4?.flights || []), ...(t4s?.flights || [])].sort((a: any, b: any) => a.time.localeCompare(b.time));
          return (
            <View style={{ 
              backgroundColor: isHot ? 'rgba(34, 211, 238, 0.15)' : 'rgba(71, 85, 105, 0.3)',
              borderRadius: 8,
              padding: 8,
              minWidth: '30%',
              flex: 1,
              borderWidth: isHot ? 1 : 0,
              borderColor: 'rgba(34, 211, 238, 0.3)',
            }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text style={{ color: isHot ? '#22D3EE' : '#CBD5E1', fontSize: 12, fontWeight: '700' }}>
                  {isHot ? '🔥 ' : ''}T4-T4S
                </Text>
                <Text style={{ color: isHot ? '#22D3EE' : '#94A3B8', fontSize: 10, fontWeight: '600' }}>
                  {totalArrivals} en 60m
                </Text>
              </View>
              {flights.slice(0, 1).map((flight: any, idx: number) => (
                <Text key={idx} style={{ color: '#64748B', fontSize: 10 }} numberOfLines={1}>
                  {flight.time} - {flight.origin}
                </Text>
              ))}
            </View>
          );
        })()}
      </View>
    </View>
  );
};

export default AirportTerminalsGrouped;
