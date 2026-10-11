@echo off
rem ==========================================================
rem  Pseudo-FEC (version portable) - double-cliquez pour lancer.
rem  Rien a installer. Aucune connexion Internet necessaire.
rem ==========================================================
pushd "%~dp0"
title Pseudo-FEC
if not exist "python\python.exe" goto manque
if not exist "app\pseudo_fec\__init__.py" goto manque
set "PYTHONHOME="
set "PYTHONPATH=%CD%\app"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
"python\python.exe" -m pseudo_fec %*
set "RC=%errorlevel%"
popd
if not "%RC%"=="0" (
  echo.
  echo Une erreur est survenue. Lisez le message ci-dessus ou ouvrez DEMARRER.html.
  pause
)
exit /b %RC%

:manque
echo.
echo  Le dossier est incomplet : recopiez le dossier Pseudo-FEC en entier
echo  depuis l'archive d'origine, sans deplacer le fichier de lancement seul.
echo.
pause
exit /b 1
