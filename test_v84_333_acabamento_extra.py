"""v84_333: acabamento avançado (do shortmaker) — @ com borda/sombra/degradê/X-Y/fonte sua, legenda com borda/sombra/opacidade
e estilo rolante, tarja sobre a legenda do vídeo original, prévia de verdade e envio de fonte."""
import os
import shutil
import subprocess

import acabamento_extra as AX
import curtos as CT
import dp_legendas
import marca_canal
from test_v84_320_lote_por_etapa import _app

RAIZ = os.path.dirname(os.path.abspath(CT.__file__))


def _clipe(caminho, dur=2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=360x640:rate=30:duration={dur}",
                    "-pix_fmt", "yuv420p", caminho], check=True, timeout=60)
    return caminho


def test_limpar_e_aplicar_no_projeto(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    a = CT.limpar_acabamento({"marca_borda": "7", "marca_borda_cor": "ff0000", "marca_sombra": 99, "marca_gradiente": "1",
                              "marca_cor": "#ffffff", "marca_cor2": "#00ff00", "marca_x": "30", "marca_y": -40, "marca_tamanho": "4.5",
                              "marca_opacidade": 90, "legenda_borda": 5, "legenda_opacidade": 80, "legenda_sombra_cor": "#123456",
                              "tarja_modo": "blur", "tarja_y0": 80, "tarja_y1": 70, "marca_fonte": "DP Anton", "lixo": "x"})
    assert a["marca_borda"] == 7 and a["marca_borda_cor"] == "#FF0000" and a["marca_sombra"] == 20 and "lixo" not in a
    full = dict(CT.ACABAMENTO_PADRAO, **a, arroba="@canal", legenda_estilo="pop")
    p = {"modelo": "comentario", "config": {}}
    CT.aplicar_acabamento(p, full)
    m, leg, t = p["config"]["marca"], p["config"]["legenda"], p["config"]["tarja"]
    assert m["borda"] == 7 and m["gradiente"] and m["cor2"] == "#00FF00" and m["desvio_x_px"] == 30 and m["desvio_y_px"] == -40
    assert abs(m["tamanho"] - 0.045) < 1e-9 and abs(m["opacidade"] - 0.9) < 1e-9 and m["fonte"] == "DP Anton"
    assert leg["borda"] == 5 and leg["opacidade"] == 80 and leg["sombra_cor"] == "#123456"
    assert t == {"modo": "blur", "y0": 0.7, "y1": 0.8, "cor": "#000000"}  # (de/até na ordem certa)
    nm = CT.normalizar_marca(m)
    assert nm["borda"] == 7 and nm["gradiente"] and nm["desvio_x_px"] == 30
    p2 = {"modelo": "comentario", "config": {}}
    CT.aplicar_acabamento(p2, dict(CT.ACABAMENTO_PADRAO, arroba="@x"))  # sem mexer: como era
    assert "borda" not in p2["config"]["marca"] and "tarja" not in p2["config"]


def test_marca_com_borda_sombra_degrade(tmp_path):
    cfg = CT.normalizar_marca({"texto": "@canal", "borda": 6, "borda_cor": "#FF0000", "sombra": 4, "gradiente": True, "cor": "#FFFFFF",
                               "cor2": "#0000FF", "desvio_x_px": 100})
    ass = open(marca_canal.gerar_ass(cfg, 1080, 1920, 5, str(tmp_path / "m.ass"))).read()
    estilo = next(l for l in ass.splitlines() if l.startswith("Style: Marca"))
    campos = estilo.split(",")
    assert campos[5] == "&H000000FF" and campos[16] == "6" and campos[17] == "4"  # borda vermelha 6, sombra 4
    assert ass.count("\\clip(") == 28 and "\\1c&H00FF0000&" in ass  # degradê até o azul
    sem = open(marca_canal.gerar_ass(CT.normalizar_marca({"texto": "@c"}), 1080, 1920, 5, str(tmp_path / "s.ass"))).read()
    assert "\\clip(" not in sem


def test_legenda_borda_sombra_opacidade_rolante(tmp_path):
    c = dp_legendas.normalizar({"ativa": True, "estilo": "rolante", "borda": 8, "borda_cor": "#00FF00", "sombra": 3, "opacidade": 50})
    ass = open(dp_legendas.gerar_ass([{"word": "oi", "start": 0, "end": 0.4}, {"word": "você", "start": 0.5, "end": 1}], c, 1080, 1920,
                                     str(tmp_path / "l.ass"))).read()
    leg = next(l for l in ass.splitlines() if l.startswith("Style: Leg")).split(",")
    assert leg[16] == "8" and leg[17] == "3" and leg[5] == "&H0000FF00&" and leg[3].startswith("&H80")  # 50% = alpha 0x80
    assert "\\move(" in ass
    assert "rolante" in {e["id"] for e in dp_legendas.ESTILOS}


def test_tarja_blur_e_solida(tmp_path):
    for modo in ("blur", "solida"):
        v = _clipe(str(tmp_path / f"{modo}.mp4"))
        antes = os.path.getsize(v)
        assert AX.aplicar_tarja(v, {"modo": modo, "y0": 0.7, "y1": 0.85, "cor": "#000000"})
        assert os.path.isfile(str(tmp_path / f"{modo}_sem_tarja.mp4")) and os.path.getsize(v) != antes
    assert not AX.aplicar_tarja(v, None)


def test_previa_e_fonte_enviada(tmp_path, monkeypatch):
    import dp_destaques
    fontes = tmp_path / "fontes"
    shutil.copytree(dp_destaques.FONTES_DIR, fontes)
    monkeypatch.setattr(dp_destaques, "FONTES_DIR", str(fontes))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    os.makedirs(tmp_path / "extras", exist_ok=True)
    import dp_extras
    try:
        dp_extras.carregar.cache_clear()
    except AttributeError:
        pass
    cl = _app(tmp_path, monkeypatch)
    r = cl.get('/curtos/acabamento/previa.jpg?d={"arroba":"@teste","marca_gradiente":true,"marca_cor2":"#FF0000","tarja_modo":"solida","tarja_y0":10,"tarja_y1":20}')
    assert r.status_code == 200 and r.data[:2] == b"\xff\xd8"
    with open(os.path.join(RAIZ, "assets", "fonts", "DejaVuSans-Bold.ttf"), "rb") as f:
        j = cl.post("/curtos/fontes", data={"fonte": (f, "minha.ttf"), "nome": "Minha Teste"}, content_type="multipart/form-data").get_json()
    assert j["ok"] and j["fonte"]["familia"] == "DP Minha Teste" and "DP Minha Teste" in j["fontes"]
    assert os.path.isfile(fontes / j["fonte"]["arquivo"])
    assert dp_legendas.normalizar({"fonte": "DP Minha Teste"})["fonte"] == "DP Minha Teste"
    assert CT.limpar_acabamento({"marca_fonte": "DP Minha Teste", "legenda_fonte": "DP Minha Teste"}) == \
        {"marca_fonte": "DP Minha Teste", "legenda_fonte": "DP Minha Teste"}
    assert cl.post("/curtos/fontes", data={}).status_code == 400
    html = cl.get("/curtos/link").get_data(as_text=True)
    for k in ("a_marca_borda", "a_marca_gradiente", "a_legenda_sombra", "a_tarja_modo", "bSortear", "a_previa_real", "bFonte", "Minha Teste"):
        assert k in html
    try:
        dp_extras.carregar.cache_clear()
    except AttributeError:
        pass
