"""
agent.py
Technical research agent — main entry point.

Usage:
    python agent.py

Requires:
    ANTHROPIC_API_KEY  — Anthropic API key
    GITHUB_TOKEN       — GitHub PAT with repo write scope (contents: write)

Session states:
    idle               → waiting for a topic
    scope_pending      → agent confirmed scope, waiting for user to confirm/correct
    review_pending     → brief is displayed; user can ask questions or request changes
    awaiting_commit    → user typed 'done'; one explicit commit command fires the push
    committed          → brief committed; session resets

CLI commands (only active in review_pending):
    done / save        → advance to awaiting_commit (shows what will be pushed)
    redo               → re-run research without re-confirming scope
    quit / exit / q    → exit the agent

In awaiting_commit:
    commit / lgtm / approved / yes   → fire the commit
    anything else                    → return to review_pending
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import anthropic
import yaml
from github_writer import commit_brief

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

CLAUDE_MD_PATH = Path(__file__).parent / "CLAUDE.md"
with open(CLAUDE_MD_PATH) as f:
    SYSTEM_PROMPT = f.read()

GITHUB_CFG = CONFIG["github"]
AGENT_CFG = CONFIG["agent"]

# ---------------------------------------------------------------------------
# Anthropic client + tools
# ---------------------------------------------------------------------------

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

TOOLS = [
    {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 10,
    }
]

# ---------------------------------------------------------------------------
# Recoverable agent error
# ---------------------------------------------------------------------------


class AgentError(Exception):
    pass


# ---------------------------------------------------------------------------
# Intent detection — explicit CLI commands only, no natural language matching
# ---------------------------------------------------------------------------

# User is done reviewing and wants to commit
DONE_COMMANDS = {"done", "save"}

# Final commit confirmation (in awaiting_commit state only)
COMMIT_COMMANDS = {"commit", "lgtm", "approved", "yes"}

# Exit
EXIT_COMMANDS = {"quit", "exit", "q"}


# ---------------------------------------------------------------------------
# Brief helpers
# ---------------------------------------------------------------------------


def get_text_content(response: anthropic.types.Message) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text")


def is_valid_brief(content: str) -> bool:
    """
    Confirm content is a real research brief, not a conversational response.
    Requires a TL;DR section and minimum length. READY FOR REVIEW is checked
    loosely since the agent may render it inside or outside a code fence.
    """
    has_tldr = "TL;DR" in content or "tl;dr" in content.lower()
    has_review = (
        "READY FOR REVIEW" in content
        or "ready for review" in content.lower()
        or "## Sources" in content  # sources section is an equally strong signal
        or "## Gaps" in content
    )
    is_long = len(content.strip()) > 300
    return has_tldr and has_review and is_long


# ---------------------------------------------------------------------------
# Core agent session
# ---------------------------------------------------------------------------


class ResearchSession:
    def __init__(self):
        self.messages: list[dict] = []
        self.pending_brief: str | None = None
        self.pending_topic: str | None = None
        self.state = "idle"

    # ------------------------------------------------------------------
    # API call
    # ------------------------------------------------------------------

    def _call_api(self) -> anthropic.types.Message:
        try:
            return client.messages.create(
                model=AGENT_CFG["model"],
                max_tokens=AGENT_CFG["max_tokens"],
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.messages,
            )
        except anthropic.AuthenticationError:
            raise AgentError(
                "Invalid API key. Check ANTHROPIC_API_KEY in Bitwarden or your .env fallback."
            )
        except anthropic.PermissionDeniedError:
            raise AgentError(
                "API key lacks permission for this model or feature.\n"
                "  Check your account at console.anthropic.com."
            )
        except anthropic.BadRequestError as exc:
            if "credit balance" in str(exc).lower():
                raise AgentError(
                    "Your Anthropic credit balance is too low.\n"
                    "  Add credits at: console.anthropic.com → Plans & Billing"
                )
            raise AgentError(f"Bad request sent to API: {exc}")
        except anthropic.RateLimitError:
            raise AgentError(
                "Rate limit reached. Wait a moment and try again.\n"
                "  If this recurs, check your usage tier at console.anthropic.com."
            )
        except anthropic.APIConnectionError:
            raise AgentError(
                "Could not reach the Anthropic API. Check your internet connection."
            )
        except anthropic.APIStatusError as exc:
            raise AgentError(f"Anthropic API error {exc.status_code}: {exc.message}")

    def _append_user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def _append_assistant(self, response: anthropic.types.Message):
        self.messages.append({"role": "assistant", "content": response.content})

    def _run_until_text(self) -> anthropic.types.Message:
        while True:
            response = self._call_api()
            self._append_assistant(response)
            if response.stop_reason == "end_turn":
                return response
            if response.stop_reason == "tool_use":
                continue
            print(
                f"[warn] Unexpected stop_reason: {response.stop_reason}",
                file=sys.stderr,
            )
            return response

    # ------------------------------------------------------------------
    # Step 1: Scope confirmation
    # ------------------------------------------------------------------

    def start(self, user_query: str) -> str:
        self.state = "scope_pending"
        self.pending_topic = user_query
        self._append_user(
            f"Research request: {user_query}\n\n"
            "Before starting, please confirm the scope per the guardrails: "
            "restate the topic in one sentence and list what you will and will not cover."
        )
        response = self._run_until_text()
        return get_text_content(response)

    # ------------------------------------------------------------------
    # Step 2: Scope confirmed → research
    # ------------------------------------------------------------------

    def confirm_scope(self, user_reply: str) -> str:
        self._append_user(user_reply + "\n\nProceed with research.")
        response = self._run_until_text()
        brief = get_text_content(response)
        if is_valid_brief(brief):
            self.pending_brief = brief
        self.state = "review_pending"
        return brief

    # ------------------------------------------------------------------
    # Step 3a: Review — free-form conversation, explicit commands only
    # ------------------------------------------------------------------

    def handle_review_reply(self, user_reply: str) -> str:
        cmd = user_reply.strip().lower()

        # 'done' or 'save' → advance to awaiting_commit
        if cmd in DONE_COMMANDS:
            if not self.pending_brief or not is_valid_brief(self.pending_brief):
                return (
                    "[Error] No valid brief is ready to commit. "
                    "Type 'redo' to re-run research."
                )
            self.state = "awaiting_commit"
            slug = self.pending_topic[:60] + (
                "..." if len(self.pending_topic) > 60 else ""
            )
            return (
                f"Ready to commit. Here's what will be pushed:\n\n"
                f"  Topic:  {slug}\n"
                f"  Repo:   {GITHUB_CFG['repo']}\n"
                f"  Branch: {GITHUB_CFG['branch']}\n\n"
                "Type 'commit', 'lgtm', 'approved', or 'yes' to confirm.\n"
                "Anything else returns you to the brief."
            )

        # 'redo' → re-run research
        if cmd == "redo":
            print("\n[Agent — re-running research...]\n")
            self._append_user(
                "Please disregard your last response and produce the full research brief now, "
                "starting with ## TL;DR. Include a ## Sources section at the end with "
                "numbered full URLs for every source cited."
            )
            response = self._run_until_text()
            revised = get_text_content(response)
            if is_valid_brief(revised):
                self.pending_brief = revised
            self.state = "review_pending"
            return revised

        # Everything else → pass to agent as a question or revision request
        self._append_user(user_reply)
        response = self._run_until_text()
        revised = get_text_content(response)
        if is_valid_brief(revised):
            self.pending_brief = revised
        self.state = "review_pending"
        return revised

    # ------------------------------------------------------------------
    # Step 3b: Awaiting final commit confirmation
    # ------------------------------------------------------------------

    def handle_commit_reply(self, user_reply: str) -> str:
        cmd = user_reply.strip().lower()

        if cmd in COMMIT_COMMANDS:
            return self._commit()

        # Not a commit command — back to review
        self.state = "review_pending"
        return (
            "Commit cancelled — returning to review.\n"
            "Ask questions, request changes, or type 'done' when ready to commit."
        )

    # ------------------------------------------------------------------
    # Step 4: Commit to GitHub
    # ------------------------------------------------------------------

    def _commit(self) -> str:
        assert self.pending_brief and self.pending_topic

        if not is_valid_brief(self.pending_brief):
            self.state = "review_pending"
            return (
                "[Error] Brief failed validation — missing TL;DR or READY FOR REVIEW.\n"
                "Type 'redo' to re-run research, or describe what you want changed."
            )

        try:
            result = commit_brief(
                topic=self.pending_topic,
                content=self.pending_brief,
                repo_name=GITHUB_CFG["repo"],
                branch=GITHUB_CFG["branch"],
                base_path=GITHUB_CFG.get("base_path", ""),
            )
        except Exception as exc:
            self.state = "review_pending"
            return (
                f"[ERROR] GitHub commit failed: {exc}\n"
                "Brief not committed. Check your GITHUB_TOKEN and repo config.\n"
                "Type 'done' to try again."
            )

        self.state = "committed"
        return (
            f"Brief committed to GitHub.\n\n"
            f"  Path:    {result['path']}\n"
            f"  Commit:  {result['sha'][:7]}\n"
            f"  URL:     {result['url']}\n\n"
            "Start a new query any time."
        )


# ---------------------------------------------------------------------------
# CLI prompts
# ---------------------------------------------------------------------------

SCOPE_PROMPT = "You > "

REVIEW_PROMPT = (
    "\n  Commands: 'done' to commit  |  'redo' to re-run  |  "
    "or just ask a question / request a change\n"
    "You > "
)

COMMIT_PROMPT = (
    "\n  Type 'commit', 'lgtm', 'approved', or 'yes' to push  |  "
    "anything else cancels\n"
    "You > "
)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main():
    print("Research Agent — type your topic, or 'quit' to exit.\n")
    session = ResearchSession()

    while True:
        try:
            if session.state == "idle":
                query = input("Topic > ").strip()
                if query.lower() in EXIT_COMMANDS:
                    break
                if not query:
                    continue
                print("\n[Agent — confirming scope...]\n")
                scope = session.start(query)
                print(scope)
                print()

            elif session.state == "scope_pending":
                reply = input(SCOPE_PROMPT).strip()
                if not reply:
                    continue
                print("\n[Agent — researching...]\n")
                brief = session.confirm_scope(reply)
                print(brief)
                print()

            elif session.state == "review_pending":
                reply = input(REVIEW_PROMPT).strip()
                if not reply:
                    continue
                if reply.lower() in EXIT_COMMANDS:
                    break
                print("\n[Agent...]\n")
                text = session.handle_review_reply(reply)
                print(text)
                print()

            elif session.state == "awaiting_commit":
                reply = input(COMMIT_PROMPT).strip()
                if not reply:
                    continue
                print("\n[Agent...]\n")
                text = session.handle_commit_reply(reply)
                print(text)
                print()

            elif session.state == "committed":
                session = ResearchSession()

            else:
                print(f"[unexpected state: {session.state}]", file=sys.stderr)
                session = ResearchSession()

        except AgentError as exc:
            print(f"\n[Error] {exc}\n", file=sys.stderr)
            session = ResearchSession()

        except KeyboardInterrupt:
            print("\n\nInterrupted. Type 'quit' to exit or start a new topic.\n")
            session = ResearchSession()


if __name__ == "__main__":
    main()
