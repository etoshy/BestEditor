import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
APP = (ROOT / "app.py").read_text(encoding="utf-8")


class ContractTests(unittest.TestCase):
    def test_frontend_sends_niche_and_subnichos(self):
        self.assertIn('nicho,', JS)
        self.assertIn('subnichos: subnichosValidados', JS)
        self.assertIn('termos: termosValidados', JS)

    def test_frontend_has_all_ranking_tabs(self):
        for key in ["geral", "nichos", "subnichos", "paises", "idiomas", "verificados"]:
            self.assertIn(f'data-result-tab="{key}"', JS)

    def test_backend_exports_all_rankings(self):
        for key in ["ranking_geral", "rankings_nichos", "rankings_subnichos", "rankings_paises", "rankings_idiomas", "verificados"]:
            self.assertIn(f'"{key}"', APP)

    def test_default_min_subs_is_zero(self):
        self.assertIn('min_subs = int(data.get("min_subs", 0))', APP)
        self.assertIn('id="min_subs" value="0"', (ROOT / "templates" / "index.html").read_text(encoding="utf-8"))

    def test_ranking_marks_incomplete_data_instead_of_silent_drop(self):
        scraper = (ROOT / "yt_scraper.py").read_text(encoding="utf-8")
        self.assertIn('dados_incompletos', scraper)
        self.assertIn('penalização conservadora', scraper)

    def test_term_failure_isolated(self):
        self.assertIn("Falha isolada no termo", APP)
        self.assertIn("continue", APP)

    def test_frontend_exposes_filters_and_mute_control(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        for key in ["duracao_min", "duracao_max", "data_periodo", "ordenacao", "mutar_audio"]:
            self.assertIn(f'id="{key}"', html)
        for key in ["duracao_min", "duracao_max", "data_periodo", "ordenacao", "mutar_audio"]:
            self.assertIn(key, JS)

    def test_backend_receives_filter_config_and_mute(self):
        self.assertIn('data.get("duracao_min", 3)', APP)
        self.assertIn('data.get("duracao_max", 20)', APP)
        self.assertIn('data.get("data_periodo", "mes")', APP)
        self.assertIn('data.get("ordenacao", "popularidade")', APP)
        self.assertIn('data.get("mutar_audio", True)', APP)
        self.assertIn('--mute-audio', APP)

    def test_scraper_supports_custom_filter_validation(self):
        scraper = (ROOT / "yt_scraper.py").read_text(encoding="utf-8")
        self.assertIn("def validar_video_no_periodo", scraper)
        self.assertIn("def _filtrar_por_duracao", scraper)
        self.assertIn("Duração personalizada", scraper)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class OpportunityContractTests(unittest.TestCase):
    def test_backend_has_niche_opportunity_summary(self):
        scraper = (ROOT / "yt_scraper.py").read_text(encoding="utf-8")
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("score_oportunidade", scraper)
        self.assertIn("reorder_group_rankings", scraper)
        self.assertIn("resumo_nichos", app)

    def test_frontend_renders_opportunity_summary(self):
        js = JS
        self.assertIn("resumo_nichos", js)
        self.assertIn("score_oportunidade", js)


class MultiNavegadorERecomendadosAutoContractTests(unittest.TestCase):
    """Navegadores simultâneos e a coleta automática de recomendados: ids do HTML existem no JS
    (e vice-versa), e o backend lê exatamente o que o frontend manda."""

    def setUp(self):
        self.html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    def test_ids_do_html_existem_e_sao_usados_no_js(self):
        for campo in ("n_navegadores", "ra-ativo", "ra-itens", "ra-meses", "ra-ref", "ra-fator", "ra-opcoes"):
            self.assertIn(f'id="{campo}"', self.html, campo)
            self.assertIn(campo, JS, campo)

    def test_navegadores_vai_de_1_a_5_e_o_padrao_e_1(self):
        self.assertRegex(self.html, r'id="n_navegadores">\s*<option value="1" selected>')
        for v in ("1", "2", "3", "4", "5"):
            self.assertIn(f'<option value="{v}"', self.html, v)

    def test_configpasso3_manda_n_navegadores_e_e_usado_pelos_dois_botoes(self):
        self.assertIn("n_navegadores: parseInt", JS)
        self.assertIn("...cfg,", JS)  # o objeto de configPasso3() é espalhado nos dois corpos de POST

    def test_recomendados_auto_so_vai_no_botao_da_busca_por_termo_nao_no_de_recomendacoes(self):
        antes_iniciar = JS[:JS.index('el("btn-iniciar").addEventListener')]
        bloco_iniciar = JS[JS.index('el("btn-iniciar").addEventListener'):JS.index('el("ra-ativo").addEventListener')]
        bloco_rec = JS[JS.index('el("btn-rec-iniciar").addEventListener'):]
        self.assertIn("recomendados_auto: configRecomendadosAuto()", bloco_iniciar)
        self.assertNotIn("recomendados_auto", bloco_rec[:bloco_rec.index("});")])

    def test_checkbox_mostra_e_esconde_as_opcoes(self):
        self.assertIn('el("ra-opcoes").style.display = el("ra-ativo").checked ? "" : "none";', JS)
        self.assertIn('style="display:none"', self.html)  # ra-opcoes começa escondido

    def test_backend_le_n_navegadores_e_limita_de_1_a_5_nas_duas_rotas(self):
        self.assertEqual(APP.count('min(5, int(data.get("n_navegadores", 1)))'), 2)

    def test_backend_so_liga_recomendados_auto_quando_ativo_e_normaliza_com_o_modulo_certo(self):
        self.assertIn('recomendados.normalizar_cfg(rec_auto_in) if rec_auto_in.get("ativo") else None', APP)

    def test_rodar_pipeline_aceita_os_dois_parametros_novos_com_valores_padrao_que_preservam_o_comportamento_antigo(self):
        assinatura = APP[APP.index("def rodar_pipeline"):APP.index("):", APP.index("def rodar_pipeline"))]
        self.assertIn("recomendados_auto=None", assinatura)
        self.assertIn("n_navegadores=1", assinatura)

