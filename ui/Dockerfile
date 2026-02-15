FROM node:22-alpine AS build

WORKDIR /app/ui

COPY ui/package*.json ./
RUN npm ci

COPY ui/ ./
RUN npm run build

FROM nginx:alpine

COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/ui/dist/ /usr/share/nginx/html/

EXPOSE 80
