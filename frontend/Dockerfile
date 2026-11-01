# Build stage
FROM node:16-alpine as build

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca npm ci --no-audit --no-fund; \
    else npm ci --no-audit --no-fund; fi

# Copy source code
COPY . .

# Build the app
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built assets from build stage
COPY --from=build /app/build /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 3000

# Start nginx
CMD ["nginx", "-g", "daemon off;"]