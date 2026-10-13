"""v84_92 — 🎬 sem a fonte "youtube" marcada, NADA vira clipe do YouTube: nem as [CENA n] de um projeto do 📝 Roteiro
do YouTube (escolhido ou vindo no .zip), nem os cortes reais — as cenas viram só contexto pros bancos marcados."""
import json
import os

import pytest

import roteiro_no_editor as rne
import roteiros_yt as ry
from prompt_builder import VideoSegment, build_prompt
from test_v84_roteiro_editor import _palavras, _projeto


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, base, providers, jid):
    p = _projeto(base)
    pal = _palavras(ry.roteiro_para_voz(p))
    os.makedirs(A._job_dir(jid), exist_ok=True)
    job = {"job_id": jid, "roteiro_id": p["id"], "word_timestamps": pal, "total_duration": len(pal) * 0.5,
           "providers": providers, "cutaway_suggestions": []}
    A._JOBS[jid] = job
    return job, pal


def test_bloco_do_roteiro_sem_youtube_e_so_contexto(tmp_path):
    p = _projeto(str(tmp_path))
    pal = _palavras(ry.roteiro_para_voz(p))
    cenas = rne.cenas_com_tempo(p, pal, len(pal) * 0.5)
    b = rne.bloco_prompt(p, cenas, com_youtube=False)
    assert "CENA 2 em ~" in b and "Série B" in b and "NÃO use" in b
    assert '"provider": "youtube"' not in b and "busca:" not in b
    assert '"provider": "youtube"' in rne.bloco_prompt(p, cenas)  # com a fonte marcada continua igual


def test_cenas_nao_viram_youtube_sem_a_fonte(A, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "BASE_DIR", str(tmp_path))
    job, pal = _job(A, str(tmp_path), ["pexels", "pixabay"], "sem-yt")
    prompt = A._com_produto(job, "PROMPT")
    assert "Cenas do roteiro" in prompt and '"provider": "youtube"' not in prompt
    dur = len(pal) * 0.5
    segs = [VideoSegment(start=k * 8.0, end=min(dur, k * 8.0 + 8), provider="pexels", query=f"q{k}") for k in range(int(dur // 8) + 1)]
    assert A._aplicar_cenas_do_roteiro(job, segs) == [] and all(s.provider == "pexels" for s in segs)
    job["pending_segments"] = [dict(s.to_dict(), provider="youtube") for s in segs]  # mesmo se algo marcasse youtube
    assert A._usar_links_do_roteiro("sem-yt", job) == 0


def test_com_a_fonte_marcada_continua_igual(A, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "BASE_DIR", str(tmp_path))
    job, pal = _job(A, str(tmp_path), ["pexels", "youtube"], "com-yt")
    dur = len(pal) * 0.5
    segs = [VideoSegment(start=k * 8.0, end=min(dur, k * 8.0 + 8), provider="pexels", query=f"q{k}") for k in range(int(dur // 8) + 1)]
    idx = A._aplicar_cenas_do_roteiro(job, segs)
    assert len(idx) == 2 and all(segs[i].provider == "youtube" for i in idx)
    assert A._tirar_youtube_desmarcado(job, segs) == 0


def test_trecho_youtube_vira_banco_marcado():
    import app as A
    segs = [VideoSegment(start=0, end=4, provider="youtube", query="trailer filme"),
            VideoSegment(start=4, end=8, provider="pexels", query="cidade")]
    assert A._tirar_youtube_desmarcado({"providers": ["wikipedia", "mixkit", "pexels"]}, segs) == 1
    assert (segs[0].provider, segs[0].media_type, segs[0].query) == ("mixkit", "video", "trailer filme")
    s = [VideoSegment(start=0, end=4, provider="youtube", query="x")]
    A._tirar_youtube_desmarcado({"providers": ["google"]}, s)
    assert (s[0].provider, s[0].media_type) == ("google", "image")  # só fonte de foto marcada


def test_corte_real_sem_youtube_e_so_pra_enviar_o_clipe():
    segs = [{"start": 0.0, "end": 4.0, "text": "O prefeito anunciou a tarifa zero."}]
    sem, com = build_prompt(segs, providers=["pexels"]), build_prompt(segs, providers=["pexels", "youtube"])
    assert "cutaway_suggestions" in sem and "NÃO pesquisa o clipe" in sem and "pesquisa esse termo sozinho" not in sem
    assert "pesquisa esse termo sozinho" in com and "NÃO pesquisa o clipe" not in com


def test_resposta_da_ia_sem_youtube_nao_gera_cenas_nem_cortes_do_youtube(A, tmp_path, monkeypatch):
    """Fluxo real: colar o JSON da 1ª IA num vídeo com projeto do Roteiro do YouTube e SEM a fonte youtube."""
    monkeypatch.setattr(A, "BASE_DIR", str(tmp_path))
    job, pal = _job(A, str(tmp_path), ["pexels"], "fluxo-sem-yt")
    dur = len(pal) * 0.5
    job.update(status="aguardando_json", segments=[{"start": 0.0, "end": dur, "text": "x"}], prompt="P", interval_seconds=8)
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_youtube_buscar_pendentes", lambda *a, **k: None)
    n = int(dur // 8) + 1
    resposta = {"segments": [{"start": k * 8.0, "end": min(dur, k * 8.0 + 8), "provider": "pexels", "query": f"q{k}"}
                             for k in range(n)],
                "cutaway_suggestions": [{"insertion_point": 3.0, "description": "coletiva real", "query": "coletiva"}]}
    r = A.app.test_client().post(f"/job/fluxo-sem-yt/submit-json", data={"ai_response": json.dumps(resposta)})
    assert r.status_code in (200, 302), r.get_data(as_text=True)[:500]
    assert all(s["provider"] != "youtube" for s in job["pending_segments"])
    # o corte real continua (pra você enviar o clipe), mas nada é pesquisado no YouTube
    assert [c["description"] for c in job["cutaway_suggestions"] if not c.get("chamada")] == ["coletiva real"]
    assert job["youtube_itens"] == []
