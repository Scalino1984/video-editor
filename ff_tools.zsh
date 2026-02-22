#!/bin/env zsh

ff__strict() {
  emulate -L zsh
  setopt pipefail err_return
  TRAPINT() { return 130 }
}

ff__need() {
  command -v "$1" >/dev/null 2>&1 || { print -u2 "Fehlt: $1"; return 1; }
}

ff__has_audio() {
  local f="${1:-}"
  [[ -n "$f" && -f "$f" ]] || return 1
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "$f" 2>/dev/null | grep -qi '^audio$'
}

ff__duration() {
  local f="${1:-}"
  ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | awk '{printf "%.6f\n",$1}'
}

ff__sec_to_hhmmss() {
  local d="${1:-0}"
  local whole h m
  whole="${d%.*}"

  h=$(( whole / 3600 ))
  m=$(( (whole % 3600) / 60 ))

  awk -v d="$d" -v h="$h" -v m="$m" 'BEGIN{
    printf "%02d:%02d:%06.3f\n", h, m, d-(h*3600+m*60)
  }'
}

ff__dims() {
  local f="${1:-}"
  local w h
  w="$(ffprobe -v error -select_streams v:0 -show_entries stream=width  -of csv=p=0 "$f" 2>/dev/null)"
  h="$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$f" 2>/dev/null)"
  [[ -n "$w" && -n "$h" ]] || return 1
  print -r -- "${w}x${h}"
}

ff__fps() {
  local f="${1:-}"
  ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of csv=p=0 "$f" 2>/dev/null | awk -F/ '{ if ($2==0) {print 0} else { printf "%.6f\n",$1/$2 } }'
}

typeset -gA FF_DESC
typeset -gA FF_EX

FF_DESC[ff__strict]="System funktion (nicht beachten!)"
FF_EX[ff__strict]="Keine funktion"

FF_DESC[ff__duration]="Zeigt die exakte länge der Audio/Video Datei (bsp: 174.264000)"
FF_EX[ff__duration]="ff__duration input.(mp3/mp4/etc.)"

FF_DESC[ff_vignette]="Vignette (Randabdunklung) auf Video anwenden (Audio bleibt, wenn vorhanden)"
FF_EX[ff_vignette]="ff_vignette --in input.mp4 --out out.mp4 --angle PI/4 --crf 18 --preset medium"

FF_DESC[ff_strip_audio]="Entfernt Audio aus einem Video (remux/copy, kein Re-Encode)"
FF_EX[ff_strip_audio]="ff_strip_audio --in input.mp4 --out input-noaudio.mp4"

FF_DESC[ff_rev]="Video rückwärts (ohne Audio)"
FF_EX[ff_rev]="ff_rev input.mp4"

FF_DESC[ff_audio_loop_video]="Video loopen bis Audio endet"
FF_EX[ff_audio_loop_video]="ff_audio_loop_video video.mp4 song.wav out.mp4"

FF_DESC[ff_audio_vid_to_vid]="Audio und Loopvideo zu Video"
FF_EX[ff_audio_vid_to_vid]="ff_audio_vid_to_vid --video loop.mp4 --audio song.wav --out out.mp4"

FF_DESC[ff_fades]="Fade In/Out (oder nur in/out) am Anfang/Ende (Audio bleibt, wenn vorhanden)"
FF_EX[ff_fades]="ff_fades input.mp4 1.0 both"

FF_DESC[ff_fades_old]="(Alt) Fade In/Out am Anfang/Ende"
FF_EX[ff_fades_old]="ff_fades_old input.mp4 1.0"

FF_DESC[ff_speed]="Geschwindigkeit via setpts (mit minterpolate 60fps), ohne Audio"
FF_EX[ff_speed]="ff_speed input.mp4 1.5"

FF_DESC[ff_mkvid_create]="erzeugt Video aus Audio + Loop-Video + optional SRT/ASS"
FF_EX[ff_mkvid_create]="ff_mkvid_create --audio A --video V [--srt S] [--ass X] [--out O] [--crf N] [--preset P] [--fps N] [--scale W]"

FF_DESC[ff_vid]="erzeugt Video aus Audio + Loop-Video + optional SRT/ASS"
FF_EX[ff_vid]="ff_vid --audio input.mp3 --video loop.mp4 --ass input.ass --fontsize 26 --marginv 80 --scale 1080 --out output.mp4"

FF_DESC[ff_concat_list]="Concat per list.txt (file '...'), rendert zu einem MP4 (Video+Audio tolerant)"
FF_EX[ff_concat_list]="ff_concat_list list.txt out.mp4 18 medium"

FF_DESC[ff_twix]="Optical-Flow Slowmo nur in einem Zeitfenster (Twixtor-ähnlich)"
FF_EX[ff_twix]="ff_twix --file in.mp4 --output out.mp4 --start 3.2 --duration 1.5 --factor 3 --fps 60"

FF_DESC[ff_still]="Standbild-Video aus Bild (optional mit Stille-Audio)"
FF_EX[ff_still]="ff_still --in cover.png --out cover.mp4 --sec 8 --audio"

FF_DESC[ff_title_fade]="Titel per drawtext mit Fade-In/Out, Outline, Box-Farbe (Audio tolerant)"
FF_EX[ff_title_fade]="ff_title_fade --in in.mp4 --out out.mp4 --text \"Mein Titel\" --start 0.5 --dur 3 --fade 0.5"

FF_DESC[ff_color_blend]="Farb-Overlay zeitgesteuert mit Fade In/Out (Audio tolerant)"
FF_EX[ff_color_blend]="ff_color_blend input.mp4 12.5 3.0 \"#6a00ff\" 0.4 0.35"

FF_DESC[ff_mov_overlay]="Overlay-MOV/MP4 zeitgesteuert mitten ins Video, skaliert auf Base (Audio tolerant)"
FF_EX[ff_mov_overlay]="ff_mov_overlay input.mp4 fx.mov 12.5 1.2 alpha 0.30 out.mp4"

FF_DESC[ff_burn_subs]="Audio/Video + SRT/ASS -> fertiges MP4, Untertitel eingebrannt (Audio-only: optional BG-Farbe/Bild/Cover per --use-cover, Fontdir optional)"
FF_EX[ff_burn_subs]="ff_burn_subs --in input.mp4 --subs input.srt --out out_subbed.mp4 --crf 18 --preset medium ff_burn_subs --in input.mp3 --subs input.ass --out out_audio_subbed.mp4 --use-cover --cover-mode crop --w 1920 --h 1080 --fps 30"
FF_EX[ff_burn_subs]="ff_burn_subs --in input.mp4 --subs input.srt --out out_subbed.mp4 --crf 18 --preset medium ff_burn_subs --in input.mp3 --subs input.ass --out out_audio_subbed.mp4 --use-cover --cover-mode crop --w 1920 --h 1080 --fps 30"

FF_DESC[ff_auto_cut_overlay]="Interner Cut bei START: blendet Ende-vor-START -> Anfang-nach-START mit MOV-Matte, skaliert (Audio tolerant)"
FF_EX[ff_auto_cut_overlay]="ff_auto_cut_overlay input.mp4 Ink_Matte.mov 10.0 0.8 luma out.mp4"

FF_DESC[ff_mov_transition]="Übergang zwischen zwei Videos mit MOV-Matte (Audio tolerant)"
FF_EX[ff_mov_transition]="ff_mov_transition a.mp4 b.mp4 Riot_Transition.mov 12.5 1.2 alpha out.mp4"

FF_DESC[ff_reframe]="Reframe auf Zielauflösung per crop/fit/blur (mit X/Y-Shift in Pixeln, Audio tolerant)"
FF_EX[ff_reframe]="ff_reframe --in input.mp4 --mode blur --w 1080 --h 1920 --x 200 --y 0 --blur 25 --out out_1080x1920_blur.mp4"

FF_DESC[ff_info]="Kurzinfo: Dauer, Codec, Profil, Auflösung, FPS, PixFmt (via ffprobe)"
FF_EX[ff_info]="ff_info input.mp4"

FF_DESC[ff_softlight_overlay]="Blendet ein FX-Video im Softlight-Modus über ein Input-Video (Default: alpha=0.12, duration=31.5s)"
#FF_EX[ff_softlight_overlay]="ff_softlight_overlay video.mp4 colorfx.mp4 out.mp4"
FF_EX[ff_softlight_overlay]="ff_softlight_overlay input.mp4 fx.mp4 output.mp4 0.12 31.5"

FF_DESC[ff_gif]="Video -> GIF (Palettegen/Paletteuse), optional Start/Dauer/FPS/Breite"
FF_EX[ff_gif]="ff_gif --in input.mp4 --out out.gif --start 2.0 --dur 3.0 --fps 15 --w 480"

FF_DESC[ff_m3u8_make]="Erstellt eine portable Extended-M3U8 Playlist aus Medien-Dateien (mit EXTINF-Dauer via ffprobe)"
FF_EX[ff_m3u8_make]="ff_m3u8_make --dir . --out playlist.m3u8 --recursive  |  ff_m3u8_make --dir /pfad --out album.m3u8 --absolute"

FF_DESC[ff_webm_loop]="Loop-Clip Export als WebM VP9 (für Website/Overlay), optional Start/Dauer/FPS/Breite/CRF"
FF_EX[ff_webm_loop]="ff_webm_loop --in input.mp4 --out loop.webm --start 0 --dur 4 --fps 30 --w 1280 --crf 32"

FF_DESC[ff_audio_norm]="Audio normalisieren nach EBU R128 (loudnorm), Video copy, Audio AAC"
FF_EX[ff_audio_norm]="ff_audio_norm --in input.mp4 --out out_norm.mp4 --i -16 --tp -1.5 --lra 11"

FF_DESC[ff_menu]="Interaktives Menü: Tool auswählen und optional --video/--audio/--list/--out vorgeben; Parameter via -- weiterreichen"
FF_EX[ff_menu]="ff_menu --video input.mp4 --audio song.wav --out out.mp4"

ff_help() {
  ff__strict

  typeset -gA FF_DESC 2>/dev/null || true
  typeset -gA FF_EX   2>/dev/null || true

  local target="${1:-}"
  local no_color=0
  local show_all=0

  if [[ "$target" == "--no-color" ]]; then
    no_color=1
    shift
    target="${1:-}"
  fi
  if [[ "$target" == "--all" ]]; then
    show_all=1
    shift
    target="${1:-}"
  fi

  local use_color=1
  [[ -n "${NO_COLOR:-}" || "$no_color" -eq 1 ]] && use_color=0
  [[ ! -t 1 ]] && use_color=0

  local C_RESET="" C_HDR="" C_TOOL="" C_DIM="" C_WARN="" C_ROW1="" C_ROW2=""
  if (( use_color )); then
    C_RESET=$'\e[0m'
    C_HDR=$'\e[36;1m'
    C_TOOL=$'\e[32m'
    C_DIM=$'\e[90m'
    C_WARN=$'\e[33m'
    C_ROW1=$'\e[37m'
    C_ROW2=$'\e[33m'
  fi

  local cols="${COLUMNS:-120}"
  (( cols < 90 )) && cols=90

  local w_tool=20
  local w_desc=38
  local w_ex=$(( cols - w_tool - w_desc - 6 ))
  (( w_ex < 40 )) && w_ex=40

  local -a _wrap_lines
  _ff__wrap() {
    local text="${1:-}"
    local width="${2:-40}"
    _wrap_lines=( "${(@f)$(print -r -- "$text" | fold -s -w "$width")}" )
    (( ${#_wrap_lines[@]} == 0 )) && _wrap_lines=( "" )
  }

  if [[ -n "$target" ]]; then
    if (( ! $+functions[$target] )); then
      print -r -- "${C_WARN}Unbekanntes Tool:${C_RESET} $target"
      print -r -- "Tipp: ${C_TOOL}ff_help${C_RESET}"
      return 1
    fi

    if "$target" --help >/dev/null 2>&1; then
      "$target" --help
      return 0
    fi

    print -r -- "${C_TOOL}${target}${C_RESET}"
    print -r -- "  Beschreibung: ${FF_DESC[$target]-Keine Beschreibung hinterlegt.}"
    print -r -- "  Beispiel    : ${FF_EX[$target]-Kein Beispiel hinterlegt.}"
    return 0
  fi

  local -a names
  names=( ${(k)functions[(I)ff_*]} )

  if (( ! show_all )); then
    names=( ${names:#ff_help} ${names:#ff_menu} ${names:#ff__strict} ${names:#ff__*} )
  fi

  names=( ${(uon)names} )
  (( ${#names[@]} )) || { print -u2 "Keine ff_* Tools gefunden."; return 1; }

  print -r -- ""
  print -r -- "${C_HDR}FFmpeg Tools Übersicht${C_RESET}"
  print -r -- "${C_DIM}Aufruf:${C_RESET} ${C_TOOL}ff_help <tool>${C_RESET}  ${C_DIM}(Detailhilfe)${C_RESET}"
  print -r -- "${C_DIM}Optionen:${C_RESET} ${C_TOOL}--no-color${C_RESET}  ${C_TOOL}--all${C_RESET}"
  print -r -- ""

  local sep_tool="${(l:${w_tool}::-:)}"
  local sep_desc="${(l:${w_desc}::-:)}"
  local sep_ex="${(l:${w_ex}::-:)}"

  print -r -- "${C_HDR}$(printf "%-${w_tool}s | %-${w_desc}s | %s" "Tool" "Beschreibung" "Beispiel")${C_RESET}"
  print -r -- "${sep_tool}-+-${sep_desc}-+-${sep_ex}"

  local n desc ex
  local -a dlines elines
  local i max
  local row=0

  for n in "${names[@]}"; do
    (( row++ ))
    local ROWC=""
    if (( use_color )); then
      if (( row % 2 == 0 )); then
        ROWC="$C_ROW2"
      else
        ROWC="$C_ROW1"
      fi
    fi

    desc="${FF_DESC[$n]-(keine Beschreibung hinterlegt)}"
    ex="${FF_EX[$n]-ff_help $n}"

    _ff__wrap "$desc" "$w_desc"
    dlines=( "${_wrap_lines[@]}" )
    _ff__wrap "$ex" "$w_ex"
    elines=( "${_wrap_lines[@]}" )

    max=$(( ${#dlines[@]} > ${#elines[@]} ? ${#dlines[@]} : ${#elines[@]} ))
    (( max < 1 )) && max=1

    i=1
    while (( i <= max )); do
      if (( i == 1 )); then
        if (( use_color )); then
          printf "%s%s%-${w_tool}s%s | %s%-${w_desc}s%s | %s%s%s\n" \
            "$ROWC" "$C_TOOL" "$n" "$C_RESET" \
            "$ROWC" "${dlines[$i]:-}" "$C_RESET" \
            "$ROWC" "${elines[$i]:-}" "$C_RESET"
        else
          printf "%-${w_tool}s | %-${w_desc}s | %s\n" \
            "$n" "${dlines[$i]:-}" "${elines[$i]:-}"
        fi
      else
        if (( use_color )); then
          printf "%s%-${w_tool}s%s | %s%-${w_desc}s%s | %s%s%s\n" \
            "$ROWC" "" "$C_RESET" \
            "$ROWC" "${dlines[$i]:-}" "$C_RESET" \
            "$ROWC" "${elines[$i]:-}" "$C_RESET"
        else
          printf "%-${w_tool}s | %-${w_desc}s | %s\n" \
            "" "${dlines[$i]:-}" "${elines[$i]:-}"
        fi
      fi
      (( i++ ))
    done
  done

  print -r -- ""
  print -r -- "${C_DIM}Tipp:${C_RESET} ${C_TOOL}ff_help <tool>${C_RESET} zeigt Details/Parameter."
  print -r -- ""
}

# -------------------------------------------------------------------
# M3U8 Playlist Builder (Extended M3U) – kompatibel mit VLC/mpv/Kodi/etc.
# -------------------------------------------------------------------
ff_m3u8_make() {
  ff__strict
  ff__need ffprobe || return 1
  ff__need find || return 1
  ff__need sort || return 1
  ff__need awk || return 1

  local DIR="."
  local OUT="playlist.m3u8"
  local RECURSIVE=0
  local ABSOLUTE=0

  # Default: Audio + Video gängige Endungen
  local EXT_REGEX='.*\.(mp3|flac|wav|m4a|aac|ogg|opus|mp4|mkv|webm|avi|mov)$'

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dir)        DIR="${2:-.}"; shift 2 ;;
      --out)        OUT="${2:-playlist.m3u8}"; shift 2 ;;
      --recursive)  RECURSIVE=1; shift ;;
      --absolute)   ABSOLUTE=1; shift ;;
      --ext-regex)  EXT_REGEX="${2:-$EXT_REGEX}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_m3u8_make
USAGE:
  ff_m3u8_make [--dir <pfad>] [--out <playlist.m3u8>] [--recursive] [--absolute] [--ext-regex <regex>]

BESCHREIBUNG:
  Erstellt eine "Extended M3U" Playlist mit .m3u8-Endung (kein HLS-Manifest),
  die sich in gängigen Playern (VLC/mpv/Kodi/PotPlayer) öffnen lässt.

  - Schreibt UTF-8 Header (#EXTM3U + #EXTENC:UTF-8)
  - Für jeden Track: #EXTINF:<dauer>,<titel>
  - Dauer wird per ffprobe ermittelt; falls unbekannt: -1
  - Standardmäßig portable Pfade:
      * ohne --recursive: Dateiname (im gleichen Ordner)
      * mit --recursive: Pfad relativ zu --dir
  - Mit --absolute: absolute Pfade in der Playlist

OPTIONEN:
  --dir <pfad>        Input-Ordner (Default: .)
  --out <datei>       Output Playlist (Default: playlist.m3u8)
  --recursive         Unterordner einbeziehen
  --absolute          Absolute Pfade schreiben (weniger portabel)
  --ext-regex <regex> Eigener Regex für Extensions (posix-extended, case-insensitive)

BEISPIELE:
  ff_m3u8_make --dir . --out playlist.m3u8
  ff_m3u8_make --dir /mnt/c/Musik/Album --out /mnt/c/Musik/Album/album.m3u8 --recursive
  ff_m3u8_make --dir . --out playlist.m3u8 --ext-regex '.*\.(mp3|flac)$'
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }

  local maxdepth_arg=(-maxdepth 1)
  (( RECURSIVE )) && maxdepth_arg=()

  # Dateien einsammeln (null-separiert, spaces-safe) + natürlich sortieren
  local -a files
  local f
  while IFS= read -r -d '' f; do
    files+=( "$f" )
  done < <(
    find "$DIR" "${maxdepth_arg[@]}" -type f -regextype posix-extended -iregex "$EXT_REGEX" -print0 \
    | sort -z -V
  )

  (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Dateien in: $DIR"; return 1; }

  # Output initialisieren (UTF-8 Extended M3U)
  {
    print -r -- "#EXTM3U"
    print -r -- "#EXTENC:UTF-8"
    print -r -- "#PLAYLIST:${OUT:t}"
  } > "$OUT" || { print -u2 "Kann nicht schreiben: $OUT"; return 1; }

  local dur title relpath linepath
  local dir_prefix="${DIR%/}/"

  for f in "${files[@]}"; do
    # Dauer (Sekunden, 3 Nachkommastellen) – fallback -1
    dur="$(
      ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f" 2>/dev/null \
      | awk '{
          if ($1 ~ /^[0-9.]+$/) printf "%.3f\n",$1;
          else print "-1"
        }'
    )"
    [[ -n "$dur" ]] || dur="-1"

    title="${f:t}"
    title="${title%.*}"

    if (( ABSOLUTE )); then
      linepath="$f"
    else
      if (( RECURSIVE )); then
        relpath="$f"
        # Prefix entfernen, wenn Datei innerhalb DIR liegt
        [[ "$relpath" == "$dir_prefix"* ]] && relpath="${relpath#$dir_prefix}"
        linepath="$relpath"
      else
        linepath="${f:t}"
      fi
    fi

    print -r -- "#EXTINF:${dur},${title}" >> "$OUT"
    print -r -- "${linepath}" >> "$OUT"
  done

  print -r -- "OK: geschrieben -> $OUT"
}

ff_vignette() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1

  local IN="" OUT="" DIR="" CRF="18" PRESET="medium" ANGLE="PI/4"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)     IN="${2:-}"; shift 2 ;;
      --out)    OUT="${2:-}"; shift 2 ;;
      --dir)    DIR="${2:-}"; shift 2 ;;
      --crf)    CRF="${2:-18}"; shift 2 ;;
      --preset) PRESET="${2:-medium}"; shift 2 ;;
      --angle)  ANGLE="${2:-PI/4}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_vignette
===========
Erzeugt eine Vignette per FFmpeg "vignette" Filter.

USAGE (Single):
  ff_vignette --in input.mp4 [--out out.mp4] [--angle PI/4] [--crf 18] [--preset medium]

USAGE (Batch):
  ff_vignette --dir /pfad/zum/ordner [--angle PI/4] [--crf 18] [--preset medium]
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

OPTIONEN:
  --angle  Stärke/Größe (kleiner = stärker, größer = softer). Default: PI/4

NOTES:
  - Metadaten (Tags, Kapitel) werden übernommen.
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    local VF="vignette=${ANGLE}"
    if ff__has_audio "$_in"; then
      ffmpeg -y -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -vf "$VF" \
        -map 0:v:0 -map "0:a?" \
        -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
        -c:a aac -profile:a aac_low -b:a 192k -ar 48000 -ac 2 \
        -movflags +faststart \
        "$_out"
    else
      ffmpeg -y -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -vf "$VF" \
        -map 0:v:0 -an \
        -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
        -movflags +faststart \
        "$_out"
    fi
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}.mp4"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_vignette --in <input.mp4> [--out out.mp4]  (oder: --dir /pfad)"; return 1; }
  [[ -n "$OUT" ]] || OUT="${IN%.*}-vignette.mp4"
  _one "$IN" "$OUT"
}

ff_strip_audio() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1

  local IN="" OUT="" DIR=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)  IN="${2:-}"; shift 2 ;;
      --out) OUT="${2:-}"; shift 2 ;;
      --dir) DIR="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_strip_audio
==============
Entfernt Audio aus einem Video (remux, kein Re-Encode).

USAGE (Single):
  ff_strip_audio --in input.(mp4|mkv|mov|webm) [--out out.(mp4|mkv|mov|webm)]

USAGE (Batch):
  ff_strip_audio --dir /pfad/zum/ordner
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

NOTES:
  - Wenn du --out weglässt, wird die Endung des Inputs beibehalten.
  - Metadaten (Tags, Kapitel) werden übernommen.
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    local -a MOVFLAGS=()
    case "${_out##*.}" in
      mp4|mov) MOVFLAGS=( -movflags +faststart ) ;;
    esac
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$_in" \
      -map_metadata 0 -map_chapters 0 \
      -map 0:v:0 -an \
      -c:v copy \
      "${MOVFLAGS[@]}" \
      "$_out"
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base ext stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; ext="${base##*.}"; stem="${base%.*}"
      out="$OUTDIR/${stem}.${ext}"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_strip_audio --in <input> [--out out]  (oder: --dir /pfad)"; return 1; }
  local ext="${IN##*.}"
  [[ -n "$OUT" ]] || OUT="${IN%.*}-noaudio.${ext}"
  _one "$IN" "$OUT"
}

ff_rev() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1

  local IN="" DIR=""
  # backward compat: positional arg
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    IN="$1"; shift
  fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)  IN="${2:-}"; shift 2 ;;
      --dir) DIR="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_rev
======
Video umkehren (reverse).

USAGE (Single):
  ff_rev <input.mp4>
  ff_rev --in input.mp4

USAGE (Batch):
  ff_rev --dir /pfad/zum/ordner
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

NOTES:
  - Audio wird entfernt (Reverse-Audio ist selten gewünscht).
  - Metadaten (Tags, Kapitel) werden übernommen.
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$_in" \
      -map_metadata 0 -map_chapters 0 \
      -vf reverse \
      -an \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -movflags +faststart \
      "$_out"
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}-ff_rev.mp4"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_rev <input.mp4>  (oder: --dir /pfad)"; return 1; }
  _one "$IN" "${IN%.*}-ff_rev.mp4"
}

ff_audio_loop_video() {
  ff__strict
  ff__need ffmpeg || return 1

  local VIDEO="${1:-}"
  local AUDIO="${2:-}"
  local OUTPUT="${3:-}"

  [[ -n "$VIDEO" && -f "$VIDEO" && -n "$AUDIO" && -f "$AUDIO" ]] || { print -u2 "Usage: ff_audio_loop_video <video.mp4> <audio.wav|mp3> [out.mp4]"; return 1; }
  [[ -n "$OUTPUT" ]] || OUTPUT="${VIDEO%.*}-loop-to-audio.mp4"

  ffmpeg -y -hide_banner -loglevel error -stats \
    -stream_loop -1 -i "$VIDEO" \
    -i "$AUDIO" \
    -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 -ac 2 \
    -shortest -movflags +faststart \
    "$OUTPUT"
}

ff_audio_vid_to_vid() {
  ff__strict
  ff__need ffmpeg || return 1

  local VIDEO="" AUDIO="" OUT="" CRF="18" PRESET="medium" ABR="192k"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --video)  VIDEO="${2:-}"; shift 2 ;;
      --audio)  AUDIO="${2:-}"; shift 2 ;;
      --out)    OUT="${2:-}"; shift 2 ;;
      --crf)    CRF="${2:-18}"; shift 2 ;;
      --preset) PRESET="${2:-medium}"; shift 2 ;;
      --abr)    ABR="${2:-192k}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_audio_vid_to_vid
USAGE: ff_audio_vid_to_vid --video loop.mp4 --audio song.wav --out out.mp4 [--crf 18] [--preset medium] [--abr 192k]
Hinweis: Für maximale Huawei/Android-Kompatibilität wird AAC-LC in MP4 verwendet (nicht lossless, aber zuverlässig abspielbar).
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  [[ -n "$VIDEO" && -f "$VIDEO" && -n "$AUDIO" && -f "$AUDIO" && -n "$OUT" ]] || {
    print -u2 "Usage: ff_audio_vid_to_vid --video <video.mp4> --audio <audio> --out <out.mp4>"
    return 1
  }

  ffmpeg -y -hide_banner -loglevel error -stats \
    -stream_loop -1 -i "$VIDEO" \
    -i "$AUDIO" \
    -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
    -c:a aac -profile:a aac_low -b:a "$ABR" -ar 44100 -ac 2 \
    -shortest -movflags +faststart \
    "$OUT"
}

ff_vid() {
  ff__strict

  local audio="" video="" srt="" ass="" out="out.mp4"
  local crf="18" preset="medium" fps="30" scale="1080"
  local shift="0" fontsize="28" marginv="60" outline="2" shadow="1"

  while (( $# )); do
    case "$1" in
      --audio)   [[ $# -ge 2 ]] || { print -u2 "Fehler: --audio benötigt Pfad"; return 2; }; audio="$2"; shift 2;;
      --video)   [[ $# -ge 2 ]] || { print -u2 "Fehler: --video benötigt Pfad"; return 2; }; video="$2"; shift 2;;
      --srt)     [[ $# -ge 2 ]] || { print -u2 "Fehler: --srt benötigt Pfad"; return 2; }; srt="$2"; shift 2;;
      --ass)     [[ $# -ge 2 ]] || { print -u2 "Fehler: --ass benötigt Pfad"; return 2; }; ass="$2"; shift 2;;
      --out)     [[ $# -ge 2 ]] || { print -u2 "Fehler: --out benötigt Pfad"; return 2; }; out="$2"; shift 2;;
      --crf)     [[ $# -ge 2 ]] || { print -u2 "Fehler: --crf benötigt Wert"; return 2; }; crf="$2"; shift 2;;
      --preset)  [[ $# -ge 2 ]] || { print -u2 "Fehler: --preset benötigt Wert"; return 2; }; preset="$2"; shift 2;;
      --fps)     [[ $# -ge 2 ]] || { print -u2 "Fehler: --fps benötigt Wert"; return 2; }; fps="$2"; shift 2;;
      --scale)   [[ $# -ge 2 ]] || { print -u2 "Fehler: --scale benötigt Wert"; return 2; }; scale="$2"; shift 2;;
      --shift)   [[ $# -ge 2 ]] || { print -u2 "Fehler: --shift benötigt Sekunden (z.B. -2.5)"; return 2; }; shift="$2"; shift 2;;
      --fontsize) [[ $# -ge 2 ]] || { print -u2 "Fehler: --fontsize benötigt Wert"; return 2; }; fontsize="$2"; shift 2;;
      --marginv) [[ $# -ge 2 ]] || { print -u2 "Fehler: --marginv benötigt Wert"; return 2; }; marginv="$2"; shift 2;;
      --outline) [[ $# -ge 2 ]] || { print -u2 "Fehler: --outline benötigt Wert"; return 2; }; outline="$2"; shift 2;;
      --shadow)  [[ $# -ge 2 ]] || { print -u2 "Fehler: --shadow benötigt Wert"; return 2; }; shadow="$2"; shift 2;;
      -h|--help)
        cat <<'EOF'
ff_vid --audio A --video V [--srt S | --ass X] [--out O]
                     [--shift -2.5] [--fontsize 28] [--marginv 60] [--outline 2] [--shadow 1]
                     [--crf 18] [--preset medium] [--fps 30] [--scale 1080]

- Loop-Video läuft bis Audio-Ende (-stream_loop -1 + -shortest)
- Untertitel werden eingebrannt (ASS bevorzugt vor SRT)
- --shift: negative Werte = früher, positive = später
EOF
        return 0
        ;;
      *) print -u2 "Fehler: Unbekannter Parameter: $1"; return 2;;
    esac
  done

  command -v ffmpeg >/dev/null 2>&1 || { print -u2 "Fehler: ffmpeg nicht gefunden"; return 127; }
  [[ -n "$audio" && -f "$audio" ]] || { print -u2 "Fehler: Audio fehlt/ungültig"; return 2; }
  [[ -n "$video" && -f "$video" ]] || { print -u2 "Fehler: Video fehlt/ungültig"; return 2; }

  if [[ -n "$srt" && ! -f "$srt" ]]; then print -u2 "Fehler: SRT nicht gefunden: $srt"; return 2; fi
  if [[ -n "$ass" && ! -f "$ass" ]]; then print -u2 "Fehler: ASS nicht gefunden: $ass"; return 2; fi

  local tmpdir; tmpdir="$(mktemp -d)"
  local tmpsubs=""
  trap 'rm -rf "$tmpdir"' EXIT

  # Untertitel vorbereiten: Zeiten shiften + Größe anpassen
  # ASS bevorzugt vor SRT
  if [[ -n "$ass" ]]; then
    tmpsubs="${tmpdir}/subs.ass"
    python3 - "$ass" "$tmpsubs" "$shift" "$fontsize" "$marginv" <<'PY'
import sys, re

src, dst, shift_s, fontsize, marginv = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5]

def parse_ass_time(t: str) -> float:
    # H:MM:SS.CS
    m = re.match(r"^(\d+):([0-5]\d):([0-5]\d)\.(\d{1,2})$", t.strip())
    if not m:
        return None
    h, mi, s, cs = m.groups()
    return int(h)*3600 + int(mi)*60 + int(s) + int(cs)/100.0

def fmt_ass_time(sec: float) -> str:
    if sec < 0: sec = 0.0
    cs_total = int(round(sec * 100.0))
    h = cs_total // 360000
    cs_total -= h * 360000
    mi = cs_total // 6000
    cs_total -= mi * 6000
    s = cs_total // 100
    cs = cs_total - s * 100
    return f"{h}:{mi:02d}:{s:02d}.{cs:02d}"

out = []
style_re = re.compile(r"^Style:\s*Default,([^,]*),(\d+),(.*)$")
dial_re = re.compile(r"^Dialogue:\s*\d+,([^,]+),([^,]+),(.*)$")

with open(src, "r", encoding="utf-8") as f:
    for line in f:
        # Style: Default,Arial,42,...
        m = style_re.match(line.rstrip("\n"))
        if m:
            fontname, _oldsize, rest = m.groups()
            out.append(f"Style: Default,{fontname},{fontsize},{rest}\n")
            continue

        # Optional: MarginV im Style nicht trivial zuverlässig (Format abhängig) -> wir lassen Style-Margins,
        # und setzen MarginV über \pos nicht; stattdessen nutzen wir Force-Style nicht.
        # (Player bleibt konsistent, MarginV kannst du über den Style-Header im Generator setzen.)
        # Dialogue: 0,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
        m = dial_re.match(line.rstrip("\n"))
        if m:
            st, en, rest = m.groups()
            st_s = parse_ass_time(st)
            en_s = parse_ass_time(en)
            if st_s is not None and en_s is not None:
                st_s += shift_s
                en_s += shift_s
                if en_s <= st_s:
                    en_s = st_s + 0.50
                out.append(f"Dialogue: 0,{fmt_ass_time(st_s)},{fmt_ass_time(en_s)},{rest}\n")
                continue

        out.append(line)

with open(dst, "w", encoding="utf-8", newline="\n") as f:
    f.writelines(out)
PY
  elif [[ -n "$srt" ]]; then
    tmpsubs="${tmpdir}/subs.srt"
    python3 - "$srt" "$tmpsubs" "$shift" <<'PY'
import sys, re
src, dst, shift_s = sys.argv[1], sys.argv[2], float(sys.argv[3])

def parse_srt_time(t: str) -> float:
    # HH:MM:SS,mmm
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", t.strip())
    if not m:
        return None
    hh, mm, ss, ms = map(int, m.groups())
    return hh*3600 + mm*60 + ss + ms/1000.0

def fmt_srt_time(sec: float) -> str:
    if sec < 0: sec = 0.0
    ms_total = int(round(sec*1000.0))
    hh = ms_total // 3600000
    ms_total -= hh*3600000
    mm = ms_total // 60000
    ms_total -= mm*60000
    ss = ms_total // 1000
    ms = ms_total - ss*1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

time_line = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*$")

out = []
with open(src, "r", encoding="utf-8") as f:
    for line in f:
        m = time_line.match(line)
        if m:
            a, b = m.groups()
            sa = parse_srt_time(a); sb = parse_srt_time(b)
            if sa is not None and sb is not None:
                sa += shift_s
                sb += shift_s
                if sb <= sa:
                    sb = sa + 0.50
                out.append(f"{fmt_srt_time(sa)} --> {fmt_srt_time(sb)}\n")
                continue
        out.append(line)

with open(dst, "w", encoding="utf-8", newline="\n") as f:
    f.writelines(out)
PY
  fi
  TOTAL="$(ff__duration "$audio")"
  ZEIT="$(ff__sec_to_hhmmss "$TOTAL")"
  local vf="scale=${scale}:-2,setsar=1,fps=${fps}"

  if [[ -n "$tmpsubs" && "$tmpsubs" == *.srt ]]; then
    # SRT: Stil via force_style
    vf="${vf},subtitles=${tmpsubs}:force_style='FontName=Arial,FontSize=${fontsize},Outline=${outline},Shadow=${shadow},MarginV=${marginv}'"
  elif [[ -n "$tmpsubs" && "$tmpsubs" == *.ass ]]; then
    # ASS: Fontsize wurde im tmp ASS angepasst
    vf="${vf},ass=${tmpsubs}"
  fi
  echo -e "\nFertiges video wird erstellt.\nAudiolänge: $ZEIT\nDateiname: $out\n"
  ffmpeg -y -hide_banner -loglevel error -stats \
    -stream_loop -1 -i "$video" \
    -i "$audio" \
    -filter_complex "[0:v]${vf}[v]" \
    -map "[v]" -map 1:a \
    -c:v libx264 -preset "$preset" -crf "$crf" -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -shortest -movflags +faststart -t "$TOTAL" \
    "$out"
}

ff_fades() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1
  ff__need awk || return 1

  local IN="" DIR=""
  local F_TIME="1.0" MODE="both"

  # backward compat: positional args
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    IN="$1"; shift
    if [[ $# -gt 0 && "${1}" != --* ]]; then
      F_TIME="$1"; shift
    fi
    if [[ $# -gt 0 && "${1}" != --* ]]; then
      MODE="$1"; shift
    fi
  fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)   IN="${2:-}"; shift 2 ;;
      --dir)  DIR="${2:-}"; shift 2 ;;
      --time) F_TIME="${2:-1.0}"; shift 2 ;;
      --mode) MODE="${2:-both}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_fades
========
Video Fade-In/Out hinzufügen.

USAGE (Single):
  ff_fades <input> [fade_time] [both|in|out]
  ff_fades --in input.mp4 [--time 1.0] [--mode both|in|out]

USAGE (Batch):
  ff_fades --dir /pfad/zum/ordner [--time 1.0] [--mode both]
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

NOTES:
  - Metadaten (Tags, Kapitel) werden übernommen.
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }

    local DUR FO VF
    DUR="$(ff__duration "$_in")"
    [[ -n "$DUR" && "$DUR" != "0.000000" ]] || { print -u2 "Konnte Videodauer nicht ermitteln: $_in"; return 1; }

    FO="$(awk -v dur="$DUR" -v ft="$F_TIME" 'BEGIN{v=dur-ft; if(v<0)v=0; printf "%.6f", v}')"

    case "$MODE" in
      both) VF="fade=t=in:st=0:d=${F_TIME},fade=t=out:st=${FO}:d=${F_TIME}" ;;
      in)   VF="fade=t=in:st=0:d=${F_TIME}" ;;
      out)  VF="fade=t=out:st=${FO}:d=${F_TIME}" ;;
      *) print -u2 "Unbekannter Modus: $MODE (both|in|out)"; return 1 ;;
    esac

    if ff__has_audio "$_in"; then
      ffmpeg -y -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -vf "$VF" \
        -map 0:v:0 -map "0:a?" \
        -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
        -c:a aac -b:a 192k -ar 48000 -ac 2 \
        -movflags +faststart \
        "$_out"
    else
      ffmpeg -y -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -vf "$VF" \
        -map 0:v:0 -an \
        -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
        -movflags +faststart \
        "$_out"
    fi
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}-fade_${MODE}.mp4"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_fades <input> [fade_time] [both|in|out]  (oder: --dir /pfad)"; return 1; }
  _one "$IN" "${IN%.*}-fade_${MODE}.mp4"
}

ff_mkvid_create() {
  ff__strict

  local audio="" video="" srt="" ass="" out="out.mp4"
  local crf="18" preset="medium" fps="30" scale="1920"

  # --- Arg Parsing ---
  while (( $# )); do
    case "$1" in
      --audio)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --audio benötigt einen Pfad"; return 2; }
        audio="$2"; shift 2;;
      --video)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --video benötigt einen Pfad"; return 2; }
        video="$2"; shift 2;;
      --srt)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --srt benötigt einen Pfad"; return 2; }
        srt="$2"; shift 2;;
      --ass)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --ass benötigt einen Pfad"; return 2; }
        ass="$2"; shift 2;;
      --out)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --out benötigt einen Pfad"; return 2; }
        out="$2"; shift 2;;
      --crf)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --crf benötigt einen Wert"; return 2; }
        crf="$2"; shift 2;;
      --preset)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --preset benötigt einen Wert"; return 2; }
        preset="$2"; shift 2;;
      --fps)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --fps benötigt einen Wert"; return 2; }
        fps="$2"; shift 2;;
      --scale)
        [[ $# -ge 2 ]] || { print -u2 "Fehler: --scale benötigt einen Wert"; return 2; }
        scale="$2"; shift 2;;
      -h|--help)
        cat <<'EOF'
ff_mkvid_create --audio A --video V [--srt S] [--ass X] [--out O] [--crf N] [--preset P] [--fps N] [--scale W]

Erstellt ein MP4: Loop-Video läuft bis Audio-Ende. Untertitel werden optional eingebrannt (ASS bevorzugt vor SRT).
EOF
        return 0;;
      *)
        print -u2 "Fehler: Unbekannter Parameter: $1"
        return 2;;
    esac
  done

  # --- Validierung ---
  command -v ffmpeg >/dev/null 2>&1 || { print -u2 "Fehler: ffmpeg nicht gefunden"; return 127; }

  [[ -n "$audio" ]] || { print -u2 "Fehler: --audio ist erforderlich"; return 2; }
  [[ -n "$video" ]] || { print -u2 "Fehler: --video ist erforderlich"; return 2; }

  [[ -f "$audio" ]] || { print -u2 "Fehler: Audio-Datei nicht gefunden: $audio"; return 2; }
  [[ -f "$video" ]] || { print -u2 "Fehler: Video-Datei nicht gefunden: $video"; return 2; }

  if [[ -n "$srt" && ! -f "$srt" ]]; then
    print -u2 "Fehler: SRT-Datei nicht gefunden: $srt"
    return 2
  fi
  if [[ -n "$ass" && ! -f "$ass" ]]; then
    print -u2 "Fehler: ASS-Datei nicht gefunden: $ass"
    return 2
  fi

  # --- Filter bauen ---
  local vf=""
  # Basis-Video: skalieren, SAR setzen, FPS
  vf="scale=${scale}:-2,setsar=1,fps=${fps}"

  # Untertitel bevorzugt ASS, sonst SRT
  if [[ -n "$ass" ]]; then
    # ASS Burn-in (libass)
    vf="${vf},ass=$(printf '%q' "$ass")"
  elif [[ -n "$srt" ]]; then
    # SRT Burn-in (libass)
    vf="${vf},subtitles=$(printf '%q' "$srt")"
  fi

  # --- ffmpeg ausführen ---
  ffmpeg -y -hide_banner -loglevel error -stats \
    -stream_loop -1 -i "$video" \
    -i "$audio" \
    -filter_complex "[0:v]${vf}[v]" \
    -map "[v]" -map 1:a \
    -c:v libx264 -preset "$preset" -crf "$crf" -pix_fmt yuv420p \
    -c:a aac -b:a 192k \
    -shortest -movflags +faststart \
    "$out"
}

ff_softlight_overlay() {
  local INPUT="$1"
  local FX="$2"
  local ALPHA="${3:-0.24}"
  local DURATION="${4:-31.500}"

  if [[ -z "$INPUT" || -z "$FX" ]]; then
    echo "Usage: ff_softlight_overlay <input.mp4> <fx.mp4> [alpha=0.24] [duration=31.500]"
    return 1
  fi

  local OUTPUT="${INPUT:r}-softlight.mp4"

  # Alpha numerisch + 0..1
  if ! [[ "$ALPHA" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Fehler: alpha muss numerisch sein (z.B. 0.24)."
    return 1
  fi
  if awk "BEGIN{exit !($ALPHA>=0 && $ALPHA<=1)}"; then :; else
    echo "Fehler: alpha muss zwischen 0 und 1 liegen (z.B. 0.24)."
    return 1
  fi

  # Duration numerisch + >0
  if ! [[ "$DURATION" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Fehler: duration muss numerisch sein (z.B. 31.5)."
    return 1
  fi
  if awk "BEGIN{exit !($DURATION>0)}"; then :; else
    echo "Fehler: duration muss > 0 sein."
    return 1
  fi

  ffmpeg -y \
    -hide_banner \
    -loglevel error \
    -stats \
    -t "$DURATION" \
    -i "$INPUT" \
    -stream_loop -1 -i "$FX" \
    -filter_complex "\
[1:v]trim=0:${DURATION},setpts=PTS-STARTPTS,format=yuv420p[fx]; \
[fx][0:v]scale2ref[fxs][base]; \
[base][fxs]blend=all_mode=softlight:all_opacity=${ALPHA},format=yuv420p[v]" \
    -map "[v]" \
    -an \
    -c:v libx264 \
    -crf 18 \
    -preset medium \
    -pix_fmt yuv420p \
    "$OUTPUT"
}


ff_softlight_overlay2() {
  local INPUT="$1"
  local FX="$2"
  local ALPHA="${3:-0.12}"
  local DURATION="${4:-31.500}"

  if [[ -z "$INPUT" || -z "$FX" ]]; then
    echo "Usage: ff_softlight_overlay <input.mp4> <fx.mp4> [alpha=0.12] [duration=31.500]"
    return 1
  fi

  # Output automatisch aus Input ableiten
  local OUTPUT="${INPUT:r}-softlight.mp4"

  # Alpha numerisch + 0..1
  if ! [[ "$ALPHA" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Fehler: alpha muss numerisch sein (z.B. 0.12)."
    return 1
  fi
  if awk "BEGIN{exit !($ALPHA>=0 && $ALPHA<=1)}"; then :; else
    echo "Fehler: alpha muss zwischen 0 und 1 liegen (z.B. 0.12)."
    return 1
  fi

  # Duration numerisch + >0
  if ! [[ "$DURATION" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "Fehler: duration muss numerisch sein (z.B. 31.5)."
    return 1
  fi
  if awk "BEGIN{exit !($DURATION>0)}"; then :; else
    echo "Fehler: duration muss > 0 sein."
    return 1
  fi

  ffmpeg -y \
    -hide_banner \
    -loglevel error \
    -stats \
    -t "$DURATION" \
    -i "$INPUT" \
    -stream_loop -1 -i "$FX" \
    -filter_complex "[1:v]trim=0:${DURATION},setpts=PTS-STARTPTS,format=rgba,colorchannelmixer=aa=${ALPHA}[fx];[fx][0:v]scale2ref[fxs][base];[base][fxs]blend=all_mode=softlight:all_opacity=1.0,format=yuv420p[v]" \
    -map "[v]" \
    -an \
    -c:v libx264 \
    -crf 18 \
    -preset medium \
    -pix_fmt yuv420p \
    "$OUTPUT"
}


ff_speed() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1

  local IN="" DIR=""
  local PTSTIME="1.5"

  # backward compat: positional args
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    IN="$1"; shift
    if [[ $# -gt 0 && "${1}" != --* ]]; then
      PTSTIME="$1"; shift
    fi
  fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)     IN="${2:-}"; shift 2 ;;
      --dir)    DIR="${2:-}"; shift 2 ;;
      --factor) PTSTIME="${2:-1.5}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_speed
========
Video-Geschwindigkeit ändern per setpts + minterpolate.

USAGE (Single):
  ff_speed <input.mp4> [setpts_factor]
  ff_speed --in input.mp4 [--factor 1.5]

USAGE (Batch):
  ff_speed --dir /pfad/zum/ordner [--factor 1.5]
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

NOTES:
  - factor < 1 = schneller, factor > 1 = langsamer
  - Audio wird entfernt (Speed-Audio ist selten gewünscht).
  - Metadaten (Tags, Kapitel) werden übernommen.
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$_in" \
      -map_metadata 0 -map_chapters 0 \
      -vf "setpts=${PTSTIME}*PTS,minterpolate=fps=60" \
      -an \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -movflags +faststart \
      "$_out"
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}-ff_speed.mp4"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_speed <input.mp4> [factor]  (oder: --dir /pfad)"; return 1; }
  _one "$IN" "${IN%.*}-ff_speed.mp4"
}

ff_concat_list() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need sed || return 1

  local list_file="${1:-}"
  local out_file="${2:-}"
  local crf="${3:-18}"
  local preset="${4:-medium}"

  [[ -n "$list_file" && -f "$list_file" && -n "$out_file" ]] || { print -u2 "Usage: ff_concat_list <list.txt> <out.mp4> [crf] [preset]"; return 1; }

  local -a files
  files=("${(@f)$(sed -n "s/^file '\(.*\)'$/\1/p" "$list_file")}")

  (( ${#files[@]} >= 2 )) || { print -u2 "Mindestens 2 'file' Einträge in $list_file nötig."; return 1; }

  local -a inputs
  local filter="" vin="" ain=""
  local i
  local any_audio=0

  for i in {1..${#files[@]}}; do
    [[ -f "${files[$i]}" ]] || { print -u2 "Datei nicht gefunden: ${files[$i]}"; return 1; }
    inputs+=( -i "${files[$i]}" )
    filter+="[$((i-1)):v]setpts=PTS-STARTPTS,format=yuv420p[v$((i-1))];"
    vin+="[v$((i-1))]"
    if ff__has_audio "${files[$i]}"; then
      any_audio=1
      filter+="[$((i-1)):a]asetpts=PTS-STARTPTS[a$((i-1))];"
      ain+="[a$((i-1))]"
    else
      any_audio=1
      filter+="anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:0.001,asetpts=PTS-STARTPTS[a$((i-1))];"
      ain+="[a$((i-1))]"
    fi
  done

  if (( any_audio )); then
    filter+="${vin}concat=n=${#files[@]}:v=1:a=0[v];${ain}concat=n=${#files[@]}:v=0:a=1[a]"
    ffmpeg -y -hide_banner -loglevel error -stats \
      "${inputs[@]}" \
      -filter_complex "$filter" \
      -map "[v]" -map "[a]" \
      -c:v libx264 -crf "$crf" -preset "$preset" -pix_fmt yuv420p \
      -c:a aac -b:a 192k -ar 48000 -ac 2 \
      -movflags +faststart \
      "$out_file"
  else
    filter+="${vin}concat=n=${#files[@]}:v=1:a=0[v]"
    ffmpeg -y -hide_banner -loglevel error -stats \
      "${inputs[@]}" \
      -filter_complex "$filter" \
      -map "[v]" \
      -c:v libx264 -crf "$crf" -preset "$preset" -pix_fmt yuv420p \
      -an -movflags +faststart \
      "$out_file"
  fi
}

ff_twix() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1
  ff__need awk || return 1

  local FILE="" OUTPUT="" START="" DUR=""
  local FACTOR="2" FPS="60" CRF="18" PRESET="medium"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --file)     FILE="${2:-}"; shift 2 ;;
      --output)   OUTPUT="${2:-}"; shift 2 ;;
      --start)    START="${2:-}"; shift 2 ;;
      --duration) DUR="${2:-}"; shift 2 ;;
      --factor)   FACTOR="${2:-}"; shift 2 ;;
      --fps)      FPS="${2:-}"; shift 2 ;;
      --crf)      CRF="${2:-}"; shift 2 ;;
      --preset)   PRESET="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_twix
USAGE: ff_twix --file input.mp4 --output out.mp4 --start 3.2 --duration 1.5 [--factor 2] [--fps 60] [--crf 18] [--preset medium]
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  [[ -n "$FILE" && -f "$FILE" && -n "$OUTPUT" && -n "$START" && -n "$DUR" ]] || { print -u2 "Usage: ff_twix --file <in> --output <out> --start <sec> --duration <sec>"; return 1; }

  [[ "$START"  == <->(|.<->) || "$START"  == <->.<-> ]] || { print -u2 "--start muss Zahl sein"; return 1; }
  [[ "$DUR"    == <->(|.<->) || "$DUR"    == <->.<-> ]] || { print -u2 "--duration muss Zahl sein"; return 1; }
  [[ "$FACTOR" == <->(|.<->) || "$FACTOR" == <->.<-> ]] || { print -u2 "--factor muss Zahl sein"; return 1; }
  [[ "$FPS"    == <->(|.<->) || "$FPS"    == <->.<-> ]] || { print -u2 "--fps muss Zahl sein"; return 1; }
  [[ "$CRF"    == <-> ]] || { print -u2 "--crf muss ganze Zahl sein"; return 1; }

  local TOTAL END
  TOTAL="$(ff__duration "$FILE")"
  END="$(awk "BEGIN{print $START+$DUR}")"
  awk "BEGIN{exit !($START>=0)}" || { print -u2 "Startzeit muss >= 0 sein"; return 1; }
  awk "BEGIN{exit !($DUR>0)}" || { print -u2 "Dauer muss > 0 sein"; return 1; }
  awk "BEGIN{exit !($FACTOR>0)}" || { print -u2 "Faktor muss > 0 sein"; return 1; }
  awk "BEGIN{exit !($END<=$TOTAL)}" || { awk "BEGIN{printf \"Zeitfenster übersteigt Videolänge. Video=%.3fs Ende=%.3fs\n\", $TOTAL, $END}" >&2; return 1; }

  ffmpeg -y -hide_banner -loglevel error -stats -fflags +genpts -i "$FILE" \
    -filter_complex "\
[0:v]fps=${FPS},format=yuv420p,split=3[vpre][veff][vpost];\
[vpre]trim=start=0:end=${START},setpts=PTS-STARTPTS[pre];\
[veff]trim=start=${START}:end=${END},setpts=PTS-STARTPTS,\
minterpolate=fps=${FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,\
setpts=${FACTOR}*PTS[eff];\
[vpost]trim=start=${END},setpts=PTS-STARTPTS[post];\
[pre][eff][post]concat=n=3:v=1:a=0[outv]" \
    -map "[outv]" -r "$FPS" -an \
    -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
    -movflags +faststart \
    "$OUTPUT"
}

ff_still() {
  ff__strict
  ff__need ffmpeg || return 1

  local IN="" OUT="" SEC=""
  local FPS="30" W="" H=""
  local CRF="18" PRESET="medium"
  local WITH_AUDIO="0"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in) IN="${2:-}"; shift 2 ;;
      --out) OUT="${2:-}"; shift 2 ;;
      --sec) SEC="${2:-}"; shift 2 ;;
      --fps) FPS="${2:-}"; shift 2 ;;
      --w) W="${2:-}"; shift 2 ;;
      --h) H="${2:-}"; shift 2 ;;
      --crf) CRF="${2:-}"; shift 2 ;;
      --preset) PRESET="${2:-}"; shift 2 ;;
      --audio) WITH_AUDIO="1"; shift 1 ;;
      --help|-h)
        cat <<'EOF'
ff_still
USAGE: ff_still --in image.png --out out.mp4 --sec 7.5 [--fps 30] [--w 1920] [--h 1080] [--crf 18] [--preset medium] [--audio]
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  [[ -n "$IN" && -f "$IN" && -n "$OUT" && -n "$SEC" ]] || { print -u2 "Usage: ff_still --in <img> --out <out.mp4> --sec <seconds>"; return 1; }

  [[ "$SEC" == <->(|.<->) || "$SEC" == <->.<-> ]] || { print -u2 "--sec muss Zahl sein"; return 1; }
  [[ "$FPS" == <-> ]] || { print -u2 "--fps muss ganze Zahl sein"; return 1; }
  [[ "$CRF" == <-> ]] || { print -u2 "--crf muss ganze Zahl sein"; return 1; }
  [[ -z "$W" || "$W" == <-> ]] || { print -u2 "--w muss Zahl sein"; return 1; }
  [[ -z "$H" || "$H" == <-> ]] || { print -u2 "--h muss Zahl sein"; return 1; }

  local vf=""
  if [[ -n "$W" && -n "$H" ]]; then
    vf="scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
  elif [[ -n "$W" && -z "$H" ]]; then
    vf="scale=${W}:-2,setsar=1,format=yuv420p"
  elif [[ -z "$W" && -n "$H" ]]; then
    vf="scale=-2:${H},setsar=1,format=yuv420p"
  else
    vf="scale=1920:-2,setsar=1,format=yuv420p"
  fi

  if [[ "$WITH_AUDIO" == "1" ]]; then
    ffmpeg -y -hide_banner -loglevel error -stats \
      -loop 1 -i "$IN" \
      -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
      -t "$SEC" -r "$FPS" \
      -vf "$vf" \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -c:a aac -b:a 160k -ar 48000 -ac 2 \
      -shortest -movflags +faststart \
      "$OUT"
  else
    ffmpeg -y -hide_banner -loglevel error -stats \
      -loop 1 -i "$IN" \
      -t "$SEC" -r "$FPS" \
      -vf "$vf" \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -an -movflags +faststart \
      "$OUT"
  fi
}

ff_title_fade() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need awk || return 1

  local IN="" OUT="" TEXT=""
  local START="0" DUR="3" FADE="0.5"
  local COLOR="white" BOXCOLOR="black@0.0"
  local OUTLINE="4" OUTLINECOLOR="black"
  local FONTSIZE="64" X="(w-text_w)/2" Y="h*0.12"
  local FONT=""
  local CRF="18" PRESET="medium"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in) IN="${2:-}"; shift 2 ;;
      --out) OUT="${2:-}"; shift 2 ;;
      --text) TEXT="${2:-}"; shift 2 ;;
      --start) START="${2:-}"; shift 2 ;;
      --dur) DUR="${2:-}"; shift 2 ;;
      --fade) FADE="${2:-}"; shift 2 ;;
      --color) COLOR="${2:-}"; shift 2 ;;
      --boxcolor) BOXCOLOR="${2:-}"; shift 2 ;;
      --outline) OUTLINE="${2:-}"; shift 2 ;;
      --outlinecolor) OUTLINECOLOR="${2:-}"; shift 2 ;;
      --fontsize) FONTSIZE="${2:-}"; shift 2 ;;
      --x) X="${2:-}"; shift 2 ;;
      --y) Y="${2:-}"; shift 2 ;;
      --font) FONT="${2:-}"; shift 2 ;;
      --crf) CRF="${2:-}"; shift 2 ;;
      --preset) PRESET="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_title_fade
USAGE: ff_title_fade --in input.mp4 --out out.mp4 --text "Titel" [--start 0.5] [--dur 3] [--fade 0.5] [--color white] [--boxcolor black@0.35] [--outline 4] [--outlinecolor black] [--fontsize 64] [--x "(w-text_w)/2"] [--y "h*0.12"] [--font /path/font.ttf] [--crf 18] [--preset medium]
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  [[ -n "$IN" && -f "$IN" && -n "$OUT" && -n "$TEXT" ]] || { print -u2 "Usage: ff_title_fade --in <in> --out <out> --text <text>"; return 1; }

  [[ "$START" == <->(|.<->) || "$START" == <->.<-> ]] || { print -u2 "--start muss Zahl sein"; return 1; }
  [[ "$DUR"   == <->(|.<->) || "$DUR"   == <->.<-> ]] || { print -u2 "--dur muss Zahl sein"; return 1; }
  [[ "$FADE"  == <->(|.<->) || "$FADE"  == <->.<-> ]] || { print -u2 "--fade muss Zahl sein"; return 1; }
  [[ "$FONTSIZE" == <-> ]] || { print -u2 "--fontsize muss ganze Zahl sein"; return 1; }
  [[ "$OUTLINE"  == <-> ]] || { print -u2 "--outline muss ganze Zahl sein"; return 1; }
  awk "BEGIN{exit !($FADE*2 <= $DUR)}" || { print -u2 "ERROR: --fade*2 darf nicht > --dur sein"; return 1; }

  local END FADEOUT_START
  END="$(awk "BEGIN{print $START+$DUR}")"
  FADEOUT_START="$(awk "BEGIN{print $START+$DUR-$FADE}")"

  local TEXT_ESC
  TEXT_ESC="${TEXT//\\/\\\\}"
  TEXT_ESC="${TEXT_ESC//:/\\:}"
  TEXT_ESC="${TEXT_ESC//\'/\\\'}"

  local FONTARG=""
  if [[ -n "$FONT" ]]; then
    [[ -f "$FONT" ]] || { print -u2 "Font nicht gefunden: $FONT"; return 1; }
    FONTARG="fontfile=${FONT}:"
  fi

  local ALPHA_EXPR
  ALPHA_EXPR="if(between(t,${START},${END}),if(lt(t,${START}+${FADE}),(t-${START})/${FADE},if(lt(t,${FADEOUT_START}),1,(${END}-t)/${FADE})),0)"

  local VF
  VF="drawtext=${FONTARG}text='${TEXT_ESC}':x=${X}:y=${Y}:fontsize=${FONTSIZE}:fontcolor=${COLOR}:alpha='${ALPHA_EXPR}':borderw=${OUTLINE}:bordercolor=${OUTLINECOLOR}:box=1:boxcolor=${BOXCOLOR}:boxborderw=20"

  if ff__has_audio "$IN"; then
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$IN" \
      -vf "$VF" \
      -map 0:v:0 -map "0:a?" \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -c:a aac -b:a 192k -ar 48000 -ac 2 \
      -movflags +faststart \
      "$OUT"
  else
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$IN" \
      -vf "$VF" \
      -map 0:v:0 -an \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -movflags +faststart \
      "$OUT"
  fi
}

ff_color_blend() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1
  ff__need awk || return 1

  local INPUT="${1:-}"
  local START="${2:-}"
  local DURATION="${3:-}"
  local COLOR="${4:-black}"
  local FADE="${5:-0.5}"
  local ALPHA="${6:-0.65}"

  [[ -n "$INPUT" && -f "$INPUT" && -n "$START" && -n "$DURATION" ]] || { print -u2 "Usage: ff_color_blend <input> <start> <duration> [color] [fade] [alpha]"; return 1; }

  local OUTPUT
  OUTPUT="${INPUT%.*}-blend-${COLOR//[^a-zA-Z0-9#]/_}-${START//[:.]/_}-${DURATION}.mp4"

  local dims fps OUT_FADE_START W H
  dims="$(ff__dims "$INPUT")" || { print -u2 "Konnte W/H nicht ermitteln."; return 1; }
  W="${dims%x*}"
  H="${dims#*x}"
  fps="$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$INPUT" 2>/dev/null)"
  [[ -n "$fps" ]] || fps="30"

  OUT_FADE_START="$(awk -v d="$DURATION" -v f="$FADE" 'BEGIN{v=d-f; if(v<0)v=0; printf "%.6f", v}')"

  local map_audio=0
  ff__has_audio "$INPUT" && map_audio=1

  if (( map_audio )); then
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$INPUT" \
      -filter_complex "\
[0:v]split=1[v0]; \
color=c=${COLOR}:s=${W}x${H}:r=${fps}:d=${DURATION}[c0]; \
[c0]format=rgba,colorchannelmixer=aa=${ALPHA},fade=t=in:st=0:d=${FADE}:alpha=1,fade=t=out:st=${OUT_FADE_START}:d=${FADE}:alpha=1,setpts=PTS+(${START})/TB[c1]; \
[v0][c1]overlay=x=0:y=0:enable='between(t,${START},${START}+${DURATION})'[vout]" \
      -map "[vout]" -map "0:a?" \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -c:a aac -b:a 192k -ar 48000 -ac 2 \
      -movflags +faststart \
      "$OUTPUT"
  else
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$INPUT" \
      -filter_complex "\
[0:v]split=1[v0]; \
color=c=${COLOR}:s=${W}x${H}:r=${fps}:d=${DURATION}[c0]; \
[c0]format=rgba,colorchannelmixer=aa=${ALPHA},fade=t=in:st=0:d=${FADE}:alpha=1,fade=t=out:st=${OUT_FADE_START}:d=${FADE}:alpha=1,setpts=PTS+(${START})/TB[c1]; \
[v0][c1]overlay=x=0:y=0:enable='between(t,${START},${START}+${DURATION})'[vout]" \
      -map "[vout]" -an \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -movflags +faststart \
      "$OUTPUT"
  fi
}

ff_mov_overlay() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1
  ff__need awk || return 1

  local INPUT="${1:-}"
  local FX="${2:-}"
  local START="${3:-}"
  local DUR="${4:-}"
  local MODE="${5:-alpha}"
  local OPACITY="${6:-0.30}"
  local OUTPUT="${7:-}"

  [[ -n "$INPUT" && -f "$INPUT" && -n "$FX" && -f "$FX" && -n "$START" ]] || { print -u2 "Usage: ff_mov_overlay <input.mp4> <fx.mov/mp4> <start> [dur] [alpha|luma|screen|softlight|overlay] [opacity] [out.mp4]"; return 1; }

  [[ -n "$OUTPUT" ]] || OUTPUT="${INPUT%.*}-mov_overlay-${MODE}-${START//[:.]/_}${DUR:+-${DUR}}.mp4"

  local fx_dur="$DUR"
  if [[ -z "$fx_dur" ]]; then
    fx_dur="$(ff__duration "$FX")"
    [[ -n "$fx_dur" && "$fx_dur" != "0.000000" ]] || fx_dur="1.0"
  fi

  local map_audio=0
  ff__has_audio "$INPUT" && map_audio=1

  local FC
  case "$MODE" in
    alpha)
      FC="\
[0:v]setpts=PTS-STARTPTS[base0]; \
[1:v]trim=0:${fx_dur},setpts=PTS-STARTPTS,format=rgba,colorchannelmixer=aa=${OPACITY}[fx0]; \
[fx0][base0]scale2ref[fxs][base]; \
[fxs]setpts=PTS+(${START})/TB[fxT]; \
[base][fxT]overlay=0:0:enable='between(t,${START},${START}+${fx_dur})'[vout]"
      ;;
    luma)
      FC="\
[0:v]setpts=PTS-STARTPTS[base0]; \
[1:v]trim=0:${fx_dur},setpts=PTS-STARTPTS,split=2[fxc][fxm]; \
[fxc]format=rgba,colorchannelmixer=aa=${OPACITY}[fxc2]; \
[fxm]format=gray,eq=contrast=1.0:brightness=0.0[mask]; \
[fxc2][mask]alphamerge[fxa]; \
[fxa][base0]scale2ref[fxs][base]; \
[fxs]setpts=PTS+(${START})/TB[fxT]; \
[base][fxT]overlay=0:0:enable='between(t,${START},${START}+${fx_dur})'[vout]"
      ;;
    screen|softlight|overlay)
      FC="\
[0:v]setpts=PTS-STARTPTS[base0]; \
[1:v]trim=0:${fx_dur},setpts=PTS-STARTPTS,format=rgba,colorchannelmixer=aa=${OPACITY}[fx0]; \
[fx0][base0]scale2ref[fxs][base]; \
[fxs]setpts=PTS+(${START})/TB[fxT]; \
[base][fxT]blend=all_mode=${MODE}:all_opacity=1.0:enable='between(t,${START},${START}+${fx_dur})'[vout]"
      ;;
    *)
      print -u2 "MODE ungültig: $MODE"
      return 1
      ;;
  esac

  if (( map_audio )); then
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$INPUT" -i "$FX" \
      -filter_complex "$FC" \
      -map "[vout]" -map "0:a?" \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -c:a aac -b:a 192k -ar 48000 -ac 2 \
      -movflags +faststart \
      "$OUTPUT"
  else
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$INPUT" -i "$FX" \
      -filter_complex "$FC" \
      -map "[vout]" -an \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -movflags +faststart \
      "$OUTPUT"
  fi
}

ff_auto_cut_overlay() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1
  ff__need awk || return 1

  local INPUT="${1:-}"
  local T="${2:-}"
  local START="${3:-}"
  local DUR="${4:-1.0}"
  local MODE="${5:-luma}"
  local OUTPUT="${6:-}"

  [[ -n "$INPUT" && -f "$INPUT" && -n "$T" && -f "$T" && -n "$START" ]] || { print -u2 "Usage: ff_auto_cut_overlay <input.mp4> <matte.mov> <start> [dur] [luma|alpha] [out.mp4]"; return 1; }
  [[ -n "$OUTPUT" ]] || OUTPUT="${INPUT%.*}-auto_cut_${MODE}-${START//[:.]/_}-${DUR}.mp4"

  local total
  total="$(ff__duration "$INPUT")"
  [[ -n "$total" ]] || { print -u2 "Konnte Videodauer nicht ermitteln."; return 1; }

  local a_start
  a_start="$(awk -v s="$START" -v d="$DUR" 'BEGIN{v=s-d; if(v<0)v=0; printf "%.6f", v}')"
  local a_end="$START"
  local b_start="$START"
  local b_end
  b_end="$(awk -v s="$START" -v d="$DUR" 'BEGIN{printf "%.6f", s+d}')"

  awk "BEGIN{exit !($b_end <= $total)}" || { print -u2 "START+DUR überschreitet Videolänge"; return 1; }

  local map_audio=0
  ff__has_audio "$INPUT" && map_audio=1

  local FC
  if [[ "$MODE" == "alpha" ]]; then
    FC="\
[0:v]setpts=PTS-STARTPTS[v0]; \
[1:v]trim=0:${DUR},setpts=PTS-STARTPTS,format=rgba[tr]; \
[tr]alphaextract,format=gray[mask]; \
[v0]split=4[vpre][va][vb][vpost]; \
[vpre]trim=0:${a_start},setpts=PTS-STARTPTS[vpre0]; \
[va]trim=${a_start}:${a_end},setpts=PTS-STARTPTS[va0]; \
[vb]trim=${b_start}:${b_end},setpts=PTS-STARTPTS[vb0]; \
[vpost]trim=${b_end},setpts=PTS-STARTPTS[vpost0]; \
[va0][vb0][mask]maskedmerge[vtr]; \
[vpre0][vtr][vpost0]concat=n=3:v=1:a=0[vout]"
  else
    FC="\
[0:v]setpts=PTS-STARTPTS[v0]; \
[1:v]trim=0:${DUR},setpts=PTS-STARTPTS,format=rgba[tr]; \
[tr]format=gray,eq=contrast=1.0:brightness=0.0[mask]; \
[v0]split=4[vpre][va][vb][vpost]; \
[vpre]trim=0:${a_start},setpts=PTS-STARTPTS[vpre0]; \
[va]trim=${a_start}:${a_end},setpts=PTS-STARTPTS[va0]; \
[vb]trim=${b_start}:${b_end},setpts=PTS-STARTPTS[vb0]; \
[vpost]trim=${b_end},setpts=PTS-STARTPTS[vpost0]; \
[va0][vb0][mask]maskedmerge[vtr]; \
[vpre0][vtr][vpost0]concat=n=3:v=1:a=0[vout]"
  fi

  if (( map_audio )); then
    local AC
    AC="\
[0:a]asplit=4[apre][aa][ab][apost]; \
[apre]atrim=0:${a_start},asetpts=PTS-STARTPTS[apre0]; \
[aa]atrim=${a_start}:${a_end},asetpts=PTS-STARTPTS[aa0]; \
[ab]atrim=${b_start}:${b_end},asetpts=PTS-STARTPTS[ab0]; \
[apost]atrim=${b_end},asetpts=PTS-STARTPTS[apost0]; \
[aa0][ab0]acrossfade=d=${DUR}:c1=tri:c2=tri[atr]; \
[apre0][atr][apost0]concat=n=3:v=0:a=1[aout]"

    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$INPUT" -i "$T" \
      -filter_complex "$FC; $AC" \
      -map "[vout]" -map "[aout]" \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -c:a aac -b:a 192k -ar 48000 -ac 2 \
      -movflags +faststart \
      "$OUTPUT"
  else
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$INPUT" -i "$T" \
      -filter_complex "$FC" \
      -map "[vout]" -an \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -movflags +faststart \
      "$OUTPUT"
  fi
}

ff_reframe() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1

  local IN="" OUT="" DIR=""
  local MODE="blur"              # crop | fit | blur
  local TW="1080" TH="1920"      # target width/height
  local XSHIFT="0" YSHIFT="0"    # px shift after crop (positive: right/down)
  local BLUR="25"                # blur sigma for blur-mode
  local CRF="18" PRESET="medium"
  local NOAUDIO=0                # 1 => kein Audio mappen/encoden

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)     IN="${2:-}"; shift 2 ;;
      --out)    OUT="${2:-}"; shift 2 ;;
      --dir)    DIR="${2:-}"; shift 2 ;;
      --mode)   MODE="${2:-blur}"; shift 2 ;;
      --w)      TW="${2:-1080}"; shift 2 ;;
      --h)      TH="${2:-1920}"; shift 2 ;;
      --x)      XSHIFT="${2:-0}"; shift 2 ;;
      --y)      YSHIFT="${2:-0}"; shift 2 ;;
      --blur)   BLUR="${2:-25}"; shift 2 ;;
      --crf)    CRF="${2:-18}"; shift 2 ;;
      --preset) PRESET="${2:-medium}"; shift 2 ;;
      --noaudio) NOAUDIO=1; shift ;;
      --help|-h)
        cat <<'EOF'
ff_reframe
==========
Video auf neue Auflösung reframen (crop/fit/blur).

USAGE (Single):
  ff_reframe --in input.mp4 [--out out.mp4] [--mode crop|fit|blur] [--w 1080] [--h 1920] [--x 0] [--y 0] [--blur 25] [--crf 18] [--preset medium] [--noaudio]

USAGE (Batch):
  ff_reframe --dir /pfad/zum/ordner [--mode blur] [--w 1080] [--h 1920] [--blur 25] [--crf 18] [--preset medium] [--noaudio]
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

MODE:
  crop : Füllt Zielauflösung ohne Balken (skalieren + crop), shift via --x/--y (px)
  fit  : Maximale Bildfläche ohne Verlust (skalieren + pad), shift wirkt nicht
  blur : Hintergrund "blurfill" (bg: scale+crop+blur, fg: scale), shift via --x/--y auf den Crop

SHIFT:
  --x >0 verschiebt Crop nach rechts (links mehr abgeschnitten)
  --x <0 verschiebt Crop nach links  (rechts mehr abgeschnitten)
  --y >0 verschiebt Crop nach unten (oben mehr abgeschnitten)
  --y <0 verschiebt Crop nach oben  (unten mehr abgeschnitten)

AUDIO:
  --noaudio : Audio wird unabhängig vom Input immer entfernt (-an)

NOTES:
  - Metadaten (Tags, Kapitel) werden übernommen.
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  # In ffmpeg-Filtergraphs trennt ',' Filter. Kommas in Expressions müssen escaped werden: '\,'
  local XEXPR="max(0\\,min(iw-${TW}\\,(iw-${TW})/2+${XSHIFT}))"
  local YEXPR="max(0\\,min(ih-${TH}\\,(ih-${TH})/2+${YSHIFT}))"

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }

    local map_audio=0
    if (( NOAUDIO )); then
      map_audio=0
    else
      ff__has_audio "$_in" && map_audio=1
    fi

    case "$MODE" in
      crop)
        if (( map_audio )); then
          ffmpeg -y -hide_banner -loglevel error -stats \
            -i "$_in" \
            -map_metadata 0 -map_chapters 0 \
            -vf "scale=${TW}:${TH}:force_original_aspect_ratio=increase,crop=${TW}:${TH}:${XEXPR}:${YEXPR},setsar=1,format=yuv420p" \
            -map 0:v:0 -map "0:a?" \
            -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
            -c:a aac -b:a 192k -ar 48000 -ac 2 \
            -movflags +faststart \
            "$_out"
        else
          ffmpeg -y -hide_banner -loglevel error -stats \
            -i "$_in" \
            -map_metadata 0 -map_chapters 0 \
            -vf "scale=${TW}:${TH}:force_original_aspect_ratio=increase,crop=${TW}:${TH}:${XEXPR}:${YEXPR},setsar=1,format=yuv420p" \
            -map 0:v:0 -an \
            -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
            -movflags +faststart \
            "$_out"
        fi
        ;;
      fit)
        if (( map_audio )); then
          ffmpeg -y -hide_banner -loglevel error -stats \
            -i "$_in" \
            -map_metadata 0 -map_chapters 0 \
            -vf "scale=${TW}:${TH}:force_original_aspect_ratio=decrease,pad=${TW}:${TH}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p" \
            -map 0:v:0 -map "0:a?" \
            -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
            -c:a aac -b:a 192k -ar 48000 -ac 2 \
            -movflags +faststart \
            "$_out"
        else
          ffmpeg -y -hide_banner -loglevel error -stats \
            -i "$_in" \
            -map_metadata 0 -map_chapters 0 \
            -vf "scale=${TW}:${TH}:force_original_aspect_ratio=decrease,pad=${TW}:${TH}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p" \
            -map 0:v:0 -an \
            -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
            -movflags +faststart \
            "$_out"
        fi
        ;;
      blur)
        if (( map_audio )); then
          ffmpeg -y -hide_banner -loglevel error -stats \
            -i "$_in" \
            -map_metadata 0 -map_chapters 0 \
            -filter_complex "\
              [0:v]scale=${TW}:${TH}:force_original_aspect_ratio=increase,crop=${TW}:${TH}:${XEXPR}:${YEXPR},gblur=sigma=${BLUR}[bg]; \
              [0:v]scale=${TW}:${TH}:force_original_aspect_ratio=decrease[fg]; \
              [bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]" \
            -map "[v]" -map "0:a?" \
            -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
            -c:a aac -b:a 192k -ar 48000 -ac 2 \
            -movflags +faststart \
            "$_out"
        else
          ffmpeg -y -hide_banner -loglevel error -stats \
            -i "$_in" \
            -map_metadata 0 -map_chapters 0 \
            -filter_complex "\
              [0:v]scale=${TW}:${TH}:force_original_aspect_ratio=increase,crop=${TW}:${TH}:${XEXPR}:${YEXPR},gblur=sigma=${BLUR}[bg]; \
              [0:v]scale=${TW}:${TH}:force_original_aspect_ratio=decrease[fg]; \
              [bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]" \
            -map "[v]" -an \
            -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
            -movflags +faststart \
            "$_out"
        fi
        ;;
      *)
        print -u2 "MODE ungültig: $MODE (crop|fit|blur)"
        return 1
        ;;
    esac
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}.mp4"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_reframe --in <input.mp4> ...  (oder: --dir /pfad)"; return 1; }
  [[ -n "$OUT" ]] || OUT="${IN%.*}-reframe-${MODE}-${TW}x${TH}-x${XSHIFT}-y${YSHIFT}.mp4"
  _one "$IN" "$OUT"
}

ff_mov_transition() {
  ff__strict
  ff__need ffmpeg || return 1
  ff__need ffprobe || return 1
  ff__need awk || return 1

  local A="${1:-}"
  local B="${2:-}"
  local T="${3:-}"
  local START="${4:-}"
  local DUR="${5:-1.0}"
  local MODE="${6:-alpha}"
  local OUTPUT="${7:-}"

  [[ -n "$A" && -f "$A" && -n "$B" && -f "$B" && -n "$T" && -f "$T" && -n "$START" ]] || { print -u2 "Usage: ff_mov_transition <A.mp4> <B.mp4> <transition.mov> <start> [dur] [alpha|luma] [out.mp4]"; return 1; }
  [[ -n "$OUTPUT" ]] || OUTPUT="${A%.*}-to-$(basename -- "${B%.*}")-movtrans-${MODE}-${START//[:.]/_}-${DUR}.mp4"

  local map_a=0 map_b=0
  ff__has_audio "$A" && map_a=1
  ff__has_audio "$B" && map_b=1

  local FC
  if [[ "$MODE" == "alpha" ]]; then
    FC="\
[0:v]setpts=PTS-STARTPTS[vA0]; \
[1:v]setpts=PTS-STARTPTS[vB0]; \
[2:v]trim=0:${DUR},setpts=PTS-STARTPTS,format=rgba[tr0]; \
[vA0][tr0]scale2ref[vA][tr]; \
[vB0][vA]scale2ref[vB][vA2]; \
[tr]alphaextract,format=gray[mask]; \
[vA2]split=2[a_pre][a_for]; \
[vB]split=2[b_for][b_post]; \
[a_for]trim=${START}:${START}+${DUR},setpts=PTS-STARTPTS[a_tr]; \
[b_for]trim=${START}:${START}+${DUR},setpts=PTS-STARTPTS[b_tr]; \
[a_pre]trim=0:${START},setpts=PTS-STARTPTS[a0]; \
[b_post]trim=${START}+${DUR},setpts=PTS-STARTPTS[b2]; \
[a_tr][b_tr][mask]maskedmerge[v_tr]; \
[a0][v_tr][b2]concat=n=3:v=1:a=0[vout]"
  else
    FC="\
[0:v]setpts=PTS-STARTPTS[vA0]; \
[1:v]setpts=PTS-STARTPTS[vB0]; \
[2:v]trim=0:${DUR},setpts=PTS-STARTPTS,format=rgba[tr0]; \
[vA0][tr0]scale2ref[vA][tr]; \
[vB0][vA]scale2ref[vB][vA2]; \
[tr]format=gray,eq=contrast=1.0:brightness=0.0[mask]; \
[vA2]split=2[a_pre][a_for]; \
[vB]split=2[b_for][b_post]; \
[a_for]trim=${START}:${START}+${DUR},setpts=PTS-STARTPTS[a_tr]; \
[b_for]trim=${START}:${START}+${DUR},setpts=PTS-STARTPTS[b_tr]; \
[a_pre]trim=0:${START},setpts=PTS-STARTPTS[a0]; \
[b_post]trim=${START}+${DUR},setpts=PTS-STARTPTS[b2]; \
[a_tr][b_tr][mask]maskedmerge[v_tr]; \
[a0][v_tr][b2]concat=n=3:v=1:a=0[vout]"
  fi

  if (( map_a || map_b )); then
    local AC
    if (( map_a )); then
      AC="[0:a]atrim=0:${START}+${DUR},asetpts=PTS-STARTPTS[aA]"
    else
      AC="anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:${START}+${DUR},asetpts=PTS-STARTPTS[aA]"
    fi
    if (( map_b )); then
      AC="${AC};[1:a]atrim=${START}:${START}+99999,asetpts=PTS-STARTPTS[aB]"
    else
      AC="${AC};anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:99999,asetpts=PTS-STARTPTS[aB]"
    fi
    AC="${AC};[aA][aB]acrossfade=d=${DUR}:c1=tri:c2=tri[aout]"

    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$A" -i "$B" -i "$T" \
      -filter_complex "$FC; $AC" \
      -map "[vout]" -map "[aout]" \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -c:a aac -b:a 192k -ar 48000 -ac 2 \
      -movflags +faststart \
      "$OUTPUT"
  else
    ffmpeg -y -hide_banner -loglevel error -stats \
      -i "$A" -i "$B" -i "$T" \
      -filter_complex "$FC" \
      -map "[vout]" -an \
      -c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
      -movflags +faststart \
      "$OUTPUT"
  fi
}

ff_info() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffprobe || return 1

  local IN="" DIR=""

  # backward compat: positional arg
  if [[ $# -gt 0 && "${1}" != --* ]]; then
    IN="$1"; shift
  fi
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)  IN="${2:-}"; shift 2 ;;
      --dir) DIR="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_info
=======
Kurzinfo: Dauer, Codec, Profil, Auflösung, FPS, PixFmt (via ffprobe).

USAGE (Single):
  ff_info <file>
  ff_info --in file

USAGE (Batch):
  ff_info --dir /pfad/zum/ordner
  -> zeigt Info für alle Medien-Dateien im Ordner
EOF
        return 0
        ;;
      *) print -u2 "Unbekannter Parameter: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    ffprobe -hide_banner -v error \
      -select_streams v:0 \
      -show_entries format=duration:stream=codec_name,profile,width,height,avg_frame_rate,r_frame_rate,pix_fmt \
      -of default=nw=1 "$_in"
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( \
      -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \
      -o -iname "*.mp3" -o -iname "*.wav" -o -iname "*.flac" -o -iname "*.m4a" -o -iname "*.ogg" \
    \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Medien-Dateien in: $DIR"; return 1; }
    local f_abs
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      print -r -- "=== ${f_abs:t} ==="
      _one "$f_abs" || return $?
      print ""
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -f "$IN" ]] || { print -u2 "Usage: ff_info <file>  (oder: --dir /pfad)"; return 1; }
  _one "$IN"
}

ff_burn_subs() {
  ff__strict

  local IN="" SUBS="" OUT=""
  local BG_COLOR="black" BG_IMG=""
  local USE_COVER="0" COVER_MODE="crop"
  local W="1920" H="1080" FPS="30"
  local CRF="18" PRESET="medium"
  local FONTDIR=""
  local A_CODEC="aac" A_BR="192k" A_SR="48000"

  local usage
  usage() {
    cat <<'EOF'
ff_burn_subs
============
Erstellt ein fertiges MP4 aus:
- Video + Subs (SRT/ASS) -> Subs werden eingebrannt
- Audio + Subs (SRT/ASS) -> Hintergrund (Farbe/Bild/Cover) + Subs

USAGE
-----
ff_burn_subs --in input.(mp4|mkv|mp3|m4a|wav|flac) --subs subs.(srt|ass) --out out.mp4
  [--bg-color black] [--bg-img bg.jpg]
  [--use-cover] [--cover-mode crop|fit]
  [--w 1920] [--h 1080] [--fps 30]
  [--crf 18] [--preset medium]
  [--fontdir /path/to/fonts]
  [--abr 192k] [--sr 48000]

PRIORITÄT (Audio-only)
----------------------
1) --bg-img (wenn gesetzt)
2) --use-cover (wenn Cover vorhanden)
3) --bg-color (Fallback)

BEISPIELE
---------
# Video + SRT
ff_burn_subs --in clip.mp4 --subs clip.srt --out clip_subbed.mp4

# Audio + ASS, Cover als Hintergrund (wenn vorhanden)
ff_burn_subs --in song.mp3 --subs song.ass --out song_subbed.mp4 --use-cover --cover-mode crop

# Audio + SRT, Bildhintergrund
ff_burn_subs --in podcast.mp3 --subs podcast.srt --out podcast.mp4 --bg-img bg.jpg --w 1920 --h 1080

# Audio + SRT, Farb-Hintergrund
ff_burn_subs --in podcast.mp3 --subs podcast.srt --out podcast.mp4 --bg-color "#0b0f14"
EOF
  }

  command -v ffmpeg >/dev/null 2>&1 || { print -u2 "Fehlt: ffmpeg"; return 1; }
  command -v ffprobe >/dev/null 2>&1 || { print -u2 "Fehlt: ffprobe"; return 1; }

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in) IN="${2:-}"; shift 2 ;;
      --subs) SUBS="${2:-}"; shift 2 ;;
      --out) OUT="${2:-}"; shift 2 ;;
      --bg-color) BG_COLOR="${2:-}"; shift 2 ;;
      --bg-img) BG_IMG="${2:-}"; shift 2 ;;
      --use-cover) USE_COVER="1"; shift 1 ;;
      --cover-mode) COVER_MODE="${2:-}"; shift 2 ;;
      --w) W="${2:-}"; shift 2 ;;
      --h) H="${2:-}"; shift 2 ;;
      --fps) FPS="${2:-}"; shift 2 ;;
      --crf) CRF="${2:-}"; shift 2 ;;
      --preset) PRESET="${2:-}"; shift 2 ;;
      --fontdir) FONTDIR="${2:-}"; shift 2 ;;
      --abr) A_BR="${2:-}"; shift 2 ;;
      --sr) A_SR="${2:-}"; shift 2 ;;
      --help|-h) usage; return 0 ;;
      *) print -u2 "Unbekannt: $1"; usage; return 1 ;;
    esac
  done

  [[ -n "$IN" && -n "$SUBS" && -n "$OUT" ]] || { usage; return 1; }
  [[ -f "$IN" ]] || { print -u2 "Input nicht gefunden: $IN"; return 1; }
  [[ -f "$SUBS" ]] || { print -u2 "Subs nicht gefunden: $SUBS"; return 1; }
  [[ -z "$BG_IMG" || -f "$BG_IMG" ]] || { print -u2 "BG-Image nicht gefunden: $BG_IMG"; return 1; }
  [[ "$COVER_MODE" == "crop" || "$COVER_MODE" == "fit" ]] || { print -u2 "--cover-mode muss crop oder fit sein"; return 1; }

  # Sub-Format bestimmen
  local subs_lc ext
  subs_lc="${SUBS:l}"
  ext="${subs_lc##*.}"
  if [[ "$ext" != "srt" && "$ext" != "ass" ]]; then
    print -u2 "ERROR: --subs muss .srt oder .ass sein"
    return 1
  fi

  # Video-Stream vorhanden?
  local has_video
  has_video="$(ffprobe -v error -select_streams v:0 -show_entries stream=index -of csv=p=0 "$IN" | head -n1 || true)"

  # Cover-Art (attached picture) vorhanden?
  # MP3/M4A haben oft: disposition.attached_pic=1 (als Video-Stream)
  local has_cover
  has_cover="$(ffprobe -v error -select_streams v \
    -show_entries stream=disposition:stream_tags \
    -of compact=p=0:nk=1 "$IN" | grep -E "attached_pic=1" | head -n1 || true)"

  # Pfade für Filter escapen
  local SUBS_ESC FONTDIR_ESC
  SUBS_ESC="${SUBS//\\/\\\\}"; SUBS_ESC="${SUBS_ESC//:/\\:}"; SUBS_ESC="${SUBS_ESC//\'/\\\'}"
  FONTDIR_ESC="${FONTDIR//\\/\\\\}"; FONTDIR_ESC="${FONTDIR_ESC//:/\\:}"; FONTDIR_ESC="${FONTDIR_ESC//\'/\\\'}"

  # Subtitle-Filter
  local SUB_FILTER=""
  if [[ "$ext" == "ass" ]]; then
    SUB_FILTER="ass='${SUBS_ESC}'"
  else
    if [[ -n "$FONTDIR" ]]; then
      SUB_FILTER="subtitles='${SUBS_ESC}':fontsdir='${FONTDIR_ESC}'"
    else
      SUB_FILTER="subtitles='${SUBS_ESC}'"
    fi
  fi

  # Helper: Cover scale mode
  local COVER_VF=""
  if [[ "$COVER_MODE" == "fit" ]]; then
    # letterbox: fit in frame + pad
    COVER_VF="scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2"
  else
    # crop fill
    COVER_VF="scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H}"
  fi

  # --- Fall A: echtes Video (nicht nur Cover) -> burn subs auf Video ---
  # Wenn Input "Video" nur Cover-Art ist, dann behandeln wir es als Audio-only.
  # Heuristik: hat Video-Stream und NICHT attached_pic=1
  local is_attached_pic_only="0"
  if [[ -n "$has_video" && -n "$has_cover" ]]; then
    # sehr wahrscheinlich: Video-Stream ist nur Cover
    is_attached_pic_only="1"
  fi

  if [[ -n "$has_video" && "$is_attached_pic_only" == "0" ]]; then
    ffmpeg -hide_banner -loglevel error -stats \
      -i "$IN" \
      -vf "$SUB_FILTER" \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -c:a aac -b:a "$A_BR" -ar "$A_SR" \
      -movflags +faststart \
      -y "$OUT"
    return $?
  fi

  # --- Fall B: Audio-only (oder Audio + Cover) -> Hintergrund wählen ---
  # Priorität: BG_IMG > use-cover > bg-color

  if [[ -n "$BG_IMG" ]]; then
    # BG Image
    ffmpeg -hide_banner -loglevel error -stats \
      -loop 1 -i "$BG_IMG" \
      -i "$IN" \
      -vf "${COVER_VF},fps=${FPS},format=yuv420p,${SUB_FILTER}" \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -c:a "$A_CODEC" -b:a "$A_BR" -ar "$A_SR" \
      -shortest -movflags +faststart \
      -y "$OUT"
    return $?
  fi

  if [[ "$USE_COVER" == "1" && -n "$has_cover" ]]; then
    # Cover aus Input: Map cover video stream + audio
    # Map: 0:v:0 (attached picture) + 0:a:0
    ffmpeg -hide_banner -loglevel error -stats \
      -i "$IN" \
      -map 0:v:0 -map 0:a:0 \
      -vf "${COVER_VF},fps=${FPS},format=yuv420p,${SUB_FILTER}" \
      -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
      -c:a "$A_CODEC" -b:a "$A_BR" -ar "$A_SR" \
      -shortest -movflags +faststart \
      -y "$OUT"
    return $?
  fi

  # BG Color fallback
  ffmpeg -hide_banner -loglevel error -stats \
    -f lavfi -i "color=c=${BG_COLOR}:s=${W}x${H}:r=${FPS}" \
    -i "$IN" \
    -map 0:v:0 -map 1:a:0 \
    -vf "${SUB_FILTER},format=yuv420p" \
    -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
    -c:a "$A_CODEC" -b:a "$A_BR" -ar "$A_SR" \
    -shortest -movflags +faststart \
    -y "$OUT"
}


ff_audio_norm() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist

  ff__strict

  local IN="" OUT="" DIR=""
  local I="-16" TP="-1.5" LRA="11"
  local ABR="192k" SR="48000"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)  IN="${2:-}"; shift 2 ;;
      --out) OUT="${2:-}"; shift 2 ;;
      --dir) DIR="${2:-}"; shift 2 ;;
      --i)   I="${2:-}"; shift 2 ;;
      --tp)  TP="${2:-}"; shift 2 ;;
      --lra) LRA="${2:-}"; shift 2 ;;
      --abr) ABR="${2:-}"; shift 2 ;;
      --sr)  SR="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_audio_norm
=============
Audio normalisieren per EBU R128 loudnorm.
Defaults: --i -16 --tp -1.5 --lra 11

USAGE (Single):
  ff_audio_norm --in "input.(mp4|mkv|mp3|wav|flac|m4a)" --out "output.(mp4|mkv|mp3|m4a)"

USAGE (Batch):
  ff_audio_norm --dir "/pfad/zum/ordner"
  -> erstellt "/pfad/zum/ordner/out" und normalisiert alle Dateien im Ordner
     (sicher für Leerzeichen und auch "!" im Dateinamen)

Optional:
  [--i -16] [--tp -1.5] [--lra 11] [--abr 192k] [--sr 48000]

BEHAVIOR:
- Metadaten (Tags) + Kapitel werden übernommen (map_metadata/map_chapters).
- MP3-Output: übernimmt vorhandenes Cover-Art (attached_pic), wenn vorhanden.
- Video-Container: Video wird kopiert (falls vorhanden), Audio normalisiert und neu encodiert.
EOF
        return 0 ;;
      *) print -u2 "Unbekannt: $1"; return 1 ;;
    esac
  done

  command -v ffmpeg  >/dev/null 2>&1 || { print -u2 "Fehlt: ffmpeg"; return 1; }
  command -v ffprobe >/dev/null 2>&1 || { print -u2 "Fehlt: ffprobe"; return 1; }

  local _norm_one
  _norm_one() {
    local _in="$1"
    local _out="$2"

    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }

    local out_lc ext
    out_lc="${_out:l}"
    ext="${out_lc##*.}"

    local has_video
    has_video="$(ffprobe -v error -select_streams v:0 -show_entries stream=index -of csv=p=0 "$_in" | head -n1 || true)"

    local cover_si=""
    cover_si="$(
      ffprobe -v error -select_streams v \
        -show_entries stream=index:stream_disposition=attached_pic \
        -of csv=p=0 "$_in" 2>/dev/null \
      | awk -F',' '$2==1 {print $1; exit}'
    )"

    if [[ "$ext" == "mp3" ]]; then
      if [[ -n "$cover_si" ]]; then
        ffmpeg -hide_banner -loglevel error -stats \
          -i "$_in" \
          -map_metadata 0 -map_chapters 0 \
          -map 0:a:0 -map 0:"$cover_si" \
          -af "loudnorm=I=${I}:TP=${TP}:LRA=${LRA}" \
          -c:a libmp3lame -b:a "$ABR" -ar "$SR" \
          -c:v copy -disposition:v:0 attached_pic \
          -id3v2_version 3 -write_id3v1 1 \
          -y "$_out"
        return $?
      fi

      ffmpeg -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -map 0:a:0 -vn \
        -af "loudnorm=I=${I}:TP=${TP}:LRA=${LRA}" \
        -c:a libmp3lame -b:a "$ABR" -ar "$SR" \
        -id3v2_version 3 -write_id3v1 1 \
        -y "$_out"
      return $?
    fi

    if [[ -n "$has_video" ]]; then
      ffmpeg -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -map 0:v:0 -map 0:a:0 \
        -c:v copy \
        -af "loudnorm=I=${I}:TP=${TP}:LRA=${LRA}" \
        -c:a aac -b:a "$ABR" -ar "$SR" \
        -movflags +faststart \
        -y "$_out"
    else
      ffmpeg -hide_banner -loglevel error -stats \
        -i "$_in" \
        -map_metadata 0 -map_chapters 0 \
        -map 0:a:0 -vn \
        -af "loudnorm=I=${I}:TP=${TP}:LRA=${LRA}" \
        -c:a aac -b:a "$ABR" -ar "$SR" \
        -movflags +faststart \
        -y "$_out"
    fi
  }

  # Batch-Modus
  if [[ -n "$DIR" ]]; then
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }

    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }

    # Dateien robust einsammeln (keine Pfad-/Subshell-Effekte)
    local -a files
    files=()
    local f
    while IFS= read -r -d '' f; do
      files+=("$f")
    done < <(find "$DIR" -maxdepth 1 -type f \( \
      -iname "*.mp3" -o -iname "*.wav" -o -iname "*.flac" -o -iname "*.m4a" -o -iname "*.mp4" -o -iname "*.mkv" \
    \) -print0)

    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Dateien in: $DIR"; return 1; }

    local f_abs base ext stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"

      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }

      base="${f_abs:t}"
      ext="${base##*.}"
      stem="${base%.*}"

      case "${ext:l}" in
        mp3|wav|flac|m4a) out="$OUTDIR/${stem}.mp3" ;;
        mp4|mkv)          out="$OUTDIR/${stem}.mp4" ;;
        *) print -u2 "Überspringe (unbekanntes Format): $f_abs"; continue ;;
      esac

      print -r -- "Normalisiere: $f_abs -> $out"
      _norm_one "$f_abs" "$out" || return $?
    done

    return 0
  fi

  # Single-Modus
  [[ -n "$IN" && -n "$OUT" ]] || { print -u2 "Usage: ff_audio_norm --in in --out out  (oder: --dir /pfad)"; return 1; }
  _norm_one "$IN" "$OUT"
}

# Sicherheitsnetz: falls du aus Gewohnheit "f_audio_norm" tippst
f_audio_norm() { ff_audio_norm "$@"; }

ff_webm_loop() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1

  local IN="" OUT="" DIR="" DUR="" START="0" FPS="30" W="1280" CRF="32"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)    IN="${2:-}"; shift 2 ;;
      --out)   OUT="${2:-}"; shift 2 ;;
      --dir)   DIR="${2:-}"; shift 2 ;;
      --dur)   DUR="${2:-}"; shift 2 ;;
      --start) START="${2:-}"; shift 2 ;;
      --fps)   FPS="${2:-}"; shift 2 ;;
      --w)     W="${2:-}"; shift 2 ;;
      --crf)   CRF="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_webm_loop
============
Erstellt ein VP9-WebM Loop-Segment aus einem Video.

USAGE (Single):
  ff_webm_loop --in in.mp4 --out loop.webm --dur 4 [--start 0] [--fps 30] [--w 1280] [--crf 32]

USAGE (Batch):
  ff_webm_loop --dir /pfad/zum/ordner --dur 4 [--start 0] [--fps 30] [--w 1280] [--crf 32]
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

NOTES:
  - --dur ist auch im Batch-Modus erforderlich (wird für alle Dateien verwendet).
EOF
        return 0 ;;
      *) print -u2 "Unbekannt: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    ffmpeg -hide_banner -loglevel error -stats \
      -ss "$START" -t "$DUR" -i "$_in" \
      -vf "fps=${FPS},scale=${W}:-2:flags=lanczos,format=yuv420p" \
      -c:v libvpx-vp9 -crf "$CRF" -b:v 0 \
      -an -y "$_out"
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -n "$DUR" ]] || { print -u2 "Batch-Modus benötigt --dur"; return 1; }
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}.webm"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -n "$OUT" && -n "$DUR" ]] || { print -u2 "Usage: ff_webm_loop --in in.mp4 --out loop.webm --dur 4  (oder: --dir /pfad --dur 4)"; return 1; }
  [[ -f "$IN" ]] || { print -u2 "Nicht gefunden: $IN"; return 1; }
  _one "$IN" "$OUT"
}


ff_gif() {
  emulate -L zsh
  setopt localoptions no_sh_word_split no_glob nobanghist
  ff__strict
  ff__need ffmpeg || return 1

  local IN="" OUT="" DIR="" START="0" DUR="" FPS="15" W="480"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --in)    IN="${2:-}"; shift 2 ;;
      --out)   OUT="${2:-}"; shift 2 ;;
      --dir)   DIR="${2:-}"; shift 2 ;;
      --start) START="${2:-}"; shift 2 ;;
      --dur)   DUR="${2:-}"; shift 2 ;;
      --fps)   FPS="${2:-}"; shift 2 ;;
      --w)     W="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_gif
======
Erstellt ein animiertes GIF aus einem Video-Ausschnitt.

USAGE (Single):
  ff_gif --in in.mp4 --out out.gif [--start 0] [--dur 3] [--fps 15] [--w 480]

USAGE (Batch):
  ff_gif --dir /pfad/zum/ordner --dur 3 [--start 0] [--fps 15] [--w 480]
  -> erstellt "<ordner>/out" und verarbeitet alle Video-Dateien im Ordner

NOTES:
  - --dur ist auch im Batch-Modus erforderlich (wird für alle Dateien verwendet).
EOF
        return 0 ;;
      *) print -u2 "Unbekannt: $1"; return 1 ;;
    esac
  done

  local _one
  _one() {
    local _in="$1" _out="$2"
    [[ -f "$_in" ]] || { print -u2 "Nicht gefunden: $_in"; return 1; }
    ffmpeg -hide_banner -loglevel error -stats \
      -ss "$START" -t "$DUR" -i "$_in" \
      -vf "fps=${FPS},scale=${W}:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
      -y "$_out"
  }

  # Batch
  if [[ -n "$DIR" ]]; then
    [[ -n "$DUR" ]] || { print -u2 "Batch-Modus benötigt --dur"; return 1; }
    [[ -d "$DIR" ]] || { print -u2 "Ordner nicht gefunden: $DIR"; return 1; }
    local OUTDIR="$DIR/out"
    mkdir -p "$OUTDIR" || { print -u2 "Kann out-Ordner nicht erstellen: $OUTDIR"; return 1; }
    local -a files; files=()
    local f
    while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.mov" -o -iname "*.webm" -o -iname "*.avi" \) -print0)
    (( ${#files[@]} > 0 )) || { print -u2 "Keine passenden Video-Dateien in: $DIR"; return 1; }
    local f_abs base stem out
    for f in "${files[@]}"; do
      f_abs="$(realpath -- "$f" 2>/dev/null || readlink -f -- "$f" 2>/dev/null || print -r -- "$f")"
      [[ -f "$f_abs" ]] || { print -u2 "Nicht gefunden: $f_abs"; return 1; }
      base="${f_abs:t}"; stem="${base%.*}"
      out="$OUTDIR/${stem}.gif"
      print -r -- "Verarbeite: $f_abs -> $out"
      _one "$f_abs" "$out" || return $?
    done
    return 0
  fi

  # Single
  [[ -n "$IN" && -n "$OUT" && -n "$DUR" ]] || { print -u2 "Usage: ff_gif --in in.mp4 --out out.gif --dur 3  (oder: --dir /pfad --dur 3)"; return 1; }
  [[ -f "$IN" ]] || { print -u2 "Nicht gefunden: $IN"; return 1; }
  _one "$IN" "$OUT"
}


ff_menu() {
  ff__strict
  ff__need ffmpeg || return 1

  local VIDEO="" AUDIO="" LIST="" OUT="" TOOL=""
  local -a passthrough=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --video|-v) VIDEO="${2:-}"; shift 2 ;;
      --audio|-a) AUDIO="${2:-}"; shift 2 ;;
      --list|-l)  LIST="${2:-}"; shift 2 ;;
      --out|-o)   OUT="${2:-}"; shift 2 ;;
      --tool|-t)  TOOL="${2:-}"; shift 2 ;;
      --help|-h)
        cat <<'EOF'
ff_menu
USAGE:
  ff_menu [--video in.mp4] [--audio song.wav] [--list list.txt] [--out out.mp4] [--tool ff_xxx] [-- <tool-args...>]

BEISPIELE:
  ff_menu --video in.mp4
  ff_menu --video in.mp4 --audio song.wav --out out.mp4 --tool ff_audio_loop_video
  ff_menu --list list.txt --out concat.mp4 --tool ff_concat_list -- 18 medium
  ff_menu --video in.mp4 --tool ff_reframe -- --mode blur --w 1080 --h 1920 --x 200 --out out.mp4

HINWEIS:
  Alles nach "--" wird 1:1 an das gewählte Tool weitergereicht.
EOF
        return 0
        ;;
      --)
        shift
        passthrough=("$@")
        break
        ;;
      *)
        print -u2 "Unbekannter Parameter: $1"
        return 1
        ;;
    esac
  done

  [[ -n "$VIDEO" ]] && [[ -f "$VIDEO" ]] || [[ -z "$VIDEO" ]] || { print -u2 "Video nicht gefunden: $VIDEO"; return 1; }
  [[ -n "$AUDIO" ]] && [[ -f "$AUDIO" ]] || [[ -z "$AUDIO" ]] || { print -u2 "Audio nicht gefunden: $AUDIO"; return 1; }
  [[ -n "$LIST"  ]] && [[ -f "$LIST"  ]] || [[ -z "$LIST"  ]] || { print -u2 "List nicht gefunden: $LIST"; return 1; }

  # Defaults
  if [[ -z "$OUT" ]]; then
    if [[ -n "$VIDEO" ]]; then
      OUT="${VIDEO%.*}-menu.mp4"
    elif [[ -n "$LIST" ]]; then
      OUT="concat-menu.mp4"
    else
      OUT="out.mp4"
    fi
  fi

  # Tool-Validierung falls vorgegeben
  if [[ -n "$TOOL" && ! $+functions[$TOOL] ]]; then
    print -u2 "Tool nicht gefunden: $TOOL"
    return 1
  fi

  # Simple Auswahlmenü (numbers)
  local -a items
  local choice=""

  # Wenn Tool explizit vorgegeben, direkt ausführen
  if [[ -n "$TOOL" ]]; then
    choice="$TOOL"
  else
    items=(
      "ff_help"
      "ff_reframe"
      "ff_fades"
      "ff_mov_overlay"
      "ff_color_blend"
      "ff_audio_loop_video"
      "ff_concat_list"
      "ff_rev"
    )

    print -r -- ""
    print -r -- "FFmpeg Menu"
    print -r -- "  VIDEO: ${VIDEO:-<none>}"
    print -r -- "  AUDIO: ${AUDIO:-<none>}"
    print -r -- "  LIST : ${LIST:-<none>}"
    print -r -- "  OUT  : ${OUT}"
    print -r -- ""

    local i=1
    for i in {1..${#items[@]}}; do
      print -r -- "  $i) ${items[$i]}"
    done
    print -r -- ""
    print -n -- "Auswahl (1-${#items[@]}): "
    read -r choice

    [[ "$choice" == <-> ]] || { print -u2 "Ungültige Auswahl."; return 1; }
    (( choice >= 1 && choice <= ${#items[@]} )) || { print -u2 "Ungültige Auswahl."; return 1; }
    choice="${items[$choice]}"
  fi

  # Dispatch
  case "$choice" in
    ff_help)
      if [[ -n "${passthrough[1]:-}" ]]; then
        ff_help "${passthrough[@]}"
      else
        ff_help
      fi
      ;;

    ff_concat_list)
      [[ -n "$LIST" ]] || { print -u2 "ff_concat_list braucht --list <list.txt>"; return 1; }
      # passthrough: [crf preset] optional
      ff_concat_list "$LIST" "$OUT" "${passthrough[@]}"
      ;;

    ff_audio_loop_video)
      [[ -n "$VIDEO" && -n "$AUDIO" ]] || { print -u2 "ff_audio_loop_video braucht --video und --audio"; return 1; }
      ff_audio_loop_video "$VIDEO" "$AUDIO" "$OUT"
      ;;

    ff_reframe)
      [[ -n "$VIDEO" ]] || { print -u2 "ff_reframe braucht --video"; return 1; }
      ff_reframe --in "$VIDEO" --out "$OUT" "${passthrough[@]}"
      ;;

    ff_fades)
      [[ -n "$VIDEO" ]] || { print -u2 "ff_fades braucht --video"; return 1; }
      # passthrough: [fade_time] [both|in|out]
      ff_fades "$VIDEO" "${passthrough[@]}"
      ;;

    ff_mov_overlay)
      [[ -n "$VIDEO" ]] || { print -u2 "ff_mov_overlay braucht --video"; return 1; }
      # passthrough muss mindestens enthalten: fx start (und optional dur mode opacity out)
      (( ${#passthrough[@]} >= 2 )) || { print -u2 "Usage via menu: --tool ff_mov_overlay -- <fx.mov> <start> [dur] [mode] [opacity] [out]"; return 1; }
      # Wenn kein out übergeben: nimm OUT
      if (( ${#passthrough[@]} >= 6 )); then
        ff_mov_overlay "$VIDEO" "${passthrough[@]}"
      else
        ff_mov_overlay "$VIDEO" "${passthrough[@]}" "$OUT"
      fi
      ;;

    ff_color_blend)
      [[ -n "$VIDEO" ]] || { print -u2 "ff_color_blend braucht --video"; return 1; }
      # passthrough: start duration [color] [fade] [alpha]
      (( ${#passthrough[@]} >= 2 )) || { print -u2 "Usage via menu: --tool ff_color_blend -- <start> <duration> [color] [fade] [alpha]"; return 1; }
      ff_color_blend "$VIDEO" "${passthrough[@]}"
      ;;

    ff_rev)
      [[ -n "$VIDEO" ]] || { print -u2 "ff_rev braucht --video"; return 1; }
      ff_rev "$VIDEO"
      ;;

    *)
      print -u2 "Unbekannt/unsupported im Menü: $choice"
      return 1
      ;;
  esac
}
