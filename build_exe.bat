@echo off
chcp 65001 >nul
rem ===================================================================
rem  Прави самостоятелен Kapilands-Taymer.exe в папката dist\
rem  Стартирай с двоен клик или от командния ред.
rem ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/3] Проверка на PyInstaller...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo      Липсва - инсталирам го...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 goto :error
)

echo [2/3] Пробен пуск на тестовете...
python -m unittest discover -s tests -t . -q
if errorlevel 1 (
    echo.
    echo      ВНИМАНИЕ: тестовете не минават. Билдът продължава въпреки това.
    echo.
)

echo [3/3] Компилиране...
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "Kapilands-Taymer" ^
    --paths "." ^
    --hidden-import "kapiland.ui.app" ^
    main.py
if errorlevel 1 goto :error

echo.
echo ГОТОВО. Файлът е: "%cd%\dist\Kapilands-Taymer.exe"
echo Може да го преместиш където искаш - данните се пазят в %%APPDATA%%\KapilandsTimer.
echo.
pause
exit /b 0

:error
echo.
echo Нещо се обърка. Прочети съобщението по-горе.
echo.
pause
exit /b 1
