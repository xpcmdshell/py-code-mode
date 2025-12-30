# Azure Container Apps Deployment

Production deployment of py-code-mode on Azure Container Apps with Redis-backed storage and bearer token authentication.

## Architecture

```
                                  Azure Container Apps Environment
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  +-------------------+    HTTP + Bearer Auth    +------------------------+              |
|  | Agent Server      | -----------------------> | Session Server         |              |
|  | (external ingress)|                          | (internal ingress)     |              |
|  | - AutoGen agent   |                          | - py-code-mode server  |              |
|  | - Claude/GPT-4    |                          | - curl, jq, nmap       |              |
|  +-------------------+                          +------------------------+              |
|          ^                                                 |                            |
|          |                                                 | TLS (port 6380)            |
|          |                                                 v                            |
|  +-------+-------+                              +------------------------+              |
|  | User (HTTPS)  |                              | Azure Cache for Redis  |              |
|  +---------------+                              | - tools, skills        |              |
|                                                 | - artifacts, deps      |              |
|                                                 +------------------------+              |
+-----------------------------------------------------------------------------------------+
                                          |
                            All secrets via Container Apps secrets
                            (no Key Vault required)
```

**Data Flow:**
1. User sends request to Agent Server (external HTTPS endpoint)
2. Agent Server authenticates to Session Server using Bearer token
3. Session Server executes code with tools from Redis
4. Artifacts and skills persist to Redis for cross-session access

## Prerequisites

- Azure CLI installed and logged in (`az login`)
- Docker installed (for building images)
- `jq` installed (for JSON parsing in deploy script)
- Python 3.11+ (for running bootstrap script)
- `ANTHROPIC_API_KEY` environment variable (for local development)

## Quick Start

### 1. Deploy Infrastructure

```bash
cd examples/azure-container-apps/deploy

# Deploy Azure resources (ACR, Redis, Container Apps Environment, Storage)
./deploy.sh my-resource-group eastus

# This creates:
# - Azure Container Registry
# - Azure Cache for Redis (Basic C0)
# - Container Apps Environment with Log Analytics
# - Azure Files shares for configs and artifacts
```

### 2. Build and Push Docker Images

The deploy script handles this automatically, but if you need to rebuild:

```bash
cd /path/to/py-code-mode

# Build session server (includes py-code-mode library + tools)
docker build --platform linux/amd64 \
    -f examples/azure-container-apps/Dockerfile \
    -t <acr>.azurecr.io/py-code-mode-session:latest .

# Build agent server (AutoGen + session client)
docker build --platform linux/amd64 \
    -f examples/azure-container-apps/Dockerfile.agent \
    -t <acr>.azurecr.io/py-code-mode-agent:latest .

# Push to ACR
az acr login --name <acr>
docker push <acr>.azurecr.io/py-code-mode-session:latest
docker push <acr>.azurecr.io/py-code-mode-agent:latest
```

### 3. Bootstrap Redis with Tools/Skills/Deps

Before deploying the apps, populate Redis with tools, skills, and pre-configured dependencies:

```bash
# Get Redis connection string from infrastructure output
REDIS_URL=$(az redis list-keys --name <redis-name> --resource-group my-resource-group \
    --query primaryKey -o tsv | xargs -I {} echo "rediss://:{}@<redis-name>.redis.cache.windows.net:6380/0")

# Bootstrap tools
python -m py_code_mode.store bootstrap \
    --source ./examples/shared/tools \
    --target "$REDIS_URL" \
    --prefix agent:tools \
    --type tools

# Bootstrap skills
python -m py_code_mode.store bootstrap \
    --source ./examples/shared/skills \
    --target "$REDIS_URL" \
    --prefix agent:skills

# Pre-configure dependencies (optional)
python -c "
import redis
r = redis.from_url('$REDIS_URL')
# Add packages that should be pre-installed
r.sadd('agent:deps', 'requests>=2.0', 'beautifulsoup4')
"
```

### 4. Deploy Container Apps with Secrets

```bash
# Generate a secure auth token
SESSION_AUTH_TOKEN=$(openssl rand -hex 32)

# Deploy apps with secrets
az deployment group create \
    --resource-group my-resource-group \
    --template-file deploy/app.bicep \
    --parameters \
        environmentId="<environment-id>" \
        acrLoginServer="<acr>.azurecr.io" \
        acrUsername="<acr>" \
        acrPassword="<acr-password>" \
        redisUrl="$REDIS_URL" \
        sessionAuthToken="$SESSION_AUTH_TOKEN" \
        anthropicApiKey="$ANTHROPIC_API_KEY"
```

### 5. Test the Deployment

```bash
# Get agent URL
AGENT_URL=$(az containerapp show --name agent-server --resource-group my-resource-group \
    --query "properties.configuration.ingress.fqdn" -o tsv)

# Submit a task
curl -X POST "https://$AGENT_URL/task" \
    -H "Content-Type: application/json" \
    -d '{"task": "List available tools and skills"}'

# Check health
curl "https://$AGENT_URL/health"
```

## Configuration

### Storage Architecture

All persistent data is stored in Azure Cache for Redis:

| Data Type | Redis Key Pattern | Description |
|-----------|-------------------|-------------|
| Tools | `agent:tools:*` | CLI tool definitions (YAML) |
| Skills | `agent:skills:*` | Reusable Python skills |
| Artifacts | `agent:artifacts:*` | Persisted data from agent sessions |
| Dependencies | `agent:deps` | Pre-configured Python packages |

**Why Redis instead of Azure Files for tools/skills?**
- Faster access (in-memory vs file I/O)
- Better for distributed deployments (multiple replicas)
- Atomic operations for skill creation
- Semantic search support via embeddings

Azure Files is still used for:
- Large artifacts (file uploads, reports)
- Config files mounted at startup

### Tool Definitions

Tools are defined as YAML files and bootstrapped to Redis:

```yaml
# examples/shared/tools/curl.yaml
name: curl
description: Make HTTP requests
command: curl
timeout: 60
tags: [http]

schema:
  options:
    silent:
      type: boolean
      short: s
      description: Silent mode (no progress output)
    location:
      type: boolean
      short: L
      description: Follow redirects
    header:
      type: array
      short: H
      description: HTTP headers
    data:
      type: string
      short: d
      description: POST data
  positional:
    - name: url
      type: string
      required: true
      description: Target URL

recipes:
  get:
    description: Simple GET request (silent, follow redirects)
    preset:
      silent: true
      location: true
    params:
      url: {}
```

### Skill Definitions

Skills are Python files with a `run()` function:

```python
# examples/shared/skills/analyze_repo.py
"""Analyze a GitHub repository - demonstrates multi-tool skill workflow."""

import json

def run(repo: str) -> dict:
    """Analyze a GitHub repository by combining multiple API calls.

    Args:
        repo: Repository in "owner/repo" format (e.g., "anthropics/claude-code")

    Returns:
        Dict with repo analysis including activity metrics
    """
    if "/" not in repo:
        return {"error": "repo must be in 'owner/repo' format"}

    base_url = f"https://api.github.com/repos/{repo}"

    # Fetch repo metadata
    repo_raw = tools.curl(url=base_url)
    repo_data = json.loads(repo_raw)

    return {
        "name": repo_data.get("full_name"),
        "description": repo_data.get("description"),
        "stars": repo_data.get("stargazers_count"),
        "forks": repo_data.get("forks_count"),
        "language": repo_data.get("language"),
    }
```

Agents invoke skills with: `skills.invoke("analyze_repo", repo="anthropics/claude-code")`

### Pre-configured Dependencies

Dependencies are locked at deployment time for security:

```python
# In deploy script or bootstrap
deps_store.add("requests>=2.0")
deps_store.add("beautifulsoup4")
```

The session server starts with `ALLOW_RUNTIME_DEPS=false`, which:
- Installs pre-configured packages on startup (`sync_deps_on_start=True`)
- Blocks `deps.add()` and `deps.remove()` at runtime
- Allows `deps.list()` and `deps.sync()` (read-only operations)

This prevents agents from installing arbitrary packages in production.

### Persistent Artifacts

Artifacts persist across sessions via Redis:

```python
# Agent code (runs in session server)
artifacts.save("scan_results", data, description="Network scan from 2024-01-15")

# Later session
previous = artifacts.load("scan_results")
```

## Environment Variables

### Session Server

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `REDIS_URL` | Yes | Redis connection string (`rediss://...`) |
| `CONTAINER_AUTH_TOKEN` | Yes | Bearer token for API authentication |
| `ALLOW_RUNTIME_DEPS` | No | Allow runtime package installation (default: false) |

### Agent Server

| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | No | Server port (default: 8080) |
| `SESSION_URL` | Yes | Session server URL (e.g., `http://session-server`) |
| `SESSION_AUTH_TOKEN` | Yes | Bearer token to authenticate with session server |
| `AZURE_AI_ENDPOINT` | Yes* | Azure AI Foundry endpoint for Claude models |
| `ANTHROPIC_API_KEY` | No | Anthropic API key (for local development) |

*Required in production. Use `ANTHROPIC_API_KEY` for local development instead.

## Security Considerations

### Authentication

1. **Bearer Token Authentication**: The session server API requires a Bearer token in the `Authorization` header. This token is shared between agent and session servers via Container Apps secrets.

2. **Defense in Depth**: Even with internal-only ingress, the session server requires authentication. This protects against:
   - Compromised containers in the same environment
   - Misconfigured ingress rules
   - Future network topology changes

3. **Fail-Closed Design**: If `CONTAINER_AUTH_TOKEN` is not set, the session server refuses to start rather than running without auth.

### Network Isolation

1. **Internal Ingress**: The session server uses internal-only ingress, accessible only from within the Container Apps environment.

2. **TLS for Redis**: Azure Cache for Redis requires TLS 1.2+ (`rediss://` scheme). Non-SSL port is disabled.

3. **No Public Endpoints**: Only the agent server has a public endpoint. The session server is completely internal.

### Runtime Safety

1. **Runtime Deps Disabled**: `ALLOW_RUNTIME_DEPS=false` prevents agents from installing packages at runtime. All dependencies must be pre-configured.

2. **Tool Allowlist**: Only tools defined in the bootstrapped configuration are available. Agents cannot execute arbitrary shell commands.

3. **Timeout Limits**: All tool executions have configurable timeouts (default: 60s for most tools, 300s for nmap).

4. **No Shell Access**: The session server executes Python code with injected namespaces, not arbitrary shell commands.

### Secrets Management

All secrets are managed via Container Apps secrets (not Key Vault):

| Secret | Used By | Purpose |
|--------|---------|---------|
| `acr-password` | Both | Pull images from ACR |
| `redis-url` | Session | Connect to Redis |
| `session-auth-token` | Both | API authentication |
| `anthropic-api-key` | Agent | Claude API access |

Container Apps secrets are:
- Encrypted at rest
- Injected as environment variables at runtime
- Not visible in logs or container inspection

## Scaling

The deployment includes auto-scaling based on HTTP concurrency:

```yaml
scale:
  minReplicas: 1
  maxReplicas: 5  # Session server
  # maxReplicas: 3  # Agent server
```

**Considerations:**
- Session server scales based on code execution load
- Agent server scales based on concurrent user requests
- Redis handles concurrent connections from all replicas
- Artifacts and skills are shared across all replicas via Redis

## Monitoring

### View Logs

```bash
# Session server logs
az containerapp logs show --name session-server --resource-group my-rg --follow

# Agent server logs
az containerapp logs show --name agent-server --resource-group my-rg --follow

# System logs (startup issues)
az containerapp logs show --name session-server --resource-group my-rg --type system
```

### Health Checks

Both servers expose `/health` endpoints:

```bash
# Agent (external)
curl https://<agent-fqdn>/health

# Session (requires tunnel for local testing)
az containerapp tunnel --name session-server --resource-group my-rg
curl http://localhost:8080/health
```

### Metrics

```bash
# Request metrics
az monitor metrics list --resource /subscriptions/.../session-server \
    --metric Requests --interval PT1M

# Redis metrics
az monitor metrics list --resource /subscriptions/.../redis \
    --metric usedmemory --interval PT5M
```

## Troubleshooting

### Container won't start

Check system logs for startup errors:
```bash
az containerapp logs show --name session-server --resource-group my-rg --type system
```

Common issues:
- Missing `CONTAINER_AUTH_TOKEN` (server refuses to start without auth)
- Invalid `REDIS_URL` (connection refused)
- Missing secrets in deployment

### Authentication failures

If you see 401 errors between agent and session:
```bash
# Verify both servers have the same token
az containerapp show --name session-server --resource-group my-rg \
    --query "properties.template.containers[0].env[?name=='CONTAINER_AUTH_TOKEN']"

az containerapp show --name agent-server --resource-group my-rg \
    --query "properties.template.containers[0].env[?name=='SESSION_AUTH_TOKEN']"
```

### Tools/Skills not found

Verify data was bootstrapped to Redis:
```bash
# Connect to Redis and check keys
redis-cli -h <redis>.redis.cache.windows.net -p 6380 --tls -a <key>
> KEYS agent:tools:*
> KEYS agent:skills:*
```

### Connection refused from agent

Ensure agent is using internal hostname:
```bash
# Correct: internal DNS name
SESSION_URL=http://session-server

# Wrong: external FQDN (won't work for internal service)
SESSION_URL=https://session-server.<env>.azurecontainerapps.io
```

### Redis connection issues

Azure Cache for Redis requires TLS:
```bash
# Correct: rediss:// (with TLS)
REDIS_URL=rediss://:key@host.redis.cache.windows.net:6380/0

# Wrong: redis:// (no TLS, will fail)
REDIS_URL=redis://:key@host.redis.cache.windows.net:6379/0
```

## Cost Estimate

| Resource | SKU | Est. Monthly Cost |
|----------|-----|-------------------|
| Container Apps (session) | 1 vCPU, 2GB | ~$30-50 |
| Container Apps (agent) | 0.5 vCPU, 1GB | ~$15-25 |
| Azure Cache for Redis | Basic C0 (250MB) | ~$16 |
| Azure Files | 5GB | ~$0.50 |
| Log Analytics | 5GB/month | ~$12 |
| Container Registry | Basic | ~$5 |

**Total estimate: ~$80-110/month** (varies by region and usage)

Use consumption-based scaling to minimize costs during low usage. Set `minReplicas: 0` for development environments.

## Files

```
azure-container-apps/
├── README.md                    # This file
├── agent.py                     # Standalone CLI agent using Session (for local testing)
├── agent_server.py              # FastAPI HTTP server using SessionClient (for Azure deployment)
├── bootstrap_redis.py           # Script to populate Redis with tools/skills/deps
├── pyproject.toml               # Dependencies
├── Dockerfile                   # Session server image
├── Dockerfile.agent             # Agent server image
└── deploy/
    ├── deploy.sh                # One-click deployment script
    ├── main.bicep               # Main deployment entry point
    ├── infra.bicep              # Infrastructure (ACR, Redis, Environment)
    ├── redis.bicep              # Redis module
    ├── app.bicep                # Container Apps (session + agent)
    └── container-app.yaml       # Container app configuration
```

## Local Development

Run the agent locally against a local Redis:

```bash
# Start Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Bootstrap tools and skills
REDIS_URL=redis://localhost:6379 python -m py_code_mode.store bootstrap \
    --source ../shared/tools --target redis://localhost:6379 --prefix agent:tools --type tools
REDIS_URL=redis://localhost:6379 python -m py_code_mode.store bootstrap \
    --source ../shared/skills --target redis://localhost:6379 --prefix agent:skills

# Run agent
cd examples/azure-container-apps
REDIS_URL=redis://localhost:6379 ANTHROPIC_API_KEY=your-key uv run python agent.py
```

Or run against the deployed Azure resources:

```bash
# Create tunnel to session server
az containerapp tunnel --name session-server --resource-group my-rg &

# Run agent locally pointing to tunnel
SESSION_URL=http://localhost:8080 \
SESSION_AUTH_TOKEN=<token> \
ANTHROPIC_API_KEY=your-key \
uv run python agent.py
```
