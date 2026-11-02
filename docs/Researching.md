# Researching

[Back to the README](../README.md)

The project's tools for studying the game. How they fit together is in
[Developer Journey and Project Structure](DeveloperJourney.md).

## Disassembly

Write the annotated assembly of your ROM to `StreetsOfRageRecompilation/output/`
(`sor.asm` and `sor.map`, ignored by Git):

```bash
./scripts/disassemble_to_asm.py
```

The labels and auxiliary addresses it uses are in
`StreetsOfRageRecompilation/code-analysis/`, and the manuscripts about the game's systems
in `StreetsOfRageRecompilation/ai-analysis/`. The rest of the tools are listed by:

```bash
cd StreetsOfRageRecompilation
PYTHONPATH=../RageDecompiler python3 -m tools --help
```

## Discovering entry points

The [discovery loop](DeveloperJourney.md#the-ragedecompiler-recompiler) adds the targets of
indirect calls to `code-analysis/aux_addresses.txt`, either one confirmed address at a time or
with speculative addresses:

```bash
./scripts/discover_aux_conservative.py
```

```bash
./scripts/discover_aux_smart.py
```

## Call-map database

Record a runtime call log by running the game with `--call-log`:

```bash
./scripts/run.py --call-log calls.csv
```

Collapse it into unique observed control-flow relationships:

```bash
cd StreetsOfRageRecompilation
python3 tools/call_map.py ../calls.csv \
  --database call-map.sqlite
```

New logs have the header `event,source,callsite,target`. A `call` row fills all
three address fields; an `entry` row uses `source` for the entered routine and
leaves `callsite` and `target` empty. The tool also accepts legacy three-column
call logs.

The SQLite database keeps every routine from `labels.csv`, including routines
with no activity in the captured run. Dynamic entry counts are stored in
`subroutine_entry`; deduplicated calls use `callsite`, `call_edge`, and
`callsite_target`. The `subroutine_activity`, `subroutine_flow`, and
`callsite_flow` views provide human-readable queries:

```bash
sqlite3 -header -column call-map.sqlite \
  'SELECT * FROM callsite_flow ORDER BY observed_count DESC LIMIT 20;'
```

Pass `--port` to start the interactive web viewer after generating the
database. `--labels` selects the labels file used for subroutine names:

```bash
python3 tools/call_map.py ../calls.csv \
  --database call-map.sqlite \
  --port 8080 \
  --labels code-analysis/labels.csv
```

Open `http://127.0.0.1:8080` to search all known routines, distinguish executed
entries from labelled-only routines, inspect observed call counts, and navigate
incoming and outgoing calls including their callsites. The server binds only
to localhost by default; pass `--host` explicitly to expose it on a different
interface.

Current logs record the dynamic 68000 entry as their source, including when
several entries share one generated C++ body. The tool always preserves a
source already present in `labels.csv`. For older logs it approximates
anonymous grouped C++ owners from the closest label; use
`--trust-recorded-source` to disable that approximation. Since old logs cannot
reliably reconstruct every non-contiguous entry, regenerate the log after
recompiling when an expected routine such as `$019D16` is absent.

## Observing the running game

`sor --debug-utils` opens remote access, which lets Python read the game's memory, the VDP and
the framebuffer while it runs: see
[`MegaDriveEnvironment/python/README.md`](../MegaDriveEnvironment/python/README.md) for the
client and [`autoplay/README.md`](../autoplay/README.md) for the observer built on it. The
keyboard captures and cheats are in [Playing](Playing.md#host-keyboard-shortcuts).
