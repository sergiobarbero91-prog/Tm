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
- `/app/test_reports/iteration_9.json` — fork session: Instant Demand 4/4 ✅; Daily Summary endpoints were missing → reimplemented in this session.

## Changelog (fork — May 2026)

### ✅ Re-implemented Instant Demand backend (was missing in /app/backend/server.py)
- Added `calculate_instant_demand()` in `/app/backend/server.py` (~line 1335).
- Extended `TerminalData` model with `instant_demand_pct`, `instant_demand_level`, `instant_demand_trend`.
- Wired into `/api/flights` for all 5 terminals (T1, T2, T3, T4, T4S).
- Pressure points: next 0-15min × 2.0, next 15-30min × 1.0, past 0-15min × 1.5; ÷10×100 → pct (cap 500); levels green<40 / yellow<80 / red<150 / critical≥150.

### ✅ Re-created daily_summary router (was lost from previous session)
- New `/app/backend/routers/daily_summary.py` with `GET /api/events/daily-summary` (public) and `POST /api/events/daily-summary/regenerate` (admin-gated via `get_admin_user`).
- Registered BEFORE `events_router` in `/app/backend/server.py` so the literal `/daily-summary` path wins over the `/{event_id}` catch-all (fixes the 405 collision detected in iteration 9).
- Added `daily_summaries_collection` to `/app/backend/shared.py`.
- Uses `google-genai` SDK with `Tool(google_search=GoogleSearch())` and `gemini-2.5-flash-lite`; reads `GEMINI_API_KEY` from env.
- Always returns the 4 required sections (defensive `_ensure_sections` guard).
- Caches per Madrid date in MongoDB; first GET of the day generates, subsequent ones serve cached.

### ✅ Frontend Demanda Instantánea bar in `renderTerminalCard`
- Aggregates per-group: avg pct, worst level, dominant trend.
- Inserted below the Score chip with flash icon, %, trend arrow (trending-up/down/remove), and a colored progress bar (green/yellow/red/critical).
- Styles in `/app/frontend/app/styles/mainStyles.ts` (`instantDemandContainer`, `instantDemandBarTrack`, `instantDemandBarFill`, etc.).
- data-testids: `flight-{groupName}-instant-demand-pct`, `flight-{groupName}-instant-demand-bar`.

### Test results
- `pytest /app/backend/tests/test_instant_demand_and_summary.py -v` → **11/11 PASS** (Instant Demand 4/4, Daily Summary 4/4, Regenerate Auth 2/2, Trains 1/1).

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
