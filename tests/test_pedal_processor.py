import pytest

from piano_telemetry.midi.pedal_processor import PedalProcessor


@pytest.mark.parametrize("channel", range(16))
@pytest.mark.parametrize("value,expected", [(0, 0), (1, 0), (63, 0), (64, 80), (127, 80)])
def test_fixed_mapping_preserves_channel_and_input(channel, value, expected) -> None:
    processor = PedalProcessor(enabled=True)
    message = [0xB0 | channel, 64, value]
    assert processor.process(message) == [0xB0 | channel, 64, expected]
    assert message == [0xB0 | channel, 64, value]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("message", [
    [0x90, 60, 100], [0x90, 60, 0], [0x8F, 60, 45], [0xB1, 1, 127],
    [0xB4, 66, 127], [0xF0, 64, 127, 0xF7], [0xF8], [0xFE],
    [0xC3, 5], [0xD8, 80], [0xE2, 0, 64], [0xAF, 60, 77], [], [0xB0, 64],
])
def test_other_messages_are_returned_unchanged(enabled, message) -> None:
    assert PedalProcessor(enabled=enabled).process(message) is message


@pytest.mark.parametrize("channel", range(16))
@pytest.mark.parametrize("value", [0, 1, 63, 64, 100, 127])
def test_disabled_pedal_is_exact_pass_through(channel, value) -> None:
    message = [0xB0 | channel, 64, value]
    assert PedalProcessor().process(message) is message


@pytest.mark.parametrize("depth", [63, 128, 80.5, True, "80", None])
def test_invalid_depth_is_rejected(depth) -> None:
    with pytest.raises(ValueError):
        PedalProcessor(depth=depth)
