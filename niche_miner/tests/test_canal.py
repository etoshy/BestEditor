"""Lógica pura do analisador de canal (canal.py). Valores da amostra calculados à mão."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import canal as cn

AGORA = datetime(2026, 9, 21, 12, 0)

# (idade em dias, título, views, duração)
AMOSTRA = [
    (3, "Como ter um dia mais produtivo com estoicismo", 900, "9:00"),
    (20, "Como parar de reclamar da vida com estoicismo", 6000, "12:00"),
    (30, "12 lições estoicas para ouvir toda manhã", 9000, "10:00"),
    (40, "Pare de esperar: como dar o primeiro passo", 8000, "15:00"),
    (50, "Por que o estoicismo funciona?", 2000, "8:00"),
    (60, "Marco Aurélio e a arte de aceitar", 1500, "9:00"),
    (70, "Como controlar suas emoções segundo o estoicismo", 7000, "11:00"),
    (80, "Sêneca sobre o tempo", 1000, "7:00"),
    (90, "Epicteto explica a liberdade", 1200, "6:00"),
    (100, "5 hábitos estoicos que mudam sua vida", 8500, "14:00"),
    (110, "O que é estoicismo de verdade", 1800, "9:00"),
    (120, "Como lidar com pessoas difíceis usando o estoicismo", 7500, "13:00"),
    (130, "Meditações de Marco Aurélio resumo", 900, "20:00"),
    (140, "Nunca mais sofra por coisas que não controla", 5000, "10:00"),
    (150, "Estoicismo para iniciantes", 1100, "8:00"),
    (155, "3 lições de Sêneca para ansiedade", 6500, "12:00"),
]


def dia(idade):
    return (AGORA.date() - timedelta(days=idade)).isoformat()


def registro(amostra=None, **extra):
    """Registro de canal como o scraper devolve (chaves de yt_scraper)."""
    linhas = AMOSTRA if amostra is None else amostra
    c = {"canal": "Estoico Exemplo", "canal_url": "https://www.youtube.com/@estoicoexemplo", "inscritos_num": 8500,
         "inscritos_text": "8,5 mil inscritos", "n_videos": 40, "views_totais": 400000, "data_criacao_canal": "2026-04-14",
         "videos_ultimos_30d": 4, "frequencia_label": "1 vídeo por semana", "amostra_completa": False, "pais_canal": "Brasil",
         "idioma_canal": "Português",
         # fora de ordem de propósito: o resultado não pode depender dela
         "amostra_videos": [{"video_id": f"v{i}", "titulo": t, "url": f"https://youtu.be/v{i}", "views_num": v, "data": dia(idade),
                             "duracao": dur, "quando": f"há {idade} dias"} for i, (idade, t, v, dur) in reversed(list(enumerate(linhas, 1)))]}
    c.update(extra)
    return c


class LinkDoCanalTests(unittest.TestCase):
    def test_formas_validas_viram_a_url_canonica(self):
        casos = {
            "@estoico": "https://www.youtube.com/@estoico",
            "https://www.youtube.com/@estoico": "https://www.youtube.com/@estoico",
            "youtube.com/@estoico/videos": "https://www.youtube.com/@estoico",
            "https://m.youtube.com/@estoico/about?x=1#y": "https://www.youtube.com/@estoico",
            "  https://www.youtube.com/@Estoico/  ": "https://www.youtube.com/@Estoico",          # mantém a caixa do handle
            "https://www.youtube.com/channel/UCabcdefghij1234567890/videos": "https://www.youtube.com/channel/UCabcdefghij1234567890",
            "https://www.youtube.com/c/NomeAntigo/featured": "https://www.youtube.com/c/NomeAntigo",
            "https://www.youtube.com/user/alguem": "https://www.youtube.com/user/alguem",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(cn.normalizar_url_canal(entrada), esperado, entrada)

    def test_o_que_nao_e_canal_e_recusado_com_mensagem_util(self):
        for lixo in ("", "   ", "https://google.com/@x", "não é link", "https://www.youtube.com/"):
            with self.assertRaises(ValueError, msg=lixo):
                cn.normalizar_url_canal(lixo)
        with self.assertRaisesRegex(ValueError, "link de um vídeo"):
            cn.normalizar_url_canal("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        with self.assertRaisesRegex(ValueError, "link de um vídeo"):
            cn.normalizar_url_canal("https://www.youtube.com/shorts/abc")


class MetricasTests(unittest.TestCase):
    def setUp(self):
        self.m = cn.metricas_canal(registro(), AGORA)

    def test_numeros_do_cabecalho_do_canal(self):
        m = self.m
        self.assertEqual((m["inscritos"], m["n_videos"], m["views_totais"], m["criado_em"]), (8500, 40, 400000, "2026-04-14"))
        self.assertEqual(m["dias_de_vida"], 160)
        self.assertEqual(m["meses_de_vida"], 5.3)
        self.assertEqual(m["views_por_video"], 10000)                                   # 400.000 / 40
        self.assertEqual(m["views_mensais_medias"], round(400000 / (160 / 30.4375)))
        self.assertEqual(m["uploads_por_mes_vida"], 7.6)                                # 40 / 5,26 meses
        self.assertEqual((m["pais"], m["idioma"], m["frequencia_label"]), ("Brasil", "Português", "1 vídeo por semana"))

    def test_mediana_dos_10_mais_recentes_ignora_a_ordem_da_coleta_e_calcula_a_tracao(self):
        m = self.m
        self.assertEqual(m["n_mediana_usados"], 10)
        self.assertEqual(m["mediana_ultimos"], 4000)                                    # 900 1000 1200 1500 2000 6000 7000 8000 8500 9000
        self.assertEqual(m["tracao"], round(4000 / 8500, 4))
        self.assertEqual((m["amostra_n"], m["amostra_com_views"]), (16, 16))
        self.assertEqual(m["mediana_views_amostra"], 3500)

    def test_duracao_e_titulo(self):
        m = self.m
        self.assertEqual((m["duracao_media_seg"], m["duracao_mediana_seg"], m["n_duracao"]), (649, 600, 16))     # média 10,81 min
        self.assertEqual(m["titulo_medio_chars"], round(sum(len(t) for _, t, _, _ in AMOSTRA) / 16, 1))

    def test_melhores_sao_os_5_com_mais_views(self):
        self.assertEqual([v["views"] for v in self.m["melhores"]], [9000, 8500, 8000, 7500, 7000])
        self.assertEqual(self.m["melhores"][0]["titulo"], "12 lições estoicas para ouvir toda manhã")

    def test_piores_nao_incluem_video_recente_que_ainda_nao_juntou_views(self):
        piores = self.m["piores"]
        self.assertEqual([v["views"] for v in piores], [900, 1000, 1100, 1200, 1500])
        self.assertNotIn("Como ter um dia mais produtivo com estoicismo", [v["titulo"] for v in piores])     # 3 dias, 900 views
        self.assertTrue(all(v["idade_dias"] >= 14 for v in piores))

    def test_o_que_o_app_nao_coleta_fica_none_e_nao_zero(self):
        self.assertIsNone(self.m["monetizado"])
        self.assertIsNone(self.m["shorts"])

    def test_canal_sem_dados_nao_inventa_numeros(self):
        m = cn.metricas_canal({"canal": "Vazio"}, AGORA)
        for campo in ("inscritos", "views_totais", "views_por_video", "views_mensais_medias", "uploads_por_mes_vida", "tracao",
                      "mediana_ultimos", "duracao_media_seg", "titulo_medio_chars", "dias_de_vida"):
            self.assertIsNone(m[campo], campo)
        self.assertEqual((m["melhores"], m["piores"], m["amostra_n"]), ([], [], 0))

    def test_canal_com_menos_de_um_mes_nao_projeta_views_mensais(self):
        m = cn.metricas_canal(registro(data_criacao_canal=dia(10)), AGORA)
        self.assertEqual(m["dias_de_vida"], 10)
        self.assertIsNone(m["views_mensais_medias"])
        self.assertIsNone(m["uploads_por_mes_vida"])

    def test_zero_videos_ou_inscritos_nao_divide_por_zero(self):
        m = cn.metricas_canal(registro(n_videos=0, inscritos_num=0), AGORA)
        self.assertIsNone(m["views_por_video"])
        self.assertIsNone(m["tracao"])

    def test_video_sem_data_mantem_a_ordem_da_coleta_e_sem_views_e_ignorado(self):
        c = registro()
        c["amostra_videos"][0]["data"] = ""
        c["amostra_videos"][1]["views_num"] = None
        m = cn.metricas_canal(c, AGORA)
        self.assertEqual(m["amostra_n"], 16)
        self.assertEqual(m["amostra_com_views"], 15)
        self.assertIsNotNone(m["mediana_ultimos"])

    def test_videos_da_amostra_traz_idade_views_por_dia_e_duracao(self):
        v = {x["indice"]: x for x in cn.videos_da_amostra(registro(), AGORA)}
        # a lista foi montada de trás para frente: o índice segue a posição na amostra guardada
        um_lista = [x for x in v.values() if x["titulo"].startswith("12 lições")][0]
        self.assertEqual((um_lista["idade_dias"], um_lista["views"], um_lista["views_dia"], um_lista["duracao_seg"]), (30, 9000, 300.0, 600))


class PadroesDeTituloTests(unittest.TestCase):
    def setUp(self):
        self.p = cn.padroes_de_titulo(cn.videos_da_amostra(registro(), AGORA))
        self.por = {x["chave"]: x for x in self.p["padroes"]}

    def test_video_recente_fica_de_fora_da_comparacao(self):
        self.assertEqual((self.p["n_videos_considerados"], self.p["idade_min_dias"]), (15, 14))

    def test_como_compara_a_mediana_com_e_sem_a_estrutura(self):
        x = self.por["como"]
        self.assertEqual((x["n_com"], x["n_sem"], x["mediana_com"], x["mediana_sem"], x["razao"]), (3, 12, 7000, 1900, 3.68))
        self.assertTrue(x["amostra_pequena"])                                         # só 3 vídeos com "Como"

    def test_numero_no_inicio(self):
        x = self.por["numero_inicio"]
        self.assertEqual((x["n_com"], x["n_sem"], x["mediana_com"], x["mediana_sem"], x["razao"]), (3, 12, 8500, 1900, 4.47))

    def test_estrutura_que_pega_os_mesmos_videos_de_outra_ja_listada_nao_repete(self):
        # no exemplo todo título com número começa com número: "Tem número" seria a mesma linha de "Começa com número"
        self.assertIn("numero_inicio", self.por)
        self.assertNotIn("tem_numero", self.por)

    def test_tem_numero_aparece_quando_pega_videos_diferentes_de_comeca_com_numero(self):
        titulos = ["7 dicas de calma", "5 hábitos simples", "3 erros comuns", "Os 5 segredos da rotina", "Guia de 10 minutos", "Prática de 2 horas",
                   "Sobre a paciência", "Filosofia do dia", "Mente tranquila", "Respirar melhor", "Foco total", "Sono profundo"]
        videos = [{"titulo": t, "views": 1000 + i * 100, "idade_dias": 60, "indice": i} for i, t in enumerate(titulos, 1)]
        por = {x["chave"]: x for x in cn.padroes_de_titulo(videos)["padroes"]}
        self.assertEqual((por["numero_inicio"]["n_com"], por["tem_numero"]["n_com"]), (3, 6))

    def test_padrao_com_poucas_ocorrencias_nao_aparece(self):
        self.assertNotIn("pergunta", self.por)                                        # só 2 títulos
        self.assertNotIn("comando", self.por)                                         # só 2 títulos
        self.assertNotIn("maiuscula", self.por)

    def test_ordenados_pela_razao_e_todos_respeitam_o_minimo(self):
        razoes = [x["razao"] for x in self.p["padroes"]]
        self.assertEqual(razoes, sorted(razoes, reverse=True))
        self.assertTrue(all(x["n_com"] >= 3 and x["n_sem"] >= 3 for x in self.p["padroes"]))

    def test_palavra_chave_mais_repetida_e_quantas_vezes_termina_o_titulo(self):
        self.assertEqual([x["palavra"] for x in self.p["palavras_chave"]], ["estoicismo"])
        k = self.p["palavras_chave"][0]
        self.assertEqual((k["titulos"], k["terminam_com"], k["mediana_com"], k["mediana_sem"]), (6, 3, 4000, 5000))

    def test_palavras_comuns_nao_viram_palavra_chave(self):
        r = cn.palavras_chave(["como fazer isso para você", "como fazer aquilo para você", "como fazer tudo para você"])
        self.assertEqual(r, [])          # tudo que se repete aqui é palavra comum

    def test_poucos_videos_maduros_usa_todos_e_diz_que_nao_filtrou(self):
        pequeno = registro(amostra=AMOSTRA[:8])
        p = cn.padroes_de_titulo(cn.videos_da_amostra(pequeno, AGORA))
        self.assertEqual((p["n_videos_considerados"], p["idade_min_dias"]), (8, 0))

    def test_sem_videos_devolve_vazio(self):
        p = cn.padroes_de_titulo([])
        self.assertEqual((p["padroes"], p["palavras_chave"], p["n_videos_considerados"]), ([], [], 0))


def analise_pronta(**extra):
    dados = cn.montar_dados(registro(), AGORA)
    return {"id": 1, "canal": dados["canal"]["nome"], "canal_url": dados["canal"]["url"], "criado_em": dados["coletado_em"], "dados": dados, "ia": extra.get("ia", {})}


class PromptsTests(unittest.TestCase):
    def test_prompt_de_categorias_lista_os_videos_com_indice_views_e_idade(self):
        p = cn.montar_prompt_categorias(analise_pronta()["dados"])
        self.assertIn('Canal: "Estoico Exemplo"', p)
        self.assertIn("inscritos: 8.500", p)
        self.assertIn("mediana de views dos últimos 10 vídeos: 4.000", p)
        self.assertIn("no ar há 5,3 meses", p)                         # vírgula decimal: o ponto é o separador de milhar
        self.assertIn("7,6 vídeos por mês", p)
        self.assertNotRegex(p, r"\d\.\d(?!\d{2}\b)\D")                 # nenhum decimal com ponto solto no prompt
        self.assertRegex(p, r'\n\d+\. "12 lições estoicas para ouvir toda manhã" — 9\.000 views, há 30 dias')
        self.assertIn('{"categorias": [{"nome": "", "descricao": "", "indices": [1, 2]}]}', p)
        self.assertIn("NO MÁXIMO uma categoria", p)
        self.assertIn("o app calcula", p)

    def test_prompt_de_categorias_exige_um_minimo_de_videos(self):
        dados = cn.montar_dados(registro(amostra=AMOSTRA[:4]), AGORA)
        with self.assertRaisesRegex(ValueError, "Poucos vídeos"):
            cn.montar_prompt_categorias(dados)

    def test_prompt_de_categorias_respeita_o_limite(self):
        p = cn.montar_prompt_categorias(analise_pronta()["dados"], limite=7)
        self.assertIn("(7):", p)
        self.assertNotIn('8. "', p)

    def test_prompt_de_estrategia_traz_so_dados_e_proibe_saturacao_inventada(self):
        p = cn.montar_prompt_estrategia(analise_pronta(), "DE", "Quero um canal em alemão sobre estoicismo aplicado")
        self.assertIn("SOMENTE com os dados abaixo", p)
        self.assertIn("Vídeos com mais views", p)
        self.assertIn('"12 lições estoicas para ouvir toda manhã" — 9.000 views', p)
        self.assertIn("já com mais de 14 dias no ar", p)
        self.assertIn("Estruturas de título", p)
        self.assertIn("razão 4,47×", p)
        self.assertIn("estoicismo (6)", p)
        self.assertIn("Alemanha — títulos em alemão", p)
        self.assertIn("Meu objetivo: Quero um canal em alemão", p)
        self.assertIn("sem evidência nos dados", p)
        self.assertIn("NÃO invente porcentagens", p)
        self.assertIn('"topicos_sugeridos"', p)

    def test_prompt_de_estrategia_nao_poe_o_video_recente_entre_os_piores(self):
        p = cn.montar_prompt_estrategia(analise_pronta())
        piores = p.split("Vídeos com menos views")[1].split("\n\n")[0]
        self.assertNotIn("Como ter um dia mais produtivo", piores)

    def test_prompt_de_estrategia_usa_categorias_e_comentarios_quando_existem(self):
        a = analise_pronta()
        idx = {v["titulo"]: v["indice"] for v in a["dados"]["videos"]}
        cats = [{"nome": "Listas", "descricao": "", "indices": [idx["12 lições estoicas para ouvir toda manhã"], idx["5 hábitos estoicos que mudam sua vida"],
                                                                 idx["3 lições de Sêneca para ansiedade"]]}]
        est, _ = cn.estatisticas_categorias(cats, a["dados"]["videos"])
        ia = {"categorias": {"categorias": cats, "estatisticas": est},
              "comentarios": {"gostaram": [{"tema": "voz calma"}], "nao_gostaram": [{"tema": "áudio baixo"}], "pedidos": [{"pedido": "vídeos mais curtos"}]}}
        p = cn.montar_prompt_estrategia({**a, "ia": ia})
        self.assertIn("Categorias do canal", p)
        self.assertIn("Listas: 3 vídeos, mediana 8.500", p)
        self.assertIn("elogia: voz calma", p)
        self.assertIn("critica: áudio baixo", p)
        self.assertIn("pede: vídeos mais curtos", p)

    def test_objetivo_gigante_e_cortado_e_mercado_desconhecido_cai_no_brasil(self):
        p = cn.montar_prompt_estrategia(analise_pronta(), "XX", "a" * 5000)
        self.assertIn("Brasil", p)
        self.assertLess(p.count("a"), 5000)
        self.assertLessEqual(len(p.split("Meu objetivo: ")[1].split("\n")[0]), 600)

    def test_comentarios_limpa_duplicados_vazios_e_exige_o_minimo(self):
        texto = "Ótimo vídeo\n\n  ótimo   vídeo  \nx\nÁudio ruim demais\nAdorei a voz\nQuero mais sobre Sêneca\nQuando sai o próximo?"
        self.assertEqual(cn.limpar_comentarios(texto), ["Ótimo vídeo", "Áudio ruim demais", "Adorei a voz", "Quero mais sobre Sêneca", "Quando sai o próximo?"])
        p = cn.montar_prompt_comentarios(analise_pronta()["dados"], texto)
        self.assertIn("5 comentários", p)
        self.assertIn("- Áudio ruim demais", p)
        self.assertIn("quantos_comentarios", p)
        self.assertIn("não invente comentários", p)
        with self.assertRaisesRegex(ValueError, "pelo menos 5"):
            cn.montar_prompt_comentarios(analise_pronta()["dados"], "só um\ndois")
        with self.assertRaises(ValueError):
            cn.montar_prompt_comentarios(analise_pronta()["dados"], "")

    def test_comentarios_respeita_limites_de_quantidade_e_tamanho(self):
        muitos = "\n".join(f"comentário número {i}" for i in range(500))
        self.assertEqual(len(cn.limpar_comentarios(muitos)), cn.MAX_COMENTARIOS)
        enormes = "\n".join(("palavra " * 70) + str(i) for i in range(100))
        self.assertLessEqual(sum(len(c) for c in cn.limpar_comentarios(enormes)), cn.MAX_CHARS_COMENTARIOS)
        self.assertTrue(all(len(c) <= 600 for c in cn.limpar_comentarios("x" * 3000 + " ok")))


class ValidacaoTests(unittest.TestCase):
    def test_categorias_descartam_indices_invalidos_repetidos_e_categorias_vazias(self):
        texto = json.dumps({"categorias": [
            {"nome": "Como fazer", "descricao": "Guias práticos", "indices": [1, 2, 7, 12]},
            {"nome": "Listas", "indices": [3, 10, 16, 2]},                       # o 2 já é da primeira
            {"nome": "Filósofos", "indices": [6, 8, 9, 13, 99, "x", 0]},          # 99, "x" e 0 não existem
            {"nome": "Vazia", "indices": [500]},
            {"indices": [4]},                                                     # sem nome
        ]})
        cats = cn.validar_categorias(texto, 16)
        self.assertEqual([(c["nome"], c["indices"]) for c in cats],
                         [("Como fazer", [1, 2, 7, 12]), ("Listas", [3, 10, 16]), ("Filósofos", [6, 8, 9, 13])])
        self.assertEqual(cats[0]["descricao"], "Guias práticos")

    def test_categorias_aceita_cerca_de_markdown_texto_em_volta_e_lista_solta(self):
        cats = cn.validar_categorias('Claro! Aqui está:\n```json\n{"Categorias": [{"Nome": "A", "Indices": [1, 2]}]}\n```\nEspero ter ajudado.', 5)
        self.assertEqual(cats[0]["nome"], "A")
        cats = cn.validar_categorias('[{"nome": "B", "indices": [3]}]', 5)
        self.assertEqual(cats[0]["indices"], [3])

    def test_categorias_sem_nada_util_da_erro_em_portugues(self):
        for lixo in ('{"categorias": []}', '{"outra": 1}', '{"categorias": [{"nome": "X", "indices": [99]}]}'):
            with self.assertRaisesRegex(ValueError, "categorias"):
                cn.validar_categorias(lixo, 16)
        with self.assertRaises(ValueError):
            cn.validar_categorias("isso não é json", 16)
        with self.assertRaisesRegex(ValueError, "Cole o JSON"):
            cn.validar_categorias("", 16)

    def test_estatisticas_das_categorias_sao_calculadas_aqui_e_ordenadas_pela_mediana(self):
        videos = cn.videos_da_amostra(registro(), AGORA)
        # os índices dos prompts são a posição na amostra guardada (que está de trás para frente)
        idx = {v["titulo"]: v["indice"] for v in videos}
        cats = [
            {"nome": "Como fazer", "descricao": "", "indices": [idx["Como ter um dia mais produtivo com estoicismo"], idx["Como parar de reclamar da vida com estoicismo"],
                                                                idx["Como controlar suas emoções segundo o estoicismo"], idx["Como lidar com pessoas difíceis usando o estoicismo"]]},
            {"nome": "Listas", "descricao": "", "indices": [idx["12 lições estoicas para ouvir toda manhã"], idx["5 hábitos estoicos que mudam sua vida"], idx["3 lições de Sêneca para ansiedade"]]},
            {"nome": "Filósofos", "descricao": "", "indices": [idx["Marco Aurélio e a arte de aceitar"], idx["Sêneca sobre o tempo"], idx["Epicteto explica a liberdade"], idx["Meditações de Marco Aurélio resumo"]]},
        ]
        est, sem = cn.estatisticas_categorias(cats, videos)
        self.assertEqual([e["nome"] for e in est], ["Listas", "Como fazer", "Filósofos"])
        listas, como, filos = est
        self.assertEqual((listas["n"], listas["mediana_views"], listas["media_views"]), (3, 8500, 8000))
        self.assertEqual((como["n"], como["mediana_views"], como["media_views"], como["share"]), (4, 6500, 5350, 0.25))
        self.assertEqual((filos["n"], filos["mediana_views"], filos["media_views"]), (4, 1100, 1150))
        self.assertEqual(como["melhor"]["views"], 7500)
        self.assertEqual(sem, 5)

    def test_estrategia_normaliza_aliases_e_limita_listas(self):
        texto = json.dumps({
            "Padroes_de_Desempenho": [{"padrao": "Números no início", "evidencia": "3 dos 5 melhores", "confianca": "media"}, {"padrao": ""}],
            "formula_de_conteudo": {"promessa_central": "Calma diária", "estrutura_do_titulo": "Número + benefício"},
            "publico": {"quem_e": "Adultos 25-40", "gatilhos_emocionais": "ansiedade; cansaço; esperança"},
            "oportunidades": [{"oportunidade": "Estoicismo no trabalho", "como_diferenciar": "casos reais", "risco": "nicho lotado"}, "Estoicismo para pais"],
            "topicos_sugeridos": [{"topico": "5 hábitos estoicos para o trabalho", "por_que": "número no início"}] * 20,
            "roteiro": {"gancho": "Pergunta forte"}, "riscos_e_ressalvas": ["amostra pequena"]})
        e = cn.validar_estrategia(texto)
        self.assertEqual(e["padroes_de_desempenho"], [{"padrao": "Números no início", "evidencia": "3 dos 5 melhores", "confianca": "media"}])
        self.assertEqual(e["publico"]["gatilhos_emocionais"], ["ansiedade", "cansaço", "esperança"])
        self.assertEqual([o["oportunidade"] for o in e["oportunidades"]], ["Estoicismo no trabalho", "Estoicismo para pais"])
        self.assertEqual(len(e["topicos_sugeridos"]), 15)
        self.assertEqual(e["topicos_sugeridos"][0], {"titulo": "5 hábitos estoicos para o trabalho", "angulo": "", "por_que_deve_funcionar": "número no início"})
        self.assertEqual(e["roteiro"], {"gancho": "Pergunta forte", "desenvolvimento": "", "fechamento": ""})
        self.assertEqual(e["riscos_e_ressalvas"], ["amostra pequena"])

    def test_estrategia_sem_nenhum_campo_util_da_erro(self):
        for lixo in ('{}', '{"foo": 1}', '{"oportunidades": [], "roteiro": {}}', '[1, 2]'):
            with self.assertRaises(ValueError, msg=lixo):
                cn.validar_estrategia(lixo)

    def test_comentarios_normaliza_e_conta_como_numero(self):
        texto = '```json\n' + json.dumps({
            "gostaram": [{"tema": "Voz calma", "quantos_comentarios": "12 comentários", "exemplo": "adoro a voz"}],
            "nao_gostaram": [{"tema": "Áudio", "quantidade": 4}, {"tema": ""}],
            "pedidos": ["mais vídeos de Sêneca", {"pedido": "legendas", "exemplo": "coloca legenda"}],
            "perguntas_frequentes": "Quando sai o próximo?; Qual livro começar?",
            "discussoes": [{"tema": "Estoicismo é frio?", "posicoes": ["sim, reprime", "não, regula"]}, "Religião e estoicismo"],
            "ideias_de_video": [{"titulo": "Estoicismo para quem tem ansiedade", "dor": "ansiedade constante"}]}) + '\n```'
        c = cn.validar_comentarios(texto)
        self.assertEqual(c["gostaram"], [{"tema": "Voz calma", "quantos_comentarios": 12, "exemplo": "adoro a voz"}])
        self.assertEqual(c["nao_gostaram"], [{"tema": "Áudio", "quantos_comentarios": 4, "exemplo": ""}])
        self.assertEqual([p["pedido"] for p in c["pedidos"]], ["mais vídeos de Sêneca", "legendas"])
        self.assertEqual(c["perguntas_frequentes"], ["Quando sai o próximo?", "Qual livro começar?"])
        self.assertEqual(c["discussoes"], [{"tema": "Estoicismo é frio?", "posicoes": ["sim, reprime", "não, regula"]},
                                           {"tema": "Religião e estoicismo", "posicoes": []}])
        self.assertEqual(c["ideias_de_video"], [{"titulo": "Estoicismo para quem tem ansiedade", "dor_que_resolve": "ansiedade constante"}])

    def test_comentarios_sem_nada_util_da_erro(self):
        for lixo in ('{}', '{"gostaram": [], "pedidos": []}', 'texto sem json'):
            with self.assertRaises(ValueError, msg=lixo):
                cn.validar_comentarios(lixo)


class PersistenciaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = os.path.join(self._tmp.name, "t.db")

    def salvar(self, **extra):
        return cn.salvar_analise(registro(**extra), AGORA, self.db)

    def test_salva_lista_e_recupera_com_tudo_calculado(self):
        aid = self.salvar()
        lista = cn.listar_analises(self.db)
        self.assertEqual([(a["id"], a["canal"], a["inscritos"], a["amostra_n"]) for a in lista], [(aid, "Estoico Exemplo", 8500, 16)])
        a = cn.obter_analise(aid, self.db)
        self.assertEqual(a["canal_url"], "https://www.youtube.com/@estoicoexemplo")
        self.assertEqual(a["dados"]["metricas"]["mediana_ultimos"], 4000)
        self.assertEqual(len(a["dados"]["videos"]), 16)
        self.assertEqual(a["dados"]["coletado_em"], "2026-09-21T12:00:00")
        self.assertEqual(a["ia"], {})

    def test_lista_mais_recente_primeiro_e_nao_mistura_analises_do_mesmo_canal(self):
        a1, a2 = self.salvar(), self.salvar(inscritos_num=9000)
        self.assertEqual([x["id"] for x in cn.listar_analises(self.db)], [a2, a1])
        self.assertEqual(cn.obter_analise(a1, self.db)["dados"]["metricas"]["inscritos"], 8500)
        self.assertEqual(cn.obter_analise(a2, self.db)["dados"]["metricas"]["inscritos"], 9000)

    def test_ia_grava_recalcula_estatisticas_e_pode_ser_apagada(self):
        aid = self.salvar()
        a = cn.obter_analise(aid, self.db)
        idx = {v["titulo"]: v["indice"] for v in a["dados"]["videos"]}
        cats = [{"nome": "Listas", "descricao": "", "indices": [idx["12 lições estoicas para ouvir toda manhã"], idx["5 hábitos estoicos que mudam sua vida"]]}]
        a = cn.gravar_ia(aid, "categorias", {"categorias": cats}, self.db)
        self.assertEqual(a["ia"]["categorias"]["estatisticas"][0]["mediana_views"], 8750)              # (9000 + 8500) / 2
        self.assertEqual(a["ia"]["categorias"]["sem_categoria"], 14)
        self.assertIn("aplicado_em", a["ia"]["categorias"])
        self.assertEqual(cn.obter_analise(aid, self.db)["ia"]["categorias"]["estatisticas"][0]["n"], 2)   # persistiu
        a = cn.gravar_ia(aid, "categorias", None, self.db)
        self.assertNotIn("categorias", a["ia"])

    def test_tipos_da_ia_sao_independentes(self):
        aid = self.salvar()
        cn.gravar_ia(aid, "estrategia", {"oportunidades": [{"oportunidade": "x"}]}, self.db)
        a = cn.gravar_ia(aid, "comentarios", {"pedidos": [{"pedido": "y"}]}, self.db)
        self.assertEqual(set(a["ia"]), {"estrategia", "comentarios"})
        a = cn.gravar_ia(aid, "estrategia", None, self.db)
        self.assertEqual(set(a["ia"]), {"comentarios"})

    def test_ia_tipo_invalido_e_analise_inexistente(self):
        aid = self.salvar()
        with self.assertRaises(ValueError):
            cn.gravar_ia(aid, "outro", {}, self.db)
        self.assertIsNone(cn.gravar_ia(999, "estrategia", {}, self.db))
        self.assertIsNone(cn.obter_analise(999, self.db))

    def test_excluir(self):
        aid = self.salvar()
        self.assertTrue(cn.excluir_analise(aid, self.db))
        self.assertFalse(cn.excluir_analise(aid, self.db))
        self.assertEqual(cn.listar_analises(self.db), [])

    def test_canal_sem_nome_usa_a_url_e_dados_hostis_sao_guardados_como_texto(self):
        aid = self.salvar(canal="", amostra=[(5, '<img src=x onerror="1">', 100, "1:00")])
        a = cn.obter_analise(aid, self.db)
        self.assertEqual(a["canal"], "https://www.youtube.com/@estoicoexemplo")
        self.assertEqual(a["dados"]["videos"][0]["titulo"], '<img src=x onerror="1">')


if __name__ == "__main__":
    unittest.main(verbosity=2)
