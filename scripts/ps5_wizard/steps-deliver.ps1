# The PS5 build wizard's ZIP files and FTP upload (step 5), clean up (step 6) and closing screen.

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

