@echo off
echo =======================================================
echo   Real-Time Anti-Mule & Fraud Intelligence Solution
echo =======================================================
echo.
echo 1. Checking if Docker is running...
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Docker Desktop is not running yet.
    echo [*] Please launch Docker Desktop from your Start Menu or Desktop.
    echo [*] Once Docker Desktop says 'Engine running', press any key to continue...
    pause
)

echo.
echo 2. Building and starting all microservices with Docker Compose...
docker compose up --build

echo.
pause
