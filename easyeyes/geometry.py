"""Where the ruler's parts sit on a monitor, in logical pixels. Positive y is down."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Band:
    """A horizontal strip across the monitor."""

    top: int
    height: int


@dataclass(frozen=True)
class RulerLayout:
    reading_window: Band
    top_guide_line: Band
    bottom_guide_line: Band

    @property
    def extent(self) -> Band:
        """The strip covering both guide lines and the reading window between them."""
        top = self.top_guide_line.top
        bottom = self.bottom_guide_line.top + self.bottom_guide_line.height
        return Band(top, bottom - top)


def center_limits(monitor_height: float, reading_window_height: float) -> tuple[float, float]:
    """The highest and lowest centers that keep the reading window on the monitor."""
    if monitor_height <= reading_window_height:
        return monitor_height / 2, monitor_height / 2
    half = reading_window_height / 2
    return half, monitor_height - half


def clamp_center(center: float, monitor_height: float, reading_window_height: float) -> float:
    low, high = center_limits(monitor_height, reading_window_height)
    return min(max(center, low), high)


def center_from_position(ruler_position: float, monitor_height: float, reading_window_height: float) -> float:
    return clamp_center(ruler_position / 100 * monitor_height, monitor_height, reading_window_height)


def position_from_center(center: float, monitor_height: float) -> float:
    return center / monitor_height * 100 if monitor_height > 0 else 50.0


def moved_position(ruler_position: float, distance: float, monitor_height: float, reading_window_height: float) -> float:
    """The Ruler position after moving the ruler `distance` pixels, stopping at the monitor's edges."""
    center = center_from_position(ruler_position, monitor_height, reading_window_height)
    moved = clamp_center(center + distance, monitor_height, reading_window_height)
    return position_from_center(moved, monitor_height)


def placed_position(y: float, monitor_height: float, reading_window_height: float) -> float:
    """The Ruler position that puts the middle of the reading window at `y`, as far as the edges allow."""
    return position_from_center(clamp_center(y, monitor_height, reading_window_height), monitor_height)


def layout(center: float, reading_window_height: int, guide_line_thickness: int) -> RulerLayout:
    """The ruler around `center`, snapped to whole pixels. Guide lines grow outward from the reading window."""
    top = math.floor(center - reading_window_height / 2 + 0.5)
    bottom = top + reading_window_height
    return RulerLayout(
        reading_window=Band(top, reading_window_height),
        top_guide_line=Band(top - guide_line_thickness, guide_line_thickness),
        bottom_guide_line=Band(bottom, guide_line_thickness),
    )
