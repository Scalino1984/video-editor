"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class BackendEnum(str, Enum):
    voxtral = "voxtral"
    openai_whisper = "openai_whisper"
    local_whisper = "local_whisper"
    whisperx = "whisperx"


class LanguageEnum(str, Enum):
    auto = "auto"
    de = "de"
    en = "en"
    fr = "fr"
    es = "es"
    it = "it"
    pt = "pt"
    ja = "ja"
    ko = "ko"
    zh = "zh"


class KaraokeModeEnum(str, Enum):
    k = "k"
    kf = "kf"
    ko = "ko"


class PresetEnum(str, Enum):
    classic = "classic"
    neon = "neon"
    high_contrast = "high_contrast"
    landscape_1080p = "landscape_1080p"
    portrait_1080x1920 = "portrait_1080x1920"
    mobile_safe = "mobile_safe"


class ExportFormatEnum(str, Enum):
    srt = "srt"
    ass = "ass"
    vtt = "vtt"
    lrc = "lrc"
    txt = "txt"


class LyricsTemplateModeEnum(str, Enum):
    source_of_truth = "lyrics_source_of_truth"
    layout_only = "layout_only_reflow"
    hybrid = "hybrid_mark_differences"
    correct_words_only = "correct_words_only"


class LyricsModeEnum(str, Enum):
    line_per_event = "line_per_event"
    merge_by_empty_lines = "merge_by_empty_lines"


class MatchModeEnum(str, Enum):
    strict = "strict"
    lenient = "lenient"


class ApproxKaraokeEnum(str, Enum):
    auto = "auto"
    on = "on"
    off = "off"


class JobStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    preprocessing = "preprocessing"
    transcribing = "transcribing"
    refining = "refining"
    exporting = "exporting"
    rendering_preview = "rendering_preview"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


# ── Request Models ────────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    backend: BackendEnum = BackendEnum.voxtral
    language: LanguageEnum = LanguageEnum.auto
    vad: bool = True
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)
    normalize: bool = True
    target_lufs: float = -16.0
    vocal_isolation: bool = False
    vocal_device: str = "cpu"
    word_timestamps: str = "auto"
    generate_ass: bool = True
    generate_vtt: bool = False
    generate_lrc: bool = False
    generate_txt: bool = False
    karaoke_mode: KaraokeModeEnum = KaraokeModeEnum.kf
    preset: PresetEnum = PresetEnum.classic
    highlight_color: str = "&H0000FFFF"
    safe_area: str = ""
    snap_to_beat: bool = False
    bpm: str | None = None
    ai_correct: bool = False
    cps: float = 18.0
    min_duration: float = 1.0
    max_duration: float = 6.0
    max_chars_per_line: int = 42
    max_lines: int = 2
    generate_preview: bool = False
    preview_duration: str = "15s"
    preview_start: str = "0s"
    preview_resolution: str = "1920x1080"
    whisperx_model_size: str = "large-v3"
    lyrics_file: str | None = None  # optional .txt/.lrc lyrics file (filename in uploads/)
    use_lyrics_template: bool = False  # activate lyrics template mode
    lyrics_template_mode: LyricsTemplateModeEnum = LyricsTemplateModeEnum.source_of_truth
    lyrics_mode: LyricsModeEnum = LyricsModeEnum.line_per_event
    match_mode: MatchModeEnum = MatchModeEnum.lenient
    preserve_empty_lines: bool = False
    approx_karaoke: ApproxKaraokeEnum = ApproxKaraokeEnum.auto
    whisperx_compute_type: str = "float16"
    whisperx_batch_size: int = 16
    build_word_timeline: bool = True


class RemapWordsRequest(BaseModel):
    """Request body for word remap endpoint."""
    edits: dict[str, str] = Field(..., description="segment_index→new_text")


class RemapWordsResponse(BaseModel):
    action: str
    confidence: float = 0.0
    needs_review: bool = False
    metrics: dict[str, Any] = {}
    details: dict[str, Any] = {}


class TimelineMetricsSchema(BaseModel):
    coverage_pct: float = 0.0
    avg_confidence: float = 0.0
    word_count: int = 0
    syllable_count: int = 0
    segment_count: int = 0
    remap_only: bool = False
    realign_needed: bool = False


class BuildTimelineResponse(BaseModel):
    status: str = "built"
    metrics: TimelineMetricsSchema = TimelineMetricsSchema()


class RefineRequest(BaseModel):
    cps: float = 18.0
    min_duration: float = 1.0
    max_duration: float = 6.0
    max_chars_per_line: int = 42
    max_lines: int = 2
    snap_to_beat: bool = False
    bpm: str | None = None


class ExportRequest(BaseModel):
    karaoke_mode: KaraokeModeEnum = KaraokeModeEnum.kf
    preset: PresetEnum = PresetEnum.classic
    highlight_color: str = "&H0000FFFF"
    safe_area: str = ""
    approx_karaoke: bool = True
    formats: list[ExportFormatEnum] = [ExportFormatEnum.srt, ExportFormatEnum.ass]


# ── Segment Operations ────────────────────────────────────────────────────────

class SegmentUpdate(BaseModel):
    index: int
    text: str | None = None
    start: float | None = None
    end: float | None = None
    speaker: str | None = None
    pinned: bool | None = None


class SegmentSplit(BaseModel):
    index: int
    split_at: float


class SegmentMerge(BaseModel):
    index_a: int
    index_b: int


class SegmentReorder(BaseModel):
    old_index: int
    new_index: int


class TimeShift(BaseModel):
    offset_ms: float
    range_start: int | None = None
    range_end: int | None = None


class SearchReplace(BaseModel):
    search: str
    replace: str
    case_sensitive: bool = False
    regex: bool = False


class DictionaryEntry(BaseModel):
    wrong: str
    correct: str


class TranslateRequest(BaseModel):
    target_language: str = "en"


class RetranscribeSegment(BaseModel):
    index: int
    backend: BackendEnum = BackendEnum.voxtral
    language: LanguageEnum = LanguageEnum.auto


# ── Response Models ───────────────────────────────────────────────────────────

class JobInfo(BaseModel):
    job_id: str
    filename: str
    status: JobStatus
    progress: float = 0.0
    stage: str = ""
    created_at: datetime
    completed_at: datetime | None = None
    error: str | None = None
    result: JobResult | None = None


class JobResult(BaseModel):
    srt_file: str | None = None
    ass_file: str | None = None
    vtt_file: str | None = None
    lrc_file: str | None = None
    txt_file: str | None = None
    preview_file: str | None = None
    report_file: str | None = None
    segments_count: int = 0
    duration_sec: float = 0.0
    needs_review: int = 0
    backend: str = ""
    language: str = ""
    word_timestamps_available: bool = False

    model_config = ConfigDict(from_attributes=True)


class SegmentInfo(BaseModel):
    index: int
    start: float
    end: float
    text: str
    confidence: float = 1.0
    has_word_timestamps: bool = False
    words: list[WordInfoSchema] = []
    speaker: str | None = None
    pinned: bool = False


class WordInfoSchema(BaseModel):
    start: float
    end: float
    word: str
    confidence: float = 1.0


class FileInfo(BaseModel):
    filename: str
    size: int
    created: datetime
    type: str
    duration: float | None = None


class AudioProbeInfo(BaseModel):
    filename: str
    duration: float
    format_name: str = ""
    bit_rate: int = 0
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""


class GapOverlap(BaseModel):
    type: str  # "gap" or "overlap"
    index_a: int
    index_b: int
    start: float
    end: float
    duration_ms: float


class JobStats(BaseModel):
    total_segments: int = 0
    total_words: int = 0
    total_chars: int = 0
    duration_sec: float = 0.0
    avg_cps: float = 0.0
    max_cps: float = 0.0
    min_cps: float = 0.0
    cps_distribution: list[dict[str, str | int]] = []
    avg_segment_duration: float = 0.0
    avg_confidence: float = 0.0
    segments_with_words: int = 0
    segments_needing_review: int = 0
    gaps: int = 0
    overlaps: int = 0
    pinned: int = 0
    bpm: float = 0.0
    processing: dict[str, bool | float] = {}


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "3.2.0"
    ffmpeg: bool = False
    backends: dict[str, bool] = {}


# ── Media / Tags ──────────────────────────────────────────────────────────────

class MediaInfo(BaseModel):
    media_id: str
    filename: str
    mime: str = ""
    file_type: str = ""  # "audio" | "video" | "subtitle" | "lyrics"
    size: int = 0
    duration: float = 0
    taggable: bool = False
    editable: bool = False
    created_at: str = ""


class MediaTagsResponse(BaseModel):
    media_id: str
    filename: str
    tags: dict[str, str]
    editable: bool
    supported_fields: list[str]
    has_cover: bool = False


class MediaTagsUpdate(BaseModel):
    tags: dict[str, str]


class LyricsTemplateInfo(BaseModel):
    source_file: str
    format: str
    total_lines: int
    target_lines_count: int
    sections: list[str]
    has_timestamps: bool = False


# Update forward ref
JobInfo.model_rebuild()
