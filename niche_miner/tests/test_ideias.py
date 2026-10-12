"""Lógica pura da aba Ideias virais (sem navegador e sem rede)."""
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

import ideias as I


# ---------------------------------------------------------------- JSON da IA
class ExtrairJsonTests(unittest.TestCase):
    def test_json_puro(self):
        self.assertEqual(I.extrair_json('{"a": 1}'), {"a": 1})

    def test_cerca_de_markdown_e_texto_em_volta(self):
        t = 'Claro! Segue:\n```json\n{"ideias": [{"titulo_amplo": "x"}]}\n```\nEspero ter ajudado [1].'
        self.assertEqual(I.extrair_json(t), {"ideias": [{"titulo_amplo": "x"}]})

    def test_prefere_o_objeto_maior_a_um_colchete_solto_antes(self):
        self.assertEqual(I.extrair_json('[nota] {"a": [1, 2, 3]}'), {"a": [1, 2, 3]})

    def test_aspas_tipograficas(self):
        self.assertEqual(I.extrair_json("{\u201ca\u201d: \u201cb\u201d}"), {"a": "b"})

    def test_lista_no_topo(self):
        self.assertEqual(I.extrair_json("[1, 2]"), [1, 2])

    def test_vazio_e_invalido(self):
        for t in ("", "   ", None):
            with self.assertRaises(ValueError):
                I.extrair_json(t)
        with self.assertRaises(ValueError):
            I.extrair_json("isso não é json")
        with self.assertRaises(ValueError):
            I.extrair_json('{"a": ')

    def test_json_grande_nao_e_quadratico(self):
        grande = {"ideias": [{"titulo_amplo": f"t{i}", "termos_validacao": ["a", "b"]} for i in range(3000)]}
        ini = time.time()
        self.assertEqual(len(I.extrair_json(json.dumps(grande))["ideias"]), 3000)
        self.assertLess(time.time() - ini, 2)


class NotasTests(unittest.TestCase):
    def test_formatos_e_limites(self):
        self.assertEqual(I._nota(4), 4.0)
        self.assertEqual(I._nota("3/5"), 3.0)
        self.assertEqual(I._nota("4,5"), 4.5)
        self.assertEqual(I._nota(9), 5.0)
        self.assertEqual(I._nota(-2), 0.0)
        for ruim in (None, "", "abc", True):
            self.assertIsNone(I._nota(ruim))


# ---------------------------------------------------------------- validação
class ValidarDecomposicaoTests(unittest.TestCase):
    def test_aceita_chaves_com_acento_e_apelidos(self):
        r = I.validar_decomposicao(json.dumps({"videos": [
            {"indice": 1, "Emoção": "curiosidade", "estrutura": "tempo como prova", "publicos_adjacentes": "pais, donos de pet", "amplitude": "4/5"}],
            "padroes": [{"nome": "P1", "elementos_fixos": ["a"], "indices": [1, "2"]}]}, ensure_ascii=False))
        v = r["videos"][0]
        self.assertEqual((v["emocao"], v["estrutura_titulo"], v["amplitude"]), ("curiosidade", "tempo como prova", 4.0))
        self.assertEqual(v["publicos_adjacentes"], ["pais", "donos de pet"])
        self.assertEqual(r["padroes"][0]["indices"], [1, 2])

    def test_indice_fora_da_lista_e_descartado(self):
        r = I.validar_decomposicao('{"videos": [{"indice": 1, "emocao": "a"}, {"indice": 9, "emocao": "b"}]}', n_videos=3)
        self.assertEqual([v["indice"] for v in r["videos"]], [1])

    def test_lista_no_topo_vira_videos(self):
        self.assertEqual(len(I.validar_decomposicao('[{"indice": 1, "emocao": "x"}]')["videos"]), 1)

    def test_sem_conteudo_util_falha(self):
        with self.assertRaises(ValueError):
            I.validar_decomposicao('{"outra": 1}')


class ValidarExpansaoTests(unittest.TestCase):
    def test_junta_buscas_aos_termos_sem_duplicar(self):
        r = I.validar_expansao(json.dumps({"problemas_e_buscas": [{"busca": "vazamento no motor"}, {"busca": "a"}],
                                           "termos_para_validar": ["a", "b"], "publicos_adjacentes": [{"publico": "mecânicos"}]}))
        self.assertEqual(r["termos_para_validar"], ["a", "b", "vazamento no motor"])
        self.assertEqual(r["publicos_adjacentes"][0]["publico"], "mecânicos")

    def test_sem_buscas_falha(self):
        with self.assertRaises(ValueError):
            I.validar_expansao('{"sinonimos": ["x"]}')


class ValidarIdeiasTests(unittest.TestCase):
    def test_normaliza_mercado_termos_e_brecha(self):
        r = I.validar_ideias(json.dumps({"ideias": [
            {"titulo_amplo": "A", "mercado": "Alemanha", "tipo_brecha": "Dupla (novo país)", "termos_validacao": "x; y", "amplitude": "3/5"},
            {"titulo_sub": "só sub", "mercado": "Canadá"},
        ]}), mercado_padrao="US")
        a, b = r
        self.assertEqual((a["mercado"], a["tipo_brecha"], a["termos_validacao"], a["amplitude"]), ("DE", "dupla", ["x", "y"], 3.0))
        self.assertEqual((b["titulo_amplo"], b["mercado"], b["tipo_brecha"]), ("só sub", "US", "simples"))
        self.assertNotEqual(a["id"], b["id"])
        self.assertIsNone(a["score"])

    def test_ideia_sem_titulo_e_ignorada_e_lista_vazia_falha(self):
        self.assertEqual(len(I.validar_ideias('{"ideias": [{"emocao": "x"}, {"titulo_amplo": "ok"}]}')), 1)
        with self.assertRaises(ValueError):
            I.validar_ideias('{"ideias": [{"emocao": "x"}]}')

    def test_mesclar_nao_duplica_por_titulo_amplo(self):
        a = I.validar_ideias('{"ideias": [{"titulo_amplo": "Título Ótimo"}]}')
        b = I.validar_ideias('{"ideias": [{"titulo_amplo": "titulo otimo"}, {"titulo_amplo": "Outro"}]}')
        todas, novas = I.mesclar_ideias(a, b)
        self.assertEqual((len(todas), novas), (2, 1))


# ---------------------------------------------------------------- prompts
class PromptsTests(unittest.TestCase):
    def videos(self, n=3):
        return [{"titulo": f"Título {i}", "canal": f"C{i}", "views_num": 1234567, "quando": "há 2 semanas",
                 "inscritos_num": 5000, "razao_views_inscritos": 246.9} for i in range(1, n + 1)]

    def test_decomposicao_traz_dados_formato_e_mercado(self):
        p = I.montar_prompt_decomposicao("pragas", self.videos(), "DE", refs_extra=["Título extra"])
        for trecho in ('1. "Título 1"', "1.234.567 views", "246.9x os inscritos", '4. "Título extra"', "Alemanha", '"videos":', '"padroes":', "amplitude"):
            self.assertIn(trecho, p)

    def test_decomposicao_limita_videos_e_exige_conteudo(self):
        p = I.montar_prompt_decomposicao("x", self.videos(50), limite=30)
        self.assertIn('30. "Título 30"', p)
        self.assertNotIn('31. "Título 31"', p)
        with self.assertRaises(ValueError):
            I.montar_prompt_decomposicao("x", [])

    def test_expansao(self):
        p = I.montar_prompt_expansao("carros", "MX", n=999)
        self.assertIn("México", p)
        self.assertIn("30 buscas", p)  # limitado a 30
        self.assertIn('"termos_para_validar"', p)

    def test_ideias_lista_so_mercados_permitidos_e_padroes(self):
        p = I.montar_prompt_ideias("pragas", [{"nome": "Truque", "emocao": "curiosidade", "estrutura": "X", "elementos_fixos": ["a"], "elementos_variaveis": ["b"]}],
                                   n=5, modo="outro_mercado", mercado_base="BR", mercados_alvo=["DE", "Polônia", "Atlantida"])
        self.assertIn("DE = Alemanha", p)
        self.assertIn("PL = Polônia", p)
        self.assertNotIn("Atlantida", p)
        self.assertNotIn("BR = Brasil", p)
        self.assertIn("Truque", p)
        self.assertIn("Não copie títulos existentes", p)
        self.assertIn("Gere 5 ideias", p)

    def test_ideias_sem_padroes_e_modo_invalido(self):
        p = I.montar_prompt_ideias("x", [], modo="qualquer")
        self.assertIn("Não há padrões extraídos", p)
        self.assertIn(I.MODOS_IDEIAS["ambos"], p)
        self.assertIn("BR = Brasil", p)  # sem alvos, usa o mercado base


# ---------------------------------------------------------------- autocomplete
class SugestoesTests(unittest.TestCase):
    def test_json_puro_jsonp_e_lixo(self):
        self.assertEqual(I.parse_sugestoes('["q", ["a", "b", "a"]]'), ["a", "b"])
        self.assertEqual(I.parse_sugestoes('window.google.ac.h(["q", [["x", 0], ["y", 0]]])'), ["x", "y"])
        for lixo in ("", "<html>", '{"a": 1}', "[1]", None):
            self.assertEqual(I.parse_sugestoes(lixo), [])


# ---------------------------------------------------------------- Trends
class ClassificarSerieTests(unittest.TestCase):
    def test_tendencias(self):
        self.assertEqual(I.classificar_serie([10] * 6 + [30] * 6)["tendencia"], "subindo")
        self.assertEqual(I.classificar_serie([30] * 6 + [10] * 6)["tendencia"], "caindo")
        self.assertEqual(I.classificar_serie([20, 21] * 6)["tendencia"], "estavel")

    def test_comeco_zerado(self):
        self.assertEqual(I.classificar_serie([0] * 6 + [40] * 6)["tendencia"], "subindo")
        self.assertEqual(I.classificar_serie([0] * 12)["tendencia"], "estavel")

    def test_perfis(self):
        self.assertEqual(I.classificar_serie([50 + (i % 3) for i in range(52)])["perfil"], "evergreen")
        pico = [2] * 40 + [100, 90, 80, 70] + [2] * 8
        self.assertEqual(I.classificar_serie(pico)["perfil"], "sazonal")

    def test_serie_curta_ou_vazia_fica_indefinida(self):
        self.assertEqual(I.classificar_serie([1, 2, 3])["tendencia"], "indefinida")
        self.assertEqual(I.classificar_serie([])["tendencia"], "indefinida")


class _FakeDF:
    def __init__(self, series):
        self._s = series
        self.columns = list(series)
        self.empty = not series

    def __getitem__(self, k):
        return mock.Mock(tolist=lambda: self._s[k])


class _FakeTrends:
    """Cada lote tem escala diferente: a âncora existe para tornar os lotes comparáveis."""
    def __init__(self, escalas, falhar_no_lote=None):
        self.lotes, self.escalas, self.falhar = [], escalas, falhar_no_lote

    def build_payload(self, lote, timeframe, geo, gprop):
        self.lotes.append((list(lote), geo, gprop))

    def interest_over_time(self):
        n = len(self.lotes)
        if self.falhar == n:
            raise RuntimeError("429 Too Many Requests")
        lote = self.lotes[-1][0]
        base = {"ancora": 50, "b": 20, "c": 10, "d": 40, "e": 5, "f": 30}
        esc = self.escalas[n - 1]
        return _FakeDF({t: [base.get(t, 10) * esc] * 12 for t in lote})


class ColetarTrendsTests(unittest.TestCase):
    def test_ancora_torna_lotes_comparaveis(self):
        fake = _FakeTrends(escalas=[1.0, 0.5])
        r = I.coletar_trends(["ancora", "b", "c", "d", "e", "f"], geo="BR", fabrica=lambda: fake, pausa=0)
        self.assertTrue(r["disponivel"])
        self.assertEqual([l[0] for l in fake.lotes], [["ancora", "b", "c", "d", "e"], ["ancora", "f"]])
        self.assertEqual(fake.lotes[0][1], "BR")
        t = r["termos"]
        # f foi lido num lote com escala 0.5 (âncora = 25): reescala para a âncora = 50
        self.assertEqual(t["ancora"]["nivel"], 50.0)
        self.assertEqual(t["f"]["nivel"], 30.0)
        self.assertEqual(t["b"]["nivel"], 20.0)

    def test_falha_no_meio_devolve_o_que_ja_coletou(self):
        fake = _FakeTrends(escalas=[1, 1], falhar_no_lote=2)
        r = I.coletar_trends(["ancora", "b", "c", "d", "e", "f"], fabrica=lambda: fake, pausa=0)
        self.assertTrue(r["disponivel"])
        self.assertIn("429", r["motivo"])
        self.assertIn("b", r["termos"])
        self.assertNotIn("f", r["termos"])

    def test_sem_pytrends_explica_como_instalar(self):
        with mock.patch.dict(sys.modules, {"pytrends": None, "pytrends.request": None}):
            r = I.coletar_trends(["a"])
        self.assertFalse(r["disponivel"])
        self.assertIn("pip install pytrends", r["motivo"])

    def test_sem_termos(self):
        self.assertFalse(I.coletar_trends([], fabrica=lambda: None)["disponivel"])

    def test_url_manual_do_trends(self):
        u = I.url_trends(["a b", "c"], geo="DE", periodo="today 12-m", gprop="youtube")
        self.assertIn("q=a%20b,c", u)
        self.assertIn("geo=DE", u)
        self.assertIn("gprop=youtube", u)


# ---------------------------------------------------------------- radar / concorrência
class RadarTests(unittest.TestCase):
    def test_metricas_concorrencia(self):
        vids = [{"views_num": 1000 * (i + 1), "views_dia": 10 * (i + 1), "canal_url": f"c{i % 4}"} for i in range(12)]
        m = I.metricas_concorrencia(vids)
        self.assertEqual((m["n_videos"], m["n_canais"], m["insuficiente"]), (12, 4, False))
        self.assertEqual(m["concentracao_top3"], 0.75)
        self.assertEqual(m["maior_views"], 12000)

    def test_poucos_videos_sao_insuficientes(self):
        self.assertTrue(I.metricas_concorrencia([{"views_num": 5, "canal": "a"}] * 3)["insuficiente"])
        self.assertEqual(I.metricas_concorrencia([])["n_videos"], 0)

    def test_selecao_para_ia_prioriza_razao_e_depois_views_dia(self):
        vs = [{"video_id": "a", "views_dia": 900}, {"video_id": "b", "razao_views_inscritos": 50, "views_dia": 1},
              {"video_id": "c", "razao_views_inscritos": 2, "views_dia": 5000}, {"video_id": "d", "views_dia": 100}]
        self.assertEqual([v["video_id"] for v in I.selecionar_para_ia(vs, 3)], ["b", "c", "a"])

    def test_resumo_por_termo_conta_outliers(self):
        r = I.resumo_radar([{"termo_busca": "t", "views_num": 10, "razao_views_inscritos": 3}, {"termo_busca": "t", "views_num": 30}])
        self.assertEqual(r, [{"termo": "t", "n_videos": 2, "mediana_views": 20, "outliers": 1}])


# ---------------------------------------------------------------- pontuação
def _ideia(id_, mercado="BR", termos=("t",), **kw):
    base = {"id": id_, "titulo_amplo": id_, "mercado": mercado, "termos_validacao": list(termos), "amplitude": None,
            "repetibilidade": None, "producao": None, "descartada": False, "sinais": {}, "criterios": {}}
    base.update(kw)
    return base


def _reg(termo, mercado="BR", **kw):
    r = {"termo": termo, "mercado": mercado, "sugestoes_google": None, "sugestoes_youtube": None, "serp_status": "desativado",
         "paa": [], "relacionadas": [], "trends": None, "yt": None}
    r.update(kw)
    return r


class PontuacaoTests(unittest.TestCase):
    def test_criterio_sem_dado_nao_vira_zero(self):
        score, conf = I.pontuar({"amplitude": 4, "demanda": None, "concorrencia": None, "repetibilidade": None, "producao": None}, None)
        self.assertEqual(score, 80.0)  # 4/5, sem penalizar o que não tem dado
        self.assertEqual(conf, 0.25)   # só 25 dos 100 pontos de peso têm dado

    def test_sem_nenhum_dado(self):
        self.assertEqual(I.pontuar({}, None), (None, 0.0))

    def test_pesos_mudam_o_score_e_pesos_invalidos_caem_no_padrao(self):
        crit = {"amplitude": 5, "demanda": 0, "concorrencia": 0, "repetibilidade": 0, "producao": 0}
        self.assertEqual(I.pontuar(crit, {"amplitude": 100, "demanda": 0, "concorrencia": 0, "repetibilidade": 0, "producao": 0})[0], 100.0)
        self.assertEqual(I.normalizar_pesos({c: 0 for c in I.CRITERIOS}), I.PESOS_PADRAO)
        self.assertEqual(I.normalizar_pesos({"amplitude": "x", "demanda": -5})["demanda"], 0.0)
        self.assertEqual(I.normalizar_pesos({"amplitude": "x"})["amplitude"], I.PESOS_PADRAO["amplitude"])

    def test_sinais_e_criterios_a_partir_da_validacao(self):
        estado = {"ideias": [_ideia("a", termos=("t1", "t2"), amplitude=4, repetibilidade=3, producao=5)], "validacao": {
            I.chave_validacao("t1", "BR"): _reg("t1", sugestoes_google=["x"] * 10, sugestoes_youtube=["y"] * 6, serp_status="ok",
                                               paa=["p1?", "p2?"], relacionadas=["r"], trends={"nivel": 80, "tendencia": "subindo", "perfil": "evergreen"},
                                               yt={"n_videos": 20, "mediana_views_dia": 500, "concentracao_top3": 0.4, "insuficiente": False}, trends_url="u"),
            I.chave_validacao("t2", "BR"): _reg("t2", sugestoes_google=["x"] * 4, sugestoes_youtube=None, serp_status="bloqueado",
                                               trends={"nivel": 20, "tendencia": "caindo", "perfil": "irregular"},
                                               yt={"n_videos": 5, "mediana_views_dia": 100, "concentracao_top3": 1.0, "insuficiente": True}),
        }}
        I.recalcular_estado(estado)
        i = estado["ideias"][0]
        s = i["sinais"]
        self.assertEqual(s["termos_validados"], 2)
        self.assertEqual(s["sugestoes_google"], 7.0)     # média de 10 e 4
        self.assertEqual(s["sugestoes_youtube"], 6.0)    # só o t1 coletou
        self.assertEqual(s["serp_perguntas"], 2)         # t2 foi bloqueado: fica de fora
        self.assertEqual((s["trends_nivel"], s["trends_termo"]), (80, "t1"))
        self.assertEqual(s["yt_concentracao_top3"], 0.4)  # resultado insuficiente não entra
        self.assertEqual(s["perguntas_exemplo"], ["p1?", "p2?"])
        self.assertEqual(s["trends_url"], "u")
        self.assertEqual(i["criterios"]["concorrencia"], 3.0)
        self.assertIsNotNone(i["criterios"]["demanda"])
        self.assertEqual(i["confianca"], 1.0)
        self.assertEqual(i["rank"], 1)

    def test_demanda_e_relativa_dentro_do_mesmo_mercado(self):
        def com_trends(nivel, cod):
            return _reg("t", cod, trends={"nivel": nivel, "tendencia": "estavel", "perfil": "evergreen"})
        estado = {"ideias": [_ideia("br_forte", "BR"), _ideia("br_fraca", "BR"), _ideia("de_unica", "DE")], "validacao": {}}
        estado["ideias"][0]["termos_validacao"] = ["a"]
        estado["ideias"][1]["termos_validacao"] = ["b"]
        estado["ideias"][2]["termos_validacao"] = ["c"]
        estado["validacao"] = {I.chave_validacao("a", "BR"): com_trends(100, "BR"), I.chave_validacao("b", "BR"): com_trends(25, "BR"),
                               I.chave_validacao("c", "DE"): com_trends(5, "DE")}
        I.recalcular_estado(estado)
        d = {i["id"]: i["criterios"]["demanda"] for i in estado["ideias"]}
        self.assertEqual(d["br_forte"], 5.0)
        self.assertEqual(d["br_fraca"], 1.25)
        self.assertEqual(d["de_unica"], 5.0)  # líder do próprio mercado, apesar do nível absoluto baixo

    def test_descartada_sai_do_ranking_e_da_referencia(self):
        estado = {"ideias": [_ideia("a", amplitude=5), _ideia("b", amplitude=1, descartada=True), _ideia("c", amplitude=3)], "validacao": {}}
        I.recalcular_estado(estado)
        ranks = {i["id"]: i["rank"] for i in estado["ideias"]}
        self.assertEqual(ranks, {"a": 1, "b": None, "c": 2})

    def test_sem_validacao_nao_inventa_sinais(self):
        estado = {"ideias": [_ideia("a", amplitude=2)], "validacao": {}}
        I.recalcular_estado(estado)
        self.assertEqual(estado["ideias"][0]["sinais"], {})
        self.assertIsNone(estado["ideias"][0]["criterios"]["demanda"])


# ---------------------------------------------------------------- decisão
class DecidirCanalTests(unittest.TestCase):
    def test_cedo_demais(self):
        r = I.decidir_canal(10)
        self.assertEqual(r["veredito"], "continuar")
        self.assertIn("impressões e CTR", r["explicacao"])

    def test_alerta_entre_15_e_29_e_descarte_a_partir_de_30(self):
        self.assertEqual(I.decidir_canal(15, 100, 1)["veredito"], "alerta")
        self.assertEqual(I.decidir_canal(29, 100, 1)["veredito"], "alerta")
        self.assertEqual(I.decidir_canal(30, 100, 1)["veredito"], "descartar")
        self.assertEqual(I.decidir_canal(45)["veredito"], "descartar")

    def test_tracao_antes_do_corte_manda_escalar(self):
        self.assertEqual(I.decidir_canal(12, 2000, 6, 45)["veredito"], "escalar")
        self.assertEqual(I.decidir_canal(40, 2000, 6, 45)["veredito"], "escalar")

    def test_diagnosticos(self):
        self.assertIn("Impressão quase zero", I.decidir_canal(20, 50, 8)["diagnosticos"][0]["causa"])
        self.assertIn("ninguém clica", I.decidir_canal(20, 5000, 1)["diagnosticos"][0]["causa"])
        self.assertIn("saem cedo", I.decidir_canal(20, 5000, 6, 10)["diagnosticos"][0]["causa"])
        self.assertEqual(I.decidir_canal(20, 5000, 6, 10)["veredito"], "alerta")

    def test_limiares_ajustaveis_e_entrada_suja(self):
        self.assertEqual(I.decidir_canal(20, 100, 2, limiares={"impressoes_baixas": 50, "ctr_baixo": 1})["veredito"], "escalar")
        r = I.decidir_canal("abc", "", "5,5", limiares={"corte_final": "x", "inexistente": 1})
        self.assertEqual(r["veredito"], "continuar")
        self.assertEqual(r["limiares"]["corte_final"], 30)


# ---------------------------------------------------------------- persistência
class PersistenciaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.addCleanup(self.tmp.cleanup)

    def criar(self, **kw):
        return I.criar_pesquisa("Pragas em casa", "BR", kw.get("termos", "mosquito\nbarata"), self.db)

    def test_criar_obter_listar_excluir(self):
        pid = self.criar()
        e = I.obter_pesquisa(pid, self.db)
        self.assertEqual((e["tema"], e["mercado"], e["termos"]), ("Pragas em casa", "BR", ["mosquito", "barata"]))
        lista = I.listar_pesquisas(self.db)
        self.assertEqual([(p["id"], p["n_ideias"], p["n_videos"]) for p in lista], [(pid, 0, 0)])
        self.assertTrue(I.excluir_pesquisa(pid, self.db))
        self.assertIsNone(I.obter_pesquisa(pid, self.db))
        self.assertFalse(I.excluir_pesquisa(pid, self.db))

    def test_tema_obrigatorio(self):
        with self.assertRaises(ValueError):
            I.criar_pesquisa("  ", db_path=self.db)

    def test_navegador_nao_consegue_sobrescrever_radar_nem_validacao(self):
        pid = self.criar()
        I.mutar_pesquisa(pid, lambda e: e.update(radar={"videos": [1]}, validacao={"k": {}}) or e, self.db)
        e = I.atualizar_config(pid, {"radar": None, "validacao": {}, "ideias": [], "termos": ["novo"], "mercado": "de", "pesos": {"amplitude": 90}}, self.db)
        self.assertEqual(e["radar"], {"videos": [1]})
        self.assertEqual(e["validacao"], {"k": {}})
        self.assertEqual((e["termos"], e["mercado"], e["pesos"]["amplitude"]), (["novo"], "DE", 90.0))

    def test_config_com_mercado_invalido_mantem_o_anterior(self):
        pid = self.criar()
        self.assertEqual(I.atualizar_config(pid, {"mercado": "XX"}, self.db)["mercado"], "BR")

    def test_atualizar_ideia_recalcula_e_valida_campos(self):
        pid = self.criar()
        ideias = I.validar_ideias('{"ideias": [{"titulo_amplo": "A", "amplitude": 2}, {"titulo_amplo": "B", "amplitude": 3}]}')
        I.mutar_pesquisa(pid, lambda e: I.recalcular_estado(e.update(ideias=ideias) or e), self.db)
        a = ideias[0]["id"]
        e = I.atualizar_ideia(pid, a, {"amplitude": 5, "favorita": 1, "termos_validacao": ["x", "y"], "campo_livre": "ignorado"}, self.db)
        i = next(x for x in e["ideias"] if x["id"] == a)
        self.assertEqual((i["amplitude"], i["favorita"], i["termos_validacao"], i["rank"]), (5.0, True, ["x", "y"], 1))
        self.assertNotIn("campo_livre", i)
        self.assertIsNone(I.atualizar_ideia(pid, "inexistente", {"amplitude": 1}, self.db))
        with self.assertRaises(KeyError):
            I.atualizar_ideia(999, a, {}, self.db)

    def test_escritas_concorrentes_nao_perdem_dados(self):
        pid = self.criar()

        def somar(_):
            I.mutar_pesquisa(pid, lambda e: e.__setitem__("contador", e.get("contador", 0) + 1) or e, self.db)

        ts = [threading.Thread(target=somar, args=(i,)) for i in range(25)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(I.obter_pesquisa(pid, self.db)["contador"], 25)

    def test_csv_exporta_ranking_com_bom_e_criterios(self):
        pid = self.criar()
        ideias = I.validar_ideias(json.dumps({"ideias": [
            {"titulo_amplo": "Baixa", "amplitude": 1}, {"titulo_amplo": "Alta, com vírgula", "amplitude": 5, "termos_validacao": ["a", "b"]}]}))
        I.mutar_pesquisa(pid, lambda e: I.recalcular_estado(e.update(ideias=ideias) or e), self.db)
        import csv, io
        linhas = list(csv.DictReader(io.StringIO(I.exportar_csv(pid, self.db))))
        self.assertEqual([l["titulo_amplo"] for l in linhas], ["Alta, com vírgula", "Baixa"])
        self.assertEqual(linhas[0]["rank"], "1")
        self.assertEqual(linhas[0]["termos_validacao"], "a | b")
        self.assertEqual(linhas[0]["amplitude"], "5.0")
        self.assertIsNone(I.exportar_csv(999, self.db))


if __name__ == "__main__":
    unittest.main(verbosity=2)
