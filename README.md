# Research Agent

Technical research assistant backed by the Anthropic API. Produces structured
briefs with citations, confidence flags, and a human review step before
committing output to GitHub.

## Repo layout

```
research-agent/
├── agent.py          # Main CLI loop and session state machine
├── github_writer.py  # GitHub commit logic (PyGithub)
├── CLAUDE.md         # Guardrails and behavior contract (loaded as system prompt)
├── config.yaml       # All runtime settings
└── requirements.txt
```

## Setup (WSL2)

```bash
# 1. Clone / copy this folder into your WSL2 home
cd ~
# (copy or git clone the research-agent folder here)

# 2. Create a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 3. Install deps
pip install -r requirements.txt

# 4. Set environment variables — add to ~/.bashrc or a .env file
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."        # needs: repo → contents (read + write)
```

## GitHub token scope

Go to github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens.

Required permissions on `JHGelpi/research`:
- **Contents**: Read and write
- **Metadata**: Read (auto-granted)

That's the minimum. Do not grant broader scopes.

## Usage

```bash
python agent.py
```

**Session flow:**

```
Topic > streaming orchestration patterns 2025

[Agent — confirming scope...]
Topic: streaming orchestration patterns in 2025
I will cover: real-time event processing frameworks, Kafka/Flink ecosystem
  updates, new streaming abstractions in cloud platforms.
I will not cover: batch processing, historical comparisons pre-2024.
Confirm?

You > confirmed

[Agent — researching...]
## TL;DR
...

## Key findings
...

READY FOR REVIEW
Low-confidence items: none
Open questions for human: none

You > lgtm

[Agent...]
Brief committed to GitHub.
  Path:    streaming-orchestration-patterns-2025/2025-06-13.md
  Commit:  a3f9c12
  URL:     https://github.com/JHGelpi/research/blob/main/...
```

## Customizing guardrails

Edit `CLAUDE.md` to adjust:
- Scope confirmation behavior
- Source age cutoff (12 months default)
- Output format / sections
- Permitted write actions

Edit `config.yaml` to adjust:
- Model, max_tokens
- GitHub repo / branch / base path
- Source age threshold

## Adding Google Drive as a source

The agent currently uses web search. To add Drive:
1. Enable the Drive MCP in your Claude.ai project for prototyping.
2. For the Python agent, use the Google Drive API with a service account
   and add a `drive_reader.py` tool alongside `github_writer.py`.
3. Add it to TOOLS in `agent.py` as a custom tool definition.
