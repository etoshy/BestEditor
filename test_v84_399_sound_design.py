"""v84_399: 🎧 sound design — emoção por trecho, ambiente, música por emoção, acentos com equilíbrio e mixagem;
no Estúdio (montagem) e em qualquer arquivo do site (página 🎧 Sound design)."""
import json
import os
import subprocess
import time

import pytest

import sound_design as SD
import sound_design_rotas as SR


def _tom(caminho, dur=6.0, freq=440, ruido=False):
    src = f"anoisesrc=d={dur}:c=pink:a=0.3" if ruido else f"sine=f={freq}:d={dur}"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, "-ar", "48000", "-ac", "2", caminho], check=True)
    return caminho


def _dur(c):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", c],
                                capture_output=True, text=True).stdout.strip())


def test_ler_resposta_continua_e_equilibrada():
    r = {"blocos": [{"inicio": 3, "fim": 50, "emocao": "tensao", "ambiente_en": "dark drone", "musica_en": "suspense"},
                    {"inicio": 50, "fim": 55, "emocao": "tensao", "ambiente_en": "x", "musica_en": "y"},   # mesma emoção: junta
                    {"inicio": 55, "fim": 120, "emocao": "inventada", "ambiente_en": "", "musica_en": ""},
                    {"inicio": 120, "fim": 170, "emocao": "silencio", "ambiente_en": "rain light", "musica_en": "sad piano"}],
         "momentos": [{"t": 30, "tipo": "revelacao", "forca": 3}, {"t": 35, "tipo": "virada", "forca": 2},  # 5 s depois: some
                      {"t": 80, "tipo": "impacto", "forca": 3}, {"t": 140, "tipo": "impacto", "forca": 3},
                      {"t": 1, "tipo": "impacto", "forca": 1}]}
    d = SD.ler_resposta(r, 180)
    b = d["blocos"]
    assert b[0]["start"] == 0 and b[-1]["end"] == 180 and all(b[k]["end"] == b[k + 1]["start"] for k in range(len(b) - 1))
    assert [x["emocao"] for x in b] == ["tensao", "neutro", "silencio"]
    assert b[1]["musica_en"] == SD.EMOCOES["neutro"]["musica_en"] and b[2]["musica_en"] == ""
    ts = [m["t"] for m in d["momentos"]]
    assert 35 not in ts and 1 not in ts and sum(1 for m in d["momentos"] if m["forca"] == 3) <= 2


def test_analisar_com_ia_falsa():
    job = {"segments": [{"start": 0, "end": 10, "text": "Era uma noite calma."}, {"start": 10, "end": 60, "text": "Até que…"}],
           "total_duration": 60}
    vistos = {}

    def chamar(rec, sis, conteudo, **kw):
        vistos.update(rec=rec, sis=sis, conteudo=conteudo, schema=kw.get("schema"))
        return {"blocos": [{"inicio": 0, "fim": 60, "emocao": "calma", "ambiente_en": "forest night", "musica_en": "calm piano"}],
                "momentos": [{"t": 10, "tipo": "virada", "forca": 2, "frase": "Até que"}]}
    d = SD.analisar(job, chamar=chamar)
    assert vistos["rec"] == "sound_design" and "EMOÇÃO-ALVO" in vistos["sis"] and "[10.0–60.0] Até que" in vistos["conteudo"]
    assert d["blocos"][0]["ambiente_en"] == "forest night" and d["momentos"][0]["t"] == 10


def test_acentos_terminam_no_momento():
    plano = {"momentos": [{"t": 20, "forca": 3}, {"t": 50, "forca": 2}, {"t": 80, "forca": 1}],
             "acentos": {"riser": {"arquivo": "r.m4a", "dur": 4}, "reverse": {"arquivo": "v.m4a", "dur": 1.5},
                         "impacto": {"arquivo": "i.m4a", "pico": 0.1}, "boom": {"arquivo": "b.m4a", "pico": 0.3}}}
    ev = SD.eventos_acentos(plano)
    assert {"arquivo": "r.m4a", "inicio": 16.0} .items() <= ev[0].items() and ev[1]["arquivo"] == "b.m4a" and abs(ev[1]["inicio"] - 19.7) < 1e-6
    assert ev[2]["arquivo"] == "v.m4a" and ev[2]["inicio"] == 48.5 and ev[3]["arquivo"] == "i.m4a"
    assert len(ev) == 5 and ev[4]["arquivo"] == "i.m4a" and ev[4]["volume"] < ev[3]["volume"]  # força 1: só o impacto, mais baixo


def test_aplicar_mixa_ambiente_e_musica(tmp_path):
    nar = _tom(str(tmp_path / "nar.wav"), 8)
    amb = _tom(str(tmp_path / "amb.wav"), 3, ruido=True)   # mais curto que o bloco: entra em loop
    mus = _tom(str(tmp_path / "mus.wav"), 30, 220)
    plano = {"blocos": [{"start": 0, "end": 4, "emocao": "calma", "ambiente": amb, "musica": mus},
                        {"start": 4, "end": 8, "emocao": "silencio", "ambiente": amb, "musica": ""}],
             "momentos": [{"t": 5, "forca": 2}], "acentos": {}, "mix": True}
    out = SD.aplicar(nar, plano, str(tmp_path / "out.wav"))
    assert os.path.isfile(out) and abs(_dur(out) - 8) < 0.3
    assert SD.aplicar(nar, {"blocos": [{"start": 0, "end": 8, "ambiente": "", "musica": ""}], "momentos": []}, str(tmp_path / "x.wav")) == nar
    # com trilha enviada pela pessoa, a música do sound design não entra (só o ambiente)
    entradas = []
    _p, amb_r, mus_r = SD._filtro_camadas(plano, True, entradas)
    assert mus_r == [] and len(amb_r) == 2


def test_dp_sons_mixa_arquivo_direto_com_reverb(tmp_path):
    import dp_sons
    nar = _tom(str(tmp_path / "nar.wav"), 3)
    hit = _tom(str(tmp_path / "hit.wav"), 0.3, 880)
    out = dp_sons.mixar(nar, [{"arquivo": hit, "inicio": 1.0, "volume": 1.0}, {"arquivo": "/nao/existe.wav", "inicio": 0}],
                        str(tmp_path / "o.wav"), reverb=True)
    assert out.endswith("o.wav") and os.path.isfile(out)


def test_buscar_escolhe_e_guarda(tmp_path):
    pasta_p, pasta_job = str(tmp_path / "pix"), str(tmp_path / "job")
    os.makedirs(pasta_p)
    sd = SD.vazio()
    sd["blocos"] = [SD.novo_bloco(0, 60, "tensao", "dark drone", "suspense dark")]
    sd["momentos"] = [SD.novo_momento(30, "revelacao", 3)]
    pedidos = []

    def rodar(args):
        pedidos.append((args.tipo, list(args.termos)))
        cat = json.load(open(os.path.join(pasta_p, "catalogo.json"))) if os.path.isfile(os.path.join(pasta_p, "catalogo.json")) else []
        for k, termo in enumerate(args.termos):
            for j, dur in enumerate((5, 40)):
                arq = _tom(os.path.join(pasta_p, f"{args.tipo}_{k}_{j}.wav"), 0.5)
                cat.append({"id": f"{args.tipo}{k}{j}", "busca": termo, "tipo": "musica" if args.tipo == "music" else "efeitos",
                            "arquivo_cortado": arq, "dur": dur, "pico": 0.1, "titulo": f"som {j}"})
        json.dump(cat, open(os.path.join(pasta_p, "catalogo.json"), "w"))
        return 0
    sd["camadas"]["juiz"] = False
    r = SD.buscar_audios(sd, pasta_p, pasta_job, rodar=rodar)
    assert [p[0] for p in pedidos] == ["sound-effects", "music"]
    assert "dark drone" in pedidos[0][1] and "cinematic riser" in pedidos[0][1] and pedidos[1][1] == ["suspense dark"]
    assert r["faltando"] == [] and sd["audios"]["musica:suspense dark"]["dur"] == 40  # cama: a mais longa
    assert sd["audios"]["efeitos:cinematic riser"]["dur"] == 5                        # acento: o 1º
    assert all(os.path.dirname(a["arquivo"]) == os.path.join(pasta_job, "sound_design") for a in sd["audios"].values())
    plano = SD.para_montar({"sound_design": sd})
    assert plano["blocos"][0]["ambiente"] and plano["blocos"][0]["musica"] and "boom" in plano["acentos"]
    sd["camadas"]["musica"] = False
    assert not SD.para_montar({"sound_design": sd})["blocos"][0]["musica"]
    # de novo: nada falta, não abre o navegador
    SD.buscar_audios(sd, pasta_p, pasta_job, rodar=rodar)
    assert len(pedidos) == 2


def test_pixabay_busca_de_musica():
    import pixabay_sons as PS
    assert PS.url_busca("sad piano", tipo="music") == "https://pixabay.com/pt/music/search/sad%20piano/"
    assert "/sound-effects/" in PS.url_busca("whoosh")


def _esperar(tid):
    import tarefas_bg
    for _ in range(200):
        t = tarefas_bg.pegar(tid)
        if t and t["status"] != "rodando":
            return t
        time.sleep(0.05)
    raise AssertionError("a tarefa não terminou")


def test_rotas_no_estudio(monkeypatch):
    import app as A
    jid = "sdteste01"
    monkeypatch.setitem(A._JOBS, jid, {"job_id": jid, "segments": [{"start": 0, "end": 30, "text": "Uma frase qualquer."}],
                                       "total_duration": 30})
    monkeypatch.setattr(A, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(SD, "analisar", lambda job, chamar=None, job_id="": SD.ler_resposta(
        {"blocos": [{"inicio": 0, "fim": 30, "emocao": "misterio", "ambiente_en": "wind light", "musica_en": "mysterious"}],
         "momentos": [{"t": 20, "tipo": "revelacao", "forca": 2}]}, 30))
    c = A.app.test_client()
    e = c.get(f"/job/{jid}/sound-design/estado").get_json()
    assert e["blocos"] == [] and e["tem_texto"] and e["camadas"]["musica"]
    tid = c.post(f"/job/{jid}/sound-design/analisar", json={}).get_json()["tarefa"]
    assert _esperar(tid)["status"] == "pronto"
    e = c.get(f"/job/{jid}/sound-design/estado").get_json()
    assert e["blocos"][0]["emocao"] == "misterio" and e["momentos"][0]["t"] == 20
    b = dict(e["blocos"][0], emocao="tristeza", musica_en="sad strings")
    e = c.post(f"/job/{jid}/sound-design/salvar", json={"blocos": [b], "momentos": [], "camadas": {"musica": False}}).get_json()
    assert e["blocos"][0]["emocao"] == "tristeza" and e["blocos"][0]["musica_en"] == "sad strings" and e["momentos"] == []
    assert e["camadas"] == {"ambiente": True, "musica": False, "acentos": True, "mix": True, "juiz": True, "memes": True}
    assert SD.para_montar(A._JOBS[jid]) is None  # sem áudio baixado ainda: a montagem segue como antes
    src = open("templates/estudio.html", encoding="utf-8").read()
    assert 'id="btnSoundDesign"' in src and "_sound_design.html" in src
    A.app.jinja_env.get_template("estudio.html")


def test_pagina_universal_e_copia(tmp_path, monkeypatch):
    import app as A
    base = str(tmp_path)
    video = str(tmp_path / "saida" / "meu_curto.mp4")
    os.makedirs(os.path.dirname(video))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=6:s=320x240:r=10", "-f", "lavfi", "-i",
                    "sine=f=300:d=6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
    assert any(r["caminho"] == video for r in SR.recentes(base))
    p = SR.criar_projeto(base, video)
    assert p["video"] and abs(p["total_duration"] - 6) < 0.3
    segs = SR.transcrever(p, SR.pasta_projeto(base, p["id"]), transcrever_fn=lambda w, **k: [{"start": 0, "end": 6, "text": " Olá. "}])
    assert segs == [{"start": 0.0, "end": 6.0, "text": "Olá."}]
    p["segments"] = segs
    amb = _tom(str(tmp_path / "amb.wav"), 2, ruido=True)
    hit = _tom(str(tmp_path / "hit.wav"), 0.3, 900)
    sd = p["sound_design"]
    sd["blocos"] = [SD.novo_bloco(0, 6, "tensao", "dark drone", "")]
    sd["momentos"] = [SD.novo_momento(3, "impacto", 1)]
    sd["audios"] = {"efeitos:dark drone": {"arquivo": amb, "dur": 2}, "efeitos:cinematic hit impact": {"arquivo": hit, "pico": 0.05}}
    saida = SR.gerar_saida(base, p)
    assert saida.endswith("_sound_design.mp4") and abs(_dur(saida) - 6) < 0.4 and os.path.isfile(video)  # o original fica
    # a página e as rotas (num base temporário)
    SR.salvar_projeto(base, p)
    monkeypatch.setattr(SR, "pasta_projeto", lambda b, pid="": os.path.join(base, SR.PASTA_PROJETOS, pid) if pid else os.path.join(base, SR.PASTA_PROJETOS))
    monkeypatch.setattr(SR, "carregar_projeto", lambda b, pid: json.load(open(os.path.join(base, SR.PASTA_PROJETOS, pid, "projeto.json"))))
    c = A.app.test_client()
    assert "🎧 Sound design" in c.get("/sound-design").get_data(as_text=True)
    e = c.get(f"/sound-design/{p['id']}/estado").get_json()
    assert e["blocos"][0]["emocao"] == "tensao" and e["tem_texto"] and e["video"]
    with pytest.raises(ValueError):
        SR.criar_projeto(base, str(tmp_path / "nada.txt"))


def test_montagem_do_estudio_com_sound_design(tmp_path, synthetic_audio):
    """A montagem normal com o plano: acentos no mix dos efeitos + ambiente/música antes do mux."""
    from PIL import Image
    from prompt_builder import VideoSegment
    import video_assembler as va
    segs = []
    for k, (a, b) in enumerate([(0, 4.7), (4.7, 9.469)]):
        p = tmp_path / f"f{k}.jpg"
        Image.new("RGB", (320, 180), (80 * k, 60, 120)).save(p)
        segs.append(VideoSegment(a, b, "pexels", "q", media_type="image", override_source={"source": "local_file", "value": str(p), "kind": "image"}))
    amb = _tom(str(tmp_path / "amb.wav"), 3, ruido=True)
    mus = _tom(str(tmp_path / "mus.wav"), 20, 220)
    hit = _tom(str(tmp_path / "hit.wav"), 0.3, 900)
    plano = {"blocos": [{"start": 0, "end": 4.7, "emocao": "tensao", "ambiente": amb, "musica": mus},
                        {"start": 4.7, "end": 9.469, "emocao": "calma", "ambiente": amb, "musica": ""}],
             "momentos": [{"t": 4.7, "forca": 1}], "acentos": {"impacto": {"arquivo": hit, "pico": 0.05}}, "mix": True}
    out = va.assemble_video(segs, synthetic_audio, str(tmp_path / "o.mp4"), str(tmp_path / "w"),
                            site_cfg={"orientation": "16:9", "export_quality": "480p", "assembly_fetch_concurrency": 2,
                                      "_sound_design": plano, "sons_auto": {"transicoes": False, "cenas": False, "destaques": False}})
    assert abs(va._probe_duration(out) - 9.469) < 0.3
    assert os.path.exists(tmp_path / "w" / "_narracao_com_sons.wav") and os.path.exists(tmp_path / "w" / "_narracao_sound_design.wav")


def test_atalho_em_qualquer_video_do_site(tmp_path):
    """O 🎧 que aparece em qualquer vídeo/áudio do site: o arquivo vem pela própria rota que o mostra."""
    from flask import Flask, send_file
    assert SR._url_local("/job/abc/final?v=2") == "/job/abc/final?v=2"
    assert SR._url_local("http://127.0.0.1:5050/x/y.mp4") == "/x/y.mp4"
    assert SR._url_local("https://evil.com/x.mp4") == "" and SR._url_local("//evil.com/x") == ""
    som = _tom(str(tmp_path / "voz.wav"), 2)
    mini = Flask("mini")

    @mini.route("/gerar-voz/arquivo/7")
    def _a():
        return send_file(som, mimetype="audio/wav")

    @mini.route("/pagina")
    def _b():
        return "<html></html>"
    p = SR.criar_de_url(mini, str(tmp_path), "/gerar-voz/arquivo/7")
    assert not p["video"] and p["fonte"].endswith("original.wav") and os.path.isfile(p["fonte"]) and abs(p["total_duration"] - 2) < 0.2
    with pytest.raises(ValueError):
        SR.criar_de_url(mini, str(tmp_path), "/pagina")
    src = "".join(open("templates/" + n, encoding="utf-8").read() for n in ("base_classica.html", "_base_scripts.html"))  # v84_405
    assert "/sound-design?url=" in src and "item('/sound-design'" in src


def test_drop_da_musica_cai_no_climax(tmp_path):
    """🎵 v84_403: música calma 10 s → forte depois; o clímax do bloco em 6 s → a música começa ~4 s depois do 0."""
    mus = str(tmp_path / "drop.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=10", "-f", "lavfi", "-i", "sine=f=220:d=10",
                    "-filter_complex", "[0]volume=0.05[a];[1]volume=0.9[b];[a][b]concat=n=2:v=0:a=1", "-ar", "48000", mus], check=True)
    pico = SD.pico_musica(mus)
    assert 9 <= pico <= 11
    plano = {"blocos": [{"start": 0, "end": 12, "ambiente": "", "musica": mus, "climax": 6.0, "pico_musica": pico}], "momentos": []}
    ent = []
    partes, _a, mus_r = SD._filtro_camadas(plano, False, ent)
    assert mus_r and f"atrim={pico - 6.0:.3f}" in partes[0] and "if(lt(t," in partes[0]
    nar = _tom(str(tmp_path / "nar.wav"), 12)
    out = SD.aplicar(nar, plano, str(tmp_path / "o.wav"))
    assert abs(_dur(out) - 12) < 0.3
    # sem clímax no bloco: do começo, sem curva
    plano["blocos"][0]["climax"] = None
    partes, _a, _m = SD._filtro_camadas(plano, False, [])
    assert "atrim=0.000" in partes[0] and "if(lt" not in partes[0]
    sd = SD.vazio()
    sd["blocos"] = [SD.novo_bloco(0, 30, "tensao", "", "suspense")]
    sd["momentos"] = [SD.novo_momento(10, "virada", 2), SD.novo_momento(22, "revelacao", 3)]
    sd["audios"] = {"musica:suspense": {"arquivo": mus, "pico_musica": pico}}
    assert SD.para_montar({"sound_design": sd})["blocos"][0]["climax"] == 22.0  # o mais forte
