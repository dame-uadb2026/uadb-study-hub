@echo off
title Serveur UADB Study Hub - En cours d'execution
color 0A
echo ===================================================
echo     DEMARRAGE AUTOMATIQUE DE UADB STUDY HUB
echo ===================================================
echo.

:: Se placer automatiquement dans le dossier ou se trouve ce fichier .bat
cd /d "%~dp0"

:: 1. Verifier et creer l'environnement virtuel si besoin
if not exist "venv" (
    echo [1/4] Creation de l'environnement virtuel Python...
    python -m venv venv
    if errorlevel 1 (
        echo [ERREUR] Python n'est pas installe ou pas ajoute au PATH !
        pause
        exit /b
    )
) else (
    echo [1/4] Environnement virtuel trouve.
)

:: 2. Activation de l'environnement virtuel
echo [2/4] Activation de l'environnement virtuel...
call venv\Scripts\activate

:: 3. Verification et installation automatique des dependances
echo [3/4] Verification des dependances (requirements.txt)...
if exist "requirements.txt" (
    pip install -r requirements.txt --quiet
)

:: 4. Ouverture automatique du navigateur dans 3 secondes
echo [4/4] Lancement de l'application web...
timeout /t 3 /nobreak > nul
start http://127.0.0.1:5000

:: 5. Execution de l'application Flask
python app.py

pause