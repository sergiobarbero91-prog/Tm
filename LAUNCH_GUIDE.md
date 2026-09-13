# 🚀 Guía de Lanzamiento - TaxiMadrid App

## 📋 Checklist Pre-Lanzamiento

### 1. Seguridad
- [ ] **Cambiar contraseña de admin** - Actualmente `admin/admin`
- [ ] **Configurar SECRET_KEY segura** - En el archivo `.env` del backend:
  ```env
  SECRET_KEY=tu-clave-super-secreta-de-al-menos-32-caracteres-aleatorios
  ```
  Puedes generar una con: `openssl rand -hex 32`

### 2. Dominio Propio
Para configurar un dominio propio, necesitarás:

1. **Registrar/tener un dominio** (ej: `taxiapp.es`)
2. **Configurar DNS** - Apuntar el dominio a la IP del servidor
3. **Certificado SSL** - Usar Let's Encrypt o similar
4. **Actualizar variables de entorno**:
   ```env
   # Frontend
   EXPO_PUBLIC_BACKEND_URL=https://api.taxiapp.es
   
   # Backend
   ALLOWED_ORIGINS=https://taxiapp.es,https://www.taxiapp.es
   ```

### 3. Backup de MongoDB ✅ CONFIGURADO

**Scripts disponibles en `/app/scripts/`:**

```bash
# Crear backup manual
/app/scripts/backup_mongodb.sh

# Restaurar desde backup
/app/scripts/restore_mongodb.sh backup_20260113_184941.tar.gz
```

**Backups automáticos:**
- Diarios: Se guardan los últimos 7 días
- Semanales (domingos): Se guardan los últimos 4
- Ubicación: `/app/backups/`

**Agregar al crontab para backup diario automático:**
```bash
# Editar crontab
crontab -e

# Añadir esta línea (backup diario a las 3:00 AM)
0 3 * * * /app/scripts/backup_mongodb.sh >> /var/log/backup.log 2>&1
```

### 4. Monitorización de Errores (Sentry) ✅ CONFIGURADO

**Para activar Sentry:**

1. Crear cuenta gratuita en https://sentry.io
2. Crear proyecto Python/FastAPI
3. Copiar el DSN y añadir al `.env` del backend:
   ```env
   SENTRY_DSN=https://xxxx@o123456.ingest.sentry.io/789
   ENVIRONMENT=production
   APP_VERSION=1.0.0
   ```
4. Reiniciar backend: `sudo supervisorctl restart backend`

**Endpoints de monitorización:**
- `GET /api/health` - Health check básico
- `GET /api/health/detailed` - Métricas del sistema (CPU, RAM, disco, MongoDB)
- `GET /api/debug/sentry-test` - Probar que Sentry funciona

**Ejemplo de health detallado:**
```json
{
  "status": "healthy",
  "system": {
    "cpu_percent": 3.8,
    "memory_percent": 53.2,
    "memory_used_gb": 16.66,
    "disk_percent": 15.2
  },
  "services": {
    "mongodb": "healthy",
    "sentry": "enabled"
  }
}
```

---

## 🏗️ Arquitectura para 20,000 Usuarios Simultáneos

### Configuración Actual
- **Backend**: FastAPI con uvicorn (1 worker)
- **Base de datos**: MongoDB
- **WebSockets**: Para radio walkie-talkie en tiempo real

### Recomendaciones para Escalar

#### 1. Backend - Múltiples Workers
```bash
# En producción, usar múltiples workers
uvicorn server:app --workers 4 --host 0.0.0.0 --port 8001
```

#### 2. MongoDB - Optimizaciones
Los índices ya están creados para:
- `street_activities.created_at`
- `taxi_status.created_at`
- `queue_status.created_at`

Para mayor rendimiento:
```javascript
// Conectar con pool de conexiones más grande
MONGO_URL=mongodb://localhost:27017/taxiapp?maxPoolSize=100
```

#### 3. Redis (Recomendado para > 10,000 usuarios)
Para cachear datos y manejar sesiones:
```bash
pip install redis aioredis
```

#### 4. Load Balancer
Para distribuir tráfico entre múltiples instancias:
- Nginx como reverse proxy
- O usar servicios cloud (AWS ALB, GCP Load Balancer)

### Estimación de Recursos

| Usuarios Simultáneos | RAM Recomendada | CPU Cores | MongoDB RAM |
|---------------------|-----------------|-----------|-------------|
| 1,000               | 2 GB            | 2         | 1 GB        |
| 5,000               | 4 GB            | 4         | 2 GB        |
| 10,000              | 8 GB            | 4         | 4 GB        |
| 20,000              | 16 GB           | 8         | 8 GB        |

### WebSockets (Radio)
- Cada conexión WebSocket consume ~50KB de RAM
- 1,000 usuarios en radio = ~50MB RAM adicional
- El servidor actual puede manejar ~5,000 conexiones WebSocket simultáneas

---

## 📊 Monitoreo

### Logs del Sistema
```bash
# Ver logs del backend
tail -f /var/log/supervisor/backend.err.log

# Ver logs de expo
tail -f /var/log/supervisor/expo.err.log
```

### Métricas a Monitorear
1. **Uso de CPU/RAM** del servidor
2. **Conexiones activas** a MongoDB
3. **Latencia de respuesta** de APIs
4. **Errores HTTP** (4xx, 5xx)
5. **Conexiones WebSocket** activas

### Herramientas Recomendadas
- **Sentry** - Para errores en tiempo real
- **Grafana + Prometheus** - Para métricas
- **UptimeRobot** - Para monitorear disponibilidad

---

## 🔧 Comandos Útiles

```bash
# Reiniciar servicios
sudo supervisorctl restart backend
sudo supervisorctl restart expo

# Ver estado
sudo supervisorctl status

# Ver usuarios conectados al radio
# Los logs muestran conexiones/desconexiones

# Backup manual de MongoDB
mongodump --out /app/backups/manual_$(date +%Y%m%d)
```

---

## ⚠️ Problemas Comunes

### 1. "Sesión expirada"
- Ya implementado refresh automático de tokens cada 20 minutos
- Si persiste, verificar que el reloj del servidor esté sincronizado

### 2. "Sin conexión a internet"
- Banner rojo aparece tras 3 intentos fallidos
- Se restaura automáticamente al recuperar conexión

### 3. APIs externas lentas (ADIF/AENA)
- El sistema tiene reintentos automáticos (3 intentos)
- Los datos se cachean cada 30 segundos
- Si fallan, se usa scraping HTML como fallback

### 4. Radio sin audio
- iOS requiere interacción del usuario para desbloquear audio
- Al tocar "Conectar" se desbloquea automáticamente
- Verificar permisos de micrófono en el dispositivo

---

## 📱 Publicación en Stores

### App Store (iOS)
1. Crear cuenta de Apple Developer ($99/año)
2. Usar EAS Build: `eas build --platform ios`
3. Subir a App Store Connect
4. Revisión tarda 1-7 días

### Google Play (Android)
1. Crear cuenta de Google Play ($25 única vez)
2. Usar EAS Build: `eas build --platform android`
3. Subir APK/AAB a Play Console
4. Revisión tarda 1-3 días

---

## 📞 Soporte Post-Lanzamiento

Monitorear durante las primeras 48 horas:
- Tasa de registro de nuevos usuarios
- Errores en logs
- Rendimiento del servidor
- Feedback de usuarios

¡Buena suerte con el lanzamiento! 🎉
