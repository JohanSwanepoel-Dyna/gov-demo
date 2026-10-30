FROM node:20.18.1-alpine3.21
WORKDIR /app
COPY package.json .
RUN npm install --omit=dev --no-audit --no-fund
COPY . .
USER node
CMD ["node", "server.js"]
