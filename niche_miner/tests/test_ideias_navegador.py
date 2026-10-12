"""Coleta da aba Ideias virais em Chromium REAL contra Google/YouTube SIMULADOS.

Valida a lógica de leitura (parse de views, filtro de duração, consentimento,
detecção de bloqueio, isolamento de falhas). NÃO valida os seletores do Google
e do YouTube de verdade: eles mudam sem aviso e só podem ser conferidos numa
execução real, na sua máquina.
"""
import http.server
import sys
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_youtube as fake
import ideias_scraper as sc
import yt_scraper as core

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False


# ------------------------------------------------------------------ páginas simuladas
SERP_PT = """<!doctype html><html><body><div id="search"><h3>Resultado 1</h3></div>
<div><div role="heading" aria-level="2">As pessoas também perguntam</div>
  <div><div>Como eliminar mosquitos em casa?</div><div>Resposta longa sem interrogação no fim</div></div>
  <div><div>Qual o melhor repelente natural?</div></div>
  <div><div>Por que os mosquitos picam mais à noite?</div></div></div>
<div><h2>Pesquisas relacionadas</h2>
  <a href="/search?q=repelente+caseiro">repelente caseiro</a>
  <a href="/search?q=mosquito+da+dengue">mosquito da dengue</a>
  <a href="/imagens">link de outra coisa</a></div></body></html>"""

SERP_EN = """<!doctype html><html><body>
<div class="related-question-pair" data-q="How do I get rid of mosquitoes?"><span>How do I get rid of mosquitoes?</span></div>
<div data-q="What kills mosquitoes instantly?">x</div>
<div id="botstuff"><div id="bres"><a href="/search?q=mosquito+trap">mosquito trap</a></div></div></body></html>"""

SERP_VAZIA = "<!doctype html><html><body><div>Nenhuma seção especial aqui</div></body></html>"

CONSENT = """<!doctype html><html><body><h1>Antes de continuar</h1>
<button onclick="location.href=location.pathname+location.search+'&consent=accept'">Aceitar tudo</button>
<button onclick="location.href=location.pathname+location.search+'&consent=reject'">Rejeitar tudo</button></body></html>"""

BLOQUEIO = "<!doctype html><html><body><p>Our systems have detected unusual traffic from your computer network.</p></body></html>"


def card_youtube(vid, titulo, canal, views_txt, quando, dur, verificado=False):
    badge = '<ytd-badge-supported-renderer aria-label="Verificado"></ytd-badge-supported-renderer>' if verificado else ""
    return (f'<ytd-video-renderer><a id="video-title" href="/watch?v={vid}&pp=abc" title="{titulo}">{titulo}</a>'
            f'<ytd-channel-name><a href="/@{canal}">{canal}</a>{badge}</ytd-channel-name>'
            f'<div id="metadata-line"><span>{views_txt}</span><span>{quando}</span></div>'
            f'<ytd-thumbnail-overlay-time-status-renderer><span>{dur}</span></ytd-thumbnail-overlay-time-status-renderer>'
            '</ytd-video-renderer>')


def html_busca(cards):
    return f"<!doctype html><html><body>{''.join(cards)}</body></html>"


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class NavegadorBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._pausa = core.SCROLL_PAUSE
        core.SCROLL_PAUSE = 0.02

    @classmethod
    def tearDownClass(cls):
        core.SCROLL_PAUSE = cls._pausa
        cls._browser.close()
        cls._pw.stop()

    def pagina(self, handler):
        ctx = self._browser.new_context(viewport={"width": 1200, "height": 800})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        page.set_default_timeout(6000)
        page.route("**/*", handler)
        return page


class SerpGoogleTests(NavegadorBase):
    def servir(self, corpo, visitas):
        def handler(route):
            visitas.append(route.request.url)
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=corpo)
        return handler

    def test_le_perguntas_e_relacionadas_em_portugues(self):
        visitas = []
        page = self.pagina(self.servir(SERP_PT, visitas))
        r = sc.coletar_serp_google(page, "como eliminar mosquitos", "DE")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["paa"], ["Como eliminar mosquitos em casa?", "Qual o melhor repelente natural?", "Por que os mosquitos picam mais à noite?"])
        self.assertEqual(r["relacionadas"], ["repelente caseiro", "mosquito da dengue"])
        q = parse_qs(urlparse(visitas[0]).query)
        self.assertEqual((q["q"], q["hl"], q["gl"]), (["como eliminar mosquitos"], ["de"], ["DE"]))

    def test_le_atributos_data_q_e_links_do_rodape(self):
        page = self.pagina(self.servir(SERP_EN, []))
        r = sc.coletar_serp_google(page, "mosquito", "US")
        self.assertEqual(r["status"], "ok")
        self.assertCountEqual(r["paa"], ["How do I get rid of mosquitoes?", "What kills mosquitoes instantly?"])
        self.assertEqual(r["relacionadas"], ["mosquito trap"])

    def test_pagina_sem_secoes_e_ok_e_vazia(self):
        page = self.pagina(self.servir(SERP_VAZIA, []))
        self.assertEqual(sc.coletar_serp_google(page, "x", "BR"), {"status": "ok", "paa": [], "relacionadas": []})

    def test_consentimento_prefere_rejeitar(self):
        visitas = []

        def handler(route):
            visitas.append(route.request.url)
            corpo = SERP_PT if "consent=" in route.request.url else CONSENT
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=corpo)

        r = sc.coletar_serp_google(self.pagina(handler), "mosquito", "BR")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["paa"]), 3)
        self.assertIn("consent=reject", visitas[-1])
        self.assertNotIn("consent=accept", "".join(visitas))

    def test_redirecionamento_para_sorry_vira_bloqueado(self):
        def handler(route):
            if "/sorry/" in route.request.url:
                return route.fulfill(status=200, content_type="text/html", body=BLOQUEIO)
            route.fulfill(status=302, headers={"Location": "https://www.google.com/sorry/index?continue=x"}, body="")

        r = sc.coletar_serp_google(self.pagina(handler), "mosquito", "BR")
        self.assertEqual((r["status"], r["paa"]), ("bloqueado", []))

    def test_texto_de_captcha_vira_bloqueado(self):
        r = sc.coletar_serp_google(self.pagina(self.servir(BLOQUEIO, [])), "mosquito", "BR")
        self.assertEqual(r["status"], "bloqueado")

    def test_falha_de_rede_vira_erro_sem_levantar(self):
        r = sc.coletar_serp_google(self.pagina(lambda route: route.abort()), "mosquito", "BR")
        self.assertEqual(r["status"], "erro")
        self.assertIn("erro", r)


class RadarNavegadorTests(NavegadorBase):
    def setUp(self):
        antigo = core.apply_filters
        core.apply_filters = lambda page, filtros=None: core._normalizar_filtros(filtros)  # a UI de filtros do site real não existe aqui
        self.addCleanup(lambda: setattr(core, "apply_filters", antigo))

    def test_coleta_calcula_views_dia_filtra_duracao_e_usa_gl(self):
        visitas = []
        cards = [
            card_youtube("aaaaaaaaaaa", "Vídeo grande", "pequeno", "1,2 mi de visualizações", "há 3 semanas", "12:34"),
            card_youtube("bbbbbbbbbbb", "Um short", "curto", "5 mi de visualizações", "há 2 dias", "0:45"),
            card_youtube("aaaaaaaaaaa", "Repetido", "pequeno", "1,2 mi de visualizações", "há 3 semanas", "12:34"),
            card_youtube("ccccccccccc", "Do verificado", "gigante", "800 mil visualizações", "há 5 horas", "8:00", verificado=True),
        ]

        def handler(route):
            visitas.append(route.request.url)
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html_busca(cards))

        page = self.pagina(handler)
        vids = sc.coletar_videos_termo(page, "como eliminar mosquitos", "DE", {"duracao_min": 3, "duracao_max": 0, "data_periodo": "mes"}, 20, log=lambda *_: None)
        self.assertEqual([v["video_id"] for v in vids], ["aaaaaaaaaaa", "ccccccccccc"])   # short e repetido ficaram de fora
        a, c = vids
        self.assertEqual((a["views_num"], a["termo_busca"], a["canal"], a["canal_verificado"]), (1200000, "como eliminar mosquitos", "pequeno", False))
        self.assertEqual(a["idade_dias"], 24)                       # "há 3 semanas" = 3 x 7 + 3 (ponto médio da faixa)
        self.assertEqual(a["views_dia"], 50000.0)
        self.assertTrue(c["canal_verificado"])
        self.assertEqual(c["idade_dias"], 1)                        # "há 5 horas" nunca vira 0 dias
        self.assertEqual(c["views_dia"], 800000.0)
        q = parse_qs(urlparse(visitas[0]).query)
        self.assertEqual((q["search_query"], q["gl"]), (["como eliminar mosquitos"], ["DE"]))

    def test_ler_inscritos_pula_verificados_respeita_top_k_e_cache(self):
        subs = {"pequeno": "12 mil inscritos", "medio": "340 mil inscritos", "outro": "8 mil inscritos"}
        visitas = []

        def handler(route):
            u = urlparse(route.request.url)
            visitas.append(u.path)
            handle = u.path.strip("/").lstrip("@")
            if handle == "quebrado":
                return route.abort()
            canal = fake.CanalFake(handle, [1, 2, 3], inscritos_txt=subs[handle]) if handle in subs else None
            if canal is None:
                return route.fulfill(status=404, body="")
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=canal.html_canal())

        def v(vid, canal, views, verificado=False):
            return {"video_id": vid, "canal": canal, "canal_url": f"https://www.youtube.com/@{canal}", "views_num": views, "canal_verificado": verificado}

        videos = [v("1", "pequeno", 500), v("2", "gigante", 9_000_000, verificado=True), v("3", "medio", 900),
                  v("4", "outro", 100), v("5", "quebrado", 50_000)]
        cache = {"https://www.youtube.com/@outro": {"inscritos_num": 1, "inscritos_text": "", "n_videos_canal": None}}
        page = self.pagina(handler)
        sc.coletar_inscritos(page, videos, top_k=3, cache=cache, log=lambda *_: None)
        # top 3 não verificados por views: quebrado (50 mil), medio (900), pequeno (500); "outro" e "gigante" ficam fora
        self.assertEqual(cache["https://www.youtube.com/@pequeno"]["inscritos_num"], 12000)
        self.assertEqual(cache["https://www.youtube.com/@medio"]["inscritos_num"], 340000)
        self.assertIsNone(cache["https://www.youtube.com/@quebrado"]["inscritos_num"])       # falha isolada, sem exceção
        self.assertNotIn("/@gigante", visitas)                                                  # verificado: nem visita
        self.assertEqual(cache["https://www.youtube.com/@outro"]["inscritos_num"], 1)          # cache preservado

        sc.aplicar_razoes(videos, cache)
        self.assertEqual(videos[0]["razao_views_inscritos"], 0.04)
        self.assertNotIn("razao_views_inscritos", videos[1])
        self.assertEqual(videos[2]["inscritos_num"], 340000)
        self.assertNotIn("razao_views_inscritos", videos[4])


# ------------------------------------------------------------------ autocomplete (sem navegador)
class SugestoesTests(unittest.TestCase):
    def test_url_por_mercado_e_fonte(self):
        g = sc.url_sugestoes("truque caseiro", "DE")
        y = sc.url_sugestoes("truque caseiro", "DE", youtube=True)
        self.assertIn("hl=de", g)
        self.assertIn("gl=DE", g)
        self.assertIn("q=truque%20caseiro", g)
        self.assertNotIn("ds=yt", g)
        self.assertIn("ds=yt", y)

    def test_coleta_google_e_youtube(self):
        def fetch(url):
            return '["q", ["a1", "a2"]]' if "ds=yt" not in url else 'window.google.ac.h(["q", [["y1", 0]]])'
        self.assertEqual(sc.coletar_sugestoes(fetch, "t", "BR"), {"google": ["a1", "a2"], "youtube": ["y1"]})

    def test_alfabeto_faz_27_consultas_por_fonte_sem_duplicar(self):
        consultas = []

        def fetch(url):
            consultas.append(url)
            return '["q", ["mesma", "outra"]]'
        r = sc.coletar_sugestoes(fetch, "t", "BR", alfabeto=True, pausa=0)
        self.assertEqual(len(consultas), 54)
        self.assertEqual(r["google"], ["mesma", "outra"])

    def test_fonte_que_nunca_respondeu_e_none_e_nao_zero(self):
        def fetch(url):
            if "ds=yt" in url:
                raise RuntimeError("HTTP 429")
            return '["q", []]'
        r = sc.coletar_sugestoes(fetch, "t", "BR")
        self.assertEqual(r["google"], [])       # respondeu, mas sem sugestões: zero de verdade
        self.assertIsNone(r["youtube"])         # nunca respondeu: não coletado

    def test_falha_parcial_no_alfabeto_mantem_o_que_veio(self):
        n = {"i": 0}

        def fetch(url):
            n["i"] += 1
            if n["i"] % 2 == 0:
                raise RuntimeError("falha")
            return '["q", ["ok"]]'
        self.assertEqual(sc.coletar_sugestoes(fetch, "t", "BR", alfabeto=True, pausa=0)["google"], ["ok"])


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class FetchPorContextoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if "erro" in self.path:
                    self.send_response(429)
                    self.end_headers()
                    return
                corpo = '["q", ["sugestão ç"]]'.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, *a):
                pass

        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_baixa_texto_utf8_e_falha_em_http_de_erro(self):
        ctx = self._browser.new_context()
        self.addCleanup(ctx.close)
        fetch = sc.fetch_por_contexto(ctx)
        base = f"http://127.0.0.1:{self.srv.server_port}"
        self.assertEqual(sc.ideias.parse_sugestoes(fetch(f"{base}/ok")), ["sugestão ç"])
        with self.assertRaises(RuntimeError):
            fetch(f"{base}/erro")


if __name__ == "__main__":
    unittest.main(verbosity=2)
