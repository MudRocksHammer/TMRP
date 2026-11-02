#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\TMRP\toolchains",
    [string]$QtPrefix,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
& (Join-Path $repository 'device-simulator/scripts/setup-windows.ps1') `
    -InstallRoot $InstallRoot -QtPrefix $QtPrefix -WithMonitor -SetupOnly
& (Join-Path $PSScriptRoot 'build-windows.ps1') -Launch:$Launch
