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
#   ./run.sh bw-setup     Guided setup: store secrets in Bitwarden and remove .env
#
# Secret management:
#   Preferred: Bitwarden CLI — secrets fetched at runtime, never on disk.
#   Fallback:  .env file     — used automatically if Bitwarden is unavailable.
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

# Bitwarden item name — change this if you store the secrets under a different name
BW_ITEM_NAME="research-agent"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "  $*"; }
warn() { echo "  [warn] $*" >&2; }
die()  { echo "  [error] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Bitwarden secret resolution
# ---------------------------------------------------------------------------

# Returns 0 (true) if the bw CLI is installed and the vault is unlocked
bw_available() {
    command -v bw >/dev/null 2>&1 || return 1
    # BW_SESSION must be set and non-empty for the vault to be accessible
    [[ -n "${BW_SESSION:-}" ]] || return 1
    bw status 2>/dev/null | grep -q '"status":"unlocked"' || return 1
}

# Fetch a named field from the Bitwarden item
# Usage: bw_get_field "field-name"
bw_get_field() {
    local field="$1"
    bw get item "$BW_ITEM_NAME" 2>/dev/null \
        | python3 -c "
import json, sys
item = json.load(sys.stdin)
# Check custom fields first
for f in item.get('fields', []):
    if f['name'] == '$field':
        print(f['value'])
        sys.exit(0)
# Fall back to login username/password for common field names
login = item.get('login', {})
if '$field' == 'ANTHROPIC_API_KEY' and login.get('password'):
    print(login['password'])
    sys.exit(0)
sys.exit(1)
" 2>/dev/null || true
}

# Resolve secrets: try Bitwarden first, fall back to .env
# Exports ANTHROPIC_API_KEY and GITHUB_TOKEN into the current shell
resolve_secrets() {
    if bw_available; then
        log "Fetching secrets from Bitwarden..."

        local anthropic_key github_token
        anthropic_key="$(bw_get_field "ANTHROPIC_API_KEY")"
        github_token="$(bw_get_field "GITHUB_TOKEN")"

        if [[ -z "$anthropic_key" || -z "$github_token" ]]; then
            warn "Bitwarden item '$BW_ITEM_NAME' found but one or more fields are missing."
            warn "Falling back to .env file."
            resolve_from_env_file
        else
            export ANTHROPIC_API_KEY="$anthropic_key"
            export GITHUB_TOKEN="$github_token"
            log "Secrets loaded from Bitwarden."
        fi
    else
        if command -v bw >/dev/null 2>&1; then
            warn "Bitwarden CLI found but vault is locked or BW_SESSION is not set."
            warn "To use Bitwarden: run 'export BW_SESSION=\$(bw unlock --raw)' first."
            warn "Falling back to .env file."
        fi
        resolve_from_env_file
    fi
}

resolve_from_env_file() {
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$ENV_EXAMPLE" ]]; then
            die ".env not found. Either:\n  1) Run './run.sh bw-setup' to store secrets in Bitwarden\n  2) Copy .env.example to .env and fill in your keys"
        else
            die ".env not found and no Bitwarden session active."
        fi
    fi

    # Validate required keys are present and non-empty
    local missing=()
    while IFS= read -r line; do
        [[ "$line" =~ ^#|^[[:space:]]*$ ]] && continue
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

    # Source the .env so variables are available for docker compose --env-file
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    log "Secrets loaded from .env."
}

# ---------------------------------------------------------------------------
# Deps check
# ---------------------------------------------------------------------------

check_deps() {
    command -v docker        >/dev/null 2>&1 || die "docker not found. Install Docker Desktop (WSL2 backend)."
    docker compose version   >/dev/null 2>&1 || die "docker compose plugin not found. Update Docker Desktop."
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
    resolve_secrets
    pre_run

    # Always build before starting — layer cache makes this fast when nothing
    # has changed. Guarantees the container never runs stale code after an edit.
    log "Building image..."
    docker compose -f "$COMPOSE_FILE" build "$SERVICE"
    log "Build complete."

    log "Starting research agent..."
    echo ""
    # Pass secrets as explicit -e flags — never written to disk inside the container
    # --rm: clean up container on exit (state persists in named volume)
    docker compose -f "$COMPOSE_FILE" run --rm \
        -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
        -e GITHUB_TOKEN="${GITHUB_TOKEN}" \
        "$SERVICE"

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
    resolve_secrets
    log "Opening shell in container (debug mode)..."
    docker compose -f "$COMPOSE_FILE" run --rm \
        -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
        -e GITHUB_TOKEN="${GITHUB_TOKEN}" \
        --entrypoint /bin/bash "$SERVICE"
}

cmd_help() {
    grep -E "^\s+\./run\.sh" "$0" | sed 's/^#//'
    echo ""
    echo "  No argument defaults to: start"
}

# Guided Bitwarden setup — stores secrets in a vault item and optionally removes .env
cmd_bw_setup() {
    command -v bw >/dev/null 2>&1 || die "Bitwarden CLI (bw) is not installed.\nInstall it from: https://bitwarden.com/help/cli/"

    echo ""
    echo "  Bitwarden setup for research-agent"
    echo "  -----------------------------------"
    echo "  This will create a Bitwarden item named '$BW_ITEM_NAME'"
    echo "  with your ANTHROPIC_API_KEY and GITHUB_TOKEN as custom fields."
    echo ""

    # Ensure vault is unlocked
    if [[ -z "${BW_SESSION:-}" ]] || ! bw status 2>/dev/null | grep -q '"status":"unlocked"'; then
        echo "  Your vault needs to be unlocked."
        echo "  Run the following, then re-run './run.sh bw-setup':"
        echo ""
        echo "    export BW_SESSION=\$(bw unlock --raw)"
        echo ""
        exit 1
    fi

    # Prompt for keys (input hidden)
    local anthropic_key github_token
    read -rsp "  Paste your ANTHROPIC_API_KEY: " anthropic_key; echo ""
    read -rsp "  Paste your GITHUB_TOKEN:      " github_token;  echo ""

    if [[ -z "$anthropic_key" || -z "$github_token" ]]; then
        die "Both keys are required. Setup aborted."
    fi

    # Build item JSON and create in Bitwarden
    local item_json
    item_json=$(python3 -c "
import json, sys
item = {
    'type': 1,
    'name': '${BW_ITEM_NAME}',
    'notes': 'Secrets for the research-agent Docker container.',
    'fields': [
        {'name': 'ANTHROPIC_API_KEY', 'value': sys.argv[1], 'type': 1},
        {'name': 'GITHUB_TOKEN',      'value': sys.argv[2], 'type': 1},
    ]
}
print(json.dumps(item))
" "$anthropic_key" "$github_token")

    # Check if item already exists — update vs create
    local existing_id
    existing_id="$(bw get item "$BW_ITEM_NAME" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null || true)"

    if [[ -n "$existing_id" ]]; then
        echo "$item_json" | bw encode | bw edit item "$existing_id" >/dev/null
        log "Bitwarden item '$BW_ITEM_NAME' updated."
    else
        echo "$item_json" | bw encode | bw create item >/dev/null
        log "Bitwarden item '$BW_ITEM_NAME' created."
    fi

    bw sync >/dev/null 2>&1 || true

    echo ""
    echo "  Secrets stored in Bitwarden."
    echo ""

    # Offer to remove .env
    if [[ -f "$ENV_FILE" ]]; then
        read -rp "  Remove the .env file from disk now? [y/N] " confirm
        if [[ "${confirm,,}" == "y" ]]; then
            rm "$ENV_FILE"
            log ".env removed."
        else
            log ".env kept. Consider deleting it manually once you've verified Bitwarden works."
        fi
    fi

    echo ""
    echo "  Setup complete. From now on, unlock your vault before running the agent:"
    echo ""
    echo "    export BW_SESSION=\$(bw unlock --raw)"
    echo "    ./run.sh"
    echo ""
}

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

COMMAND="${1:-start}"

case "$COMMAND" in
    start|"")  cmd_start    ;;
    build)     cmd_build    ;;
    stop)      cmd_stop     ;;
    logs)      cmd_logs     ;;
    clean)     cmd_clean    ;;
    shell)     cmd_shell    ;;
    bw-setup)  cmd_bw_setup ;;
    help|--help|-h) cmd_help ;;
    *)         die "Unknown command: $COMMAND. Run ./run.sh help for usage." ;;
esac
