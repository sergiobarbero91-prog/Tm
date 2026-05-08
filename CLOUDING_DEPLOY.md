# 🇪🇸 Guía de Despliegue en Clouding.io

## Índice
1. [Crear cuenta y servidor](#1-crear-cuenta-y-servidor)
2. [Configurar dominio](#2-configurar-dominio)
3. [Conectar al servidor](#3-conectar-al-servidor)
4. [Desplegar la aplicación](#4-desplegar-la-aplicación)
5. [Mantenimiento](#5-mantenimiento)

---

## 1. Crear cuenta y servidor

### 1.1. Registrarse en Clouding.io

1. Ve a [clouding.io](https://clouding.io)
2. Click en **"Registrarse"**
3. Rellena tus datos (acepta pagos con tarjeta española)
4. Verifica tu email

### 1.2. Crear un servidor

1. En el panel, click en **"Crear Servidor"**
2. Configuración recomendada:

| Opción | Valor recomendado |
|--------|-------------------|
| **Sistema Operativo** | Ubuntu 22.04 LTS |
| **Cores** | 1 vCore |
| **RAM** | 2 GB |
| **Disco** | 20 GB SSD |
| **Ubicación** | Barcelona 🇪🇸 |

3. **Coste estimado:** ~5-7€/mes

4. En **"Acceso SSH"**, selecciona **"Contraseña"** y guárdala

5. Click en **"Crear Servidor"**

6. Espera ~2 minutos a que se cree

7. **Anota la IP pública** del servidor (ej: `85.208.xxx.xxx`)

---

## 2. Configurar dominio

### 2.1. Comprar dominio (si no tienes uno)

Opciones españolas:
- [dondominio.com](https://dondominio.com) - Desde 5€/año
- [dinahosting.com](https://dinahosting.com) - Desde 8€/año
- [arsys.es](https://arsys.es) - Desde 7€/año

### 2.2. Configurar DNS

En tu proveedor de dominio, añade estos registros DNS:

| Tipo | Nombre | Valor | TTL |
|------|--------|-------|-----|
| A | @ | `TU_IP_SERVIDOR` | 3600 |
| A | www | `TU_IP_SERVIDOR` | 3600 |

**Ejemplo:** Si tu IP es `85.208.123.45` y tu dominio es `taximeter.es`:
- `@` → `85.208.123.45`
- `www` → `85.208.123.45`

⏳ **Espera 5-30 minutos** a que se propaguen los DNS.

---

## 3. Conectar al servidor

### 3.1. Desde Windows (PowerShell o CMD)

```bash
ssh root@TU_IP_SERVIDOR
```

Introduce la contraseña cuando te la pida.

### 3.2. Desde Mac/Linux (Terminal)

```bash
ssh root@TU_IP_SERVIDOR
```

### 3.3. Alternativa: Panel de Clouding

En el panel de Clouding.io → Tu servidor → **"Consola"**

---

## 4. Desplegar la aplicación

### Opción A: Instalación automática (recomendada)

Una vez conectado al servidor, ejecuta:

```bash
# Descargar e instalar
curl -fsSL https://raw.githubusercontent.com/TU_USUARIO/TU_REPO/main/scripts/install-clouding.sh -o install.sh
chmod +x install.sh
sudo ./install.sh
```

Sigue las instrucciones en pantalla. Te pedirá:
- Tu dominio (ej: `taximeter.es`)
- URL de tu repositorio GitHub

### Opción B: Instalación manual

#### Paso 1: Actualizar sistema
```bash
apt-get update && apt-get upgrade -y
```

#### Paso 2: Instalar Docker
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
systemctl enable docker
systemctl start docker
```

#### Paso 3: Instalar Docker Compose
```bash
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
```

#### Paso 4: Clonar repositorio
```bash
cd /opt
git clone https://github.com/TU_USUARIO/TU_REPO.git taximeter
cd taximeter
```

#### Paso 5: Configurar variables
```bash
# Genera una clave secreta
SECRET_KEY=$(openssl rand -hex 32)

# Crea el archivo .env
cat > .env << EOF
DOMAIN_URL=https://tu-dominio.es
SECRET_KEY=$SECRET_KEY
EOF
```

#### Paso 6: Configurar dominio en nginx
```bash
# Reemplaza TU_DOMINIO.com por tu dominio real
sed -i "s/TU_DOMINIO.com/tu-dominio.es/g" nginx/nginx.conf
```

#### Paso 7: Obtener certificado SSL
```bash
# Instalar certbot
apt-get install -y certbot

# Obtener certificado (asegúrate de que tu dominio apunta al servidor)
certbot certonly --standalone -d tu-dominio.es -d www.tu-dominio.es
```

#### Paso 8: Iniciar aplicación
```bash
docker-compose up -d
```

---

## 5. Mantenimiento

### Comandos útiles

```bash
# Ver estado de los servicios
docker-compose ps

# Ver logs en tiempo real
docker-compose logs -f

# Ver logs de un servicio específico
docker-compose logs -f backend
docker-compose logs -f frontend

# Reiniciar todos los servicios
docker-compose restart

# Reiniciar un servicio específico
docker-compose restart backend

# Parar la aplicación
docker-compose down

# Actualizar la aplicación
cd /opt/taximeter
git pull
docker-compose up -d --build
```

### Renovar certificado SSL

El certificado se renueva automáticamente, pero puedes forzarlo:

```bash
certbot renew --force-renewal
docker-compose restart nginx
```

### Backups de la base de datos

```bash
# Crear backup
docker exec taximeter-mongodb mongodump --out /backup

# Copiar backup al host
docker cp taximeter-mongodb:/backup ./backup-$(date +%Y%m%d)
```

### Monitorizar recursos

```bash
# Ver uso de CPU/RAM
htop

# Ver uso de disco
df -h

# Ver uso de Docker
docker stats
```

---

## Solución de problemas

### La web no carga

1. Verifica que Docker está funcionando:
```bash
docker-compose ps
```

2. Revisa los logs:
```bash
docker-compose logs -f
```

3. Verifica el firewall:
```bash
ufw status
ufw allow 80
ufw allow 443
```

### Error de SSL

1. Verifica que el dominio apunta al servidor:
```bash
ping tu-dominio.es
```

2. Renueva el certificado:
```bash
certbot certonly --standalone -d tu-dominio.es
docker-compose restart nginx
```

### La base de datos no conecta

1. Verifica que MongoDB está corriendo:
```bash
docker-compose ps mongodb
docker-compose logs mongodb
```

2. Reinicia MongoDB:
```bash
docker-compose restart mongodb
```

---

## Costes estimados

| Concepto | Coste |
|----------|-------|
| Servidor Clouding.io (2GB RAM) | ~6€/mes |
| Dominio .es | ~8€/año |
| Certificado SSL | **GRATIS** (Let's Encrypt) |
| **TOTAL** | **~7€/mes** |

---

## Soporte

- **Clouding.io:** [soporte@clouding.io](mailto:soporte@clouding.io) - 24/7 en español
- **Documentación:** [docs.clouding.io](https://docs.clouding.io)
- **Teléfono:** 931 22 65 05 (España)

---

## Checklist final

- [ ] Servidor creado en Clouding.io
- [ ] Dominio comprado y DNS configurados
- [ ] Conexión SSH funcionando
- [ ] Docker instalado
- [ ] Repositorio clonado
- [ ] Variables de entorno configuradas
- [ ] Certificado SSL instalado
- [ ] Aplicación desplegada y funcionando
- [ ] Backup configurado (opcional)
