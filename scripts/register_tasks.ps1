# 주식 오토플로우 - Windows 작업스케줄러 등록 스크립트
# 1회 실행하면 평일 09/12/15/18시에 자동 실행되는 작업 4개가 등록된다.
#
# 실행:  관리자 권한 PowerShell에서
#        powershell -ExecutionPolicy Bypass -File register_tasks.ps1
#
# 해제:  powershell -File register_tasks.ps1 -Unregister

param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunnerPath  = Join-Path $ProjectRoot "scripts\run_prompt.ps1"
$TaskFolder  = "\주식오토플로우"

$Slots = @(
    @{ Name = "주식_0030_글로벌점검"; Time = "00:30"; Prompt = "0000_global"; Days = @("Monday","Tuesday","Wednesday","Thursday","Friday") }
    @{ Name = "주식_0900_개장점검";  Time = "09:00"; Prompt = "0900_pre_market"; Days = @("Monday","Tuesday","Wednesday","Thursday","Friday") }
    @{ Name = "주식_1200_장중점검";  Time = "12:00"; Prompt = "1200_midday"; Days = @("Monday","Tuesday","Wednesday","Thursday","Friday") }
    @{ Name = "주식_1500_마감점검";  Time = "15:00"; Prompt = "1500_close"; Days = @("Monday","Tuesday","Wednesday","Thursday","Friday") }
    @{ Name = "주식_1800_일일리포트"; Time = "18:00"; Prompt = "1800_report"; Days = @("Monday","Tuesday","Wednesday","Thursday","Friday") }
    @{ Name = "주식_토요일_사후분석"; Time = "18:00"; Prompt = "saturday_review"; Days = @("Saturday") }
    @{ Name = "주식_일요일_다음주전략"; Time = "18:00"; Prompt = "sunday_strategy"; Days = @("Sunday") }
)

if ($Unregister) {
    foreach ($s in $Slots) {
        $path = "$TaskFolder\$($s.Name)"
        try {
            Unregister-ScheduledTask -TaskName $s.Name -TaskPath "$TaskFolder\" -Confirm:$false -ErrorAction Stop
            Write-Host "Removed: $path"
        } catch {
            Write-Host "Skip (not found): $path"
        }
    }
    return
}

if (-not (Test-Path $RunnerPath)) {
    Write-Error "Runner not found: $RunnerPath"
    return
}

foreach ($s in $Slots) {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunnerPath`" -PromptName $($s.Prompt)" `
        -WorkingDirectory $ProjectRoot

    # 평일(월~금) 매일 지정 시각
    $trigger = New-ScheduledTaskTrigger -Weekly `
        -DaysOfWeek $s.Days `
        -At $s.Time

    # PC가 꺼져있어 누락된 경우 다음 부팅 시 즉시 보강 실행
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -WakeToRun `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -MultipleInstances IgnoreNew

    # 현재 사용자로 대화형 실행 (Claude Code GUI/CLI 권한 사용)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Limited

    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
            -Description "주식 오토플로우 - $($s.Prompt) ($($s.Time) 평일)"

    Register-ScheduledTask -TaskName $s.Name -TaskPath $TaskFolder -InputObject $task -Force | Out-Null
    Write-Host "Registered: $TaskFolder\$($s.Name)  @ 평일 $($s.Time)"
}

Write-Host ""
Write-Host "확인: 작업스케줄러(taskschd.msc) → 작업 스케줄러 라이브러리 → 주식오토플로우 폴더"
Write-Host "해제: powershell -File register_tasks.ps1 -Unregister"
