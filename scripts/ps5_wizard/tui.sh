#!/bin/bash
# Terminal UI helpers for the PS5 build wizards (scripts/ps5_wizzard_*.sh). Source it, do not run it.
#
# Pure bash 3.2 (the one macOS ships) plus tools every macOS and Linux has: tput, fold, tr, sed.
# Everything interactive reads /dev/tty; everything drawn goes to stdout.

TUI_CHILD_PID=""
TUI_LOG_DIR=""
TUI_CURSOR_HIDDEN=0
TUI_ESC=$'\033'

tui_init() {
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        echo "This wizard is interactive: run it from a terminal." >&2
        exit 1
    fi
    COLS=$(tput cols 2>/dev/null || echo 80)
    [ "$COLS" -ge 60 ] 2>/dev/null || COLS=60
    W=$COLS
    [ "$W" -le 78 ] || W=78

    case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
        *UTF-8* | *utf-8* | *UTF8* | *utf8*)
            G_H='─' G_V='│' G_TL='╭' G_TR='╮' G_BL='╰' G_BR='╯'
            G_DONE='●' G_NOW='◉' G_TODO='○' G_OK='✔' G_FAIL='✖' G_WARN='▲' G_INFO='●' G_ARROW='❯'
            G_BAR_ON='█' G_BAR_OFF='░' G_SEP='──'
            SPINNER_FRAMES=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
            ;;
        *)
            G_H='-' G_V='|' G_TL='+' G_TR='+' G_BL='+' G_BR='+'
            G_DONE='*' G_NOW='>' G_TODO='.' G_OK='+' G_FAIL='x' G_WARN='!' G_INFO='*' G_ARROW='>'
            G_BAR_ON='#' G_BAR_OFF='-' G_SEP='--'
            SPINNER_FRAMES=('|' '/' '-' '\')
            ;;
    esac

    if [ -n "${NO_COLOR:-}" ] || [ "${TERM:-dumb}" = dumb ]; then
        RST='' BOLD='' DIM='' ACCENT='' ACCENT2='' OK='' WARN='' ERR='' INFO='' MUTED='' INVERT=''
    else
        RST=$'\033[0m' BOLD=$'\033[1m' DIM=$'\033[2m' INVERT=$'\033[7m'
        ACCENT=$'\033[38;5;203m' ACCENT2=$'\033[38;5;215m'
        OK=$'\033[38;5;114m' WARN=$'\033[38;5;221m' ERR=$'\033[38;5;203m'
        INFO=$'\033[38;5;81m' MUTED=$'\033[38;5;245m'
    fi

    TUI_LOG_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sor-wizard.XXXXXX")
    trap tui_on_exit EXIT
    trap tui_on_interrupt INT TERM
}

tui_cursor_hide() { printf '\033[?25l'; TUI_CURSOR_HIDDEN=1; }
tui_cursor_show() { printf '\033[?25h'; TUI_CURSOR_HIDDEN=0; }

tui_on_exit() {
    tui_cursor_show
    if [ "${TUI_KEEP_LOGS:-0}" != 1 ] && [ -n "$TUI_LOG_DIR" ]; then
        rm -rf "$TUI_LOG_DIR"
    fi
}

tui_on_interrupt() {
    if [ -n "$TUI_CHILD_PID" ]; then
        kill "$TUI_CHILD_PID" 2>/dev/null
    fi
    tui_cursor_show
    printf '\r\033[K\n%s%s%s Cancelled. Nothing else was changed.\n' "$WARN" "$G_WARN" "$RST"
    exit 130
}

# ---------------------------------------------------------------------------
# Layout

rep() {  # rep STRING COUNT
    local out="" i
    for ((i = 0; i < $2; i++)); do out+=$1; done
    printf '%s' "$out"
}

screen_clear() { printf '\033[H\033[2J\033[3J'; }

banner() {
    local line
    line=$(rep "$G_H" $((W - 2)))
    printf '%s%s%s%s%s\n' "$ACCENT" "$G_TL" "$line" "$G_TR" "$RST"
    printf '%s%s%s  %sS T R E E T S   O F   R A G E%s%*s%s%s%s\n' \
        "$ACCENT" "$G_V" "$RST" "$BOLD$ACCENT2" "$RST" $((W - 33)) "" "$ACCENT" "$G_V" "$RST"
    printf '%s%s%s  %sPlayStation 5 build wizard%s%*s%s%s%s\n' \
        "$ACCENT" "$G_V" "$RST" "$MUTED" "$RST" $((W - 30)) "" "$ACCENT" "$G_V" "$RST"
    printf '%s%s%s%s%s\n\n' "$ACCENT" "$G_BL" "$line" "$G_BR" "$RST"
}

stepper() {  # stepper CURRENT (1-based); uses STEP_NAMES
    local current=$1 i=1 name out=""
    for name in "${STEP_NAMES[@]}"; do
        if [ "$i" -lt "$current" ]; then
            out+="${OK}${G_DONE}${RST} ${MUTED}${name}${RST}"
        elif [ "$i" -eq "$current" ]; then
            out+="${ACCENT}${G_NOW}${RST} ${BOLD}${name}${RST}"
        else
            out+="${MUTED}${G_TODO} ${name}${RST}"
        fi
        [ "$i" -lt "${#STEP_NAMES[@]}" ] && out+=" ${MUTED}${G_SEP}${RST} "
        i=$((i + 1))
    done
    printf '%s\n\n' "$out"
}

step_begin() {  # step_begin NUMBER TITLE
    screen_clear
    banner
    stepper "$1"
    printf '%sStep %s of %s%s  %s%s%s\n' "$MUTED" "$1" "${#STEP_NAMES[@]}" "$RST" "$BOLD" "$2" "$RST"
    printf '%s%s%s\n\n' "$MUTED" "$(rep "$G_H" $((W)))" "$RST"
}

say() {  # say TEXT...: wrapped, indented two columns
    local text="$*"
    printf '%s\n' "$text" | fold -s -w $((W - 2)) | sed 's/^/  /'
}

blank() { printf '\n'; }

ok()   { printf '  %s%s%s %s\n' "$OK" "$G_OK" "$RST" "$*"; }
warn() { printf '  %s%s%s %s\n' "$WARN" "$G_WARN" "$RST" "$*"; }
fail() { printf '  %s%s%s %s\n' "$ERR" "$G_FAIL" "$RST" "$*"; }
info() { printf '  %s%s%s %s\n' "$INFO" "$G_INFO" "$RST" "$*"; }
muted() { printf '  %s%s%s\n' "$MUTED" "$*" "$RST"; }

box() {  # box COLOR TITLE < plain-text lines
    local color=$1 title=$2 inner=$((W - 4)) line fill
    local label=" $title "
    fill=$(rep "$G_H" $((W - 3 - ${#label})))
    printf '%s%s%s%s%s%s%s\n' "$color" "$G_TL" "$G_H" "$RST$BOLD" "$label" "$RST$color" "$fill$G_TR$RST"
    fold -s -w "$inner" | while IFS= read -r line; do
        printf '%s%s%s %s%*s %s%s%s\n' "$color" "$G_V" "$RST" "$line" $((inner - ${#line})) "" "$color" "$G_V" "$RST"
    done
    printf '%s%s%s%s%s\n' "$color" "$G_BL" "$(rep "$G_H" $((W - 2)))" "$G_BR" "$RST"
}

human_size() {  # human_size BYTES
    awk -v b="$1" 'BEGIN {
        split("B KB MB GB", u, " "); i = 1
        while (b >= 1024 && i < 4) { b /= 1024; i++ }
        printf (i == 1 ? "%d %s" : "%.1f %s"), b, u[i]
    }'
}

format_elapsed() {  # format_elapsed SECONDS
    printf '%02d:%02d' $(($1 / 60)) $(($1 % 60))
}

# ---------------------------------------------------------------------------
# Input

# menu "Label|detail" ...: arrows or j/k move, 1-9 jump, Enter chooses. Sets MENU_CHOICE (0-based).
menu() {
    local items=("$@") count=$# selected=0 key rest i label detail
    local width=0
    for i in "${items[@]}"; do
        label=${i%%|*}
        [ ${#label} -gt $width ] && width=${#label}
    done

    menu_draw() {
        for ((i = 0; i < count; i++)); do
            label=${items[$i]%%|*}
            detail=""
            case "${items[$i]}" in *"|"*) detail=${items[$i]#*|} ;; esac
            printf '\r\033[K'
            if [ "$i" -eq "$selected" ]; then
                printf '  %s%s%s %s%s%-*s%s' "$ACCENT" "$G_ARROW" "$RST" "$BOLD" "$ACCENT2" "$width" "$label" "$RST"
                [ -n "$detail" ] && printf '  %s%s%s' "$MUTED" "$detail" "$RST"
            else
                printf '    %-*s' "$width" "$label"
                [ -n "$detail" ] && printf '  %s%s%s' "$MUTED" "$detail" "$RST"
            fi
            printf '\n'
        done
    }

    tui_cursor_hide
    menu_draw
    while true; do
        IFS= read -rsn1 key </dev/tty
        case "$key" in
            $'\033')
                rest=""
                read -rsn2 -t 1 rest </dev/tty
                case "$rest" in
                    '[A') selected=$(((selected + count - 1) % count)) ;;
                    '[B') selected=$(((selected + 1) % count)) ;;
                esac
                ;;
            k) selected=$(((selected + count - 1) % count)) ;;
            j) selected=$(((selected + 1) % count)) ;;
            [1-9])
                [ "$key" -le "$count" ] && selected=$((key - 1))
                ;;
            '') break ;;
        esac
        printf '\033[%dA' "$count"
        menu_draw
    done
    tui_cursor_show
    MENU_CHOICE=$selected
    printf '\n'
}

# ask_text PROMPT: a line with arrow-key editing, drag-and-drop friendly. Sets REPLY_TEXT.
ask_text() {
    local prompt=$'\001'"${ACCENT}"$'\002'"  ${G_ARROW} "$'\001'"${RST}"$'\002'
    REPLY_TEXT=""
    printf '  %s%s%s\n' "$MUTED" "$1" "$RST"
    IFS= read -e -r -p "$prompt" REPLY_TEXT </dev/tty
}

# wait_enter [MESSAGE]
wait_enter() {
    local key
    printf '  %s%s%s' "$MUTED" "${1:-Press ENTER to continue}" "$RST"
    tui_cursor_hide
    IFS= read -rsn1 key </dev/tty
    tui_cursor_show
    printf '\n'
}

# ---------------------------------------------------------------------------
# Long-running work

# run_task MESSAGE COMMAND...: spinner with elapsed time and the last output line; the output goes
# to a log. Returns the command's status; on failure prints the log's tail.
run_task() {
    local message=$1
    shift
    TUI_TASK_COUNT=$(( ${TUI_TASK_COUNT:-0} + 1 ))
    local log="$TUI_LOG_DIR/task-$TUI_TASK_COUNT.log"
    local start=$SECONDS frame=0 tick=0 last="" status elapsed room
    TUI_LAST_LOG="$log"

    "$@" >"$log" 2>&1 </dev/null &
    TUI_CHILD_PID=$!
    tui_cursor_hide
    while kill -0 "$TUI_CHILD_PID" 2>/dev/null; do
        if [ $((tick % 5)) -eq 0 ]; then
            last=$(tail -c 600 "$log" 2>/dev/null | tr '\r' '\n' | sed "s/$TUI_ESC\\[[0-9;?]*[A-Za-z]//g" | grep -v '^[[:space:]]*$' | tail -n 1)
        fi
        elapsed=$((SECONDS - start))
        room=$((COLS - ${#message} - 14))
        [ "$room" -gt 0 ] || room=0
        printf '\r\033[K  %s%s%s %s %s%s%s' "$ACCENT" "${SPINNER_FRAMES[$((frame % ${#SPINNER_FRAMES[@]}))]}" "$RST" \
            "$message" "$MUTED" "$(format_elapsed "$elapsed")" "$RST"
        if [ "$room" -gt 8 ]; then
            printf '  %s%s%s' "$DIM$MUTED" "${last:0:$room}" "$RST"
        fi
        frame=$((frame + 1))
        tick=$((tick + 1))
        sleep 0.1
    done
    wait "$TUI_CHILD_PID"
    status=$?
    TUI_CHILD_PID=""
    tui_cursor_show
    elapsed=$((SECONDS - start))
    printf '\r\033[K'
    if [ "$status" -eq 0 ]; then
        printf '  %s%s%s %s %s%s%s\n' "$OK" "$G_OK" "$RST" "$message" "$MUTED" "$(format_elapsed "$elapsed")" "$RST"
    else
        printf '  %s%s%s %s %s(failed after %s)%s\n' "$ERR" "$G_FAIL" "$RST" "$message" "$MUTED" "$(format_elapsed "$elapsed")" "$RST"
        blank
        tail -n 25 "$log" | sed 's/^/    /'
        blank
        TUI_KEEP_LOGS=1
        muted "Full log: $log"
    fi
    return "$status"
}

# progress_bar DONE TOTAL PREFIX LABEL: redraws one line; a long LABEL loses its start.
progress_bar() {
    local done_count=$1 total=$2 prefix=$3 label=$4 width=28 filled percent room
    [ "$total" -gt 0 ] || total=1
    percent=$((done_count * 100 / total))
    filled=$((done_count * width / total))
    room=$((COLS - width - 14 - ${#prefix}))
    if [ "$room" -lt 1 ]; then
        label=""
    elif [ ${#label} -gt "$room" ]; then
        label=${label: -$room}
    fi
    printf '\r\033[K  %s%s%s%s%s %3d%%  %s%s %s%s' \
        "$ACCENT" "$(rep "$G_BAR_ON" "$filled")" "$MUTED" "$(rep "$G_BAR_OFF" $((width - filled)))" "$RST" \
        "$percent" "$RST" "$prefix" "$MUTED$label" "$RST"
}
