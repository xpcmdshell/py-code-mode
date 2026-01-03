# CLI Reference

Command-line tools for py-code-mode.

## MCP Server

The MCP server exposes py-code-mode to Claude Code and other MCP clients.

### Installation

```bash
# Add to Claude Code
claude mcp add py-code-mode -- uvx --from git+https://github.com/xpcmdshell/py-code-mode.git@v0.10.0 py-code-mode-mcp --base ~/.code-mode
```

### Usage

```bash
py-code-mode-mcp [OPTIONS]
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--base PATH` | Base directory with `tools/`, `skills/`, `artifacts/` subdirs | - |
| `--storage PATH` | Path to storage directory (skills, artifacts) | - |
| `--tools PATH` | Path to tools directory (YAML definitions) | - |
| `--redis URL` | Redis URL for storage | - |
| `--prefix PREFIX` | Redis key prefix | `py-code-mode` |
| `--timeout SECONDS` | Code execution timeout | unlimited |
| `--no-runtime-deps` | Disable runtime dependency installation | false |
| `--no-sync-deps` | Don't install pre-configured deps on startup | false |

### Examples

```bash
# Base directory (auto-discovers tools/, skills/, artifacts/)
py-code-mode-mcp --base ~/.code-mode

# Explicit storage + tools paths
py-code-mode-mcp --storage ./data --tools ./project/tools

# Redis storage with timeout
py-code-mode-mcp --redis redis://localhost:6379 --prefix my-agent --timeout 60

# Production: locked down deps
py-code-mode-mcp --base ~/.code-mode --no-runtime-deps
```

### Exposed MCP Tools

When running, the server exposes these tools to MCP clients:

| Tool | Description |
|------|-------------|
| `run_code` | Execute Python with access to tools, skills, artifacts, deps |
| `list_tools` | List available tools |
| `search_tools` | Semantic search for tools |
| `list_skills` | List available skills |
| `search_skills` | Semantic search for skills |
| `create_skill` | Save a new skill |
| `delete_skill` | Remove a skill |
| `list_artifacts` | List saved artifacts |
| `list_deps` | List configured dependencies |
| `add_dep` | Add and install a dependency (if `--no-runtime-deps` not set) |
| `remove_dep` | Remove a dependency (if `--no-runtime-deps` not set) |

---

## Store CLI

Manage skills, tools, and dependencies in Redis stores.

### Usage

```bash
python -m py_code_mode.cli.store <command> [OPTIONS]
```

### Commands

#### bootstrap

Push skills, tools, or deps from local files to a store.

```bash
python -m py_code_mode.cli.store bootstrap \
  --source PATH \
  --target URL \
  --prefix PREFIX \
  [--type skills|tools|deps] \
  [--clear] \
  [--deps "pkg1" "pkg2"]
```

| Option | Description | Default |
|--------|-------------|---------|
| `--source PATH` | Source directory or requirements file | required |
| `--target URL` | Target store URL (e.g., `redis://localhost:6379`) | required |
| `--prefix PREFIX` | Key prefix for items | `skills` |
| `--type TYPE` | Type of items: `skills`, `tools`, or `deps` | `skills` |
| `--clear` | Remove existing items before adding | false |
| `--deps` | Inline package specs (for deps only) | - |

**Examples:**

```bash
# Bootstrap skills
python -m py_code_mode.cli.store bootstrap \
  --source ./skills \
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

# Replace all existing skills
python -m py_code_mode.cli.store bootstrap \
  --source ./skills \
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
  [--type skills|tools|deps]
```

**Examples:**

```bash
# List skills
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

Retrieve skills from a store to local files.

```bash
python -m py_code_mode.cli.store pull \
  --target URL \
  --prefix PREFIX \
  --dest PATH
```

**Example:**

```bash
# Pull skills to review agent-created ones
python -m py_code_mode.cli.store pull \
  --target redis://localhost:6379 \
  --prefix my-agent \
  --dest ./skills-from-redis
```

#### diff

Compare local skills vs remote store.

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
  --source ./skills \
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

### Deploy Skills to Production

```bash
# In CI pipeline
python -m py_code_mode.cli.store bootstrap \
  --source ./skills \
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
  --source ./skills \
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
