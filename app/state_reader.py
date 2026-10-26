"""
State reader (Phase 3 front-end): video -> observation stream.

Turns a submission video into the list of readings that verification.py
consumes:

    [{"t_ms": 18200, "inputs": {}, "outputs": {"disp1": "1"}}, ...]

For each sampled frame and each 7-segment display the value is one of
    "0".."9", "a".."f"   a valid glyph
    "off"                display clearly visible, no segment lit
    "invalid"            display visible, lit pattern is not a glyph
    None                 unreadable (hand in the way, lost registration, ...)

How it works
------------
1. Sample frames (default 6 fps) and REGISTER each one to a clean reference
   frame with SIFT + RANSAC homography on the breadboard. The camera moves
   and hands cover things, but the display then always lands in the same
   place, even while it is unlit or partly covered.
2. Find the display(s) in the reference frame (bright white-core segments
   with a red halo). At most `max_displays` (default 2), ordered left->right.
3. Per frame: crop the display ROI from the registered frame, reject frames
   where a hand / shadow covers it (skin + dark pixel test).
4. Fit the display box from the union of lit pixels, choose the display's
   rotation (0/90/180/270) by which one makes the lit patterns decode to
   valid glyphs most often, then read the 7 segments with a slanted layout.
5. Decode segment pattern -> glyph.

Display geometry (slanted 7-segment digit) was calibrated on the standard kit
display; see LAYOUT. Switch / button / LED reading is NOT in this module yet.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterator, Optional

import cv2
import numpy as np
from app.dip_detector import find_dip_switch, read_state as read_dip_state

# ------------------------------------------------------------------ constants
REG_WIDTH = 540            # width used for feature matching
CANON_WIDTH = 810          # width of the reference space crops are cut in
MIN_INLIERS = 40           # below this the registration is not trusted
TW, TH = 60, 90            # upright digit crop size used for reading
LIT_THRESHOLD = 222.0      # mean min-channel inside a segment: lit above this
SKIN_MAX, DARK_MAX = 0.03, 0.06   # occlusion limits inside the display box

# slanted 7-segment layout in the TWxTH upright crop (fitted on the kit display)
LAYOUT = dict(shear=10, left=0, width=48, t=9, gap=2)

# segment sets (a-g) -> glyph
GLYPHS = {
    "abcdef": "0", "bc": "1", "abdeg": "2", "abcdg": "3", "bcfg": "4",
    "acdfg": "5", "acdefg": "6", "abc": "7", "abcdefg": "8", "abcdfg": "9",
    # 7447-style BCD decoders draw 6 without the top bar and 9 without the
    # bottom bar. In this decimal ("bcd") style 'cdefg' therefore reads as 6,
    # so hex 'b' cannot be told apart from it.
    "cdefg": "6", "abcfg": "9",
    # hex letters with an unambiguous shape
    "abcefg": "a", "adef": "c", "bcdeg": "d", "adefg": "e", "aefg": "f",
}
DIGITS_ONLY = set("0123456789")


# ------------------------------------------------------------------ result types
@dataclass
class DisplayInfo:
    id: str
    box_ref: tuple            # (x0, y0, x1, y1) in canonical reference space
    rotation: Optional[int] = None      # degrees clockwise to make it upright
    orientation_confidence: float = 0.0
    readable_frames: int = 0
    warnings: list = field(default_factory=list)


@dataclass
class ReaderResult:
    observations: list
    displays: list
    warnings: list
    stats: dict


# ------------------------------------------------------------------ video access
def iter_sampled_frames(path: str, sample_fps: float = 6.0) -> Iterator[tuple]:
    """Yield (t_ms, full-res BGR frame) at roughly sample_fps.
    Orientation metadata (phone rotation) is applied."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"cannot open video: {path}")
    try:
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
    except Exception:
        pass
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step_ms = 1000.0 / sample_fps
    next_t, idx = 0.0, 0
    while True:
        if not cap.grab():
            break
        t_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if not t_ms or (idx > 0 and t_ms <= 0):
            t_ms = idx * 1000.0 / fps
        idx += 1
        if t_ms + 1e-6 >= next_t:
            ok, frame = cap.retrieve()
            if not ok:
                continue
            yield float(t_ms), frame
            next_t += step_ms
            if next_t < t_ms:               # fell behind (dropped frames)
                next_t = t_ms + step_ms
    cap.release()


def _small_gray(frame):
    s = REG_WIDTH / frame.shape[1]
    small = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return small, s


def _skin_dark_fraction(bgr) -> tuple:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    skin = (h >= 6) & (h <= 26) & (s >= 55) & (v >= 50)
    return float(skin.mean()), float((v < 95).mean())


# ------------------------------------------------------------------ registration
def _sift(gray):
    return cv2.SIFT_create(nfeatures=2000).detectAndCompute(gray, None)


def _register(kp, des, ref_kp, ref_des, matcher):
    if des is None or len(kp) < 10:
        return None, 0
    knn = matcher.knnMatch(des, ref_des, k=2)
    good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return None, 0
    src = np.float32([kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([ref_kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None or mask is None:
        return None, 0
    # reject degenerate transforms (wild scale / flip)
    det = np.linalg.det(H[:2, :2])
    if not (0.3 < det < 3.5):
        return None, 0
    return H, int(mask.sum())


# ------------------------------------------------------------------ display finding
def find_displays(frame, max_displays: int = 2) -> list:
    """Locate lit 7-segment displays in a full-res frame.
    Returns boxes (x, y, w, h) in that frame's pixel coordinates,
    ordered left->right, top->bottom.

    Candidates are clusters of bright white segment cores (wires and other red
    things have none); a red halo around the cluster confirms it is an LED."""
    b, g, r = [frame[..., i].astype(np.int16) for i in range(3)]
    halo = ((r >= 190) & (r - g >= 45) & (r - b >= 35)).astype(np.uint8)
    white = (np.minimum(np.minimum(r, g), b) >= 215).astype(np.uint8)
    W = frame.shape[1]
    k = max(5, int(W * 0.012)) | 1
    blob = cv2.dilate(white, np.ones((k, k), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(blob)
    cands = []
    for i in range(1, n):
        x, y, w, h, _a = st[i]
        if not (0.04 * W <= max(w, h) <= 0.45 * W):
            continue
        if not (0.45 <= w / h <= 2.3):
            continue
        wc = int((white[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)).sum())
        if wc < 0.0004 * W * W or not (0.08 <= wc / float(w * h) <= 0.75):
            continue
        m = int(0.2 * max(w, h))
        y0, x0 = max(0, y - m), max(0, x - m)
        halo_px = int(halo[y0:y + h + m, x0:x + w + m].sum())
        if halo_px < 0.15 * wc:                 # no red glow around it: not an LED
            continue
        cands.append((wc, (int(x), int(y), int(w), int(h))))

    # Fallback for red LED displays (no white core)
    if not cands:
        red_led = ((r >= 180) & (r - g >= 55) & (r - b >= 55)).astype(np.uint8)
        blob_red = cv2.dilate(red_led, np.ones((k, k), np.uint8))
        n_red, lab_red, st_red, _ = cv2.connectedComponentsWithStats(blob_red)
        for i in range(1, n_red):
            x, y, w, h, _a = st_red[i]
            if not (0.02 * W <= max(w, h) <= 0.40 * W):
                continue
            if not (0.4 <= w / float(h) <= 2.2):
                continue
            rc = int((red_led[y:y + h, x:x + w] & (lab_red[y:y + h, x:x + w] == i)).sum())
            if rc < 0.0003 * W * W or not (0.05 <= rc / float(w * h) <= 0.85):
                continue
            cands.append((rc, (int(x), int(y), int(w), int(h))))

    cands.sort(reverse=True)
    out = []
    for wc, (x, y, w, h) in cands:
        if out:
            top_wc, (tx, ty, tw, th) = out[0]
            similar = 0.6 <= (w * h) / float(tw * th) <= 1.7 and wc >= 0.35 * top_wc
            if not similar:
                continue
        out.append((wc, (x, y, w, h)))
        if len(out) >= max_displays:
            break
    boxes = [b_ for _, b_ in out]
    boxes.sort(key=lambda bx: (round(bx[0] / max(1, W * 0.05)), bx[1]))
    return boxes


# ------------------------------------------------------------------ segment geometry
def _polys(shear, left, width, t, gap=2):
    def X(x, y):
        return x + left + shear * (1 - y / TH)

    xl0, xl1, xr0, xr1 = 0, t, width - t, width
    ya0, ya1 = 0, t
    yg0, yg1 = TH / 2 - t / 2, TH / 2 + t / 2
    yd0, yd1 = TH - t, TH

    def rect(xa, xb, ya, yb):
        return np.array([[X(xa, ya), ya], [X(xb, ya), ya], [X(xb, yb), yb], [X(xa, yb), yb]], np.float32)

    return {
        "a": rect(xl1 + gap, xr0 - gap, ya0, ya1),
        "b": rect(xr0, xr1, ya1 + gap, yg0 - gap + t / 2),
        "c": rect(xr0, xr1, yg1 - t / 2 + gap, yd0 - gap),
        "d": rect(xl1 + gap, xr0 - gap, yd0, yd1),
        "e": rect(xl0, xl1, yg1 - t / 2 + gap, yd0 - gap),
        "f": rect(xl0, xl1, ya1 + gap, yg0 - gap + t / 2),
        "g": rect(xl1 + gap, xr0 - gap, yg0, yg1),
    }


def _segment_masks() -> dict:
    masks = {}
    for name, p in _polys(**LAYOUT).items():
        m = np.zeros((TH, TW), np.uint8)
        cv2.fillPoly(m, [np.round(p).astype(np.int32)], 1)
        masks[name] = cv2.erode(m, np.ones((3, 3), np.uint8)).astype(bool)
    return masks


_MASKS = _segment_masks()
_SEG_ORDER = "abcdefg"


def _rotate(img, rot):
    return {0: img,
            90: cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
            180: cv2.rotate(img, cv2.ROTATE_180),
            270: cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)}[rot]


def upright_crop(box_img, rot):
    """Rotate a display-box crop upright and resize to the reading size."""
    return cv2.resize(_rotate(box_img, rot), (TW, TH), interpolation=cv2.INTER_AREA)


def segment_scores(upright_bgr) -> dict:
    b, g, r = [upright_bgr[..., i].astype(np.float32) for i in range(3)]
    red_dom = r - np.maximum(g, b)
    if red_dom.mean() > 25.0:
        metric = np.clip(red_dom * 3.5, 0, 255)
    else:
        metric = upright_bgr.astype(np.float32).min(axis=2)
    return {k: float(metric[m].mean()) for k, m in _MASKS.items()}


def lit_string(scores: dict, thr: float = LIT_THRESHOLD) -> str:
    return "".join(k for k in _SEG_ORDER if scores[k] >= thr)


def decode_scores(scores: dict, thr: float = LIT_THRESHOLD) -> str:
    lit = lit_string(scores, thr)
    if not lit:
        return "off"
    return GLYPHS.get(lit, "invalid")


def render_glyph(lit_segments: str, lit=(255, 255, 255), unlit=(170, 165, 165)):
    """Synthetic upright TWxTH digit (used by tests)."""
    img = np.zeros((TH, TW, 3), np.uint8)
    img[:] = (150, 145, 145)
    for name, p in _polys(**LAYOUT).items():
        col = lit if name in lit_segments else unlit
        cv2.fillPoly(img, [np.round(p).astype(np.int32)], col)
    return img


# ------------------------------------------------------------------ occlusion
def is_occluded(box_img, pad_img=None) -> bool:
    ref = pad_img if pad_img is not None else box_img
    skin, dark = _skin_dark_fraction(ref)
    return skin > SKIN_MAX or dark > DARK_MAX


# ------------------------------------------------------------------ orientation
def choose_rotation(boxes: list) -> tuple:
    """boxes: display-box crops (BGR) of readable frames.
    Returns (rotation, confidence, note). Confidence = share of frames whose
    pattern decodes to a valid glyph under the chosen rotation."""
    if not boxes:
        return 90, 0.0, "no readable frames to choose orientation from"
    h, w = boxes[0].shape[:2]
    if w > h * 1.1:
        cands = (90, 270)
    elif h > w * 1.1:
        cands = (0, 180)
    else:
        cands = (0, 90, 180, 270)

    def score(rot):
        valid = digit = lit_frames = 0
        for b in boxes:
            sc = segment_scores(upright_crop(b, rot))
            sym = decode_scores(sc)
            if sym == "off":
                continue
            lit_frames += 1
            if sym != "invalid":
                valid += 1
                digit += sym in DIGITS_ONLY
        return (valid + 0.25 * digit) / max(1, lit_frames), valid / max(1, lit_frames)

    results = {r: score(r) for r in cands}
    best = max(cands, key=lambda r: (round(results[r][0], 6), -abs(r - 90)))
    ties = [r for r in cands if abs(results[r][0] - results[best][0]) < 1e-6]
    note = ""
    if len(ties) > 1:
        note = ("orientation ambiguous (patterns look the same in rotations "
                f"{sorted(ties)}); only symmetric glyphs like 0/8 seen?")
    return best, results[best][1], note


# ------------------------------------------------------------------ main entry
def read_video(path: str, sample_fps: float = 4.0, max_displays: int = 2,
               debug_dir: Optional[str] = None) -> ReaderResult:
    warnings: list = []

    # ---- pass 1: small frames, timestamps, hand fraction (for reference choice)
    times, smalls, hand = [], [], []
    for t_ms, fr in iter_sampled_frames(path, sample_fps):
        small, _ = _small_gray(fr)
        sk, dk = _skin_dark_fraction(small)
        times.append(t_ms)
        smalls.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        hand.append(sk)        # skin only: the dark floor would otherwise count as 'hand'
    n = len(times)
    if n == 0:
        raise ValueError("no frames could be read from the video")

    # ---- choose reference frame: sharp and hand-free; must show a lit display
    sharp = np.array([cv2.Laplacian(g, cv2.CV_64F).var() for g in smalls])
    quality = sharp * np.clip(1.0 - 8.0 * np.array(hand), 0, 1)
    order = [int(i) for i in np.argsort(-quality) if hand[i] < 0.06][:40]
    ref_i, boxes_full, ref_full = None, [], None
    want = set(order[:40]) | set(range(40))
    frames_cache = {}
    for i, (t_ms, fr) in enumerate(iter_sampled_frames(path, sample_fps)):
        if i in want:
            frames_cache[i] = fr
        if i >= max(want, default=0):
            break
    for i in order:
        fr = frames_cache.get(i)
        if fr is None:
            continue
        found = find_displays(fr, max_displays)
        if found:
            ref_i, boxes_full, ref_full = i, found, fr
            break
    dip_cand, dip_cand_i = None, None
    for i_fr, fr in frames_cache.items():
        cand = find_dip_switch(fr)
        if cand is None:
            continue
        # Prefer the candidate with the most levers found (ideally 4)
        if dip_cand is None or len(cand.lever_boxes) > len(dip_cand.lever_boxes):
            dip_cand, dip_cand_i = cand, i_fr
        elif len(cand.lever_boxes) == len(dip_cand.lever_boxes) and cand.score > dip_cand.score:
            dip_cand, dip_cand_i = cand, i_fr

    frames_cache.clear()
    if ref_i is None:
        warnings.append("could not find a lit 7-segment display in any clear frame")
        observations = [
            {
                "t_ms": times[i],
                "inputs": {},
                "outputs": {},
                "lit": {},
            }
            for i in range(n)
        ]
        stats = {
            "frames_sampled": n,
            "frames_registered": 0,
            "reference_frame_ms": None,
            "displays_found": 0,
            "sample_fps": sample_fps,
        }
        return ReaderResult(observations, [], warnings, stats)

    full_w = ref_full.shape[1]
    canon = CANON_WIDTH / full_w                       # full-res -> canonical
    a_small = REG_WIDTH / full_w                       # full-res -> feature space
    ref_kp, ref_des = _sift(smalls[ref_i])
    matcher = cv2.BFMatcher()

    # ROI (canonical coords) per display: box grown by a margin
    rois, infos = [], []
    for k, (x, y, w, h) in enumerate(boxes_full):
        m = 0.35 * max(w, h)
        x0, y0 = int((x - m) * canon), int((y - m) * canon)
        x1, y1 = int((x + w + m) * canon), int((y + h + m) * canon)
        rois.append((x0, y0, x1, y1))
        infos.append(DisplayInfo(id=f"disp{k + 1}" if max_displays > 1 or len(boxes_full) > 1 else "disp",
                                 box_ref=(x0, y0, x1, y1)))
    if len(boxes_full) == 1 and infos[0].id != "disp":
        infos[0].id = "disp"

    # ---- pass 2: register every frame
    Hs, inl = [], []
    for g in smalls:
        kp, des = _sift(g)
        H, ni = _register(kp, des, ref_kp, ref_des, matcher)
        Hs.append(H)
        inl.append(ni)

    # ---- pass 3: cut ROI crops from the full-res frames
    S_c = np.diag([CANON_WIDTH / REG_WIDTH] * 2 + [1.0])
    S_a = np.diag([a_small, a_small, 1.0])
    S_up = np.diag([1.0 / a_small, 1.0 / a_small, 1.0])
    crops = [[None] * n for _ in rois]
    dip_crops = [None] * n
    
    if dip_cand and Hs[dip_cand_i] is not None:
        M_dip = S_c @ Hs[dip_cand_i] @ S_a
        x, y, w, h = dip_cand.box
        pts = np.float32([[[x, y], [x+w, y+h]]])
        pts_c = cv2.perspectiveTransform(pts, M_dip)[0]
        dx_c = int(min(pts_c[0][0], pts_c[1][0]))
        dy_c = int(min(pts_c[0][1], pts_c[1][1]))
        dw_c = max(1, int(abs(pts_c[1][0] - pts_c[0][0])))
        dh_c = max(1, int(abs(pts_c[1][1] - pts_c[0][1])))
    else:
        dip_cand = None

    idx = 0
    for i, (t_ms, fr) in enumerate(iter_sampled_frames(path, sample_fps)):
        if i >= n:
            break
        if Hs[i] is None or inl[i] < MIN_INLIERS:
            continue
        M = S_c @ Hs[i] @ S_a
        for d, (x0, y0, x1, y1) in enumerate(rois):
            shift = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
            crops[d][i] = cv2.warpPerspective(fr, shift @ M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR)
            
        if dip_cand:
            shift_dip = np.array([[1, 0, -dx_c], [0, 1, -dy_c], [0, 0, 1]], float)
            dip_crops[i] = cv2.warpPerspective(fr, shift_dip @ M, (dw_c, dh_c), flags=cv2.INTER_LINEAR)

    # ---- per display: box fit, occlusion, orientation, decode
    per_display_vals, per_display_pats = [], []
    for d, info in enumerate(infos):
        cs = crops[d]
        valid_idx = [i for i in range(n) if cs[i] is not None]
        if not valid_idx:
            info.warnings.append("no frame registered well enough")
            per_display_vals.append([None] * n)
            per_display_pats.append([None] * n)
            continue
        # occlusion on the central part of the ROI (display + small margin)
        H_, W_ = cs[valid_idx[0]].shape[:2]
        cx0, cy0, cx1, cy1 = int(W_ * 0.18), int(H_ * 0.18), int(W_ * 0.82), int(H_ * 0.82)
        clear = [i for i in valid_idx if not is_occluded(cs[i][cy0:cy1, cx0:cx1])]
        if len(clear) < 6:
            info.warnings.append("display almost never clearly visible")
            per_display_vals.append([None] * n)
            per_display_pats.append([None] * n)
            continue
        # display box = biggest blob of pixels that are white-lit in >=6% of clear frames
        acc = np.zeros((H_, W_), np.float32)
        for i in clear:
            acc += (cs[i].min(axis=2) >= 215)
        m = (acc >= max(3, 0.06 * len(clear))).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        nl, lab, st, _ = cv2.connectedComponentsWithStats(m)
        if nl < 2:
            info.warnings.append("no lit segments seen in clear frames")
            per_display_vals.append([None] * n)
            per_display_pats.append([None] * n)
            continue
        kbest = 1 + int(np.argmax(st[1:, 4]))
        bx, by, bw, bh = st[kbest, :4]
        box = (int(bx), int(by), int(bx + bw), int(by + bh))
        asp = bw / float(bh)
        if not (0.5 <= asp <= 0.85 or 1.2 <= asp <= 2.0):
            info.warnings.append(f"display box aspect {asp:.2f} looks unusual; some segments may never light")
        bx0, by0, bx1, by1 = box
        boxes_clear = [cs[i][by0:by1, bx0:bx1] for i in clear]
        rot, conf, note = choose_rotation(boxes_clear)
        info.rotation, info.orientation_confidence = rot, conf
        if note:
            info.warnings.append(note)
        if conf < 0.6:
            info.warnings.append(f"only {conf:.0%} of lit frames decode to valid glyphs; check display mounting/layout")

        clear_set = set(clear)
        vals, pats = [], []
        for i in range(n):
            if i not in clear_set:
                vals.append(None)
                pats.append(None)
                continue
            sc = segment_scores(upright_crop(cs[i][by0:by1, bx0:bx1], rot))
            vals.append(decode_scores(sc))
            pats.append(lit_string(sc))
        per_display_pats.append(pats)
        info.readable_frames = sum(v is not None for v in vals)
        per_display_vals.append(vals)

        if debug_dir:
            _write_debug(debug_dir, info.id, cs, times, vals, box, rot)

    # ---- read DIP switch states
    dip_vals = [None] * n
    if dip_cand:
        from dataclasses import replace
        # The DIP crops are in canonical space (full-res coords * canon), so
        # scale the lever_boxes from full-res to canonical too
        scaled_levers = [
            (int(lx * canon), int(ly * canon), max(1, int(lw * canon)), max(1, int(lh * canon)))
            for (lx, ly, lw, lh) in dip_cand.lever_boxes
        ]
        local_cand = replace(
            dip_cand,
            box=(0, 0, max(1, int(dip_cand.box[2] * canon)), max(1, int(dip_cand.box[3] * canon))),
            lever_boxes=scaled_levers
        )
        for i in range(n):
            if dip_crops[i] is not None:
                dip_vals[i] = read_dip_state(dip_crops[i], local_cand)
                if debug_dir:
                    import os
                    os.makedirs(debug_dir, exist_ok=True)
                    cv2.imwrite(os.path.join(debug_dir, f"dip_crop_{i:03d}.jpg"), dip_crops[i])

    observations = []
    for i in range(n):
        obs_inputs = {}
        if dip_vals[i] is not None:
            # Levers detected left-to-right, but sw1(MSB) is physically rightmost.
            # Reversing maps image-left-to-right → logical MSB-to-LSB.
            obs_inputs["sw"] = dip_vals[i][::-1]
            
        observations.append({
            "t_ms": times[i],
            "inputs": obs_inputs,
            "outputs": {info.id: per_display_vals[d][i] for d, info in enumerate(infos)},
            "lit": {info.id: per_display_pats[d][i] for d, info in enumerate(infos)},
        })

    stats = {
        "frames_sampled": n,
        "frames_registered": int(sum(h is not None and inl[i] >= MIN_INLIERS for i, h in enumerate(Hs))),
        "reference_frame_ms": times[ref_i],
        "displays_found": len(infos),
        "sample_fps": sample_fps,
    }
    for info in infos:
        warnings += [f"{info.id}: {w}" for w in info.warnings]
    return ReaderResult(observations, infos, warnings, stats)


def _write_debug(debug_dir, disp_id, crops, times, vals, box, rot):
    os.makedirs(debug_dir, exist_ok=True)
    tiles = []
    for i, c in enumerate(crops):
        if c is None:
            t = np.zeros((TH * 2, TW * 2, 3), np.uint8)
            label = "n/a"
        else:
            bx0, by0, bx1, by1 = box
            t = cv2.resize(upright_crop(c[by0:by1, bx0:bx1], rot), (TW * 2, TH * 2))
            label = str(vals[i])
        cv2.putText(t, f"{times[i] / 1000:.1f}s", (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        cv2.putText(t, label, (3, TH * 2 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 0) if vals[i] not in (None, "invalid") else (0, 0, 255), 2)
        tiles.append(t)
    cols = 12
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[j:j + cols]) for j in range(0, len(tiles), cols)]
    cv2.imwrite(os.path.join(debug_dir, f"{disp_id}_timeline.jpg"), np.vstack(rows))


# ------------------------------------------------------------------ CLI
if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Read 7-segment display states from a video.")
    ap.add_argument("video")
    ap.add_argument("--fps", type=float, default=6.0)
    ap.add_argument("--max-displays", type=int, default=2)
    ap.add_argument("--out", default="observations.json")
    ap.add_argument("--debug-dir", default=None)
    ap.add_argument("--tasks", default=None, help="tasks JSON; also run verification")
    ap.add_argument("--task-id", default=None)
    args = ap.parse_args()

    res = read_video(args.video, args.fps, args.max_displays, args.debug_dir)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(res.observations, f)
    if args.tasks and args.task_id:
        from app.verification import load_tasks, verify
        print(verify(load_tasks(args.tasks)[args.task_id], res.observations).summary())
    print(json.dumps({"stats": res.stats,
                      "displays": [d.__dict__ for d in res.displays],
                      "warnings": res.warnings}, indent=2, default=str))
