"""Lógica pura de recomendações (sem navegador), com a lateral real enviada pelo usuário."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import recomendados as rec
from recomendados_fixture import LATERAL_REAL


def bruto(t):
    """Tupla da fixture -> item bruto, no formato que o JS da página devolve."""
    vid, titulo, canal, selo, views, views_aria, quando, quando_aria, dur, novo = t
    return {"id": vid, "href": f"/watch?v={vid}", "titulo": titulo, "canal": canal, "verificado": bool(selo),
            "views_txt": views, "quando_txt": quando_aria, "quando_curto": quando, "dur_txt": dur, "novo": novo, "texto": titulo}


def itens_reais(n=15, origem="SEED0000001"):
    return [rec.normalizar_item(bruto(t), origem, f"https://www.youtube.com/watch?v={origem}", "Vídeo de origem") for t in LATERAL_REAL[:n]]


def por_canal(anotados, aprovado=True):
    return sorted(i["canal"] for i in anotados if i["aprovado"] == aprovado)


class UrlsTests(unittest.TestCase):
    def test_aceita_watch_youtu_be_e_live_e_padroniza(self):
        alvo = "https://www.youtube.com/watch?v=yHx7y4RYNIw"
        for texto in ["https://www.youtube.com/watch?v=yHx7y4RYNIw", "youtube.com/watch?v=yHx7y4RYNIw&t=3s&list=RD1",
                      "https://youtu.be/yHx7y4RYNIw?si=xyz", "https://www.youtube.com/watch?feature=share&v=yHx7y4RYNIw",
                      "https://www.youtube.com/live/yHx7y4RYNIw"]:
            self.assertEqual(rec.normalizar_url_video(texto), (alvo, "yHx7y4RYNIw"), texto)

    def test_rejeita_o_que_nao_e_video_com_lateral(self):
        for texto in ["https://www.youtube.com/shorts/yHx7y4RYNIw", "https://www.youtube.com/@canal", "texto solto", "", None,
                      "https://www.youtube.com/watch?v=curto"]:
            self.assertIsNone(rec.normalizar_url_video(texto), texto)

    def test_separar_urls_tira_repetidos_separa_invalidos_e_limita(self):
        texto = "https://youtu.be/aaaaaaaaaaa\n\nhttps://www.youtube.com/watch?v=aaaaaaaaaaa&t=1\nlixo\nhttps://www.youtube.com/watch?v=bbbbbbbbbbb"
        validas, invalidas, cortadas = rec.separar_urls(texto)
        self.assertEqual([u[-11:] for u in validas], ["aaaaaaaaaaa", "bbbbbbbbbbb"])
        self.assertEqual(invalidas, ["lixo"])
        self.assertEqual(cortadas, 0)
        muitas = "\n".join(f"https://youtu.be/{i:011d}" for i in range(25))
        validas, _, cortadas = rec.separar_urls(muitas)
        self.assertEqual((len(validas), cortadas), (rec.MAX_ORIGENS, 5))

    def test_url_de_canal_fica_no_formato_canonico_mesmo_com_handle_nao_latino(self):
        esperado = "https://www.youtube.com/@%D0%9D%D0%98%D0%98%D0%90%D0%9D"
        for href in ["/@%D0%9D%D0%98%D0%98%D0%90%D0%9D", "http://www.youtube.com/@НИИАН/", "https://www.youtube.com/@%D0%9D%D0%98%D0%98%D0%90%D0%9D?si=1"]:
            self.assertEqual(rec.normalizar_url_canal(href), esperado, href)
        self.assertEqual(rec.normalizar_url_canal("https://www.youtube.com/channel/UCabc/"), "https://www.youtube.com/channel/UCabc")
        for ruim in ["", None, "https://www.youtube.com/watch?v=abc", "/results?search_query=x"]:
            self.assertEqual(rec.normalizar_url_canal(ruim), "", ruim)


class IdadeTests(unittest.TestCase):
    def test_idade_em_meses(self):
        casos = {"há 14 horas": 0.02, "há 14 h": 0.02, "há 30 minutos": 0, "agora": 0, "há 5 dias": 0.17, "há 3 semanas": 0.69,
                 "há 1 mês": 1, "há um mês": 1, "há 5 meses": 5, "há 1 ano": 12, "há 2 anos": 24, "3 hours ago": 0, "2 years ago": 24,
                 "Transmitido há 2 semanas": 0.46}
        for texto, esperado in casos.items():
            self.assertAlmostEqual(rec.idade_meses(texto), esperado, delta=0.02, msg=texto)

    def test_texto_que_nao_entende_vira_desconhecido_nunca_recente(self):
        for texto in ["", None, "xyz", "Estreia em breve"]:
            self.assertIsNone(rec.idade_meses(texto), texto)

    def test_semanas_nao_sao_confundidas_com_segundos(self):
        self.assertGreater(rec.idade_meses("há 3 semanas"), 0.5)


class ItemTests(unittest.TestCase):
    def test_item_real_e_normalizado(self):
        it = itens_reais(15)[8]   # Mistere
        self.assertEqual((it["canal"], it["views_num"], it["canal_verificado"], it["tipo"]), ("Mistere", 90000, False, "video"))
        self.assertEqual(it["duracao_segundos"], 32 * 60 + 56)
        self.assertAlmostEqual(it["idade_meses"], 0.1, delta=0.01)   # "há 3 dias"
        self.assertEqual(it["url"], "https://www.youtube.com/watch?v=m4Rz8S1yUqU")

    def test_views_em_milhoes_e_decimais_do_youtube(self):
        views = {it["video_id"]: it["views_num"] for it in itens_reais(21)}
        self.assertEqual(views["1Dj247BKsTI"], 1_300_000)   # 1,3 mi
        self.assertEqual(views["6COk1VYyIlY"], 1_000_000)   # 1 mi
        self.assertEqual(views["5TOmOGjFVNw"], 4_500)       # 4,5 mil
        self.assertEqual(views["c8ysBDqu38E"], 69)

    def test_item_sem_views_fica_com_views_none(self):
        self.assertIsNone(itens_reais(3)[2]["views_num"])   # Novatroop: só "há 1 ano"

    def test_tipos_short_playlist_e_live(self):
        base = {"titulo": "x", "canal": "c", "views_txt": "5 mil", "quando_txt": "há 1 dia"}
        self.assertEqual(rec.normalizar_item({**base, "id": "SHORTid0001", "href": "/shorts/SHORTid0001"})["tipo"], "short")
        self.assertEqual(rec.normalizar_item({**base, "id": "", "href": "/playlist?list=PL1"})["tipo"], "playlist")
        live = rec.normalizar_item({**base, "id": "LIVEid00001", "href": "/watch?v=LIVEid00001", "ao_vivo": True})
        self.assertEqual(live["tipo"], "live")
        self.assertIsNone(live["views_num"])   # "assistindo" não é views


class SelecaoTests(unittest.TestCase):
    def test_lateral_real_com_media_aprova_so_o_canal_que_esta_acima(self):
        # Elegíveis (não verificados e recentes): akS 69, Капитан Флинт 179, Olsior reacts 4.500, Mistere 90.000.
        anotados, rel = rec.selecionar_candidatos(itens_reais(15), {"referencia": "media", "meses_max": 3})
        g = rel["grupos"][0]
        self.assertEqual((g["coletados"], g["elegiveis"], g["valor"], g["limiar"], g["aprovados"]), (15, 4, 23687, 23687, 1))
        self.assertEqual(por_canal(anotados), ["Mistere"])
        mistere = next(i for i in anotados if i["canal"] == "Mistere")
        self.assertEqual((mistere["motivo"], mistere["razao_media"]), ("ok", 3.8))

    def test_mediana_e_menos_dominada_pelo_outlier(self):
        anotados, rel = rec.selecionar_candidatos(itens_reais(15), {"referencia": "mediana"})
        self.assertEqual(rel["grupos"][0]["valor"], 2340)        # mediana de 69, 179, 4.500 e 90.000
        self.assertEqual(por_canal(anotados), ["Mistere", "Olsior reacts"])

    def test_fator_deixa_entrar_quem_esta_perto_da_media(self):
        _, rel = rec.selecionar_candidatos(itens_reais(15), {"referencia": "media", "fator": 0.1})
        self.assertEqual(rel["grupos"][0]["limiar"], 2369)
        anotados, _ = rec.selecionar_candidatos(itens_reais(15), {"referencia": "media", "fator": 0.1})
        self.assertEqual(por_canal(anotados), ["Mistere", "Olsior reacts"])

    def test_cada_descarte_tem_o_motivo_certo(self):
        anotados, rel = rec.selecionar_candidatos(itens_reais(21))
        motivo = {i["video_id"]: i["motivo"] for i in anotados}
        self.assertEqual(motivo["iOL2SMkyn3I"], "verificado")           # ANCAPSU (check)
        self.assertEqual(motivo["tJiTPwVVrXw"], "verificado")           # 7 Minutoz (selo recortado)
        self.assertEqual(motivo["XBODjgZ6hyY"], "antigo")               # Viktor Galvão, há 2 anos
        self.assertEqual(motivo["c8ysBDqu38E"], "abaixo_da_media")      # akS, 69 views
        self.assertEqual(motivo["m4Rz8S1yUqU"], "ok")
        self.assertEqual(rel["grupos"][0]["excluidos"]["verificado"], 14)   # 14 dos 21 têm selo

    def test_os_21_itens_mudam_a_media_e_o_diego_alex_nao_passa(self):
        anotados, rel = rec.selecionar_candidatos(itens_reais(21))
        g = rel["grupos"][0]
        self.assertEqual((g["elegiveis"], g["valor"]), (6, 17966))      # 69, 179, 4.500, 90.000, 49 e 13.000
        self.assertEqual(por_canal(anotados), ["Mistere"])

    def test_filtro_de_duracao_em_minutos(self):
        anotados, rel = rec.selecionar_candidatos(itens_reais(15), {"duracao_min": 15})
        motivo = {i["canal"]: i["motivo"] for i in anotados if i["canal"] in ("Olsior reacts", "Mistere")}
        self.assertEqual(motivo["Olsior reacts"], "duracao")            # 11:13 < 15 min
        self.assertEqual(rel["grupos"][0]["elegiveis"], 3)
        anotados, _ = rec.selecionar_candidatos(itens_reais(15), {"duracao_max": 25})
        self.assertEqual({i["canal"]: i["motivo"] for i in anotados}["Mistere"], "duracao")   # 32:56 > 25 min

    def test_janela_de_meses_mais_larga_traz_o_video_de_2_anos_para_o_pool(self):
        anotados, rel = rec.selecionar_candidatos(itens_reais(21), {"meses_max": 36})
        self.assertEqual(rel["grupos"][0]["elegiveis"], 7)              # entra o Viktor Galvão (3,4 mil)
        self.assertEqual({i["video_id"]: i["motivo"] for i in anotados}["XBODjgZ6hyY"], "abaixo_da_media")

    def test_nao_video_patrocinado_sem_views_e_idade_desconhecida(self):
        base = {"titulo": "t", "canal": "Canal", "verificado": False, "views_txt": "10 mil", "quando_txt": "há 2 dias", "dur_txt": "10:00", "texto": "t"}
        brutos = [
            {**base, "id": "aaaaaaaaaa1", "href": "/watch?v=aaaaaaaaaa1"},
            {**base, "id": "aaaaaaaaaa2", "href": "/shorts/aaaaaaaaaa2"},
            {**base, "id": "aaaaaaaaaa3", "href": "/watch?v=aaaaaaaaaa3", "texto": "Patrocinado"},
            {**base, "id": "aaaaaaaaaa4", "href": "/watch?v=aaaaaaaaaa4", "views_txt": ""},
            {**base, "id": "aaaaaaaaaa5", "href": "/watch?v=aaaaaaaaaa5", "quando_txt": "estreia em breve"},
        ]
        itens = [rec.normalizar_item(b, "O", "u", "T") for b in brutos]
        anotados, _ = rec.selecionar_candidatos(itens)
        self.assertEqual([i["motivo"] for i in anotados], ["ok", "nao_video", "patrocinado", "sem_views", "idade_desconhecida"])

    def test_video_repetido_em_duas_laterais_conta_uma_vez(self):
        a, b = itens_reais(15, "ORIGEMAAAA1"), itens_reais(15, "ORIGEMBBBB2")
        anotados, _ = rec.selecionar_candidatos(a + b)
        self.assertEqual(sum(1 for i in anotados if i["motivo"] == "duplicado"), 15)
        self.assertEqual(sum(1 for i in anotados if i["aprovado"]), 1)

    def test_pool_pequeno_e_marcado_como_pouco_confiavel_e_pool_vazio_nao_quebra(self):
        so_verificados = [i for i in itens_reais(15) if i["canal_verificado"]]
        anotados, rel = rec.selecionar_candidatos(so_verificados)
        g = rel["grupos"][0]
        self.assertEqual((g["elegiveis"], g["valor"], g["limiar"], g["aprovados"], g["pouco_confiavel"]), (0, None, None, 0, False))
        _, rel = rec.selecionar_candidatos(itens_reais(15))
        self.assertFalse(rel["grupos"][0]["pouco_confiavel"])          # 4 elegíveis já dá uma média razoável
        um = [i for i in itens_reais(15) if i["canal"] == "Mistere"]
        _, rel = rec.selecionar_candidatos(um)
        self.assertTrue(rel["grupos"][0]["pouco_confiavel"])
        self.assertEqual(rel["grupos"][0]["aprovados"], 1)

    def test_lista_vazia(self):
        anotados, rel = rec.selecionar_candidatos([])
        self.assertEqual((anotados, rel["grupos"], rel["totais"]), ([], [], {"coletados": 0, "aprovados": 0}))

    def test_escopo_por_video_usa_uma_media_para_cada_lateral(self):
        a = itens_reais(15, "ORIGEMAAAA1")
        # lateral B: um único não verificado recente, com poucas views; sozinho ele é a própria média
        b = [rec.normalizar_item({"id": "bbbbbbbbbb1", "href": "/watch?v=bbbbbbbbbb1", "titulo": "Pequeno", "canal": "Pequeno Canal", "verificado": False,
                                  "views_txt": "300", "quando_txt": "há 2 dias", "dur_txt": "8:00", "texto": "Pequeno"}, "ORIGEMBBBB2", "u", "B")]
        anotados, rel = rec.selecionar_candidatos(a + b, {"escopo": "por_video"})
        self.assertEqual([g["valor"] for g in rel["grupos"]], [23687, 300])
        self.assertEqual(por_canal(anotados), ["Mistere", "Pequeno Canal"])

    def test_escopo_global_junta_as_laterais_numa_media_so(self):
        a = itens_reais(15, "ORIGEMAAAA1")
        b = [rec.normalizar_item({"id": "bbbbbbbbbb1", "href": "/watch?v=bbbbbbbbbb1", "titulo": "Pequeno", "canal": "Pequeno Canal", "verificado": False,
                                  "views_txt": "300", "quando_txt": "há 2 dias", "dur_txt": "8:00", "texto": "Pequeno"}, "ORIGEMBBBB2", "u", "B")]
        anotados, rel = rec.selecionar_candidatos(a + b, {"escopo": "global"})
        self.assertEqual(len(rel["grupos"]), 1)
        g = rel["grupos"][0]
        self.assertEqual((g["elegiveis"], g["valor"]), (5, 19010))      # (69 + 179 + 4.500 + 90.000 + 300) / 5 = 19.009,6
        self.assertEqual(por_canal(anotados), ["Mistere"])
        self.assertEqual({o["origem_id"] for o in g["origens"]}, {"ORIGEMAAAA1", "ORIGEMBBBB2"})

    def test_nao_altera_a_lista_de_entrada(self):
        itens = itens_reais(15)
        copia = [dict(i) for i in itens]
        rec.selecionar_candidatos(itens)
        self.assertEqual(itens, copia)


class ConfigTests(unittest.TestCase):
    def test_limites_e_valores_invalidos_voltam_ao_padrao_ou_sao_limitados(self):
        c = rec.normalizar_cfg({"max_itens": 999, "meses_max": 0, "fator": "abc", "referencia": "moda", "escopo": "x", "duracao_min": -5})
        self.assertEqual((c["max_itens"], c["meses_max"], c["fator"], c["referencia"], c["escopo"], c["duracao_min"]), (40, 1, 1.0, "media", "por_video", 0))
        self.assertEqual(rec.normalizar_cfg(None), rec.CFG_PADRAO)
        self.assertEqual(rec.normalizar_cfg({"fator": "0,8"})["fator"], 0.8)


class PromptTests(unittest.TestCase):
    CANAIS = [{"canal": "Mistere", "canal_url": "https://www.youtube.com/@mistere", "inscritos_num": 12000, "n_videos": 9,
               "views_totais": 350000, "pais_canal": "BR", "idioma_canal": "pt", "top_3_populares": [{"titulo": "Popular do Mistere"}]},
              {"canal": "Sem dados", "canal_url": "https://www.youtube.com/@sd"}]
    VIDEOS = [{"canal_url": "https://www.youtube.com/@mistere", "titulo": "Estão Me Perseguindo...", "views_num": 90000},
              {"canal_url": "https://www.youtube.com/@mistere", "titulo": "Outro vídeo", "views_num": 100}]

    def test_prompt_lista_canais_titulos_e_pede_o_mesmo_json_do_passo_1(self):
        p = rec.montar_prompt_subnichos_de_canais(self.CANAIS, self.VIDEOS)
        for trecho in ['1. "Mistere"', "12.000 inscritos", "9 vídeos", "país BR", '"Estão Me Perseguindo..."', '2. "Sem dados" — sem dados',
                       '{"subnichos": [{"nome": "nome do subnicho", "termos": ["termo 1", "termo 2"]}]}', "5 subnichos", "termos de busca em inglês"]:
            self.assertIn(trecho, p)
        self.assertLess(p.index("Estão Me Perseguindo"), p.index("Outro vídeo"))    # o mais visto primeiro

    def test_sem_videos_usa_os_populares_do_canal_e_respeita_o_limite(self):
        p = rec.montar_prompt_subnichos_de_canais(self.CANAIS, None, max_canais=1)
        self.assertIn("Popular do Mistere", p)
        self.assertNotIn("Sem dados", p)

    def test_sem_canais_da_erro_claro(self):
        with self.assertRaises(ValueError):
            rec.montar_prompt_subnichos_de_canais([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
