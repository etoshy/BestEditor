"""Contratos estáticos da aba Analisar canal: ids do JS existem, scripts na ordem certa, HTML alinhado com o backend."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import canal

HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
JS_UI = (ROOT / "static" / "canal_ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class ContratoCanalTests(unittest.TestCase):
    def test_todo_id_usado_pelo_js_existe_no_html_e_nao_ha_duplicados(self):
        ids = re.findall(r'\sid="([^"]+)"', HTML)
        self.assertEqual(sorted(i for i in set(ids) if ids.count(i) > 1), [])
        self.assertEqual(sorted(set(re.findall(r'\$\("([\w-]+)"\)', JS_UI)) - set(ids)), [])

    def test_scripts_carregam_na_ordem_de_dependencia(self):
        ordem = re.findall(r"filename='([\w]+\.js)'", HTML)
        for antes in ("metodo.js", "canal.js", "app.js", "ideias.js"):
            self.assertLess(ordem.index(antes), ordem.index("canal_ui.js"), antes)       # usa NicheMetodo, NicheCanal, escapeHtml e o seletor das Ideias
        self.assertLess(ordem.index("metodo_ui.js"), ordem.index("canal_ui.js"))         # lê os limites de tração da aba Método

    def test_botao_da_aba_aponta_para_a_view_existente_e_ela_comeca_escondida(self):
        self.assertIn('data-view="canal"', HTML)
        self.assertRegex(HTML, r'id="view-canal" class="view" style="display:none"')
        self.assertIn('body[data-view="canal"] .rail { display: none; }', CSS)

    def test_tipos_de_ia_do_html_sao_os_mesmos_do_backend(self):
        tipos = re.findall(r'class="id-card mt-card cn-ia" data-tipo="(\w+)"', HTML)
        self.assertEqual(sorted(tipos), sorted(canal.TIPOS_IA))

    def test_cada_card_de_ia_tem_todos_os_elementos_que_o_js_procura(self):
        classes = set(re.findall(r'querySelector\("\.([\w-]+)"\)', JS_UI))
        for tipo in canal.TIPOS_IA:
            trecho = HTML[HTML.index(f'data-tipo="{tipo}"'):]
            trecho = trecho[:trecho.index('<div class="cn-out"></div>')]
            for c in classes:
                if c in ("cn-out",):
                    continue
                self.assertIn(c, trecho, f"{tipo}: falta .{c}")

    def test_ids_das_ponte_e_do_mapa(self):
        for i in ("rec-urls", "btn-rec-iniciar", "id-sessoes", "id-termos", "id-fluxo", "ms-n", "mp-cuidado", "mp-forte"):
            self.assertIn(f'id="{i}"', HTML, i)                                           # elementos de outras abas que a ponte usa
        self.assertEqual(len(re.findall(r"<tr>", HTML[HTML.index('id="cn-mapa"'):HTML.index("</table>", HTML.index('id="cn-mapa"'))])), 15)   # cabeçalho + 14


if __name__ == "__main__":
    unittest.main(verbosity=2)
