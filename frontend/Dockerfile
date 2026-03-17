FROM node:20-alpine

WORKDIR /app

# Install dependencies (cached layer)
COPY package.json package-lock.json* ./
RUN npm install

# Copy remaining source (dev mode uses volume mounts for hot reload)
COPY . .

EXPOSE 5173

# --host 0.0.0.0 so the port is accessible outside the container
CMD ["npm", "run", "dev", "--", "--host"]
