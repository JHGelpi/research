#!/usr/bin/env bash
# run.sh — Research Agent container lifecycle manager
#
# Usage:
#   ./run.sh              Start the agent (build if needed, attach to stdin)
#   ./run.sh build        Force-rebuild the image
#   ./run.sh stop         Stop and remove the container
#   ./run.sh logs         Tail logs from the last run
#   ./run.sh clean        Remove container, image, and named volume
#   ./run.sh shell        Drop into a bash shell inside the container (debug)
#
# Future hooks:
#   - Pre-flight checks (token validation, network, Drive auth) go in check_env()
#   - Notifications, logging pipelines, or CI triggers go in post_run()
#   - Additional subcommands extend the case block at the bottom

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE_FILE="docker-compose.yml"
SERVICE="research-agent"
ENV_FILE=".env"
ENV_EXAMPLE=".env.example"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "  $*"; }
warn() { echo "  [warn] $*" >&2; }
die()  { echo "  [error] $*" >&2; exit 1; }

check_deps() {
    command -v docker        >/dev/null 2>&1 || die "docker not found. Install Docker Desktop (WSL2 backend)."
    docker compose version   >/dev/null 2>&1 || die "docker compose plugin not found. Update Docker Desktop."
}

check_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$ENV_EXAMPLE" ]]; then
            die ".env not found. Copy .env.example to .env and fill in your keys:\n  cp .env.example .env"
        else
            die ".env not found."
        fi
    fi

    # Validate required keys are present and non-empty
    local missing=()
    while IFS= read -r line; do
        [[ "$line" =~ ^#|^[[:space:]]*$ ]] && continue   # skip comments and blanks
        local key="${line%%=*}"
        local val
        val="$(grep -E "^${key}=" "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')" || true
        if [[ -z "$val" || "$val" == "sk-ant-..."* || "$val" == "ghp_..."* ]]; then
            missing+=("$key")
        fi
    done < "$ENV_EXAMPLE"

    if [[ ${#missing[@]} -gt 0 ]]; then
        die "Missing or placeholder values in .env: ${missing[*]}\nEdit .env and set real credentials."
    fi
}

# ---------------------------------------------------------------------------
# Future hook stubs — add logic here as the project grows
# ---------------------------------------------------------------------------

pre_run() {
    : # e.g. validate Drive token, ping GitHub API, check model quota
}

post_run() {
    : # e.g. send Slack notification, log session metadata, trigger downstream job
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_build() {
    log "Building image..."
    docker compose -f "$COMPOSE_FILE" build --no-cache "$SERVICE"
    log "Build complete."
}

cmd_start() {
    check_deps
    check_env
    pre_run

    # Build only if image doesn't exist yet (skip on subsequent runs)
    if ! docker image inspect research-agent:latest >/dev/null 2>&1; then
        log "Image not found — building..."
        docker compose -f "$COMPOSE_FILE" build "$SERVICE"
    fi

    log "Starting research agent..."
    echo ""
    # --rm: clean up container on exit (state persists in named volume)
    docker compose -f "$COMPOSE_FILE" run --rm "$SERVICE"

    post_run
}

cmd_stop() {
    log "Stopping container..."
    docker compose -f "$COMPOSE_FILE" down
    log "Done."
}

cmd_logs() {
    docker compose -f "$COMPOSE_FILE" logs --tail=100 -f "$SERVICE"
}

cmd_clean() {
    log "Removing container, image, and volume..."
    docker compose -f "$COMPOSE_FILE" down --volumes --rmi local
    log "Clean complete."
}

cmd_shell() {
    check_deps
    check_env
    log "Opening shell in container (debug mode)..."
    docker compose -f "$COMPOSE_FILE" run --rm --entrypoint /bin/bash "$SERVICE"
}

cmd_help() {
    grep -E "^\s+\./run\.sh" "$0" | sed 's/^#//'
    echo ""
    echo "  No argument defaults to: start"
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

COMMAND="${1:-start}"

case "$COMMAND" in
    start|"")  cmd_start  ;;
    build)     cmd_build  ;;
    stop)      cmd_stop   ;;
    logs)      cmd_logs   ;;
    clean)     cmd_clean  ;;
    shell)     cmd_shell  ;;
    help|--help|-h) cmd_help ;;
    *)         die "Unknown command: $COMMAND. Run ./run.sh help for usage." ;;
esac
