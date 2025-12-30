#!/usr/bin/env python3
"""Bootstrap Redis with tools, skills, and dependencies for Azure Container Apps.

This script populates Redis with the necessary configuration before deploying
Container Apps. It loads tools and skills from the shared examples directory
and pre-configures Python dependencies.

Usage:
    python bootstrap_redis.py \
        --redis-url "rediss://:key@host:6380/0" \
        --prefix "pycodemode" \
        --tools-path "../shared/tools" \
        --skills-path "../shared/skills" \
        --deps "requests>=2.31" "pandas>=2.0" "beautifulsoup4>=4.12"

Or with environment variable:
    REDIS_URL="rediss://..." python bootstrap_redis.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import redis
import yaml

from py_code_mode.deps import RedisDepsStore
from py_code_mode.skills import PythonSkill, RedisSkillStore
from py_code_mode.storage.redis_tools import RedisToolStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def load_tools(r: redis.Redis, tools_path: Path, prefix: str) -> int:
    """Load tool YAML files into Redis.

    Args:
        r: Redis client instance.
        tools_path: Path to directory containing tool YAML files.
        prefix: Redis key prefix for tools.

    Returns:
        Number of tools loaded.
    """
    if not tools_path.exists():
        logger.warning("Tools path does not exist: %s", tools_path)
        return 0

    store = RedisToolStore(r, prefix=prefix)
    count = 0

    for tool_file in sorted(tools_path.glob("*.yaml")):
        try:
            with open(tool_file) as f:
                tool_config = yaml.safe_load(f)

            if not tool_config:
                logger.warning("Empty tool config in %s, skipping", tool_file.name)
                continue

            name = tool_config.get("name")
            if not name:
                logger.warning("Tool in %s missing 'name' field, skipping", tool_file.name)
                continue

            store.add(name, tool_config)
            logger.info("  Loaded tool: %s", name)
            count += 1

        except yaml.YAMLError as e:
            logger.error("Failed to parse %s: %s", tool_file.name, e)
        except OSError as e:
            logger.error("Failed to read %s: %s", tool_file.name, e)

    return count


def load_skills(r: redis.Redis, skills_path: Path, prefix: str) -> int:
    """Load skill Python files into Redis.

    Args:
        r: Redis client instance.
        skills_path: Path to directory containing skill .py files.
        prefix: Redis key prefix for skills.

    Returns:
        Number of skills loaded.
    """
    if not skills_path.exists():
        logger.warning("Skills path does not exist: %s", skills_path)
        return 0

    store = RedisSkillStore(r, prefix=prefix)
    count = 0
    skills_to_save: list[PythonSkill] = []

    for skill_file in sorted(skills_path.glob("*.py")):
        # Skip private files
        if skill_file.name.startswith("_"):
            continue

        try:
            skill = PythonSkill.from_file(skill_file)
            skills_to_save.append(skill)
            logger.info("  Loaded skill: %s", skill.name)
            count += 1

        except (OSError, SyntaxError, ValueError) as e:
            logger.error("Failed to load skill from %s: %s", skill_file.name, e)

    # Use batch save for efficiency
    if skills_to_save:
        store.save_batch(skills_to_save)

    return count


def configure_deps(r: redis.Redis, deps: list[str], prefix: str) -> int:
    """Configure Python dependencies in Redis.

    Args:
        r: Redis client instance.
        deps: List of package specifications (e.g., ["requests>=2.31", "pandas>=2.0"]).
        prefix: Redis key prefix for deps.

    Returns:
        Number of dependencies configured.
    """
    if not deps:
        return 0

    store = RedisDepsStore(r, prefix=prefix)
    count = 0

    for dep in deps:
        try:
            store.add(dep)
            logger.info("  Configured dep: %s", dep)
            count += 1
        except ValueError as e:
            logger.error("Invalid dependency %s: %s", dep, e)

    return count


def main() -> int:
    """Bootstrap Redis with tools, skills, and dependencies.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = argparse.ArgumentParser(
        description="Bootstrap Redis with tools, skills, and dependencies.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL"),
        help="Redis URL (default: REDIS_URL environment variable)",
    )
    parser.add_argument(
        "--prefix",
        default="pycodemode",
        help="Redis key prefix (default: pycodemode)",
    )
    parser.add_argument(
        "--tools-path",
        type=Path,
        default=Path(__file__).parent.parent / "shared" / "tools",
        help="Path to tools directory (default: ../shared/tools)",
    )
    parser.add_argument(
        "--skills-path",
        type=Path,
        default=Path(__file__).parent.parent / "shared" / "skills",
        help="Path to skills directory (default: ../shared/skills)",
    )
    parser.add_argument(
        "--deps",
        nargs="*",
        default=["requests>=2.31", "beautifulsoup4>=4.12", "pandas>=2.0"],
        help="Python dependencies to pre-configure (default: requests, beautifulsoup4, pandas)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing tools, skills, and deps before loading",
    )

    args = parser.parse_args()

    if not args.redis_url:
        logger.error("Redis URL required. Set --redis-url or REDIS_URL environment variable.")
        return 1

    # Connect to Redis
    try:
        r = redis.from_url(args.redis_url)
        r.ping()
        logger.info("Connected to Redis")
    except redis.RedisError as e:
        logger.error("Failed to connect to Redis: %s", e)
        return 1

    # Derive prefixes for each store type
    tools_prefix = f"{args.prefix}:tools"
    skills_prefix = f"{args.prefix}:skills"
    deps_prefix = f"{args.prefix}:deps"

    # Clear existing data if requested
    if args.clear:
        logger.info("Clearing existing data...")
        tool_store = RedisToolStore(r, prefix=tools_prefix)
        skill_store = RedisSkillStore(r, prefix=skills_prefix)
        deps_store = RedisDepsStore(r, prefix=deps_prefix)

        # Clear by deleting the hash keys
        for tool_name in tool_store.list():
            tool_store.remove(tool_name)
        for skill in skill_store.list_all():
            skill_store.delete(skill.name)
        deps_store.clear()

        logger.info("Cleared existing data")

    # Load tools
    logger.info("Loading tools from %s...", args.tools_path)
    tools_count = load_tools(r, args.tools_path, tools_prefix)
    logger.info("Loaded %d tools", tools_count)

    # Load skills
    logger.info("Loading skills from %s...", args.skills_path)
    skills_count = load_skills(r, args.skills_path, skills_prefix)
    logger.info("Loaded %d skills", skills_count)

    # Configure deps
    logger.info("Configuring dependencies...")
    deps_count = configure_deps(r, args.deps, deps_prefix)
    logger.info("Configured %d deps", deps_count)

    # Summary
    logger.info("Bootstrap complete:")
    logger.info("  Tools:  %d (prefix: %s)", tools_count, tools_prefix)
    logger.info("  Skills: %d (prefix: %s)", skills_count, skills_prefix)
    logger.info("  Deps:   %d (prefix: %s)", deps_count, deps_prefix)

    return 0


if __name__ == "__main__":
    sys.exit(main())
