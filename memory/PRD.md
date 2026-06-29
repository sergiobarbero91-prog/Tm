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
