"""Quick script: extract audio + transcribe one video, print the transcript."""
import sys, os
sys.path.insert(0, ".")
os.environ.setdefault("GEMINI_API_KEY", open(".env").read().split("GEMINI_API_KEY=")[1].split()[0])

from pathlib import Path
from app.ingestion import extract_audio
from app.transcription import transcribe
import tempfile, shutil

VIDEO = r"D:\IITGN\videos\YTSave_YouTube_Media_CqkE6Rqt-_E_TheMultiplexers-25110049-CLOCK_001_1080p.mp4"

job_dir = Path("data") / "transcribe_test"
job_dir.mkdir(parents=True, exist_ok=True)

print("Extracting audio...")
audio = extract_audio(VIDEO, str(job_dir))
print("Transcribing...")
result = transcribe(audio)
print("\n=== TRANSCRIPT ===")
print(result["text"])
shutil.rmtree(job_dir, ignore_errors=True)
