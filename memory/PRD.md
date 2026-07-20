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

### 🐛 Bug fix #2 — Eventos IA con festivales multi-día ya terminados (Feb 2026)
- **Síntoma reportado**: Mad Cool 2026 (que terminó el 12-jul) y Auditorio Miguel Ríos de Rivas (programación del fin de semana pasado) seguían apareciendo en el resumen aunque HOY fuera posterior.
- **RCA**: el fix anterior (iter_14) validaba HORA pero no FECHA de finalización de eventos multi-día. Google Search Grounding devuelve "Mad Cool 2026" como destacado durante semanas y el modelo confundía "existe en 2026" con "está ocurriendo hoy".
- **Fix aplicado (3 capas)** en `/app/backend/routers/daily_summary.py`:
  1. **Prompt REGLA #0**: bloque nuevo con encabezado que muestra HOY, AYER, MAÑANA en formato ISO. Checklist obligatorio de 4 pasos por evento (buscar fechas → identificar inicio y fin → verificar HOY ∈ rango → escribir bullet con fecha entre paréntesis). Anti-ejemplos explícitos "Mad Cool ended 10-12 julio" y "Auditorio Rivas fin de semana".
  2. **`_verify_events_sync`** (nueva función): segunda llamada a Gemini con Google Search grounding que revisa cada bullet de GRANDES EVENTOS y TEATROS Y OCIO, elimina los que no cubran HOY. Temperature=0.1. Safe-fallback al texto original si la pasada falla.
  3. **Temperature bajado 0.4 → 0.2** en la generación principal para menos "creatividad" con fechas.
- **Validación en vivo** (testing_agent iter_15, 12/12 PASS, cuota Gemini fresca):
  - Force-refresh en 2026-07-13 12:18 Madrid → resumen SIN Mad Cool, SIN Auditorio Rivas, SIN referencias a fin de semana pasado. Cada bullet lleva su fecha/rango entre paréntesis: "Veranos de la Villa 2026 (7-jul → 29-ago)", "Fescinal (hoy 2026-07-13)", "Chulíssima (hoy 2026-07-13)", etc.
  - Mock-flow: `_generate_summary` llama a `_generate_summary_sync` una vez y luego a `_verify_events_sync` una vez con el texto inicial, y devuelve el texto verificado.
- **Coste**: doble llamada a Gemini por regeneración (+15-25s). Con caché de 4h = 6 dobles-llamadas por día como mucho.
- **Regression suite**: `/app/backend/tests/test_daily_summary_date_verification.py` (12 tests) + `test_daily_summary_freshness.py` (actualizado, 8 tests PASS).

### 🐛 Bug fix #3 — Eventos IA quedando VACÍOS por sobre-conservadurismo (Feb 2026)
- **Síntoma reportado**: tras los fixes de fechas (iter_15+16), el modelo se volvió tan cauto que devolvía "Sin información verificada para hoy." en GRANDES EVENTOS, TEATROS Y OCIO y ALERTAS DE TRÁFICO — el usuario reportó que hoy había celebración del Mundial en Cibeles/Colón/Autocine y no aparecía.
- **RCA**: reglas del prompt demasiado estrictas (obligar hora + fecha exactas) + `_strip_stale_bullets` sin fail-open + verify pass agresivo → sección se quedaba vacía.
- **Fix aplicado (6 capas de seguridad)** en `/app/backend/routers/daily_summary.py`:
  1. **Prompt REGLA #3 suavizada**: "SOLO como ÚLTIMO recurso" escribe "Sin información verificada". Antes de rendirse, incluye 2-3 bullets con "(horario por confirmar)".
  2. **Prompt REGLA #4 nueva "ACONTECIMIENTOS NACIONALES"**: si HOY hay Mundial/Champions/San Silvestre/cabalgata/Orgullo/procesión, MENCIÓNALO SIEMPRE con puntos de encuentro (Cibeles/Neptuno tras victorias, Puerta del Sol, Colón, Autocine Madrid RACE, Madrid Río).
  3. **Regla #6 suavizada**: "DEBERÍA" (antes "DEBE") con "INCLUYE el bullet — no lo descartes por falta de hora".
  4. **`_generate_summary_sync(extra_prompt=None)`**: acepta prompt adicional; temperature 0.2 → 0.3 en el reintento.
  5. **Retry-with-softer-prompt**: si tras la primera generación 2+ secciones de eventos están vacías, se hace un segundo Gemini call con `_retry_prompt_softer(today)` que exige mínimo 2-3 bullets con "(horario por confirmar)" permitido.
  6. **Fail-open en `_strip_stale_bullets`**: si borrar bullets pasados dejaría una sección vacía, se conservan los originales (mejor "algo posiblemente stale" que "vacío") + log warning.
  7. **`_verify_events_sync` fail-open**: si el verify pass elimina >70% de bullets, se revierte al texto original (probable over-pruning).
  8. **Nueva `_strip_hallucinated_instructions`**: elimina bullets con markers como "NO RELLENES esta sección" que el modelo copia por error de [AEROPUERTO] a otras secciones.
- **Validado en vivo** (testing_agent iter_17, 42/42 PASS, ~55s):
  - Force-refresh generó 3 bullets GRANDES EVENTOS + 6 TEATROS Y OCIO + 4 ALERTAS DE TRÁFICO + AEROPUERTO con datos AENA.
  - Cero contaminación de "NO RELLENES" fuera de [AEROPUERTO].
  - Cada bullet incluye fecha/rango entre paréntesis (justifica vigencia).
- **Test suite**: `/app/backend/tests/test_daily_summary_soften_widen.py` (42 tests, 5 unit classes + 2 integration + 1 live).
- **Nota code-review**: el fichero `daily_summary.py` supera los 1180 líneas — pendiente refactor a subpaquete `daily_summary/{prompt,filters,gemini,airport}.py`.

### 🐛 Bug fix #4 — Subida de fotos del taxímetro fallaba en producción (Feb 2026)
- **Síntoma reportado**: "no e sido capaz de subir una fotografia para probarlo en produccion" en la pantalla Gestión → Salario → 'FOTO INICIO DE JORNADA'.
- **RCA**: (a) cámaras móviles generan JPEG de 3-10 MB, nginx en prod suele estar en `client_max_body_size 1M` → 413 silencioso; (b) `oncancel` en `<input type=file>` oculto no es fiable → promesa colgada → botón bloqueado; (c) sin compresión cliente, foto de 8 MB sube íntegra; (d) sin progreso ni mensajes de error → el usuario se rendía.
- **Fix aplicado (7 mejoras)** en `/app/frontend/app/index.tsx` y `/app/backend/routers/journal.py`:
  1. **`_compressImage()`** — compresión JPEG en el navegador antes de subir: canvas 2D, max side 1600 px, quality 0.85, background blanco (evita artefactos negros en HEIC/PNG con alpha). Short-circuit para archivos <900 KB. Fotos reales quedan en ~200-800 KB.
  2. **`ocrPickFile()` reescrita** — attach del `<input>` a `document.body` antes de `.click()` (fix Safari mobile) + resolución garantizada vía `window.focus` fallback (sustituye al `oncancel` no fiable) + limpieza del DOM en finish.
  3. **Axios con `timeout: 90_000`, `maxContentLength: 25MB`, `onUploadProgress`** → barra de progreso verde con % en vivo.
  4. **`_friendlyUploadError()`** — mensajes en español por código (413 → "La imagen es demasiado grande…"; 401 → "Sesión caducada"; 503 → mensaje del servidor; ECONNABORTED → "La subida ha tardado demasiado"; sin response → "Revisa tu conexión").
  5. **Fallback `<input type=file>` visible** debajo del botón principal para escritorio o cuando la cámara falla. `data-testid="ocr-start-file-fallback"` + `"ocr-end-file-fallback"` (RN Web SÍ preserva data-* en inputs nativos).
  6. **Backend `_save_photo`** — cap 12 → **20 MB** con HTTP **413** (no 400) y mensaje "La imagen ocupa X.X MB y el máximo son 20 MB". Extensiones ampliadas: JPG/PNG/WEBP/**HEIC/HEIF** (iPhone).
  7. **Ambas rutas (`ocrStartShift` + `ocrEndShift`) idempotentes**: cada `finally` resetea `ocrBusy` y `ocrUploadProgress` → nunca deja el UI colgado.
- **Validado en vivo** por testing_agent (iter_18, 14/14 PASS + 4 skipped por 503 Gemini): fallback input sube una foto real → backend responde → banner de error amigable "El servicio de IA está temporalmente saturado" cuando toca. Backend rechaza 22 MB con 413 y acepta 15 MB con 200.
- **Nota para producción**: si tu nginx sigue en 1 MB, la compresión cliente ya baja fotos reales a <1 MB así que probablemente ni necesitas tocarlo. Pero para máxima robustez añade en tu nginx.conf:
  ```
  client_max_body_size 25M;
  ```
- **Testabilidad**: TouchableOpacity de RN Web no propaga `data-testid` al DOM (esto es un cabo suelto para tests futuros — pendiente cambiar a `dataSet={{ testid: '…' }}` o migrar a Pressable).

### 🐛 Bug fix #5 — Subida de fotos fallaba con "No se pudo conectar al servidor" (Feb 2026)
- **Síntoma reportado**: tras el fix de compresión (iter_18) el usuario seguía viendo "No se pudo conectar al servidor" al subir foto en producción.
- **RCA**: la config CORS del backend combinaba `allow_credentials=True` + `allow_origins=['*']`. Combinación **prohibida por la spec CORS**: los navegadores la rechazan silenciosamente → preflight XHR completa a nivel red pero el navegador NO expone la respuesta a axios → `e.response === undefined` → `_friendlyUploadError` cae en la rama `!e.response` con el genérico "No se pudo conectar".
- **Fix aplicado (5 mejoras)**:
  1. **`server.py` CORS spec-compliant**: si `ALLOWED_ORIGINS` está sin definir o es `'*'`, se fuerza `allow_credentials=False` (spec-compliant). Cuando se ponen orígenes específicos (ej. `https://asdelvolante.es`), se activan credentials.
  2. **Warning de arranque**: si se está en modo wildcard, el backend loguea `[cors] ALLOWED_ORIGINS is wildcard ('*')... Set ALLOWED_ORIGINS='https://your-domain.com' en backend/.env`.
  3. **`expose_headers=['Content-Type', 'Retry-After']`** → el frontend puede leer el `Retry-After` de las respuestas 503.
  4. **`_friendlyUploadError` diagnóstico**: el mensaje ahora incluye la URL exacta que se intentó (`e?.config?.url`) y el código axios (`ERR_NETWORK`, `ECONNABORTED`, etc.). Ejemplo: `"No se pudo conectar con el servidor (posible bloqueo CORS o backend caído). Detalles técnicos: ERR_NETWORK [https://asdelvolante.es/api/journal/start]"`.
  5. **Botón "🔧 Probar conexión con el servidor"**: bajo el botón principal de foto, hace GET a `/api/journal/active` con 15s timeout y muestra `"✅ Conexión OK — backend responde en XX ms"` o el mismo error verboso si falla. Auto-diagnóstico para usuarios finales sin conocimientos técnicos.
- **Validado en vivo** (testing_agent iter_19, 9/9 backend + Playwright smoke happy+error): wildcard mode no emite credentials, specific mode las emite correctamente, botón diagnóstico devuelve `✅ Conexión OK 46ms` en happy path y `🔴 ERR_NETWORK [url]` en error path.
- **Handoff producción**: en `asdelvolante.es`/`backend/.env` añadir `ALLOWED_ORIGINS=https://asdelvolante.es,https://www.asdelvolante.es` y reiniciar backend. Con eso las cookies y auth headers cross-origin funcionan correctamente.

### 🐛 Bug fix #6 — Subida de foto en producción "imagen demasiado grande" + crash de compresión (Feb 2026)
- **Síntomas encadenados**:
  - Iter_19 arregló CORS → conexión al backend OK.
  - Iter_20 el usuario vio "La imagen es demasiado grande" (413 de nginx con `client_max_body_size 1M` por defecto).
  - Iter_20 fix intentó apretar la compresión, pero introdujo **bug crítico**: `new Image()` colisionaba con el `Image` importado de `react-native` en la línea 21 del `index.tsx`, tirando la pipeline entera de compresión con `TypeError: Image.default is not a constructor`.
- **Fix aplicado**:
  1. **Compresión más agresiva** (`_compressImage` en `index.tsx`): maxSide 1600→**1400**, quality 0.85→**0.75**, skip-threshold 900KB→**300KB**, con **segunda pasada** a 0.75× escala + quality 0.65 si el resultado sigue >800 KB.
  2. **Fix del shadow**: `new Image()` → `new window.Image()` (usa la del DOM, no la de RN).
  3. **Mensaje de error 413 accionable**: "La imagen es demasiado grande. Sube el límite de nginx (client_max_body_size 25M;) y reinicia el contenedor nginx. Si eres el usuario, avisa al admin."
- **Validado por testing_agent iter_21** (100% PASS): fotos 3-4 MB se comprimen a <1 MB en cliente, POST llega al backend, si mock 413 sale el mensaje con la guía de nginx.
- **Instrucciones para producción**:
  1. Save to GitHub → `git pull` → `docker compose up -d --build frontend`
  2. Edita el `nginx.conf` de tu setup añadiendo `client_max_body_size 25M;` dentro del bloque `server { listen 443 ssl; ... }`
  3. `docker compose restart nginx`
  4. En el móvil: cierra caché completa de asdelvolante.es → login → Gestión → sube foto
- **Nota code-review**: `_friendlyUploadError` trataba TypeErrors como errores de red genéricos. Añadir en el futuro `if (e instanceof TypeError) return 'Error interno: ' + e.message` para exponer bugs JS claramente en el próximo P1.

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

### 🛡️ Modo "Revisar y confirmar" + fix 500 en /end (Feb 2026)
- **Bug fix**: el endpoint `POST /api/journal/end` devolvía 500 al procesar
  las lecturas OCR con los nuevos tiempos numéricos (`tiempo_ocupado`/
  `tiempo_on` cambiaron de `Optional[str]` a `Optional[float]` — pero
  `_hhmm_to_minutes` seguía haciendo `":" in t` sobre un float,
  provocando TypeError). Solución: `_hhmm_to_minutes` ahora chequea
  `isinstance(t, str)` primero. Además `_compute_totals` calcula
  `min_on` y `min_ocupado` directamente del diff numérico (segundos → min).
- **Flujo "Revisar y confirmar"**: tras subir la foto (INICIO o FIN) se
  abre automáticamente el modal editable con TODOS los valores extraídos:
    - Título: **"Revisar y confirmar (inicio/fin)"** con check-mark verde
    - 9 campos editables (fecha, hora, servicios, carreras €, dists km,
      tiempos), placeholder "—" para los no detectados
    - Botón principal grande: **"Confirmar y guardar"** (verde) 2×
      ancho del botón "Cancelar" (gris)
    - `ocrSaveManual` incluye ahora los tiempos como numéricos en el
      payload PUT `/api/journal/{id}/manual`
  Así el usuario SIEMPRE valida antes de que la jornada se registre
  definitivamente — cualquier fallo del OCR es corregible al vuelo.
- **Ficheros tocados**:
  - `backend/routers/journal.py` — `_hhmm_to_minutes` tipo-safe,
    `_compute_totals` con `_diff_seconds_to_minutes` para tiempo_*.
  - `frontend/app/index.tsx` — `ocrStartShift` y `ocrEndShift` abren
    automáticamente `setOcrShowEditModal('start'|'end')` tras el upload
    exitoso, poblando `ocrEditDraft` con la reading extraída.
- **Test end-to-end vía API**: `POST /start` → 200, `POST /end` → 200,
  totals correctamente computados.

- **Política de dominio (usuario)**: la sección "P …" del ticket se IGNORA
  para los cálculos. Los campos principales SIEMPRE reflejan la sección
  superior de TOTALES ACUMULADOS del taxímetro. La jornada se computa
  como `end.TOTALES - start.TOTALES` en `_compute_totals`.
- **Double-pass OCR (PSM 4 + PSM 6)**: dos pasadas de Tesseract con page
  segmentation modes distintos sobre la misma imagen preprocesada. PSM 4
  = single column of variable-sized text (mejor en tickets con dos
  columnas etiqueta+valor). PSM 6 = uniform block (mejor con líneas
  densas). Cada una capta campos distintos.
- **Merge inteligente por campo** (`_pick` y `_looks_ocr_corrupt`):
    - Prefiere valores en rango razonable (km < 1M, € < 10M).
    - Rechaza enteros grandes en campos de distancia (el taxímetro imprime
      distancias con coma; un `dist_libre_km=261423` sin coma es OCR
      corrupto, se descarta).
    - Empates: valor con decimales > valor entero > valor del PSM con
      más score total.
- **Consistency check**: si `dist_total_km` se desvía >20 % de
  `ocupado + libre + off`, se recalcula como esa suma. Warning devuelto
  al usuario para transparencia.
- **Etiquetas ampliadas**: añadidos "Num. Servicios" (con punto), "NS
  LICENCIA", "N2 LICENCIA" (variantes OCR-corrupt del "Nº").
- **Resultado sobre foto real**:
  - 8 de 9 campos principales correctos (~90 %)
  - dist_total_km recuperado vía consistency check aunque el OCR falló
  - Único fallo: `tiempo_ocupado` (OCR se comió el prefijo "55" del
    557761 → 39761). Irrecoverable sin edición manual.
  - Latencia end-to-end vía API: **5.0 s**

- **Backend** — Nuevo endpoint `GET /api/journal/{id}/photo/{which}?thumb=1`
  en `routers/journal.py`:
    - Auth-protected (ownership check: sólo el dueño de la jornada o admin).
    - `which` ∈ {"start", "end"}. Devuelve 400 si otro valor.
    - `?thumb=1` genera on-the-fly una miniatura 400×400 JPEG q=75 con PIL
      (~20 KB vs ~1 MB del original). `Cache-Control: private, max-age=3600`
      para que el navegador la cachee 1 hora.
    - Sin thumb devuelve el fichero original con `FileResponse`.
- **Frontend** — Nuevo componente `JournalThumb` en `app/index.tsx`:
    - Fetcha el thumbnail vía `axios responseType: 'blob'` con el JWT en el
      header (no exponemos token en la URL).
    - Convierte el blob a ObjectURL y renderiza un `<img>` de 44×44 px.
    - Cache in-memory con `useRef<Map>` para no re-fetchar en cada render.
    - Estados: cargando (spinner) / error (icono placeholder) / listo.
- **Integración**: en la lista de historial (últimas 6 jornadas), muestra
  las miniaturas de las fotos de INICIO y FIN antes del texto.
- **Fichero backend**: `backend/routers/journal.py` — nuevo endpoint
  antes de `/start`.
- **Fichero frontend**: `frontend/app/index.tsx` — componente `JournalThumb`
  añadido tras `ocrLoadHistory`; fila de historial actualizada para
  mostrar los thumbnails.
- **Test**: `curl` a `/api/journal/{id}/photo/start?thumb=1` → 200,
  `Content-Type: image/jpeg`, tamaño ~20 KB. Sin auth → 401. `which`
  inválido → 400.

- **Nuevo panel colapsable "TOTALES TAXÍMETRO (acumulado)"** debajo de cada
  lectura (start / end) en la pestaña Gestión. Muestra los 12 campos del
  bloque de acumulados históricos (`totales_taximetro`): Licencia,
  Servicios, Carreras €, Suplementos €, Total €, Dist. Total/Ocup/Libre/OFF,
  T. ocupado, T. ON, Borrados. Se pliega/expande con un icono chevron.
  Se muestra en gris (jerarquía visual — datos secundarios para auditoría).
- **Detección de valores imposibles** (OCR Confidence): en la lectura de FIN
  cualquier valor de campos monotónicos (`num_servicios`, `carreras_eur`,
  `dist_*_km`, `tiempo_*`) que sea MENOR que la lectura de inicio se colorea
  en **rojo #F87171** con un `⚠` junto a la etiqueta. Además:
    - Valores negativos → rojo
    - `dist_libre + dist_ocupado > dist_total × 1.05` → rojo (con 5% de
      tolerancia por redondeo del taxímetro)
- **Estado nuevo**: `ocrExpandTotals: Set<string>` (contiene 'start' / 'end'
  para los paneles expandidos).
- **Fichero**: `frontend/app/index.tsx` — refactor de `renderReading`
  (líneas 13417-13560 aprox).

- **Contexto**: El usuario compartió una foto real de su parcial. El ticket tiene
  DOS secciones:
    - **Sección superior — TOTALES ACUMULADOS** (histórico del taxímetro):
      FECHA, Nº LICENCIA, Num. Servicios, Carreras, Suplementos, Total,
      Dist. Total/Ocupado/Libre/OFF, Tiempo Ocupado, Tiempo On, Borrados
    - **Sección inferior — PARCIALES DEL TURNO** (líneas con prefijo "P "):
      P Nº de servs, P Carreras, P Suplementos, P Total, P Dist. *, P Tiempo *
  Además la foto llega **rotada 90°** desde el móvil.
- **Solución**:
  - `_preprocess_for_ocr`: auto-rotación probando las 4 orientaciones sobre
    una MINIATURA 800px (fast path 800ms en vez de 6s) contando keywords
    del ticket. Luego OCR final sobre imagen 2400px + deskew fino.
  - `_label_to_regex`: convierte etiquetas legibles ("Dist. Total") en
    patrones tolerantes (espacio → `\s+`, punto → `[.,]?`) sin las
    complicaciones de `re.escape`.
  - `_parse_ticket_text`: separa líneas por presencia de `\bP\s+(N|Carreras
    |Dist|Tiempo|Total|Suplem)` (más robusto que "línea empieza con P").
    Los CAMPOS PRINCIPALES reflejan la **sección P** (parcial del turno);
    los TOTALES ACUMULADOS se guardan en `totales_taximetro` para
    auditoría.
  - Añadidos `totales_taximetro` y `parcial_turno` al modelo `ParcialReading`.
  - `tiempo_ocupado`/`tiempo_on` cambiados de `Optional[str]` a
    `Optional[float]` (el ticket los imprime como enteros, no como HH:MM).
- **Resultado sobre foto real**:
  - Fecha ✅ `2026-07-18`, Hora ✅ `15:06`
  - `totales_taximetro`: **11/11 campos detectados** (Carreras 49854.10 €,
    Total 50059.00 €, Dist. Total/Ocup/Libre/OFF, Tiempo Ocup/On, Borrados,
    Licencia)
  - `parcial_turno`: Todos a 0 (correcto — foto es de INICIO de jornada)
  - Latencia end-to-end vía API: **4.3s** (Tesseract sobre 2400px)

- **Motivación**: Usuarios recibían `503 IA saturada` cuando la cuota Gemini se
  agotaba o el modelo se sobrecargaba. Además, cada foto costaba dinero.
- **Solución**: OCR 100 % local con **Tesseract 5.3** (paquete `tesseract-ocr`
  + `tesseract-ocr-spa` en el Dockerfile del backend). Sin API externa, sin
  cuota, sin latencia de red, gratis y funciona sin conexión al modelo LLM.
- **Preprocesado** (`_preprocess_for_ocr` en `journal.py`): OpenCV escala
  grises → CLAHE contraste local → median blur → Otsu threshold → deskew
  automático si la foto está torcida <15°.
- **Parseo regex tolerante** (`_parse_ticket_text`): etiquetas alternativas
  para Digitax D5/D8, Semel Turmix, Taxitronic TM7, Ikon TX-80. Formato
  español 1.234,56 correctamente convertido a float.
- **Warnings** para campos no detectados → el frontend muestra "⚠ campo X
  no detectado" y el botón "Corregir" abre el modal de edición manual.
- **Guía de cámara**: modal nuevo con vista previa en vivo (`getUserMedia`
  + recuadro naranja punteado 3:5) para que el conductor encaje el ticket
  antes de disparar. Fallback al file picker nativo si no hay permiso
  de cámara.
- **Tests**: `_ocr_parcial_sync` sobre ticket sintético →
  9/9 campos detectados en 0.4 s. `POST /api/journal/start` end-to-end →
  200 OK con `start_reading` completo, 0.4 s.
- **Ficheros tocados**:
  - `backend/routers/journal.py` — reemplazado el bloque Gemini Vision
    por Tesseract + regex. Eliminada dependencia de `google.genai` para OCR.
  - `backend/Dockerfile` — añadidos paquetes apt `tesseract-ocr`,
    `tesseract-ocr-spa`, `libgl1`, `libglib2.0-0`.
  - `backend/requirements.txt` — añadidos `pytesseract==0.3.13`,
    `opencv-python-headless==5.0.0.93`, `pillow==12.1.1`.
  - `frontend/app/index.tsx` — nuevo modal cámara con guía visual y
    captura vía `getUserMedia` + fallback file picker.

## Critical Business Logic (don't break)
- Fare Calculator T1/T2/T3/T4/T7/Nochebuena tariffs are exact official Madrid values.
- Grouped airport terminals on login page: T1, T2-T3, T4-T4S.
- WhatsApp hourly broadcast runs 6-23h with random minute 1-30.

### 🐛 Bug fix #7 — "IA saturada" al subir foto del taxímetro (Feb 2026)
- **Backend** `/app/backend/routers/journal.py`: `_ocr_parcial_sync` ahora reintenta hasta
  3 veces con backoff exponencial (2s → 4s → 8s) contra el modelo principal
  (`gemini-2.5-flash`) ante 429/RESOURCE_EXHAUSTED/503/overloaded/deadline.
  Si se agotan, cambia al modelo fallback (`gemini-2.5-flash-lite`) con otros 3
  reintentos. Solo si TAMBIÉN se agota el fallback devuelve HTTP 503 al cliente.
- **Frontend** `/app/frontend/app/index.tsx`: `ocrStartShift` y `ocrEndShift` ahora
  hacen un reintento extra automático tras 4s si el backend responde 503, de forma
  que el usuario prácticamente nunca ve el mensaje de saturación.
- **Nginx** `/app/nginx/nginx.conf`: `client_max_body_size 25M;` +
  `client_body_buffer_size 128k;` + `client_body_timeout 120s;` añadidos al
  bloque `http` para desbloquear la subida de fotos en producción.
