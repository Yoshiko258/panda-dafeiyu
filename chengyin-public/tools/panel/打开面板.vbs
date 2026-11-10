' ChengYin panel UI: ensure server is running, then open the page.
Option Explicit
Dim sh, dir
Set sh = CreateObject("WScript.Shell")
dir = "D:\chengyin\tools\panel"
sh.Run "wscript.exe """ & dir & "\open-panel.vbs""", 0, True
WScript.Sleep 1500
sh.Run "http://127.0.0.1:8899/"