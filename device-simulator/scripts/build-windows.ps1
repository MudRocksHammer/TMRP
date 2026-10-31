param(
    [string]$QtPrefix,
    [string]$VcpkgRoot,
    [string]$VisualStudioPath,
    [ValidateSet("Debug", "Release")][string]$Configuration = "Release"
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot 'windows-toolchain.ps1')
$simulatorRoot = Split-Path $PSScriptRoot -Parent
$settingsPath = Join-Path $simulatorRoot '.deps/windows-toolchain.json'
if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    if (!$QtPrefix) { $QtPrefix = $settings.QtPrefix }
    if (!$VcpkgRoot) { $VcpkgRoot = $settings.VcpkgRoot }
    if (!$VisualStudioPath) { $VisualStudioPath = $settings.VisualStudioPath }
    if ($settings.CmakeBin) { $env:PATH = "$($settings.CmakeBin);$env:PATH" }
}
if (!$QtPrefix -or !$VcpkgRoot) {
    throw 'Run setup-windows.ps1 first, or specify -QtPrefix and -VcpkgRoot.'
}
$vs = Find-VisualStudio -InstallationPath $VisualStudioPath
if (!$vs) { throw 'VS 2022/2026 C++ tools not found. Run setup-windows.ps1 after installing the C++ workload.' }
$cmake = Find-CompatibleCMake $vs
if (!$cmake) { throw "CMake $($vs.MinimumCmake) or newer is required. Run setup-windows.ps1." }
$buildDirectory = Join-Path $simulatorRoot $vs.BuildFolder
$toolchain = Join-Path $VcpkgRoot "scripts/buildsystems/vcpkg.cmake"
if (!(Test-Path $toolchain) -or !(Test-Path (Join-Path $QtPrefix "bin/windeployqt.exe"))) {
    throw 'Check the paths to the Qt MSVC x64 kit and vcpkg.'
}
$previousPath = $env:PATH
$previousPlugins = $env:QT_PLUGIN_PATH
$previousPlatform = $env:QT_QPA_PLATFORM
$previousVS = $env:VCPKG_VISUAL_STUDIO_PATH
try {
    $env:PATH = "$(Split-Path $cmake -Parent);$(Join-Path $QtPrefix 'bin');$env:PATH"
    $env:VCPKG_VISUAL_STUDIO_PATH = $vs.Path
    # Use the same Visual Studio instance for the app and vcpkg dependencies.
    & $cmake -S $simulatorRoot -B $buildDirectory -G $vs.Generator -A x64 `
        "-DCMAKE_GENERATOR_INSTANCE=$($vs.Path)" `
        "-DCMAKE_PREFIX_PATH=$QtPrefix" "-DCMAKE_TOOLCHAIN_FILE=$toolchain" `
        -DVCPKG_TARGET_TRIPLET=x64-windows
    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }
    & $cmake --build $buildDirectory --config $Configuration --parallel 2
    if ($LASTEXITCODE -ne 0) { throw "C++ build failed" }
    $env:QT_PLUGIN_PATH = Join-Path $QtPrefix "plugins"
    $env:QT_QPA_PLATFORM = "offscreen"
    # Run QtTest; vcpkg deploys the MQTT/OpenSSL DLLs alongside each executable.
    ctest --test-dir $buildDirectory -C $Configuration --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    $app = Join-Path $buildDirectory "$Configuration/tmrp-device-simulator.exe"
    $deployMode = if ($Configuration -eq "Debug") { "--debug" } else { "--release" }
    # Deploy Qt DLLs and platform/SQLite plugins alongside the executable.
    & (Join-Path $QtPrefix "bin/windeployqt.exe") $deployMode --compiler-runtime $app
    if ($LASTEXITCODE -ne 0) { throw "Qt deployment failed" }
    Write-Host "Built: $app"
} finally {
    $env:PATH = $previousPath
    $env:QT_PLUGIN_PATH = $previousPlugins
    $env:QT_QPA_PLATFORM = $previousPlatform
    $env:VCPKG_VISUAL_STUDIO_PATH = $previousVS
}
