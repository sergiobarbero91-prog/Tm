
## ✈️ Vuelos comerciales vs privados (Jun 2026)
- `backend/flight_classifier.py`: `is_private_flight()` marks a flight private when ANY of these is true: the code looks like a registration (ECMKV, EC-NUY, D-IABC, N123AB), the aircraft is a business jet (C56X, GLEX, PC12...), or the operator is private (NetJets, VistaJet, Flexjet...). Airline codes (IB0618, I21574=Iberia Express, U2, 3O) count as commercial.
- `flight_weight()` = 0.25 for private, 1 otherwise. Applied everywhere: P/E/F/S counters, GRANDES, weighted score/winner, saturation, instant demand, street-data airport counts, daily-summary airport peaks.
- `FlightArrival.is_private` field; TerminalData count fields are now float.
- Frontend: PRIVADO badge + dimmed row (opacity 0.55, grey border), note "N vuelos privados (cuentan 0,25)", fractional counts shown with a comma.
- Tests: tests/test_flight_classifier.py (18), tests/test_flights_private_api.py (5) — iteration_25 100%.
- Known: 16 old tests in test_terminal_demand.py / test_instant_pressure.py are outdated (they expect fields that were removed earlier).

## 🚆 Trenes desde los paneles SIV de Adif (Jun 2026)
- Researched madrono.app: it reads Adif's station panels (SIV, the SignalR WebSocket wss://info.adif.es/InfoStation, topics dnv3-gravita-<code> + PRO-ECM-<code>; Atocha 60000, Chamartín 17000). Its fallbacks are a Google Sheet and then the Adif web. It never mixes sources.
- `backend/adif_siv.py`: read_siv_payload (12s timeout, 2 attempts), parse_siv_payload keeps class_stop destination/intermediate and traffic L/R (no Cercanías), est = scheduled + delay_in; cancelled trains are dropped and counted; coupled trains are de-duplicated; trains that disappear from the panel are carried for 1h as "Llegado" so they count as past; ESP alerts are filtered to L/R.
- server.py: fetch_train_arrivals_combined tries SIV first (legacy ADIF/Renfe only as fallback), refresh_trains_siv_periodically runs every 5 min (and persists to trains_cache), StationData gains source/data_time/cancelled_count/alerts (source='siv' only if the cached arrivals come from SIV).
- Frontend: components/StationSivInfo.tsx (cancelled pill, expandable alerts, "Fuente: paneles de la estación de Adif · HH:MM").
- Tests: tests/test_adif_siv.py (4) + tests/test_trains_siv_api.py; iteration_26 100% backend, frontend bug '0' fixed.
- Known (pre-existing): the real-time train filter in the frontend uses the device timezone, not Europe/Madrid.

## 🚌 Autobuses: Avanza en directo + horarios oficiales de Alsa (Jun 2026)
- Researched madrono.app: Estación Sur comes from the public Avanza API (apisvt.avanzagrupo.com/sge/getServicios?estacion=ESAM&horas=15&grupo=T&previstas=1&tipo=L). Av. América comes from the official Alsa GTFS (Punto de Acceso Nacional), served as avamerica.json.
- `backend/bus_sources.py`:
  - parse_avanza / fetch_estacion_sur_live: SITUADO→"En dársena", RETRASADO→"Retrasado", dársena as platform, 'MANGA, LA'→'La Manga'.
  - build_schedule / avamerica_arrivals / ensure_alsa_schedule: GTFS from files.mobilitydatabase.org/mdb-2825/latest.zip (NAP direct download needs an API key). Reduced to the stop 0000515500000001, long-distance only (origin ≥70 km), times past 24h handled, file at backend/data/alsa_avamerica.json, rebuilt when older than 7 days (loop every 6h). Validated: 68 arrivals vs Madroño's 67 on 1/11.
- routers/buses.py: ES live (2 min cache) → old scrape → static; AA GTFS → CheckMyBus → static. Each station returns source + source_label. Delayed buses stay as upcoming until they arrive (uses ISO 'at').
- Frontend: source line (green dot if live), "Dársena N" line, coloured status badges; footer mentions the new sources.
- Tests: tests/test_bus_sources.py (3), tests/test_buses_api.py (3); iteration_27 100%.
