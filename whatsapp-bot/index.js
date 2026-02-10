/**
 * WhatsApp Bot for TaxiMeter Madrid
 * Sends hourly updates about trains, flights, and events to a taxi driver group
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const axios = require('axios');

// Configuration
const PORT = process.env.WHATSAPP_BOT_PORT || 3001;
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8001';
const GROUP_ID = process.env.WHATSAPP_GROUP_ID || null;

// Bot state
let botState = {
    isReady: false,
    isAuthenticated: false,
    qrCode: null,
    lastMessageSent: null,
    groupId: GROUP_ID,
    groupName: null,
    error: null,
    messagesCount: 0
};

// Initialize WhatsApp client with local authentication (saves session)
const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: '/app/whatsapp-bot/.wwebjs_auth'
    }),
    puppeteer: {
        headless: true,
        executablePath: '/root/.cache/puppeteer/chrome/linux_arm-145.0.7632.46/chrome-linux64/chrome',
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--disable-gpu',
            '--single-process'
        ]
    }
});

// Express server for API
const app = express();
app.use(express.json());

// ==================== WhatsApp Events ====================

client.on('qr', (qr) => {
    console.log('📱 Escanea el código QR con tu WhatsApp:');
    qrcode.generate(qr, { small: true });
    botState.qrCode = qr;
    botState.isAuthenticated = false;
});

client.on('authenticated', () => {
    console.log('✅ Autenticado correctamente');
    botState.isAuthenticated = true;
    botState.qrCode = null;
});

client.on('ready', async () => {
    console.log('🚀 WhatsApp Bot listo!');
    botState.isReady = true;
    botState.error = null;
    
    // List available groups
    const chats = await client.getChats();
    const groups = chats.filter(chat => chat.isGroup);
    console.log('\n📋 Grupos disponibles:');
    groups.forEach(group => {
        console.log(`   - ${group.name} (ID: ${group.id._serialized})`);
    });
    
    // If group ID is set, verify it exists
    if (botState.groupId) {
        const group = groups.find(g => g.id._serialized === botState.groupId);
        if (group) {
            botState.groupName = group.name;
            console.log(`\n✅ Grupo configurado: ${group.name}`);
        } else {
            console.log(`\n⚠️ Grupo con ID ${botState.groupId} no encontrado`);
        }
    }
});

client.on('disconnected', (reason) => {
    console.log('❌ Desconectado:', reason);
    botState.isReady = false;
    botState.isAuthenticated = false;
    botState.error = reason;
});

client.on('auth_failure', (message) => {
    console.error('❌ Error de autenticación:', message);
    botState.error = message;
    botState.isAuthenticated = false;
});

// ==================== API Endpoints ====================

// Get bot status
app.get('/status', (req, res) => {
    res.json({
        success: true,
        data: {
            isReady: botState.isReady,
            isAuthenticated: botState.isAuthenticated,
            hasQR: botState.qrCode !== null,
            groupId: botState.groupId,
            groupName: botState.groupName,
            lastMessageSent: botState.lastMessageSent,
            messagesCount: botState.messagesCount,
            error: botState.error
        }
    });
});

// Get QR code for authentication
app.get('/qr', (req, res) => {
    if (botState.isAuthenticated) {
        return res.json({ success: true, message: 'Ya autenticado', qr: null });
    }
    if (botState.qrCode) {
        return res.json({ success: true, qr: botState.qrCode });
    }
    res.json({ success: false, message: 'QR no disponible todavía' });
});

// List available groups
app.get('/groups', async (req, res) => {
    if (!botState.isReady) {
        return res.status(503).json({ success: false, message: 'Bot no está listo' });
    }
    
    try {
        const chats = await client.getChats();
        const groups = chats.filter(chat => chat.isGroup).map(group => ({
            id: group.id._serialized,
            name: group.name,
            participantsCount: group.participants?.length || 0
        }));
        
        res.json({ success: true, groups });
    } catch (error) {
        res.status(500).json({ success: false, message: error.message });
    }
});

// Set target group
app.post('/set-group', async (req, res) => {
    const { groupId } = req.body;
    
    if (!groupId) {
        return res.status(400).json({ success: false, message: 'groupId es requerido' });
    }
    
    if (!botState.isReady) {
        return res.status(503).json({ success: false, message: 'Bot no está listo' });
    }
    
    try {
        const chats = await client.getChats();
        const group = chats.find(chat => chat.id._serialized === groupId && chat.isGroup);
        
        if (!group) {
            return res.status(404).json({ success: false, message: 'Grupo no encontrado' });
        }
        
        botState.groupId = groupId;
        botState.groupName = group.name;
        
        res.json({ 
            success: true, 
            message: `Grupo configurado: ${group.name}`,
            groupId: groupId,
            groupName: group.name
        });
    } catch (error) {
        res.status(500).json({ success: false, message: error.message });
    }
});

// Send message to configured group
app.post('/send', async (req, res) => {
    const { message, groupId } = req.body;
    const targetGroup = groupId || botState.groupId;
    
    if (!message) {
        return res.status(400).json({ success: false, message: 'message es requerido' });
    }
    
    if (!targetGroup) {
        return res.status(400).json({ success: false, message: 'No hay grupo configurado' });
    }
    
    if (!botState.isReady) {
        return res.status(503).json({ success: false, message: 'Bot no está listo' });
    }
    
    try {
        await client.sendMessage(targetGroup, message);
        botState.lastMessageSent = new Date().toISOString();
        botState.messagesCount++;
        
        res.json({ 
            success: true, 
            message: 'Mensaje enviado',
            sentAt: botState.lastMessageSent
        });
    } catch (error) {
        res.status(500).json({ success: false, message: error.message });
    }
});

// Send hourly update (called by scheduler)
app.post('/send-hourly-update', async (req, res) => {
    if (!botState.isReady || !botState.groupId) {
        return res.status(503).json({ 
            success: false, 
            message: botState.isReady ? 'No hay grupo configurado' : 'Bot no está listo' 
        });
    }
    
    try {
        // Fetch data from backend
        const [trainsRes, flightsRes, eventsRes] = await Promise.all([
            axios.get(`${BACKEND_URL}/api/arrivals`).catch(e => ({ data: null })),
            axios.get(`${BACKEND_URL}/api/flights`).catch(e => ({ data: null })),
            axios.get(`${BACKEND_URL}/api/events/active`).catch(e => ({ data: null }))
        ]);
        
        // Build message
        const now = new Date();
        const timeStr = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
        const dateStr = now.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
        
        let message = `🚖 *RESUMEN HORARIO - ${timeStr}*\n`;
        message += `📅 ${dateStr}\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        // Trains section
        if (trainsRes.data) {
            const trains = trainsRes.data;
            message += `🚂 *TRENES PRÓXIMOS*\n`;
            
            if (trains.atocha?.arrivals?.length > 0) {
                message += `\n📍 *Atocha* (próx. 30min: ${trains.atocha.total_next_30min || 0})\n`;
                trains.atocha.arrivals.slice(0, 3).forEach(t => {
                    message += `   • ${t.time} - ${t.train_type} desde ${t.origin}\n`;
                });
            }
            
            if (trains.chamartin?.arrivals?.length > 0) {
                message += `\n📍 *Chamartín* (próx. 30min: ${trains.chamartin.total_next_30min || 0})\n`;
                trains.chamartin.arrivals.slice(0, 3).forEach(t => {
                    message += `   • ${t.time} - ${t.train_type} desde ${t.origin}\n`;
                });
            }
            message += `\n`;
        }
        
        // Flights section
        if (flightsRes.data?.terminals) {
            message += `✈️ *VUELOS PRÓXIMOS*\n`;
            const terminals = flightsRes.data.terminals;
            
            Object.entries(terminals).forEach(([terminal, data]) => {
                if (data.arrivals?.length > 0) {
                    const count30 = data.total_next_30min || data.arrivals.filter(f => {
                        const mins = parseInt(f.minutes_until || '999');
                        return mins <= 30;
                    }).length;
                    message += `\n📍 *${terminal}* (próx. 30min: ${count30})\n`;
                    data.arrivals.slice(0, 2).forEach(f => {
                        message += `   • ${f.scheduled_time || f.time} - ${f.flight_number} desde ${f.origin}\n`;
                    });
                }
            });
            message += `\n`;
        }
        
        // Events section
        if (eventsRes.data?.events?.length > 0) {
            message += `📌 *EVENTOS ACTIVOS*\n`;
            eventsRes.data.events.slice(0, 3).forEach(event => {
                const emoji = event.event_type === 'concert' ? '🎵' : 
                              event.event_type === 'football' ? '⚽' : 
                              event.event_type === 'convention' ? '🎪' : '📌';
                message += `${emoji} ${event.title}`;
                if (event.location) message += ` - ${event.location}`;
                message += `\n`;
            });
            message += `\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `_Actualización automática de As del Volante_`;
        
        // Send message
        await client.sendMessage(botState.groupId, message);
        botState.lastMessageSent = new Date().toISOString();
        botState.messagesCount++;
        
        res.json({ 
            success: true, 
            message: 'Actualización horaria enviada',
            sentAt: botState.lastMessageSent
        });
        
    } catch (error) {
        console.error('Error enviando actualización:', error);
        res.status(500).json({ success: false, message: error.message });
    }
});

// Logout and clear session
app.post('/logout', async (req, res) => {
    try {
        await client.logout();
        botState = {
            isReady: false,
            isAuthenticated: false,
            qrCode: null,
            lastMessageSent: null,
            groupId: null,
            groupName: null,
            error: null,
            messagesCount: botState.messagesCount
        };
        res.json({ success: true, message: 'Sesión cerrada' });
    } catch (error) {
        res.status(500).json({ success: false, message: error.message });
    }
});

// Health check
app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ==================== Start Services ====================

// Start Express server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`🌐 API del bot disponible en http://localhost:${PORT}`);
    console.log('\nEndpoints:');
    console.log('  GET  /status          - Estado del bot');
    console.log('  GET  /qr              - Código QR para autenticar');
    console.log('  GET  /groups          - Lista de grupos');
    console.log('  POST /set-group       - Configurar grupo destino');
    console.log('  POST /send            - Enviar mensaje');
    console.log('  POST /send-hourly-update - Enviar actualización horaria');
    console.log('  POST /logout          - Cerrar sesión');
});

// Initialize WhatsApp client
console.log('🔄 Iniciando cliente de WhatsApp...');
client.initialize();
