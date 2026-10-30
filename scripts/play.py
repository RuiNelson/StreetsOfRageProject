#!/usr/bin/env python3
"""Configure and launch the Streets of Rage host (`sor`) and `autoplay`.

    ./scripts/play.py                        window: configure, then Ctrl+R launches both
    ./scripts/play.py --last                 launch the saved configuration, no window
    ./scripts/play.py --preset turbo         launch a preset, no window (for scripts and agents)
    ./scripts/play.py --preset boss --level 2 --agent-p2

The window remembers its settings in last_play_py_settings.yml (meta-repository
root, gitignored) and reads it back on the next launch. Presets given on the
command line start from the defaults, never from the saved file, and do not
overwrite it, so a scripted run is reproducible. Unknown options are handed to
autoplay as they are.

Standard library only; the window needs a Python with Tk (_tkinter).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from _common import META_ROOT, built_executable, find_tk_python, script_command
from _session import run_session


SETTINGS_PATH = META_ROOT / "last_play_py_settings.yml"
SOR_BUILD_DIR = META_ROOT / "StreetsOfRageRecompilation" / "build"
DEFAULT_ROM = META_ROOT / "StreetsOfRageRecompilation" / "rom" / "SOR.bin"

# Every setting, with its default. The type of the default is the type of the value.
DEFAULTS: dict[str, Any] = {
    # host (sor)
    "port": 6969,
    "turbo": 0,  # 0 = off; needs the internal timer (vsync 0)
    "vsync": 0,  # 0 internal timer, 1 VSync, 2 VSync/2, 3 VSync/3
    "lang": "en",  # "" = the host's own default
    "hz": 0,  # 0 = the host's own default
    "silent": False,
    "sound": "prerendered",  # or "emulated": sor --sound (ignored when silent)
    "soundtrack": "",  # "" = sor's default, soundtrack/ next to the ROM
    "fullscreen": False,
    "widescreen": False,
    "integer_scaling": False,  # --integerScaling, whole-number scale factors only
    "alt_controls": False,  # --altControls, the 6-button layout
    "debug_utils": True,  # remote access, hotkeys and cheats: always on when autoplay runs
    "debug": False,
    "call_log": "",
    "rom": "",
    # autoplay
    "agent_p1": False,
    "agent_p2": False,
    "reach": "",  # "" = stay in the menus
    "lockstep": False,
    "poll_ms": 0,  # 0 = auto: 32/turbo ms under turbo (16 at x2), autoplay's own default otherwise
    "hud_ms": 0,  # 0 = autoplay's own default
    "start_level": 0,  # 0 = none
    "sweep": "",  # "", "street", "mrx" or "only:<family>"
    "no_food": False,
    "no_police": False,
    "extra": "",  # more autoplay arguments, as typed
    # launcher
    "build_first": False,
}

# Fields a preset sets. The rest (widescreen, integer scaling, 6-button, fullscreen, ROM, sound source, soundtrack
# folder, call log, extra...) is the user's own and survives a preset.
SESSION_FIELDS = (
    "port", "turbo", "vsync", "lang", "debug_utils", "silent", "agent_p1", "agent_p2", "reach",
    "lockstep", "poll_ms", "start_level", "sweep", "no_food", "no_police",
)
_QUIET = dict(
    port=7777, turbo=0, vsync=0, lang="en", debug_utils=True, silent=True, agent_p1=True, agent_p2=False,
    reach="blaze", lockstep=False, poll_ms=0, start_level=0, sweep="", no_food=False, no_police=False,
)
PRESETS: dict[str, tuple[str, dict[str, Any]]] = {
    "turbo": ("Measured session: turbo x2, silent, poll 16 ms (was both_turbo)", {**_QUIET, "turbo": 2}),
    "watch": ("Normal speed with sound (was both_sound)", {**_QUIET, "silent": False}),
    "quiet": ("Normal speed, silent (was both)", {**_QUIET}),
    "lockstep": ("AI-clocked, frame-exact (was both_lockstep_speed)",
                 {**_QUIET, "port": 6767, "turbo": 10, "lockstep": True}),
    "p2": ("Second player AI, VSync/2 (was both_second_player_ai)",
           {**_QUIET, "agent_p1": False, "agent_p2": True, "vsync": 2, "reach": ""}),
    "boss": ("Straight to a round's boss, others swept (was go_to_boss; use --level)",
             {**_QUIET, "turbo": 2, "no_police": True}),
}
PRESET_ORDER = ("turbo", "watch", "quiet", "lockstep", "p2", "boss")

NO_FOOD_LEVELS = frozenset({2, 3, 4, 5, 8})
ENEMY_FAMILIES = ("garcia", "hakuro", "jack", "nora", "signal")  # autoplay --only-enemy choices


def boss_fields(level: int) -> dict[str, Any]:
    """The level-dependent part of the go-to-boss setup (autoplay's CLAUDE.md, "Scoring a fight")."""
    return {
        "start_level": level,
        "sweep": "mrx" if level == 8 else "street",
        "no_food": level in NO_FOOD_LEVELS,
    }


def preset_settings(base: dict[str, Any], name: str, level: int = 0) -> dict[str, Any]:
    settings = {**base, **PRESETS[name][1]}
    if name == "boss":
        settings.update(boss_fields(level or settings["start_level"] or 1))
    return settings


# ---------------------------------------------------------------------------------------------------
# Settings file: a flat YAML subset (key: value; booleans, integers, JSON-quoted strings).


def parse_value(text: str) -> Any:
    text = text.strip()
    if text in {"true", "false"}:
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if len(text) >= 2 and text[0] == text[-1] == '"':
        try:
            return json.loads(text)
        except ValueError:
            return text[1:-1]
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    return text


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    settings = dict(DEFAULTS)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return settings
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        if key not in DEFAULTS:
            continue
        value = parse_value(rest)
        default = DEFAULTS[key]
        if isinstance(value, bool) == isinstance(default, bool) and isinstance(value, type(default)):
            settings[key] = value
        elif isinstance(default, str):
            settings[key] = str(value)
    return settings


def save_settings(settings: dict[str, Any], path: Path = SETTINGS_PATH) -> None:
    lines = ["# Written by scripts/play.py and read back on its next launch. Gitignored; safe to edit."]
    lines += [f"{key}: {format_value(settings[key])}" for key in DEFAULTS]
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"play.py: cannot save {path.name}: {error}", file=sys.stderr)


# ---------------------------------------------------------------------------------------------------
# Command lines


def host_arguments(s: dict[str, Any], *, with_autoplay: bool) -> list[str]:
    """Arguments for scripts/run.py (the optional ROM comes first, as run.py expects)."""
    args: list[str] = [s["rom"]] if s["rom"] else []
    if s["turbo"] > 0:
        args += ["--turbo", str(s["turbo"])]
    elif s["vsync"]:
        args += ["--vsync", str(s["vsync"])]
    if s["lang"]:
        args += ["--lang", s["lang"]]
    if s["hz"]:
        args += ["--hz", str(s["hz"])]
    if s["debug_utils"] or with_autoplay:
        args.append("--debugUtils")
    if s["debug"]:
        args.append("--debug")
    if s["fullscreen"]:
        args.append("--fullScreen")
    if s["widescreen"]:
        args.append("--widescreen")
    if s["integer_scaling"]:
        args.append("--integerScaling")
    if s["alt_controls"]:
        args.append("--altControls")
    args += ["--port", str(s["port"])]
    if s["silent"]:
        args.append("--silent")
    else:
        if s["sound"] == "emulated":
            args += ["--sound", "emulated"]
        elif s["soundtrack"]:
            args += ["--soundtrack", s["soundtrack"]]
    if s["call_log"]:
        args += ["--callLog", s["call_log"]]
    return args


def auto_poll_ms(turbo: int) -> float:
    """Poll cadence that keeps ~2 game frames per tick: 16 ms at x2, 8 at x4, 3.2 at x10 (0 = autoplay's default)."""
    return round(32 / turbo, 2) if turbo > 0 else 0


def autoplay_arguments(s: dict[str, Any]) -> list[str]:
    """Arguments for scripts/autoplay.py."""
    args: list[str] = []
    poll = s["poll_ms"] or auto_poll_ms(s["turbo"])
    if s["lockstep"]:
        args.append("--lockstep")
    elif poll:
        args += ["--poll-ms", f"{poll:g}"]
    args += ["--port", str(s["port"])]
    if s["hud_ms"]:
        args += ["--hud-ms", str(s["hud_ms"])]
    if s["agent_p1"]:
        args.append("--agent-p1")
    if s["agent_p2"]:
        args.append("--agent-p2")
    if s["reach"]:
        args += ["--reach-gameplay", s["reach"]]
    if s["start_level"]:
        args += ["--start-level", str(s["start_level"])]
    sweep = s["sweep"]
    if sweep == "street":
        args.append("--kill-street-enemies")
    elif sweep == "mrx":
        args.append("--kill-until-mr-x")
    elif sweep.startswith("only:"):
        args += ["--only-enemy", sweep[5:]]
    if s["no_food"]:
        args.append("--no-food")
    if s["no_police"]:
        args.append("--no-police")
    args += shlex.split(s["extra"])
    return args


def soundtrack_dir(s: dict[str, Any]) -> Path:
    """The folder sor reads the pre-rendered soundtrack from (its default: soundtrack/ next to the ROM)."""
    if s["soundtrack"]:
        return Path(s["soundtrack"]).expanduser()
    rom = Path(s["rom"]).expanduser() if s["rom"] else Path(os.environ.get("SOR_ROM", DEFAULT_ROM))
    return rom.parent / "soundtrack"


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def check(s: dict[str, Any], mode: str, *, probe: bool = False) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for launching `mode` ("both", "host" or "autoplay")."""
    errors: list[str] = []
    warnings: list[str] = []
    if not 1 <= s["port"] <= 65535:
        errors.append("port must be 1-65535")
    if not 0 <= s["start_level"] <= 8:
        errors.append("start level must be 0 (none) to 8")
    try:
        shlex.split(s["extra"])
    except ValueError as error:
        errors.append(f"extra arguments: {error}")
    if mode != "autoplay":
        if not s["build_first"] and not built_executable(SOR_BUILD_DIR, "sor").is_file():
            errors.append("sor is not built: Ctrl+B builds it first")
        if s["rom"] and not Path(s["rom"]).expanduser().is_file():
            errors.append(f"ROM not found: {s['rom']}")
        if not s["silent"] and s["sound"] == "prerendered" and not (soundtrack_dir(s) / "manifest.tsv").is_file():
            warnings.append(f"no pre-rendered soundtrack in {soundtrack_dir(s)}: sor will emulate the sound chips "
                            "(scripts/render_soundtrack.py renders it)")
        if probe and not errors and port_in_use(s["port"]):
            errors.append(f"port {s['port']} already has a listener (a host is running?): Ctrl+A attaches to it")
    elif probe and not errors and not port_in_use(s["port"]):
        warnings.append(f"nothing is listening on port {s['port']} yet")
    if mode != "autoplay" and s["turbo"] > 0 and s["vsync"]:
        warnings.append("turbo needs the internal timer: the vsync setting is ignored")
    if mode != "host" and s["lockstep"] and s["poll_ms"]:
        warnings.append("lockstep paces itself: --poll-ms is not passed")
    if mode == "host" and not s["debug_utils"]:
        warnings.append("without debugUtils there is no remote access for autoplay")
    return errors, warnings


def describe(s: dict[str, Any], mode: str) -> list[str]:
    lines: list[str] = []
    if s["build_first"] and mode != "autoplay":
        lines.append("build:     build.py")
    if mode != "autoplay":
        lines.append("sor:       " + shlex.join(host_arguments(s, with_autoplay=mode == "both")))
    if mode != "host":
        try:
            lines.append("autoplay:  " + shlex.join(autoplay_arguments(s)))
        except ValueError:
            lines.append("autoplay:  (unparsable extra arguments)")
    return lines


def execute(s: dict[str, Any], mode: str) -> int:
    """Run the session in the foreground; Ctrl+C ends it. Returns the exit code."""
    print("\n".join(describe(s, mode)), flush=True)
    if s["build_first"] and mode != "autoplay":
        if subprocess.run(script_command("build.py")).returncode != 0:
            print("play.py: build failed", file=sys.stderr)
            return 1
    try:
        if mode == "both":
            return run_session(host_arguments(s, with_autoplay=True), autoplay_arguments(s), s["port"])
        if mode == "host":
            return subprocess.run(script_command("run.py", *host_arguments(s, with_autoplay=False))).returncode
        return subprocess.run(script_command("autoplay.py", *autoplay_arguments(s))).returncode
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------------------------------------
# Window

LANG_CHOICES = [("default", ""), ("en (overseas)", "en"), ("jp (Japan)", "jp")]
TURBO_CHOICES = [("off", 0), ("x2", 2), ("x3", 3), ("x4", 4), ("x6", 6), ("x10", 10), ("x16", 16), ("x24", 24), ("x32", 32)]
VSYNC_CHOICES = [("internal timer", 0), ("VSync", 1), ("VSync / 2", 2), ("VSync / 3", 3)]
HZ_CHOICES = [("default", 0), ("60 (NTSC)", 60), ("50 (PAL)", 50)]
SOUND_CHOICES = [("pre-rendered", "prerendered"), ("emulated chips", "emulated")]
REACH_CHOICES = [("stay in the menus", ""), ("Axel", "axel"), ("Adam", "adam"), ("Blaze", "blaze")]
SWEEP_CHOICES = [("none", ""), ("street enemies", "street"), ("until Mr. X (round 8)", "mrx")] + [
    (f"only {family}", f"only:{family}") for family in ENEMY_FAMILIES
]
CHOICES = {
    "lang": LANG_CHOICES, "turbo": TURBO_CHOICES, "vsync": VSYNC_CHOICES, "hz": HZ_CHOICES, "sound": SOUND_CHOICES,
    "reach": REACH_CHOICES, "sweep": SWEEP_CHOICES,
}


def to_int(text: str, fallback: int) -> int:
    try:
        return int(text.strip())
    except ValueError:
        return fallback


class PlayWindow:
    def __init__(self, tk: Any, ttk: Any, root: Any, settings: dict[str, Any], notice: str) -> None:
        self.tk, self.ttk, self.root = tk, ttk, root
        self.action = "quit"
        self.result = dict(settings)
        self.vars: dict[str, Any] = {}
        self.options: dict[str, list[tuple[str, Any]]] = {key: list(values) for key, values in CHOICES.items()}
        self.combos: dict[str, Any] = {}
        self.buttons: dict[str, Any] = {}
        self.extra_entry: Any = None
        self.loading = True
        self.session: Any = None  # the running launch (a child play.py), polled so Tk keeps serving events
        self.session_mode = ""
        root.title("Streets of Rage - play")
        root.minsize(980, 660)
        self.status = tk.StringVar(value=notice)
        self.build()
        self.load(settings)
        self.loading = False
        self.bind_keys()
        self.refresh()
        root.protocol("WM_DELETE_WINDOW", lambda: self.finish("quit"))
        root.focus_force()

    # -- construction

    def build(self) -> None:
        tk, ttk, root = self.tk, self.ttk, self.root
        root.columnconfigure(0, weight=1, uniform="cols")
        root.columnconfigure(1, weight=1, uniform="cols")
        root.rowconfigure(3, weight=1)

        presets = ttk.LabelFrame(root, text="Presets")
        presets.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 4))
        for index, name in enumerate(PRESET_ORDER, start=1):
            ttk.Button(presets, text=f"^{index}  {name}", command=lambda n=name: self.apply_preset(n)).grid(
                row=0, column=index - 1, padx=4, pady=4)

        shared = ttk.LabelFrame(root, text="Session: set once, used by the host and by autoplay")
        shared.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=4)
        shared.columnconfigure(1, weight=1)
        shared.columnconfigure(3, weight=1)
        self.spin(shared, 0, "Port: sor --port, autoplay --port", "port", 1, 65535)
        self.combo(shared, 0, "Turbo (^T): sor --turbo, autoplay poll 32/turbo ms", "turbo", column=2)

        host = ttk.LabelFrame(root, text="Host (sor)")
        host.grid(row=2, column=0, sticky="nsew", padx=(10, 5), pady=4)
        host.columnconfigure(1, weight=1)
        autoplay = ttk.LabelFrame(root, text="Autoplay")
        autoplay.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=4)
        autoplay.columnconfigure(1, weight=1)

        self.combo(host, 0, "Frame sync (ignored under turbo)", "vsync")
        self.combo(host, 1, "Language", "lang")
        self.combo(host, 2, "Video Hz", "hz")
        self.check(host, 3, "Silent (^N)", "silent")
        self.combo(host, 4, "Sound (ignored when silent)", "sound")
        self.entry(host, 5, "Soundtrack folder (empty = next to the ROM)", "soundtrack", browse=True)
        self.check(host, 6, "Fullscreen (^F)", "fullscreen")
        self.check(host, 7, "Widescreen (^W)", "widescreen")
        self.check(host, 8, "Integer scaling (^U)", "integer_scaling")
        self.check(host, 9, "6-button layout, --altControls (^X)", "alt_controls")
        self.check(host, 10, "debugUtils: remote access, hotkeys (^D)", "debug_utils")
        self.check(host, 11, "Log CPU/VDP state, --debug", "debug")
        self.entry(host, 12, "Call log file", "call_log")
        self.entry(host, 13, "ROM file", "rom")

        self.check(autoplay, 0, "AI plays P1 (^7)", "agent_p1")
        self.check(autoplay, 1, "AI plays P2 (^8)", "agent_p2")
        self.combo(autoplay, 2, "Reach gameplay as (^G)", "reach")
        self.check(autoplay, 3, "Lockstep, frame-exact (^L)", "lockstep")
        self.spin(autoplay, 4, "Poll ms (0 = auto)", "poll_ms", 0, 1000)
        self.spin(autoplay, 5, "HUD ms (0 = default)", "hud_ms", 0, 1000)
        self.spin(autoplay, 6, "Start level (^= / ^-, 0 = none)", "start_level", 0, 8)
        self.combo(autoplay, 7, "Sweep enemies (^K)", "sweep")
        self.check(autoplay, 8, "No food (scoring a fight)", "no_food")
        self.check(autoplay, 9, "No police special", "no_police")
        self.extra_entry = self.entry(autoplay, 10, "Extra arguments (^E)", "extra")

        preview = ttk.LabelFrame(root, text="Command lines")
        preview.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=4)
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.preview = tk.Text(preview, height=7, wrap="word", font="TkFixedFont", state="disabled",
                               takefocus=0, borderwidth=0, highlightthickness=0)
        self.preview.grid(row=0, column=0, sticky="nsew", padx=6, pady=4)
        self.preview.tag_configure("error", foreground="#c0392b")
        self.preview.tag_configure("warning", foreground="#b9770e")

        bar = ttk.Frame(root)
        bar.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))
        bar.columnconfigure(1, weight=1)
        self.vars["build_first"] = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Build first (^B)", variable=self.vars["build_first"]).grid(row=0, column=0)
        ttk.Label(bar, textvariable=self.status, foreground="#c0392b").grid(row=0, column=1, sticky="w", padx=10)
        for column, (text, mode) in enumerate(
                [("Run Game + AI Connected  ^R", "both"), ("Run Game  ^S", "host"), ("Run AI  ^A", "autoplay")],
                start=2):
            self.buttons[mode] = ttk.Button(bar, text=text, command=lambda m=mode: self.launch(m))
            self.buttons[mode].grid(row=0, column=column, padx=3)
        ttk.Button(bar, text="Quit  ^Q", command=lambda: self.finish("quit")).grid(row=0, column=5, padx=(12, 0))
        # Run AI is the way in when the game was started outside this window.
        ttk.Label(bar, text="If you already have the game running", foreground="#909090",
                  font=("TkDefaultFont", 8)).grid(row=1, column=4, columnspan=2, sticky="w")
        self.trace("build_first")

    def trace(self, key: str) -> None:
        self.vars[key].trace_add("write", lambda *_: self.changed(key))

    def check(self, parent: Any, row: int, text: str, key: str) -> None:
        self.vars[key] = self.tk.BooleanVar()
        self.ttk.Checkbutton(parent, text=text, variable=self.vars[key]).grid(
            row=row, column=0, columnspan=2, sticky="w", padx=8, pady=1)
        self.trace(key)

    def entry(self, parent: Any, row: int, label: str, key: str, browse: bool = False) -> Any:
        self.vars[key] = self.tk.StringVar()
        self.ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=2)
        if browse:
            # A folder: the entry plus a button that opens the system folder chooser.
            field = self.ttk.Frame(parent)
            field.grid(row=row, column=1, sticky="ew", padx=8, pady=2)
            field.columnconfigure(0, weight=1)
            widget = self.ttk.Entry(field, textvariable=self.vars[key])
            widget.grid(row=0, column=0, sticky="ew")
            self.ttk.Button(field, text="...", width=3, command=lambda: self.choose_folder(key)).grid(
                row=0, column=1, padx=(4, 0))
        else:
            widget = self.ttk.Entry(parent, textvariable=self.vars[key])
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=2)
        self.trace(key)
        return widget

    def choose_folder(self, key: str) -> None:
        from tkinter import filedialog

        current = self.vars[key].get().strip()
        initial = Path(current).expanduser() if current else soundtrack_dir(self.collect())
        chosen = filedialog.askdirectory(parent=self.root, mustexist=True, title="Soundtrack folder",
                                         initialdir=str(initial if initial.is_dir() else META_ROOT))
        if chosen:
            self.vars[key].set(chosen)

    def spin(self, parent: Any, row: int, label: str, key: str, low: int, high: int, column: int = 0) -> None:
        self.vars[key] = self.tk.StringVar()
        self.ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=8, pady=2)
        self.ttk.Spinbox(parent, textvariable=self.vars[key], from_=low, to=high, width=8).grid(
            row=row, column=column + 1, sticky="w", padx=8, pady=2)
        self.trace(key)

    def combo(self, parent: Any, row: int, label: str, key: str, column: int = 0) -> None:
        self.vars[key] = self.tk.StringVar()
        self.ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=8, pady=2)
        box = self.ttk.Combobox(parent, textvariable=self.vars[key], state="readonly",
                                values=[name for name, _ in self.options[key]])
        box.grid(row=row, column=column + 1, sticky="ew", padx=8, pady=2)
        self.combos[key] = box
        self.trace(key)

    # -- settings <-> widgets

    def choice_value(self, key: str) -> Any:
        label = self.vars[key].get()
        for name, value in self.options[key]:
            if name == label:
                return value
        return self.options[key][0][1]

    def set_choice(self, key: str, value: Any) -> None:
        if all(candidate != value for _, candidate in self.options[key]):
            self.options[key].append((f"x{value}" if key == "turbo" else str(value), value))
            self.combos[key].configure(values=[name for name, _ in self.options[key]])
        self.vars[key].set(next(name for name, candidate in self.options[key] if candidate == value))

    def collect(self) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        for key, default in DEFAULTS.items():
            if key in self.options:
                settings[key] = self.choice_value(key)
            elif isinstance(default, bool):
                settings[key] = bool(self.vars[key].get())
            elif isinstance(default, int):
                settings[key] = to_int(self.vars[key].get(), default if key == "port" else 0)
            else:
                settings[key] = self.vars[key].get().strip()
        return settings

    def load(self, settings: dict[str, Any]) -> None:
        was_loading, self.loading = self.loading, True
        for key, value in settings.items():
            if key in self.options:
                self.set_choice(key, value)
            elif isinstance(DEFAULTS[key], bool):
                self.vars[key].set(bool(value))
            else:
                self.vars[key].set(str(value))
        self.loading = was_loading

    # -- reacting to changes

    def changed(self, key: str = "") -> None:
        if self.loading:
            return
        if key == "start_level":
            settings = self.collect()
            if settings["sweep"] in {"street", "mrx"} and 1 <= settings["start_level"] <= 8:
                # A level-dependent boss setup follows the level: round 8's sweep, and no food where the
                # fight is scored (autoplay's CLAUDE.md, "Scoring a fight without the food").
                self.load({**boss_fields(settings["start_level"])})
        self.refresh()

    def refresh(self) -> None:
        settings = self.collect()
        errors, warnings = check(settings, "both")
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("end", "\n".join(describe(settings, "both")) + "\n")
        for message in errors:
            self.preview.insert("end", f"! {message}\n", "error")
        for message in warnings:
            self.preview.insert("end", f"* {message}\n", "warning")
        self.preview.configure(state="disabled")
        # The connected pair needs the host's remote server: without debugUtils it cannot start.
        self.buttons["both"].configure(state="normal" if settings["debug_utils"] else "disabled")
        if self.status.get() and not self.loading:
            self.status.set("")
        save_settings(settings)

    # -- actions

    def apply_preset(self, name: str) -> None:
        self.load(preset_settings(self.collect(), name))
        self.refresh()

    def launch(self, mode: str) -> None:
        settings = self.collect()
        if mode == "both" and not settings["debug_utils"]:
            # The button is disabled; the ^R shortcut goes through here too.
            self.status.set("Run Game + AI Connected needs debugUtils on (^D)")
            return
        errors, _ = check(settings, mode, probe=True)
        if errors:
            self.status.set(errors[0])
            return
        if self.session is not None:
            self.status.set(f"A session ({self.session_mode}) is still running")
            return
        # The session runs in a child process: blocking here would leave the Tk app unresponsive
        # (the macOS beach ball) until the game ends.
        save_settings(settings)
        self.session_mode = mode
        self.session = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--run-saved", mode])
        self.status.set(f"Running ({mode})... Quit stops it")
        self.root.after(300, self.poll_session)

    def poll_session(self) -> None:
        if self.session is None:
            return
        code = self.session.poll()
        if code is None:
            self.root.after(300, self.poll_session)
            return
        self.session = None
        self.status.set(f"Last run ({self.session_mode}) exited with code {code}.")

    def stop_session(self) -> None:
        session, self.session = self.session, None
        if session is None or session.poll() is not None:
            return
        try:
            session.send_signal(signal.SIGINT) if os.name != "nt" else session.terminate()
            session.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            session.kill()

    def finish(self, action: str) -> None:
        self.stop_session()
        self.action = action
        self.result = self.collect()
        self.root.quit()

    def toggle(self, key: str) -> None:
        self.vars[key].set(not self.vars[key].get())

    def cycle(self, key: str, step: int = 1) -> None:
        names = [name for name, _ in self.options[key]]
        current = self.vars[key].get()
        index = names.index(current) if current in names else 0
        self.vars[key].set(names[(index + step) % len(names)])

    def step_level(self, step: int) -> None:
        level = to_int(self.vars["start_level"].get(), 0)
        self.vars["start_level"].set(str(max(0, min(8, level + step))))

    def reset(self) -> None:
        self.load(dict(DEFAULTS))
        self.refresh()

    # -- keyboard

    def bind_keys(self) -> None:
        actions: dict[str, Any] = {
            "r": lambda: self.launch("both"), "Return": lambda: self.launch("both"),
            "s": lambda: self.launch("host"), "a": lambda: self.launch("autoplay"),
            "q": lambda: self.finish("quit"),
            "b": lambda: self.toggle("build_first"),
            "n": lambda: self.toggle("silent"), "f": lambda: self.toggle("fullscreen"),
            "w": lambda: self.toggle("widescreen"), "u": lambda: self.toggle("integer_scaling"), "x": lambda: self.toggle("alt_controls"),
            "d": lambda: self.toggle("debug_utils"), "l": lambda: self.toggle("lockstep"),
            "7": lambda: self.toggle("agent_p1"), "8": lambda: self.toggle("agent_p2"),
            "t": lambda: self.cycle("turbo"), "g": lambda: self.cycle("reach"), "k": lambda: self.cycle("sweep"),
            "equal": lambda: self.step_level(1), "plus": lambda: self.step_level(1),
            "minus": lambda: self.step_level(-1),
            "0": self.reset,
            "e": lambda: (self.extra_entry.focus_set(), self.extra_entry.icursor("end")),
        }
        for index, name in enumerate(PRESET_ORDER, start=1):
            actions[str(index)] = lambda n=name: self.apply_preset(n)
        for key, function in actions.items():
            for variant in {key, key.upper()} if len(key) == 1 else {key}:
                self.root.bind_class("PlayKeys", f"<Control-Key-{variant}>", self.handler(function))
        # Entry-like widgets bind many Ctrl+letter keys themselves (Ctrl+A, Ctrl+F...): the shared
        # tag goes first on every widget and returns "break" so these shortcuts always win.
        self.tag_widgets(self.root)

    @staticmethod
    def handler(function: Any) -> Any:
        def run(_event: Any) -> str:
            function()
            return "break"
        return run

    def tag_widgets(self, widget: Any) -> None:
        widget.bindtags(("PlayKeys", *widget.bindtags()))
        for child in widget.winfo_children():
            self.tag_widgets(child)


def run_window(settings: dict[str, Any], notice: str) -> tuple[str, dict[str, Any]]:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    window = PlayWindow(tk, ttk, root, settings, notice)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        window.stop_session()
    action, result = window.action, window.result
    root.destroy()
    return action, result


def ensure_tk() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        python = find_tk_python()
        if python is None:
            print("play.py: no Python with Tk (_tkinter) found; use --preset/--last for the command line.",
                  file=sys.stderr)
            raise SystemExit(1)
        os.execv(python, [python, str(Path(__file__).resolve()), *sys.argv[1:]])


def interactive() -> int:
    ensure_tk()
    settings = load_settings()
    _, settings = run_window(settings, "")
    save_settings(settings)
    return 0


# ---------------------------------------------------------------------------------------------------
# Command line


def parse_arguments(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="play.py", allow_abbrev=False,
        description=__doc__.split("\n\n")[0],
        epilog="Presets: " + "; ".join(f"{name} = {PRESETS[name][0]}" for name in PRESET_ORDER)
        + ". Other options are passed to autoplay.",
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), help="launch a preset without the window")
    parser.add_argument("--last", action="store_true", help="launch the saved settings without the window")
    parser.add_argument("--level", type=int, default=0, metavar="N", help="with --preset boss: the round (1-8)")
    parser.add_argument("--mode", choices=("both", "host", "autoplay"), default="both",
                        help="what to start (default: both)")
    parser.add_argument("--run-saved", choices=("both", "host", "autoplay"), metavar="MODE",
                        help="internal: run the saved settings in the foreground (the window starts this)")
    parser.add_argument("--dry-run", action="store_true", help="print the command lines and exit")
    return parser.parse_known_args(argv)


def main() -> int:
    if len(sys.argv) == 1:
        return interactive()
    arguments, extra = parse_arguments(sys.argv[1:])
    if arguments.run_saved:
        return execute(load_settings(), arguments.run_saved)
    if arguments.preset is None and not arguments.last:
        print("play.py: give --preset NAME or --last (no arguments opens the window)", file=sys.stderr)
        return 2
    if arguments.level and arguments.preset != "boss":
        print("play.py: --level goes with --preset boss", file=sys.stderr)
        return 2
    if arguments.preset == "boss" and arguments.level and arguments.level not in range(1, 9):
        print("play.py: --level must be 1-8", file=sys.stderr)
        return 2
    if arguments.preset:
        settings = preset_settings(dict(DEFAULTS), arguments.preset, arguments.level)
    else:
        settings = load_settings()
    if extra:
        settings["extra"] = shlex.join([*shlex.split(settings["extra"]), *extra])
    errors, warnings = check(settings, arguments.mode, probe=not arguments.dry_run)
    for message in warnings:
        print(f"play.py: {message}", file=sys.stderr)
    if errors:
        for message in errors:
            print(f"play.py: {message}", file=sys.stderr)
        return 1
    if arguments.dry_run:
        print("\n".join(describe(settings, arguments.mode)))
        return 0
    return execute(settings, arguments.mode)


if __name__ == "__main__":
    raise SystemExit(main())
