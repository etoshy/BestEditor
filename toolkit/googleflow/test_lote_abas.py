"""Lote em várias abas (Vídeos modelados) contra uma IMITAÇÃO do Flow (flow_falso_teste/)
com os mesmos elementos do HTML real: chip Agente, configurações da caixa,
chip "Início" -> lista de imagens com envio de arquivo -> "Incluir no comando"."""
import collections
import functools
import http.server
import os
import shutil
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from googleflow import googleflow_client as g  # noqa: E402

_AQUI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow_falso_teste")


class _Servidor(http.server.SimpleHTTPRequestHandler):
    """Como o Flow: as imagens geradas ficam em /image/<id>?Expires=..."""
    def translate_path(self, path):
        if path.startswith("/image/"):
            path = "/asb/img.png"
        return super().translate_path(path)

    def log_message(self, *a):
        pass


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


def _variante(html: str, qual: str) -> str:
    """Versões ALTERADAS da imitação do Flow — o fluxo tem que aguentar todas."""
    if qual == "agente_ligado":  # layout antigo: chip Agente ligado esconde o botão de configurações
        html = html.replace(
            '<button class="settings-trigger-button" aria-label="Gatilho de configurações" id="gat" onclick="abreCfg()">',
            '<flow-agent-mode-toggle-chip><button class="agent-mode-chip" aria-pressed="true" onclick="this.setAttribute(\'aria-pressed\','
            ' this.getAttribute(\'aria-pressed\')==\'true\'?\'false\':\'true\'); document.getElementById(\'gat\').hidden ='
            ' this.getAttribute(\'aria-pressed\')==\'true\'">Agente</button></flow-agent-mode-toggle-chip>'
            '<button class="settings-trigger-button" aria-label="Gatilho de configurações" id="gat" hidden onclick="abreCfg()">')
    elif qual == "ingles_sem_rotulos":  # textos em inglês, grupos sem aria-label, classes trocadas
        html = (html.replace('`<flow-toggles aria-label="${label}">`', '`<flow-toggles>`')
                .replace("Vídeo", "Video").replace("Imagem", "Image")
                .replace("<flow-prompt-box-settings>", '<div class="cdk-overlay-pane">').replace("</flow-prompt-box-settings>`", "</div>`")
                .replace('class="detail-add-to-prompt-btn"', 'class="btn-add"').replace(" Incluir no comando ", " Add to prompt ")
                .replace('class="generate-icon-button" aria-label="Iniciar geração" id="gerar"', 'class="go" type="submit" aria-label="Generate" id="gerar"')
                .replace('class="settings-trigger-button" aria-label="Gatilho de configurações" id="gat"', 'class="cfg-btn" aria-label="Settings" id="gat"')
                .replace('id="chipInicio">Início<', 'id="chipInicio">Start<'))
    elif qual == "painel_com_salvar":  # o painel da caixa só aplica/fecha clicando em "Salvar" (Esc não fecha)
        html = (html.replace("if(e.key=='Escape' && !document.querySelector('.asset-picker'))", "if(false)")
                .replace("+ `</flow-prompt-box-settings>`; }",
                         "+ `<button class=\"settings-save-button\" onclick=\"document.getElementById('ov').innerHTML=''\">Salvar</button></flow-prompt-box-settings>`; }"))
        # e, enquanto as configurações não forem salvas, a geração não sai (como no Flow real)
        html = html.replace("function gera(){", "function gera(){ if (document.querySelector('#ov flow-prompt-box-settings')) return;")
        assert "settings-save-button" in html and "if (document.querySelector('#ov flow-prompt-box-settings')) return;" in html
    elif qual == "salvar_fora_do_painel":  # HTML real do usuário: <div class="save-container"><button class="settings-save-button">
        html = (html.replace("if(e.key=='Escape' && !document.querySelector('.asset-picker'))", "if(false)")
                .replace("function gera(){", "function gera(){ if (document.querySelector('#ov flow-prompt-box-settings')) return;")
                .replace("+ `</flow-prompt-box-settings>`; }",
                         "+ `</flow-prompt-box-settings><div class=\"save-container\"><button class=\"mdc-button settings-save-button\" "
                         "onclick=\"document.getElementById('ov').innerHTML=''\"><span class=\"mdc-button__label\"> Salvar </span></button></div>`; }")
                # cópia ESCONDIDA do botão de salvar antes, como o Flow faz com a caixa
                .replace('<div id="galeria"></div>', '<div style="display:none"><button class="settings-save-button">Salvar</button></div><div id="galeria"></div>'))
        assert "save-container" in html
    elif qual == "painel_agente_aberto":  # print do usuário: "Configurações do agente" aberto cobre a caixa
        painel = ('<button aria-label="Configurações do agente" id="btnAgente" onclick="abrePainelAgente()">tune</button>'
                  '<div id="painelAgente" class="side-panel"><div class="settings-content">'
                  '<div id="agent-settings-confirm-policy-label">Confirmar antes de gerar</div>'
                  '<flow-toggles aria-label="Proporção padrão da geração de imagens"><button class="mat-button-toggle-button" aria-checked="true">'
                  '<span class="toggle-text">9:16</span></button></flow-toggles></div>'
                  '<button aria-label="Fechar" onclick="fechaPainelAgente()"><mat-icon>close</mat-icon></button>'
                  '<div class="save-container"><button class="mdc-button settings-save-button" onclick="window.salvou=(window.salvou||0)+1; fechaPainelAgente()">'
                  '<span class="mdc-button__label"> Salvar </span></button></div></div>'
                  '<script>function abrePainelAgente(){ window.reabriu=(window.reabriu||0)+1; painelAgente.style.display=""; caixaVis.style.display="none"; }'
                  'function fechaPainelAgente(){ painelAgente.style.display="none"; caixaVis.style.display=""; }</script>')
        html = html.replace('<div class="base-prompt-box">\n <flow-ingredient-bar', painel + '<div class="base-prompt-box" id="caixaVis" style="display:none">\n <flow-ingredient-bar', 1)
        assert 'id="caixaVis"' in html
    elif qual == "compacto_com_consentimento":  # janela estreita do usuário: lista de mídias fora do pop-up + "Concordo"
        html = html.replace("<script>\nlet modo=", "<script>\nwindow.MOBILE = true; window.CONSENTIMENTO = true;\nlet modo=", 1)
        assert "window.MOBILE = true" in html
    elif qual == "primeiro_clique_falha":  # o botão de configurações ignora o 1º clique
        html = html.replace('onclick="abreCfg()"', 'onclick="if(!window._ja){window._ja=1;return;} abreCfg()"')
    return html


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
@pytest.mark.parametrize("variante", ["atual", "agente_ligado", "ingles_sem_rotulos", "primeiro_clique_falha", "painel_com_salvar", "salvar_fora_do_painel", "painel_agente_aberto", "compacto_com_consentimento"])
def test_lote_duas_abas_frame_e_animacao(tmp_path, monkeypatch, variante):
    site = tmp_path / "site"
    shutil.copytree(_AQUI, site)
    (site / "projeto.html").write_text(_variante((site / "projeto.html").read_text(encoding="utf-8"), variante), encoding="utf-8")
    (site / "asb").mkdir()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=400x700", "-frames:v", "1",
                    str(site / "asb" / "img.png")], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=90x160:d=1", "-pix_fmt", "yuv420p",
                    str(site / "v.mp4")], check=True)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Servidor, directory=str(site)))
    srv.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    porta = srv.server_address[1]
    from pathlib import Path
    monkeypatch.setattr(g, "pasta_dados", lambda: Path(tmp_path / "dados"))
    monkeypatch.setattr(g, "FLOW_URL", f"http://127.0.0.1:{porta}/index.html")
    monkeypatch.setattr(g, "SEL_NOVO_PROJETO", "#novo")
    monkeypatch.setattr(g, "PAUSA_APOS_NOVO_PROJETO_S", 0.5)
    monkeypatch.setattr(g, "ESTAVEL_S", 1.5)
    monkeypatch.setattr(g, "escolher_conta_disponivel", lambda *a, **k: "teste")
    for nome in ("salvar_sessao", "restaurar_sessao", "_dispensar_dialogos_de_boas_vindas", "_dispensar_changelog",
                 "_passar_pela_pagina_inicial", "configurar_projeto"):
        monkeypatch.setattr(g, nome, lambda *a, **k: None)
    monkeypatch.setattr(g, "_abrir", lambda p, cfg, headless, conta="x": (p.chromium.launch(headless=True).new_context(), True))
    try:
        cli = g.GoogleFlowClient({"browser_visible": True, "flow_modo_automacao": "antigo"})  # o jeito antigo continua de reserva
        frame = tmp_path / "cena_003_123.png"
        shutil.copy(site / "asb" / "img.png", frame)
        fila = collections.deque([
            cli.preparar_trabalho({"id": "f1", "tipo": "imagem", "prompt": "a dark well", "modelo": "Nano Banana 2.1", "proporcao": "9:16"}),
            cli.preparar_trabalho({"id": "f2", "tipo": "imagem", "prompt": "a girl", "modelo": "Nano Banana 2.1", "proporcao": "9:16"}),
            cli.preparar_trabalho({"id": "a1", "tipo": "animar", "prompt": "slow push-in", "imagem": str(frame),
                                   "modelo": "Omni 1.1 Flash", "resolucao": "720p", "duracao": "4s", "proporcao": "9:16"}),
        ])
        eventos = []

        def _ev(e):
            eventos.append(e)
            if e["tipo"] == "fim" and e["id"] == "f1":  # frame pronto -> anima ELE (como no ⚡ dos Vídeos modelados)
                assert e["media_id"], "o id da imagem gerada não foi lido da URL"
                fila.append(cli.preparar_trabalho({"id": "a2", "tipo": "animar", "prompt": "push-in on f1", "imagem": e["arquivo"],
                                                   "media_id": e["media_id"], "modelo": "Omni 1.1 Flash", "resolucao": "720p",
                                                   "duracao": "4s", "proporcao": "9:16"}))
        cli.gerar_lote(fila, abas=2, cooldown=(0.5, 1), on_evento=_ev)
        fins = {e["id"]: e for e in eventos if e["tipo"] == "fim"}
        assert set(fins) == {"f1", "f2", "a1", "a2"}, [e for e in eventos if e["tipo"] == "erro"]
        assert fins["a2"]["reaproveitou_frame"] is True and fins["a2"]["aba"] == fins["f1"]["aba"]  # usou a imagem do projeto
        assert fins["a1"]["reaproveitou_frame"] is False  # frame de fora: enviou o arquivo
        assert fins["a1"]["arquivo"].endswith(".mp4") and os.path.getsize(fins["a1"]["arquivo"]) > 1000
        assert {e["aba"] for e in eventos if e["tipo"] == "inicio"} == {1, 2}  # duas abas trabalharam
        assert os.path.exists(g.pasta_ao_vivo() / "aba_1.jpg")
        # o mesmo pedido de novo vem do cache, sem abrir o Flow
        fila.append(cli.preparar_trabalho({"id": "f1b", "tipo": "imagem", "prompt": "a dark well", "modelo": "Nano Banana 2.1", "proporcao": "9:16"}))
        eventos.clear()
        cli.gerar_lote(fila, abas=2, on_evento=eventos.append)
        assert eventos[0]["tipo"] == "fim" and eventos[0]["cache"]
    finally:
        g.encerrar_sessao()
        srv.shutdown()


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium não instalado")
def test_diagnostico_salva_html_so_da_parte_importante(tmp_path, monkeypatch):
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    monkeypatch.setattr(g, "pasta_dados", lambda: Path(tmp_path))
    html = _variante((Path(_AQUI) / "projeto.html").read_text(encoding="utf-8"), "painel_agente_aberto")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page()
        pg.set_content(html.replace('<div class="base-prompt-box"', '<div _ngcontent-ng-c123="" class="base-prompt-box"', 1))
        base = g.salvar_diagnostico(pg, "teste")
        b.close()
    texto = Path(base + "_html.txt").read_text(encoding="utf-8")
    assert "PAINEL CONFIGURAÇÕES DO AGENTE" in texto and "settings-save-button" in texto
    assert "BOTÕES VISÍVEIS" in texto and '"Salvar"' in texto
    assert "_ngcontent" not in texto and "cfg escondido" not in texto  # sem lixo do Angular nem o que está escondido
    assert "_html.txt" in g._aviso_diag(base)
