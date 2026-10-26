import time
import requests
import argparse
import sys
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def test_pipeline(video_path: str, photo_path: str, task_id: str, student_id: str):
    if not Path(video_path).exists():
        print(f"❌ Error: Video file not found at {video_path}")
        sys.exit(1)
    if not Path(photo_path).exists():
        print(f"❌ Error: Photo file not found at {photo_path}")
        sys.exit(1)

    print("==================================================")
    print("🚀 POW Analyzer - End-to-End API Test")
    print("==================================================")

    # 1. Request Upload URLs
    print(f"\n[1/4] Requesting upload URLs for task '{task_id}'...")
    res = requests.post(f"{BASE_URL}/submissions/request-upload", json={
        "student_id": student_id,
        "task_id": task_id
    })
    if res.status_code != 200:
        print(f"❌ Failed: {res.text}")
        sys.exit(1)
    
    data = res.json()
    submission_id = data["submission_id"]
    video_url = data["video_upload_url"]
    photo_url = data["photo_upload_url"]
    print(f"✅ Got Submission ID: {submission_id}")

    # 2. Upload files directly to S3
    print("\n[2/4] Uploading files to S3 using signed URLs...")
    with open(video_path, "rb") as f:
        print(f"  -> Uploading video ({Path(video_path).name})...")
        r_vid = requests.put(video_url, data=f, headers={"Content-Type": "video/mp4"})
        r_vid.raise_for_status()

    with open(photo_path, "rb") as f:
        print(f"  -> Uploading photo ({Path(photo_path).name})...")
        r_pho = requests.put(photo_url, data=f, headers={"Content-Type": "image/jpeg"})
        r_pho.raise_for_status()
    
    print("✅ Uploads complete.")

    # 3. Trigger Analysis
    print("\n[3/4] Triggering background analysis...")
    res = requests.post(f"{BASE_URL}/submissions/{submission_id}/analyze", json={
        "student_id": student_id,
        "task_id": task_id
    })
    if res.status_code != 200:
        print(f"❌ Failed: {res.text}")
        sys.exit(1)
    print("✅ Analysis job started.")

    # 4. Poll for Result
    print("\n[4/4] Polling for results (this usually takes 90-120 seconds)...")
    while True:
        res = requests.get(f"{BASE_URL}/submissions/{submission_id}/result")
        if res.status_code == 200:
            result = res.json()
            status = result["status"]
            stage = result.get("stage", "unknown")
            
            if status == "completed":
                print("\n🎉 Analysis Completed!")
                print("==================================================")
                print("Final Verification Result:")
                vr = result.get("verification", {})
                print(f"  Passed: {vr.get('passed')}")
                print(f"  Score:  {vr.get('score', 0) * 100:.0f}% ({vr.get('satisfied_count')}/{vr.get('total_count')} entries)")
                print("\nTranscript Snippet:")
                transcript = result.get("transcript_text", "")
                print(f"  \"{transcript[:100]}...\"")
                print("==================================================")
                break
            elif status == "failed":
                print(f"\n❌ Analysis Failed at stage '{stage}':")
                print(result.get("error"))
                break
            else:
                # Still processing
                print(f"  ⏳ Status: {status} | Stage: {stage}...")
                time.sleep(5)
        else:
            print(f"❌ API Error: {res.text}")
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the POW Analyzer API")
    parser.add_argument("video", help="Path to test video (.mp4)")
    parser.add_argument("photo", help="Path to test photo (.jpg)")
    parser.add_argument("--task", default="task_04_bcd_to_7seg_decoder", help="Task ID to test against")
    parser.add_argument("--student", default="test_student_123", help="Student ID to use")
    
    args = parser.parse_args()
    test_pipeline(args.video, args.photo, args.task, args.student)
