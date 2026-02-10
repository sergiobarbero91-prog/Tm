#!/bin/bash
# Script to manage WhatsApp Bot service

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
                curl -s http://localhost:3001/status | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'Autenticado: {d[\"isAuthenticated\"]}'); print(f'Listo: {d[\"isReady\"]}'); print(f'Grupo: {d[\"groupName\"] or \"No configurado\"}')"
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
