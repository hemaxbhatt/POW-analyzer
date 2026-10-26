"""
Stage 1: Ingestion (direct-upload version)

Given a local video file path (already on disk, downloaded from Firebase
Storage by app/storage.py), produce:
  - an extracted audio track (for transcription)
  - a handful of candidate still frames (for later component detection)

NOTE: download_video() has been removed -- file acquisition now happens
via signed upload URLs; see app/storage.py.
"""

import subprocess
from pathlib import Path


def extract_audio(video_path: str, job_dir: str) -> str:
    """Extract a mono 16 kHz WAV -- the format Whisper expects."""
    audio_path = str(Path(job_dir) / "audio.wav")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-ac", "1", "-ar", "16000",
            audio_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return audio_path


def sample_frames(video_path: str, job_dir: str, target_fps: float = 4.0) -> list[str]:
    """
    Naive uniform frame sampling. Default is 6 fps to catch short windows
    where the student's hand moves away from the board.

    Replace with scene-change detection (e.g. ffmpeg's `select='gt(scene,0.4)'`
    filter) once the pipeline is working end-to-end -- uniform sampling wastes
    compute on redundant near-duplicate frames.
    """
    frames_dir = Path(job_dir) / "frames"
    frames_dir.mkdir(exist_ok=True)
    out_pattern = str(frames_dir / "frame_%04d.jpg")

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps={target_fps}",
            out_pattern,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return sorted(str(p) for p in frames_dir.glob("*.jpg"))
