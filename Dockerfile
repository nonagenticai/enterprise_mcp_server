FROM python:3.12-slim

LABEL description="Enterprise MCP Gateway Server with Claude Code CLI"
LABEL version="1.3"
LABEL maintainer="George Dekker"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies including Node.js, uv and clean up
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && pip install --no-cache-dir uv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create directory for Claude configuration
RUN mkdir -p /root/.claude

# Copy dependency files
COPY pyproject.toml ./
COPY uv.lock* ./
COPY README.md ./

# Install Python dependencies using uv
RUN uv sync --frozen

# Copy the application code
COPY . /app/

# Expose the port that the app runs on
EXPOSE 8030

# Set environment variables for database connection
ENV PORT=8030
ENV HOST=0.0.0.0
ENV POSTGRES_HOST=postgres
ENV POSTGRES_PORT=5432
ENV POSTGRES_DB=enterprise_mcp_server
ENV POSTGRES_USER=postgres
ENV POSTGRES_PASSWORD=postgres

# Run the Enterprise MCP ASGI application using uv run
CMD ["uv", "run", "uvicorn", "src.asgi:app", "--host", "0.0.0.0", "--port", "8030"]
