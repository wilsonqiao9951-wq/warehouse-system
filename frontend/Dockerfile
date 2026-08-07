FROM node:20-alpine AS build

ARG NEXT_PUBLIC_API_BASE_URL=/api
ARG OPENPARTSFLOW_VERSION=dev
ARG VCS_REF=unknown

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --include=dev
COPY . ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

ARG OPENPARTSFLOW_VERSION=dev
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="OpenPartsFlow Web" \
      org.opencontainers.image.version="${OPENPARTSFLOW_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=101:101 /app/out /usr/share/nginx/html

USER 101:101
EXPOSE 8080
STOPSIGNAL SIGQUIT
