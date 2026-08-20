from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MidiPorts:
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


def list_midi_ports() -> MidiPorts:
    rtmidi = _load_rtmidi()
    midi_in = rtmidi.MidiIn()
    midi_out = rtmidi.MidiOut()
    try:
        return MidiPorts(inputs=tuple(midi_in.get_ports()), outputs=tuple(midi_out.get_ports()))
    finally:
        del midi_in
        del midi_out


def resolve_port(selector: str, ports: tuple[str, ...], *, kind: str) -> int:
    """Resolve an index, exact name, or unique case-insensitive substring."""
    if not ports:
        raise RuntimeError(f"no MIDI {kind} ports are available")

    try:
        index = int(selector)
    except ValueError:
        index = -1
    if 0 <= index < len(ports):
        return index

    folded = selector.casefold()
    exact = [index for index, name in enumerate(ports) if name.casefold() == folded]
    if len(exact) == 1:
        return exact[0]

    partial = [index for index, name in enumerate(ports) if folded in name.casefold()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise RuntimeError(f"MIDI {kind} port not found: {selector!r}")
    matches = ", ".join(repr(ports[index]) for index in partial)
    raise RuntimeError(f"MIDI {kind} selector is ambiguous: {selector!r}; matches {matches}")


def _load_rtmidi():
    try:
        import rtmidi
    except ImportError as exc:
        raise RuntimeError(
            "python-rtmidi is not installed; install the project in the piano-midi environment"
        ) from exc
    return rtmidi

