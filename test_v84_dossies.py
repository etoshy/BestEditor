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
