"""Aba API do YouTube no navegador real: servidor Flask local, Chromium do Playwright e a API do YouTube falsa no lugar da rede."""
import csv
import io
import json
import logging
import os
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as webapp
import fake_yt_api as F
import yt_api as Y
import yt_rotas

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False

V = F.vid_id
NAV = '.topnav-btn[data-view="yt"]'
BASE = "http://127.0.0.1"


def ia_json(**campos):
    return json.dumps(campos, ensure_ascii=False)


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        cls.srv = make_server("127.0.0.1", 0, webapp.app, threaded=True)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/"
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.f = F.mundo()
        for p in (mock.patch.object(Y, "_urlopen", self.f), mock.patch.object(yt_rotas, "_agora", lambda: F.AGORA),
                  mock.patch.dict(os.environ, {"NICHE_MINER_DB": os.path.join(self._tmp.name, "b.db")})):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("YOUTUBE_API_KEY", None)

    def tearDown(self):
        self.assertEqual(getattr(self, "erros", []), [])

    # ------------------------------------------------------------------ apoio
    def abrir(self, chave=F.CHAVE, largura=1500):
        ctx = self._browser.new_context(viewport={"width": largura, "height": 1000}, accept_downloads=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.url.rstrip("/"))
        ctx.route(re.compile(r"^(?!http://127\.0\.0\.1).*"), lambda r: r.abort())          # imagens externas do YouTube: sem rede aqui
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        self.erros, self.requisicoes = [], []
        page.on("pageerror", lambda e: self.erros.append(str(e)))
        page.on("request", lambda r: self.requisicoes.append((r.method, r.url, r.post_data)))
        page.goto(self.url)
        self.ir_yt(page)
        if chave:
            page.fill("#yt-chave", chave)
        return page

    def ir_yt(self, page):
        page.click(NAV)
        page.wait_for_selector("#view-yt", state="visible")

    def sub(self, page, nome):
        page.click(f'.yt-sub-btn[data-sub="{nome}"]')
        page.wait_for_selector(f"#yt-painel-{nome}", state="visible")

    def clicar_e_esperar(self, page, botao):
        page.click(botao)
        page.wait_for_function("(b) => !document.querySelector(b).disabled", arg=botao)

    def gerar_prompt(self, page, card):
        antes = page.input_value(f"{card} .yt-prompt-out")
        page.click(f"{card} .yt-gerar")
        page.wait_for_function(
            "(a) => { const el = document.querySelector(a[0] + ' .yt-prompt-out'); return el && el.value && el.value !== a[1]; }", arg=[card, antes])
        return page.input_value(f"{card} .yt-prompt-out")

    def aplicar_ia(self, page, card, texto):
        page.fill(f"{card} .yt-colar", texto)
        page.click(f"{card} .yt-aplicar")
        page.wait_for_function("(c) => document.querySelector(c + ' .yt-msg').textContent.trim() !== ''", arg=card)

    def titulos(self, page, tabela):
        return page.eval_on_selector_all(f"{tabela} tbody .yt-video a", "els => els.map(e => e.textContent)")

    def texto(self, page, seletor):
        return page.inner_text(seletor)

    def buscar(self, page, q="estoicismo", **campos):
        page.fill("#yp-q", q)
        for id_, valor in campos.items():
            page.select_option(f"#yp-{id_}", valor)
        self.clicar_e_esperar(page, "#yp-buscar")

    def cota(self, page):
        return page.inner_text("#yt-cota-usada")

    def chamadas_yt(self):
        return [(m, u.split("/api/yt/")[1], json.loads(b) if b else None) for m, u, b in self.requisicoes if "/api/yt/" in u and m == "POST"]


# ====================================================================== chave, cota e navegação
class ChaveECotaTests(Base):
    def test_chave_guardada_restaurada_mostrada_e_esquecida(self):
        page = self.abrir()
        self.assertEqual(page.evaluate("localStorage.getItem('niche_miner_yt_chave')"), F.CHAVE)
        self.assertEqual(page.get_attribute("#yt-chave", "type"), "password")
        page.click("#yt-chave-ver")
        self.assertEqual((page.get_attribute("#yt-chave", "type"), self.texto(page, "#yt-chave-ver")), ("text", "Ocultar"))
        page.reload()
        self.ir_yt(page)
        self.assertEqual(page.input_value("#yt-chave"), F.CHAVE)
        page.click("#yt-chave-esquecer")
        self.assertEqual((page.input_value("#yt-chave"), page.evaluate("localStorage.getItem('niche_miner_yt_chave')")), ("", None))

    def test_sem_chave_avisa_e_nao_chama_a_api(self):
        page = self.abrir(chave=None)
        page.fill("#yp-q", "x")
        page.click("#yp-buscar")
        self.assertIn("Cole a chave da API", self.texto(page, "#yp-msg"))
        self.assertEqual(self.f.chamadas, [])
        self.assertEqual(self.chamadas_yt(), [])

    def test_chave_da_variavel_de_ambiente_vale_sem_digitar(self):
        os.environ["YOUTUBE_API_KEY"] = F.CHAVE
        page = self.abrir(chave=None)
        page.wait_for_function("document.querySelector('#yt-ambiente').textContent === 'sim'")
        self.assertIn("variável de ambiente", self.texto(page, "#yt-chave-msg"))
        self.buscar(page)
        self.assertEqual(self.titulos(page, "#yp-tabela")[0], "Sêneca em 45 segundos")
        self.assertEqual(self.chamadas_yt()[-1][2]["chave"], "")                                # o navegador não mandou chave nenhuma

    def test_chave_errada_e_cota_esgotada_dao_mensagem_amigavel_e_liberam_o_botao(self):
        page = self.abrir(chave="AIzaChaveErradaQualquer1234567890xyz")
        self.buscar(page)
        msg = self.texto(page, "#yp-msg")
        self.assertIn("Chave da API inválida", msg)
        self.assertNotIn("AIzaChaveErrada", msg)
        self.assertEqual((page.is_enabled("#yp-buscar"), self.texto(page, "#yp-buscar"), self.cota(page)), (True, "Buscar", "0"))
        page.fill("#yt-chave", F.CHAVE)
        self.f.cota = 0
        self.clicar_e_esperar(page, "#yp-buscar")
        self.assertIn("cota diária", self.texto(page, "#yp-msg"))
        self.assertEqual(self.cota(page), "0")                                                   # erro não soma cota

    def test_contador_de_cota_soma_persiste_zera_e_muda_de_dia(self):
        page = self.abrir()
        self.buscar(page)
        self.assertEqual(self.cota(page), "102")
        self.sub(page, "alta")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.assertEqual(self.cota(page), "104")
        page.reload()
        self.ir_yt(page)
        self.assertEqual(self.cota(page), "104")
        page.click("#yt-cota-zerar")
        self.assertEqual(self.cota(page), "0")
        page.evaluate("localStorage.setItem('niche_miner_yt_cota', JSON.stringify({dia: '2020-01-01', usadas: 9999}))")
        page.reload()
        self.ir_yt(page)
        self.assertEqual(self.cota(page), "0")

    def test_limite_de_short_muda_a_classificacao_e_fica_guardado(self):
        page = self.abrir()
        self.buscar(page)
        linha = page.locator("#yp-tabela tbody tr", has_text="Filosofia rápida")
        self.assertNotIn("Short", linha.inner_text())                                            # 2:30 não é Short com 60 s
        page.select_option("#yt-short", "180")
        self.assertIn("Short", linha.inner_text())
        self.assertEqual(page.evaluate("localStorage.getItem('niche_miner_yt_short')"), "180")
        page.reload()
        self.ir_yt(page)
        self.assertEqual(page.input_value("#yt-short"), "180")

    def test_navegacao_entre_abas_e_sub_abas(self):
        page = self.abrir()
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.rail')).display"), "none")
        for nome in ("pesquisa", "alta", "comparar", "canal", "video", "historico"):
            self.sub(page, nome)
            visiveis = page.eval_on_selector_all(".yt-painel", "els => els.filter(e => !e.hidden).map(e => e.id)")
            self.assertEqual(visiveis, [f"yt-painel-{nome}"])
        page.click('.topnav-btn[data-view="minerar"]')
        page.wait_for_selector("#view-yt", state="hidden")
        self.assertNotEqual(page.evaluate("getComputedStyle(document.querySelector('.rail')).display"), "none")


# ====================================================================== 1. pesquisa avançada
class PesquisaTests(Base):
    def test_busca_com_palavra_chave_assume_7_dias_e_ordena_por_engajamento(self):
        page = self.abrir()
        self.buscar(page, "estoicismo", pais="BR", idioma="pt")
        self.assertEqual(self.titulos(page, "#yp-tabela"), ["Sêneca em 45 segundos", "12 lições estoicas para ouvir toda manhã", "Como ter um dia mais produtivo", "Filosofia rápida", "Trailer curto de Roma"])
        p = self.f.por_recurso("search")[0]
        self.assertEqual((p["q"], p["regionCode"], p["relevanceLanguage"], p["publishedAfter"], p["order"], p["maxResults"]), ("estoicismo", "BR", "pt", "2026-09-14T00:00:00Z", "viewCount", "25"))
        self.assertEqual(page.input_value("#yp-de"), "2026-09-14")
        self.assertIn("últimos 7 dias", self.texto(page, "#yp-msg"))
        self.assertIn("Gastou 102 unidades", self.texto(page, "#yp-msg"))
        self.assertEqual(self.texto(page, "#yp-contagem"), "5 de 5 vídeos")
        self.assertEqual((self.f.unidades_gastas(), self.cota(page)), (102, "102"))

    def test_custo_aparece_antes_de_clicar_e_muda_com_a_palavra_chave(self):
        page = self.abrir()
        self.assertIn("2 unidades", self.texto(page, "#yp-custo"))
        page.fill("#yp-q", "estoicismo")
        self.assertIn("102 unidades", self.texto(page, "#yp-custo"))
        page.fill("#yp-q", "  ")
        self.assertIn("2 unidades", self.texto(page, "#yp-custo"))

    def test_atalhos_de_data_preenchem_o_periodo_e_vao_para_a_api(self):
        page = self.abrir()
        page.click("#yp-atalhos >> text=1 mês")
        esperado = page.evaluate("NicheYT.dataAtalho(30, new Date())")
        self.assertEqual((page.input_value("#yp-de"), page.input_value("#yp-ate")), (esperado, ""))
        self.buscar(page)
        self.assertEqual(self.f.por_recurso("search")[0]["publishedAfter"], f"{esperado}T00:00:00Z")
        self.assertNotIn("últimos 7 dias", self.texto(page, "#yp-msg"))                            # o usuário escolheu o período
        page.fill("#yp-de", "2026-08-01")
        page.fill("#yp-ate", "2026-08-31")
        self.clicar_e_esperar(page, "#yp-buscar")
        p = self.f.por_recurso("search")[1]
        self.assertEqual((p["publishedAfter"], p["publishedBefore"]), ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"))

    def test_sem_palavra_chave_cai_no_em_alta_filtrado(self):
        page = self.abrir()
        self.clicar_e_esperar(page, "#yp-buscar")
        self.assertEqual(self.titulos(page, "#yp-tabela"), ["Documentário sobre Roma"])
        self.assertIn("vídeos em alta de US", self.texto(page, "#yp-msg"))
        self.assertIn("Gastou 2 unidades", self.texto(page, "#yp-msg"))
        self.assertEqual(self.f.por_recurso("search"), [])
        page.select_option("#yp-pais", "BR")
        self.clicar_e_esperar(page, "#yp-buscar")
        self.assertEqual(sorted(self.titulos(page, "#yp-tabela")), sorted(["Trailer curto de Roma", "Documentário sobre Roma", "Filosofia rápida", "12 lições estoicas para ouvir toda manhã"]))

    def test_filtros_extras_rodam_no_navegador_sem_gastar_cota(self):
        page = self.abrir()
        self.buscar(page)
        gastas = len(self.f.chamadas)

        def com(**filtros):
            for id_ in ("views", "smin", "smax", "cvmin", "cvmax", "dmin", "dmax"):
                page.fill(f"#yp-f-{id_}", "")
            page.select_option("#yp-f-formato", "todos")
            for id_, valor in filtros.items():
                (page.select_option if id_ == "formato" else page.fill)(f"#yp-f-{id_}", valor)
            return self.titulos(page, "#yp-tabela")

        self.assertEqual(com(views="100000"), ["Filosofia rápida", "Trailer curto de Roma"])
        self.assertEqual(self.texto(page, "#yp-contagem"), "2 de 5 vídeos")
        self.assertEqual(com(smin="100000"), ["Trailer curto de Roma"])                              # canal Beta; o Gama esconde inscritos
        self.assertEqual(com(smax="10000"), ["Sêneca em 45 segundos", "12 lições estoicas para ouvir toda manhã", "Como ter um dia mais produtivo"])
        self.assertEqual(com(cvmin="1000000"), ["Trailer curto de Roma"])
        self.assertEqual(com(dmin="9", dmax="10"), ["12 lições estoicas para ouvir toda manhã", "Como ter um dia mais produtivo"])   # 10:00 e 9:00
        self.assertEqual(com(formato="shorts"), ["Sêneca em 45 segundos", "Trailer curto de Roma"])
        self.assertEqual(com(formato="longos", views="100000"), ["Filosofia rápida"])
        self.assertEqual(com(views="99999999"), [])
        self.assertIn("Nenhum vídeo passa nos filtros", self.texto(page, "#yp-tabela"))
        self.assertEqual(len(self.f.chamadas), gastas)                                           # nada disso foi à API

    def test_ordenacao(self):
        page = self.abrir()
        self.buscar(page)

        def ordem(chave, direcao="desc"):
            page.select_option("#yp-ordem", chave)
            page.select_option("#yp-dir", direcao)
            return self.titulos(page, "#yp-tabela")

        self.assertEqual(ordem("views")[0], "Trailer curto de Roma")
        self.assertEqual(ordem("views", "asc")[0], "Como ter um dia mais produtivo")
        self.assertEqual(ordem("data"), ["Como ter um dia mais produtivo", "Trailer curto de Roma", "Filosofia rápida", "12 lições estoicas para ouvir toda manhã", "Sêneca em 45 segundos"])
        self.assertEqual(ordem("inscritos"), ["Trailer curto de Roma", "12 lições estoicas para ouvir toda manhã", "Sêneca em 45 segundos", "Como ter um dia mais produtivo", "Filosofia rápida"])
        self.assertEqual(ordem("duracao")[0], "12 lições estoicas para ouvir toda manhã")   # 10 min: a mais longa deste conjunto de busca
        self.assertEqual(ordem("likes")[:2], ["Trailer curto de Roma", "Filosofia rápida"])

    def test_csv_respeita_filtros_ordem_e_neutraliza_formulas(self):
        self.f.add_video(F.video_item(V(13), '=HYPERLINK("http://evil.example","x")', F.uc("a"), "@evil", 2, 500000, 5, 1, "PT5M"))
        self.f.busca_ids.append(V(13))
        page = self.abrir()
        self.buscar(page)
        page.fill("#yp-f-views", "100000")
        with page.expect_download() as d:
            page.click("#yp-csv")
        arq = d.value
        self.assertRegex(arq.suggested_filename, r"^pesquisa_youtube_\d{4}-\d{2}-\d{2}\.csv$")
        bruto = Path(arq.path()).read_bytes().decode("utf-8")
        self.assertTrue(bruto.startswith("\ufeff"))
        linhas = list(csv.reader(io.StringIO(bruto.lstrip("\ufeff"))))
        self.assertEqual(linhas[0], page.evaluate("NicheYT.COLUNAS_CSV.map(c => c.rotulo)"))
        corpo = {l[0]: l for l in linhas[1:]}
        self.assertEqual(len(linhas) - 1, 3)                                                     # Filosofia, Trailer e o de título hostil
        self.assertIn("'=HYPERLINK(\"http://evil.example\",\"x\")", corpo)                       # fórmula neutralizada
        self.assertEqual(corpo["'=HYPERLINK(\"http://evil.example\",\"x\")"][2], "'@evil")
        rot = linhas[0]
        trailer = dict(zip(rot, corpo["Trailer curto de Roma"]))
        self.assertEqual((trailer["Formato"], trailer["Inscritos do canal"], trailer["Engajamento (%)"], trailer["Duração"]), ("Short", "120000", "5.42", "0:58"))
        filosofia = dict(zip(rot, corpo["Filosofia rápida"]))
        self.assertEqual((filosofia["Formato"], filosofia["Inscritos do canal"]), ("Longo", ""))    # inscritos ocultos ficam em branco, não 0

    def test_pdf_monta_copia_para_impressao_e_limpa_depois(self):
        page = self.abrir()
        self.buscar(page, "estoicismo")
        page.fill("#yp-f-views", "100000")
        page.evaluate("""() => { window.__print = null; window.print = () => { window.__print = {
            classe: document.body.classList.contains('yt-imprimindo'), linhas: document.querySelectorAll('#yt-print tbody tr').length,
            titulo: document.querySelector('#yt-print h1').textContent, imagens: document.querySelectorAll('#yt-print img').length }; }; }""")
        page.click("#yp-pdf")
        registro = page.evaluate("window.__print")
        self.assertEqual((registro["classe"], registro["linhas"], registro["imagens"]), (True, 2, 0))
        self.assertIn("estoicismo", registro["titulo"])
        page.emulate_media(media="print")                                                       # como o navegador vê na hora de imprimir
        visiveis = page.evaluate("[...document.body.children].filter(e => e.id !== 'yt-print' && getComputedStyle(e).display !== 'none').map(e => e.tagName)")
        self.assertEqual(visiveis, [])
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('#yt-print')).display"), "block")
        page.emulate_media(media="screen")
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('#yt-print')).display"), "none")    # na tela nunca aparece
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        self.assertEqual(page.evaluate("[document.body.classList.contains('yt-imprimindo'), document.querySelectorAll('#yt-print').length]"), [False, 0])


# ====================================================================== 2. em alta
class EmAltaTests(Base):
    def test_carrega_filtra_100_mil_views_e_a_duracao_e_reordena(self):
        page = self.abrir()
        self.sub(page, "alta")
        self.clicar_e_esperar(page, "#ya-carregar")
        p = self.f.por_recurso("videos")[0]
        self.assertEqual((p["chart"], p["regionCode"], p["maxResults"]), ("mostPopular", "BR", "50"))
        self.assertEqual(self.titulos(page, "#ya-tabela"), ["Trailer curto de Roma", "Documentário sobre Roma", "Filosofia rápida"])       # 30 mil e 9 mil ficam de fora
        self.assertEqual(self.texto(page, "#ya-contagem"), "3 de 5 vídeos em alta (só com 100 mil views ou mais)")
        self.assertIn("Gastou 2 unidades", self.texto(page, "#ya-msg"))
        for dur, esperado in {"shorts": ["Trailer curto de Roma"], "menos5": ["Trailer curto de Roma", "Filosofia rápida"], "mais8": ["Documentário sobre Roma"], "mais30": ["Documentário sobre Roma"]}.items():
            page.select_option("#ya-dur", dur)
            self.assertEqual(self.titulos(page, "#ya-tabela"), esperado, dur)
        page.select_option("#ya-dur", "todos")
        page.select_option("#ya-ordem", "engajamento")
        self.assertEqual(self.titulos(page, "#ya-tabela"), ["Documentário sobre Roma", "Filosofia rápida", "Trailer curto de Roma"])
        page.select_option("#ya-ordem", "data")
        page.select_option("#ya-dir", "asc")
        self.assertEqual(self.titulos(page, "#ya-tabela"), ["Filosofia rápida", "Trailer curto de Roma", "Documentário sobre Roma"])
        self.assertEqual(len(self.f.por_recurso("videos")), 1)                                    # ordenar e filtrar não chamam a API de novo
        self.assertEqual(len(self.f.chamadas), 2)

    def test_atalhos_de_pais_categoria_e_lista_vazia(self):
        page = self.abrir()
        self.sub(page, "alta")
        page.click("#ya-atalhos >> text=EN-US")
        self.assertEqual(page.input_value("#ya-pais"), "US")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.assertEqual(self.titulos(page, "#ya-tabela"), ["Documentário sobre Roma", "Roma em 8 minutos"])
        page.click("#ya-atalhos >> text=ES")
        self.assertEqual(page.input_value("#ya-pais"), "ES")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.assertIn("não devolveu vídeos", self.texto(page, "#ya-msg"))
        self.assertIn("Nenhum vídeo passa nos filtros", self.texto(page, "#ya-tabela"))
        page.click("#ya-atalhos >> text=PT-BR")
        page.select_option("#ya-cat", "27")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.assertEqual(self.f.por_recurso("videos")[-1]["videoCategoryId"], "27")
        self.assertEqual(self.titulos(page, "#ya-tabela"), ["Filosofia rápida"])

    def test_pais_sem_lista_em_alta_da_erro_amigavel(self):
        page = self.abrir()
        self.sub(page, "alta")
        self.f.erro_forcado = ("videos", 400, "chart not supported", "videoChartNotFound")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.assertIn("lista de vídeos em alta", self.texto(page, "#ya-msg"))
        self.assertFalse(page.is_visible("#ya-resultado"))


# ====================================================================== IA (mesmo padrão nas cinco)
class IaTests(Base):
    def em_alta(self, page):
        self.sub(page, "alta")
        self.clicar_e_esperar(page, "#ya-carregar")

    def test_oportunidades_prompt_copiar_aplicar_evidencias_e_apagar(self):
        page = self.abrir()
        self.em_alta(page)
        card = "#yt-ia-alta"
        page.fill(f"{card} .yt-ctx", "quero um canal dark de história")
        prompt = self.gerar_prompt(page, card)
        self.assertIn("Vídeos em alta em BR", prompt)
        self.assertIn('1. "Trailer curto de Roma"', prompt)
        self.assertIn('3. "Filosofia rápida"', prompt)
        self.assertNotIn("Sêneca", prompt)                                                       # só a lista filtrada que está na tela
        self.assertIn("quero um canal dark de história", prompt)
        self.assertTrue(page.is_enabled(f"{card} .yt-copiar"))
        page.click(f"{card} .yt-copiar")
        self.assertEqual(page.evaluate("navigator.clipboard.readText()"), prompt)
        # a ordem da tabela muda depois do prompt: a evidência continua apontando para a lista do prompt
        page.select_option("#ya-ordem", "engajamento")
        self.aplicar_ia(page, card, ia_json(leitura_geral="Roma domina", nichos_em_alta=[{"nicho": "História de Roma", "por_que": "2 vídeos", "evidencia": [1, 2, 9], "dificuldade": "media"}],
                                            oportunidades_dark=[{"ideia": "Roma animada", "formato": "animação", "como_produzir": "IA e narração", "titulo": "Roma em 8 minutos", "evidencia": [1]}],
                                            canais_pequenos_em_destaque=[{"indice": 3, "por_que": "150 mil views sem aparecer"}], ressalvas=["amostra pequena"]))
        self.assertEqual(self.texto(page, f"{card} .yt-msg"), "Aplicado.")
        saida = self.texto(page, f"{card} .yt-out")
        for trecho in ("Leitura geral", "Roma domina", "História de Roma", "Roma animada", "150 mil views sem aparecer", "amostra pequena", "trate como hipótese"):
            self.assertIn(trecho, saida)
        ev = page.eval_on_selector_all(f"{card} .yt-out .yt-ev:first-of-type a, {card} .yt-out .yt-ev a", "els => els.map(a => [a.textContent, a.href])")
        self.assertEqual(ev[:2], [["1", f"https://www.youtube.com/watch?v={V(8)}"], ["2", f"https://www.youtube.com/watch?v={V(7)}"]])   # 1 = Trailer, 2 = Documentário; o 9 caiu
        self.assertNotIn("9", [e[0] for e in ev])
        self.assertEqual(page.get_attribute(f"{card} .yt-out a:has-text('Canal Gama')", "href"), "https://www.youtube.com/@gama")
        self.assertEqual(page.get_attribute(f"{card} .yt-out a:has-text('ver vídeo')", "href"), f"https://www.youtube.com/watch?v={V(12)}")
        page.click(f"{card} .yt-apagar")
        self.assertEqual(self.texto(page, f"{card} .yt-out").strip(), "")
        # a rota de IA nunca recebe a chave
        for _, rota, corpo in self.chamadas_yt():
            if rota.startswith(("prompt/", "ia/")):
                self.assertNotIn("chave", corpo, rota)

    def test_resposta_ruim_mostra_erro_e_nao_apaga_nada_do_que_ja_existe(self):
        page = self.abrir()
        self.em_alta(page)
        card = "#yt-ia-alta"
        self.aplicar_ia(page, card, "isto não é json")
        self.assertTrue(self.texto(page, f"{card} .yt-msg"))
        self.assertTrue(page.eval_on_selector(f"{card} .yt-msg", "e => e.classList.contains('cn-erro')"))
        self.assertEqual(self.texto(page, f"{card} .yt-out").strip(), "")
        self.assertEqual(page.input_value(f"{card} .yt-colar"), "isto não é json")               # o texto colado fica para corrigir

    def test_dados_novos_limpam_prompt_e_resultado_velhos_mas_mantem_o_contexto(self):
        page = self.abrir()
        self.em_alta(page)
        card = "#yt-ia-alta"
        page.fill(f"{card} .yt-ctx", "meu contexto")
        self.gerar_prompt(page, card)
        self.aplicar_ia(page, card, ia_json(leitura_geral="velha"))
        self.assertIn("velha", self.texto(page, f"{card} .yt-out"))
        self.clicar_e_esperar(page, "#ya-carregar")
        self.assertEqual(self.texto(page, f"{card} .yt-out").strip(), "")
        self.assertFalse(page.is_visible(f"{card} .yt-prompt-out"))
        self.assertTrue(page.is_disabled(f"{card} .yt-copiar"))
        self.assertEqual(page.input_value(f"{card} .yt-ctx"), "meu contexto")

    def test_sem_dados_o_prompt_pede_para_carregar_primeiro(self):
        page = self.abrir()
        self.em_alta(page)
        page.select_option("#ya-dur", "shorts")
        page.select_option("#ya-ordem", "views")
        page.fill("#yt-ia-alta .yt-ctx", "x")
        self.f.em_alta["BR"] = []
        self.clicar_e_esperar(page, "#ya-carregar")
        page.click("#yt-ia-alta .yt-gerar")
        self.assertIn("Carregue os dados", self.texto(page, "#yt-ia-alta .yt-msg-prompt"))

    def test_comparativo(self):
        page = self.abrir()
        self.sub(page, "comparar")
        page.fill("#yc-a", "@alfa")
        page.fill("#yc-b", "@beta")
        self.clicar_e_esperar(page, "#yc-comparar")
        card = "#yt-ia-comparar"
        page.fill(f"{card} .yt-ctx", "vou competir com o B")
        prompt = self.gerar_prompt(page, card)
        for trecho in ("CANAL A", "Canal Alfa", "CANAL B", "Canal Beta", "- Inscritos: A = 8.500, B = 120.000", "vou competir com o B"):
            self.assertIn(trecho, prompt)
        self.aplicar_ia(page, card, ia_json(resumo="B é maior", forcas_a=["engajamento"], forcas_b=["alcance"], veredito="Copiar a frequência do A",
                                            diferencas_de_estrategia=[{"tema": "Duração", "a": "10 min", "b": "35 min"}]))
        saida = self.texto(page, f"{card} .yt-out")
        for trecho in ("B é maior", "Onde o canal A vai melhor", "engajamento", "Duração", "35 min", "Copiar a frequência do A"):
            self.assertIn(trecho, saida)

    def test_dossie_do_canal(self):
        page = self.abrir()
        self.sub(page, "canal")
        page.fill("#yk-canal", "@alfa")
        self.clicar_e_esperar(page, "#yk-analisar")
        card = "#yt-ia-canal"
        page.fill(f"{card} .yt-ctx", "penso em copiar o formato")
        prompt = self.gerar_prompt(page, card)
        for trecho in ('Canal: "Canal Alfa"', "Palavras-chave do canal: estoicismo, vida diária, calma", "penso em copiar o formato", "você NÃO viu os vídeos"):
            self.assertIn(trecho, prompt)
        self.aplicar_ia(page, card, ia_json(resumo="Canal de filosofia", pontos_fortes=["nicho claro"], oportunidades=[{"oportunidade": "Séries", "como": "agrupar por tema"}]))
        saida = self.texto(page, f"{card} .yt-out")
        for trecho in ("Canal de filosofia", "Pontos fortes", "nicho claro", "Séries", "agrupar por tema"):
            self.assertIn(trecho, saida)

    def test_engenharia_reversa_com_e_sem_transcricao(self):
        page = self.abrir()
        self.sub(page, "video")
        page.fill("#yv-video", f"https://youtu.be/{V(2)}")
        self.clicar_e_esperar(page, "#yv-analisar")
        card = "#yt-ia-video"
        sem = self.gerar_prompt(page, card)
        self.assertIn("SEM TRANSCRIÇÃO", sem)
        self.assertIn("marque como hipótese", sem)
        page.fill("#yv-transcricao", "Olá, hoje vou falar de estoicismo em 12 lições.")
        com = self.gerar_prompt(page, card)
        self.assertIn("Transcrição do vídeo:\nOlá, hoje vou falar de estoicismo", com)
        self.assertNotIn("SEM TRANSCRIÇÃO", com)
        self.assertIn('Título: "12 lições estoicas para ouvir toda manhã"', com)
        self.aplicar_ia(page, card, ia_json(resumo="Lista numerada", gancho={"tecnica": "Promessa numérica", "como_funciona": "avisa quantas lições"},
                                            estrutura=[{"trecho": "0:00 abertura", "funcao": "gancho", "tecnica": "pergunta"}], retencao=["loops abertos"], o_que_replicar=["lista numerada"]))
        saida = self.texto(page, f"{card} .yt-out")
        for trecho in ("Lista numerada", "Promessa numérica", "0:00 abertura", "loops abertos", "lista numerada"):
            self.assertIn(trecho, saida)

    def test_auditoria_envia_o_historico_completo_em_ordem_cronologica_com_evidencias(self):
        page = self.abrir()
        self.sub(page, "historico")
        page.fill("#yh-canal", "@alfa")
        self.clicar_e_esperar(page, "#yh-carregar")
        page.select_option("#yh-formato", "shorts")
        self.assertEqual(self.titulos(page, "#yh-tabela"), ["Sêneca em 45 segundos"])            # a tela mostra 1...
        card = "#yt-ia-historico"
        prompt = self.gerar_prompt(page, card)
        hist = prompt.split("(6 vídeos):\n")[1].split("\n\n")[0].splitlines()
        self.assertEqual(len(hist), 6)                                                          # ...mas o prompt leva os 6
        self.assertTrue(hist[0].startswith('1. "Como controlar suas emoções"'))
        self.assertTrue(hist[5].startswith('6. "Como ter um dia mais produtivo"'))
        self.aplicar_ia(page, card, ia_json(resumo="Crescimento em degraus", fases=[{"periodo": "início", "o_que_aconteceu": "canal pequeno", "evidencia": [1, 2, 60]}],
                                            recomendacoes=[{"acao": "publicar 2 por semana", "por_que": "hoje é 1"}]))
        ev = page.eval_on_selector_all(f"{card} .yt-out .yt-ev a", "els => els.map(a => [a.textContent, a.href])")
        self.assertEqual(ev, [["1", f"https://www.youtube.com/watch?v={V(6)}"], ["2", f"https://www.youtube.com/watch?v={V(5)}"]])   # os dois mais antigos; 60 não existe
        self.assertIn("publicar 2 por semana", self.texto(page, f"{card} .yt-out"))

# ====================================================================== 3 a 6

# ====================================================================== 3 a 6
class ComparaCanalVideoHistoricoTests(Base):
    def test_comparar_mostra_lado_a_lado_marca_o_maior_e_gasta_7(self):
        page = self.abrir()
        self.sub(page, "comparar")
        page.fill("#yc-a", "@alfa")
        page.fill("#yc-b", "@beta")
        self.assertIn("7 unidades", self.texto(page, "#yc-custo"))
        page.fill("#yc-a", F.uc("a"))
        self.assertIn("6 unidades", self.texto(page, "#yc-custo"))
        page.fill("#yc-a", "@alfa")
        self.clicar_e_esperar(page, "#yc-comparar")
        self.assertIn("Gastou 7 unidades", self.texto(page, "#yc-msg"))
        self.assertEqual(self.cota(page), "7")
        cab = self.texto(page, "#yc-cabecas")
        self.assertIn("Canal Alfa", cab)
        self.assertIn("120.000 inscritos", cab)
        self.assertEqual(page.locator("#yc-tabela tbody tr").count(), 11)

        def maior(rotulo):
            return page.eval_on_selector_all("#yc-tabela tbody tr", "(trs, r) => { const tr = trs.find(t => t.cells[0].textContent === r); return [...tr.cells].slice(1).map(c => c.classList.contains('yt-maior')); }", rotulo)

        self.assertEqual(maior("Inscritos"), [False, True])
        self.assertEqual(maior("Vídeos por semana (últimos vídeos)"), [True, False])
        self.assertEqual(maior("Engajamento médio (%)"), [True, False])
        self.assertEqual(maior("Tração (mediana ÷ inscritos)"), [False, True])
        self.assertNotIn("melhor", self.texto(page, "#yc-tabela").lower())                        # só diz quem é maior
        self.assertIn("Sêneca em 45 segundos", self.texto(page, "#yc-videos"))

    def test_comparar_erros(self):
        page = self.abrir()
        self.sub(page, "comparar")
        page.fill("#yc-a", "@alfa")
        page.fill("#yc-b", F.uc("a"))
        self.clicar_e_esperar(page, "#yc-comparar")
        self.assertIn("dois canais diferentes", self.texto(page, "#yc-msg"))
        page.fill("#yc-b", "@ninguem")
        self.clicar_e_esperar(page, "#yc-comparar")
        self.assertIn("Não encontrei o canal", self.texto(page, "#yc-msg"))
        self.assertFalse(page.is_visible("#yc-resultado"))

    def test_analisar_canal_com_metricas_derivadas_e_inscritos_ocultos(self):
        page = self.abrir()
        self.sub(page, "canal")
        page.fill("#yk-canal", "@alfa")
        self.assertIn("2 unidades", self.texto(page, "#yk-custo"))
        self.clicar_e_esperar(page, "#yk-analisar")

        def card(rot):
            return page.locator(f'#yk-cards .cn-card:has(.cn-card-rot:text-is("{rot}"))').inner_text()

        self.assertIn("8.500", card("Inscritos"))
        self.assertIn("10.000", card("Views por vídeo"))
        self.assertIn("0,53", card("Vídeos por semana"))
        self.assertIn("2,125%", card("Inscritos ÷ views"))
        self.assertIn("212,5", card("Inscritos por vídeo"))
        self.assertEqual(page.eval_on_selector_all("#yk-palavras .cn-chip", "els => els.map(e => e.textContent)"), ["estoicismo", "vida diária", "calma"])
        page.click("#yk-resultado summary")
        self.assertIn("Descrição de Canal Alfa", self.texto(page, "#yk-descricao"))
        page.fill("#yk-canal", "https://www.youtube.com/@gama")
        self.clicar_e_esperar(page, "#yk-analisar")
        self.assertIn("não disponível", card("Inscritos"))
        self.assertIn("o canal esconde", card("Inscritos"))
        self.assertIn("não disponível", card("Inscritos por vídeo"))
        self.assertIn("4.167", card("Views por vídeo"))
        self.assertIn("esconde o número de inscritos", self.texto(page, "#yk-msg"))

    def test_analisar_video_cartoes_thumb_tags_e_download_da_melhor_resolucao(self):
        page = self.abrir()
        self.sub(page, "video")
        page.fill("#yv-video", f"https://www.youtube.com/watch?v={V(2)}&t=5s")
        self.clicar_e_esperar(page, "#yv-analisar")

        def card(rot):
            return page.locator(f'#yv-cards .cn-card:has(.cn-card-rot:text-is("{rot}"))').inner_text()

        self.assertIn("9.000", card("Views"))
        self.assertIn("8,78%", card("Engajamento"))
        self.assertIn("10:00", card("Duração"))
        self.assertIn("Longo", card("Formato"))
        self.assertIn("1,06", card("Views ÷ inscritos"))
        self.assertTrue(page.get_attribute("#yv-thumb", "src").endswith(f"/vi/{V(2)}/maxres.jpg"))
        self.assertEqual(page.eval_on_selector_all("#yv-tags .cn-chip", "els => els.map(e => e.textContent)"), ["filosofia", "estoicismo"])
        self.assertIn("tópicos: Philosophy, Knowledge", self.texto(page, "#yv-cab"))
        with page.expect_download() as d:
            page.click("#yv-baixar")
        self.assertEqual(d.value.suggested_filename, f"{V(2)}_maxresdefault.jpg")
        self.assertTrue(Path(d.value.path()).read_bytes().startswith(b"\xff\xd8\xff"))
        self.assertEqual(self.texto(page, "#yv-baixar-info"), "Baixada em maxresdefault.")
        page.fill("#yv-video", V(4))
        self.clicar_e_esperar(page, "#yv-analisar")
        self.assertIn("Short", card("Formato"))
        with page.expect_download() as d:
            page.click("#yv-baixar")
        self.assertEqual(d.value.suggested_filename, f"{V(4)}_hqdefault.jpg")                      # sem maxres nem sd: desceu até a hq

    def test_video_sem_miniatura_e_entradas_ruins_mostram_o_motivo(self):
        page = self.abrir()
        self.sub(page, "video")
        page.fill("#yv-video", V(5))
        self.clicar_e_esperar(page, "#yv-analisar")
        page.click("#yv-baixar")
        page.wait_for_function("document.querySelector('#yv-baixar-info').textContent.includes('miniatura')")
        self.assertIn("não tem miniatura", self.texto(page, "#yv-baixar-info"))
        self.assertTrue(page.eval_on_selector("#yv-baixar-info", "e => e.classList.contains('cn-erro')"))
        page.fill("#yv-video", "isso não é link")
        self.clicar_e_esperar(page, "#yv-analisar")
        self.assertIn("Não achei o ID do vídeo", self.texto(page, "#yv-msg"))
        page.fill("#yv-video", "vid99999999")
        self.clicar_e_esperar(page, "#yv-analisar")
        self.assertIn("Não encontrei esse vídeo", self.texto(page, "#yv-msg"))

    def test_transcricao_some_ao_trocar_de_video_e_fica_ao_repetir_o_mesmo(self):
        page = self.abrir()
        self.sub(page, "video")
        page.fill("#yv-video", V(2))
        self.clicar_e_esperar(page, "#yv-analisar")
        page.fill("#yv-transcricao", "texto colado")
        self.clicar_e_esperar(page, "#yv-analisar")
        self.assertEqual(page.input_value("#yv-transcricao"), "texto colado")
        page.fill("#yv-video", V(4))
        self.clicar_e_esperar(page, "#yv-analisar")
        self.assertEqual(page.input_value("#yv-transcricao"), "")

    def test_historico_ordens_formato_e_sem_nova_chamada(self):
        page = self.abrir()
        self.sub(page, "historico")
        page.fill("#yh-canal", "@alfa")
        self.assertIn("4 unidades", self.texto(page, "#yh-custo"))
        page.fill("#yh-canal", F.uc("a"))
        self.assertIn("3 unidades", self.texto(page, "#yh-custo"))
        page.fill("#yh-canal", "@alfa")
        self.clicar_e_esperar(page, "#yh-carregar")
        self.assertIn("Gastou 4 unidades", self.texto(page, "#yh-msg"))
        self.assertEqual(self.f.por_recurso("playlistItems")[0]["maxResults"], "30")
        gastas = len(self.f.chamadas)
        self.assertEqual(self.titulos(page, "#yh-tabela"), ["Como ter um dia mais produtivo", "12 lições estoicas para ouvir toda manhã", "Pare de esperar agora", "Sêneca em 45 segundos", "Marco Aurélio explicado", "Como controlar suas emoções"])
        cards = self.texto(page, "#yh-cards")
        for trecho in ("6", "7.500", "9.400", "7,98%", "1,13"):
            self.assertIn(trecho, cards)
        ordens = {"views": "Sêneca em 45 segundos", "likes": "Sêneca em 45 segundos", "engajamento": "Sêneca em 45 segundos"}
        for chave, primeiro in ordens.items():
            page.select_option("#yh-ordem", chave)
            self.assertEqual(self.titulos(page, "#yh-tabela")[0], primeiro, chave)
        page.select_option("#yh-ordem", "engajamento")
        self.assertEqual(self.titulos(page, "#yh-tabela")[1:4], ["12 lições estoicas para ouvir toda manhã", "Como ter um dia mais produtivo", "Marco Aurélio explicado"])
        page.select_option("#yh-ordem", "views")
        self.assertEqual(self.titulos(page, "#yh-tabela")[-1], "Como ter um dia mais produtivo")
        page.select_option("#yh-formato", "shorts")
        self.assertEqual(self.texto(page, "#yh-contagem"), "1 de 6 vídeos")
        page.select_option("#yh-formato", "longos")
        self.assertEqual(self.texto(page, "#yh-contagem"), "5 de 6 vídeos")
        self.assertEqual(len(self.f.chamadas), gastas)


# ====================================================================== segurança e layout
class SegurancaELayoutTests(Base):
    def hostil(self):
        xss = lambda n: f'<img src=x onerror="window.__xss={n}">'
        self.f.add_canal(F.canal_item(F.uc("h"), f'<script>window.__xss=1</script>Canal {xss(2)}', 500, 5000, 3, "2025-01-01T00:00:00Z", handle="@hostil", keywords=f'{xss(3)} "<b id=evil>x</b>"',
                                      descricao=f"{xss(4)} descrição"), "@hostil")
        for i, dias in ((21, 1), (22, 2), (23, 3)):
            self.f.add_video(F.video_item(V(i), f"{xss(5)} Vídeo hostil {i}", F.uc("h"), f"<b id=evil2>Canal</b> {xss(6)}", dias, 1000 * i, 10, 1, "PT5M", tags=[xss(7), "<svg onload=window.__xss=8>"], topicos=["<b>x</b>"]))
        self.f.busca_ids = [V(21), V(22), V(23)]
        self.f.em_alta["BR"] = [V(21), V(22), V(23)]

    def nada_executou(self, page):
        self.assertIsNone(page.evaluate("window.__xss"))
        self.assertEqual(page.locator("#evil, #evil2, #view-yt img[src='x'], #view-yt svg[onload]").count(), 0)

    def test_texto_hostil_do_youtube_nunca_vira_html_em_nenhuma_ferramenta(self):
        self.hostil()
        page = self.abrir()
        self.buscar(page)
        self.assertIn("<img src=x", self.texto(page, "#yp-tabela"))                                # aparece como texto, não como imagem
        self.nada_executou(page)
        self.sub(page, "alta")
        page.select_option("#ya-dur", "todos")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.nada_executou(page)
        self.sub(page, "comparar")
        page.fill("#yc-a", "@alfa")
        page.fill("#yc-b", "@hostil")
        self.clicar_e_esperar(page, "#yc-comparar")
        self.assertIn("<script>", self.texto(page, "#yc-cabecas"))
        self.nada_executou(page)
        self.sub(page, "canal")
        page.fill("#yk-canal", "@hostil")
        self.clicar_e_esperar(page, "#yk-analisar")
        page.click("#yk-resultado summary")
        self.assertIn("<img src=x", self.texto(page, "#yk-descricao"))
        self.assertIn("<b id=evil>", self.texto(page, "#yk-palavras"))
        self.nada_executou(page)
        self.sub(page, "video")
        page.fill("#yv-video", V(21))
        self.clicar_e_esperar(page, "#yv-analisar")
        self.assertIn("<svg onload", self.texto(page, "#yv-tags"))
        self.nada_executou(page)
        self.sub(page, "historico")
        page.fill("#yh-canal", "@hostil")
        self.clicar_e_esperar(page, "#yh-carregar")
        self.nada_executou(page)
        # e o que a IA devolve também é texto
        self.aplicar_ia(page, "#yt-ia-historico", ia_json(resumo='<img src=x onerror="window.__xss=9">', fases=[{"periodo": "<b id=evil>x</b>", "o_que_aconteceu": "a", "evidencia": [1]}]))
        self.assertIn("<img src=x", self.texto(page, "#yt-ia-historico .yt-out"))
        self.nada_executou(page)

    def test_a_chave_so_viaja_no_corpo_das_rotas_do_youtube(self):
        page = self.abrir()
        self.buscar(page)
        self.sub(page, "alta")
        self.clicar_e_esperar(page, "#ya-carregar")
        self.gerar_prompt(page, "#yt-ia-alta")
        self.aplicar_ia(page, "#yt-ia-alta", ia_json(resumo="ok"))
        for metodo, url, corpo in self.requisicoes:
            self.assertNotIn(F.CHAVE, url)                                                       # nunca na URL
        for _, rota, corpo in self.chamadas_yt():
            if rota.startswith(("prompt/", "ia/")):
                self.assertNotIn("chave", corpo, rota)
            else:
                self.assertEqual(corpo["chave"], F.CHAVE, rota)
        texto_da_pagina = page.evaluate("document.body.innerText")
        self.assertNotIn(F.CHAVE, texto_da_pagina)                                               # nem escrita na tela (a senha fica só no campo)
        self.assertNotIn(F.CHAVE, "\n".join(u for _, u, _ in self.requisicoes))

    def test_sem_rolagem_horizontal_nas_seis_ferramentas_em_tela_media(self):
        page = self.abrir(largura=1100)
        cheque = lambda nome: self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - window.innerWidth"), 1, nome)
        cheque("topo")
        self.buscar(page)
        cheque("pesquisa")
        self.sub(page, "alta")
        self.clicar_e_esperar(page, "#ya-carregar")
        cheque("alta")
        self.sub(page, "comparar")
        page.fill("#yc-a", "@alfa")
        page.fill("#yc-b", "@beta")
        self.clicar_e_esperar(page, "#yc-comparar")
        cheque("comparar")
        self.sub(page, "canal")
        page.fill("#yk-canal", "@alfa")
        self.clicar_e_esperar(page, "#yk-analisar")
        cheque("canal")
        self.sub(page, "video")
        page.fill("#yv-video", V(2))
        self.clicar_e_esperar(page, "#yv-analisar")
        cheque("video")
        self.sub(page, "historico")
        page.fill("#yh-canal", "@alfa")
        self.clicar_e_esperar(page, "#yh-carregar")
        cheque("historico")

    def test_botao_fica_bloqueado_durante_a_chamada_e_nao_dispara_duas_vezes(self):
        page = self.abrir()
        page.fill("#yp-q", "estoicismo")
        page.evaluate("document.querySelector('#yp-buscar').click(); document.querySelector('#yp-buscar').click();")
        page.wait_for_function("!document.querySelector('#yp-buscar').disabled")
        self.assertEqual(len(self.f.por_recurso("search")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
