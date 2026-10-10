"""v77: refino fino pela IA (composição, tipografia, ênfase, animação por destaque, sons) e cores dos gráficos."""
import json

import dp_destaques as dd
import dp_graficos as dg
import prompt_edicao as pe


def _ev(**kw):
    d = dict({"estilo": "glow_01", "start": 1.0, "end": 4.0, "texto": "a guerra acabou em 1945"}, **kw)
    return dd._eventos_de_um(d, 1280, 720, dd.paleta_padrao(), [])


def test_enfase_pinta_palavra():
    linhas = [l for l in _ev(enfase=["1945"]) if l.startswith("Dialogue: 2")]
    assert any("1945" in l and "\\1c&H000AD6FF&" in l for l in linhas)  # #FFD60A em BGR do ASS
    sem = [l for l in _ev() if l.startswith("Dialogue: 2")]
    assert not any("\\1c&H000AD6FF&}1945" in l for l in sem)


def test_sobreposicoes_de_estilo():
    l2 = [l for l in _ev(fonte="anton", escala=1.5, maiusculas=True, anim_entrada="pop", anim_saida="riscar", interna="brilho")]
    principal = next(l for l in l2 if l.startswith("Dialogue: 2"))
    assert "\\fnDP Anton" in principal and "A GUERRA" in principal and "\\fscx30" in principal
    assert any(l.startswith("Dialogue: 4") for l in l2) and any(l.startswith("Dialogue: 1") for l in l2)
    normal = next(l for l in _ev() if l.startswith("Dialogue: 2"))
    import re
    fs = lambda l: int(re.search(r"\\fs(\d+)", l).group(1))  # noqa: E731
    assert fs(principal) > fs(normal)


def test_prompt_pede_refino():
    job = {"total_duration": 8, "pending_segments": [{"start": 0, "end": 4, "provider": "p", "query": "a"}, {"start": 4, "end": 8, "provider": "p", "query": "b"}], "segments": []}
    t = pe.montar_prompt(job, {"direcao": "sys_tudo"})
    for k in ('"enfase"', '"anim_entrada"', '"fonte"', '"zona"', '"bordas"', '"camera"', '"transition_som"', '"esquema"', '"cartao"', "REFINO FINO"):
        assert k in t, k


def test_ler_resposta_refino():
    ws = [{"word": w, "start": 0.2 + k * 0.4, "end": 0.5 + k * 0.4} for k, w in enumerate("Em 1945 a guerra acabou".split())]
    r = pe.ler_resposta(json.dumps({
        "trechos": [{"trecho": 1, "bordas": "smart", "camera": "giro", "foco": {"x": 0.2, "y": 2}, "transition_som": "nenhum",
                     "template": "MOLDURA_02", "template_campos": {"_fundo": "grade_ondulada", "_fundo_cor": "#ff0000"}},
                    {"trecho": 2, "camera": "giro"}],
        "destaques": [{"estilo": "selo_ano", "texto": "1945", "palavra": "1945", "zona": "canto_tr", "enfase": "1945", "fonte": "anton",
                       "maiusculas": True, "escala": 3, "anim_entrada": "pop", "anim_saida": "riscar", "interna": "brilho", "som": "nenhum"},
                      {"estilo": "glow_01", "avulso": True, "texto": "FIM", "start": 10, "end": 12}],
        "legenda": {"estilo": "pop", "posicao": "topo", "tamanho": 0.5, "cor_ativa": "#00ff00"},
        "graficos": [{"tipo": "barras", "dados": [{"rotulo": "a", "valor": 1, "cor": "#ff0000"}, ["b", 2, "#00ff00"]], "start": 1, "end": 4,
                      "esquema": "arcoiris", "cartao": "claro", "fundo_opacidade": 2, "texto_cor": "#111111"}],
        "sons": [{"som": "transicoes/digital", "start": 2, "volume": 3}]}), 5, 20, ws, [True, False, True, True, True])
    t0 = r["trechos"][0]
    assert (t0["bordas"], t0["camera"], t0["foco"], t0["transition_som"]) == ("smart", "giro", {"x": 0.2, "y": 1.0}, "nenhum")
    assert t0["template_campos"] == {"_fundo": "grade_ondulada", "_fundo_cor": "#FF0000"}
    assert all("camera" not in t for t in r["trechos"][1:])  # trecho 2 é vídeo
    h = r["destaques"][0]
    assert (h["zona"], h["enfase"], h["fonte"], h["escala"], h["anim_entrada"], h["anim_saida"], h["interna"], h["som"]) == \
        ("canto_tr", ["1945"], "anton", 1.6, "pop", "riscar", "brilho", "nenhum")
    av = r["destaques"][1]
    assert av["avulso"] and av["start"] == 10.0 and av["end"] == 12.0
    assert r["legenda"] == {"estilo": "pop", "posicao": "topo", "tamanho": 0.1, "cor_ativa": "#00FF00"}
    g = r["graficos"][0]
    assert g["esquema"] == "arcoiris" and g["cartao"] == "claro" and g["fundo_opacidade"] == 1.0 and g["dados"][1]["cor"] == "#00FF00"
    assert r["sons"][0]["volume"] == 1.5


def test_cores_do_grafico_mudam_o_desenho():
    base = dg.normalizar({"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 0, "end": 4})
    claro = dg.normalizar({"tipo": "barras", "dados": [["a", 1], ["b", 2]], "start": 0, "end": 4, "cartao": "claro"})
    azul = dg.normalizar({"tipo": "barras", "dados": [["a", 1, "#0000FF"], ["b", 2, "#0000FF"]], "start": 0, "end": 4})
    im1, _ = dg.desenhar(base, 3, 640, 360)
    im2, _ = dg.desenhar(claro, 3, 640, 360)
    im3, _ = dg.desenhar(azul, 3, 640, 360, "#FFD60A")
    assert im1.getpixel((5, 60))[0] < 60 and im2.getpixel((5, 60))[0] > 200   # fundo escuro × claro
    w, h = im3.size
    azuis = sum(1 for x in range(0, w, 4) for y in range(0, h, 4) if im3.getpixel((x, y))[2] > 200 and im3.getpixel((x, y))[0] < 60)
    assert azuis > 20
