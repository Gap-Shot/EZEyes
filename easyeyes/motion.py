"""Turning Up and Down key presses in Move mode into Steps and Glides."""

from __future__ import annotations

# A press shorter than this is a tap (a Step); a longer one Glides. Fixed by design.
HOLD_THRESHOLD = 0.3  # seconds


class KeyMotion:
    """Tracks the movement key being held. Directions are -1 (up) and 1 (down); times are in seconds."""

    def __init__(self) -> None:
        self._direction = 0
        self._pressed_at = 0.0
        self._glided_until: float | None = None

    @property
    def held(self) -> bool:
        return self._direction != 0

    def press(self, direction: int, now: float) -> None:
        if direction == self._direction:
            return  # key repeat
        # Pressing the other direction abandons the first key without a Step.
        self._direction = direction
        self._pressed_at = now
        self._glided_until = None

    def advance(self, now: float, glide_speed: float) -> float:
        """Pixels glided since the last call, signed by direction."""
        if not self._direction:
            return 0.0
        glide_start = self._pressed_at + HOLD_THRESHOLD
        if now < glide_start:
            return 0.0
        since = glide_start if self._glided_until is None else self._glided_until
        self._glided_until = now
        return self._direction * glide_speed * max(0.0, now - since)

    def release(self, direction: int, now: float, text_line_spacing: float, glide_speed: float) -> float:
        """Pixels to move when the key comes up: a whole Step after a tap, or the rest of a Glide."""
        if direction != self._direction:
            return 0.0
        if now - self._pressed_at < HOLD_THRESHOLD:
            distance = direction * text_line_spacing
        else:
            distance = self.advance(now, glide_speed)
        self.cancel()
        return distance

    def cancel(self) -> None:
        self._direction = 0
        self._glided_until = None
