"""Step 1 - read a MIDI file and pull out only the drum-channel note-on events.

Drum data in a Standard MIDI File lives on channel 10 (index 9). Anything
else - track names, other instrument channels, control changes, pitch bend,
etc. - is not music we can notate on a drum staff, so it is discarded here.
"""

from dataclasses import dataclass

import mido

from .drum_map import lookup

DRUM_CHANNEL = 9  # MIDI channel 10, zero-indexed


@dataclass
class DrumEvent:
    time_sec: float
    note: int
    velocity: int
    name: str


@dataclass
class ExtractionResult:
    events: list[DrumEvent]
    tempo_bpm: float
    time_signature: tuple[int, int]
    ticks_per_beat: int


def extract_drum_events(midi_path: str) -> ExtractionResult:
    midi = mido.MidiFile(midi_path)

    tempo_us_per_beat = 500000  # default 120 bpm
    time_signature = (4, 4)
    events: list[DrumEvent] = []

    for track in midi.tracks:
        abs_ticks = 0
        for msg in track:
            abs_ticks += msg.time
            if msg.type == "set_tempo":
                tempo_us_per_beat = msg.tempo
            elif msg.type == "time_signature":
                time_signature = (msg.numerator, msg.denominator)
            elif msg.type == "note_on" and msg.velocity > 0 and msg.channel == DRUM_CHANNEL:
                time_sec = mido.tick2second(abs_ticks, midi.ticks_per_beat, tempo_us_per_beat)
                spec = lookup(msg.note)
                events.append(
                    DrumEvent(
                        time_sec=time_sec,
                        note=msg.note,
                        velocity=msg.velocity,
                        name=spec["name"],
                    )
                )

    events.sort(key=lambda e: e.time_sec)
    tempo_bpm = 60_000_000 / tempo_us_per_beat

    return ExtractionResult(
        events=events,
        tempo_bpm=tempo_bpm,
        time_signature=time_signature,
        ticks_per_beat=midi.ticks_per_beat,
    )
