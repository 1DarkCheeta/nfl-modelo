@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Listo. Abriendo la pagina (ya no necesita servidor) ===
start "" "%~dp0docs\index.html"
pause
