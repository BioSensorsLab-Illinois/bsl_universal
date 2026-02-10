from __future__ import annotations

"""
Device monitor GUI launcher and standalone app.

The launcher uses a subprocess so Tk runs on the subprocess main thread,
avoiding host-process instability on macOS.
"""

import subprocess
import sys
import json
from pathlib import Path
from typing import Optional

from loguru import logger

from .device_health import DeviceStatus, device_health_hub

_MONITOR_PROCESS: Optional[subprocess.Popen] = None


def start_device_monitor_window() -> bool:
    """
    Start the device monitor GUI in a subprocess.

    Returns
    -------
    bool
        True when launch succeeded or window is already running.
    """
    global _MONITOR_PROCESS
    if _MONITOR_PROCESS is not None and _MONITOR_PROCESS.poll() is None:
        return True
    try:
        _MONITOR_PROCESS = subprocess.Popen(
            [sys.executable, "-m", "bsl_universal.core.device_monitor_gui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        logger.warning("Unable to launch monitor GUI subprocess: {}", exc)
        return False


def run_device_monitor_app() -> None:
    """
    Run monitor GUI event loop in the current process.

    Returns
    -------
    None
    """
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk
    except Exception as exc:  # pragma: no cover
        logger.warning("Tkinter is unavailable; monitor GUI cannot start: {}", exc)
        return

    root = tk.Tk()
    root.title("BSL Device Monitor")
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    win_w = max(1040, min(1540, int(screen_w * 0.88)))
    win_h = max(700, min(1020, int(screen_h * 0.88)))
    win_x = max(0, (screen_w - win_w) // 2)
    win_y = max(0, (screen_h - win_h) // 4)
    root.geometry(f"{win_w}x{win_h}+{win_x}+{win_y}")
    root.minsize(980, 620)
    root.configure(background="#E9EEF2")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("Card.TFrame", background="#FFFFFF")
    style.configure("Header.TLabel", background="#E9EEF2", foreground="#18354A", font=("Helvetica", 12, "bold"))
    style.configure("Title.TLabel", background="#E9EEF2", foreground="#0B2438", font=("Helvetica", 16, "bold"))
    style.configure("Body.TLabel", background="#FFFFFF", foreground="#1F2A33", font=("Helvetica", 10))
    style.configure("Status.TLabel", background="#E9EEF2", foreground="#0B2438", font=("Helvetica", 10))
    style.configure("Accent.TButton", font=("Helvetica", 10, "bold"))

    status_palette = {
        "CONNECTING": ("#DCEEFF", "#0C4A7A"),
        "CONNECTED": ("#DCF8E8", "#11663A"),
        "DISCONNECTED": ("#E5E8EC", "#4A5561"),
        "WARNING": ("#FFF5D9", "#8A5A0A"),
        "UNRECOVERABLE_FAILURE": ("#FDE3E5", "#8E1327"),
        "STALE_SESSION": ("#F7E5FF", "#5A2478"),
    }

    top = ttk.Frame(root, padding=(12, 10, 12, 0), style="Card.TFrame")
    top.pack(fill="x")

    title_row = ttk.Frame(top, style="Card.TFrame")
    title_row.pack(fill="x", pady=(0, 8))
    ttk.Label(title_row, text="Connected Device Monitor", style="Title.TLabel").pack(side="left")

    status_message = tk.StringVar(value="Monitor ready.")
    ttk.Label(title_row, textvariable=status_message, style="Status.TLabel").pack(side="right")

    summary = ttk.Frame(top, style="Card.TFrame")
    summary.pack(fill="x", pady=(0, 8))

    summary_widgets: dict[str, tk.Label] = {}
    for col, key in enumerate(
        ("CONNECTING", "CONNECTED", "WARNING", "UNRECOVERABLE_FAILURE", "STALE_SESSION", "DISCONNECTED")
    ):
        bg, fg = status_palette[key]
        card = tk.Frame(summary, bg=bg, bd=0, highlightthickness=1, highlightbackground="#D0D7DE")
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0), pady=0)
        summary.grid_columnconfigure(col, weight=1)

        tk.Label(card, text=key.replace("_", " "), bg=bg, fg=fg, font=("Helvetica", 9, "bold")).pack(
            anchor="w", padx=10, pady=(8, 1)
        )
        count_label = tk.Label(card, text="0", bg=bg, fg=fg, font=("Helvetica", 18, "bold"))
        count_label.pack(anchor="w", padx=10, pady=(0, 8))
        summary_widgets[key] = count_label

    controls = ttk.Frame(top, style="Card.TFrame")
    controls.pack(fill="x")

    search_var = tk.StringVar(value="")
    active_only_var = tk.BooleanVar(value=False)
    auto_refresh_var = tk.BooleanVar(value=True)
    refresh_interval_ms = 600
    refresh_job_id: str | None = None

    ttk.Label(controls, text="Filter", style="Header.TLabel").grid(row=0, column=0, sticky="w")
    filter_entry = ttk.Entry(controls, textvariable=search_var, width=26)
    filter_entry.grid(row=0, column=1, padx=(6, 12), sticky="w")

    ttk.Checkbutton(controls, text="Show only active", variable=active_only_var).grid(row=0, column=2, padx=(0, 12), sticky="w")
    ttk.Checkbutton(controls, text="Auto refresh", variable=auto_refresh_var).grid(row=0, column=3, padx=(0, 12), sticky="w")

    controls.grid_columnconfigure(6, weight=1)

    content = ttk.Frame(root, padding=12)
    content.pack(fill="both", expand=True)

    tree_card = ttk.Frame(content, style="Card.TFrame")
    tree_card.pack(fill="both", expand=True)

    columns = ("model", "type", "sn", "status", "updated", "owner", "error")
    tree = ttk.Treeview(tree_card, columns=columns, show="headings", height=14)
    tree.heading("model", text="Model / Nickname")
    tree.heading("type", text="Type")
    tree.heading("sn", text="S/N")
    tree.heading("status", text="Status")
    tree.heading("updated", text="Updated (UTC)")
    tree.heading("owner", text="Owner PID")
    tree.heading("error", text="Last Error")

    tree.column("model", width=190, anchor="w")
    tree.column("type", width=170, anchor="w")
    tree.column("sn", width=150, anchor="w")
    tree.column("status", width=170, anchor="center")
    tree.column("updated", width=210, anchor="w")
    tree.column("owner", width=90, anchor="center")
    tree.column("error", width=260, anchor="w")

    for status, (bg, fg) in status_palette.items():
        tree.tag_configure(status, background=bg, foreground=fg)

    tree_scroll_y = ttk.Scrollbar(tree_card, orient="vertical", command=tree.yview)
    tree_scroll_x = ttk.Scrollbar(tree_card, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

    tree.grid(row=0, column=0, sticky="nsew")
    tree_scroll_y.grid(row=0, column=1, sticky="ns")
    tree_scroll_x.grid(row=1, column=0, sticky="ew")
    tree_card.grid_rowconfigure(0, weight=1)
    tree_card.grid_columnconfigure(0, weight=1)

    actions = ttk.Frame(content, style="Card.TFrame", padding=(0, 10, 0, 8))
    actions.pack(fill="x")

    def _set_status(msg: str) -> None:
        status_message.set(msg)

    def _clear_tree() -> None:
        for row_id in tree.get_children():
            tree.delete(row_id)

    def _match_filter(item: DeviceStatus) -> bool:
        pattern = search_var.get().strip().lower()
        if not pattern:
            return True
        haystack = " ".join(
            [
                str(item.model),
                str(item.device_type),
                str(item.serial_number),
                str(item.status),
                str(item.last_error),
            ]
        ).lower()
        return pattern in haystack

    def _refresh_snapshot(*, manual: bool = False) -> None:
        nonlocal refresh_job_id
        try:
            device_health_hub.reconcile_stale_entries()
            snapshot = sorted(device_health_hub.get_snapshot_from_file(), key=lambda x: x.key)
        except Exception as exc:
            _set_status(f"Snapshot refresh failed: {exc}")
            if auto_refresh_var.get():
                refresh_job_id = root.after(refresh_interval_ms, _refresh_snapshot)
            return

        _clear_tree()
        counts = {
            "CONNECTING": 0,
            "CONNECTED": 0,
            "WARNING": 0,
            "UNRECOVERABLE_FAILURE": 0,
            "STALE_SESSION": 0,
            "DISCONNECTED": 0,
        }

        active_states = {"CONNECTING", "CONNECTED", "WARNING", "UNRECOVERABLE_FAILURE"}

        visible_rows = 0
        for item in snapshot:
            status_key = item.status.upper()
            if status_key in counts:
                counts[status_key] += 1

            if active_only_var.get() and status_key not in active_states:
                continue
            if not _match_filter(item):
                continue

            visible_rows += 1
            tree.insert(
                "",
                "end",
                values=(
                    item.model,
                    item.device_type,
                    item.serial_number,
                    item.status,
                    item.updated_at,
                    item.process_id or "-",
                    item.last_error,
                ),
                tags=(status_key,),
            )

        for key, label in summary_widgets.items():
            label.configure(text=str(counts.get(key, 0)))

        if manual:
            _set_status(f"Refreshed {visible_rows} visible row(s).")

        if refresh_job_id is not None:
            try:
                root.after_cancel(refresh_job_id)
            except Exception:
                pass
            refresh_job_id = None
        if auto_refresh_var.get():
            refresh_job_id = root.after(refresh_interval_ms, _refresh_snapshot)

    def _clear_disconnected_stale() -> None:
        removed = device_health_hub.clear_entries(statuses=("DISCONNECTED", "STALE_SESSION"))
        _set_status(f"Removed {removed} disconnected/stale row(s).")
        _refresh_snapshot(manual=False)

    def _clear_failures() -> None:
        removed = device_health_hub.clear_entries(statuses=("WARNING", "UNRECOVERABLE_FAILURE"))
        _set_status(f"Removed {removed} warning/failure row(s).")
        _refresh_snapshot(manual=False)

    def _clear_all() -> None:
        removed = device_health_hub.clear_entries(statuses=None)
        _set_status(f"Removed {removed} row(s).")
        _refresh_snapshot(manual=False)

    ttk.Button(actions, text="Refresh", style="Accent.TButton", command=lambda: _refresh_snapshot(manual=True)).pack(
        side="left"
    )
    ttk.Button(actions, text="Clear Disconnected/Stale", command=_clear_disconnected_stale).pack(side="left", padx=(8, 0))
    ttk.Button(actions, text="Clear Warnings/Failures", command=_clear_failures).pack(side="left", padx=(8, 0))
    ttk.Button(actions, text="Clear All", command=_clear_all).pack(side="left", padx=(8, 0))

    email_card = ttk.LabelFrame(content, text="Device Email Alerts", padding=10)
    email_card.pack(fill="x", pady=(2, 0))

    email_cfg = device_health_hub.get_email_config()

    enabled_var = tk.BooleanVar(value=email_cfg.enabled)
    sender_var = tk.StringVar(value=email_cfg.sender_email or "students@bsl-uiuc.com")
    recipient_var = tk.StringVar(value=email_cfg.recipient_email)
    default_secret_path = device_health_hub.get_default_oauth_client_secret_file()
    client_secret_var = tk.StringVar(value=email_cfg.oauth_client_secrets_file or default_secret_path)
    token_file_var = tk.StringVar(value=email_cfg.oauth_token_file)
    supported_alert_categories = list(device_health_hub.get_supported_alert_categories())
    default_categories_raw = getattr(email_cfg, "default_categories", ["UNRECOVERABLE_FAILURE"])
    default_categories = {
        str(cat).strip().upper()
        for cat in default_categories_raw
        if isinstance(cat, str) and str(cat).strip()
    }
    default_category_vars = {
        cat: tk.BooleanVar(value=(cat in default_categories))
        for cat in supported_alert_categories
    }
    matrix_overrides: dict[str, list[str]] = {}
    raw_matrix = getattr(email_cfg, "instrument_category_matrix", {})
    if isinstance(raw_matrix, dict):
        for raw_instrument, raw_categories in raw_matrix.items():
            instrument = str(raw_instrument).strip()
            if not instrument:
                continue
            if isinstance(raw_categories, (list, tuple, set)):
                matrix_overrides[instrument] = [
                    cat
                    for cat in (
                        str(item).strip().upper()
                        for item in raw_categories
                        if isinstance(item, str) and str(item).strip()
                    )
                    if cat in supported_alert_categories
                ]
            else:
                matrix_overrides[instrument] = []
    alert_policy_var = tk.StringVar(value="")
    oauth_status_var = tk.StringVar(value="")
    advanced_status_var = tk.StringVar(value="")

    header = ttk.Frame(email_card)
    header.pack(fill="x", pady=(0, 6))

    ttk.Checkbutton(
        header,
        text="Enable alert emails",
        variable=enabled_var,
    ).pack(side="left")

    form = ttk.Frame(email_card, padding=8)
    form.pack(fill="x")

    ttk.Label(form, text="Recipient Email").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
    ttk.Entry(form, textvariable=recipient_var, width=42).grid(row=0, column=1, sticky="w", pady=(0, 4))

    ttk.Label(
        form,
        text=(
            "Default sender is students@bsl-uiuc.com. "
            "Use 'Alert Categories...' for category policy and Settings > Advanced for sender/OAuth/custom service."
        ),
        style="Status.TLabel",
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    ttk.Label(form, textvariable=alert_policy_var, style="Status.TLabel").grid(
        row=2, column=0, columnspan=3, sticky="w", pady=(4, 0)
    )

    def _refresh_oauth_status() -> None:
        token_path = Path(token_file_var.get().strip() or "").expanduser()
        if not token_path.exists():
            oauth_status_var.set("OAuth not authorized yet. Click 'Authorize Google Workspace'.")
            return
        try:
            token_payload = json.loads(token_path.read_text(encoding="utf-8"))
            scopes = token_payload.get("scopes", [])
            if isinstance(scopes, list):
                cleaned_scopes = {scope.strip() for scope in scopes if isinstance(scope, str) and scope.strip()}
            else:
                cleaned_scopes = set()
        except Exception:
            cleaned_scopes = set()

        if cleaned_scopes and "https://mail.google.com/" not in cleaned_scopes:
            if "https://www.googleapis.com/auth/gmail.send" in cleaned_scopes:
                oauth_status_var.set(
                    "OAuth token uses legacy gmail.send scope. Click 'Authorize Google Workspace' to upgrade."
                )
                return
            oauth_status_var.set(
                "OAuth token scope is incompatible with SMTP mode. Re-authorize Google Workspace."
            )
            return

        oauth_status_var.set(f"OAuth authorized: token found at {token_path}")

    def _default_categories_selected() -> list[str]:
        return [cat for cat in supported_alert_categories if default_category_vars[cat].get()]

    def _refresh_alert_policy_status() -> None:
        defaults = _default_categories_selected()
        default_text = ", ".join(defaults) if defaults else "none"
        alert_policy_var.set(
            f"Alert categories default: {default_text}. Matrix overrides: {len(matrix_overrides)} instrument(s)."
        )

    def _collect_matrix_instruments() -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()

        try:
            for item in device_health_hub.get_snapshot_from_file():
                status = str(getattr(item, "status", "")).strip().upper()
                if status != "CONNECTED":
                    continue
                token = str(getattr(item, "key", "")).split(":", 1)[0].strip()
                if token and token.lower() not in seen:
                    merged.append(token)
                    seen.add(token.lower())
        except Exception:
            pass
        return merged

    def _save_email_config() -> None:
        device_health_hub.set_email_config(
            enabled=enabled_var.get(),
            recipient_email=recipient_var.get().strip(),
            sender_email=sender_var.get().strip() or "students@bsl-uiuc.com",
            provider="gmail",
            oauth_client_secrets_file=client_secret_var.get().strip(),
            oauth_token_file=token_file_var.get().strip(),
            default_categories=_default_categories_selected(),
            instrument_category_matrix=matrix_overrides,
        )
        _set_status("Saved email alert configuration.")
        _refresh_alert_policy_status()
        _refresh_oauth_status()

    def _authorize_google() -> None:
        _save_email_config()
        ok, msg = device_health_hub.authorize_google_workspace(
            client_secrets_file=client_secret_var.get().strip() or None,
            sender_email=sender_var.get().strip() or "students@bsl-uiuc.com",
            recipient_email=recipient_var.get().strip(),
        )
        if ok:
            enabled_var.set(True)
            _set_status(msg)
            cfg = device_health_hub.get_email_config()
            token_file_var.set(cfg.oauth_token_file)
            _refresh_oauth_status()
        else:
            _set_status(msg)

    def _open_alert_category_matrix() -> None:
        popup = tk.Toplevel(root)
        popup.title("Email Alert Category Matrix")
        popup.transient(root)
        popup.geometry("980x620")
        popup.minsize(860, 520)
        popup.resizable(True, True)

        outer = ttk.Frame(popup, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Default Categories (applies to all instruments unless overridden)",
            style="Header.TLabel",
        ).pack(anchor="w")

        defaults_row = ttk.Frame(outer)
        defaults_row.pack(fill="x", pady=(6, 10))

        local_default_vars = {
            cat: tk.BooleanVar(value=default_category_vars[cat].get())
            for cat in supported_alert_categories
        }
        for col, category in enumerate(supported_alert_categories):
            ttk.Checkbutton(defaults_row, text=category, variable=local_default_vars[category]).grid(
                row=0, column=col, sticky="w", padx=(0, 10)
            )

        ttk.Label(
            outer,
            text="Per-Instrument Override Matrix (when override is disabled, defaults are used)",
            style="Header.TLabel",
        ).pack(anchor="w")

        matrix_card = ttk.Frame(outer)
        matrix_card.pack(fill="both", expand=True, pady=(6, 0))

        canvas = tk.Canvas(matrix_card, highlightthickness=0, background="#FFFFFF")
        scroll_y = ttk.Scrollbar(matrix_card, orient="vertical", command=canvas.yview)
        scroll_x = ttk.Scrollbar(matrix_card, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        matrix_card.grid_rowconfigure(0, weight=1)
        matrix_card.grid_columnconfigure(0, weight=1)

        matrix_frame = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=matrix_frame, anchor="nw")

        def _on_matrix_configure(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event) -> None:
            canvas.itemconfigure(canvas_window, width=event.width)

        matrix_frame.bind("<Configure>", _on_matrix_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        ttk.Label(matrix_frame, text="Instrument", style="Header.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        ttk.Label(matrix_frame, text="Override", style="Header.TLabel").grid(
            row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 6)
        )
        for col, category in enumerate(supported_alert_categories, start=2):
            ttk.Label(matrix_frame, text=category, style="Header.TLabel").grid(
                row=0,
                column=col,
                sticky="w",
                padx=(0, 8),
                pady=(0, 6),
            )

        local_rows: dict[str, tuple[tk.BooleanVar, dict[str, tk.BooleanVar], list[ttk.Checkbutton]]] = {}
        for row, instrument in enumerate(_collect_matrix_instruments(), start=1):
            categories = None
            for matrix_key, matrix_categories in matrix_overrides.items():
                if str(matrix_key).strip().lower() == str(instrument).strip().lower():
                    categories = list(matrix_categories)
                    break
            override_var = tk.BooleanVar(value=categories is not None)
            category_vars = {
                category: tk.BooleanVar(value=bool(categories is not None and category in categories))
                for category in supported_alert_categories
            }
            category_buttons: list[ttk.Checkbutton] = []

            ttk.Label(matrix_frame, text=instrument).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
            ttk.Checkbutton(matrix_frame, variable=override_var).grid(
                row=row, column=1, sticky="w", padx=(0, 8), pady=(0, 4)
            )

            for col, category in enumerate(supported_alert_categories, start=2):
                button = ttk.Checkbutton(matrix_frame, variable=category_vars[category])
                button.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=(0, 4))
                category_buttons.append(button)

            local_rows[instrument] = (override_var, category_vars, category_buttons)

        if not local_rows:
            ttk.Label(
                matrix_frame,
                text="No connected instruments found.",
                style="Status.TLabel",
            ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 4))

        def _sync_row_states() -> None:
            for override_var, _cat_vars, cat_buttons in local_rows.values():
                state = "normal" if override_var.get() else "disabled"
                for button in cat_buttons:
                    button.configure(state=state)

        for override_var, _cat_vars, _buttons in local_rows.values():
            override_var.trace_add("write", lambda *_args: _sync_row_states())

        _sync_row_states()

        popup_status = tk.StringVar(value="")
        ttk.Label(outer, textvariable=popup_status, style="Status.TLabel").pack(anchor="w", pady=(10, 0))

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(12, 0))

        def _save_matrix() -> None:
            for category in supported_alert_categories:
                default_category_vars[category].set(local_default_vars[category].get())
            matrix_overrides.clear()
            for instrument, (override_var, cat_vars, _buttons) in local_rows.items():
                if not override_var.get():
                    continue
                matrix_overrides[instrument] = [
                    category
                    for category in supported_alert_categories
                    if cat_vars[category].get()
                ]
            _save_email_config()
            popup_status.set("Alert category matrix saved.")

        ttk.Button(action_row, text="Save Matrix", style="Accent.TButton", command=_save_matrix).pack(side="left")
        ttk.Button(action_row, text="Close", command=popup.destroy).pack(side="left", padx=(8, 0))

    def _open_advanced_settings() -> None:
        advanced = tk.Toplevel(root)
        advanced.title("Advanced Settings")
        advanced.transient(root)
        advanced.geometry("840x360")
        advanced.minsize(760, 320)
        advanced.resizable(True, True)

        container = ttk.Frame(advanced, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Sender Workspace Email", style="Header.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4)
        )
        ttk.Entry(container, textvariable=sender_var, width=70).grid(
            row=0, column=1, sticky="ew", pady=(0, 4)
        )

        ttk.Label(
            container,
            text="OAuth Client Secret JSON",
            style="Header.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 4))
        ttk.Entry(container, textvariable=client_secret_var, width=70).grid(row=1, column=1, sticky="ew", pady=(10, 4))

        def _browse_client_secret() -> None:
            path = filedialog.askopenfilename(
                title="Select Google OAuth Client Secret",
                filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            )
            if path:
                client_secret_var.set(path)

        ttk.Button(container, text="Browse...", command=_browse_client_secret).grid(
            row=1,
            column=2,
            padx=(8, 0),
            sticky="w",
        )

        ttk.Label(container, text="Token File", style="Header.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 4)
        )
        ttk.Entry(container, textvariable=token_file_var, width=70).grid(
            row=2, column=1, sticky="ew", pady=(10, 4)
        )

        ttk.Label(
            container,
            text=f"Hardcoded default JSON: {default_secret_path}",
            style="Status.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        ttk.Label(container, textvariable=oauth_status_var, style="Status.TLabel").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        ttk.Label(container, textvariable=advanced_status_var, style="Status.TLabel").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        container.grid_columnconfigure(1, weight=1)

        button_row = ttk.Frame(container)
        button_row.grid(row=6, column=0, columnspan=3, sticky="e", pady=(14, 0))

        def _save_advanced() -> None:
            _save_email_config()
            advanced_status_var.set("Advanced settings saved.")

        ttk.Button(button_row, text="Save", style="Accent.TButton", command=_save_advanced).pack(side="left")
        ttk.Button(button_row, text="Close", command=advanced.destroy).pack(side="left", padx=(8, 0))

    menubar = tk.Menu(root)
    settings_menu = tk.Menu(menubar, tearoff=0)
    advanced_menu = tk.Menu(settings_menu, tearoff=0)
    advanced_menu.add_command(label="Alert Category Matrix...", command=_open_alert_category_matrix)
    advanced_menu.add_command(label="OAuth / Server JSON...", command=_open_advanced_settings)
    settings_menu.add_cascade(label="Advanced", menu=advanced_menu)
    menubar.add_cascade(label="Settings", menu=settings_menu)
    root.config(menu=menubar)

    def _send_test_email() -> None:
        _save_email_config()
        ok, msg = device_health_hub.send_test_email()
        _set_status(msg if ok else f"Test email failed: {msg}")

    email_buttons = ttk.Frame(email_card)
    email_buttons.pack(fill="x", pady=(8, 0))

    ttk.Button(email_buttons, text="Save Email Settings", style="Accent.TButton", command=_save_email_config).pack(
        side="left"
    )
    ttk.Button(email_buttons, text="Alert Categories...", command=_open_alert_category_matrix).pack(
        side="left", padx=(8, 0)
    )
    ttk.Button(email_buttons, text="Authorize Google Workspace", command=_authorize_google).pack(
        side="left", padx=(8, 0)
    )
    ttk.Button(email_buttons, text="Send Test Email", command=_send_test_email).pack(side="left", padx=(8, 0))

    auto_refresh_var.trace_add("write", lambda *_args: _refresh_snapshot(manual=False))

    filter_entry.bind("<KeyRelease>", lambda _evt: _refresh_snapshot(manual=False))

    _refresh_alert_policy_status()
    _refresh_oauth_status()
    _refresh_snapshot(manual=True)
    root.mainloop()


if __name__ == "__main__":
    run_device_monitor_app()
