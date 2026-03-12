# CLI Reference

Command-line tools for py-code-mode.

## MCP Server

The MCP server exposes py-code-mode to Claude Code and other MCP clients.

### Installation

```bash
# Add to Claude Code
claude mcp add py-code-mode -- uvx --from git+https://github.com/xpcmdshell/py-code-mode.git@v0.16.1 py-code-mode-mcp --base ~/.code-mode
```

### Usage

```bash
py-code-mode-mcp [OPTIONS]
```

### Minimal Setup (Recommended)

In normal usage, you only need storage. Everything else is optional.

```bash
# Easiest: one base directory (auto-uses base/tools if present)
py-code-mode-mcp --base ~/.code-mode

# Or explicit storage path
py-code-mode-mcp --storage ./data

# Optional: choose a non-default executor
py-code-mode-mcp --base ~/.code-mode --executor deno-sandbox
```

### Required vs Optional

- Required: one of `--base`, `--storage`, or `--redis`
- Optional: all other flags
- Default executor: `subprocess`

### Common Options

| Flag | Description | Default |
|------|-------------|---------|
| `--base PATH` | Base directory with `tools/`, `workflows/`, `artifacts/` subdirs | - |
| `--storage PATH` | Path to storage directory (workflows, artifacts) | - |
| `--tools PATH` | Path to tools directory (YAML definitions) | - |
| `--redis URL` | Redis URL for storage | - |
| `--prefix PREFIX` | Redis key prefix | `py-code-mode` |
| `--executor {subprocess,in-process,container,deno-sandbox}` | Execution backend | `subprocess` |
| `--timeout SECONDS` | Code execution timeout | backend-specific |
| `--no-runtime-deps` | Disable runtime dependency installation | false |
| `--no-sync-deps` | Don't install pre-configured deps on startup | false |

### Advanced Backend Overrides (Escape Hatches)

These are optional tuning/debug flags. You do not need them for normal setup.
Use backend-specific flags only with matching `--executor`.

#### Subprocess (`--executor subprocess`)

| Flag | Description |
|------|-------------|
| `--subprocess-python-version VERSION` | Python `major.minor` for kernel venv |
| `--subprocess-venv-path PATH` | Explicit venv path |
| `--subprocess-startup-timeout SECONDS` | Kernel startup timeout |
| `--subprocess-ipc-timeout SECONDS` | RPC timeout for host/sandbox calls |
| `--subprocess-no-cache-venv` | Disable venv cache |
| `--subprocess-cleanup-venv-on-close` | Delete venv when session exits |

#### In-Process (`--executor in-process`)

| Flag | Description |
|------|-------------|
| `--inprocess-ipc-timeout SECONDS` | RPC timeout for host namespace calls |

#### Container (`--executor container`)

| Flag | Description |
|------|-------------|
| `--container-image IMAGE` | Docker image to run |
| `--container-port PORT` | Host port for container API |
| `--container-host HOST` | Host for container API connection |
| `--container-startup-timeout SECONDS` | Container startup timeout |
| `--container-ipc-timeout SECONDS` | Container RPC timeout |
| `--container-remote-url URL` | Connect to an existing remote session server |
| `--container-no-auto-build` | Disable auto-build when image is missing |
| `--container-keep-container` | Keep container after MCP server exits |
| `--container-auth-token TOKEN` | Bearer token for container API auth |
| `--container-auth-disabled` | Disable container API auth (local dev only) |

#### Deno Sandbox (`--executor deno-sandbox`)

| Flag | Description |
|------|-------------|
| `--deno-executable PATH_OR_NAME` | Deno binary to execute |
| `--deno-runner-path PATH` | Runner TypeScript entrypoint path |
| `--deno-dir PATH` | Deno cache directory (`DENO_DIR`) |
| `--deno-network-profile {none,deps-only,full}` | Network policy for sandbox process |
| `--deno-ipc-timeout SECONDS` | Host/sandbox RPC timeout |
| `--deno-deps-timeout SECONDS` | Dependency installation timeout |
| `--deno-deps-net-allowlist HOST` | Allowed host for `deps-only` (repeat flag) |

### Examples

```bash
# Minimal default setup
py-code-mode-mcp --base ~/.code-mode

# Explicit storage + tools
py-code-mode-mcp --storage ./data --tools ./project/tools

# Redis storage
py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent

# Add a timeout (optional override)
py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent --timeout 60

# Use Deno sandbox backend
py-code-mode-mcp --base ~/.code-mode --executor deno-sandbox

# Deno sandbox with deps-only network profile
py-code-mode-mcp \
  --base ~/.code-mode \
  --executor deno-sandbox \
  --deno-network-profile deps-only \
  --deno-deps-net-allowlist pypi.org \
  --deno-deps-net-allowlist files.pythonhosted.org

# Use in-process backend (fastest, least isolated)
py-code-mode-mcp --base ~/.code-mode --executor in-process

# Container backend with explicit image
py-code-mode-mcp --base ~/.code-mode --executor container --container-image py-code-mode-tools:latest

# Production-style lock-down
py-code-mode-mcp --base ~/.code-mode --no-runtime-deps
```

### Exposed MCP Tools

When running, the server exposes these tools to MCP clients:

| Tool | Description |
|------|-------------|
| `run_code` | Execute Python with access to tools, workflows, artifacts, deps |
| `list_tools` | List available tools |
| `search_tools` | Semantic search for tools |
| `list_workflows` | List available workflows |
| `search_workflows` | Semantic search for workflows |
| `create_workflow` | Save a new workflow |
| `delete_workflow` | Remove a workflow |
| `list_artifacts` | List saved artifacts |
| `list_deps` | List configured dependencies |
| `add_dep` | Add and install a dependency (if `--no-runtime-deps` not set) |
| `remove_dep` | Remove a dependency (if `--no-runtime-deps` not set) |

---

## Store CLI

Manage workflows, tools, and dependencies in Redis stores.

### Usage

```bash
python -m py_code_mode.cli.store <command> [OPTIONS]
```

### Commands

#### bootstrap

Push workflows, tools, or deps from local files to a store.

```bash
python -m py_code_mode.cli.store bootstrap \
  --source PATH \
  --target URL \
  --prefix PREFIX \
  [--type workflows|tools|deps] \
  [--clear] \
  [--deps "pkg1" "pkg2"]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--source PATH` | Source directory or requirements file | required |
| `--target URL` | Target store URL (e.g., `redis://localhost:6379`) | required |
| `--prefix PREFIX` | Key prefix for items | `workflows` |
| `--type TYPE` | Type of items: `workflows`, `tools`, or `deps` | `workflows` |
| `--clear` | Remove existing items before adding | false |
| `--deps` | Inline package specs (for deps only) | - |

**Examples:**

```bash
# Bootstrap workflows
python -m py_code_mode.cli.store bootstrap \
  --source ./workflows \
  --target redis://localhost:6379 \
  --prefix my-agent

# Bootstrap tools
python -m py_code_mode.cli.store bootstrap \
  --source ./tools \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --type tools

# Bootstrap deps from requirements file
python -m py_code_mode.cli.store bootstrap \
  --source requirements.txt \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --type deps

# Bootstrap deps inline
python -m py_code_mode.cli.store bootstrap \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --type deps \
  --deps "requests>=2.31" "pandas>=2.0"

# Replace all existing workflows
python -m py_code_mode.cli.store bootstrap \
  --source ./workflows \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --clear
```

#### list

List items in a store.

```bash
python -m py_code_mode.cli.store list \
  --target URL \
  --prefix PREFIX \
  [--type workflows|tools|deps]
```

**Examples:**

```bash
# List workflows
python -m py_code_mode.cli.store list \
  --target redis://localhost:6379 \
  --prefix my-agent

# List tools
python -m py_code_mode.cli.store list \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --type tools

# List deps
python -m py_code_mode.cli.store list \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --type deps
```

#### pull

Retrieve workflows from a store to local files.

```bash
python -m py_code_mode.cli.store pull \
  --target URL \
  --prefix PREFIX \
  --dest PATH
```

**Example:**

```bash
# Pull workflows to review agent-created ones
python -m py_code_mode.cli.store pull \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --dest ./workflows-from-redis
```

#### diff

Compare local workflows vs remote store.

```bash
python -m py_code_mode.cli.store diff \
  --source PATH \
  --target URL \
  --prefix PREFIX
```

**Example:**

```bash
# See what agent added or changed
python -m py_code_mode.cli.store diff \
  --source ./workflows \
  --target redis://localhost:6379 \
  --prefix my-agent
```

Output shows:
- `+ name` - Agent-created (in store, not local)
- `- name` - Removed from store (local only)
- `~ name` - Modified
- `= name` - Unchanged

---

## CI/CD Patterns

### Deploy Workflows to Production

```bash
# In CI pipeline
python -m py_code_mode.cli.store bootstrap \
  --source ./workflows \
  --target $REDIS_URL \
  --prefix production \
  --clear
```

### Review Agent Creations

```bash
# Pull what agents created
python -m py_code_mode.cli.store pull \
  --target $REDIS_URL \
  --prefix production \
  --dest ./review

# Compare to source
python -m py_code_mode.cli.store diff \
  --source ./workflows \
  --target $REDIS_URL \
  --prefix production
```

### Pre-configure Dependencies

```bash
# Bootstrap deps to Redis
python -m py_code_mode.cli.store bootstrap \
  --source requirements.txt \
  --target $REDIS_URL \
  --prefix production \
  --type deps

# Then run MCP server with --no-runtime-deps to lock it down
py-code-mode-mcp --redis $REDIS_URL --prefix production --no-runtime-deps
```
