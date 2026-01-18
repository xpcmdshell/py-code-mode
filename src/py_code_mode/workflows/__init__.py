"""py_code_mode.workflows - Workflow store, library, and semantic search."""

from py_code_mode.workflows.store import (
    FileWorkflowStore,
    MemoryWorkflowStore,
    RedisWorkflowStore,
    WorkflowStore,
)
from py_code_mode.workflows.vector_store import (
    ModelInfo,
    SearchResult,
    VectorStore,
    compute_content_hash,
)
from py_code_mode.workflows.workflow import (
    PythonWorkflow,
    WorkflowMetadata,
    WorkflowParameter,
)

# Semantic features require numpy/scikit-learn - optional import
try:
    from py_code_mode.workflows.embeddings import (
        MODEL_ALIASES,
        Embedder,
        EmbeddingProvider,
        MockEmbedder,
        cosine_similarity,
        resolve_model_name,
    )
    from py_code_mode.workflows.library import (
        RankingConfig,
        WorkflowLibrary,
        create_workflow_library,
    )

    SEMANTIC_AVAILABLE = True
except ImportError:
    SEMANTIC_AVAILABLE = False
    MODEL_ALIASES = None  # type: ignore[assignment]
    Embedder = None  # type: ignore[assignment, misc]
    EmbeddingProvider = None  # type: ignore[assignment, misc]
    MockEmbedder = None  # type: ignore[assignment, misc]
    cosine_similarity = None  # type: ignore[assignment]
    resolve_model_name = None  # type: ignore[assignment]
    RankingConfig = None  # type: ignore[assignment, misc]
    WorkflowLibrary = None  # type: ignore[assignment, misc]
    create_workflow_library = None  # type: ignore[assignment]

__all__ = [
    # Core types
    "PythonWorkflow",
    "WorkflowMetadata",
    "WorkflowParameter",
    # Stores
    "WorkflowStore",
    "MemoryWorkflowStore",
    "FileWorkflowStore",
    "RedisWorkflowStore",
    # VectorStore types
    "VectorStore",
    "ModelInfo",
    "SearchResult",
    "compute_content_hash",
    # Semantic (optional)
    "SEMANTIC_AVAILABLE",
    "MODEL_ALIASES",
    "Embedder",
    "EmbeddingProvider",
    "MockEmbedder",
    "cosine_similarity",
    "resolve_model_name",
    "RankingConfig",
    "WorkflowLibrary",
    "create_workflow_library",
]
