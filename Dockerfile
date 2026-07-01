# rebbe.dev - Docker Configuration
# Multi-stage Python build using the uv package manager for fast, reproducible
# dependency resolution. Produces a production-ready image with minimal size
# by using python:3.11-slim as the base and excluding dev dependencies.
FROM python:3.11-slim

# Copy the official uv binary from the Astral-maintained container image.
# This avoids installing uv via pip/curl and keeps the layer cache-friendly.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first (separate layer) so Docker can cache the
# install step when only application code changes.
COPY pyproject.toml uv.lock ./

# Install dependencies using uv.
#   --frozen  : use the exact versions from uv.lock (reproducible builds)
#   --no-dev  : skip test/dev dependencies to keep the image lean
#   --no-install-project : only install third-party deps, not the project itself
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY library/ ./library/

# Set environment variables
ENV PYTHONUNBUFFERED=1
# ^ Ensures Python stdout/stderr are sent straight to the terminal (Docker logs)
#   without being buffered, so log output appears immediately.
ENV PYTHONDONTWRITEBYTECODE=1
# ^ Add the virtual environment's bin directory to PATH so that installed
#   console scripts (e.g. uvicorn) can be invoked directly.
ENV PATH="/app/.venv/bin:$PATH"

# Build the RAG index at image build time so it's ready when the container starts
RUN python -m backend.app.agents.rag

# Create a non-root user and hand off ownership of the app directory. This is
# done after the RAG index build and all COPY steps (which need root to write
# into /app) so the resulting image still runs as root during the build but
# drops privileges before the application actually starts. The app only reads
# rag_index.json.gz at runtime (via gzip.open in read mode), so it never needs
# to write into /app after this point.
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Expose the port uvicorn listens on inside the container
EXPOSE 8000

# Launch the FastAPI application via uvicorn, binding to all interfaces
# so the container is reachable from the Docker network.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
