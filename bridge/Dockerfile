FROM node:20-slim
WORKDIR /app
COPY package.json package-lock.json* ./
# lockfile があれば ci、無ければ install
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi
COPY . .
ENV NODE_ENV=production
CMD ["node","server.js"]
