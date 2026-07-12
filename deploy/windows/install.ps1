param(
    [Parameter(Mandatory)] [string] $ArtifactDirectory,
    [Parameter(Mandatory)] [string] $ConfigFile
)
$ErrorActionPreference = 'Stop'
$service = 'HomelabResourceMonitorWindowsAgent'
$install = Join-Path $env:ProgramFiles 'HomelabResourceMonitor\WindowsAgent'
$configDirectory = Join-Path $env:ProgramData 'HomelabResourceMonitor'
$config = Join-Path $configDirectory 'windows-agent.json'
$errorLog = Join-Path $env:TEMP 'homelab-resource-monitor-install-error.txt'
trap {
    [IO.File]::WriteAllText($errorLog, ($_ | Out-String))
    break
}

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell.'
}
if (-not (Test-Path -LiteralPath $ArtifactDirectory -PathType Container)) { throw 'Artifact directory not found.' }
if (-not (Test-Path -LiteralPath $ConfigFile -PathType Leaf)) { throw 'Config file not found.' }
if (-not (Get-CimInstance Win32_SystemDriver -Filter "Name='PawnIO'" -ErrorAction SilentlyContinue)) {
    throw 'PawnIO is required for Windows CPU temperature/power sensors. Install signed package namazso.PawnIO first.'
}

sc.exe stop $service 2>$null | Out-Null
if (Get-Service -Name $service -ErrorAction SilentlyContinue) {
    (Get-Service -Name $service).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(20))
}
New-Item -ItemType Directory -Force -Path $install, $configDirectory | Out-Null
Copy-Item -Path (Join-Path $ArtifactDirectory '*') -Destination $install -Recurse -Force
if (Test-Path -LiteralPath $config) {
    icacls.exe $config /grant:r '*S-1-5-32-544:(F)' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot make the existing config updateable by Administrators.' }
}
$sourceConfig = (Resolve-Path -LiteralPath $ConfigFile).Path
if (-not (Test-Path -LiteralPath $config) -or $sourceConfig -ne (Resolve-Path -LiteralPath $config).Path) {
    Copy-Item -LiteralPath $ConfigFile -Destination $config -Force
}
icacls.exe $config /inheritance:r /grant:r '*S-1-5-18:(R)' '*S-1-5-32-544:(F)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict installed config ACL.' }

$exe = Join-Path $install 'HomelabResourceMonitor.WindowsAgent.exe'
sc.exe query $service 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    sc.exe create $service start= auto binPath= "`"$exe`" --config `"$config`"" DisplayName= 'Homelab Resource Monitor Windows Agent' | Out-Null
} else {
    Set-Service -Name $service -StartupType Automatic
}
if ($LASTEXITCODE -ne 0) { throw 'Cannot create or update Windows Service.' }
sc.exe failure $service reset= 86400 actions= restart/5000/restart/15000/none/0 | Out-Null
sc.exe start $service | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Windows Service was installed but did not start.' }
Remove-Item -LiteralPath $errorLog -Force -ErrorAction SilentlyContinue
Write-Output "Installed and started $service"
