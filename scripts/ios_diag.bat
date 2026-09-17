@echo off
title TestHub iOS Diagnostic
REM ============================================================
REM Double-click launcher for ios_diag.ps1.
REM
REM Run this ON THE PC THE IPHONE IS PLUGGED INTO when either:
REM   * ios_wda_host.bat hangs with no result, or
REM   * you just moved to a NEW PC and want to know what is
REM     missing before running the launcher.
REM
REM It is read-only: it starts nothing and kills nothing.
REM ASCII-only, CRLF.
REM ============================================================

echo ============================================
echo  TestHub - iOS diagnostic [read only]
echo ============================================
echo  Checks: Apple certs / go-ios version / DDI cache
echo          device / ports / WDA / TestHub server
echo.

set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ios_diag.ps1""

REM Prefer a normal window first; if it is blocked, fall back to elevation.
REM The elevated copy runs in its own window, so it must NOT be given
REM TESTHUB_NOPAUSE - we want it to keep the report on screen.
net session >nul 2>nul
if %errorlevel% equ 0 (
    %PS%
) else (
    echo Requesting administrator rights ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -Verb RunAs -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0ios_diag.ps1'"
)

echo.
echo Done. If a report was requested, copy everything above.
pause
exit /b 0
