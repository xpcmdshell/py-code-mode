# Combined Dockerfile for Azure Container Apps deployment
# Includes base + tools in one image for simpler deployment

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies and tools in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build dependencies
    gcc \
    # Network tools
    nmap \
    curl \
    wget \
    dnsutils \
    whois \
    netcat-openbsd \
    traceroute \
    # HTTP tools
    httpie \
    jq \
    # File tools
    file \
    xxd \
    binutils \
    && rm -rf /var/lib/apt/lists/*

# Install uv (official installer provides both uv and uvx commands)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Create directories
RUN mkdir -p /app/skills /workspace/artifacts /workspace/configs

# Copy package files (from repo root)
COPY pyproject.toml README.md ./
COPY src/ src/

# Install py-code-mode with container, redis, and mcp dependencies
RUN uv pip install --system -e ".[container,redis,mcp]"

# Environment
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8080
ENV ARTIFACTS_PATH=/workspace/artifacts
ENV SKILLS_PATH=/workspace/configs/skills
ENV TOOLS_CONFIG=/workspace/configs/tools.yaml

EXPOSE 8080

# Entry point - directly run uvicorn
CMD ["python", "-m", "uvicorn", "py_code_mode.backends.container.server:app", "--host", "0.0.0.0", "--port", "8080"]
