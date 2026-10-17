"""
📘 Guia + ➕ extras do DarkPlanner: os exemplos de docs/guia/exemplos viram
transições, efeitos, entradas, filtros, destaques, cenas, paletas, sons e fontes
de verdade (catálogo, prévia do Estúdio, prompt da IA e montagem com ffmpeg).
"""
import json
import os
import shutil
import subprocess

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
EXEMPLOS = os.path.join(AQUI, "docs", "guia", "exemplos")


@pytest.fixture
def extras(tmp_path, monkeypatch):
    """Pasta de extras com os exemplos do guia (o site volta ao normal no fim)."""
    import dp_extras
    pasta = tmp_path / "extras"
    shutil.copytree(EXEMPLOS, pasta)
    monkeypatch.setenv("DP_EXTRAS_DIR", str(pasta))
    dp_extras.recarregar()
    yield pasta
    monkeypatch.undo()  # volta o DP_EXTRAS_DIR de antes
    dp_extras.recarregar()


def _clip(caminho, cor, dur=2.0, W=192, H=108):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s={W}x{H}:r=30:d={dur}",
                    "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(caminho)], check=True)
    return str(caminho)


def _dur(caminho):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", caminho],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def test_exemplos_entram_sem_erro(extras):
    import dp_extras
    r = dp_extras.resumo()
    assert r["erros"] == [], r["erros"]
    assert r["contagem"]["transicoes"] == 3 and r["contagem"]["destaques"] == 2 and r["contagem"]["cenas"] == 2


def test_transicoes_dos_extras(extras, tmp_path):
    import dp_visual
    import video_assembler as va
    ids = {t["dp_id"]: t for t in dp_visual.transicoes()}
    assert ids["cortina_central"]["previa"] == "horzclose" and "Cortina fechando no centro" in ids["cortina_central"]["rotulo"]
    assert ids["luz_dourada_2"]["previa"] is None  # expressão (luz) — a prévia usa fade
    assert dp_visual.resolver_transicao("dp:cortina_central") == ("nativa", "horzclose")
    assert dp_visual.resolver_transicao("dp:luz_dourada_2")[0] == "expr"
    tipo, expr = dp_visual.resolver_transicao("dp:varredura_diagonal_suave")
    assert tipo == "expr" and "sin(Y/H*18)" in expr
    # roda de verdade no ffmpeg
    a, b = _clip(tmp_path / "a.mp4", "red"), _clip(tmp_path / "b.mp4", "blue")
    for t in ("dp:varredura_diagonal_suave", "dp:cortina_central", "dp:luz_dourada_2"):
        out = str(tmp_path / f"{t[3:]}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a, "-i", b, "-filter_complex",
                        f"[0:v][1:v]xfade={va._transicao_xfade(t)}:duration=0.8:offset=1.0,format=yuv420p[v]", "-map", "[v]", out], check=True)
        assert abs(_dur(out) - 3.0) < 0.15


def test_efeitos_entradas_e_filtros(extras, tmp_path):
    import dp_visual
    ef = {e["id"]: e for e in dp_visual.efeitos()}
    assert ef["zoom_lento_foto"]["so_foto"] and dp_visual.EFEITO_PARA_ZOOM["zoom_lento_foto"] == "in"
    assert not ef["calor_suave"]["so_foto"] and ef["calor_suave"]["rotulo"] == "Calor suave"
    assert dp_visual.atmosfera("calor_suave", 192, 108, 2, str(tmp_path))[1] == ["[base]eq=gamma=1.06:saturation=1.12,colorbalance=rm=0.05:bm=-0.04[base]"]
    assert dp_visual.atmosfera("poeira_dourada", 192, 108, 2, str(tmp_path / "t"))[0]  # = ov_poeira (textura)
    en = {e["id"]: e for e in dp_visual.entradas()}
    assert en["pop_rapido"]["previa"] == "pop" and en["pop_rapido"]["dur"] == 0.25
    assert dp_visual._gesto("pop_rapido", "p", 192, 108) == dp_visual._gesto("pop", "p", 192, 108)
    fi = {f["id"]: f for f in dp_visual.filtros()}
    assert fi["noite_azul"]["css"].startswith("saturate") and dp_visual.cadeia_filtro("noite_azul").startswith("colorbalance")
    # montagem de um trecho com efeito + entrada + saída dos extras
    clip = _clip(tmp_path / "c.mp4", "orange")
    out = str(tmp_path / "o.mp4")
    assert dp_visual.pos_processar_clipe(clip, out, 2.0, 192, 108, str(tmp_path / "w"), efeito="calor_suave", entrada="pop_rapido", saida="ergue_lento")
    assert abs(_dur(out) - 2.0) < 0.1
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-vf", dp_visual.cadeia_filtro("noite_azul"), str(tmp_path / "f.mp4")], check=True)


def test_destaques_dos_extras(extras, tmp_path):
    import dp_destaques
    h = dp_destaques.estilo("titulo_neon_grade")
    assert h["label"] == "Título neon com grade" and h["tipografia"]["fonte"] == "bebas" and h["papel"] == "abertura"  # herdou do épico
    assert h["coreografia"]["entrada"] == "glitch" and h["coreografia"]["saida"] == "blur"
    cat = {e["id"]: e for e in dp_destaques.catalogo_para_editor()}
    assert cat["titulo_neon_grade"]["categoria"] == "⭐ Meus estilos" and cat["titulo_neon_grade"]["fonte"] == "DP Bebas Neue"
    assert "titulo_neon_grade" in dp_destaques.bloco_para_prompt()  # a IA enxerga
    assert cat["titulo_neon_grade"]["fundo"] == ["grade_3d", "#2F7BFF"]
    import dp_sons
    assert dp_sons.do_darkplanner(dp_destaques.estilo("selo_valor_verde")["audio"]["assets"][0]) == "impacto/impacto_5"
    base = _clip(tmp_path / "b.mp4", "gray", 3.0, 320, 180)
    out = str(tmp_path / "hl.mp4")
    dp_destaques.aplicar_destaques(base, out, [{"estilo": "titulo_neon_grade", "start": 0.2, "end": 2.6, "texto": "A NOITE"},
                                              ], 320, 180, str(tmp_path / "w"))
    assert abs(_dur(out) - 3.0) < 0.1
    ass = (tmp_path / "x.ass")
    dp_destaques.gerar_ass([{"estilo": "selo_valor_verde", "start": 0.2, "end": 2.0, "texto": "R$ 2,4 BI"}], 320, 180, str(ass))
    assert "DP Anton" in ass.read_text(encoding="utf-8")


def test_cenas_dos_extras(extras, tmp_path):
    import cenas_dp
    assert cenas_dp.slots_do_template("MEU_TRIO_COLUNAS") == 3
    lay = cenas_dp.layout("MEU_TRIO_COLUNAS")
    assert lay["arranjo"] == "personalizado" and lay["janelas"][1] == (0.35, 0.08, 0.30, 0.70)
    assert cenas_dp.layout_para("MEU_TRIO_COLUNAS", 1080, 1920)["vertical"]
    par = cenas_dp.layout("MEU_PAR_PAPEL")
    assert par["arranjo"] == "lado_a_lado" and par["fundo_fixo"] == "papel" and cenas_dp.slots_do_template("MEU_PAR_PAPEL") == 2
    ed = {c["id"]: c for c in cenas_dp.catalogo_para_editor()}
    assert len(ed["MEU_TRIO_COLUNAS"]["janelas"]) == 3
    clips = [_clip(tmp_path / f"c{k}.mp4", c, 3.0 - k * 0.5) for k, c in enumerate(["red", "green", "blue"])]
    out = cenas_dp.renderizar_cena("MEU_TRIO_COLUNAS", clips, [0.0, 0.5, 1.0], 3.0, str(tmp_path / "o.mp4"), 192, 108, str(tmp_path / "w"),
                                   falas=["um", "dois", "três"])
    assert abs(_dur(out) - 3.0) < 0.1


def test_paleta_som_e_fonte(extras, tmp_path):
    import dp_cores
    import dp_destaques
    import dp_extras
    import dp_guia
    import dp_sons
    assert any(p["id"] == "minha_marca" and p["primaria"] == "#00C2A8" for p in dp_cores.PALETAS)
    # som: converte, mede o pico e registra
    wav = tmp_path / "boom.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=0.3", "-f", "lavfi", "-i",
                    "sine=frequency=90:duration=0.4", "-filter_complex", "[0][1]concat=n=2:v=0:a=1,afade=t=out:st=0.45:d=0.25", str(wav)], check=True)
    sons_dir = tmp_path / "sons"
    shutil.copytree(dp_sons.SONS_DIR, sons_dir, ignore=shutil.ignore_patterns("*.m4a"))
    import unittest.mock as um
    with um.patch.object(dp_sons, "SONS_DIR", str(sons_dir)):
        it = dp_guia.adicionar_som(str(wav), "meus testes", "Boom grave")
        assert it["id"] == "meus_testes/boom_grave" and 0.25 < it["pico"] < 0.75 and 0.25 < it["inicio_som"] < 0.4
        dp_extras.recarregar()
        assert dp_sons.som("meus_testes/boom_grave")["arquivo"] == "meus_testes/boom_grave.m4a"
        assert any(c["nome"] == "meus_testes" for c in dp_sons.categorias())
    # fonte: renomeia a família pra "DP …" e registra
    pytest.importorskip("fontTools")
    fontes_dir = tmp_path / "fontes"
    fontes_dir.mkdir()
    with um.patch.object(dp_destaques, "FONTES_DIR", str(fontes_dir)):
        r = dp_guia.adicionar_fonte(os.path.join(AQUI, "assets", "fonts", "dp", "anton-Bold.ttf"), "minha_fonte", "Minha Fonte")
        assert r["familia"] == "DP Minha Fonte" and r["estilo"] == "Bold"
        from PIL import ImageFont
        assert ImageFont.truetype(str(fontes_dir / r["arquivo"]), 20).getname()[0] == "DP Minha Fonte"
        dp_extras.recarregar()
        assert dp_destaques._FONTE["minha_fonte"] == "DP Minha Fonte"
        assert dp_destaques.fontes_json()["minha_fonte"]["arquivos"]["Bold"] == r["arquivo"]


def test_erros_aparecem_com_o_nome_do_arquivo(tmp_path, monkeypatch):
    import dp_extras
    import dp_visual
    pasta = tmp_path / "ex"
    pasta.mkdir()
    (pasta / "ruim.json").write_text(json.dumps({
        "transicoes": [{"id": "fade", "xfade": "fade"}, {"id": "sem_tipo"}, {"id": "nao_nativa", "xfade": "inventada"}],
        "destaques": {"x_estilo": {"base": "nao_existe"}}, "efeitos": [{"id": "ruim", "filtro": "eq=gamma=2"}],
        "coisa": []}), encoding="utf-8")
    (pasta / "quebrado.json").write_text("{ isto não é json", encoding="utf-8")
    (pasta / "_ignorado.json").write_text("{ nem leio", encoding="utf-8")
    monkeypatch.setenv("DP_EXTRAS_DIR", str(pasta))
    try:
        dp_extras.recarregar()
        dp_visual.dp()
        e = "\n".join(dp_extras.erros())
        assert "quebrado.json: não é um JSON válido" in e and "_ignorado" not in e
        assert "ruim.json: transição sem_tipo" in e and "seção desconhecida coisa" in e
        assert "ruim.json: transicoes fade já existe" in e and "nao_nativa" in e and "\"xfade\" 'inventada'" in e
        assert "x_estilo: \"base\" 'nao_existe'" in e and "começa com [base]" in e
        assert "dp:nao_nativa" not in {t["id"] for t in dp_visual.transicoes()}
    finally:
        monkeypatch.undo()
        dp_extras.recarregar()


def test_verificar_sem_extras_esta_limpo():
    import dp_guia
    r = dp_guia.verificar()
    assert r["erros"] == [] and r["avisos"] == []


def test_markdown_do_guia():
    import guia
    h = guia.markdown_para_html("# Título\n\nTexto com `codigo` e **negrito** e [link](01-transicoes.md#xfade).\n\n"
                                "- um\n- dois\n  - sub\n\n```json\n{\"a\": \"<b>\"}\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> nota")
    assert '<h1 id="título">Título</h1>' in h and "<code>codigo</code>" in h and "<b>negrito</b>" in h
    assert '<a href="/guia/01-transicoes#xfade">link</a>' in h and "<li>dois<ul><li>sub</li></ul></li>" in h
    assert "&lt;b&gt;" in h and "<table>" in h and "<td>2</td>" in h and "<blockquote>nota</blockquote>" in h


def test_pagina_do_guia_e_todos_os_arquivos():
    import app as A
    import guia
    c = A.app.test_client()
    r = c.get("/guia")
    assert r.status_code == 200 and "Seus extras" in r.get_data(as_text=True)
    pgs = guia.paginas()
    assert len(pgs) >= 12
    for pg in pgs:
        html = c.get(f"/guia/{pg['slug']}").get_data(as_text=True)
        assert "<h1" in html, pg
    assert c.get("/guia/nao-existe").status_code == 404 and c.get("/guia/..%2Fapp").status_code == 404
    assert json.loads(c.get("/guia/exemplos/destaques.json").get_data(as_text=True))["destaques"]
    assert c.post("/guia/extras/recarregar").get_json()["ok"]
    assert 'href="/guia"' in c.get("/").get_data(as_text=True)  # v84_161: link no menu lateral
