# 시연용 복사본(demo_run/)을 처음 상태로 만든다. 실제 workbook/ 은 건드리지 않는다.
#   사용: powershell -File scripts/prepare_demo.ps1
# 시연 중 모든 명령에 --root demo_run 을 붙이면 이 복사본에서만 실행된다.
# 촬영을 다시 하려면 이 스크립트를 다시 실행한다(복사본이 지워지고 현재 workbook/ 상태로 새로 만들어진다).

$root = Split-Path $PSScriptRoot -Parent
$dest = Join-Path $root "demo_run"

if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory $dest | Out-Null
foreach ($d in "workbook", "data", ".claude") {
    Copy-Item (Join-Path $root $d) (Join-Path $dest $d) -Recurse
}

# 시연에서 텔레그램으로 새로 받을 8주차 메모가 남아 있으면 지운다
Remove-Item (Join-Path $dest "data\updates\week08.md") -ErrorAction SilentlyContinue

# 출력 문구는 영문으로 둔다(BOM 없는 UTF-8 한글을 Windows PowerShell 5 가 깨뜨리기 때문)
Write-Host "Demo copy created: $dest"
Write-Host "  memos: $((Get-ChildItem (Join-Path $dest 'data\updates') -Filter 'week*.md' | ForEach-Object { $_.BaseName }) -join ', ')"
Write-Host "  next:  python src/pm_agent.py quality --week 7 --root demo_run"
