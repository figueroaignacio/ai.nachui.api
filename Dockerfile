# Use a slim Python image with uv pre-installed
FROM astralsh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy dependency configuration files
COPY pyproject.toml uv.lock ./

# Install dependencies (without installing the project itself)
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
COPY . .

# Sync the project
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.12-slim-bookworm

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Copy the virtual environment and application code from the builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# Expose FastAPI default port
EXPOSE 8000

# Make entrypoint executable
RUN chmod +x /app/entrypoint.sh

# Use the entrypoint script to run migrations and start the server
ENTRYPOINT ["/app/entrypoint.sh"]
