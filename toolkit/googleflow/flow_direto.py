"""
flow_direto.py
==============

🎬 GOOGLE FLOW NO MODO DIRETO (v84_74) — reescrito a partir do HTML REAL de cada tela que o usuário mandou
(lista de projetos, projeto novo, configurações do agente, pop-up de configurações da caixa nos modos Imagem e
Vídeo, menus de modelo, caixa com Início/Fim, cartão "gerando 33%", menu de mídia com "Incluir no comando",
bloco da imagem gerada). Nada aqui é palpite de seletor: cada um está no HTML de `flow_simulado/`.

O passo a passo (o mesmo que a pessoa faz à mão):

  1. abre https://flow.google.com/ → "Novo projeto" (button.new-project-button) → /project/<id>
  2. com o Agente ligado, ícone "tune" (Configurações) → painel "Configurações do agente":
     "Confirmar antes de gerar" = Nunca, padrões de imagem e de vídeo (proporção, quantidade, modelo) → Salvar
  3. desliga o Agente (chip "Agente", aria-pressed) → aparece o "Gatilho de configurações" da caixa
  4. gatilho → pop-up: Modo (Imagem/Vídeo), Tipo de vídeo (Frames/Elementos), Proporção, modelo
     (menu "Selecionar família de modelos"), Quantidade (x1…x4) → clica fora pra fechar
  5. Vídeo → Frames: chips "Início"/"Fim" → menu de mídia → imagem do projeto (ou "Enviar mídia") →
     "Incluir no comando" (o "+" da caixa faz o mesmo pra uma imagem de referência)
  6. escreve o prompt (ProseMirror) → "Iniciar geração"
  7. o bloco novo mostra "33%"… e vira a imagem (img[data-media-id]) ou o vídeo
  8. baixa pelo link do flow-content.google (com os cookies do navegador)

Cada passo confere que deu certo e, se não deu, levanta `FlowPassoErro(passo, mensagem)` dizendo QUAL passo e o que
faltou. `on_passo(nome, estado, detalhe)` avisa o andamento (a área de teste mostra passo a passo).
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from playwright.sync_api import TimeoutError as PWTimeout
except ImportError:  # pragma: no cover
    class PWTimeout(Exception):  # type: ignore[no-redef]
        pass

FLOW_URL = "https://flow.google.com/"
RE_PROJETO = re.compile(r"/project/[0-9a-zA-Z-]{6,}")

# ------------------------------------------------------------------ seletores (todos confirmados no HTML real)
S = {
    "novo_projeto": "button.new-project-button",
    "criar_com_flow": 'button[aria-label="Crie com o Google Flow"]',
    "caixa": "flow-prompt-box",                                   # a caixa principal (a do painel do agente é outra)
    "editor": 'flow-prompt-box .ProseMirror[contenteditable="true"]',
    "gerar": 'flow-prompt-box button[aria-label="Iniciar geração"]',
    "agente_chip": ("flow-prompt-box flow-agent-mode-toggle-chip button.agent-mode-chip, "
                    "flow-prompt-box button.agent-mode-chip, flow-prompt-box button:has(.agent-mode-chip-label), "
                    'flow-prompt-box button:has-text("Agente"):not([aria-label])'),
    "agente_config": 'flow-prompt-box .agent-footer-actions button[aria-label="Configurações"]',
    "agente_painel": "flow-settings-view",
    "agente_nunca": '.confirm-policy-group mat-radio-button:has(input[value="2"])',
    "agente_nunca_input": '.confirm-policy-group input[value="2"]',
    "agente_salvar": "button.settings-save-button",
    "agente_modelo_imagem": "button.image-model-picker-button",
    "agente_modelo_video": "button.video-model-picker-button",
    "gatilho": 'flow-prompt-box button.settings-trigger-button',
    "resumo": "flow-prompt-box .settings-summary",
    "popup": "flow-prompt-box-settings",
    "popup_modelo": 'flow-prompt-box-settings button[aria-label="Selecionar família de modelos"]',
    "menu_modelos": ".flow-model-picker-panel",
    "creditos": "flow-prompt-box-settings .credit-cost-label",
    "chip_frame": "flow-prompt-box flow-ingredient-bar .frame-trigger",
    "adicionar": 'flow-prompt-box button.add-menu-trigger',
    "menu_midia": "flow-add-menu-popover-content",
    "midia_item": "flow-add-menu-popover-content button.asset-item",
    "midia_enviar": "flow-add-menu-popover-content button.sidebar-upload-btn",
    "midia_previa": "flow-add-menu-popover-content img.detail-preview-image",
    "midia_incluir": "flow-add-menu-popover-content button.detail-add-to-prompt-btn",
    "progresso": ".loading-percentage",
    "erro_uso": ".error-text",
    "creditos_banner": "flow-credit-banner",
}
# grupos de opções do pop-up / do painel (aria-label do flow-toggles)
GRUPO = {"modo": "Modo", "tipo_video": "Tipo de vídeo", "proporcao": "Proporção", "quantidade": "Quantidade de resultados",
         "img_proporcao": "Proporção padrão da geração de imagens", "img_quantidade": "Quantidade padrão de imagens geradas",
         "vid_proporcao": "Proporção padrão para geração de vídeo", "vid_quantidade": "Quantidade padrão de vídeos gerados"}
PROPORCOES = ("16:9", "4:3", "1:1", "3:4", "9:16")
MODELOS_IMAGEM = ("Nano Banana Pro", "Nano Banana 2 Lite", "Nano Banana 2.1")
MODELOS_VIDEO = ("Omni 1.1 Flash", "Veo 3.1 - Lite", "Veo 3.1 - Fast", "Veo 3.1 - Quality")

# resultado: os blocos de mídia do projeto (fora de pop-ups/menus): imagem com data-media-id ou vídeo
JS_MIDIAS = r"""() => {
  const fora = e => !e.closest('.cdk-overlay-container, flow-add-menu-popover-content, flow-prompt-box, flow-settings-view');
  const out = [];
  document.querySelectorAll('img[data-media-id]').forEach(i => { if (fora(i)) out.push({id: i.dataset.mediaId, url: i.currentSrc || i.src, tipo: 'imagem'}); });
  document.querySelectorAll('video').forEach(v => { if (!fora(v)) return;
    const s = v.currentSrc || v.src || ((v.querySelector('source') || {}).src) || '';
    const id = v.dataset.mediaId || (s.match(/\/video\/([0-9a-zA-Z_-]{8,})/) || [])[1] || s;
    if (s) out.push({id: id, url: s, tipo: 'video'}); });
  return out; }"""
# cartões ainda gerando (com a %) e cartões que falharam (texto de erro no lugar da %)
JS_CARTOES = r"""() => Array.from(document.querySelectorAll('.loading-percentage')).map(p => {
  const c = p.closest('.container') || p.parentElement;
  return {pct: (p.innerText || '').trim(), texto: ((c && c.querySelector('.subtitle')) || {}).innerText || ''}; })"""
JS_AVISOS = r"""() => Array.from(document.querySelectorAll('.error-text, mat-snack-bar-container, simple-snack-bar, [role="alert"]'))
  .filter(e => e.getClientRects().length > 0).map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400)"""
RE_LIMITE = re.compile(r"limite de uso|cr[eé]ditos? insuficiente|sem cr[eé]ditos|limit|quota|cota", re.I)
RE_FALHA = re.compile(r"n[ãa]o foi poss[ií]vel|falh|erro ao gerar|viola|pol[ií]tica|policy|unable to generate|couldn.t generate", re.I)


class FlowPassoErro(Exception):
    """Um passo do Flow não deu certo. `passo` diz qual (pra mostrar na área de teste e no log)."""

    def __init__(self, passo: str, mensagem: str):
        super().__init__(f"[{passo}] {mensagem}")
        self.passo, self.mensagem = passo, mensagem


class FlowLimite(FlowPassoErro):
    """O Flow avisou limite de uso / sem créditos (troca de conta)."""


class FlowLogin(FlowPassoErro):
    """O Flow pediu login."""


class FlowRecusou(FlowPassoErro):
    """O Flow recusou o pedido (política de conteúdo / falha na geração)."""


Passo = Callable[[str, str, str], None]


def _nada(_n: str, _e: str, _d: str) -> None:
    pass


def _esperar(cond: Callable[[], bool], timeout_s: float, passo_s: float = 0.25) -> bool:
    fim = time.monotonic() + timeout_s
    while True:
        try:
            if cond():
                return True
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() >= fim:
            return False
        time.sleep(passo_s)


def _visivel(page, sel: str) -> bool:
    try:
        loc = page.locator(sel)
        return any(loc.nth(k).is_visible() for k in range(min(loc.count(), 6)))
    except Exception:  # noqa: BLE001
        return False


def _primeiro(page, sel: str, timeout_s: float = 10.0, passo: str = "", erro: str = ""):
    """O 1º elemento VISÍVEL de `sel` (espera até `timeout_s`). Sem ele: FlowPassoErro(passo, erro)."""
    achado = [None]

    def _tem() -> bool:
        loc = page.locator(sel)
        for k in range(min(loc.count(), 8)):
            if loc.nth(k).is_visible():
                achado[0] = loc.nth(k)
                return True
        return False
    if _esperar(_tem, timeout_s):
        return achado[0]
    if passo:
        raise FlowPassoErro(passo, erro or f"não apareceu: {sel}")
    return None


def _marcado(el) -> bool:
    try:
        return (el.get_attribute("aria-checked") or el.get_attribute("aria-pressed")) == "true"
    except Exception:  # noqa: BLE001
        return False


def _texto_opcao(texto: str) -> str:
    return texto.replace('"', '\\"')


# ------------------------------------------------------------------ 1. abrir e criar projeto
LARGURA_MIN = 900      # janela pequena: o Flow vira o layout estreito e o chip "Agente" some (com ~900px ele aparece)
JANELA = {"width": 1400, "height": 950}


def garantir_largura(page, minimo: int = LARGURA_MIN) -> int:
    """Janela estreita = o Flow esconde o chip "Agente" (e outros botões). Se a página está mais estreita que
    `minimo`, aumenta a JANELA do navegador (Chromium: CDP) — ou, se não der, o viewport. Devolve a largura final."""
    try:
        largura = int(page.evaluate("window.innerWidth"))
    except Exception:  # noqa: BLE001
        return 0
    if largura >= minimo:
        return largura
    try:
        cdp = page.context.new_cdp_session(page)
        wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": dict(JANELA)})
        _esperar(lambda: int(page.evaluate("window.innerWidth")) >= minimo, 3)
        largura = int(page.evaluate("window.innerWidth"))
    except Exception:  # noqa: BLE001
        pass
    if largura < minimo:
        try:
            page.set_viewport_size({"width": JANELA["width"], "height": JANELA["height"] - 100})
            largura = int(page.evaluate("window.innerWidth"))
        except Exception:  # noqa: BLE001
            pass
    return largura


def abrir_flow(context, url: str = FLOW_URL, headless: bool = True, on_passo: Passo = _nada, timeout_login_s: float = 300):
    """Abre a lista de projetos. Sem o botão "Novo projeto" = precisa de login (oculto: erro na hora)."""
    on_passo("abrir", "andando", url)
    page = context.new_page()
    garantir_largura(page)
    page.goto(url, wait_until="domcontentloaded")
    try:  # apresentação do Flow (algumas contas): "Crie com o Google Flow"
        b = page.locator(S["criar_com_flow"]).first
        b.wait_for(state="visible", timeout=4_000)
        b.click()
        page.wait_for_load_state("domcontentloaded")
    except Exception:  # noqa: BLE001
        pass
    if _primeiro(page, S["novo_projeto"], 15) is None:
        if headless or timeout_login_s <= 0:
            page.close()
            raise FlowLogin("abrir", "o Flow pediu login (não apareceu \"Novo projeto\"). Faça o login uma vez com o "
                                     "navegador visível (Configurações → Google Flow → Fazer login).")
        on_passo("abrir", "andando", "faça o login na janela do navegador…")
        if _primeiro(page, S["novo_projeto"], timeout_login_s) is None:
            raise FlowLogin("abrir", f"tempo esgotado ({int(timeout_login_s)}s) esperando o login no Flow.")
    on_passo("abrir", "ok", "lista de projetos aberta")
    return page


def novo_projeto(page, context=None, on_passo: Passo = _nada):
    """Clica em "Novo projeto" e devolve a página do projeto (mesma aba ou aba nova)."""
    on_passo("novo_projeto", "andando", "")
    antes = set(context.pages) if context is not None else set()
    _primeiro(page, S["novo_projeto"], 15, "novo_projeto", 'não achei o botão "Novo projeto"').click()
    alvo = [page]
    fim = time.monotonic() + 30
    abriu = False
    while time.monotonic() < fim and not abriu:
        try:  # wait_for_url processa os eventos do navegador (time.sleep não: a URL ficaria velha)
            alvo[0].wait_for_url(RE_PROJETO, timeout=700)
            abriu = True
        except Exception:  # noqa: BLE001
            if context is not None:
                novas = [p for p in context.pages if p not in antes]
                if novas:
                    alvo[0] = novas[-1]
    if not abriu:
        raise FlowPassoErro("novo_projeto", f"cliquei em \"Novo projeto\" mas o projeto não abriu (ficou em {page.url}).")
    p = alvo[0]
    if p is not page:
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass
    p.wait_for_load_state("domcontentloaded")
    garantir_largura(p)
    _primeiro(p, S["editor"], 30, "novo_projeto", "o projeto abriu mas a caixa \"O que você quer criar?\" não apareceu.")
    on_passo("novo_projeto", "ok", p.url)
    return p


# ------------------------------------------------------------------ 2. configurações do agente
def _toggle(raiz, grupo: str, texto: str, passo: str, obrigatorio: bool = True) -> bool:
    """Marca a opção `texto` do grupo (flow-toggles[aria-label=grupo]) e confere aria-checked."""
    if not texto:
        return False
    sel = f'flow-toggles[aria-label="{grupo}"] button[role="radio"]:has(.toggle-text:text-is("{_texto_opcao(texto)}"))'
    el = _primeiro(raiz, sel, 5)
    if el is None:
        if obrigatorio:
            raise FlowPassoErro(passo, f'não achei a opção "{texto}" em "{grupo}".')
        return False
    if _marcado(el):
        return True
    for _ in range(3):
        el.click()
        if _esperar(lambda: _marcado(el), 3):
            return True
    if obrigatorio:
        raise FlowPassoErro(passo, f'cliquei em "{texto}" ({grupo}) mas não ficou marcado.')
    return False


def _escolher_no_menu_modelos(page, nome: str, passo: str) -> None:
    """Menu de modelos aberto → clica no item (pelo nome, sem o emoji) e confere que o menu fechou."""
    menu = _primeiro(page, S["menu_modelos"], 6, passo, "o menu de modelos não abriu.")
    item = menu.locator(f'flow-menu-item button:has(.label:has-text("{_texto_opcao(nome)}"))').first
    try:
        item.wait_for(state="visible", timeout=4_000)
    except PWTimeout:
        nomes = [t.strip() for t in menu.locator(".label").all_inner_texts()]
        page.keyboard.press("Escape")
        raise FlowPassoErro(passo, f'o modelo "{nome}" não está no menu (tem: {", ".join(nomes)}).')
    item.click()
    _esperar(lambda: not _visivel(page, S["menu_modelos"]), 4)
    if _visivel(page, S["menu_modelos"]):  # abriu um submenu (versões do modelo): fica com a opção já marcada
        page.keyboard.press("Escape")


def configurar_agente(page, img_proporcao: str = "16:9", img_quantidade: str = "x1", img_modelo: str = "",
                      vid_proporcao: str = "16:9", vid_quantidade: str = "x1", vid_modelo: str = "",
                      on_passo: Passo = _nada) -> None:
    """Agente ligado → "tune" → Confirmar antes de gerar = NUNCA + padrões de imagem/vídeo → Salvar."""
    passo = "config_agente"
    on_passo(passo, "andando", "")
    ligar_agente(page, True)
    _primeiro(page, S["agente_config"], 10, passo, 'não achei o botão "Configurações" (ícone tune) do agente.').click()
    painel = _primeiro(page, S["agente_painel"], 10, passo, 'o painel "Configurações do agente" não abriu.')
    nunca = _primeiro(painel, S["agente_nunca"], 5, passo, 'não achei a opção "Nunca" em "Confirmar antes de gerar".')
    for _ in range(3):
        if painel.locator(S["agente_nunca_input"]).first.is_checked():
            break
        nunca.locator("label").first.click()
        _esperar(lambda: painel.locator(S["agente_nunca_input"]).first.is_checked(), 2)
    if not painel.locator(S["agente_nunca_input"]).first.is_checked():
        raise FlowPassoErro(passo, '"Confirmar antes de gerar" não ficou em "Nunca".')
    _toggle(painel, GRUPO["img_proporcao"], img_proporcao, passo, obrigatorio=False)
    _toggle(painel, GRUPO["img_quantidade"], img_quantidade, passo, obrigatorio=False)
    _toggle(painel, GRUPO["vid_proporcao"], vid_proporcao, passo, obrigatorio=False)
    _toggle(painel, GRUPO["vid_quantidade"], vid_quantidade, passo, obrigatorio=False)
    for botao, nome in ((S["agente_modelo_imagem"], img_modelo), (S["agente_modelo_video"], vid_modelo)):
        if not nome:
            continue
        b = _primeiro(painel, botao, 3)
        if b is None or nome.lower() in (b.inner_text() or "").lower():
            continue
        b.click()
        _escolher_no_menu_modelos(page, nome, passo)
    _primeiro(page, S["agente_salvar"], 5, passo, 'não achei o "Salvar" das configurações do agente.').click()
    if not _esperar(lambda: not _visivel(page, S["agente_painel"]), 8):
        raise FlowPassoErro(passo, 'cliquei em "Salvar" mas o painel do agente não fechou.')
    on_passo(passo, "ok", f"Nunca · imagem {img_proporcao} {img_quantidade} {img_modelo} · vídeo {vid_proporcao} {vid_quantidade} {vid_modelo}")


def ligar_agente(page, ligado: bool) -> None:
    chip = _primeiro(page, S["agente_chip"], 8)
    if chip is None:  # janela estreita esconde o chip: alarga e procura de novo
        largura = garantir_largura(page)
        chip = _primeiro(page, S["agente_chip"], 6)
    if chip is None:
        if ligado:
            raise FlowPassoErro("agente", f'não achei o chip "Agente" da caixa (a página tem {largura}px de largura — '
                                          'com a janela pequena o Flow esconde esse botão; deixe a janela maior).')
        return  # sem o chip: a caixa já está no modo direto
    for _ in range(3):
        if _marcado(chip) == ligado:
            return
        chip.click()
        _esperar(lambda: _marcado(chip) == ligado, 3)
    if _marcado(chip) != ligado:
        raise FlowPassoErro("agente", f'o chip "Agente" não ficou {"ligado" if ligado else "desligado"}.')


def desligar_agente(page, on_passo: Passo = _nada) -> None:
    on_passo("desligar_agente", "andando", "")
    ligar_agente(page, False)
    _primeiro(page, S["gatilho"], 8, "desligar_agente",
              'desliguei o Agente mas o botão de configurações da caixa (modelo · x1) não apareceu.')
    on_passo("desligar_agente", "ok", "")


# ------------------------------------------------------------------ 3. configurações da caixa (pop-up)
def abrir_popup(page):
    if _visivel(page, S["popup"]):
        return _primeiro(page, S["popup"], 1)
    _primeiro(page, S["gatilho"], 10, "configurar", 'não achei o botão de configurações da caixa (modelo · x1).').click()
    return _primeiro(page, S["popup"], 6, "configurar", "cliquei nas configurações da caixa mas o pop-up não abriu.")


def fechar_popup(page) -> None:
    """Fecha clicando FORA do pop-up (como a pessoa faz); se não fechar, Escape."""
    for k in range(3):
        if not _visivel(page, S["popup"]):
            return
        if k == 0:
            vp = page.viewport_size or {"width": 1280, "height": 800}
            page.mouse.click(max(5, vp["width"] // 2), 12)
        else:
            page.keyboard.press("Escape")
        _esperar(lambda: not _visivel(page, S["popup"]), 2)
    if _visivel(page, S["popup"]):
        raise FlowPassoErro("configurar", "o pop-up de configurações da caixa não fechou.")


def resumo(page) -> str:
    try:
        return " ".join((page.locator(S["resumo"]).first.inner_text() or "").split())
    except Exception:  # noqa: BLE001
        return ""


def configurar_caixa(page, tipo: str = "imagem", proporcao: str = "16:9", modelo: str = "", quantidade: str = "x1",
                     tipo_video: str = "Frames", on_passo: Passo = _nada) -> Dict[str, str]:
    """tipo "imagem" ou "video". Vídeo: `tipo_video` "Frames" (início/fim) ou "Elementos" (só o texto).
    Devolve {"resumo", "creditos"}."""
    passo = "configurar"
    on_passo(passo, "andando", f"{tipo} {proporcao} {modelo} {quantidade}")
    pop = abrir_popup(page)
    _toggle(pop, GRUPO["modo"], "Vídeo" if tipo == "video" else "Imagem", passo)
    pop = abrir_popup(page)  # trocar o modo redesenha o pop-up
    if tipo == "video" and tipo_video:
        _toggle(pop, GRUPO["tipo_video"], tipo_video, passo)
    if proporcao:
        _toggle(pop, GRUPO["proporcao"], proporcao, passo, obrigatorio=proporcao in ("16:9", "9:16"))
    if modelo:
        b = _primeiro(page, S["popup_modelo"], 4, passo, 'não achei o botão do modelo no pop-up.')
        if modelo.lower() not in (b.inner_text() or "").lower():
            b.click()
            _escolher_no_menu_modelos(page, modelo, passo)
            pop = abrir_popup(page)
            b = _primeiro(page, S["popup_modelo"], 4, passo, 'o pop-up fechou depois de escolher o modelo.')
            if modelo.lower() not in (b.inner_text() or "").lower():
                raise FlowPassoErro(passo, f'escolhi "{modelo}" mas o modelo ficou "{" ".join((b.inner_text() or "").split())}".')
    if quantidade:
        _toggle(pop, GRUPO["quantidade"], quantidade, passo, obrigatorio=False)
    creditos = ""
    try:
        creditos = " ".join((pop.locator(".credit-cost-label").first.inner_text() or "").split())
    except Exception:  # noqa: BLE001
        pass
    fechar_popup(page)
    r = resumo(page)
    if tipo == "video" and r and "vídeo" not in r.lower() and "video" not in r.lower():
        raise FlowPassoErro(passo, f'pedi Vídeo mas a caixa mostra "{r}".')
    on_passo(passo, "ok", f"{r} · {creditos}".strip(" ·"))
    return {"resumo": r, "creditos": creditos}


# ------------------------------------------------------------------ 4. mídia: frames (início/fim) e referência
def _escolher_midia(page, arquivo: Optional[str], media_id: str, nome: str, passo: str) -> str:
    """Menu de mídia aberto → escolhe a imagem do projeto (`media_id`) ou envia `arquivo` → Incluir no comando."""
    _primeiro(page, S["menu_midia"], 8, passo, "o menu de mídia (imagens do projeto / Enviar mídia) não abriu.")
    item = None
    if media_id:
        item = _primeiro(page, f'{S["midia_item"]}:has(img[src*="{media_id}"])', 6)
    origem = "do projeto"
    if item is None:
        if not arquivo:
            raise FlowPassoErro(passo, "a imagem não está no projeto e nenhum arquivo foi dado pra enviar.")
        antes = page.locator(S["midia_item"]).count()
        enviar = _primeiro(page, S["midia_enviar"], 5, passo, 'não achei o botão "Enviar mídia".')
        try:
            with page.expect_file_chooser(timeout=10_000) as escolha:
                enviar.click()
            escolha.value.set_files(arquivo)
        except PWTimeout:
            raise FlowPassoErro(passo, 'cliquei em "Enviar mídia" mas a janela de escolher arquivo não abriu.')
        origem = "enviada"
        if not _esperar(lambda: page.locator(S["midia_incluir"]).count() > 0 and page.locator(S["midia_item"]).count() > antes, 120):
            raise FlowPassoErro(passo, "enviei a imagem mas ela não apareceu na lista de mídias do Flow.")
        item = page.locator(S["midia_item"]).first  # a mais recente vem primeiro ("Recentes")
    item.click()
    _primeiro(page, S["midia_previa"], 60, passo, "escolhi a imagem mas a prévia não carregou.")
    _primeiro(page, S["midia_incluir"], 10, passo, 'não achei o botão "Incluir no comando".').click()
    if not _esperar(lambda: not _visivel(page, S["menu_midia"]), 8):
        raise FlowPassoErro(passo, 'cliquei em "Incluir no comando" mas o menu de mídia não fechou.')
    return origem


def definir_frame(page, qual: str = "Início", arquivo: Optional[str] = None, media_id: str = "",
                  on_passo: Passo = _nada) -> str:
    """Vídeo → Frames: chip "Início" ou "Fim" → imagem → "Incluir no comando". Confere que o chip ficou preenchido."""
    passo = "frame_" + ("inicio" if qual.lower().startswith("in") else "fim")
    on_passo(passo, "andando", media_id or (arquivo or ""))
    chips = page.locator(S["chip_frame"])
    if not _esperar(lambda: chips.count() >= 2, 8):
        raise FlowPassoErro(passo, 'os campos "Início"/"Fim" não apareceram (o modo Vídeo → Frames está ligado?).')
    chip = chips.nth(0 if passo.endswith("inicio") else 1)
    (chip.locator("button").first if chip.locator("button").count() else chip).click()  # o botão do chip, não a moldura
    origem = _escolher_midia(page, arquivo, media_id, qual, passo)
    if not _esperar(lambda: chip.locator("button.empty-chip").count() == 0, 10):
        raise FlowPassoErro(passo, f'incluí a imagem mas o campo "{qual}" continua vazio.')
    on_passo(passo, "ok", f"imagem {origem}")
    return origem


def incluir_referencia(page, arquivo: Optional[str] = None, media_id: str = "", on_passo: Passo = _nada) -> str:
    """"+" da caixa → imagem de referência (pra modificar uma foto com um prompt novo)."""
    passo = "referencia"
    on_passo(passo, "andando", media_id or (arquivo or ""))
    _primeiro(page, S["adicionar"], 8, passo, 'não achei o "+" (Adicionar elementos à caixa de comando).').click()
    origem = _escolher_midia(page, arquivo, media_id, "referência", passo)
    on_passo(passo, "ok", f"imagem {origem}")
    return origem


# ------------------------------------------------------------------ 5. prompt, gerar, esperar
def escrever_prompt(page, texto: str, on_passo: Passo = _nada) -> None:
    passo = "prompt"
    texto = " ".join((texto or "").split())
    if not texto:
        raise FlowPassoErro(passo, "o prompt está vazio.")
    on_passo(passo, "andando", texto[:80])
    ed = _primeiro(page, S["editor"], 10, passo, 'não achei onde digitar ("O que você quer criar?").')
    amostra = texto[:25].lower()

    def _entrou() -> bool:
        return amostra in " ".join((ed.inner_text() or "").split()).lower()
    for k in range(3):
        ed.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        if k == 0:
            page.keyboard.insert_text(texto)
        else:
            page.keyboard.type(texto, delay=6)
        if _esperar(_entrou, 3):
            on_passo(passo, "ok", "")
            return
    raise FlowPassoErro(passo, "cliquei na caixa mas o texto do prompt não entrou nela.")


def midias_na_pagina(page) -> List[Dict[str, str]]:
    try:
        return list(page.evaluate(JS_MIDIAS) or [])
    except Exception:  # noqa: BLE001
        return []


def avisos(page) -> str:
    try:
        return str(page.evaluate(JS_AVISOS) or "")
    except Exception:  # noqa: BLE001
        return ""


def clicar_gerar(page, on_passo: Passo = _nada) -> Dict[str, Any]:
    """Clica UMA vez em "Iniciar geração" (clicar de novo cobraria duas vezes). Devolve o estado pra `checar`."""
    passo = "gerar"
    on_passo(passo, "andando", "")
    antes = {m["id"] for m in midias_na_pagina(page)}
    avisos_antes = avisos(page)
    botao = _primeiro(page, S["gerar"], 8, passo, 'não achei o botão "Iniciar geração".')
    if not _esperar(lambda: botao.is_enabled() and botao.get_attribute("disabled") is None, 15):
        av = avisos(page)
        if av and RE_LIMITE.search(av):
            raise FlowLimite(passo, "o Flow avisou: " + av)
        raise FlowPassoErro(passo, '"Iniciar geração" continua desabilitado (o prompt entrou?).' + (f" Aviso: {av}" if av else ""))
    n_cartoes = len(page.evaluate(JS_CARTOES) or [])
    botao.click()
    on_passo(passo, "ok", "pedido enviado")
    return {"antes": antes, "avisos_antes": avisos_antes, "cartoes_antes": n_cartoes, "t0": time.monotonic(),
            "viu_cartao": False, "pct": ""}


def checar(page, estado: Dict[str, Any], tipo: str = "imagem") -> Optional[List[Dict[str, str]]]:
    """Não bloqueia: None = ainda gerando; lista = as mídias NOVAS (imagem/vídeo). Erro nomeado se o Flow recusou."""
    novas = [m for m in midias_na_pagina(page) if m["id"] not in estado["antes"]
             and (m["tipo"] == ("video" if tipo == "video" else "imagem"))]
    cartoes = page.evaluate(JS_CARTOES) or []
    if cartoes:
        estado["viu_cartao"] = True
        estado["pct"] = cartoes[-1].get("pct") or estado.get("pct") or ""
        falhou = [c for c in cartoes if RE_FALHA.search(c.get("pct") or "")]
        if falhou:
            raise FlowRecusou("esperar", "o Flow não gerou: " + (falhou[-1].get("pct") or ""))
    if novas and not cartoes:
        return novas
    av = avisos(page)
    if av and av != estado.get("avisos_antes"):
        if RE_LIMITE.search(av):
            raise FlowLimite("esperar", "o Flow avisou: " + av)
        if RE_FALHA.search(av):
            raise FlowRecusou("esperar", "o Flow recusou: " + av)
    return None


def esperar_resultado(page, estado: Dict[str, Any], tipo: str = "imagem", timeout_s: float = 300,
                      on_passo: Passo = _nada) -> List[Dict[str, str]]:
    passo = "esperar"
    ultimo = None
    while True:
        r = checar(page, estado, tipo)
        if r:
            on_passo(passo, "ok", f"{len(r)} {tipo}(s) pronta(s)")
            return r
        if estado.get("pct") != ultimo:
            ultimo = estado.get("pct")
            on_passo(passo, "andando", f"gerando {ultimo}" if ultimo else "gerando…")
        if time.monotonic() - estado["t0"] > timeout_s:
            raise FlowPassoErro(passo, f"tempo esgotado ({int(timeout_s)}s) esperando o Flow"
                                + (f" (parou em {estado['pct']})" if estado.get("pct") else
                                   " — nenhum cartão \"gerando\" apareceu: o pedido chegou a ser enviado?"))
        time.sleep(1.0)


# ------------------------------------------------------------------ tudo junto (um pedido)
def gerar_um(page, trab: Dict[str, Any], on_passo: Passo = _nada, timeout_s: float = 300) -> List[Dict[str, str]]:
    """Um pedido completo numa página de projeto JÁ preparada (agente configurado e desligado).
    trab = {"tipo": "imagem"|"video", "prompt", "proporcao", "modelo", "tipo_video": "Frames"|"Elementos",
            "inicio": {"arquivo", "media_id"}, "fim": {...}, "referencia": {...}, "simular": bool}"""
    tipo = "video" if trab.get("tipo") in ("video", "animar") else "imagem"
    frames = tipo == "video" and (trab.get("inicio") or trab.get("fim") or (trab.get("tipo_video") or "Frames") == "Frames")
    configurar_caixa(page, tipo, trab.get("proporcao") or "16:9", trab.get("modelo") or "", trab.get("quantidade") or "x1",
                     ("Frames" if frames else "Elementos") if tipo == "video" else "", on_passo=on_passo)
    for qual, chave in (("Início", "inicio"), ("Fim", "fim")):
        f = trab.get(chave) or {}
        if tipo == "video" and (f.get("arquivo") or f.get("media_id")):
            definir_frame(page, qual, f.get("arquivo"), f.get("media_id") or "", on_passo)
    ref = trab.get("referencia") or {}
    if tipo == "imagem" and (ref.get("arquivo") or ref.get("media_id")):
        incluir_referencia(page, ref.get("arquivo"), ref.get("media_id") or "", on_passo)
    escrever_prompt(page, trab["prompt"], on_passo)
    if trab.get("simular"):  # 🧪 teste sem gastar crédito: para aqui, antes do clique em gerar
        on_passo("gerar", "pulado", "modo teste sem gerar (nenhum crédito gasto)")
        return []
    estado = clicar_gerar(page, on_passo)
    return esperar_resultado(page, estado, tipo, timeout_s, on_passo)


def preparar_projeto(context, url: str = FLOW_URL, headless: bool = True, agente: Optional[Dict[str, str]] = None,
                     on_passo: Passo = _nada):
    """Abre o Flow, cria um projeto, configura o agente (se `agente` vier) e desliga o agente. → página do projeto."""
    page = abrir_flow(context, url, headless, on_passo)
    page = novo_projeto(page, context, on_passo)
    if agente is not None:
        configurar_agente(page, on_passo=on_passo, **agente)
    desligar_agente(page, on_passo)
    return page
