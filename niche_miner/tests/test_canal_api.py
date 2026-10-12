"""Rotas /api/canal/* e o job de análise, sem navegador e sem rede (Playwright e scraper trocados por dublês)."""
import json
import os
import sys
import tempfile
import threading
import time
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


class _Pagina:
    def __init__(self, titulo="Estoico Exemplo - YouTube"):
        self.titulo = titulo

    def title(self):
        return self.titulo

    def set_default_timeout(self, ms):
        pass


class _Nav:
    def __init__(self, pagina):
        self.pagina, self.launch_args, self.headless, self.fechado = pagina, None, None, False

    def launch(self, headless=False, args=None):
        self.headless, self.launch_args = headless, args
        return self

    def new_context(self):
        return self

    def new_page(self):
        return self.pagina

    def set_default_timeout(self, ms):
        pass

    def close(self):
        self.fechado = True


class _FakePW:
    def __init__(self, pagina=None):
        self.chromium = _Nav(pagina or _Pagina())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sobre_ok(page, url):
    return {"inscritos_text": "8,5 mil inscritos", "inscritos_num": 8500, "n_videos": 40, "views_totais": 400000,
            "data_criacao_canal": "2026-04-14", "pais_canal": "Brasil", "idioma_canal": "Português"}


def detalhes_ok(page, url, n_frequencia=50, total_videos=None, **kw):
    r = registro()
    return {"amostra_videos": r["amostra_videos"], "amostra_completa": False, "videos_ultimos_30d": 4, "frequencia_label": "1 vídeo por semana"}


class ApiBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "t.db")
        env = mock.patch.dict(os.environ, {"NICHE_MINER_DB": self.db})
        env.start()
        self.addCleanup(env.stop)
        webapp.JOBS.clear()
        self.c = webapp.app.test_client()

    def post(self, url, corpo=None):
        r = self.c.post(url, json=corpo or {})
        return r.status_code, r.get_json()

    def esperar_job(self, job_id, limite=10):
        fim = time.time() + limite
        while time.time() < fim:
            j = webapp.JOBS[job_id]
            if j["status"] in ("concluido", "erro"):
                return j
            time.sleep(0.05)
        self.fail("job não terminou a tempo")

    def semear(self, **extra):
        return canal.salvar_analise(registro(**extra), AGORA, self.db)

    def analisar(self, corpo=None, sobre=sobre_ok, detalhes=detalhes_ok, pagina=None):
        pw = _FakePW(pagina)
        with mock.patch.object(canal_api, "sync_playwright", lambda: pw), \
             mock.patch.object(core, "scrape_channel_about", sobre), \
             mock.patch.object(core, "enrich_channel_details", detalhes):
            status, j = self.post("/api/canal/analisar", corpo or {"url": "@estoicoexemplo"})
            if status != 200:
                return status, j, None, pw
            return status, j, self.esperar_job(j["job_id"]), pw


class AnaliseJobTests(ApiBase):
    def test_analisar_le_o_canal_grava_e_devolve_o_id(self):
        status, j, job, pw = self.analisar({"url": "youtube.com/@estoicoexemplo/videos", "n_videos": 60, "headless": True, "mutar_audio": False})
        self.assertEqual(status, 200)
        self.assertEqual(job["status"], "concluido", job.get("erro"))
        self.assertEqual(job["resultado"]["n_videos_lidos"], 16)
        a = canal.obter_analise(job["resultado"]["analise_id"], self.db)
        self.assertEqual(a["canal"], "Estoico Exemplo")                                   # nome tirado do título da página
        self.assertEqual(a["canal_url"], "https://www.youtube.com/@estoicoexemplo")        # link normalizado
        self.assertEqual((a["dados"]["metricas"]["inscritos"], a["dados"]["metricas"]["views_totais"]), (8500, 400000))
        self.assertEqual(len(a["dados"]["videos"]), 16)
        self.assertTrue(pw.chromium.fechado)
        self.assertTrue(pw.chromium.headless)
        self.assertEqual(pw.chromium.launch_args, [])                                     # áudio não mutado
        self.assertTrue(any("Análise salva" in l for l in job["logs"]))
        self.assertTrue(any("Estoico Exemplo" in l for l in job["logs"]))

    def test_n_videos_e_repassado_e_limitado(self):
        vistos = []

        def detalhes(page, url, n_frequencia=50, total_videos=None, **kw):
            vistos.append((n_frequencia, total_videos))
            return detalhes_ok(page, url)
        for pedido, esperado in ((60, 60), (5, canal_api.MIN_VIDEOS), (9999, canal_api.MAX_VIDEOS), ("abc", canal_api.PADRAO_VIDEOS), (None, canal_api.PADRAO_VIDEOS)):
            webapp.JOBS.clear()
            self.analisar({"url": "@x", "n_videos": pedido}, detalhes=detalhes)
            self.assertEqual(vistos[-1], (esperado, 40), pedido)                          # total de vídeos vem do cabeçalho

    def test_canal_sem_videos_lidos_vira_erro_claro_e_fecha_o_navegador(self):
        status, j, job, pw = self.analisar(detalhes=lambda *a, **k: {"amostra_videos": []})
        self.assertEqual(job["status"], "erro")
        self.assertIn("Não consegui ler os vídeos", job["erro"])
        self.assertTrue(pw.chromium.fechado)
        self.assertEqual(canal.listar_analises(self.db), [])                              # nada salvo pela metade

    def test_falha_do_scraper_vira_erro_do_job_e_libera_a_trava(self):
        def quebra(page, url):
            raise RuntimeError("página mudou")
        status, j, job, pw = self.analisar(sobre=quebra)
        self.assertEqual(job["status"], "erro")
        self.assertIn("página mudou", job["erro"])
        self.assertTrue(pw.chromium.fechado)
        for _ in range(50):
            if not webapp.JOBS[j["job_id"]]["thread"].is_alive():
                break
            time.sleep(0.02)
        status2, j2, job2, _ = self.analisar()                                            # outra análise já pode começar
        self.assertEqual(job2["status"], "concluido")

    def test_link_invalido_nao_inicia_job(self):
        for lixo in ("", "https://www.youtube.com/watch?v=aaaaaaaaaaa", "banana", None):
            status, j = self.post("/api/canal/analisar", {"url": lixo})
            self.assertEqual(status, 400, lixo)
            self.assertFalse(j["ok"])
        self.assertEqual(webapp.JOBS, {})
        _, j = self.post("/api/canal/analisar", {"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"})
        self.assertIn("link de um vídeo", j["erro"])

    def test_so_uma_coleta_por_vez_com_qualquer_aba(self):
        livre = threading.Event()
        webapp.JOBS["outro"] = {"status": "rodando", "logs": [], "resultado": None, "erro": None, "thread": threading.Thread(target=livre.wait, daemon=True)}
        webapp.JOBS["outro"]["thread"].start()
        self.addCleanup(livre.set)
        status, j = self.post("/api/canal/analisar", {"url": "@x"})
        self.assertEqual(status, 409)
        self.assertIn("Já existe uma coleta", j["erro"])

    def test_json_invalido_no_corpo_nao_derruba_a_rota(self):
        r = self.c.post("/api/canal/analisar", data="isso nao e json", content_type="application/json")
        self.assertEqual(r.status_code, 400)


class CrudTests(ApiBase):
    def test_listar_obter_excluir(self):
        aid = self.semear()
        lista = self.c.get("/api/canal/analises").get_json()["analises"]
        self.assertEqual([(a["id"], a["canal"]) for a in lista], [(aid, "Estoico Exemplo")])
        a = self.c.get(f"/api/canal/analises/{aid}").get_json()["analise"]
        self.assertEqual(a["dados"]["metricas"]["mediana_ultimos"], 4000)
        self.assertEqual(self.c.delete(f"/api/canal/analises/{aid}").get_json(), {"ok": True})
        self.assertEqual(self.c.get(f"/api/canal/analises/{aid}").status_code, 404)
        self.assertEqual(self.c.delete(f"/api/canal/analises/{aid}").status_code, 404)

    def test_lista_vazia(self):
        self.assertEqual(self.c.get("/api/canal/analises").get_json(), {"ok": True, "analises": []})


class PromptEIaTests(ApiBase):
    def setUp(self):
        super().setUp()
        self.aid = self.semear()
        self.base = f"/api/canal/analises/{self.aid}"

    def test_prompt_de_cada_tipo(self):
        _, j = self.post(f"{self.base}/prompt/categorias")
        self.assertIn('"categorias"', j["prompt"])
        _, j = self.post(f"{self.base}/prompt/estrategia", {"mercado": "Alemanha", "objetivo": "canal em alemão"})
        self.assertIn("Alemanha — títulos em alemão", j["prompt"])
        self.assertIn("Meu objetivo: canal em alemão", j["prompt"])
        _, j = self.post(f"{self.base}/prompt/comentarios", {"comentarios": "a1 ótimo\nb2 ruim\nc3 legal\nd4 quero mais\ne5 bom demais"})
        self.assertIn("- d4 quero mais", j["prompt"])

    def test_prompt_de_comentarios_sem_o_minimo_e_erro_400(self):
        status, j = self.post(f"{self.base}/prompt/comentarios", {"comentarios": "só um"})
        self.assertEqual(status, 400)
        self.assertIn("pelo menos 5", j["erro"])

    def test_tipo_ou_analise_inexistente_e_404(self):
        self.assertEqual(self.post(f"{self.base}/prompt/outro")[0], 404)
        self.assertEqual(self.post("/api/canal/analises/999/prompt/categorias")[0], 404)
        self.assertEqual(self.post(f"{self.base}/ia/outro", {"texto": "{}"})[0], 404)
        self.assertEqual(self.post("/api/canal/analises/999/ia/categorias", {"texto": "{}"})[0], 404)
        self.assertEqual(self.c.delete(f"{self.base}/ia/outro").status_code, 404)
        self.assertEqual(self.c.delete("/api/canal/analises/999/ia/categorias").status_code, 404)

    def test_aplicar_categorias_devolve_estatisticas_calculadas_pelo_app(self):
        a = self.c.get(self.base).get_json()["analise"]
        idx = {v["titulo"]: v["indice"] for v in a["dados"]["videos"]}
        texto = "```json\n" + json.dumps({"categorias": [{"nome": "Listas", "indices": [idx["12 lições estoicas para ouvir toda manhã"], idx["5 hábitos estoicos que mudam sua vida"], 999]}]}) + "\n```"
        status, j = self.post(f"{self.base}/ia/categorias", {"texto": texto})
        self.assertEqual(status, 200)
        cat = j["analise"]["ia"]["categorias"]
        self.assertEqual(cat["estatisticas"][0]["n"], 2)
        self.assertEqual(cat["estatisticas"][0]["mediana_views"], 8750)
        self.assertEqual(cat["sem_categoria"], 14)
        # persistiu
        self.assertEqual(self.c.get(self.base).get_json()["analise"]["ia"]["categorias"]["estatisticas"][0]["n"], 2)

    def test_aplicar_estrategia_e_comentarios_e_limpar(self):
        est = {"oportunidades": [{"oportunidade": "Estoicismo no trabalho", "como_diferenciar": "casos reais"}], "topicos_sugeridos": [{"titulo": "5 hábitos"}]}
        _, j = self.post(f"{self.base}/ia/estrategia", {"texto": json.dumps(est)})
        self.assertEqual(j["analise"]["ia"]["estrategia"]["oportunidades"][0]["oportunidade"], "Estoicismo no trabalho")
        _, j = self.post(f"{self.base}/ia/comentarios", {"texto": json.dumps({"pedidos": ["legendas"]})})
        self.assertEqual(set(j["analise"]["ia"]), {"estrategia", "comentarios"})
        j = self.c.delete(f"{self.base}/ia/estrategia").get_json()
        self.assertEqual(set(j["analise"]["ia"]), {"comentarios"})

    def test_estrategia_ja_aplicada_entra_no_prompt_de_estrategia_seguinte(self):
        self.post(f"{self.base}/ia/comentarios", {"texto": json.dumps({"nao_gostaram": [{"tema": "áudio baixo"}], "pedidos": ["legendas"]})})
        _, j = self.post(f"{self.base}/prompt/estrategia")
        self.assertIn("critica: áudio baixo", j["prompt"])
        self.assertIn("pede: legendas", j["prompt"])

    def test_json_ruim_da_ia_da_400_com_mensagem_e_nao_grava(self):
        for tipo in ("categorias", "estrategia", "comentarios"):
            for lixo in ("", "isto não é json", "{}"):
                status, j = self.post(f"{self.base}/ia/{tipo}", {"texto": lixo})
                self.assertEqual(status, 400, (tipo, lixo))
                self.assertFalse(j["ok"])
        self.assertEqual(self.c.get(self.base).get_json()["analise"]["ia"], {})

    def test_rota_de_texto_sem_corpo_nao_derruba(self):
        r = self.c.post(f"{self.base}/ia/categorias", data="x", content_type="application/json")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
