"""Contratos estáticos da aba API do YouTube: ids do JS existem no HTML, scripts na ordem, rotas e tipos de IA alinhados."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as webapp
import yt_ia

HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
JS_UI = (ROOT / "static" / "ytapi_ui.js").read_text(encoding="utf-8")
JS_PURO = (ROOT / "static" / "ytapi.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
SUBS = ("pesquisa", "alta", "comparar", "canal", "video", "historico")


class ContratoYtTests(unittest.TestCase):
    def test_todo_id_usado_pelo_js_existe_no_html_e_nao_ha_duplicados(self):
        ids = re.findall(r'\sid="([^"]+)"', HTML)
        self.assertEqual(sorted(i for i in set(ids) if ids.count(i) > 1), [])
        chamados = set(re.findall(r'\$\("([\w-]+)"\)', JS_UI))
        listados = set(re.findall(r'"(y[packvh]-[\w-]+)"', JS_UI))                       # ids em listas ("yp-f-views", ...)
        alvos = set(re.findall(r'alvo: "([\w-]+)"', JS_UI))
        dinamicos = {"yt-print"}                                                          # criado pelo JS na hora de imprimir
        self.assertEqual(sorted((chamados | listados | alvos) - set(ids) - dinamicos), [])

    def test_scripts_carregam_na_ordem_de_dependencia(self):
        ordem = re.findall(r"filename='([\w]+\.js)'", HTML)
        self.assertEqual(ordem.count("ytapi.js"), 1)
        self.assertEqual(ordem.count("ytapi_ui.js"), 1)
        self.assertLess(ordem.index("ytapi.js"), ordem.index("ytapi_ui.js"))
        self.assertLess(ordem.index("metodo.js"), ordem.index("ytapi_ui.js"))            # toCsv
        self.assertLess(ordem.index("app.js"), ordem.index("ytapi_ui.js"))               # escapeHtml
        self.assertLess(ordem.index("ideias.js"), ordem.index("ytapi_ui.js"))            # o clique da aba passa pelos handlers de navegação

    def test_botao_da_aba_view_e_css_do_rail(self):
        self.assertIn('data-view="yt"', HTML)
        self.assertRegex(HTML, r'id="view-yt" class="view" style="display:none"')
        self.assertIn('body[data-view="yt"] .rail { display: none; }', CSS)
        self.assertEqual(HTML.count("<main"), HTML.count("</main>"))
        self.assertLess(HTML.index('id="view-yt"'), HTML.index("</main>"))               # dentro do <main>

    def test_seis_sub_abas_com_painel_e_seis_ias_com_container(self):
        botoes = re.findall(r'class="yt-sub-btn[^"]*" data-sub="(\w+)"', HTML)
        self.assertEqual(botoes, list(SUBS))
        for s in SUBS:
            self.assertIn(f'id="yt-painel-{s}"', HTML, s)
        self.assertEqual(sorted(re.findall(r'id="(yt-ia-\w+)"', HTML)), ["yt-ia-alta", "yt-ia-canal", "yt-ia-comparar", "yt-ia-historico", "yt-ia-video"])

    def test_tipos_de_ia_do_js_sao_os_do_backend(self):
        tipos = re.findall(r'montarIA\("(\w+)"', JS_UI)
        self.assertEqual(sorted(tipos), sorted(yt_ia.TIPOS))
        for tipo in yt_ia.TIPOS:
            self.assertIn(f"    {tipo}: [", JS_UI, tipo)                                   # cada tipo tem seus renderizadores de resposta

    def test_o_card_de_ia_gerado_pelo_js_tem_todas_as_classes_que_ele_mesmo_procura(self):
        template = JS_UI[JS_UI.index("alvo.innerHTML = `"):JS_UI.index("const card = alvo.firstElementChild;")]
        buscadas = set(re.findall(r'q\("\.([\w-]+)"\)', JS_UI)) | set(re.findall(r'card\.querySelector\("\.([\w-]+)"\)', JS_UI))
        self.assertGreaterEqual(len(buscadas), 8)
        for c in buscadas:
            self.assertIn(c, template, f"falta .{c} no card de IA")

    def test_rotas_usadas_pelo_js_existem_no_flask(self):
        regras = {r.rule for r in webapp.app.url_map.iter_rules()}
        usadas = set(re.findall(r'"(/api/yt/[\w-]+)"', JS_UI))
        self.assertEqual(usadas, {"/api/yt/config", "/api/yt/pesquisar", "/api/yt/em-alta", "/api/yt/comparar", "/api/yt/canal", "/api/yt/video", "/api/yt/historico"})
        self.assertLessEqual(usadas, regras)
        self.assertIn("/api/yt/prompt/<tipo>", regras)
        self.assertIn("/api/yt/ia/<tipo>", regras)
        self.assertIn("/api/yt/miniatura", regras)
        self.assertIn("/api/yt/prompt/${tipo}", JS_UI)
        self.assertIn("/api/yt/ia/${tipo}", JS_UI)

    def test_a_chave_so_vai_nas_rotas_que_falam_com_o_youtube_e_nunca_na_url(self):
        com_chave = set(re.findall(r'postYT\("(/api/yt/[\w-]+)"', JS_UI))
        self.assertEqual(com_chave, {"/api/yt/pesquisar", "/api/yt/em-alta", "/api/yt/comparar", "/api/yt/canal", "/api/yt/video", "/api/yt/historico"})
        self.assertIn("const postYT = (url, corpo) => postJson(url, { ...corpo, chave: chave() });", JS_UI)
        for rota in ("/api/yt/prompt/${tipo}", "/api/yt/ia/${tipo}"):
            linha = next(l for l in JS_UI.splitlines() if rota in l)
            self.assertIn("postJson(", linha)
            self.assertNotIn("chave", linha)
        self.assertNotRegex(JS_UI, r"[?&]key=|[?&]chave=")
        self.assertNotIn("console.log", JS_UI)                                            # nada que imprima a chave ou os dados

    def test_so_ha_uma_chave_guardada_no_navegador_e_e_a_da_api(self):
        chaves = re.findall(r'"(niche_miner_yt_\w+)"', JS_UI)
        self.assertEqual(sorted(set(chaves)), ["niche_miner_yt_chave", "niche_miner_yt_cota", "niche_miner_yt_short"])

    def test_todo_texto_de_terceiros_passa_por_escape(self):
        # campos que vêm do YouTube só entram em innerHTML depois de esc()/cartao()/inteiro()/fmt()
        crus = re.findall(r"\$\{(?:v|c|x|l)\.(?:titulo|canal|descricao|handle|nicho|ideia|resumo)\}", JS_UI)
        self.assertEqual(crus, [], "campo de texto interpolado sem esc()")
        self.assertNotIn("v.thumb}", JS_UI.replace("esc(link(v.thumb))", ""))
        self.assertIn("textContent = v.descricao", JS_UI)
        self.assertIn("textContent = c.descricao", JS_UI)

    def test_modulo_puro_nao_toca_o_dom(self):
        codigo = re.sub(r"//.*", "", JS_PURO)                                             # comentários podem citar window.NicheYT
        for proibido in ("document.", "window.", "localStorage", "fetch(", "XMLHttpRequest"):
            self.assertNotIn(proibido, codigo, proibido)

    def test_css_de_impressao_esconde_tudo_menos_a_copia_do_relatorio(self):
        self.assertIn("body.yt-imprimindo > *:not(#yt-print) { display: none !important; }", CSS)
        self.assertIn("#yt-print { display: none; }", CSS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
