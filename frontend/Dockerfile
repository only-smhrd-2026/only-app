# 배포용: 화면을 빌드해서 Caddy 이미지에 넣는다 (docker-compose.yml 의 caddy 서비스). Caddyfile 은 compose 가 마운트.
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /src/dist /srv
