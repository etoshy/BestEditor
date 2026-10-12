"""v84_69 — 🤖 a IA acha os vídeos do YouTube (busca → capas/títulos → transcrição → momento → nova busca, até 3)
e 📑 os capítulos do Roteiro do YouTube no tempo do vídeo final."""
import json
import os
import time
import zipfile

import pytest

import yt_agente as ag


def _v(n, nota=None, url=None):
    d = {"id": f"id{n:09d}"[:11], "titulo": f"Vídeo {n}", "url": url or f"https://www.youtube.com/watch?v=v{n}", "canal": "c",
         "duracao_segundos": 600, "miniatura_url": f"https://i.ytimg.com/{n}.jpg"}
    if nota is not None:
        d["ia_nota"] = nota
    return d


def _rodar(buscas, legendas, momento_em, nova=lambda f, m: "", **kw):
    """buscas: {termo: [vídeos]} · legendas: {url: linhas} · momento_em: url que tem o momento."""
    chamadas = {"buscar": [], "legenda": [], "achar": []}

    def buscar(t):
        chamadas["buscar"].append(t)
        return buscas.get(t, [])

    def ordenar(rs, termo, vistos):
        return {"resultados": sorted(rs, key=lambda v: -(v.get("ia_nota") or 0)), "busca_melhor": kw.get("busca_melhor", "")}

    def legenda(u):
        chamadas["legenda"].append(u)
        return {"linhas": legendas.get(u, [])}

    def achar(linhas, v):
        chamadas["achar"].append(v["url"])
        return {"achou": v["url"] == momento_em, "inicio": 12.0, "fim": 18.0, "frase": "a frase", "confianca": 0.9}
    r = ag.procurar("a fala", "termo 1", 6.0, buscar=buscar, ordenar=ordenar, legenda=legenda, achar=achar,
                    nova_busca=nova, max_buscas=kw.get("max_buscas", 3))
    return r, chamadas


LEG = [{"inicio": 0, "fim": 2, "texto": "oi"}]


def test_acha_no_segundo_video_da_primeira_busca():
    vs = [_v(1, 9), _v(2, 8), _v(3, 2)]
    r, ch = _rodar({"termo 1": vs}, {v["url"]: LEG for v in vs}, vs[1]["url"])
    assert r["achou"] and r["video"]["titulo"] == "Vídeo 2" and (r["inicio"], r["fim"]) == (12.0, 18.0)
    assert ch["buscar"] == ["termo 1"] and ch["achar"] == [vs[0]["url"], vs[1]["url"]]


def test_nota_baixa_e_sem_legenda_sao_pulados_e_nova_busca():
    b1 = [_v(1, 9), _v(2, 3)]                     # o 2 tem nota baixa: nem abre
    b2 = [_v(3, 8), _v(4, 7)]
    novas = []

    def nova(feitas, motivos):
        novas.append((list(feitas), list(motivos)))
        return "termo 2"
    r, ch = _rodar({"termo 1": b1, "termo 2": b2}, {b2[1]["url"]: LEG}, b2[1]["url"], nova=nova)
    assert r["achou"] and r["busca"] == "termo 2" and r["buscas"] == ["termo 1", "termo 2"]
    assert b1[1]["url"] not in ch["legenda"] and ch["achar"] == [b2[1]["url"]]  # o 1 e o 3 não tinham legenda
    assert any("sem legenda" in m for m in novas[0][1])


def test_desiste_depois_de_3_buscas_e_deixa_os_resultados():
    termos = iter(["termo 2", "termo 3", "termo 4"])
    bs = {f"termo {k}": [_v(k * 10 + j, 8) for j in range(4)] for k in range(1, 5)}
    r, ch = _rodar(bs, {v["url"]: LEG for l in bs.values() for v in l}, "nenhum", nova=lambda f, m: next(termos))
    assert not r["achou"] and r["buscas"] == ["termo 1", "termo 2", "termo 3"] and "escolha à mão" in r["motivo"]
    assert len(ch["achar"]) == 9 and r["resultados"] and r["resultados"][0]["titulo"].startswith("Vídeo 3")
    assert r["termo_resultados"] == "termo 3"


def test_usa_a_busca_sugerida_pela_ia_e_nao_repete_video():
    vs = [_v(1, 9), _v(2, 8)]
    r, ch = _rodar({"termo 1": vs, "outra": vs + [_v(5, 6)]}, {v["url"]: LEG for v in vs + [_v(5)]}, _v(5)["url"],
                   busca_melhor="outra")
    assert r["achou"] and r["buscas"] == ["termo 1", "outra"] and ch["achar"].count(vs[0]["url"]) == 1


def test_sem_ideia_de_busca_para_antes():
    r, ch = _rodar({"termo 1": []}, {}, "x")
    assert not r["achou"] and r["buscas"] == ["termo 1"]


# ------------------------------------------------------------------ rotas do painel
@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def _job(A, jid):
    os.makedirs(A._job_dir(jid), exist_ok=True)
    segs = [{"start": 0.0, "end": 6.0, "provider": "youtube", "query": "discurso famoso", "media_type": "video", "override_source": None},
            {"start": 6.0, "end": 12.0, "provider": "youtube", "query": "coisa rara", "media_type": "video", "override_source": None},
            {"start": 12.0, "end": 18.0, "provider": "pexels", "query": "cidade", "media_type": "video", "override_source": None}]
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 18.0, "pending_segments": segs,
                    "segment_previews": [None] * 3, "overlays": [], "cutaway_suggestions": [], "media_library": [],
                    "segments": [{"start": 0, "end": 6, "text": "ele disse eu tenho um sonho"}, {"start": 6, "end": 12, "text": "algo raro"}]}
    return A._JOBS[jid]


def _esperar(A, job, t=10):
    fim = time.time() + t
    while time.time() < fim and (job.get("youtube_ia") or {}).get("rodando"):
        time.sleep(0.05)


def test_rota_ia_acha_baixa_e_aplica(A, monkeypatch, tmp_path):
    import ia_midia
    import ia_servico
    jid = "yt-ia"
    job = _job(A, jid)
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda rec: None)
    bom = _v(1, 9)
    monkeypatch.setattr(A, "buscar_videos_youtube", lambda t, quantidade=20: [bom, _v(2, 7)] if t == "discurso famoso" else [_v(3, 8)])
    capas = []
    monkeypatch.setattr(ia_midia, "ordenar_youtube", lambda rs, fala, termo, ficha, job=None, com_capas=0, ja_vistos=None:
                        capas.append(com_capas) or {"resultados": rs, "busca_melhor": ""})
    monkeypatch.setattr(ia_midia, "nova_busca_youtube", lambda fala, feitas, motivos, ficha, job=None: "" if len(feitas) > 1 else "coisa rara 2")
    monkeypatch.setattr(A, "_legenda_com_tempos", lambda url, pasta: {"linhas": LEG})
    monkeypatch.setattr(ia_midia, "achar_momento", lambda linhas, fala, titulo, canal, dur, ficha, job=None:
                        {"achou": "sonho" in fala and titulo == "Vídeo 1", "inicio": 30.0, "fim": 33.0, "frase": "I have a dream", "confianca": 0.9})
    baixados = []

    def baixar(url, pasta):
        baixados.append(url)
        os.makedirs(pasta, exist_ok=True)
        open(os.path.join(pasta, "v.mp4"), "wb").write(b"x")
        return {"caminho": os.path.join(pasta, "v.mp4")}
    cortes = []
    monkeypatch.setattr(A, "yt_baixar_video", baixar)
    monkeypatch.setattr(A, "yt_cortar_trecho", lambda c, i, f, saida: cortes.append((i, f)) or open(saida, "wb").write(b"y"))
    c = A.app.test_client()
    d = c.post(f"/job/{jid}/youtube/ia", json={}).get_json()
    assert d["ok"] and d["total"] == 2
    _esperar(A, job)
    it = {i["id"]: i for i in job["youtube_itens"]}
    assert it["seg-0"]["ia"]["estado"] == "pronto" and baixados == [bom["url"]] and cortes == [(30.0, 36.0)]  # completa até os 6 s do trecho
    assert job["pending_segments"][0]["override_source"]["source"] == "local_file" and it["seg-0"]["escolha"]["ia"]
    assert it["seg-1"]["ia"]["estado"] == "nao_achou" and it["seg-1"]["resultados"] and it["seg-1"]["status"] == "pronto"
    assert job["pending_segments"][1]["override_source"] is None
    assert set(capas) == {12}
    g = c.get(f"/job/{jid}/youtube/itens").get_json()
    assert g["ia"]["achados"] == 1 and g["ia"]["total"] == 2 and not g["ia"]["rodando"]
    # de novo: só o que ficou sem vídeo
    assert c.post(f"/job/{jid}/youtube/ia", json={}).get_json()["total"] == 1
    _esperar(A, job)


def test_rota_ia_desligada_e_parar(A, monkeypatch):
    import ia_servico
    jid = "yt-ia2"
    job = _job(A, jid)
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda rec: "desligada" if rec == "youtube_momento" else None)
    r = A.app.test_client().post(f"/job/{jid}/youtube/ia", json={})
    assert r.status_code == 400 and "desligada" in r.get_json()["erro"]
    A._YOUTUBE_IA_PARAR.add(jid)
    A._youtube_itens_sincronizar(job)
    A._youtube_ia_rodar(jid, ["seg-0", "seg-1"])
    assert job["youtube_ia"]["parado"] and job["youtube_ia"]["feitos"] == 0
    html = A.app.test_client().get(f"/job/{jid}/edit-segments").get_data(as_text=True)
    assert 'id="yt-ia-todos"' in html and "ytIaUm(" in html


# ------------------------------------------------------------------ 📑 Roteiro do YouTube
def test_capitulos_do_roteiro_do_youtube_no_video_final(A, tmp_path, monkeypatch):
    import capitulos_video as cv
    import dossies as ds
    import roteiros_yt as ry
    base = str(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    p = ry.criar_projeto(base, "https://www.youtube.com/watch?v=abcdefghijk")
    texto = "\n\n".join(f"Parte {k} começa agora mesmo. " + " ".join(f"palavra{j % 9} coisa{k}" for j in range(80)) for k in range(1, 4))
    p["resultado"] = {"roteiro_final": texto, "descricao": "Desc.", "palavras": len(texto.split()),
                      "capitulos": ry._capitulos([{"titulo": f"C{k}", "comeca_em": f"Parte {k} começa agora mesmo"} for k in range(1, 4)],
                                                 texto, len(texto.split()), [])}
    ry.salvar_projeto(base, p)
    pal = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, w in enumerate(texto.split())]
    job = {"job_id": "r1", "status": "concluido", "roteiro_id": p["id"], "total_duration": len(pal) * 0.4, "word_timestamps": pal}
    monkeypatch.setattr(A, "_probe_media_duration", lambda c: 20.0 if c == "clipe.mp4" else 999.0)
    A._capitulos_do_video_final("r1", job, "final.mp4", [{"resolved_path": "clipe.mp4", "insertion_point": 1.0}])
    assert job["capitulos_video"][1]["segundos"] > 20 and job["descricao_youtube"].startswith("Desc.")
    salvo = ry.carregar_projeto(base, p["id"])["resultado"]
    assert salvo["capitulos_video"]["capitulos"] == job["capitulos_video"]
    assert ry.descricao_com_capitulos(salvo) == job["descricao_youtube"]
    ry.aplicar_tempos_do_audio(base, p["id"], pal, len(pal) * 0.4)
    assert "capitulos_video" not in ry.carregar_projeto(base, p["id"])["resultado"]
    # o roteiro colado no Gerador de voz é reconhecido
    assert ds.achar_roteiro_yt_pelo_texto(base, texto) == p["id"]
    # o .zip do Gerar voz leva o roteiro_id e o vídeo novo liga
    z = str(tmp_path / "n.zip")
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("info.json", json.dumps({"roteiro_id": p["id"]}))
    assert A._roteiro_do_zip(z) == p["id"]
    assert cv.para_job({"job_id": "x"}, base, pal, [], 10) is None
