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

### ✅ SSL Auto-renewal (Done)
- Fixed `nginx/nginx.conf` to allow `/.well-known/acme-challenge/` via HTTP before HTTPS redirect.
- Updated `docker-compose.yml`: shared `certbot_webroot` volume + Nginx auto-reload every 6h + Certbot uses `--webroot` mode.
- Provided user with manual one-time renewal commands for `asdelvolante.es`.

### ✅ AI Daily Event Summary with Real Web Search (Done — eliminates hallucinations)
- New router `/app/backend/routers/daily_summary.py`:
  - `GET /api/events/daily-summary` (public) — cached, generates on-demand if missing.
  - `POST /api/events/daily-summary/regenerate` (admin) — force regeneration.
- Uses Gemini 2.5-flash + `google_search` tool (Google Search Grounding) via `google-genai` SDK.
- Prompt forces 5+ specific searches: WiZink Center, Movistar Arena, IFEMA, esmadrid.com, madrid.es + EMT cortes.
- Anti-hallucination: validates `grounding_metadata` is present; if Gemini doesn't search → rejected.
- Cached in `daily_summaries` collection (upsert by date).
- Scheduler in `server.py`: regenerates daily at 05:00 Madrid + hourly retries on failure.
- Fallback: if regeneration fails, returns most recent successful summary with warning flag.
- Validated with real call: 15 search queries, 20 grounded sources, real events (Arcángel WiZink 20:30h, WAH Show IFEMA, EMT line modifications).
- 10/10 backend pytest tests passing (in `/app/backend/tests/test_daily_summary.py`).

### ✅ Frontend "Resumen del día" Card (Done)
- Added AI summary card at top of "Eventos" tab in `frontend/app/index.tsx`.
- States: `dailySummary`, `dailySummaryLoading`, `dailySummaryExpanded`.
- Auto-fetched on entering Eventos tab.
- Refresh button (calls public cached GET; full regeneration is admin-only and scheduled).
- Expand/Collapse for long text.
- Error state + fallback warning if generation failed.
- All elements use `testID` prop (RN-Web auto-converts to data-testid in DOM).

### ✅ WhatsApp Bot — AI Summary Injection (Done)
- `/app/whatsapp-bot/index.js` `/send-hourly-update` now fetches `/api/events/daily-summary` and prepends it to the hourly broadcast under section "🤖 RESUMEN DEL DÍA (IA)".

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
