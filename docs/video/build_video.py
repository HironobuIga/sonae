"""Assemble the Sonae demo video.

    AWS_PROFILE=... python docs/video/build_video.py [--voice Danielle] [--engine generative]

Pipeline: narration.json → Amazon Polly per segment → ffprobe durations →
each segment's visuals share its narration time → ffmpeg stills-to-video
concat + audio concat → docs/video/sonae-demo.mp4 (1080p30, ≤5 min).

Frames: slide_*.png are 3840x2160 (scaled), cap_*.png are 3200x1882 raw UI
captures (cropped to 16:9 from the top, then scaled).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
FRAMES = HERE / "frames"
AUDIO = HERE / "audio"
WORK = HERE / "work"
OUT = HERE / "sonae-demo.mp4"

GAP = 0.8  # breathing room between segments (s) — a beat to absorb each one
LEAD_IN = 0.6
MIN_PER_VISUAL = 2.4
FPS = 30


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd[:6])}…")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def synthesize(segments: list[dict], voice: str, engine: str) -> None:
    AUDIO.mkdir(exist_ok=True)
    for seg in segments:
        mp3 = AUDIO / f"{seg['id']}.mp3"
        if mp3.exists():
            continue
        print(f"polly: {seg['id']} ({len(seg['text'])} chars)")
        run([
            "aws", "polly", "synthesize-speech",
            "--engine", engine, "--voice-id", voice,
            "--output-format", "mp3", "--sample-rate", "24000",
            "--text", seg["text"], str(mp3),
        ])


def main() -> None:
    voice = sys.argv[sys.argv.index("--voice") + 1] if "--voice" in sys.argv else "Danielle"
    engine = sys.argv[sys.argv.index("--engine") + 1] if "--engine" in sys.argv else "generative"

    spec = json.loads((HERE / "narration.json").read_text())
    segments = spec["segments"]
    synthesize(segments, voice, engine)

    WORK.mkdir(exist_ok=True)
    video_parts: list[Path] = []
    audio_parts: list[Path] = []

    silence = WORK / "silence.m4a"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", str(GAP), "-c:a", "aac", str(silence)])
    lead = WORK / "lead.m4a"
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", str(LEAD_IN), "-c:a", "aac", str(lead)])
    audio_parts.append(lead)

    total = LEAD_IN
    for seg in segments:
        mp3 = AUDIO / f"{seg['id']}.mp3"
        dur = probe_duration(mp3)
        visuals = seg["visuals"]
        seg_time = max(dur, MIN_PER_VISUAL * len(visuals)) + GAP
        per = seg_time / len(visuals)
        print(f"{seg['id']}: {dur:5.1f}s narration, {len(visuals)} visual(s) × {per:4.1f}s")
        for i, vis in enumerate(visuals):
            img = FRAMES / f"{vis}.png"
            if not img.exists():
                raise SystemExit(f"missing frame: {img}")
            part = WORK / f"{seg['id']}_{i}.mp4"
            import struct

            with open(img, "rb") as fh:
                w, h = struct.unpack(">II", fh.read(33)[16:24])
            if (w, h) == (1920, 1080) or abs(w / h - 16 / 9) < 0.01:
                vf = "scale=1920:1080"
            elif w >= 3200 and h >= 1800:
                vf = "crop=3200:1800:0:0,scale=1920:1080"  # raw UI capture, top-anchored 16:9
            else:
                vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#05080f"
            run(["ffmpeg", "-y", "-loop", "1", "-t", f"{per:.3f}", "-i", str(img),
                 "-vf", vf + ",format=yuv420p", "-r", str(FPS),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(part)])
            video_parts.append(part)
        # segment audio + trailing gap (and padding if visuals forced extra time)
        pad = seg_time - dur - GAP
        seg_audio = WORK / f"{seg['id']}.m4a"
        run(["ffmpeg", "-y", "-i", str(mp3), "-af", f"apad=pad_dur={max(pad,0)+GAP:.3f}",
             "-c:a", "aac", "-ar", "24000", str(seg_audio)])
        audio_parts.append(seg_audio)
        total += seg_time

    print(f"total runtime ≈ {total/60:.1f} min")
    if total > 300:
        print("WARNING: over 5 minutes — trim narration!", file=sys.stderr)

    vlist = WORK / "video.txt"
    vlist.write_text("".join(f"file '{p.name}'\n" for p in video_parts))
    alist = WORK / "audio.txt"
    alist.write_text("".join(f"file '{p.name}'\n" for p in audio_parts))

    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist),
         "-c", "copy", str(WORK / "video_all.mp4")])
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alist),
         "-c", "copy", str(WORK / "audio_all.m4a")])
    run(["ffmpeg", "-y", "-i", str(WORK / "video_all.mp4"), "-i", str(WORK / "audio_all.m4a"),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
         "-movflags", "+faststart", str(OUT)])
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.1f} MB, {probe_duration(OUT):.0f}s)")


if __name__ == "__main__":
    main()
