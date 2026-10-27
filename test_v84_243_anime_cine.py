"""🎬 v84_243 — Anime quadro a quadro: o Flow só desenha (chave + desenhos em sequência a partir do anterior) e a
animação é montada aqui (tempos em 2, câmera, impacto, efeitos, transições, legendas, vozes e sons)."""
import io
import json
import os
import subprocess
import threading
import time

import pytest
from PIL import Image, ImageDraw

import anime_cine as AC
import criador_personagens as C


@pytest.fixture
def base(tmp_path, monkeypatch):
    for k, v in (("ANIME_CINE_DIR", "cine"), ("CRIADOR_PERSONAGENS_DIR", "criador"), ("PERSONAGENS_POD_DIR", "pod"),
                 ("ANIME2D_DIR", "a2d"), ("REACT_PERSONAGENS_DIR", "react")):
        monkeypatch.setenv(k, str(tmp_path / v))
    return str(tmp_path)


class Lote:
    def __init__(self):
        self.trava = threading.Lock()
        self.fila, self.rodando, self.itens, self.n = [], True, [], 0

    def adicionar(self, itens, modelo="", proporcao="16:9", quantidade="x1", **kw):
        out = []
        for it in itens:
            self.n += 1
            j = {"id": f"j{self.n}", "estado": "fila", "resultados": [], "item": it}
            self.fila.append(j)
            self.itens.append(it)
            out.append({"id": j["id"]})
        return out

    def iniciar(self):
        pass


@pytest.fixture
def lote(monkeypatch, tmp_path):
    import flow_estudio as FE
    import flow_lote
    L = Lote()
    monkeypatch.setattr(flow_lote, "lote", lambda: L)
    gal = tmp_path / "gal"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    L.gal = gal
    return L


def _terminar(L):
    for j in L.fila:
        if j["estado"] == "fila":
            im = Image.new("RGB", (1280, 720), (30 + L.n * 7 % 200, 60, 120))
            ImageDraw.Draw(im).ellipse([500, 200, 780, 520], fill=(240, 200, 60))
            nome = f"{j['id']}.png"
            im.save(L.gal / nome)
            j.update(estado="ok", resultados=[{"tipo": "imagem", "arquivo": nome}])


PLANO_IA = {"titulo": "A ponte", "planos": [
    {"dur": 2.0, "tipo": "estabelecimento", "camera": "zoom_in", "efeitos": ["brasas", "vinheta"], "transicao": "corte",
     "acao_pt": "a ponte na chuva", "quem": ["Kaito"], "falas": [{"quem": "Kaito", "texto": "Chegou a sua hora.", "t": 0.5}],
     "sfx": [{"som": "tensao", "t": 0}], "desenhos": [{"prompt_en": "Kaito on the bridge in the rain", "segura": 1, "impacto": False}]},
    {"dur": 1.5, "tipo": "close", "camera": "chicote", "efeitos": ["linhas", "flash"], "transicao": "flash",
     "acao_pt": "o golpe", "quem": ["kaito", "Demônio"], "falas": [], "sfx": [{"som": "espada", "t": 0.2}],
     "desenhos": [{"prompt_en": "Kaito draws the sword", "segura": 1, "impacto": False},
                  {"prompt_en": "the blade swings, water trail", "segura": 1, "impacto": False},
                  {"prompt_en": "the blade hits the demon", "segura": 2, "impacto": True}]},
    {"dur": 1.2, "tipo": "geral", "camera": "tremor", "efeitos": ["tremor", "foco"], "transicao": "preto",
     "acao_pt": "o demônio se desfaz", "quem": ["Demônio"], "falas": [{"quem": "Demônio", "texto": "Não!", "t": 0.1}],
     "sfx": [], "desenhos": [{"prompt_en": "the demon turns to ash", "segura": 1, "impacto": False}]}]}


def _proj(base):
    p = AC.criar("A ponte", base, roteiro="Kaito corta o demônio na ponte", duracao=5, estilo="anime")
    AC.personagem_seu(p, Image.new("RGB", (300, 500), (200, 30, 30)), "Kaito", "young swordsman, black hair, checkered haori", base)
    AC.personagem_seu(p, Image.new("RGB", (300, 500), (30, 30, 30)), "Demônio", "pale demon with horns", base)
    AC.aplicar_planos(p, PLANO_IA)
    AC.salvar(p, base)
    return p


def test_planos_tempos_e_fontes(base, monkeypatch):
    p = _proj(base)
    kaito, demo = p["personagens"][0]["id"], p["personagens"][1]["id"]
    assert p["planos"][1]["quem"] == [kaito, demo] and p["planos"][0]["falas"][0]["quem"] == kaito
    assert p["planos"][1]["quadros"][2]["impacto"] and AC.duracao_total(p) == pytest.approx(4.7)
    for pl in p["planos"]:
        assert sum(n for _k, n in AC._tempos(pl, len(pl["quadros"]))) == round(pl["dur"] * AC.FPS)
    # a IA recebe o roteiro, as páginas e os personagens
    visto = {}

    class IA:
        @staticmethod
        def imagem_bloco(cam, larg=320):
            return {"type": "image"}

        @staticmethod
        def chamar(rec, sys, conteudo, schema=None, **kw):
            visto.update(rec=rec, txt=conteudo[0]["text"], sys=sys, n=len(conteudo))
            return PLANO_IA
    monkeypatch.setattr(C, "ia_ligada", lambda: True)
    monkeypatch.setattr(C, "_ia", lambda: IA)
    AC.guardar_pagina(p, Image.new("RGB", (800, 1200), (255, 255, 255)), base)
    AC.salvar(p, base)
    AC.planejar(p["id"], base)
    assert visto["rec"] == "anime_cine" and "Kaito" in visto["txt"] and "PÁGINAS DE MANGÁ: 1" in visto["txt"] and "DESENHOS" in visto["sys"]
    assert len(AC.carregar(p["id"], base)["planos"]) == 3
    # puxar um personagem do 🧬 Criador (o design aprovado) e um lugar com foto
    k = C.criar("Akemi", base)
    v = {"id": "vx", "estado": "fila"}
    k["design"]["variacoes"].append(v)
    im = Image.new("RGB", (600, 900), (0, 255, 0))
    ImageDraw.Draw(im).rectangle([200, 100, 400, 850], fill=(200, 50, 50))
    C.guardar_design(k, v, im, base)
    k["design"]["aprovado"] = "vx"
    C.aplicar_ficha(k, {"aparencia_en": "red hair girl"})
    C.salvar(k, base)
    fontes = AC.fontes_personagens(base)
    assert any(f["fonte"] == f"criador:{k['id']}" for f in fontes)
    q = AC.carregar(p["id"], base)
    c = AC.importar_personagem(q, f"criador:{k['id']}", base)
    assert c["aparencia_en"] == "red hair girl" and os.path.isfile(os.path.join(AC.pasta(p["id"], base), "refs", c["imagem"]))
    import criador_lugares as CL
    lg = CL.criar("Ponte Velha", "casa", "", base, descricao="old wooden bridge")
    CL.enviar_imagem(lg["id"], Image.new("RGB", (1280, 720), (10, 40, 60)), "foto", base)
    AC.editar_entrada(q, {"lugar": lg["id"]})
    desc, img = AC.lugar_info(q, base)
    assert "wooden bridge" in desc and os.path.isfile(img)


def test_flow_so_desenha_chave_e_sequencia(base, lote):
    p = _proj(base)
    r = AC.gerar_chaves(p["id"], None, "mais chuva", base)
    assert r["enviadas"] == 3 and all(it["tipo"] == "imagem" for it in lote.itens)  # nada de vídeo
    it = lote.itens[1]
    assert os.path.isfile(it["referencia_arquivo"]) and "2 panels" in it["prompt"] and "Kaito" in it["prompt"]
    assert "NO text" in it["prompt"] and "mais chuva" in it["prompt"] and "close-up" in it["prompt"]
    _terminar(lote)
    AC.acompanhar(p["id"], base)
    p = AC.carregar(p["id"], base)
    pl = p["planos"][1]
    assert pl["quadros"][0]["arquivo"] and Image.open(os.path.join(AC.pasta(p["id"], base), "quadros", pl["quadros"][0]["arquivo"])).size == (1920, 1080)
    with pytest.raises(AC.CineErro):
        AC.gerar_sequencia(p["id"], [pl["id"]], base)  # sem aprovar a chave, não
    AC.aprovar_chave(p["id"], pl["id"], True, base)
    assert AC.gerar_sequencia(p["id"], [pl["id"]], base)["enviadas"] == 1
    seq1 = lote.itens[-1]
    p = AC.carregar(p["id"], base)
    pl = p["planos"][1]
    assert seq1["referencia_arquivo"].endswith(pl["quadros"][0]["arquivo"]) and "PREVIOUS DRAWING" in seq1["prompt"]
    _terminar(lote)
    AC.acompanhar(p["id"], base)  # o 2º chega → o 3º vai sozinho, a partir do 2º
    p = AC.carregar(p["id"], base)
    pl = p["planos"][1]
    assert pl["quadros"][1]["arquivo"] and pl["quadros"][2]["estado"] == "fila"
    assert lote.itens[-1]["referencia_arquivo"].endswith(pl["quadros"][1]["arquivo"]) and "hits the demon" in lote.itens[-1]["prompt"]
    _terminar(lote)
    AC.acompanhar(p["id"], base)
    AC.acompanhar(p["id"], base)
    p = AC.carregar(p["id"], base)
    assert all(q.get("arquivo") for q in p["planos"][1]["quadros"]) and not p["planos"][1]["sequencia"]
    # refazer um desenho do meio: a referência é o anterior
    q1 = p["planos"][1]["quadros"][1]
    AC.refazer_quadro(p["id"], p["planos"][1]["id"], q1["id"], "mais rastro de água", base)
    assert lote.itens[-1]["referencia_arquivo"].endswith(p["planos"][1]["quadros"][0]["arquivo"]) and "mais rastro" in lote.itens[-1]["prompt"]
    _terminar(lote)
    AC.acompanhar(p["id"], base)
    q1 = AC.carregar(p["id"], base)["planos"][1]["quadros"][1]
    assert len(q1["versoes"]) == 2
    AC.escolher_versao(p["id"], p["planos"][1]["id"], q1["id"], q1["versoes"][0], base)


def _dur(cam):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", cam],
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    return float(d["format"]["duration"]), {s["codec_type"] for s in d["streams"]}


def test_montagem_vozes_e_sons(base, lote, monkeypatch):
    p = _proj(base)
    AC.gerar_chaves(p["id"], None, "", base)
    _terminar(lote)
    AC.acompanhar(p["id"], base)
    p = AC.carregar(p["id"], base)
    for pl in p["planos"]:
        AC.aprovar_chave(p["id"], pl["id"], True, base)
    AC.gerar_sequencia(p["id"], None, base)
    for _ in range(4):
        _terminar(lote)
        AC.acompanhar(p["id"], base)
    # 🎙 vozes (TTS de mentira)
    import anime2d as A
    import multivoz
    monkeypatch.setattr(A, "voz_por_slug", lambda slug, mp="xtts": {"slug": slug} if slug else None)
    monkeypatch.setattr(multivoz, "kwargs_da_voz", lambda v: ("teste", {}))

    def tts(motor, texto, saida, **kw):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.8", saida], check=True)
    q = AC.carregar(p["id"], base)
    for c in q["personagens"]:
        AC.editar_personagem(q, c["id"], {"voz": "voz1"}, base)
    AC.salvar(q, base)
    r = AC.gerar_vozes(p["id"], base, tts, lambda t, m: t)
    assert r["feitas"] == 2 and r["sem_voz"] == 0
    assert AC.gerar_vozes(p["id"], base, tts, lambda t, m: t)["feitas"] == 0  # nada mudou: não refaz
    # 💥 quadro de impacto: negativo nos 2 primeiros quadros do desenho
    q = AC.carregar(p["id"], base)
    g = AC._Plano(q, q["planos"][1], base, 480, 270)
    assert g.impactos and g.quadro(g.impactos[0]).getpixel((5, 5)) != g.quadro(g.impactos[0] + 4).getpixel((5, 5))
    # 🎬 a cena inteira (um quarto da resolução pra ser rápido)
    nome = AC.montar(p["id"], base, None, 0.25)
    cam = os.path.join(AC.pasta(p["id"], base), "saida", nome)
    dur, tipos = _dur(cam)
    assert abs(dur - 4.7) < 0.25 and tipos == {"video", "audio"}
    assert AC.carregar(p["id"], base)["saida"]["mp4"] == nome
    eventos = AC._sfx_globais(AC.carregar(p["id"], base))
    assert len(eventos) >= 3  # tensão, espada e o impacto automático
    # prévia de um plano só
    pv = AC.montar(p["id"], base, [q["planos"][1]["id"]], 0.25)
    assert abs(_dur(os.path.join(AC.pasta(p["id"], base), "saida", pv))[0] - 1.5) < 0.2


def test_rotas(base, lote):
    import app as AP
    c = AP.app.test_client()
    assert "Anime quadro a quadro" in c.get("/modelos-video").get_data(as_text=True)
    r = c.post("/anime-cine/novo", data={"titulo": "Teste", "roteiro": "um soco\no outro voa", "duracao": "6"}, content_type="multipart/form-data")
    pid = r.headers["Location"].split("/")[-1]
    h = c.get(f"/anime-cine/{pid}").get_data(as_text=True)
    assert "storyboard" in h and "Prévia" in h
    assert c.post(f"/anime-cine/{pid}/personagem/seu", data={"arquivo": (io.BytesIO(_png()), "k.png"), "nome": "Kaito"},
                  content_type="multipart/form-data").get_json()["ok"]
    assert c.post(f"/anime-cine/{pid}/planejar", json={}).get_json()["ok"]  # sem IA: um plano por linha
    for _ in range(60):
        t = c.get(f"/anime-cine/{pid}/estado").get_json()["tarefa"]
        if t and t.get("fim"):
            break
        time.sleep(0.05)
    e = c.get(f"/anime-cine/{pid}/estado").get_json()
    assert len(e["planos"]) == 2
    pls = e["planos"]
    pls[0]["quadros"].append({"id": "", "prompt_en": "the fist lands", "segura": 2, "impacto": True})
    pls[0]["efeitos"] = ["linhas", "nao_existe"]
    assert c.post(f"/anime-cine/{pid}/planos", json={"planos": pls}).get_json()["ok"]
    e = c.get(f"/anime-cine/{pid}/estado").get_json()
    assert len(e["planos"][0]["quadros"]) == 2 and e["planos"][0]["efeitos"] == ["linhas"] and e["planos"][0]["quadros"][1]["id"]
    assert c.post(f"/anime-cine/{pid}/chaves", json={}).get_json()["enviadas"] == 2
    assert c.post(f"/anime-cine/{pid}/editor", json={}).status_code == 400  # sem o mp4 ainda
    assert c.post(f"/anime-cine/{pid}/excluir").status_code == 302


def _png():
    b = io.BytesIO()
    Image.new("RGB", (300, 400), (90, 90, 200)).save(b, "PNG")
    return b.getvalue()
