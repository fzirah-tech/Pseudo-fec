@echo off
rem ==========================================================
rem  Pseudo-FEC - double-cliquez sur ce fichier pour lancer l'application.
rem  Aucune commande a taper. Voir DEMARRER.html pour le guide.
rem ==========================================================
cd /d "%~dp0"
title Pseudo-FEC
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 bootstrap.py %*
  goto fin
)
where python >nul 2>nul
if %errorlevel%==0 (
  python bootstrap.py %*
  goto fin
)
goto nopython

:fin
if %errorlevel%==9009 goto nopython
if errorlevel 1 (
  echo.
  echo Une erreur est survenue. Lisez le message ci-dessus ou ouvrez DEMARRER.html.
  pause
)
exit /b %errorlevel%

:nopython
echo.
echo  Python n'est pas installe sur cet ordinateur (ou n'est pas accessible).
echo.
echo  1. Ouvrez https://www.python.org/downloads/windows/
echo  2. Telechargez "Windows installer (64-bit)" de Python 3.13
echo  3. Au lancement de l'installeur, COCHEZ "Add python.exe to PATH"
echo     puis choisissez "Install Now" (aucun droit administrateur requis)
echo  4. Relancez ce fichier.
echo.
pause
exit /b 1
