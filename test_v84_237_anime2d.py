"""v84_237: 🎞 Animação 2D — premissa/história/áudio → plano (personagens, locais, itens, cenas) → momentos (fala,
narração, ação, destaque; quem está em cena, onde, pose, câmera) → poses no 🧍 Personagens (só as que o roteiro usa, com
2º quadro e boca) → locais/itens no Flow → vozes → editor com tudo posicionado."""
import io
import json
import os
import subprocess

import pytest
from PIL import Image, ImageDraw

import anime2d as A


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIME2D_DIR", str(tmp_path / "anime2d"))
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pod"))
    return str(tmp_path)


def _png(cor=(200, 50, 50), tam=(300, 450), fundo=None):
    im = Image.new("RGBA" if fundo is None else "RGB", tam, (0, 0, 0, 0) if fundo is None else fundo)
    ImageDraw.Draw(im).rectangle([40, 40, tam[0] - 40, tam[1] - 1], fill=cor)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


PLANO = {
    "titulo": "Kenta e o vaso", "sinopse": "Kenta quebra o vaso e tenta esconder.", "duracao_min": 2,
    "personagens": [
        {"nome": "Kenta", "descricao": "menino de 5 anos", "personalidade": "sapeca", "jeito_de_falar": "rápido",
         "aparencia_en": "5-year-old boy, spiky black hair, red t-shirt, blue shorts", "genero": "masculino", "idade": "crianca"},
        {"nome": "Mãe", "descricao": "a mãe", "personalidade": "brava", "jeito_de_falar": "KENTAAA",
         "aparencia_en": "woman, brown hair bun, green apron", "genero": "feminino", "idade": "adulto"}],
    "locais": [{"nome": "Sala", "descricao": "sala da casa", "prompt_en": "living room with a sofa and a window",
                "frente_en": "a small coffee table"}],
    "itens": [{"nome": "Vaso quebrado", "tipo": "objeto", "prompt_en": "a broken vase"},
              {"nome": "Mãe gigante", "tipo": "destaque", "prompt_en": "the mother as a giant scary silhouette in the door"}],
    "cenas": [{"titulo": "O acidente", "local": "Sala", "resumo": "Kenta quebra o vaso", "personagens": ["Kenta"], "inicio_audio": 0},
              {"titulo": "A mãe chega", "local": "Sala", "resumo": "a mãe chega", "personagens": ["Kenta", "Mãe"], "inicio_audio": 0}],
}
CENA1 = {"momentos": [
    {"tipo": "narracao", "quem": "Narrador", "texto": "Era uma tarde tranquila.", "pose": "neutro", "pose_en": "",
     "em_cena": [{"personagem": "Kenta", "posicao": "centro", "pose": "neutro", "olha": "direita"}], "camera": "zoom_in",
     "destaque": "", "objeto": "", "duracao": 0, "tempo": 0},
    {"tipo": "acao", "quem": "Kenta", "texto": "Kenta corre e esbarra no vaso", "pose": "correndo", "pose_en": "",
     "em_cena": [{"personagem": "Kenta", "posicao": "esquerda", "pose": "correndo", "olha": "direita"}], "camera": "tremida",
     "destaque": "", "objeto": "Vaso quebrado", "duracao": 2, "tempo": 0},
    {"tipo": "fala", "quem": "Kenta", "texto": "Fala 3: Ops... ninguém viu, né?", "pose": "outra", "pose_en": "hiding behind his own hands",
     "em_cena": [{"personagem": "Kenta", "posicao": "centro", "pose": "outra", "olha": "esquerda"}], "camera": "fixa",
     "destaque": "", "objeto": "", "duracao": 0, "tempo": 0}]}
CENA2 = {"momentos": [
    {"tipo": "destaque", "quem": "", "texto": "a mãe na porta", "pose": "neutro", "pose_en": "", "em_cena": [], "camera": "fixa",
     "destaque": "Mãe gigante", "objeto": "", "duracao": 2.5, "tempo": 0},
    {"tipo": "fala", "quem": "Mãe", "texto": "KENTAAA!", "pose": "bravo", "pose_en": "",
     "em_cena": [{"personagem": "Kenta", "posicao": "esquerda", "pose": "assustado", "olha": "direita"},
                 {"personagem": "Mãe", "posicao": "direita", "pose": "bravo", "olha": "esquerda"}],
     "camera": "zoom_in", "destaque": "", "objeto": "", "duracao": 0, "tempo": 0}]}


def _ia_falsa(monkeypatch):
    import ia_servico
    vistos = []

    def falsa(recurso, system, conteudo, **kw):
        assert recurso == "anime2d"
        vistos.append(system)
        if "PLANO" in system:
            return PLANO
        texto = conteudo if isinstance(conteudo, str) else conteudo[0]["text"]
        return CENA1 if "CENA 1 DE" in texto else CENA2
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    monkeypatch.setattr(A, "ia_ligada", lambda: True)
    return vistos


def _poses_prontas(p, c, base):
    import personagens_pod as pp
    proj = pp.carregar(c["pod"]["pid"], base)
    pp.criar_bocas(proj["id"], base, [x["arquivo"] for x in proj["dados"]["poses"] if not x["arquivo"].endswith("_b.png")])
    proj = pp.carregar(c["pod"]["pid"], base)
    for x in proj["dados"]["poses"]:
        local = x["arquivo"][:-4] + "_v1.png"
        cor = (0, 0, 200, 255) if x.get("tipo") == "boca" else (200, 0, 0, 255) if x["arquivo"].endswith("_b.png") else (30, 30, 30, 255)
        im = Image.new("RGBA", (1200, 1800), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([400, 300, 800, 1790], fill=cor)
        im.save(os.path.join(pp._pasta(proj["id"], base), "imagens", local))
        proj["imagens"][x["arquivo"]].update(estado="pronta", versoes=[{"local": local}], atual=0)
    proj["mestre"] = {"arquivo": proj["dados"]["poses"][0]["arquivo"], "local": proj["dados"]["poses"][0]["arquivo"][:-4] + "_v1.png"}
    pp.salvar(proj, base)


def test_premissa_plano_cenas_poses_e_editor(base, monkeypatch):
    import personagens_pod as pp
    _ia_falsa(monkeypatch)
    p = A.criar("Kenta", "Um menino quebra o vaso da mãe.", "cartoon", base, duracao_alvo=0)
    assert p["duracao_alvo"] == 0.0 and "DURAÇÃO é você que decide" in A.sys_plano(p)
    A.guardar_referencia(p, "kenta.png", _png((250, 0, 0)), "personagem", "Kenta", "", base)
    A.guardar_referencia(p, "estilo.png", _png((0, 250, 0)), "estilo", "", "", base)
    A.salvar(p, base)
    A.planejar(p["id"], base)
    p = A.carregar(p["id"], base)
    kenta = A.achar(p["personagens"], "Kenta")
    assert kenta["refs"] and len(p["cenas"]) == 2 and p["plano"]["duracao_min"] == 2 and A.duracao_planejada(p) == 2
    r = A.escrever_cenas(p["id"], base)
    assert r["feitas"] == 2
    p = A.carregar(p["id"], base)
    m1 = p["cenas"][0]["momentos"]
    assert [m["tipo"] for m in m1] == ["narracao", "acao", "fala"] and m1[0]["quem"] == "narrador"
    assert m1[2]["texto"] == "Ops... ninguém viu, né?"  # sem "Fala 3:"
    assert m1[1]["objeto"] and p["cenas"][1]["momentos"][0]["destaque"]
    # 🧍 só as poses que o roteiro usa (+ neutra), com 2º quadro nas de movimento e a pose livre
    usadas = A.poses_usadas(p, kenta["id"])
    assert set(usadas) == {"neutro", "correndo", "assustado", "x_hiding_behind_his_own_ha", "andando"}  # 🚶 muda de lugar
    js = A.poses_json(p, kenta)
    arqs = [x["arquivo"] for x in js["poses"]]
    assert "kenta_correndo_b.png" in arqs and "kenta_assustado_b.png" in arqs and "kenta_neutro_b.png" not in arqs
    assert "cartoon" in js["texto_fixo"]["estilo"].lower() and js["corpo_inteiro"]
    enviados = []
    monkeypatch.setattr(pp, "enviar", lambda pid, arqs, *a, **k: enviados.append(list(arqs)) or {"ok": True})
    A.criar_poses(p["id"], kenta["id"], base)
    assert enviados[-1] == ["kenta_neutro.png"]  # a ⭐ neutra primeiro
    mae = A.achar(p["personagens"], "Mãe")
    A.criar_poses(p["id"], mae["id"], base)
    p = A.carregar(p["id"], base)
    for c in p["personagens"]:
        _poses_prontas(p, c, base)
    assert set(A.poses_prontas(A.achar(p["personagens"], "Kenta"), base)) >= {"neutro", "correndo"}
    # 🏞 locais/itens: as suas imagens
    sala = p["locais"][0]
    for st, img, rec, tela in ((sala.setdefault("img", {}), _png((90, 140, 200), (1280, 720), (90, 140, 200)), False, True),
                               (sala.setdefault("frente", {}), _png((120, 80, 40), (800, 300), (0, 255, 0)), True, False)):
        A.guardar_img(p, st, Image.open(io.BytesIO(img)), rec, base, origem="sua", tela_cheia=tela)
    for it in p["itens"]:
        A.guardar_img(p, it.setdefault("img", {}), Image.open(io.BytesIO(_png((200, 200, 0), (640, 360), (200, 200, 0)))),
                      it["tipo"] != "destaque", base, tela_cheia=it["tipo"] == "destaque")
    A.salvar(p, base)
    # ⏱ sem vozes: tempo de leitura
    tl = A.linha_do_tempo(p, base)
    assert tl["cenas"][1]["ini"] == tl["cenas"][0]["fim"] and tl["duracao"] > 6
    plano = A.plano_de_camadas(p, base)
    assert any(f["b"] for f in plano["figs"] if f["pose_nome"] == "correndo")
    fala_mae = next(f for f in plano["figs"] if f["nome"] == "Mãe")
    assert fala_mae["boca"] and fala_mae["espelhar"] and fala_mae["cx"] > plano["W"] * 0.8
    jd = os.path.join(base, "job")
    os.makedirs(jd)
    m = A.montar_editor(p, base, jd)
    assert len(m["segmentos"]) == 5 and m["segmentos"][0]["zoom_direction"] == "in"  # 🎥 um plano por momento
    ovs = m["overlays"]
    camadas = {o["camada"] for o in ovs}
    assert {"personagem", "objeto", "frente", "destaque", "legenda"} <= camadas
    corre = [o for o in ovs if o.get("expressao") == "correndo"]
    assert len(corre) >= 2 and len({o["source"]["value"] for o in corre}) == 2  # o 2º quadro só na transição, depois a pose parada
    anda = [o for o in ovs if o.get("expressao") == "andando"]
    assert len(anda) >= 2 and all(any("de" in mv for mv in o["mov"]) for o in anda)  # 🚶 andando até o lugar novo
    assert any(o.get("boca_janelas") for o in ovs if o.get("cid") == mae["id"])
    assert os.path.isfile(m["audio"])
    assert A.previa(p, base, os.path.join(base, "prev.jpg"), 1.0)


def test_vozes_por_personagem_viram_a_linha_do_tempo(base, monkeypatch):
    import multivoz
    _ia_falsa(monkeypatch)
    p = A.criar("Vozes", "x", "anime", base)
    A.aplicar_plano(p, PLANO)
    A.aplicar_cena(p, 0, CENA1)
    A.aplicar_cena(p, 1, CENA2)
    A.achar(p["personagens"], "Kenta")["voz"] = "kenta"
    p["narrador"] = {"ativo": True, "voz": "narra"}
    A.salvar(p, base)
    monkeypatch.setattr(multivoz, "por_slug", lambda: {"kenta": {"slug": "kenta", "nome": "Kenta", "motor": "piper", "config": {}},
                                                       "narra": {"slug": "narra", "nome": "Narrador", "motor": "piper", "config": {}}})
    monkeypatch.setattr(multivoz, "kwargs_da_voz", lambda v: ("piper", {"voz": v["slug"]}))
    chamadas = []

    def tts(motor, texto, saida, **kw):
        chamadas.append((kw["voz"], texto))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=1.5", saida], check=True)
    r = A.gerar_vozes(p["id"], base, tts, lambda t, m: t)
    assert r["feitas"] == 2 and r["sem_voz"] == 1  # a Mãe não tem voz: fica muda com a legenda
    assert ("narra", "Era uma tarde tranquila.") in chamadas
    p = A.carregar(p["id"], base)
    tl = A.linha_do_tempo(p, base)
    m0 = tl["cenas"][0]["momentos"][0]
    assert m0["audio_ok"] and abs((m0["fim"] - m0["ini"]) - 1.5) < 0.1
    assert A.gerar_vozes(p["id"], base, tts, lambda t, m: t)["feitas"] == 0  # já tem: não refaz
    wav = A.montar_audio(p, tl, os.path.join(base, "ep.wav"), base)
    assert abs(A.duracao_wav(wav) - tl["duracao"]) < 0.3


def test_audio_pronto_a_ia_monta_em_volta(base, monkeypatch):
    """🎧 Um áudio (diálogo/narração): o Whisper transcreve, a IA acha os personagens e as cenas pelos tempos."""
    import whisper_transcribe
    vistos = _ia_falsa(monkeypatch)
    wav = os.path.join(base, "dialogo.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=12", wav], check=True)
    p = A.criar("Do áudio", "Kenta é um menino; a mãe é brava.", "anime", base)
    with open(wav, "rb") as f:
        A.guardar_audio(p, "dialogo.wav", f.read(), base)
    A.salvar(p, base)
    monkeypatch.setattr(whisper_transcribe, "transcribe_audio", lambda cam: [
        {"start": 0.5, "end": 2.5, "text": "Era uma tarde tranquila."}, {"start": 3.0, "end": 5.0, "text": "Ops, ninguém viu."},
        {"start": 7.0, "end": 9.0, "text": "KENTAAA!"}])
    assert A.transcrever_audio(p["id"], base) == 3
    p = A.carregar(p["id"], base)
    assert "ÁUDIO ENVIADO" in A.prompt_plano(p) and "KENTAAA" in A.prompt_plano(p)
    plano = json.loads(json.dumps(PLANO))
    plano["cenas"][1]["inicio_audio"] = 6.5
    A.aplicar_plano(p, plano)
    assert [s["audio_ini"] for s in p["cenas"]] == [0.0, 6.5]
    assert "MODO ÁUDIO" in A.sys_cena(p) and "6.5" not in A.prompt_cena(p, 0).split("TRANSCRIÇÃO")[-1].split("KENTA")[0][-5:]
    c1 = json.loads(json.dumps(CENA1))
    for m, t in zip(c1["momentos"], (0.5, 2.6, 3.0)):
        m["tempo"] = t
    c2 = json.loads(json.dumps(CENA2))
    for m, t in zip(c2["momentos"], (6.5, 7.0)):
        m["tempo"] = t
    A.aplicar_cena(p, 0, c1)
    A.aplicar_cena(p, 1, c2)
    A.salvar(p, base)
    tl = A.linha_do_tempo(p, base)
    assert tl["duracao"] >= 11.9 and tl["cenas"][1]["ini"] == 6.5
    m_ken = tl["cenas"][0]["momentos"][2]
    assert m_ken["ini"] == 3.0 and m_ken["fala_fim"] == 5.0  # a boca só mexe enquanto o trecho dura
    with pytest.raises(A.AnimeErro):
        A.gerar_vozes(p["id"], base, lambda *a, **k: None, lambda t, m: t)  # não precisa de vozes
    out = A.montar_audio(p, tl, os.path.join(base, "ep.wav"), base)
    assert abs(A.duracao_wav(out) - 12) < 0.3


def test_reaproveita_personagem_e_imagens_de_outro_episodio(base, monkeypatch):
    import personagens_pod as pp
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: {"ok": True})
    a = A.criar("Ep 1", "x", "cartoon", base)
    A.aplicar_plano(a, PLANO)
    A.aplicar_cena(a, 0, CENA1)
    A.salvar(a, base)
    A.criar_poses(a["id"], A.achar(a["personagens"], "Kenta")["id"], base)
    a = A.carregar(a["id"], base)
    A.guardar_img(a, a["locais"][0].setdefault("img", {}), Image.open(io.BytesIO(_png((1, 2, 3), (1280, 720), (1, 2, 3)))), False, base, tela_cheia=True)
    A.salvar(a, base)
    b = A.criar("Ep 2", "y", "cartoon", base)
    A.aplicar_plano(b, PLANO)
    A.aplicar_cena(b, 0, CENA1)
    A.salvar(b, base)
    A.criar_poses(b["id"], A.achar(b["personagens"], "Kenta")["id"], base)
    b = A.carregar(b["id"], base)
    kb = A.achar(b["personagens"], "Kenta")
    assert kb["pod"]["pid"] == A.achar(a["personagens"], "Kenta")["pod"]["pid"] and kb["pod"]["reaproveitado"] == "Ep 1"
    assert A.reaproveitar_imagens(b["id"], base) == 1
    assert A.arquivo_img(A.carregar(b["id"], base), A.carregar(b["id"], base)["locais"][0]["img"], base)
    c = A.criar("Ep 3", "z", "oleo", base)  # outro estilo: não reaproveita
    A.aplicar_plano(c, PLANO)
    assert not A.reaproveitar_personagem(c, A.achar(c["personagens"], "Kenta"), base)


def test_rotas_pagina_e_editor(base, monkeypatch):
    import app as AP
    _ia_falsa(monkeypatch)
    cli = AP.app.test_client()
    r = cli.post("/anime2d/novo", data={"titulo": "Teste rota", "premissa": "um gato fala", "estilo": "paint", "proporcao": "9:16",
                                        "duracao": "3", "referencias": (io.BytesIO(_png()), "Gato.png")},
                 content_type="multipart/form-data")
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    html = cli.get(f"/anime2d/{pid}").get_data(as_text=True)
    assert "Animação 2D" in html and "Exemplo de instruções" in html and "Kenta" in html  # o exemplo aparece
    assert "🎞 Animação 2D" in cli.get("/modelos-video").get_data(as_text=True)
    assert cli.post(f"/anime2d/{pid}/colar/plano", json={"texto": "```json\n" + json.dumps(PLANO) + "\n```"}).get_json()["ok"]
    assert cli.post(f"/anime2d/{pid}/colar/cena", json={"texto": json.dumps(CENA1), "k": 0}).get_json()["ok"]
    e = cli.get(f"/anime2d/{pid}/estado").get_json()
    assert e["proporcao"] == "9:16" and len(e["cenas"][0]["momentos"]) == 3 and e["referencias"][0]["nome"] == "Gato"
    assert "Responda SÓ com um JSON" in cli.get(f"/anime2d/{pid}/prompt/cena?k=1").get_json()["prompt"]
    # editar a cena na página mantém os ids
    s = e["cenas"][0]
    mom = [dict(m, em_cena=[dict(x, personagem=x["cid"]) for x in m["em_cena"]]) for m in s["momentos"]]
    mom[0]["texto"] = "Era uma tarde MUITO tranquila."
    assert cli.post(f"/anime2d/{pid}/cena/0", json={"titulo": s["titulo"], "momentos": mom}).get_json()["ok"]
    e = cli.get(f"/anime2d/{pid}/estado").get_json()
    assert e["cenas"][0]["momentos"][0]["texto"] == "Era uma tarde MUITO tranquila." and e["cenas"][0]["momentos"][0]["id"] == s["momentos"][0]["id"]
    lo = e["locais"][0]["id"]
    assert cli.post(f"/anime2d/{pid}/imagem/{lo}:fundo", data={"arquivo": (io.BytesIO(_png((9, 9, 9), (720, 1280), (9, 9, 9))), "f.png")},
                    content_type="multipart/form-data").get_json()["ok"]
    assert cli.get(f"/anime2d/{pid}/previa.jpg?t=1").status_code == 200
    d = cli.post(f"/anime2d/{pid}/editor", json={}).get_json()
    assert d["ok"]
    job = AP._JOBS[d["job_id"]]
    assert job["orientation"] == "9:16" and len(job["pending_segments"]) == 3  # 🎥 um plano por momento
    assert any("sem poses" in a or "ainda sem poses" in a for a in d["avisos"])


def test_parallax_camadas_em_velocidades_diferentes():
    """🌄 Câmera em pan: a frente anda mais que os personagens (o fundo é o mais lento, no editor); zoom abre pros
    lados; tremida treme; desligado não mexe. A conta do render (_mov_expr) e a da prévia batem."""
    import video_assembler as va
    plano = {"paralaxe": True, "tremidas": [{"ini": 1.0, "fim": 2.0}],
             "fundos": [{"ini": 0.0, "fim": 4.0, "camera": "pan_esq"}, {"ini": 4.0, "fim": 8.0, "camera": "zoom_in"},
                        {"ini": 8.0, "fim": 9.0, "camera": "fixa"}]}
    fr = A.movimento(plano, "frente", 0, 4)
    pe = A.movimento(plano, "personagem", 0, 4, 0.5)
    assert fr[0]["dx"] > pe[0]["dx"] > 0.15  # mais perto = mais rápido; o fundo anda ~0,15
    assert any(m.get("tremor") for m in pe)
    esq, dir_ = A.movimento(plano, "personagem", 4, 8, 0.2)[0], A.movimento(plano, "personagem", 4, 8, 0.8)[0]
    assert esq["dx"] < 0 < dir_["dx"] and esq["dy"] > 0  # zoom in: abrem pros lados e descem
    assert A.movimento(plano, "personagem", 8, 9) == [] and A.movimento(plano, "legenda", 0, 4) == []
    assert A.movimento(dict(plano, paralaxe=False), "frente", 0, 4) == []
    # no meio da cena a camada está onde você pôs; nas pontas, ±metade
    assert A.deslocamento(fr[:1], 2.0, 1000, 500) == (0.0, 0.0)
    assert abs(A.deslocamento(fr[:1], 4.0, 1000, 500)[0] - 160) < 1e-6
    ex = va._mov_expr(fr, "x")
    assert ex.startswith("+between(t,0.000,4.000)*main_w*0.32000") and va._mov_expr([], "x") == ""
    assert "0" in va._mov_expr([{"a": 1, "b": 2, "tremor": 0.01}], "y")


def test_zip_com_tudo_importar_exportar(base, monkeypatch):
    """📦 O zip de exemplo entra inteiro (história, config, personagens com refs/ficha/poses prontas, locais com fundo
    e frente prontos, itens, estilo, cenas) num projeto novo; exportar e importar de novo dá o mesmo; num projeto que
    já existe junta (não duplica)."""
    import zipfile
    import anime2d_zip as AZ
    import personagens_pod as pp
    enviados = []
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: enviados.append(a) or {"ok": True})
    ex = AZ.exemplo()
    assert "exemplo_animacao_2d/LEIA-ME.txt" in zipfile.ZipFile(io.BytesIO(ex)).namelist()
    p = A.criar("", "", "anime", base)
    rel = AZ.importar(p["id"], ex, base, novo=True)
    p = A.carregar(p["id"], base)
    assert p["titulo"] == "O vaso quebrado" and p["estilo"] == "cartoon" and "Kenta, 5 anos" in p["premissa"]
    assert {c["nome"] for c in p["personagens"]} == {"Kenta", "Mãe"}
    k = next(c for c in p["personagens"] if c["nome"] == "Kenta")
    assert k["personalidade"].startswith("sapeca") and k["aparencia_en"].startswith("5 year old") and k["genero"] == "masculino"
    assert len(k["refs"]) == 1 and len(next(c for c in p["personagens"] if c["nome"] == "Mãe")["refs"]) == 1
    assert rel["poses"] == 5 and k["poses_zip"] == ["escondido atras do sofa"] and k["pod"]["fase"] == "zip"
    prontas = A.poses_prontas(k, base)
    assert prontas["neutro"]["boca"] and prontas["correndo"]["b"] and "x_escondido_atras_do_sofa" in prontas
    assert Image.open(prontas["neutro"]["pose"]).size == (1200, 1800)
    assert not enviados  # o que veio pronto não vai pro Flow
    sala = next(x for x in p["locais"] if x["nome"] == "Sala")
    assert A.arquivo_img(p, sala["img"], base) and A.arquivo_img(p, sala["frente"], base) and sala["frente_en"]
    quintal = next(x for x in p["locais"] if x["nome"] == "Quintal")
    assert quintal["refs"] and not A.arquivo_img(p, quintal.get("img") or {}, base)
    vaso = next(i for i in p["itens"] if i["nome"] == "Vaso quebrado")
    assert vaso["tipo"] == "objeto" and A.arquivo_img(p, vaso["img"], base)
    assert next(i for i in p["itens"] if i["nome"] == "Mãe gigante")["tipo"] == "destaque"
    assert len(A.refs_estilo(p, base)) == 1
    assert rel["cenas"] == 1 and rel["momentos"] == 3
    ms = p["cenas"][0]["momentos"]
    assert ms[1]["objeto"] == vaso["id"] and ms[1]["camera"] == "tremida"
    e = ms[2]["em_cena"][0]
    assert e["pose"] == "outra" and A.nome_pose(e["pose"], e["pose_en"]) == "x_escondido_atras_do_sofa"
    # a pose pronta é usada na montagem
    plano = A.plano_de_camadas(p, base)
    assert any(f["pose_nome"] == "x_escondido_atras_do_sofa" and f["pose"] == prontas["x_escondido_atras_do_sofa"]["pose"]
               for f in plano["figs"])
    assert "escondido atras do sofa" in A.prompt_cena(p, 0)
    # exportar → importar num projeto novo: o mesmo
    out = AZ.exportar(p["id"], base)
    q = A.criar("", "", "anime", base)
    rel2 = AZ.importar(q["id"], out, base, novo=True)
    q = A.carregar(q["id"], base)
    assert q["titulo"] == p["titulo"] and rel2["poses"] == 5 and rel2["momentos"] == 3 and rel2["imagens"] == rel["imagens"]
    assert A.poses_prontas(next(c for c in q["personagens"] if c["nome"] == "Kenta"), base).keys() == prontas.keys()
    # de novo no mesmo projeto: junta, não duplica
    AZ.importar(p["id"], ex, base)
    p = A.carregar(p["id"], base)
    assert len(p["personagens"]) == 2 and len(p["locais"]) == 2 and len(p["itens"]) == 2
    # zip quebrado / vazio
    with pytest.raises(A.AnimeErro):
        AZ.importar(p["id"], b"nao e zip", base)


def test_zip_atalhos_e_pose_verde(base):
    """Arquivos soltos (personagens/Bia.png, locais/Praia.png), pasta de fora, referencias/ soltas, pose com fundo
    verde recortada, historia.txt e áudio."""
    import zipfile
    import anime2d_zip as AZ
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("meu/historia.txt", "Bia vai à praia.")
        z.writestr("meu/personagens/Bia.png", _png((10, 200, 10)))
        z.writestr("meu/personagens/Bia.json", json.dumps({"personalidade": "alegre", "voz": "nao-existe"}))
        verde = Image.new("RGB", (300, 450), (0, 255, 0))
        ImageDraw.Draw(verde).rectangle([100, 50, 200, 449], fill=(200, 30, 30))
        bb = io.BytesIO(); verde.save(bb, "PNG")
        z.writestr("meu/personagens/Bia/poses/feliz.png", bb.getvalue())
        z.writestr("meu/locais/Praia.png", _png((0, 0, 200), (640, 360), (0, 0, 200)))
        z.writestr("meu/referencias/Praia.jpg", _png((0, 0, 100), (100, 100), (0, 0, 100)))
        z.writestr("meu/__MACOSX/._lixo", b"x")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=1", os.path.join(base, "a.mp3")], check=True)
        z.write(os.path.join(base, "a.mp3"), "meu/audio.mp3")
    p = A.criar("Praia", "", "anime", base)
    rel = AZ.importar(p["id"], b.getvalue(), base)
    p = A.carregar(p["id"], base)
    assert p["titulo"] == "Praia" and p["premissa"] == "Bia vai à praia." and rel["audio"] and A.audio_ok(p, base)
    bia = p["personagens"][0]
    assert bia["nome"] == "Bia" and bia["personalidade"] == "alegre" and bia["refs"] and not bia.get("voz")
    assert any("nao-existe" in a for a in rel["avisos"])
    praia = p["locais"][0]
    assert A.arquivo_img(p, praia["img"], base) and praia["refs"]
    feliz = A.poses_prontas(bia, base)["feliz"]["pose"]
    im = Image.open(feliz)
    assert im.getpixel((5, 5))[3] == 0 and im.getpixel((600, 1700))[3] == 255  # o verde virou transparente
    assert AZ.nome_pose_arquivo("correndo_b") == ("correndo", "b", "")
    assert AZ.nome_pose_arquivo("Neutro boca") == ("neutro", "boca", "")


def test_zip_rotas(base):
    import app as AP
    import anime2d_zip as AZ
    c = AP.app.test_client()
    assert c.get("/anime2d/zip-exemplo.zip").status_code == 200
    assert "COMO MONTAR" in c.get("/anime2d/zip-guia.txt").get_data(as_text=True)
    r = c.post("/anime2d/novo", data={"titulo": "", "premissa": "", "estilo": "anime", "zip": (io.BytesIO(AZ.exemplo()), "ex.zip")},
               content_type="multipart/form-data")
    assert r.status_code == 302
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    p = A.carregar(pid, AP.BASE_DIR)
    try:
        assert p["titulo"] == "O vaso quebrado" and len(p["personagens"]) == 2
        html = c.get(f"/anime2d/{pid}").get_data(as_text=True)
        assert "📦 Zip com tudo" in html and "COMO MONTAR O ZIP" in html and "personagem.json" in html
        r = c.post(f"/anime2d/{pid}/zip", data={"arquivo": (io.BytesIO(AZ.exemplo()), "ex.zip")}, content_type="multipart/form-data")
        assert r.get_json()["ok"] and "personagem" in r.get_json()["resumo"]
        g = c.get(f"/anime2d/{pid}/zip")
        assert g.status_code == 200 and g.data[:2] == b"PK"
    finally:
        A.excluir(pid, AP.BASE_DIR)


# ------------------------------------------------------------------ 📖 mangá → anime
ADAPTACAO = {
    "titulo": "A carteira", "sinopse": "A irmã mais nova pega a carteira da mais velha e compra doces.", "tom": "comédia",
    "estilo_sugerido": "manga_tinta", "notas": ["o soco vira destaque em tela cheia"],
    "personagens": [
        {"nome": "Yomi", "descricao": "irmã mais velha", "personalidade": "explosiva", "jeito_de_falar": "grita",
         "aparencia_manga_en": "girl with black bob hair, fox ears, fur coat", "design_en": "girl, black bob hair, red eyes, black fox ears, dark coat with white fur",
         "mudancas_anime": "ganha olhos vermelhos", "genero": "feminino", "idade": "jovem",
         "recorte": {"pagina": 1, "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.9}},
        {"nome": "Kon", "descricao": "irmã mais nova", "personalidade": "tranquila e esperta", "jeito_de_falar": "calma",
         "aparencia_manga_en": "girl with long light hair, fox ears", "design_en": "girl, long platinum hair, golden fox ears, purple dress",
         "mudancas_anime": "cabelo platinado", "genero": "feminino", "idade": "crianca",
         "recorte": {"pagina": 2, "x0": 0.5, "y0": 0.0, "x1": 1.0, "y1": 0.6}}],
    "locais": [{"nome": "Casa", "descricao": "casa velha na floresta", "prompt_en": "old house interior full of books",
                "frente_en": "", "recorte": {"pagina": 2, "x0": 0, "y0": 0.5, "x1": 1, "y1": 1}}],
    "itens": [{"nome": "Carteira", "tipo": "objeto", "prompt_en": "a round coin purse"},
              {"nome": "O soco", "tipo": "destaque", "prompt_en": "a cartoon punch impact"}],
    "cenas": [{"titulo": "A carteira sumiu", "local": "Casa", "resumo": "Yomi procura a carteira", "personagens": ["Yomi", "Kon"],
               "paginas": [1, 2], "nota_adaptacao": "zoom no rosto da Yomi"}],
}


def _paginas(n=2):
    out = []
    for k in range(n):
        im = Image.new("RGB", (964, 1400), (255, 255, 255))
        ImageDraw.Draw(im).rectangle([100 + 40 * k, 150, 450, 1200], fill=(20, 20, 20))
        b = io.BytesIO(); im.save(b, "JPEG")
        out.append((f"{k + 1}.jpg", b.getvalue()))
    return out


class _LoteFalso:
    def __init__(self):
        import threading
        self.trava, self.fila, self.rodando, self.pedidos = threading.Lock(), [], True, []

    def adicionar(self, itens, proporcao="16:9", quantidade="x1", **kw):
        feitos = []
        for it in itens:
            j = {"id": f"j{len(self.fila)}", "estado": "fila", "resultados": [], "prompt": it["prompt"], "proporcao": proporcao,
                 "ref": it.get("referencia_arquivo")}
            self.fila.append(j)
            feitos.append(j)
        return feitos

    def iniciar(self):
        pass


def test_manga_adaptacao_design_aprovado_e_cenas(base, monkeypatch, tmp_path):
    """📖 Páginas → a IA lê → personagens (mangá + versão anime) com o recorte de referência, locais, itens, cenas com as
    páginas → 🎨 design no Flow (entra sozinho) → só depois de ✔ aprovar as poses saem (com o design de referência) →
    as cenas são escritas lendo as páginas."""
    import ia_servico
    import flow_lote
    import flow_estudio as FE
    import personagens_pod as pp
    import anime2d_manga as AM
    vistos = []

    def falsa(recurso, system, conteudo, **kw):
        imgs = [b for b in conteudo if isinstance(b, dict) and b.get("type") == "image"] if isinstance(conteudo, list) else []
        vistos.append((system[:60], len(imgs), conteudo[0]["text"] if isinstance(conteudo, list) else conteudo))
        if "ADAPTAÇÃO DE MANGÁ" in system:
            return ADAPTACAO
        return {"momentos": [{"tipo": "fala", "quem": "Yomi", "texto": "Você sabe onde está minha carteira?", "pose": "bravo", "pose_en": "",
                              "em_cena": [{"personagem": "Yomi", "posicao": "esquerda", "pose": "bravo", "olha": "direita"}],
                              "camera": "zoom_in", "destaque": "", "objeto": "", "duracao": 0, "tempo": 0, "som": "porta batendo"}]}
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    monkeypatch.setattr(A, "ia_ligada", lambda: True)
    lote = _LoteFalso()
    monkeypatch.setattr(flow_lote, "lote", lambda: lote)
    monkeypatch.setattr(pp, "enviar", lambda *a, **k: {"ok": True})
    p = A.criar("", "", "manga_tinta", base)
    assert AM.guardar_paginas(p, list(reversed(_paginas(2))), base) == 2  # a ordem vem do nome
    A.salvar(p, base)
    assert A.paginas_manga(p)[0].startswith("pg_001")
    rel = AM.ler_manga(p["id"], base)
    assert vistos[0][1] == 2 and rel == {"personagens": 2, "locais": 1, "itens": 2, "cenas": 1, "recortes": 3}
    p = A.carregar(p["id"], base)
    assert p["titulo"] == "A carteira" and p["premissa"].startswith("A irmã")
    yomi = next(c for c in p["personagens"] if c["nome"] == "Yomi")
    assert yomi["aparencia_en"] == yomi["design_en"] and yomi["aparencia_manga_en"].startswith("girl with black")
    assert yomi["refs"] and A.precisa_aprovar(yomi)  # 🔒 com a versão anime, as poses esperam o design aprovado
    assert p["cenas"][0]["paginas"] == [1, 2] and p["locais"][0]["refs"]
    # 🎨 design no Flow → entra sozinho
    AM.gerar_designs(p["id"], None, "", base)
    assert len(lote.fila) == 2 and lote.fila[0]["proporcao"] == "3:4" and "anime adaptation of a manga" in lote.fila[0]["prompt"]
    assert lote.fila[0]["ref"] and os.path.isfile(lote.fila[0]["ref"])
    gal = tmp_path / "galeria"
    gal.mkdir()
    Image.new("RGB", (600, 800), (200, 100, 100)).save(gal / "d.png")
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    for j in lote.fila:
        j.update(estado="ok", resultados=[{"tipo": "imagem", "arquivo": "d.png"}])
    A._acompanhar_imagens(p["id"], base)
    p = A.carregar(p["id"], base)
    yomi = next(c for c in p["personagens"] if c["nome"] == "Yomi")
    assert yomi["design"]["estado"] == "pronta" and A.precisa_aprovar(yomi)
    with pytest.raises(A.AnimeErro, match="Aprove"):
        A.criar_poses(p["id"], yomi["id"], base)
    AM.aprovar_design(p, yomi["id"])
    A.salvar(p, base)
    A.criar_poses(p["id"], yomi["id"], base)
    p = A.carregar(p["id"], base)
    proj = pp.carregar(next(c for c in p["personagens"] if c["nome"] == "Yomi")["pod"]["pid"], base)
    assert proj["refs"][0] == "design_anime_aprovado.png"
    # ✍ as cenas leem as páginas delas
    A.escrever_cenas(p["id"], base)
    assert vistos[-1][1] == 2 and "ADAPTA AS PÁGINAS 1, 2" in vistos[-1][2]
    p = A.carregar(p["id"], base)
    assert p["cenas"][0]["momentos"][0]["som"] == "porta batendo"
    # ⬇ o JSON da adaptação
    js = AM.json_adaptacao(p)
    y = next(x for x in js["personagens"] if x["nome"] == "Yomi")
    assert y["design"]["estado"] == "aprovado" and y["recorte"]["pagina"] == 1 and y["mudancas_anime"]
    # 📦 exportar com mangá → importar: páginas, adaptação, design aprovado e as páginas das cenas
    import anime2d_zip as AZ
    q = A.criar("", "", "anime", base)
    rel = AZ.importar(q["id"], AZ.exportar(p["id"], base), base, novo=True)
    q = A.carregar(q["id"], base)
    assert rel["paginas"] == 2 and rel["adaptacao"] and q["cenas"][0]["paginas"] == [1, 2]
    qy = next(c for c in q["personagens"] if c["nome"] == "Yomi")
    assert qy["design"]["aprovado"] and not A.precisa_aprovar(qy) and qy["design_en"]
    qk = next(c for c in q["personagens"] if c["nome"] == "Kon")
    assert A.precisa_aprovar(qk)  # o da Kon não foi aprovado


def test_manga_rotas(base, monkeypatch):
    import app as AP
    import anime2d_manga as AM
    import zipfile
    c = AP.app.test_client()
    p = A.criar("M", "", "anime", base)
    pid = p["id"]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in _paginas(3):
            z.writestr("cap/" + n, d)
    r = c.post(f"/anime2d/{pid}/manga/paginas", data={"paginas": (io.BytesIO(b.getvalue()), "cap.zip")}, content_type="multipart/form-data")
    assert r.get_json()["total"] == 3
    assert c.get(f"/anime2d/{pid}/manga/2.jpg").status_code == 200
    assert "ANEXE as páginas" in c.get(f"/anime2d/{pid}/prompt/manga").get_json()["prompt"]
    assert c.post(f"/anime2d/{pid}/colar/manga", json={"texto": json.dumps(ADAPTACAO)}).get_json()["ok"]
    p = A.carregar(pid, base)
    yomi = next(x for x in p["personagens"] if x["nome"] == "Yomi")
    r = c.post(f"/anime2d/{pid}/manga/recorte", json={"pagina": 3, "caixa": [0.1, 0.1, 0.6, 0.7], "tipo": "personagem", "nome": "Yomi"})
    assert r.get_json()["ok"] and len(A.carregar(pid, base)["personagens"][0]["refs"]) == 2
    r = c.post(f"/anime2d/{pid}/design/{yomi['id']}", data={"arquivo": (io.BytesIO(_png()), "d.png")}, content_type="multipart/form-data")
    assert r.get_json()["ok"]
    assert A.precisa_aprovar(next(x for x in A.carregar(pid, base)["personagens"] if x["nome"] == "Yomi"))
    assert c.post(f"/anime2d/{pid}/design/{yomi['id']}", json={}).get_json()["ok"]
    assert not A.precisa_aprovar(next(x for x in A.carregar(pid, base)["personagens"] if x["nome"] == "Yomi"))
    js = json.loads(c.get(f"/anime2d/{pid}/adaptacao.json").data)
    assert js["formato"] == "anime2d_adaptacao_v1" and len(js["cenas"]) == 1
    html = c.get(f"/anime2d/{pid}").get_data(as_text=True)
    assert "📖 Mangá / 🎬 vídeo → anime" in html and "Mangá em tinta" in html and "Vídeo de referência" in html


# ------------------------------------------------------------------ 🎬 v84_238: planos, móveis, lugares, texto, vozes, vídeo
def test_planos_moveis_lugares_e_andar(base, monkeypatch, tmp_path):
    """Cada momento é um corte (geral/médio/close/reação) recortando o MESMO cenário; a cadeira vai atrás e a mesa na
    frente de quem senta; quem muda de lugar anda; sem loop (2º quadro só na transição); pisca nas poses paradas."""
    import anime2d_cena as AC
    p = A.criar("Planos", "x", "anime", base)
    A.aplicar_plano(p, dict(PLANO, locais=[dict(PLANO["locais"][0], props=[{"nome": "Mesa", "prompt_en": "desk", "camada": "frente"},
                                                                          {"nome": "Cadeira", "prompt_en": "chair", "camada": "atras"}],
                                                 lugares=[{"nome": "atrás da mesa", "sentado": True, "descricao": ""}])]))
    lo = p["locais"][0]
    A.guardar_img(p, lo.setdefault("img", {}), Image.open(io.BytesIO(_png((90, 140, 200), (1280, 720), (90, 140, 200)))), False, base, tela_cheia=True)
    for pr in lo["props"]:
        A.guardar_img(p, pr.setdefault("img", {}), Image.open(io.BytesIO(_png((120, 80, 40), (600, 300), (0, 255, 0)))), True, base)
    assert "Mesa" in A.prompt_imagem(p, "local", lo) and "NOT in this image" in A.prompt_imagem(p, "local", lo)
    K = lambda pos, pose="neutro": {"personagem": "Kenta", "posicao": pos, "pose": pose, "olha": "direita"}  # noqa: E731
    M = lambda pos: {"personagem": "Mãe", "posicao": pos, "pose": "sentado", "olha": "esquerda"}  # noqa: E731
    A.aplicar_cena(p, 0, {"momentos": [
        {"tipo": "fala", "quem": "Kenta", "texto": "Oi mãe!", "em_cena": [K("esquerda"), M("atrás da mesa")], "plano": "geral"},
        {"tipo": "fala", "quem": "Kenta", "texto": "Olha isso!", "em_cena": [K("centro_esq", "correndo"), M("atrás da mesa")], "plano": "geral"},
        {"tipo": "acao", "quem": "Mãe", "texto": "ela encara", "duracao": 3, "em_cena": [K("centro_esq"), M("atrás da mesa")], "plano": "close", "foco": "Mãe"},
        {"tipo": "fala", "quem": "Kenta", "texto": "Ué!", "em_cena": [K("centro_esq", "chocado"), M("atrás da mesa")], "plano": "reacao", "foco": "Kenta",
         "fundo_reacao": "impacto"},
        {"tipo": "fala", "quem": "Kenta", "texto": "Tá bom.", "em_cena": [{**K("centro_esq", "triste"), "poses_seguintes": ["bravo"]}, M("atrás da mesa")],
         "plano": "medio"}]})
    A.salvar(p, base)
    m = p["cenas"][0]["momentos"]
    assert [x["plano"] for x in m] == ["geral", "geral", "close", "reacao", "medio"] and m[3]["fundo_reacao"] == "impacto"
    assert m[4]["em_cena"][0]["poses"] == [{"pose": "bravo", "pose_en": ""}] and m[0]["em_cena"][1]["posicao"] == "atrás da mesa"
    kenta, mae = A.achar(p["personagens"], "Kenta"), A.achar(p["personagens"], "Mãe")
    us = A.poses_usadas(p, kenta["id"])
    assert {"andando", "busto_chocado", "bravo"} <= set(us) and "busto_neutro" in A.poses_usadas(p, mae["id"])
    arqs = [x["arquivo"] for x in A.poses_json(p, kenta)["poses"]]
    assert "kenta_neutro_pisca.png" in arqs and "kenta_andando_pisca.png" not in arqs and "kenta_busto_chocado.png" in arqs
    assert "NO furniture" in A.poses_json(p, kenta)["texto_fixo"]["regras"]
    # poses prontas de mentira (figuras com canvas transparente)
    fig = tmp_path / "f.png"
    im = Image.new("RGBA", (600, 900), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle([200, 100, 400, 880], fill=(30, 30, 30, 255)); im.save(fig)
    pos = {"pose": str(fig), "b": str(fig), "boca": str(fig), "pisca": str(fig)}
    monkeypatch.setattr(A, "poses_prontas", lambda c, base=None: {k: dict(pos) for k in ("neutro", "correndo", "chocado", "triste", "bravo",
                                                                                        "andando", "sentado", "busto_neutro", "busto_chocado")})
    p = A.carregar(p["id"], base)
    pl = A.plano_de_camadas(p, base)
    assert [f["plano"] for f in pl["fundos"]] == ["geral", "geral", "close", "reacao", "medio"]
    assert pl["fundos"][2]["arquivo"] != pl["fundos"][0]["arquivo"] and "/_cena/r_impacto" in pl["fundos"][3]["arquivo"]
    cam = pl["camadas"]
    m0 = [c for c in cam if c["a"] < pl["fundos"][0]["fim"]]
    ordem = [c["camada"] for c in m0]
    assert ordem.index("atras") < ordem.index("personagem") and ordem[-1] == "frente"  # cadeira < gente < mesa
    anda = [c for c in cam if c.get("expressao") == "andando"]
    assert anda and anda[0]["desloc"]["de"] < 0 and len({c["img"] for c in anda}) == 2
    so_close = [c for c in cam if pl["fundos"][2]["ini"] <= c["a"] < pl["fundos"][2]["fim"]]
    assert {c["tipo"] for c in so_close} == {"fig"} and {c["cid"] for c in so_close} == {mae["id"]} and so_close[0]["expressao"] == "busto_neutro"
    assert any(c["img"].endswith("_pisca.png") for c in so_close)  # 😑 piscou no plano parado
    seq = [c["expressao"] for c in cam if c.get("cid") == kenta["id"] and c["a"] >= pl["fundos"][4]["ini"]]
    assert seq.index("triste") < seq.index("bravo")  # poses em sequência
    # o andar no render e na prévia batem
    d = anda[0]["desloc"]
    assert A.deslocamento([d], d["a"], 1920, 1080)[0] == pytest.approx(1920 * d["de"]) and A.deslocamento([d], d["b"] + 0.1, 1920, 1080)[0] == 0
    import video_assembler as va
    assert "min(1,max(0," in va._mov_expr([d], "x")
    jd = tmp_path / "job"
    jd.mkdir()
    ed = A.montar_editor(p, base, str(jd))
    assert len(ed["segmentos"]) == 5 and {o["camada"] for o in ed["overlays"]} >= {"atras", "personagem", "frente", "legenda"}
    assert A.previa(p, base, str(tmp_path / "pv.jpg"), pl["fundos"][1]["ini"] + 0.2)


def test_destaque_com_personagens_texto_e_cenario(base, monkeypatch):
    """🌟 O destaque leva a referência do design de quem aparece + o fundo do lugar, e escreve o texto que faz parte da cena."""
    import flow_lote
    p = A.criar("Dest", "x", "anime", base)
    A.aplicar_plano(p, dict(PLANO, itens=[{"nome": "Bilhete", "tipo": "destaque", "prompt_en": "a note", "personagens": ["Mãe"],
                                           "texto": "VISTA-SE COMO UMA GAROTA"}]))
    A.aplicar_cena(p, 0, {"momentos": [{"tipo": "destaque", "quem": "", "texto": "", "destaque": "Bilhete", "duracao": 2, "em_cena": []}]})
    lo = p["locais"][0]
    A.guardar_img(p, lo.setdefault("img", {}), Image.open(io.BytesIO(_png((90, 140, 200), (1280, 720), (90, 140, 200)))), False, base, tela_cheia=True)
    mae = A.achar(p["personagens"], "Mãe")
    A.guardar_img(p, mae.setdefault("design", {}), Image.open(io.BytesIO(_png())), False, base)
    mae["design"]["aprovado"] = mae["design"]["arquivo"]
    A.salvar(p, base)
    it = p["itens"][0]
    pr = A.prompt_imagem(p, "item", it)
    assert "VISTA-SE COMO UMA GAROTA" in pr and "Mãe" in pr and "SETTING" in pr and "speech balloons" in pr
    capt = []

    class L:
        def adicionar(self, itens, **kw):
            capt.extend(itens)
            return [{"id": f"j{k}"} for k in range(len(itens))]

        def iniciar(self):
            pass
    monkeypatch.setattr(flow_lote, "lote", lambda: L())
    A.gerar_imagens(p["id"], base, [it["id"]])
    ref = Image.open(capt[0]["referencia_arquivo"])
    assert ref.width > ref.height  # colagem: o design + o fundo (+ estilo)


def test_vozes_todas_e_agrupadas(base, monkeypatch):
    """🎙 Os 🗣️ perfis de voz também aparecem; a geração faz TODAS as falas de uma voz em seguida."""
    import multivoz
    import perfis_info
    import sys as _s
    import types
    monkeypatch.setattr(multivoz, "listar", lambda: [{"slug": "ana", "nome": "Ana", "motor": "piper", "config": {}}])
    monkeypatch.setattr(multivoz, "por_slug", lambda: {"ana": {"slug": "ana", "nome": "Ana", "motor": "piper", "config": {}}})
    monkeypatch.setattr(multivoz, "kwargs_da_voz", lambda v: (v["motor"], {"voz": v["slug"]}))
    monkeypatch.setattr(perfis_info, "todos", lambda: {"Zé": {"genero": "masculino"}})
    fake = types.ModuleType("tts.voice_generator")
    fake.listar_perfis_de_voz = lambda: ["Zé"]
    monkeypatch.setitem(_s.modules, "tts.voice_generator", fake)
    vs = A.vozes_disponiveis("chatterbox")
    assert {v["slug"] for v in vs} == {"ana", "perfil:Zé"} and A.voz_por_slug("perfil:Zé", "chatterbox")["motor"] == "chatterbox"
    p = A.criar("V", "x", "anime", base)
    A.aplicar_plano(p, PLANO)
    A.aplicar_cena(p, 0, CENA1)
    A.aplicar_cena(p, 1, CENA2)
    A.achar(p["personagens"], "Kenta")["voz"] = "perfil:Zé"
    A.achar(p["personagens"], "Mãe")["voz"] = "ana"
    p["narrador"] = {"ativo": True, "voz": "ana"}
    A.salvar(p, base)
    ordem = []

    def tts(motor, texto, saida, **kw):
        ordem.append(kw.get("voz") or kw.get("voice_profile"))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=d=0.5", saida], check=True)
    monkeypatch.setattr(multivoz, "kwargs_da_voz", lambda v: (v["motor"], {"voz": v["slug"]} if v["motor"] == "piper" else {"voice_profile": v["config"]["vozPerfil"]}))
    A.gerar_vozes(p["id"], base, tts, lambda t, m: t)
    assert ordem == sorted(ordem, key=lambda x: ordem.index(x))  # agrupadas: nenhuma voz volta depois de outra
    assert len([i for i in range(1, len(ordem)) if ordem[i] != ordem[i - 1]]) == 1


def test_video_de_referencia(base, tmp_path):
    """🎬 Um vídeo → quadros-chave com o segundo de cada um (as “páginas”), o áudio vira o do episódio, e a IA recebe o
    pedido de recriar a cena com os personagens do projeto."""
    import anime2d_manga as AM
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=8:s=320x240:r=10", "-f", "lavfi", "-i", "sine=d=8",
                    "-shortest", "-pix_fmt", "yuv420p", str(v)], check=True)
    p = A.criar("Vid", "o homem de terno = Kenta", "anime", base)
    r = AM.guardar_video(p, "v.mp4", v.read_bytes(), base, True)
    assert r["quadros"] >= 3 and r["audio"] and A.e_video(p) and len(p["manga"]["tempos"]) == r["quadros"]
    assert "s do vídeo" in A.rotulo_pagina(p, 2) and "RECRIAR uma cena" in AM.sys_adaptacao(p) and "QUADROS DO VÍDEO" in AM.prompt_adaptacao(p)
    AM.guardar_paginas(p, [("1.png", _png())], base, substituir=True)
    assert not A.e_video(p)  # páginas de mangá de novo: volta a ser mangá


def test_ritmo_jashin_cobertura_respira_pulo():
    """🎬 v84_238c: fala longa vira cortes; respiração e pulinho batem entre a prévia e o render."""
    import anime2d as A
    import anime2d_cena as C
    import video_assembler as VA
    ms = [{"id": "m1", "tipo": "fala", "quem": "a", "foco": "", "plano": "geral", "camera": "fixa", "ini": 0.0, "fim": 7.0,
           "em_cena": [{"cid": "a"}, {"cid": "b"}]},
          {"id": "m2", "tipo": "fala", "quem": "b", "plano": "medio", "camera": "tremida", "ini": 7.0, "fim": 8.5,
           "em_cena": [{"cid": "a"}, {"cid": "b"}]}]
    ts = {"ini": 0.0, "fim": 8.5}
    cs = C.cobertura({}, ms, ts)
    assert [c["corte"] for c in cs] == [0, 1, 2, 0]
    assert [(c["plano"], c["foco"]) for c in cs[:3]] == [("geral", "a"), ("close", "a"), ("medio", "b")]
    assert cs[1]["corte_ini"] > 0 and cs[3]["corte_ini"] == 7.0
    assert len(C.cobertura({"cobertura": False}, ms, ts)) == 2
    mov = [{"a": 0.0, "b": 99999.0, "resp": 0.004, "f": 1.0}, {"a": 2.0, "b": 2.28, "pulo": 0.03}]
    x, y = A.deslocamento(mov, 2.14, 1920, 1080)
    assert x == 0 and y < -20  # no meio do pulo: lá em cima
    assert "sin(t*" in VA._mov_expr(mov, "y") and "PI" in VA._mov_expr(mov, "y") and VA._mov_expr(mov, "x") == ""


def test_pisca_espera_a_pose_de_base(tmp_path, monkeypatch):
    """🐛 v84_238c: 'Gerar o que falta' com a pose ainda sem imagem quebrava ('NoneType' has no attribute 'save') —
    o piscando/2º quadro (edita_base) agora espera a pose de base e segue sozinho depois."""
    import json as _j
    import personagens_pod as pp
    import flow_lote

    class Lote:
        def __init__(self):
            self.itens = []

        def adicionar(self, itens, **kw):
            self.itens += itens
            return [{"id": f"j{i}"} for i in range(len(itens))]

        def iniciar(self):
            pass
    lt = Lote()
    monkeypatch.setattr(flow_lote, "lote", lambda: lt)
    dados = {"formato": "personagens_pod_v1", "personagem": "g", "nome": "G", "texto_fixo": {"trava": "girl"},
             "fundo": "verde", "flow": {"proporcao": "3:4"},
             "poses": [{"arquivo": "g_neutro.png", "tipo": "pose", "prompt": "standing", "mestre": True},
                       {"arquivo": "g_x.png", "tipo": "pose", "prompt": "sitting"},
                       {"arquivo": "g_x_pisca.png", "tipo": "pose", "prompt": "blink", "pose_base": "g_x.png", "edita_base": True}]}
    base = str(tmp_path)
    q = pp.criar("G", _j.dumps(dados), [], base=base, motor="flow")
    r = pp.enviar(q["id"], ["g_x_pisca.png"], base=base)
    assert r["ok"]
    assert len(lt.itens) == 1 and "g_x_pisca.png" in r["depois"]  # mandou a pose; o piscando espera


def test_local_variante_usa_o_original(tmp_path):
    """🌫 v84_238e: 'Quarto cheio de fumaça' (variante_de 'Quarto') usa os lugares/móveis/chão do original."""
    import anime2d as A
    p = {"locais": [{"id": "l1", "nome": "Quarto", "props": [{"nome": "Poltrona", "x": 0.2, "y": 0.9}],
                     "lugares": [{"nome": "na poltrona", "sentado": True, "x": 0.2, "y": 0.88, "escala": 1}],
                     "chao": {"y": 0.97, "alt": 0.6}},
                    {"id": "l2", "nome": "Quarto cheio de fumaça", "variante_de": "Quarto", "props": [], "lugares": []}]}
    v = p["locais"][1]
    assert A.base_do_local(p, v)["id"] == "l1" and A.base_do_local(p, p["locais"][0]) is None
    assert "na poltrona" in A.lugares_do_local(p, v)
    assert A.layout_do_local(p, v)["props"][0]["nome"] == "Poltrona"
    pr = A.prompt_imagem({"estilo": "anime", "proporcao": "16:9"}, "local", dict(v, prompt_en="filled with smoke"))
    assert pr.startswith("EDIT the reference image") and "filled with smoke" in pr


def test_planta_layout_angulo(tmp_path):
    """📐 v84_238f: a planta vira o esboço + o texto de layout do fundo; móveis pegam a posição dela; ângulos e visão."""
    import anime2d as A
    import anime2d_planta as PL
    lo = {"id": "l1", "nome": "Quarto", "props": [], "lugares": []}
    A.aplicar_props_lugares(lo, {"props": [{"nome": "Poltrona", "camada": "atras", "real": 0.95}],
                                 "planta": {"camera": "da porta", "camera_en": "from the door, facing the window wall",
                                            "fora_de_quadro": "a porta", "fora_de_quadro_en": "the door",
                                            "elementos": [{"nome": "Fornalha", "en": "a round iron furnace", "onde": "direita",
                                                           "x": 0.8, "y": 0.92, "w": 0.3, "h": 0.55, "camada": "fundo"},
                                                          {"nome": "Poltrona", "en": "an armchair", "onde": "chao",
                                                           "x": 0.22, "y": 0.93, "w": 0.2, "h": 0.3, "camada": "movel"}]}})
    assert lo["props"][0]["x"] == 0.22 and lo["props"][0]["y"] == 0.93  # o móvel pegou a posição da planta
    p = {"id": "x", "estilo": "anime", "proporcao": "16:9", "locais": [lo], "personagens": [], "itens": []}
    pr = A.prompt_imagem(p, "local", lo)
    assert "RED block = a round iron furnace" in pr and "RIGHT third" in pr and "WHITE DASHED" in pr and "the door" in pr
    cam = PL.esboco(lo["planta"], str(tmp_path), 1920, 1080)
    assert cam and os.path.isfile(cam)
    ang = {"id": "l2", "nome": "Canto da fornalha", "props": [], "lugares": [{"nome": "na fornalha", "x": 0.3, "y": 0.95}]}
    A.aplicar_props_lugares(ang, {"angulo_de": "Quarto", "angulo_en": "close to the furnace corner"})
    p["locais"].append(ang)
    assert A.angulo_base(p, ang) is lo and [x["id"] for x in A.familia_do_local(p, lo)] == ["l1", "l2"]
    assert "ANOTHER CAMERA ANGLE: close to the furnace corner" in A.prompt_imagem(p, "local", ang)
    s = {"id": "s1", "local": "l1"}
    m = A.limpar_momento(p, {"tipo": "acao", "texto": "x", "angulo": "Canto da fornalha", "visao": "ela de perto; a janela fora"})
    assert m["angulo"] == "l2" and m["visao"].startswith("ela de perto") and A.local_do_momento(p, s, m) is ang


def test_texto_de_abertura_no_editor(tmp_path):
    """🔤 v84_238g: p['abertura_texto'] (ex.: 'Prólogo') vira o texto do 1º trecho do editor, em cima."""
    import anime2d_cena as C
    src = open(C.__file__, encoding="utf-8").read()
    assert "abertura_texto" in src and "ABERTURA_DUR" in src and '"position": "top-center"' in src


def test_png_estragado_nao_derruba_a_montagem(tmp_path):
    """🐛 v84_238g: 'cannot identify image file …_pisca__36.png' (cache pela metade de uma montagem interrompida)."""
    import video_assembler as VA
    from PIL import Image
    src = tmp_path / "0016_g_x_pisca.png"
    Image.new("RGBA", (80, 120), (255, 0, 0, 255)).save(src)
    ruim = tmp_path / "0016_g_x_pisca__36.png"
    ruim.write_bytes(b"\x89PNG\r\n\x1a\n pela metade")
    os.utime(ruim, (os.path.getmtime(src) + 10, os.path.getmtime(src) + 10))  # mais novo que a original: antes era aceito
    pronto = VA._png_no_tamanho(str(src), 36, False)
    assert pronto and VA._png_valido(pronto)
    with Image.open(pronto) as im:
        assert im.size[0] == 36


def test_storyboard_e_revisao_pela_ia(base, monkeypatch, tmp_path):
    """🎬🔎 v84_238h: o Flow desenha a cena no fundo (storyboard) → a IA lê as posições → lugares/móveis; e a revisão:
    um quadro por corte, a IA aponta o erro com uma correção (mover lugar, trocar plano, corte de reação, regerar)."""
    import anime2d_revisao as RV
    import flow_lote
    import ia_servico
    p = A.criar("Story", "x", "anime", base)
    A.aplicar_plano(p, dict(PLANO, locais=[dict(PLANO["locais"][0], props=[{"nome": "Sofá", "prompt_en": "a sofa", "camada": "atras"}],
                                                 lugares=[{"nome": "no sofá", "sentado": True, "descricao": ""}])]))
    lo = p["locais"][0]
    A.guardar_img(p, lo.setdefault("img", {}), Image.open(io.BytesIO(_png((90, 140, 200), (1280, 720), (90, 140, 200)))), False, base, tela_cheia=True)
    A.aplicar_cena(p, 0, {"momentos": [
        {"tipo": "fala", "quem": "Kenta", "texto": "Oi!", "em_cena": [{"personagem": "Kenta", "posicao": "esquerda", "pose": "feliz"},
                                                                     {"personagem": "Mãe", "posicao": "no sofá", "pose": "sentado"}], "plano": "geral"},
        {"tipo": "fala", "quem": "Mãe", "texto": "Oi, filho.", "em_cena": [{"personagem": "Kenta", "posicao": "esquerda", "pose": "feliz"},
                                                                          {"personagem": "Mãe", "posicao": "no sofá", "pose": "sentado"}], "plano": "medio"}]})
    A.salvar(p, base)
    pedidos = []

    class Lote:
        def adicionar(self, itens, **kw):
            pedidos.extend(itens)
            return [{"id": "j1"}]

        def iniciar(self):
            pass
    monkeypatch.setattr(flow_lote, "lote", lambda: Lote())
    RV.pedir_storyboard(p["id"], lo["id"], base)
    assert "STORYBOARD" in pedidos[0]["prompt"] and "Kenta" in pedidos[0]["prompt"] and "sitting ON the seat" in pedidos[0]["prompt"]
    p = A.carregar(p["id"], base)
    lo = p["locais"][0]
    assert lo["story"]["estado"] == "fila" and {o["lugar"] for o in lo["story"]["ocupantes"]} == {"esquerda", "no sofá"}
    A.guardar_img(p, lo["story"], Image.open(io.BytesIO(_png((90, 140, 200), (1280, 720), (90, 140, 200)))), False, base, tela_cheia=True)
    A.salvar(p, base)

    def falsa(recurso, system, conteudo, **kw):
        if "STORYBOARD" in conteudo[0]["text"]:
            return {"lugares": [{"lugar": "esquerda", "visivel": True, "x0": 0.1, "y0": 0.4, "x1": 0.3, "y1": 0.95, "pes_x": 0.2, "pes_y": 0.95},
                                {"lugar": "no sofá", "visivel": True, "x0": 0.5, "y0": 0.45, "x1": 0.7, "y1": 0.85, "pes_x": 0.6, "pes_y": 0.85}],
                    "moveis": [{"nome": "Sofá", "visivel": True, "x0": 0.45, "y0": 0.5, "x1": 0.8, "y1": 0.9}]}
        return {"quadros": [{"n": 1, "ok": False, "problemas": [
            dict({k: "" for k in ("local", "lugar", "movel", "plano", "foco", "angulo", "personagem", "pose_en", "alvo", "pedido")},
                 descricao="Kenta flutuando", acao="lugar", local="Sala", lugar="esquerda", x=0.22, y=0.97, escala=1.1, w=0),
            dict({k: "" for k in ("local", "lugar", "movel", "plano", "foco", "angulo", "personagem", "pose_en", "alvo", "pedido")},
                 descricao="falta a reação da mãe", acao="corte_reacao", personagem="Mãe", pose_en="smiling softly", x=0, y=0, escala=0, w=0),
            dict({k: "" for k in ("local", "lugar", "movel", "plano", "foco", "angulo", "personagem", "pose_en", "alvo", "pedido")},
                 descricao="mão deformada", acao="regerar", alvo="pose:Kenta:feliz", pedido="mão com 5 dedos", x=0, y=0, escala=0, w=0)]}]} \
            if "QUADRO 1" in str(conteudo) and not getattr(falsa, "feito", False) and not setattr(falsa, "feito", True) else {"quadros": []}
    monkeypatch.setattr(ia_servico, "chamar", falsa)
    msg = RV.ler_storyboard(p["id"], lo["id"], base)
    p = A.carregar(p["id"], base)
    lo = p["locais"][0]
    lg = {x["nome"]: x for x in lo["lugares"]}
    assert "posição" in msg and lg["esquerda"]["x"] == 0.2 and lg["no sofá"]["y"] == 0.85 and lg["esquerda"]["escala"] > 0.5
    assert lo["props"][0]["x"] == pytest.approx(0.625) and lo["props"][0]["w_manual"]
    fig = tmp_path / "f.png"
    im = Image.new("RGBA", (600, 900), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle([200, 100, 400, 880], fill=(30, 30, 30, 255)); im.save(fig)
    monkeypatch.setattr(A, "poses_prontas", lambda c, base=None: {k: {"pose": str(fig)} for k in ("neutro", "feliz", "sentado", "busto_neutro")})
    msg = RV.revisar(p["id"], base)
    p = A.carregar(p["id"], base)
    lg = {x["nome"]: x for x in p["locais"][0]["lugares"]}
    ms = p["cenas"][0]["momentos"]
    assert lg["esquerda"]["escala"] == 1.1 and len(ms) == 3 and ms[1]["plano"] == "close" and ms[1]["em_cena"][1]["pose_en"] == "smiling softly"
    assert p["revisao"]["sugestoes"] and "mão com 5 dedos" in p["revisao"]["sugestoes"][0] and "corrigido" in msg


def test_troca_de_angulo_a_cada_10s_que_condiz():
    """🎥 v84_238j: sem 'angulo', depois de ~10 s no mesmo ângulo a câmera troca pra outro ângulo do MESMO cômodo e
    estado em que os lugares de quem está em cena existem (vai pra onde a ação está); nunca pra variante; volta pra
    câmera principal quando quem está em cena não cabe no ângulo."""
    import anime2d_cena as C
    q = {"id": "l1", "nome": "Quarto", "lugares": [{"nome": "na poltrona", "sentado": True, "x": .2, "y": .9}, {"nome": "na fornalha", "x": .5, "y": .97}]}
    canto = {"id": "l2", "nome": "Canto", "angulo_de": "Quarto", "lugares": [{"nome": "na fornalha", "x": .6, "y": .98}]}
    fum = {"id": "l3", "nome": "Quarto com fumaça", "variante_de": "Quarto", "lugares": []}
    p = {"locais": [q, canto, fum], "personagens": [{"id": "c1", "nome": "G"}], "troca_angulo_s": 10}
    s = {"id": "s1", "local": "l1"}

    def mm(t, pos, **kw):
        return dict({"id": f"m{t}", "tipo": "acao", "corte_ini": t, "em_cena": [{"cid": "c1", "posicao": pos}], "foco": "c1"}, **kw)
    ms = [mm(0, "na poltrona"), mm(4, "na poltrona"), mm(11, "na poltrona"), mm(13, "na fornalha"), mm(25, "na fornalha"),
          mm(37, "na poltrona"), mm(40, "centro", angulo="l1")]
    los = [x["id"] for x in C.angulos_auto(p, s, {"ini": 0}, ms)]
    assert los[:3] == ["l1", "l1", "l1"]  # a poltrona não existe no canto: não troca
    assert los[3] == "l2"  # 13 s, ela foi pra fornalha: a câmera vai pro canto da fornalha
    assert los[4] == "l1"  # mais 10 s: troca de novo (pode repetir)
    assert los[5] == "l1" and los[6] == "l1" and "l3" not in los  # nunca vira a variante (fumaça)
    p["troca_angulo_s"] = 0
    assert {x["id"] for x in C.angulos_auto(p, s, {"ini": 0}, ms)} == {"l1"}
