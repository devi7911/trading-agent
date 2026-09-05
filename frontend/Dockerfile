# syntax=docker/dockerfile:1
FROM node:22-alpine AS base
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

# ---- dev: ng serve with hot reload, proxying /api to the api container ----
FROM base AS dev
EXPOSE 4200
CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--port", "4200", "--poll", "1000", "--proxy-config", "proxy.conf.json"]

# ---- build: static bundle ----
FROM base AS build
RUN npx ng build --configuration production

# ---- prod: nginx serving the bundle ----
FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
