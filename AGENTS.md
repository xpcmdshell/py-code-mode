# Agent Instructions

## Agent-Managed Beads (User Preference)

**The user does NOT interact with bd directly.** Agent handles all issue tracking automatically.

### On session start:
1. Run `bd ready` to check available tasks
2. Present options to user in plain language
3. If no tasks exist, ask what to work on and create issues

### During work:
- Create parent issues for features: `bd create "Feature: X" -p 0`
- Create sub-tasks: `bd create "Subtask" -p 1 --parent <id>`
- Link blockers: `bd dep add <blocked-id> <blocker-id>`
- Claim work: `bd update <id> --status in_progress`

### On task completion:
- Close finished work: `bd close <id>`
- Run `bd ready` to suggest next task
- Present next options to user

### Key principle:
User says what they want in plain English. Agent translates to bd commands, executes them, and reports back in plain English.

---

## Branch Policy

**The `main` branch is protected.** You cannot push directly to main.

**ALWAYS create a feature branch before making changes:**
```bash
git checkout -b feature/description-of-work
# ... make changes ...
git push -u origin feature/description-of-work
# Then create a PR
```

---

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
```

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

