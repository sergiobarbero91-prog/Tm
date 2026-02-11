#!/bin/bash
# Script to manage WhatsApp Bot service
# 
# Usage:
#   ./whatsapp-bot.sh start    - Start the bot (using PM2 if available)
#   ./whatsapp-bot.sh stop     - Stop the bot
#   ./whatsapp-bot.sh restart  - Restart the bot
#   ./whatsapp-bot.sh status   - Check bot status
#   ./whatsapp-bot.sh logs     - View bot logs

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
            # Use PM2 if available
            cd $BOT_DIR
            pm2 start ecosystem.config.js
            echo "Bot iniciado con PM2"
        else
            # Fallback to nohup
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
                echo "Bot detenido"
            else
                # Try to kill by name
                pkill -f "node index.js" 2>/dev/null
                echo "Bot detenido (pkill)"
            fi
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
        echo "Estado del WhatsApp Bot:"
        echo ""
        
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            pm2 status whatsapp-bot
        else
            if [ -f "$PID_FILE" ]; then
                PID=$(cat $PID_FILE)
                if ps -p $PID > /dev/null 2>&1; then
                    echo "✅ Bot corriendo (PID: $PID)"
                else
                    echo "❌ Bot no está corriendo (PID file stale)"
                    rm -f $PID_FILE
                fi
            else
                # Check if running without PID file
                RUNNING_PID=$(pgrep -f "node index.js")
                if [ -n "$RUNNING_PID" ]; then
                    echo "✅ Bot corriendo (PID: $RUNNING_PID)"
                else
                    echo "❌ Bot no está corriendo"
                fi
            fi
        fi
        
        echo ""
        echo "Verificando API del bot..."
        curl -s http://localhost:3001/status | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)['data']
    print(f'  Autenticado: {\"✅\" if d[\"isAuthenticated\"] else \"❌\"}')
    print(f'  Listo: {\"✅\" if d[\"isReady\"] else \"❌\"}')
    print(f'  Grupo: {d[\"groupName\"] or \"No configurado\"}')
    print(f'  Mensajes enviados: {d[\"messagesCount\"]}')
    if d.get('error'):
        print(f'  Error: {d[\"error\"]}')
except:
    print('  ❌ No se pudo conectar a la API del bot')
"
        ;;
        
    logs)
        if [ "$PM2_AVAILABLE" = "yes" ]; then
            pm2 logs whatsapp-bot --lines 50
        else
            tail -50 $BOT_DIR/logs/combined.log 2>/dev/null || tail -50 $BOT_DIR/bot.log 2>/dev/null
        fi
        ;;
        
    install-pm2)
        echo "Instalando PM2..."
        npm install -g pm2
        echo ""
        echo "Configurando bot con PM2..."
        cd $BOT_DIR
        pm2 start ecosystem.config.js
        pm2 save
        pm2 startup
        echo ""
        echo "✅ PM2 instalado y configurado"
        echo "El bot se iniciará automáticamente al reiniciar el servidor"
        ;;
        
    *)
        echo "Uso: $0 {start|stop|restart|status|logs|install-pm2}"
        echo ""
        echo "Comandos:"
        echo "  start       - Iniciar el bot"
        echo "  stop        - Detener el bot"
        echo "  restart     - Reiniciar el bot"
        echo "  status      - Ver estado del bot"
        echo "  logs        - Ver logs del bot"
        echo "  install-pm2 - Instalar PM2 y configurar auto-inicio"
        exit 1
        ;;
esac
            echo "Bot no está corriendo"
        fi
        ;;
    logs)
        tail -f $LOG_FILE
        ;;
    qr)
        curl -s http://localhost:3001/qr | python3 -c "
import sys, json
try:
    import qrcode
    d = json.load(sys.stdin)
    if d.get('qr'):
        qr = qrcode.QRCode(version=1, box_size=1, border=1)
        qr.add_data(d['qr'])
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        print('\\nEscanea el código QR con WhatsApp')
    else:
        print('Ya autenticado o QR no disponible')
except ImportError:
    print('Instala qrcode: pip install qrcode')
    d = json.load(sys.stdin)
    if d.get('qr'):
        print('QR disponible en: http://localhost:3001/qr')
"
        ;;
    groups)
        echo "Grupos disponibles:"
        curl -s http://localhost:3001/groups | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('success'):
    for g in d.get('groups', []):
        print(f\"  - {g['name']} (ID: {g['id']})\")"
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
print(d.get('message', 'Error'))"
        ;;
    send-test)
        echo "Enviando mensaje de prueba..."
        curl -s -X POST http://localhost:3001/send \
            -H "Content-Type: application/json" \
            -d '{"message": "🚖 Test desde As del Volante Bot"}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Enviado!' if d.get('success') else f'Error: {d.get(\"message\")}')"
        ;;
    send-update)
        echo "Enviando actualización horaria..."
        curl -s -X POST http://localhost:3001/send-hourly-update | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Enviado!' if d.get('success') else f'Error: {d.get(\"message\")}')"
        ;;
    *)
        echo "Uso: $0 {start|stop|restart|status|logs|qr|groups|set-group|send-test|send-update}"
        exit 1
        ;;
esac
