@echo off
setlocal
title PDF Studio
cd /d "%~dp0"

if not exist "api\.venv\Scripts\python.exe" (
  echo [1/3] Creating Python environment...
  py -m venv api\.venv
  if errorlevel 1 goto :error
  "api\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
  "api\.venv\Scripts\python.exe" -m pip install -r api\requirements.txt --quiet
  if errorlevel 1 goto :error
)

if not exist "web\out\index.html" (
  echo [2/3] Building the interface, first run only. This can take a few minutes...
  pushd web
  if not exist "node_modules" call npm install
  if errorlevel 1 (popd & goto :error)
  call npm run build
  if errorlevel 1 (popd & goto :error)
  popd
)

echo [3/3] Starting PDF Studio at http://127.0.0.1:8000
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"
"api\.venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo Setup failed. Please check the messages above.
pause
