"""🔥 v84_291 — Momentos mais vistos: gráfico, transcrição, picos, escolha, corte vertical seguindo o alvo, curto."""
import json
import os
import subprocess

import pytest

import momentos_yt as M


# ---------------------------------------------------------------------------------------------------- ajudantes
def _video_robo(cam, dur=12):
    """1920x1080: fundo cinza com ruído e um 'robô' (quadrado vermelho) andando da esquerda (x≈300) pra direita (x≈1500)."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=1920x1080:r=25:d={dur}",
                    "-f", "lavfi", "-i", f"color=c=red:s=200x300:r=25:d={dur}", "-f", "lavfi", "-i", f"sine=f=440:d={dur}",
                    "-filter_complex", f"[0:v][1:v]overlay=x='200+1200*t/{dur}':y=400[v]", "-map", "[v]", "-map", "2:a",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", cam], check=True)


class VisaoVermelha(M.Visao):
    """👁 de mentira: 'acha' o alvo procurando os pixels vermelhos (no lugar do Moondream)."""

    def __init__(self):
        self.vc = {"backend": "hf"}
        self.erro = ""
        self.chamar = None

    def descrever(self, img, contexto=""):
        return "A red robot moves across a gray court."

    def achar(self, img, alvo):
        from PIL import Image
        im = Image.open(img).convert("RGB")
        w, h = im.size
        xs = [x for x in range(0, w, 4) for y in range(0, h, 20) if (lambda p: p[0] > 180 and p[1] < 80 and p[2] < 80)(im.getpixel((x, y)))]
        if not xs:
            return []
        return [(min(xs) / w, 0.3, max(xs) / w, 0.7)]


class YDLFalso:
    INFO = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, link, download=False):
        return YDLFalso.INFO

    def download(self, links):
        pass


class ModuloFalso:
    YoutubeDL = YDLFalso


def _heat(dur, pico_t, n=100):
    passo = dur / n
    return [{"start_time": i * passo, "end_time": (i + 1) * passo,
             "value": 0.2 + 0.8 * max(0.0, 1 - abs((i + 0.5) * passo - pico_t) / (dur * 0.04))} for i in range(n)]


# ---------------------------------------------------------------------------------------------------- partes puras
def test_transcricao_colada_do_youtube_e_srt():
    leg = M.legenda_colada("0:00\nOlá pessoal\n0:05\no robô entra\n1:02:03\nfim")
    assert [x["t0"] for x in leg] == [0, 5, 3723] and leg[0]["t1"] == 5 and leg[1]["texto"] == "o robô entra"
    leg = M.legenda_colada("1\n00:00:01,000 --> 00:00:03,500\nprimeira\n\n2\n00:00:04,000 --> 00:00:06,000\nsegunda")
    assert leg == [{"t0": 1.0, "t1": 3.5, "texto": "primeira"}, {"t0": 4.0, "t1": 6.0, "texto": "segunda"}]
    assert M.legenda_colada("0:13 frase na mesma linha")[0] == {"t0": 13.0, "t1": 17.0, "texto": "frase na mesma linha"}


def test_grafico_colado_do_youtube():
    svg = ('<svg class="ytp-heat-map-svg" viewBox="0 0 1000 100"><path class="ytp-heat-map-path" '
           'd="M 0.0,100.0 C 1.0,90.0 2.0,90.0 5.0,90.0 C 100,90 200,90 300,90 C 320,10 330,0 340,0 C 360,10 380,90 400,90 C 600,90 800,90 1000,90"></path></svg>')
    h = M.heatmap_colado(svg, 500)
    assert len(h) == 100 and h[-1][1] == 500
    top = max(h, key=lambda x: x[2])
    assert 150 <= top[0] <= 180 and top[2] == 1.0  # o pico em x≈340/1000 → ~170 s


def test_legenda_json3_junta_os_pedacos():
    d = {"events": [{"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "the robot"}]},
                    {"tStartMs": 1500, "dDurationMs": 1500, "segs": [{"utf8": "jumps."}]},
                    {"tStartMs": 3000, "dDurationMs": 100, "segs": [{"utf8": "\n"}]},
                    {"tStartMs": 5000, "dDurationMs": 2000, "segs": [{"utf8": "Wow"}]}]}
    assert M.legenda_json3(d) == [{"t0": 0.0, "t1": 3.0, "texto": "the robot jumps."}, {"t0": 5.0, "t1": 7.0, "texto": "Wow"}]


def test_candidatos_nos_picos_com_preparacao_antes():
    dur = 600
    heat = M.heatmap_do_info({"heatmap": _heat(dur, 160) + []})
    # um segundo pico menor em 420 s
    for h in heat:
        if 400 <= h[0] <= 440:
            h[2] = max(h[2], 0.7)
    leg = [{"t0": float(t), "t1": float(t + 5), "texto": f"frase {t}"} for t in range(0, dur, 5)]
    cs = M.candidatos(heat, dur, 20, 60, 4, leg, [{"t": 161, "texto": "2:41 kkkk", "curtidas": 50}])
    assert cs[0]["pico"] == pytest.approx(162, abs=4) and cs[0]["t0"] < 160 < cs[0]["t1"]
    assert 20 <= cs[0]["t1"] - cs[0]["t0"] <= 66
    assert cs[0]["t0"] % 5 == 0 and cs[0]["t1"] % 5 == 0  # encaixou nas frases
    assert cs[0]["comentarios"] and any(abs(c["pico"] - 420) < 25 for c in cs)


def test_expressao_do_crop_segue_e_pula_no_corte():
    tr = [(0.0, 0.2), (2.0, 0.6), (2.02, 0.6), (2.03, 0.9), (4.0, 0.9)]
    e = M.expressao_x(tr, 1920, 606)
    calc = lambda t: eval(e.replace("gte", "_gte").replace("lt(", "_lt(").replace("t-", f"{t}-").replace("(t,", f"({t},"),  # noqa: E731
                          {"_gte": lambda a, b: float(a >= b), "_lt": lambda a, b: float(a < b)})
    assert calc(0.5) == pytest.approx(0.3 * 1920 - 303, abs=2)
    assert calc(3.0) == pytest.approx(min(1920 - 606, 0.9 * 1920 - 303), abs=2)


# ---------------------------------------------------------------------------------------------------- o caminho todo
def test_analisar_escolher_cortar_vertical_e_virar_curto(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    base = str(tmp_path)
    fonte = str(tmp_path / "longo.mp4")
    _video_robo(fonte, 12)
    YDLFalso.INFO = {"title": "CUE7 robot", "duration": 12, "heatmap": _heat(12, 6.0), "uploader": "ALVARK",
                     "description": "basket robot", "chapters": [{"start_time": 0, "title": "Intro"}],
                     "comments": [{"text": "0:06 the robot!!", "like_count": 900, "parent": "root"}]}

    def baixador(url, d):
        cam = os.path.join(d, "x.mp4")
        import shutil
        shutil.copy(fonte, cam)
        return cam
    pedidos = []

    def chamar(recurso, system, conteudo, **kw):
        pedidos.append(conteudo)
        return {"cortes": [{"candidato": 0, "inicio": 2.0, "fim": 10.0, "titulo_pt": "O robô cruza", "motivo_pt": "pico",
                            "alvo_en": "red robot", "alvo_pt": "robô vermelho", "modo": "explicar", "ideia_gancho_pt": "Como ele anda?"}]}
    p = M.novo(base, "https://www.youtube.com/watch?v=N2jUcdTBeIY",
               {"n_cortes": 1, "dur_min": 5, "dur_max": 10, "transcricao_colada": "0:02\nlook at this robot\n0:06\nit crosses the court\n0:10\nwow",
                "usar_navegador": False})
    p = M.analisar(base, p["id"], ytdlp_module=ModuloFalso, baixador=baixador, chamar=chamar)
    assert p["heat_fonte"] == "yt-dlp" and p["legenda_fonte"] == "colada" and p["candidatos"]
    assert "Candidate 0" in pedidos[0] and "look at this robot" in pedidos[0] and "the robot!!" in pedidos[0]
    c = p["cortes"][0]
    assert (c["t0"], c["t1"], c["alvo"], c["modo"]) == (2.0, 10.0, "red robot", "explicar")

    c = M.produzir_corte(base, p["id"], 1, baixador=baixador, visao=VisaoVermelha())
    out = os.path.join(M.pasta(base, p["id"]), "cortes", c["arquivo"])
    info = M.sondar(out)
    assert (info["w"], info["h"]) == (1080, 1920) and info["dur"] == pytest.approx(8, abs=0.3)
    assert c["enquadramento"]["achados"] > 5 and c["visual"]
    # o robô fica no meio do vertical no começo E no fim (o recorte andou junto)
    from PIL import Image
    for t in (2.5, 7.5):  # (o comecinho abre de propósito)
        q = str(tmp_path / f"q{t}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", q], check=True)
        im = Image.open(q).convert("RGB")
        vermelho = [x for x in range(0, 1080, 8) if (lambda px: px[0] > 180 and px[1] < 80)(im.getpixel((x, 960)))]
        assert vermelho, f"robô sumiu do quadro em {t}s"
        assert 200 < sum(vermelho) / len(vermelho) < 880, (t, sum(vermelho) / len(vermelho))

    import curtos as CT
    import curtos_comentario as CC
    cid = M.criar_curto(base, p["id"], 1)
    q = CT.carregar(base, cid)
    assert q["modelo"] == "comentario" and q["config"]["proporcao"] == "9:16" and q["config"]["motor_perfil"] == "chatterbox_turbo"
    assert CC.dados(q)["modo_link"] == "explicar" and q["link_rapido"]["link"].endswith("?t=2")
    linhas = CC.dados(q)["linhas"]
    assert any(l["tipo"] == "fala" and l["texto"].startswith("look at this") and l["t0"] == 0 for l in linhas)
    assert any(l["tipo"] == "visual" for l in linhas)
    assert any("the robot!!" in x["texto"] for x in CC.dados(q)["info_link"]["comentarios"])
    assert "Como ele anda?" in q["config"]["extra"]
    assert M.carregar(base, p["id"])["cortes"][0]["curto"] == cid


def test_produzir_chama_o_pipeline_dos_curtos(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    base = str(tmp_path)
    fonte = str(tmp_path / "longo.mp4")
    _video_robo(fonte, 8)
    p = M.novo(base, "https://youtu.be/N2jUcdTBeIY", {"enquadrar": "desfocado"})
    p["cortes"] = [M.novo_corte(1, 1, 5, titulo="a"), M.novo_corte(2, 5, 7, titulo="b", usar=False)]
    M.salvar(base, p)
    import shutil
    rodou = []
    M.salvar_config_visao(base, {"backend": "nenhum"})
    r = M.produzir(base, p["id"], ate="editor", baixador=lambda u, d: shutil.copy(fonte, os.path.join(d, "v.mp4")),
                   rodar_link=lambda cid, voz, q, exp, prog: rodou.append((cid, exp)))
    assert r == "1/1 prontos" and len(rodou) == 1 and rodou[0][1] is False
    p = M.carregar(base, p["id"])
    assert p["cortes"][0]["estado"] == "✅ no editor" and p["cortes"][1]["estado"] == ""
    assert (M.sondar(os.path.join(M.pasta(base, p["id"]), "cortes", p["cortes"][0]["arquivo"]))["w"]) == 1080


def test_rotas(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    from flask import Flask
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(M.__file__), "templates"))
    M.registrar(app, str(tmp_path))
    monkeypatch.setattr(M, "analisar", lambda *a, **k: None)
    cl = app.test_client()
    assert cl.post("/momentos-yt/novo", json={"link": "https://example.com"}).get_json()["ok"] is False
    j = cl.post("/momentos-yt/novo", json={"link": "https://www.youtube.com/watch?v=N2jUcdTBeIY", "n_cortes": 2}).get_json()
    pid = j["id"]
    import time
    time.sleep(0.3)
    p = M.carregar(str(tmp_path), pid)
    p["dur"] = 300
    p["cortes"] = [M.novo_corte(1, 10, 40, alvo="robot")]
    M.salvar(str(tmp_path), p)
    j = cl.post(f"/momentos-yt/{pid}/corte/1", json={"t0": "0:20", "alvo": "red robot", "modo": "explicar"}).get_json()
    c = j["projeto"]["cortes"][0]
    assert (c["t0"], c["alvo"], c["modo"]) == (20.0, "red robot", "explicar")
    assert cl.post(f"/momentos-yt/{pid}/corte/1", json={"t1": "0:10"}).get_json()["ok"] is False
    j = cl.post(f"/momentos-yt/{pid}/corte/novo", json={"t0": "1:00", "t1": "1:30"}).get_json()
    assert [c["n"] for c in j["projeto"]["cortes"]] == [1, 2]
    assert json.loads(cl.get("/momentos-yt/lista").data)["lista"][0]["id"] == pid


def test_grafico_lido_no_navegador_com_capitulos(tmp_path, monkeypatch):
    """Player de mentira com o gráfico partido em 2 capítulos (cada pedaço é um <svg> com a própria largura)."""
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    monkeypatch.setenv("MOMENTOS_NAVEGADOR_OCULTO", "1")
    pag = tmp_path / "yt.html"
    pag.write_text("""<!doctype html><html><body style="margin:0">
<div style="position:absolute;left:100px;top:300px;width:1000px">
  <div style="display:flex;height:40px">
    <div class="ytp-heat-map-chapter" style="width:400px"><svg class="ytp-heat-map-svg" viewBox="0 0 1000 100" preserveAspectRatio="none" width="400" height="40">
      <path class="ytp-heat-map-path" d="M 0,100 L 0,90 L 500,90 L 750,10 L 1000,80 L 1000,100 Z"/></svg></div>
    <div class="ytp-heat-map-chapter" style="width:600px"><svg class="ytp-heat-map-svg" viewBox="0 0 1000 100" preserveAspectRatio="none" width="600" height="40">
      <path class="ytp-heat-map-path" d="M 0,100 L 0,80 L 1000,85 L 1000,100 Z"/></svg></div>
  </div>
  <div class="ytp-progress-bar" style="width:1000px;height:6px;background:red"></div>
</div><video></video></body></html>""", encoding="utf-8")
    h = M.heatmap_pelo_navegador(str(tmp_path), pag.as_uri(), 1000)
    top = max(h, key=lambda x: x[2])
    assert len(h) == 100 and 280 <= top[0] <= 320  # pico em 75% do 1º capítulo (40% da barra) = 30% do vídeo


def test_noticia_no_chatterbox_turbo_pede_ingles_com_tags(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    import curtos as CT
    p = CT.criar(str(tmp_path), "", "teste", [], "uma notícia", modelo="noticia")
    assert CT.regra_tags_turbo(p) == ""
    p["config"]["motor_perfil"] = "chatterbox_turbo"
    r = CT.regra_tags_turbo(p)
    assert "INGLÊS" in r and "[gasp]" in r and "[laugh]" in r
    assert "INGLÊS (Chatterbox Turbo" in CT.conteudo_roteiro(str(tmp_path), p)


# ---------------------------------------------------------------------------------------------------- 🎞 compilação
def test_compilacao_um_short_com_os_melhores_momentos(tmp_path, monkeypatch):
    monkeypatch.setenv("MOMENTOS_YT_DIR", str(tmp_path / "my"))
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    base = str(tmp_path)
    fonte = str(tmp_path / "longo.mp4")
    _video_robo(fonte, 20)
    YDLFalso.INFO = {"title": "CUE7 robot", "duration": 20, "heatmap": _heat(20, 12.0), "description": "Toyota CUE7"}
    import shutil

    def baixador(url, d):
        cam = os.path.join(d, "x.mp4")
        shutil.copy(fonte, cam)
        return cam
    pedidos = []

    def chamar(recurso, system, conteudo, **kw):
        pedidos.append((system, conteudo))
        return {"assunto_pt": "o robô CUE7", "alvo_en": "red robot", "gancho_pt": "O novo robô da Toyota simplesmente fez isso",
                "fatos_pt": "2 metros de altura; recorde de 2 mil acertos seguidos (conferir)",
                "cortes": [{"inicio": 1, "fim": 7, "titulo_pt": "entrada", "mostra_pt": "o robô entra", "alvo_en": "red robot"},
                           {"inicio": 9, "fim": 16, "titulo_pt": "o arremesso", "mostra_pt": "a cesta", "alvo_en": "red robot"}],
                "climax": {"corte": 1, "inicio": 11, "fim": 14.5, "por_que_pt": "a bola entra sem tocar no aro"}}
    p = M.novo(base, "https://www.youtube.com/watch?v=N2jUcdTBeIY",
               {"formato": "compilacao", "assunto": "o robô", "usar_navegador": False, "referencia": "O novo robô da Toyota simplesmente fez isso…"})
    p = M.analisar(base, p["id"], ytdlp_module=ModuloFalso, baixador=baixador, chamar=chamar)
    assert "best moments" in pedidos[0][0].lower() and "simplesmente fez isso" in pedidos[0][1] and "THE SHORT IS ABOUT: o robô" in pedidos[0][1]
    assert [c["n"] for c in p["cortes"]] == [1, 2] and p["compilacao"]["climax"] == {"n": 2, "t0": 11.0, "t1": 14.5, "por_que": "a bola entra sem tocar no aro"}

    M.salvar_config_visao(base, {"backend": "nenhum"})
    rodou = []
    r = M.produzir(base, p["id"], ate="exportar", baixador=baixador, rodar_link=lambda cid, voz, q, exp, prog: rodou.append((cid, exp)))
    assert r == "pronto" and rodou and rodou[0][1] is True
    p = M.carregar(base, p["id"])
    assert p["compilacao"]["estado"] == "✅ pronto"
    largo = os.path.join(M.pasta(base, p["id"]), "cortes", "climax_largo.mp4")
    assert (M.sondar(largo)["w"], round(M.sondar(largo)["dur"])) == (1920, 4)  # largo, com o tamanho do momento

    import curtos as CT
    import curtos_comentario as CC
    q = CT.carregar(base, p["compilacao"]["curto"])
    assert q["modelo"] == "explicativo" and q["config"]["midia"] == "minhas" and q["config"]["proporcao"] == "9:16"
    assert [m["id"] for m in q["midias"]] == ["M1", "M2", "W1"] and [m["id"] for m in CC.clipes(base, q)] == ["M1", "M2"]
    assert q["momento_original"] == {"midia": "W1", "material": "M2", "de": 2.0, "ate": 5.5, "descricao": "a bola entra sem tocar no aro"}
    assert "material M2 with de/ate inside 2.0-5.5" in q["config"]["extra"] and "Tell me in the comments" in q["config"]["extra"]
    assert "recorde de 2 mil" in q["noticia"]["texto"] and "simplesmente fez isso" in CC.dados(q)["referencia"]
    assert "## YOUR VIDEO SOURCES" in CC.conteudo_roteiro(base, q)


def test_som_original_entra_depois_da_frase_que_anuncia(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    import curtos as CT
    p = {"momento_original": {"midia": "W1", "material": "M2", "de": 2.0, "ate": 5.5, "descricao": "a cesta"},
         "roteiro": {"blocos": [{"cenas": [{"material": "M1", "de": 0, "ate": 3}]},
                                {"cenas": [{"material": "M2", "de": 0, "ate": 2}, {"material": "M2", "de": 2.5, "ate": 4}]},
                                {"cenas": [{"material": "M1", "de": 4, "ate": 6}]}]},
         "gravacao": {"dur": 20, "alinhamento": [{"bloco": 0, "start": 0, "end": 5}, {"bloco": 1, "start": 5.2, "end": 11.0},
                                                 {"bloco": 2, "start": 11.2, "end": 20}]}}
    cs = CT.cortes_com_som_original(p)
    assert cs == [{"insertion_point": 11.15, "description": "a cesta", "audio_mode": "pause", "midia": "W1"}]
    p["momento_original"]["material"] = "M9"  # nenhuma cena bate: o bloco do meio
    assert CT.cortes_com_som_original(p)[0]["insertion_point"] == 5.15
    import prompt_builder
    parsed = prompt_builder.parse_ai_response(json.dumps({"segments": [{"start": 0, "end": 20, "provider": "pexels", "query": "robot"}],
                                                          "cutaway_suggestions": cs}), total_duration=20)
    assert parsed.cutaway_suggestions[0]["midia"] == "W1" and parsed.cutaway_suggestions[0]["audio_mode"] == "pause"
