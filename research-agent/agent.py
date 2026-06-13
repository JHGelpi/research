"""
agent.py
Technical research agent — main entry point.

Usage:
    python agent.py

Requires:
    ANTHROPIC_API_KEY  — Anthropic API key
    GITHUB_TOKEN       — GitHub PAT with repo write scope (contents: write)

Flow per query:
    1. User submits a research topic
    2. Agent confirms scope (per-query) — user must approve before research begins
    3. Agent researches using web search + any uploaded docs
    4. Agent returns a structured brief with TL;DR, findings, confidence flags, review block
    5. User reviews in chat — replies with approval to trigger GitHub commit
    6. Agent commits to JHGelpi/research/{topic_slug}/{YYYY-MM-DD}.md
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
# Recoverable agent error — printed cleanly, no traceback
# ---------------------------------------------------------------------------


class AgentError(Exception):
    """A known, user-facing error. Printed without a traceback."""

    pass


# ---------------------------------------------------------------------------
# Approval detection
# ---------------------------------------------------------------------------

APPROVAL_PATTERNS = re.compile(
    r"\b(approved?|commit\s+it|lgtm|looks?\s+good|ship\s+it|yes\s+commit|go\s+ahead)\b",
    re.IGNORECASE,
)


def is_approval(text: str) -> bool:
    return bool(APPROVAL_PATTERNS.search(text))


# ---------------------------------------------------------------------------
# Brief extraction helpers
# ---------------------------------------------------------------------------


def get_text_content(response: anthropic.types.Message) -> str:
    """Extract plain text from an API response (skips tool-use blocks)."""
    return "\n".join(block.text for block in response.content if block.type == "text")


# ---------------------------------------------------------------------------
# Core agent loop
# ---------------------------------------------------------------------------


class ResearchSession:
    """
    Manages one research topic from scope confirmation through GitHub commit.
    """

    def __init__(self):
        self.messages: list[dict] = []
        self.pending_brief: str | None = None
        self.pending_topic: str | None = None
        self.state: str = (
            "idle"  # idle → scope_pending → researching → review_pending → committed
        )

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

    # ------------------------------------------------------------------
    # Handle tool use (web_search) — agentic loop
    # ------------------------------------------------------------------

    def _run_until_text(self) -> anthropic.types.Message:
        """
        Keep calling the API until stop_reason is 'end_turn' (no more tool calls).
        The Anthropic SDK returns tool_use blocks; we feed results back automatically.
        Web search is server-side so results come back in tool_result blocks.
        """
        while True:
            response = self._call_api()
            self._append_assistant(response)

            if response.stop_reason == "end_turn":
                return response

            if response.stop_reason == "tool_use":
                # Web search is executed server-side; no client execution needed.
                # Tool results are already included in the next API response
                # when using the built-in web_search server tool.
                # For any custom client-side tools added later, handle here.
                continue

            # Unexpected stop reason — surface and return
            print(
                f"[warn] Unexpected stop_reason: {response.stop_reason}",
                file=sys.stderr,
            )
            return response

    # ------------------------------------------------------------------
    # Step 1: Scope confirmation
    # ------------------------------------------------------------------

    def start(self, user_query: str) -> str:
        """
        Submit the initial query. Agent will confirm scope before researching.
        Returns the agent's scope confirmation message.
        """
        self.state = "scope_pending"
        self._append_user(
            f"Research request: {user_query}\n\n"
            "Before starting, please confirm the scope per the guardrails: "
            "restate the topic in one sentence and list what you will and will not cover."
        )
        # Store the user's original query as the topic — never the agent's
        # restated scope text, which is too long and conversational to slug cleanly.
        self.pending_topic = user_query
        response = self._run_until_text()
        scope_text = get_text_content(response)
        return scope_text

    # ------------------------------------------------------------------
    # Step 2: User confirms scope → agent researches
    # ------------------------------------------------------------------

    def confirm_scope(self, user_reply: str) -> str:
        """
        User has confirmed (or corrected) the scope. Agent proceeds to research.
        Returns the structured brief.
        """
        self.state = "researching"
        self._append_user(user_reply + "\n\nProceed with research.")
        response = self._run_until_text()
        brief = get_text_content(response)
        self.pending_brief = brief
        self.state = "review_pending"
        return brief

    # ------------------------------------------------------------------
    # Step 3: Human review — approval triggers commit
    # ------------------------------------------------------------------

    def handle_review_reply(self, user_reply: str) -> str:
        """
        Handle the user's reply to the READY FOR REVIEW block.
        If approved: commit to GitHub and return confirmation.
        Otherwise: pass reply back to agent for revision.
        """
        if is_approval(user_reply) and self.pending_brief and self.pending_topic:
            return self._commit()

        # Not an approval — treat as a revision request
        self.state = "researching"
        self._append_user(user_reply)
        response = self._run_until_text()
        revised = get_text_content(response)
        self.pending_brief = revised
        self.state = "review_pending"
        return revised

    # ------------------------------------------------------------------
    # Step 4: Commit to GitHub
    # ------------------------------------------------------------------

    def _commit(self) -> str:
        assert self.pending_brief and self.pending_topic

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
                "The brief has NOT been committed. Check your GITHUB_TOKEN and repo config.\n"
                "Your brief is still available — reply 'lgtm' to try again."
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
# CLI entrypoint
# ---------------------------------------------------------------------------


def main():
    print("Research Agent — type your topic, or 'quit' to exit.\n")

    session = ResearchSession()

    while True:
        try:
            if session.state == "idle":
                query = input("Topic > ").strip()
                if query.lower() in ("quit", "exit", "q"):
                    break
                if not query:
                    continue
                print("\n[Agent — confirming scope...]\n")
                scope = session.start(query)
                print(scope)
                print()

            elif session.state == "scope_pending":
                reply = input("You > ").strip()
                if not reply:
                    continue
                print("\n[Agent — researching...]\n")
                brief = session.confirm_scope(reply)
                print(brief)
                print()

            elif session.state == "review_pending":
                reply = input("You > ").strip()
                if not reply:
                    continue
                print("\n[Agent...]\n")
                result = session.handle_review_reply(reply)
                print(result)
                print()

            elif session.state == "committed":
                # Reset for next query
                session = ResearchSession()

            else:
                print(f"[unexpected state: {session.state}]", file=sys.stderr)
                session = ResearchSession()

        except AgentError as exc:
            # Known, recoverable errors — print cleanly and reset to idle
            print(f"\n[Error] {exc}\n", file=sys.stderr)
            session = ResearchSession()

        except KeyboardInterrupt:
            print("\n\nInterrupted. Type 'quit' to exit or start a new topic.\n")
            session = ResearchSession()


if __name__ == "__main__":
    main()
