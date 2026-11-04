"""v84_349: 🧩 vídeo composto — "link1, link2, link3" na mesma linha vira UM vídeo informativo (60 s+, não lista) com as fontes."""
import os
import subprocess

import curtos as CT
import curtos_comentario as CC
import curtos_link as CL
import curtos_rotas as CR
from test_v84_320_lote_por_etapa import _app


def test_separar_links():
    t = ("Praias\nhttps://a.com/1, https://b.com/2,https://c.com/3\nhttps://d.com/4\nhttps://e.com/5 https://f.com/6\n"
         "https://a.com/1, https://b.com/2, https://c.com/3\nAnimais: https://g.com/7 , https://h.com/8")
    r = CR._separar_grupos(t)
    assert r == [("https://a.com/1,https://b.com/2,https://c.com/3", "Praias"), ("https://d.com/4", "Praias"),
                 ("https://e.com/5", "Praias"), ("https://f.com/6", "Praias"), ("https://g.com/7,https://h.com/8", "Animais")]
    assert CR._separar_grupos("https://a.com/x?y=1,2") == [("https://a.com/x?y=1,2", "")]  # vírgula dentro do link: link normal
    seis = ", ".join(f"https://a.com/{k}" for k in range(6))
    assert CR._separar_grupos(seis)[0][0].count(",") == 4  # no máximo 5 fontes


def _baixador(base, falha=""):
    def baixar(b, pid, url, *a, **k):
        if url == falha:
            raise CT.CurtoErro("não baixou (teste)")
        d = CT.pasta(b, pid)
        os.makedirs(d, exist_ok=True)
        cam = os.path.join(d, f"_tmp_{abs(hash(url))}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x284:d=2:r=10", "-pix_fmt", "yuv420p", cam],
                       check=True, timeout=60)
        with CT._TRAVA:
            p = CT.carregar(b, pid)
            m = CT.adicionar_midia(b, p, cam, "video", "vídeo do link", "M", origem=url)
            CT.salvar(b, p)
        return m["id"]
    return baixar


def test_composto_cria_coleta_e_roteiro(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    r = cl.post("/curtos/link/novo", json={"link": "https://www.tiktok.com/@praia1/video/1, https://www.instagram.com/reel/X2/, "
                                                   "https://www.tiktok.com/@praia3/video/3\nhttps://a.com/solo", "duracao": 30}).get_json()
    assert r["ok"] and len(r["criados"]) == 2
    p = CT.carregar(base, r["criados"][0])
    assert p["config"]["composto"] == 3 and len(p["link_rapido"]["links"]) == 3 and p["titulo"].startswith("🧩")
    assert "duracao_alvo_s" not in p["config"] or not p["config"]["duracao_alvo_s"]  # 30 s pedido: o composto ignora (60+)
    assert "composto" not in CT.carregar(base, r["criados"][1])["config"]
    # coleta: baixa as 3 (uma falha não para), lê a legenda/comentários de cada
    monkeypatch.setattr(CC, "baixar_clipe", _baixador(base, falha="https://www.instagram.com/reel/X2/"))
    vistos = []
    monkeypatch.setattr(CL, "baixar_info", lambda u, n=60: vistos.append(u) or {"titulo": f"post {u[-3:]}", "comentarios": [
        {"texto": f"que lugar é esse? {u[-3:]}", "curtidas": 10}], "autor_handle": ""})
    pid = r["criados"][0]
    logs = []
    CR_reg = CR  # (as funções internas vêm do registrar — chamamos pela rota de refazer)
    import time
    monkeypatch.setattr(CC, "transcrever_clipe", lambda *a, **k: 0)
    monkeypatch.setattr(CC, "descrever_clipe", lambda *a, **k: None)
    monkeypatch.setattr(CC, "gerar_roteiro", lambda b, i, *a, **k: (_ for _ in ()).throw(CT.CurtoErro("parou no roteiro (teste)")))
    cl.post(f"/curtos/link/{pid}/refazer")
    for _ in range(300):
        if (CR.TAREFAS.get(pid) or {}).get("fim"):
            break
        time.sleep(0.05)
    q = CT.carregar(base, pid)
    assert len(CC.clipes(base, q)) == 2 and "parou no roteiro" in (CR.TAREFAS[pid]["erro"] or "")
    assert any("não baixaram" in x for x in [l if isinstance(l, str) else str(l) for l in q["link_rapido"].get("log") or []])
    assert len(CC.dados(q)["info_links"]) == 3 and len(vistos) == 3
    # o prompt: regra do composto + cada fonte
    sis, cont = CC.sistema(q), CC.conteudo_roteiro(base, q)
    assert "COMPOSITE VIDEO" in sis and "NOT A LIST" in sis and "INTERCUT" in sis and "M1…M3" in sis
    assert "60+ seconds" in cont and "## SOURCE M1 — by @praia1" in cont and "## SOURCE M2 — by @praia3" in cont
    assert "que lugar é esse? o/1" in cont
    # créditos de todas as fontes
    d = CL.com_fontes("Praias de verdade.", [(i["url"], i["info"]) for i in CC.dados(q)["info_links"]])
    assert d.endswith("Sources: @praia1 (TikTok) · https://www.instagram.com/reel/X2/ (Instagram) · @praia3 (TikTok)")
    assert CL.com_fontes(d, [("https://x.com/@a/1", {})]) == d  # não duplica
    v = next(x for x in cl.get("/curtos/link/estado").get_json()["videos"] if x["id"] == pid)
    assert len(v["links"]) == 3
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert "contarVideos" in html and "composto" in html


def test_composto_precisa_de_2_fontes(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    r = cl.post("/curtos/link/novo", json={"link": "https://a.com/1, https://b.com/2"}).get_json()
    pid = r["criados"][0]
    monkeypatch.setattr(CC, "baixar_clipe", _baixador(base, falha="https://b.com/2"))
    import time
    cl.post(f"/curtos/link/{pid}/refazer")
    for _ in range(300):
        if (CR.TAREFAS.get(pid) or {}).get("fim"):
            break
        time.sleep(0.05)
    assert "precisa de 2+ fontes" in CR.TAREFAS[pid]["erro"]
