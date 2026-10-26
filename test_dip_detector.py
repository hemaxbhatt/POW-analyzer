"""
Tests for dip_detector.py using synthetic images with a KNOWN correct answer.

Why synthetic instead of your real photo:
Your real photo has exactly one switch in exactly one position -- passing on
it proves the code works for that one frame, not that the logic is sound.
These tests build fake breadboard images where we control every pixel, so we
know the exact right answer in advance, and can check the code against
distractors (wires, IC chips, labels) on purpose.
"""
import cv2
import numpy as np
import pytest

from app.dip_detector import find_dip_switch, read_state, annotate


def make_switch_patch(lever_state="1010", w=65, h=78, axis="row"):
    """A red DIP-switch-like patch with 4 white levers.
    lever_state: '1' = lever near the top/left of its slot, '0' = other side.

    Lever width is ~50% of its slot (measured on the real photo: red fill
    across the lever band stayed in 0.42-0.89, never near the ~0.22 you'd
    get from levers spanning 70% of their slot -- an earlier, too-wide
    version of this fixture briefly broke the dense-core trim test below
    for exactly that reason)."""
    patch = np.full((h, w, 3), (60, 60, 190), np.uint8)   # red body (BGR)
    n = len(lever_state)
    margin = int(w * 0.08)
    slot_w = (w - 2 * margin) / n
    lever_h = int(h * 0.42)
    top_y, bot_y = int(h * 0.20), int(h * 0.58)
    for i, bit in enumerate(lever_state):
        x0 = int(margin + i * slot_w + slot_w * 0.27)
        x1 = int(margin + i * slot_w + slot_w * 0.73)
        y0 = top_y if bit == "1" else bot_y
        cv2.rectangle(patch, (x0, y0), (x1, y0 + lever_h), (235, 235, 235), -1)
    if axis == "column":
        patch = cv2.rotate(patch, cv2.ROTATE_90_CLOCKWISE)
    return patch


def scene_with_switch(lever_state="1010", switch_pos=(650, 500), distractors=True):
    """Concrete-grey board scene with a real switch plus, optionally, things
    that historically fooled the old detector: a tight wire tangle and an
    IC-sized red-ish blob."""
    frame = np.full((1080, 1920, 3), (120, 125, 125), np.uint8)
    cv2.rectangle(frame, (400, 250), (1400, 950), (225, 225, 225), -1)  # breadboard
    sx, sy = switch_pos
    patch = make_switch_patch(lever_state)
    h, w = patch.shape[:2]
    frame[sy:sy + h, sx:sx + w] = patch

    if distractors:
        # a snarled cluster of red jumper wires (thick, overlapping, curved)
        rng = np.random.default_rng(0)
        for _ in range(14):
            p1 = (int(rng.integers(700, 900)), int(rng.integers(300, 450)))
            p2 = (int(rng.integers(700, 900)), int(rng.integers(300, 450)))
            cv2.line(frame, p1, p2, (55, 55, 200), 6)
        # a dark IC-sized rectangle with small scattered white pin-holes
        cv2.rectangle(frame, (950, 400), (1150, 600), (40, 40, 45), -1)
        for _ in range(20):
            x = int(rng.integers(955, 1145))
            y = int(rng.integers(405, 595))
            cv2.circle(frame, (x, y), int(rng.integers(2, 6)), (230, 230, 230), -1)
    return frame


# ---------------------------------------------------------------- localization

def test_finds_switch_and_ignores_wire_and_ic_distractors():
    frame = scene_with_switch("1010")
    cand = find_dip_switch(frame)
    assert cand is not None
    x, y, w, h = cand.box
    assert abs(x - 650) < 15 and abs(y - 500) < 15   # lands on the real switch
    assert not (950 < x < 1150)                       # didn't grab the IC instead


def test_no_false_positive_on_empty_board():
    frame = scene_with_switch("1010", distractors=True)
    frame[500:578, 650:715] = (225, 225, 225)  # paint over the real switch -> none left
    cand = find_dip_switch(frame)
    assert cand is None or not (640 < cand.box[0] < 660)


@pytest.mark.parametrize("pos", [(300, 300), (1200, 800), (900, 900)])
def test_finds_switch_at_various_positions(pos):
    frame = scene_with_switch("0101", switch_pos=pos)
    cand = find_dip_switch(frame)
    assert cand is not None
    assert abs(cand.box[0] - pos[0]) < 15 and abs(cand.box[1] - pos[1]) < 15


def test_survives_a_merged_wire_tail():
    """Regression test for the bug found on board.jpg: a wire touching the
    switch merges into the same red blob, inflating the box and (before the
    dense-core trim) biasing every reading toward one side."""
    frame = scene_with_switch("0110", switch_pos=(650, 500), distractors=False)
    sx, sy = 650, 500
    sw, sh = 65, 78
    # a wire tail hanging straight down from the switch's bottom edge,
    # touching it so the red mask merges them into one blob
    cv2.line(frame, (sx + 20, sy + sh - 2), (sx + 20, sy + sh + 65), (55, 55, 200), 8)
    cv2.line(frame, (sx + 45, sy + sh - 2), (sx + 40, sy + sh + 50), (55, 55, 200), 8)

    cand = find_dip_switch(frame)
    assert cand is not None
    assert cand.box[3] < 90, f"box height {cand.box[3]} should be trimmed close to the real {sh}px switch"
    assert read_state(frame, cand) == "1001"


def test_finds_vertically_mounted_switch():
    patch = make_switch_patch("1100", axis="column")
    frame = np.full((1080, 1920, 3), (120, 125, 125), np.uint8)
    h, w = patch.shape[:2]
    frame[500:500 + h, 700:700 + w] = patch
    cand = find_dip_switch(frame)
    assert cand is not None
    assert cand.axis == "column"


# ---------------------------------------------------------------- lever count

def test_exactly_four_levers_found():
    frame = scene_with_switch("1001")
    cand = find_dip_switch(frame)
    assert cand is not None
    assert len(cand.lever_boxes) == 4


def test_levers_ordered_left_to_right():
    frame = scene_with_switch("1001")
    cand = find_dip_switch(frame)
    xs = [b[0] for b in cand.lever_boxes]
    assert xs == sorted(xs)


# ---------------------------------------------------------------- state reading

@pytest.mark.parametrize("state,expected", [("0000", "1111"), ("1111", "0000"), ("1010", "0101"), ("0101", "1010"), ("1001", "0110"), ("0110", "1001")])
def test_reads_correct_pattern(state, expected):
    frame = scene_with_switch(state)
    cand = find_dip_switch(frame)
    assert cand is not None
    assert read_state(frame, cand) == expected


def test_reading_is_consistent_across_positions():
    # same logical pattern, different place on the board -> same reading
    for pos in [(200, 200), (1500, 850)]:
        frame = scene_with_switch("0110", switch_pos=pos)
        cand = find_dip_switch(frame)
        assert read_state(frame, cand) == "1001"


# ---------------------------------------------------------------- annotate() sanity

def test_annotate_draws_without_crashing_and_returns_same_shape():
    frame = scene_with_switch("1010")
    cand = find_dip_switch(frame)
    out = annotate(frame, cand)
    assert out.shape == frame.shape
    assert not np.array_equal(out, frame)   # something was actually drawn


def test_annotate_handles_no_candidate():
    frame = scene_with_switch("1010")
    out = annotate(frame, None)
    assert np.array_equal(out, frame)
