@echo off
setlocal
title PDF Studio - install dependencies
cd /d "%~dp0"

echo ============================================================
echo   PDF Studio - dependency installer
echo ============================================================
echo.

set "PYTHON="
where py >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
if not defined PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
  echo [X] Python was not found.
  echo.
  echo     Install Python 3.12 first:
  echo       winget install -e --id Python.Python.3.12
  echo     or download it from https://www.python.org/downloads/windows/
  echo     In the installer tick: "Add python.exe to PATH"
  echo.
  pause
  exit /b 1
)

echo [1/3] Python environment (api\.venv) ...
if not exist "api\.venv\Scripts\python.exe" (
  %PYTHON% -m venv api\.venv
  if errorlevel 1 goto :error
) else (
  echo       already present
)

echo [2/3] Installing Python packages (needs internet once) ...
"api\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"api\.venv\Scripts\python.exe" -m pip install -r api\requirements.txt
if errorlevel 1 goto :error

echo [3/3] OCR engine (Tesseract) ...
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
  echo       found - scanned documents can be edited
) else (
  echo       NOT found - the app still works, but OCR of photos/scans is off.
  echo       Install it with:  winget install -e --id UB-Mannheim.TesseractOCR
)

echo.
echo ------------------------------------------------------------
echo   Ready. Double-click start.bat to run the app.
echo   It opens http://127.0.0.1:8000 in your browser.
echo ------------------------------------------------------------
echo.
pause
exit /b 0

:error
echo.
echo [X] Something failed. Check the messages above.
echo     Most common cause: no internet, or a proxy blocking pip.
echo.
pause
exit /b 1
