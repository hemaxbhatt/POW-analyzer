import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

def _evaluate_frame_match(kp1, des1, frame_gray, flann) -> tuple[int, float, str]:
    sift = cv2.SIFT_create()
    kp2, des2 = sift.detectAndCompute(frame_gray, None)
    if des2 is None or len(des2) < 10:
        return 0, 0.0, "Not enough features in frame."

    matches = flann.knnMatch(des1, des2, k=2)
    good_matches = []
    for match_group in matches:
        if len(match_group) == 2:
            m, n = match_group
            if m.distance < 0.7 * n.distance:
                good_matches.append(m)

    MIN_MATCH_COUNT = 30
    if len(good_matches) < MIN_MATCH_COUNT:
        return len(good_matches), 0.0, f"Only {len(good_matches)} good matches found (need {MIN_MATCH_COUNT})."

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if mask is None:
        return 0, 0.0, "Homography computation failed."

    inliers = int(np.sum(mask))
    match_score = float(inliers / len(good_matches))
    return inliers, match_score, f"Found {inliers} structural inliers."


def verify_submission_match(video_path: str, photo_path: str) -> dict:
    """
    Compares the uploaded photo against candidate frames from the video to ensure
    they feature the same breadboard/circuit, avoiding transient hand occlusions.
    
    Returns:
        dict: {
            "is_match": bool,
            "inlier_count": int,
            "match_score": float,
            "reason": str
        }
    """
    try:
        # 1. Load the photo
        photo = cv2.imread(photo_path, cv2.IMREAD_GRAYSCALE)
        if photo is None:
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Could not read photo file."}

        # 2. Extract candidate frames across the video (25%, 50%, 75%)
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Could not open video file."}

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_fractions = [0.25, 0.50, 0.75]
        candidate_indices = [max(0, min(total_frames - 1, int(f * total_frames))) for f in sample_fractions]

        candidate_frames = []
        for idx in set(candidate_indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                candidate_frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        cap.release()

        if not candidate_frames:
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Could not read frames from video."}

        # 3. Detect SIFT on reference photo
        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(photo, None)
        if des1 is None or len(des1) < 10:
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Not enough features detected in photo."}

        # 4. Flann matcher
        index_params = dict(algorithm=1, trees=5)  # FLANN_INDEX_KDTREE = 1
        search_params = dict(checks=50)
        flann = cv2.FlannBasedMatcher(index_params, search_params)

        # 5. Evaluate candidate frames and select best inlier match
        best_inliers, best_score, best_reason = 0, 0.0, "No candidate match."
        for frame_gray in candidate_frames:
            inliers, score, reason = _evaluate_frame_match(kp1, des1, frame_gray, flann)
            if inliers > best_inliers:
                best_inliers, best_score, best_reason = inliers, score, reason
            if best_inliers >= 80:  # Early exit on strong confirmed match
                break

        is_match = best_inliers >= 40
        return {
            "is_match": bool(is_match),
            "inlier_count": int(best_inliers),
            "match_score": round(best_score, 3),
            "reason": f"Found {best_inliers} structural inliers between photo and video."
        }

    except Exception as e:
        logger.error(f"Anti-fraud check failed: {e}")
        return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": f"Error: {e}"}
