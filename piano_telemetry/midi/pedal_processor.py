from __future__ import annotations


class PedalProcessor:
    """Fixed CC64 mapping; the router serializes state and output together."""

    def __init__(self, *, enabled: bool = False, depth: int = 80) -> None:
        self.enabled = enabled
        self.depth = self._validate_depth(depth)
        self.reset()

    @staticmethod
    def _validate_depth(depth: int) -> int:
        if type(depth) is not int or not 64 <= depth <= 127:
            raise ValueError("Pedal depth must be an integer from 64 to 127")
        return depth

    @staticmethod
    def is_state_message(message: list[int]) -> bool:
        return (len(message) == 1 and message[0] == 0xFF) or (
            len(message) == 3
            and 0xB0 <= message[0] <= 0xBF
            and message[1] in (64, 121)
        )

    def reset(self) -> None:
        self._raw: list[int | None] = [None] * 16
        self._output: list[int | None] = [None] * 16

    def process(self, message: list[int]) -> list[int]:
        if len(message) == 1 and message[0] == 0xFF:
            self.reset()
        elif len(message) == 3 and 0xB0 <= message[0] <= 0xBF:
            channel = message[0] & 0x0F
            if message[1] == 121:
                self._raw[channel] = self._output[channel] = None
            elif message[1] == 64:
                self._raw[channel] = message[2]
                if self.enabled:
                    return [message[0], 64, self.depth if message[2] >= 64 else 0]
        return message

    def record_output(self, message: list[int]) -> None:
        if len(message) == 3 and 0xB0 <= message[0] <= 0xBF and message[1] == 64:
            self._output[message[0] & 0x0F] = message[2]

    def configure(self, *, enabled: bool, depth: int) -> list[list[int]]:
        self.depth = self._validate_depth(depth)
        self.enabled = enabled
        updates = []
        for channel, raw in enumerate(self._raw):
            # Unknown and released pedals must never acquire sustain on a setting change.
            if raw is not None and raw >= 64:
                value = self.depth if enabled else raw
                if value != self._output[channel]:
                    updates.append([0xB0 | channel, 64, value])
        return updates
