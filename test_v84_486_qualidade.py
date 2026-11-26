"""v84_486 — 🧪 verificação de qualidade do roteiro pronto: prompt → JSON de correções → aplica (sem encolher)."""
import json

import pytest

import dossies as ds
import qualidade_roteiro as qr

ROT = ("A resposta indireta é quando você muda de assunto ou faz uma piada.\n\n"
       "Também não diz que a reunião vai acontecer sem você.\n\n"
       "Essa conversa começa onde a anterior parou. " + "Uma frase qualquer sobre perguntas. " * 60)


def test_prompt_e_ler():
    pr = qr.prompt(ROT, "Pergunta armadilha", "F1 — notas: resposta indireta = informação parcial", "1) réplica | 2) disjunção",
                   alvo_palavras=500)
    assert "conceito_errado" in pr and "MAPA" in pr and "FONTE" in pr and "TAMANHO" in pr and ROT[:40] in pr
    d = qr.ler(json.dumps({"problemas": [{"tipo": "conceito errado", "trecho": "A resposta indireta é", "correcao": "x"},
                                         {"tipo": "zzz", "de": "a", "para": "a"}], "resumo": "ok"}))
    assert len(d["trocas"]) == 1 and d["trocas"][0]["tipo"] == "conceito_errado" and d["resumo"] == "ok"
    with pytest.raises(ValueError):
        qr.prompt("", "x")


@pytest.fixture
def proj():
    import app as _app
    p = ds.criar(_app.BASE_DIR, "Pergunta armadilha", modelo="raciocinio_maldito")
    p["config"].update(modo_partes="nao", minutos=2, extra="1) réplica | 2) disjunção")
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": ROT, "titulos": ["T"]}), p)
    ds.salvar(_app.BASE_DIR, p)
    yield _app, p
    ds.excluir(_app.BASE_DIR, p["id"])


def test_rotas(proj):
    A, p = proj
    c = A.app.test_client()
    pr = c.post(f"/qualidade/dossie/{p['id']}/prompt", json={}).get_json()
    assert pr["ok"] and "disjunção" in pr["prompt"]
    resp = json.dumps({"correcoes": [
        {"tipo": "conceito_errado", "de": "A resposta indireta é quando você muda de assunto ou faz uma piada.",
         "para": "A resposta indireta dá só parte da informação pedida.", "porque": "a fonte define assim"}],
        "resumo": "1 conceito corrigido"})
    r = c.post(f"/qualidade/dossie/{p['id']}/ler", json={"texto": resp}).get_json()
    assert r["ok"] and len(r["aplicadas"]) == 1 and r["aplicadas"][0]["tipo"] == "conceito_errado"
    q = ds.carregar(A.BASE_DIR, p["id"])
    assert "parte da informação pedida" in q["resultado"]["roteiro"]
    vazio = c.post(f"/qualidade/dossie/{p['id']}/ler", json={"texto": json.dumps({"correcoes": [], "resumo": "nada"})}).get_json()
    assert vazio["ok"] and vazio["aplicadas"] == []
    # encolher demais = não aplica
    corta = json.dumps({"correcoes": [{"tipo": "repeticao", "de": "Uma frase qualquer sobre perguntas. " * 50, "para": ""}]})
    assert c.post(f"/qualidade/dossie/{p['id']}/ler", json={"texto": corta}).status_code == 400


def test_v488_link_amazon_encurtado():
    import vendas as v
    assert v._eh_amazon("https://link.amazon/B0jjxqS7M") and v._eh_amazon("https://www.amazon.com.br/dp/1")
    assert not v._eh_amazon("https://amazon.evil.com/x")


def test_v489_trocar_livro_nao_achado():
    import livros_afiliado as la
    p = {"tema": "pergunta armadilha", "resultado": {"roteiro": "texto do roteiro " * 50}}
    lv = la.estado(p)
    lv["sugeridos"] = [{"titulo": "Uma Introdução aos Argumentos", "autor": "Trudy Govier", "por_que": "ARG", "onde": "x"}]
    pedidos = []

    def falso(rec, system, conteudo, **kw):
        pedidos.append((conteudo, kw))
        return {"livros": [{"titulo": "A Arte de Argumentar", "autor": "Anthony Weston", "editora": "WMF Martins Fontes",
                            "por_que": "p", "onde": ""}]}
    novo = la.trocar(p, 0, chamar=falso)
    assert novo["titulo"] == "A Arte de Argumentar" and novo["onde"] == "x" and novo["editora"]
    assert "Trudy Govier" in pedidos[0][0] and pedidos[0][1]["web"] is True
    assert la.estado(p)["nao_achados"] and la.estado(p)["sugeridos"][0]["titulo"] == "A Arte de Argumentar"


def test_v490_autor_e_titulo_limpos_na_descricao():
    import livros_afiliado as la
    assert la.limpar_autor("Edição Português por Douglas N. Walton , Ana Lúcia R. Franco , Carlos A. L. Salum &amp; 1 mais") == "Douglas N. Walton"
    assert la.limpar_autor("Arthur Schopenhauer (Autor), Fulano de Tal (Organizador)") == "Arthur Schopenhauer"
    assert la.limpar_titulo("Informal Logic: A Pragmatic Approach – Edição Português") == "Informal Logic: A Pragmatic Approach"
    res = {"livros": {"ativo": True, "destino": "ambos", "escolhidos": [
        {"titulo_curto": "X &amp; Y", "autor": "por Ana &amp; 2 mais", "link": "https://link.amazon/a"}]}}
    d = la.bloco_descricao(res)
    assert "&amp;" not in d and "mais" not in d and "X & Y — Ana" in d


def test_v491_livro_nao_entra_na_abertura():
    import livros_afiliado as la
    rot = "Abertura do vídeo com o gancho.\n\n" + ("Meio do vídeo com explicação. " * 40) + "\n\nFrase do meio onde cabe o livro.\n\n" + ("Mais texto. " * 40)
    p = {"tema": "x", "resultado": {"roteiro": rot, "livros": {"escolhidos": [{"titulo_curto": "L", "autor": "A", "capa": "", "link": "https://amzn.to/x"}]}}}

    def falso(rec, system, conteudo, **kw):
        assert "NÃO INVENTE" in system
        return {"trocas": [{"de": "Abertura do vídeo com o gancho.", "para": "Abertura. Leia L.", "livro": "L"},
                           {"de": "Frase do meio onde cabe o livro.", "para": "Frase do meio. Pra ir mais fundo, tem L, de A.", "livro": "L"}]}
    novo = la.adaptar(p, chamar=falso)
    assert "Leia L" not in novo and "Pra ir mais fundo, tem L" in novo


def test_v492_refazer_parte_da_versao_sem_livros():
    import livros_afiliado as la
    p = {"resultado": {"roteiro": "COM livro", "roteiro_sem_livros": "SEM livro", "livros": {"ativo": True}}}
    assert la._roteiro_base(p) == "SEM livro"
    p["resultado"].update(roteiro="SEM livro corrigido", livros={"ativo": False})
    assert la._roteiro_base(p) == "SEM livro corrigido"


def test_v494_direcao_e_capa_do_livro():
    import cenas_lote
    import dp_direcao
    d = next(x for x in dp_direcao.sistema() if x["id"] == "sys_raciocinio_maldito")
    assert d["som_transicoes"] == "nenhum" and not any("sfx" in e for e in d["destaques"]["estilos"])
    import dossies as ds
    assert ds.MODELOS["raciocinio_maldito"]["direcao_sugerida"] == "sys_raciocinio_maldito"
    cenas = [{"start": 0, "end": 4, "fala": "o vídeo começa aqui"},
             {"start": 4, "end": 8, "fala": "pra quem quiser ir mais fundo tem Como Ler um Livro do Adler"}]
    assert cenas_lote.cena_do_texto(cenas, "Como Ler um Livro") == 1
    js = cenas_lote.montar_json(cenas, {}, {0}, "", {1: {"id": "I7", "tipo": "foto", "provider": "material", "livro": True}})
    seg = js["segments"][1]
    assert seg["query"] == "I7" and seg["aspect_fill"] == "cartao"


def test_v495_capa_do_livro_no_fluxo_local(monkeypatch):
    import app as A
    p = {"resultado": {"livros": {"ativo": True, "escolhidos": [{"titulo_curto": "Como Ler um Livro", "capa": "I7"}]}}}
    monkeypatch.setattr(A, "_projeto_do_job", lambda job: ("dossie", None, p, "material"))
    job = {"segments": [{"start": 0, "end": 5, "text": "abertura do vídeo"},
                        {"start": 30, "end": 36, "text": "pra quem quiser treinar tem Como Ler um Livro do Adler"}]}
    segs = [{"start": 0, "end": 10, "provider": "anime_pexels", "query": "x"},
            {"start": 28, "end": 34, "provider": "anime_pexels", "query": "y"}]
    assert A._forcar_capas_livro(job, segs) == 1
    assert segs[1]["provider"] == "material" and segs[1]["query"] == "I7" and segs[1]["aspect_fill"] == "cartao"
    assert segs[0]["provider"] == "anime_pexels"


def test_v497_trecho_do_livro_editado_e_ia_sem_som(monkeypatch):
    import app as A
    import prompt_edicao as pe
    p = {"resultado": {"livros": {"ativo": True, "escolhidos": [{"titulo_curto": "Como Ler um Livro", "autor": "Mortimer J. Adler", "capa": "I7"}]}}}
    monkeypatch.setattr(A, "_projeto_do_job", lambda job: ("dossie", None, p, "material"))
    job = {"segments": [{"start": 30, "end": 36, "text": "tem Como Ler um Livro do Adler"}], "pending_segments": [],
           "total_duration": 60}
    segs = [{"start": 28, "end": 34, "provider": "x", "query": "y"}]
    A._forcar_capas_livro(job, segs)
    assert segs[0]["livro"] and segs[0]["aspect_fill"] == "cartao"

    class P:
        segments, destaques, graficos = [], [], []
    A._aplicar_extras_dp(job, P())
    d = [x for x in job["destaques"] if x["origem"] == "livro"]
    assert d and "Como Ler um Livro — Mortimer J. Adler" == d[0]["texto"]
    pr = pe.montar_prompt({"pending_segments": [dict(segs[0], end=34)], "total_duration": 60},
                          {"direcao": "sys_raciocinio_maldito", "segmentos": [dict(segs[0])]})
    assert "SEM EFEITO SONORO" in pr and "ESTÉTICA DO CANAL" in pr and "CAPA DO LIVRO" in pr
    assert "Sons (opcional" not in pr


def test_v498_livro_em_projeto_antigo(monkeypatch):
    import app as A
    p = {"resultado": {"livros": {"ativo": True, "escolhidos": [{"titulo_curto": "Como Ler um Livro", "autor": "Adler", "capa": "I7"}]}}}
    monkeypatch.setattr(A, "_projeto_do_job", lambda job: ("dossie", None, p, "material"))
    monkeypatch.setattr(A, "_save_state", lambda jid: None)
    usados = []
    monkeypatch.setattr(A, "_aplicar_produto", lambda job, segs: usados.extend(segs) or len(segs))
    job = {"segments": [{"start": 30, "end": 36, "text": "tem Como Ler um Livro do Adler"}],
           "pending_segments": [{"start": 28, "end": 34, "provider": "anime", "query": "y",
                                 "override_source": {"source": "local_file", "value": "/clip.mp4"}}],
           "segment_previews": [{"x": 1}], "destaques": []}
    assert A._livro_em_projeto_antigo("j", job) == 1
    s = job["pending_segments"][0]
    assert s["query"] == "I7" and s["aspect_fill"] == "cartao" and "override_source" not in s and usados == [s]
    assert job["segment_previews"][0] == {} and any(d["origem"] == "livro" for d in job["destaques"])
    assert A._livro_em_projeto_antigo("j", job) == 0  # uma vez só


def test_v499_sem_filtro_tempo_de_leitura_e_enumeracao():
    import dp_destaques as dd
    import dp_direcao
    import prompt_edicao as pe
    segs = [{"start": i * 5, "end": i * 5 + 5, "foto": True} for i in range(30)]
    assert dp_direcao.planejar(segs, "sys_raciocinio_maldito", semente=7)["filtro_cor"] is None
    pal = [{"word": "Pressuposto", "start": 10.0, "end": 10.6}, {"word": "é", "start": 10.7, "end": 10.8}]
    d = dd.ancorar([{"estilo": "branco", "start": 10, "end": 10.6, "texto": "1. PRESSUPOSTO"}], pal, 60)
    assert d[0]["end"] - d[0]["start"] >= 2.15
    pr = pe.montar_prompt({"pending_segments": [], "total_duration": 60}, {"direcao": "sys_raciocinio_maldito", "segmentos": []})
    assert "ENUMERAÇÃO = ÊNFASE" in pr and "Filtro de cor (UM pro vídeo todo): NÃO usar" in pr


def test_v500_pares_json_viram_o_formulario():
    import json as _j
    import app as A
    from flask import request
    pares = [["seg_0_start", "0"], ["seg_0_query", "x"], ["seg_1_start", "5"]]
    with A.app.test_request_context("/job/x/confirm", method="POST",
                                    data={"_pares": _j.dumps(pares), "export_quality": "1080p"},
                                    content_type="multipart/form-data"):
        A.app.preprocess_request()
        assert request.form["seg_0_query"] == "x" and request.form["seg_1_start"] == "5"
        assert request.form["export_quality"] == "1080p" and "_pares" not in request.form


def test_v501_status_dos_livros(monkeypatch):
    import app as A
    p = {"resultado": {"livros": {"ativo": True, "escolhidos": [{"titulo_curto": "Como Ler um Livro", "capa": "I7"}]}}}
    monkeypatch.setattr(A, "_projeto_do_job", lambda job: ("dossie", None, p, "material"))
    job = {"segments": [{"start": 30, "end": 36, "text": "tem Como Ler um Livro do Adler"}],
           "pending_segments": [{"start": 28, "end": 34, "provider": "material", "query": "I7", "livro": True}]}
    st = A.status_livros(job)
    assert st[0]["no_roteiro"] and st[0]["falado_em"] == 30 and st[0]["trecho"] == 0 and st[0]["no_texto"] is False
    job["segments"][0]["text"] = "outra coisa"
    assert A.status_livros(job)[0]["falado_em"] is None


def test_v84_503_livros_mencao_e_botao():
    import os, sys
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "toolkit"))
    import livros_afiliado as la
    assert la.limpar_autor("por Fulano de Tal (Autor) &amp; mais").startswith("Fulano")
    src = open(os.path.join(base, "templates", "dossie_detalhe.html"), encoding="utf-8").read()
    assert "📍 no roteiro" in src and "no roteiro (a IA acha o melhor lugar)" in src and "gere a 🎙 voz de novo" in src
    assert 'x["mencao"]' in open(la.__file__, encoding="utf-8").read()


def _proj_livros():
    rot = ("Abertura forte sobre pensar direito. " * 20 + "\n\n" +
           "Um argumento tem premissas e conclusão. Saber separar as duas é o começo de tudo.\n\n"
           "A falácia é um erro de raciocínio que parece certo. Ela engana porque soa bem.\n\n"
           "Por hoje é isso. As fontes estão na descrição.")
    return {"tema": "lógica", "resultado": {"roteiro": rot, "livros": {"escolhidos": [
        {"titulo": "Como Ler um Livro", "titulo_curto": "Como Ler um Livro", "autor": "Mortimer J. Adler", "capa": "I1", "link": "x"},
        {"titulo": "Introdução à Lógica: 3ª edição", "titulo_curto": "Introdução à Lógica", "autor": "Irving M. Copi", "capa": "I2", "link": "y"}]}}}


def test_v84_504_livro_que_ficou_de_fora_ganha_segunda_chamada():
    import os, sys
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "toolkit"))
    import livros_afiliado as la
    p = _proj_livros()
    chamadas = []

    def fake(rec, system, conteudo, **kw):
        chamadas.append(conteudo)
        if len(chamadas) == 1:  # 1ª: o 2º livro vai na ABERTURA (é descartado) — só o 1º entra
            return {"trocas": [
                {"de": "Saber separar as duas é o começo de tudo.", "livro": "Como Ler um Livro",
                 "para": "Saber separar as duas é o começo de tudo. [I1] Isso está em ‘Como Ler um Livro’, do Adler."},
                {"de": "Abertura forte sobre pensar direito.", "livro": "Introdução à Lógica",
                 "para": "Abertura forte sobre pensar direito. [I2] Tem ‘Introdução à Lógica’, do Copi."}]}
        assert "Introdução à Lógica" in conteudo and "JÁ CITADOS" in conteudo and "Abertura forte" not in conteudo
        return {"trocas": [{"de": "Ela engana porque soa bem.", "livro": "Introdução à Lógica",
                            "para": "Ela engana porque soa bem. [I2] Pra ir mais fundo, tem ‘Introdução à Lógica’, do Copi."}]}
    novo = la.adaptar(p, chamar=fake)
    assert len(chamadas) == 2
    lv = p["resultado"]["livros"]
    assert all(x.get("mencao") for x in lv["escolhidos"]) and lv["faltando"] == []
    assert "Copi" in lv["escolhidos"][1]["mencao"] and novo.index("Introdução à Lógica") > novo.index("Adler")
    assert not novo.startswith("Abertura forte sobre pensar direito. [I2]")


def test_v84_504_encaixar_so_o_que_falta():
    import os, sys
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "toolkit"))
    import livros_afiliado as la
    p = _proj_livros()
    r = p["resultado"]
    r["roteiro_sem_livros"] = r["roteiro"]
    r["roteiro_com_livros"] = r["roteiro"].replace("o começo de tudo.", "o começo de tudo. [I1] Está em ‘Como Ler um Livro’.")
    r["livros"]["ativo"] = True
    lv = la.estado(p)
    assert lv["escolhidos"][0].get("mencao") and not lv["escolhidos"][1].get("mencao")

    def fake(rec, system, conteudo, **kw):
        assert "Como Ler um Livro" not in conteudo.split("ROTEIRO")[0].split("JÁ CITADOS")[0]
        return {"trocas": [{"de": "Ela engana porque soa bem.", "livro": "Introdução à Lógica",
                            "para": "Ela engana porque soa bem. [I2] Tem ‘Introdução à Lógica’, do Copi."}]}
    novo = la.encaixar_faltando(p, chamar=fake)
    assert "‘Como Ler um Livro’" in novo and "Introdução à Lógica" in novo
    assert all(x.get("mencao") for x in lv["escolhidos"])
