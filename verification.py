"""
Phase 3 - functional verification.

Takes per-frame observations (what the DIP switch / button / LED / 7-segment
looked like at each sampled timestamp) and checks them against a task spec
(see task_schema.json).

Pipeline:
    raw observations -> stabilize() -> stable segments -> verify_* -> result

This module knows nothing about video or detection. Whatever produces the
observations (Phase 2 detection + state reading) just has to emit a list of:

    {"t_ms": 1200, "inputs": {"sw": "1010", "btn": "released"},
                   "outputs": {"disp": "5", "led1": "off"}}

A value of None (or "unknown", "?", "") means "couldn't read this component
in this frame". Such frames are never trusted as stable state.

Value conventions (all compared case-insensitively):
    dip_switch_4pos        "0101" (bit order is handled upstream by the reader)
                           spec patterns may use 'x' as a don't-care: "11xx"
    push_button            "pressed" | "released"
    led                    "on" | "off"
    seven_segment_display  "0"-"9", "a"-"f", "off", "invalid"
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any, Iterable, Mapping, Optional

WILDCARD = "x"
UNKNOWN_VALUES = {None, "", "unknown", "?"}
EPS = 1e-6

_DIP_RE = re.compile(r"^[01x]{4}$")
_SEVEN_SEG_RE = re.compile(r"^([0-9a-f]|off|invalid)$")
_BUTTON_VALUES = {"pressed", "released"}
_LED_VALUES = {"on", "off"}


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------

def _norm(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    return None if s in UNKNOWN_VALUES else s


def _norm_map(m: Mapping[str, Any]) -> dict:
    return {k: _norm(v) for k, v in m.items()}


@dataclass(frozen=True)
class Observation:
    t_ms: float
    inputs: dict
    outputs: dict


@dataclass(frozen=True)
class Segment:
    """A run of frames with identical readings, held long enough to count."""
    start_ms: float
    end_ms: float       # timestamp of the last frame in the run
    duration_ms: float  # end - start + one frame interval
    inputs: dict
    outputs: dict


@dataclass
class EntryResult:
    index: int                        # position in expected_behavior (0-based)
    satisfied: bool
    status: str                       # ok | input_not_shown | output_not_shown | wrong_output |
                                      # trigger_not_found | no_stable_output |
                                      # gap_exceeded
    expected: dict
    observed: Optional[dict] = None
    at_ms: Optional[float] = None
    detail: str = ""


@dataclass
class Violation:
    at_ms: float
    inputs: dict
    observed_outputs: dict
    policy: str
    detail: str


@dataclass
class VerificationResult:
    task_id: str
    mode: str
    passed: bool
    score: float
    satisfied_count: int
    total_count: int
    entries: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        lines = [
            f"[{'PASS' if self.passed else 'FAIL'}] {self.task_id} ({self.mode}) "
            f"{self.satisfied_count}/{self.total_count} = {self.score:.0%}"
        ]
        for e in self.entries:
            if not e.satisfied:
                lines.append(f"  - entry {e.index}: {e.status} - {e.detail}")
        for v in self.violations:
            lines.append(f"  ! violation @ {v.at_ms:.0f}ms: {v.detail}")
        for w in self.warnings:
            lines.append(f"  ~ {w}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Observations -> stable segments
# --------------------------------------------------------------------------

def coerce_observations(raw: Iterable[Any]) -> list:
    """Accept Observation objects or plain dicts; normalize and sort by time."""
    out = []
    for r in raw:
        if isinstance(r, Observation):
            out.append(Observation(r.t_ms, _norm_map(r.inputs), _norm_map(r.outputs)))
        else:
            out.append(Observation(
                float(r["t_ms"]),
                _norm_map(r.get("inputs", {})),
                _norm_map(r.get("outputs", {})),
            ))
    out.sort(key=lambda o: o.t_ms)
    return out


def _frame_interval(obs: list) -> float:
    diffs = [b.t_ms - a.t_ms for a, b in zip(obs, obs[1:]) if b.t_ms > a.t_ms]
    return float(median(diffs)) if diffs else 0.0


def _has_unknown(o: Observation) -> bool:
    return any(v is None for v in o.inputs.values()) or any(
        v is None for v in o.outputs.values()
    )


def stabilize(obs: list, min_hold_ms: float) -> list:
    """
    Collapse consecutive identical frames into segments and keep only those
    held for at least min_hold_ms. This is what filters flicker, a hand
    passing over the board, and switches caught mid-flip.
    """
    if not obs:
        return []
    interval = _frame_interval(obs)

    def key(o):
        return (tuple(sorted(o.inputs.items())), tuple(sorted(o.outputs.items())))

    segments, run_start = [], 0
    for i in range(1, len(obs) + 1):
        if i == len(obs) or key(obs[i]) != key(obs[run_start]):
            first, last = obs[run_start], obs[i - 1]
            duration = last.t_ms - first.t_ms + interval
            if not _has_unknown(first) and duration >= min_hold_ms:
                segments.append(Segment(
                    first.t_ms, last.t_ms, duration,
                    dict(first.inputs), dict(first.outputs),
                ))
            run_start = i
    return segments


def press_events(obs: list, component_id: str, min_press_frames: int = 1) -> list:
    """
    Timestamps at which a momentary button went from not-pressed to pressed
    (held for at least min_press_frames consecutive frames).
    Detected on raw frames, not segments, so a quick tap still counts.
    """
    events, run, run_start = [], 0, 0.0
    for o in obs:
        if o.inputs.get(component_id) == "pressed":
            if run == 0:
                run_start = o.t_ms
            run += 1
            if run == min_press_frames:
                events.append(run_start)
        else:
            run = 0
    return events


# --------------------------------------------------------------------------
# Matching helpers
# --------------------------------------------------------------------------

def _inputs_match(expected: Mapping[str, str], observed: Mapping[str, Optional[str]]) -> bool:
    """Every key in `expected` must match. Extra observed keys are ignored.
    'x' in an expected pattern is a per-character don't-care."""
    for cid, exp in expected.items():
        e, o = _norm(exp), observed.get(cid)
        if e is None or o is None:
            return False
        if len(e) == len(o) and WILDCARD in e:
            if any(ec != WILDCARD and ec != oc for ec, oc in zip(e, o)):
                return False
        elif e != o:
            return False
    return True


def _outputs_match(expected: Mapping[str, str], observed: Mapping[str, Optional[str]]) -> bool:
    for cid, exp in expected.items():
        e, o = _norm(exp), observed.get(cid)
        if e is None or o is None or e != o:
            return False
    return True


def _fmt(m: Mapping) -> str:
    return ", ".join(f"{k}={v}" for k, v in m.items()) or "(any)"


# --------------------------------------------------------------------------
# state_match
# --------------------------------------------------------------------------

def _verify_state_match(task: dict, segments: list):
    entries, violations, warnings = [], [], []
    spec = task["expected_behavior"]

    for i, item in enumerate(spec):
        exp_in, exp_out = item["input"], item["output"]
        shown = [s for s in segments if _inputs_match(exp_in, s.inputs)]
        if not exp_in:
            # display-only entry: no input is required, the output just has to appear
            good = next((s for s in shown if _outputs_match(exp_out, s.outputs)), None)
            if good:
                entries.append(EntryResult(i, True, "ok", item, dict(good.outputs), good.start_ms))
            else:
                entries.append(EntryResult(
                    i, False, "output_not_shown", item,
                    detail=f"never held {_fmt(exp_out)} long enough (hidden or not reached)"))
            continue
        if not shown:
            entries.append(EntryResult(
                i, False, "input_not_shown", item,
                detail=f"never held input {_fmt(exp_in)} long enough"))
            continue
        good = next((s for s in shown if _outputs_match(exp_out, s.outputs)), None)
        if good:
            entries.append(EntryResult(i, True, "ok", item, dict(good.outputs), good.start_ms))
            bad = [s for s in shown if not _outputs_match(exp_out, s.outputs)]
            if bad:
                warnings.append(
                    f"entry {i}: input {_fmt(exp_in)} also shown with a different "
                    f"output ({_fmt(bad[0].outputs)}) at {bad[0].start_ms:.0f}ms")
        else:
            last = shown[-1]
            entries.append(EntryResult(
                i, False, "wrong_output", item, dict(last.outputs), last.start_ms,
                f"input {_fmt(exp_in)} gave {_fmt(last.outputs)}, "
                f"expected {_fmt(exp_out)}"))

    policy = task.get("unlisted_input_policy", "ignore")
    if policy != "ignore":
        default_out = task.get("default_output", {})
        for s in segments:
            if any(_inputs_match(item["input"], s.inputs) for item in spec):
                continue
            if policy == "must_be_absent":
                violations.append(Violation(
                    s.start_ms, s.inputs, s.outputs, policy,
                    f"input {_fmt(s.inputs)} should never be shown"))
            elif policy == "must_match_default" and not _outputs_match(default_out, s.outputs):
                violations.append(Violation(
                    s.start_ms, s.inputs, s.outputs, policy,
                    f"unlisted input {_fmt(s.inputs)} gave {_fmt(s.outputs)}, "
                    f"expected default {_fmt(default_out)}"))
    return entries, violations, warnings


# --------------------------------------------------------------------------
# sequence_match
# --------------------------------------------------------------------------

def _verify_sequence(task: dict, obs: list, segments: list, max_gap_ms, min_press_frames: int):
    steps = sorted(task["expected_behavior"], key=lambda s: s["step"])
    entries, warnings = [], []
    cursor, prev_anchor = float("-inf"), None
    press_cache: dict = {}

    for i, step in enumerate(steps):
        trig, exp_out = step["trigger"], step["output"]
        anchor, outcome = None, None

        if trig.get("event") == "button_press":
            cid = trig["component_id"]
            if cid not in press_cache:
                press_cache[cid] = press_events(obs, cid, min_press_frames)
            presses = press_cache[cid]
            press_t = next((t for t in presses if t >= cursor), None)
            if press_t is None:
                entries.append(EntryResult(
                    i, False, "trigger_not_found", step,
                    detail=f"step {step['step']}: no further press of '{cid}' found"))
                continue
            next_press = next((t for t in presses if t > press_t), float("inf"))
            # Output that settled after this press, before the next one. Works
            # whether the circuit reacts on press or on release.
            window = [s for s in segments if press_t <= s.start_ms < next_press]
            cursor, anchor = press_t + EPS, press_t
            if not window:
                entries.append(EntryResult(
                    i, False, "no_stable_output", step, at_ms=press_t,
                    detail=f"step {step['step']}: no stable output after press at {press_t:.0f}ms"))
                prev_anchor = anchor
                continue
            outcome = window[-1]
        else:
            wanted = trig.get("input_state", {})
            seg = next((s for s in segments
                        if s.start_ms >= cursor and _inputs_match(wanted, s.inputs)), None)
            if seg is None:
                entries.append(EntryResult(
                    i, False, "trigger_not_found", step,
                    detail=f"step {step['step']}: state {_fmt(wanted)} not reached"))
                continue
            cursor, anchor, outcome = seg.end_ms + EPS, seg.start_ms, seg

        if max_gap_ms is not None and prev_anchor is not None and anchor - prev_anchor > max_gap_ms:
            entries.append(EntryResult(
                i, False, "gap_exceeded", step, dict(outcome.outputs), anchor,
                f"step {step['step']}: {anchor - prev_anchor:.0f}ms after previous step "
                f"(max {max_gap_ms}ms)"))
        elif _outputs_match(exp_out, outcome.outputs):
            entries.append(EntryResult(i, True, "ok", step, dict(outcome.outputs), anchor))
        else:
            entries.append(EntryResult(
                i, False, "wrong_output", step, dict(outcome.outputs), anchor,
                f"step {step['step']}: got {_fmt(outcome.outputs)}, expected {_fmt(exp_out)}"))
        prev_anchor = anchor

    return entries, [], warnings


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def verify(task: dict, observations: Iterable[Any], min_press_frames: int = 1) -> VerificationResult:
    """Check a list of observations against one task spec."""
    problems = check_task_semantics(task)
    if problems:
        raise ValueError("Invalid task spec:\n  " + "\n  ".join(problems))

    mode = task["verification_mode"]
    timing = task.get("timing", {})
    obs = coerce_observations(observations)
    segments = stabilize(obs, timing.get("min_hold_time_ms", 500))

    warnings = []
    if not obs:
        warnings.append("no observations supplied")
    elif not segments:
        warnings.append("no state was held long enough to count (check min_hold_time_ms / detection quality)")

    if mode == "state_match":
        entries, violations, extra = _verify_state_match(task, segments)
    else:
        entries, violations, extra = _verify_sequence(
            task, obs, segments, timing.get("max_gap_ms"), min_press_frames)
    warnings += extra

    total = len(entries)
    satisfied = sum(e.satisfied for e in entries)
    score = satisfied / total if total else 0.0

    grading = task.get("grading", {})
    if grading.get("all_or_nothing", True):
        meets = satisfied == total
    else:
        meets = score >= grading["pass_threshold"]

    return VerificationResult(
        task_id=task["task_id"], mode=mode, passed=meets and not violations,
        score=score, satisfied_count=satisfied, total_count=total,
        entries=entries, violations=violations, warnings=warnings)


# --------------------------------------------------------------------------
# Spec sanity checks (things JSON Schema can't express)
# --------------------------------------------------------------------------

def _value_problem(ctype: str, value: str, where: str, is_input: bool) -> Optional[str]:
    v = _norm(value)
    if v is None:
        return f"{where}: empty value"
    if ctype == "dip_switch_4pos" and not (_DIP_RE.match(v) if is_input else False):
        return f"{where}: '{value}' is not a 4-char pattern of 0/1/x"
    if ctype == "push_button" and v not in _BUTTON_VALUES:
        return f"{where}: '{value}' must be pressed/released"
    if ctype == "led" and v not in _LED_VALUES:
        return f"{where}: '{value}' must be on/off"
    if ctype == "seven_segment_display" and not _SEVEN_SEG_RE.match(v):
        return f"{where}: '{value}' must be 0-9, a-f, off or invalid"
    return None


def check_task_semantics(task: dict) -> list:
    """Return a list of human-readable problems (empty list = spec is usable)."""
    errs = []
    comps = task.get("components", {})
    ins = {c["id"]: c["type"] for c in comps.get("inputs", [])}
    outs = {c["id"]: c["type"] for c in comps.get("outputs", [])}
    mode = task.get("verification_mode")
    spec = task.get("expected_behavior", [])

    if mode not in ("state_match", "sequence_match"):
        errs.append(f"unknown verification_mode '{mode}'")
        return errs
    if not spec:
        errs.append("expected_behavior is empty")

    def check_inputs(m, where):
        for cid, val in m.items():
            if cid not in ins:
                errs.append(f"{where}: unknown input component '{cid}'")
            elif (p := _value_problem(ins[cid], val, f"{where}.{cid}", True)):
                errs.append(p)

    def check_outputs(m, where):
        for cid, val in m.items():
            if cid not in outs:
                errs.append(f"{where}: unknown output component '{cid}'")
            elif (p := _value_problem(outs[cid], val, f"{where}.{cid}", False)):
                errs.append(p)

    if mode == "state_match":
        for i, item in enumerate(spec):
            if "input" not in item or "output" not in item:
                errs.append(f"entry {i}: state_match entries need 'input' and 'output'")
                continue
            check_inputs(item["input"], f"entry {i}.input")
            check_outputs(item["output"], f"entry {i}.output")
        if task.get("unlisted_input_policy") == "must_match_default" and not task.get("default_output"):
            errs.append("unlisted_input_policy=must_match_default needs default_output")
        if task.get("default_output"):
            check_outputs(task["default_output"], "default_output")
    else:
        nums = [item.get("step") for item in spec]
        if sorted(nums) != list(range(1, len(spec) + 1)):
            errs.append(f"step numbers must be exactly 1..{len(spec)} with no repeats, got {nums}")
        for i, item in enumerate(spec):
            if "trigger" not in item or "output" not in item or "step" not in item:
                errs.append(f"entry {i}: sequence steps need 'step', 'trigger' and 'output'")
                continue
            trig = item["trigger"]
            if trig.get("event") == "button_press":
                cid = trig.get("component_id")
                if ins.get(cid) != "push_button":
                    errs.append(f"entry {i}: button_press needs component_id of a push_button, got '{cid}'")
            elif trig.get("event"):
                errs.append(f"entry {i}: unknown event '{trig['event']}'")
            check_inputs(trig.get("input_state", {}), f"entry {i}.trigger")
            check_outputs(item["output"], f"entry {i}.output")

    grading = task.get("grading", {})
    if not grading.get("all_or_nothing", True) and "pass_threshold" not in grading:
        errs.append("grading.all_or_nothing=false requires pass_threshold")
    return errs


# --------------------------------------------------------------------------
# Convenience + CLI
# --------------------------------------------------------------------------

def load_tasks(path: str) -> dict:
    """Load a JSON file holding one task or a list of tasks -> {task_id: task}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tasks = data if isinstance(data, list) else [data]
    return {t["task_id"]: t for t in tasks}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Verify observations against a task spec.")
    ap.add_argument("tasks", help="JSON file with a task or list of tasks")
    ap.add_argument("observations", help="JSON file with a list of observations")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--json", action="store_true", help="print full result as JSON")
    args = ap.parse_args()

    task = load_tasks(args.tasks)[args.task_id]
    with open(args.observations, encoding="utf-8") as f:
        result = verify(task, json.load(f))
    print(json.dumps(result.to_dict(), indent=2) if args.json else result.summary())
