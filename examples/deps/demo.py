#!/usr/bin/env python3
"""End-to-end demo of py-code-mode dependency management.

This script demonstrates:
1. Creating a session with FileStorage
2. Using deps.add() to install packages at runtime
3. Using the installed packages immediately
4. Listing and removing dependencies
5. Persistence across sessions

Run with: uv run python demo.py
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from py_code_mode import FileStorage, Session


async def main() -> None:
    # Create temporary storage for the demo
    demo_dir = Path(tempfile.mkdtemp(prefix="deps-demo-"))
    print(f"Demo storage: {demo_dir}\n")
    print("=" * 60)

    storage = FileStorage(base_path=demo_dir)

    # --- Session 1: Add and use dependencies ---
    print("\n[Session 1] Adding and using dependencies\n")

    async with Session(storage=storage) as session:
        # Check initial state
        result = await session.run("deps.list()")
        print(f"1. Initial deps: {result.value}")

        # Add the 'art' package (small ASCII art library)
        print("\n2. Adding 'art' package...")
        result = await session.run('deps.add("art")')
        sync_result = result.value
        print(f"   Installed: {sync_result.installed}")
        print(f"   Already present: {sync_result.already_present}")
        print(f"   Failed: {sync_result.failed}")

        # Use the package immediately
        print("\n3. Using the installed package:")
        result = await session.run('''
import art
print(art.text2art("Hello!"))
''')
        print(result.stdout)

        # Add another package with version specifier
        print("4. Adding 'six>=1.10' (with version specifier)...")
        result = await session.run('deps.add("six>=1.10")')
        print(f"   Result: {result.value}")

        # List all deps
        result = await session.run("deps.list()")
        print(f"\n5. Current deps: {result.value}")

    # --- Session 2: Deps persist across sessions ---
    print("\n" + "=" * 60)
    print("\n[Session 2] Verifying persistence\n")

    async with Session(storage=storage) as session:
        # Deps should still be there
        result = await session.run("deps.list()")
        print(f"1. Deps after restart: {result.value}")

        # Packages are already installed, sync shows already_present
        print("\n2. Calling deps.sync()...")
        result = await session.run("deps.sync()")
        sync_result = result.value
        print(f"   Installed: {sync_result.installed}")
        print(f"   Already present: {sync_result.already_present}")

        # Remove by base name (works even though we added "six>=1.10")
        print("\n3. Removing 'six' (by base name, not full specifier)...")
        result = await session.run('deps.remove("six")')
        print(f"   Removed: {result.value}")

        result = await session.run("deps.list()")
        print(f"\n4. Final deps: {result.value}")

    # --- Show the persisted file ---
    print("\n" + "=" * 60)
    print("\n[Storage] What's on disk:\n")

    requirements_file = demo_dir / "deps" / "requirements.txt"
    if requirements_file.exists():
        print(f"Contents of {requirements_file}:")
        print(requirements_file.read_text())
    else:
        print("(requirements.txt is empty or removed)")

    print("\nDemo complete!")


if __name__ == "__main__":
    asyncio.run(main())
