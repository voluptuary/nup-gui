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
from windows_gui import NupPackagerApp
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
        self.app = NupPackagerApp(self.root)
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
        original = self.work / "source.nup"
        target = self.work / "target.nup"
        pack(str(original), str(self.source))
        pack(str(target), str(self.source))
        icon = image_bytes("PNG")
        replace_metadata(original, [serialize_block({3: icon, 4: b"7.0", 5: b"Copy title", 6: b"Copy studio"})])
        self.app.copy_metadata_nup_to_nup()
        dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel))
        entries = [widget for widget in dialog.winfo_children() if widget.winfo_class() == "TEntry"]
        entries[0].insert(0, str(original))
        entries[1].insert(0, str(target))
        self.root.update()
        self.assertIsNotNone(dialog.preview_image)
        button = next(widget for widget in dialog.winfo_children()
                      if widget.winfo_class() == "TButton" and widget.cget("text") == "Edit metadata")
        with patch("windows_gui.messagebox.showinfo"), patch("windows_gui.messagebox.showerror") as error:
            button.invoke()
            deadline = time.monotonic() + 5
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.app.busy)
            error.assert_not_called()
        self.assertEqual(load_application(target).icon, icon)
        self.assertEqual(self.app.title_name.get(), "Copy title")
        self.assertIsNotNone(self.app.icon_image_ref)

    def test_invalid_import_keeps_current_fields_and_reports_error(self):
        invalid = self.work / "invalid.nup"
        invalid.write_bytes(b"not a NUP")
        self.app.title_name.set("Unsaved edit")
        with patch("windows_gui.filedialog.askopenfilename", return_value=str(invalid)), patch("windows_gui.messagebox.showerror") as error:
            self.app.import_from_nup()
            error.assert_called_once()
        self.assertEqual(self.app.title_name.get(), "Unsaved edit")

    def test_pack_and_unpack_layout_fit_the_window(self):
        for mode in ("pack", "unpack", "pack"):
            self.app.mode.set(mode)
            self.app.update_mode()
            self.root.update()
            for widget in (self.app.source_entry, self.app.output_entry, self.app.action_button):
                self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), self.root.winfo_height())
                self.assertLessEqual(widget.winfo_x() + widget.winfo_width(), self.root.winfo_width())
