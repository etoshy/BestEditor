"""v84_362: 🔊 takes da sua voz no mesmo volume + verificador de efeitos sonoros (regras + IA) + corrigir os já gerados."""
import subprocess

import curtos as CT
import gravar_voz as GV
import sons_verificar as SV
from test_v84_325_minha_voz import _projeto


def _tom(cam, db, d=1.2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=220:d={d}", "-af", f"volume={db}dB", "-ac", "1", cam], check=True)
    return cam


def _lufs_trecho(cam, ini, fim):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(ini), "-to", str(fim), "-i", cam, "-af", "loudnorm=print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    import json
    import re
    return float(json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S).group(0))["input_i"])


def test_takes_ficam_no_mesmo_volume(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    pid = _projeto(base)
    GV.adicionar_take(base, pid, "B1", _tom(str(tmp_path / "baixo.wav"), -14))  # um take bem mais baixo (12 dB)
    GV.adicionar_take(base, pid, "B2", _tom(str(tmp_path / "alto.wav"), -2))
    final = GV.juntar(base, pid)
    a = _lufs_trecho(final, 0.1, 1.1)
    b = _lufs_trecho(final, 1.2 + GV.PAUSA_ENTRE_PARTES_S + 0.1, 1.2 + GV.PAUSA_ENTRE_PARTES_S + 1.1)
    assert abs(a - b) < 1.5, (a, b)  # antes: 12 dB de diferença
    assert abs(a - GV.ALVO_LUFS) < 2.0
    sem = GV.juntar(base, pid, normalizar=False)
    assert abs(_lufs_trecho(sem, 0.1, 1.1) - _lufs_trecho(sem, 1.3 + GV.PAUSA_ENTRE_PARTES_S, 2.2 + GV.PAUSA_ENTRE_PARTES_S)) > 10


SONS = [{"id": "variados/whoosh_1", "dur": 0.8, "inicio_som": 0.1, "pico": 0.3, "fim_som": 0.7, "nivel_db": -12},
        {"id": "impacto/impacto_1", "dur": 1.0, "inicio_som": 0.0, "pico": 0.1, "fim_som": 0.9, "nivel_db": -3},
        {"id": "pixabay/999", "nome": "Crowd cheering stadium", "tags": ["whoosh", "crowd"], "dur": 9.0, "inicio_som": 0, "pico": 2, "fim_som": 9},
        {"id": "pop/pop_1", "dur": 0.3, "inicio_som": 0, "pico": 0.05, "fim_som": 0.25, "nivel_db": -14}]


def _p():
    return {"id": "x1", "roteiro": {"blocos": [{"id": "B1", "fala": "He jumps off the cliff.", "sfx": []},
                                               {"id": "B2", "fala": "And lands softly in the water.", "sfx": []}]},
            "gravacao": {"dur": 12.0, "alinhamento": [{"start": 0, "end": 6}, {"start": 6, "end": 12}],
                         "palavras": [{"word": "jumps", "start": 0.8}, {"word": "lands", "start": 7.0}]}}


def _sons_falsos(monkeypatch):
    import dp_sons
    monkeypatch.setattr(dp_sons, "sons", lambda: list(SONS))
    monkeypatch.setattr(dp_sons, "som", lambda sid: next((s for s in SONS if s["id"] == sid), None))


def test_regras(monkeypatch):
    _sons_falsos(monkeypatch)
    evs = [{"som": "pixabay/999", "start": 1.0, "volume": 0.8, "origem": "ia", "curto": "B1:whoosh"},   # comprido + de outra deixa
           {"som": "variados/whoosh_1", "start": 3.0, "volume": 0.8, "origem": "ia", "curto": "B1:corte"},
           {"som": "pop/pop_1", "start": 3.5, "volume": 0.8, "origem": "ia", "curto": "B2:pop"},           # colado no de 3.3
           {"som": "impacto/impacto_1", "start": 7.0, "volume": 0.9, "origem": "ia", "curto": "B2:impacto"},  # alto demais
           {"som": "pop/pop_1", "start": 3.4, "volume": 1, "origem": "voce"}]                              # o seu: nunca mexe
    novos, rel = SV.regras(evs, _p())
    assert not any(e["som"] == "pixabay/999" for e in novos)
    assert any(r["acao"] == "trocar" and "Pixabay" in r["motivo"] or "comprido" in r["motivo"] for r in rel)
    assert any(r["acao"] == "tirar" and "colado" in r["motivo"] for r in rel)
    imp = next(e for e in novos if e["som"] == "impacto/impacto_1")
    assert imp["volume"] == 0.55
    assert any(e.get("origem") == "voce" for e in novos)


def test_ia_tira_o_desconexo_e_troca_tipo(monkeypatch):
    _sons_falsos(monkeypatch)
    evs = [{"som": "variados/whoosh_1", "start": 0.5, "volume": 0.8, "origem": "ia", "curto": "B1:whoosh"},
           {"som": "pop/pop_1", "start": 6.95, "volume": 0.8, "origem": "ia", "curto": "B2:pop"}]
    visto = {}

    def chamar(rec, sis, txt, **k):
        visto["txt"] = txt
        return {"sons": [{"i": 0, "acao": "manter", "tipo_novo": "", "motivo": ""},
                         {"i": 1, "acao": "trocar", "tipo_novo": "impacto", "motivo": "cai na água"}]}
    r = SV.verificar(evs, _p(), usar_ia=True, chamar=chamar)
    assert "lands softly in the water" in visto["txt"] and "jumps" in visto["txt"]
    assert r["ia"] and [e["som"] for e in r["eventos"]] == ["variados/whoosh_1", "impacto/impacto_1"]
    r2 = SV.verificar(evs, _p(), chamar=lambda *a, **k: {"sons": [{"i": 0, "acao": "tirar", "tipo_novo": "", "motivo": "nada a ver"}]})
    assert r2["depois"] == 1 and "nada a ver" in r2["relatorio"][0]["motivo"]


def test_rotas_verificar_e_corrigir(tmp_path, monkeypatch):
    from test_v84_320_lote_por_etapa import _app
    import curtos_rotas as CR
    _sons_falsos(monkeypatch)
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    pid = cl.post("/curtos/link/novo", json={"link": "https://a.com/1"}).get_json()["criados"][0]
    faixa = {"j1": [{"som": "pixabay/999", "start": 1.0, "volume": 0.8, "origem": "ia", "curto": "B1:whoosh"}]}
    monkeypatch.setitem(CR.CB, "sons_ler", lambda j: [dict(e) for e in faixa[j]])
    monkeypatch.setitem(CR.CB, "sons_gravar", lambda j, evs: faixa.__setitem__(j, evs))
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        p.update(_p() | {"id": pid, "editor": {"job_id": "j1"}})
        CT.salvar(base, p)
    j = cl.post(f"/curtos/{pid}/sons/verificar").get_json()
    assert j["ok"] and j["relatorio"] and faixa["j1"][0]["som"] == "pixabay/999"  # só olhou
    j = cl.post("/curtos/link/sons/corrigir", json={"ids": [pid]}).get_json()
    assert j["feitos"][0]["id"] == pid and faixa["j1"][0]["som"] != "pixabay/999"
    assert CT.carregar(base, pid)["sons_verificados"]["assinatura"]
