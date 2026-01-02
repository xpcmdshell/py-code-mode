# Production Deployment

Guide for deploying py-code-mode in production environments.

## Architecture

Production deployments typically combine:
- **RedisStorage** - Shared skill library across instances
- **ContainerExecutor** - Isolated code execution
- **Pre-configured dependencies** - Locked down environment
- **Monitoring and observability** - Health checks and logging

```python
import os
from py_code_mode import Session, RedisStorage
from py_code_mode.execution import ContainerExecutor, ContainerConfig

# Shared skill library
storage = RedisStorage(url=os.getenv("REDIS_URL"), prefix="production")

# Isolated execution with authentication and pre-configured deps
config = ContainerConfig(
    timeout=60.0,
    allow_runtime_deps=False,  # Lock down package installation
    auth_token=os.getenv("CONTAINER_AUTH_TOKEN"),  # Required for production
    deps=["pandas>=2.0", "numpy", "requests"],  # Pre-configured dependencies
)
executor = ContainerExecutor(config)

async with Session(storage=storage, executor=executor, sync_deps_on_start=True) as session:
    result = await session.run(agent_code)
```

---

## Security Best Practices

### 1. Enable API Authentication

The container HTTP API requires authentication by default. **Never deploy without authentication.**

```python
# Load token from environment/secret store
token = os.getenv("CONTAINER_AUTH_TOKEN")
# Or: token = azure_keyvault.get_secret("container-auth-token")
# Or: token = hashicorp_vault.read("secret/container-auth")["token"]

config = ContainerConfig(
    auth_token=token,  # Required - server refuses to start without it
)
```

**Fail-closed design:** If you forget to configure auth, the container refuses to start. This prevents accidental unauthenticated deployments.

### 2. Lock Down Dependencies

Prevent agents from installing arbitrary packages:

```python
config = ContainerConfig(
    allow_runtime_deps=False,  # Block runtime installation
    deps=["pandas>=2.0", "requests>=2.28.0"],  # Pre-configure allowed packages
)
```

### 3. Use Container Isolation

Run untrusted agent code in containers:

```python
executor = ContainerExecutor(ContainerConfig(
    timeout=60.0,
    auth_token=os.getenv("CONTAINER_AUTH_TOKEN"),
    network_disabled=False,  # Set True to disable network
    memory_limit="512m",
    cpu_quota=None
))
```

### 4. Validate Input

Never trust agent code without validation:

```python
# Bad: Direct execution
result = await session.run(user_provided_code)

# Better: Validation layer
if is_safe(user_provided_code):
    result = await session.run(user_provided_code)
else:
    raise SecurityError("Unsafe code detected")
```

### 5. Isolate Storage by Tenant

Use separate Redis prefixes for multi-tenant deployments:

```python
def get_storage(tenant_id: str, redis_url: str) -> RedisStorage:
    return RedisStorage(
        url=redis_url,
        prefix=f"tenant-{tenant_id}"
    )
```

---

## Scalability Patterns

### Horizontal Scaling

Multiple agent instances share skill library via Redis:

```
┌─────────────┐     ┌──────────┐     ┌─────────────┐
│  Instance 1 │────▶│  Redis   │◀────│  Instance 2 │
└─────────────┘     │ (Skills) │     └─────────────┘
                    └──────────┘
                         ▲
                         │
                    ┌─────────────┐
                    │  Instance 3 │
                    └─────────────┘
```

All instances benefit when any instance creates a skill.

### Load Balancing

```python
# Each instance runs the same code
async def handle_request(agent_code: str, tenant_id: str):
    storage = get_storage(tenant_id)
    executor = ContainerExecutor(config)

    async with Session(storage=storage, executor=executor) as session:
        return await session.run(agent_code)
```

Load balancer distributes requests across instances.

---

## Container Image Management

### Building Images

```bash
# Build base image
docker build -t py-code-mode:base -f docker/Dockerfile.base .

# Build with additional tools
docker build -t py-code-mode:tools -f docker/Dockerfile.tools .
```

### Updating Images

When you update py-code-mode library code:

```bash
# Rebuild images with new code
docker build -t py-code-mode:base -f docker/Dockerfile.base .

# Restart containers to use new image
# (Kubernetes will do this automatically on rollout)
```

### Multi-Stage Builds

Use multi-stage builds to keep images small:

```dockerfile
# Dockerfile.base
FROM python:3.11-slim as builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
COPY src/ /app/src/
ENV PATH=/root/.local/bin:$PATH
CMD ["python", "-m", "py_code_mode.container.server"]
```

---

## Monitoring and Observability

### Health Checks

```python
from fastapi import FastAPI
from py_code_mode import Session, RedisStorage

app = FastAPI()

@app.get("/health")
async def health():
    try:
        # Check Redis connectivity
        redis_client.ping()

        # Check executor can start
        async with Session(storage=storage, executor=executor) as session:
            await session.run("print('health check')")

        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### Logging

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_agent(code: str):
    logger.info("Starting agent execution", extra={"code_length": len(code)})

    try:
        result = await session.run(code)
        logger.info("Execution succeeded", extra={"result_type": type(result.value)})
        return result
    except Exception as e:
        logger.error("Execution failed", extra={"error": str(e)}, exc_info=True)
        raise
```

### Metrics

Track key metrics:
- Execution time per request
- Success/failure rates
- Skill creation rate
- Redis memory usage
- Container startup time

---

## Example Deployment: Azure Container Apps

See [examples/azure-container-apps/](../examples/azure-container-apps/) for a complete production deployment example including:

- Docker image configuration
- Azure Container Apps deployment
- Redis integration
- Environment configuration
- Scaling policies

---

## Checklist

Before going to production:

- [ ] **Container API authentication configured** (`auth_token` set from secret store)
- [ ] Dependencies pre-configured and locked (`allow_runtime_deps=False`)
- [ ] Using ContainerExecutor for isolation
- [ ] Redis configured with persistence and backups
- [ ] Health checks implemented
- [ ] Logging and metrics in place
- [ ] Multi-instance testing completed
- [ ] Resource limits set (memory, CPU, timeout)
- [ ] Secrets management configured (API keys, credentials, container auth token)
- [ ] Disaster recovery plan documented
- [ ] Monitoring and alerting configured
