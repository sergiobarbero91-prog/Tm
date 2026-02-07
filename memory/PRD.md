# TaxiDash Madrid - Product Requirements Document

## Original Problem Statement
Aplicación full-stack para taxistas de Madrid que incluye:
- Dashboard de datos de trenes/vuelos/calle
- Suite social completa (feed, DMs, perfiles, grupos)
- Sistema de moderación y administración
- Alertas y emergencias
- Juegos para taxistas

## User Personas
- Taxistas de Madrid (usuarios principales)
- Moderadores (gestión de reportes)
- Administradores (gestión completa)

## Core Requirements
1. Dashboard con datos en tiempo real de estaciones y aeropuertos
2. Sistema social con posts, mensajes, amigos y grupos
3. Panel de moderación y administración
4. Sistema de alertas y emergencias (SOS)
5. Juegos multijugador

## Tech Stack
- **Frontend**: React Native for Web (Expo)
- **Backend**: FastAPI + MongoDB
- **APIs externas**: ADIF (trenes), AENA (vuelos), OSRM (routing), Photon (geocoding)

## Current Status

### Completed Features
- Dashboard principal con datos de trenes/vuelos/calle
- Sistema de autenticación JWT
- Feed social con posts, likes, comentarios
- Sistema de mensajes directos y grupos
- Panel de moderación y administración
- Sistema de alertas y emergencias
- Juegos (Batalla Naval, etc.)
- Subida de imágenes en posts
- Posts guardados
- Opciones de post (editar, eliminar, reportar)
- Autocompletado de ubicación tipo GPS al crear posts

### Session 2026-02-07 - Refactorización
**COMPLETADO:**
1. **Refactorización de estilos**: Extraídos ~8,100 líneas de estilos a `/app/frontend/app/styles/mainStyles.ts`
2. **Reducción del archivo principal**: `index.tsx` reducido de 24,100 a ~16,000 líneas
3. **Bug selector de pestañas**: Implementado `useMemo` y `nativeID` para forzar re-render
4. **Autocompletado de ubicaciones**: Campo de texto con búsqueda usando Photon API

## Architecture (Post-Refactoring)
```
/app
├── backend/
│   ├── routers/
│   │   ├── social.py
│   │   └── geocoding.py
│   └── server.py
└── frontend/
    └── app/
        ├── index.tsx        # 16,000 líneas (reducido de 24,100)
        └── styles/
            └── mainStyles.ts  # 8,100 líneas de estilos
```

## Known Issues
1. Bug del selector de pestañas en Safari móvil (parcialmente corregido)
2. Suite de tests pytest rota (P2)
3. Warnings de `shadow*` style props en web

## Future Improvements
- Continuar extrayendo componentes de `index.tsx`
- Migrar `expo-av` a `expo-audio`
- Persistir datos de juegos en MongoDB

## Credentials
- Admin: `admin` / `admin`
