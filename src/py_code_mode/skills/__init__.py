"""py_code_mode.skills - Skill store, library, and semantic search."""

from py_code_mode.skills.skill import (
    PythonSkill,
    SkillMetadata,
    SkillParameter,
)
from py_code_mode.skills.store import (
    FileSkillStore,
    MemorySkillStore,
    RedisSkillStore,
    SkillStore,
)

# Semantic features require numpy/scikit-learn - optional import
try:
    from py_code_mode.skills.embeddings import (
        MODEL_ALIASES,
        Embedder,
        EmbeddingProvider,
        MockEmbedder,
        cosine_similarity,
        resolve_model_name,
    )
    from py_code_mode.skills.library import (
        RankingConfig,
        SkillLibrary,
        create_skill_library,
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
    SkillLibrary = None  # type: ignore[assignment, misc]
    create_skill_library = None  # type: ignore[assignment]

__all__ = [
    # Core types
    "PythonSkill",
    "SkillMetadata",
    "SkillParameter",
    # Stores
    "SkillStore",
    "MemorySkillStore",
    "FileSkillStore",
    "RedisSkillStore",
    # Semantic (optional)
    "SEMANTIC_AVAILABLE",
    "MODEL_ALIASES",
    "Embedder",
    "EmbeddingProvider",
    "MockEmbedder",
    "cosine_similarity",
    "resolve_model_name",
    "RankingConfig",
    "SkillLibrary",
    "create_skill_library",
]
