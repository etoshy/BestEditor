"""
🛒 Vídeo de venda: produto (Amazon) -> materiais com descrição -> como vender ->
prompt -> roteiro (JSON) -> Gerar voz -> Novo vídeo com o projeto (as mídias do
produto entram nos trechos "produto" e na biblioteca do Estúdio).
"""
import io
import json
import os
import threading
import zipfile

import pytest

import vendas as vd

AMAZON_HTML = """<html><head><title>Amazon.com.br : Garrafa Térmica X</title>
<meta property="og:title" content="Garrafa Térmica X 1L">
<meta name="description" content="Garrafa que mantém gelado por 24h"></head><body>
<span id="productTitle" class="a-size-large">  Garrafa Térmica X 1L Aço Inox  </span>
<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">R$ 129,90</span></span></div>
<span id="acrPopover" title="4,7 de 5 estrelas"></span><span id="acrCustomerReviewText">1.234 avaliações de clientes</span>
<div id="feature-bullets"><ul>
<li><span class="a-list-item"> Mantém gelado por 24 horas </span></li>
<li><span class="a-list-item">Aço inox 304, sem gosto</span></li>
<li><span class="a-list-item">Ver mais detalhes</span></li></ul></div>
<div id="productDescription"><p>Ideal pra academia e trabalho.</p></div></div>
<script>var data = {'colorImages': { 'initial': [{"hiRes":"https://m.media-amazon.com/images/I/AAA._AC_SL1500_.jpg","large":"https://m.media-amazon.com/images/I/AAA._AC_SX679_.jpg"},
{"hiRes":"https://m.media-amazon.com/images/I/BBB._AC_SL1500_.jpg"}]}};</script>
</body></html>"""


def test_le_a_pagina_da_amazon():
    d = vd.ler_amazon(AMAZON_HTML, "https://www.amazon.com.br/dp/B0X")
    assert d["titulo"] == "Garrafa Térmica X 1L Aço Inox"
    assert d["preco"] == "R$ 129,90"
    assert d["topicos"] == ["Mantém gelado por 24 horas", "Aço inox 304, sem gosto"]
    assert "academia" in d["descricao"]
    assert "4,7 de 5 estrelas" in d["detalhes"] and "1.234" in d["detalhes"]
    assert d["imagens"] == ["https://m.media-amazon.com/images/I/AAA._AC_SL1500_.jpg", "https://m.media-amazon.com/images/I/BBB._AC_SL1500_.jpg"]
    assert vd._eh_amazon("https://amzn.to/abc") and vd._eh_amazon("https://www.amazon.com.br/dp/x") and not vd._eh_amazon("https://amazonas.com")
    assert vd._pagina_bloqueada("<title>Amazon.com</title> Enter the characters you see below captcha")
    assert not vd._pagina_bloqueada(AMAZON_HTML)


def test_og_de_uma_pagina():
    og = vd.ler_og('<meta content="Review do produto" property="og:title"><meta property="og:image" content="/img/a.jpg">'
                   '<meta property="og:description" content="Testei por 30 dias">', "https://site.com/review")
    assert og["titulo"] == "Review do produto" and og["imagem"] == "https://site.com/img/a.jpg" and og["descricao"] == "Testei por 30 dias"


@pytest.fixture(scope="module")
def site_falso(tmp_path_factory):
    """Página com OG + a imagem dela + uma foto solta."""
    from flask import Flask, Response
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buf, "JPEG")
    jpg = buf.getvalue()
    app = Flask("site_falso")

    @app.route("/review")
    def review():
        return ('<html><head><meta property="og:title" content="Garrafa X na academia">'
                '<meta property="og:description" content="Aguentou o treino todo gelada"><meta property="og:image" content="/foto.jpg">'
                "</head><body>oi</body></html>")

    @app.route("/foto.jpg")
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


def _png():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 200)).save(b, "PNG")
    b.seek(0)
    return b


def test_fluxo_completo(A, site_falso):
    c = A.app.test_client()
    r = c.post("/vendas/novo", data={"nome": "Garrafa - teste"})
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        assert "Como vender" in c.get(f"/vendas/{pid}").get_data(as_text=True)
        assert "🛒 Vídeo de venda" in c.get("/vendas").get_data(as_text=True)
        assert c.post(f"/vendas/{pid}/prompt", json={}).status_code == 400  # sem produto nem material
        c.post(f"/vendas/{pid}/produto", json={"titulo": "Garrafa Térmica X", "preco": "R$ 129,90",
                                                "topicos": "- Mantém gelado 24h\n- Aço inox", "descricao": "Pra academia"})
        # do PC: tem que dizer o que é
        assert c.post(f"/vendas/{pid}/midia", data={"arquivo": (_png(), "foto.png")}, content_type="multipart/form-data").status_code == 400
        r = c.post(f"/vendas/{pid}/midia", data={"arquivo": (_png(), "foto.png"), "descricao": "garrafa aberta mostrando a tampa"},
                   content_type="multipart/form-data")
        assert r.get_json()["midia"]["id"] == "M1"
        # de um link: OG + a imagem da página baixada
        m2 = c.post(f"/vendas/{pid}/midia-url", json={"url": site_falso + "/review"}).get_json()["midia"]
        assert m2["id"] == "M2" and m2["tipo"] == "foto" and m2["og"]["titulo"] == "Garrafa X na academia" and m2["arquivo"]
        m3 = c.post(f"/vendas/{pid}/midia-url", json={"url": site_falso + "/foto.jpg", "descricao": "foto de lado"}).get_json()["midia"]
        assert m3["tipo"] == "foto" and m3["descricao"] == "foto de lado"
        assert c.post(f"/vendas/{pid}/texto", json={"conteudo": "Amei!"}).status_code == 400
        assert c.post(f"/vendas/{pid}/texto", json={"conteudo": "Amei, uso todo dia", "descricao": "avaliação real de cliente"}).get_json()["midia"]["id"] == "T1"
        c.post(f"/vendas/{pid}/midia/M2", json={"descricao": "pessoa usando na academia", "usar": "ambos"})
        assert c.get(f"/vendas/{pid}/arquivo/M1").status_code == 200
        c.post(f"/vendas/{pid}/config", json={"tecnicas": ["urgencia", "percepcao_valor", "xpto"], "link_onde": "comentario",
                                               "preco_modo": "tela", "filtros": ["nao_publi", "aviso_afiliado"], "proibidos": "barato",
                                               "duracao_s": 45, "oferta": "cupom de 10% até domingo"})
        pr = c.post(f"/vendas/{pid}/prompt", json={"extra": "terminar com pergunta"}).get_json()["prompt"]
        assert "- M1 (foto): garrafa aberta mostrando a tampa" in pr
        assert "- M2 (foto): pessoa usando na academia | da página: Garrafa X na academia — Aguentou o treino todo gelada" in pr
        assert "T1 — avaliação real de cliente:\nAmei, uso todo dia" in pr
        assert "Urgência" in pr and "Percepção de valor" in pr and "xpto" not in pr
        assert "comentário fixado" in pr and "aparece só escrito na tela" in pr and "NUNCA use estas palavras/temas: barato" in pr
        assert "cupom de 10% até domingo" in pr and "Não invente" in pr and "~45 s" in pr and "terminar com pergunta" in pr
        # gratuito: sem preço
        c.post(f"/vendas/{pid}/config", json={"tipo_produto": "gratuito"})
        prg = c.post(f"/vendas/{pid}/prompt", json={}).get_json()["prompt"]
        assert "GRATUITO" in prg and "R$ 129,90" not in prg
        c.post(f"/vendas/{pid}/config", json={"tipo_produto": "pago"})
        c.post(f"/vendas/{pid}/produto", json={"link": "https://www.amazon.com.br/dp/B0X"})
        resposta = ("Claro! ```json\n" + json.dumps({
            "titulo_video": "A garrafa que não esquenta", "gancho": "Sua água esquenta no treino?",
            "roteiro": "Sua água esquenta no treino?\n[M2]\nEssa aqui aguenta 24 horas gelada.\n[M1] Olha a tampa. [M9] Corre.",
            "momentos": [{"midia": "M1", "trecho": "Olha a tampa.", "texto_na_tela": "R$ 129,90"}],
            "descricao": "Link: {LINK}", "titulos": ["A"], "hashtags": ["#garrafa"]}) + "\n```")
        rot = c.post(f"/vendas/{pid}/roteiro", json={"texto": resposta}).get_json()
        R = rot["roteiro"]
        assert any("M9" in a for a in R["avisos"])
        assert {m["midia"] for m in R["momentos"]} == {"M1", "M2"}
        assert next(m for m in R["momentos"] if m["midia"] == "M2")["trecho"].startswith("Essa aqui aguenta")
        assert "https://www.amazon.com.br/dp/B0X" in R["descricao"] and "associado da Amazon" in R["descricao"]
        assert rot["voz"] == "Sua água esquenta no treino?\nEssa aqui aguenta 24 horas gelada.\nOlha a tampa. Corre."
        voz = c.get(f"/gerar-voz?venda={pid}").get_data(as_text=True)
        assert "Essa aqui aguenta 24 horas gelada." in voz and f'name="venda_id" value="{pid}"' in voz and "[M1]" not in voz
        assert f'<option value="venda:{pid}" selected>' in c.get(f"/?venda={pid}").get_data(as_text=True)

        # ---- editor: projeto ligado ao vídeo
        job = {"job_id": "vd-job", "providers": ["pexels", "pixabay"], "media_library": []}
        assert A._ligar_venda(job, pid)
        assert len(job["media_library"]) == 3 and {it["venda_midia"] for it in job["media_library"]} == {"M1", "M2", "M3"}
        A._ligar_venda(job, pid)
        assert len(job["media_library"]) == 3  # não duplica
        bloco = A._com_produto(job, "PROMPT")
        assert bloco.startswith("PROMPT\n") and '"provider": "produto"' in bloco and "- M1 (foto): garrafa aberta" in bloco
        assert 'trecho sugerido: "Olha a tampa."' in bloco
        segs = [{"provider": "produto", "query": "m1", "start": 0, "end": 3},
                {"provider": "produto", "query": "M99", "start": 3, "end": 5, "visual": "pessoa bebendo água"},
                {"provider": "pexels", "query": "gym", "start": 5, "end": 8}]
        assert A._aplicar_produto(job, segs) == 1
        assert segs[0]["override_source"]["source"] == "local_file" and segs[0]["media_type"] == "image"
        assert segs[1]["provider"] == "pexels" and segs[1]["query"] == "pessoa bebendo água"  # ID inexistente: cai pros bancos
        assert "override_source" not in segs[2]
    finally:
        c.post(f"/vendas/{pid}/excluir")
    assert not os.path.isdir(os.path.join(A.BASE_DIR, "vendas", pid))


def test_zip_do_gerar_voz_leva_o_projeto(A, tmp_path):
    z = tmp_path / "n.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("info.json", json.dumps({"idioma": "pt", "venda_id": "abcdef0123"}))
    assert A._venda_do_zip(str(z)) == "abcdef0123"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("info.json", json.dumps({"idioma": "pt", "venda_id": "../x"}))
    assert A._venda_do_zip(str(z)) == ""


def test_submit_json_com_produto_vira_arquivo_local(A, tmp_path, monkeypatch):
    p = vd.criar(A.BASE_DIR, nome="t")
    try:
        os.makedirs(vd.pasta_midias(A.BASE_DIR, p["id"]), exist_ok=True)
        with open(os.path.join(vd.pasta_midias(A.BASE_DIR, p["id"]), "a.png"), "wb") as f:
            f.write(_png().getvalue())
        vd.adicionar_midia(p, tipo="foto", origem="pc", arquivo="a.png", descricao="produto de frente")
        vd.salvar(A.BASE_DIR, p)
        jid = "vd-submit"
        os.makedirs(A._job_dir(jid), exist_ok=True)
        A._JOBS[jid] = {"job_id": jid, "providers": ["pexels"], "total_duration": 8.0, "status": "aguardando_json",
                        "segments": [{"start": 0, "end": 8, "text": "x"}], "media_library": []}
        A._ligar_venda(A._JOBS[jid], p["id"])
        chamados = []
        monkeypatch.setattr(A, "_fetch_previews", lambda job_id, job, segs: chamados.append([s.override_source for s in segs]))
        r = A.app.test_client().post(f"/job/{jid}/submit-json", data={"ai_response": json.dumps({"segments": [
            {"start": 0, "end": 4, "provider": "produto", "query": "M1"}, {"start": 4, "end": 8, "provider": "pexels", "query": "gym"}]})})
        assert r.status_code == 302, r.get_data(as_text=True)[:500]
        seg = A._JOBS[jid]["pending_segments"][0]
        assert seg["override_source"]["value"].endswith("a.png") and seg["media_type"] == "image"
        assert chamados[0][0]["source"] == "local_file" and chamados[0][1] is None
    finally:
        vd.excluir(A.BASE_DIR, p["id"])
