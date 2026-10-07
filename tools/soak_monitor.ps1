<#[
Read-only, unattended release soak observer. Start the packaged app with
--soak-telemetry <absolute JSON path>, then monitor that same file. The output
contains process metrics and allowlisted counters, never app messages/config.
#>
param(
    [string]$TelemetryPath = "",
    [string]$OutputDirectory = "",
    [double]$DurationHours = 24,
    [ValidateRange(1, 3600)][int]$IntervalSeconds = 5,
    [string]$ProcessName = "HA Windows Bridge",
    [string]$ExpectedExePath = "",
    [switch]$ImportOnly
)

$ErrorActionPreference = "Stop"
function Assert-SoakKeys {
    param($Object, [string[]]$Allowed, [string[]]$Required)
    if ($null -eq $Object -or $Object -isnot [pscustomobject]) {
        throw "Invalid telemetry object."
    }
    $Names = @($Object.PSObject.Properties | ForEach-Object { $_.Name })
    foreach ($Name in $Names) {
        if ($Name -cnotin $Allowed) { throw "Unexpected telemetry field." }
    }
    foreach ($Name in $Required) {
        if ($Name -cnotin $Names) { throw "Missing telemetry field." }
    }
}

function ConvertTo-SoakInteger {
    param($Value)
    if (($Value -isnot [int] -and $Value -isnot [long]) -or $Value -lt 0) {
        throw "Invalid telemetry counter."
    }
    return [long]$Value
}

function ConvertTo-SoakNumber {
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -isnot [int] -and $Value -isnot [long] -and $Value -isnot [double] -and
        $Value -isnot [decimal]) { throw "Invalid telemetry duration." }
    $Number = [double]$Value
    if ($Number -lt 0 -or [double]::IsNaN($Number) -or [double]::IsInfinity($Number)) {
        throw "Invalid telemetry duration."
    }
    return $Number
}

function ConvertTo-SoakTimestamp {
    param($Value)
    if ($Value -is [datetime]) { return [DateTimeOffset]$Value }
    if ($Value -isnot [string]) { throw "Invalid telemetry timestamp." }
    return [DateTimeOffset]::Parse(
        $Value, [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind
    )
}

function Test-SoakPayload {
    param($Raw)
    Assert-SoakKeys -Object $Raw -Allowed @("schema", "pid", "process_start_utc", "sample_utc", "closed", "logs", "connections") -Required @("schema", "pid", "process_start_utc", "sample_utc", "closed", "logs", "connections")
    if ((ConvertTo-SoakInteger $Raw.schema) -ne 1 -or
        (ConvertTo-SoakInteger $Raw.pid) -lt 1 -or $Raw.pid -gt [int]::MaxValue -or
        $Raw.closed -isnot [bool]) { throw "Invalid telemetry identity." }
    $Start = ConvertTo-SoakTimestamp $Raw.process_start_utc
    $Sample = ConvertTo-SoakTimestamp $Raw.sample_utc
    Assert-SoakKeys -Object $Raw.logs -Allowed @("warnings", "errors") -Required @("warnings", "errors")
    $Logs = [pscustomobject]@{
        warnings = ConvertTo-SoakInteger $Raw.logs.warnings
        errors = ConvertTo-SoakInteger $Raw.logs.errors
    }
    Assert-SoakKeys -Object $Raw.connections -Allowed @("mqtt", "home_assistant") -Required @()
    $Connections = [pscustomobject]@{}
    $ConnectionKeys = @("state", "attempt", "transitions", "failures", "reconnects",
        "recoveries", "last_failure_utc", "last_recovery_utc",
        "last_recovery_seconds", "max_recovery_seconds", "pending_failure")
    $States = @("stopped", "connecting", "connected", "retry_wait", "suspended",
        "auth_error", "configuration_error")
    foreach ($Transport in @($Raw.connections.PSObject.Properties | ForEach-Object { $_.Name })) {
        $Item = $Raw.connections.$Transport
        Assert-SoakKeys -Object $Item -Allowed $ConnectionKeys -Required $ConnectionKeys
        if ($Item.state -isnot [string] -or $Item.state -cnotin $States -or
            $Item.pending_failure -isnot [bool]) { throw "Invalid connection state." }
        $LastFailure = if ($null -eq $Item.last_failure_utc) { $null } else {
            (ConvertTo-SoakTimestamp $Item.last_failure_utc).ToString("o")
        }
        $LastRecovery = if ($null -eq $Item.last_recovery_utc) { $null } else {
            (ConvertTo-SoakTimestamp $Item.last_recovery_utc).ToString("o")
        }
        $Clean = [pscustomobject]@{
            state = $Item.state
            attempt = ConvertTo-SoakInteger $Item.attempt
            transitions = ConvertTo-SoakInteger $Item.transitions
            failures = ConvertTo-SoakInteger $Item.failures
            reconnects = ConvertTo-SoakInteger $Item.reconnects
            recoveries = ConvertTo-SoakInteger $Item.recoveries
            last_failure_utc = $LastFailure
            last_recovery_utc = $LastRecovery
            last_recovery_seconds = ConvertTo-SoakNumber $Item.last_recovery_seconds
            max_recovery_seconds = ConvertTo-SoakNumber $Item.max_recovery_seconds
            pending_failure = $Item.pending_failure
        }
        $Connections | Add-Member -NotePropertyName $Transport -NotePropertyValue $Clean
    }
    return [pscustomobject]@{
        schema = 1
        pid = [int]$Raw.pid
        process_start_utc = $Start
        sample_utc = $Sample
        closed = $Raw.closed
        logs = $Logs
        connections = $Connections
    }
}

function Get-SoakAssessment {
    param(
        [object[]]$Rows,
        [DateTimeOffset]$Started,
        [DateTimeOffset]$Ended,
        [TimeSpan]$Duration,
        [int]$IntervalSeconds,
        [bool]$Completed,
        [int]$BadSamples,
        [int]$GapCount
    )
    $Reasons = [System.Collections.Generic.List[string]]::new()
    if (-not $Completed) { $Reasons.Add("observer_not_completed") }
    if ($Duration -lt [TimeSpan]::FromHours(24) -or
        ($Ended - $Started).TotalHours -lt 24) { $Reasons.Add("less_than_24h") }
    if ($Rows.Count -lt 2) { $Reasons.Add("insufficient_samples") }
    if ($BadSamples -gt 0 -or @($Rows | Where-Object { $_.status -ne "ok" }).Count -gt 0) {
        $Reasons.Add("invalid_or_missing_samples")
    }
    $GapDetected = $GapCount -gt 0
    for ($Index = 1; $Index -lt $Rows.Count; $Index++) {
        if (([DateTimeOffset]$Rows[$Index].timestamp_utc -
             [DateTimeOffset]$Rows[$Index - 1].timestamp_utc).TotalSeconds -gt
            ($IntervalSeconds * 1.5)) { $GapDetected = $true }
    }
    if ($GapDetected) { $Reasons.Add("sampling_gap") }
    if ($Rows.Count -gt 0) {
        $First = [DateTimeOffset]$Rows[0].timestamp_utc
        $Last = [DateTimeOffset]$Rows[$Rows.Count - 1].timestamp_utc
        if (($First - $Started).TotalSeconds -gt ($IntervalSeconds * 1.5) -or
            ($Started.Add($Duration) - $Last).TotalSeconds -gt ($IntervalSeconds * 0.5)) {
            $Reasons.Add("sample_coverage")
        }
    }
    if (($Rows | Measure-Object app_errors -Maximum).Maximum -gt 0) {
        $Reasons.Add("application_errors")
    }
    if ($Rows.Count -gt 0) {
        $LastRow = $Rows[$Rows.Count - 1]
        if ($LastRow.mqtt_pending_failure -eq $true -or
            $LastRow.direct_pending_failure -eq $true) { $Reasons.Add("unrecovered_connection") }
    }
    return [pscustomobject]@{
        verdict = if ($Reasons.Count -gt 0) { "INCOMPLETE_OR_FAIL" } else { "PENDING_REVIEW" }
        reasons = @($Reasons)
    }
}

function Get-SoakProcessSample {
    param(
        [int]$TargetPid,
        [DateTimeOffset]$ExpectedStart,
        [string]$ProcessName,
        [string]$ExpectedExePath,
        [DateTimeOffset]$Now
    )
    try {
        $Observed = Get-Process -Id $TargetPid -ErrorAction Stop
    }
    catch {
        return [pscustomobject]@{ status = "process_missing" }
    }
    try {
        $ActualStart = ([DateTimeOffset]$Observed.StartTime.ToUniversalTime()).ToUnixTimeMilliseconds()
        if ([Math]::Abs($ActualStart - $ExpectedStart.ToUnixTimeMilliseconds()) -gt 2000 -or
            $Observed.ProcessName -ne $ProcessName) {
            return [pscustomobject]@{ status = "process_identity_mismatch" }
        }
        if ($ExpectedExePath -and
            -not [string]::Equals($Observed.Path, $ExpectedExePath,
                [System.StringComparison]::OrdinalIgnoreCase)) {
            return [pscustomobject]@{ status = "executable_path_mismatch" }
        }
        $Sample = [pscustomobject]@{
            status = "ok"
            pid = [int]$Observed.Id
            uptime_seconds = [Math]::Round(($Now - $ExpectedStart).TotalSeconds, 1)
            working_set_mb = [Math]::Round($Observed.WorkingSet64 / 1MB, 2)
            private_mb = [Math]::Round($Observed.PrivateMemorySize64 / 1MB, 2)
            handles = [int]$Observed.HandleCount
            threads = [int]$Observed.Threads.Count
            cpu_seconds = $Observed.TotalProcessorTime.TotalSeconds
        }
        if ($Observed.HasExited) {
            return [pscustomobject]@{ status = "process_missing" }
        }
        return $Sample
    }
    catch {
        return [pscustomobject]@{ status = "process_unavailable" }
    }
}

if ($ImportOnly) { return }
if ([string]::IsNullOrWhiteSpace($TelemetryPath) -or
    [string]::IsNullOrWhiteSpace($OutputDirectory)) {
    throw "TelemetryPath and OutputDirectory are required."
}
if ($DurationHours -le 0) { throw "DurationHours must be positive." }
$Duration = [TimeSpan]::FromHours($DurationHours)
$TelemetryPath = [System.IO.Path]::GetFullPath($TelemetryPath)
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if ($ExpectedExePath) { $ExpectedExePath = [System.IO.Path]::GetFullPath($ExpectedExePath) }
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$CsvPath = Join-Path $OutputDirectory "samples.csv"
$SummaryPath = Join-Path $OutputDirectory "summary.json"
if ((Test-Path -LiteralPath $CsvPath) -or (Test-Path -LiteralPath $SummaryPath)) {
    throw "OutputDirectory already contains soak results; choose an empty directory."
}

$Started = [DateTimeOffset]::UtcNow
$Deadline = $Started.Add($Duration)
$NextTick = $Started
$PreviousSample = $null
$PreviousCpu = $null
$ExpectedIdentity = $null
$Rows = [System.Collections.Generic.List[object]]::new()
$GapCount = 0
$BadSamples = 0
$Completed = $false
$MaxTelemetryAgeSeconds = 15  # Producer cadence is five seconds, independent of observer interval.

try {
    do {
        $Now = [DateTimeOffset]::UtcNow
        if ($null -ne $PreviousSample -and ($Now - $PreviousSample).TotalSeconds -gt ($IntervalSeconds * 1.5)) {
            $GapCount++
        }
        $PreviousSample = $Now
        $Status = "ok"
        $Telemetry = $null
        $ProcessSample = $null
        $Age = $null
        try {
            $Raw = Get-Content -LiteralPath $TelemetryPath -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            $Telemetry = Test-SoakPayload $Raw
            $TeleStart = [DateTimeOffset]$Telemetry.process_start_utc
            $TeleSample = [DateTimeOffset]$Telemetry.sample_utc
            $Age = ($Now - $TeleSample).TotalSeconds
            if ($Age -lt -2 -or $Age -gt $MaxTelemetryAgeSeconds -or $Telemetry.closed) {
                $Status = "telemetry_stale"
            }
            $Identity = "$($Telemetry.pid)|$($TeleStart.ToUnixTimeMilliseconds())"
            if ($null -eq $ExpectedIdentity) { $ExpectedIdentity = $Identity }
            elseif ($Identity -ne $ExpectedIdentity) { $Status = "process_restarted" }
        }
        catch {
            $Status = "telemetry_unavailable"
            $Telemetry = $null
        }

        if ($Telemetry) {
            $ProcessSample = Get-SoakProcessSample -TargetPid $Telemetry.pid -ExpectedStart $TeleStart -ProcessName $ProcessName -ExpectedExePath $ExpectedExePath -Now $Now
            if ($Status -eq "ok" -and $ProcessSample.status -ne "ok") {
                $Status = $ProcessSample.status
            }
        }

        $CpuPercent = $null
        if ($ProcessSample -and $ProcessSample.status -eq "ok") {
            $CpuSeconds = $ProcessSample.cpu_seconds
            if ($null -ne $PreviousCpu -and $PreviousCpu.pid -eq $ProcessSample.pid) {
                $WallSeconds = ($Now - $PreviousCpu.when).TotalSeconds
                if ($WallSeconds -gt 0) {
                    $CpuPercent = [Math]::Round(100 * ($CpuSeconds - $PreviousCpu.seconds) /
                        ($WallSeconds * [Environment]::ProcessorCount), 3)
                }
            }
            $PreviousCpu = @{ pid = $ProcessSample.pid; when = $Now; seconds = $CpuSeconds }
        }

        $Mqtt = if ($Telemetry) { $Telemetry.connections.mqtt } else { $null }
        $Direct = if ($Telemetry) { $Telemetry.connections.home_assistant } else { $null }
        $Row = [pscustomobject]@{
            timestamp_utc = $Now.ToString("o")
            status = $Status
            pid = if ($ProcessSample) { $ProcessSample.pid } else { $null }
            process_uptime_seconds = if ($ProcessSample) { $ProcessSample.uptime_seconds } else { $null }
            working_set_mb = if ($ProcessSample) { $ProcessSample.working_set_mb } else { $null }
            private_mb = if ($ProcessSample) { $ProcessSample.private_mb } else { $null }
            handles = if ($ProcessSample) { $ProcessSample.handles } else { $null }
            threads = if ($ProcessSample) { $ProcessSample.threads } else { $null }
            cpu_percent_of_machine = $CpuPercent
            telemetry_age_seconds = if ($null -ne $Age) { [Math]::Round($Age, 2) } else { $null }
            app_warnings = if ($Telemetry) { $Telemetry.logs.warnings } else { $null }
            app_errors = if ($Telemetry) { $Telemetry.logs.errors } else { $null }
            mqtt_state = if ($Mqtt) { $Mqtt.state } else { $null }
            mqtt_attempt = if ($Mqtt) { $Mqtt.attempt } else { $null }
            mqtt_failures = if ($Mqtt) { $Mqtt.failures } else { $null }
            mqtt_reconnects = if ($Mqtt) { $Mqtt.reconnects } else { $null }
            mqtt_recoveries = if ($Mqtt) { $Mqtt.recoveries } else { $null }
            mqtt_last_recovery_utc = if ($Mqtt) { $Mqtt.last_recovery_utc } else { $null }
            mqtt_max_recovery_seconds = if ($Mqtt) { $Mqtt.max_recovery_seconds } else { $null }
            mqtt_pending_failure = if ($Mqtt) { $Mqtt.pending_failure } else { $null }
            direct_state = if ($Direct) { $Direct.state } else { $null }
            direct_attempt = if ($Direct) { $Direct.attempt } else { $null }
            direct_failures = if ($Direct) { $Direct.failures } else { $null }
            direct_reconnects = if ($Direct) { $Direct.reconnects } else { $null }
            direct_recoveries = if ($Direct) { $Direct.recoveries } else { $null }
            direct_last_recovery_utc = if ($Direct) { $Direct.last_recovery_utc } else { $null }
            direct_max_recovery_seconds = if ($Direct) { $Direct.max_recovery_seconds } else { $null }
            direct_pending_failure = if ($Direct) { $Direct.pending_failure } else { $null }
        }
        $Rows.Add($Row)
        $Row | Export-Csv -LiteralPath $CsvPath -NoTypeInformation -Append -Encoding UTF8
        if ($Status -ne "ok") { $BadSamples++ }
        if ($Now -ge $Deadline) {
            $Completed = $true
            break
        }
        do { $NextTick = $NextTick.AddSeconds($IntervalSeconds) }
        while ($NextTick -le [DateTimeOffset]::UtcNow)
        $WakeAt = if ($NextTick -lt $Deadline) { $NextTick } else { $Deadline }
        $SleepMilliseconds = [Math]::Max(1, ($WakeAt - [DateTimeOffset]::UtcNow).TotalMilliseconds)
        Start-Sleep -Milliseconds ([int][Math]::Ceiling($SleepMilliseconds))
    } while ($true)
}
finally {
    $Ended = [DateTimeOffset]::UtcNow
    $Elapsed = ($Ended - $Started).TotalSeconds
    $Good = @($Rows | Where-Object { $_.status -eq "ok" })
    $Baseline = @($Good | Where-Object {
        ([DateTimeOffset]$_.timestamp_utc - $Started).TotalMinutes -ge 30
    } | Select-Object -First 1)
    $Last = @($Good | Select-Object -Last 1)
    $Assessment = Get-SoakAssessment -Rows $Rows.ToArray() -Started $Started -Ended $Ended -Duration $Duration -IntervalSeconds $IntervalSeconds -Completed $Completed -BadSamples $BadSamples -GapCount $GapCount
    $Verdict = $Assessment.verdict
    $Summary = [ordered]@{
        schema = 1
        verdict = $Verdict
        reasons = @($Assessment.reasons)
        started_utc = $Started.ToString("o")
        ended_utc = $Ended.ToString("o")
        elapsed_hours = [Math]::Round($Elapsed / 3600, 4)
        requested_hours = $DurationHours
        interval_seconds = $IntervalSeconds
        sample_count = $Rows.Count
        invalid_samples = $BadSamples
        sampling_gaps = $GapCount
        first_sample = if ($Good.Count -gt 0) { $Good[0] } else { $null }
        warm_baseline_after_30m = if ($Baseline.Count -gt 0) { $Baseline[0] } else { $null }
        last_sample = if ($Last.Count -gt 0) { $Last[0] } else { $null }
        peaks = if ($Good.Count -gt 0) {
            [ordered]@{
                working_set_mb = ($Good | Measure-Object working_set_mb -Maximum).Maximum
                private_mb = ($Good | Measure-Object private_mb -Maximum).Maximum
                handles = ($Good | Measure-Object handles -Maximum).Maximum
                threads = ($Good | Measure-Object threads -Maximum).Maximum
                cpu_percent_of_machine = ($Good | Measure-Object cpu_percent_of_machine -Maximum).Maximum
            }
        } else { $null }
    }
    $Summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
    Write-Host "Soak $Verdict; $($Rows.Count) samples, $BadSamples invalid, $GapCount gaps. Results: $OutputDirectory"
}
