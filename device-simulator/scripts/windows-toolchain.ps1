# Shared detection for setup and direct builds; no installation side effects.
function ConvertTo-VSToolchain {
    param($Instance)
    $installationVersion = @($Instance.installationVersion)[0]
    $major = ([version]$installationVersion).Major
    switch ($major) {
        17 { $generator = 'Visual Studio 17 2022'; $minimum = '3.21'; $folder = 'build-windows' }
        18 { $generator = 'Visual Studio 18 2026'; $minimum = '4.2'; $folder = 'build-windows-vs2026' }
        default { throw "Unsupported Visual Studio version: $($Instance.installationVersion)" }
    }
    return [pscustomobject]@{
        Path = $Instance.installationPath
        Generator = $generator
        MinimumCmake = [version]$minimum
        BuildFolder = $folder
    }
}

function Find-VisualStudio {
    param(
        [string]$InstallationPath,
        [switch]$IncludeWithoutCpp,
        [string]$VsWherePath = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    $locator = $VsWherePath
    if (!(Test-Path $locator)) { return $null }
    $arguments = @('-products', '*', '-version', '[17.0,19.0)', '-format', 'json', '-utf8')
    if (!$IncludeWithoutCpp) {
        $arguments += @('-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64')
    }
    # vswhere emits UTF-8 with -utf8, including installation paths containing non-ASCII text.
    $previousEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
        $json = & $locator @arguments
        if ($LASTEXITCODE -ne 0) { throw 'vswhere failed.' }
    } finally { [Console]::OutputEncoding = $previousEncoding }
    $instances = @($json -join "`n" | ConvertFrom-Json)
    if ($InstallationPath) {
        $instances = @($instances | Where-Object { $_.installationPath -eq $InstallationPath })
    }
    $chosen = $instances | Sort-Object {
        [version](@($_.installationVersion)[0])
    } -Descending |
        Select-Object -First 1
    if ($chosen) { return ConvertTo-VSToolchain $chosen }
    return $null
}

function Find-CompatibleCMake {
    param($VisualStudio)
    $candidates = @(
        (Join-Path $VisualStudio.Path 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'),
        "$env:ProgramFiles\CMake\bin\cmake.exe"
    )
    $command = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (!(Test-Path $candidate)) { continue }
        $versionText = & $candidate --version
        if ($LASTEXITCODE -ne 0) { continue }
        if (($versionText -join "`n") -match 'cmake version (\d+\.\d+\.\d+)') {
            if ([version]$Matches[1] -ge $VisualStudio.MinimumCmake) { return $candidate }
        }
    }
    return $null
}
