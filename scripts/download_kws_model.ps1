Param(
    [Parameter(Mandatory = $true)]
    [string]$ModelZipUrl,

    [string]$OutDir = "kws_model"
)

$ErrorActionPreference = "Stop"

Write-Host "[KWS] Downloading model..." -ForegroundColor Cyan
Write-Host "URL: $ModelZipUrl"

$root = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $root $OutDir
$tmpDir = Join-Path $env:TEMP ("dota2_kws_" + [Guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tmpDir "model.zip"

New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

try {
    Invoke-WebRequest -Uri $ModelZipUrl -OutFile $zipPath

    Write-Host "[KWS] Extracting..." -ForegroundColor Cyan
    Expand-Archive -Path $zipPath -DestinationPath $tmpDir -Force

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
    Copy-Item $tokens.FullName  (Join-Path $targetDir "tokens.txt")   -Force

    Write-Host "[KWS] Model ready at: $targetDir" -ForegroundColor Green
    Write-Host "[KWS] Files:"
    Get-ChildItem $targetDir | Select-Object Name, Length
}
finally {
    if (Test-Path $tmpDir) {
        Remove-Item -Path $tmpDir -Recurse -Force
    }
}
