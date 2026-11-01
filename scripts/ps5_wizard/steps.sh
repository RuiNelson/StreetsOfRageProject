#!/bin/bash
# The steps of the PS5 build wizard (scripts/ps5_wizzard.sh). Source tui.sh first, then this.
#
# The platform file (macos.sh or linux.sh) supplies these before wizard_main runs:
#   platform_engine_options        prints "Name|URL|note" lines: where to get a container engine
#   platform_engine_start_hint     prints how to start an installed engine
#   platform_tools_hint            prints how to install curl and zip, when they are missing
#   platform_open_url URL
#   platform_sha256 FILE           prints the SHA-256 in lowercase hex
#   platform_pick_file             prints a path chosen in a file dialog (non-zero status: none)
#   platform_fix_ownership         optional: gives the user the files a root container wrote
#   DOCKER_WORKSPACE_OPTIONS       optional suffix for the workspace mount (":z" under SELinux)
#
# The build is the one scripts/build_ps5.py does, with the same image and volume names, run here
# with `docker` only, so the computer needs nothing else installed.

STEP_NAMES=("Docker" "ROM" "Soundtrack" "Build" "Deliver" "Clean up")

IMAGE=sor-ps5-toolchain
BUILD_VOLUME=sor-ps5-build
TITLE_ID=PPSA99872
ROM_SHA256=95d7efb98e97f4ffffe68257aef9a855034a36a41b86cf9d332d129f30cb2d4b
ROM_SIZE=524288
FTP_DEFAULT_PORT=2121
ZIP_HOMEBREW_NAME=StreetsOfRage-PS5-homebrew.zip
ZIP_DATA_NAME=StreetsOfRage-PS5-data.zip

wizard_paths() {
    REPO_ROOT=$(cd "$SCRIPTS_DIR/.." && pwd)
    SOR_DIR=$REPO_ROOT/StreetsOfRageRecompilation
    DOCKER_CONTEXT=$SOR_DIR/prospero/docker
    ROM_DEST=$SOR_DIR/rom/SOR.bin
    SOUNDTRACK_DIR=$SOR_DIR/rom/soundtrack
    GENERATED_DIR=$SOR_DIR/generated
    DIST_DIR=$SOR_DIR/dist-ps5
    OUTPUT_DIR=$(pwd)

    # What was there before the wizard: cleaning up removes only what it made.
    HAD_ROM=0; [ -f "$ROM_DEST" ] && HAD_ROM=1
    HAD_SOUNDTRACK=0; [ -e "$SOUNDTRACK_DIR" ] && HAD_SOUNDTRACK=1
    HAD_GENERATED=0; [ -e "$GENERATED_DIR" ] && HAD_GENERATED=1
    HAD_DIST=0; [ -e "$DIST_DIR" ] && HAD_DIST=1
    ZIPS_MADE=()
}

docker_run() {  # docker_run COMMAND...: the toolchain image with the workspace and the build volume
    docker run --rm -v "$REPO_ROOT:/workspace${DOCKER_WORKSPACE_OPTIONS:-}" -v "$BUILD_VOLUME:/build" "$IMAGE" "$@"
}

die() {  # die MESSAGE: a final, readable stop
    blank
    fail "$*"
    blank
    exit 1
}

fix_ownership() {
    if type platform_fix_ownership >/dev/null 2>&1; then
        platform_fix_ownership
    fi
}

menu_or_die() {  # a menu whose last item is always "Quit"
    menu "$@"
    if [ "$MENU_CHOICE" -eq $(($# - 1)) ]; then
        blank
        muted "Stopped by you. Nothing else was changed."
        exit 0
    fi
}

# ---------------------------------------------------------------------------
# Preflight

check_workspace() {
    local tool missing_tools=""
    for tool in curl zip awk fold sed find; do
        command -v "$tool" >/dev/null 2>&1 || missing_tools+=" $tool"
    done
    if [ -n "$missing_tools" ]; then
        screen_clear
        banner
        fail "These programs are needed and were not found:$missing_tools"
        blank
        platform_tools_hint | while IFS= read -r line; do say "$line"; done
        blank
        exit 1
    fi

    local missing=""
    [ -f "$DOCKER_CONTEXT/Dockerfile" ] || missing="StreetsOfRageRecompilation/prospero/docker/Dockerfile"
    [ -f "$REPO_ROOT/RageDecompiler/tools/__main__.py" ] || missing="RageDecompiler/tools"
    [ -d "$REPO_ROOT/MegaDriveEnvironment" ] && [ -n "$(ls -A "$REPO_ROOT/MegaDriveEnvironment" 2>/dev/null)" ] ||
        missing="MegaDriveEnvironment"
    if [ -n "$missing" ]; then
        screen_clear
        banner
        fail "This copy of the project is incomplete: $missing is missing."
        blank
        say "Fetch the submodules, and use the branch that has the PS5 port (prospero):"
        blank
        muted "git submodule update --init --recursive"
        blank
        exit 1
    fi
    if [ ! -w "$OUTPUT_DIR" ]; then
        die "The current folder is not writable, and the ZIP files go there: $OUTPUT_DIR"
    fi
}

# ---------------------------------------------------------------------------
# 1. Container engine

step_docker() {
    step_begin 1 "Container engine"
    say "The whole build runs inside a container, so the only thing to install on this computer is a container engine."
    blank

    local line name url note
    while true; do
        if ! command -v docker >/dev/null 2>&1; then
            warn "No container engine was found (no 'docker' command)."
            blank
            say "Install one of these (any of them works):"
            blank
            local options=() urls=()
            while IFS='|' read -r name url note; do
                [ -n "$name" ] || continue
                printf '    %s%s%s  %s\n' "$BOLD" "$name" "$RST" "$note"
                printf '    %s%s%s\n\n' "$INFO" "$url" "$RST"
                options+=("Open the $name page")
                urls+=("$url")
            done < <(platform_engine_options)
            options+=("I installed one: check again" "Quit")
            menu_or_die "${options[@]}"
            if [ "$MENU_CHOICE" -lt "${#urls[@]}" ]; then
                platform_open_url "${urls[$MENU_CHOICE]}"
            fi
            step_begin 1 "Container engine"
            continue
        fi
        if ! docker info >/dev/null 2>&1; then
            warn "A 'docker' command exists, but the engine is not running."
            blank
            platform_engine_start_hint | while IFS= read -r line; do say "$line"; done
            blank
            menu_or_die "Check again" "Quit"
            step_begin 1 "Container engine"
            continue
        fi
        break
    done

    local engine
    engine=$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)
    ok "Container engine ready${engine:+: $engine}"

    local free_kb
    free_kb=$(df -k "$REPO_ROOT" | awk 'NR == 2 { print $4 }')
    if [ -n "$free_kb" ] && [ "$free_kb" -lt $((12 * 1024 * 1024)) ] 2>/dev/null; then
        warn "Only $(human_size $((free_kb * 1024))) free here; the build needs about 12 GB."
    fi
    blank
    wait_enter
}

# ---------------------------------------------------------------------------
# 2. ROM

clean_path() {  # a path as a terminal hands it over: quotes, backslash escapes, ~, trailing blanks
    local path=$1
    path=$(printf '%s' "$path" | sed -e 's/[[:space:]]*$//' -e 's/^[[:space:]]*//')
    case "$path" in
        \'*\') path=${path#\'}; path=${path%\'} ;;
        \"*\") path=${path#\"}; path=${path%\"} ;;
        *) path=$(printf '%s' "$path" | sed 's/\\\(.\)/\1/g') ;;
    esac
    case "$path" in
        '~'/*) path=$HOME/${path#\~/} ;;
        '~') path=$HOME ;;
    esac
    printf '%s' "$path"
}

rom_problem() {  # rom_problem FILE: prints why it is not usable; status 0 when it is fine
    local file=$1 extension size hash
    if [ ! -f "$file" ]; then
        echo "That is not a file: $file"
        return 1
    fi
    extension=$(printf '%s' "${file##*.}" | tr '[:upper:]' '[:lower:]')
    case "$extension" in
        bin | md | gen) ;;
        smd)
            echo "SMD files are not supported. Use the raw dump (.bin, .md or .gen)."
            return 1
            ;;
        *)
            echo "A ROM file ends in .bin, .md or .gen (this one ends in .$extension)."
            return 1
            ;;
    esac
    size=$(wc -c <"$file" | tr -d ' ')
    hash=$(platform_sha256 "$file")
    if [ "$hash" != "$ROM_SHA256" ]; then
        echo "This is not the right ROM. It must be the Mega Drive / Genesis JUE Rev. A dump."
        echo "Its SHA-256:  $hash"
        echo "Expected:     $ROM_SHA256"
        if [ "$size" -eq $((ROM_SIZE + 512)) ]; then
            echo "It is 512 bytes longer than a raw dump: it looks like an SMD file, which is not supported."
        elif [ "$size" -ne "$ROM_SIZE" ]; then
            echo "Its size is $size bytes; the raw dump is $ROM_SIZE."
        fi
        return 1
    fi
    return 0
}

step_rom() {
    step_begin 2 "Your Streets of Rage ROM"
    say "The game is built from your own copy of the original Mega Drive / Genesis game: the JUE Rev. A ROM of Streets of Rage (.bin, .md or .gen, the raw dump; .smd is not supported). It never leaves this computer, except in the files you choose to send to your console."
    blank

    if [ -f "$ROM_DEST" ] && [ -z "$(rom_problem "$ROM_DEST")" ]; then
        ok "A verified ROM is already in place: ${ROM_DEST#"$REPO_ROOT"/}"
        blank
        menu "Use it|keep going" "Choose another ROM file"
        if [ "$MENU_CHOICE" -eq 0 ]; then
            return
        fi
        blank
    fi

    local candidate problem
    while true; do
        say "Drag the ROM file onto this window and press ENTER, or type its path."
        say "Press ENTER on an empty line to pick it in a file dialog."
        blank
        ask_text "ROM file"
        candidate=$(clean_path "$REPLY_TEXT")
        if [ -z "$candidate" ]; then
            candidate=$(platform_pick_file) || candidate=""
            if [ -z "$candidate" ]; then
                blank
                warn "No file was chosen. If no dialog opened, type or drag the path instead."
                blank
                continue
            fi
        fi
        blank
        if problem=$(rom_problem "$candidate"); then
            break
        fi
        printf '%s\n' "$problem" | box "$ERR" "Not usable" | sed 's/^/  /'
        blank
    done

    mkdir -p "$(dirname "$ROM_DEST")"
    if [ "$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")" != "$ROM_DEST" ]; then
        cp "$candidate" "$ROM_DEST" || die "Could not copy the ROM to $ROM_DEST"
    fi
    ok "JUE Rev. A verified (SHA-256 ${ROM_SHA256:0:12}...)"
    ok "Copied to ${ROM_DEST#"$REPO_ROOT"/}"
    blank
    wait_enter
}

# ---------------------------------------------------------------------------
# 3. Toolchain image and soundtrack

ensure_image() {
    if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
        box "$INFO" "First time on this computer" <<'EOF'
The PS5 toolchain is built once into a container image: about 5 GB, and it can take a good while. Later runs reuse it.
EOF
        blank
    fi
    BUILDKIT_PROGRESS=plain DOCKER_BUILDKIT=1 run_task "Preparing the toolchain image" \
        docker build -t "$IMAGE" "$DOCKER_CONTEXT" || exit 1
    run_task "Checking the toolchain" docker_run bash /opt/ps5/check-toolchain.sh || exit 1
}

render_soundtrack_script() {
    cat <<'EOF'
set -e
tool=/workspace/StreetsOfRageRecompilation/tools/soundtrack
rom=/workspace/StreetsOfRageRecompilation/rom/SOR.bin
out=/workspace/StreetsOfRageRecompilation/rom/soundtrack
cmake -S "$tool" -B /build/soundtrack -DCMAKE_BUILD_TYPE=Release
cmake --build /build/soundtrack --parallel
rm -rf "$out.rendering"
/build/soundtrack/sor_soundtrack --rom "$rom" --out "$out.rendering" --chip ym3438
rm -rf "$out"
mv "$out.rendering" "$out"
EOF
}

step_soundtrack() {
    step_begin 3 "Pre-rendering the soundtrack"
    say "The music, sound effects and voices are rendered from your ROM into FLAC files. This is done inside the container."
    blank
    ensure_image

    local render=1
    if [ -f "$SOUNDTRACK_DIR/manifest.tsv" ]; then
        blank
        ok "A soundtrack is already rendered: ${SOUNDTRACK_DIR#"$REPO_ROOT"/}"
        blank
        menu "Keep it" "Render it again"
        [ "$MENU_CHOICE" -eq 0 ] && render=0
        blank
    fi
    if [ "$render" -eq 1 ]; then
        blank
        run_task "Rendering the soundtrack (about 4 minutes, 265 MB)" docker_run bash -c "$(render_soundtrack_script)" || exit 1
        [ -f "$SOUNDTRACK_DIR/manifest.tsv" ] || die "The soundtrack folder came out empty: $SOUNDTRACK_DIR"
        fix_ownership
    fi
    blank
    wait_enter
}

# ---------------------------------------------------------------------------
# 4. Generate and compile

step_build() {
    step_begin 4 "Compiling the title for the PS5"
    say "Your ROM is translated to C++, then compiled for the console with the PS5 toolchain. The first build is the long one."
    blank
    run_task "Generating the C++ port from your ROM" \
        docker_run env PYTHONDONTWRITEBYTECODE=1 python3 /workspace/scripts/generate_cpp.py || exit 1
    run_task "Compiling the PS5 title" \
        docker_run bash /workspace/StreetsOfRageRecompilation/prospero/tools/build.sh || exit 1
    fix_ownership
    [ -f "$DIST_DIR/$TITLE_ID/eboot.bin" ] && [ -d "$DIST_DIR/data-sor/ai-code" ] ||
        die "The build finished but its files are not in ${DIST_DIR#"$REPO_ROOT"/}"
    blank
    ok "The title is built: ${DIST_DIR#"$REPO_ROOT"/}/$TITLE_ID"
    blank
    wait_enter
}

# ---------------------------------------------------------------------------
# 5. Zip files and FTP

stage_data_tree() {  # the /data/sor folder, as symlinks, so zipping it copies nothing first
    local stage=$1
    mkdir -p "$stage/sor"
    ln -s "$DIST_DIR/data-sor/ai-code" "$stage/sor/ai-code"
    ln -s "$DIST_DIR/data-sor/python" "$stage/sor/python"
    ln -s "$SOUNDTRACK_DIR" "$stage/sor/soundtrack"
    ln -s "$ROM_DEST" "$stage/sor/SOR.bin"
}

make_zip() {  # make_zip ZIPFILE DIRECTORY FOLDER: zips FOLDER, which sits in DIRECTORY, following links
    local zipfile=$1 directory=$2 folder=$3
    rm -f "$zipfile"
    (cd "$directory" && zip -rq -X -n .flac "$zipfile" "$folder" -x '*.DS_Store' -x '*/__pycache__/*')
}

make_zip_files() {
    local stage="$TUI_LOG_DIR/stage"
    mkdir -p "$stage"
    stage_data_tree "$stage"
    ZIP_HOMEBREW=$OUTPUT_DIR/$ZIP_HOMEBREW_NAME
    ZIP_DATA=$OUTPUT_DIR/$ZIP_DATA_NAME
    run_task "Zipping the title ($ZIP_HOMEBREW_NAME)" make_zip "$ZIP_HOMEBREW" "$DIST_DIR" "$TITLE_ID" || exit 1
    run_task "Zipping the data folder ($ZIP_DATA_NAME)" make_zip "$ZIP_DATA" "$stage" sor || exit 1
    ZIPS_MADE=("$ZIP_HOMEBREW" "$ZIP_DATA")
    blank
    ok "$(human_size "$(wc -c <"$ZIP_HOMEBREW" | tr -d ' ')")  $ZIP_HOMEBREW_NAME"
    ok "$(human_size "$(wc -c <"$ZIP_DATA" | tr -d ' ')")  $ZIP_DATA_NAME"
}

urlencode_path() { printf '%s' "$1" | sed -e 's/%/%25/g' -e 's/ /%20/g' -e 's/#/%23/g' -e 's/?/%3F/g'; }

upload_list() {  # upload_list: "local|remote" per file, the program last
    local file root remote
    for root in "ai-code" "python"; do
        find "$DIST_DIR/data-sor/$root" -type f ! -name '.*' ! -path '*/__pycache__/*' | sort |
            while IFS= read -r file; do printf '%s|/data/sor/%s\n' "$file" "$root/${file#"$DIST_DIR/data-sor/$root/"}"; done
    done
    find "$SOUNDTRACK_DIR" -type f ! -name '.*' | sort |
        while IFS= read -r file; do printf '%s|/data/sor/soundtrack/%s\n' "$file" "${file#"$SOUNDTRACK_DIR/"}"; done
    printf '%s|/data/sor/SOR.bin\n' "$ROM_DEST"
    find "$DIST_DIR/$TITLE_ID" -type f ! -name '.*' ! -name eboot.bin | sort |
        while IFS= read -r file; do printf '%s|/data/homebrew/%s/%s\n' "$file" "$TITLE_ID" "${file#"$DIST_DIR/$TITLE_ID/"}"; done
    printf '%s|/data/homebrew/%s/eboot.bin\n' "$DIST_DIR/$TITLE_ID/eboot.bin" "$TITLE_ID"
}

ask_console_address() {
    local port
    while true; do
        ask_text "The console's IP address (for example 192.168.1.50)"
        FTP_HOST=$(printf '%s' "$REPLY_TEXT" | tr -d '[:space:]')
        case "$FTP_HOST" in
            '' | *[!A-Za-z0-9.:-]*) warn "That does not look like an address."; blank; continue ;;
        esac
        ask_text "FTP port (ENTER for $FTP_DEFAULT_PORT)"
        port=$(printf '%s' "$REPLY_TEXT" | tr -d '[:space:]')
        FTP_PORT=${port:-$FTP_DEFAULT_PORT}
        case "$FTP_PORT" in
            '' | *[!0-9]*) warn "A port is a number."; blank; continue ;;
        esac
        blank
        if run_task "Connecting to $FTP_HOST:$FTP_PORT" \
            curl -sS --connect-timeout 8 --max-time 15 --list-only "ftp://$FTP_HOST:$FTP_PORT/"; then
            return
        fi
        blank
        say "The console did not answer. Check that ftpsrv is running on it, that this computer is on the same network, and the address."
        blank
        menu_or_die "Try another address" "Quit"
        blank
    done
}

upload_files() {
    local list="$TUI_LOG_DIR/upload.list" total_files total_bytes=0 sent_bytes=0 index=0 local_file remote size
    upload_list >"$list"
    total_files=$(wc -l <"$list" | tr -d ' ')
    while IFS='|' read -r local_file remote; do
        size=$(wc -c <"$local_file" | tr -d ' ')
        total_bytes=$((total_bytes + size))
    done <"$list"

    blank
    say "Sending $total_files files ($(human_size "$total_bytes")). Close the game on the console first."
    blank
    tui_cursor_hide
    local attempt
    while IFS='|' read -r local_file remote; do
        index=$((index + 1))
        progress_bar "$sent_bytes" "$total_bytes" "$index/$total_files " "$remote"
        size=$(wc -c <"$local_file" | tr -d ' ')
        attempt=1
        until curl -sS --connect-timeout 15 --ftp-create-dirs -T "$local_file" \
            "ftp://$FTP_HOST:$FTP_PORT$(urlencode_path "$remote")" 2>"$TUI_LOG_DIR/ftp.err"; do
            if [ "$attempt" -ge 3 ]; then
                tui_cursor_show
                printf '\r\033[K'
                fail "Could not send $remote"
                sed 's/^/    /' "$TUI_LOG_DIR/ftp.err"
                die "The upload stopped. Run the wizard again: it sends everything again."
            fi
            attempt=$((attempt + 1))
            sleep 2
        done
        sent_bytes=$((sent_bytes + size))
    done <"$list"
    progress_bar "$total_bytes" "$total_bytes" "$total_files/$total_files " "files"
    tui_cursor_show
    printf '\n'
    blank
    ok "Everything is on the console."
}

step_deliver() {
    step_begin 5 "Getting the game to your PS5"
    say "How do you want the files?"
    blank
    menu "ZIP files|two ZIP files in this folder, to copy to the console yourself" \
        "Upload by FTP|the wizard sends the files to the console over your network" \
        "Both|make the ZIP files and upload"
    local choice=$MENU_CHOICE
    blank
    DELIVERED_ZIPS=0
    DELIVERED_FTP=0

    if [ "$choice" -eq 0 ] || [ "$choice" -eq 2 ]; then
        make_zip_files
        DELIVERED_ZIPS=1
        blank
    fi
    if [ "$choice" -eq 1 ] || [ "$choice" -eq 2 ]; then
        say "On the PS5, run an FTP server such as ftpsrv (anonymous login, port $FTP_DEFAULT_PORT by default). The files go to /data/homebrew and /data/sor."
        blank
        ask_console_address
        upload_files
        DELIVERED_FTP=1
        blank
    fi
    wait_enter
}

# ---------------------------------------------------------------------------
# 6. Clean up and finish

step_cleanup() {
    step_begin 6 "Cleaning up"
    local remove=()
    remove+=("The container image and build volume|about 5 GB and the compiled objects")
    [ "$HAD_GENERATED" -eq 0 ] && [ -e "$GENERATED_DIR" ] && remove+=("The generated C++|${GENERATED_DIR#"$REPO_ROOT"/}")
    [ "$HAD_DIST" -eq 0 ] && [ -e "$DIST_DIR" ] && remove+=("The built title|${DIST_DIR#"$REPO_ROOT"/}")
    [ "$HAD_SOUNDTRACK" -eq 0 ] && [ -e "$SOUNDTRACK_DIR" ] && remove+=("The rendered soundtrack|${SOUNDTRACK_DIR#"$REPO_ROOT"/}")
    [ "$HAD_ROM" -eq 0 ] && [ -f "$ROM_DEST" ] && remove+=("The copy of your ROM|${ROM_DEST#"$REPO_ROOT"/}")

    say "Everything the wizard made can be removed now. Your ZIP files and your own ROM file stay."
    blank
    local item
    for item in "${remove[@]}"; do
        printf '    %s-%s %s  %s%s%s\n' "$ACCENT" "$RST" "${item%%|*}" "$MUTED" "${item#*|}" "$RST"
    done
    blank
    menu "Clean up everything|free the disk space" "Keep it all|faster the next time"
    local choice=$MENU_CHOICE
    blank
    if [ "$choice" -eq 0 ]; then
        docker image rm -f "$IMAGE" >/dev/null 2>&1 && ok "Removed the container image"
        docker volume rm -f "$BUILD_VOLUME" >/dev/null 2>&1 && ok "Removed the build volume"
        [ "$HAD_GENERATED" -eq 0 ] && rm -rf "$GENERATED_DIR" && ok "Removed the generated C++"
        [ "$HAD_DIST" -eq 0 ] && rm -rf "$DIST_DIR" && ok "Removed the built title"
        [ "$HAD_SOUNDTRACK" -eq 0 ] && rm -rf "$SOUNDTRACK_DIR" && ok "Removed the rendered soundtrack"
        [ "$HAD_ROM" -eq 0 ] && rm -f "$ROM_DEST" && ok "Removed the copy of your ROM"
    else
        muted "Nothing removed."
    fi
    blank
}

wizard_finish() {
    local lines=""
    if [ "$DELIVERED_ZIPS" -eq 1 ]; then
        lines+="Your ZIP files are in: $OUTPUT_DIR"$'\n\n'
        lines+="1. $ZIP_HOMEBREW_NAME: unzip it into /data/homebrew on the console (or any folder ShadowMountPlus 1.7 beta 4 or newer scans). It holds the folder $TITLE_ID."$'\n\n'
        lines+="2. $ZIP_DATA_NAME: unzip it into /data on the console. It holds the folder sor: the AI, Python, the soundtrack and your ROM as SOR.bin."$'\n\n'
    fi
    if [ "$DELIVERED_FTP" -eq 1 ]; then
        lines+="The files are on the console: the title in /data/homebrew/$TITLE_ID and the data in /data/sor."$'\n\n'
    fi
    lines+="Mount the title with ShadowMountPlus and start Streets of Rage from the home screen."
    printf '%s\n' "$lines" | box "$OK" "All done"
    blank
}

wizard_main() {
    tui_init
    wizard_paths
    check_workspace
    step_docker
    step_rom
    step_soundtrack
    step_build
    step_deliver
    step_cleanup
    wizard_finish
}
