from __future__ import annotations

import json
import math
import sys
import threading
import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import customtkinter as ctk

from app.models.calculation import CalculationRecord, TaxResult, TaxSettings
from app.repositories.calculation_repository import CalculationRepository
from app.services.ceir_service import CEIRService
from app.services.export_service import ExportService
from app.services.tax_service import TaxService
from app.utils.constants import APP_NAME, CHECK_TYPES, PAGE_SIZE
from app.utils.currency import format_mmk, format_number_input
from app.utils.validators import parse_app_id_list, parse_imei_list, sanitize_identifier_input, validate_identifier


BLUE = "#2563EB"
BLUE_HOVER = "#1D4ED8"
GREEN = "#059669"
RED = "#DC2626"
AMBER = "#D97706"
TABLE_FONT_SIZE = 13 if sys.platform == "win32" else 11
TABLE_HEADER_FONT_SIZE = 12 if sys.platform == "win32" else 11
TABLE_ROW_HEIGHT = 46 if sys.platform == "win32" else 40
TABLE_HEADER_HEIGHT = 46 if sys.platform == "win32" else 42


def status_glyph(value: object) -> str:
    if value is None:
        return ""
    return "✔" if bool(value) else "✘"


class MainWindow(ctk.CTk):
    def __init__(self, repository: CalculationRepository) -> None:
        super().__init__()
        self.repository = repository
        self.title("Database Check History")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = max(1180, int(screen_width * 0.94))
        window_height = max(720, int(screen_height * 0.90))
        window_width = min(window_width, screen_width)
        window_height = min(window_height, screen_height)
        position_x = max(0, (screen_width - window_width) // 2)
        position_y = max(0, (screen_height - window_height) // 2)
        self.geometry(f"{window_width}x{window_height}+{position_x}+{position_y}")
        self.minsize(1100, 700)
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=("#F8FAFC", "#0B1220"))
        self.content.grid(row=0, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.pages["check"] = CheckView(
            self.content, repository, self.refresh_history, lambda: self.show_page("history"), self.set_theme
        )
        self.pages["calculator"] = CalculatorView(self.content, repository, self.refresh_history)
        self.pages["history"] = HistoryView(self.content, repository, lambda: self.show_page("check"))
        self.pages["settings"] = SettingsView(self.content, repository, self.on_settings_changed)
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self._build_menu()
        self.show_page("check")

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)
        navigate = tk.Menu(menu_bar, tearoff=False)
        navigate.add_command(label="Check IMEI", command=lambda: self.show_page("check"))
        navigate.add_command(label="Tax Calculator", command=lambda: self.show_page("calculator"))
        navigate.add_command(label="Database Check History", command=lambda: self.show_page("history"))
        navigate.add_separator()
        navigate.add_command(label="Settings", command=lambda: self.show_page("settings"))
        menu_bar.add_cascade(label="Functions", menu=navigate)

        records = tk.Menu(menu_bar, tearoff=False)
        records.add_command(label="Delete Selected Record", command=lambda: self.pages["history"].delete_selected())  # type: ignore[attr-defined]
        records.add_command(label="Export Filtered CSV", command=lambda: self.pages["history"].export())  # type: ignore[attr-defined]
        records.add_separator()
        records.add_command(label="Clear History", command=lambda: self.pages["history"].clear())  # type: ignore[attr-defined]
        menu_bar.add_cascade(label="Records", menu=records)

        view = tk.Menu(menu_bar, tearoff=False)
        view.add_command(label="Toggle Light / Dark Mode", command=self.toggle_theme)
        menu_bar.add_cascade(label="View", menu=view)
        self.configure(menu=menu_bar)

    def show_page(self, name: str) -> None:
        self.pages[name].tkraise()
        titles = {
            "check": "Check IMEI",
            "calculator": "CEIR Mobile Tax Calculator",
            "history": "Database Check History",
            "settings": "Tax Settings",
        }
        self.title(titles[name])
        if name == "history":
            self.refresh_history()
        if name == "settings":
            self.pages[name].load()  # type: ignore[attr-defined]

    def refresh_history(self) -> None:
        history = self.pages.get("history")
        if history:
            history.refresh()  # type: ignore[attr-defined]

    def show_check_results(self) -> None:
        """Open the screenshot-style table after CEIR check results are saved."""
        history = self.pages.get("history")
        if history:
            history.type_filter.set("ALL")  # type: ignore[attr-defined]
            history.search.delete(0, "end")  # type: ignore[attr-defined]
            history.page = 1  # type: ignore[attr-defined]
        self.show_page("history")

    def on_settings_changed(self) -> None:
        calculator = self.pages.get("calculator")
        if calculator:
            calculator.clear_result()  # type: ignore[attr-defined]

    def toggle_theme(self) -> None:
        current = ctk.get_appearance_mode()
        self.set_theme("Light" if current == "Dark" else "Dark")

    def set_theme(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        check = self.pages.get("check")
        if check and hasattr(check, "theme_switch"):
            check.theme_switch.set(mode)  # type: ignore[attr-defined]
        self.pages["history"].apply_table_style()  # type: ignore[attr-defined]


class Page(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, title: str, subtitle: str = "") -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=27, weight="bold"))
        self.title_label.grid(row=0, column=0, padx=30, pady=(26, 2), sticky="w")
        self.subtitle_label: ctk.CTkLabel | None = None
        if subtitle:
            self.subtitle_label = ctk.CTkLabel(self, text=subtitle, text_color=("#64748B", "#94A3B8"))
            self.subtitle_label.grid(row=1, column=0, padx=30, sticky="w")


class ThemeToggle(ctk.CTkFrame):
    """Two-button theme control with distinct selected text colors."""

    def __init__(self, master: ctk.CTkFrame, command: Callable[[str], None]) -> None:
        super().__init__(
            master, width=168, height=34, corner_radius=10,
            fg_color=("#DDE4EE", "#263449"),
        )
        self.command = command
        self.pack_propagate(False)
        self.light_button = ctk.CTkButton(
            self, text="☀ Light", width=81, height=28, corner_radius=8,
            font=ctk.CTkFont(size=11, weight="bold"), command=lambda: self.choose("Light"),
        )
        self.light_button.pack(side="left", padx=(3, 1), pady=3)
        self.dark_button = ctk.CTkButton(
            self, text="☾ Dark", width=81, height=28, corner_radius=8,
            font=ctk.CTkFont(size=11, weight="bold"), command=lambda: self.choose("Dark"),
        )
        self.dark_button.pack(side="left", padx=(1, 3), pady=3)
        self.set("Light")

    def choose(self, mode: str) -> None:
        self.set(mode)
        self.command(mode)

    def set(self, mode: str) -> None:
        selected = {
            "fg_color": BLUE, "hover_color": BLUE_HOVER, "text_color": "#FFFFFF",
        }
        unselected = {
            "fg_color": ("#F3F6FA", "#334155"),
            "hover_color": ("#E6ECF3", "#475569"),
            "text_color": ("#334155", "#E2E8F0"),
        }
        self.light_button.configure(**(selected if mode == "Light" else unselected))
        self.dark_button.configure(**(selected if mode == "Dark" else unselected))


class CheckView(Page):
    def __init__(
        self,
        master: ctk.CTkFrame,
        repository: CalculationRepository,
        on_saved: Callable[[], None],
        on_history: Callable[[], None],
        on_theme: Callable[[str], None],
    ) -> None:
        super().__init__(master, "Check IMEI", "Enter multiple 15-digit IMEIs separated by commas or new lines.")
        self.title_label.grid_remove()
        if self.subtitle_label:
            self.subtitle_label.grid_remove()
        self.repository = repository
        self.on_saved = on_saved
        self.on_history = on_history
        self.on_theme = on_theme
        self.failed_identifiers: list[str] = []
        self.current_input_mode = "IMEI CHECK"
        self.input_cache = {"IMEI CHECK": "", "APP ID CHECK": ""}
        self.live_results: list[tuple[tuple[object, ...], tuple[str, ...]]] = []
        self.result_page = 1
        self.result_page_size = 100
        self.service = CEIRService()
        self.grid_rowconfigure(0, weight=1)
        body = ctk.CTkFrame(self)
        body.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        body.grid_columnconfigure(0, weight=5)
        body.grid_columnconfigure(1, weight=6)
        body.grid_rowconfigure(0, weight=1)
        input_panel = ctk.CTkFrame(
            body, corner_radius=14, fg_color=("#FFFFFF", "#111C2E"),
            border_width=1, border_color=("#D8DEE8", "#2A3950"),
        )
        input_panel.grid(row=0, column=0, rowspan=3, padx=(16, 8), pady=16, sticky="nsew")
        input_panel.grid_columnconfigure((0, 1, 2), weight=1)
        input_panel.grid_rowconfigure(4, weight=1)
        self.mode_tabs = ctk.CTkSegmentedButton(
            input_panel, values=["IMEI CHECK", "APP ID CHECK"], height=38,
            selected_color=BLUE, selected_hover_color=BLUE_HOVER,
            command=self._change_input_mode,
        )
        self.mode_tabs.grid(row=0, column=0, columnspan=3, padx=22, pady=(20, 10), sticky="ew")
        self.mode_tabs.set("IMEI CHECK")
        self.input_kind_label = ctk.CTkLabel(
            input_panel, text="IMEI INPUT", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=BLUE,
        )
        self.input_kind_label.grid(row=1, column=0, padx=22, pady=(2, 1), sticky="w")
        self.imei_count_label = ctk.CTkLabel(
            input_panel, text="0 IMEIs ready", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#64748B", "#94A3B8"), corner_radius=12,
            fg_color=("#EEF2F7", "#1E293B"), padx=10, pady=3,
        )
        self.imei_count_label.grid(row=1, column=1, columnspan=2, padx=22, pady=(2, 1), sticky="e")
        self.input_heading = ctk.CTkLabel(
            input_panel, text="Paste one or multiple IMEI numbers",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.input_heading.grid(row=2, column=0, columnspan=3, padx=22, pady=(2, 2), sticky="w")
        self.input_help = ctk.CTkLabel(
            input_panel, text="Separate each 15-digit IMEI with a comma or a new line.",
            text_color=("#64748B", "#94A3B8"),
        )
        self.input_help.grid(row=3, column=0, columnspan=3, padx=22, pady=(0, 12), sticky="w")
        self.imei = ctk.CTkTextbox(
            input_panel, height=300, corner_radius=10, border_width=1,
            border_color=("#CBD2DC", "#3A4A62"), fg_color=("#FFFFFF", "#0F1929"),
            text_color=("#1F2937", "#E5E7EB"), font=ctk.CTkFont(size=15),
            border_spacing=12, wrap="word", undo=True, maxundo=100,
        )
        self.imei.grid(row=4, column=0, columnspan=3, padx=22, pady=(0, 14), sticky="nsew")
        self.imei.bind("<KeyRelease>", self._update_input_count)
        self.imei.bind("<FocusIn>", self._on_input_focus_in)
        self.imei.bind("<FocusOut>", self._on_input_focus_out)
        self.check_button = ctk.CTkButton(
            input_panel, text="Check IMEIs", height=52, corner_radius=10,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=BLUE, hover_color=BLUE_HOVER, command=self.start_check,
        )
        self.check_button.grid(row=5, column=0, columnspan=3, padx=22, pady=(0, 12), sticky="ew")
        input_actions = ctk.CTkFrame(input_panel, fg_color="transparent")
        input_actions.grid(row=6, column=0, columnspan=3, padx=22, pady=(0, 20), sticky="ew")
        input_actions.grid_columnconfigure((0, 1, 2, 3), weight=1)
        ctk.CTkButton(
            input_actions, text="Import File", height=38,
            fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"),
            hover_color=("#D8E2F0", "#475569"), command=self.import_imei_file,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            input_actions, text="Clear", height=38,
            fg_color=("#FDECEC", "#48252A"), text_color=("#B42318", "#FDA29B"),
            hover_color=("#FBD5D5", "#633038"), command=self.clear_input,
        ).grid(row=0, column=1, padx=4, sticky="ew")
        self.retry_button = ctk.CTkButton(
            input_actions, text="Retry Failed", height=38, state="disabled",
            fg_color=AMBER, hover_color="#B45309", command=self.retry_failed,
        )
        self.retry_button.grid(row=0, column=2, padx=4, sticky="ew")
        self.history_button = ctk.CTkButton(
            input_actions, text="View History", height=38,
            fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"),
            hover_color=("#D8E2F0", "#475569"), command=self.on_history,
        )
        self.history_button.grid(row=0, column=3, padx=(4, 0), sticky="ew")
        result = ctk.CTkFrame(body, fg_color=("#F1F5F9", "#111C2E"))
        result.grid(row=0, column=1, rowspan=3, padx=(8, 16), pady=16, sticky="nsew")
        result_header = ctk.CTkFrame(result, fg_color="transparent")
        result_header.pack(fill="x", padx=24, pady=(20, 12))
        ctk.CTkLabel(result_header, text="Check Result", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.theme_switch = ThemeToggle(result_header, self._change_theme)
        self.theme_switch.pack(side="right")
        self.theme_switch.set(ctk.get_appearance_mode())
        self.result_status = ctk.CTkLabel(result, text="Ready to check", font=ctk.CTkFont(size=17, weight="bold"), text_color=("#64748B", "#94A3B8"))
        self.result_status.pack(anchor="w", padx=24, pady=5)
        result_table_frame = ctk.CTkFrame(result, fg_color="transparent")
        result_table_frame.pack(fill="both", expand=True, padx=14, pady=10)
        result_table_frame.grid_columnconfigure(0, weight=1)
        result_table_frame.grid_rowconfigure(0, weight=1)
        result_columns = ("imei", "device", "taxation", "network", "base", "tax")
        self.results_tree = ttk.Treeview(result_table_frame, columns=result_columns, show="headings", height=10)
        for column, label, width in zip(result_columns, ("IMEI", "Brand / Model", "Taxation", "Network", "Base Price", "Tax Price"), (145, 190, 85, 85, 105, 105)):
            self.results_tree.heading(column, text=label)
            self.results_tree.column(column, width=width, minwidth=70, anchor="e" if column in {"base", "tax"} else "center")
        result_scroll = ttk.Scrollbar(result_table_frame, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=result_scroll.set)
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        self.results_tree.bind("<Configure>", self._resize_result_page)
        result_scroll.grid(row=0, column=1, sticky="ns")
        self.results_tree.tag_configure("good", foreground=GREEN)
        self.results_tree.tag_configure("bad", foreground=RED)
        result_footer = ctk.CTkFrame(result, fg_color="transparent")
        result_footer.pack(fill="x", padx=14, pady=(0, 4))
        result_footer.grid_columnconfigure(1, weight=1)
        self.result_prev = ctk.CTkButton(
            result_footer, text="‹ Prev", width=72, height=30, fg_color="transparent",
            text_color=("#475569", "#CBD5E1"), hover_color=("#E8EEF7", "#263449"),
            command=lambda: self._change_result_page(-1),
        )
        self.result_prev.grid(row=0, column=0, sticky="w")
        self.result_page_label = ctk.CTkLabel(
            result_footer, text="Page 1 of 1 (Total Records: 0)",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.result_page_label.grid(row=0, column=1)
        self.result_next = ctk.CTkButton(
            result_footer, text="Next ›", width=72, height=30, fg_color="transparent",
            text_color=("#475569", "#CBD5E1"), hover_color=("#E8EEF7", "#263449"),
            command=lambda: self._change_result_page(1),
        )
        self.result_next.grid(row=0, column=2, sticky="e")
        self.note = ctk.CTkLabel(result, text="Brand and Model are loaded automatically from the CEIR Device Info API.", wraplength=420, justify="left", text_color=("#64748B", "#94A3B8"))
        self.note.pack(anchor="w", padx=24, pady=(20, 10))
        self._render_result_page()

    def _change_theme(self, mode: str) -> None:
        self.on_theme(mode)

    def _change_input_mode(self, mode: str) -> None:
        self.input_cache[self.current_input_mode] = self.imei.get("1.0", "end").strip()
        self.current_input_mode = mode
        self.imei.delete("1.0", "end")
        cached = self.input_cache.get(mode, "")
        if cached:
            self.imei.insert("1.0", cached)
        is_imei = mode == "IMEI CHECK"
        self.input_kind_label.configure(text="IMEI INPUT" if is_imei else "APPLICATION ID INPUT")
        self.input_heading.configure(text="Paste one or multiple IMEI numbers" if is_imei else "Paste one or multiple Application IDs")
        self.input_help.configure(
            text="Separate each 15-digit IMEI with a comma or a new line."
            if is_imei else "Example: MM-CR-DEMO123. Separate multiple IDs with a comma or a new line."
        )
        self.check_button.configure(text="Check IMEIs" if is_imei else "Check App IDs")
        self.results_tree.heading("imei", text="IMEI" if is_imei else "App ID")
        self.failed_identifiers = []
        self.retry_button.configure(text="Retry Failed", state="disabled")
        self._set_results()
        self.result_status.configure(text="Ready to check", text_color=("#64748B", "#94A3B8"))
        self.note.configure(
            text="Brand and Model are loaded automatically from the CEIR Device Info API."
            if is_imei else "Registration status and official tax amounts are loaded from the CEIR App ID API.",
            text_color=("#64748B", "#94A3B8"),
        )
        self._update_input_count()

    def _sanitize_input_box(self, _event: object = None) -> None:
        content = self.imei.get("1.0", "end-1c")
        sanitized = sanitize_identifier_input(content)
        if sanitized != content:
            self.imei.delete("1.0", "end")
            self.imei.insert("1.0", sanitized)
            self.imei.mark_set("insert", "end-1c")
        self._update_input_count()

    def _on_input_focus_in(self, _event: object = None) -> None:
        self.imei.configure(border_color=BLUE, border_width=2)

    def _on_input_focus_out(self, _event: object = None) -> None:
        self._sanitize_input_box()
        self.imei.configure(border_color=("#CBD2DC", "#3A4A62"), border_width=1)

    def _update_input_count(self, _event: object = None) -> None:
        candidates = self.imei.get("1.0", "end").replace(",", " ").split()
        if self.current_input_mode == "IMEI CHECK":
            is_valid = lambda value: value.isdigit() and len(value) == 15
            noun = "IMEI"
        else:
            is_valid = lambda value: bool(value) and all(character.isalnum() or character == "-" for character in value)
            noun = "App ID"
        valid = {value for value in candidates if is_valid(value)}
        invalid_count = sum(1 for value in candidates if not is_valid(value))
        if invalid_count:
            self.imei_count_label.configure(
                text=f"{len(valid)} ready • {invalid_count} invalid",
                text_color=AMBER, fg_color=("#FFF4E5", "#422F18"),
            )
        elif valid:
            self.imei_count_label.configure(
                text=f"{len(valid)} {noun}{'s' if len(valid) != 1 else ''} ready",
                text_color=GREEN, fg_color=("#E8F7F0", "#17392D"),
            )
        else:
            self.imei_count_label.configure(
                text=f"0 {noun}s ready", text_color=("#64748B", "#94A3B8"),
                fg_color=("#EEF2F7", "#1E293B"),
            )

    def import_imei_file(self) -> None:
        noun = "IMEI" if self.current_input_mode == "IMEI CHECK" else "App ID"
        path = filedialog.askopenfilename(
            parent=self,
            title=f"Import {noun} File",
            filetypes=[("Text or CSV", "*.txt *.csv"), ("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                content = sanitize_identifier_input(handle.read().strip())
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Import failed", f"Could not read the {noun} file:\n{exc}", parent=self)
            return
        if not content:
            messagebox.showwarning("Empty file", f"The selected file does not contain any {noun}s.", parent=self)
            return
        existing = self.imei.get("1.0", "end").strip()
        if existing:
            self.imei.insert("end", f"\n{content}")
        else:
            self.imei.insert("1.0", content)
        self._update_input_count()
        try:
            count = len(self._parse_identifiers())
            self.note.configure(
                text=f"Imported successfully. {count} unique {noun}(s) ready to check.",
                text_color=("#64748B", "#94A3B8"),
            )
        except ValueError as exc:
            self.note.configure(text=f"File imported, but some values need correction: {exc}", text_color=AMBER)

    def clear_input(self) -> None:
        self.imei.delete("1.0", "end")
        self.input_cache[self.current_input_mode] = ""
        self._update_input_count()
        self.failed_identifiers = []
        self.retry_button.configure(text="Retry Failed", state="disabled")
        self._set_results()
        self.result_status.configure(text="Ready to check", text_color=("#64748B", "#94A3B8"))
        self.note.configure(
            text="Brand and Model are loaded automatically from the CEIR Device Info API."
            if self.current_input_mode == "IMEI CHECK"
            else "Registration status and official tax amounts are loaded from the CEIR App ID API.",
            text_color=("#64748B", "#94A3B8"),
        )

    def retry_failed(self) -> None:
        if not self.failed_identifiers:
            return
        retry_values = list(self.failed_identifiers)
        self.imei.delete("1.0", "end")
        self.imei.insert("1.0", ", ".join(retry_values))
        self._update_input_count()
        self.start_check()

    def _parse_identifiers(self) -> list[str]:
        content = self.imei.get("1.0", "end")
        return parse_imei_list(content) if self.current_input_mode == "IMEI CHECK" else parse_app_id_list(content)

    def _check_button_label(self) -> str:
        return "Check IMEIs" if self.current_input_mode == "IMEI CHECK" else "Check App IDs"

    def start_check(self) -> None:
        self._sanitize_input_box()
        try:
            identifiers = self._parse_identifiers()
        except ValueError as exc:
            messagebox.showwarning("Invalid input", str(exc), parent=self)
            return
        self.failed_identifiers = []
        self.retry_button.configure(text="Retry Failed", state="disabled")
        self.check_button.configure(state="disabled", text=f"Checking 0/{len(identifiers)}…")
        self.mode_tabs.configure(state="disabled")
        self.result_status.configure(text="Solving verification challenge…", text_color=AMBER)
        self._set_results("")
        target = self._worker if self.current_input_mode == "IMEI CHECK" else self._app_id_worker
        threading.Thread(target=target, args=(identifiers,), daemon=True).start()

    def _worker(self, imeis: list[str]) -> None:
        completed = 0
        succeeded = 0
        errors: list[str] = []
        # CEIR accepts only one IMEI per verification request. Process the list
        # sequentially so one rejected IMEI does not prevent the others running.
        for imei in imeis:
            try:
                result = self.service.check_imei(imei)
                device_info = None
                device_error = ""
                try:
                    device_info = self.service.get_device_info(imei)
                except Exception as exc:
                    device_error = str(exc)
                resolved_brand = device_info.brand if device_info else ""
                resolved_model = device_info.model if device_info else ""
                details = {"verification": result.raw}
                if device_info:
                    details["device_info"] = device_info.raw
                if device_error:
                    details["device_info_error"] = device_error
                self.repository.add(CalculationRecord(
                    check_type="SINGLE CHECK" if len(imeis) == 1 else "BATCH CHECK", imei_or_app_id=imei,
                    brand=resolved_brand, model=resolved_model,
                    taxation_status=result.taxation_status, network_status=result.network_status,
                    check_message=json.dumps(details, ensure_ascii=False),
                ))
                succeeded += 1
                self.after(0, self._append_result, imei, resolved_brand, resolved_model, result.payment_state, result.block_state, None, None, result.network_status)
            except Exception as exc:
                errors.append(f"{imei}: {exc}")
            completed += 1
            self.after(0, self.check_button.configure, {"text": f"Checking {completed}/{len(imeis)}…"})
        self.after(0, self._finish_batch, succeeded, len(imeis), errors)

    def _app_id_worker(self, app_ids: list[str]) -> None:
        succeeded = 0
        errors: list[str] = []
        for completed, app_id in enumerate(app_ids, start=1):
            try:
                status = self.service.get_registration_status(app_id)
                self.repository.add(CalculationRecord(
                    check_type="APP ID CHECK", imei_or_app_id=status.declaration_id,
                    brand=status.brand, model=status.model,
                    base_price=status.base_price, customs_duty=status.customs_duty,
                    commercial_tax=status.commercial_tax, redemption_fee=status.redemption_fee,
                    income_tax=0, total_tax=status.total_tax,
                    taxation_status=status.taxation_status, network_status=None,
                    check_message=json.dumps(status.raw, ensure_ascii=False),
                ))
                succeeded += 1
                self.after(
                    0, self._append_result, status.declaration_id, status.brand, status.model,
                    status.business_state, "", status.base_price, status.total_tax, status.taxation_status,
                )
            except Exception as exc:
                errors.append(f"{app_id}: {exc}")
            self.after(0, self.check_button.configure, {"text": f"Checking {completed}/{len(app_ids)}…"})
        self.after(0, self._finish_batch, succeeded, len(app_ids), errors)

    def _set_results(self, _text: str = "") -> None:
        self.live_results = []
        self.result_page = 1
        self._render_result_page()

    def _render_result_page(self) -> None:
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        total = len(self.live_results)
        total_pages = max(1, math.ceil(total / self.result_page_size))
        self.result_page = max(1, min(self.result_page, total_pages))
        start = (self.result_page - 1) * self.result_page_size
        for values, tags in self.live_results[start:start + self.result_page_size]:
            self.results_tree.insert("", "end", values=values, tags=tags)
        self.result_page_label.configure(
            text=f"Page {self.result_page} of {total_pages} (Total Records: {total})"
        )
        self.result_prev.configure(state="normal" if self.result_page > 1 else "disabled")
        self.result_next.configure(state="normal" if self.result_page < total_pages else "disabled")

    def _change_result_page(self, amount: int) -> None:
        self.result_page += amount
        self._render_result_page()

    def _resize_result_page(self, event: tk.Event) -> None:
        # Use platform-aware header/row sizes so Windows DPI scaling paginates correctly.
        # Use the available height rather than an arbitrary fixed record count.
        available_rows = max(1, (int(event.height) - TABLE_HEADER_HEIGHT) // TABLE_ROW_HEIGHT)
        if available_rows == self.result_page_size:
            return
        self.result_page_size = available_rows
        self.result_page = max(1, math.ceil(len(self.live_results) / self.result_page_size))
        self._render_result_page()

    def _append_result(self, identifier: str, brand: str, model: str, payment: str, block: str, base_price: int | None, total_tax: int | None, is_good: bool | None) -> None:
        values = (
            identifier, " ".join(part for part in (brand, model) if part), payment, block,
            format_mmk(base_price), format_mmk(total_tax),
        )
        tags = ("good",) if is_good else ("bad",) if is_good is False else ()
        self.live_results.append((values, tags))
        self.result_page = max(1, math.ceil(len(self.live_results) / self.result_page_size))
        self._render_result_page()

    def _append_error(self, error: str) -> None:
        parts = error.split(":", 1)
        values = (parts[0], "", "ERROR", parts[1].strip() if len(parts) > 1 else error, "", "")
        self.live_results.append((values, ("bad",)))
        self.result_page = max(1, math.ceil(len(self.live_results) / self.result_page_size))
        self._render_result_page()

    def _show_error(self, detail: str) -> None:
        self.check_button.configure(state="normal", text=self._check_button_label())
        self.mode_tabs.configure(state="normal")
        self.result_status.configure(text="Check failed", text_color=RED)
        self.note.configure(text=detail)

    def _finish_batch(self, succeeded: int, total: int, errors: list[str]) -> None:
        self.check_button.configure(state="normal", text=self._check_button_label())
        self.mode_tabs.configure(state="normal")
        failed = total - succeeded
        self.result_status.configure(
            text=f"Complete: {succeeded} succeeded, {failed} failed",
            text_color=GREEN if failed == 0 else AMBER,
        )
        if errors:
            for error in errors:
                self._append_error(error)
            self.failed_identifiers = [error.split(":", 1)[0] for error in errors]
            self.retry_button.configure(text=f"Retry Failed ({len(self.failed_identifiers)})", state="normal")
        else:
            self.failed_identifiers = []
            self.retry_button.configure(text="Retry Failed", state="disabled")
        self.note.configure(text="Successful CEIR results were saved separately to History.")
        if succeeded:
            self.on_saved()


class CalculatorView(Page):
    def __init__(self, master: ctk.CTkFrame, repository: CalculationRepository, on_saved: Callable[[], None]) -> None:
        super().__init__(master, "Tax Calculator", "Calculate Myanmar CEIR customs tax with exact half-up MMK rounding.")
        self.repository = repository
        self.on_saved = on_saved
        self.current_result: TaxResult | None = None
        self.grid_rowconfigure(2, weight=1)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, padx=24, pady=18, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1)
        form = ctk.CTkFrame(body)
        form.grid(row=0, column=0, padx=6, pady=6, sticky="nsew")
        result_frame = ctk.CTkFrame(body)
        result_frame.grid(row=0, column=1, padx=6, pady=6, sticky="nsew")
        self.entries: dict[str, ctk.CTkEntry] = {}
        for row, (key, label, placeholder) in enumerate((
            ("brand", "Brand (optional)", "e.g. Samsung"), ("model", "Model (optional)", "e.g. Galaxy S25"),
            ("identifier", "IMEI / Application ID", "Identifier (optional for manual)"), ("price", "Base Price (MMK)", "e.g. 1,995,000"),
        )):
            ctk.CTkLabel(form, text=label, font=ctk.CTkFont(weight="bold")).grid(row=row * 2, column=0, padx=22, pady=(18 if row == 0 else 8, 5), sticky="w")
            entry = ctk.CTkEntry(form, height=40, placeholder_text=placeholder)
            entry.grid(row=row * 2 + 1, column=0, padx=22, sticky="ew")
            self.entries[key] = entry
        self.entries["price"].bind("<KeyRelease>", self._format_price)
        ctk.CTkLabel(form, text="Check Type", font=ctk.CTkFont(weight="bold")).grid(row=8, column=0, padx=22, pady=(8, 5), sticky="w")
        self.check_type = ctk.CTkOptionMenu(form, values=list(CHECK_TYPES), height=40, command=lambda _value: self._auto_calculate())
        self.check_type.set("APP ID CHECK")
        self.check_type.grid(row=9, column=0, padx=22, sticky="ew")
        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.grid(row=10, column=0, padx=22, pady=22, sticky="ew")
        actions.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(actions, text="Calculate", fg_color=BLUE, hover_color=BLUE_HOVER, command=self.calculate).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(actions, text="Reset", fg_color=("#64748B", "#475569"), command=self.reset).grid(row=0, column=1, padx=(5, 0), sticky="ew")
        ctk.CTkLabel(result_frame, text="Calculation Result", font=ctk.CTkFont(size=19, weight="bold")).pack(anchor="w", padx=24, pady=(24, 14))
        self.result_labels: dict[str, ctk.CTkLabel] = {}
        for key, label in (("base", "Base Price"), ("customs", "Customs Duty"), ("commercial", "Commercial Tax"), ("redemption", "Redemption Fee"), ("income", "Income Tax"), ("total", "Total Tax"), ("rate", "Effective Tax Rate"), ("grand", "Grand Total")):
            row_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=24, pady=5)
            ctk.CTkLabel(row_frame, text=label).pack(side="left")
            value = ctk.CTkLabel(row_frame, text="—", font=ctk.CTkFont(weight="bold"))
            value.pack(side="right")
            self.result_labels[key] = value
        result_actions = ctk.CTkFrame(result_frame, fg_color="transparent")
        result_actions.pack(fill="x", padx=24, pady=22)
        ctk.CTkButton(result_actions, text="Copy Result", fg_color=("#64748B", "#475569"), command=self.copy_result).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(result_actions, text="Save Calculation", fg_color=GREEN, command=self.save).pack(side="left", expand=True, fill="x", padx=(5, 0))

    def _format_price(self, _event: object = None) -> None:
        entry = self.entries["price"]
        formatted = format_number_input(entry.get())
        if entry.get() != formatted:
            entry.delete(0, "end")
            entry.insert(0, formatted)
        self._auto_calculate()

    def _display_result(self, result: TaxResult) -> None:
        self.current_result = result
        values = {
            "base": format_mmk(result.base_price), "customs": format_mmk(result.customs_duty),
            "commercial": format_mmk(result.commercial_tax), "redemption": format_mmk(result.redemption_fee),
            "income": format_mmk(result.income_tax), "total": format_mmk(result.total_tax),
            "rate": f"{result.effective_rate}%", "grand": format_mmk(result.grand_total),
        }
        for key, value in values.items():
            color = BLUE if key in {"total", "grand"} else ("#1F2937", "#E5E7EB")
            self.result_labels[key].configure(text=value, text_color=color)

    def _auto_calculate(self) -> None:
        """Refresh the result silently while the user edits the base price."""
        price = self.entries["price"].get()
        if not price:
            self.clear_result()
            return
        try:
            result = TaxService.calculate(price, self.repository.get_settings())
        except ValueError:
            self.clear_result()
            return
        self._display_result(result)

    def calculate(self) -> None:
        try:
            identifier = validate_identifier(self.entries["identifier"].get(), self.check_type.get())
            result = TaxService.calculate(self.entries["price"].get(), self.repository.get_settings())
        except ValueError as exc:
            messagebox.showwarning("Invalid input", str(exc), parent=self)
            return
        self._display_result(result)
        self.entries["identifier"].delete(0, "end")
        self.entries["identifier"].insert(0, identifier)

    def clear_result(self) -> None:
        self.current_result = None
        for label in self.result_labels.values():
            label.configure(text="—", text_color=("#1F2937", "#E5E7EB"))

    def reset(self) -> None:
        for entry in self.entries.values():
            entry.delete(0, "end")
        self.check_type.set("APP ID CHECK")
        self.clear_result()

    def result_text(self) -> str:
        if not self.current_result:
            return ""
        return "\n".join(f"{key.replace('_', ' ').title()}: {label.cget('text')}" for key, label in self.result_labels.items())

    def copy_result(self) -> None:
        if not self.current_result:
            messagebox.showinfo("No result", "Calculate tax first.", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(self.result_text())

    def save(self) -> None:
        if not self.current_result:
            messagebox.showinfo("No result", "Calculate tax first.", parent=self)
            return
        try:
            identifier = validate_identifier(self.entries["identifier"].get(), self.check_type.get())
            result = TaxService.calculate(self.entries["price"].get(), self.repository.get_settings())
        except ValueError as exc:
            messagebox.showwarning("Invalid input", str(exc), parent=self)
            return
        self._display_result(result)
        record_id = self.repository.add(CalculationRecord(
            check_type=self.check_type.get(), imei_or_app_id=identifier,
            brand=self.entries["brand"].get().strip(), model=self.entries["model"].get().strip(),
            base_price=result.base_price, customs_duty=result.customs_duty, commercial_tax=result.commercial_tax,
            redemption_fee=result.redemption_fee, income_tax=result.income_tax, total_tax=result.total_tax,
        ))
        self.on_saved()
        messagebox.showinfo("Saved", f"Calculation #{record_id} was saved to History.", parent=self)


class HistoryGrid(tk.Frame):
    """A bordered, cell-colored table tailored to the History screenshot."""

    HEADINGS = ("", "ID", "Date Time", "Type", "IMEI / App ID", "Brand / Model", "Taxation", "Network", "Base Price", "Tax Price")
    MIN_WIDTHS = (34, 50, 150, 140, 165, 205, 82, 78, 115, 115)
    TYPE_COLORS = {
        "APP ID CHECK": "#2563EB",
        "SINGLE CHECK": "#059669",
        "BATCH CHECK": "#D97706",
        "MANUAL CALCULATION": "#64748B",
    }

    def __init__(self, master: tk.Misc, on_double_click: Callable[[], None]) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.on_double_click = on_double_click
        self.selected_record_id: int | None = None
        self.row_widgets: dict[int, list[tk.Label]] = {}
        self.current_rows: list[dict] = []
        self.current_page = 1
        self.dark = False
        for column, width in enumerate(self.MIN_WIDTHS):
            self.grid_columnconfigure(column, weight=1 if column in {2, 4, 5, 8, 9} else 0, minsize=width)
        self.grid_rowconfigure(13, weight=1)

    def configure_theme(self, dark: bool) -> None:
        self.dark = dark
        self.render(self.current_rows, self.current_page)

    def render(self, rows: list[dict], page: int) -> None:
        self.current_rows = rows
        self.current_page = page
        self.selected_record_id = None
        self.row_widgets.clear()
        for widget in self.winfo_children():
            widget.destroy()
        background = "#111C2E" if self.dark else "#FFFFFF"
        header_background = "#17243A" if self.dark else "#F0F1F3"
        header_foreground = "#E2E8F0" if self.dark else "#4B5563"
        border = "#344258" if self.dark else "#D4D7DC"
        self.configure(bg=background)
        for column, heading in enumerate(self.HEADINGS):
            header = tk.Label(
                self, text=heading, bg=header_background, fg=header_foreground,
                font=("Segoe UI", TABLE_HEADER_FONT_SIZE, "bold"), padx=7, pady=10,
                highlightbackground=border, highlightcolor=border, highlightthickness=1, bd=0,
            )
            header.grid(row=0, column=column, sticky="nsew")
        for index, record in enumerate(rows):
            self._render_row(index + 1, record, border)

    def _render_row(self, grid_row: int, record: dict, border: str) -> None:
        row_background = ("#152238" if grid_row % 2 == 0 else "#111C2E") if self.dark else ("#F5F5F5" if grid_row % 2 == 0 else "#FFFFFF")
        normal_foreground = "#E5E7EB" if self.dark else "#374151"
        taxation = record["taxation_status"]
        network = record["network_status"]
        values = (
            (self.current_page - 1) * PAGE_SIZE + grid_row,
            record["id"], record["date_time"], record["check_type"], record["imei_or_app_id"] or "",
            " ".join(part for part in (record["brand"], record["model"]) if part),
            status_glyph(taxation), status_glyph(network),
            format_mmk(record["base_price"]), format_mmk(record["total_tax"]),
        )
        widgets: list[tk.Label] = []
        for column, value in enumerate(values):
            foreground = normal_foreground
            if column == 3:
                foreground = self.TYPE_COLORS.get(str(value), normal_foreground)
            elif column == 6 and taxation is not None:
                foreground = GREEN if taxation else RED
            elif column == 7 and network is not None:
                foreground = GREEN if network else RED
            anchor = "e" if column in {8, 9} else "center"
            cell = tk.Label(
                self, text=value, bg=row_background, fg=foreground, anchor=anchor,
                font=("Segoe UI", TABLE_FONT_SIZE, "bold" if column in {3, 6, 7} else "normal"),
                padx=7, pady=8, highlightbackground=border, highlightcolor=border,
                highlightthickness=1, bd=0,
            )
            cell.grid(row=grid_row, column=column, sticky="nsew")
            cell.bind("<Button-1>", lambda _event, record_id=record["id"]: self.select(record_id))
            cell.bind("<Double-1>", lambda _event, record_id=record["id"]: self._open(record_id))
            widgets.append(cell)
        self.row_widgets[int(record["id"])] = widgets

    def select(self, record_id: int) -> None:
        self.selected_record_id = int(record_id)
        for current_id, widgets in self.row_widgets.items():
            grid_row = int(widgets[0].grid_info()["row"])
            normal = ("#152238" if grid_row % 2 == 0 else "#111C2E") if self.dark else ("#F5F5F5" if grid_row % 2 == 0 else "#FFFFFF")
            background = "#1E4C7A" if self.dark and current_id == record_id else "#DBEAFE" if current_id == record_id else normal
            for widget in widgets:
                widget.configure(bg=background)

    def _open(self, record_id: int) -> None:
        self.select(record_id)
        self.on_double_click()


class HistoryView(Page):
    COLUMNS = ("row_number", "id", "date", "type", "identifier", "device", "taxation", "network", "base", "tax")

    def __init__(self, master: ctk.CTkFrame, repository: CalculationRepository, on_back: Callable[[], None]) -> None:
        super().__init__(master, "Database Check History")
        self.title_label.grid_remove()
        self.repository = repository
        self.on_back = on_back
        self.page = 1
        self.total = 0
        toolbar = ctk.CTkFrame(self, corner_radius=8, fg_color=("#FFFFFF", "#111C2E"), border_width=1, border_color=("#D8DEE8", "#263449"))
        toolbar.grid(row=2, column=0, padx=8, pady=(10, 5), sticky="ew")
        toolbar.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(toolbar, text="← Back", width=82, height=40, fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"), hover_color=("#D8E2F0", "#475569"), command=self.on_back).grid(row=0, column=0, padx=(12, 6), pady=10)
        ctk.CTkLabel(toolbar, text="🔍  Search:", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=1, padx=(4, 8), pady=12)
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Filter by IMEI, Brand, Model, Date, Hash…", height=40, font=ctk.CTkFont(size=13))
        self.search.grid(row=0, column=2, padx=(0, 14), pady=10, sticky="ew")
        self.search.bind("<KeyRelease>", lambda _event: self.reset_page())
        ctk.CTkLabel(toolbar, text="🏷  Type:", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=3, padx=(0, 7), pady=12)
        self.type_filter = ctk.CTkOptionMenu(toolbar, values=["ALL", *CHECK_TYPES], width=205, height=40, command=lambda _value: self.reset_page())
        self.type_filter.grid(row=0, column=4, padx=(0, 10), pady=10)
        ctk.CTkButton(toolbar, text="⬇  Export CSV", width=125, height=40, fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"), hover_color=("#D8E2F0", "#475569"), command=self.export).grid(row=0, column=5, padx=4, pady=10)
        ctk.CTkButton(toolbar, text="🗑  Clear History", width=135, height=40, fg_color=RED, hover_color="#B91C1C", command=self.clear).grid(row=0, column=6, padx=(4, 14), pady=10)
        table_frame = ctk.CTkFrame(self, corner_radius=5, border_width=1, border_color=("#D1D7E0", "#263449"))
        table_frame.grid(row=3, column=0, padx=8, pady=3, sticky="nsew")
        self.grid_rowconfigure(3, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)
        self.table = HistoryGrid(table_frame, self.open_detail)
        self.table.grid(row=0, column=0, sticky="nsew")
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, padx=8, pady=(5, 8), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)
        self.prev = ctk.CTkButton(footer, text="◂ Prev", width=100, height=36, fg_color="transparent", text_color=("#334155", "#CBD5E1"), command=lambda: self.change_page(-1))
        self.prev.grid(row=0, column=0)
        self.page_label = ctk.CTkLabel(footer, text="Page 1 of 1 (Total Records: 0)", font=ctk.CTkFont(size=14, weight="bold"))
        self.page_label.grid(row=0, column=1)
        self.next = ctk.CTkButton(footer, text="Next ▸", width=100, height=36, fg_color="transparent", text_color=("#334155", "#CBD5E1"), command=lambda: self.change_page(1))
        self.next.grid(row=0, column=2)
        self.apply_table_style()

    def apply_table_style(self) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background="#111C2E" if dark else "#FFFFFF", fieldbackground="#111C2E" if dark else "#FFFFFF", foreground="#E5E7EB" if dark else "#334155", rowheight=TABLE_ROW_HEIGHT, borderwidth=0, font=("Segoe UI", TABLE_FONT_SIZE))
        style.map("Treeview", background=[("selected", BLUE)], foreground=[("selected", "#FFFFFF")])
        style.configure("Treeview.Heading", background="#17243A" if dark else "#EEF2F7", foreground="#CBD5E1" if dark else "#334155", relief="flat", padding=11, font=("Segoe UI", TABLE_HEADER_FONT_SIZE, "bold"))
        self.table.configure_theme(dark)

    def reset_page(self) -> None:
        self.page = 1
        self.refresh()

    def refresh(self) -> None:
        rows, self.total = self.repository.list_filtered(self.search.get(), self.type_filter.get(), self.page, PAGE_SIZE)
        self.table.render(rows, self.page)
        pages = max(1, math.ceil(self.total / PAGE_SIZE))
        if self.page > pages:
            self.page = pages
            self.refresh()
            return
        self.page_label.configure(text=f"Page {self.page} of {pages} (Total Records: {self.total})")
        self.prev.configure(state="normal" if self.page > 1 else "disabled")
        self.next.configure(state="normal" if self.page < pages else "disabled")

    def change_page(self, amount: int) -> None:
        self.page += amount
        self.refresh()

    def selected_id(self) -> int | None:
        return self.table.selected_record_id

    def delete_selected(self) -> None:
        record_id = self.selected_id()
        if record_id is None:
            messagebox.showinfo("Delete record", "Select a record first.", parent=self)
            return
        if messagebox.askyesno("Delete record", f"Delete record #{record_id}?", parent=self):
            self.repository.delete(record_id)
            self.refresh()

    def clear(self) -> None:
        if self.total and messagebox.askyesno("Clear History", "Permanently delete every history record?", icon="warning", parent=self):
            self.repository.clear()
            self.reset_page()

    def export(self) -> None:
        rows = self.repository.all_filtered(self.search.get(), self.type_filter.get())
        if not rows:
            messagebox.showinfo("Export CSV", "There are no filtered records to export.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export filtered history", defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if path:
            try:
                ExportService.export_history(rows, path)
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc), parent=self)

    def open_detail(self, _event: object = None) -> None:
        record_id = self.selected_id()
        if record_id is None:
            return
        record = self.repository.get(record_id)
        if not record:
            return
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Calculation #{record_id}")
        dialog.geometry("570x610")
        dialog.transient(self.winfo_toplevel())
        box = ctk.CTkTextbox(dialog, wrap="word", font=("Segoe UI", 13))
        box.pack(fill="both", expand=True, padx=18, pady=18)
        labels = {
            "id": "ID", "date_time": "Date Time", "check_type": "Type", "imei_or_app_id": "IMEI / App ID",
            "brand": "Brand", "model": "Model", "base_price": "Base Price", "customs_duty": "Customs Duty",
            "commercial_tax": "Commercial Tax", "redemption_fee": "Redemption Fee", "income_tax": "Income Tax",
            "total_tax": "Total Tax", "taxation_status": "Taxation", "network_status": "Network", "check_message": "CEIR Details",
        }
        money = {"base_price", "customs_duty", "commercial_tax", "redemption_fee", "income_tax", "total_tax"}
        for key, label in labels.items():
            value = record.get(key)
            if key in money:
                value = format_mmk(value)
            elif key in {"taxation_status", "network_status"}:
                value = "Not applicable" if value is None else ("Passed" if value else "Failed")
            box.insert("end", f"{label}\n{value or '—'}\n\n")
        box.configure(state="disabled")


class SettingsView(Page):
    def __init__(self, master: ctk.CTkFrame, repository: CalculationRepository, on_changed: Callable[[], None]) -> None:
        super().__init__(master, "Tax Settings", "Adjust percentage rates used for new calculations.")
        self.repository = repository
        self.on_changed = on_changed
        panel = ctk.CTkFrame(self)
        panel.grid(row=2, column=0, padx=30, pady=24, sticky="new")
        panel.grid_columnconfigure(1, weight=1)
        self.variables: dict[str, tk.StringVar] = {}
        rows = (("customs_duty_rate", "Customs Duty %"), ("commercial_tax_rate", "Commercial Tax %"), ("redemption_fee_rate", "Redemption Fee %"), ("income_tax_rate", "Income Tax %"))
        for row, (key, label) in enumerate(rows):
            ctk.CTkLabel(panel, text=label, font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, padx=24, pady=14, sticky="w")
            variable = tk.StringVar()
            self.variables[key] = variable
            ctk.CTkEntry(panel, textvariable=variable, height=38).grid(row=row, column=1, padx=24, pady=8, sticky="ew")
        self.income_enabled = tk.BooleanVar()
        ctk.CTkSwitch(panel, text="Enable Income Tax", variable=self.income_enabled).grid(row=4, column=0, columnspan=2, padx=24, pady=14, sticky="w")
        actions = ctk.CTkFrame(panel, fg_color="transparent")
        actions.grid(row=5, column=0, columnspan=2, padx=24, pady=20, sticky="ew")
        ctk.CTkButton(actions, text="Save Settings", fg_color=BLUE, command=self.save).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(actions, text="Reset all to defaults", fg_color=("#64748B", "#475569"), command=self.reset).pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.load()

    def load(self) -> None:
        settings = self.repository.get_settings()
        for key, variable in self.variables.items():
            variable.set(str(getattr(settings, key)))
        self.income_enabled.set(settings.income_tax_enabled)

    def _values(self) -> TaxSettings:
        try:
            decimals = {key: Decimal(variable.get().strip()) for key, variable in self.variables.items()}
        except InvalidOperation as exc:
            raise ValueError("All rates must be valid numbers.") from exc
        if any(value < 0 or value > 100 for value in decimals.values()):
            raise ValueError("Each percentage must be between 0 and 100.")
        return TaxSettings(**decimals, income_tax_enabled=self.income_enabled.get())

    def save(self) -> None:
        try:
            self.repository.save_settings(self._values())
        except ValueError as exc:
            messagebox.showwarning("Invalid settings", str(exc), parent=self)
            return
        self.on_changed()
        messagebox.showinfo("Settings", "Tax settings were saved.", parent=self)

    def reset(self) -> None:
        self.repository.reset_settings()
        self.load()
        self.on_changed()
