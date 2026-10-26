import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

def verify_submission_match(video_path: str, photo_path: str) -> dict:
    """
    Compares the uploaded photo against a frame from the video to ensure
    they feature the same breadboard/circuit.
    
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

        # 2. Extract a frame from the middle of the video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Could not open video file."}
        
        # Get total frames and seek to the middle (gives a good chance of a clear shot)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        mid_frame_idx = max(0, total_frames // 2)
        cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame_idx)
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Could not read frame from video."}
            
        video_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 3. Initialize SIFT detector
        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(photo, None)
        kp2, des2 = sift.detectAndCompute(video_gray, None)

        if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
            return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Not enough features detected in images."}

        # 4. Feature Matching using FLANN (Fast Library for Approximate Nearest Neighbors)
        index_params = dict(algorithm=1, trees=5) # FLANN_INDEX_KDTREE = 1
        search_params = dict(checks=50)
        flann = cv2.FlannBasedMatcher(index_params, search_params)

        matches = flann.knnMatch(des1, des2, k=2)

        # 5. Apply Lowe's ratio test to find "good" matches
        good_matches = []
        for match_group in matches:
            if len(match_group) == 2:
                m, n = match_group
                if m.distance < 0.7 * n.distance:
                    good_matches.append(m)

        # 6. Homography check (RANSAC) to ensure structural geometry matches
        MIN_MATCH_COUNT = 30
        
        if len(good_matches) < MIN_MATCH_COUNT:
            return {
                "is_match": False, 
                "inlier_count": len(good_matches),
                "match_score": 0.0, 
                "reason": f"Only {len(good_matches)} good matches found (need {MIN_MATCH_COUNT}). Likely different circuits."
            }

        # Extract coordinates of the good matches
        src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)

        # Find homography matrix and inliers
        H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        
        if mask is None:
             return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": "Homography computation failed."}
             
        inliers = np.sum(mask)
        match_score = float(inliers / len(good_matches))

        # Decision Thresholds
        # If we have more than 40 structural inliers, it's definitely the same board
        is_match = inliers >= 40
        
        return {
            "is_match": bool(is_match),
            "inlier_count": int(inliers),
            "match_score": round(match_score, 3),
            "reason": f"Found {inliers} structural inliers between photo and video."
        }

    except Exception as e:
        logger.error(f"Anti-fraud check failed: {e}")
        return {"is_match": False, "inlier_count": 0, "match_score": 0.0, "reason": f"Error: {e}"}
