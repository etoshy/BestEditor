import csv
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import biblioteca as bib


def _video(vid, titulo, views, data, canal="Canal A", canal_url="https://youtube.com/@a", termo="hacker", verificado=False):
    return {
        "video_id": vid, "titulo": titulo, "url": f"https://www.youtube.com/watch?v={vid}",
        "views_num": views, "views_text": f"{views} views", "data_publicacao": data,
        "canal": canal, "canal_url": canal_url, "canal_verificado": verificado,
        "termo_busca": termo, "subnicho": "Segurança", "nicho": "Tecnologia", "duracao": "10:00",
    }


def _pv(vid, titulo, views, data):
    return {"video_id": vid, "titulo": titulo, "url": f"https://www.youtube.com/watch?v={vid}",
            "views_num": views, "views_text": f"{views} views", "quando": "", "duracao": "", "data": data,
            "data_exata": True}


CANAL = {
    "canal": "Canal Ação", "canal_url": "https://youtube.com/@acao", "inscritos_num": 12000, "n_videos": 20,
    "views_totais": 1234567, "data_criacao_canal": "2026-06-01",
    "primeiro_video_data_publicacao": "2026-07-01", "primeiro_video_confiavel": True,
    "primeiros_5_videos": [_pv(f"p{i}", f"Primeiro {i}", 100 * i, f"2026-07-0{i}") for i in range(1, 6)],
    "top_3_populares": [_pv("t1", "Top 1", 9000, "2026-08-01")],
    "ultimos_3_videos": [_pv("u1", "Último 1", 50, "2026-09-15")],
    "ultimo_video_data_publicacao": "2026-09-15",
    "amostra_videos": [_pv(f"a{i}", f"Amostra {i}", i, "2026-09-01") for i in range(50)],
    "frequencia_label": "1 por semana", "frequencia_videos_por_semana": 1.1, "frequencia_atividade": "ativo",
    "fora_da_janela": False, "idade_desconhecida": False, "meses_desde_primeiro_video": 2.6, "score": 321.5,
    "nichos": ["Tecnologia"], "subnichos": ["Segurança"], "termos_busca": ["hacker"],
}


class BibliotecaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "sub", "b.db")  # a pasta é criada sozinha

    def tearDown(self):
        self._tmp.cleanup()

    def _salvar(self, tema="Tecnologia", canais=None, videos=None, termos=("hacker",)):
        return bib.salvar_busca(
            tema, list(termos), [{"nome": "Segurança", "termos": list(termos)}], {"data_periodo": "mes"},
            {"janela_meses": 3}, [CANAL] if canais is None else canais,
            [_video("v1", "Ataque hacker no banco", 5000, "2026-09-10")] if videos is None else videos,
            db_path=self.db)

    def test_roundtrip_preserva_todos_os_detalhes_do_canal(self):
        bid = self._salvar()
        dados = bib.obter_busca(bid, self.db)
        c = dados["canais"][0]
        self.assertEqual(c["views_totais"], 1234567)
        self.assertEqual(len(c["primeiros_5_videos"]), 5)
        self.assertEqual(len(c["amostra_videos"]), 50)
        self.assertEqual(c["frequencia_label"], "1 por semana")
        self.assertEqual(dados["busca"]["tema"], "Tecnologia")
        self.assertEqual(dados["busca"]["config"], {"janela_meses": 3})
        self.assertEqual(dados["videos"][0]["titulo"], "Ataque hacker no banco")

    def test_videos_repetidos_em_varios_termos_viram_um_registro(self):
        videos = [_video("v1", "Ataque", 100, "2026-09-01", termo="hacker"),
                  _video("v1", "Ataque", 900, "2026-09-01", termo="invasão")]
        bid = self._salvar(videos=videos, termos=("hacker", "invasão"))
        vs = bib.obter_busca(bid, self.db)["videos"]
        self.assertEqual(len(vs), 1)
        self.assertEqual(vs[0]["views_num"], 900)
        self.assertEqual(vs[0]["termo_busca"], "hacker | invasão")

    def test_temas_agrupam_ignorando_caixa_e_acento(self):
        self._salvar(tema="Segurança")
        self._salvar(tema="seguranca")
        self._salvar(tema="Culinária")
        temas = bib.listar_biblioteca(self.db)
        self.assertEqual([t["n_buscas"] for t in temas], [1, 2])  # mais recente primeiro
        self.assertEqual(temas[1]["tema"], "seguranca")

    def test_pesquisa_sem_acento_em_titulo_canal_termo_e_tema(self):
        self._salvar(tema="Segurança digital", termos=("invasão",))
        self.assertEqual(len(bib.pesquisar("ATAQUE hacker", self.db)["videos"]), 1)
        self.assertEqual(len(bib.pesquisar("acao", self.db)["canais"]), 1)      # "Canal Ação"
        self.assertEqual(len(bib.pesquisar("invasao", self.db)["buscas"]), 1)   # termo
        self.assertEqual(len(bib.pesquisar("seguranca", self.db)["buscas"]), 1) # tema
        self.assertEqual(bib.pesquisar("ataque culinaria", self.db)["videos"], [])  # todos os termos
        self.assertEqual(bib.pesquisar("   ", self.db)["videos"], [])

    def test_pesquisa_trata_percentual_e_underscore_como_texto(self):
        self._salvar()
        self.assertEqual(bib.pesquisar("%", self.db)["videos"], [])
        self.assertEqual(bib.pesquisar("_", self.db)["canais"], [])

    def test_primeiro_video_nao_confirmado_nao_vira_data(self):
        canal = dict(CANAL, primeiro_video_confiavel=False)
        bid = self._salvar(canais=[canal])
        r = bib.pesquisar("acao", self.db)["canais"][0]
        self.assertEqual(r["data_primeiro_video"], "")
        self.assertEqual(r["data_ultimo_video"], "2026-09-15")
        self.assertEqual(bib.obter_busca(bid, self.db)["canais"][0]["canal"], "Canal Ação")

    def test_excluir_remove_canais_e_videos(self):
        bid = self._salvar()
        self.assertTrue(bib.excluir_busca(bid, self.db))
        self.assertIsNone(bib.obter_busca(bid, self.db))
        self.assertEqual(bib.pesquisar("ataque", self.db)["videos"], [])
        self.assertFalse(bib.excluir_busca(bid, self.db))

    def test_canais_verificados_ficam_separados_dos_canais_analisados(self):
        videos = [_video("v1", "Ataque", 10, "2026-09-01"),
                  _video("v2", "Outro", 20, "2026-09-02", canal="Grande", canal_url="https://youtube.com/@g", verificado=True)]
        bid = self._salvar(videos=videos)
        d = bib.obter_busca(bid, self.db)
        self.assertEqual([v["canal"] for v in d["verificados"]], ["Grande"])
        self.assertEqual(d["busca"]["n_verificados"], 1)

    def test_csv_de_canais_traz_as_colunas_pedidas(self):
        bid = self._salvar()
        txt = bib.exportar_csv(bid, "canais", self.db)
        linhas = list(csv.reader(io.StringIO(txt), delimiter=";"))
        cab, linha = linhas[0], dict(zip(linhas[0], linhas[1]))
        for col in ["Canal", "Link do canal", "Inscritos", "Nº de vídeos", "Views totais (Sobre)",
                    "Data do 1º vídeo", "Data do último vídeo", "Frequência de postagem"]:
            self.assertIn(col, cab)
        self.assertEqual(linha["Views totais (Sobre)"], "1234567")
        self.assertEqual(linha["Data do 1º vídeo"], "2026-07-01")
        self.assertEqual(linha["Fora da janela"], "não")
        self.assertIn("Primeiro 1 (100 views · 2026-07-01)", linha["5 primeiros vídeos"])

    def test_csv_de_videos_e_busca_inexistente(self):
        bid = self._salvar()
        linhas = list(csv.reader(io.StringIO(bib.exportar_csv(bid, "videos", self.db)), delimiter=";"))
        self.assertEqual(linhas[0][:4], ["Título", "Data", "Views", "Link"])
        self.assertEqual(linhas[1][0], "Ataque hacker no banco")
        self.assertIsNone(bib.exportar_csv(999, "videos", self.db))
        with self.assertRaises(ValueError):
            bib.exportar_csv(bid, "xyz", self.db)

    def test_variavel_de_ambiente_troca_o_banco(self):
        alt = os.path.join(self._tmp.name, "env.db")
        os.environ["NICHE_MINER_DB"] = alt
        try:
            bib.salvar_busca("Tema", ["t"], [], {}, {}, [], [])
            self.assertTrue(os.path.exists(alt))
            self.assertEqual(len(bib.listar_biblioteca()), 1)
        finally:
            del os.environ["NICHE_MINER_DB"]


if __name__ == "__main__":
    unittest.main(verbosity=2)
