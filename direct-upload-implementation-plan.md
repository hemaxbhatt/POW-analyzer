# Implementation Plan: Direct Upload (Replacing YouTube Ingestion)

## Context for the implementing agent

This document is a complete implementation spec for modifying an existing
project called **proof-of-work-analyzer**. The project currently:

- Accepts a YouTube URL from a student portal
- Downloads the video via `yt-dlp`
- Extracts audio, transcribes with Whisper, samples frames
- Has an optional component-detection stage (YOLO, not yet trained)

**Goal of this change:** replace the YouTube-link ingestion path entirely
with **direct file upload** from the student portal straight to cloud
storage, using signed upload URLs. This removes all YouTube-scraping
fragility (bot detection, cookie expiry, yt-dlp version breakage) and
gives the backend a trustworthy, immediately-available raw file instead
of something scraped and re-encoded by YouTube.

The existing portal (where students submit work) is built in **PHP and
Next.js**. The analysis backend is a **Python FastAPI** service. The team
already has experience with **Firebase** — use **Firebase Storage** as
the storage backend unless there's a reason to prefer S3/Cloudinary
(this doc defaults to Firebase Storage; swap the SDK calls if a
different provider is chosen).

---

## 1. Architecture change summary

### Before (current)
```
Student → pastes YouTube link → portal → FastAPI /submissions/analyze
                                              → yt-dlp downloads from YouTube
                                              → ffmpeg extracts audio/frames
                                              → Whisper transcribes
                                              → (optional) YOLO detects
```

### After (target)
```
Student → portal requests a signed upload URL from FastAPI
        → student's browser uploads video + photo DIRECTLY to
          Firebase Storage (bypasses the backend entirely for the
          upload itself -- large files never pass through your server)
        → portal notifies FastAPI "upload complete" with the storage
          path + submission metadata
        → FastAPI fetches the file from Firebase Storage (server-side,
          trusted, fast, no scraping)
        → ffmpeg extracts audio/frames
        → Whisper transcribes
        → (optional) YOLO detects
```

Key property: **the browser uploads directly to storage**, not to your
backend. Your backend only ever generates the signed URL and later reads
the file straight from storage once upload is confirmed. This keeps
large video uploads off your API server entirely.

---

## 2. Storage setup (Firebase Storage)

### 2.1 Bucket structure
```
submissions/
  {student_id}/
    {submission_id}/
      video.mp4
      photo.jpg
```

Using `{student_id}/{submission_id}/` as the path prefix keeps
submissions organized and makes per-student cleanup/export trivial
later.

### 2.2 Firebase Storage security rules

File: `storage.rules` (add to the existing Firebase project)

```
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    match /submissions/{studentId}/{submissionId}/{fileName} {
      // Writes only happen via signed URLs issued by the backend
      // (using the Admin SDK, which bypasses these rules entirely).
      // These rules govern any direct client SDK access -- lock it
      // down to read-only for authenticated users, no direct writes.
      allow read: if request.auth != null;
      allow write: if false;  // all writes go through signed URLs only
    }
  }
}
```

### 2.3 File constraints to enforce (both client-side AND server-side --
never trust client-side validation alone)

| Constraint | Video | Photo |
|---|---|---|
| Max file size | 500 MB (adjust to your real duration limits) | 15 MB |
| Allowed MIME types | `video/mp4`, `video/quicktime` (.mov) | `image/jpeg`, `image/png` |
| Max duration | e.g. 5 minutes (check server-side after upload via ffprobe) | n/a |

---

## 3. Backend changes (FastAPI)

### 3.1 New dependency

Add to `requirements.txt`:
```
firebase-admin==6.5.0
```

### 3.2 New module: `app/storage.py`

```python
"""
Signed upload URL generation + fetching uploaded files from Firebase
Storage. Replaces app/ingestion.py's YouTube-downloading responsibility
with direct-upload handling.
"""

import uuid
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, storage

# Initialize once at import time. Path to your Firebase service account
# JSON key -- keep this OUT of version control (add to .gitignore),
# load via environment variable in production.
FIREBASE_CRED_PATH = "firebase-service-account.json"
FIREBASE_BUCKET = "your-project-id.appspot.com"  # replace with real bucket name

_app = firebase_admin.initialize_app(
    credentials.Certificate(FIREBASE_CRED_PATH),
    {"storageBucket": FIREBASE_BUCKET},
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# How long a signed upload URL stays valid before it expires.
UPLOAD_URL_EXPIRY_MINUTES = 15

ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png"}
MAX_VIDEO_SIZE_BYTES = 500 * 1024 * 1024   # 500 MB
MAX_PHOTO_SIZE_BYTES = 15 * 1024 * 1024    # 15 MB


def create_upload_urls(student_id: str, task_id: str) -> dict:
    """
    Generates a new submission_id and signed upload URLs for both the
    video and the required clear photo. The portal calls this first,
    then uses the returned URLs to upload directly from the browser.
    """
    submission_id = str(uuid.uuid4())
    bucket = storage.bucket()

    video_blob = bucket.blob(f"submissions/{student_id}/{submission_id}/video.mp4")
    photo_blob = bucket.blob(f"submissions/{student_id}/{submission_id}/photo.jpg")

    video_url = video_blob.generate_signed_url(
        version="v4",
        expiration=UPLOAD_URL_EXPIRY_MINUTES * 60,
        method="PUT",
        content_type="video/mp4",
    )
    photo_url = photo_blob.generate_signed_url(
        version="v4",
        expiration=UPLOAD_URL_EXPIRY_MINUTES * 60,
        method="PUT",
        content_type="image/jpeg",
    )

    return {
        "submission_id": submission_id,
        "video_upload_url": video_url,
        "photo_upload_url": photo_url,
        "expires_in_minutes": UPLOAD_URL_EXPIRY_MINUTES,
    }


def download_submission_files(student_id: str, submission_id: str) -> dict:
    """
    Called AFTER the portal confirms both files were uploaded. Pulls the
    files from Firebase Storage down to local disk (in the same
    data/<job_id>/ structure the rest of the pipeline already expects),
    so ingestion.py's extract_audio/sample_frames functions work
    unchanged.
    """
    job_dir = DATA_DIR / submission_id
    job_dir.mkdir(parents=True, exist_ok=True)

    bucket = storage.bucket()

    video_blob = bucket.blob(f"submissions/{student_id}/{submission_id}/video.mp4")
    photo_blob = bucket.blob(f"submissions/{student_id}/{submission_id}/photo.jpg")

    if not video_blob.exists():
        raise FileNotFoundError("Video not found in storage -- upload may not have completed.")
    if not photo_blob.exists():
        raise FileNotFoundError("Photo not found in storage -- upload may not have completed.")

    # Enforce size limits server-side (never trust the client alone).
    video_blob.reload()
    photo_blob.reload()
    if video_blob.size > MAX_VIDEO_SIZE_BYTES:
        raise ValueError(f"Video exceeds max size of {MAX_VIDEO_SIZE_BYTES} bytes.")
    if photo_blob.size > MAX_PHOTO_SIZE_BYTES:
        raise ValueError(f"Photo exceeds max size of {MAX_PHOTO_SIZE_BYTES} bytes.")

    video_path = str(job_dir / "source.mp4")
    photo_path = str(job_dir / "photo.jpg")
    video_blob.download_to_filename(video_path)
    photo_blob.download_to_filename(photo_path)

    return {
        "job_id": submission_id,
        "job_dir": str(job_dir),
        "video_path": video_path,
        "photo_path": photo_path,
    }
```

### 3.3 Updated `app/main.py`

Replace the YouTube-link-based request/flow with a **two-step** flow:
step 1 requests upload URLs, step 2 (after upload) triggers analysis.

```python
"""
Proof-of-Work Analyzer -- API entrypoint (direct-upload version)

Two-step flow:
  1. POST /submissions/request-upload  -> returns signed upload URLs
  2. Portal uploads video+photo directly to those URLs (not through
     this API)
  3. POST /submissions/analyze         -> backend fetches from storage
     and runs the pipeline
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.storage import create_upload_urls, download_submission_files
from app.ingestion import extract_audio, sample_frames
from app.transcription import transcribe

app = FastAPI(title="Proof-of-Work Analyzer", version="0.3.0")


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
    submission_id: str
    task_id: str


class SubmissionResult(BaseModel):
    job_id: str
    transcript_text: str
    frame_count: int
    frame_paths: list[str]
    photo_path: str
    component_counts: dict | None = None
    component_confidence: dict | None = None
    detection_status: str
    status: str


@app.post("/submissions/request-upload", response_model=UploadResponse)
def request_upload(req: UploadRequest):
    """Step 1: portal calls this before showing the upload widget."""
    try:
        result = create_upload_urls(req.student_id, req.task_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not create upload URLs: {e}")
    return UploadResponse(**result)


@app.post("/submissions/analyze", response_model=SubmissionResult)
def analyze_submission(req: AnalyzeRequest):
    """Step 2: portal calls this AFTER both files finish uploading."""
    try:
        files = download_submission_files(req.student_id, req.submission_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch uploaded files: {e}")

    audio_path = extract_audio(files["video_path"], files["job_dir"])
    frame_paths = sample_frames(files["video_path"], files["job_dir"])
    transcript = transcribe(audio_path)

    component_counts = None
    component_confidence = None
    detection_status = "skipped_no_model"
    try:
        from app.detection import detect_components_multi_frame
        detection_result = detect_components_multi_frame(frame_paths + [files["photo_path"]])
        component_counts = detection_result["component_counts"]
        component_confidence = detection_result["component_confidence"]
        detection_status = "ok"
    except FileNotFoundError:
        detection_status = "skipped_no_model"
    except Exception as e:
        detection_status = f"error: {e}"

    return SubmissionResult(
        job_id=files["job_id"],
        transcript_text=transcript["text"],
        frame_count=len(frame_paths),
        frame_paths=frame_paths,
        photo_path=files["photo_path"],
        component_counts=component_counts,
        component_confidence=component_confidence,
        detection_status=detection_status,
        status="analyzed",
    )


@app.get("/health")
def health():
    return {"status": "ok"}
```

### 3.4 `app/ingestion.py` changes

- **Delete** `download_video()` entirely (no longer needed -- no more
  yt-dlp).
- **Keep** `extract_audio()` and `sample_frames()` unchanged -- they
  operate on a local file path regardless of where that file came from.
- **Remove** the `yt-dlp` dependency from `requirements.txt`.
- **Delete** `cookies.txt` and all cookie/player-client workarounds --
  no longer relevant.

---

## 4. Frontend changes (student portal)

### 4.1 Flow the portal needs to implement

1. Student fills in task_id (already known from the assignment they're
   viewing) and selects a video file + photo file from their device.
2. Portal calls `POST /submissions/request-upload` with
   `{student_id, task_id}`.
3. Portal receives `{submission_id, video_upload_url, photo_upload_url}`.
4. Portal uploads the two files **directly to those URLs** using a
   plain `PUT` request (NOT through your own backend -- this is the
   whole point).
5. Once both uploads succeed, portal calls
   `POST /submissions/analyze` with `{student_id, submission_id, task_id}`.
6. Portal shows the result / polls for status.

### 4.2 Example upload code (vanilla JS, works in either the PHP pages
or a Next.js component)

```javascript
async function submitProofOfWork(studentId, taskId, videoFile, photoFile) {
  // Step 1: request signed upload URLs
  const uploadReq = await fetch("/api/submissions/request-upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_id: studentId, task_id: taskId }),
  });
  const { submission_id, video_upload_url, photo_upload_url } = await uploadReq.json();

  // Step 2: upload files directly to storage (bypasses your backend)
  await Promise.all([
    fetch(video_upload_url, {
      method: "PUT",
      headers: { "Content-Type": "video/mp4" },
      body: videoFile,
    }),
    fetch(photo_upload_url, {
      method: "PUT",
      headers: { "Content-Type": "image/jpeg" },
      body: photoFile,
    }),
  ]);

  // Step 3: tell the backend the upload is done, trigger analysis
  const analyzeReq = await fetch("/api/submissions/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      student_id: studentId,
      submission_id: submission_id,
      task_id: taskId,
    }),
  });
  return await analyzeReq.json();
}
```

Notes for whoever wires this into the actual portal:
- `/api/submissions/request-upload` and `/api/submissions/analyze`
  above assume the PHP/Next.js portal proxies these calls to the
  FastAPI service (common pattern: keep the FastAPI service internal,
  never expose it directly to the browser). Adjust the fetch URLs to
  match however the portal currently reverse-proxies to the Python
  backend.
- Add basic client-side checks before upload (file type, rough size)
  purely for fast user feedback -- but this is NOT a substitute for the
  server-side checks already added in `storage.py`.
- Show upload progress to the student (especially for video files) --
  a plain `fetch` PUT doesn't give progress events; use `XMLHttpRequest`
  with the `upload.onprogress` event instead if a progress bar is
  wanted.

---

## 5. Environment/config changes

Add to whatever `.env` / secrets management the FastAPI service uses:

```
FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com
FIREBASE_SERVICE_ACCOUNT_PATH=/secure/path/firebase-service-account.json
```

Update `app/storage.py` to read these from environment variables
instead of hardcoding, e.g.:
```python
import os
FIREBASE_CRED_PATH = os.environ["FIREBASE_SERVICE_ACCOUNT_PATH"]
FIREBASE_BUCKET = os.environ["FIREBASE_STORAGE_BUCKET"]
```

**Never commit the Firebase service account JSON key to version
control.** Add it to `.gitignore`.

---

## 6. Migration checklist

- [ ] Create/confirm Firebase project and Storage bucket
- [ ] Generate a service account key (Firebase Console → Project
      Settings → Service Accounts → Generate new private key)
- [ ] Add `storage.rules` to the Firebase project, deploy them
- [ ] Add `firebase-admin` to `requirements.txt`, remove `yt-dlp`
- [ ] Add `app/storage.py` (new file, as specified above)
- [ ] Replace `app/main.py` with the two-step-flow version above
- [ ] Remove `download_video()` from `app/ingestion.py`; keep the rest
- [ ] Delete `cookies.txt` and any cookie-related code/config
- [ ] Update portal to implement the 3-step upload flow (request URL →
      direct PUT upload → trigger analyze)
- [ ] Add client-side + confirm server-side file type/size validation
- [ ] Test end-to-end with a real video+photo pair
- [ ] Confirm signed URLs actually expire after the configured window
      (test by waiting past expiry and attempting an upload)
- [ ] Remove/archive old YouTube-link-based endpoint once migration is
      confirmed working, OR keep both temporarily if a transition
      period is needed

---

## 7. What this change does NOT affect

These stay exactly as they are -- no changes needed:
- `app/transcription.py` (Whisper transcription logic)
- `app/detection.py` (YOLO detection logic)
- `training/` (dataset labeling + training workflow)
- The overall phase roadmap (functional verification, rubric scoring,
  decision fusion, anti-fraud cross-check) -- this change only affects
  HOW files arrive at the backend, not what happens to them afterward.
