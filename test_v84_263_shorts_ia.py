"""v84_263: 🎌 Shorts de IA — universo da série com elenco fixo (B) + modelar um viral em storyboard → cenas A/B → Flow → edição."""
import json
import os
import shutil
import subprocess
import threading

import pytest

import shorts_ia as SI

UNIVERSO = {"nome": "Dragon Roommate", "premissa": "Uma dragoa milenar vira colega de quarto de um programador.",
            "tom": "caos doméstico, punchline no fim", "bordoes": ["Puny human!", "That's illegal in dragon law."],
            "elenco": [{"nome": "Ignis", "papel": "a caótica", "aparencia": "tall dragon woman, long crimson hair, gold eyes, small horns, maid outfit",
                        "personalidade": "orgulhosa e literal", "jeito_de_falar": "fala como rainha", "voz": "confident deep female voice"},
                       {"nome": "Ken", "papel": "o que sofre", "aparencia": "tired young man, messy black hair, glasses, gray hoodie",
                        "personalidade": "cansado", "jeito_de_falar": "suspira", "voz": "tired male voice"}],
            "cenarios": [{"nome": "Kitnet", "descricao": "tiny cluttered studio apartment with a kitchenette"}]}

CENAS = {"titulo": "Ignis vs the microwave", "logica": "gancho no susto, virada, punchline",
         "titulos": [{"post": "She thought it was a portal", "pt": "Ela achou que era um portal"}],
         "cenas": [
             {"quem": ["P1", "P2", "P1", "PX"], "cenario": "L1", "duracao": 5, "plano": "médio", "acao": "Ignis vê o micro-ondas",
              "inicio": "Ignis glaring at a microwave", "fim": "", "movimento": "slow push in",
              "falas": [{"quem": "P1", "texto": "What sorcery is this?", "emocao": "suspicious"}], "base": [1, 2]},
             {"quem": ["P2"], "cenario": "", "duracao": 12, "plano": "close", "acao": "Ken suspira", "inicio": "Ken facepalm",
              "fim": "Ken lying on the floor", "movimento": "shake", "falas": [], "base": []}]}


def _ia(*respostas):
    fila = list(respostas)

    def chamar(recurso, sistema, conteudo, **kw):
        chamar.vistos.append((sistema, conteudo))
        return json.loads(json.dumps(fila.pop(0) if len(fila) > 1 else fila[0]))
    chamar.vistos = []
    return chamar


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("SHORTS_IA_DIR", str(tmp_path / "shorts_ia"))
    return str(tmp_path)


class _LoteFalso:
    def __init__(self):
        self.trava = threading.RLock()
        self.fila, self.rodando, self.n = [], True, 0

    def adicionar(self, itens, proporcao="16:9", **kw):
        novos = []
        for it in itens:
            self.n += 1
            j = dict(it, id=f"j{self.n}", estado="pendente", proporcao=proporcao, resultados=[])
            self.fila.append(j)
            novos.append(j)
        return novos

    def iniciar(self):
        pass

    def terminar(self, galeria, tipo="imagem"):
        for j in self.fila:
            if j["estado"] == "pendente":
                nome = f"{j['id']}.{'mp4' if j['tipo'] == 'video' else 'png'}"
                if j["tipo"] == "video":
                    _video(os.path.join(galeria, nome), 3)
                else:
                    from PIL import Image
                    Image.new("RGB", (90, 160), (200, 50, 50)).save(os.path.join(galeria, nome))
                j.update(estado="ok", resultados=[{"tipo": j["tipo"], "arquivo": nome}])


def _video(caminho, dur, cor="red", som=True, size="180x320"):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:size={size}:rate=24:d={dur}"]
    if som:
        cmd += ["-f", "lavfi", "-i", f"sine=f=440:d={dur}", "-shortest"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", caminho], check=True)
    return caminho


@pytest.fixture
def lote(monkeypatch, tmp_path):
    lt = _LoteFalso()
    gal = tmp_path / "galeria"
    gal.mkdir()
    monkeypatch.setattr(SI, "_lote", lambda: lt)
    monkeypatch.setattr(SI, "_galeria", lambda arq: str(gal / os.path.basename(arq)))
    lt.galeria = str(gal)
    return lt


def test_planos_divide_longo_e_junta_curto():
    pl = SI.planos(10.0, [0.3, 2.0, 2.4, 9.0])
    assert pl[0][0] == 0.0 and pl[-1][1] == 10.0
    assert all(b - a <= 3.5 + 1e-6 for a, b in pl)  # o plano de 2,4→9,0 (6,6 s) virou dois
    assert not any(abs(a - 0.3) < 1e-6 for a, _b in pl)  # 0→0,3 era curto demais: juntou
    assert len(SI.planos(100.0, [float(x) for x in range(1, 100)], teto=30)) == 30


def test_universo_elenco_e_marca(base):
    s = SI.nova_serie(base, "", "dragoa colega de quarto")
    assert s["estilo"] == "anime_comedia" and s["proporcao"] == "9:16"
    ia = _ia(UNIVERSO)
    s = SI.gerar_universo(base, s["id"], "", chamar=ia)
    assert s["nome"] == "Dragon Roommate" and [p["id"] for p in s["elenco"]] == ["P1", "P2"] and s["cenarios"][0]["id"] == "L1"
    assert s["marca"]["texto"] == "@dragonroommate" and s["marca"]["ativa"]
    assert "ORIGINAIS" in ia.vistos[0][0]
    p = SI.salvar_personagem(base, s["id"], {"id": "P1", "aparencia": "outra"})
    assert p["aparencia"] == "outra" and p["nome"] == "Ignis"
    s = SI.atualizar_serie(base, s["id"], {"nome": "Kitnet Dragon", "bordoes": "a\n\nb"})
    assert s["bordoes"] == ["a", "b"] and s["marca"]["texto"] == "@kitnetdragon"  # o @ acompanha o nome
    s = SI.atualizar_serie(base, s["id"], {"marca": {"texto": "@meucanal"}})
    s = SI.atualizar_serie(base, s["id"], {"nome": "Outro"})
    assert s["marca"]["texto"] == "@meucanal"  # mudou na mão: não mexe mais


def test_prompts_sem_obra_e_com_referencias(base):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    pr = SI.prompt_ref_personagem(s, s["elenco"][0])
    for proibido in ("Dragon Maid", "Kobayashi", "Jashin", "Kyoto Animation"):
        assert proibido.lower() not in (pr + SI.ESTILOS["anime_comedia"]["prompt"]).lower()
    assert "Full body" in pr and "plain flat light gray background" in pr and "crimson hair" in pr
    cena = SI._nova_cena(CENAS["cenas"][0], {"P1", "P2"}, {"L1"})
    assert cena["quem"] == ["P1", "P2"]  # sem repetição, só ids do elenco (máx. 3)
    pi = SI.prompt_imagem_cena(s, cena, "inicio", [("Ignis", "a"), ("Ken", "b"), ("location", "c")])
    assert "panel 1 = Ignis" in pi and "panel 3 = location" in pi and "vertical 9:16" in pi and "No text" in pi
    pv = SI.prompt_video_cena(s, cena, False)
    assert 'Ignis (confident deep female voice), suspicious says in English: "What sorcery is this?"' in pv
    assert "No background music" in pv


def test_ideia_vira_episodio_e_cenas(base):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    ideias = SI.gerar_ideias(base, s["id"], 5, chamar=_ia({"ideias": [
        {"titulo": "Micro-ondas", "formato": "mal-entendido que vai escalando", "sinopse": "s", "gancho": "g", "quem": ["P1", "P9"]}]}))
    assert ideias[0]["quem"] == ["P1"]
    e = SI.novo_ep(base, s["id"], ideia=ideias[0]["id"])
    assert e["origem"]["tipo"] == "ideia" and e["titulo"] == "Micro-ondas"
    assert SI.carregar_serie(base, s["id"])["ideias"][0]["ep"] == e["id"]
    ia = _ia(CENAS)
    e = SI.modelar(base, s["id"], e["id"], "mais curto", chamar=ia)
    assert "EPISÓDIO A PARTIR DE UMA IDEIA" in ia.vistos[0][0] and "mais curto" in ia.vistos[0][1]
    assert len(e["cenas"]) == 2 and e["cenas"][1]["duracao"] == 8.0  # nunca passa de 8 s (um vídeo do Flow)
    assert e["titulos"][0]["post"] == "She thought it was a portal"
    c = json.loads(json.dumps(e["cenas"]))
    c[0]["falas"][0]["texto"] = "What dark magic is this?"
    c[0]["corte"] = {"ini": 0.5, "fim": ""}
    e = SI.salvar_cenas(base, s["id"], e["id"], list(reversed(c)))
    assert e["cenas"][1]["falas"][0]["texto"] == "What dark magic is this?" and e["cenas"][1]["corte"] == {"ini": 0.5, "fim": None}
    e = SI.voltar_cenas(base, s["id"], e["id"]) if e.get("cenas_anteriores") else e


def test_viral_storyboard(base):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    e = SI.novo_ep(base, s["id"], url="https://example.com/v")
    pasta = os.path.join(base, "v")
    os.makedirs(pasta)
    partes = [_video(os.path.join(pasta, f"p{k}.mp4"), 2, cor) for k, cor in enumerate(("red", "blue", "green"))]
    lista = os.path.join(pasta, "l.txt")
    open(lista, "w").write("".join(f"file '{p}'\n" for p in partes))
    viral = os.path.join(pasta, "viral.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", viral], check=True)

    def baixador(url, d):
        return shutil.copy(viral, os.path.join(d, "x.mp4"))

    def whisper(audio, **kw):
        return [{"start": 0.0, "end": 1.5, "text": "Watch this."}, {"start": 2.0, "end": 3.5, "text": "No way!"}]
    analise = {"resumo": "um cara assusta o outro", "por_que_viraliza": "susto + reação", "estrutura": {"gancho": "a", "desenvolvimento": "b", "virada": "c", "final": "d"},
               "personagens": [{"rotulo": "A", "descricao": "cara de vermelho"}, {"rotulo": "B", "descricao": "cara de azul"}],
               "momentos": [{"n": 1, "o_que": "A fala", "quem": ["A"], "falas": [{"quem": "A", "texto": "Watch this."}], "emocao": "confiante", "camera": "close"}]}
    ia = _ia(analise)
    e = SI.analisar_viral(base, s["id"], e["id"], whisper, ia, baixador)
    sb = e["origem"]["storyboard"]
    assert len(sb) == 3 and abs(sb[1]["de"] - 2.0) < 0.2  # um plano por cor
    assert sb[0]["falas"][0]["texto"] == "Watch this." and os.path.isfile(os.path.join(SI.pasta_ep(base, s["id"], e["id"]), "quadros", sb[0]["quadro"]))
    assert e["papeis"] == {"A": "P1", "B": "P2"}  # troca de elenco sugerida
    assert any(b.get("type") == "image" for b in ia.vistos[0][1])
    ia2 = _ia(CENAS)
    SI.modelar(base, s["id"], e["id"], chamar=ia2)
    assert "MODELAGEM de um viral" in ia2.vistos[0][0] and "#1 0.0" in ia2.vistos[0][1] and '"A": "P1"' in ia2.vistos[0][1]


def test_flow_refs_quadros_videos(base, lote):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    sid = s["id"]
    r = SI.pedir_refs(base, sid, ["P1", "P2", "L1"])
    assert r["enviadas"] == 3 and lote.fila[0]["tipo"] == "imagem"
    lote.terminar(lote.galeria)
    assert SI.sincronizar_serie(base, sid)
    s = SI.carregar_serie(base, sid)
    assert all(SI.caminho_ref(base, s, x) for x in s["elenco"] + s["cenarios"])
    e = SI.novo_ep(base, sid, "t")
    e = SI.modelar(base, sid, e["id"], chamar=_ia(CENAS))
    r = SI.pedir_imagens(base, sid, e["id"])
    assert r["enviadas"] == 2  # só o quadro A (o "como termina" vai no texto do vídeo)
    j = lote.fila[3]
    assert j.get("referencia_arquivo") and os.path.isfile(j["referencia_arquivo"]) and "panel 1 = Ignis" in j["prompt"]
    SI.salvar_opcoes(base, sid, e["id"], {"modo_video": "frames"})
    with pytest.raises(SI.ShortsIAErro):
        SI.pedir_videos(base, sid, e["id"])  # modo "animar o quadro A": ainda sem quadro A
    lote.terminar(lote.galeria)
    SI.sincronizar_ep(base, sid, e["id"])
    r = SI.pedir_videos(base, sid, e["id"])
    assert r["enviadas"] == 2
    v2 = lote.fila[-1]
    assert v2["tipo"] == "video" and v2.get("inicio_arquivo") and "The shot ends with: Ken lying on the floor" in v2["prompt"]
    lote.terminar(lote.galeria)
    SI.sincronizar_ep(base, sid, e["id"])
    e = SI.carregar_ep(base, sid, e["id"])
    assert all(c["video"]["estado"] == "pronto" for c in e["cenas"])
    with pytest.raises(SI.ShortsIAErro):
        SI.pedir_videos(base, sid, e["id"])  # já prontos: só com 🔁 refazer
    assert SI.pedir_videos(base, sid, e["id"], [0], refazer=True)["enviadas"] == 1


def test_exportar(base, monkeypatch):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    e = SI.novo_ep(base, s["id"], "t")
    e = SI.modelar(base, s["id"], e["id"], chamar=_ia(CENAS))
    pe = SI.pasta_ep(base, s["id"], e["id"])
    md = os.path.join(pe, "midia")
    os.makedirs(md)
    for k, cn in enumerate(e["cenas"]):
        _video(os.path.join(md, f"v{k}.mp4"), 4, som=(k == 0), size="270x480")
        cn["video"] = dict(SI._slot(), estado="pronto", arquivo=f"v{k}.mp4")
    SI.salvar_ep(base, e)
    SI.salvar_opcoes(base, s["id"], e["id"], {"qualidade": "1080p", "zoom": False, "legenda": True})
    final = SI.exportar(base, s["id"], e["id"])
    assert os.path.isfile(final)
    dur = SI._ffprobe_dur(final)
    # cena 1: 4 s de vídeo − 0,35 da ponta, ÷1,15; cena 2: idem; − a transição
    assert 5.0 < dur < 6.6
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", final],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "1080,1920"
    e = SI.carregar_ep(base, s["id"], e["id"])
    assert e["export"]["cenas"] == 2 and "She thought it was a portal" in SI.texto_titulos(e)


def test_janela_corta_ponta_bugada():
    assert SI.janela({"duracao": 5}, 8.0, 0.35) == (0.0, 5.6)
    assert SI.janela({"duracao": 8}, 8.0, 0.35) == (0.0, 7.65)
    assert SI.janela({"duracao": 5, "corte": {"ini": 1, "fim": 3}}, 8.0, 0.35) == (1.0, 3.0)


def test_paginas(base, monkeypatch):
    monkeypatch.setenv("NARRATION_SITE_NAO_CARREGAR_PROJETOS", "1")
    monkeypatch.setenv("CURTOS_VIGIA", "0")
    import app as A
    import shorts_ia_rotas as R
    monkeypatch.setitem(R.CB, "chamar", _ia(UNIVERSO))
    c = A.app.test_client()
    assert c.get("/shorts-ia").status_code == 200
    r = c.post("/shorts-ia/nova", data={"premissa": "x", "gerar": "0"})
    sid = r.headers["Location"].rsplit("/", 1)[-1]
    assert c.get(f"/shorts-ia/s/{sid}").status_code == 200
    assert c.post(f"/shorts-ia/s/{sid}/personagem", json={"nome": "Ignis", "aparencia": "red hair"}).get_json()["item"]["id"] == "P1"
    r = c.post(f"/shorts-ia/s/{sid}/ep/novo", json={"titulo": "tema livre", "modelar": "0"}).get_json()
    assert r["ok"]
    eid = r["ep"]
    assert c.get(f"/shorts-ia/s/{sid}/ep/{eid}").status_code == 200
    assert c.get(f"/shorts-ia/s/{sid}/ep/{eid}/estado").get_json()["ep"]["titulo"] == "tema livre"
    assert c.get(f"/shorts-ia/s/{sid}/ep/{eid}/cenas.zip").status_code == 200
    assert c.get(f"/shorts-ia/s/{sid}/arquivo/serie.json").status_code == 404
    assert c.get(f"/shorts-ia/s/{sid}/arquivo/../../x").status_code == 404
    assert c.get("/shorts-ia/s/zzz").status_code == 404


def test_fichas_e_voz_consistentes(base, lote):
    """A técnica de consistência: 📋 ficha (do Flow, a partir da referência) + 🎙 ficha de voz → ingredientes do vídeo."""
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    sid = s["id"]
    SI.salvar_personagem(base, sid, {"id": "P1", "genero": "female", "idade": "looks 22", "altura": "180 cm"})
    with pytest.raises(SI.ShortsIAErro):
        SI.pedir_fichas(base, sid, ["P1"])  # sem a referência ainda
    SI.pedir_refs(base, sid, ["P1", "P2"])
    lote.terminar(lote.galeria)
    SI.sincronizar_serie(base, sid)
    r = SI.pedir_fichas(base, sid, ["P1", "P2"])
    j = lote.fila[-2]
    assert r["enviadas"] == 2 and j["referencia_arquivo"] and "CHARACTER SHEET" in j["prompt"]
    assert "GENDER: FEMALE" in j["prompt"] and "keep the same gender" in j["prompt"] and j["proporcao"] == "16:9"
    lote.terminar(lote.galeria)
    SI.sincronizar_serie(base, sid)
    s = SI.carregar_serie(base, sid)
    assert SI.arquivo_serie(base, s, s["elenco"][0]["ficha"])
    perfil = {"idioma": "English (US)", "sotaque": "slight posh British", "genero": "female", "idade_vocal": "mid 20s",
              "timbre": "smooth, slightly smoky", "tom": "low-mid", "ritmo": "slow, regal pauses", "diccao": "crisp",
              "atitude": "condescending but warm", "maneirismos": "dramatic sigh before insults",
              "emocoes": [{"emocao": "angry", "como_soa": "a low growl under the words"}, {"emocao": "happy", "como_soa": "bright, almost singing"}],
              "frase_exemplo": "Puny human!", "resumo": "smooth smoky low-mid female voice, slight posh British accent, slow regal pace"}
    ia = _ia(perfil)
    vp = SI.fazer_ficha_de_voz(base, sid, "P1", chamar=ia)
    assert vp["resumo"].startswith("smooth smoky") and vp["por"] == "ia"
    assert any(b.get("type") == "image" for b in ia.vistos[0][1])  # a IA vê a personagem
    vp2 = SI.fazer_ficha_de_voz(base, sid, "P2", chamar=lambda *a, **k: None)  # sem IA: pela descrição da voz
    assert vp2["por"] == "regra" and "tired male voice" in vp2["resumo"]
    s = SI.carregar_serie(base, sid)
    from PIL import Image
    im = Image.open(SI.arquivo_serie(base, s, s["elenco"][0]["voz_ficha"]))
    assert im.size == (1920, 1080)
    e = SI.modelar(base, sid, SI.novo_ep(base, sid, "t")["id"], chamar=_ia(CENAS))
    assert e["edicao"]["modo_video"] == "elementos" and e["edicao"]["modelo_video"] == "Omni 1.1 Flash"
    r = SI.pedir_videos(base, sid, e["id"])  # sem quadro A: vai só com as fichas
    assert r["enviadas"] == 2
    v1, v2 = lote.fila[-2], lote.fila[-1]
    assert not v1.get("inicio_arquivo") and len(v1["referencias_arquivos"]) == 3  # 📋 Ignis, 📋 Ken, 🎙 Ignis
    assert "Reference image 1: the character sheet of Ignis" in v1["prompt"] and "Reference image 3: the voice sheet of Ignis" in v1["prompt"]
    assert "using the voice from Ignis's voice sheet" in v1["prompt"] and "Keep voice consistency and character consistency" in v1["prompt"]
    assert "smooth smoky" in v1["prompt"] and "no wind" in v1["prompt"]
    assert len(v2["referencias_arquivos"]) == 1  # só o Ken, sem fala


def test_flow_lote_aceita_ingredientes_e_nao_vira_foto(tmp_path, monkeypatch):
    import flow_lote
    monkeypatch.setattr(flow_lote, "pasta", lambda: str(tmp_path))
    lt = flow_lote.Lote() if hasattr(flow_lote, "Lote") else None
    a = tmp_path / "ficha.png"
    from PIL import Image
    Image.new("RGB", (10, 10)).save(a)
    j = lt.adicionar([{"prompt": "x", "tipo": "video", "referencias_arquivos": [str(a), str(tmp_path / "nao_existe.png")]}])[0]
    assert j["referencias_arquivos"] == [str(a)]
    chamado = []
    monkeypatch.setattr(flow_lote, "reescrever_para_foto", lambda *a, **k: chamado.append(1) or {"prompt": "f", "por": "regra"})
    lt._converter_videos()
    assert not chamado and j["tipo"] == "video"  # vídeo com fala (fichas) espera crédito de vídeo — nunca vira foto


# ------------------------------------------------------------------ v84_265: capítulos, personagens novos, momentos
def _img(caminho, cor=(200, 60, 60)):
    from PIL import Image
    Image.new("RGB", (120, 200), cor).save(caminho)
    return caminho


def test_universo_com_imagens_e_personagem_da_imagem(base, tmp_path):
    s = SI.nova_serie(base, "", "vila no interior", estilo="anime_cotidiano")
    assert s["estilo"] == "anime_cotidiano" and s["padroes"]["dur_plano"] == 5.0
    u = json.loads(json.dumps(UNIVERSO))
    u["elenco"][0]["imagem"] = 2
    u["elenco"][1]["imagem"] = 0
    ia = _ia(u)
    s = SI.gerar_universo(base, s["id"], "", chamar=ia, imagens=[_img(str(tmp_path / "a.png")), _img(str(tmp_path / "b.png"), (10, 200, 10))])
    blocos = ia.vistos[0][1]
    assert [b["text"] for b in blocos if b.get("type") == "text"][:2] == ["IMAGEM 1:", "IMAGEM 2:"]
    assert "CRIANÇAS" in ia.vistos[0][0] and "Nunca romance" in ia.vistos[0][0]
    assert SI.caminho_ref(base, s, s["elenco"][0]) and not SI.caminho_ref(base, s, s["elenco"][1])  # a imagem 2 virou a ref da Ignis
    ia2 = _ia({"nome": "Vovó Fumi", "papel": "a avó", "aparencia": "small old woman, gray bun, apron", "personalidade": "rabugenta e doce",
               "jeito_de_falar": "resmunga", "voz": "raspy old female voice", "genero": "female", "idade": "78", "altura": "148 cm", "imagem": 1})
    p = SI.personagem_da_imagem(base, s["id"], _img(str(tmp_path / "c.png")), "é a avó", chamar=ia2)
    assert p["nome"] == "Vovó Fumi" and p["ref"]["estado"] == "pronto" and "é a avó" in ia2.vistos[0][1][-1]["text"]


def test_capitulo_premissa_novos_personagens_e_memoria(base, lote):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    sid = s["id"]
    s = SI.atualizar_serie(base, sid, {"formato_serie": "continua", "padroes": {"dur_plano": 4, "modelo_video": "Veo 3.1 - Quality"}})
    SI.salvar_personagem(base, sid, {"id": "P1", "historico_txt": "tem medo de caranguejo"})
    premissa = {"titulo": "O ovo", "logline": "Ignis quer chocar um ovo", "gancho": "um ovo enorme", "desenvolvimento": "d", "virada": "é de pato",
                "final": "o pato segue o Ken", "quem": ["P1", "N1"], "continuidade": "depois do micro-ondas", "tom": "fofo",
                "novos_personagens": [{"id": "N1", "nome": "Gen", "papel": "o vizinho", "aparencia": "old farmer, straw hat", "personalidade": "calmo",
                                       "jeito_de_falar": "devagar", "voz": "slow deep voice", "genero": "male", "idade": "70", "altura": "160 cm", "fixo": True}]}
    ia = _ia(premissa)
    pr = SI.gerar_premissa_capitulo(base, sid, "um ovo", ["P1"], True, chamar=ia)
    sistema, texto = ia.vistos[0]
    assert "CONTÍNUA" in sistema and "tem medo de caranguejo" in texto and "PERSONAGENS QUE ELE QUER: Ignis" in texto
    assert pr["quem"] == ["P1", "N1"] and pr["novos_personagens"][0]["nome"] == "Gen"
    e = SI.criar_capitulo(base, sid, pr)
    s = SI.carregar_serie(base, sid)
    gen = next(p for p in s["elenco"] if p["nome"] == "Gen")
    assert gen["estreia"] == e["id"] and gen["preparar"] and e["origem"]["capitulo"]["quem"] == ["P1", gen["id"]]
    assert e["edicao"]["modelo_video"] == "Veo 3.1 - Quality" and e["dur_plano"] == 4.0
    assert any(j["prompt"].startswith(SI.ESTILOS["anime_comedia"]["prompt"][:30]) and "Gen" in j["prompt"] for j in lote.fila)  # 🧍 já pedida
    cenas = {"titulo": "O ovo", "titulos": [], "logica": "l", "resumo": "Ignis chocou um ovo de pato.",
             "memoria": [{"quem": "P1", "fato": "virou 'mãe' de um patinho"}, {"quem": "N2", "fato": "x"}],
             "novos_personagens": [{"id": "N2", "nome": "Patinho", "papel": "pato", "aparencia": "tiny yellow duckling", "personalidade": "grudento",
                                    "jeito_de_falar": "quack", "voz": "tiny quack", "genero": "", "idade": "1 dia", "altura": "", "fixo": True}],
             "cenas": [{"momento": "M1 · o ovo", "angulo": "wide establishing", "quem": ["P1", "N2"], "cenario": "", "duracao": 4, "plano": "aberto",
                        "acao": "a", "inicio": "i", "fim": "", "movimento": "m", "falas": [{"quem": "N2", "texto": "Quack!", "emocao": "happy"}], "base": []},
                       {"momento": "M1 · o ovo", "angulo": "close-up on Ignis", "quem": ["P1"], "cenario": "", "duracao": 4, "plano": "close",
                        "acao": "a", "inicio": "i2", "fim": "", "movimento": "m", "falas": [], "base": []}]}
    ia2 = _ia(cenas)
    e = SI.modelar(base, sid, e["id"], chamar=ia2)
    sis2, txt2 = ia2.vistos[0]
    assert "≈ 4 s" in sis2 and "8 a 14" in sis2 and "MOMENTOS E ÂNGULOS" in sis2 and "PREMISSA DESTE CAPÍTULO: O ovo" in txt2
    s = SI.carregar_serie(base, sid)
    pato = next(p for p in s["elenco"] if p["nome"] == "Patinho")
    assert e["cenas"][0]["quem"] == ["P1", pato["id"]] and e["cenas"][0]["falas"][0]["quem"] == pato["id"]
    assert e["cenas"][1]["angulo"] == "close-up on Ignis" and e["resumo"] == "Ignis chocou um ovo de pato."
    ign = SI.item(s, "P1")
    assert [h["fato"] for h in ign["historico"]] == ["tem medo de caranguejo", "virou 'mãe' de um patinho"]
    assert "virou 'mãe'" in SI.contexto_serie(s, base) and "Ignis chocou um ovo" in SI.contexto_serie(s, base)
    SI.modelar(base, sid, e["id"], chamar=_ia(cenas))  # re-modelar não duplica a memória
    assert len(SI.item(SI.carregar_serie(base, sid), "P1")["historico"]) == 2
    # 🎬 quadro A do 2º ângulo do mesmo momento leva o plano anterior como referência de continuidade
    pe = SI.pasta_ep(base, sid, e["id"])
    os.makedirs(os.path.join(pe, "midia"), exist_ok=True)
    _img(os.path.join(pe, "midia", "a0.png"))
    e = SI.carregar_ep(base, sid, e["id"])
    e["cenas"][0]["img_inicio"] = dict(SI._slot(), estado="pronto", arquivo="a0.png")
    SI.salvar_ep(base, e)
    SI.pedir_imagens(base, sid, e["id"], [1])
    assert "previous shot of this same moment" in lote.fila[-1]["prompt"] and "Camera: close-up on Ignis" in lote.fila[-1]["prompt"]
    SI.apagar_ep(base, sid, e["id"])
    assert [h["fato"] for h in SI.item(SI.carregar_serie(base, sid), "P1")["historico"]] == ["tem medo de caranguejo"]


def test_momento_em_corte_seco(base):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    e = SI.novo_ep(base, s["id"], "t")
    cenas = [dict(SI._nova_cena({"momento": m, "quem": ["P1"], "duracao": 3, "inicio": "x"}, {"P1"}, set())) for m in ("M1", "M1", "M2")]
    e = SI.salvar_cenas(base, s["id"], e["id"], cenas)
    pe = SI.pasta_ep(base, s["id"], e["id"])
    md = os.path.join(pe, "midia")
    os.makedirs(md)
    for k, cn in enumerate(e["cenas"]):
        _video(os.path.join(md, f"v{k}.mp4"), 3, size="180x320")
        cn["video"] = dict(SI._slot(), estado="pronto", arquivo=f"v{k}.mp4")
    SI.salvar_ep(base, e)
    SI.salvar_opcoes(base, s["id"], e["id"], {"zoom": False, "legenda": False, "velocidade": 1.0, "corte_fim": 0})
    final = SI.exportar(base, s["id"], e["id"])
    # 3 planos de 3,6 s (3 s + folga limitada pelo vídeo de 3 s → 3 s): M1+M1 em corte seco (6 s) + M2 (3 s) − 1 transição
    assert abs(SI._ffprobe_dur(final) - (9.0 - 0.16)) < 0.25


def test_inspiracoes_e_refazer(base, lote, tmp_path):
    s = SI.gerar_universo(base, SI.nova_serie(base)["id"], "x", chamar=_ia(UNIVERSO))
    sid = s["id"]
    SI.guardar_ref(base, sid, "P1", _img(str(tmp_path / "r.png")))
    ins = SI.guardar_inspiracoes(base, sid, "P1", [_img(str(tmp_path / "i1.png")), _img(str(tmp_path / "i2.png"), (0, 0, 200))])
    assert len(ins) == 2
    novo = {"nome": "Outro", "papel": "a dragoa", "aparencia": "tall woman, short silver bob, teal eyes, red apron", "personalidade": "p",
            "jeito_de_falar": "j", "voz": "calm alto", "genero": "female", "idade": "25", "altura": "175 cm", "imagem": 0}
    ia = _ia(novo)
    p = SI.refazer_personagem(base, sid, "P1", "inspiracao", chamar=ia)
    assert "ORIGINAL" in ia.vistos[0][0] and sum(1 for b in ia.vistos[0][1] if b.get("type") == "image") == 2
    assert p["nome"] == "Ignis" and "silver bob" in p["aparencia"] and p["preparar"]  # o nome fica
    assert p["ref"]["estado"] == "fila" and not p["ref"].get("arquivo")  # referência NOVA, gerada só pelo texto
    j = lote.fila[-1]
    assert "silver bob" in j["prompt"] and not j.get("referencia_arquivo")  # nada de copiar a imagem
    lote.terminar(lote.galeria)
    SI.sincronizar_serie(base, sid)  # 🧍 chegou → 📋 ficha pedida sozinha
    assert "CHARACTER SHEET" in lote.fila[-1]["prompt"]
    ia2 = _ia(dict(novo, aparencia="exactly as the reference"))
    p = SI.refazer_personagem(base, sid, "P1", "referencia", chamar=ia2)
    assert "FIEL às imagens" in ia2.vistos[0][0] and sum(1 for b in ia2.vistos[0][1] if b.get("type") == "image") == 3  # ref + 2
    assert p["aparencia"] == "exactly as the reference" and "CHARACTER SHEET" in lote.fila[-1]["prompt"]
    q = SI.personagem_da_imagem(base, sid, [_img(str(tmp_path / "a.png")), _img(str(tmp_path / "b.png"))], chamar=_ia(novo), modo="inspiracao")
    assert len(q["inspiracoes"]) == 2 and not (q["ref"] or {}).get("arquivo")
