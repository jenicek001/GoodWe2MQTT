# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Create a non-root user
RUN groupadd -r goodwe && useradd -r -g goodwe goodwe

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ ./src/
COPY goodwe2mqtt.py logger.py ./

# Switch to non-root user
USER goodwe

# Environment variables
ENV PYTHONUNBUFFERED=1

CMD ["python", "goodwe2mqtt.py"]
