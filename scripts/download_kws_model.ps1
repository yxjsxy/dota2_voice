Param(
    [string]$ModelUrl = "https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2",
    [string]$OutDir = "kws_model"
)

$ErrorActionPreference = "Stop"

Write-Host "[KWS] Downloading model..." -ForegroundColor Cyan
Write-Host "URL: $ModelUrl"

$root = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $root $OutDir
$tmpDir = Join-Path $env:TEMP ("dota2_kws_" + [Guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tmpDir (Split-Path $ModelUrl -Leaf)

New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

try {
    Invoke-WebRequest -Uri $ModelUrl -OutFile $archivePath

    Write-Host "[KWS] Extracting..." -ForegroundColor Cyan
    if ($archivePath -match "\.zip$") {
        Expand-Archive -Path $archivePath -DestinationPath $tmpDir -Force
    }
    elseif ($archivePath -match "\.tar\.bz2$" -or $archivePath -match "\.tbz2$") {
        tar -xjf $archivePath -C $tmpDir
    }
    elseif ($archivePath -match "\.tar\.gz$" -or $archivePath -match "\.tgz$") {
        tar -xzf $archivePath -C $tmpDir
    }
    else {
        throw "Unsupported archive format: $archivePath"
    }

    $encoder = Get-ChildItem -Path $tmpDir -Recurse -Filter "encoder*.onnx" | Select-Object -First 1
    $decoder = Get-ChildItem -Path $tmpDir -Recurse -Filter "decoder*.onnx" | Select-Object -First 1
    $joiner  = Get-ChildItem -Path $tmpDir -Recurse -Filter "joiner*.onnx"  | Select-Object -First 1
    $tokens  = Get-ChildItem -Path $tmpDir -Recurse -Filter "tokens.txt"    | Select-Object -First 1

    if (-not $encoder -or -not $decoder -or -not $joiner -or -not $tokens) {
        throw "Model archive missing required files. Need encoder*.onnx/decoder*.onnx/joiner*.onnx/tokens.txt"
    }

    Copy-Item $encoder.FullName (Join-Path $targetDir $encoder.Name) -Force
    Copy-Item $decoder.FullName (Join-Path $targetDir $decoder.Name) -Force
    Copy-Item $joiner.FullName  (Join-Path $targetDir $joiner.Name)  -Force
    Copy-Item $tokens.FullName  (Join-Path $targetDir "tokens.txt") -Force

    Write-Host "[KWS] Model ready at: $targetDir" -ForegroundColor Green
    Write-Host "[KWS] Files:"
    Get-ChildItem $targetDir | Select-Object Name, Length
}
finally {
    if (Test-Path $tmpDir) {
        Remove-Item -Path $tmpDir -Recurse -Force
    }
}
