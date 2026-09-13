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

### Twilio SMS (Emisora — OTP for clients)
- Stored in `/app/backend/.env` as `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SERVICE_SID`
- Currently EMPTY → backend runs in **DEV OTP MODE**: any client can log in with the fixed OTP `123456`.
- To enable real SMS: create a Twilio account, create a Verify service, fill the three vars and restart backend.
- Source: https://console.twilio.com/ (Account SID/Auth Token on dashboard, Verify service under Explore → Verify → Services)

## Emisora / Cliente Test Flow
- To force the CLIENT experience without going through the role picker, open: `<base>/?cliente_qr=<QR_TOKEN>` or clear `localStorage['appRole']` and reload.
- Any phone works in DEV mode; the fixed OTP is `123456`.

## Notes
- `admin` account is seeded by the backend on first run (see auth router).
- Default DB: `test_database` (preview) / `taximeter_madrid` (production).
- WhatsApp bot runs externally on port 3001 (only on user's production server).
