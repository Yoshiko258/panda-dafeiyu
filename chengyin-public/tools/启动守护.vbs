' Background watchdog launcher (no window at all).
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\chengyin"
sh.Run """D:\chengyin\runtime\python\pythonw.exe"" ""D:\chengyin\tools\supervisor.py""", 0, False
