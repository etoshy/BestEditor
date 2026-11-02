"""v84_322: cada canal do link com idioma e voz próprios; reloader enxuto (não derruba o site por MemoryError)."""
import os

import curtos as CT
import curtos_comentario as CC
import curtos_rotas as CR
from flask import Flask


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(CR, "CB", dict(CR.CB))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(CT.__file__), "templates"))
    CR.registrar(app, str(tmp_path))
    return app.test_client()


def test_voz_e_idioma_do_canal(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    de = cl.post("/curtos/canais/novo", json={"nome": "Tiere DE", "voz_link": {"lingua_post": "de", "idioma": "en", "voz": "vDE"}}).get_json()["id"]
    us = cl.post("/curtos/canais/novo", json={"nome": "Fails US"}).get_json()["id"]
    cl.post(f"/curtos/canais/{us}/editar", json={"voz_link": {"lingua_post": "en", "idioma": "en", "voz": "vTurbo"}})
    pt = cl.post("/curtos/canais/novo", json={"nome": "Arte BR", "voz_link": {"idioma": "pt", "voz": "vPT", "lingua_post": "xx"}}).get_json()["id"]
    canais = {c["id"]: c for c in cl.get("/curtos/canais-link").get_json()["canais"]}
    assert canais[de]["voz_link"] == {"lingua_post": "de", "idioma": "en", "voz": "vDE", "modo": ""}
    assert canais[pt]["voz_link"]["lingua_post"] == ""  # idioma inválido não entra
    for nome, cid in (("Animais", de), ("Fails", us), ("Arte", pt)):
        cl.post("/curtos/link/grupos", json={"nome": nome, "canal_id": cid})
    r = cl.post("/curtos/link/novo", json={"link": "Animais\nhttps://a.com/1\nFails:\nhttps://a.com/2\nArte\nhttps://a.com/3\nOutro\nhttps://a.com/4",
                                           "lingua_post": "en", "idioma": "en", "voz": "vEnvio"}).get_json()
    a, f, ar, o = (CT.carregar(base, x) for x in r["criados"])
    assert CC.dados(a)["lingua_post"] == "de" and a["config"]["voz_tts"] == "vDE" and a["config"]["motor_perfil"] == "chatterbox"
    assert f["config"]["voz_tts"] == "vTurbo" and f["config"]["motor_perfil"] == "chatterbox_turbo"  # inglês: tags de voz
    assert CC.dados(ar)["idioma"] == "pt" and ar["config"]["voz_tts"] == "vPT" and ar["config"]["motor_perfil"] == "chatterbox"
    assert o["config"]["voz_tts"] == "vEnvio" and o["config"]["motor_perfil"] == "chatterbox_turbo"  # sem canal: o do envio


def test_voz_do_envio_nao_vai_pro_motor_errado(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    br = cl.post("/curtos/canais/novo", json={"nome": "BR", "voz_link": {"idioma": "pt"}}).get_json()["id"]
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1", "canal_id": br, "lingua_post": "en", "idioma": "en",
                                           "voz": "vTurboEN"}).get_json()
    p = CT.carregar(base, r["criados"][0])
    assert p["config"]["motor_perfil"] == "chatterbox" and p["config"].get("voz_tts", "") in ("", None)  # voz do Turbo não serve


def test_reloader_enxuto_so_o_projeto(monkeypatch):
    import werkzeug._reloader as wr
    import app
    monkeypatch.setattr(wr, "_find_stat_paths", wr._find_stat_paths)
    monkeypatch.setattr(wr.StatReloaderLoop, "run_step", wr.StatReloaderLoop.run_step)
    app._reloader_enxuto()
    ps = wr._find_stat_paths(set(), set())
    assert any(p.endswith(os.sep + "app.py") for p in ps) and not any("site-packages" in p for p in ps)
    chamado = []

    def explode(self):
        chamado.append(1)
        raise MemoryError
    monkeypatch.setattr(wr, "_find_stat_paths", lambda *a: explode(None))
    loop = wr.StatReloaderLoop.__new__(wr.StatReloaderLoop)
    loop.extra_files, loop.exclude_patterns, loop.mtimes = set(), set(), {}
    wr.StatReloaderLoop.run_step(loop)  # não levanta: só pula a rodada
    assert chamado
