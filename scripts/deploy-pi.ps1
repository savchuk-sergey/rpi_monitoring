param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9.-]*$')] [string] $HostName = '192.168.31.94',
    [ValidatePattern('^[A-Za-z0-9._-]+$')] [string] $UserName = 'ssavchuk',
    [Parameter(Mandatory)] [string] $CalibrationFile,
    [switch] $EnablePowerActions,
    [switch] $DryRun
)
$ErrorActionPreference = 'Stop'
$target = "$UserName@$HostName"
$elevate = if ($UserName -eq 'root') { '' } else { 'sudo -n ' }
$privilegeCheck = if ($UserName -eq 'root') { 'test "$(id -u)" -eq 0' } else { 'sudo -n true' }
$venvCheck = '{ venv_test=$(mktemp -d) || exit; python3 -m venv "$venv_test"; result=$?; rm -rf "$venv_test"; test "$result" -eq 0; }'
$stage = '/tmp/homelab-resource-monitor-deploy-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$ssh = @('-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes')
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$powerActionsEnabled = if ($EnablePowerActions) { 'true' } else { 'false' }
$powerActionsLabel = if ($EnablePowerActions) { 'enabled' } else { 'disabled' }

if (-not (Test-Path -LiteralPath $CalibrationFile -PathType Leaf)) { throw 'Calibration file not found.' }
& ssh @ssh $target "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; export PATH; hostname >/dev/null && test -e /dev/spidev0.0 && test -e /dev/spidev0.1 && command -v python3 >/dev/null && command -v systemctl >/dev/null && command -v systemd-analyze >/dev/null && command -v runuser >/dev/null && command -v curl >/dev/null && command -v sed >/dev/null && vcgencmd get_throttled && $privilegeCheck && $venvCheck"
if ($LASTEXITCODE -ne 0) { throw 'Pi preflight failed.' }
if ($DryRun) { Write-Output "Dry-run preflight passed; no changes made; power actions $powerActionsLabel."; exit 0 }

Push-Location $repo
try {
    & ssh @ssh $target "mkdir -p $stage/agents"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create remote stage.' }
    & scp -q agents/__init__.py "${target}:${stage}/agents/"
    if ($LASTEXITCODE -ne 0) { throw 'Agent package copy failed.' }
    & scp -q -r agents/linux "${target}:${stage}/agents/"
    if ($LASTEXITCODE -ne 0) { throw 'Linux agent copy failed.' }
    & scp -q -r display hub protocol deploy pyproject.toml "${target}:${stage}/"
    if ($LASTEXITCODE -ne 0) { throw 'Source copy failed.' }
    & scp -q -p $CalibrationFile "${target}:${stage}/touch-calibration.json"
    if ($LASTEXITCODE -ne 0) { throw 'Calibration copy failed.' }
    & ssh @ssh $target "sed -i 's/\r`$//' $stage/deploy/raspberry-pi/install.sh"
    if ($LASTEXITCODE -ne 0) { throw 'Installer line-ending normalization failed.' }
    $install = "${elevate}sh $stage/deploy/raspberry-pi/install.sh $stage $stage/touch-calibration.json $powerActionsEnabled && curl -fsS http://127.0.0.1:8766/api/v1/state >/dev/null"
    $diagnostics = "${elevate}systemctl --no-pager --full status homelab-resource-monitor-hub.service homelab-resource-monitor-display.service homelab-resource-monitor-linux-agent.service homelab-resource-monitor-power.socket; ${elevate}journalctl --no-pager -n 50 -u homelab-resource-monitor-hub.service -u homelab-resource-monitor-display.service -u homelab-resource-monitor-linux-agent.service -u 'homelab-resource-monitor-power@*.service'"
    & ssh @ssh $target "$install || { $diagnostics; exit 1; }"
    if ($LASTEXITCODE -ne 0) { throw 'Remote installation or verification failed.' }
} finally {
    & ssh @ssh $target "rm -rf -- $stage" 2>$null
    Pop-Location
}
Write-Output "Deployed Raspberry Pi services to $target; power actions $powerActionsLabel."
