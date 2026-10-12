"""Interface das recomendações no navegador real (servidor Flask local, rotas de coleta simuladas)."""
import json
import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as webapp
import biblioteca as bib

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False

URL_A = "https://www.youtube.com/watch?v=aaaaaaaaaa1"
URL_B = "https://www.youtube.com/watch?v=bbbbbbbbbb2"
TITULO_HOSTIL = '<img src=x onerror="window.__xss=1"> Estão Me Perseguindo'


def canal(nome, score, rank, **extra):
    c = {"canal": nome, "canal_url": f"https://youtube.com/@{nome}", "inscritos_num": 1000, "inscritos_text": "1 mil inscritos",
         "n_videos": 10, "views_totais": 50000, "score": score, "rank_geral": rank, "rank_grupo": rank, "termo_busca": "Recomendados de: A",
         "fora_da_janela": False, "video_exemplo": f"https://www.youtube.com/watch?v={nome[:1] * 11}"}
    c.update(extra)
    return c


def resultado(canais, **extra):
    r = {"nicho": "Anime", "ranking_geral": canais, "ranking_nao_verificados": canais, "verificados": [],
         "rankings_nichos": {"Anime": canais}, "rankings_subnichos": {"Sem subnicho": canais}, "rankings_paises": {}, "rankings_idiomas": {},
         "resumo_nichos": [], "resumo_subnichos": [], "resumo_paises": [], "resumo_idiomas": [], "falhas_termos": [], "filtros": {},
         "analise": {"janela_meses": 3}, "resumo_janela": {}, "busca_id": None}
    r.update(extra)
    return r


RELATORIO = {
    "cfg": {"referencia": "media", "fator": 1, "meses_max": 3, "escopo": "por_video"},
    "grupos": [{"origem_titulo": "Vídeo de origem A", "coletados": 15, "elegiveis": 4, "valor": 23687, "limiar": 23687, "aprovados": 1, "pouco_confiavel": False},
               {"origem_titulo": "Vídeo B", "coletados": 15, "elegiveis": 0, "valor": None, "limiar": None, "aprovados": 0, "pouco_confiavel": False},
               {"origem_titulo": "Vídeo C", "coletados": 10, "elegiveis": 2, "valor": 300, "limiar": 300, "aprovados": 1, "pouco_confiavel": True}],
    "itens": [
        {"video_id": "a", "url": "https://www.youtube.com/watch?v=a", "titulo": "Vídeo do akS", "canal": "akS", "canal_verificado": False, "views_num": 69,
         "quando": "há 5 dias", "aprovado": False, "motivo": "abaixo_da_media", "razao_media": 0.0, "analisado": False},
        {"video_id": "b", "url": "https://www.youtube.com/watch?v=b", "titulo": TITULO_HOSTIL, "canal": "Mistere", "canal_verificado": False,
         "views_num": 90000, "quando": "há 3 dias", "aprovado": True, "motivo": "ok", "razao_media": 3.8, "analisado": True},
        {"video_id": "c", "url": "https://www.youtube.com/watch?v=c", "titulo": "Vídeo do ANCAPSU", "canal": "ANCAPSU", "canal_verificado": True, "views_num": 310000,
         "quando": "há 14 horas", "aprovado": False, "motivo": "verificado", "razao_media": None, "analisado": False},
        {"video_id": "d", "url": "https://www.youtube.com/watch?v=d", "titulo": "Patrocinado", "canal": "Outro", "canal_verificado": False, "views_num": 50000,
         "quando": "há 2 dias", "aprovado": False, "motivo": "validacao:patrocinado", "razao_media": 2.1, "analisado": False},
    ],
    "canais_analisados": 1,
}


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class InterfaceRecomendacoesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(cls._tmp.name, "b.db")
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
        os.environ.pop("NICHE_MINER_DB", None)
        cls._tmp.cleanup()

    def abrir(self):
        ctx = self._browser.new_context(viewport={"width": 1600, "height": 900})
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=self.url.rstrip("/"))
        self.addCleanup(ctx.close)
        page = ctx.new_page()
        self.erros, self.dialogos = [], []
        page.on("pageerror", lambda e: self.erros.append(str(e)))
        page.on("dialog", lambda d: (self.dialogos.append(d.message), d.accept()))
        page.goto(self.url)
        return page

    def tearDown(self):
        self.assertEqual(getattr(self, "erros", []), [])

    def simular_servidor(self, page, resultado_final=None, erro_iniciar=None):
        """Substitui só as rotas de coleta; guarda o corpo enviado."""
        pedidos = {}

        def iniciar(route):
            pedidos["url"] = route.request.url.rsplit("/api/", 1)[-1]
            pedidos["corpo"] = json.loads(route.request.post_data)
            corpo = {"ok": False, "erro": erro_iniciar} if erro_iniciar else {"ok": True, "job_id": "job1"}
            route.fulfill(status=400 if erro_iniciar else 200, content_type="application/json", body=json.dumps(corpo))

        chamadas = {"n": 0}

        def logs(route):
            chamadas["n"] += 1
            status = "concluido" if (resultado_final and chamadas["n"] > 1) else "rodando"
            route.fulfill(content_type="application/json", body=json.dumps({"ok": True, "cursor": 1, "logs": ["linha do log"], "status": status}))

        page.route("**/api/iniciar-recomendados", iniciar)
        page.route("**/api/iniciar", iniciar)
        page.route("**/api/logs/**", logs)
        page.route("**/api/resultado/**", lambda r: r.fulfill(content_type="application/json", body=json.dumps({"ok": True, "resultado": resultado_final or {}})))
        return pedidos

    # ------------------------------------------------------------------ botão e campos
    def test_botao_so_habilita_com_link_e_padroes_batem_com_a_triagem_documentada(self):
        page = self.abrir()
        self.assertTrue(page.is_disabled("#btn-rec-iniciar"))
        page.fill("#rec-urls", URL_A)
        self.assertFalse(page.is_disabled("#btn-rec-iniciar"))
        page.fill("#rec-urls", "  \n ")
        self.assertTrue(page.is_disabled("#btn-rec-iniciar"))
        self.assertEqual([page.input_value(i) for i in ("#rec-itens", "#rec-meses", "#rec-ref", "#rec-fator", "#rec-escopo")],
                         ["15", "3", "media", "1", "por_video"])

    def test_preferencias_da_triagem_sao_lembradas(self):
        page = self.abrir()
        page.select_option("#rec-ref", "mediana")
        page.select_option("#rec-meses", "6")
        page.fill("#rec-itens", "20")
        page.select_option("#rec-escopo", "global")
        page.reload()
        self.assertEqual([page.input_value(i) for i in ("#rec-ref", "#rec-meses", "#rec-itens", "#rec-escopo")], ["mediana", "6", "20", "global"])

    # ------------------------------------------------------------------ iniciar
    def test_envia_urls_triagem_e_parametros_do_passo_3(self):
        page = self.abrir()
        pedidos = self.simular_servidor(page)
        page.fill("#nicho", "Anime")
        page.fill("#rec-urls", f"{URL_A}\n\n{URL_B}\n")
        page.select_option("#rec-ref", "mediana")
        page.select_option("#rec-fator", "0.8")
        page.select_option("#rec-meses", "6")
        page.select_option("#rec-escopo", "global")
        page.fill("#rec-itens", "20")
        page.fill("#min_subs", "1000")
        page.click("#btn-rec-iniciar")
        page.wait_for_function("document.getElementById('status-pill').textContent === 'rodando'")
        c = pedidos["corpo"]
        self.assertEqual(pedidos["url"], "iniciar-recomendados")
        self.assertEqual(c["urls"], [URL_A, URL_B])
        self.assertEqual((c["referencia"], c["fator"], c["meses_max"], c["escopo"], c["max_itens"]), ("mediana", 0.8, 6, "global", 20))
        self.assertEqual((c["duracao_min"], c["duracao_max"], c["min_subs"], c["janela_meses"], c["nicho"]), (3, 20, 1000, 3, "Anime"))
        self.assertIs(c["descartar_fora_janela"], True)
        self.assertTrue(page.is_disabled("#btn-rec-iniciar") and page.is_disabled("#btn-iniciar"))   # não dispara duas coletas

    def test_duracao_invalida_avisa_e_nao_envia(self):
        page = self.abrir()
        pedidos = self.simular_servidor(page)
        page.fill("#duracao_min", "30")
        page.fill("#duracao_max", "10")
        page.fill("#rec-urls", URL_A)
        page.click("#btn-rec-iniciar")
        page.wait_for_timeout(300)
        self.assertEqual(pedidos, {})
        self.assertTrue(any("duração" in d for d in self.dialogos))

    def test_erro_do_servidor_mostra_a_mensagem_e_libera_o_botao(self):
        page = self.abrir()
        self.simular_servidor(page, erro_iniciar="Já existe uma coleta em andamento. Aguarde ela terminar.")
        page.fill("#rec-urls", URL_A)
        page.click("#btn-rec-iniciar")
        page.wait_for_function("document.getElementById('status-pill').textContent === 'erro'")
        self.assertEqual(self.dialogos, ["Já existe uma coleta em andamento. Aguarde ela terminar."])
        self.assertFalse(page.is_disabled("#btn-rec-iniciar"))

    def test_ao_concluir_mostra_o_resultado_e_libera_os_botoes_certos(self):
        page = self.abrir()
        final = resultado([canal("mistere", 90, 1)], recomendados=RELATORIO)
        self.simular_servidor(page, resultado_final=final)
        page.fill("#rec-urls", URL_A)
        page.click("#btn-rec-iniciar")
        page.wait_for_selector(".rec-report", timeout=8000)
        self.assertFalse(page.is_disabled("#btn-rec-iniciar"))     # há link
        self.assertTrue(page.is_disabled("#btn-iniciar"))          # não há termos validados: continua bloqueado
        self.assertIn("linha do log", page.inner_text("#console"))

    def test_botao_da_busca_por_termo_continua_enviando_o_mesmo_corpo(self):
        page = self.abrir()
        pedidos = self.simular_servidor(page)
        page.evaluate("() => { termosValidados = ['termo um']; subnichosValidados = [{nome: 'S', termos: ['termo um']}]; el('btn-iniciar').disabled = false; }")
        page.fill("#nicho", "Tema")
        page.click("#btn-iniciar")
        page.wait_for_function("document.getElementById('status-pill').textContent === 'rodando'")
        c = pedidos["corpo"]
        self.assertEqual(pedidos["url"], "iniciar")
        self.assertEqual((c["termos"], c["nicho"], c["data_periodo"], c["ordenacao"], c["trends"]), (["termo um"], "Tema", "mes", "popularidade", False))
        self.assertEqual((c["max_videos"], c["duracao_min"], c["duracao_max"], c["janela_meses"]), (100, 3, 20, 3))
        self.assertNotIn("urls", c)

    # ------------------------------------------------------------------ exemplos
    def test_usar_exemplos_do_ultimo_resultado_sem_repetir_e_sem_canal_fora_da_janela(self):
        page = self.abrir()
        page.click("#btn-rec-exemplos")
        self.assertTrue(any("Rode uma mineração" in d for d in self.dialogos))
        canais = [canal(n, 50 - i, i + 1) for i, n in enumerate(["alfa", "bravo", "carlos", "delta", "eco", "fox"])]
        canais[1]["fora_da_janela"] = True
        page.evaluate("(r) => renderResultado(r)", resultado(canais))
        page.click("#btn-rec-exemplos")
        linhas = page.input_value("#rec-urls").splitlines()
        self.assertEqual(linhas, [f"https://www.youtube.com/watch?v={n[0] * 11}" for n in ("alfa", "carlos", "delta", "eco", "fox")])
        page.click("#btn-rec-exemplos")     # segunda vez não duplica
        self.assertEqual(page.input_value("#rec-urls").splitlines(), linhas)
        self.assertFalse(page.is_disabled("#btn-rec-iniciar"))

    # ------------------------------------------------------------------ relatório
    def test_relatorio_mostra_referencia_corte_e_decisao_de_cada_video(self):
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado([canal("mistere", 90, 1)], recomendados=RELATORIO))
        texto = page.inner_text(".rec-report")
        for trecho in ["Vídeo de origem A", "4 elegíveis de 15", "média 23.687 views", "corte 23.687", "1 aprovado",
                       "nenhum recomendado elegível", "poucos elegíveis: referência frágil", "1 canal(is) analisado(s)", "até 3 mês(es)"]:
            self.assertIn(trecho, texto)
        page.click(".rec-report summary")
        linhas = page.locator(".rec-tabela tbody tr").all_inner_texts()
        self.assertEqual(len(linhas), 4)
        self.assertIn("Mistere", linhas[0])           # analisado vem primeiro
        self.assertIn("canal analisado", linhas[0])
        self.assertIn("3,8×", linhas[0])
        self.assertTrue(any("akS" in l and "<0,01×" in l for l in linhas))          # 69 views vs. média de 23.687
        self.assertTrue(any("ANCAPSU" in l and "canal verificado" in l for l in linhas))
        self.assertTrue(any("descartado ao abrir o vídeo (patrocinado)" in l for l in linhas))
        self.assertTrue(any("abaixo do corte de views" in l for l in linhas))

    def test_titulo_com_html_nao_e_executado(self):
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado([canal("mistere", 90, 1)], recomendados=RELATORIO))
        page.click(".rec-report summary")
        self.assertIsNone(page.evaluate("window.__xss || null"))
        self.assertEqual(page.locator(".rec-tabela img").count(), 0)
        self.assertIn("<img src=x", page.inner_text(".rec-tabela"))

    def test_sem_canais_o_relatorio_aparece_para_explicar_o_motivo(self):
        page = self.abrir()
        rel = {**RELATORIO, "itens": [RELATORIO["itens"][0]], "canais_analisados": 0}
        page.evaluate("(r) => renderResultado(r)", resultado([], recomendados=rel))
        self.assertIn("Triagem das recomendações", page.inner_text("#results-area"))
        self.assertIn("nenhum canal passou", page.inner_text("#results-area"))

    def test_busca_normal_nao_mostra_relatorio(self):
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado([canal("mistere", 90, 1)]))
        self.assertEqual(page.locator(".rec-report").count(), 0)
        self.assertEqual(page.locator(".prompt-canais").count(), 0)      # sem busca salva não há o que enviar ao prompt

    # ------------------------------------------------------------------ prompt
    def test_gerar_prompt_dos_canais_usa_a_busca_salva_e_sobrevive_a_novo_desenho(self):
        busca_id = bib.salvar_busca("Anime", [URL_A], [], {}, {}, [canal("mistere", 90, 1, video_exemplo=URL_A)],
                                    [{"video_id": "v1", "titulo": "Estão Me Perseguindo...", "url": URL_A, "canal": "mistere", "canal_url": "https://youtube.com/@mistere",
                                      "canal_verificado": False, "views_num": 90000, "views_text": "90 mil", "data_publicacao": "2026-09-18",
                                      "termo_busca": "Recomendados de: A", "subnicho": "Sem subnicho", "nicho": "Anime"}])
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado([canal("mistere", 90, 1)], busca_id=busca_id))
        self.assertTrue(page.is_hidden("#prompt-canais-wrap"))
        page.click("#btn-prompt-canais")
        page.wait_for_selector("#prompt-canais-wrap", state="visible")
        prompt = page.inner_text("#prompt-canais-text")
        for trecho in ['"mistere"', "Estão Me Perseguindo...", '{"subnichos"', "termos de busca em inglês"]:
            self.assertIn(trecho, prompt)
        page.evaluate("(r) => renderResultado(r)", resultado([canal("mistere", 90, 1)], busca_id=busca_id))   # ex.: alternar filtro da janela
        self.assertEqual(page.inner_text("#prompt-canais-text"), prompt)
        page.click("#btn-copiar-prompt-canais")
        page.wait_for_function("document.getElementById('btn-copiar-prompt-canais').textContent === 'Copiado!'")   # a gravação no clipboard é assíncrona
        self.assertEqual(page.evaluate("navigator.clipboard.readText()"), prompt)      # o texto do prompt foi mesmo copiado

    def test_busca_inexistente_mostra_o_erro_do_servidor(self):
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado([canal("mistere", 90, 1)], busca_id=987654))
        page.click("#btn-prompt-canais")
        page.wait_for_timeout(500)
        self.assertEqual(self.dialogos, ["Busca não encontrada na biblioteca."])
        self.assertTrue(page.is_hidden("#prompt-canais-wrap"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
