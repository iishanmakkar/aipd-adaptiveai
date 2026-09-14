FROM node:18-alpine

WORKDIR /app

COPY package.json package-lock.json ./
# npm ci installs exactly what the lockfile pins. .dockerignore keeps the host
# node_modules out of the context, so the Windows deps can no longer overwrite
# this Linux install (that silently broke the container before).
RUN npm ci --no-audit --no-fund

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
