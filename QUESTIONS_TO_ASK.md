# POW Analyzer — Open Questions & Improvements Needed

*Created: 2026-10-14. Answer these to make the system production-ready.*

---

## 🔴 CRITICAL — Blockers for Real Use

### 1. Display Hardware Variety
**Problem:** The state reader only detects white/yellow segment displays (BCD decoder kit). The digital clock kit uses **red LED segments** which are invisible to the current detector.

**Questions:**
- How many different display/kit types are used across all tasks?
- Can students be required to use a standard kit with white segments?
- Or should we build separate display detectors per kit type?

---

### 2. Task Spec for Every Real Task
**Problem:** We only have specs for 5 tasks (`task_04`, `task_02`, `task_09`, `demo_display_0_to_9`, `task_05_digital_clock`). We have no idea what tasks the other student videos correspond to.

**Questions:**
- What is the complete list of tasks assigned this semester?
- For each task, what exactly must the student demonstrate? (full truth table / key behaviors)
- What is the grading policy — `all_or_nothing` or partial credit (`pass_threshold`)?
- How many points is each task worth?

---

### 3. Student Photos
**Problem:** Anti-fraud requires a top-down photo of the board from the same submission. Currently we have no real photos — only a placeholder `board.jpg`.

**Questions:**
- Are students currently required to submit a photo alongside the video?
- If yes, where are those photos stored (S3 bucket path)?
- If no, should we make it mandatory going forward?

---

### 4. Matching Student → Task
**Problem:** The video filenames contain team names (e.g. `TheMultiplexers`) but we have no mapping of which team submitted which task. Grading against the wrong task gives meaningless results.

**Questions:**
- Is there a spreadsheet / portal database that maps student ID → task ID?
- Can the portal pass `task_id` automatically when triggering analysis?

---

## 🟡 IMPORTANT — Quality Improvements

### 5. Fusion Weight Calibration
**Current:** CV = 20%, Rubric = 80%. These were set because DIP switch reading was abandoned.

**Questions:**
- Once we have more real submission results, should we adjust these weights?
- Is 65% a reasonable pass threshold? (A student who verbally explains 82% of the task passes even with 0% CV score.)
- Should borderline submissions (45–65%) automatically go to a human reviewer?

---

### 6. State Reader — Graceful Failure
**Problem:** If the state reader can't find a display (e.g. red LED clock), the entire pipeline crashes. It should degrade gracefully to rubric-only scoring instead.

**Action needed:** Make `read_video` return empty observations instead of raising a `ValueError` when no display is found.

---

### 7. Speed — State Reader is Slow
**Current:** ~105 seconds for a 45-second video. For 100+ submissions this becomes hours.

**Questions:**
- Is there a time budget per submission? (e.g. must complete within 3 minutes)
- Should we run submissions in parallel (multiple workers)?
- Is a GPU available on the server to speed up feature matching?

---

### 8. Rubric LLM — Model Reliability
**Problem:** The Gemini model sometimes returns 503 (overloaded) and the fallback chain occasionally disconnects entirely, causing 0% rubric score unfairly.

**Questions:**
- Is the Gemini API key on a paid tier or free tier? (Free tier has strict rate limits.)
- Should we add Anthropic Claude as a second fallback to never get a 0% score due to API failure?

---

## 🟢 FUTURE — Nice to Have

### 9. Portal Integration
- How does the student portal (PHP/Next.js) currently trigger analysis? Does it call our API or is it manual?
- What does the portal show students after submission — just pass/fail, or the detailed breakdown?
- Should borderline cases show a "pending human review" message to students?

### 10. Anti-Fraud Threshold Tuning
- Current threshold: ≥40 SIFT inliers = same board. Is this too strict or too loose?
- Do we have any confirmed fraud cases to test against?
- What happens when a student uses the same board for multiple tasks? (Will always match.)

### 11. Sequence / Ordering Check for Clocks
- For the digital clock, should seconds be verified to count **upward** (1→2→3) in order, or is it enough that they appear at some point?
- Currently `state_match` mode is order-independent — should `sequence_match` be used instead?

### 12. Multi-Display Tasks
- The clock has 6 displays, our pipeline reads at most 2. Is there any task that genuinely needs all 6 read?
- For the clock: is it acceptable to require students to zoom in on just the seconds display?

### 13. DIP Switch Reading — Revisit?
- We abandoned DIP switch reading because the student's hand covers the switch during every flip.
- Could we require students to hold their hand away for 1 second after each flip (a submission guideline)?
- Or is rubric-only verification acceptable long term for decoder tasks?

---

## 📋 Summary — What We Need From You

| # | What | Priority |
|---|---|---|
| 1 | Full list of tasks assigned this semester with expected behaviors | 🔴 Critical |
| 2 | Student → task ID mapping (spreadsheet or portal export) | 🔴 Critical |
| 3 | Are student photos being collected? Where? | 🔴 Critical |
| 4 | Display type used in each task (white segment or red LED?) | 🔴 Critical |
| 5 | Pass/fail threshold preferences (is 65% okay?) | 🟡 Important |
| 6 | Is Gemini API key on paid tier? | 🟡 Important |
| 7 | Time budget per submission | 🟡 Important |
| 8 | Should borderline go to human review or auto-fail? | 🟡 Important |

---

*Updated by Antigravity — 2026-10-14*
