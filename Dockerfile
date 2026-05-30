# Grid Memory Server — multi-agent shared memory as a service
# Also includes OpenAI-compatible proxy for transparent context injection.
#
# Usage:
#   docker build -t grid-memory .
#   docker run -d -p 8080:8080 -v grid-data:/data grid-memory
#
# With upstream LLM (context injection + forwarding):
#   docker run -d -p 8080:8080 -e GRID_UPSTREAM_API_KEY=sk-... grid-memory
#
# Agents connect with:
#   base_url = "http://localhost:8080/v1"

FROM node:20-alpine

WORKDIR /app

# Copy only what's needed — zero npm dependencies
COPY package.json .
COPY reference/store.js ./reference/store.js
COPY server.js .
COPY openai-proxy.js .

EXPOSE 8080

ENV GRID_STORE_DIR=/data
ENV PORT=8080
ENV HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

CMD ["node", "server.js"]
