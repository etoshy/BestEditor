"""Lógica do navegador da aba API do YouTube (static/ytapi.js), executada no Node real."""
import json
import re
import shutil
import subprocess
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULO = json.dumps(str(ROOT / "static" / "ytapi.js"))


def node(expressao):
    js = f"const Y = require({MODULO}); process.stdout.write(JSON.stringify({expressao}));"
    r = subprocess.run(["node", "-"], input=js, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


CANAIS = {"c1": {"inscritos": 1000, "views_totais": 50000}, "c2": {"inscritos": 100000, "views_totais": 9000000},
          "c3": {"inscritos": None, "views_totais": 200000}}


def v(i, canal, views, dur, eng=None, pub=None, titulo=None):
    return {"id": i, "titulo": titulo or f"Vídeo {i}", "canal_id": canal, "views": views, "duracao_seg": dur, "engajamento": eng, "publicado": pub or f"2026-09-{i:02d}T10:00:00Z",
            "likes": views // 10, "comentarios": views // 100, "views_dia": views / 5, "url": f"https://youtu.be/{i}", "canal": "Canal", "data": f"2026-09-{i:02d}", "idade_dias": 30 - i}


VIDEOS = [v(1, "c1", 5000, 45, 8.0), v(2, "c1", 200000, 600, 5.0), v(3, "c2", 1000000, 2100, 3.0), v(4, "c2", 99999, 58, 4.0),
          v(5, "c3", 150000, 0, 6.0), v(6, "c3", 300000, None), v(7, "cx", 120000, 500)]
DADOS = f"{json.dumps(VIDEOS)}, {json.dumps(CANAIS)}"


def ids(expr):
    return [x["id"] for x in node(expr)]


class ShortETest(unittest.TestCase):
    def test_short_por_duracao_com_limite_ajustavel(self):
        casos = [(45, 60, True), (60, 60, True), (61, 60, False), (150, 180, True), (181, 180, False), (0, 60, False), (None, 60, False)]
        for dur, limite, esperado in casos:
            self.assertEqual(node(f"Y.ehShort({{duracao_seg: {json.dumps(dur)}}}, {limite})"), esperado, (dur, limite))
        self.assertTrue(node("Y.ehShort({duracao_seg: 60})"))                                    # sem limite informado: 60

    def test_formato_nao_classifica_o_que_nao_tem_duracao_nem_o_ao_vivo(self):
        for formato in ("shorts", "longos"):
            self.assertFalse(node(f"Y.formatoOk({{duracao_seg: null}}, '{formato}', 60)"))
            self.assertFalse(node(f"Y.formatoOk({{duracao_seg: 0}}, '{formato}', 60)"))
        self.assertTrue(node("Y.formatoOk({duracao_seg: null}, 'todos', 60)"))
        self.assertTrue(node("Y.formatoOk({duracao_seg: 45}, 'shorts', 60)"))
        self.assertFalse(node("Y.formatoOk({duracao_seg: 45}, 'longos', 60)"))
        self.assertTrue(node("Y.formatoOk({duracao_seg: 600}, 'longos', 60)"))
        self.assertFalse(node("Y.formatoOk({duracao_seg: 100}, 'longos', 180)"))               # com o limite de 3 min, 100 s é Short


class FiltrarTests(unittest.TestCase):
    def filtrar(self, f, short=60):
        return ids(f"Y.filtrar({DADOS}, {json.dumps(f)}, {short})")

    def test_sem_filtro_devolve_tudo_e_ignora_campos_vazios(self):
        self.assertEqual(self.filtrar({}), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(self.filtrar({"texto": "  ", "viewsMin": "", "subsMin": None, "formato": "todos"}), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(ids(f"Y.filtrar({json.dumps(VIDEOS)}, null, null)"), [1, 2, 3, 4, 5, 6, 7])

    def test_views_minimas_inclusivas(self):
        self.assertEqual(self.filtrar({"viewsMin": 100000}), [2, 3, 5, 6, 7])
        self.assertEqual(self.filtrar({"viewsMin": 100000.5}), [2, 3, 5, 6, 7])
        self.assertEqual(self.filtrar({"viewsMin": 99999}), [2, 3, 4, 5, 6, 7])

    def test_faixa_de_inscritos_do_canal_e_canal_sem_dado_nao_passa(self):
        self.assertEqual(self.filtrar({"subsMin": 1000, "subsMax": 50000}), [1, 2])
        self.assertEqual(self.filtrar({"subsMin": 0}), [1, 2, 3, 4])                             # inscritos ocultos (c3) e canal desconhecido (cx) ficam de fora
        self.assertEqual(self.filtrar({"subsMax": 1000}), [1, 2])
        self.assertEqual(self.filtrar({"subsMin": 100000}), [3, 4])

    def test_faixa_de_views_do_canal(self):
        self.assertEqual(self.filtrar({"canalViewsMin": 100000}), [3, 4, 5, 6])
        self.assertEqual(self.filtrar({"canalViewsMax": 100000}), [1, 2])
        self.assertEqual(self.filtrar({"canalViewsMin": 100000, "canalViewsMax": 1000000}), [5, 6])

    def test_duracao_exata_em_segundos(self):
        self.assertEqual(self.filtrar({"duracaoMinSeg": 300, "duracaoMaxSeg": 1000}), [2, 7])
        self.assertEqual(self.filtrar({"duracaoMinSeg": 0}), [1, 2, 3, 4, 5, 7])                 # sem duração (6) não passa quando há filtro
        self.assertEqual(self.filtrar({"duracaoMaxSeg": 60}), [1, 4, 5])

    def test_formato_texto_e_combinacoes(self):
        self.assertEqual(self.filtrar({"formato": "shorts"}), [1, 4])
        self.assertEqual(self.filtrar({"formato": "longos"}), [2, 3, 7])
        self.assertEqual(self.filtrar({"formato": "shorts"}, short=180), [1, 4])
        self.assertEqual(self.filtrar({"texto": "VÍDEO 3"}), [3])
        self.assertEqual(self.filtrar({"texto": "video 3"}), [3])
        self.assertEqual(self.filtrar({"formato": "longos", "viewsMin": 200000, "subsMin": 1000}), [2, 3])


class EmAltaTests(unittest.TestCase):
    def filtrar(self, **o):
        return ids(f"Y.filtrarEmAlta({json.dumps(VIDEOS)}, {json.dumps(o)}, 60)")

    def test_por_padrao_so_100_mil_views_ou_mais(self):
        self.assertEqual(self.filtrar(), [2, 3, 5, 6, 7])
        self.assertEqual(self.filtrar(duracao="todos"), [2, 3, 5, 6, 7])

    def test_filtros_de_duracao_do_em_alta(self):
        self.assertEqual(self.filtrar(viewsMin=None, duracao="shorts"), [1, 4])
        self.assertEqual(self.filtrar(viewsMin=None, duracao="menos5"), [1, 4])
        self.assertEqual(self.filtrar(duracao="mais8"), [2, 3, 7])                                # 500 s > 480 s
        self.assertEqual(self.filtrar(duracao="mais30"), [3])
        self.assertEqual(self.filtrar(duracao="shorts"), [])                                      # nenhum Short passa dos 100 mil neste conjunto
        self.assertEqual(self.filtrar(viewsMin=1000000, duracao="mais8"), [3])

    def test_video_sem_duracao_ou_ao_vivo_nao_entra_nos_filtros_de_duracao(self):
        self.assertNotIn(6, self.filtrar(duracao="mais8"))
        self.assertNotIn(5, self.filtrar(viewsMin=None, duracao="menos5"))


class OrdenarTests(unittest.TestCase):
    def ordem(self, chave, dir="desc"):
        return ids(f"Y.ordenar({json.dumps(VIDEOS)}, {json.dumps(chave)}, {json.dumps(dir)}, {json.dumps(CANAIS)})")

    def test_engajamento_com_ausentes_sempre_no_fim(self):
        self.assertEqual(self.ordem("engajamento"), [1, 5, 2, 4, 3, 6, 7])
        self.assertEqual(self.ordem("engajamento", "asc"), [3, 4, 2, 5, 1, 6, 7])

    def test_views_data_e_duracao(self):
        self.assertEqual(self.ordem("views"), [3, 6, 2, 5, 7, 4, 1])
        self.assertEqual(self.ordem("views", "asc"), [1, 4, 7, 5, 2, 6, 3])
        self.assertEqual(self.ordem("data"), [7, 6, 5, 4, 3, 2, 1])
        self.assertEqual(self.ordem("data", "asc"), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(self.ordem("duracao"), [3, 2, 7, 4, 1, 5, 6])                           # 0 (ao vivo) conta como valor; None vai para o fim

    def test_inscritos_do_canal_e_chave_desconhecida(self):
        self.assertEqual(self.ordem("inscritos"), [3, 4, 1, 2, 5, 6, 7])
        self.assertEqual(self.ordem("inscritos", "asc"), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(self.ordem("xyz"), [1, 2, 3, 4, 5, 6, 7])

    def test_nao_muta_a_lista_original(self):
        self.assertEqual(node(f"(() => {{ const a = {json.dumps(VIDEOS)}; Y.ordenar(a, 'views', 'desc', {{}}); return a.map(x => x.id); }})()"), [1, 2, 3, 4, 5, 6, 7])


class CustoECotaTests(unittest.TestCase):
    def test_custo_de_resolver_o_canal(self):
        casos = {"UC" + "a" * 22: 0, "https://www.youtube.com/channel/UC" + "a" * 22: 0, "@alfa": 1, "https://www.youtube.com/@alfa": 1, "https://www.youtube.com/c/NomeCustom": 101,
                 "https://www.youtube.com/user/antigo": 1, "": 0}
        for entrada, custo in casos.items():
            self.assertEqual(node(f"Y.custoResolver({json.dumps(entrada)})"), custo, entrada)

    def test_custo_de_cada_ferramenta_bate_com_o_do_servidor(self):
        self.assertEqual((node("Y.custoPesquisa('estoicismo')"), node("Y.custoPesquisa('')"), node("Y.custoPesquisa('   ')")), (102, 2, 2))
        self.assertEqual((node("Y.custoComparar('@a', '@b')"), node("Y.custoComparar('UC' + 'a'.repeat(22), '@b')")), (7, 6))
        self.assertEqual((node("Y.custoCanal('@x')"), node("Y.custoCanal('UC' + 'a'.repeat(22))")), (2, 1))
        self.assertEqual((node("Y.custoHistorico('@x')"), node("Y.custoHistorico('UC' + 'a'.repeat(22))")), (4, 3))
        self.assertEqual((node("Y.CUSTO_EM_ALTA"), node("Y.CUSTO_VIDEO")), (2, 2))

    def test_cota_zera_a_meia_noite_do_pacifico(self):
        self.assertEqual(node("Y.diaPacifico(new Date(Date.UTC(2026, 8, 21, 5, 0)))"), "2026-09-20")      # 22h de domingo em Los Angeles
        self.assertEqual(node("Y.diaPacifico(new Date(Date.UTC(2026, 8, 21, 8, 0)))"), "2026-09-21")      # 1h de segunda
        self.assertEqual(node("Y.somarCota(null, '2026-09-21', 102)"), {"dia": "2026-09-21", "usadas": 102})
        self.assertEqual(node("Y.somarCota({dia: '2026-09-21', usadas: 102}, '2026-09-21', 2)"), {"dia": "2026-09-21", "usadas": 104})
        self.assertEqual(node("Y.somarCota({dia: '2026-09-20', usadas: 9000}, '2026-09-21', 2)"), {"dia": "2026-09-21", "usadas": 2})
        self.assertEqual(node("Y.somarCota({dia: 'd', usadas: 5}, 'd', -50)"), {"dia": "d", "usadas": 5})
        self.assertEqual(node("Y.somarCota({dia: 'd', usadas: 5}, 'd', 'abc')"), {"dia": "d", "usadas": 5})

    def test_atalhos_de_data(self):
        casos = {7: "2026-09-14", 15: "2026-09-06", 30: "2026-08-22", 90: "2026-06-23", 180: "2026-03-25", 365: "2025-09-21"}
        for dias, esperado in casos.items():
            self.assertEqual(node(f"Y.dataAtalho({dias}, new Date(2026, 8, 21))"), esperado, dias)
        self.assertEqual([a["rotulo"] for a in node("Y.ATALHOS_DATA")], ["7 dias", "15 dias", "1 mês", "3 meses", "6 meses", "1 ano"])


class ListasEExportacaoTests(unittest.TestCase):
    def test_paises_unicos_ordenados_e_atalhos_existem(self):
        paises = node("Y.PAISES")
        codigos = [c for c, _ in paises]
        self.assertEqual(len(codigos), len(set(codigos)))
        self.assertTrue(all(re.fullmatch(r"[A-Z]{2}", c) for c in codigos))
        self.assertGreater(len(paises), 80)
        self.assertIn(["BR", "Brasil"], paises)
        self.assertIn(["US", "Estados Unidos"], paises)
        nomes = [n for _, n in paises]
        sem_acento = lambda t: "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)).lower()
        self.assertEqual(nomes, sorted(nomes, key=sem_acento))                                    # ordem alfabética em português, ignorando acento
        self.assertEqual(nomes[0], "África do Sul")
        self.assertEqual({a["codigo"] for a in node("Y.ATALHOS_PAIS")}, {"BR", "US", "ES"})
        self.assertTrue({a["codigo"] for a in node("Y.ATALHOS_PAIS")} <= set(codigos))

    def test_categorias_e_idiomas(self):
        cats = node("Y.CATEGORIAS")
        self.assertEqual(cats[0], ["", "Todas"])
        self.assertTrue(all(re.fullmatch(r"\d{1,2}", c) for c, _ in cats[1:]))
        self.assertTrue(all(re.fullmatch(r"[a-z]{2}", c) for c, _ in node("Y.IDIOMAS")))

    def test_duracao_em_texto(self):
        for seg, esperado in {600: "10:00", 45: "0:45", 3730: "1:02:10", 0: "0:00"}.items():
            self.assertEqual(node(f"Y.duracaoTexto({seg})"), esperado, seg)
        self.assertEqual(node("Y.duracaoTexto(null)"), "—")

    def test_linhas_do_csv(self):
        linhas = node(f"Y.linhasCsv({json.dumps(VIDEOS)}, {json.dumps(CANAIS)}, 60)")
        um, dois, cinco, seis = linhas[0], linhas[1], linhas[4], linhas[5]
        self.assertEqual((um["formato"], um["duracao"], um["inscritos"], um["views_canal"], um["engajamento"]), ("Short", "0:45", 1000, 50000, 8.0))
        self.assertEqual((dois["formato"], dois["duracao"]), ("Longo", "10:00"))
        self.assertEqual((cinco["formato"], cinco["duracao"], cinco["inscritos"]), ("", "0:00", None))     # ao vivo: nem Short nem Longo; inscritos ocultos
        self.assertEqual((seis["formato"], seis["duracao"], seis["engajamento"]), ("", "", None))
        self.assertEqual(linhas[6]["inscritos"], None)                                                     # canal desconhecido
        self.assertEqual(node("Y.COLUNAS_CSV.map(c => c.chave)"), node(f"Object.keys(Y.linhasCsv([{json.dumps(VIDEOS[0])}], {{}}, 60)[0])"))

    def test_csv_neutraliza_formulas_em_titulo_e_canal(self):
        for perigoso in ("=HYPERLINK(\"http://x\")", "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"):
            self.assertEqual(node(f"Y.seguroCsv({json.dumps(perigoso)})"), "'" + perigoso, repr(perigoso))
        for normal in ("Como ter foco", "12 lições", "", "Edição especial - parte 2"):
            self.assertEqual(node(f"Y.seguroCsv({json.dumps(normal)})"), normal)
        v = {"id": 1, "titulo": "=cmd|' /C calc'!A0", "canal": "@evil", "canal_id": "c1", "views": 10, "duracao_seg": 600, "url": "https://youtu.be/x", "data": "2026-09-01"}
        linha = node(f"Y.linhasCsv([{json.dumps(v)}], {json.dumps(CANAIS)}, 60)")[0]
        self.assertTrue(linha["titulo"].startswith("'="))
        self.assertTrue(linha["canal"].startswith("'@"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
