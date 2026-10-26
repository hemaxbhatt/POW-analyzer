"""
Batch-run evaluation script for student digital clock submissions.
"""
import os, glob, time, json, requests

VIDEO_DIR = r"D:\IITGN\videos"
PHOTO_PATH = r"D:\IITGN\madhava\board.jpg"  # placeholder reference photo
TASK_ID = "task_05_digital_clock"

clock_videos = [
    "TheMultiplexers_25110049_CLOCK.mp4",
    "Gatekeepers_AS_25110019_Clock.mp4",
    "Logic_Mates_25110074_CLOCK.mp4",
    "Nanometers_25110162_Clock.mp4",
    "AAJ_Tak_25110140_CLOCK.mp4",
    "threeBits_25110268_CLOCK.mp4",
]

results = []

for vname in clock_videos:
    vpath = os.path.join(VIDEO_DIR, vname)
    if not os.path.exists(vpath):
        print(f"Skipping {vname} (file not found)")
        continue

    student_id = vname.replace(".mp4", "")
    print(f"\n=======================================================")
    print(f"Starting submission: {student_id}")
    print(f"=======================================================")

    t0 = time.time()
    resp = requests.post("http://127.0.0.1:8000/test/local-analyze", json={
        "video_path": vpath,
        "photo_path": PHOTO_PATH,
        "task_id": TASK_ID,
        "student_id": student_id,
    })

    if resp.status_code != 200:
        print(f"Trigger failed: {resp.status_code} {resp.text}")
        continue

    sid = resp.json()["submission_id"]
    print(f"Submission ID: {sid}. Polling result...")

    while True:
        r = requests.get(f"http://127.0.0.1:8000/submissions/{sid}/result").json()
        stage = r.get("stage")
        status = r.get("status")
        print(f"  [{time.time()-t0:.1f}s] Stage: {stage} | Status: {status}")

        if status in ("completed", "failed"):
            dur = time.time() - t0
            f = r.get("fusion") or {}
            v = r.get("verification") or {}
            rb = r.get("rubric") or {}
            af = r.get("anti_fraud") or {}
            st = r.get("reader_stats") or {}

            item = {
                "student_id": student_id,
                "video": vname,
                "duration_s": round(dur, 1),
                "status": status,
                "decision": f.get("decision", "unknown").upper(),
                "fused_score": round(f.get("fused_score", 0.0) * 100, 1),
                "cv_score": round(v.get("score", 0.0) * 100, 1),
                "displays_found": st.get("displays_found", 0),
                "frames_registered": st.get("frames_registered", 0),
                "rubric_score": round(rb.get("score", 0.0) * 100, 1),
                "rubric_reason": rb.get("reasoning", ""),
                "anti_fraud_match": af.get("is_match"),
                "anti_fraud_inliers": af.get("inlier_count"),
            }
            results.append(item)
            print(f"COMPLETED in {dur:.1f}s: Decision={item['decision']}, Fused={item['fused_score']}%, Rubric={item['rubric_score']}%")
            break

        time.sleep(6)

# Save markdown report
md_lines = [
    "# Batch Evaluation Report — Digital Clock Submissions",
    f"*Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}*",
    "",
    "| Student / Team | Decision | Fused Score | CV Score | Displays | Rubric Score | Anti-Fraud | Rubric Feedback |",
    "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
]

for r in results:
    md_lines.append(
        f"| **{r['student_id']}** | **{r['decision']}** | {r['fused_score']}% | {r['cv_score']}% | {r['displays_found']} | {r['rubric_score']}% | Inliers: {r['anti_fraud_inliers']} | {r['rubric_reason']} |"
    )

report_text = "\n".join(md_lines)
with open("batch_clock_results.md", "w", encoding="utf-8") as f:
    f.write(report_text)

print("\n\n" + report_text)
