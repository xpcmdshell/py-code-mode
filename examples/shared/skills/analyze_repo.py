"""Analyze a GitHub repository - demonstrates multi-tool skill workflow."""

import json


def run(repo: str) -> dict:
    """Analyze a GitHub repository by combining multiple API calls.

    This skill demonstrates the value of prebaked workflows:
    1. Fetches repo metadata (stars, forks, language)
    2. Gets recent commits to understand activity
    3. Checks open issues count
    4. Summarizes everything in one call

    Args:
        repo: Repository in "owner/repo" format (e.g., "anthropics/claude-code")

    Returns:
        Dict with repo analysis including activity metrics
    """
    if "/" not in repo:
        return {"error": "repo must be in 'owner/repo' format"}

    base_url = f"https://api.github.com/repos/{repo}"
    results = {}

    # Step 1: Fetch repo metadata
    repo_raw = tools.curl(url=base_url)
    try:
        repo_data = json.loads(repo_raw)
        results["repo"] = {
            "name": repo_data.get("full_name"),
            "description": repo_data.get("description"),
            "stars": repo_data.get("stargazers_count"),
            "forks": repo_data.get("forks_count"),
            "language": repo_data.get("language"),
            "open_issues": repo_data.get("open_issues_count"),
        }
    except json.JSONDecodeError:
        return {"error": f"Failed to fetch repo: {repo_raw[:200]}"}

    # Step 2: Fetch recent commits
    commits_raw = tools.curl(url=f"{base_url}/commits?per_page=5")
    try:
        commits = json.loads(commits_raw)
        results["recent_commits"] = [
            {
                "sha": c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0][:60],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"][:10],
            }
            for c in commits[:5]
        ]
    except (json.JSONDecodeError, KeyError):
        results["recent_commits"] = "Could not fetch commits"

    # Step 3: Fetch contributors count
    contribs_raw = tools.curl(url=f"{base_url}/contributors?per_page=1")
    try:
        # GitHub returns Link header with total, but we'll just note top contributor
        contribs = json.loads(contribs_raw)
        if isinstance(contribs, list) and contribs:
            results["top_contributor"] = contribs[0].get("login")
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    return results
