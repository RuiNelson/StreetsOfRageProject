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
from .state import (
    GameSnapshot,
    disconnected_snapshot,
    read_snapshot,
    snapshot_from_work_ram,
)

# Wall-clock sample period. ~2 frames at 60 Hz (2 / 60 * 1000 ≈ 33.3 ms).
DEFAULT_POLL_MS = 33
ASSUMED_HZ = 60

# Lockstep cadence: game frames stepped per AI tick. Matches the labs'
# FRAMES_PER_TICK and kinematics.FRAMES_PER_TICK's nominal 2 -- one tick per
# object update (objects run at 30 Hz), so the plan's stick lands exactly.
LOCKSTEP_FRAMES_PER_TICK = 2


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


class _LockstepCapture:
    """Capture (instead of send) both players' button commands in lockstep mode.

    The two-player ``RecordingClient`` the ``tools/*_lab.py`` labs each
    reimplement for player 1 alone, promoted here. ``SharedGamepadState.press``
    sends a full two-player payload -- the acting player's edge plus the other
    player's current hold -- so replaying that payload verbatim for its frames
    and then falling back to the sticky holds reproduces the tick exactly.

    Touched from the poll thread (AI ticks, stepping) and the Tk thread (HUD
    toggle releases), so every method takes the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: dict[int, int] = {1: 0, 2: 0}
        self._press_mask: dict[int, int] = {1: 0, 2: 0}
        self._press_frames: dict[int, int] = {1: 0, 2: 0}

    def reset(self) -> None:
        with self._lock:
            self._held = {1: 0, 2: 0}
            self._press_mask = {1: 0, 2: 0}
            self._press_frames = {1: 0, 2: 0}

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
        with self._lock:
            self._held[1] = int(player1)
            self._held[2] = int(player2)

    def press_buttons(
        self, *, player1: int = 0, player2: int = 0, frames: int = 1
    ) -> None:
        with self._lock:
            self._press_mask[1] = int(player1)
            self._press_mask[2] = int(player2)
            self._press_frames[1] = int(frames)
            self._press_frames[2] = int(frames)

    def press_pending(self, player_index: int) -> bool:
        with self._lock:
            return self._press_frames[player_index] > 0

    def next_frame_masks(self) -> tuple[int, int]:
        """Masks for one stepped frame, draining any pending press first."""

        with self._lock:
            out = {}
            for index in (1, 2):
                if self._press_frames[index] > 0:
                    self._press_frames[index] -= 1
                    out[index] = self._press_mask[index]
                else:
                    out[index] = self._held[index]
            return (out[1], out[2])


def _group_step_masks(
    masks: list[tuple[int, int]],
) -> list[tuple[int, int, int, int]]:
    """Group consecutive equal per-frame masks into ``step_input`` calls.

    Returns ``(player1, player2, held_frames, total_frames)`` tuples:
    ``held_frames`` covers the whole group when any button is down, else the
    group plays released. Grouping keeps the common case -- one tick, one
    mask -- to a single round trip while staying frame-exact when a press
    edge falls mid-tick.
    """

    groups: list[list[int]] = []
    for player1, player2 in masks:
        if groups and groups[-1][0] == player1 and groups[-1][1] == player2:
            groups[-1][3] += 1
        else:
            groups.append([player1, player2, 0, 1])
    result = []
    for player1, player2, _, total in groups:
        held = total if (player1 or player2) else 0
        result.append((player1, player2, held, total))
    return result


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
        "--lockstep",
        action="store_true",
        help=(
            "Drive the host in lockstep while an AI is engaged: tick the "
            "pipeline, then step exactly "
            f"{LOCKSTEP_FRAMES_PER_TICK} game frames as fast as the host runs "
            "them (no --poll-ms pacing, no --turbo). Falls back to realtime "
            "polling with no AI engaged or while the game is not playable. "
            "Requires the host's --debugUtils."
        ),
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
        "--no-police",
        action="store_true",
        help=(
            "Debug: never call the police special, for the whole session. "
            "Use when *testing* (user: \"The police is allowed for "
            "Souther/Antonio, just don't test with the police on\"): a fight "
            "the special helped win measures the special, not the plan. "
            "scripts/go_to_boss passes it."
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
        "--kill-until-mr-x",
        action="store_true",
        help=(
            "Debug, for round 8: kill every enemy and every boss of the rush "
            "repeatedly through the host's X hotkey (requires --debugUtils), "
            "until Mr. X's scene is up -- then nothing, so his helpers and he "
            "are the fight. Cannot be combined with another sweep."
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
        no_police: bool = False,
        lockstep: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.poll_ms = max(1, poll_ms)
        self.hud_ms = max(16, hud_ms)
        self.scenario = scenario
        # --lockstep: while an AI is engaged and the game is playable, tick
        # the pipeline and then step exactly LOCKSTEP_FRAMES_PER_TICK game
        # frames as fast as the host runs them (no wall-clock pacing, no
        # turbo). Falls back to realtime polling otherwise.
        self.lockstep = lockstep
        self._lockstep_engaged = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: GameSnapshot = disconnected_snapshot("starting")
        self._client = None
        self._rom: RomData | None = None
        self._hud: ObserverHud | None = None

        # Diagnostic only (not read by the AI): how many emulated frames
        # actually landed between polls, vs. wall-clock time spent. Lets a
        # user judge whether --poll-ms is really tracking the host's frame
        # rate before trusting kinematics.FRAMES_PER_TICK's nominal 2 --
        # see autoplay/CLAUDE.md's OBJECT_UPDATE_FRAMES story for why that
        # nominal constant is not swapped for a live measurement outright.
        self._frame_timing_samples: list[tuple[int, float]] = []
        self._frame_timing_logged_at = 0.0

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
        # In lockstep mode the AI never touches the live latch: the tick's
        # output is captured and replayed through step_input instead, so the
        # sticky hold and the stepped masks cannot fight over the pad.
        self._capture = _LockstepCapture()
        if lockstep:
            self._gamepad_state = SharedGamepadState(self._capture)
        self._gamepads = {
            1: VirtualGamepad(self._gamepad_state, player_index=1),
            2: VirtualGamepad(self._gamepad_state, player_index=2),
        }
        self._agent_loops = {
            1: AgentLoop(self._gamepads[1], no_food=no_food, no_police=no_police),
            2: AgentLoop(self._gamepads[2], no_food=no_food, no_police=no_police),
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
        target = self._lockstep_loop if self.lockstep else self._poll_loop
        thread = threading.Thread(target=target, name="sor-remote-poll", daemon=True)
        thread.start()

    def _sleep_remaining(self, started: float, poll_s: float) -> None:
        elapsed = time.monotonic() - started
        remaining = poll_s - elapsed
        if remaining > 0:
            self._stop.wait(remaining)

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
                self._record_frame_timing(snapshot, time.monotonic() - started)

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

    def _engage_lockstep(self, client) -> bool:
        """Freeze the host at a frame boundary and take over its clock.

        Clears the sticky button latch first (the labs release the pad before
        entering lockstep for the same reason): from here on the only input
        the game sees is each step's own masks.
        """

        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001 - engage fails below instead
            return False
        self._capture.reset()
        self._gamepad_state.reset()
        try:
            # Short timeout on purpose: entry cannot latch while the host CPU
            # is inside a run-to-completion ROM load (level/decompression --
            # no interrupt dispatch, so no checkpoint latches until the load
            # finishes), and a failed attempt freezes the game for the whole
            # wait. 2 s of freeze with a retry right after beats 10 s; the
            # loop retries until it lands. Measured: instant entry in settled
            # gameplay, timeouts only across loads, at any turbo.
            client.set_lockstep(True, timeout_ms=2_000)
        except Exception as exc:  # noqa: BLE001 - reported, retried next poll
            logger.warning("lockstep engage failed: %s", exc)
            return False
        self._lockstep_engaged = True
        logger.info(
            "lockstep engaged: driving %d frames per AI tick", LOCKSTEP_FRAMES_PER_TICK
        )
        return True

    def _disengage_lockstep(self, client) -> None:
        """Release the host back to realtime; never fails the caller."""

        self._lockstep_engaged = False
        try:
            client.set_lockstep(False)
        except Exception:  # noqa: BLE001 - best effort on the way out
            pass
        try:
            client.hold_buttons(player1=0, player2=0)
        except Exception:  # noqa: BLE001 - best effort on the way out
            pass

    def _lockstep_loop(self) -> None:
        """Tick the AI and step the game, alternating, as fast as possible.

        While an AI is engaged and the game is playable the host is frozen
        and this loop owns its clock: one pipeline tick, then exactly
        ``LOCKSTEP_FRAMES_PER_TICK`` stepped frames, then back to the tick --
        the labs' shape (``tools/antonio_lab.py``), live. No ``--poll-ms``
        sleeping and no ``--turbo``: each step runs the moment the tick lands.

        With no AI engaged, before the level jump, or on a level mismatch
        (reset/title), the host runs realtime and this loop only observes --
        the AI never ticks there, so menus and the continue UI are crossed in
        realtime and play resumes in lockstep.
        """

        from megadrive_remote import MegaDriveClient

        backoff_s = 0.25
        poll_s = self.poll_ms / 1000.0
        ram: bytes | None = None
        frame_no = 0
        # Lockstep cost breakdown (diagnostic only, logged at DEBUG): how
        # much of each tick the AI pipeline vs. the stepped frames take, so
        # a slowdown can be told apart between "the plan is heavy" and "the
        # host is heavy" without guessing.
        lockstep_tick_ms: list[float] = []
        lockstep_step_ms: list[float] = []
        lockstep_logged_at = 0.0

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
                            client.close()
                            break
                        self._client = client
                    self._gamepad_state.reset()
                    self._rom = _read_rom_data(client)
                    backoff_s = 0.25
                    ram = None

                assert self._client is not None
                client = self._client
                if ram is None:
                    snapshot = read_snapshot(client, rom=self._rom)
                else:
                    snapshot = snapshot_from_work_ram(
                        ram, rom=self._rom, uptime_frames=frame_no
                    )
                self._record_frame_timing(snapshot, time.monotonic() - started)

                with self._lock:
                    self._latest = snapshot

                ai_on = (
                    self.agent_p1_enabled.is_set()
                    or self.agent_p2_enabled.is_set()
                )
                if not self._lockstep_engaged:
                    if not self._apply_scenario(snapshot):
                        self._sleep_remaining(started, poll_s)
                        continue
                    playable = any(p.is_playable for p in snapshot.players)
                    if ai_on and playable and self._engage_lockstep(client):
                        ram = None
                        continue
                    self._sleep_remaining(started, poll_s)
                    continue

                if not ai_on or not self._apply_scenario(snapshot):
                    self._disengage_lockstep(client)
                    ram = None
                    continue

                tick_started = time.monotonic()
                for player_index in (1, 2):
                    enabled = (
                        self.agent_p1_enabled.is_set()
                        if player_index == 1
                        else self.agent_p2_enabled.is_set()
                    )
                    # A tick with no verb releases the pad, which would drop
                    # both a press still draining and the launch direction a
                    # crouch is sampling -- the labs skip the tick instead.
                    if enabled and not self._capture.press_pending(player_index):
                        self._agent_loops[player_index].tick(
                            snapshot, player_index=player_index
                        )
                tick_ms = (time.monotonic() - tick_started) * 1000.0
                masks = [
                    self._capture.next_frame_masks()
                    for _ in range(LOCKSTEP_FRAMES_PER_TICK)
                ]
                for player1, player2, held, total in _group_step_masks(masks):
                    result = client.step_input(
                        player1=player1, player2=player2,
                        held_frames=held, total_frames=total,
                    )
                step_ms = (time.monotonic() - tick_started) * 1000.0 - tick_ms
                lockstep_tick_ms.append(tick_ms)
                lockstep_step_ms.append(step_ms)
                now = time.monotonic()
                if now - lockstep_logged_at >= 3.0 and lockstep_tick_ms:
                    logger.debug(
                        "lockstep timing: %d ticks, tick min=%.1fms mean=%.1fms "
                        "max=%.1fms, step min=%.1fms mean=%.1fms max=%.1fms",
                        len(lockstep_tick_ms),
                        min(lockstep_tick_ms),
                        sum(lockstep_tick_ms) / len(lockstep_tick_ms),
                        max(lockstep_tick_ms),
                        min(lockstep_step_ms),
                        sum(lockstep_step_ms) / len(lockstep_step_ms),
                        max(lockstep_step_ms),
                    )
                    lockstep_tick_ms.clear()
                    lockstep_step_ms.clear()
                    lockstep_logged_at = now
                ram = result.work_ram
                frame_no = result.frame
            except Exception as exc:  # noqa: BLE001 - surface any link failure in HUD
                self._lockstep_engaged = False
                ram = None
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

    def _record_frame_timing(self, snapshot: GameSnapshot, elapsed_s: float) -> None:
        """Log how many emulated frames a poll actually covered.

        Purely observational: never read by the AI or by ``kinematics.py``
        (which never imports this module). ``uptime_frames`` resets on
        ``restart_game``/reconnect, which reads as a negative delta here and
        is simply dropped rather than logged as a stall.
        """

        previous = self._frame_timing_samples[-1][0] if self._frame_timing_samples else None
        current = snapshot.raw.get("uptime_frames")
        if current is None:
            return
        if previous is not None and current > previous:
            self._frame_timing_samples.append((current, elapsed_s))
        elif previous is None:
            self._frame_timing_samples.append((current, elapsed_s))

        now = time.monotonic()
        if now - self._frame_timing_logged_at < 3.0 or len(self._frame_timing_samples) < 2:
            return
        deltas = [
            b[0] - a[0]
            for a, b in zip(self._frame_timing_samples, self._frame_timing_samples[1:])
        ]
        wall_ms = [b[1] * 1000.0 for b in self._frame_timing_samples[1:]]
        if deltas:
            logger.debug(
                "poll timing: %d ticks, frames/tick min=%d mean=%.2f max=%d, "
                "poll work min=%.1fms mean=%.1fms max=%.1fms (poll_ms=%d)",
                len(deltas),
                min(deltas),
                sum(deltas) / len(deltas),
                max(deltas),
                min(wall_ms),
                sum(wall_ms) / len(wall_ms),
                max(wall_ms),
                self.poll_ms,
            )
        self._frame_timing_samples = self._frame_timing_samples[-1:]
        self._frame_timing_logged_at = now

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

        scenario.note_snapshot(snapshot)
        scenario.sweep_other_families(self._client)
        return True

    def stop(self) -> None:
        self._stop.set()
        self._lockstep_engaged = False
        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                # A host left in lockstep stays frozen: release it before the
                # latch clear below, best effort like everything else here.
                client.set_lockstep(False)
            except Exception:  # noqa: BLE001
                pass
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
        subtitle = (
            f"lockstep {LOCKSTEP_FRAMES_PER_TICK}f/tick"
            if self.lockstep
            else f"poll {self.poll_ms}ms (~{approx_frames:.1f}f)"
        )
        self._hud = ObserverHud(
            on_close=self.stop,
            on_toggle_agent=self._handle_toggle_agent_ui,
            subtitle=subtitle,
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
        no_police=args.no_police,
        lockstep=args.lockstep,
        scenario=DebugScenario(
            start_level=args.start_level,
            only_enemy=args.only_enemy,
            kill_street_enemies=args.kill_street_enemies,
            kill_until_mr_x=args.kill_until_mr_x,
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
    if args.kill_until_mr_x:
        scenario_bits.append("kill everything until Mr. X")
    scenario_text = f"; debug scenario: {', '.join(scenario_bits)}" if scenario_bits else ""
    print(
        f"Starting SoR Autoplay GUI → {args.host}:{args.port} "
        f"({'lockstep 2f/tick' if args.lockstep else f'poll {args.poll_ms}ms'}"
        f"{agent_text}{reach_text}{scenario_text}; Esc/Q to quit)",
        file=sys.stderr,
    )
    return app.run_gui(
        reach_gameplay=args.reach_gameplay,
        reach_gameplay_timeout_ms=args.reach_gameplay_timeout_ms,
    )


if __name__ == "__main__":
    raise SystemExit(main())
