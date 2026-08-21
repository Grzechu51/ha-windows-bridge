param(
    [switch]$SkipInstall,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

function Assert-NativeCommandSucceeded {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed (exit code $LASTEXITCODE)."
    }
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv (Join-Path $ProjectRoot ".venv")
    Assert-NativeCommandSucceeded "Tworzenie środowiska .venv"
}

if (-not $SkipInstall) {
    & $VenvPython -m pip install --upgrade pip
    Assert-NativeCommandSucceeded "Aktualizacja pip"
    & $VenvPython -m pip install -c "constraints.txt" -e ".[dev]"
    Assert-NativeCommandSucceeded "Instalacja zależności"
}

$BuiltExe = Join-Path $ProjectRoot "dist\HA Windows Bridge\HA Windows Bridge.exe"
if (Test-Path -LiteralPath $BuiltExe) {
    $ResolvedBuiltExe = [System.IO.Path]::GetFullPath($BuiltExe)
    $RunningBridge = @(
        Get-Process -Name "HA Windows Bridge" -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $ResolvedBuiltExe }
    )
    if ($RunningBridge.Count -gt 0) {
        throw "Close HA Windows Bridge before building. Running PID: $($RunningBridge.Id -join ', ')."
    }
}

& $VenvPython -m pytest
Assert-NativeCommandSucceeded "Testy"
& $VenvPython "tools\create_icon.py"
Assert-NativeCommandSucceeded "Generowanie ikony"
& $VenvPython -m PyInstaller --noconfirm --clean "HAWindowsBridge.spec"
Assert-NativeCommandSucceeded "Budowanie PyInstaller"

$AppVersion = (& $VenvPython -c "from ha_windows_bridge import __version__; print(__version__)").Trim()
Assert-NativeCommandSucceeded "Odczyt wersji aplikacji"
$AppDist = Join-Path $ProjectRoot "dist\HA Windows Bridge"
Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination (Join-Path $AppDist "LICENSE") -Force
$PortableZip = Join-Path $ProjectRoot "dist\HA-Windows-Bridge-$AppVersion-win64.zip"
Compress-Archive -Path (Join-Path $AppDist "*") -DestinationPath $PortableZip -CompressionLevel Optimal -Force

$IntegrationZip = Join-Path $ProjectRoot "dist\HA-Windows-Bridge-HA-Integration-$AppVersion.zip"
$ComponentRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "custom_components"))
$ComponentRootPrefix = $ComponentRoot.TrimEnd('\') + '\'
Get-ChildItem -LiteralPath $ComponentRoot -Directory -Filter "__pycache__" -Recurse |
    ForEach-Object {
        $CachePath = [System.IO.Path]::GetFullPath($_.FullName)
        if (-not $CachePath.StartsWith($ComponentRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove cache outside custom_components: $CachePath"
        }
        Remove-Item -LiteralPath $CachePath -Recurse -Force
    }
$IntegrationSources = @(
    (Join-Path $ProjectRoot "custom_components"),
    (Join-Path $ProjectRoot "hacs.json"),
    (Join-Path $ProjectRoot "HOME_ASSISTANT_INTEGRATION.md"),
    (Join-Path $ProjectRoot "LICENSE")
)
Compress-Archive -Path $IntegrationSources -DestinationPath $IntegrationZip -CompressionLevel Optimal -Force

if ($Installer) {
    $Iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($Iscc) {
        $IsccPath = $Iscc.Source
    } else {
        $BundledIscc = Join-Path $ProjectRoot "tools\InnoSetup\7.0.2\ISCC.exe"
        if (-not (Test-Path -LiteralPath $BundledIscc)) {
            throw "Inno Setup (iscc.exe) was not found. Install Inno Setup 7 or run without -Installer."
        }
        $IsccPath = $BundledIscc
    }
    & $IsccPath "/DMyAppVersion=$AppVersion" "installer\HAWindowsBridge.iss"
    Assert-NativeCommandSucceeded "Budowanie instalatora"
}

$ReleaseArtifacts = @(
    $PortableZip,
    $IntegrationZip,
    (Join-Path $ProjectRoot "dist\HA-Windows-Bridge-Setup-$AppVersion.exe")
) | Where-Object { Test-Path -LiteralPath $_ }
$ChecksumPath = Join-Path $ProjectRoot "dist\SHA256SUMS-$AppVersion.txt"
$ChecksumLines = $ReleaseArtifacts | ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
    "$($Hash.Hash.ToLowerInvariant())  $([System.IO.Path]::GetFileName($_))"
}
[System.IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [System.Text.UTF8Encoding]::new($false))

Write-Host "Gotowe: dist\HA Windows Bridge\HA Windows Bridge.exe"
Write-Host "Portable version: dist\HA-Windows-Bridge-$AppVersion-win64.zip"
Write-Host "Home Assistant integration: dist\HA-Windows-Bridge-HA-Integration-$AppVersion.zip"
Write-Host "Checksums: dist\SHA256SUMS-$AppVersion.txt"
