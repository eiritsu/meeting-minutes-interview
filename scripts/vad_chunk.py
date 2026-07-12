#!/usr/bin/env python3
"""
VAD (Voice Activity Detection) silence-based audio chunker.

Pure Python, no external dependencies — only stdlib (wave, struct, json, math).

Reads a 16kHz mono WAV file, detects silence segments via RMS energy,
and splits audio at silence midpoints. Falls back to fixed-time chunking
if no silence is detected.

Design inspired by meetily: split at natural pauses for better transcription.

CLI:
    python3 vad_chunk.py --input meeting.wav --output-dir /tmp/chunks

Output (JSON to stdout):
    {
      "chunks": [
        {"path": "...", "index": 1, "start_time": 0.0, "end_time": 120.5, "duration": 120.5}
      ],
      "total_chunks": N,
      "method": "vad"  // or "fixed_fallback"
    }
"""
import argparse
import json
import math
import os
import struct
import sys
import wave
from pathlib import Path


# ─── RMS / dB helpers ───────────────────────────────────────────────────────

def rms_to_db(rms: float) -> float:
    """Convert RMS amplitude (0.0–32768.0) to dB. Floor at -100 dB."""
    if rms <= 0:
        return -100.0
    return 20.0 * math.log10(rms / 32768.0)


def db_to_rms(db: float) -> float:
    """Convert dB (relative to full-scale 16-bit) back to RMS amplitude."""
    return 32768.0 * (10.0 ** (db / 20.0))


# ─── Frame-level energy analysis ────────────────────────────────────────────

def compute_frame_energies(samples: list, frame_size: int) -> list:
    """
    Compute RMS energy (as dB) for each non-overlapping frame.

    Args:
        samples: list of int16 sample values
        frame_size: samples per frame (e.g. 800 = 50ms at 16kHz)

    Returns:
        List of (frame_rms_db, sample_offset) tuples
    """
    energies = []
    num_frames = len(samples) // frame_size
    for i in range(num_frames):
        start = i * frame_size
        end = start + frame_size
        frame = samples[start:end]
        # RMS = sqrt(mean(x^2))
        sum_sq = sum(s * s for s in frame)
        rms = math.sqrt(sum_sq / frame_size)
        db = rms_to_db(rms)
        energies.append((db, start))
    return energies


# ─── Silence segment detection ──────────────────────────────────────────────

def detect_silence_segments(energies: list, threshold_db: float,
                            min_silence_frames: int, sr: int) -> list:
    """
    Group consecutive below-threshold frames into silence segments.

    Args:
        energies: list of (db, sample_offset) from compute_frame_energies
        threshold_db: frames below this dB are "silent"
        min_silence_frames: minimum consecutive silent frames for a segment
        sr: sample rate (for converting frame counts to time)

    Returns:
        List of (center_sample, silence_start_sec, silence_end_sec) tuples
    """
    segments = []
    seg_start = None  # index in energies list

    for i, (db, _) in enumerate(energies):
        if db < threshold_db:
            if seg_start is None:
                seg_start = i
        else:
            if seg_start is not None:
                seg_len = i - seg_start
                if seg_len >= min_silence_frames:
                    # Center of the silence segment (in sample index)
                    center_idx = seg_start + seg_len // 2
                    center_sample = energies[center_idx][1]
                    seg_start_sec = energies[seg_start][1] / sr
                    seg_end_sec = energies[i - 1][1] / sr
                    # The actual end includes frame_size samples
                    frame_size = energies[1][1] - energies[0][1] if len(energies) > 1 else 800
                    seg_end_sec = (energies[i - 1][1] + frame_size) / sr
                    segments.append((center_sample, seg_start_sec, seg_end_sec))
                seg_start = None

    # Handle trailing silence
    if seg_start is not None:
        seg_len = len(energies) - seg_start
        if seg_len >= min_silence_frames:
            center_idx = seg_start + seg_len // 2
            center_sample = energies[center_idx][1]
            seg_start_sec = energies[seg_start][1] / sr
            # Trailing silence end = total samples
            frame_size = energies[1][1] - energies[0][1] if len(energies) > 1 else 800
            seg_end_sec = (energies[-1][1] + frame_size) / sr
            segments.append((center_sample, seg_start_sec, seg_end_sec))

    return segments


# ─── Chunk boundary computation ─────────────────────────────────────────────

def filter_edge_silences(segments: list, total_samples: int, sr: int,
                          min_segment_sec: float = 3.0) -> list:
    """
    Remove silence segments at the very start or end of audio.
    Leading/trailing silence are natural and shouldn't be split points.

    A segment is "edge" if:
      - Its silence range touches the start (start_sec < min_segment_sec)
      - Its silence range touches the end (end_sec > total_duration - min_segment_sec)
    """
    total_duration = total_samples / sr
    min_silence_start = min_segment_sec
    max_silence_end = total_duration - min_segment_sec

    filtered = []
    for center_sample, start_sec, end_sec in segments:
        # Skip if silence touches the start edge
        if start_sec < min_silence_start:
            continue
        # Skip if silence touches the end edge
        if end_sec > max_silence_end:
            continue
        filtered.append((center_sample, start_sec, end_sec))
    return filtered


def compute_chunk_boundaries(segments: list, total_samples: int, sr: int,
                            overlap_samples: int,
                            max_chunk_samples: int) -> list:
    """
    Compute chunk boundaries from silence midpoints.

    Chunks are split at silence midpoints with optional overlap on each side.
    Adjacent chunks intentionally overlap by 2*overlap_samples to avoid
    cutting off words at boundaries. This overlap is by design.

    Args:
        segments: list of (center_sample, ...) from detect_silence_segments
        total_samples: total number of samples in the audio
        sr: sample rate
        overlap_samples: overlap in samples on each side of boundary
        max_chunk_samples: max chunk size in samples

    Returns:
        List of (start_sample, end_sample) tuples
    """
    if not segments:
        return []

    # Step 1: Compute non-overlapping base split points
    split_points = [0]  # start of audio
    for center_sample, _, _ in segments:
        split_points.append(center_sample)
    split_points.append(total_samples)  # end of audio

    # Step 2: Convert split points to boundaries with overlap
    boundaries = []
    for i in range(len(split_points) - 1):
        base_start = split_points[i]
        base_end = split_points[i + 1]

        # Extend by overlap on each side (avoid cutting words)
        if i == 0:
            # First chunk: no left overlap, extend right
            chunk_start = 0
            chunk_end = min(base_end + overlap_samples, total_samples)
        elif i == len(split_points) - 2:
            # Last chunk: extend left, no right overlap
            chunk_start = max(base_start - overlap_samples, 0)
            chunk_end = total_samples
        else:
            # Middle chunks: extend both sides
            chunk_start = max(base_start - overlap_samples, 0)
            chunk_end = min(base_end + overlap_samples, total_samples)

        # Skip tiny chunks (< 1 second)
        if (chunk_end - chunk_start) < sr:
            continue

        # Skip if this would be a near-duplicate of previous chunk
        # (chunk starts within 0.5s of previous chunk's end)
        if boundaries and chunk_start >= boundaries[-1][1] - int(0.5 * sr):
            # Extend previous chunk to cover this region
            boundaries[-1] = (boundaries[-1][0], max(boundaries[-1][1], chunk_end))
            continue

        boundaries.append((chunk_start, chunk_end))

    # Step 3: Enforce max chunk size — split oversized chunks
    result = []
    for start, end in boundaries:
        chunk_size = end - start
        if chunk_size > max_chunk_samples:
            # Split into fixed-size sub-chunks with overlap
            pos = start
            while pos < end:
                chunk_end = min(pos + max_chunk_samples, end)
                result.append((pos, chunk_end))
                pos = chunk_end - overlap_samples  # overlap for next sub-chunk
                if pos >= end - sr:
                    break
        else:
            result.append((start, end))

    return result



# ─── Fixed-time fallback ────────────────────────────────────────────────────

def fixed_time_boundaries(total_samples: int, sr: int,
                          max_chunk_samples: int,
                          overlap_samples: int) -> list:
    """Generate fixed-time chunk boundaries as fallback."""
    boundaries = []
    pos = 0
    while pos < total_samples:
        end = min(pos + max_chunk_samples, total_samples)
        boundaries.append((pos, end))
        pos = end - overlap_samples  # overlap for next chunk
        if pos >= total_samples:
            break
        # Ensure we don't infinite loop on tiny remainders
        if end == total_samples:
            break
    return boundaries


# ─── WAV writing ────────────────────────────────────────────────────────────

def write_chunk_wav(src_path: str, dst_path: str,
                    start_sample: int, end_sample: int,
                    sr: int, nchannels: int, sampwidth: int) -> dict:
    """
    Extract a portion of a WAV file and write it to a new file.

    Returns dict with path, start_time, end_time, duration.
    """
    with wave.open(src_path, 'rb') as src:
        src.setpos(start_sample)
        n_frames = end_sample - start_sample
        data = src.readframes(n_frames)

    with wave.open(dst_path, 'wb') as dst:
        dst.setnchannels(nchannels)
        dst.setsampwidth(sampwidth)
        dst.setframerate(sr)
        dst.writeframes(data)

    start_time = start_sample / sr
    end_time = end_sample / sr
    duration = end_time - start_time

    return {
        "path": str(dst_path),
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
        "duration": round(duration, 3),
    }


# ─── Main VAD chunking pipeline ─────────────────────────────────────────────

def vad_chunk(input_path: str, output_dir: str,
              min_silence_duration: float = 1.5,
              silence_threshold_db: float = -40.0,
              max_chunk_seconds: float = 900.0,
              overlap_seconds: float = 0.5) -> dict:
    """
    Main VAD chunking function.

    Args:
        input_path: path to 16kHz mono WAV file
        output_dir: directory to write chunk files
        min_silence_duration: minimum silence duration (seconds) to count as split point
        silence_threshold_db: RMS dB threshold below which audio is "silent"
        max_chunk_seconds: maximum chunk duration in seconds
        overlap_seconds: overlap on each side of split point

    Returns:
        JSON-serializable dict with chunks, total_chunks, method
    """
    input_path = str(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read WAV metadata
    with wave.open(input_path, 'rb') as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        sr = wf.getframerate()
        total_frames = wf.getnframes()

        if sr != 16000:
            print(f"[WARN] Expected 16kHz, got {sr}Hz. Proceeding anyway.", file=sys.stderr)
        if nchannels != 1:
            print(f"[WARN] Expected mono, got {nchannels} channels. Proceeding anyway.", file=sys.stderr)

        # Read all samples
        raw_data = wf.readframes(total_frames)

    # Unpack samples based on bit depth
    if sampwidth == 2:
        samples = list(struct.unpack(f'<{total_frames}h', raw_data))
    elif sampwidth == 1:
        # 8-bit WAV: unsigned, center at 128
        samples = [s - 128 for s in struct.unpack(f'<{total_frames}B', raw_data)]
        # Scale to int16 range for consistent dB calculation
        samples = [s * 256 for s in samples]
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth} bytes")

    total_duration = total_frames / sr

    # ── VAD parameters ──
    # Frame size: 50ms = 800 samples at 16kHz
    frame_size = int(sr * 0.05)
    if frame_size < 1:
        frame_size = 1

    min_silence_frames = max(1, int(min_silence_duration * sr / frame_size))
    overlap_samples = int(overlap_seconds * sr)
    max_chunk_samples = int(max_chunk_seconds * sr)

    # ── Step 1: Compute frame energies ──
    energies = compute_frame_energies(samples, frame_size)

    if not energies:
        # Empty or very short audio
        chunk_info = write_chunk_wav(input_path, str(output_dir / "chunk_001.wav"),
                                     0, total_frames, sr, nchannels, sampwidth)
        chunk_info["index"] = 1
        return {
            "chunks": [chunk_info],
            "total_chunks": 1,
            "method": "vad",
        }

    # ── Step 2: Detect silence segments ──
    silence_segments = detect_silence_segments(
        energies, silence_threshold_db, min_silence_frames, sr
    )

    # ── Step 2.5: Filter edge silences ──
    # Leading/trailing silence are natural and shouldn't be split points.
    # A silence segment is "edge" if it touches the first/last 3 seconds.
    filtered_segments = filter_edge_silences(silence_segments, total_frames, sr)

    # ── Step 3: Decide method ──
    if filtered_segments:
        silence_segments = filtered_segments  # use filtered list
        method = "vad"
        boundaries = compute_chunk_boundaries(
            silence_segments, total_frames, sr,
            overlap_samples, max_chunk_samples
        )
    else:
        # No silence detected → fallback to fixed-time chunking
        method = "fixed_fallback"
        boundaries = fixed_time_boundaries(
            total_frames, sr, max_chunk_samples, overlap_samples
        )
        print(f"[INFO] No silence segments detected (threshold={silence_threshold_db}dB, "
              f"min_duration={min_silence_duration}s). Falling back to fixed-time chunking "
              f"({max_chunk_seconds}s per chunk).", file=sys.stderr)

    # Ensure we have at least one chunk
    if not boundaries:
        boundaries = [(0, total_frames)]

    # ── Step 4: Write chunk files ──
    chunks = []
    for idx, (start, end) in enumerate(boundaries, 1):
        # Clamp to valid range
        start = max(0, start)
        end = min(total_frames, end)
        if start >= end:
            continue

        chunk_filename = f"chunk_{idx:03d}.wav"
        chunk_path = output_dir / chunk_filename

        info = write_chunk_wav(
            input_path, str(chunk_path),
            start, end, sr, nchannels, sampwidth
        )
        info["index"] = idx
        chunks.append(info)

    return {
        "chunks": chunks,
        "total_chunks": len(chunks),
        "method": method,
    }


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="VAD silence-based audio chunker (pure Python, no dependencies)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python3 vad_chunk.py --input meeting.wav --output-dir /tmp/chunks

  # Adjust sensitivity (more aggressive splitting)
  python3 vad_chunk.py --input meeting.wav --output-dir /tmp/chunks \\
      --min-silence-duration 0.8 --silence-threshold-db -35

  # Longer max chunk, more overlap
  python3 vad_chunk.py --input meeting.wav --output-dir /tmp/chunks \\
      --max-chunk-seconds 1200 --overlap-seconds 1.0
        """
    )
    parser.add_argument("--input", required=True,
                        help="Path to 16kHz mono WAV file")
    parser.add_argument("--output-dir", required=True,
                        help="Directory for chunk WAV files")
    parser.add_argument("--min-silence-duration", type=float, default=1.5,
                        help="Minimum silence duration in seconds (default: 1.5)")
    parser.add_argument("--silence-threshold-db", type=float, default=-40.0,
                        help="Silence threshold in dB (default: -40)")
    parser.add_argument("--max-chunk-seconds", type=float, default=900.0,
                        help="Maximum chunk duration in seconds (default: 900 = 15min)")
    parser.add_argument("--overlap-seconds", type=float, default=0.5,
                        help="Overlap on each side of split point in seconds (default: 0.5)")
    parser.add_argument("--debug", action="store_true",
                        help="Print debug info to stderr")

    args = parser.parse_args()

    # Validate input
    if not os.path.isfile(args.input):
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    result = vad_chunk(
        input_path=args.input,
        output_dir=args.output_dir,
        min_silence_duration=args.min_silence_duration,
        silence_threshold_db=args.silence_threshold_db,
        max_chunk_seconds=args.max_chunk_seconds,
        overlap_seconds=args.overlap_seconds,
    )

    if args.debug:
        print(f"\n[DEBUG] Method: {result['method']}", file=sys.stderr)
        print(f"[DEBUG] Total chunks: {result['total_chunks']}", file=sys.stderr)
        for c in result["chunks"]:
            print(f"  [{c['index']}] {c['start_time']:.1f}s → {c['end_time']:.1f}s "
                  f"({c['duration']:.1f}s) {c['path']}", file=sys.stderr)

    # Output JSON to stdout
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
