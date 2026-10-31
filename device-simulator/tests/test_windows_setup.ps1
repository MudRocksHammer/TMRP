# Run with PowerShell 7 on Linux or Windows; no installers/network/admin required.
$ErrorActionPreference = 'Stop'
$scriptDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts'
foreach ($file in Get-ChildItem $scriptDirectory -Filter '*.ps1') {
    # ASCII source remains identical under UTF-8 and Windows ANSI code pages,
    # including when an editor or transfer tool removes the UTF-8 BOM.
    $sourceBytes = [IO.File]::ReadAllBytes($file.FullName)
    if (@($sourceBytes | Where-Object { $_ -gt 127 }).Count) {
        throw "Keep Windows entry scripts ASCII-only: $($file.Name)"
    }
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
    foreach ($codePage in @(936, 1252)) {
        $decoded = [Text.Encoding]::GetEncoding($codePage).GetString($sourceBytes)
        [System.Management.Automation.Language.Parser]::ParseInput(
            $decoded, [ref]$tokens, [ref]$parseErrors) | Out-Null
        if ($parseErrors.Count) {
            throw "Script parse failed under code page ${codePage}: $($file.Name)"
        }
    }
}
. (Join-Path $scriptDirectory 'setup-windows.ps1')
function Assert-True([bool]$Condition, [string]$Message) {
    if (!$Condition) { throw $Message }
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('tmrp-setup-test-' + [guid]::NewGuid())
try {
    New-Item -ItemType Directory -Force $temporary | Out-Null
    $fakeLocator = Join-Path $temporary 'vswhere-fixture.ps1'
    @'
$global:LASTEXITCODE = 0
if ($args -contains '-requires') {
    '[{"installationVersion":"17.14.0","installationPath":"C:\\VS2022"},{"installationVersion":"18.0.0","installationPath":"C:\\VS2026 Community"}]'
} else {
    '[{"installationVersion":"18.1.0","installationPath":"C:\\VS2026 Without Cpp"}]'
}
'@ | Set-Content $fakeLocator
    $detected = Find-VisualStudio -VsWherePath $fakeLocator
    Assert-True ($detected.Generator -eq 'Visual Studio 18 2026') 'Newest C++ instance must be preferred.'
    $pinned = Find-VisualStudio -VsWherePath $fakeLocator -InstallationPath 'C:\VS2022'
    Assert-True ($pinned.Generator -eq 'Visual Studio 17 2022') 'A saved instance must be respected.'
    $missing = Find-VisualStudio -VsWherePath $fakeLocator -InstallationPath 'C:\Missing'
    Assert-True ($null -eq $missing) 'Missing saved instances must not silently switch compilers.'
    $incomplete = Find-VisualStudio -VsWherePath $fakeLocator -IncludeWithoutCpp
    Assert-True ($incomplete.Path -eq 'C:\VS2026 Without Cpp') 'Incomplete installs must be detectable.'
    $vs2022 = ConvertTo-VSToolchain ([pscustomobject]@{
        installationVersion = '17.14.0'; installationPath = 'C:\VS2022'
    })
    $vs2026 = ConvertTo-VSToolchain ([pscustomobject]@{
        installationVersion = '18.0.0'; installationPath = 'C:\VS2026 Community'
    })
    Assert-True ($vs2022.Generator -eq 'Visual Studio 17 2022') 'VS 2022 generator mismatch.'
    Assert-True ($vs2026.Generator -eq 'Visual Studio 18 2026') 'VS 2026 generator mismatch.'
    Assert-True ($vs2026.MinimumCmake -eq [version]'4.2') 'VS 2026 must require CMake 4.2.'
    Assert-True ($vs2026.Path -eq 'C:\VS2026 Community') 'The selected instance path must be preserved.'
    Assert-True ($vs2022.BuildFolder -ne $vs2026.BuildFolder) 'Different generators must use different caches.'
    $unsupported = $false
    try {
        ConvertTo-VSToolchain ([pscustomobject]@{ installationVersion = '16.0.0' }) | Out-Null
    } catch { $unsupported = $_.Exception.Message -match 'Unsupported Visual Studio' }
    Assert-True $unsupported 'An unsupported VS version must fail explicitly.'
    Assert-True (!(Test-QtKit '')) 'An empty Qt path must be rejected.'
    Assert-True (!(Test-QtKit $temporary)) 'A missing Qt kit must be rejected.'
    foreach ($relative in @('bin/windeployqt.exe', 'lib/cmake/Qt6/Qt6Config.cmake',
        'lib/cmake/Qt6Test/Qt6TestConfig.cmake', 'plugins/sqldrivers/qsqlite.dll',
        'lib/Qt6Core.lib', 'mkspecs/qconfig.pri')) {
        $path = Join-Path $temporary $relative
        New-Item -ItemType Directory -Force (Split-Path $path -Parent) | Out-Null
        Set-Content $path ''
    }
    $qconfig = Join-Path $temporary 'mkspecs/qconfig.pri'
    Set-Content $qconfig 'QT_ARCH = arm64'
    Assert-True (!(Test-QtKit $temporary)) 'ARM64 must be rejected.'
    Set-Content $qconfig 'QT_ARCH = x86_64'
    Assert-True (Test-QtKit $temporary) 'A complete MSVC x64 fixture must be accepted.'
    Remove-Item (Join-Path $temporary 'lib/Qt6Core.lib')
    Assert-True (!(Test-QtKit $temporary)) 'A kit without the MSVC import library must be rejected.'
    Set-Content (Join-Path $temporary 'lib/Qt6Core.lib') ''
    Remove-Item (Join-Path $temporary 'plugins/sqldrivers/qsqlite.dll')
    Assert-True (!(Test-QtKit $temporary)) 'A kit without SQLite must be rejected.'
    $shell = (Get-Process -Id $PID).Path
    Invoke-Checked $shell @('-NoProfile', '-Command', 'exit 0')
    $failed = $false
    try { Invoke-Checked $shell @('-NoProfile', '-Command', 'exit 23') }
    catch { $failed = $_.Exception.Message -match 'exit 23' }
    Assert-True $failed 'A native tool error must stop setup and preserve its exit code.'
    Write-Host 'PASS: PowerShell syntax, VS 2022/2026 selection, Qt kit validation and native failure handling.'
} finally {
    if (Test-Path $temporary) { Remove-Item -Recurse -Force $temporary }
}
