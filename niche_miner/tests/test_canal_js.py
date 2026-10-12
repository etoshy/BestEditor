"""Explorador de vídeos (static/canal.js), executado no Node real."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULO = json.dumps(str(ROOT / "static" / "canal.js"))


def node(expressao):
    js = f"const C = require({MODULO}); process.stdout.write(JSON.stringify({expressao}));"
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def v(indice, titulo, views, idade, views_dia=None, data=None, duracao_seg=None, duracao=""):
    return {"indice": indice, "titulo": titulo, "url": f"https://youtu.be/{indice}", "views": views, "idade_dias": idade,
            "views_dia": views_dia, "data": data if data is not None else "", "duracao_seg": duracao_seg, "duracao": duracao}


VIDEOS = [
    v(1, "Como ter um dia produtivo", 900, 3, 300.0, "2026-09-18", 540, "9:00"),
    v(2, "12 lições estoicas", 9000, 30, 300.0, "2026-08-22", 600, "10:00"),
    v(3, "Sêneca sobre o tempo", 1000, 80, 12.5, "2026-07-03", 420, "7:00"),
    v(4, "Meditações resumo", 900, 130, 6.9, "2026-05-14", 1200, "20:00"),
    v(5, "Sem dados", None, None, None, "", None, ""),
]


def ids(expr):
    return [x["indice"] for x in node(expr)]


class FatorTests(unittest.TestCase):
    def test_fator_e_views_sobre_a_mediana(self):
        self.assertEqual(node("C.fatorOutlier(9000, 1000)"), 9)
        self.assertIsNone(node("C.fatorOutlier(9000, 0)"))
        self.assertIsNone(node("C.fatorOutlier(null, 1000)"))
        self.assertIsNone(node("C.fatorOutlier(9000, null)"))

    def test_preparar_acrescenta_o_fator_sem_mutar_o_original(self):
        r = node(f"(() => {{ const orig = {json.dumps(VIDEOS)}; const p = C.prepararVideos(orig, 1000); return [p.map(x => x.fator), 'fator' in orig[0]]; }})()")
        self.assertEqual(r, [[0.9, 9, 1, 0.9, None], False])
        self.assertEqual(node("C.prepararVideos(null, 1000)"), [])


class FiltrarTests(unittest.TestCase):
    base = f"C.prepararVideos({json.dumps(VIDEOS)}, 1000)"

    def filtrar(self, f):
        return ids(f"C.filtrar({self.base}, {json.dumps(f)})")

    def test_sem_filtro_devolve_tudo(self):
        self.assertEqual(self.filtrar({}), [1, 2, 3, 4, 5])
        self.assertEqual(ids(f"C.filtrar({self.base}, null)"), [1, 2, 3, 4, 5])
        self.assertEqual(self.filtrar({"texto": "  ", "dias": None, "viewsMin": "", "fatorMin": None}), [1, 2, 3, 4, 5])

    def test_texto_ignora_acento_e_caixa(self):
        self.assertEqual(self.filtrar({"texto": "seneca"}), [3])
        self.assertEqual(self.filtrar({"texto": "SÊNECA"}), [3])
        self.assertEqual(self.filtrar({"texto": "licoes"}), [2])
        self.assertEqual(self.filtrar({"texto": "nada"}), [])

    def test_periodo_e_a_idade_maxima_e_video_sem_data_nao_passa(self):
        self.assertEqual(self.filtrar({"dias": 30}), [1, 2])              # 3 e 30 dias (30 entra)
        self.assertEqual(self.filtrar({"dias": 90}), [1, 2, 3])
        self.assertEqual(self.filtrar({"dias": 0}), [])

    def test_faixa_de_views_inclusiva_e_video_sem_views_nao_passa(self):
        self.assertEqual(self.filtrar({"viewsMin": 1000}), [2, 3])
        self.assertEqual(self.filtrar({"viewsMax": 1000}), [1, 3, 4])
        self.assertEqual(self.filtrar({"viewsMin": 900, "viewsMax": 1000}), [1, 3, 4])

    def test_fator_minimo_a_pontuacao(self):
        self.assertEqual(self.filtrar({"fatorMin": 2}), [2])
        self.assertEqual(self.filtrar({"fatorMin": 1}), [2, 3])
        self.assertEqual(self.filtrar({"fatorMin": 0.5}), [1, 2, 3, 4])

    def test_categoria_por_indices_e_combinacao_de_filtros(self):
        self.assertEqual(self.filtrar({"indices": [2, 3, 4]}), [2, 3, 4])
        self.assertEqual(self.filtrar({"indices": []}), [])
        self.assertEqual(self.filtrar({"indices": [1, 2, 3], "dias": 90, "viewsMin": 1000}), [2, 3])


class OrdenarTests(unittest.TestCase):
    base = f"C.prepararVideos({json.dumps(VIDEOS)}, 1000)"

    def ordem(self, chave, crescente="false"):
        return ids(f"C.ordenar({self.base}, {json.dumps(chave)}, {crescente})")

    def test_views_maior_primeiro_empate_mantem_a_ordem_e_sem_valor_no_fim(self):
        self.assertEqual(self.ordem("views"), [2, 3, 1, 4, 5])       # 1 e 4 empatam em 900: o 1 veio antes
        self.assertEqual(self.ordem("views", "true"), [1, 4, 3, 2, 5])   # sem dado fica no fim também no crescente

    def test_views_por_dia_fator_data_e_duracao(self):
        self.assertEqual(self.ordem("views_dia"), [1, 2, 3, 4, 5])      # 300 e 300 empatam
        self.assertEqual(self.ordem("fator"), [2, 3, 1, 4, 5])
        self.assertEqual(self.ordem("data"), [1, 2, 3, 4, 5])           # mais recente primeiro
        self.assertEqual(self.ordem("data", "true"), [4, 3, 2, 1, 5])
        self.assertEqual(self.ordem("duracao"), [4, 2, 1, 3, 5])

    def test_original_e_chave_desconhecida_nao_reordenam_e_nao_mutam(self):
        self.assertEqual(self.ordem("original"), [1, 2, 3, 4, 5])
        self.assertEqual(self.ordem("xyz"), [1, 2, 3, 4, 5])
        self.assertEqual(node(f"(() => {{ const a = {json.dumps(VIDEOS)}; C.ordenar(a, 'views'); return a.map(x => x.indice); }})()"), [1, 2, 3, 4, 5])


class ExportacaoTests(unittest.TestCase):
    def test_duracao_em_texto(self):
        casos = {540: "9:00", 65: "1:05", 3725: "1:02:05", 0: "0:00"}
        for seg, esperado in casos.items():
            self.assertEqual(node(f"C.duracaoTexto({seg})"), esperado, seg)
        self.assertEqual(node("C.duracaoTexto(null)"), "—")

    def test_linhas_de_exportacao_arredondam_e_trazem_a_categoria(self):
        linhas = node(f"C.linhasExport(C.prepararVideos({json.dumps(VIDEOS)}, 1000), {{2: 'Listas'}})")
        self.assertEqual(linhas[1], {"titulo": "12 lições estoicas", "url": "https://youtu.be/2", "views": 9000, "views_dia": 300.0, "fator": 9,
                                     "data": "2026-08-22", "idade_dias": 30, "duracao": "10:00", "categoria": "Listas"})
        self.assertEqual(linhas[0]["categoria"], "")
        self.assertEqual((linhas[4]["views"], linhas[4]["fator"], linhas[4]["idade_dias"], linhas[4]["duracao"]), (None, None, None, ""))

    def test_colunas_de_exportacao_cobrem_as_chaves_das_linhas(self):
        colunas = node("C.COLUNAS_EXPORT.map(c => c.chave)")
        linha = node(f"Object.keys(C.linhasExport([{json.dumps(VIDEOS[0])}])[0])")
        self.assertEqual(colunas, linha)


if __name__ == "__main__":
    unittest.main(verbosity=2)
