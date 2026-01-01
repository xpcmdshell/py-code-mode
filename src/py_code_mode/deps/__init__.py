"""Dependencies management module.

Provides storage, installation, and namespace for Python package dependencies.
"""

from py_code_mode.deps.installer import PackageInstaller, SyncResult
from py_code_mode.deps.namespace import (
    ControlledDepsNamespace,
    DepsNamespace,
    RuntimeDepsDisabledError,
)
from py_code_mode.deps.store import DepsStore, FileDepsStore, MemoryDepsStore, RedisDepsStore

__all__ = [
    "DepsStore",
    "FileDepsStore",
    "MemoryDepsStore",
    "RedisDepsStore",
    "PackageInstaller",
    "SyncResult",
    "DepsNamespace",
    "ControlledDepsNamespace",
    "RuntimeDepsDisabledError",
]
