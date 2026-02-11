/**
 * PM2 Configuration for WhatsApp Bot
 * 
 * Commands:
 *   pm2 start ecosystem.config.js    - Start the bot
 *   pm2 restart whatsapp-bot         - Restart the bot
 *   pm2 stop whatsapp-bot            - Stop the bot
 *   pm2 logs whatsapp-bot            - View logs
 *   pm2 monit                        - Monitor all processes
 */

module.exports = {
  apps: [{
    name: 'whatsapp-bot',
    script: 'index.js',
    cwd: '/home/TM/whatsapp-bot',
    
    // Auto-restart configuration
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',  // Restart if memory exceeds 500MB
    restart_delay: 5000,         // Wait 5 seconds before restart
    max_restarts: 10,            // Max 10 restarts in a row
    min_uptime: '10s',           // Consider started after 10 seconds
    
    // Environment variables
    env: {
      NODE_ENV: 'production',
      BACKEND_URL: 'https://asdelvolante.es',
      WHATSAPP_BOT_PORT: 3001
    },
    
    // Logging
    error_file: '/home/TM/whatsapp-bot/logs/error.log',
    out_file: '/home/TM/whatsapp-bot/logs/out.log',
    log_file: '/home/TM/whatsapp-bot/logs/combined.log',
    time: true,  // Add timestamps to logs
    
    // Graceful shutdown
    kill_timeout: 10000,  // 10 seconds to gracefully shutdown
    
    // Cron restart (optional - restart every day at 5 AM to prevent memory leaks)
    // cron_restart: '0 5 * * *'
  }]
};
