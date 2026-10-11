@echo off
rem Cree un environnement Python local et installe les dependances epinglees.
rem Seule etape necessitant Internet (telechargement des paquets) ; l'outil lui-meme est hors ligne.
cd /d "%~dp0\.."
py -3.11 -m venv .venv || py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo Installation terminee. Lancez scripts\lancer.bat
pause
