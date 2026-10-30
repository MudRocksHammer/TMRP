param(
    [Parameter(Mandatory=$true)][string]$QtPrefix,
    [Parameter(Mandatory=$true)][string]$VcpkgRoot,
    [ValidateSet("Debug", "Release")][string]$Configuration = "Release"
)
$ErrorActionPreference = "Stop"
$simulatorRoot = Split-Path $PSScriptRoot -Parent
$buildDirectory = Join-Path $simulatorRoot "build-windows"
$toolchain = Join-Path $VcpkgRoot "scripts/buildsystems/vcpkg.cmake"
if (!(Test-Path $toolchain) -or !(Test-Path (Join-Path $QtPrefix "bin/windeployqt.exe"))) {
    throw "Qt (MSVC 2022 x64) と vcpkg のパスを確認してください。"
}
# MSVC x64、Qt、vcpkgの依存ライブラリを同じ構成で使用する
cmake -S $simulatorRoot -B $buildDirectory -G "Visual Studio 17 2022" -A x64 `
    "-DCMAKE_PREFIX_PATH=$QtPrefix" "-DCMAKE_TOOLCHAIN_FILE=$toolchain" `
    -DVCPKG_TARGET_TRIPLET=x64-windows
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }
cmake --build $buildDirectory --config $Configuration --parallel 2
if ($LASTEXITCODE -ne 0) { throw "C++ build failed" }
$env:PATH = "$(Join-Path $QtPrefix 'bin');$env:PATH"
$env:QT_PLUGIN_PATH = Join-Path $QtPrefix "plugins"
$env:QT_QPA_PLATFORM = "offscreen"
# QtTestを実行する。vcpkgがMQTT/OpenSSL DLLをビルド先へ配置する
ctest --test-dir $buildDirectory -C $Configuration --output-on-failure
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
Remove-Item Env:QT_QPA_PLATFORM
$app = Join-Path $buildDirectory "$Configuration/tmrp-device-simulator.exe"
$deployMode = if ($Configuration -eq "Debug") { "--debug" } else { "--release" }
# Qt DLL・platforms・SQLite等のQtプラグインを実行ファイルの横へ配置する
& (Join-Path $QtPrefix "bin/windeployqt.exe") $deployMode --compiler-runtime $app
if ($LASTEXITCODE -ne 0) { throw "Qt deployment failed" }
Write-Host "Built: $app"
