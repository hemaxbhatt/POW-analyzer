"""
Pipeline orchestrator: ties the full analysis pipeline together.

Called as a background task by main.py's /analyze endpoint.  Runs:
  1. Download files from S3
  2. Extract audio + sample frames
  3. Transcribe audio (Whisper)
  4. Optional YOLO component detection
  5. State reader (video -> 7-segment observations)
  6. Verification (observations vs task truth table)
  7. Save result to disk (+ optional S3 upload)

This module is deliberately kept separate from main.py so it can be
tested in isolation and swapped to a Celery task later with minimal
changes.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TASKS_PATH = Path(__file__).resolve().parent.parent / "schemas" / "example_tasks.json"


# --------------------------------------------------------------------------
# Task spec loading
# --------------------------------------------------------------------------

_TASK_CACHE: dict | None = None


def _load_tasks() -> dict:
    """Load task specs from schemas/example_tasks.json.  Cached after first call."""
    global _TASK_CACHE
    if _TASK_CACHE is None:
        with open(TASKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        tasks = data if isinstance(data, list) else [data]
        _TASK_CACHE = {t["task_id"]: t for t in tasks}
        logger.info("Loaded %d task specs from %s", len(_TASK_CACHE), TASKS_PATH)
    return _TASK_CACHE


def get_available_task_ids() -> list[str]:
    """Return the list of task IDs we can verify against."""
    return list(_load_tasks().keys())


# --------------------------------------------------------------------------
# Result persistence
# --------------------------------------------------------------------------

def _result_path(submission_id: str) -> Path:
    return DATA_DIR / submission_id / "result.json"


def save_result(submission_id: str, result: dict) -> Path:
    """Write a result dict to data/{submission_id}/result.json."""
    p = _result_path(submission_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    return p


def load_result(submission_id: str) -> dict | None:
    """Read the result, or None if it doesn't exist yet."""
    p = _result_path(submission_id)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

def run_pipeline(
    student_id: str,
    submission_id: str,
    task_id: str,
) -> None:
    """
    Full analysis pipeline.  Designed to be called via
    ``background_tasks.add_task(run_pipeline, ...)``.

    Writes intermediate status updates to result.json so the polling
    endpoint can report progress.
    """
    result = {
        "submission_id": submission_id,
        "task_id": task_id,
        "status": "processing",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "stage": "downloading",
        "verification": None,
        "transcript_text": None,
        "reader_stats": None,
        "reader_warnings": None,
        "detection_status": None,
        "component_counts": None,
        "component_confidence": None,
        "error": None,
        "rubric": None,
        "fusion": None,
    }
    save_result(submission_id, result)

    try:
        # ── 1. Download from S3 ──────────────────────────────────────────
        from app.storage import download_submission_files

        result["stage"] = "downloading"
        save_result(submission_id, result)
        files = download_submission_files(student_id, submission_id)
        video_path = files["video_path"]
        job_dir = files["job_dir"]

        # ── 2. Audio extraction + frame sampling ─────────────────────────
        from app.ingestion import extract_audio, sample_frames

        result["stage"] = "extracting_audio"
        save_result(submission_id, result)
        audio_path = extract_audio(video_path, job_dir)
        frame_paths = sample_frames(video_path, job_dir)

        # ── 3. Transcription ─────────────────────────────────────────────
        from app.transcription import transcribe

        result["stage"] = "transcribing"
        save_result(submission_id, result)
        transcript = transcribe(audio_path)
        result["transcript_text"] = transcript["text"]

        # ── 4. Component detection (optional) ────────────────────────────
        result["stage"] = "detecting_components"
        save_result(submission_id, result)
        try:
            from app.detection import detect_components_multi_frame

            detection_result = detect_components_multi_frame(
                frame_paths + [files["photo_path"]]
            )
            result["component_counts"] = detection_result["component_counts"]
            result["component_confidence"] = detection_result["component_confidence"]
            result["detection_status"] = "ok"
        except FileNotFoundError:
            result["detection_status"] = "skipped_no_model"
        except Exception as e:
            result["detection_status"] = f"error: {e}"
            logger.warning("Detection failed: %s", e)

        # ── 5. State reader ──────────────────────────────────────────────
        from app.state_reader import read_video

        result["stage"] = "reading_display"
        save_result(submission_id, result)
        reader_result = read_video(video_path, sample_fps=4.0, max_displays=2)
        observations = reader_result.observations
        result["reader_stats"] = reader_result.stats
        result["reader_warnings"] = reader_result.warnings

        # Save raw observations alongside the result
        obs_path = Path(job_dir) / "observations.json"
        with open(obs_path, "w", encoding="utf-8") as f:
            json.dump(observations, f, indent=2, default=str)

        # ── 6. Verification ──────────────────────────────────────────────
        from app.verification import verify

        result["stage"] = "verifying"
        save_result(submission_id, result)

        tasks = _load_tasks()
        if task_id not in tasks:
            available = ", ".join(tasks.keys())
            raise ValueError(
                f"Unknown task_id '{task_id}'. "
                f"Available tasks: {available}"
            )
        task_spec = tasks[task_id]
        vr = verify(task_spec, observations)
        result["verification"] = vr.to_dict()

        # ── 7. Transcript Rubric Scoring (Phase 4) ───────────────────────
        result["stage"] = "rubric_scoring"
        save_result(submission_id, result)
        
        from app.rubric import score_transcript
        rubric_result = score_transcript(task_spec, result["transcript_text"])
        result["rubric"] = rubric_result

        # ── 8. Anti-fraud check (Phase 6) ────────────────────────────────
        result["stage"] = "anti_fraud_check"
        save_result(submission_id, result)
        
        from app.anti_fraud import verify_submission_match
        photo_path = files["photo_path"]
        result["anti_fraud"] = verify_submission_match(video_path, photo_path)

        # ── 9. Decision Fusion (Phase 5) ─────────────────────────────────
        from app.fusion import fuse
        fusion_result = fuse(result["verification"], rubric_result)
        result["fusion"] = fusion_result

        # ── Done ─────────────────────────────────────────────────────────
        result["status"] = "completed"
        result["stage"] = "done"
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        save_result(submission_id, result)
        logger.info(
            "Pipeline completed for %s: %s (cv=%.0f%% rubric=%.0f%% fused=%.0f%%)",
            submission_id,
            fusion_result["decision"].upper(),
            result["verification"]["score"] * 100,
            rubric_result["score"] * 100,
            fusion_result["fused_score"] * 100,
        )

    except Exception as e:
        result["status"] = "failed"
        result["stage"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        save_result(submission_id, result)
        logger.error(
            "Pipeline failed for %s: %s\n%s",
            submission_id,
            e,
            traceback.format_exc(),
        )
