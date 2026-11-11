"""Gaps from the long objective logs and gap reconciliation by meaning (both with a fake model)."""
from __future__ import annotations

import time
from pathlib import Path

from darwin_hoard import backing, gaps, gaps_log, reconcile
from darwin_hoard.store import Store

LOG = """# Objetivos acordados

## Ejecutar en PC o Spark — 09-11-2026

Hecho y verificado. Lo siguiente:

- **Elegir la Spark de destino** desde el Hub, comprobando memoria libre.
- **Traslado más rápido por Wi-Fi:** el primer traslado va a 5-8 MB/s por la tubería de ssh.

## Primer token con cobertura — 03-11-2026

Integrado: el primer token con cobertura va a otro destino y gana el primero que responda.

- El modelo por defecto no tiene otro servidor con el mismo modelo ni respaldos.
- Plano: en repos grandes falta una pasada en segundo plano que complete el resto de ficheros.

## Sesión antigua — 01-09-2026

Falta una cosa vieja que ya nadie recuerda y que debería quedar fuera por la fecha.

## Sin fecha

La búsqueda por persona sigue sin existir y hoy es solo texto completo con LIKE en las transcripciones.
Integrado lo demás.
"""


def _write(tmp_path: Path, text: str = LOG) -> Path:
    p = tmp_path / "OBJETIVOS.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_parse_takes_only_open_things_and_keeps_the_origin(tmp_path):
    cands = gaps_log.parse_log(LOG)
    titles = [c["title"] for c in cands]
    assert "Elegir la Spark de destino" in titles                                    # bullet under «Lo siguiente»
    assert any(t.startswith("Traslado más rápido") for t in titles)
    assert any("falta una pasada" in c["detail"] for c in cands)                       # bullet with its own cue
    assert not any("primer token con cobertura va" in c["detail"] for c in cands)      # history without a cue
    assert not any("cosa vieja" in c["detail"] for c in cands)                         # older than the window
    assert any("sigue sin existir" in c["detail"] for c in cands)                      # sentence of an undated section
    first = next(c for c in cands if c["title"] == "Elegir la Spark de destino")
    assert first["line"] == 7 and first["section"].startswith("Ejecutar en PC") and first["section_line"] == 3
    assert len({c["key"] for c in cands}) == len(cands)


def test_key_ignores_the_line_so_moving_text_is_not_new(tmp_path):
    a = {c["key"] for c in gaps_log.parse_log(LOG)}
    b = {c["key"] for c in gaps_log.parse_log("# Nuevo\n\nUna línea más arriba.\n\n" + LOG.split("\n", 1)[1])}
    assert a == b


def _chat_factory(open_if: str, calls: list):
    def chat(messages, **kw):
        calls.append(messages)
        body = messages[-1]["content"]
        items = []
        for chunk in body.split("\n\n")[1:]:
            n = int(chunk[1:chunk.index("]")])
            detail = chunk.split("\n", 1)[1]   # the header line carries the section name, not the text
            items.append({"n": n, "open": open_if in detail, "title": f"Pendiente {n}" if open_if in detail else ""})
        return {"ok": True, "json": {"items": items}, "model": "fake"}
    return chat


def test_import_log_sorts_with_the_model_is_idempotent_and_closes(tmp_path):
    store = Store(tmp_path / "d.db")
    f = _write(tmp_path)
    calls: list = []
    chat = _chat_factory("Spark", calls)
    first = gaps_log.import_log(store, f, "faustus", chat=chat)
    assert first["classified"] == "model" and first["added"] == 1 and first["rejected"] >= 3
    gap = store.one("SELECT * FROM gaps WHERE json_extract(watch,'$.from')='objetivos-log'")
    assert gap["target"] == "faustus" and gap["title"].startswith("Pendiente")
    w = gap["watch"] if isinstance(gap["watch"], dict) else __import__("json").loads(gap["watch"])
    assert w["file"] == str(f) and w["line"] == 7 and w["section"].startswith("Ejecutar") and w["classified"] == "model"
    n_calls = len(calls)
    again = gaps_log.import_log(store, f, "faustus", chat=chat)
    assert again["added"] == 0 and again["kept"] == 1 and len(calls) == n_calls   # nothing asked twice, nothing duplicated
    f.write_text(LOG.replace("- **Elegir la Spark de destino** desde el Hub, comprobando memoria libre.\n", ""), encoding="utf-8")
    gone = gaps_log.import_log(store, f, "faustus", chat=chat)
    assert gone["closed"] == 1
    assert store.one("SELECT state FROM gaps WHERE id=?", (gap["id"],))["state"] == "cerrada"


def test_a_model_that_does_not_answer_leaves_the_batch_for_later(tmp_path):
    store = Store(tmp_path / "d.db")
    f = _write(tmp_path)
    res = gaps_log.import_log(store, f, "faustus", chat=lambda *a, **k: {"ok": False, "error": "no_model"})
    assert res["added"] == 0 and res["pending"] > 0
    assert store.one("SELECT COUNT(*) AS n FROM gaps")["n"] == 0
    res2 = gaps_log.import_log(store, f, "faustus", chat=_chat_factory("Spark", []))
    assert res2["added"] == 1


def test_without_a_model_the_cue_decides_and_says_so(tmp_path):
    store = Store(tmp_path / "d.db")
    res = gaps_log.import_log(store, _write(tmp_path), "faustus", chat=None)
    assert res["classified"] == "heuristic" and res["added"] >= 4


def test_import_objectives_takes_extra_logs_and_short_lists_still_work(tmp_path):
    store = Store(tmp_path / "d.db")
    root = tmp_path / "Hoards"
    d = root / "Faustusables" / "Baird's Hoard"
    d.mkdir(parents=True)
    (d / "faustus-plugin.json").write_text('{"id": "baird"}', encoding="utf-8")
    (d / "OBJETIVOS.md").write_text("# O\n\n- Atajo global para captura.\n", encoding="utf-8")
    out = gaps.import_objectives(store, root, extra_files=[(_write(tmp_path), "faustus")], chat=_chat_factory("Spark", []))
    assert out["log_added"] == 1 and out["added"] == 2
    assert store.one("SELECT COUNT(*) AS n FROM gaps WHERE target='faustus'")["n"] == 1
    assert gaps.import_objectives(store, root, extra_files=[(tmp_path / "OBJETIVOS.md", "faustus")], chat=_chat_factory("Spark", []))["added"] == 0


# ---------------------------------------------------------------------- reconciliation by meaning

def _tree(store: Store):
    now = time.time()
    with store.tx() as c:
        for key, level, name, app, detail in [
                ("cap:vit:render-critique", "capability", "render critique", "vitruvius", "Mira una imagen renderizada y dice qué está mal"),
                ("cap:vit:palette", "capability", "palette", "vitruvius", "paletas de color"),
                ("cap:gul:printability", "capability", "printability", "gulliver", "comprueba si un modelo se puede imprimir")]:
            c.execute("INSERT INTO capabilities(key, parent_key, level, name, app_id, detail, since, seen) VALUES (?,?,?,?,?,?,?,?)",
                      (key, None, level, name, app, detail, now, now))


def test_semantic_flags_by_meaning_never_closes_and_survives_name_reconcile(tmp_path):
    store = Store(tmp_path / "d.db")
    _tree(store)
    backing.mark(store, "cap:vit:render-critique", implemented=True, evidence=[{"kind": "commit", "ref": "abc1234"}])
    backing.mark(store, "cap:gul:printability", implemented=True, evidence=[{"kind": "commit", "ref": "def5678"}])
    gid = store.add_gap(title="Criticar una imagen generada y decir qué corregir", detail="Que la app mire el render y diga los fallos", target="vitruvius")
    other = store.add_gap(title="Exportar el modelo para la web", detail="glTF dentro de un presupuesto", target="gulliver")
    seen: list = []

    def chat(messages, **kw):
        seen.append(messages[-1]["content"])
        return {"ok": True, "json": {"match": 1, "confidence": "alta", "reason": "Ya critica renders"}} if "imagen generada" in messages[-1]["content"] \
            else {"ok": True, "json": {"match": 0, "confidence": "baja", "reason": ""}}

    out = reconcile.semantic(store, chat)
    assert out["flagged"] == 1 and out["newly_flagged"] == [gid]
    flag = store.one("SELECT * FROM gap_flags WHERE gap_id=?", (gid,))
    assert flag["status"] == "possibly_stale" and flag["reason"] == "semantic" and flag["capability_key"] == "cap:vit:render-critique"
    assert store.one("SELECT state FROM gaps WHERE id=?", (gid,))["state"] == "abierta"           # a flag, never a closure
    assert store.one("SELECT state FROM gaps WHERE id=?", (other,))["state"] == "abierta"
    reconcile.reconcile(store)                                                                      # the by-name pass keeps it
    assert store.one("SELECT reason FROM gap_flags WHERE gap_id=?", (gid,))["reason"] == "semantic"
    asked = len(seen)
    reconcile.semantic(store, chat)
    assert len(seen) == asked                                                                        # unchanged gaps are not asked again
    reconcile.reconcile(store, dismiss_ids=[gid])
    backing.mark(store, "cap:vit:render-critique", implemented=True, evidence=[{"kind": "commit", "ref": "abc1234"}], note="again")
    reconcile.semantic(store, chat)
    assert store.one("SELECT status FROM gap_flags WHERE gap_id=?", (gid,))["status"] == "dismissed"
    assert reconcile.listing(store)["open"] == 2


def test_semantic_flag_goes_when_the_proof_goes(tmp_path):
    store = Store(tmp_path / "d.db")
    _tree(store)
    backing.mark(store, "cap:vit:render-critique", implemented=True, evidence=[{"kind": "commit", "ref": "abc1234"}])
    gid = store.add_gap(title="Criticar una imagen generada", detail="render", target="vitruvius")
    reconcile.semantic(store, lambda *a, **k: {"ok": True, "json": {"match": 1, "confidence": "alta", "reason": "x"}})
    assert store.one("SELECT 1 AS x FROM gap_flags WHERE gap_id=?", (gid,))
    backing.mark(store, "cap:vit:render-critique", implemented=False)
    reconcile.reconcile(store)
    assert not store.one("SELECT 1 AS x FROM gap_flags WHERE gap_id=?", (gid,))


def test_semantic_ignores_a_model_that_does_not_answer(tmp_path):
    store = Store(tmp_path / "d.db")
    _tree(store)
    backing.mark(store, "cap:vit:render-critique", implemented=True, evidence=[{"kind": "commit", "ref": "abc1234"}])
    store.add_gap(title="Criticar una imagen generada", detail="render", target="vitruvius")
    out = reconcile.semantic(store, lambda *a, **k: {"ok": False, "error": "timeout"})
    assert out["flagged"] == 0 and out["model_failed"] == 1
