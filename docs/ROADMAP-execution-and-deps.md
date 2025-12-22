# Roadmap: Execution Environments and Dependency Management

Status: **Ready for Implementation**
Created: 2024-12-20
Last Updated: 2024-12-21

---

## Problem Statement

py-code-mode conflates three separate dependency concerns:

1. **Library deps** - what py-code-mode itself needs to run
2. **Host application deps** - the agent/MCP server using py-code-mode
3. **Execution environment deps** - what `import X` should find inside `run_code()`

Additionally, the execution isolation spectrum has a gap:

```
In-Process ◄──────────────────────────────────► Full Container
    │                                                    │
    │  Fast startup                      Full isolation  │
    │  Shared deps                       Slow startup    │
    │  No isolation                      Heavy runtime   │
    │                                                    │
    └────────────── GAP: Need lightweight isolation ─────┘
```

---

## Part 1: Dependency Management System

### Current Pain Points

| Scenario | Current Experience |
|----------|-------------------|
| MCP with Claude Code | User installs MCP, wants pandas. No clear path. |
| Container executor | Must edit tools.yaml, rebuild Docker image. |
| Library usage | Must add execution deps to agent's pyproject.toml (conflicts!) |

### Design: Deps as Storage Component

Extend storage to include `deps` alongside tools/skills/artifacts:

```
~/.code-mode/
├── tools/
├── skills/
├── artifacts/
└── deps/
    └── requirements.txt   # execution environment deps
```

### New Components

#### DepsStore Protocol

```python
class DepsStore(Protocol):
    def list(self) -> list[str]: ...
    def add(self, package: str) -> None: ...
    def remove(self, package: str) -> bool: ...
    def clear(self) -> None: ...
    def hash(self) -> str: ...  # For cache invalidation
```

Implementations:
- `FileDepsStore` - stores in `<storage>/deps/requirements.txt`
- `RedisDepsStore` - stores in `<prefix>:deps` Redis set

#### PackageInstaller

```python
class PackageInstaller:
    def sync(self, store: DepsStore) -> SyncResult:
        """Install missing packages, return status."""
```

- Uses `uv pip install` (fast) with pip fallback
- Hash-based caching to avoid reinstall on every startup
- Returns detailed status (installed, already_present, failed)

#### DepsNamespace (Agent API)

Exposed as `deps.*` in run_code():

```python
deps.add("pandas")        # Add and install immediately
deps.list()               # List configured deps
deps.remove("pandas")     # Remove from config
deps.sync()               # Ensure all deps installed
```

### Integration Points

#### Storage Backends

Add `deps` property to `StorageBackend` protocol:

```python
class StorageBackend(Protocol):
    @property
    def tools(self) -> ToolStore: ...
    @property
    def skills(self) -> SkillStoreWrapper: ...
    @property
    def artifacts(self) -> ArtifactStoreWrapper: ...
    @property
    def deps(self) -> DepsStore: ...  # NEW
```

#### InProcessExecutor

On `start()`:
1. Read deps from storage
2. Sync (install missing)
3. Inject `deps` namespace

Note: For in-process, deps install to host Python. This is correct - same process = same environment.

#### ContainerExecutor

On container startup:
1. Mount deps/requirements.txt from storage
2. `uv pip sync` inside container
3. No image rebuild needed!

#### MCP Server

New tools exposed:
- `add_dep(package: str)` - Add and install
- `list_deps()` - List configured deps
- `remove_dep(package: str)` - Remove from config

### Files to Create/Modify

| File | Change |
|------|--------|
| `src/py_code_mode/deps/__init__.py` | New module exports |
| `src/py_code_mode/deps/store.py` | DepsStore protocol, File/Redis implementations |
| `src/py_code_mode/deps/installer.py` | PackageInstaller |
| `src/py_code_mode/deps/namespace.py` | DepsNamespace (agent API) |
| `src/py_code_mode/storage/backends.py` | Add deps property |
| `src/py_code_mode/execution/in_process/executor.py` | Inject deps namespace |
| `src/py_code_mode/execution/container/server.py` | Sync deps at startup |
| `src/py_code_mode/cli/mcp_server.py` | add_dep, list_deps, remove_dep tools |

---

## Part 2: Execution Environment Analysis

### Which Python Runs Code?

#### InProcessExecutor

- Uses `exec(code, namespace)` in host Python
- `import X` uses host's `sys.path`
- **Environment = whatever Python runs the Session**

For MCP with Claude Code, depends on installation method:

| Installation | Python Used | Adding Packages |
|--------------|-------------|-----------------|
| `pipx install py-code-mode` | pipx venv | `pipx inject py-code-mode pandas` |
| `uvx py-code-mode-mcp` | ephemeral uv env | `--with pandas` flag |
| `pip install py-code-mode` | current env | `pip install pandas` |

#### ContainerExecutor

- Runs code in Docker container
- Has own Python environment (from image)
- `python_deps` in tools.yaml installed at startup
- **Environment = container's Python**

### Design Decision

**Accept the model, don't over-abstract:**

- In-process = host environment (correct - same process)
- Container = isolated environment (correct - separate process)

The deps system (Part 1) makes managing both ergonomic.

---

## Part 3: Lightweight Isolation (Microsandbox)

### The Gap

Between in-process (no isolation) and container (heavyweight), users want:
- Dependency isolation
- Fast startup (<500ms)
- Lower resource overhead than Docker

### Microsandbox Overview

[microsandbox](https://github.com/microsandbox/microsandbox) provides:

- **Hardware isolation** via microVMs (libkrun)
- **<200ms startup** (faster than Docker)
- **OCI compatible** (runs standard container images)
- **HVF on macOS**, KVM on Linux
- **Built-in MCP support**
- **Status: Experimental**

### Proposed: MicrosandboxExecutor

Same architecture as ContainerExecutor - session server inside sandbox, HTTP communication:

```
Host Process                    Sandbox (microVM)
┌─────────────────┐            ┌─────────────────────┐
│ MicrosandboxExec│───HTTP────▶│ Session Server      │
│ (thin client)   │            │ (py-code-mode)      │
└─────────────────┘            │ tools.* skills.*    │
                               └─────────────────────┘
```

### Reusable Components

- `container/server.py` - Session server (unchanged)
- `container/client.py` - HTTP client (works for any target)
- Storage access patterns - Same approach

### Comparison

| Aspect | InProcess | Container | Microsandbox |
|--------|-----------|-----------|--------------|
| Startup | ~0ms | 2-5s | <200ms |
| Isolation | None | Kernel | Hardware (VM) |
| Deps separation | No | Yes | Yes |
| Platform | All | Linux/macOS/Win | Linux (KVM), macOS (HVF) |
| Maturity | Production | Production | Experimental |

### Open Questions (Require Spike)

1. **File mounting** - Can microsandbox mount host directories? Critical for FileStorage.
2. **Port exposure** - Can sandbox expose HTTP to host? Needed for session server.
3. **Server lifecycle** - Does user run `msb server start` separately?
4. **Memory/CPU limits** - Configuration unclear from docs.

### Proposed Module Structure

```
src/py_code_mode/execution/
  microsandbox/
    __init__.py       # MicrosandboxConfig, MicrosandboxExecutor
    config.py         # MicrosandboxConfig dataclass
    executor.py       # MicrosandboxExecutor
```

### Config Design

```python
@dataclass
class MicrosandboxConfig:
    name: str | None = None
    server_url: str = "http://127.0.0.1:5555"
    api_key: str | None = None
    timeout: float = 30.0
    startup_timeout: float = 10.0  # Much faster than Docker
    server_port: int = 8080
    image: str = "py-code-mode:tools"  # Same OCI image as container
```

---

## Implementation Phases

### Phase 1: Deps Management (Foundation)

**Priority: High**
**Effort: Medium**
**Risk: Low**

1. Create `deps/` module (store, installer, namespace)
2. Integrate with storage backends
3. Integrate with InProcessExecutor
4. Add MCP tools
5. Update ContainerExecutor to use storage-based deps

This benefits all executors and unblocks ergonomic dependency management.

### Phase 2: Microsandbox Spike

**Priority: Medium**
**Effort: Low**
**Risk: Medium**

Validate before full implementation:
1. Can we run session server inside microsandbox?
2. Can we communicate via HTTP?
3. Can we mount host directories?
4. What's the actual startup time?

### Phase 3: MicrosandboxExecutor

**Priority: Medium** (contingent on spike success)
**Effort: Medium**
**Risk: Medium**

1. Implement MicrosandboxExecutor (Redis-only first)
2. Add file mounting if supported
3. Integrate with deps system
4. Documentation

### Phase 4: Executor Factory

**Priority: Low**
**Effort: Low**
**Risk: Low**

```python
async def create_executor(preference: str = "auto") -> Executor:
    """Create best available executor.

    Preference order for "auto":
    1. Microsandbox (if available)
    2. Container (if Docker available)
    3. InProcess (always available)
    """
```

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-12-20 | Deps as storage component | Consistent with tools/skills/artifacts pattern |
| 2024-12-20 | Use uv for package installation | 10-100x faster than pip |
| 2024-12-20 | In-process deps go to host Python | Same process = same environment (correct model) |
| 2024-12-20 | Keep ContainerExecutor + add Microsandbox | Different maturity levels, user choice |
| 2024-12-20 | Reuse session server for microsandbox | Proven pattern, minimal new code |

---

## References

- [Microsandbox GitHub](https://github.com/microsandbox/microsandbox)
- [Microsandbox Docs](https://docs.microsandbox.dev/)
- [Awesome Sandbox](https://github.com/restyler/awesome-sandbox) - Alternatives list
- [llm-sandbox](https://github.com/vndee/llm-sandbox) - Another lightweight option

---

## Research Summary (2024-12-21)

### Microsandbox: No-Go

Evaluated microsandbox (libkrun-based microVMs). Ruled out due to:
- **No volume mounts** - Can't inject tools/skills/artifacts from host
- **No port forwarding** - Can't use HTTP session server pattern

Microsandbox is designed for untrusted code isolation, not controlled environments with host access.

### llm-sandbox: Patterns Extracted

Analyzed llm-sandbox implementation for ideas:

| Pattern | Their Approach | Our Adaptation |
|---------|---------------|----------------|
| State persistence | IPython shell | `code.InteractiveConsole` (stdlib) |
| Communication | File-based IPC (poll loop) | JSON-RPC over stdio (faster) |
| Runtime deps | `pip install` in container | `uv pip install` in venv |
| Timeouts | Threading-based | `asyncio.wait_for()` + terminate |

### Final Decision: SubprocessExecutor

**Architecture:**
```
Host Process                    Subprocess (uv venv)
┌─────────────────┐            ┌──────────────────────┐
│SubprocessExecutor│──stdin───►│ session_runner.py    │
│  (JSON-RPC)     │◄──stdout──│ InteractiveConsole   │
└─────────────────┘            │ tools.* skills.*     │
                               └──────────────────────┘
```

**Why this wins:**
- ~100ms warm startup (vs 2-5s for Docker)
- Dependency isolation (separate venv)
- No Docker dependency
- Cross-platform
- Simpler than container orchestration

---

## Notes

This document captures design discussions from 2024-12-20 through 2024-12-21.

**Key insight:** The execution environment should be a first-class concept with its own dependency specification, independent of how py-code-mode or the host app were installed.

**Implementation order:**
1. SubprocessExecutor (core isolation mechanism)
2. DepsStore/DepsNamespace (dependency management)
3. Integration with existing executors
