"""v84_278 — 🎬 Explicador animado: narração + legenda → plano de cenas → página → MP4 / editor."""
import json
import os
import subprocess

import pytest

import explicador as X

SRT = """1
00:00:00,000 --> 00:00:02,000
Welcome to the show. Here is the goal.

2
00:00:02,000 --> 00:00:04,000
One pair beats high card.

3
00:00:04,000 --> 00:00:06,000
You bet and they fold. Thanks for watching.
"""


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPLICADOR_DIR", str(tmp_path / "expl"))
    return str(tmp_path)


def _audio(tmp_path, dur=6.0):
    cam = str(tmp_path / "n.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=220:d={dur}", "-ar", "24000", cam], check=True)
    return cam


PLANO = {"cenas": [
    {"tipo": "texto", "de": 0, "linhas": [{"texto": "WELCOME", "estilo": "titulo", "em": "Welcome"},
                                          {"texto": "THE GOAL", "estilo": "tag", "em": "Here is the goal"}]},
    {"tipo": "escada", "de": "One pair", "capitulo": "RANK", "itens": [{"chave": "pair", "em": "One pair"}, {"chave": "high", "em": "high card"}]},
    {"tipo": "mao", "de": "You bet", "dsl": "mesa: blinds=0.5/1 unidade=bb\njogador: You 100 7c 6c heroi\njogador: Rival 100 Qh Jd\nbotao: You\n"
                                          "preflop: You raise 2.5; Rival fold",
     "ancoras": [{"em": "they fold", "evento": {"tipo": "acao", "quem": "Rival", "acao": "fold"}}],
     "destaques": [{"em": "they fold", "alvo": "jogador:Rival", "texto": "FOLD"}, {"em": "Thanks", "estilo": "carimbo", "texto": "BYE"}]},
]}


def test_tempos_acha_frases_normalizando():
    T = X.Tempos(X.ler_srt(SRT))
    assert T.quando("here is the GOAL!") == pytest.approx(1.0, abs=0.35)
    assert T.quando("One pair") == pytest.approx(2.0, abs=0.05)
    assert T.quando("they fold", 3) > 4
    assert T.quando("nada disso existe aqui") is None
    assert T.quando(2.5) == 2.5


def test_whisper_vira_palavras():
    segs = X.segs_de_whisper([{"start": 0, "end": 1, "text": "oi tudo", "words": [{"word": " oi", "start": 0, "end": .4}, {"word": " tudo", "start": .4, "end": 1}]}])
    assert segs == [[0, 0.4, "oi"], [0.4, 1, "tudo"]]


def test_projeto_plano_e_pagina(base, tmp_path):
    p = X.novo(base, "Teste", _audio(tmp_path), SRT)
    p["plano"] = PLANO
    X.salvar(p, base)
    r = X.resumo(X.carregar(p["id"], base))
    assert r["ok"] and [c["tipo"] for c in r["cenas"]] == ["texto", "escada", "mao"]
    assert not r["avisos"], r["avisos"]
    d, C = X.escrever_tela(X.carregar(p["id"], base), base)
    html = open(os.path.join(d, "index.html"), encoding="utf-8").read()
    assert "window.render" in html and "ONE PAIR" in html.replace("&quot;", "\"") and 'src="maos/m3.html"' in html
    assert os.path.isfile(os.path.join(d, "maos", "m3.html"))
    assert any(k == "impact" for _t, k in C.snd) and any(k in ("ficha", "carta") for _t, k in C.snd)
    assert C.capitulos == [("RANK", C.linha[1]["ini"])]


def test_frase_que_nao_existe_vira_aviso(base, tmp_path):
    p = X.novo(base, "Teste", _audio(tmp_path), SRT)
    p["plano"] = {"cenas": [{"tipo": "texto", "de": 0, "linhas": [{"texto": "A", "estilo": "grande", "em": "frase inventada pela IA"}]}]}
    X.salvar(p, base)
    assert any("frase inventada" in a for a in X.resumo(p)["avisos"])


def test_texto_e_escapado(base, tmp_path):
    p = X.novo(base, "T", _audio(tmp_path), SRT)
    p["plano"] = {"cenas": [{"tipo": "texto", "de": 0, "linhas": [{"texto": "<script>x</script>", "estilo": "grande"}]}]}
    X.salvar(p, base)
    _d, C = X.escrever_tela(p, base)
    assert "<script>x" not in "".join(C.cenas_html)


def test_exemplo_poker_e_valido():
    with open(os.path.join(X.AQUI, "assets", "explicador", "exemplo_poker.json"), encoding="utf-8") as f:
        pl = json.load(f)
    tipos = {c["tipo"] for c in pl["cenas"]}
    assert {"texto", "marca", "icones", "fichas", "cartas", "escada", "comparacao", "mao", "dicas", "lista"} <= tipos
    for c in pl["cenas"]:
        assert hasattr(X.Construtor, "c_" + c["tipo"])


def test_keyframes_seguram_e_aceleram():
    kf = X._keyframes([(0, 0), (5, 2), (6, 6)])
    assert kf[0] == [0, 0] and [2, 2] in kf and [5, 2] in kf and kf[-1] == [6, 6]
    assert X._inverso(kf, 1.0) == pytest.approx(1.0)


def test_plano_ia_com_ia_falsa(base, tmp_path):
    p = X.novo(base, "T", _audio(tmp_path), SRT)
    visto = {}

    def falsa(recurso, sistema, conteudo, **kw):
        visto.update(recurso=recurso, conteudo=conteudo)
        return json.dumps(PLANO)
    r = X.plano_ia(p["id"], base, "use poker", chamar=falsa)
    assert r["n_cenas"] == 3 and visto["recurso"] == "explicador" and "[2.0]" in visto["conteudo"] and "use poker" in visto["conteudo"]


def test_renderiza_e_monta_editor(base, tmp_path):
    p = X.novo(base, "Curto", _audio(tmp_path), SRT)
    p["plano"] = PLANO
    p["op"].update(resolucao="1080p", trabalhadores=2, musica="sintetizada")
    X.salvar(p, base)
    r = X.renderizar(p["id"], base)
    mp4 = os.path.join(X.pasta(p["id"], base), "saida", r["mp4"])
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", mp4],
                         capture_output=True, text=True).stdout
    assert "video,1920,1080" in out and "audio" in out
    jd = str(tmp_path / "job")
    os.makedirs(jd)
    m = X.montar_editor(X.carregar(p["id"], base), base, jd)
    assert len(m["segmentos"]) == 3 and all(os.path.isfile(s["override_source"]["value"]) for s in m["segmentos"])
    assert m["musica"] and os.path.isfile(m["audio"]) and m["qualidade"] == "1080p"


def test_rotas(base, tmp_path, monkeypatch):
    import flask
    import explicador_rotas
    app = flask.Flask(__name__, template_folder=os.path.join(X.AQUI, "templates"))
    explicador_rotas.registrar(app, base)
    c = app.test_client()
    with open(_audio(tmp_path), "rb") as f:
        r = c.post("/explicador/novo", data={"titulo": "Rota", "audio": (f, "n.wav"), "srt": (__import__("io").BytesIO(SRT.encode()), "l.srt")},
                   content_type="multipart/form-data")
    assert r.status_code == 302
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    r = c.post(f"/explicador/{pid}/salvar", json={"plano": json.dumps(PLANO), "op": {"acento": "#ff0055", "resolucao": "9k"}})
    d = r.get_json()
    assert d["ok"] and d["projeto"]["op"]["resolucao"] == "2160p" and len(d["resumo"]["cenas"]) == 3
    assert c.post(f"/explicador/{pid}/salvar", json={"plano": "{quebrado"}).status_code == 400
    h = c.get(f"/explicador/{pid}/previa/").get_data(as_text=True)
    assert "--ac:#ff0055" in h and "/explicador/fontes" in h and f"/explicador/{pid}/audio" in h
    assert c.get(f"/explicador/{pid}/previa/maos/m3.html").status_code == 200
    assert c.get(f"/explicador/{pid}/mp4").status_code == 404
    assert c.post(f"/explicador/{pid}/editor").status_code == 400


def test_tecnica_caso_contagem_e_icones_novos(base, tmp_path):
    p = X.novo(base, "T", _audio(tmp_path), SRT)
    p["plano"] = {"cenas": [{"tipo": "icones", "de": 0, "tecnica": {"n": 1, "nome": "COLLUSION", "icone": "usuarios", "em": "Welcome"},
                             "linhas": [{"texto": "2010 · WPT BARCELONA", "estilo": "caso", "em": "Here is the goal"},
                                        {"texto": "$22,000,000", "estilo": "contagem", "sub": "PAID BACK", "em": "One pair"}],
                             "itens": [{"icone": "robo", "texto": "BOTS", "em": "they fold"}, {"icone": "mascara", "texto": "GHOST", "em": "Thanks"}]}]}
    X.salvar(p, base)
    _d, C = X.escrever_tela(p, base)
    h = "".join(C.cenas_html)
    assert 'class="tec"' in h and "#1 · COLLUSION" in h and '<div class="caso"><b>2010</b>' in h
    assert 'class="cnt" data-v="22000000"' in h
    assert "data-pre=\"$\"" in h and "#22d3ee" in h  # o robô
    assert not C.avisos


def test_documentario_foto_video_trechos(base, tmp_path):
    from PIL import Image
    p = X.novo(base, "Doc", _audio(tmp_path), SRT)
    md = os.path.join(p["_dir"], "midia")
    Image.new("RGB", (400, 600), (120, 80, 40)).save(os.path.join(md, "f.jpg"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x240:d=8:r=30", "-f", "lavfi", "-i", "sine=f=440:d=8",
                    "-vf", "pad=426:240:53:0", "-shortest", os.path.join(md, "v.mp4")], check=True)
    p["trechos"] = [{"arquivo": "v.mp4", "ini": 1, "fim": 3, "antes_de": "One pair beats", "exato": True}]
    p["plano"] = {"cenas": [{"tipo": "capitulo", "de": 0, "numero": "CHAPTER ONE", "titulo": "THE KID", "arquivo": "f.jpg"},
                            {"tipo": "video", "trecho": 1},
                            {"tipo": "foto", "de": "One pair beats", "fotos": [{"arquivo": "f.jpg", "rotulo": "LAS VEGAS · 1997"}]},
                            {"tipo": "video", "de": "You bet", "cortes": [{"arquivo": "v.mp4", "ini": 4, "zoom": 1.5}]},
                            {"tipo": "citacao", "de": "Thanks", "texto": "Nobody ever beat me.", "autor": "STU"}]}
    p["op"]["estilo"] = "documentario"
    X.salvar(p, base)
    q = X.carregar(p["id"], base)
    d, C = X.escrever_tela(q, base)
    assert not C.avisos, C.avisos
    ins = C.inseridos[0]
    assert ins["t1"] - ins["t0"] == pytest.approx(2.0, abs=0.1) and ins["t0"] > 1.5
    assert C.linha[1]["ini"] == pytest.approx(ins["t0"] - 0.12, abs=0.05)
    assert C.END > 6 + 2  # a narração ficou mais longa com o trecho
    assert C.clipes and all(os.path.isfile(os.path.join(q["_dir"], "cache", c["h"], "00001.jpg")) for c in C.clipes)
    assert C.clipes[0]["recorte"][2] <= 330  # tirou as bordas pretas
    h = open(os.path.join(d, "index.html"), encoding="utf-8").read()
    assert 'class="doc"' in h and "DP Garamond" in h and "CHAPTER ONE" in h and "../cache/fotos/" in h
