"""Full pipeline test on a clock video."""
import requests, json, time

VIDEO = r"D:\IITGN\videos\TheMultiplexers_25110049_CLOCK.mp4"
PHOTO = r"D:\IITGN\madhava\board.jpg"   # placeholder — no real photo for this student
TASK  = "task_05_digital_clock"

r = requests.post("http://127.0.0.1:8000/test/local-analyze", json={
    "video_path": VIDEO,
    "photo_path": PHOTO,
    "task_id": TASK,
    "student_id": "TheMultiplexers-25110049",
})
print("Trigger:", r.status_code, r.json())
sid = r.json()["submission_id"]
print("Submission ID:", sid)

while True:
    d = requests.get(f"http://127.0.0.1:8000/submissions/{sid}/result").json()
    print("  Stage:", d.get("stage"), "| Status:", d.get("status"))
    if d["status"] in ("completed", "failed"):
        f = d.get("fusion") or {}
        v = d.get("verification") or {}
        rb = d.get("rubric") or {}
        af = d.get("anti_fraud") or {}
        print("\n=== RESULT ===")
        print(f"Decision:     {f.get('decision','?').upper()}")
        print(f"Fused score:  {f.get('fused_score',0)*100:.0f}%")
        print(f"CV score:     {v.get('score',0)*100:.0f}%  ({v.get('satisfied_count',0)}/{v.get('total_count',0)} entries)")
        print(f"Rubric score: {rb.get('score',0)*100:.0f}%")
        print(f"Rubric reason: {rb.get('reasoning','')}")
        print(f"Anti-fraud:   match={af.get('is_match')}  inliers={af.get('inlier_count')}")
        print(f"Transcript:   {d.get('transcript_text','')[:300]}")
        break
    time.sleep(5)
