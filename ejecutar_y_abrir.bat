@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Generando el reporte con momios decimales (puede tardar varios minutos) ===
powershell -NoProfile -Command "$env:PYTHONIOENCODING=\"utf-8\"; py semana_nfl.py 2>&1 | Tee-Object -FilePath ejecutar_decimal.log"
echo === Listo. Abriendo la pagina (ya no necesita servidor) ===
start "" "%~dp0docs\index.html"
pause
