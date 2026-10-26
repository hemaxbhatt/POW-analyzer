"""Tests for state_reader.py. Synthetic images only, except one optional
end-to-end test that runs when POW_SAMPLE_VIDEO points at a real video."""
import os

import cv2
import numpy as np
import pytest

from app import state_reader as sr

# lit segments for each digit as a 7447 BCD decoder draws them
DIGIT_SEGS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "cdefg", "7": "abc", "8": "abcdefg", "9": "abcfg",
}


def mounted(lit, rot):
    """Synthetic display box as the camera would see it when the display must be
    rotated `rot` degrees clockwise to stand upright."""
    up = sr.render_glyph(lit)
    inverse = {0: 0, 90: 270, 180: 180, 270: 90}[rot]
    return sr._rotate(up, inverse)


# ---------------------------------------------------------------- decoding

@pytest.mark.parametrize("digit,segs", DIGIT_SEGS.items())
def test_every_digit_decodes_upright(digit, segs):
    scores = sr.segment_scores(sr.render_glyph(segs))
    assert sr.decode_scores(scores) == digit


def test_blank_and_invalid():
    assert sr.decode_scores(sr.segment_scores(sr.render_glyph(""))) == "off"
    assert sr.decode_scores(sr.segment_scores(sr.render_glyph("af"))) == "invalid"


def test_lit_unlit_threshold_has_margin():
    lit = sr.segment_scores(sr.render_glyph("abcdefg"))
    unlit = sr.segment_scores(sr.render_glyph(""))
    assert min(lit.values()) > sr.LIT_THRESHOLD + 20
    assert max(unlit.values()) < sr.LIT_THRESHOLD - 20


# ---------------------------------------------------------------- orientation

@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_choose_rotation_finds_true_mounting(rot):
    boxes = [mounted(DIGIT_SEGS[d], rot) for d in "0123456789" for _ in range(3)]
    got, conf, _ = sr.choose_rotation(boxes)
    assert got == rot
    assert conf > 0.95


def test_orientation_restricted_by_box_aspect():
    boxes = [mounted(DIGIT_SEGS[d], 90) for d in "13"]      # landscape box
    assert boxes[0].shape[1] > boxes[0].shape[0]
    got, _, _ = sr.choose_rotation(boxes)
    assert got in (90, 270)


def test_symmetric_only_patterns_are_flagged_ambiguous():
    boxes = [mounted(DIGIT_SEGS[d], 90) for d in "08" for _ in range(4)]
    _, _, note = sr.choose_rotation(boxes)
    assert "ambiguous" in note


def test_choose_rotation_handles_no_frames():
    rot, conf, note = sr.choose_rotation([])
    assert conf == 0.0 and note


# ---------------------------------------------------------------- occlusion

def test_clear_display_is_not_occluded():
    assert not sr.is_occluded(sr.render_glyph("abcdefg"))


def test_skin_coloured_patch_is_occluded():
    img = sr.render_glyph("abcdefg")
    img[:] = (110, 150, 205)                    # BGR skin tone
    assert sr.is_occluded(img)


def test_dark_shadow_is_occluded():
    img = sr.render_glyph("abcdefg")
    img[: img.shape[0] // 2] = (30, 30, 35)
    assert sr.is_occluded(img)


# ---------------------------------------------------------------- finding displays

def synth_frame(display_positions, size=(1080, 1920)):
    """Concrete-grey frame with lit 'digit 8' displays (white core + red halo),
    a tall white paper label and a thin red wire as distractors."""
    w, h = size
    frame = np.full((h, w, 3), (120, 125, 125), np.uint8)
    cv2.rectangle(frame, (200, 480), (500, 1320), (235, 235, 235), -1)          # paper label
    cv2.line(frame, (620, 300), (700, 900), (60, 60, 210), 6)                    # red wire
    for (x, y) in display_positions:
        g = cv2.resize(sr.render_glyph("abcdefg"), (110, 165), interpolation=cv2.INTER_CUBIC)
        white = (g.min(axis=2) >= 215).astype(np.uint8)
        halo = cv2.dilate(white, np.ones((9, 9), np.uint8)) - white
        patch = np.full_like(g, (170, 170, 175))
        patch[halo > 0] = (90, 90, 225)
        patch[white > 0] = (255, 255, 255)
        frame[y:y + 165, x:x + 110] = patch
    return frame


def test_find_single_display_ignores_label_and_wire():
    boxes = sr.find_displays(synth_frame([(700, 900)]))
    assert len(boxes) == 1
    x, y, w, h = boxes[0]
    assert abs((x + w / 2) - 755) < 40 and abs((y + h / 2) - 982) < 40


def test_find_two_displays_ordered_left_to_right():
    boxes = sr.find_displays(synth_frame([(650, 900), (300, 1400)]), max_displays=2)
    assert len(boxes) == 2
    assert boxes[0][0] < boxes[1][0]


def test_max_displays_respected():
    boxes = sr.find_displays(synth_frame([(650, 900), (300, 1400)]), max_displays=1)
    assert len(boxes) == 1


def test_no_lit_display_returns_empty():
    frame = np.full((1920, 1080, 3), (120, 125, 125), np.uint8)
    assert sr.find_displays(frame) == []


# ---------------------------------------------------------------- registration

def test_register_recovers_known_shift():
    rng = np.random.default_rng(3)
    base = np.full((960, 540), 140, np.uint8)
    for _ in range(300):                                      # random blobs = texture
        x, y = rng.integers(20, 500), rng.integers(20, 920)
        cv2.circle(base, (int(x), int(y)), int(rng.integers(4, 14)), int(rng.integers(30, 250)), -1)
    base = cv2.GaussianBlur(base, (3, 3), 0)
    M = np.float32([[1, 0, 25], [0, 1, -18]])
    moved = cv2.warpAffine(base, M, (540, 960), borderValue=140)
    kp_r, de_r = sr._sift(base)
    kp, de = sr._sift(moved)
    H, inl = sr._register(kp, de, kp_r, de_r, cv2.BFMatcher())
    assert H is not None and inl >= sr.MIN_INLIERS
    p = H @ np.array([300.0 + 25, 400.0 - 18, 1.0])           # moved point -> ref
    p = p[:2] / p[2]
    assert np.allclose(p, [300, 400], atol=2.0)


def test_register_rejects_textureless_frame():
    flat = np.full((960, 540), 128, np.uint8)
    kp_r, de_r = sr._sift(cv2.GaussianBlur(np.random.default_rng(1).integers(0, 255, (960, 540)).astype(np.uint8), (5, 5), 0))
    kp, de = sr._sift(flat)
    H, inl = sr._register(kp, de, kp_r, de_r, cv2.BFMatcher())
    assert H is None and inl == 0


# ---------------------------------------------------------------- output contract

def test_observations_are_verifier_compatible():
    from verification import verify
    obs = [{"t_ms": i * 167.0, "inputs": {}, "outputs": {"disp": "1" if i < 12 else "3"},
            "lit": {"disp": "bc"}} for i in range(24)]
    task = {
        "task_id": "t", "verification_mode": "state_match",
        "components": {"inputs": [], "outputs": [{"id": "disp", "type": "seven_segment_display"}]},
        "expected_behavior": [{"input": {}, "output": {"disp": "1"}},
                              {"input": {}, "output": {"disp": "3"}}],
    }
    assert verify(task, obs).passed


def test_read_video_graceful_fallback_when_no_display(monkeypatch):
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    monkeypatch.setattr(sr, "iter_sampled_frames", lambda path, fps: [(0.0, blank), (167.0, blank)])
    res = sr.read_video("dummy.mp4")
    assert res.stats["displays_found"] == 0
    assert len(res.observations) == 2
    assert any("could not find a lit 7-segment display" in w for w in res.warnings)
    assert res.observations[0]["outputs"] == {}


def test_red_led_segment_scores():
    # Synthetic red LED crop: red channel high, green and blue low
    glyph_red = sr.render_glyph("abcdef", lit=(20, 20, 240), unlit=(20, 20, 40))
    sc = sr.segment_scores(glyph_red)
    assert sr.decode_scores(sc, thr=180.0) == "0"


# ---------------------------------------------------------------- optional end-to-end

@pytest.mark.skipif(not os.environ.get("POW_SAMPLE_VIDEO"), reason="set POW_SAMPLE_VIDEO to run")
def test_end_to_end_on_sample_video():
    res = sr.read_video(os.environ["POW_SAMPLE_VIDEO"])
    seen = {o["outputs"]["disp"] for o in res.observations} - {None}
    assert res.displays[0].rotation in (90, 270)
    assert {"0", "1", "3", "8"} <= seen
