import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from pseudo_fec import crypto  # noqa: E402

TEST_PASS = "phrase de test uniquement 123"  # jamais la vraie phrase du cabinet


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(crypto, "KDF_DEFAULT", {"n": 2**10, "r": 8, "p": 1})


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from pseudo_fec.config import Config
    monkeypatch.setenv("PSEUDOFEC_PREFS", str(tmp_path / "prefs.json"))
    c = Config.load(tmp_path / "cabinet.json", tmp_path / "prefs.json")
    c.cabinet["tables_root"] = str(tmp_path / "tables")
    c.cabinet["outputs_root"] = str(tmp_path / "sorties")
    return c
