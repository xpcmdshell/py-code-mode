"""CLI for workflow and tool store lifecycle management.

Commands:
    bootstrap - Push workflows or tools from directory to store
    pull - Retrieve workflows from store to local files
    diff - Compare local workflows vs remote store
    list - List items in store

Usage:
    python -m py_code_mode.cli.store bootstrap --source ./workflows --target redis://...
    python -m py_code_mode.cli.store bootstrap --source ./tools --target redis://... --type tools
    python -m py_code_mode.cli.store pull --target redis://... --dest ./workflows-from-redis
    python -m py_code_mode.cli.store diff --source ./workflows --target redis://...
    python -m py_code_mode.cli.store list --target redis://... --prefix agent-workflows
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import redis as redis_lib
import yaml

from py_code_mode.deps import RedisDepsStore
from py_code_mode.storage import RedisToolStore
from py_code_mode.workflows import FileWorkflowStore, PythonWorkflow, RedisWorkflowStore

logger = logging.getLogger(__name__)


def _get_store(target: str, prefix: str) -> RedisWorkflowStore:
    """Get workflow store based on URL scheme.

    Args:
        target: Target URL (e.g., redis://localhost:6379).
        prefix: Key prefix for workflows.

    Returns:
        RedisWorkflowStore connected to the target.

    Raises:
        ValueError: Unknown URL scheme.
        NotImplementedError: Known but unimplemented scheme.
    """
    parsed = urlparse(target)

    if parsed.scheme in ("redis", "rediss"):
        r = redis_lib.from_url(target)
        return RedisWorkflowStore(r, prefix=prefix)

    elif parsed.scheme == "s3":
        raise NotImplementedError("S3 adapter coming soon")

    elif parsed.scheme == "cosmos":
        raise NotImplementedError("CosmosDB adapter coming soon")

    elif parsed.scheme == "file":
        raise NotImplementedError("File adapter coming soon")

    else:
        raise ValueError(
            f"Unknown scheme: {parsed.scheme}. Supported: redis://, rediss://, s3://, cosmos://"
        )


def _workflow_hash(workflow: PythonWorkflow) -> str:
    """Hash workflow content for quick comparison.

    Args:
        workflow: Workflow to hash.

    Returns:
        12-character hash of workflow content.
    """
    content = f"{workflow.name}:{workflow.description}:{workflow.source}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def bootstrap(
    source: Path | None,
    target: str,
    prefix: str,
    store_type: str = "workflows",
    clear: bool = False,
    deps: list[str] | None = None,
) -> int:
    """Push workflows, tools, or deps to store.

    Args:
        source: Path to directory containing workflow/tool files, or requirements file for deps.
        target: Target store URL.
        prefix: Key prefix for items.
        store_type: Type of store ("workflows", "tools", or "deps").
        clear: If True, remove existing items first.
        deps: Inline package specs for deps bootstrapping (only used when store_type is "deps").

    Returns:
        Number of items added.
    """
    if store_type == "tools":
        if source is None:
            raise ValueError("--source is required for tools bootstrapping")
        return _bootstrap_tools(source, target, prefix, clear)
    elif store_type == "deps":
        return _bootstrap_deps(source, deps, target, prefix, clear)
    else:
        if source is None:
            raise ValueError("--source is required for workflows bootstrapping")
        return _bootstrap_workflows(source, target, prefix, clear)


def _bootstrap_workflows(source: Path, target: str, prefix: str, clear: bool) -> int:
    """Bootstrap workflows to store."""
    store = _get_store(target, prefix)

    if clear:
        for workflow in store.list_all():
            store.delete(workflow.name)
            print(f"  Removed: {workflow.name}")

    # Load from local directory
    local_store = FileWorkflowStore(source)
    workflows = local_store.list_all()

    # Use batch save if available (RedisWorkflowStore)
    if hasattr(store, "save_batch"):
        store.save_batch(workflows)
        for workflow in workflows:
            print(f"  Added: {workflow.name}")
    else:
        for workflow in workflows:
            store.save(workflow)
            print(f"  Added: {workflow.name}")

    print(f"\nBootstrapped {len(workflows)} workflows to {target} (prefix: {prefix})")
    return len(workflows)


def _bootstrap_tools(source: Path, target: str, prefix: str, clear: bool) -> int:
    """Bootstrap tools to store."""
    parsed = urlparse(target)

    if parsed.scheme not in ("redis", "rediss"):
        raise ValueError(f"Tool store only supports Redis, got: {parsed.scheme}")

    r = redis_lib.from_url(target)
    store = RedisToolStore(r, prefix=prefix)

    if clear:
        for name in store.list():
            store.remove(name)
            print(f"  Removed: {name}")

    # Load from directory
    added = 0
    if source.exists():
        for tool_file in sorted(source.glob("*.yaml")):
            try:
                with open(tool_file) as f:
                    tool = yaml.safe_load(f)
                    if not isinstance(tool, dict) or "name" not in tool:
                        logger.warning(f"Invalid tool YAML (missing 'name'): {tool_file}")
                        continue
            except yaml.YAMLError as e:
                logger.warning(f"Failed to parse YAML {tool_file}: {e}")
                continue

            store.add(tool["name"], tool)
            print(f"  Added: {tool['name']}")
            added += 1

    print(f"\nBootstrapped {added} tools to {target} (prefix: {prefix})")
    return added


def _bootstrap_deps(
    source: Path | None,
    deps: list[str] | None,
    target: str,
    prefix: str,
    clear: bool,
) -> int:
    """Bootstrap deps to store.

    Args:
        source: Path to requirements.txt style file (one package spec per line).
        deps: Inline package specs.
        target: Target store URL.
        prefix: Key prefix for deps.
        clear: If True, remove existing deps first.

    Returns:
        Number of deps added.

    Raises:
        ValueError: If neither source nor deps provided, or invalid target scheme.
    """
    parsed = urlparse(target)

    if parsed.scheme not in ("redis", "rediss"):
        raise ValueError(f"Deps store only supports Redis, got: {parsed.scheme}")

    # Collect package specs from both sources
    package_specs: list[str] = []

    # Read from file if provided
    if source is not None:
        if not source.exists():
            raise ValueError(f"Source file does not exist: {source}")
        with open(source) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if line and not line.startswith("#"):
                    package_specs.append(line)

    # Add inline deps
    if deps:
        package_specs.extend(deps)

    if not package_specs:
        raise ValueError("No deps provided. Use --source or --deps to specify packages.")

    r = redis_lib.from_url(target)
    store = RedisDepsStore(r, prefix=prefix)

    if clear:
        store.clear()
        print("  Cleared existing deps")

    added = 0
    for dep in package_specs:
        try:
            store.add(dep)
            print(f"  Added: {dep}")
            added += 1
        except ValueError as e:
            logger.warning(f"Invalid dependency '{dep}': {e}")

    print(f"\nBootstrapped {added} deps to {target} (prefix: {prefix})")
    return added


def pull(target: str, prefix: str, dest: Path) -> int:
    """Pull workflows from store to local files.

    Args:
        target: Target store URL.
        prefix: Key prefix for workflows.
        dest: Destination directory for workflow files.

    Returns:
        Number of workflows pulled.
    """
    store = _get_store(target, prefix)

    dest.mkdir(parents=True, exist_ok=True)
    pulled = 0

    for workflow in store.list_all():
        # Write as .py file
        file_path = dest / f"{workflow.name}.py"
        file_path.write_text(workflow.source)
        pulled += 1
        print(f"  {workflow.name} -> {file_path}")

    print(f"\nPulled {pulled} workflows to {dest}")
    return pulled


def diff(source: Path, target: str, prefix: str) -> dict:
    """Compare local workflows vs remote store.

    Args:
        source: Path to local workflows directory.
        target: Target store URL.
        prefix: Key prefix for workflows.

    Returns:
        Dict with keys: added, modified, removed, unchanged.
    """
    store = _get_store(target, prefix)

    # Load local workflows
    local_store = FileWorkflowStore(source)
    local_workflows = {w.name: w for w in local_store.list_all()}
    local_hashes = {name: _workflow_hash(w) for name, w in local_workflows.items()}

    # Load remote workflows
    remote_workflows = {w.name: w for w in store.list_all()}
    remote_hashes = {name: _workflow_hash(w) for name, w in remote_workflows.items()}

    result: dict[str, list[str]] = {
        "added": [],
        "modified": [],
        "removed": [],
        "unchanged": [],
    }

    all_names = set(local_workflows.keys()) | set(remote_workflows.keys())
    for name in sorted(all_names):
        in_local = name in local_workflows
        in_remote = name in remote_workflows

        if in_remote and not in_local:
            print(f"  + {name} (agent-created)")
            result["added"].append(name)
        elif in_local and not in_remote:
            print(f"  - {name} (removed from store)")
            result["removed"].append(name)
        elif local_hashes[name] != remote_hashes[name]:
            print(f"  ~ {name} (modified)")
            result["modified"].append(name)
        else:
            print(f"  = {name}")
            result["unchanged"].append(name)

    return result


def list_items(target: str, prefix: str, store_type: str = "workflows") -> int:
    """List items in store.

    Args:
        target: Target store URL.
        prefix: Key prefix for items.
        store_type: Type of store ("workflows", "tools", or "deps").

    Returns:
        Number of items listed.
    """
    parsed = urlparse(target)

    if parsed.scheme not in ("redis", "rediss"):
        raise ValueError(f"Only Redis is supported, got: {parsed.scheme}")

    r = redis_lib.from_url(target)

    if store_type == "tools":
        store = RedisToolStore(r, prefix=prefix)
        items = store.list()
        for name, config in items.items():
            desc = config.get("description", "")[:50]
            print(f"  {name}: {desc}")
        print(f"\n{len(items)} tools in {target} (prefix: {prefix})")
        return len(items)
    elif store_type == "deps":
        store = RedisDepsStore(r, prefix=prefix)
        deps = store.list()
        for dep in deps:
            print(f"  {dep}")
        print(f"\n{len(deps)} deps in {target} (prefix: {prefix})")
        return len(deps)
    else:
        store = RedisWorkflowStore(r, prefix=prefix)
        workflows = store.list_all()
        for workflow in workflows:
            desc = workflow.description[:50] if workflow.description else ""
            print(f"  {workflow.name}: {desc}")
        print(f"\n{len(workflows)} workflows in {target} (prefix: {prefix})")
        return len(workflows)


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for store CLI.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        description="Workflow, tool, and deps store lifecycle management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Push workflows from repo to Redis (deploy time)
  python -m py_code_mode.store bootstrap \
    --source ./workflows \
    --target redis://localhost:6379 \
    --prefix agent-workflows

  # Push tools to Redis
  python -m py_code_mode.store bootstrap \
    --source ./tools \
    --target redis://localhost:6379 \
    --prefix agent-tools \
    --type tools

  # Push deps from requirements file
  python -m py_code_mode.store bootstrap \
    --source requirements.txt \
    --target redis://localhost:6379 \
    --prefix agent-deps \
    --type deps

  # Push deps inline
  python -m py_code_mode.store bootstrap \
    --target redis://localhost:6379 \
    --prefix agent-deps \
    --type deps \
    --deps "requests>=2.31" "pandas>=2.0"

  # List workflows in Redis
  python -m py_code_mode.store list \
    --target redis://localhost:6379 \
    --prefix agent-workflows

  # List deps in Redis
  python -m py_code_mode.store list \
    --target redis://localhost:6379 \
    --prefix agent-deps \
    --type deps

  # Pull workflows from Redis to local files (review agent-created workflows)
  python -m py_code_mode.store pull \
    --target redis://localhost:6379 \
    --prefix agent-workflows \
    --dest ./workflows-from-redis

  # Compare local vs Redis (what did agent add/change?)
  python -m py_code_mode.store diff \
    --source ./workflows \
    --target redis://localhost:6379 \
    --prefix agent-workflows
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # bootstrap
    boot = subparsers.add_parser(
        "bootstrap",
        help="Push workflows, tools, or deps to store",
    )
    boot.add_argument(
        "--source",
        type=Path,
        help="Path to directory (workflows/tools) or requirements file (deps)",
    )
    boot.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    boot.add_argument(
        "--prefix",
        default="workflows",
        help="Key prefix (default: workflows)",
    )
    boot.add_argument(
        "--type",
        choices=["workflows", "tools", "deps"],
        default="workflows",
        help="Type of items to bootstrap (default: workflows)",
    )
    boot.add_argument(
        "--clear",
        action="store_true",
        help="Remove existing items before adding new ones",
    )
    boot.add_argument(
        "--deps",
        nargs="*",
        help="Inline package specs for deps bootstrapping (e.g., 'requests>=2.31' 'pandas>=2.0')",
    )

    # list
    ls = subparsers.add_parser(
        "list",
        help="List items in store",
    )
    ls.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    ls.add_argument(
        "--prefix",
        default="workflows",
        help="Key prefix (default: workflows)",
    )
    ls.add_argument(
        "--type",
        choices=["workflows", "tools", "deps"],
        default="workflows",
        help="Type of items to list (default: workflows)",
    )

    # pull
    pl = subparsers.add_parser(
        "pull",
        help="Retrieve workflows from store to local files",
    )
    pl.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    pl.add_argument(
        "--prefix",
        default="workflows",
        help="Key prefix for workflows (default: workflows)",
    )
    pl.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Destination directory for workflow files",
    )

    # diff
    df = subparsers.add_parser(
        "diff",
        help="Compare local workflows vs remote store",
    )
    df.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to local workflows directory",
    )
    df.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    df.add_argument(
        "--prefix",
        default="workflows",
        help="Key prefix for workflows (default: workflows)",
    )

    return parser


def main() -> None:
    """Main entry point for store CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "bootstrap":
        deps = getattr(args, "deps", None)
        bootstrap(args.source, args.target, args.prefix, args.type, args.clear, deps)
    elif args.command == "list":
        list_items(args.target, args.prefix, args.type)
    elif args.command == "pull":
        pull(args.target, args.prefix, args.dest)
    elif args.command == "diff":
        diff(args.source, args.target, args.prefix)


if __name__ == "__main__":
    main()
