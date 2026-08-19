"""Step 3 - translate the quantized grid into a MusicXML document.

Each grid slot becomes one note (or rest) of fixed duration. Consecutive
empty slots are merged into longer rests for readability. Simultaneous
drum hits in the same slot are written as a chord sharing one stem, each
note carrying the notehead shape for its instrument.

Notes are split across two voices per drum_map's `voice` field, matching
standard drum notation: cymbals/snare/toms-up in voice 1 (stems up), kick
and floor toms in voice 2 (stems down). Without this split every instrument
shared one beam group and low drums (kick, toms) were visually tangled up
with the hi-hat/snare pattern instead of reading as their own line.

Two extra notation conventions are applied on top of the raw grid:
- Open hi-hat (46) gets a small circle above the x notehead on its first
  hit. If the same open run keeps going past one measure, later hits in
  that run drop the circle (plain x) and a "-> Open H.H" label marks the
  measure where the run started, instead of repeating the circle everywhere.
- Pedal hi-hat (44) is not drawn as its own note; when it coincides with a
  kick hit it becomes a staccato dot on that kick note, and only falls back
  to its own x note when no kick is present in the same slot.
"""

from xml.sax.saxutils import escape

from .drum_map import lookup

# Duration values expressible as a single note, longest first, in grid-slot units
# (assuming a 16th-note grid, i.e. 1 slot = 1 sixteenth note).
_DURATION_STEPS_16TH = [
    (16, "whole"),
    (8, "half"),
    (4, "quarter"),
    (2, "eighth"),
    (1, "16th"),
]

OPEN_HIHAT = 46
CLOSED_HIHAT = 42
PEDAL_HIHAT = 44
KICK_NOTES = {35, 36}


def _type_for_slots(slots: int, slots_per_quarter: int) -> list[tuple[int, str]]:
    """Break a slot count into MusicXML note-type chunks (greedy, no dots)."""
    if slots_per_quarter == 8:
        table = [(32, "whole"), (16, "half"), (8, "quarter"), (4, "eighth"), (2, "16th"), (1, "32nd")]
    elif slots_per_quarter == 4:
        table = _DURATION_STEPS_16TH
    elif slots_per_quarter == 2:
        table = [(8, "whole"), (4, "half"), (2, "quarter"), (1, "eighth")]
    elif slots_per_quarter == 1:
        table = [(4, "whole"), (2, "half"), (1, "quarter")]
    else:
        table = [(slots_per_quarter, "quarter"), (1, "16th")]

    chunks = []
    remaining = slots
    for steps, name in table:
        while remaining >= steps:
            chunks.append((steps, name))
            remaining -= steps
    if remaining > 0:
        chunks.append((remaining, "16th"))
    return chunks


def _fold_pedal_hihat_into_kick(measures: list[list[list[int]]]) -> tuple[list[list[list[int]]], set[tuple[int, int]]]:
    """Drops pedal hi-hat (44) as its own note when it lines up with a kick,
    recording that slot for a staccato dot on the kick instead. If no kick
    is present in the slot, the pedal hi-hat note is left in place."""
    processed = []
    staccato_slots: set[tuple[int, int]] = set()
    for m_idx, measure in enumerate(measures):
        new_measure = []
        for s_idx, slot in enumerate(measure):
            if PEDAL_HIHAT in slot and any(n in KICK_NOTES for n in slot):
                staccato_slots.add((m_idx, s_idx))
                slot = [n for n in slot if n != PEDAL_HIHAT]
            new_measure.append(slot)
        processed.append(new_measure)
    return processed, staccato_slots


def _compute_open_hihat_marks(measures: list[list[list[int]]]) -> tuple[set[tuple[int, int]], set[int]]:
    """Groups consecutive open hi-hat hits (uninterrupted by a closed hit)
    into runs. A run confined to one measure gets the open circle on every
    hit; a run spanning more than one measure gets the circle only on its
    first hit, plus a text label on the measure it starts in."""
    hihat_seq: list[tuple[int, int, int]] = []
    for m_idx, measure in enumerate(measures):
        for s_idx, slot in enumerate(measure):
            if OPEN_HIHAT in slot:
                hihat_seq.append((m_idx, s_idx, OPEN_HIHAT))
            elif CLOSED_HIHAT in slot:
                hihat_seq.append((m_idx, s_idx, CLOSED_HIHAT))

    circle_slots: set[tuple[int, int]] = set()
    label_measures: set[int] = set()

    def flush(run: list[tuple[int, int, int]]) -> None:
        if not run:
            return
        measures_in_run = {m for m, s, n in run}
        if len(measures_in_run) > 1:
            first_m, first_s, _ = run[0]
            circle_slots.add((first_m, first_s))
            label_measures.add(first_m)
        else:
            for m, s, n in run:
                circle_slots.add((m, s))

    current_run: list[tuple[int, int, int]] = []
    for m_idx, s_idx, note in hihat_seq:
        if note == OPEN_HIHAT:
            current_run.append((m_idx, s_idx, note))
        else:
            flush(current_run)
            current_run = []
    flush(current_run)

    return circle_slots, label_measures


def _voice_xml(
    voice_slots: list[list[int]],
    voice_num: int,
    slots_per_quarter: int,
    measure_idx: int,
    circle_slots: set[tuple[int, int]],
    staccato_slots: set[tuple[int, int]],
) -> str:
    """Render one voice's worth of a measure: notes/chords where hits exist,
    rests (merged into longer note values) everywhere else."""
    out = []
    i = 0
    n = len(voice_slots)
    while i < n:
        hits = voice_slots[i]
        if not hits:
            run_start = i
            while i < n and not voice_slots[i]:
                i += 1
            for steps, note_type in _type_for_slots(i - run_start, slots_per_quarter):
                out.append(
                    f"<note><rest/><duration>{steps}</duration>"
                    f"<voice>{voice_num}</voice><type>{note_type}</type></note>"
                )
            continue

        slot_idx = i
        # duration = time until the next hit in this voice (or measure end),
        # capped to the longest single note value that fits - this collapses
        # what used to be "short note + several rests" into one clean symbol
        # whenever a hit lines up evenly with the next one (e.g. quarter-note
        # spaced hits become one quarter note instead of four tied 16ths).
        # Instruments that actually ring (cymbals, triangle, ...) can extend
        # all the way to the next hit. Struck/damped drums (kick, snare,
        # toms) still merge short, regular gaps into one clean note - a
        # steady 8th-note kick shouldn't be broken into "16th + 16th rest" -
        # but are capped at one quarter note so a long silence doesn't turn
        # into an unnaturally held half/whole-note kick.
        next_hit = i + 1
        while next_hit < n and not voice_slots[next_hit]:
            next_hit += 1
        reach = next_hit - i
        if not all(lookup(note)["sustain"] for note in hits):
            reach = min(reach, slots_per_quarter)
        steps, note_type = _type_for_slots(reach, slots_per_quarter)[0]

        for idx, note in enumerate(hits):
            spec = lookup(note)
            chord_tag = "<chord/>" if idx > 0 else ""
            stem = "up" if voice_num == 1 else "down"

            notations = ""
            if note == OPEN_HIHAT and (measure_idx, slot_idx) in circle_slots:
                notations = "<notations><articulations><open/></articulations></notations>"
            elif note in KICK_NOTES and (measure_idx, slot_idx) in staccato_slots:
                notations = "<notations><articulations><staccato/></articulations></notations>"

            out.append(
                f"<note>{chord_tag}"
                f"<unpitched><display-step>{spec['step']}</display-step>"
                f"<display-octave>{spec['octave']}</display-octave></unpitched>"
                f"<duration>{steps}</duration>"
                f"<voice>{voice_num}</voice><type>{note_type}</type><stem>{stem}</stem>"
                f'<notehead>{spec["notehead"]}</notehead>'
                f"<instrument id=\"P1-I{note}\"/>"
                f"{notations}"
                f"</note>"
            )
        i += steps
    return "".join(out)


def build_musicxml(
    measures: list[list[list[int]]],
    time_signature: tuple[int, int],
    tempo_bpm: float,
    slots_per_quarter: int,
    title: str = "Drum Transcription",
    staff_size_percent: int = 100,
) -> str:
    beats, beat_type = time_signature
    divisions = slots_per_quarter  # one division per grid slot
    slots_per_measure = int(beats * (4 / beat_type) * slots_per_quarter)
    # <scaling> sets how many mm one staff (40 tenths) prints as - this is
    # what MuseScore actually reads as "notation size" on export, since the
    # CLI itself has no size flag. 7mm at 100% is a standard staff height.
    staff_mm = 7.0 * staff_size_percent / 100

    measures, staccato_slots = _fold_pedal_hihat_into_kick(measures)
    circle_slots, label_measures = _compute_open_hihat_marks(measures)

    parts_xml = []
    measure_num = 0

    for measure_idx, measure in enumerate(measures):
        measure_num += 1
        voice1_slots = [[note for note in slot if lookup(note)["voice"] == 1] for slot in measure]
        voice2_slots = [[note for note in slot if lookup(note)["voice"] == 2] for slot in measure]

        voice1_xml = _voice_xml(voice1_slots, 1, slots_per_quarter, measure_idx, circle_slots, staccato_slots)
        voice2_xml = _voice_xml(voice2_slots, 2, slots_per_quarter, measure_idx, circle_slots, staccato_slots)
        backup = f"<backup><duration>{slots_per_measure}</duration></backup>"

        attributes = ""
        if measure_num == 1:
            attributes = (
                f"<attributes><divisions>{divisions}</divisions>"
                f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"
                f'<clef><sign>percussion</sign><line>2</line></clef>'
                f"</attributes>"
                f'<direction placement="above"><direction-type>'
                f'<metronome><beat-unit>quarter</beat-unit><per-minute>{round(tempo_bpm)}</per-minute></metronome>'
                f"</direction-type><sound tempo=\"{round(tempo_bpm)}\"/></direction>"
            )

        open_label = ""
        if measure_idx in label_measures:
            open_label = (
                '<direction placement="above"><direction-type>'
                '<words>→ Open H.H</words></direction-type></direction>'
            )

        parts_xml.append(
            f'<measure number="{measure_num}">{attributes}{open_label}{voice1_xml}{backup}{voice2_xml}</measure>'
        )

    score_instruments = "".join(
        f'<score-instrument id="P1-I{note}"><instrument-name>{escape(spec["name"])}</instrument-name>'
        f"<instrument-sound>drum</instrument-sound></score-instrument>"
        for note, spec in {n: lookup(n) for m in measures for slot in m for n in slot}.items()
    )
    midi_instruments = "".join(
        f'<midi-instrument id="P1-I{note}"><midi-channel>10</midi-channel>'
        f"<midi-unpitched>{note + 1}</midi-unpitched></midi-instrument>"
        for note in {n for m in measures for slot in m for n in slot}
    )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <work><work-title>{escape(title)}</work-title></work>
  <defaults>
    <scaling><millimeters>{staff_mm:.3f}</millimeters><tenths>40</tenths></scaling>
  </defaults>
  <part-list>
    <score-part id="P1">
      <part-name>Drum Set</part-name>
      {score_instruments}
      {midi_instruments}
    </score-part>
  </part-list>
  <part id="P1">
    {"".join(parts_xml)}
  </part>
</score-partwise>
"""
    return xml
