
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

## 🪪 Emisora: QR y código fijos + tarjeta de visita (Jun 2026)
- The 6-digit code never rotates now (no more 24h auto-rotation). The POST /api/rides/driver/qr/rotate endpoint and the "Generar nuevo código" button are removed (user's choice). The code is generated with secrets.randbelow. Existing drivers keep their current code.
- New GET /api/rides/driver/qr/card.png (auth): an 85x55 mm @300dpi PNG with the name, phone, licence, QR (FRONTEND_PUBLIC_URL/?cliente_qr=token), code and site. Built by `backend/business_card.py` (qrcode + Pillow, fonts bundled in backend/assets/fonts/Liberation).
- Frontend: a "Descargar tarjeta de visita" button in the QR modal (web download tarjeta-taxi.png).
- Tests: test_rides.py updated, test_driver_business_card.py; iteration_28 100%.

## 📱 SIV relay from the driver's phone (Jun 2026)
- In production (Clouding VPS) Adif answers HTTP 403 to the server WebSocket. Confirmed in the logs.
- `frontend/app/components/sivRelay.ts`: the device opens wss://info.adif.es/InfoStation, keeps only the L/R destination/intermediate trains, alerts and origin names (slim payload), and POSTs to /api/trains/siv-snapshot. It only runs when the server copy is missing or older than 4 min, never for historical queries, and is guarded by inFlight.
- Backend: POST /api/trains/siv-snapshot (auth, valid station, ≤400 trains). ingest_relayed_payload only accepts a fresh data_time (≤5 min, ≤60 s in the future) that is newer than the stored one. It updates arrival_cache + trains_cache and persists to the `siv_state` collection (restored at startup).
- fetch_train_arrivals_combined uses the relayed snapshot (≤15 min old) before the legacy fallback. On a 403 the server does not retry.
- Tests: test_siv_relay.py (8), test_adif_siv.py (5). iteration_29: 100% with a simulated 403.

## 🪪 Business card with the user's design (Jun 2026)
- Template `backend/assets/card/template.png` (1536x1024) is the user's design with the word "admin" removed (OpenCV inpaint). Fonts are Poppins ExtraBoldItalic/ExtraBold/Bold (OFL) in backend/assets/fonts.
- `business_card.py` draws, in fixed regions: the driver's name (shadow, auto-fit), the QR (decodes correctly), the 6-digit code, and the phone (+34 stripped, "611 000 999"; "Pide tu taxi en la app" if there is no phone). The web address and icons are part of the template.

## 💶 Gestión: Porcentaje fijo + Pago fijo (alquiler) (Jun 2026)
- "Fijo" was renamed "Porcentaje fijo". New mode pago_fijo: € per day × days (editable, default 125×22). The owner always gets the full amount, whatever the days worked.
- Driver benefit = billing − fixed payment − petrol (only if the driver pays it). Settlement = fixed payment − card − app − petrol (if the owner pays it). The breakdown and the PDF are adapted. Mode buttons are a 2x2 grid. iteration_30 100%.

## 🚫 Trenes cancelados en desplegable (Jun 2026)
- parse_siv_payload returns cancelled_trains (scheduled_time, day_label 'mañana', origin, train_type, train_number, operator) within -30 min..+12 h. Cancelled trains are no longer carried over as 'Llegado'. /api/trains exposes StationData.cancelled_trains.
- StationSivInfo: the 'N trenes cancelados' row expands/collapses like the alerts. iteration_31 100%.
- Known (pre-existing): on 390 px the header with the user menu overflows by ~19 px.

## 📅 Agenda automática de Madrid (Jun 2026)
- Researched madrono.app: its events come from a manually maintained Google Sheet published at api.madrono.app/eventos. Not used: it is their own work.
- `backend/agenda_sources.py` sources:
  - ESPN public schedules: home matches in Madrid for Real Madrid, Atlético, Rayo, Getafe and Leganés.
  - Movistar Arena: links on /programacion. Basketball is tagged 'deporte'.
  - Palacio Vistalegre: tribe events REST API.
  - La Riviera and IFEMA: JSON-LD. Fairs are expanded per day 10-19 h; anything longer than 10 days is excluded.
  - datos.madrid.es agenda: big municipal venues + FiestasNavidadesReyes, recurrence expanded, courses/workshops excluded.
- `routers/events.py`:
  - refresh_agenda + agenda_refresh_loop (every 6 h, started at startup). Upsert by uid into agenda_events with a unique index. Cleanup removes ended events and events dropped by their source.
  - GET /api/events/agenda?days (auth, 1-21, UTC query fields).
  - Also fixed: GET /api/events/active used a sync loop over an async cursor.
- daily_summary: _agenda_facts_today injects today's verified agenda into the Gemini prompt.
- Frontend: components/AgendaSection.tsx in the Eventos tab (filters Todo/Deportes/Conciertos/Ferias/Cultura, grouped by day, ALTA DEMANDA badge, tapping a row opens its link).
- Tests: test_agenda_sources.py, test_agenda_api.py. iteration_32 100%.
