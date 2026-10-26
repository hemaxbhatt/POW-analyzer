"""
Decision Fusion (Phase 5): combines the computer-vision verification score
and the transcript rubric score into a final decision.

Decision logic:
  - video_score  = verification.score   (0.0-1.0, from truth-table checking)
  - rubric_score = rubric.score         (0.0-1.0, from LLM transcript scoring)
  - fused_score  = weighted average (video 60%, rubric 40%)
  - "pass" if fused_score >= PASS_THRESHOLD (0.75)
  - "borderline" if fused_score >= BORDERLINE_THRESHOLD (0.5)
  - "fail" otherwise
  
Special override rules:
  - If video_score == 1.0  → always PASS (CV saw every state correctly)
  - If video_score == 0.0 and rubric_score == 0.0 → always FAIL
  - If video_score < 0.2 and rubric_score < 0.3 → always FAIL
    (both signal and voice evidence absent)
"""

from __future__ import annotations

VIDEO_WEIGHT = 0.20
RUBRIC_WEIGHT = 0.80
PASS_THRESHOLD = 0.65
BORDERLINE_THRESHOLD = 0.45


def fuse(verification: dict, rubric: dict) -> dict:
    """
    Parameters
    ----------
    verification : dict
        Output of VerificationResult.to_dict() — must have 'score' and 'passed'.
    rubric : dict
        Output of rubric.score_transcript() — must have 'score' and 'passed'.

    Returns
    -------
    dict with keys:
        decision   : "pass" | "borderline" | "fail"
        fused_score: float
        video_score: float
        rubric_score: float
        reasoning  : str
    """
    video_score  = float(verification.get("score", 0.0))
    rubric_score = float(rubric.get("score", 0.0))

    # Override: perfect CV score → unconditional pass
    if video_score >= 1.0:
        decision = "pass"
        notes = "Computer-vision verified all truth-table entries (100%)."
    # Override: nothing at all → hard fail
    elif video_score < 0.2 and rubric_score < 0.3:
        decision = "fail"
        notes = (
            "Both video evidence (≥80% not verified) and verbal explanation "
            "(≥70% not mentioned) are insufficient."
        )
    else:
        fused = VIDEO_WEIGHT * video_score + RUBRIC_WEIGHT * rubric_score
        if fused >= PASS_THRESHOLD:
            decision = "pass"
        elif fused >= BORDERLINE_THRESHOLD:
            decision = "borderline"
        else:
            decision = "fail"
        notes = (
            f"Fused score {fused:.1%} "
            f"(video {video_score:.1%} × {VIDEO_WEIGHT:.0%} + "
            f"rubric {rubric_score:.1%} × {RUBRIC_WEIGHT:.0%}). "
            f"Threshold: pass≥{PASS_THRESHOLD:.0%}, "
            f"borderline≥{BORDERLINE_THRESHOLD:.0%}."
        )
        return {
            "decision": decision,
            "fused_score": round(fused, 4),
            "video_score": round(video_score, 4),
            "rubric_score": round(rubric_score, 4),
            "reasoning": notes,
        }

    # returned from the override branches
    fused = VIDEO_WEIGHT * video_score + RUBRIC_WEIGHT * rubric_score
    return {
        "decision": decision,
        "fused_score": round(fused, 4),
        "video_score": round(video_score, 4),
        "rubric_score": round(rubric_score, 4),
        "reasoning": notes,
    }
