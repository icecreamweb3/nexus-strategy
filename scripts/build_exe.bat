@echo off
setlocal
cd /d "%~dp0\.."
set "BUILD_PYTHON=.build-venv\Scripts\python.exe"

if not exist "%BUILD_PYTHON%" (
    echo Creating isolated Windows build environment...
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv .build-venv
    ) else (
        py -3 -m venv .build-venv
    )
    if errorlevel 1 (
        echo Failed to create .build-venv. Please install Python 3.
        exit /b 1
    )
)

echo Installing build and runtime dependencies...
"%BUILD_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed.
    exit /b 1
)

echo Building executable...
"%BUILD_PYTHON%" scripts\build_exe.py %*

if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build completed successfully.
endlocal
