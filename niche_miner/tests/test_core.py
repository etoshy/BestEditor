import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yt_scraper as core


class FakeElement:
    def __init__(self, text="", content="", aria_label=""):
        self._text = text
        self._content = content
        self._aria_label = aria_label
    def inner_text(self):
        return self._text
    def get_attribute(self, name):
        if name == "content":
            return self._content
        if name == "aria-label":
            return self._aria_label
        return ""


class FakeLocator:
    def __init__(self, text=""):
        self.text = text
    def inner_text(self, timeout=None):
        return self.text


class FakePage:
    def __init__(self, published="2026-09-10", body=""): 
        self.published = published
        self.body = body
        self.url = ""
    def goto(self, url, **kwargs):
        self.url = url
    def wait_for_timeout(self, ms):
        pass
    def query_selector(self, sel):
        if sel == 'meta[itemprop="datePublished"]':
            return FakeElement(content=self.published) if self.published else None
        return None
    def query_selector_all(self, sel):
        return []
    def locator(self, sel):
        return FakeLocator(self.body)


class CoreTests(unittest.TestCase):
    def test_parse_count(self):
        self.assertEqual(core.parse_count("1,2 mi de inscritos"), 1_200_000)
        self.assertEqual(core.parse_count("234 mil visualizações"), 234_000)
        self.assertEqual(core.parse_count("17 views"), 17)

    def test_extract_channel_header_current_youtube_dom(self):
        class ChannelHeaderPage:
            def __init__(self):
                self.sub = FakeElement(text="841 mil inscritos", aria_label="841 mil inscritos")
                self.videos = FakeElement(text="346 vídeos")
            def query_selector_all(self, sel):
                if 'aria-label*=\"inscrit' in sel or 'aria-label*=\"subscriber' in sel:
                    return [self.sub]
                if 'role=\"text\"' in sel or 'yt-content-metadata-view-model span' in sel:
                    return [self.sub, self.videos]
                return []

        out = core._extract_channel_header_metadata(ChannelHeaderPage(), "")
        self.assertEqual(out["inscritos_text"], "841 mil inscritos")
        self.assertEqual(out["inscritos_num"], 841_000)
        self.assertEqual(out["n_videos"], 346)

    def test_extract_channel_header_fallback_text(self):
        class EmptyPage:
            def query_selector_all(self, sel):
                return []
        out = core._extract_channel_header_metadata(EmptyPage(), "@skd • 841 mil inscritos • 346 vídeos")
        self.assertEqual(out["inscritos_num"], 841_000)
        self.assertEqual(out["n_videos"], 346)

    def test_parse_duration_seconds(self):
        self.assertEqual(core.parse_duration_seconds("03:15"), 195)
        self.assertEqual(core.parse_duration_seconds("01:02:03"), 3723)
        self.assertIsNone(core.parse_duration_seconds("3 min"))

    def test_normalize_filters(self):
        cfg = core._normalizar_filtros({
            "duracao_min": "20", "duracao_max": "3",
            "data_periodo": "semana", "ordenacao": "popularidade",
        })
        self.assertEqual(cfg["duracao_min"], 3)
        self.assertEqual(cfg["duracao_max"], 20)
        self.assertEqual(cfg["data_periodo"], "semana")
        self.assertEqual(cfg["ordenacao"], "popularidade")

    def test_filter_duration_range(self):
        rows = [
            {"titulo": "a", "duracao_segundos": 120},
            {"titulo": "b", "duracao_segundos": 300},
            {"titulo": "c", "duracao_segundos": 1500},
        ]
        kept = core._filtrar_por_duracao(rows, {"duracao_min": 3, "duracao_max": 20})
        self.assertEqual([x["titulo"] for x in kept], ["b"])

    def test_all_dates_does_not_require_real_date(self):
        page = FakePage(None)
        video = {"url": "https://www.youtube.com/watch?v=abc"}
        ok, reason = core.validar_video_no_periodo(page, video, "todos")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_sponsored_detection(self):
        self.assertTrue(core.texto_indica_patrocinado("Includes paid promotion"))
        self.assertTrue(core.texto_indica_patrocinado("Conteúdo patrocinado"))
        self.assertFalse(core.texto_indica_patrocinado("Documentary about abandoned infrastructure"))

    def test_language_inference(self):
        self.assertEqual(core._infer_language("The documentary explores this abandoned channel. History and videos."), "Inglês")
        self.assertEqual(core._infer_language("Este canal mostra vídeos sobre história do Brasil. Não perca os vídeos."), "Português")
        self.assertEqual(core._infer_language("xylophone quantum zebra"), "")

    def test_date_validation_accepts_current_month(self):
        page = FakePage("2026-09-10")
        video = {"url": "https://www.youtube.com/watch?v=abc"}
        ok, reason = core.validar_video_no_mes(page, video, 2026, 9)
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(video["data_publicacao"], "2026-09-10")
        self.assertTrue(video["data_verificada"])

    def test_date_validation_rejects_old_video(self):
        page = FakePage("2026-08-31")
        video = {"url": "https://www.youtube.com/watch?v=abc"}
        ok, reason = core.validar_video_no_mes(page, video, 2026, 9)
        self.assertFalse(ok)
        self.assertIn("fora_do_periodo", reason)

    def test_date_validation_rejects_sponsored(self):
        page = FakePage("2026-09-10", body="This video includes paid promotion")
        # locator/body is used by validar_video_no_mes
        ok, reason = core.validar_video_no_mes(page, {"url": "https://www.youtube.com/watch?v=abc"}, 2026, 9)
        self.assertFalse(ok)
        self.assertEqual(reason, "patrocinado")

    def test_merge_keeps_all_associations(self):
        rows = [
            {"canal_url": "https://youtube.com/@a", "canal": "A", "score": 100, "nicho": "Webdoc", "subnicho": "Abandoned", "termo_busca": "abandoned infrastructure", "pais_canal": "United States", "idioma_canal": "Inglês"},
            {"canal_url": "https://youtube.com/@a", "canal": "A", "score": 120, "nicho": "Webdoc", "subnicho": "Forgotten Places", "termo_busca": "forgotten places documentary", "pais_canal": "United States", "idioma_canal": "Inglês"},
        ]
        merged = core.merge_channel_records(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["score"], 120)
        self.assertEqual(set(merged[0]["subnichos"]), {"Abandoned", "Forgotten Places"})
        self.assertEqual(len(merged[0]["termos_busca"]), 2)

    def test_group_rankings_by_subniche(self):
        rows = [
            {"canal_url": "a", "canal": "A", "score": 200, "subnichos": ["Abandoned"], "nichos": ["Webdoc"]},
            {"canal_url": "b", "canal": "B", "score": 100, "subnichos": ["Abandoned", "Dark History"], "nichos": ["Webdoc"]},
        ]
        groups = core.build_group_rankings(rows, "subnicho", "Sem subnicho")
        self.assertEqual([x["canal"] for x in groups["Abandoned"]], ["A", "B"])
        self.assertIn("Dark History", groups)

    def test_ranking_does_not_drop_missing_channel_data(self):
        rows = [
            {"canal_url": "a", "canal": "A", "inscritos_num": None, "n_videos": None, "primeiro_video_quando": ""},
            {"canal_url": "b", "canal": "B", "inscritos_num": 120_000, "n_videos": 12, "primeiro_video_quando": "há 1 mês"},
        ]
        ranked = core.rank_channels(rows, min_subs=50_000, max_videos=100)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["canal"], "B")
        self.assertTrue(ranked[1]["dados_incompletos"])

    def test_zero_min_subs_keeps_candidates(self):
        rows = [
            {"canal_url": "a", "canal": "A", "inscritos_num": 1200, "n_videos": 4, "primeiro_video_quando": "há 2 meses"},
            {"canal_url": "b", "canal": "B", "inscritos_num": 900, "n_videos": 8, "primeiro_video_quando": "há 3 meses"},
        ]
        ranked = core.rank_channels(rows, min_subs=0, max_videos=100)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["canal"], "A")

    def test_video_count_and_age_are_preferences_not_hard_filters(self):
        rows = [
            {"canal_url": "a", "canal": "A", "inscritos_num": 100_000, "n_videos": 250, "primeiro_video_quando": "há 36 meses"},
            {"canal_url": "b", "canal": "B", "inscritos_num": 50_000, "n_videos": 5, "primeiro_video_quando": "há 2 meses"},
        ]
        ranked = core.rank_channels(rows, min_subs=0, max_videos=100)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["canal"], "B")
        self.assertIn("A", [x["canal"] for x in ranked])

    def test_confirmed_min_subs_filter_still_works(self):
        rows = [
            {"canal_url": "a", "canal": "A", "inscritos_num": 10_000, "n_videos": 4, "primeiro_video_quando": "há 2 meses"},
            {"canal_url": "b", "canal": "B", "inscritos_num": 60_000, "n_videos": 8, "primeiro_video_quando": "há 3 meses"},
        ]
        ranked = core.rank_channels(rows, min_subs=50_000, max_videos=100)
        self.assertEqual([x["canal"] for x in ranked], ["B"])

    def test_ranking_rule_prefers_subs_and_fewer_videos_and_recency(self):
        rows = [
            {"canal_url": "a", "canal": "A", "inscritos_num": 200_000, "n_videos": 10, "primeiro_video_quando": "há 1 mês"},
            {"canal_url": "b", "canal": "B", "inscritos_num": 200_000, "n_videos": 80, "primeiro_video_quando": "há 18 meses"},
        ]
        ranked = core.rank_channels(rows, min_subs=0, max_videos=100)
        self.assertEqual(ranked[0]["canal"], "A")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])



class OpportunityRankingTests(unittest.TestCase):
    def test_group_summary_ranks_by_opportunity(self):
        groups = {
            "Nicho A": [
                {"canal": "A1", "score": 1000},
                {"canal": "A2", "score": 900},
                {"canal": "A3", "score": 800},
            ],
            "Nicho B": [
                {"canal": "B1", "score": 1300},
                {"canal": "B2", "score": 100},
                {"canal": "B3", "score": 80},
            ],
        }
        out = core.build_group_summaries(groups, "nicho")
        self.assertEqual(out[0]["nicho"], "Nicho A")
        self.assertGreater(out[0]["score_oportunidade"], out[1]["score_oportunidade"])
        self.assertEqual([x["canal"] for x in out[0]["top_canais"]], ["A1", "A2", "A3"])

    def test_reorder_groups_follows_opportunity_summary(self):
        groups = {"B": [1], "A": [2], "C": [3]}
        summaries = [
            {"nicho": "C", "rank": 1},
            {"nicho": "A", "rank": 2},
            {"nicho": "B", "rank": 3},
        ]
        ordered = core.reorder_group_rankings(groups, summaries, "nicho")
        self.assertEqual(list(ordered.keys()), ["C", "A", "B"])

    def test_summary_has_required_opportunity_fields(self):
        out = core.build_group_summaries({"Webdoc": [{"canal": "A", "score": 50}]}, "nicho")
        row = out[0]
        for key in ["rank", "score_oportunidade", "melhor_score", "media_top3_score", "top_canais"]:
            self.assertIn(key, row)

class WatchInfoTests(unittest.TestCase):
    def test_parse_exact_watch_date_and_views_pt(self):
        views_num, published, views_text, date_text = core._extrair_views_data_do_texto_info(
            "8.443 visualizações • 26 de ago. de 2026"
        )
        self.assertEqual(views_num, 8443)
        self.assertEqual(published.isoformat(), "2026-08-26")
        self.assertEqual(views_text, "8.443 visualizações")
        self.assertEqual(date_text, "26 de ago. de 2026")

    def test_parse_exact_watch_date_and_views_en(self):
        views_num, published, views_text, date_text = core._extrair_views_data_do_texto_info(
            "8,4K views • Aug 26, 2026"
        )
        self.assertEqual(views_num, 8400)
        self.assertEqual(published.isoformat(), "2026-08-26")
        self.assertEqual(views_text, "8,4K views")
        self.assertEqual(date_text, "Aug 26, 2026")

    def test_months_since_exact_date(self):
        value = core._meses_desde_data("2026-08-26", agora=core.datetime(2026, 9, 18))
        self.assertAlmostEqual(value, 23 / 30.4375, places=4)

    def test_watch_info_reads_tooltip_before_relative_info(self):
        class WatchPage:
            def __init__(self):
                self.clicked = False
            def locator(self, sel):
                class L:
                    def __init__(self, outer): self.outer = outer
                    def count(self): return 0
                    def is_visible(self): return False
                    def click(self, timeout=0): self.outer.clicked = True
                return L(self)
            def query_selector_all(self, sel):
                if '#tooltip' in sel:
                    return [FakeElement(text="8.443 visualizações • 26 de ago. de 2026")]
                if '#info' in sel:
                    return [FakeElement(text="8,4 mil visualizações há 3 semanas")]
                return []
            def evaluate(self, script):
                return False
            def query_selector(self, sel):
                return None
        out = core.extrair_watch_info(WatchPage(), "8,4 mil visualizações", "há 3 semanas")
        self.assertEqual(out["views_num"], 8443)
        self.assertEqual(out["data_publicacao"], "2026-08-26")
        self.assertEqual(out["data_texto"], "26 de ago. de 2026")



if __name__ == "__main__":
    unittest.main(verbosity=2)
