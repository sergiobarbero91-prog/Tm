# PRD — As del Volante (Taxi Madrid app)

## Original Problem
Reliable train + flight data aggregator for Madrid taxi drivers (asdelvolante.es). Includes:
- Live trains (Atocha, Chamartín) and flights (Barajas T1-T4S)
- Hot zones reporting
- Public fare calculator with strict Madrid tariffs
- Community events with votes
- WhatsApp bot hourly broadcast
- AI-generated daily event summary (Madrid venues + city agenda)

## User
Spanish-speaking taxi drivers in Madrid. Tone: professional but close, tutea.

## Current Tech Stack
- Backend: FastAPI + Motor (MongoDB)
- Frontend: Expo Web + React Native (single `app/index.tsx`)
- Database: MongoDB
- AI: Google Gemini 2.5-flash with Google Search Grounding (`google-genai` SDK)
- WhatsApp: `whatsapp-web.js` Node microservice (external, port 3001)
- Deployment: User-managed Ubuntu + docker compose, Nginx reverse proxy, Let's Encrypt SSL

## Changelog (this session — Feb 2026)

### ✅ Instant Pressure (Demanda en este Momento) — airports (Done)
- Backend `/api/flights` returns per-terminal: `instant_pressure_pct`, `instant_pressure_level` (green/yellow/red/critical), `instant_pressure_trend` (up/down/flat), `instant_pressure_breakdown` (counts per bucket).
- Function `calculate_instant_pressure` in `/app/backend/server.py` (line ~1395-1530) maps minutes-since-arrival to points: <5min=+0.2, 5-15=+0.4, 15-30=+0.8, 30-45=+1.0, 45-60=+0.3 (×1.5 for long-haul). Total × 10 = saturation %.
- Long-haul detection: heuristic by origin city keywords (transatlantic/transpacific/intercontinental).
- Frontend: new bar in `renderTerminalCard` for each airport group below the hourly forecast (relabeled 'Previsión Próxima Hora · Score X.X'). New bar shows 'Demanda en este Momento' + % + trend arrow + colored progress bar.
- Bonus: installed `brotli==1.1.0` so AENA HTML decoding works in preview too.
- Tests: 9/9 pytest passing in `/app/backend/tests/test_instant_pressure.py`. Frontend testIDs `instant-pressure-T1/T2/T4` verified.

### ✅ AI Daily Summary upgrades (Done — earlier today)
- Now zonal briefing: 🏟 GRANDES RECINTOS, ⚽ ESTADIOS (Bernabéu/Metropolitano/Vallecas/Coliseum), 🎭 GRAN VÍA, 🚧 CORTES TRÁFICO, 🎉 DISTRITOS Y MUNICIPIOS (Rivas, Alcorcón, Móstoles, Leganés, Getafe, Pozuelo, etc.).
- 15 obligatory Google Search queries (one per team, per recinto, per source).
- Model: `gemini-2.5-flash-lite` (500 RPD free tier vs 20 for flash).
- Retries with backoff for 503/429.
- Truncation guard: response must end with punctuation.

### ✅ SSL Auto-renewal (Done — earlier today)
- `nginx/nginx.conf` allows `/.well-known/acme-challenge/` via HTTP.
- `docker-compose.yml`: certbot_webroot shared volume + Nginx auto-reload every 6h + certbot `--webroot` mode.

## Dependencies Added
- `google-genai==1.63.0` (added to `/app/backend/requirements.txt`)
- ENV: `GEMINI_API_KEY` in `/app/backend/.env`

## P0 / Pending
- [ ] User to do **Force Push** to GitHub (Emergent → main) and `git pull` + `docker compose build backend && docker compose up -d` on production server.
- [ ] User to verify SSL renewal commands work on their server.

## P1 / Upcoming
- [ ] WhatsApp Puppeteer session corruption auto-recovery (currently manual `rm -rf .wwebjs_auth`).
- [ ] Force Disconnect button for WhatsApp bot in admin UI (paired with existing Restart button).

## P2 / Future
- [ ] ADIF API IP rotation (night blocking).
- [ ] Refactor monolithic `server.py` (~3900 lines) into modules.
- [ ] Refactor monolithic `frontend/app/index.tsx` (~17700 lines).
- [ ] Accessibility improvements.

## Critical Business Logic (don't break)
- Fare Calculator T1/T2/T3/T4/T7/Nochebuena tariffs are exact official Madrid values. **Do not modify.**
- Grouped airport terminals on login page: T1, T2-T3, T4-T4S.
- WhatsApp hourly broadcast runs 6-23h with random minute 1-30 to avoid patterns.

## Important Files
- `/app/backend/routers/daily_summary.py` — AI summary feature
- `/app/backend/server.py` line 3818-3895 — daily_summary_task scheduler
- `/app/backend/shared.py` line 62 — `daily_summaries_collection`
- `/app/frontend/app/index.tsx` line ~444-455 — summary state, ~11125-11265 — UI card
- `/app/whatsapp-bot/index.js` line 642+ — hourly broadcast with AI injection
- `/app/nginx/nginx.conf` — Let's Encrypt webroot challenge
- `/app/docker-compose.yml` — Certbot auto-renewal config

## Test Reports
- `/app/test_reports/iteration_4.json` — AI summary feature (backend 10/10 ✅, frontend ✅)
- `/app/backend/tests/test_daily_summary.py` — pytest suite for daily summary
