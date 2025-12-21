"""CLI for skill and tool store lifecycle management.

Commands:
    bootstrap - Push skills or tools from directory to store
    pull - Retrieve skills from store to local files
    diff - Compare local skills vs remote store
    list - List items in store

Usage:
    python -m py_code_mode.cli.store bootstrap --source ./skills --target redis://...
    python -m py_code_mode.cli.store bootstrap --source ./tools --target redis://... --type tools
    python -m py_code_mode.cli.store pull --target redis://... --dest ./skills-from-redis
    python -m py_code_mode.cli.store diff --source ./skills --target redis://...
    python -m py_code_mode.cli.store list --target redis://... --prefix agent-skills
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import redis as redis_lib
import yaml

from py_code_mode.skills import FileSkillStore, PythonSkill, RedisSkillStore
from py_code_mode.storage import RedisToolStore

logger = logging.getLogger(__name__)


def _get_store(target: str, prefix: str) -> RedisSkillStore:
    """Get skill store based on URL scheme.

    Args:
        target: Target URL (e.g., redis://localhost:6379).
        prefix: Key prefix for skills.

    Returns:
        RedisSkillStore connected to the target.

    Raises:
        ValueError: Unknown URL scheme.
        NotImplementedError: Known but unimplemented scheme.
    """
    parsed = urlparse(target)

    if parsed.scheme in ("redis", "rediss"):
        r = redis_lib.from_url(target)
        return RedisSkillStore(r, prefix=prefix)

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


def _skill_hash(skill: PythonSkill) -> str:
    """Hash skill content for quick comparison.

    Args:
        skill: Skill to hash.

    Returns:
        12-character hash of skill content.
    """
    content = f"{skill.name}:{skill.description}:{skill.source}"
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def bootstrap(
    source: Path,
    target: str,
    prefix: str,
    store_type: str = "skills",
    clear: bool = False,
) -> int:
    """Push skills or tools from directory to store.

    Args:
        source: Path to directory containing skill/tool files.
        target: Target store URL.
        prefix: Key prefix for items.
        store_type: Type of store ("skills" or "tools").
        clear: If True, remove existing items first.

    Returns:
        Number of items added.
    """
    if store_type == "tools":
        return _bootstrap_tools(source, target, prefix, clear)
    else:
        return _bootstrap_skills(source, target, prefix, clear)


def _bootstrap_skills(source: Path, target: str, prefix: str, clear: bool) -> int:
    """Bootstrap skills to store."""
    store = _get_store(target, prefix)

    if clear:
        for skill in store.list_all():
            store.delete(skill.name)
            print(f"  Removed: {skill.name}")

    # Load from local directory
    local_store = FileSkillStore(source)
    skills = local_store.list_all()

    # Use batch save if available (RedisSkillStore)
    if hasattr(store, "save_batch"):
        store.save_batch(skills)
        for skill in skills:
            print(f"  Added: {skill.name}")
    else:
        for skill in skills:
            store.save(skill)
            print(f"  Added: {skill.name}")

    print(f"\nBootstrapped {len(skills)} skills to {target} (prefix: {prefix})")
    return len(skills)


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


def pull(target: str, prefix: str, dest: Path) -> int:
    """Pull skills from store to local files.

    Args:
        target: Target store URL.
        prefix: Key prefix for skills.
        dest: Destination directory for skill files.

    Returns:
        Number of skills pulled.
    """
    store = _get_store(target, prefix)

    dest.mkdir(parents=True, exist_ok=True)
    pulled = 0

    for skill in store.list_all():
        # Write as .py file
        file_path = dest / f"{skill.name}.py"
        file_path.write_text(skill.source)
        pulled += 1
        print(f"  {skill.name} -> {file_path}")

    print(f"\nPulled {pulled} skills to {dest}")
    return pulled


def diff(source: Path, target: str, prefix: str) -> dict:
    """Compare local skills vs remote store.

    Args:
        source: Path to local skills directory.
        target: Target store URL.
        prefix: Key prefix for skills.

    Returns:
        Dict with keys: added, modified, removed, unchanged.
    """
    store = _get_store(target, prefix)

    # Load local skills
    local_store = FileSkillStore(source)
    local_skills = {s.name: s for s in local_store.list_all()}
    local_hashes = {name: _skill_hash(s) for name, s in local_skills.items()}

    # Load remote skills
    remote_skills = {s.name: s for s in store.list_all()}
    remote_hashes = {name: _skill_hash(s) for name, s in remote_skills.items()}

    result: dict[str, list[str]] = {
        "added": [],
        "modified": [],
        "removed": [],
        "unchanged": [],
    }

    all_names = set(local_skills.keys()) | set(remote_skills.keys())
    for name in sorted(all_names):
        in_local = name in local_skills
        in_remote = name in remote_skills

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


def list_items(target: str, prefix: str, store_type: str = "skills") -> int:
    """List items in store.

    Args:
        target: Target store URL.
        prefix: Key prefix for items.
        store_type: Type of store ("skills" or "tools").

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
    else:
        store = RedisSkillStore(r, prefix=prefix)
        skills = store.list_all()
        for skill in skills:
            desc = skill.description[:50] if skill.description else ""
            print(f"  {skill.name}: {desc}")
        print(f"\n{len(skills)} skills in {target} (prefix: {prefix})")
        return len(skills)


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for store CLI.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        description="Skill and tool store lifecycle management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Push skills from repo to Redis (deploy time)
  python -m py_code_mode.store bootstrap \\
    --source ./skills \\
    --target redis://localhost:6379 \\
    --prefix agent-skills

  # Push tools to Redis
  python -m py_code_mode.store bootstrap \\
    --source ./tools \\
    --target redis://localhost:6379 \\
    --prefix agent-tools \\
    --type tools

  # List skills in Redis
  python -m py_code_mode.store list \\
    --target redis://localhost:6379 \\
    --prefix agent-skills

  # Pull skills from Redis to local files (review agent-created skills)
  python -m py_code_mode.store pull \\
    --target redis://localhost:6379 \\
    --prefix agent-skills \\
    --dest ./skills-from-redis

  # Compare local vs Redis (what did agent add/change?)
  python -m py_code_mode.store diff \\
    --source ./skills \\
    --target redis://localhost:6379 \\
    --prefix agent-skills
""",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # bootstrap
    boot = subparsers.add_parser(
        "bootstrap",
        help="Push skills or tools from directory to store",
    )
    boot.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to directory containing skill/tool files",
    )
    boot.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    boot.add_argument(
        "--prefix",
        default="skills",
        help="Key prefix (default: skills)",
    )
    boot.add_argument(
        "--type",
        choices=["skills", "tools"],
        default="skills",
        help="Type of items to bootstrap (default: skills)",
    )
    boot.add_argument(
        "--clear",
        action="store_true",
        help="Remove existing items before adding new ones",
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
        default="skills",
        help="Key prefix (default: skills)",
    )
    ls.add_argument(
        "--type",
        choices=["skills", "tools"],
        default="skills",
        help="Type of items to list (default: skills)",
    )

    # pull
    pl = subparsers.add_parser(
        "pull",
        help="Retrieve skills from store to local files",
    )
    pl.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    pl.add_argument(
        "--prefix",
        default="skills",
        help="Key prefix for skills (default: skills)",
    )
    pl.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="Destination directory for skill files",
    )

    # diff
    df = subparsers.add_parser(
        "diff",
        help="Compare local skills vs remote store",
    )
    df.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to local skills directory",
    )
    df.add_argument(
        "--target",
        required=True,
        help="Target store URL (e.g., redis://localhost:6379)",
    )
    df.add_argument(
        "--prefix",
        default="skills",
        help="Key prefix for skills (default: skills)",
    )

    return parser


def main() -> None:
    """Main entry point for store CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "bootstrap":
        bootstrap(args.source, args.target, args.prefix, args.type, args.clear)
    elif args.command == "list":
        list_items(args.target, args.prefix, args.type)
    elif args.command == "pull":
        pull(args.target, args.prefix, args.dest)
    elif args.command == "diff":
        diff(args.source, args.target, args.prefix)


if __name__ == "__main__":
    main()
