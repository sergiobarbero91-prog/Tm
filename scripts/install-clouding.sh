#!/bin/bash

#############################################
# Script de instalación para Clouding.io
# TaxiMeter Madrid - Despliegue automático
#############################################

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  TaxiMeter Madrid - Instalación${NC}"
echo -e "${GREEN}========================================${NC}"

# Verificar que se ejecuta como root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Ejecuta este script como root (sudo)${NC}"
    exit 1
fi

# Pedir dominio
echo -e "${YELLOW}¿Cuál es tu dominio? (ej: taximeter.es)${NC}"
read -p "Dominio: " DOMAIN

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Error: Debes introducir un dominio${NC}"
    exit 1
fi

echo -e "${GREEN}Configurando para: ${DOMAIN}${NC}"

# 1. Actualizar sistema
echo -e "${YELLOW}[1/7] Actualizando sistema...${NC}"
apt-get update && apt-get upgrade -y

# 2. Instalar Docker
echo -e "${YELLOW}[2/7] Instalando Docker...${NC}"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    systemctl enable docker
    systemctl start docker
else
    echo "Docker ya está instalado"
fi

# 3. Instalar Docker Compose
echo -e "${YELLOW}[3/7] Instalando Docker Compose...${NC}"
if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
else
    echo "Docker Compose ya está instalado"
fi

# 4. Instalar Git
echo -e "${YELLOW}[4/7] Instalando Git...${NC}"
apt-get install -y git

# 5. Clonar repositorio
echo -e "${YELLOW}[5/7] Clonando repositorio...${NC}"
echo -e "${YELLOW}¿URL de tu repositorio GitHub?${NC}"
read -p "URL (ej: https://github.com/usuario/repo.git): " REPO_URL

if [ -z "$REPO_URL" ]; then
    echo -e "${RED}Error: Debes introducir la URL del repositorio${NC}"
    exit 1
fi

cd /opt
if [ -d "taximeter" ]; then
    echo "Directorio existente, actualizando..."
    cd taximeter
    git pull
else
    git clone "$REPO_URL" taximeter
    cd taximeter
fi

# 6. Configurar variables de entorno
echo -e "${YELLOW}[6/7] Configurando variables de entorno...${NC}"

# Generar SECRET_KEY
SECRET_KEY=$(openssl rand -hex 32)

# Crear archivo .env
cat > .env << EOF
DOMAIN_URL=https://${DOMAIN}
SECRET_KEY=${SECRET_KEY}
EOF

# Actualizar nginx.conf con el dominio
sed -i "s/TU_DOMINIO.com/${DOMAIN}/g" nginx/nginx.conf

echo -e "${GREEN}Variables configuradas${NC}"

# 7. Obtener certificado SSL
echo -e "${YELLOW}[7/7] Configurando SSL con Let's Encrypt...${NC}"

# Primero, iniciar sin SSL para obtener el certificado
# Crear configuración temporal de nginx sin SSL
cat > nginx/nginx-temp.conf << 'EOF'
events {
    worker_connections 1024;
}
http {
    server {
        listen 80;
        server_name _;
        
        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }
        
        location / {
            return 200 'OK';
            add_header Content-Type text/plain;
        }
    }
}
EOF

# Crear directorio para certbot
mkdir -p /var/www/certbot

# Iniciar nginx temporal
docker run -d --name nginx-temp \
    -p 80:80 \
    -v $(pwd)/nginx/nginx-temp.conf:/etc/nginx/nginx.conf:ro \
    -v /var/www/certbot:/var/www/certbot \
    nginx:alpine

sleep 5

# Obtener certificado
docker run --rm \
    -v /etc/letsencrypt:/etc/letsencrypt \
    -v /var/www/certbot:/var/www/certbot \
    certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email admin@${DOMAIN} \
    --agree-tos \
    --no-eff-email \
    -d ${DOMAIN} \
    -d www.${DOMAIN}

# Parar nginx temporal
docker stop nginx-temp
docker rm nginx-temp
rm nginx/nginx-temp.conf

# Copiar certificados
mkdir -p nginx/ssl

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  ¡Instalación completada!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Para iniciar la aplicación, ejecuta:"
echo -e "${YELLOW}  cd /opt/taximeter${NC}"
echo -e "${YELLOW}  docker-compose up -d${NC}"
echo ""
echo -e "Tu aplicación estará disponible en:"
echo -e "${GREEN}  https://${DOMAIN}${NC}"
echo ""
echo -e "Comandos útiles:"
echo -e "  Ver logs:     ${YELLOW}docker-compose logs -f${NC}"
echo -e "  Reiniciar:    ${YELLOW}docker-compose restart${NC}"
echo -e "  Parar:        ${YELLOW}docker-compose down${NC}"
echo -e "  Actualizar:   ${YELLOW}git pull && docker-compose up -d --build${NC}"
