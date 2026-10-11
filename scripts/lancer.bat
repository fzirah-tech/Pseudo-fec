@echo off
rem Lancement en mode "developpement" (avant la creation de l'executable).
rem Prerequis : Python 3.11+ installe ; environnement cree par installer_dev.bat
cd /d "%~dp0\.."
if not exist .venv\Scripts\python.exe (
  echo Environnement absent : lancez d'abord scripts\installer_dev.bat
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pseudo_fec
