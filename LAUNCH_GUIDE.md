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

### 3. Backup de MongoDB
Script para backup automático (crear en `/app/backup.sh`):
```bash
#!/bin/bash
BACKUP_DIR="/app/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Crear backup
mongodump --out $BACKUP_DIR/backup_$DATE

# Comprimir
tar -czf $BACKUP_DIR/backup_$DATE.tar.gz -C $BACKUP_DIR backup_$DATE
rm -rf $BACKUP_DIR/backup_$DATE

# Mantener solo últimos 7 días
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Backup completado: backup_$DATE.tar.gz"
```

Agregar al crontab para backup diario:
```bash
0 3 * * * /app/backup.sh >> /var/log/backup.log 2>&1
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
