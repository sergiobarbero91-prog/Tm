/**
 * RolePicker — first-run splash to choose between Conductor and Cliente.
 * Stores the chosen role in AsyncStorage under APP_ROLE_KEY.
 */
import React from 'react';
import { View, Text, TouchableOpacity, StatusBar, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';

export const APP_ROLE_KEY = 'appRole';
export type AppRole = 'driver' | 'client';

export const RolePicker: React.FC<{ onPick: (r: AppRole) => void }> = ({ onPick }) => {
  const choose = async (r: AppRole) => {
    try {
      await AsyncStorage.setItem(APP_ROLE_KEY, r);
    } catch {}
    onPick(r);
  };

  return (
    <View style={{ flex: 1, backgroundColor: '#0F172A', padding: 24, justifyContent: 'center' }}>
      {Platform.OS !== 'web' && <StatusBar barStyle="light-content" />}
      <View style={{ alignItems: 'center', marginBottom: 40 }}>
        <View style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: '#F59E0B', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
          <Ionicons name="car" size={44} color="#0F172A" />
        </View>
        <Text style={{ color: '#F1F5F9', fontSize: 28, fontWeight: '900', letterSpacing: 1 }}>TaxiDash</Text>
        <Text style={{ color: '#94A3B8', fontSize: 14, marginTop: 8, textAlign: 'center' }}>
          ¿Cómo vas a usar la aplicación?
        </Text>
      </View>

      <TouchableOpacity
        onPress={() => choose('driver')}
        style={{
          backgroundColor: '#1E293B',
          borderRadius: 16,
          padding: 20,
          borderWidth: 2,
          borderColor: '#334155',
          flexDirection: 'row',
          alignItems: 'center',
          marginBottom: 14,
        }}
        testID="role-picker-driver"
      >
        <View style={{ width: 52, height: 52, borderRadius: 26, backgroundColor: '#F59E0B', alignItems: 'center', justifyContent: 'center', marginRight: 14 }}>
          <Ionicons name="car-sport" size={28} color="#0F172A" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ color: '#F1F5F9', fontSize: 17, fontWeight: '800' }}>Soy taxista</Text>
          <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 2 }}>
            Estaciones en tiempo real, gestión, reservas y emisora.
          </Text>
        </View>
        <Ionicons name="chevron-forward" size={22} color="#64748B" />
      </TouchableOpacity>

      <TouchableOpacity
        onPress={() => choose('client')}
        style={{
          backgroundColor: '#1E293B',
          borderRadius: 16,
          padding: 20,
          borderWidth: 2,
          borderColor: '#334155',
          flexDirection: 'row',
          alignItems: 'center',
        }}
        testID="role-picker-client"
      >
        <View style={{ width: 52, height: 52, borderRadius: 26, backgroundColor: '#3B82F6', alignItems: 'center', justifyContent: 'center', marginRight: 14 }}>
          <Ionicons name="person" size={28} color="#0F172A" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ color: '#F1F5F9', fontSize: 17, fontWeight: '800' }}>Necesito un taxi</Text>
          <Text style={{ color: '#94A3B8', fontSize: 12, marginTop: 2 }}>
            Pide un servicio ahora o programa una reserva.
          </Text>
        </View>
        <Ionicons name="chevron-forward" size={22} color="#64748B" />
      </TouchableOpacity>

      <Text style={{ color: '#475569', fontSize: 11, textAlign: 'center', marginTop: 30 }}>
        Podrás cambiar de rol en cualquier momento desde la cabecera.
      </Text>
    </View>
  );
};

export default RolePicker;
