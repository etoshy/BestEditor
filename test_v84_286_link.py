"""🔗 v84_286 — Link → vídeo pronto: comentários (yt-dlp / colados), modo comentar/explicar/auto, fila e etapas."""
import json
import os
import subprocess
import time

import pytest

import curtos_link as CL


def test_ler_info_ytdlp_e_colados():
    j = {"title": "He stopped to help", "description": "#marathon", "uploader": "run", "view_count": 2_300_000, "like_count": 80000,
         "comment_count": 1500, "comments": [
             {"text": "why did he stop??", "like_count": 12000, "parent": "root"},
             {"text": "he was right", "like_count": 900, "parent": "root"},
             {"text": "reply", "like_count": 99999, "parent": "abc"},
             {"text": "why did he stop??", "like_count": 3, "parent": "root"}]}
    i = CL.ler_info_ytdlp(j)
    assert [c["texto"] for c in i["comentarios"]] == ["why did he stop??", "he was right"] and i["views"] == 2_300_000
    t = CL.texto_para_ia(i)
    assert "2.3M views" in t and "(12.0K likes) [?] why did he stop??" in t and "UNCONFIRMED" in t
    cs = CL.comentarios_colados("why did he stop?? 12K\n- he was right 340 curtidas\nlol\n")
    assert cs[0] == {"texto": "why did he stop??", "curtidas": 12000, "autor": ""} and cs[1]["curtidas"] == 340 and cs[2]["texto"] == "lol"
    assert CL.texto_para_ia({}) == ""


def test_modo():
    assert "EXPLAIN WHAT IS HAPPENING" in CL.regra_modo("explicar") and "COMMENTARY" in CL.regra_modo("comentario")
    assert "[EXPLAIN]" in CL.regra_modo("auto")
    assert CL.modo_escolhido("[EXPLAIN] How he did it", "auto") == "explicar"
    assert CL.modo_escolhido("[COMMENTARY] x", "auto") == "comentario"
    assert CL.modo_escolhido("x", "explicar") == "explicar" and CL.modo_escolhido("x", "auto") == ""
    assert CL.limpar_marca("[EXPLAIN]  How") == "How"


def test_baixar_info_falha_nao_quebra(monkeypatch):
    def falso(*a, **k):
        raise subprocess.TimeoutExpired("yt", 1)
    monkeypatch.setattr(subprocess, "run", falso)
    r = CL.baixar_info("https://www.tiktok.com/@x/video/1")
    assert r["ok"] is False and r["comentarios"] == []


ROT = {"titulo_video": "The finish line choice", "descricao": "[EXPLAIN] How marathon rules work", "hashtags": ["#run"],
       "roteiro_en": "x", "roteiro_pt": "x", "ganchos": [], "finais": [], "titulos": [{"en": "The finish line choice", "pt": "A escolha"}],
       "blocos": [{"funcao": "gancho", "fala_en": "[gasp] Two seconds from the finish line…", "fala_pt": "A dois segundos…",
                   "cenas": [{"layout": "clipe", "material": "M1", "de": 0, "ate": 2, "query": "", "palavra": "", "efeito": "",
                              "entrada": "none", "destaque": {"alvo": "", "tipo": "", "texto": ""},
                              "sugestao": {"layout": "", "query": "", "por_que": ""}}], "sfx": []},
                  {"funcao": "pergunta", "fala_en": "Was he wrong?", "fala_pt": "Ele errou?", "cenas": [], "sfx": []}]}


def test_link_ate_o_roteiro_e_para_na_voz(tmp_path, monkeypatch):
    """Fluxo real da aba até o roteiro (sem TTS aqui → para com erro claro e o 🔁 fica disponível)."""
    import app as A
    import curtos_comentario as CC
    import curtos_rotas as R
    import ia_servico
    clip = str(tmp_path / "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=360x640:r=30:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", clip], check=True)
    vistos = []

    def chamar(recurso, sis, conteudo, schema=None, **kw):
        txt = conteudo if isinstance(conteudo, str) else " ".join(b.get("text", "") for b in conteudo if isinstance(b, dict))
        vistos.append(txt)
        if "momentos" in (schema or {}).get("properties", {}):
            return {"momentos": [{"de": 0, "ate": 2, "o_que": "um corredor cai"}, {"de": 2, "ate": 4, "o_que": "outro ajuda"}], "resumo": "corrida"}
        return ROT
    monkeypatch.setattr(ia_servico, "chamar", chamar)
    monkeypatch.setattr(ia_servico, "motivo_desligado", lambda *a, **k: None)
    monkeypatch.setattr(CC, "_baixador_padrao", lambda url, d: (__import__("shutil").copy(clip, os.path.join(d, "original.mp4")), os.path.join(d, "original.mp4"))[1])
    monkeypatch.setattr(CL, "baixar_info", lambda url, n=60, timeout=90: {"ok": True, "titulo": "He stopped", "descricao": "", "views": 1000,
                                                                     "comentarios": [{"texto": "how is that allowed??", "curtidas": 500, "autor": ""}]})
    tts = R.CB.get("tts")
    R.CB["tts"] = None
    try:
        c = A.app.test_client()
        assert c.get("/curtos/link").status_code == 200
        r = c.post("/curtos/link/novo", json={"link": "https://www.tiktok.com/@x/video/123", "modo": "explicar", "comentarios": "is he ok? 2K"}).get_json()
        assert r["ok"], r
        pid = r["criados"][0]
        for _ in range(300):
            v = next(x for x in c.get("/curtos/link/estado").get_json()["videos"] if x["id"] == pid)
            if not v["rodando"]:
                break
            time.sleep(0.2)
        assert "voz" in v["erro"].lower(), v
        assert v["roteiro"].startswith("Two seconds") and "[gasp]" in v["roteiro_tags"]
        assert v["titulos"][0]["en"] == "The finish line choice" and v["n_comentarios"] == 2 and v["modo_usado"] == "explicar"
        assert v["descricao"] == "How marathon rules work" and v["titulo"] == "He stopped"
        roteiro = [t for t in vistos if "WHAT VIEWERS SAY" in t][-1]
        assert "is he ok?" in roteiro and "how is that allowed??" in roteiro and "EXPLAIN WHAT IS HAPPENING" in roteiro
        assert c.post(f"/curtos/link/{pid}/refazer").get_json()["ok"]
        for _ in range(200):
            v = next(x for x in c.get("/curtos/link/estado").get_json()["videos"] if x["id"] == pid)
            if not v["rodando"]:
                break
            time.sleep(0.1)
        assert "voz" in v["erro"].lower()  # 🔁 pulou o que já estava feito (não baixou nem escreveu de novo)
        assert len([t for t in vistos if "WHAT VIEWERS SAY" in t]) == 1
    finally:
        R.CB["tts"] = tts
        import curtos as CT
        for x in CT.listar(A.BASE_DIR):
            q = CT.carregar(A.BASE_DIR, x["id"])
            if (q.get("link_rapido") or {}).get("link") == "https://www.tiktok.com/@x/video/123":
                CT.excluir(A.BASE_DIR, x["id"])
