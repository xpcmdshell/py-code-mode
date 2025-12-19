"""py-code-mode: Code mode for LLM agents.

Tools exposed as Python SDK bindings callable via Jupyter execution.
"""

from py_code_mode.adapters import CLIAdapter, CLIToolSpec, ToolAdapter
from py_code_mode.artifacts import (
    Artifact,
    ArtifactStore,
    ArtifactStoreProtocol,
    FileArtifactStore,
)

# Backend protocol and factory
from py_code_mode.backend import (
    Capability,
    Executor,
    get_backend,
    list_backends,
    register_backend,
)

# Import backends to trigger registration
from py_code_mode.backends import InProcessExecutor
from py_code_mode.backends.in_process import CodeExecutor  # Backward compat alias

# Container backend is optional (requires docker, httpx, fastapi)
try:
    from py_code_mode.backends.container import ContainerConfig, ContainerExecutor

    _CONTAINER_AVAILABLE = True
except ImportError:
    _CONTAINER_AVAILABLE = False
    ContainerConfig = None  # type: ignore
    ContainerExecutor = None  # type: ignore

from py_code_mode.http_adapter import Endpoint, HTTPAdapter
from py_code_mode.mcp_adapter import MCPAdapter
from py_code_mode.redis_artifacts import RedisArtifactStore
from py_code_mode.redis_tools import RedisToolStore, registry_from_redis
from py_code_mode.skill_store import (
    FileSkillStore,
    MemorySkillStore,
    RedisSkillStore,
    SkillStore,
)
from py_code_mode.skills import (
    PythonSkill,
    SkillMetadata,
    SkillParameter,
)
from py_code_mode.types import ExecutionResult

# Semantic features require numpy/scikit-learn - optional import
try:
    from py_code_mode.semantic import (
        MODEL_ALIASES,
        Embedder,
        EmbeddingProvider,
        MockEmbedder,
        RankingConfig,
        SkillLibrary,
        create_skill_library,
        resolve_model_name,
    )

    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False
    MODEL_ALIASES = None  # type: ignore
    EmbeddingProvider = None  # type: ignore
    Embedder = None  # type: ignore
    MockEmbedder = None  # type: ignore
    RankingConfig = None  # type: ignore
    SkillLibrary = None  # type: ignore
    create_skill_library = None  # type: ignore
    resolve_model_name = None  # type: ignore
from py_code_mode.errors import (
    ArtifactNotFoundError,
    ArtifactWriteError,
    CodeModeError,
    ConfigurationError,
    DependencyError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillValidationError,
    StorageError,
    StorageReadError,
    StorageWriteError,
    ToolCallError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from py_code_mode.registry import ScopedToolRegistry, ToolRegistry
from py_code_mode.session import Session
from py_code_mode.storage import FileStorage, RedisStorage, StorageBackend
from py_code_mode.types import JsonSchema, ToolDefinition

__version__ = "0.1.0"

__all__ = [
    # Artifacts
    "Artifact",
    "ArtifactStore",
    "ArtifactStoreProtocol",
    "FileArtifactStore",
    "RedisArtifactStore",
    "RedisToolStore",
    "registry_from_redis",
    # Errors
    "CodeModeError",
    "ToolNotFoundError",
    "ToolCallError",
    "ToolTimeoutError",
    "ArtifactNotFoundError",
    "ArtifactWriteError",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillExecutionError",
    "DependencyError",
    "StorageError",
    "StorageReadError",
    "StorageWriteError",
    "ConfigurationError",
    # Types
    "ToolDefinition",
    "JsonSchema",
    "ExecutionResult",
    # Adapters
    "ToolAdapter",
    "CLIAdapter",
    "CLIToolSpec",
    "MCPAdapter",
    "HTTPAdapter",
    "Endpoint",
    # Registry
    "ToolRegistry",
    "ScopedToolRegistry",
    # Backend Protocol and Factory
    "Executor",
    "Capability",
    "register_backend",
    "get_backend",
    "list_backends",
    # Executors
    "InProcessExecutor",
    "CodeExecutor",  # Backward compat alias for InProcessExecutor
    "ContainerExecutor",
    "ContainerConfig",
    # Skills
    "SkillMetadata",
    "SkillParameter",
    "PythonSkill",
    # Skill Storage
    "SkillStore",
    "MemorySkillStore",
    "FileSkillStore",
    "RedisSkillStore",
    # Semantic
    "MODEL_ALIASES",
    "EmbeddingProvider",
    "Embedder",
    "MockEmbedder",
    "RankingConfig",
    "SkillLibrary",
    "resolve_model_name",
    "create_skill_library",
    # Storage and Session
    "StorageBackend",
    "FileStorage",
    "RedisStorage",
    "Session",
]
