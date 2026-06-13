# Research Agent

Technical research assistant backed by the Anthropic API. Produces structured
briefs with citations, confidence flags, and a human review step before
committing output to GitHub.

## Repo layout

```
research-agent/
├── agent.py            # Main CLI loop and session state machine
├── github_writer.py    # GitHub commit logic (PyGithub)
├── CLAUDE.md           # Guardrails and behavior contract (loaded as system prompt)
├── config.yaml         # All runtime settings
├── Dockerfile          # Two-stage build, non-root runtime user
├── docker-compose.yml  # Container config with named volume
├── run.sh              # Lifecycle manager — primary entrypoint
├── .env.example        # Fallback secrets template (copy to .env if not using Bitwarden)
└── requirements.txt
```

## Prerequisites

- **Docker Desktop** with WSL2 backend enabled
- **Bitwarden CLI** (`bw`) — preferred secrets manager
- A Bitwarden **Login item** named `research-agent` with two Hidden custom fields:
  - `ANTHROPIC_API_KEY`
  - `GITHUB_TOKEN`

See _Secrets management_ below for setup details.

## Secrets management

Secrets are fetched from Bitwarden at runtime and injected as environment
variables. They are never written to disk inside the container.

### Bitwarden setup (recommended)

**Option A — guided CLI setup:**
```bash
export BW_SESSION=$(bw unlock --raw)
./run.sh bw-setup
```

`bw-setup` prompts for your keys, creates the Bitwarden item in the correct
format, and offers to delete any existing `.env` file.

**Option B — manual Bitwarden setup:**

In the Bitwarden web vault or desktop app:
1. Create a new item → type **Login**, name it `research-agent`
2. Leave username/password blank
3. Add two **Hidden** custom fields:
   - `ANTHROPIC_API_KEY` → your Anthropic API key
   - `GITHUB_TOKEN` → your GitHub fine-grained token
4. Save, then `bw sync` in your terminal

### Fallback: .env file

If Bitwarden is unavailable, `run.sh` automatically falls back to a `.env`
file with a warning. To use this path:

```bash
cp .env.example .env
# edit .env with real values
```

`.env` is gitignored and should never be committed.

### Running with Bitwarden (normal workflow)

```bash
export BW_SESSION=$(bw unlock --raw)
./run.sh
```

Add a convenience alias to `~/.bashrc` to reduce typing:

```bash
alias bw-unlock='export BW_SESSION=$(bw unlock --raw)'
```

Then the daily workflow is just:

```bash
bw-unlock && ./run.sh
```

## GitHub token scope

Go to github.com → Settings → Developer settings → Personal access tokens → Fine-grained tokens.

Required permissions on `JHGelpi/research`:
- **Contents**: Read and write
- **Metadata**: Read (auto-granted)

That's the minimum. Do not grant broader scopes.

## Usage

```bash
./run.sh
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

## run.sh commands

| Command | What it does |
|---|---|
| `./run.sh` | Start the agent (build if needed) |
| `./run.sh build` | Force-rebuild the image |
| `./run.sh shell` | Open bash inside the container (debug) |
| `./run.sh stop` | Stop the container |
| `./run.sh clean` | Remove container, image, and volume |
| `./run.sh logs` | Tail logs from the last run |
| `./run.sh bw-setup` | Guided Bitwarden secrets setup |

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
