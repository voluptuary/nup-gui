from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nup.access import app_meta, extract_dump
from nup import format as F
from nup.errors import OperationCancelled
from nup.operations import pack_atomic, unpack_atomic
from nup.pack import pack
from nup.read import NupReader
from nup.verify import verify


def file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file() and path.name != ".nup-metadata.json"
    }


class DumpRoundTripTests(unittest.TestCase):
    def test_control_icon_is_auto_detected_embedded_and_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "source"
            (source / "base" / "romfs").mkdir(parents=True)
            (source / "base" / "romfs" / "asset.bin").write_bytes(b"romfs data")
            icon = b"\x89PNG\r\n\x1a\n" + b"dummy png payload"
            icon_path = source / "base" / "control" / "icon.dat"
            icon_path.parent.mkdir(parents=True)
            icon_path.write_bytes(icon)
            package = work / "icon.nup"

            pack(str(package), str(source))
            self.assertEqual(verify(str(package), deep=True), (True, []))
            with NupReader(str(package)) as reader:
                self.assertEqual(app_meta(reader, reader.packages[0])[F.TLV_ICON], icon)

            restored = work / "restored"
            with NupReader(str(package)) as reader:
                extract_dump(reader, str(restored))
            self.assertEqual((restored / "base" / "control" / "icon.png").read_bytes(), icon)
            self.assertEqual((restored / "base" / "control" / "icon.dat").read_bytes(), icon)

    def test_existing_iconless_package_can_be_unpacked_and_repacked_with_icon(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "source"
            (source / "base" / "romfs").mkdir(parents=True)
            (source / "base" / "romfs" / "asset.bin").write_bytes(b"old game data")
            original = work / "original.nup"
            pack(str(original), str(source))

            restored = work / "restored"
            with NupReader(str(original)) as reader, patch("sys.stderr") as stderr:
                extract_dump(reader, str(restored))
                self.assertIn("missing artwork metadata", str(stderr.write.call_args_list))

            supplied_icon = restored / "base" / "control" / "icon.jpg"
            supplied_icon.parent.mkdir(parents=True)
            supplied_icon.write_bytes(b"\xff\xd8\xff" + b"jpeg payload")
            repacked = work / "repacked.nup"
            pack(str(repacked), str(restored),
                 names={None: "Test Game"}, display_version="1.2.3")
            self.assertEqual(verify(str(repacked), deep=True), (True, []))
            with NupReader(str(repacked)) as reader:
                meta = app_meta(reader, reader.packages[0])
                self.assertEqual(meta[F.TLV_ICON], supplied_icon.read_bytes())
                self.assertEqual(meta[F.TLV_TITLE_NAME], b"Test Game")
                self.assertEqual(meta[F.TLV_DISPLAY_VERSION], b"1.2.3")

    def test_pack_then_unpack_preserves_every_file_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "source"
            payloads = {
                "base/exefs/main": b"\x00NSO0\xff" + bytes(range(256)) * 4,
                "base/exefs/main.npdm": b"NPDM\x00binary\xffdata",
                "base/romfs/message.txt": "Switch 2 dump ✓\n".encode("utf-8"),
                "base/romfs/empty.bin": b"",
                "base/romfs/.listing": b"dump-tool listing bytes\x00",
                "base/romfs/repeated.bin": b"NUP round trip " * 32_000,
                "updates/458752/exefs/subsdk0": bytes(reversed(range(256))) * 17,
                "updates/458752/romfs/update.dat": b"update payload\x00\xff",
                "dlc/040074a01bf13001/0/romfs/dlc.dat": b"dlc payload\x00\xfe",
                "dlc/040074a01bf13001/7/romfs/second-dlc.dat": b"second add-on",
            }
            for relative, data in payloads.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (source / "base" / "romfs" / "empty-folder").mkdir()

            package = work / "game.nup"
            restored = work / "restored"
            repacked = work / "repacked.nup"
            restored_again = work / "restored-again"
            pack(str(package), str(source), keep_listings=True)
            progress: list[tuple[int, int, str]] = []
            with NupReader(str(package)) as reader:
                written = extract_dump(reader, str(restored),
                                       lambda done, total, name: progress.append((done, total, name)))

            self.assertEqual(written, len(payloads))
            self.assertEqual(progress[-1][:2], (len(payloads), len(payloads)))
            self.assertEqual(file_hashes(source), file_hashes(restored))
            source_dirs = {
                path.relative_to(source).as_posix()
                for path in source.rglob("*") if path.is_dir()
            }
            restored_dirs = {
                path.relative_to(restored).as_posix()
                for path in restored.rglob("*") if path.is_dir()
            }
            self.assertEqual(source_dirs, restored_dirs)

            pack(str(repacked), str(restored), keep_listings=True)
            with NupReader(str(repacked)) as reader:
                extract_dump(reader, str(restored_again))
            self.assertEqual(file_hashes(source), file_hashes(restored_again))
            restored_again_dirs = {
                path.relative_to(restored_again).as_posix()
                for path in restored_again.rglob("*") if path.is_dir()
            }
            self.assertEqual(source_dirs, restored_again_dirs)

    def test_cancel_pack_removes_partial_output_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "source"
            for name, data in (("one.bin", b"one"), ("two.bin", b"two")):
                path = source / "base" / "romfs" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            original_hashes = file_hashes(source)
            cancel = threading.Event()

            def stop_after_first_file(done: int, _total: int, _node: object) -> None:
                if done == 1:
                    cancel.set()

            output = work / "cancelled.nup"
            with self.assertRaises(OperationCancelled):
                pack_atomic(str(output), str(source), progress=stop_after_first_file,
                            cancel=cancel.is_set)

            self.assertFalse(output.exists())
            self.assertEqual(file_hashes(source), original_hashes)
            self.assertFalse(any(work.glob(".nup-pack-*")))

    def test_cancel_unpack_removes_partial_output_and_preserves_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source = work / "source"
            for name, data in (("one.bin", b"one"), ("two.bin", b"two")):
                path = source / "base" / "romfs" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            package = work / "input.nup"
            pack(str(package), str(source), keep_listings=True)
            original_package_hash = hashlib.sha256(package.read_bytes()).digest()
            cancel = threading.Event()

            def stop_after_first_file(done: int, _total: int, _name: str) -> None:
                if done == 1:
                    cancel.set()

            output = work / "cancelled-dump"
            with self.assertRaises(OperationCancelled):
                unpack_atomic(str(package), str(output), progress=stop_after_first_file,
                              cancel=cancel.is_set)

            self.assertFalse(output.exists())
            self.assertEqual(hashlib.sha256(package.read_bytes()).digest(), original_package_hash)
            self.assertFalse(any(work.glob(".nup-unpack-*")))


if __name__ == "__main__":
    unittest.main()
