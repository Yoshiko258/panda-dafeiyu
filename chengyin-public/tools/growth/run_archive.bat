@echo off
cd /d D:\chengyin
"D:\chengyin\runtime\python\python.exe" "D:\chengyin\tools\growth\archive.py" >> "D:\chengyin\logs\archive.log" 2>&1
"D:\chengyin\runtime\python\python.exe" "D:\chengyin\tools\cleanup_media.py" --apply >> "D:\chengyin\logs\archive.log" 2>&1