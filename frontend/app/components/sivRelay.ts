// Reads Adif station panels (SIV) from the device and relays a slim snapshot to our backend.
// Adif rejects datacenter IPs (HTTP 403), but accepts connections from phones/browsers.
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const SIV_HUB = 'wss://info.adif.es/InfoStation';
const RS = '\u001e';
const TIMEOUT_MS = 12000;
const MAX_AGE_MS = 5 * 60 * 1000;

const readStation = (code: string): Promise<any> =>
  new Promise((resolve, reject) => {
    const topics = [`dnv3-gravita-${code}`, `PRO-ECM-${code}`];
    let ws: WebSocket;
    try {
      ws = new WebSocket(SIV_HUB);
    } catch (e) {
      reject(e);
      return;
    }
    const done = (fn: () => void) => {
      clearTimeout(timer);
      try { ws.close(); } catch {}
      fn();
    };
    const timer = setTimeout(() => done(() => reject(new Error('timeout'))), TIMEOUT_MS);
    const send = (o: any) => ws.send(JSON.stringify(o) + RS);
    ws.onopen = () => send({ protocol: 'json', version: 1 });
    ws.onerror = () => done(() => reject(new Error('ws error')));
    ws.onmessage = (ev: any) => {
      String(ev.data).split(RS).forEach(part => {
        if (!part) return;
        let m: any;
        try { m = JSON.parse(part); } catch { return; }
        if (m.type === undefined) {
          topics.forEach(t => {
            send({ type: 1, target: 'JoinInfo', arguments: [t] });
            send({ type: 1, target: 'GetLastMessage', arguments: [t] });
          });
        } else if (m.type === 1 && m.target === 'ReceiveMessage') {
          let d: any;
          try { d = JSON.parse(m.arguments[0]); } catch { return; }
          const st = d.station_settings || {};
          if (st.code && String(st.code) !== code) return;
          if (st.data_time && Date.now() - new Date(st.data_time).getTime() > MAX_AGE_MS) return;
          done(() => resolve(d));
        } else if (m.type === 7) {
          done(() => reject(new Error(m.error || 'closed')));
        }
      });
    };
  });

// Keep only what the backend parser needs (~700 KB -> a few KB)
const slim = (d: any) => {
  const trains = (d.trains || [])
    .filter((t: any) => ['destination', 'intermediate'].includes(t.class_stop) && ['L', 'R'].includes(t.traffic_type))
    .map((t: any) => ({
      id: t.id, commercial_id: t.commercial_id, company: t.company, traffic_type: t.traffic_type,
      class_stop: t.class_stop, status: t.status, arrival_time: t.arrival_time, delay_in: t.delay_in,
      platform_in: t.platform_in, platform: t.platform, origins: t.origins, technical_number_in: t.technical_number_in,
    }));
  const stations: Record<string, any> = {};
  trains.forEach((t: any) => (t.origins || []).forEach((o: any) => {
    const s = d.stations?.[o.code];
    if (s) stations[o.code] = { name: s.name };
  }));
  const st = d.station_settings || {};
  return {
    station_settings: { code: st.code, data_time: st.data_time },
    trains,
    stations,
    station_alerts: d.station_alerts || [],
  };
};

let inFlight = false;

// Read the given stations from the device and post them. Returns true if anything was relayed.
export const relaySivStations = async (apiBase: string, codes: string[]): Promise<boolean> => {
  if (inFlight || !codes.length) return false;
  inFlight = true;
  let relayed = false;
  try {
    const token = await AsyncStorage.getItem('token');
    if (!token) return false;
    for (const code of codes) {
      try {
        const payload = slim(await readStation(code));
        await axios.post(`${apiBase}/api/trains/siv-snapshot`, { station_id: code, payload }, {
          headers: { Authorization: `Bearer ${token}` },
        });
        relayed = true;
      } catch (e: any) {
        console.log(`[SIV] Station ${code} not relayed:`, e?.message || e);
      }
    }
  } finally {
    inFlight = false;
  }
  return relayed;
};

// Stations whose server copy is missing or older than ~4 min
export const staleSivStations = (trainData: any): string[] => {
  const out: string[] = [];
  [['atocha', '60000'], ['chamartin', '17000']].forEach(([key, code]) => {
    const st = trainData?.[key];
    if (!st) return;
    const age = st.data_time ? Date.now() - new Date(st.data_time).getTime() : Infinity;
    if (st.source !== 'siv' || age > 4 * 60 * 1000) out.push(code);
  });
  return out;
};
