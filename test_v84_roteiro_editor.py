"""v84_71 — 📝 projeto do Roteiro do YouTube no editor: cada [CENA n] vira trecho do YouTube no ponto certo."""
import os

import pytest

import roteiro_no_editor as rne
import roteiros_yt as ry


def _projeto(base):
    p = ry.criar_projeto(base, "https://www.youtube.com/watch?v=abcdefghijk")
    blocos = []
    for k in range(1, 4):
        blocos.append(" ".join(f"intro{k} palavra{j}" for j in range(30)))
        blocos.append(f"[CENA {k}]")
        blocos.append(f"Agora vem a cena {k} famosa demais " + " ".join(f"fala{k} item{j}" for j in range(30)))
    p["resultado"] = {"roteiro_final": "\n".join(blocos), "capitulos": [], "descricao": "D",
                      "cenas": [{"id": 1, "obra": "Filme A", "momento": "a dança", "busca_youtube": "filme a dança cena",
                                 "link": "https://www.youtube.com/watch?v=zzzzzzzzzzz", "link_inicio": "1:35", "link_fim": "1:42"},
                                {"id": 2, "obra": "Série B", "momento": "o tiro", "busca_youtube": "serie b tiro"},
                                {"id": 3, "obra": "Jogo C", "momento": "o chefe", "como_ficou": "removida"},
                                {"id": 4, "obra": "Anime D", "momento": "sem marcador"}]}
    ry.salvar_projeto(base, p)
    return p


def _palavras(texto, ritmo=0.5):
    return [{"word": w, "start": i * ritmo, "end": i * ritmo + 0.4} for i, w in enumerate(texto.split())]


def test_cenas_com_tempo_e_prompt(tmp_path):
    p = _projeto(str(tmp_path))
    falado = ry.roteiro_para_voz(p)
    assert "[CENA" not in falado
    pal = _palavras(falado)
    cenas = rne.cenas_com_tempo(p, pal, len(pal) * 0.5)
    por = {c["id"]: c for c in cenas}
    assert set(por) == {1, 2, 4}  # a removida sai
    idx = falado.split().index("Agora")
    assert por[1]["tempo"] == pytest.approx(idx * 0.5, abs=0.6)
    assert por[2]["tempo"] > por[1]["tempo"] + 20 and por[4]["tempo"] is None
    b = rne.bloco_prompt(p, cenas)
    assert '"provider": "youtube"' in b and "CENA 2 em ~" in b and 'busca: "serie b tiro"' in b and "sem marcador" in b


def test_aplicar_e_link(tmp_path):
    cenas = [{"id": 1, "tempo": 16.0, "busca": "filme a dança"}, {"id": 2, "tempo": 47.0, "busca": "serie b"},
             {"id": 4, "tempo": None, "busca": "x"}]
    segs = [{"start": float(k * 10), "end": float(k * 10 + 10), "provider": "pexels", "query": f"q{k}", "override_source": None}
            for k in range(5)]
    segs[4]["override_source"] = {"source": "local_file", "value": "/x.mp4"}
    usados = rne.aplicar(segs, cenas)
    assert usados == [1, 4] and segs[1]["provider"] == "youtube" and segs[1]["query"] == "filme a dança"
    assert segs[4]["provider"] == "pexels" and segs[4]["roteiro_cena"] == 2  # arquivo escolhido: não troca
    e = rne.escolha_do_link({"link": "https://y/x", "link_inicio": "1:35", "link_fim": "1:42", "obra": "A", "momento": "m"}, 6.0)
    assert (e["inicio"], e["fim"]) == (95.0, 102.0)
    assert rne.escolha_do_link({"link": "https://y/x", "obra": "A", "momento": "m"}, 6.0)["fim"] == 6.0
    assert rne.escolha_do_link({"link": ""}, 6) is None


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_no_app(A, tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    p = _projeto(base)
    falado = ry.roteiro_para_voz(p)
    pal = _palavras(falado)
    jid = "rot-ed"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    job = {"job_id": jid, "roteiro_id": p["id"], "word_timestamps": pal, "total_duration": len(pal) * 0.5, "providers": ["pexels", "youtube"],
           "cutaway_suggestions": []}
    A._JOBS[jid] = job
    assert "Cenas do roteiro" in A._com_produto(job, "PROMPT") and job["roteiro_cenas"]
    from prompt_builder import VideoSegment
    dur = len(pal) * 0.5
    segs = [VideoSegment(start=k * 8.0, end=min(dur, k * 8.0 + 8), provider="pexels", query=f"q{k}") for k in range(int(dur // 8) + 1)]
    idx = A._aplicar_cenas_do_roteiro(job, segs)
    assert len(idx) == 2 and all(segs[i].provider == "youtube" for i in idx)
    job["pending_segments"] = [s.to_dict() for s in segs]
    for i in idx:
        job["pending_segments"][i]["roteiro_cena"] = segs[i].roteiro_cena
    A._youtube_itens_sincronizar(job)
    aplicados = []
    monkeypatch.setattr(A, "_youtube_baixar_e_aplicar", lambda j, item, esc, tag="": aplicados.append((item, esc["url"], esc["inicio"])))
    assert A._usar_links_do_roteiro(jid, job) == 1  # só a cena 1 tem link
    import time
    for _ in range(50):
        if aplicados:
            break
        time.sleep(0.02)
    assert aplicados == [(f"seg-{idx[0]}", "https://www.youtube.com/watch?v=zzzzzzzzzzz", 95.0)]


def test_novo_video_lista_os_roteiros(A, monkeypatch):
    monkeypatch.setattr(ry, "listar_projetos", lambda base: [{"id": "abc123", "titulo": "Meu roteiro", "etapa": "pronto"},
                                                              {"id": "def456", "titulo": "Sem roteiro", "etapa": "transcrito"}])
    monkeypatch.setattr(ry, "carregar_projeto", lambda base, pid: {"resultado": {"cenas": [{"id": 1}, {"id": 2}]}})
    html = A.app.test_client().get("/?roteiro=abc123").get_data(as_text=True)
    assert 'value="roteiro:abc123" selected' in html and "Meu roteiro (2 cenas)" in html and "def456" not in html


def test_novo_video_com_roteiro_liga_o_projeto(A, monkeypatch, tmp_path):
    import subprocess
    audio = str(tmp_path / "n.wav")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=2", "-loglevel", "error", audio], check=True)
    monkeypatch.setattr(A, "transcribe_audio", lambda *a, **k: [{"start": 0.0, "end": 2.0, "text": "teste"}])
    with open(audio, "rb") as f:
        A.app.test_client().post("/transcribe", data={"audio": (f, "a.wav"), "interval_seconds": "2", "language": "pt",
                                                      "providers": ["pexels"], "projeto_midias": "roteiro:abc123def"},
                                 content_type="multipart/form-data")
    job = A._JOBS[list(A._JOBS.keys())[-1]]
    # (v84_92) o projeto liga, mas NÃO marca a fonte youtube sozinho — só o que você marcou
    assert job["roteiro_id"] == "abc123def" and job["providers"] == ["pexels"] and not job.get("dossie_id")
