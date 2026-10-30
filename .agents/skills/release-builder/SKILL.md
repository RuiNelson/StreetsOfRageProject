---
name: release-builder
description: >
  Publish a GitHub release of StreetsOfRageBuilder: bump the version, build all
  platforms with the Builder GitHub Action, and create the release with the
  five binaries and the project's release-notes format. Use when asked to
  release, publish, or ship a new Builder version, "lançar a versão X.Y.Z",
  "criar release", or "gerar release no GitHub".
---

# Release the Builder

Releases are tags of the meta-repository (`0.2.0`, no `v`) on `main`, titled
`Version X.Y.Z - {{ main feature }}`, with the Builder binaries attached.
Work on `main` only; never force-push.

## 1. Ask the user (skip what they already said)

- the version `X.Y.Z` (the last one: `gh release list --limit 3`);
- the main feature for the title;
- the release state: published now, draft, or artifacts only.

## 2. Bump the version

Run the script from the meta-repository root; it sets `X.Y.Z` in both
StreetsOfRageRecompilation (`main.cpp`, `sor --version`) and
StreetsOfRageBuilder (the workflow names the files from `tauri.conf.json`):

```bash
./scripts/update_version_everywhere.py X.Y.Z    # --dry-run lists the changes only
```

It edits `StreetsOfRageRecompilation/main.cpp`,
`StreetsOfRageBuilder/Backend/{tauri.conf.json,Cargo.toml,Cargo.lock}` and
`StreetsOfRageBuilder/Frontend/{package.json,package-lock.json}`; do not edit
them by hand or with `sed`.

Check with `cd StreetsOfRageBuilder/Backend && cargo check --offline`, then
commit and push to `main` (inspect `git status` first; leave unrelated files
out). `StreetsOfRageRecompilation` is a submodule: commit and push it first,
then include its gitlink in the meta-repository commit.

## 3. Build all platforms

```bash
gh workflow run builder.yml --ref main      # every platform defaults to on
gh run list --workflow=builder.yml --limit 1
gh run watch RUN_ID --exit-status >/dev/null 2>&1; gh run view RUN_ID --json conclusion,jobs
```

All five jobs (`macos-universal`, `windows-x64`, `windows-arm64`, `linux-x64`,
`linux-arm64`) must succeed. The run must be of the commit that carries the
version bump (the workflow is dispatched on `main`'s tip). On failure, read
`gh run view RUN_ID --log-failed`, fix, and rebuild; do not release a partial
set unless the user says so.

## 4. Collect the files

Use the scratchpad, not the repository:

```bash
gh run download RUN_ID --repo RuiNelson/StreetsOfRageProject -D DIR
```

Each artifact `StreetsOfRageBuilder-<platform>/` holds one file already named
`StreetsOfRageBuilder-X.Y.Z-<platform>.<dmg|exe|AppImage>`. Check the five
names carry the new version, and `file` them (Windows `PE32+ … x86-64` /
`Aarch64`, Linux `ELF … x86-64` / `aarch64`; the dmg can be mounted and
`lipo -archs` on its app must show `x86_64 arm64`). The binaries are unsigned
and not run on the build host: say so in the report.

## 5. Release notes

Write them to a file in the scratchpad in exactly this format. The bullets are
for **players** (what the wizard does, fixes they would notice); leave out
documentation, CI, refactors and other developer details. Ask the user what changed since the
previous release if it is not clear from the conversation; for a first Builder
release describe the whole wizard.

````markdown
* User-facing feature or fix.
* …

## Run Instructions

The apps are not signed yet, so your system will warn you the first time. It is safe to continue.

### macOS

You'll need to remove the quarantine attribute so Gatekeeper allows execution, use [Xattr-remove by perez987](https://github.com/perez987/Xattr-remove) or the command line:

```
xattr -dr com.apple.quarantine "/Applications/Streets of Rage Builder.app"
```

Open the `.dmg`, drag **Streets of Rage Builder** to Applications, run the command above, then open the app.

### Windows

1. Download `StreetsOfRageBuilder-X.Y.Z-windows-x64.exe` (or `-windows-arm64.exe` on ARM PCs such as Snapdragon).
2. Chrome and Edge may say the file *"isn't commonly downloaded"* or *"could be dangerous"*. In the downloads list, open the `⋯` menu next to the file and choose **Keep**, then **Keep anyway** (in Edge: **Keep** > **Show more** > **Keep anyway**).
3. Double-click the file. If Windows SmartScreen shows *"Windows protected your PC"*, click **More info**, then **Run anyway**.

### Linux

Download the AppImage for your CPU (`x64` or `arm64`), then make it executable and run it:

```
chmod +x StreetsOfRageBuilder-X.Y.Z-linux-x64.AppImage
./StreetsOfRageBuilder-X.Y.Z-linux-x64.AppImage
```

Or right-click the file, open **Properties** > **Permissions** and tick **Allow executing file as program**, then double-click it. If it fails with a FUSE error, install `libfuse2` (`sudo apt install libfuse2`; on Ubuntu 24.04 `libfuse2t64`) or run it with `--appimage-extract-and-run`.
````

The title is the release name, not part of the notes file:
`Version X.Y.Z - {{ Main feature }}`. Replace `X.Y.Z` everywhere in the notes.
If the app name, step list or platforms changed, update the text to match.

## 6. Create the release

Pin the tag to the commit that was built:

```bash
gh release create X.Y.Z --target "$(git rev-parse HEAD)" \
  --title "Version X.Y.Z - Main feature" --notes-file NOTES.md DIR/*/*
# add --draft when the user asked for a draft
gh release view X.Y.Z --json url,assets --jq '.url, (.assets[]|.name)'
```

Publishing is outward-facing: only create the release in the state the user
chose in step 1. Report the URL, the five asset names, and what was not
tested (binaries not executed on each platform).
