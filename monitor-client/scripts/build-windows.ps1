#Requires -Version 5.1
param([switch]$Launch)
$ErrorActionPreference = 'Stop'
$monitorRoot = Split-Path $PSScriptRoot -Parent
$repository = Split-Path $monitorRoot -Parent
. (Join-Path $repository 'device-simulator/scripts/windows-toolchain.ps1')
$settings = Get-Content (Join-Path $repository 'device-simulator/.deps/windows-toolchain.json') -Raw | ConvertFrom-Json
$vs = Find-VisualStudio -InstallationPath $settings.VisualStudioPath
if (!$vs) { throw 'Saved Visual Studio C++ installation not found. Run setup-windows.ps1.' }
$qt = $settings.QtPrefix
if (!(Test-Path (Join-Path $qt 'lib/cmake/Qt6WebSockets/Qt6WebSocketsConfig.cmake'))) {
    throw 'Qt WebSockets is missing. Run monitor-client/scripts/setup-windows.ps1.'
}
$previousPath = $env:PATH
$previousPlugins = $env:QT_PLUGIN_PATH
$previousPlatform = $env:QT_QPA_PLATFORM
try {
    $env:PATH = "$($settings.CmakeBin);$(Join-Path $qt 'bin');$env:PATH"
    $cmake = Find-CompatibleCMake $vs
    if (!$cmake) { throw 'Compatible CMake not found.' }
    $build = Join-Path $monitorRoot $vs.BuildFolder
    & $cmake -S $monitorRoot -B $build -G $vs.Generator -A x64 `
        "-DCMAKE_GENERATOR_INSTANCE=$($vs.Path)" "-DCMAKE_PREFIX_PATH=$qt"
    if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed.' }
    & $cmake --build $build --config Release --parallel 2
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    $env:QT_PLUGIN_PATH = Join-Path $qt 'plugins'
    $env:QT_QPA_PLATFORM = 'offscreen'
    & (Join-Path (Split-Path $cmake -Parent) 'ctest.exe') --test-dir $build -C Release --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    $app = Join-Path $build 'Release/tmrp-monitor-client.exe'
    & (Join-Path $qt 'bin/windeployqt.exe') --release --compiler-runtime $app
    if ($LASTEXITCODE -ne 0) { throw 'Qt deployment failed.' }
    Write-Host "Built: $app"
} finally {
    $env:PATH = $previousPath
    $env:QT_PLUGIN_PATH = $previousPlugins
    $env:QT_QPA_PLATFORM = $previousPlatform
}
if ($Launch) { Start-Process $app }
