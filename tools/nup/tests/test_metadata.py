from __future__ import annotations

import hashlib
import io
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from nup import format as F
from nup.access import extract_dump, meta_records
from nup.application import copy_application, dump_application, load_application, nacp_metadata
from nup.edit import edit
from nup.meta import _encode_localized, decode_localized, parse_block, serialize_block
from nup.operations import pack_atomic
from nup.pack import pack
from nup.read import NupReader
from nup.verify import verify


def image_bytes(kind="JPEG"):
    stream = io.BytesIO()
    Image.new("RGB", (256, 256), (28, 100, 170)).save(stream, format=kind)
    return stream.getvalue()


def replace_metadata(path, blocks):
    """Independent on-disk fixture writer using literal SPEC TLV numbers."""
    with NupReader(str(path)) as reader:
        data = bytearray(reader._mm)
        info = dict(reader.super)
        toc = bytearray(data[info["toc_offset"]:info["toc_offset"] + info["toc_size"]])
        end = min(p.meta_offset for p in reader.packages if p.meta_size)
        data = data[:end]
        for index, block in enumerate(blocks):
            # meta_offset and meta_size are at byte 32 and 40 of PackageRecord.
            struct.pack_into("<QI", toc, 48 + index * 64 + 32, len(data), len(block))
            data.extend(block)
        data[info["toc_offset"]:info["toc_offset"] + len(toc)] = toc
        data[:128] = F.pack_super(F.MAGIC, info["header_size"], info["header_version"],
                                 info["toc_offset"], len(toc), hashlib.sha256(toc).digest(),
                                 info["blob_offset"], len(data), len(blocks), info["flags"], info["uuid"])
    path.write_bytes(data)


def snapshot(path):
    with NupReader(str(path)) as r:
        return ([(p.title_id, int(p.kind), p.version, p.flags) for p in r.packages],
                list(r.dirs), list(r.children),
                [(f[0], r.read_file(i)) for i, f in enumerate(r.files)],
                [bytes(r._mm[p.meta_offset:p.meta_offset + p.meta_size]) for p in r.packages])


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.source = self.work / "dump"
        (self.source / "base/romfs/empty").mkdir(parents=True)
        (self.source / "base/romfs/data.bin").write_bytes(bytes(range(256)) * 64)
        (self.source / "base/romfs/.listing").write_bytes(b"listing\0\xff")

    def package(self, name="source.nup", title_id=0):
        path = self.work / name
        pack(str(path), str(self.source), keep_listings=True, base_title_id=title_id)
        return path

    def test_literal_spec_ids_populate_correct_fields(self):
        path = self.package()
        icon = image_bytes()
        replace_metadata(path, [serialize_block({3: icon, 4: b"9.2.0", 5: b"Correct title", 6: b"Correct publisher"})])
        meta = load_application(path)
        self.assertEqual((meta.title, meta.publisher, meta.version, meta.icon),
                         ("Correct title", "Correct publisher", "9.2.0", icon))
        self.assertEqual([int(F.TLV_NPDM), int(F.TLV_NACP), int(F.TLV_ICON),
                          int(F.TLV_TITLE_NAME), int(F.TLV_LOCALIZED_ICONS)], [1, 2, 3, 5, 10])

    def test_legacy_shifted_metadata_is_read_and_migrated_on_edit(self):
        path = self.package()
        icon = image_bytes()
        replace_metadata(path, [serialize_block({0: b"npdm", 2: icon, 3: b"1.2", 4: b"Old title", 5: b"Old publisher", 7: b"dump"})])
        self.assertEqual(load_application(path).title, "Old title")
        edit(str(path), name="Edited")
        with NupReader(str(path)) as r:
            records = dict(meta_records(r, r.packages[0]))
        self.assertEqual(records[1], b"npdm")
        self.assertEqual(records[3], icon)
        self.assertEqual(records[5], b"Edited")

    def test_complete_roundtrip_preserves_raw_metadata_identity_and_tree(self):
        (self.source / "updates/65536/romfs").mkdir(parents=True)
        (self.source / "updates/65536/romfs/update").write_bytes(b"patch")
        original = self.package(title_id=0x0100000000001000)
        icon = image_bytes()
        first = serialize_block({1: b"npdm\0", 3: icon, 4: b"2.3", 5: b"Title", 6: b"Studio",
                                 8: b"original dump", 9: _encode_localized({"ja": "名前".encode()}),
                                 10: _encode_localized({"fr": image_bytes("PNG")}), 0xF001: bytes(range(256))})
        # Also retain an unknown duplicate TLV's payload and original ordering.
        first += struct.pack("<HHI", 0xF001, 0, 3) + b"dup"
        second = serialize_block({7: b"b" * 32, 8: b"update source", 0xF002: b"opaque\0"})
        replace_metadata(original, [first, second])
        before = snapshot(original)
        restored = self.work / "restored"
        with NupReader(str(original)) as r:
            extract_dump(r, str(restored))
        repacked = self.work / "repacked.nup"
        pack(str(repacked), str(restored))
        self.assertEqual(verify(str(repacked), deep=True), (True, []))
        self.assertEqual(snapshot(repacked), before)
        self.assertEqual(load_application(repacked).icon, icon)
        self.assertEqual(dump_application(restored, []).publisher, "Studio")

    def test_copy_preserves_source_and_target_content_and_localized_metadata(self):
        source = self.package(title_id=0x0100000000001000)
        target = self.package("target.nup", title_id=0x0100000000002000)
        source_records = {2: bytes(0x4000), 3: image_bytes(), 4: b"3.1", 5: b"Source", 6: b"Source studio",
                          9: _encode_localized({"en-us": b"English", "ja": "日本語".encode()}),
                          10: _encode_localized({"ja": image_bytes("PNG")})}
        replace_metadata(source, [serialize_block(source_records)])
        replace_metadata(target, [serialize_block({1: b"target NPDM", 7: b"t" * 32, 8: b"target dump", 0xF001: b"target unknown"}) + struct.pack("<HHI", 0xF001, 0, 9) + b"duplicate"])
        original_source = source.read_bytes()
        before = snapshot(target)
        copy_application(str(source), str(target))
        self.assertEqual(source.read_bytes(), original_source)
        self.assertEqual(snapshot(target)[:4], before[:4])
        with NupReader(str(target)) as r:
            actual = dict(meta_records(r, r.packages[0]))
        for key, data in source_records.items():
            self.assertEqual(actual[key], data)
        for key, data in {1: b"target NPDM", 7: b"t" * 32, 8: b"target dump", 0xF001: b"target unknown"}.items():
            self.assertEqual(actual[key], data)
        self.assertIn(struct.pack("<HHI", 0xF001, 0, 9) + b"duplicate", snapshot(target)[4][0])
        self.assertEqual(verify(str(target), deep=True), (True, []))

    def test_localized_only_metadata_is_previewed_and_copied(self):
        source = self.package()
        target = self.package("target.nup")
        icon = image_bytes()
        replace_metadata(source, [serialize_block({9: _encode_localized({"en-us": b"Localized title"}),
                                                   10: _encode_localized({"en-us": icon})})])
        copied = copy_application(str(source), str(target))
        self.assertEqual((copied.title, copied.icon), ("Localized title", icon))
        self.assertEqual(load_application(target).icon, icon)

    def test_empty_source_is_not_reported_as_successful_copy(self):
        source = self.package()
        target = self.package("target.nup")
        original = target.read_bytes()
        with self.assertRaises(ValueError):
            copy_application(str(source), str(target))
        self.assertEqual(target.read_bytes(), original)

    def test_publisher_reaches_atomic_pack(self):
        target = self.work / "atomic.nup"
        pack_atomic(str(target), str(self.source), name="Title", publisher="Publisher", display_version="1.7")
        self.assertEqual(load_application(target).publisher, "Publisher")

    def test_dump_uses_nacp_text_instead_of_guessing_from_folder_and_integer(self):
        data = bytearray(0x4000)
        data[:10] = b"Real title"
        data[0x200:0x206] = b"Studio"
        data[0x3060:0x3065] = b"4.5.6"
        (self.source / "base/control.nacp").write_bytes(data)
        meta = dump_application(self.source, [str(self.source / "base")])
        self.assertEqual((meta.title, meta.publisher, meta.version), ("Real title", "Studio", "4.5.6"))

    def test_compressed_nacp_and_cli_pack_use_real_text(self):
        import zlib
        titles = bytearray(32 * 0x300)
        titles[:10] = b"Real title"
        titles[0x200:0x206] = b"Studio"
        compressor = zlib.compressobj(wbits=-15)
        compressed = compressor.compress(titles) + compressor.flush()
        data = bytearray(0x4000)
        data[:2] = len(compressed).to_bytes(2, "little")
        data[2:2 + len(compressed)] = compressed
        data[0x3215] = 1
        data[0x3060:0x3065] = b"4.5.6"
        (self.source / "base/control.nacp").write_bytes(data)
        self.assertEqual(nacp_metadata(data).title, "Real title")
        path = self.package()
        meta = load_application(path)
        self.assertEqual((meta.title, meta.publisher, meta.version), ("Real title", "Studio", "4.5.6"))

    def test_truncated_localized_records_have_clear_errors(self):
        for payload in (b"\x00", b"\x05en", b"\x02en\x10\0\0\0x"):
            with self.subTest(payload=payload), self.assertRaises(F.NupError):
                decode_localized(payload)
