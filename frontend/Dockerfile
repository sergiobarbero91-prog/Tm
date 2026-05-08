FROM node:20-alpine

WORKDIR /app

# Instalar dependencias (sin yarn.lock para evitar problemas)
COPY package.json ./
RUN yarn install

# Copiar código fuente
COPY . .

# Argumento para la URL del backend
ARG EXPO_PUBLIC_BACKEND_URL
ENV EXPO_PUBLIC_BACKEND_URL=$EXPO_PUBLIC_BACKEND_URL

# Construir la aplicación web
RUN npx expo export -p web

# Instalar serve para servir archivos estáticos
RUN yarn global add serve

# Exponer puerto
EXPOSE 3000

# Comando de inicio
CMD ["serve", "dist", "-s", "-l", "3000"]
