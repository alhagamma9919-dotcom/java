@echo off
title ComfyUI
setlocal
set "COMFY=C:\ComfyUI"
set "PORT=8188"
set "URL=http://127.0.0.1:%PORT%"
set "CFG=%~dp0config.json"
if not exist "%CFG%" set "CFG=C:\src\java\comfy-remote\config.json"

rem Already running (e.g. started from the phone)? Just open it.
powershell -NoProfile -Command "try { iwr %URL%/system_stats -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
  echo ComfyUI is already running. Opening %URL% ...
  start "" %URL%
  timeout /t 3 >nul
  exit /b
)

rem Same extra arguments as the phone launcher (config.json -> comfy_args)
set "ARGS=--preview-method auto"
for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "try { $c = Get-Content '%CFG%' -Raw | ConvertFrom-Json; if ($c.comfy_args) { $c.comfy_args -join ' ' } else { '--preview-method auto' } } catch { '--preview-method auto' }"`) do set "ARGS=%%a"

echo Starting ComfyUI with: %ARGS%
echo The browser opens by itself when it is ready. Close this window to stop ComfyUI.
echo.

rem Open the browser as soon as ComfyUI answers
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "for ($i = 0; $i -lt 300; $i++) { try { iwr %URL%/system_stats -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process '%URL%'; break } catch { Start-Sleep 2 } }"

cd /d "%COMFY%"
"%COMFY%\venv\Scripts\python.exe" main.py --listen 127.0.0.1 --port %PORT% %ARGS%
echo.
echo ComfyUI stopped.
pause
