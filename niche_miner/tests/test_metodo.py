"""Fórmulas do método (static/metodo.js), executadas no Node real. Valores calculados à mão."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULO = json.dumps(str(ROOT / "static" / "metodo.js"))
AGORA = "new Date(2026, 8, 21)"     # 21/09/2026


def node(expressao):
    js = f"const M = require({MODULO}); const agora = {AGORA}; process.stdout.write(JSON.stringify({expressao}));"
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def v(data, views, titulo=None):
    return {"titulo": titulo or f"vídeo {data}", "url": f"https://youtu.be/{data}", "views_num": views, "data": data}


# 12 vídeos fora de ordem. Os 10 mais recentes: 9000 1000 1200 800 1100 900 1000 700 1300 1000 -> mediana 1000, média 1800.
# Os dois mais antigos (viral de janeiro/fevereiro) ficam de fora dos "últimos 10".
AMOSTRA = [
    v("2026-01-01", 500000), v("2026-09-10", 1000), v("2026-08-12", 900), v("2026-09-18", 9000), v("2026-07-22", 1300),
    v("2026-09-03", 1200), v("2026-02-01", 400000), v("2026-08-28", 800), v("2026-07-15", 1000), v("2026-08-20", 1100),
    v("2026-08-05", 1000), v("2026-07-30", 700),
]


def canal(inscritos=500, amostra=None, **extra):
    c = {"canal": "Canal X", "canal_url": "https://www.youtube.com/@x", "inscritos_num": inscritos, "n_videos": 12,
         "videos_ultimos_30d": 3, "data_criacao_canal": "2026-04-14", "amostra_videos": AMOSTRA if amostra is None else amostra}
    c.update(extra)
    return c


def metricas(c, opcoes="{}"):
    return node(f"M.metricasCanal({json.dumps(c)}, {{agora, ...{opcoes}}})")


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class MedianaTests(unittest.TestCase):
    def test_mediana_impar_par_e_dados_ruins(self):
        self.assertEqual(node("M.mediana([5, 1, 3])"), 3)
        self.assertEqual(node("M.mediana([4, 1, 3, 2])"), 2.5)
        self.assertEqual(node("M.mediana([1, null, '', 'x', 3, undefined])"), 2)
        self.assertIsNone(node("M.mediana([])"))
        self.assertIsNone(node("M.mediana(null)"))

    def test_um_video_viral_infla_a_media_mas_nao_a_mediana(self):
        # o argumento dele: 200 mil em um vídeo esconde os outros outliers do canal
        self.assertEqual(node("M.mediana([200000, 900, 800, 700, 1000])"), 900)
        self.assertEqual(node("M.media([200000, 900, 800, 700, 1000])"), 40680)


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class TracaoOutlierTests(unittest.TestCase):
    def test_tracao_e_mediana_sobre_inscritos(self):
        self.assertEqual(node("M.tracao(5000, 1000)"), 5)
        self.assertAlmostEqual(node("M.tracao(50, 1000)"), 0.05)
        for inscritos in ("0", "null", "undefined"):
            self.assertIsNone(node(f"M.tracao(1000, {inscritos})"), inscritos)
        self.assertIsNone(node("M.tracao(null, 1000)"))

    def test_faixas_de_tracao_nos_limites(self):
        chave = lambda t: node(f"M.classificarTracao({t}).chave")
        self.assertEqual(chave(0.04), "cuidado")
        self.assertEqual(chave(0.05), "intermediario")      # abaixo de 0,05 é cuidado; 0,05 já não é
        self.assertEqual(chave(2.99), "intermediario")
        self.assertEqual(chave(3), "forte")                 # a partir de 3 o algoritmo está entregando
        self.assertEqual(chave("null"), "sem_dado")
        self.assertEqual(node("M.classificarTracao(0.2, {cuidado: 0.5, forte: 1}).chave"), "cuidado")   # limites ajustáveis

    def test_fator_outlier(self):
        self.assertEqual(node("M.fatorOutlier(10000, 2000)"), 5)
        self.assertIsNone(node("M.fatorOutlier(10000, 0)"))
        self.assertIsNone(node("M.fatorOutlier(null, 2000)"))


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class DatasTests(unittest.TestCase):
    def test_idade_do_canal_do_exemplo_do_video(self):
        # ele cita canal criado em 14/04 e estamos em setembro: "faz 5 meses"
        self.assertEqual(node("M.diasDesde('2026-04-14', agora)"), 160)
        self.assertEqual(round(node("M.idadeMeses('2026-04-14', agora)"), 1), 5.3)
        self.assertIsNone(node("M.idadeMeses('', agora)"))
        self.assertIsNone(node("M.idadeMeses('lixo', agora)"))

    def test_data_no_futuro_nao_da_idade_negativa(self):
        self.assertEqual(node("M.diasDesde('2027-01-01', agora)"), 0)

    def test_views_por_hora_media_e_media_de_vida_nao_o_vph_atual(self):
        self.assertEqual(node("M.viewsPorHoraMedia(2400, '2026-09-11', agora)"), 10)     # 10 dias = 240 h
        self.assertEqual(node("M.viewsPorHoraMedia(240, '2026-09-21', agora)"), 10)      # postado hoje: conta 24 h
        self.assertIsNone(node("M.viewsPorHoraMedia(240, '', agora)"))
        # o vídeo do roteiro: 147 mil em 3 meses tem "3 VPH" no VidIQ (ritmo atual); a média de vida é outra coisa
        self.assertGreater(node("M.viewsPorHoraMedia(147000, '2026-06-23', agora)"), 60)


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class SaturacaoTests(unittest.TestCase):
    def test_semaforo_nas_fronteiras(self):
        chave = lambda n: node(f"M.semaforoSaturacao({n}).chave")
        self.assertEqual([chave(n) for n in (0, 4, 5, 20, 21, 30, 31, 80)],
                         ["aberto", "aberto", "saturando", "saturando", "sem_regra", "sem_regra", "abandone", "abandone"])

    def test_entradas_invalidas_nao_classificam(self):
        for n in ("null", "-1", "'abc'"):
            self.assertIsNone(node(f"M.semaforoSaturacao({n})"), n)

    def test_texto_de_campo_aberto_lembra_da_condicao_de_ter_views(self):
        self.assertIn("bastante visualização", node("M.semaforoSaturacao(2).texto"))
        self.assertIn("iniciante", node("M.semaforoSaturacao(10).texto"))


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class MetricasCanalTests(unittest.TestCase):
    def test_usa_so_os_10_mais_recentes_mesmo_com_a_amostra_fora_de_ordem(self):
        m = metricas(canal(500))
        self.assertEqual((m["n_amostra"], m["n_ultimos"], m["amostra_pequena"]), (12, 10, False))
        self.assertEqual((m["mediana"], m["media"], m["media_sobre_mediana"]), (1000, 1800, 1.8))
        self.assertEqual(m["maior_fator"], 9)

    def test_o_viral_antigo_nao_entra_na_mediana_dos_ultimos_10(self):
        # se os 12 entrassem a mediana seria 1.050; com 500 mil e 400 mil dentro, a média passaria de 76 mil
        m = metricas(canal(500), "{n: 12}")
        self.assertEqual(m["mediana"], 1050)
        self.assertGreater(m["media"], 76000)

    def test_tracao_e_sinal_por_tamanho_do_canal(self):
        self.assertEqual((metricas(canal(500))["tracao"], metricas(canal(500))["sinal"]["chave"]), (2, "intermediario"))
        self.assertEqual((metricas(canal(250))["tracao"], metricas(canal(250))["sinal"]["chave"]), (4, "forte"))
        self.assertEqual(metricas(canal(100000))["sinal"]["chave"], "cuidado")            # 0,01
        self.assertEqual(metricas(canal(250), "{limites: {forte: 5}}")["sinal"]["chave"], "intermediario")

    def test_sem_inscritos_ou_sem_amostra_nao_inventa_numero(self):
        for c in (canal(None), canal(0)):
            m = metricas(c)
            self.assertEqual((m["tracao"], m["sinal"]["chave"]), (None, "sem_dado"))
        vazio = metricas(canal(500, amostra=[]))
        self.assertEqual((vazio["mediana"], vazio["media"], vazio["tracao"], vazio["maior_fator"], vazio["outliers"], vazio["amostra_pequena"]),
                         (None, None, None, None, [], True))

    def test_amostra_pequena_avisa_e_usa_o_que_tem(self):
        m = metricas(canal(500, amostra=AMOSTRA[1:7]))
        self.assertEqual((m["n_ultimos"], m["amostra_pequena"]), (6, True))
        self.assertIsNotNone(m["mediana"])

    def test_video_sem_views_e_ignorado(self):
        m = metricas(canal(500, amostra=[v("2026-09-18", None), v("2026-09-10", 1000), v("2026-09-03", 3000)]))
        self.assertEqual((m["n_ultimos"], m["mediana"]), (2, 2000))

    def test_outliers_recentes_ordenados_por_fator(self):
        m = metricas(canal(500))       # fatorMin 2 e só últimos 30 dias: só o vídeo de 9.000 views (3 dias atrás)
        self.assertEqual([(o["views"], o["fator"], o["dias"]) for o in m["outliers"]], [(9000, 9, 3)])
        self.assertEqual(round(m["outliers"][0]["vph_medio"], 1), 125.0)                  # 9000 / (3 x 24)

    def test_outliers_sem_filtro_de_30_dias_trazem_os_virais_antigos_primeiro(self):
        m = metricas(canal(500), "{so30d: false}")
        self.assertEqual([o["fator"] for o in m["outliers"]], [500, 400, 9])

    def test_fator_minimo_ajustavel(self):
        m = metricas(canal(500), "{fatorMin: 1.2}")
        self.assertEqual([o["views"] for o in m["outliers"]], [9000, 1200])               # 1.200 / 1.000 = 1,2 entra

    def test_dados_do_canal_passam_para_a_tabela(self):
        m = metricas(canal(500))
        self.assertEqual((m["inscritos"], m["n_videos"], m["videos_30d"], m["criado_em"]), (500, 12, 3, "2026-04-14"))
        self.assertEqual(round(m["idade_meses"], 1), 5.3)


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class UltimosNTests(unittest.TestCase):
    def test_ordena_por_data_quando_todos_tem_data(self):
        r = node("M.ultimosN([{views_num: 1, data: '2026-01-01'}, {views_num: 2, data: '2026-03-01'}], 10).map(x => x.views_num)")
        self.assertEqual(r, [2, 1])

    def test_mantem_a_ordem_da_coleta_se_algum_video_nao_tem_data(self):
        r = node("M.ultimosN([{views_num: 1, data: '2026-01-01'}, {views_num: 2, data: ''}, {views_num: 3, data: '2026-03-01'}], 10).map(x => x.views_num)")
        self.assertEqual(r, [1, 2, 3])

    def test_limite_n_e_empate_estavel(self):
        r = node("M.ultimosN([{views_num: 1, data: '2026-03-01'}, {views_num: 2, data: '2026-03-01'}, {views_num: 3, data: '2026-01-01'}], 2).map(x => x.views_num)")
        self.assertEqual(r, [1, 2])


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class EntradaESaidaTests(unittest.TestCase):
    def test_contagens_digitadas_como_no_youtube_e_no_vidiq(self):
        casos = {"12 mil": 12000, "1,5 mi": 1500000, "8.443": 8443, "1.234.567": 1234567, "300": 300, "2k": 2000, "1,234": 1234,
                 "4,5 mil": 4500, "1.5m": 1500000}
        for texto, esperado in casos.items():
            self.assertEqual(node(f"M.parseContagem({json.dumps(texto)})"), esperado, texto)
        for lixo in ("abc", "", "12 milhões?", "-5"):
            self.assertIsNone(node(f"M.parseContagem({json.dumps(lixo)})"), lixo)

    def test_lista_uma_por_linha_ou_ponto_e_virgula_separa_os_invalidos(self):
        r = node("M.parseLista('1.000\\n2 mil; x\\n\\n3,5 mil')")
        self.assertEqual(r, {"valores": [1000, 2000, 3500], "invalidos": ["x"]})

    def test_csv_escapa_virgula_aspas_quebra_de_linha_e_traz_bom(self):
        cols = [{"chave": "a", "rotulo": "Canal"}, {"chave": "b", "rotulo": "Nota, 1"}]
        linhas = [{"a": 'Ele disse "oi"', "b": 1.5}, {"a": "duas\nlinhas", "b": None}, {"a": "x;y", "b": 0}]
        csv = node(f"M.toCsv({json.dumps(cols)}, {json.dumps(linhas)})")
        self.assertTrue(csv.startswith("\ufeffCanal,\"Nota, 1\"\r\n"))
        self.assertIn('"Ele disse ""oi""",1.5', csv)
        self.assertIn('"duas\nlinhas",', csv)
        self.assertIn('"x;y",0', csv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
