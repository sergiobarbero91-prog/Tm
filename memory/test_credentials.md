# Test Credentials

## Admin Login
- **Endpoint**: `POST /api/auth/login` (JSON body: `{"username": "...", "password": "..."}`)
- **Username**: `admin`
- **Password**: `admin`
- **Role**: admin (full access)
- Returns: `{"access_token": "<JWT>", "token_type": "bearer", "user": {...}}`
- Use header `Authorization: Bearer <JWT>` for protected endpoints.

## Integrations / API Keys

### Gemini API Key (Google AI Studio)
- Stored in `/app/backend/.env` as `GEMINI_API_KEY`
- Used by: `/app/backend/routers/daily_summary.py` for Google Search Grounding (AI daily event summary)
- Source: https://aistudio.google.com/apikey
- Owner: User (asdelvolante.es)

## Notes
- `admin` account is seeded by the backend on first run (see auth router).
- Default DB: `test_database` (preview) / `taximeter_madrid` (production).
- WhatsApp bot runs externally on port 3001 (only on user's production server).
