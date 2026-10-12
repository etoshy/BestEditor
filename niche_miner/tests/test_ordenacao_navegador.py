"""Ordenação das tabelas de canais no navegador real (servidor Flask local + dados fictícios)."""
import logging
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as webapp

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False


def canal(nome, inscritos, videos, views, score, rank, **extra):
    c = {"canal": nome, "canal_url": f"https://youtube.com/@{nome}", "inscritos_num": inscritos,
         "inscritos_text": f"{inscritos} inscritos" if inscritos is not None else "", "n_videos": videos, "views_totais": views,
         "score": score, "rank_geral": rank, "rank_grupo": rank, "termo_busca": "termo", "fora_da_janela": False}
    c.update(extra)
    return c


# Ordem original (regra do app): A, B, C, D, E
A = canal("A", 1000, 10, 50000, 50, 1)
B = canal("B", 5000, 200, 900000, 40, 2)
C = canal("C", 300, 3, 90000, 30, 3)
D = canal("D", None, None, None, 20, 4, dados_incompletos=True)
E = canal("E", 5000, 20, 100000, 10, 5)
GERAL = [A, B, C, D, E]
RESULTADO = {
    "nicho": "x", "ranking_geral": GERAL, "ranking_nao_verificados": GERAL, "verificados": [],
    "rankings_nichos": {"Grupo 1": [A, B, C, D, E], "Grupo 2": [C, A]}, "rankings_subnichos": {"S": [A]},
    "rankings_paises": {"Brasil": [A]}, "rankings_idiomas": {"Português": [A]},
    "resumo_nichos": [], "resumo_subnichos": [], "resumo_paises": [], "resumo_idiomas": [],
    "falhas_termos": [], "filtros": {}, "analise": {"janela_meses": 0}, "resumo_janela": {}, "busca_id": None,
}


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class OrdenacaoNavegadorTests(unittest.TestCase):
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

    def abrir(self, ctx=None):
        ctx = ctx or self._browser.new_context(viewport={"width": 1600, "height": 900})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        self.erros = []
        page.on("pageerror", lambda e: self.erros.append(str(e)))
        page.goto(self.url)
        page.evaluate("(r) => renderResultado(r)", RESULTADO)
        return page

    def tearDown(self):
        self.assertEqual(getattr(self, "erros", []), [])

    def nomes(self, page, painel="#panel-geral"):
        return "".join(page.locator(f"{painel} tbody tr:not(.detail-row) td.canal a").all_inner_texts())

    def posicoes(self, page, painel="#panel-geral"):
        return page.locator(f"{painel} tbody tr:not(.detail-row) td:first-child").all_inner_texts()

    def test_padrao_mantem_a_ordem_da_regra_e_o_rank_original(self):
        page = self.abrir()
        self.assertEqual(self.nomes(page), "ABCDE")
        self.assertEqual(self.posicoes(page), ["1", "2", "3", "4", "5"])
        self.assertEqual(page.input_value("#panel-geral .sort-select"), "padrao")
        self.assertTrue(page.is_disabled("#panel-geral .sort-dir"))

    def test_clicar_no_cabecalho_ordena_e_clicar_de_novo_inverte(self):
        page = self.abrir()
        page.click("#panel-geral th[data-sort=inscritos]")
        self.assertEqual(self.nomes(page), "BEACD")                       # D (sem dado) no fim
        self.assertIn("▼", page.inner_text("#panel-geral th[data-sort=inscritos]"))
        self.assertEqual(self.posicoes(page), ["1", "2", "3", "4", "5"])    # posição = lugar na ordenação atual
        page.click("#panel-geral th[data-sort=inscritos]")
        self.assertEqual(self.nomes(page), "CABED")                       # crescente; D continua no fim
        self.assertIn("▲", page.inner_text("#panel-geral th[data-sort=inscritos]"))
        page.click("#panel-geral th[data-sort=videos]")
        self.assertEqual(self.nomes(page), "CAEBD")                       # vídeos: começa por MENOS vídeos
        self.assertIn("▲", page.inner_text("#panel-geral th[data-sort=videos]"))
        self.assertNotIn("▲", page.inner_text("#panel-geral th[data-sort=inscritos]"))

    def test_seletor_e_botao_de_direcao(self):
        page = self.abrir()
        page.select_option("#panel-geral .sort-select", "views")
        self.assertEqual(self.nomes(page), "BECAD")
        page.click("#panel-geral .sort-dir")
        self.assertEqual(self.nomes(page), "ACEBD")
        page.select_option("#panel-geral .sort-select", "views_por_video")
        self.assertEqual(self.nomes(page), "CAEBD")
        self.assertEqual(page.locator("#panel-geral tbody tr:not(.detail-row)").first.locator("td").nth(5).inner_text(), "30.000")
        page.select_option("#panel-geral .sort-select", "padrao")
        self.assertEqual(self.nomes(page), "ABCDE")
        self.assertEqual(self.posicoes(page), ["1", "2", "3", "4", "5"])

    def test_combinada_menos_videos_mais_views_mais_inscritos(self):
        page = self.abrir()
        page.select_option("#panel-geral .sort-select", "combinada")
        self.assertEqual(self.nomes(page), "BECAD")
        col = page.locator("#panel-geral tbody tr:not(.detail-row) td:nth-last-child(3)").all_inner_texts()
        self.assertEqual(col, ["2,0", "2,0", "2,7", "3,0", "5,0"])
        self.assertIn("três listas", page.inner_text("#panel-geral .sort-bar .hint"))

    def test_todas_as_tabelas_ficam_sincronizadas(self):
        page = self.abrir()
        page.click("#panel-geral th[data-sort=videos]")
        page.click('.result-tab[data-result-tab="nichos"]')
        self.assertEqual(self.nomes(page, "#group-table-nicho"), "CAEBD")   # o grupo já abre na ordem escolhida no Geral
        page.select_option("#group-select-nicho", "1")
        self.assertEqual(self.nomes(page, "#group-table-nicho"), "CA")   # o grupo trocado também respeita a ordem atual
        page.select_option("#group-select-nicho", "0")
        page.select_option("#group-table-nicho .sort-select", "inscritos")
        page.click('.result-tab[data-result-tab="geral"]')
        self.assertEqual(self.nomes(page), "BEACD")                      # mudou no grupo, refletiu no Geral

    def test_botao_detalhes_continua_funcionando_apos_reordenar(self):
        page = self.abrir()
        page.click("#panel-geral th[data-sort=views]")
        page.locator("#panel-geral .btn-detalhes").first.click()
        self.assertTrue(page.locator("#panel-geral .detail-row:not([hidden])").count() == 1)

    def test_preferencia_persiste_entre_recarregamentos(self):
        ctx = self._browser.new_context(viewport={"width": 1600, "height": 900})
        page = self.abrir(ctx)
        page.click("#panel-geral th[data-sort=videos]")
        page.click("#panel-geral th[data-sort=videos]")     # crescente -> decrescente
        page.reload()
        page.evaluate("(r) => renderResultado(r)", RESULTADO)
        self.assertEqual(self.nomes(page), "BEACD")
        self.assertEqual(page.input_value("#panel-geral .sort-select"), "videos")
        self.assertIn("decrescente", page.inner_text("#panel-geral .sort-dir"))

    def test_preferencia_corrompida_volta_ao_padrao(self):
        ctx = self._browser.new_context()
        page = ctx.new_page()
        self.addCleanup(ctx.close)
        page.goto(self.url)
        page.evaluate("localStorage.setItem('niche_miner_ordenacao', '{lixo')")
        page.reload()
        page.evaluate("(r) => renderResultado(r)", RESULTADO)
        self.assertEqual(self.nomes(page), "ABCDE")

    def test_biblioteca_usa_a_mesma_tabela_com_ordenacao(self):
        page = self.abrir()
        page.evaluate("""() => { const d = document.createElement('div'); d.id = 'teste-lib';
          document.body.appendChild(d); }""")
        html = page.evaluate("(c) => renderUnverifiedTable(c, true, { mostrarFora: true })", GERAL)
        page.evaluate("(h) => { document.getElementById('teste-lib').innerHTML = h; }", html)
        page.select_option("#teste-lib .sort-select", "inscritos_por_video")
        self.assertEqual(self.nomes(page, "#teste-lib"), "EACBD")

    def test_colspan_do_detalhe_cobre_todas_as_colunas(self):
        page = self.abrir()
        colunas = page.locator("#panel-geral thead th").count()
        colspan = page.locator("#panel-geral .detail-row td").first.get_attribute("colspan")
        self.assertEqual(str(colunas), colspan)

    def test_canais_fora_da_janela_ocultos_nao_entram_na_combinada(self):
        antigo = canal("Velho", 9_000_000, 1, 99_000_000, 99, 6, fora_da_janela=True)
        resultado = {**RESULTADO, "ranking_geral": GERAL + [antigo], "analise": {"janela_meses": 3}, "resumo_janela": {"dentro": 4, "fora": 1}}
        ctx = self._browser.new_context(viewport={"width": 1600, "height": 900})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        page.goto(self.url)
        page.evaluate("(r) => renderResultado(r)", resultado)
        page.select_option("#panel-geral .sort-select", "combinada")
        self.assertEqual(self.nomes(page), "BECAD")     # Velho está oculto e não desloca as posições dos demais
        page.check("#toggle-fora-janela")
        self.assertEqual(self.nomes(page)[0], "V")      # aparece (é o melhor em tudo) depois de mostrar os fora da janela


if __name__ == "__main__":
    unittest.main(verbosity=2)
