# Build Streets of Rage for the PlayStation 5 on Windows 11, step by step, with nothing to install
# but a container engine (Docker Desktop or Podman Desktop). Run it from a terminal:
#
#   powershell -ExecutionPolicy Bypass -File scripts\ps5_wizzard.ps1      (or scripts\ps5_wizzard.cmd)
#
# The ZIP files it makes go to the folder you run it from. It is the same wizard as
# scripts/ps5_wizzard.sh (macOS and Linux), and runs on Windows PowerShell 5.1, the one Windows 11
# ships, as well as on PowerShell 7. These files are plain ASCII on purpose: 5.1 reads a file without
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

# The wizard itself is in scripts/ps5_wizard/: the screen, background work, and the steps.
. (Join-Path $script:ScriptsDir 'ps5_wizard/tui.ps1')
. (Join-Path $script:ScriptsDir 'ps5_wizard/tasks.ps1')
. (Join-Path $script:ScriptsDir 'ps5_wizard/steps-setup.ps1')
. (Join-Path $script:ScriptsDir 'ps5_wizard/steps-build.ps1')
. (Join-Path $script:ScriptsDir 'ps5_wizard/steps-deliver.ps1')

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
