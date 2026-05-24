# ── Etapa 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copiar manifiestos primero → caché de npm ci cuando solo cambia el código
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build


# ── Etapa 2: serve ────────────────────────────────────────────────────────────
FROM nginx:alpine

# Artefacto del build de React
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx.conf se copia como template: la imagen oficial de nginx ejecuta
# envsubst sobre los archivos en /etc/nginx/templates/ al arrancar,
# y deposita el resultado en /etc/nginx/conf.d/default.conf.
# Esto permite inyectar BACKEND_URL sin reconstruir la imagen.
COPY nginx.conf /etc/nginx/templates/default.conf.template

# URL del backend — valor por defecto para docker-compose local.
# En Render, sobrescribir con la URL real: https://<backend>.onrender.com
ENV BACKEND_URL=http://backend:8000

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
