import os
import json
import logging

logger = logging.getLogger(__name__)


def score_transcript(task_spec: dict, transcript_text: str) -> dict:
    """
    Phase 4: Score the student's transcript against the task truth table.
    Uses Google Gemini (gemini-2.0-flash) via GEMINI_API_KEY env var.
    Falls back to Anthropic if ANTHROPIC_API_KEY is set instead.
    Returns { score: float, passed: bool, reasoning: str }.
    """
    if not transcript_text or not transcript_text.strip():
        return {
            "score": 0.0,
            "passed": False,
            "reasoning": "No transcript available (audio was empty or missing)."
        }

    title = task_spec.get("title", "")
    description = task_spec.get("description", "")
    behavior = json.dumps(task_spec.get("expected_behavior", []), indent=2)

    prompt = f"""You are an automated grading assistant for a digital electronics lab.
The student was assigned the task '{title}': {description}.

The expected states or behavior to demonstrate are:
{behavior}

The student's video transcript is:
<transcript>
{transcript_text}
</transcript>

Based ONLY on the transcript, evaluate how well the student verbally described and demonstrated the required task behaviors:
- If the task description specifies key functional behaviors (e.g. counting, rollover, reset, button increments), evaluate whether those behaviors were explained.
- If the task specifies input->output combinations, evaluate how many of those combinations they verbally covered.

Respond with ONLY a JSON object, no other text:
{{
  "score": <float 0.0-1.0, fraction of required behaviors/states covered>,
  "passed": <true if score >= 0.7>,
  "reasoning": "<one or two sentences: what was demonstrated and what was missing>"
}}"""

    # Try new google-genai SDK first
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            import time
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            # Try models in order — newer first, fall back to stable aliases on 503
            MODELS_TO_TY = [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-flash-latest",
            ]
            last_err = None
            for model_name in MODELS_TO_TY:
                for attempt in range(2):
                    try:
                        chat = client.chats.create(model=model_name)
                        response = chat.send_message(
                            message=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.0,
                                response_mime_type="application/json",
                            )
                        )
                        result = json.loads(response.text.strip())
                        return {
                            "score": float(result.get("score", 0.0)),
                            "passed": bool(result.get("passed", False)),
                            "reasoning": result.get("reasoning", ""),
                            "model": model_name
                        }
                    except Exception as e:
                        last_err = e
                        err_str = str(e)
                        if "503" in err_str or "UNAVAILABLE" in err_str:
                            time.sleep(2 * (attempt + 1))
                            continue
                        elif "404" in err_str or "NOT_FOUND" in err_str:
                            break  # try next model
                        raise  # unexpected error — surface it
            raise last_err
        except Exception as e:
            logger.error(f"Gemini rubric error: {e}")
            return {"score": 0.0, "passed": False, "reasoning": f"Gemini error: {e}"}

    # Fallback: Anthropic Claude
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=anthropic_key)
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=300,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip().strip("```json").strip("```").strip()
            result = json.loads(text)
            return {
                "score": float(result.get("score", 0.0)),
                "passed": bool(result.get("passed", False)),
                "reasoning": result.get("reasoning", ""),
                "model": "claude-3-5-sonnet"
            }
        except Exception as e:
            logger.error(f"Anthropic rubric error: {e}")
            return {"score": 0.0, "passed": False, "reasoning": f"Anthropic error: {e}"}

    logger.warning("No LLM API key set (GEMINI_API_KEY or ANTHROPIC_API_KEY). Skipping rubric.")
    return {"score": 0.0, "passed": False, "reasoning": "No API key configured."}
