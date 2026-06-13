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
    scope_pending      → agent has confirmed scope, waiting for user to confirm/correct
    researching        → agent is running research (internal, not shown to user)
    review_pending     → brief is displayed; user can ask questions or request changes
    awaiting_commit    → user has said "commit" / "looks good"; one more confirm fires the push
    committed          → brief committed to GitHub; session resets
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
# Intent detection
# ---------------------------------------------------------------------------

# Explicit commit intent — unambiguous phrases only.
# "proceed", "looks good", "stick with it" are NOT here — they're too
# easily said during the review conversation before the user is ready to commit.
COMMIT_PATTERNS = re.compile(
    r"\b(approved?|commit(\s+it|\s+as.is)?|lgtm|ship\s+it|yes\s+commit|push\s+it)\b",
    re.IGNORECASE,
)

# Softer "ready to move forward" phrases — used to advance from review_pending
# to awaiting_commit (where the user is shown what will be committed and asked
# to confirm with an explicit commit phrase).
READY_PATTERNS = re.compile(
    r"\b(proceed|looks?\s+good|stick\s+with|as.is|that\s+works|go\s+ahead|"
    r"yes\s+please|that.s\s+fine|let.s\s+go|good\s+to\s+go|ready)\b",
    re.IGNORECASE,
)


def is_commit(text: str) -> bool:
    return bool(COMMIT_PATTERNS.search(text))


def is_ready(text: str) -> bool:
    return bool(READY_PATTERNS.search(text)) or is_commit(text)


# ---------------------------------------------------------------------------
# Brief helpers
# ---------------------------------------------------------------------------


def get_text_content(response: anthropic.types.Message) -> str:
    """Extract plain text from an API response (skips tool-use blocks)."""
    return "\n".join(block.text for block in response.content if block.type == "text")


def is_valid_brief(content: str) -> bool:
    """
    Confirm content is a real research brief, not a conversational meta-response.
    Requires TL;DR, READY FOR REVIEW, and minimum length.
    """
    has_tldr = "TL;DR" in content or "tl;dr" in content.lower()
    has_review = "READY FOR REVIEW" in content
    is_long = len(content.strip()) > 300
    return has_tldr and has_review and is_long


# ---------------------------------------------------------------------------
# Core agent session
# ---------------------------------------------------------------------------


class ResearchSession:
    """
    Manages one research topic from scope confirmation through GitHub commit.

    State machine:
        idle → scope_pending → review_pending ⇄ (revision loop)
                                     ↓  (user signals ready)
                              awaiting_commit
                                     ↓  (explicit commit phrase)
                                 committed
    """

    def __init__(self):
        self.messages: list[dict] = []
        self.pending_brief: str | None = None
        self.pending_topic: str | None = None
        self.state = "idle"

    # ------------------------------------------------------------------
    # API call with graceful error handling
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
        """Run the agentic loop until the model returns end_turn (no more tool calls)."""
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
        # Store original query as topic slug source — never the agent's restatement
        self.pending_topic = user_query
        self._append_user(
            f"Research request: {user_query}\n\n"
            "Before starting, please confirm the scope per the guardrails: "
            "restate the topic in one sentence and list what you will and will not cover."
        )
        response = self._run_until_text()
        return get_text_content(response)

    # ------------------------------------------------------------------
    # Step 2: User confirms scope → research runs → brief returned
    # ------------------------------------------------------------------

    def confirm_scope(self, user_reply: str) -> str:
        self._append_user(user_reply + "\n\nProceed with research.")
        response = self._run_until_text()
        brief = get_text_content(response)
        # Only store as pending_brief if it's a real brief
        if is_valid_brief(brief):
            self.pending_brief = brief
        self.state = "review_pending"
        return brief

    # ------------------------------------------------------------------
    # Step 3a: Review conversation — user can ask questions or request changes
    # ------------------------------------------------------------------

    def handle_review_reply(self, user_reply: str) -> tuple[str, str]:
        """
        Handle a reply during review_pending.

        Returns (response_text, new_state) so the main loop can print a
        contextual prompt based on what state we're now in.
        """
        # Explicit commit phrase — go straight to commit
        if is_commit(user_reply) and self.pending_brief and self.pending_topic:
            result = self._commit()
            return result, self.state

        # Softer "ready" signal — advance to awaiting_commit for one final confirm
        if (
            is_ready(user_reply)
            and self.pending_brief
            and is_valid_brief(self.pending_brief)
        ):
            self.state = "awaiting_commit"
            slug = self.pending_topic[:60] + (
                "..." if len(self.pending_topic) > 60 else ""
            )
            return (
                f"Ready to commit. Here's what will be pushed:\n\n"
                f"  Topic:  {slug}\n"
                f"  Repo:   {GITHUB_CFG['repo']}\n"
                f"  Branch: {GITHUB_CFG['branch']}\n\n"
                "Type 'commit', 'approved', or 'lgtm' to confirm. "
                "Anything else returns to the brief."
            ), "awaiting_commit"

        # 'redo' — re-run research without re-confirming scope
        if user_reply.strip().lower() == "redo":
            print("\n[Agent — re-running research...]\n")
            self._append_user(
                "Please disregard your last response and produce the full research brief now, "
                "starting with ## TL;DR."
            )
            response = self._run_until_text()
            revised = get_text_content(response)
            if is_valid_brief(revised):
                self.pending_brief = revised
            self.state = "review_pending"
            return revised, "review_pending"

        # Revision request — pass to agent, preserve pending_brief if response is conversational
        self._append_user(user_reply)
        response = self._run_until_text()
        revised = get_text_content(response)
        if is_valid_brief(revised):
            self.pending_brief = revised
        self.state = "review_pending"
        return revised, "review_pending"

    # ------------------------------------------------------------------
    # Step 3b: Awaiting commit confirmation
    # ------------------------------------------------------------------

    def handle_commit_reply(self, user_reply: str) -> tuple[str, str]:
        """
        We've shown the user what will be committed. Explicit commit phrase fires it.
        Anything else drops back to review_pending.
        """
        if is_commit(user_reply):
            result = self._commit()
            return result, self.state

        # Not a commit phrase — back to review
        self.state = "review_pending"
        return (
            "Commit cancelled — brief is still available for review.\n"
            "Make changes, ask questions, or say 'commit' / 'lgtm' when ready."
        ), "review_pending"

    # ------------------------------------------------------------------
    # Step 4: Commit to GitHub
    # ------------------------------------------------------------------

    def _commit(self) -> str:
        assert self.pending_brief and self.pending_topic

        if not is_valid_brief(self.pending_brief):
            self.state = "review_pending"
            return (
                "[Error] Brief content failed validation — missing TL;DR or READY FOR REVIEW.\n"
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
                "The brief has NOT been committed. Check your GITHUB_TOKEN and repo config.\n"
                "Your brief is still here — type 'lgtm' to try again."
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

REVIEW_PROMPT = (
    "  (Ask questions, request changes, say 'ready' to commit, or 'redo' to re-run)\n"
    "You > "
)
COMMIT_PROMPT = (
    "  (Type 'commit', 'approved', or 'lgtm' to push — anything else cancels)\nYou > "
)


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
                reply = input(REVIEW_PROMPT).strip()
                if not reply:
                    continue
                print("\n[Agent...]\n")
                text, _ = session.handle_review_reply(reply)
                print(text)
                print()

            elif session.state == "awaiting_commit":
                reply = input(COMMIT_PROMPT).strip()
                if not reply:
                    continue
                print("\n[Agent...]\n")
                text, _ = session.handle_commit_reply(reply)
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
