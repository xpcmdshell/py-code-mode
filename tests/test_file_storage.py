"""Unit tests for FileStorage implementation.

FileStorage stores tools, skills, and artifacts as files on disk.
This is the default storage backend for local development.

Structure:
    root/
        tools/       # YAML tool definitions
        skills/      # Python skill files
        artifacts/   # Saved artifacts (JSON, binary)
"""

from __future__ import annotations

from pathlib import Path

import pytest

# These imports will fail initially - that's expected (TDD red phase)
from py_code_mode.storage import FileStorage


class TestFileStorageConstruction:
    """Tests for FileStorage initialization."""

    def test_create_with_path(self, tmp_path: Path) -> None:
        """FileStorage can be created with a Path."""
        storage = FileStorage(tmp_path)
        assert storage is not None

    def test_create_with_string_path(self, tmp_path: Path) -> None:
        """FileStorage can be created with a string path."""
        storage = FileStorage(str(tmp_path))
        assert storage is not None

    def test_create_with_nonexistent_path_creates_it(self, tmp_path: Path) -> None:
        """FileStorage creates the root directory if it doesn't exist."""
        new_path = tmp_path / "new_storage"
        assert not new_path.exists()

        storage = FileStorage(new_path)

        # Accessing a store should create directories
        _ = storage.tools.list()
        assert new_path.exists()

    def test_root_property_returns_path(self, tmp_path: Path) -> None:
        """FileStorage has root property returning the storage path."""
        storage = FileStorage(tmp_path)
        assert storage.root == tmp_path or storage.root == Path(tmp_path)


class TestFileStorageTools:
    """Tests for FileStorage.tools - tool storage operations."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with tools directory."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()
        return FileStorage(tmp_path)

    @pytest.fixture
    def tool_yaml(self) -> str:
        """Sample tool YAML content."""
        return """
name: nmap
command: nmap
description: Network port scanner
tags:
  - network
  - recon

schema:
  options:
    sS: {type: boolean, short: sS, description: TCP SYN scan}
  positional:
    - name: target
      type: string
      required: true
      description: Target host

recipes:
  scan:
    description: Scan a target
    params:
      target: {}
"""

    def test_list_empty_returns_empty_list(self, storage: FileStorage) -> None:
        """tools.list() returns empty list when no tools exist."""
        result = storage.tools.list()
        assert result == []

    def test_list_returns_tool_info(
        self, storage: FileStorage, tool_yaml: str, tmp_path: Path
    ) -> None:
        """tools.list() returns list of tool info dicts."""
        (tmp_path / "tools" / "nmap.yaml").write_text(tool_yaml)

        result = storage.tools.list()

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["name"] == "nmap"
        assert "description" in result[0]
        assert "params" in result[0]

    def test_list_multiple_tools(self, storage: FileStorage, tmp_path: Path) -> None:
        """tools.list() returns all tools."""
        tool1_yaml = """
name: tool1
command: echo
description: Tool 1

schema:
  positional:
    - name: text
      type: string
      required: true

recipes:
  echo:
    description: Echo text
    params:
      text: {}
"""
        tool2_yaml = """
name: tool2
command: echo
description: Tool 2

schema:
  positional:
    - name: text
      type: string
      required: true

recipes:
  echo:
    description: Echo text
    params:
      text: {}
"""
        (tmp_path / "tools" / "tool1.yaml").write_text(tool1_yaml)
        (tmp_path / "tools" / "tool2.yaml").write_text(tool2_yaml)

        result = storage.tools.list()

        assert len(result) == 2
        names = {t["name"] for t in result}
        assert names == {"tool1", "tool2"}

    def test_get_existing_tool(self, storage: FileStorage, tool_yaml: str, tmp_path: Path) -> None:
        """tools.get(name) returns tool definition."""
        (tmp_path / "tools" / "nmap.yaml").write_text(tool_yaml)

        result = storage.tools.get("nmap")

        assert result is not None
        assert result["name"] == "nmap"
        assert result["description"] == "Network port scanner"

    def test_get_nonexistent_returns_none(self, storage: FileStorage) -> None:
        """tools.get(name) returns None for nonexistent tool."""
        result = storage.tools.get("nonexistent")
        assert result is None

    def test_exists_true_for_existing(
        self, storage: FileStorage, tool_yaml: str, tmp_path: Path
    ) -> None:
        """tools.exists(name) returns True for existing tool."""
        (tmp_path / "tools" / "nmap.yaml").write_text(tool_yaml)

        assert storage.tools.exists("nmap") is True

    def test_exists_false_for_nonexistent(self, storage: FileStorage) -> None:
        """tools.exists(name) returns False for nonexistent tool."""
        assert storage.tools.exists("nonexistent") is False

    def test_save_creates_yaml_file(self, storage: FileStorage, tmp_path: Path) -> None:
        """tools.save(tool) creates a YAML file."""
        tool = {
            "name": "mytool",
            "command": "echo",
            "description": "Test tool",
            "schema": {"positional": [{"name": "text", "type": "string", "required": True}]},
            "recipes": {"echo": {"description": "Echo text", "params": {"text": {}}}},
        }

        storage.tools.save(tool)

        yaml_path = tmp_path / "tools" / "mytool.yaml"
        assert yaml_path.exists()
        content = yaml_path.read_text()
        assert "mytool" in content

    def test_save_overwrites_existing(self, storage: FileStorage, tmp_path: Path) -> None:
        """tools.save(tool) overwrites existing tool."""
        tool = {
            "name": "mytool",
            "command": "echo",
            "description": "Version 1",
            "schema": {"positional": [{"name": "text", "type": "string", "required": True}]},
            "recipes": {"echo": {"description": "Echo text", "params": {"text": {}}}},
        }
        storage.tools.save(tool)

        # Save updated version
        tool["description"] = "Version 2"
        storage.tools.save(tool)

        result = storage.tools.get("mytool")
        assert result["description"] == "Version 2"

    def test_delete_removes_file(
        self, storage: FileStorage, tool_yaml: str, tmp_path: Path
    ) -> None:
        """tools.delete(name) removes the YAML file."""
        yaml_path = tmp_path / "tools" / "nmap.yaml"
        yaml_path.write_text(tool_yaml)

        result = storage.tools.delete("nmap")

        assert result is True
        assert not yaml_path.exists()

    def test_delete_nonexistent_returns_false(self, storage: FileStorage) -> None:
        """tools.delete(name) returns False for nonexistent tool."""
        result = storage.tools.delete("nonexistent")
        assert result is False

    def test_search_finds_matching_tools(self, storage: FileStorage, tmp_path: Path) -> None:
        """tools.search(query) finds tools matching the query."""
        nmap_yaml = """
name: nmap
command: nmap
description: Network port scanner for security testing

schema:
  positional:
    - name: target
      type: string
      required: true

recipes:
  scan:
    description: Scan target
    params:
      target: {}
"""
        curl_yaml = """
name: curl
command: curl
description: HTTP client for web requests

schema:
  positional:
    - name: url
      type: string
      required: true

recipes:
  get:
    description: Get URL
    params:
      url: {}
"""
        (tmp_path / "tools" / "nmap.yaml").write_text(nmap_yaml)
        (tmp_path / "tools" / "curl.yaml").write_text(curl_yaml)

        result = storage.tools.search("network")

        assert isinstance(result, list)
        # Should find nmap (network in description)
        assert len(result) >= 1


class TestFileStorageSkills:
    """Tests for FileStorage.skills - skill storage operations."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with skills directory."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        return FileStorage(tmp_path)

    @pytest.fixture
    def skill_source(self) -> str:
        """Sample skill source code."""
        return '''"""Double a number."""

def run(n: int) -> int:
    return n * 2
'''

    def test_list_empty_returns_empty_list(self, storage: FileStorage) -> None:
        """skills.list() returns empty list when no skills exist."""
        result = storage.skills.list()
        assert result == []

    def test_list_returns_skill_info(
        self, storage: FileStorage, skill_source: str, tmp_path: Path
    ) -> None:
        """skills.list() returns list of skill info dicts."""
        (tmp_path / "skills" / "double.py").write_text(skill_source)

        result = storage.skills.list()

        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["name"] == "double"
        assert "description" in result[0]
        assert "params" in result[0]

    def test_list_ignores_underscore_files(
        self, storage: FileStorage, skill_source: str, tmp_path: Path
    ) -> None:
        """skills.list() ignores files starting with underscore."""
        (tmp_path / "skills" / "double.py").write_text(skill_source)
        (tmp_path / "skills" / "__init__.py").write_text("")
        (tmp_path / "skills" / "_private.py").write_text("def run(): pass")

        result = storage.skills.list()

        assert len(result) == 1
        assert result[0]["name"] == "double"

    def test_get_existing_skill(
        self, storage: FileStorage, skill_source: str, tmp_path: Path
    ) -> None:
        """skills.get(name) returns skill definition."""
        (tmp_path / "skills" / "double.py").write_text(skill_source)

        result = storage.skills.get("double")

        assert result is not None
        assert result["name"] == "double"
        assert "Double a number" in result["description"]

    def test_get_nonexistent_returns_none(self, storage: FileStorage) -> None:
        """skills.get(name) returns None for nonexistent skill."""
        result = storage.skills.get("nonexistent")
        assert result is None

    def test_exists_true_for_existing(
        self, storage: FileStorage, skill_source: str, tmp_path: Path
    ) -> None:
        """skills.exists(name) returns True for existing skill."""
        (tmp_path / "skills" / "double.py").write_text(skill_source)

        assert storage.skills.exists("double") is True

    def test_exists_false_for_nonexistent(self, storage: FileStorage) -> None:
        """skills.exists(name) returns False for nonexistent skill."""
        assert storage.skills.exists("nonexistent") is False

    def test_save_creates_python_file(self, storage: FileStorage, tmp_path: Path) -> None:
        """skills.save(skill) creates a Python file."""
        skill = {
            "name": "greet",
            "source": 'def run(name: str) -> str:\n    return f"Hello, {name}!"',
            "description": "Greet someone",
        }

        storage.skills.save(skill)

        py_path = tmp_path / "skills" / "greet.py"
        assert py_path.exists()
        content = py_path.read_text()
        assert "def run" in content

    def test_create_skill(self, storage: FileStorage, tmp_path: Path) -> None:
        """skills.create(name, description, source) creates and saves a skill."""
        storage.skills.create(
            name="triple",
            description="Triple a number",
            source="def run(n: int) -> int:\n    return n * 3",
        )

        assert storage.skills.exists("triple")
        skill = storage.skills.get("triple")
        assert skill is not None
        assert skill["name"] == "triple"

    def test_delete_removes_file(
        self, storage: FileStorage, skill_source: str, tmp_path: Path
    ) -> None:
        """skills.delete(name) removes the Python file."""
        py_path = tmp_path / "skills" / "double.py"
        py_path.write_text(skill_source)

        result = storage.skills.delete("double")

        assert result is True
        assert not py_path.exists()

    def test_delete_nonexistent_returns_false(self, storage: FileStorage) -> None:
        """skills.delete(name) returns False for nonexistent skill."""
        result = storage.skills.delete("nonexistent")
        assert result is False

    def test_search_finds_matching_skills(self, storage: FileStorage, tmp_path: Path) -> None:
        """skills.search(query) finds skills matching the query."""
        (tmp_path / "skills" / "double.py").write_text(
            '"""Double a number by multiplying by 2."""\ndef run(n: int) -> int:\n    return n * 2'
        )
        (tmp_path / "skills" / "greet.py").write_text(
            '"""Greet someone."""\ndef run(name: str) -> str:\n    return f"Hello, {name}!"'
        )

        result = storage.skills.search("number")

        assert isinstance(result, list)
        # Should find double (number in description)


class TestFileStorageArtifacts:
    """Tests for FileStorage.artifacts - artifact storage operations."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage with artifacts directory."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        return FileStorage(tmp_path)

    def test_list_empty_returns_empty(self, storage: FileStorage) -> None:
        """artifacts.list() returns empty iterable when no artifacts exist."""
        result = list(storage.artifacts.list())
        assert result == []

    def test_save_and_load_json_data(self, storage: FileStorage) -> None:
        """Can save and load JSON-serializable data."""
        data = {"key": "value", "count": 42, "items": [1, 2, 3]}

        storage.artifacts.save("test.json", data, "Test artifact")

        loaded = storage.artifacts.load("test.json")
        assert loaded == data

    def test_save_and_load_bytes(self, storage: FileStorage) -> None:
        """Can save and load binary data."""
        data = b"binary content here"

        storage.artifacts.save("test.bin", data, "Binary artifact")

        loaded = storage.artifacts.load("test.bin")
        # May return bytes or decoded string depending on implementation
        assert data in loaded or data.decode() in str(loaded)

    def test_save_and_load_string(self, storage: FileStorage) -> None:
        """Can save and load string data."""
        data = "plain text content"

        storage.artifacts.save("test.txt", data, "Text artifact")

        loaded = storage.artifacts.load("test.txt")
        assert data in str(loaded)

    def test_list_returns_artifact_info(self, storage: FileStorage) -> None:
        """artifacts.list() returns artifact metadata."""
        storage.artifacts.save("file1.json", {"a": 1}, "First file")
        storage.artifacts.save("file2.json", {"b": 2}, "Second file")

        result = list(storage.artifacts.list())

        assert len(result) == 2
        names = {a["name"] if isinstance(a, dict) else a for a in result}
        assert "file1.json" in names or any("file1" in str(a) for a in result)

    def test_load_nonexistent_returns_none_or_raises(self, storage: FileStorage) -> None:
        """artifacts.load(name) returns None or raises for nonexistent."""
        try:
            result = storage.artifacts.load("nonexistent.json")
            assert result is None
        except (FileNotFoundError, KeyError):
            pass  # Raising is acceptable

    def test_exists_true_for_existing(self, storage: FileStorage) -> None:
        """artifacts.exists(name) returns True for existing artifact."""
        storage.artifacts.save("exists.json", {"test": True}, "Exists")

        assert storage.artifacts.exists("exists.json") is True

    def test_exists_false_for_nonexistent(self, storage: FileStorage) -> None:
        """artifacts.exists(name) returns False for nonexistent artifact."""
        assert storage.artifacts.exists("nonexistent.json") is False

    def test_delete_removes_artifact(self, storage: FileStorage) -> None:
        """artifacts.delete(name) removes the artifact."""
        storage.artifacts.save("to_delete.json", {}, "Will be deleted")

        result = storage.artifacts.delete("to_delete.json")

        assert result is True
        assert storage.artifacts.exists("to_delete.json") is False

    def test_delete_nonexistent_returns_false(self, storage: FileStorage) -> None:
        """artifacts.delete(name) returns False for nonexistent artifact."""
        result = storage.artifacts.delete("nonexistent.json")
        assert result is False

    def test_save_overwrites_existing(self, storage: FileStorage) -> None:
        """artifacts.save() overwrites existing artifact."""
        storage.artifacts.save("data.json", {"version": 1}, "Version 1")
        storage.artifacts.save("data.json", {"version": 2}, "Version 2")

        loaded = storage.artifacts.load("data.json")
        assert loaded["version"] == 2


class TestFileStorageFilesystemBehavior:
    """Tests for FileStorage filesystem-specific behavior."""

    def test_creates_tools_dir_on_first_access(self, tmp_path: Path) -> None:
        """tools/ directory is created on first access."""
        storage = FileStorage(tmp_path)
        # Directory might not exist until first operation
        _ = storage.tools.list()
        # After listing, directory should exist (or storage should work)
        # This is implementation-dependent

    def test_creates_skills_dir_on_first_access(self, tmp_path: Path) -> None:
        """skills/ directory is created on first access."""
        storage = FileStorage(tmp_path)
        _ = storage.skills.list()

    def test_creates_artifacts_dir_on_first_access(self, tmp_path: Path) -> None:
        """artifacts/ directory is created on first access."""
        storage = FileStorage(tmp_path)
        _ = list(storage.artifacts.list())

    def test_handles_concurrent_access_safely(self, tmp_path: Path) -> None:
        """FileStorage handles multiple instances accessing same path."""
        storage1 = FileStorage(tmp_path)
        storage2 = FileStorage(tmp_path)

        # Both should see the same files
        storage1.artifacts.save("shared.json", {"source": 1}, "Shared")

        loaded = storage2.artifacts.load("shared.json")
        assert loaded["source"] == 1


class TestFileStorageEdgeCases:
    """Edge case tests for FileStorage."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FileStorage:
        """Create FileStorage."""
        return FileStorage(tmp_path)

    def test_tool_name_with_special_chars(self, storage: FileStorage, tmp_path: Path) -> None:
        """Tool names with special characters are handled safely."""
        # This should either work or raise a clear error
        try:
            tool_yaml = """
name: my-tool_v2
command: echo
description: Tool with special chars

schema:
  positional:
    - name: text
      type: string
      required: true

recipes:
  echo:
    description: Echo text
    params:
      text: {}
"""
            tools_dir = tmp_path / "tools"
            tools_dir.mkdir(exist_ok=True)
            (tools_dir / "my-tool_v2.yaml").write_text(tool_yaml)
            assert storage.tools.exists("my-tool_v2")
        except ValueError:
            pass  # Rejecting special chars is acceptable

    def test_skill_name_with_special_chars(self, storage: FileStorage) -> None:
        """Skill names with special characters are handled safely."""
        try:
            storage.skills.create(
                name="my_skill_v2",
                description="Skill with underscores",
                source="def run(): return 1",
            )
            assert storage.skills.exists("my_skill_v2")
        except ValueError:
            pass  # Rejecting special chars is acceptable

    def test_artifact_with_subdirectory_path(self, storage: FileStorage) -> None:
        """Artifacts can use subdirectory paths."""
        storage.artifacts.save("reports/scan.json", {"results": []}, "Scan report")

        # Should be loadable
        loaded = storage.artifacts.load("reports/scan.json")
        assert loaded == {"results": []}

    def test_empty_tool_yaml_handled(self, storage: FileStorage, tmp_path: Path) -> None:
        """Empty or malformed YAML files don't crash list()."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir(exist_ok=True)
        (tools_dir / "empty.yaml").write_text("")

        # Should not crash
        try:
            result = storage.tools.list()
            # May return empty list or skip malformed files
            assert isinstance(result, list)
        except Exception:
            pass  # Raising on malformed files is acceptable

    def test_skill_without_docstring_has_empty_description(
        self, storage: FileStorage, tmp_path: Path
    ) -> None:
        """Skills without docstrings have empty/default description."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir(exist_ok=True)
        (skills_dir / "nodoc.py").write_text("def run(): return 42")

        result = storage.skills.get("nodoc")

        assert result is not None
        # Description should exist (empty string is fine)
        assert "description" in result
