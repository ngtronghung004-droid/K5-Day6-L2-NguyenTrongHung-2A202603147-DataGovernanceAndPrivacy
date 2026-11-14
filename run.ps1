# One-command reproduce on Windows for Group AA1
param(
    [string]$Track = "t02"
)

$ErrorActionPreference = "Stop"
$python = "C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe"

Write-Host "=== 1. Checking Preflight Environment ===" -ForegroundColor Cyan
& $python -m tools.preflight

Write-Host "`n=== 2. Running PoC Pipeline (Offline, Seed 42) ===" -ForegroundColor Cyan
& $python -m src.main --config configs/lab.yaml --track $Track --output out/poc --run-name poc --offline --seed 42

Write-Host "`n=== 3. Running Group AA1 Unit Tests ===" -ForegroundColor Cyan
& $python -m pytest tests/test_t02_aa1.py -v

Write-Host "`n=== Complete! All contract artifacts generated in out/poc/ ===" -ForegroundColor Green
