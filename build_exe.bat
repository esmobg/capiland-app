@echo off
chcp 65001 >nul
rem ===================================================================
rem  Прави самостоятелен Kapilands-Taymer.exe в папката dist\
rem ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/3] Проверка на зависимостите...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

echo [2/3] Тестове...
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
    --add-binary "vendor\nvda\x64\nvdaControllerClient.dll;vendor\nvda\x64" ^
    --add-data "vendor\nvda\license.txt;vendor\nvda" ^
    --add-data "vendor\nvda\README.md;vendor\nvda" ^
    --hidden-import "kapiland.wxui.app" ^
    --hidden-import "comtypes.client" ^
    --exclude-module "tkinter" ^
    main.py
if errorlevel 1 goto :error

echo.
echo ГОТОВО: "%cd%\dist\Kapilands-Taymer.exe"
echo Данните се пазят в %%APPDATA%%\KapilandsTimer.
echo.
pause
exit /b 0

:error
echo.
echo Нещо се обърка. Прочети съобщението по-горе.
echo.
pause
exit /b 1
