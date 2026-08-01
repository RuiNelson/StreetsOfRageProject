"""Entry point: attach to a running SoR host, observe, and optionally drive AI."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .agent import AgentConfig, AgentState, decide_actions
from .hud import HUD_PAINT_MS_DEFAULT, ObserverHud
from .state import GameSnapshot, disconnected_snapshot, read_snapshot

# Wall-clock sample period. ~2 frames at 60 Hz (2 / 60 * 1000 ≈ 33.3 ms).
DEFAULT_POLL_MS = 33
ASSUMED_HZ = 60
# Frames to hold each AI button mask (standard controls; press_buttons is blocking).
DEFAULT_AGENT_HOLD_FRAMES = 2


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sor-autoplay",
        description=(
            "Observer + optional AI agents for a running StreetsOfRageRecompilation "
            "instance via MegaDriveEnvironment remote access. "
            "Agents use standard controls only (no --altControls)."
        ),
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
            "Wall-clock remote poll period in milliseconds when agents are off "
            f"(default: {DEFAULT_POLL_MS}, ~2 frames at {ASSUMED_HZ} Hz). "
            "Does not wait on VSync. When an agent is on, hold-frames pace input."
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
        "--agent-p1",
        action="store_true",
        help="Start with the P1 agent enabled (standard controls)",
    )
    parser.add_argument(
        "--agent-p2",
        action="store_true",
        help="Start with the P2 agent enabled (standard controls)",
    )
    parser.add_argument(
        "--agent-hold-frames",
        type=int,
        default=DEFAULT_AGENT_HOLD_FRAMES,
        help=(
            "Frames to hold each AI button mask via press_buttons "
            f"(default: {DEFAULT_AGENT_HOLD_FRAMES})"
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one snapshot to stdout and exit (no GUI)",
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
        agent_hold_frames: int = DEFAULT_AGENT_HOLD_FRAMES,
    ) -> None:
        self.host = host
        self.port = port
        self.poll_ms = max(1, poll_ms)
        self.hud_ms = max(16, hud_ms)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: GameSnapshot = disconnected_snapshot("starting")
        self._client = None
        self._hud: ObserverHud | None = None
        self._agent_config = AgentConfig(
            p1_enabled=agent_p1,
            p2_enabled=agent_p2,
            hold_frames=max(1, agent_hold_frames),
        )
        self._agent_memory = AgentState()
        self._agent_notes: tuple[str, str] = ("", "")
        self._was_agent_active = False

    def agent_config(self) -> AgentConfig:
        with self._lock:
            return AgentConfig(
                p1_enabled=self._agent_config.p1_enabled,
                p2_enabled=self._agent_config.p2_enabled,
                hold_frames=self._agent_config.hold_frames,
                police_threshold=self._agent_config.police_threshold,
            )

    def set_agent_enabled(self, player_index: int, enabled: bool) -> None:
        with self._lock:
            if player_index == 1:
                self._agent_config.p1_enabled = enabled
            elif player_index == 2:
                self._agent_config.p2_enabled = enabled

    def toggle_agent(self, player_index: int) -> bool:
        with self._lock:
            if player_index == 1:
                self._agent_config.p1_enabled = not self._agent_config.p1_enabled
                return self._agent_config.p1_enabled
            if player_index == 2:
                self._agent_config.p2_enabled = not self._agent_config.p2_enabled
                return self._agent_config.p2_enabled
        return False

    def agent_notes(self) -> tuple[str, str]:
        with self._lock:
            return self._agent_notes

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
                    self._client = client
                    backoff_s = 0.25

                assert self._client is not None
                snapshot = read_snapshot(self._client)

                config = self.agent_config()
                notes = ("", "")
                if config.any_enabled() and snapshot.connected:
                    decision = decide_actions(snapshot, config, self._agent_memory)
                    notes = (decision.p1_note, decision.p2_note)
                    if decision.steady:
                        if self._was_agent_active:
                            try:
                                self._client.release_buttons()
                            except Exception:  # noqa: BLE001
                                pass
                            self._was_agent_active = False
                    else:
                        # Sticky latch: directions stay held across polls so the
                        # game sees continuous walking (PRESS_BUTTONS always
                        # released after N frames and produced walk-taps).
                        try:
                            self._client.hold_buttons(
                                player1=decision.p1_mask,
                                player2=decision.p2_mask,
                            )
                        except AttributeError:
                            # Older megadrive_remote without HOLD_BUTTONS.
                            self._client.press_buttons(
                                player1=decision.p1_mask,
                                player2=decision.p2_mask,
                                frames=max(config.hold_frames, 4),
                            )
                        self._was_agent_active = bool(
                            decision.p1_mask or decision.p2_mask
                        )
                        if not self._was_agent_active:
                            try:
                                self._client.release_buttons()
                            except Exception:  # noqa: BLE001
                                pass
                elif self._was_agent_active:
                    try:
                        self._client.release_buttons()
                    except Exception:  # noqa: BLE001
                        pass
                    self._was_agent_active = False

                with self._lock:
                    self._latest = snapshot
                    self._agent_notes = notes

                # Wall-clock cadence always (hold_buttons is non-blocking).
                elapsed = time.monotonic() - started
                remaining = poll_s - elapsed
                if remaining > 0:
                    self._stop.wait(remaining)
            except Exception as exc:  # noqa: BLE001 - surface any link failure in HUD
                with self._lock:
                    self._latest = disconnected_snapshot(str(exc))
                    self._agent_notes = ("", "")
                if self._client is not None:
                    try:
                        self._client.release_buttons()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        self._client.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._client = None
                self._was_agent_active = False
                self._stop.wait(backoff_s)
                backoff_s = min(2.0, backoff_s * 1.5)

    def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            try:
                self._client.release_buttons()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def latest(self) -> GameSnapshot:
        with self._lock:
            return self._latest

    def run_gui(self) -> int:
        self.start_poller()
        approx_frames = self.poll_ms * ASSUMED_HZ / 1000.0
        self._hud = ObserverHud(
            on_close=self.stop,
            subtitle=f"poll {self.poll_ms}ms (~{approx_frames:.1f}f) · std controls",
            on_toggle_agent=self.toggle_agent,
            agent_config_provider=self.agent_config,
            agent_notes_provider=self.agent_notes,
        )

        def tick() -> None:
            if self._stop.is_set() or self._hud is None:
                return
            try:
                self._hud.update(self.latest())
            except Exception as exc:  # noqa: BLE001
                self._hud.update(disconnected_snapshot(f"HUD error: {exc}"))
            self._hud.schedule(self.hud_ms, tick)

        self._hud.schedule(0, tick)
        try:
            self._hud.run()
        finally:
            self.stop()
        return 0

    def run_once(self) -> int:
        from megadrive_remote import MegaDriveClient

        try:
            with MegaDriveClient(self.host, self.port, connect_timeout=2.0, io_timeout=2.0) as client:
                client.ping()
                snapshot = read_snapshot(client)
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
        agent_hold_frames=args.agent_hold_frames,
    )
    if args.once:
        return app.run_once()
    return app.run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
