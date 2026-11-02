"""v84_330: curto de comentário "só com os meus vídeos" — cena que a IA mandou buscar fora do clipe volta pro clipe (vira 💡 sugestão)."""
import os
import subprocess

import curtos as CT
import curtos_comentario as CC


def _proj(tmp_path, monkeypatch, midia=None):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    p = CT.criar(base, "", "t", modelo="comentario")
    v = str(tmp_path / "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x284:duration=6", "-pix_fmt", "yuv420p", v],
                   check=True, timeout=60)
    m = CT.adicionar_midia(base, p, v, "video", "clip", "M")
    m["dur"] = 6.0
    if midia:
        p["config"]["midia"] = midia
    CT.salvar(base, p)
    return base, CT.carregar(base, p["id"])


def _resp(*cenas):
    return {"blocos": [{"funcao": "fato", "fala_en": f"line {k}", "fala_pt": "x", "cenas": [c]} for k, c in enumerate(cenas)],
            "ganchos": [], "finais": [], "titulos": [], "titulo_video": "t", "descricao": "d", "hashtags": []}


CLIPE = {"layout": "clipe", "material": "M1", "de": 1, "ate": 3, "query": "", "efeito": "", "entrada": "none"}
BANCO = {"layout": "video", "material": "", "query": "dark cave interior small blue light ahead", "efeito": "", "entrada": "none"}


def test_cena_de_banco_volta_pro_clipe_e_vira_sugestao(tmp_path, monkeypatch):
    base, p = _proj(tmp_path, monkeypatch)
    r = CC.ler_roteiro(_resp(CLIPE, BANCO), p)
    c = r["blocos"][1]["cenas"][0]
    assert c["layout"] == "materia" and c["material"] == "M1" and c["de"] == 3.0 and c["ate"] == 5.5  # logo depois da anterior
    assert c["sugestao"]["layout"] == "clipe_real" and "dark cave" in c["sugestao"]["query"]
    r = CC.ler_roteiro(_resp(BANCO), p)  # sem cena anterior: o começo do clipe
    assert r["blocos"][0]["cenas"][0]["material"] == "M1" and r["blocos"][0]["cenas"][0]["de"] == 0.0


def test_misto_e_cartao_ficam_como_estao(tmp_path, monkeypatch):
    base, p = _proj(tmp_path, monkeypatch, midia="misto")
    r = CC.ler_roteiro(_resp(CLIPE, BANCO), p)
    assert r["blocos"][1]["cenas"][0]["layout"] == "video"  # no misto o banco é permitido
    blocos = [{"cenas": [dict(CLIPE, layout="materia")]}, {"cenas": [{"layout": "cartao", "query": "texto"}]}]
    assert CC.segurar_no_clipe(p, blocos) == 0 and blocos[1]["cenas"][0]["layout"] == "cartao"


def test_prompt_autentico_pede_fatos_sobre_o_clipe(tmp_path, monkeypatch):
    base, p = _proj(tmp_path, monkeypatch)
    assert "OVER THE CLIP" in CC.sistema(p)
