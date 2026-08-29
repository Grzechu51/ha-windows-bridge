param(
    [switch]$SkipInstall,
    [switch]$Installer,
    [string]$SigningThumbprint = $env:HAWB_SIGNING_THUMBPRINT
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
function Invoke-CodeSigning {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($SigningThumbprint)) {
        Write-Warning "Artifacts are unsigned. Set HAWB_SIGNING_THUMBPRINT for a public release."
        return
    }
    $NormalizedThumbprint = ($SigningThumbprint -replace "\s", "").ToUpperInvariant()
    if ($NormalizedThumbprint -notmatch "^[0-9A-F]{40}$") {
        throw "HAWB_SIGNING_THUMBPRINT must be a 40-character SHA-1 certificate thumbprint."
    }
    $SignTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $SignTool) {
        throw "signtool.exe was not found. Install the Windows SDK."
    }
    & $SignTool.Source sign /sha1 $NormalizedThumbprint /fd SHA256 /tr "http://timestamp.digicert.com" /td SHA256 $Path
    Assert-NativeCommandSucceeded "Podpisywanie $Path"
    $Signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Authenticode verification failed for $Path ($($Signature.Status))."
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

$AppVersion = (& $VenvPython -c "from ha_windows_bridge import __version__; print(__version__)").Trim()
Assert-NativeCommandSucceeded "Odczyt wersji aplikacji"

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

$ProjectRootPrefix = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\') + '\'
$TestTemp = Join-Path $ProjectRoot (".build-test-temp-" + [System.Guid]::NewGuid().ToString("N"))
$ResolvedTestTemp = [System.IO.Path]::GetFullPath($TestTemp)
if (-not $ResolvedTestTemp.StartsWith($ProjectRootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a test directory outside the project: $ResolvedTestTemp"
}
try {
    & $VenvPython -m pytest -p no:cacheprovider --basetemp $ResolvedTestTemp
    Assert-NativeCommandSucceeded "Testy"
}
finally {
    if (Test-Path -LiteralPath $ResolvedTestTemp) {
        Remove-Item -LiteralPath $ResolvedTestTemp -Recurse -Force
    }
}
& $VenvPython "tools\create_icon.py"
Assert-NativeCommandSucceeded "Generowanie ikony"
$PythonBase = (& $VenvPython -c "import sys; print(sys.base_prefix)").Trim()
Assert-NativeCommandSucceeded "Odczyt katalogu bazowego Pythona"
$OriginalBuildPath = $env:PATH
$CleanBuildPath = @(
    (Split-Path -Parent $VenvPython),
    $PythonBase,
    (Join-Path $PythonBase "DLLs"),
    (Join-Path $PythonBase "Scripts"),
    (Join-Path $env:SystemRoot "System32"),
    $env:SystemRoot
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
try {
    # PyInstaller resolves transitive DLL dependencies through PATH. Build
    # runners may prepend unrelated tools (for example Poppler) that ship DLLs
    # named like Windows ICU. Keeping only Python and Windows locations avoids
    # silently packaging those incompatible libraries.
    $env:PATH = $CleanBuildPath -join [System.IO.Path]::PathSeparator
    & $VenvPython -m PyInstaller --noconfirm --clean "HAWindowsBridge.spec"
    Assert-NativeCommandSucceeded "Budowanie PyInstaller"
}
finally {
    $env:PATH = $OriginalBuildPath
}

$UnexpectedRuntimeFiles = @(
    Get-ChildItem -LiteralPath (Split-Path -Parent $BuiltExe) -Recurse -File |
        Where-Object {
            $_.Name -in @("icu.dll", "icuuc.dll", "ucrtbase.dll") -or
            $_.Name -match "^icudt\d+\.dll$"
        }
)
if ($UnexpectedRuntimeFiles.Count -gt 0) {
    throw "Unexpected system/runtime DLLs were bundled: $($UnexpectedRuntimeFiles.FullName -join ', ')."
}

$SmokeTest = Start-Process -FilePath $BuiltExe -ArgumentList "--smoke-test" -Wait -PassThru -WindowStyle Hidden
if ($SmokeTest.ExitCode -ne 0) {
    throw "Packaged application smoke test failed (exit code $($SmokeTest.ExitCode))."
}
$BuiltVersion = (Get-Item -LiteralPath $BuiltExe).VersionInfo.ProductVersion.Trim()
if ($BuiltVersion -ne $AppVersion) {
    throw "EXE version $BuiltVersion does not match application version $AppVersion."
}
$IntegrationVersion = (Get-Content -LiteralPath "custom_components\ha_windows_bridge\manifest.json" -Raw | ConvertFrom-Json).version
if ($IntegrationVersion -ne $AppVersion) {
    throw "Integration version $IntegrationVersion does not match application version $AppVersion."
}
Invoke-CodeSigning -Path $BuiltExe

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
    $InstallerPath = Join-Path $ProjectRoot "dist\HA-Windows-Bridge-Setup-$AppVersion.exe"
    Invoke-CodeSigning -Path $InstallerPath
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
