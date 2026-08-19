"""Step 2 - beat correction (quantization).

Snaps each drum hit to the nearest slot on a fixed subdivision grid (e.g.
16th notes), merges rapid retriggers/flams of the same drum into a single
hit, and optionally drops ghost notes (hits below a velocity threshold).

Output is a list of measures; each measure is a list of `grid` slots, and
each slot is a list of MIDI note numbers sounding at that instant.
"""

from dataclasses import dataclass, field

from .extract import DrumEvent


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

    if not filtered:
        return QuantizeResult(measures=[[[] for _ in range(slots_per_measure)]])

    max_slot = max(round(e.time_sec / seconds_per_slot) for e in filtered)
    num_measures = max_slot // slots_per_measure + 1
    measures: list[list[list[int]]] = [
        [[] for _ in range(slots_per_measure)] for _ in range(num_measures)
    ]
    velocities: dict[tuple[int, int, int], int] = {}

    for e in filtered:
        slot_index = round(e.time_sec / seconds_per_slot)
        measure_idx = slot_index // slots_per_measure
        slot_in_measure = slot_index % slots_per_measure
        if e.note not in measures[measure_idx][slot_in_measure]:
            measures[measure_idx][slot_in_measure].append(e.note)
            velocities[(measure_idx, slot_in_measure, e.note)] = e.velocity

    return QuantizeResult(measures=measures, velocities=velocities)


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
