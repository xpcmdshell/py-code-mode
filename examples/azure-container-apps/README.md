# Azure Container Apps Deployment

Production deployment of py-code-mode session server on Azure Container Apps with persistent storage and security isolation.

## Architecture

```
Azure Container Apps Environment
+-------------------------------------------------------------+
|                                                             |
|  +------------------+         +------------------------+    |
|  | Agent Container  |  HTTP   | Session Container      |    |
|  | (your agent)     | ------> | (py-code-mode server)  |    |
|  |                  |         | - nmap, curl, dig      |    |
|  +------------------+         | - persistent state     |    |
|                               +------------------------+    |
|                                          |                  |
|                                          v                  |
|                               +------------------------+    |
|                               | Azure Files (artifacts)|    |
|                               +------------------------+    |
+-------------------------------------------------------------+
```

## Why Azure Container Apps (Not Dynamic Sessions)?

Azure has two container execution options. We use **regular Container Apps** because:

| Feature | Dynamic Sessions | Container Apps |
|---------|------------------|----------------|
| Custom container images | Limited (sandbox restrictions) | Full support |
| Volume mounts | Not supported | Azure Files, EmptyDir |
| Network access (Redis, etc.) | Isolated by default | Full control |
| Session persistence | 15 min max idle | Configurable |
| Use case | Sandboxed untrusted code | Production workloads |

Dynamic Sessions is designed for security sandboxing of untrusted LLM-generated code. For production agents that need custom tools, persistent storage, and network access, regular Container Apps is the right choice.

## Prerequisites

- Azure CLI installed and logged in (`az login`)
- Docker installed
- Container registry (Azure Container Registry or GitHub Container Registry)
- `ANTHROPIC_API_KEY` environment variable

## Quick Start

### 1. Deploy the Session Server

```bash
cd examples/azure-container-apps/deploy

# Deploy (creates resource group, storage, container app)
./deploy.sh my-resource-group my-environment ghcr.io/myorg

# This will:
# - Create Azure resource group and Container Apps environment
# - Create Azure Files shares for artifacts and configs
# - Upload tools.yaml and skills to Azure Files
# - Build and push the Docker image
# - Deploy the container app
```

### 2. Run the Agent Locally (Against Azure Session)

```bash
# Get the session URL (internal FQDN)
az containerapp show --name py-code-mode-session --resource-group my-rg \
    --query "properties.configuration.ingress.fqdn" -o tsv

# For testing, create a tunnel to the internal endpoint
az containerapp tunnel --name py-code-mode-session --resource-group my-rg

# In another terminal
export SESSION_URL=http://localhost:8080
export ANTHROPIC_API_KEY=your-key
python agent.py
```

### 3. Deploy Agent Container to Azure

For production, deploy the agent as another container in the same environment:

```bash
# Build agent image
docker build -t ghcr.io/myorg/my-agent:latest .
docker push ghcr.io/myorg/my-agent:latest

# Deploy agent container
az containerapp create \
    --name my-agent \
    --resource-group my-rg \
    --environment my-environment \
    --image ghcr.io/myorg/my-agent:latest \
    --env-vars SESSION_URL=http://py-code-mode-session:8080 \
               ANTHROPIC_API_KEY=secretref:anthropic-key \
    --secrets anthropic-key=your-api-key
```

## Configuration

### Tools (configs/tools.yaml)

Define CLI tools available to agents:

```yaml
cli_tools:
  - name: nmap
    description: Network scanner
    command: nmap
    args_template: "{flags} {target}"
    timeout_seconds: 300
    tags: [network, recon]
```

### Skills (configs/skills/*.py)

Add reusable code recipes:

```python
# configs/skills/port_scan.py
def run(target: str, ports: str = "80,443") -> dict:
    """Scan ports on target."""
    raw = tools.call("cli.nmap", {"target": target, "flags": f"-p {ports}"})
    # Parse and return structured results
    return {"target": target, "raw": raw}
```

Agents can then use: `skills.invoke("port_scan", target="10.0.0.1")`

### Persistent Artifacts

Artifacts are stored on Azure Files and persist across sessions:

```python
# Save scan results
artifacts.save("scan_results.json", data, description="Initial recon")

# Load in a later session
data = artifacts.load("scan_results.json")
```

### Redis for Distributed Storage (Optional)

For multi-container scenarios, use Redis instead of file-based artifacts:

```bash
# Create Azure Cache for Redis
az redis create --name my-redis --resource-group my-rg --location eastus --sku Basic --vm-size c0

# Get connection string
REDIS_URL=$(az redis list-keys --name my-redis --resource-group my-rg --query primaryKey -o tsv)

# Add as secret
az containerapp secret set --name py-code-mode-session --resource-group my-rg \
    --secrets redis-connection="redis://:$REDIS_URL@my-redis.redis.cache.windows.net:6380?ssl=true"

# Update container to use Redis
az containerapp update --name py-code-mode-session --resource-group my-rg \
    --set-env-vars REDIS_URL=secretref:redis-connection
```

## Files

```
azure-container-apps/
├── agent.py                 # Example agent using SessionClient
├── pyproject.toml           # Dependencies
├── configs/
│   ├── tools.yaml           # CLI tool definitions
│   └── skills/
│       └── port_scan.py     # Example skill
└── deploy/
    ├── deploy.sh            # Deployment script
    └── container-app.yaml   # ACA manifest
```

## Security Considerations

1. **Internal Ingress**: The session server uses internal ingress, accessible only within the Container Apps environment
2. **No Shell Access**: Agents can only execute Python code with predefined tools, not arbitrary shell commands
3. **Tool Allowlist**: Only tools defined in `tools.yaml` are available
4. **Timeout Limits**: All tool executions have configurable timeouts
5. **Artifact Isolation**: Each deployment has its own Azure Files share

## Scaling

The deployment manifest includes auto-scaling based on HTTP concurrency:

```yaml
scale:
  minReplicas: 1
  maxReplicas: 10
  rules:
    - name: http-rule
      http:
        metadata:
          concurrentRequests: "10"
```

Adjust based on your workload. Each replica maintains its own executor state, so sticky sessions may be needed for stateful workflows.

## Monitoring

```bash
# View logs
az containerapp logs show --name py-code-mode-session --resource-group my-rg --follow

# View metrics
az monitor metrics list --resource /subscriptions/.../py-code-mode-session \
    --metric Requests --interval PT1M

# Check health
curl https://<internal-fqdn>/health
```

## Troubleshooting

### Container won't start

Check logs for startup errors:
```bash
az containerapp logs show --name py-code-mode-session --resource-group my-rg --type system
```

### Tools not available

Verify tools.yaml was uploaded:
```bash
az storage file list --account-name <storage> --share-name configs-share
```

### Connection refused from agent

Ensure agent is in the same Container Apps environment and using internal hostname:
```bash
# Should be: http://py-code-mode-session:8080
# Not: https://<fqdn> (that's for external access)
```

## Cost Estimate

| Resource | SKU | Est. Monthly Cost |
|----------|-----|-------------------|
| Container Apps | 1 vCPU, 2GB | ~$30-50 |
| Azure Files | 1GB | ~$0.10 |
| Redis (optional) | Basic C0 | ~$16 |

Costs vary by region and usage. Use consumption-based scaling to minimize costs during low usage.
