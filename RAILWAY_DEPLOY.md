# 🚀 Guía de Despliegue en Railway

## Requisitos Previos
- Cuenta en [Railway](https://railway.app) (usa tu GitHub para registrarte)
- Este repositorio guardado en GitHub

---

## Paso 1: Crear Proyecto en Railway

1. Ve a [railway.app](https://railway.app)
2. Click en **"New Project"**
3. Selecciona **"Deploy from GitHub repo"**
4. Autoriza Railway para acceder a tu GitHub si es necesario
5. Selecciona este repositorio

---

## Paso 2: Configurar MongoDB (Base de Datos)

1. En tu proyecto de Railway, click en **"+ New"**
2. Selecciona **"Database"** → **"MongoDB"**
3. Railway creará automáticamente la base de datos
4. Click en el servicio MongoDB → **"Variables"**
5. Copia el valor de `MONGO_URL` (lo necesitarás para el backend)

---

## Paso 3: Configurar el Backend (FastAPI)

1. Click en **"+ New"** → **"GitHub Repo"** → Selecciona este repo
2. Railway detectará el proyecto
3. Click en el servicio creado → **"Settings"**:
   - **Root Directory:** `backend`
4. Ve a **"Variables"** y añade:
   ```
   MONGO_URL=mongodb://mongo:xxxx (pega la URL del paso 2)
   DB_NAME=taximeter_madrid
   SECRET_KEY=tu-clave-secreta-muy-larga-y-segura-123456
   ALLOWED_ORIGINS=*
   ```
5. El backend se desplegará automáticamente
6. Copia la URL del backend (ej: `https://backend-production-xxxx.up.railway.app`)

---

## Paso 4: Configurar el Frontend (Expo Web)

1. Click en **"+ New"** → **"GitHub Repo"** → Selecciona este repo otra vez
2. Click en el servicio creado → **"Settings"**:
   - **Root Directory:** `frontend`
3. Ve a **"Variables"** y añade:
   ```
   EXPO_PUBLIC_BACKEND_URL=https://tu-backend.up.railway.app (URL del paso 3)
   ```
4. El frontend se desplegará automáticamente

---

## Paso 5: Configurar Dominio Personalizado (Opcional)

1. Click en el servicio Frontend → **"Settings"** → **"Domains"**
2. Puedes usar el dominio gratuito de Railway o añadir tu propio dominio

---

## Variables de Entorno Necesarias

### Backend (`/backend`)
| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `MONGO_URL` | URL de conexión a MongoDB | `mongodb://...` |
| `DB_NAME` | Nombre de la base de datos | `taximeter_madrid` |
| `SECRET_KEY` | Clave secreta para JWT | `abc123...` |
| `ALLOWED_ORIGINS` | Orígenes CORS permitidos | `*` |

### Frontend (`/frontend`)
| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `EXPO_PUBLIC_BACKEND_URL` | URL del backend | `https://backend-xxx.railway.app` |

---

## Troubleshooting

### El frontend no carga
- Verifica que `EXPO_PUBLIC_BACKEND_URL` apunta al backend correcto
- Revisa los logs en Railway (click en el servicio → "Logs")

### Error de conexión a MongoDB
- Asegúrate de que `MONGO_URL` tiene el formato correcto
- Verifica que el servicio MongoDB está activo

### Error 500 en el backend
- Revisa los logs del backend
- Verifica todas las variables de entorno

---

## Costo Estimado

- **Hobby Plan:** $5/mes incluido
- **Uso típico:** $5-15/mes dependiendo del tráfico
- Sin spin-down (siempre activo)
