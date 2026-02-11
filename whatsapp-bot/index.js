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
const BACKEND_URL = process.env.BACKEND_URL || 'https://asdelvolante.es';
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
    messagesCount: 0,
    reconnectAttempts: 0
};

// Max reconnection attempts before giving up
const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_DELAY_MS = 10000; // 10 seconds

// Auth data path - use environment variable or default
const AUTH_DATA_PATH = process.env.AUTH_DATA_PATH || './.wwebjs_auth';

// Initialize WhatsApp client with local authentication (saves session)
let client = new Client({
    authStrategy: new LocalAuth({
        dataPath: AUTH_DATA_PATH
    }),
    puppeteer: {
        headless: true,
        executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
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

// Function to handle reconnection
async function handleReconnect(reason) {
    console.log(`⚠️ Desconectado: ${reason}`);
    botState.isReady = false;
    botState.error = reason;
    
    if (botState.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        botState.reconnectAttempts++;
        console.log(`🔄 Intentando reconexión ${botState.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS} en ${RECONNECT_DELAY_MS/1000}s...`);
        
        setTimeout(async () => {
            try {
                console.log('🔄 Reinicializando cliente...');
                await client.initialize();
            } catch (error) {
                console.error('❌ Error al reinicializar:', error.message);
                handleReconnect('Error de reinicialización');
            }
        }, RECONNECT_DELAY_MS);
    } else {
        console.error('❌ Máximo de intentos de reconexión alcanzado. El bot necesita reinicio manual.');
        botState.error = 'Máximo de intentos de reconexión alcanzado';
    }
}

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

// ==================== Message Handler for Commands ====================

client.on('message', async (message) => {
    try {
        // Only respond to messages from the configured group
        if (!botState.groupId || message.from !== botState.groupId) return;
        
        const text = message.body.toLowerCase().trim();
        
        // Command list
        const commands = {
            '!trenes': fetchTrainsInfo,
            '!estaciones': fetchTrainsInfo,
            '!vuelos': fetchFlightsInfo,
            '!terminales': fetchFlightsInfo,
            '!eventos': fetchEventsInfo,
            '!todo': fetchAllInfo,
            '!resumen': fetchAllInfo,
            '!ayuda': showHelp,
            '!help': showHelp,
            // Estaciones individuales
            '!atocha': () => fetchStationInfo('atocha'),
            '!chamartin': () => fetchStationInfo('chamartin'),
            '!chamartín': () => fetchStationInfo('chamartin'),
            // Terminales individuales
            '!t1': () => fetchTerminalInfo('T1'),
            '!t2': () => fetchTerminalInfo('T2'),
            '!t3': () => fetchTerminalInfo('T3'),
            '!t4': () => fetchTerminalInfo('T4'),
            '!t4s': () => fetchTerminalInfo('T4S')
        };
        
        const handler = commands[text];
        if (handler) {
            console.log(`📥 Comando recibido: ${text}`);
            const response = await handler();
            await client.sendMessage(botState.groupId, response);
            botState.lastMessageSent = new Date().toISOString();
            botState.messagesCount++;
            console.log(`📤 Respuesta enviada`);
        }
    } catch (error) {
        console.error('Error handling message:', error);
    }
});

// ==================== Command Handlers ====================

async function fetchTrainsInfo() {
    try {
        const response = await axios.get(`${BACKEND_URL}/api/trains`);
        const trains = response.data;
        
        let message = `🚂 *TRENES - LLEGADAS*\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        // Atocha
        if (trains.atocha?.arrivals?.length > 0) {
            const total30 = trains.atocha.arrivals.filter(t => {
                const mins = parseInt(t.minutes_until || '999');
                return mins <= 30;
            }).length;
            message += `📍 *ATOCHA* (próx. 30min: ${total30})\n\n`;
            trains.atocha.arrivals.slice(0, 8).forEach(t => {
                const trainType = t.train_type || t.type || 'Tren';
                const origin = t.origin || 'Origen';
                const time = t.time || t.arrival_time || '';
                message += `   ${time} - *${trainType}*\n`;
                message += `   └ desde ${origin}\n\n`;
            });
        } else {
            message += `📍 *ATOCHA*\n   Sin datos disponibles\n\n`;
        }
        
        // Chamartín
        if (trains.chamartin?.arrivals?.length > 0) {
            const total30 = trains.chamartin.arrivals.filter(t => {
                const mins = parseInt(t.minutes_until || '999');
                return mins <= 30;
            }).length;
            message += `📍 *CHAMARTÍN* (próx. 30min: ${total30})\n\n`;
            trains.chamartin.arrivals.slice(0, 8).forEach(t => {
                const trainType = t.train_type || t.type || 'Tren';
                const origin = t.origin || 'Origen';
                const time = t.time || t.arrival_time || '';
                message += `   ${time} - *${trainType}*\n`;
                message += `   └ desde ${origin}\n\n`;
            });
        } else {
            message += `📍 *CHAMARTÍN*\n   Sin datos disponibles\n\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 www.asdelvolante.es`;
        
        return message;
    } catch (error) {
        console.error('Error fetching trains:', error);
        return `❌ Error al obtener datos de trenes`;
    }
}

// Función para obtener info de una estación específica
async function fetchStationInfo(station) {
    try {
        const response = await axios.get(`${BACKEND_URL}/api/trains`);
        const trains = response.data;
        const stationData = trains[station];
        
        const stationNames = {
            'atocha': 'ATOCHA',
            'chamartin': 'CHAMARTÍN'
        };
        
        let message = `🚂 *TRENES - ${stationNames[station] || station.toUpperCase()}*\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        if (stationData?.arrivals?.length > 0) {
            const total30 = stationData.arrivals.filter(t => {
                const mins = parseInt(t.minutes_until || '999');
                return mins <= 30;
            }).length;
            
            message += `📍 Próximos 30 min: *${total30} trenes*\n\n`;
            
            stationData.arrivals.slice(0, 12).forEach((t, i) => {
                const trainType = t.train_type || t.type || 'Tren';
                const origin = t.origin || 'Origen';
                const time = t.time || t.arrival_time || '';
                const minsUntil = t.minutes_until ? ` (${t.minutes_until} min)` : '';
                
                message += `*${i + 1}.* ${time}${minsUntil}\n`;
                message += `   *${trainType}* desde ${origin}\n\n`;
            });
        } else {
            message += `   Sin datos disponibles en este momento\n\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 www.asdelvolante.es`;
        
        return message;
    } catch (error) {
        console.error(`Error fetching ${station}:`, error);
        return `❌ Error al obtener datos de ${station}`;
    }
}

// Función para obtener info de una terminal específica
async function fetchTerminalInfo(terminal) {
    try {
        const response = await axios.get(`${BACKEND_URL}/api/flights`);
        const data = response.data;
        const termData = data.terminals?.[terminal];
        
        let message = `✈️ *VUELOS - TERMINAL ${terminal}*\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        if (termData?.arrivals?.length > 0) {
            const count30 = termData.arrivals.filter(f => {
                const mins = parseInt(f.minutes_until || '999');
                return mins <= 30;
            }).length;
            
            message += `📍 Próximos 30 min: *${count30} vuelos*\n\n`;
            
            termData.arrivals.slice(0, 12).forEach((f, i) => {
                const time = f.scheduled_time || f.time || '';
                const flight = f.flight_number || f.flight || '';
                const origin = f.origin || '';
                const minsUntil = f.minutes_until ? ` (${f.minutes_until} min)` : '';
                
                message += `*${i + 1}.* ${time}${minsUntil}\n`;
                message += `   *${flight}* desde ${origin}\n\n`;
            });
        } else {
            message += `   Sin vuelos programados en este momento\n\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 www.asdelvolante.es`;
        
        return message;
    } catch (error) {
        console.error(`Error fetching terminal ${terminal}:`, error);
        return `❌ Error al obtener datos de ${terminal}`;
    }
}

async function fetchFlightsInfo() {
    try {
        const response = await axios.get(`${BACKEND_URL}/api/flights`);
        const data = response.data;
        
        let message = `✈️ *VUELOS - LLEGADAS*\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        if (data.terminals) {
            const terminalOrder = ['T1', 'T2', 'T3', 'T4', 'T4S'];
            
            for (const terminal of terminalOrder) {
                const termData = data.terminals[terminal];
                if (termData?.arrivals?.length > 0) {
                    const count30 = termData.arrivals.filter(f => {
                        const mins = parseInt(f.minutes_until || '999');
                        return mins <= 30;
                    }).length;
                    
                    message += `📍 *${terminal}* (próx. 30min: ${count30})\n\n`;
                    termData.arrivals.slice(0, 5).forEach(f => {
                        const time = f.scheduled_time || f.time || '';
                        const flight = f.flight_number || f.flight || '';
                        const origin = f.origin || '';
                        message += `   ${time} - *${flight}*\n`;
                        message += `   └ desde ${origin}\n\n`;
                    });
                }
            }
        } else {
            message += `   Sin datos de vuelos disponibles\n\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 www.asdelvolante.es`;
        
        return message;
    } catch (error) {
        console.error('Error fetching flights:', error);
        return `❌ Error al obtener datos de vuelos`;
    }
}

async function fetchEventsInfo() {
    try {
        const response = await axios.get(`${BACKEND_URL}/api/events/active`);
        const data = response.data;
        
        let message = `📌 *EVENTOS ACTIVOS*\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        if (data.events?.length > 0) {
            data.events.forEach(event => {
                const emoji = event.event_type === 'concert' ? '🎵' : 
                              event.event_type === 'football' ? '⚽' : 
                              event.event_type === 'basketball' ? '🏀' :
                              event.event_type === 'convention' ? '🎪' : 
                              event.event_type === 'theater' ? '🎭' : '📌';
                
                message += `${emoji} *${event.title || event.name || 'Evento'}*\n`;
                if (event.location) message += `   📍 ${event.location}\n`;
                if (event.event_time) message += `   🕐 ${event.event_time}\n`;
                message += `\n`;
            });
        } else {
            message += `   No hay eventos activos en este momento\n\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 www.asdelvolante.es`;
        
        return message;
    } catch (error) {
        console.error('Error fetching events:', error);
        return `❌ Error al obtener datos de eventos`;
    }
}

async function fetchAllInfo() {
    try {
        const [trainsRes, flightsRes, eventsRes] = await Promise.all([
            axios.get(`${BACKEND_URL}/api/trains`).catch(e => ({ data: null })),
            axios.get(`${BACKEND_URL}/api/flights`).catch(e => ({ data: null })),
            axios.get(`${BACKEND_URL}/api/events/active`).catch(e => ({ data: null }))
        ]);
        
        const now = new Date();
        const timeStr = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' });
        
        let message = `🚖 *RESUMEN COMPLETO - ${timeStr}*\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        // Trains summary
        message += `🚂 *TRENES*\n`;
        if (trainsRes.data) {
            const atocha = trainsRes.data.atocha?.arrivals?.slice(0, 3) || [];
            const chamartin = trainsRes.data.chamartin?.arrivals?.slice(0, 3) || [];
            
            if (atocha.length > 0) {
                message += `📍 Atocha:\n`;
                atocha.forEach(t => {
                    message += `   • ${t.time || ''} - ${t.train_type || 'Tren'} (${t.origin || ''})\n`;
                });
            }
            if (chamartin.length > 0) {
                message += `📍 Chamartín:\n`;
                chamartin.forEach(t => {
                    message += `   • ${t.time || ''} - ${t.train_type || 'Tren'} (${t.origin || ''})\n`;
                });
            }
        } else {
            message += `   Sin datos\n`;
        }
        message += `\n`;
        
        // Flights summary
        message += `✈️ *VUELOS*\n`;
        if (flightsRes.data?.terminals) {
            ['T1', 'T4', 'T4S'].forEach(t => {
                const termData = flightsRes.data.terminals[t];
                if (termData?.arrivals?.length > 0) {
                    const count = termData.arrivals.filter(f => parseInt(f.minutes_until || '999') <= 30).length;
                    message += `   ${t}: ${count} en próx. 30min\n`;
                }
            });
        } else {
            message += `   Sin datos\n`;
        }
        message += `\n`;
        
        // Events summary
        message += `📌 *EVENTOS*\n`;
        if (eventsRes.data?.events?.length > 0) {
            eventsRes.data.events.slice(0, 3).forEach(e => {
                message += `   • ${e.title || e.name || 'Evento'}`;
                if (e.event_time) message += ` (${e.event_time})`;
                message += `\n`;
            });
        } else {
            message += `   Sin eventos activos\n`;
        }
        
        message += `\n━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 www.asdelvolante.es`;
        
        return message;
    } catch (error) {
        console.error('Error fetching all info:', error);
        return `❌ Error al obtener datos`;
    }
}

function showHelp() {
    let message = `🤖 *COMANDOS DISPONIBLES*\n`;
    message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
    
    message += `📋 *RESUMEN*\n`;
    message += `*!todo* o *!resumen* - Ver todo\n\n`;
    
    message += `🚂 *TRENES*\n`;
    message += `*!trenes* - Ver todas las estaciones\n`;
    message += `*!atocha* - Solo Atocha\n`;
    message += `*!chamartin* - Solo Chamartín\n\n`;
    
    message += `✈️ *VUELOS*\n`;
    message += `*!vuelos* - Ver todas las terminales\n`;
    message += `*!t1* - Solo Terminal 1\n`;
    message += `*!t2* - Solo Terminal 2\n`;
    message += `*!t4* - Solo Terminal 4\n`;
    message += `*!t4s* - Solo Terminal 4S\n\n`;
    
    message += `📌 *OTROS*\n`;
    message += `*!eventos* - Ver eventos activos\n`;
    message += `*!ayuda* - Ver esta ayuda\n\n`;
    
    message += `━━━━━━━━━━━━━━━━━━━━━\n`;
    message += `📱 www.asdelvolante.es`;
    
    return Promise.resolve(message);
}

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
            axios.get(`${BACKEND_URL}/api/trains`).catch(e => ({ data: null })),
            axios.get(`${BACKEND_URL}/api/flights`).catch(e => ({ data: null })),
            axios.get(`${BACKEND_URL}/api/events/active`).catch(e => ({ data: null }))
        ]);
        
        // Build message
        const now = new Date();
        const timeStr = now.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' });
        const dateStr = now.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Madrid' });
        
        let message = `🚖 *RESUMEN HORARIO - ${timeStr}*\n`;
        message += `📅 ${dateStr}\n`;
        message += `━━━━━━━━━━━━━━━━━━━━━\n\n`;
        
        // Trains section
        let hasTrains = false;
        if (trainsRes.data) {
            const trains = trainsRes.data;
            
            // Check Atocha
            if (trains.atocha?.arrivals?.length > 0) {
                if (!hasTrains) {
                    message += `🚂 *TRENES PRÓXIMOS*\n`;
                    hasTrains = true;
                }
                const total30 = trains.atocha.total_next_30min || trains.atocha.arrivals.filter(t => {
                    const mins = parseInt(t.minutes_until || '999');
                    return mins <= 30;
                }).length;
                message += `\n📍 *Atocha* (próx. 30min: ${total30})\n`;
                trains.atocha.arrivals.slice(0, 4).forEach(t => {
                    const trainType = t.train_type || t.type || 'Tren';
                    const origin = t.origin || 'Origen';
                    const time = t.time || t.arrival_time || '';
                    message += `   • ${time} - ${trainType} desde ${origin}\n`;
                });
            }
            
            // Check Chamartín
            if (trains.chamartin?.arrivals?.length > 0) {
                if (!hasTrains) {
                    message += `🚂 *TRENES PRÓXIMOS*\n`;
                    hasTrains = true;
                }
                const total30 = trains.chamartin.total_next_30min || trains.chamartin.arrivals.filter(t => {
                    const mins = parseInt(t.minutes_until || '999');
                    return mins <= 30;
                }).length;
                message += `\n📍 *Chamartín* (próx. 30min: ${total30})\n`;
                trains.chamartin.arrivals.slice(0, 4).forEach(t => {
                    const trainType = t.train_type || t.type || 'Tren';
                    const origin = t.origin || 'Origen';
                    const time = t.time || t.arrival_time || '';
                    message += `   • ${time} - ${trainType} desde ${origin}\n`;
                });
            }
            
            if (hasTrains) message += `\n`;
        }
        
        if (!hasTrains) {
            message += `🚂 *TRENES*\n`;
            message += `   Sin datos de trenes disponibles\n\n`;
        }
        
        // Flights section
        let hasFlights = false;
        if (flightsRes.data?.terminals) {
            const terminals = flightsRes.data.terminals;
            
            // Check each terminal
            Object.entries(terminals).forEach(([terminal, data]) => {
                if (data.arrivals?.length > 0) {
                    if (!hasFlights) {
                        message += `✈️ *VUELOS PRÓXIMOS*\n`;
                        hasFlights = true;
                    }
                    const count30 = data.total_next_30min || data.arrivals.filter(f => {
                        const mins = parseInt(f.minutes_until || '999');
                        return mins <= 30;
                    }).length;
                    message += `\n📍 *${terminal}* (próx. 30min: ${count30})\n`;
                    data.arrivals.slice(0, 3).forEach(f => {
                        const time = f.scheduled_time || f.time || '';
                        const flight = f.flight_number || f.flight || '';
                        const origin = f.origin || '';
                        message += `   • ${time} - ${flight} desde ${origin}\n`;
                    });
                }
            });
            
            if (hasFlights) message += `\n`;
        }
        
        if (!hasFlights) {
            message += `✈️ *VUELOS*\n`;
            message += `   Sin datos de vuelos disponibles\n\n`;
        }
        
        // Events section
        if (eventsRes.data?.events?.length > 0) {
            message += `📌 *EVENTOS ACTIVOS*\n`;
            eventsRes.data.events.slice(0, 5).forEach(event => {
                const emoji = event.event_type === 'concert' ? '🎵' : 
                              event.event_type === 'football' ? '⚽' : 
                              event.event_type === 'basketball' ? '🏀' :
                              event.event_type === 'convention' ? '🎪' : 
                              event.event_type === 'theater' ? '🎭' : '📌';
                message += `${emoji} ${event.title || event.name}`;
                if (event.location || event.venue) message += ` - ${event.location || event.venue}`;
                if (event.start_time) message += ` (${event.start_time})`;
                message += `\n`;
            });
            message += `\n`;
        } else {
            message += `📌 *EVENTOS*\n`;
            message += `   Sin eventos activos\n\n`;
        }
        
        message += `━━━━━━━━━━━━━━━━━━━━━\n`;
        message += `📱 *Más info en:* www.asdelvolante.es\n`;
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

// Restart the WhatsApp client (reconnect without losing session)
app.post('/restart', async (req, res) => {
    try {
        console.log('🔄 Reiniciando cliente de WhatsApp...');
        
        // Store current config
        const currentGroupId = botState.groupId;
        const currentGroupName = botState.groupName;
        const currentMessagesCount = botState.messagesCount;
        
        // Reset state
        botState = {
            isReady: false,
            isAuthenticated: false,
            qrCode: null,
            lastMessageSent: botState.lastMessageSent,
            groupId: currentGroupId,
            groupName: currentGroupName,
            error: null,
            messagesCount: currentMessagesCount
        };
        
        // Destroy and reinitialize client
        try {
            await client.destroy();
        } catch (destroyError) {
            console.log('⚠️ Error al destruir cliente (ignorado):', destroyError.message);
        }
        
        // Wait a moment before reinitializing
        setTimeout(() => {
            console.log('🔄 Reinicializando cliente...');
            client.initialize();
        }, 2000);
        
        res.json({ 
            success: true, 
            message: 'Bot reiniciándose. Espera unos segundos y verifica el estado.',
            note: 'El bot mantendrá la sesión de WhatsApp si está guardada.'
        });
        
    } catch (error) {
        console.error('Error reiniciando bot:', error);
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
    console.log('  POST /restart         - Reiniciar el bot');
    console.log('  POST /logout          - Cerrar sesión');
});

// Initialize WhatsApp client
console.log('🔄 Iniciando cliente de WhatsApp...');
client.initialize();
