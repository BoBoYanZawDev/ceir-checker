from __future__ import annotations

import calendar
import csv
import json
import math
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import customtkinter as ctk

from app.models.calculation import ApplicantProfile, CalculationRecord, TaxResult, TaxSettings
from app.repositories.calculation_repository import CalculationRepository
from app.services.ceir_service import CEIRService, RegistrationTaxQuote
from app.services.export_service import ExportService
from app.services.tax_service import TaxService
from app.utils.constants import APP_NAME, CHECK_TYPES, PAGE_SIZE
from app.utils.currency import format_mmk, format_number_input
from app.utils.validators import (
    build_nrc,
    normalize_birthday,
    parse_app_id_list,
    parse_imei_list,
    parse_nrc,
    sanitize_identifier_input,
    validate_identifier,
)


BLUE = "#2F67E8"
BLUE_HOVER = "#2558D4"
GREEN = "#059669"
RED = "#DC2626"
AMBER = "#D97706"
# Keep the desktop UI comfortably readable on both Retina macOS displays and
# Windows DPI configurations.  CustomTkinter scales its own fonts and widget
# geometry with this value; native Tk table/list widgets are sized separately.
UI_WIDGET_SCALE = 1.18
TABLE_FONT_SIZE = 16
TABLE_HEADER_FONT_SIZE = 15
TABLE_ROW_HEIGHT = 54
TABLE_HEADER_HEIGHT = 52
NATIVE_TEXT_FONT_SIZE = 15


def application_icon_path() -> Path | None:
    """Locate app_icon.png in source checkouts and PyInstaller bundles."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(bundle_root) / "app_icon.png" if bundle_root else None,
        project_root / "app_icon.png",
        project_root.parent / "app_icon.png",
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def status_glyph(value: object) -> str:
    if value is None:
        return ""
    return "✔" if bool(value) else "✘"


def format_ceir_datetime(value: str) -> str:
    """Trim a CEIR ISO timestamp down to 'YYYY-MM-DD HH:MM:SS' for display."""
    if not value:
        return ""
    text = value.replace("T", " ").rstrip("Z")
    return text.split(".", 1)[0]


def is_payable_unpaid(payment_state: object, taxation_status: object) -> bool:
    """Exclude transport/check failures while accepting CEIR pending tax states."""
    state = str(payment_state or "").upper()
    return taxation_status is False and not any(
        marker in state for marker in ("FAIL", "ERROR", "UNKNOWN", "INVALID")
    )


def registration_history_metadata(record: dict) -> tuple[list[str], str, str]:
    """Recover registration IMEIs and device names from saved CEIR details."""
    if record.get("check_type") != "REGISTRATION REQUEST":
        return [], str(record.get("brand") or ""), str(record.get("model") or "")
    try:
        details = json.loads(str(record.get("check_message") or "{}"))
    except (json.JSONDecodeError, TypeError):
        details = {}
    if not isinstance(details, dict):
        details = {}

    imeis: list[str] = []

    def add_imeis(value: object) -> None:
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, list):
                add_imeis(candidate)
            elif candidate and str(candidate) not in imeis:
                imeis.append(str(candidate))

    add_imeis(details.get("imeis") or details.get("imei"))
    response = details.get("response") or details
    registry = response.get("Registry") if isinstance(response, dict) else None
    if not isinstance(registry, dict):
        registry = response if isinstance(response, dict) else {}
    devices = registry.get("devices") or registry.get("Devices") or []
    if isinstance(devices, dict):
        devices = [devices]
    brands: list[str] = []
    models: list[str] = []
    if isinstance(devices, list):
        for device in devices:
            if not isinstance(device, dict):
                continue
            add_imeis(device.get("imeis") or device.get("IMEIs") or device.get("imei"))
            brand = str(device.get("brand") or device.get("Brand") or "")
            model = str(device.get("model") or device.get("Model") or "")
            if brand and brand not in brands:
                brands.append(brand)
            if model and model not in models:
                models.append(model)
    device_info = details.get("device_info") or []
    if isinstance(device_info, dict):
        device_info = [device_info]
    if isinstance(device_info, list):
        for device in device_info:
            if not isinstance(device, dict):
                continue
            brand = str(device.get("gsmaBrandName") or "")
            model = str(device.get("gsmaModelName") or "")
            if brand and brand not in brands:
                brands.append(brand)
            if model and model not in models:
                models.append(model)
    return (
        imeis,
        str(record.get("brand") or " / ".join(brands)),
        str(record.get("model") or " / ".join(models)),
    )


class EditableDatePicker(ctk.CTkFrame):
    """An editable date entry with a small, dependency-free calendar popup."""

    def __init__(self, master: tk.Misc, variable: tk.StringVar) -> None:
        super().__init__(master, fg_color="transparent")
        self.variable = variable
        self.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(
            self, textvariable=variable, placeholder_text="DD-MM-YYYY", height=38,
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            self, text="▦", width=42, height=38, corner_radius=8,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=BLUE, hover_color=BLUE_HOVER, command=self._open_calendar,
        ).grid(row=0, column=1, padx=(6, 0))
        self._popup: ctk.CTkToplevel | None = None
        self._display_year = date.today().year
        self._display_month = date.today().month

    def _open_calendar(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.lift()
            return
        try:
            selected = datetime.strptime(normalize_birthday(self.variable.get()), "%Y-%m-%d").date()
        except ValueError:
            selected = date.today()
        self._display_year, self._display_month = selected.year, selected.month
        popup = ctk.CTkToplevel(self)
        self._popup = popup
        popup.title("Choose birthday")
        popup.geometry("330x330")
        popup.resizable(False, False)
        popup.transient(self.winfo_toplevel())
        popup.protocol("WM_DELETE_WINDOW", self._close_calendar)
        popup.grid_columnconfigure(0, weight=1)
        self._calendar_body = ctk.CTkFrame(popup, fg_color="transparent")
        self._calendar_body.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        self._draw_calendar()
        popup.after(50, popup.grab_set)

    def _close_calendar(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.grab_release()
            self._popup.destroy()
        self._popup = None

    def _change_month(self, amount: int) -> None:
        month_index = self._display_year * 12 + self._display_month - 1 + amount
        self._display_year, zero_based_month = divmod(month_index, 12)
        self._display_month = zero_based_month + 1
        self._draw_calendar()

    def _choose_month(self, month_name: str) -> None:
        try:
            self._display_month = list(calendar.month_name).index(month_name)
        except ValueError:
            return
        self._draw_calendar()

    def _choose_year(self, year_text: str) -> None:
        try:
            self._display_year = int(year_text)
        except ValueError:
            return
        self._draw_calendar()

    def _draw_calendar(self) -> None:
        for child in self._calendar_body.winfo_children():
            child.destroy()
        for column in range(7):
            self._calendar_body.grid_columnconfigure(column, weight=1)
        ctk.CTkButton(
            self._calendar_body, text="‹", width=34, height=30,
            fg_color="transparent", text_color=("#334155", "#E2E8F0"),
            hover_color=("#E2E8F0", "#334155"), command=lambda: self._change_month(-1),
        ).grid(row=0, column=0)
        month_variable = tk.StringVar(value=calendar.month_name[self._display_month])
        month_picker = SearchableDropdown(
            self._calendar_body, variable=month_variable,
            values=list(calendar.month_name)[1:], command=self._choose_month,
            width=132, height=32,
        )
        month_picker.grid(row=0, column=1, columnspan=3, padx=3, pady=(0, 8), sticky="ew")
        current_year = date.today().year
        first_year = max(current_year, self._display_year)
        last_year = min(1900, self._display_year)
        year_variable = tk.StringVar(value=str(self._display_year))
        year_picker = SearchableDropdown(
            self._calendar_body, variable=year_variable,
            values=[str(year) for year in range(first_year, last_year - 1, -1)],
            command=self._choose_year, width=92, height=32,
        )
        year_picker.grid(row=0, column=4, columnspan=2, padx=3, pady=(0, 8), sticky="ew")
        ctk.CTkButton(
            self._calendar_body, text="›", width=34, height=30,
            fg_color="transparent", text_color=("#334155", "#E2E8F0"),
            hover_color=("#E2E8F0", "#334155"), command=lambda: self._change_month(1),
        ).grid(row=0, column=6)
        for column, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            ctk.CTkLabel(
                self._calendar_body, text=name, text_color=("#64748B", "#94A3B8"),
                font=ctk.CTkFont(size=11, weight="bold"),
            ).grid(row=1, column=column, pady=(0, 5))
        today = date.today()
        for week_index, week in enumerate(calendar.monthcalendar(self._display_year, self._display_month), start=2):
            for column, day_number in enumerate(week):
                if not day_number:
                    continue
                is_today = (
                    self._display_year == today.year
                    and self._display_month == today.month
                    and day_number == today.day
                )
                ctk.CTkButton(
                    self._calendar_body, text=str(day_number), width=36, height=32, corner_radius=7,
                    fg_color=BLUE if is_today else "transparent",
                    text_color="#FFFFFF" if is_today else ("#334155", "#E2E8F0"),
                    hover_color=BLUE_HOVER,
                    command=lambda day=day_number: self._select_day(day),
                ).grid(row=week_index, column=column, padx=1, pady=1)

    def _select_day(self, day_number: int) -> None:
        selected = date(self._display_year, self._display_month, day_number)
        self.variable.set(selected.strftime("%d-%m-%Y"))
        self._close_calendar()


class SearchableDropdown(ctk.CTkFrame):
    """Theme-aware dropdown that filters its API values as the user types."""

    def __init__(
        self, master: tk.Misc, *, variable: tk.StringVar, values: list[str],
        command: Callable[[str], None] | None = None, width: int = 140, height: int = 38,
        state: str = "normal", **style: object,
    ) -> None:
        self._field_fg = style.get("fg_color", ("#FFFFFF", "#1E293B"))
        self._border_idle = ("#CBD5E1", "#475569")
        self._border_focus = (BLUE, "#60A5FA")
        super().__init__(
            master, fg_color=self._field_fg, border_width=1, border_color=self._border_idle,
            corner_radius=6, width=width, height=height,
        )
        self.grid_propagate(False)
        self.variable = variable
        self._values = list(values)
        self._filtered_values = list(values)
        self._command = command
        self._popup: tk.Frame | None = None
        self._listbox: tk.Listbox | None = None
        self._outside_bind_id: str | None = None
        self._owner_window: tk.Misc | None = None
        self._dropdown_fg = style.get("dropdown_fg_color", ("#FFFFFF", "#1E293B"))
        self._dropdown_text = style.get("dropdown_text_color", ("#1E3A5F", "#F8FAFC"))
        self._dropdown_hover = style.get("dropdown_hover_color", ("#DCE8FA", "#334155"))
        self.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(
            self, textvariable=variable, width=max(42, width - 42),
            height=max(30, height - 4), border_width=0, corner_radius=5,
            fg_color=self._field_fg,
            text_color=style.get("text_color", ("#1E3A5F", "#F8FAFC")),
        )
        self.entry.grid(row=0, column=0, padx=(3, 0), pady=2, sticky="ew")
        self.button = ctk.CTkButton(
            self, text="⌕", font=ctk.CTkFont(size=14, weight="bold"),
            width=34, height=max(28, height - 6), corner_radius=5,
            fg_color="transparent", hover_color=("#EEF4FF", "#334155"),
            text_color=("#94A3B8", "#CBD5E1"),
            command=self.toggle,
        )
        self.button.grid(row=0, column=1, padx=(0, 3), pady=3)
        self.entry.bind("<KeyRelease>", self._on_search)
        self.entry.bind("<Button-1>", self._select_entry_text)
        self.entry.bind("<FocusIn>", self._on_focus)
        self.entry.bind("<Down>", self._focus_list)
        self.entry.bind("<Return>", self._choose_first)
        self.entry.bind("<Escape>", lambda _event: self.close())
        self.set_state(state)

    @staticmethod
    def _theme_color(value: object) -> str:
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            return str(value[1] if ctk.get_appearance_mode() == "Dark" else value[0])
        return str(value)

    def set_values(self, values: list[str], state: str | None = None) -> None:
        self._values = list(values)
        self._filtered_values = list(values)
        if state is not None:
            self.set_state(state)
        if self._popup is not None:
            self._render_values()

    def set_command(self, command: Callable[[str], None]) -> None:
        self._command = command

    def set_state(self, state: str) -> None:
        self.entry.configure(state=state)
        self.button.configure(state=state)
        if state == "disabled":
            self.close()

    def toggle(self) -> None:
        if self._popup is not None:
            self.close()
        else:
            self._filtered_values = list(self._values)
            self.open()

    def open(self) -> None:
        if self._popup is not None or str(self.entry.cget("state")) == "disabled":
            return
        self.update_idletasks()
        owner = self.winfo_toplevel()
        background = self._theme_color(self._dropdown_fg)
        owner_width = max(owner.winfo_width(), 240)
        width = min(max(self.winfo_width(), 220), owner_width - 16)
        row_count = max(1, min(10, len(self._filtered_values)))
        x = self.winfo_rootx() - owner.winfo_rootx()
        x = min(max(8, x), max(8, owner_width - width - 8))
        y = self.winfo_rooty() - owner.winfo_rooty() + self.winfo_height() + 2
        available_height = max(80, owner.winfo_height() - y - 16)
        popup_height = min(row_count * 32 + 8, available_height, 328)
        frame = tk.Frame(
            owner, bg=background, highlightthickness=1,
            highlightbackground=self._theme_color(("#D1D5DB", "#475569")),
        )
        self._popup = frame
        frame.place(x=x, y=y, width=width, height=popup_height)
        frame.lift()
        scrollbar = tk.Scrollbar(frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self._listbox = tk.Listbox(
            frame, borderwidth=0, highlightthickness=0, activestyle="none",
            bg=background, fg=self._theme_color(self._dropdown_text),
            selectbackground=self._theme_color(self._dropdown_hover),
            selectforeground=self._theme_color(self._dropdown_text),
            exportselection=False, font=("Segoe UI", NATIVE_TEXT_FONT_SIZE), yscrollcommand=scrollbar.set,
        )
        self._listbox.pack(side="left", fill="both", expand=True, padx=3, pady=3)
        scrollbar.configure(command=self._listbox.yview)
        self._listbox.bind("<ButtonRelease-1>", self._choose_listbox)
        self._listbox.bind("<Return>", self._choose_listbox)
        self._listbox.bind("<Escape>", lambda _event: self.close())
        self._render_values()
        self.entry.focus_set()
        self._owner_window = owner
        self._outside_bind_id = self._owner_window.bind("<Button-1>", self._close_outside, add="+")

    def close(self) -> None:
        if self._popup is not None:
            self._popup.destroy()
        self._popup = None
        self._listbox = None
        if self._owner_window is not None and self._outside_bind_id is not None:
            self._owner_window.unbind("<Button-1>", self._outside_bind_id)
        self._owner_window = None
        self._outside_bind_id = None
        self.configure(border_color=self._border_idle)

    def _close_outside(self, event: tk.Event) -> None:
        widget: tk.Misc | None = event.widget
        while widget is not None:
            if widget is self or widget is self._popup:
                return
            widget = getattr(widget, "master", None)
        self.close()

    def _render_values(self) -> None:
        if self._listbox is None:
            return
        self._listbox.delete(0, "end")
        for value in self._filtered_values:
            self._listbox.insert("end", value)
        if not self._filtered_values:
            self._listbox.insert("end", "No matching results")
            return
        selected = self.variable.get()
        if selected in self._filtered_values:
            index = self._filtered_values.index(selected)
            self._listbox.selection_set(index)
            self._listbox.activate(index)
            self._listbox.see(index)

    def _on_search(self, event: tk.Event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape", "Tab"}:
            return
        query = self.variable.get().strip().casefold()
        self._filtered_values = [value for value in self._values if query in value.casefold()]
        if self._popup is None:
            self.open()
        else:
            self._render_values()

    def _select_entry_text(self, _event: tk.Event) -> None:
        self.after_idle(lambda: self.entry.select_range(0, "end"))

    def _on_focus(self, _event: tk.Event) -> None:
        self.configure(border_color=self._border_focus)
        if self._popup is None:
            self._filtered_values = list(self._values)
            self.open()

    def _focus_list(self, _event: tk.Event) -> str:
        if self._popup is None:
            self.open()
        if self._listbox is not None and self._filtered_values:
            self._listbox.focus_set()
            self._listbox.selection_set(0)
        return "break"

    def _choose_first(self, _event: tk.Event) -> str:
        if self._filtered_values:
            self._select(self._filtered_values[0])
        return "break"

    def _choose_listbox(self, _event: tk.Event) -> None:
        if self._listbox is None or not self._filtered_values:
            return
        selection = self._listbox.curselection()
        if selection:
            self._select(self._filtered_values[selection[0]])

    def _select(self, value: str) -> None:
        self.variable.set(value)
        self._filtered_values = list(self._values)
        self.close()
        if self._command is not None:
            self._command(value)


class MainWindow(ctk.CTk):
    def __init__(self, repository: CalculationRepository) -> None:
        # This is deliberately larger than ceir_tax_calculator.  Applying it
        # before constructing the root keeps fonts, buttons and inputs in sync.
        ctk.set_widget_scaling(UI_WIDGET_SCALE)
        super().__init__()
        self._app_icon_image: tk.PhotoImage | None = None
        icon_path = application_icon_path()
        if icon_path is not None:
            try:
                self._app_icon_image = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, self._app_icon_image)
            except tk.TclError:
                # A broken/unsupported icon must never prevent the app opening.
                self._app_icon_image = None
        self.repository = repository
        self.title(APP_NAME)
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
        ctk.ThemeManager.theme["CTkButton"]["corner_radius"] = 9
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color=("#F8FAFC", "#0B1220"))
        self.content.grid(row=0, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.pages["check"] = CheckView(
            self.content, repository, self.refresh_history, lambda: self.show_page("history"),
            lambda: self.show_page("settings"), self.set_theme,
        )
        self.pages["calculator"] = CalculatorView(self.content, repository, self.refresh_history)
        self.pages["history"] = HistoryView(self.content, repository, lambda: self.show_page("check"))
        self.pages["settings"] = SettingsView(
            self.content, repository, self.on_settings_changed, lambda: self.show_page("check")
        )
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
        self._build_menu()
        self.show_page("check")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        check_view = self.pages.get("check")
        if check_view is not None:
            check_view.service.close()  # type: ignore[attr-defined]
        self.destroy()

    def _build_menu(self) -> None:
        menu_bar = tk.Menu(self)
        navigate = tk.Menu(menu_bar, tearoff=False)
        navigate.add_command(label="Check IMEI", command=lambda: self.show_page("check"))
        navigate.add_command(label="Tax Calculator", command=lambda: self.show_page("calculator"))
        navigate.add_command(label="Database Check History", command=lambda: self.show_page("history"))
        navigate.add_separator()
        navigate.add_command(label="Reload CEIR Session", command=lambda: self.pages["check"].reload_session())  # type: ignore[attr-defined]
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
            "check": f"{APP_NAME} — CEIR Workflows",
            "calculator": f"{APP_NAME} — Local Tax Calculator",
            "history": f"{APP_NAME} — Database Check History",
            "settings": f"{APP_NAME} — Settings",
        }
        self.title(titles[name])
        if name == "history":
            self.refresh_history()
        if name == "settings":
            self.pages[name].load()  # type: ignore[attr-defined]
            self.pages[name].load_applicant()  # type: ignore[attr-defined]

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
            check.apply_table_style()  # type: ignore[attr-defined]
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


class TopbarActionButton(ctk.CTkFrame):
    """Compact top-bar action with independently sized, font-rendered icon."""

    def __init__(
        self,
        master: tk.Misc,
        symbol: str,
        text: str,
        command: Callable[[], None],
        width: int,
    ) -> None:
        self._normal_color = ("#EEF1F5", "#263449")
        self._hover_color = ("#E1E6EC", "#334155")
        button_cursor = (
            "pointinghand" if sys.platform == "darwin"
            else "hand2" if sys.platform.startswith("win")
            else "arrow"
        )
        super().__init__(
            master, width=width, height=28, corner_radius=8,
            fg_color=self._normal_color, cursor=button_cursor,
        )
        self.command = command
        self.pack_propagate(False)
        content = ctk.CTkFrame(self, fg_color="transparent", cursor=button_cursor)
        content.place(relx=0.5, rely=0.5, anchor="center")
        icon = ctk.CTkLabel(
            content, text=symbol, width=14, height=18,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(BLUE, "#8FB0FF"), cursor=button_cursor,
        )
        # Symbol glyphs sit lower than normal text on both Segoe UI and the
        # macOS system font; bottom padding optically centers the icon.
        icon.pack(side="left", padx=(0, 2), pady=(0, 2))
        label = ctk.CTkLabel(
            content, text=text, height=18,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#374151", "#E5E7EB"), cursor=button_cursor,
        )
        label.pack(side="left", pady=(0, 2))
        for widget in (self, content, icon, label):
            widget.bind("<Button-1>", self._invoke)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _invoke(self, _event: tk.Event) -> None:
        self.command()

    def _enter(self, _event: tk.Event) -> None:
        self.configure(fg_color=self._hover_color)

    def _leave(self, event: tk.Event) -> None:
        x, y = self.winfo_pointerxy()
        if not (self.winfo_rootx() <= x <= self.winfo_rootx() + self.winfo_width()
                and self.winfo_rooty() <= y <= self.winfo_rooty() + self.winfo_height()):
            self.configure(fg_color=self._normal_color)


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
            self, text="☀ Light",
            width=81, height=28, corner_radius=8,
            font=ctk.CTkFont(size=11, weight="bold"), command=lambda: self.choose("Light"),
        )
        self.light_button.pack(side="left", padx=(3, 1), pady=3)
        self.dark_button = ctk.CTkButton(
            self, text="☾ Dark",
            width=81, height=28, corner_radius=8,
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


class LiveResultsGrid(tk.Frame):
    """Reference-style result area with a view for each workflow tab."""

    MIN_WIDTHS = (80, 130, 150, 80, 90, 90, 80)

    def __init__(self, master: tk.Misc, on_pay_tax: Callable[[str], None] | None = None) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.on_pay_tax = on_pay_tax
        self.mode = "IMEI CHECK"
        self.headings = ("IMEI", "Brand / Model", "Taxation", "Network", "Base Price", "Tax Price", "Allocation Date")
        self.dark = False
        self.current_rows: list[dict] = []
        for column, width in enumerate(self.MIN_WIDTHS):
            self.grid_columnconfigure(column, weight=1 if column in {1, 4, 5, 6} else 0, minsize=width)
        self.render([])

    def configure_theme(self, dark: bool) -> None:
        self.dark = dark
        self.render(self.current_rows)

    def set_identifier_label(self, text: str) -> None:
        self.headings = (text, *self.headings[1:])
        self.render(self.current_rows)

    def set_extra_column_label(self, text: str) -> None:
        self.headings = (*self.headings[:-1], text)
        self.render(self.current_rows)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.render(self.current_rows)

    def _palette(self) -> tuple[str, str, str, str]:
        return (
            "#111C2E" if self.dark else "#FFFFFF",
            "#E5E7EB" if self.dark else "#374151",
            "#94A3B8" if self.dark else "#6B7280",
            "#344258" if self.dark else "#D4D7DC",
        )

    def _label(
        self, row: int, column: int, text: object, *, columnspan: int = 1,
        anchor: str = "w", bold: bool = False, color: str | None = None,
        padx: int = 8, pady: int = 7,
    ) -> tk.Label:
        background, foreground, _muted, border = self._palette()
        label = tk.Label(
            self, text=str(text or ""), bg=background, fg=color or foreground, anchor=anchor,
            font=("Segoe UI", TABLE_FONT_SIZE, "bold" if bold else "normal"),
            padx=padx, pady=pady, highlightbackground=border, highlightcolor=border,
            highlightthickness=0, bd=0, justify="left", wraplength=260 if columnspan > 1 else 0,
        )
        label.grid(row=row, column=column, columnspan=columnspan, sticky="nsew")
        return label

    def _section(self, row: int, title: str, columns: int = 8) -> int:
        _background, foreground, _muted, border = self._palette()
        label = self._label(row, 0, title, columnspan=columns, bold=True, pady=10)
        label.configure(font=("Segoe UI", TABLE_HEADER_FONT_SIZE + 1, "bold"), highlightthickness=0)
        separator = tk.Frame(self, height=1, bg=border)
        separator.grid(row=row + 1, column=0, columnspan=columns, sticky="ew")
        return row + 2

    def _pay_tax_button(self, row: int, imei: str, column: int, columnspan: int = 1) -> None:
        if self.on_pay_tax is None or not imei:
            return
        action = tk.Label(
            self, text="Pay Tax  →", bg=BLUE, fg="#FFFFFF", relief="flat", bd=0,
            cursor="hand2", takefocus=True, font=("Segoe UI", TABLE_FONT_SIZE, "bold"),
            padx=12, pady=5,
        )
        action.grid(
            row=row, column=column, columnspan=columnspan,
            padx=8, pady=4, sticky="e",
        )
        action.bind("<Button-1>", lambda _event: self.on_pay_tax(imei))
        action.bind("<Return>", lambda _event: self.on_pay_tax(imei))
        action.bind("<Enter>", lambda _event: action.configure(bg=BLUE_HOVER))
        action.bind("<Leave>", lambda _event: action.configure(bg=BLUE))

    def _field_pair(self, row: int, left: tuple[str, object], right: tuple[str, object] | None = None) -> int:
        _background, foreground, muted, border = self._palette()
        pairs = [left, right]
        for offset, pair in enumerate(pairs):
            if pair is None:
                continue
            label, value = pair
            start = offset * 4
            self._label(row, start, label, color=muted, padx=8, pady=7)
            value_color = foreground
            value_upper = str(value).upper()
            if value_upper in {"PAID", "UNBLOCKED", "ALLOWED", "VALID", "VALID FORMAT"}:
                value_color = GREEN
            elif value_upper in {"UNPAID", "BLOCKED", "ERROR", "FAILED", "INVALID"}:
                value_color = RED
            self._label(row, start + 1, value, columnspan=3, bold=value_upper in {"PAID", "UNPAID"}, color=value_color)
        separator = tk.Frame(self, height=1, bg=border)
        separator.grid(row=row + 1, column=0, columnspan=8, sticky="ew")
        return row + 2

    def _draw_header(self) -> None:
        header_background = "#17243A" if self.dark else "#F0F1F3"
        header_foreground = "#E2E8F0" if self.dark else "#4B5563"
        border = "#344258" if self.dark else "#D4D7DC"
        for column, heading in enumerate(self.headings):
            header = tk.Label(
                self, text=heading, bg=header_background, fg=header_foreground,
                font=("Segoe UI", TABLE_HEADER_FONT_SIZE, "bold"), padx=7, pady=10,
                highlightbackground=border, highlightcolor=border, highlightthickness=1, bd=0,
            )
            header.grid(row=0, column=column, sticky="nsew")

    def render(self, rows: list[dict]) -> None:
        self.current_rows = rows
        for widget in self.winfo_children():
            widget.destroy()
        background = "#111C2E" if self.dark else "#FFFFFF"
        self.configure(bg=background)
        for column in range(8):
            self.grid_columnconfigure(column, weight=1, minsize=80)
        if self.mode == "BATCH CHECK" or (self.mode == "IMEI CHECK" and len(rows) > 1):
            self._render_batch(rows)
        elif self.mode in {"APP ID CHECK", "PAYTAX"}:
            self._render_application(rows)
        else:
            self._render_single(rows)

    def _render_single(self, rows: list[dict]) -> None:
        row = self._section(0, "Device Status")
        item = rows[0] if rows else {}
        details = item.get("details") or {}
        device = details.get("device_info") or {}
        verification = details.get("verification") or {}
        row = self._field_pair(row, ("IMEI Number", item.get("identifier", "")))
        row = self._field_pair(row, ("Format", "Valid Format" if item else ""))
        row = self._field_pair(row, ("Network", item.get("network_text", "")))
        taxation_row = row
        row = self._field_pair(row, ("Taxation", item.get("taxation_text", "")))
        if is_payable_unpaid(item.get("taxation_text"), item.get("taxation_good")):
            self._pay_tax_button(taxation_row, str(item.get("identifier") or ""), 5, 2)
        row = self._field_pair(row, ("End Of Grace Period", verification.get("endOfGracePeriod") or verification.get("gracePeriodEnd") or ""))
        row = self._section(row + 1, "Hardware Specs")
        row = self._field_pair(row, ("Brand", device.get("gsmaBrandName") or ""), ("Model", device.get("gsmaModelName") or item.get("device", "")))
        row = self._field_pair(row, ("Marketing Name", device.get("marketingName") or device.get("gsmaModelName") or ""), ("Device Type", device.get("gsmaDeviceType") or ""))
        self._field_pair(row, ("Base Price", item.get("base_text", "")))

    def _render_batch(self, rows: list[dict]) -> None:
        background, foreground, muted, border = self._palette()
        paid = sum(1 for item in rows if item.get("taxation_good") is True)
        unpaid = sum(1 for item in rows if item.get("taxation_good") is False)
        cards = tk.Frame(self, bg=background, bd=0, highlightthickness=0)
        cards.grid(row=0, column=0, columnspan=8, padx=4, pady=(4, 14), sticky="ew")
        for column in range(3):
            cards.grid_columnconfigure(column, weight=1, uniform="summary_cards")
        card_specs = (
            ("TOTAL RECORDS", len(rows), foreground, "#F8FAFC", "#1E293B"),
            ("TAX PAID ✓", paid, GREEN, "#ECFDF5", "#12392C"),
            ("TAX UNPAID/ERROR ✕", unpaid, RED, "#FEF2F2", "#442326"),
        )
        for column, (title, value, color, light_bg, dark_bg) in enumerate(card_specs):
            card = ctk.CTkFrame(
                cards, fg_color=(light_bg, dark_bg), corner_radius=12,
                border_width=1, border_color=("#D8DEE8", "#344258"),
            )
            card.grid(row=0, column=column, padx=6, sticky="nsew")
            ctk.CTkLabel(
                card, text=title, fg_color="transparent", text_color=("#6B7280", "#94A3B8"), anchor="w",
                font=ctk.CTkFont(family="Segoe UI", size=TABLE_HEADER_FONT_SIZE, weight="bold"),
            ).pack(fill="x")
            card.winfo_children()[-1].pack_configure(padx=14, pady=(8, 2))
            ctk.CTkLabel(
                card, text=str(value), fg_color="transparent", text_color=color, anchor="w",
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            ).pack(fill="x", padx=14, pady=(0, 10))
        headings = ("#", "IMEI Number", "Specification (Specs)", "Format", "Taxation", "Network", "Action")
        for column, heading in enumerate(headings):
            header = tk.Label(
                self, text=heading, bg=background, fg=muted, font=("Segoe UI", TABLE_HEADER_FONT_SIZE, "bold"),
                padx=7, pady=9, highlightbackground=border, highlightthickness=0,
            )
            header.grid(row=3, column=column, sticky="nsew")
        tk.Frame(self, height=1, bg=border).grid(row=4, column=0, columnspan=8, sticky="ew")
        for index, item in enumerate(rows, start=1):
            data_row = 5 + (index - 1) * 2
            separator_row = data_row + 1
            values = (index, item.get("identifier"), item.get("device"), "Valid", item.get("taxation_text"), item.get("network_text"))
            for column, value in enumerate(values):
                color = foreground
                if column == 3:
                    color = GREEN
                elif column == 4:
                    color = GREEN if item.get("taxation_good") else RED
                elif column == 5:
                    color = GREEN if item.get("network_good") else RED
                self._label(data_row, column, value, color=color, pady=6, anchor="center" if column != 1 else "w")
            if is_payable_unpaid(item.get("taxation_text"), item.get("taxation_good")):
                self._pay_tax_button(data_row, str(item.get("identifier") or ""), 6)
            else:
                self._label(data_row, 6, "—", color=muted, pady=6, anchor="center")
            tk.Frame(self, height=1, bg=border).grid(row=separator_row, column=0, columnspan=8, sticky="ew")

    def _render_application(self, rows: list[dict]) -> None:
        if len(rows) > 1:
            grid_row = 0
            for index, item in enumerate(rows, start=1):
                raw = item.get("details") or {}
                status = raw.get("RequestStatus") or raw.get("Registry") or raw
                if not isinstance(status, dict):
                    status = {}
                grid_row = self._section(grid_row, f"Application Summary {index}")
                grid_row = self._field_pair(
                    grid_row,
                    ("Declaration ID", item.get("identifier", "")),
                    ("Business State", status.get("BusinessState") or item.get("taxation_text", "")),
                )
                grid_row = self._field_pair(
                    grid_row,
                    ("Total Amount", item.get("tax_text", "")),
                    ("Base Price", item.get("base_text", "")),
                )
                grid_row = self._field_pair(
                    grid_row,
                    ("Brand / Model", item.get("device", "")),
                    ("Payment Date", status.get("paymentDt") or ""),
                )
                grid_row = self._field_pair(
                    grid_row,
                    ("Created Date", status.get("createdDt") or ""),
                    ("Expiration Date", status.get("ExpirationDate") or ""),
                )
                grid_row += 2
            return
        item = rows[0] if rows else {}
        raw = item.get("details") or {}
        status = raw.get("RequestStatus") or raw.get("Registry") or raw
        if not isinstance(status, dict):
            status = {}
        row = self._section(0, "Application Summary")
        row = self._field_pair(row, ("Declaration ID", item.get("identifier", "")), ("Business State", status.get("BusinessState") or item.get("taxation_text", "")))
        row = self._field_pair(row, ("MSISDN", status.get("MSISDN") or ""), ("Registration Type", status.get("RegistrationType") or "None"))
        row = self._field_pair(row, ("Total Amount", item.get("tax_text", "")), ("Payment Amount", status.get("paymentAmount") or "0 MMK"))
        row = self._field_pair(row, ("Created Date", status.get("createdDt") or ""), ("Approved Date", status.get("approvedDt") or "None"))
        row = self._field_pair(row, ("Declaration Hash", status.get("declarationHash") or ""), ("Expiration Date", status.get("ExpirationDate") or ""))
        row = self._field_pair(row, ("Purpose", status.get("purpose") or ""), ("Source", status.get("source") or "LEGAL_INDIVIDUAL"))
        row = self._field_pair(row, ("Initiator", status.get("initiator") or ""), ("Login", status.get("login") or ""))
        row = self._field_pair(row, ("Method", status.get("Method") or ""), ("Payment Date", status.get("paymentDt") or ""))
        applicant = status.get("applicant") or raw.get("applicant") or {}
        row = self._section(row + 1, "Applicant Profile")
        row = self._field_pair(row, ("Full Name", applicant.get("fullName") or ""), ("National ID", applicant.get("nationalId") or ""))
        row = self._field_pair(row, ("Birthday", applicant.get("birthday") or ""), ("Email", applicant.get("email") or ""))
        row = self._field_pair(row, ("Address", applicant.get("address") or ""), ("Phone", applicant.get("phone") or ""))
        devices = status.get("devices") or []
        row = self._section(row + 1, f"Devices List ({len(devices)})")
        row = self._field_pair(row, ("Brand / Model", ", ".join(f"{d.get('brand', '')} {d.get('model', '')}".strip() for d in devices)), ("IMEIs", "\n".join(str(i) for d in devices for i in d.get("imeis", []))))
        row = self._section(row + 1, "Approvals & Documents")
        row = self._field_pair(row, ("Confirmed By", status.get("confirmedBy") or ""), ("Confirmed Date", status.get("confirmedDt") or "None"))
        row = self._field_pair(row, ("Approved By", status.get("approvedBy") or ""), ("Recommendation #", status.get("recommendationNo") or ""))
        row = self._field_pair(row, ("Licence #", status.get("licenceNo") or ""), ("Endorsement #", status.get("endorsementNo") or ""))
        row = self._field_pair(row, ("Release ID", status.get("releaseId") or "None"), ("Basis Price Sum", status.get("basePriceSum") or ""))
        self._field_pair(row, ("Comment", status.get("comment") or "None"))



class CheckView(Page):
    def __init__(
        self,
        master: ctk.CTkFrame,
        repository: CalculationRepository,
        on_saved: Callable[[], None],
        on_history: Callable[[], None],
        on_settings: Callable[[], None],
        on_theme: Callable[[str], None],
    ) -> None:
        super().__init__(master, "Check IMEI", "Enter multiple 15-digit IMEIs separated by commas or new lines.")
        self.title_label.grid_remove()
        if self.subtitle_label:
            self.subtitle_label.grid_remove()
        self.repository = repository
        self.on_saved = on_saved
        self.on_history = on_history
        self.on_settings = on_settings
        self.on_theme = on_theme
        self._cancel_requested = False
        self.failed_identifiers: list[str] = []
        self.unpaid_imeis: list[str] = []
        self.current_input_mode = "IMEI CHECK"
        self.input_cache = {mode: "" for mode in ("IMEI CHECK", "APP ID CHECK", "PAYTAX")}
        self.live_results: list[tuple[tuple[object, ...], tuple[str, ...]]] = []
        self.result_page = 1
        self.result_page_size = 100
        self._input_count_after_id: str | None = None
        self.service = CEIRService()
        self.grid_rowconfigure(1, weight=1)
        topbar = ctk.CTkFrame(self, corner_radius=0, fg_color=("#F8FAFC", "#0B1220"))
        topbar.grid(row=0, column=0, padx=14, pady=(8, 0), sticky="ew")
        ctk.CTkLabel(
            topbar, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left", padx=(2, 0), pady=6)
        self.theme_switch = ThemeToggle(topbar, self._change_theme)
        self.theme_switch.pack(side="right", padx=(6, 0), pady=4)
        self.theme_switch.set(ctk.get_appearance_mode())
        TopbarActionButton(
            topbar, symbol="⚙", text="Settings", width=81, command=self.on_settings,
        ).pack(side="right", padx=4, pady=4)
        TopbarActionButton(
            topbar, symbol="◷", text="History", width=81, command=self.on_history,
        ).pack(side="right", padx=4, pady=4)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        # Give the input side less space than the results table.  Its action
        # buttons reflow below when this column becomes narrow.
        body.grid_columnconfigure(0, weight=4, uniform="check_columns")
        body.grid_columnconfigure(1, weight=7, uniform="check_columns")
        body.grid_rowconfigure(0, weight=1)
        input_panel = ctk.CTkFrame(
            body, corner_radius=10, fg_color=("#FFFFFF", "#111C2E"),
            border_width=1, border_color=("#D8DEE8", "#2A3950"),
        )
        input_panel.grid(row=0, column=0, rowspan=3, padx=(4, 4), pady=2, sticky="nsew")
        input_panel.grid_columnconfigure((0, 1, 2), weight=1)
        # Keep the actions at the bottom of the panel instead of leaving a
        # large empty area below them on tall screens.
        input_panel.grid_rowconfigure(4, weight=1)
        self.mode_tabs = ctk.CTkSegmentedButton(
            input_panel, values=["IMEI Check", "App ID Check", "PayTax"], height=38,
            corner_radius=8, border_width=1,
            fg_color=("#FFFFFF", "#111C2E"),
            selected_color=BLUE, selected_hover_color=BLUE_HOVER,
            unselected_color=("#FFFFFF", "#111C2E"),
            unselected_hover_color=("#F1F5F9", "#1E293B"),
            text_color=("#111827", "#F8FAFC"),
            command=self._change_input_mode,
        )
        self.mode_tabs.grid(row=0, column=0, columnspan=3, padx=12, pady=(12, 6), sticky="ew")
        self.mode_tabs.set("IMEI Check")
        self._style_mode_tab_text()
        self.input_kind_label = ctk.CTkLabel(
            input_panel, text="IMEI INPUT", font=ctk.CTkFont(size=11, weight="bold"),
            text_color=BLUE,
        )
        self.input_kind_label.grid(row=1, column=0, padx=14, pady=(2, 1), sticky="w")
        self.imei_count_label = ctk.CTkLabel(
            input_panel, text="0 IMEIs ready", font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#64748B", "#94A3B8"), corner_radius=12,
            fg_color=("#EEF2F7", "#1E293B"), padx=10, pady=3,
        )
        self.imei_count_label.grid(row=1, column=1, columnspan=2, padx=14, pady=(2, 1), sticky="e")
        self.input_heading = ctk.CTkLabel(
            input_panel, text="Enter one device IMEI",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.input_heading.grid(row=2, column=0, columnspan=3, padx=14, pady=(2, 2), sticky="w")
        self.input_help = ctk.CTkLabel(
            input_panel, text="Enter exactly one valid 15-digit IMEI.",
            text_color=("#64748B", "#94A3B8"),
        )
        self.input_help.grid(row=3, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="w")
        self.imei_editor = ctk.CTkFrame(input_panel, fg_color="transparent")
        self.imei_editor.grid(row=4, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="nsew")
        self.imei_editor.grid_columnconfigure(0, weight=1)
        self.imei_editor.grid_rowconfigure(0, weight=1)
        self.imei = ctk.CTkTextbox(
            self.imei_editor, height=300, corner_radius=10, border_width=1,
            border_color=("#CBD2DC", "#3A4A62"), fg_color=("#FFFFFF", "#111827"),
            text_color=("#1F2937", "#F3F4F6"),
            font=ctk.CTkFont(family="Segoe UI", size=15),
            border_spacing=10, wrap="word", undo=True, maxundo=-1,
        )
        self.imei.grid(row=0, column=0, sticky="nsew")
        self.main_input_clear_button = ctk.CTkButton(
            self.imei_editor, text="×", width=22, height=22, corner_radius=11,
            font=ctk.CTkFont(size=13), fg_color="transparent",
            text_color=("#64748B", "#CBD5E1"), hover_color=("#FDE2E2", "#573038"),
            command=self._clear_main_input,
        )
        self.main_input_clear_button.place(relx=1, x=-25, y=8, anchor="ne")
        self.imei.bind("<KeyRelease>", self._on_main_input_key_release)
        self.imei.bind("<FocusIn>", self._on_input_focus_in)
        self.imei.bind("<FocusOut>", self._on_input_focus_out)
        self.imei._textbox.configure(
            spacing1=3, spacing3=3, insertwidth=2, padx=5, pady=5,
            selectbackground=BLUE, selectforeground="#FFFFFF",
            inactiveselectbackground="#BFD2FA",
        )
        self.paytax_frame = ctk.CTkFrame(
            input_panel, corner_radius=0, fg_color=("#F7F7F8", "#0F1929")
        )
        self.paytax_frame.grid(row=4, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="nsew")
        self.paytax_frame.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(
            self.paytax_frame, text="Device Registration IMEIs:", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 5), sticky="w")
        imei1_row = ctk.CTkFrame(self.paytax_frame, fg_color="transparent")
        imei1_row.grid(row=1, column=0, columnspan=2, padx=12, pady=5, sticky="ew")
        imei1_row.grid_columnconfigure(0, weight=1)
        self.paytax_imei1 = ctk.CTkEntry(imei1_row, placeholder_text="Enter IMEI 1…", height=42)
        self.paytax_imei1.grid(row=0, column=0, sticky="ew")
        imei1_clear_button = ctk.CTkButton(
            imei1_row, text="×", width=20, height=20, corner_radius=10,
            font=ctk.CTkFont(size=12), fg_color="transparent",
            text_color=("#64748B", "#CBD5E1"), hover_color=("#FDE2E2", "#573038"),
            command=lambda: self._clear_paytax_entry(self.paytax_imei1),
        )
        imei1_clear_button.place(relx=1, x=-10, rely=0.5, anchor="e")
        imei2_row = ctk.CTkFrame(self.paytax_frame, fg_color="transparent")
        imei2_row.grid(row=2, column=0, columnspan=2, padx=12, pady=5, sticky="ew")
        imei2_row.grid_columnconfigure(0, weight=1)
        self.paytax_imei2 = ctk.CTkEntry(imei2_row, placeholder_text="Enter IMEI 2…", height=42)
        self.paytax_imei2.grid(row=0, column=0, sticky="ew")
        imei2_clear_button = ctk.CTkButton(
            imei2_row, text="×", width=20, height=20, corner_radius=10,
            font=ctk.CTkFont(size=12), fg_color="transparent",
            text_color=("#64748B", "#CBD5E1"), hover_color=("#FDE2E2", "#573038"),
            command=lambda: self._clear_paytax_entry(self.paytax_imei2),
        )
        imei2_clear_button.place(relx=1, x=-10, rely=0.5, anchor="e")
        self.paytax_imei1.bind("<KeyRelease>", self._update_input_count)
        self.paytax_imei2.bind("<KeyRelease>", self._update_input_count)
        ctk.CTkButton(
            self.paytax_frame, text="⇧ Choose Profile JSON", height=38,
            fg_color=("#E5E7EB", "#334155"), text_color=("#374151", "#F8FAFC"),
            hover_color=("#D8DEE8", "#475569"), command=self._import_profile_json,
        ).grid(row=3, column=0, padx=(12, 5), pady=(5, 4), sticky="ew")
        ctk.CTkButton(
            self.paytax_frame, text="＋ Create Profile JSON", height=38,
            fg_color=("#E5E7EB", "#334155"), text_color=(BLUE, "#7DA2FF"),
            hover_color=("#D8DEE8", "#475569"), command=self.open_profile_editor,
        ).grid(row=3, column=1, padx=(5, 12), pady=(5, 4), sticky="ew")
        self.profile_file_label = ctk.CTkLabel(
            self.paytax_frame, text="No file selected (Required)", text_color=RED, anchor="w"
        )
        self.profile_file_label.grid(row=4, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="ew")
        self.paytax_frame.grid_remove()
        for widget in (self.input_kind_label, self.imei_count_label, self.input_heading, self.input_help):
            widget.grid_remove()
        options = ctk.CTkFrame(input_panel, fg_color="transparent")
        options.grid(row=5, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="ew")
        self.altcha_bypass = tk.BooleanVar(value=True)
        self.tax_paid_first = tk.BooleanVar(value=False)
        compact_checkbox = {
            "checkbox_width": 18, "checkbox_height": 18, "corner_radius": 5,
            "border_width": 2, "font": ctk.CTkFont(size=12), "height": 22,
        }
        ctk.CTkCheckBox(
            options, text="Use Altcha Security Bypass", variable=self.altcha_bypass, **compact_checkbox,
        ).pack(anchor="w", pady=1)
        ctk.CTkCheckBox(
            options, text="Sort Batch: Tax Paid First", variable=self.tax_paid_first, **compact_checkbox,
        ).pack(anchor="w", pady=1)

        primary_actions = ctk.CTkFrame(input_panel, fg_color="transparent")
        primary_actions.grid(row=6, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="ew")
        primary_actions.grid_columnconfigure(0, weight=2)
        primary_actions.grid_columnconfigure(1, weight=1)
        self.check_button = ctk.CTkButton(
            primary_actions, text="START CHECK", height=38, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=BLUE, hover_color=BLUE_HOVER, command=self.start_check,
        )
        self.check_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.cancel_button = ctk.CTkButton(
            primary_actions, text="CANCEL", height=38, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#EEF1F5", "#263449"), text_color=(RED, "#FDA29B"),
            hover_color=("#E1E6EC", "#334155"), command=self.cancel_check,
        )
        self.cancel_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        input_actions = ctk.CTkFrame(input_panel, fg_color="transparent")
        input_actions.grid(row=7, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="ew")
        input_actions.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.import_button = ctk.CTkButton(
            input_actions, text="⇧ Import File", height=38,
            fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"),
            hover_color=("#D8E2F0", "#475569"), command=self.import_imei_file,
        )
        self.import_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.clear_button = ctk.CTkButton(
            input_actions, text="× Clear", height=38,
            fg_color=("#FDECEC", "#48252A"), text_color=("#B42318", "#FDA29B"),
            hover_color=("#FBD5D5", "#633038"), command=self.clear_input,
        )
        self.clear_button.grid(row=0, column=1, padx=4, sticky="ew")
        self.retry_button = ctk.CTkButton(
            input_actions, text="↻ Retry Failed", height=38, state="disabled",
            fg_color=AMBER, hover_color="#B45309", command=self._retry_or_edit_profile,
        )
        self.retry_button.grid(row=0, column=2, padx=4, sticky="ew")
        self.history_button = ctk.CTkButton(
            input_actions, text="◷ View History", height=38,
            fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"),
            hover_color=("#D8E2F0", "#475569"), command=self.on_history,
        )
        self.history_button.grid(row=0, column=3, padx=(4, 0), sticky="ew")
        self.reload_session_button = ctk.CTkButton(
            input_actions, text="↻ Reload CEIR Session", height=34,
            fg_color="transparent", text_color=("#475569", "#94A3B8"),
            hover_color=("#E8EEF7", "#263449"), command=self.reload_session,
        )
        self.reload_session_button.grid(row=1, column=0, columnspan=2, padx=(0, 4), pady=(6, 0), sticky="ew")
        self.official_tax_button = ctk.CTkButton(
            input_actions, text="Pay Tax  →", height=34, state="disabled",
            fg_color=AMBER, hover_color="#B45309", command=self._secondary_action,
        )
        self.official_tax_button.grid(row=1, column=2, columnspan=2, padx=(4, 0), pady=(6, 0), sticky="ew")
        self.report_button = ctk.CTkButton(
            input_actions, text="⇩ Export PNG", height=38,
            fg_color=("#EEF1F5", "#263449"), text_color=("#374151", "#E5E7EB"),
            hover_color=("#E1E6EC", "#334155"), command=self.export_report_image,
        )
        self.csv_button = ctk.CTkButton(
            input_actions, text="⇩ Export to CSV", height=38,
            fg_color=("#EEF1F5", "#263449"), text_color=("#374151", "#E5E7EB"),
            hover_color=("#E1E6EC", "#334155"), command=self.export_current_csv,
        )
        self.quick_paytax_button = ctk.CTkButton(
            input_panel, text="Pay Tax  →", height=36, corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color=BLUE,
            hover_color=BLUE_HOVER, command=self.get_official_tax,
        )
        self.quick_paytax_button.grid(
            row=8, column=0, columnspan=3, padx=14, pady=(0, 7), sticky="ew",
        )
        self.quick_paytax_button.grid_remove()
        self.result_status = ctk.CTkLabel(
            input_panel, text="Status: Ready to Check.", font=ctk.CTkFont(size=11),
            text_color=("#64748B", "#94A3B8"), anchor="w",
        )
        self.result_status.grid(row=9, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="ew")
        self.input_actions = input_actions
        self._actions_compact: bool | None = None
        input_actions.bind("<Configure>", self._reflow_input_actions)
        result = ctk.CTkFrame(
            body, corner_radius=10, fg_color=("#FFFFFF", "#111C2E"),
            border_width=1, border_color=("#D8DEE8", "#2A3950"),
        )
        result.grid(row=0, column=1, rowspan=3, padx=(4, 4), pady=2, sticky="nsew")
        result_table_frame = ctk.CTkFrame(result, fg_color="transparent")
        result_table_frame.pack(fill="both", expand=True, padx=10, pady=10)
        result_table_frame.grid_columnconfigure(0, weight=1)
        result_table_frame.grid_rowconfigure(0, weight=1)
        # A plain grid would squish/clip columns below their minimum widths on a
        # small window. Wrapping it in a canvas + horizontal scrollbar lets the
        # table keep its natural width and scroll instead of breaking.
        canvas_bg = "#FFFFFF" if ctk.get_appearance_mode() == "Light" else "#111C2E"
        self.results_canvas = tk.Canvas(result_table_frame, highlightthickness=0, bd=0, bg=canvas_bg)
        self.results_canvas.grid(row=0, column=0, sticky="nsew")
        results_hscroll = ttk.Scrollbar(result_table_frame, orient="horizontal", command=self.results_canvas.xview)
        results_hscroll.grid(row=1, column=0, sticky="ew")
        results_vscroll = ttk.Scrollbar(result_table_frame, orient="vertical", command=self.results_canvas.yview)
        results_vscroll.grid(row=0, column=1, sticky="ns")
        self.results_canvas.configure(xscrollcommand=results_hscroll.set, yscrollcommand=results_vscroll.set)
        self.results_grid = LiveResultsGrid(self.results_canvas, self._open_unpaid_in_paytax)
        self.results_grid_window = self.results_canvas.create_window((0, 0), window=self.results_grid, anchor="nw")
        self.results_grid.bind(
            "<Configure>", lambda _event: self.results_canvas.configure(scrollregion=self.results_canvas.bbox("all"))
        )
        self.results_canvas.bind("<Configure>", self._on_results_canvas_configure)
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
        result_footer.pack_forget()
        self.note.pack_forget()
        self._layout_input_actions()
        self.apply_table_style()
        self._render_result_page()

    def _reflow_input_actions(self, event: tk.Event) -> None:
        self._actions_compact = event.width < 560
        self._layout_input_actions()

    def _layout_input_actions(self) -> None:
        for column in range(4):
            self.input_actions.grid_columnconfigure(column, weight=1)
        for widget in (self.import_button, self.clear_button, self.retry_button, self.history_button, self.official_tax_button):
            widget.grid_remove()
        self.reload_session_button.grid(row=0, column=0, columnspan=4, padx=0, pady=(0, 6), sticky="ew")
        self.report_button.grid(row=1, column=0, columnspan=2, padx=(0, 5), sticky="ew")
        self.csv_button.grid(row=1, column=2, columnspan=2, padx=(5, 0), sticky="ew")

    def apply_table_style(self) -> None:
        dark = ctk.get_appearance_mode() == "Dark"
        self.results_grid.configure_theme(dark)
        self.results_canvas.configure(bg="#111C2E" if dark else "#FFFFFF")

    def _change_theme(self, mode: str) -> None:
        self.on_theme(mode)

    def _change_input_mode(self, mode: str) -> None:
        self._style_mode_tab_text()
        mode = mode.upper()
        self.quick_paytax_button.grid_remove()
        self.input_cache[self.current_input_mode] = self._current_input_text().strip()
        self.current_input_mode = mode
        self.results_grid.set_mode(mode)
        cached = self.input_cache.get(mode, "")
        if mode == "PAYTAX":
            self.imei_editor.grid_remove()
            self.paytax_frame.grid()
        else:
            self.paytax_frame.grid_remove()
            self.imei_editor.grid()
        self._set_current_input_text(cached)
        is_app_id = mode == "APP ID CHECK"
        is_paytax = mode == "PAYTAX"
        if is_paytax:
            profile = self.repository.get_applicant_profile()
            self.profile_file_label.configure(
                text=f"Profile ready: {profile.full_name}" if profile.is_complete() else "No file selected (Required)",
                text_color=GREEN if profile.is_complete() else RED,
            )
        self.check_button.configure(text=self._check_button_label())
        self.results_grid.set_identifier_label("App ID" if is_app_id else "IMEI / App ID")
        self.results_grid.set_extra_column_label("Confirmed / Paid" if is_app_id or is_paytax else "Allocation Date")
        self.failed_identifiers = []
        self.retry_button.configure(
            text="＋ Create Profile JSON" if is_paytax else "↻ Retry Failed",
            state="normal" if is_paytax else "disabled",
        )
        self.unpaid_imeis = []
        self.import_button.configure(text="⇧ Load Profile JSON" if is_paytax else "⇧ Import File")
        self.official_tax_button.configure(
            text="Save Profile JSON" if is_paytax else "Pay Tax  →",
            state="normal" if is_paytax else "disabled",
        )
        self._set_results()
        self.result_status.configure(text="Status: Ready to Check.", text_color=("#64748B", "#94A3B8"))
        self.note.configure(
            text=(
                "A saved applicant profile is required. Registration and IRD payment use the official CEIR APIs."
                if is_paytax else
                "Registration status and official tax amounts are loaded from the CEIR App ID API."
                if is_app_id else
                "Brand and Model are loaded automatically from the CEIR Device Info API."
            ),
            text_color=("#64748B", "#94A3B8"),
        )
        self._update_input_count()
        self._layout_input_actions()

    def _style_mode_tab_text(self) -> None:
        """Keep inactive tabs readable while preserving white text on the active blue tab."""
        selected = self.mode_tabs.get()
        for value, button in self.mode_tabs._buttons_dict.items():
            button.configure(
                text_color="#FFFFFF" if value == selected else ("#111827", "#F8FAFC"),
                text_color_disabled=("#6B7280", "#94A3B8"),
            )

    def _current_input_text(self) -> str:
        if self.current_input_mode == "PAYTAX":
            return "\n".join(value for value in (self.paytax_imei1.get(), self.paytax_imei2.get()) if value.strip())
        return self.imei.get("1.0", "end")

    def _set_current_input_text(self, content: str) -> None:
        if self.current_input_mode == "PAYTAX":
            values = [value for value in content.replace(",", " ").split() if value][:2]
            for entry, value in zip((self.paytax_imei1, self.paytax_imei2), [*values, "", ""]):
                entry.delete(0, "end")
                if value:
                    entry.insert(0, value)
            return
        self.imei.delete("1.0", "end")
        if content:
            self.imei.insert("1.0", content)

    def _clear_paytax_entry(self, entry: ctk.CTkEntry) -> None:
        entry.delete(0, "end")
        self.input_cache["PAYTAX"] = self._current_input_text()
        self._update_input_count()
        entry.focus_set()

    def _clear_main_input(self) -> None:
        self.imei.delete("1.0", "end")
        self.input_cache[self.current_input_mode] = ""
        self._update_input_count()
        self.imei.focus_set()

    def _on_main_input_key_release(self, event: tk.Event) -> None:
        content = self.imei.get("1.0", "end-1c")
        sanitized = sanitize_identifier_input(content)
        if sanitized != content:
            prefix = self.imei.get("1.0", "insert")
            cursor_offset = len(sanitize_identifier_input(prefix))
            self.imei.delete("1.0", "end")
            self.imei.insert("1.0", sanitized)
            self.imei.mark_set("insert", f"1.0+{cursor_offset}c")
            self.imei.see("insert")
        self._update_input_count(event)

    def _sanitize_input_box(self, _event: object = None) -> None:
        if self.current_input_mode == "PAYTAX":
            for entry in (self.paytax_imei1, self.paytax_imei2):
                value = "".join(character for character in entry.get() if character.isdigit())[:15]
                entry.delete(0, "end")
                entry.insert(0, value)
            self._update_input_count()
            return
        # The multiline editor deliberately preserves the user's whitespace,
        # line breaks, selection, and cursor position like a normal text editor.
        # The parsers already understand commas, spaces, and new lines.
        self._update_input_count()

    def _on_input_focus_in(self, _event: object = None) -> None:
        self.imei.configure(border_color=BLUE)

    def _on_input_focus_out(self, _event: object = None) -> None:
        # Keep the editor untouched while the user moves around the form.
        # Validation and normalization happen only when START CHECK is used.
        self.imei.configure(border_color=("#CBD2DC", "#3A4A62"))

    def _update_input_count(self, _event: object = None) -> None:
        if _event is not None:
            if self._input_count_after_id is not None:
                self.after_cancel(self._input_count_after_id)
            self._input_count_after_id = self.after(120, self._update_input_count)
            return
        self._input_count_after_id = None
        candidates = self._current_input_text().replace(",", " ").split()
        if self.current_input_mode != "APP ID CHECK":
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
        if self.current_input_mode == "PAYTAX":
            self._import_profile_json()
            return
        noun = "App ID" if self.current_input_mode == "APP ID CHECK" else "IMEI"
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

    def export_current_csv(self) -> None:
        if not self.live_results:
            messagebox.showinfo("Export CSV", "There are no current results to export.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export Current Results", defaultextension=".csv",
            initialfile="ceir_current_results.csv", filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["IMEI / App ID", "Brand / Model", "Taxation", "Network", "Base Price", "Tax Price", "Details"])
                for item in self.live_results:
                    writer.writerow([
                        item.get("identifier", ""), item.get("device", ""), item.get("taxation_text", ""),
                        item.get("network_text", ""), item.get("base_text", ""), item.get("tax_text", ""),
                        item.get("extra_text", ""),
                    ])
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.result_status.configure(text=f"Status: CSV exported to {path}", text_color=GREEN)

    def export_report_image(self) -> None:
        if not self.live_results:
            messagebox.showinfo("Export PNG", "There are no current results to export.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export PNG", defaultextension=".png",
            initialfile="ceir_report.png", filetypes=[("PNG image", "*.png")],
        )
        if not path:
            return
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            messagebox.showerror(
                "PNG export unavailable",
                "Pillow is required for PNG export. Reinstall the app dependencies and try again.",
                parent=self,
            )
            return

        dark = ctk.get_appearance_mode() == "Dark"
        colors = {
            "background": "#111C2E" if dark else "#FFFFFF",
            "foreground": "#E5E7EB" if dark else "#1F2937",
            "muted": "#94A3B8" if dark else "#64748B",
            "header": "#17243A" if dark else "#EEF2F7",
            "alternate": "#152238" if dark else "#F8FAFC",
            "divider": "#334155" if dark else "#D8DEE8",
        }
        width, row_height, table_top = 1600, 52, 142
        height = max(360, table_top + 50 + len(self.live_results) * row_height + 42)

        def load_font(size: int, bold: bool = False):
            candidates = (
                ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/SFNS.ttf"),
                ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
                ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            )
            for regular, strong in candidates:
                try:
                    return ImageFont.truetype(strong if bold else regular, size=size)
                except OSError:
                    continue
            return ImageFont.load_default()

        title_font = load_font(30, True)
        subtitle_font = load_font(18)
        header_font = load_font(16, True)
        cell_font = load_font(16)
        image = Image.new("RGB", (width, height), colors["background"])
        draw = ImageDraw.Draw(image)
        draw.text((48, 34), APP_NAME, fill=colors["foreground"], font=title_font)
        draw.text(
            (48, 78), f"{self.current_input_mode.title()} Report",
            fill=colors["muted"], font=subtitle_font,
        )
        draw.rounded_rectangle((40, table_top, width - 40, height - 32), radius=12, outline=colors["divider"], width=1)
        draw.rectangle((41, table_top + 1, width - 41, table_top + 49), fill=colors["header"])

        headers = ("IMEI / App ID", "Brand / Model", "Taxation", "Network", "Base Price", "Tax Price")
        xs = (58, 350, 730, 910, 1080, 1320)
        column_widths = (275, 360, 160, 150, 220, 220)

        def fitted_text(value: object, max_width: int) -> str:
            text = str(value or "")
            if draw.textlength(text, font=cell_font) <= max_width:
                return text
            while text and draw.textlength(f"{text}…", font=cell_font) > max_width:
                text = text[:-1]
            return f"{text}…"

        for x, heading in zip(xs, headers):
            draw.text((x, table_top + 15), heading, fill=colors["muted"], font=header_font)
        for index, item in enumerate(self.live_results):
            top = table_top + 50 + index * row_height
            if index % 2:
                draw.rectangle((41, top, width - 41, top + row_height), fill=colors["alternate"])
            values = (
                item.get("identifier"), item.get("device"), item.get("taxation_text"),
                item.get("network_text"), item.get("base_text"), item.get("tax_text"),
            )
            for column, (x, value, max_width) in enumerate(zip(xs, values, column_widths)):
                text = fitted_text(value, max_width)
                text_color = colors["foreground"]
                if column == 2 and text:
                    text_color = GREEN if text.upper() in {"PAID", "VALID", "TAX PAID"} else RED
                elif column == 3 and text:
                    text_color = GREEN if text.upper() in {"ALLOWED", "UNBLOCKED", "VALID"} else RED
                draw.text((x, top + 16), text, fill=text_color, font=cell_font)
            draw.line((41, top + row_height, width - 41, top + row_height), fill=colors["divider"], width=1)
        try:
            image.save(path, format="PNG", optimize=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.result_status.configure(text=f"Status: PNG exported to {path}", text_color=GREEN)

    def _import_profile_json(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Load Applicant Profile", filetypes=[("JSON profile", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("The profile must be a JSON object.")
            profile = ApplicantProfile(
                taxpayer_type=str(data.get("taxpayerType") or data.get("taxpayer_type") or "Individual"),
                is_foreigner=bool(data.get("isForeigner", data.get("is_foreigner", False))),
                tin=str(data.get("tin") or ""),
                national_id=str(data.get("nationalId") or data.get("national_id") or ""),
                full_name=str(data.get("fullName") or data.get("full_name") or ""),
                birthday=str(data.get("birthday") or ""), address=str(data.get("address") or ""),
                email=str(data.get("email") or ""), phone=str(data.get("phone") or ""),
                tax_office_division=str(data.get("taxOfficeDivision") or data.get("tax_office_division") or ""),
                tax_office_code=str(data.get("taxOfficeCode") or data.get("tax_office_code") or ""),
                region_code=str(data.get("regionCode") or data.get("region_code") or ""),
                township_code=str(data.get("townshipCode") or data.get("township_code") or ""),
                uin=str(data.get("uin") or ""),
            )
            if not profile.is_complete():
                raise ValueError("National ID, Full Name, Birthday, Address, and Phone are required.")
            self.repository.save_applicant_profile(profile)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            messagebox.showerror("Profile import failed", str(exc), parent=self)
            return
        self.profile_file_label.configure(text=f"Selected: {Path(path).name}", text_color=GREEN)
        self.note.configure(text=f"Applicant profile loaded: {profile.full_name}", text_color=GREEN)

    def _export_profile_json(self) -> None:
        profile = self.repository.get_applicant_profile()
        if not profile.is_complete():
            messagebox.showwarning("Profile incomplete", "Complete the applicant details first.", parent=self)
            self.on_settings()
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Applicant Profile", defaultextension=".json",
            initialfile="ceir_applicant_profile.json", filetypes=[("JSON profile", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(profile.to_api_payload(), handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showerror("Profile export failed", str(exc), parent=self)
            return
        self.note.configure(text=f"Applicant profile saved to {path}", text_color=GREEN)

    def _retry_or_edit_profile(self) -> None:
        if self.current_input_mode == "PAYTAX":
            self.open_profile_editor()
        else:
            self.retry_failed()

    def open_profile_editor(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Applicant Details")
        dialog.geometry("1040x680")
        dialog.minsize(820, 590)
        dialog.transient(self.winfo_toplevel())
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        heading = ctk.CTkFrame(dialog, corner_radius=0, fg_color=("#F8FAFC", "#111C2E"))
        heading.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            heading, text="Applicant Details (for Official CEIR Tax Registration)",
            font=ctk.CTkFont(size=20, weight="bold"), anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 6))
        ctk.CTkLabel(
            heading, text="Complete the applicant identity used for CEIR registration and IRD payment.",
            text_color=("#64748B", "#94A3B8"), anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 16))

        form = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        form.grid(row=1, column=0, padx=18, pady=12, sticky="nsew")
        form.grid_columnconfigure((0, 1, 2), weight=1, uniform="applicant_fields")
        current = self.repository.get_applicant_profile()
        try:
            birthday_display = datetime.strptime(
                normalize_birthday(current.birthday), "%Y-%m-%d",
            ).strftime("%d-%m-%Y")
        except ValueError:
            birthday_display = current.birthday
        nrc_region_saved, nrc_township_saved, nrc_type_saved, nrc_number_saved = parse_nrc(current.national_id)
        variables = {
            key: tk.StringVar(
                value=(birthday_display if key == "birthday" else nrc_number_saved if key == "nrc_number" else getattr(current, key))
            )
            for key in ("nrc_number", "uin", "full_name", "birthday", "address", "email", "phone")
        }

        def field_frame(row: int, column: int, label: str, columnspan: int = 1) -> ctk.CTkFrame:
            field = ctk.CTkFrame(form, fg_color="transparent")
            field.grid(row=row, column=column, columnspan=columnspan, padx=8, pady=7, sticky="ew")
            ctk.CTkLabel(field, text=label, font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(
                fill="x", pady=(0, 5)
            )
            return field

        def add_entry(row: int, column: int, key: str, label: str, placeholder: str) -> None:
            ctk.CTkEntry(
                field_frame(row, column, label), textvariable=variables[key],
                placeholder_text=placeholder, height=38,
            ).pack(fill="x")

        nrc_region_var = tk.StringVar(value="Loading…")
        nrc_township_var = tk.StringVar(value=nrc_township_saved or "Select NRC region first")
        nrc_type_var = tk.StringVar(value=nrc_type_saved or "Loading…")
        region_var = tk.StringVar(value=current.tax_office_division or "Loading…")
        township_var = tk.StringVar(value=current.tax_office_code or "Select state/division first")
        region_map: dict[str, dict] = {}
        nrc_region_map: dict[str, dict] = {}
        nrc_township_map: dict[str, dict] = {}
        document_type_map: dict[str, dict] = {}
        township_map: dict[str, dict] = {}

        option_colors = {
            "fg_color": ("#E8F0FC", "#1E293B"), "button_color": BLUE,
            "button_hover_color": BLUE_HOVER, "text_color": ("#1E3A5F", "#F8FAFC"),
            "dropdown_fg_color": ("#FFFFFF", "#1E293B"),
            "dropdown_hover_color": ("#DCE8FA", "#334155"),
            "dropdown_text_color": ("#1E3A5F", "#F8FAFC"),
        }

        nrc_field = field_frame(0, 0, "NRC / National ID * — select the first three parts; type only the 6-digit number", 3)
        nrc_row = ctk.CTkFrame(nrc_field, fg_color="transparent")
        nrc_row.pack(fill="x")
        nrc_row.grid_columnconfigure(1, weight=1)
        nrc_region_menu = SearchableDropdown(
            nrc_row, variable=nrc_region_var, values=[nrc_region_var.get()], width=180, height=38,
            state="disabled",
            **option_colors,
        )
        nrc_region_menu.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        nrc_township_menu = SearchableDropdown(
            nrc_row, variable=nrc_township_var, values=[nrc_township_var.get()], height=38,
            state="disabled",
            **option_colors,
        )
        nrc_township_menu.grid(row=0, column=1, padx=6, sticky="ew")
        nrc_type_menu = SearchableDropdown(
            nrc_row, variable=nrc_type_var, values=[nrc_type_var.get()], width=150, height=38,
            state="disabled",
            **option_colors,
        )
        nrc_type_menu.grid(row=0, column=2, padx=6, sticky="ew")
        nrc_number_validation = (dialog.register(lambda value: not value or (value.isdigit() and len(value) <= 6)), "%P")
        ctk.CTkEntry(
            nrc_row, textvariable=variables["nrc_number"], placeholder_text="6-digit number",
            width=190, height=38, validate="key", validatecommand=nrc_number_validation,
        ).grid(row=0, column=3, padx=(6, 0), sticky="ew")

        add_entry(1, 0, "uin", "Unique Identification Number", "Optional UIN")
        add_entry(1, 1, "full_name", "Full Name *", "Full Name")
        birthday_field = field_frame(1, 2, "Birthday *")
        EditableDatePicker(birthday_field, variables["birthday"]).pack(fill="x")

        region_menu = SearchableDropdown(
            field_frame(2, 0, "State / Division (Current Address) *"),
            variable=region_var, values=[region_var.get()], height=38, state="disabled",
            **option_colors,
        )
        region_menu.pack(fill="x")
        township_menu = SearchableDropdown(
            field_frame(2, 1, "Township *"), variable=township_var,
            values=[township_var.get()], height=38, state="disabled",
            **option_colors,
        )
        township_menu.pack(fill="x")

        add_entry(2, 2, "address", "Address *", "Current address")
        add_entry(3, 0, "email", "Contact Email", "email@example.com")
        add_entry(3, 1, "phone", "Phone *", "959XXXXXXXXX")

        filter_status = ctk.CTkLabel(
            field_frame(3, 2, "CEIR Lists"), text="Loading NRC, regions and tax offices…",
            text_color=AMBER, anchor="w", justify="left", wraplength=280,
        )
        filter_status.pack(fill="x", pady=8)

        ctk.CTkLabel(
            form,
            text=("Birthday can be typed as DD-MM-YYYY or selected with the calendar.  "
                  "IRD NRC format: use (N) instead of (နိုင်), for example 12/အလန(N)288521."),
            text_color=("#64748B", "#94A3B8"), anchor="w", justify="left",
        ).grid(row=4, column=0, columnspan=3, padx=8, pady=(10, 4), sticky="ew")

        def display_name(item: dict, primary: str, secondary: str, fallback: str) -> str:
            first, second = str(item.get(primary) or ""), str(item.get(secondary) or "")
            return " — ".join(part for part in (first, second) if part) or str(item.get(fallback) or "Unknown")

        def load_nrc_townships(region_label: str, preferred: str = "") -> None:
            item = nrc_region_map.get(region_label)
            if not item:
                return
            region_code = str(item.get("code") or "")
            nrc_township_var.set("Loading…")
            nrc_township_menu.set_values(["Loading…"], "disabled")

            def worker() -> None:
                try:
                    rows = self.service.get_townships(region_code)
                    error = ""
                except Exception as exc:
                    rows, error = [], str(exc)

                def apply() -> None:
                    if not dialog.winfo_exists() or nrc_region_map.get(nrc_region_var.get(), {}).get("code") != item.get("code"):
                        return
                    nrc_township_map.clear()
                    for row in rows:
                        label = display_name(row, "townshipMm", "townshipEn", "id")
                        nrc_township_map[label] = row
                    values = list(nrc_township_map) or ([preferred] if preferred else ["No townships available"])
                    nrc_township_menu.set_values(values, "normal" if nrc_township_map else "disabled")
                    selected = next(
                        (
                            label for label, row in nrc_township_map.items()
                            if str(row.get("townshipMm")) == preferred
                        ),
                        values[0],
                    )
                    nrc_township_var.set(selected)
                    if error:
                        filter_status.configure(text=f"NRC township API: {error}", text_color=RED)

                dialog.after(0, apply)

            threading.Thread(target=worker, daemon=True).start()

        def load_townships(region_label: str, preferred: str = "") -> None:
            item = region_map.get(region_label)
            if not item:
                return
            region_code = str(item.get("code") or "")
            township_var.set("Loading…")
            township_menu.set_values(["Loading…"], "disabled")

            def worker() -> None:
                try:
                    rows = self.service.get_tax_offices(region_code)
                    error = ""
                except Exception as exc:
                    rows, error = [], str(exc)

                def apply() -> None:
                    if not dialog.winfo_exists() or region_map.get(region_var.get(), {}).get("code") != item.get("code"):
                        return
                    township_map.clear()
                    for row in rows:
                        label = display_name(row, "officeNameEn", "officeNameMm", "officeCode")
                        township_map[label] = row
                    values = list(township_map) or ([preferred] if preferred else ["No townships available"])
                    township_menu.set_values(values, "normal" if township_map else "disabled")
                    selected = next(
                        (
                            label for label, row in township_map.items()
                            if str(row.get("officeCode")) == preferred
                        ),
                        values[0],
                    )
                    township_var.set(selected)
                    if error:
                        filter_status.configure(text=f"Tax office API: {error}", text_color=RED)

                dialog.after(0, apply)

            threading.Thread(target=worker, daemon=True).start()

        nrc_region_menu.set_command(lambda label: load_nrc_townships(label))
        region_menu.set_command(lambda label: load_townships(label))

        def load_initial_filters() -> None:
            errors: list[str] = []
            try:
                regions = self.service.get_regions()
            except Exception as exc:
                regions = []
                errors.append(f"Region: {exc}")
            try:
                document_types = self.service.get_document_types()
            except Exception as exc:
                document_types = []
                errors.append(f"NRC type: {exc}")
            try:
                tax_regions = self.service.get_tax_regions()
            except Exception as exc:
                tax_regions = []
                errors.append(f"Tax region: {exc}")

            def apply() -> None:
                if not dialog.winfo_exists():
                    return
                for row in regions:
                    nrc_code = str(row.get("codeMm") or row.get("code") or "")
                    nrc_region_map[f"{nrc_code}/"] = row
                for row in document_types:
                    document_type_map[display_name(row, "type", "typeValue", "id")] = row
                for row in tax_regions:
                    region_map[display_name(row, "nameEn", "nameMm", "code")] = row
                region_values = list(region_map) or (
                    [current.tax_office_division] if current.tax_office_division else ["Unavailable"]
                )
                nrc_region_values = list(nrc_region_map) or (
                    [f"{nrc_region_saved}/"] if nrc_region_saved else ["Unavailable"]
                )
                document_values = list(document_type_map) or ([nrc_type_saved] if nrc_type_saved else ["Unavailable"])
                nrc_region_menu.set_values(nrc_region_values, "normal" if nrc_region_map else "disabled")
                nrc_type_menu.set_values(document_values, "normal" if document_type_map else "disabled")
                region_menu.set_values(region_values, "normal" if region_map else "disabled")
                selected_nrc_region = next(
                    (label for label, row in nrc_region_map.items() if str(row.get("code")) == nrc_region_saved),
                    nrc_region_values[0],
                )
                selected_document_type = next(
                    (
                        label for label, row in document_type_map.items()
                        if str(row.get("typeValue")) == nrc_type_saved
                    ),
                    document_values[0],
                )
                selected_region = next(
                    (
                        label for label, row in region_map.items()
                        if str(row.get("code")) == current.tax_office_division
                    ),
                    region_values[0],
                )
                nrc_region_var.set(selected_nrc_region)
                nrc_type_var.set(selected_document_type)
                region_var.set(selected_region)
                if nrc_region_map:
                    load_nrc_townships(selected_nrc_region, nrc_township_saved)
                if region_map:
                    load_townships(selected_region, current.tax_office_code)
                filter_status.configure(
                    text="CEIR lists loaded" if not errors else "\n".join(errors),
                    text_color=GREEN if not errors else RED,
                )

            dialog.after(0, apply)

        threading.Thread(target=load_initial_filters, daemon=True).start()

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=2, column=0, padx=24, pady=(0, 20), sticky="ew")
        actions.grid_columnconfigure((0, 1, 2), weight=1)

        def save_profile(export_json: bool = False) -> None:
            try:
                birthday = normalize_birthday(variables["birthday"].get())
                nrc_region = nrc_region_map.get(nrc_region_var.get(), {})
                nrc_township = nrc_township_map.get(nrc_township_var.get(), {})
                document_type = document_type_map.get(nrc_type_var.get(), {})
                national_id = build_nrc(
                    str(nrc_region.get("code") or nrc_region_saved),
                    str(nrc_township.get("townshipMm") or nrc_township_saved),
                    str(document_type.get("typeValue") or nrc_type_saved),
                    variables["nrc_number"].get(),
                )
            except ValueError as exc:
                messagebox.showwarning("Invalid applicant details", str(exc), parent=dialog)
                return
            region = region_map.get(region_var.get(), {})
            township = township_map.get(township_var.get(), {})
            profile = ApplicantProfile(
                taxpayer_type=current.taxpayer_type or "Individual", is_foreigner=current.is_foreigner,
                tin=current.tin,
                region_code=current.region_code, township_code=current.township_code,
                tax_office_division=str(region.get("code") or current.tax_office_division),
                tax_office_code=str(township.get("officeCode") or current.tax_office_code),
                national_id=national_id,
                uin=variables["uin"].get().strip(), full_name=variables["full_name"].get().strip(),
                birthday=birthday, address=variables["address"].get().strip(),
                email=variables["email"].get().strip(), phone=variables["phone"].get().strip(),
            )
            if not profile.is_complete():
                messagebox.showwarning(
                    "Profile incomplete", "National ID, Full Name, Birthday, Address, and Phone are required.",
                    parent=dialog,
                )
                return
            self.repository.save_applicant_profile(profile)
            self.profile_file_label.configure(text=f"Profile ready: {profile.full_name}", text_color=GREEN)
            if export_json:
                path = filedialog.asksaveasfilename(
                    parent=dialog, title="Save Applicant Profile", defaultextension=".json",
                    initialfile="ceir_applicant_profile.json", filetypes=[("JSON profile", "*.json")],
                )
                if not path:
                    return
                try:
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(profile.to_api_payload(), handle, ensure_ascii=False, indent=2)
                except OSError as exc:
                    messagebox.showerror("Profile export failed", str(exc), parent=dialog)
                    return
            dialog.destroy()

        ctk.CTkButton(
            actions, text="Cancel", fg_color=("#E5E7EB", "#334155"),
            text_color=("#374151", "#F8FAFC"), command=dialog.destroy,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(
            actions, text="Save Profile", fg_color=BLUE, hover_color=BLUE_HOVER,
            command=save_profile,
        ).grid(row=0, column=1, padx=5, sticky="ew")
        ctk.CTkButton(
            actions, text="Save Profile JSON", fg_color=BLUE, hover_color=BLUE_HOVER,
            command=lambda: save_profile(True),
        ).grid(row=0, column=2, padx=(5, 0), sticky="ew")
        dialog.after(100, dialog.grab_set)

    def _secondary_action(self) -> None:
        if self.current_input_mode == "PAYTAX":
            self._export_profile_json()
        else:
            self.get_official_tax()

    def clear_input(self) -> None:
        self._set_current_input_text("")
        self.input_cache[self.current_input_mode] = ""
        self._update_input_count()
        self.failed_identifiers = []
        is_paytax = self.current_input_mode == "PAYTAX"
        self.retry_button.configure(
            text="＋ Create Profile JSON" if is_paytax else "↻ Retry Failed",
            state="normal" if is_paytax else "disabled",
        )
        self.unpaid_imeis = []
        self.quick_paytax_button.grid_remove()
        self.official_tax_button.configure(
            text="Save Profile JSON" if is_paytax else "Pay Tax  →",
            state="normal" if is_paytax else "disabled",
        )
        self._set_results()
        self.result_status.configure(text="Status: Ready to Check.", text_color=("#64748B", "#94A3B8"))
        self.note.configure(
            text=(
                "A saved applicant profile is required. Registration and IRD payment use the official CEIR APIs."
                if is_paytax else
                "Registration status and official tax amounts are loaded from the CEIR App ID API."
                if self.current_input_mode == "APP ID CHECK" else
                "Brand and Model are loaded automatically from the CEIR Device Info API."
            ),
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

    def reload_session(self) -> None:
        self.reload_session_button.configure(state="disabled", text="↻ Reloading CEIR session…")
        self.result_status.configure(text="Reloading CEIR session…", text_color=AMBER)
        threading.Thread(target=self._reload_session_worker, daemon=True).start()

    def _reload_session_worker(self) -> None:
        try:
            self.service.reload_session()
        except Exception as exc:
            self.after(0, self._finish_reload_session, False, str(exc))
            return
        self.after(0, self._finish_reload_session, True, "")

    def _finish_reload_session(self, success: bool, message: str) -> None:
        self.reload_session_button.configure(state="normal", text="↻ Reload CEIR Session")
        if success:
            self.result_status.configure(text="CEIR session reloaded.", text_color=GREEN)
        else:
            self.result_status.configure(text=f"Could not reload CEIR session: {message}", text_color=RED)

    def get_official_tax(self) -> None:
        if not self.unpaid_imeis:
            return
        if len(self.unpaid_imeis) == 1:
            self._open_unpaid_in_paytax(self.unpaid_imeis[0])
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Choose an unpaid IMEI")
        dialog.geometry("430x420")
        dialog.transient(self.winfo_toplevel())
        ctk.CTkLabel(
            dialog, text="Choose an IMEI to continue in PayTax",
            font=ctk.CTkFont(size=17, weight="bold"), anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 5))
        ctk.CTkLabel(
            dialog, text=f"{len(self.unpaid_imeis)} unpaid IMEIs found. Select 1 or 2 IMEIs.",
            text_color=("#64748B", "#94A3B8"), anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 12))
        choices = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        choices.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        selected_variables: dict[str, tk.BooleanVar] = {}
        selection_status = ctk.CTkLabel(
            dialog, text="Select at least one IMEI", text_color=("#64748B", "#94A3B8"),
        )

        def selected_imeis() -> list[str]:
            return [imei for imei, variable in selected_variables.items() if variable.get()]

        def update_selection(changed_imei: str) -> None:
            selected = selected_imeis()
            if len(selected) > 2:
                selected_variables[changed_imei].set(False)
                selected = selected_imeis()
                selection_status.configure(text="You can select a maximum of 2 IMEIs.", text_color=RED)
            else:
                selection_status.configure(
                    text=f"{len(selected)} selected" if selected else "Select at least one IMEI",
                    text_color=GREEN if selected else ("#64748B", "#94A3B8"),
                )
            continue_button.configure(state="normal" if selected else "disabled")

        for imei in self.unpaid_imeis:
            variable = tk.BooleanVar(value=False)
            selected_variables[imei] = variable
            ctk.CTkCheckBox(
                choices, text=imei, variable=variable, height=38, corner_radius=6,
                command=lambda value=imei: update_selection(value),
            ).pack(fill="x", pady=4)
        selection_status.pack(fill="x", padx=20, pady=(0, 8))
        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 18))
        actions.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            actions, text="Cancel", height=38, fg_color=("#E5E7EB", "#334155"),
            text_color=("#374151", "#F8FAFC"), command=dialog.destroy,
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        continue_button = ctk.CTkButton(
            actions, text="Continue to PayTax", height=38, state="disabled",
            fg_color=BLUE, hover_color=BLUE_HOVER,
            command=lambda: self._open_selected_unpaid_in_paytax(selected_imeis(), dialog),
        )
        continue_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")
        dialog.after(100, dialog.grab_set)

    def _open_unpaid_in_paytax(self, imei: str, dialog: ctk.CTkToplevel | None = None) -> None:
        self._open_selected_unpaid_in_paytax([imei], dialog)

    def _open_selected_unpaid_in_paytax(
        self, imeis: list[str], dialog: ctk.CTkToplevel | None = None,
    ) -> None:
        imeis = list(dict.fromkeys(imeis))[:2]
        if not imeis:
            return
        if dialog is not None:
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            dialog.destroy()
        self.input_cache["PAYTAX"] = "\n".join(imeis)
        self.quick_paytax_button.grid_remove()
        self.mode_tabs.set("PayTax")
        self._style_mode_tab_text()
        self._change_input_mode("PayTax")
        self.note.configure(
            text=(
                f"{len(imeis)} unpaid {'IMEIs are' if len(imeis) > 1 else 'IMEI is'} ready. "
                "Complete the applicant profile, then press START CHECK."
            ),
            text_color=AMBER,
        )
        self.paytax_imei1.focus_set()

    def _show_registration_quote(self, quote: RegistrationTaxQuote) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Official CEIR Tax")
        dialog.geometry("420x480")
        dialog.transient(self.winfo_toplevel())
        rows = [
            ("Customs Duty", quote.customs_duty),
            ("Commercial Tax", quote.commercial_tax),
            ("Redemption Fine for non-licensed import", quote.redemption_fee),
        ]
        if quote.income_tax:
            rows.append(("Advanced Income Tax", quote.income_tax))
        for index, (label, amount) in enumerate(rows):
            top_pad = 20 if index == 0 else 8
            ctk.CTkLabel(dialog, text=label, text_color=("#64748B", "#94A3B8")).pack(anchor="w", padx=20, pady=(top_pad, 0))
            ctk.CTkLabel(dialog, text=format_mmk(amount), font=ctk.CTkFont(size=20, weight="bold"), text_color=BLUE).pack(anchor="w", padx=20)
        ctk.CTkFrame(dialog, height=1, fg_color=("#D8DEE8", "#2A3950")).pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(dialog, text="Total Tax Amount", text_color=("#64748B", "#94A3B8")).pack(anchor="w", padx=20)
        ctk.CTkLabel(
            dialog, text=format_mmk(quote.total_tax), font=ctk.CTkFont(size=26, weight="bold"), text_color=GREEN,
        ).pack(anchor="w", padx=20, pady=(0, 20))
        ctk.CTkLabel(dialog, text=f"App ID: {quote.declaration_id}", text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=20, pady=(0, 12)
        )
        ctk.CTkButton(
            dialog, text="Open Official IRD Payment", fg_color=GREEN, hover_color="#047857",
            command=lambda: self._open_payment(quote, dialog),
        ).pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkButton(
            dialog, text="Pay Later", fg_color=("#E8EEF7", "#334155"),
            text_color=("#1E293B", "#F8FAFC"), command=dialog.destroy,
        ).pack(fill="x", padx=20, pady=(0, 20))

    def _open_payment(self, quote: RegistrationTaxQuote, dialog: ctk.CTkToplevel) -> None:
        dialog.destroy()
        self.result_status.configure(text="Preparing official IRD payment page…", text_color=AMBER)
        registry = quote.raw.get("Registry") or {}
        declaration_hash = str(
            registry.get("DeclarationHash") or registry.get("declarationHash") or ""
        ) if isinstance(registry, dict) else ""
        applicant = self.repository.get_applicant_profile().to_api_payload()
        threading.Thread(
            target=self._payment_worker,
            args=(quote.declaration_id, declaration_hash, applicant), daemon=True,
        ).start()

    def _payment_worker(self, declaration_id: str, declaration_hash: str, applicant: dict) -> None:
        try:
            path = self.service.initialize_payment(declaration_id, declaration_hash, applicant)
        except Exception as exc:
            self.after(0, self._finish_payment, "", str(exc))
            return
        self.after(0, self._finish_payment, path, "")

    def _finish_payment(self, path: str, error: str) -> None:
        if error:
            self.result_status.configure(text="Could not prepare IRD payment", text_color=RED)
            messagebox.showerror("IRD payment failed", error, parent=self)
            return
        self.result_status.configure(text="IRD payment page opened in your browser", text_color=GREEN)
        webbrowser.open(Path(path).resolve().as_uri())

    def _parse_identifiers(self) -> list[str]:
        content = self._current_input_text()
        if self.current_input_mode == "APP ID CHECK":
            return parse_app_id_list(content)
        imeis = parse_imei_list(content)
        if self.current_input_mode == "PAYTAX" and len(imeis) not in {1, 2}:
            raise ValueError("PayTax requires one IMEI, or two IMEIs for a dual-SIM device.")
        return imeis

    def _check_button_label(self) -> str:
        return "START CHECK"

    def start_check(self) -> None:
        self._cancel_requested = False
        self._sanitize_input_box()
        try:
            identifiers = self._parse_identifiers()
        except ValueError as exc:
            messagebox.showwarning("Invalid input", str(exc), parent=self)
            return
        profile = None
        if self.current_input_mode == "PAYTAX":
            profile = self.repository.get_applicant_profile()
            if not profile.is_complete():
                messagebox.showwarning(
                    "Applicant profile required",
                    "Load a Profile JSON or complete Applicant Details in Settings before registering.",
                    parent=self,
                )
                return
            if not messagebox.askyesno(
                "Submit CEIR registration",
                "This creates a real CEIR declaration for this device and prepares its IRD payment page. Continue?",
                parent=self,
            ):
                return
        self.failed_identifiers = []
        self.quick_paytax_button.grid_remove()
        self.retry_button.configure(text="↻ Retry Failed", state="disabled")
        self.unpaid_imeis = []
        if self.current_input_mode != "PAYTAX":
            self.official_tax_button.configure(text="Pay Tax  →", state="disabled")
        self.check_button.configure(state="disabled", text=f"Checking 0/{len(identifiers)}…")
        self.mode_tabs.configure(state="disabled")
        self.result_status.configure(text="Status: Solving verification challenge…", text_color=AMBER)
        self._set_results("")
        if self.current_input_mode == "APP ID CHECK":
            target, args = self._app_id_worker, (identifiers,)
        elif self.current_input_mode == "PAYTAX":
            target, args = self._paytax_worker, (identifiers, profile.to_api_payload())
        else:
            check_type = "SINGLE CHECK" if len(identifiers) == 1 else "BATCH CHECK"
            target, args = self._worker, (identifiers, check_type)
        threading.Thread(target=target, args=args, daemon=True).start()

    def cancel_check(self) -> None:
        self._cancel_requested = True
        self.clear_input()
        self.check_button.configure(state="normal", text=self._check_button_label())
        self.mode_tabs.configure(state="normal")
        self.result_status.configure(text="Status: Cancelled.", text_color=RED)

    def _worker(self, imeis: list[str], check_type: str) -> None:
        succeeded = 0
        errors: list[str] = []
        unpaid: list[str] = []
        try:
            results = self.service.check_imeis(imeis)
        except Exception as exc:
            errors = [f"{imei}: {exc}" for imei in imeis]
            self.after(0, self._finish_batch, 0, len(imeis), errors, unpaid)
            return
        for completed, (imei, result) in enumerate(zip(imeis, results), start=1):
            if self._cancel_requested:
                break
            try:
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
                if is_payable_unpaid(result.payment_state, result.taxation_status):
                    unpaid.append(imei)
                self.repository.add(CalculationRecord(
                    check_type=check_type, imei_or_app_id=imei,
                    brand=resolved_brand, model=resolved_model,
                    taxation_status=result.taxation_status, network_status=result.network_status,
                    check_message=json.dumps(details, ensure_ascii=False),
                ))
                succeeded += 1
                allocation_date = device_info.allocation_date if device_info and result.taxation_status else ""
                self.after(
                    0, self._append_result, imei, resolved_brand, resolved_model,
                    result.payment_state, result.block_state,
                    None, None,
                    result.taxation_status, result.network_status, allocation_date, details,
                )
            except Exception as exc:
                errors.append(f"{imei}: {exc}")
            self.after(0, self.check_button.configure, {"text": f"Checking {completed}/{len(imeis)}…"})
        self.after(0, self._finish_batch, succeeded, len(imeis), errors, unpaid)

    def _app_id_worker(self, app_ids: list[str]) -> None:
        succeeded = 0
        errors: list[str] = []
        for completed, app_id in enumerate(app_ids, start=1):
            if self._cancel_requested:
                break
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
                date_parts = []
                if status.confirmed_at:
                    date_parts.append(f"Confirmed: {format_ceir_datetime(status.confirmed_at)}")
                if status.payment_at:
                    date_parts.append(f"Paid: {format_ceir_datetime(status.payment_at)}")
                self.after(
                    0, self._append_result, status.declaration_id, status.brand, status.model,
                    status.business_state, "", status.base_price, status.total_tax, status.taxation_status,
                    None, "\n".join(date_parts), status.raw,
                )
            except Exception as exc:
                errors.append(f"{app_id}: {exc}")
            self.after(0, self.check_button.configure, {"text": f"Checking {completed}/{len(app_ids)}…"})
        self.after(0, self._finish_batch, succeeded, len(app_ids), errors, [])

    def _paytax_worker(self, imeis: list[str], applicant: dict) -> None:
        if self._cancel_requested:
            return
        try:
            if len(imeis) == 2:
                self.after(
                    0, self.result_status.configure,
                    {"text": "Status: Verifying both IMEIs are the same device…", "text_color": AMBER},
                )
                if not self.service.are_same_device(imeis):
                    self.after(
                        0, self._finish_paytax, None,
                        "The two IMEIs do not belong to the same device. CEIR registration was not submitted.",
                    )
                    return
                if self._cancel_requested:
                    return
                self.after(
                    0, self.result_status.configure,
                    {"text": "Status: Same device confirmed. Creating declaration…", "text_color": GREEN},
                )
            device_info = []
            for imei in imeis:
                try:
                    device_info.append(self.service.get_device_info(imei))
                except Exception:
                    continue
            brands = list(dict.fromkeys(info.brand for info in device_info if info.brand))
            models = list(dict.fromkeys(info.model for info in device_info if info.model))
            quote = self.service.create_registration_request([imeis], applicant)
            self.repository.add(CalculationRecord(
                check_type="REGISTRATION REQUEST", imei_or_app_id=quote.declaration_id,
                brand=" / ".join(brands), model=" / ".join(models),
                customs_duty=quote.customs_duty, commercial_tax=quote.commercial_tax,
                redemption_fee=quote.redemption_fee, income_tax=quote.income_tax,
                total_tax=quote.total_tax, taxation_status=False, network_status=None,
                check_message=json.dumps({
                    "imeis": imeis, "device_info": [info.raw for info in device_info],
                    "response": quote.raw,
                }, ensure_ascii=False),
            ))
        except Exception as exc:
            self.after(0, self._finish_paytax, None, str(exc))
            return
        self.after(0, self._finish_paytax, quote, "")

    def _finish_paytax(self, quote: RegistrationTaxQuote | None, error: str) -> None:
        self.check_button.configure(state="normal", text=self._check_button_label())
        self.mode_tabs.configure(state="normal")
        if quote is None:
            self.result_status.configure(text="Registration failed", text_color=RED)
            self.note.configure(text=error, text_color=RED)
            messagebox.showerror("CEIR registration failed", error, parent=self)
            return
        details = {**quote.raw, "applicant": self.repository.get_applicant_profile().to_api_payload()}
        registry = details.get("Registry")
        if isinstance(registry, dict):
            registry.setdefault("applicant", details["applicant"])
            registry.setdefault("devices", [{"brand": "", "model": "", "imeis": self._parse_current_imeis_for_report()}])
        self._append_result(
            quote.declaration_id, "", "", "UNPAID", "", None, quote.total_tax,
            False, None, "Ready for IRD payment", details,
        )
        self.result_status.configure(text="Declaration created successfully", text_color=GREEN)
        self.note.configure(text=f"App ID {quote.declaration_id} is ready for payment.", text_color=GREEN)
        self.on_saved()
        self._show_registration_quote(quote)

    def _parse_current_imeis_for_report(self) -> list[str]:
        try:
            return parse_imei_list(self._current_input_text())
        except ValueError:
            return []

    def _set_results(self, _text: str = "") -> None:
        self.live_results = []
        self.result_page = 1
        self._render_result_page()

    def _render_result_page(self) -> None:
        total = len(self.live_results)
        total_pages = max(1, math.ceil(total / self.result_page_size))
        self.result_page = max(1, min(self.result_page, total_pages))
        start = (self.result_page - 1) * self.result_page_size
        self.results_grid.render(self.live_results[start:start + self.result_page_size])
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

    def _on_results_canvas_configure(self, event: tk.Event) -> None:
        # Stretch the table to the canvas width when there's room to spare, but
        # never below its natural minimum - that's what triggers the horizontal
        # scrollbar instead of squishing/clipping columns on a small window.
        min_width = sum(LiveResultsGrid.MIN_WIDTHS)
        width = max(int(event.width), min_width)
        self.results_canvas.itemconfigure(self.results_grid_window, width=width)
        self._resize_result_page(event)

    def _append_result(
        self, identifier: str, brand: str, model: str, payment: str, block: str,
        base_price: int | None, total_tax: int | None,
        taxation_good: bool | None, network_good: bool | None,
        extra_text: str = "",
        details: dict | None = None,
    ) -> None:
        self.live_results.append({
            "identifier": identifier,
            "device": " ".join(part for part in (brand, model) if part),
            "taxation_text": payment, "network_text": block,
            "base_text": format_mmk(base_price), "tax_text": format_mmk(total_tax),
            "taxation_good": taxation_good, "network_good": network_good,
            "extra_text": extra_text,
            "details": details or {},
        })
        self.result_page = max(1, math.ceil(len(self.live_results) / self.result_page_size))
        self._render_result_page()

    def _append_error(self, error: str) -> None:
        parts = error.split(":", 1)
        self.live_results.append({
            "identifier": parts[0], "device": "",
            "taxation_text": "ERROR", "network_text": parts[1].strip() if len(parts) > 1 else error,
            "base_text": "", "tax_text": "", "extra_text": "",
            "taxation_good": False, "network_good": False,
        })
        self.result_page = max(1, math.ceil(len(self.live_results) / self.result_page_size))
        self._render_result_page()

    def _show_error(self, detail: str) -> None:
        self.check_button.configure(state="normal", text=self._check_button_label())
        self.mode_tabs.configure(state="normal")
        self.result_status.configure(text="Check failed", text_color=RED)
        self.note.configure(text=detail)

    def _finish_batch(self, succeeded: int, total: int, errors: list[str], unpaid: list[str]) -> None:
        if self._cancel_requested:
            return
        self.check_button.configure(state="normal", text=self._check_button_label())
        self.mode_tabs.configure(state="normal")
        failed = total - succeeded
        self.result_status.configure(
            text=f"Status: Check Complete. {succeeded} succeeded, {failed} failed.",
            text_color=GREEN if failed == 0 else AMBER,
        )
        if errors:
            for error in errors:
                self._append_error(error)
            self.failed_identifiers = [error.split(":", 1)[0] for error in errors]
            self.retry_button.configure(text=f"↻ Retry Failed ({len(self.failed_identifiers)})", state="normal")
        else:
            self.failed_identifiers = []
            self.retry_button.configure(text="↻ Retry Failed", state="disabled")
        self.unpaid_imeis = unpaid
        if self.current_input_mode == "IMEI CHECK" and self.tax_paid_first.get():
            self.live_results.sort(key=lambda item: item.get("taxation_good") is not True)
            self._render_result_page()
        if unpaid:
            self.official_tax_button.configure(text=f"Pay Tax ({len(unpaid)})  →", state="normal")
            self.quick_paytax_button.configure(
                text="Pay Tax →" if len(unpaid) == 1 else f"Choose IMEI & Pay Tax ({len(unpaid)}) →"
            )
            self.quick_paytax_button.grid()
        else:
            self.official_tax_button.configure(text="Pay Tax  →", state="disabled")
            self.quick_paytax_button.grid_remove()
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
        "REGISTRATION REQUEST": "#7C3AED",
    }

    def __init__(self, master: tk.Misc, on_double_click: Callable[[], None]) -> None:
        super().__init__(master, bd=0, highlightthickness=0)
        self.on_double_click = on_double_click
        self.selected_record_id: int | None = None
        self.row_widgets: dict[int, list[tk.Label]] = {}
        self.current_rows: list[dict] = []
        self.current_page = 1
        self.current_page_size = PAGE_SIZE
        self._filler_row = 1
        self.dark = False
        for column, width in enumerate(self.MIN_WIDTHS):
            self.grid_columnconfigure(column, weight=1 if column in {2, 4, 5, 8, 9} else 0, minsize=width)

    def configure_theme(self, dark: bool) -> None:
        self.dark = dark
        self.render(self.current_rows, self.current_page, self.current_page_size)

    def pagination_metrics(self) -> tuple[int, int]:
        """Return actual rendered header/typical-row heights in Tk pixels."""
        self.update_idletasks()
        header_heights = [
            widget.winfo_reqheight()
            for widget in self.winfo_children()
            if int(widget.grid_info().get("row", -1)) == 0
        ]
        row_heights = sorted(
            widgets[0].winfo_reqheight() for widgets in self.row_widgets.values() if widgets
        )
        header_height = max(header_heights, default=TABLE_HEADER_HEIGHT)
        row_height = row_heights[len(row_heights) // 2] if row_heights else TABLE_ROW_HEIGHT
        return max(1, header_height), max(1, row_height)

    def render(self, rows: list[dict], page: int, page_size: int) -> None:
        self.current_rows = rows
        self.current_page = page
        self.current_page_size = page_size
        self.selected_record_id = None
        self.row_widgets.clear()
        self.grid_rowconfigure(self._filler_row, weight=0)
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
        # Any space left after the last complete row is kept below the table;
        # no data row is stretched into a tall strip.
        self._filler_row = len(rows) + 1
        self.grid_rowconfigure(self._filler_row, weight=1)

    def _render_row(self, grid_row: int, record: dict, border: str) -> None:
        row_background = ("#152238" if grid_row % 2 == 0 else "#111C2E") if self.dark else ("#F5F5F5" if grid_row % 2 == 0 else "#FFFFFF")
        normal_foreground = "#E5E7EB" if self.dark else "#374151"
        taxation = record["taxation_status"]
        network = record["network_status"]
        registration_imeis, brand, model = registration_history_metadata(record)
        identifier = str(record["imei_or_app_id"] or "")
        if registration_imeis:
            identifier = "\n".join((identifier, *registration_imeis))
        values = (
            (self.current_page - 1) * self.current_page_size + grid_row,
            record["id"], record["date_time"], record["check_type"], identifier,
            " ".join(part for part in (brand, model) if part),
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
            anchor = "e" if column in {8, 9} else "w" if column in {4, 5} else "center"
            cell = tk.Label(
                self, text=value, bg=row_background, fg=foreground, anchor=anchor,
                justify="left", wraplength=245 if column in {4, 5} else 0,
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
        self.page_size = PAGE_SIZE
        self.total = 0
        self._resize_after_id: str | None = None
        toolbar = ctk.CTkFrame(self, corner_radius=8, fg_color=("#FFFFFF", "#111C2E"), border_width=1, border_color=("#D8DEE8", "#263449"))
        toolbar.grid(row=2, column=0, padx=8, pady=(10, 5), sticky="ew")
        toolbar.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(toolbar, text="← Back", width=82, height=40, fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"), hover_color=("#D8E2F0", "#475569"), command=self.on_back).grid(row=0, column=0, padx=(12, 6), pady=10)
        ctk.CTkLabel(
            toolbar, text="⌕  Search:",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=1, padx=(4, 8), pady=12)
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Filter by IMEI, Brand, Model, Date, Hash…", height=40, font=ctk.CTkFont(size=13))
        self.search.grid(row=0, column=2, padx=(0, 14), pady=10, sticky="ew")
        self.search.bind("<KeyRelease>", lambda _event: self.reset_page())
        ctk.CTkLabel(
            toolbar, text="◇  Type:",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=3, padx=(0, 7), pady=12)
        self.type_filter = ctk.CTkOptionMenu(toolbar, values=["ALL", *CHECK_TYPES], width=205, height=40, command=lambda _value: self.reset_page())
        self.type_filter.grid(row=0, column=4, padx=(0, 10), pady=10)
        ctk.CTkButton(
            toolbar, text="⇩ Export CSV",
            width=132, height=40, fg_color=("#E8EEF7", "#334155"),
            text_color=("#1E293B", "#F8FAFC"), hover_color=("#D8E2F0", "#475569"), command=self.export,
        ).grid(row=0, column=5, padx=4, pady=10)
        ctk.CTkButton(
            toolbar, text="× Clear History",
            width=142, height=40, fg_color=RED, hover_color="#B91C1C", command=self.clear,
        ).grid(row=0, column=6, padx=(4, 14), pady=10)
        table_frame = ctk.CTkFrame(self, corner_radius=5, border_width=1, border_color=("#D1D7E0", "#263449"))
        table_frame.grid(row=3, column=0, padx=8, pady=3, sticky="nsew")
        self.grid_rowconfigure(3, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)
        self.table = HistoryGrid(table_frame, self.open_detail)
        self.table.grid(row=0, column=0, sticky="nsew")
        table_frame.bind("<Configure>", self._schedule_page_resize)
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
        rows, self.total = self.repository.list_filtered(
            self.search.get(), self.type_filter.get(), self.page, self.page_size
        )
        had_rendered_rows = bool(self.table.current_rows)
        self.table.render(rows, self.page, self.page_size)
        pages = max(1, math.ceil(self.total / self.page_size))
        if self.page > pages:
            self.page = pages
            self.refresh()
            return
        self.page_label.configure(text=f"Page {self.page} of {pages} (Total Records: {self.total})")
        self.prev.configure(state="normal" if self.page > 1 else "disabled")
        self.next.configure(state="normal" if self.page < pages else "disabled")
        # Re-measure after data is rendered too: an initially empty table has
        # no row from which Tk can report the platform's real row height.
        if rows and not had_rendered_rows:
            self._queue_page_resize(int(self.table.master.winfo_height()))

    def _schedule_page_resize(self, event: tk.Event) -> None:
        """Debounce geometry events before recalculating the history page size."""
        self._queue_page_resize(int(event.height))

    def _queue_page_resize(self, height: int) -> None:
        if height < TABLE_HEADER_HEIGHT + TABLE_ROW_HEIGHT * 2:
            return
        if self._resize_after_id is not None:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(100, lambda: self._resize_page_to_height(height))

    def _resize_page_to_height(self, height: int) -> None:
        self._resize_after_id = None
        header_height, row_height = self.table.pagination_metrics()
        available_rows = max(1, (height - header_height) // row_height)
        if available_rows == self.page_size:
            return
        # Keep the previously visible first record on screen when resizing.
        first_record_index = (self.page - 1) * self.page_size
        self.page_size = available_rows
        self.page = first_record_index // self.page_size + 1
        self.refresh()

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
        registration_imeis, registration_brand, registration_model = registration_history_metadata(record)
        record = dict(record)
        if registration_imeis:
            record["registration_imeis"] = "\n".join(registration_imeis)
        if registration_brand:
            record["brand"] = registration_brand
        if registration_model:
            record["model"] = registration_model
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Calculation #{record_id}")
        dialog.geometry("570x610")
        dialog.transient(self.winfo_toplevel())
        box = ctk.CTkTextbox(dialog, wrap="word", font=("Segoe UI", NATIVE_TEXT_FONT_SIZE))
        box.pack(fill="both", expand=True, padx=18, pady=18)
        labels = {
            "id": "ID", "date_time": "Date Time", "check_type": "Type", "imei_or_app_id": "IMEI / App ID",
            "registration_imeis": "Registration IMEIs",
            "brand": "Brand", "model": "Model", "base_price": "Base Price", "customs_duty": "Customs Duty",
            "commercial_tax": "Commercial Tax", "redemption_fee": "Redemption Fee", "income_tax": "Income Tax",
            "total_tax": "Total Tax", "taxation_status": "Taxation", "network_status": "Network", "check_message": "CEIR Details",
        }
        money = {"base_price", "customs_duty", "commercial_tax", "redemption_fee", "income_tax", "total_tax"}
        for key, label in labels.items():
            if key == "registration_imeis" and not registration_imeis:
                continue
            value = record.get(key)
            if key in money:
                value = format_mmk(value)
            elif key in {"taxation_status", "network_status"}:
                value = "Not applicable" if value is None else ("Passed" if value else "Failed")
            box.insert("end", f"{label}\n{value or '—'}\n\n")
        box.configure(state="disabled")


class SettingsView(Page):
    APPLICANT_FIELDS = (
        ("full_name", "Full Name"),
        ("national_id", "National ID"),
        ("birthday", "Birthday (YYYY-MM-DD)"),
        ("phone", "Phone"),
        ("email", "Email"),
        ("address", "Address"),
        ("tax_office_division", "Tax Office Division"),
        ("tax_office_code", "Tax Office Code"),
        ("region_code", "Region Code"),
        ("township_code", "Township Code"),
        ("tin", "TIN"),
        ("uin", "UIN"),
    )

    def __init__(
        self,
        master: ctk.CTkFrame,
        repository: CalculationRepository,
        on_changed: Callable[[], None],
        on_back: Callable[[], None],
    ) -> None:
        super().__init__(master, "Tax Settings", "Adjust percentage rates used for new calculations.")
        self.repository = repository
        self.on_changed = on_changed
        self.on_back = on_back
        ctk.CTkButton(
            self, text="← Back to CEIR Workflows", width=190, height=38,
            fg_color=("#E8EEF7", "#334155"), text_color=("#1E293B", "#F8FAFC"),
            hover_color=("#D8E2F0", "#475569"), command=self.on_back,
        ).grid(row=0, column=0, padx=30, pady=(22, 0), sticky="e")
        self.grid_rowconfigure(3, weight=1)
        panel = ctk.CTkFrame(self)
        panel.grid(row=2, column=0, padx=30, pady=(24, 12), sticky="new")
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

        applicant_panel = ctk.CTkFrame(self)
        applicant_panel.grid(row=3, column=0, padx=30, pady=(0, 24), sticky="nsew")
        applicant_panel.grid_columnconfigure(0, weight=1)
        applicant_panel.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(
            applicant_panel, text="Applicant Details (for Official CEIR Tax Registration)",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(20, 2), sticky="w")
        ctk.CTkLabel(
            applicant_panel,
            text=(
                "Used by the PayTax workflow after opening an unpaid IMEI from the Check page. "
                "START CHECK submits a real registration to CEIR under this identity."
            ),
            text_color=("#64748B", "#94A3B8"), wraplength=560, justify="left",
        ).grid(row=1, column=0, padx=24, pady=(0, 10), sticky="w")
        applicant_fields = ctk.CTkScrollableFrame(applicant_panel, fg_color="transparent", height=220)
        applicant_fields.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="nsew")
        applicant_fields.grid_columnconfigure(1, weight=1)
        self.applicant_variables: dict[str, tk.StringVar] = {}
        for row, (key, label) in enumerate(self.APPLICANT_FIELDS):
            ctk.CTkLabel(applicant_fields, text=label, font=ctk.CTkFont(size=12, weight="bold")).grid(
                row=row, column=0, padx=(12, 8), pady=8, sticky="w"
            )
            variable = tk.StringVar()
            self.applicant_variables[key] = variable
            ctk.CTkEntry(applicant_fields, textvariable=variable, height=34).grid(
                row=row, column=1, padx=(0, 12), pady=8, sticky="ew"
            )
        taxpayer_row = len(self.APPLICANT_FIELDS)
        ctk.CTkLabel(applicant_fields, text="Taxpayer Type", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=taxpayer_row, column=0, padx=(12, 8), pady=8, sticky="w"
        )
        self.applicant_taxpayer_type = ctk.CTkOptionMenu(applicant_fields, values=["Individual", "Corporate"], height=34)
        self.applicant_taxpayer_type.grid(row=taxpayer_row, column=1, padx=(0, 12), pady=8, sticky="ew")
        self.applicant_is_foreigner = tk.BooleanVar()
        ctk.CTkSwitch(applicant_fields, text="Is Foreigner", variable=self.applicant_is_foreigner).grid(
            row=taxpayer_row + 1, column=0, columnspan=2, padx=12, pady=8, sticky="w"
        )
        applicant_actions = ctk.CTkFrame(applicant_panel, fg_color="transparent")
        applicant_actions.grid(row=3, column=0, padx=24, pady=(4, 20), sticky="ew")
        ctk.CTkButton(applicant_actions, text="Save Applicant Details", fg_color=BLUE, command=self.save_applicant).pack(fill="x")

        self.load()
        self.load_applicant()

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

    def load_applicant(self) -> None:
        profile = self.repository.get_applicant_profile()
        for key, variable in self.applicant_variables.items():
            variable.set(getattr(profile, key))
        self.applicant_taxpayer_type.set(profile.taxpayer_type or "Individual")
        self.applicant_is_foreigner.set(profile.is_foreigner)

    def save_applicant(self) -> None:
        profile = ApplicantProfile(
            taxpayer_type=self.applicant_taxpayer_type.get(),
            is_foreigner=self.applicant_is_foreigner.get(),
            **{key: variable.get().strip() for key, variable in self.applicant_variables.items()},
        )
        self.repository.save_applicant_profile(profile)
        messagebox.showinfo("Applicant Details", "Applicant details were saved.", parent=self)
