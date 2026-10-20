"""v84_185: 🧍 as personagens do canal por cima do vídeo, só quando falam — o roteiro com as tags casado com o tempo
das palavras do áudio; pose pela emoção, virada pro centro; entrada/saída e a boca no ffmpeg."""
import io
import json
import os
import shutil
import subprocess
import zipfile

import numpy as np
import pytest
from PIL import Image, ImageDraw

import marca_visual as mv
import personagens_editor as pe
import personagens_pod as pp
from test_v84_183_personagens_pod import _png

ROTEIRO = ("[narrador] Was passiert wenn ein Stern stirbt? Niemand weiß es genau. "
           "[mira|curiosa] Und warum leuchtet er dann so hell? "
           "[vanta|ironica] Weil er sich gern in Szene setzt. "
           "[narrador] Die Antwort liegt im Kern des Sterns. [excited] Ganz tief drin.")


def _palavras(texto, erro=None):
    """Palavras "do Whisper" (sem as tags), 0,4 s cada; `erro` troca algumas palavras (o Whisper ouve diferente)."""
    import re
    ws, t = [], 0.0
    for w in re.sub(r"\[[^\]]*\]", " ", texto).split():
        ws.append({"word": (erro or {}).get(w, w), "start": round(t, 2), "end": round(t + 0.35, 2)})
        t += 0.4
    return ws


def test_linha_do_tempo():
    falas = pe.linha_do_tempo(ROTEIRO, _palavras(ROTEIRO, {"leuchtet": "leichtet", "Szene": "Zene"}), ["mira", "vanta"])
    quem = [(f["slug"], f["emocao"]) for f in falas]
    assert quem == [(None, ""), ("mira", "curiosa"), ("vanta", "ironica"), (None, "")]
    mira = falas[1]
    assert mira["texto"].startswith("Und warum") and mira["start"] == pytest.approx(4.0) and len(mira["palavras"]) == 7
    # tag de voz cadastrada que não é personagem = narrador; voz mapeada pra personagem
    t2 = "[voz_narrador] Hallo Welt. [voz_mira] Ich bin da. [excited] Wirklich!"
    f2 = pe.linha_do_tempo(t2, _palavras(t2), ["mira"], {"voz_mira": "mira"}, ["voz_narrador", "voz_mira"])
    assert [f["slug"] for f in f2] == [None, "mira"] and f2[1]["texto"] == "Ich bin da. Wirklich!"


def _poses():
    def p(a, lado, grupo="reacao", boca=None):
        return {"arquivo": a, "caminho": a, "aprovada": True, "lado": lado, "grupo": grupo, "texto": a, "mestre": False, "boca": boca}
    return [p("mira_neutra_esq.png", "esq", boca="b.png"), p("mira_neutra_dir.png", "dir"), p("mira_curiosa_dir.png", "dir"),
            p("mira_curiosa_esq.png", "esq", boca="b.png"), p("mira_lupa_dir.png", "dir", "objeto")]


def test_escolher_pose():
    ps = _poses()
    assert pe.escolher_pose(ps, "curiosa", "esquerda")["arquivo"] == "mira_curiosa_dir.png"  # na esquerda olha pra direita
    assert pe.escolher_pose(ps, "curiosa", "direita")["arquivo"] == "mira_curiosa_esq.png"
    assert pe.escolher_pose(ps, "", "direita")["arquivo"] == "mira_neutra_esq.png"
    assert pe.escolher_pose(ps, "", "direita", evitar="mira_neutra_esq.png")["arquivo"] != "mira_neutra_esq.png"


def test_aparicoes_juntam_e_respeitam_lado():
    falas = [{"slug": "mira", "emocao": "curiosa", "start": 1.0, "end": 2.0, "palavras": [[1.0, 1.4], [1.5, 2.0]], "texto": "a"},
             {"slug": None, "emocao": "", "start": 2.1, "end": 2.5, "palavras": [[2.1, 2.5]], "texto": "n"},
             {"slug": "mira", "emocao": "", "start": 2.6, "end": 3.5, "palavras": [[2.6, 3.5]], "texto": "b"},
             {"slug": "vanta", "emocao": "", "start": 4.0, "end": 4.3, "palavras": [[4.0, 4.3]], "texto": "curta"},
             {"slug": "vanta", "emocao": "", "start": 8.0, "end": 9.5, "palavras": [[8.0, 9.5]], "texto": "c"}]
    pers = [{"slug": "mira", "nome": "Mira", "poses": _poses()}, {"slug": "vanta", "nome": "Vanta", "poses": []}]
    cfg = dict(pe.PADRAO, lados={"mira": "direita"}, frequencia=1)
    aps, avisos = pe.aparicoes(falas, pers, cfg, 20.0)
    assert len(aps) == 1 and aps[0]["start"] == pytest.approx(0.85) and aps[0]["end"] == pytest.approx(3.95)  # juntou as 2 falas
    assert aps[0]["lado"] == "direita" and aps[0]["x_percent"] > 50 and aps[0]["pose"].endswith("_esq.png")
    assert aps[0]["boca"] == "b.png" and aps[0]["boca_janelas"] == [[1.0, 2.0], [2.6, 3.5]]
    assert aps[0]["size_percent"] == pytest.approx(0.72 / 0.95 * 1080 / 1.5 / 1920 * 100, abs=0.01)
    assert any("Vanta" in a for a in avisos)  # fala mas não tem pose


def _canal(tmp_path, ativo=True):
    buf = io.BytesIO()
    poses = {"formato": "personagens_pod_v1", "personagem": "mira", "texto_fixo": {"trava": "M"},
             "poses": [{"arquivo": "mira_curiosa_dir.png", "prompt": "c", "grupo": "reacao"},
                       {"arquivo": "mira_curiosa_dir_boca.png", "tipo": "boca", "base": "mira_curiosa_dir.png", "prompt": "b"},
                       {"arquivo": "mira_neutra_dir.png", "prompt": "n", "grupo": "reacao"}]}
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ast/brand_guide.json", json.dumps({"schema": mv.SCHEMA, "project": {"name": "AST"}}))
        z.writestr("ast/pacote.json", json.dumps({"formato": mv.FORMATO_PACOTE, "slug": "ast",
                                                  "personagens_editor": {"ativo": ativo, "lados": {"mira": "esquerda"}}}))
        z.writestr("ast/assets/logo.png", _png())
        z.writestr("ast/personagens.json", json.dumps({"personagens": [{"slug": "mira", "nome": "Mira", "poses_json": "personagens/mira.json"},
                                                                       {"slug": "vanta", "nome": "Vanta"}]}))
        z.writestr("ast/personagens/mira.json", json.dumps(poses))
    base = str(tmp_path)
    mv.importar_zip(base, buf.getvalue())
    p = pp.criar_do_canal("ast", "mira", [], base=base)
    d = pp._pasta(p["id"], base)
    q = pp.carregar(p["id"], base)
    for a, cor in (("mira_curiosa_dir.png", (255, 0, 0, 255)), ("mira_curiosa_dir_boca.png", (0, 255, 0, 255)), ("mira_neutra_dir.png", (0, 0, 255, 255))):
        im = Image.new("RGBA", (1200, 1800), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([300, 300, 900, 1800], fill=cor)
        im.save(os.path.join(d, "imagens", a))
        q["imagens"][a].update(estado="aprovada", versoes=[{"local": a}], atual=0)
    pp.salvar(q, base)
    return base


def test_aplicar_no_projeto(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    base = _canal(tmp_path)
    job = {"orientation": "16:9", "total_duration": 12.0, "texto_falas": ROTEIRO,
           "overlays": [{"id": "x1", "source": {"source": "url", "value": "http://a"}, "start": 0, "end": 1}],
           "personagens_canal": {"canal": "ast", "config": {"frequencia": 1}}}
    jd = str(tmp_path / "job")
    r = pe.aplicar(job, jd, base, _palavras(ROTEIRO))
    assert r["n"] == 1 and r["de_onde"].startswith("o roteiro do áudio")
    assert any("Vanta" in a for a in r["avisos"])  # vanta fala mas não tem projeto
    ov = next(o for o in job["overlays"] if o.get("origem") == "personagem")
    assert ov["personagem"] == "mira" and ov["pose"] == "mira_curiosa_dir.png" and ov["lado"] == "esquerda"
    assert os.path.isfile(ov["source"]["value"]) and os.path.isfile(ov["boca_path"]) and ov["anim_in"] == "deslizar"
    assert job["overlays"][0]["id"] == "x1"  # os seus overlays ficam
    # mexer à mão: a aparição fica ao refazer; trocar a pose
    pe.trocar_pose(job, ov["id"], "mira_neutra_dir.png", base, jd)
    assert ov["manual"] and ov["pose"] == "mira_neutra_dir.png" and ov["boca_path"] is None
    pe.aplicar(job, jd, base, _palavras(ROTEIRO))
    assert [o["id"] for o in job["overlays"] if o.get("origem") == "personagem"] == [ov["id"]]
    est = pe.estado(job, base)
    assert est["canal"] == "ast" and est["aparicoes"][0]["pose"] == "mira_neutra_dir.png"
    assert [p["slug"] for p in est["personagens"]] == ["mira", "vanta"] and est["personagens"][0]["poses"]
    assert pe.remover(job) == 1 and len(job["overlays"]) == 1
    # sem roteiro / sem canal: erro claro
    with pytest.raises(pe.PersEdErro, match="roteiro"):
        pe.aplicar({"personagens_canal": {"canal": "ast"}}, jd, base, _palavras(ROTEIRO))
    with pytest.raises(pe.PersEdErro, match="canal"):
        pe.aplicar({"texto_falas": ROTEIRO}, jd, base, _palavras(ROTEIRO))


def test_auto_so_com_ativo(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    base = _canal(tmp_path, ativo=False)
    job = {"texto_falas": ROTEIRO, "personagens_canal": {"canal": "ast"}, "overlays": []}
    assert pe.auto(job, str(tmp_path / "j"), base, _palavras(ROTEIRO)) is None and job["overlays"] == []


def test_rotas_do_estudio(tmp_path, monkeypatch):
    import app as A
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    base = _canal(tmp_path)
    monkeypatch.setattr(A, "BASE_DIR", base)
    jid = "pers-teste"
    os.makedirs(A._job_dir(jid), exist_ok=True)
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "orientation": "16:9", "total_duration": 12.0,
                    "word_timestamps": _palavras(ROTEIRO), "overlays": [], "pending_segments": []}
    try:
        c = A.app.test_client()
        # o registrar guardou o BASE_DIR de verdade: usa as funções com o base do teste
        monkeypatch.setattr(pe, "estado", (lambda f: (lambda job, _b: f(job, base)))(pe.estado))
        monkeypatch.setattr(pe, "aplicar", (lambda f: (lambda job, jd, _b, pal, canal="", texto="", cfg_extra=None, **kw: f(job, jd, base, pal, canal, texto, cfg_extra, **kw)))(pe.aplicar))
        d = c.post(f"/job/{jid}/personagens/aplicar", json={"canal": "ast", "texto": ROTEIRO, "config": {"entrada": "aparecer"}}).get_json()
        assert d["n"] == 1 and d["overlays"][0]["_url"].endswith(d["overlays"][0]["id"]) and d["overlays"][0]["anim_in"] == "aparecer"
        oid = d["overlays"][0]["id"]
        d = c.post(f"/job/{jid}/personagens/{oid}", json={"lado": "direita", "boca": False}).get_json()
        ov = A._JOBS[jid]["overlays"][0]
        assert ov["lado"] == "direita" and ov["x_percent"] > 50 and ov["ancora"] == "centro" and ov["boca_desligada"] and ov["manual"]
        assert pe.para_render(ov)["boca_path"] is None
        d = c.post(f"/job/{jid}/personagens/{oid}/remover").get_json()
        assert d["overlays"] == []
        html = c.get(f"/job/{jid}/edit-segments?modo=estudio").get_data(as_text=True)
        assert 'id="tab-personagens"' in html and 'data-tab="personagens"' in html
    finally:
        A._JOBS.pop(jid, None)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_render_entra_desliza_e_boca(tmp_path):
    import video_assembler as va
    base = str(tmp_path / "base.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x3050a0:s=640x360:d=4:r=25", "-f", "lavfi",
                    "-i", "anullsrc=r=24000:cl=mono", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", base], check=True)
    im = Image.new("RGBA", (300, 450), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([80, 80, 220, 450], fill=(255, 0, 0, 255))
    im.save(tmp_path / "p.png")
    ImageDraw.Draw(im).rectangle([120, 120, 180, 180], fill=(0, 255, 0, 255))
    im.save(tmp_path / "b.png")
    ov = {"resolved_path": str(tmp_path / "p.png"), "media_type": "image", "start": 1.0, "end": 3.0, "size_percent": 30,
          "personagem": "mira", "x_percent": 2, "y_percent": 100, "anim_in": "deslizar", "anim_out": "aparecer", "anim_dur": 0.3,
          "lado": "esquerda", "boca_path": str(tmp_path / "b.png"), "boca_janelas": [[1.0, 2.5]]}
    out = str(tmp_path / "out.mp4")
    va.apply_overlays(base, [ov], out, 640, 360)

    def frame(t):
        f = str(tmp_path / "f.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", out, "-frames:v", "1", f], check=True)
        a = np.asarray(Image.open(f).convert("RGB")).astype(int)
        return ((a[..., 0] > 200) & (a[..., 1] < 80)).sum(), ((a[..., 1] > 200) & (a[..., 0] < 80)).sum()
    assert frame(0.5) == (0, 0)                    # antes: nada
    verm, _v = frame(2.8)
    assert verm > 1000                              # durante: a personagem
    assert frame(3.6)[0] == 0                       # depois: sumiu
    assert any(frame(t)[1] > 0 for t in (1.5, 1.56, 1.62, 1.68, 1.74))  # a boca abre em algum momento


def test_melhores_momentos_e_mascote_narrador():
    """v84_186: nem toda fala vira aparição (frequência + intervalo); mascote apresentador ilustra frases da narração."""
    ws = _palavras("Was ist das? Ein Stern. Er stirbt langsam und leuchtet. Dann explodiert er! Niemand weiß warum. "
                   "Es bleibt ein Rätsel. Wirklich seltsam? Ja.")
    falas = pe.falas_sem_roteiro(ws)
    pers = [{"slug": "mascote", "nome": "Mascote", "poses": _poses()}]
    cfg = dict(pe.PADRAO, narrador_personagem="mascote", frequencia=0.4, min_intervalo=3, boca=False)
    cands = pe.candidatos(falas, pers, cfg)
    assert len(cands) >= 4 and all(c["tipo"] == "narracao" for c in cands)
    esc = pe.escolher_momentos(cands, cfg)
    assert 1 <= len(esc) < len(cands)
    assert any("?" in c["texto"] or "!" in c["texto"] for c in esc)  # pergunta/exclamação ganham
    for a, b in zip(esc, esc[1:]):
        assert b["start"] - a["end"] >= 3 or a["end"] - b["start"] >= 3
    aps, _av = pe.montar(esc, pers, cfg, 60.0)
    assert aps and all(a["boca"] is None and a["boca_janelas"] == [] for a in aps)  # mascote narrando: sem boca
    # IA: escolhe os momentos, a pose e a animação (inválidos caem na regra)
    ia = {cands[0]["id"]: {"id": cands[0]["id"], "pose": "mira_lupa_dir.png", "entrada": "subir", "saida": "xx"}}
    aps, _av = pe.montar([cands[0]], pers, cfg, 60.0, ia=ia)
    assert aps[0]["pose"] == "mira_lupa_dir.png" and aps[0]["entrada"] == "subir" and aps[0]["saida"] == cfg["saida"]


def test_ia_escolhe(monkeypatch):
    import ia_servico
    visto = {}
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "personagens")

    def chamar(recurso, system, conteudo, schema=None, **kw):
        visto.update(system=system, conteudo=conteudo)
        return {"aparicoes": [{"id": 2, "pose": "mira_curiosa_esq.png", "entrada": "aparecer", "saida": "nenhuma"}, {"id": 99}]}
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    falas = pe.linha_do_tempo(ROTEIRO, _palavras(ROTEIRO), ["mira", "vanta"])
    pers = [{"slug": "mira", "nome": "Mira", "poses": _poses()}, {"slug": "vanta", "nome": "Vanta", "poses": _poses()}]
    cands = pe.candidatos(falas, pers, pe.PADRAO)
    r = pe.escolher_com_ia(cands, pers, pe.PADRAO, 1)
    assert r == [{"id": 2, "pose": "mira_curiosa_esq.png", "entrada": "aparecer", "saida": "nenhuma"}]  # id 99 não existe
    assert "Choose about 1 of the BEST moments" in visto["system"] and "mira_curiosa_esq.png" in visto["conteudo"]
    assert "[1]" in visto["conteudo"] and "Und warum" in visto["conteudo"]


def test_falas_exatas_do_pod(tmp_path, monkeypatch):
    """v84_187: o pod devolve quem falou quando ({{quem=…}} → <nome>.falas.json): o editor usa o tempo exato; a emoção
    continua vindo da tag do roteiro."""
    ws = _palavras(ROTEIRO)
    lista = [{"quem": "narrador", "voz": "perfil:n", "inicio": 0.0, "fim": 3.95, "texto": "x"},
             {"quem": "voz_mira", "voz": "perfil:m", "inicio": 4.0, "fim": 6.75, "texto": "y"},
             {"quem": "vanta", "voz": "perfil:v", "inicio": 6.8, "fim": 9.15, "texto": "z"},
             {"quem": "narrador", "voz": "perfil:n", "inicio": 9.2, "fim": 20, "texto": "w"}]
    f = pe.falas_do_pod(lista, ws, ["mira", "vanta"], {"voz_mira": "mira"})
    assert [x["slug"] for x in f] == [None, "mira", "vanta", None]
    assert f[1]["texto"].startswith("Und warum") and len(f[1]["palavras"]) == 7
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    base = _canal(tmp_path)
    job = {"orientation": "16:9", "total_duration": 12.0, "texto_falas": ROTEIRO, "falas_pod": [dict(x, quem=x["quem"].replace("voz_mira", "mira")) for x in lista],
           "overlays": [], "personagens_canal": {"canal": "ast", "config": {"frequencia": 1}}}
    r = pe.aplicar(job, str(tmp_path / "job"), base, ws)
    assert r["de_onde"].startswith("o pod") and r["n"] == 1
    ov = job["overlays"][0]
    assert ov["personagem"] == "mira" and ov["emocao"] == "curiosa" and ov["pose"] == "mira_curiosa_dir.png"


def test_ia_escolheu_pouco_a_regra_completa(tmp_path, monkeypatch):
    """v84_215: a IA devolveu 1 momento só — a regra completa até a frequência (antes o vídeo ficava com 1 aparição)."""
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pp"))
    base = _canal(tmp_path)
    rot = " ".join(f"[mira] Frage {k}? Wirklich seltsam, oder nicht? [narrador] Ja, das ist so. Und weiter geht es hier." for k in range(8))
    job = {"orientation": "16:9", "total_duration": 120.0, "texto_falas": rot, "overlays": [],
           "personagens_canal": {"canal": "ast", "config": {"frequencia": 0.6, "ia": True}}}
    chamado = []

    def ia_fake(cands, *a, **k):
        chamado.append(len(cands))
        return [{"id": cands[0]["id"], "pose": "", "entrada": "", "saida": ""}]
    monkeypatch.setattr(pe, "escolher_com_ia", ia_fake)
    r = pe.aplicar(job, str(tmp_path / "j"), base, _palavras(rot))
    assert chamado and r["por"] == "ia+regra" and r["n"] >= 3
