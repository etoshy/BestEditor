"""Lógica pura de ordenação de canais (static/ordenacao.js), executada no Node real."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULO = json.dumps(str(ROOT / "static" / "ordenacao.js"))

# Ordem original: A, B, C, D, E.  D não tem nenhum dado (canal cuja aba Sobre falhou).
CANAIS = [
    {"id": "A", "inscritos_num": 1000, "n_videos": 10, "views_totais": 50000, "score": 10},
    {"id": "B", "inscritos_num": 5000, "n_videos": 200, "views_totais": 900000, "score": 30},
    {"id": "C", "inscritos_num": 300, "n_videos": 3, "views_totais": 90000, "score": 20},
    {"id": "D", "inscritos_num": None, "n_videos": None, "views_totais": None, "score": None},
    {"id": "E", "inscritos_num": 5000, "n_videos": 20, "views_totais": 100000, "score": 20},
]


def node(expressao):
    js = f"const O = require({MODULO}); process.stdout.write(JSON.stringify({expressao}));"
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True)   # stdin: sem limite de tamanho de argumento
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


def ordem(campo, dir=None, canais=CANAIS):
    ids = node(f"O.ordenar({json.dumps(canais)}, {json.dumps(campo)}, {json.dumps(dir)}).map(c => c.id)")
    return "".join(ids)


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class OrdenarTests(unittest.TestCase):
    def test_inscritos_empate_mantem_ordem_original_e_vazio_vai_para_o_fim(self):
        self.assertEqual(ordem("inscritos", "desc"), "BEACD")   # B e E empatam: B veio antes
        self.assertEqual(ordem("inscritos", "asc"), "CABED")  # dado ausente fica no fim também no crescente

    def test_videos_por_padrao_menos_primeiro(self):
        self.assertEqual(ordem("videos"), "CAEBD")
        self.assertEqual(ordem("videos", "desc"), "BEACD")

    def test_views_totais(self):
        self.assertEqual(ordem("views", "desc"), "BECAD")
        self.assertEqual(ordem("views", "asc"), "ACEBD")

    def test_views_por_video(self):
        # A=5000, B=4500, C=30000, E=5000; D sem dado
        self.assertEqual(ordem("views_por_video"), "CAEBD")

    def test_inscritos_por_video(self):
        # A=100, B=25, C=100, E=250
        self.assertEqual(ordem("inscritos_por_video"), "EACBD")

    def test_razao_sem_videos_ou_sem_dado_e_ausente_nao_infinito(self):
        canais = [{"id": "Z", "inscritos_num": 900, "n_videos": 0, "views_totais": 900},
                  {"id": "Y", "inscritos_num": 100, "n_videos": None, "views_totais": 100},
                  {"id": "X", "inscritos_num": 10, "n_videos": 5, "views_totais": 10}]
        self.assertEqual(ordem("views_por_video", "desc", canais), "XZY")
        self.assertEqual(ordem("views_por_video", "asc", canais), "XZY")
        self.assertIsNone(node("O.razao(5, 0)"))
        self.assertIsNone(node("O.razao(null, 3)"))
        self.assertEqual(node("O.razao('10', '4')"), 2.5)

    def test_score(self):
        self.assertEqual(ordem("score"), "BCEAD")

    def test_padrao_nao_reordena_e_devolve_copia(self):
        self.assertEqual(ordem("padrao"), "ABCDE")
        self.assertEqual(ordem("padrao", "asc"), "ABCDE")
        r = node(f"(() => {{ const l = {json.dumps(CANAIS)}; const s = O.ordenar(l, 'inscritos', 'desc'); return [l.map(c => c.id).join(''), s === l]; }})()")
        self.assertEqual(r, ["ABCDE", False])   # a lista original não é alterada

    def test_numeros_em_texto_e_valores_invalidos(self):
        canais = [{"id": "a", "inscritos_num": "1000"}, {"id": "b", "inscritos_num": "abc"},
                  {"id": "c", "inscritos_num": ""}, {"id": "d", "inscritos_num": 5000}]
        self.assertEqual(ordem("inscritos", "desc", canais), "dabc")   # 5000 > "1000"; texto inválido e vazio vão para o fim

    def test_lista_vazia_ou_invalida(self):
        self.assertEqual(node("O.ordenar([], 'inscritos', 'desc')"), [])
        self.assertEqual(node("O.ordenar(null, 'inscritos', 'desc')"), [])
        self.assertEqual(node("O.ordenar(undefined, 'combinada')"), [])


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class CombinadaTests(unittest.TestCase):
    """Menos vídeos + mais views + mais inscritos, como média de posições (1 = melhor)."""

    def test_posicoes_calculadas_a_mao(self):
        # inscritos: B=1 E=1 A=3 C=4 D=5 | views: B=1 E=2 C=3 A=4 D=5 | vídeos (menos): C=1 A=2 E=3 B=4 D=5
        r = node(f"(() => {{ const l = {json.dumps(CANAIS)}; const p = O.posicaoCombinada(l); return l.map(c => [c.id, p.get(c)]); }})()")
        got = {i: round(v, 3) for i, v in r}
        self.assertEqual(got, {"A": 3.0, "B": 2.0, "C": 2.667, "D": 5.0, "E": 2.0})

    def test_ordem_combinada_e_dado_ausente_conta_como_pior(self):
        self.assertEqual(ordem("combinada"), "BECAD")          # B e E empatam (2,0): B veio antes
        # decrescente = pior primeiro: D (sem dados = pior posição), A, C e o empate B/E na ordem original
        self.assertEqual(ordem("combinada", "desc"), "DACBE")

    def test_canal_com_dado_ausente_nunca_ganha_de_canal_completo_igual(self):
        canais = [{"id": "sem", "inscritos_num": None, "n_videos": 5, "views_totais": 1000},
                  {"id": "com", "inscritos_num": 10, "n_videos": 5, "views_totais": 1000}]
        self.assertEqual(ordem("combinada", "asc", canais), "comsem")

    def test_um_unico_canal_e_lista_vazia(self):
        self.assertEqual(node("O.posicaoCombinada([{inscritos_num: 1, n_videos: 1, views_totais: 1}]).size"), 1)
        self.assertEqual(node("O.posicaoCombinada([]).size"), 0)

    def test_desempenho_com_muitos_canais(self):
        import time
        canais = [{"id": i, "inscritos_num": (i * 7919) % 10007, "n_videos": (i * 31) % 500, "views_totais": (i * 104729) % 1000003} for i in range(2000)]
        ini = time.time()
        r = node(f"O.ordenar({json.dumps(canais)}, 'combinada', 'asc').length")
        self.assertEqual(r, 2000)
        self.assertLess(time.time() - ini, 5)


@unittest.skipUnless(shutil.which("node"), "node não instalado")
class NormalizarTests(unittest.TestCase):
    def test_campo_invalido_cai_no_padrao_e_direcao_no_default_da_metrica(self):
        self.assertEqual(node("O.normalizar('xyz', 'asc')"), {"campo": "padrao", "dir": "asc"})
        self.assertEqual(node("O.normalizar('videos')"), {"campo": "videos", "dir": "asc"})
        self.assertEqual(node("O.normalizar('inscritos', 'lixo')"), {"campo": "inscritos", "dir": "desc"})
        self.assertEqual(node("O.normalizar('combinada')"), {"campo": "combinada", "dir": "asc"})

    def test_toda_metrica_da_ordem_existe_e_tem_rotulo_e_ajuda(self):
        r = node("O.ORDEM.map(k => [k, !!O.METRICAS[k], !!O.METRICAS[k].rotulo, !!O.METRICAS[k].ajuda])")
        self.assertEqual(len(r), 8)
        self.assertTrue(all(all(x[1:]) for x in r))


class IntegracaoHtmlTests(unittest.TestCase):
    def test_ordenacao_js_carrega_antes_do_app_js(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("filename='ordenacao.js'", html)
        self.assertLess(html.index("filename='ordenacao.js'"), html.index("filename='app.js'"))

    def test_scripts_de_teste_checam_a_sintaxe_do_modulo(self):
        for nome in ("run_tests.bat", "run_tests.ps1"):
            self.assertIn("ordenacao.js", (ROOT / nome).read_text(encoding="utf-8"), nome)


if __name__ == "__main__":
    unittest.main(verbosity=2)
