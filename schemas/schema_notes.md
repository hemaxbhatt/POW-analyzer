# Task Truth-Table Schema — Design Notes

## Files
- `task_schema.json` — formal JSON Schema (draft 2020-12), validates any task spec
- `example_tasks.json` — 3 worked examples covering the 3 shapes of task we expect

## Key design decisions

**Two verification modes, not a boolean.**
Originally sketched as `sequence_required: true/false`. Changed to an explicit
`verification_mode` enum (`state_match` / `sequence_match`) so a third mode
can be added later (e.g. `final_state_only`) without breaking the shape.

- `state_match` — order doesn't matter. Good for pure combinational tasks
  (decoders, gates): "whenever the switches show X, the output must be Y."
- `sequence_match` — order matters. Needed for anything driven by the
  push button as a step/trigger (counters, state machines), where showing
  the right outputs in the wrong order is still wrong.

**`unlisted_input_policy` — handles don't-cares vs strict tables.**
Not every task's truth table is exhaustive. A 2-input AND gate task only
cares about 2 of the 4 switches; the other 2 positions are don't-cares and
will show up as "extra" input combinations in the video. Three explicit
policies:
- `ignore` — extra combos shown are fine, not penalized (don't-care case)
- `must_be_absent` — student should never show this combo at all
- `must_match_default` — compare against a single `default_output` (e.g. a
  decoder should show "invalid" for any BCD code above 9)

**`min_hold_time_ms` — noise filtering built in from the start.**
A hand moving over the breadboard, camera shake, or LED flicker could
register as a spurious state change. Rather than bolt this onto Phase 3
later, the schema carries a per-task tolerance for how long a state must be
stable before it "counts" as an observed state.

**Push button modeled as an event, not just a held state.**
For `sequence_match` steps, a trigger can be either an `input_state` (a
switch pattern being reached) or a discrete `event: button_press`. This
matches how the button actually behaves (momentary) rather than forcing
it into the same "held state" model as the DIP switches.

**`grading` is separate from `expected_behavior`.**
All-or-nothing vs partial-credit (`pass_threshold`) is a grading policy
decision, not a truth-table fact, so it's its own block. Defaults to
all-or-nothing.

## Open questions / assumptions to confirm against real task designs

1. **Is `all_or_nothing: true` actually the right default?** I assumed most
   combinational tasks (decoders, gates) should require every listed input
   to be shown correctly, since these are usually short truth tables. Flip
   this per-task if some tasks are meant to be partial-credit.
2. **Multi-output tasks** — schema supports multiple output components per
   task (e.g. an LED *and* a 7-segment both driven by the same switches),
   but there's no worked example yet. Worth adding one once you know if
   any real tasks actually do this.
3. **`max_gap_ms`** exists but defaults to `null` (no timing pressure
   between sequence steps). Unclear yet whether any task needs "must
   complete within N seconds" — left as an opt-in field for now rather
   than guessing at a default.
4. **Bit order** (`bit_order: [8,4,2,1]`, switch 1 = MSB) is a guess at the
   physical convention — needs confirming against how the actual DIP
   switch is labeled/oriented in the kit, since flipping it would silently
   invert every expected_behavior entry.

None of these block starting Phase 3's comparison logic — they're all
per-task config, not structural changes to the schema.
