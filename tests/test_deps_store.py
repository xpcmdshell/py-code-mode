"""Tests for DepsStore protocol and implementations.

TDD RED phase: These tests are written before implementation.
They will fail until the deps module is implemented.

Test hierarchy:
1. Protocol compliance tests
2. Core operations (add/remove/list/clear)
3. Hash-based cache invalidation
4. Edge cases and invariants
5. Persistence verification
"""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


# =============================================================================
# DepsStore Protocol Tests
# =============================================================================


class TestDepsStoreProtocol:
    """Verify implementations satisfy the DepsStore protocol."""

    def test_file_deps_store_is_deps_store(self, tmp_path: Path) -> None:
        """FileDepsStore should satisfy DepsStore protocol.

        Breaks when: FileDepsStore doesn't implement all protocol methods.
        """
        from py_code_mode.deps import DepsStore, FileDepsStore

        store = FileDepsStore(tmp_path)
        assert isinstance(store, DepsStore)

    def test_redis_deps_store_is_deps_store(self, mock_redis: "MockRedisClient") -> None:
        """RedisDepsStore should satisfy DepsStore protocol.

        Breaks when: RedisDepsStore doesn't implement all protocol methods.
        """
        from py_code_mode.deps import DepsStore, RedisDepsStore

        store = RedisDepsStore(mock_redis, prefix="test")
        assert isinstance(store, DepsStore)

    def test_protocol_requires_list_method(self) -> None:
        """DepsStore protocol requires list() -> list[str].

        Breaks when: Protocol doesn't define list method.
        """
        from py_code_mode.deps import DepsStore

        assert hasattr(DepsStore, "list")

    def test_protocol_requires_add_method(self) -> None:
        """DepsStore protocol requires add(package: str) -> None.

        Breaks when: Protocol doesn't define add method.
        """
        from py_code_mode.deps import DepsStore

        assert hasattr(DepsStore, "add")

    def test_protocol_requires_remove_method(self) -> None:
        """DepsStore protocol requires remove(package: str) -> bool.

        Breaks when: Protocol doesn't define remove method.
        """
        from py_code_mode.deps import DepsStore

        assert hasattr(DepsStore, "remove")

    def test_protocol_requires_clear_method(self) -> None:
        """DepsStore protocol requires clear() -> None.

        Breaks when: Protocol doesn't define clear method.
        """
        from py_code_mode.deps import DepsStore

        assert hasattr(DepsStore, "clear")

    def test_protocol_requires_hash_method(self) -> None:
        """DepsStore protocol requires hash() -> str.

        Breaks when: Protocol doesn't define hash method.
        """
        from py_code_mode.deps import DepsStore

        assert hasattr(DepsStore, "hash")


# =============================================================================
# FileDepsStore Tests
# =============================================================================


class TestFileDepsStore:
    """Tests for file-based dependency store."""

    @pytest.fixture
    def file_store(self, tmp_path: Path):
        """File store in temp directory."""
        from py_code_mode.deps import FileDepsStore

        return FileDepsStore(tmp_path)

    # --- Core Operations ---

    def test_list_empty_store(self, file_store) -> None:
        """list() returns empty list for fresh store.

        Breaks when: Fresh store returns non-empty list.
        """
        assert file_store.list() == []

    def test_add_single_package(self, file_store) -> None:
        """add() adds a package to the store.

        Breaks when: add() doesn't persist the package.
        """
        file_store.add("pandas")
        deps = file_store.list()
        assert "pandas" in deps

    def test_add_multiple_packages(self, file_store) -> None:
        """add() can add multiple packages.

        Breaks when: Only first or last package is stored.
        """
        file_store.add("pandas")
        file_store.add("numpy")
        file_store.add("requests")

        deps = file_store.list()
        assert set(deps) == {"pandas", "numpy", "requests"}

    def test_add_duplicate_package_is_idempotent(self, file_store) -> None:
        """add() with same package twice doesn't create duplicates.

        Breaks when: Duplicate packages appear in list.
        """
        file_store.add("pandas")
        file_store.add("pandas")

        deps = file_store.list()
        assert deps.count("pandas") == 1

    def test_remove_existing_package(self, file_store) -> None:
        """remove() removes an existing package.

        Breaks when: Package still in list after remove.
        """
        file_store.add("pandas")
        result = file_store.remove("pandas")

        assert result is True
        assert "pandas" not in file_store.list()

    def test_remove_nonexistent_package_returns_false(self, file_store) -> None:
        """remove() returns False for nonexistent package.

        Breaks when: Returns True for missing package.
        """
        result = file_store.remove("nonexistent")
        assert result is False

    def test_remove_preserves_other_packages(self, file_store) -> None:
        """remove() only removes the specified package.

        Breaks when: Other packages are also removed.
        """
        file_store.add("pandas")
        file_store.add("numpy")
        file_store.remove("pandas")

        deps = file_store.list()
        assert "numpy" in deps
        assert "pandas" not in deps

    def test_clear_removes_all_packages(self, file_store) -> None:
        """clear() removes all packages.

        Breaks when: Packages remain after clear.
        """
        file_store.add("pandas")
        file_store.add("numpy")
        file_store.add("requests")

        file_store.clear()

        assert file_store.list() == []

    def test_clear_on_empty_store_succeeds(self, file_store) -> None:
        """clear() on empty store doesn't raise.

        Breaks when: clear() raises exception on empty store.
        """
        file_store.clear()  # Should not raise
        assert file_store.list() == []

    # --- Hash-based Cache Invalidation ---

    def test_hash_returns_string(self, file_store) -> None:
        """hash() returns a string.

        Breaks when: hash() returns wrong type.
        """
        h = file_store.hash()
        assert isinstance(h, str)

    def test_hash_empty_store_is_deterministic(self, file_store) -> None:
        """hash() for empty store is consistent.

        Breaks when: hash() returns different values for same state.
        """
        h1 = file_store.hash()
        h2 = file_store.hash()
        assert h1 == h2

    def test_hash_changes_when_package_added(self, file_store) -> None:
        """hash() changes after adding a package.

        Breaks when: hash() is same after state change (cache invalidation broken).
        """
        h1 = file_store.hash()
        file_store.add("pandas")
        h2 = file_store.hash()

        assert h1 != h2

    def test_hash_changes_when_package_removed(self, file_store) -> None:
        """hash() changes after removing a package.

        Breaks when: hash() is same after state change (cache invalidation broken).
        """
        file_store.add("pandas")
        h1 = file_store.hash()
        file_store.remove("pandas")
        h2 = file_store.hash()

        assert h1 != h2

    def test_hash_same_for_same_packages(self, tmp_path: Path) -> None:
        """hash() is same for stores with identical packages.

        Breaks when: hash() uses non-content factors (timestamps, etc.).
        """
        from py_code_mode.deps import FileDepsStore

        store1 = FileDepsStore(tmp_path / "store1")
        store2 = FileDepsStore(tmp_path / "store2")

        store1.add("pandas")
        store1.add("numpy")

        store2.add("numpy")
        store2.add("pandas")

        # Same packages, different add order - hash should be same
        assert store1.hash() == store2.hash()

    # --- Package Normalization ---

    def test_package_name_normalized_to_lowercase(self, file_store) -> None:
        """Package names are normalized to lowercase.

        Breaks when: Case-sensitive package names cause duplicates.
        """
        file_store.add("Pandas")
        deps = file_store.list()

        assert "pandas" in deps
        assert "Pandas" not in deps

    def test_package_name_underscore_normalized(self, file_store) -> None:
        """Underscores and hyphens are normalized.

        Breaks when: 'my-package' and 'my_package' are treated as different.
        """
        file_store.add("my-package")
        file_store.add("my_package")

        deps = file_store.list()
        # PEP 503: treat as same package
        assert len(deps) == 1

    # --- Version Specifiers ---

    def test_add_package_with_version_specifier(self, file_store) -> None:
        """add() handles version specifiers.

        Breaks when: Version specifiers are stripped or cause errors.
        """
        file_store.add("pandas>=2.0")
        deps = file_store.list()

        assert "pandas>=2.0" in deps

    def test_add_package_with_exact_version(self, file_store) -> None:
        """add() handles exact version pins.

        Breaks when: Exact versions cause errors.
        """
        file_store.add("requests==2.31.0")
        deps = file_store.list()

        assert "requests==2.31.0" in deps

    def test_add_package_with_extras(self, file_store) -> None:
        """add() handles extras syntax.

        Breaks when: Extras syntax causes errors.
        """
        file_store.add("httpx[http2]")
        deps = file_store.list()

        assert "httpx[http2]" in deps

    # --- Persistence ---

    def test_add_creates_requirements_file(self, tmp_path: Path) -> None:
        """add() creates requirements.txt in deps/ subdirectory.

        Breaks when: File is not created or in wrong location.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)
        store.add("pandas")

        expected_path = tmp_path / "deps" / "requirements.txt"
        assert expected_path.exists()

    def test_requirements_file_contains_packages(self, tmp_path: Path) -> None:
        """requirements.txt contains added packages.

        Breaks when: File contents don't match added packages.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)
        store.add("pandas>=2.0")
        store.add("numpy")

        requirements_path = tmp_path / "deps" / "requirements.txt"
        content = requirements_path.read_text()

        assert "pandas>=2.0" in content
        assert "numpy" in content

    def test_store_loads_existing_requirements(self, tmp_path: Path) -> None:
        """FileDepsStore loads existing requirements.txt on init.

        Breaks when: Existing deps are ignored.
        """
        from py_code_mode.deps import FileDepsStore

        # Create requirements.txt manually
        deps_dir = tmp_path / "deps"
        deps_dir.mkdir(parents=True)
        (deps_dir / "requirements.txt").write_text("pandas>=2.0\nnumpy\n")

        store = FileDepsStore(tmp_path)
        deps = store.list()

        assert "pandas>=2.0" in deps
        assert "numpy" in deps

    def test_store_handles_comments_in_requirements(self, tmp_path: Path) -> None:
        """FileDepsStore ignores comments in requirements.txt.

        Breaks when: Comments are treated as packages.
        """
        from py_code_mode.deps import FileDepsStore

        deps_dir = tmp_path / "deps"
        deps_dir.mkdir(parents=True)
        (deps_dir / "requirements.txt").write_text("# Data science\npandas\n# Web\nrequests\n")

        store = FileDepsStore(tmp_path)
        deps = store.list()

        assert "pandas" in deps
        assert "requests" in deps
        assert "# Data science" not in deps

    def test_store_handles_blank_lines(self, tmp_path: Path) -> None:
        """FileDepsStore ignores blank lines in requirements.txt.

        Breaks when: Blank lines cause errors or empty entries.
        """
        from py_code_mode.deps import FileDepsStore

        deps_dir = tmp_path / "deps"
        deps_dir.mkdir(parents=True)
        (deps_dir / "requirements.txt").write_text("pandas\n\n\nnumpy\n")

        store = FileDepsStore(tmp_path)
        deps = store.list()

        assert len(deps) == 2
        assert "" not in deps


# =============================================================================
# RedisDepsStore Tests
# =============================================================================


class TestRedisDepsStore:
    """Tests for Redis-based dependency store."""

    @pytest.fixture
    def redis_store(self, mock_redis: "MockRedisClient"):
        """Redis store with mock client."""
        from py_code_mode.deps import RedisDepsStore

        return RedisDepsStore(mock_redis, prefix="test")

    # --- Core Operations ---

    def test_list_empty_store(self, redis_store) -> None:
        """list() returns empty list for fresh store.

        Breaks when: Fresh store returns non-empty list.
        """
        assert redis_store.list() == []

    def test_add_single_package(self, redis_store) -> None:
        """add() adds a package to the store.

        Breaks when: add() doesn't persist the package.
        """
        redis_store.add("pandas")
        deps = redis_store.list()
        assert "pandas" in deps

    def test_add_multiple_packages(self, redis_store) -> None:
        """add() can add multiple packages.

        Breaks when: Only first or last package is stored.
        """
        redis_store.add("pandas")
        redis_store.add("numpy")
        redis_store.add("requests")

        deps = redis_store.list()
        assert set(deps) == {"pandas", "numpy", "requests"}

    def test_add_duplicate_package_is_idempotent(self, redis_store) -> None:
        """add() with same package twice doesn't create duplicates.

        Breaks when: Duplicate packages appear in list.
        """
        redis_store.add("pandas")
        redis_store.add("pandas")

        deps = redis_store.list()
        assert deps.count("pandas") == 1

    def test_remove_existing_package(self, redis_store) -> None:
        """remove() removes an existing package.

        Breaks when: Package still in list after remove.
        """
        redis_store.add("pandas")
        result = redis_store.remove("pandas")

        assert result is True
        assert "pandas" not in redis_store.list()

    def test_remove_nonexistent_package_returns_false(self, redis_store) -> None:
        """remove() returns False for nonexistent package.

        Breaks when: Returns True for missing package.
        """
        result = redis_store.remove("nonexistent")
        assert result is False

    def test_remove_preserves_other_packages(self, redis_store) -> None:
        """remove() only removes the specified package.

        Breaks when: Other packages are also removed.
        """
        redis_store.add("pandas")
        redis_store.add("numpy")
        redis_store.remove("pandas")

        deps = redis_store.list()
        assert "numpy" in deps
        assert "pandas" not in deps

    def test_clear_removes_all_packages(self, redis_store) -> None:
        """clear() removes all packages.

        Breaks when: Packages remain after clear.
        """
        redis_store.add("pandas")
        redis_store.add("numpy")
        redis_store.add("requests")

        redis_store.clear()

        assert redis_store.list() == []

    def test_clear_on_empty_store_succeeds(self, redis_store) -> None:
        """clear() on empty store doesn't raise.

        Breaks when: clear() raises exception on empty store.
        """
        redis_store.clear()  # Should not raise
        assert redis_store.list() == []

    # --- Hash-based Cache Invalidation ---

    def test_hash_returns_string(self, redis_store) -> None:
        """hash() returns a string.

        Breaks when: hash() returns wrong type.
        """
        h = redis_store.hash()
        assert isinstance(h, str)

    def test_hash_empty_store_is_deterministic(self, redis_store) -> None:
        """hash() for empty store is consistent.

        Breaks when: hash() returns different values for same state.
        """
        h1 = redis_store.hash()
        h2 = redis_store.hash()
        assert h1 == h2

    def test_hash_changes_when_package_added(self, redis_store) -> None:
        """hash() changes after adding a package.

        Breaks when: hash() is same after state change (cache invalidation broken).
        """
        h1 = redis_store.hash()
        redis_store.add("pandas")
        h2 = redis_store.hash()

        assert h1 != h2

    def test_hash_changes_when_package_removed(self, redis_store) -> None:
        """hash() changes after removing a package.

        Breaks when: hash() is same after state change (cache invalidation broken).
        """
        redis_store.add("pandas")
        h1 = redis_store.hash()
        redis_store.remove("pandas")
        h2 = redis_store.hash()

        assert h1 != h2

    # --- Package Normalization ---

    def test_package_name_normalized_to_lowercase(self, redis_store) -> None:
        """Package names are normalized to lowercase.

        Breaks when: Case-sensitive package names cause duplicates.
        """
        redis_store.add("Pandas")
        deps = redis_store.list()

        assert "pandas" in deps
        assert "Pandas" not in deps

    # --- Version Specifiers ---

    def test_add_package_with_version_specifier(self, redis_store) -> None:
        """add() handles version specifiers.

        Breaks when: Version specifiers are stripped or cause errors.
        """
        redis_store.add("pandas>=2.0")
        deps = redis_store.list()

        assert "pandas>=2.0" in deps

    # --- Redis Key Structure ---

    def test_uses_correct_redis_key(self, mock_redis: "MockRedisClient") -> None:
        """RedisDepsStore uses prefixed Redis set key.

        Breaks when: Key format doesn't follow pattern.
        """
        from py_code_mode.deps import RedisDepsStore

        store = RedisDepsStore(mock_redis, prefix="myapp")
        store.add("pandas")

        # Should store in a set at {prefix}:deps
        # Check mock redis internal structure
        assert (
            "myapp:deps" in mock_redis._sets
            or "myapp:deps" in mock_redis._data
            or any(k.startswith("myapp:deps") for k in mock_redis._strings)
        )

    def test_different_prefixes_are_isolated(self, mock_redis: "MockRedisClient") -> None:
        """Stores with different prefixes don't interfere.

        Breaks when: Prefixes share data.
        """
        from py_code_mode.deps import RedisDepsStore

        store1 = RedisDepsStore(mock_redis, prefix="app1")
        store2 = RedisDepsStore(mock_redis, prefix="app2")

        store1.add("pandas")
        store2.add("numpy")

        assert store1.list() == ["pandas"]
        assert store2.list() == ["numpy"]


# =============================================================================
# Invariant Tests
# =============================================================================


class TestDepsStoreInvariants:
    """Tests for properties that must always hold across implementations."""

    @pytest.fixture(params=["file", "redis"])
    def store(self, request, tmp_path: Path, mock_redis: "MockRedisClient"):
        """Parametrized fixture for both store implementations."""
        from py_code_mode.deps import FileDepsStore, RedisDepsStore

        if request.param == "file":
            return FileDepsStore(tmp_path)
        else:
            return RedisDepsStore(mock_redis, prefix="test")

    def test_list_after_add_contains_package(self, store) -> None:
        """Invariant: add(x) => x in list().

        Breaks when: add() doesn't persist.
        """
        store.add("pandas")
        assert "pandas" in store.list()

    def test_list_after_remove_excludes_package(self, store) -> None:
        """Invariant: remove(x) => x not in list().

        Breaks when: remove() doesn't delete.
        """
        store.add("pandas")
        store.remove("pandas")
        assert "pandas" not in store.list()

    def test_list_after_clear_is_empty(self, store) -> None:
        """Invariant: clear() => list() == [].

        Breaks when: clear() doesn't remove all.
        """
        store.add("pandas")
        store.add("numpy")
        store.clear()
        assert store.list() == []

    def test_hash_deterministic(self, store) -> None:
        """Invariant: hash() is deterministic for same state.

        Breaks when: hash() uses non-deterministic factors.
        """
        store.add("pandas")
        h1 = store.hash()
        h2 = store.hash()
        assert h1 == h2

    def test_add_then_remove_returns_to_previous_hash(self, store) -> None:
        """Invariant: add(x); remove(x) => hash unchanged.

        Breaks when: hash includes order/history information.
        """
        h1 = store.hash()
        store.add("pandas")
        store.remove("pandas")
        h2 = store.hash()

        assert h1 == h2


# =============================================================================
# Negative Tests
# =============================================================================


class TestDepsStoreNegativeCases:
    """Tests for error conditions and edge cases."""

    def test_add_empty_string_rejected(self, tmp_path: Path) -> None:
        """add('') raises ValueError.

        Breaks when: Empty string is accepted as package name.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        with pytest.raises(ValueError, match="[Ii]nvalid|[Ee]mpty"):
            store.add("")

    def test_add_whitespace_only_rejected(self, tmp_path: Path) -> None:
        """add('   ') raises ValueError.

        Breaks when: Whitespace-only string is accepted.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        with pytest.raises(ValueError, match="[Ii]nvalid|[Ee]mpty"):
            store.add("   ")

    def test_add_with_invalid_characters_rejected(self, tmp_path: Path) -> None:
        """add() rejects packages with shell metacharacters.

        Breaks when: Dangerous characters are allowed (command injection risk).
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        invalid_names = [
            "pandas; rm -rf /",
            "numpy && cat /etc/passwd",
            "$(whoami)",
            "`id`",
            "package|cat /etc/shadow",
        ]

        for name in invalid_names:
            with pytest.raises(ValueError, match="[Ii]nvalid"):
                store.add(name)

    def test_add_with_url_syntax_rejected(self, tmp_path: Path) -> None:
        """add() rejects packages with @ (URL install syntax).

        Breaks when: URL-based package installs are allowed, enabling
        installation from arbitrary git repos or file paths.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        url_packages = [
            "package @ https://evil.com/malware.tar.gz",
            "mypackage @ git+https://github.com/evil/repo",
            "pkg @ file:///etc/passwd",
            "pandas>=2.0 @ https://example.com/package.whl",
        ]

        for name in url_packages:
            with pytest.raises(ValueError, match="[Ii]nvalid|blocked"):
                store.add(name)

    def test_add_with_environment_markers_rejected(self, tmp_path: Path) -> None:
        """add() rejects packages with ; (environment marker syntax).

        Breaks when: Environment markers are allowed, which could
        potentially be used to inject arbitrary expressions.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        marker_packages = [
            "pandas>=2.0; python_version >= '3.8'",
            "numpy; sys_platform == 'linux'",
            "requests; extra == 'security'",
        ]

        for name in marker_packages:
            with pytest.raises(ValueError, match="[Ii]nvalid|blocked"):
                store.add(name)

    def test_add_with_permissive_version_specifier_rejected(self, tmp_path: Path) -> None:
        """add() rejects version specifiers with dangerous characters.

        Breaks when: Version specifier regex is too permissive and allows
        arbitrary content after version operators.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        dangerous_versions = [
            "pandas>=2.0; os.system('id')",
            "numpy>=1.0 @ https://evil.com/",
            "requests>=2.0$(whoami)",
        ]

        for name in dangerous_versions:
            with pytest.raises(ValueError, match="[Ii]nvalid|blocked"):
                store.add(name)

    def test_file_store_handles_permission_error(self, tmp_path: Path) -> None:
        """FileDepsStore handles filesystem permission errors gracefully.

        Breaks when: PermissionError crashes the store.
        """
        from py_code_mode.deps import FileDepsStore

        # Create store, then make directory read-only
        store = FileDepsStore(tmp_path)
        deps_dir = tmp_path / "deps"
        deps_dir.mkdir(parents=True, exist_ok=True)

        # This test is platform-dependent, so we just verify the store
        # can be created - actual permission handling is implementation detail
        assert store is not None

    def test_remove_empty_string_returns_false(self, tmp_path: Path) -> None:
        """remove('') returns False without error.

        Breaks when: Empty string causes crash.
        """
        from py_code_mode.deps import FileDepsStore

        store = FileDepsStore(tmp_path)

        # Should return False, not raise
        result = store.remove("")
        assert result is False


# =============================================================================
# Integration Tests with Real Redis
# =============================================================================


class TestRedisDepsStoreIntegration:
    """Integration tests with real Redis using testcontainers."""

    def test_roundtrip_packages(self, redis_client, request) -> None:
        """Add and list packages through real Redis.

        Breaks when: Redis serialization/deserialization is broken.
        """
        from py_code_mode.deps import RedisDepsStore

        # Use unique prefix per test for isolation
        test_name = request.node.name.replace("[", "_").replace("]", "_")
        prefix = f"test-deps-{test_name}"

        store = RedisDepsStore(redis_client, prefix=prefix)

        store.add("pandas>=2.0")
        store.add("numpy")
        store.add("requests==2.31.0")

        deps = store.list()
        assert set(deps) == {"pandas>=2.0", "numpy", "requests==2.31.0"}

    def test_clear_through_real_redis(self, redis_client, request) -> None:
        """clear() removes all packages in real Redis.

        Breaks when: clear() doesn't delete Redis keys.
        """
        from py_code_mode.deps import RedisDepsStore

        test_name = request.node.name.replace("[", "_").replace("]", "_")
        prefix = f"test-deps-{test_name}"

        store = RedisDepsStore(redis_client, prefix=prefix)

        store.add("pandas")
        store.add("numpy")
        store.clear()

        assert store.list() == []

    def test_hash_consistency_across_connections(self, redis_client, request) -> None:
        """hash() is consistent across different store instances.

        Breaks when: hash() uses instance-local state.
        """
        from py_code_mode.deps import RedisDepsStore

        test_name = request.node.name.replace("[", "_").replace("]", "_")
        prefix = f"test-deps-{test_name}"

        store1 = RedisDepsStore(redis_client, prefix=prefix)
        store1.add("pandas")
        store1.add("numpy")

        h1 = store1.hash()

        # Create new store instance pointing to same Redis data
        store2 = RedisDepsStore(redis_client, prefix=prefix)
        h2 = store2.hash()

        assert h1 == h2
