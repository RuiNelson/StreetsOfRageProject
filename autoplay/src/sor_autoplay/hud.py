"""Maximized-window HUD: 3-column status bar + map filling remaining space."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from .phases import CombatPhase, phase_color
from .state import GameSnapshot, PlayerSnapshot
from .world_map import MAP_ASPECT, WorldMap

OUTER_PAD = 12
STATUS_GAP = 10
MAP_INNER_PAD = 10
# GUI paint only; remote sampling uses its own wall-clock poll period.
HUD_PAINT_MS_DEFAULT = 33

_BG = "#050508"
_CARD = "#12131a"
_BORDER = "#3a3f55"
_TEXT = "#d7dbe8"
_MUTED = "#8b90a5"
_DIM = "#5c6178"

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
    """Maximized window: state/P1/P2 columns on top; map takes the rest."""

    def __init__(
        self,
        *,
        title: str = "SoR Autoplay",
        subtitle: str = "live replica",
        on_close: Callable[[], None] | None = None,
        on_toggle_agent: Callable[[int], bool] | None = None,
        agent_config_provider: Callable[[], object] | None = None,
        agent_notes_provider: Callable[[], tuple[str, str]] | None = None,
    ) -> None:
        self._on_close = on_close
        self._on_toggle_agent = on_toggle_agent
        self._agent_config_provider = agent_config_provider
        self._agent_notes_provider = agent_notes_provider
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
        self._markers: list[tuple[int, int]] = []  # (disc_id, text_id)
        self._hole_rects: list[int] = []
        self._last_canvas_size: tuple[int, int] = (0, 0)
        self._last_plot_geom: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._last_meta_text: str = ""

        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=_BG)
        self.root.minsize(720, 420)
        self._start_maximized()
        self.root.bind("<Escape>", self._handle_close)
        self.root.bind("<q>", self._handle_close)
        self.root.bind("1", lambda _e: self._toggle_agent(1))
        self.root.bind("2", lambda _e: self._toggle_agent(2))
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
            text="Esc/Q quit · 1/2 toggle AI · std controls (B atk C jump A special)",
            font=self._font_small,
            fg=_DIM,
        )

        # P1 column
        self._p1_title = self._heading(self._col_p1, "P1", fg="#9ecbff")
        self._p1_header = self._label(self._col_p1, fg="#9ecbff")
        self._p1_health = self._label(self._col_p1, mono=True)
        self._p1_stats = self._label(self._col_p1, mono=True)
        self._p1_score = self._label(self._col_p1, mono=True)
        self._p1_agent_btn = self._agent_button(self._col_p1, 1, "#9ecbff")
        self._p1_agent_note = self._label(self._col_p1, font=self._font_small, fg=_MUTED)

        # P2 column (always present for a stable 3-column layout)
        self._p2_title = self._heading(self._col_p2, "P2", fg="#ffb3c7")
        self._p2_header = self._label(self._col_p2, fg="#ffb3c7")
        self._p2_health = self._label(self._col_p2, mono=True)
        self._p2_stats = self._label(self._col_p2, mono=True)
        self._p2_score = self._label(self._col_p2, mono=True)
        self._p2_agent_btn = self._agent_button(self._col_p2, 2, "#ffb3c7")
        self._p2_agent_note = self._label(self._col_p2, font=self._font_small, fg=_MUTED)

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
                "1/2 players   G Garcia  S Signal  H Haku-Ro  N Nora  J Jack   B boss   "
                "outline: green=down  orange=charge  red=atk  cyan=block  purple=held   "
                "symbol suffix = phase (d/c/a/…)   k/b weapons  a/+ food"
            ),
            fg=_DIM,
            bg=_CARD,
            font=self._font_map_tiny,
            anchor="w",
            justify=tk.LEFT,
        )
        self._map_legend.pack(fill=tk.X, padx=10, pady=(0, 8))

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

    def _agent_button(self, parent: tk.Frame, player_index: int, accent: str) -> tk.Button:
        btn = tk.Button(
            parent,
            text=f"AI P{player_index}: OFF",
            command=lambda: self._toggle_agent(player_index),
            bg="#1c1f2b",
            fg=accent,
            activebackground="#2a2f42",
            activeforeground=accent,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=_BORDER,
            font=self._font_small,
            padx=8,
            pady=4,
            cursor="hand2",
        )
        btn.pack(anchor="w", pady=(6, 0))
        return btn

    def _toggle_agent(self, player_index: int) -> None:
        if self._on_toggle_agent is None:
            return
        self._on_toggle_agent(player_index)
        self._refresh_agent_buttons()

    def _refresh_agent_buttons(self) -> None:
        p1_on = False
        p2_on = False
        if self._agent_config_provider is not None:
            cfg = self._agent_config_provider()
            p1_on = bool(getattr(cfg, "p1_enabled", False))
            p2_on = bool(getattr(cfg, "p2_enabled", False))
        self._p1_agent_btn.configure(
            text=f"AI P1: {'ON' if p1_on else 'OFF'}  (key 1)",
            bg="#1a3d2e" if p1_on else "#1c1f2b",
            fg="#5ddea0" if p1_on else "#9ecbff",
        )
        self._p2_agent_btn.configure(
            text=f"AI P2: {'ON' if p2_on else 'OFF'}  (key 2)",
            bg="#3d1a28" if p2_on else "#1c1f2b",
            fg="#5ddea0" if p2_on else "#ffb3c7",
        )

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

    def _start_maximized(self) -> None:
        self.root.attributes("-fullscreen", False)
        self.root.after_idle(self._apply_maximized)

    def _apply_maximized(self) -> None:
        self.root.update_idletasks()
        try:
            self.root.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            self.root.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass
        if sys.platform == "darwin":
            try:
                self.root.tk.call("wm", "state", self.root._w, "zoomed")  # noqa: SLF001
                return
            except tk.TclError:
                pass
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f"{width}x{height}+0+0")

    def _pick_font_family(self) -> str:
        available = set(tkfont.families())
        for name in ("SF Mono", "Menlo", "Monaco", "Consolas", "Courier New", "TkFixedFont"):
            if name in available:
                return name
        return "TkDefaultFont"

    def _handle_close(self, _event: object | None = None) -> None:
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

    def update(self, snapshot: GameSnapshot) -> None:
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

        self._refresh_agent_buttons()
        notes = ("", "")
        if self._agent_notes_provider is not None:
            notes = self._agent_notes_provider()
        h1 = len(snapshot.world_map.threats_targeting(1))
        h2 = len(snapshot.world_map.threats_targeting(2))
        p1_ai = notes[0] if notes[0] else "—"
        p2_ai = notes[1] if notes[1] else "—"
        self._p1_agent_note.configure(
            text=f"AI: {p1_ai}" + (f"  ·  hunted×{h1}" if h1 else "")
        )
        self._p2_agent_note.configure(
            text=f"AI: {p2_ai}" + (f"  ·  hunted×{h2}" if h2 else "")
        )

        self._latest_map = snapshot.world_map
        self._latest_holes = snapshot.floor_holes
        self._draw_map(snapshot.world_map, snapshot.floor_holes)

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
        """Update the map in place (letterboxed to the live camera aspect)."""

        canvas = self._canvas
        counts = world.counts_by_kind()
        count_bits = "  ".join(f"{k}:{n}" for k, n in sorted(counts.items()) if n)
        phases = world.phase_counts()
        phase_bits = "  ".join(f"{k}:{n}" for k, n in sorted(phases.items()) if n)
        cam_aspect = world.camera_width / world.camera_height
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
        ox, oy, plot_w, plot_h = _letterboxed_plot(w, h, pad, aspect=cam_aspect)

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

        # Camera frustum: fixed world aspect MAP_ASPECT → same on screen after letterbox.
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
                outline="#3d4663",
                dash=(3, 2),
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

        marker_r = max(6, min(14, int(min(plot_w, plot_h) / 48)))
        boss_r = marker_r + 2

        entities = sorted(
            world.entities,
            key=lambda e: (_KIND_Z.get(e.kind, 4), e.world_y, e.world_x),
        )
        self._ensure_marker_pool(len(entities))

        plot_left = ox
        plot_right = ox + plot_w
        plot_top = oy
        plot_bottom = oy + plot_h
        drawn = 0

        for entity in entities:
            # map_x = cam-relative X; map_y = absolute lane (top-down, Z ignored).
            cx = _map_x(entity.map_x, world, ox, plot_w)
            cy = _map_y(entity.map_y, world, oy, plot_h)
            if not (plot_left <= cx <= plot_right and plot_top <= cy <= plot_bottom):
                continue
            if drawn >= len(self._markers):
                self._ensure_marker_pool(drawn + 1)
            disc_id, text_id = self._markers[drawn]
            r = boss_r if entity.kind in ("player", "boss") else marker_r
            canvas.coords(disc_id, cx - r, cy - r, cx + r, cy + r)
            outline = phase_color(
                CombatPhase.DEATH if entity.is_defeated else entity.combat_phase
            )
            canvas.itemconfigure(
                disc_id,
                state="normal",
                fill=entity.color,
                outline=outline if outline else "#1a1b22",
                width=3 if outline else 1,
            )
            canvas.coords(text_id, cx, cy)
            # Symbol; combatants append a 1-char phase hint when not idle.
            symbol = entity.symbol
            if entity.kind in ("enemy", "boss") and entity.phase_tag not in (
                "idle",
                "?",
            ):
                symbol = f"{entity.symbol}{entity.phase_tag[0]}"
            canvas.itemconfigure(
                text_id,
                state="normal",
                text=symbol,
                fill=entity.color,
            )
            # Markers above holes and camera.
            canvas.tag_raise(disc_id)
            canvas.tag_raise(text_id)
            drawn += 1

        for index in range(drawn, len(self._markers)):
            disc_id, text_id = self._markers[index]
            canvas.itemconfigure(disc_id, state="hidden")
            canvas.itemconfigure(text_id, state="hidden")

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

    def _ensure_marker_pool(self, count: int) -> None:
        """Grow the reusable disc/text pool to at least ``count`` markers."""

        canvas = self._canvas
        while len(self._markers) < count:
            disc_id = canvas.create_oval(
                0,
                0,
                0,
                0,
                fill="#050508",
                outline="",
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
            self._markers.append((disc_id, text_id))


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
    t = (map_x - world.view_left) / world.view_width
    return ox + t * plot_w


def _map_y(map_y: float, world: WorldMap, oy: float, plot_h: float) -> float:
    # Larger lane Y → lower on the canvas (front of the stage).
    t = (map_y - world.view_top) / world.view_height
    return oy + t * plot_h


def _health_bar(player: PlayerSnapshot, width: int = 16) -> str:
    if player.health is None or player.health_percent is None:
        return "—  (no live object)"
    filled = int(round((player.health_percent / 100.0) * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar}  {player.health_percent:5.1f}%  ({player.health}/{0x50})"
