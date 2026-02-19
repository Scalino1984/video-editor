# Job & Render Pipeline

## Job States

```
pending → preprocessing → transcribing → refining → exporting → completed
                                                               → failed
                                                               → cancelled
```

| State | Description |
|-------|-------------|
| `pending` | Job created, waiting for executor |
| `preprocessing` | FFmpeg convert, normalize, VAD, vocal isolation |
| `transcribing` | Backend transcription running |
| `refining` | Text cleanup, alignment, segmentation, lyrics align |
| `exporting` | SRT/ASS/VTT/LRC/TXT generation |
| `rendering_preview` | Optional preview clip rendering |
| `completed` | All artifacts generated |
| `failed` | Error occurred (see `job.error`) |
| `cancelled` | User-requested cancellation |

## Pipeline Flow

```
Audio Upload
  → create_job() [assigns job_id, SSE: job_created]
  → ThreadPoolExecutor._transcribe_sync()
    → _check_cancel() [checkpoint]
    → Vocal Isolation? (Demucs via media_executor)
    → FFmpeg convert → WAV 16kHz mono
    → Normalize? (LUFS target)
    → VAD? (webrtcvad silence removal)
    → Transcription (selected backend)
    → VAD Remap (restore original timestamps)
    → Text Cleanup (whitespace, quotes, dictionary)
    → Word Timestamp Approximation (syllable-weighted)
    → Segmentation (split/merge/gaps/line-breaks)
    → Lyrics Alignment? (greedy match to reference)
    → BPM Snap? (beat-grid quantization)
    → AI Correction? (Mistral API)
    → Export (SRT + ASS + optional formats)
    → Confidence Report
    → Waveform Generation
    → Library DB Save
    → SSE: job_completed
```

## Concurrency Control

- **ThreadPoolExecutor**: `max_workers=2` for transcription jobs
- **Media Semaphore**: `MAX_MEDIA_JOBS=1` (env) limits concurrent ffmpeg/demucs
- **Backpressure**: `MAX_PENDING_MEDIA_JOBS=3` (env) returns HTTP 429 when exceeded
- **Job Memory**: `MAX_FINISHED_JOBS=200` — oldest finished jobs pruned from memory

## Cancellation

- `POST /api/jobs/{job_id}/cancel` sets a `threading.Event`
- `_check_cancel(job_id)` called at each pipeline stage boundary
- Raises `JobCancelled` exception → caught in job wrapper

## Undo/Redo

- `push_undo(job_id)` saves current `segments.json` before every mutation
- Max 50 undo steps per job (deque-based)
- Redo stack cleared on new mutation
- Thread-safe via `_undo_lock`

## Idempotency

- Transcription deduplication via `source_hash` (filename + backend + language)
- Media registration deduplication via filename + path
- File registry deduplication via storage_path + state
