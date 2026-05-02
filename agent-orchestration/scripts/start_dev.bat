@echo off
REM Development startup script (Windows)

echo Starting Agent Orchestration Service (Development Mode)...

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Start with auto-reload
uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload --log-level info
