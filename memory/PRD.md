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
- [x] Información de trenes en tiempo real (ADIF)
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
