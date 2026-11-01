# The PS5 build wizard's paths, container engine (step 1) and ROM (step 2).

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

