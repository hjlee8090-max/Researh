# 주식 오토플로우 - 단일 프롬프트 실행기
# 사용법: powershell -File run_prompt.ps1 -PromptName 0900_pre_market
# 또는:  powershell -File run_prompt.ps1 -PromptName 1800_report

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("0000_global", "0900_pre_market", "1200_midday", "1500_close", "1800_report", "saturday_review", "sunday_strategy", "weekend_report")]
    [string]$PromptName
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PromptPath = Join-Path $ProjectRoot "prompts\$PromptName.md"
$LogDir = Join-Path $ProjectRoot "state\run_logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Today = Get-Date -Format "yyyy-MM-dd"
$Stamp = Get-Date -Format "HHmmss"
$LogFile = Join-Path $LogDir "$Today`_$PromptName`_$Stamp.log"

if (-not (Test-Path $PromptPath)) {
    "ERROR: prompt file not found at $PromptPath" | Tee-Object -FilePath $LogFile
    exit 1
}

$PromptContent = Get-Content -Path $PromptPath -Raw -Encoding UTF8

# Claude Code CLI 실행
# - 작업 디렉토리를 프로젝트 루트로
# - 프롬프트는 stdin으로 전달
# - 권한 모드는 acceptEdits (기본 편집은 자동, 위험 작업은 확인)
# - 출력은 로그 파일로 캡처
# 참고: claude CLI의 정확한 옵션은 버전마다 다를 수 있음. 환경에 맞춰 조정.
Push-Location $ProjectRoot
try {
    "=== Run: $PromptName @ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $LogFile -Encoding utf8
    $PromptContent | & claude --print --permission-mode acceptEdits 2>&1 | Tee-Object -FilePath $LogFile -Append
    $exit = $LASTEXITCODE
    "=== Exit: $exit @ $(Get-Date -Format 'HH:mm:ss') ===" | Out-File -FilePath $LogFile -Encoding utf8 -Append
    exit $exit
} finally {
    Pop-Location
}
