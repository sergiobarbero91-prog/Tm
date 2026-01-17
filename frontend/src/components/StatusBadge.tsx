// =============================================================================
// StatusBadge Component - TaxiDash Madrid
// =============================================================================
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'default';

interface StatusBadgeProps {
  text: string;
  variant?: BadgeVariant;
  size?: 'small' | 'medium' | 'large';
  icon?: React.ReactNode;
}

const variantColors: Record<BadgeVariant, { bg: string; text: string }> = {
  success: { bg: '#10B98120', text: '#10B981' },
  warning: { bg: '#F59E0B20', text: '#F59E0B' },
  danger: { bg: '#EF444420', text: '#EF4444' },
  info: { bg: '#3B82F620', text: '#3B82F6' },
  default: { bg: '#6366F120', text: '#6366F1' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  text,
  variant = 'default',
  size = 'medium',
  icon,
}) => {
  const colors = variantColors[variant];
  
  const sizeStyles = {
    small: { paddingHorizontal: 6, paddingVertical: 2, fontSize: 10 },
    medium: { paddingHorizontal: 10, paddingVertical: 4, fontSize: 12 },
    large: { paddingHorizontal: 14, paddingVertical: 6, fontSize: 14 },
  };

  return (
    <View style={[
      styles.container,
      { backgroundColor: colors.bg },
      { paddingHorizontal: sizeStyles[size].paddingHorizontal },
      { paddingVertical: sizeStyles[size].paddingVertical },
    ]}>
      {icon}
      <Text style={[
        styles.text,
        { color: colors.text },
        { fontSize: sizeStyles[size].fontSize },
      ]}>
        {text}
      </Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 12,
    gap: 4,
  },
  text: {
    fontWeight: '600',
  },
});

export default StatusBadge;
