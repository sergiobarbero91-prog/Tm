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

### Twilio SMS (Emisora — DEPRECATED)
- Kept in `/app/backend/.env` (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_VERIFY_SERVICE_SID) but no longer used by the frontend.
- Client verification is now done via a 6-digit code shown on the taxista's screen next to the QR (see below).

## Emisora / Cliente Test Flow (Feb 2026)
- Driver logs in → opens Reservas → "Emisora" section → "QR clientes". The modal shows a QR and a big 6-digit code.
- Client opens `<base>/?cliente_qr=<token>` (or scans the QR), fills phone + nombre + apellido + the 6-digit code the taxista dictates, and gets logged in.
- Endpoint: `POST /api/rides/client/authenticate` with `{phone, first_name, last_name, qr_token, verification_code}`.
- To rotate the driver's code manually: `POST /api/rides/driver/qr/rotate` (auth required).

## Notes
- `admin` account is seeded by the backend on first run (see auth router).
- Default DB: `test_database` (preview) / `taximeter_madrid` (production).
- WhatsApp bot runs externally on port 3001 (only on user's production server).
