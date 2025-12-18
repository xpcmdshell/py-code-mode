"""Tests for skill store CLI module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from py_code_mode.skills import PythonSkill


def _make_skill(name: str, description: str, source: str) -> PythonSkill:
    """Helper to create a PythonSkill."""
    full_source = f'"""{description}"""\n\n{source}'
    return PythonSkill.from_source(name=name, source=full_source, description=description)


class TestGetStore:
    """Test _get_store factory function."""

    def test_redis_scheme_creates_redis_store(self) -> None:
        """redis:// scheme creates RedisSkillStore."""
        from py_code_mode.store import _get_store

        with patch("py_code_mode.store.redis_lib") as mock_redis_lib:
            mock_client = MagicMock()
            mock_redis_lib.from_url.return_value = mock_client

            store = _get_store("redis://localhost:6379", prefix="test")

            mock_redis_lib.from_url.assert_called_once_with("redis://localhost:6379")
            assert store is not None

    def test_rediss_scheme_creates_redis_store(self) -> None:
        """rediss:// (TLS) scheme creates RedisSkillStore."""
        from py_code_mode.store import _get_store

        with patch("py_code_mode.store.redis_lib") as mock_redis_lib:
            mock_client = MagicMock()
            mock_redis_lib.from_url.return_value = mock_client

            _get_store("rediss://localhost:6380", prefix="test")

            mock_redis_lib.from_url.assert_called_once_with("rediss://localhost:6380")

    def test_unknown_scheme_raises_valueerror(self) -> None:
        """Unknown scheme raises ValueError."""
        from py_code_mode.store import _get_store

        with pytest.raises(ValueError, match="Unknown scheme"):
            _get_store("unknown://localhost", prefix="test")

    def test_s3_scheme_not_implemented(self) -> None:
        """s3:// scheme raises NotImplementedError."""
        from py_code_mode.store import _get_store

        with pytest.raises(NotImplementedError, match="S3"):
            _get_store("s3://bucket/path", prefix="test")

    def test_cosmos_scheme_not_implemented(self) -> None:
        """cosmos:// scheme raises NotImplementedError."""
        from py_code_mode.store import _get_store

        with pytest.raises(NotImplementedError, match="Cosmos"):
            _get_store("cosmos://account.documents.azure.com", prefix="test")


class TestSkillHash:
    """Test _skill_hash function."""

    def test_same_skill_same_hash(self) -> None:
        """Same skill content produces same hash."""
        from py_code_mode.store import _skill_hash

        skill = _make_skill("test", "Test skill", "def run():\n    return 'hello'")

        hash1 = _skill_hash(skill)
        hash2 = _skill_hash(skill)
        assert hash1 == hash2

    def test_different_content_different_hash(self) -> None:
        """Different skill content produces different hash."""
        from py_code_mode.store import _skill_hash

        skill1 = _make_skill("test", "Desc 1", "def run(): return 1")
        skill2 = _make_skill("test", "Desc 2", "def run(): return 1")

        assert _skill_hash(skill1) != _skill_hash(skill2)

    def test_hash_is_short(self) -> None:
        """Hash is truncated to 12 characters."""
        from py_code_mode.store import _skill_hash

        skill = _make_skill("test", "desc", "def run(): pass")
        assert len(_skill_hash(skill)) == 12


class TestBootstrap:
    """Test bootstrap command."""

    def test_bootstrap_loads_skills_from_directory(self, tmp_path: Path) -> None:
        """Bootstrap loads skills from source directory."""
        from py_code_mode.store import bootstrap

        # Create test skill
        skill_file = tmp_path / "my_skill.py"
        skill_file.write_text('''"""My test skill."""

def run(x: int) -> int:
    """Double a number."""
    return x * 2
''')

        # Mock store
        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            count = bootstrap(tmp_path, "redis://localhost", "test-prefix")

        assert count == 1
        # Uses batch save when available (RedisSkillStore)
        mock_store.save_batch.assert_called_once()

    def test_bootstrap_with_clear_removes_existing(self, tmp_path: Path) -> None:
        """Bootstrap with clear=True removes existing skills first."""
        from py_code_mode.store import bootstrap

        # Create test skill
        skill_file = tmp_path / "new_skill.py"
        skill_file.write_text('"""New skill."""\ndef run() -> str:\n    return "new"')

        # Mock store with existing skill
        mock_store = MagicMock()
        existing_skill = _make_skill("old_skill", "Old", "def run(): pass")
        mock_store.list_all.return_value = [existing_skill]

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            bootstrap(tmp_path, "redis://localhost", "test-prefix", clear=True)

        # Should have deleted old skill
        mock_store.delete.assert_called_once_with("old_skill")

    def test_bootstrap_returns_count(self, tmp_path: Path) -> None:
        """Bootstrap returns number of skills added."""
        from py_code_mode.store import bootstrap

        # Create multiple skills
        (tmp_path / "skill1.py").write_text('"""S1."""\ndef run(): return 1')
        (tmp_path / "skill2.py").write_text('"""S2."""\ndef run(): return 2')

        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            count = bootstrap(tmp_path, "redis://localhost", "test-prefix")

        assert count == 2


class TestPull:
    """Test pull command."""

    def test_pull_writes_skills_to_files(self, tmp_path: Path) -> None:
        """Pull writes skills to destination directory."""
        from py_code_mode.store import pull

        dest = tmp_path / "pulled"

        # Mock store with skills
        mock_store = MagicMock()
        skill = MagicMock()
        skill.name = "skill1"
        skill.description = "First skill"
        skill.source = '"""First skill."""\ndef run():\n    print("one")'
        mock_store.list_all.return_value = [skill]

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            count = pull("redis://localhost", "test-prefix", dest)

        assert count == 1
        assert dest.exists()
        assert (dest / "skill1.py").exists()

    def test_pull_creates_destination_directory(self, tmp_path: Path) -> None:
        """Pull creates destination directory if it doesn't exist."""
        from py_code_mode.store import pull

        dest = tmp_path / "new" / "nested" / "dir"
        assert not dest.exists()

        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            pull("redis://localhost", "test-prefix", dest)

        assert dest.exists()


class TestDiff:
    """Test diff command."""

    def test_diff_finds_added_skills(self, tmp_path: Path) -> None:
        """Diff identifies skills only in remote (agent-created)."""
        from py_code_mode.store import diff

        # Empty local directory
        local = tmp_path / "local"
        local.mkdir()

        # Remote has a skill
        mock_store = MagicMock()
        remote_skill = MagicMock()
        remote_skill.name = "agent_created"
        remote_skill.description = "Created by agent"
        remote_skill.source = '"""Created by agent."""\ndef run(): pass'
        mock_store.list_all.return_value = [remote_skill]

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "agent_created" in result["added"]
        assert len(result["removed"]) == 0
        assert len(result["modified"]) == 0

    def test_diff_finds_removed_skills(self, tmp_path: Path) -> None:
        """Diff identifies skills only in local (removed from remote)."""
        from py_code_mode.store import diff

        # Local has a skill
        local = tmp_path / "local"
        local.mkdir()
        (local / "local_only.py").write_text('"""Local skill."""\ndef run(): pass')

        # Remote is empty
        mock_store = MagicMock()
        mock_store.list_all.return_value = []

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "local_only" in result["removed"]
        assert len(result["added"]) == 0

    def test_diff_finds_modified_skills(self, tmp_path: Path) -> None:
        """Diff identifies skills with different content."""
        from py_code_mode.store import diff

        # Local skill
        local = tmp_path / "local"
        local.mkdir()
        (local / "shared_skill.py").write_text('"""Local version."""\ndef run(): return "local"')

        # Remote has different version
        mock_store = MagicMock()
        remote_skill = MagicMock()
        remote_skill.name = "shared_skill"
        remote_skill.description = "Remote version"
        remote_skill.source = '"""Remote version."""\ndef run(): return "remote"'
        mock_store.list_all.return_value = [remote_skill]

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "shared_skill" in result["modified"]

    def test_diff_finds_unchanged_skills(self, tmp_path: Path) -> None:
        """Diff identifies identical skills."""
        from py_code_mode.store import diff

        # Local skill
        local = tmp_path / "local"
        local.mkdir()
        skill_content = '"""Same skill."""\ndef run(): return "same"'
        (local / "same_skill.py").write_text(skill_content)

        # Remote has same content
        mock_store = MagicMock()
        remote_skill = MagicMock()
        remote_skill.name = "same_skill"
        remote_skill.description = "Same skill."
        remote_skill.source = skill_content
        mock_store.list_all.return_value = [remote_skill]

        with patch("py_code_mode.store._get_store", return_value=mock_store):
            result = diff(local, "redis://localhost", "test-prefix")

        assert "same_skill" in result["unchanged"]


class TestCLI:
    """Test CLI argument parsing."""

    def test_bootstrap_command_parses_args(self) -> None:
        """Bootstrap command parses arguments correctly."""
        from py_code_mode.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "bootstrap",
                "--source",
                "/path/to/skills",
                "--target",
                "redis://localhost:6379",
                "--prefix",
                "my-skills",
                "--clear",
            ]
        )

        assert args.command == "bootstrap"
        assert str(args.source) == "/path/to/skills"
        assert args.target == "redis://localhost:6379"
        assert args.prefix == "my-skills"
        assert args.clear is True

    def test_pull_command_parses_args(self) -> None:
        """Pull command parses arguments correctly."""
        from py_code_mode.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "pull",
                "--target",
                "redis://localhost:6379",
                "--prefix",
                "my-skills",
                "--dest",
                "/path/to/dest",
            ]
        )

        assert args.command == "pull"
        assert args.target == "redis://localhost:6379"
        assert args.prefix == "my-skills"
        assert str(args.dest) == "/path/to/dest"

    def test_diff_command_parses_args(self) -> None:
        """Diff command parses arguments correctly."""
        from py_code_mode.store import create_parser

        parser = create_parser()
        args = parser.parse_args(
            [
                "diff",
                "--source",
                "/path/to/skills",
                "--target",
                "redis://localhost:6379",
                "--prefix",
                "my-skills",
            ]
        )

        assert args.command == "diff"
        assert str(args.source) == "/path/to/skills"
        assert args.target == "redis://localhost:6379"
        assert args.prefix == "my-skills"

    def test_default_prefix(self) -> None:
        """Default prefix is 'skills'."""
        from py_code_mode.store import create_parser

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

        assert args.prefix == "skills"
