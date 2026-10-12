"""UI da aba Minerar (navegadores simultâneos + recomendados automáticos da lateral) em Chromium
real, contra o servidor Flask local. As rotas /api/iniciar e /api/iniciar-recomendados são
interceptadas (sem rodar o pipeline de verdade) só para capturar o corpo do POST que o
JavaScript monta — a lógica do pipeline em si já é testada em tests/test_multi_navegador.py."""
import json
import logging
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

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


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class MinerarUiTests(unittest.TestCase):
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

    def abrir(self):
        ctx = self._browser.new_context(viewport={"width": 1300, "height": 1000})
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        self.erros = []
        page.on("pageerror", lambda e: self.erros.append(str(e)))
        page.goto(self.url)
        return page

    def interceptar(self, page, rota):
        """Substitui a rota real por uma que só devolve um job falso e guarda o corpo enviado."""
        capturado = {}
        pronto = threading.Event()

        def responder(route, request):
            capturado["body"] = json.loads(request.post_data or "{}")
            pronto.set()
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "job_id": "fake123"}))

        page.route(f"**{rota}", responder)
        page.route("**/api/logs/**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"ok": True, "logs": [], "cursor": 0, "status": "rodando"})))
        return capturado, pronto

    def habilitar_iniciar(self, page, termos=("termo um", "termo dois")):
        page.evaluate("(t) => { termosValidados = t; document.getElementById('btn-iniciar').disabled = false; }", list(termos))

    def habilitar_rec(self, page):
        page.fill("#rec-urls", "https://www.youtube.com/watch?v=aaaaaaaaaaa")
        page.dispatch_event("#rec-urls", "input")
        page.evaluate("document.getElementById('btn-rec-iniciar').disabled = false;")

    def tearDown(self):
        self.assertEqual(self.erros, [])

    # ------------------------------------------------------------------ navegadores simultâneos

    def test_padrao_e_1_navegador_e_o_select_vai_ate_5(self):
        page = self.abrir()
        self.assertEqual(page.input_value("#n_navegadores"), "1")
        valores = page.eval_on_selector_all("#n_navegadores option", "els => els.map(e => e.value)")
        self.assertEqual(valores, ["1", "2", "3", "4", "5"])

    def test_navegadores_escolhido_vai_para_o_botao_iniciar(self):
        page = self.abrir()
        cap, pronto = self.interceptar(page, "/api/iniciar")
        page.select_option("#n_navegadores", "4")
        self.habilitar_iniciar(page)
        page.click("#btn-iniciar")
        self.assertTrue(pronto.wait(3))
        self.assertEqual(cap["body"]["n_navegadores"], 4)

    def test_navegadores_escolhido_tambem_vai_para_o_botao_de_recomendacoes(self):
        page = self.abrir()
        cap, pronto = self.interceptar(page, "/api/iniciar-recomendados")
        page.select_option("#n_navegadores", "5")
        self.habilitar_rec(page)
        page.click("#btn-rec-iniciar")
        self.assertTrue(pronto.wait(3))
        self.assertEqual(cap["body"]["n_navegadores"], 5)

    def test_preferencia_de_navegadores_fica_salva_entre_recarregamentos(self):
        page = self.abrir()
        page.select_option("#n_navegadores", "3")
        page.evaluate("salvarPreferencias()")
        page.reload()
        self.assertEqual(page.input_value("#n_navegadores"), "3")

    # ------------------------------------------------------------------ recomendados automáticos

    def test_opcoes_da_lateral_comecam_escondidas_e_aparecem_ao_marcar(self):
        page = self.abrir()
        self.assertFalse(page.is_visible("#ra-opcoes"))
        page.click("#ra-ativo")
        self.assertTrue(page.is_visible("#ra-opcoes"))
        page.click("#ra-ativo")
        self.assertFalse(page.is_visible("#ra-opcoes"))

    def test_desmarcado_manda_ativo_false_mas_ainda_manda_o_objeto(self):
        page = self.abrir()
        cap, pronto = self.interceptar(page, "/api/iniciar")
        self.habilitar_iniciar(page)
        page.click("#btn-iniciar")
        self.assertTrue(pronto.wait(3))
        self.assertEqual(cap["body"]["recomendados_auto"]["ativo"], False)

    def test_marcado_manda_as_opcoes_escolhidas(self):
        page = self.abrir()
        cap, pronto = self.interceptar(page, "/api/iniciar")
        page.click("#ra-ativo")
        page.fill("#ra-itens", "9")
        page.select_option("#ra-meses", "12")
        page.select_option("#ra-ref", "mediana")
        page.select_option("#ra-fator", "0.8")
        self.habilitar_iniciar(page)
        page.click("#btn-iniciar")
        self.assertTrue(pronto.wait(3))
        ra = cap["body"]["recomendados_auto"]
        self.assertEqual(ra, {"ativo": True, "max_itens": 9, "meses_max": 12, "referencia": "mediana", "fator": 0.8})

    def test_botao_de_recomendacoes_nunca_manda_recomendados_auto(self):
        page = self.abrir()
        cap, pronto = self.interceptar(page, "/api/iniciar-recomendados")
        page.click("#ra-ativo")  # marcado na tela, mas essa opção é só da busca por termo
        self.habilitar_rec(page)
        page.click("#btn-rec-iniciar")
        self.assertTrue(pronto.wait(3))
        self.assertNotIn("recomendados_auto", cap["body"])

    def test_preferencia_da_lateral_fica_salva_entre_recarregamentos(self):
        page = self.abrir()
        page.click("#ra-ativo")
        page.fill("#ra-itens", "12")
        page.evaluate("salvarPreferencias()")
        page.reload()
        self.assertTrue(page.is_checked("#ra-ativo"))
        self.assertTrue(page.is_visible("#ra-opcoes"))
        self.assertEqual(page.input_value("#ra-itens"), "12")

    # ------------------------------------------------------------------ a rota real aceita o corpo que a tela monta

    def test_rota_iniciar_aceita_o_corpo_que_a_tela_monta(self):
        """O corpo capturado no navegador é o mesmo que a rota real aceita e repassa ao pipeline."""
        page = self.abrir()
        cap, pronto = self.interceptar(page, "/api/iniciar")
        page.select_option("#n_navegadores", "2")
        page.click("#ra-ativo")
        self.habilitar_iniciar(page)
        page.click("#btn-iniciar")
        self.assertTrue(pronto.wait(3))

        capturado_pipeline = {}
        pronto2 = threading.Event()

        def falso_pipeline(*args, **kwargs):
            capturado_pipeline.update(kwargs=kwargs)
            pronto2.set()

        with mock.patch.object(webapp, "rodar_pipeline", falso_pipeline):
            r = webapp.app.test_client().post("/api/iniciar", json=cap["body"])
            self.assertTrue(r.get_json()["ok"], r.get_json())
            self.assertTrue(pronto2.wait(3))
        self.assertEqual(capturado_pipeline["kwargs"]["n_navegadores"], 2)
        self.assertEqual(capturado_pipeline["kwargs"]["recomendados_auto"]["max_itens"], 5)  # padrão da tela


if __name__ == "__main__":
    unittest.main(verbosity=2)
