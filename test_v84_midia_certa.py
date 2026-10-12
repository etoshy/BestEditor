"""v84_70 — 🧭 cada trecho vai pra fonte certa e 🃏 sem imagem boa vira cartão de texto (nunca a "menos pior")."""
import os

import pytest

import video_assembler as va
from prompt_builder import VideoSegment


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _sg(provider="pexels", media="video"):
    return VideoSegment(start=0.0, end=4.0, provider=provider, query="q", media_type=media)


def test_rotas(A):
    job = {"providers": ["pexels", "pixabay", "bing", "youtube", "flow", "wikipedia"]}
    sg = _sg()
    assert A._rotear_trecho(job, sg, {"midia": "youtube", "real": True})["ia_rota"] == "youtube" and sg.provider == "youtube"
    sg = _sg()
    r = A._rotear_trecho(job, sg, {"midia": "video", "real": True})
    assert r == {"provider": "bing", "media_type": "image", "ia_rota": "foto_real"} and sg.media_type == "image"
    sg = _sg()
    assert A._rotear_trecho(job, sg, {"midia": "ia", "real": False})["provider"] == "flow"
    sg = _sg()
    assert A._rotear_trecho(job, sg, {"midia": "cartao"}) == {"ia_rigoroso": True, "ia_rota": "abstrato"} and sg.provider == "pexels"
    sg = _sg("bing", "image")
    assert A._rotear_trecho(job, sg, {"midia": "video", "real": False})["provider"] == "pexels"
    sg = _sg()
    assert A._rotear_trecho(job, sg, {"midia": "video", "real": False}) == {} and sg.provider == "pexels"
    # só entre os bancos LIGADOS no projeto
    sg = _sg()
    assert A._rotear_trecho({"providers": ["pexels"]}, sg, {"midia": "youtube", "real": True}) == {} and sg.provider == "pexels"
    sg = _sg()
    assert A._rotear_trecho({"providers": ["pexels", "wikipedia"]}, sg, {"midia": "foto", "real": True})["provider"] == "wikipedia"


def test_buscas_melhores_le_real_e_frase(monkeypatch):
    import ia_midia
    monkeypatch.setattr(ia_midia.ia, "ativo", lambda r: True)
    monkeypatch.setattr(ia_midia.ia, "chamar", lambda *a, **k: {"trechos": [
        {"n": 1, "buscas": ["Ted Bundy 1979 trial"], "midia": "foto", "real": True, "visual": "o julgamento",
         "frase_tela": "um tribunal inteiro hipnotizado por um assassino confesso de verdade"}]})
    r = ia_midia.buscas_melhores([{"n": 1, "fala": "x"}], {})
    assert r[1]["real"] is True and len(r[1]["frase_tela"].split()) == 10 and r[1]["midia"] == "foto"


def _preview(monkeypatch, notas, rigoroso=False, cartao_ligado=True):
    cands = [{"thumbnail": f"t{k}", "url": f"u{k}", "label": f"c{k}"} for k in range(len(notas))]
    monkeypatch.setattr(va, "search_candidates", lambda *a, **k: [dict(c) for c in cands])
    monkeypatch.setattr(va, "_ia_pode", lambda r: r != "nova_busca" and (cartao_ligado or r != "cartao"))
    monkeypatch.setattr(va, "_ia_cfg", lambda: {"nota_minima": 7, "candidatos": 10})
    monkeypatch.setattr(va, "julgar_candidatos_ia", lambda cs, ctx, q, **k: {
        "lista": sorted([dict(c, ia_nota=n, ia_motivo="m") for c, n in zip(cs, notas)], key=lambda c: -c["ia_nota"]), "nova_busca": ""})
    sg = _sg()
    sg._rigoroso = rigoroso
    return va.fetch_segment_preview_lightweight(sg, site_cfg={"provider_priority": ["pexels"]}, ia_ctx={"fala": "f"})


def test_tudo_reprovado_vira_cartao(monkeypatch):
    r = _preview(monkeypatch, [3, 2, 4])
    assert r["cartao"] and not r["ok"] and r["ia_nota"] == 4 and "nenhuma imagem boa" in r["error"]
    r = _preview(monkeypatch, [3, 2, 4], cartao_ligado=False)  # desligado: a menos pior com ⚠, como antes
    assert r["ok"] and r["label"].startswith("⚠")
    r = _preview(monkeypatch, [6, 3])  # nota 5-6 num trecho comum: usa com ⚠
    assert r["ok"] and r["ia_nota"] == 6
    r = _preview(monkeypatch, [6, 3], rigoroso=True)  # trecho abstrato: só o BOM passa
    assert r.get("cartao") and r["ia_nota"] == 6
    r = _preview(monkeypatch, [8, 3], rigoroso=True)
    assert r["ok"] and r["ia_nota"] == 8


def test_cartao_no_trecho(A, monkeypatch):
    import dp_destaques
    jid = "cartao-t"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    job = {"job_id": jid, "orientation": "16:9", "destaques": [{"id": "x", "estilo": "capitulo", "start": 9, "end": 10, "texto": "outro"}],
           "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "q"}]}
    sg = _sg()
    sg._frase_tela = "a mentira que durou trinta anos"
    p = A._cartao_no_trecho(jid, job, 0, sg, "fala qualquer", "nenhuma imagem boa (melhor nota 3)")
    assert p["ok"] and p["cartao"] and os.path.exists(p["thumbnail_path"]) and "🃏" in p["label"]
    pend = job["pending_segments"][0]
    assert pend["override_source"]["cartao"] and pend["media_type"] == "image" and pend["cartao"]["texto"] == "a mentira que durou trinta anos"
    d = [d for d in job["destaques"] if d.get("origem") == "cartao"]
    assert len(d) == 1 and d[0]["avulso"] and (d[0]["start"], d[0]["end"]) == (0.0, 4.0) and dp_destaques.estilo(d[0]["estilo"])
    assert job["destaques"][0]["origem"] == "cartao"  # ordenado pelo tempo
    A._cartao_no_trecho(jid, job, 0, sg, "", "de novo")  # refazer não duplica
    assert len([d for d in job["destaques"] if d.get("origem") == "cartao"]) == 1
    # sem frase da IA: o começo da fala
    sg2 = _sg()
    A._cartao_no_trecho(jid, job, 0, sg2, "um dois três quatro cinco seis sete oito nove dez", "x")
    texto = [d for d in job["destaques"] if d.get("origem") == "cartao"][0]["texto"]
    assert texto.startswith("um dois") and len(texto.split()) <= 8


def test_estilo_do_cartao_usa_a_direcao(A, monkeypatch):
    import dp_destaques
    import dp_direcao
    tela = next(k for k, v in dp_destaques.catalogo().items()
                if (v.get("cena") or {}).get("assumeTela") and v.get("forma") == "centro_frase")
    monkeypatch.setattr(dp_direcao, "direcao", lambda did, kit=None: {"destaques": {"estilos": ["branco", tela]}})
    assert A._estilo_do_cartao({"editor_defaults": {"direcao": "x"}}) == tela
    monkeypatch.setattr(dp_direcao, "direcao", lambda did, kit=None: None)
    assert A._estilo_do_cartao({}) in A._CARTAO_PADRAO


def test_form_guarda_o_cartao(A):
    from werkzeug.datastructures import MultiDict
    import json
    job = {}
    A._destaques_do_form(job, MultiDict({"destaques_json": json.dumps([
        {"id": "a", "estilo": "capitulo", "start": 0, "end": 4, "texto": "x", "avulso": True, "origem": "cartao", "trecho": 2}])}))
    assert job["destaques"][0]["origem"] == "cartao" and job["destaques"][0]["trecho"] == 2


def test_prompt_de_edicao_mostra_o_cartao():
    import prompt_edicao as pe
    job = {"total_duration": 8.0, "pending_segments": [{"start": 0.0, "end": 4.0, "provider": "pexels", "query": "traição"},
                                                       {"start": 4.0, "end": 8.0, "provider": "pexels", "query": "q"}]}
    segs = [dict(job["pending_segments"][0], override_source={"source": "local_file", "value": "/x.png", "cartao": True}),
            job["pending_segments"][1]]
    t = pe.montar_prompt(job, {"direcao": "sys_tudo", "segmentos": segs})
    assert "🃏 cartão de texto (nenhuma imagem boa pra 'traição')" in t
