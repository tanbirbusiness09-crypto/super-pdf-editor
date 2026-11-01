# Build a shareable Windows package of PDF Studio.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_release.ps1
#
# Produces dist\PDF-Studio-Windows-v<version>.zip containing the app code, the
# pre-built interface (so Node.js is not needed to run it), the OCR language
# data and the installation notes. Private data (uploads, assets, venv,
# node_modules, caches) is never copied.

param(
    [string]$Version = "0.1.0",
    [string]$OutDir = "dist"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$stageRoot = Join-Path $root "$OutDir\_stage"
$appDir = Join-Path $stageRoot "PDF-Studio"
$zipPath = Join-Path $root "$OutDir\PDF-Studio-Windows-v$Version.zip"

if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null

function Copy-Filtered {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string[]]$ExcludeDirs = @(),
        [string[]]$ExcludeFiles = @()
    )

    $sourcePath = (Resolve-Path -LiteralPath $Source).Path
    $files = Get-ChildItem -LiteralPath $sourcePath -Recurse -File -Force
    $copied = 0

    foreach ($file in $files) {
        $relative = $file.FullName.Substring($sourcePath.Length).TrimStart('\')
        $segments = $relative -split '\\'
        $skip = $false
        foreach ($segment in $segments) {
            if ($ExcludeDirs -contains $segment) { $skip = $true; break }
        }
        if ($skip) { continue }
        if ($ExcludeFiles -contains $file.Name) { continue }

        $target = Join-Path $Destination $relative
        $parent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        $copied++
    }
    return $copied
}

$total = 0

$total += Copy-Filtered -Source "api" -Destination (Join-Path $appDir "api") `
    -ExcludeDirs @(".venv", "__pycache__", ".mypy_cache", ".pytest_cache") `
    -ExcludeFiles @("*.pyc")

$total += Copy-Filtered -Source "web" -Destination (Join-Path $appDir "web") `
    -ExcludeDirs @("node_modules", ".next") `
    -ExcludeFiles @("tsconfig.tsbuildinfo")

$total += Copy-Filtered -Source "data\tessdata" -Destination (Join-Path $appDir "data\tessdata") `
    -ExcludeFiles @("osd.traineddata")

$total += Copy-Filtered -Source "tests" -Destination (Join-Path $appDir "tests") `
    -ExcludeDirs @("fixtures", "__pycache__") `
    -ExcludeFiles @("*.pyc")

foreach ($name in @("README.md", "INSTALL.txt", "start.bat", "dev.bat", "install.bat", ".gitignore")) {
    if (Test-Path -LiteralPath $name) {
        Copy-Item -LiteralPath $name -Destination (Join-Path $appDir $name) -Force
        $total++
    }
}

# Empty folders the app fills on first start.
foreach ($name in @("data\uploads", "data\output")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $appDir $name) | Out-Null
}

# Safety net: a release must never carry private data or build caches.
$forbidden = @("data\uploads\*\*", "data\assets\**", "data\fonts\**", "api\.venv\**",
    "web\node_modules\**", "web\.next\**", "**\*.pyc")
foreach ($pattern in $forbidden) {
    $hit = Get-ChildItem -Path $appDir -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like (Join-Path $appDir $pattern) }
    if ($hit) {
        throw "refusing to package private/build files: $($hit[0].FullName)"
    }
}

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $appDir -DestinationPath $zipPath -CompressionLevel Optimal

$zipSize = (Get-Item $zipPath).Length / 1MB
$stageSize = (Get-ChildItem $appDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB

Write-Host ""
Write-Host ("packaged {0} files, {1:N1} MB unpacked -> {2:N1} MB zip" -f $total, $stageSize, $zipSize)
Write-Host "  $zipPath"

Remove-Item $stageRoot -Recurse -Force
