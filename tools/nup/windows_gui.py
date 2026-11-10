"""Tkinter desktop front end for packing and unpacking NUP dumps."""

from __future__ import annotations

import os
import tempfile
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from nup.application import ApplicationMetadata, copy_application, dump_application, load_application
from nup.errors import OperationCancelled
from nup.icons import image_extension, is_supported_image
from nup.operations import pack_atomic, unpack_atomic


ICON_RELATIVE_PATH = Path("assets") / "NUP_GUI_Packager.ico"


def resource_path(relative_path: Path) -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / relative_path
    return Path(__file__).resolve().parent / "launcher" / relative_path


class NupPackagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue[tuple[str, str, str, str]] = queue.Queue()
        self.busy = False
        self.metadata_files = tempfile.TemporaryDirectory(prefix="nup-metadata-")
        self.cancel_event: threading.Event | None = None
        self.progress_mode = "indeterminate"
        self.mode = tk.StringVar(value="pack")
        self.source = tk.StringVar()
        self.icon = tk.StringVar()
        self.title_name = tk.StringVar()
        self.display_version = tk.StringVar()
        self.publisher = tk.StringVar()
        self.output = tk.StringVar()
        self.status = tk.StringVar(value="Choose a dump folder to package.")

        root.title("NUP Packager")
        root.geometry("800x440")
        root.minsize(760, 360)
        root.columnconfigure(1, weight=1)
        root.columnconfigure(2, minsize=120)
        root.protocol("WM_DELETE_WINDOW", self.close)
        try:
            root.iconbitmap(str(resource_path(ICON_RELATIVE_PATH)))
        except tk.TclError:
            pass

        self.pack_radio = ttk.Radiobutton(
            root, text="Pack .nup", variable=self.mode, value="pack",
            command=self.update_mode,
        )
        self.pack_radio.grid(row=0, column=0, sticky="w", padx=8, pady=(10, 4))
        self.unpack_radio = ttk.Radiobutton(
            root, text="Unpack .nup", variable=self.mode, value="unpack",
            command=self.update_mode,
        )
        self.unpack_radio.grid(row=0, column=1, sticky="w", padx=8, pady=(10, 4))

        self.source_label = ttk.Label(root)
        self.source_label.grid(row=1, column=0, sticky="w", padx=8, pady=8)
        self.source_entry = self.bind_entry(ttk.Entry(root, textvariable=self.source, width=45))
        self.source_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        self.source_button = ttk.Button(root, text="Browse...", command=self.browse_source)
        self.source_button.grid(row=1, column=2, sticky="ew", padx=8, pady=8)

        self.metadata_source_label = ttk.Label(root, text="Metadata source")
        self.metadata_source_label.grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.buttons_frame = ttk.Frame(root)
        self.buttons_frame.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 8), pady=4)
        self.import_dump_button = ttk.Button(self.buttons_frame, text="Import from dump", command=self.import_from_dump)
        self.import_dump_button.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self.import_nup_button = ttk.Button(self.buttons_frame, text="Import from .nup", command=self.import_from_nup)
        self.import_nup_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(8, 0))
        self.copy_nup_button = ttk.Button(self.buttons_frame, text="Edit existing .nup metadata", command=self.copy_metadata_nup_to_nup)
        self.copy_nup_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(8, 0))

        self.title_label = ttk.Label(root, text="Game title (optional)")
        self.title_label.grid(row=3, column=0, sticky="w", padx=8, pady=8)
        self.title_entry = self.bind_entry(ttk.Entry(root, textvariable=self.title_name, width=45))
        self.title_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=8)

        self.version_label = ttk.Label(root, text="Display version (optional)")
        self.version_label.grid(row=4, column=0, sticky="w", padx=8, pady=8)
        self.version_entry = self.bind_entry(ttk.Entry(root, textvariable=self.display_version, width=45))
        self.version_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=8)

        self.publisher_label = ttk.Label(root, text="Publisher (optional)")
        self.publisher_label.grid(row=5, column=0, sticky="w", padx=8, pady=8)
        self.publisher_entry = self.bind_entry(ttk.Entry(root, textvariable=self.publisher, width=45))
        self.publisher_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=8)

        # Icon preview spanning rows 3 to 5 in column 2 (to the right of title, version, publisher entries)
        self.icon_preview_label = ttk.Label(root, text="No artwork", anchor="center", relief="groove", width=16)
        self.icon_preview_label.grid(row=3, column=2, rowspan=3, sticky="nsew", padx=8, pady=4)

        self.icon_label = ttk.Label(root, text="Icon file (optional)")
        self.icon_label.grid(row=6, column=0, sticky="w", padx=8, pady=8)
        self.icon_entry = self.bind_entry(ttk.Entry(root, textvariable=self.icon, width=45))
        self.icon_entry.grid(row=6, column=1, sticky="ew", padx=8, pady=8)
        self.icon_button = ttk.Button(root, text="Browse...", command=self.browse_icon)
        self.icon_button.grid(row=6, column=2, sticky="ew", padx=8, pady=8)

        self.output_label = ttk.Label(root)
        self.output_label.grid(row=7, column=0, sticky="w", padx=8, pady=8)
        self.output_entry = self.bind_entry(ttk.Entry(root, textvariable=self.output, width=45))
        self.output_entry.grid(row=7, column=1, sticky="ew", padx=8, pady=8)
        self.output_button = ttk.Button(root, text="Browse...", command=self.browse_output)
        self.output_button.grid(row=7, column=2, sticky="ew", padx=8, pady=8)

        self.status_label = ttk.Label(root, textvariable=self.status, wraplength=720)
        root.bind("<Configure>", lambda event: self.status_label.configure(
            wraplength=max(400, event.width - 32)) if event.widget is root else None)
        self.status_label.grid(
            row=8, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 4)
        )
        self.progress = ttk.Progressbar(root, mode="indeterminate", maximum=100)
        self.progress.grid(row=9, column=0, columnspan=3, sticky="ew", padx=8, pady=5)
        self.progress.grid_remove()

        self.action_button = ttk.Button(root, command=self.start_operation)
        self.action_button.grid(row=10, column=2, sticky="e", padx=8, pady=10)
        self.cancel_button = ttk.Button(root, text="Cancel", command=self.cancel_operation)
        self.cancel_button.grid(row=10, column=1, sticky="e", padx=8, pady=10)
        self.cancel_button.grid_remove()

        self.icon_image_ref = None
        self.icon.trace_add("write", lambda *_: self.update_icon_preview())
        self.update_mode()
        self.poll_after_id = self.root.after(100, self.drain_events)

    def bind_entry(self, entry: ttk.Entry) -> ttk.Entry:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: entry.select_range(0, tk.END))

        def show_menu(event: tk.Event) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        entry.bind("<Button-3>", show_menu)
        entry.bind("<Button-2>", show_menu)
        return entry

    def update_icon_preview(self) -> None:
        icon_path = self.icon.get().strip()
        if not icon_path or not os.path.isfile(icon_path):
            self.icon_preview_label.configure(image="", text="No artwork")
            self.icon_image_ref = None
            return
        try:
            with Image.open(icon_path) as image:
                image.thumbnail((96, 96), Image.Resampling.LANCZOS)
                img = ImageTk.PhotoImage(image.convert("RGBA"), master=self.root)
            self.icon_preview_label.configure(image=img, text="")
            self.icon_image_ref = img
        except (OSError, ValueError, tk.TclError):
            self.icon_preview_label.configure(image="", text="Cannot preview image")
            self.icon_image_ref = None

    def show_metadata(self, metadata: ApplicationMetadata) -> None:
        # Parse completely before changing any fields, so a failed import keeps
        # the user's current edits. Temporary artwork lives until app close.
        icon_path = ""
        if metadata.icon:
            path = Path(self.metadata_files.name) / ("icon-" + str(time.time_ns()) +
                                                   (image_extension(metadata.icon) or ".dat"))
            path.write_bytes(metadata.icon)
            icon_path = str(path)
        self.title_name.set(metadata.title)
        self.publisher.set(metadata.publisher)
        self.display_version.set(metadata.version)
        self.icon.set(icon_path)

    def update_mode(self) -> None:
        if self.mode.get() == "pack":
            for widget in (self.buttons_frame,
                           self.icon_preview_label,
                           self.icon_label, self.icon_entry, self.icon_button,
                           self.title_label, self.title_entry,
                           self.version_label, self.version_entry,
                           self.publisher_label, self.publisher_entry):
                widget.grid()
            self.output_label.grid(row=7, column=0, sticky="w", padx=8, pady=8)
            self.output_entry.grid(row=7, column=1, sticky="ew", padx=8, pady=8)
            self.output_button.grid(row=7, column=2, sticky="ew", padx=8, pady=8)
            self.status_label.grid(row=8, column=0, columnspan=3,
                                   sticky="w", padx=8, pady=(10, 4))
            self.progress.grid(row=9, column=0, columnspan=3, sticky="ew", padx=8, pady=5)
            self.progress.grid_remove()
            self.action_button.grid(row=10, column=2, sticky="e", padx=8, pady=10)
            self.cancel_button.grid(row=10, column=1, sticky="e", padx=8, pady=10)
            self.cancel_button.grid_remove()
            self.root.geometry("800x420")
            self.source_label.configure(text="Dump parent folder")
            self.output_label.configure(text="Output .nup file")
            self.action_button.configure(text="Create NUP")
            self.status.set("Choose a dump folder to package.")
        else:
            for widget in (self.buttons_frame,
                           self.icon_preview_label,
                           self.icon_label, self.icon_entry, self.icon_button,
                           self.title_label, self.title_entry,
                           self.version_label, self.version_entry,
                           self.publisher_label, self.publisher_entry):
                widget.grid_remove()
            self.output_label.grid(row=2, column=0, sticky="w", padx=8, pady=8)
            self.output_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=8)
            self.output_button.grid(row=2, column=2, sticky="ew", padx=8, pady=8)
            self.status_label.grid(row=3, column=0, columnspan=3,
                                   sticky="w", padx=8, pady=(10, 4))
            self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", padx=8, pady=5)
            self.progress.grid_remove()
            self.action_button.grid(row=5, column=2, sticky="e", padx=8, pady=10)
            self.cancel_button.grid(row=5, column=1, sticky="e", padx=8, pady=10)
            self.cancel_button.grid_remove()
            self.root.geometry("800x280")
            self.source_label.configure(text="Input .nup file")
            self.output_label.configure(text="Output dump folder")
            self.action_button.configure(text="Extract NUP")
            self.status.set("Choose a .nup file to restore as a dump folder.")

    def import_from_nup(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a NUP package to import metadata from",
            filetypes=(("NUP package", "*.nup"), ("All files", "*.*")),
        )
        if not selected:
            return
        path = Path(selected)
        try:
            metadata = load_application(path)
            self.show_metadata(metadata)
            fields = [label for label, value in (("title", metadata.title),
                      ("publisher", metadata.publisher), ("version", metadata.version),
                      ("artwork", metadata.icon)) if value]
            self.status.set(f"Imported {', '.join(fields)} from {path.name}. Review before creating a package."
                            if fields else f"No application metadata found in {path.name}.")
        except Exception as exc:
            messagebox.showerror("Import Failed", f"Could not import metadata from {path.name}:\n{exc}", parent=self.root)

    def import_from_dump(self) -> None:
        selected_dir = filedialog.askdirectory(
            parent=self.root,
            title="Choose a dump folder to import metadata from",
            mustexist=True,
        )
        if selected_dir:
            self.auto_populate_metadata(Path(selected_dir))

    def copy_metadata_nup_to_nup(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Edit existing .nup metadata")
        dlg.geometry("800x470")
        dlg.minsize(740, 430)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.columnconfigure(1, weight=1)
        dlg.columnconfigure(2, minsize=112)

        src_var = tk.StringVar()
        dst_var = tk.StringVar()
        title_var = tk.StringVar()
        version_var = tk.StringVar()
        publisher_var = tk.StringVar()
        icon_var = tk.StringVar()
        status_v = tk.StringVar(value="Choose a source package to import from, or edit the selected target.")

        def choose_file(variable: tk.StringVar, title: str) -> None:
            selected = filedialog.askopenfilename(
                parent=dlg, title=title,
                filetypes=(("NUP package", "*.nup"), ("All files", "*.*")))
            if selected:
                variable.set(selected)

        ttk.Label(dlg, text="Source .nup file:").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        src_entry = self.bind_entry(ttk.Entry(dlg, textvariable=src_var, width=45))
        src_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(dlg, text="Browse...", command=lambda: choose_file(
            src_var, "Choose metadata source .nup")).grid(row=0, column=2, padx=8, pady=8)

        ttk.Label(dlg, text="Target .nup file:").grid(row=1, column=0, sticky="w", padx=10, pady=8)
        dst_entry = self.bind_entry(ttk.Entry(dlg, textvariable=dst_var, width=45))
        dst_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(dlg, text="Browse...", command=lambda: choose_file(
            dst_var, "Choose .nup file to edit")).grid(row=1, column=2, padx=8, pady=8)

        title_label = ttk.Label(dlg, text="Game title (optional)")
        title_label.grid(row=3, column=0, sticky="w", padx=10, pady=7)
        title_entry = self.bind_entry(ttk.Entry(dlg, textvariable=title_var, width=45))
        title_entry.grid(row=3, column=1, sticky="ew", padx=8, pady=7)
        version_label = ttk.Label(dlg, text="Display version (optional)")
        version_label.grid(row=4, column=0, sticky="w", padx=10, pady=7)
        version_entry = self.bind_entry(ttk.Entry(dlg, textvariable=version_var, width=45))
        version_entry.grid(row=4, column=1, sticky="ew", padx=8, pady=7)
        publisher_label = ttk.Label(dlg, text="Publisher (optional)")
        publisher_label.grid(row=5, column=0, sticky="w", padx=10, pady=7)
        publisher_entry = self.bind_entry(ttk.Entry(dlg, textvariable=publisher_var, width=45))
        publisher_entry.grid(row=5, column=1, sticky="ew", padx=8, pady=7)

        icon_label = ttk.Label(dlg, text="Icon file (optional)")
        icon_label.grid(row=6, column=0, sticky="w", padx=10, pady=7)
        icon_entry = self.bind_entry(ttk.Entry(dlg, textvariable=icon_var, width=45))
        icon_entry.grid(row=6, column=1, sticky="ew", padx=8, pady=7)

        def browse_edit_icon() -> None:
            selected = filedialog.askopenfilename(
                parent=dlg, title="Choose an application icon",
                filetypes=(("JPEG or PNG image", "*.jpg *.jpeg *.png *.dat"),
                           ("All files", "*.*")))
            if selected:
                if not is_supported_image(selected):
                    messagebox.showerror("Invalid Format", "Choose a valid JPEG or PNG image.", parent=dlg)
                    return
                icon_var.set(selected)

        ttk.Button(dlg, text="Browse...", command=browse_edit_icon).grid(
            row=6, column=2, sticky="ew", padx=8, pady=7)
        preview_icon = ttk.Label(dlg, text="No artwork", anchor="center", relief="groove", width=14)
        preview_icon.grid(row=3, column=2, rowspan=3, sticky="nsew", padx=8, pady=6)
        preview_text = tk.StringVar(value="Metadata preview")
        ttk.Label(dlg, textvariable=preview_text, wraplength=720).grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(5, 8))
        ttk.Label(dlg, textvariable=status_v, wraplength=720).grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 5))

        def show_dialog_metadata(metadata: ApplicationMetadata) -> None:
            title_var.set(metadata.title)
            version_var.set(metadata.version)
            publisher_var.set(metadata.publisher)
            icon_path = ""
            if metadata.icon:
                icon_path = str(Path(self.metadata_files.name) / f"edit-icon-{time.time_ns()}{image_extension(metadata.icon) or '.dat'}")
                Path(icon_path).write_bytes(metadata.icon)
            icon_var.set(icon_path)
            preview_text.set(f"Title: {metadata.title or '—'}  |  Publisher: {metadata.publisher or '—'}  |  Version: {metadata.version or '—'}")
            if metadata.icon:
                import io
                with Image.open(io.BytesIO(metadata.icon)) as image:
                    image.thumbnail((88, 88), Image.Resampling.LANCZOS)
                    dlg.preview_image = ImageTk.PhotoImage(image.convert("RGBA"), master=dlg)
                preview_icon.configure(image=dlg.preview_image, text="")
            else:
                preview_icon.configure(image="", text="No artwork")

        def refresh_fields(*_args) -> None:
            selected = src_var.get().strip() or dst_var.get().strip()
            if not selected or not os.path.isfile(selected):
                return
            try:
                show_dialog_metadata(load_application(selected))
            except Exception as exc:
                status_v.set(f"Could not load metadata: {exc}")

        src_var.trace_add("write", refresh_fields)
        dst_var.trace_add("write", refresh_fields)

        copying = False
        dlg.protocol("WM_DELETE_WINDOW", lambda: None if copying else dlg.destroy())
        edit_fields = (src_entry, dst_entry, title_entry, version_entry,
                       publisher_entry, icon_entry)
        actions_frame = ttk.Frame(dlg)
        actions_frame.grid(row=8, column=0, columnspan=3, sticky="e", padx=10, pady=10)
        update_source_button = ttk.Button(actions_frame, text="Update source")
        edit_button = ttk.Button(actions_frame, text="Transfer metadata")
        update_source_button.pack(side=tk.RIGHT)
        edit_button.pack(side=tk.RIGHT, padx=(0, 8))

        def execute_source_update() -> None:
            nonlocal copying
            source_path = src_var.get().strip()
            if not source_path or not os.path.isfile(source_path):
                messagebox.showerror(
                    "Source Required", "Choose a valid source .nup file to update.", parent=dlg)
                return
            try:
                before = load_application(source_path)
            except Exception as exc:
                messagebox.showerror(
                    "Source Read Failed", f"Could not read source metadata:\n{exc}", parent=dlg)
                return

            title = title_var.get().strip()
            version = version_var.get().strip()
            publisher = publisher_var.get().strip()
            icon_path = icon_var.get().strip()
            changes: list[str] = []
            overrides: dict[str, object] = {}

            if title != before.title:
                changes.append(f"Title: {before.title or '(empty)'} → {title or '(empty)'}")
                overrides.update(name=title or None, clear_name=not bool(title))
            if version != before.version:
                changes.append(f"Display version: {before.version or '(empty)'} → {version or '(empty)'}")
                overrides.update(display_version=version or None,
                                 clear_display_version=not bool(version))
            if publisher != before.publisher:
                changes.append(f"Publisher: {before.publisher or '(empty)'} → {publisher or '(empty)'}")
                overrides.update(publisher=publisher or None,
                                 clear_publisher=not bool(publisher))

            if icon_path and not os.path.isfile(icon_path):
                messagebox.showerror("Icon Not Found", "The selected icon file does not exist.", parent=dlg)
                return
            if icon_path and not is_supported_image(icon_path):
                messagebox.showerror("Invalid Format", "Choose a valid JPEG or PNG image.", parent=dlg)
                return
            icon_bytes = Path(icon_path).read_bytes() if icon_path else b""
            if icon_bytes != before.icon:
                def describe_icon(data: bytes) -> str:
                    if not data:
                        return "no icon"
                    extension = image_extension(data) or "image"
                    return f"{extension.lstrip('.').upper()} image ({len(data):,} bytes)"

                changes.append(f"Icon: {describe_icon(before.icon)} → {describe_icon(icon_bytes)}")
                if icon_path:
                    overrides["icon"] = icon_path
                else:
                    overrides["clear_icon"] = True

            if not changes:
                messagebox.showinfo(
                    "No Changes", "The source metadata already matches these fields.", parent=dlg)
                return

            summary = (
                f"Update metadata in this source package?\n{source_path}\n\n"
                + "\n".join(changes)
                + "\n\nOnly the listed application metadata fields will be changed. "
                  "Package contents and unrelated metadata will be preserved.\n\nContinue?"
            )
            if not messagebox.askyesno("Confirm source update", summary, parent=dlg):
                return

            copying = True
            self.busy = True
            self._set_controls_enabled(False)
            for widget in (*edit_fields, update_source_button, edit_button):
                widget.configure(state="disabled")
            status_v.set("Updating source metadata and verifying the package…")
            results = queue.Queue()

            def work() -> None:
                try:
                    from nup.edit import edit
                    edit(source_path, **overrides)
                    metadata = load_application(source_path)
                    results.put((metadata, None))
                except Exception as exc:
                    results.put((None, exc))

            def completed_source_update() -> None:
                nonlocal copying
                try:
                    metadata, error = results.get_nowait()
                except queue.Empty:
                    dlg.after(100, completed_source_update)
                    return
                copying = False
                self.busy = False
                self._set_controls_enabled(True)
                for widget in (*edit_fields, update_source_button, edit_button):
                    widget.configure(state="normal")
                if error:
                    status_v.set("Source update failed. Review the error before retrying.")
                    messagebox.showerror("Source Update Failed", str(error), parent=dlg)
                else:
                    show_dialog_metadata(metadata)
                    self.show_metadata(metadata)
                    status_v.set(f"Updated source metadata in {Path(source_path).name}.")
                    messagebox.showinfo(
                        "Source Updated",
                        f"Confirmed metadata changes were written to:\n{source_path}", parent=dlg)

            threading.Thread(target=work, daemon=True).start()
            dlg.after(100, completed_source_update)

        def execute_edit() -> None:
            nonlocal copying
            source_path = src_var.get().strip()
            target_path = dst_var.get().strip()
            if not target_path or not os.path.isfile(target_path):
                messagebox.showerror("Error", "Please select a valid target .nup file.", parent=dlg)
                return
            if source_path and (not os.path.isfile(source_path) or
                                Path(source_path).resolve() == Path(target_path).resolve()):
                messagebox.showerror("Error", "Choose a valid, different source .nup file.", parent=dlg)
                return
            if icon_var.get() and not is_supported_image(icon_var.get()):
                messagebox.showerror("Invalid Format", "Choose a valid JPEG or PNG image.", parent=dlg)
                return
            copying = True
            self.busy = True
            self._set_controls_enabled(False)
            for widget in (*edit_fields, update_source_button, edit_button):
                widget.configure(state="disabled")
            status_v.set("Editing metadata and verifying the target package…")
            results = queue.Queue()
            values = (title_var.get().strip(), version_var.get().strip(),
                      publisher_var.get().strip(), icon_var.get().strip())

            def work() -> None:
                try:
                    overrides = dict(name=values[0] or None,
                                     display_version=values[1] or None,
                                     publisher=values[2] or None,
                                     icon=values[3] or None,
                                     clear_name=not bool(values[0]),
                                     clear_display_version=not bool(values[1]),
                                     clear_publisher=not bool(values[2]),
                                     clear_icon=not bool(values[3]))
                    if source_path:
                        metadata = copy_application(source_path, target_path, **overrides)
                    else:
                        from nup.edit import edit
                        edit(target_path, **overrides)
                        metadata = load_application(target_path)
                    results.put((metadata, None))
                except Exception as exc:
                    results.put((None, exc))

            def completed() -> None:
                nonlocal copying
                try:
                    metadata, error = results.get_nowait()
                except queue.Empty:
                    dlg.after(100, completed)
                    return
                copying = False
                self.busy = False
                self._set_controls_enabled(True)
                for widget in (*edit_fields, update_source_button, edit_button):
                    widget.configure(state="normal")
                if error:
                    status_v.set("Edit failed. Review the error before retrying.")
                    messagebox.showerror("Edit Failed", str(error), parent=dlg)
                else:
                    self.show_metadata(metadata)
                    self.status.set(f"Edited and verified metadata in {Path(target_path).name}.")
                    messagebox.showinfo("Success", f"Metadata edited successfully in:\n{target_path}", parent=dlg)
                    dlg.destroy()

            threading.Thread(target=work, daemon=True).start()
            dlg.after(100, completed)

        update_source_button.configure(command=execute_source_update)
        edit_button.configure(command=execute_edit)

    def browse_icon(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose an application icon",
            filetypes=(("JPEG or PNG image", "*.jpg *.jpeg *.png *.dat"),
                       ("All files", "*.*")),
        )
        if selected:
            if not is_supported_image(selected):
                messagebox.showerror(
                    "Invalid Format",
                    "The selected file is not a supported JPEG or PNG image format (missing valid magic bytes).",
                    parent=self.root,
                )
                return
            self.icon.set(selected)

    def auto_populate_metadata(self, source_path: Path) -> None:
        try:
            from nup.discover import discover
            packages = discover(str(source_path), None)
            metadata = dump_application(source_path, [p.src for p in packages])
            self.show_metadata(metadata)
            self.status.set("Dump metadata loaded. Review or replace any item; empty fields are optional.")
        except (Exception, SystemExit) as exc:
            self.status.set(f"Metadata scan failed: {exc}")

    def browse_source(self) -> None:
        if self.mode.get() == "pack":
            options = {
                "parent": self.root,
                "title": "Choose the folder containing base/, updates/, dlc/, or content folders",
                "mustexist": True,
            }
            if self.source.get():
                options["initialdir"] = self.source.get()
            selected = filedialog.askdirectory(**options)
            if not selected:
                return
            self.source.set(selected)
            source = Path(selected)
            if not self.output.get():
                self.output.set(str(source.parent / f"{source.name}.nup"))
            self.auto_populate_metadata(source)
        else:
            selected = filedialog.askopenfilename(
                parent=self.root,
                title="Choose a NUP package",
                filetypes=(("NUP package", "*.nup"), ("All files", "*.*")),
            )
            if not selected:
                return
            self.source.set(selected)
            if not self.output.get():
                source = Path(selected)
                self.output.set(str(source.parent / source.stem))

    def browse_output(self) -> None:
        if self.mode.get() == "pack":
            selected = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save NUP package",
                initialfile=self.output.get() or "",
                defaultextension=".nup",
                filetypes=(("NUP package", "*.nup"), ("All files", "*.*")),
                confirmoverwrite=False,
            )
        else:
            selected = filedialog.askdirectory(
                parent=self.root,
                title="Choose a parent folder for the restored dump",
                mustexist=True,
            )
            if selected:
                stem = Path(self.source.get()).stem if self.source.get() else "restored"
                selected = str(Path(selected) / stem)
        if selected:
            self.output.set(selected)

    def start_operation(self) -> None:
        source_text = self.source.get().strip()
        output_text = self.output.get().strip()
        if not source_text:
            messagebox.showerror("NUP Packager", "Choose an input first.", parent=self.root)
            return
        if not output_text:
            messagebox.showerror("NUP Packager", "Choose an output location.", parent=self.root)
            return
        source, output = Path(source_text), Path(output_text)
        mode = self.mode.get()
        if mode == "pack":
            if not source.is_dir():
                messagebox.showerror("NUP Packager", "Choose an existing dump folder.", parent=self.root)
                return
            if output.exists():
                messagebox.showerror(
                    "NUP Packager", "Choose a new output filename. Existing files are not overwritten.",
                    parent=self.root,
                )
                return
        else:
            if not source.is_file():
                messagebox.showerror("NUP Packager", "Choose an existing .nup file.", parent=self.root)
                return
            if output.exists():
                messagebox.showerror(
                    "NUP Packager", "Choose a new output folder. Existing folders are not overwritten.",
                    parent=self.root,
                )
                return

        self.busy = True
        self.cancel_event = threading.Event()
        self._set_controls_enabled(False)
        self.cancel_button.configure(text="Cancel", state="normal")
        self.cancel_button.grid()
        self.status.set("Scanning dump contents..." if mode == "pack" else "Reading NUP package...")
        self.progress.configure(mode="indeterminate")
        self.progress.grid()
        self.progress.start(12)
        threading.Thread(
            target=self.operation_worker,
            args=(mode, source, output, self.cancel_event,
                  self.icon.get().strip() or None,
                  self.title_name.get().strip() or None,
                  self.display_version.get().strip() or None,
                  self.publisher.get().strip() or None), daemon=True,
        ).start()

    def cancel_operation(self) -> None:
        if self.cancel_event is None or self.cancel_event.is_set():
            return
        self.cancel_event.set()
        self.cancel_button.configure(text="Cancelling...", state="disabled")
        self.status.set("Cancelling at the next safe checkpoint and removing temporary output...")

    def operation_worker(
        self,
        mode: str,
        source: Path,
        output: Path,
        cancel_event: threading.Event,
        icon: str | None,
        title_name: str | None,
        display_version: str | None,
        publisher: str | None,
    ) -> None:
        last_report = 0.0

        def report(done: int, total: int, file_name: str) -> None:
            nonlocal last_report
            now = time.monotonic()
            if now - last_report < 0.1 and done != total:
                return
            last_report = now
            self.events.put(("progress", str(done), str(total), file_name))

        try:
            if mode == "pack":
                def pack_progress(done: int, total: int, file_node: object) -> None:
                    raw_name = getattr(file_node, "name", b"")
                    name = raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
                    report(done, total, name)

                pack_atomic(
                    str(output), str(source), keep_listings=True,
                    icon=icon, name=title_name, display_version=display_version,
                    publisher=publisher,
                    progress=pack_progress, cancel=cancel_event.is_set,
                )
            else:
                unpack_atomic(
                    str(source), str(output), progress=report,
                    cancel=cancel_event.is_set,
                )
        except OperationCancelled:
            self.events.put(("cancelled", "", "", str(output)))
        except (Exception, SystemExit) as exc:
            self.events.put(("error", "", "", f"{type(exc).__name__}: {exc}"))
        else:
            self.events.put(("done", "", "", str(output)))

    def drain_events(self) -> None:
        if self.poll_after_id is not None:
            self.root.after_cancel(self.poll_after_id)
            self.poll_after_id = None
        try:
            while True:
                kind, first, second, detail = self.events.get_nowait()
                if kind == "progress":
                    done, total = int(first), int(second)
                    if self.progress_mode != "determinate":
                        self.progress.stop()
                        self.progress.configure(mode="determinate")
                        self.progress_mode = "determinate"
                    self.progress.configure(maximum=max(1, total), value=done)
                    action = "Packing" if self.mode.get() == "pack" else "Extracting"
                    self.status.set(f"{action} {done} of {total} files: {detail}")
                elif kind == "done":
                    self.finish_operation()
                    action = "Package created" if self.mode.get() == "pack" else "Dump restored"
                    self.status.set(f"{action} successfully.")
                    messagebox.showinfo(action, f"Created:\n{detail}" if self.mode.get() == "pack"
                                        else f"Restored to:\n{detail}", parent=self.root)
                elif kind == "error":
                    self.finish_operation()
                    self.status.set("Operation failed.")
                    messagebox.showerror("NUP operation failed", detail, parent=self.root)
                elif kind == "cancelled":
                    self.finish_operation()
                    self.status.set("Cancelled. Temporary output removed; original files are unchanged.")
        except queue.Empty:
            pass
        try:
            self.poll_after_id = self.root.after(100, self.drain_events)
        except tk.TclError:
            pass

    def finish_operation(self) -> None:
        self.progress.stop()
        self.progress.grid_remove()
        self.progress_mode = "indeterminate"
        self.busy = False
        self.cancel_event = None
        self.cancel_button.configure(text="Cancel", state="disabled")
        self.cancel_button.grid_remove()
        self._set_controls_enabled(True)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for control in (
            self.pack_radio, self.unpack_radio, self.source_entry, self.source_button,
            self.import_nup_button, self.import_dump_button, self.copy_nup_button,
            self.icon_entry, self.icon_button, self.title_entry, self.version_entry,
            self.publisher_entry,
            self.output_entry, self.output_button, self.action_button,
        ):
            control.configure(state=state)
        self.cancel_button.configure(state="disabled" if enabled else "normal")

    def close(self) -> None:
        if self.busy:
            messagebox.showwarning(
                "NUP Packager", "Wait for the current operation to finish before closing.",
                parent=self.root,
            )
            return
        if self.poll_after_id is not None:
            self.root.after_cancel(self.poll_after_id)
            self.poll_after_id = None
        self.metadata_files.cleanup()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    NupPackagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
