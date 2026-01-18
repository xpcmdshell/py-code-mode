"""Tests for workflow store CLI module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from py_code_mode.workflows import PythonWorkflow


def _make_workflow(name: str, description: str, source: str) -> PythonWorkflow:
    """Helper to create a PythonWorkflow."""
    full_source = f'"""{description}"""\n\n{source}'
    return PythonWorkflow.from_source(name=name, source=full_source, description=description)


class TestGetStore:
    """Test _get_store factory function."""

    def test_redis_scheme_creates_redis_store(self) -> None:
        """redis:// scheme creates RedisWorkflowStore."""
        from py_code_mode.cli.store import _get_store

        with patch("py_code_mode.cli.store.redis_lib") as mock_redis_lib:
            mock_client = MagicMock()
            mock_redis_lib.from_url.return_value = mock_client

            store = _get_store("redis://localhost:6379", prefix="test")

            mock_redis_lib.from_url.assert_called_once_with("redis://localhost:6379")
            assert store is not None

    def test_rediss_scheme_creates_redis_store(self) -> None:
        """rediss:// (TLS) scheme creates RedisWorkflowStore."""
        from py_code_mode.cli.store import _get_store

        with patch("py_code_mode.cli.store.redis_lib") as mock_redis_lib:
            mock_client = MagicMock()
            mock_redis_lib.from_url.return_value = mock_client

            _get_store("rediss://localhost:6380", prefix="test")

            mock_redis_lib.from_url.assert_called_once_with("rediss://localhost:6380")

    def test_unknown_scheme_raises_valueerror(self) -> None:
        """Unknown scheme raises ValueError."""
        from py_code_mode.cli.store import _get_store

        with pytest.raises(ValueError, match="Unknown scheme"):
            _get_store("unknown://localhost", prefix="test")

    def test_s3_scheme_not_implemented(self) -> None:
        """s3:// scheme raises NotImplementedError."""
        from py_code_mode.cli.store import _get_store

        with pytest.raises(NotImplementedError, match="S3"):
            _get_store("s3://bucket/path", prefix="test")

    def test_cosmos_scheme_not_implemented(self) -> None:
        """cosmos:// scheme raises NotImplementedError."""
        from py_code_mode.cli.store import _get_store

        with pytest.raises(NotImplementedError, match="Cosmos"):
            _get_store("cosmos://account.documents.azure.com", prefix="test")


class TestWorkflowHash:
    """Test _workflow_hash function."""

    def test_same_workflow_same_hash(self) -> None:
        """Same workflow content produces same hash."""
        from py_code_mode.cli.store import _workflow_hash

        workflow = _make_workflow("test", "Test workflow", "async def run():\n    return 'hello'")

        hash1 = _workflow_hash(workflow)
        hash2 = _workflow_hash(workflow)
        assert hash1 == hash2

    def test_different_content_different_hash(self) -> None:
        """Different workflow content produces different hash."""
        from py_code_mode.cli.store import _workflow_hash

        workflow1 = _make_workflow("test", "Desc 1", "async def run(): return 1")
        workflow2 = _make_workflow("test", "Desc 2", "async def run(): return 1")

        assert _workflow_hash(workflow1) != _workflow_hash(workflow2)

    def test_hash_is_short(self) -> None:
        """Hash is truncated to 12 characters."""
        from py_code_mode.cli.store import _workflow_hash

        workflow = _make_workflow("test", "desc", "async def run(): pass")
        assert len(_workflow_hash(workflow)) == 12


class TestBootstrap:
    """Test bootstrap command."""

    def test_bootstrap_loads_workflows_from_directory(self, tmp_path: Path) -> None:
        """Bootstrap loads workflows from source directory."""
        from py_code_mode.cli.store import bootstrap

        # Create test workflow
        workflow_file = tmp_path / "my_workflow.py"
        workflow_file.write_text('''"""My test workflow."""

async def run(x: int) -> int:
    """Double a number."""
    return x * 2
''')

        # Mock store
        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            count = bootstrap(tmp_path, "redis://localhost", "test-prefix")

        assert count == 1
        # Uses batch save when available (RedisWorkflowStore)
        mock_store.save_batch.assert_called_once()

    def test_bootstrap_with_clear_removes_existing(self, tmp_path: Path) -> None:
        """Bootstrap with clear=True removes existing workflows first."""
        from py_code_mode.cli.store import bootstrap

        # Create test workflow
        workflow_file = tmp_path / "new_workflow.py"
        workflow_file.write_text('"""New workflow."""\nasync def run() -> str:\n    return "new"')

        # Mock store with existing workflow
        mock_store = MagicMock()
        existing_workflow = _make_workflow("old_workflow", "Old", "async def run(): pass")
        mock_store.list_all.return_value = [existing_workflow]

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            bootstrap(tmp_path, "redis://localhost", "test-prefix", clear=True)

        # Should have deleted old workflow
        mock_store.delete.assert_called_once_with("old_workflow")

    def test_bootstrap_returns_count(self, tmp_path: Path) -> None:
        """Bootstrap returns number of workflows added."""
        from py_code_mode.cli.store import bootstrap

        # Create multiple workflows
        (tmp_path / "workflow1.py").write_text('"""S1."""\nasync def run(): return 1')
        (tmp_path / "workflow2.py").write_text('"""S2."""\nasync def run(): return 2')

        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            count = bootstrap(tmp_path, "redis://localhost", "test-prefix")

        assert count == 2


class TestPull:
    """Test pull command."""

    def test_pull_writes_workflows_to_files(self, tmp_path: Path) -> None:
        """Pull writes workflows to destination directory."""
        from py_code_mode.cli.store import pull

        dest = tmp_path / "pulled"

        # Mock store with workflows
        mock_store = MagicMock()
        workflow = MagicMock()
        workflow.name = "workflow1"
        workflow.description = "First workflow"
        workflow.source = '"""First workflow."""\nasync def run():\n    print("one")'
        mock_store.list_all.return_value = [workflow]

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            count = pull("redis://localhost", "test-prefix", dest)

        assert count == 1
        assert dest.exists()
        assert (dest / "workflow1.py").exists()

    def test_pull_creates_destination_directory(self, tmp_path: Path) -> None:
        """Pull creates destination directory if it doesn't exist."""
        from py_code_mode.cli.store import pull

        dest = tmp_path / "new" / "nested" / "dir"
        assert not dest.exists()

        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            pull("redis://localhost", "test-prefix", dest)

        assert dest.exists()


class TestDiff:
    """Test diff command."""

    def test_diff_finds_added_workflows(self, tmp_path: Path) -> None:
        """Diff identifies workflows only in remote (agent-created)."""
        from py_code_mode.cli.store import diff

        # Empty local directory
        local = tmp_path / "local"
        local.mkdir()

        # Remote has a workflow
        mock_store = MagicMock()
        remote_workflow = MagicMock()
        remote_workflow.name = "agent_created"
        remote_workflow.description = "Created by agent"
        remote_workflow.source = '"""Created by agent."""\nasync def run(): pass'
        mock_store.list_all.return_value = [remote_workflow]

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "agent_created" in result["added"]
        assert len(result["removed"]) == 0
        assert len(result["modified"]) == 0

    def test_diff_finds_removed_workflows(self, tmp_path: Path) -> None:
        """Diff identifies workflows only in local (removed from remote)."""
        from py_code_mode.cli.store import diff

        # Local has a workflow
        local = tmp_path / "local"
        local.mkdir()
        (local / "local_only.py").write_text('"""Local workflow."""\nasync def run(): pass')

        # Remote is empty
        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "local_only" in result["removed"]
        assert len(result["added"]) == 0

    def test_diff_finds_modified_workflows(self, tmp_path: Path) -> None:
        """Diff identifies workflows with different content."""
        from py_code_mode.cli.store import diff

        local = tmp_path / "local"
        local.mkdir()
        local_workflow = '"""Local version."""\nasync def run(): return "local"'
        (local / "shared_workflow.py").write_text(local_workflow)

        # Remote has different version
        mock_store = MagicMock()
        remote_workflow = MagicMock()
        remote_workflow.name = "shared_workflow"
        remote_workflow.description = "Remote version"
        remote_workflow.source = '"""Remote version."""\nasync def run(): return "remote"'
        mock_store.list_all.return_value = [remote_workflow]

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "shared_workflow" in result["modified"]

    def test_diff_finds_unchanged_workflows(self, tmp_path: Path) -> None:
        """Diff identifies identical workflows."""
        from py_code_mode.cli.store import diff

        # Local workflow
        local = tmp_path / "local"
        local.mkdir()
        workflow_content = '"""Same workflow."""\nasync def run(): return "same"'
        (local / "same_workflow.py").write_text(workflow_content)

        # Remote has same content
        mock_store = MagicMock()
        remote_workflow = MagicMock()
        remote_workflow.name = "same_workflow"
        remote_workflow.description = "Same workflow."
        remote_workflow.source = workflow_content
        mock_store.list_all.return_value = [remote_workflow]

        with patch("py_code_mode.cli.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "same_workflow" in result["unchanged"]


class TestCLI:
    """Test CLI argument parsing."""

    def test_bootstrap_command_parses_args(self) -> None:
        """Bootstrap command parses arguments correctly."""
        from py_code_mode.cli.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "bootstrap",
                "--source",
                "/path/to/workflows",
                "--target",
                "redis://localhost:6379",
                "--prefix",
                "my-workflows",
                "--clear",
            ]
        )

        assert args.command == "bootstrap"
        assert str(args.source) == "/path/to/workflows"
        assert args.target == "redis://localhost:6379"
        assert args.prefix == "my-workflows"
        assert args.clear is True

    def test_pull_command_parses_args(self) -> None:
        """Pull command parses arguments correctly."""
        from py_code_mode.cli.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "pull",
                "--target",
                "redis://localhost:6379",
                "--prefix",
                "my-workflows",
                "--dest",
                "/path/to/dest",
            ]
        )

        assert args.command == "pull"
        assert args.target == "redis://localhost:6379"
        assert args.prefix == "my-workflows"
        assert str(args.dest) == "/path/to/dest"

    def test_diff_command_parses_args(self) -> None:
        """Diff command parses arguments correctly."""
        from py_code_mode.cli.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "diff",
                "--source",
                "/path/to/workflows",
                "--target",
                "redis://localhost:6379",
                "--prefix",
                "my-workflows",
            ]
        )

        assert args.command == "diff"
        assert str(args.source) == "/path/to/workflows"
        assert args.target == "redis://localhost:6379"
        assert args.prefix == "my-workflows"

    def test_default_prefix(self) -> None:
        """Default prefix is 'workflows'."""
        from py_code_mode.cli.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "pull",
                "--target",
                "redis://localhost",
                "--dest",
                "/tmp/dest",
            ]
        )

        assert args.prefix == "workflows"
