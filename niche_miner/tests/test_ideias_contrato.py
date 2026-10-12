"""Contrato entre ideias.js, o template e as rotas Flask (pega id/rota digitados errado)."""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as webapp

JS = (ROOT / "static" / "ideias.js").read_text(encoding="utf-8")
HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class ContratoIdeiasTests(unittest.TestCase):
    def test_aba_view_e_script_existem(self):
        self.assertIn('data-view="ideias"', HTML)
        self.assertIn('id="view-ideias"', HTML)
        self.assertIn("filename='ideias.js'", HTML)
        # o carregamento vem depois de app.js e biblioteca.js (depende das funções globais deles)
        self.assertLess(HTML.index("filename='app.js'"), HTML.index("filename='ideias.js'"))
        self.assertLess(HTML.index("filename='biblioteca.js'"), HTML.index("filename='ideias.js'"))

    def test_todo_id_usado_no_js_existe_no_html_ou_e_criado_pelo_proprio_js(self):
        html_ids = set(re.findall(r'id="([^"]+)"', HTML))
        js_ids = set(re.findall(r'id="([^"$]+)"', JS))          # ids criados em templates literais do JS
        usados = set(re.findall(r'\$\("([^"]+)"\)', JS))
        faltando = sorted(i for i in usados if i not in html_ids and i not in js_ids)
        self.assertEqual(faltando, [])

    def test_ids_dos_blocos_de_ia_batem_com_os_containers(self):
        # os três blocos são montados em containers que precisam existir no HTML
        for p in ("id-exp", "id-dec", "id-ide"):
            self.assertIn(f'id="{p}-ia"', HTML)
            self.assertIn(f'"{p}"', JS)
        for sufixo in ("gerar", "prompt-wrap", "prompt", "copiar", "texto", "validar", "fb"):
            self.assertIn(f'id="${{p}}-{sufixo}"', JS)

    def test_toda_url_da_api_usada_no_js_e_uma_rota_registrada(self):
        adaptador = webapp.app.url_map.bind("localhost")
        urls = set(re.findall(r'[`"](/api/ideias/[^`"?]*)[`"]', JS))
        self.assertGreaterEqual(len(urls), 8)
        for u in urls:
            caminho = re.sub(r"\$\{[^}]+\}", "1", u)
            achou = False
            for metodo in ("GET", "POST", "PATCH", "DELETE"):
                try:
                    adaptador.match(caminho, method=metodo)
                    achou = True
                    break
                except Exception:
                    continue
            self.assertTrue(achou, f"rota inexistente: {u}")

    def test_o_js_so_chama_rotas_do_proprio_modulo_ou_de_logs(self):
        externas = set(re.findall(r'[`"](/api/(?!ideias)[^`"?]*)', JS))
        self.assertEqual({re.sub(r"\$\{[^}]+\}", "X", e) for e in externas}, {"/api/logs/X"})

    def test_classes_css_usadas_no_js_existem_no_css(self):
        classes = set(re.findall(r'class="((?:id-[a-z-]+ ?)+)"', JS + HTML))
        conhecidas = {c for grupo in classes for c in grupo.split()}
        # classes dinâmicas (adicionadas como sufixo/estado) e utilitárias já existentes ficam de fora
        ausentes = sorted(c for c in conhecidas if f".{c}" not in CSS and c not in {"id-sel", "id-val-ck", "id-add-termo", "id-nota", "id-ideia-termos",
                                                                                      "id-fav", "id-desc", "id-restaurar", "id-rank"})
        self.assertEqual(ausentes, [])

    @unittest.skipUnless(shutil.which("node"), "node não instalado")
    def test_sintaxe_do_js(self):
        r = subprocess.run(["node", "--check", str(ROOT / "static" / "ideias.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_rail_so_some_na_aba_ideias(self):
        self.assertIn('body[data-view="ideias"] .rail { display: none; }', CSS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
