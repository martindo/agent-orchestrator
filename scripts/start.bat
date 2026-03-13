@echo off
echo ===================================
echo  Agent Orchestrator - Start
echo ===================================
echo.

cd /d "%~dp0.."

REM Check workspace has settings.yaml
if not exist "workspace\settings.yaml" (
    echo [INFO] No workspace found. Setting up default workspace...
    mkdir workspace\profiles 2>nul
    if exist "profiles\research-team" (
        xcopy /E /I /Y "profiles\research-team" "workspace\profiles\research-team" >nul
        echo [INFO] Copied research-team profile to workspace.
    )
    (
        echo active_profile: research-team
        echo api_keys: {}
        echo llm_endpoints:
        echo   ollama: http://ollama:11434
        echo log_level: INFO
        echo persistence_backend: file
    ) > workspace\settings.yaml
    echo [INFO] Created default settings.yaml
)

echo Starting containers...
docker compose up -d
if errorlevel 1 (
    echo [ERROR] Failed to start containers.
    pause
    exit /b 1
)

echo.
echo Waiting for database...
:waitdb
docker compose exec -T db pg_isready -U orchestrator -d agent_orchestrator >nul 2>&1
if errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto waitdb
)
echo [OK] Database ready.

echo Waiting for API...
:waitapi
curl -sf http://localhost:8000/api/v1/health >nul 2>&1
if errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto waitapi
)
echo [OK] API ready.

echo.
echo ===================================
echo  Agent Orchestrator is running!
echo ===================================
echo  API:     http://localhost:8000
echo  Docs:    http://localhost:8000/docs
echo  Ollama:  http://localhost:11434
echo ===================================
echo.
pause
