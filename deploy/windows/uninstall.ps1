$ErrorActionPreference = 'Stop'
$service = 'HomelabResourceMonitorWindowsAgent'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell.'
}
sc.exe stop $service 2>$null | Out-Null
sc.exe delete $service 2>$null | Out-Null
Remove-Item -LiteralPath (Join-Path $env:ProgramFiles 'HomelabResourceMonitor\WindowsAgent') -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $env:ProgramData 'HomelabResourceMonitor\windows-agent.json') -Force -ErrorAction SilentlyContinue
