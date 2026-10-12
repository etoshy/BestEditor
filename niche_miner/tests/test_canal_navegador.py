"""Aba Analisar canal no navegador real (servidor Flask local + banco temporário por teste).

O job de análise roda de verdade, com o Playwright e o scraper trocados por dublês (o servidor está no mesmo processo)."""
import csv
import io
import json
import logging
import os
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
import canal
import canal_api
import yt_scraper as core
from test_canal import AGORA, AMOSTRA, registro
from test_canal_api import _FakePW, detalhes_ok, sobre_ok

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False

XSS_TITULO = '<img src=x onerror="window.__xss=1"> Vídeo hostil'


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class AbaCanalTests(unittest.TestCase):
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
        self.db = os.path.join(self._tmp.name, "b.db")
        env = mock.patch.dict(os.environ, {"NICHE_MINER_DB": self.db})
        env.start()
        self.addCleanup(env.stop)
        webapp.JOBS.clear()

    def tearDown(self):
        self.assertEqual(getattr(self, "erros", []), [])

    # ------------------------------------------------------------------ apoio
    def semear(self, **extra):
        return canal.salvar_analise(registro(**extra), AGORA, self.db)

    def abrir(self):
        ctx = self._browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.url.rstrip("/"))
        self.addCleanup(ctx.close)
        ctx.add_init_script("window.CN_POLL_MS = 20;")
        page = ctx.new_page()
        self.erros, self.dialogos = [], []
        page.on("pageerror", lambda e: self.erros.append(str(e)))
        page.on("dialog", lambda d: (self.dialogos.append(d.message), d.accept()))
        page.goto(self.url)
        return page

    def aba(self, esperar_painel=True):
        page = self.abrir()
        page.click('.topnav-btn[data-view="canal"]')
        page.wait_for_selector("#view-canal", state="visible")
        if esperar_painel:
            page.wait_for_selector("#cn-painel", state="visible")
            page.wait_for_selector("#cn-videos tbody tr")
        return page

    @staticmethod
    def card(page, rotulo):
        return page.evaluate("""(r) => { const c = [...document.querySelectorAll('.cn-card')].find(x => x.querySelector('.cn-card-rot').textContent.startsWith(r));
            return c ? [c.querySelector('.cn-card-val').innerText.trim(), (c.querySelector('.cn-card-sub') || {innerText: ''}).innerText.trim()] : null; }""", rotulo)

    @staticmethod
    def titulos(page):
        return page.eval_on_selector_all("#cn-videos tbody tr", "rs => rs.map(r => r.querySelector('a').textContent.trim())")

    @staticmethod
    def ia(page, tipo):
        return page.locator(f'.cn-ia[data-tipo="{tipo}"]')

    def indices(self, aid):
        return {v["titulo"]: v["indice"] for v in canal.obter_analise(aid, self.db)["dados"]["videos"]}

    def get_json(self, caminho):
        return webapp.app.test_client().get(caminho).get_json()

    # ------------------------------------------------------------------ navegação e conteúdo
    def test_aba_abre_esconde_o_resto_e_sem_analises_mostra_o_estado_vazio(self):
        page = self.aba(esperar_painel=False)
        self.assertFalse(page.is_visible("#view-minerar"))
        self.assertFalse(page.is_visible(".rail"))
        self.assertIn("Analisar canal", page.inner_text("#view-canal .main-title"))
        page.wait_for_function("document.querySelector('#cn-analises').textContent.includes('nenhuma análise ainda')")
        self.assertFalse(page.is_visible("#cn-painel"))
        self.assertTrue(page.is_disabled("#cn-excluir"))
        page.click('.topnav-btn[data-view="minerar"]')
        self.assertTrue(page.is_visible(".rail"))

    def test_mapa_do_nextlev_cobre_as_ferramentas_e_as_minutagens_cabem_no_video(self):
        page = self.aba(esperar_painel=False)
        texto = page.inner_text("#cn-mapa")
        for esperado in ("Filtros de vídeos", "Analisar canal", "categorias", "Formatos de título", "saturação", "comentários", "Palavras por minuto",
                         "Canais similares", "Visão geral do nicho", "Descobrir canais a partir de um vídeo", "Faceless Outliers"):
            self.assertIn(esperado.lower(), texto.lower(), esperado)
        self.assertEqual(page.locator("#cn-mapa tbody tr").count(), 14)
        self.assertIn("de propósito, não", texto)                       # a saturação é recusada com motivo
        for m in page.eval_on_selector_all("#view-canal .mt-min", "ns => ns.map(n => n.textContent.trim())"):
            self.assertRegex(m, r"^\d{1,2}:\d{2}$", m)
            minutos, segundos = (int(x) for x in m.split(":"))
            self.assertLessEqual(minutos * 60 + segundos, 36 * 60, f"{m} passa da duração do vídeo (36:00)")

    # ------------------------------------------------------------------ fluxo completo (job real, scraper trocado)
    def test_analisar_de_ponta_a_ponta_abre_o_painel_e_manda_os_parametros(self):
        vistos = {}

        def detalhes(page, url, n_frequencia=50, total_videos=None, **kw):
            vistos.update(url=url, n=n_frequencia, total=total_videos)
            print("lendo vídeos do canal")
            return detalhes_ok(page, url)
        pw = _FakePW()
        with mock.patch.object(canal_api, "sync_playwright", lambda: pw), mock.patch.object(core, "scrape_channel_about", sobre_ok), \
             mock.patch.object(core, "enrich_channel_details", detalhes):
            page = self.aba(esperar_painel=False)
            page.fill("#cn-url", "youtube.com/@estoicoexemplo/videos")
            page.fill("#cn-n", "60")
            page.check("#cn-headless")
            page.click("#cn-analisar")
            page.wait_for_selector("#cn-painel", state="visible")
            page.wait_for_selector("#cn-videos tbody tr")
        self.assertEqual(vistos, {"url": "https://www.youtube.com/@estoicoexemplo", "n": 60, "total": 40})
        self.assertTrue(pw.chromium.headless)
        self.assertEqual(page.inner_text("#cn-status"), "concluído")
        log = page.inner_text("#cn-log")
        self.assertIn("lendo vídeos do canal", log)
        self.assertIn("Análise salva", log)
        self.assertIn("Estoico Exemplo", page.inner_text("#cn-cab"))
        self.assertTrue(page.is_enabled("#cn-analisar"))
        self.assertIn("#1 · Estoico Exemplo", page.inner_text("#cn-analises"))

    def test_erro_do_scraper_aparece_no_log_e_libera_o_botao(self):
        def quebra(page, url):
            raise RuntimeError("página mudou")
        pw = _FakePW()
        with mock.patch.object(canal_api, "sync_playwright", lambda: pw), mock.patch.object(core, "scrape_channel_about", quebra):
            page = self.aba(esperar_painel=False)
            page.fill("#cn-url", "@x")
            page.click("#cn-analisar")
            page.wait_for_function("document.querySelector('#cn-status').textContent === 'erro'")
        self.assertIn("ERRO: página mudou", page.inner_text("#cn-log"))
        self.assertTrue(page.is_enabled("#cn-analisar"))
        self.assertFalse(page.is_visible("#cn-painel"))

    def test_link_vazio_ou_invalido_nao_inicia_nada(self):
        page = self.aba(esperar_painel=False)
        page.click("#cn-analisar")
        self.assertEqual(page.inner_text("#cn-status"), "informe o link do canal")
        page.fill("#cn-url", "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        page.click("#cn-analisar")
        page.wait_for_function("document.querySelector('#cn-status').textContent === 'erro'")
        self.assertIn("link de um vídeo", page.inner_text("#cn-log"))
        self.assertEqual(webapp.JOBS, {})
        self.assertTrue(page.is_enabled("#cn-analisar"))

    # ------------------------------------------------------------------ painel
    def test_painel_mostra_as_metricas_do_canal(self):
        self.semear()
        page = self.aba()
        cab = page.inner_text("#cn-cab")
        self.assertIn("Estoico Exemplo", cab)
        self.assertIn("16 vídeos lidos (16 com views)", cab)
        self.assertEqual(page.get_attribute("#cn-cab a", "href"), "https://www.youtube.com/@estoicoexemplo")
        self.assertNotEqual(page.eval_on_selector("#cn-cab a", "a => getComputedStyle(a).color"), "rgb(0, 0, 238)")      # não o azul padrão, ilegível no fundo escuro
        self.assertIn("Amostra: os 16 vídeos mais recentes de 40", cab)
        esperado = {"Inscritos": "8.500", "Views totais": "400.000", "Vídeos publicados": "40", "Views por vídeo": "10.000",
                    "Mediana dos últimos 10": "4.000", "Tração": "0,471", "Idade do canal": "160 dias", "Vídeos por mês": "7,6",
                    "Vídeos nos últimos 30 dias": "4", "Duração média": "10:49", "Views médias por mês": "76.094"}
        for rotulo, valor in esperado.items():
            self.assertEqual(self.card(page, rotulo)[0], valor, rotulo)
        media_titulo = f"{round(sum(len(t) for _, t, _, _ in AMOSTRA) / 16, 1):.1f}".replace(".", ",")
        self.assertEqual(self.card(page, "Título médio")[0], media_titulo)
        self.assertEqual(self.card(page, "Idade do canal")[1], "5,3 meses")
        self.assertEqual(self.card(page, "Duração média")[1], "mediana 10:00")
        self.assertIn("intermediário", self.card(page, "Tração")[1])
        self.assertEqual(self.card(page, "Vídeos nos últimos 30 dias")[1], "1 vídeo por semana")
        for nd in ("Shorts", "Monetizado"):
            self.assertEqual(self.card(page, nd)[0], "não coletado")

    def test_tracao_usa_os_limites_ajustados_na_aba_metodo(self):
        self.semear()
        page = self.aba()
        page.evaluate("() => { document.getElementById('mp-forte').value = '0.4'; }")
        page.select_option("#cn-analises", "")
        page.select_option("#cn-analises", "1")
        page.wait_for_function("[...document.querySelectorAll('.cn-card-sub')].some(n => n.textContent.includes('algoritmo entregando'))")
        self.assertIn("algoritmo entregando", self.card(page, "Tração")[1])

    def test_melhores_e_piores_desempenhos(self):
        self.semear()
        page = self.aba()
        melhores = page.inner_text("#cn-melhores")
        self.assertTrue(melhores.startswith("12 lições estoicas para ouvir toda manhã"))
        self.assertIn("9.000 views · há 30 dia(s)", melhores)
        self.assertEqual(page.locator("#cn-melhores li").count(), 5)
        piores = page.inner_text("#cn-piores")
        self.assertEqual(page.locator("#cn-piores li").count(), 5)
        self.assertNotIn("Como ter um dia mais produtivo", piores)                # 3 dias: ainda não juntou views
        self.assertTrue(piores.startswith("Meditações de Marco Aurélio resumo"))

    def test_estruturas_de_titulo_e_palavras_chave(self):
        self.semear()
        page = self.aba()
        linhas = page.eval_on_selector_all("#cn-padroes tbody tr", "rs => rs.map(r => [...r.cells].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))")
        por = {l[0]: l for l in linhas}
        numero = por["Começa com número (ex.: 12 lições...)"]
        self.assertEqual(numero[1:4], ["3 de 15", "8.500", "1.900"])
        self.assertIn("4,47×", numero[4])
        self.assertIn("poucos vídeos", numero[4])
        self.assertIn("Compara 15 vídeos", page.inner_text("#cn-padroes"))
        self.assertIn("correlação em amostra pequena", page.inner_text("#cn-padroes"))
        chip = page.inner_text("#cn-palavras")
        self.assertIn("estoicismo", chip)
        self.assertIn("6 títulos", chip)
        self.assertIn("termina o título em 3", chip)

    def test_canal_com_poucos_dados_avisa_e_nao_quebra(self):
        canal.salvar_analise({"canal": "Vazio", "canal_url": "https://www.youtube.com/@vazio",
                              "amostra_videos": [{"video_id": "a", "titulo": "Único vídeo", "url": "https://youtu.be/a", "views_num": 100, "data": "", "duracao": ""}]},
                             AGORA, self.db)
        page = self.aba()
        self.assertIn("Poucos vídeos com views lidos", page.inner_text("#cn-cab"))
        self.assertEqual(self.card(page, "Inscritos")[0], "—")
        self.assertEqual(self.card(page, "Tração")[0], "—")
        self.assertIn("nenhuma estrutura", page.inner_text("#cn-padroes"))
        self.assertIn("nenhuma palavra", page.inner_text("#cn-palavras"))
        self.assertEqual(page.locator("#cn-videos tbody tr").count(), 1)

    # ------------------------------------------------------------------ explorador
    def test_explorador_lista_todos_por_views_e_filtra_por_texto_periodo_views_e_fator(self):
        self.semear()
        page = self.aba()
        self.assertEqual(page.locator("#cn-videos tbody tr").count(), 16)
        self.assertEqual(self.titulos(page)[0], "12 lições estoicas para ouvir toda manhã")
        self.assertEqual(page.inner_text("#cn-videos-info"), "16 de 16 vídeos")

        page.fill("#cn-f-texto", "seneca")                                        # sem acento, sem caixa
        self.assertEqual(sorted(self.titulos(page)), ["3 lições de Sêneca para ansiedade", "Sêneca sobre o tempo"])
        page.click("#cn-f-limpar")

        page.select_option("#cn-f-dias", "30")
        self.assertEqual(sorted(self.titulos(page)), ["12 lições estoicas para ouvir toda manhã", "Como parar de reclamar da vida com estoicismo",
                                                       "Como ter um dia mais produtivo com estoicismo"])            # 30, 20 e 3 dias (o de 30 entra)
        page.select_option("#cn-f-dias", "7")
        self.assertEqual(self.titulos(page), ["Como ter um dia mais produtivo com estoicismo"])
        page.click("#cn-f-limpar")

        page.fill("#cn-f-vmin", "5 mil")
        self.assertEqual(page.locator("#cn-videos tbody tr").count(), 8)
        page.fill("#cn-f-vmax", "7 mil")
        views = page.eval_on_selector_all("#cn-videos tbody tr", "rs => rs.map(r => r.cells[2].innerText.trim())")
        self.assertEqual(sorted(views), ["5.000", "6.000", "6.500", "7.000"])
        page.click("#cn-f-limpar")

        page.fill("#cn-f-fator", "2")                                             # mediana 4.000: só os de 8.000+
        self.assertEqual(page.inner_text("#cn-videos-info"), "3 de 16 vídeos")
        linha = page.eval_on_selector("#cn-videos tbody tr", "r => [...r.cells].map(c => c.innerText.replace(/\\s+/g, ' ').trim())")
        self.assertEqual((linha[2], linha[4]), ("9.000", "2,3×"))                # 9.000 / 4.000 = 2,25

    def test_ordenacao_valor_ruim_e_nenhum_resultado(self):
        self.semear()
        page = self.aba()
        page.select_option("#cn-f-ordem", "data")
        self.assertEqual(self.titulos(page)[0], "Como ter um dia mais produtivo com estoicismo")       # 3 dias atrás
        page.select_option("#cn-f-ordem", "duracao")
        self.assertEqual(self.titulos(page)[0], "Meditações de Marco Aurélio resumo")                   # 20 min
        page.select_option("#cn-f-ordem", "original")
        page.fill("#cn-f-vmin", "abc")
        self.assertIn("não entendi: abc", page.inner_text("#cn-videos-info"))
        self.assertEqual(page.locator("#cn-videos tbody tr").count(), 16)                              # valor ruim não filtra
        page.fill("#cn-f-vmin", "")
        page.fill("#cn-f-texto", "zzzz")
        self.assertIn("nenhum vídeo com esses filtros", page.inner_text("#cn-videos"))
        self.assertTrue(page.is_disabled("#cn-csv"))
        self.assertTrue(page.is_disabled("#cn-json"))

    def test_exportar_csv_e_json_respeitam_filtros_e_ordem(self):
        self.semear()
        page = self.aba()
        page.fill("#cn-f-texto", "seneca")
        with page.expect_download() as d:
            page.click("#cn-csv")
        self.assertRegex(d.value.suggested_filename, r"^videos_estoico_exemplo_\d{4}-\d{2}-\d{2}\.csv$")
        bruto = Path(d.value.path()).read_bytes().decode("utf-8")
        self.assertTrue(bruto.startswith("\ufeffTítulo,URL,Views,Views por dia,Fator outlier (x a mediana),Publicado em,Idade (dias),Duração,Categoria"))
        linhas = list(csv.DictReader(io.StringIO(bruto.lstrip("\ufeff"))))
        self.assertEqual([l["Título"] for l in linhas], ["3 lições de Sêneca para ansiedade", "Sêneca sobre o tempo"])      # por views
        self.assertEqual((linhas[0]["Views"], linhas[0]["Fator outlier (x a mediana)"], linhas[0]["Duração"], linhas[0]["Idade (dias)"]), ("6500", "1.63", "12:00", "155"))
        with page.expect_download() as d:
            page.click("#cn-json")
        self.assertTrue(d.value.suggested_filename.endswith(".json"))
        dados = json.loads(Path(d.value.path()).read_text(encoding="utf-8"))
        self.assertEqual([x["titulo"] for x in dados], ["3 lições de Sêneca para ansiedade", "Sêneca sobre o tempo"])
        self.assertEqual(dados[0]["views"], 6500)

    def test_exportar_a_analise_inteira(self):
        self.semear()
        page = self.aba()
        with page.expect_download() as d:
            page.click("#cn-exp-analise")
        dados = json.loads(Path(d.value.path()).read_text(encoding="utf-8"))
        self.assertEqual((dados["canal"], dados["dados"]["metricas"]["mediana_ultimos"], dados["ia"]), ("Estoico Exemplo", 4000, {}))
        self.assertEqual(len(dados["dados"]["videos"]), 16)

    # ------------------------------------------------------------------ IA externa: categorias
    def test_categorias_gerar_copiar_colar_aplicar_e_usar_no_explorador(self):
        aid = self.semear()
        idx = self.indices(aid)
        page = self.aba()
        cat = self.ia(page, "categorias")
        self.assertTrue(cat.locator(".cn-copiar").is_disabled())
        cat.locator(".cn-gerar").click()
        cat.locator(".cn-prompt-out").wait_for(state="visible")
        prompt = cat.locator(".cn-prompt-out").input_value()
        self.assertIn('Canal: "Estoico Exemplo"', prompt)
        self.assertIn('"categorias"', prompt)
        self.assertIn("Prompt de", cat.locator(".cn-msg-prompt").inner_text())
        cat.locator(".cn-copiar").click()
        page.wait_for_function("document.querySelector('.cn-ia[data-tipo=categorias] .cn-msg-prompt').textContent === 'Copiado.'")
        self.assertEqual(page.evaluate("navigator.clipboard.readText()"), prompt)

        como = [idx["Como ter um dia mais produtivo com estoicismo"], idx["Como parar de reclamar da vida com estoicismo"],
                idx["Como controlar suas emoções segundo o estoicismo"], idx["Como lidar com pessoas difíceis usando o estoicismo"]]
        listas = [idx["12 lições estoicas para ouvir toda manhã"], idx["5 hábitos estoicos que mudam sua vida"], idx["3 lições de Sêneca para ansiedade"], 999]
        filos = [idx["Marco Aurélio e a arte de aceitar"], idx["Sêneca sobre o tempo"], idx["Epicteto explica a liberdade"], idx["Meditações de Marco Aurélio resumo"]]
        resposta = "Claro!\n```json\n" + json.dumps({"categorias": [
            {"nome": "Como fazer", "descricao": "Guias práticos", "indices": como}, {"nome": "Listas", "indices": listas},
            {"nome": "Filósofos", "indices": filos}]}) + "\n```"
        cat.locator(".cn-colar").fill(resposta)
        cat.locator(".cn-aplicar").click()
        cat.locator(".cn-out table").wait_for()
        self.assertEqual(cat.locator(".cn-msg").inner_text(), "Aplicado.")
        linhas = cat.locator(".cn-out tbody tr").evaluate_all("rs => rs.map(r => [...r.cells].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))")
        self.assertEqual([l[0].split(" ")[0] for l in linhas], ["Listas", "Como", "Filósofos"])              # ordenadas pela mediana
        self.assertEqual(linhas[0][1:5], ["3", "19%", "8.500", "8.000"])
        self.assertEqual(linhas[1][1:5], ["4", "25%", "6.500", "5.350"])
        self.assertIn("12 lições estoicas", linhas[0][5])
        self.assertIn("5 vídeo(s) ficaram sem categoria", cat.locator(".cn-out").inner_text())
        self.assertEqual(cat.locator(".cn-colar").input_value(), "")

        # o explorador ganha a coluna e o filtro de categoria
        self.assertIn("Listas (3)", page.inner_text("#cn-f-cat"))
        self.assertIn("Categoria", page.inner_text("#cn-videos thead"))
        page.select_option("#cn-f-cat", label="Listas (3)")
        self.assertEqual(sorted(self.titulos(page)), ["12 lições estoicas para ouvir toda manhã", "3 lições de Sêneca para ansiedade", "5 hábitos estoicos que mudam sua vida"])
        with page.expect_download() as d:
            page.click("#cn-csv")
        linhas_csv = list(csv.DictReader(io.StringIO(Path(d.value.path()).read_text(encoding="utf-8").lstrip("\ufeff"))))
        self.assertEqual({l["Categoria"] for l in linhas_csv}, {"Listas"})

        # persiste ao recarregar e pode ser apagado
        page.reload()
        page.click('.topnav-btn[data-view="canal"]')
        cat = self.ia(page, "categorias")
        cat.locator(".cn-out table").wait_for()
        cat.locator(".cn-apagar").click()
        page.wait_for_function("document.querySelector('.cn-ia[data-tipo=categorias] .cn-out').innerHTML === ''")
        self.assertNotIn("Categoria", page.inner_text("#cn-videos thead"))
        self.assertEqual(page.input_value("#cn-f-cat"), "")

    def test_resposta_ruim_da_ia_mostra_o_erro_e_nao_aplica_nada(self):
        self.semear()
        page = self.aba()
        cat = self.ia(page, "categorias")
        for lixo in ("isso não é json", '{"categorias": []}', ""):
            cat.locator(".cn-colar").fill(lixo)
            cat.locator(".cn-aplicar").click()
            page.wait_for_function("document.querySelector('.cn-ia[data-tipo=categorias] .cn-msg').textContent.length > 0")
            self.assertIn("cn-erro", cat.locator(".cn-msg").get_attribute("class"))
        self.assertEqual(cat.locator(".cn-out").inner_html(), "")
        self.assertEqual(canal.obter_analise(1, self.db)["ia"], {})

    # ------------------------------------------------------------------ IA externa: estratégia e comentários
    def test_estrategia_usa_mercado_e_objetivo_no_prompt_e_renderiza_a_resposta_com_seguranca(self):
        self.semear()
        page = self.aba()
        self.assertIn("Alemanha", page.inner_text("#cn-mercado"))
        page.select_option("#cn-mercado", "DE")
        page.fill("#cn-objetivo", "canal dark em alemão, sem aparecer")
        est = self.ia(page, "estrategia")
        est.locator(".cn-gerar").click()
        est.locator(".cn-prompt-out").wait_for(state="visible")
        prompt = est.locator(".cn-prompt-out").input_value()
        self.assertIn("Alemanha — títulos em alemão", prompt)
        self.assertIn("Meu objetivo: canal dark em alemão, sem aparecer", prompt)
        self.assertIn("NÃO invente porcentagens", prompt)

        resposta = {"padroes_de_desempenho": [{"padrao": "Número no início", "evidencia": "3 dos 5 melhores", "confianca": "media"}],
                    "formula_de_conteudo": {"promessa_central": "Calma diária"},
                    "publico": {"quem_e": "Adultos 25-40", "gatilhos_emocionais": ["ansiedade", "cansaço"]},
                    "oportunidades": [{"oportunidade": XSS_TITULO, "como_diferenciar": "casos reais", "risco": "nicho lotado"}],
                    "topicos_sugeridos": [{"titulo": "5 Gewohnheiten der Stoiker", "angulo": "para o trabalho"}],
                    "roteiro": {"gancho": "Pergunta forte"}, "riscos_e_ressalvas": ["amostra pequena"]}
        est.locator(".cn-colar").fill(json.dumps(resposta))
        est.locator(".cn-aplicar").click()
        est.locator(".cn-out .cn-bloco").first.wait_for()
        saida = est.locator(".cn-out").inner_text()
        for esperado in ("Hipóteses da IA", "Padrões de desempenho", "Número no início", "Fórmula de conteúdo", "Calma diária", "ansiedade, cansaço",
                         "Como diferenciar: casos reais", "Risco: nicho lotado", "5 Gewohnheiten der Stoiker", "Diretrizes de roteiro", "Pergunta forte", "amostra pequena"):
            self.assertIn(esperado, saida, esperado)
        self.assertIn("<img src=x", saida)                                              # hostil aparece como texto
        self.assertIsNone(page.evaluate("window.__xss || null"))

    def test_comentarios_exigem_o_minimo_e_a_resposta_vira_listas(self):
        self.semear()
        page = self.aba()
        com = self.ia(page, "comentarios")
        page.fill("#cn-comentarios", "só um\ndois")
        com.locator(".cn-gerar").click()
        page.wait_for_function("document.querySelector('.cn-ia[data-tipo=comentarios] .cn-msg-prompt').textContent.length > 0")
        self.assertIn("pelo menos 5", com.locator(".cn-msg-prompt").inner_text())
        self.assertTrue(com.locator(".cn-copiar").is_disabled())
        self.assertFalse(com.locator(".cn-prompt-out").is_visible())

        page.fill("#cn-comentarios", "Ótimo vídeo\nÁudio ruim demais\nAdorei a voz\nQuero mais sobre Sêneca\nQuando sai o próximo?")
        com.locator(".cn-gerar").click()
        com.locator(".cn-prompt-out").wait_for(state="visible")
        self.assertIn("- Áudio ruim demais", com.locator(".cn-prompt-out").input_value())
        resposta = {"gostaram": [{"tema": "Voz calma", "quantos_comentarios": 12, "exemplo": "adoro a voz"}], "nao_gostaram": [{"tema": "Áudio baixo"}],
                    "pedidos": ["legendas"], "perguntas_frequentes": ["Quando sai o próximo?"],
                    "discussoes": [{"tema": "Estoicismo é frio?", "posicoes": ["sim", "não"]}], "ideias_de_video": [{"titulo": "Estoicismo e ansiedade", "dor": "ansiedade"}]}
        com.locator(".cn-colar").fill(json.dumps(resposta))
        com.locator(".cn-aplicar").click()
        com.locator(".cn-out .cn-bloco").first.wait_for()
        saida = com.locator(".cn-out").inner_text()
        for esperado in ("O que o público elogia", "Voz calma", "≈ 12 comentários", "“adoro a voz”", "O que o público critica", "Áudio baixo", "legendas",
                         "Quando sai o próximo?", "sim × não", "Estoicismo e ansiedade"):
            self.assertIn(esperado, saida, esperado)

    def test_o_que_a_ia_devolveu_entra_no_prompt_de_estrategia_seguinte(self):
        self.semear()
        page = self.aba()
        com = self.ia(page, "comentarios")
        com.locator(".cn-colar").fill(json.dumps({"nao_gostaram": [{"tema": "áudio baixo"}], "pedidos": ["legendas"]}))
        com.locator(".cn-aplicar").click()
        com.locator(".cn-out .cn-bloco").first.wait_for()
        est = self.ia(page, "estrategia")
        est.locator(".cn-gerar").click()
        est.locator(".cn-prompt-out").wait_for(state="visible")
        prompt = est.locator(".cn-prompt-out").input_value()
        self.assertIn("critica: áudio baixo", prompt)
        self.assertIn("pede: legendas", prompt)

    # ------------------------------------------------------------------ várias análises
    def test_abre_a_mais_recente_troca_e_exclui_analises_salvas(self):
        a1 = self.semear()
        a2 = self.semear(canal="Segundo Canal", canal_url="https://www.youtube.com/@segundo", inscritos_num=1000)
        page = self.aba()                                                                  # sem histórico no navegador: abre a mais recente
        self.assertEqual(page.input_value("#cn-analises"), str(a2))
        self.assertIn("Segundo Canal", page.inner_text("#cn-cab"))
        self.assertEqual(self.card(page, "Inscritos")[0], "1.000")
        page.select_option("#cn-analises", str(a1))
        page.wait_for_function("document.querySelector('.cn-card-val').innerText === '8.500'")
        self.assertIn("Estoico Exemplo", page.inner_text("#cn-cab"))
        page.click("#cn-excluir")
        self.assertIn(f"Excluir a análise #{a1}", self.dialogos[-1])
        page.wait_for_function("document.querySelector('#cn-cab').textContent.includes('Segundo Canal')")   # cai na que sobrou
        self.assertIsNone(canal.obter_analise(a1, self.db))
        self.assertIsNotNone(canal.obter_analise(a2, self.db))

    def test_excluir_a_ultima_esconde_o_painel(self):
        self.semear()
        page = self.aba()
        page.click("#cn-excluir")
        page.wait_for_function("document.querySelector('#cn-analises').textContent.includes('nenhuma análise ainda')")
        self.assertFalse(page.is_visible("#cn-painel"))
        self.assertTrue(page.is_disabled("#cn-excluir"))

    # ------------------------------------------------------------------ pontes
    def test_ponte_para_recomendacoes_manda_os_3_mais_vistos_sem_duplicar(self):
        self.semear()
        page = self.aba()
        page.click("#cn-ponte-similares")
        self.assertTrue(page.is_visible("#view-minerar"))
        urls = page.input_value("#rec-urls").split("\n")
        top3 = [v["url"] for v in canal.obter_analise(1, self.db)["dados"]["metricas"]["melhores"][:3]]
        self.assertEqual(urls, top3)
        self.assertTrue(page.is_enabled("#btn-rec-iniciar"))
        page.click('.topnav-btn[data-view="canal"]')
        self.assertIn("Enviei 3 link(s)", page.inner_text("#cn-ponte-info"))
        page.click("#cn-ponte-similares")
        self.assertEqual(len(page.input_value("#rec-urls").split("\n")), 3)                 # não duplica

    def test_botao_de_cada_video_manda_so_aquele_video(self):
        self.semear()
        page = self.aba()
        page.locator("#cn-videos tbody tr", has_text="Sêneca sobre o tempo").locator(".cn-similar").click()
        self.assertTrue(page.is_visible("#view-minerar"))
        esperado = [v["url"] for v in canal.obter_analise(1, self.db)["dados"]["videos"] if v["titulo"] == "Sêneca sobre o tempo"]
        self.assertEqual(page.input_value("#rec-urls").split("\n"), esperado)

    def test_ponte_para_ideias_cria_a_pesquisa_e_abre_no_radar(self):
        self.semear()
        page = self.aba()
        self.assertEqual(page.input_value("#cn-ponte-tema"), "Estoicismo")
        self.assertEqual(page.input_value("#cn-ponte-termos"), "estoicismo")
        page.select_option("#cn-mercado", "DE")
        page.click("#cn-ponte-nicho")
        page.wait_for_selector("#id-fluxo", state="visible")
        self.assertTrue(page.is_visible("#view-ideias"))
        pesquisas = self.get_json("/api/ideias/pesquisas")["pesquisas"]
        self.assertEqual([p["tema"] for p in pesquisas], ["Estoicismo"])
        pid = pesquisas[0]["id"]
        self.assertEqual(self.get_json(f"/api/ideias/pesquisas/{pid}")["pesquisa"]["mercado"], "DE")
        self.assertEqual(page.input_value("#id-sessoes"), str(pid))
        self.assertEqual(page.input_value("#id-termos"), "estoicismo")

        # segunda vez, com a aba Ideias já iniciada: a pesquisa nova entra no seletor à mão
        page.click('.topnav-btn[data-view="canal"]')
        page.fill("#cn-ponte-tema", "Marco Aurélio")
        page.fill("#cn-ponte-termos", "marco aurélio, meditações")
        page.click("#cn-ponte-nicho")
        page.wait_for_function("document.querySelector('#id-termos').value === 'marco aurélio\\nmeditações'")
        self.assertEqual(len(self.get_json("/api/ideias/pesquisas")["pesquisas"]), 2)

    def test_ponte_para_ideias_sem_tema_ou_termos_avisa(self):
        self.semear()
        page = self.aba()
        page.fill("#cn-ponte-termos", "  ,  ")
        page.click("#cn-ponte-nicho")
        self.assertIn("Informe o tema", page.inner_text("#cn-ponte-nicho-info"))
        self.assertEqual(self.get_json("/api/ideias/pesquisas")["pesquisas"], [])
        self.assertFalse(page.is_visible("#id-fluxo"))

    def test_atalho_para_o_semaforo_de_saturacao_da_aba_metodo(self):
        page = self.aba(esperar_painel=False)
        page.click("#cn-ir-metodo")
        self.assertTrue(page.is_visible("#view-metodo"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "ms-n")

    # ------------------------------------------------------------------ segurança
    def test_nomes_e_titulos_hostis_nao_executam_em_nenhuma_parte_da_aba(self):
        canal.salvar_analise(registro(canal='<img src=x onerror="window.__xss=1">Canal', amostra=[(3, XSS_TITULO, 900, "9:00")] + AMOSTRA[1:]), AGORA, self.db)
        page = self.aba()
        self.assertIn("<img src=x", page.inner_text("#cn-cab"))
        self.assertIn("<img src=x", page.inner_text("#cn-analises"))
        self.assertIn("<img src=x", page.inner_text("#cn-videos"))
        page.select_option("#cn-f-ordem", "data")
        self.assertIn("<img src=x", page.inner_text("#cn-videos"))
        cat = self.ia(page, "categorias")
        cat.locator(".cn-colar").fill(json.dumps({"categorias": [{"nome": XSS_TITULO, "descricao": XSS_TITULO, "indices": [1, 2, 3]}]}))
        cat.locator(".cn-aplicar").click()
        cat.locator(".cn-out table").wait_for()
        self.assertIn("<img src=x", cat.locator(".cn-out").inner_text())
        self.assertIn("<img src=x", page.inner_text("#cn-f-cat"))
        page.fill("#cn-f-texto", '<b onmouseover="window.__xss=1">')
        self.assertIsNone(page.evaluate("window.__xss || null"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
