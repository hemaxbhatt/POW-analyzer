"""
Proof-of-Work Analyzer -- API entrypoint (direct-upload version)

Three-step flow:
  1. POST /submissions/request-upload  -> returns signed upload URLs
  2. Portal uploads video+photo DIRECTLY to those signed URLs
     (not through this API -- large files never pass through the server)
  3. POST /submissions/{submission_id}/analyze  -> kicks off the full
     pipeline as a background job (download, read, verify, save)
  4. GET  /submissions/{submission_id}/result   -> poll for outcome

Detection remains OPTIONAL: if no trained YOLO model exists yet, the
endpoint still returns ingestion + transcription + verification results
with a note that detection was skipped. This keeps the API working
throughout Phase 2 development.
"""

from dotenv import load_dotenv
load_dotenv()  # must happen before app.storage reads env vars at module level

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from typing import Optional

from app.storage import create_upload_urls
from app.analysis import run_pipeline, load_result, get_available_task_ids

app = FastAPI(
    title="Proof-of-Work Analyzer",
    version="0.4.0",
    description=(
        "Automated pipeline for analysing student proof-of-work submissions. "
        "Upload video & photo, then trigger the analysis pipeline to get "
        "transcriptions, component detection, and functional verification results."
    ),
    docs_url=None,   # disable default /docs so we can serve our custom one
    redoc_url=None,  # disable default /redoc
)


@app.on_event("startup")
def cleanup_orphaned_jobs():
    """
    On server boot, check for any jobs in data/ that were left in 'processing'
    state due to an unexpected server restart or termination, and mark them as failed.
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from app.analysis import DATA_DIR, save_result
    import logging

    data_dir = Path(DATA_DIR)
    if not data_dir.exists():
        return

    recovered = 0
    for res_path in data_dir.glob("*/result.json"):
        try:
            with open(res_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("status") == "processing":
                d["status"] = "failed"
                d["stage"] = "error"
                d["error"] = "Server was restarted while analysis was in progress. Please re-trigger submission."
                d["completed_at"] = datetime.now(timezone.utc).isoformat()
                save_result(res_path.parent.name, d)
                recovered += 1
        except Exception:
            continue
    if recovered:
        logging.getLogger("uvicorn.error").info("Recovered %d orphaned in-progress submission(s).", recovered)


from app.docs_ui import DOCS_HTML

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui() -> HTMLResponse:
    """Serve a completely custom dark-mode Swagger UI."""
    return HTMLResponse(content=DOCS_HTML, status_code=200)


@app.get("/redoc", include_in_schema=False)
async def custom_redoc() -> HTMLResponse:
    """Serve ReDoc with dark theme."""
    html_content = """<!DOCTYPE html>
<html>
<head>
  <title>Proof-of-Work Analyzer · ReDoc</title>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
  <style>body { margin: 0; padding: 0; background: #0f1117; }</style>
</head>
<body>
  <redoc
    spec-url='/openapi.json'
    theme='{
      "colors": {
        "primary": { "main": "#7c9ef8" },
        "text": { "primary": "#e2e8f0", "secondary": "#94a3b8" },
        "background": { "primary": "#0f1117", "secondary": "#13161f" },
        "border": { "dark": "#2d3748", "light": "#1e2130" },
        "responses": {
          "success": { "color": "#22c55e", "backgroundColor": "#0d2218" },
          "error": { "color": "#ef4444", "backgroundColor": "#2d1515" }
        },
        "http": {
          "get": "#22c55e",
          "post": "#0ea5e9",
          "put": "#f59e0b",
          "delete": "#ef4444",
          "patch": "#a78bfa"
        }
      },
      "typography": {
        "fontSize": "15px",
        "fontFamily": "Inter, Segoe UI, system-ui, sans-serif",
        "headings": { "fontFamily": "Inter, Segoe UI, sans-serif", "fontWeight": "700" },
        "code": { "fontFamily": "Fira Code, Cascadia Code, monospace", "fontSize": "13px", "backgroundColor": "#1a1d2e", "color": "#e2e8f0" }
      },
      "sidebar": {
        "backgroundColor": "#13161f",
        "textColor": "#94a3b8",
        "activeTextColor": "#7c9ef8"
      },
      "rightPanel": {
        "backgroundColor": "#1a1d2e",
        "textColor": "#e2e8f0"
      }
    }'
  ></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html_content)



# ── Request / Response models ────────────────────────────────────────────────

class UploadRequest(BaseModel):
    student_id: str
    task_id: str


class UploadResponse(BaseModel):
    submission_id: str
    video_upload_url: str
    photo_upload_url: str
    expires_in_minutes: int


class AnalyzeRequest(BaseModel):
    student_id: str
    task_id: str


class AnalyzeResponse(BaseModel):
    submission_id: str
    status: str
    message: str


class VerificationDetail(BaseModel):
    task_id: Optional[str] = None
    mode: Optional[str] = None
    passed: Optional[bool] = None
    score: Optional[float] = None
    satisfied_count: Optional[int] = None
    total_count: Optional[int] = None
    entries: Optional[list] = None
    violations: Optional[list] = None
    warnings: Optional[list] = None


class SubmissionResult(BaseModel):
    submission_id: str
    task_id: Optional[str] = None
    status: str                        # processing | completed | failed
    stage: Optional[str] = None        # downloading | extracting_audio | transcribing |
                                       # detecting_components | reading_display | verifying |
                                       # done | error
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    verification: Optional[dict] = None
    transcript_text: Optional[str] = None
    reader_stats: Optional[dict] = None
    reader_warnings: Optional[list] = None
    detection_status: Optional[str] = None
    component_counts: Optional[dict] = None
    component_confidence: Optional[dict] = None
    error: Optional[str] = None
    rubric: Optional[dict] = None
    fusion: Optional[dict] = None
    anti_fraud: Optional[dict] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/submissions/request-upload", response_model=UploadResponse)
def request_upload(req: UploadRequest):
    """
    Step 1: portal calls this before showing the file-upload widget to the
    student. Returns pre-signed PUT URLs for the video and photo; the
    portal uses these to upload directly to S3 without the files ever
    passing through this server.
    """
    try:
        result = create_upload_urls(req.student_id, req.task_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Could not create upload URLs: {e}"
        )
    return UploadResponse(**result)


@app.post("/submissions/{submission_id}/analyze", response_model=AnalyzeResponse)
def analyze_submission(
    submission_id: str,
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Step 2: portal calls this AFTER both files finish uploading to storage.

    Kicks off the full analysis pipeline as a background job:
    download from S3 → extract audio → transcribe → detect components →
    read 7-segment displays → verify against task truth table → save result.

    Returns immediately with status "processing". Poll
    GET /submissions/{submission_id}/result for the outcome.
    """
    # Validate task_id is known
    available = get_available_task_ids()
    if req.task_id not in available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown task_id '{req.task_id}'. "
                f"Available tasks: {', '.join(available)}"
            ),
        )

    # Check if there's already a running/completed job for this submission
    existing = load_result(submission_id)
    if existing and existing.get("status") == "processing":
        return AnalyzeResponse(
            submission_id=submission_id,
            status="processing",
            message="Analysis is already in progress. Poll GET /submissions/{id}/result for updates.",
        )

    # Kick off background pipeline
    background_tasks.add_task(
        run_pipeline,
        student_id=req.student_id,
        submission_id=submission_id,
        task_id=req.task_id,
    )

    return AnalyzeResponse(
        submission_id=submission_id,
        status="processing",
        message=(
            "Analysis started. Poll GET /submissions/{id}/result for the outcome. "
            "The pipeline typically takes 90-120 seconds per video."
        ),
    )


@app.get("/submissions/{submission_id}/result", response_model=SubmissionResult)
def get_result(submission_id: str):
    """
    Poll for the analysis result.

    Returns the current state of the analysis job:
    - **processing**: pipeline is still running (check `stage` for progress)
    - **completed**: verification result is available
    - **failed**: something went wrong (check `error` field)

    If no analysis has been started for this submission_id, returns 404.
    """
    result = load_result(submission_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No analysis found for submission '{submission_id}'. "
                "Call POST /submissions/{id}/analyze first."
            ),
        )
    return SubmissionResult(**result)


@app.get("/submissions/export/csv")
def export_submissions_csv():
    """Export all completed and processed submissions as a downloadable CSV summary."""
    import csv, io, json
    from pathlib import Path
    from app.analysis import DATA_DIR

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "submission_id", "student_id", "task_id", "status",
        "decision", "fused_score", "cv_score", "rubric_score",
        "anti_fraud_match", "anti_fraud_inliers", "created_at", "rubric_reason"
    ])

    data_dir = Path(DATA_DIR)
    if data_dir.exists():
        for res_file in sorted(data_dir.glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(res_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                fused = d.get("fusion") or {}
                verif = d.get("verification") or {}
                rubric = d.get("rubric") or {}
                af = d.get("anti_fraud") or {}
                writer.writerow([
                    d.get("submission_id", res_file.parent.name),
                    d.get("student_id", ""),
                    d.get("task_id", ""),
                    d.get("status", ""),
                    fused.get("decision", ""),
                    fused.get("fused_score", ""),
                    verif.get("score", ""),
                    rubric.get("score", ""),
                    af.get("is_match", ""),
                    af.get("inlier_count", ""),
                    d.get("created_at", ""),
                    rubric.get("reasoning", "")
                ])
            except Exception:
                continue

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=submissions_summary.csv"}
    )


@app.get("/tasks")
def list_tasks():
    """List available task IDs that can be used with the /analyze endpoint."""
    return {"task_ids": get_available_task_ids()}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Dev / Test endpoints ──────────────────────────────────────────────────────

class LocalAnalyzeRequest(BaseModel):
    video_path: str
    photo_path: str
    task_id: str
    student_id: str = "test_student"
    submission_id: Optional[str] = None


@app.post("/test/local-analyze")
def local_analyze(req: LocalAnalyzeRequest, background_tasks: BackgroundTasks):
    """DEV: Run full pipeline on local files (no S3 upload needed)."""
    import uuid, os, shutil
    from app.analysis import DATA_DIR, save_result
    from datetime import datetime, timezone

    if not os.path.exists(req.video_path):
        raise HTTPException(status_code=400, detail=f"Video not found: {req.video_path}")
    if not os.path.exists(req.photo_path):
        raise HTTPException(status_code=400, detail=f"Photo not found: {req.photo_path}")

    available = get_available_task_ids()
    if req.task_id not in available:
        raise HTTPException(status_code=400,
                            detail=f"Unknown task_id '{req.task_id}'. Available: {', '.join(available)}")

    submission_id = req.submission_id or str(uuid.uuid4())
    job_dir = DATA_DIR / submission_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_dest = str(job_dir / "source.mp4")
    photo_dest = str(job_dir / "photo.jpg")
    if req.video_path != video_dest:
        shutil.copy2(req.video_path, video_dest)
    if req.photo_path != photo_dest:
        shutil.copy2(req.photo_path, photo_dest)

    save_result(submission_id, {
        "submission_id": submission_id, "task_id": req.task_id,
        "status": "processing", "stage": "queued",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None, "error": None,
    })

    def _run_local(student_id, submission_id, task_id, video_path, photo_path):
        import json, logging, traceback
        from datetime import datetime, timezone
        from pathlib import Path
        logger = logging.getLogger(__name__)
        result = {
            "submission_id": submission_id, "task_id": task_id,
            "status": "processing", "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None, "stage": "extracting_audio",
            "verification": None, "transcript_text": None,
            "reader_stats": None, "reader_warnings": None,
            "detection_status": "skipped_local_test",
            "component_counts": None, "component_confidence": None,
            "error": None, "rubric": None, "fusion": None,
        }
        save_result(submission_id, result)
        try:
            job_dir_path = str(DATA_DIR / submission_id)

            from app.ingestion import extract_audio, sample_frames
            result["stage"] = "extracting_audio"; save_result(submission_id, result)
            audio_path = extract_audio(video_path, job_dir_path)
            sample_frames(video_path, job_dir_path)

            from app.transcription import transcribe
            result["stage"] = "transcribing"; save_result(submission_id, result)
            transcript = transcribe(audio_path)
            result["transcript_text"] = transcript["text"]

            from app.state_reader import read_video
            result["stage"] = "reading_display"; save_result(submission_id, result)
            reader_result = read_video(video_path, sample_fps=4.0, max_displays=2)
            observations = reader_result.observations
            result["reader_stats"] = reader_result.stats
            result["reader_warnings"] = reader_result.warnings
            (Path(job_dir_path) / "observations.json").write_text(
                json.dumps(observations, indent=2, default=str))

            from app.verification import verify
            from app.analysis import _load_tasks
            result["stage"] = "verifying"; save_result(submission_id, result)
            task_spec = _load_tasks()[task_id]
            vr = verify(task_spec, observations)
            result["verification"] = vr.to_dict()

            from app.rubric import score_transcript
            result["stage"] = "rubric_scoring"; save_result(submission_id, result)
            rubric = score_transcript(task_spec, result["transcript_text"])
            result["rubric"] = rubric

            from app.anti_fraud import verify_submission_match
            result["stage"] = "anti_fraud_check"; save_result(submission_id, result)
            result["anti_fraud"] = verify_submission_match(video_path, photo_path)

            from app.fusion import fuse
            result["fusion"] = fuse(result["verification"], rubric)
            result["status"] = "completed"
            result["stage"] = "done"
            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            save_result(submission_id, result)
            logger.info("Local pipeline done: %s decision=%s", submission_id,
                        result["fusion"]["decision"])
        except Exception as e:
            result["status"] = "failed"; result["stage"] = "error"
            result["error"] = f"{type(e).__name__}: {e}"
            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            save_result(submission_id, result)
            logger.error("Local pipeline failed: %s\n%s", e, traceback.format_exc())

    background_tasks.add_task(_run_local, req.student_id, submission_id,
                               req.task_id, video_dest, photo_dest)
    return {"submission_id": submission_id, "status": "processing",
            "message": f"Pipeline started. Poll GET /submissions/{submission_id}/result"}


@app.get("/test/list-submissions")
def list_submissions():
    """DEV: List all submissions that have a result.json on disk."""
    import json
    from app.analysis import DATA_DIR
    results = []
    for d in sorted(DATA_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        rp = d / "result.json"
        if rp.exists():
            try:
                r = json.loads(rp.read_text())
                results.append({
                    "submission_id": d.name,
                    "task_id": r.get("task_id"),
                    "status": r.get("status"),
                    "stage": r.get("stage"),
                    "decision": (r.get("fusion") or {}).get("decision"),
                    "fused_score": (r.get("fusion") or {}).get("fused_score"),
                })
            except Exception:
                pass
    return {"submissions": results}


TEST_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>POW Analyzer — Test UI</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0f1117;color:#e2e8f0;font-family:Inter,Segoe UI,sans-serif;padding:24px}
h1{color:#7c9ef8;font-size:1.4rem;margin-bottom:4px}
.sub{color:#64748b;font-size:.85rem;margin-bottom:24px}
.row{display:flex;gap:16px}
.col{flex:1}
.card{background:#1a1d2e;border:1px solid #2d3748;border-radius:10px;padding:20px;margin-bottom:20px}
h2{font-size:.8rem;color:#94a3b8;margin-bottom:14px;text-transform:uppercase;letter-spacing:.06em}
label{display:block;font-size:.78rem;color:#64748b;margin-top:12px;margin-bottom:4px}
input,select{width:100%;background:#0f1117;border:1px solid #2d3748;color:#e2e8f0;padding:8px 12px;border-radius:6px;font-size:.88rem}
input:focus,select:focus{outline:none;border-color:#7c9ef8}
button{margin-top:16px;padding:9px 18px;background:#7c9ef8;color:#0f1117;border:none;border-radius:6px;font-weight:700;cursor:pointer;font-size:.88rem}
button:hover{background:#93adf9}button:disabled{background:#2d3748;color:#64748b;cursor:not-allowed}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.72rem;font-weight:700}
.pass{background:#0d2218;color:#22c55e}.fail{background:#2d1515;color:#ef4444}
.borderline{background:#2d2510;color:#f59e0b}.processing{background:#1e2130;color:#94a3b8}
.sgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px}
.sbox{background:#0f1117;border-radius:8px;padding:14px;text-align:center}
.sval{font-size:1.9rem;font-weight:800}.slbl{font-size:.7rem;color:#64748b;margin-top:4px}
.entry{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #1e2130;font-size:.8rem}
.entry:last-child{border:none}
.ok{color:#22c55e}.wrong{color:#ef4444}.missing{color:#f59e0b}
pre{background:#0f1117;border-radius:6px;padding:10px;font-size:.72rem;overflow:auto;color:#94a3b8;white-space:pre-wrap;max-height:180px}
.pill{background:#13161f;border:1px solid #2d3748;padding:2px 10px;border-radius:99px;font-size:.72rem;color:#7c9ef8}
.srow{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #1e2130;font-size:.8rem;cursor:pointer}
.srow:hover{color:#7c9ef8}.sid{color:#64748b;font-family:monospace;font-size:.72rem}
</style></head>
<body>
<h1>&#128300; Proof-of-Work Analyzer &mdash; Test Dashboard</h1>
<p class="sub">Local dev UI &mdash; runs the full pipeline and shows results in real time</p>
<div class="row">
  <div class="col">
    <div class="card">
      <h2>Run Pipeline (Local Files)</h2>
      <label>Video Path (absolute path on server)</label>
      <input id="vp" placeholder="C:/Users/hemax/Downloads/ApexNode_23110001_1.2.mp4"/>
      <label>Photo Path (absolute path on server)</label>
      <input id="pp" placeholder="C:/path/to/photo.jpg"/>
      <label>Task ID</label><select id="tid"></select>
      <label>Student ID</label><input id="sid" value="test_student"/>
      <button id="runBtn" onclick="run()">&#9654; Run Analysis</button>
    </div>
    <div class="card">
      <h2>Poll Existing Submission</h2>
      <label>Submission ID</label>
      <input id="pid" placeholder="paste uuid here"/>
      <button onclick="poll(document.getElementById('pid').value)">&#8635; Poll</button>
    </div>
    <div class="card">
      <h2>Recent Submissions</h2>
      <div id="subList"><p style="color:#64748b;font-size:.8rem">Loading...</p></div>
    </div>
  </div>
  <div class="col">
    <div class="card" id="rc" style="display:none">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <h2 style="margin:0">Result</h2>
        <span id="stg" class="pill"></span>
        <span id="dec" class="badge"></span>
      </div>
      <div class="sgrid">
        <div class="sbox"><div class="sval" id="fs" style="color:#7c9ef8">-</div><div class="slbl">Fused Score</div></div>
        <div class="sbox"><div class="sval" id="cs" style="color:#22c55e">-</div><div class="slbl">CV (Video)</div></div>
        <div class="sbox"><div class="sval" id="rs" style="color:#f59e0b">-</div><div class="slbl">Rubric (LLM)</div></div>
      </div>
      <label style="margin-top:16px">LLM Reasoning</label>
      <div id="rea" style="background:#0f1117;border-radius:6px;padding:10px;font-size:.8rem;color:#94a3b8;margin-top:6px;min-height:36px"></div>
      <label style="margin-top:14px">Truth Table Entries</label>
      <div id="ent"></div>
      <label style="margin-top:14px">Whisper Transcript</label>
      <pre id="tr"></pre>
      <label style="margin-top:14px">Reader Stats</label>
      <pre id="rs2"></pre>
    </div>
    <div class="card" id="sc"><p style="color:#64748b;font-size:.85rem">Start a run or select a submission to see results.</p></div>
  </div>
</div>
<script>
let timer=null,cur=null;
async function loadTasks(){const r=await fetch('/tasks');const d=await r.json();const s=document.getElementById('tid');d.task_ids.forEach(id=>{const o=document.createElement('option');o.value=id;o.textContent=id;s.appendChild(o)});}
async function loadSubs(){const r=await fetch('/test/list-submissions');const d=await r.json();const el=document.getElementById('subList');if(!d.submissions.length){el.innerHTML='<p style="color:#64748b;font-size:.8rem">No submissions yet</p>';return;}el.innerHTML=d.submissions.map(s=>{const dec=s.decision||s.status;const cls=dec==='pass'?'pass':dec==='fail'?'fail':dec==='borderline'?'borderline':'processing';const pct=s.fused_score!=null?Math.round(s.fused_score*100)+'%':'';return`<div class="srow" onclick="poll('${s.submission_id}')"><span class="badge ${cls}">${dec||'...'}</span><span style="flex:1">${s.task_id||''} ${pct}</span><span class="sid">${s.submission_id.slice(0,8)}...</span></div>`}).join('');}
async function run(){const v=document.getElementById('vp').value.trim();const p=document.getElementById('pp').value.trim();const t=document.getElementById('tid').value;const s=document.getElementById('sid').value.trim()||'test_student';if(!v||!p){alert('Enter video and photo paths');return;}const btn=document.getElementById('runBtn');btn.disabled=true;btn.textContent='Starting...';try{const r=await fetch('/test/local-analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({video_path:v,photo_path:p,task_id:t,student_id:s})});const d=await r.json();if(!r.ok){alert(d.detail||'Error');return;}poll(d.submission_id);}finally{btn.disabled=false;btn.textContent='Run Analysis';}}
function poll(id){if(!id)return;cur=id;document.getElementById('pid').value=id;if(timer)clearInterval(timer);document.getElementById('rc').style.display='block';document.getElementById('sc').style.display='none';fetch(`/submissions/${id}/result`).then(r=>r.json()).then(update);timer=setInterval(()=>{fetch(`/submissions/${cur}/result`).then(r=>r.json()).then(d=>{update(d);if(d.status==='completed'||d.status==='failed'){clearInterval(timer);loadSubs();}});},2000);}
function pct(v){return v!=null?Math.round(v*100)+'%':'-';}
function update(d){document.getElementById('stg').textContent=d.stage||'';const f=d.fusion||{};const dec=f.decision||d.status;const b=document.getElementById('dec');b.textContent=dec||'';b.className='badge '+(dec==='pass'?'pass':dec==='fail'?'fail':dec==='borderline'?'borderline':'processing');document.getElementById('fs').textContent=pct(f.fused_score);document.getElementById('cs').textContent=pct(f.video_score);document.getElementById('rs').textContent=pct(f.rubric_score);
let rea = (d.rubric||{}).reasoning||'-';
if (d.anti_fraud) { rea = "[Anti-Fraud: " + (d.anti_fraud.is_match ? "MATCH" : "MISMATCH") + "] " + d.anti_fraud.reason + "\n\n" + rea; }
document.getElementById('rea').textContent=rea;
document.getElementById('tr').textContent=d.transcript_text||'(not yet transcribed)';document.getElementById('rs2').textContent=d.reader_stats?JSON.stringify(d.reader_stats,null,2):'-';const vr=d.verification;const el=document.getElementById('ent');if(vr&&vr.entries){el.innerHTML=vr.entries.map(e=>{const c=e.status==='ok'?'ok':e.status==='wrong_output'?'wrong':'missing';return`<div class="entry"><span class="${c}">&#11044;</span><span>${JSON.stringify(e.expected.input)} &rarr; ${JSON.stringify(e.expected.output)}</span><span style="margin-left:auto;color:#64748b">${e.status}</span></div>`}).join('');}else{el.innerHTML='<p style="color:#64748b;font-size:.8rem">-</p>';}if(d.status==='failed'){document.getElementById('rea').textContent=d.error||'Unknown error';document.getElementById('rea').style.color='#ef4444';}}
loadTasks();loadSubs();
</script></body></html>"""


@app.get("/test-ui", response_class=HTMLResponse)
def test_ui():
    """DEV: Serve a local test dashboard for the pipeline."""
    return HTMLResponse(content=TEST_UI_HTML)
