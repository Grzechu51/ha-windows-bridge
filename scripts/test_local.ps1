[CmdletBinding()]
param(
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Nie znaleziono lokalnego srodowiska .venv. Najpierw zainstaluj zaleznosci projektu."
}

function Invoke-PythonStep {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Polecenie zakonczylo sie kodem ${LASTEXITCODE}: python $($Arguments -join ' ')"
    }
}

Push-Location $repoRoot
try {
    Invoke-PythonStep -Arguments @(
        "-m", "ruff", "check", "ha_windows_bridge", "custom_components", "tests", "main.py", "mqtt_volume.pyw"
    )

    $previousQtPlatform = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    try {
        $pytestTemp = Join-Path $repoRoot "build\pytest-local-$PID"
        Invoke-PythonStep -Arguments @(
            "-m", "pytest", "--basetemp", $pytestTemp, "-p", "no:cacheprovider"
        )
    }
    finally {
        $env:QT_QPA_PLATFORM = $previousQtPlatform
    }

    if (-not $SkipBuild) {
        Invoke-PythonStep -Arguments @(
            "-m", "PyInstaller", "--clean", "--noconfirm", "HAWindowsBridge.spec"
        )

        $executable = (Resolve-Path -LiteralPath ".\dist\HA Windows Bridge\HA Windows Bridge.exe").Path
        $process = Start-Process -FilePath $executable -ArgumentList "--smoke-test" -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Smoke-test paczki zakonczyl sie kodem $($process.ExitCode)."
        }
    }

    Write-Host "Wszystkie lokalne testy zakonczyly sie poprawnie." -ForegroundColor Green
}
finally {
    Pop-Location
}
