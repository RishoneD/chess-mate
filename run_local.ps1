# Run Chess-mate locally.
# The venv and Stockfish live outside the synced folder (under %LOCALAPPDATA%).
$ErrorActionPreference = "Stop"

$venv = Join-Path $env:LOCALAPPDATA "venvs\check-mate"
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv $venv
    & $py -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
}

if (-not $env:STOCKFISH_PATH) {
    $sf = Join-Path $env:LOCALAPPDATA "check-mate-tools\stockfish\stockfish\stockfish-windows-x86-64-universal.exe"
    if (Test-Path $sf) { $env:STOCKFISH_PATH = $sf }
}

Set-Location $PSScriptRoot
& $py -m streamlit run app.py --server.port 8501 --server.headless true @args
