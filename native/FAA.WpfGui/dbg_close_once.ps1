param([string]$Exe, [string]$ProcArgs)
$env:DOTNET_ROOT = Join-Path $env:LOCALAPPDATA 'Microsoft\dotnet'
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WE8 {
  public delegate bool EnumProc(IntPtr hwnd, IntPtr lparam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lparam);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder sb, int max);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  public delegate bool ChildProc(IntPtr hwnd, IntPtr lparam);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, ChildProc cb, IntPtr lparam);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int max);
  public static IntPtr FindMain(uint pid) {
    IntPtr f = IntPtr.Zero;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) { var c = new StringBuilder(64); GetClassName(h, c, 64);
        if (c.ToString().StartsWith("HwndWrapper")) { f = h; return false; } } return true; }, IntPtr.Zero);
    return f;
  }
  public static IntPtr FindDialog(uint pid) {
    IntPtr f = IntPtr.Zero;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) { var c = new StringBuilder(64); GetClassName(h, c, 64);
        if (c.ToString() == "#32770") { f = h; return false; } } return true; }, IntPtr.Zero);
    return f;
  }
  public static IntPtr FindOk(IntPtr dlg) {
    IntPtr f = IntPtr.Zero;
    EnumChildWindows(dlg, (h, l) => { var c = new StringBuilder(64); GetClassName(h, c, 64);
      var t = new StringBuilder(64); GetWindowText(h, t, 64);
      if (c.ToString() == "Button" && t.ToString().StartsWith("确定")) { f = h; return false; } return true; }, IntPtr.Zero);
    return f;
  }
}
'@
$p = Start-Process -FilePath $Exe -ArgumentList $ProcArgs -PassThru
Start-Sleep -Seconds 8
$main = [WE8]::FindMain([uint32]$p.Id)
if ($main -eq [IntPtr]::Zero) { Write-Output "MAIN-NOT-FOUND"; Stop-Process -Id $p.Id -Force; exit 1 }
Write-Output "MAIN-UP"
[WE8]::PostMessage($main, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
Start-Sleep -Seconds 2
$dlg = [WE8]::FindDialog([uint32]$p.Id)
if ($dlg -eq [IntPtr]::Zero) { Write-Output "DIALOG-NOT-FOUND (no confirm?)"; Stop-Process -Id $p.Id -Force; exit 1 }
Write-Output "CONFIRM-DIALOG-UP"
$ok = [WE8]::FindOk($dlg)
[WE8]::PostMessage($ok, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
Write-Output "OK-CLICKED (single shot)"
$exited = $false
for ($i = 0; $i -lt 12; $i++) {
  Start-Sleep -Seconds 1
  if (-not (Get-Process -Id $p.Id -ErrorAction SilentlyContinue)) { $exited = $true; Write-Output ("APP-EXITED after ~" + ($i+1) + "s (FIRST close attempt)"); break }
}
if (-not $exited) { Write-Output "APP-STILL-ALIVE (needs second X = bug)"; Stop-Process -Id $p.Id -Force }
