# Getting started with the research agent

This agent is a command-line tool that researches technical topics for you, produces a structured summary, and saves the result to GitHub — automatically. This guide will walk you through everything from zero.

---

## What does it actually do?

You give it a topic. It searches the web, reads recent sources, and writes you a structured research brief with citations. Before it does any of that, it confirms what it's going to look into so you're not surprised by the output. After it's done, you review the brief in your terminal and decide whether to save it. If you approve, it commits the file directly to the `JHGelpi/research` GitHub repository.

No copy-paste, no manual filing. You read → approve → it saves.

---

## Before you begin

You need three things installed on your machine:

**Docker Desktop** — this is the software that runs the agent in an isolated container. Download it from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop). During installation, if it asks about WSL 2 integration, say yes.

**Git** (optional but recommended) — for cloning this repository. Download from [git-scm.com](https://git-scm.com).

**A terminal** — on Windows, use the WSL 2 terminal (search "Ubuntu" or "WSL" in your Start menu). On Mac, use Terminal.

---

## One-time setup

You only do this once.

### Step 1 — Get the files

If you have Git:
```
git clone https://github.com/JHGelpi/research.git
cd research/research-agent
```

If you don't have Git, download the repository as a ZIP from GitHub, unzip it, and open a terminal in the `research-agent` folder.

### Step 2 — Create your credentials file

The agent needs two secret keys to work. These stay on your machine and are never uploaded anywhere.

In the `research-agent` folder, find the file called `.env.example`. Make a copy of it and name the copy `.env`:

```
cp .env.example .env
```

Now open `.env` in any text editor. You'll see two lines:

```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
```

You need to replace the placeholders with your real keys. The next two steps explain where to get them.

### Step 3 — Get your Anthropic API key

This is what lets the agent use Claude to do research.

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in (or create an account).
2. Click **API Keys** in the left sidebar.
3. Click **Create Key**, give it a name like "research-agent", and copy the key it shows you.
4. Paste it into `.env` replacing `sk-ant-...`, so the line looks like:
   ```
   ANTHROPIC_API_KEY=sk-ant-apiXXXXXXXXXXXXXX
   ```

> The key is only shown once. If you lose it, you'll need to create a new one.

### Step 4 — Get your GitHub token

This is what lets the agent save research briefs to GitHub.

1. Go to [github.com](https://github.com) and sign in.
2. Click your profile photo (top right) → **Settings**.
3. Scroll down the left sidebar to **Developer settings** → **Personal access tokens** → **Fine-grained tokens**.
4. Click **Generate new token**.
5. Give it a name like "research-agent".
6. Under **Repository access**, choose **Only select repositories** and pick `JHGelpi/research`.
7. Under **Permissions → Repository permissions**, find **Contents** and set it to **Read and write**.
8. Click **Generate token** and copy it.
9. Paste it into `.env` replacing `ghp_...`, so the line looks like:
   ```
   GITHUB_TOKEN=ghp_XXXXXXXXXXXXXXXXXXXX
   ```

Save the `.env` file.

### Step 5 — Start Docker Desktop

Open Docker Desktop and wait for it to finish starting up. You'll know it's ready when the whale icon in your taskbar (Windows) or menu bar (Mac) stops animating.

---

## Running the agent

Open your terminal in the `research-agent` folder and run:

```
./run.sh
```

The very first time you run this, it will take a minute or two to build the agent. You'll see a lot of text scroll past — that's normal. Subsequent runs start in a few seconds.

When the agent is ready, you'll see:

```
Research Agent — type your topic, or 'quit' to exit.

Topic >
```

---

## A complete example session

Here's what a full session looks like, start to finish.

**You type a topic:**
```
Topic > container orchestration tools compared to Kubernetes in 2025
```

**The agent confirms what it's going to research before doing anything:**
```
[Agent — confirming scope...]

Topic: A comparison of container orchestration tools versus Kubernetes in 2025.

I will cover: current alternatives to Kubernetes (Nomad, Docker Swarm, k3s, etc.),
their positioning relative to Kubernetes, recent developments as of 2025.

I will not cover: general Docker usage, Kubernetes internals, pre-2024 history.

Confirm?
```

**You confirm — or correct it if it misunderstood:**
```
You > confirmed
```

If the agent misunderstood your topic, say so here and it will adjust before researching. For example: "Actually, focus only on tools suited for small teams, not enterprise."

**The agent researches and writes the brief:**
```
[Agent — researching...]

## TL;DR
Kubernetes remains dominant in 2025 but lighter alternatives like k3s and Nomad
have gained significant adoption for teams prioritizing operational simplicity
over ecosystem breadth...

## Key findings
- k3s 1.29 reached production-ready status for edge deployments [CNCF, 2025-02]
- HashiCorp Nomad 1.8 introduced native Kubernetes-compatible scheduling [HashiCorp Blog, 2025-01]
- Docker Swarm usage declined 34% year-over-year per CNCF survey [OLDER SOURCE — 2024-03]

## Confidence flags
- HIGH: k3s and Nomad findings — primary vendor sources, published 2025
- MEDIUM: Docker Swarm decline — survey data, slightly outside 12-month window [OLDER SOURCE]

## Gaps / next questions
- Pricing comparison not available from public sources
- No independent benchmarks found for Nomad vs k3s at scale

---
READY FOR REVIEW
Low-confidence items: Docker Swarm decline figure [OLDER SOURCE — 2024-03]
Open questions for human: Should the OLDER SOURCE finding be included or removed?
```

**You review it and decide what to do.**

If you want to save it:
```
You > lgtm
```

If you want a change first:
```
You > Remove the Docker Swarm section, the older source isn't useful here
```

The agent will revise and show you the updated brief, then wait for your approval again.

**Once approved, it commits to GitHub:**
```
[Agent...]

Brief committed to GitHub.

  Path:    container-orchestration-tools-compared-to-kubernetes-in-2025/2025-06-13.md
  Commit:  a3f9c12
  URL:     https://github.com/JHGelpi/research/blob/main/container-orchestration...

Start a new query any time.
```

The file is now in the repository. You can view it at the URL the agent prints.

---

## Approval phrases

When the agent shows `READY FOR REVIEW`, it's waiting for you to either approve or request changes. To approve and trigger the commit, say any of the following:

- `approved`
- `lgtm`
- `looks good`
- `commit it`
- `ship it`
- `go ahead`

To request changes instead, just describe what you want changed in plain language.

---

## Understanding the brief format

Every brief follows the same structure so you always know what you're reading.

**TL;DR** — two or three sentences summarizing the whole thing. Read this first.

**Key findings** — the substance of the research, each bullet with a citation showing the source and date. Citations look like `[Source Name, YYYY-MM]`. If a finding couldn't be cited, you'll see `[UNVERIFIED — needs source]`.

**Confidence flags** — the agent rates its own certainty. HIGH means a primary source published within the last 12 months. MEDIUM means a secondary source, or a primary source that's a bit older. LOW means the finding is inferred with no direct citation. Sources older than 12 months are flagged with `[OLDER SOURCE]`.

**Gaps / next questions** — things the agent couldn't find or questions it couldn't answer. Useful for knowing what to dig into further.

**READY FOR REVIEW** — always the last thing, always lists any low-confidence items so you know exactly what to scrutinize before approving.

---

## Tips for good results

**Be specific with your topic.** "AI in 2025" will produce a vague brief. "Retrieval-augmented generation performance benchmarks 2025" will produce a tight, useful one.

**Use the scope confirmation step.** This is your chance to catch misunderstandings before the agent spends time on the wrong thing. Don't just type `confirmed` reflexively — read what it says it's going to cover.

**Ask for revisions freely.** The agent won't commit anything without your approval. If the brief is missing something or includes something you don't want, say so. You can go back and forth as many times as you need before approving.

**Don't approve findings you're unsure about.** If something looks wrong or a citation seems off, ask the agent to verify it or remove it before committing.

---

## Other commands

You don't have to run the agent to manage it. From the `research-agent` folder:

| Command | What it does |
|---|---|
| `./run.sh` | Start the agent |
| `./run.sh build` | Rebuild the agent after code changes |
| `./run.sh shell` | Open a terminal inside the container (for troubleshooting) |
| `./run.sh stop` | Stop the container |
| `./run.sh clean` | Full reset — removes everything, start fresh |
| `./run.sh logs` | Show output from the last run |

---

## Troubleshooting

**"Missing or placeholder values in .env"** — your `.env` file still has the example text instead of real keys. Open `.env` and replace the placeholder values with your actual Anthropic API key and GitHub token.

**"docker not found"** — Docker Desktop isn't installed or isn't running. Start Docker Desktop and wait for it to be ready before running `./run.sh`.

**The agent starts but produces no results / errors on search** — web search must be enabled for your Anthropic account. Log in to [console.anthropic.com](https://console.anthropic.com), go to Settings, and check that web search is enabled.

**"GitHub commit failed"** — your GitHub token may have expired (they default to 30–90 days) or may not have the right permissions. Go back to Step 4 and generate a new token, then update your `.env` file.

**The agent is stuck and not responding** — press `Ctrl+C` to exit, then `./run.sh` to start a fresh session.

---

## Where your research lives

Every approved brief is saved to [github.com/JHGelpi/research](https://github.com/JHGelpi/research), organized by topic. Each topic gets its own folder, and each research session gets a file named by date:

```
research/
├── container-orchestration-tools/
│   └── 2025-06-13.md
├── streaming-architecture-patterns/
│   └── 2025-06-20.md
└── research-agent/
    └── (the agent code lives here)
```

You can browse, search, and share these files directly on GitHub.
