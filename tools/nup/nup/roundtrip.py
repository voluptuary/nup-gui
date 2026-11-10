"""Lossless metadata sidecar for NUP -> dump -> NUP conversions."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path, PurePosixPath

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
    if not path.exists() and not path.is_symlink():
        return {}
    try:
        from .sourceio import open_source
        if not path.is_file() or path.is_symlink():
            raise ValueError("sidecar must be a regular file without links")
        with open_source(str(path)) as stream:
            data = json.loads(stream.read().decode("utf-8"))
        if not isinstance(data, dict) or type(data.get("format")) is not int or data["format"] != 1:
            raise ValueError("unsupported sidecar version")
        root = Path(source).resolve()
        seen = set()
        if not isinstance(data.get("packages"), list) or not data["packages"]:
            raise ValueError("packages must be a nonempty list")
        from .access import _valid_windows_component
        for package in data["packages"]:
            if not isinstance(package, dict):
                raise ValueError("package must be an object")
            relative = package["path"]
            if not isinstance(relative, str):
                raise ValueError("package path must be text")
            parts = PurePosixPath(relative).parts
            if (not parts or relative != "/".join(parts)
                    or not all(_valid_windows_component(part) for part in parts)):
                raise ValueError("noncanonical or unsafe package path")
            for field, upper in (("title_id", 2**64), ("version", 2**32), ("kind", len(F.Kind)), ("flags", 256)):
                if type(package.get(field)) is not int or not 0 <= package[field] < upper:
                    raise ValueError(f"invalid package {field}")
            if package["flags"] & ~F.PKG_FLAG_STANDALONE_UPDATE:
                raise ValueError("unknown package flags")
            if relative.casefold() in seen or not (root / relative).resolve().is_relative_to(root):
                raise ValueError("duplicate or unsafe package path")
            seen.add(relative.casefold())
            block = base64.b64decode(package["block"], validate=True)
            from .meta import parse_block
            parse_block(block)
            package["raw_block"] = block
        artwork = data.get("artwork", [])
        if not isinstance(artwork, list):
            raise ValueError("artwork must be a list")
        artwork_seen = set()
        for item in artwork:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("invalid generated artwork entry")
            relative = item["path"]
            allowed = {package["path"] + "/control/icon" + extension
                       for package in data["packages"] for extension in (".jpg", ".png")}
            if relative not in allowed or relative in artwork_seen:
                raise ValueError("unsafe or duplicate generated artwork path")
            if not (root / relative).resolve().is_relative_to(root):
                raise ValueError("generated artwork escapes dump")
            if not isinstance(item.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", item["sha256"]):
                raise ValueError("invalid generated artwork hash")
            if type(item.get("created_directory", False)) is not bool:
                raise ValueError("invalid generated artwork directory flag")
            artwork_seen.add(relative)
        return data
    except (KeyError, TypeError, ValueError, OSError, UnicodeError, RecursionError) as exc:
        raise F.NupError(f"Invalid {SIDECAR}: {exc}") from exc
