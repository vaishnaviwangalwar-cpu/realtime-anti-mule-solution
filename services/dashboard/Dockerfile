# Build stage
FROM node:18-alpine AS build
WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source files
COPY public ./public
COPY src ./src

# Build the React app
ENV CI=false
ENV DISABLE_ESLINT_PLUGIN=true
RUN npm run build

# Production stage – serve with nginx
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html

# Expose port 80 (default for nginx)
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]