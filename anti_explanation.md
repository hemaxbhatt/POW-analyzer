# POW Analyzer — Daily Progress Log (Antigravity)

*This file is maintained by Antigravity and updated each time a major task is completed. It serves as a living diary of what was built, what changed, and what comes next — focused on helping you pick up exactly where we left off.*

---

## 2026-09-30 — Session 2: Wiring Endpoints

### What we did in this session

**Wired the Async `POST /submissions/{id}/analyze` Endpoint**
Because processing a video takes ~105 seconds (too long for a regular HTTP response), we transitioned the analysis to a background task flow.

1. **Moved core modules to `app/`**: Copied `state_reader.py` into `app/` and replaced `app/verification.py` with the updated root copy (which adds support for `output_not_shown` for display-only tasks).
2. **Created `app/analysis.py`**: A new orchestrator module that chains everything together (S3 download -> audio extraction -> transcription -> YOLO detection -> state reader -> truth-table verification -> JSON result saving). It continuously updates a `result.json` file on disk with the current processing stage.
3. **Updated `app/main.py`**:
   - `POST /submissions/{submission_id}/analyze`: Now returns immediately and kicks off the background task.
   - `GET /submissions/{submission_id}/result`: New polling endpoint that the portal calls to retrieve the current processing status (`processing`, `completed`, `failed`), and the final VerificationResult once done.
4. **Dependency updates**: Added `opencv-python` and `numpy` to `requirements.txt`.
5. **Config cleanup**: Updated `.env.example` to correctly show the AWS S3 variables instead of the old Firebase variables.

### Environment Warning: Broken `venv`
During testing, I found that your virtual environment (`venv` folder) is broken. It was likely copied over from another machine or user account. It contains hardcoded paths pointing to `C:\Users\bhagy\AppData\Local\Programs\Python\Python311\python.exe`. 
You will need to delete the `venv` folder and recreate it on this machine to run the server.

---

## 2026-09-30 — Session 1: Baseline sync + file replacements

### What we did today

**Context catch-up**
Read `NEW_WORK_LOG.md` and `PROJECT_OVERVIEW.md` to get full project context. The POW Analyzer is a FastAPI microservice that automatically grades student-submitted breadboard videos by checking whether the observed component behavior (7-segment digits, LEDs, DIP switches) matches a task truth table.

**File replacements from `files/` → `madhava/`**

The `files/` folder at `D:\IITGN\files\` held the latest/canonical versions of 10 project files. All were copied into their proper places inside `madhava/`:

| Source (`files/`) | Destination (`madhava/`) | Notes |
|---|---|---|
| `PROJECT_OVERVIEW.md` | `madhava/PROJECT_OVERVIEW.md` | Technical reference, 15 KB |
| `disp_timeline.jpg` | `madhava/disp_timeline.jpg` | Visual timeline of display state from real test video |
| `state_reader.py` | `madhava/state_reader.py` | 7-segment frame reader — the main CV module |
| `verification.py` | `madhava/verification.py` | Truth-table verifier |
| `observations.json` | `madhava/observations.json` | Output from running state_reader on the real test video |
| `example_tasks.json` | `madhava/schemas/example_tasks.json` | 3 worked task specs (BCD decoder, AND gate, counter); now 7 KB, was 3.7 KB |
| `schema_notes.md` | `madhava/schemas/schema_notes.md` | Design decisions around the task schema |
| `task_schema.json` | `madhava/schemas/task_schema.json` | JSON Schema (draft 2020-12) for task specs |
| `test_state_reader.py` | `madhava/test/test_state_reader.py` | Pytest suite for state_reader |
| `test_verification.py` | `madhava/test/test_verification.py` | Pytest suite for verification (26 tests) |

`madhava/test/task_schema.json` was also synced so the test suite can resolve its schema reference locally.

---

### Current state of the project (as of end of session)

| Piece | Status |
|---|---|
| Truth-table schema (`task_schema.json`) | Done — in `schemas/` |
| Verification logic (`verification.py`) | Done — 26 tests passing |
| 7-segment state reader (`state_reader.py`) | Done — tested on real 44 s video |
| Real test video pipeline output | 6/10 digits verified; 4 hidden by hand |
| Background-job endpoint in `app/` | **Done — `/analyze` and `/result` endpoints wired** |
| DIP switch / push button / LED reading | Not started |
| Transcript rubric scoring (Phase 4) | Not started |
| Decision fusion (Phase 5) | Not started |
| Anti-fraud cross-match (Phase 6) | Not started |

---

### Folder layout (what is in `madhava/` right now)

```
madhava/
├── app/
│   ├── main.py              # FastAPI app
│   ├── analysis.py          # Background task orchestrator for pipeline
│   ├── ingestion.py         # S3 download, audio, frames
│   ├── transcription.py     # Whisper
│   ├── storage.py
│   ├── docs_ui.py
│   ├── detection.py         # YOLO component detection (optional)
│   ├── state_reader.py      # <- copied into app/
│   └── verification.py      # <- synced with root copy
├── schemas/
│   ├── task_schema.json     # <- updated from files/
│   ├── example_tasks.json   # <- updated from files/ (now 7 KB)
│   └── schema_notes.md      # <- updated from files/
├── test/
│   ├── task_schema.json     # local copy for test imports
│   ├── test_state_reader.py # <- updated from files/
│   └── test_verification.py # <- updated from files/
├── training/
│   └── train.py
├── state_reader.py          # <- updated from files/ (21 KB)
├── verification.py          # <- updated from files/ (20 KB)
├── observations.json        # <- updated from files/ (25 KB output)
├── disp_timeline.jpg        # <- updated from files/
├── PROJECT_OVERVIEW.md      # <- updated from files/
├── example_tasks.json       # STALE root-level copy — canonical is in schemas/
├── direct-upload-implementation-plan.md
├── README.md, requirements.txt, .env, .gitignore, storage.rules
└── data/                    # per-submission working files (videos, frames, audio, result.json)
```

---

### Next priorities (in order)

1. **Recreate your Virtual Environment**: The current `venv` is broken and points to another user's machine paths (`bhagy`). You must recreate it to run the server.
2. Raise frame sampling rate in ingestion to ~5–6 fps (currently 1 frame per 3 s — misses short display windows).
3. Hand-label the test video to measure state_reader accuracy against human ground truth.
4. Phase 4: Transcript rubric scoring via LLM.
5. Phase 5: Decision fusion (verification score + rubric score → approve / reject / send to human).
6. Phase 6: Photo/video anti-fraud cross-match.

---

*Updated by Antigravity — 2026-09-30 21:26 IST*

---

## 2026-10-03 — Session 3: DIP Switch Integration

### What we did in this session

**Phase 3: DIP Switch Reading — integrated into the pipeline**

The previous session ended with the pipeline scoring **0% (0/10)** on `task_04_bcd_to_7seg_decoder` because `state_reader.py` was outputting `"inputs": {}` — it could read 7-segment displays but had no code to read the DIP switch inputs.

#### Work completed

1. **User wrote `dip_detector.py`** — A lever-cluster-based DIP switch detector. Instead of relying on red blob shape alone (which matched red jumper wire tangles), it uses a sliding window over white blobs inside red candidates to find 3–6 evenly-spaced, similarly-sized levers.

2. **User wrote `test_dip_detector.py`** — A synthetic pytest suite that verifies the detector against pixel-perfect distractor images (wires, ICs, glare). No real image required.

3. **Moved `dip_detector.py` → `app/dip_detector.py`** and integrated into the pipeline.

4. **Integrated DIP reading into `app/state_reader.py`**:
   - `find_dip_switch()` is called across all 40 cached frames; the candidate with the most levers wins.
   - The DIP switch ROI is warped per-frame using the same SIFT homography as the 7-segment displays (canonical coordinate space).
   - `read_state()` is called on each warped crop and the result written into `observations[i]["inputs"]["sw"]`.

5. **Calibration fixes made during live testing**:
   - Relaxed `LEVER_SIZE_SPREAD` from 0.45 → 3.5 to tolerate video compression artifacte.
   - Added `MIN_BOX_W / MIN_BOX_H` (40×20 px) to reject tiny high-solidity false positives.
   - Reweighted scoring: `score = 0.3 × levers + solidity` so a real 4-lever switch always beats tiny noise.
   - FLipped bit convention: `0` = lever UP (switch OFF), `1` = lever DOWN (switch ON).
   - Fixed coord inate system for DIP crops to use canonical-space homography.
   - Best-levers selection: scans all 40 cached frames and keeps the candidate with the most levers.

6. **End-to-end test run results**:
   - Session started at **0% (0/10)**
   - After integration + calibration: **10% (1/10)** — `sw=0000 → disp=0` correctly verified ✅
   - **Ongoing**: lever boxes are stacked vertically (column axis, all `lx≈22`, varying `ly`). Axis/ordering fix in progress.

#### Files changed this session

| File | Change |
|---|---|
| `app/dip_detector.py` | **NEW** — moved from root; multiple calibration tweaks |
| `app/state_reader.py` | Integrated DIP reading (import, find, warp, read, output) |
| `debug_dip.py` – `debug_dip6.py` | Scratch debug scripts |
| `debug_result.py` | Scratch: parse verification result |

#### Current state of the project

| Piece | Status |
|---|---|
| Truth-table schema | ✅ Done |
| Verification logic | ✅ Done |
| 7-segment state reader | ✅ Done |
| Async `/analyze` + `/result` endpoints | ✅ Done |
| DIP switch detection (`dip_detector.py`) | ✅ Integrated |
| DIP switch reading accuracy | 🔧 In progress — axis/ordering fix needed |
| Transcript rubric scoring (Phase 4) | Not started |
| Decision fusion (Phase 5) | Not started |
| Anti-fraud cross-match (Phase 6) | Not started |

#### Fixes implemented during debug (Part 2)

7. **Pipeline Scan Fix**: `read_video` was prematurely aborting its candidate scan after finding the first lit 7-segment display (at frame 12). This prevented it from finding the DIP switch at frame 14 (when the user's hand moves away). Fixed Pass 1 to unconditionally cache and scan the first 40 frames.
8. **MAX_LEVERS Restricted**: Reduced `MAX_LEVERS` from 6 to 4. The student's board uses a 4-position switch; allowing 6 levers was causing 5-lever noise blobs (like wire tangles) to artificially outscore the real switch.
9. **Canonical Coordinate Mapping**: Discovered a major coordinate space bug. The DIP switch was being found in frame 14, but its bounding box was being applied to the SIFT homography as if it were in the reference frame's space (frame 12). This caused the pipeline to track an empty patch of breadboard instead of the switch. Used `cv2.perspectiveTransform` to mathematically map the DIP candidate box into the canonical reference space before generating crops.

#### Next immediate step

Investigate the SIFT-tracked crops. Even after mapping the coordinates into canonical space, the bit readings are noisy. Need to dump the pipeline's DIP crops to disk (`cv2.imwrite`) to visually inspect if the homography warp is successfully tracking the switch, or if it's drifting due to the portrait orientation of the camera.

---

*Updated by Antigravity — 2026-10-03 23:41 IST*

---

## 2026-10-05 — Session 4: Environment Repair + Phase 4 & 5 Built

### Context

New laptop / new machine. All paths changed. The `venv` was broken (pointed to old machine's Python at `C:\Users\bhagy\...`). Python 3.14 is now the system default — but the project requires **Python 3.11** (whisper build breaks on 3.14).

### Environment fixes

1. Deleted the broken `venv`.
2. Recreated it explicitly with `py -3.11 -m venv venv`.
3. Upgraded `pip`, `setuptools`, `wheel` inside the new venv first.
4. Installed all deps via `.\venv\Scripts\python.exe -m pip install -r requirements.txt` — succeeded cleanly on Python 3.11.
5. Installed `pytest` separately (wasn't in requirements.txt).
6. Installed `anthropic` for Phase 4 (uncommented from requirements.txt).

**Test suite after repair:** 58 passed, 1 skipped ✅

### DIP switch investigation

Ran `debug_pipeline.py` on `ApexNode_23110001_1.2.mp4`. The pipeline outputs fully random bit patterns every 168 ms. Added DIP crop dumps (`dip_crop_NNN.jpg`) to `debug_out/` via `debug_dir`. Visually inspected: **the SIFT tracker IS correctly centering the switch** — the coordinate mapping is not drifting. The noise is caused by the student's **hand completely covering the switch** during every flip, so the detector sees skin/shadow pixels instead of lever whites.

**Decision:** Drop DIP switch visual reading. Pivot to verifying circuit behavior via **audio/transcript** instead.

### Phase 4 built — `app/rubric.py`

New module: `score_transcript(task_spec, transcript_text) → dict`

- Calls **Claude 3.5 Sonnet** via the Anthropic API.
- Sends the task's truth table + the Whisper transcript.
- LLM evaluates what fraction of expected input→output combinations the student verbally described.
- Returns `{ score: float, passed: bool, reasoning: str }`.
- Gracefully skips (score=0) if `ANTHROPIC_API_KEY` is not set.

`ANTHROPIC_API_KEY` must be added to `.env` (documented in `.env.example`).

### Phase 5 built — `app/fusion.py`

New module: `fuse(verification_dict, rubric_dict) → dict`

Weighted fusion of CV + LLM signals:
- **Video (CV):** 60% weight — **Rubric (LLM):** 40% weight
- **Pass** ≥ 75%, **Borderline** ≥ 50%, **Fail** otherwise
- Override: CV = 100% → always Pass; both CV < 20% and rubric < 30% → always Fail

Returns `{ decision, fused_score, video_score, rubric_score, reasoning }`.

### Pipeline wiring — `app/analysis.py`

- Added `rubric` and `fusion` to initial `result` schema.
- Phase 4 wired as **stage 7** (`rubric_scoring`) after verification.
- Phase 5 wired as **stage 8** immediately after.
- Completion log now reports CV %, rubric %, and fused %.

### Test helper added

`test_rubric_fusion.py` — loads latest `data/*/result.json`, runs rubric + fusion on the real transcript, prints all scores.
Run: `.\venv\Scripts\python.exe test_rubric_fusion.py`

### Current state of the project

| Piece | Status |
|---|---|
| Truth-table schema | ✅ Done |
| Verification logic | ✅ Done (58 tests passing) |
| 7-segment state reader | ✅ Done |
| Async `/analyze` + `/result` endpoints | ✅ Done |
| DIP switch visual reading | ⚠️ Abandoned — hand occlusion too severe |
| Phase 4: Transcript rubric scoring | ✅ Built — needs `ANTHROPIC_API_KEY` in `.env` |
| Phase 5: Decision fusion | ✅ Built — wired into pipeline |
| End-to-end Phase 4+5 test | ⏳ Pending — needs API key |
| Phase 6: Anti-fraud cross-match | Not started |

### Next steps (in order)

1. Add `ANTHROPIC_API_KEY` to `.env` and run `test_rubric_fusion.py`.
2. Evaluate rubric quality — does the LLM extract what the student verbally demonstrated correctly?
3. Tune fusion weights / thresholds based on real results.
4. Consider switching rubric LLM to Gemini (`google-generativeai`) to avoid a separate API key.
5. Phase 6: Anti-fraud photo/video cross-match.

---

*Updated by Antigravity — 2026-10-05 12:20 IST*

---

## 2026-10-06 — Session 5: Phase 4 + 5 End-to-End Test (Working)

### What we did

**Got Phase 4 (transcript rubric scoring) fully working end-to-end on the real transcript.**

#### API key + SDK journey
- User provided Gemini API key from AI Studio (non-standard `AQ.` format, not `AIzaSy`).
- First attempt failed: I had incorrectly prefixed the key with `AIzaSy` when writing to `.env`.
- Fixed `.env` to have the correct raw key.
- `google-generativeai` is now **deprecated** — migrated to the new `google-genai` SDK (`google.genai`).
- `gemini-2.0-flash` and `gemini-2.5-flash` are no longer available to this key → must use `gemini-3.8-flash`.
- `gemini-3.8-flash` returns 503 intermittently due to load → added a **model fallback chain**:
  1. `gemini-3.8-flash` (try twice with backoff)
  2. `gemini-3.7-flash`
  3. `gemini-3.6-flash`
  4. `gemini-flash-latest`
- First successful model hit: `gemini-3.7-flash` (3.8 was overloaded, fell through to 3.7).

#### Results on real submission

Transcript (457 chars): *"Over here we have implemented a BCD to 7 segment decoder. As you can see right now all the switches are off so it is just playing 0 and over here 1 is the MSB and 4 is the LSB. So when I turn on the s..."*

| Signal | Score | Note |
|---|---|---|
| CV verification | 10% | Only `sw=0000→disp=0` confirmed; DIP unreadable due to hand occlusion |
| Rubric (LLM) | 60% | "Student demonstrated 6/10 BCD values (0, 1, 3, 7, 8, 9) but skipped 2, 4, 5, 6" |
| **Fused decision** | **30% → FAIL** | Below 50% borderline threshold |

**The LLM result is accurate** — matches manual observation from the `disp_timeline.jpg` exactly. The student showed ~6 digits and skipped the rest.

#### Files changed

| File | Change |
|---|---|
| `app/rubric.py` | Migrated to `google-genai` SDK; added model fallback chain (3.8→3.7→3.6→flash-latest) with 503 retry |
| `app/main.py` | Added `rubric` and `fusion` fields to `SubmissionResult` model (Bug B1 from audit) |
| `requirements.txt` | Switched from `google-generativeai` → `google-genai`; added `pytest` |
| `.env` | Correct Gemini API key written |
| `.env.example` | Documents both `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` |

### Current state of the project

| Piece | Status |
|---|---|
| Truth-table schema | ✅ Done |
| Verification logic | ✅ Done (58 tests passing) |
| 7-segment state reader | ✅ Done |
| Async `/analyze` + `/result` endpoints | ✅ Done |
| DIP switch visual reading | ⚠️ Abandoned — hand occlusion |
| Phase 4: Transcript rubric scoring | ✅ **Working on real data** — 60% score, correct |
| Phase 5: Decision fusion | ✅ **Working on real data** — FAIL (30%), correct |
| API response includes rubric + fusion | ✅ Fixed (Bug B1) |
| Phase 6: Anti-fraud cross-match | Not started |
| YOLO component detection | Not started (no trained model) |

### Next steps

1. **Tune fusion weights/thresholds** — currently 60%/40% and 75%/50%. With the CV signal this broken (10%), the rubric dominates. May want to increase rubric weight or lower the pass threshold until YOLO or DIP reading improves.
2. **Run the full pipeline end-to-end** via the API (`POST /analyze`) to confirm the new stages 7+8 work in the background job context. — ✅ **Done**: added `/test-ui` and `/test/local-analyze` for local testing. Verified it runs successfully end-to-end.
3. **Phase 6**: Anti-fraud photo/video cross-match.
4. **Fix the AFC warning** from the `google-genai` SDK (recommend using `Chat.send_message` instead of `Models.generate_content` for tool-calling — doesn't affect us but produces noise in logs).

---

*Updated by Antigravity — 2026-10-06 12:15 IST*


---

## 2026-10-14 — Session 6: Anti-Fraud Tested, Test Suite Repaired, New Videos & Hardware Discrepancies

### What we did in this session

1. **Repaired & Validated Unit Test Suite:**
   - Fixed broken import paths in `test_dip_detector.py` (`from app.dip_detector...`).
   - Fixed assertions for inverted bit convention (0 = UP, 1 = DOWN) in `test_dip_detector.py`.
   - Renamed `test_api.py` to `run_api_test.py` to prevent pytest collection failures.
   - Result: **76 tests passed, 1 skipped**.

2. **Fusion Weights Tuned & SDK AFC Warning Addressed:**
   - Updated `app/fusion.py`: Video 20% / Rubric 80%, Pass threshold 65%, Borderline 45%.
   - Updated `app/rubric.py`: Switched to `client.chats.create().send_message()` to suppress SDK AFC warning.

3. **Phase 6 (Anti-Fraud Cross-Match) Validated:**
   - Tested `app/anti_fraud.py` on `ApexNode_23110001_1.2.mp4` + `board.jpg`.
   - Passed with 142 structural inliers (threshold >= 40) and match score of 0.55.

4. **Tested Full Pipeline on New Student Footage:**
   - Evaluated `DIGITAL_NEXUS_25110041_VIDEO_1.mp4`: Correctly flagged wrong task (student demonstrated an AND gate instead of BCD decoder) and mismatched board (only 14 inliers vs placeholder photo).
   - Inspected `TheMultiplexers_25110049_CLOCK.mp4`: Audio transcription revealed a 6-display digital clock powered by a 555 timer.
   - Added `task_05_digital_clock` to `schemas/example_tasks.json`.

5. **Discovered Display Hardware Incompatibility:**
   - Pipeline crashed on clock video: `ValueError: could not find a lit 7-segment display in any clear frame`.
   - Visual frame extraction confirmed the clock uses **red LED segments**, whereas `app/state_reader.py` requires **white segment cores with red halos**.
   - Identified that `state_reader.py` needs to fail gracefully (returning 0% CV score rather than crashing) when unknown hardware is presented.

6. **Action Items Catalogued:**
   - Documented all open hardware, task mapping, and infrastructure questions in `QUESTIONS_TO_ASK.md`.

### Current state of the project

| Piece | Status |
|---|---|
| Truth-table schema & test tasks | ✅ Done (`schemas/example_tasks.json` has 5 tasks) |
| Verification logic | ✅ Done (76 tests passing) |
| 7-segment state reader | ⚠️ Calibrated for white-core displays only; crashes on red LEDs |
| Async `/analyze` + `/result` endpoints | ✅ Done |
| Phase 4: Transcript rubric scoring | ✅ Working (Gemini with fallback chain) |
| Phase 5: Decision fusion | ✅ Tuned (20% CV / 80% Rubric) |
| Phase 6: Anti-fraud cross-match | ✅ Validated on real pair (142 inliers) |
| Graceful state reader fallback | ❌ Pending (needs to return empty obs instead of crashing) |

---

*Updated by Antigravity — 2026-10-14 15:20 IST*


---

## 2026-10-21 — Session 7: Graceful Fallback Implemented, Root/App State Reader Synced, Generalized Rubric Evaluator, and Clock Video Pass Verified

### What we did in this session

1. **Pre-Check Baseline & Regression Protection:**
   - Ran pytest baseline: verified all 76 unit tests passed.
   - Tested backward compatibility of `app.state_reader.read_video` on real `ApexNode_23110001_1.2.mp4` footage (verified it still extracts 269 frames and 1 display cleanly).

2. **Implemented Graceful CV Fallback:**
   - Patched `app/state_reader.py`: Replaced fatal `ValueError: could not find a lit 7-segment display in any clear frame` with a graceful warning and structured empty observations.
   - Aligned display count parameter: Updated `app/main.py` (`max_displays=2`) to match `app/analysis.py`.
   - Synced legacy root `state_reader.py` to forward directly to `app.state_reader`.
   - Added unit test `test_read_video_graceful_fallback_when_no_display` in `test/test_state_reader.py`. Test suite increased to **77 passed, 1 skipped**.

3. **Generalized Transcript Rubric Evaluator:**
   - Updated `app/rubric.py` prompt: Enabled the evaluator to grade both combinational truth-table inputs and rich sequential/functional task descriptions (such as clock rollover, 555-timer frequency speedup, manual minutes/hours buttons, and reset buttons).

4. **End-to-End Verification of Clock Video (`TheMultiplexers_25110049_CLOCK.mp4`):**
   - Triggered pipeline via `POST /test/local-analyze` for `task_05_digital_clock`.
   - Video processed end-to-end without crashing:
     - CV: Gracefully degraded to 0% with warning logged.
     - Rubric: Evaluated all 5 sequential behaviors and awarded **100%**.
     - Anti-fraud: Correctly flagged mismatch (8 inliers vs placeholder `board.jpg`).
     - Fusion: Evaluated final decision as **PASS (80% fused score)**.

### Current state of the project

| Piece | Status |
|---|---|
| Truth-table schema & test tasks | ✅ Done (`schemas/example_tasks.json` has 5 tasks) |
| Verification logic | ✅ Done (77 unit tests passing) |
| 7-segment state reader | ✅ Working on white-core displays; degrades gracefully on red LEDs |
| Async `/analyze` + `/result` endpoints | ✅ Done |
| Phase 4: Transcript rubric scoring | ✅ Working (handles both truth tables & sequential behaviors) |
| Phase 5: Decision fusion | ✅ Working (20% CV / 80% Rubric, PASS at 80% on clock demo) |
| Phase 6: Anti-fraud cross-match | ✅ Working (differentiates matching vs mismatched boards) |

---

*Updated by Antigravity — 2026-10-21 11:35 IST*


---

## 2026-10-21 — Session 8: Red LED Computer Vision Detection & Batch-Run Validation on 6 Real Student Clock Videos

### What we did in this session

1. **Implemented Red LED Dual-Mode Display Finder & Segment Scoring:**
   - Modified `find_displays()` in `app/state_reader.py`: Added pure red LED detection ($R \ge 180, R-G \ge 55, R-B \ge 55$) as a fallback if no white-core displays are found.
   - Updated `segment_scores()` in `app/state_reader.py`: Dynamically detects high red dominance ($R - \max(G, B) > 25.0$) and scales the red intensity difference to compute segment scores.
   - Preserved 100% backward compatibility for white-core displays (ApexNode / BCD kit).
   - Added unit test `test_red_led_segment_scores` in `test/test_state_reader.py`. Total test count: **78 passed, 1 skipped**.
   - Verified on real clock footage: registered 266 of 289 frames (92%) and localized 2 displays.

2. **Executed Full Automated Batch Evaluation on All 6 Clock Submissions:**
   - Evaluated 6 student videos sequentially with zero crashes:
     - `TheMultiplexers_25110049_CLOCK`: **PASS** (80.0% fused score, 100% rubric).
     - `Gatekeepers_AS_25110019_Clock`: **FAIL** (32.0% fused score, 40% rubric — student incorrectly reset seconds at 15 and omitted hours rollover).
     - `Logic_Mates_25110074_CLOCK`: **PASS** (76.0% fused score, 95% rubric).
     - `Nanometers_25110162_Clock`: **PASS** (72.0% fused score, 90% rubric).
     - `AAJ_Tak_25110140_CLOCK`: **BORDERLINE** (64.0% fused score, 80% rubric — omitted hours rollover to 12).
     - `threeBits_25110268_CLOCK`: **PASS** (72.0% fused score, 90% rubric).
   - Saved report to `batch_clock_results.md`.

### Current state of the project

| Piece | Status |
|---|---|
| Truth-table schema & test tasks | ✅ Done (`schemas/example_tasks.json` has 5 tasks) |
| Verification logic | ✅ Done (78 unit tests passing) |
| 7-segment state reader | ✅ Supports both white-core displays & pure red LED displays |
| Async `/analyze` + `/result` endpoints | ✅ Done |
| Phase 4: Transcript rubric scoring | ✅ Validated across 6 real student videos |
| Phase 5: Decision fusion | ✅ Successfully classified PASS (4), BORDERLINE (1), and FAIL (1) |
| Phase 6: Anti-fraud cross-match | ✅ Correctly flagged non-matching placeholder photo on all 6 videos |
| Batch evaluation | ✅ Done on all available clock submissions |

---

*Updated by Antigravity — 2026-10-21 13:40 IST*


---

## 2026-10-22 — Session 9: AND Gate Evaluation & Production Dockerization

### What we did in this session

1. **Option 1: AND Gate True Task Evaluation (`DIGITAL_NEXUS`):**
   - Evaluated `DIGITAL_NEXUS_25110041_VIDEO_1.mp4` against its actual task: `task_02_dip_led_and_gate`.
   - Result:
     - Fused Score: **32.0% (FAIL)**
     - Rubric Score: **40.0%** — LLM evaluator correctly recognized the student mentioned the NAND IC and inputs A/B, but failed to demonstrate or state the LED output (off vs on) for each truth table state.
     - Anti-Fraud: **14 inliers (Mismatch)** against placeholder board photo.
   - All 8 student videos in `D:\IITGN\videos\` have now been evaluated against their true target tasks!

2. **Option 2: Production Readiness & Dockerization:**
   - Created production-grade [`Dockerfile`](file:///d:/IITGN/madhava/Dockerfile) based on `python:3.11-slim` with system `ffmpeg`, `libgl1`, and healthcheck.
   - Created [`.dockerignore`](file:///d:/IITGN/madhava/.dockerignore) to prevent copying videos and caches into images.
   - Created [`docker-compose.yml`](file:///d:/IITGN/madhava/docker-compose.yml) mapping port 8000, environment file, and persistent volume for `data/`.
   - Created [`DEPLOYMENT.md`](file:///d:/IITGN/madhava/DEPLOYMENT.md) with quick start, API integration guide, and disk retention commands.
   - Verified unit tests: **78 passed, 1 skipped** with zero regressions.

---

*Updated by Antigravity — 2026-10-22 13:05 IST*


---

## 2026-10-22 to 2026-10-26 — Session 10: CSV Export, Speed Optimisation & Git v1.0 Checkpoint

### What we did in this session

1. **Instructor CSV Export Endpoint:**
   - Added `GET /submissions/export/csv` to `app/main.py`.
   - Scans all `data/*/result.json` files and returns a `text/csv` download with columns: `submission_id, student_id, task_id, status, decision, fused_score, cv_score, rubric_score, anti_fraud_match, anti_fraud_inliers, created_at, rubric_reason`.
   - Verified: 200 status, correct `Content-Disposition: attachment; filename=submissions_summary.csv` header, 22 data rows returned.

2. **Processing Speed Optimisation (3x speedup):**
   - Benchmarked frame sampling: 269 frames at 6fps took ~105s; 179 frames at 4fps took **25.17s** on the same video.
   - Lowered default `sample_fps` from 6.0 → **4.0** in:
     - `app/state_reader.py` (`read_video` default)
     - `app/analysis.py` (pipeline call)
     - `app/main.py` (local test endpoint call)
     - `app/ingestion.py` (`sample_frames` default)
   - Verified all 78 unit tests still pass after the change.

3. **Repository Clean-Up & Git Checkpoint (v1.0):**
   - Moved 18 debug/scratch `.py` files to `scratch/` folder.
   - Created `.gitignore` covering: venv, `__pycache__`, `data/`, videos, debug images, and OS artefacts.
   - `git init` → staged 41 source/doc/config files → committed as `feat: Milestone v1 — full automated grading pipeline`.
   - Tagged as `v1.0`.

### Current state of the project

| Piece | Status |
|---|---|
| Git repository | ✅ Initialized, v1.0 tagged |
| Instructor CSV export | ✅ `GET /submissions/export/csv` working |
| Frame sampling speed | ✅ 4fps default — ~25s/video (~3x speedup) |
| All 78 unit tests | ✅ Passing |

---

*Updated by Antigravity — 2026-10-26 07:18 IST*
