"""v84_256: 💡 nichos de canais explicativos + ideias de vídeo; 📚 explicativo do zero com as imagens geradas no Flow (realistas)."""
import json
import os

import pytest

import curtos as CT
import curtos_comentario as CC
import curtos_nichos as CN
from test_v84_253_comentario import _esperar, _tts, _whisper, VOZ  # noqa: F401


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    monkeypatch.setenv("DP_EXTRAS_DIR", str(tmp_path / "extras"))
    import dp_extras
    dp_extras.recarregar()
    return str(tmp_path)


IDEIAS = {"ideias": [
    {"titulo_en": "Why manhole covers are round", "titulo_pt": "Por que a tampa de bueiro é redonda", "gancho_en": "This shape can't fall in.",
     "tema": "Um círculo não cai pelo próprio buraco; é fácil de rolar.", "por_que": "objeto do dia a dia", "visual": "tampa, rua, close"},
    {"titulo_en": "Why pencils are hexagonal", "titulo_pt": "Por que o lápis é sextavado", "gancho_en": "Your pencil has 6 sides for a reason.",
     "tema": "Não rola da mesa; segura melhor.", "por_que": "todo mundo tem um", "visual": "lápis na mesa, fábrica"},
    {"titulo_en": "WHY PENCILS ARE HEXAGONAL", "titulo_pt": "repetida", "gancho_en": "", "tema": "x", "por_que": "", "visual": ""},
]}

ROTEIRO_FLOW = {
    "titulo_video": "Why manhole covers are round", "descricao": "d", "hashtags": [], "roteiro_en": "…", "roteiro_pt": "…",
    "titulos": [{"en": "Why manhole covers are round", "pt": "Por que a tampa é redonda"}],
    "ganchos": [{"en": "This shape can't fall in.", "pt": "Essa forma não cai."}], "finais": [{"en": "Now you know.", "pt": "Agora você sabe."}],
    "blocos": [
        {"funcao": "gancho", "fala_en": "This shape can't fall in.", "fala_pt": "Essa forma não cai.",
         "cenas": [{"layout": "ia", "query": "extreme close-up of a round cast iron manhole cover on a wet city street at dusk"}], "sfx": []},
        {"funcao": "fato", "fala_en": "A worker rolls it back into place in seconds.", "fala_pt": "Um operário rola ela de volta em segundos.",
         "cenas": [{"layout": "ia_video", "query": "a city worker rolling a heavy round manhole cover across the asphalt, handheld"}], "sfx": []},
    ]}


def _ia(resp):
    def chamar(recurso, sistema, conteudo, **kw):
        chamar.vistos.append((sistema, conteudo))
        return json.loads(json.dumps(resp))
    chamar.vistos = []
    return chamar


def test_nichos_e_canal(base):
    ns = CN.nichos()
    assert len(ns) == 6 and {"Shape Reason", "Made In Minutes"} <= {n["nome"] for n in ns}
    c = CN.criar_canal_do_nicho(base, "shape_reason")
    assert c["nicho"] == "shape_reason" and c["modelo"] == "explicativo" and c["idioma"] == "en"
    assert c["perfil"]["estilo_ia"] == "realista" and c["perfil"]["legenda"]["posicao"] == "terco"
    assert "Shape Reason" in c["perfil"]["resumo"] and c["perfil"]["nicho"]["tema"]
    assert CN.criar_canal_do_nicho(base, "shape_reason")["id"] == c["id"]  # não duplica
    p = CT.criar(base, c["id"], "x", modelo="explicativo")
    assert CT.marca_do(base, p)["texto"] == "@shapereason"  # a marca já vem com o @ do canal
    assert CT.canal_do_modelo(base, "explicativo") != c["id"]  # o canal de nicho não vira o padrão do modelo
    with pytest.raises(CT.CurtoErro):
        CN.criar_canal_do_nicho(base, "nao_existe")


def test_ideias_sem_repetir_e_video_no_flow(base):
    c = CN.criar_canal_do_nicho(base, "shape_reason")
    ia = _ia(IDEIAS)
    novas = CN.gerar_ideias(base, c["id"], 10, ia, pedido="só coisas da rua")
    assert [i["titulo_en"] for i in novas] == ["Why manhole covers are round", "Why pencils are hexagonal"]  # a repetida saiu
    assert "só coisas da rua" in ia.vistos[0][1] and "Shape Reason" in ia.vistos[0][1]
    ia2 = _ia(IDEIAS)
    assert CN.gerar_ideias(base, c["id"], 10, ia2) == []  # as que já existem não voltam
    assert "Why manhole covers are round" in ia2.vistos[0][1]
    p = CN.video_da_ideia(base, c["id"], novas[0]["id"], "1:1", "v1")
    assert p["modelo"] == "explicativo" and p["canal_id"] == c["id"] and p["config"]["midia"] == "flow"
    assert p["config"]["proporcao"] == "1:1" and p["config"]["estilo_ia"] == "realista"
    assert "Um círculo" in p["noticia"]["texto"]
    assert CN.video_da_ideia(base, c["id"], novas[0]["id"])["id"] == p["id"]  # a ideia já virou vídeo: abre o mesmo
    assert CN.ideias(base, c["id"])[0]["pid"] == p["id"]
    q = CT.carregar(base, p["id"])
    sis, cont = CC.sistema(q), CC.conteudo_roteiro(base, q)
    assert "GENERATED with AI (Google Flow)" in sis and "ia_video" in sis and "VIDEO SOURCES" not in cont
    assert "CHANNEL NICHE" in cont and "SQUARE 1:1" in cont


def test_flow_realista_na_montagem(base):
    c = CN.criar_canal_do_nicho(base, "shape_reason")
    p = CT.criar(base, c["id"], "Manhole", texto="tampa de bueiro redonda", modelo="explicativo")
    pid = p["id"]
    CC.gerar_roteiro(base, pid, _ia(ROTEIRO_FLOW))
    r = CT.carregar(base, pid)["roteiro"]
    assert [b["cenas"][0]["layout"] for b in r["blocos"]] == ["ia", "ia_video"]
    CC.gerar_takes(base, pid, _tts, lambda t, m: t, VOZ, 1)
    CC.usar_take(base, pid, 1, _whisper(base, pid))
    d = CT.montar_dados_editor(base, pid, ["pexels", "flow"])
    segs = d["resposta"]["segments"]
    assert [(s["provider"], s["media_type"]) for s in segs] == [("flow", "image"), ("flow", "video")]
    assert all("Photorealistic" in s["query"] for s in segs)
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["config"]["estilo_ia"] = "livre"
        CT.salvar(base, q)
    assert not any("Photorealistic" in s["query"] for s in CT.montar_dados_editor(base, pid, ["pexels", "flow"])["resposta"]["segments"])
    # sem Flow: o vídeo gerado vira foto gerada (runpod) ou foto de banco
    segs2 = CT.montar_dados_editor(base, pid, ["pexels"])["resposta"]["segments"]
    assert all(s["provider"] == "pexels" for s in segs2)


def test_modo_midia(base, tmp_path):
    p = CT.criar(base, "", "x", texto="y", modelo="explicativo")
    assert CC.modo_midia(p) == "flow"  # sem vídeo nenhum: Flow
    from test_v84_253_comentario import _clipe
    with CT._TRAVA:
        q = CT.carregar(base, p["id"])
        CT.adicionar_midia(base, q, _clipe(str(tmp_path / "a.mp4"), 3), "video", "a")
        CT.salvar(base, q)
    q = CT.carregar(base, p["id"])
    assert CC.modo_midia(q) == "minhas" and CC.so_fontes(q)
    q["config"]["midia"] = "misto"
    assert CC.modo_midia(q) == "misto" and "Mix freely" in CC.sistema(q)
    q["config"]["midia"] = "flow"
    assert "GENERATED with AI" in CC.sistema(q)


# ------------------------------------------------------------------ rotas
@pytest.fixture
def cliente(base, monkeypatch):
    import app as A
    import ia_servico
    monkeypatch.setattr(A, "BASE_DIR", base)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_job_dir", lambda j: os.path.join(base, "jobs", j))
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda *a, **k: None)
    A.app.config["TESTING"] = True
    return A, A.app.test_client()


def test_rotas_nichos_ideias(cliente, base, monkeypatch):
    _A, cl = cliente
    html = cl.get("/curtos/modelo/explicativo").get_data(as_text=True)
    assert "Nichos de canais explicativos" in html and "Wild Trickcraft" in html and "gerar tudo no Flow" in html
    r = cl.post("/curtos/nicho/wild_trickcraft/criar")
    cid = r.headers["Location"].split("canal=")[1].split("#")[0]
    assert CT.carregar_canal(base, cid)["nicho"] == "wild_trickcraft"
    assert "💡 ideias (0 livres)" in cl.get("/curtos/modelo/explicativo").get_data(as_text=True)
    orig = CN.gerar_ideias
    monkeypatch.setattr(CN, "gerar_ideias", lambda b, c, n=10, chamar=None, pedido="": orig(b, c, n, _ia(IDEIAS), pedido))
    assert cl.post(f"/curtos/canal/{cid}/ideias", json={"n": 10}).get_json()["ok"]
    assert not _esperar("ideias:" + cid)["erro"]
    ids = cl.get(f"/curtos/canal/{cid}/ideias").get_json()["ideias"]
    assert len(ids) == 2
    d = cl.post(f"/curtos/canal/{cid}/ideia/{ids[0]['id']}/video", json={"proporcao": "9:16"}).get_json()
    assert d["ok"] and d["link"] == f"/curtos/{d['pid']}"
    pg = cl.get(d["link"]).get_data(as_text=True)
    assert "gerar tudo no Flow" in pg and "vídeo gerado (Flow)" in pg
    e = cl.get(f"/curtos/{d['pid']}/estado").get_json()
    assert e["midia_modo"] == "flow" and e["estilo_ia"] == "realista"
    assert cl.post(f"/curtos/{d['pid']}/proporcao", json={"proporcao": "9:16", "midia": "misto", "estilo_ia": "livre"}).get_json()["ok"]
    q = CT.carregar(base, d["pid"])
    assert q["config"]["midia"] == "misto" and q["config"]["estilo_ia"] == "livre"
    # novo pelo formulário, do zero no Flow, num canal de nicho
    r = cl.post("/curtos/novo", data={"modelo": "explicativo", "texto": "por que o flamingo fica num pé só", "midia": "flow",
                                      "estilo_ia": "realista", "canal_id": cid, "lingua_post": "en"}, content_type="multipart/form-data")
    pid = r.headers["Location"].rsplit("/", 1)[1]
    _esperar(pid) if __import__("curtos_rotas").TAREFAS.get(pid) else None
    p = CT.carregar(base, pid)
    assert p["canal_id"] == cid and p["config"]["midia"] == "flow" and not p["midias"]
