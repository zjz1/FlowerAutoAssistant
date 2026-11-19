param([string]$Exe, [string]$ProcArgs)
$env:DOTNET_ROOT = Join-Path $env:LOCALAPPDATA 'Microsoft\dotnet'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$p = Start-Process -FilePath $Exe -ArgumentList $ProcArgs -PassThru
Start-Sleep -Seconds 8
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output "WINDOW-NOT-FOUND"; Stop-Process -Id $p.Id -Force; exit 1 }
$tcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Text)
$texts = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tcond)
$banner = $false; $badge = ""
foreach ($t in $texts) {
  $n = $t.Current.Name
  if ($n -match "正在运行, 设置已锁定") { $banner = $true; Write-Output ("LOCK-BANNER: " + $n) }
  if ($n -match "运行中: ") { $badge = $n; Write-Output ("RUNNING-BADGE: " + $n) }
}
$bcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
$btns = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $bcond)
foreach ($b in $btns) {
  if ($b.Current.Name -match "开始一轮") {
    Write-Output ("START-BUTTON enabled=" + (-not $b.Current.IsEnabled))
  }
  if ($b.Current.Name -eq "⚙" -or $b.Current.Name -like "*⚙*") { }
}
$cbcond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::CheckBox)
$cbs = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cbcond)
Write-Output ("CHECKBOX-COUNT: " + $cbs.Count + " (home page; disabled count follows)")
$dis = 0
foreach ($c in $cbs) { if (-not $c.Current.IsEnabled) { $dis++ } }
Write-Output ("CHECKBOX-DISABLED-COUNT: " + $dis + " (expect 1 = 运行中模块的勾选)")
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
