@echo off
:: ============================================================================
:: Proteus — Stop all Proteus services
:: ============================================================================

title Proteus - Stop Services
color 0C
setlocal enabledelayedexpansion

echo.
echo ============================================================================
echo Stopping Proteus services...
echo ============================================================================
echo.

:: Stop uvicorn (FastAPI backend)
echo [STOP] Stopping FastAPI Backend (uvicorn)...
taskkill /f /fi "WINDOWTITLE eq Proteus - FastAPI Backend*" >nul 2>&1
taskkill /f /im uvicorn.exe >nul 2>&1
taskkill /f /fi "IMAGENAME eq python.exe" /fi "WINDOWTITLE eq Proteus - FastAPI Backend*" >nul 2>&1

:: Stop Vite frontend
echo [STOP] Stopping Frontend UI (Vite)...
taskkill /f /fi "WINDOWTITLE eq Proteus - Frontend UI*" >nul 2>&1
taskkill /f /im node.exe >nul 2>&1
taskkill /f /fi "IMAGENAME eq node.exe" /fi "WINDOWTITLE eq Proteus - Frontend UI*" >nul 2>&1

:: Stop Ollama (optional - comment out if you want to keep Ollama running)
:: echo [STOP] Stopping Ollama...
:: taskkill /f /im ollama.exe >nul 2>&1

echo.
echo [STOP] All Proteus services stopped.
echo ============================================================================
echo.
pause