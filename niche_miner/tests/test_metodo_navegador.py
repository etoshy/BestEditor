"""Aba Método no navegador real (servidor Flask local + banco temporário por teste)."""
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
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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

TITULO_HOSTIL = '<img src=x onerror="window.__xss=1"> Vídeo hostil'


def dia(dias_atras):
    return (date.today() - timedelta(days=dias_atras)).isoformat()


def vid(dias_atras, views, titulo=None):
    return {"video_id": f"v{dias_atras}", "titulo": titulo or f"Vídeo de {dias_atras} dias atrás", "url": f"https://youtu.be/v{dias_atras}",
            "views_num": views, "data": dia(dias_atras)}


# Os 10 mais recentes: 9000 1000 1200 800 1100 900 1000 700 1300 1000 -> mediana 1000, média 1800. Os 2 virais antigos ficam fora.
DIAS_E_VIEWS = [(3, 9000), (11, 1000), (18, 1200), (24, 800), (32, 1100), (40, 900), (47, 1000), (53, 700), (61, 1300), (68, 1000)]


def amostra(titulo_do_recente=None):
    v = [vid(d, w) for d, w in DIAS_E_VIEWS]
    if titulo_do_recente:
        v[0]["titulo"] = titulo_do_recente
    return v + [vid(263, 500000), vid(232, 400000)]      # fora de ordem de propósito abaixo


def canal(nome, inscritos, com_amostra=True, titulo_do_recente=None):
    c = {"canal": nome, "canal_url": f"https://youtube.com/@{nome}", "inscritos_num": inscritos, "n_videos": 12, "videos_ultimos_30d": 3,
         "data_criacao_canal": dia(160), "score": 10, "rank_geral": 1, "fora_da_janela": False}
    c["amostra_videos"] = list(reversed(amostra(titulo_do_recente))) if com_amostra else []
    return c


def resultado(canais):
    return {"nicho": "Astronomia", "ranking_geral": canais, "ranking_nao_verificados": canais, "verificados": [],
            "rankings_nichos": {"Astronomia": canais}, "rankings_subnichos": {"Sem subnicho": canais}, "rankings_paises": {}, "rankings_idiomas": {},
            "resumo_nichos": [], "resumo_subnichos": [], "resumo_paises": [], "resumo_idiomas": [], "falhas_termos": [], "filtros": {},
            "analise": {"janela_meses": 3}, "resumo_janela": {}, "busca_id": None}


CANAIS = [canal("Alfa", 500), canal("Bravo", 250), canal("Charlie", 100000), canal("Delta", 800, com_amostra=False)]


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class AbaMetodoTests(unittest.TestCase):
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
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")
        self.addCleanup(os.environ.pop, "NICHE_MINER_DB", None)

    def tearDown(self):
        self.assertEqual(getattr(self, "erros", []), [])

    def abrir(self, contexto=None):
        ctx = contexto or self._browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        if contexto is None:
            self.addCleanup(ctx.close)
        page = ctx.new_page()
        self.erros, self.dialogos = [], []
        page.on("pageerror", lambda e: self.erros.append(str(e)))
        page.on("dialog", lambda d: (self.dialogos.append(d.message), d.accept()))
        page.goto(self.url)
        return page

    def abrir_aba(self, page=None):
        page = page or self.abrir()
        page.click('.topnav-btn[data-view="metodo"]')
        page.wait_for_selector("#view-metodo", state="visible")
        return page

    def com_resultado(self, canais=None):
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado(CANAIS if canais is None else canais))
        self.abrir_aba(page)
        page.wait_for_selector("#mp-tabela tbody tr")
        return page

    @staticmethod
    def nomes(page):
        return page.eval_on_selector_all("#mp-tabela tbody tr", "rs => rs.map(r => r.cells[0].innerText.trim())")

    @staticmethod
    def linha(page, nome):
        return page.evaluate("""(n) => { const r = [...document.querySelectorAll('#mp-tabela tbody tr')].find(x => x.cells[0].innerText.trim() === n);
            return r ? [...r.cells].map(c => c.innerText.replace(/\\s+/g, ' ').trim()) : null; }""", nome)

    # ------------------------------------------------------------------ navegação e conteúdo
    def test_botao_abre_a_aba_esconde_as_outras_e_a_barra_lateral(self):
        page = self.abrir()
        self.assertTrue(page.is_visible("#view-minerar"))
        self.assertFalse(page.is_visible("#view-metodo"))
        self.abrir_aba(page)
        self.assertFalse(page.is_visible("#view-minerar"))
        self.assertFalse(page.is_visible(".rail"))
        self.assertIn("Método Dark", page.inner_text("#view-metodo .main-title"))
        page.click('.topnav-btn[data-view="minerar"]')
        self.assertTrue(page.is_visible(".rail"))
        self.assertFalse(page.is_visible("#view-metodo"))

    def test_conteudo_traz_as_secoes_as_formulas_e_as_ressalvas(self):
        page = self.abrir_aba()
        texto = page.inner_text("#view-metodo")
        for esperado in ("O que ele explica", "Como seguir", "Ferramentas", "Limites e cuidados", "mediana", "tração", "fator outlier",
                         "saturação", "Etapa 6", "não é problema de prompt", "5 centés"):
            self.assertIn(esperado.lower(), texto.lower(), esperado)
        # o app diverge do método em um ponto e a aba diz isso
        self.assertIn("diverge", texto)

    def test_todas_as_minutagens_tem_formato_valido_e_cabem_no_video(self):
        page = self.abrir_aba()
        minutagens = page.eval_on_selector_all("#view-metodo .mt-min", "ns => ns.map(n => n.textContent.trim())")
        self.assertGreater(len(minutagens), 40)
        for m in minutagens:
            self.assertRegex(m, r"^\d{1,2}(:\d{2}){1,2}$", m)
            partes = [int(p) for p in m.split(":")]
            segundos = partes[0] * 60 + partes[1] if len(partes) == 2 else partes[0] * 3600 + partes[1] * 60 + partes[2]
            self.assertLessEqual(segundos, 70 * 60, f"{m} passa da duração do vídeo (1h10)")

    # ------------------------------------------------------------------ checklist
    def test_checklist_conta_persiste_ao_recarregar_e_limpa(self):
        page = self.abrir_aba()
        total = page.locator(".mt-check").count()
        self.assertEqual(total, 21)
        self.assertEqual(page.inner_text("#mt-progresso"), f"0 de {total}")
        page.check('.mt-check[data-chave="1-tracao"]')
        page.check('.mt-check[data-chave="4-contagem"]')
        self.assertEqual(page.inner_text("#mt-progresso"), f"2 de {total}")
        page.reload()
        self.abrir_aba(page)
        self.assertTrue(page.is_checked('.mt-check[data-chave="1-tracao"]'))
        self.assertFalse(page.is_checked('.mt-check[data-chave="1-planilha"]'))
        self.assertEqual(page.inner_text("#mt-progresso"), f"2 de {total}")
        page.uncheck('.mt-check[data-chave="1-tracao"]')
        page.reload()
        self.abrir_aba(page)
        self.assertEqual(page.inner_text("#mt-progresso"), f"1 de {total}")
        page.click("#mt-limpar")
        self.assertEqual(self.dialogos[-1], "Limpar todas as marcações do checklist?")
        self.assertEqual(page.inner_text("#mt-progresso"), f"0 de {total}")
        page.reload()
        self.abrir_aba(page)
        self.assertEqual(page.inner_text("#mt-progresso"), f"0 de {total}")

    def test_chaves_do_checklist_sao_unicas(self):
        page = self.abrir_aba()
        chaves = page.eval_on_selector_all(".mt-check", "ns => ns.map(n => n.dataset.chave)")
        self.assertEqual(len(chaves), len(set(chaves)))

    # ------------------------------------------------------------------ semáforo
    def test_semaforo_de_saturacao(self):
        page = self.abrir_aba()
        self.assertEqual(page.inner_text("#ms-saida").strip(), "")
        for n, rotulo in (("3", "campo aberto"), ("10", "saturando"), ("25", "zona sem regra dele"), ("40", "abandone")):
            page.fill("#ms-n", n)
            self.assertIn(rotulo, page.inner_text("#ms-saida"), n)
        page.fill("#ms-n", "")
        self.assertEqual(page.inner_text("#ms-saida").strip(), "")

    # ------------------------------------------------------------------ calculadora
    def test_calculadora_com_o_exemplo_da_media_inflada(self):
        page = self.abrir_aba()
        page.fill("#mc-views", "200 mil\n900\n800\n700\n1000")
        page.fill("#mc-inscritos", "10 mil")
        page.fill("#mc-video", "147 mil")
        saida = page.inner_text("#mc-saida")
        self.assertIn("Mediana de 5 vídeo(s): 900", saida)
        self.assertIn("média: 40.680", saida)
        self.assertIn("puxam a média", saida)
        self.assertIn("a mediana é frágil", saida)                    # menos de 10 vídeos
        self.assertIn("0,09", saida)                                  # tração 900 / 10.000
        self.assertIn("intermediário", saida)
        self.assertIn("163,3×", saida)                                # 147.000 / 900
        self.assertIn("acima do seu mínimo", saida)

    def test_calculadora_respeita_os_limites_ajustados_e_a_data_de_criacao(self):
        page = self.abrir_aba()
        page.fill("#mc-views", "5000\n5000\n5000")
        page.fill("#mc-inscritos", "1000")                            # tração 5
        self.assertIn("algoritmo entregando", page.inner_text("#mc-saida"))
        page.fill("#mp-forte", "8")
        self.assertIn("intermediário", page.inner_text("#mc-saida"))
        page.fill("#mc-criado", dia(160))
        self.assertIn("Canal criado há 5,3 meses", page.inner_text("#mc-saida"))

    def test_calculadora_avisa_o_que_nao_entendeu_e_nao_inventa_numero(self):
        page = self.abrir_aba()
        page.fill("#mc-views", "abc\n1000\n2000")
        page.fill("#mc-inscritos", "xyz")
        saida = page.inner_text("#mc-saida")
        self.assertIn("Não entendi: abc, xyz", saida)
        self.assertNotIn("Tração", saida)
        page.fill("#mc-views", "")
        page.fill("#mc-inscritos", "")
        self.assertEqual(page.inner_text("#mc-saida").strip(), "")

    # ------------------------------------------------------------------ planilha: fonte = último resultado
    def test_planilha_calcula_mediana_tracao_e_ordena_por_tracao(self):
        page = self.com_resultado()
        self.assertEqual(self.nomes(page), ["Bravo", "Alfa", "Charlie", "Delta"])          # tração 4, 2, 0,01, sem dado
        self.assertIn("Último resultado desta sessão (4 canais)", page.inner_text("#mp-fonte"))
        alfa = self.linha(page, "Alfa")
        self.assertEqual(alfa[1], "500")
        self.assertIn("5,3 meses", alfa[2])
        self.assertEqual((alfa[3], alfa[4]), ("12", "3"))
        self.assertEqual((alfa[5], alfa[6], alfa[7], alfa[8], alfa[9]), ("1.000", "1.800", "2", "intermediário", "9×"))
        self.assertEqual(alfa[10], "1")                                                     # só o de 9.000 views (3 dias atrás)
        self.assertEqual(self.linha(page, "Bravo")[8], "algoritmo entregando")
        self.assertEqual(self.linha(page, "Charlie")[8], "cuidado")
        delta = self.linha(page, "Delta")
        self.assertEqual((delta[5], delta[7], delta[8], delta[9], delta[10]), ("—", "—", "sem dado", "—", "—"))
        info = page.inner_text("#mp-info")
        self.assertIn("4 canais", info)
        self.assertIn("3 com vídeos recentes", info)

    def test_ordenacao_da_planilha(self):
        page = self.com_resultado()
        page.select_option("#mp-ordem", "original")
        self.assertEqual(self.nomes(page), ["Alfa", "Bravo", "Charlie", "Delta"])
        page.select_option("#mp-ordem", "inscritos")
        self.assertEqual(self.nomes(page), ["Charlie", "Delta", "Alfa", "Bravo"])
        page.select_option("#mp-ordem", "mediana")                                          # 1.000, 1.000, 1.000 e sem dado no fim
        self.assertEqual(self.nomes(page)[-1], "Delta")

    def test_limites_n_e_filtro_de_30_dias_recalculam_sem_recarregar(self):
        page = self.com_resultado()
        page.fill("#mp-forte", "5")
        self.assertEqual(self.linha(page, "Bravo")[8], "intermediário")                     # tração 4 < 5
        page.fill("#mp-forte", "3")
        page.fill("#mp-n", "5")                                                             # últimos 5: 9000 1000 1200 800 1100 -> mediana 1.100
        self.assertEqual(self.linha(page, "Alfa")[5], "1.100")
        self.assertIn("Mediana (5)", page.inner_text("#mp-tabela thead"))
        page.fill("#mp-n", "10")
        page.uncheck("#mp-30d")                                                             # entram os 2 virais antigos (fatores 500 e 400) + o de 9.000
        self.assertEqual(self.linha(page, "Alfa")[10], "3")
        page.fill("#mp-fator", "600")
        self.assertEqual(self.linha(page, "Alfa")[10], "—")

    def test_detalhes_dos_outliers_mostram_titulo_fator_e_dias(self):
        page = self.com_resultado()
        page.locator("#mp-tabela tbody tr", has_text="Alfa").locator("details summary").click()
        detalhe = page.locator("#mp-tabela tbody tr", has_text="Alfa").locator("details").inner_text()
        self.assertIn("Vídeo de 3 dias atrás", detalhe)
        self.assertIn("9.000 views", detalhe)
        self.assertIn("9× a mediana", detalhe)
        self.assertIn("≈ 125 views/h", detalhe)                                              # 9.000 / (3 dias x 24 h)
        self.assertIn("há 3 dia(s)", detalhe)
        self.assertIn("views/h de média desde a postagem", detalhe)                          # não finge ser o VPH do VidIQ

    def test_amostra_pequena_e_marcada_com_o_n_usado(self):
        pequeno = canal("Pequeno", 500)
        pequeno["amostra_videos"] = pequeno["amostra_videos"][:0] + [vid(3, 900), vid(10, 1100), vid(20, 1000)]
        page = self.com_resultado([pequeno])
        self.assertIn("n=3", self.linha(page, "Pequeno")[5])
        self.assertEqual(self.linha(page, "Pequeno")[5].split()[0], "1.000")

    def test_sem_fonte_mostra_estado_vazio_e_csv_desabilitado(self):
        page = self.abrir_aba()
        self.assertIn("nenhuma fonte ainda", page.inner_text("#mp-fonte"))
        self.assertIn("rode uma mineração", page.inner_text("#mp-tabela"))
        self.assertTrue(page.is_disabled("#mp-csv"))

    # ------------------------------------------------------------------ CSV
    def test_csv_baixado_tem_as_metricas_na_ordem_da_tabela(self):
        page = self.com_resultado()
        with page.expect_download() as d:
            page.click("#mp-csv")
        arquivo = d.value
        self.assertRegex(arquivo.suggested_filename, r"^metodo_canais_\d{4}-\d{2}-\d{2}\.csv$")
        bruto = Path(arquivo.path()).read_bytes().decode("utf-8")
        self.assertTrue(bruto.startswith("\ufeffCanal,URL,Inscritos,"))
        linhas = list(csv.DictReader(io.StringIO(bruto.lstrip("\ufeff"))))
        self.assertEqual([l["Canal"] for l in linhas], ["Bravo", "Alfa", "Charlie", "Delta"])
        alfa = linhas[1]
        self.assertEqual((alfa["Inscritos"], alfa["Mediana de views"], alfa["Média de views"], alfa["Tração"], alfa["Sinal"]),
                         ("500", "1000", "1800", "2", "intermediário"))
        self.assertEqual((alfa["Maior fator outlier"], alfa["Outliers"], alfa["Vídeos usados na mediana"]), ("9", "1", "10"))
        self.assertIn("9000 views", alfa["Vídeos outlier"])
        self.assertEqual(linhas[3]["Mediana de views"], "")                                 # Delta: sem dado, célula vazia
        self.assertEqual(linhas[3]["Sinal"], "sem dado")

    # ------------------------------------------------------------------ planilha: fonte = Biblioteca
    def test_planilha_le_uma_busca_salva_na_biblioteca(self):
        canais = [canal("Salvo", 500), canal("Salvo2", 250)]
        busca_id = bib.salvar_busca("Astronomia", ["estrelas"], [], {}, {}, canais, [])
        page = self.abrir_aba()
        page.wait_for_selector(f'#mp-fonte option[value="busca:{busca_id}"]', state="attached")
        self.assertIn("Biblioteca · Astronomia", page.inner_text("#mp-fonte"))
        page.wait_for_selector("#mp-tabela tbody tr")
        self.assertEqual(self.nomes(page), ["Salvo2", "Salvo"])
        self.assertEqual(self.linha(page, "Salvo")[5], "1.000")

    def test_troca_de_fonte_entre_sessao_e_biblioteca(self):
        busca_id = bib.salvar_busca("Astronomia", ["estrelas"], [], {}, {}, [canal("Salvo", 500)], [])
        page = self.abrir()
        page.evaluate("(r) => renderResultado(r)", resultado([canal("DaSessao", 500)]))
        self.abrir_aba(page)
        page.wait_for_selector(f'#mp-fonte option[value="busca:{busca_id}"]', state="attached")
        self.assertEqual(self.nomes(page), ["DaSessao"])
        page.select_option("#mp-fonte", f"busca:{busca_id}")
        page.wait_for_function("() => document.querySelector('#mp-tabela tbody tr').cells[0].innerText.trim() === 'Salvo'")
        page.select_option("#mp-fonte", "sessao")
        page.wait_for_function("() => document.querySelector('#mp-tabela tbody tr').cells[0].innerText.trim() === 'DaSessao'")

    def test_busca_antiga_sem_lista_de_videos_avisa_em_vez_de_inventar(self):
        bib.salvar_busca("Antigo", ["x"], [], {}, {}, [canal("Velho", 500, com_amostra=False)], [])
        page = self.abrir_aba()
        page.wait_for_selector("#mp-tabela tbody tr")
        self.assertEqual(self.linha(page, "Velho")[5], "—")
        self.assertIn("0 com vídeos recentes", page.inner_text("#mp-info"))
        self.assertIn("rode de novo", page.inner_text("#mp-info"))

    def test_erro_ao_abrir_a_busca_aparece_e_desabilita_o_csv(self):
        busca_id = bib.salvar_busca("Astronomia", ["estrelas"], [], {}, {}, [canal("Salvo", 500)], [])
        page = self.abrir_aba()
        page.wait_for_selector(f'#mp-fonte option[value="busca:{busca_id}"]', state="attached")
        page.wait_for_selector("#mp-tabela tbody tr")
        page.route("**/api/biblioteca/busca/**", lambda r: r.fulfill(status=404, content_type="application/json",
                                                                       body=json.dumps({"ok": False, "erro": "Busca não encontrada."})))
        page.click("#mp-atualizar")
        page.wait_for_selector("#mp-tabela .empty-state")
        self.assertIn("Busca não encontrada.", page.inner_text("#mp-tabela"))
        self.assertTrue(page.is_disabled("#mp-csv"))

    # ------------------------------------------------------------------ segurança
    def test_nome_de_canal_e_titulo_de_video_hostis_nao_executam(self):
        hostil = canal('<img src=x onerror="window.__xss=1">Canal', 500, titulo_do_recente=TITULO_HOSTIL)
        page = self.com_resultado([hostil])
        page.locator("#mp-tabela tbody tr details summary").click()
        self.assertIn("<img src=x", page.inner_text("#mp-tabela"))                            # aparece como texto
        self.assertIsNone(page.evaluate("window.__xss || null"))
        page.select_option("#mp-ordem", "original")
        page.fill("#mc-views", '<b onmouseover="window.__xss=1">1000</b>')
        self.assertIn("Não entendi", page.inner_text("#mc-saida"))
        self.assertIsNone(page.evaluate("window.__xss || null"))

    # ------------------------------------------------------------------ ligação com o resto do app
    def test_usar_mediana_muda_a_referencia_das_recomendacoes_e_persiste(self):
        page = self.abrir()
        self.assertEqual(page.input_value("#rec-ref"), "media")
        self.abrir_aba(page)
        page.click("#mm-usar-mediana")
        self.assertIn("mediana", page.inner_text("#mm-info"))
        self.assertEqual(page.input_value("#rec-ref"), "mediana")
        self.assertEqual(page.evaluate("localStorage.getItem('niche_miner_rec-ref')"), "mediana")
        page.reload()
        self.assertEqual(page.input_value("#rec-ref"), "mediana")

    def test_as_outras_abas_continuam_funcionando_depois_de_visitar_a_nova(self):
        page = self.abrir_aba()
        page.click('.topnav-btn[data-view="biblioteca"]')
        self.assertTrue(page.is_visible("#view-biblioteca"))
        self.assertFalse(page.is_visible("#view-metodo"))
        page.click('.topnav-btn[data-view="ideias"]')
        self.assertTrue(page.is_visible("#view-ideias"))
        self.assertFalse(page.is_visible(".rail"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
