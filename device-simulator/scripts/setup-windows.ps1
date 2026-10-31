#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\TMRP\toolchains",
    [ValidatePattern('^6\.\d+\.\d+$')][string]$QtVersion = '6.8.3',
    [string]$QtPrefix,
    [string]$VcpkgRoot,
    [switch]$SetupOnly,
    [switch]$Launch
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-toolchain.ps1')

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed (exit $LASTEXITCODE). Fix the error above and run setup again."
    }
}

function Update-SessionPath {
    # Refresh installer changes without changing the permanent PATH ourselves.
    $env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
        [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:PATH
}

function Install-WingetPackage {
    param([string]$Id, [string[]]$Extra = @())
    if (!(Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'Install/update Microsoft App Installer (winget), reopen PowerShell and retry.'
    }
    Write-Host "Installing $Id ..."
    Invoke-Checked 'winget.exe' (@('install', '--id', $Id, '--exact', '--source', 'winget',
        '--accept-source-agreements', '--accept-package-agreements') + $Extra)
    Update-SessionPath
}

function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe"
    )
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\WindowsApps\*') {
        $candidates += $command.Source
    }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}

function Test-QtKit {
    param([string]$Prefix)
    if (!$Prefix) { return $false }
    foreach ($relative in @('bin/windeployqt.exe', 'lib/cmake/Qt6/Qt6Config.cmake',
        'lib/cmake/Qt6Test/Qt6TestConfig.cmake', 'plugins/sqldrivers/qsqlite.dll',
        'lib/Qt6Core.lib')) {
        if (!(Test-Path (Join-Path $Prefix $relative))) { return $false }
    }
    # Reject MinGW/ARM kits before starting a long dependency build.
    $configuration = Join-Path $Prefix 'mkspecs/qconfig.pri'
    if (!(Test-Path $configuration)) { return $false }
    $contents = Get-Content $configuration -Raw
    return ($contents -match '(?m)^QT_ARCH\s*=\s*x86_64\s*$')
}

function Start-Setup {
    if ($env:OS -ne 'Windows_NT' -or ![Environment]::Is64BitProcess -or
        $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
        throw 'Run this script in 64-bit PowerShell on Windows x64.'
    }
    if ($SetupOnly -and $Launch) { throw 'Use either -SetupOnly or -Launch.' }
    if ($QtPrefix -and !(Test-QtKit $QtPrefix)) {
        throw 'QtPrefix must point to a complete Qt MSVC x64 kit (including QtTest and SQLite).'
    }
    $root = [IO.Path]::GetFullPath($InstallRoot)
    New-Item -ItemType Directory -Force $root | Out-Null
    Write-Host "Toolchain folder: $root"

    if (!(Get-Command git.exe -ErrorAction SilentlyContinue)) {
        Install-WingetPackage 'Git.Git'
    }
    if (!(Get-Command git.exe -ErrorAction SilentlyContinue)) {
        throw 'Git is unavailable. Reopen PowerShell and retry.'
    }
    $vs = Find-VisualStudio
    if (!$vs) {
        $incomplete = Find-VisualStudio -IncludeWithoutCpp
        if ($incomplete) {
            throw "In Visual Studio Installer, modify '$($incomplete.Path)' and add Desktop development with C++ (MSVC x64/x86, Windows SDK, CMake tools), then retry."
        }
        # --force also allows adding the workload to an incomplete Build Tools install.
        Install-WingetPackage 'Microsoft.VisualStudio.2022.BuildTools' @('--force', '--override',
            '--passive --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended')
        $vs = Find-VisualStudio
        if (!$vs) { throw 'VS 2022 C++ tools unavailable. Finish installation/reboot, then retry.' }
    }
    Write-Host "Using $($vs.Generator): $($vs.Path)"
    $cmake = Find-CompatibleCMake $vs
    if (!$cmake) {
        Install-WingetPackage 'Kitware.CMake' @('--force')
        $cmake = Find-CompatibleCMake $vs
    }
    if (!$cmake) { throw "CMake $($vs.MinimumCmake) or newer is required. Reopen PowerShell and retry." }
    $cmakeBin = Split-Path $cmake -Parent
    $env:PATH = "$cmakeBin;$env:PATH"

    if (!$VcpkgRoot) {
        if ($env:VCPKG_ROOT) { $VcpkgRoot = $env:VCPKG_ROOT }
        elseif ($env:VCPKG_INSTALLATION_ROOT) { $VcpkgRoot = $env:VCPKG_INSTALLATION_ROOT }
        else { $VcpkgRoot = Join-Path $root 'vcpkg' }
    }
    $VcpkgRoot = [IO.Path]::GetFullPath($VcpkgRoot)
    if (!(Test-Path $VcpkgRoot)) {
        Invoke-Checked 'git.exe' @('clone', 'https://github.com/microsoft/vcpkg.git', $VcpkgRoot)
    }
    if (!(Test-Path (Join-Path $VcpkgRoot 'scripts/buildsystems/vcpkg.cmake'))) {
        throw "Not a vcpkg checkout: $VcpkgRoot. Specify another -VcpkgRoot."
    }
    if (!(Test-Path (Join-Path $VcpkgRoot 'vcpkg.exe'))) {
        Invoke-Checked (Join-Path $VcpkgRoot 'bootstrap-vcpkg.bat') @('-disableMetrics')
    }

    if (!$QtPrefix) {
        foreach ($candidate in @($env:QT_ROOT_DIR, "C:\Qt\$QtVersion\msvc2022_64",
            (Join-Path $root "Qt/$QtVersion/msvc2022_64"))) {
            if (Test-QtKit $candidate) { $QtPrefix = $candidate; break }
        }
    }
    if (!$QtPrefix) {
        $python = Find-Python
        if (!$python) {
            Install-WingetPackage 'Python.Python.3.12' @('--scope', 'user')
            $python = Find-Python
        }
        if (!$python) { throw 'Python unavailable. Reopen PowerShell and retry.' }
        $venv = Join-Path $root 'aqt-venv'
        $aqtPython = Join-Path $venv 'Scripts/python.exe'
        if (!(Test-Path $aqtPython)) { Invoke-Checked $python @('-m', 'venv', $venv) }
        Invoke-Checked $aqtPython @('-m', 'pip', 'install', 'aqtinstall==3.3.0')
        $qtRoot = Join-Path $root 'Qt'
        Invoke-Checked $aqtPython @('-m', 'aqt', 'install-qt', 'windows', 'desktop',
            $QtVersion, 'win64_msvc2022_64', '--outputdir', $qtRoot)
        $QtPrefix = Join-Path $qtRoot "$QtVersion/msvc2022_64"
    }
    if (!(Test-QtKit $QtPrefix)) { throw "Qt installation incomplete: $QtPrefix" }
    $QtPrefix = [IO.Path]::GetFullPath($QtPrefix)
    $simulator = Split-Path $PSScriptRoot -Parent
    $settingsDirectory = Join-Path $simulator '.deps'
    New-Item -ItemType Directory -Force $settingsDirectory | Out-Null
    $settings = Join-Path $settingsDirectory 'windows-toolchain.json'
    @{ QtPrefix = $QtPrefix; VcpkgRoot = $VcpkgRoot; CmakeBin = $cmakeBin;
        VisualStudioPath = $vs.Path } |
        ConvertTo-Json | Set-Content -Encoding UTF8 $settings
    Write-Host "Saved local build settings: $settings"
    if (!$SetupOnly) {
        & (Join-Path $PSScriptRoot 'build-windows.ps1')
        if ($Launch) {
            Start-Process (Join-Path $simulator "$($vs.BuildFolder)/Release/tmrp-device-simulator.exe")
        }
    }
}

# Dot-sourcing only loads functions, enabling isolated tests without installation.
if ($MyInvocation.InvocationName -ne '.') { Start-Setup }
