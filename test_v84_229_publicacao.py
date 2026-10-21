"""v84_229: 📣 aba Publicação — títulos/descrições/tags/hashtags com alternativas e capas (ideias, referência, Flow)."""
import io
import os

import pytest
from PIL import Image

import publicacao as pub


@pytest.fixture
def cena(monkeypatch, tmp_path):
    import app as A
    import ia_servico
    import flow_estudio as FE
    import flow_lote
    from test_v84_184_personagens_flow import LoteFalso
    jid = "pub_" + os.urandom(3).hex()
    jd = tmp_path / "job"
    jd.mkdir()
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "language": "de", "total_duration": 600,
                    "pending_segments": [], "word_timestamps": [{"word": w, "start": k, "end": k + .5} for k, w in
                                                               enumerate("Was passiert wenn man in ein Schwarzes Loch fällt".split())]}
    monkeypatch.setattr(A, "_job_dir", lambda j: str(jd))
    monkeypatch.setattr(pub, "personagens", lambda job, base: [{"slug": "vanta", "nome": "Vanta", "visual_en": "goth girl",
                                                                "personalidade": "irônica", "ref": str(_png(tmp_path / "v.png"))}])
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda r, c=None: None)
    chamadas = []

    def chamar(rec, system, conteudo, schema=None, **k):
        chamadas.append(conteudo)
        props = (schema or {}).get("properties") or {}
        if "capas" in props:
            return {"capas": [{"ideia": f"ideia {i}", "texto": "SCHWARZES LOCH", "prompt": f"black hole scene {i}",
                               "personagem": "vanta" if i == 0 else "x"} for i in range(3)]}
        if "tem_pessoa" in props:
            return {"ideia": "ela na frente do buraco negro", "tem_pessoa": True, "texto_original": "BLACK HOLE",
                    "texto": "SCHWARZES LOCH", "prompt": "the character in front of a black hole"}
        n = len(chamadas)
        return {t: [f"{t} {n}-{i}" for i in range(3)] for t in props}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    monkeypatch.setattr(ia_servico, "imagem_bloco", lambda c, l=320, timeout=12.0: {"type": "image"})
    falso = LoteFalso()
    monkeypatch.setattr(flow_lote, "lote", lambda: falso)
    gal = tmp_path / "gal"
    gal.mkdir()
    monkeypatch.setattr(FE, "pasta_galeria", lambda: str(gal))
    yield A, jid, falso, gal, chamadas
    A._JOBS.pop(jid, None)
    import shutil
    shutil.rmtree(pub.pdir_de(A.BASE_DIR, jid), ignore_errors=True)


def _png(cam, cor=(200, 50, 50, 255)):
    Image.new("RGBA", (60, 90), cor).save(cam)
    return cam


def test_textos_e_alternativas(cena):
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/publicacao/textos", json={}).get_json()
    assert d["textos"]["titulos"] == ["titulos 1-0", "titulos 1-1", "titulos 1-2"] and d["idioma_video"]["codigo"] == "de"
    assert all(h.startswith("#") for h in d["textos"]["hashtags"])
    assert "Deutsch" in chamadas[0] or "alem" in chamadas[0].lower() or "de" in chamadas[0]
    d = c.post(f"/job/{jid}/publicacao/textos", json={"tipos": ["titulos"], "mais": True}).get_json()
    assert len(d["textos"]["titulos"]) == 6 and len(d["textos"]["tags"]) == 3  # só os títulos ganharam alternativas
    assert "JÁ EXISTEM" in chamadas[-1] and "titulos 1-0" in chamadas[-1]
    d = c.post(f"/job/{jid}/publicacao/textos/titulos/0", json={"valor": "Mein Titel"}).get_json()
    assert d["textos"]["titulos"][0] == "Mein Titel"
    d = c.post(f"/job/{jid}/publicacao/textos/titulos/0", json={"apagar": True}).get_json()
    assert len(d["textos"]["titulos"]) == 5


def test_capas_ideias_referencia_e_flow(cena, tmp_path):
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/publicacao/capas/ideias", json={}).get_json()
    assert len(d["capas"]) == 3 and d["capas"][0]["personagem"] == "vanta" and d["capas"][1]["personagem"] == ""
    # capa de referência: a pessoa vira a nossa personagem, o texto no idioma do vídeo, e já vai pro Flow
    b = io.BytesIO()
    Image.new("RGB", (160, 90), (10, 10, 40)).save(b, "PNG")
    b.seek(0)
    d = c.post(f"/job/{jid}/publicacao/capas/referencia", data={"imagem": (b, "ref.png"), "personagem": "vanta", "gerar": "1"},
               content_type="multipart/form-data").get_json()
    nova = next(x for x in d["capas"] if x["n"] == d["capa_nova"])
    assert nova["da_referencia"] and nova["texto"] == "SCHWARZES LOCH" and nova["texto_original"] == "BLACK HOLE"
    assert nova["status"] == "fila" and nova["url_ref"]
    j = falso.fila[-1]
    assert "LEFT = the CHARACTER" in j["prompt"] and "NO text" in j["prompt"] and j["proporcao"] == "16:9"
    assert Image.open(j["referencia_arquivo"]).width > Image.open(j["referencia_arquivo"]).height  # personagem + referência
    # o Flow terminou: a capa ganha a imagem e a versão final com o texto
    Image.new("RGB", (1280, 720), (30, 30, 90)).save(gal / "r.png")
    j.update(estado="ok", resultados=[{"tipo": "imagem", "arquivo": "r.png"}])
    d = c.get(f"/job/{jid}/publicacao").get_json()
    nova = next(x for x in d["capas"] if x["n"] == nova["n"])
    assert nova["status"] == "pronta" and nova["url_final"]
    r = c.get(nova["url_final"])
    assert r.status_code == 200 and Image.open(io.BytesIO(r.data)).size == (1280, 720)
    # mudar o texto refaz a final; apagar
    d = c.post(f"/job/{jid}/publicacao/capas/{nova['n']}", json={"texto": "NIE ZURÜCK"}).get_json()
    assert next(x for x in d["capas"] if x["n"] == nova["n"])["url_final"]
    d = c.post(f"/job/{jid}/publicacao/capas/1", json={"apagar": True}).get_json()
    assert all(x["n"] != 1 for x in d["capas"])


def test_historico_sem_o_projeto(cena):
    """🗂 v84_230: a publicação fica em publicacoes/<id> com o contexto guardado — apagar o projeto não apaga, e dá pra
    continuar gerando pela página 📣 Publicações."""
    A, jid, falso, gal, chamadas = cena
    c = A.app.test_client()
    c.post(f"/job/{jid}/publicacao/textos", json={})
    assert os.path.isfile(os.path.join(pub.pdir_de(A.BASE_DIR, jid), "ctx.json"))
    html = c.get("/publicacoes").get_data(as_text=True)
    assert f"/publicacoes/{jid}" in html
    A._JOBS.pop(jid)  # o projeto foi apagado
    d = c.get(f"/publicacoes/{jid}/api").get_json()
    assert d["textos"]["titulos"] and d["meta"]["tem_projeto"] is False and "Schwarzes" in d["narracao"]
    d = c.post(f"/publicacoes/{jid}/api/textos", json={"tipos": ["hashtags"], "mais": True}).get_json()
    assert len(d["textos"]["hashtags"]) == 6 and "Schwarzes Loch" in chamadas[-1]  # gerou com a narração guardada
    pagina = c.get(f"/publicacoes/{jid}").get_data(as_text=True)
    assert "projeto foi apagado" in pagina and 'data-api="/publicacoes/' in pagina
    assert "projeto apagado" in c.get("/publicacoes").get_data(as_text=True)
    r = c.post(f"/publicacoes/{jid}/excluir")
    assert r.status_code == 302 and not os.path.isdir(pub.pdir_de(A.BASE_DIR, jid))


def test_migra_da_pasta_do_projeto(tmp_path):
    jd, pd = tmp_path / "job", tmp_path / "pub"
    (jd / "publicacao").mkdir(parents=True)
    pub.salvar(str(jd / "publicacao"), {"textos": {"titulos": ["a"]}, "capas": [{"n": 1, "final": str(jd / "publicacao" / "x.jpg")}]})
    pub.migrar(str(jd), str(pd))
    d = pub.carregar(str(pd))
    assert d["textos"]["titulos"] == ["a"] and d["capas"][0]["final"].startswith(str(pd))
