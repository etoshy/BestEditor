"""v84_181: 🎨 o pacote do canal manda na 🏭 Produção no pod (% , estética e personagens) e 🔗 o lote continua num pod
novo (VPS nova): sem narração pede de novo; com narração manda só as imagens que faltam no PC."""
import io
import json
import os
import zipfile

import pytest

import canal_pod
import marca_visual as mv
from test_v84_producao_pod import _esperar, pod_falso  # noqa: F401 — fixture

AQUI = os.path.dirname(os.path.abspath(__file__))
PACOTES = os.path.join(os.path.dirname(AQUI), "..")


def _zip_da_pasta(pasta: str) -> bytes:
    """Os pacotes de canal de verdade (Dinge erklären, ASTRANEBEL) — da pasta ao lado do projeto, se existir."""
    buf = io.BytesIO()
    raiz = os.path.dirname(pasta)
    with zipfile.ZipFile(buf, "w") as z:
        for d, _ds, fs in os.walk(pasta):
            for f in fs:
                cam = os.path.join(d, f)
                z.write(cam, os.path.relpath(cam, raiz))
    return buf.getvalue()


def _achar(slug: str):
    for cand in (os.path.join(PACOTES, "dinge", slug), os.path.join(PACOTES, "astra", slug),
                 os.path.join(AQUI, "marcas", slug)):
        if os.path.isfile(os.path.join(cand, "brand_guide.json")):
            return cand
    return None


@pytest.fixture()
def canais(tmp_path):
    import dossies as ds
    antes = set(ds.MODELOS)
    out = {}
    for slug in ("dinge_erklaeren", "astranebel"):
        pasta = _achar(slug)
        if not pasta:
            pytest.skip(f"pacote {slug} não está aqui")
        out[slug] = mv.carregar(str(tmp_path), mv.importar_zip(str(tmp_path), _zip_da_pasta(pasta)))
    yield str(tmp_path), out
    for k in set(ds.MODELOS) - antes:
        ds.MODELOS.pop(k, None)


# ------------------------------------------------------------------ a regra dos personagens
def test_config_do_pacote(canais):
    _b, c = canais
    d, a = canal_pod.config(c["dinge_erklaeren"]), canal_pod.config(c["astranebel"])
    assert d["pct"] == 100 and a["pct"] == 100
    assert d["estilo_fotos"] == "foto" and a["estilo_fotos"] == "ilustracao"
    assert canal_pod.tem_mascote(c["dinge_erklaeren"]) and not canal_pod.tem_mascote(c["astranebel"])
    assert {p["slug"] for p in canal_pod.personagens(c["astranebel"])} >= {"mira", "vanta"}
    assert "arquivo" not in canal_pod.tipos_imagem(c["astranebel"], a)  # canal desenhado: sem foto de arquivo


def test_regra_mascote_dinge(canais):
    _b, c = canais
    m = c["dinge_erklaeren"]
    g = canal_pod.aplicar_regra(m, {"pessoa": "generica", "mascote": "", "acao_en": "examining an old map with a magnifying glass"})
    assert g["mascote"] == "investigando" and g["personagens"] == []
    assert canal_pod.aplicar_regra(m, {"pessoa": "nenhuma", "mascote": "curioso"})["mascote"] == ""
    assert canal_pod.aplicar_regra(m, {"pessoa": "real", "mascote": "curioso"})["mascote"] == ""
    assert canal_pod.aplicar_regra(m, {"pessoa": "generica", "pessoas": [{"nome": "X", "idade": 40}]})["mascote"] == ""
    # prompt: estética + trava do mascote + as referências dele (klein); sem pessoa = Z-Image, sem mascote, mesma estética
    pr, refs = canal_pod.prompt_e_refs(m, dict(g, assunto_en="a muddy 19th-century potato field in Brandenburg"))
    estilo = m["guia"]["generation_system"]["style_lock_en"][:40]
    assert estilo in pr and "PROPORTION LOCK" in pr and "potato field" in pr
    assert refs and any("mascote_proporcoes" in n for n, _c in refs) and len(refs) <= 4
    assert all(os.path.isfile(c_) for _n, c_ in refs)
    pr2, refs2 = canal_pod.prompt_e_refs(m, {"assunto_en": "an empty village road at dusk", "pessoa": "nenhuma"})
    assert estilo in pr2 and "no mascot in this frame" in pr2 and refs2 == []
    assert "photorealistic documentary" not in pr2


def test_regra_personagens_astranebel(canais):
    _b, c = canais
    m = c["astranebel"]
    r = canal_pod.aplicar_regra
    assert [x["slug"] for x in r(m, {"pessoa": "nenhuma", "fala_de": "vanta"})["personagens"]] == ["vanta"]  # falando
    assert [x["slug"] for x in r(m, {"pessoa": "generica", "fala_de": ""})["personagens"]] == ["mira"]  # anônimo → personagem
    assert r(m, {"pessoa": "nenhuma", "fala_de": "", "personagens": ["mira"]})["personagens"] == []  # sem gente, sem fala
    assert r(m, {"pessoa": "real", "fala_de": "mira"})["personagens"] == []  # pessoa real citada: só ela
    d = r(m, {"pessoa": "generica", "fala_de": "mira", "personagens": ["vanta"], "acao_en": "pointing at the dying star"})
    assert [x["slug"] for x in d["personagens"]] == ["mira", "vanta"]
    pr, refs = canal_pod.prompt_e_refs(m, dict(d, assunto_en="a red supergiant collapsing"))
    assert "ASTRANEBEL visual style" in pr and "MIRA" in pr and "VANTA" in pr
    papeis = [n for n, _c in refs]
    assert any(n.startswith("personagem_mira") for n in papeis) and any(n.startswith("personagem_vanta") for n in papeis)


# ------------------------------------------------------------------ no lote
def _ia_falsa(monkeypatch, cenas_ia):
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "producao_pod")
    vistos = []

    def chamar(recurso, system, conteudo, schema=None, **kw):
        vistos.append(system)
        ns = [int(x.split("]")[0].strip("[")) for x in conteudo.split("\n") if x.startswith("[")]
        return {"cenas": [dict(cenas_ia(n), n=n) for n in ns]}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    return vistos


def test_lote_do_canal_forca_100_e_estetica(pod_falso, canais, monkeypatch):
    base, c = canais
    pp, est = pod_falso["pp"], pod_falso["estado"]
    monkeypatch.setattr(pp, "_BASE", base)
    enviados = []
    import pod_studio

    def com_refs(itens, **kw):
        enviados.append(itens)
        return pod_studio.enviar_imagens([{k: v for k, v in i.items() if k != "referencias"} for i in itens], **kw), False
    monkeypatch.setattr(pod_studio, "enviar_imagens_com_refs", com_refs)
    sis = _ia_falsa(monkeypatch, lambda n: {"visual": "v", "busca": "b", "dificil": 0, "assunto_en": f"scene {n} subject",
                                            "pessoa": "generica" if n == 1 else "nenhuma", "mascote": "curioso",
                                            "acao_en": "looking up in wonder"})
    lote = pp.criar([{"origem": "texto", "titulo": "Brandenburg", "texto": "Brandenburg ist leer. Niemand wohnt dort mehr. Warum?",
                      "idioma": "de"}], {"intervalo": 5, "pct": 30, "canal": "dinge_erklaeren"}, pod_url="https://a-8000.proxy.runpod.net")
    l = _esperar(pp, lote["id"])
    it = l["itens"][0]
    assert it["estado"] == "pronto" and it["canal"] == "dinge_erklaeren"
    assert it["cenas"]["pct"] == 100 and it["cenas"]["pendentes"] == 0  # o pacote manda: 100%, não os 30 do lote
    itens = enviados[0]
    estilo = c["dinge_erklaeren"]["guia"]["generation_system"]["style_lock_en"][:40]
    assert all(estilo in i["prompt"] for i in itens)
    assert itens[0].get("referencias") and "PROPORTION LOCK" in itens[0]["prompt"]  # cena 1: pessoa genérica → mascote
    assert all(not i.get("referencias") and "no mascot in this frame" in i["prompt"] for i in itens[1:])
    assert "REGRA DO CANAL" in sis[0] and "Dinge" in sis[0]
    seg = pod_falso["criados"][0]["resposta"]["segments"][0]
    assert seg["provider"] == "runpod" and seg["personagens"] == ["mascote:curioso"]


def test_lote_sem_canal_continua_igual(pod_falso, canais, monkeypatch):
    base, _c = canais
    pp = pod_falso["pp"]
    monkeypatch.setattr(pp, "_BASE", base)
    lote = pp.criar([{"origem": "texto", "titulo": "A", "texto": "Era uma vez um navio. Ninguém a bordo. O mar calmo."}],
                    {"intervalo": 5, "pct": 30})
    l = _esperar(pp, lote["id"])
    assert l["itens"][0]["estado"] == "pronto" and not l["itens"][0].get("canal")


# ------------------------------------------------------------------ 🔗 pod novo
def test_pod_novo_sem_narracao_pede_de_novo(pod_falso, monkeypatch):
    pp, est = pod_falso["pp"], pod_falso["estado"]
    import pod_studio
    import site_config
    salvos = []
    monkeypatch.setattr(site_config, "save_site_config", lambda v, path=None: salvos.append(v))
    real = pod_studio.job

    def morto(jid, cfg=None):
        if jid.startswith("voz"):
            raise pod_studio.PodErro("Read timed out.")
        return real(jid, cfg)
    monkeypatch.setattr(pod_studio, "job", morto)
    lote = pp.criar([{"origem": "texto", "titulo": "Frauke", "texto": "Uma frase qualquer com palavras suficientes aqui."}], {},
                    pod_url="https://velho-8000.proxy.runpod.net")
    l = _esperar(pp, lote["id"], 20)
    assert l["itens"][0]["estado"] == "erro"
    monkeypatch.setattr(pod_studio, "job", real)
    vozes_antes = sum(1 for t, _d in est["pedidos"] if t == "voz")
    pp.tentar_de_novo(lote["id"], l["itens"][0]["id"], pod_url="https://novo-8000.proxy.runpod.net/")
    l = _esperar(pp, lote["id"])
    assert l["itens"][0]["estado"] == "pronto" and l["pod_url"] == "https://novo-8000.proxy.runpod.net"
    assert sum(1 for t, _d in est["pedidos"] if t == "voz") == vozes_antes + 1  # narrou de novo, no pod novo
    assert salvos and salvos[-1]["runpod_pod_url"] == "https://novo-8000.proxy.runpod.net"


def test_pod_novo_manda_so_as_imagens_que_faltam(pod_falso, monkeypatch):
    pp, est = pod_falso["pp"], pod_falso["estado"]
    import pod_studio
    import site_config
    monkeypatch.setattr(site_config, "save_site_config", lambda v, path=None: None)
    texto = " ".join(f"Frase numero {k} do roteiro longo." for k in range(30))
    lote = pp.criar([{"origem": "texto", "titulo": "Supernova", "texto": texto}], {"intervalo": 3, "pct": 100})
    l = _esperar(pp, lote["id"])
    it = l["itens"][0]
    pasta = os.path.join(pp.pasta_item(lote["id"], it["id"]), "imagens")
    feitas = sorted(os.listdir(pasta))
    assert len(feitas) >= 4
    for n in feitas[: len(feitas) // 2]:  # o pod morreu antes de mandar metade
        os.remove(os.path.join(pasta, n))
    falta = pp.faltam_no_pc(lote["id"], it["id"])
    assert falta == len(feitas) // 2
    n_img = sum(1 for t, _d in est["pedidos"] if t == "img")
    r = pp.refazer_imagens(lote["id"], it["id"], pod_url="https://vps2-8000.proxy.runpod.net")
    assert r["reenviadas"] == falta
    l = _esperar(pp, lote["id"])
    imgs = [d for t, d in est["pedidos"] if t == "img"]
    assert len(imgs) == n_img + 1 and len(imgs[-1]["itens"]) == falta  # só as que faltavam
    assert pp.faltam_no_pc(lote["id"], it["id"]) == 0 and l["itens"][0]["estado"] == "pronto"
    assert sum(1 for t, _d in est["pedidos"] if t == "voz") == 1  # não narrou de novo


def test_tentar_de_novo_com_pod_novo_reenvia_imagens(pod_falso, monkeypatch):
    pp, est = pod_falso["pp"], pod_falso["estado"]
    import pod_studio
    import site_config
    monkeypatch.setattr(site_config, "save_site_config", lambda v, path=None: None)
    real = pod_studio.job
    monkeypatch.setattr(pod_studio, "job", lambda jid, cfg=None: (_ for _ in ()).throw(pod_studio.PodErro("Read timed out."))
                        if jid.startswith("img") else real(jid, cfg))
    lote = pp.criar([{"origem": "texto", "titulo": "B", "texto": "Uma frase. Outra frase. Mais uma frase aqui pra cortar."}],
                    {"intervalo": 3, "pct": 100})
    l = _esperar(pp, lote["id"], 20)
    it = l["itens"][0]
    assert it["estado"] == "erro" and it["pod_img"]
    monkeypatch.setattr(pod_studio, "job", real)
    pp.tentar_de_novo(lote["id"], it["id"], pod_url="https://vps3-8000.proxy.runpod.net")
    l = _esperar(pp, lote["id"])
    assert l["itens"][0]["estado"] == "pronto" and pp.faltam_no_pc(lote["id"], it["id"]) == 0
    assert sum(1 for t, _d in est["pedidos"] if t == "voz") == 1


def test_aviso_de_job_parado(monkeypatch):
    import producao_pod as pp
    monkeypatch.setattr(pp, "PARADO_S", 0)
    it = {"id": "x1", "estado": "imagens", "pod_img": "img-9"}
    st = {"status": "na_fila", "posicao_fila": 1, "progresso": {"feito": 0, "total": 8}}
    assert pp._vigiar_parado(it, st) == ""
    assert "parado há" in pp._vigiar_parado(it, st) and "link novo" in pp._vigiar_parado(it, st)


def test_rotas_pod_url_e_zip_do_canal(canais):
    import app as a
    c = a.app.test_client()
    r = c.post("/producao-pod/abcdef1234/pod-url", json={"pod_url": "nao é link"})
    assert r.status_code == 400
    r = c.get("/marca/modelo-vazio.zip")
    z = zipfile.ZipFile(io.BytesIO(r.data))
    pac = json.loads(z.read("meu_canal/pacote.json"))
    assert pac["producao_pod"]["pct"] == 100
