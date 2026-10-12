"""Navegadores em paralelo (rodar_pipeline) e o modo automático de recomendados (recomendados_auto)
na busca por termo — sem navegador real e sem rede: Playwright e processar_termo são dublês."""
import os
import re
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
import recomendados as rec
import yt_scraper as core
from test_app_biblioteca import _FakePW, _canal, _video


class DividirTests(unittest.TestCase):
    def test_distribui_em_roda_viva_preservando_a_ordem_dentro_do_grupo(self):
        self.assertEqual(webapp._dividir(["a", "b", "c", "d", "e"], 2), [["a", "c", "e"], ["b", "d"]])
        self.assertEqual(webapp._dividir(["a", "b", "c"], 3), [["a"], ["b"], ["c"]])

    def test_grupo_vazio_nao_entra_no_resultado(self):
        self.assertEqual(webapp._dividir(["a", "b"], 5), [["a"], ["b"]])
        self.assertEqual(webapp._dividir([], 3), [])
        self.assertEqual(webapp._dividir(["a"], 1), [["a"]])

    def test_n_menor_que_1_vira_1(self):
        self.assertEqual(webapp._dividir(["a", "b"], 0), [["a", "b"]])


class LogStreamThreadTests(unittest.TestCase):
    def setUp(self):
        webapp.JOBS.clear()
        self.job_id = webapp.novo_job()
        self.log = webapp.LogStream(self.job_id)

    def tearDown(self):
        # job "pendente" sem thread registrada conta como ativo (ver ha_job_ativo) — não deixar
        # sobrar no dict global compartilhado por todos os arquivos de teste.
        webapp.JOBS.pop(self.job_id, None)

    def test_cada_thread_tem_seu_prefixo_e_as_linhas_nao_se_misturam(self):
        def trabalhar(prefixo, partes):
            self.log.marcar_thread(prefixo)
            for p in partes:
                self.log.write(p)  # escreve em pedaços, como print() faria em mais de uma chamada

        t1 = threading.Thread(target=trabalhar, args=("[navegador 1] ", ["linha ", "a1\nlinha ", "a2\n"]))
        t2 = threading.Thread(target=trabalhar, args=("[navegador 2] ", ["linha ", "b1\nlinha ", "b2\n"]))
        t1.start(); t1.join()
        t2.start(); t2.join()
        logs = webapp.JOBS[self.job_id]["logs"]
        self.assertEqual(logs, ["[navegador 1] linha a1", "[navegador 1] linha a2", "[navegador 2] linha b1", "[navegador 2] linha b2"])

    def test_sem_marcar_thread_nao_tem_prefixo(self):
        self.log.write("sem prefixo\n")
        self.assertEqual(webapp.JOBS[self.job_id]["logs"], ["sem prefixo"])

    def test_escritas_concorrentes_em_muitas_threads_nao_corrompem_linhas(self):
        n = 12

        def trabalhar(i):
            self.log.marcar_thread(f"[t{i}] ")
            for _ in range(20):
                self.log.write(f"x{i}\n")

        threads = [threading.Thread(target=trabalhar, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        logs = webapp.JOBS[self.job_id]["logs"]
        self.assertEqual(len(logs), n * 20)
        for i in range(n):
            self.assertEqual(sum(1 for l in logs if l == f"[t{i}] x{i}"), 20)
        self.assertTrue(all(re.fullmatch(r"\[t\d+\] x\d+", l) for l in logs))  # nenhuma linha corrompida/misturada


class PipelineMultiNavegadorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")
        self.chamadas = []
        self.lock = threading.Lock()

    def tearDown(self):
        os.environ.pop("NICHE_MINER_DB", None)
        self._tmp.cleanup()

    def _processar_termo_falso(self, falhar_em=None, capturar_auto=None):
        def falso(page, termo, max_videos, min_subs, subnicho, nicho, filtros=None, analise=None, cache_canais=None, recomendados_auto=None):
            with self.lock:
                self.chamadas.append(termo)
                if capturar_auto is not None:
                    capturar_auto.append(recomendados_auto)
            if termo == falhar_em:
                raise RuntimeError("boom")
            videos = [_video(f"v_{termo}", f"canal_{termo}", termo, subnicho)]
            ranked = [_canal(f"canal_{termo}", 50, nicho=nicho, subnicho=subnicho, termo_busca=termo)]
            return videos, ranked
        return falso

    def _rodar(self, termos, n_navegadores, **kw):
        job_id = webapp.novo_job()
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.core, "processar_termo", self._processar_termo_falso(**kw)):
            webapp.rodar_pipeline(job_id, list(termos), 100, 0, True, False, "Tema", [],
                                  {"data_periodo": "mes"}, True, None, n_navegadores=n_navegadores)
        return webapp.JOBS[job_id]

    def test_todos_os_termos_sao_processados_exatamente_uma_vez(self):
        termos = [f"termo{i}" for i in range(7)]
        job = self._rodar(termos, 3)
        self.assertEqual(job["status"], "concluido", job["erro"])
        self.assertEqual(sorted(self.chamadas), sorted(termos))
        r = job["resultado"]
        self.assertEqual(len(r["ranking_geral"]), 7)
        self.assertEqual(len(r["videos"]), 7)

    def test_log_mostra_quantos_navegadores_e_prefixa_as_linhas(self):
        job = self._rodar([f"t{i}" for i in range(4)], 2)
        logs = job["logs"]
        self.assertTrue(any("Rodando com 2 navegadores em paralelo" in l for l in logs))
        self.assertTrue(any(l.startswith("[navegador 1] ") for l in logs))
        self.assertTrue(any(l.startswith("[navegador 2] ") for l in logs))
        # a linha final (fora das threads) não fica com prefixo de navegador nenhum
        self.assertTrue(any(l.startswith("Concluído.") for l in logs))
        self.assertFalse(any(re.match(r"^\[navegador \d+\] Concluído\.", l) for l in logs))
        self.assertTrue(any(l.startswith("[navegador 1] Terminou este navegador.") for l in logs))

    def test_nao_abre_mais_navegadores_do_que_termos(self):
        job = self._rodar(["unico"], 5)
        logs = job["logs"]
        self.assertTrue(any("ignorando os navegadores extras" in l for l in logs))
        self.assertFalse(any("em paralelo" in l for l in logs))
        self.assertEqual(self.chamadas, ["unico"])

    def test_n_navegadores_1_e_o_caminho_de_sempre_sem_mencao_a_navegadores_no_plural(self):
        job = self._rodar(["a", "b"], 1)
        self.assertTrue(any("Rodando com 1 navegador." in l for l in job["logs"]))
        self.assertFalse(any("[navegador" in l for l in job["logs"]))

    def test_falha_isolada_em_um_termo_nao_derruba_os_demais_mesmo_em_outra_thread(self):
        termos = [f"t{i}" for i in range(6)]
        job = self._rodar(termos, 3, falhar_em="t3")
        self.assertEqual(job["status"], "concluido", job["erro"])
        self.assertIn("t3", job["resultado"]["falhas_termos"][0])
        self.assertEqual(sorted(c["canal"] for c in job["resultado"]["ranking_geral"]), sorted(f"canal_{t}" for t in termos if t != "t3"))
        self.assertEqual(sorted(self.chamadas), sorted(termos))  # a falha não impediu os outros de rodar

    def test_recomendados_auto_e_repassado_para_cada_chamada_mesmo_com_varios_navegadores(self):
        capturados = []
        job_id = webapp.novo_job()
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.core, "processar_termo", self._processar_termo_falso(capturar_auto=capturados)):
            webapp.rodar_pipeline(job_id, [f"t{i}" for i in range(4)], 100, 0, True, False, "Tema", [],
                                  {"data_periodo": "mes"}, True, None, n_navegadores=2,
                                  recomendados_auto={"ativo": True, "max_itens": 7})
        self.assertEqual(len(capturados), 4)
        self.assertTrue(all(c == {"ativo": True, "max_itens": 7} for c in capturados))

    def test_cada_navegador_tem_seu_proprio_cache_de_canais(self):
        vistos_cache = []

        def falso(page, termo, max_videos, min_subs, subnicho, nicho, filtros=None, analise=None, cache_canais=None, recomendados_auto=None):
            with self.lock:
                vistos_cache.append(id(cache_canais))
            return [], []

        job_id = webapp.novo_job()
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.core, "processar_termo", falso):
            webapp.rodar_pipeline(job_id, [f"t{i}" for i in range(4)], 100, 0, True, False, "Tema", [],
                                  {"data_periodo": "mes"}, True, None, n_navegadores=2)
        # 4 termos em 2 navegadores -> só 2 dicts de cache distintos (um por navegador, reaproveitado dentro dele)
        self.assertEqual(len(set(vistos_cache)), 2)


class PipelineMultiNavegadorRecomendadosCfgTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["NICHE_MINER_DB"] = os.path.join(self._tmp.name, "b.db")

    def tearDown(self):
        os.environ.pop("NICHE_MINER_DB", None)
        self._tmp.cleanup()

    def _processar_recomendados_falso(self, urls_vistas, lock, falhar_url=None):
        def falso(page, urls, cfg, min_subs, max_videos, analise, cache_canais, nicho="Sem nicho", log=print):
            with lock:
                urls_vistas.extend(urls)
            if falhar_url and falhar_url in urls:
                raise RuntimeError("boom-rec")
            videos = [_video(f"v_{u[-1]}", f"canal_{u[-1]}", f"Recomendados de: {u}", "Sem subnicho") for u in urls]
            ranked = [_canal(f"canal_{u[-1]}", 50, nicho=nicho, subnicho="Sem subnicho") for u in urls]
            relatorio = {"cfg": cfg, "grupos": [{"origem_id": u, "valor": 100, "aprovados": 1} for u in urls],
                        "origens": [{"origem_id": u} for u in urls], "itens": [{"video_id": u} for u in urls],
                        "totais": {"coletados": len(urls), "aprovados": len(urls)}, "canais_analisados": len(urls)}
            return videos, ranked, [], relatorio
        return falso

    def test_urls_divididas_entre_navegadores_e_relatorios_somados(self):
        urls = [f"https://www.youtube.com/watch?v=vid{i:08d}" for i in range(6)]
        vistas, lock = [], threading.Lock()
        job_id = webapp.novo_job()
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.recomendados, "processar_recomendados", self._processar_recomendados_falso(vistas, lock)):
            webapp.rodar_pipeline(job_id, urls, 100, 500, True, False, "Anime", [], {"data_periodo": "todos"}, True,
                                  {"janela_meses": 3}, recomendados_cfg={"referencia": "media"}, n_navegadores=3)
        job = webapp.JOBS[job_id]
        self.assertEqual(job["status"], "concluido", job["erro"])
        self.assertEqual(sorted(vistas), sorted(urls))
        r = job["resultado"]
        self.assertEqual(len(r["videos"]), 6)
        self.assertEqual(r["recomendados"]["totais"], {"coletados": 6, "aprovados": 6})
        self.assertEqual(len(r["recomendados"]["grupos"]), 6)
        self.assertEqual(r["recomendados"]["canais_analisados"], 6)

    def test_falha_em_um_navegador_do_modo_recomendados_nao_derruba_os_outros(self):
        urls = [f"https://www.youtube.com/watch?v=vid{i:08d}" for i in range(4)]
        vistas, lock = [], threading.Lock()
        job_id = webapp.novo_job()
        with mock.patch.object(webapp, "sync_playwright", lambda: _FakePW()), \
                mock.patch.object(webapp.recomendados, "processar_recomendados",
                                  self._processar_recomendados_falso(vistas, lock, falhar_url=urls[0])):
            webapp.rodar_pipeline(job_id, urls, 100, 500, True, False, "Anime", [], {"data_periodo": "todos"}, True,
                                  {"janela_meses": 3}, recomendados_cfg={"referencia": "media"}, n_navegadores=4)
        job = webapp.JOBS[job_id]
        self.assertEqual(job["status"], "concluido", job["erro"])
        self.assertTrue(any("navegador" in f.lower() for f in job["resultado"]["falhas_termos"]))
        # os outros 3 navegadores ainda produziram vídeos normalmente
        self.assertGreaterEqual(len(job["resultado"]["videos"]), 3)


class ProcessarTermoRecomendadosAutoTests(unittest.TestCase):
    """A ligação real dentro de yt_scraper.processar_termo (sem app.py): lateral lida sem
    navegar de novo, triada pela mesma lógica da mineração manual e somada aos candidatos."""

    def test_recomendados_auto_le_a_lateral_apos_cada_video_validado_e_soma_aprovados(self):
        video_busca = {"video_id": "buscaAAAA1", "url": "https://www.youtube.com/watch?v=buscaAAAA1",
                       "titulo": "Vídeo achado na busca", "canal": "Canal Base", "canal_url": "https://youtube.com/@base",
                       "canal_verificado": False, "views_num": 500, "views_text": "500", "duracao_segundos": 300, "data_publicacao": "2026-09-01"}
        item_lateral_bruto = {"id": "recAAAAAAA1", "href": "/watch?v=recAAAAAAA1", "titulo": "Recomendado bom", "canal": "Canal Rec",
                              "verificado": False, "views_txt": "50 mil visualizações", "quando_txt": "há 1 semana", "dur_txt": "5:00", "texto": ""}
        video_aprovado = {"video_id": "recAAAAAAA1", "url": "https://www.youtube.com/watch?v=recAAAAAAA1", "titulo": "Recomendado bom",
                          "canal": "Canal Rec", "canal_url": "https://youtube.com/@rec", "canal_verificado": False,
                          "views_num": 50000, "views_text": "50 mil", "data_publicacao": "2026-09-10T00:00:00", "termo_busca": "",
                          "duracao_segundos": 300}

        with mock.patch.object(core, "build_search_url", return_value="https://busca"), \
                mock.patch.object(core, "collect_videos", return_value=[video_busca]), \
                mock.patch.object(core, "_filtrar_por_duracao", side_effect=lambda v, f: v), \
                mock.patch.object(core, "validar_video_no_periodo", return_value=(True, "ok")), \
                mock.patch.object(core, "apply_filters"), \
                mock.patch.object(core, "analisar_canais_nao_verificados") as falso_analise, \
                mock.patch.object(rec, "_ler_lateral_atual", return_value=("Vídeo achado na busca", [item_lateral_bruto])) as falso_ler, \
                mock.patch.object(rec, "processar_lateral_inline", return_value=([video_aprovado], {"grupos": []})) as falso_inline:
            page = mock.MagicMock()
            falso_analise.return_value = []
            videos, ranked = core.processar_termo(page, "termo x", 100, 0, "Sub", "Nicho",
                                                   recomendados_auto={"ativo": True, "max_itens": 5})

        falso_ler.assert_called_once()
        self.assertEqual(falso_ler.call_args[0][0], page)
        falso_inline.assert_called_once()
        # os itens brutos da lateral chegam normalizados (com a origem = o vídeo achado na busca)
        itens_passados = falso_inline.call_args[0][1]
        self.assertEqual(len(itens_passados), 1)
        self.assertEqual(itens_passados[0]["origem_id"], "buscaAAAA1")
        self.assertEqual(itens_passados[0]["video_id"], "recAAAAAAA1")
        # o vídeo aprovado na lateral entrou na lista que vai para a análise de canais, além do vídeo original
        videos_para_analise = falso_analise.call_args[0][1]
        self.assertEqual({v["video_id"] for v in videos_para_analise}, {"buscaAAAA1", "recAAAAAAA1"})

    def test_sem_aprovados_na_lateral_nao_chama_a_validacao(self):
        video_busca = {"video_id": "buscaAAAA1", "url": "https://www.youtube.com/watch?v=buscaAAAA1",
                       "titulo": "Vídeo achado", "canal": "Canal Base", "canal_url": "https://youtube.com/@base",
                       "canal_verificado": False, "views_num": 500, "views_text": "500", "duracao_segundos": 300, "data_publicacao": "2026-09-01"}
        with mock.patch.object(core, "build_search_url", return_value="https://busca"), \
                mock.patch.object(core, "collect_videos", return_value=[video_busca]), \
                mock.patch.object(core, "_filtrar_por_duracao", side_effect=lambda v, f: v), \
                mock.patch.object(core, "validar_video_no_periodo", return_value=(True, "ok")), \
                mock.patch.object(core, "apply_filters"), \
                mock.patch.object(core, "analisar_canais_nao_verificados", return_value=[]) as falso_analise, \
                mock.patch.object(rec, "_ler_lateral_atual", return_value=("t", [])):
            page = mock.MagicMock()
            core.processar_termo(page, "termo x", 100, 0, recomendados_auto={"ativo": True})
        videos_para_analise = falso_analise.call_args[0][1]
        self.assertEqual({v["video_id"] for v in videos_para_analise}, {"buscaAAAA1"})

    def test_falha_ao_ler_a_lateral_de_um_video_nao_interrompe_o_termo(self):
        video_busca = {"video_id": "buscaAAAA1", "url": "https://www.youtube.com/watch?v=buscaAAAA1",
                       "titulo": "Vídeo achado", "canal": "Canal Base", "canal_url": "https://youtube.com/@base",
                       "canal_verificado": False, "views_num": 500, "views_text": "500", "duracao_segundos": 300, "data_publicacao": "2026-09-01"}
        with mock.patch.object(core, "build_search_url", return_value="https://busca"), \
                mock.patch.object(core, "collect_videos", return_value=[video_busca]), \
                mock.patch.object(core, "_filtrar_por_duracao", side_effect=lambda v, f: v), \
                mock.patch.object(core, "validar_video_no_periodo", return_value=(True, "ok")), \
                mock.patch.object(core, "apply_filters"), \
                mock.patch.object(core, "analisar_canais_nao_verificados", return_value=[]) as falso_analise, \
                mock.patch.object(rec, "_ler_lateral_atual", side_effect=RuntimeError("sem lateral")):
            page = mock.MagicMock()
            videos, ranked = core.processar_termo(page, "termo x", 100, 0, recomendados_auto={"ativo": True})
        # mesmo com a lateral falhando, o vídeo original da busca segue normalmente
        self.assertEqual({v["video_id"] for v in falso_analise.call_args[0][1]}, {"buscaAAAA1"})

    def test_sem_recomendados_auto_processar_termo_funciona_como_antes(self):
        video_busca = {"video_id": "buscaAAAA1", "url": "https://www.youtube.com/watch?v=buscaAAAA1",
                       "titulo": "Vídeo achado", "canal": "Canal Base", "canal_url": "https://youtube.com/@base",
                       "canal_verificado": False, "views_num": 500, "views_text": "500", "duracao_segundos": 300, "data_publicacao": "2026-09-01"}
        with mock.patch.object(core, "build_search_url", return_value="https://busca"), \
                mock.patch.object(core, "collect_videos", return_value=[video_busca]), \
                mock.patch.object(core, "_filtrar_por_duracao", side_effect=lambda v, f: v), \
                mock.patch.object(core, "validar_video_no_periodo", return_value=(True, "ok")), \
                mock.patch.object(core, "apply_filters"), \
                mock.patch.object(core, "analisar_canais_nao_verificados", return_value=[]) as falso_analise, \
                mock.patch.object(rec, "_ler_lateral_atual") as falso_ler:
            page = mock.MagicMock()
            core.processar_termo(page, "termo x", 100, 0)
        falso_ler.assert_not_called()
        self.assertEqual({v["video_id"] for v in falso_analise.call_args[0][1]}, {"buscaAAAA1"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
