"""Typed failures used to preserve fail-closed status semantics."""

from __future__ import annotations


class AQGError(RuntimeError):
    """Base exception for expected AQG failures."""


class ConfigurationError(AQGError):
    """Policy or project configuration is invalid or incomplete."""


class InfrastructureError(AQGError):
    """A checker could not start or produce trustworthy evidence."""


class QualityFailure(AQGError):
    """A checker ran successfully and found a real quality defect."""
