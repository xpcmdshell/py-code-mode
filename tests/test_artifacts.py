"""Tests for artifacts system - written first to define interface."""

import json
from pathlib import Path

import pytest

from py_code_mode.artifacts import FileArtifactStore


class TestArtifactDataclass:
    """Tests that define the Artifact metadata structure."""

    def test_artifact_has_required_fields(self) -> None:
        """Artifact has name, path, description."""
        from py_code_mode.artifacts import Artifact

        artifact = Artifact(
            name="scan_results.json",
            path="/tmp/artifacts/scan_results.json",
            description="Nmap scan of 10.0.0.0/24",
        )

        assert artifact.name == "scan_results.json"
        assert artifact.path == "/tmp/artifacts/scan_results.json"
        assert artifact.description == "Nmap scan of 10.0.0.0/24"

    def test_artifact_optional_metadata(self) -> None:
        """Artifact can have optional metadata dict."""
        from py_code_mode.artifacts import Artifact

        artifact = Artifact(
            name="hosts.txt",
            path="/tmp/artifacts/hosts.txt",
            description="Discovered hosts",
            metadata={"count": 42, "source": "nmap"},
        )

        assert artifact.metadata["count"] == 42

    def test_artifact_created_timestamp(self) -> None:
        """Artifact tracks creation time."""
        from py_code_mode.artifacts import Artifact

        artifact = Artifact(
            name="test.json",
            path="/tmp/test.json",
            description="Test",
        )

        assert artifact.created_at is not None


class TestArtifactStore:
    """Tests for ArtifactStore - file storage with metadata."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        """Create a store with temp directory."""
        return FileArtifactStore(tmp_path)

    def test_store_has_path(self, store, tmp_path: Path) -> None:
        """Store exposes its base path as string."""
        assert store.path == str(tmp_path)

    def test_save_creates_file(self, store) -> None:
        """save() writes data to file."""
        store.save("test.txt", "hello world", description="Test file")

        assert (store.path_obj / "test.txt").exists()
        assert (store.path_obj / "test.txt").read_text() == "hello world"

    def test_save_json_data(self, store) -> None:
        """save() serializes dicts/lists as JSON."""
        data = {"hosts": ["10.0.0.1", "10.0.0.2"], "count": 2}
        store.save("hosts.json", data, description="Host list")

        content = json.loads((store.path_obj / "hosts.json").read_text())
        assert content == data

    def test_save_bytes(self, store) -> None:
        """save() handles binary data."""
        data = b"\x89PNG\r\n\x1a\n"
        store.save("image.png", data, description="Screenshot")

        assert (store.path_obj / "image.png").read_bytes() == data

    def test_save_updates_index(self, store) -> None:
        """save() updates metadata index."""
        store.save("test.json", {"x": 1}, description="Test data")

        # Index file should exist
        index_path = store.path_obj / ".artifacts.json"
        assert index_path.exists()

        index = json.loads(index_path.read_text())
        assert "test.json" in index
        assert index["test.json"]["description"] == "Test data"

    def test_load_reads_file(self, store) -> None:
        """load() reads file content."""
        store.save("data.json", {"key": "value"}, description="Test")

        data = store.load("data.json")

        assert data == {"key": "value"}

    def test_load_text_file(self, store) -> None:
        """load() reads text files as strings."""
        store.save("notes.txt", "some notes", description="Notes")

        data = store.load("notes.txt")

        assert data == "some notes"

    def test_load_not_found(self, store) -> None:
        """load() raises for missing artifact."""
        from py_code_mode.errors import ArtifactNotFoundError

        with pytest.raises(ArtifactNotFoundError):
            store.load("nonexistent.json")

    def test_list_returns_artifacts(self, store) -> None:
        """list() returns Artifact objects with metadata."""
        store.save("a.json", {}, description="First")
        store.save("b.json", {}, description="Second")

        artifacts = store.list()

        assert len(artifacts) == 2
        names = {a.name for a in artifacts}
        assert names == {"a.json", "b.json"}

    def test_list_includes_descriptions(self, store) -> None:
        """list() includes descriptions from index."""
        store.save("scan.json", {}, description="Network scan results")

        artifacts = store.list()

        assert artifacts[0].description == "Network scan results"

    def test_list_empty_store(self, store) -> None:
        """list() returns empty for new store."""
        assert store.list() == []

    def test_get_returns_single_artifact(self, store) -> None:
        """get() returns single Artifact by name."""
        store.save("target.json", {"ip": "10.0.0.1"}, description="Target info")

        artifact = store.get("target.json")

        assert artifact is not None
        assert artifact.name == "target.json"
        assert artifact.description == "Target info"

    def test_get_not_found(self, store) -> None:
        """get() returns None for missing artifact."""
        assert store.get("missing.json") is None

    def test_exists(self, store) -> None:
        """exists() checks if artifact exists."""
        store.save("present.json", {}, description="Here")

        assert store.exists("present.json") is True
        assert store.exists("missing.json") is False

    def test_delete_removes_file_and_index(self, store) -> None:
        """delete() removes file and index entry."""
        store.save("temp.json", {}, description="Temporary")

        store.delete("temp.json")

        assert not (store.path_obj / "temp.json").exists()
        assert store.get("temp.json") is None

    def test_save_with_metadata(self, store) -> None:
        """save() accepts additional metadata."""
        store.save(
            "results.json",
            {"data": []},
            description="Scan results",
            metadata={"tool": "nmap", "duration_sec": 120},
        )

        artifact = store.get("results.json")
        assert artifact.metadata["tool"] == "nmap"


class TestArtifactStoreFileAccess:
    """Tests for raw file access patterns."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        return FileArtifactStore(tmp_path)

    def test_path_property_for_raw_access(self, store) -> None:
        """Can use store.path_obj for standard file I/O."""
        store.save("data.txt", "content", description="Test")

        # Raw file access still works via path_obj
        with open(store.path_obj / "data.txt") as f:
            assert f.read() == "content"

    def test_external_file_not_in_index(self, store) -> None:
        """Files created externally aren't in index."""
        # Write file directly, bypassing store
        (store.path_obj / "external.txt").write_text("external data")

        # Not in index
        assert store.get("external.txt") is None

        # But list_files() could find it
        all_files = list(store.path_obj.glob("*"))
        assert any(f.name == "external.txt" for f in all_files)

    def test_register_external_file(self, store) -> None:
        """Can register externally created files."""
        # Write file directly
        (store.path_obj / "external.json").write_text('{"x": 1}')

        # Register it
        store.register("external.json", description="Externally created")

        artifact = store.get("external.json")
        assert artifact is not None
        assert artifact.description == "Externally created"


class TestArtifactStoreSubdirectories:
    """Tests for organizing artifacts in subdirectories."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        return FileArtifactStore(tmp_path)

    def test_save_with_subdirectory(self, store) -> None:
        """save() creates subdirectories as needed."""
        store.save("scans/nmap/results.json", {"hosts": []}, description="Nmap scan")

        assert (store.path_obj / "scans" / "nmap" / "results.json").exists()

    def test_list_includes_subdirectory_artifacts(self, store) -> None:
        """list() includes artifacts in subdirectories."""
        store.save("root.json", {}, description="Root level")
        store.save("sub/nested.json", {}, description="Nested")

        artifacts = store.list()

        names = {a.name for a in artifacts}
        assert "root.json" in names
        assert "sub/nested.json" in names

    def test_load_from_subdirectory(self, store) -> None:
        """load() works with subdirectory paths."""
        store.save("deep/path/data.json", {"nested": True}, description="Deep")

        data = store.load("deep/path/data.json")

        assert data == {"nested": True}
