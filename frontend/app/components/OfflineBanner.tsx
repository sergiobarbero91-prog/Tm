// =============================================================================
// OfflineBanner Component - TaxiDash Madrid
// =============================================================================
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';

interface OfflineBannerProps {
  onDismiss?: () => void;
}

export const OfflineBanner: React.FC<OfflineBannerProps> = ({ onDismiss }) => {
  return (
    <View style={styles.container}>
      <Feather name="wifi-off" size={18} color="#FFFFFF" />
      <Text style={styles.text}>Sin conexión a Internet</Text>
      {onDismiss && (
        <TouchableOpacity onPress={onDismiss} style={styles.closeButton}>
          <Feather name="x" size={18} color="#FFFFFF" />
        </TouchableOpacity>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#DC2626',
    paddingVertical: 8,
    paddingHorizontal: 16,
    gap: 8,
  },
  text: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
  },
  closeButton: {
    padding: 4,
  },
});

export default OfflineBanner;
