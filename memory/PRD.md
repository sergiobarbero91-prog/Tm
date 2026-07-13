# PRD — As del Volante (Taxi Madrid app)

## Original Problem
Reliable train + flight data aggregator for Madrid taxi drivers (asdelvolante.es). Includes:
- Live trains (Atocha, Chamartín) and flights (Barajas T1-T4S)
- Hot zones reporting
- Public fare calculator with strict Madrid tariffs
- Community events with votes
- WhatsApp bot hourly broadcast
- AI-generated daily event summary

## User
Spanish-speaking taxi drivers in Madrid. Tone: professional, tutea, direct.

## Tech Stack
- Backend: FastAPI + Motor (MongoDB)
- Frontend: Expo Web + React Native (single `app/index.tsx`)
- Database: MongoDB
- AI: Google Gemini 2.5-flash-lite with Google Search Grounding (`google-genai` SDK)
- WhatsApp: `whatsapp-web.js` Node microservice
- Deployment: User-managed Ubuntu + docker compose + Nginx + Let's Encrypt SSL

## Baseline
The on-disk code in /app matches https://github.com/sergiobarbero91-prog/Tm (single commit `656183e`).
Only the items below have been added on top of that baseline.

## Changelog (this session — Feb 2026)

### ✅ Demanda Instantánea (Aviones)
- `/app/backend/server.py` lines ~1394-1505: helper functions (`_is_long_haul_flight`, `calculate_instant_demand`, `instant_demand_level`, `instant_demand_trend`).
- Model `TerminalData` extended with `instant_demand_pct`, `instant_demand_level`, `instant_demand_trend`.
- Endpoint `/api/flights` enriches each terminal with these fields (skipped on custom time-windows).
- Pressure points: EN TIERRA <5min=+0.2; ENTREGANDO <15min=+0.4, >15min=+0.8; FINALIZADO 0-15min=+1.0, 16-30min=+0.3; ×1.5 long-haul; ×10 = %.
- Frontend: NEW bar in `renderTerminalCard` (line ~7892-7965) BELOW the existing Score chip, labeled "Demanda en este Momento", with %, trend arrow ⬆⬇➡, colored progress bar (green<40, yellow 40-70, red 70-100, critical >100). testIDs `instant-demand-T1/T2/T4`.
- Original UI 100% preserved: `XA - YP` orange/green counters, Score chip "Score: X.X" remain unchanged.

### ✅ AI Daily Summary (`/app/backend/routers/daily_summary.py`)
- Gemini 2.5-flash-lite + `google_search` tool (grounding). 500 RPD free tier.
- `max_output_tokens=1500`, `temperature=0.1`.
- Telegram-style prompt with 4 mandatory sections: `[GRANDES EVENTOS]`, `[TEATROS Y OCIO]`, `[ALERTAS DE TRÁFICO]`, `[PREVISIÓN MAÑANA]`.
- **Bold** for places and hours.
- Anti-loop: dedupes consecutive identical lines.
- Anti-hallucination: rejects responses with no grounding metadata.
- Retries on 503/429 with backoff.
- Endpoints: `GET /api/events/daily-summary` (public), `POST /api/events/daily-summary/regenerate` (admin).
- Daily scheduler at 05:00 Madrid + hourly retry on failure (in `/app/backend/server.py` line ~3946).
- `/app/backend/shared.py`: added `daily_summaries_collection`.
- `requirements.txt`: added `google-genai==1.63.0`, `brotli==1.1.0`.
- `/app/backend/.env`: added `GEMINI_API_KEY`.

### ✅ Frontend "Resumen del Día" card
- `/app/frontend/app/index.tsx` line ~437-447: states.
- Line ~3627-3645: `fetchDailySummary`.
- Line ~6461 (& deps line 6495): triggers on Eventos tab.
- Line ~11231-11400: card JSX with parsed [SECTION] headers (violet bold) and **bold** segments (yellow).

### ✅ WhatsApp Bot: AI summary injection
- `/app/whatsapp-bot/index.js`: `/send-hourly-update` prepends "🤖 RESUMEN DEL DÍA (IA)" block fetched from `/api/events/daily-summary`.

### ✅ SSL Auto-renewal (no longer manual)
- `/app/nginx/nginx.conf`: allows `/.well-known/acme-challenge/` via HTTP.
- `/app/docker-compose.yml`: `certbot_webroot` shared volume + Nginx auto-reload every 6h + certbot `--webroot` mode.

## Test Reports
- `/app/test_reports/iteration_7.json` — initial test (backend 11/11 ✅, AI card not rendering due to stale Metro cache)
- `/app/test_reports/iteration_8.json` — final re-test (**Backend 11/11 ✅ + Frontend 2/2 ✅**)
- `/app/test_reports/iteration_9.json` — fork session post-fork: missing prod files detected.
- `/app/test_reports/iteration_10.json` — **PROD MERGE COMPLETE: 27/29 PASS** (2 fails are external Gemini 429 quota, NOT code).

## Changelog (May 2026 — Production Recovery Merge)

### ✅ Recovered full production codebase to GitHub
- `/app/backend/server.py` (3958 → 4448 lines): full prod logic including `is_large_aircraft`, `LARGE_AIRCRAFT_CODES`, `AENA_STATUS_MAP`, `upsert_tracked_flights`, `calculate_saturation`, `flight_sort_key`, AENA fallback fetcher, status mapping (`IBK → Entregando equipaje`), tracking of finalized flights in MongoDB.
- `/app/backend/routers/buses.py` (NEW, 398 lines): scraping of ALSA + Avanza arrivals (Avda. América + Estación Sur) via BeautifulSoup, mongo caching.
- `/app/backend/routers/reservations.py` (NEW, 381 lines): full taxi reservations lifecycle (create, offer, accept, cancel, calendar, logs).
- `/app/backend/shared.py`: added `daily_summaries_collection`, `flights_tracked_collection`.
- `/app/frontend/app/index.tsx` (17575 → 19323 lines): full prod UI for airport terminal cards with P/E/F/S badges (Próximos/Entregando/Finalizado/Siguientes), GRANDES wide-body tag, Cinta de equipaje, status colors, taxi-exit panel, alert buttons, etc.
- `/app/frontend/app/styles/mainStyles.ts`: replaced by prod version.
- `/app/frontend/app/components/PublicBusArrivals.tsx` (NEW): public homepage bus widget.
- `/app/frontend/app/components/PublicEventsSummary.tsx` (NEW): public homepage daily events summary widget.

### ✅ New `calculate_instant_demand()` spec (user-defined)
Pressure points based on STATUS + minutes since landing:
- FINALIZADO 0-15 min: +1.0  |  16-30 min: +0.3
- ENTREGANDO EQUIPAJE >15 min: +0.8  |  <15 min: +0.4
- EN TIERRA: +0.2 fixed
- Multiplier x1.5 for wide-body aircraft (via `is_large_aircraft()`)
- pct = points × 10 (allows >100% for critical saturation)
- Levels: green<40, yellow<70, red≤100, critical>100
- Returned fields: `instant_demand_pct`, `instant_demand_level`, `instant_demand_points`

### ✅ Two demand bars in the airport terminal card
- **Top bar (was "DEMANDA")** → relabeled "**PREVISIÓN PRÓXIMA HORA**" (existing saturation algorithm).
- **NEW bottom bar**: "**DEMANDA EN ESTE MOMENTO**" — flash icon + colored value (green/yellow/red/critical) + trend arrow (⬆/⬇/➡) computed in-component vs the previous tick via `useRef`. Numeric % can exceed 100, with a "SATURACIÓN CRÍTICA" caption when so.

### ✅ Improved error handling
- `routers/daily_summary.py`: Gemini 429 RESOURCE_EXHAUSTED now translates to HTTP 503 + `Retry-After: 3600` header with a clean Spanish message.

### Test results
- `pytest /app/backend/tests/test_instant_demand_and_summary.py -v` → **11/11 PASS** ✅
- Iteration 10 testing agent: **27/29 PASS** (2 fails are upstream Gemini quota, not code).

## Session log — Production deploy (13 May 2026)

### ✅ Deployed to production (asdelvolante.es)
- Server.py merge (3958→4453), routers/buses.py + routers/reservations.py + routers/daily_summary.py created, frontend index.tsx merge (17575→19327), 2 new public components.
- GEMINI_API_KEY added to /home/TM/backend/.env.
- Containers rebuilt: taximeter-backend + taximeter-frontend.
- Endpoint `/api/events/daily-summary-public` created for homepage widget (component PublicEventsSummary expected `success/summary/day_name`).
- Endpoint `/api/events/daily-summary` GET now returns `success: true` (dashboard frontend checks that flag).
- Model upgraded `gemini-2.5-flash-lite → gemini-2.5-flash` + exhaustive prompt with 8+ queries/section, forces deeper search before declaring "Sin información".
- Result on Madrid San Isidro day: 22 sources, 12 distinct queries, 5+ events in [GRANDES EVENTOS], 7 in [TEATROS Y OCIO], all 4 sections populated.

### ✅ Jornada con OCR del taxímetro ("Gestión" — pestaña automatizada) — Feb 2026
- `/app/backend/routers/journal.py` (470 LOC): nuevo router con
  - `POST /api/journal/start` (multipart `photo`) → Gemini Vision OCR (gemini-2.5-flash) extrae 9 campos del parcial inicial.
  - `POST /api/journal/fuel` (form `amount_eur`, `liters?`, `note?`) → añade gasto a la jornada abierta. Rechaza importe ≤ 0.
  - `POST /api/journal/end` (multipart `photo` + `precio_cerrado`, `cobrado_tarjeta`, `cobrado_app`) → OCR parcial final + computa `totals` con:
    - facturacion_taximetro_eur = carreras_fin − carreras_inicio
    - precio_cerrado_eur, total_ingresos_eur, cobrado_tarjeta/app/efectivo, gasto_gasolina_eur, total_neto_eur
    - dist_*_diff_km, tiempo_*_diff, num_servicios_diff, media_eur_servicio
  - `GET /api/journal/active` → jornada abierta del usuario actual.
  - `GET /api/journal/list?limit=30` → historial ordenado por start_at desc.
  - `PUT /api/journal/{id}/manual` (form `field=start|end`, `payload=JSON`) → corrección manual de lectura OCR (recomputa `totals` si está cerrada).
  - `DELETE /api/journal/{id}`.
- Router registrado en `/app/backend/server.py` (línea 78 + 4037).
- Frontend `/app/frontend/app/index.tsx`:
  - Estado OCR (líneas ~437–460), helpers (líneas ~462–600).
  - useEffect: al abrir pestaña `gestion` precarga active + history.
  - UI (líneas ~13028–13234): sección verde "📷 Jornada con foto del taxímetro" arriba del calculador manual existente. 3 modales (gasolina, cerrar jornada, corregir lectura).
- Tests pytest `/app/backend/tests/test_journal.py`: 12/12 PASS.

### ✅ AI Daily Summary — Markdown bold ahora se renderiza (Feb 2026)
- `/app/frontend/app/index.tsx` ~líneas 12660–12698: renderer inline detecta `[SECTION]` (violeta bold uppercase sin corchetes) y `**bold**` (ámbar bold). Sin asteriscos literales.

### ✅ Daily Summary — Regla horaria reforzada (Feb 2026)
- `/app/backend/routers/daily_summary.py` regla #9: nunca inventar horas; si no hay fuente oficial → "(horario por confirmar)".

### ✅ Métricas avanzadas + Gráficas de Tendencia (Feb 2026)
- `_compute_totals` ampliado con **14 nuevas métricas**:
  - **Tiempo**: `tiempo_jornada_min/str` (reloj inicio→fin), `tiempo_on_min` (trabajo efectivo), `tiempo_ocupado_min` (cargado), `pct_tiempo_ocupacion` (ocupado/on × 100).
  - **Facturación**: `total_ingresos_eur` (carreras+cerrado), `eur_por_hora`, `eur_por_km`, `media_eur_servicio`.
  - **Distancia**: `dist_total/ocupado/libre_diff_km`, `pct_dist_ocupado`.
  - **Combustible**: `gasto_gasolina_por_km` (€/km desde último repostaje con km_total_at_refuel; fallback a fuel/km_totales), `rendimiento_por_km` (€/km facturado − €/km gasolina), `rendimiento_por_eur_gasolina` (facturado / gasto), `refuel_warning` (mensaje cuando no se anotaron km al repostar).
- POST `/api/journal/fuel` acepta nuevo campo opcional `km_total_at_refuel` (km del taxímetro al repostar).
- Nuevo endpoint **GET `/api/journal/stats?bucket=day|week|month&days=N`** → series agregadas (`neto_eur`, `ingresos_eur`, `gasolina_eur`, `km_total`, `horas_on`, `servicios`, `jornadas`, `eur_por_hora`, `eur_por_km`) + totales del período. Para gráficas.
- Gemini 429 ahora se mapea a HTTP 503 con header `Retry-After: 60` en `_ocr_parcial_sync` (antes filtraba como 500 genérico).
- Frontend:
  - Tarjeta de resultados reagrupada en **4 bloques** (Tiempo, Facturación, Distancia, Combustible+Rendimiento) cada uno con su color y un destacado grande del valor clave. Bloque final dedicado al NETO en grande.
  - Modal "Añadir gasolina" ahora pide opcionalmente "Km del taxímetro al repostar" con explicación.
  - Modal "Cerrar jornada" muestra un banner ámbar: "💡 Antes de cerrar el turno: reposta y registra el gasto con los km del taxímetro".
  - Nueva sección **"Tendencia"** con selector día/semana/mes, 6 tarjetas de KPI (Neto, Jornadas, Horas, €/h, Km, €/km) y un gráfico SVG inline de Neto vs Facturado.
- Tests pytest `/app/backend/tests/test_journal.py`: 20 tests (8 deterministas + 12 dependientes de Gemini que skipean limpiamente cuando hay cuota agotada). Todos los valores numéricos verificados en la primera corrida con cuota fresca.

### ✅ Modo de cobro variable + Resumen por rango + PDF (Feb 2026)
- **Backend** `/app/backend/routers/journal.py`:
  - Nuevo endpoint `GET /api/journal/summary?start=YYYY-MM-DD&end=YYYY-MM-DD` que devuelve agregados de las jornadas cerradas en el rango: `totals` (ingresos, neto, gasolina, km, horas_on, jornadas, dias_trabajados, €/hora, €/km, servicios, carreras, precio_cerrado, cobrado_*, dist_*, % ocupación, % km cargado) + `daily` (desglose por día para variable diario).
  - Validación: 400 si fechas inválidas o `end<start`.
- **Frontend** `/app/frontend/app/index.tsx`:
  - **"Modo de cobro"** dropdown con 3 opciones (`gestion-mode-fijo`, `-variable_diario`, `-variable_mensual`).
    - Fijo → selector 40/45/50 existente.
    - Variable diario/mensual → editor de 3 tramos: 0–T1€ → P1%, T1–T2€ → P2%, >T2€ → P3% (defaults 130/200/40/45/50). Inputs: `gestion-bracket-t1/t2/p1/p2/p3`.
  - **"Resumen del periodo"** sustituye al antiguo "Datos del turno":
    - Date pickers nativos (`<input type="date">` en web) para `start` y `end`.
    - Presets: Hoy / Semana / Este mes / Mes pasado.
    - Modo READ-ONLY por defecto: muestra 10 tarjetas KPI + bloque detalle (carreras, cerrado, cobros, km cargado/libre, %).
    - Botón "Cálculo manual" (`gestion-toggle-manual`) cambia a inputs editables con banner ámbar "✏️ Cálculo libre — no afecta a tus jornadas guardadas".
  - **Botón CALCULAR** actualizado:
    - `fijo`: `rec × %` (igual que antes).
    - `variable_mensual`: aplica `bracketPct(total_facturado) × total_facturado`. Ej: 220€ → tramo >200€ → 50% × 220 = 110€.
    - `variable_diario`: itera `daily[]` y suma `dia.facturado × bracketPct(dia.facturado)`. Si no hay datos diarios → fallback a mensual + warn en consola.
  - **PDF (`Descargar PDF`)** incluye:
    - Rango de fechas seleccionado en cabecera.
    - Modo (`Fijo X%` / `Variable diario` / `Variable mensual`).
    - Tramos: `0–130€ → 40% · 130–200€ → 45% · >200€ → 50%`.
    - Tabla con datos del periodo (15 filas si hay summary) o del turno manual.
- Tests `/app/backend/tests/test_journal_summary.py`: 10 tests (8 PASS deterministas + 2 skipped por cuota Gemini). Verificado: 401 sin auth, 422 sin params, 400 fechas inválidas o `end<start`, rango vacío devuelve estructura completa con divisiones por cero como `None`, rango de 1 día funciona, /stats sigue funcionando.

### 🐛 Bug fix — Eventos IA reportando eventos ya terminados (Feb 2026)
- **Síntoma reportado**: el resumen mostraba partidos ya jugados, teatros de mañana a las 22h, etc.
- **RCA (2 causas)**:
  1. El prompt sólo indicaba la FECHA pero no la HORA ACTUAL → el modelo no tenía referencia para excluir eventos terminados.
  2. La caché usaba `{date: today}` → una vez generado a las 07:00 se servía el mismo texto todo el día.
- **Fix** (`/app/backend/routers/daily_summary.py`):
  - Nuevas helpers `_now_madrid_hhmm()` y `_cache_slot_madrid()` (slot cada 4h: 00/04/08/12/16/20).
  - Prompt reforzado con bloque "REGLA DE VIGENCIA" (la más importante):
    - Incluye la hora actual explícitamente (dos veces).
    - "Eventos con FINALIZACIÓN anterior a HH:MM: PROHIBIDOS".
    - "Eventos en curso: marcar (en curso)".
    - "Eventos de AYER, ANTEAYER u otra fecha: TOTALMENTE PROHIBIDOS aunque Google los devuelva".
    - Regla #10: cada bullet DEBE contener una hora; sin hora, mejor descartar.
  - Caché cambiada a `{cache_slot: 'YYYY-MM-DDTHH'}` → refresco automático cada 4h. Docs antiguos sin `cache_slot` se ignoran → primera petición del día fuerza regeneración.
  - Public endpoint hereda el mismo comportamiento (usa el mismo `_load_cached`).
- **Tests**: `/app/backend/tests/test_daily_summary_freshness.py` (20/20 PASS): prompt keywords, cache slot format, round-trip DB por `cache_slot`, stale-slot ignorado, cache hit devuelve mismo `generated_at`, `force_refresh` regenera, endpoint público comparte doc.

### 🟡 P1 — Open items for next session
- 🆕 **New AEROPUERTO section in daily summary with optimal terminal arrival time** (user request 13 May 2026): cross AENA flight data we already have at `/api/flights` (terminals, instant_demand_pct, saturation_30min/60min, large_30min, delivering_30min, arrival schedules) with the AI summary to suggest the taxi driver the **best time to head toward each terminal** based on landing "waves". Example output: "T4S — pico previsto 18:30h-19:15h (5 vuelos grandes seguidos, sal de aquí a las 17:50h)". Implementation notes:
   - DO NOT need more Gemini calls. Compute peaks in backend from the flights cache (group landings by 15-min buckets, weight by aircraft size/status, pick top-3 peaks of the next 6h per terminal).
   - Either pass the computed peaks as extra context to Gemini so it includes a 5th `[AEROPUERTO]` section, OR render it as a separate UI block above the AI summary card (cheaper, no token cost).
   - Check daily Gemini quota headroom before deciding: today we used 12 queries for the city summary. The free tier of gemini-2.5-flash allows ~1500/day, plenty of room.
- **Rotate the GEMINI_API_KEY** — was exposed in chat history. Replace with a fresh key from https://aistudio.google.com/apikey on both /home/TM/backend/.env (prod) and Emergent preview backend/.env.

## P0 / Pending User Actions
- Force Push to GitHub (commits in Emergent are only mine, no remote-only commits to lose)
- On Ubuntu server: `git pull && docker compose build backend && docker compose up -d`
- Add `GEMINI_API_KEY` to production `.env`
- Renew SSL once with the standalone command, then auto-renewal kicks in.

## P1 / Upcoming
- WhatsApp Puppeteer session auto-recovery (currently manual `rm -rf .wwebjs_auth`)
- Force Disconnect button for WhatsApp bot in admin UI

## P2 / Future
- ADIF API IP rotation (night blocking)
- Refactor `server.py` (~4000 lines) into modules
- Refactor `frontend/app/index.tsx` (~18000 lines)
- Accessibility improvements

## Critical Business Logic (don't break)
- Fare Calculator T1/T2/T3/T4/T7/Nochebuena tariffs are exact official Madrid values.
- Grouped airport terminals on login page: T1, T2-T3, T4-T4S.
- WhatsApp hourly broadcast runs 6-23h with random minute 1-30.
