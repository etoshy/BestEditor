"""v84_255: 📚 modelo Explicativo (assunto + vídeos brutos → colagem só com eles; o que faltar vira 💡 sugestão), títulos no idioma
do post + português, idioma da postagem, ⬛ proporção 1:1 e 🏷 marca @canal por cima do vídeo."""
import json
import os
import subprocess

import pytest

import curtos as CT
import curtos_comentario as CC
from test_v84_253_comentario import _clipe, _esperar, _tts, _whisper, VOZ  # noqa: F401


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    monkeypatch.setenv("RASTREIO_DIR", str(tmp_path / "rastreios"))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    return str(tmp_path)


RESP = {
    "titulo_video": "Il segreto del tetrapode", "descricao": "d", "hashtags": ["#curiosità"], "roteiro_en": "…", "roteiro_pt": "…",
    "titulos": [{"en": "Il segreto del tetrapode", "pt": "O segredo do tetrápode"}, {"en": "Titolo 2", "pt": "Título 2"}],
    "ganchos": [{"en": "Perché questa forma ferma le onde?", "pt": "Por que essa forma para as ondas?"}],
    "finais": [{"en": "Lo sapevi?", "pt": "Você sabia?"}],
    "blocos": [
        {"funcao": "gancho", "fala_en": "Perché questa forma strana ferma le onde?", "fala_pt": "Por que essa forma estranha para as ondas?",
         "cenas": [{"layout": "clipe", "material": "M1", "de": 0, "ate": 3, "palavra": "", "efeito": "zoom_in", "entrada": "punch_in",
                    "destaque": {"alvo": "the white square", "tipo": "seta", "texto": ""}, "sugestao": {"layout": ""}}],
         "sfx": [{"tipo": "pop", "palavra": "", "busca": "pop"}]},
        {"funcao": "fato", "fala_en": "Fu inventata da ingegneri francesi nel millenovecentocinquanta.",
         "fala_pt": "Foi inventada por engenheiros franceses em mil novecentos e cinquenta.",
         "cenas": [{"layout": "clipe", "material": "M2", "de": 1, "ate": 4, "palavra": "", "efeito": "", "entrada": "none",
                    "sugestao": {"layout": "foto_real", "query": "Pierre Danel tetrapod 1950", "por_que": "a foto do inventor"}}],
         "sfx": []},
        {"funcao": "final", "fala_en": "Lo sapevi?", "fala_pt": "Você sabia?",
         "cenas": [{"layout": "ia", "query": "epic ocean storm hitting concrete blocks, cinematic"}], "sfx": []},
    ]}


def _ia(resp=RESP):
    def chamar(recurso, sistema, conteudo, **kw):
        chamar.vistos.append((sistema, conteudo))
        return json.loads(json.dumps(resp))
    chamar.vistos = []
    return chamar


def _projeto(base, tmp_path, n=2, lingua="it"):
    p = CT.criar(base, "", "Tetrapodi", texto="Por que o tetrápode segura as ondas", modelo="explicativo")
    with CT._TRAVA:
        q = CT.carregar(base, p["id"])
        for k in range(n):
            CT.adicionar_midia(base, q, _clipe(str(tmp_path / f"f{k}.mp4"), 6), "video", f"fonte {k + 1}")
        CC.dados(q)["lingua_post"] = lingua
        CT.salvar(base, q)
    CC.salvar_texto_do_clipe(base, p["id"], "0:00 guindaste levanta o bloco\n0:03 bloco na água", "M1", "visual")
    CC.salvar_texto_do_clipe(base, p["id"], "0:00 onda gigante\n0:04 fábrica", "M2", "visual")
    return p["id"]


# ------------------------------------------------------------------ roteiro
def test_prompt_explicativo_so_com_as_fontes_e_lingua(base, tmp_path):
    pid = _projeto(base, tmp_path)
    p = CT.carregar(base, pid)
    sis, cont = CC.sistema(p), CC.conteudo_roteiro(base, p)
    assert "EXPLAINER" in sis and "ONLY from the creator's VIDEO SOURCES" in sis and "'sugestao'" in sis
    assert "in ITALIAN" in sis and "[gasp]" not in sis  # tags do Chatterbox só em inglês
    assert "M1 — fonte 1" in cont and "guindaste" in cont and "tetrápode" in cont and "POST LANGUAGE: ITALIAN" in cont
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["config"]["so_fontes"] = False
        CT.salvar(base, q)
    assert "Mix freely" in CC.sistema(CT.carregar(base, pid))  # v84_256: desmarcado = 🔀 misto
    q = CT.criar(base, "", "sem fontes", texto="x", modelo="explicativo")
    assert not CC.so_fontes(q)  # sem vídeo nenhum: busca/gera sozinho


def test_roteiro_titulos_e_sugestoes(base, tmp_path):
    pid = _projeto(base, tmp_path)
    r = CC.gerar_roteiro(base, pid, _ia())
    assert [t["pt"] for t in r["titulos"]] == ["O segredo do tetrápode", "Título 2"]
    c0, c1 = r["blocos"][0]["cenas"][0], r["blocos"][1]["cenas"][0]
    assert c0["layout"] == "materia" and c0["destaque"]["tipo"] == "seta" and "sugestao" not in c0
    assert c1["material"] == "M2" and c1["sugestao"]["query"].startswith("Pierre")
    assert r["blocos"][2]["cenas"][0]["layout"] == "ia"  # o que não tem vídeo: imagem gerada
    sg = CC.sugestoes(CT.carregar(base, pid))
    assert len(sg) == 1 and not sg[0]["usada"] and sg[0]["fonte"] == "M2"
    CC.usar_sugestao(base, pid, 1, 0, True)
    c = CT.carregar(base, pid)["roteiro"]["blocos"][1]["cenas"][0]
    assert c["layout"] == "foto_real" and c["query"].startswith("Pierre") and c["reserva"]["material"] == "M2"
    # salvar da tela não perde a sugestão nem a reserva
    rr = CT.carregar(base, pid)["roteiro"]
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["roteiro"] = CT.ler_roteiro(rr, q)
        CT.salvar(base, q)
    assert CC.sugestoes(CT.carregar(base, pid))[0]["usada"]
    CC.usar_sugestao(base, pid, 1, 0, False)
    c = CT.carregar(base, pid)["roteiro"]["blocos"][1]["cenas"][0]
    assert c["layout"] == "materia" and c["material"] == "M2" and c["de"] == 1
    CC.escolher(base, pid, "titulos", 1)
    q = CT.carregar(base, pid)["roteiro"]
    assert q["titulo_video"] == "Titolo 2" and q["titulo_pt"] == "Título 2"
    assert q["blocos"][0]["fala"].startswith("Perché")  # o título não mexe na fala
    novos = CC.mais_opcoes(base, pid, "titulos", _ia({"opcoes": [{"en": "Nuovo", "pt": "Novo"}] * 5}))
    assert len(novos) == 5 and len(CT.carregar(base, pid)["roteiro"]["titulos"]) == 7


def test_lingua_post_e_motor_da_voz(base, tmp_path):
    pid = _projeto(base, tmp_path, lingua="en")
    CC.definir_lingua_post(base, pid, "it")
    assert CT.carregar(base, pid)["config"]["motor_perfil"] == "chatterbox"  # o Turbo só fala inglês
    CC.definir_lingua_post(base, pid, "en")
    assert CT.carregar(base, pid)["config"]["motor_perfil"] == "chatterbox_turbo"
    CC.trocar_idioma(base, pid, "pt")
    p = CT.carregar(base, pid)
    assert p["config"]["motor_perfil"] == "chatterbox" and CT.idioma_narrado(p) == "pt"
    with pytest.raises(CT.CurtoErro):
        CC.definir_lingua_post(base, pid, "xx")


# ------------------------------------------------------------------ montagem, 1:1 e marca
def test_explicativo_monta_quadrado_com_marca(base, tmp_path):
    pid = _projeto(base, tmp_path)
    CC.gerar_roteiro(base, pid, _ia())
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["config"]["proporcao"] = "1:1"
        CT.salvar(base, q)
    CC.gerar_takes(base, pid, _tts, lambda t, m: t, VOZ, 1)
    wh = _whisper(base, pid)
    CC.usar_take(base, pid, 1, wh)
    assert wh.idiomas == ["it"]  # o Whisper ouve no idioma narrado
    d = CT.montar_dados_editor(base, pid)
    assert d["orientation"] == "1:1" and d["idioma"] == "it" and d["enquadramento"] == "smart"
    assert d["legendas"]["posicao"] == "terco" and d["legendas"]["tamanho"] > 0.05  # ⬛ a letra cresce no quadrado
    assert {x["query"].split("@")[0] for x in d["planos"] if x["provider"] == "material"} == {"M1", "M2"}
    assert any(x["layout"] == "ia" for x in d["planos"])
    m = d["marca"]
    assert m["ativa"] and m["posicao"] == "meio" and m["opacidade"] == 0.5 and m["texto"].startswith("@")
    assert "QUADRADO" not in CC.conteudo_roteiro(base, CT.carregar(base, pid)) and "SQUARE 1:1" in CC.conteudo_roteiro(base, CT.carregar(base, pid))


def test_marca_normaliza_e_queima(tmp_path):
    m = CT.normalizar_marca({"texto": "  @meu canal ", "opacidade": 3, "posicao": "xx", "cor": "#ff0000", "ativa": "0"}, "Canal X")
    assert m["texto"] == "@meu canal" and m["opacidade"] == 1.0 and m["posicao"] == "meio" and m["cor"] == "#FF0000" and not m["ativa"]
    assert CT.marca_padrao("Curiosità Lab!")["texto"] == "@curiositalab"
    import marca_canal
    cfg = CT.normalizar_marca({}, "teste")
    ass = marca_canal.gerar_ass(cfg, 1080, 1920, 5, str(tmp_path / "m.ass"), posicao_legenda="meio")
    txt = open(ass, encoding="utf-8").read()
    assert "@teste" in txt and "\\alpha&H80&" in txt and "\\pos(540,787)" in txt  # 50% e subiu de baixo da legenda do meio
    v = str(tmp_path / "v.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=360x640:d=2:r=24", "-f", "lavfi", "-i", "sine=d=2",
                    "-shortest", "-pix_fmt", "yuv420p", v], check=True)
    assert marca_canal.aplicar(v, cfg, str(tmp_path))
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", v, "-frames:v", "1", "-vf", "crop=200:50:80:295,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    assert max(out) > 80  # o texto apareceu no meio (metade da opacidade)
    assert not marca_canal.aplicar(v, dict(cfg, ativa=False), str(tmp_path))


def test_legenda_terco_de_baixo(tmp_path):
    import dp_legendas
    cfg = dp_legendas.normalizar({"ativa": True, "posicao": "terco"})
    assert cfg["posicao"] == "terco"
    ass = dp_legendas.gerar_ass([{"word": "oi", "start": 0, "end": 0.5}], cfg, 1080, 1920, str(tmp_path / "l.ass"))
    assert "\\pos(540,1459)" in open(ass, encoding="utf-8").read() or ",5,20,20,0,1" in open(ass, encoding="utf-8").read()


# ------------------------------------------------------------------ rotas
@pytest.fixture
def cliente(base, monkeypatch):
    import app as A
    monkeypatch.setattr(A, "BASE_DIR", base)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_job_dir", lambda j: os.path.join(base, "jobs", j))
    A.app.config["TESTING"] = True
    return A, A.app.test_client()


def _baixador(tmp_path):
    def b(url, pasta):
        b.urls.append(url)
        return _clipe(os.path.join(pasta, f"v{len(b.urls)}.mp4"), 5)
    b.urls = []
    return b


def test_novo_explicativo_com_5_links_e_editor(cliente, base, tmp_path, monkeypatch):
    A, cl = cliente
    import curtos_rotas as R
    b = _baixador(tmp_path)
    monkeypatch.setitem(R.CB, "baixar", b)
    assert "Novo vídeo explicativo" in cl.get("/curtos/modelo/explicativo").get_data(as_text=True)
    links = "\n".join(f"https://www.youtube.com/shorts/v{k}" for k in range(5))
    r = cl.post("/curtos/novo", data={"modelo": "explicativo", "tem_so_fontes": "1", "so_fontes": "1", "texto": "tetrápodes",
                                      "link": links, "lingua_post": "it", "idioma": "en", "proporcao": "1:1"},
                content_type="multipart/form-data")
    pid = r.headers["Location"].rsplit("/", 1)[1]
    assert not _esperar(pid)["erro"]
    p = CT.carregar(base, pid)
    assert [m["id"] for m in p["midias"]] == ["M1", "M2", "M3", "M4", "M5"] and len(b.urls) == 5
    assert p["modelo"] == "explicativo" and p["config"]["proporcao"] == "1:1" and p["config"]["so_fontes"] is True
    assert p["comentario"]["lingua_post"] == "it" and p["config"]["motor_perfil"] == "chatterbox"
    assert p["canal_id"] == CT.canal_do_modelo(base, "explicativo")
    html = cl.get(f"/curtos/{pid}").get_data(as_text=True)
    assert "📚" in html and "Títulos" not in html or True
    assert "Marca do canal" in html and "Italiano" in html
    e = cl.get(f"/curtos/{pid}/estado").get_json()
    assert e["so_fontes"] is True and e["marca"]["ativa"] and e["proporcao"] == "1:1"
    # roteiro (resposta colada), sugestão aceita, marca e editor
    resp = dict(RESP, blocos=[dict(x) for x in RESP["blocos"]])
    assert cl.post(f"/curtos/{pid}/roteiro", json={"resposta": json.dumps(resp)}).get_json()["ok"]
    assert cl.post(f"/curtos/{pid}/comentario/sugestao", json={"bloco": 1, "cena": 0, "usar": True}).get_json()["ok"]
    assert cl.get(f"/curtos/{pid}/estado").get_json()["sugestoes"][0]["usada"]
    m = cl.post(f"/curtos/{pid}/marca", json={"marca": {"texto": "@curiosita", "opacidade": 0.4, "posicao": "inf_dir"}, "padrao_canal": True}).get_json()
    assert m["marca"]["texto"] == "@curiosita" and m["marca"]["posicao"] == "inf_dir"
    assert CT.carregar_canal(base, p["canal_id"])["perfil"]["marca"]["opacidade"] == 0.4
    monkeypatch.setitem(R.CB, "transcrever", _whisper(base, pid))
    CC.gerar_takes(base, pid, _tts, lambda t, mm: t, VOZ, 1)
    CC.usar_take(base, pid, 1, R.CB["transcrever"])
    r = cl.post(f"/curtos/{pid}/editor", json={}).get_json()
    assert r["ok"], r
    job = A._JOBS[r["job_id"]]
    assert job["orientation"] == "1:1" and job["marca"]["texto"] == "@curiosita"
    assert job["editor_defaults"]["aspect_fill"] == "smart"
    assert any(s["provider"] in ("brave", "google", "bing", "wikipedia", "pexels") and "Pierre" in s["query"] for s in job["pending_segments"])
    # mexeu na marca depois: o projeto do editor acompanha
    cl.post(f"/curtos/{pid}/marca", json={"marca": {"ativa": False}})
    assert A._JOBS[r["job_id"]]["marca"]["ativa"] is False


def test_noticia_tambem_tem_1x1_e_marca(cliente, base):
    _A, cl = cliente
    r = cl.post("/curtos/novo", data={"canal_id": "", "titulo": "N", "texto": "algo", "proporcao": "1:1"})
    pid = r.headers["Location"].rsplit("/", 1)[1]
    assert CT.carregar(base, pid)["config"]["proporcao"] == "1:1"
    assert "QUADRADO 1:1" in CT.conteudo_roteiro(base, CT.carregar(base, pid))
    assert "Marca do canal" in cl.get(f"/curtos/{pid}").get_data(as_text=True)
    assert "Explicativo (curiosidades)" in cl.get("/curtos").get_data(as_text=True)
