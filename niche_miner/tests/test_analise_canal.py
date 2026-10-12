"""Testes das funções de análise de canal (frequência, datas relativas, Sobre, janela).

O teste dos cards usa um fixture reproduzindo o HTML REAL da aba /videos enviado
pelo usuário (layout ``yt-lockup-view-model``) e roda em Chromium de verdade.
"""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yt_scraper as core

FIXTURE = ROOT / "tests" / "fixtures" / "canal_videos_grid_novo_layout.html"
HOJE = datetime(2026, 9, 19, 12, 0)


class ParseCountTests(unittest.TestCase):
    def test_agrupamento_de_milhares_do_sobre(self):
        # O Sobre mostra o número completo; antes "1.234.567" virava 1.
        self.assertEqual(core.parse_count("1.234.567 visualizações"), 1_234_567)
        self.assertEqual(core.parse_count("12.345.678 visualizações"), 12_345_678)
        self.assertEqual(core.parse_count("1,234,567 views"), 1_234_567)

    def test_formatos_antigos_continuam_iguais(self):
        self.assertEqual(core.parse_count("234 mil visualizações"), 234_000)
        self.assertEqual(core.parse_count("7,7 mil visualizações"), 7_700)
        self.assertEqual(core.parse_count("1,2 mi"), 1_200_000)
        self.assertEqual(core.parse_count("8.443 visualizações"), 8_443)
        self.assertEqual(core.parse_count("8.4K"), 8_400)


class DataRelativaTests(unittest.TestCase):
    def d(self, texto):
        return core._data_aproximada_de_texto(texto, agora=HOJE)

    def test_unidades_em_portugues_e_ingles(self):
        self.assertEqual(self.d("há 5 horas"), date(2026, 9, 19))
        self.assertEqual(self.d("há 2 dias"), date(2026, 9, 17))
        self.assertEqual(self.d("Transmitido há 2 dias"), date(2026, 9, 17))
        self.assertEqual(self.d("2 days ago"), date(2026, 9, 17))
        self.assertEqual(self.d("Streamed 3 weeks ago"), self.d("há 3 semanas"))

    def test_ponto_medio_da_faixa(self):
        # "há 1 mês" = 30 a 59 dias -> ~45 dias; "há 1 ano" -> ~1,5 ano
        self.assertEqual((date(2026, 9, 19) - self.d("há 1 mês")).days, 45)
        self.assertEqual((date(2026, 9, 19) - self.d("há 3 semanas")).days, 24)

    def test_nao_e_data_relativa(self):
        self.assertIsNone(self.d("192 mil visualizações"))
        self.assertIsNone(self.d(""))
        self.assertIsNone(self.d(None))


class FrequenciaTests(unittest.TestCase):
    def videos(self, dias):
        return [{"data_aprox": (date(2026, 9, 19) - __import__("datetime").timedelta(days=d)).isoformat()} for d in dias]

    def test_rotulos_por_faixa(self):
        casos = [(0.3, "vários por dia"), (1.0, "todo dia"), (1.5, "quase todo dia"), (2.33, "2–3 por semana"),
                 (7, "1 por semana"), (14, "a cada 2 semanas"), (30, "1 por mês"), (90, "menos de 1 por mês"),
                 (None, "dados insuficientes")]
        for intervalo, esperado in casos:
            with self.subTest(intervalo=intervalo):
                self.assertEqual(core.classificar_frequencia(intervalo), esperado)

    def test_todo_dia(self):
        f = core.analisar_frequencia(self.videos(range(0, 30)), agora=HOJE)
        self.assertEqual(f["frequencia_label"], "todo dia")
        self.assertEqual(f["frequencia_n_amostra"], 30)
        self.assertEqual(f["videos_ultimos_30d"], 30)
        self.assertEqual(f["frequencia_atividade"], "ativo")

    def test_uma_por_semana(self):
        f = core.analisar_frequencia(self.videos(range(0, 70, 7)), agora=HOJE)
        self.assertEqual(f["frequencia_label"], "1 por semana")
        self.assertEqual(f["frequencia_videos_por_semana"], 1.0)

    def test_uma_por_mes(self):
        f = core.analisar_frequencia(self.videos(range(0, 300, 30)), agora=HOJE)
        self.assertEqual(f["frequencia_label"], "1 por mês")

    def test_ancoras_exatas_prevalecem_sobre_as_aproximadas(self):
        v = self.videos([2, 3, 4])
        f = core.analisar_frequencia(v, agora=HOJE, ultimo_data_iso="2026-09-19",
                                     primeiro_data_iso="2026-09-09", amostra_completa=True)
        self.assertEqual(f["frequencia_periodo_dias"], 10)          # 19/09 - 09/09
        self.assertEqual(f["frequencia_intervalo_medio_dias"], 5.0)  # 10 dias / 2 intervalos
        self.assertEqual(f["frequencia_label"], "1 por semana")

    def test_ancora_do_primeiro_so_vale_com_amostra_completa(self):
        v = self.videos([0, 1, 2])
        f = core.analisar_frequencia(v, agora=HOJE, primeiro_data_iso="2020-01-01", amostra_completa=False)
        self.assertEqual(f["frequencia_periodo_dias"], 2)            # ignorou a âncora de 2020

    def test_canal_parado(self):
        f = core.analisar_frequencia(self.videos([120, 127, 134, 141]), agora=HOJE)
        self.assertEqual(f["frequencia_atividade"], "parado")
        self.assertEqual(f["dias_desde_ultimo_video"], 120)

    def test_poucos_dados(self):
        self.assertEqual(core.analisar_frequencia([], agora=HOJE)["frequencia_label"], "dados insuficientes")
        um = core.analisar_frequencia(self.videos([3]), agora=HOJE)
        self.assertEqual(um["frequencia_label"], "dados insuficientes")
        self.assertTrue(um["frequencia_amostra_pequena"])
        self.assertEqual(core.analisar_frequencia(self.videos(range(0, 50)), agora=HOJE)["frequencia_amostra_pequena"], False)

    def test_video_sem_data_e_ignorado(self):
        f = core.analisar_frequencia(self.videos([0, 7]) + [{"quando": "Estreia em breve"}], agora=HOJE)
        self.assertEqual(f["frequencia_n_amostra"], 2)


class SobreTests(unittest.TestCase):
    def test_views_totais_e_data_de_criacao(self):
        texto = ("Canal sobre tecnologia. Assista 5.000 visualizações de conteúdo!\nEstatísticas\n"
                 "Inscreveu-se em 15 de mar. de 2026\n12.345.678 visualizações\nBrasil")
        r = core._extrair_stats_about(texto)
        self.assertEqual(r["views_totais"], 12_345_678)      # última ocorrência, não a da descrição
        self.assertEqual(r["data_criacao_canal"], "2026-03-15")

    def test_ingles(self):
        r = core._extrair_stats_about("Joined Mar 15, 2026\n1,234,567 views")
        self.assertEqual(r["views_totais"], 1_234_567)
        self.assertEqual(r["data_criacao_canal"], "2026-03-15")

    def test_sem_estatisticas_nao_inventa(self):
        r = core._extrair_stats_about("Só uma descrição.")
        self.assertIsNone(r["views_totais"])
        self.assertEqual(r["data_criacao_canal"], "")


class AnaliseConfigTests(unittest.TestCase):
    def test_padroes(self):
        self.assertEqual(core._normalizar_analise(None),
                         {"janela_meses": 3, "descartar_fora_janela": True, "n_frequencia": 50})

    def test_limites_e_valores_invalidos(self):
        self.assertEqual(core._normalizar_analise({"janela_meses": "abc"})["janela_meses"], 3)
        self.assertEqual(core._normalizar_analise({"janela_meses": -5})["janela_meses"], 0)
        self.assertEqual(core._normalizar_analise({"janela_meses": 1.5})["janela_meses"], 1.5)
        self.assertEqual(core._normalizar_analise({"n_frequencia": 5})["n_frequencia"], 10)
        self.assertEqual(core._normalizar_analise({"n_frequencia": 999})["n_frequencia"], 100)


class JanelaNoRankingTests(unittest.TestCase):
    def canal(self, nome, meses_atras, subs=10_000, nvid=20, **extra):
        iso = (HOJE.date() - __import__("datetime").timedelta(days=round(meses_atras * 30.4375))).isoformat()
        return dict({"canal": nome, "canal_url": f"u/{nome}", "inscritos_num": subs, "n_videos": nvid,
                     "primeiro_video_data_publicacao": iso}, **extra)

    def rank(self, canais, janela):
        antes = core.datetime
        try:
            class _Fixo(datetime):
                @classmethod
                def now(cls, tz=None):
                    return HOJE
            core.datetime = _Fixo
            return {c["canal"]: c for c in core.rank_channels(canais, janela_meses=janela)}
        finally:
            core.datetime = antes

    def test_marca_dentro_e_fora(self):
        r = self.rank([self.canal("novo", 1), self.canal("limite", 3), self.canal("velho", 8)], janela=3)
        self.assertFalse(r["novo"]["fora_da_janela"])
        self.assertFalse(r["limite"]["fora_da_janela"])
        self.assertTrue(r["velho"]["fora_da_janela"])

    def test_janela_menor_reclassifica(self):
        r = self.rank([self.canal("c", 2)], janela=1)
        self.assertTrue(r["c"]["fora_da_janela"])

    def test_sem_janela_nao_marca_ninguem(self):
        r = self.rank([self.canal("velho", 30)], janela=0)
        self.assertFalse(r["velho"]["fora_da_janela"])

    def test_mais_recente_pontua_mais_com_o_mesmo_tamanho(self):
        r = self.rank([self.canal("a", 0.5), self.canal("b", 2.5)], janela=3)
        self.assertGreater(r["a"]["score"], r["b"]["score"])

    def test_idade_desconhecida_nunca_e_fora_nem_dentro(self):
        sem_data = {"canal": "x", "canal_url": "u/x", "inscritos_num": 500, "n_videos": 3}
        r = self.rank([sem_data, dict(self.canal("nc", 1), primeiro_video_confiavel=False)], janela=3)
        for nome in ("x", "nc"):
            self.assertTrue(r[nome]["idade_desconhecida"], nome)
            self.assertFalse(r[nome]["fora_da_janela"], nome)
            self.assertIsNone(r[nome]["meses_desde_primeiro_video"], nome)

    def test_inscritos_por_mes(self):
        r = self.rank([self.canal("c", 2, subs=12_000)], janela=3)
        self.assertAlmostEqual(r["c"]["inscritos_por_mes"], 12_000 / 2, delta=150)

    def test_resumo_de_oportunidade_ignora_canais_fora_da_janela(self):
        grupos = {"Novo": [{"canal": "n", "score": 10}],
                  "SoAntigos": [{"canal": "a", "score": 9999, "fora_da_janela": True}],
                  "Misto": [{"canal": "m", "score": 20}, {"canal": "gigante", "score": 5000, "fora_da_janela": True}]}
        out = core.build_group_summaries(grupos, "nicho")
        self.assertEqual([r["nicho"] for r in out], ["Misto", "Novo"])   # o gigante antigo não puxou o Misto
        self.assertEqual(out[0]["candidatos"], 1)
        self.assertEqual(out[0]["melhor_score"], 20)
        # o grupo só com canais antigos continua listado, no fim
        self.assertEqual(list(core.reorder_group_rankings(grupos, out, "nicho")), ["Misto", "Novo", "SoAntigos"])


class CardsDoHtmlRealTests(unittest.TestCase):
    """Roda o leitor de cards no DOM do layout novo (HTML enviado pelo usuário)."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:  # sem Chromium instalado
            raise unittest.SkipTest(f"Chromium do Playwright indisponível: {exc}")
        cls._page = cls._browser.new_page()
        cls._page.set_content(FIXTURE.read_text(encoding="utf-8"))
        cls.cards = [core._card_video_data(c) for c in cls._page.query_selector_all(core.CARDS_CANAL_SEL)]

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def test_le_todos_os_cards(self):
        self.assertEqual(len(self.cards), 10)
        self.assertTrue(all(self.cards))

    def test_primeiro_card(self):
        c = self.cards[0]
        self.assertEqual(c["video_id"], "cbloz65iVVM")
        self.assertEqual(c["url"], "https://www.youtube.com/watch?v=cbloz65iVVM")
        self.assertTrue(c["titulo"].startswith("C PADRÃO KERNIGHAN & RITCHIE"))
        self.assertEqual((c["views_num"], c["quando"], c["duracao"]), (192_000, "há 2 dias", "14:00"))

    def test_id_com_parametro_extra_e_id_iniciado_por_hifen(self):
        por_id = {c["video_id"]: c for c in self.cards}
        self.assertIn("0Qkm2H7iWmM", por_id)        # href tem "&pp=..."
        self.assertEqual(por_id["0Qkm2H7iWmM"]["url"], "https://www.youtube.com/watch?v=0Qkm2H7iWmM")
        self.assertIn("-Obi5y_rM7c", por_id)        # id começa com "-"
        self.assertEqual(por_id["-Obi5y_rM7c"]["views_num"], 3_400)     # "3,4 mil", não 3,4 milhões

    def test_views_e_datas_relativas_de_todos(self):
        esperado = [(192_000, "há 2 dias"), (434_000, "há 3 semanas"), (48_000, "há 3 semanas"), (86_000, "há 1 mês"),
                    (31_000, "há 1 mês"), (7_700, "há 2 meses"), (3_400, "há 3 meses"), (34_000, "há 4 meses"),
                    (91_000, "há 7 meses"), (45_000, "há 8 meses")]
        self.assertEqual([(c["views_num"], c["quando"]) for c in self.cards], esperado)
        self.assertTrue(all(c["data_aprox"] for c in self.cards))

    def test_ordem_das_datas_aproximadas_e_decrescente(self):
        datas = [c["data_aprox"] for c in self.cards]
        self.assertEqual(datas, sorted(datas, reverse=True))

    def test_aspas_no_titulo(self):
        c = next(c for c in self.cards if c["video_id"] == "DtgpC_L1iP0")
        self.assertIn('"OLHO de DEUS"', c["titulo"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
