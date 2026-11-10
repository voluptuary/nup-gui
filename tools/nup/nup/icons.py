"""Artwork icon discovery and image type helpers."""

from __future__ import annotations

import os

from .sourceio import open_source
from .format import NupError


_ICON_NAMES = ("icon.png", "icon.jpg", "icon.jpeg", "icon.dat",
               "cover.jpg", "cover.png", "boxart.png", "boxart.jpg")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def is_icon_filename(name: str) -> bool:
    lowered = name.lower()
    return (lowered in _ICON_NAMES
            or (lowered.startswith("icon_") and lowered.endswith(".dat")))


def image_extension(data: bytes) -> str | None:
    """Return the recognized image extension, or None for unsupported bytes."""
    if data.startswith(_PNG_MAGIC):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return None


def is_supported_image(path: str) -> bool:
    try:
        with open_source(path) as stream:
            return image_extension(stream.read(8)) is not None
    except (OSError, NupError):
        return False


def detect_icon(source: str, package_dirs: list[str]) -> str | None:
    """Find a supported artwork file, preferring source-root and control assets."""
    source = os.path.abspath(source)
    candidates: list[str] = []

    def add_dir(directory: str) -> None:
        candidates.extend(os.path.join(directory, name) for name in _ICON_NAMES)
        try:
            localized = sorted(
                name for name in os.listdir(directory)
                if is_icon_filename(name)
            )
        except (OSError, NupError):
            localized = []
        candidates.extend(os.path.join(directory, name) for name in localized)

    add_dir(source)
    add_dir(os.path.join(source, "control"))
    for package_dir in package_dirs:
        add_dir(package_dir)
        for control_dir in ("control", os.path.join("romfs", "control"),
                            os.path.join("romfs", "Nintendo", "Contents", "registered")):
            add_dir(os.path.join(package_dir, control_dir))
    # A sidecar beside the selected source folder is a common GUI workflow.
    add_dir(os.path.dirname(source))
    for path in candidates:
        if os.path.isfile(path) and is_supported_image(path):
            return path
    return None
