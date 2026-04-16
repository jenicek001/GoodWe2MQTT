# Stage 1: Builder — install dependencies via Poetry into an isolated prefix
FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir poetry==2.1.3

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root --no-interaction

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Create a non-root user
RUN groupadd -r goodwe && useradd -r -g goodwe goodwe

# Copy installed dependencies from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Copy application source
COPY src/ ./src/

# Switch to non-root user
USER goodwe

ENV PYTHONUNBUFFERED=1

CMD ["python", "src/goodwe2mqtt.py"]
