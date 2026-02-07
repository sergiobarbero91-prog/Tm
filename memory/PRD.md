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

### Session 2026-02-07 Changes
1. **Bug Fix (PARCIAL)**: Selector de pestañas - Actualizado texto e icono para mostrar "Social" y "Moderación". PENDIENTE VERIFICACIÓN por usuario.
2. **Feature**: Autocompletado de ubicación GPS - Al crear posts, ahora hay un campo de texto con autocompletado que busca direcciones de Madrid usando Photon API (como un GPS real).

## Known Issues
1. **Bug selector pestañas**: Usuario reporta que "administración" aparece en las últimas pestañas. Necesita más información para reproducir.
2. Suite de tests pytest rota
3. Warnings de `shadow*` style props en web
4. Archivo `index.tsx` masivo (23,000+ líneas) necesita refactorización urgente

## Prioritized Backlog

### P0 - Critical
- [ ] Investigar y corregir bug de "administración" en pestañas (necesita más info)
- [ ] Refactorizar `frontend/app/index.tsx` en componentes manejables

### P1 - High
- [ ] Persistir datos de juegos en MongoDB
- [ ] Migrar `expo-av` a `expo-audio`
- [ ] Arreglar suite de tests pytest

### P2 - Medium
- [ ] Corregir warnings de `shadow*` props
- [ ] Optimizaciones de rendimiento

## Architecture Notes
```
/app
├── backend/
│   ├── routers/
│   │   ├── social.py
│   │   └── geocoding.py  # API de búsqueda de direcciones
│   ├── tests/           # Broken
│   └── server.py
└── frontend/
    └── app/
        └── index.tsx    # CRÍTICO: 23,000+ líneas
```

## Credentials
- Admin: `admin` / `admin`
