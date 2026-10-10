"""
🕵️ Modelos de vídeo (True Crime): tema + fontes (matérias de qualquer site:
título, subtítulos, texto e imagens com legenda) + materiais -> prompt no formato
do modelo -> JSON (títulos, ideias, descrição, capítulos, roteiro) -> Gerar voz
(capítulos com o tempo real) -> Novo vídeo com o projeto (provider "material").
"""
import io
import json
import os
import threading
import time
import zipfile

import pytest

import dossies as ds

MATERIA = """<html><head><title>Caso X | Jornal</title>
<meta property="og:title" content="O caso X: o que se sabe"><meta property="og:description" content="Linha fina do caso">
<meta property="og:image" content="/img/capa.jpg"><meta property="og:site_name" content="Jornal Teste">
<meta name="author" content="Fulana Repórter"><meta property="article:published_time" content="2021-03-04T10:00:00Z"></head>
<body><nav><a>Home</a></nav><header><img src="/img/logo.png" alt="logo"></header>
<article><h1>O caso X: o que se sabe até agora</h1>
<p>Maria, 34 anos, desapareceu na noite de 12 de março de 2020 depois de sair do trabalho em Campinas.</p>
<figure><img data-src="/img/casa.jpg" srcset="/img/casa-300.jpg 300w, /img/casa-1200.jpg 1200w" alt="casa"><figcaption>A casa onde Maria morava</figcaption></figure>
<h2>A investigação</h2>
<p>A polícia ouviu 15 testemunhas nas primeiras duas semanas de investigação do caso.</p>
<p>Leia também: outro caso</p>
<blockquote>Nunca vamos desistir, disse a irmã de Maria em entrevista.</blockquote>
<img src="/img/icone.png" width="16" height="16">
<h2>O julgamento</h2><p>O acusado foi julgado em 2022 e condenado a 20 anos pelo tribunal do júri.</p>
</article><aside class="related"><p>Notícia relacionada qualquer que não deveria entrar no texto.</p></aside></body></html>"""


def test_le_materia_com_secoes_e_imagens():
    d = ds.ler_materia(MATERIA, "https://jornal.com/caso-x")
    assert d["titulo"] == "O caso X: o que se sabe até agora" and d["linha_fina"] == "Linha fina do caso"
    assert d["autor"] == "Fulana Repórter" and d["data"].startswith("2021-03-04") and d["site"] == "Jornal Teste"
    assert [s["titulo"] for s in d["secoes"]] == ["", "A investigação", "O julgamento"]
    assert "15 testemunhas" in d["texto"] and "## O julgamento" in d["texto"] and "“Nunca vamos desistir" in d["texto"]
    assert "Leia também" not in d["texto"] and "relacionada" not in d["texto"]
    urls = [i["url"] for i in d["imagens"]]
    assert urls[0] == "https://jornal.com/img/capa.jpg"
    assert "https://jornal.com/img/casa-1200.jpg" in urls  # o maior do srcset
    assert next(i for i in d["imagens"] if i["url"].endswith("casa-1200.jpg"))["legenda"] == "A casa onde Maria morava"
    assert not any("logo" in u or "icone" in u for u in urls)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from flask import Flask, Response
    from PIL import Image

    def jpg(w, h, cor):
        b = io.BytesIO()
        Image.new("RGB", (w, h), cor).save(b, "JPEG")
        return b.getvalue()
    grande, pequena = jpg(800, 500, (90, 20, 20)), jpg(60, 40, (0, 0, 0))
    app = Flask("jornal_falso")

    @app.route("/caso-x")
    def materia():
        return MATERIA

    @app.route("/img/<nome>")
    def img(nome):
        return Response(pequena if "300" in nome else grande, mimetype="image/jpeg")

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


def _espera_fontes(c, pid, seg=20):
    for _ in range(int(seg / 0.2)):
        d = c.get(f"/modelos-video/{pid}/dados").get_json()
        if d["fontes"] and all(f["estado"] in ("pronta", "erro") for f in d["fontes"]):
            return d
        time.sleep(0.2)
    raise AssertionError("fontes não terminaram")


def test_fluxo_completo(A, site):
    c = A.app.test_client()
    r = c.post("/modelos-video/novo", data={"tema": "O caso X", "modelo": "true_crime", "fontes": site + "/caso-x\nnão é link"})
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        d = _espera_fontes(c, pid)
        f = d["fontes"][0]
        assert f["estado"] == "pronta" and f["titulo"].startswith("O caso X") and f["imagens"] == 2  # capa + casa (ícone fora)
        imgs = [m for m in d["midias"] if m["fonte"] == "F1"]
        casa = next(m for m in imgs if m["legenda"] == "A casa onde Maria morava")
        assert casa["id"].startswith("I") and casa["url_arquivo"] and casa["og"]["titulo"].startswith("O caso X")
        assert c.post(f"/modelos-video/{pid}/fontes", json={"urls": site + "/caso-x"}).get_json()["erros"]  # repetida
        assert "Modelos de vídeo" in c.get("/modelos-video").get_data(as_text=True)
        assert "Fontes (matérias" in c.get(f"/modelos-video/{pid}").get_data(as_text=True)
        # materiais meus
        from PIL import Image
        def png():
            b = io.BytesIO()
            Image.new("RGB", (400, 300), (1, 2, 3)).save(b, "PNG")
            b.seek(0)
            return b
        assert c.post(f"/modelos-video/{pid}/midia", data={"arquivo": (png(), "x.png")}, content_type="multipart/form-data").status_code == 400
        b = png()
        meu = c.post(f"/modelos-video/{pid}/midia", data={"arquivo": (b, "x.png"), "descricao": "foto da delegacia"},
                     content_type="multipart/form-data").get_json()["midia"]
        tx = c.post(f"/modelos-video/{pid}/texto", json={"conteudo": "12/03 21h saiu do trabalho", "descricao": "linha do tempo"}).get_json()["midia"]
        assert tx["id"] == "T1"
        c.post(f"/modelos-video/{pid}/config", json={"formato": "misterio", "minutos": 12, "tom": "sóbrio"})
        pr = c.post(f"/modelos-video/{pid}/prompt", json={}).get_json()["prompt"]
        assert "## Tema\nO caso X" in pr and "Mistério não resolvido" in pr and "~12 min (~1800 palavras)" in pr
        assert "Presunção de inocência" in pr and "### F1 — O caso X" in pr and "15 testemunhas" in pr and "Linha fina: Linha fina do caso" in pr
        assert f"- {casa['id']} (foto, F1): A casa onde Maria morava" in pr and f"- {meu['id']} (foto): foto da delegacia" in pr
        assert "### T1 — linha do tempo\n12/03 21h saiu do trabalho" in pr and "Tom: sóbrio" in pr
        resp = json.dumps({
            "titulos": ["O que aconteceu com Maria?"], "ideias": ["thumb da casa"],
            "descricao": "Em 2020, Maria desapareceu em Campinas.",
            "capitulos": [{"titulo": "A noite", "comeca_em": "Na noite de 12 de março"},
                          {"titulo": "A investigação", "comeca_em": "A polícia ouviu quinze testemunhas"}],
            "roteiro": f"Na noite de 12 de março de 2020, Maria saiu do trabalho e nunca chegou em casa.\n[{casa['id']}]\n"
                       + "Essa era a casa dela. " * 30 + "\nA polícia ouviu quinze testemunhas nas duas primeiras semanas. [I99] Fim.",
            "momentos": [], "tags": ["true crime"], "fontes_usadas": ["F1"], "observacoes": "conferir a data"})
        R = c.post(f"/modelos-video/{pid}/resultado", json={"texto": resp}).get_json()["projeto"]
        res = R["resultado"]
        assert any("I99" in a for a in res["avisos"]) and res["momentos"][0]["midia"] == casa["id"]
        assert "[" not in res["roteiro_final"] and res["capitulos"][0]["segundos"] == 0 and res["capitulos"][1]["posicao"] > 0.5
        assert R["descricao_pronta"].startswith("Em 2020") and "0:00 A noite" in R["descricao_pronta"]
        assert "Fontes:\n- O caso X" in R["descricao_pronta"] and site + "/caso-x" in R["descricao_pronta"]
        voz = c.get(f"/gerar-voz?dossie={pid}").get_data(as_text=True)
        assert "Essa era a casa dela." in voz and f'name="dossie_id" value="{pid}"' in voz
        # tempo real dos capítulos depois do TTS
        palavras = [{"word": w, "start": i * 0.4} for i, w in enumerate(res["roteiro_final"].split())]
        res2 = ds.aplicar_tempos_do_audio(A.BASE_DIR, pid, palavras, len(palavras) * 0.4)
        k = res["roteiro_final"].split().index("polícia") - 1
        assert res2["capitulos"][0]["segundos_audio"] == 0 and abs(res2["capitulos"][1]["segundos_audio"] - k * 0.4) < 1.0
        assert f'<option value="dossie:{pid}" selected>' in c.get(f"/?dossie={pid}").get_data(as_text=True)
        # editor
        job = {"job_id": "ds-job", "providers": ["pexels"], "media_library": []}
        assert A._ligar_projeto(job, "dossie", pid) and job["dossie_id"] == pid and "venda_id" not in job
        assert len(job["media_library"]) == 3
        bloco = A._com_produto(job, "P")
        assert '"provider": "material"' in bloco and f'- {casa["id"]} (foto): A casa onde Maria morava' in bloco
        assert 'trecho sugerido: "Essa era a casa dela.' in bloco
        segs = [{"provider": "material", "query": casa["id"], "start": 0, "end": 3}, {"provider": "material", "query": "I77", "start": 3, "end": 5}]
        assert A._aplicar_produto(job, segs) == 1 and segs[0]["override_source"]["source"] == "local_file"
        assert segs[1]["provider"] == "pexels"
        assert A._provider_do_projeto(job) == ["material"]
    finally:
        c.post(f"/modelos-video/{pid}/excluir")
    assert not os.path.isdir(os.path.join(A.BASE_DIR, "dossies", pid))


def test_zip_leva_o_modelo(A, tmp_path):
    z = tmp_path / "n.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("info.json", json.dumps({"idioma": "pt", "dossie_id": "0123456789"}))
    assert A._projeto_do_zip(str(z)) == ("dossie", "0123456789") and A._venda_do_zip(str(z)) == ""


def test_prompt_pede_fonte_ou_texto():
    p = {"tema": "Caso Y", "config": {}, "fontes": [], "midias": [], "roteiro_base": ""}
    with pytest.raises(ds.DossieError, match="inventaria"):
        ds.prompt_roteiro(p)
    p["roteiro_base"] = "minhas anotações"
    assert "minhas anotações" in ds.prompt_roteiro(p)


# ------------------------------------------------------------------ fontes por arquivo + filtros + produto
def _pdf_simples(caminho, paginas):
    """PDF mínimo com texto (uma página por item de `paginas`)."""
    objs, kids = [], []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(None)  # pages, depois
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for txt in paginas:
        stream = f"BT /F1 12 Tf 72 720 Td ({txt}) Tj ET".encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        cont = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {cont} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode())
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    open(caminho, "wb").write(out)


def test_le_arquivos_de_fonte(tmp_path):
    pdf = tmp_path / "livro.pdf"
    _pdf_simples(str(pdf), ["Capitulo um: o comeco do caso.", "Pagina dois: a investigacao.", "Pagina tres: o juri."])
    d = ds.ler_arquivo(str(pdf), "2-3")
    assert "investigacao" in d["texto"] and "comeco" not in d["texto"] and "[pág. 2]" in d["texto"] and "usadas: 2-3" in d["site"]
    assert "comeco" in ds.ler_arquivo(str(pdf))["texto"]
    docx = tmp_path / "notas.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Linha do tempo</w:t></w:r></w:p>'
                   '<w:p><w:r><w:t>12/03: ela saiu do trabalho.</w:t></w:r></w:p></w:body></w:document>')
    d = ds.ler_arquivo(str(docx))
    assert d["secoes"][0]["titulo"] == "Linha do tempo" and "ela saiu" in d["texto"]
    ep = tmp_path / "livro.epub"
    with zipfile.ZipFile(ep, "w") as z:
        z.writestr("OEBPS/content.opf", '<package><metadata><dc:title>O Livro do Caso</dc:title></metadata><manifest>'
                   '<item id="c1" href="c1.xhtml"/><item id="c2" href="c2.xhtml"/></manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/c1.xhtml", "<html><body><h1>Capítulo 1</h1><p>Era uma noite fria.</p></body></html>")
        z.writestr("OEBPS/c2.xhtml", "<html><body><h1>Capítulo 2</h1><p>O detetive chegou.</p></body></html>")
    d = ds.ler_arquivo(str(ep))
    assert d["titulo"] == "O Livro do Caso" and d["texto"].index("noite fria") < d["texto"].index("detetive")
    srt = tmp_path / "leg.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nOlá pessoal\n\n2\n00:00:02,500 --> 00:00:04,000\nhoje o caso\n", encoding="utf-8")
    assert ds.ler_arquivo(str(srt))["texto"].split() == ["Olá", "pessoal", "hoje", "o", "caso"]


def test_arquivo_filtros_marcas_produto_e_edicao(A, tmp_path):
    c = A.app.test_client()
    p = ds.criar(A.BASE_DIR, tema="O caso Y", modelo="true_crime")
    try:
        pdf = tmp_path / "doc.pdf"
        _pdf_simples(str(pdf), ["Pagina um do processo.", "Pagina dois do processo."])
        r = c.post(f"/modelos-video/{p['id']}/fonte-arquivo", data={"arquivo": (open(pdf, "rb"), "processo.pdf"), "paginas": "2"},
                   content_type="multipart/form-data")
        assert r.status_code == 200
        d = _espera_fontes(c, p["id"])
        f = d["fontes"][0]
        assert f["estado"] == "pronta" and "dois" in f["texto"] and "um do" not in f["texto"] and f["arquivo"].endswith("processo.pdf")
        assert c.post(f"/modelos-video/{p['id']}/fonte-arquivo", data={"arquivo": (io.BytesIO(b"x"), "a.exe")},
                      content_type="multipart/form-data").status_code == 400
        c.post(f"/modelos-video/{p['id']}/config", json={"sugerir_produto": True})
        pr = c.post(f"/modelos-video/{p['id']}/prompt", json={}).get_json()["prompt"]
        assert "(arquivo: F1_processo.pdf)" in pr and "Pagina dois do processo" in pr
        assert "experiências e histórias pessoais deles" in pr and "[[VENDA]] = momento de anúncio" in pr and "PRODUTO SUGERIDO" in pr
        assert '"produto_sugerido"' in pr
        c.post(f"/modelos-video/{p['id']}/config", json={"sem_experiencias": False, "marcar_chamadas": False, "sugerir_produto": False})
        pr2 = c.post(f"/modelos-video/{p['id']}/prompt", json={}).get_json()["prompt"]
        assert "histórias pessoais deles" not in pr2 and "[[VENDA]] = momento" not in pr2 and "PRODUTO SUGERIDO" not in pr2
        resp = json.dumps({"titulos": ["T"], "descricao": "D", "capitulos": [{"titulo": "A", "comeca_em": "Tudo começou"}],
                           "roteiro": "Tudo começou numa noite.\n\n[[INSCREVA]]\n\nO processo andou.\n\n[[VENDA]]\n\nFim.",
                           "produto_sugerido": {"nome": "Livro: O caso Y", "por_que": "aprofunda o caso", "busca": "livro caso y",
                                                "chamada": "Quer saber tudo? O livro conta."}})
        R = c.post(f"/modelos-video/{p['id']}/resultado", json={"texto": resp}).get_json()["projeto"]["resultado"]
        assert R["chamadas"] == {"inscreva": 1, "venda": 1} and R["produto_sugerido"]["nome"] == "Livro: O caso Y"
        assert "[[VENDA]]" in R["roteiro_final"]  # a marca vai pro Gerar voz (vira a pausa do vídeo de venda)
        novo = "Tudo começou numa noite.\n\n[[VENDA]]\n\nO processo andou.\n\nFim."
        R2 = c.post(f"/modelos-video/{p['id']}/roteiro-editado", json={"roteiro": novo}).get_json()["projeto"]["resultado"]
        assert R2["chamadas"] == {"inscreva": 0, "venda": 1} and R2["titulos"] == ["T"] and R2["produto_sugerido"]["nome"].startswith("Livro")
        v = c.post(f"/modelos-video/{p['id']}/produto-para-venda", json={}).get_json()
        assert v["url"].startswith("/vendas/") and "amazon.com.br/s?k=livro+caso+y" in v["amazon"]
        import vendas as vd
        vp = vd.carregar(A.BASE_DIR, v["url"].split("/")[-1])
        assert vp["produto"]["titulo"] == "Livro: O caso Y" and vp["midias"][0]["tipo"] == "texto"
        vd.excluir(A.BASE_DIR, vp["id"])
        c.delete(f"/modelos-video/{p['id']}/fonte/F1")
        assert not os.listdir(os.path.join(A.BASE_DIR, "dossies", p["id"], "fontes"))
    finally:
        ds.excluir(A.BASE_DIR, p["id"])
