#!/bin/bash
# Script to manage WhatsApp Bot service
# 
# Usage:
#   ./whatsapp-bot.sh start       - Start the bot (using PM2 if available)
#   ./whatsapp-bot.sh stop        - Stop the bot
#   ./whatsapp-bot.sh restart     - Restart the bot
#   ./whatsapp-bot.sh status      - Check bot status
#   ./whatsapp-bot.sh logs        - View bot logs
#   ./whatsapp-bot.sh install-pm2 - Install and configure PM2

ACTION=$1
BOT_DIR="/home/TM/whatsapp-bot"
LOG_FILE="/var/log/whatsapp-bot.log"
PID_FILE="/var/run/whatsapp-bot.pid"

# Check if PM2 is installed
PM2_AVAILABLE=$(command -v pm2 &> /dev/null && echo "yes" || echo "no")

case "$ACTION" in
    start)
        echo "Iniciando WhatsApp Bot..."
        
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            cd $BOT_DIR
            pm2 start ecosystem.config.js 2>/dev/null || pm2 restart whatsapp-bot
            echo "Bot iniciado con PM2"
        else
            if [ -f "$PID_FILE" ]; then
                PID=$(cat $PID_FILE)
                if ps -p $PID > /dev/null 2>&1; then
                    echo "El bot ya está corriendo (PID: $PID)"
                    exit 0
                fi
            fi
            cd $BOT_DIR
            mkdir -p logs
            nohup node index.js >> logs/combined.log 2>&1 &
            echo $! > $PID_FILE
            echo "Bot iniciado (PID: $!)"
        fi
        ;;
        
    stop)
        echo "Deteniendo WhatsApp Bot..."
        
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            pm2 stop whatsapp-bot 2>/dev/null
            echo "Bot detenido (PM2)"
        else
            if [ -f "$PID_FILE" ]; then
                PID=$(cat $PID_FILE)
                kill $PID 2>/dev/null
                rm -f $PID_FILE
            fi
            pkill -f "node index.js" 2>/dev/null
            echo "Bot detenido"
        fi
        ;;
        
    restart)
        echo "Reiniciando WhatsApp Bot..."
        
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            pm2 restart whatsapp-bot
            echo "Bot reiniciado (PM2)"
        else
            $0 stop
            sleep 2
            $0 start
        fi
        ;;
        
    status)
        echo "=== Estado del WhatsApp Bot ==="
        echo ""
        
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            pm2 status whatsapp-bot
        else
            RUNNING_PID=$(pgrep -f "node index.js")
            if [ -n "$RUNNING_PID" ]; then
                echo "✅ Proceso corriendo (PID: $RUNNING_PID)"
            else
                echo "❌ Proceso no está corriendo"
            fi
        fi
        
        echo ""
        echo "=== Estado de la API ==="
        curl -s http://localhost:3001/status | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)['data']
    print(f'  Autenticado: {\"✅\" if d[\"isAuthenticated\"] else \"❌\"}')
    print(f'  Listo: {\"✅\" if d[\"isReady\"] else \"❌\"}')
    print(f'  Grupo: {d[\"groupName\"] or \"No configurado\"}')
    print(f'  Mensajes enviados: {d[\"messagesCount\"]}')
    if d.get('reconnectAttempts', 0) > 0:
        print(f'  Intentos reconexión: {d[\"reconnectAttempts\"]}')
    if d.get('error'):
        print(f'  ⚠️ Error: {d[\"error\"]}')
except Exception as e:
    print(f'  ❌ No se pudo conectar a la API del bot')
"
        ;;
        
    logs)
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            pm2 logs whatsapp-bot --lines 50
        else
            tail -50 $BOT_DIR/logs/combined.log 2>/dev/null || tail -50 $BOT_DIR/bot.log 2>/dev/null || echo "No hay logs disponibles"
        fi
        ;;
        
    qr)
        echo "Obteniendo código QR..."
        curl -s http://localhost:3001/qr | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('qr'):
        print('QR disponible. Escanea desde: http://TU_IP:3001/qr')
        print('O mira los logs del bot para ver el QR en ASCII')
    else:
        print('Ya autenticado o QR no disponible')
except:
    print('Error al obtener QR')
"
        ;;
        
    groups)
        echo "Grupos disponibles:"
        curl -s http://localhost:3001/groups | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('success'):
        for g in d.get('groups', []):
            print(f\"  - {g['name']} (ID: {g['id']})\")
    else:
        print('  Error obteniendo grupos')
except:
    print('  Error de conexión')
"
        ;;
        
    set-group)
        GROUP_ID=$2
        if [ -z "$GROUP_ID" ]; then
            echo "Uso: $0 set-group <group_id>"
            exit 1
        fi
        curl -s -X POST http://localhost:3001/set-group \
            -H "Content-Type: application/json" \
            -d "{\"groupId\": \"$GROUP_ID\"}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('message', 'Error'))
"
        ;;
        
    send-test)
        echo "Enviando mensaje de prueba..."
        curl -s -X POST http://localhost:3001/send \
            -H "Content-Type: application/json" \
            -d '{"message": "🚖 Test desde As del Volante Bot"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('✅ Enviado!' if d.get('success') else f'❌ Error: {d.get(\"message\")}')
"
        ;;
        
    send-update)
        echo "Enviando actualización horaria..."
        curl -s -X POST http://localhost:3001/send-hourly-update | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('✅ Enviado!' if d.get('success') else f'❌ Error: {d.get(\"message\")}')
"
        ;;
        
    install-pm2)
        echo "=== Instalando PM2 ==="
        npm install -g pm2
        echo ""
        echo "=== Configurando bot con PM2 ==="
        cd $BOT_DIR
        pm2 delete whatsapp-bot 2>/dev/null
        pm2 start ecosystem.config.js
        pm2 save
        echo ""
        echo "=== Configurando auto-inicio ==="
        pm2 startup
        echo ""
        echo "✅ PM2 instalado y configurado"
        echo ""
        echo "El bot se iniciará automáticamente al reiniciar el servidor."
        echo "Ejecuta el comando de 'pm2 startup' que aparece arriba si es necesario."
        ;;
        
    *)
        echo "WhatsApp Bot Manager"
        echo ""
        echo "Uso: $0 <comando>"
        echo ""
        echo "Comandos:"
        echo "  start       - Iniciar el bot"
        echo "  stop        - Detener el bot"
        echo "  restart     - Reiniciar el bot"
        echo "  status      - Ver estado del bot"
        echo "  logs        - Ver logs del bot"
        echo "  qr          - Ver código QR"
        echo "  groups      - Listar grupos disponibles"
        echo "  set-group   - Configurar grupo destino"
        echo "  send-test   - Enviar mensaje de prueba"
        echo "  send-update - Enviar actualización horaria"
        echo "  install-pm2 - Instalar PM2 para auto-reinicio"
        exit 1
        ;;
esac
