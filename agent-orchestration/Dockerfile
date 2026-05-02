# Multi-stage Dockerfile for Agent Orchestration service

FROM python:3.11-slim as builder

WORKDIR /app

# Install system dependencies for building Python packages
# libffi-dev and libsodium-dev required for pynacl (GitHub secrets encryption)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies for pynacl and Git for DevOps workflows
RUN apt-get update && apt-get install -y \
    libsodium23 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY . .

# Make sure scripts are in PATH
ENV PATH=/root/.local/bin:$PATH

# Expose ports
EXPOSE 8002 9002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8002/api/v1/health')"

# Run the application
CMD ["python", "-m", "app.main"]
