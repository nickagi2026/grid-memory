# Grid Memory — Build & Deploy
#
# Usage:
#   make build          # Build Docker image
#   make run            # Run locally (node)
#   make docker-run     # Run via Docker Compose
#   make test           # Run all tests
#   make test-store     # Run store engine tests
#   make test-python    # Run Python SDK tests
#   make test-node      # Run Node.js SDK tests
#   make test-proxy     # Run proxy tests
#   make clean          # Clean temp files

IMAGE_NAME ?= grid-memory
IMAGE_TAG ?= latest
PORT ?= 8080

# ── Docker ──

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

docker-run:
	docker compose up -d

docker-stop:
	docker compose down

docker-logs:
	docker compose logs -f

# To push to a registry:
#   make push REGISTRY=ghcr.io/your-org
push:
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)
	docker push $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

# ── Local Run ──

run:
	node server.js

run-proxy:
	GRID_UPSTREAM_API_KEY=$(GRID_UPSTREAM_API_KEY) node server.js

run-python:
	cd sdk/python && python3 -m grid_memory.openai_server

# ── Tests ──

test: test-store test-python test-node test-proxy

test-store:
	node tests/test-store.js

test-python:
	cd sdk/python && python3 -m unittest discover tests -v

test-node:
	cd sdk/node && npm test

test-proxy:
	# Start server, run proxy tests, stop server
	PORT=$(PORT) node server.js & SERVER_PID=$$!; \
	sleep 2; \
	GRID_URL=http://localhost:$(PORT) node --test tests/test-openai-proxy.js; \
	EXIT_CODE=$$?; \
	kill $$SERVER_PID 2>/dev/null; \
	exit $$EXIT_CODE

test-proxy-python:
	# Start Python proxy, run tests, stop
	PORT=9098 python3 -m grid_memory.openai_server & PY_PID=$$!; \
	sleep 2; \
	GRID_URL=http://localhost:9098 python3 -m unittest sdk/python/tests/test_openai_server.py -v; \
	EXIT_CODE=$$?; \
	kill $$PY_PID 2>/dev/null; \
	exit $$EXIT_CODE

# ── Clean ──

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf sdk/python/build sdk/python/dist sdk/python/*.egg-info

.PHONY: build push run run-proxy run-python test test-store test-python test-node test-proxy test-proxy-python clean docker-run docker-stop docker-logs
