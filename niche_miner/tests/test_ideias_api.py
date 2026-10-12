"""Rotas /api/ideias/* e jobs (radar e validação), sem navegador e sem rede.

O Playwright e as funções de coleta são trocados por dublês para exercitar o
fluxo inteiro: gravação no SQLite, log ao vivo, isolamento de falhas por termo,
bloqueio do Google e a trava de uma coleta por vez.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as webapp
import ideias
import ideias_api
import ideias_scraper as sc


class _Nav:
    def __init__(self):
        self.launch_args = None
        self.headless = None
        self.fechado = False

    def launch(self, headless=False, args=None):
        self.headless, self.launch_args = headless, args
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


def _video(vid, termo, canal, views, quando="há 5 dias", verificado=False):
    return {"video_id": vid, "titulo": f"Título {vid}", "url": f"https://www.youtube.com/watch?v={vid}", "canal": canal,
            "canal_url": f"https://youtube.com/@{canal}", "canal_verificado": verificado, "views_num": views, "quando": quando,
            "idade_dias": 5, "views_dia": round(views / 5, 1), "termo_busca": termo}


class ApiBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"NICHE_MINER_DB": os.path.join(self.tmp.name, "t.db")})
        env.start()
        self.addCleanup(env.stop)
        webapp.JOBS.clear()
        self.c = webapp.app.test_client()

    def post(self, url, corpo=None):
        r = self.c.post(url, json=corpo or {})
        return r.status_code, r.get_json()

    def criar(self, tema="Pragas", termos=None, mercado="BR"):
        _, j = self.post("/api/ideias/pesquisas", {"tema": tema, "mercado": mercado, "termos": ["mosquito", "barata"] if termos is None else termos})
        return j["pesquisa"]["id"]

    def esperar_job(self, job_id, limite=10):
        fim = time.time() + limite
        while time.time() < fim:
            j = webapp.JOBS[job_id]
            if j["status"] in ("concluido", "erro"):
                return j
            time.sleep(0.05)
        self.fail("job não terminou a tempo")

    def semear_radar(self, pid, videos):
        def f(e):
            e["radar"] = {"videos": videos, "resumo": [], "falhas": [], "mercado": "BR"}
            e["radar_selecao"] = [v["video_id"] for v in videos]
            return e
        ideias.mutar_pesquisa(pid, f)


class CrudTests(ApiBase):
    def test_criar_listar_obter_config_excluir(self):
        pid = self.criar()
        self.assertEqual(self.c.get("/api/ideias/pesquisas").get_json()["pesquisas"][0]["tema"], "Pragas")
        self.assertEqual(self.c.get(f"/api/ideias/pesquisas/{pid}").get_json()["pesquisa"]["termos"], ["mosquito", "barata"])
        r = self.c.patch(f"/api/ideias/pesquisas/{pid}", json={"termos": ["a", "b", "c"], "mercado": "DE"})
        self.assertEqual((r.get_json()["pesquisa"]["termos"], r.get_json()["pesquisa"]["mercado"]), (["a", "b", "c"], "DE"))
        self.assertEqual(self.c.delete(f"/api/ideias/pesquisas/{pid}").status_code, 200)
        self.assertEqual(self.c.get(f"/api/ideias/pesquisas/{pid}").status_code, 404)
        self.assertEqual(self.c.patch("/api/ideias/pesquisas/999", json={}).status_code, 404)

    def test_tema_vazio_e_400(self):
        status, j = self.post("/api/ideias/pesquisas", {"tema": " "})
        self.assertEqual(status, 400)
        self.assertIn("tema", j["erro"])

    def test_mercados_e_padroes_para_a_interface(self):
        j = self.c.get("/api/ideias/mercados").get_json()
        self.assertIn("BR", [m["codigo"] for m in j["mercados"]])
        self.assertEqual(set(j["pesos_padrao"]), set(ideias.CRITERIOS))
        self.assertIn("corte_final", j["limiares_padrao"])

    def test_decidir_canal(self):
        _, j = self.post("/api/ideias/decidir-canal", {"n_videos": 31, "impressoes": 100, "ctr": 1})
        self.assertEqual(j["decisao"]["veredito"], "descartar")


class IaTests(ApiBase):
    def test_prompt_decompor_guarda_a_ordem_para_mapear_a_resposta(self):
        pid = self.criar()
        vids = [_video(f"v{i}", "mosquito", f"c{i}", 1000 * i) for i in range(1, 6)]
        self.semear_radar(pid, vids)
        status, j = self.post(f"/api/ideias/pesquisas/{pid}/prompt/decompor", {"video_ids": ["v3", "v1", "nao_existe"], "refs_extra": ["Título de fora"]})
        self.assertEqual(status, 200)
        self.assertIn('1. "Título v3"', j["prompt"])
        self.assertIn('2. "Título v1"', j["prompt"])
        self.assertIn('3. "Título de fora"', j["prompt"])
        base = ideias.obter_pesquisa(pid)["decomposicao_base"]
        self.assertEqual([(b["indice"], b["video_id"]) for b in base], [(1, "v3"), (2, "v1"), (3, None)])

        resp = {"videos": [{"indice": 1, "emocao": "a"}, {"indice": 3, "emocao": "b"}, {"indice": 7, "emocao": "fora"}],
                "padroes": [{"nome": "P"}]}
        status, j = self.post(f"/api/ideias/pesquisas/{pid}/colar/decompor", {"texto": json.dumps(resp)})
        self.assertEqual((status, j["resumo"]), (200, {"videos": 2, "padroes": 1}))
        self.assertEqual([v["indice"] for v in j["pesquisa"]["decomposicao"]["videos"]], [1, 3])

    def test_prompt_decompor_sem_video_nem_referencia_e_400(self):
        pid = self.criar()
        status, j = self.post(f"/api/ideias/pesquisas/{pid}/prompt/decompor")
        self.assertEqual(status, 400)
        self.assertIn("vídeos", j["erro"])

    def test_prompt_de_ideias_usa_os_padroes_importados(self):
        pid = self.criar()
        ideias.mutar_pesquisa(pid, lambda e: e.update(decomposicao={"videos": [], "padroes": [{"nome": "Padrão Ouro", "emocao": "surpresa", "estrutura": "E"}]}) or e)
        _, j = self.post(f"/api/ideias/pesquisas/{pid}/prompt/ideias", {"n": 4, "modo": "outro_mercado", "mercados_alvo": ["DE"]})
        for trecho in ("Padrão Ouro", "DE = Alemanha", "Gere 4 ideias"):
            self.assertIn(trecho, j["prompt"])

    def test_prompt_de_expansao_usa_o_foco(self):
        pid = self.criar()
        _, j = self.post(f"/api/ideias/pesquisas/{pid}/prompt/expandir", {"foco": "carros automáticos"})
        self.assertIn("carros automáticos", j["prompt"])

    def test_colar_ideias_soma_sem_duplicar_e_pontua(self):
        pid = self.criar()
        texto = json.dumps({"ideias": [{"titulo_amplo": "A", "amplitude": 4, "repetibilidade": 4, "producao": 4}, {"titulo_amplo": "B", "amplitude": 2}]})
        _, j = self.post(f"/api/ideias/pesquisas/{pid}/colar/ideias", {"texto": texto})
        self.assertEqual(j["resumo"], {"lidas": 2, "novas": 2, "total": 2})
        self.assertEqual([i["titulo_amplo"] for i in sorted(j["pesquisa"]["ideias"], key=lambda i: i["rank"])], ["A", "B"])
        _, j2 = self.post(f"/api/ideias/pesquisas/{pid}/colar/ideias", {"texto": texto})
        self.assertEqual(j2["resumo"], {"lidas": 2, "novas": 0, "total": 2})

    def test_json_invalido_e_400_e_nao_altera_o_estado(self):
        pid = self.criar()
        for tipo in ("decompor", "expandir", "ideias"):
            status, j = self.post(f"/api/ideias/pesquisas/{pid}/colar/{tipo}", {"texto": "conversa sem json"})
            self.assertEqual(status, 400, tipo)
            self.assertIn("JSON", j["erro"])
        self.assertEqual(ideias.obter_pesquisa(pid)["ideias"], [])
        self.assertEqual(self.post(f"/api/ideias/pesquisas/{pid}/colar/xyz", {"texto": "{}"})[0], 404)
        self.assertEqual(self.post("/api/ideias/pesquisas/999/prompt/ideias")[0], 404)

    def test_editar_ideia_pela_rota(self):
        pid = self.criar()
        _, j = self.post(f"/api/ideias/pesquisas/{pid}/colar/ideias", {"texto": '{"ideias": [{"titulo_amplo": "A", "amplitude": 1}]}'})
        iid = j["pesquisa"]["ideias"][0]["id"]
        r = self.c.patch(f"/api/ideias/pesquisas/{pid}/ideias/{iid}", json={"amplitude": 5, "descartada": True})
        i = r.get_json()["pesquisa"]["ideias"][0]
        self.assertEqual((i["amplitude"], i["descartada"], i["rank"]), (5.0, True, None))
        self.assertEqual(self.c.patch(f"/api/ideias/pesquisas/{pid}/ideias/xxxx", json={}).status_code, 404)

    def test_csv(self):
        pid = self.criar()
        self.post(f"/api/ideias/pesquisas/{pid}/colar/ideias", {"texto": '{"ideias": [{"titulo_amplo": "Título Ç"}]}'})
        r = self.c.get(f"/api/ideias/pesquisas/{pid}/ideias.csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith("\ufeff".encode("utf-8")))
        self.assertIn("Título Ç", r.data.decode("utf-8"))
        self.assertEqual(self.c.get("/api/ideias/pesquisas/999/ideias.csv").status_code, 404)


class RadarJobTests(ApiBase):
    def rodar(self, corpo, pid, coletar, inscritos=None):
        pw = _FakePW()
        inscritos = inscritos or (lambda page, videos, k, cache, log=print: cache.update({"https://youtube.com/@pequeno": {"inscritos_num": 1000, "n_videos_canal": 8}}))
        with mock.patch.object(ideias_api, "sync_playwright", lambda: pw), \
             mock.patch.object(sc, "coletar_videos_termo", coletar), \
             mock.patch.object(sc, "coletar_inscritos", inscritos):
            status, j = self.post(f"/api/ideias/pesquisas/{pid}/radar", corpo)
            self.assertEqual(status, 200, j)
            job = self.esperar_job(j["job_id"])
        return job, pw

    def test_radar_salva_dedupe_razao_e_isola_falhas(self):
        pid = self.criar(termos=[])

        def coletar(page, termo, cod, filtros, max_videos, log=print):
            if termo == "quebra":
                raise RuntimeError("página mudou")
            print(f"coletando {termo}")
            base = [_video("comum", termo, "outro", 500), _video("grande", termo, "pequeno", 50000)]
            return base if termo == "a" else base + [_video("so_b", termo, "x", 10)]

        job, pw = self.rodar({"termos": ["a", "quebra", "b"], "data_periodo": "semana", "top_canais": 5, "headless": True, "mutar_audio": True}, pid, coletar)
        self.assertEqual(job["status"], "concluido", job.get("erro"))
        log = "\n".join(job["logs"])
        self.assertIn("Falha isolada no termo 'quebra'", log)
        self.assertIn("coletando b", log)
        self.assertEqual(job["resultado"], {"videos": 3, "falhas": 1})
        self.assertEqual((pw.chromium.headless, pw.chromium.launch_args, pw.chromium.fechado), (True, ["--mute-audio"], True))

        e = ideias.obter_pesquisa(pid)
        por_id = {v["video_id"]: v for v in e["radar"]["videos"]}
        self.assertEqual(set(por_id), {"comum", "grande", "so_b"})
        self.assertEqual(por_id["comum"]["termos"], ["a", "b"])           # o mesmo vídeo achado em 2 termos
        self.assertEqual(por_id["grande"]["razao_views_inscritos"], 50.0)  # 50.000 views / 1.000 inscritos
        self.assertEqual(e["radar"]["videos"][0]["video_id"], "grande")    # outlier no topo
        self.assertEqual(e["radar_selecao"][0], "grande")
        self.assertEqual(e["termos"], ["a", "quebra", "b"])
        self.assertEqual(len(e["radar"]["falhas"]), 1)
        self.assertEqual(e["radar"]["filtros"]["data_periodo"], "semana")

    def test_radar_sem_termos_da_erro_claro(self):
        pid = self.criar(termos=[])
        job, _ = self.rodar({"termos": []}, pid, lambda *a, **k: [])
        self.assertEqual(job["status"], "erro")
        self.assertIn("termo", job["erro"])

    def test_top_canais_zero_nao_le_inscritos(self):
        pid = self.criar()
        chamou = []
        job, _ = self.rodar({"termos": ["a"], "top_canais": 0}, pid, lambda *a, **k: [_video("v", "a", "c", 10)],
                            inscritos=lambda *a, **k: chamou.append(1))
        self.assertEqual(job["status"], "concluido")
        self.assertEqual(chamou, [])

    def test_navegador_e_fechado_mesmo_com_erro_no_meio(self):
        pid = self.criar()
        job, pw = self.rodar({"termos": ["a"], "top_canais": 3}, pid, lambda *a, **k: [_video("v", "a", "c", 10)],
                             inscritos=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertEqual(job["status"], "erro")
        self.assertTrue(pw.chromium.fechado)


class ValidacaoJobTests(ApiBase):
    def preparar(self):
        pid = self.criar()
        texto = json.dumps({"ideias": [
            {"titulo_amplo": "Ideia BR", "mercado": "BR", "termos_validacao": ["t br 1", "t br 2", "t br 3", "t br 4"], "amplitude": 4, "repetibilidade": 4, "producao": 4},
            {"titulo_amplo": "Ideia DE", "mercado": "DE", "termos_validacao": ["t de"], "amplitude": 3},
            {"titulo_amplo": "Sem termos", "mercado": "BR"}]})
        _, j = self.post(f"/api/ideias/pesquisas/{pid}/colar/ideias", {"texto": texto})
        return pid, {i["titulo_amplo"]: i["id"] for i in j["pesquisa"]["ideias"]}

    def rodar(self, pid, cfg, serp=None, trends=None, yt=None):
        pw = _FakePW()
        chamadas = {"serp": [], "sug": [], "yt": [], "trends": []}

        def sug(fetch, termo, cod, alfabeto=False, pausa=0):
            chamadas["sug"].append((termo, cod, alfabeto))
            return {"google": [f"{termo} {c}" for c in "abc"], "youtube": ["y1"]}

        def serp_(page, termo, cod):
            chamadas["serp"].append(termo)
            return (serp or (lambda t: {"status": "ok", "paa": [f"{t}?"], "relacionadas": ["rel"]}))(termo)

        def yt_(page, termo, cod, filtros, max_videos, log=print):
            chamadas["yt"].append((termo, filtros["data_periodo"]))
            return [_video(f"{termo}{i}", termo, f"c{i % 10}", 1000 * (i + 1)) for i in range(12)]

        def trends_(termos, geo="", periodo="", gprop="", log=print, **kw):
            chamadas["trends"].append((list(termos), geo, periodo, gprop))
            if trends is not None:
                return trends
            return {"disponivel": True, "motivo": "", "termos": {t: {"nivel": 50.0, "media": 50.0, "tendencia": "subindo", "perfil": "evergreen", "serie": [1]} for t in termos}}

        with mock.patch.object(ideias_api, "sync_playwright", lambda: pw), \
             mock.patch.object(sc, "fetch_por_contexto", lambda ctx: (lambda url: "")), \
             mock.patch.object(sc, "coletar_sugestoes", sug), mock.patch.object(sc, "coletar_serp_google", serp_), \
             mock.patch.object(sc, "coletar_videos_termo", yt_), mock.patch.object(ideias, "coletar_trends", trends_):
            status, j = self.post(f"/api/ideias/pesquisas/{pid}/validar", cfg)
            if status != 200:
                return status, j, None, chamadas, pw
            return status, j, self.esperar_job(j["job_id"]), chamadas, pw

    def test_validacao_completa_grava_sinais_e_pontua(self):
        pid, ids = self.preparar()
        status, _, job, ch, pw = self.rodar(pid, {"ideia_ids": [ids["Ideia BR"], ids["Ideia DE"], ids["Sem termos"]], "trends_fonte": "youtube",
                                                  "trends_periodo": "today 5-y", "data_periodo": "ano", "alfabeto": True, "headless": True})
        self.assertEqual(job["status"], "concluido", job.get("erro"))
        # no máximo 3 termos por ideia; ideia sem termos é ignorada
        self.assertEqual([t for t, *_ in ch["sug"]], ["t br 1", "t br 2", "t br 3", "t de"])
        self.assertTrue(all(a for *_, a in ch["sug"]))                       # alfabeto repassado
        self.assertEqual(set(p for _, p in ch["yt"]), {"ano"})               # período repassado
        self.assertEqual(sorted(ch["trends"], key=lambda x: x[1]), [(["t br 1", "t br 2", "t br 3"], "BR", "today 5-y", "youtube"), (["t de"], "DE", "today 5-y", "youtube")])
        self.assertTrue(pw.chromium.fechado)

        e = ideias.obter_pesquisa(pid)
        self.assertEqual(len(e["validacao"]), 4)
        br = next(i for i in e["ideias"] if i["titulo_amplo"] == "Ideia BR")
        self.assertEqual(br["sinais"]["termos_validados"], 3)
        self.assertEqual(br["sinais"]["trends_tendencia"], "subindo")
        self.assertEqual(br["confianca"], 1.0)
        self.assertIsNotNone(br["criterios"]["demanda"])
        self.assertIsNotNone(br["criterios"]["concorrencia"])
        sem = next(i for i in e["ideias"] if i["titulo_amplo"] == "Sem termos")
        self.assertEqual(sem["sinais"], {})

    def test_google_bloqueado_pula_serp_nos_demais_termos(self):
        pid, ids = self.preparar()
        _, _, job, ch, _ = self.rodar(pid, {"ideia_ids": [ids["Ideia BR"]], "trends": False, "yt": False},
                                      serp=lambda t: {"status": "bloqueado", "paa": [], "relacionadas": []})
        self.assertEqual(job["status"], "concluido")
        self.assertEqual(len(ch["serp"]), 1)                                  # só a primeira tentativa
        self.assertTrue(job["resultado"]["serp_bloqueada"])
        self.assertIn("pulando a SERP", "\n".join(job["logs"]))
        status = {r["termo"]: r["serp_status"] for r in ideias.obter_pesquisa(pid)["validacao"].values()}
        self.assertEqual(status, {"t br 1": "bloqueado", "t br 2": "pulado", "t br 3": "pulado"})

    def test_trends_indisponivel_nao_derruba_e_deixa_link_manual(self):
        pid, ids = self.preparar()
        _, _, job, _, _ = self.rodar(pid, {"ideia_ids": [ids["Ideia DE"]], "serp": False, "yt": False, "sugestoes": False},
                                     trends={"disponivel": False, "motivo": "pytrends não instalado (pip install pytrends)", "termos": {}})
        self.assertEqual(job["status"], "concluido")
        self.assertIn("pytrends", job["resultado"]["trends_motivo"])
        reg = next(iter(ideias.obter_pesquisa(pid)["validacao"].values()))
        self.assertIsNone(reg["trends"])
        self.assertIn("trends.google.com", reg["trends_url"])
        self.assertIn("geo=DE", reg["trends_url"])

    def test_sem_nenhuma_fonte_de_navegador_nao_abre_o_chromium(self):
        pid, ids = self.preparar()
        _, _, job, _, pw = self.rodar(pid, {"ideia_ids": [ids["Ideia DE"]], "sugestoes": False, "serp": False, "yt": False, "trends": False})
        self.assertEqual(job["status"], "concluido")
        self.assertIsNone(pw.chromium.headless)

    def test_validar_exige_ideias_e_termos(self):
        pid, ids = self.preparar()
        self.assertEqual(self.post(f"/api/ideias/pesquisas/{pid}/validar", {"ideia_ids": []})[0], 400)
        _, _, job, _, _ = self.rodar(pid, {"ideia_ids": [ids["Sem termos"]]})
        self.assertEqual(job["status"], "erro")
        self.assertIn("termos de validação", job["erro"])


class TravaDeJobUnicoTests(ApiBase):
    def test_segundo_job_e_recusado_e_minerar_tambem(self):
        pid = self.criar()
        webapp.JOBS["ocupado"] = {"status": "rodando", "logs": [], "resultado": None, "erro": None}
        status, j = self.post(f"/api/ideias/pesquisas/{pid}/radar", {"termos": ["a"]})
        self.assertEqual(status, 409)
        self.assertIn("em andamento", j["erro"])
        status, j = self.post("/api/iniciar", {"termos": ["a"]})
        self.assertEqual(status, 409)
        webapp.JOBS["ocupado"]["status"] = "concluido"
        with mock.patch.object(webapp, "rodar_pipeline"):
            self.assertEqual(self.post("/api/iniciar", {"termos": ["a"]})[0], 200)

    def test_job_com_status_rodando_mas_thread_morta_nao_bloqueia(self):
        import threading
        morta = threading.Thread(target=lambda: None)
        morta.start()
        morta.join()
        webapp.JOBS["travado"] = {"status": "rodando", "logs": [], "resultado": None, "erro": None, "thread": morta}
        self.assertFalse(ideias_api.ha_job_ativo(webapp.JOBS))
        webapp.JOBS["travado"]["thread"] = threading.Thread(target=lambda: None)   # criada e ainda não iniciada
        self.assertTrue(ideias_api.ha_job_ativo(webapp.JOBS))

    def test_job_novo_registra_a_thread_para_a_trava(self):
        pid = self.criar()
        with mock.patch.object(ideias_api, "sync_playwright", lambda: _FakePW()), \
             mock.patch.object(sc, "coletar_videos_termo", lambda *a, **k: []):
            _, j = self.post(f"/api/ideias/pesquisas/{pid}/radar", {"termos": ["a"], "top_canais": 0})
            self.assertIn("thread", webapp.JOBS[j["job_id"]])
            self.esperar_job(j["job_id"])

    def test_logs_do_job_usam_a_mesma_rota_da_aba_minerar(self):
        pid = self.criar()
        with mock.patch.object(ideias_api, "sync_playwright", lambda: _FakePW()), \
             mock.patch.object(sc, "coletar_videos_termo", lambda *a, **k: (print("linha de log"), [])[1]):
            _, j = self.post(f"/api/ideias/pesquisas/{pid}/radar", {"termos": ["a"], "top_canais": 0})
            self.esperar_job(j["job_id"])
        r = self.c.get(f"/api/logs/{j['job_id']}?cursor=0").get_json()
        self.assertEqual(r["status"], "concluido")
        self.assertIn("linha de log", r["logs"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
