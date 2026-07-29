---
name: explore-call-map
description: >
  Generate, query, and interactively explore deduplicated Streets of Rage
  runtime subroutine-call maps with
  StreetsOfRageRecompilation/tools/call_map.py. Use when asked to process a
  typed entry/call log (or legacy source,callsite,target log), create or inspect
  call-map.sqlite, find
  callers/callees or callsites, apply code-analysis/labels.csv names, start the
  call-map web viewer, or investigate observed 68000 call flows. Triggers
  include "call map", "call log", "mapa de chamadas", "fluxos de subrotinas",
  "callsites", "call-map.sqlite", and "visualizar chamadas".
---

# Explore the runtime call map

Work from the `StreetsOfRageProject/` meta-repository. Read the root
`CLAUDE.md` and `StreetsOfRageRecompilation/CLAUDE.md` before changing or
publishing project files.

Use the checked-in
`StreetsOfRageRecompilation/tools/call_map.py`; do not recreate its aggregation
logic. The tool accepts one or more CSV logs with the exact header
`event,source,callsite,target` and legacy logs with the exact header
`source,callsite,target`. It collapses repeated events, stores the result in
SQLite, includes every labels.csv routine even when unobserved, and can serve a
read-only interactive viewer.

Treat the web viewer strictly as a presentation surface for humans. When an AI
agent needs to inspect or reason about the call map, query the SQLite database
directly; do not start the web server or use browser automation for agent-side
analysis.

## Workflow

1. Resolve the input log paths, output database path, and labels file. Prefer
   `StreetsOfRageRecompilation/code-analysis/labels.csv`.
2. Inspect `python3 StreetsOfRageRecompilation/tools/call_map.py --help` before
   invoking it so the skill stays aligned with the checked-in interface.
3. Check that the database path is not an input log or the labels file. The
   database is regenerated, so preserve an existing database if the user needs
   it.
4. Generate the SQLite map. Add `--port` only when a human explicitly wants an
   interactive viewer; never add it merely so an agent can inspect the data.
5. Report entry-event, call-event, flow, and callsite counts printed by the
   tool. For SQL analysis, query the human-readable `subroutine_activity`,
   `subroutine_flow`, and `callsite_flow` views before joining raw tables.
6. Treat logs, SQLite databases, screenshots, and exported call maps as local
   analysis artefacts. Do not stage or commit them unless the user explicitly
   requests that exact artefact be versioned.

## Generate a database

```bash
python3 StreetsOfRageRecompilation/tools/call_map.py calls.csv \
  --database StreetsOfRageRecompilation/call-map.sqlite \
  --labels StreetsOfRageRecompilation/code-analysis/labels.csv
```

Pass multiple log paths to merge observations from several runs.

New logs contain `call` events with all address fields and `entry` events whose
`source` is the entered routine and whose other address fields are empty. The
tool preserves source addresses already present in `labels.csv`. For older
logs it approximates anonymous grouped C++ owners from the closest preceding
label; use `--trust-recorded-source` to disable that approximation. Legacy logs
have no entry events, so they cannot prove whether a routine executed.

## Start the web viewer

Use this mode only to let a human explore the map visually. Agents must use the
SQLite queries below instead.

```bash
python3 StreetsOfRageRecompilation/tools/call_map.py calls.csv \
  --database StreetsOfRageRecompilation/call-map.sqlite \
  --labels StreetsOfRageRecompilation/code-analysis/labels.csv \
  --port 8080
```

Keep the process handle while the viewer is needed and provide
`http://127.0.0.1:8080` to the user. It binds to localhost by default. Do not
use `--host 0.0.0.0` or another externally reachable interface unless the user
explicitly asks to expose it. Stop temporary validation servers before
finishing; leave a user-requested server running only when the environment can
reliably preserve its process.

If a human-facing viewer change itself requires visual validation, use the
available browser-control skill against the localhost URL, verify search and
subroutine navigation, then close the validation tab and stop the temporary
server. Do not use browser control to extract or analyze call relationships.

## SQLite schema

Use these tables for agent-side analysis:

| Object | Purpose | Key columns |
|---|---|---|
| `metadata` | Generation context and event totals | `key`, `value` |
| `subroutine` | Every labelled routine plus anonymous observed routines | `address` PK, `name`, `description` |
| `subroutine_entry` | Dynamic entry counts; absent row means zero entries | `address` PK/FK, `observed_count` |
| `callsite` | Call instructions grouped by their source routine | composite PK (`source_address`, `address`), `observed_count` |
| `call_edge` | Deduplicated source-to-target flows | composite PK (`source_address`, `target_address`), `observed_count` |
| `callsite_target` | Exact source/callsite/target relationships | composite PK (`source_address`, `callsite_address`, `target_address`), `observed_count` |

`callsite.source_address`, both addresses in `call_edge`, and the source and
target addresses in `callsite_target` refer to `subroutine.address`.
`callsite_target.(source_address, callsite_address)` refers to
`callsite.(source_address, address)`. Target indexes support reverse-caller
queries.

Raw-table addresses are 24-bit integers. These views join labels and format
addresses as `$XXXXXX` text:

- `subroutine_activity(address, name, description, entry_count,
  incoming_flows, outgoing_flows)`
- `subroutine_flow(source_address, source_name, target_address, target_name,
  observed_count)`
- `callsite_flow(source_address, source_name, callsite_address,
  target_address, target_name, observed_count)`

`observed_count` is the number of runtime events collapsed into that row; it is
not a static reachability weight. Expected `metadata` keys are
`format_version`, `total_events`, `call_events`, `entry_events`,
`normalized_source_events`, and `input_files`.

## Query useful relationships

Top observed flows:

```bash
sqlite3 -header -column StreetsOfRageRecompilation/call-map.sqlite \
  'SELECT * FROM subroutine_flow ORDER BY observed_count DESC LIMIT 20;'
```

Find labelled routines that were not observed entering:

```bash
sqlite3 -header -column StreetsOfRageRecompilation/call-map.sqlite \
  'SELECT address, name FROM subroutine_activity
   WHERE entry_count = 0 ORDER BY address;'
```

Callsites for one labelled subroutine:

```bash
sqlite3 -header -column StreetsOfRageRecompilation/call-map.sqlite \
  "SELECT * FROM callsite_flow
   WHERE source_name = 'update_player_object'
      OR target_name = 'update_player_object'
   ORDER BY observed_count DESC;"
```

Use parameterized queries in Python when names or addresses come from
untrusted input. A routine present only because of `labels.csv` is known but
not observed in that run. Explain that entries and graph edges are runtime
observations, not proof of every statically possible path.

## Missing log

If no call log exists, explain that the game can create one with:

```bash
StreetsOfRageRecompilation/build/sor \
  --rom StreetsOfRageRecompilation/rom/SOR.bin \
  --callLog calls.csv
```

Do not launch or automate the game unless the user asks. If they do, use the
`control-megadrive-game` skill and follow its bounded-run requirements.

## Completion criteria

Provide the exact command used, database location, aggregation counts, viewer
URL when applicable, and any SQL result requested. Confirm that no temporary
server remains and that generated analysis artefacts were not committed.
