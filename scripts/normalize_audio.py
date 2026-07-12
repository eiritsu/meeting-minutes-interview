#!/usr/bin/env python3
"""
Audio Loudness Normalizer for ASR Preprocessing
================================================
EBU R128 loudness normalization targeting -16 LUFS (speech-optimized).

Features:
  - EBU R128 loudness normalization via ffmpeg loudnorm filter
  - Fallback to pure-Python peak normalization when ffmpeg is unavailable
  - Converts any input format (wav/mp3/m4a/flac/etc.) to 16kHz mono WAV
  - Skips processing if input is already 16kHz mono WAV within -20~-10 LUFS
  - Processing info output to stderr

Usage:
  python3 normalize_audio.py --input input.wav --output normalized.wav [--target-lufs -16]

Reference: meetily EBU R128 normalization pipeline.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import wave
import math
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# ffmpeg detection
# ---------------------------------------------------------------------------

def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg binary on macOS / Linux."""
    candidates = [
        shutil.which("ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


FFMPEG = find_ffmpeg()

# ---------------------------------------------------------------------------
# ffmpeg-based EBU R128 loudness measurement + normalization
# ---------------------------------------------------------------------------

def measure_loudness_ffmpeg(filepath: str, ffmpeg: str) -> dict:
    """
    Run two-pass loudness scan via ffmpeg loudnorm filter (print_format=json).
    Returns dict with integrated_loudness, true_peak, lra, etc.
    """
    cmd = [
        ffmpeg, "-hide_banner", "-nostats",
        "-i", filepath,
        "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # loudnorm JSON is in stderr
    stderr = result.stderr
    # Extract JSON block (between last { and last })
    json_match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', stderr, re.DOTALL)
    if not json_match:
        # Try multiline JSON block
        lines = stderr.split('\n')
        json_lines = []
        capture = False
        for line in lines:
            if '"input_i"' in line:
                capture = True
            if capture:
                json_lines.append(line)
            if capture and line.strip() == '}':
                break
        if json_lines:
            json_text = '\n'.join(json_lines)
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                pass
    else:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # Fallback: try to parse individual values from stderr
    info = {}
    for key in ['input_i', 'input_tp', 'input_lra', 'input_thresh',
                 'target_offset', 'target_i', 'target_tp']:
        m = re.search(rf'"{key}":\s*"([^"]*)"', stderr)
        if m:
            info[key] = m.group(1)
    return info


def normalize_ffmpeg(input_path: str, output_path: str, target_lufs: float,
                     target_tp: float = -1.5, ffmpeg: Optional[str] = None) -> dict:
    """
    Two-pass EBU R128 normalization using ffmpeg loudnorm filter.

    Pass 1: measure the audio
    Pass 2: apply normalization with measured values

    Returns dict with before/after loudness info.
    """
    if ffmpeg is None:
        ffmpeg = FFMPEG
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    info = {"method": "ffmpeg_ebu_r128"}

    # --- Pass 1: measure ---
    measured = measure_loudness_ffmpeg(input_path, ffmpeg)
    info["before_lufs"] = measured.get("input_i", "N/A")
    info["before_tp"] = measured.get("input_tp", "N/A")
    info["before_lra"] = measured.get("input_lra", "N/A")

    # --- Pass 2: normalize ---
    # Build loudnorm filter with measured values
    measured_i = measured.get("input_i", "0")
    measured_tp = measured.get("input_tp", "0")
    measured_lra = measured.get("input_lra", "7")
    measured_thresh = measured.get("input_thresh", "0")
    target_offset = measured.get("target_offset", "0")

    loudnorm_filter = (
        f"loudnorm=I={target_lufs}:TP={target_tp}:LRA=11"
        f":measured_I={measured_i}"
        f":measured_TP={measured_tp}"
        f":measured_LRA={measured_lra}"
        f":measured_thresh={measured_thresh}"
        f":offset={target_offset}"
        f":linear=true"
        f":print_format=json"
    )

    cmd = [
        ffmpeg, "-hide_banner", "-nostats", "-y",
        "-i", input_path,
        "-af", loudnorm_filter,
        "-ar", "16000",       # 16kHz for ASR
        "-ac", "1",           # mono
        "-acodec", "pcm_s16le",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[WARN] ffmpeg normalization failed: {result.stderr[-500:]}", file=sys.stderr)
        # Fallback: simple conversion
        cmd_simple = [
            ffmpeg, "-hide_banner", "-y",
            "-i", input_path,
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            output_path
        ]
        subprocess.run(cmd_simple, capture_output=True, text=True)
        info["method"] = "ffmpeg_simple_convert"
        return info

    # --- Pass 3: measure output ---
    out_measured = measure_loudness_ffmpeg(output_path, ffmpeg)
    info["after_lufs"] = out_measured.get("input_i", "N/A")
    info["after_tp"] = out_measured.get("input_tp", "N/A")

    return info


# ---------------------------------------------------------------------------
# Pure-Python fallback (peak normalization + format conversion)
# ---------------------------------------------------------------------------

def parse_wav_info(filepath: str) -> dict:
    """Parse WAV header to get sample rate, channels, bit depth."""
    try:
        with wave.open(filepath, 'rb') as wf:
            return {
                "channels": wf.getnchannels(),
                "sample_width": wf.getsampwidth(),
                "sample_rate": wf.getframerate(),
                "n_frames": wf.getnframes(),
            }
    except Exception:
        return {}


def measure_peak_python(filepath: str) -> float:
    """Measure peak amplitude of a WAV file in dB."""
    info = parse_wav_info(filepath)
    if not info:
        return -100.0

    sample_width = info["sample_width"]
    max_val = 0
    with open(filepath, 'rb') as f:
        # Skip WAV header
        data = f.read()
        # Find 'data' chunk
        idx = data.find(b'data')
        if idx == -1:
            return -100.0
        data_start = idx + 8  # skip 'data' + 4 bytes size
        audio_data = data[data_start:]

        if sample_width == 2:
            fmt = f'<{len(audio_data)//2}h'
            samples = struct.unpack(fmt, audio_data)
            max_val = max(abs(s) for s in samples) if samples else 0
            peak_linear = max_val / 32768.0
        elif sample_width == 1:
            samples = list(audio_data)
            max_val = max(abs(s - 128) for s in samples) if samples else 0
            peak_linear = max_val / 128.0
        elif sample_width == 4:
            fmt = f'<{len(audio_data)//4}i'
            samples = struct.unpack(fmt, audio_data)
            max_val = max(abs(s) for s in samples) if samples else 0
            peak_linear = max_val / 2147483648.0
        else:
            return -100.0

    if peak_linear <= 0:
        return -100.0
    return 20 * math.log10(peak_linear)


def normalize_peak_python(input_path: str, output_path: str,
                          target_peak_db: float = -3.0) -> dict:
    """
    Pure-Python peak normalization fallback.
    Converts to 16kHz mono WAV with peak normalization.
    """
    info = {"method": "python_peak_normalization"}

    try:
        with wave.open(input_path, 'rb') as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            raw_data = wf.readframes(n_frames)
    except Exception as e:
        # If wave module can't read it, try raw conversion via ffmpeg
        # or raise an error
        raise RuntimeError(f"Cannot read audio file: {e}. "
                           "Install ffmpeg for full format support.")

    # Convert to samples list (interleaved)
    if sample_width == 2:
        fmt = f'<{len(raw_data)//2}h'
        samples = list(struct.unpack(fmt, raw_data))
    elif sample_width == 1:
        # Convert 8-bit unsigned to signed 16-bit
        samples = [(s - 128) * 256 for s in raw_data]
        sample_width = 2
    elif sample_width == 4:
        fmt = f'<{len(raw_data)//4}i'
        samples = list(struct.unpack(fmt, raw_data))
        # Scale to 16-bit
        samples = [s // 65536 for s in samples]
        sample_width = 2
    else:
        raise RuntimeError(f"Unsupported sample width: {sample_width}")

    # Mix to mono if stereo
    if channels == 2:
        mono_samples = []
        for i in range(0, len(samples), 2):
            mono_samples.append((samples[i] + samples[i+1]) // 2)
        samples = mono_samples
    channels = 1

    # Measure current peak
    if not samples:
        info["before_peak_db"] = "-inf"
        info["after_peak_db"] = "-inf"
        return info

    current_peak = max(abs(s) for s in samples)
    if current_peak == 0:
        info["before_peak_db"] = "-inf"
        info["after_peak_db"] = "-inf"
        return info

    current_peak_db = 20 * math.log10(current_peak / 32768.0) if current_peak > 0 else -100
    info["before_peak_db"] = f"{current_peak_db:.2f}"

    # Calculate gain
    gain_linear = 10 ** (target_peak_db / 20.0) / (current_peak / 32768.0)
    gain_linear = min(gain_linear, 100.0)  # safety cap

    # Apply gain
    normalized = [int(max(-32768, min(32767, s * gain_linear))) for s in samples]

    # Measure after peak
    after_peak = max(abs(s) for s in normalized) if normalized else 0
    after_peak_db = 20 * math.log10(after_peak / 32768.0) if after_peak > 0 else -100
    info["after_peak_db"] = f"{after_peak_db:.2f}"

    # Resample to 16kHz if needed (simple linear interpolation)
    if sample_rate != 16000:
        ratio = 16000.0 / sample_rate
        new_length = int(len(normalized) * ratio)
        resampled = []
        for i in range(new_length):
            pos = i / ratio
            idx = int(pos)
            frac = pos - idx
            if idx + 1 < len(normalized):
                val = normalized[idx] * (1 - frac) + normalized[idx + 1] * frac
            else:
                val = normalized[idx] if idx < len(normalized) else 0
            resampled.append(int(max(-32768, min(32767, val))))
        normalized = resampled
        info["resampled_from"] = sample_rate
        info["resampled_to"] = 16000

    # Write output WAV
    with wave.open(output_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack(f'<{len(normalized)}h', *normalized))

    info["after_sample_rate"] = "16000"
    info["after_channels"] = "1"
    return info


# ---------------------------------------------------------------------------
# Quick check: is this already ASR-ready?
# ---------------------------------------------------------------------------

def get_audio_info_ffmpeg(filepath: str, ffmpeg: str) -> dict:
    """Get audio stream info via ffprobe."""
    probe_cmd = [
        ffmpeg.replace("ffmpeg", "ffprobe") if "ffprobe" not in ffmpeg else ffmpeg,
        "-v", "quiet", "-print_format", "json",
        "-show_streams", filepath
    ]
    # Try ffprobe first
    ffprobe_path = ffmpeg.replace("ffmpeg", "ffprobe")
    if not os.path.isfile(ffprobe_path):
        ffprobe_path = shutil.which("ffprobe") or ffmpeg

    cmd = [
        ffprobe_path, "-v", "quiet", "-print_format", "json",
        "-show_streams", filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return {
                    "sample_rate": int(stream.get("sample_rate", 0)),
                    "channels": int(stream.get("channels", 0)),
                    "codec": stream.get("codec_name", ""),
                    "duration": float(stream.get("duration", 0)),
                }
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def is_asr_ready_ffmpeg(filepath: str, target_lufs: float) -> bool:
    """Check if file is already 16kHz mono WAV and loudness is in range."""
    info = get_audio_info_ffmpeg(filepath, FFMPEG)
    if not info:
        return False

    is_16k_mono_wav = (
        info.get("sample_rate") == 16000 and
        info.get("channels") == 1 and
        info.get("codec") in ("pcm_s16le", "pcm_s16be", "wav")
    )
    if not is_16k_mono_wav:
        return False

    # Check loudness
    measured = measure_loudness_ffmpeg(filepath, FFMPEG)
    lufs_str = measured.get("input_i", None)
    if lufs_str is None:
        return False
    try:
        lufs = float(lufs_str)
        return -20 <= lufs <= -10
    except (ValueError, TypeError):
        return False


def is_asr_ready_python(filepath: str) -> bool:
    """Check if WAV file is 16kHz mono without ffmpeg."""
    info = parse_wav_info(filepath)
    if not info:
        return False
    return (
        info.get("sample_rate") == 16000 and
        info.get("channels") == 1 and
        filepath.lower().endswith('.wav')
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Audio loudness normalizer for ASR preprocessing (EBU R128)"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Input audio file (any supported format: wav/mp3/m4a/flac/etc.)"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="Output file path (always 16kHz mono WAV)"
    )
    parser.add_argument(
        "--target-lufs", type=float, default=-16.0,
        help="Target integrated loudness in LUFS (default: -16, speech-optimized)"
    )
    parser.add_argument(
        "--target-tp", type=float, default=-1.5,
        help="Target true peak in dBTP (default: -1.5)"
    )
    parser.add_argument(
        "--skip-if-ready", action="store_true", default=True,
        help="Skip processing if input is already ASR-ready (default: True)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force re-processing even if input appears ASR-ready"
    )

    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    target_lufs = args.target_lufs
    target_tp = args.target_tp

    # Validate input
    if not os.path.isfile(input_path):
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Create output directory if needed
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Print header
    print("=" * 60, file=sys.stderr)
    print("  Audio Loudness Normalizer (EBU R128)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Input:  {input_path}", file=sys.stderr)
    print(f"  Output: {output_path}", file=sys.stderr)
    print(f"  Target: {target_lufs} LUFS / {target_tp} dBTP", file=sys.stderr)
    print(f"  Format: 16kHz mono WAV (ASR-optimized)", file=sys.stderr)
    print(f"  FFmpeg: {FFMPEG or 'NOT FOUND'}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    # --- Check if already ASR-ready ---
    if args.skip_if_ready and not args.force:
        if FFMPEG:
            if is_asr_ready_ffmpeg(input_path, target_lufs):
                print(f"  ⏭ Input is already ASR-ready (16kHz mono, loudness OK)", file=sys.stderr)
                print(f"  → Copying directly to output", file=sys.stderr)
                shutil.copy2(input_path, output_path)
                print("=" * 60, file=sys.stderr)
                print("  ✅ Done (skipped - already normalized)", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                sys.exit(0)
        else:
            if is_asr_ready_python(input_path):
                print(f"  ⏭ Input is already 16kHz mono WAV", file=sys.stderr)
                shutil.copy2(input_path, output_path)
                print("=" * 60, file=sys.stderr)
                print("  ✅ Done (skipped - already 16kHz mono WAV)", file=sys.stderr)
                print("=" * 60, file=sys.stderr)
                sys.exit(0)

    # --- Normalize ---
    info = {}

    if FFMPEG:
        # Use ffmpeg for full EBU R128 normalization
        print("  🔊 Using ffmpeg EBU R128 two-pass normalization...", file=sys.stderr)
        try:
            info = normalize_ffmpeg(
                input_path, output_path, target_lufs, target_tp, FFMPEG
            )
        except Exception as e:
            print(f"  ⚠ EBU R128 normalization failed: {e}", file=sys.stderr)
            print(f"  → Falling back to simple format conversion", file=sys.stderr)
            cmd = [
                FFMPEG, "-hide_banner", "-nostats", "-y",
                "-i", input_path,
                "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                output_path
            ]
            subprocess.run(cmd, capture_output=True, text=True)
            info = {"method": "ffmpeg_fallback_simple"}
    else:
        # Pure Python fallback
        print("  ⚠ ffmpeg not found — using Python peak normalization", file=sys.stderr)
        print(f"  → Install ffmpeg for EBU R128 loudness normalization", file=sys.stderr)
        try:
            info = normalize_peak_python(
                input_path, output_path, target_peak_db=-3.0
            )
        except Exception as e:
            print(f"  ✗ Pure Python normalization failed: {e}", file=sys.stderr)
            sys.exit(1)

    # --- Print results ---
    print("-" * 60, file=sys.stderr)
    print(f"  Method:       {info.get('method', 'unknown')}", file=sys.stderr)
    if "before_lufs" in info:
        print(f"  Before:       {info['before_lufs']} LUFS (TP: {info.get('before_tp', 'N/A')} dBTP)", file=sys.stderr)
    if "after_lufs" in info:
        print(f"  After:        {info['after_lufs']} LUFS (TP: {info.get('after_tp', 'N/A')} dBTP)", file=sys.stderr)
    if "before_peak_db" in info:
        print(f"  Before peak:  {info['before_peak_db']} dB", file=sys.stderr)
    if "after_peak_db" in info:
        print(f"  After peak:   {info['after_peak_db']} dB", file=sys.stderr)
    if "resampled_from" in info:
        print(f"  Resampled:    {info['resampled_from']} → {info['resampled_to']} Hz", file=sys.stderr)

    # Verify output
    if os.path.isfile(output_path):
        out_size = os.path.getsize(output_path)
        if out_size > 0:
            print(f"  Output size:  {out_size / 1024:.1f} KB", file=sys.stderr)
        else:
            print(f"  ✗ Warning: Output file is empty!", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"  ✗ Error: Output file was not created!", file=sys.stderr)
        sys.exit(1)

    print("=" * 60, file=sys.stderr)
    print("  ✅ Normalization complete", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # Print output path to stdout for pipeline use
    print(output_path)


if __name__ == "__main__":
    main()
