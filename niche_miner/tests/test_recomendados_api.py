"""Recomendações no servidor: pipeline (fonte alternativa), rotas e prompt dos canais (sem navegador e sem rede)."""
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
import biblioteca as bib
from test_app_biblioteca import _FakePW, _canal, _video

URLS = ["https://www.youtube.com/watch?v=aaaaaaaaaa1", "https://www.youtube.com/watch?v=bbbbbbbbbb2"]
RELATORIO = {"cfg": {"referencia": "media"}, "grupos": [{"origem_id": "aaaaaaaaaa1", "valor": 23687, "aprovados": 1}],
             "totais": {"coletados": 15, "aprovados": 1}, "itens": [], "origens": [], "canais_analisados": 1}


class PipelineRecomendadosTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")

    def tearDown(self):
        os.environ.pop("NICHE_MINER_DB", None)
        self._tmp.cleanup()

    def _rodar(self, falhas=None, usar_trends=False):
        vistos = {}

        def falso_processar(page, urls, cfg, min_subs, max_videos, analise, cache_canais, nicho="Sem nicho", log=print):
            vistos.update(urls=list(urls), cfg=cfg, min_subs=min_subs, nicho=nicho, analise=analise)
            videos = [_video("v1", "mistere", "Recomendados de: A", "Sem subnicho")]
            ranked = [_canal("mistere", 50, nicho=nicho, subnicho="Sem subnicho", termo_busca="Recomendados de: A"),
                      _canal("antigo", 999, fora_da_janela=True, nicho=nicho, subnicho="Sem subnicho")]
            return videos, ranked, list(falhas or []), dict(RELATORIO)

        def nao_deve_chamar(*a, **k):
            raise AssertionError("busca por termo não pode rodar na fonte de recomendações")

        job_id = webapp.novo_job()
        cfg = {"referencia": "media", "meses_max": 3}
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.recomendados, "processar_recomendados", falso_processar), \
                mock.patch.object(webapp.core, "processar_termo", nao_deve_chamar), \
                mock.patch.object(webapp.core, "checar_google_trends", nao_deve_chamar):
            webapp.rodar_pipeline(job_id, URLS, 100, 500, True, usar_trends, "Anime", [], {"data_periodo": "todos"}, True,
                                  {"janela_meses": 3}, recomendados_cfg=cfg)
        return webapp.JOBS[job_id], vistos

    def test_resultado_tem_o_mesmo_formato_da_busca_mais_o_relatorio(self):
        job, vistos = self._rodar()
        self.assertEqual(job["status"], "concluido", job.get("erro"))
        r = job["resultado"]
        self.assertEqual((r["fonte"], r["recomendados"]), ("recomendados", RELATORIO))
        self.assertEqual(vistos["urls"], URLS)
        self.assertEqual((vistos["min_subs"], vistos["nicho"]), (500, "Anime"))
        # ordena pela regra da janela: canal dentro da janela antes do que está fora, mesmo com score menor
        self.assertEqual([c["canal"] for c in r["ranking_geral"]], ["mistere", "antigo"])
        self.assertEqual([c["rank_geral"] for c in r["ranking_geral"]], [1, 2])
        for chave in ("rankings_nichos", "rankings_subnichos", "rankings_paises", "rankings_idiomas", "resumo_nichos", "verificados", "videos"):
            self.assertIn(chave, r)
        self.assertEqual(r["rankings_nichos"].keys(), {"Anime"})
        self.assertEqual(r["resumo_janela"], {"dentro": 1, "desconhecida": 0, "fora": 1})

    def test_google_trends_e_ignorado_nesta_fonte(self):
        job, _ = self._rodar(usar_trends=True)
        self.assertEqual(job["status"], "concluido", job.get("erro"))   # checar_google_trends levantaria AssertionError

    def test_salva_na_biblioteca_com_a_origem_da_config(self):
        job, _ = self._rodar()
        busca_id = job["resultado"]["busca_id"]
        self.assertIsNotNone(busca_id)
        salvo = bib.obter_busca(busca_id)
        self.assertEqual(salvo["busca"]["config"]["fonte"], "recomendados")
        self.assertEqual(salvo["busca"]["config"]["recomendados"]["meses_max"], 3)
        self.assertEqual(salvo["busca"]["termos"], URLS)          # os vídeos de origem ficam como "termos" da busca
        self.assertEqual(salvo["busca"]["tema"], "Anime")
        self.assertEqual({c["canal"] for c in salvo["canais"]}, {"mistere", "antigo"})

    def test_falhas_dos_videos_de_origem_aparecem_como_falhas(self):
        job, _ = self._rodar(falhas=["Falha isolada no vídeo de origem 'x'"])
        self.assertEqual(job["resultado"]["falhas_termos"], ["Falha isolada no vídeo de origem 'x'"])

    def test_busca_normal_continua_sem_relatorio(self):
        job_id = webapp.novo_job()

        def falso_processar_termo(page, termo, max_videos, min_subs, subnicho, nicho, filtros=None, analise=None, cache_canais=None, recomendados_auto=None):
            return [_video("v", "c", termo, subnicho)], [_canal("c", 10, nicho=nicho, subnicho=subnicho)]

        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.core, "processar_termo", falso_processar_termo):
            webapp.rodar_pipeline(job_id, ["termo"], 100, 0, True, False, "Tema", [], {"data_periodo": "mes"}, True, None)
        r = webapp.JOBS[job_id]["resultado"]
        self.assertEqual((r["fonte"], r["recomendados"]), ("busca", None))


class RotaIniciarTests(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()

    def iniciar(self, corpo, ativo=False):
        capturado, pronto = {}, threading.Event()

        def falso_pipeline(*args, **kwargs):
            capturado.update(args=args, kwargs=kwargs)
            pronto.set()

        with mock.patch.object(webapp, "rodar_pipeline", falso_pipeline), \
                mock.patch.object(webapp.ideias_api, "ha_job_ativo", return_value=ativo):
            r = self.client.post("/api/iniciar-recomendados", json=corpo)
            if r.status_code == 200:
                self.assertTrue(pronto.wait(3))
        return r, capturado

    def test_repassa_urls_padronizadas_e_configuracao_normalizada(self):
        r, cap = self.iniciar({"urls": "https://youtu.be/aaaaaaaaaa1?si=1\nhttps://www.youtube.com/watch?v=bbbbbbbbbb2&t=5",
                               "referencia": "mediana", "fator": "0,8", "meses_max": 6, "escopo": "global", "max_itens": 20,
                               "duracao_min": 3, "duracao_max": 20, "min_subs": 1000, "janela_meses": 2, "nicho": "Anime", "headless": True})
        self.assertTrue(r.get_json()["ok"])
        _job_id, urls, max_videos, min_subs, headless, trends, nicho, subnichos, filtros, mutar, analise = cap["args"]
        self.assertEqual(urls, URLS)
        self.assertEqual((min_subs, headless, trends, nicho, subnichos, mutar), (1000, True, False, "Anime", [], True))
        self.assertEqual((filtros["duracao_min"], filtros["duracao_max"], filtros["data_periodo"]), (3, 20, "todos"))
        self.assertEqual(analise["janela_meses"], 2)
        cfg = cap["kwargs"]["recomendados_cfg"]
        self.assertEqual((cfg["referencia"], cfg["fator"], cfg["meses_max"], cfg["escopo"], cfg["max_itens"]), ("mediana", 0.8, 6, "global", 20))

    def test_padroes_quando_so_as_urls_sao_enviadas(self):
        _, cap = self.iniciar({"urls": URLS[0]})
        cfg = cap["kwargs"]["recomendados_cfg"]
        self.assertEqual((cfg["referencia"], cfg["fator"], cfg["meses_max"], cfg["escopo"], cfg["max_itens"]), ("media", 1.0, 3, "por_video", 15))
        self.assertEqual(cap["args"][6], "Sem nicho")   # args = (job_id, urls, max_videos, min_subs, headless, trends, nicho, ...)

    def test_recusa_link_invalido_lista_vazia_e_excesso_de_origens(self):
        r, _ = self.iniciar({"urls": URLS[0] + "\nhttps://www.youtube.com/@canal"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("@canal", r.get_json()["erro"])
        self.assertEqual(self.iniciar({"urls": "  \n "})[0].status_code, 400)
        muitas = "\n".join(f"https://youtu.be/{i:011d}" for i in range(21))
        r, _ = self.iniciar({"urls": muitas})
        self.assertEqual(r.status_code, 400)
        self.assertIn("21", r.get_json()["erro"])
        self.assertEqual(self.iniciar({"urls": URLS[0], "min_subs": "abc"})[0].status_code, 400)

    def test_so_uma_coleta_por_vez(self):
        r, _ = self.iniciar({"urls": URLS[0]}, ativo=True)
        self.assertEqual(r.status_code, 409)

    def test_rota_de_busca_por_termo_continua_igual(self):
        cap, pronto = {}, threading.Event()

        def falso(*args, **kwargs):
            cap.update(args=args, kwargs=kwargs)
            pronto.set()

        with mock.patch.object(webapp, "rodar_pipeline", falso):
            self.assertTrue(self.client.post("/api/iniciar", json={"termos": ["x"]}).get_json()["ok"])
            self.assertTrue(pronto.wait(3))
        self.assertEqual(cap["kwargs"], {"recomendados_auto": None, "n_navegadores": 1})
        self.assertEqual(len(cap["args"]), 11)


class RotaPromptCanaisTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")
        self.client = webapp.app.test_client()
        canais = [_canal("mistere", 90, inscritos_num=12000, n_videos=9, views_totais=350000),
                  _canal("velho", 500, fora_da_janela=True)]
        videos = [{**_video("v1", "mistere", "Recomendados de: A", "Sem subnicho"), "titulo": "Estão Me Perseguindo...", "views_num": 90000}]
        self.bid = bib.salvar_busca("Anime", URLS, [], {}, {}, canais, videos)

    def tearDown(self):
        os.environ.pop("NICHE_MINER_DB", None)
        self._tmp.cleanup()

    def test_prompt_usa_os_canais_dentro_da_janela_e_seus_titulos(self):
        j = self.client.post("/api/gerar-prompt-canais", json={"busca_id": self.bid}).get_json()
        self.assertTrue(j["ok"], j)
        self.assertIn('"mistere"', j["prompt"])
        self.assertIn("12.000 inscritos", j["prompt"])
        self.assertIn("Estão Me Perseguindo...", j["prompt"])
        self.assertNotIn('"velho"', j["prompt"])      # fora da janela fica de fora
        self.assertEqual(j["n_canais"], 1)

    def test_resposta_da_ia_no_formato_do_prompt_entra_no_passo_2(self):
        resposta = '{"subnichos": [{"nome": "Terror psicológico narrado", "termos": ["scary stories narrated", "creepy pasta reading"]}]}'
        j = self.client.post("/api/validar-json", json={"texto": resposta}).get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["termos"], ["scary stories narrated", "creepy pasta reading"])

    def test_erros(self):
        self.assertEqual(self.client.post("/api/gerar-prompt-canais", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/gerar-prompt-canais", json={"busca_id": "x"}).status_code, 400)
        self.assertEqual(self.client.post("/api/gerar-prompt-canais", json={"busca_id": 999}).status_code, 404)
        vazio = bib.salvar_busca("Vazio", ["t"], [], {}, {}, [], [])
        r = self.client.post("/api/gerar-prompt-canais", json={"busca_id": vazio})
        self.assertEqual(r.status_code, 400)
        self.assertIn("canais", r.get_json()["erro"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
