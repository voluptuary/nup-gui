"""Lossless metadata sidecar for NUP -> dump -> NUP conversions."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from . import format as F

SIDECAR = ".nup-metadata.json"


def write_sidecar(reader, destination: str, targets, artwork: list[dict]) -> None:
    packages = []
    for package, relative in targets:
        block = bytes(reader._mm[package.meta_offset:package.meta_offset + package.meta_size])
        packages.append(dict(path=Path(relative).as_posix(), title_id=package.title_id,
                             kind=int(package.kind), version=package.version, flags=package.flags,
                             block=base64.b64encode(block).decode("ascii")))
    path = Path(destination) / SIDECAR
    path.write_text(json.dumps(dict(format=1, packages=packages, artwork=artwork),
                               indent=2) + "\n", encoding="utf-8")


def read_sidecar(source: str) -> dict:
    path = Path(source) / SIDECAR
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["format"] != 1:
            raise ValueError("unsupported sidecar version")
        root = Path(source).resolve()
        seen = set()
        for package in data["packages"]:
            relative = package["path"]
            if relative in seen or not (root / relative).resolve().is_relative_to(root):
                raise ValueError("duplicate or unsafe package path")
            seen.add(relative)
            block = base64.b64decode(package["block"], validate=True)
            pos = 0
            while pos < len(block):
                if pos + 8 > len(block):
                    raise ValueError("truncated metadata")
                _, reserved, size = F._tlv_s.unpack_from(block, pos)
                if reserved or pos + 8 + size > len(block):
                    raise ValueError("invalid metadata record")
                pos += 8 + size
            package["raw_block"] = block
        return data
    except (KeyError, TypeError, ValueError) as exc:
        raise F.NupError(f"Invalid {SIDECAR}: {exc}") from exc
