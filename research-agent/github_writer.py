"""
github_writer.py
Handles committing approved research briefs to JHGelpi/research.
File structure: topic_folders  →  {topic_slug}/{YYYY-MM-DD}.md
Commit trigger: auto_after_approval (called from agent.py after user approves)
"""

from __future__ import annotations

import os
import re
import textwrap
from datetime import date
from pathlib import PurePosixPath

from github import Github, GithubException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert a topic string to a safe directory name."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text or "untitled"


def _build_path(base_path: str, topic: str, run_date: date | None = None) -> str:
    """
    Build the repo-relative file path.
    Example: topic_folders → "streaming-orchestration/2025-06-13.md"
    """
    run_date = run_date or date.today()
    slug = _slugify(topic)
    filename = f"{run_date.isoformat()}.md"
    parts = [p for p in [base_path, slug, filename] if p]
    return str(PurePosixPath(*parts))


def _build_commit_message(topic: str, run_date: date | None = None) -> str:
    run_date = run_date or date.today()
    slug = _slugify(topic)
    return f"research: {slug} {run_date.isoformat()}"


def _add_frontmatter(content: str, topic: str, run_date: date) -> str:
    """Prepend YAML frontmatter so briefs are indexable."""
    frontmatter = textwrap.dedent(f"""\
        ---
        topic: {topic}
        date: {run_date.isoformat()}
        agent: research-agent
        ---

    """)
    return frontmatter + content


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def commit_brief(
    topic: str,
    content: str,
    repo_name: str = "JHGelpi/research",
    branch: str = "main",
    base_path: str = "",
    run_date: date | None = None,
    github_token: str | None = None,
) -> dict:
    """
    Commit a research brief to GitHub.

    Args:
        topic:        Human-readable topic string (used for slug + frontmatter).
        content:      Full markdown content of the brief.
        repo_name:    GitHub "owner/repo" string.
        branch:       Target branch (default: main).
        base_path:    Optional prefix folder inside the repo.
        run_date:     Override today's date (useful for testing).
        github_token: PAT with repo write scope. Falls back to GITHUB_TOKEN env var.

    Returns:
        dict with keys: path, sha, url, committed (bool)

    Raises:
        ValueError:  Missing token or bad config.
        GithubException: API-level errors from PyGithub.
    """
    token = github_token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "GitHub token required. Set GITHUB_TOKEN env var or pass github_token=."
        )

    run_date = run_date or date.today()
    path = _build_path(base_path, topic, run_date)
    commit_message = _build_commit_message(topic, run_date)
    full_content = _add_frontmatter(content, topic, run_date)

    g = Github(token)
    repo = g.get_repo(repo_name)

    # Check if file already exists (update vs create)
    try:
        existing = repo.get_contents(path, ref=branch)
        result = repo.update_file(
            path=path,
            message=commit_message,
            content=full_content,
            sha=existing.sha,
            branch=branch,
        )
        action = "updated"
    except GithubException as exc:
        if exc.status != 404:
            raise
        result = repo.create_file(
            path=path,
            message=commit_message,
            content=full_content,
            branch=branch,
        )
        action = "created"

    commit = result["commit"]
    html_url = f"https://github.com/{repo_name}/blob/{branch}/{path}"

    return {
        "committed": True,
        "action": action,
        "path": path,
        "sha": commit.sha,
        "url": html_url,
        "commit_message": commit_message,
    }
