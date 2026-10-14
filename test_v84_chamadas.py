"""v84 — chamadas de inscreva-se / venda / link: marcador no texto do TTS,
tempo exato no áudio, e no editor um clipe que entra NO LUGAR do trecho."""
import io
import json
import os
import re
import shutil
import subprocess
import time
import zipfile

import pytest

import chamadas as ch


# ------------------------------------------------------------------ texto
def test_dividir_e_remover():
    t = "Começo da história.\n[[INSCREVA]]\nMeio. [[venda]] [[INSCREVA: Deixa o like!]] [[OUTRA: fica]] Fim."
    partes = ch.dividir(t)
    assert [p["tipo"] for p in partes] == [None, "inscreva", None, "venda", "inscreva", None]
    assert partes[1]["texto"] == "" and partes[4]["texto"] == "Deixa o like!"
    assert "[[OUTRA: fica]]" in partes[-1]["texto"]  # nome desconhecido: texto comum
    assert ch.remover_marcadores(t) == "Começo da história.\n\nMeio.  Deixa o like! [[OUTRA: fica]] Fim."
    assert ch.tipo_do_nome("LINK") is None
    assert ch.tipo_do_nome("Inscreva-se") == "inscreva" and ch.tipo_do_nome("PATROCÍNIO") == "venda"


def test_limpeza_do_tts_nao_le_o_marcador():
    import narracoes as na
    out = na.limpar_texto_para_tts("Oi.\n[[INSCREVA]]\ntchau [[VENDA]]")
    assert "INSCREVA" not in out and "VENDA" not in out and "tchau" in out


def test_multivoz_ignora_marcador():
    import multivoz as mv
    d = mv.dividir("[[INSCREVA]] Oi [[LIKE: curte aí]] tchau", {})
    assert not d["desconhecidas"] and "curte aí" in d["falas"][0]["texto"]


def test_tempos_por_duracao_e_alinhamento():
    partes = ch.dividir("Um dois três. [[INSCREVA: deixa o like]] quatro cinco. [[VENDA]] seis")
    out = ch.de_duracoes(partes, [2.0, 1.5, 1.0, 0.0, 0.5])
    assert out == [{"tipo": "inscreva", "texto": "deixa o like", "inicio": 2.0, "fim": 3.5},
                   {"tipo": "venda", "texto": "", "inicio": 4.5, "fim": 4.5}]
    palavras = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in
                enumerate(["Um", "dois", "três.", "Deixa", "o", "like,", "quatro", "cinco.", "seis"])]
    al = ch.alinhar(partes, palavras)
    assert al[0]["inicio"] == 1.5 and al[0]["fim"] == 2.9
    assert al[1]["inicio"] == 3.9 and al[1]["fim"] == 3.9  # ponto depois de "cinco"


def test_srt_com_marcador():
    segs = [{"start": 0, "end": 2, "text": "Olá"}, {"start": 2, "end": 4, "text": "[[INSCREVA: se inscreve]]"},
            {"start": 4, "end": 6, "text": "[[VENDA]] continua"}]
    limpos, chs = ch.do_srt(segs)
    assert [s["text"] for s in limpos] == ["Olá", "se inscreve", "continua"]
    assert chs == [{"tipo": "inscreva", "texto": "se inscreve", "inicio": 2.0, "fim": 4.0},
                   {"tipo": "venda", "texto": "", "inicio": 4.0, "fim": 4.0}]


def test_roteiro_yt_limpeza_preserva_marcador():
    import roteiros_yt as ry
    out = ry.limpar_para_tts("Oi!!! [[INSCREVA: deixa o like 👍]] [Música] fim", "pt")["texto"]
    assert "[[INSCREVA: deixa o like]]" in out and "Música" not in out


# ------------------------------------------------------------------ montagem
def _video(path, cor, dur, freq=None):
    args = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={cor}:s=320x180:r=30:d={dur}"]
    if freq:
        args += ["-f", "lavfi", "-i", f"sine=f={freq}:d={dur}", "-c:a", "aac", "-shortest"]
    subprocess.run(args + ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def test_insert_cutaways_substitui_o_trecho(tmp_path):
    import video_assembler as va
    base = _video(tmp_path / "base.mp4", "blue", 6, 440)
    clipe = _video(tmp_path / "clipe.mp4", "red", 2, 880)
    out = va.insert_cutaways(base, [{"resolved_path": clipe, "insertion_point": 2.0, "remove_ate": 4.5}],
                             str(tmp_path / "out.mp4"), str(tmp_path), 320, 180)
    assert abs(va._probe_duration(out) - 5.5) < 0.25  # 6 - 2.5 tirados + 2 do clipe
    palavras = [{"start": 1.0, "end": 1.5}, {"start": 3.0, "end": 3.4}, {"start": 5.0, "end": 5.5}]
    d = va.shift_timestamps_for_cutaways(palavras, [{"insertion_point": 2.0, "remove_ate": 4.5, "duration": 2.0}])
    assert d == [{"start": 1.0, "end": 1.5}, {"start": 4.5, "end": 5.0}]  # a do meio saiu; a última andou -0.5
    # ponto (sem remover) continua igual a antes
    assert va.shift_timestamps_for_cutaways([{"start": 3.0, "end": 3.5}], [{"insertion_point": 2.0, "duration": 2.0}]) == [{"start": 5.0, "end": 5.5}]


# ------------------------------------------------------------------ app
@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(ch, "PASTA_PADRAO", str(tmp_path / "padrao"))
    return _app


def test_gerar_voz_com_chamadas_tempo_exato_e_zip(A, monkeypatch, tmp_path):
    def lote(itens, on_progresso=None, **k):
        for i, (_e, texto, saida, _kw) in enumerate(itens):
            dur = 1.0 + (0.5 if "like" in texto else 0)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f=300:d={dur}", "-ar", "24000", saida], check=True)
            if on_progresso:
                on_progresso(i, None)
        return {}

    def sem_legenda(*a, **k):
        raise A.TranscriptionError("sem whisper no teste")
    monkeypatch.setattr(A, "tts_gerar_audio_isolado_lote", lote)
    monkeypatch.setattr(A, "transcribe_audio", sem_legenda)
    monkeypatch.setattr(A, "VOZES_DIR", str(tmp_path))
    jid = "vozch"
    A._GERAR_VOZ_STATUS[jid] = {"running": True, "log": "", "erro": None, "pronto": False, "engine": "piper", "idioma": "pt"}
    saida = str(tmp_path / f"{jid}.wav")
    A._gerar_voz_em_background(jid, "piper", "Oi pessoal. [[INSCREVA: deixa o like]] Vamos lá. [[VENDA]] Fim.", saida, {})
    st = A._GERAR_VOZ_STATUS[jid]
    assert not st["erro"], st["log"]
    assert abs(A._probe_media_duration(saida) - 4.5) < 0.1
    assert st["chamadas"] == [{"tipo": "inscreva", "texto": "deixa o like", "inicio": 1.0, "fim": 2.5},
                              {"tipo": "venda", "texto": "", "inicio": 3.5, "fim": 3.5}]
    c = A.app.test_client()
    res = c.get(f"/gerar-voz/status/{jid}").get_json()["resultado"]
    assert res["zip_url"] and res["chamadas"][0]["rotulo"].startswith("👍")
    z = zipfile.ZipFile(io.BytesIO(c.get(res["zip_url"]).data))
    assert json.loads(z.read("chamadas.json"))["chamadas"][0]["fim"] == 2.5


def test_zip_cria_chamadas_no_editor_e_clipe_padrao(A, monkeypatch, tmp_path):
    monkeypatch.setattr(A, "fetch_segment_preview_lightweight", lambda s, **k: {"ok": False, "error": "x"})
    srt = "1\n00:00:00,000 --> 00:00:03,000\nOlá a todos.\n\n2\n00:00:03,000 --> 00:00:05,000\n[[VENDA]] compre\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("narracao.wav", b"fake")
        zf.writestr("legenda.srt", srt)
        zf.writestr("chamadas.json", json.dumps({"chamadas": [{"tipo": "inscreva", "texto": "deixa o like", "inicio": 1.0, "fim": 2.5}]}))
    buf.seek(0)
    c = A.app.test_client()
    r = c.post("/transcribe", data={"interval_seconds": "7", "providers": ["pexels"], "audio": (buf, "n.zip")}, content_type="multipart/form-data")
    jid = r.headers["Location"].rstrip("/").rsplit("/", 2)[-2]
    job = A._JOBS[jid]
    assert [x["tipo"] for x in job["chamadas"]] == ["inscreva", "venda"]
    for _ in range(200):
        if job["status"] != "transcrevendo":
            break
        time.sleep(0.05)
    assert all("[[" not in s["text"] for s in job["segments"])
    cortes = A._cortes_com_chamadas(job, [])
    assert [(x["tipo"], x["insertion_point"], x["remove_ate"], x["resolved_path"]) for x in cortes] == [("inscreva", 1.0, 2.5, None), ("venda", 3.0, 3.0, None)]
    job["cutaway_suggestions"] = cortes
    job["total_duration"] = 5.0
    # colar o JSON da IA de novo não duplica nem apaga as chamadas
    assert A._cortes_com_chamadas(job, [{"id": "ia1"}])[1:] == cortes
    # chamada manual + clipe padrão
    assert c.post(f"/job/{jid}/chamada/nova", json={"tipo": "inscreva", "inicio": 4.2, "fim": 4.2}).get_json()["ok"]
    clipe = _video(tmp_path / "like.mp4", "red", 1, 600)
    with open(clipe, "rb") as f:
        c.post(f"/job/{jid}/upload-cutaway/{cortes[0]['id']}", data={"cutaway_file": (f, "like.mp4"), "padrao": "on"}, content_type="multipart/form-data")
    inscr = [x for x in job["cutaway_suggestions"] if x.get("tipo") == "inscreva"]
    # só a marca que recebeu o vídeo ganha clipe: as outras do mesmo tipo seguem com a narração normal
    assert inscr[0]["resolved_path"] and inscr[1]["resolved_path"] is None and ch.clipe_padrao("inscreva")
    assert ch.para_cortes([{"tipo": "inscreva", "inicio": 0, "fim": 1}])[0]["clipe_padrao"]  # próximos vídeos
    assert c.post(f"/job/{jid}/chamada/{inscr[1]['id']}/tirar-clipe", json={}).get_json()["ok"]
    assert inscr[1]["resolved_path"] is None
    # o painel do YouTube não procura vídeo pras chamadas
    assert not any(it.get("cutaway_id") for it in A._youtube_itens_sincronizar(job) if it.get("tipo") == "corte" and it["cutaway_id"] in {x["id"] for x in inscr})


def test_scripts_compilam(A, tmp_path):
    if not shutil.which("node"):
        pytest.skip("sem node")
    import os as _os
    _os.makedirs(A._job_dir("ch-js"), exist_ok=True)
    A._JOBS["ch-js"] = {"job_id": "ch-js", "status": "pronto_para_editar", "created_at": 1.0, "providers": ["pexels"], "audio_path": "",
                        "total_duration": 8.0, "segment_previews": [None],
                        "pending_segments": [{"start": 0, "end": 8, "provider": "pexels", "query": "a", "media_type": "video", "override_source": None}],
                        "cutaway_suggestions": ch.para_cortes([{"tipo": "venda", "texto": "compre", "inicio": 2, "fim": 4}])}
    c = A.app.test_client()
    for url in ("/job/ch-js/edit-segments?modo=estudio", "/gerar-voz"):
        html = c.get(url).get_data(as_text=True)
        alvo = tmp_path / "s.js"
        alvo.write_text("\n;\n".join(re.findall(r"<script>(.*?)</script>", html, re.S)), encoding="utf-8")
        r = subprocess.run(["node", "--check", str(alvo)], capture_output=True, text=True)
        assert r.returncode == 0, (url, r.stderr[-1500:])


# ------------------------------------------------------------------ Roteiro do YouTube marca [[INSCREVA]]/[[VENDA]]
def _proj_ry(roteiro):
    return {"id": "d" * 10, "transcricao": {"blocos": [{"inicio": 0, "texto": "oi"}]},
            "analise": {"roteiro": roteiro, "cenas": [], "idioma": "pt-BR"}}


def test_roteiro_yt_pede_as_marcas_e_nao_deixa_tirar():
    import roteiros_yt as ry
    p = _proj_ry("Gancho forte.\n\n[[INSCREVA]]\n\nMeio da história.\n\n[[VENDA]]\n\nFim.")
    pa = ry.prompt_analise(p, ry.MODELOS_FABRICA[0])
    assert "[[INSCREVA]] = chamada pra ação" in pa and "[[VENDA]] = momento de anúncio" in pa
    assert pa.index("[[VENDA]] = momento") < pa.index("Formato de resposta")
    assert "[[INSCREVA]] = chamada" not in ry.prompt_analise(p, ry.MODELOS_FABRICA[0], marcar_chamadas=False)
    pc = ry.prompt_acoes(p, ["traduzir", "ads"], idioma="en")
    assert "MANTENHA todas as marcas [[INSCREVA]] e [[VENDA]]" in pc and "ponha a marca [[VENDA]]" in pc
    assert "ponha a marca [[VENDA]]" not in ry.prompt_acoes(p, ["ads"], cta_no_texto=False)
    # resposta da IA que perdeu uma marca: avisa; marca não vira "tag desconhecida"
    r = ry.ler_resultado(json.dumps({"roteiro_final": "Strong hook.\n\n[[INSCREVA]]\n\nMiddle.\n\nEnd."}), p)
    assert any("tirou 1 marca(s) [[VENDA]]" in a for a in r["avisos"])
    assert not any("Chatterbox" in a for a in r["avisos"]) and r["palavras"] == 4
    # vai pro Gerar voz com as marcas, e a limpeza local não tira
    p["resultado"] = {"roteiro_final": "Oi!!! 😀\n\n[[INSCREVA]]\n\nfim [CENA 1]\n\n[[VENDA]]"}
    voz = ry.roteiro_para_voz(p)
    assert "\n[[INSCREVA]]\n" in voz and voz.endswith("[[VENDA]]") and "CENA" not in voz
    ry.aplicar_limpeza(p)
    assert p["resultado"]["roteiro_final"].count("[[INSCREVA]]") == 1 and "[[VENDA]]" in p["resultado"]["roteiro_final"]
    assert ry.ler_analise(json.dumps({"roteiro": "a\n\n[[VENDA]]\n\nb", "cenas": []}))["marcas"] == {"inscreva": 0, "venda": 1}


def test_ritmo_livre_e_fixo_no_prompt():
    import prompt_builder as pb
    segs = [{"start": 0.0, "end": 30.0, "text": "oi"}]
    livre = pb.build_prompt(segs, interval_seconds=5, providers=["pexels"])
    assert "RITMO LIVRE" in livre and "~5 segundos por cena é só a MÉDIA" in livre and "até ~11s" in livre
    fixo = pb.build_prompt(segs, interval_seconds=5, providers=["pexels"], ritmo="fixo")
    assert "RITMO LIVRE" not in fixo and "troque de vídeo a cada ~5 segundos" in fixo
    assert "RITMO LIVRE" in pb.build_animepexels_prompt(segs, interval_seconds=5)
    assert "RITMO LIVRE" not in pb.build_animepexels_prompt(segs, interval_seconds=5, ritmo="fixo")


def test_varias_marcas_do_mesmo_tipo_so_a_primeira_ganha_o_padrao(monkeypatch, tmp_path):
    """Com várias [[INSCREVA]] / [[VENDA]], o vídeo padrão entra em UMA de cada tipo (a 1ª);
    as outras ficam desligadas até a pessoa escolher — mesmo sem mexer em nada."""
    padrao = tmp_path / "p.mp4"
    padrao.write_bytes(b"x")
    monkeypatch.setattr(ch, "clipe_padrao", lambda tipo, perfil=None: str(padrao))
    cortes = ch.para_cortes([{"tipo": "venda", "inicio": 50}, {"tipo": "inscreva", "inicio": 10}, {"tipo": "inscreva", "inicio": 80},
                             {"tipo": "venda", "inicio": 120}, {"tipo": "inscreva", "inicio": 200}])
    com = [(c["tipo"], c["insertion_point"]) for c in cortes if c["resolved_path"]]
    assert com == [("inscreva", 10.0), ("venda", 50.0)]
    assert all(c.get("desligada") for c in cortes if not c["resolved_path"])


def test_marcas_de_cena_nao_vao_pra_voz():
    t = "Começo.\n[CENA 3]\nOlha isso [Cena 2: luta no telhado] aqui.\n\n[[SCENE 4]]\n(CENA 5) Fim [laugh].\n[[VENDA]]\nTchau."
    novo, n = ch.tirar_marcas_de_cena(t)
    assert n == 4
    assert "CENA" not in novo.upper().replace("[[VENDA]]", "") and "[laugh]" in novo and "[[VENDA]]" in novo
    assert "Olha isso aqui." in novo


def test_gerar_voz_tira_as_marcas_antes_de_narrar(A, monkeypatch):
    visto = []
    monkeypatch.setattr(A, "_gerar_voz_em_background", lambda job_id, engine, texto, *a, **k: visto.append(texto))
    r = A.app.test_client().post("/gerar-voz/gerar", data={"texto": "Oi.\n[CENA 1]\nTudo bem?", "engine": "piper"})
    assert r.status_code == 200
    for _ in range(100):
        if visto:
            break
        time.sleep(0.02)
    assert visto == ["Oi.\nTudo bem?"]
    assert "btn-tirar-cenas" in A.app.test_client().get("/gerar-voz").get_data(as_text=True)
