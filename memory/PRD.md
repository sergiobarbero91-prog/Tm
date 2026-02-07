# TaxiMeter Madrid - PRD

## Descripción del Proyecto
Aplicación móvil (React Native Web/Expo) para Madrid que incluye funcionalidades sociales, moderación y administración.

## Stack Tecnológico
- **Frontend:** React Native Web (Expo), TypeScript
- **Backend:** FastAPI (Python)
- **Base de datos:** MongoDB
- **Despliegue:** Railway (recomendado)

## Estado Actual - Febrero 2026

### ✅ Completado
- [x] Autocompletado GPS para ubicaciones en creación de posts
- [x] Refactorización parcial: estilos extraídos a `styles.ts` (~8,000 líneas)
- [x] Corrección de `.gitignore` para permitir archivos `.env` en despliegue
- [x] Preparación para despliegue (configuración de variables de entorno)
- [x] Fix del selector de pestañas con `useMemo` y `nativeID` dinámico
- [x] **Configuración para Railway:**
  - Archivos `Procfile` para backend y frontend
  - Archivos `railway.toml` con configuración de despliegue
  - Scripts de build actualizados en `package.json`
  - Guía completa en `RAILWAY_DEPLOY.md`

### 🚀 Próximo Paso
- [ ] Guardar en GitHub (botón "Save to Github")
- [ ] Desplegar en Railway siguiendo `RAILWAY_DEPLOY.md`

### 📋 Backlog (P1)
- [ ] Completar refactorización de `src/screens/index.tsx` (~16,000 líneas restantes)
  - Extraer tipos/interfaces
  - Extraer constantes
  - Extraer componentes principales (Social, Admin, Moderation panels)
  - Crear estructura de carpetas: `src/components/`, `src/hooks/`, `src/types/`

## Arquitectura de Archivos

```
/app
├── RAILWAY_DEPLOY.md    // <-- GUÍA DE DESPLIEGUE EN RAILWAY
├── frontend/
│   ├── Procfile         // Comando de inicio para Railway
│   ├── railway.toml     // Configuración de Railway
│   ├── package.json     // Scripts de build actualizados
│   └── ...
├── backend/
│   ├── Procfile         // Comando de inicio para Railway
│   ├── railway.toml     // Configuración de Railway
│   └── server.py        // API FastAPI
└── ...
```

## Despliegue en Railway

Ver guía completa: `/app/RAILWAY_DEPLOY.md`

**Resumen rápido:**
1. Crear cuenta en [railway.app](https://railway.app)
2. Nuevo proyecto → Deploy from GitHub
3. Añadir MongoDB (base de datos)
4. Configurar Backend (root: `backend`)
5. Configurar Frontend (root: `frontend`)
6. Configurar variables de entorno

**Costo:** ~$5-15/mes (siempre activo, sin spin-down)

## API Endpoints Principales
- `GET /api/health` - Health check
- `POST /api/login` - Autenticación
- `GET /api/search-addresses` - Autocompletado de direcciones
