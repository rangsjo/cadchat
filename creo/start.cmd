@echo off
rem cadchat + Creo in one command (Windows).
rem   creo\start.cmd                  install what is missing, start cadchat and Creo, connect, open the viewer
rem   creo\start.cmd doctor           only check every prerequisite and say what to fix
rem   creo\start.cmd --no-launch      attach to a Creo that is already running instead of starting one
rem   creo\start.cmd --creo "C:\Program Files\PTC\Creo 10.0.5.0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
exit /b %ERRORLEVEL%
