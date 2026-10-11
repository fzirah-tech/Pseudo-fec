import argparse

from . import __version__


def main() -> None:
    ap = argparse.ArgumentParser(prog="pseudo-fec", description="Pseudo-FEC : interface locale hors ligne.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    ap.add_argument("--port", type=int, default=0, help="port local (0 = automatique)")
    a = ap.parse_args()
    from .ui.server import run
    run(open_browser=not a.no_browser, port=a.port)


if __name__ == "__main__":
    main()
