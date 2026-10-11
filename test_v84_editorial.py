"""
🗞 Quadros editoriais (o estilo "documentário editorial" dos vídeos de referência):
catálogo, validação, desenho de cada tipo (16:9 e 9:16), o passe do ffmpeg
(post desfoca, título com o vídeo nas letras, bilhetes com o vídeo do trecho na
moldura), prévia do Estúdio, salvar e a IA.
"""
import json
import os
import subprocess

import pytest

import dp_editorial as E


def _clip(caminho, cor, dur=6.0, W=320, H=180):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={cor}:s={W}x{H}:r=30:d={dur}", "-f", "lavfi", "-i",
                    f"sine=f=330:d={dur}", "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    str(caminho)], check=True)
    return str(caminho)


def _px(video, t, x, y):
    from PIL import Image
    png = video + f".{t}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", video, "-frames:v", "1", png], check=True)
    return Image.open(png).convert("RGB").getpixel((x, y))


def _dur(v):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", v],
                                capture_output=True, text=True).stdout)


def test_catalogo_exemplos_e_prompt():
    assert len(E.TIPOS) == 14 and set(E.EXEMPLOS) == set(E.TIPOS)
    ed = E.para_editor()
    for tipo in E.TIPOS:
        q = E.exemplo(tipo, 3.0)
        assert q["tipo"] == tipo and q["start"] == 3.0 and q["end"] > 4.0
        assert {c["k"] for c in ed[tipo]["campos"]} >= {"cor"}
        assert f"- {tipo} = " in E.bloco_para_prompt()
    assert ed["terminal"]["camada"] == "tela" and ed["post"]["camada"] == "sobre" and ed["titulo_video"]["camada"] == "mascara"


def test_normalizar():
    assert E.normalizar({"tipo": "nada"}) is None and E.normalizar("x") is None
    q = E.normalizar({"tipo": "terminal", "start": 2, "end": 2.5, "linhas": ["a", "b"], "cor": "vermelho", "fundo": "neon"})
    assert q["end"] - q["start"] >= 1.2 and q["linhas"] == "a\nb" and q["cor"] == "" and q["fundo"] == ""
    assert E.normalizar({"tipo": "mural", "imagens": "bib:1, bib:2"})["imagens"] == ["bib:1", "bib:2"]
    assert E.normalizar({"tipo": "post", "rede": "orkut"})["rede"] == "x"
    assert E.normalizar({"tipo": "numero", "start": 9.5, "end": 14}, duracao=10) is None  # sobra menos de 1,2 s
    assert E.normalizar({"tipo": "numero", "ate": "98,5"})["ate"] == 98.5


@pytest.mark.parametrize("W,H", [(320, 180), (180, 320)])
@pytest.mark.parametrize("tipo", sorted(E.TIPOS))
def test_cada_tipo_desenha(tipo, W, H):
    q = E.exemplo(tipo)
    dur = q["end"] - q["start"]
    ctx = E.novo_ctx()
    meio = E.desenhar(q, dur * 0.6, W, H, ctx)
    assert meio.size == (W, H) and meio.mode == "RGBA"
    camada = E.TIPOS[tipo]["camada"]
    if camada == "tela":
        assert meio.getpixel((W // 2, H - 3))[3] == 255  # cobre a cena
        assert E.desenhar(q, 0, W, H, ctx).getpixel((W // 2, H - 3))[3] < 40  # entra com fade (o vídeo aparece)
    elif camada == "sobre" and tipo != "post":
        assert meio.getpixel((W - 2, H - 2))[3] == 0  # o vídeo continua aparecendo
    if tipo == "titulo_video":
        assert E.mascara(q, dur * 0.6, W, H).getbbox() is not None


def test_simbolos_que_a_fonte_nao_tem():
    f = E._f("serif", 40)
    assert E._sem_glifo(f.path, 40, "∇") and not E._sem_glifo(f.path, 40, "a") and not E._sem_glifo(f.path, 40, "é")
    assert "DejaVu" in E._fonte_do_char(f, "∂").path and E._fonte_do_char(f, "x") is f


def test_print_sem_rede_cai_na_pagina_montada(tmp_path):
    assert E.capturar_print("ftp://x", str(tmp_path)) is None
    q = E.normalizar({"tipo": "pagina", "url": "https://exemplo.invalido/noticia", "titulo": "Manchete", "site": "exemplo.com"})
    assert E.desenhar(q, 2.0, 320, 180, E.novo_ctx()).getpixel((160, 175))[3] == 255


def test_passe_do_ffmpeg(tmp_path):
    from PIL import Image
    base = _clip(tmp_path / "base.mp4", "red", 12.0)
    foto = tmp_path / "foto.png"
    Image.new("RGB", (200, 150), (20, 200, 40)).save(foto)
    itens = [
        {"tipo": "numero", "start": 0.2, "end": 2.6, "de": 1, "ate": 9},
        {"tipo": "titulo_video", "start": 2.8, "end": 5.6, "titulo": "TESTE", "subtitulo": "def"},
        {"tipo": "bilhetes", "start": 5.8, "end": 8.6, "notas": "a\nb"},
        {"tipo": "mural", "start": 8.8, "end": 11.6, "imagens": ["bib:f"], "citacoes": "x"},
    ]
    out = E.aplicar_editoriais(base, str(tmp_path / "o.mp4"), itens, 320, 180, str(tmp_path / "w"), imagens={"bib:f": str(foto)})
    assert abs(_dur(out) - 12.0) < 0.15
    assert subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", out],
                          capture_output=True, text=True).stdout.strip() == "audio"
    r, g, b = _px(out, 1.5, 240, 120)  # número: papel bege
    assert r > 170 and g > 160 and b > 140 and abs(r - g) < 30
    assert max(_px(out, 4.6, 5, 5)) < 40  # título: fundo preto
    jx, jy, jw, jh = E.janela(E.normalizar(itens[2]), 320, 180)
    r, g, b = _px(out, 7.5, jx + jw // 2, jy + jh // 2)  # bilhetes: o vídeo do trecho dentro da moldura
    assert r > 150 and g < 90
    assert _px(out, 11.9, 160, 90)[0] > 150  # depois dos quadros, o vídeo volta


def test_post_desfoca_o_video(tmp_path):
    from PIL import Image
    src = tmp_path / "xadrez.png"
    im = Image.new("RGB", (320, 180), (0, 0, 0))
    for x in range(0, 320, 8):
        for y in range(0, 180, 8):
            if (x // 8 + y // 8) % 2:
                im.paste((255, 255, 255), (x, y, x + 8, y + 8))
    im.save(src)
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(src), "-t", "4", "-r", "30", "-pix_fmt", "yuv420p", base], check=True)
    out = E.aplicar_editoriais(base, str(tmp_path / "o.mp4"), [{"tipo": "post", "start": 0.5, "end": 3.5, "texto": "oi"}], 320, 180, str(tmp_path / "w"))
    antes = [_px(out, 0.1, x, 10)[0] for x in range(2, 30, 3)]
    durante = [_px(out, 2.0, x, 10)[0] for x in range(2, 30, 3)]
    assert max(antes) - min(antes) > 150 and max(durante) - min(durante) < 60


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_salvar_e_ia(A):
    jid = "v84ed"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 20.0, "media_library": [],
                    "pending_segments": [{"start": i * 4.0, "end": i * 4.0 + 4, "provider": "pexels", "query": "x", "media_type": "image"} for i in range(5)],
                    "segment_previews": [{"index": i, "ok": False} for i in range(5)], "overlays": [], "cutaway_suggestions": [],
                    "segments": [{"start": 0, "end": 4, "text": "O número chegou a 98 por cento."}]}
    c = A.app.test_client()
    assert c.get("/editorial/exemplo/ficha").get_json()["tipo"] == "ficha" and c.get("/editorial/exemplo/x").status_code == 404
    img = c.post(f"/job/{jid}/editorial/previa", json={"item": {"tipo": "numero", "start": 0, "end": 4, "ate": 98}, "t": 2})
    assert img.status_code == 200 and img.mimetype == "image/png"
    assert c.post(f"/job/{jid}/editorial/previa", json={"item": {"tipo": "?"}}).status_code == 400
    html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
    assert 'id="tab-editorial"' in html and 'id="layerEd"' in html and '"editorial_tipos"' in html
    form = {"acao": "salvar", **{f"seg_{i}_start": str(i * 4.0) for i in range(5)}, **{f"seg_{i}_end": str(i * 4.0 + 4) for i in range(5)},
            "editoriais_json": json.dumps([{"tipo": "numero", "start": 1, "end": 5, "ate": 98}, {"tipo": "?"}])}
    assert c.post(f"/job/{jid}/confirm-segments", data=form, headers={"X-Requested-With": "fetch"}).status_code == 200
    assert [q["tipo"] for q in A._JOBS[jid]["editoriais"]] == ["numero"]
    r = c.post(f"/job/{jid}/edicao/prompt", json={"direcao": "sys_tudo", "segmentos": A._JOBS[jid]["pending_segments"]}).get_json()
    assert "Quadros editoriais" in r["prompt"] and "- ficha = " in r["prompt"] and '"editoriais"' in r["prompt"]
    resp = {"editoriais": [{"tipo": "numero", "start": 1, "end": 5, "ate": 98, "sufixo": "%"}, {"tipo": "inventado"}]}
    r = c.post(f"/job/{jid}/edicao/resposta", json={"texto": json.dumps(resp)}).get_json()
    assert r["ok"] and len(r["editoriais"]) == 1 and r["editoriais"][0]["id"] and any("inventado" in a for a in r["avisos"])
