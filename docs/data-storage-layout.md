# Data & Storage Layout

## Root Paths

| Path | Purpose | Cleanup |
|------|---------|---------|
| `data/uploads/` | Uploaded audio/text files | Manual delete via UI/API |
| `data/output/{job_id}/` | Per-job output artifacts | Deleted with job (`DELETE /api/jobs/{job_id}`) |
| `data/editor/assets/` | Editor project assets (UUID-prefixed copies) | Manual or orphan cleanup |
| `data/editor/projects/` | Saved editor project JSON files | Manual delete |
| `data/editor/renders/` | Rendered video outputs | Manual delete |
| `data/library.sqlite` | Library DB (transcriptions, media, file_registry) | Persistent |

## Per-Job Artifacts (`data/output/{job_id}/`)

| File | Purpose | Auto-generated |
|------|---------|----------------|
| `{stem}.srt` | SRT subtitles | Yes (pipeline + sync on edit) |
| `{stem}.ass` | ASS karaoke subtitles | Yes (pipeline + sync on edit) |
| `{stem}.vtt` | WebVTT subtitles | Optional (export) |
| `{stem}.lrc` | LRC lyrics | Optional (export) |
| `{stem}.txt` | Plain text | Optional (export) |
| `{stem}.report.json` | Confidence/quality report | Yes |
| `{stem}_karaoke.html` | Standalone HTML player | Optional |
| `segments.json` | **Single Source of Truth** for segment editing | Yes |
| `waveform.json` | Waveform peaks for UI visualization | Yes |
| `{audio_copy}` | Copy of original audio for playback | Yes |
| `.chat_history.sqlite` | AI chat history per job | On first AI chat |
| `snapshots/snap_*.json` | Segment state snapshots | On user request |
| `stems/` | Demucs vocal separation outputs | On separation job |
| `separation_result.json` | Separation metadata | On separation job |

## Naming Conventions

- Job IDs: `uuid4().hex[:12]` (e.g., `a1b2c3d4e5f6`)
- Editor asset files: `{uuid8}_{original_name}` (prevents collision)
- Snapshots: `snap_{label_or_timestamp}.json`
- File registry IDs: `uuid4().hex[:12]`

## Cleanup Strategy

1. **Job deletion** (`DELETE /api/jobs/{job_id}`):
   - Removes file registry references for the job
   - Marks unreferenced files as `deleted` in registry
   - Deletes `data/output/{job_id}/` directory tree
   - Removes job from in-memory tracking

2. **Orphan detection** (`GET /api/file-registry/orphaned/list`):
   - Finds files in registry with no remaining references
   - Candidates for manual cleanup via `POST /api/file-registry/cleanup`

3. **Job memory cleanup** (automatic):
   - Completed/failed/cancelled jobs exceeding `MAX_FINISHED_JOBS=200` are pruned from memory
   - On-disk artifacts persist until explicit deletion
