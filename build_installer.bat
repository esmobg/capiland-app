@echo off
chcp 65001 >nul
rem ===================================================================
rem  Прави инсталатора dist\Kapilands-Taymer-2.1-Setup.exe
rem  Нужни са: готов dist\Kapilands-Taymer.exe (build_exe.bat) и Inno Setup 6.
rem ===================================================================
setlocal
cd /d "%~dp0"

if not exist "dist\Kapilands-Taymer.exe" (
    echo Няма dist\Kapilands-Taymer.exe - първо пусни build_exe.bat.
    goto :error
)

set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Не намирам Inno Setup 6. Инсталирай го от https://jrsoftware.org/isinfo.php
    goto :error
)

"%ISCC%" /Q "installer\kapilands.iss"
if errorlevel 1 goto :error

echo.
echo ГОТОВО: "%cd%\dist\Kapilands-Taymer-2.1-Setup.exe"
echo.
pause
exit /b 0

:error
echo.
pause
exit /b 1
