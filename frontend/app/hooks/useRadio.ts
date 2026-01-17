// =============================================================================
// useRadio Hook - TaxiDash Madrid
// Walkie-Talkie functionality via WebSocket
// =============================================================================
import { useState, useCallback, useRef, useEffect } from 'react';
import { Alert, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Audio } from 'expo-av';
import axios from 'axios';
import Constants from 'expo-constants';

const API_BASE = Constants.expoConfig?.extra?.EXPO_PUBLIC_BACKEND_URL || 
                 process.env.EXPO_PUBLIC_BACKEND_URL || '';

interface RadioChannel {
  id: number;
  name: string;
  users_count: number;
}

interface RadioUser {
  username: string;
  full_name?: string;
}

interface UseRadioReturn {
  // State
  radioConnected: boolean;
  radioChannel: number;
  radioChannels: RadioChannel[];
  radioUsers: RadioUser[];
  radioTransmitting: boolean;
  radioChannelBusy: boolean;
  radioTransmittingUser: string | null;
  radioMuted: boolean;
  audioPermission: boolean;
  
  // Actions
  fetchRadioChannels: () => Promise<void>;
  connectToRadioChannel: (channel: number) => Promise<void>;
  disconnectFromRadio: () => void;
  startTransmission: () => Promise<void>;
  stopTransmission: () => Promise<void>;
  toggleMute: () => void;
}

export const useRadio = (): UseRadioReturn => {
  // State
  const [radioConnected, setRadioConnected] = useState(false);
  const [radioChannel, setRadioChannel] = useState(1);
  const [radioChannels, setRadioChannels] = useState<RadioChannel[]>([]);
  const [radioUsers, setRadioUsers] = useState<RadioUser[]>([]);
  const [radioTransmitting, setRadioTransmitting] = useState(false);
  const [radioChannelBusy, setRadioChannelBusy] = useState(false);
  const [radioTransmittingUser, setRadioTransmittingUser] = useState<string | null>(null);
  const [radioMuted, setRadioMuted] = useState(false);
  const [audioPermission, setAudioPermission] = useState(false);
  
  // Refs
  const radioWsRef = useRef<WebSocket | null>(null);
  const recordingRef = useRef<Audio.Recording | null>(null);
  const webAudioRef = useRef<HTMLAudioElement | null>(null);
  const webAudioUnlockedRef = useRef(false);
  const radioMutedRef = useRef(false);
  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Keep ref in sync with state
  useEffect(() => {
    radioMutedRef.current = radioMuted;
  }, [radioMuted]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
      if (radioWsRef.current) {
        radioWsRef.current.close();
      }
    };
  }, []);

  const fetchRadioChannels = useCallback(async () => {
    try {
      const token = await AsyncStorage.getItem('token');
      const response = await axios.get(`${API_BASE}/api/radio/channels`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setRadioChannels(response.data.channels);
    } catch (error) {
      console.error('Error fetching radio channels:', error);
    }
  }, []);

  const playReceivedAudio = useCallback(async (audioData: string, mimeType?: string) => {
    if (radioMutedRef.current) {
      console.log('Radio: Muted, skipping audio playback');
      return;
    }

    try {
      if (Platform.OS === 'web') {
        // Web playback using persistent Audio element
        if (webAudioRef.current) {
          const effectiveMimeType = mimeType || 'audio/mp4';
          const audioSrc = `data:${effectiveMimeType};base64,${audioData}`;
          webAudioRef.current.src = audioSrc;
          webAudioRef.current.volume = 1.0;
          await webAudioRef.current.play();
        }
      } else {
        // Native playback
        const effectiveMimeType = mimeType || 'audio/mp4';
        const audioUri = `data:${effectiveMimeType};base64,${audioData}`;
        
        const { sound } = await Audio.Sound.createAsync(
          { uri: audioUri },
          { shouldPlay: true, volume: 1.0 }
        );
        
        sound.setOnPlaybackStatusUpdate((status: any) => {
          if (status.didJustFinish) {
            sound.unloadAsync();
          }
        });
      }
    } catch (error) {
      console.error('Radio: Error playing audio:', error);
    }
  }, []);

  const connectToRadioChannel = useCallback(async (channel: number) => {
    try {
      const token = await AsyncStorage.getItem('token');
      if (!token) return;

      // Request audio permission
      const { status } = await Audio.requestPermissionsAsync();
      if (status === 'granted') {
        setAudioPermission(true);
        await Audio.setAudioModeAsync({
          allowsRecordingIOS: true,
          playsInSilentModeIOS: true,
          staysActiveInBackground: true,
          shouldDuckAndroid: true,
          playThroughEarpieceAndroid: false,
        });
      }

      // Web audio unlock
      if (Platform.OS === 'web') {
        try {
          if (!webAudioRef.current) {
            webAudioRef.current = new window.Audio();
            webAudioRef.current.volume = 1.0;
          }
          const silentMp3 = 'data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA/+M4wAAAAAAAAAAAAEluZm8AAAAPAAAAAwAAAbAAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV////////////////////////////////////////////AAAAAExhdmM1OC4xMwAAAAAAAAAAAAAAACQDgAAAAAAAAAGwknmBmgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/+M4wAALkAK4AABEAIAAADSAAABQAAANIAAABEAAATwAAAAEAAADSAAABQAAANIAAAARAAEA/+M4wAAK0AKYAABEAIAAADSAAAAQAAANIAAABEAAATwAAAAEAAADSAAAAQAAANIAAAARAAEA';
          webAudioRef.current.src = silentMp3;
          await webAudioRef.current.play();
          webAudioUnlockedRef.current = true;
        } catch (e) {
          console.log('Radio: Audio unlock error:', e);
        }
      }

      // Close existing connection
      if (radioWsRef.current) {
        radioWsRef.current.close();
      }

      // Create WebSocket connection
      const wsProtocol = API_BASE.startsWith('https') ? 'wss' : 'ws';
      const wsHost = API_BASE.replace(/^https?:\/\//, '');
      const wsUrl = `${wsProtocol}://${wsHost}/api/radio/ws/${channel}?token=${token}`;

      const ws = new WebSocket(wsUrl);
      radioWsRef.current = ws;

      ws.onopen = () => {
        console.log(`Radio: Connected to channel ${channel}`);
        setRadioConnected(true);
        setRadioChannel(channel);
        
        // Ping interval
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 15000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'channel_status') {
            setRadioUsers(data.users || []);
            setRadioChannelBusy(data.transmitting_user !== null);
            setRadioTransmittingUser(data.transmitting_user);
          } else if (data.type === 'transmission_status') {
            if (!data.success && data.message === 'Canal ocupado') {
              Alert.alert('Radio', 'El canal está ocupado.');
            }
          } else if (data.type === 'audio') {
            playReceivedAudio(data.audio_data, data.mime_type);
          }
        } catch (e) {
          console.error('Radio: Error parsing message', e);
        }
      };

      ws.onclose = () => {
        setRadioConnected(false);
        setRadioUsers([]);
        setRadioChannelBusy(false);
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
      };

      ws.onerror = (error) => {
        console.error('Radio: WebSocket error', error);
      };

    } catch (error) {
      console.error('Radio: Connection error', error);
      Alert.alert('Error', 'No se pudo conectar al radio');
    }
  }, [playReceivedAudio]);

  const disconnectFromRadio = useCallback(() => {
    if (radioWsRef.current) {
      radioWsRef.current.close();
      radioWsRef.current = null;
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
    }
    setRadioConnected(false);
    setRadioUsers([]);
  }, []);

  const startTransmission = useCallback(async () => {
    if (!radioWsRef.current || radioWsRef.current.readyState !== WebSocket.OPEN) {
      Alert.alert('Error', 'No estás conectado al radio');
      return;
    }

    try {
      // Request start transmission
      radioWsRef.current.send(JSON.stringify({ type: 'start_transmission' }));
      
      // Start recording
      const { recording } = await Audio.Recording.createAsync(
        Platform.OS === 'web' 
          ? Audio.RecordingOptionsPresets.HIGH_QUALITY
          : {
              android: {
                extension: '.webm',
                outputFormat: Audio.AndroidOutputFormat.WEBM,
                audioEncoder: Audio.AndroidAudioEncoder.OPUS,
                sampleRate: 16000,
                numberOfChannels: 1,
                bitRate: 32000,
              },
              ios: {
                extension: '.m4a',
                outputFormat: Audio.IOSOutputFormat.MPEG4AAC,
                audioQuality: Audio.IOSAudioQuality.MEDIUM,
                sampleRate: 16000,
                numberOfChannels: 1,
                bitRate: 32000,
              },
              web: {
                mimeType: 'audio/webm',
                bitsPerSecond: 32000,
              },
            }
      );
      
      recordingRef.current = recording;
      setRadioTransmitting(true);
    } catch (error) {
      console.error('Radio: Error starting transmission', error);
      Alert.alert('Error', 'No se pudo iniciar la transmisión');
    }
  }, []);

  const stopTransmission = useCallback(async () => {
    if (!recordingRef.current) return;

    try {
      setRadioTransmitting(false);
      
      await recordingRef.current.stopAndUnloadAsync();
      const uri = recordingRef.current.getURI();
      recordingRef.current = null;

      if (uri && radioWsRef.current && radioWsRef.current.readyState === WebSocket.OPEN) {
        // Read and send audio
        const response = await fetch(uri);
        const blob = await response.blob();
        const reader = new FileReader();
        
        reader.onloadend = () => {
          const base64 = (reader.result as string).split(',')[1];
          const mimeType = Platform.OS === 'ios' ? 'audio/mp4' : 'audio/webm';
          
          radioWsRef.current?.send(JSON.stringify({
            type: 'audio',
            audio_data: base64,
            mime_type: mimeType,
          }));
          
          radioWsRef.current?.send(JSON.stringify({ type: 'stop_transmission' }));
        };
        
        reader.readAsDataURL(blob);
      }
    } catch (error) {
      console.error('Radio: Error stopping transmission', error);
    }
  }, []);

  const toggleMute = useCallback(() => {
    setRadioMuted(prev => !prev);
  }, []);

  return {
    radioConnected,
    radioChannel,
    radioChannels,
    radioUsers,
    radioTransmitting,
    radioChannelBusy,
    radioTransmittingUser,
    radioMuted,
    audioPermission,
    fetchRadioChannels,
    connectToRadioChannel,
    disconnectFromRadio,
    startTransmission,
    stopTransmission,
    toggleMute,
  };
};

export default useRadio;
