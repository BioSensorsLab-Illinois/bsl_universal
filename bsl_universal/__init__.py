"""
bsl_universal package.

The package intentionally keeps top-level imports lightweight so hardware
drivers and optional SDK dependencies are loaded only when explicitly used.
"""

__all__ = [
    "analysis",
    "instruments",
    "core",
]
