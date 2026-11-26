# Installs MPFB (MakeHuman Plugin For Blender: GPL code, CC0 core assets) into an isolated Blender profile
# .mpfb\blender_user in the repository root - your own Blender profile is not touched. Needed only to REBUILD
# the mannequin (python -m bp3d mannequin); the built body bodies\mannequin_f\mannequin_f.blend is in git.
# Source: official Blender Extensions platform, hash-pinned. Another profile with MPFB: set BP3D_MPFB instead.
$ErrorActionPreference = "Stop"
$Repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Dir = Join-Path $Repo ".mpfb"
$Zip = Join-Path $Dir "download\add-on-mpfb-v2.0.18.zip"
$Sha = "c075b3e9b94b8e5556a5f03f4653602d02ea306de08126e8f55ed6dee28a2dad"
$Url = "https://extensions.blender.org/download/sha256:$Sha/add-on-mpfb-v2.0.18.zip"
$Blender = $env:BP3D_BLENDER
if (-not $Blender) {
    foreach ($c in "C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
                   "C:\Program Files\Blender Foundation\Blender 5.3\blender.exe") {
        if (Test-Path $c) { $Blender = $c; break }
    }
}
if (-not $Blender) { $c = Get-Command blender -ErrorAction SilentlyContinue; if ($c) { $Blender = $c.Source } }
if (-not $Blender -or -not (Test-Path $Blender)) { throw "Blender not found: set BP3D_BLENDER" }

New-Item -ItemType Directory -Force (Join-Path $Dir "download") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Dir "blender_user") | Out-Null
if (-not (Test-Path $Zip)) { Invoke-WebRequest -Uri $Url -OutFile $Zip }
$Got = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
if ($Got -ne $Sha) { throw "MPFB archive hash mismatch: $Got" }
$env:BLENDER_USER_RESOURCES = Join-Path $Dir "blender_user"
& $Blender --command extension install-file -r user_default --enable $Zip
if ($LASTEXITCODE -ne 0) { throw "MPFB install failed" }
Write-Host "MPFB ready: $Dir (rebuild the mannequin with: python -m bp3d mannequin)"
