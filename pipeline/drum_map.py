"""General MIDI percussion (channel 10) -> standard 5-line drum staff position.

Positions follow the common notation convention (bottom line = E4).
displaystep/displayoctave are used for <unpitched> in MusicXML; notehead
controls the note-head shape rendered by MuseScore. `sustain` marks
instruments that actually ring (cymbals, triangle, ...) - only those are
allowed to be drawn as a long held note in musicxml_gen; struck/damped
drums (kick, snare, toms, ...) always stay a short discrete note even if
the next hit is far away.
"""

DrumSpec = dict


GM_DRUM_MAP: dict[int, DrumSpec] = {
    # GarageBand Drummer uses 33 as an accented snare hit; not a standard GM
    # note (GM starts at 35), so it shares the snare's position/notehead
    33: {"name": "Snare (Accent)", "step": "C", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    35: {"name": "Acoustic Bass Drum", "step": "F", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    36: {"name": "Kick", "step": "F", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    37: {"name": "Side Stick", "step": "C", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},
    38: {"name": "Snare", "step": "C", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    40: {"name": "Electric Snare", "step": "C", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    # GM has 6 distinct tom notes, but real kits usually only have 3 - grouped
    # here in GM note-number order (low -> high pitch), 2 notes per tier, so
    # a fill using any of the 6 still lands on one of 3 clean staff positions.
    # Positioned relative to the snare (C5): low tom one space below, mid tom
    # one line above, high tom one space above.
    41: {"name": "Low Tom", "step": "A", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    43: {"name": "Low Tom", "step": "A", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    45: {"name": "Mid Tom", "step": "D", "octave": 5, "notehead": "normal", "voice": 2, "sustain": False},
    47: {"name": "High Tom", "step": "E", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    48: {"name": "High Tom", "step": "E", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    50: {"name": "High Tom", "step": "E", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    42: {"name": "Closed Hi-Hat", "step": "G", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},
    44: {"name": "Pedal Hi-Hat", "step": "D", "octave": 4, "notehead": "x", "voice": 2, "sustain": False},
    46: {"name": "Open Hi-Hat", "step": "G", "octave": 5, "notehead": "x", "voice": 1, "sustain": True},
    49: {"name": "Crash Cymbal 1", "step": "F", "octave": 5, "notehead": "circle-x", "voice": 1, "sustain": True},
    57: {"name": "Crash Cymbal 2", "step": "A", "octave": 5, "notehead": "circle-x", "voice": 1, "sustain": True},
    51: {"name": "Ride Cymbal 1", "step": "A", "octave": 5, "notehead": "cross", "voice": 1, "sustain": True},
    59: {"name": "Ride Cymbal 2", "step": "A", "octave": 5, "notehead": "cross", "voice": 1, "sustain": True},
    # this kit's Drummer track uses 54 for ride bell instead of GM's standard
    # 53 - both map to the same spot so either note number renders correctly
    53: {"name": "Ride Bell", "step": "F", "octave": 5, "notehead": "diamond", "voice": 1, "sustain": True},
    54: {"name": "Ride Bell", "step": "F", "octave": 5, "notehead": "diamond", "voice": 1, "sustain": True},
    39: {"name": "Hand Clap", "step": "A", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},
    # remaining standard GM percussion key map (35-81), so nothing falls
    # through to the ambiguous fallback and gets mistaken for the snare
    52: {"name": "Chinese Cymbal", "step": "A", "octave": 5, "notehead": "x", "voice": 1, "sustain": True},
    55: {"name": "Splash Cymbal", "step": "F", "octave": 5, "notehead": "x", "voice": 1, "sustain": True},
    56: {"name": "Cowbell", "step": "A", "octave": 5, "notehead": "triangle", "voice": 1, "sustain": False},
    58: {"name": "Vibraslap", "step": "A", "octave": 4, "notehead": "diamond", "voice": 2, "sustain": True},
    60: {"name": "Hi Bongo", "step": "D", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    61: {"name": "Low Bongo", "step": "B", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    62: {"name": "Mute Hi Conga", "step": "E", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    63: {"name": "Open Hi Conga", "step": "D", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    64: {"name": "Low Conga", "step": "B", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    65: {"name": "High Timbale", "step": "E", "octave": 5, "notehead": "normal", "voice": 1, "sustain": False},
    66: {"name": "Low Timbale", "step": "A", "octave": 4, "notehead": "normal", "voice": 2, "sustain": False},
    67: {"name": "High Agogo", "step": "D", "octave": 5, "notehead": "triangle", "voice": 1, "sustain": False},
    68: {"name": "Low Agogo", "step": "B", "octave": 4, "notehead": "triangle", "voice": 2, "sustain": False},
    # off the hi-hat's G5/x - cabasa/maracas/shaker are commonly layered
    # under a live hi-hat pattern in the same song, so sharing hi-hat's
    # position made them render as doubled-up identical noteheads whenever
    # both played at once
    69: {"name": "Cabasa", "step": "B", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},
    70: {"name": "Maracas", "step": "B", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},
    71: {"name": "Short Whistle", "step": "E", "octave": 5, "notehead": "triangle", "voice": 1, "sustain": True},
    72: {"name": "Long Whistle", "step": "E", "octave": 5, "notehead": "triangle", "voice": 1, "sustain": True},
    73: {"name": "Short Guiro", "step": "A", "octave": 4, "notehead": "x", "voice": 2, "sustain": False},
    74: {"name": "Long Guiro", "step": "A", "octave": 4, "notehead": "x", "voice": 2, "sustain": False},
    75: {"name": "Claves", "step": "B", "octave": 4, "notehead": "x", "voice": 2, "sustain": False},
    76: {"name": "Hi Wood Block", "step": "D", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},
    77: {"name": "Low Wood Block", "step": "B", "octave": 4, "notehead": "x", "voice": 2, "sustain": False},
    78: {"name": "Mute Cuica", "step": "A", "octave": 4, "notehead": "diamond", "voice": 2, "sustain": True},
    79: {"name": "Open Cuica", "step": "D", "octave": 5, "notehead": "diamond", "voice": 1, "sustain": True},
    80: {"name": "Mute Triangle", "step": "E", "octave": 5, "notehead": "triangle", "voice": 1, "sustain": True},
    81: {"name": "Open Triangle", "step": "E", "octave": 5, "notehead": "triangle", "voice": 1, "sustain": True},
    82: {"name": "Shaker", "step": "B", "octave": 5, "notehead": "x", "voice": 1, "sustain": False},  # GM2 extension
}

GHOST_VELOCITY_DEFAULT = 30


def lookup(note: int) -> DrumSpec:
    return GM_DRUM_MAP.get(
        note,
        # deliberately distinct from the snare (C5/normal) so an unmapped
        # note is visibly obvious instead of silently reading as a snare hit
        {"name": f"Note {note}", "step": "E", "octave": 4, "notehead": "diamond", "voice": 1, "sustain": False},
    )
