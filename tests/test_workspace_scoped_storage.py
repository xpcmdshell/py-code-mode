"""Tests for workspace-scoped storage behavior."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from py_code_mode import Session
from py_code_mode.errors import ArtifactNotFoundError
from py_code_mode.storage import FileStorage, RedisStorage

if TYPE_CHECKING:
    from tests.conftest import MockRedisClient


SHARED_WORKFLOW_SOURCE = """async def run() -> str:
    return "shared workflow"
"""

SEARCHABLE_WORKFLOW_SOURCE = """async def run() -> str:
    return "searchable workflow"
"""


class TestWorkspaceScopedFileStorageArtifacts:
    """Session-facing artifact behavior with workspace-scoped FileStorage."""

    @pytest.mark.asyncio
    async def test_artifacts_are_isolated_between_workspaces(self, tmp_path: Path) -> None:
        workspace_a = FileStorage(tmp_path, workspace_id="client_a")
        workspace_b = FileStorage(tmp_path, workspace_id="client_b")

        async with Session(storage=workspace_a) as session_a:
            await session_a.save_artifact(
                name="campaign.json",
                data={"workspace": "client_a"},
                description="Artifact scoped to client_a",
            )

        async with Session(storage=workspace_b) as session_b:
            assert await session_b.list_artifacts() == []
            with pytest.raises(ArtifactNotFoundError):
                await session_b.load_artifact("campaign.json")

    @pytest.mark.asyncio
    async def test_artifacts_are_shared_by_separately_initialized_sessions_in_same_workspace(
        self, tmp_path: Path
    ) -> None:
        writer_storage = FileStorage(tmp_path, workspace_id="shared_client")
        reader_storage = FileStorage(tmp_path, workspace_id="shared_client")

        async with Session(storage=writer_storage) as writer:
            await writer.save_artifact(
                name="campaign.json",
                data={"shared": True},
                description="Shared artifact",
            )

        async with Session(storage=reader_storage) as reader:
            assert await reader.load_artifact("campaign.json") == {"shared": True}
            artifacts = await reader.list_artifacts()
            assert [artifact["name"] for artifact in artifacts] == ["campaign.json"]


class TestWorkspaceScopedFileStorageWorkflows:
    """Session-facing workflow behavior with workspace-scoped FileStorage."""

    @pytest.mark.asyncio
    async def test_workflows_are_isolated_between_workspaces(self, tmp_path: Path) -> None:
        workspace_a = FileStorage(tmp_path, workspace_id="client_a")
        workspace_b = FileStorage(tmp_path, workspace_id="client_b")

        async with Session(storage=workspace_a) as session_a:
            await session_a.add_workflow(
                name="shared_campaign",
                source=SHARED_WORKFLOW_SOURCE,
                description="Workflow scoped to client_a",
            )

        async with Session(storage=workspace_b) as session_b:
            assert await session_b.get_workflow("shared_campaign") is None
            assert await session_b.list_workflows() == []

    @pytest.mark.asyncio
    async def test_workflows_are_shared_by_separately_initialized_sessions_in_same_workspace(
        self, tmp_path: Path
    ) -> None:
        writer_storage = FileStorage(tmp_path, workspace_id="shared_client")
        reader_storage = FileStorage(tmp_path, workspace_id="shared_client")

        async with Session(storage=writer_storage) as writer:
            await writer.add_workflow(
                name="shared_campaign",
                source=SHARED_WORKFLOW_SOURCE,
                description="Workflow visible within one workspace",
            )

        async with Session(storage=reader_storage) as reader:
            workflow = await reader.get_workflow("shared_campaign")
            assert workflow is not None
            assert workflow["name"] == "shared_campaign"

            result = await reader.run("workflows.shared_campaign()")
            assert result.is_ok
            assert result.value == "shared workflow"

    @pytest.mark.asyncio
    async def test_workflow_search_is_isolated_between_workspaces(self, tmp_path: Path) -> None:
        workspace_a = FileStorage(tmp_path, workspace_id="client_a")
        workspace_b = FileStorage(tmp_path, workspace_id="client_b")

        async with Session(storage=workspace_a) as session_a:
            await session_a.add_workflow(
                name="campaign_search",
                source=SEARCHABLE_WORKFLOW_SOURCE,
                description="Analyze campaign metrics and summarize ad performance",
            )
            results = await session_a.search_workflows("campaign metrics ad performance")
            assert [workflow["name"] for workflow in results] == ["campaign_search"]

        async with Session(storage=workspace_b) as session_b:
            results = await session_b.search_workflows("campaign metrics ad performance")
            assert results == []


class TestWorkspaceScopedRedisStorageArtifacts:
    """Session-facing artifact behavior with workspace-scoped RedisStorage."""

    @pytest.mark.asyncio
    async def test_artifacts_are_isolated_between_workspaces(
        self, mock_redis: MockRedisClient
    ) -> None:
        workspace_a = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")
        workspace_b = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_b")

        async with Session(storage=workspace_a) as session_a:
            await session_a.save_artifact(
                name="campaign.json",
                data={"workspace": "client_a"},
                description="Artifact scoped to client_a",
            )

        async with Session(storage=workspace_b) as session_b:
            assert await session_b.list_artifacts() == []
            with pytest.raises(ArtifactNotFoundError):
                await session_b.load_artifact("campaign.json")

    @pytest.mark.asyncio
    async def test_artifacts_are_shared_by_separately_initialized_sessions_in_same_workspace(
        self, mock_redis: MockRedisClient
    ) -> None:
        writer_storage = RedisStorage(
            redis=mock_redis,
            prefix="app",
            workspace_id="shared_client",
        )
        reader_storage = RedisStorage(
            redis=mock_redis,
            prefix="app",
            workspace_id="shared_client",
        )

        async with Session(storage=writer_storage) as writer:
            await writer.save_artifact(
                name="campaign.json",
                data={"shared": True},
                description="Shared artifact",
            )

        async with Session(storage=reader_storage) as reader:
            assert await reader.load_artifact("campaign.json") == {"shared": True}
            artifacts = await reader.list_artifacts()
            assert [artifact["name"] for artifact in artifacts] == ["campaign.json"]


class TestWorkspaceScopedRedisStorageWorkflows:
    """Session-facing workflow behavior with workspace-scoped RedisStorage."""

    @pytest.mark.asyncio
    async def test_workflows_are_isolated_between_workspaces(
        self, mock_redis: MockRedisClient
    ) -> None:
        workspace_a = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")
        workspace_b = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_b")

        async with Session(storage=workspace_a) as session_a:
            await session_a.add_workflow(
                name="shared_campaign",
                source=SHARED_WORKFLOW_SOURCE,
                description="Workflow scoped to client_a",
            )

        async with Session(storage=workspace_b) as session_b:
            assert await session_b.get_workflow("shared_campaign") is None
            assert await session_b.list_workflows() == []

    @pytest.mark.asyncio
    async def test_workflows_are_shared_by_separately_initialized_sessions_in_same_workspace(
        self, mock_redis: MockRedisClient
    ) -> None:
        writer_storage = RedisStorage(
            redis=mock_redis,
            prefix="app",
            workspace_id="shared_client",
        )
        reader_storage = RedisStorage(
            redis=mock_redis,
            prefix="app",
            workspace_id="shared_client",
        )

        async with Session(storage=writer_storage) as writer:
            await writer.add_workflow(
                name="shared_campaign",
                source=SHARED_WORKFLOW_SOURCE,
                description="Workflow visible within one workspace",
            )

        async with Session(storage=reader_storage) as reader:
            workflow = await reader.get_workflow("shared_campaign")
            assert workflow is not None
            assert workflow["name"] == "shared_campaign"

            result = await reader.run("workflows.shared_campaign()")
            assert result.is_ok
            assert result.value == "shared workflow"

    @pytest.mark.asyncio
    async def test_workflow_search_is_isolated_between_workspaces(
        self, mock_redis: MockRedisClient
    ) -> None:
        workspace_a = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")
        workspace_b = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_b")

        async with Session(storage=workspace_a) as session_a:
            await session_a.add_workflow(
                name="campaign_search",
                source=SEARCHABLE_WORKFLOW_SOURCE,
                description="Analyze campaign metrics and summarize ad performance",
            )
            results = await session_a.search_workflows("campaign metrics ad performance")
            assert [workflow["name"] for workflow in results] == ["campaign_search"]

        async with Session(storage=workspace_b) as session_b:
            results = await session_b.search_workflows("campaign metrics ad performance")
            assert results == []


class TestWorkspaceScopedStorageDefaults:
    """Expected behavior when workspace_id is omitted."""

    @pytest.mark.asyncio
    async def test_omitting_workspace_id_preserves_current_unscoped_session_behavior(
        self, tmp_path: Path
    ) -> None:
        writer_storage = FileStorage(tmp_path)
        reader_storage = FileStorage(tmp_path, workspace_id=None)

        async with Session(storage=writer_storage) as writer:
            await writer.save_artifact(
                name="legacy.json",
                data={"mode": "legacy"},
                description="Legacy unscoped artifact",
            )

        async with Session(storage=reader_storage) as reader:
            assert await reader.load_artifact("legacy.json") == {"mode": "legacy"}

    @pytest.mark.asyncio
    async def test_omitting_workspace_id_preserves_current_unscoped_redis_behavior(
        self, mock_redis: MockRedisClient
    ) -> None:
        writer_storage = RedisStorage(redis=mock_redis, prefix="app")
        reader_storage = RedisStorage(redis=mock_redis, prefix="app", workspace_id=None)

        async with Session(storage=writer_storage) as writer:
            await writer.save_artifact(
                name="legacy.json",
                data={"mode": "legacy"},
                description="Legacy unscoped artifact",
            )

        async with Session(storage=reader_storage) as reader:
            assert await reader.load_artifact("legacy.json") == {"mode": "legacy"}

    @pytest.mark.asyncio
    async def test_omitting_workspace_id_preserves_current_unscoped_workflow_behavior(
        self, tmp_path: Path
    ) -> None:
        writer_storage = FileStorage(tmp_path)
        reader_storage = FileStorage(tmp_path, workspace_id=None)

        async with Session(storage=writer_storage) as writer:
            await writer.add_workflow(
                name="legacy_workflow",
                source=SHARED_WORKFLOW_SOURCE,
                description="Legacy unscoped workflow",
            )

        async with Session(storage=reader_storage) as reader:
            workflow = await reader.get_workflow("legacy_workflow")
            assert workflow is not None
            result = await reader.run("workflows.legacy_workflow()")
            assert result.is_ok
            assert result.value == "shared workflow"

    @pytest.mark.asyncio
    async def test_omitting_workspace_id_preserves_current_unscoped_redis_workflow_behavior(
        self, mock_redis: MockRedisClient
    ) -> None:
        writer_storage = RedisStorage(redis=mock_redis, prefix="app")
        reader_storage = RedisStorage(redis=mock_redis, prefix="app", workspace_id=None)

        async with Session(storage=writer_storage) as writer:
            await writer.add_workflow(
                name="legacy_workflow",
                source=SHARED_WORKFLOW_SOURCE,
                description="Legacy unscoped workflow",
            )

        async with Session(storage=reader_storage) as reader:
            workflow = await reader.get_workflow("legacy_workflow")
            assert workflow is not None
            result = await reader.run("workflows.legacy_workflow()")
            assert result.is_ok
            assert result.value == "shared workflow"

    @pytest.mark.asyncio
    async def test_scoped_file_storage_does_not_see_unscoped_artifacts(
        self, tmp_path: Path
    ) -> None:
        legacy_storage = FileStorage(tmp_path)
        scoped_storage = FileStorage(tmp_path, workspace_id="client_a")

        async with Session(storage=legacy_storage) as legacy:
            await legacy.save_artifact(
                name="legacy.json",
                data={"mode": "legacy"},
                description="Legacy artifact",
            )

        async with Session(storage=scoped_storage) as scoped:
            assert await scoped.list_artifacts() == []
            with pytest.raises(ArtifactNotFoundError):
                await scoped.load_artifact("legacy.json")

    @pytest.mark.asyncio
    async def test_unscoped_file_storage_does_not_see_scoped_artifacts(
        self, tmp_path: Path
    ) -> None:
        legacy_storage = FileStorage(tmp_path)
        scoped_storage = FileStorage(tmp_path, workspace_id="client_a")

        async with Session(storage=scoped_storage) as scoped:
            await scoped.save_artifact(
                name="workspace.json",
                data={"mode": "scoped"},
                description="Scoped artifact",
            )

        async with Session(storage=legacy_storage) as legacy:
            assert await legacy.list_artifacts() == []
            with pytest.raises(ArtifactNotFoundError):
                await legacy.load_artifact("workspace.json")

    @pytest.mark.asyncio
    async def test_scoped_file_storage_does_not_see_unscoped_workflows(
        self, tmp_path: Path
    ) -> None:
        legacy_storage = FileStorage(tmp_path)
        scoped_storage = FileStorage(tmp_path, workspace_id="client_a")

        async with Session(storage=legacy_storage) as legacy:
            await legacy.add_workflow(
                name="legacy_workflow",
                source=SHARED_WORKFLOW_SOURCE,
                description="Legacy unscoped workflow",
            )

        async with Session(storage=scoped_storage) as scoped:
            assert await scoped.get_workflow("legacy_workflow") is None
            assert await scoped.search_workflows("legacy unscoped workflow") == []

    @pytest.mark.asyncio
    async def test_scoped_redis_storage_does_not_see_unscoped_artifacts(
        self, mock_redis: MockRedisClient
    ) -> None:
        legacy_storage = RedisStorage(redis=mock_redis, prefix="app")
        scoped_storage = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")

        async with Session(storage=legacy_storage) as legacy:
            await legacy.save_artifact(
                name="legacy.json",
                data={"mode": "legacy"},
                description="Legacy artifact",
            )

        async with Session(storage=scoped_storage) as scoped:
            assert await scoped.list_artifacts() == []
            with pytest.raises(ArtifactNotFoundError):
                await scoped.load_artifact("legacy.json")

    @pytest.mark.asyncio
    async def test_unscoped_redis_storage_does_not_see_scoped_artifacts(
        self, mock_redis: MockRedisClient
    ) -> None:
        legacy_storage = RedisStorage(redis=mock_redis, prefix="app")
        scoped_storage = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")

        async with Session(storage=scoped_storage) as scoped:
            await scoped.save_artifact(
                name="workspace.json",
                data={"mode": "scoped"},
                description="Scoped artifact",
            )

        async with Session(storage=legacy_storage) as legacy:
            assert await legacy.list_artifacts() == []
            with pytest.raises(ArtifactNotFoundError):
                await legacy.load_artifact("workspace.json")

    @pytest.mark.asyncio
    async def test_scoped_redis_storage_does_not_see_unscoped_workflows(
        self, mock_redis: MockRedisClient
    ) -> None:
        legacy_storage = RedisStorage(redis=mock_redis, prefix="app")
        scoped_storage = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")

        async with Session(storage=legacy_storage) as legacy:
            await legacy.add_workflow(
                name="legacy_workflow",
                source=SHARED_WORKFLOW_SOURCE,
                description="Legacy unscoped workflow",
            )

        async with Session(storage=scoped_storage) as scoped:
            assert await scoped.get_workflow("legacy_workflow") is None
            assert await scoped.search_workflows("legacy unscoped workflow") == []

    def test_file_storage_without_workspace_id_uses_legacy_layout(self, tmp_path: Path) -> None:
        storage = FileStorage(tmp_path, workspace_id=None)

        access = storage.get_serializable_access()

        assert access.workflows_path == tmp_path / "workflows"
        assert access.artifacts_path == tmp_path / "artifacts"
        if access.vectors_path is not None:
            assert access.vectors_path == tmp_path / "vectors"

    def test_file_storage_workspace_id_scopes_paths(self, tmp_path: Path) -> None:
        storage = FileStorage(tmp_path, workspace_id="client_a")

        access = storage.get_serializable_access()

        assert access.workflows_path == tmp_path / "workspaces" / "client_a" / "workflows"
        assert access.artifacts_path == tmp_path / "workspaces" / "client_a" / "artifacts"
        if access.vectors_path is not None:
            assert access.vectors_path == tmp_path / "workspaces" / "client_a" / "vectors"

    def test_redis_storage_workspace_id_scopes_prefixes(self, mock_redis: MockRedisClient) -> None:
        storage = RedisStorage(
            redis=mock_redis,
            prefix="app",
            workspace_id="client_a",
        )

        access = storage.get_serializable_access()

        assert access.workflows_prefix == "app:ws:client_a:workflows"
        assert access.artifacts_prefix == "app:ws:client_a:artifacts"
        if access.vectors_prefix is not None:
            assert access.vectors_prefix == "app:ws:client_a:vectors"

    def test_redis_storage_without_workspace_id_preserves_current_prefixes(
        self, mock_redis: MockRedisClient
    ) -> None:
        storage = RedisStorage(
            redis=mock_redis,
            prefix="app",
            workspace_id=None,
        )

        access = storage.get_serializable_access()

        assert access.workflows_prefix == "app:workflows"
        assert access.artifacts_prefix == "app:artifacts"
        if access.vectors_prefix is not None:
            assert access.vectors_prefix == "app:vectors"


class TestWorkspaceScopedBootstrapConfig:
    """Bootstrap config preserves workspace scope without re-scoping deps roots."""

    def test_file_storage_workspace_id_is_serialized_explicitly(self, tmp_path: Path) -> None:
        storage = FileStorage(tmp_path, workspace_id="client_a")

        config = storage.to_bootstrap_config()

        assert config["base_path"] == str(tmp_path)
        assert config["workspace_id"] == "client_a"

    def test_redis_storage_workspace_id_is_serialized_explicitly(
        self, mock_redis: MockRedisClient
    ) -> None:
        storage = RedisStorage(redis=mock_redis, prefix="app", workspace_id="client_a")

        config = storage.to_bootstrap_config()

        assert config["prefix"] == "app"
        assert config["workspace_id"] == "client_a"


class TestWorkspaceIdValidation:
    """Validation behavior for workspace identifiers."""

    @pytest.mark.parametrize("workspace_id", ["", ".", "..", "../escape", "bad/name", r"bad\\name"])
    def test_file_storage_rejects_invalid_workspace_ids(
        self, tmp_path: Path, workspace_id: str
    ) -> None:
        with pytest.raises(ValueError):
            FileStorage(tmp_path, workspace_id=workspace_id)

    @pytest.mark.parametrize("workspace_id", ["", ".", "..", "../escape", "bad/name", "bad:name"])
    def test_redis_storage_rejects_invalid_workspace_ids(
        self, mock_redis: MockRedisClient, workspace_id: str
    ) -> None:
        with pytest.raises(ValueError):
            RedisStorage(redis=mock_redis, prefix="app", workspace_id=workspace_id)
