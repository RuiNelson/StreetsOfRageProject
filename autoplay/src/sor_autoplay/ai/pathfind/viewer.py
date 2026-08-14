"""A Tk window for looking at what the path finder actually does.

Not part of the AI, and not connected to anything: this window never talks
to a running ``sor``, never reads RAM, and imports nothing from the rest of
``sor_autoplay`` -- not even the game's own HUD. It only imports this
package and ``tkinter``. Draw a body, draw obstacles, pick a destination,
and look at the vectors that come back.

It exists because every test in ``tests/ai/pathfind/`` asserts a *property*
("the route never overlaps the crate", "the right edge stopped at x=160").
Those catch regressions, but they cannot show whether the route a human
would call sensible is the route that comes out -- how a corridor one body
wide is threaded, what the minimum step length does to a detour, where a
best-effort route gives up. That is a question for eyes.

Launch it with a Python that has Tk (the default ``python3`` on this machine
does not)::

    cd autoplay
    PYTHONPATH=src python3.11 -m sor_autoplay.ai.pathfind.viewer

Everything on screen is computed through the package's public API --
``find_path``, ``Path.positions``, the three goal classes -- so what the
window shows is what a caller gets, with no drawing-only geometry in
between.
"""

from __future__ import annotations

import argparse
import tkinter as tk
from dataclasses import dataclass

from .geometry import Edge, Point, Rect, Segment
from .goals import Goal, PointGoal, RectGoal, SegmentGoal
from .grid import Lattice
from .search import DEFAULT_MAX_NODES, Path, find_path

# The SoR walkable band, as a familiar default rather than a dependency --
# nothing here reads the game's real bounds.
DEFAULT_WORLD = Rect(0, 0, 320, 112)
DEFAULT_BODY = Rect(16, 16, 16, 16)
DEFAULT_STEP = 8

_BG = "#050508"
_CARD = "#12131a"
_PLOT_BG = "#11131c"
_BORDER = "#3a3f55"
_TEXT = "#d7dbe8"
_MUTED = "#8b90a5"
_DIM = "#5c6178"

_BODY = "#63b3ff"
_BODY_GHOST = "#2f5f8f"
_OBSTACLE = "#7a3550"
_OBSTACLE_EDGE = "#c8577f"
_GOAL = "#ffd166"
_GOAL_EDGE = "#ff9f1c"
_ROUTE = "#5ce1a0"
_FAIL = "#ff6b6b"

# Tk's `stipple` is silently solid on Aqua (macOS): a stippled fill draws the
# pattern's colour flat instead of dithering it. Translucency is therefore
# pre-blended against the known plot background, the same trade the game HUD
# makes for the identical reason.
def _blend(fg: str, bg: str, alpha: float) -> str:
    fr, fgc, fb = int(fg[1:3], 16), int(fg[3:5], 16), int(fg[5:7], 16)
    br, bgc, bb = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
    return "#%02x%02x%02x" % (
        round(fr * alpha + br * (1 - alpha)),
        round(fgc * alpha + bgc * (1 - alpha)),
        round(fb * alpha + bb * (1 - alpha)),
    )


MODES = (
    ("body", "Corpo"),
    ("obstacle", "Obstáculo"),
    ("goal", "Destino"),
    ("erase", "Apagar"),
)

GOAL_TYPES = (
    ("point", "Ponto"),
    ("segment", "Segmento"),
    ("rect", "Rectângulo"),
)

BODY_EDGES = (
    (Edge.TOP, "topo"),
    (Edge.BOTTOM, "fundo"),
    (Edge.LEFT, "esquerda"),
    (Edge.RIGHT, "direita"),
)

# The four *facing* pairings, the ones `RectGoal.horizontal`/`.vertical` are
# built from. The aligned pairings (top on top) live behind their own
# checkbox because two same-height boxes satisfy them side by side, which
# reads as a bug when it was not asked for.
FACING_PAIRS = (
    ((Edge.BOTTOM, Edge.TOP), "meu fundo → topo do alvo"),
    ((Edge.TOP, Edge.BOTTOM), "meu topo → fundo do alvo"),
    ((Edge.RIGHT, Edge.LEFT), "minha direita → esquerda do alvo"),
    ((Edge.LEFT, Edge.RIGHT), "minha esquerda → direita do alvo"),
)

ALIGNED_PAIRS = (
    (Edge.TOP, Edge.TOP),
    (Edge.BOTTOM, Edge.BOTTOM),
    (Edge.LEFT, Edge.LEFT),
    (Edge.RIGHT, Edge.RIGHT),
)

# Above this the lattice is a grey wash rather than information.
MAX_LATTICE_DOTS = 6000


@dataclass
class Scene:
    """Everything the window lets you draw."""

    world: Rect
    body: Rect
    obstacles: list[Rect]
    goal_point: Point | None = None
    goal_segment: Segment | None = None
    goal_rect: Rect | None = None


class PathfindViewer:
    """The window itself: canvas on the left, controls on the right."""

    def __init__(
        self,
        *,
        world: Rect = DEFAULT_WORLD,
        body: Rect = DEFAULT_BODY,
        step: int = DEFAULT_STEP,
    ) -> None:
        self.scene = Scene(world=world, body=body, obstacles=[])
        self.path: Path | None = None
        self.error: str | None = None
        self._drag: tuple[float, float] | None = None
        self._scale = 1.0
        self._origin = (0.0, 0.0)

        self.root = tk.Tk()
        self.root.title("Path finder")
        self.root.configure(bg=_BG)
        self.root.geometry("1180x680")
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

        self.mode = tk.StringVar(value="obstacle")
        self.goal_type = tk.StringVar(value="point")
        self.step = tk.IntVar(value=step)
        self.tolerance = tk.IntVar(value=0)
        self.max_nodes = tk.IntVar(value=DEFAULT_MAX_NODES)
        self.allow_diagonals = tk.BooleanVar(value=True)
        self.target_is_obstacle = tk.BooleanVar(value=True)
        self.include_aligned = tk.BooleanVar(value=False)
        self.show_lattice = tk.BooleanVar(value=False)
        self.show_stops = tk.BooleanVar(value=True)
        self.show_lengths = tk.BooleanVar(value=True)
        self.segment_edges = {edge: tk.BooleanVar(value=edge is Edge.RIGHT) for edge, _ in BODY_EDGES}
        self.rect_pairs = {
            pair: tk.BooleanVar(value=pair in (FACING_PAIRS[0][0], FACING_PAIRS[1][0]))
            for pair, _ in FACING_PAIRS
        }

        self._build_toolbar()
        self._build_body()
        self._build_status()

        for var in (
            self.goal_type,
            self.step,
            self.tolerance,
            self.max_nodes,
            self.allow_diagonals,
            self.target_is_obstacle,
            self.include_aligned,
            self.show_lattice,
            self.show_stops,
            self.show_lengths,
            *self.segment_edges.values(),
            *self.rect_pairs.values(),
        ):
            var.trace_add("write", lambda *_a: self._replan())

        self._replan()

    # ---------------------------------------------------------------- build

    def _build_toolbar(self) -> None:
        bar = tk.Frame(self.root, bg=_BG)
        bar.pack(fill=tk.X, padx=12, pady=(12, 6))

        tk.Label(bar, text="Modo:", bg=_BG, fg=_MUTED, font=("Helvetica", 11)).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        for value, label in MODES:
            tk.Radiobutton(
                bar,
                text=label,
                value=value,
                variable=self.mode,
                indicatoron=False,
                bg=_CARD,
                fg=_TEXT,
                selectcolor=_BORDER,
                activebackground=_BORDER,
                activeforeground=_TEXT,
                relief=tk.FLAT,
                padx=12,
                pady=4,
                highlightthickness=0,
                borderwidth=0,
            ).pack(side=tk.LEFT, padx=2)

        tk.Button(
            bar,
            text="Limpar obstáculos",
            command=self._clear_obstacles,
            bg=_CARD,
            fg=_TEXT,
            activebackground=_BORDER,
            activeforeground=_TEXT,
            relief=tk.FLAT,
            highlightthickness=0,
            borderwidth=0,
            padx=10,
            pady=4,
        ).pack(side=tk.RIGHT, padx=2)
        tk.Button(
            bar,
            text="Limpar tudo",
            command=self._clear_all,
            bg=_CARD,
            fg=_TEXT,
            activebackground=_BORDER,
            activeforeground=_TEXT,
            relief=tk.FLAT,
            highlightthickness=0,
            borderwidth=0,
            padx=10,
            pady=4,
        ).pack(side=tk.RIGHT, padx=2)

    def _build_body(self) -> None:
        middle = tk.Frame(self.root, bg=_BG)
        middle.pack(fill=tk.BOTH, expand=True, padx=12)

        self.canvas = tk.Canvas(
            middle,
            bg=_PLOT_BG,
            highlightthickness=1,
            highlightbackground=_BORDER,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        panel = tk.Frame(middle, bg=_CARD, width=270)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        panel.pack_propagate(False)
        self._build_panel(panel)

    def _build_panel(self, panel: tk.Frame) -> None:
        self._heading(panel, "Destino")
        for value, label in GOAL_TYPES:
            tk.Radiobutton(
                panel,
                text=label,
                value=value,
                variable=self.goal_type,
                bg=_CARD,
                fg=_TEXT,
                selectcolor=_CARD,
                activebackground=_CARD,
                activeforeground=_TEXT,
                highlightthickness=0,
                anchor="w",
            ).pack(fill=tk.X, padx=10)

        # Only the controls that apply to the current goal type are packed;
        # _sync_panel swaps them.
        self._point_box = tk.Frame(panel, bg=_CARD)
        self._spin(self._point_box, "tolerância", self.tolerance, 0, 64)

        self._segment_box = tk.Frame(panel, bg=_CARD)
        tk.Label(
            self._segment_box,
            text="arestas do corpo que contam",
            bg=_CARD,
            fg=_MUTED,
            font=("Helvetica", 10),
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(6, 0))
        for edge, label in BODY_EDGES:
            self._check(self._segment_box, label, self.segment_edges[edge])

        self._rect_box = tk.Frame(panel, bg=_CARD)
        tk.Label(
            self._rect_box,
            text="pares de arestas que contam",
            bg=_CARD,
            fg=_MUTED,
            font=("Helvetica", 10),
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(6, 0))
        for pair, label in FACING_PAIRS:
            self._check(self._rect_box, label, self.rect_pairs[pair])
        self._check(self._rect_box, "incluir pares alinhados", self.include_aligned)
        self._check(self._rect_box, "alvo também é obstáculo", self.target_is_obstacle)
        presets = tk.Frame(self._rect_box, bg=_CARD)
        presets.pack(fill=tk.X, padx=10, pady=(4, 0))
        tk.Button(
            presets,
            text="Horizontal",
            command=lambda: self._preset(horizontal=True),
            bg=_BORDER,
            fg=_TEXT,
            relief=tk.FLAT,
            highlightthickness=0,
            borderwidth=0,
            padx=8,
        ).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(
            presets,
            text="Vertical",
            command=lambda: self._preset(horizontal=False),
            bg=_BORDER,
            fg=_TEXT,
            relief=tk.FLAT,
            highlightthickness=0,
            borderwidth=0,
            padx=8,
        ).pack(side=tk.LEFT)

        self._heading(panel, "Procura")
        self._spin(panel, "passo mínimo", self.step, 1, 64)
        self._spin(panel, "máx. nós", self.max_nodes, 10, 200_000, increment=1000)
        self._check(panel, "diagonais", self.allow_diagonals)

        self._heading(panel, "Desenho")
        self._check(panel, "mostrar lattice", self.show_lattice)
        self._check(panel, "mostrar paragens", self.show_stops)
        self._check(panel, "mostrar comprimentos", self.show_lengths)

        self._hint = tk.Label(
            panel,
            text="",
            bg=_CARD,
            fg=_DIM,
            font=("Helvetica", 10),
            wraplength=250,
            justify=tk.LEFT,
            anchor="w",
        )
        self._hint.pack(fill=tk.X, padx=10, pady=10, side=tk.BOTTOM)

    def _build_status(self) -> None:
        self.status = tk.Label(
            self.root,
            text="",
            bg=_BG,
            fg=_TEXT,
            font=("Helvetica", 11),
            anchor="w",
            justify=tk.LEFT,
            wraplength=1100,
        )
        self.status.pack(fill=tk.X, padx=12, pady=(6, 12))

    def _heading(self, parent: tk.Frame, text: str) -> None:
        tk.Label(
            parent,
            text=text.upper(),
            bg=_CARD,
            fg=_MUTED,
            font=("Helvetica", 10, "bold"),
            anchor="w",
        ).pack(fill=tk.X, padx=10, pady=(12, 4))

    def _check(self, parent: tk.Frame, label: str, var: tk.BooleanVar) -> None:
        tk.Checkbutton(
            parent,
            text=label,
            variable=var,
            bg=_CARD,
            fg=_TEXT,
            selectcolor=_CARD,
            activebackground=_CARD,
            activeforeground=_TEXT,
            highlightthickness=0,
            anchor="w",
        ).pack(fill=tk.X, padx=10)

    def _spin(
        self,
        parent: tk.Frame,
        label: str,
        var: tk.IntVar,
        low: int,
        high: int,
        *,
        increment: int = 1,
    ) -> None:
        row = tk.Frame(parent, bg=_CARD)
        row.pack(fill=tk.X, padx=10, pady=2)
        tk.Label(row, text=label, bg=_CARD, fg=_TEXT, anchor="w").pack(side=tk.LEFT)
        tk.Spinbox(
            row,
            from_=low,
            to=high,
            increment=increment,
            textvariable=var,
            width=7,
            bg=_PLOT_BG,
            fg=_TEXT,
            buttonbackground=_BORDER,
            highlightthickness=0,
            relief=tk.FLAT,
            justify=tk.RIGHT,
        ).pack(side=tk.RIGHT)

    # ------------------------------------------------------------- geometry

    def _fit(self) -> None:
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        world = self.scene.world
        margin = 24
        self._scale = min(
            (width - 2 * margin) / max(world.width, 1),
            (height - 2 * margin) / max(world.height, 1),
        )
        self._scale = max(self._scale, 0.2)
        self._origin = (
            (width - world.width * self._scale) / 2 - world.x * self._scale,
            (height - world.height * self._scale) / 2 - world.y * self._scale,
        )

    def _to_canvas(self, x: float, y: float) -> tuple[float, float]:
        return self._origin[0] + x * self._scale, self._origin[1] + y * self._scale

    def _to_world(self, cx: float, cy: float) -> Point:
        return Point(
            round((cx - self._origin[0]) / self._scale),
            round((cy - self._origin[1]) / self._scale),
        )

    def _clamped(self, rect: Rect) -> Rect:
        """Keep a drawn rectangle inside the world."""

        world = self.scene.world
        left = min(max(rect.left, world.left), world.right)
        top = min(max(rect.top, world.top), world.bottom)
        right = min(max(rect.right, world.left), world.right)
        bottom = min(max(rect.bottom, world.top), world.bottom)
        return Rect(left, top, right - left, bottom - top)

    @staticmethod
    def _rect_between(a: Point, b: Point) -> Rect:
        left, top = min(a.x, b.x), min(a.y, b.y)
        return Rect(left, top, abs(a.x - b.x), abs(a.y - b.y))

    # ---------------------------------------------------------------- input

    def _on_press(self, event: tk.Event) -> None:
        point = self._to_world(event.x, event.y)
        self._drag = (point.x, point.y)

        if self.mode.get() == "erase":
            self._erase_at(point)
            self._drag = None
            self._replan()
        elif self.mode.get() == "goal" and self.goal_type.get() == "point":
            self.scene.goal_point = point
            self._drag = None
            self._replan()

    def _on_motion(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        self._draw(preview=self._to_world(event.x, event.y))

    def _on_release(self, event: tk.Event) -> None:
        if self._drag is None:
            return
        start = Point(*self._drag)
        end = self._to_world(event.x, event.y)
        self._drag = None

        mode = self.mode.get()
        if mode == "goal" and self.goal_type.get() == "segment":
            if start != end:
                self.scene.goal_segment = Segment(start, end)
            self._replan()
            return

        rect = self._clamped(self._rect_between(start, end))
        if rect.width <= 0 or rect.height <= 0:
            self._draw()
            return

        if mode == "body":
            self.scene.body = rect
        elif mode == "obstacle":
            self.scene.obstacles.append(rect)
        elif mode == "goal":
            self.scene.goal_rect = rect
        self._replan()

    def _erase_at(self, point: Point) -> None:
        for index in range(len(self.scene.obstacles) - 1, -1, -1):
            if self.scene.obstacles[index].contains_point(point):
                del self.scene.obstacles[index]
                return

    def _clear_obstacles(self) -> None:
        self.scene.obstacles.clear()
        self._replan()

    def _clear_all(self) -> None:
        self.scene.obstacles.clear()
        self.scene.goal_point = None
        self.scene.goal_segment = None
        self.scene.goal_rect = None
        self._replan()

    def _preset(self, *, horizontal: bool) -> None:
        wanted = FACING_PAIRS[:2] if horizontal else FACING_PAIRS[2:]
        wanted_pairs = {pair for pair, _ in wanted}
        for pair, var in self.rect_pairs.items():
            var.set(pair in wanted_pairs)

    # ----------------------------------------------------------------- plan

    def _current_goal(self) -> Goal | None:
        kind = self.goal_type.get()
        if kind == "point":
            if self.scene.goal_point is None:
                return None
            return PointGoal(self.scene.goal_point, self._int(self.tolerance, 0))
        if kind == "segment":
            if self.scene.goal_segment is None:
                return None
            edges = frozenset(e for e, var in self.segment_edges.items() if var.get())
            if not edges:
                return None
            return SegmentGoal(self.scene.goal_segment, edges)
        if self.scene.goal_rect is None:
            return None
        pairs = {pair for pair, var in self.rect_pairs.items() if var.get()}
        if self.include_aligned.get():
            pairs |= set(ALIGNED_PAIRS)
        if not pairs:
            return None
        return RectGoal(self.scene.goal_rect, frozenset(pairs))

    def _obstacles(self) -> list[Rect]:
        obstacles = list(self.scene.obstacles)
        if (
            self.goal_type.get() == "rect"
            and self.scene.goal_rect is not None
            and self.target_is_obstacle.get()
        ):
            obstacles.append(self.scene.goal_rect)
        return obstacles

    @staticmethod
    def _int(var: tk.IntVar, fallback: int) -> int:
        """Read a spinbox that the user may be mid-way through editing."""

        try:
            return int(var.get())
        except (tk.TclError, ValueError):
            return fallback

    def _replan(self) -> None:
        self._sync_panel()
        goal = self._current_goal()
        self.error = None
        self.path = None
        if goal is not None:
            try:
                self.path = find_path(
                    start=self.scene.body,
                    goal=goal,
                    world=self.scene.world,
                    obstacles=self._obstacles(),
                    step=self._int(self.step, DEFAULT_STEP),
                    allow_diagonals=self.allow_diagonals.get(),
                    max_nodes=max(1, self._int(self.max_nodes, DEFAULT_MAX_NODES)),
                )
            except ValueError as exc:
                self.error = str(exc)
        self._draw()
        self._update_status(goal)

    def _sync_panel(self) -> None:
        kind = self.goal_type.get()
        for box in (self._point_box, self._segment_box, self._rect_box):
            box.pack_forget()
        box = {"point": self._point_box, "segment": self._segment_box}.get(kind, self._rect_box)
        box.pack(fill=tk.X, pady=(4, 0))

        hints = {
            "body": "Arrasta para desenhar o corpo inicial.",
            "obstacle": "Arrasta para acrescentar um obstáculo.",
            "erase": "Clica num obstáculo para o remover.",
        }
        goal_hints = {
            "point": "Clica para pôr o ponto de destino.",
            "segment": "Arrasta para desenhar o segmento de destino.",
            "rect": "Arrasta para desenhar o rectângulo de destino.",
        }
        self._hint.configure(text=hints.get(self.mode.get(), goal_hints[kind]))

    # ---------------------------------------------------------------- paint

    def _draw(self, preview: Point | None = None) -> None:
        self._fit()
        canvas = self.canvas
        canvas.delete("all")
        self._draw_world()
        if self.show_lattice.get():
            self._draw_lattice()
        self._draw_obstacles()
        self._draw_goal()
        self._draw_path()
        self._draw_body()
        if preview is not None and self._drag is not None:
            self._draw_preview(Point(*self._drag), preview)

    def _rectangle(self, rect: Rect, **options) -> None:
        x0, y0 = self._to_canvas(rect.left, rect.top)
        x1, y1 = self._to_canvas(rect.right, rect.bottom)
        self.canvas.create_rectangle(x0, y0, x1, y1, **options)

    def _line(self, a: Point, b: Point, **options) -> None:
        x0, y0 = self._to_canvas(a.x, a.y)
        x1, y1 = self._to_canvas(b.x, b.y)
        self.canvas.create_line(x0, y0, x1, y1, **options)

    def _draw_world(self) -> None:
        self._rectangle(self.scene.world, outline=_BORDER, width=1, fill=_PLOT_BG)

    def _draw_lattice(self) -> None:
        step = max(1, self._int(self.step, DEFAULT_STEP))
        world, body = self.scene.world, self.scene.body
        columns = int(world.width // step) + 1
        rows = int(world.height // step) + 1
        if columns * rows > MAX_LATTICE_DOTS:
            return
        colour = _blend(_DIM, _PLOT_BG, 0.5)
        i = 0
        while body.x + i * step <= world.right:
            j = 0
            while body.y + j * step <= world.bottom:
                cx, cy = self._to_canvas(body.x + i * step, body.y + j * step)
                self.canvas.create_oval(cx - 1, cy - 1, cx + 1, cy + 1, outline="", fill=colour)
                j += 1
            i += 1

    def _draw_obstacles(self) -> None:
        # Obstacles the body already stands in are the ones `Lattice` drops
        # for the whole search; drawing them dashed makes the escape rule
        # visible instead of looking like the route ignores geometry.
        lattice = Lattice(
            start=self.scene.body,
            world=self.scene.world,
            obstacles=self._obstacles(),
            step=max(1, self._int(self.step, DEFAULT_STEP)),
        )
        ignored = list(lattice.ignored)
        for obstacle in self._obstacles():
            is_ignored = any(obstacle == other for other in ignored)
            extra = {"dash": (3, 3)} if is_ignored else {}
            self._rectangle(
                obstacle,
                fill=_blend(_OBSTACLE, _PLOT_BG, 0.35 if is_ignored else 1.0),
                outline=_OBSTACLE_EDGE,
                width=1,
                **extra,
            )

    def _draw_goal(self) -> None:
        kind = self.goal_type.get()
        if kind == "point" and self.scene.goal_point is not None:
            point = self.scene.goal_point
            tolerance = self._int(self.tolerance, 0)
            if tolerance:
                self._rectangle(
                    Rect(point.x, point.y, 0, 0).grown_by(tolerance),
                    outline=_blend(_GOAL, _PLOT_BG, 0.5),
                    dash=(2, 3),
                )
            cx, cy = self._to_canvas(point.x, point.y)
            self.canvas.create_line(cx - 7, cy, cx + 7, cy, fill=_GOAL, width=2)
            self.canvas.create_line(cx, cy - 7, cx, cy + 7, fill=_GOAL, width=2)
        elif kind == "segment" and self.scene.goal_segment is not None:
            segment = self.scene.goal_segment
            self._line(segment.start, segment.end, fill=_GOAL, width=3)
        elif kind == "rect" and self.scene.goal_rect is not None:
            target = self.scene.goal_rect
            self._rectangle(
                target,
                fill=_blend(_GOAL, _PLOT_BG, 0.16),
                outline=_blend(_GOAL, _PLOT_BG, 0.6),
            )
            for pair, var in self.rect_pairs.items():
                if var.get():
                    edge = target.edge(pair[1])
                    self._line(edge.start, edge.end, fill=_GOAL_EDGE, width=4)

    def _draw_body(self) -> None:
        self._rectangle(
            self.scene.body,
            fill=_blend(_BODY, _PLOT_BG, 0.28),
            outline=_BODY,
            width=2,
        )
        if self.path is not None and self.path.steps:
            self._rectangle(self.path.final, outline=_BODY_GHOST, width=2, dash=(4, 3))
            # The body's own arriving edges, so a segment or rect goal can be
            # checked by eye at the position that claims to satisfy it.
            for edge in self._arriving_edges():
                side = self.path.final.edge(edge)
                self._line(side.start, side.end, fill=_ROUTE if self.path.reached else _FAIL, width=3)

    def _arriving_edges(self) -> frozenset[Edge]:
        kind = self.goal_type.get()
        if kind == "segment":
            return frozenset(e for e, var in self.segment_edges.items() if var.get())
        if kind == "rect":
            return frozenset(own for (own, _), var in self.rect_pairs.items() if var.get())
        return frozenset()

    def _draw_path(self) -> None:
        if self.path is None or not self.path.steps:
            return
        colour = _ROUTE if self.path.reached else _FAIL
        positions = self.path.positions()

        if self.show_stops.get():
            faint = _blend(colour, _PLOT_BG, 0.22)
            for rect in positions[1:-1]:
                self._rectangle(rect, outline=faint)

        for previous, current, step in zip(positions, positions[1:], self.path.steps):
            self._line(previous.center, current.center, fill=colour, width=2, arrow=tk.LAST)
            if self.show_lengths.get():
                mid = Point(
                    (previous.center.x + current.center.x) / 2,
                    (previous.center.y + current.center.y) / 2,
                )
                cx, cy = self._to_canvas(mid.x, mid.y)
                self.canvas.create_text(
                    cx,
                    cy - 10,
                    text=f"{step.length:g}",
                    fill=colour,
                    font=("Helvetica", 9),
                )

    def _draw_preview(self, start: Point, end: Point) -> None:
        mode = self.mode.get()
        if mode == "goal" and self.goal_type.get() == "segment":
            self._line(start, end, fill=_GOAL, width=2, dash=(4, 2))
            return
        if mode in ("erase",):
            return
        colour = {"body": _BODY, "obstacle": _OBSTACLE_EDGE}.get(mode, _GOAL)
        self._rectangle(self._rect_between(start, end), outline=colour, dash=(4, 2))

    # --------------------------------------------------------------- status

    def _update_status(self, goal: Goal | None) -> None:
        if self.error is not None:
            self.status.configure(text=f"erro: {self.error}", fg=_FAIL)
            return
        if goal is None:
            self.status.configure(
                text="sem destino — escolhe o modo Destino e desenha-o (e, no rectângulo, "
                "pelo menos um par de arestas)",
                fg=_MUTED,
            )
            return

        path = self.path
        assert path is not None
        vectors = ", ".join(f"{step.direction.name} {step.length:g}" for step in path.steps)
        head = "alcançado" if path.reached else "NÃO alcançado (melhor esforço)"
        self.status.configure(
            text=(
                f"{head} — {len(path.steps)} vectores, comprimento {path.length:.1f}, "
                f"{path.nodes_expanded} nós expandidos    {vectors}"
            ),
            fg=_ROUTE if path.reached else _FAIL,
        )

    def run(self) -> None:
        self.root.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--width", type=int, default=int(DEFAULT_WORLD.width))
    parser.add_argument("--height", type=int, default=int(DEFAULT_WORLD.height))
    parser.add_argument("--step", type=int, default=DEFAULT_STEP)
    parser.add_argument("--body", type=int, default=16, help="side of the starting body")
    args = parser.parse_args(argv)

    world = Rect(0, 0, args.width, args.height)
    body = Rect(16, 16, args.body, args.body)
    PathfindViewer(world=world, body=body, step=args.step).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
