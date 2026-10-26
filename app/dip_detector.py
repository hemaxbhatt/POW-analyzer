"""
DIP switch detector — fixed version.

What was wrong with the original scratch_test_dip.py
------------------------------------------------------
It picked candidates using only 3 numbers: contour area, solidity
(area / convex-hull-area), and bounding-box aspect ratio. The problem is
that those three numbers don't uniquely describe a DIP switch — a tight
cluster of jumper wires, or the IC footprint with its surrounding solder
pads, can score just as "solid and squarish" as the real switch, depending
on exactly how the morphological close operation happens to bridge gaps
between components. That's why the debug image showed boxes around the
wire cluster and the IC instead of the switch.

The fix
-------
A DIP switch has one property nothing else on the board has: **4 white
toggle levers of nearly identical size, evenly spaced in a row (or
column)**. Measured on the real photo:

    true switch : white blobs sized [156, 167, 171, 179] (+ small text bits)
    IC region   : white blobs sized [... 2100, 3841, 5896, 17770] (huge, uneven)
    wire tangle : only 3 blobs, sizes [21, 65, 114] (uneven)

So instead of trusting solidity/aspect alone, we now use them only to get
a short list of red candidates, then require each candidate to contain a
tight cluster of same-sized, evenly-spaced white blobs before accepting
it. This is a much stronger, more specific signature.

Usage
-----
    python dip_detector.py path/to/frame.jpg
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

# ------------------------------------------------------------------ tuning
RED_RANGES = [((0, 70, 50), (10, 255, 255)), ((170, 70, 50), (180, 255, 255))]
WHITE_RANGE = ((0, 0, 150), (180, 70, 255))
MIN_AREA, MAX_AREA = 300, 8000          # red blob area, px^2 (widened vs. original 400-5000)
MIN_SOLIDITY = 0.55                      # widened vs. original 0.85 -- solidity alone no longer decides
ASPECT_RANGE = (0.4, 2.5)                # widened vs. original 0.8-1.6: tolerates 2-8 position switches
                                          # AND a switch whose red blob merges with one adjacent wire
MIN_LEVERS, MAX_LEVERS = 3, 4            # tolerate 1 lever occluded/merged, max 4
LEVER_SIZE_SPREAD = 2.5                  # tolerates video-compressed lever blobs; aspect ratio filter handles wires
MIN_BOX_W, MIN_BOX_H = 40, 55           # portrait DIP switch body (63x73 = real switch)
MIN_BOX_ASPECT = 0.7                     # w/h must be <= 1.43; rejects wire bundles (90x58 = 1.55)


@dataclass
class DipCandidate:
    box: tuple            # (x, y, w, h) in the source image
    lever_boxes: list      # [(x, y, w, h), ...] in ROI-local coords, left/top -> right/bottom
    axis: str              # "row" (levers side by side) or "column" (stacked)
    score: float           # higher is more switch-like


def _red_mask(img) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = np.zeros(img.shape[:2], np.uint8)
    for lo, hi in RED_RANGES:
        mask |= cv2.inRange(hsv, np.array(lo), np.array(hi))
    k = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    return mask


def _lever_cluster(roi) -> Optional[tuple]:
    """Look for a tight cluster of similar-sized white blobs = toggle levers.
    Returns (lever_boxes, axis) or None."""
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array(WHITE_RANGE[0]), np.array(WHITE_RANGE[1]))
    n, lab, st, _ = cv2.connectedComponentsWithStats(white)
    blobs = [tuple(st[i][:4]) for i in range(1, n) if st[i][4] >= 8]
    if len(blobs) < MIN_LEVERS:
        return None

    areas = np.array([w * h for (_, _, w, h) in blobs], float)
    order = np.argsort(areas)                          # smallest first
    best = None
    # Levers are NOT reliably "the biggest white blobs" -- if the red mask
    # merges in a stray wire, that wire's highlight can out-size the actual
    # levers (seen on real footage: glare blobs of 1800-2700px vs. levers
    # at ~170px). So instead of only trying the top-K largest, slide a
    # window of every size across ALL blobs sorted by area, and look for
    # ANY tight same-sized group, wherever it falls in that ordering.
    for k in range(MAX_LEVERS, MIN_LEVERS - 1, -1):
        if k > len(order):
            continue
        for start in range(0, len(order) - k + 1):
            idx = order[start:start + k]
            a = areas[idx]
            spread = (a.max() - a.min()) / a.mean()
            if spread > LEVER_SIZE_SPREAD:
                continue
            chosen = [blobs[i] for i in idx]
            xs = [b[0] + b[2] / 2 for b in chosen]
            ys = [b[1] + b[3] / 2 for b in chosen]
            row_like = np.std(ys) < np.std(xs)        # centers line up more in y -> side by side
            chosen.sort(key=lambda b: b[0] if row_like else b[1])
            # evenly spaced check along the axis of separation
            centers = sorted(xs if row_like else ys)
            gaps = np.diff(centers)
            if len(gaps) and (gaps.max() - gaps.min()) / gaps.mean() > 0.6:
                continue
            score = k - spread                         # prefer more levers, tighter size match
            if best is None or score > best[0]:
                best = (score, chosen, "row" if row_like else "column")
    if best is None:
        return None
    _, chosen, axis = best
    return chosen, axis


def _longest_true_run(flags: np.ndarray, min_run: int) -> tuple:
    """Longest contiguous True stretch in `flags`, at least min_run long.
    Falls back to the full range if nothing qualifies."""
    best_len, best_start = 0, 0
    run_start = None
    for i, v in enumerate(flags.tolist() + [False]):   # sentinel flushes the last run
        if v and run_start is None:
            run_start = i
        elif not v and run_start is not None:
            if i - run_start > best_len:
                best_len, best_start = i - run_start, run_start
            run_start = None
    if best_len < min_run:
        return 0, len(flags)
    return best_start, best_start + best_len


def _trim_to_dense_core(mask_roi: np.ndarray, min_fill: float = 0.35, min_run: int = 5) -> tuple:
    """A real switch body is solid (high red-pixel fill) across nearly its
    full width AND height. A merged-in wire tail is thin and sparse in
    whichever direction it extends. So: keep only the longest contiguous
    stretch of rows that are mostly filled, then the same for columns
    within that -- this trims a merged wire tail off from whichever side
    it's attached, without needing to know in advance which side that is.
    Returns (x0, y0, w, h) relative to mask_roi."""
    h, w = mask_roi.shape
    row_fill = mask_roi.astype(np.float32).sum(axis=1) / 255.0 / max(1, w)
    y0, y1 = _longest_true_run(row_fill >= min_fill, min_run)
    sub = mask_roi[y0:y1]
    col_fill = sub.astype(np.float32).sum(axis=0) / 255.0 / max(1, sub.shape[0])
    x0, x1 = _longest_true_run(col_fill >= min_fill, min_run)
    return x0, y0, x1 - x0, y1 - y0


def find_dip_switch(img) -> Optional[DipCandidate]:
    mask = _red_mask(img)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: Optional[DipCandidate] = None
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)
        if not (MIN_AREA <= area <= MAX_AREA):
            continue
        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        if hull_area == 0:
            continue
        solidity = area / hull_area
        aspect = w / float(h)
        if solidity < MIN_SOLIDITY or not (ASPECT_RANGE[0] <= aspect <= ASPECT_RANGE[1]):
            continue
        # trim off any merged-in wire tail before doing anything else, so
        # neither the lever search nor the state reading ever sees it
        tx, ty, tw, th = _trim_to_dense_core(mask[y:y + h, x:x + w])
        x, y, w, h = x + tx, y + ty, tw, th
        if w < MIN_BOX_W or h < MIN_BOX_H:
            continue                                       # too small to be a real 4-pos DIP switch
        if (w / float(h)) > (1.0 / MIN_BOX_ASPECT):
            continue                                       # too wide/flat — wire bundle, not a switch
        roi = img[y:y + h, x:x + w]
        result = _lever_cluster(roi)
        if result is None:
            continue                                       # the deciding filter: no lever pattern, reject
        levers, axis = result
        # Lever count contributes 0.3 per lever (4 levers = 1.2) vs solidity max ~1.0
        # This ensures a proper 4-lever switch beats high-solidity tiny blobs
        score = 0.3 * len(levers) + solidity
        cand = DipCandidate((x, y, w, h), levers, axis, score)
        if best is None or cand.score > best.score:
            best = cand
    return best


def read_state(img, candidate: DipCandidate) -> str:
    """'1' = lever toward the low-coordinate side of its slot, '0' = the other side.
    NOTE: which physical side means logical ON has NOT been confirmed against a
    known switch position yet -- treat this as a raw position readout, and
    calibrate the 0/1 <-> ON/OFF mapping against a frame where the true circuit
    state is independently known (see the note at the bottom of this file).

    IMPORTANT: each lever's travel range is measured across the FULL switch
    box (the whole height, for a row-mounted switch), not just the lever's
    own tight bounding box -- a blob's centroid within its own bounding box
    is always near the middle, by definition, so that would never be able
    to tell top from bottom. The lever_boxes' x-span (or y-span, for a
    column-mounted switch) is what locates each slot; where the lever sits
    within the box's full height (or width) is what tells us the position."""
    # candidate.box is already trimmed to the switch's dense rectangular
    # core (see _trim_to_dense_core), so its own full height (row-mounted)
    # or width (column-mounted) is a reliable travel range -- it no longer
    # includes a merged-in wire tail that would otherwise skew the midline.
    x, y, w, h = candidate.box
    roi = img[y:y + h, x:x + w]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array(WHITE_RANGE[0]), np.array(WHITE_RANGE[1]))
    state = ""
    for (lx, ly, lw, lh) in candidate.lever_boxes:
        if candidate.axis == "row":
            slot = white[0:h, lx:lx + lw]
        else:
            slot = white[ly:ly + lh, 0:w]
        M = cv2.moments(slot, binaryImage=True)
        if M["m00"] == 0:
            state += "x"
            continue
        if candidate.axis == "row":
            c = M["m01"] / M["m00"]
            state += "0" if c < h / 2 else "1"
        else:
            c = M["m10"] / M["m00"]
            state += "0" if c < w / 2 else "1"
    return state


def annotate(img, candidate: Optional[DipCandidate]):
    out = img.copy()
    if candidate is None:
        return out
    x, y, w, h = candidate.box
    cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
    for (lx, ly, lw, lh) in candidate.lever_boxes:
        cv2.rectangle(out, (x + lx, y + ly), (x + lx + lw, y + ly + lh), (255, 0, 255), 1)
    return out


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "board.jpg"
    img = cv2.imread(path)
    if img is None:
        print(f"could not read {path}")
        sys.exit(1)

    cand = find_dip_switch(img)
    if cand is None:
        print("no DIP switch found")
        sys.exit(0)

    x, y, w, h = cand.box
    print(f"DIP switch found at x={x} y={y} w={w} h={h} "
          f"({len(cand.lever_boxes)} levers, axis={cand.axis}, score={cand.score:.2f})")
    state = read_state(img, cand)
    print(f"Raw lever positions: {state}  "
          f"(0/1 <-> ON/OFF mapping not yet calibrated, see module docstring)")
    cv2.imwrite("dip_debug.jpg", annotate(img, cand))
    print("Saved dip_debug.jpg")
