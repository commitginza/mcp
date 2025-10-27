FROM node:20-slim
WORKDIR /app
COPY bridge/package.json bridge/package-lock.json* ./
RUN npm ci --omit=dev
COPY bridge/ ./
ENV NODE_ENV=production
CMD ["node", "server.js"]
