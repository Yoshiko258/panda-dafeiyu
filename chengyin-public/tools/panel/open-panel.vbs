' ChengYin panel server: start hidden, never open a browser.
Option Explicit
Dim sh, py, dir, probe
Set sh = CreateObject("WScript.Shell")
dir = "D:\chengyin\tools\panel"
py = "D:\chengyin\runtime\python\python.exe"
sh.CurrentDirectory = dir
probe = "cmd /c netstat -ano | findstr "":8899"" | findstr LISTENING >nul 2>&1"
If sh.Run(probe, 0, True) <> 0 Then
    sh.Run """" & py & """ """ & dir & "\server.py""", 0, False
End If