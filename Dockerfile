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

# Copy all community modules
COPY package.json .
COPY server.js gateway.js route-registry.js governance-db.js .
COPY openai-proxy.js embeddings.js .
COPY contracts.js constitution.js federation.js subscriptions.js .
COPY seed-mode.js setup-wizard.js instant-roi.js .
COPY explain.js cascade.js conflicts.js deduplication.js .
COPY dreaming.js provenance.js reputation.js staleness.js .
COPY amnesia-detector.js decision-graph.js auto-contract.js .
COPY reference/ ./reference/

EXPOSE 8080

ENV GRID_STORE_DIR=/data
ENV PORT=8080
ENV HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

CMD ["node", "server.js"]
