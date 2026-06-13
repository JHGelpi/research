# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage — install deps into a clean layer
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .

RUN pip install --upgrade pip --quiet \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---------------------------------------------------------------------------
# Runtime stage — minimal image, non-root user
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root user for least-privilege operation
RUN groupadd --gid 1001 agent \
 && useradd --uid 1001 --gid agent --shell /bin/bash --create-home agent

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy source — owner is agent, not root
COPY --chown=agent:agent . .

USER agent

# agent.py reads from stdin — keep it open; no HTTP port needed
ENTRYPOINT ["python", "agent.py"]
