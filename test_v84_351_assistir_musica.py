"""v84_351: 👀 Assistir posts (temporário, carrossel = vários players, notas por vídeo) + 🎵 música e 📍 local do post."""
import os
import subprocess
import time

import assistir_posts as AP
import curtos as CT
import curtos_comentario as CC
import curtos_link as CL
from test_v84_320_lote_por_etapa import _app


def _mp4(cam):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x284:d=1:r=10", "-pix_fmt", "yuv420p", cam],
                   check=True, timeout=60)


def test_musica_e_local():
    j = {"track": "Everything In Its Right Place", "artist": "Radiohead", "location": "Ilhas Faroés", "title": "x"}
    i = CL.ler_info_ytdlp(j)
    assert i["musica"] == "Everything In Its Right Place · Radiohead" and i["local"] == "Ilhas Faroés"
    assert CL.musica_do_post({"track": "original sound - fulano", "artist": "fulano"}) == ""
    assert CL.musica_do_post({"track": "Dexter - The blood theme", "artists": ["Geek Music"]}) == "Dexter - The blood theme · Geek Music"
    assert CL.local_do_post({"location": {"name": "Lisboa"}}) == "Lisboa"
    txt = CL.texto_para_ia(dict(i, comentarios=[]))
    assert "Location tagged by the creator: Ilhas Faroés" in txt and "Song on the post" in txt


def test_cartao_musica_local_editavel(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    pid = cl.post("/curtos/link/novo", json={"link": "https://a.com/1"}).get_json()["criados"][0]
    with CT._TRAVA:
        p = CT.carregar(base, pid)
        CC.dados(p)["info_link"] = {"musica": "Floating in Reverie · Moayad Aljabal", "local": "Ilhas Faroés", "comentarios": []}
        CT.salvar(base, p)
    v = next(x for x in cl.get("/curtos/link/estado").get_json()["videos"] if x["id"] == pid)
    assert v["musica"] == "Floating in Reverie · Moayad Aljabal" and v["local"] == "Ilhas Faroés" and not v["local_editado"]
    j = cl.post(f"/curtos/link/{pid}/editar", json={"local": "Vágar, Ilhas Faroé", "musica": ""}).get_json()
    v = next(x for x in j["videos"] if x["id"] == pid)
    assert v["local"] == "Vágar, Ilhas Faroé" and v["local_editado"] and v["musica"] == "Floating in Reverie · Moayad Aljabal"
    assert "trust it): Vágar, Ilhas Faroé" in CC.conteudo_roteiro(base, CT.carregar(base, pid))


def test_assistir_sessao_carrossel_e_apagar(tmp_path):
    base = str(tmp_path)
    sid = AP.nova_sessao(base)

    def baixar(url, pasta):
        n = 3 if "carrossel" in url else 1
        if "quebrado" in url:
            raise RuntimeError("\x1b[0;31mERROR:\x1b[0m login required")
        out = []
        for k in range(1, n + 1):
            c = os.path.join(pasta, f"item_{k}.mp4")
            _mp4(c)
            out.append(c)
        return out
    info = lambda u: {"titulo": "post " + u[-1], "musica": "Song · Band", "local": "Faroé"}  # noqa: E731
    AP.adicionar(base, sid, ["https://ig.com/p/carrossel", "https://ig.com/reel/1", "https://ig.com/reel/1", "https://ig.com/quebrado",
                             "nao-e-link"], baixar, info, esperar=True)
    e = {i["url"]: i for i in AP.estado(sid)}
    assert len(e) == 3  # repetido e não-link fora
    assert e["https://ig.com/p/carrossel"]["videos"] == ["item_1.mp4", "item_2.mp4", "item_3.mp4"]
    assert e["https://ig.com/reel/1"]["estado"] == "pronto" and e["https://ig.com/reel/1"]["info"]["musica"] == "Song · Band"
    assert e["https://ig.com/quebrado"]["estado"] == "erro" and "login required" in e["https://ig.com/quebrado"]["erro"]
    assert "\x1b" not in e["https://ig.com/quebrado"]["erro"]
    assert AP.arquivo(base, sid, 1, "item_2.mp4") and AP.arquivo(base, sid, 1, "../../x") is None
    AP.apagar_sessao(base, sid)
    assert not os.path.isdir(os.path.join(AP.raiz(base), sid)) and AP.estado(sid) == []
    # faxina: sessão esquecida (> 6 h) some sozinha
    velha = os.path.join(AP.raiz(base), "abcdef123456")
    os.makedirs(velha)
    os.utime(velha, (time.time() - 7 * 3600,) * 2)
    assert AP.faxina(base) == 1 and not os.path.isdir(velha)


def test_rotas_assistir(tmp_path, monkeypatch):
    import app as A
    monkeypatch.setattr(AP, "_baixar_padrao", lambda u, p: (_mp4(os.path.join(p, "item_1.mp4")), [os.path.join(p, "item_1.mp4")])[1])
    monkeypatch.setattr(AP, "_info_padrao", lambda u: {"titulo": "oi"})
    cl = A.app.test_client()
    html = cl.get("/assistir").get_data(as_text=True)
    sid = html.split("const SID = ")[1].split(";")[0].strip('"')
    assert "pôr o tempo" in html or "data-tempo" in html
    j = cl.post(f"/assistir/{sid}/adicionar", json={"links": "https://www.instagram.com/reel/abc/\nhttps://x.com/y"}).get_json()
    assert j["ok"] and j["novos"] == 2
    for _ in range(100):
        it = cl.get(f"/assistir/{sid}/estado").get_json()["itens"]
        if all(i["estado"] in ("pronto", "erro") for i in it):
            break
        time.sleep(0.1)
    assert cl.get(f"/assistir/{sid}/1/item_1.mp4").status_code == 200
    assert cl.get(f"/assistir/{sid}/1/..%2F..%2Fapp.py").status_code == 404
    assert cl.post(f"/assistir/{sid}/apagar").get_json()["ok"]
    assert cl.get(f"/assistir/{sid}/1/item_1.mp4").status_code == 404
    assert cl.post("/assistir/naoexiste12/adicionar", json={"links": "https://a.com"}).status_code == 400
