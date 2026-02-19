#!/usr/bin/env bash
#
# Karaoke Sub Tool — Server Manager
# Usage:
#   ./server.sh start        Server im Hintergrund starten
#   ./server.sh stop         Server sauber stoppen
#   ./server.sh restart      Stop + Start
#   ./server.sh status       Läuft der Server?
#   ./server.sh log          Live-Log anzeigen (Ctrl+C zum Beenden)
#
# Optionen:
#   --host 0.0.0.0           Bind-Adresse (Default: 127.0.0.1)
#   --port 8000              Port (Default: 8000)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.server.pid"
LOG_FILE="$SCRIPT_DIR/.server.log"
VENV_DIR="$SCRIPT_DIR/.venv"

# Defaults
HOST="127.0.0.1"
PORT="8000"

# ── Farben ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}ℹ${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*"; }

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

get_pid() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
        # PID-File existiert aber Prozess nicht mehr → aufräumen
        rm -f "$PID_FILE"
    fi
    return 1
}

activate_venv() {
    if [[ -f "$VENV_DIR/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source "$VENV_DIR/bin/activate"
    elif [[ -f "$SCRIPT_DIR/venv/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source "$SCRIPT_DIR/venv/bin/activate"
    fi
}

kill_tree() {
    # Stoppt den Prozess und alle Kindprozesse (uvicorn spawnt Workers)
    local pid=$1
    local children
    children=$(pgrep -P "$pid" 2>/dev/null || true)

    for child in $children; do
        kill_tree "$child"
    done

    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null || true
    fi
}

wait_for_exit() {
    local pid=$1
    local timeout=${2:-10}
    local elapsed=0

    while kill -0 "$pid" 2>/dev/null && (( elapsed < timeout )); do
        sleep 0.5
        elapsed=$((elapsed + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        return 1  # noch am laufen
    fi
    return 0
}

# ── Kommandos ─────────────────────────────────────────────────────────────────

do_start() {
    if pid=$(get_pid); then
        warn "Server läuft bereits (PID $pid)"
        info "URL: ${BOLD}http://$HOST:$PORT${NC}"
        return 0
    fi

    info "Starte Karaoke Sub Tool..."
    info "Host: $HOST  Port: $PORT"

    cd "$SCRIPT_DIR"
    activate_venv

    # Prüfe ob Python und main.py vorhanden
    if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
        err "Python nicht gefunden!"
        exit 1
    fi
    local PYTHON
    PYTHON=$(command -v python3 2>/dev/null || command -v python)

    if [[ ! -f "$SCRIPT_DIR/main.py" ]]; then
        err "main.py nicht gefunden in $SCRIPT_DIR"
        exit 1
    fi

    # Prüfe ob Port frei ist
    if ss -tlnp 2>/dev/null | grep -q ":$PORT " || \
       lsof -i ":$PORT" &>/dev/null 2>&1; then
        err "Port $PORT ist bereits belegt!"
        info "Versuche: ./server.sh stop  oder anderen Port: ./server.sh start --port 8001"
        exit 1
    fi

    # Server im Hintergrund starten
    nohup "$PYTHON" -u main.py --host "$HOST" --port "$PORT" \
        >> "$LOG_FILE" 2>&1 &
    local new_pid=$!

    echo "$new_pid" > "$PID_FILE"

    # Kurz warten und prüfen ob der Prozess noch lebt
    sleep 1.5
    if ! kill -0 "$new_pid" 2>/dev/null; then
        err "Server konnte nicht gestartet werden!"
        err "Log prüfen: ./server.sh log"
        rm -f "$PID_FILE"
        exit 1
    fi

    ok "Server gestartet (PID $new_pid)"
    info "URL: ${BOLD}http://$HOST:$PORT${NC}"
    info "Log: ${BOLD}./server.sh log${NC}"
    info "Stop: ${BOLD}./server.sh stop${NC}"
}

do_stop() {
    local pid
    if ! pid=$(get_pid); then
        warn "Server läuft nicht"
        return 0
    fi

    info "Stoppe Server (PID $pid)..."

    # Graceful: SIGTERM an Prozessbaum
    kill_tree "$pid"

    if wait_for_exit "$pid" 10; then
        rm -f "$PID_FILE"
        ok "Server gestoppt"
        return 0
    fi

    # Falls SIGTERM nicht reicht: SIGKILL
    warn "Server reagiert nicht auf SIGTERM — sende SIGKILL..."
    kill -9 "$pid" 2>/dev/null || true

    # Auch alle übrig gebliebenen uvicorn-Prozesse killen
    pkill -9 -f "uvicorn.*main:app.*$PORT" 2>/dev/null || true

    sleep 0.5
    rm -f "$PID_FILE"

    if ! kill -0 "$pid" 2>/dev/null; then
        ok "Server gestoppt (SIGKILL)"
    else
        err "Konnte Server nicht stoppen! Manuell prüfen: kill -9 $pid"
        exit 1
    fi
}

do_restart() {
    do_stop
    sleep 1
    do_start
}

do_status() {
    local pid
    if pid=$(get_pid); then
        ok "Server läuft (PID $pid)"
        info "URL: ${BOLD}http://$HOST:$PORT${NC}"

        # Speicher und CPU anzeigen
        if command -v ps &>/dev/null; then
            local mem cpu
            mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.1f", $1/1024}')
            cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | tr -d ' ')
            info "RAM: ${mem}MB  CPU: ${cpu}%"
        fi

        # Uptime
        if [[ -f "$PID_FILE" ]]; then
            local started
            started=$(stat -c %Y "$PID_FILE" 2>/dev/null || stat -f %m "$PID_FILE" 2>/dev/null)
            if [[ -n "$started" ]]; then
                local now elapsed_s mins hours
                now=$(date +%s)
                elapsed_s=$((now - started))
                mins=$((elapsed_s / 60))
                hours=$((mins / 60))
                mins=$((mins % 60))
                info "Uptime: ${hours}h ${mins}m"
            fi
        fi

        # Log-Größe
        if [[ -f "$LOG_FILE" ]]; then
            local log_size
            log_size=$(du -h "$LOG_FILE" | cut -f1)
            info "Log: $log_size ($LOG_FILE)"
        fi
    else
        warn "Server läuft nicht"
        return 1
    fi
}

do_log() {
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "Noch kein Log vorhanden"
        return 1
    fi
    info "Log: $LOG_FILE (Ctrl+C zum Beenden)"
    echo "────────────────────────────────────────"
    tail -f "$LOG_FILE"
}

do_help() {
    echo -e "${BOLD}Karaoke Sub Tool — Server Manager${NC}"
    echo ""
    echo -e "  ${GREEN}./server.sh start${NC}    Server im Hintergrund starten"
    echo -e "  ${GREEN}./server.sh stop${NC}     Server sauber stoppen"
    echo -e "  ${GREEN}./server.sh restart${NC}  Stop + Start"
    echo -e "  ${GREEN}./server.sh status${NC}   Status anzeigen"
    echo -e "  ${GREEN}./server.sh log${NC}      Live-Log (tail -f)"
    echo ""
    echo "  Optionen:"
    echo "    --host 0.0.0.0     Bind-Adresse (Default: 127.0.0.1)"
    echo "    --port 8000        Port (Default: 8000)"
    echo ""
    echo "  Beispiele:"
    echo "    ./server.sh start --port 9000"
    echo "    ./server.sh start --host 0.0.0.0"
    echo "    ./server.sh restart --port 8080"
}

# ── Argument Parsing ──────────────────────────────────────────────────────────

CMD="${1:-help}"
shift || true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        *) warn "Unbekannte Option: $1"; shift ;;
    esac
done

case "$CMD" in
    start)   do_start   ;;
    stop)    do_stop    ;;
    restart) do_restart ;;
    status)  do_status  ;;
    log)     do_log     ;;
    help|-h|--help) do_help ;;
    *) err "Unbekanntes Kommando: $CMD"; do_help; exit 1 ;;
esac
