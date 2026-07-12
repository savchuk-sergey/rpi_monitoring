param(
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]*$')] [string] $HubHost,
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9._-]+$')] [string] $HubUser,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9][a-z0-9._-]{0,63}$')] [string] $NodeId,
    [Parameter(Mandatory)] [ValidateLength(1, 64)] [ValidatePattern('\S')] [string] $DisplayName,
    [ValidateRange(1, 60)] [int] $IntervalSeconds = 2
)
$ErrorActionPreference = 'Stop'
$service = 'HomelabResourceMonitorWindowsAgent'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$project = Join-Path $repo 'agents\windows\HomelabResourceMonitor.WindowsAgent\HomelabResourceMonitor.WindowsAgent.csproj'
$artifact = Join-Path $repo 'artifacts\windows-agent\win-x64'
$configFile = Join-Path $repo 'deploy\windows\windows-agent.json'
$installedConfig = Join-Path $env:ProgramData 'HomelabResourceMonitor\windows-agent.json'
$hubTarget = "$HubUser@$HubHost"
$hubElevate = if ($HubUser -eq 'root') { '' } else { 'sudo -n ' }
$hubPrivilegeCheck = if ($HubUser -eq 'root') { 'test "$(id -u)" -eq 0' } else { 'sudo -n true' }
$hubHelper = '/tmp/homelab-resource-monitor-add-node-hash-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '.py'
$ssh = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes')

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this script from an elevated PowerShell.' }
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { throw 'dotnet SDK is required.' }
& ssh @ssh $hubTarget "command -v python3 >/dev/null && command -v curl >/dev/null && $hubPrivilegeCheck && ${hubElevate}test -f /etc/homelab-resource-monitor/hub.json && curl -fsS http://127.0.0.1:8765/healthz >/dev/null"
if ($LASTEXITCODE -ne 0) { throw 'Hub preflight failed.' }

$newNode = -not (Test-Path -LiteralPath $installedConfig -PathType Leaf)
if ($newNode) {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $token = [Convert]::ToBase64String($bytes)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try { $hashBytes = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($token)) } finally { $sha256.Dispose() }
    $hash = ($hashBytes | ForEach-Object { $_.ToString('x2') }) -join ''
    $config = [ordered]@{
        hub_url = "http://${HubHost}:8765/api/v1/telemetry"
        node_id = $NodeId
        display_name = $DisplayName
        token = $token
        interval_seconds = $IntervalSeconds
    } | ConvertTo-Json
    [IO.File]::WriteAllText($configFile, $config + [Environment]::NewLine)
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    icacls.exe $configFile /inheritance:r /grant:r "${identity}:(F)" '*S-1-5-18:(F)' '*S-1-5-32-544:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict local config ACL.' }
} else {
    $installed = Get-Content -Raw -LiteralPath $installedConfig | ConvertFrom-Json
    if ($installed.node_id -ne $NodeId) { throw "Installed node_id '$($installed.node_id)' does not match '$NodeId'." }
    if ($installed.hub_url -ne "http://${HubHost}:8765/api/v1/telemetry") { throw 'Installed config points to a different hub.' }
    $configFile = $installedConfig
}

try {
    if ($newNode) {
        & scp -q (Join-Path $repo 'deploy\raspberry-pi\add-node-hash.py') "${hubTarget}:${hubHelper}"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot copy the hub registration helper.' }
        & ssh @ssh $hubTarget "${hubElevate}python3 $hubHelper $NodeId $hash && ${hubElevate}systemctl restart homelab-resource-monitor-hub.service && curl -fs --retry 10 --retry-delay 1 --retry-connrefused http://127.0.0.1:8765/healthz >/dev/null"
        if ($LASTEXITCODE -ne 0) { throw 'Hub node registration failed.' }
    }
    if (Test-Path -LiteralPath $artifact) { Remove-Item -LiteralPath $artifact -Recurse -Force }
    & dotnet publish $project -c Release -r win-x64 --self-contained true -o $artifact
    if ($LASTEXITCODE -ne 0) { throw 'Windows agent publish failed.' }
    & (Join-Path $repo 'deploy\windows\install.ps1') -ArtifactDirectory $artifact -ConfigFile $configFile
    if ((Get-Service -Name $service).Status -ne 'Running') { throw 'Windows agent service is not running.' }

    $verify = 'for i in 1 2 3 4 5 6 7 8 9 10; do curl -fsS http://127.0.0.1:8766/api/v1/state | python3 -c ''import json,sys; raise SystemExit(0 if any(n["node_id"] == sys.argv[1] for n in json.load(sys.stdin)["nodes"]) else 1)'' {0} && exit 0; sleep 1; done; exit 1' -f $NodeId
    & ssh @ssh $hubTarget $verify
    if ($LASTEXITCODE -ne 0) { throw "Node '$NodeId' did not appear in hub state." }
    Write-Output "Deployed Windows agent '$NodeId'"
} finally {
    & ssh @ssh $hubTarget "rm -f -- $hubHelper" 2>$null
}
