"""Step 1 - read a MIDI file and pull out only the drum-channel note-on events.

Drum data in a Standard MIDI File normally lives on channel 10 (index 9).
If nothing is found there, some DAW exports (e.g. GarageBand's "Drummer"
track) put the drum part on a different channel instead, sharing that
channel with other instruments - so as a fallback we look for a track
whose *name* identifies it as the drum part and pull notes from that
specific track only, regardless of its channel number.

Anything else - other instrument tracks, control changes, pitch bend, etc. -
is not music we can notate on a drum staff, so it is discarded here.
"""

from dataclasses import dataclass

import mido

from .drum_map import lookup

DRUM_CHANNEL = 9  # MIDI channel 10, zero-indexed

# not part of a standard drum kit - dropped entirely rather than notated
EXCLUDED_NOTES = {34, 69, 70, 82}  # unmapped (GarageBand Drummer), Cabasa, Maracas, Shaker

DRUM_TRACK_NAME_KEYWORDS = ("drum", "drummer", "드럼")


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


def _decode_track_name(raw: str | None) -> str:
    """mido decodes meta-text as latin-1, which is byte-preserving - so a
    UTF-8-encoded name (e.g. Korean track names from some DAWs) comes out
    mojibake'd rather than raising. Round-tripping through latin-1 -> utf-8
    recovers it; if that fails, the name just wasn't UTF-8 to begin with."""
    if not raw:
        return ""
    try:
        return raw.encode("latin1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return raw


def _looks_like_drum_track(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in DRUM_TRACK_NAME_KEYWORDS)


def _collect_events(
    track, ticks_per_beat: int, tempo_us_per_beat: int, channel_filter: int | None
) -> list[DrumEvent]:
    events: list[DrumEvent] = []
    abs_ticks = 0
    for msg in track:
        abs_ticks += msg.time
        if msg.type == "set_tempo":
            tempo_us_per_beat = msg.tempo
        elif (
            msg.type == "note_on"
            and msg.velocity > 0
            and (channel_filter is None or msg.channel == channel_filter)
            and msg.note not in EXCLUDED_NOTES
        ):
            time_sec = mido.tick2second(abs_ticks, ticks_per_beat, tempo_us_per_beat)
            spec = lookup(msg.note)
            events.append(
                DrumEvent(time_sec=time_sec, note=msg.note, velocity=msg.velocity, name=spec["name"])
            )
    return events


def extract_drum_events(midi_path: str) -> ExtractionResult:
    midi = mido.MidiFile(midi_path)

    tempo_us_per_beat = 500000  # default 120 bpm
    time_signature = (4, 4)
    for track in midi.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                tempo_us_per_beat = msg.tempo
            elif msg.type == "time_signature":
                time_signature = (msg.numerator, msg.denominator)

    events: list[DrumEvent] = []
    for track in midi.tracks:
        events.extend(_collect_events(track, midi.ticks_per_beat, tempo_us_per_beat, DRUM_CHANNEL))

    if not events:
        # fall back to a named drum track on whatever channel it uses -
        # some DAW exports don't follow the channel-10 convention
        for track in midi.tracks:
            track_name = ""
            for msg in track:
                if msg.type == "track_name":
                    track_name = _decode_track_name(msg.name)
                    break
            if _looks_like_drum_track(track_name):
                events = _collect_events(track, midi.ticks_per_beat, tempo_us_per_beat, None)
                if events:
                    break

    events.sort(key=lambda e: e.time_sec)
    tempo_bpm = 60_000_000 / tempo_us_per_beat

    return ExtractionResult(
        events=events,
        tempo_bpm=tempo_bpm,
        time_signature=time_signature,
        ticks_per_beat=midi.ticks_per_beat,
    )
