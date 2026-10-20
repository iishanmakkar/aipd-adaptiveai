FROM node:18-alpine

WORKDIR /app

COPY package.json package-lock.json ./
# npm ci installs exactly what the lockfile pins. .dockerignore keeps the host
# node_modules out of the context, so the Windows deps can no longer overwrite
# this Linux install (that silently broke the container before).
RUN npm ci --no-audit --no-fund

COPY . .

# Production builds bake VITE_* at BUILD time (Vite semantics): pass them as
# --build-arg (see docker-compose.prod.yml). The dev server (`npm run dev`,
# the base compose command) reads them from the container environment
# instead, so local development needs no build args.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
