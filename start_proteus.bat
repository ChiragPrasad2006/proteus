@echo off
:: ============================================================================
:: Proteus — The Local-First AI Email Agent That Becomes You, Over Time
:: One-click Windows launcher for the complete Proteus stack
:: ============================================================================

title Proteus Launcher
color 0A
setlocal enabledelayedexpansion

:: ----------------------------------------------------------------------------
:: Configuration
:: ----------------------------------------------------------------------------
set "VENV_PYTHON=D:\MLops\.venv\Scripts\python.exe"
set "BACKEND_MODULE=backend.main:app"
set "BACKEND_HOST=127.0.0.1"
set "BACKEND_PORT=8000"
set "FRONTEND_DIR=%~dp0frontend"
set "FRONTEND_PORT=5173"
set "OLLAMA_URL=http://localhost:11434"
set "OLLAMA_MODEL=qwen3:8b"
set "HEALTH_ENDPOINT=http://%BACKEND_HOST%:%BACKEND_PORT%/api/health"

:: Step 1: Environment & Cache Safety
echo.
echo ============================================================================
echo [1/4] Checking Ollama & %OLLAMA_MODEL%...
echo ============================================================================
echo.

if exist "D:\" (
    set "HF_HOME=D:\huggingface_cache"
    echo [ENV] HF_HOME set to D:\huggingface_cache
) else (
    echo [ENV] D:\ drive not found, using default HF cache location
)

set "EMAIL_WRITER_LOCAL_DATA_DIR=%~dp0local_user_data"
if not exist "%EMAIL_WRITER_LOCAL_DATA_DIR%" mkdir "%EMAIL_WRITER_LOCAL_DATA_DIR%" 2>nul
echo [ENV] EMAIL_WRITER_LOCAL_DATA_DIR set to %EMAIL_WRITER_LOCAL_DATA_DIR%

:: ----------------------------------------------------------------------------
:: Step 2: Check/Start Ollama & Verify Model
:: ----------------------------------------------------------------------------
echo.
echo [OLLAMA] Checking if Ollama is running on %OLLAMA_URL%...

:: Try to reach Ollama API
curl -s -f --max-time 3 "%OLLAMA_URL%/api/tags" >nul 2>&1
if %errorlevel% neq 0 (
    echo [OLLAMA] Ollama not responding. Starting Ollama server...
    start "Proteus - Ollama Runtime" /min cmd /c "ollama serve"
    
    echo [OLLAMA] Waiting for Ollama API to become available...
    set "OLLAMA_READY=0"
    for /l %%i in (1,1,30) do (
        curl -s -f --max-time 2 "%OLLAMA_URL%/api/tags" >nul 2>&1
        if !errorlevel! equ 0 (
            set "OLLAMA_READY=1"
            goto :ollama_ready
        )
        echo [OLLAMA] Waiting... (%%i/30)
        timeout /t 2 /nobreak >nul
    )
    :ollama_ready
    if "%OLLAMA_READY%" neq "1" (
        echo.
        echo [ERROR] Ollama failed to start within 60 seconds.
        echo [ERROR] Please start Ollama manually: ollama serve
        pause
        exit /b 1
    )
    echo [OLLAMA] Ollama API is now responding.
) else (
    echo [OLLAMA] Ollama is already running.
)

:: Verify model is pulled
echo [OLLAMA] Checking for model %OLLAMA_MODEL%...
ollama list | findstr /r /c:"^%OLLAMA_MODEL% " >nul 2>&1
if %errorlevel% neq 0 (
    echo [OLLAMA] Model %OLLAMA_MODEL% not found. Pulling...
    ollama pull %OLLAMA_MODEL%
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] Failed to pull %OLLAMA_MODEL%.
        echo [ERROR] Please run manually: ollama pull %OLLAMA_MODEL%
        pause
        exit /b 1
    )
    echo [OLLAMA] Model %OLLAMA_MODEL% pulled successfully.
) else (
    echo [OLLAMA] Model %OLLAMA_MODEL% is already available.
)

:: ----------------------------------------------------------------------------
:: Step 3: Start FastAPI Backend
:: ----------------------------------------------------------------------------
echo.
echo ============================================================================
echo [2/4] Starting FastAPI Backend...
echo ============================================================================
echo.

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python not found at %VENV_PYTHON%
    echo [ERROR] Please verify the virtual environment path.
    pause
    exit /b 1
)

echo [BACKEND] Launching uvicorn on http://%BACKEND_HOST%:%BACKEND_PORT%...
start "Proteus - FastAPI Backend" cmd /k "%VENV_PYTHON% -m uvicorn %BACKEND_MODULE% --host %BACKEND_HOST% --port %BACKEND_PORT%"

echo [BACKEND] Waiting for health endpoint %HEALTH_ENDPOINT%...
set "BACKEND_READY=0"
for /l %%i in (1,1,30) do (
    curl -s -f --max-time 2 "%HEALTH_ENDPOINT%" >nul 2>&1
    if !errorlevel! equ 0 (
        set "BACKEND_READY=1"
        goto :backend_ready
    )
    echo [BACKEND] Waiting... (%%i/30)
    timeout /t 2 /nobreak >nul
)
:backend_ready
if "%BACKEND_READY%" neq "1" (
    echo.
    echo [ERROR] FastAPI backend failed to start within 60 seconds.
    echo [ERROR] Check the 'Proteus - FastAPI Backend' window for errors.
    pause
    exit /b 1
)
echo [BACKEND] Backend is healthy at %HEALTH_ENDPOINT%

:: ----------------------------------------------------------------------------
:: Step 4: Start Vite Frontend & Open Browser
:: ----------------------------------------------------------------------------
echo.
echo ============================================================================
echo [3/4] Starting Proteus UI...
echo ============================================================================
echo.

if not exist "%FRONTEND_DIR%\package.json" (
    echo [ERROR] Frontend directory not found at %FRONTEND_DIR%
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo [FRONTEND] node_modules not found. Running npm install...
    cd /d "%FRONTEND_DIR%"
    npm install
    if %errorlevel% neq 0 (
        echo.
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
    cd /d "%~dp0"
    echo [FRONTEND] Dependencies installed.
) else (
    echo [FRONTEND] Dependencies already installed.
)

echo [FRONTEND] Launching Vite dev server on http://localhost:%FRONTEND_PORT%...
start "Proteus - Frontend UI" cmd /k "cd /d %FRONTEND_DIR% && npm run dev"

echo [FRONTEND] Waiting for Vite to compile...
timeout /t 3 /nobreak >nul

echo [FRONTEND] Opening browser at http://localhost:%FRONTEND_PORT%...
start "" "http://localhost:%FRONTEND_PORT%"

:: ----------------------------------------------------------------------------
:: Success
:: ----------------------------------------------------------------------------
echo.
echo ============================================================================
echo [4/4] Proteus is live!
echo ============================================================================
echo.
echo   Backend API : http://%BACKEND_HOST%:%BACKEND_PORT%
echo   Frontend UI : http://localhost:%FRONTEND_PORT%
echo   API Health  : %HEALTH_ENDPOINT%
echo   Ollama      : %OLLAMA_URL% (model: %OLLAMA_MODEL%)
echo.
echo Press Ctrl+C in the backend/frontend windows to stop services.
echo This launcher window can be closed.
echo ============================================================================
echo.

pause