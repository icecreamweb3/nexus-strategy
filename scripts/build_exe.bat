@echo off
setlocal
cd /d "%~dp0\.."
set "BUILD_ENV=.build-venv-py312"
set "BUILD_PYTHON=%BUILD_ENV%\Scripts\python.exe"

if not exist "%BUILD_PYTHON%" (
    echo Checking for 64-bit Python 3.12...
    py -3.12 -c "import struct,sys; sys.exit(0 if struct.calcsize('P') * 8 == 64 else 1)" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo Python 3.12 64-bit was not found.
        echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
        echo Make sure the Python Launcher ^(py^) is enabled, then run this script again.
        exit /b 1
    )

    echo Creating isolated Python 3.12 build environment...
    py -3.12 -m venv "%BUILD_ENV%"
    if errorlevel 1 (
        echo Failed to create %BUILD_ENV%.
        exit /b 1
    )
)

echo Installing build and runtime dependencies...
"%BUILD_PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo.
    echo Failed to update packaging tools.
    exit /b 1
)

"%BUILD_PYTHON%" -m pip install --only-binary=:all: -r requirements.txt
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
