# TaxiMeter Madrid - PRD

## Descripción del Proyecto
Aplicación móvil (React Native Web/Expo) para Madrid que incluye funcionalidades sociales, moderación y administración.

## Stack Tecnológico
- **Frontend:** React Native Web (Expo), TypeScript
- **Backend:** FastAPI (Python)
- **Base de datos:** MongoDB
- **Despliegue:** Clouding.io (España) con Docker

## Estado Actual - Febrero 2026

### ✅ Completado
- [x] Autocompletado GPS para ubicaciones en creación de posts
- [x] Refactorización parcial: estilos extraídos a `styles.ts` (~8,000 líneas)
- [x] Corrección de `.gitignore` para permitir archivos `.env` en despliegue
- [x] Preparación para despliegue (configuración de variables de entorno)
- [x] Fix del selector de pestañas con `useMemo` y `nativeID` dinámico
- [x] **Configuración completa para Clouding.io:**
  - `docker-compose.yml` - Orquestación de servicios
  - `backend/Dockerfile` - Imagen Docker del backend
  - `frontend/Dockerfile` - Imagen Docker del frontend
  - `nginx/nginx.conf` - Reverse proxy con SSL
  - `scripts/install-clouding.sh` - Script de instalación automática
  - `CLOUDING_DEPLOY.md` - Guía completa en español

### 🚀 Próximo Paso
1. Guardar en GitHub (botón "Save to Github")
2. Crear servidor en [clouding.io](https://clouding.io)
3. Seguir la guía `CLOUDING_DEPLOY.md`

### 📋 Backlog (P1)
- [ ] Completar refactorización de `src/screens/index.tsx` (~16,000 líneas restantes)

## Arquitectura de Despliegue (Clouding.io)

```
┌─────────────────────────────────────────────────────┐
│                   CLOUDING.IO                        │
│                  (Barcelona 🇪🇸)                      │
│                                                      │
│  ┌─────────────────────────────────────────────┐   │
│  │                   NGINX                      │   │
│  │            (Reverse Proxy + SSL)             │   │
│  │                 :80 / :443                   │   │
│  └─────────────┬───────────────┬───────────────┘   │
│                │               │                    │
│        /api/*  │               │  /*                │
│                ▼               ▼                    │
│  ┌─────────────────┐   ┌─────────────────┐        │
│  │    BACKEND      │   │    FRONTEND     │        │
│  │   (FastAPI)     │   │  (Expo Web)     │        │
│  │     :8001       │   │     :3000       │        │
│  └────────┬────────┘   └─────────────────┘        │
│           │                                        │
│           ▼                                        │
│  ┌─────────────────┐                              │
│  │    MONGODB      │                              │
│  │     :27017      │                              │
│  └─────────────────┘                              │
└─────────────────────────────────────────────────────┘
```

## Archivos de Despliegue

```
/app
├── CLOUDING_DEPLOY.md      # Guía completa en español
├── docker-compose.yml      # Orquestación Docker
├── .env.example            # Variables de ejemplo
├── nginx/
│   └── nginx.conf          # Configuración Nginx
├── scripts/
│   └── install-clouding.sh # Instalación automática
├── backend/
│   └── Dockerfile          # Imagen backend
└── frontend/
    └── Dockerfile          # Imagen frontend
```

## Costes Estimados (España)

| Concepto | Coste |
|----------|-------|
| Servidor Clouding.io (2GB RAM, Barcelona) | ~6€/mes |
| Dominio .es | ~8€/año |
| Certificado SSL (Let's Encrypt) | GRATIS |
| **TOTAL** | **~7€/mes** |

## Ventajas de Clouding.io

- ✅ Servidores en Barcelona (baja latencia)
- ✅ 100% cumplimiento RGPD
- ✅ Pago en euros (tarjeta española)
- ✅ Soporte 24/7 en español
- ✅ Facturación española con IVA
