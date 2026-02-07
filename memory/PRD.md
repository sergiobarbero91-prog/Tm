# TaxiMeter Madrid - PRD

## Descripción del Proyecto
Aplicación móvil (React Native Web/Expo) para Madrid que incluye funcionalidades sociales, moderación y administración.

## Stack Tecnológico
- **Frontend:** React Native Web (Expo), TypeScript
- **Backend:** FastAPI (Python)
- **Base de datos:** MongoDB
- **Despliegue:** Emergent Platform con supervisor

## Estado Actual - Febrero 2026

### ✅ Completado
- [x] Autocompletado GPS para ubicaciones en creación de posts
- [x] Refactorización parcial: estilos extraídos a `styles.ts` (~8,000 líneas)
- [x] Corrección de `.gitignore` para permitir archivos `.env` en despliegue
- [x] Preparación para despliegue (configuración de variables de entorno)
- [x] Fix del selector de pestañas con `useMemo` y `nativeID` dinámico

### 🔄 Pendiente de Verificación por Usuario
- [ ] Bug del selector de pestañas - usuario debe confirmar si funciona correctamente

### 📋 Backlog (P1)
- [ ] Completar refactorización de `src/screens/index.tsx` (~16,000 líneas restantes)
  - Extraer tipos/interfaces
  - Extraer constantes
  - Extraer componentes principales (Social, Admin, Moderation panels)
  - Crear estructura de carpetas: `src/components/`, `src/hooks/`, `src/types/`

## Arquitectura de Archivos

```
/app
├── src/
│   ├── screens/
│   │   ├── index.tsx  // Componente principal (~16,000 líneas) - NECESITA REFACTORIZACIÓN
│   │   └── styles.ts  // Estilos extraídos (~8,000 líneas)
│   └── ...
├── frontend/
│   └── .env           // Variables de entorno Expo
├── backend/
│   ├── server.py      // API FastAPI
│   └── .env           // Variables de entorno backend
└── .gitignore         // Corregido para permitir .env
```

## API Endpoints Principales
- `GET /api/health` - Health check
- `POST /api/login` - Autenticación
- `GET /api/search-addresses` - Autocompletado de direcciones

## Notas Técnicas
- El bug del selector de pestañas requirió uso de `useMemo` y `nativeID` dinámico para forzar re-renderizado
- El screenshot tool no funciona bien con el flujo de login de esta app; usar curl para backend y tests manuales para frontend
