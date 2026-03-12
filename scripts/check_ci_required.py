from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(".github/workflows/ci.yml")
GATE_JOB = "ci-required"
EXCLUDED_JOBS = {GATE_JOB}


def main() -> int:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
    jobs = workflow.get("jobs", {})

    if GATE_JOB not in jobs:
        print(f"Missing aggregate gate job: {GATE_JOB}")
        return 1

    real_jobs = {job_id for job_id in jobs if job_id not in EXCLUDED_JOBS}

    gate_needs = jobs[GATE_JOB].get("needs", [])
    if isinstance(gate_needs, str):
        gate_needs = [gate_needs]

    gate_needs_set = set(gate_needs)
    missing = sorted(real_jobs - gate_needs_set)
    extra = sorted(gate_needs_set - real_jobs)

    if missing:
        print(f"{GATE_JOB} is missing jobs: {', '.join(missing)}")
    if extra:
        print(f"{GATE_JOB} has stale jobs: {', '.join(extra)}")

    if missing or extra:
        return 1

    print(f"{GATE_JOB} covers all top-level CI jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
