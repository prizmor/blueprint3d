# Blueprint3D setup for Windows: creates venv\ in the repository root (Python 3.12, build123d/OpenCascade,
# numpy, scipy) and checks that Blender and a headless browser can be found.
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# Python: uv is used when found (BP3D_UV or PATH) and installs Python 3.12 into .python\ by itself;
# otherwise the py launcher / python 3.10-3.13 from PATH is used.
$ErrorActionPreference = "Stop"
$Repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Venv = Join-Path $Repo "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Req = Join-Path $Repo "requirements.txt"

function Run { param([string]$Exe, [string[]]$A) & $Exe @A; if ($LASTEXITCODE -ne 0) { throw "Failed: $Exe $A" } }

# 1. Bodies are stored in Git LFS: a clone without LFS has text pointers instead of .blend files.
$Body = Join-Path $Repo "bodies\mannequin_f\mannequin_f.blend"
if ((Test-Path $Body) -and (Get-Item $Body).Length -lt 1024) {
    Write-Host "bodies/*.blend are Git LFS pointers - fetching them (git lfs pull)"
    Push-Location $Repo
    try { Run "git" @("lfs", "install", "--local"); Run "git" @("lfs", "pull") } finally { Pop-Location }
}

# 2. Python environment.
$Uv = $env:BP3D_UV
if (-not $Uv) { $c = Get-Command uv -ErrorAction SilentlyContinue; if ($c) { $Uv = $c.Source } }
if ($Uv) {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Repo ".python"
    Run $Uv @("python", "install", "3.12")
    if (-not (Test-Path $Py)) { Run $Uv @("venv", "--python", "3.12", $Venv) }
    Run $Uv @("pip", "install", "--python", $Py, "-r", $Req)
} else {
    if (-not (Test-Path $Py)) {
        $Base = $null
        if (Get-Command py -ErrorAction SilentlyContinue) {
            foreach ($v in "3.12", "3.13", "3.11", "3.10") {
                & py "-$v" -c "import sys" 2>$null
                if ($LASTEXITCODE -eq 0) { $Base = @("py", "-$v"); break }
            }
        }
        if (-not $Base -and (Get-Command python -ErrorAction SilentlyContinue)) {
            & python -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)"
            if ($LASTEXITCODE -eq 0) { $Base = @("python") }
        }
        if (-not $Base) { throw "Python 3.10-3.13 not found. Install Python 3.12 or uv (https://docs.astral.sh/uv/) and run again." }
        $Exe = $Base[0]; $Args0 = @(); if ($Base.Count -gt 1) { $Args0 = $Base[1..($Base.Count - 1)] }
        Run $Exe ($Args0 + @("-m", "venv", $Venv))
    }
    Run $Py @("-m", "pip", "install", "--upgrade", "pip")
    Run $Py @("-m", "pip", "install", "-r", $Req)
}
Run $Py @("-c", "import build123d; print('build123d', build123d.__version__)")

# 3. External programs: Blender for the 3D stage, a Chromium-based browser for PNG/PDF of the sheet.
$env:PYTHONPATH = $Repo
& $Py -c "from bp3d.build import find_blender; print('Blender:', find_blender())"
if ($LASTEXITCODE -ne 0) { Write-Warning "Blender 5.3 not found - drawings work, build/render/posetest do not. Set BP3D_BLENDER to blender.exe." }
& $Py -c "from bp3d.__main__ import browser; b = browser(); print('Browser:', b or 'NOT FOUND'); raise SystemExit(0 if b else 1)"
if ($LASTEXITCODE -ne 0) { Write-Warning "Edge/Chrome/Chromium not found - drawings are written as SVG only. Set BP3D_BROWSER." }

Write-Host "Blueprint3D ready: $Venv"
Write-Host "Check the tool:  `$env:PYTHONPATH=`"$Repo`"; & `"$Py`" -m bp3d selftest"
