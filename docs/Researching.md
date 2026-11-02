# Researching

[Back to the README](../README.md)

This project exists to make the game's internals available for study. Here is how to read the game, watch
it run and add to what is known. [Developer Journey and Project Structure](DeveloperJourney.md) explains how
these tools came about.

All of it needs [a build](BuildingDesktop.md#building-by-hand) and your own ROM. Unless a command starts with
`cd`, run it from the root of the repository.

- [Reading the code](#reading-the-code)
- [Who calls whom: the call map](#who-calls-whom-the-call-map)
- [Observing the running game](#observing-the-running-game)
- [Finding missing code](#finding-missing-code)
- [Keeping the analysis in step](#keeping-the-analysis-in-step)

## Reading the code

Start with the assembly of the whole program, which this writes to `StreetsOfRageRecompilation/output/`
(`sor.asm` and `sor.map`, ignored by Git because they come from the ROM):

```bash
./scripts/disassemble_to_asm.py
```

Three more places in `StreetsOfRageRecompilation/` help you read it:

- **[`ai-analysis/`](../StreetsOfRageRecompilation/ai-analysis/)** has a manuscript per system, explaining
  behavior: graphics, backgrounds and scrolling, compression, sound, controls, levels, combat, items, the
  campaign, and [every enemy and boss](../StreetsOfRageRecompilation/ai-analysis/enemy-ai.md).
- **`code-analysis/`** has the authority on names and locations (`labels.csv`, `addresses.csv`), and the list
  of routines rewritten by hand (`manual_functions.txt`).
- **`generated/`** has the same program as C++, useful for navigating. Treat the assembly as the primary
  evidence.

The other tools are listed by:

```bash
cd StreetsOfRageRecompilation && PYTHONPATH=../RageDecompiler python3 -m tools --help
```

## Who calls whom: the call map

The assembly shows what could be called. A call log shows what was. Play with logging on, doing whatever you
want to study:

```bash
./scripts/run.py --call-log calls.csv
```

Then collapse the log into a SQLite database of unique relationships:

```bash
cd StreetsOfRageRecompilation && python3 tools/call_map.py ../calls.csv --database call-map.sqlite
```

### Asking it questions

From `StreetsOfRageRecompilation/`, this asks which routines called `$019D16`, and from where:

```bash
sqlite3 -header -column call-map.sqlite "SELECT source_name, callsite_address, observed_count FROM callsite_flow WHERE target_address = '\$019D16' ORDER BY observed_count DESC;"
```

And this asks which labelled routines never ran in that session:

```bash
sqlite3 -header -column call-map.sqlite 'SELECT address, name FROM subroutine_activity WHERE entry_count = 0;'
```

Three views give the human-readable answers:

| View                  | One row for each                                                                  |
| --------------------- | --------------------------------------------------------------------------------- |
| `subroutine_activity` | Routine: how many times it was entered, and how many others it calls or is called by |
| `subroutine_flow`     | Observed caller and callee, with a count                                          |
| `callsite_flow`       | Observed caller, call site and callee, with a count                               |

Their data is in the tables `subroutine_entry`, `callsite`, `call_edge` and `callsite_target`. The database keeps
every routine from `labels.csv`, including those with no activity. Counts are observations, not proof of every
path: a routine that never ran in your session may still run in another.

### Browsing it

Pass `--port` to open the interactive viewer after generating the database:

```bash
cd StreetsOfRageRecompilation && python3 tools/call_map.py ../calls.csv --database call-map.sqlite --port 8080
```

At `http://127.0.0.1:8080` you can search all known routines, tell the ones that ran from the ones only labelled,
see call counts, and walk incoming and outgoing calls with their call sites. The server listens only on localhost
unless you pass `--host`. `--labels` selects another labels file.

### Log format

A log's header is `event,source,callsite,target`. A `call` row fills all three addresses, and an `entry` row has
only `source`, the routine entered. The tool also accepts old three-column logs.

Current logs record the 68000 routine actually entered, even when several entries share one generated C++ body, and
a source already in `labels.csv` is always kept. For old logs the tool guesses anonymous grouped owners from the
closest label; `--trust-recorded-source` turns that off. Old logs cannot reliably reconstruct every non-contiguous
entry, so if a routine you expect is missing, recompile and record a new log.

## Observing the running game

With `--debug-utils`, the game opens a TCP port through which a program can read its memory, VDP and framebuffer as
it runs. This Python script reads the frame counter, and the word that is nonzero during a pause or a police special:

```python
from megadrive_remote import MegaDriveClient

with MegaDriveClient("127.0.0.1", 6969) as game:
    print(game.get_game_uptime_frames())
    print(game.read_value(0xFFFA1A, width=2))
```

Start the game, then run the script from a second terminal with
`PYTHONPATH=MegaDriveEnvironment/python/src python3 your_script.py`:

```bash
./scripts/run.py --debug-utils
```

The [client's README](../MegaDriveEnvironment/python/README.md) has the rest of its API. For a ready-made view, use the
observer, a live HUD and 2D map of every actor, described in [`autoplay/README.md`](../autoplay/README.md):

```bash
./scripts/autoplay.py
```

A few other things help you get to the moment you want to study:

- `Alt`/`Option` + `1`–`8` [jumps to a level](Playing.md#debug-cheats), and other cheats clear enemies or add lives.
- `Ctrl+S` [saves the VDP's complete state](Playing.md#keyboard-shortcuts) as an image: frame, tile sheets, nametables
  and registers. `Ctrl+P` saves the frame.
- `./scripts/play.py --preset boss --level N` puts the AI straight in front of a round's boss.

## Finding missing code

The recompiler can't see routines reached only through jump tables and other indirect calls, as
[the journey explains](DeveloperJourney.md#from-68000-code-to-c-ragedecompiler). Two scripts find them, adding what
they confirm to `code-analysis/aux_addresses.txt`. Add only code the game can reach: the cartridge's dead code stays out
of the recompilation.

The conservative one rebuilds and runs the game again for each address it discovers:

```bash
./scripts/discover_aux_conservative.py
```

The smart one seeds speculative addresses first, so that a single build can confirm many:

```bash
./scripts/discover_aux_smart.py
```

Both find only what an unattended run reaches. A target that needs a particular situation shows up instead as an abort
during play, with the address on standard error:

```text
indirect dispatch to unknown address $XXXXXX (in fn $YYYYYY)
```

When that happens, read the dispatching code in `output/sor.asm` and decode its jump table in the ROM. Add **every**
target to `aux_addresses.txt`, not only the one you saw, because the others are the same path in another situation.
Then generate the C++ again, rebuild, and repeat the situation on purpose.

## Keeping the analysis in step

Names have one home. `code-analysis/labels.csv` and `addresses.csv` decide what a routine is called, and the manuscripts
must not invent their own vocabulary. After adding, renaming, moving or removing a symbol, update the manuscripts from
those files and check the result:

```bash
cd StreetsOfRageRecompilation && ./sync_ai_analysis.py && ./sync_ai_analysis.py --check
```

When a code label changes, regenerate what derives from it as well. Never rename a symbol directly in `output/sor.asm` or
in the generated C++:

```bash
./scripts/disassemble_to_asm.py
```

```bash
./scripts/generate_cpp_and_build.py
```
