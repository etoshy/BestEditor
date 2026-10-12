"""Contratos estáticos da aba Método: o JS só usa ids que existem, scripts na ordem certa, aba ligada ao botão."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
JS_UI = (ROOT / "static" / "metodo_ui.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class ContratoMetodoTests(unittest.TestCase):
    def test_todo_id_usado_pelo_js_existe_no_html_e_nao_ha_duplicados(self):
        ids = re.findall(r'\sid="([^"]+)"', HTML)
        self.assertEqual(sorted(i for i in set(ids) if ids.count(i) > 1), [])
        faltando = sorted(set(re.findall(r'\$\("([\w-]+)"\)', JS_UI)) - set(ids))
        self.assertEqual(faltando, [])

    def test_scripts_carregam_na_ordem_de_dependencia(self):
        ordem = re.findall(r"filename='([\w]+\.js)'", HTML)
        self.assertLess(ordem.index("metodo.js"), ordem.index("metodo_ui.js"))
        self.assertLess(ordem.index("app.js"), ordem.index("metodo_ui.js"))          # usa escapeHtml, ultimoResultado, salvarPreferencias
        self.assertLess(ordem.index("ideias.js"), ordem.index("metodo_ui.js"))

    def test_botao_da_aba_aponta_para_a_view_existente(self):
        self.assertIn('data-view="metodo"', HTML)
        self.assertIn('id="view-metodo"', HTML)
        self.assertRegex(HTML, r'id="view-metodo" class="view" style="display:none"')      # começa escondida como as outras

    def test_barra_lateral_some_na_aba_como_na_de_ideias(self):
        self.assertIn('body[data-view="metodo"] .rail { display: none; }', CSS)

    def test_checklist_tem_chaves_unicas_e_prefixadas_pela_etapa(self):
        chaves = re.findall(r'class="mt-check" data-chave="([^"]+)"', HTML)
        self.assertEqual(len(chaves), len(set(chaves)))
        for c in chaves:
            self.assertRegex(c, r"^[0-5]-[a-z]+$")

    def test_o_atalho_da_mediana_usa_ids_que_existem_no_formulario_de_recomendacoes(self):
        self.assertIn('id="rec-ref"', HTML)
        self.assertIn('<option value="mediana"', HTML[HTML.index('id="rec-ref"'):])


if __name__ == "__main__":
    unittest.main(verbosity=2)
