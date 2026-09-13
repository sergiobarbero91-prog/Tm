/**
 * Shared Madrid taxi fare estimator.
 *
 * Uses the exact same logic as the public (pre-login) calculator, which is
 * the source of truth. Consumed by:
 *   - components/PublicFareCalculator.tsx (calls calculateEstimatedFare)
 *   - the internal Tarifas tab in index.tsx
 *   - components/EmisoraClient.tsx to show "Tarifa estimada" before requesting
 *
 * Official Madrid tariffs (2025):
 *   T1  Día laborable 07-21h → bajada 2,55€ + 1,40€/km
 *   T2  Noches, findes, festivos → bajada 3,20€ + 1,60€/km
 *   T3  Aeropuerto ↔ fuera M30 → base 22€ (incluye 9km) + km extra a T1/T2
 *   T4  Aeropuerto ↔ dentro M30 → tarifa fija 33€
 *   T7  Estaciones/IFEMA → base 8€ (incluye 1,4km) + km extra a T1/T2
 */
import axios from 'axios';

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL || '';

export type FareResult = {
  tarifa: string;
  fare_min: number;
  fare_max: number;
  distance_km: number;
  details: string;
};

export type FareOriginType = 'terminal' | 'station' | 'street';

const TERMINAL_COORDS: Record<string, { lat: number; lng: number }> = {
  T1: { lat: 40.4676, lng: -3.5701 },
  T2: { lat: 40.4693, lng: -3.5660 },
  T3: { lat: 40.4654, lng: -3.5708 },
  T4: { lat: 40.4719, lng: -3.5626 },
};
const STATION_COORDS: Record<string, { lat: number; lng: number }> = {
  Atocha: { lat: 40.4055, lng: -3.6883 },
  Chamartín: { lat: 40.4720, lng: -3.6822 },
};

const haversine = (lat1: number, lon1: number, lat2: number, lon2: number) => {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

const isAirportKeyword = (s: string) =>
  /barajas|aeropuerto|airport|\bt[1-4]s?\b/i.test(s.trim());

const isStationKeyword = (s: string) =>
  /atocha|chamart[ií]n|ifema|estaci[oó]n/i.test(s.trim());

const detectOriginType = (originText: string): { type: FareOriginType; key: string } => {
  const s = originText.trim();
  // Try to match terminal shorthand first
  const term = s.match(/\bt([1-4])s?\b/i);
  if (term) return { type: 'terminal', key: `T${term[1]}` };
  if (isAirportKeyword(s)) return { type: 'terminal', key: 'T4' };
  if (/atocha/i.test(s)) return { type: 'station', key: 'Atocha' };
  if (/chamart/i.test(s)) return { type: 'station', key: 'Chamartín' };
  if (isStationKeyword(s)) return { type: 'station', key: 'Atocha' };
  return { type: 'street', key: s };
};

/** Compute a Madrid taxi fare estimate given free-text origin + destination. */
export async function calculateEstimatedFare(
  originText: string,
  destinationText: string,
  now: Date = new Date(),
): Promise<FareResult> {
  const hour = now.getHours();
  const day = now.getDay();
  const isNight = hour >= 21 || hour < 7;
  const isWeekend = day === 0 || day === 6;
  const isTarifa2 = isNight || isWeekend;
  const tarifaBase = isTarifa2 ? 'Tarifa 2' : 'Tarifa 1';
  const per_km_rate = isTarifa2 ? 1.6 : 1.4;
  const bajada_bandera = isTarifa2 ? 3.2 : 2.55;

  const { type: originType, key: originKey } = detectOriginType(originText);
  let originCoords: { lat: number; lng: number } | null = null;
  let isAirport = false;
  let isStation = false;

  if (originType === 'terminal') {
    originCoords = TERMINAL_COORDS[originKey] || TERMINAL_COORDS.T4;
    isAirport = true;
  } else if (originType === 'station') {
    originCoords = STATION_COORDS[originKey] || STATION_COORDS.Atocha;
    isStation = true;
  } else {
    const geo = await axios
      .get(`${API_BASE}/api/geocode/forward`, {
        params: { address: `${originKey}, Madrid, Spain` },
        timeout: 10000,
      })
      .catch(() => null);
    if (geo?.data?.latitude && geo?.data?.longitude) {
      originCoords = { lat: geo.data.latitude, lng: geo.data.longitude };
    }
  }
  if (!originCoords) throw new Error('No se pudo localizar el origen');

  // Destination — geocode and check M30
  const destGeo = await axios
    .get(`${API_BASE}/api/geocode/forward`, {
      params: { address: `${destinationText}, Madrid, Spain` },
      timeout: 10000,
    })
    .catch(() => null);
  if (!destGeo?.data?.latitude || !destGeo?.data?.longitude) {
    throw new Error('No se pudo localizar el destino');
  }
  const destCoords = { lat: destGeo.data.latitude, lng: destGeo.data.longitude };
  const isDestInsideM30: boolean = !!destGeo.data.is_inside_m30;

  // Route distance (fallback to haversine * 1.3 straight-line factor)
  let distance_km = 0;
  try {
    const r = await axios.post(
      `${API_BASE}/api/calculate-route-distance`,
      {
        origin_lat: originCoords.lat,
        origin_lng: originCoords.lng,
        dest_lat: destCoords.lat,
        dest_lng: destCoords.lng,
      },
      { timeout: 15000 },
    );
    distance_km = r.data?.distance_km || 0;
  } catch {
    distance_km = haversine(originCoords.lat, originCoords.lng, destCoords.lat, destCoords.lng) * 1.3;
  }

  if (isStation) {
    // Tarifa 7
    const TARIFA_7_BASE = 8.0;
    const TARIFA_7_KM_FRANCHISE = 1.4;
    const extra_km = Math.max(0, distance_km - TARIFA_7_KM_FRANCHISE);
    const total = TARIFA_7_BASE + extra_km * per_km_rate;
    return {
      tarifa: extra_km > 0 ? `Tarifa 7 + ${tarifaBase}` : 'Tarifa 7',
      fare_min: total,
      fare_max: total * 1.05,
      distance_km,
      details:
        extra_km > 0
          ? `Base 8€ (1,4km incluidos) + ${extra_km.toFixed(1)}km × ${per_km_rate.toFixed(2)}€/km`
          : 'Base 8€ (primeros 1,4km incluidos)',
    };
  }
  if (isAirport && isDestInsideM30) {
    // Tarifa 4 fija
    return {
      tarifa: 'Tarifa 4 (Fija)',
      fare_min: 33,
      fare_max: 33,
      distance_km,
      details: 'Tarifa fija aeropuerto ↔ dentro de M30',
    };
  }
  if (isAirport && !isDestInsideM30) {
    // Tarifa 3
    const TARIFA_3_BASE = 22.0;
    const TARIFA_3_KM_FRANCHISE = 9;
    const extra_km = Math.max(0, distance_km - TARIFA_3_KM_FRANCHISE);
    const total = TARIFA_3_BASE + extra_km * per_km_rate;
    return {
      tarifa: extra_km > 0 ? `Tarifa 3 + ${tarifaBase}` : 'Tarifa 3',
      fare_min: total,
      fare_max: total * 1.05,
      distance_km,
      details:
        extra_km > 0
          ? `Base 22€ (9km incluidos) + ${extra_km.toFixed(1)}km × ${per_km_rate.toFixed(2)}€/km`
          : 'Base 22€ (primeros 9km incluidos)',
    };
  }
  // Tarifa 1/2 street
  const total = bajada_bandera + distance_km * per_km_rate;
  return {
    tarifa: tarifaBase,
    fare_min: total,
    fare_max: total * 1.05,
    distance_km,
    details: `Bajada bandera ${bajada_bandera.toFixed(2)}€ + ${distance_km.toFixed(1)}km × ${per_km_rate.toFixed(2)}€/km`,
  };
}
