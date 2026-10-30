"""The Streets of Rage symbolic AI's core: no HUD, no sockets, no remote client.

The same code plays through ``sor_autoplay`` (an external process, over the
remote-access port) and inside the ``sor`` host. It reads the game from a
work-RAM image or a ``state.MemorySource`` and acts through a
``ai.gamepad.ButtonClient``; whoever runs it supplies those two.
"""
