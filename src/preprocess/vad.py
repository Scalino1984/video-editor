"""Voice Activity Detection using webrtcvad."""

from __future__ import annotations

import struct
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from src.utils.logging import debug, warn


@dataclass
class SpeechSegment:
    start_ms: int
    end_ms: int


def _read_wave(path: Path) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError("WAV must be mono")
        if wf.getsampwidth() != 2:
            raise ValueError("WAV must be 16-bit")
        sample_rate = wf.getframerate()
        if sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(f"Unsupported sample rate: {sample_rate}")
        data = wf.readframes(wf.getnframes())
    return data, sample_rate, wf.getnframes()


def _frame_generator(audio: bytes, sample_rate: int, frame_ms: int = 30):
    n = int(sample_rate * (frame_ms / 1000.0) * 2)
    offset = 0
    timestamp = 0.0
    duration = frame_ms / 1000.0
    while offset + n <= len(audio):
        yield audio[offset:offset + n], timestamp, duration
        timestamp += duration
        offset += n


def detect_speech(wav_path: Path, aggressiveness: int = 2,
                  min_speech_ms: int = 300, min_silence_ms: int = 500) -> list[SpeechSegment]:
    try:
        import webrtcvad
    except ImportError:
        warn("webrtcvad not installed — skipping VAD")
        return []

    audio, sample_rate, n_frames = _read_wave(wav_path)
    vad = webrtcvad.Vad(aggressiveness)

    segments: list[SpeechSegment] = []
    frame_ms = 30
    is_speech = False
    speech_start = 0
    silence_frames = 0
    speech_frames = 0
    min_speech_frames = min_speech_ms // frame_ms
    min_silence_frames = min_silence_ms // frame_ms

    for frame, timestamp, duration in _frame_generator(audio, sample_rate, frame_ms):
        active = vad.is_speech(frame, sample_rate)

        if not is_speech:
            if active:
                speech_frames += 1
                if speech_frames >= min_speech_frames:
                    is_speech = True
                    speech_start = int((timestamp - (speech_frames - 1) * duration) * 1000)
                    silence_frames = 0
            else:
                speech_frames = 0
        else:
            if not active:
                silence_frames += 1
                if silence_frames >= min_silence_frames:
                    end_ms = int((timestamp - silence_frames * duration) * 1000)
                    segments.append(SpeechSegment(speech_start, end_ms))
                    is_speech = False
                    speech_frames = 0
                    silence_frames = 0
            else:
                silence_frames = 0

    if is_speech:
        end_ms = int((n_frames / sample_rate) * 1000)
        segments.append(SpeechSegment(speech_start, end_ms))

    debug(f"VAD found {len(segments)} speech segments")
    return segments


def create_vad_trimmed(wav_path: Path, segments: list[SpeechSegment],
                       output_path: Path | None = None, pad_ms: int = 200) -> Path:
    if not segments:
        return wav_path

    if output_path is None:
        output_path = wav_path.with_stem(wav_path.stem + "_vad")

    # Merge overlapping/adjacent segments first (critical for correct time mapping)
    merged = _merge_close_segments(segments, gap_ms=pad_ms * 2)

    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        sw = wf.getsampwidth()
        nc = wf.getnchannels()
        total_frames = wf.getnframes()
        audio = wf.readframes(total_frames)

    total_ms = int(total_frames / sr * 1000)
    bytes_per_ms = sr * sw * nc // 1000
    trimmed = b""
    prev_end = -1
    for seg in merged:
        start = max(0, seg.start_ms - pad_ms)
        end = min(total_ms, seg.end_ms + pad_ms)
        # Prevent overlap with previous segment
        if prev_end >= 0 and start < prev_end:
            start = prev_end
        if start >= end:
            continue
        start_byte = start * bytes_per_ms
        end_byte = end * bytes_per_ms
        trimmed += audio[start_byte:end_byte]
        prev_end = end

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(nc)
        wf.setsampwidth(sw)
        wf.setframerate(sr)
        wf.writeframes(trimmed)

    return output_path


def _merge_close_segments(segments: list[SpeechSegment], gap_ms: int = 400) -> list[SpeechSegment]:
    """Merge speech segments that are closer than gap_ms apart."""
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda s: s.start_ms)
    merged = [SpeechSegment(sorted_segs[0].start_ms, sorted_segs[0].end_ms)]
    for seg in sorted_segs[1:]:
        if seg.start_ms - merged[-1].end_ms <= gap_ms:
            merged[-1].end_ms = max(merged[-1].end_ms, seg.end_ms)
        else:
            merged.append(SpeechSegment(seg.start_ms, seg.end_ms))
    debug(f"VAD merge: {len(segments)} → {len(merged)} segments (gap≤{gap_ms}ms)")
    return merged


def create_time_mapping(segments: list[SpeechSegment], pad_ms: int = 200) -> list[tuple[int, int, int]]:
    """Return list of (vad_start_ms, vad_end_ms, original_start_ms) for remapping."""
    # Merge first to prevent overlapping padding
    merged = _merge_close_segments(segments, gap_ms=pad_ms * 2)
    mapping = []
    offset = 0
    prev_end = -1
    for seg in merged:
        padded_start = max(0, seg.start_ms - pad_ms)
        padded_end = seg.end_ms + pad_ms
        # Prevent overlap with previous padded segment
        if prev_end >= 0 and padded_start < prev_end:
            padded_start = prev_end
        if padded_start >= padded_end:
            continue
        duration = padded_end - padded_start
        mapping.append((offset, offset + duration, padded_start))
        offset += duration
        prev_end = padded_end
    return mapping


def remap_timestamps(segments: list[dict], time_mapping: list[tuple[int, int, int]]) -> list[dict]:
    """Remap timestamps from VAD-trimmed audio back to original timeline."""
    if not time_mapping:
        return segments

    result = []
    for seg in segments:
        start_ms = int(seg["start"] * 1000)
        end_ms = int(seg["end"] * 1000)

        matched = False
        for vad_start, vad_end, orig_start in time_mapping:
            if vad_start <= start_ms < vad_end:
                offset = orig_start - vad_start
                new_seg = dict(seg)
                new_seg["start"] = (start_ms + offset) / 1000

                # For end_ms: check if it crosses into the next chunk
                if end_ms <= vad_end:
                    new_seg["end"] = (end_ms + offset) / 1000
                else:
                    # End is beyond this chunk — find the right chunk for end
                    end_offset = offset  # fallback: same offset
                    for vs, ve, os in time_mapping:
                        if vs <= end_ms < ve:
                            end_offset = os - vs
                            break
                    new_seg["end"] = (end_ms + end_offset) / 1000

                # Remap word timestamps
                if "words" in new_seg:
                    remapped_words = []
                    for w in new_seg["words"]:
                        w_start_ms = int(w["start"] * 1000)
                        w_end_ms = int(w["end"] * 1000)
                        w_offset = offset  # default: same chunk as segment start
                        for vs, ve, os in time_mapping:
                            if vs <= w_start_ms < ve:
                                w_offset = os - vs
                                break
                        w_end_offset = w_offset  # default: same chunk as word start
                        for vs, ve, os in time_mapping:
                            if vs <= w_end_ms < ve:
                                w_end_offset = os - vs
                                break
                        remapped_words.append({
                            **w,
                            "start": (w_start_ms + w_offset) / 1000,
                            "end": (w_end_ms + w_end_offset) / 1000,
                        })
                    new_seg["words"] = remapped_words

                result.append(new_seg)
                matched = True
                break

        if not matched:
            # Segment doesn't match any VAD chunk — find nearest chunk
            if time_mapping:
                nearest = min(time_mapping, key=lambda m: abs(m[0] - start_ms))
                offset = nearest[2] - nearest[0]
                new_seg = dict(seg)
                new_seg["start"] = (start_ms + offset) / 1000
                new_seg["end"] = (end_ms + offset) / 1000
                if "words" in new_seg:
                    new_seg["words"] = [
                        {**w, "start": w["start"] + offset / 1000, "end": w["end"] + offset / 1000}
                        for w in new_seg["words"]
                    ]
                result.append(new_seg)
                warn(f"VAD remap: segment at {seg['start']:.1f}s didn't match any chunk, used nearest")

    # Post-remap: detect unreasonable gaps
    if len(result) >= 2:
        max_gap = 0
        for i in range(1, len(result)):
            gap = result[i]["start"] - result[i-1]["end"]
            max_gap = max(max_gap, gap)
        if max_gap > 30:
            warn(f"VAD remap: large gap detected ({max_gap:.1f}s) — may indicate VAD over-trimming")

    return result
