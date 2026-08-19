"""Step 2 - beat correction (quantization).

Snaps each drum hit to the nearest slot on a fixed subdivision grid (e.g.
16th notes), merges rapid retriggers/flams of the same drum into a single
hit, and optionally drops ghost notes (hits below a velocity threshold).

Output is a list of measures; each measure is a list of `grid` slots, and
each slot is a list of MIDI note numbers sounding at that instant.
"""

from dataclasses import dataclass, field

from .drum_map import GM_DRUM_MAP, lookup
from .extract import DrumEvent

# a soft hit landing this close before a louder hit at the same staff
# position reads as a flam/drag grace note, not a separate grid-note or a
# simultaneous chord. Below GRACE_WINDOW_MIN_SEC it's within normal
# "simultaneous hit" jitter (e.g. a kick+snare struck together by a human);
# above GRACE_WINDOW_MAX_SEC it's just two distinct, deliberately spaced hits.
GRACE_WINDOW_MIN_SEC = 0.012
GRACE_WINDOW_MAX_SEC = 0.06


@dataclass
class QuantizeOptions:
    grid: int = 16  # subdivisions per whole note grid step count is grid-per-measure below
    subdivisions_per_quarter: int = 4  # 4 -> 16th-note grid, 2 -> 8th-note grid
    ghost_velocity_threshold: int = 0  # hits below this velocity are dropped (0 = keep all)
    merge_window_sec: float = 0.03  # retriggers of the same note within this window are merged


@dataclass
class QuantizeResult:
    measures: list[list[list[int]]]
    # velocity of each hit, keyed by (measure_idx, slot_idx, note) - kept
    # alongside the grid (rather than folded into it) so every existing
    # consumer of `measures` keeps working unchanged; only snap_stray_offbeats
    # needs this extra signal.
    velocities: dict[tuple[int, int, int], int] = field(default_factory=dict)
    # grace note attached just before the main note at this slot, keyed by
    # (measure_idx, slot_idx, main_note) -> grace note number. The grace note
    # itself never gets its own grid slot - it has no rhythmic duration.
    grace_notes: dict[tuple[int, int, int], int] = field(default_factory=dict)


def quantize_events(
    events: list[DrumEvent],
    tempo_bpm: float,
    time_signature: tuple[int, int],
    options: QuantizeOptions,
) -> QuantizeResult:
    beats_per_measure, beat_unit = time_signature
    seconds_per_quarter = 60.0 / tempo_bpm
    # ticks here means "grid slots per quarter note"
    slots_per_quarter = options.subdivisions_per_quarter
    slots_per_measure = int(beats_per_measure * (4 / beat_unit) * slots_per_quarter)
    seconds_per_slot = seconds_per_quarter / slots_per_quarter

    filtered = [e for e in events if e.velocity >= options.ghost_velocity_threshold]
    filtered = _merge_retriggers(filtered, options.merge_window_sec)
    filtered, grace_for = _detect_grace_notes(filtered)

    if not filtered:
        return QuantizeResult(measures=[[[] for _ in range(slots_per_measure)]])

    max_slot = max(round(e.time_sec / seconds_per_slot) for e in filtered)
    num_measures = max_slot // slots_per_measure + 1
    measures: list[list[list[int]]] = [
        [[] for _ in range(slots_per_measure)] for _ in range(num_measures)
    ]
    velocities: dict[tuple[int, int, int], int] = {}
    grace_notes: dict[tuple[int, int, int], int] = {}

    for e in filtered:
        slot_index = round(e.time_sec / seconds_per_slot)
        measure_idx = slot_index // slots_per_measure
        slot_in_measure = slot_index % slots_per_measure
        if e.note not in measures[measure_idx][slot_in_measure]:
            measures[measure_idx][slot_in_measure].append(e.note)
            velocities[(measure_idx, slot_in_measure, e.note)] = e.velocity
            grace = grace_for.get(id(e))
            if grace is not None:
                grace_notes[(measure_idx, slot_in_measure, e.note)] = grace.note

    _resolve_hihat_conflicts(measures, velocities)
    _resolve_duplicate_noteheads(measures, velocities, grace_notes)

    return QuantizeResult(measures=measures, velocities=velocities, grace_notes=grace_notes)


def _same_position_groups() -> list[set[int]]:
    """Any set of GM notes drum_map.py maps to the identical staff position
    + notehead (snare variants, crash 1/2, ride 1/2, tom tiers, ...) - two
    of them landing in the same slot would render as one indistinguishably
    doubled-up notehead, so they're resolved the same way regardless of
    which specific instruments they are."""
    groups: dict[tuple[str, int, str], set[int]] = {}
    for note, spec in GM_DRUM_MAP.items():
        key = (spec["step"], spec["octave"], spec["notehead"])
        groups.setdefault(key, set()).add(note)
    return [notes for notes in groups.values() if len(notes) > 1]


_DUPLICATE_NOTE_GROUPS = _same_position_groups()


def _resolve_duplicate_noteheads(
    measures: list[list[list[int]]],
    velocities: dict[tuple[int, int, int], int],
    grace_notes: dict[tuple[int, int, int], int],
) -> None:
    """When two notes that share a staff position + notehead land in the
    same slot, keep only the louder one - the pair is visually identical
    and indistinguishable anyway, so there's nothing lost by collapsing it
    to a single note (open/closed hi-hat is handled separately since that
    pair isn't "keep the louder", it's "keep open").
    """
    for measure_idx, measure in enumerate(measures):
        for slot_idx, hits in enumerate(measure):
            for group in _DUPLICATE_NOTE_GROUPS:
                present = [n for n in hits if n in group]
                if len(present) < 2:
                    continue
                loudest = max(present, key=lambda n: velocities.get((measure_idx, slot_idx, n), 0))
                for note in present:
                    if note == loudest:
                        continue
                    hits.remove(note)
                    velocities.pop((measure_idx, slot_idx, note), None)
                    grace_notes.pop((measure_idx, slot_idx, note), None)


def _detect_grace_notes(
    events: list[DrumEvent],
) -> tuple[list[DrumEvent], dict[int, DrumEvent]]:
    """Flags a soft hit landing just before a louder hit at the same staff
    position as a flam/drag grace note rather than its own grid note. The
    grace hit is pulled out of the event list (it must not consume its own
    grid slot) and returned in a lookup keyed by id() of the main hit it
    attaches to, since DrumEvent has no stable identifier of its own."""
    events = sorted(events, key=lambda e: e.time_sec)
    grace_for: dict[int, DrumEvent] = {}
    skip_indices: set[int] = set()

    for i in range(len(events) - 1):
        if i in skip_indices:
            continue
        a, b = events[i], events[i + 1]
        gap = b.time_sec - a.time_sec
        if not (GRACE_WINDOW_MIN_SEC <= gap <= GRACE_WINDOW_MAX_SEC):
            continue
        if a.velocity >= b.velocity:
            continue
        spec_a, spec_b = lookup(a.note), lookup(b.note)
        if (spec_a["step"], spec_a["octave"]) != (spec_b["step"], spec_b["octave"]):
            continue
        grace_for[id(b)] = a
        skip_indices.add(i)

    remaining = [e for idx, e in enumerate(events) if idx not in skip_indices]
    return remaining, grace_for


CLOSED_HIHAT = 42
OPEN_HIHAT = 46


def _resolve_hihat_conflicts(
    measures: list[list[list[int]]], velocities: dict[tuple[int, int, int], int]
) -> None:
    """A hi-hat can't be open and closed at the same instant. When a coarse
    grid rounds two real, separate hits (e.g. closed on the beat, open on
    the "&") into the same slot, keep the open hi-hat and drop the closed
    one - open is the more specific/informative of the two, and losing it
    would silently turn an open-hihat pattern into a plain closed one.
    """
    for measure_idx, measure in enumerate(measures):
        for slot_idx, hits in enumerate(measure):
            if CLOSED_HIHAT in hits and OPEN_HIHAT in hits:
                hits.remove(CLOSED_HIHAT)
                velocities.pop((measure_idx, slot_idx, CLOSED_HIHAT), None)


def snap_stray_offbeats(
    measures: list[list[list[int]]],
    slots_per_quarter: int,
    velocities: dict[tuple[int, int, int], int] | None = None,
) -> list[list[list[int]]]:
    """"튀는 박자 자동 정리" - pulls a note off the beat grid back onto the
    nearest strong beat (the beat itself or its "&") when it looks like
    quantization noise rather than an intended fill/roll. A hit is kept in
    place (not snapped) if either signal below says "this is real playing":

    - Structural: a same-instrument hit sits in the immediately neighboring
      slot (a roll on one drum), OR *any* instrument fires in a neighboring
      slot (an alternating-instrument fill, e.g. kick/snare trading 32nds -
      those never share a same-instrument neighbor, so the plain same-note
      check alone would wrongly erase them).
    - Statistical: the hit's velocity isn't a outlier compared to that
      instrument's average velocity across the piece. A hit sitting next to
      unrelated activity but struck far softer than normal for that drum
      reads as stray noise even inside a busy passage, so it's snapped
      despite the neighboring activity.

    A hit failing both checks (alone, and/or abnormally soft) is treated as
    quantization noise and pulled onto the nearest strong beat.
    """
    if slots_per_quarter < 4 or not measures:
        return measures  # nothing finer than 8th notes to call "off-beat"

    velocities = velocities or {}
    strong_divisor = slots_per_quarter // 2

    note_velocities: dict[int, list[int]] = {}
    for (_, _, note), velocity in velocities.items():
        note_velocities.setdefault(note, []).append(velocity)
    baseline_velocity = {note: sum(vs) / len(vs) for note, vs in note_velocities.items()}
    OUTLIER_RATIO = 0.6  # softer than 60% of this instrument's average = likely noise

    new_measures = [[list(hits) for hits in measure] for measure in measures]
    for measure_idx, measure in enumerate(new_measures):
        slots_per_measure = len(measure)
        for slot_idx in range(slots_per_measure):
            if slot_idx % strong_divisor != 0:
                for note in list(measure[slot_idx]):
                    same_note_neighbor = (slot_idx > 0 and note in measure[slot_idx - 1]) or (
                        slot_idx + 1 < slots_per_measure and note in measure[slot_idx + 1]
                    )
                    if same_note_neighbor:
                        continue  # a roll on this exact drum - definitely real, leave it

                    any_neighbor_activity = (slot_idx > 0 and measure[slot_idx - 1]) or (
                        slot_idx + 1 < slots_per_measure and measure[slot_idx + 1]
                    )
                    velocity = velocities.get((measure_idx, slot_idx, note))
                    baseline = baseline_velocity.get(note)
                    is_soft_outlier = (
                        velocity is not None and baseline and velocity < baseline * OUTLIER_RATIO
                    )

                    if any_neighbor_activity and not is_soft_outlier:
                        continue  # part of a broader fill and hit at a normal strength - leave it

                    prev_strong = (slot_idx // strong_divisor) * strong_divisor
                    next_strong = prev_strong + strong_divisor
                    if next_strong >= slots_per_measure:
                        next_strong = prev_strong
                    target = prev_strong if (slot_idx - prev_strong) <= (next_strong - slot_idx) else next_strong
                    measure[slot_idx].remove(note)
                    if note not in measure[target]:
                        measure[target].append(note)

    return new_measures


def _merge_retriggers(events: list[DrumEvent], window_sec: float) -> list[DrumEvent]:
    if window_sec <= 0:
        return events

    events = sorted(events, key=lambda e: e.time_sec)
    last_index: dict[int, int] = {}
    merged: list[DrumEvent] = []

    for e in events:
        idx = last_index.get(e.note)
        if idx is not None and (e.time_sec - merged[idx].time_sec) < window_sec:
            # keep the louder hit of the pair, drop the retrigger
            if e.velocity > merged[idx].velocity:
                merged[idx] = e
            continue
        merged.append(e)
        last_index[e.note] = len(merged) - 1

    return merged
