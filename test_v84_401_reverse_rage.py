"""v84_401: 🔄 reverse rage — a treta vira gentileza (ironia wholesome), sem palavrão, golpes pixelados, abertura nova a cada vídeo."""
import curtos as CT
import curtos_comentario as CC
import palavroes
from test_v84_320_lote_por_etapa import _app, _falsos
from test_v84_345_personalidade import _p


def test_palavroes():
    assert palavroes.limpar("What the fuck, man, that shit is wild!") == "What the, man, that is wild!"
    assert palavroes.limpar("Que porra é essa, caralho?") == "Que é essa?"
    assert palavroes.limpar("Hell yeah, damn good") == "Hell yeah, damn good"  # aceito pelos anúncios
    assert palavroes.achar("Shitty day") == ["Shitty"]


def test_prompt_sem_sorteio_e_sem_repetir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "Wholesome Roads", "")
    velho = _p(base, c["id"], "reverso", falas=("In Russia, bikers are treated like royalty.", "Such a wholesome reunion."))
    novo = _p(base, c["id"], "reverso")
    sis = CC.sistema(novo)
    assert "REVERSE RAGE MODE" in sis and "AUTHENTIC MODE" not in sis and "head rub" in sis and "agressoes" in sis
    cont = CC.conteudo_roteiro(base, novo)
    assert "invent a NEW one for THIS clip" in cont and "HOOK TYPE" not in cont  # sem sorteio de tipo
    assert "In Russia, bikers are treated like royalty." in cont and "RECENT SCRIPTS" in cont  # o que não repetir
    sc = CC.roteiro_schema(novo)
    assert "agressoes" in sc["properties"] and "agressoes" in sc["required"]
    assert "agressoes" not in CC.roteiro_schema(_p(base, c["id"]))["properties"]
    assert "reverso" in CC.ESTILOS_ROTEIRO


def test_ler_roteiro_limpa_e_guarda_agressoes(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "W", "")
    p = _p(base, c["id"], "reverso")
    p["midias"] = [{"id": "M1", "tipo": "video"}]
    resp = {"blocos": [{"funcao": list(CT.FUNCOES_BLOCO)[0], "fala_en": "He gave him a gentle head rub, damn, what a fucking sweetheart.",
                        "fala_pt": "", "cenas": [{"layout": "clipe", "material": "M1", "de": 0, "ate": 3}], "sfx": []}],
            "agressoes": [{"material": "M1", "de": 4.0, "ate": 4.6, "o_que": "soco", "tipo": "golpe", "alvo": "his face", "vira": ""},
                          {"material": "M9", "de": 1, "ate": 2, "o_que": "x"},
                          {"material": "M1", "de": 5, "ate": 4, "o_que": "ruim"},
                          {"material": "M1", "de": 6, "ate": 9, "o_que": "faca", "tipo": "arma", "alvo": "the knife", "vira": "a baguette"}]}
    r = CC.ler_roteiro(resp, p, "en")
    assert "fucking" not in r["blocos"][0]["fala"] and "head rub" in r["blocos"][0]["fala"]
    assert r["agressoes"] == [{"material": "M1", "de": 3.8, "ate": 4.8, "o_que": "soco", "tipo": "golpe", "alvo": "his face", "vira": ""},
                              {"material": "M1", "de": 5.8, "ate": 9.2, "o_que": "faca", "tipo": "arma", "alvo": "the knife", "vira": "a baguette"}]


def test_censura_so_na_area_e_na_linha_do_tempo():
    p = {"config": {"estilo_roteiro": "reverso", "proporcao": "9:16"},
         "roteiro": {"agressoes": [{"material": "M1", "de": 3.8, "ate": 4.8, "tipo": "golpe", "caixa": [0.4, 0.2, 0.2, 0.15],
                                    "caixa2": [0.5, 0.25, 0.2, 0.15], "clipe_wh": [720, 1280]},
                                   {"material": "M1", "de": 0.5, "ate": 1.0, "tipo": "arma", "caixa": None}]}}
    planos = [{"start": 0.0, "end": 2.0, "clipe": {"mid": "M1", "ini": 0.0, "fim": 2.0}},
              {"start": 2.0, "end": 5.0, "clipe": {"mid": "M1", "ini": 3.0, "fim": 6.0}}]  # o plano 2 mostra 3.0–6.0 do clipe
    cz = CT.censura_reverso(p, planos)
    golpe = next(c for c in cz if c["forma"] == "elipse")
    assert abs(golpe["start"] - 2.8) < 1e-6 and abs(golpe["end"] - 3.8) < 1e-6 and not golpe["tela_toda"]
    assert (golpe["x"], golpe["y"], golpe["x2"], golpe["y2"]) == (0.4, 0.2, 0.5, 0.25)  # mesma proporção: igual; desliza
    arma = next(c for c in cz if c["forma"] == "retangulo")
    assert arma["ajustar"] and arma["w"] < 1 and arma["start"] == 0.5  # não achou: área média, pra ajustar
    import dp_censura
    n = dp_censura.normalizar([dict(golpe)], 10)[0]
    assert n["tela_toda"] is False and n["x2"] == 0.5 and n["forma"] == "elipse"
    p["config"]["cobrir_agressoes"] = "nao"
    assert CT.censura_reverso(p, planos) == []


def test_caixa_de_clipe_deitado_no_quadro_em_pe():
    # clipe 16:9 dentro de um quadro 9:16 com fundo (fit): a faixa do meio
    c = CT._no_quadro([0.5, 0.5, 0.1, 0.1], [1920, 1080], (1080.0, 1920.0), "fit")
    assert abs(c[0] - 0.5) < 1e-3 and 0.45 < c[1] < 0.55 and c[3] < 0.05
    # cortado pra preencher (zoom): o meio do clipe vira a tela toda — a caixa cresce
    z = CT._no_quadro([0.45, 0.4, 0.1, 0.2], [1920, 1080], (1080.0, 1920.0), "zoom")
    assert z[2] > 0.1 and abs(z[1] - 0.4) < 1e-3


def test_preparar_censura_acha_a_area(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "W3", "")
    p = _p(base, c["id"], "reverso")
    vid = str(tmp_path / "clip.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=6:s=360x640:r=10", "-pix_fmt", "yuv420p", vid], check=True)
    monkeypatch.setattr(CC, "clipes", lambda b, q: [{"id": "M1", "caminho": vid}])
    p["roteiro"]["agressoes"] = [{"material": "M1", "de": 1.0, "ate": 3.0, "tipo": "golpe", "alvo": "the face being slapped"},
                                 {"material": "M1", "de": 4.0, "ate": 4.4, "tipo": "arma", "alvo": "the pistol"}]
    CT.salvar(base, p)
    pedidos = []

    def achar(video, t, alvo, tmp, chamar=None, base_=None):
        pedidos.append((round(t, 2), alvo))
        return None if "pistol" in alvo else [144.0, 128.0, 72.0, 64.0]  # 0.4,0.2,0.2,0.1 do clipe
    monkeypatch.setattr(CC, "achar_objeto", achar)
    r = CC.preparar_censura(base, p["id"])
    assert r == {"achados": 1, "sem_lugar": 1}
    assert pedidos[0] == (1.4, "the face being slapped") and pedidos[1] == (2.6, "the face being slapped")  # começo e fim
    ag = CT.carregar(base, p["id"])["roteiro"]["agressoes"]
    assert ag[0]["caixa"] and ag[0]["caixa"][2] > 0.2 and ag[0]["caixa2"] and ag[1]["caixa"] is None
    assert CC.preparar_censura(base, p["id"]) == {"achados": 0, "sem_lugar": 0}  # já procurado: não procura de novo


def test_link_e_pagina(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    _falsos(base, monkeypatch)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1", "exportar": False, "roteiro_reverso": True}).get_json()
    pid = r["criados"][0]
    assert CT.carregar(base, pid)["config"]["estilo_roteiro"] == "reverso"
    assert 'id="roteiro_reverso"' in cl.get("/curtos/link").get_data(as_text=True)


def test_composto_com_reverse_rage(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "W2", "")
    p = _p(base, c["id"], "reverso")
    p["config"]["composto"] = 3
    sis = CC.sistema(p)
    assert "REVERSE RAGE WITH 3 CLIPS" in sis and "COMPOSITE VIDEO" not in sis
    p["config"]["estilo_roteiro"] = "autentico"
    assert "COMPOSITE VIDEO" in CC.sistema(p)


def test_momentos_do_youtube_com_reverse_rage(tmp_path, monkeypatch):
    import os
    import momentos_yt as M
    from flask import Flask
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(M.__file__), "templates"))
    M.registrar(app, str(tmp_path))
    monkeypatch.setattr(M, "analisar", lambda *a, **k: None)
    cl = app.test_client()
    j = cl.post("/momentos-yt/novo", json={"link": "https://www.youtube.com/watch?v=N2jUcdTBeIY", "estilo_roteiro": "reverso"}).get_json()
    assert M.carregar(str(tmp_path), j["id"])["config"]["estilo_roteiro"] == "reverso"
    j = cl.post("/momentos-yt/novo", json={"link": "https://www.youtube.com/watch?v=N2jUcdTBeIY", "estilo_roteiro": "xx"}).get_json()
    assert M.carregar(str(tmp_path), j["id"])["config"]["estilo_roteiro"] == ""
    assert 'id="estilo_roteiro"' in cl.get("/momentos-yt").get_data(as_text=True)
