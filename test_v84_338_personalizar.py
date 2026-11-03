"""v84_338: personalização reorganizada — estilos prontos do @ (caixa, neon, contorno duplo, 3D), itálico/MAIÚSCULAS/espaço,
fontes do Google Fonts (catálogo + qualquer nome) e a página com abas internas, galeria de fontes e sorteio separado."""
import io
import os
import shutil

import acabamento_extra as AX
import curtos as CT
import fontes_google as FG
import marca_canal
from test_v84_320_lote_por_etapa import _app

RAIZ = os.path.dirname(os.path.abspath(CT.__file__))


def test_estilos_do_arroba(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    a = CT.limpar_acabamento({"marca_estilo": "neon", "marca_estilo_cor": "00e5ff", "marca_italico": "1", "marca_maiusculas": True,
                              "marca_espaco": "99", "lixo": 1})
    assert a == {"marca_estilo": "neon", "marca_estilo_cor": "#00E5FF", "marca_italico": True, "marca_maiusculas": True, "marca_espaco": 40}
    assert CT.limpar_acabamento({"marca_estilo": "inventado"})["marca_estilo"] == ""
    p = {"modelo": "comentario", "config": {}}
    CT.aplicar_acabamento(p, dict(CT.ACABAMENTO_PADRAO, **a, arroba="@meucanal"))
    m = CT.normalizar_marca(p["config"]["marca"])
    assert m["estilo"] == "neon" and m["estilo_cor"] == "#00E5FF" and m["italico"] and m["maiusculas"] and m["espaco"] == 40
    ass = open(marca_canal.gerar_ass(m, 1080, 1920, 3, str(tmp_path / "n.ass")), encoding="utf-8").read()
    assert "@MEUCANAL" in ass and "\\blur" in ass and "\\3c&HFFE500&" in ass
    estilo = [l for l in ass.splitlines() if l.startswith("Style: Marca")][0].split(",")
    assert estilo[8] == "1" and estilo[13] == "40.0"  # itálico e o espaço entre letras
    caixa = open(marca_canal.gerar_ass(dict(m, estilo="caixa"), 1080, 1920, 3, str(tmp_path / "c.ass")), encoding="utf-8").read()
    assert [l for l in caixa.splitlines() if l.startswith("Style: Marca")][0].split(",")[15] == "3"  # BorderStyle 3 = caixa
    tres = open(marca_canal.gerar_ass(dict(m, estilo="3d"), 1080, 1920, 3, str(tmp_path / "3.ass")), encoding="utf-8").read()
    assert tres.count("Dialogue: 0,") == 10
    simples = open(marca_canal.gerar_ass(CT.normalizar_marca({"texto": "@x"}), 1080, 1920, 3, str(tmp_path / "s.ass")), encoding="utf-8").read()
    assert simples.count("Dialogue:") == 1  # sem estilo: igual a antes


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_baixar_do_google_fonts(tmp_path, monkeypatch):
    import dp_destaques
    import dp_extras
    fontes = tmp_path / "fontes"
    shutil.copytree(dp_destaques.FONTES_DIR, fontes)
    monkeypatch.setattr(dp_destaques, "FONTES_DIR", str(fontes))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    os.makedirs(tmp_path / "extras", exist_ok=True)
    try:
        dp_extras.carregar.cache_clear()
    except AttributeError:
        pass
    ttf = open(os.path.join(RAIZ, "assets", "fonts", "DejaVuSans-Bold.ttf"), "rb").read()
    pedidos = []

    def abrir(req, timeout=0):
        url = req.full_url
        pedidos.append(url)
        assert "Mozilla/4.0" in req.get_header("User-agent")
        if "googleapis" in url:
            if url.endswith(":700"):
                raise OSError("400 Bad Request")  # essa fonte não tem o 700
            return _Resp(b"@font-face { font-family: 'Bangers'; src: url(https://fonts.gstatic.com/s/bangers/v1/abc.ttf) format('truetype'); }")
        return _Resp(ttf)
    it = FG.baixar("Bangers", abrir)
    assert it == {"familia": "DP Bangers", "nome": "Bangers", "ja_tinha": False}
    assert pedidos[0].endswith("family=Bangers:700") and pedidos[1].endswith(":400") and pedidos[2].endswith("abc.ttf")
    assert AX.familias()["DP Bangers"] == "Bangers (Google)"
    assert any(f.startswith("gf-bangers") for f in os.listdir(fontes))
    assert FG.baixar("Bangers", abrir)["ja_tinha"] and len(pedidos) == 3  # não baixa de novo
    assert next(c for c in FG.catalogo() if c["nome"] == "Bangers")["instalada"]
    for ruim in ("", "../x", "a" * 80):
        try:
            FG.baixar(ruim, abrir)
            raise AssertionError(ruim)
        except FG.FonteErro:
            pass
    sem = lambda req, timeout=0: _Resp(b"/* nada */")  # noqa: E731
    try:
        FG.baixar("Nao Existe", sem)
        raise AssertionError("devia falhar")
    except FG.FonteErro as exc:
        assert "não achei" in str(exc)
    # a rota
    cl = _app(tmp_path, monkeypatch)
    j = cl.get("/curtos/fontes/google").get_json()
    assert j["ok"] and len(j["catalogo"]) >= 60 and "DP Bangers" in j["fontes"]
    monkeypatch.setattr(FG, "_pegar", lambda url, abrir=None, timeout=30: (_ for _ in ()).throw(OSError("sem internet")))
    r = cl.post("/curtos/fontes/google", json={"nome": "Lobster"})
    assert r.status_code == 400 and "Lobster" in r.get_json()["erro"]
    assert cl.post("/curtos/fontes/google", json={"nome": "Bangers"}).get_json()["fonte"]["ja_tinha"]


def test_pagina_organizada(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    html = cl.get("/curtos/personalizar").get_data(as_text=True)
    for k in ('data-sec="marca"', 'data-sec="legenda"', 'data-sec="cores"', 'data-sec="fontes"', 'class="pz-lado"', 'id="galMarca"',
              'id="galLeg"', "bSortearMarca", "bSortearLeg", "bDesfazer", 'id="a_marca_estilo"', 'id="a_marca_italico"', "gfMarcadas",
              'id="a_previa_marca"', 'id="a_previa_real"'):
        assert k in html, k
    assert html.count('id="a_escopo"') == 1 and html.count('id="a_marca_fonte"') == 1
