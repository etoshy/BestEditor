"""v84_182: 🎞 Animar cenas com o Google Flow — imagem → vídeo (frame de Início) pelo 🚀 Flow em massa, prompt da IA
(do prompt da imagem ou do contexto), corte no tempo da cena (início/meio/fim/livre), voltar pra imagem e sugestões."""
import os
import re
import subprocess
import threading

import pytest

import animar_flow as af


def _video(caminho: str, dur: float = 8.0) -> str:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=24:duration={dur}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", caminho], check=True)
    return caminho


def _png(caminho: str) -> str:
    from PIL import Image
    Image.new("RGB", (320, 180), (200, 40, 40)).save(caminho)
    return caminho


# ------------------------------------------------------------------ corte
def test_janela_sempre_com_a_duracao_da_cena():
    assert af.calcular_janela(8.0, 3.0, "inicio") == (0.0, 1.0)
    assert af.calcular_janela(8.0, 3.0, "meio") == (2.5, 1.0)
    assert af.calcular_janela(8.0, 3.0, "fim") == (5.0, 1.0)
    assert af.calcular_janela(8.0, 3.0, "livre", 9) == (5.0, 1.0)  # nunca passa do fim do vídeo
    assert af.calcular_janela(8.0, 10.0) == (0.0, 1.25)  # cena maior: mais lento
    assert af.calcular_janela(8.0, 30.0)[1] == af.VEL_MAX


def test_cortar_de_verdade(tmp_path):
    an = {"id": "a1", "video": _video(str(tmp_path / "v.mp4")), "duracao_video": 8.0, "janela": "fim"}
    c = af.cortar(an, 3.0, str(tmp_path / "animar"))
    assert abs(af.duracao(c) - 3.0) < 0.15 and an["inicio_corte"] == 5.0
    an["janela"] = "meio"
    c2 = af.cortar(an, 3.0, str(tmp_path / "animar"))
    assert c2 != c and not os.path.exists(c) and an["inicio_corte"] == 2.5
    c3 = af.cortar(an, 10.0, str(tmp_path / "animar"))
    assert abs(af.duracao(c3) - 10.0) < 0.3 and an["velocidade"] == 1.25


def test_prompt_sem_ia_usa_o_prompt_da_imagem():
    seg = {"provider": "runpod", "query": "A lonely lighthouse on a cliff at dusk, stormy sea, photorealistic"}
    p = af.prompt_regra(seg, "o farol ficou sozinho")
    assert "lighthouse" in p and "camera" in p and "no text" in p
    assert af.prompt_da_imagem({"provider": "pexels", "query": "lighthouse"}) == ""


# ------------------------------------------------------------------ Flow em massa: vídeo com frame de Início
def test_lote_guarda_o_frame_e_nao_converte_em_foto(tmp_path, monkeypatch):
    import app  # noqa: F401 — põe o toolkit (googleflow) no caminho
    import flow_lote as fl
    monkeypatch.setattr(fl, "pasta", lambda: str(tmp_path))
    lote = fl.Lote()
    frame = _png(str(tmp_path / "f.png"))
    j1, j2 = lote.adicionar([{"prompt": "anima", "tipo": "video", "inicio_arquivo": frame},
                             {"prompt": "um vídeo comum", "tipo": "video"}])
    assert j1["inicio_arquivo"] == os.path.abspath(frame) and j1["origem"] == "animar" and "inicio_arquivo" not in j2
    monkeypatch.setattr(fl, "reescrever_para_foto", lambda p, log: {"prompt": "foto " + p, "por": "regra"})
    lote._converter_videos()
    assert j2["tipo"] == "imagem" and j1["tipo"] == "video"  # só o vídeo comum vira foto
    lote._converter_videos()  # sobrou só a animação: não mexe
    assert j1["tipo"] == "video" and j1["estado"] == "pendente"


# ------------------------------------------------------------------ no editor (Flow simulado)
class LoteFalso:
    def __init__(self):
        self.trava = threading.RLock()
        self.fila, self.rodando, self.fim_msg, self.status_conta, self.iniciou = [], False, None, {}, 0

    def adicionar(self, itens, proporcao="16:9", **kw):
        novos = []
        for k, it in enumerate(itens):
            j = {"id": f"fj{len(self.fila) + 1}", "prompt": it["prompt"], "tipo": it["tipo"], "estado": "pendente",
                 "inicio_arquivo": it.get("inicio_arquivo"), "proporcao": proporcao, "resultados": [], "criado": len(self.fila)}
            self.fila.append(j)
            novos.append(j)
        return novos

    def iniciar(self):
        self.rodando = True
        self.iniciou += 1

    def remover(self, jid):
        self.fila = [x for x in self.fila if x["id"] != jid]


@pytest.fixture()
def editor(tmp_path, monkeypatch):
    import app as A
    import flow_estudio as FE
    import flow_lote
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    falso = LoteFalso()
    monkeypatch.setattr(flow_lote, "lote", lambda: falso)
    gal = tmp_path / "galeria"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    monkeypatch.setattr(af, "INTERVALO_SYNC", 0.05)
    jid = "anim-teste"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    foto = _png(str(tmp_path / "foto.png"))
    A._JOBS[jid] = {
        "job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "original_filename": "n.wav", "orientation": "9:16",
        "pending_segments": [
            {"start": 0.0, "end": 3.0, "provider": "bing", "query": "farol", "media_type": "image",
             "override_source": {"source": "local_file", "value": foto, "kind": "image", "zoom_direction": "in"}},
            {"start": 3.0, "end": 6.0, "provider": "pexels", "query": "city", "media_type": "video", "override_source": None},
            {"start": 6.0, "end": 9.0, "provider": "runpod", "query": "A red supergiant collapsing, cinematic", "media_type": "image",
             "override_source": None},
        ],
        "segment_previews": [None, None, {"index": 2, "ok": True, "thumbnail_path": foto, "thumbnail_url": f"/job/{jid}/thumbnail/2"}],
        "cutaway_suggestions": [], "overlays": [],
    }
    c = A.app.test_client()
    yield A, c, jid, falso, gal, foto
    A._JOBS.pop(jid, None)
    af._VIGIA["jobs"].discard(jid)


def _pronto(falso, gal, jid_flow, dur=8.0):
    j = next(x for x in falso.fila if x["id"] == jid_flow)
    _video(str(gal / f"{jid_flow}.mp4"), dur)
    j.update(estado="ok", resultados=[{"id": "g1", "arquivo": f"{jid_flow}.mp4", "tipo": "video"}])


def test_animar_do_comeco_ao_fim(editor):
    A, c, jid, falso, gal, foto = editor
    d = c.get(f"/job/{jid}/animar/estado").get_json()
    assert d["animaveis"] == [0, 2] and not d["itens"]  # a cena de vídeo não é animável
    r = c.post(f"/job/{jid}/animar/enviar", json={"indices": [0, 1, 2], "prompts": {"2": "the star swells and explodes slowly"}})
    d = r.get_json()
    assert r.status_code == 200 and d["enviadas"] == 2 and any("é vídeo" in e for e in d["erros"])
    assert falso.iniciou == 1 and falso.fila[0]["proporcao"] == "9:16"
    assert falso.fila[0]["inicio_arquivo"] == foto and falso.fila[1]["prompt"] == "the star swells and explodes slowly"
    segs = A._JOBS[jid]["pending_segments"]
    assert segs[0]["animacao"]["estado"] == "fila" and segs[0]["animacao"]["prompt_por"] == "regra"
    assert "farol" in segs[0]["animacao"]["prompt"]
    # o Flow terminou a 1ª
    _pronto(falso, gal, segs[0]["animacao"]["flow_job"])
    d = c.get(f"/job/{jid}/animar/estado").get_json()
    it = next(x for x in d["itens"] if x["i"] == 0)
    assert it["animacao"]["estado"] == "pronto" and it["animacao"]["em_uso"] and it["media_type"] == "video"
    assert it["override_source"]["kind"] == "video" and abs(af.duracao(it["override_source"]["value"]) - 3.0) < 0.15
    assert d["esperando"]  # a 2ª ainda na fila
    # ⏭ fim do vídeo
    r = c.post(f"/job/{jid}/animar/0/janela", json={"janela": "fim", "id": it["animacao"]["id"]})
    assert r.get_json()["animacao"]["inicio_corte"] == 5.0
    # 🖼 voltar pra imagem e 🎬 de novo
    r = c.post(f"/job/{jid}/animar/0/usar", json={"modo": "imagem"}).get_json()
    assert r["override_source"]["value"] == foto and r["override_source"]["zoom_direction"] == "in" and r["media_type"] == "image"
    assert not r["animacao"]["em_uso"]
    r = c.post(f"/job/{jid}/animar/0/usar", json={"modo": "video"}).get_json()
    assert r["animacao"]["em_uso"] and r["media_type"] == "video"
    assert c.get(f"/job/{jid}/animar/0/video?qual=completo").status_code == 200
    assert c.get(f"/job/{jid}/animar/0/video?qual=frame").status_code == 200
    # a 2ª (cena de IA sem arquivo escolhido) volta pra prévia do pod
    _pronto(falso, gal, segs[2]["animacao"]["flow_job"], dur=2.0)  # vídeo menor que a cena: fica mais lento
    d = c.get(f"/job/{jid}/animar/estado").get_json()
    it2 = next(x for x in d["itens"] if x["i"] == 2)
    assert it2["animacao"]["velocidade"] == 1.5 and not d["esperando"]
    r = c.post(f"/job/{jid}/animar/2/usar", json={"modo": "imagem"}).get_json()
    assert r["override_source"] is None and r["media_type"] == "image"


def test_erro_do_flow_e_tirar_da_fila(editor):
    A, c, jid, falso, gal, foto = editor
    c.post(f"/job/{jid}/animar/enviar", json={"indices": [0, 2]})
    segs = A._JOBS[jid]["pending_segments"]
    j0 = next(x for x in falso.fila if x["id"] == segs[0]["animacao"]["flow_job"])
    j0.update(estado="erro", erro="o Flow recusou: pessoa famosa")
    falso.rodando = False
    falso.fim_msg = "💳 Parei: sem crédito de vídeo"
    d = c.get(f"/job/{jid}/animar/estado").get_json()
    by = {x["i"]: x["animacao"] for x in d["itens"]}
    assert by[0]["estado"] == "erro" and "recusou" in by[0]["erro"]
    assert by[2]["estado"] == "parado" and "sem crédito" in by[2]["msg"]
    assert c.post(f"/job/{jid}/animar/continuar").status_code == 200 and falso.rodando
    r = c.post(f"/job/{jid}/animar/2/cancelar", json={}).get_json()
    assert r["ok"] and "animacao" not in A._JOBS[jid]["pending_segments"][2] and len(falso.fila) == 1


def test_salvar_no_estudio_mantem_a_animacao(editor):
    A, c, jid, falso, gal, foto = editor
    c.post(f"/job/{jid}/animar/enviar", json={"indices": [0]})
    seg0 = A._JOBS[jid]["pending_segments"][0]
    aid = seg0["animacao"]["id"]
    _pronto(falso, gal, seg0["animacao"]["flow_job"])
    c.get(f"/job/{jid}/animar/estado")
    corte = A._JOBS[jid]["pending_segments"][0]["override_source"]["value"]
    # a página não sabia do vídeo novo e salva com a imagem antiga no trecho 0
    form = {"acao": "salvar"}
    for k, s in enumerate(A._JOBS[jid]["pending_segments"]):
        p = f"seg_{k}_"
        form.update({p + "start": s["start"], p + "end": s["end"], p + "query": s["query"], p + "provider": s["provider"],
                     p + "animacao_id": aid if k == 0 else "", p + "source_mode": "upload" if k == 0 else "auto",
                     p + "media_type": s["media_type"] if k else "image"})
    form["seg_0_local_value"] = foto
    r = c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200
    s0 = A._JOBS[jid]["pending_segments"][0]
    assert s0["animacao"]["id"] == aid and s0["override_source"]["value"] == corte and s0["media_type"] == "video"


def test_sugerir_sem_ia_poe_a_cena_de_ia_primeiro(editor):
    A, c, jid, falso, gal, foto = editor
    d = c.post(f"/job/{jid}/animar/sugerir").get_json()
    assert [x["i"] for x in d["sugestoes"]] == [2, 0] and all(x["por"] == "regra" for x in d["sugestoes"])


def test_prompt_com_ia_olha_a_imagem(editor, monkeypatch):
    A, c, jid, falso, gal, foto = editor
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "animar")
    visto = {}

    def chamar(recurso, system, conteudo, schema=None, **kw):
        visto["conteudo"] = conteudo
        return {"prompt": "The supergiant star slowly swells, glowing plasma ripples outward while the camera gently pushes in, "
                          "same composition and colors", "resumo_pt": "a estrela incha"}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    d = c.post(f"/job/{jid}/animar/prompt/2").get_json()
    assert d["por"] == "ia" and "supergiant" in d["prompt"]
    textos = " ".join(x.get("text", "") for x in visto["conteudo"] if isinstance(x, dict))
    assert "PROMPT THAT CREATED THIS IMAGE" in textos and "red supergiant" in textos
    assert any(x.get("type") == "image" for x in visto["conteudo"] if isinstance(x, dict))


def test_estudio_renderiza_e_o_js_compila(editor, tmp_path):
    A, c, jid, *_ = editor
    r = c.get(f"/job/{jid}/edit-segments?modo=estudio")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-tab="animar"' in html and 'id="tab-animar"' in html
    import shutil
    if not shutil.which("node"):
        pytest.skip("sem node")
    scripts = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)
    for k, sc in enumerate(scripts):
        f = tmp_path / f"s{k}.js"
        f.write_text(sc, encoding="utf-8")
        p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-800:]


def test_dividir_trecho_animado_a_2a_parte_volta_pra_imagem(editor):
    A, c, jid, falso, gal, foto = editor
    c.post(f"/job/{jid}/animar/enviar", json={"indices": [0]})
    s0 = A._JOBS[jid]["pending_segments"][0]
    aid = s0["animacao"]["id"]
    _pronto(falso, gal, s0["animacao"]["flow_job"])
    c.get(f"/job/{jid}/animar/estado")
    corte = A._JOBS[jid]["pending_segments"][0]["override_source"]["value"]
    # a página dividiu o trecho 0 em dois (0–1,5 e 1,5–3), os dois com o vídeo e o mesmo id
    partes = [(0.0, 1.5), (1.5, 3.0), (3.0, 6.0), (6.0, 9.0)]
    form = {"acao": "salvar"}
    for k, (a, b) in enumerate(partes):
        p = f"seg_{k}_"
        orig = A._JOBS[jid]["pending_segments"][max(0, k - 1)]
        form.update({p + "start": a, p + "end": b, p + "query": orig["query"], p + "provider": orig["provider"],
                     p + "animacao_id": aid if k < 2 else "", p + "source_mode": "upload" if k < 2 else "auto",
                     p + "media_type": "video" if k < 2 else orig["media_type"]})
        if k < 2:
            form[p + "local_value"] = corte
    r = c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200
    segs = A._JOBS[jid]["pending_segments"]
    assert segs[0]["animacao"]["id"] == aid and "animacao" not in segs[1]
    assert segs[1]["override_source"]["value"] == foto and segs[1]["media_type"] == "image"
    # a 1ª parte ficou menor: o vídeo é cortado de novo com 1,5 s
    c.get(f"/job/{jid}/animar/estado")
    novo = A._JOBS[jid]["pending_segments"][0]["override_source"]["value"]
    assert novo != corte and abs(af.duracao(novo) - 1.5) < 0.15
