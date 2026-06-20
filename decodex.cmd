@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON_EXE="

if defined DECODEX_PYTHON set "PYTHON_EXE=%DECODEX_PYTHON%"
if not defined PYTHON_EXE if defined PYTHON set "PYTHON_EXE=%PYTHON%"
if not defined PYTHON_EXE if defined PYTHON3 set "PYTHON_EXE=%PYTHON3%"

if not defined PYTHON_EXE (
  for %%I in (python.exe python3.exe) do (
    if not defined PYTHON_EXE for %%J in (%%I) do set "PYTHON_EXE=%%~$PATH:J"
  )
)

if not defined PYTHON_EXE (
  echo No usable Python interpreter found.
  exit /b 1
)

"%PYTHON_EXE%" "%ROOT%tools\decodex.py" %*
exit /b %ERRORLEVEL%
