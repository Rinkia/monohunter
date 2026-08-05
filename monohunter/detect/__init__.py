"""Detection engine: a Detector interface with pluggable implementations."""

from .base import Candidate, Detector
from .box import BoxMatchedFilter

__all__ = ["Candidate", "Detector", "BoxMatchedFilter"]
