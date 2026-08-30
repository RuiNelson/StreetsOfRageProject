"""Entry point: attach to a running SoR host and observe live state."""

from __future__ import annotations

import logging

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Sequence

from . import __version__
from .ai.gamepad import SharedGamepadState, VirtualGamepad
from .ai.loop import AgentLoop
from .debug_scenario import ENEMY_FAMILY_HOTKEYS, DebugScenario
from .hud import HUD_PAINT_MS_DEFAULT, ObserverHud
from .rom_data import RomData
from .state import GameSnapshot, disconnected_snapshot, read_snapshot

# Wall-clock sample period. ~2 frames at 60 Hz (2 / 60 * 1000 ≈ 33.3 ms).
DEFAULT_POLL_MS = 33
ASSUMED_HZ = 60


class _RemoteClientProxy:
    """Forwards button commands to whichever client ``ObserverApp`` currently
    holds, so the AI's ``SharedGamepadState`` survives poll-loop reconnects
    without needing to be rebuilt (it is otherwise a plain, long-lived
    object owned once by ``ObserverApp``)."""

    def __init__(self, app: "ObserverApp") -> None:
        self._app = app

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
        client = self._app._client
        if client is not None:
            client.hold_buttons(player1=player1, player2=player2)

    def press_buttons(self, *, player1: int = 0, player2: int = 0, frames: int = 1) -> None:
        client = self._app._client
        if client is not None:
            client.press_buttons(player1=player1, player2=player2, frames=frames)


def _default_megadrive_python_src() -> Path | None:
    """Locate sibling MegaDriveEnvironment/python/src when run from the workspace."""

    here = Path(__file__).resolve()
    # autoplay/src/sor_autoplay/app.py -> workspace root is parents[3]
    candidates = [
        here.parents[3] / "MegaDriveEnvironment" / "python" / "src",
        here.parents[2] / "MegaDriveEnvironment" / "python" / "src",
        Path.cwd() / "MegaDriveEnvironment" / "python" / "src",
        Path.cwd().parent / "MegaDriveEnvironment" / "python" / "src",
    ]
    for path in candidates:
        if (path / "megadrive_remote").is_dir():
            return path
    return None


def _ensure_megadrive_remote_on_path() -> None:
    if "megadrive_remote" in sys.modules:
        return
    try:
        import megadrive_remote  # noqa: F401
        return
    except ImportError:
        pass
    src = _default_megadrive_python_src()
    if src is not None and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import megadrive_remote  # noqa: F401


def _reach_gameplay(host: str, port: int, character: str, *, timeout_ms: int) -> None:
    """Navigate the real menus to playable gameplay (exclusive remote client)."""

    from megadrive_remote import MegaDriveClient

    from .reach_gameplay import reach_gameplay

    with MegaDriveClient(host, port, connect_timeout=5.0, io_timeout=5.0) as client:
        reach_gameplay(client, character, timeout_ms=timeout_ms)


def _try_reach_gameplay(
    host: str,
    port: int,
    character: str,
    *,
    timeout_ms: int,
    connect_attempts: int = 8,
    connect_retry_s: float = 0.75,
    should_abort: Callable[[], bool] | None = None,
) -> bool:
    """Run menu navigation; retry while the host is not listening yet.

    The remote protocol is single-client, so this must not run concurrently
    with the observer poller. Returns True on success.
    """

    last_exc: BaseException | None = None
    for attempt in range(1, connect_attempts + 1):
        if should_abort is not None and should_abort():
            print("--reach-gameplay: aborted (observer closing)", file=sys.stderr)
            return False
        try:
            print(
                f"--reach-gameplay: connecting to {host}:{port} as {character} "
                f"(attempt {attempt}/{connect_attempts})…",
                file=sys.stderr,
            )
            _reach_gameplay(host, port, character, timeout_ms=timeout_ms)
            print("--reach-gameplay: reached playable gameplay", file=sys.stderr)
            return True
        except Exception as exc:  # noqa: BLE001 - surface any navigation failure
            last_exc = exc
            # Connection refused / timeout → host not up yet; keep waiting.
            if attempt < connect_attempts:
                # Sleep in small slices so window close aborts promptly.
                deadline = time.monotonic() + connect_retry_s
                while time.monotonic() < deadline:
                    if should_abort is not None and should_abort():
                        print(
                            "--reach-gameplay: aborted (observer closing)",
                            file=sys.stderr,
                        )
                        return False
                    time.sleep(min(0.1, deadline - time.monotonic()))
    print(
        f"--reach-gameplay failed after {connect_attempts} attempts: {last_exc}\n"
        f"  Is the game host running with remote access on {host}:{port}?\n"
        f"  Example: ./scripts/run --debugUtils --port {port}\n"
        f"  Observer will keep polling; AI flags still apply once connected.",
        file=sys.stderr,
    )
    return False


def build_parser() -> argparse.ArgumentParser:
    # scripts/autoplay sets SOR_AUTOPLAY_PROG so --help shows the wrapper name.
    prog = os.environ.get("SOR_AUTOPLAY_PROG") or "sor-autoplay"
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Live observer for a running StreetsOfRageRecompilation instance "
            "via MegaDriveEnvironment remote access. Optional symbolic AI "
            "controls P1/P2 through controller input only (never RAM writes)."
        ),
        epilog=(
            "Start the game host first (same --port), for example:\n"
            "  ./scripts/run --debugUtils --port 7777\n"
            "  ./scripts/autoplay --port 7777 --reach-gameplay axel --agent-p1\n"
            "\n"
            "AI is off by default; enable with --agent-p1 / --agent-p2 or the "
            "HUD toggle labels. --reach-gameplay runs after the GUI opens "
            "(exclusive remote session, then polling starts)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Remote host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=6969,
        help="Remote TCP port (default: 6969)",
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=DEFAULT_POLL_MS,
        help=(
            "Wall-clock remote poll period in milliseconds "
            f"(default: {DEFAULT_POLL_MS}, ~2 frames at {ASSUMED_HZ} Hz). "
            "Does not wait on VSync."
        ),
    )
    parser.add_argument(
        "--hud-ms",
        type=int,
        default=HUD_PAINT_MS_DEFAULT,
        help=(
            "GUI paint period in milliseconds; only redraws the latest snapshot "
            f"(default: {HUD_PAINT_MS_DEFAULT})"
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot to stdout and exit (no GUI)",
    )
    parser.add_argument(
        "--agent-p1",
        action="store_true",
        help="Start with the symbolic AI controlling P1 (off by default)",
    )
    parser.add_argument(
        "--agent-p2",
        action="store_true",
        help="Start with the symbolic AI controlling P2 (off by default)",
    )
    parser.add_argument(
        "--reach-gameplay",
        choices=("axel", "adam", "blaze"),
        default=None,
        help=(
            "After the GUI opens, navigate the real menus (restart, Start, "
            "one-player, character select) to playable one-player gameplay "
            "as this character, then start remote polling. Off by default. "
            "The remote protocol is single-client, so navigation runs before "
            "the observer poller attaches."
        ),
    )
    parser.add_argument(
        "--reach-gameplay-timeout-ms",
        type=int,
        default=30_000,
        help="Timeout for each menu-navigation step of --reach-gameplay (default: 30000)",
    )
    parser.add_argument(
        "--start-level",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Debug: jump to level N (1-8) as soon as gameplay is reached, using "
            "the host's own level hotkey. Requires the host to run with "
            "--debugUtils. The AI is held off until the jump has been made."
        ),
    )
    parser.add_argument(
        "--only-enemy",
        choices=sorted(ENEMY_FAMILY_HOTKEYS),
        default=None,
        help=(
            "Debug: keep only this enemy family alive, killing every other "
            "family repeatedly through the host's per-family kill hotkeys "
            "(requires --debugUtils). Waves respawn, so the sweep runs for the "
            "whole session."
        ),
    )
    parser.add_argument(
        "--no-food",
        action="store_true",
        help=(
            "Debug: never walk to a health pickup, for the whole session. "
            "Use when *scoring* a fight: a heal hides the damage taken after "
            "it (damage is a running minimum), and a plan that survives only "
            "because it ate is not a plan. Does not need --debugUtils."
        ),
    )
    parser.add_argument(
        "--kill-street-enemies",
        action="store_true",
        help=(
            "Debug: kill every ordinary (non-boss) enemy family repeatedly "
            "through the host's per-family kill hotkeys (requires --debugUtils). "
            "Use to isolate a boss fight. Cannot be combined with --only-enemy."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _print_snapshot(snapshot: GameSnapshot) -> None:
    status = "LIVE" if snapshot.connected else "OFFLINE"
    print(f"[{status}] mode={snapshot.game_mode} (0x{snapshot.game_state:02X})")
    time_text = f"{snapshot.time_left}s" if snapshot.timer_valid else "—"
    print(
        f"  level={snapshot.level_display} (index {snapshot.level_index})  "
        f"wave={snapshot.wave}  time={time_text}"
    )
    for player in snapshot.players:
        print(f"  {player.summary_line()}")
    flags = []
    if snapshot.paused:
        flags.append("PAUSED")
    if snapshot.police_special_active:
        flags.append(
            f"POLICE_SPECIAL(P{(snapshot.police_special_caller or 0) + 1})"
        )
    print(f"  flags: {', '.join(flags) if flags else 'running'}")
    print(f"  floor_holes: {len(snapshot.floor_holes)}")
    for hole in snapshot.floor_holes[:12]:
        print(
            f"    hole x={hole.world_x}..{hole.world_x_end} "
            f"lane={hole.lane_y}..{hole.lane_y_end}"
        )
    world = snapshot.world_map
    counts = world.counts_by_kind()
    print(
        f"  map: cam=({world.camera_x},{world.camera_y})  "
        f"entities={len(world.entities)}  "
        f"{counts or '{}'}"
    )
    for entity in world.entities[:24]:
        print(
            f"    [{entity.slot}] {entity.symbol} {entity.label:<16} "
            f"kind={entity.kind:<10} "
            f"world=({entity.world_x},{entity.world_y},z={entity.world_z}) "
            f"map=({entity.map_x:.0f},{entity.map_y:.0f})"
        )
    if len(world.entities) > 24:
        print(f"    … {len(world.entities) - 24} more")
    if snapshot.error:
        print(f"  error: {snapshot.error}")


logger = logging.getLogger(__name__)


def _read_rom_data(client) -> RomData | None:
    """Read the static ROM tables, or ``None`` if the link refuses them.

    Hitboxes and attack ranges are an enhancement over the position-only
    observation that came before them, so losing them must not take the
    observer down with them.
    """

    try:
        return RomData.read(client)
    except Exception:  # noqa: BLE001 - any link failure degrades, never fails
        logger.warning("could not read ROM shape/animation tables", exc_info=True)
        return None


class ObserverApp:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        poll_ms: int = DEFAULT_POLL_MS,
        hud_ms: int = HUD_PAINT_MS_DEFAULT,
        agent_p1: bool = False,
        agent_p2: bool = False,
        scenario: DebugScenario | None = None,
        no_food: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.poll_ms = max(1, poll_ms)
        self.hud_ms = max(16, hud_ms)
        self.scenario = scenario
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: GameSnapshot = disconnected_snapshot("starting")
        self._client = None
        self._rom: RomData | None = None
        self._hud: ObserverHud | None = None

        # AI is opt-in and off by default; toggled via CLI flag or the HUD's
        # per-player click label. One SharedGamepadState is shared by both
        # VirtualGamepad views because a single remote HOLD_BUTTONS call
        # latches both players' masks at once (see ai/gamepad.py).
        self.agent_p1_enabled = threading.Event()
        self.agent_p2_enabled = threading.Event()
        if agent_p1:
            self.agent_p1_enabled.set()
        if agent_p2:
            self.agent_p2_enabled.set()
        self._gamepad_state = SharedGamepadState(_RemoteClientProxy(self))
        self._gamepads = {
            1: VirtualGamepad(self._gamepad_state, player_index=1),
            2: VirtualGamepad(self._gamepad_state, player_index=2),
        }
        self._agent_loops = {
            1: AgentLoop(self._gamepads[1], no_food=no_food),
            2: AgentLoop(self._gamepads[2], no_food=no_food),
        }

    def set_agent_enabled(self, player_index: int, enabled: bool) -> None:
        event = self.agent_p1_enabled if player_index == 1 else self.agent_p2_enabled
        if enabled:
            event.set()
        else:
            event.clear()
            # Clear the HUD's live verb state so the label reads as idle.
            self._agent_loops[player_index].inform_hud(set())
            self._gamepads[player_index].release()

    def start_poller(self) -> None:
        thread = threading.Thread(target=self._poll_loop, name="sor-remote-poll", daemon=True)
        thread.start()

    def _poll_loop(self) -> None:
        from megadrive_remote import MegaDriveClient

        backoff_s = 0.25
        poll_s = self.poll_ms / 1000.0

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                if self._client is None:
                    client = MegaDriveClient(
                        self.host,
                        self.port,
                        connect_timeout=1.5,
                        io_timeout=1.5,
                    )
                    client.connect()
                    client.ping()
                    with self._lock:
                        if self._stop.is_set():
                            # stop() ran while we were connecting; do not
                            # leak this socket past the poller's lifetime.
                            client.close()
                            break
                        self._client = client
                    # The fresh connection's remote button latch already
                    # starts empty; resync our cache so a held mask that
                    # matches what we sent before the drop still gets sent.
                    self._gamepad_state.reset()
                    # ROM shape/animation tables: static for the session, so
                    # they are read once per *connection* rather than per
                    # poll. A failure here is not fatal -- the observer keeps
                    # working, just without real hitboxes or attack ranges.
                    self._rom = _read_rom_data(client)
                    backoff_s = 0.25

                assert self._client is not None
                snapshot = read_snapshot(self._client, rom=self._rom)

                with self._lock:
                    self._latest = snapshot

                if not self._apply_scenario(snapshot):
                    elapsed = time.monotonic() - started
                    remaining = poll_s - elapsed
                    if remaining > 0:
                        self._stop.wait(remaining)
                    continue

                if self.agent_p1_enabled.is_set():
                    self._agent_loops[1].tick(snapshot, player_index=1)
                if self.agent_p2_enabled.is_set():
                    self._agent_loops[2].tick(snapshot, player_index=2)

                elapsed = time.monotonic() - started
                remaining = poll_s - elapsed
                if remaining > 0:
                    self._stop.wait(remaining)
            except Exception as exc:  # noqa: BLE001 - surface any link failure in HUD
                with self._lock:
                    self._latest = disconnected_snapshot(str(exc))
                    client, self._client = self._client, None
                if client is not None:
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass
                self._stop.wait(backoff_s)
                backoff_s = min(2.0, backoff_s * 1.5)

    def _apply_scenario(self, snapshot: GameSnapshot) -> bool:
        """Run the debug scenario for this poll; True when the AI may tick.

        The level jump is requested once, the moment gameplay is actually
        playable, and the AI is held off until the game reports the requested
        level: a verb decided during the intro is aimed at the scene the jump
        is about to throw away.

        Past the jump, the level-index gate below must not fire on a
        continue/name-entry screen (object type $0F replaces the playable
        object, so ``is_playable`` reads false there too). ``ai/loop.py``
        already carves this case out for the same reason -- the pipeline
        still has to answer Yes and type the initials -- but this gate runs
        *before* ``AgentLoop.tick`` and used to hold it off regardless,
        which left the continue prompt unanswered until its own timer
        expired and the ROM fell back to the title screen: indistinguishable
        from the game resetting mid-level, and far more likely on a long,
        punishing level (round 2's boss costs 1-2 lives over a ~10 minute
        traversal) than a short one. See ``tools/boss_fight.py``, which hit
        the same gate and documents it as "hung this harness completely".
        """

        scenario = self.scenario
        if scenario is None or not scenario.active or self._client is None:
            return True

        playable = any(player.is_playable for player in snapshot.players)
        if scenario.level_jump_pending:
            if not playable:
                return False
            scenario.apply_start_level(self._client)
            return False
        in_continue_ui = any(player.is_continue_ui for player in snapshot.players)
        if (
            scenario.start_level is not None
            and not in_continue_ui
            and (not playable or snapshot.level_index != scenario.start_level - 1)
        ):
            return False

        scenario.sweep_other_families(self._client)
        return True

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                # Release directly on the captured client, not through
                # ai.gamepad — self._client is already cleared above, so the
                # gamepad's proxy would see no client and no-op.
                client.hold_buttons(player1=0, player2=0)
            except Exception:  # noqa: BLE001
                pass
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    def latest(self) -> GameSnapshot:
        with self._lock:
            return self._latest

    def run_gui(
        self,
        *,
        reach_gameplay: str | None = None,
        reach_gameplay_timeout_ms: int = 30_000,
    ) -> int:
        """Open the HUD immediately; optionally navigate menus, then poll.

        ``--reach-gameplay`` must not block window creation. The remote service
        allows only one TCP client, so menu navigation runs on a background
        thread *before* the poller attaches (AI is held off until then).
        """

        approx_frames = self.poll_ms * ASSUMED_HZ / 1000.0
        self._hud = ObserverHud(
            on_close=self.stop,
            on_toggle_agent=self._handle_toggle_agent_ui,
            subtitle=f"poll {self.poll_ms}ms (~{approx_frames:.1f}f)",
        )

        def tick() -> None:
            if self._stop.is_set() or self._hud is None:
                return
            try:
                self._hud.update(
                    self.latest(),
                    agent_p1_enabled=self.agent_p1_enabled.is_set(),
                    agent_p2_enabled=self.agent_p2_enabled.is_set(),
                    p1_state=self._agent_loops[1].verb_state(),
                    p2_state=self._agent_loops[2].verb_state(),
                )
            except Exception as exc:  # noqa: BLE001
                self._hud.update(disconnected_snapshot(f"HUD error: {exc}"))
            self._hud.schedule(self.hud_ms, tick)

        self._hud.schedule(0, tick)

        if reach_gameplay is not None:
            with self._lock:
                self._latest = disconnected_snapshot(
                    f"navigating menus as {reach_gameplay}…"
                )
            thread = threading.Thread(
                target=self._reach_gameplay_then_start_poller,
                args=(reach_gameplay, reach_gameplay_timeout_ms),
                name="sor-reach-gameplay",
                daemon=True,
            )
            thread.start()
        else:
            self.start_poller()

        try:
            self._hud.run()
        finally:
            self.stop()
        return 0

    def _reach_gameplay_then_start_poller(
        self, character: str, timeout_ms: int
    ) -> None:
        """Exclusive menu navigation, then attach the observer poller.

        AI is disabled for the duration so navigation owns the pad; requested
        ``--agent-p*`` flags are restored before polling begins.
        """

        resume_p1 = self.agent_p1_enabled.is_set()
        resume_p2 = self.agent_p2_enabled.is_set()
        self.agent_p1_enabled.clear()
        self.agent_p2_enabled.clear()
        try:
            if not self._stop.is_set():
                _try_reach_gameplay(
                    self.host,
                    self.port,
                    character,
                    timeout_ms=timeout_ms,
                    should_abort=self._stop.is_set,
                )
        finally:
            if resume_p1:
                self.agent_p1_enabled.set()
            if resume_p2:
                self.agent_p2_enabled.set()
            if not self._stop.is_set():
                self.start_poller()

    def _handle_toggle_agent_ui(self, player_index: int) -> None:
        event = self.agent_p1_enabled if player_index == 1 else self.agent_p2_enabled
        self.set_agent_enabled(player_index, not event.is_set())

    def run_once(self) -> int:
        from megadrive_remote import MegaDriveClient

        try:
            with MegaDriveClient(self.host, self.port, connect_timeout=2.0, io_timeout=2.0) as client:
                client.ping()
                snapshot = read_snapshot(client, rom=_read_rom_data(client))
        except Exception as exc:  # noqa: BLE001
            snapshot = disconnected_snapshot(str(exc))
            _print_snapshot(snapshot)
            return 1
        _print_snapshot(snapshot)
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _ensure_megadrive_remote_on_path()

    app = ObserverApp(
        host=args.host,
        port=args.port,
        poll_ms=args.poll_ms,
        hud_ms=args.hud_ms,
        agent_p1=args.agent_p1,
        agent_p2=args.agent_p2,
        no_food=args.no_food,
        scenario=DebugScenario(
            start_level=args.start_level,
            only_enemy=args.only_enemy,
            kill_street_enemies=args.kill_street_enemies,
        ),
    )
    if args.once:
        # Snapshot-only mode has no GUI; still honor menu navigation first.
        if args.reach_gameplay is not None:
            _try_reach_gameplay(
                args.host,
                args.port,
                args.reach_gameplay,
                timeout_ms=args.reach_gameplay_timeout_ms,
            )
        return app.run_once()

    agents = []
    if args.agent_p1:
        agents.append("P1")
    if args.agent_p2:
        agents.append("P2")
    agent_text = f"; AI on {','.join(agents)}" if agents else ""
    reach_text = (
        f"; then reach-gameplay={args.reach_gameplay}"
        if args.reach_gameplay is not None
        else ""
    )
    scenario_bits = []
    if args.start_level is not None:
        scenario_bits.append(f"level {args.start_level}")
    if args.only_enemy is not None:
        scenario_bits.append(f"only {args.only_enemy}")
    if args.kill_street_enemies:
        scenario_bits.append("kill street enemies")
    scenario_text = f"; debug scenario: {', '.join(scenario_bits)}" if scenario_bits else ""
    print(
        f"Starting SoR Autoplay GUI → {args.host}:{args.port} "
        f"(poll {args.poll_ms}ms{agent_text}{reach_text}{scenario_text}; Esc/Q to quit)",
        file=sys.stderr,
    )
    return app.run_gui(
        reach_gameplay=args.reach_gameplay,
        reach_gameplay_timeout_ms=args.reach_gameplay_timeout_ms,
    )


if __name__ == "__main__":
    raise SystemExit(main())
