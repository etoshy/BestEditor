"""
v84 — buscas melhores pras cenas.

Reclamação: "quando envio o roteiro pra uma IA gerar as pesquisas pras cenas,
as IAs entregam um negócio ruim". O prompt dizia só "termo em inglês, visual,
2 a 5 palavras"; agora tem uma seção inteira de como escrever a busca, a IA
escreve a imagem antes ("visual"), manda buscas de reserva ("alternativas") e
uma busca com a cara do vídeo ("busca_reserva") — que a montagem usa no lugar
de "nature background". E o Estúdio ganhou a revisão das buscas com IA.
"""
import json
import os

import pytest

import prompt_builder as pb
import video_assembler as va

_FALA = [
    {"start": 0.0, "end": 5.0, "text": "Ninguém sabe o que aconteceu naquela noite."},
    {"start": 5.0, "end": 10.0, "text": "Nove estudantes subiram a montanha e nunca voltaram."},
]


# ------------------------------------------------------------------ prompt principal
class TestPromptPrincipal:
    def test_tem_a_secao_de_como_escrever_a_busca(self):
        p = pb.build_prompt(_FALA, providers=["pexels", "pixabay"])
        assert "## Como escrever a busca de cada trecho" in p
        for trecho in ("CONCRETO, nunca abstrato", "UMA coisa por busca", "IDENTIDADE VISUAL", "VARIE O PLANO",
                       "busca ruim → busca boa", "\"visual\"", "\"alternativas\"", "\"busca_reserva\""):
            assert trecho in p, trecho
        # a seção vem depois das regras e antes do formato da resposta
        assert p.index("Regras:") < p.index("## Como escrever") < p.index("## Formato de resposta")

    def test_exemplo_do_json_mostra_os_campos_novos_e_e_json_de_verdade(self):
        p = pb.build_prompt(_FALA, providers=["pexels", "pixabay"])
        bloco = p[p.index("{\n  \"busca_reserva\""):]
        bloco = bloco[: bloco.index("\n}\n") + 2]
        data = json.loads(bloco)  # o exemplo tem que ser JSON válido (antes a linha da foto saía com {{ }})
        assert data["busca_reserva"]
        assert all(s.get("visual") and s.get("alternativas") for s in data["segments"])
        assert data["segments"][2]["media_type"] == "image"

    def test_so_cita_bancos_selecionados(self):
        p = pb.build_prompt(_FALA, providers=["pexels", "pixabay"])
        assert "mixkit" not in p and "magnific" not in p and "animepexels" not in p
        assert 'Os bancos de estoque ("pexels", "pixabay")' in p

    def test_aponta_os_provedores_de_nome_proprio_quando_existem(self):
        com = pb.build_prompt(_FALA, providers=["pexels", "wikipedia", "bing"])
        sem = pb.build_prompt(_FALA, providers=["pexels"])
        assert 'use "wikipedia" / "bing"' in com
        assert "Quando o nome próprio PRECISA aparecer" not in sem

    def test_mixkit_continua_com_categoria(self):
        p = pb.build_prompt(_FALA, providers=["pexels", "mixkit"])
        assert "continuam sendo CATEGORIAS do site" in p

    def test_sem_banco_de_estoque_nao_tem_a_secao(self):
        p = pb.build_prompt(_FALA, providers=["flow", "bing"])
        assert "## Como escrever a busca" not in p
        assert "alternativas" in p  # ainda pede reservas (servem pros buscadores)

    def test_video_longo_pede_resposta_enxuta(self):
        longo = [{"start": float(i), "end": float(i + 1), "text": "x"} for i in range(600)]
        assert "muitos trechos" in pb.build_prompt(longo, interval_seconds=4, providers=["pexels"])
        assert "muitos trechos" not in pb.build_prompt(_FALA, interval_seconds=4, providers=["pexels"])

    def test_prompt_de_anime_tambem_pede_visual_e_reservas(self):
        p = pb.build_animepexels_prompt(_FALA)
        assert '"alternativas"' in p and '"visual"' in p and "CENA CONCRETA" in p


# ------------------------------------------------------------------ leitura da resposta
class TestLeitura:
    def _resp(self, segs, **raiz):
        return json.dumps(dict(raiz, segments=segs))

    def test_campos_novos_sao_lidos_e_limpos(self):
        r = pb.parse_ai_response(self._resp([
            {"start": 0, "end": 5, "visual": "estrada vazia", "provider": "pexels",
             "query": "\"empty dark road 4K stock footage\"", "alternativas": ["Empty Dark Road", "dark road", "dark road", "road", "night", "x"]},
            {"start": 5, "end": 10, "provider": "flow", "media_type": "image", "query": "montanha nevada à noite", "alternativas": ["a"]},
        ], busca_reserva="snowy mountain night HD"), valid_providers=["pexels", "flow"], total_duration=10)
        a, b = r.segments
        assert a.query == "empty dark road"
        assert a.alternativas == ["dark road", "road", "night"]  # sem a igual à principal, sem repetidas, no máximo 3
        assert a.visual == "estrada vazia"
        assert a.busca_reserva == r.busca_reserva == "snowy mountain night"
        assert b.alternativas is None and b.busca_reserva is None  # flow gera, não busca
        assert b.query == "montanha nevada à noite"  # descrição do flow não é "limpa"
        d = a.to_dict()
        assert d["alternativas"] == ["dark road", "road", "night"] and d["visual"] == "estrada vazia"

    def test_alternativas_em_texto_tambem_valem(self):
        r = pb.parse_ai_response(self._resp([{"start": 0, "end": 10, "provider": "pexels", "query": "old man reading",
                                              "alternativas": "man reading | old book"}]), total_duration=10)
        assert r.segments[0].alternativas == ["man reading", "old book"]

    def test_resposta_antiga_continua_igual(self):
        r = pb.parse_ai_response(json.dumps([{"start": 0, "end": 10, "provider": "pexels", "query": "sunrise"}]), total_duration=10)
        d = r.segments[0].to_dict()
        assert "alternativas" not in d and "visual" not in d and "busca_reserva" not in d

    def test_limpar_query_nao_estraga_termo_bom(self):
        assert pb.limpar_query("stock market crash red screen") == "stock market crash red screen"
        assert pb.limpar_query("video game controller") == "video game controller"
        assert pb.limpar_query("  b-roll city skyline 8K. ") == "city skyline"
        assert pb.limpar_query("4k hd") == ""


# ------------------------------------------------------------------ montagem usa as reservas
class TestReservasNaMontagem:
    def _seg(self, **kw):
        base = dict(start=0, end=4, provider="pexels", query="tired man on laptop at night")
        base.update(kw)
        return pb.VideoSegment(**base)

    def test_ordem_alternativas_nucleo_ultima_palavra_reserva(self):
        seg = self._seg(alternativas=["man working late", "laptop in dark room"], busca_reserva="dark city night")
        assert va._fallback_queries_for(seg) == ["man working late", "laptop in dark room", "tired man laptop", "night", "dark city night"]

    def test_sem_campos_novos_cai_no_nature_background_como_antes(self):
        assert va._fallback_queries_for(self._seg(query="sunrise over mountains")) == ["mountains", "nature background"]

    def test_close_up_e_artigo_nao_contam_no_nucleo(self):
        seg = self._seg(query="close up of hands typing on keyboard at night")
        assert "hands typing keyboard" in va._fallback_queries_for(seg)

    def test_mixkit_usa_alternativas_e_flow_nada(self):
        assert va._fallback_queries_for(self._seg(provider="mixkit", query="business", alternativas=["technology"])) == ["technology", "background"]
        assert va._fallback_queries_for(self._seg(provider="flow", alternativas=["x"], busca_reserva="y")) == []

    def test_buscadores_de_imagem_usam_a_reserva_da_ia_na_2a_passada(self, tmp_path):
        chamadas = []

        def lote(itens, pasta, on_result=None, **kw):
            chamadas.append([it["query"] for it in itens])
            for it in itens:
                ok = it["query"] == "snowy tent"
                on_result(it["query"], {"ok": ok, "path": str(tmp_path / "a.jpg") if ok else None, "engine": "bing"})

        seg = self._seg(provider="bing", media_type="image", query="dyatlov pass tent 1959", alternativas=["snowy tent"])
        res = va.prefetch_browser_images([(0, seg)], str(tmp_path), site_cfg={}, lote_fn=lote)
        assert chamadas == [["dyatlov pass tent 1959"], ["snowy tent"]]
        assert res[0]["ok"] and res[0]["query_usada"] == "snowy tent"


# ------------------------------------------------------------------ avisos
class TestAvisos:
    def test_aponta_portugues_repeticao_sequencia_e_longas(self):
        av = " ".join(pb.avisos_buscas([
            {"provider": "pexels", "query": "homem andando na rua"},
            {"provider": "pexels", "query": "dark forest"},
            {"provider": "pexels", "query": "dark forest"},
            {"provider": "pixabay", "query": "Dark Forest"},
            {"provider": "pexels", "query": "a man walking slowly through the old dark forest at night"},
        ]))
        assert "não parecem estar em inglês (trechos 1)" in av
        assert "“dark forest” 3×" in av
        assert "trechos seguidos (trechos 3, 4)" in av
        assert "longas demais (trechos 5)" in av

    def test_ignora_midia_escolhida_flow_e_busca_boa(self):
        assert pb.avisos_buscas([
            {"provider": "pexels", "query": "homem andando", "override_source": {"source": "local_file"}},
            {"provider": "flow", "query": "uma cidade flutuando"},
            {"provider": "pexels", "query": "empty dark road at night"},
            {"provider": "pexels", "query": "old man reading letter"},
        ]) == []


# ------------------------------------------------------------------ revisão das buscas
_TRECHOS = [
    {"start": 0, "end": 4, "provider": "pexels", "query": "mystery", "fala": "Ninguém sabe o que aconteceu."},
    {"start": 4, "end": 8, "provider": "flow", "media_type": "image", "query": "x", "fala": "Nove estudantes"},
    {"start": 8, "end": 12, "provider": "pixabay", "query": "mountain", "override_source": {"source": "local_file"}, "fala": "subiram"},
    {"start": 12, "end": 16, "provider": "pexels", "media_type": "image", "query": "tent", "alternativas": ["snow"], "fala": "a barraca rasgada"},
]


class TestRevisao:
    def test_prompt_lista_fala_busca_e_fixos(self):
        p = pb.build_revisao_buscas_prompt(_TRECHOS, "português", "9:16", "mais clima de terror")
        assert '#0 [00:00.000–00:04.000] pexels · vídeo | fala: "Ninguém sabe o que aconteceu." | busca atual: "mystery"' in p
        assert "#1 [00:04.000–00:08.000] (FIXO — imagem gerada por IA" in p
        assert "#2 [00:08.000–00:12.000] (FIXO — mídia escolhida à mão" in p
        assert 'pexels · foto' in p and 'reservas: "snow"' in p
        assert "mais clima de terror" in p and "VERTICAL" in p
        assert "## Como escrever a busca" in p and "(2 trechos)" in p

    def test_sem_trecho_de_estoque_da_erro_claro(self):
        with pytest.raises(pb.PromptBuilderError, match="não há busca pra revisar"):
            pb.build_revisao_buscas_prompt([_TRECHOS[1], _TRECHOS[2]])

    def test_le_resposta_ignora_fixos_e_marca_o_que_mudou(self):
        r = pb.ler_revisao_buscas("```json\n" + json.dumps({"busca_reserva": "snowy mountain night", "trechos": [
            {"i": 0, "visual": "estrada escura", "query": "empty dark road at night", "alternativas": ["dark road"]},
            {"i": 1, "query": "nao pode"},
            {"i": "#3", "query": "tent", "alternativas": ["snow tent", "camping tent"]},
            {"i": 9, "query": "nao existe"},
        ]}) + "\n```", _TRECHOS)
        assert [t["i"] for t in r["trechos"]] == [0, 3]
        assert r["trechos"][0]["mudou"] and r["trechos"][0]["antes"] == "mystery"
        assert not r["trechos"][1]["mudou"] and r["trechos"][1]["alternativas"] == ["snow tent", "camping tent"]
        assert r["busca_reserva"] == "snowy mountain night"
        assert any("#1 é fixo" in a for a in r["avisos"]) and any("#9 não existe" in a for a in r["avisos"])

    def test_resposta_com_texto_em_volta_ou_vazia(self):
        r = pb.ler_revisao_buscas('Claro! Aqui está:\n{"trechos": [{"i": 0, "query": "dark road"}]}\nAbraço', _TRECHOS)
        assert r["trechos"][0]["query"] == "dark road"
        with pytest.raises(pb.PromptBuilderError):
            pb.ler_revisao_buscas('{"trechos": [{"i": 1, "query": "x"}]}', _TRECHOS)


# ------------------------------------------------------------------ site
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(A):
    return A.app.test_client()


def _job(A, job_id, segs):
    os.makedirs(A._job_dir(job_id), exist_ok=True)
    A._JOBS[job_id] = {
        "job_id": job_id, "status": "pronto_para_editar", "created_at": 1.0, "language": "pt",
        "providers": ["pexels", "pixabay", "flow"], "total_duration": segs[-1]["end"],
        "pending_segments": segs, "segment_previews": [None] * len(segs),
        "segments": [{"start": s["start"], "end": s["end"], "text": f"fala {k}"} for k, s in enumerate(segs)],
    }
    return A._JOBS[job_id]


def _segs():
    return [
        {"start": 0.0, "end": 4.0, "provider": "pexels", "query": "mystery", "media_type": "video", "override_source": None,
         "alternativas": ["dark night"], "visual": "noite", "busca_reserva": "dark forest"},
        {"start": 4.0, "end": 8.0, "provider": "pixabay", "query": "mountain", "media_type": "video", "override_source": None},
    ]


class TestSite:
    def test_editor_classico_mantem_reservas_so_se_a_busca_nao_mudou(self, A, client):
        job = _job(A, "bus-classico", _segs())
        client.post("/job/bus-classico/confirm-segments", data={"acao": "salvar", "seg_0_query": "mystery", "seg_1_query": "snowy mountain"})
        s0, s1 = job["pending_segments"]
        assert s0["alternativas"] == ["dark night"] and s0["visual"] == "noite" and s0["busca_reserva"] == "dark forest"
        job["pending_segments"][0]["query"] = "mystery"
        client.post("/job/bus-classico/confirm-segments", data={"acao": "salvar", "seg_0_query": "foggy road"})
        assert "alternativas" not in job["pending_segments"][0]  # reserva de outra busca não serve

    def test_estudio_manda_reservas_visual_e_reserva_do_video(self, A, client):
        job = _job(A, "bus-estudio", _segs())
        client.post("/job/bus-estudio/confirm-segments", data={
            "acao": "salvar", "busca_reserva": "snowy mountain night 4k",
            "seg_0_query": "empty dark road", "seg_0_alternativas": json.dumps(["dark road", "empty dark road"]), "seg_0_visual": "estrada",
            "seg_1_query": "mountain", "seg_1_alternativas": "[]", "seg_1_visual": "",
        })
        s0, s1 = job["pending_segments"]
        assert s0["query"] == "empty dark road" and s0["alternativas"] == ["dark road"] and s0["visual"] == "estrada"
        assert s0["busca_reserva"] == s1["busca_reserva"] == "snowy mountain night"
        assert "alternativas" not in s1

    def test_submit_json_avisa_buscas_ruins(self, A, client, monkeypatch):
        job = _job(A, "bus-aviso", _segs())
        monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
        resp = json.dumps({"segments": [
            {"start": 0, "end": 4, "provider": "pexels", "query": "homem andando na rua"},
            {"start": 4, "end": 8, "provider": "pexels", "query": "dark forest"},
        ]})
        client.post("/job/bus-aviso/submit-json", data={"ai_response": resp})
        assert "não parecem estar em inglês" in job["aviso_buscas"]
        html = client.get("/job/bus-aviso/edit-segments?modo=estudio").get_data(as_text=True)
        assert "avisoBuscas" in html and "Revisar buscas com IA" in html

    def test_rotas_da_revisao(self, A, client):
        _job(A, "bus-rev", _segs())
        d = client.post("/job/bus-rev/buscas/prompt", json={"objetivo": "clima de terror"}).get_json()
        assert d["ok"] and d["revisaveis"] == 2 and 'fala: "fala 0"' in d["prompt"] and "clima de terror" in d["prompt"]
        d = client.post("/job/bus-rev/buscas/resposta", json={"texto": json.dumps({"trechos": [{"i": 1, "query": "snowy mountain peak"}]})}).get_json()
        assert d["ok"] and d["trechos"][0]["mudou"] and d["trechos"][0]["antes"] == "mountain"
        r = client.post("/job/bus-rev/buscas/resposta", json={"texto": "nada"})
        assert r.status_code == 400

    def test_previa_tenta_reservas_e_grava(self, A, client, monkeypatch):
        job = _job(A, "bus-previa", _segs())
        vistos = []

        def fake(provider, query, **kw):
            vistos.append(query)
            return [{"thumbnail": "https://t/x.jpg", "url": "https://p/1", "label": "estrada"}] if query == "dark road" else []

        monkeypatch.setattr(A, "search_candidates", fake)
        d = client.post("/job/bus-previa/buscas/previa/0", json={"query": "empty dark road", "provider": "pexels", "alternativas": ["dark road"]}).get_json()
        assert vistos == ["empty dark road", "dark road"]
        assert d["preview"]["ok"] and "reserva “dark road”" in d["preview"]["label"]
        assert job["segment_previews"][0]["thumbnail_url"] == "https://t/x.jpg"
        # desfazer grava a prévia antiga sem buscar nada
        client.post("/job/bus-previa/buscas/previa/0", json={"definir": {"ok": False, "error": "antiga"}})
        assert job["segment_previews"][0]["error"] == "antiga" and len(vistos) == 2

    def test_corrigir_trecho_usa_a_reserva_da_ia(self, A, client):
        job = _job(A, "bus-fix", _segs())
        job["assembly_error"] = "Trecho 1: nada"
        job["assembly_error_segment_index"] = 0
        d = client.post("/job/bus-fix/corrigir-trecho", json={"indice": 0}).get_json()
        assert job["pending_segments"][0]["query"] == "dark night" and "reserva da IA" in d["mensagem"]


# ------------------------------------------------------------------ buscadores: marca d'água e imagem repetida
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import buscador_imagens_unificado as bu  # noqa: E402


def _png(path, cor, padrao=0):
    """Imagem com blocos sorteados pela semente `padrao`: mesma semente = mesma
    imagem (mesmo com outro endereço); semente diferente = imagem diferente."""
    import random
    from PIL import Image, ImageDraw
    rnd = random.Random(padrao)
    im = Image.new("RGB", (160, 90), cor)
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rnd.randrange(150), rnd.randrange(80)
        v = rnd.randrange(256)
        d.rectangle([x, y, x + 20, y + 14], fill=(v, 255 - v, rnd.randrange(256)))
    im.save(path)
    return str(path)


class TestMarcaDagua:
    def test_detecta_pelo_endereco_pagina_e_titulo(self):
        I = bu.ImagemBuscador
        assert bu.tem_marca_dagua(I(original_url="https://c8.alamy.com/comp/JGT9HN/x.jpg"))
        assert bu.tem_marca_dagua(I(original_url="https://t3.ftcdn.net/jpg/01/x.jpg"))
        assert bu.tem_marca_dagua(I(original_url="https://a.com/x.jpg", source_page="https://www.shutterstock.com/image-photo/x"))
        assert bu.tem_marca_dagua(I(original_url="https://a.com/x.jpg", title="Bride at the door Stock Photo - Alamy"))
        assert not bu.tem_marca_dagua(I(original_url="https://upload.wikimedia.org/k.jpg", title="Kill Bill poster"))
        assert not bu.tem_marca_dagua(I(original_url="https://a.com/stock-market.jpg", title="stock market crash"))

    def test_limpa_endereco_reserva_marcado(self):
        img = bu.ImagemBuscador(original_url="https://a.com/x.jpg", fallback_urls=["https://c8.alamy.com/y.jpg", "https://b.com/z.jpg"])
        assert bu.sem_marca_dagua([img])[0].fallback_urls == ["https://b.com/z.jpg"]


class TestNaoRepetirImagem:
    def _rodar(self, tmp_path, por_termo, pedidos, evitar=None):
        arquivos = {}

        def buscar(engine, termos):
            return {"por_termo": {t: [bu.ImagemBuscador(original_url=u, title=u) for u, _c in por_termo.get(t, [])] for t in termos},
                    "erros": {}, "erro_geral": None}

        def baixar(img, pasta, stem):
            cor = dict(sum(por_termo.values(), []))[img.original_url]
            return _png(tmp_path / f"{stem}.png", *cor)

        return bu.buscar_e_baixar_primeira(pedidos, str(tmp_path), engines=["bing"], paralelo=False,
                                           buscar_fn=buscar, baixar_fn=baixar, evitar=evitar)

    def test_mesma_cena_em_outro_site_e_pulada(self, tmp_path):
        mesma = ((200, 30, 30), 5)
        res = self._rodar(tmp_path, {
            "mr blonde dancing": [("https://a.com/1.jpg", mesma), ("https://a.com/2.jpg", ((20, 200, 30), 3))],
            "mr blonde razor": [("https://outro.com/1-copia.jpg", mesma), ("https://c.com/3.jpg", ((30, 30, 200), 7))],
        }, ["mr blonde dancing", "mr blonde razor"])
        assert res["mr blonde dancing"]["original_url"] == "https://a.com/1.jpg"
        assert res["mr blonde razor"]["original_url"] == "https://c.com/3.jpg"  # a cópia da 1ª ficou de fora

    def test_marca_dagua_nunca_entra(self, tmp_path):
        res = self._rodar(tmp_path, {"bride": [("https://c8.alamy.com/x.jpg", ((1, 2, 3), 2)), ("https://ok.com/b.jpg", ((90, 90, 9), 4))]}, ["bride"])
        assert res["bride"]["original_url"] == "https://ok.com/b.jpg"

    def test_mesmo_termo_em_tres_trechos_traz_tres_imagens(self, tmp_path):
        res = self._rodar(tmp_path, {"pulp fiction": [(f"https://s.com/{k}.jpg", ((40 * k, 255 - 40 * k, 60), k + 1)) for k in range(4)]},
                          [{"query": "pulp fiction", "engine": "bing", "quantidade": 3}])
        r = res["pulp fiction"]
        assert [r["original_url"]] + [e["original_url"] for e in r["extras"]] == [f"https://s.com/{k}.jpg" for k in range(3)]

    def test_so_repetida_entra_como_ultimo_recurso(self, tmp_path):
        a = _png(tmp_path / "ja.png", (200, 30, 30), 5)
        res = self._rodar(tmp_path, {"x": [("https://z.com/x.jpg", ((200, 30, 30), 5))]}, ["x"], evitar=[bu.assinatura_visual(a)])
        assert res["x"]["ok"] and res["x"]["repetida"]

    def test_prefetch_espalha_as_imagens_entre_os_trechos(self, tmp_path):
        def lote(pedidos, pasta, on_result=None, **kw):
            assert pedidos[0]["quantidade"] == 2 and kw["evitar"] == ["https://antes.com/a.jpg"]
            p1, p2 = _png(tmp_path / "1.png", (9, 9, 9)), _png(tmp_path / "2.png", (99, 9, 9), 4)
            on_result("pulp fiction", {"ok": True, "path": p1, "engine": "bing", "original_url": "u1",
                                       "extras": [{"path": p2, "engine": "bing", "original_url": "u2"}]})

        seg = pb.VideoSegment(start=0, end=4, provider="bing", query="pulp fiction", media_type="image")
        cache = {"outro": {"ok": True, "path": "/nao", "original_url": "https://antes.com/a.jpg"}}
        res = va.prefetch_browser_images([(0, seg), (1, seg)], str(tmp_path), site_cfg={}, cache=cache, lote_fn=lote)
        assert res[0]["original_url"] == "u1" and res[1]["original_url"] == "u2"
        # do cache (prévia → montagem) continua uma pra cada trecho
        res2 = va.prefetch_browser_images([(0, seg), (1, seg)], str(tmp_path), site_cfg={}, cache=cache, lote_fn=None)
        assert res2[0]["path"] != res2[1]["path"]

    def test_revisao_com_ia_vale_pros_buscadores(self):
        trechos = [{"start": 0, "end": 4, "provider": "bing", "media_type": "image", "query": "mr blonde", "fala": "a"},
                   {"start": 4, "end": 8, "provider": "bing", "media_type": "image", "query": "mr blonde", "fala": "b"}]
        p = pb.build_revisao_buscas_prompt(trechos)
        assert "## Trechos de buscador de imagem (bing)" in p and "MESMA imagem" in p and "(2 trechos)" in p
        assert "Buscas repetidas" not in " ".join(pb.avisos_buscas(trechos))  # 2× ainda não é aviso
        assert "trechos seguidos" in " ".join(pb.avisos_buscas(trechos))


class TestRepetidaTentaReservaAntes:
    def test_repetida_vai_pra_busca_reserva_e_so_entra_se_nada_mais_achar(self, tmp_path):
        chamadas = []
        p_rep, p_nova = _png(tmp_path / "rep.png", (9, 9, 9), 1), _png(tmp_path / "nova.png", (99, 9, 9), 2)

        def lote(pedidos, pasta, on_result=None, **kw):
            q = pedidos[0]["query"]
            chamadas.append(q)
            if q == "mr blonde scene":
                on_result(q, {"ok": True, "repetida": True, "path": p_rep, "engine": "bing", "original_url": "rep"})
            else:
                on_result(q, {"ok": True, "path": p_nova, "engine": "bing", "original_url": "nova"})

        seg = pb.VideoSegment(start=0, end=4, provider="bing", query="mr blonde scene", media_type="image", alternativas=["michael madsen 1992"])
        res = va.prefetch_browser_images([(0, seg)], str(tmp_path), site_cfg={}, cache={}, lote_fn=lote)
        assert chamadas == ["mr blonde scene", "michael madsen 1992"] and res[0]["original_url"] == "nova"

        def lote_so_repetida(pedidos, pasta, on_result=None, **kw):
            q = pedidos[0]["query"]
            on_result(q, {"ok": True, "repetida": True, "path": p_rep, "engine": "bing", "original_url": "rep-" + q})

        res = va.prefetch_browser_images([(0, seg)], str(tmp_path), site_cfg={}, cache={}, lote_fn=lote_so_repetida)
        assert res[0]["ok"] and res[0]["original_url"] == "rep-mr blonde scene"  # fica a 1ª repetida, não some


def test_bing_sem_abrir_detalhe_quando_pede_varios_candidatos():
    assert bu._opcoes_do_motor("bing", None, 14) == {"click_details": False}
    assert bu._opcoes_do_motor("bing", {"click_details": True}, 14) == {"click_details": True}
    assert bu._opcoes_do_motor("bing", None, 1) == {} and bu._opcoes_do_motor("brave", None, 14) == {}
