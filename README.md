# POW Analyzer — Proof-of-Work Automated Grading System

> **Automatically analyze and grade student digital-electronics breadboard video submissions — no human in the loop.**

Built at **IIT Gandhinagar** for automated verification of lab proof-of-work submissions. Students submit a short video of their circuit and a top-down photo. The system runs a full multi-modal analysis pipeline and returns a PASS / BORDERLINE / FAIL decision with detailed reasoning.

---

## How It Works

```
Student Video + Board Photo
         │
         ▼
┌─────────────────────┐
│  1. Ingestion        │  ffmpeg audio extraction + 4fps frame sampling
│  2. Transcription    │  OpenAI Whisper (local, offline)
│  3. Display Reader   │  SIFT homography + 7-segment decoder
│                      │  (supports white-core & red LED displays)
│  4. Rubric Scoring   │  Gemini LLM evaluates transcript vs task spec
│  5. Decision Fusion  │  CV (20%) + Rubric (80%) → PASS/BORDERLINE/FAIL
│  6. Anti-Fraud       │  SIFT cross-match: video frame vs reference photo
└─────────────────────┘
         │
         ▼
   result.json  →  Portal (PHP / Next.js)
```

---

## Validated Results (Oct 2026)

Tested across **8 real student submissions** (digital clock + BCD decoder + AND gate):

| Task | Videos Tested | PASS | BORDERLINE | FAIL |
|---|:---:|:---:|:---:|:---:|
| Digital Clock (HH:MM:SS) | 6 | 4 | 1 | 1 |
| BCD to 7-Segment Decoder | 1 | 0 | 1 | 0 |
| AND Gate via DIP Switch | 1 | 0 | 0 | 1 |

Processing time: **~25 seconds per video** on CPU.

---

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/hemaxbhatt/POW-analyzer.git
cd POW-analyzer
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Run the server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Run the test suite
```bash
pytest test/test_verification.py test/test_state_reader.py test_dip_detector.py
# → 78 passed, 1 skipped
```

### 5. Test the full pipeline (local video)
Open `http://127.0.0.1:8000/test-ui` in your browser, or use the script:
```bash
python run_pipeline_test.py
```

---

## Docker Deployment

```bash
docker compose up -d --build
curl http://localhost:8000/health   # → {"status": "ok"}
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for full production setup.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `POST` | `/submissions/request-upload` | Get signed S3 upload URLs |
| `POST` | `/submissions/{id}/analyze` | Trigger pipeline (S3 flow) |
| `POST` | `/test/local-analyze` | Trigger pipeline (local files) |
| `GET` | `/submissions/{id}/result` | Poll for result |
| `GET` | `/submissions/export/csv` | Download full grading CSV |
| `GET` | `/tasks` | List available task IDs |

---

## Project Structure

```
├── app/
│   ├── main.py            # FastAPI entrypoint + all endpoints
│   ├── analysis.py        # Pipeline orchestrator (background job)
│   ├── ingestion.py       # ffmpeg audio + frame extraction
│   ├── transcription.py   # Whisper transcription
│   ├── state_reader.py    # 7-segment CV reader (SIFT + homography)
│   ├── dip_detector.py    # DIP switch detector
│   ├── verification.py    # Truth-table verification engine
│   ├── rubric.py          # Gemini/Claude LLM rubric evaluator
│   ├── fusion.py          # Decision fusion (CV + Rubric)
│   ├── anti_fraud.py      # Photo/video cross-match
│   └── storage.py         # AWS S3 integration
├── schemas/
│   ├── example_tasks.json # 5 task specifications
│   └── task_schema.json   # JSON schema for task definitions
├── test/
│   ├── test_verification.py
│   └── test_state_reader.py
├── test_dip_detector.py
├── Dockerfile
├── docker-compose.yml
├── DEPLOYMENT.md
└── requirements.txt
```

---

## Adding a New Task

Add an entry to [`schemas/example_tasks.json`](schemas/example_tasks.json):

```json
{
  "task_id": "task_06_half_adder",
  "title": "Half Adder",
  "description": "Student must demonstrate Sum and Carry outputs for all 4 input combinations.",
  "verification_mode": "state_match",
  "expected_behavior": [
    {"input": {"sw": "0000"}, "output": {"disp": "0"}},
    {"input": {"sw": "0001"}, "output": {"disp": "1"}},
    {"input": {"sw": "0010"}, "output": {"disp": "1"}},
    {"input": {"sw": "0011"}, "output": {"disp": "0"}}
  ],
  "grading": {"all_or_nothing": true},
  "metadata": {"unit": "Combinational Logic", "points": 10}
}
```

Restart the server to pick up the new task.

---

## Fusion Weights & Thresholds

Configured in [`app/fusion.py`](app/fusion.py):

| Parameter | Value | Rationale |
|---|---|---|
| `VIDEO_WEIGHT` | 0.20 | Hand occlusion makes CV unreliable on input switches |
| `RUBRIC_WEIGHT` | 0.80 | Verbal explanation is the strongest signal |
| `PASS_THRESHOLD` | 0.65 | Minimum fused score to PASS |
| `BORDERLINE_THRESHOLD` | 0.45 | Below PASS, above this → human review |

---

## Tech Stack

- **Python 3.11** — FastAPI, OpenCV, NumPy, Whisper, Ultralytics (YOLO)
- **Google Gemini API** — LLM rubric evaluator (with fallback chain)
- **Anthropic Claude** — Secondary LLM fallback
- **ffmpeg** — Audio extraction and frame sampling
- **AWS S3** — Production video/photo storage

---

## Limitations & Known Issues

- DIP switch visual reading is bypassed (hand occlusion); truth-table input verification relies on audio transcript
- 7-segment reader calibrated for standard kit displays; red LED displays are detected but orientation confidence may be low
- Anti-fraud requires a reference photo per submission; placeholder photo produces expected mismatch

---

*Project Madhava — IIT Gandhinagar, 2026*
