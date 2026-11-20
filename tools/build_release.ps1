<#
.SYNOPSIS
    Assemble the FAA portable release zip (RELEASE_PLAN_1.0 Phase 2 / #22).

.DESCRIPTION
    Layout produced in build/release/FAA-<Version>/:
        FAA.WpfGui.exe          self-contained WPF shell (single file)
        backend/                PyInstaller one-folder backend (faa_webui.exe + _internal)
        start_faa.bat           double-click launcher
        LICENSE / THIRD_PARTY_NOTICES.md / ASSETS.md / README.md / CHANGELOG.md
        SHA256SUMS.txt          per-file hashes
    Output:
        build/release/FAA-<Version>-win-x64.zip
        build/release/FAA-<Version>-win-x64.zip.sha256

.PARAMETER Version
    Release version used in folder / zip names (default: 1.0.0).

.PARAMETER SkipBuild
    Reuse existing build/dist/faa_webui and build/wpf instead of rebuilding.

.EXAMPLE
    pwsh tools/build_release.ps1 -Version 1.0.0
#>
param(
    [string]$Version = "1.0.0",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $root "build"
$backendDir = Join-Path $buildDir "dist\faa_webui"
$wpfDir = Join-Path $buildDir "wpf"
$releaseRoot = Join-Path $buildDir "release"
$stage = Join-Path $releaseRoot "FAA-$Version"
$zipPath = Join-Path $releaseRoot "FAA-$Version-win-x64.zip"

function Find-Dotnet {
    $cmd = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $env:LOCALAPPDATA "Microsoft\dotnet\dotnet.exe"
    if (Test-Path $local) { return $local }
    $global = "C:\Program Files\dotnet\dotnet.exe"
    if (Test-Path $global) { return $global }
    throw "dotnet not found (PATH / %LOCALAPPDATA%\Microsoft\dotnet / Program Files)."
}

function Find-Python {
    $venv = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "Python not found (.venv\Scripts\python.exe or python on PATH)."
}

if (-not $SkipBuild) {
    Write-Host "[1/4] PyInstaller backend -> $backendDir"
    $python = Find-Python
    Push-Location $root
    try {
        & $python -m PyInstaller tools\faa_webui.spec --noconfirm --clean `
            --distpath (Join-Path $buildDir "dist") --workpath (Join-Path $buildDir "work")
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit=$LASTEXITCODE)" }
    }
    finally { Pop-Location }

    Write-Host "[2/4] dotnet publish WPF -> $wpfDir"
    $dotnet = Find-Dotnet
    if (Test-Path $wpfDir) { Remove-Item $wpfDir -Recurse -Force }
    & $dotnet publish (Join-Path $root "native\FAA.WpfGui\FAA.WpfGui.csproj") `
        -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o $wpfDir
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed (exit=$LASTEXITCODE)" }
}
else {
    Write-Host "[1/4] SkipBuild: reuse existing backend / WPF publish output"
}

if (-not (Test-Path (Join-Path $backendDir "faa_webui.exe"))) { throw "Missing backend: $backendDir" }
if (-not (Test-Path (Join-Path $wpfDir "FAA.WpfGui.exe"))) { throw "Missing WPF exe: $wpfDir" }

Write-Host "[3/4] Stage -> $stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

Get-ChildItem $wpfDir -File | Where-Object { $_.Extension -notin ".pdb", ".xml" } |
    Copy-Item -Destination $stage
Copy-Item $backendDir (Join-Path $stage "backend") -Recurse

foreach ($doc in @("LICENSE", "THIRD_PARTY_NOTICES.md", "ASSETS.md", "README.md", "CHANGELOG.md")) {
    $src = Join-Path $root $doc
    if (Test-Path $src) { Copy-Item $src -Destination $stage }
}
# 1.0 合规: THIRD_PARTY_NOTICES 要求第三方许可文本随包分发（LGPL/Apache/MIT/BSD）
$licenses = Join-Path $root "licenses"
if (Test-Path $licenses) {
    Copy-Item $licenses (Join-Path $stage "licenses") -Recurse
}

$launcher = Join-Path $stage "start_faa.bat"
$lines = @(
    "@echo off",
    "rem FAA portable launcher: starts the WPF shell (backend is launched by the shell).",
    "start `"`" `"%~dp0FAA.WpfGui.exe`""
)
[System.IO.File]::WriteAllLines($launcher, $lines, (New-Object System.Text.UTF8Encoding($false)))

$hashes = Get-ChildItem $stage -Recurse -File |
    Get-FileHash -Algorithm SHA256 |
    ForEach-Object { $_.Hash.ToLower() + "  " + $_.Path.Substring($stage.Length + 1).Replace("\", "/") }
[System.IO.File]::WriteAllLines((Join-Path $stage "SHA256SUMS.txt"), $hashes,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host "[4/4] Zip -> $zipPath"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $stage -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
$hashFile = "$zipPath.sha256"
[System.IO.File]::WriteAllText($hashFile, "$zipHash  $(Split-Path $zipPath -Leaf)`n",
    (New-Object System.Text.UTF8Encoding($false)))

$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "OK: $zipPath ($sizeMb MB)"
Write-Host "SHA256: $zipHash"
