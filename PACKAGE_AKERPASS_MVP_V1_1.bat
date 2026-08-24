@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "RELEASE_DIR=release"
set "PACKAGE_NAME=akerpass_mvp_v1_1_candidate.zip"
set "PACKAGE_PATH=%RELEASE_DIR%\%PACKAGE_NAME%"
set "HASH_PATH=%RELEASE_DIR%\%PACKAGE_NAME%.sha256.txt"

echo ==============================================================================
echo AkerPass MVP v1.1 - verifiera och paketera HTTPS-kandidat
echo ==============================================================================

py -3 src\43_verify_akerpass_web_v1.py
if errorlevel 1 goto :fail

if not exist "dist\index.html" (
  echo FEL: dist\index.html saknas. Kor CHECK_AKERPASS_MVP_V1_1.bat forst.
  goto :fail
)

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
if exist "%PACKAGE_PATH%" del "%PACKAGE_PATH%"
if exist "%HASH_PATH%" del "%HASH_PATH%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'dist\*' -DestinationPath '%PACKAGE_PATH%' -CompressionLevel Optimal; $h=(Get-FileHash -Algorithm SHA256 '%PACKAGE_PATH%').Hash.ToLowerInvariant(); Set-Content -Encoding ascii '%HASH_PATH%' ($h + '  %PACKAGE_NAME%'); Write-Host ('SHA256: ' + $h)"
if errorlevel 1 goto :fail

echo.
echo PAKET KLART:
echo   %PACKAGE_PATH%
echo   %HASH_PATH%
echo.
echo Extrahera ZIP-filen i _candidate_v1_1 pa one.com.
echo Den befintliga livesajten ska inte flyttas eller skrivas over annu.
exit /b 0

:fail
echo.
echo PAKETERING: FEL
echo Ingen releasekandidat far laddas upp.
exit /b 1
