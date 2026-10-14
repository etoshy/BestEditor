"""v84_92 — 🎬 Revisão do diretor + 🖼️ formato (mídia em pé num vídeo deitado).

O diretor passa pela timeline: problemas automáticos (sem prévia, formato, desenho, nota baixa, repetida) e, com a IA,
olha cada miniatura com a fala de antes/depois e decide: busca nova (no buscador com mais chance), gráfico nativo,
cartão, ou "procurar na mão". O Estúdio aplica, confere as buscas e marca 🔎 o que não achou."""
import json
import os

import pytest

import estilo_imagem as ei
import revisao_diretor as rd
import video_assembler as va
from prompt_builder import VideoSegment


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _segs(n=5):
    return [{"start": 4.0 * k, "end": 4.0 * k + 4, "provider": "pexels", "query": f"q{k}", "media_type": "video",
             "alternativas": [f"alt{k}"]} for k in range(n)]


# ------------------------------------------------------------------ 🖼️ formato
def test_formato_pela_miniatura():
    from PIL import Image
    assert ei.formato(Image.new("RGB", (1920, 1080))) == "horizontal"
    assert ei.formato(Image.new("RGB", (1080, 1920))) == "vertical"
    assert ei.formato(Image.new("RGB", (1000, 1000))) == "quadrada"
    assert ei.formato_errado("vertical", "16:9") and ei.formato_errado("horizontal", "9:16")
    assert not ei.formato_errado("quadrada", "16:9") and not ei.formato_errado("", "16:9") and not ei.formato_errado("vertical", "1:1")


def test_ordena_pelo_formato_mesmo_sem_o_filtro_de_estilo():
    cands = [{"id": "v", "thumbnail": "t/v"}, {"id": "h", "thumbnail": "t/h"}]
    fmt = lambda u: "vertical" if u == "t/v" else "horizontal"  # noqa: E731
    out = ei.ordenar_candidatos(cands, {"estilo_imagens": "qualquer", "orientation": "16:9"},
                                classificar_fn=lambda u: "", formato_fn=fmt)
    assert [c["id"] for c in out] == ["h", "v"] and out[1]["formato_errado"]
    out = ei.ordenar_candidatos(cands, {"estilo_imagens": "qualquer", "orientation": "9:16"},
                                classificar_fn=lambda u: "", formato_fn=fmt)
    assert [c["id"] for c in out] == ["v", "h"]
    assert ei.ordenar_candidatos(cands, {"estilo_imagens": "qualquer", "orientation": "1:1"}) == cands


def test_busca_da_previa_pede_o_formato_ao_banco():
    pedidos = {}

    class Cli:
        def search_all(self, query, max_pages=1, **kw):
            pedidos.update(kw)
            return []

    class Fab:
        cfg = {}

        def get_client(self, p):
            return Cli()

        def close_all(self):
            pass
    va.search_candidates("pexels", "city", site_cfg={"orientation": "16:9"}, client_factory=Fab())
    assert pedidos.get("orientation") == "landscape"
    pedidos.clear()
    va.search_candidates("pixabay", "city", site_cfg={"orientation": "9:16"}, client_factory=Fab())
    assert pedidos.get("orientation") == "vertical"

    class CliVelho:  # cliente sem o filtro: busca sem ele, não quebra
        def search_all(self, query, max_pages=1):
            return []

    class Fab2(Fab):
        def get_client(self, p):
            return CliVelho()
    assert va.search_candidates("pexels", "city", site_cfg={"orientation": "16:9"}, client_factory=Fab2()) == []


def test_previa_pula_o_video_em_pe(monkeypatch):
    monkeypatch.setattr(va, "search_candidates", lambda p, q, max_results=1, **kw: [
        {"id": "1", "thumbnail": "t/em_pe", "url": "http://p/em_pe", "label": "phone booth"},
        {"id": "2", "thumbnail": "t/deitado", "url": "http://p/deitado", "label": "phone booth wide"}])
    monkeypatch.setattr(ei, "classificar_url", lambda u, t=6.0, baixar=None: "")
    monkeypatch.setattr(ei, "formato_url", lambda u, t=6.0, baixar=None: "vertical" if "em_pe" in u else "horizontal")
    seg = VideoSegment(start=0.0, end=4.0, provider="pexels", query="woman phone call night")
    r = va.fetch_segment_preview_lightweight(seg, site_cfg={"provider_priority": ["pexels"], "orientation": "16:9"})
    assert r["result_url"] == "http://p/deitado" and not r["label"].startswith("⚠")


# ------------------------------------------------------------------ 🎬 revisão: trechos e problemas automáticos
def test_trechos_e_problemas_automaticos():
    segs = _segs(6)
    segs[4]["override_source"] = {"source": "local_file"}  # escolhido por você: fica de fora
    segs[5]["provider"] = "youtube"
    previas = [{"thumb": "t/0", "label": "ok"}, {"thumb": "t/em_pe"}, {"thumb": "t/3d"}, {"thumb": "t/0", "label": "⚠ fraca"}, {}, {}]
    falas = ["um", "dois", "tres", "quatro", "cinco", "seis"]
    tr = rd.montar_trechos(segs, falas, previas, lambda i, s, pv: pv.get("thumb") or "")
    assert tr[1]["antes"] == "um" and tr[1]["depois"] == "tres" and tr[4]["pulado"] and tr[5]["pulado"]
    an = {"t/em_pe": {"estilo": "", "formato": "vertical"}, "t/3d": {"estilo": "recorte_fundo_branco", "formato": "horizontal"}}
    rd.problemas_automaticos(tr, "16:9", True, analisar=lambda u: an.get(u, {"estilo": "", "formato": "horizontal"}))
    assert tr[0]["flags"] == [] and tr[1]["flags"] == ["formato"] and tr[2]["flags"] == ["desenho"]
    assert set(tr[3]["flags"]) == {"nota_baixa", "repetida"} and tr[4]["flags"] == []


def test_plano_sem_ia():
    segs = _segs(3)
    segs[2]["alternativas"] = []
    tr = rd.montar_trechos(segs, ["a", "b", "c"], [{"thumb": "t/0"}, {"thumb": "t/1"}, {}], lambda i, s, pv: pv.get("thumb") or "")
    rd.problemas_automaticos(tr, "16:9", True, analisar=lambda u: {"estilo": "", "formato": "vertical" if u == "t/1" else "horizontal"})
    p = rd.plano(tr, {}, rd.disponiveis(["pexels", "pixabay"]))
    assert [(x["i"], x["acao"]) for x in p["itens"]] == [(1, "busca"), (2, "manual")]
    assert p["itens"][0]["buscas"] == ["alt1"] and p["itens"][0]["buscador"] == "pexels" and not p["com_ia"]


def test_revisao_com_ia_e_validacao():
    segs = _segs(5)
    falas = ["o golpista abriu a mesa", "ganhou 6 mil dólares numa noite, o dobro do mês anterior de 3 mil",
             "era tudo uma ilusão", "o documento do processo foi assinado", "ele foi preso em Miami"]
    tr = rd.montar_trechos(segs, falas, [{"thumb": f"t/{k}"} for k in range(5)], lambda i, s, pv: pv.get("thumb") or "")
    rd.problemas_automaticos(tr, "16:9", True, analisar=lambda u: {"estilo": "", "formato": "horizontal"})
    enviados = []

    def chamar(rec, system, conteudo, schema, **kw):
        enviados.append((rec, system, conteudo, schema))
        return {"trechos": [
            {"n": 1, "ok": True, "acao": "manter"},
            {"n": 2, "ok": False, "problema": "seta desenhada", "acao": "grafico",
             "grafico": {"tipo": "barras", "titulo": "Ganho por noite", "unidade": "US$",
                         "dados": [{"rotulo": "antes", "valor": 3000}, {"rotulo": "naquela noite", "valor": 6000}]}},
            {"n": 3, "ok": False, "problema": "genérica", "acao": "cartao", "frase": "Era tudo uma ilusão cuidadosamente montada pra enganar"},
            {"n": 4, "ok": False, "problema": "documento específico", "acao": "manual", "procurar": "o print do processo no site do tribunal"},
            {"n": 5, "ok": False, "problema": "não é Miami", "acao": "busca", "buscas": ["Miami police arrest 1990s", "Miami skyline night"],
             "buscador": "magnific", "midia": "foto"},
        ]}
    dec = rd.revisar_ia(tr, {"estilo_imagem": "real"}, rd.disponiveis(["pexels", "google"]), "16:9", ["barras", "numero"],
                        chamar=chamar, imagem=lambda u: {"type": "image", "src": u})
    rec, system, conteudo, schema = enviados[0]
    assert rec == "revisao" and "google" in system and "estilo_imagem" in system
    textos = " ".join(c.get("text", "") for c in conteudo)
    assert "antes: o golpista abriu a mesa" in textos and "TRECHO: ganhou 6 mil" in textos and "depois: era tudo" in textos
    assert sum(1 for c in conteudo if c.get("type") == "image") == 5
    p = rd.plano(tr, dec, rd.disponiveis(["pexels", "google"]), duracao=20.0, com_ia=True)
    por = {x["i"]: x for x in p["itens"]}
    assert 0 not in por  # manter e sem problema: nem aparece
    g = por[1]["grafico"]
    assert por[1]["acao"] == "grafico" and g["posicao"] == "tela_cheia" and (g["start"], g["end"]) == (4.0, 8.0) and g["origem"] == "revisao"
    assert por[2]["acao"] == "cartao" and len(por[2]["frase"].split()) <= 8
    assert por[3]["acao"] == "manual" and "tribunal" in por[3]["procurar"]
    assert por[4]["acao"] == "busca" and por[4]["buscador"] == "google" and por[4]["midia"] == "foto"  # "magnific" não está marcado
    assert p["contagem"] == {"grafico": 1, "cartao": 1, "manual": 1, "busca": 1}


def test_grafico_sem_dados_vira_cartao():
    tr = rd.montar_trechos(_segs(1), ["muito dinheiro"], [{"thumb": "t/0"}], lambda i, s, pv: pv.get("thumb") or "")
    p = rd.plano(tr, {0: {"acao": "grafico", "grafico": {"tipo": "barras", "titulo": "Dinheiro", "dados": []}, "frase": ""}},
                 rd.disponiveis(["pexels"]), com_ia=True)
    assert p["itens"][0]["acao"] == "cartao" and p["avisos"]


# ------------------------------------------------------------------ rotas
def _job(A, jid, n=4):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {
        "job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 4.0 * n, "providers": ["pexels"],
        "pending_segments": [{"start": 4.0 * k, "end": 4.0 * k + 4, "provider": "pexels", "query": f"q{k}", "media_type": "video",
                              "alternativas": [f"alt{k}"]} for k in range(n)],
        "segment_previews": [{"index": k, "ok": True, "thumbnail_url": f"https://cdn/t{k}.jpg"} for k in range(n)],
        "segments": [{"start": 0.0, "end": 4.0 * n, "text": "uma história contada em partes iguais pra testar"}],
        "word_timestamps": [{"word": w, "start": k * 1.0, "end": k * 1.0 + 0.8} for k, w in enumerate("uma história contada em partes iguais pra testar".split())],
        "orientation": "16:9",
    }
    return A._JOBS[jid]


def test_rota_da_revisao_em_segundo_plano(A, monkeypatch):
    import ia_servico
    import tarefas_bg
    _job(A, "rd-rota")
    monkeypatch.setattr(ei, "analisar_url", lambda u, t=6.0, baixar=None: {"estilo": "", "formato": "vertical" if u.endswith("t1.jpg") else "horizontal"})
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    d = A.app.test_client().post("/job/rd-rota/revisao-diretor", json={}).get_json()
    t = tarefas_bg.esperar(d["tarefa"], 20)
    assert t["status"] == "pronto", t.get("erro")
    itens = t["resultado"]["itens"]
    assert [(x["i"], x["acao"], x["flags"]) for x in itens] == [(1, "busca", ["formato"])]


def test_rota_do_fundo_cartao_e_grafico(A):
    job = _job(A, "rd-fundo")
    c = A.app.test_client()
    d = c.post("/job/rd-fundo/revisao/fundo/1", json={"tipo": "cartao", "frase": "Era tudo uma ilusão"}).get_json()
    assert d["ok"] and d["override_source"]["cartao"] and os.path.isfile(d["override_source"]["value"])
    assert d["destaque"]["texto"] and d["destaque"]["trecho"] == 1 and job["segment_previews"][1]["thumbnail_path"]
    d = c.post("/job/rd-fundo/revisao/fundo/2", json={"tipo": "grafico"}).get_json()
    assert d["ok"] and d["destaque"] is None and "gráfico" in d["preview"]["label"]
    assert not any(x.get("trecho") == 2 for x in job.get("destaques") or [])


def test_salvar_guarda_a_marca_procurar_na_mao(A):
    job = _job(A, "rd-salvar", n=2)
    cli = A.app.test_client()
    form = {"acao": "salvar"}
    for k in range(2):
        form.update({f"seg_{k}_start": str(4.0 * k), f"seg_{k}_end": str(4.0 * k + 4), f"seg_{k}_query": f"q{k}", f"seg_{k}_provider": "pexels"})
    form["seg_1_revisao"] = json.dumps({"manual": True, "procurar": "o print do processo", "motivo": "específico"})
    r = cli.post("/job/rd-salvar/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200
    assert job["pending_segments"][1]["revisao"] == {"procurar": "o print do processo", "motivo": "específico", "manual": True}
    form2 = {k: v for k, v in form.items() if not k.endswith("_revisao")}  # editor clássico: mantém
    cli.post("/job/rd-salvar/confirm-segments", data=form2, headers={"X-Requested-With": "fetch"})
    assert job["pending_segments"][1]["revisao"]["manual"]
    form["seg_1_revisao"] = ""  # ✓ Resolvido no Estúdio: tira
    cli.post("/job/rd-salvar/confirm-segments", data=form, headers={"X-Requested-With": "fetch"})
    assert "revisao" not in job["pending_segments"][1]


def test_estudio_tem_o_painel(A):
    _job(A, "rd-pagina")
    h = A.app.test_client().get("/job/rd-pagina/edit-segments?modo=estudio").get_data(as_text=True)
    assert 'id="revDiretor"' in h and 'id="rdRodar"' in h and "revisao-diretor" in h and "rev-bdg" in h
    import ia_servico
    assert "revisao" in ia_servico.RECURSOS
