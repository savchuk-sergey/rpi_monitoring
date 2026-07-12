param(
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]*$')] [string] $AgentHost,
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9._-]+$')] [string] $AgentUser,
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]*$')] [string] $HubHost,
    [Parameter(Mandatory)] [ValidatePattern('^[A-Za-z0-9._-]+$')] [string] $HubUser,
    [Parameter(Mandatory)] [ValidatePattern('^[a-z0-9][a-z0-9._-]{0,63}$')] [string] $NodeId,
    [Parameter(Mandatory)] [ValidateLength(1, 64)] [ValidatePattern('\S')] [string] $DisplayName,
    [ValidateRange(1, 60)] [int] $IntervalSeconds = 2,
    [switch] $DryRun
)
$ErrorActionPreference = 'Stop'
$ssh = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes')
$agentTarget = "$AgentUser@$AgentHost"
$hubTarget = "$HubUser@$HubHost"
$agentElevate = if ($AgentUser -eq 'root') { '' } else { 'sudo -n ' }
$hubElevate = if ($HubUser -eq 'root') { '' } else { 'sudo -n ' }
$agentPrivilegeCheck = if ($AgentUser -eq 'root') { 'test "$(id -u)" -eq 0' } else { 'sudo -n true' }
$hubPrivilegeCheck = if ($HubUser -eq 'root') { 'test "$(id -u)" -eq 0' } else { 'sudo -n true' }
$stage = '/tmp/homelab-resource-monitor-deploy-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$hubHelper = '/tmp/homelab-resource-monitor-add-node-hash-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '.py'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configFile = $null

& ssh @ssh $agentTarget "command -v python3 >/dev/null && command -v systemctl >/dev/null && command -v curl >/dev/null && $agentPrivilegeCheck && curl -fsS http://${HubHost}:8765/healthz >/dev/null"
if ($LASTEXITCODE -ne 0) { throw 'Linux agent preflight failed.' }
& ssh @ssh $hubTarget "command -v python3 >/dev/null && command -v systemctl >/dev/null && command -v curl >/dev/null && $hubPrivilegeCheck && ${hubElevate}test -f /etc/homelab-resource-monitor/hub.json && curl -fsS http://127.0.0.1:8765/healthz >/dev/null"
if ($LASTEXITCODE -ne 0) { throw 'Hub preflight failed.' }

$readNode = "if ${agentElevate}test -f /etc/homelab-resource-monitor/linux-agent.json; then ${agentElevate}python3 -c 'import json; print(json.load(open(`"/etc/homelab-resource-monitor/linux-agent.json`"))[`"node_id`"])'; fi"
$installedNode = (& ssh @ssh $agentTarget $readNode | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the installed Linux agent config.' }
if ($installedNode -and $installedNode -ne $NodeId) { throw "Installed node_id '$installedNode' does not match '$NodeId'." }
if ($DryRun) { Write-Output "Dry-run preflight passed for $agentTarget; no changes made."; exit 0 }

$targetInfo = @(& ssh @ssh $agentTarget "uname -m; python3 -c 'import sys; print(str(sys.version_info.major)+str(sys.version_info.minor))'")
if ($LASTEXITCODE -ne 0 -or $targetInfo.Count -ne 2) { throw 'Cannot determine target Python platform.' }
$architecture = $targetInfo[0].Trim()
$pythonTag = $targetInfo[1].Trim()
$platform = switch ($architecture) {
    'x86_64' { 'manylinux2014_x86_64' }
    'aarch64' { 'manylinux2014_aarch64' }
    default { throw "Unsupported Linux architecture '$architecture'." }
}
$wheelhouse = Join-Path $repo "artifacts\linux-agent\${architecture}-cp${pythonTag}"
New-Item -ItemType Directory -Force -Path $wheelhouse | Out-Null
Remove-Item -Path (Join-Path $wheelhouse 'homelab_resource_monitor-*.whl') -Force -ErrorAction SilentlyContinue
Push-Location $repo
try {
    & python -m pip wheel --disable-pip-version-check --no-deps --wheel-dir $wheelhouse .
    if ($LASTEXITCODE -ne 0) { throw 'Application wheel build failed.' }
    & python -m pip download --disable-pip-version-check --dest $wheelhouse --only-binary=:all: --platform $platform --python-version $pythonTag --implementation cp --abi "cp$pythonTag" 'aiohttp==3.13.2' 'jsonschema==4.25.1'
    if ($LASTEXITCODE -ne 0) { throw "Cannot build wheelhouse for $architecture CPython $pythonTag." }
    $runtime = Join-Path $wheelhouse 'runtime'
    $artifactRoot = [IO.Path]::GetFullPath((Join-Path $repo 'artifacts\linux-agent'))
    if (-not [IO.Path]::GetFullPath($runtime).StartsWith($artifactRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe runtime artifact path.' }
    if (Test-Path -LiteralPath $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
    & python -m pip install --disable-pip-version-check --no-index --find-links $wheelhouse --target $runtime --platform $platform --python-version $pythonTag --implementation cp --abi "cp$pythonTag" --only-binary=:all: homelab-resource-monitor
    if ($LASTEXITCODE -ne 0) { throw 'Ready runtime artifact build failed.' }
} finally {
    Pop-Location
}

try {
    Push-Location $repo
    & ssh @ssh $agentTarget "mkdir -p $stage/deploy"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create remote stage.' }
    & scp -q -r deploy/linux deploy/systemd "${agentTarget}:${stage}/deploy/"
    if ($LASTEXITCODE -ne 0) { throw 'Installer copy failed.' }
    & scp -q -r $runtime "${agentTarget}:${stage}/runtime"
    if ($LASTEXITCODE -ne 0) { throw 'Runtime artifact copy failed.' }

    $configArgument = ''
    if (-not $installedNode) {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $token = [Convert]::ToBase64String($bytes)
        $sha256 = [Security.Cryptography.SHA256]::Create()
        try { $hashBytes = $sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($token)) } finally { $sha256.Dispose() }
        $hash = ($hashBytes | ForEach-Object { $_.ToString('x2') }) -join ''
        $configFile = [IO.Path]::GetTempFileName()
        $config = [ordered]@{
            hub_url = "http://${HubHost}:8765/api/v1/telemetry"
            node_id = $NodeId
            display_name = $DisplayName
            token = $token
            interval_seconds = $IntervalSeconds
        } | ConvertTo-Json
        [IO.File]::WriteAllText($configFile, $config + [Environment]::NewLine)
        & scp -q deploy/raspberry-pi/add-node-hash.py "${hubTarget}:${hubHelper}"
        if ($LASTEXITCODE -ne 0) { throw 'Cannot copy the hub registration helper.' }
        & ssh @ssh $hubTarget "${hubElevate}python3 $hubHelper $NodeId $hash && ${hubElevate}systemctl restart homelab-resource-monitor-hub.service && curl -fs --retry 10 --retry-delay 1 --retry-connrefused http://127.0.0.1:8765/healthz >/dev/null"
        if ($LASTEXITCODE -ne 0) { throw 'Hub node registration failed.' }
        & scp -q $configFile "${agentTarget}:${stage}/linux-agent.json"
        if ($LASTEXITCODE -ne 0) { throw 'Agent config copy failed.' }
        $configArgument = " $stage/linux-agent.json"
    }

    $install = "${agentElevate}sh $stage/deploy/linux/install-agent.sh $stage/runtime$configArgument"
    $diagnostics = "${agentElevate}systemctl --no-pager --full status homelab-resource-monitor-linux-agent.service; ${agentElevate}journalctl --no-pager -n 50 -u homelab-resource-monitor-linux-agent.service"
    & ssh @ssh $agentTarget "$install && ${agentElevate}systemctl --quiet is-active homelab-resource-monitor-linux-agent.service || { $diagnostics; exit 1; }"
    if ($LASTEXITCODE -ne 0) { throw 'Linux agent installation failed.' }

    $verify = 'for i in 1 2 3 4 5 6 7 8 9 10; do curl -fsS http://127.0.0.1:8766/api/v1/state | python3 -c ''import json,sys; raise SystemExit(0 if any(n["node_id"] == sys.argv[1] for n in json.load(sys.stdin)["nodes"]) else 1)'' {0} && exit 0; sleep 1; done; exit 1' -f $NodeId
    & ssh @ssh $hubTarget $verify
    if ($LASTEXITCODE -ne 0) { throw "Node '$NodeId' did not appear in hub state." }
    Write-Output "Deployed Linux agent '$NodeId' to $agentTarget"
} finally {
    if ((Get-Location).Path -eq $repo) { Pop-Location }
    & ssh @ssh $agentTarget "rm -rf -- $stage" 2>$null
    & ssh @ssh $hubTarget "rm -f -- $hubHelper" 2>$null
    if ($configFile) { Remove-Item -LiteralPath $configFile -Force -ErrorAction SilentlyContinue }
}
