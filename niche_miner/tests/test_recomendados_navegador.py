"""Lateral de recomendados em Chromium REAL contra páginas SIMULADAS do YouTube.

A estrutura da lateral (yt-lockup-view-model) vem do HTML de um vídeo real enviado pelo usuário.
Valida a leitura, a resolução do canal e o fluxo completo. NÃO valida o YouTube ao vivo: o site muda
sem aviso e só uma execução real, na sua máquina, confirma os seletores.
"""
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import recomendados as rec
import recomendados_fixture as fx
import yt_scraper as core

try:
    from playwright.sync_api import sync_playwright
    _p = sync_playwright().start()
    _b = _p.chromium.launch(headless=True)
    _b.close()
    _p.stop()
    CHROMIUM = True
except Exception:  # sem Playwright/Chromium instalado
    CHROMIUM = False

SEED_A, SEED_B = "https://www.youtube.com/watch?v=SEEDAAAAAA1", "https://www.youtube.com/watch?v=SEEDBBBBBB2"


def site(paginas):
    """Roteador: devolve o HTML do dicionário {video_id: html}; 'ABORTAR' derruba a navegação."""
    def rota(route):
        m = re.search(r"[?&]v=([\w-]{11})", route.request.url)
        html = paginas.get(m.group(1)) if m else None
        if html == "ABORTAR":
            return route.abort()
        route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or "<html><body>nada</body></html>")
    return rota


class NavegadorBase(unittest.TestCase):
    """Chromium compartilhado + roteador das páginas simuladas (não tem testes próprios)."""

    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def pagina(self, paginas):
        ctx = self.browser.new_context()
        self.addCleanup(ctx.close)
        ctx.route("https://www.youtube.com/**", site(paginas))
        page = ctx.new_page()
        page.set_default_timeout(8000)
        return page


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class ColetaTests(NavegadorBase):
    def coletar(self, lockups, n=15, url=SEED_A, espera_ms=2500):
        page = self.pagina({"SEEDAAAAAA1": fx.pagina_watch("Vídeo de origem A", lockups)})
        return rec.coletar_recomendados(page, url, n, log=lambda *_: None, espera_ms=espera_ms)

    def test_le_os_15_primeiros_da_lateral_real_e_o_titulo_do_video_de_origem(self):
        titulo, brutos = self.coletar(fx.lockups_reais())
        self.assertEqual(titulo, "Vídeo de origem A")
        self.assertEqual(len(brutos), 15)
        self.assertEqual([b["id"] for b in brutos], [t[0] for t in fx.LATERAL_REAL[:15]])

    def test_campos_de_cada_tipo_de_item_real(self):
        _, brutos = self.coletar(fx.lockups_reais())
        por_id = {b["id"]: b for b in brutos}
        mist = por_id["m4Rz8S1yUqU"]     # não verificado, com "Novo"
        self.assertEqual((mist["canal"], mist["verificado"], mist["views_txt"], mist["quando_txt"], mist["dur_txt"], mist["novo"]),
                         ("Mistere", False, "90 mil", "há 3 dias", "32:56", True))
        self.assertTrue(por_id["iOL2SMkyn3I"]["verificado"])               # selo de check
        self.assertTrue(por_id["7beAvWZOSVs"]["verificado"])               # selo recortado
        self.assertEqual(por_id["iOL2SMkyn3I"]["quando_txt"], "há 14 horas")   # prefere o aria-label por extenso
        self.assertEqual(por_id["RkClGpnTwfU"]["views_txt"], "")           # só para membros: sem views
        self.assertEqual(por_id["1Dj247BKsTI"]["views_txt"], "1,3 mi")     # texto curto, não o aria-label sem número

    def test_o_selo_do_canal_nao_e_confundido_com_o_icone_de_views(self):
        _, brutos = self.coletar(fx.lockups_reais())
        nao_verificados = {b["canal"] for b in brutos if not b["verificado"]}
        self.assertEqual(nao_verificados, {"akS", "Капитан Флинт", "Olsior reacts", "Mistere", "Viktor Galvão"})   # Viktor é descartado depois, por ser antigo

    def test_colaboracao_com_dois_canais(self):
        _, brutos = self.coletar(fx.lockups_reais(), n=21)
        colab = next(b for b in brutos if b["id"] == "wr5tMxciPko")
        self.assertEqual(colab["canal"], "remary e Shooter_sz")
        self.assertTrue(colab["verificado"])

    def test_pede_mais_do_que_existe_devolve_o_que_tem_sem_travar(self):
        _, brutos = self.coletar(fx.lockups_reais(4), n=15)
        self.assertEqual(len(brutos), 4)

    def test_playlist_short_e_live_sao_lidos_e_classificados_como_nao_video(self):
        html = fx.lockup_playlist() + fx.lockup_short() + fx.lockup_ao_vivo() + fx.lockups_reais(1)
        _, brutos = self.coletar(html)
        tipos = {b["titulo"]: rec.normalizar_item(b)["tipo"] for b in brutos}
        self.assertEqual(tipos, {"Playlist de animes": "playlist", "Um short qualquer": "short", "Live agora": "live",
                                 fx.LATERAL_REAL[0][1]: "video"})
        live = next(rec.normalizar_item(b) for b in brutos if b["titulo"] == "Live agora")
        self.assertIsNone(live["views_num"])

    def test_layout_antigo_da_lateral_continua_funcionando(self):
        html = fx.lockup_layout_antigo("OLDVID00001", "Título antigo", "Canal Antigo", False) + fx.lockup_layout_antigo("OLDVID00002", "Outro", "Verificado Antigo", True)
        _, brutos = self.coletar(html)
        a, b = (rec.normalizar_item(x) for x in brutos)
        self.assertEqual((a["canal"], a["canal_verificado"], a["views_num"], a["duracao_segundos"]), ("Canal Antigo", False, 12000, 605))
        self.assertTrue(b["canal_verificado"])
        self.assertAlmostEqual(a["idade_meses"], 0.46, delta=0.02)   # "há 2 semanas"

    def test_pagina_sem_lateral_devolve_lista_vazia(self):
        _, brutos = self.coletar("", espera_ms=600)
        self.assertEqual(brutos, [])


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class ResolverCanalTests(NavegadorBase):
    """Reaproveita a infraestrutura; abre a página de um vídeo aprovado."""

    def item(self, vid="m4Rz8S1yUqU", **extra):
        base = {"video_id": vid, "titulo": "Estão Me Perseguindo...", "url": f"https://www.youtube.com/watch?v={vid}", "canal": "Mistere",
                "views_text": "90 mil", "views_num": 90000, "quando": "há 3 dias", "duracao": "32:56", "duracao_segundos": 1976,
                "origem_url": SEED_A, "razao_media": 3.8}
        base.update(extra)
        return base

    def test_resolve_canal_data_real_e_marca_o_video(self):
        pag = fx.pagina_video_candidato("Estão Me Perseguindo...", fx.CANAIS["Mistere"], "Mistere Oficial", dias_atras=3)
        page = self.pagina({"m4Rz8S1yUqU": pag})
        video, motivo = rec.validar_e_resolver(page, self.item(), meses_max=3)
        self.assertEqual(motivo, "ok")
        self.assertEqual((video["canal_url"], video["canal"], video["data_verificada"], video["canal_verificado"], video["views_num"]),
                         ("https://www.youtube.com/@mistere", "Mistere Oficial", True, False, 90000))
        self.assertTrue(video["data_publicacao"].startswith("20"))

    def test_handle_nao_latino_vira_o_mesmo_formato_dos_cards_de_busca(self):
        pag = fx.pagina_video_candidato("t", fx.CANAIS["Капитан Флинт"], "Капитан Флинт", dias_atras=3)
        page = self.pagina({"7F176Ym4J9c": pag})
        video, _ = rec.validar_e_resolver(page, self.item("7F176Ym4J9c"), meses_max=3)
        self.assertEqual(video["canal_url"], fx.CANAIS["Капитан Флинт"])

    def test_descarta_patrocinado_fora_do_periodo_e_canal_nao_identificado(self):
        casos = {
            "AAAAAAAAAA1": (fx.pagina_video_candidato("t", fx.CANAIS["Mistere"], "M", 3, patrocinado=True), "patrocinado"),
            "AAAAAAAAAA2": (fx.pagina_video_candidato("t", fx.CANAIS["Mistere"], "M", 200), "fora_do_periodo"),
            "AAAAAAAAAA3": (fx.pagina_video_candidato("t", fx.CANAIS["Mistere"], "M", 3, sem_dono=True), "canal_nao_identificado"),
        }
        page = self.pagina({vid: html for vid, (html, _) in casos.items()})
        for vid, (_, esperado) in casos.items():
            video, motivo = rec.validar_e_resolver(page, self.item(vid), meses_max=3)
            self.assertIsNone(video, vid)
            self.assertTrue(motivo.startswith(esperado), f"{vid}: {motivo}")

    def test_extrair_canal_direto(self):
        page = self.pagina({"m4Rz8S1yUqU": fx.pagina_video_candidato("t", fx.CANAIS["Mistere"], "Mistere", 3)})
        page.goto("https://www.youtube.com/watch?v=m4Rz8S1yUqU")
        self.assertEqual(rec.extrair_canal_da_pagina(page), ("https://www.youtube.com/@mistere", "Mistere"))


@unittest.skipUnless(CHROMIUM, "Chromium do Playwright não disponível")
class FluxoCompletoTests(NavegadorBase):
    def paginas(self):
        pags = {"SEEDAAAAAA1": fx.pagina_watch("Vídeo de origem A", fx.lockups_reais()), "SEEDBBBBBB2": "ABORTAR"}
        pags["m4Rz8S1yUqU"] = fx.pagina_video_candidato("Estão Me Perseguindo...", fx.CANAIS["Mistere"], "Mistere", 3)
        return pags

    def rodar(self, cfg=None, paginas=None):
        page = self.pagina(paginas or self.paginas())
        chamadas = []

        def analise_falsa(pg, videos, termo, subnicho, nicho, min_subs, max_videos, analise, cache):
            chamadas.append({"videos": videos, "termo": termo, "nicho": nicho, "min_subs": min_subs})
            return [{"canal": v["canal"], "canal_url": v["canal_url"], "score": 1.0} for v in videos]

        logs = []
        with mock.patch.object(core, "analisar_canais_nao_verificados", analise_falsa):
            resultado = rec.processar_recomendados(page, [SEED_A, SEED_B], cfg or {"referencia": "media"}, 5000, 100,
                                                   {"janela_meses": 3}, {}, "Anime", log=lambda *a: logs.append(" ".join(map(str, a))))
        return resultado, chamadas, logs

    def test_so_o_canal_acima_da_media_chega_a_analise_de_canais(self):
        (videos, ranked, falhas, rel), chamadas, _ = self.rodar()
        self.assertEqual([v["canal"] for v in videos], ["Mistere"])
        self.assertEqual(videos[0]["canal_url"], "https://www.youtube.com/@mistere")
        self.assertEqual(len(chamadas), 1)
        self.assertEqual((chamadas[0]["min_subs"], chamadas[0]["nicho"]), (5000, "Anime"))
        self.assertEqual([r["canal"] for r in ranked], ["Mistere"])
        self.assertEqual(videos[0]["termo_busca"], "Recomendados de: Vídeo de origem A")
        self.assertEqual((videos[0]["subnicho"], videos[0]["nicho"]), ("Sem subnicho", "Anime"))

    def test_falha_de_um_video_de_origem_nao_derruba_o_outro(self):
        (_, _, falhas, rel), _, logs = self.rodar()
        self.assertEqual(len(falhas), 1)
        self.assertIn("SEEDBBBBBB2", falhas[0])
        self.assertIn("ERRO ISOLADO", "\n".join(logs))
        self.assertEqual([o["origem_id"] for o in rel["origens"]], ["SEEDAAAAAA1"])

    def test_relatorio_explica_a_decisao(self):
        (_, _, _, rel), _, logs = self.rodar()
        g = rel["grupos"][0]
        self.assertEqual((g["coletados"], g["elegiveis"], g["valor"], g["aprovados"]), (15, 4, 23687, 1))
        analisados = [i["canal"] for i in rel["itens"] if i["analisado"]]
        self.assertEqual(analisados, ["Mistere"])
        self.assertEqual(rel["canais_analisados"], 1)
        motivos = {i["canal"]: i["motivo"] for i in rel["itens"] if i["canal"] in ("akS", "Olsior reacts", "ANCAPSU")}
        self.assertEqual(motivos, {"akS": "abaixo_da_media", "Olsior reacts": "abaixo_da_media", "ANCAPSU": "verificado"})
        texto = "\n".join(logs)
        self.assertIn("média = 23.687", texto)
        self.assertIn("1 aprovados", texto)

    def test_aprovado_que_falha_na_validacao_sai_do_resultado_com_motivo(self):
        pags = self.paginas()
        pags["m4Rz8S1yUqU"] = fx.pagina_video_candidato("t", fx.CANAIS["Mistere"], "Mistere", 3, patrocinado=True)
        (videos, ranked, _, rel), chamadas, _ = self.rodar(paginas=pags)
        self.assertEqual((videos, ranked), ([], []))
        item = next(i for i in rel["itens"] if i["canal"] == "Mistere")
        self.assertEqual((item["aprovado"], item["analisado"], item["motivo"]), (False, False, "validacao:patrocinado"))

    def test_mediana_leva_dois_canais_para_a_analise(self):
        pags = self.paginas()
        pags["5TOmOGjFVNw"] = fx.pagina_video_candidato("Огляд", fx.CANAIS["Olsior reacts"], "Olsior reacts", 11)
        (videos, _, _, _), _, _ = self.rodar({"referencia": "mediana"}, pags)
        self.assertEqual(sorted(v["canal"] for v in videos), ["Mistere", "Olsior reacts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
