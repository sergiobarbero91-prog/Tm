# Guía de Configuración del Bot de WhatsApp

## 📋 Descripción

El bot de WhatsApp envía automáticamente actualizaciones cada hora (entre 6:00 AM y 11:00 PM) al grupo de taxistas con información sobre:
- 🚂 Llegadas de trenes a Atocha y Chamartín
- ✈️ Llegadas de vuelos al aeropuerto
- 📌 Eventos activos en la ciudad

## 🚀 Instalación en el Servidor

### 1. Instalar Chromium (requerido para WhatsApp Web)

```bash
apt-get update && apt-get install -y chromium
```

### 2. Instalar dependencias del bot

```bash
cd /home/TM/whatsapp-bot
npm install
```

### 3. Dar permisos al script de gestión

```bash
chmod +x /home/TM/scripts/whatsapp-bot.sh
```

## 📱 Configuración Inicial

### Paso 1: Iniciar el bot

```bash
/home/TM/scripts/whatsapp-bot.sh start
```

### Paso 2: Escanear el código QR

Para ver el código QR en la terminal:

```bash
# Opción 1: Instalar qrcode y ver en terminal
pip install qrcode
/home/TM/scripts/whatsapp-bot.sh qr
```

O accede directamente a: `http://localhost:3001/qr`

Abre WhatsApp en tu teléfono:
1. Ve a **Configuración** → **Dispositivos vinculados**
2. Toca **Vincular un dispositivo**
3. Escanea el código QR

### Paso 3: Verificar autenticación

```bash
/home/TM/scripts/whatsapp-bot.sh status
```

Deberías ver:
```
Bot corriendo (PID: XXXX)
Autenticado: True
Listo: True
Grupo: No configurado
```

### Paso 4: Configurar el grupo destino

Ver grupos disponibles:
```bash
/home/TM/scripts/whatsapp-bot.sh groups
```

Configurar el grupo:
```bash
/home/TM/scripts/whatsapp-bot.sh set-group "ID_DEL_GRUPO@g.us"
```

Ejemplo:
```bash
/home/TM/scripts/whatsapp-bot.sh set-group "120363XXXXXXXXX@g.us"
```

### Paso 5: Probar el envío

```bash
# Mensaje de prueba simple
/home/TM/scripts/whatsapp-bot.sh send-test

# Actualización completa (trenes, vuelos, eventos)
/home/TM/scripts/whatsapp-bot.sh send-update
```

## 🔧 Comandos de Gestión

| Comando | Descripción |
|---------|-------------|
| `start` | Iniciar el bot |
| `stop` | Detener el bot |
| `restart` | Reiniciar el bot |
| `status` | Ver estado del bot |
| `logs` | Ver logs en tiempo real |
| `qr` | Mostrar código QR |
| `groups` | Listar grupos disponibles |
| `set-group <id>` | Configurar grupo destino |
| `send-test` | Enviar mensaje de prueba |
| `send-update` | Enviar actualización horaria |

## ⏰ Programación Automática

El bot está configurado para enviar actualizaciones automáticamente cada hora entre las 6:00 y las 23:00 (hora de Madrid). Esta tarea se ejecuta desde el backend de la aplicación.

Si el bot no está activo o no hay grupo configurado, las actualizaciones no se enviarán.

## 📝 Ejemplo de Mensaje

```
🚖 *RESUMEN HORARIO - 14:00*
📅 lunes, 10 de febrero

━━━━━━━━━━━━━━━━━━━━━

🚂 *TRENES PRÓXIMOS*

📍 *Atocha* (próx. 30min: 5)
   • 14:05 - AVE desde Barcelona Sants
   • 14:12 - ALVIA desde Sevilla
   • 14:20 - IRYO desde Valencia

📍 *Chamartín* (próx. 30min: 3)
   • 14:08 - AVE desde Valladolid
   • 14:15 - OUIGO desde Barcelona

✈️ *VUELOS PRÓXIMOS*

📍 *T4* (próx. 30min: 8)
   • 14:10 - IB3423 desde Londres
   • 14:25 - IB3156 desde París

📌 *EVENTOS ACTIVOS*
⚽ Real Madrid vs Barcelona - Santiago Bernabéu

━━━━━━━━━━━━━━━━━━━━━
_Actualización automática de As del Volante_
```

## 🔍 Solución de Problemas

### El bot no se conecta
1. Verifica que Chromium está instalado: `which chromium`
2. Reinicia el bot: `/home/TM/scripts/whatsapp-bot.sh restart`
3. Vuelve a escanear el QR

### No se envían mensajes
1. Verifica el estado: `/home/TM/scripts/whatsapp-bot.sh status`
2. Verifica que hay un grupo configurado
3. Prueba manualmente: `/home/TM/scripts/whatsapp-bot.sh send-test`

### Desconexión frecuente
WhatsApp puede desconectar dispositivos inactivos. El bot mantiene la sesión activa, pero si se desconecta:
1. Escanea el QR de nuevo
2. Verifica que no hay otro dispositivo usando la misma cuenta

## 🛡️ Seguridad

- El bot usa autenticación local guardada en `/home/TM/whatsapp-bot/.wwebjs_auth`
- No compartas estos archivos
- Para cambiar de cuenta, borra la carpeta `.wwebjs_auth` y vuelve a escanear el QR

## 📊 API REST

El bot expone una API en `http://localhost:3001`:

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/status` | GET | Estado del bot |
| `/qr` | GET | Código QR |
| `/groups` | GET | Lista de grupos |
| `/set-group` | POST | Configurar grupo |
| `/send` | POST | Enviar mensaje |
| `/send-hourly-update` | POST | Enviar actualización |
| `/logout` | POST | Cerrar sesión |
