"""Confidence marking, low-confidence detection, and report generation."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

from src.transcription.base import TranscriptSegment
from src.utils.logging import warn


@dataclass
class SegmentReport:
    index: int
    start: float
    end: float
    text: str
    avg_conf: float
    min_conf: float
    needs_review: bool
    word_timestamps_real: bool
    low_conf_words: list[str] = field(default_factory=list)


@dataclass
class FileReport:
    filename: str
    backend: str
    language: str
    total_segments: int
    segments_needing_review: int
    avg_confidence: float
    vad_active: bool = False
    normalize_active: bool = False
    vocal_isolation_active: bool = False
    bpm_snap_active: bool = False
    bpm_value: float = 0.0
    ai_correct_active: bool = False
    duration_sec: float = 0.0
    runtime_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    segment_reports: list[SegmentReport] = field(default_factory=list)


def analyze_confidence(segments: list[TranscriptSegment],
                       threshold: float = 0.6) -> list[SegmentReport]:
    reports = []
    for i, seg in enumerate(segments):
        word_confs = [w.confidence for w in seg.words] if seg.words else [seg.confidence]
        avg_conf = sum(word_confs) / len(word_confs) if word_confs else 0.0
        min_conf = min(word_confs) if word_confs else 0.0
        needs_review = min_conf < threshold or avg_conf < threshold

        low_words = [w.word for w in seg.words if w.confidence < threshold]

        if needs_review:
            warn(f"Segment {i + 1} needs review (conf={avg_conf:.2f}): {seg.text[:50]}...")

        reports.append(SegmentReport(
            index=i + 1,
            start=seg.start,
            end=seg.end,
            text=seg.text,
            avg_conf=round(avg_conf, 3),
            min_conf=round(min_conf, 3),
            needs_review=needs_review,
            word_timestamps_real=seg.has_word_timestamps and all(
                w.confidence > 0.5 for w in seg.words
            ),
            low_conf_words=low_words,
        ))
    return reports


def generate_report(file_report: FileReport, fmt: str = "json") -> str:
    if fmt == "json":
        data = {
            "filename": file_report.filename,
            "backend": file_report.backend,
            "language": file_report.language,
            "total_segments": file_report.total_segments,
            "segments_needing_review": file_report.segments_needing_review,
            "avg_confidence": round(file_report.avg_confidence, 3),
            "processing": {
                "vad": file_report.vad_active,
                "normalize": file_report.normalize_active,
                "vocal_isolation": file_report.vocal_isolation_active,
                "bpm_snap": file_report.bpm_snap_active,
                "bpm": file_report.bpm_value,
                "ai_correct": file_report.ai_correct_active,
            },
            "duration_sec": round(file_report.duration_sec, 2),
            "runtime_sec": round(file_report.runtime_sec, 2),
            "errors": file_report.errors,
            "warnings": file_report.warnings,
            "segments": [
                {
                    "index": sr.index,
                    "start": sr.start,
                    "end": sr.end,
                    "text": sr.text,
                    "avg_conf": sr.avg_conf,
                    "min_conf": sr.min_conf,
                    "needs_review": sr.needs_review,
                    "word_timestamps_real": sr.word_timestamps_real,
                    "low_conf_words": sr.low_conf_words,
                }
                for sr in file_report.segment_reports
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    elif fmt == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "index", "start", "end", "text", "avg_conf", "min_conf",
            "needs_review", "word_timestamps_real", "low_conf_words"
        ])
        for sr in file_report.segment_reports:
            writer.writerow([
                sr.index, sr.start, sr.end, sr.text, sr.avg_conf, sr.min_conf,
                sr.needs_review, sr.word_timestamps_real, ";".join(sr.low_conf_words)
            ])
        return output.getvalue()

    return ""


def save_report(file_report: FileReport, output_path: Path, fmt: str = "json") -> Path:
    ext = ".json" if fmt == "json" else ".csv"
    report_path = output_path.with_suffix(f".report{ext}")
    content = generate_report(file_report, fmt)
    report_path.write_text(content, encoding="utf-8")
    return report_path
