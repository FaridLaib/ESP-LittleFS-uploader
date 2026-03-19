@echo off
REM -----------------------------------------------------------------------
REM Build LittleFS Uploader as a standalone .exe
REM
REM Folder structure BEFORE building:
REM
REM   LittleFS_Uploader/
REM   ├── littlefs_uploader.py
REM   ├── build.bat               (this file)
REM   └── tools/
REM       ├── esptool.exe
REM       ├── mklittlefs.exe
REM       └── libwinpthread-1.dll
REM
REM Prerequisites:
REM   pip install pyinstaller pyserial
REM   (esptool Python package NOT needed — we bundle the exe)
REM -----------------------------------------------------------------------

echo.
echo === LittleFS Uploader Build ===
echo.

REM ---- Check tools/ folder ----
set TOOLS_OK=1
set ADD_DATA=

if not exist tools\mklittlefs.exe (
    echo [!] tools\mklittlefs.exe NOT FOUND
    set TOOLS_OK=0
)
if not exist tools\esptool.exe (
    echo [!] tools\esptool.exe NOT FOUND
    set TOOLS_OK=0
)
if not exist tools\libwinpthread-1.dll (
    echo [!] tools\libwinpthread-1.dll NOT FOUND
    echo     esptool.exe may fail at runtime without this DLL.
)

if %TOOLS_OK%==0 (
    echo.
    echo WARNING: Missing tools. The exe will still build, but users
    echo          will need to browse to the missing tools manually.
    echo.
    echo Place all 3 files in a tools\ subfolder:
    echo   tools\esptool.exe
    echo   tools\mklittlefs.exe
    echo   tools\libwinpthread-1.dll
    echo.
    pause
)

if exist tools (
    set ADD_DATA=--add-data "tools;tools"
    echo Bundling tools\ folder into exe...
) else (
    echo No tools\ folder found — building without bundled tools.
)

echo.
echo Building with PyInstaller...
echo.

pyinstaller --onefile --windowed ^
    --name "LittleFS_Uploader" ^
    --icon=NONE ^
    %ADD_DATA% ^
    littlefs_uploader.py

echo.
if exist dist\LittleFS_Uploader.exe (
    echo ========================================
    echo  SUCCESS: dist\LittleFS_Uploader.exe
    echo ========================================
    echo.
    echo This is a single standalone file.
    echo No Python, no dependencies on the target machine.
    echo Just copy it anywhere and run.
) else (
    echo BUILD FAILED — check errors above.
)
echo.
pause
