// =============================================================================
// useNetwork Hook - TaxiDash Madrid
// Network connectivity monitoring
// =============================================================================
import { useState, useEffect, useCallback } from 'react';
import NetInfo, { NetInfoState } from '@react-native-community/netinfo';

interface UseNetworkReturn {
  isConnected: boolean;
  isInternetReachable: boolean | null;
  connectionType: string | null;
  showOfflineBanner: boolean;
  dismissOfflineBanner: () => void;
}

export const useNetwork = (): UseNetworkReturn => {
  const [isConnected, setIsConnected] = useState(true);
  const [isInternetReachable, setIsInternetReachable] = useState<boolean | null>(true);
  const [connectionType, setConnectionType] = useState<string | null>(null);
  const [showOfflineBanner, setShowOfflineBanner] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    // Subscribe to network state updates
    const unsubscribe = NetInfo.addEventListener((state: NetInfoState) => {
      const connected = state.isConnected ?? false;
      const reachable = state.isInternetReachable;
      
      setIsConnected(connected);
      setIsInternetReachable(reachable);
      setConnectionType(state.type);

      // Show banner if not connected and not dismissed
      if (!connected || reachable === false) {
        if (!bannerDismissed) {
          setShowOfflineBanner(true);
        }
      } else {
        // Reset dismissed state when back online
        setBannerDismissed(false);
        setShowOfflineBanner(false);
      }
    });

    // Check initial state
    NetInfo.fetch().then((state) => {
      const connected = state.isConnected ?? false;
      const reachable = state.isInternetReachable;
      
      setIsConnected(connected);
      setIsInternetReachable(reachable);
      setConnectionType(state.type);

      if (!connected || reachable === false) {
        setShowOfflineBanner(true);
      }
    });

    return () => {
      unsubscribe();
    };
  }, [bannerDismissed]);

  const dismissOfflineBanner = useCallback(() => {
    setBannerDismissed(true);
    setShowOfflineBanner(false);
  }, []);

  return {
    isConnected,
    isInternetReachable,
    connectionType,
    showOfflineBanner,
    dismissOfflineBanner,
  };
};

export default useNetwork;
