"""What the ``sor`` host runs in its own process (``SoRPython.cpp``): P2's AI.

``host`` is the ``sor_host`` module the game provides. It is handed in rather
than imported so that this package still loads anywhere else.

Every image of the work RAM the game publishes goes through the same
``snapshot_from_work_ram`` + ``AgentLoop.tick`` as ``autoplay``'s lockstep loop.
The AI's commands reach the game as the same binary input documents a remote
client sends, without the socket.
"""

from __future__ import annotations

import time
import traceback

from .ai.gamepad import SharedGamepadState, VirtualGamepad
from .ai.loop import AgentLoop
from .remote_input import InputDocument, PlayerInput, md_buttons_to_actions, pack_input
from .rom_data import RomData
from .state import snapshot_from_work_ram

AI_PLAYER = 2
WAIT_FRAME_S = 0.25


class InProcessClient:
    """The pad's ``ButtonClient`` and a ``MemorySource``, over ``sor_host``.

    Same timing as ``sor_autoplay.sor_remote.SoRClient``: a queued press starts
    on the next sampled frame, replaces the held mask while it plays, and one
    queued behind another waits for it and a released frame. It only speaks for
    ``AI_PLAYER``, the only seat the game takes from it.
    """

    def __init__(self, host) -> None:
        self._host = host
        self.six_button = False
        self._serial = 0
        self._seq = 0
        self._record = PlayerInput()
        self._release = 0

    def read_memory(self, address: int, length: int) -> bytes:
        return self._host.read_memory(address, length)

    def enhanced(self, player: int) -> bool:
        return self.six_button

    def hold_buttons(self, *, player1: int = 0, player2: int = 0) -> None:
        record = self._record
        self._record = PlayerInput(self._actions(player2), record.seq, record.queue, record.schedule)
        self._send()

    def queue_press_buttons(self, *, player: int, buttons: int, frames: int = 1) -> int:
        if player != AI_PLAYER:
            raise ValueError("the embedded AI only plays P2")
        now = self._host.current_frame()
        start = self._release + 1 if self._release >= now + 1 else now + 1
        self._release = start + frames
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        self._record = PlayerInput(self._record.held, self._seq, True, ((self._actions(buttons), frames),))
        self._send()
        return self._release

    def reset(self) -> None:
        """The game restarted: nothing held, no press left to wait for."""

        self._release = 0
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        self._record = PlayerInput(seq=self._seq)
        self._send()

    def _actions(self, mask: int) -> int:
        return md_buttons_to_actions(mask, enhanced=self.six_button)

    def _send(self) -> None:
        self._serial = (self._serial + 1) & 0xFFFFFFFF
        self._host.set_input(pack_input(InputDocument({AI_PLAYER: self._record}, self._serial)))


def _read_rom(client: InProcessClient, host) -> RomData | None:
    try:
        return RomData.read(client)
    except Exception:  # noqa: BLE001 - as the observer: losing them degrades, never fails
        host.log("could not read the ROM's shape and animation tables:\n" + traceback.format_exc())
        return None


class _Stats:
    def __init__(self) -> None:
        self.ticks = 0
        self.total_s = 0.0
        self.worst_s = 0.0
        self.skipped = 0
        self.failed = 0

    def summary(self) -> str:
        mean = 1000.0 * self.total_s / self.ticks if self.ticks else 0.0
        return (
            f"{self.ticks} ticks, mean {mean:.2f} ms, worst {1000.0 * self.worst_s:.1f} ms, "
            f"{self.skipped} skipped, {self.failed} failed"
        )


def run(host) -> None:
    """Play P2 until the game asks the AI to end."""

    client = InProcessClient(host)
    state = SharedGamepadState(client)

    def new_loop() -> AgentLoop:
        return AgentLoop(VirtualGamepad(state, player_index=AI_PLAYER))

    loop = new_loop()
    rom: RomData | None = None
    rom_read = False
    last_frame: int | None = None
    frames_per_tick = 2
    stats = _Stats()

    while not host.stop_requested():
        published = host.wait_frame(WAIT_FRAME_S)
        if published is None:
            continue
        frame, ram, enhanced = published
        # The ROM is loaded by the first frame the game publishes.
        if not rom_read:
            rom = _read_rom(client, host)
            rom_read = True
            host.log("AI on P2")
        if last_frame is not None and frame < last_frame:
            client.reset()
            state.reset()
            loop = new_loop()
        elif last_frame is not None:
            stats.skipped += max(0, (frame - last_frame) // frames_per_tick - 1)
        last_frame = frame
        client.six_button = enhanced

        started = time.perf_counter()
        try:
            snapshot = snapshot_from_work_ram(
                ram, rom=rom, uptime_frames=frame, widescreen=host.widescreen()
            )
            loop.tick(snapshot, player_index=AI_PLAYER)
        except Exception:  # noqa: BLE001 - one bad tick must not lose the rest of the game
            if stats.failed == 0:
                host.log("a tick failed (later ones only counted):\n" + traceback.format_exc())
            stats.failed += 1
            state.release(AI_PLAYER)
        elapsed = time.perf_counter() - started
        stats.ticks += 1
        stats.total_s += elapsed
        stats.worst_s = max(stats.worst_s, elapsed)

    host.log(f"ended: {stats.summary()}")
