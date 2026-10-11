"""Lanceur : prépare l'environnement local (une seule fois) puis démarre Pseudo-FEC.

Utilise uniquement la bibliothèque standard de Python. Appelé par « Lancer-Pseudo-FEC.bat ».
La seule étape qui utilise Internet est le téléchargement des composants lors de la première préparation
(ou jamais, avec un dossier « wheels » de composants fournis) ; l'application, elle, est hors ligne.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 11)


def venv_dir() -> Path:
    return ROOT / ".venv"


def venv_python() -> Path:
    return venv_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements_hash() -> str:
    return hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()


def marker() -> Path:
    return venv_dir() / ".pf_requirements"


def need_install() -> bool:
    return not venv_python().exists() or not marker().exists() or marker().read_text().strip() != requirements_hash()


def say(msg: str = "") -> None:
    print(msg, flush=True)


def python_ok() -> bool:
    if sys.version_info < MIN_PYTHON:
        say(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou plus récent est nécessaire (version trouvée : "
            f"{sys.version_info[0]}.{sys.version_info[1]}).")
        say("Installez Python 3.13 depuis https://www.python.org/downloads/windows/ (voir DEMARRER.html).")
        return False
    return True


def install() -> bool:
    say("Première préparation de l'application (1 à 3 minutes).")
    say("Une connexion Internet est utilisée UNIQUEMENT pour télécharger les composants ; ensuite l'outil est 100 % hors ligne.")
    if not venv_python().exists():
        say("→ Création de l'environnement local…")
        venv.create(venv_dir(), with_pip=True, clear=False)
    cmd = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")]
    wheels = ROOT / "wheels"
    if wheels.is_dir():
        say("→ Dossier « wheels » trouvé : installation hors ligne.")
        cmd[5:5] = ["--no-index", "--find-links", str(wheels)]
    say("→ Installation des composants…")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        say("\nL'installation des composants a échoué. Dernières lignes du message :")
        say("\n".join(r.stdout.strip().splitlines()[-8:] + r.stderr.strip().splitlines()[-8:]))
        say("\nCauses fréquentes : pas de connexion Internet, proxy d'entreprise, antivirus. "
            "Solution : demandez le dossier « wheels » (installation hors ligne) ou relancez avec Internet.")
        return False
    marker().write_text(requirements_hash())
    say("✓ Préparation terminée.\n")
    return True


def check() -> int:
    say(f"Dossier de l'application : {ROOT}")
    say(f"Python : {sys.version.split()[0]} ({'OK' if sys.version_info >= MIN_PYTHON else 'TROP ANCIEN'})")
    say(f"Environnement local : {'prêt' if not need_install() else 'à préparer au premier lancement'}")
    return 0 if sys.version_info >= MIN_PYTHON else 1


def main(argv: list[str]) -> int:
    if "--check" in argv:
        return check()
    if not python_ok():
        return 1
    if "--reinstall" in argv and venv_dir().exists():
        marker().unlink(missing_ok=True)
        argv = [a for a in argv if a != "--reinstall"]
    if need_install() and not install():
        return 1
    say("Démarrage de Pseudo-FEC… Le navigateur va s'ouvrir.")
    say("Ne fermez pas cette fenêtre tant que vous utilisez l'application (bouton « Quitter » dans la page pour l'arrêter).\n")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    try:
        return subprocess.call([str(venv_python()), "-m", "pseudo_fec", *argv], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
