from __future__ import annotations

import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows_gui import NupPackagerApp, configure_error_log
from nup.application import load_application
from nup.meta import serialize_block
from nup.pack import pack
from test_metadata import image_bytes, replace_metadata


@unittest.skipUnless(os.environ.get("DISPLAY"), "GUI tests require Xvfb or a display")
class GuiMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.root = tk.Tk()
        with patch("windows_gui.configure_error_log", return_value=configure_error_log(self.work)):
            self.app = NupPackagerApp(self.root)
        self.root.update_idletasks()
        self.addCleanup(self.app.close)
        self.source = self.work / "dump"
        (self.source / "base/romfs").mkdir(parents=True)
        (self.source / "base/romfs/data").write_bytes(b"game data")

    def test_import_jpeg_preview_and_create_keeps_imported_and_edited_values(self):
        original = self.work / "original.nup"
        pack(str(original), str(self.source))
        icon = image_bytes()
        replace_metadata(original, [serialize_block({3: icon, 4: b"5.1", 5: b"Imported title", 6: b"Imported publisher"})])
        with patch("windows_gui.filedialog.askopenfilename", return_value=str(original)):
            self.app.import_from_nup()
        self.assertEqual(self.app.title_name.get(), "Imported title")
        self.assertEqual(self.app.publisher.get(), "Imported publisher")
        self.assertEqual(self.app.display_version.get(), "5.1")
        self.assertIsNotNone(self.app.icon_image_ref)
        self.assertLessEqual(self.app.icon_image_ref.width(), 96)
        self.assertLessEqual(self.app.icon_image_ref.height(), 96)
        self.app.title_name.set("Manually edited title")
        self.app.source.set(str(self.source))
        output = self.work / "new.nup"
        self.app.output.set(str(output))

        class ImmediateThread:
            def __init__(self, target, args, **_kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)

        with patch("windows_gui.threading.Thread", ImmediateThread), patch("windows_gui.messagebox.showinfo"), patch("windows_gui.messagebox.showerror") as error:
            self.app.start_operation()
            self.app.drain_events()
            error.assert_not_called()
        actual = load_application(output)
        self.assertEqual((actual.title, actual.publisher, actual.version, actual.icon),
                         ("Manually edited title", "Imported publisher", "5.1", icon))

    def test_edit_dialog_previews_and_verifies_target_without_freezing(self):
        original = self.work / "source & $ café.nup"
        target = self.work / "target & $ café.nup"
        pack(str(original), str(self.source))
        pack(str(target), str(self.source))
        icon = image_bytes("PNG")
        replace_metadata(original, [serialize_block({3: icon, 4: b"7.0", 5: "Title: café & $ 日本語".encode(), 6: "Studio: & $ €".encode()})])
        self.app.copy_metadata_nup_to_nup()
        dialog = self.app.editor_frame
        self.assertFalse(any(isinstance(widget, tk.Toplevel) for widget in self.root.winfo_children()))
        entries = [widget for widget in dialog.winfo_children() if widget.winfo_class() == "TEntry"]
        entries[0].insert(0, str(original))
        entries[1].insert(0, str(target))
        self.root.update()
        self.assertIsNotNone(dialog.preview_image)
        button = self.app.editor_transfer_button
        with patch("windows_gui.messagebox.askyesno", return_value=True), patch("windows_gui.messagebox.showinfo"), patch("windows_gui.messagebox.showerror") as error:
            button.invoke()
            deadline = time.monotonic() + 5
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.app.busy)
            error.assert_not_called()
        self.assertEqual(load_application(target).icon, icon)
        self.assertEqual(self.app.title_name.get(), "Title: café & $ 日本語")
        self.assertIsNotNone(self.app.icon_image_ref)

    def test_invalid_import_keeps_current_fields_and_reports_error(self):
        invalid = self.work / "invalid.nup"
        invalid.write_bytes(b"not a NUP")
        self.app.title_name.set("Unsaved edit")
        with patch("windows_gui.filedialog.askopenfilename", return_value=str(invalid)), patch("windows_gui.messagebox.showerror") as error:
            self.app.import_from_nup()
            error.assert_called_once()
        self.assertEqual(self.app.title_name.get(), "Unsaved edit")
        log = self.app.error_log_path.read_text(encoding="utf-8")
        self.assertIn("Import Failed", log)
        self.assertIn("Traceback", log)
        with patch("windows_gui.messagebox.showerror"):
            self.app.report_callback_exception(ValueError, ValueError("second: & $ 日本語"), None)
        updated = self.app.error_log_path.read_text(encoding="utf-8")
        self.assertTrue(updated.startswith(log))
        self.assertIn("second: & $ 日本語", updated)

    def test_pack_and_unpack_layout_fit_the_window(self):
        for mode in ("pack", "unpack", "pack"):
            self.app.mode.set(mode)
            self.app.update_mode()
            self.root.update()
            for widget in (self.app.source_entry, self.app.output_entry, self.app.action_button):
                self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), self.root.winfo_height())
                self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), self.root.winfo_width())

    def test_editor_mode_buttons_and_source_update_preserve_special_characters(self):
        original = self.work / "source & $ café.nup"
        pack(str(original), str(self.source))
        self.app.copy_nup_button.invoke()
        self.app.editor_source.set(str(original))
        value = "Edited: café & $ 日本語"
        self.app.editor_title.set(value)
        self.app.editor_publisher.set(value)
        self.app.editor_version.set("v1: & $")
        self.root.update()
        widths = {button.winfo_width() for button in self.app.editor_buttons}
        self.assertEqual(len(widths), 1)
        self.assertGreater(self.app.editor_transfer_button.winfo_x(), self.app.editor_update_button.winfo_x())
        with patch("windows_gui.messagebox.askyesno", return_value=True), patch("windows_gui.messagebox.showinfo"), patch("windows_gui.messagebox.showerror") as error:
            self.app.editor_update_button.invoke()
            deadline = time.monotonic() + 10
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.app.busy)
            error.assert_not_called()
        actual = load_application(original)
        self.assertEqual((actual.title, actual.publisher, actual.version), (value, value, "v1: & $"))
        self.app.mode.set("pack")
        self.app.update_mode()
        self.root.update()
        self.assertFalse(self.app.editor_frame.winfo_ismapped())
        self.app.copy_nup_button.invoke()
        self.assertEqual(self.app.editor_title.get(), value)

    def test_failed_background_transfer_is_logged_and_keeps_editor_open(self):
        original = self.work / "valid.nup"
        target = self.work / "broken.nup"
        pack(str(original), str(self.source))
        replace_metadata(original, [serialize_block({5: b"Title: & $"})])
        pack(str(target), str(self.source))
        self.app.copy_nup_button.invoke()
        self.app.editor_source.set(str(original))
        self.app.editor_target.set(str(target))
        with patch("windows_gui.messagebox.askyesno", return_value=True), patch("windows_gui.copy_application", side_effect=OSError("Test write failure: & $")), patch("windows_gui.messagebox.showerror") as error:
            self.app.editor_transfer_button.invoke()
            deadline = time.monotonic() + 10
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.app.busy)
            error.assert_called_once()
        self.assertTrue(self.app.editor_frame.winfo_exists())
        log = self.app.error_log_path.read_text(encoding="utf-8")
        self.assertIn("Metadata operation", log)
        self.assertIn("Traceback", log)
        self.assertIn("Edit Failed", log)

    def test_transfer_confirmation_summarizes_changes_and_cancel_preserves_packages(self):
        original = self.work / "source & $.nup"
        target = self.work / "target & $.nup"
        pack(str(original), str(self.source))
        pack(str(target), str(self.source))
        replace_metadata(original, [serialize_block({5: "New: café & $ 日本語".encode(), 6: b"Studio"})])
        source_bytes, target_bytes = original.read_bytes(), target.read_bytes()
        self.app.copy_nup_button.invoke()
        self.app.editor_source.set(str(original))
        self.app.editor_target.set(str(target))
        with patch("windows_gui.messagebox.askyesno", return_value=False) as confirm:
            self.app.editor_transfer_button.invoke()
        confirm.assert_called_once()
        title, summary = confirm.call_args.args
        self.assertEqual(title, "Confirm metadata transfer")
        for text in (str(original), str(target), "New: café & $ 日本語", "Publisher", "remain unchanged"):
            self.assertIn(text, summary)
        self.assertFalse(self.app.busy)
        self.assertEqual(original.read_bytes(), source_bytes)
        self.assertEqual(target.read_bytes(), target_bytes)
