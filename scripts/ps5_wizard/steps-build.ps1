# The PS5 build wizard's toolchain image and soundtrack (step 3), and the build (step 4).

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

