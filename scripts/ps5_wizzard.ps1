# Build Streets of Rage for the PlayStation 5 on Windows 11, step by step, with nothing to install
# but a container engine (Docker Desktop or Podman Desktop). Run it from a terminal:
#
#   powershell -ExecutionPolicy Bypass -File scripts\ps5_wizzard.ps1      (or scripts\ps5_wizzard.cmd)
#
# The ZIP files it makes go to the folder you run it from. It is the same wizard as
# scripts/ps5_wizzard.sh (macOS and Linux), and runs on Windows PowerShell 5.1, the one Windows 11
# ships, as well as on PowerShell 7. This file is plain ASCII on purpose: 5.1 reads a file without
# a byte-order mark as ANSI.

$script:ScriptsDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$StepNames = @('Docker', 'ROM', 'Soundtrack', 'Build', 'Deliver', 'Clean up')

$Image = 'sor-ps5-toolchain'
$BuildVolume = 'sor-ps5-build'
$TitleId = 'PPSA99872'
$RomSha256 = '95d7efb98e97f4ffffe68257aef9a855034a36a41b86cf9d332d129f30cb2d4b'
$RomSize = 524288
$FtpDefaultPort = 2121
$ZipHomebrewName = 'StreetsOfRage-PS5-homebrew.zip'
$ZipDataName = 'StreetsOfRage-PS5-data.zip'

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

# ---------------------------------------------------------------------------
# Long-running work

function Get-FileTail([string]$path, [int]$bytes = 800) {
    try {
        $stream = [IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        try {
            $start = [Math]::Max(0, $stream.Length - $bytes)
            [void]$stream.Seek($start, 'Begin')
            $buffer = New-Object byte[] ($stream.Length - $start)
            [void]$stream.Read($buffer, 0, $buffer.Length)
            return [Text.Encoding]::UTF8.GetString($buffer)
        } finally { $stream.Dispose() }
    } catch { return '' }
}

function Get-LastLine([string[]]$paths) {
    $best = ''
    $bestTime = [datetime]::MinValue
    foreach ($path in $paths) {
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $time = (Get-Item -LiteralPath $path).LastWriteTime
        $tail = Get-FileTail $path
        $lines = @(($tail -replace "`r", "`n") -split "`n" | ForEach-Object { ($_ -replace "$([char]27)\[[0-9;?]*[A-Za-z]", '').Trim() } | Where-Object { $_ })
        if ($lines.Count -gt 0 -and $time -ge $bestTime) { $best = $lines[-1]; $bestTime = $time }
    }
    return $best
}

function ConvertTo-ArgumentString([string[]]$Arguments) {
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -eq '' -or $argument -match '[\s"]') {
            $escaped = $argument -replace '(\\*)"', '$1$1\"'
            $escaped = $escaped -replace '(\\+)$', '$1$1'
            '"' + $escaped + '"'
        } else { $argument }
    }
    return ($quoted -join ' ')
}

# Wait-WithSpinner: draws the spinner until $isRunning says stop; returns the seconds taken.
function Wait-WithSpinner([string]$message, [scriptblock]$isRunning, [string[]]$logFiles) {
    $start = Get-Date
    $frame = 0
    $last = ''
    Hide-Cursor
    while (& $isRunning) {
        if ($frame % 5 -eq 0 -and $logFiles) { $last = Get-LastLine $logFiles }
        $elapsed = [int]((Get-Date) - $start).TotalSeconds
        $room = $script:Cols - $message.Length - 14
        $spin = $script:Spinner[$frame % $script:Spinner.Count]
        Out-Raw "`r$($script:Esc)[K  $($script:Accent)$spin$($script:Rst) $message $($script:Muted)$(Format-Elapsed $elapsed)$($script:Rst)"
        if ($room -gt 8 -and $last) {
            if ($last.Length -gt $room) { $last = $last.Substring(0, $room) }
            Out-Raw "  $($script:Muted)$last$($script:Rst)"
        }
        $frame++
        Start-Sleep -Milliseconds 100
    }
    Show-Cursor
    Out-Raw "`r$($script:Esc)[K"
    return [int]((Get-Date) - $start).TotalSeconds
}

function Write-TaskResult([string]$message, [bool]$success, [int]$elapsed) {
    if ($success) {
        Out-Line "  $($script:Okc)$($script:G.Ok)$($script:Rst) $message $($script:Muted)$(Format-Elapsed $elapsed)$($script:Rst)"
    } else {
        Out-Line "  $($script:Errc)$($script:G.Fail)$($script:Rst) $message $($script:Muted)(failed after $(Format-Elapsed $elapsed))$($script:Rst)"
    }
}

# Invoke-Task: runs a program in the background with a spinner. Returns $true when it exits with 0.
function Invoke-Task([string]$Message, [string]$File, [string[]]$Arguments, [string]$StdinFile = '') {
    $script:TaskCount++
    $out = Join-Path $script:LogDir "task-$($script:TaskCount).out.log"
    $err = Join-Path $script:LogDir "task-$($script:TaskCount).err.log"
    $parameters = @{
        FilePath = $File; ArgumentList = (ConvertTo-ArgumentString $Arguments); NoNewWindow = $true; PassThru = $true
        RedirectStandardOutput = $out; RedirectStandardError = $err
    }
    if ($StdinFile) { $parameters.RedirectStandardInput = $StdinFile }
    $process = Start-Process @parameters
    $script:ChildProcess = $process
    $null = $process.Handle   # keeps the exit code readable
    $elapsed = Wait-WithSpinner $Message { -not $process.HasExited } @($out, $err)
    $process.WaitForExit()
    $script:ChildProcess = $null
    $success = ($process.ExitCode -eq 0)
    Write-TaskResult $Message $success $elapsed
    if (-not $success) {
        Blank
        $errLines = @(Get-Content -LiteralPath $err -Tail 25 -ErrorAction SilentlyContinue)
        $outLines = @(Get-Content -LiteralPath $out -Tail 25 -ErrorAction SilentlyContinue)
        $shown = if ($errLines.Count -ge 8) { $errLines } else { $outLines + $errLines }
        foreach ($line in ($shown | Select-Object -Last 25)) { Out-Line "    $line" }
        Blank
        $script:KeepLogs = $true
        Say-Muted "Full log: $err"
    }
    return $success
}

# Invoke-JobTask: the same for a script block that runs in a background job.
function Invoke-JobTask([string]$Message, [scriptblock]$Script, [object[]]$ArgumentList) {
    $job = Start-Job -ScriptBlock $Script -ArgumentList $ArgumentList
    $elapsed = Wait-WithSpinner $Message { $job.State -eq 'Running' -or $job.State -eq 'NotStarted' } @()
    $result = Receive-Job -Job $job -ErrorAction SilentlyContinue -ErrorVariable jobErrors
    $success = ($job.State -eq 'Completed') -and (-not $jobErrors)
    Remove-Job -Job $job -Force
    Write-TaskResult $Message $success $elapsed
    if (-not $success) {
        Blank
        foreach ($e in $jobErrors) { Out-Line "    $e" }
        Blank
    }
    return $success
}

function Write-Progress2([double]$done, [double]$total, [string]$prefix, [string]$label) {
    $width = 28
    if ($total -le 0) { $total = 1 }
    $percent = [int]($done * 100 / $total)
    $filled = [int]($done * $width / $total)
    $room = $script:Cols - $width - 14 - $prefix.Length
    if ($room -lt 1) { $label = '' } elseif ($label.Length -gt $room) { $label = $label.Substring($label.Length - $room) }
    $shown = "$percent".PadLeft(3)
    Out-Raw "`r$($script:Esc)[K  $($script:Accent)$(Repeat-Text $script:G.BarOn $filled)$($script:Muted)$(Repeat-Text $script:G.BarOff ($width - $filled))$($script:Rst) $shown%  $prefix$($script:Muted)$label$($script:Rst)"
}

# ---------------------------------------------------------------------------
# Paths and the container engine

# Join-Path keeps the slashes it is given; the comparisons and the trimming below need one kind.
function Join-Normal([string]$base, [string]$child) { return [IO.Path]::GetFullPath((Join-Path $base $child)) }

function Initialize-Paths {
    $script:RepoRoot = (Resolve-Path (Join-Path $script:ScriptsDir '..')).ProviderPath
    $script:SorDir = Join-Normal $script:RepoRoot 'StreetsOfRageRecompilation'
    $script:DockerContext = Join-Normal $script:SorDir 'prospero/docker'
    $script:RomDest = Join-Normal $script:SorDir 'rom/SOR.bin'
    $script:SoundtrackDir = Join-Normal $script:SorDir 'rom/soundtrack'
    $script:GeneratedDir = Join-Normal $script:SorDir 'generated'
    $script:DistDir = Join-Normal $script:SorDir 'dist-ps5'
    $here = (Get-Location).ProviderPath
    # Started by a double click, the current folder is scripts\: put the ZIP files in the project folder.
    if ($here.TrimEnd('\', '/') -eq $script:ScriptsDir.TrimEnd('\', '/')) { $here = $script:RepoRoot }
    $script:OutputDir = $here

    $script:HadRom = Test-Path -LiteralPath $script:RomDest
    $script:HadSoundtrack = Test-Path -LiteralPath $script:SoundtrackDir
    $script:HadGenerated = Test-Path -LiteralPath $script:GeneratedDir
    $script:HadDist = Test-Path -LiteralPath $script:DistDir
}

function Get-RelativeToRepo([string]$path) {
    return $path.Substring($script:RepoRoot.Length).TrimStart('\', '/')
}

function Get-RunArguments([string[]]$Command, [switch]$Interactive) {
    $arguments = @('run', '--rm')
    if ($Interactive) { $arguments += '-i' }
    $arguments += @('-v', "$($script:RepoRoot):/workspace", '-v', "${BuildVolume}:/build", $Image)
    return $arguments + $Command
}

function Invoke-EngineTask([string]$Message, [string[]]$Command, [string]$StdinFile = '') {
    # A name, so that Ctrl-C can remove the container: killing the client leaves it running.
    $script:RunningContainer = 'sor-wizard-' + [IO.Path]::GetRandomFileName().Replace('.', '')
    $arguments = Get-RunArguments $Command -Interactive:([bool]$StdinFile)
    $arguments = @('run', '--name', $script:RunningContainer) + $arguments[1..($arguments.Count - 1)]
    $result = Invoke-Task $Message $script:EnginePath $arguments $StdinFile
    $script:RunningContainer = $null
    return $result
}

function Stop-Wizard([string]$message) {
    Blank
    Say-Fail $message
    Blank
    $script:Failed = $true
    exit 1
}

function Test-Engine([string]$name) {
    $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { return $null }
    return $command
}

function Test-EngineRunning([string]$path) {
    & $path info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Test-Workspace {
    foreach ($tool in @($script:Curl)) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            Clear-Screen2; Write-Banner
            Say-Fail "$tool was not found. It comes with Windows 11: this installation looks damaged."
            Blank
            $script:Failed = $true
            exit 1
        }
    }
    $missing = ''
    if (-not (Test-Path -LiteralPath (Join-Path $script:DockerContext 'Dockerfile'))) { $missing = 'StreetsOfRageRecompilation\prospero\docker\Dockerfile' }
    if (-not (Test-Path -LiteralPath (Join-Path $script:RepoRoot 'RageDecompiler/tools/__main__.py'))) { $missing = 'RageDecompiler\tools' }
    if (-not (Test-Path -LiteralPath (Join-Path $script:RepoRoot 'MegaDriveEnvironment/CMakeLists.txt'))) { $missing = 'MegaDriveEnvironment' }
    if ($missing) {
        Clear-Screen2; Write-Banner
        Say-Fail "This copy of the project is incomplete: $missing is missing."
        Blank
        Say 'Fetch the submodules, and use the branch that has the PS5 port (prospero):'
        Blank
        Say-Muted 'git submodule update --init --recursive'
        Blank
        $script:Failed = $true
        exit 1
    }
    try {
        $probe = Join-Path $script:OutputDir ('.sor-wizard-' + [IO.Path]::GetRandomFileName())
        New-Item -ItemType File -Path $probe -ErrorAction Stop | Out-Null
        Remove-Item -LiteralPath $probe -Force
    } catch {
        Stop-Wizard "The current folder is not writable, and the ZIP files go there: $($script:OutputDir)"
    }
}

# ---------------------------------------------------------------------------
# 1. Container engine

function Step-Docker {
    Start-Step 1 'Container engine'
    Say 'The whole build runs inside a container, so the only thing to install on this computer is a container engine.'
    Blank

    $options = @(
        @{ Name = 'Docker Desktop'; Url = 'https://www.docker.com/products/docker-desktop/'; Note = 'Free, with paid plans. Uses WSL 2, which it offers to set up.' },
        @{ Name = 'Podman Desktop'; Url = 'https://podman-desktop.io/'; Note = 'Free.' }
    )
    while ($true) {
        $docker = Test-Engine 'docker'
        $podman = Test-Engine 'podman'
        if (-not $docker -and -not $podman) {
            Say-Warn 'No container engine was found (no docker or podman command).'
            Blank
            Say 'Install one of these (either works), then open it once so it can finish its setup:'
            Blank
            foreach ($option in $options) {
                Out-Line "    $($script:Bold)$($option.Name)$($script:Rst)  $($option.Note)"
                Out-Line "    $($script:Infoc)$($option.Url)$($script:Rst)"
                Blank
            }
            $items = @($options | ForEach-Object { "Open the $($_.Name) page" }) + @('I installed one: check again', 'Quit')
            $choice = Show-MenuOrQuit $items
            if ($choice -lt $options.Count) { Start-Process $options[$choice].Url }
            Start-Step 1 'Container engine'
            continue
        }
        $running = $null
        foreach ($candidate in @($docker, $podman)) {
            if ($candidate -and (Test-EngineRunning $candidate.Source)) { $running = $candidate; break }
        }
        if (-not $running) {
            Say-Warn 'A container engine is installed, but it is not running.'
            Blank
            Say 'Open Docker Desktop and wait until it says the engine is running. With Podman Desktop, start the Podman machine (in Resources).'
            Blank
            [void](Show-MenuOrQuit @('Check again', 'Quit'))
            Start-Step 1 'Container engine'
            continue
        }
        $script:EnginePath = $running.Source
        $version = (& $script:EnginePath --version 2>$null | Select-Object -First 1)
        Say-Ok "Container engine ready: $version"
        break
    }

    try {
        $free = (Get-Item -LiteralPath $script:RepoRoot).PSDrive.Free
        if ($free -and $free -lt 12GB) { Say-Warn "Only $(Format-Size $free) free here; the build needs about 12 GB." }
    } catch { }
    Blank
    Wait-Enter
}

# ---------------------------------------------------------------------------
# 2. ROM

function ConvertTo-CleanPath([string]$path) {
    $path = $path.Trim()
    if ($path.StartsWith('& ')) { $path = $path.Substring(2).Trim() }
    if ($path.Length -ge 2 -and (($path.StartsWith('"') -and $path.EndsWith('"')) -or ($path.StartsWith("'") -and $path.EndsWith("'")))) {
        $path = $path.Substring(1, $path.Length - 2)
    }
    if ($path -eq '~') { return $HOME }
    if ($path.StartsWith('~/') -or $path.StartsWith('~\')) { return (Join-Path $HOME $path.Substring(2)) }
    return $path
}

# Get-RomProblem: the lines saying why the file is not usable, or nothing when it is.
function Get-RomProblem([string]$file) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return @("That is not a file: $file") }
    $extension = [IO.Path]::GetExtension($file).TrimStart('.').ToLowerInvariant()
    if ($extension -eq 'smd') { return @('SMD files are not supported. Use the raw dump (.bin, .md or .gen).') }
    if (@('bin', 'md', 'gen') -notcontains $extension) { return @("A ROM file ends in .bin, .md or .gen (this one ends in .$extension).") }
    $size = (Get-Item -LiteralPath $file).Length
    $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $RomSha256) {
        $lines = @('This is not the right ROM. It must be the Mega Drive / Genesis JUE Rev. A dump.', "Its SHA-256: $hash", "Expected: $RomSha256")
        if ($size -eq ($RomSize + 512)) { $lines += 'It is 512 bytes longer than a raw dump: it looks like an SMD file, which is not supported.' }
        elseif ($size -ne $RomSize) { $lines += "Its size is $size bytes; the raw dump is $RomSize." }
        return $lines
    }
    return @()
}

function Select-RomFile {
    # The file dialog needs a single-threaded apartment; Windows PowerShell 5.1 starts in a multithreaded one.
    if ($env:OS -ne 'Windows_NT') { return '' }
    $command = '$d = New-Object System.Windows.Forms.OpenFileDialog; $d.Title = ''Choose your Streets of Rage ROM (Mega Drive / Genesis, JUE Rev. A)''; ' +
        '$d.Filter = ''Mega Drive ROM (*.bin;*.md;*.gen)|*.bin;*.md;*.gen|All files (*.*)|*.*''; if ($d.ShowDialog() -eq ''OK'') { $d.FileName }'
    $shell = (Get-Process -Id $PID).Path
    $result = & $shell -NoProfile -STA -Command "Add-Type -AssemblyName System.Windows.Forms; $command" 2>$null
    return ($result | Select-Object -First 1)
}

function Step-Rom {
    Start-Step 2 'Your Streets of Rage ROM'
    Say 'The game is built from your own copy of the original Mega Drive / Genesis game: the JUE Rev. A ROM of Streets of Rage (.bin, .md or .gen, the raw dump; .smd is not supported). It never leaves this computer, except in the files you choose to send to your console.'
    Blank

    if ((Test-Path -LiteralPath $script:RomDest) -and (@(Get-RomProblem $script:RomDest).Count -eq 0)) {
        Say-Ok "A verified ROM is already in place: $(Get-RelativeToRepo $script:RomDest)"
        Blank
        $choice = Show-Menu @('Use it|keep going', 'Choose another ROM file')
        if ($choice -eq 0) { return }
        Blank
    }

    while ($true) {
        Say 'Drag the ROM file onto this window and press ENTER, or type its path.'
        Say 'Press ENTER on an empty line to pick it in a file dialog.'
        Blank
        $candidate = ConvertTo-CleanPath (Read-TextLine 'ROM file')
        if (-not $candidate) {
            $candidate = Select-RomFile
            if (-not $candidate) {
                Blank
                Say-Warn 'No file was chosen. If no dialog opened, type or drag the path instead.'
                Blank
                continue
            }
        }
        Blank
        $problem = @(Get-RomProblem $candidate)
        if ($problem.Count -eq 0) { break }
        Write-Box $script:Errc 'Not usable' ($problem -join "`n")
        Blank
    }

    New-Item -ItemType Directory -Path (Split-Path -Parent $script:RomDest) -Force | Out-Null
    if ((Resolve-Path -LiteralPath $candidate).ProviderPath -ne $script:RomDest) {
        Copy-Item -LiteralPath $candidate -Destination $script:RomDest -Force
    }
    Say-Ok "JUE Rev. A verified (SHA-256 $($RomSha256.Substring(0, 12))...)"
    Say-Ok "Copied to $(Get-RelativeToRepo $script:RomDest)"
    Blank
    Wait-Enter
}

# ---------------------------------------------------------------------------
# 3. Toolchain image and soundtrack

# Git on Windows usually checks files out with CRLF line endings, which the shell scripts and the
# patch of the PS5 build cannot take inside a Linux container. Returns how many files it changed.
function ConvertTo-LineFeeds {
    $root = Join-Path $script:SorDir 'prospero'
    $changed = 0
    $files = Get-ChildItem -LiteralPath $root -Recurse -File -Force | Where-Object {
        $_.Extension -in @('.sh', '.site', '.patch') -or $_.Name -eq 'Dockerfile'
    }
    foreach ($file in $files) {
        $bytes = [IO.File]::ReadAllBytes($file.FullName)
        if ([Array]::IndexOf($bytes, [byte]13) -lt 0) { continue }
        $clean = [System.Collections.Generic.List[byte]]::new($bytes.Length)
        for ($i = 0; $i -lt $bytes.Length; $i++) {
            if ($bytes[$i] -eq 13 -and ($i + 1) -lt $bytes.Length -and $bytes[$i + 1] -eq 10) { continue }
            $clean.Add($bytes[$i])
        }
        [IO.File]::WriteAllBytes($file.FullName, $clean.ToArray())
        $changed++
    }
    return $changed
}

function Initialize-Image {
    $converted = ConvertTo-LineFeeds
    if ($converted -gt 0) {
        Say-Ok "Set $converted build files to Unix line endings (Git on Windows had changed them)"
    }
    $null = & $script:EnginePath image inspect $Image 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Box $script:Infoc 'First time on this computer' 'The PS5 toolchain is built once into a container image: about 5 GB, and it can take a good while. Later runs reuse it.'
        Blank
    }
    $env:BUILDKIT_PROGRESS = 'plain'
    $env:DOCKER_BUILDKIT = '1'
    if (-not (Invoke-Task 'Preparing the toolchain image' $script:EnginePath @('build', '-t', $Image, $script:DockerContext))) { $script:Failed = $true; exit 1 }
    if (-not (Invoke-EngineTask 'Checking the toolchain' @('bash', '/opt/ps5/check-toolchain.sh'))) { $script:Failed = $true; exit 1 }
}

$RenderSoundtrackScript = @'
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
'@

function Step-Soundtrack {
    Start-Step 3 'Pre-rendering the soundtrack'
    Say "The music, sound effects and voices are rendered from your ROM into FLAC files, because the console's real-time sound is not good enough. This is done inside the container."
    Blank
    Initialize-Image

    $render = $true
    if (Test-Path -LiteralPath (Join-Path $script:SoundtrackDir 'manifest.tsv')) {
        Blank
        Say-Ok "A soundtrack is already rendered: $(Get-RelativeToRepo $script:SoundtrackDir)"
        Blank
        if ((Show-Menu @('Keep it', 'Render it again')) -eq 0) { $render = $false }
        Blank
    }
    if ($render) {
        Blank
        # The script goes in on standard input: no quoting to get wrong, whichever PowerShell this is.
        $scriptFile = Join-Path $script:LogDir 'render-soundtrack.sh'
        [IO.File]::WriteAllText($scriptFile, ($RenderSoundtrackScript -replace "`r`n", "`n"), (New-Object System.Text.UTF8Encoding($false)))
        if (-not (Invoke-EngineTask 'Rendering the soundtrack (about 4 minutes, 265 MB)' @('bash', '-s') $scriptFile)) { $script:Failed = $true; exit 1 }
        if (-not (Test-Path -LiteralPath (Join-Path $script:SoundtrackDir 'manifest.tsv'))) {
            Stop-Wizard "The soundtrack folder came out empty: $($script:SoundtrackDir)"
        }
    }
    Blank
    Wait-Enter
}

# ---------------------------------------------------------------------------
# 4. Generate and compile

function Step-Build {
    Start-Step 4 'Compiling the title for the PS5'
    Say 'Your ROM is translated to C++, then compiled for the console with the PS5 toolchain. The first build is the long one.'
    Blank
    if (-not (Invoke-EngineTask 'Generating the C++ port from your ROM' @('env', 'PYTHONDONTWRITEBYTECODE=1', 'python3', '/workspace/scripts/generate_cpp.py'))) { $script:Failed = $true; exit 1 }
    if (-not (Invoke-EngineTask 'Compiling the PS5 title' @('bash', '/workspace/StreetsOfRageRecompilation/prospero/tools/build.sh'))) { $script:Failed = $true; exit 1 }
    if (-not ((Test-Path -LiteralPath (Join-Path $script:DistDir "$TitleId/eboot.bin")) -and (Test-Path -LiteralPath (Join-Path $script:DistDir 'data-sor/ai-code')))) {
        Stop-Wizard "The build finished but its files are not in $(Get-RelativeToRepo $script:DistDir)"
    }
    Blank
    Say-Ok "The title is built: $(Get-RelativeToRepo $script:DistDir)\$TitleId"
    Blank
    Wait-Enter
}

# ---------------------------------------------------------------------------
# 5. Zip files and FTP

function Get-TreeFiles([string]$root, [string]$prefix) {
    # "Local" and "Entry" for each file under $root; no dot files, no __pycache__.
    $rootFull = (Resolve-Path -LiteralPath $root).ProviderPath.TrimEnd('\', '/')
    $found = @()
    foreach ($file in (Get-ChildItem -LiteralPath $rootFull -Recurse -File -Force)) {
        $relative = $file.FullName.Substring($rootFull.Length).TrimStart('\', '/').Replace('\', '/')
        if ($file.Name.StartsWith('.') -or $relative -match '(^|/)__pycache__/') { continue }
        $found += @{ Local = $file.FullName; Entry = "$prefix/$relative" }
    }
    return $found
}

function Get-HomebrewFiles { return @(Get-TreeFiles (Join-Path $script:DistDir $TitleId) $TitleId) }

function Get-DataFiles {
    $files = @()
    $files += Get-TreeFiles (Join-Path $script:DistDir 'data-sor/ai-code') 'sor/ai-code'
    $files += Get-TreeFiles (Join-Path $script:DistDir 'data-sor/python') 'sor/python'
    $files += Get-TreeFiles $script:SoundtrackDir 'sor/soundtrack'
    $files += @{ Local = $script:RomDest; Entry = 'sor/SOR.bin' }
    return $files
}

# Runs in a background job. The entries get forward slashes: Compress-Archive in Windows PowerShell 5.1
# writes backslashes, which the console's unzip then takes as part of the file name.
$ZipJob = {
    param($ZipPath, $Files)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
    $stream = [IO.File]::Open($ZipPath, 'Create')
    try {
        $archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Create)
        try {
            foreach ($file in $Files) {
                $level = if ($file.Local -like '*.flac') { [IO.Compression.CompressionLevel]::NoCompression } else { [IO.Compression.CompressionLevel]::Optimal }
                [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.Local, $file.Entry, $level)
            }
        } finally { $archive.Dispose() }
    } finally { $stream.Dispose() }
}

function New-ZipFiles {
    $script:ZipHomebrew = Join-Path $script:OutputDir $ZipHomebrewName
    $script:ZipData = Join-Path $script:OutputDir $ZipDataName
    if (-not (Invoke-JobTask "Zipping the title ($ZipHomebrewName)" $ZipJob @($script:ZipHomebrew, (Get-HomebrewFiles)))) { $script:Failed = $true; exit 1 }
    if (-not (Invoke-JobTask "Zipping the data folder ($ZipDataName)" $ZipJob @($script:ZipData, (Get-DataFiles)))) { $script:Failed = $true; exit 1 }
    Blank
    Say-Ok "$(Format-Size (Get-Item -LiteralPath $script:ZipHomebrew).Length)  $ZipHomebrewName"
    Say-Ok "$(Format-Size (Get-Item -LiteralPath $script:ZipData).Length)  $ZipDataName"
}

function ConvertTo-UrlPath([string]$path) {
    return ($path -replace '%', '%25' -replace ' ', '%20' -replace '#', '%23' -replace '\?', '%3F')
}

function Get-UploadList {
    $list = @()
    foreach ($entry in (Get-DataFiles)) { $list += @{ Local = $entry.Local; Remote = '/data/' + $entry.Entry } }
    $homebrew = Get-HomebrewFiles
    foreach ($entry in ($homebrew | Where-Object { $_.Entry -ne "$TitleId/eboot.bin" })) { $list += @{ Local = $entry.Local; Remote = '/data/homebrew/' + $entry.Entry } }
    foreach ($entry in ($homebrew | Where-Object { $_.Entry -eq "$TitleId/eboot.bin" })) { $list += @{ Local = $entry.Local; Remote = '/data/homebrew/' + $entry.Entry } }
    return $list
}

function Read-ConsoleAddress {
    while ($true) {
        $script:FtpHost = (Read-TextLine 'The console''s IP address (for example 192.168.1.50)') -replace '\s', ''
        if (-not $script:FtpHost -or $script:FtpHost -notmatch '^[A-Za-z0-9.:-]+$') { Say-Warn 'That does not look like an address.'; Blank; continue }
        $portText = (Read-TextLine "FTP port (ENTER for $FtpDefaultPort)") -replace '\s', ''
        if (-not $portText) { $portText = "$FtpDefaultPort" }
        if ($portText -notmatch '^[0-9]+$') { Say-Warn 'A port is a number.'; Blank; continue }
        $script:FtpPort = $portText
        Blank
        if (Invoke-Task "Connecting to $($script:FtpHost):$($script:FtpPort)" $script:Curl @('-sS', '--connect-timeout', '8', '--max-time', '15', '--list-only', "ftp://$($script:FtpHost):$($script:FtpPort)/")) { return }
        Blank
        Say 'The console did not answer. Check that ftpsrv is running on it, that this computer is on the same network, and the address.'
        Blank
        [void](Show-MenuOrQuit @('Try another address', 'Quit'))
        Blank
    }
}

function Send-Files {
    $list = @(Get-UploadList)
    $totalFiles = $list.Count
    $totalBytes = 0
    foreach ($item in $list) { $item.Size = (Get-Item -LiteralPath $item.Local).Length; $totalBytes += $item.Size }
    Blank
    Say "Sending $totalFiles files ($(Format-Size $totalBytes)). Close the game on the console first."
    Blank
    Hide-Cursor
    $sent = 0
    $index = 0
    $errFile = Join-Path $script:LogDir 'ftp.err'
    foreach ($item in $list) {
        $index++
        Write-Progress2 $sent $totalBytes "$index/$totalFiles " $item.Remote
        $attempt = 1
        while ($true) {
            & $script:Curl -sS --connect-timeout 15 --ftp-create-dirs -T $item.Local "ftp://$($script:FtpHost):$($script:FtpPort)$(ConvertTo-UrlPath $item.Remote)" 2> $errFile
            if ($LASTEXITCODE -eq 0) { break }
            if ($attempt -ge 3) {
                Show-Cursor
                Out-Raw "`r$($script:Esc)[K"
                Say-Fail "Could not send $($item.Remote)"
                foreach ($line in (Get-Content -LiteralPath $errFile -ErrorAction SilentlyContinue)) { Out-Line "    $line" }
                Stop-Wizard 'The upload stopped. Run the wizard again: it sends everything again.'
            }
            $attempt++
            Start-Sleep -Seconds 2
        }
        $sent += $item.Size
    }
    Write-Progress2 $totalBytes $totalBytes "$totalFiles/$totalFiles " 'files'
    Show-Cursor
    Out-Line
    Blank
    Say-Ok 'Everything is on the console.'
}

function Step-Deliver {
    Start-Step 5 'Getting the game to your PS5'
    Say 'How do you want the files?'
    Blank
    $choice = Show-Menu @(
        'ZIP files|two ZIP files in this folder, to copy to the console yourself',
        'Upload by FTP|the wizard sends the files to the console over your network',
        'Both|make the ZIP files and upload')
    Blank
    $script:DeliveredZips = $false
    $script:DeliveredFtp = $false
    if ($choice -eq 0 -or $choice -eq 2) {
        New-ZipFiles
        $script:DeliveredZips = $true
        Blank
    }
    if ($choice -eq 1 -or $choice -eq 2) {
        Say "On the PS5, run an FTP server such as ftpsrv (anonymous login, port $FtpDefaultPort by default). The files go to /data/homebrew and /data/sor."
        Blank
        Read-ConsoleAddress
        Send-Files
        $script:DeliveredFtp = $true
        Blank
    }
    Wait-Enter
}

# ---------------------------------------------------------------------------
# 6. Clean up and finish

function Step-Cleanup {
    Start-Step 6 'Cleaning up'
    $remove = @(@{ Label = 'The container image and build volume'; Detail = 'about 5 GB and the compiled objects' })
    if (-not $script:HadGenerated -and (Test-Path -LiteralPath $script:GeneratedDir)) { $remove += @{ Label = 'The generated C++'; Detail = (Get-RelativeToRepo $script:GeneratedDir) } }
    if (-not $script:HadDist -and (Test-Path -LiteralPath $script:DistDir)) { $remove += @{ Label = 'The built title'; Detail = (Get-RelativeToRepo $script:DistDir) } }
    if (-not $script:HadSoundtrack -and (Test-Path -LiteralPath $script:SoundtrackDir)) { $remove += @{ Label = 'The rendered soundtrack'; Detail = (Get-RelativeToRepo $script:SoundtrackDir) } }
    if (-not $script:HadRom -and (Test-Path -LiteralPath $script:RomDest)) { $remove += @{ Label = 'The copy of your ROM'; Detail = (Get-RelativeToRepo $script:RomDest) } }

    Say 'Everything the wizard made can be removed now. Your ZIP files and your own ROM file stay.'
    Blank
    foreach ($item in $remove) { Out-Line "    $($script:Accent)-$($script:Rst) $($item.Label)  $($script:Muted)$($item.Detail)$($script:Rst)" }
    Blank
    $choice = Show-Menu @('Clean up everything|free the disk space', 'Keep it all|faster the next time')
    Blank
    if ($choice -eq 0) {
        & $script:EnginePath image rm -f $Image *> $null
        if ($LASTEXITCODE -eq 0) { Say-Ok 'Removed the container image' }
        & $script:EnginePath volume rm -f $BuildVolume *> $null
        if ($LASTEXITCODE -eq 0) { Say-Ok 'Removed the build volume' }
        $targets = @(
            @($script:HadGenerated, $script:GeneratedDir, 'the generated C++'),
            @($script:HadDist, $script:DistDir, 'the built title'),
            @($script:HadSoundtrack, $script:SoundtrackDir, 'the rendered soundtrack'),
            @($script:HadRom, $script:RomDest, 'the copy of your ROM'))
        foreach ($target in $targets) {
            if (-not $target[0] -and (Test-Path -LiteralPath $target[1])) {
                Remove-Item -LiteralPath $target[1] -Recurse -Force
                Say-Ok "Removed $($target[2])"
            }
        }
    } else {
        Say-Muted 'Nothing removed.'
    }
    Blank
}

function Write-Finish {
    $text = ''
    if ($script:DeliveredZips) {
        $text += "Your ZIP files are in: $($script:OutputDir)`n`n"
        $text += "1. ${ZipHomebrewName}: unzip it into /data/homebrew on the console (or any folder ShadowMountPlus 1.7 beta 4 or newer scans). It holds the folder $TitleId.`n`n"
        $text += "2. ${ZipDataName}: unzip it into /data on the console. It holds the folder sor: the AI, Python, the soundtrack and your ROM as SOR.bin.`n`n"
    }
    if ($script:DeliveredFtp) {
        $text += "The files are on the console: the title in /data/homebrew/$TitleId and the data in /data/sor.`n`n"
    }
    $text += 'Mount the title with ShadowMountPlus and start Streets of Rage from the home screen.'
    Write-Box $script:Okc 'All done' $text
    Blank
}

# ---------------------------------------------------------------------------

function Start-Wizard {
    Initialize-Screen
    Initialize-Paths
    Test-Workspace
    Step-Docker
    Step-Rom
    Step-Soundtrack
    Step-Build
    Step-Deliver
    Step-Cleanup
    Write-Finish
    $script:Finished = $true
}

try {
    Start-Wizard
} finally {
    if ($script:ChildProcess -and -not $script:ChildProcess.HasExited) {
        try { $script:ChildProcess.Kill() } catch { }
        if ($script:RunningContainer) { & $script:EnginePath rm -f $script:RunningContainer *> $null }
    }
    try { Show-Cursor } catch { }
    if (-not $script:Finished -and -not $script:Failed) {
        Out-Line
        Out-Line "  $($script:Warnc)$($script:G.Warn)$($script:Rst) Cancelled. Nothing else was changed."
    }
    if ($script:LogDir -and -not $script:KeepLogs -and (Test-Path -LiteralPath $script:LogDir)) {
        Remove-Item -LiteralPath $script:LogDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
