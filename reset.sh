#!/usr/bin/env bash
#
# Karaoke Sub Tool — Reset Script
# Löscht alle erzeugten Inhalte und setzt die Datenbank auf 0.
#
# Usage:
#   ./reset.sh               Interaktiv (Bestätigung erforderlich)
#   ./reset.sh --force       Ohne Rückfrage alles löschen
#   ./reset.sh --dry-run     Nur anzeigen, was gelöscht würde
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"

# ── Farben ────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Flags ─────────────────────────────────────────────────────────────────────

FORCE=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --force|-f)  FORCE=true ;;
        --dry-run|-n) DRY_RUN=true ;;
        --help|-h)
            echo "Usage: ./reset.sh [--force] [--dry-run]"
            echo ""
            echo "Löscht alle erzeugten Inhalte und setzt die Datenbank auf 0."
            echo ""
            echo "  --force, -f     Ohne Rückfrage löschen"
            echo "  --dry-run, -n   Nur anzeigen, was gelöscht würde"
            echo "  --help, -h      Diese Hilfe anzeigen"
            exit 0
            ;;
    esac
done

# ── Zu löschende Verzeichnisse und Dateien ────────────────────────────────────

# Verzeichnisse deren INHALT gelöscht wird (Verzeichnis selbst bleibt)
CLEAR_DIRS=(
    "$DATA_DIR/output"              # Job-Artefakte (SRT, ASS, segments.json, Waveforms, ...)
    "$DATA_DIR/uploads"             # Hochgeladene Audio-/Textdateien
    "$DATA_DIR/editor/assets"       # Editor-Assets
    "$DATA_DIR/editor/projects"     # Editor-Projekte
    "$DATA_DIR/editor/renders"      # Editor-Renders
    "$DATA_DIR/editor/overlays"     # Editor-Overlays
    "$DATA_DIR/logs"                # Anwendungslogs
    "$SCRIPT_DIR/separated"         # Demucs-Stems (Vocal Isolation)
)

# SQLite-Datenbanken
DB_FILES=(
    "$DATA_DIR/library.sqlite"      # Library-DB (Transkriptionen, Media, File-Registry)
)
# Chat-History DBs liegen in data/output/{job_id}/.chat_history.sqlite → werden mit output/ gelöscht

# Pipeline-Cache
CACHE_DIRS=(
    "$SCRIPT_DIR/.karaoke_cache"    # Pipeline-Cache
)

# ── Zusammenfassung berechnen ─────────────────────────────────────────────────

count_items() {
    local total=0
    for dir in "${CLEAR_DIRS[@]}"; do
        if [[ -d "$dir" ]]; then
            local n
            n=$(find "$dir" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
            total=$((total + n))
        fi
    done
    for f in "${DB_FILES[@]}"; do
        [[ -f "$f" ]] && total=$((total + 1))
    done
    for d in "${CACHE_DIRS[@]}"; do
        [[ -d "$d" ]] && total=$((total + 1))
    done
    echo "$total"
}

show_summary() {
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Karaoke Sub Tool — Reset${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""

    for dir in "${CLEAR_DIRS[@]}"; do
        local name="${dir#$SCRIPT_DIR/}"
        if [[ -d "$dir" ]]; then
            local n
            n=$(find "$dir" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
            if [[ $n -gt 0 ]]; then
                echo -e "  ${YELLOW}▸${NC} $name/ — $n Einträge"
            else
                echo -e "  ${GREEN}✓${NC} $name/ — leer"
            fi
        else
            echo -e "  ${GREEN}✓${NC} $name/ — existiert nicht"
        fi
    done

    echo ""
    for f in "${DB_FILES[@]}"; do
        local name="${f#$SCRIPT_DIR/}"
        if [[ -f "$f" ]]; then
            local size
            size=$(du -h "$f" 2>/dev/null | cut -f1)
            echo -e "  ${YELLOW}▸${NC} $name — $size"
        else
            echo -e "  ${GREEN}✓${NC} $name — existiert nicht"
        fi
    done

    echo ""
    for d in "${CACHE_DIRS[@]}"; do
        local name="${d#$SCRIPT_DIR/}"
        if [[ -d "$d" ]]; then
            local size
            size=$(du -sh "$d" 2>/dev/null | cut -f1)
            echo -e "  ${YELLOW}▸${NC} $name/ — $size"
        else
            echo -e "  ${GREEN}✓${NC} $name/ — existiert nicht"
        fi
    done

    echo ""
}

# ── Löschlogik ────────────────────────────────────────────────────────────────

do_reset() {
    local action_label="Lösche"
    [[ "$DRY_RUN" == true ]] && action_label="Würde löschen"

    # Verzeichnis-Inhalte löschen
    for dir in "${CLEAR_DIRS[@]}"; do
        local name="${dir#$SCRIPT_DIR/}"
        if [[ -d "$dir" ]]; then
            local n
            n=$(find "$dir" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
            if [[ $n -gt 0 ]]; then
                echo -e "  ${RED}✗${NC} $action_label: $name/* ($n Einträge)"
                if [[ "$DRY_RUN" == false ]]; then
                    rm -rf "${dir:?}"/*
                    rm -rf "$dir"/.[!.]* 2>/dev/null || true  # Versteckte Dateien
                fi
            fi
        fi
    done

    # Datenbanken löschen
    for f in "${DB_FILES[@]}"; do
        local name="${f#$SCRIPT_DIR/}"
        if [[ -f "$f" ]]; then
            echo -e "  ${RED}✗${NC} $action_label: $name"
            [[ "$DRY_RUN" == false ]] && rm -f "$f"
        fi
    done

    # Cache-Verzeichnisse komplett löschen
    for d in "${CACHE_DIRS[@]}"; do
        local name="${d#$SCRIPT_DIR/}"
        if [[ -d "$d" ]]; then
            echo -e "  ${RED}✗${NC} $action_label: $name/"
            [[ "$DRY_RUN" == false ]] && rm -rf "$d"
        fi
    done

    # Leere Verzeichnisse sicherstellen
    if [[ "$DRY_RUN" == false ]]; then
        for dir in "${CLEAR_DIRS[@]}"; do
            mkdir -p "$dir"
        done
    fi

    echo ""
    if [[ "$DRY_RUN" == true ]]; then
        echo -e "${CYAN}Dry-Run — nichts wurde gelöscht.${NC}"
    else
        echo -e "${GREEN}✓ Reset abgeschlossen. Alle Daten gelöscht.${NC}"
        echo -e "  Server neu starten: ${CYAN}./server.sh restart${NC}"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

TOTAL=$(count_items)

if [[ "$TOTAL" -eq 0 ]]; then
    echo -e "${GREEN}Nichts zu löschen — alles bereits sauber.${NC}"
    exit 0
fi

show_summary

if [[ "$DRY_RUN" == true ]]; then
    do_reset
    exit 0
fi

if [[ "$FORCE" == true ]]; then
    echo -e "${RED}Force-Modus — lösche alles ohne Rückfrage...${NC}"
    echo ""
    do_reset
    exit 0
fi

# Interaktive Bestätigung
echo -e "${RED}WARNUNG: Alle erzeugten Inhalte und die Datenbank werden unwiderruflich gelöscht!${NC}"
echo ""
read -rp "Fortfahren? [j/N] " answer
echo ""

case "$answer" in
    [jJyY])
        do_reset
        ;;
    *)
        echo -e "${YELLOW}Abgebrochen.${NC}"
        exit 1
        ;;
esac
