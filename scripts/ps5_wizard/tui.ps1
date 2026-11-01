# Screen and keyboard helpers of the PS5 build wizard (scripts/ps5_wizzard.ps1), dot-sourced by it.

# ---------------------------------------------------------------------------
# Screen

$script:Esc = [string][char]27
# On Windows, plain `curl` is an alias of Invoke-WebRequest: the program is curl.exe (in Windows 11 since 2018).
$script:Curl = $(if ($env:OS -eq 'Windows_NT') { 'curl.exe' } else { 'curl' })
$script:Finished = $false
$script:Failed = $false
$script:ChildProcess = $null
$script:KeepLogs = $false
$script:TaskCount = 0

function Initialize-Screen {
    if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) {
        [Console]::Error.WriteLine('This wizard is interactive: run it from a terminal.')
        exit 1
    }
    if ($env:OS -eq 'Windows_NT') {
        # Turn on ANSI colours in the old console host; Windows Terminal has them already.
        try {
            Add-Type -Namespace SorWizard -Name Vt -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern System.IntPtr GetStdHandle(int handle);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(System.IntPtr handle, out uint mode);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(System.IntPtr handle, uint mode);
'@
            $handle = [SorWizard.Vt]::GetStdHandle(-11)
            $mode = 0
            if ([SorWizard.Vt]::GetConsoleMode($handle, [ref]$mode)) {
                [void][SorWizard.Vt]::SetConsoleMode($handle, $mode -bor 4)
            }
        } catch { }
    }
    try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

    $width = 80
    try { $width = [Console]::WindowWidth } catch { }
    if ($width -lt 60) { $width = 60 }
    $script:Cols = $width
    $script:W = [Math]::Min($width, 78)

    $e = $script:Esc
    if ($env:NO_COLOR) {
        $script:Rst = ''; $script:Bold = ''; $script:Accent = ''; $script:Accent2 = ''
        $script:Okc = ''; $script:Warnc = ''; $script:Errc = ''; $script:Infoc = ''; $script:Muted = ''
    } else {
        $script:Rst = "$e[0m"; $script:Bold = "$e[1m"
        $script:Accent = "$e[38;5;203m"; $script:Accent2 = "$e[38;5;215m"
        $script:Okc = "$e[38;5;114m"; $script:Warnc = "$e[38;5;221m"; $script:Errc = "$e[38;5;203m"
        $script:Infoc = "$e[38;5;81m"; $script:Muted = "$e[38;5;245m"
    }

    # Windows Terminal and VS Code draw all of these; the old console host does not have the glyphs.
    if ($env:WT_SESSION -or $env:TERM_PROGRAM -or $env:OS -ne 'Windows_NT') {
        $script:G = @{
            H = [string][char]0x2500; V = [string][char]0x2502; TL = [string][char]0x256D; TR = [string][char]0x256E
            BL = [string][char]0x2570; BR = [string][char]0x256F; Done = [string][char]0x25CF; Now = [string][char]0x25C9
            Todo = [string][char]0x25CB; Ok = [string][char]0x2714; Fail = [string][char]0x2716; Warn = [string][char]0x25B2
            Info = [string][char]0x25CF; Arrow = [string][char]0x276F; BarOn = [string][char]0x2588; BarOff = [string][char]0x2591
            Sep = ([string][char]0x2500) * 2
        }
        $script:Spinner = @(0x280B, 0x2819, 0x2839, 0x2838, 0x283C, 0x2834, 0x2826, 0x2827, 0x2807, 0x280F | ForEach-Object { [string][char]$_ })
    } else {
        $script:G = @{
            H = '-'; V = '|'; TL = '+'; TR = '+'; BL = '+'; BR = '+'; Done = '*'; Now = '>'; Todo = '.'
            Ok = '+'; Fail = 'x'; Warn = '!'; Info = '*'; Arrow = '>'; BarOn = '#'; BarOff = '-'; Sep = '--'
        }
        $script:Spinner = @('|', '/', '-', '\')
    }

    $script:LogDir = Join-Path ([IO.Path]::GetTempPath()) ('sor-wizard-' + [IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
}

function Out-Raw([string]$text) { [Console]::Out.Write($text) }
function Out-Line([string]$text = '') { [Console]::Out.WriteLine($text) }
function Hide-Cursor { Out-Raw "$($script:Esc)[?25l" }
function Show-Cursor { Out-Raw "$($script:Esc)[?25h" }
function Clear-Screen2 { Out-Raw "$($script:Esc)[H$($script:Esc)[2J$($script:Esc)[3J" }
function Repeat-Text([string]$text, [int]$count) { if ($count -le 0) { return '' } return ($text * $count) }

function Write-Banner {
    $g = $script:G
    $line = Repeat-Text $g.H ($script:W - 2)
    $title = 'S T R E E T S   O F   R A G E'
    $sub = 'PlayStation 5 build wizard'
    Out-Line "$($script:Accent)$($g.TL)$line$($g.TR)$($script:Rst)"
    Out-Line "$($script:Accent)$($g.V)$($script:Rst)  $($script:Bold)$($script:Accent2)$title$($script:Rst)$(' ' * ($script:W - 4 - $title.Length))$($script:Accent)$($g.V)$($script:Rst)"
    Out-Line "$($script:Accent)$($g.V)$($script:Rst)  $($script:Muted)$sub$($script:Rst)$(' ' * ($script:W - 4 - $sub.Length))$($script:Accent)$($g.V)$($script:Rst)"
    Out-Line "$($script:Accent)$($g.BL)$line$($g.BR)$($script:Rst)"
    Out-Line
}

function Write-Stepper([int]$current) {
    $g = $script:G
    $parts = @()
    for ($i = 1; $i -le $StepNames.Count; $i++) {
        $name = $StepNames[$i - 1]
        if ($i -lt $current) { $parts += "$($script:Okc)$($g.Done)$($script:Rst) $($script:Muted)$name$($script:Rst)" }
        elseif ($i -eq $current) { $parts += "$($script:Accent)$($g.Now)$($script:Rst) $($script:Bold)$name$($script:Rst)" }
        else { $parts += "$($script:Muted)$($g.Todo) $name$($script:Rst)" }
    }
    Out-Line ($parts -join " $($script:Muted)$($g.Sep)$($script:Rst) ")
    Out-Line
}

function Start-Step([int]$number, [string]$title) {
    Clear-Screen2
    Write-Banner
    Write-Stepper $number
    Out-Line "$($script:Muted)Step $number of $($StepNames.Count)$($script:Rst)  $($script:Bold)$title$($script:Rst)"
    Out-Line "$($script:Muted)$(Repeat-Text $script:G.H $script:W)$($script:Rst)"
    Out-Line
}

function Get-WrappedLines([string]$text, [int]$width) {
    $lines = New-Object System.Collections.ArrayList
    foreach ($paragraph in ($text -split "`n")) {
        $current = ''
        foreach ($word in ($paragraph -split ' ')) {
            if ($current.Length -eq 0) { $current = $word }
            elseif (($current.Length + 1 + $word.Length) -le $width) { $current += ' ' + $word }
            else { [void]$lines.Add($current); $current = $word }
        }
        [void]$lines.Add($current)
    }
    return , @($lines)
}

function Say([string]$text) {
    foreach ($line in (Get-WrappedLines $text ($script:W - 2))) { Out-Line "  $line" }
}
function Blank { Out-Line }
function Say-Ok([string]$text) { Out-Line "  $($script:Okc)$($script:G.Ok)$($script:Rst) $text" }
function Say-Warn([string]$text) { Out-Line "  $($script:Warnc)$($script:G.Warn)$($script:Rst) $text" }
function Say-Fail([string]$text) { Out-Line "  $($script:Errc)$($script:G.Fail)$($script:Rst) $text" }
function Say-Muted([string]$text) { Out-Line "  $($script:Muted)$text$($script:Rst)" }

function Write-Box([string]$color, [string]$title, [string]$text) {
    $g = $script:G
    $inner = $script:W - 4
    $label = " $title "
    Out-Line "  $color$($g.TL)$($g.H)$($script:Rst)$($script:Bold)$label$($script:Rst)$color$(Repeat-Text $g.H ($script:W - 3 - $label.Length))$($g.TR)$($script:Rst)"
    foreach ($line in (Get-WrappedLines $text $inner)) {
        Out-Line "  $color$($g.V)$($script:Rst) $line$(' ' * [Math]::Max(0, $inner - $line.Length)) $color$($g.V)$($script:Rst)"
    }
    Out-Line "  $color$($g.BL)$(Repeat-Text $g.H ($script:W - 2))$($g.BR)$($script:Rst)"
}

function Format-Size([double]$bytes) {
    $units = @('B', 'KB', 'MB', 'GB')
    $i = 0
    while ($bytes -ge 1024 -and $i -lt 3) { $bytes /= 1024; $i++ }
    if ($i -eq 0) { return ('{0:0} {1}' -f $bytes, $units[$i]) }
    return ('{0:0.0} {1}' -f $bytes, $units[$i])
}

function Format-Elapsed([int]$seconds) { return ('{0:00}:{1:00}' -f [Math]::Floor($seconds / 60), ($seconds % 60)) }

# ---------------------------------------------------------------------------
# Input

# Show-Menu 'Label|detail', ...: arrows or j/k move, 1-9 jump, Enter chooses. Returns the index.
function Show-Menu([string[]]$Items) {
    $count = $Items.Count
    $labels = @(); $details = @()
    $width = 0
    foreach ($item in $Items) {
        $parts = $item.Split('|', 2)
        $labels += $parts[0]
        $details += $(if ($parts.Count -gt 1) { $parts[1] } else { '' })
        if ($parts[0].Length -gt $width) { $width = $parts[0].Length }
    }
    $selected = 0
    $draw = {
        for ($i = 0; $i -lt $count; $i++) {
            $room = [Math]::Max(0, $script:Cols - $width - 10)
            $detail = $details[$i]
            if ($detail.Length -gt $room) { $detail = $detail.Substring(0, $room) }
            Out-Raw "`r$($script:Esc)[K"
            if ($i -eq $selected) {
                Out-Raw "  $($script:Accent)$($script:G.Arrow)$($script:Rst) $($script:Bold)$($script:Accent2)$($labels[$i].PadRight($width))$($script:Rst)"
            } else {
                Out-Raw "    $($labels[$i].PadRight($width))"
            }
            if ($detail) { Out-Raw "  $($script:Muted)$detail$($script:Rst)" }
            Out-Line
        }
    }
    Hide-Cursor
    & $draw
    while ($true) {
        $key = [Console]::ReadKey($true)
        if ($key.Key -eq 'Enter') { break }
        elseif ($key.Key -eq 'UpArrow' -or $key.KeyChar -eq 'k') { $selected = ($selected + $count - 1) % $count }
        elseif ($key.Key -eq 'DownArrow' -or $key.KeyChar -eq 'j') { $selected = ($selected + 1) % $count }
        elseif ($key.KeyChar -ge '1' -and $key.KeyChar -le '9' -and ([int][string]$key.KeyChar) -le $count) { $selected = [int][string]$key.KeyChar - 1 }
        Out-Raw "$($script:Esc)[${count}A"
        & $draw
    }
    Show-Cursor
    Out-Line
    return $selected
}

function Show-MenuOrQuit([string[]]$Items) {
    $choice = Show-Menu $Items
    if ($choice -eq ($Items.Count - 1)) {
        Blank
        Say-Muted 'Stopped by you. Nothing else was changed.'
        $script:Finished = $true
        exit 0
    }
    return $choice
}

function Read-TextLine([string]$prompt) {
    Out-Line "  $($script:Muted)$prompt$($script:Rst)"
    Out-Raw "  $($script:Accent)$($script:G.Arrow)$($script:Rst) "
    $text = [Console]::ReadLine()
    if ($null -eq $text) { return '' }
    return $text
}

function Wait-Enter([string]$message = 'Press ENTER to continue') {
    Out-Raw "  $($script:Muted)$message$($script:Rst)"
    Hide-Cursor
    do { $key = [Console]::ReadKey($true) } until ($key.Key -eq 'Enter')
    Show-Cursor
    Out-Line
}

