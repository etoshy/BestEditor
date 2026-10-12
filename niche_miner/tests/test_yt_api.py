"""yt_api.py contra a API falsa (tests/fake_yt_api.py): custo de cota, erros, parsers e as seis ferramentas."""
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_yt_api as F
import yt_api as Y

A, B, C = F.uc("a"), F.uc("b"), F.uc("c")
V = F.vid_id


class Base(unittest.TestCase):
    def setUp(self):
        self.f = F.mundo()
        p = mock.patch.object(Y, "_urlopen", self.f)
        p.start()
        self.addCleanup(p.stop)

    def cli(self):
        return Y.Cliente(F.CHAVE)


class ClienteTests(Base):
    def test_chave_ausente_ou_malformada(self):
        for ruim in ("", "   ", None, "com espaço no meio 1234", "curta"):
            with self.assertRaises(Y.YTErro, msg=repr(ruim)):
                Y.Cliente(ruim)

    def test_url_leva_a_chave_e_os_parametros_e_ignora_vazios(self):
        self.cli().get("videos", part="snippet", id=[V(1), V(2)], chart="", maxResults=None)
        recurso, p = self.f.chamadas[0]
        self.assertEqual((recurso, p["id"], p["part"]), ("videos", f"{V(1)},{V(2)}", "snippet"))
        self.assertNotIn("chart", p)
        self.assertNotIn("maxResults", p)

    def test_custo_de_cota_por_recurso(self):
        c = self.cli()
        c.get("search", part="snippet", type="video", q="x")
        c.get("videos", part="snippet", id=V(1))
        c.get("channels", part="snippet", id=A)
        c.get("playlistItems", part="contentDetails", playlistId="UU" + A[2:])
        self.assertEqual(c.unidades, 100 + 1 + 1 + 1)
        self.assertEqual(c.unidades, self.f.unidades_gastas())

    def test_chamada_com_erro_nao_soma_unidades(self):
        c = Y.Cliente("AIzaOutraChaveQualquer1234567890")
        with self.assertRaises(Y.YTErro):
            c.get("videos", part="snippet", id=V(1))
        self.assertEqual(c.unidades, 0)

    def test_erros_da_api_viram_mensagens_em_portugues_com_status(self):
        casos = [
            (F._http_erro("u", 403, "You have exceeded your quota", "quotaExceeded"), 429, "cota diária"),
            (F._http_erro("u", 400, "API key not valid", "badRequest", detalhes="API_KEY_INVALID"), 400, "Chave da API inválida"),
            (F._http_erro("u", 403, "YouTube Data API v3 has not been used in project 123 before or it is disabled", "accessNotConfigured"), 403, "não está ativada"),
            (F._http_erro("u", 400, "chart not supported", "videoChartNotFound"), 400, "lista de vídeos em alta"),
            (F._http_erro("u", 404, "nope", "playlistNotFound"), 404, "Não encontrei isso"),
            (F._http_erro("u", 403, "blocked", "forbidden"), 403, "bloqueada"),
            (F._http_erro("u", 500, "backend error", "backendError"), 502, "Erro da API do YouTube (500)"),
        ]
        for exc, status, trecho in casos:
            self.f.erro_forcado = None
            with mock.patch.object(Y, "_urlopen", mock.Mock(side_effect=exc)):
                with self.assertRaises(Y.YTErro) as cm:
                    self.cli().get("videos", part="snippet", id=V(1))
            self.assertEqual(cm.exception.status, status, trecho)
            self.assertIn(trecho, cm.exception.mensagem)

    def test_a_chave_nunca_aparece_em_mensagem_de_erro(self):
        exc = F._http_erro("u", 500, f"falha com key={F.CHAVE} no meio", "backendError")
        with mock.patch.object(Y, "_urlopen", mock.Mock(side_effect=exc)):
            with self.assertRaises(Y.YTErro) as cm:
                self.cli().get("videos", part="snippet", id=V(1))
        self.assertNotIn(F.CHAVE, cm.exception.mensagem)
        self.assertIn("***", cm.exception.mensagem)

    def test_falha_de_rede_e_resposta_ilegivel(self):
        self.f.falha_rede = True
        with self.assertRaisesRegex(Y.YTErro, "sem conexão") as cm:
            self.cli().get("videos", part="snippet", id=V(1))
        self.assertEqual(cm.exception.status, 502)
        lixo = mock.Mock(return_value=F._Resp(b"<html>nao e json</html>"))
        with mock.patch.object(Y, "_urlopen", lixo):
            with self.assertRaisesRegex(Y.YTErro, "não entendi"):
                self.cli().get("videos", part="snippet", id=V(1))

    def test_cota_esgotada_no_meio_do_caminho(self):
        f = F.mundo(cota=101)
        with mock.patch.object(Y, "_urlopen", f):
            with self.assertRaisesRegex(Y.YTErro, "cota diária"):
                Y.pesquisa_avancada(self.cli(), {"q": "x"}, F.AGORA)          # a busca (100) passa; os 2 seguintes: sobra 1 e falha no 2º


class EntradasTests(unittest.TestCase):
    def test_extrair_video_id(self):
        casos = {"vid00000002": "vid00000002", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s": "dQw4w9WgXcQ", "youtu.be/dQw4w9WgXcQ?si=abc": "dQw4w9WgXcQ",
                 "https://youtu.be/dQw4w9WgXcQ": "dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ", "https://m.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
                 "https://www.youtube.com/embed/dQw4w9WgXcQ": "dQw4w9WgXcQ", "https://www.youtube.com/live/dQw4w9WgXcQ": "dQw4w9WgXcQ", "  dQw4w9WgXcQ  ": "dQw4w9WgXcQ"}
        for entrada, esperado in casos.items():
            self.assertEqual(Y.extrair_video_id(entrada), esperado, entrada)
        for lixo in ("", "curto", "https://www.youtube.com/watch?v=curto", "https://google.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/@canal"):
            with self.assertRaises(ValueError, msg=lixo):
                Y.extrair_video_id(lixo)

    def test_interpretar_canal(self):
        casos = {A: ("id", A), "@alfa": ("handle", "@alfa"), f"https://www.youtube.com/channel/{A}": ("id", A), "https://www.youtube.com/@alfa/videos": ("handle", "@alfa"),
                 "youtube.com/@alfa": ("handle", "@alfa"), "https://www.youtube.com/c/NomeCustom": ("custom", "NomeCustom"), "https://www.youtube.com/user/antigo": ("usuario", "antigo"),
                 "alfa": ("handle", "@alfa"), "https://www.youtube.com/%40alfa": ("handle", "@alfa")}
        for entrada, esperado in casos.items():
            self.assertEqual(Y.interpretar_canal(entrada), esperado, entrada)
        for lixo in ("", "  ", "https://google.com/@alfa", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "duas palavras", "a/b"):
            with self.assertRaises(ValueError, msg=lixo):
                Y.interpretar_canal(lixo)

    def test_duracao_iso_8601(self):
        casos = {"PT1H2M10S": 3730, "PT45S": 45, "PT10M": 600, "PT3H": 10800, "P0D": 0, "P1DT2H": 93600, "PT2M30S": 150, "PT0S": 0}
        for iso, seg in casos.items():
            self.assertEqual(Y.duracao_segundos(iso), seg, iso)
        for lixo in ("", None, "PT", "10:30", "abc", "P"):
            self.assertIsNone(Y.duracao_segundos(lixo), repr(lixo))


class ResolverCanalTests(Base):
    def test_id_nao_gasta_cota(self):
        c = self.cli()
        self.assertEqual(Y.resolver_canal(c, A), (A, ""))
        self.assertEqual((c.unidades, self.f.chamadas), (0, []))

    def test_handle_usa_forhandle_a_1_unidade_e_nao_a_busca_de_100(self):
        c = self.cli()
        self.assertEqual(Y.resolver_canal(c, "@Alfa"), (A, ""))                    # caixa não importa
        self.assertEqual(c.unidades, 1)
        self.assertEqual(self.f.chamadas[0], ("channels", {"part": "id", "forHandle": "@Alfa"}))
        self.assertEqual(self.f.por_recurso("search"), [])

    def test_usuario_antigo_e_nome_custom(self):
        c = self.cli()
        self.assertEqual(Y.resolver_canal(c, "https://www.youtube.com/user/antigo"), (A, ""))
        cid, aviso = Y.resolver_canal(c, "https://www.youtube.com/c/NomeCustom")   # só a busca resolve: 100 unidades
        self.assertEqual(cid, B)
        self.assertIn("busca de nome (100 unidades)", aviso)
        self.assertEqual(c.unidades, 1 + 100)

    def test_handle_que_nao_existe_cai_na_busca_e_depois_da_erro(self):
        c = self.cli()
        with self.assertRaisesRegex(Y.YTErro, "Não encontrei o canal “@ninguem”"):
            Y.resolver_canal(c, "@ninguem")
        self.assertEqual(c.unidades, 1 + 100)                                       # tentou forHandle e depois a busca


class NormalizacaoTests(Base):
    def test_video_traz_engajamento_views_por_dia_e_idade(self):
        v = Y.normalizar_video(self.f.videos[V(2)], F.AGORA)
        self.assertEqual((v["id"], v["url"], v["titulo"], v["canal"], v["canal_id"]), (V(2), f"https://www.youtube.com/watch?v={V(2)}", "12 lições estoicas para ouvir toda manhã", "Canal Alfa", A))
        self.assertEqual((v["views"], v["likes"], v["comentarios"], v["engajamento"]), (9000, 700, 90, 8.78))          # (700 + 90) / 9000
        self.assertEqual((v["idade_dias"], v["data"], v["views_dia"], v["duracao_seg"]), (6, "2026-09-15", 1500.0, 600))
        self.assertEqual(v["thumb"], f"https://i.ytimg.com/vi/{V(2)}/maxres.jpg")                                       # a maior que existe

    def test_likes_ocultos_contam_como_zero_se_ha_comentarios_e_views_zero_nao_divide(self):
        v = Y.normalizar_video(self.f.videos[V(11)], F.AGORA)
        self.assertIsNone(v["likes"])
        self.assertEqual(v["engajamento"], 6.67)                                                                         # 800 / 12000
        self.assertTrue(v["ao_vivo"])
        zero = F.video_item("zero0000000", "Sem views", A, "Canal Alfa", 1, 0, 0, 0, "PT1M")
        self.assertIsNone(Y.normalizar_video(zero, F.AGORA)["engajamento"])
        self.assertIsNone(Y.normalizar_video({"id": "x", "snippet": {}, "statistics": {}}, F.AGORA)["engajamento"])

    def test_canal_normalizado(self):
        c = Y.normalizar_canal(self.f.canais[A])
        self.assertEqual((c["id"], c["titulo"], c["handle"], c["url"], c["pais"]), (A, "Canal Alfa", "@alfa", "https://www.youtube.com/@alfa", "BR"))
        self.assertEqual((c["inscritos"], c["views_totais"], c["n_videos"], c["inscritos_ocultos"]), (8500, 400000, 40, False))
        self.assertEqual(c["uploads_playlist"], "UU" + A[2:])
        self.assertEqual(c["palavras_chave"], ["estoicismo", "vida diária", "calma"])                      # aspas agrupam a expressão
        self.assertEqual(Y._palavras_chave('estoicismo "vida diária" calma'), ["estoicismo", "vida diária", "calma"])

    def test_canal_com_inscritos_ocultos_fica_none_e_sem_handle_usa_a_url_do_id(self):
        c = Y.normalizar_canal(self.f.canais[C])
        self.assertIsNone(c["inscritos"])
        self.assertTrue(c["inscritos_ocultos"])
        sem = Y.normalizar_canal(F.canal_item(F.uc("d"), "Sem handle", 10, 100, 1, "2026-01-01T00:00:00Z"))
        self.assertEqual((sem["handle"], sem["url"]), ("", f"https://www.youtube.com/channel/{F.uc('d')}"))

    def test_metricas_do_canal(self):
        m = Y.metricas_canal(Y.normalizar_canal(self.f.canais[A]), F.AGORA)
        self.assertEqual((m["idade_dias"], m["views_por_video"], m["inscritos_por_video"], m["videos_por_semana"], m["inscritos_por_view_pct"]), (525, 10000, 212.5, 0.53, 2.125))
        novo = Y.metricas_canal({"inscritos": 10, "views_totais": 100, "n_videos": 3, "criado_em": "2026-09-20T00:00:00Z"}, F.AGORA)
        self.assertEqual(novo["videos_por_semana"], 3.0)                                                                # menos de 1 semana conta como 1
        vazio = Y.metricas_canal({"inscritos": None, "views_totais": None, "n_videos": 0, "criado_em": ""}, F.AGORA)
        self.assertEqual(set(vazio.values()), {None})

    def test_metricas_recentes(self):
        vs = [Y.normalizar_video(self.f.videos[V(n)], F.AGORA) for n in (1, 2, 3, 4, 5, 6)]
        m = Y.metricas_recentes(vs, F.AGORA)
        self.assertEqual((m["n"], m["mediana_views"], m["media_views"], m["engajamento_medio"]), (6, 7500, 9400, 7.98))
        self.assertEqual((m["intervalo_medio_dias"], m["videos_por_semana"], m["dias_desde_o_ultimo"]), (6.2, 1.13, 3))     # 31 dias entre o 1º e o 6º / 5
        self.assertEqual(Y.metricas_recentes([], F.AGORA)["mediana_views"], None)
        um = Y.metricas_recentes(vs[:1], F.AGORA)
        self.assertEqual((um["videos_por_semana"], um["intervalo_medio_dias"]), (None, None))


class PesquisaTests(Base):
    def test_sem_datas_assume_os_ultimos_7_dias_e_mostra_que_assumiu(self):
        p = Y.normalizar_pesquisa({"q": "estoicismo"}, F.AGORA)
        self.assertEqual((p["de"], p["ate"], p["assumiu_7_dias"], p["publicado_depois"], p["publicado_antes"]), ("2026-09-14", "", True, "2026-09-14T00:00:00Z", ""))
        p = Y.normalizar_pesquisa({"q": "x", "de": "2026-08-01", "ate": "2026-08-31"}, F.AGORA)
        self.assertEqual((p["assumiu_7_dias"], p["publicado_depois"], p["publicado_antes"]), (False, "2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z"))
        self.assertEqual(Y.normalizar_pesquisa({"ate": "2026-08-31"}, F.AGORA)["de"], "")                                 # só a data final: não inventa a inicial

    def test_validacao_e_limites(self):
        with self.assertRaisesRegex(ValueError, "depois da data final"):
            Y.normalizar_pesquisa({"de": "2026-09-10", "ate": "2026-09-01"}, F.AGORA)
        with self.assertRaisesRegex(ValueError, "Data inválida"):
            Y.normalizar_pesquisa({"de": "amanhã"}, F.AGORA)
        q = lambda **k: Y.normalizar_pesquisa(k, F.AGORA)
        self.assertEqual([q(quantidade=x)["quantidade"] for x in (0, -5, 3, 999, "abc", None)], [25, 1, 3, 50, 25, 25])
        p = q(q="  vários   espaços  ", pais="br", idioma="PT", duracao="xyz", formato="qualquer", ordem="nada")
        self.assertEqual((p["q"], p["pais"], p["idioma"], p["duracao"], p["formato"], p["ordem"], p["modo"]), ("vários espaços", "BR", "pt", "any", "todos", "viewCount", "busca"))
        self.assertEqual(q(pais="BRA", idioma="p1")["pais"], "")                                                        # código inválido é ignorado
        self.assertEqual(q()["modo"], "em_alta")
        self.assertEqual(len(q(q="x" * 999)["q"]), 200)

    def test_busca_por_palavra_chave_passa_os_filtros_a_api_e_custa_102(self):
        c = self.cli()
        r = Y.pesquisa_avancada(c, {"q": "estoicismo", "pais": "BR", "idioma": "pt", "duracao": "medium", "quantidade": 10, "ordem": "date"}, F.AGORA)
        p = self.f.por_recurso("search")[0]
        self.assertEqual((p["q"], p["type"], p["maxResults"], p["order"], p["regionCode"], p["relevanceLanguage"], p["videoDuration"], p["publishedAfter"]),
                         ("estoicismo", "video", "10", "date", "BR", "pt", "medium", "2026-09-14T00:00:00Z"))
        self.assertNotIn("publishedBefore", p)
        self.assertEqual(r["unidades"], 102)
        self.assertEqual([v["id"] for v in r["videos"]], [V(2), V(4), V(8), V(12), V(1)])                                # ordem da busca; 999 some
        self.assertEqual(sorted(r["canais"]), sorted([A, B, C]))
        self.assertEqual(r["params"]["modo"], "busca")
        self.assertTrue(r["params"]["assumiu_7_dias"])

    def test_formato_shorts_pede_duracao_curta_a_api_e_any_nao_manda_o_parametro(self):
        Y.pesquisa_avancada(self.cli(), {"q": "x", "formato": "shorts"}, F.AGORA)
        Y.pesquisa_avancada(self.cli(), {"q": "x"}, F.AGORA)
        Y.pesquisa_avancada(self.cli(), {"q": "x", "formato": "shorts", "duracao": "long"}, F.AGORA)
        ps = self.f.por_recurso("search")
        self.assertEqual((ps[0]["videoDuration"], "videoDuration" in ps[1], ps[2]["videoDuration"]), ("short", False, "long"))

    def test_vazio_cai_no_trending_filtrado_com_eua_por_padrao_e_custa_2(self):
        r = Y.pesquisa_avancada(self.cli(), {}, F.AGORA)
        p = self.f.por_recurso("videos")[0]
        self.assertEqual((p["chart"], p["regionCode"], p["maxResults"]), ("mostPopular", "US", "50"))
        self.assertEqual([v["id"] for v in r["videos"]], [V(7)])                                                        # 9 e 10 são mais velhos que 7 dias
        self.assertEqual((r["unidades"], r["params"]["modo"], r["params"]["pais_usado"]), (2, "em_alta", "US"))
        self.assertIn("vídeos em alta de US", r["avisos"][0])
        self.assertEqual(self.f.por_recurso("search"), [])

    def test_trending_filtrado_por_data_duracao_idioma_e_quantidade(self):
        c = lambda **d: [v["id"] for v in Y.pesquisa_avancada(self.cli(), d, F.AGORA)["videos"]]
        self.assertEqual(c(pais="BR"), [V(8), V(7), V(12), V(2)])                                                        # o 4 (20 dias) fica de fora
        self.assertEqual(c(pais="BR", de="2026-08-01"), [V(8), V(7), V(12), V(4), V(2)])
        self.assertEqual(c(pais="BR", de="2026-08-01", ate="2026-09-10"), [V(4)])
        self.assertEqual(c(pais="BR", duracao="short"), [V(8), V(12)])                                                   # 58 s e 2m30
        self.assertEqual(c(pais="BR", duracao="long"), [V(7)])                                                           # só os > 20 min
        self.assertEqual(c(pais="BR", idioma="en"), [V(8), V(7)])
        self.f.videos[V(12)]["snippet"]["defaultAudioLanguage"] = ""                                                     # sem idioma declarado: fica
        self.assertEqual(c(pais="BR", idioma="en"), [V(8), V(7), V(12)])
        self.assertEqual(c(pais="BR", quantidade=2), [V(8), V(7)])
        self.assertEqual(c(pais="PT"), [])

    def test_sem_resultado_nao_gasta_chamada_de_canais(self):
        c = self.cli()
        r = Y.pesquisa_avancada(c, {"pais": "PT"}, F.AGORA)
        self.assertEqual((r["videos"], r["canais"], c.unidades), ([], {}, 1))


class EmAltaTests(Base):
    def test_lista_paises_e_categoria(self):
        c = self.cli()
        r = Y.em_alta(c, "br", "", F.AGORA)
        self.assertEqual([v["id"] for v in r["videos"]], [V(8), V(7), V(12), V(4), V(2)])
        self.assertEqual((r["pais"], r["unidades"]), ("BR", 2))
        p = self.f.por_recurso("videos")[0]
        self.assertNotIn("videoCategoryId", p)
        r = Y.em_alta(self.cli(), "BR", "27", F.AGORA)
        self.assertEqual([v["id"] for v in r["videos"]], [V(12), V(4), V(2)])
        self.assertEqual(self.f.por_recurso("videos")[-1]["videoCategoryId"], "27")

    def test_padrao_eua_categoria_invalida_ignorada_e_vazio_avisa(self):
        r = Y.em_alta(self.cli(), "", "abc", F.AGORA)
        self.assertEqual((r["pais"], r["categoria"]), ("US", ""))
        r = Y.em_alta(self.cli(), "PT", "", F.AGORA)
        self.assertEqual((r["videos"], r["canais"]), ([], {}))
        self.assertIn("não devolveu vídeos", r["avisos"][0])

    def test_pais_ou_categoria_sem_lista_de_em_alta_vira_erro_claro(self):
        with self.assertRaisesRegex(Y.YTErro, "lista de vídeos em alta"):
            Y.em_alta(self.cli(), "ZZ", "", F.AGORA)
        with self.assertRaisesRegex(Y.YTErro, "lista de vídeos em alta"):
            Y.em_alta(self.cli(), "BR", "99", F.AGORA)


class CompararTests(Base):
    def test_compara_dois_canais_por_handle_e_gasta_7_unidades(self):
        r = Y.comparar(self.cli(), "@alfa", "@beta", F.AGORA)
        self.assertEqual(r["unidades"], 2 + 1 + 2 + 2)                                       # 2 handles, 1 channels, 2 playlistItems, 2 videos
        self.assertEqual((r["a"]["canal"]["id"], r["b"]["canal"]["id"]), (A, B))
        self.assertEqual([v["id"] for v in r["a"]["videos"]], [V(n) for n in (1, 2, 3, 4, 5, 6)])                       # mais novo primeiro
        self.assertEqual(len(self.f.por_recurso("channels")), 3)                              # forHandle x2 + um lote com os 2 canais
        self.assertEqual(self.f.por_recurso("channels")[2]["id"], f"{A},{B}")
        ra, rb = r["a"]["recentes"], r["b"]["recentes"]
        self.assertEqual((ra["mediana_views"], ra["tracao"], ra["videos_por_semana"]), (7500, 0.8824, 1.13))
        self.assertEqual((rb["mediana_views"], rb["media_views"], rb["tracao"]), (400000, 522500, 3.3333))

    def test_linhas_da_comparacao_dizem_so_quem_tem_o_numero_maior(self):
        r = Y.comparar(self.cli(), "@alfa", "@beta", F.AGORA)
        linhas = {l["chave"]: l for l in r["comparacao"]}
        self.assertEqual((linhas["inscritos"]["a"], linhas["inscritos"]["b"], linhas["inscritos"]["maior"]), (8500, 120000, "b"))
        self.assertEqual(linhas["views_por_video"]["maior"], "b")
        self.assertEqual(linhas["videos_por_semana"]["maior"], "a")                           # 1,13 contra 0,55
        self.assertEqual(linhas["engajamento_medio"]["maior"], "a")                           # 7,98 contra 4,5
        self.assertEqual(linhas["tracao"]["maior"], "b")
        self.assertEqual(len(r["comparacao"]), 11)
        self.assertNotIn("melhor", json.dumps(r["comparacao"]))

    def test_empate_e_dado_ausente(self):
        a = {"canal": {"inscritos": 10}, "metricas": {}, "recentes": {}}
        b = {"canal": {"inscritos": 10}, "metricas": {}, "recentes": {}}
        linhas = {l["chave"]: l for l in Y.montar_comparacao(a, b)}
        self.assertEqual((linhas["inscritos"]["maior"], linhas["views_totais"]["maior"]), ("empate", None))

    def test_mesmo_canal_dos_dois_lados_e_canal_inexistente(self):
        with self.assertRaisesRegex(ValueError, "dois canais diferentes"):
            Y.comparar(self.cli(), "@alfa", A, F.AGORA)
        with self.assertRaisesRegex(Y.YTErro, "Não encontrei o canal"):
            Y.comparar(self.cli(), "@alfa", "@ninguem", F.AGORA)

    def test_canal_sem_inscritos_visiveis_compara_sem_inventar(self):
        r = Y.comparar(self.cli(), "@alfa", "@gama", F.AGORA)
        linhas = {l["chave"]: l for l in r["comparacao"]}
        self.assertIsNone(linhas["inscritos"]["b"])
        self.assertIsNone(linhas["inscritos"]["maior"])
        self.assertIsNone(linhas["tracao"]["b"])


class CanalVideoHistoricoTests(Base):
    def test_analisar_canal(self):
        r = Y.analisar_canal(self.cli(), "https://www.youtube.com/@alfa", F.AGORA)
        self.assertEqual((r["canal"]["id"], r["metricas"]["views_por_video"], r["unidades"], r["avisos"]), (A, 10000, 2, []))
        self.assertEqual(r["canal"]["palavras_chave"], ["estoicismo", "vida diária", "calma"])
        self.assertEqual(self.f.por_recurso("channels")[1]["part"], "snippet,statistics,brandingSettings,contentDetails")

    def test_analisar_canal_com_inscritos_ocultos_avisa(self):
        r = Y.analisar_canal(self.cli(), "@gama", F.AGORA)
        self.assertIsNone(r["metricas"]["inscritos_por_video"])
        self.assertEqual(r["metricas"]["views_por_video"], 4167)
        self.assertIn("esconde o número de inscritos", r["avisos"][0])

    def test_analisar_video_por_link_e_short_por_duracao(self):
        r = Y.analisar_video(self.cli(), f"https://www.youtube.com/watch?v={V(2)}", F.AGORA)
        v = r["video"]
        self.assertEqual((v["id"], v["duracao_seg"], v["views_sobre_inscritos"], v["inscritos_do_canal"], r["unidades"]), (V(2), 600, 1.06, 8500, 2))
        self.assertEqual(v["tags"], ["filosofia", "estoicismo"])
        self.assertEqual(v["topicos"], ["Philosophy", "Knowledge"])
        self.assertEqual([t["nome"] for t in v["thumbs"]], ["maxres", "high", "default"])
        self.assertEqual(v["thumb"], f"https://i.ytimg.com/vi/{V(2)}/maxres.jpg")
        self.assertGreater(len(v["descricao"]), 100)                                           # descrição inteira, não a versão curta da lista
        self.assertEqual(self.f.por_recurso("videos")[0]["part"], "snippet,statistics,contentDetails,topicDetails")
        curto = Y.analisar_video(self.cli(), f"https://www.youtube.com/shorts/{V(4)}", F.AGORA)["video"]
        self.assertEqual(curto["duracao_seg"], 45)

    def test_video_inexistente_ou_link_ruim(self):
        with self.assertRaisesRegex(Y.YTErro, "Não encontrei esse vídeo"):
            Y.analisar_video(self.cli(), "vid99999999", F.AGORA)
        with self.assertRaises(ValueError):
            Y.analisar_video(self.cli(), "isso não é link", F.AGORA)

    def test_historico(self):
        r = Y.historico(self.cli(), "@alfa", 30, F.AGORA)
        self.assertEqual((r["unidades"], [v["id"] for v in r["videos"]]), (4, [V(n) for n in (1, 2, 3, 4, 5, 6)]))
        self.assertEqual(self.f.por_recurso("playlistItems")[0]["maxResults"], "30")
        self.assertEqual((r["recentes"]["mediana_views"], r["recentes"]["tracao"]), (7500, 0.8824))
        self.assertEqual(Y.historico(self.cli(), A, 999, F.AGORA)["canal"]["id"], A)
        self.assertEqual(self.f.por_recurso("playlistItems")[-1]["maxResults"], "50")            # limitado a 50 por chamada

    def test_historico_de_canal_sem_videos(self):
        self.f.add_canal(F.canal_item(F.uc("e"), "Vazio", 5, 0, 0, "2026-01-01T00:00:00Z", handle="@vazio"), "@vazio")
        r = Y.historico(self.cli(), "@vazio", 30, F.AGORA)
        self.assertEqual((r["videos"], r["recentes"]["n"]), ([], 0))

    def test_videos_em_lotes_de_50_sem_maxresults(self):
        for n in range(100, 220):
            self.f.add_video(F.video_item(F.vid_id(n), f"Vídeo {n}", A, "Canal Alfa", 5, 100, 1, 1, "PT1M"))
        c = self.cli()
        vs = Y.buscar_videos(c, [F.vid_id(n) for n in range(100, 220)] + [F.vid_id(100)], F.AGORA)             # o repetido é ignorado
        self.assertEqual(len(vs), 120)
        chamadas = self.f.por_recurso("videos")
        self.assertEqual([len(p["id"].split(",")) for p in chamadas], [50, 50, 20])
        self.assertTrue(all("maxResults" not in p for p in chamadas))
        self.assertEqual(c.unidades, 3)


class MiniaturaTests(unittest.TestCase):
    def test_tenta_da_maior_para_a_menor_e_devolve_a_primeira_que_existe(self):
        f = F.mundo()
        self.assertEqual(Y.baixar_miniatura(V(2), abrir=f)[2], "maxresdefault")
        corpo, tipo, nome = Y.baixar_miniatura(V(4), abrir=f)                                # sem maxres nem sd: cai no hq
        self.assertEqual((nome, tipo), ("hqdefault", "image/jpeg"))
        self.assertTrue(corpo.startswith(b"\xff\xd8\xff"))
        self.assertEqual(Y.baixar_miniatura(V(1), abrir=f)[2], "default")

    def test_sem_nenhuma_miniatura_id_invalido_e_falhas(self):
        f = F.mundo()
        with self.assertRaisesRegex(Y.YTErro, "não tem miniatura"):
            Y.baixar_miniatura(V(5), abrir=f)
        for ruim in ("", "curto", "../../etc/passwd", "vid0000000 2", None, "a" * 12):
            with self.assertRaises(ValueError, msg=repr(ruim)):
                Y.baixar_miniatura(ruim, abrir=f)
        f.falha_rede = True
        with self.assertRaisesRegex(Y.YTErro, "sem conexão"):
            Y.baixar_miniatura(V(2), abrir=f)
        erro500 = mock.Mock(side_effect=HTTPError("u", 500, "x", {}, io.BytesIO(b"")))
        with self.assertRaisesRegex(Y.YTErro, "Não consegui baixar"):
            Y.baixar_miniatura(V(2), abrir=erro500)

    def test_so_pede_imagem_a_i_ytimg_com_o_id_validado(self):
        vistos = []

        def abrir(req, timeout=15):
            vistos.append(req.full_url)
            raise HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b""))
        with self.assertRaises(Y.YTErro):
            Y.baixar_miniatura(V(2), abrir=abrir)
        self.assertEqual(len(vistos), 5)
        self.assertTrue(all(u.startswith(f"https://i.ytimg.com/vi/{V(2)}/") for u in vistos))


if __name__ == "__main__":
    unittest.main(verbosity=2)
