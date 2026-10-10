"""
🛒 Vídeo de venda com página que não é Amazon: Gumroad, landing page (JSON-LD ou
só texto), página salva (.html) enviada pelo usuário e páginas como material.
O conteúdo da página vai pro prompt e a IA separa o que vende.
"""
import io
import json
import threading

import pytest

import vendas as vd

GUMROAD_PROPS = {"product": {"id": "abc", "name": "Pack de LUTs Cinema", "price_cents": 1900, "currency_code": "usd",
                             "customizable_price": False, "summary": "40 LUTs pra Premiere e DaVinci",
                             "description_html": "<p>Deixe seus vídeos com cara de filme.</p><ul><li>40 LUTs</li><li>Tutorial em vídeo</li></ul>",
                             "covers": [{"url": "https://public-files.gumroad.com/capa1.png", "type": "image"},
                                        {"url": "https://public-files.gumroad.com/demo.mp4", "type": "video"}],
                             "attributes": [{"name": "Tamanho", "value": "120 MB"}],
                             "ratings": {"count": 87, "average": 4.9}, "seller": {"name": "Ana Edita"}}}
GUMROAD_HTML = ("<html><head><title>Pack de LUTs Cinema</title><meta property='og:image' content='https://public-files.gumroad.com/og.png'>"
                "<link rel='stylesheet' href='https://assets.gumroad.com/app.css'></head><body>"
                "<script type='application/json' class='js-react-on-rails-component' data-component-name='ProductPage'>"
                + json.dumps(GUMROAD_PROPS) + "</script><div id='root'></div></body></html>")

LANDING_HTML = """<html><head><title>Curso Edição Rápida — Inscrições abertas</title>
<meta property="og:description" content="Aprenda a editar vídeos virais em 7 dias">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Course","name":"Curso Edição Rápida",
 "description":"Do zero ao primeiro vídeo viral","offers":{"@type":"Offer","price":"197.00","priceCurrency":"BRL"},
 "aggregateRating":{"@type":"AggregateRating","ratingValue":"4.8","reviewCount":"312"}}</script></head>
<body><nav><a href="/">Início</a></nav><main>
<h1>Edite vídeos que prendem até o fim</h1>
<p>Você grava, mas ninguém assiste até o final? O problema não é a câmera, é a edição.</p>
<h2>O que você vai aprender</h2>
<ul><li>Cortes que seguram a retenção acima de 70%</li><li>Legendas animadas no CapCut e no Premiere</li>
<li>Como escolher música sem tomar direitos autorais</li></ul>
<h2>Bônus</h2><p>Pack com 200 efeitos sonoros e modelos de legenda prontos pra usar.</p>
<h2>Garantia</h2><p>Garantia incondicional de 7 dias: não gostou, devolvemos 100% do valor.</p>
<h2>Depoimentos</h2><blockquote>Meu canal saiu de 300 pra 12 mil inscritos em 3 meses. — Júlia</blockquote>
<figure><img src="/img/aula.jpg" width="800" height="450"><figcaption>Aula 3: cortes dinâmicos</figcaption></figure>
<p>De R$ 397 por apenas R$ 197 à vista ou 12x de R$ 19,70.</p>
<iframe src="https://www.youtube.com/embed/VSL123"></iframe>
</main><footer>Termos de uso · Política de privacidade</footer></body></html>"""

SO_TEXTO_HTML = """<html><head><title>Planner Digital 2027</title></head><body><article>
<h1>Planner Digital 2027</h1><p>Organize a sua semana inteira no tablet, com links entre as páginas e capa editável.</p>
<p>Por apenas R$ 29,90 você leva o planner e as atualizações de graça para sempre.</p></article></body></html>"""


def test_le_pagina_do_gumroad():
    d = vd.ler_pagina(GUMROAD_HTML, "https://anaedita.gumroad.com/l/luts")
    assert d["loja"] == "gumroad"
    assert d["titulo"] == "Pack de LUTs Cinema" and d["preco"] == "US$19.00"
    assert "cara de filme" in d["descricao"] and "40 LUTs pra Premiere e DaVinci" in d["topicos"]
    assert "https://public-files.gumroad.com/capa1.png" in d["imagens"] and "https://public-files.gumroad.com/og.png" in d["imagens"]
    assert d["videos"] == ["https://public-files.gumroad.com/demo.mp4"]
    assert "Tamanho: 120 MB" in d["detalhes"] and "4.9 de 5 (87 avaliações)" in d["detalhes"] and "Ana Edita" in d["detalhes"]
    assert vd._eh_gumroad("https://gum.co/x") and not vd._eh_gumroad("https://site.com", "<html></html>")


def test_preco_do_gumroad_em_real_e_pague_quanto_quiser():
    assert vd._preco_ld("1297.5", "BRL") == "R$ 1.297,50" and vd._preco_ld(19, "usd") == "US$ 19.00" and vd._preco_ld("x", "") == "x"
    assert vd._preco_gumroad({"price_cents": 4990, "currency_code": "brl"}) == "R$49,90"
    assert vd._preco_gumroad({"price_cents": 0, "customizable_price": True}) == "grátis (ou pague quanto quiser)"
    assert vd._preco_gumroad({"price_cents": 500, "currency_code": "usd", "customizable_price": True}) == "US$5.00+"


def test_le_landing_page_com_conteudo_inteiro():
    d = vd.ler_pagina(LANDING_HTML, "https://edicaorapida.com.br/curso")
    assert d["loja"] == "pagina" and d["titulo"] == "Curso Edição Rápida" and d["preco"] == "R$ 197,00"
    assert "Avaliação na página: 4.8 (312 avaliações)" in d["detalhes"]
    assert "Vídeo na página: https://www.youtube.com/embed/VSL123" in d["detalhes"]
    c = d["conteudo"]
    for trecho in ("O que você vai aprender", "retenção acima de 70%", "200 efeitos sonoros", "Garantia incondicional de 7 dias",
                   "300 pra 12 mil inscritos", "De R$ 397 por apenas R$ 197"):
        assert trecho in c, trecho
    assert "Política de privacidade" not in c and "Início" not in c
    assert "https://edicaorapida.com.br/img/aula.jpg" in d["imagens"]
    assert d["legendas"]["https://edicaorapida.com.br/img/aula.jpg"] == "Aula 3: cortes dinâmicos"


def test_pagina_so_com_texto_pega_preco_do_texto():
    d = vd.ler_pagina(SO_TEXTO_HTML, "https://loja.com/planner")
    assert d["titulo"] == "Planner Digital 2027" and d["preco"] == "R$ 29,90" and "tablet" in d["conteudo"]
    with pytest.raises(vd.VendaError):
        vd.ler_pagina("<html><body></body></html>", "https://x.com")


def test_ler_produto_escolhe_amazon_ou_pagina():
    assert vd.ler_produto(SO_TEXTO_HTML, "https://loja.com/planner")["loja"] == "pagina"
    import test_v84_vendas as tv
    assert vd.ler_produto(tv.AMAZON_HTML, "https://www.amazon.com.br/dp/B0X")["loja"] == "amazon"


def test_prompt_leva_o_conteudo_da_pagina():
    p = {"id": "x", "link": "https://edicaorapida.com.br/curso", "midias": [], "config": {"duracao_s": 60},
         "produto": vd.ler_pagina(LANDING_HTML, "https://edicaorapida.com.br/curso")}
    pr = vd.prompt_roteiro(p)
    assert "## Conteúdo da página de venda" in pr and "Garantia incondicional de 7 dias" in pr
    assert "QUE ESTÃO na página" in pr and "segundo a página" in pr
    p["produto"]["conteudo"] = ""
    assert "## Conteúdo da página de venda" not in vd.prompt_roteiro(p)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from flask import Flask, Response
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (30, 30, 200)).save(buf, "JPEG")
    jpg = buf.getvalue()
    app = Flask("site_landing")

    @app.route("/curso")
    def curso():
        return LANDING_HTML.replace('src="/img/aula.jpg"', 'src="/img/aula.jpg"')

    @app.route("/img/aula.jpg")
    def foto():
        return Response(jpg, mimetype="image/jpeg")

    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_link_html_enviado_e_material(A, site):
    c = A.app.test_client()
    pid = c.post("/vendas/novo", data={"nome": "Curso"}).headers["Location"].rstrip("/").split("/")[-1]
    try:
        r = c.post(f"/vendas/{pid}/ler-link", json={"link": site + "/curso"})
        assert r.status_code == 200, r.get_json()
        P = r.get_json()["projeto"]
        assert P["loja"] == "pagina" and "Garantia incondicional" in P["produto"]["conteudo"]
        fotos = [m for m in P["midias"] if m.get("do_produto")]
        assert fotos and any("na página: Aula 3: cortes dinâmicos" in m["descricao"] for m in fotos)
        # editar o conteúdo na mão
        c.post(f"/vendas/{pid}/produto", json={"conteudo": "Só isto: garantia de 30 dias."})
        assert "Só isto: garantia de 30 dias." in c.post(f"/vendas/{pid}/prompt", json={}).get_json()["prompt"]
        # página salva (.html) enviada — sem precisar baixar
        r = c.post(f"/vendas/{pid}/ler-html", data={"arquivo": (io.BytesIO(GUMROAD_HTML.encode()), "pagina.html"), "fotos": "0"},
                   content_type="multipart/form-data")
        assert r.status_code == 200, r.get_json()
        P = r.get_json()["projeto"]
        assert P["loja"] == "gumroad" and P["produto"]["titulo"] == "Pack de LUTs Cinema" and P["produto"]["preco"] == "US$19.00"
        assert c.post(f"/vendas/{pid}/ler-html", data={"arquivo": (io.BytesIO(b"x"), "a.pdf")},
                      content_type="multipart/form-data").status_code == 400
        # página como MATERIAL: o conteúdo dela também vai pro prompt
        m = c.post(f"/vendas/{pid}/midia-url", json={"url": site + "/curso"}).get_json()["midia"]
        assert "Garantia incondicional" in m["conteudo"]
        pr = c.post(f"/vendas/{pid}/prompt", json={}).get_json()["prompt"]
        assert "## Conteúdo das páginas enviadas como material" in pr and f"- {m['id']} (" in pr
        assert "Enviar página salva" in c.get(f"/vendas/{pid}").get_data(as_text=True)
    finally:
        c.post(f"/vendas/{pid}/excluir")
