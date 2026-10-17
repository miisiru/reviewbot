@echo off
setlocal
cd /d "%~dp0"

set "HSR_EXCEL=%~dp0data\TurnBasedGameData\ExcelOutput"
set "HSR_TEXTMAP=%~dp0data\TurnBasedGameData\TextMap"

if not exist "%HSR_EXCEL%\EquipmentConfig.json" (
    echo ERROR: EquipmentConfig.json is missing.
    echo Download the ExcelOutput game-data folder first.
    pause
    exit /b 1
)

set "INPUT=%~dp0submissions.json"
if not "%~1"=="" set "INPUT=%~f1"

if not exist "%INPUT%" (
    echo ERROR: Submission file not found: "%INPUT%"
    pause
    exit /b 1
)

python -u tools\run_local.py "%INPUT%" --watch --poll 10
set "RESULT=%ERRORLEVEL%"

echo.
echo Finished with exit code %RESULT%.
pause
exit /b %RESULT%