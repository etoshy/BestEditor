"""Rotas /api/yt/*: fluxo completo servidor -> cliente da API (falsa), erros, chave e miniatura."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as webapp
import fake_yt_api as F
import yt_api as Y
import yt_rotas

V = F.vid_id


class Base(unittest.TestCase):
    def setUp(self):
        self.f = F.mundo()
        for alvo, novo in ((Y, "_urlopen"), (yt_rotas, "_agora")):
            p = mock.patch.object(alvo, novo, self.f if novo == "_urlopen" else (lambda: F.AGORA))
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("YOUTUBE_API_KEY", None)
        self.c = webapp.app.test_client()

    def post(self, url, corpo=None, com_chave=True):
        corpo = dict(corpo or {})
        if com_chave:
            corpo.setdefault("chave", F.CHAVE)
        r = self.c.post(url, json=corpo)
        return r.status_code, r.get_json(), r.get_data(as_text=True)


class ConfigEChaveTests(Base):
    def test_config_informa_se_a_chave_esta_no_ambiente_e_os_custos(self):
        j = self.c.get("/api/yt/config").get_json()
        self.assertEqual((j["chave_no_ambiente"], j["custos"]["search"], j["custos"]["videos"]), (False, 100, 1))
        os.environ["YOUTUBE_API_KEY"] = F.CHAVE
        self.assertTrue(self.c.get("/api/yt/config").get_json()["chave_no_ambiente"])

    def test_chave_do_ambiente_vale_quando_o_corpo_nao_traz(self):
        os.environ["YOUTUBE_API_KEY"] = F.CHAVE
        status, j, _ = self.post("/api/yt/canal", {"canal": "@alfa"}, com_chave=False)
        self.assertEqual((status, j["canal"]["id"]), (200, F.uc("a")))

    def test_sem_chave_chave_errada_cota_e_rede(self):
        status, j, _ = self.post("/api/yt/canal", {"canal": "@alfa"}, com_chave=False)
        self.assertEqual((status, j["razao"]), (400, "sem_chave"))
        status, j, _ = self.post("/api/yt/canal", {"canal": "@alfa", "chave": "AIzaChaveErrada1234567890abcdefghijk"})
        self.assertEqual((status, j["razao"]), (400, "badRequest"))
        self.assertIn("Chave da API inválida", j["erro"])
        self.f.cota = 0
        status, j, _ = self.post("/api/yt/canal", {"canal": "@alfa"})
        self.assertEqual(status, 429)
        self.assertIn("cota diária", j["erro"])
        self.f.cota, self.f.falha_rede = 100, True
        status, j, _ = self.post("/api/yt/canal", {"canal": "@alfa"})
        self.assertEqual((status, j["razao"]), (502, "rede"))

    def test_a_chave_nunca_volta_na_resposta_nem_nos_erros(self):
        respostas = [self.post("/api/yt/canal", {"canal": "@alfa"}), self.post("/api/yt/canal", {"canal": "@nao_existe_mesmo"}),
                     self.post("/api/yt/video", {"video": "lixo"}), self.post("/api/yt/pesquisar", {"q": "x", "de": "ontem"})]
        self.f.erro_forcado = ("channels", 500, f"falha com {F.CHAVE}", "backendError")
        respostas.append(self.post("/api/yt/canal", {"canal": F.uc("a")}))
        for status, j, texto in respostas:
            self.assertNotIn(F.CHAVE, texto)

    def test_corpo_que_nao_e_json_nao_derruba(self):
        r = self.c.post("/api/yt/canal", data="isso nao e json", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.get_json()["ok"])

    def test_erro_inesperado_vira_500_sem_detalhes_e_a_chave_nao_vai_para_o_log(self):
        with mock.patch.object(Y, "analisar_canal", side_effect=RuntimeError(f"segredo {F.CHAVE}")):
            with self.assertLogs("yt_rotas", level="ERROR") as cap:
                status, j, texto = self.post("/api/yt/canal", {"canal": "@alfa"})
        self.assertEqual((status, j["razao"]), (500, "interno"))
        self.assertNotIn("segredo", texto)
        self.assertNotIn(F.CHAVE, texto)
        log = "\n".join(cap.output)
        self.assertIn("RuntimeError", log)
        self.assertNotIn(F.CHAVE, log)
        self.assertIn("***", log)
        self.assertIsNone(cap.records[0].exc_info)                             # sem traceback: a mensagem original não vai para o terminal

    def test_valueerror_com_a_chave_na_mensagem_sai_mascarado(self):
        with mock.patch.object(Y, "analisar_canal", side_effect=ValueError(f"url ruim ...?key={F.CHAVE}")):
            status, j, texto = self.post("/api/yt/canal", {"canal": "@alfa"})
        self.assertEqual(status, 400)
        self.assertNotIn(F.CHAVE, texto)
        self.assertIn("key=***", j["erro"])


class FerramentasTests(Base):
    def test_pesquisar_por_palavra_chave(self):
        status, j, _ = self.post("/api/yt/pesquisar", {"q": "estoicismo", "pais": "BR", "idioma": "pt", "quantidade": 10})
        self.assertEqual(status, 200)
        self.assertEqual([v["id"] for v in j["videos"]], [V(2), V(4), V(8), V(12), V(1)])
        self.assertEqual((j["unidades"], j["params"]["assumiu_7_dias"], j["params"]["publicado_depois"]), (102, True, "2026-09-14T00:00:00Z"))
        self.assertEqual(sorted(j["canais"]), sorted([F.uc("a"), F.uc("b"), F.uc("c")]))

    def test_pesquisar_vazio_cai_no_em_alta_filtrado_e_erros_de_entrada_sao_400(self):
        status, j, _ = self.post("/api/yt/pesquisar", {})
        self.assertEqual((status, j["params"]["modo"], j["unidades"]), (200, "em_alta", 2))
        for ruim, trecho in (({"de": "ontem"}, "Data inválida"), ({"de": "2026-09-10", "ate": "2026-09-01"}, "depois da data final")):
            status, j, _ = self.post("/api/yt/pesquisar", ruim)
            self.assertEqual(status, 400)
            self.assertIn(trecho, j["erro"])

    def test_em_alta(self):
        status, j, _ = self.post("/api/yt/em-alta", {"pais": "BR", "categoria": "27"})
        self.assertEqual((status, [v["id"] for v in j["videos"]], j["unidades"]), (200, [V(12), V(4), V(2)], 2))
        status, j, _ = self.post("/api/yt/em-alta", {"pais": "ZZ"})
        self.assertEqual(status, 400)
        self.assertIn("lista de vídeos em alta", j["erro"])

    def test_comparar(self):
        status, j, _ = self.post("/api/yt/comparar", {"a": "@alfa", "b": "@beta"})
        self.assertEqual((status, j["unidades"], len(j["comparacao"])), (200, 7, 11))
        self.assertEqual(j["a"]["recentes"]["mediana_views"], 7500)
        status, j, _ = self.post("/api/yt/comparar", {"a": "@alfa", "b": F.uc("a")})
        self.assertEqual(status, 400)
        self.assertIn("dois canais diferentes", j["erro"])
        status, j, _ = self.post("/api/yt/comparar", {"a": "@alfa"})
        self.assertEqual(status, 400)

    def test_canal_video_e_historico(self):
        status, j, _ = self.post("/api/yt/canal", {"canal": "https://www.youtube.com/@gama"})
        self.assertEqual((status, j["canal"]["inscritos"], j["canal"]["inscritos_ocultos"]), (200, None, True))
        status, j, _ = self.post("/api/yt/video", {"video": f"https://youtu.be/{V(2)}"})
        self.assertEqual((status, j["video"]["duracao_seg"], j["video"]["thumb"].endswith("maxres.jpg")), (200, 600, True))
        status, j, _ = self.post("/api/yt/video", {"video": "não é link"})
        self.assertEqual(status, 400)
        status, j, _ = self.post("/api/yt/video", {"video": "vid99999999"})
        self.assertEqual(status, 404)
        status, j, _ = self.post("/api/yt/historico", {"canal": "@alfa", "n": 30})
        self.assertEqual((status, len(j["videos"]), j["unidades"]), (200, 6, 4))
        for n, esperado in ((999, "50"), ("abc", "30"), (0, "30"), (-3, "1")):
            self.f.chamadas.clear()
            self.post("/api/yt/historico", {"canal": F.uc("a"), "n": n})
            self.assertEqual(self.f.por_recurso("playlistItems")[0]["maxResults"], esperado, n)


class IaTests(Base):
    def test_prompt_de_cada_tipo_a_partir_dos_dados_devolvidos_pelas_rotas(self):
        em_alta = self.post("/api/yt/em-alta", {"pais": "BR"})[1]
        comp = self.post("/api/yt/comparar", {"a": "@alfa", "b": "@beta"})[1]
        canal = self.post("/api/yt/canal", {"canal": "@alfa"})[1]
        video = self.post("/api/yt/video", {"video": V(2)})[1]
        hist = self.post("/api/yt/historico", {"canal": "@alfa"})[1]
        casos = {"oportunidades": (em_alta, "nichos_em_alta"), "comparativo": (comp, "CANAL B"), "dossie": (canal, "Palavras-chave do canal"),
                 "engenharia": (video, "SEM TRANSCRIÇÃO"), "auditoria": (hist, "do mais antigo ao mais novo")}
        for tipo, (dados, trecho) in casos.items():
            status, j, _ = self.post(f"/api/yt/prompt/{tipo}", {"dados": dados, "contexto": "meu contexto"}, com_chave=False)
            self.assertEqual(status, 200, tipo)
            self.assertIn(trecho, j["prompt"], tipo)
            self.assertIn("meu contexto", j["prompt"], tipo)

    def test_engenharia_leva_a_transcricao_colada(self):
        video = self.post("/api/yt/video", {"video": V(2)})[1]
        j = self.post("/api/yt/prompt/engenharia", {"dados": video, "transcricao": "Olá, bem-vindos ao canal"}, com_chave=False)[1]
        self.assertIn("Transcrição do vídeo:\nOlá, bem-vindos", j["prompt"])

    def test_dados_ruins_dao_400_e_nunca_500(self):
        for tipo in ("oportunidades", "comparativo", "dossie", "engenharia", "auditoria"):
            for lixo in (None, {}, [], "texto", 5, {"videos": "x", "a": 1, "b": [], "canal": "x", "video": 3}):
                status, j, _ = self.post(f"/api/yt/prompt/{tipo}", {"dados": lixo}, com_chave=False)
                self.assertEqual(status, 400, (tipo, lixo))
                self.assertFalse(j["ok"])

    def test_tipo_desconhecido_e_404(self):
        self.assertEqual(self.post("/api/yt/prompt/outro", {"dados": {}}, com_chave=False)[0], 404)
        self.assertEqual(self.post("/api/yt/ia/outro", {"texto": "{}"}, com_chave=False)[0], 404)

    def test_aplicar_resposta_valida_e_limita_os_indices_ao_tamanho_da_lista(self):
        texto = json.dumps({"leitura_geral": "Roma em alta", "nichos_em_alta": [{"nicho": "Roma", "evidencia": [1, 2, 9]}]})
        status, j, _ = self.post("/api/yt/ia/oportunidades", {"texto": texto, "n_videos": 5}, com_chave=False)
        self.assertEqual(status, 200)
        self.assertEqual(j["resultado"]["nichos_em_alta"][0]["evidencia"], [1, 2])
        status, j, _ = self.post("/api/yt/ia/auditoria", {"texto": json.dumps({"fases": [{"periodo": "a", "o_que_aconteceu": "b", "evidencia": [3, 40]}]}), "n_videos": 30}, com_chave=False)
        self.assertEqual(j["resultado"]["fases"][0]["evidencia"], [3])
        status, j, _ = self.post("/api/yt/ia/dossie", {"texto": json.dumps({"resumo": "ok"})}, com_chave=False)
        self.assertEqual((status, j["resultado"]["resumo"]), (200, "ok"))

    def test_resposta_ruim_da_ia_da_400_com_mensagem(self):
        for tipo in ("oportunidades", "comparativo", "dossie", "engenharia", "auditoria"):
            for lixo in ("", "isso não é json", "{}"):
                status, j, _ = self.post(f"/api/yt/ia/{tipo}", {"texto": lixo}, com_chave=False)
                self.assertEqual(status, 400, (tipo, lixo))
                self.assertTrue(j["erro"])


class MiniaturaTests(Base):
    def test_baixa_a_maior_resolucao_como_anexo(self):
        r = self.c.get(f"/api/yt/miniatura?video={V(2)}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["X-Resolucao"], "maxresdefault")
        self.assertEqual(r.headers["Content-Disposition"], f'attachment; filename="{V(2)}_maxresdefault.jpg"')
        self.assertEqual(r.mimetype, "image/jpeg")
        self.assertTrue(r.data.startswith(b"\xff\xd8\xff"))
        self.assertEqual(self.c.get(f"/api/yt/miniatura?video={V(4)}").headers["X-Resolucao"], "hqdefault")

    def test_erros_e_nao_aceita_url_qualquer(self):
        self.assertEqual(self.c.get(f"/api/yt/miniatura?video={V(5)}").status_code, 404)
        for ruim in ("", "curto", "../../etc/passwd", "http://evil.example/x"):
            r = self.c.get("/api/yt/miniatura", query_string={"video": ruim})
            self.assertEqual(r.status_code, 400, ruim)
        self.f.chamadas.clear()
        r = self.c.get("/api/yt/miniatura", query_string={"video": V(2), "url": "http://evil.example/x.jpg"})           # parâmetro extra é ignorado
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
