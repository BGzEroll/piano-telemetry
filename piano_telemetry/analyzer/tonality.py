from __future__ import annotations

from dataclasses import asdict, dataclass


DEFAULT_TONALITY = "C_major"


@dataclass(frozen=True, slots=True)
class Tonality:
    value: str
    label: str
    tonic_pitch_class: int
    tonic_letter: int
    mode: str
    fifths: int


# Enharmonic spellings are selected to keep every standard key signature at
# six or fewer sharps/flats while covering all twelve equal-tempered tonics.
TONALITIES: tuple[Tonality, ...] = (
    Tonality("C_major", "C 大调", 0, 0, "major", 0),
    Tonality("Db_major", "D♭ 大调", 1, 1, "major", -5),
    Tonality("D_major", "D 大调", 2, 1, "major", 2),
    Tonality("Eb_major", "E♭ 大调", 3, 2, "major", -3),
    Tonality("E_major", "E 大调", 4, 2, "major", 4),
    Tonality("F_major", "F 大调", 5, 3, "major", -1),
    Tonality("Fs_major", "F♯ 大调", 6, 3, "major", 6),
    Tonality("G_major", "G 大调", 7, 4, "major", 1),
    Tonality("Ab_major", "A♭ 大调", 8, 5, "major", -4),
    Tonality("A_major", "A 大调", 9, 5, "major", 3),
    Tonality("Bb_major", "B♭ 大调", 10, 6, "major", -2),
    Tonality("B_major", "B 大调", 11, 6, "major", 5),
    Tonality("C_minor", "C 小调", 0, 0, "minor", -3),
    Tonality("Cs_minor", "C♯ 小调", 1, 0, "minor", 4),
    Tonality("D_minor", "D 小调", 2, 1, "minor", -1),
    Tonality("Eb_minor", "E♭ 小调", 3, 2, "minor", -6),
    Tonality("E_minor", "E 小调", 4, 2, "minor", 1),
    Tonality("F_minor", "F 小调", 5, 3, "minor", -4),
    Tonality("Fs_minor", "F♯ 小调", 6, 3, "minor", 3),
    Tonality("G_minor", "G 小调", 7, 4, "minor", -2),
    Tonality("Gs_minor", "G♯ 小调", 8, 4, "minor", 5),
    Tonality("A_minor", "A 小调", 9, 5, "minor", 0),
    Tonality("Bb_minor", "B♭ 小调", 10, 6, "minor", -5),
    Tonality("B_minor", "B 小调", 11, 6, "minor", 2),
)

_BY_VALUE = {tonality.value: tonality for tonality in TONALITIES}
_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")


def normalize_tonality(value: object) -> str:
    if isinstance(value, str) and value in _BY_VALUE:
        return value
    return DEFAULT_TONALITY


def get_tonality(value: object) -> Tonality:
    return _BY_VALUE[normalize_tonality(value)]


def pitch_class_name(pitch_class: int, tonality: object) -> str:
    selected = get_tonality(tonality)
    names = _FLAT_NAMES if selected.fifths < 0 else _SHARP_NAMES
    return names[pitch_class % 12]


def tonalities_payload() -> list[dict[str, object]]:
    return [asdict(tonality) for tonality in TONALITIES]
