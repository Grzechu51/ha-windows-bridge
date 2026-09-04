"""Compatibility facade for the overlay subsystem."""

from .overlays.card import OverlayCard
from .overlays.manager import OverlayManager

__all__ = ["OverlayCard", "OverlayManager"]
