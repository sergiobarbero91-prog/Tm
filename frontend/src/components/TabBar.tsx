// =============================================================================
// TabBar Component - TaxiDash Madrid
// =============================================================================
import React from 'react';
import { View, TouchableOpacity, Text, StyleSheet } from 'react-native';
import { Feather } from '@expo/vector-icons';
import { TabType } from '../types';

interface Tab {
  id: TabType;
  label: string;
  icon: keyof typeof Feather.glyphMap;
}

interface TabBarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  isAdmin?: boolean;
}

const TABS: Tab[] = [
  { id: 'trains', label: 'Trenes', icon: 'clock' },
  { id: 'flights', label: 'Vuelos', icon: 'send' },
  { id: 'street', label: 'Calle', icon: 'map-pin' },
  { id: 'events', label: 'Eventos', icon: 'calendar' },
];

export const TabBar: React.FC<TabBarProps> = ({ 
  activeTab, 
  onTabChange, 
  isAdmin = false 
}) => {
  const tabs = isAdmin 
    ? [...TABS, { id: 'admin' as TabType, label: 'Admin', icon: 'settings' as keyof typeof Feather.glyphMap }]
    : TABS;

  return (
    <View style={styles.container}>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <TouchableOpacity
            key={tab.id}
            style={styles.tab}
            onPress={() => onTabChange(tab.id)}
            activeOpacity={0.7}
          >
            <Feather
              name={tab.icon}
              size={20}
              color={isActive ? '#6366F1' : '#94A3B8'}
            />
            <Text style={[
              styles.tabLabel,
              isActive && styles.tabLabelActive
            ]}>
              {tab.label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    backgroundColor: '#1E293B',
    borderTopWidth: 1,
    borderTopColor: '#334155',
    paddingBottom: 20,
    paddingTop: 8,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 8,
    gap: 4,
  },
  tabLabel: {
    fontSize: 12,
    color: '#94A3B8',
  },
  tabLabelActive: {
    color: '#6366F1',
    fontWeight: '600',
  },
});

export default TabBar;
