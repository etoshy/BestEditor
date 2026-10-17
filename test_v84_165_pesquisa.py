"""v84_165: 📰 Buscador de casos e notícias (YouTube simulado, HTML do Google de exemplo, junção sem repetir)."""
import os

import pytest

import pesquisa_casos as pc

HTML = """<html><body><div id="rso">
<div class="MjjYud"><a href="https://www.bbc.com/news/unabomber-123?utm_source=x"><h3>Who was the Unabomber?</h3><span class="VuuXrf">BBC</span></a>
  <div class="VwiC3b">Ted Kaczynski mailed bombs for 17 years.</div></div>
<div class="MjjYud"><a href="/url?q=https://www.youtube.com/watch%3Fv%3DabcdefghijK&sa=U"><h3>Unabomber documentary</h3></a></div>
<div class="MjjYud"><a href="https://www.google.com/search?q=x"><h3>google interno</h3></a></div>
<div class="MjjYud"><a href="https://www.fbi.gov/history/famous-cases/unabomber"><h3>Unabomber — FBI</h3><cite>fbi.gov</cite></a></div>
</div></body></html>"""


class _YDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        assert "sp=CAMSAhAB" in url  # ordenado por visualizações
        def v(i, views, dur):
            return {"id": f"vid{i:08d}", "title": f"Video {i}", "channel": "Canal", "view_count": views, "duration": dur, "ie_key": "Youtube"}
        return {"entries": [v(1, 9_000_000, 1800), v(2, 5_000_000, 40), v(3, 4_000_000, 2400), v(4, 3_000_000, 1200),
                            v(5, 2_000_000, 3000), v(6, 1_000_000, 600), v(7, 500_000, 900)]}


class _FakeYtdlp:
    YoutubeDL = _YDL


def test_extrai_do_html_e_junta_sem_repetir():
    itens = pc.extrair_de_texto(HTML)
    assert [i["url"] for i in itens] == ["https://www.bbc.com/news/unabomber-123", "https://www.youtube.com/watch?v=abcdefghijK",
                                         "https://www.fbi.gov/history/famous-cases/unabomber"]
    assert itens[0]["fonte"] == "BBC" and "17 years" in itens[0]["trecho"]
    p = {"resultados": []}
    assert pc.adicionar_resultados(p, itens, "google", "1")["novos"] == 3
    r = pc.adicionar_resultados(p, pc.extrair_de_texto("https://bbc.com/news/unabomber-123\nhttps://youtu.be/abcdefghijK\nhttps://apnews.com/a"))
    assert r == {"novos": 1, "repetidos": 2, "total": 4}
    assert [x["tipo"] for x in p["resultados"]] == ["materia", "video", "materia", "materia"]


def test_youtube_mais_vistos_e_tempo_sugerido():
    r = pc.buscar_youtube("Unabomber", "en", ytdlp_module=_FakeYtdlp)
    assert r["videos"][0]["views"] == 9_000_000 and r["videos"][1]["short"]
    # top 5 sem o Short: 1800, 2400, 1200, 3000, 600 → média 1800 s (30 min), mediana 1800
    assert r["usados"] == 5 and r["media_s"] == 1800 and r["sugestao_min"] == 30
    assert pc.estatisticas(r["videos"], sem_shorts=False, top=3)["usados"] == 3


def test_url_google_noticias_em_ingles():
    u = pc.url_google("Unabomber", "noticias", "en", "DEST", 2)
    assert "tbm=nws" in u and "hl=en" in u and "lr=lang_en" in u and "start=10" in u and u.endswith("#bes=DEST")


def test_rotas(monkeypatch):
    import app as a
    import dossies as ds
    import navegador_imagens as ni
    c = a.app.test_client()
    r = c.post("/pesquisas/nova", data={"tema": "o Unabomber", "idioma": "en", "categoria": "noticias"})
    assert r.status_code == 302
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        assert c.get(f"/pesquisas/{pid}").status_code == 200 and c.get("/pesquisas").status_code == 200
        abertos = []
        monkeypatch.setattr(ni, "abrir", lambda base, urls, cfg=None, chaves=None, pid="": abertos.append(urls) or {"ok": True, "navegador": "Brave", "confirmadas": [0]})
        d = c.post(f"/pesquisas/{pid}/google", json={"pagina": 1}).get_json()
        assert d["ok"] and "tbm=nws" in abertos[0][0] and "#bes=" in abertos[0][0]
        # o userscript manda como text/plain
        import json
        d = c.post(f"/pesquisas/{pid}/resultados", data=json.dumps({"itens": [{"url": "https://www.bbc.com/a", "titulo": "A"}], "pagina": "1"}),
                   content_type="text/plain").get_json()
        assert d["novos"] == 1
        assert c.post(f"/pesquisas/{pid}/colar", json={"texto": HTML}).get_json()["novos"] == 3
        dados = c.get(f"/pesquisas/{pid}/dados").get_json()
        rid = dados["resultados"][0]["id"]
        c.post(f"/pesquisas/{pid}/item/{rid}", json={"marcado": False})
        d = c.post(f"/pesquisas/{pid}/para-modelo", json={"modelo": "novo", "minutos": 12}).get_json()
        assert d["ok"] and len(d["urls"]) == 3 and "https://www.bbc.com/a" not in d["urls"]
        mod = ds.carregar(a.BASE_DIR, d["modelo"])
        assert mod["tema"] == "o Unabomber" and mod["config"]["minutos"] == 12
        ds.excluir(a.BASE_DIR, d["modelo"])
    finally:
        pc.excluir(a.BASE_DIR, pid)


GOTO_HTML = """<div id="center_col"><div class="MjjYud"><a jsname="UWckNb" href="/goto?url=CAESdwHrOzAVXt5sqUc9fJLP">
<h3 class="LC20lb">Murder of Tristan Brübach</h3><cite>https://en.wikipedia.org<span> › wiki › Murder_of_Tristan_Brü...</span></cite></a></div>
<div class="MjjYud"><a href="/goto?url=CAESfgHrOzAVO6lXFU9nVk"><h3 class="LC20lb">Tracing Darkness - Podcast</h3>
<cite>https://podcasts.apple.com<span> › podcast › tracing-darkness</span></cite></a></div></div>"""


def test_goto_do_google_novo():
    itens = pc.extrair_de_texto(GOTO_HTML)
    assert len(itens) == 2 and all(pc.eh_goto(i["url"]) for i in itens)
    # com o redirecionamento: o link de verdade
    r = pc.resolver_itens([dict(i) for i in itens], transporte=lambda u: (302, "https://www.bbc.com/news/x?utm_source=g", ""))
    assert [x["url"] for x in r] == ["https://www.bbc.com/news/x"] * 2 and not r[0].get("aproximado")
    # página intermediária com <meta refresh>
    r = pc.resolver_itens([dict(itens[0])], transporte=lambda u: (200, "", '<meta http-equiv="refresh" content="0;url=https://apnews.com/a">'))
    assert r[0]["url"] == "https://apnews.com/a"
    # sem rede: plano B pelo endereço mostrado (a Wikipédia completa pelo título)
    r = pc.resolver_itens([dict(i) for i in itens], transporte=lambda u: (_ for _ in ()).throw(OSError("sem rede")))
    assert [x["url"] for x in r] == ["https://en.wikipedia.org/wiki/Murder_of_Tristan_Br%C3%BCbach", "https://podcasts.apple.com/podcast/tracing-darkness"]
    assert all(x["aproximado"] for x in r)
