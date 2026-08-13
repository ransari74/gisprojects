# syntax=docker/dockerfile:1

# --- dev: the Vite dev server, with the API proxied through it ---------------
FROM node:22-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# --- build: static assets for a CDN (Cloudflare Pages, Vercel, S3) ----------
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# VITE_API_BASE bakes the API origin into the bundle when the frontend is
# hosted separately from the API; leave unset to use a same-origin /api proxy.
ARG VITE_API_BASE
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# --- serve: nginx for the built assets --------------------------------------
FROM nginx:1.27-alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
