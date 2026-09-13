#!/bin/bash
# ============================================
# INSTALADOR DEL BOT DE WHATSAPP
# Para As del Volante - TaxiMeter Madrid
# ============================================

echo "🚀 Instalando Bot de WhatsApp para As del Volante..."

# 1. Instalar Chromium
echo "📦 Instalando Chromium..."
apt-get update && apt-get install -y chromium

# 2. Crear directorios
echo "📁 Creando directorios..."
mkdir -p /home/TM/whatsapp-bot
mkdir -p /home/TM/scripts

# 3. Crear package.json
echo "📄 Creando package.json..."
cat > /home/TM/whatsapp-bot/package.json << 'PACKAGE_EOF'
{
  "name": "whatsapp-bot",
  "version": "1.0.0",
  "description": "WhatsApp Bot for As del Volante",
  "main": "index.js",
  "scripts": {
    "start": "node index.js"
  },
  "dependencies": {
    "whatsapp-web.js": "^1.26.0",
    "qrcode-terminal": "^0.12.0",
    "express": "^4.18.2",
    "axios": "^1.6.0"
  }
}
PACKAGE_EOF

# 4. Crear script de gestión
echo "📄 Creando script de gestión..."
cat > /home/TM/scripts/whatsapp-bot.sh << 'SCRIPT_EOF'
#!/bin/bash
ACTION=$1
BOT_DIR="/home/TM/whatsapp-bot"
LOG_FILE="/var/log/whatsapp-bot.log"
PID_FILE="/var/run/whatsapp-bot.pid"

case "$ACTION" in
    start)
        echo "Iniciando WhatsApp Bot..."
        if [ -f "$PID_FILE" ]; then
            PID=$(cat $PID_FILE)
            if ps -p $PID > /dev/null 2>&1; then
                echo "El bot ya está corriendo (PID: $PID)"
                exit 0
            fi
        fi
        cd $BOT_DIR
        export BACKEND_URL="http://localhost:8001"
        nohup node index.js >> $LOG_FILE 2>&1 &
        echo $! > $PID_FILE
        echo "Bot iniciado (PID: $!)"
        ;;
    stop)
        echo "Deteniendo WhatsApp Bot..."
        if [ -f "$PID_FILE" ]; then
            PID=$(cat $PID_FILE)
            kill $PID 2>/dev/null
            rm -f $PID_FILE
            echo "Bot detenido"
        else
            echo "El bot no está corriendo"
        fi
        pkill -f "node.*index.js" 2>/dev/null
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat $PID_FILE)
            if ps -p $PID > /dev/null 2>&1; then
                echo "Bot corriendo (PID: $PID)"
                curl -s http://localhost:3001/status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'Autenticado: {d[\"isAuthenticated\"]}'); print(f'Listo: {d[\"isReady\"]}'); print(f'Grupo: {d[\"groupName\"] or \"No configurado\"}')" 2>/dev/null || echo "API no disponible"
            else
                echo "Bot no está corriendo (PID file stale)"
                rm -f $PID_FILE
            fi
        else
            echo "Bot no está corriendo"
        fi
        ;;
    logs)
        tail -f $LOG_FILE
        ;;
    groups)
        echo "Grupos disponibles:"
        curl -s http://localhost:3001/groups 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); [print(f'  {g[\"name\"]}: {g[\"id\"]}') for g in d.get('groups',[])]" 2>/dev/null || echo "Error: Bot no disponible"
        ;;
    set-group)
        GROUP_ID=$2
        if [ -z "$GROUP_ID" ]; then
            echo "Uso: $0 set-group <group_id>"
            exit 1
        fi
        curl -s -X POST http://localhost:3001/set-group -H "Content-Type: application/json" -d "{\"groupId\": \"$GROUP_ID\"}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message', 'Error'))"
        ;;
    send-test)
        echo "Enviando mensaje de prueba..."
        curl -s -X POST http://localhost:3001/send -H "Content-Type: application/json" -d '{"message": "🚖 Test desde As del Volante Bot"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('Enviado!' if d.get('success') else f'Error: {d.get(\"message\")}')"
        ;;
    send-update)
        echo "Enviando actualización horaria..."
        curl -s -X POST http://localhost:3001/send-hourly-update | python3 -c "import sys,json; d=json.load(sys.stdin); print('Enviado!' if d.get('success') else f'Error: {d.get(\"message\")}')"
        ;;
    *)
        echo "Uso: $0 {start|stop|restart|status|logs|groups|set-group|send-test|send-update}"
        exit 1
        ;;
esac
SCRIPT_EOF

chmod +x /home/TM/scripts/whatsapp-bot.sh

# 5. Instalar dependencias
echo "📦 Instalando dependencias de Node.js..."
cd /home/TM/whatsapp-bot && npm install

echo ""
echo "✅ Instalación completada!"
echo ""
echo "📋 PRÓXIMOS PASOS:"
echo "1. Descarga el archivo index.js del bot"
echo "2. Inicia el bot: /home/TM/scripts/whatsapp-bot.sh start"
echo "3. Mira los logs para ver el QR: /home/TM/scripts/whatsapp-bot.sh logs"
echo "4. Escanea el QR con WhatsApp"
echo "5. Configura el grupo: /home/TM/scripts/whatsapp-bot.sh groups"
echo "6. Selecciona el grupo: /home/TM/scripts/whatsapp-bot.sh set-group <ID>"
echo ""
