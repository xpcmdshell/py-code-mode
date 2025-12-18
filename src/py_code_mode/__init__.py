"""py-code-mode: Code mode for LLM agents.

Tools exposed as Python SDK bindings callable via Jupyter execution.
"""

from py_code_mode.adapters import CLIAdapter, CLIToolSpec, ToolAdapter
from py_code_mode.mcp_adapter import MCPAdapter
from py_code_mode.http_adapter import HTTPAdapter, Endpoint
from py_code_mode.artifacts import (
    Artifact,
    ArtifactStore,
    ArtifactStoreProtocol,
    FileArtifactStore,
)
from py_code_mode.redis_artifacts import RedisArtifactStore
from py_code_mode.redis_tools import RedisToolStore, registry_from_redis
from py_code_mode.executor import CodeExecutor, ExecutionResult
from py_code_mode.skills import (
    SkillMetadata,
    SkillParameter,
    PythonSkill,
)
from py_code_mode.skill_store import (
    SkillStore,
    MemorySkillStore,
    FileSkillStore,
    RedisSkillStore,
)
# Semantic features require numpy/scikit-learn - optional import
try:
    from py_code_mode.semantic import (
        EmbeddingProvider,
        GraniteEmbedder,
        MockEmbedder,
        RankingConfig,
        SkillLibrary,
        create_skill_library,
    )
    _SEMANTIC_AVAILABLE = True
except ImportError:
    _SEMANTIC_AVAILABLE = False
    EmbeddingProvider = None  # type: ignore
    GraniteEmbedder = None  # type: ignore
    MockEmbedder = None  # type: ignore
    RankingConfig = None  # type: ignore
    SkillLibrary = None  # type: ignore
    create_skill_library = None  # type: ignore
from py_code_mode.errors import (
    ArtifactNotFoundError,
    ArtifactWriteError,
    CodeModeError,
    DependencyError,
    SkillExecutionError,
    SkillNotFoundError,
    SkillValidationError,
    ToolCallError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from py_code_mode.registry import ScopedToolRegistry, ToolRegistry
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
    # Types
    "ToolDefinition",
    "JsonSchema",
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
    # Executor
    "CodeExecutor",
    "ExecutionResult",
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
    "EmbeddingProvider",
    "GraniteEmbedder",
    "MockEmbedder",
    "RankingConfig",
    "SkillLibrary",
    "create_skill_library",
]
