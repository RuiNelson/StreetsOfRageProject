# Background work for the PS5 build wizard: a spinner over a program or a job, and a progress bar.

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

