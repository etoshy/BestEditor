"""v84_58 — chamadas (inscreva-se / venda) nunca viram busca de imagem, com ou sem IA."""
import chamadas as ch
from prompt_builder import VideoSegment


def test_reconhece_busca_de_chamada():
    for q in ("subscribe button animation", "like button and bell icon", "[[INSCREVA]]", "inscreva-se no canal", "link in the description",
              "buy now banner", "promo code"):
        assert ch.eh_busca_de_chamada(q), q
    for q in ("Columbine high school 1999", "police car at night", "coupon history 1900s", "comment section of a newspaper"):
        assert not ch.eh_busca_de_chamada(q), q


def test_limpar_buscas_herda_o_trecho_anterior():
    segs = [VideoSegment(start=0, end=5, provider="pexels", query="Columbine school"),
            VideoSegment(start=5, end=9, provider="pexels", query="subscribe button"),
            VideoSegment(start=9, end=14, provider="pexels", query="police car"),
            VideoSegment(start=14, end=18, provider="youtube", query="like button")]
    segs[0].alternativas = ["school building"]
    n = ch.limpar_buscas(segs, [{"tipo": "inscreva", "inicio": 9.5, "fim": 13.8, "texto": "deixa o like"}])
    assert n == 2 and [s.query for s in segs] == ["Columbine school", "Columbine school", "Columbine school", "like button"]
    assert segs[1].alternativas == ["school building"] and segs[1].busca_chamada == "subscribe button"
    d = [{"start": 0, "end": 3, "query": "subscribe", "alternativas": ["sunset beach", "like button"]}]
    ch.limpar_buscas(d)
    assert d[0]["query"] == "sunset beach"


def test_regra_no_prompt():
    b = ch.bloco_prompt_buscas([{"inicio": 80, "fim": 84}, {"inicio": 120, "fim": 120}])
    assert "NÃO são assunto do vídeo" in b and "01:20.0–01:24.0" in b and "02:00" not in b
    assert "01:20" not in ch.bloco_prompt_buscas([])


def test_submit_json_limpa(monkeypatch):
    import os
    import app as A
    A.app.config["TESTING"] = True
    jid = "chbusca"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "providers": ["pexels"], "total_duration": 10.0, "segments": [], "chamadas": [{"tipo": "inscreva", "inicio": 5, "fim": 10, "texto": "inscreva-se"}]}
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_youtube_buscar_pendentes", lambda *a, **k: None)
    r = A.app.test_client().post(f"/job/{jid}/submit-json", data={"ai_response": '[{"start":0,"end":5,"provider":"pexels","query":"ocean waves"},{"start":5,"end":10,"provider":"pexels","query":"subscribe button"}]'})
    assert r.status_code in (200, 302)
    assert [s["query"] for s in A._JOBS[jid]["pending_segments"]] == ["ocean waves", "ocean waves"]
