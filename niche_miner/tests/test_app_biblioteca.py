"""Integração do app.py com a biblioteca (sem navegador e sem rede).

O Playwright e o ``processar_termo`` são trocados por dublês para exercitar o
``rodar_pipeline`` inteiro: ordenação por janela, cache de canais, gravação na
biblioteca e as rotas /api/biblioteca/*.
"""
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

import app as webapp
import biblioteca as bib


class _Nav:
    def __init__(self):
        self.args = None
        self.fechado = False

    def launch(self, headless=False, args=None):
        self.args = args
        return self

    def new_context(self):
        return self

    def new_page(self):
        return self

    def set_default_timeout(self, ms):
        pass

    def close(self):
        self.fechado = True


class _FakePW:
    def __init__(self):
        self.chromium = _Nav()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _canal(nome, score, **extra):
    c = {"canal": nome, "canal_url": f"https://youtube.com/@{nome}", "score": score,
         "inscritos_num": 1000, "n_videos": 10, "pais_canal": "Brasil", "idioma_canal": "Português",
         "fora_da_janela": False, "idade_desconhecida": False, "frequencia_label": "1 por semana"}
    c.update(extra)
    return c


def _video(vid, canal, termo, subnicho, verificado=False):
    return {"video_id": vid, "titulo": f"Título {vid}", "url": f"https://www.youtube.com/watch?v={vid}",
            "canal": canal, "canal_url": f"https://youtube.com/@{canal}", "canal_verificado": verificado,
            "views_num": 100, "views_text": "100 views", "data_publicacao": "2026-09-10",
            "termo_busca": termo, "subnicho": subnicho, "nicho": "Tecnologia"}


class OrdenacaoPorJanelaTests(unittest.TestCase):
    def setUp(self):
        self.canais = [
            _canal("fora_top", 900, fora_da_janela=True),
            _canal("desconhecido", 500, idade_desconhecida=True),
            _canal("novo_pequeno", 10),
            _canal("novo_grande", 80),
        ]

    def test_com_janela_novos_primeiro_depois_desconhecidos_e_fora_por_ultimo(self):
        ordem = [c["canal"] for c in webapp._ordenar_por_janela(self.canais, 3)]
        self.assertEqual(ordem, ["novo_grande", "novo_pequeno", "desconhecido", "fora_top"])

    def test_sem_janela_ordena_so_pelo_score(self):
        ordem = [c["canal"] for c in webapp._ordenar_por_janela(self.canais, 0)]
        self.assertEqual(ordem, ["fora_top", "desconhecido", "novo_grande", "novo_pequeno"])

    def test_resumo_da_janela(self):
        self.assertEqual(webapp._resumo_janela(self.canais), {"dentro": 2, "desconhecida": 1, "fora": 1})


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")
        self.chamadas = []

    def tearDown(self):
        os.environ.pop("NICHE_MINER_DB", None)
        self._tmp.cleanup()

    def _rodar(self, termos, analise=None, falhar_em=None):
        chamadas = self.chamadas

        def falso_processar_termo(page, termo, max_videos, min_subs, subnicho, nicho, filtros=None,
                                  analise=None, cache_canais=None, recomendados_auto=None):
            chamadas.append({"termo": termo, "analise": analise, "cache": cache_canais, "recomendados_auto": recomendados_auto})
            if termo == falhar_em:
                raise RuntimeError("boom")
            cache_canais[f"usado:{termo}"] = True
            videos = [_video(f"v_{termo}", "novo", termo, subnicho),
                      _video(f"g_{termo}", "grande", termo, subnicho, verificado=True)]
            ranked = [_canal("antigo", 999, fora_da_janela=True, nicho=nicho, subnicho=subnicho, termo_busca=termo),
                      _canal("novo", 50, nicho=nicho, subnicho=subnicho, termo_busca=termo)]
            return videos, ranked

        job_id = webapp.novo_job()
        subnichos = [{"nome": "Segurança", "termos": list(termos)}]
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.core, "processar_termo", falso_processar_termo):
            webapp.rodar_pipeline(job_id, list(termos), 100, 0, True, False, "Tecnologia", subnichos,
                                  {"data_periodo": "mes"}, True, analise)
        return webapp.JOBS[job_id]

    def test_pipeline_ordena_por_janela_e_salva_na_biblioteca(self):
        job = self._rodar(["hacker", "invasão"], {"janela_meses": 2})
        self.assertEqual(job["status"], "concluido", job["erro"])
        r = job["resultado"]
        self.assertEqual([c["canal"] for c in r["ranking_geral"]], ["novo", "antigo"])  # novo antes, mesmo com score menor
        self.assertEqual(r["resumo_janela"], {"dentro": 1, "desconhecida": 0, "fora": 1})
        self.assertEqual(r["analise"]["janela_meses"], 2)
        self.assertIsNotNone(r["busca_id"])
        self.assertTrue(any("Busca salva na biblioteca" in linha for linha in job["logs"]))

        salvo = bib.obter_busca(r["busca_id"])
        self.assertEqual(salvo["busca"]["tema"], "Tecnologia")
        self.assertEqual(salvo["busca"]["termos"], ["hacker", "invasão"])
        self.assertEqual(salvo["busca"]["config"]["janela_meses"], 2)
        self.assertEqual([c["canal"] for c in salvo["canais"]], ["novo", "antigo"])
        self.assertEqual(len(salvo["videos"]), 4)
        self.assertEqual([v["canal"] for v in salvo["verificados"]], ["grande"])

    def test_termos_compartilham_analise_e_cache_do_mesmo_job(self):
        self._rodar(["a", "b", "c"], {"janela_meses": 1, "descartar_fora_janela": False})
        self.assertEqual(len(self.chamadas), 3)
        self.assertTrue(all(c["analise"]["janela_meses"] == 1 for c in self.chamadas))
        self.assertTrue(all(c["analise"]["descartar_fora_janela"] is False for c in self.chamadas))
        self.assertEqual(len({id(c["cache"]) for c in self.chamadas}), 1)  # o MESMO dict

    def test_falha_em_um_termo_nao_impede_de_salvar_os_outros(self):
        job = self._rodar(["ok1", "quebra", "ok2"], falhar_em="quebra")
        self.assertEqual(job["status"], "concluido")
        self.assertEqual(len(job["resultado"]["falhas_termos"]), 1)
        self.assertIsNotNone(job["resultado"]["busca_id"])
        self.assertEqual(bib.obter_busca(job["resultado"]["busca_id"])["busca"]["termos"], ["ok1", "quebra", "ok2"])

    def test_falha_ao_salvar_nao_derruba_o_job(self):
        with mock.patch.object(webapp.biblioteca, "salvar_busca", side_effect=OSError("disco cheio")):
            job = self._rodar(["a"])
        self.assertEqual(job["status"], "concluido")
        self.assertIsNone(job["resultado"]["busca_id"])
        self.assertTrue(any("não foi possível salvar na biblioteca" in linha for linha in job["logs"]))


class RotasTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")
        self.client = webapp.app.test_client()
        self.bid = bib.salvar_busca(
            "Tecnologia", ["hacker"], [], {}, {},
            [_canal("acao", 10, views_totais=555)], [_video("v1", "acao", "hacker", "Seg")])

    def tearDown(self):
        os.environ.pop("NICHE_MINER_DB", None)
        self._tmp.cleanup()

    def test_listar_obter_pesquisar_e_excluir(self):
        j = self.client.get("/api/biblioteca").get_json()
        self.assertEqual(j["temas"][0]["tema"], "Tecnologia")
        self.assertEqual(j["temas"][0]["buscas"][0]["id"], self.bid)

        j = self.client.get(f"/api/biblioteca/busca/{self.bid}").get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["canais"][0]["views_totais"], 555)

        j = self.client.get("/api/biblioteca/pesquisar?q=TITULO").get_json()
        self.assertEqual(len(j["videos"]), 1)
        self.assertEqual(self.client.get("/api/biblioteca/pesquisar?q=").get_json()["videos"], [])

        self.assertEqual(self.client.delete(f"/api/biblioteca/busca/{self.bid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/biblioteca/busca/{self.bid}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/biblioteca/busca/{self.bid}").status_code, 404)

    def test_csv_tem_bom_e_nome_de_arquivo(self):
        r = self.client.get(f"/api/biblioteca/busca/{self.bid}/canais.csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.mimetype.startswith("text/csv"))
        self.assertTrue(r.data.startswith("\ufeff".encode("utf-8")))
        self.assertIn(f"busca_{self.bid}_canais.csv", r.headers["Content-Disposition"])
        self.assertEqual(self.client.get(f"/api/biblioteca/busca/{self.bid}/xyz.csv").status_code, 404)
        self.assertEqual(self.client.get("/api/biblioteca/busca/999/videos.csv").status_code, 404)

    def test_iniciar_repassa_a_config_da_analise(self):
        capturado = {}
        pronto = threading.Event()

        def falso_pipeline(*args, **kwargs):
            capturado["args"] = args
            capturado["kwargs"] = kwargs
            pronto.set()

        with mock.patch.object(webapp, "rodar_pipeline", falso_pipeline):
            r = self.client.post("/api/iniciar", json={
                "termos": ["x"], "nicho": "Tema", "janela_meses": 2, "descartar_fora_janela": False})
            self.assertTrue(r.get_json()["ok"])
            self.assertTrue(pronto.wait(3))
        analise = capturado["args"][-1]
        self.assertEqual(analise["janela_meses"], 2)
        self.assertIs(analise["descartar_fora_janela"], False)
        self.assertEqual(analise["n_frequencia"], 50)

    def test_iniciar_sem_config_usa_janela_de_3_meses(self):
        capturado = {}
        pronto = threading.Event()

        def falso_pipeline(*args, **kwargs):
            capturado["analise"] = args[-1]
            pronto.set()

        with mock.patch.object(webapp, "rodar_pipeline", falso_pipeline):
            self.client.post("/api/iniciar", json={"termos": ["x"]})
            self.assertTrue(pronto.wait(3))
        self.assertEqual(capturado["analise"]["janela_meses"], 3)
        self.assertIs(capturado["analise"]["descartar_fora_janela"], True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
