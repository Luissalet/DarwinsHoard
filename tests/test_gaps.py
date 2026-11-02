"""Gaps from OBJETIVOS.md lists: one per item, logs skipped, closed when the item leaves the file."""
from pathlib import Path

from darwin_hoard import gaps
from darwin_hoard.store import Store


def _repo(root: Path, folder: str, app: str, text: str) -> Path:
    d = root / "Faustusables" / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "faustus-plugin.json").write_text(f'{{"id": "{app}"}}', encoding="utf-8")
    (d / "OBJETIVOS.md").write_text(text, encoding="utf-8")
    return d / "OBJETIVOS.md"


def test_lists_become_gaps_and_close_when_done(tmp_path):
    store = Store(tmp_path / "d.db")
    root = tmp_path / "Hoards"
    f = _repo(root, "Baird's Hoard", "baird", "# Objetivos\n\n- Atajo global para captura.\n- Captura de una zona: arrastrar.\n  sigue aquí\n- [x] Ya hecho.\n")
    _repo(root, "Silver's Hoard", "silver", "# O\n\n1. **Modo campaña por juego.** Recorrer un juego\n   de principio a fin.\n")
    _repo(root, "Big", "big", "# Log\n" + "- linea\n" * 200)
    out = gaps.import_objectives(store, root)
    assert out["added"] == 3
    rows = {r["title"]: r for r in store.q("SELECT title, target, detail, state FROM gaps")}
    assert rows["Atajo global para captura"]["target"] == "baird"
    assert rows["Captura de una zona"]["detail"].endswith("sigue aquí")
    assert rows["Modo campaña por juego"]["target"] == "silver"
    assert gaps.import_objectives(store, root)["added"] == 0
    f.write_text("# Objetivos\n\n- Captura de una zona: arrastrar.\n", encoding="utf-8")
    again = gaps.import_objectives(store, root)
    assert again["closed"] == 1
    assert store.one("SELECT state FROM gaps WHERE title='Atajo global para captura'")["state"] == "cerrada"
