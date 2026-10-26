"""Tests for verification.py - all synthetic, no video needed."""
import json
from pathlib import Path

import pytest

from verification import (
    check_task_semantics, press_events, coerce_observations, stabilize, verify,
)

DT = 100  # ms between synthetic frames


def frames(spans, dt=DT, start=0):
    """spans: [(duration_ms, inputs, outputs), ...] -> list of observation dicts."""
    t, out = start, []
    for dur, ins, outs in spans:
        for _ in range(int(dur / dt)):
            out.append({"t_ms": t, "inputs": dict(ins), "outputs": dict(outs)})
            t += dt
    return out


# ---------------------------------------------------------------- task builders

def then(base, spans):
    """Append more spans after an existing frame list, continuing its clock."""
    return base + frames(spans, start=base[-1]["t_ms"] + DT)


def decoder_task(**over):
    task = {
        "task_id": "decoder",
        "components": {
            "inputs": [{"id": "sw", "type": "dip_switch_4pos"}],
            "outputs": [{"id": "disp", "type": "seven_segment_display"}],
        },
        "verification_mode": "state_match",
        "unlisted_input_policy": "ignore",
        "timing": {"min_hold_time_ms": 500},
        "grading": {"all_or_nothing": True},
        "expected_behavior": [
            {"input": {"sw": f"{n:04b}"}, "output": {"disp": str(n)}} for n in range(10)
        ],
    }
    task.update(over)
    return task


def decoder_frames(skip=(), override=None, hold=700):
    override = override or {}
    spans = []
    for n in range(10):
        if n in skip:
            continue
        spans.append((hold, {"sw": f"{n:04b}"}, {"disp": override.get(n, str(n))}))
    return frames(spans)


def counter_task(**over):
    task = {
        "task_id": "counter",
        "components": {
            "inputs": [{"id": "btn", "type": "push_button"}],
            "outputs": [{"id": "disp", "type": "seven_segment_display"}],
        },
        "verification_mode": "sequence_match",
        "timing": {"min_hold_time_ms": 200, "max_gap_ms": None},
        "grading": {"all_or_nothing": True},
        "expected_behavior": [
            {"step": 1, "trigger": {"input_state": {}}, "output": {"disp": "0"}},
            {"step": 2, "trigger": {"event": "button_press", "component_id": "btn"}, "output": {"disp": "1"}},
            {"step": 3, "trigger": {"event": "button_press", "component_id": "btn"}, "output": {"disp": "2"}},
            {"step": 4, "trigger": {"event": "button_press", "component_id": "btn"}, "output": {"disp": "3"}},
            {"step": 5, "trigger": {"event": "button_press", "component_id": "btn"}, "output": {"disp": "0"}},
        ],
    }
    task.update(over)
    return task


def counter_frames(values, change_on="press", press_ms=300, rest_ms=500):
    spans = [(rest_ms, {"btn": "released"}, {"disp": values[0]})]
    for prev, new in zip(values, values[1:]):
        spans.append((press_ms, {"btn": "pressed"}, {"disp": new if change_on == "press" else prev}))
        spans.append((rest_ms, {"btn": "released"}, {"disp": new}))
    return frames(spans)


# ---------------------------------------------------------------- state_match

def test_decoder_all_correct_passes():
    r = verify(decoder_task(), decoder_frames())
    assert r.passed and r.score == 1.0 and r.satisfied_count == 10


def test_decoder_wrong_digit_reported():
    r = verify(decoder_task(), decoder_frames(override={5: "6"}))
    assert not r.passed
    bad = [e for e in r.entries if not e.satisfied]
    assert len(bad) == 1 and bad[0].status == "wrong_output" and bad[0].index == 5
    assert bad[0].observed == {"disp": "6"}


def test_decoder_missing_input_reported():
    r = verify(decoder_task(), decoder_frames(skip=(9,)))
    assert not r.passed and r.score == pytest.approx(0.9)
    assert [e.status for e in r.entries if not e.satisfied] == ["input_not_shown"]


def test_flicker_shorter_than_min_hold_is_ignored():
    # 9 is only shown for 200ms -> never counts as a held state
    spans = [(700, {"sw": f"{n:04b}"}, {"disp": str(n)}) for n in range(9)]
    spans.append((200, {"sw": "1001"}, {"disp": "9"}))
    r = verify(decoder_task(), frames(spans))
    assert r.entries[9].status == "input_not_shown"


def test_unknown_frames_break_stability():
    spans = [(300, {"sw": "0001"}, {"disp": "1"}),
             (100, {"sw": "0001"}, {"disp": None}),     # reader failed here
             (300, {"sw": "0001"}, {"disp": "1"})]
    segs = stabilize(coerce_observations(frames(spans)), 500)
    assert segs == []  # neither half is long enough on its own


def test_first_correct_showing_wins_and_contradiction_is_warned():
    spans = [(700, {"sw": "0001"}, {"disp": "7"}),
             (700, {"sw": "0000"}, {"disp": "0"}),
             (700, {"sw": "0001"}, {"disp": "1"})]
    task = decoder_task()
    task["expected_behavior"] = task["expected_behavior"][:2]
    r = verify(task, frames(spans))
    assert r.passed
    assert any("also shown with a different output" in w for w in r.warnings)


def test_default_policy_flags_bad_unlisted_output():
    task = decoder_task(unlisted_input_policy="must_match_default",
                        default_output={"disp": "invalid"})
    good = then(decoder_frames(), [(700, {"sw": "1111"}, {"disp": "invalid"})])
    bad = then(decoder_frames(), [(700, {"sw": "1111"}, {"disp": "8"})])
    assert verify(task, good).passed
    r = verify(task, bad)
    assert not r.passed and len(r.violations) == 1 and r.score == 1.0


def test_must_be_absent_policy():
    task = decoder_task(unlisted_input_policy="must_be_absent")
    r = verify(task, then(decoder_frames(), [(700, {"sw": "1100"}, {"disp": "off"})]))
    assert not r.passed and r.violations[0].policy == "must_be_absent"


def test_ignore_policy_allows_extra_states():
    r = verify(decoder_task(), then(decoder_frames(), [(700, {"sw": "1111"}, {"disp": "off"})]))
    assert r.passed and not r.violations


def test_led_and_gate_with_dont_care_pattern():
    task = {
        "task_id": "and2",
        "components": {"inputs": [{"id": "sw", "type": "dip_switch_4pos"}],
                       "outputs": [{"id": "led1", "type": "led"}]},
        "verification_mode": "state_match",
        "expected_behavior": [
            {"input": {"sw": "00xx"}, "output": {"led1": "off"}},
            {"input": {"sw": "01xx"}, "output": {"led1": "off"}},
            {"input": {"sw": "10xx"}, "output": {"led1": "off"}},
            {"input": {"sw": "11xx"}, "output": {"led1": "on"}},
        ],
    }
    obs = frames([(700, {"sw": "0000"}, {"led1": "off"}),
                  (700, {"sw": "0110"}, {"led1": "off"}),
                  (700, {"sw": "1001"}, {"led1": "off"}),
                  (700, {"sw": "1101"}, {"led1": "on"})])
    assert verify(task, obs).passed


def test_case_insensitive_values():
    obs = frames([(700, {"sw": "0001"}, {"disp": "A"})])
    task = decoder_task()
    task["expected_behavior"] = [{"input": {"sw": "0001"}, "output": {"disp": "a"}}]
    assert verify(task, obs).passed


def test_no_observations_fails_cleanly():
    r = verify(decoder_task(), [])
    assert not r.passed and r.score == 0.0
    assert "no observations supplied" in r.warnings


# ---------------------------------------------------------------- sequence_match

def test_counter_passes_when_output_changes_on_press():
    assert verify(counter_task(), counter_frames(list("01230"))).passed


def test_counter_passes_when_output_changes_on_release():
    assert verify(counter_task(), counter_frames(list("01230"), change_on="release")).passed


def test_counter_quick_taps_are_still_counted():
    # 100ms taps = one frame each; min_hold 200 drops the pressed segment
    # itself, but the press event comes from raw frames and the settled
    # output after release is what gets checked.
    r = verify(counter_task(), counter_frames(list("01230"), change_on="release", press_ms=100))
    assert r.passed


def test_counter_wrong_output_reported():
    r = verify(counter_task(), counter_frames(list("01233")))
    assert not r.passed
    bad = [e for e in r.entries if not e.satisfied]
    assert len(bad) == 1 and bad[0].status == "wrong_output" and bad[0].index == 4


def test_counter_partial_credit_threshold():
    obs = counter_frames(list("01233"))  # 4/5 correct
    assert verify(counter_task(grading={"all_or_nothing": False, "pass_threshold": 0.75}), obs).passed
    assert not verify(counter_task(grading={"all_or_nothing": False, "pass_threshold": 0.9}), obs).passed


def test_counter_missing_presses():
    r = verify(counter_task(), counter_frames(list("012")))  # only 2 presses
    statuses = [e.status for e in r.entries]
    assert statuses[:3] == ["ok", "ok", "ok"]
    assert statuses[3:] == ["trigger_not_found", "trigger_not_found"]


def test_counter_order_matters():
    # right digits, wrong order
    r = verify(counter_task(), counter_frames(list("02130")))
    assert not r.passed


def test_max_gap_enforced():
    task = counter_task(timing={"min_hold_time_ms": 200, "max_gap_ms": 500})
    slow = counter_frames(list("01230"), rest_ms=2000)
    r = verify(task, slow)
    assert any(e.status == "gap_exceeded" for e in r.entries)
    fast = counter_frames(list("01230"), rest_ms=200, press_ms=200)
    assert verify(task, fast).passed


def test_press_events_debounce():
    obs = coerce_observations(frames([
        (100, {"btn": "released"}, {}), (100, {"btn": "pressed"}, {}),   # 1-frame blip
        (300, {"btn": "released"}, {}), (300, {"btn": "pressed"}, {}),   # real press
    ]))
    assert len(press_events(obs, "btn", min_press_frames=1)) == 2
    assert len(press_events(obs, "btn", min_press_frames=2)) == 1


def test_state_trigger_sequence():
    task = {
        "task_id": "seq_states",
        "components": {"inputs": [{"id": "sw", "type": "dip_switch_4pos"}],
                       "outputs": [{"id": "led1", "type": "led"}]},
        "verification_mode": "sequence_match",
        "expected_behavior": [
            {"step": 1, "trigger": {"input_state": {"sw": "0001"}}, "output": {"led1": "on"}},
            {"step": 2, "trigger": {"input_state": {"sw": "0010"}}, "output": {"led1": "off"}},
        ],
    }
    ok = frames([(700, {"sw": "0001"}, {"led1": "on"}), (700, {"sw": "0010"}, {"led1": "off"})])
    swapped = frames([(700, {"sw": "0010"}, {"led1": "off"}), (700, {"sw": "0001"}, {"led1": "on"})])
    assert verify(task, ok).passed
    r = verify(task, swapped)
    assert not r.passed and r.entries[1].status == "trigger_not_found"


# ---------------------------------------------------------------- spec checks

def test_semantics_catches_bad_values_and_ids():
    task = decoder_task()
    task["expected_behavior"][0]["output"] = {"disp": "lit"}
    task["expected_behavior"][1]["input"] = {"nope": "0001"}
    task["expected_behavior"][2]["input"] = {"sw": "01"}
    errs = check_task_semantics(task)
    assert len(errs) == 3
    with pytest.raises(ValueError):
        verify(task, [])


def test_semantics_threshold_and_default_and_steps():
    assert check_task_semantics(counter_task(grading={"all_or_nothing": False}))
    assert check_task_semantics(decoder_task(unlisted_input_policy="must_match_default"))
    bad = counter_task()
    bad["expected_behavior"][2]["step"] = 5
    assert check_task_semantics(bad)


def test_button_press_needs_push_button_component():
    bad = counter_task()
    bad["expected_behavior"][1]["trigger"]["component_id"] = "disp"
    assert check_task_semantics(bad)


# ---------------------------------------------------------------- shipped examples

def _find_examples():
    here = Path(__file__).resolve().parent
    for p in [here / "example_tasks.json", here.parent / "schemas" / "example_tasks.json"]:
        if p.exists():
            return p
    return None


def test_shipped_examples_are_semantically_valid():
    p = _find_examples()
    if p is None:
        pytest.skip("example_tasks.json not found next to tests or in ../schemas/")
    for task in json.loads(p.read_text()):
        assert check_task_semantics(task) == [], task["task_id"]


# ---------------------------------------------------------------- display-only tasks

def display_only_task(digits="0123"):
    return {
        "task_id": "display_only",
        "components": {"inputs": [], "outputs": [{"id": "disp", "type": "seven_segment_display"}]},
        "verification_mode": "state_match",
        "timing": {"min_hold_time_ms": 500},
        "expected_behavior": [{"input": {}, "output": {"disp": d}} for d in digits],
    }


def test_display_only_passes_when_every_digit_appears():
    obs = frames([(700, {}, {"disp": d}) for d in "0123"])
    assert verify(display_only_task(), obs).passed


def test_display_only_reports_output_not_shown_without_noise():
    obs = frames([(700, {}, {"disp": "0"}), (700, {}, {"disp": "3"})])
    r = verify(display_only_task(), obs)
    assert not r.passed
    assert [e.status for e in r.entries] == ["ok", "output_not_shown", "output_not_shown", "ok"]
    assert r.warnings == []          # no "also shown with a different output" chatter


def test_display_only_ignores_unreadable_frames():
    obs = frames([(700, {}, {"disp": "0"}), (700, {}, {"disp": None}), (700, {}, {"disp": "1"})])
    r = verify(display_only_task("01"), obs)
    assert r.passed
