"""Integração em Chromium real contra um YouTube SIMULADO (tests/fake_youtube.py).

Valida a lógica de: ordenação por chip/URL, rolagem em lotes, 5 primeiros vídeos,
3 mais recentes, amostra de 50 com frequência, top 3 populares, aba Sobre e
janela de idade. Não valida os seletores do site real.
"""
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import yt_scraper as core
import fake_youtube as fake

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class IntegracaoCanal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def pagina(self, *canais):
        ctx = self._browser.new_context(viewport={"width": 1200, "height": 800})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        visitas = fake.instalar(page, list(canais))
        page.set_default_timeout(8000)
        return fake.PaginaRapida(page), visitas

    # ---- cenários ----
    def canal_diario_novo(self):
        # 34 vídeos, 1 por dia, o primeiro há 33 dias -> cobre 2 lotes de rolagem (30 + 4)
        return fake.CanalFake("novo", list(range(0, 34)), modo_ordenacao="chips")

    def test_ordenacao_aplicada_de_fato_por_chip_url_ou_nenhuma(self):
        """Garante que o chip/URL realmente reordena (o fallback de 'carregar tudo' esconderia uma falha)."""
        casos = [("chips", True), ("url", True), ("nenhum", False)]
        for modo, esperado in casos:
            with self.subTest(modo=modo):
                c = fake.CanalFake(f"ord{modo[:2]}", list(range(0, 120)), modo_ordenacao=modo)
                page, _ = self.pagina(c)
                self.assertEqual(core._abrir_videos_canal(page, c.url, "antigos"), esperado)
                if esperado:
                    self.assertEqual(core._card_video_data(page.query_selector_all(core.CARDS_CANAL_SEL)[0])["titulo"],
                                     f"Vídeo 119 do canal {c.handle}")

    def test_primeiros_5_com_chip_mais_antigos(self):
        c = self.canal_diario_novo()
        page, _ = self.pagina(c)
        r = core.scrape_first_video(page, c.url)
        self.assertTrue(r["primeiro_video_confiavel"])
        primeiros = r["primeiros_5_videos"]
        self.assertEqual(len(primeiros), 5)
        # do mais antigo para o mais novo
        self.assertEqual([v["titulo"] for v in primeiros],
                         [f"Vídeo {i} do canal novo" for i in (33, 32, 31, 30, 29)])
        # o 1º tem data exata (página do vídeo); os outros só aproximada
        esperado = (date.today() - timedelta(days=33)).isoformat()
        self.assertEqual(r["primeiro_video_data_publicacao"], esperado)
        self.assertTrue(primeiros[0]["data_exata"])
        self.assertFalse(primeiros[1]["data_exata"])
        self.assertEqual(primeiros[0]["views_num"], 1000 + 33 * 10)

    def test_recentes_e_frequencia_todo_dia(self):
        c = self.canal_diario_novo()
        page, _ = self.pagina(c)
        primeiro_iso = (date.today() - timedelta(days=33)).isoformat()
        r = core.scrape_recent_videos(page, c.url, n=50, primeiro_data_iso=primeiro_iso, total_videos=34)
        self.assertEqual(len(r["amostra_videos"]), 34)          # rolou além do 1º lote de 30
        self.assertTrue(r["amostra_completa"])
        self.assertEqual([v["titulo"] for v in r["ultimos_3_videos"]],
                         [f"Vídeo {i} do canal novo" for i in (0, 1, 2)])
        self.assertEqual(r["ultimo_video_data_publicacao"], date.today().isoformat())
        self.assertEqual(r["frequencia_label"], "todo dia")
        self.assertAlmostEqual(r["frequencia_intervalo_medio_dias"], 1.0, places=1)
        self.assertEqual(r["frequencia_atividade"], "ativo")
        self.assertGreaterEqual(r["videos_ultimos_30d"], 27)

    def test_frequencia_semanal(self):
        c = fake.CanalFake("semana", [w * 7 for w in range(0, 12)], modo_ordenacao="chips")
        page, _ = self.pagina(c)
        r = core.scrape_recent_videos(page, c.url, n=50,
                                      primeiro_data_iso=(date.today() - timedelta(days=77)).isoformat(),
                                      total_videos=12)
        self.assertEqual(r["frequencia_label"], "1 por semana")

    def test_amostra_limitada_a_50_e_top3_pela_ordenacao_populares(self):
        # 120 vídeos (1 a cada 3 dias). O mais visto de todos é o mais ANTIGO -> só o chip 'Populares' o revela.
        dias = [i * 3 for i in range(120)]
        views = [500 + i for i in range(120)]
        views[119], views[118], views[117] = 900_000, 800_000, 700_000
        c = fake.CanalFake("grande", dias, views=views, modo_ordenacao="chips")
        page, _ = self.pagina(c)
        det = core.enrich_channel_details(page, c.url, janela_meses=0, n_frequencia=50, total_videos=120)
        self.assertEqual(len(det["amostra_videos"]), 50)
        self.assertFalse(det["amostra_completa"])
        self.assertEqual([v["views_num"] for v in det["top_3_populares"]], [900_000, 800_000, 700_000])
        self.assertEqual(det["frequencia_label"], "2–3 por semana")
        # o vídeo mais antigo real foi achado pelo chip, mesmo com 120 vídeos
        self.assertEqual(det["primeiro_video_titulo"], "Vídeo 119 do canal grande")

    def test_ordenacao_por_url_quando_nao_ha_chips(self):
        c = fake.CanalFake("urlonly", list(range(0, 40)), modo_ordenacao="url")
        page, _ = self.pagina(c)
        r = core.scrape_first_video(page, c.url)
        self.assertTrue(r["primeiro_video_confiavel"])
        self.assertEqual(r["primeiro_video_titulo"], "Vídeo 39 do canal urlonly")

    def test_sem_ordenacao_carrega_tudo_e_inverte(self):
        c = fake.CanalFake("semsort", list(range(0, 45)), modo_ordenacao="nenhum")
        page, _ = self.pagina(c)
        r = core.scrape_first_video(page, c.url)
        self.assertTrue(r["primeiro_video_confiavel"])          # lista chegou ao fim
        self.assertEqual(r["primeiro_video_titulo"], "Vídeo 44 do canal semsort")
        self.assertEqual(len(r["primeiros_5_videos"]), 5)

    def test_sem_ordenacao_e_lista_incompleta_marca_idade_incerta(self):
        antigo = core.LIMITE_LISTA_COMPLETA
        core.LIMITE_LISTA_COMPLETA = 60      # simula canal enorme sem ordenação
        self.addCleanup(setattr, core, "LIMITE_LISTA_COMPLETA", antigo)
        c = fake.CanalFake("enorme", list(range(0, 200)), modo_ordenacao="nenhum")
        page, _ = self.pagina(c)
        r = core.scrape_first_video(page, c.url)
        self.assertFalse(r["primeiro_video_confiavel"])
        # idade incerta nunca vira "canal recente": entra no ranking como desconhecida
        ch = dict(r, canal="x", canal_url="u", inscritos_num=1000, n_videos=200)
        ranked = core.rank_channels([ch], janela_meses=3)
        self.assertTrue(ranked[0]["idade_desconhecida"])
        self.assertFalse(ranked[0]["fora_da_janela"])

    def test_sobre_views_totais_e_data_de_criacao(self):
        c = fake.CanalFake("sobre", list(range(0, 10)), views_totais="12.345.678", pais="Portugal")
        page, _ = self.pagina(c)
        r = core.scrape_channel_about(page, c.url)
        self.assertEqual(r["views_totais"], 12_345_678)
        self.assertEqual(r["inscritos_num"], 12_000)
        self.assertEqual(r["n_videos"], 10)
        self.assertEqual(r["data_criacao_canal"], (date.today() - timedelta(days=9 + 5)).isoformat())
        self.assertEqual(r["pais_canal"], "Portugal")

    def test_janela_descarta_canal_antigo_sem_gastar_navegacoes(self):
        # primeiro vídeo há 200 dias (~6,6 meses) e janela de 3 meses
        c = fake.CanalFake("velho", [i * 20 for i in range(11)], modo_ordenacao="chips")
        page, visitas = self.pagina(c)
        det = core.enrich_channel_details(page, c.url, janela_meses=3, descartar_fora_janela=True)
        self.assertEqual(det["primeiro_video_titulo"], "Vídeo 10 do canal velho")
        self.assertNotIn("amostra_videos", det)                  # nem chegou a ler os recentes
        self.assertEqual(det["top_3_populares"], [])
        n_abas_recentes = sum(1 for u in visitas if u.endswith("/videos"))
        self.assertLessEqual(n_abas_recentes, 1)                 # só abriu a lista de antigos
        ranked = core.rank_channels([dict(det, canal="v", canal_url="u", inscritos_num=5000, n_videos=11)], janela_meses=3)
        self.assertTrue(ranked[0]["fora_da_janela"])

    def test_janela_mantem_canal_dentro_e_analisa_por_completo(self):
        c = self.canal_diario_novo()
        page, _ = self.pagina(c)
        det = core.enrich_channel_details(page, c.url, janela_meses=3, descartar_fora_janela=True,
                                          n_frequencia=50, total_videos=34)
        self.assertEqual(len(det["primeiros_5_videos"]), 5)
        self.assertEqual(len(det["ultimos_3_videos"]), 3)
        self.assertEqual(len(det["top_3_populares"]), 3)         # amostra completa: top 3 sem outra navegação
        self.assertEqual(det["frequencia_label"], "todo dia")
        ranked = core.rank_channels([dict(det, canal="n", canal_url="u", inscritos_num=9000, n_videos=34)], janela_meses=3)
        self.assertFalse(ranked[0]["fora_da_janela"])
        self.assertEqual(ranked[0]["idade_desconhecida"], False)
        self.assertAlmostEqual(ranked[0]["meses_desde_primeiro_video"], 33 / 30.4375, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
