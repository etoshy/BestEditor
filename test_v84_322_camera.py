"""v84_322: 🎥 câmera experimental — ligada nos vídeos novos; desligada = montagem anterior."""
import os
import subprocess

import camera_exp
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


def _clipe(caminho, dur=2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=360x640:rate=30:duration={dur}",
                    "-pix_fmt", "yuv420p", caminho], check=True, timeout=60)
    return caminho


def test_novos_nascem_ligados_antigos_ficam_como_eram(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(str(tmp_path), "", "t", modelo="comentario")
    assert camera_exp.ligada(p)
    assert "CAMERA DIRECTION" in CC.sistema(p) and "{LINGUA}" not in CC.sistema(p)
    cena = CC.roteiro_schema(p)["properties"]["blocos"]["items"]["properties"]["cenas"]["items"]
    assert "zoom_detalhe" in cena["properties"] and "zoom_detalhe" in cena["required"]
    p["config"].pop("camera_exp")  # projeto de antes
    assert not camera_exp.ligada(p) and "CAMERA DIRECTION" not in CC.sistema(p)
    assert CC.roteiro_schema(p) is CC.ROTEIRO_SCHEMA


def test_teto_corta_o_excesso():
    cn = lambda **k: dict({"material": "M1", "de": 0, "ate": 1, "efeito": "zoom_in", "entrada": "punch_in"}, **k)  # noqa: E731
    r = {"blocos": [{"cenas": [cn(zoom_detalhe="claw", congelar={"texto": "Fact one"}),
                               cn(zoom_detalhe="fur", destaque={"alvo": "eye"}),
                               cn(zoom_detalhe="tail"), cn(zoom_detalhe="nose", congelar={"texto": "Fact two"}),
                               cn(destaque={"alvo": "a"}), cn(destaque={"alvo": "b"}),
                               {"layout": "foto", "query": "x", "zoom_detalhe": "nope", "efeito": ""}]}]}
    camera_exp.aplicar_teto(r)
    cs = r["blocos"][0]["cenas"]
    assert cs[0]["zoom_detalhe"] == "claw" and "congelar" not in cs[0]  # 1 efeito por cena: o zoom ganha
    assert cs[1]["zoom_detalhe"] == "fur" and "destaque" not in cs[1]
    assert "zoom_detalhe" not in cs[3] and cs[3]["congelar"] == {"texto": "Fact two"}  # 4º zoom passou do teto (3)
    assert sum(1 for c in cs if c.get("zoom_detalhe")) == 3
    assert sum(1 for c in cs if (c.get("destaque") or {}).get("alvo")) == 2
    assert "zoom_detalhe" not in cs[6]  # fora de clipe não tem zoom
    assert sum(1 for c in cs if c.get("entrada") not in (None, "none")) == 3
    assert cs[2]["efeito"] == ""  # 3º zoom_in seguido vira ''


def test_render_zoom_e_congelar(tmp_path):
    v = _clipe(str(tmp_path / "c.mp4"))
    z = camera_exp.render_zoom(v, str(tmp_path / "z.mp4"), [[30, 400, 60, 60]] * 60, 30.0)
    f = camera_exp.render_congelar(v, str(tmp_path / "f.mp4"), "Sloths almost never drink water", 30.0, 1.5)
    import rastreio
    assert abs(rastreio.sondar(z)["dur"] - 2.0) < 0.15 and rastreio.sondar(z)["largura"] == 360
    assert abs(rastreio.sondar(f)["dur"] - 1.5) < 0.15
    img, h = camera_exp.cartao_png("a very long fact card that must wrap into lines nicely", 360, 640)
    assert img.size[0] == 360 and 0 < h < 640 * 0.4


def test_preparar_faz_as_midias_e_o_editor_usa(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(base, "", "t", modelo="comentario")
    v = _clipe(str(tmp_path / "c.mp4"), 3)
    planos = [{"start": 0.0, "end": 1.0, "clipe": {"mid": "M1", "de": 0.0, "ate": 1.0, "off": 0.0}, "zoom_detalhe": "red circle"},
              {"start": 1.0, "end": 2.0, "clipe": {"mid": "M1", "de": 1.0, "ate": 2.0, "off": 0.0}, "congelar": "A real fact"},
              {"start": 2.0, "end": 3.0, "clipe": {"mid": "M1", "de": 2.0, "ate": 3.0, "off": 0.0}, "zoom_detalhe": "ghost"}]
    monkeypatch.setattr(CT, "planos_do_video", lambda *a, **k: [dict(x, clipe=dict(x["clipe"])) for x in planos])
    monkeypatch.setattr(CC, "clipes", lambda b, q: [{"id": "M1", "caminho": v}])
    monkeypatch.setattr(CC, "achar_objeto", lambda vid, t, alvo, *a, **k: [100, 200, 80, 80] if alvo == "red circle" else None)
    r = camera_exp.preparar(base, p["id"], ["pexels"])
    assert len(r["feitos"]) == 2 and r["pulados"][0]["alvo"] == "ghost"
    q = CT.carregar(base, p["id"])
    ids = sorted(q["camera_prontos"].values())
    assert ids[0].startswith("F") and ids[1].startswith("Z")
    assert all(CT.caminho_midia(base, q, m) for m in q["midias"] if m["id"] in ids)
    # a mesma chave que o editor usa (montar_dados_editor) acha o pedaço pronto
    xs = [dict(x, clipe=dict(x["clipe"])) for x in planos]
    CT.fixar_trechos_do_clipe(xs, {"M1": 3.0})
    assert camera_exp.chave(xs[0]) in q["camera_prontos"] and camera_exp.chave(xs[1]) in q["camera_prontos"]
    assert camera_exp.preparar(base, p["id"], ["pexels"])["feitos"] == r["feitos"]  # 2ª vez: reaproveita


def test_desligada_nao_faz_nada(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    p = CT.criar(base, "", "t", modelo="comentario")
    p["config"]["camera_exp"] = False
    CT.salvar(base, p)
    monkeypatch.setattr(CT, "planos_do_video", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia montar")))
    assert camera_exp.preparar(base, p["id"]) == {"feitos": [], "pulados": []}


def test_cena_guarda_os_campos():
    out = CT._trecho_da_cena({"de": 1, "ate": 2, "zoom_detalhe": "green algae on the back", "congelar": {"texto": "Algae grows in its fur"}})
    assert out["zoom_detalhe"] == "green algae on the back" and out["congelar"] == {"texto": "Algae grows in its fur"}
    assert "congelar" not in CT._trecho_da_cena({"de": 1, "congelar": {"texto": ""}})


def test_link_e_pagina(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    a = cl.post("/curtos/link/novo", json={"link": "https://a.com/1"}).get_json()["criados"][0]
    b = cl.post("/curtos/link/novo", json={"link": "https://a.com/2", "camera_exp": False}).get_json()["criados"][0]
    assert CT.carregar(base, a)["config"]["camera_exp"] is True and CT.carregar(base, b)["config"]["camera_exp"] is False
    cl.post(f"/curtos/{b}/config", json={"camera_exp": True})
    assert CT.carregar(base, b)["config"]["camera_exp"] is True
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert 'id="camera_exp" checked' in html
