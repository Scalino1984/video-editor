# Timing SSOT & Edit Flow

Architecture documentation for word-level timing in Karaoke Sub Tool.

## Overview

The **Word Timeline** system provides a Single Source of Truth (SSOT) for word-level
timing data derived from audio alignment (Voxtral/Whisper). Segment start/end times
are **derived** from underlying `WordToken` timestamps, ensuring that text edits
(moving words between segments) maintain audio synchronization.

## Core Concepts

### Data Model

```
AlignmentRun (one per alignment pass)
├── run_id, track_id, window_start_ms, window_end_ms
├── model_provider, model_version, params_hash
├── quality_metrics: coverage, avg_confidence, warnings
├── WordToken[] (ordered by idx_in_run)
│   ├── word_id (stable within run)
│   ├── surface (display form), norm (lowercase, no punctuation)
│   ├── start_ms, end_ms, confidence
│   └── SyllableToken[] (optional, for fine-grained karaoke)
│       ├── syll_id, syll_index, text
│       └── start_ms, end_ms, confidence
└── SegmentWordMap[]
    ├── segment_id → ordered word_id list
    ├── map_version, updated_at, author (system/user)
    └── Derived: segment.start = min(word.start_ms), segment.end = max(word.end_ms)
```

### Invariants

1. `WordToken.start_ms < end_ms`, monotonic by `idx_in_run`
2. Segment times = min/max of mapped WordTokens (+ gap/clamp policy)
3. No duplicate `word_id` across segment mappings within a group
4. Syllable durations sum to word duration (±1ms rounding)
5. No negative times; minimum segment duration enforced (200ms default)

## Edit Flow

When a user changes segment text (e.g., moves "Regeln" from segment A to B):

```
User Edit → Tokenize new texts → Match tokens to WordTimeline
                                         │
                            ┌─────────────┴─────────────┐
                            ▼                           ▼
                     All tokens match?            Missing/new tokens?
                            │                           │
                            ▼                           ▼
                    REMAP ONLY                  RE-ALIGN LOCAL
                    (fast path)                 (alignment needed)
                            │                           │
                            ▼                           ▼
                Update SegmentWordMap         Compute window →
                Derive new segment times      Call Voxtral/Whisper →
                Rebuild word arrays           New AlignmentRun →
                Export ASS                    Rebind segments →
                                              Export ASS
```

### Remap Only (Fast Path)

When words are **only redistributed** between segments:
- WordTimeline stays unchanged (no re-alignment)
- Only `SegmentWordMap` ownership changes
- Segment times are re-derived from mapped words
- ASS export regenerated with correct karaoke timing

### Re-Align Local (Slow Path)

When words are **added/removed** or matching confidence is low:
- A local time window is computed (affected segments ± padding)
- New alignment pass runs only in that window
- New `AlignmentRun` created; old words replaced in window
- Segments re-bound to new word tokens

## Persistence

Files stored per job in `data/output/{job_id}/`:

| File | Purpose |
|------|---------|
| `segments.json` | Segment data (start, end, text, words) — remains SSOT for UI |
| `word_timeline.json` | WordTimeline with AlignmentRuns and SegmentWordMaps |

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/jobs/{id}/word-timeline/build` | POST | Build timeline from current segments |
| `/api/jobs/{id}/word-timeline` | GET | Retrieve word timeline + metrics |
| `/api/jobs/{id}/segments/remap-words` | POST | Remap words between segments |

### Remap Request

```json
POST /api/jobs/{id}/segments/remap-words
{
  "0": "Nur Meine",
  "1": "Regeln Bleiben. Die"
}
```

### Remap Response

```json
{
  "action": "remap",
  "confidence": 1.0,
  "needs_review": false,
  "metrics": {
    "coverage_pct": 1.0,
    "avg_confidence": 0.9,
    "word_count": 5,
    "syllable_count": 0,
    "segment_count": 2
  }
}
```

## ASS Export

Karaoke tags support two granularity levels:

1. **Word-level** (default): Each word gets a `\kf` tag with duration in centiseconds
2. **Syllable-level** (optional): Each syllable gets its own `\kf` tag for smooth fill

### Gap/Clamp Policy

- Minimum gap between segments: 20–120ms (configurable)
- Minimum segment duration: 200ms
- No negative times
- No overlapping segments within a group

## Observability

Metrics tracked per operation:

| Metric | Description |
|--------|-------------|
| `coverage_pct` | % of words with confidence > 0.5 |
| `avg_confidence` | Mean word confidence score |
| `word_count` | Total words in timeline |
| `syllable_count` | Total syllables (if generated) |
| `remap_only` | Whether edit was remap-only |
| `realign_needed` | Whether re-alignment was triggered |

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `gap_min_ms` | 20 | Minimum gap between segments (ms) |
| `gap_max_ms` | 120 | Maximum gap before clamping (ms) |
| `min_segment_duration_ms` | 200 | Minimum segment duration (ms) |
| `window_padding_ms` | 1000 | Padding around alignment window (ms) |
| `max_window_ms` | 30000 | Maximum alignment window size (ms) |
| `coverage_threshold` | 0.80 | Minimum coverage for quality gate |
| `confidence_threshold` | 0.55 | Minimum avg confidence for quality gate |

## Runbook

### Low Coverage / Confidence

1. Check `word_timeline.json` → `alignment_runs[].coverage` and `avg_confidence`
2. If coverage < 80%: audio may have music/noise in that region
3. Try re-processing with vocal isolation enabled
4. Use `/api/jobs/{id}/word-timeline/build` to regenerate from current segments

### Reprocessing

1. Build fresh timeline: `POST /api/jobs/{id}/word-timeline/build`
2. Check metrics in response
3. If satisfactory, use remap endpoint for text edits
4. If not, consider re-transcribing the affected region
