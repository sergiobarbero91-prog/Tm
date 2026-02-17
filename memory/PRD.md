# TaxiMeter Madrid - PRD

## Descripción del Proyecto
Aplicación móvil (React Native Web/Expo) para taxistas de Madrid que incluye funcionalidades sociales, moderación, gamificación y herramientas de trabajo.

## Stack Tecnológico
- **Frontend:** React Native Web (Expo), TypeScript
- **Backend:** FastAPI (Python)
- **Base de datos:** MongoDB
- **Despliegue:** Clouding.io (España) con Docker
- **Bot WhatsApp:** Node.js + whatsapp-web.js

## Estado Actual - Febrero 2026

### ✅ Completado
- [x] Sistema de gamificación/puntos completo
- [x] Sistema de moderación y reportes
- [x] Funciones sociales (amigos, mensajes, grupos)
- [x] Información de trenes en tiempo real (ADIF) - **CORREGIDO Feb 10, 2026**
- [x] Información de vuelos en tiempo real (AENA)
- [x] Sistema de eventos y alertas
- [x] Radio en tiempo real (WebSocket)
- [x] Sistema de check-in/check-out
- [x] **Bot de WhatsApp** - NUEVO (Febrero 2026)
  - Servicio Node.js con whatsapp-web.js
  - Envío automático cada hora (6:00 - 23:00)
  - Información de trenes, vuelos y eventos
  - Panel de administración en la app
  - Script de gestión (`scripts/whatsapp-bot.sh`)
  - Guía completa (`WHATSAPP_BOT_GUIDE.md`)
- [x] Configuración completa para Clouding.io

### 🔧 Corrección del Scraper de Trenes (Feb 10, 2026)

**Problema resuelto:** El scraper de datos de ADIF estaba fallando debido a bloqueos anti-bot.

**Solución implementada - Sistema de fallback en cascada:**
1. **API de ADIF** → Primera opción (funciona intermitentemente)
2. **HTML Scrape** → Fallback si la API falla
3. **Google Apps Script** → Último recurso como proxy externo

**Archivos modificados:**
- `/app/backend/server.py` - Nueva función `fetch_trains_from_google_script()`
- `/app/backend/.env` - Añadida variable `GOOGLE_SCRIPT_TRAINS_URL`

### 🔧 Integración Renfe Open Data GTFS (Feb 16, 2026)

**Objetivo:** Añadir Renfe Open Data como fuente secundaria de datos de trenes para aumentar la fiabilidad.

**Solución implementada:**
1. **Módulo `renfe_gtfs.py`** - Descarga y parsea datos GTFS estáticos de Renfe
2. **Función `fetch_train_arrivals_combined()`** - Combina ADIF + Renfe GTFS inteligentemente
3. **Carga en background** - Los datos GTFS se cargan en background al iniciar el servidor

**Lógica de fallback:**
- Si ADIF devuelve suficientes trenes (>=5), usa solo ADIF
- Si ADIF falla o devuelve pocos trenes, complementa con Renfe GTFS
- Deduplicación automática por número de tren + hora
- Campo `source` añadido a todos los trenes (ADIF, Renfe GTFS, Google Script)

**Datos GTFS cargados:**
- 622 rutas
- 5914 viajes
- 771 estaciones

**Archivos modificados:**
- `/app/backend/renfe_gtfs.py` - Módulo para Renfe GTFS (existía, ahora integrado)
- `/app/backend/server.py` - Nueva función `fetch_train_arrivals_combined()`, import de módulo GTFS

### 🔥 Feature: Zonas Calientes / Taxi Needed Zones (Feb 17, 2026)

**Objetivo:** Permitir a los taxistas reportar zonas donde se necesitan taxis (calles calientes) para ayudar a otros conductores a encontrar clientes.

**Funcionalidades implementadas:**

**Backend (server.py):**
- `POST /api/taxi-needed-zones` - Reportar una zona caliente con coordenadas
  - Geocodificación inversa para obtener nombre de calle
  - Deduplicación: mismo usuario no puede reportar misma zona en 30 min
  - Zonas expiran automáticamente después de 1 hora
- `GET /api/taxi-needed-zones` - Obtener zonas activas
  - Agregación por ubicación (~100m de tolerancia)
  - Ordenación por distancia si se proporciona ubicación del usuario
  - Lista de reporteros con número de licencia y hora
- `DELETE /api/taxi-needed-zones/{zone_id}` - Eliminar zona (solo owner o admin)

**Frontend (index.tsx):**
- Botón "Reportar Calle Caliente" en tab Calle
  - Icono de llama roja
  - Deshabilitado sin permiso de ubicación
  - Feedback visual durante el reporte
- Sección "Zonas con demanda" mostrando zonas activas
  - Contador de reportes
  - Última hora de reporte
  - Distancia al usuario (si ubicación disponible)
  - Botón de navegación GPS
- Modal "Ver todo" con lista completa de zonas
  - Detalles de cada zona (calle, número)
  - Lista de reporteros (licencia + hora)
  - Botón "Ir con GPS" para navegación

**Archivos modificados:**
- `/app/backend/server.py` - Endpoints POST/GET/DELETE /api/taxi-needed-zones (líneas 2367-2549)
- `/app/frontend/app/index.tsx` - Estados, funciones y UI
- `/app/frontend/app/styles/mainStyles.ts` - Estilos nuevos

**Tests:**
- `/app/backend/tests/test_taxi_needed_zones.py` - 11 tests (100% passing)
- Verificación completa de backend y frontend

**Estado actual de endpoints:**
| Endpoint | Estado | Datos típicos |
|----------|--------|---------------|
| `/api/trains` | ✅ OK | Atocha: 20-75, Chamartín: 20-75 trenes |
| `/api/flights` | ✅ OK | 50-180 vuelos |
| `/api/health` | ✅ OK | healthy |

### 🔧 Mejoras del Bot de WhatsApp (Feb 11, 2026)

**Cambios realizados:**
1. **BACKEND_URL actualizado** - El bot ahora usa `https://asdelvolante.es` en lugar de `localhost:8001`
2. **Endpoint de reinicio añadido** - Nuevo endpoint `POST /restart` para reiniciar el bot sin acceso SSH
3. **Panel de Admin actualizado** - Botón "Reiniciar Bot" añadido en la sección de WhatsApp
4. **Auto-reconexión implementada** - El bot intenta reconectarse automáticamente hasta 5 veces si se desconecta
5. **Soporte PM2** - Configuración para PM2 que auto-reinicia el bot si falla

**Archivos modificados:**
- `/app/whatsapp-bot/index.js` - BACKEND_URL, auto-reconnect, eventos de desconexión
- `/app/whatsapp-bot/ecosystem.config.js` - Configuración PM2 (NUEVO)
- `/app/backend/routers/whatsapp.py` - Endpoint `POST /api/whatsapp/restart`
- `/app/frontend/app/index.tsx` - Función `restartWhatsAppBot()` + botón en UI
- `/app/scripts/whatsapp-bot.sh` - Script mejorado con soporte PM2

### Configuración PM2 (Recomendado)

Para que el bot se reinicie automáticamente si falla, ejecuta en el servidor:

```bash
cd /home/TM/scripts
./whatsapp-bot.sh install-pm2
```

Esto instalará PM2 y configurará:
- Auto-reinicio si el bot falla
- Reinicio si usa más de 500MB de memoria
- Inicio automático al reiniciar el servidor
- Logs organizados en `/home/TM/whatsapp-bot/logs/`

### Monitor Automático del Bot (Backend)

El backend incluye un monitor que:
- Verifica el estado del bot cada 5 minutos
- Si el bot no responde o está desconectado, intenta reiniciarlo
- Máximo 3 intentos de reinicio antes de requerir intervención manual
- Registra todos los eventos en logs

**Endpoints del monitor:**
- `GET /api/whatsapp/monitor/status` - Ver estado del monitor
- `POST /api/whatsapp/monitor/reset` - Resetear contador de errores

**Variables de entorno (opcionales):**
```
WHATSAPP_MONITOR_ENABLED=true
WHATSAPP_MONITOR_INTERVAL=300
WHATSAPP_MAX_RESTART_ATTEMPTS=3
```

### 🚀 Bot de WhatsApp

**Funcionalidades implementadas:**
- Panel visual en Admin → "Bot de WhatsApp"
- Estado del bot (Conectado/Desconectado)
- Obtención de código QR para autenticación
- Listado de grupos disponibles
- Configuración de grupo destino
- Envío de mensaje de prueba
- Envío manual de actualización horaria
- Envío automático cada hora (6:00 - 23:00)

**Archivos creados:**
- `/app/whatsapp-bot/index.js` - Servicio principal
- `/app/whatsapp-bot/package.json` - Dependencias
- `/app/backend/routers/whatsapp.py` - API del backend
- `/app/scripts/whatsapp-bot.sh` - Script de gestión
- `/app/WHATSAPP_BOT_GUIDE.md` - Guía completa

**Endpoints API:**
- `GET /api/whatsapp/status` - Estado del bot
- `GET /api/whatsapp/qr` - Código QR (solo admin)
- `GET /api/whatsapp/groups` - Lista de grupos
- `POST /api/whatsapp/set-group` - Configurar grupo
- `POST /api/whatsapp/send` - Enviar mensaje
- `POST /api/whatsapp/send-hourly-update` - Enviar actualización

### 📋 Backlog (P1)
- [ ] Completar refactorización de `src/screens/index.tsx`

## Arquitectura con Bot de WhatsApp

```
┌─────────────────────────────────────────────────────────┐
│                    CLOUDING.IO                           │
│                   (Barcelona 🇪🇸)                         │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │                    NGINX                          │   │
│  │             (Reverse Proxy + SSL)                 │   │
│  │                  :80 / :443                       │   │
│  └──────────────┬──────────────┬────────────────────┘   │
│                 │              │                         │
│         /api/*  │              │  /*                     │
│                 ▼              ▼                         │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │     BACKEND      │  │    FRONTEND      │            │
│  │    (FastAPI)     │  │   (Expo Web)     │            │
│  │      :8001       │  │      :3000       │            │
│  └────────┬─────────┘  └──────────────────┘            │
│           │                                             │
│           │ API calls                                   │
│           ▼                                             │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │    MONGODB       │  │  WHATSAPP BOT    │            │
│  │     :27017       │  │  (Node.js :3001) │            │
│  └──────────────────┘  └──────────────────┘            │
│                              │                          │
│                              ▼                          │
│                     ┌──────────────────┐               │
│                     │   WhatsApp Web   │               │
│                     │    (Chromium)    │               │
│                     └──────────────────┘               │
└─────────────────────────────────────────────────────────┘
```

## Comandos del Bot de WhatsApp

```bash
# Iniciar bot
/home/TM/scripts/whatsapp-bot.sh start

# Ver estado
/home/TM/scripts/whatsapp-bot.sh status

# Ver código QR
/home/TM/scripts/whatsapp-bot.sh qr

# Listar grupos
/home/TM/scripts/whatsapp-bot.sh groups

# Configurar grupo
/home/TM/scripts/whatsapp-bot.sh set-group "ID_GRUPO@g.us"

# Enviar test
/home/TM/scripts/whatsapp-bot.sh send-test

# Enviar actualización
/home/TM/scripts/whatsapp-bot.sh send-update
```

## Costes Estimados (España)

| Concepto | Coste |
|----------|-------|
| Servidor Clouding.io (2GB RAM, Barcelona) | ~6€/mes |
| Dominio .es | ~8€/año |
| Certificado SSL (Let's Encrypt) | GRATIS |
| Bot WhatsApp | GRATIS |
| **TOTAL** | **~7€/mes** |
