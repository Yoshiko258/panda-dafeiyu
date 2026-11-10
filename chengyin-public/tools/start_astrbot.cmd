@echo off
rem ���� AstrBot������Ŀ¼�̶��� astrbot\data����־׷�ӵ���Ŀ logs\astrbot.log
cd /d "D:\chengyin\astrbot"
set ASTRBOT_ROOT=D:\chengyin\astrbot
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
"D:\chengyin\runtime\python\python.exe" -u main.py >> "D:\chengyin\logs\astrbot.log" 2>&1
