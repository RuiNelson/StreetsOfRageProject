"""Tk observer HUD: 3-column status bar + map filling remaining space.

The window restores its last size/position from a small JSON file and only
maximizes on first run (no saved geometry yet).
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Callable

from .ai.loop import VerbState
from .ai.tokens import Verb
from .hitboxes import Hitbox
from .phases import CombatPhase, phase_color
from .state import GameSnapshot, PlayerSnapshot
from .world_map import MAP_ASPECT, WorldMap

OUTER_PAD = 12
STATUS_GAP = 10
MAP_INNER_PAD = 10
# GUI paint only; remote sampling uses its own wall-clock poll period.
HUD_PAINT_MS_DEFAULT = 33

# Where the last window geometry ("WxH+X+Y") is persisted across launches.
# In ~/.config/sor-autoplay/window.json (or $XDG_CONFIG_HOME).
_WINDOW_CONFIG_REL = Path("sor-autoplay") / "window.json"


def _window_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / _WINDOW_CONFIG_REL
    return Path.home() / ".config" / _WINDOW_CONFIG_REL

_BG = "#050508"
_CARD = "#12131a"
_BORDER = "#3a3f55"
_TEXT = "#d7dbe8"
_MUTED = "#8b90a5"
_DIM = "#5c6178"
# Map plot background (_ensure_static_plate's self._plot_rect fill) -- the
# surface an AttackRange square is blended against, see _blend_hex.
_PLOT_BG = "#11131c"
# AttackRange squares: same red as phases.phase_color's ATTACKING outline,
# at 35% opacity. Tk canvas items have no real alpha, and `stipple` -- this
# HUD's other translucency idiom, used for floor holes -- is silently a
# no-op on Aqua Tk (macOS): the canvas draws the stipple pattern's *fill*
# solid instead of dithering it, so a stippled square here would render as
# flat opaque red covering whatever is under it. Blending the colour with
# the known plot background ahead of time and drawing that as a plain solid
# fill reads as translucent on every platform, at the cost of only being
# exactly right over that one background colour (approximately right over
# anything else on the map, which is the same trade the stipple idiom
# already made).
_RANGE_FILL_ALPHA = 0.35


def _blend_hex(fg: str, bg: str, alpha: float) -> str:
    """``fg`` at ``alpha`` opacity over solid ``bg``, as one opaque hex colour."""

    fr, fgc, fb = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
    br, bgc, bb = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
    r = round(fr * alpha + br * (1 - alpha))
    g = round(fgc * alpha + bgc * (1 - alpha))
    b = round(fb * alpha + bb * (1 - alpha))
    return f"#{r:02x}{g:02x}{b:02x}"


_RANGE_FILL = _blend_hex("#ff453a", _PLOT_BG, _RANGE_FILL_ALPHA)
# Screen-space floor for a hitbox-derived marker, so a real but tiny/
# zoomed-out box does not vanish. Purely cosmetic -- never fed back into
# anything the AI reads.
MIN_MARKER_PX = 6

# Draw order: props under fighters so players/bosses stay readable.
_KIND_Z = {
    "breakable": 0,
    "pickup": 1,
    "weapon": 2,
    "projectile": 3,
    "other": 4,
    "enemy": 5,
    "boss": 6,
    "player": 7,
}


class ObserverHud:
    """Observer window: state/P1/P2 columns on top; map takes the rest.

    Restores the last window size/position from disk when available.
    """

    def __init__(
        self,
        *,
        title: str = "SoR Autoplay",
        subtitle: str = "live replica",
        on_close: Callable[[], None] | None = None,
        on_toggle_agent: Callable[[int], None] | None = None,
    ) -> None:
        self._on_close = on_close
        self._on_toggle_agent = on_toggle_agent
        self._latest_map: WorldMap | None = None
        self._latest_holes: tuple = ()
        self._map_draw_job: str | None = None
        # Stable canvas items — avoid delete("all") every poll (that flashes).
        self._bg_rect: int | None = None
        self._plot_rect: int | None = None
        self._grid_lines: list[int] = []
        self._cam_rect: int | None = None
        self._cam_label: int | None = None
        self._empty_label: int | None = None
        self._markers: list[tuple[int, int]] = []  # (square_id, text_id)
        self._hole_rects: list[int] = []
        self._range_rects: list[int] = []  # AttackRange squares, pooled like holes
        self._last_canvas_size: tuple[int, int] = (0, 0)
        self._last_plot_geom: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._last_meta_text: str = ""

        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=_BG)
        self.root.minsize(720, 420)
        self.root.bind("<Escape>", self._handle_close)
        self.root.bind("<q>", self._handle_close)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

        family = self._pick_font_family()
        self._font_title = tkfont.Font(family=family, size=12, weight="bold")
        self._font_body = tkfont.Font(family=family, size=11)
        self._font_mono = tkfont.Font(family=family, size=11)
        self._font_small = tkfont.Font(family=family, size=9)
        self._font_map = tkfont.Font(family=family, size=13, weight="bold")
        self._font_map_tiny = tkfont.Font(family=family, size=8)

        self._stage = tk.Frame(self.root, bg=_BG)
        self._stage.pack(fill=tk.BOTH, expand=True, padx=OUTER_PAD, pady=OUTER_PAD)

        # --- Top: three equal columns (State / P1 / P2) ---
        self._status_row = tk.Frame(self._stage, bg=_BG)
        self._status_row.pack(fill=tk.X, side=tk.TOP)
        self._status_row.columnconfigure(0, weight=1, uniform="status")
        self._status_row.columnconfigure(1, weight=1, uniform="status")
        self._status_row.columnconfigure(2, weight=1, uniform="status")

        self._col_state = self._card(self._status_row, 0)
        self._col_p1 = self._card(self._status_row, 1)
        self._col_p2 = self._card(self._status_row, 2)

        # State column
        self._state_title = self._heading(self._col_state, f"State  ·  {subtitle}")
        self._status = self._label(self._col_state, font=self._font_small, fg=_MUTED)
        self._mode = self._label(self._col_state)
        self._level = self._label(self._col_state)
        self._time = self._label(self._col_state)
        self._flags = self._label(self._col_state, mono=True)
        self._holes = self._label(self._col_state, font=self._font_small, fg=_MUTED)
        self._footer = self._label(
            self._col_state,
            text="Esc/Q quit · click AI: OFF/ON to toggle autoplay",
            font=self._font_small,
            fg=_DIM,
        )

        # P1 column
        self._p1_title = self._heading(self._col_p1, "P1", fg="#9ecbff")
        self._p1_header = self._label(self._col_p1, fg="#9ecbff")
        self._p1_health = self._label(self._col_p1, mono=True)
        self._p1_stats = self._label(self._col_p1, mono=True)
        self._p1_score = self._label(self._col_p1, mono=True)
        self._p1_hunt = self._label(self._col_p1, font=self._font_small, fg=_MUTED)
        self._p1_verb = self._label(self._col_p1, font=self._font_small, fg=_MUTED)
        self._p1_pending = self._label(self._col_p1, font=self._font_small, fg=_MUTED)
        self._p1_agent_toggle = self._label(self._col_p1, font=self._font_small, fg=_MUTED)
        self._p1_agent_toggle.configure(cursor="hand2")
        self._p1_agent_toggle.bind("<Button-1>", lambda _e: self._handle_toggle_agent(1))

        # P2 column (always present for a stable 3-column layout)
        self._p2_title = self._heading(self._col_p2, "P2", fg="#ffb3c7")
        self._p2_header = self._label(self._col_p2, fg="#ffb3c7")
        self._p2_health = self._label(self._col_p2, mono=True)
        self._p2_stats = self._label(self._col_p2, mono=True)
        self._p2_score = self._label(self._col_p2, mono=True)
        self._p2_hunt = self._label(self._col_p2, font=self._font_small, fg=_MUTED)
        self._p2_verb = self._label(self._col_p2, font=self._font_small, fg=_MUTED)
        self._p2_pending = self._label(self._col_p2, font=self._font_small, fg=_MUTED)
        self._p2_agent_toggle = self._label(self._col_p2, font=self._font_small, fg=_MUTED)
        self._p2_agent_toggle.configure(cursor="hand2")
        self._p2_agent_toggle.bind("<Button-1>", lambda _e: self._handle_toggle_agent(2))

        # --- Bottom: map fills all remaining window space ---
        self._map_frame = tk.Frame(
            self._stage,
            bg=_CARD,
            highlightbackground=_BORDER,
            highlightthickness=1,
        )
        self._map_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP, pady=(STATUS_GAP, 0))

        self._map_header = tk.Frame(self._map_frame, bg=_CARD)
        self._map_header.pack(fill=tk.X, padx=10, pady=(8, 0))

        self._map_title = tk.Label(
            self._map_header,
            text="World map  ·  top-down (X × lane depth)",
            fg="#e8eaf2",
            bg=_CARD,
            font=self._font_title,
            anchor="w",
        )
        self._map_title.pack(side=tk.LEFT)

        self._map_meta = tk.Label(
            self._map_header,
            text="cam —",
            fg=_MUTED,
            bg=_CARD,
            font=self._font_small,
            anchor="e",
        )
        self._map_meta.pack(side=tk.RIGHT)

        self._canvas = tk.Canvas(
            self._map_frame,
            bg="#0a0b10",
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._map_legend = tk.Label(
            self._map_frame,
            text=(
                "letters only · square outline = state  "
                "(green=down  orange=charge  red=atk  cyan=block  purple=held  gray=dead)  "
                "dashed box = camera · dim letters = off-camera  "
                "1/2  G/S/H/N/J  B boss  k/b/|/p weapons  a/+ food"
            ),
            fg=_DIM,
            bg=_CARD,
            font=self._font_map_tiny,
            anchor="w",
            justify=tk.LEFT,
        )
        self._map_legend.pack(fill=tk.X, padx=10, pady=(0, 8))

        # Apply geometry only after the whole UI is built. Restore the last
        # size/position if we have one, otherwise maximize (first run). Do not
        # schedule this with after_idle at construction time: the first
        # deiconify/focus flushes the idle callback before the layout exists
        # and the window ends up dropping to its minimum size.
        self._save_geometry_job: str | None = None
        self.root.bind("<Configure>", self._on_window_configure)
        self._restore_or_maximize()
        # Bring the observer to the front — macOS often opens Tk behind the
        # terminal that launched it.
        self._raise_window()

    def _card(self, parent: tk.Frame, column: int) -> tk.Frame:
        frame = tk.Frame(
            parent,
            bg=_CARD,
            highlightbackground=_BORDER,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        padx = (0, STATUS_GAP) if column < 2 else (0, 0)
        frame.grid(row=0, column=column, sticky="nsew", padx=padx)
        return frame

    def _heading(self, parent: tk.Frame, text: str, *, fg: str = "#e8eaf2") -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            fg=fg,
            bg=_CARD,
            font=self._font_title,
            anchor="w",
            justify=tk.LEFT,
        )
        label.pack(fill=tk.X, pady=(0, 4))
        return label

    def _label(
        self,
        parent: tk.Frame,
        *,
        text: str = "",
        fg: str = _TEXT,
        mono: bool = False,
        font: tkfont.Font | None = None,
    ) -> tk.Label:
        label = tk.Label(
            parent,
            text=text,
            fg=fg,
            bg=_CARD,
            font=font if font is not None else (self._font_mono if mono else self._font_body),
            anchor="w",
            justify=tk.LEFT,
        )
        label.pack(fill=tk.X)
        return label

    def _raise_window(self) -> None:
        """Make the window visible and focused after launch from a terminal."""

        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            # Temporary topmost so macOS actually activates the window, then
            # drop it so the user can freely switch away.
            self.root.attributes("-topmost", True)
            self.root.after(200, lambda: self._clear_topmost())
        except tk.TclError:
            pass

    def _clear_topmost(self) -> None:
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _apply_maximized(self) -> None:
        """First-run default: maximize the window (no saved geometry yet)."""

        self.root.update_idletasks()
        try:
            self.root.state("zoomed")
            self._raise_window()
            return
        except tk.TclError:
            pass
        try:
            self.root.attributes("-zoomed", True)
            self._raise_window()
            return
        except tk.TclError:
            pass
        if sys.platform == "darwin":
            try:
                self.root.tk.call("wm", "state", self.root._w, "zoomed")  # noqa: SLF001
                self._raise_window()
                return
            except tk.TclError:
                pass
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")
        self._raise_window()

    def _restore_or_maximize(self) -> None:
        """Restore the last saved size/position; maximize only on first run."""

        self.root.update_idletasks()
        saved = self._load_saved_geometry()
        if saved:
            try:
                self.root.geometry(saved)
                return
            except tk.TclError:
                pass
        self._apply_maximized()

    def _load_saved_geometry(self) -> str | None:
        try:
            data = json.loads(_window_config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        geometry = data.get("geometry") if isinstance(data, dict) else None
        if not isinstance(geometry, str):
            return None
        return self._sanitize_geometry(geometry)

    def _sanitize_geometry(self, geometry: str) -> str | None:
        """Validate a "WxH+X+Y" string and clamp it to the current screen."""

        try:
            size, _, pos = geometry.partition("+")
            w_s, h_s = size.split("x")
            w, h = int(w_s), int(h_s)
            if pos:
                x_s, _, y_s = pos.partition("+")
                x, y = int(x_s), int(y_s)
            else:
                x = y = 0
        except ValueError:
            return None
        if w <= 0 or h <= 0:
            return None
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(w, sw)
        h = min(h, sh)
        x = min(max(x, 0), max(sw - w, 0))
        y = min(max(y, 0), max(sh - h, 0))
        return f"{w}x{h}+{x}+{y}"

    def _on_window_configure(self, _event: object | None = None) -> None:
        # Debounced save so resizing/dragging does not hammer the disk.
        if self._save_geometry_job is not None:
            try:
                self.root.after_cancel(self._save_geometry_job)
            except tk.TclError:
                pass
        self._save_geometry_job = self.root.after(300, self._save_geometry)

    def _save_geometry(self) -> None:
        self._save_geometry_job = None
        try:
            # Never persist a maximized (zoomed) size — keep the previous
            # normal geometry instead.
            if self.root.state() == "zoomed":
                return
            geometry = self.root.geometry()
            geometry = self._sanitize_geometry(geometry)
        except tk.TclError:
            return
        if geometry is None:
            return
        try:
            path = _window_config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"geometry": geometry}), encoding="utf-8")
        except OSError:
            pass

    def _pick_font_family(self) -> str:
        available = set(tkfont.families())
        for name in ("SF Mono", "Menlo", "Monaco", "Consolas", "Courier New", "TkFixedFont"):
            if name in available:
                return name
        return "TkDefaultFont"

    def _handle_toggle_agent(self, player_index: int) -> None:
        if self._on_toggle_agent is not None:
            self._on_toggle_agent(player_index)

    def _handle_close(self, _event: object | None = None) -> None:
        # Persist the final size/position (unless it is zoomed) so the next
        # launch restores it.
        if self._save_geometry_job is not None:
            try:
                self.root.after_cancel(self._save_geometry_job)
            except tk.TclError:
                pass
            self._save_geometry_job = None
        self._save_geometry()
        if self._on_close is not None:
            self._on_close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def schedule(self, ms: int, callback: Callable[[], None]) -> None:
        self.root.after(ms, callback)

    def run(self) -> None:
        self.root.mainloop()

    def _on_canvas_configure(self, _event: tk.Event) -> None:
        # Coalesce resize redraws.
        if self._map_draw_job is not None:
            try:
                self.root.after_cancel(self._map_draw_job)
            except tk.TclError:
                pass
        self._map_draw_job = self.root.after(16, self._redraw_map_if_any)

    def _redraw_map_if_any(self) -> None:
        self._map_draw_job = None
        if self._latest_map is not None:
            self._draw_map(self._latest_map, self._latest_holes)

    def update(
        self,
        snapshot: GameSnapshot,
        *,
        agent_p1_enabled: bool = False,
        agent_p2_enabled: bool = False,
        p1_state: VerbState | None = None,
        p2_state: VerbState | None = None,
    ) -> None:
        if snapshot.connected:
            link = "● LIVE"
            link_color = "#5ddea0"
            host_note = f"0x{snapshot.game_state:02X}"
        else:
            link = "○ OFFLINE"
            link_color = "#ff6b6b"
            host_note = snapshot.error or "waiting for remote"

        self._status.configure(text=f"{link}  ·  {host_note}", fg=link_color)
        self._mode.configure(text=f"Mode   {snapshot.game_mode}")
        self._level.configure(
            text=(
                f"Level  {snapshot.level_display}  "
                f"(idx {snapshot.level_index})  "
                f"Wave {snapshot.wave}"
            )
        )
        if not snapshot.timer_valid:
            self._time.configure(text="Time   —  (not in gameplay)")
        else:
            clock_note = "stopped" if snapshot.clock_stopped else "running"
            self._time.configure(
                text=(
                    f"Time   {snapshot.time_left:02d}s  "
                    f"(digit {snapshot.round_timer_bcd:02d}, {clock_note})"
                )
            )

        flag_bits: list[str] = []
        if snapshot.paused:
            flag_bits.append("PAUSED")
        if snapshot.police_special_active:
            who = (
                f"P{snapshot.police_special_caller + 1}"
                if snapshot.police_special_caller is not None
                else "?"
            )
            flag_bits.append(f"POLICE SPECIAL ({who})")
        if flag_bits:
            self._flags.configure(text="  ".join(flag_bits), fg="#ffd84d")
        else:
            self._flags.configure(text="Running", fg=_MUTED)

        if snapshot.floor_holes:
            self._holes.configure(
                text=f"Floor holes: {len(snapshot.floor_holes)} region(s)",
                fg="#7dd3fc",
            )
        elif snapshot.level_index == 3 and snapshot.timer_valid:
            self._holes.configure(text="Floor holes: none near camera", fg=_MUTED)
        else:
            self._holes.configure(text="", fg=_MUTED)

        self._render_player(snapshot.p1, self._p1_header, self._p1_health, self._p1_stats, self._p1_score)
        self._render_player(snapshot.p2, self._p2_header, self._p2_health, self._p2_stats, self._p2_score)

        h1 = len(snapshot.world_map.threats_targeting(1))
        h2 = len(snapshot.world_map.threats_targeting(2))
        self._p1_hunt.configure(text=f"Hunted ×{h1}" if h1 else "")
        self._p2_hunt.configure(text=f"Hunted ×{h2}" if h2 else "")

        self._render_verb(self._p1_verb, agent_p1_enabled, p1_state)
        self._render_verb(self._p2_verb, agent_p2_enabled, p2_state)
        self._render_pending(self._p1_pending, agent_p1_enabled, p1_state)
        self._render_pending(self._p2_pending, agent_p2_enabled, p2_state)

        self._render_agent_toggle(self._p1_agent_toggle, agent_p1_enabled)
        self._render_agent_toggle(self._p2_agent_toggle, agent_p2_enabled)

        self._latest_map = snapshot.world_map
        self._latest_holes = snapshot.floor_holes
        self._draw_map(snapshot.world_map, snapshot.floor_holes)

    def _render_agent_toggle(self, label: tk.Label, enabled: bool) -> None:
        if enabled:
            label.configure(text="AI: ON  (click to disable)", fg="#5ddea0")
        else:
            label.configure(text="AI: OFF  (click to enable)", fg=_MUTED)

    def _render_verb(
        self, label: tk.Label, enabled: bool, state: VerbState | None
    ) -> None:
        if not enabled or state is None:
            label.configure(text="")
            return
        label.configure(text=f"Verb  {_describe_verb(state.winning)}", fg="#ffd84d")

    def _render_pending(
        self, label: tk.Label, enabled: bool, state: VerbState | None
    ) -> None:
        if not enabled or state is None:
            label.configure(text="")
            return
        label.configure(text=_describe_pending(state.pending), fg=_MUTED)

    def _render_player(
        self,
        player: PlayerSnapshot,
        header: tk.Label,
        health: tk.Label,
        stats: tk.Label,
        score: tk.Label,
    ) -> None:
        if not player.mode_active and not player.is_playable:
            header.configure(text="inactive")
            health.configure(text="Life    —")
            stats.configure(text="Lives   —   Specials —")
            score.configure(text="Score   —")
            return

        state_bits: list[str] = []
        if player.is_playable:
            state_bits.append("active")
        elif player.object_type == 0x0F:
            state_bits.append("continue")
        elif player.mode_active:
            state_bits.append("in mode")
        if player.out_flag:
            state_bits.append("out")
        state = ", ".join(state_bits) if state_bits else "present"

        header.configure(text=f"{player.character_name}  ·  {state}")
        health.configure(text=f"Life    {_health_bar(player)}")
        stats.configure(
            text=(
                f"Lives   {player.lives}   "
                f"Specials {player.specials}   "
                f"Cont {player.continues}"
            )
        )
        score.configure(text=f"Score   {player.score_text}")

    def _draw_map(self, world: WorldMap, holes: tuple = ()) -> None:
        """Update the map in place (letterboxed to the live *view* aspect)."""

        canvas = self._canvas
        counts = world.counts_by_kind()
        count_bits = "  ".join(f"{k}:{n}" for k, n in sorted(counts.items()) if n)
        phases = world.phase_counts()
        phase_bits = "  ".join(f"{k}:{n}" for k, n in sorted(phases.items()) if n)
        # View is aspect-locked to the camera band; letterbox the full view so
        # the true camera rect is a correct subset (not the whole plate).
        view_aspect = world.view_width / world.view_height
        hole_note = f"  holes:{len(holes)}" if holes else ""
        hunt1 = len(world.threats_targeting(1))
        hunt2 = len(world.threats_targeting(2))
        hunt_note = ""
        if hunt1 or hunt2:
            hunt_note = f"  hunt P1:{hunt1} P2:{hunt2}"
        meta = (
            f"cam X={world.camera_x}  "
            f"lane 0..{world.camera_bottom:.0f}  "
            f"{count_bits or 'empty'}  "
            f"{phase_bits}{hole_note}{hunt_note}"
        )
        if meta != self._last_meta_text:
            self._last_meta_text = meta
            self._map_meta.configure(text=meta)

        w = max(int(canvas.winfo_width()), 2)
        h = max(int(canvas.winfo_height()), 2)
        if w < 8 or h < 8:
            return

        pad = MAP_INNER_PAD
        ox, oy, plot_w, plot_h = _letterboxed_plot(w, h, pad, aspect=view_aspect)

        size = (w, h)
        plot_geom = (ox, oy, plot_w, plot_h)
        if (
            size != self._last_canvas_size
            or plot_geom != self._last_plot_geom
            or self._bg_rect is None
        ):
            self._last_canvas_size = size
            self._last_plot_geom = plot_geom
            self._ensure_static_plate(w, h, ox, oy, plot_w, plot_h)

        # Map plate = wide *view* (camera + off-screen ring). Inner camera rect
        # is the player walk band (32..288 × 0..lane), not the full 320 CRT.
        x0 = _map_x(world.camera_left, world, ox, plot_w)
        x1 = _map_x(world.camera_right, world, ox, plot_w)
        y0 = _map_y(world.camera_top, world, oy, plot_h)
        y1 = _map_y(world.camera_bottom, world, oy, plot_h)
        if self._cam_rect is None:
            self._cam_rect = canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                fill="#161a28",
                outline="#5a6484",
                width=2,
                dash=(4, 2),
                tags=("cam",),
            )
            self._cam_label = canvas.create_text(
                x0 + 4,
                y0 + 2,
                text="camera",
                anchor="nw",
                fill=_DIM,
                font=self._font_map_tiny,
                tags=("cam",),
            )
        else:
            canvas.coords(self._cam_rect, x0, y0, x1, y1)
            canvas.coords(self._cam_label, x0 + 4, y0 + 2)

        # Floor holes: one filled rect per connected pit (under actors).
        self._ensure_hole_pool(len(holes))
        for index, hole in enumerate(holes):
            hx0 = _map_x(hole.world_x - world.camera_x, world, ox, plot_w)
            hy0 = _map_y(float(hole.lane_y), world, oy, plot_h)
            hx1 = _map_x(hole.world_x_end - world.camera_x, world, ox, plot_w)
            hy1 = _map_y(float(hole.lane_y_end), world, oy, plot_h)
            hx0 = max(ox, min(ox + plot_w, hx0))
            hx1 = max(ox, min(ox + plot_w, hx1))
            hy0 = max(oy, min(oy + plot_h, hy0))
            hy1 = max(oy, min(oy + plot_h, hy1))
            rid = self._hole_rects[index]
            if hx1 - hx0 >= 2 and hy1 - hy0 >= 2:
                canvas.coords(rid, hx0, hy0, hx1, hy1)
                canvas.itemconfigure(rid, state="normal")
                # Holes above the camera band so they stay visible inside it.
                canvas.tag_raise(rid, "cam")
            else:
                canvas.itemconfigure(rid, state="hidden")
        for index in range(len(holes), len(self._hole_rects)):
            canvas.itemconfigure(self._hole_rects[index], state="hidden")

        # Fallback marker size for an entity with no real Hitbox this tick
        # (no RomData, or a frame whose body box id is 0) -- unchanged from
        # before real hitboxes existed.
        half = max(7, min(16, int(min(plot_w, plot_h) / 40)))
        boss_half = half + 2

        entities = sorted(
            world.entities,
            key=lambda e: (_KIND_Z.get(e.kind, 4), e.world_y, e.world_x),
        )
        self._ensure_marker_pool(len(entities))
        # Upper bound: some entities will fall outside the plot and draw none
        # of their ranges, so this only ever over-allocates, never under-.
        self._ensure_range_pool(sum(len(e.attack_ranges) for e in entities))

        plot_left = ox
        plot_right = ox + plot_w
        plot_top = oy
        plot_bottom = oy + plot_h
        drawn = 0
        ranges_drawn = 0

        for entity in entities:
            # map_x = cam-relative X; map_y = absolute lane (top-down, Z ignored).
            # Draw on-camera *and* off-camera actors that fall inside the view.
            cx = _map_x(entity.map_x, world, ox, plot_w)
            cy = _map_y(entity.map_y, world, oy, plot_h)
            if not (plot_left <= cx <= plot_right and plot_top <= cy <= plot_bottom):
                continue
            if drawn >= len(self._markers):
                self._ensure_marker_pool(drawn + 1)
            square_id, text_id = self._markers[drawn]
            if entity.hitbox is not None:
                sx0, sy0, sx1, sy1 = _hitbox_to_canvas(entity.hitbox, world, ox, oy, plot_w, plot_h)
                sx0, sx1 = _expand_to_min(sx0, sx1, MIN_MARKER_PX)
                sy0, sy1 = _expand_to_min(sy0, sy1, MIN_MARKER_PX)
            else:
                r = boss_half if entity.kind in ("player", "boss") else half
                sx0, sy0, sx1, sy1 = cx - r, cy - r, cx + r, cy + r
            canvas.coords(square_id, sx0, sy0, sx1, sy1)
            outline = phase_color(
                CombatPhase.DEATH if entity.is_defeated else entity.combat_phase
            )
            if not outline:
                # Idle / non-combat: use the family colour as a thin outline.
                outline = entity.color
            # Dim letters slightly when outside the true camera rectangle.
            in_camera = (
                world.camera_left <= entity.map_x <= world.camera_right
                and world.camera_top <= entity.map_y <= world.camera_bottom
            )
            letter_fill = entity.color if in_camera else _DIM
            canvas.itemconfigure(
                square_id,
                state="normal",
                fill="",  # letter only — state is the square outline
                outline=outline,
                width=2,
            )
            # Letter stays at the entity's own position, not the (possibly
            # off-centre, per a lane-offset attack box) hitbox centre.
            canvas.coords(text_id, cx, cy)
            # Single letter/symbol — no phase suffix (outline carries state).
            canvas.itemconfigure(
                text_id,
                state="normal",
                text=entity.symbol,
                fill=letter_fill,
            )
            # Markers above holes and camera.
            canvas.tag_raise(square_id)
            canvas.tag_raise(text_id)
            drawn += 1

            for attack_range in entity.attack_ranges:
                projected = attack_range.projected(
                    world_x=entity.world_x,
                    lane_y=entity.world_y,
                    world_z=entity.world_z,
                    facing_left=entity.facing_left,
                )
                rx0, ry0, rx1, ry1 = _hitbox_to_canvas(projected, world, ox, oy, plot_w, plot_h)
                rx0 = max(plot_left, min(plot_right, rx0))
                rx1 = max(plot_left, min(plot_right, rx1))
                ry0 = max(plot_top, min(plot_bottom, ry0))
                ry1 = max(plot_top, min(plot_bottom, ry1))
                if rx1 - rx0 < 2 or ry1 - ry0 < 2:
                    continue
                if ranges_drawn >= len(self._range_rects):
                    self._ensure_range_pool(ranges_drawn + 1)
                range_id = self._range_rects[ranges_drawn]
                canvas.coords(range_id, rx0, ry0, rx1, ry1)
                canvas.itemconfigure(range_id, state="normal")
                # Below the marker/letter, above holes and the camera plate.
                canvas.tag_raise(range_id, "cam")
                canvas.tag_lower(range_id, "marker")
                ranges_drawn += 1

        for index in range(drawn, len(self._markers)):
            square_id, text_id = self._markers[index]
            canvas.itemconfigure(square_id, state="hidden")
            canvas.itemconfigure(text_id, state="hidden")
        for index in range(ranges_drawn, len(self._range_rects)):
            canvas.itemconfigure(self._range_rects[index], state="hidden")

        empty_cx = ox + plot_w / 2
        empty_cy = oy + plot_h / 2
        if self._empty_label is None:
            self._empty_label = canvas.create_text(
                empty_cx,
                empty_cy,
                text="no mapped actors",
                fill="#3a3f55",
                font=self._font_small,
                tags=("empty",),
            )
        else:
            canvas.coords(self._empty_label, empty_cx, empty_cy)
        canvas.itemconfigure(
            self._empty_label,
            state="normal" if drawn == 0 else "hidden",
        )
        if drawn == 0:
            canvas.tag_raise(self._empty_label)

    def _ensure_static_plate(
        self,
        w: int,
        h: int,
        ox: float,
        oy: float,
        plot_w: float,
        plot_h: float,
    ) -> None:
        """Create or resize the letterboxed plot plate."""

        canvas = self._canvas
        if self._bg_rect is None:
            self._bg_rect = canvas.create_rectangle(
                0, 0, w, h, fill="#0a0b10", outline="", tags=("static",)
            )
            self._plot_rect = canvas.create_rectangle(
                ox,
                oy,
                ox + plot_w,
                oy + plot_h,
                fill="#11131c",
                outline="#2a2e40",
                tags=("static",),
            )
            self._grid_lines = []
            for frac in (0.25, 0.5, 0.75):
                y = oy + plot_h * frac
                self._grid_lines.append(
                    canvas.create_line(
                        ox, y, ox + plot_w, y, fill="#1c2030", tags=("static",)
                    )
                )
        else:
            canvas.coords(self._bg_rect, 0, 0, w, h)
            canvas.coords(self._plot_rect, ox, oy, ox + plot_w, oy + plot_h)
            for i, frac in enumerate((0.25, 0.5, 0.75)):
                y = oy + plot_h * frac
                canvas.coords(self._grid_lines[i], ox, y, ox + plot_w, y)

        canvas.tag_lower("static")
        if self._cam_rect is not None:
            canvas.tag_raise("cam", "static")

    def _ensure_hole_pool(self, count: int) -> None:
        canvas = self._canvas
        while len(self._hole_rects) < count:
            self._hole_rects.append(
                canvas.create_rectangle(
                    0,
                    0,
                    0,
                    0,
                    fill="#0c1929",
                    outline="#0ea5e9",
                    width=2,
                    stipple="gray50",
                    state="hidden",
                    tags=("hole",),
                )
            )

    def _ensure_range_pool(self, count: int) -> None:
        """Grow the reusable ``AttackRange`` square pool to at least ``count``.

        One rectangle per (entity, AttackRange) pair, not per entity: an
        enemy with several confirmed attacks (Garcia types $21/$22's own
        two-stage strike, e.g.) gets one square each. ``_RANGE_FILL`` is a
        pre-blended solid colour rather than a real alpha fill (Tk canvas
        items have none) -- so unlike true translucency, two overlapping
        squares do not compound into a darker shade; whichever is drawn last
        simply covers the other at the same fixed opacity.
        """

        canvas = self._canvas
        while len(self._range_rects) < count:
            self._range_rects.append(
                canvas.create_rectangle(
                    0,
                    0,
                    0,
                    0,
                    fill=_RANGE_FILL,
                    outline="",
                    state="hidden",
                    tags=("range",),
                )
            )

    def _ensure_marker_pool(self, count: int) -> None:
        """Grow the reusable square-outline/text pool to at least ``count``."""

        canvas = self._canvas
        while len(self._markers) < count:
            square_id = canvas.create_rectangle(
                0,
                0,
                0,
                0,
                fill="",
                outline="#888",
                width=2,
                state="hidden",
                tags=("marker",),
            )
            text_id = canvas.create_text(
                0,
                0,
                text="",
                fill="#ffffff",
                font=self._font_map,
                state="hidden",
                tags=("marker",),
            )
            self._markers.append((square_id, text_id))


def _letterboxed_plot(
    canvas_w: int,
    canvas_h: int,
    pad: int,
    *,
    aspect: float = MAP_ASPECT,
) -> tuple[float, float, float, float]:
    """Return (ox, oy, plot_w, plot_h) letterboxed to ``aspect`` inside the pad."""

    if aspect <= 0:
        aspect = MAP_ASPECT
    avail_w = max(canvas_w - 2 * pad, 1)
    avail_h = max(canvas_h - 2 * pad, 1)
    if avail_w / avail_h > aspect:
        plot_h = float(avail_h)
        plot_w = plot_h * aspect
    else:
        plot_w = float(avail_w)
        plot_h = plot_w / aspect
    ox = pad + (avail_w - plot_w) / 2.0
    oy = pad + (avail_h - plot_h) / 2.0
    return ox, oy, plot_w, plot_h


def _map_x(map_x: float, world: WorldMap, ox: float, plot_w: float) -> float:
    """Project camera-relative map X into the full *view* plate."""

    t = (map_x - world.view_left) / world.view_width
    return ox + t * plot_w


def _map_y(map_y: float, world: WorldMap, oy: float, plot_h: float) -> float:
    """Project lane Y into the full *view* plate. Larger Y → front (down)."""

    t = (map_y - world.view_top) / world.view_height
    return oy + t * plot_h


def _hitbox_to_canvas(
    hitbox: Hitbox, world: WorldMap, ox: float, oy: float, plot_w: float, plot_h: float
) -> tuple[float, float, float, float]:
    """Project an absolute-world ``Hitbox`` into canvas coordinates.

    X needs the camera offset first (``map_x = world_x - camera_x``, per
    ``world_map.project_to_map``); the lane axis is already absolute in both
    coordinate systems, so ``hitbox.y0``/``y1`` go straight into ``_map_y``.
    """

    x0 = _map_x(hitbox.x0 - world.camera_x, world, ox, plot_w)
    x1 = _map_x(hitbox.x1 - world.camera_x, world, ox, plot_w)
    y0 = _map_y(hitbox.y0, world, oy, plot_h)
    y1 = _map_y(hitbox.y1, world, oy, plot_h)
    return x0, y0, x1, y1


def _expand_to_min(a: float, b: float, minimum: float) -> tuple[float, float]:
    """Widen ``(a, b)`` symmetrically about its centre to at least ``minimum``.

    Only ever grows, never shrinks a real box -- purely a visibility floor
    for a hitbox that projects to a sliver at a zoomed-out view.
    """

    span = b - a
    if span >= minimum:
        return a, b
    pad = (minimum - span) / 2.0
    return a - pad, b + pad


def _describe_verb(verb: Verb | None) -> str:
    """One-line label for whichever ``Verb`` determine_priority_verb
    kept, using the field names shared across the ``ai`` package's Verb
    subclasses (``target_slot``/``threat_slot``/``direction``/coordinate)
    rather than special-casing every concrete class here."""

    if verb is None:
        return "—  (no button)"
    name = type(verb).__name__
    parts: list[str] = []
    direction = getattr(verb, "direction", None)
    if direction is not None:
        parts.append(str(direction))
    target = getattr(verb, "target_slot", None) or getattr(verb, "threat_slot", None)
    if target is not None:
        parts.append(f"→{target}")
    elif hasattr(verb, "target_x") and hasattr(verb, "target_y"):
        parts.append(f"→({verb.target_x},{verb.target_y})")
    if parts:
        return f"{name}  ({' '.join(parts)})"
    return name


def _describe_pending(pending: tuple[Verb, ...]) -> str:
    """One-line label for every candidate ``Verb`` the AI considered
    before ``determine_priority_verb`` collapsed them to one."""

    if not pending:
        return ""
    names = ", ".join(_describe_verb(verb) for verb in pending)
    return f"Pending  {names}"


def _health_bar(player: PlayerSnapshot, width: int = 16) -> str:
    if player.health is None or player.health_percent is None:
        return "—  (no live object)"
    filled = int(round((player.health_percent / 100.0) * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar}  {player.health_percent:5.1f}%  ({player.health}/{0x50})"
