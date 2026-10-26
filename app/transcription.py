"""
Stage 2: Transcription

Wraps Whisper. Loaded once at module import so the model isn't re-loaded
per-request (that's the single biggest latency trap people hit when they
first wire Whisper into a web service).
"""

import whisper

# "small" is a reasonable accuracy/speed tradeoff to start with.
# Move to "medium" once you're validating on real submissions and want
# better accuracy on technical vocabulary (IC names, pin numbers, etc).
_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = whisper.load_model("small")
    return _MODEL


def transcribe(audio_path: str) -> dict:
    """
    Returns a timestamped transcript:
    {
      "text": "full transcript...",
      "segments": [{"start": 0.0, "end": 4.2, "text": "..."}]
    }

    Timestamps matter later: they let you correlate a spoken explanation
    ("now I'm setting the DIP switch to represent five") with the video
    frame/timestamp where that action visibly happens.
    """
    model = _get_model()
    result = model.transcribe(audio_path, fp16=False)
    return {
        "text": result["text"].strip(),
        "segments": [
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            }
            for seg in result["segments"]
        ],
    }
