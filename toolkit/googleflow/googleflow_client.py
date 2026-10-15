"""
googleflow_client.py
====================

Geração de imagens com IA no Google Flow (https://flow.google.com/),
automatizando o navegador com Playwright. É o script `flow_gerador.py`
(o mesmo fluxo e os mesmos seletores) reorganizado como um módulo, pra
o site poder usar o Flow como uma FONTE de imagens igual aos bancos de
foto (Pexels, Wikipedia...): a IA que monta o roteiro escolhe
`"provider": "flow"` + `"media_type": "image"` e a `query` vira o pedido
de imagem.

O que mudou em relação ao script solto:

- Modo OCULTO (`browser_visible = False` na config do site): o navegador
  roda sem janela. O login no Google precisa de uma janela visível UMA
  vez (ver `GoogleFlowClient.login_interativo`); depois disso a sessão
  fica no perfil do navegador e o modo oculto funciona sozinho. Se a
  sessão expirar, em modo oculto a geração falha com
  `GoogleFlowLoginRequired` (mensagem explicando o que fazer) em vez de
  ficar esperando um login que ninguém consegue fazer.
- Cache: o mesmo pedido de imagem (mesmo texto + mesma proporção) nunca
  é gerado duas vezes — a prévia gera, a montagem final reaproveita.
  Gerar no Flow demora e gasta créditos; repetir seria desperdício.
- UM navegador e UMA conversa pro vídeo inteiro: ao gerar a primeira
  imagem, abre o Flow, cria um projeto novo e faz a configuração uma vez
  ("Confirmar antes de gerar" -> Nunca, quantidade -> x1, Salvar); as imagens
  seguintes são digitadas na MESMA conversa, uma atrás da outra. Uma thread
  própria é dona do navegador (o Playwright síncrono não pode trocar de
  thread) e as buscas do site entram numa fila. O navegador fecha sozinho
  depois de `OCIOSO_S` sem pedidos; se uma geração falhar, a conversa é
  descartada e a próxima começa um projeto novo (navegador continua aberto).
- Pastas resolvidas a partir da raiz do projeto (`flow_dados/`), não do
  diretório onde o servidor foi iniciado.

LOGIN AUTOMÁTICO (opcional): em vez de digitar e-mail/senha na janela, você
pode informar os dois e o site preenche sozinho (`login_automatico`). A senha só
é usada na hora e nunca vai pra nenhum arquivo do projeto -- se você marcar pra
guardá-la, ela vai pro cofre de credenciais do sistema operacional (pacote
`keyring`; no Windows é o Gerenciador de Credenciais), não pro `contas.json`.
Os seletores do formulário de login do Google (`SEL_GOOGLE_*`) são um palpite
baseado em como essa página costuma ser -- NÃO foram testados contra o Google
de verdade, e o Google muda esse formulário com frequência. Além disso, o
Google ativamente desconfia de login automatizado: pode pedir verificação em
duas etapas ou bloquear com "este navegador pode não ser seguro" -- nesses
casos a janela continua aberta (os mesmos 5 minutos do login manual) pra você
completar à mão. Ative por sua conta e risco: automatizar o login pode
contrariar os termos do Google e arriscar a conta.

VÁRIAS CONTAS: cada conta Google tem o seu próprio perfil de navegador (o login
é feito uma vez, à mão, numa janela visível — nenhuma senha é guardada). Quando o
Flow avisa que o limite/créditos da conta acabou, ela é marcada como esgotada por
`flow_horas_ate_liberar` horas, o navegador é reaberto com o perfil da PRÓXIMA conta
e o MESMO pedido é refeito lá. A conta "principal" usa o perfil de sempre.

Não compartilhe nem versione `flow_dados/perfis_navegador/`: quem tiver o
`sessao.json` acessa a conta Google.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import string
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # playwright é opcional: só é exigido de verdade na hora de gerar
    from playwright.sync_api import TimeoutError as PWTimeout
    PLAYWRIGHT_DISPONIVEL = True
except ImportError:  # pragma: no cover - depende do ambiente
    PLAYWRIGHT_DISPONIVEL = False

    class PWTimeout(Exception):  # type: ignore[no-redef]
        """Substituto usado só quando o playwright não está instalado
        (ex: testes) — assim o resto do módulo continua importável."""


CDP_URL = "http://localhost:9222"
FLOW_URL = "https://flow.google.com/"
FLOW_URL_POS_LOGIN = "https://flow.google.com/?pli=1"  # usada só logo após um login automático (ver login_automatico)
GOOGLE_LOGIN_URL = "https://accounts.google.com/login?hl=pt-br"
GOOGLE_TROCAR_SENHA_URL = "https://myaccount.google.com/intro/signinoptions/password?hl=pt-BR"
URL_PREFIXO_IMAGENS = "/flow/imagens/"   # rota do Flask que serve as imagens geradas
TIMEOUT_GERACAO_S = 300                  # tempo máximo esperando a geração (5 min)
TIMEOUT_LOGIN_S = 300                    # tempo máximo esperando o login (janela visível)
PAUSA_APOS_NOVO_PROJETO_S = 3.0
NAVEGADORES_VALIDOS = ("auto", "chrome", "edge", "chromium", "firefox", "webkit", "cdp")
ORDEM_AUTO = ["chrome", "edge", "chromium", "firefox", "webkit"]
CONTA_PADRAO = "principal"  # a conta de sempre (perfil sem sufixo); não pode ser removida
# Trechos que, na resposta do Flow SEM imagem, indicam limite/créditos esgotados.
# O texto exato do Flow não é conhecido: se o seu for diferente, acrescente
# palavras em Configurações (`flow_palavras_limite`).
PALAVRAS_LIMITE = (
    "crédito", "credito", "credits", "credit limit", "quota", "cota diária", "cota de", "limite",
    "limit reached", "usage limit", "daily limit", "exceeded", "excedeu", "excedid", "esgotou", "esgotad", "run out of",
)
OCIOSO_S = 120.0          # sem pedidos por tanto tempo => fecha o navegador
ESTAVEL_S = 5.0           # imagem apareceu e nada mudou por tanto tempo => terminou
PAUSA_POLLING_S = 1.0
GRACA_SEM_IMAGEM_S = 8.0  # resposta só de texto: espera um pouco a imagem chegar antes de desistir

# Seletores (baseados no HTML do Flow — se o Google mudar a página, é aqui
# que se ajusta)
SEL_NOVO_PROJETO = "button.new-project-button"
SEL_EDITOR_PROMPT = ".agent-panel-prompt-box .ProseMirror"
SEL_BOTAO_ENVIAR = ".agent-panel-prompt-box button.generate-icon-button"
SEL_MENSAGEM = "flow-a2ui-message-renderer"
SEL_IMAGEM = "flow-a2ui-image-option img.image-thumbnail"

# Formulário de login do Google (accounts.google.com) -- IDs/seletores conhecidos
# do formulário "clássico", mas NÃO verificados contra o site real (ver docstring
# do módulo). Se o Google mudar isso, o login automático passa a falhar (a janela
# fica aberta e a pessoa completa à mão, então nada trava por causa disso).
# Confirmados pelo usuário via HTML real de accounts.google.com/login?hl=pt-br:
# o campo de e-mail tem id="identifierId" e o de senha name="Passwd" -- os botões
# "Avançar" não têm um id estável no HTML que ele mandou (pode existir num elemento
# pai que não veio na captura -- por isso mantemos #identifierNext/#passwordNext
# como tentativa extra, historicamente estáveis nessa tela), então usamos o texto
# do botão como seletor principal (funciona com a conta em pt-br; "Next" cobre
# contas em inglês).
SEL_GOOGLE_EMAIL = "#identifierId"
SEL_GOOGLE_EMAIL_PROXIMO = '#identifierNext, button:has-text("Avançar"), button:has-text("Next")'
SEL_GOOGLE_SENHA = 'input[name="Passwd"]'
SEL_GOOGLE_SENHA_PROXIMO = '#passwordNext, button:has-text("Avançar"), button:has-text("Next")'

# Duas caixas de boas-vindas que o Flow mostra na PRIMEIRA vez que uma conta é
# usada nele (confirmado pelo usuário via HTML real): uma apresentação e a
# política de privacidade. A 2ª só libera o botão "Continuar"/"Avançar" depois
# de rolar o texto até o fim.
SEL_DIALOGO_BOASVINDAS = "app-onboarding-dialog"
SEL_DIALOGO_BOTAO_PRIMARIO = SEL_DIALOGO_BOASVINDAS + " button.flow-button-primary"
SEL_DIALOGO_FIM_DO_TEXTO = SEL_DIALOGO_BOASVINDAS + " .scroll-end-target"

# Página de apresentação (flow.google.com/about) que algumas contas veem em vez
# de ir direto pro app -- confirmado pelo usuário via HTML real. O botão "Crie
# com o Google Flow" leva pro app de verdade (a aba recarrega depois do clique).
SEL_BOTAO_CRIAR_COM_FLOW = 'button[aria-label="Crie com o Google Flow"]'

# Troca de senha (confirmado pelo usuário via HTML real de
# myaccount.google.com/intro/signinoptions/password): antes de trocar, o
# Google às vezes pede a senha ATUAL de novo pra "confirmar identidade" (o
# mesmo campo name="Passwd" do login; o botão desta vez tem id="passwordNext"
# confirmado). Depois disso (ou direto, se a sessão já era recente) aparece o
# formulário com os dois campos da senha NOVA e o botão "Alterar senha".
SEL_REAUTH_SENHA = 'input[name="Passwd"]'
SEL_REAUTH_AVANCAR = "#passwordNext"
# Se aparecer isso, o Google está pedindo pra resolver um captcha -- o site
# NUNCA tenta resolver: para na hora e avisa (ver trocar_senha).
SEL_REAUTH_CAPTCHA = "#captchaimg"
SEL_NOVA_SENHA = 'input[name="password"]'
SEL_CONFIRMAR_NOVA_SENHA = 'input[name="confirmation_password"]'
SEL_ALTERAR_SENHA_BOTAO = 'button:has-text("Alterar senha")'

SENHA_GERADA_CARACTERES = string.ascii_lowercase + string.digits


def gerar_senha_aleatoria(tamanho: int = 10) -> str:
    """Senha aleatória (criptograficamente segura) só com letras minúsculas e
    números -- o formato pedido pra troca automática de senha."""
    return "".join(secrets.choice(SENHA_GERADA_CARACTERES) for _ in range(tamanho))

# Aviso de novidades da versão -- pode aparecer DEPOIS de clicar em "Novo
# projeto" (confirmado pelo usuário via HTML real). Diferente das caixas de
# boas-vindas: aparece uma vez só, sem rolagem, e some sozinho ao clicar
# "Começar" -- não reaparece nas próximas vezes que essa conta abre um projeto.
SEL_CHANGELOG_MODAL = "flow-change-log-modal, .change-log-modal"  # v84_107: a tag do HTML real
SEL_CHANGELOG_BOTAO_PRIMARIO = "flow-change-log-modal button.flow-button-primary, .change-log-modal button.flow-button-primary"

# Painel de configurações do agente (HTML fornecido pelo usuário). O BOTÃO que
# abre esse painel não é conhecido com certeza: tentamos os candidatos abaixo
# (+ o seletor configurado em `flow_seletor_configuracoes`) e confirmamos que o
# painel abriu esperando o rótulo `SEL_PAINEL_ROTULO`.
SEL_PAINEL_ROTULO = "#agent-settings-confirm-policy-label"
SEL_PAINEL = ".settings-content"
SEL_CONFIRMAR_NUNCA = '.confirm-policy-group mat-radio-button:has(input[value="2"])'   # value 1 = Sempre, 2 = Nunca
SEL_CONFIRMAR_NUNCA_INPUT = '.confirm-policy-group input[value="2"]'
SEL_IMAGENS_X1 = ('.settings-content > .settings-section:nth-child(2) '
                  'button.mat-button-toggle-button:has(.toggle-text:text-is("x1"))')  # 2ª seção = imagens
# 3ª seção do painel = "Padrão para geração de vídeo" (mesma estrutura da de
# imagens: proporção, quantidade, modelo). A ORDEM das seções (Confirmar /
# Imagens / Vídeo) e todos os seletores abaixo foram confirmados num único
# HTML real do painel inteiro (não mais um "melhor esforço").
SEL_VIDEO_X1 = ('.settings-content > .settings-section:nth-child(3) '
                'button.mat-button-toggle-button:has(.toggle-text:text-is("x1"))')
SEL_VIDEO_MODELO_BOTAO = '.settings-content > .settings-section:nth-child(3) button.video-model-picker-button'
SEL_SALVAR_CONFIG = "button.settings-save-button"
# Seção de IMAGENS do painel (2ª): proporção padrão e modelo padrão (HTML real
# enviado pelo usuário: flow-toggles[aria-label="Proporção padrão da geração de
# imagens"] e o botão .image-model-picker-button que abre o menu com
# "🍌 Nano Banana Pro" / "🍌 Nano Banana 2 Lite" / "🍌 Nano Banana 2.1").
SEL_IMAGEM_PROPORCAO = 'flow-toggles[aria-label*="Proporção padrão da geração de imagens"] button.mat-button-toggle-button'
SEL_IMAGEM_MODELO_BOTAO = 'button.image-model-picker-button'
SEL_VIDEO_PROPORCAO = 'flow-toggles[aria-label*="Proporção padrão para geração de vídeo"] button.mat-button-toggle-button'

# ---- Animar uma imagem (vídeo com FRAME inicial) — fluxo enviado pelo usuário:
# + (adicionar elementos) -> escolhe a imagem -> espera a prévia carregar ->
# "Incluir no comando" -> desliga o modo Agente -> abre o "Gatilho de
# configurações" da caixa -> Vídeo -> Frames -> modelo (Omni 1.1 Flash) ->
# 720p -> 4s -> x1 -> digita o movimento -> Iniciar geração.
SEL_CAIXA_PROMPT = ".base-prompt-box"
SEL_EDITOR_CAIXA = [".agent-panel-prompt-box .ProseMirror", ".base-prompt-box .ProseMirror",
                    "flow-rich-text-editor .ProseMirror"]
SEL_BOTAO_ADICIONAR = 'button.add-menu-trigger, button[aria-label="Adicionar elementos à caixa de comando"]'
SEL_PREVIA_CARREGADA = "img.detail-preview-image"
SEL_INCLUIR_NO_COMANDO = 'button:has-text("Incluir no comando")'
SEL_CHIP_AGENTE = "flow-agent-mode-toggle-chip button.agent-mode-chip"
SEL_GATILHO_CONFIG_CAIXA = 'button.settings-trigger-button, button[aria-label="Gatilho de configurações"]'
SEL_CONFIG_CAIXA = "flow-prompt-box-settings"
SEL_BOTAO_GERAR = 'button.generate-icon-button, button[aria-label="Iniciar geração"]'
SEL_MODELO_CAIXA = 'flow-prompt-box-settings button[aria-label="Selecionar família de modelos"]'
# itens do menu "+" que abrem o seletor de arquivo do computador (texto exato do Flow
# não foi confirmado: vários candidatos) — e, se não houver, o 1º cartão com imagem
SEL_ITEM_ENVIAR_ARQUIVO = ('.cdk-overlay-pane [role="menuitem"]:has-text("Enviar"), '
                           '.cdk-overlay-pane [role="menuitem"]:has-text("Upload"), '
                           '.cdk-overlay-pane [role="menuitem"]:has-text("Carregar"), '
                           '.cdk-overlay-pane [role="menuitem"]:has-text("computador"), '
                           '.cdk-overlay-pane button:has-text("Enviar"), .cdk-overlay-pane button:has-text("Upload")')
SEL_ITEM_IMAGEM_RECENTE = ".cdk-overlay-pane img"
# Modo direto com Vídeo + Frames ligado (HTML real enviado pelo usuário): a caixa
# ganha a barra de ingredientes com os chips "Início" e "Fim". Clicar em
# "Início" abre a lista de imagens do projeto (button.asset-item com o nome do
# arquivo em .asset-title); escolher uma abre a prévia com o botão
# "Incluir no comando" (button.detail-add-to-prompt-btn).
SEL_CHIP_FRAME = "flow-ingredient-bar .frame-trigger"
SEL_ASSET_ITEM = ".cdk-overlay-container button.asset-item"
SEL_BTN_INCLUIR = 'button.detail-add-to-prompt-btn, button:has-text("Incluir no comando")'
SEL_BTN_ENVIAR_ARQUIVO = ('.cdk-overlay-container button:has-text("Enviar"), .cdk-overlay-container button:has-text("Fazer upload"), '
                          '.cdk-overlay-container button:has-text("Upload"), .cdk-overlay-container button:has-text("Carregar"), '
                          '.cdk-overlay-container [role="menuitem"]:has-text("Enviar"), .cdk-overlay-container [role="menuitem"]:has-text("Upload")')
# imagens geradas no projeto (fora dos menus/pop-ups): link do flow-content.google ou /asb/
JS_IMAGENS_NA_PAGINA = """() => { const u = [];
    document.querySelectorAll('img').forEach(i => { const s = i.currentSrc || i.src || '';
        if (!s || i.closest('.cdk-overlay-container, .mobile-add-menu-container, flow-add-menu-asset-item, .asset-item')) return;
        if (!/flow-content\\.google|\\/asb\\/|googleusercontent|\\/image\\//.test(s)) return;
        if ((i.naturalWidth || 0) < 120) return;
        if (!u.includes(s)) u.push(s); });
    return u; }"""
JS_VIDEOS_FORA_DOS_MENUS = """() => { const u = [];
    document.querySelectorAll('video, video source').forEach(v => { const s = v.currentSrc || v.src || '';
        if (s && !v.closest('.cdk-overlay-container') && !u.includes(s)) u.push(s); });
    return u; }"""
_RE_FALHA_GERACAO = re.compile(r"falh|não foi possível|nao foi possivel|não conseguimos|erro ao gerar|violat|polític|policy|unable to generate|couldn.t generate", re.IGNORECASE)
TIMEOUT_IMAGEM_LOTE_S = 300
TIMEOUT_PREVIA_S = 180
JS_VIDEOS_NA_PAGINA = """() => { const u = [];
    document.querySelectorAll('video, video source').forEach(v => { const s = v.currentSrc || v.src || '';
        if (s && !u.includes(s)) u.push(s); });
    return u; }"""
SEL_BOTAO_CONFIGURACOES = [
    # os dois primeiros são os mais específicos -- confirmados pelo HTML real
    # que o usuário mandou: o botão fica dentro de .agent-footer-actions,
    # ao lado do de "Instruções para o agente" (ambos dentro de
    # .bottom-controls > .submit-controls). Restringir a esse container evita
    # bater sem querer numa OUTRA engrenagem da tela (ex: a de configurações
    # gerais da conta, na barra superior, que também contém "onfigura"/
    # "setting" no aria-label e fica bem mais cedo no DOM).
    '.agent-footer-actions button[aria-label*="onfigura" i]',
    '.agent-footer-actions button:has(mat-icon:text-is("tune"))',
    'button[aria-label*="onfigura" i]',
    'button[aria-label*="etting" i]',
    'button[aria-label*="referên" i]',
    # \".agent-panel\" (sem \"-prompt-box\") nunca bateu com nada -- não existe
    # elemento com essa classe EXATA no HTML real, só \"agent-panel-prompt-box\"
    # (um seletor de classe CSS exige o nome inteiro, não aceita substring).
    # Mantidos como candidatos mais amplos, agora com o nome certo.
    '.agent-panel-prompt-box button:has(mat-icon:text-is("settings"))',
    '.agent-panel-prompt-box button:has(mat-icon:text-is("tune"))',
    'button:has(mat-icon:text-is("settings"))',
    'button:has(mat-icon:text-is("tune"))',
]

# Balão da mensagem DO USUÁRIO na conversa (HTML fornecido pelo usuário): aparece
# quando o Flow aceita o pedido. Não é contado em SEL_MENSAGEM (que são as
# respostas do agente).
SEL_MSG_USUARIO = ".message-row.user-row"
# Avisos que o Material mostra por cima da página (toast/snackbar, alerta, diálogo):
# é onde um "limite atingido" costuma aparecer, fora do chat.
SEL_AVISOS = ('.error-text, '  # confirmado pelo usuário: "Você chegou ao limite de uso." vem nessa classe
              'mat-snack-bar-container, snack-bar-container, simple-snack-bar, '
              '[role="alert"], [role="alertdialog"], mat-dialog-container, [role="dialog"]')

JS_ESTADO = """([msgSel, imgSel, antes]) => {
    const novas = Array.from(document.querySelectorAll(msgSel)).slice(antes);
    const ultima = novas.length ? novas[novas.length - 1] : null;
    const urls = [];
    novas.forEach(m => m.querySelectorAll(imgSel).forEach(im => urls.push(im.src)));
    return {
        mensagens: novas.length,
        urls: urls,
        ultima_e_texto: !!ultima && !!ultima.querySelector('flow-a2ui-text') &&
                        !ultima.querySelector('flow-a2ui-multiple-choice'),
        texto: ultima ? (ultima.innerText || '').trim().slice(0, 300) : '',
        avisos: Array.from(document.querySelectorAll('__AVISOS__'))
                     .map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400)
    };
}"""
# VÍDEO gerado (Veo) na conversa do agente. O HTML exato do cartão de vídeo do
# Flow NÃO foi confirmado num HTML real (o das imagens foi) — por isso vários
# candidatos e a possibilidade de trocar em Configurações (`flow_seletor_video`).
SEL_VIDEO = "flow-a2ui-video-option video, flow-a2ui-message-renderer video, flow-a2ui-video-option source"
JS_ESTADO_VIDEO = JS_ESTADO.replace(
    "novas.forEach(m => m.querySelectorAll(imgSel).forEach(im => urls.push(im.src)));",
    "novas.forEach(m => m.querySelectorAll(imgSel).forEach(v => { const s = v.currentSrc || v.src || "
    "((v.querySelector && v.querySelector('source')) || {}).src || ''; if (s && !urls.includes(s)) urls.push(s); }));",
)
# baixa um blob:/URL de dentro da página (o vídeo pode não ter URL pública)
JS_BAIXAR_BASE64 = """async (url) => {
    const r = await fetch(url); const b = await r.blob();
    return await new Promise(ok => { const f = new FileReader(); f.onload = () => ok(String(f.result).split(',')[1] || ''); f.readAsDataURL(b); });
}"""
TIMEOUT_VIDEO_MIN_S = 600   # vídeo (Veo) demora bem mais que imagem
GRACA_SEM_VIDEO_S = 240.0   # o agente costuma responder "gerando..." em texto antes do vídeo chegar
JS_AVISOS = """() => Array.from(document.querySelectorAll('__AVISOS__'))
    .map(e => (e.innerText || '').trim()).filter(Boolean).join(' | ').slice(0, 400)"""
JS_TEXTO_PAGINA = "() => (document.body.innerText || '').slice(-3000)"
# Só as partes do HTML que importam pra ajustar o site (caixa de comando, pop-ups, painéis
# abertos, botões visíveis), limpas do "lixo" do Angular — pra você copiar e mandar.
JS_HTML_IMPORTANTE = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const limpa = h => h.replace(/\s_ng[a-z]+-[a-z0-9-]+="[^"]*"/g, '').replace(/<svg[\s\S]*?<\/svg>/g, '<svg/>')
    .replace(/<!---->/g, '').replace(/\s(bis_skin_checked|mat-ripple-loader-[a-z-]+|cdk-describedby-host|aria-describedby)="[^"]*"/g, '')
    .replace(/<span class="mat-(focus-indicator|mdc-button-touch-target|mdc-button-persistent-ripple|ripple)[^"]*"[^>]*><\/span>/g, '')
    .replace(/\n\s*\n/g, '\n');
  const partes = [], vistos = new Set();
  const add = (titulo, els, mesmoEscondido) => els.forEach((e, i) => {
    if ((!vis(e) && !mesmoEscondido) || vistos.has(e)) return;
    for (const v of vistos) if (v.contains(e)) return;
    vistos.add(e);
    partes.push('<!-- ===== ' + titulo + ' ' + (i + 1) + (vis(e) ? '' : ' (ESCONDIDA na tela)') + ' ===== -->\n'
      + limpa(e.outerHTML).slice(0, 40000));
  });
  const caixas = [...document.querySelectorAll('flow-prompt-box, .base-prompt-box')];
  add('CAIXA DE COMANDO', caixas);
  add('PAINEL CONFIGURAÇÕES DO AGENTE', [...document.querySelectorAll('.settings-content')].map(e =>
      e.closest('[role=dialog], aside, mat-sidenav, mat-drawer, .side-panel, [class*=panel]') || e.parentElement));
  add('POP-UP / MENU ABERTO', [...document.querySelectorAll('.cdk-overlay-pane, [role=dialog], [role=alertdialog]')]);
  if (!partes.length) add('CAIXA DE COMANDO', caixas, true);  // nada visível (o erro pode ser esse): manda a caixa escondida
  const botoes = [...document.querySelectorAll('button')].filter(vis).slice(0, 80).map(b =>
      '- "' + (b.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 50) + '" aria-label="' + (b.getAttribute('aria-label') || '') +
      '" class="' + (b.getAttribute('class') || '').split(' ').filter(c => !/^(mdc-|mat-mdc|mat-unthemed|flow-button-no)/.test(c)).join(' ') + '"');
  return 'URL: ' + location.href + '\n\n' + partes.join('\n\n') + '\n\n<!-- ===== BOTÕES VISÍVEIS ===== -->\n' + botoes.join('\n');
}"""
JS_ESTADO = JS_ESTADO.replace("__AVISOS__", SEL_AVISOS)
JS_ESTADO_VIDEO = JS_ESTADO_VIDEO.replace("__AVISOS__", SEL_AVISOS)
JS_AVISOS = JS_AVISOS.replace("__AVISOS__", SEL_AVISOS)
JS_BOTOES = """() => Array.from(document.querySelectorAll('button'))
    .filter(b => b.offsetParent !== null).slice(0, 40)
    .map(b => { const i = b.querySelector('mat-icon');
                return (b.getAttribute('aria-label') || '(sem aria-label)') + ' | ícone: ' + (i ? i.textContent.trim() : '-'); })"""


class GoogleFlowError(Exception):
    """Falha ao gerar imagens no Google Flow."""


class GoogleFlowLoginRequired(GoogleFlowError):
    """O Flow pediu login e não dá pra fazer agora (navegador oculto, ou o
    tempo de espera acabou)."""


class GoogleFlowLimitReached(GoogleFlowError):
    """O Flow avisou que o limite/créditos da conta atual acabou."""


class GoogleFlowSemContas(GoogleFlowError):
    """Todas as contas configuradas estão com o limite esgotado."""


# Um navegador/geração por vez (perfil do Chrome exclusivo + playwright
# síncrono preso à thread que o criou).
_FLOW_LOCK = threading.Lock()
_JSON_LOCK = threading.Lock()


# ------------------------------ pastas ------------------------------
def pasta_dados() -> Path:
    env = os.environ.get("GOOGLEFLOW_DATA_DIR")
    if env:
        return Path(env)
    # toolkit/googleflow/googleflow_client.py -> raiz do projeto
    return Path(__file__).resolve().parent.parent.parent / "flow_dados"


def pasta_imagens() -> Path:
    return pasta_dados() / "imagens"


def pasta_perfis() -> Path:
    return pasta_dados() / "perfis_navegador"


def arquivo_json() -> Path:
    return pasta_imagens() / "imagens.json"


def _slug(nome: str) -> str:
    return re.sub(r"[^\w.@+-]", "_", nome)


def arquivo_sessao(conta: str = CONTA_PADRAO) -> Path:
    if conta == CONTA_PADRAO:
        return pasta_perfis() / "sessao.json"
    return pasta_perfis() / f"sessao--{_slug(conta)}.json"


def perfil_da_conta(navegador: str, conta: str = CONTA_PADRAO) -> str:
    """Pasta do perfil do navegador dessa conta. A conta principal mantém o
    caminho de sempre (`<navegador>`), então quem já fez login não perde nada."""
    if conta == CONTA_PADRAO:
        return str(pasta_perfis() / navegador)
    return str(pasta_perfis() / f"{navegador}--{_slug(conta)}")


def arquivo_contas() -> Path:
    return pasta_dados() / "contas.json"


# ----------------------------- navegador -----------------------------
def _args_chromium(headless: bool) -> Dict[str, Any]:
    args: Dict[str, Any] = dict(
        headless=headless,
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )
    if headless:
        # sem janela não existe "tamanho da janela" — sem um viewport
        # explícito a página abre minúscula e o layout do Flow quebra.
        args["viewport"] = {"width": 1366, "height": 900}
    else:
        args["no_viewport"] = True
        # janela grande: estreita (< ~1200px) o Flow esconde o chip "Agente" e outros botões da caixa
        args["args"] = args["args"] + ["--window-size=1400,950"]
    return args


def abrir_navegador(p, nome: str, exe: Optional[str] = None, headless: bool = False, conta: str = CONTA_PADRAO):
    """Devolve (context, fechar_no_final). Suporta qualquer navegador.
    No modo "cdp" (Chrome do próprio usuário já aberto) `headless` não
    tem efeito: a janela é a dele."""
    if exe:
        nome = "custom"

    if nome == "cdp":
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            raise GoogleFlowError(
                "Não consegui conectar ao Chrome. Abra-o com "
                "--remote-debugging-port=9222 --user-data-dir=<pasta>."
            )
        return browser.contexts[0], False

    perfil = perfil_da_conta(nome, conta)

    if nome == "custom":
        ctx = p.chromium.launch_persistent_context(perfil, executable_path=exe, **_args_chromium(headless))
    elif nome == "chrome":
        ctx = p.chromium.launch_persistent_context(perfil, channel="chrome", **_args_chromium(headless))
    elif nome in ("edge", "msedge"):
        ctx = p.chromium.launch_persistent_context(perfil, channel="msedge", **_args_chromium(headless))
    elif nome == "chromium":
        ctx = p.chromium.launch_persistent_context(perfil, **_args_chromium(headless))
    elif nome == "firefox":
        extra = {"viewport": {"width": 1366, "height": 900}} if headless else {}
        ctx = p.firefox.launch_persistent_context(perfil, headless=headless, **extra)
    elif nome == "webkit":
        extra = {"viewport": {"width": 1366, "height": 900}} if headless else {}
        ctx = p.webkit.launch_persistent_context(perfil, headless=headless, **extra)
    else:
        raise GoogleFlowError(f"Navegador desconhecido: {nome}")

    return ctx, True


def abrir_navegador_auto(p, headless: bool = False, conta: str = CONTA_PADRAO):
    erros = []
    for nome in ORDEM_AUTO:
        try:
            return abrir_navegador(p, nome, headless=headless, conta=conta)
        except Exception as e:  # noqa: BLE001
            erros.append(f"{nome}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
    raise GoogleFlowError(
        "Nenhum navegador pôde ser aberto:\n  " + "\n  ".join(erros)
        + "\nInstale um com: playwright install chromium"
    )


def _abrir(p, cfg: Dict[str, Any], headless: bool, conta: str = CONTA_PADRAO):
    nome = (cfg.get("flow_navegador") or "auto").strip().lower()
    exe = (cfg.get("flow_exe") or "").strip() or None
    if nome == "auto" and not exe:
        return abrir_navegador_auto(p, headless=headless, conta=conta)
    return abrir_navegador(p, nome, exe, headless=headless, conta=conta)


# ------------------------------ sessão ------------------------------
def salvar_sessao(context, conta: str = CONTA_PADRAO) -> None:
    """Salva cookies + localStorage num arquivo (backup do login)."""
    try:
        pasta_perfis().mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(arquivo_sessao(conta)))
    except Exception:  # noqa: BLE001 - backup é só um extra
        pass


def restaurar_sessao(context, conta: str = CONTA_PADRAO) -> None:
    """Recarrega os cookies salvos, útil se o perfil perdeu cookies de sessão."""
    if not arquivo_sessao(conta).exists():
        return
    try:
        estado = json.loads(arquivo_sessao(conta).read_text(encoding="utf-8"))
        cookies = estado.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------- senhas --------------------------------
SERVICO_KEYRING = "narration_video_site_googleflow"


def keyring_disponivel() -> bool:
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def salvar_senha(conta: str, senha: str) -> None:
    """Guarda a senha no cofre de credenciais do sistema operacional (NUNCA em
    arquivo do projeto). Precisa do pacote `keyring` instalado."""
    try:
        import keyring
    except ImportError:
        raise GoogleFlowError(
            'Guardar a senha requer o pacote "keyring" (pip install keyring) -- sem ele, a senha '
            "não pode ser salva com segurança. Você ainda pode fazer o login automático sem salvar."
        )
    try:
        keyring.set_password(SERVICO_KEYRING, conta, senha)
    except Exception as exc:  # noqa: BLE001
        raise GoogleFlowError(f"Não consegui guardar a senha no cofre de credenciais do sistema: {exc}") from exc


def obter_senha(conta: str) -> Optional[str]:
    try:
        import keyring
        return keyring.get_password(SERVICO_KEYRING, conta)
    except Exception:  # noqa: BLE001
        return None


def remover_senha(conta: str) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICO_KEYRING, conta)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------- contas -------------------------------
_CONTAS_LOCK = threading.Lock()
_NOME_CONTA = re.compile(r"^[\w.@+-]{1,60}$")


def texto_indica_limite(texto: str, extras: str = "") -> bool:
    """A resposta do Flow (sem imagem) fala de limite/créditos esgotados?"""
    t = (texto or "").lower()
    palavras = list(PALAVRAS_LIMITE) + [x.strip().lower() for x in re.split(r"[,;\n]", extras or "") if x.strip()]
    return any(x in t for x in palavras)


def _ler_contas() -> Dict[str, Any]:
    """Formato em disco: {"contas": [{"nome": ..., "email": ...}, ...], "esgotadas": {...}}.
    A principal (`CONTA_PADRAO`) é sempre a 1ª entrada de `contas` -- inserida
    automaticamente se o arquivo ainda não tiver ela (conta antiga, criada
    antes dela poder ter e-mail). Lê também o formato antigo (lista de
    strings, sem e-mail) sem quebrar."""
    try:
        d = json.loads(arquivo_contas().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    contas = []
    for c in d.get("contas", []):
        if isinstance(c, str):
            contas.append({"nome": c, "email": ""})
        elif isinstance(c, dict) and isinstance(c.get("nome"), str):
            contas.append({"nome": c["nome"], "email": c.get("email") or ""})
    if not contas or contas[0]["nome"] != CONTA_PADRAO:
        contas = [c for c in contas if c["nome"] != CONTA_PADRAO]
        contas.insert(0, {"nome": CONTA_PADRAO, "email": ""})
    return {
        "contas": contas,
        "esgotadas": dict(d.get("esgotadas", {})) if isinstance(d.get("esgotadas"), dict) else {},
        # v84_105: limite SÓ de vídeo ou SÓ de imagem ({nome: {"video": iso, "imagem": iso}}) — a conta sem crédito pra
        # vídeo continua gerando imagem; quando as duas acabam, ela fica esgotada de vez até liberar
        "esgotadas_tipo": {k: dict(v) for k, v in (d.get("esgotadas_tipo") or {}).items() if isinstance(v, dict)}
                          if isinstance(d.get("esgotadas_tipo"), dict) else {},
    }


def _gravar_contas(d: Dict[str, Any]) -> None:
    pasta_dados().mkdir(parents=True, exist_ok=True)
    arquivo_contas().write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def nomes_das_contas() -> List[str]:
    return [c["nome"] for c in _ler_contas()["contas"]]


def adicionar_conta(nome: str, email: str = "") -> None:
    """Cadastra uma conta: `nome` é só um RÓTULO pra você reconhecer (ex: o
    e-mail), `email` é opcional e só é usado pelo LOGIN AUTOMÁTICO (preenchido
    sozinho no formulário do Google) -- sem ele, essa conta só pode logar pelo
    login manual (você digita na janela). Nenhuma senha é guardada aqui."""
    nome = (nome or "").strip()
    if not _NOME_CONTA.match(nome):
        raise GoogleFlowError("Nome de conta inválido: use de 1 a 60 letras, números, ponto, @, + ou hífen (sem espaços).")
    email = (email or "").strip()
    if email and "@" not in email:
        raise GoogleFlowError("E-mail inválido.")
    with _CONTAS_LOCK:
        d = _ler_contas()
        if nome.lower() in [c["nome"].lower() for c in d["contas"]]:
            raise GoogleFlowError(f"Já existe uma conta chamada '{nome}'.")
        d["contas"].append({"nome": nome, "email": email})
        _gravar_contas(d)


def definir_email(nome: str, email: str) -> None:
    """Define/atualiza o e-mail (pro login automático e pra exportar/importar)
    de uma conta já cadastrada -- inclusive a principal."""
    email = (email or "").strip()
    if email and "@" not in email:
        raise GoogleFlowError("E-mail inválido.")
    with _CONTAS_LOCK:
        d = _ler_contas()
        for c in d["contas"]:
            if c["nome"] == nome:
                c["email"] = email
                _gravar_contas(d)
                return
        raise GoogleFlowError(f"Conta '{nome}' não encontrada.")


def remover_conta(nome: str) -> None:
    """Tira a conta da lista e esquece a senha salva dela, se houver (o perfil
    do navegador continua no disco -- ver `perfil_da_conta`)."""
    if nome == CONTA_PADRAO:
        raise GoogleFlowError("A conta principal não pode ser removida.")
    with _CONTAS_LOCK:
        d = _ler_contas()
        nomes = [c["nome"] for c in d["contas"]]
        if nome not in nomes:
            raise GoogleFlowError(f"Conta '{nome}' não encontrada.")
        d["contas"] = [c for c in d["contas"] if c["nome"] != nome]
        d["esgotadas"].pop(nome, None)
        d["esgotadas_tipo"].pop(nome, None)
        _gravar_contas(d)
    remover_senha(nome)


TIPOS_LIMITE = ("video", "imagem")


def tipo_do_limite(tipo: Any) -> Optional[str]:
    """"video"/"animar" → "video"; "imagem"/"foto" → "imagem"; o resto (lote misto, desconhecido) → None (= a conta toda)."""
    t = str(tipo or "").lower()
    if t in ("video", "vídeo", "animar"):
        return "video"
    if t in ("imagem", "foto", "image"):
        return "imagem"
    return None


def marcar_esgotada(nome: str, horas: float = 24, agora: Optional[datetime] = None, tipo: Optional[str] = None) -> None:
    """Conta sem crédito/limite por `horas`. `tipo` "video" ou "imagem": só aquele tipo (a conta continua servindo pro
    outro); None: a conta toda."""
    if nome not in nomes_das_contas():
        raise GoogleFlowError(f"Conta '{nome}' não encontrada.")
    ate = ((agora or datetime.now()) + timedelta(hours=horas)).isoformat(timespec="seconds")
    tipo = tipo_do_limite(tipo)
    with _CONTAS_LOCK:
        d = _ler_contas()
        if tipo:
            d["esgotadas_tipo"].setdefault(nome, {})[tipo] = ate
        else:
            d["esgotadas"][nome] = ate
        _gravar_contas(d)


def liberar_conta(nome: str, tipo: Optional[str] = None) -> None:
    tipo = tipo_do_limite(tipo)
    despular_conta(nome)  # ♻ liberar = volta a tentar a conta também se ela tinha sido pulada
    with _CONTAS_LOCK:
        d = _ler_contas()
        if tipo:
            (d["esgotadas_tipo"].get(nome) or {}).pop(tipo, None)
        else:
            d["esgotadas"].pop(nome, None)
            d["esgotadas_tipo"].pop(nome, None)
        _gravar_contas(d)


# ⏭ v84_110: conta PULADA (pediu login de novo, sessão caiu, não abriu o navegador…) — fica fora da troca de contas até
# fazer o login (🔑 Contas Google / 🌐 Abrir navegador), clicar em ♻ liberar, ou passar PULAR_MINUTOS. Só na memória:
# reiniciar o site tenta a conta de novo.
PULAR_MINUTOS = 60
_PULADAS: Dict[str, Dict[str, Any]] = {}
_PULADAS_LOCK = threading.Lock()
RE_PROBLEMA_DE_LOGIN = re.compile(r"login|log in|sign[ -]?in|fa[çc]a o login|fazer login|entrar na conta|sess[ãa]o (?:caiu|expirou)|"
                                  r"verifi(?:que|car) (?:sua|a) (?:identidade|conta)|captcha|unusual|incomum|"
                                  r"conta (?:desativada|suspensa|bloqueada)|account (?:disabled|suspended)|accounts\.google\.com", re.I)


def _chave_pulada(nome: str) -> str:
    return f"{pasta_dados()}::{nome}"  # por pasta de dados (cada instalação/teste tem as suas)


def pular_conta(nome: str, motivo: str, minutos: Optional[float] = None, agora: Optional[datetime] = None) -> None:
    agora = agora or datetime.now()
    ate = agora + timedelta(minutes=PULAR_MINUTOS if minutos is None else minutos)
    with _PULADAS_LOCK:
        _PULADAS[_chave_pulada(nome)] = {"motivo": str(motivo or "problema na conta")[:240], "ate": ate.isoformat(timespec="seconds")}


def despular_conta(nome: Optional[str] = None) -> None:
    """Volta a usar a conta (None = todas)."""
    with _PULADAS_LOCK:
        if nome is None:
            for k in [k for k in _PULADAS if k.startswith(f"{pasta_dados()}::")]:
                _PULADAS.pop(k, None)
        else:
            _PULADAS.pop(_chave_pulada(nome), None)


def conta_pulada(nome: str, agora: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    agora = agora or datetime.now()
    with _PULADAS_LOCK:
        info = _PULADAS.get(_chave_pulada(nome))
        if info and not _ativo(info["ate"], agora):
            _PULADAS.pop(_chave_pulada(nome), None)
            return None
        return dict(info) if info else None


def _ativo(ate: Optional[str], agora: datetime) -> bool:
    try:
        return bool(ate) and datetime.fromisoformat(ate) > agora
    except ValueError:
        return False


def listar_contas(agora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """[{nome, esgotada, esgotada_ate, esgotada_video, video_ate, esgotada_imagem, imagem_ate, logada, email,
    tem_senha_salva}] — a principal sempre primeiro. "esgotada" = a conta TODA (marcada assim, ou vídeo E imagem
    esgotados). "logada" = já existe backup de sessão dessa conta (foi usada/logada antes)."""
    agora = agora or datetime.now()
    d = _ler_contas()
    saida = []
    for c in d["contas"]:
        nome = c["nome"]
        ate = d["esgotadas"].get(nome)
        toda = _ativo(ate, agora)
        por = d["esgotadas_tipo"].get(nome) or {}
        vid, img = _ativo(por.get("video"), agora), _ativo(por.get("imagem"), agora)
        esgotada = toda or (vid and img)
        if not toda and esgotada:
            ate = min(por["video"], por["imagem"])
        saida.append({
            "nome": nome, "esgotada": esgotada, "esgotada_ate": ate if esgotada else None,
            "esgotada_video": toda or vid, "video_ate": (ate if toda else por.get("video")) if (toda or vid) else None,
            "esgotada_imagem": toda or img, "imagem_ate": (ate if toda else por.get("imagem")) if (toda or img) else None,
            "logada": arquivo_sessao(nome).exists(), "email": c["email"],
            "tem_senha_salva": obter_senha(nome) is not None,
            "pulada": (conta_pulada(nome, agora) or {}).get("motivo"), "pulada_ate": (conta_pulada(nome, agora) or {}).get("ate"),
        })
    return saida


def conta_serve(nome: str, tipo: Optional[str] = None, agora: Optional[datetime] = None) -> bool:
    c = next((x for x in listar_contas(agora) if x["nome"] == nome), None)
    tipo = tipo_do_limite(tipo)
    return bool(c) and not c["esgotada"] and not (tipo and c["esgotada_" + tipo]) and not c.get("pulada")


def escolher_conta_disponivel(agora: Optional[datetime] = None, tipo: Optional[str] = None) -> str:
    """A 1ª conta (na ordem da lista) que serve pra `tipo` ("video"/"imagem"; None = qualquer), preferindo as que já
    têm login. Se nenhuma serve, levanta `GoogleFlowSemContas`."""
    contas = listar_contas(agora)
    tipo = tipo_do_limite(tipo)
    livres = [c for c in contas if not c["esgotada"] and not (tipo and c["esgotada_" + tipo]) and not c.get("pulada")]
    puladas = [c for c in contas if c.get("pulada") and not c["esgotada"] and not (tipo and c["esgotada_" + tipo])]
    if not livres and puladas:
        raise GoogleFlowSemContas(
            "Nenhuma conta do Google Flow disponível: " + "; ".join(f"'{c['nome']}' foi pulada ({c['pulada']})" for c in puladas)
            + ". Faça o login dela em 🔑 Contas Google (ou 🌐 Abrir navegador no 🚀 Em massa) e tente de novo.")
    if not livres:
        def _quando(c):
            return c["esgotada_ate"] or (c.get(f"{tipo}_ate") if tipo else None) or "?"
        detalhe = "; ".join(f"'{c['nome']}' volta em {_quando(c)}" for c in contas)
        raise GoogleFlowSemContas(
            f"Todas as contas do Google Flow atingiram o limite{' de ' + ('vídeo' if tipo == 'video' else 'imagem') if tipo else ''} "
            f"({detalhe}). Adicione outra conta em 🔑 Contas Google, ou libere uma manualmente se o limite já renovou."
        )
    return ([c for c in livres if c["logada"]] or livres)[0]["nome"]


# -------------------------------- json -------------------------------
def carregar_json() -> List[Dict[str, Any]]:
    with _JSON_LOCK:
        if arquivo_json().exists():
            try:
                dados = json.loads(arquivo_json().read_text(encoding="utf-8"))
                if isinstance(dados, list):
                    return dados
            except (json.JSONDecodeError, OSError):
                pass
    return []


def _salvar_json(dados: List[Dict[str, Any]]) -> None:
    with _JSON_LOCK:
        pasta_imagens().mkdir(parents=True, exist_ok=True)
        arquivo_json().write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------- ações no Flow ---------------------------
def _passar_pela_pagina_inicial(page) -> None:
    """Algumas contas caem na página de apresentação do Flow em vez de ir
    direto pro app (confirmado pelo usuário via HTML real). Se aparecer o
    botão "Crie com o Google Flow", clica nele e espera a aba recarregar. Se
    não aparecer (a maioria das vezes, contas que já usaram o Flow antes),
    não faz nada -- nunca levanta erro."""
    botao = page.locator(SEL_BOTAO_CRIAR_COM_FLOW).first
    try:
        botao.wait_for(state="visible", timeout=5_000)
    except PWTimeout:
        return
    botao.click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except PWTimeout:
        pass


def abrir_novo_projeto(context, headless: bool = False):
    """Abre o Flow, clica em 'New project' e devolve a página do projeto
    (pode ser uma nova aba ou a mesma)."""
    page = context.new_page()
    page.goto(FLOW_URL, wait_until="domcontentloaded")
    _passar_pela_pagina_inicial(page)

    botao = page.locator(SEL_NOVO_PROJETO).first
    try:
        botao.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        if headless:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
            raise GoogleFlowLoginRequired(
                "O Google Flow pediu login, e com o navegador OCULTO não dá pra fazer login. "
                "Abra Configurações → Google Flow → \"Fazer login no Flow\" (abre uma janela "
                "visível, uma vez só), ou desmarque \"Ocultar o navegador\" e gere de novo."
            )
        try:
            botao.wait_for(state="visible", timeout=TIMEOUT_LOGIN_S * 1000)
        except PWTimeout:
            raise GoogleFlowLoginRequired(
                f"Tempo esgotado ({TIMEOUT_LOGIN_S}s) esperando o login no Google Flow."
            )

    # 1ª vez que ESSA conta usa o Flow: passa pelas caixas de boas-vindas antes
    # de clicar em "Novo projeto" (senão o clique é bloqueado pela caixa por cima).
    _dispensar_dialogos_de_boas_vindas(page)

    paginas_antes = set(context.pages)
    botao.click()

    time.sleep(PAUSA_APOS_NOVO_PROJETO_S)
    novas = [p for p in context.pages if p not in paginas_antes]
    if novas:
        try:
            page.close()  # a aba inicial não serve mais: o projeto abriu em outra
        except Exception:  # noqa: BLE001
            pass
        page = novas[-1]
    page.wait_for_load_state("domcontentloaded")
    page.bring_to_front()
    _dispensar_changelog(page)
    return page


def _preencher_login_google(page, email: str, senha: str) -> None:
    """Vai pra página de login do Google e preenche e-mail/senha (fluxo
    confirmado pelo usuário). Levanta PWTimeout se algum campo/botão não
    aparecer -- quem chama trata isso como "não consegui logar
    automaticamente" (login pede verificação extra, senha errada, ou o
    Google mudou essa página)."""
    page.goto(GOOGLE_LOGIN_URL, wait_until="domcontentloaded")
    page.locator(SEL_GOOGLE_EMAIL).first.wait_for(state="visible", timeout=20_000)
    page.locator(SEL_GOOGLE_EMAIL).first.fill(email)
    page.locator(SEL_GOOGLE_EMAIL_PROXIMO).first.click()
    page.locator(SEL_GOOGLE_SENHA).first.wait_for(state="visible", timeout=20_000)
    page.locator(SEL_GOOGLE_SENHA).first.fill(senha)
    page.locator(SEL_GOOGLE_SENHA_PROXIMO).first.click()
    page.goto(FLOW_URL_POS_LOGIN, wait_until="domcontentloaded")
    _passar_pela_pagina_inicial(page)


def _dispensar_dialogos_de_boas_vindas(page) -> None:
    """Passa pelas caixas de boas-vindas que o Flow mostra na 1ª vez que uma
    conta é usada nele (ver `SEL_DIALOGO_*`) -- se não aparecerem (conta que já
    passou por isso antes), não faz nada. As duas usam o MESMO seletor (a 2ª
    substitui a 1ª no lugar, não fica "escondida" depois do clique) -- por
    isso o critério de parar é a próxima verificação de "visível" não achar
    mais nada, não esperar a caixa sumir. Nunca levanta erro: se um passo
    falhar, tenta seguir em frente mesmo assim (o próximo `wait_for` do "Novo
    projeto" é quem decide se deu certo)."""
    for _ in range(2):  # no máximo 2 diálogos em sequência
        dialogo = page.locator(SEL_DIALOGO_BOASVINDAS).first
        try:
            dialogo.wait_for(state="visible", timeout=3_000)
        except PWTimeout:
            return
        try:
            page.locator(SEL_DIALOGO_FIM_DO_TEXTO).first.scroll_into_view_if_needed(timeout=3_000)
        except Exception:  # noqa: BLE001 -- esse diálogo pode não ter nada pra rolar
            pass
        try:
            page.wait_for_function(
                """sel => { const b = document.querySelector(sel); return b && !b.disabled; }""",
                arg=SEL_DIALOGO_BOTAO_PRIMARIO, timeout=5_000,
            )
        except PWTimeout:
            pass
        try:
            page.locator(SEL_DIALOGO_BOTAO_PRIMARIO).first.click()
        except Exception:  # noqa: BLE001
            return


def _dispensar_changelog(page) -> None:
    """Depois de clicar em "Novo projeto", o Flow às vezes mostra um aviso de
    novidades da versão (confirmado pelo usuário via HTML real) -- clica em
    "Começar" pra tirar do caminho. Se não aparecer, não faz nada. Nunca
    levanta erro (o próximo passo é quem decide se deu certo)."""
    try:
        page.locator(SEL_CHANGELOG_MODAL).first.wait_for(state="visible", timeout=4_000)
    except PWTimeout:
        return
    try:
        page.locator(SEL_CHANGELOG_BOTAO_PRIMARIO).first.click()
    except Exception:  # noqa: BLE001
        pass


def _confirmar(condicao, timeout_s: float = 3.0) -> bool:
    """A interface (Angular) atualiza o estado um instante depois do clique."""
    fim = time.monotonic() + timeout_s
    while True:
        if condicao():
            return True
        if time.monotonic() >= fim:
            return False
        time.sleep(0.1)


def _abrir_painel_configuracoes(page, seletor_extra: str = "") -> None:
    """Clica no botão de configurações do agente e confirma que o painel abriu.
    Tenta o seletor configurado pelo usuário primeiro, depois os candidatos
    conhecidos; um candidato que não abre o painel certo é descartado."""
    candidatos = ([seletor_extra.strip()] if seletor_extra and seletor_extra.strip() else []) + SEL_BOTAO_CONFIGURACOES
    for sel in candidatos:
        botao = page.locator(sel).first
        try:
            botao.wait_for(state="visible", timeout=2_500)
        except PWTimeout:
            continue  # esse candidato nem existe na tela
        try:
            botao.click()
            page.locator(SEL_PAINEL_ROTULO).first.wait_for(state="visible", timeout=5_000)
            return
        except PWTimeout:
            try:
                page.keyboard.press("Escape")  # clicou, mas abriu outra coisa: fecha e tenta o próximo
            except Exception:  # noqa: BLE001
                pass
    try:
        botoes = page.evaluate(JS_BOTOES)
    except Exception:  # noqa: BLE001
        botoes = []
    raise GoogleFlowError(
        "Não consegui abrir o painel de configurações do Flow (não achei o botão certo). "
        "Botões visíveis na tela: " + ("; ".join(botoes) if botoes else "(não consegui listar)") + ". "
        "Informe o seletor CSS do botão em Configurações → Google Flow → \"Seletor do botão de "
        "configurações\", ou desmarque \"Configurar o projeto antes de gerar\" se já configurou o Flow à mão."
    )


def _sel_item_menu_modelo(modelo: str) -> str:
    """Seletor do item do menu de modelo (imagem ou vídeo) com esse nome
    exato (ex: "Veo 3.1 - Lite", confirmado pelo usuário via HTML real). Usa
    o texto visível -- não há um id/valor estável por trás de cada opção."""
    modelo = modelo.replace('"', '\\"')
    return f'flow-menu-item:has-text("{modelo}") button'


def _primeiro_visivel(raiz, seletor: str, timeout_s: float = 0.0):
    """O 1º elemento VISÍVEL que casa com `seletor` (o Flow deixa cópias escondidas
    da caixa de comando/painéis na página — pegar `.first` pegava a escondida)."""
    fim = time.monotonic() + timeout_s
    while True:
        loc = raiz.locator(seletor)
        try:
            for k in range(loc.count()):
                el = loc.nth(k)
                if el.is_visible():
                    return el
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() >= fim:
            return None
        time.sleep(0.3)


def caixa_visivel(page, timeout_s: float = 20.0):
    """A caixa de comando que está NA TELA (a que tem o botão de configurações visível)."""
    fim = time.monotonic() + timeout_s
    while True:
        caixas = page.locator(SEL_CAIXA_PROMPT)
        try:
            achou = None
            for k in range(caixas.count()):
                c = caixas.nth(k)
                if not c.is_visible():
                    continue
                if _primeiro_visivel(c, SEL_GATILHO_CONFIG_CAIXA) is not None:
                    return c
                achou = achou or c
            if achou is not None and time.monotonic() >= fim - timeout_s / 2:
                return achou
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() >= fim:
            raise GoogleFlowError("Não achei a caixa de comando do Flow na tela (onde se digita o pedido).")
        time.sleep(0.4)


def _clicar_toggle(page, seletor_botoes: str, texto: str) -> bool:
    """Clica no botão de um grupo de toggles (proporção, quantidade, duração...)
    cujo texto visível é exatamente `texto` ("9:16", "x1", "4s", "720p") e
    confere que ficou marcado. Best-effort: devolve False se não achou."""
    if not texto:
        return False
    alvo = _primeiro_visivel(page, f'{seletor_botoes}:has(.toggle-text:text-is("{texto}"))', timeout_s=3.0)
    if alvo is None:
        return False
    try:
        alvo.click(timeout=5_000)
    except Exception:  # noqa: BLE001
        return False
    return _confirmar(lambda: alvo.get_attribute("aria-checked") == "true")


def _escolher_no_menu(page, botao_sel: str, modelo: str) -> bool:
    """Abre o menu de modelo (botão `botao_sel`) e escolhe `modelo` pelo texto."""
    if not modelo:
        return False
    try:
        botao = _primeiro_visivel(page, botao_sel, timeout_s=3.0) or page.locator(botao_sel).first
        botao.click(timeout=5_000)
        item = _primeiro_visivel(page, _sel_item_menu_modelo(modelo), timeout_s=5.0) or page.locator(_sel_item_menu_modelo(modelo)).first
        item.wait_for(state="visible", timeout=5_000)
        item.click(timeout=5_000)
        return True
    except Exception:  # noqa: BLE001 -- preferência, não trava
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        return False


def proporcao_flow(proporcao: str) -> str:
    """"9x16" / "9:16" / "9:16" -> "9:16" (o texto dos toggles do Flow)."""
    p = str(proporcao or "").replace("x", ":").replace(" ", "")
    return p if p in ("16:9", "4:3", "1:1", "3:4", "9:16") else ""


def configurar_projeto(page, seletor_extra: str = "", modelo_video: str = "", modelo_imagem: str = "",
                       proporcao_imagem: str = "", proporcao_video: str = "") -> None:
    """Depois de criar o projeto: abre as configurações do agente, escolhe
    'Confirmar antes de gerar' = Nunca (senão o agente para pedindo
    confirmação a cada imagem), quantidade de imagens = x1, quantidade de
    vídeos = x1, o modelo de vídeo padrão (se `modelo_video` foi passado —
    ex: "Veo 3.1 - Lite"), e salva. Confere Nunca/x1 de imagem/x1 de vídeo —
    um desses passos falhando em silêncio deixaria as gerações seguintes
    travadas até o timeout. A escolha do MODELO de vídeo é best-effort (não
    trava a configuração inteira se o menu não abrir do jeito esperado):
    errar o modelo gera algo mesmo assim, só não é o modelo preferido."""
    _abrir_painel_configuracoes(page, seletor_extra)
    try:
        page.locator(SEL_CONFIRMAR_NUNCA).first.click(timeout=10_000)
        if not _confirmar(lambda: page.locator(SEL_CONFIRMAR_NUNCA_INPUT).first.is_checked()):
            raise GoogleFlowError('Não consegui marcar "Confirmar antes de gerar: Nunca" nas configurações do Flow.')

        x1 = page.locator(SEL_IMAGENS_X1).first
        x1.click(timeout=10_000)
        if not _confirmar(lambda: x1.get_attribute("aria-checked") == "true"):
            raise GoogleFlowError('Não consegui marcar a quantidade de imagens "x1" nas configurações do Flow.')

        x1_video = page.locator(SEL_VIDEO_X1).first
        x1_video.click(timeout=10_000)
        if not _confirmar(lambda: x1_video.get_attribute("aria-checked") == "true"):
            raise GoogleFlowError('Não consegui marcar a quantidade de vídeos "x1" nas configurações do Flow.')

        # preferências (best-effort): proporção e modelo padrão de imagem e de vídeo
        _clicar_toggle(page, SEL_IMAGEM_PROPORCAO, proporcao_flow(proporcao_imagem))
        _escolher_no_menu(page, SEL_IMAGEM_MODELO_BOTAO, modelo_imagem)
        if proporcao_flow(proporcao_video) in ("16:9", "9:16"):
            _clicar_toggle(page, SEL_VIDEO_PROPORCAO, proporcao_flow(proporcao_video))
        _escolher_no_menu(page, SEL_VIDEO_MODELO_BOTAO, modelo_video)

        try:
            # o botão VISÍVEL (o Flow pode ter cópias escondidas); sem ele, o seletor de sempre
            (_primeiro_visivel(page, SEL_SALVAR_CONFIG) or page.locator(SEL_SALVAR_CONFIG).first).click(timeout=10_000)
        except PWTimeout:
            # o botão mudou de classe: procura "Salvar"/"Save"/"Aplicar"... visível no painel
            if not salvar_painel(page, _primeiro_visivel(page, SEL_PAINEL), timeout_s=10.0):
                raise
        # confere que FECHOU (o visível — não o 1º da página); se não, Salvar de novo / X / Esc
        if not _confirmar(lambda: _primeiro_visivel(page, SEL_PAINEL_ROTULO) is None, timeout_s=6.0):
            fechar_config_agente(page)
        if _primeiro_visivel(page, SEL_PAINEL_ROTULO) is not None:
            raise GoogleFlowError('Cliquei em "Salvar" nas configurações do agente, mas o painel continuou aberto.')
        page.locator(SEL_PAINEL).first.wait_for(state="hidden", timeout=15_000)
    except PWTimeout as exc:
        raise GoogleFlowError(
            "Tempo esgotado configurando o projeto no Flow (o painel de configurações mudou?). "
            "Desmarque \"Configurar o projeto antes de gerar\" em Configurações se já configurou o Flow à mão."
        ) from exc


def gerar_videos(page, prompt: str, timeout_geracao_s: int = TIMEOUT_VIDEO_MIN_S,
                 ignorar=frozenset(), palavras_limite: str = "", seletor: str = "") -> List[str]:
    """Como `gerar_imagens`, mas espera um VÍDEO (Veo) na conversa e devolve
    as URLs (http ou blob:) dos vídeos novos."""
    return gerar_imagens(page, prompt, max(int(timeout_geracao_s or 0), TIMEOUT_VIDEO_MIN_S), ignorar, palavras_limite,
                         _video=True, _seletor=seletor or SEL_VIDEO)


def gerar_imagens(page, prompt: str, timeout_geracao_s: int = TIMEOUT_GERACAO_S,
                  ignorar=frozenset(), palavras_limite: str = "", _video: bool = False, _seletor: str = "") -> List[str]:
    """Escreve o prompt NA CONVERSA ATUAL, envia, espera a geração e devolve as
    URLs das imagens NOVAS. Como a conversa é reaproveitada, só olha as
    mensagens que surgiram depois do envio (`antes`) e descarta URLs já vistas —
    uma geração recusada/sem imagem nunca pode devolver a imagem do pedido anterior."""
    editor = page.locator(SEL_EDITOR_PROMPT).first
    editor.wait_for(state="visible", timeout=60_000)

    antes = page.locator(SEL_MENSAGEM).count()
    antes_usuario = page.locator(SEL_MSG_USUARIO).count()

    editor.click()
    page.keyboard.type(prompt, delay=20)

    botao = page.locator(SEL_BOTAO_ENVIAR).first
    try:
        page.wait_for_function(
            """sel => {
                const b = document.querySelector(sel);
                return b && !b.disabled;
            }""",
            arg=SEL_BOTAO_ENVIAR,
            timeout=15_000,
        )
    except PWTimeout:
        # botão de enviar travado: o Flow costuma fazer isso (e/ou mostrar um aviso) quando o limite acaba
        avisos = _avisos(page)
        if texto_indica_limite(avisos, palavras_limite):
            raise GoogleFlowLimitReached("Limite do Google Flow atingido: " + avisos)
        raise GoogleFlowError(
            "O botão de enviar do Flow continua desabilitado (limite atingido ou conversa travada?)."
            + (f" Aviso na tela: {avisos}" if avisos else "")
        )
    botao.click()

    # O Flow aceitou o pedido? Se sim, a mensagem do usuário aparece na conversa.
    if not _confirmar(lambda: page.locator(SEL_MSG_USUARIO).count() > antes_usuario, timeout_s=15.0):
        avisos = _avisos(page)
        if texto_indica_limite(avisos, palavras_limite):
            raise GoogleFlowLimitReached("Limite do Google Flow atingido: " + avisos)
        raise GoogleFlowError(
            "O Flow não aceitou o pedido (a sua mensagem não apareceu na conversa)."
            + (f" Aviso na tela: {avisos}" if avisos else "")
        )
    if _video:
        return esperar_geracao(page, antes, timeout_geracao_s, ignorar, palavras_limite,
                               script=JS_ESTADO_VIDEO, seletor=_seletor or SEL_VIDEO, graca_s=GRACA_SEM_VIDEO_S, oque="vídeo")
    return esperar_geracao(page, antes, timeout_geracao_s, ignorar, palavras_limite)


def _editor_da_caixa(page):
    """O editor (ProseMirror) da caixa de comando — com o Agente ligado ele fica
    no painel do agente; desligado, pode ser a caixa base."""
    for sel in SEL_EDITOR_CAIXA:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=4_000)
            return loc
        except PWTimeout:
            continue
    raise GoogleFlowError("Não achei a caixa de comando do Flow (onde se digita o pedido).")


def definir_modo_agente(page, ligado: bool) -> None:
    """Liga/desliga o chip "Agente" da caixa de comando (aria-pressed). A
    geração de IMAGENS do site usa o agente; animar com frame usa a caixa
    direta (agente desligado), como no passo a passo do usuário."""
    chip = _primeiro_visivel(page, SEL_CHIP_AGENTE, timeout_s=3.0)
    if chip is None:
        return  # sem o chip (layout do Flow sem modo Agente): a caixa já é a direta
    if (chip.get_attribute("aria-pressed") == "true") != ligado:
        chip.click()
        _confirmar(lambda: (chip.get_attribute("aria-pressed") == "true") == ligado, timeout_s=4.0)


def _anexar_imagem(page, caminho_imagem: str) -> None:
    """"+" da caixa -> manda a imagem (arquivo do computador; se o menu não tiver
    envio de arquivo, usa a imagem mais recente do projeto) -> espera a prévia
    carregar (spinner -> img.detail-preview-image) -> "Incluir no comando"."""
    page.locator(SEL_BOTAO_ADICIONAR).first.click(timeout=15_000)
    time.sleep(0.8)
    anexou = False
    entrada = page.locator('input[type="file"]')
    try:
        if entrada.count():
            entrada.first.set_input_files(caminho_imagem, timeout=10_000)
            anexou = True
    except Exception:  # noqa: BLE001
        anexou = False
    if not anexou:
        item = page.locator(SEL_ITEM_ENVIAR_ARQUIVO).first
        try:
            item.wait_for(state="visible", timeout=3_000)
            with page.expect_file_chooser(timeout=10_000) as escolha:
                item.click()
            escolha.value.set_files(caminho_imagem)
            anexou = True
        except Exception:  # noqa: BLE001
            anexou = False
    if not anexou:
        recente = page.locator(SEL_ITEM_IMAGEM_RECENTE).first
        try:
            recente.wait_for(state="visible", timeout=5_000)
            recente.click()
            anexou = True
        except Exception as exc:  # noqa: BLE001
            raise GoogleFlowError("Não consegui anexar a imagem inicial no Flow (o menu \"+\" mudou?).") from exc
    try:
        page.locator(SEL_PREVIA_CARREGADA).first.wait_for(state="visible", timeout=TIMEOUT_PREVIA_S * 1000)
    except PWTimeout as exc:
        raise GoogleFlowError("A prévia da imagem inicial não carregou no Flow (spinner não terminou).") from exc
    try:
        page.locator(SEL_INCLUIR_NO_COMANDO).first.click(timeout=15_000)
    except PWTimeout as exc:
        raise GoogleFlowError("Não achei o botão \"Incluir no comando\" depois de carregar a imagem.") from exc
    time.sleep(0.8)


def _configurar_caixa_video(page, modelo: str, resolucao: str, duracao: str, proporcao: str) -> None:
    """Abre o "Gatilho de configurações" da caixa (aparece com o Agente
    desligado) e escolhe Vídeo -> Frames -> modelo -> resolução -> duração ->
    x1 -> proporção. Os toggles que não existirem pro modelo são ignorados."""
    gatilho = page.locator(SEL_GATILHO_CONFIG_CAIXA).first
    try:
        gatilho.wait_for(state="visible", timeout=10_000)
        gatilho.click()
        page.locator(SEL_CONFIG_CAIXA).first.wait_for(state="visible", timeout=10_000)
    except PWTimeout as exc:
        raise GoogleFlowError("Não consegui abrir as configurações da caixa de comando do Flow "
                              "(o modo Agente desligou?).") from exc
    base = SEL_CONFIG_CAIXA + ' flow-toggles[aria-label="{}"] button.mat-button-toggle-button'
    if not _clicar_toggle(page, base.format("Modo"), "Vídeo"):
        raise GoogleFlowError('Não consegui escolher "Vídeo" nas configurações da caixa do Flow.')
    time.sleep(0.5)
    if not _clicar_toggle(page, base.format("Tipo de vídeo"), "Frames"):
        raise GoogleFlowError('Não consegui escolher "Frames" (vídeo a partir da imagem) no Flow.')
    time.sleep(0.5)
    if modelo:
        _escolher_no_menu(page, SEL_MODELO_CAIXA, modelo)
        time.sleep(0.8)  # trocar o modelo muda os toggles que aparecem
    _clicar_toggle(page, base.format("Proporção"), proporcao_flow(proporcao))
    _clicar_toggle(page, base.format("Resolução do vídeo"), resolucao)
    _clicar_toggle(page, base.format("Duração do vídeo"), duracao)
    _clicar_toggle(page, base.format("Quantidade de resultados"), "x1")
    try:
        page.keyboard.press("Escape")  # fecha o painel sem desfazer a escolha
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.4)


def animar_imagem(page, caminho_imagem: str, prompt: str, timeout_s: int = TIMEOUT_VIDEO_MIN_S,
                  modelo: str = "Omni 1.1 Flash", resolucao: str = "720p", duracao: str = "4s",
                  proporcao: str = "9:16", palavras_limite: str = "", ignorar=frozenset()) -> List[str]:
    """Gera um VÍDEO a partir de uma imagem inicial (frame) e devolve as URLs dos
    vídeos novos que aparecerem na página."""
    if not os.path.isfile(caminho_imagem):
        raise GoogleFlowError(f"Imagem inicial não encontrada: {caminho_imagem}")
    definir_modo_agente(page, True)   # o "+" funciona nos dois modos; o agente é desligado depois de anexar
    try:
        antes = set(page.evaluate(JS_VIDEOS_NA_PAGINA) or [])
    except Exception:  # noqa: BLE001
        antes = set()
    _anexar_imagem(page, caminho_imagem)
    definir_modo_agente(page, False)
    _configurar_caixa_video(page, modelo, resolucao, duracao, proporcao)
    editor = _editor_da_caixa(page)
    editor.click()
    page.keyboard.type(" ".join((prompt or "").split()), delay=15)
    try:
        page.wait_for_function(
            "sel => { const b = Array.from(document.querySelectorAll(sel)).find(x => x.offsetParent !== null);"
            " return b && !b.disabled; }", arg=SEL_BOTAO_GERAR, timeout=20_000)
    except PWTimeout:
        avisos = _avisos(page)
        if texto_indica_limite(avisos, palavras_limite):
            raise GoogleFlowLimitReached("Limite do Google Flow atingido: " + avisos)
        raise GoogleFlowError("O botão \"Iniciar geração\" continua desabilitado." + (f" Aviso: {avisos}" if avisos else ""))
    botoes = page.locator(SEL_BOTAO_GERAR)
    for k in range(botoes.count()):
        if botoes.nth(k).is_visible() and botoes.nth(k).is_enabled():
            botoes.nth(k).click()
            break
    fim = time.monotonic() + max(int(timeout_s or 0), 120)
    assinatura, estavel_desde = None, 0.0
    while True:
        try:
            atuais = [u for u in (page.evaluate(JS_VIDEOS_NA_PAGINA) or []) if u not in antes and u not in ignorar]
        except Exception:  # noqa: BLE001
            atuais = []
        agora = time.monotonic()
        if atuais:
            if tuple(atuais) != assinatura:
                assinatura, estavel_desde = tuple(atuais), agora
            elif agora - estavel_desde >= ESTAVEL_S:
                return list(atuais)
        else:
            avisos = _avisos(page)
            if avisos and texto_indica_limite(avisos, palavras_limite):
                raise GoogleFlowLimitReached("Limite do Google Flow atingido: " + avisos)
        if agora >= fim:
            raise GoogleFlowError("Tempo esgotado esperando o vídeo animado a partir da imagem no Flow."
                                  + (f" Aviso na tela: {_avisos(page)}" if _avisos(page) else ""))
        time.sleep(PAUSA_POLLING_S * 2)


# =============================================================== modo direto (sem Agente)
# BLINDADO contra mudanças pequenas no Flow: cada elemento tem VÁRIAS pistas
# (classe, aria-label, texto em português e inglês, ícone) e o código só usa o
# que está VISÍVEL. Cada passo confere se deu certo e tenta de novo; se um
# trabalho falha ANTES de clicar em gerar, o lote tenta de novo num projeto novo.
PISTAS = {
    "caixa": [".base-prompt-box", "flow-base-prompt-box", "flow-prompt-box", ".prompt-box-container"],
    # SÓ o botão da CAIXA (o que mostra "🍌 modelo · x1"). Nada de "qualquer botão com 'configura'":
    # isso achava o botão "Configurações do agente" e reabria aquele painel sem parar.
    # (só procurado DENTRO da caixa; as pistas soltas excluem qualquer botão "do agente")
    "gatilho": ["button.settings-trigger-button", 'button[aria-label="Gatilho de configurações"]',
                'button[aria-label="Settings trigger"]', "button:has(.settings-summary)",
                'button[aria-label*="onfigura"]:not([aria-label*="gente"]):not(.agent-footer-actions *)',
                'button[aria-label*="ettings"]:not([aria-label*="gent"]):not(.agent-footer-actions *)'],
    "painel": ["flow-prompt-box-settings",
               ".cdk-overlay-pane:has(flow-toggles):not(:has(.settings-content)):not(:has(#agent-settings-confirm-policy-label))",
               ".cdk-overlay-pane:has(.mat-button-toggle-group):not(:has(.settings-content))"],
    # painel lateral "Configurações do agente" (o do projeto): fecha com Salvar ou com o X
    "agente_painel": ["#agent-settings-confirm-policy-label", ".settings-content", ".confirm-policy-group"],
    "agente_salvar": ["button.settings-save-button", ".save-container button"],
    "agente_fechar": ['button[aria-label="Fechar"]', 'button[aria-label*="echar"]', 'button[aria-label*="Close"]',
                      'button:has(mat-icon:text-is("close"))'],
    "editor": [".ProseMirror", '[contenteditable="true"]', "textarea"],
    "gerar": ["button.generate-icon-button", 'button[aria-label="Iniciar geração"]', 'button[aria-label*="eração"]',
              'button[aria-label*="enerate"]', 'button[type="submit"]:has(mat-icon:text-is("arrow_forward"))',
              'button[type="submit"]'],
    "agente": ["flow-agent-mode-toggle-chip button", "button.agent-mode-chip", 'button:has(.agent-mode-chip-label)'],
    "modelo": ['button[aria-label="Selecionar família de modelos"]', 'button[aria-label*="modelo"]', 'button[aria-label*="odel"]',
               "button.mat-mdc-menu-trigger:has(.model-select-trigger-content)", "button:has(.model-select-trigger-content)"],
    "chip_inicio": ["flow-ingredient-bar .frame-trigger", ".frame-trigger", 'button.empty-chip:text-is("Início")',
                    'button.empty-chip:text-is("Start")', 'button:text-is("Início")'],
    "asset": ["button.asset-item", "[role=option].asset-item", ".asset-item"],
    # botão de enviar arquivo na lista de mídias (layout normal e compacto/celular)
    "enviar_midia": ['button.upload-button', 'button[aria-label="Enviar mídia"]', 'button[aria-label*="nviar"]',
                     'button[aria-label*="pload"]', 'button:has(mat-icon:text-is("upload"))'],
    # aviso "Direitos de uso desta imagem" ao enviar arquivo -> Concordo
    "consentimento": ['flow-upload-consent-dialog .agree-actions-group button', 'flow-upload-consent-dialog button:has-text("Concordo")',
                      'mat-dialog-container button:has-text("Concordo")', '[role=dialog] button:has-text("Concordo")',
                      '[role=dialog] button:has-text("I agree")', '[role=dialog] button:has-text("Agree")',
                      'flow-upload-consent-dialog button:has-text("Agree")'],
    "salvar": ["button.settings-save-button", ".save-container button", 'button:text-is("Salvar")', 'button:has-text("Salvar")', 'button:has-text("Save")',
               'button:has-text("Aplicar")', 'button:has-text("Apply")', 'button:has-text("Concluído")', 'button:has-text("Done")',
               'button:has-text("OK")'],
    "incluir": ["button.detail-add-to-prompt-btn", 'button:has-text("Incluir no comando")', 'button:has-text("Adicionar ao comando")',
                'button:has-text("Add to prompt")', 'button:has-text("Usar")'],
}
TEXTOS = {
    "Imagem": ["Imagem", "Image", "Imagens"], "Vídeo": ["Vídeo", "Video", "Vídeos"],
    "Frames": ["Frames", "Frame", "Quadros", "Frames para vídeo"],
}
ROTULOS_GRUPO = {"Modo": ["Modo", "Mode"], "Tipo de vídeo": ["Tipo de vídeo", "Video type", "Tipo"],
                 "Proporção": ["Proporção", "Aspect ratio", "Proporção da tela"],
                 "Resolução do vídeo": ["Resolução do vídeo", "Resolução", "Resolution"],
                 "Duração do vídeo": ["Duração do vídeo", "Duração", "Duration"],
                 "Quantidade de resultados": ["Quantidade de resultados", "Quantidade", "Outputs", "Number of outputs"]}


def _achar(raiz, chave_ou_lista, timeout_s: float = 0.0):
    """1º elemento VISÍVEL entre todas as pistas (na ordem). None se não achou."""
    pistas = PISTAS[chave_ou_lista] if isinstance(chave_ou_lista, str) else list(chave_ou_lista)
    fim = time.monotonic() + timeout_s
    while True:
        for sel in pistas:
            el = _primeiro_visivel(raiz, sel)
            if el is not None:
                return el
        if time.monotonic() >= fim:
            return None
        time.sleep(0.3)


def aceitar_consentimento(page) -> bool:
    """Se o Flow pedir "Direitos de uso desta imagem", clica em Concordo."""
    botao = _achar(page, "consentimento")
    if botao is None:
        return False
    try:
        botao.click(timeout=5_000)
        _confirmar(lambda: _achar(page, "consentimento") is None, timeout_s=4.0)
        return True
    except Exception:  # noqa: BLE001
        return False


_RE_MEDIA_ID = re.compile(r"/image/([0-9A-Za-z_-]{12,})")


def media_id_da_url(url: str) -> str:
    """https://flow-content.google/image/<id>?Expires=... -> <id> (o mesmo id aparece na
    miniatura da lista de mídias do projeto). "" se a URL não tiver."""
    m = _RE_MEDIA_ID.search(str(url or ""))
    return m.group(1) if m else ""


def fechar_config_agente(page, timeout_s: float = 10.0) -> bool:
    """Se o painel "Configurações do agente" estiver aberto (ele cobre a caixa de comando),
    clica em SALVAR e confere que fechou; se não fechar, clica no X; por último, Esc.
    Devolve True se havia um painel aberto."""
    if _achar(page, "agente_painel") is None:
        return False
    fim = time.monotonic() + timeout_s
    tentativa = 0
    while _achar(page, "agente_painel") is not None and time.monotonic() < fim:
        tentativa += 1
        if tentativa <= 2:
            botao = _achar(page, "agente_salvar", timeout_s=1.5)
        elif tentativa <= 4:
            botao = _achar(page, "agente_fechar", timeout_s=1.0)
        else:
            botao = None
        try:
            if botao is not None:
                botao.scroll_into_view_if_needed(timeout=2_000)
                botao.click(timeout=5_000)
            else:
                page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        _confirmar(lambda: _achar(page, "agente_painel") is None, timeout_s=2.5)
    return True


def _caixa_da_tela(page, timeout_s: float = 20.0):
    """A caixa de comando visível (de preferência a que tem o botão de configurações/gerar).
    Se um painel estiver na frente dela, fecha (salvando). Nunca \"chuta\" a página inteira."""
    fim = time.monotonic() + timeout_s
    while True:
        fechar_config_agente(page)
        melhor = None
        for sel in PISTAS["caixa"]:
            caixas = page.locator(sel)
            try:
                for k in range(caixas.count()):
                    c = caixas.nth(k)
                    if not c.is_visible():
                        continue
                    if _achar(c, "editor") is None:
                        continue
                    if _achar(c, "gatilho") is not None or _achar(c, "gerar") is not None:
                        return c
                    melhor = melhor or c
            except Exception:  # noqa: BLE001
                continue
        if melhor is not None and time.monotonic() >= fim - timeout_s * 0.6:
            return melhor
        if time.monotonic() >= fim:
            raise GoogleFlowError("Não achei a caixa de comando do Flow na tela (onde se digita o pedido) — "
                                  "algum painel ficou na frente dela?")
        time.sleep(0.4)


def _desbloquear(page) -> None:
    """Tira da frente o que costuma travar cliques: painel do agente, menus, diálogos de novidade."""
    for f in (aceitar_consentimento, fechar_config_agente, _dispensar_changelog, _dispensar_dialogos_de_boas_vindas):
        try:
            f(page)
        except Exception:  # noqa: BLE001
            pass


def _repetir(passo, tentativas: int = 3, pausa_s: float = 1.0, page=None):
    """Roda `passo()` até dar certo; entre tentativas aperta Escape e tira o que bloqueia."""
    ultimo: Optional[BaseException] = None
    for k in range(tentativas):
        try:
            return passo()
        except GoogleFlowLimitReached:
            raise
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            if page is not None and k + 1 < tentativas:
                try:
                    page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
                _desbloquear(page)
            time.sleep(pausa_s * (k + 1))
    raise ultimo if isinstance(ultimo, GoogleFlowError) else GoogleFlowError(str(ultimo))


def _escolhido(el) -> Optional[bool]:
    """True/False se o botão de opção diz se está marcado; None se ele não informa."""
    try:
        v = el.get_attribute("aria-checked") or el.get_attribute("aria-pressed") or el.get_attribute("aria-selected")
        if v in ("true", "false"):
            return v == "true"
        pai = el.locator("xpath=..")
        cls = (pai.get_attribute("class") or "") + " " + (el.get_attribute("class") or "")
        if "checked" in cls or "selected" in cls:
            return True
    except Exception:  # noqa: BLE001
        pass
    return None


def _clicar_opcao(painel, grupo: str, alvo: str, obrigatorio: bool = False) -> bool:
    """Escolhe a opção `alvo` (\"Vídeo\", \"Frames\", \"9:16\", \"720p\", \"4s\", \"x1\") no painel:
    1º pelo grupo (aria-label), 2º por qualquer botão do painel com esse texto exato.
    Confere que ficou marcada; se o Flow não informar, aceita o clique."""
    if not alvo:
        return False
    textos = TEXTOS.get(alvo, [alvo])
    pistas = []
    for rot in ROTULOS_GRUPO.get(grupo, [grupo]):
        for t in textos:
            pistas.append(f'flow-toggles[aria-label*="{rot}"] button:has(.toggle-text:text-is("{t}"))')
            pistas.append(f'[aria-label*="{rot}"] button:has-text("{t}")')
    for t in textos:
        pistas += [f'button:has(.toggle-text:text-is("{t}"))', f'[role="radio"]:text-is("{t}")', f'button:text-is("{t}")']
    el = _achar(painel, pistas, timeout_s=3.0)
    if el is None:
        if obrigatorio:
            raise GoogleFlowError(f'Não achei a opção "{alvo}" nas configurações da caixa do Flow.')
        return False
    if _escolhido(el) is True:
        return True
    for _ in range(2):
        try:
            el.click(timeout=5_000)
        except Exception:  # noqa: BLE001
            continue
        if _confirmar(lambda: _escolhido(el) is not False, timeout_s=2.0):
            return True
    if obrigatorio:
        raise GoogleFlowError(f'Cliquei em "{alvo}" nas configurações do Flow mas não ficou marcado.')
    return False


def _escolher_modelo(page, painel, modelo: str) -> bool:
    """Abre o seletor de modelo do painel e escolhe pelo nome (\"Omni 1.1 Flash\", \"Nano Banana 2.1\")."""
    if not modelo:
        return False
    try:
        if modelo.lower() in (painel.inner_text() or "").lower():
            botao_atual = _achar(painel, "modelo")
            if botao_atual is not None and modelo.lower() in (botao_atual.inner_text() or "").lower():
                return True  # já é esse modelo
    except Exception:  # noqa: BLE001
        pass
    botao = _achar(painel, "modelo", timeout_s=3.0)
    if botao is None:
        return False
    nome = modelo.replace('"', '\\"')
    for _ in range(2):
        try:
            botao.click(timeout=5_000)
            item = _achar(page, [f'flow-menu-item:has-text("{nome}") button', f'[role="menuitem"]:has-text("{nome}")',
                                 f'.cdk-overlay-container button:has-text("{nome}")'], timeout_s=5.0)
            if item is not None:
                item.click(timeout=5_000)
                time.sleep(0.8)
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
    return False


def _abrir_painel(page, caixa):
    painel = _achar(page, "painel")
    if painel is not None:
        return painel
    gatilho = _achar(caixa, "gatilho", timeout_s=10.0)
    if gatilho is None:
        raise GoogleFlowError('Não achei o botão de configurações da caixa do Flow (o que mostra o modelo e "x1").')
    gatilho.click(timeout=8_000)
    painel = _achar(page, "painel", timeout_s=8.0)
    if painel is None:
        raise GoogleFlowError("Cliquei no botão de configurações da caixa do Flow, mas o painel não abriu.")
    return painel


def salvar_painel(page, painel=None, timeout_s: float = 8.0) -> bool:
    """Clica em "Salvar" do painel aberto (procura DENTRO do painel, depois nos
    pop-ups) e confere que ele fechou. False se não havia botão de salvar."""
    raizes = [r for r in (painel, page.locator(".cdk-overlay-container")) if r is not None]
    for k, raiz in enumerate(raizes + [page]):
        # na página toda, só as pistas exatas do Flow (o botão "Salvar" fica numa .save-container
        # que pode estar FORA do bloco do painel); texto solto ("OK", "Done") só dentro do painel/pop-up
        pistas = "salvar" if k < len(raizes) else ["button.settings-save-button", ".save-container button"]
        botao = _achar(raiz, pistas, timeout_s=1.0)
        if botao is None:
            continue
        for _ in range(2):
            try:
                botao.click(timeout=5_000)
            except Exception:  # noqa: BLE001
                pass
            if _confirmar(lambda: painel is None or not painel.is_visible(), timeout_s=timeout_s):
                return True
        return True
    return False


def _fechar_painel(page, caixa) -> None:
    """Depois de mudar as opções: clica em Salvar (se o painel tiver); se não
    tiver ou não fechar, Esc / clica de novo no botão / clica fora."""
    for _ in range(3):
        painel = _achar(page, "painel")
        if painel is None:
            return
        if salvar_painel(page, painel) and _achar(page, "painel") is None:
            return
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
        if _achar(page, "painel") is None:
            return
        g = _achar(caixa, "gatilho")
        if g is not None:
            try:
                g.click(timeout=3_000)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.5)
        if _achar(page, "painel") is None:
            return
        try:  # clica num canto neutro da página
            page.mouse.click(5, 5)
        except Exception:  # noqa: BLE001
            pass


def _desligar_agente(page) -> None:
    """O chip \"Agente\" às vezes aparece, às vezes não. Se aparecer ligado, desliga."""
    chip = _achar(page, "agente", timeout_s=1.5)
    if chip is None:
        return
    for _ in range(2):
        estado = _escolhido(chip)
        if estado is False:
            return
        if estado is None:  # o chip não diz se está ligado: decide pela classe
            try:
                if "checked" not in (chip.get_attribute("class") or ""):
                    return
            except Exception:  # noqa: BLE001
                return
        try:
            chip.click(timeout=3_000)
        except Exception:  # noqa: BLE001
            return
        _confirmar(lambda: _escolhido(chip) is False, timeout_s=3.0)


def preparar_caixa(page, tipo: str, modelo: str = "", proporcao: str = "9:16", resolucao: str = "", duracao: str = "") -> None:
    """Agente desligado (se existir) + configurações da caixa: Imagem (proporção,
    modelo, x1) ou Vídeo -> Frames (modelo, proporção, resolução, duração, x1)."""
    video = tipo != "imagem"

    def _passo():
        fechar_config_agente(page)
        _desligar_agente(page)
        caixa = _caixa_da_tela(page)
        painel = _abrir_painel(page, caixa)
        _clicar_opcao(painel, "Modo", "Vídeo" if video else "Imagem", obrigatorio=True)
        time.sleep(0.5)
        painel = _abrir_painel(page, caixa)  # trocar o modo pode redesenhar o painel
        if video:
            _clicar_opcao(painel, "Tipo de vídeo", "Frames", obrigatorio=True)
            time.sleep(0.4)
        if modelo:
            _escolher_modelo(page, painel, modelo)
            painel = _abrir_painel(page, caixa)  # fechar o menu do modelo pode fechar o painel junto
        _clicar_opcao(painel, "Proporção", proporcao_flow(proporcao))
        if video:
            _clicar_opcao(painel, "Resolução do vídeo", resolucao)
            _clicar_opcao(painel, "Duração do vídeo", duracao)
        _clicar_opcao(painel, "Quantidade de resultados", "x1")
        _fechar_painel(page, caixa)
    _repetir(_passo, tentativas=3, page=page)
    time.sleep(0.3)


def definir_frame_inicial(page, caminho_imagem: str, media_id: str = "") -> bool:
    """Chip "Início" -> escolhe a imagem e "Incluir no comando". Se `media_id` vier (o frame
    foi gerado NESTE projeto), escolhe a própria imagem na lista de mídias, sem enviar
    arquivo; senão envia o arquivo (aceitando o aviso de direitos de uso) e escolhe pelo
    nome. Devolve True se reaproveitou a imagem do projeto."""
    nome = os.path.basename(caminho_imagem)
    radical = os.path.splitext(nome)[0].replace('"', "")
    mid = (media_id or "").replace('"', "")
    reaproveitou = [False]

    def _chip():
        return _achar(page, "chip_inicio", timeout_s=10.0)

    def _vazio(chip) -> bool:
        try:
            return chip.locator("button.empty-chip").count() > 0 or (chip.inner_text() or "").strip() in ("Início", "Start")
        except Exception:  # noqa: BLE001
            return True

    def _item_do_projeto():
        if not mid:
            return None
        return _achar(page, [f'button.asset-item:has(img[src*="{mid}"])', f'[role=option]:has(img[src*="{mid}"])',
                             f'.asset-item:has(img[src*="{mid}"])'])

    def _item_enviado():
        return _achar(page, [f'button.asset-item:has(.asset-title:has-text("{radical}"))',
                             f'[role=option]:has-text("{radical}")', f'.asset-item:has-text("{radical}")'])

    def _passo():
        chip = _chip()
        if chip is None:
            raise GoogleFlowError('Não apareceu o campo "Início" na caixa do Flow (o modo Vídeo → Frames ligou?).')
        alvo = chip.locator("button").first if chip.locator("button").count() else chip
        alvo.click(timeout=8_000)
        time.sleep(1.0)
        aceitar_consentimento(page)
        # 1) a imagem já está no projeto (gerada aqui): escolhe ela
        item = None
        fim = time.monotonic() + (6 if mid else 0)
        while mid and time.monotonic() < fim and item is None:
            item = _item_do_projeto()
            if item is None:
                time.sleep(0.5)
        enviado = False
        if item is not None:
            reaproveitou[0] = True
        else:
            # 2) envia o arquivo (input direto; senão o botão de enviar abre o seletor de arquivo)
            for sel in ('.cdk-overlay-container input[type="file"]', '.mobile-add-menu-container input[type="file"]',
                        'flow-media-upload input[type="file"]', 'input[type="file"]'):
                entrada = page.locator(sel)
                try:
                    if entrada.count():
                        entrada.last.set_input_files(caminho_imagem, timeout=10_000)
                        enviado = True
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not enviado:
                for pista in (PISTAS["enviar_midia"] + [SEL_BTN_ENVIAR_ARQUIVO]):
                    botao = _achar(page, [pista])
                    if botao is None:
                        continue
                    try:
                        with page.expect_file_chooser(timeout=8_000) as escolha:
                            botao.click(timeout=4_000)
                        escolha.value.set_files(caminho_imagem)
                        enviado = True
                        break
                    except Exception:  # noqa: BLE001
                        continue
            fim = time.monotonic() + (120 if enviado else 8)
            while time.monotonic() < fim:
                aceitar_consentimento(page)  # "Direitos de uso desta imagem" -> Concordo
                if _achar(page, "incluir") is not None:  # o Flow já abriu a prévia da imagem enviada
                    break
                item = _item_enviado()
                if item is not None:
                    break
                time.sleep(0.8)
            if item is None and _achar(page, "incluir") is None:
                raise GoogleFlowError('A imagem do frame foi enviada mas não apareceu na lista do "Início" do Flow.'
                                      if enviado else 'Não achei como enviar a imagem do frame no "Início" do Flow.')
        if item is not None:
            item.click(timeout=5_000)
        aceitar_consentimento(page)
        try:
            page.locator(SEL_PREVIA_CARREGADA).first.wait_for(state="visible", timeout=TIMEOUT_PREVIA_S * 1000)
        except PWTimeout:
            pass  # alguns layouts não mostram a prévia grande
        incluir = _achar(page, "incluir", timeout_s=30.0)
        if incluir is None:
            raise GoogleFlowError('Não achei o botão "Incluir no comando" depois de escolher a imagem do frame.')
        incluir.click(timeout=8_000)
        if not _confirmar(lambda: (_chip() is not None and not _vazio(_chip())), timeout_s=10.0):
            raise GoogleFlowError('A imagem não ficou no campo "Início" da caixa do Flow.')
    _repetir(_passo, tentativas=3, pausa_s=1.5, page=page)
    time.sleep(0.5)
    return reaproveitou[0]


def _digitar_e_gerar(page, prompt: str, palavras_limite: str = "") -> None:
    """Escreve o prompt na caixa VISÍVEL, confere que entrou e clica UMA vez em gerar."""
    texto = " ".join((prompt or "").split())
    amostra = texto[:25].lower()
    caixa = _caixa_da_tela(page)

    def _editor():
        return _achar(caixa, "editor", timeout_s=8.0) or _achar(page, "editor", timeout_s=2.0)

    def _entrou(ed) -> bool:
        try:
            atual = ed.input_value() if (ed.evaluate("e => e.tagName") or "").upper() == "TEXTAREA" else ed.inner_text()
            return amostra in " ".join((atual or "").split()).lower()
        except Exception:  # noqa: BLE001
            return False

    def _escrever():
        ed = _editor()
        if ed is None:
            raise GoogleFlowError('Não achei onde digitar o pedido na caixa do Flow ("O que você quer criar?").')
        for tentativa in range(3):
            ed.click(timeout=5_000)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            if tentativa == 0:
                page.keyboard.insert_text(texto)
            elif tentativa == 1:
                page.keyboard.type(texto, delay=8)
            else:
                ed.fill(texto)
            if _confirmar(lambda: _entrou(ed), timeout_s=3.0):
                return ed
        raise GoogleFlowError("Cliquei na caixa do Flow mas o texto do pedido não entrou nela.")
    ed = _repetir(_escrever, tentativas=2, page=page)
    botao = None
    fim = time.monotonic() + 20
    while time.monotonic() < fim:
        b = _achar(caixa, "gerar") or _achar(page, "gerar")
        if b is not None and b.is_enabled():
            botao = b
            break
        time.sleep(0.4)
    if botao is None:
        avisos = _avisos(page)
        if texto_indica_limite(avisos, palavras_limite):
            raise GoogleFlowLimitReached("Limite do Google Flow atingido: " + avisos)
        raise GoogleFlowError('O botão "Iniciar geração" continua desabilitado.' + (f" Aviso: {avisos}" if avisos else ""))
    if not _entrou(ed):  # algo apagou o texto antes do clique: escreve de novo
        _escrever()
    botao.click(timeout=8_000)  # um clique só: clicar de novo poderia gerar (e cobrar) duas vezes


class _AntesDeGerar(GoogleFlowError):
    """Falhou ANTES do clique em gerar: dá pra tentar de novo sem gastar crédito."""


def submeter_trabalho(page, trab: Dict[str, Any], palavras_limite: str = "") -> Dict[str, Any]:
    """Prepara a caixa e manda gerar UM trabalho (imagem ou animação). Devolve o
    estado pra `checar_trabalho`. Erros antes do clique em gerar saem como _AntesDeGerar."""
    video = trab["tipo"] == "animar"
    script = JS_VIDEOS_FORA_DOS_MENUS if video else JS_IMAGENS_NA_PAGINA
    try:
        preparar_caixa(page, "video" if video else "imagem", trab.get("modelo") or "", trab.get("proporcao") or "9:16",
                       trab.get("resolucao") or "720p", trab.get("duracao") or "4s")
        reaproveitou = definir_frame_inicial(page, trab["imagem"], trab.get("media_id") or "") if video else False
        try:
            antes = set(page.evaluate(script) or [])
        except Exception:  # noqa: BLE001
            antes = set()
        avisos_antes = _avisos(page)
    except GoogleFlowLimitReached:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _AntesDeGerar(str(exc)) from exc
    try:
        _digitar_e_gerar(page, trab["prompt"], palavras_limite)
    except GoogleFlowLimitReached:
        raise
    except Exception as exc:  # noqa: BLE001 -- _digitar_e_gerar só falha antes do clique
        raise _AntesDeGerar(str(exc)) from exc
    return {"antes": antes, "script": script, "avisos_antes": avisos_antes, "assinatura": None, "desde": 0.0,
            "reaproveitou": reaproveitou}


def checar_trabalho(page, estado: Dict[str, Any], ignorar=frozenset(), palavras_limite: str = "") -> Optional[List[str]]:
    """None = ainda gerando; lista = URLs novas (estáveis por ESTAVEL_S). Levanta
    erro se o Flow mostrou limite ou falha."""
    try:
        atuais = [u for u in (page.evaluate(estado["script"]) or []) if u not in estado["antes"] and u not in ignorar]
    except Exception:  # noqa: BLE001
        atuais = []
    agora = time.monotonic()
    if atuais:
        if tuple(atuais) != estado["assinatura"]:
            estado["assinatura"], estado["desde"] = tuple(atuais), agora
        elif agora - estado["desde"] >= ESTAVEL_S:
            return list(atuais)
        return None
    avisos = _avisos(page)
    if avisos and avisos != estado.get("avisos_antes"):
        if texto_indica_limite(avisos, palavras_limite):
            raise GoogleFlowLimitReached("Limite do Google Flow atingido: " + avisos)
        if _RE_FALHA_GERACAO.search(avisos):
            raise GoogleFlowError("O Flow recusou/falhou a geração: " + avisos)
    return None


def submeter_direto(page, trab: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Lote no modo direto: configura a caixa (+ frame) e escreve o prompt (erro aqui = _AntesDeGerar, dá pra tentar
    de novo sem gastar crédito); depois UM clique em gerar. Devolve o estado pra `checar_direto`."""
    from googleflow import flow_direto as fd
    d = trabalho_direto(trab["tipo"], trab["prompt"], cfg, trab, trab.get("imagem") or "", trab.get("media_id") or "")
    if trab.get("modelo"):
        d["modelo"] = trab["modelo"]
    video = d["tipo"] == "video"
    reaproveitou = False
    try:
        fd.configurar_caixa(page, d["tipo"], d.get("proporcao") or "16:9", d.get("modelo") or "", "x1",
                            d.get("tipo_video") or ("Frames" if video else ""))
        ini = d.get("inicio") or {}
        if video and (ini.get("arquivo") or ini.get("media_id")):
            reaproveitou = fd.definir_frame(page, "Início", d["inicio"].get("arquivo"), d["inicio"].get("media_id") or "") == "do projeto"
        fd.escrever_prompt(page, d["prompt"])
    except fd.FlowLimite as exc:
        e2 = erro_do_passo(exc)
        e2.tipo_midia = "video" if video else "imagem"
        raise e2 from exc
    except fd.FlowPassoErro as exc:
        raise _AntesDeGerar(str(erro_do_passo(exc))) from exc
    try:
        estado = fd.clicar_gerar(page)
    except fd.FlowLimite as exc:
        e2 = erro_do_passo(exc)
        e2.tipo_midia = "video" if video else "imagem"
        raise e2 from exc
    except fd.FlowPassoErro as exc:  # o clique não aconteceu: nada foi cobrado
        raise _AntesDeGerar(str(erro_do_passo(exc))) from exc
    estado.update(direto=True, tipo_midia="video" if video else "imagem", reaproveitou=reaproveitou)
    return estado


def checar_direto(page, estado: Dict[str, Any]) -> Optional[List[str]]:
    from googleflow import flow_direto as fd
    try:
        r = fd.checar(page, estado, estado.get("tipo_midia") or "imagem")
    except fd.FlowPassoErro as exc:
        e2 = erro_do_passo(exc)
        if isinstance(exc, fd.FlowLimite):
            e2.tipo_midia = estado.get("tipo_midia") or "imagem"
        raise e2 from exc
    return [m["url"] for m in r] if r else None


def _url_original(url: str) -> str:
    """Miniatura do Google (\"...=s512-rw\") -> tamanho original (\"=s0\")."""
    return re.sub(r"=s\d+(-[a-z]+)*$", "=s0", url) if "=s" in url else url


def chave_trabalho(trab: Dict[str, Any]) -> str:
    if trab["tipo"] == "animar":
        with open(trab["imagem"], "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()
        return chave_do_prompt(f"animar|{digest}|{trab['prompt']}|{trab.get('modelo')}|{trab.get('resolucao')}|"
                               f"{trab.get('duracao')}|{trab.get('proporcao')}")
    return chave_do_prompt(f"direto|imagem|{trab['prompt']}|{trab.get('modelo')}|{trab.get('proporcao')}")


def arquivo_do_cache(trab: Dict[str, Any]) -> Optional[str]:
    """Caminho local já gerado pra esse trabalho (ou None)."""
    itens = _videos_do_cache(trab["chave"]) if trab["tipo"] == "animar" else _fotos_do_cache(trab["chave"])
    for it in itens:
        if it.local_path and os.path.isfile(it.local_path):
            return it.local_path
    return None


def pasta_ao_vivo() -> Path:
    return pasta_dados() / "ao_vivo"


def _avisos(page) -> str:
    """Texto dos avisos/toasts/diálogos visíveis na página (vazio se não achar)."""
    try:
        return str(page.evaluate(JS_AVISOS) or "")
    except Exception:  # noqa: BLE001
        return ""


def _aviso_diag(base: Optional[str]) -> str:
    if not base:
        return ""
    extra = f" — HTML da parte importante em {base}_html.txt" if os.path.exists(f"{base}_html.txt") else ""
    return f" [diagnóstico salvo em {base}.png/.txt{extra}]"


JS_HTML_PAGINA = r"""() => {
  const c = document.documentElement.cloneNode(true);
  c.querySelectorAll('script, style, link[rel=stylesheet], noscript, iframe').forEach(e => e.remove());
  return '<!-- URL: ' + location.href + ' -->\n' + c.outerHTML.replace(/<svg[\s\S]*?<\/svg>/g, '<svg/>')
    .replace(/\s_ng[a-z]+-[a-z0-9-]+="[^"]*"/g, '').replace(/<!---->/g, '');
}"""

_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_RE_CONTA = re.compile(r"(Conta do Google|Google Account)\s*:[^\"<]*", re.I)
_RE_FOTO = re.compile(r"https://lh\d\.googleusercontent\.com/[^\"'\s)]*")


def limpar_dados_pessoais(texto: str) -> str:
    """Tira e-mail, nome da conta Google e foto do perfil do que vai pro diagnóstico (você vai mandar pra alguém)."""
    texto = _RE_EMAIL.sub("email@removido", texto or "")
    texto = _RE_CONTA.sub(r"\1: (removido)", texto)
    return _RE_FOTO.sub("https://foto-do-perfil-removida", texto)


def arquivos_do_diagnostico(base: str) -> List[Path]:
    """Os arquivos de um diagnóstico (`base` = nome sem extensão, ex.: 20261013_042705_039541)."""
    pasta = pasta_dados() / "diagnostico"
    return [pasta / (base + fim) for fim in (".png", ".txt", "_html.txt", "_pagina.html") if (pasta / (base + fim)).exists()]


def salvar_diagnostico(page, motivo: str) -> Optional[str]:
    """Guarda uma captura de tela + o texto da página em `flow_dados/diagnostico/`
    (mantém só os 20 mais recentes) pra você poder ver o que o Flow mostrou quando
    algo falhou. Nunca levanta erro. Devolve o caminho base, ou None."""
    try:
        pasta = pasta_dados() / "diagnostico"
        pasta.mkdir(parents=True, exist_ok=True)
        base = pasta / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        try:
            page.screenshot(path=str(base) + ".png")
        except Exception:  # noqa: BLE001
            pass
        try:
            texto = str(page.evaluate(JS_TEXTO_PAGINA) or "")
        except Exception:  # noqa: BLE001
            texto = ""
        Path(str(base) + ".txt").write_text(limpar_dados_pessoais(f"{motivo}\n\n--- texto da página ---\n{texto}"), encoding="utf-8")
        try:  # HTML só da parte importante, pronto pra copiar e mandar
            html = str(page.evaluate(JS_HTML_IMPORTANTE) or "")
            if html:
                Path(str(base) + "_html.txt").write_text(limpar_dados_pessoais(f"{motivo}\n\n{html}"), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:  # a página INTEIRA (sem scripts/estilos) — pra quando a parte importante não basta
            pagina = str(page.evaluate(JS_HTML_PAGINA) or "")
            if pagina:
                Path(str(base) + "_pagina.html").write_text(limpar_dados_pessoais(pagina)[:4_000_000], encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        for antigo in sorted(a for a in pasta.glob("*.txt") if not a.name.endswith("_html.txt"))[:-20]:
            for fim in (".txt", ".png", "_html.txt", "_pagina.html"):
                Path(str(antigo.with_suffix("")) + fim).unlink(missing_ok=True)
        return str(base)
    except Exception:  # noqa: BLE001
        return None


def esperar_geracao(page, antes: int, timeout_s: float, ignorar=frozenset(), palavras_limite: str = "",
                    script: str = "", seletor: str = "", graca_s: float = 0.0, oque: str = "imagem") -> List[str]:
    """Termina quando (a) a última mensagem nova é só texto — o critério do
    script original — ou (b) apareceu imagem e nada mudou por `ESTAVEL_S`
    (cobre o caso de x1, em que o texto e a imagem podem vir na mesma mensagem)."""
    fim = time.monotonic() + timeout_s
    assinatura = None
    estavel_desde = 0.0
    texto_desde = None
    while True:
        estado = page.evaluate(script or JS_ESTADO, [SEL_MENSAGEM, seletor or SEL_IMAGEM, antes])
        urls = [u for u in estado.get("urls", []) if u not in ignorar]
        so_texto = estado.get("mensagens", 0) > 0 and bool(estado.get("ultima_e_texto"))
        agora = time.monotonic()
        if urls:
            if so_texto:
                return urls
            atual = (estado.get("mensagens"), tuple(urls))
            if atual != assinatura:
                assinatura, estavel_desde = atual, agora
            elif agora - estavel_desde >= ESTAVEL_S:
                return urls
        elif texto_indica_limite((estado.get("texto") or "") + " " + (estado.get("avisos") or ""), palavras_limite):
            raise GoogleFlowLimitReached(
                "Limite do Google Flow atingido: " + ((estado.get("texto") or "") + " " + (estado.get("avisos") or "")).strip()
            )
        elif so_texto:
            texto_desde = texto_desde or agora
            if agora - texto_desde >= (graca_s or GRACA_SEM_IMAGEM_S):
                raise GoogleFlowError(
                    f"O Flow respondeu sem gerar {oque}: " + (estado.get("texto") or "(sem texto)")
                    + (f" | Aviso na tela: {estado['avisos']}" if estado.get("avisos") else "")
                )
        else:
            texto_desde = None
        if agora >= fim:
            raise GoogleFlowError(
                ("Tempo esgotado esperando a geração das imagens no Google Flow." if oque == "imagem" else
                 f"Tempo esgotado esperando a geração do {oque} no Google Flow (se o vídeo apareceu na tela, o "
                 "seletor dele pode ter mudado: ajuste \"flow_seletor_video\" em Configurações).")
                + (f" Aviso na tela: {estado['avisos']}" if estado.get("avisos") else "")
            )
        time.sleep(PAUSA_POLLING_S)


# v84_106: quem quer saber de cada imagem/vídeo gerado (o site põe na 🖼 galeria da aba Google Flow).
# Cada função recebe (caminho_do_arquivo, registro) — erro aqui nunca atrapalha a geração.
AO_SALVAR: List[Any] = []


def _avisar_salvo(registros: List[Dict[str, str]]) -> None:
    for r in registros:
        for fn in list(AO_SALVAR):
            try:
                fn(str(pasta_imagens() / r["arquivo"]), dict(r))
            except Exception:  # noqa: BLE001
                pass


def baixar_imagens(context, urls: List[str], prompt: str, chave: str) -> List[Dict[str, str]]:
    """Baixa as imagens (usa os cookies do navegador) pra pasta de imagens
    e registra cada uma em `imagens.json`. Nomes determinísticos
    (`flow_<chave>_<n>.<ext>`) — é o que permite o cache achar de novo."""
    pasta_imagens().mkdir(parents=True, exist_ok=True)
    dados = carregar_json()
    salvas: List[Dict[str, str]] = []

    for i, url in enumerate(urls, start=1):
        resp = context.request.get(url)
        if not resp.ok:
            continue
        tipo = resp.headers.get("content-type", "")
        ext = "jpg" if "jpeg" in tipo else "webp" if "webp" in tipo else "png"
        nome = f"flow_{chave[:12]}_{i}.{ext}"
        (pasta_imagens() / nome).write_bytes(resp.body())
        registro = {
            "arquivo": nome, "prompt": prompt, "chave": chave, "indice": i,
            "data": datetime.now().isoformat(timespec="seconds"),
        }
        dados = [d for d in dados if d.get("arquivo") != nome] + [registro]
        salvas.append(registro)

    if not salvas:
        raise GoogleFlowError("Não consegui baixar nenhuma das imagens geradas pelo Google Flow.")
    _salvar_json(dados)
    _avisar_salvo(salvas)
    return salvas


def baixar_videos(context, page, urls: List[str], prompt: str, chave: str) -> List[Dict[str, str]]:
    """Baixa os vídeos gerados (URL http com os cookies do navegador, ou blob:
    lido de dentro da página) pra pasta de mídia do Flow e registra cada um
    em `imagens.json` com `"tipo": "video"`. Tira um quadro .jpg (miniatura
    do editor) quando o ffmpeg existir."""
    import base64
    import subprocess
    pasta_imagens().mkdir(parents=True, exist_ok=True)
    dados = carregar_json()
    salvos: List[Dict[str, str]] = []
    for i, url in enumerate(urls, start=1):
        corpo = b""
        try:
            if url.startswith(("blob:", "data:")):
                corpo = base64.b64decode(page.evaluate(JS_BAIXAR_BASE64, url) or "")
            else:
                resp = context.request.get(url)
                if resp.ok:
                    corpo = resp.body()
        except Exception:  # noqa: BLE001 -- tenta o próximo
            corpo = b""
        if len(corpo) < 1024:
            continue
        nome = f"flow_{chave[:12]}_{i}.mp4"
        destino = pasta_imagens() / nome
        destino.write_bytes(corpo)
        miniatura = ""
        try:
            thumb = pasta_imagens() / f"flow_{chave[:12]}_{i}_thumb.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(destino), "-frames:v", "1",
                            "-vf", "scale=480:-2", str(thumb)], capture_output=True, timeout=60)
            if thumb.exists():
                miniatura = thumb.name
        except Exception:  # noqa: BLE001
            pass
        registro = {
            "arquivo": nome, "prompt": prompt, "chave": chave, "indice": i, "tipo": "video",
            "miniatura": miniatura, "data": datetime.now().isoformat(timespec="seconds"),
        }
        dados = [d for d in dados if d.get("arquivo") != nome] + [registro]
        salvos.append(registro)
    if not salvos:
        raise GoogleFlowError("Não consegui baixar nenhum dos vídeos gerados pelo Google Flow.")
    _salvar_json(dados)
    _avisar_salvo(salvos)
    return salvos


# ------------------------------ prompt ------------------------------
_INICIO_DE_COMANDO = re.compile(r"^\s*(gere|crie|generate|create|make|desenhe|draw)\b", re.IGNORECASE)
_JA_TEM_PROPORCAO = re.compile(r"propor[cç][aã]o|aspect|\b16\s*[x:]\s*9\b|\b9\s*[x:]\s*16\b", re.IGNORECASE)


def proporcao_para_orientacao(orientation: Optional[str]) -> str:
    return "9x16" if orientation == "9:16" else "16x9"


_PEDE_IMAGEM = re.compile(r"^\s*(gere|crie|desenhe)\s+(a|uma)\s+imagem(\s+de)?\s+", re.IGNORECASE)


def montar_prompt_video(descricao: str, proporcao: str = "16x9") -> str:
    """Pedido de VÍDEO pro agente do Flow: "um gato correndo" ->
    "gere um vídeo de um gato correndo proporção 16x9"."""
    texto = " ".join((descricao or "").split())
    if not texto:
        raise GoogleFlowError("Descrição do vídeo vazia.")
    texto = _PEDE_IMAGEM.sub("", texto)
    if not re.search(r"\bv[ií]deo\b|\bvideo\b", texto, re.IGNORECASE) or not _INICIO_DE_COMANDO.match(texto):
        texto = f"gere um vídeo de {texto}"
    if not _JA_TEM_PROPORCAO.search(texto):
        texto = f"{texto} proporção {proporcao}"
    return texto


def montar_prompt(descricao: str, proporcao: str = "16x9") -> str:
    """Transforma a `query` do segmento no pedido enviado ao agente do Flow.
    O painel do Flow é um chat: sem um verbo de comando ele pode responder
    com texto em vez de gerar. Ex: "um gato correndo" ->
    "gere a imagem de um gato correndo proporção 16x9"."""
    texto = " ".join((descricao or "").split())
    if not texto:
        raise GoogleFlowError("Descrição da imagem vazia.")
    if not _INICIO_DE_COMANDO.match(texto):
        texto = f"gere a imagem de {texto}"
    if not _JA_TEM_PROPORCAO.search(texto):
        texto = f"{texto} proporção {proporcao}"
    return texto


def chave_do_prompt(prompt: str) -> str:
    return hashlib.sha1(" ".join(prompt.lower().split()).encode("utf-8")).hexdigest()


# ------------------------------ cliente ------------------------------
@dataclass
class FlowPhoto:
    """Uma imagem gerada — mesmos campos que os outros clientes de foto
    expõem (id, url, sizes, description, author), pra o resto do site
    tratar o Flow como qualquer banco de fotos."""
    id: str
    url: str
    sizes: Dict[str, str]
    description: str
    author: str = "Google Flow (IA)"
    local_path: str = ""


@dataclass
class FlowVideo:
    """Um vídeo gerado (Veo) — mesma "cara" dos resultados dos bancos de vídeo
    (`id`, `to_dict()` com thumbnail/url) pra entrar no caminho de vídeo do site."""
    id: str
    url: str
    thumbnail: str = ""
    description: str = ""
    author: str = "Google Flow (IA)"
    local_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "thumbnail": self.thumbnail, "title": self.description[:60], "author": self.author,
                "url": self.url, "video_preview_url": self.url}


class _SessaoNula:
    """`ClientFactory` fecha `client.session` no fim; o Flow não mantém
    navegador aberto entre chamadas (abre, gera e fecha na mesma thread —
    o playwright síncrono não pode trocar de thread), então não há nada
    a fechar."""

    def close(self) -> None:
        pass


def _playwright_padrao():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


class GoogleFlowClient:
    """Cliente de FOTOS (geradas por IA) do Google Flow.

    `site_cfg` (config do site): usa `browser_visible` (False = oculto),
    `orientation` (proporção do pedido), `flow_navegador`, `flow_exe` e
    `flow_timeout_seconds`. `playwright_factory` existe pra teste: uma
    função sem argumentos que devolve algo no estilo `sync_playwright()`.
    """

    def __init__(self, site_cfg: Optional[Dict[str, Any]] = None, playwright_factory=None):
        self.cfg: Dict[str, Any] = site_cfg or {}
        self._playwright_factory = playwright_factory
        self.session = _SessaoNula()
        if playwright_factory is None and not PLAYWRIGHT_DISPONIVEL:
            raise GoogleFlowError(
                "Playwright não está instalado — o Google Flow precisa dele. Rode: "
                "pip install playwright && playwright install chromium"
            )

    # -- config ---------------------------------------------------------
    @property
    def oculto(self) -> bool:
        return not self.cfg.get("browser_visible", False)

    @property
    def proporcao(self) -> str:
        return proporcao_para_orientacao(self.cfg.get("orientation"))

    @property
    def timeout_geracao_s(self) -> int:
        try:
            return int(self.cfg.get("flow_timeout_seconds") or TIMEOUT_GERACAO_S)
        except (TypeError, ValueError):
            return TIMEOUT_GERACAO_S

    def _abrir_playwright(self):
        return (self._playwright_factory or _playwright_padrao)()

    # -- interface de banco de fotos -------------------------------------
    def _chave_sessao(self):
        nome = (self.cfg.get("flow_navegador") or "auto").strip().lower()
        exe = (self.cfg.get("flow_exe") or "").strip()
        return (nome, exe, self.oculto, self._playwright_factory or _playwright_padrao)

    def search_photos_all(self, query: str, max_pages: int = 1, **_ignorado: Any) -> List[FlowPhoto]:
        """"Busca" = gera (ou reaproveita do cache) a imagem desse pedido, na
        conversa única do Flow. O pedido entra numa fila e é atendido pela
        thread dona do navegador; quem chama espera o resultado."""
        prompt = montar_prompt(query, self.proporcao)
        chave = chave_do_prompt(prompt)

        fotos = self._do_cache(chave)
        if fotos:
            return fotos
        pedido = _Pedido(prompt, chave, self.timeout_geracao_s, dict(self.cfg))
        _enviar(self._chave_sessao(), self.cfg, self._playwright_factory or _playwright_padrao, pedido)
        pedido.pronto.wait()
        if pedido.erro is not None:
            raise pedido.erro
        fotos = self._do_cache(chave)
        if not fotos:
            raise GoogleFlowError("O Google Flow não devolveu nenhuma imagem.")
        return fotos

    # -- interface de banco de VÍDEO (vídeo gerado com Veo) ---------------
    @property
    def timeout_video_s(self) -> int:
        return max(self.timeout_geracao_s, TIMEOUT_VIDEO_MIN_S)

    def search_all(self, query: str = "", max_pages: int = 1, **_ignorado: Any) -> List[FlowVideo]:
        """"Busca" de vídeo = gera (ou reaproveita do cache) um vídeo curto desse pedido."""
        prompt = montar_prompt_video(query, self.proporcao)
        chave = chave_do_prompt(prompt)
        videos = _videos_do_cache(chave)
        if videos:
            return videos
        pedido = _Pedido(prompt, chave, self.timeout_video_s, dict(self.cfg), tipo="video")
        _enviar(self._chave_sessao(), self.cfg, self._playwright_factory or _playwright_padrao, pedido)
        pedido.pronto.wait()
        if pedido.erro is not None:
            raise pedido.erro
        videos = _videos_do_cache(chave)
        if not videos:
            raise GoogleFlowError("O Google Flow não devolveu nenhum vídeo.")
        return videos

    def gerar_imagem_prompt(self, prompt_completo: str, forcar: bool = False) -> List[FlowPhoto]:
        """Gera (ou reaproveita do cache) uma imagem com o pedido EXATO — usado
        pelos Vídeos modelados, onde o prompt já vem pronto do estilo.
        `forcar` = esquece a imagem guardada e gera outra (variação)."""
        if forcar:
            descartar_do_cache(prompt_completo, "imagem", self.proporcao)
        return self.search_photos_all(prompt_completo)

    def animar_imagem(self, caminho_imagem: str, prompt: str, modelo: str = "Omni 1.1 Flash",
                      resolucao: str = "720p", duracao: str = "4s", proporcao: str = "9:16",
                      forcar: bool = False) -> List[FlowVideo]:
        """Anima uma imagem (frame inicial) no Flow e devolve o vídeo gerado. Mesmo
        pedido (mesma imagem + mesmo movimento + mesmas opções) não é gerado duas vezes."""
        if not os.path.isfile(caminho_imagem):
            raise GoogleFlowError(f"Imagem inicial não encontrada: {caminho_imagem}")
        with open(caminho_imagem, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()
        opcoes = {"modelo": modelo, "resolucao": resolucao, "duracao": duracao, "proporcao": proporcao}
        chave = chave_do_prompt(f"animar|{digest}|{prompt}|{modelo}|{resolucao}|{duracao}|{proporcao}")
        if forcar:
            descartar_chave(chave)
        videos = _videos_do_cache(chave)
        if videos:
            return videos
        pedido = _Pedido(" ".join((prompt or "").split()), chave, self.timeout_video_s, dict(self.cfg), tipo="animar",
                         imagem=caminho_imagem, opcoes=opcoes)
        _enviar(self._chave_sessao(), self.cfg, self._playwright_factory or _playwright_padrao, pedido)
        pedido.pronto.wait()
        if pedido.erro is not None:
            raise pedido.erro
        videos = _videos_do_cache(chave)
        if not videos:
            raise GoogleFlowError("O Google Flow não devolveu o vídeo animado.")
        return videos

    def preparar_trabalho(self, trab: Dict[str, Any]) -> Dict[str, Any]:
        """Completa um trabalho de lote (calcula a chave; `forcar` esquece o resultado guardado)."""
        t = dict(trab)
        if t["tipo"] == "animar" and not os.path.isfile(t.get("imagem") or ""):
            raise GoogleFlowError(f"Imagem inicial não encontrada: {t.get('imagem')}")
        t["prompt"] = " ".join(str(t.get("prompt") or "").split())
        t["chave"] = chave_trabalho(t)
        if t.get("forcar"):
            descartar_chave(t["chave"])
        return t

    def gerar_lote(self, fila, abas: int = 2, cooldown=(2.0, 9.0), on_evento=None, cancelar=None) -> None:
        """Atende a `fila` (collections.deque de trabalhos já preparados com
        `preparar_trabalho`) com até `abas` abas do Flow em paralelo e um intervalo
        aleatório de `cooldown` segundos entre um envio e outro. A fila pode
        receber mais trabalhos enquanto roda. Cada trabalho termina com um evento
        {"tipo": "fim", "arquivo": ...} ou {"tipo": "erro", "erro": ...}."""
        pedido = _Pedido("lote", "lote_" + secrets.token_hex(6), self.timeout_video_s, dict(self.cfg), tipo="lote",
                         opcoes={"fila": fila, "abas": abas, "cooldown": cooldown, "evento": on_evento, "cancelar": cancelar})
        _enviar(self._chave_sessao(), self.cfg, self._playwright_factory or _playwright_padrao, pedido)
        pedido.pronto.wait()
        if pedido.erro is not None:
            raise pedido.erro

    def download_video(self, video: FlowVideo, output_dir: Optional[str] = None, **_ignorado: Any) -> str:
        origem = video.local_path
        if not origem or not os.path.exists(origem):
            raise GoogleFlowError(f"Arquivo do vídeo gerado não encontrado: {origem!r}")
        if not output_dir:
            return origem
        os.makedirs(output_dir, exist_ok=True)
        destino = os.path.join(output_dir, os.path.basename(origem))
        shutil.copyfile(origem, destino)
        return destino

    def download_photo(self, photo: FlowPhoto, output_dir: Optional[str] = None, **_ignorado: Any) -> str:
        """As imagens já estão no disco (foram baixadas na geração) — só
        copia pra pasta de trabalho da montagem."""
        origem = photo.local_path
        if not origem or not os.path.exists(origem):
            raise GoogleFlowError(f"Arquivo da imagem gerada não encontrado: {origem!r}")
        if not output_dir:
            return origem
        os.makedirs(output_dir, exist_ok=True)
        destino = os.path.join(output_dir, os.path.basename(origem))
        shutil.copyfile(origem, destino)
        return destino

    # -- login ------------------------------------------------------------
    def login_interativo(self, conta: str = CONTA_PADRAO) -> bool:
        """Abre uma janela VISÍVEL do navegador pra você entrar na conta
        Google; salva a sessão no perfil. Só precisa ser feito uma vez (ou
        quando a sessão expirar). Fecha antes a sessão de geração (o perfil do
        navegador é exclusivo). Espera até `TIMEOUT_LOGIN_S`."""
        encerrar_sessao()
        with _FLOW_LOCK:
            with self._abrir_playwright() as p:
                context, fechar = _abrir(p, self.cfg, headless=False, conta=conta)
                try:
                    if fechar:
                        restaurar_sessao(context, conta)
                    page = context.new_page()
                    page.goto(FLOW_URL, wait_until="domcontentloaded")
                    _passar_pela_pagina_inicial(page)
                    botao = page.locator(SEL_NOVO_PROJETO).first
                    try:
                        botao.wait_for(state="visible", timeout=TIMEOUT_LOGIN_S * 1000)
                    except PWTimeout:
                        raise GoogleFlowLoginRequired(
                            f"Tempo esgotado ({TIMEOUT_LOGIN_S}s) esperando o login no Google Flow."
                        )
                    salvar_sessao(context, conta)
                finally:
                    salvar_sessao(context, conta)
                    if fechar:
                        context.close()
        return True

    def login_automatico(self, conta: str, email: str, senha: str) -> bool:
        """Como `login_interativo`, mas preenche e-mail/senha sozinho em vez de
        esperar você digitar. A janela abre visível e continua aberta pelo
        mesmo `TIMEOUT_LOGIN_S` mesmo depois de preencher os campos -- se o
        Google pedir verificação em duas etapas ou bloquear o preenchimento
        automático, dá pra completar à mão nela, dentro desse tempo. Não se
        aplica ao navegador "cdp" (aí o login é no seu próprio Chrome, à mão).
        A senha passa só por esta chamada; ver `salvar_senha` para guardá-la."""
        if (self.cfg.get("flow_navegador") or "auto").strip().lower() == "cdp":
            raise GoogleFlowError('Login automático não se aplica ao navegador "cdp" -- faça login no seu próprio Chrome.')
        encerrar_sessao()
        with _FLOW_LOCK:
            with self._abrir_playwright() as p:
                context, fechar = _abrir(p, self.cfg, headless=False, conta=conta)
                try:
                    if fechar:
                        restaurar_sessao(context, conta)
                    page = context.new_page()
                    page.goto(FLOW_URL, wait_until="domcontentloaded")
                    _passar_pela_pagina_inicial(page)
                    try:
                        page.locator(SEL_NOVO_PROJETO).first.wait_for(state="visible", timeout=5_000)
                    except PWTimeout:
                        try:
                            _preencher_login_google(page, email, senha)
                            _dispensar_dialogos_de_boas_vindas(page)
                            page.locator(SEL_NOVO_PROJETO).first.wait_for(state="visible", timeout=TIMEOUT_LOGIN_S * 1000)
                        except PWTimeout:
                            avisos = _avisos(page)
                            caminho = salvar_diagnostico(page, "login automático não completou")
                            raise GoogleFlowLoginRequired(
                                f"Não consegui confirmar o login automático da conta '{conta}' -- o Google pode ter "
                                "pedido verificação em duas etapas ou bloqueado o preenchimento automático."
                                + (f" Aviso: {avisos}" if avisos else "")
                                + (_aviso_diag(caminho) if caminho else "")
                            )
                    salvar_sessao(context, conta)
                finally:
                    salvar_sessao(context, conta)
                    if fechar:
                        context.close()
        return True

    def trocar_senha(self, conta: str, senha_atual: str, nova_senha: Optional[str] = None) -> str:
        """Troca a senha da conta (fluxo confirmado pelo usuário via HTML real
        de myaccount.google.com). Faz login se precisar (a conta precisa ter
        e-mail cadastrado -- ver `definir_email`), confirma identidade com a
        senha ATUAL quando o Google pede, e define `nova_senha` (ou gera uma
        de 10 caracteres, só letras minúsculas e números, se não passar
        nenhuma). Guarda a senha nova com `salvar_senha` só depois de
        confirmar que a troca funcionou, e devolve ela.

        NUNCA tenta resolver captcha: se o Google mostrar um durante a
        confirmação de identidade, para na hora com um erro claro -- a
        janela fica aberta pra você completar à mão. Não se aplica ao
        navegador "cdp"."""
        if (self.cfg.get("flow_navegador") or "auto").strip().lower() == "cdp":
            raise GoogleFlowError('Troca de senha não se aplica ao navegador "cdp" -- faça isso no seu próprio Chrome.')
        nova_senha = nova_senha or gerar_senha_aleatoria()
        encerrar_sessao()
        with _FLOW_LOCK:
            with self._abrir_playwright() as p:
                context, fechar = _abrir(p, self.cfg, headless=False, conta=conta)
                try:
                    if fechar:
                        restaurar_sessao(context, conta)
                    page = context.new_page()
                    page.goto(GOOGLE_TROCAR_SENHA_URL, wait_until="domcontentloaded")

                    # não estava logada: o Google manda pra tela de login sozinho
                    try:
                        page.locator(SEL_GOOGLE_EMAIL).first.wait_for(state="visible", timeout=5_000)
                    except PWTimeout:
                        pass
                    else:
                        contas_por_nome = {c["nome"]: c for c in listar_contas()}
                        email = contas_por_nome.get(conta, {}).get("email", "")
                        if not email:
                            raise GoogleFlowError(
                                f"A conta '{conta}' não tem e-mail cadastrado -- preciso dele pra fazer login "
                                "antes de trocar a senha. Cadastre o e-mail e tente de novo."
                            )
                        page.locator(SEL_GOOGLE_EMAIL).first.fill(email)
                        page.locator(SEL_GOOGLE_EMAIL_PROXIMO).first.click()
                        page.locator(SEL_GOOGLE_SENHA).first.wait_for(state="visible", timeout=20_000)
                        page.locator(SEL_GOOGLE_SENHA).first.fill(senha_atual)
                        page.locator(SEL_GOOGLE_SENHA_PROXIMO).first.click()
                        page.goto(GOOGLE_TROCAR_SENHA_URL, wait_until="domcontentloaded")

                    # confirmar identidade: pede a senha ATUAL de novo (só às vezes)
                    try:
                        page.locator(SEL_REAUTH_SENHA).first.wait_for(state="visible", timeout=8_000)
                    except PWTimeout:
                        pass
                    else:
                        if page.locator(SEL_REAUTH_CAPTCHA).first.is_visible():
                            caminho = salvar_diagnostico(page, "captcha apareceu na troca de senha")
                            raise GoogleFlowError(
                                f"O Google pediu pra resolver um captcha pra confirmar a identidade da conta "
                                f"'{conta}' -- isso não é automatizado. A janela continua aberta: resolva o "
                                "captcha e troque a senha manualmente nela."
                                + (_aviso_diag(caminho) if caminho else "")
                            )
                        page.locator(SEL_REAUTH_SENHA).first.fill(senha_atual)
                        page.locator(SEL_REAUTH_AVANCAR).first.click()

                    try:
                        page.locator(SEL_NOVA_SENHA).first.wait_for(state="visible", timeout=20_000)
                        page.locator(SEL_NOVA_SENHA).first.fill(nova_senha)
                        page.locator(SEL_CONFIRMAR_NOVA_SENHA).first.fill(nova_senha)
                        page.locator(SEL_ALTERAR_SENHA_BOTAO).first.click()
                        page.locator(SEL_NOVA_SENHA).first.wait_for(state="hidden", timeout=20_000)
                    except PWTimeout as exc:
                        avisos = _avisos(page)
                        caminho = salvar_diagnostico(page, "troca de senha não confirmada")
                        raise GoogleFlowError(
                            f"Não consegui confirmar que a senha da conta '{conta}' foi trocada -- a senha ATUAL "
                            "pode estar errada, ou o Google mudou essa página."
                            + (f" Aviso: {avisos}" if avisos else "")
                            + (_aviso_diag(caminho) if caminho else "")
                        ) from exc

                    salvar_sessao(context, conta)
                finally:
                    salvar_sessao(context, conta)
                    if fechar:
                        context.close()
        salvar_senha(conta, nova_senha)
        return nova_senha

    # -- internos ---------------------------------------------------------
    def _do_cache(self, chave: str) -> List[FlowPhoto]:
        return _fotos_do_cache(chave)


def descartar_do_cache(prompt: str, tipo: str = "imagem", proporcao: str = "16x9") -> int:
    """Esquece o resultado guardado de um pedido (pra GERAR DE NOVO uma variação).
    Os arquivos continuam no disco; só o registro sai de `imagens.json`."""
    chave = chave_do_prompt(montar_prompt(prompt, proporcao) if tipo == "imagem" else prompt)
    dados = carregar_json()
    novos = [d for d in dados if d.get("chave") != chave]
    if len(novos) != len(dados):
        _salvar_json(novos)
    return len(dados) - len(novos)


def descartar_chave(chave: str) -> int:
    dados = carregar_json()
    novos = [d for d in dados if d.get("chave") != chave]
    if len(novos) != len(dados):
        _salvar_json(novos)
    return len(dados) - len(novos)


def _videos_do_cache(chave: str) -> List["FlowVideo"]:
    registros = sorted(
        (r for r in carregar_json() if r.get("chave") == chave and r.get("tipo") == "video"),
        key=lambda r: r.get("indice", 0),
    )
    videos = []
    for r in registros:
        caminho = pasta_imagens() / r.get("arquivo", "")
        if not caminho.exists():
            continue
        thumb = URL_PREFIXO_IMAGENS + r["miniatura"] if r.get("miniatura") and (pasta_imagens() / r["miniatura"]).exists() else ""
        videos.append(FlowVideo(id=caminho.stem, url=URL_PREFIXO_IMAGENS + caminho.name, thumbnail=thumb,
                                description=r.get("prompt", ""), local_path=str(caminho)))
    return videos


def _fotos_do_cache(chave: str) -> List[FlowPhoto]:
    registros = sorted(
        (r for r in carregar_json() if r.get("chave") == chave and r.get("tipo") != "video"),
        key=lambda r: r.get("indice", 0),
    )
    fotos = []
    for r in registros:
        caminho = pasta_imagens() / r.get("arquivo", "")
        if not caminho.exists():
            continue
        url = URL_PREFIXO_IMAGENS + caminho.name
        fotos.append(FlowPhoto(
            id=caminho.stem, url=url,
            sizes={"tiny": url, "small": url, "original": url},
            description=r.get("prompt", ""), local_path=str(caminho),
        ))
    return fotos


# ------------------------- sessão persistente -------------------------
class _Pedido:
    """Uma imagem pedida por alguma thread do site."""

    def __init__(self, prompt: str, chave: str, timeout_s: int, cfg: Dict[str, Any], tipo: str = "imagem",
                 imagem: str = "", opcoes: Optional[Dict[str, Any]] = None):
        self.prompt, self.chave, self.timeout_s, self.cfg = prompt, chave, timeout_s, cfg
        self.tipo = tipo if tipo in ("video", "animar", "lote") else "imagem"
        self.imagem = imagem             # só no tipo "animar": a imagem inicial (frame)
        self.opcoes = dict(opcoes or {})  # só no tipo "animar": modelo, resolucao, duracao, proporcao
        self.pronto = threading.Event()
        self.erro: Optional[BaseException] = None

    def concluir(self, erro: Optional[BaseException] = None) -> None:
        self.erro = erro
        self.pronto.set()


def _horas_para_liberar(cfg: Dict[str, Any]) -> float:
    try:
        return float(cfg.get("flow_horas_ate_liberar") or 24)
    except (TypeError, ValueError):
        return 24.0


def _config_do_projeto(cfg: Dict[str, Any]) -> tuple:
    """O que é configurado UMA vez no projeto do Flow: se mudar entre pedidos, o
    trabalhador abre um projeto novo em vez de gerar com a configuração errada."""
    return tuple(str(cfg.get(k) or "") for k in ("flow_modelo_imagem", "flow_proporcao_imagem",
                                                  "flow_proporcao_video", "flow_modelo_video"))


# ------------------------------------------------------------------ 🎬 modo DIRETO (v84_74, flow_direto.py)
def modo_direto(cfg: Dict[str, Any]) -> bool:
    """O jeito novo (seletores do HTML real, passo a passo conferido). A config do site já vem com "direto" por padrão
    (site_config.py); um cliente criado sem essa chave (scripts/testes antigos) continua no jeito de antes."""
    return str((cfg or {}).get("flow_modo_automacao") or "") == "direto"


def erro_do_passo(exc: BaseException) -> BaseException:
    """FlowPassoErro (flow_direto) → os erros que o resto do site já trata (troca de conta, login…)."""
    from googleflow import flow_direto as fd
    if isinstance(exc, fd.FlowLimite):
        return GoogleFlowLimitReached(f"Limite do Google Flow atingido: {exc.mensagem}")
    if isinstance(exc, fd.FlowLogin):
        return GoogleFlowLoginRequired(exc.mensagem)
    if isinstance(exc, fd.FlowPassoErro):
        return GoogleFlowError(f"Flow, passo \"{exc.passo}\": {exc.mensagem}")
    return exc


def agente_da_cfg(cfg: Dict[str, Any]) -> Dict[str, str]:
    """O que vai no painel "Configurações do agente" (uma vez por projeto)."""
    prop = proporcao_flow(proporcao_para_orientacao(cfg.get("orientation")))
    return {"img_proporcao": proporcao_flow(cfg.get("flow_proporcao_imagem") or "") or prop, "img_quantidade": "x1",
            "img_modelo": str(cfg.get("flow_modelo_imagem") or ""),
            "vid_proporcao": proporcao_flow(cfg.get("flow_proporcao_video") or "") or (prop if prop in ("16:9", "9:16") else "16:9"),
            "vid_quantidade": "x1", "vid_modelo": str(cfg.get("flow_modelo_video") or "")}


def trabalho_direto(tipo: str, prompt: str, cfg: Dict[str, Any], opcoes: Optional[Dict[str, Any]] = None,
                    imagem: str = "", media_id: str = "") -> Dict[str, Any]:
    """Pedido do site → o formato do flow_direto.gerar_um."""
    o = dict(opcoes or {})
    prop_cfg = proporcao_flow(proporcao_para_orientacao(cfg.get("orientation")))
    if tipo == "animar":
        return {"tipo": "video", "tipo_video": "Frames", "prompt": prompt, "modelo": o.get("modelo") or "",
                "proporcao": proporcao_flow(o.get("proporcao") or "") or prop_cfg,
                "inicio": {"arquivo": imagem, "media_id": media_id}}
    if tipo == "video":
        return {"tipo": "video", "tipo_video": "Elementos", "prompt": prompt, "modelo": str(cfg.get("flow_modelo_video") or ""),
                "proporcao": proporcao_flow(cfg.get("flow_proporcao_video") or "") or prop_cfg}
    return {"tipo": "imagem", "prompt": prompt, "modelo": str(cfg.get("flow_modelo_imagem") or ""),
            "proporcao": proporcao_flow(o.get("proporcao") or cfg.get("flow_proporcao_imagem") or "") or prop_cfg}


_PARAR = object()
_REG_LOCK = threading.Lock()
_TRABALHADOR: Optional["_Trabalhador"] = None


class _Trabalhador(threading.Thread):
    """Dono do navegador: abre UMA vez, mantém UMA conversa (projeto) e atende
    os pedidos em fila, um de cada vez. Tudo do Playwright acontece nesta thread."""

    def __init__(self, chave, cfg: Dict[str, Any], fabrica):
        super().__init__(name="googleflow-sessao", daemon=True)
        self.chave, self.cfg, self.fabrica = chave, dict(cfg), fabrica
        self.headless = chave[2]
        self.fila: "queue.Queue" = queue.Queue()
        self.encerrado = False
        self.contexto = None
        self.fechar_contexto = False
        self.conta: Optional[str] = None   # conta do navegador aberto agora
        self.pagina = None
        self.vistas: set = set()
        self._erro_final: Optional[BaseException] = None

    def parar(self) -> None:
        self.fila.put(_PARAR)  # depois dos pedidos já na fila (FIFO)

    def run(self) -> None:
        global _TRABALHADOR
        try:
            with _FLOW_LOCK:  # um navegador por vez (perfil exclusivo)
                with self.fabrica() as p:
                    self._loop(p)
        except BaseException as exc:  # noqa: BLE001
            self._erro_final = exc
        finally:
            with _REG_LOCK:
                self.encerrado = True
                if _TRABALHADOR is self:
                    _TRABALHADOR = None
            erro = self._erro_final or GoogleFlowError("A sessão do Google Flow foi encerrada antes de atender o pedido.")
            while True:
                try:
                    item = self.fila.get_nowait()
                except queue.Empty:
                    break
                if item is not _PARAR:
                    item.concluir(erro)

    def _loop(self, p) -> None:
        global _TRABALHADOR
        try:
            while True:
                try:
                    item = self.fila.get(timeout=OCIOSO_S)
                except queue.Empty:
                    with _REG_LOCK:
                        if self.fila.empty():  # ocioso de verdade: fecha o navegador
                            self.encerrado = True
                            if _TRABALHADOR is self:
                                _TRABALHADOR = None
                            return
                    continue
                if item is _PARAR:
                    return
                try:
                    self._atender(p, item)
                    item.concluir()
                except BaseException as exc:  # noqa: BLE001
                    self._apos_falha(exc)
                    item.concluir(exc)
        finally:
            self._fechar_tudo()

    def _atender(self, p, item: _Pedido) -> None:
        horas = _horas_para_liberar(item.cfg)
        ultimo_limite = ""
        ultimo_login: Optional[GoogleFlowLoginRequired] = None
        for _ in range(len(nomes_das_contas()) + 1):  # no máximo uma tentativa por conta: nunca gira pra sempre
            if item.tipo != "lote" and (_videos_do_cache(item.chave) if item.tipo in ("video", "animar") else _fotos_do_cache(item.chave)):  # outro pedido igual já gerou enquanto esperava na fila
                return
            try:
                self._gerar(p, item)
                return
            except GoogleFlowLimitReached as exc_limite:
                if self.chave[0] == "cdp" or self.conta is None:
                    raise  # Chrome do próprio usuário: não dá pra trocar de conta
                ultimo_limite = str(exc_limite)
                # v84_105: sem crédito de VÍDEO não quer dizer sem crédito de IMAGEM — marca só o tipo que acabou
                marcar_esgotada(self.conta, horas, tipo=getattr(exc_limite, "tipo_midia", None) or tipo_do_limite(item.tipo))
                self._fechar_pagina()
                self._fechar_contexto()
                # volta pro início do laço: escolhe a próxima conta e refaz ESTE pedido
                # (se não sobrou nenhuma, `escolher_conta_disponivel` levanta SemContas)
            except GoogleFlowSemContas as exc_sem:
                if ultimo_login is not None:  # pulou conta(s) por login e não sobrou nenhuma: o erro útil é o do login
                    raise ultimo_login from exc_sem
                if ultimo_limite:  # não perde o texto que o Flow mostrou
                    raise GoogleFlowSemContas(f"{exc_sem} | Última mensagem do Flow: {ultimo_limite}") from exc_sem
                raise
            except GoogleFlowLoginRequired as exc:
                if self.chave[0] != "cdp" and self.conta and len(nomes_das_contas()) > 1:
                    # ⏭ v84_110: a conta pediu login → pula ela e refaz ESTE pedido na próxima
                    pular_conta(self.conta, f"pediu login: {str(exc)[:160]}")
                    ultimo_login = exc if str(exc).startswith("Conta '") else GoogleFlowLoginRequired(f"Conta '{self.conta}': {exc}")
                    self._fechar_pagina()
                    self._fechar_contexto()
                    continue
                if self.conta and not str(exc).startswith("Conta '"):
                    raise GoogleFlowLoginRequired(f"Conta '{self.conta}': {exc}") from exc
                raise
        raise GoogleFlowSemContas("Não consegui gerar a imagem em nenhuma das contas do Google Flow.")

    def _gerar(self, p, item: _Pedido) -> None:
        tipo_lim = tipo_do_limite(item.tipo)
        if self.contexto is not None and self.chave[0] != "cdp" and self.conta and tipo_lim \
                and not conta_serve(self.conta, tipo_lim):  # a conta aberta não tem mais crédito pra este tipo
            self._fechar_pagina()
            self._fechar_contexto()
        if self.contexto is None:
            self.conta = CONTA_PADRAO if self.chave[0] == "cdp" else escolher_conta_disponivel(tipo=tipo_lim)
            self.contexto, self.fechar_contexto = _abrir(p, item.cfg, headless=self.headless, conta=self.conta)
            if self.fechar_contexto:
                restaurar_sessao(self.contexto, self.conta)
        if item.tipo == "lote":
            self._executar_lote(item)
            return
        if modo_direto(item.cfg):
            self._gerar_direto(item)
            return
        config_projeto = _config_do_projeto(item.cfg)
        if self.pagina is not None and getattr(self, "config_projeto", None) not in (None, config_projeto):
            self._fechar_pagina()  # proporção/modelo do projeto mudou: começa um projeto novo
        if self.pagina is None:
            self.pagina = abrir_novo_projeto(self.contexto, headless=self.headless)
            self.vistas = set()
            self.config_projeto = config_projeto
            if item.cfg.get("flow_configurar_projeto", True):
                configurar_projeto(
                    self.pagina,
                    item.cfg.get("flow_seletor_configuracoes", "") or "",
                    item.cfg.get("flow_modelo_video", "") or "",
                    modelo_imagem=item.cfg.get("flow_modelo_imagem", "") or "",
                    proporcao_imagem=item.cfg.get("flow_proporcao_imagem", "") or "",
                    proporcao_video=item.cfg.get("flow_proporcao_video", "") or "",
                )
            salvar_sessao(self.contexto, self.conta)  # login confirmado -> guarda a sessão
        if item.tipo == "animar":
            o = item.opcoes
            urls = animar_imagem(self.pagina, item.imagem, item.prompt, item.timeout_s,
                                 modelo=o.get("modelo") or "Omni 1.1 Flash", resolucao=o.get("resolucao") or "720p",
                                 duracao=o.get("duracao") or "4s", proporcao=o.get("proporcao") or "9:16",
                                 palavras_limite=item.cfg.get("flow_palavras_limite", "") or "", ignorar=self.vistas)
            self.vistas.update(urls)
            baixar_videos(self.contexto, self.pagina, urls[-1:], item.prompt, item.chave)
            return
        definir_modo_agente(self.pagina, True)  # depois de animar, o agente ficou desligado
        if item.tipo == "video":
            urls = gerar_videos(self.pagina, item.prompt, item.timeout_s, ignorar=self.vistas,
                                palavras_limite=item.cfg.get("flow_palavras_limite", "") or "",
                                seletor=item.cfg.get("flow_seletor_video", "") or "")
            self.vistas.update(urls)
            baixar_videos(self.contexto, self.pagina, urls, item.prompt, item.chave)
            return
        urls = gerar_imagens(self.pagina, item.prompt, item.timeout_s, ignorar=self.vistas,
                             palavras_limite=item.cfg.get("flow_palavras_limite", "") or "")
        self.vistas.update(urls)
        baixar_imagens(self.contexto, urls, item.prompt, item.chave)

    def _gerar_direto(self, item: _Pedido) -> None:
        """🎬 Um pedido pelo modo direto (flow_direto): projeto preparado UMA vez (agente configurado e desligado),
        depois cada pedido configura a caixa, escreve, gera e espera o bloco novo."""
        from googleflow import flow_direto as fd
        config_projeto = _config_do_projeto(item.cfg)
        if self.pagina is not None and getattr(self, "config_projeto", None) not in (None, config_projeto):
            self._fechar_pagina()
        try:
            if self.pagina is None:
                agente = agente_da_cfg(item.cfg) if item.cfg.get("flow_configurar_projeto", True) else None
                self.pagina = fd.preparar_projeto(self.contexto, FLOW_URL, self.headless, agente)
                self.config_projeto = config_projeto
                salvar_sessao(self.contexto, self.conta)
            trab = trabalho_direto(item.tipo, item.prompt, item.cfg, item.opcoes, item.imagem)
            midias = fd.gerar_um(self.pagina, trab, timeout_s=item.timeout_s)
        except fd.FlowPassoErro as exc:
            raise erro_do_passo(exc) from exc
        urls = [m["url"] for m in midias]
        if not urls:
            raise GoogleFlowError("O Flow terminou mas não apareceu nenhuma mídia nova no projeto.")
        if item.tipo in ("video", "animar"):
            baixar_videos(self.contexto, self.pagina, urls[:1], item.prompt, item.chave)
        else:
            try:
                baixar_imagens(self.contexto, [_url_original(urls[0])], item.prompt, item.chave)
            except GoogleFlowError:
                baixar_imagens(self.contexto, urls[:1], item.prompt, item.chave)

    # ------------------------------------------------------------ lote em várias abas
    def _nova_aba_projeto(self, cfg: Dict[str, Any]):
        if modo_direto(cfg):
            from googleflow import flow_direto as fd
            try:
                pagina = fd.preparar_projeto(self.contexto, FLOW_URL, self.headless,
                                             agente_da_cfg(cfg) if cfg.get("flow_configurar_projeto", True) else None)
            except fd.FlowPassoErro as exc:
                raise erro_do_passo(exc) from exc
            salvar_sessao(self.contexto, self.conta)
            return pagina
        pagina = abrir_novo_projeto(self.contexto, headless=self.headless)
        if cfg.get("flow_janela_compacta", True):
            try:  # o layout compacto (estreito) do Flow — o que funcionou nos testes do usuário
                pagina.set_viewport_size({"width": 520, "height": 900})
            except Exception:  # noqa: BLE001
                pass
        # NÃO abre "Configurações do agente": no modo direto o modelo/proporção/x1 são escolhidos
        # na própria caixa a cada pedido. Se o Flow abrir esse painel sozinho, salva e fecha.
        fechar_config_agente(pagina)
        salvar_sessao(self.contexto, self.conta)
        return pagina

    def _executar_lote(self, item: _Pedido) -> None:
        """Atende uma FILA de trabalhos (imagem / animação) com até N abas do Flow
        ao mesmo tempo — cada aba é um projeto. Tudo nesta thread: enquanto uma aba
        espera o Flow, outra recebe o próximo pedido (com um intervalo aleatório
        entre um envio e outro). A fila pode crescer enquanto roda."""
        import random
        o = item.opcoes
        fila = o["fila"]
        evento = o.get("evento") or (lambda _d: None)
        cancelar = o.get("cancelar") or (lambda: False)
        n_abas = max(1, min(4, int(o.get("abas") or 2)))
        cd_min, cd_max = o.get("cooldown") or (2.0, 9.0)
        limite_txt = item.cfg.get("flow_palavras_limite", "") or ""
        abas: List[Dict[str, Any]] = getattr(self, "abas_lote", None) or []
        self.abas_lote = abas
        proximo_envio = 0.0
        limite: Optional[BaseException] = None
        pasta_ao_vivo().mkdir(parents=True, exist_ok=True)

        def _ev(**d):
            try:
                evento(d)
            except Exception:  # noqa: BLE001 -- callback nunca derruba o navegador
                pass

        def _descartar(aba, motivo):
            if aba.get("pagina") is not None:
                caminho = salvar_diagnostico(aba["pagina"], motivo)
                try:
                    aba["pagina"].close()
                except Exception:  # noqa: BLE001
                    pass
                aba["pagina"] = None
                return caminho
            return None

        def _foto(aba):
            if aba.get("pagina") is None or time.monotonic() - aba.get("foto_em", 0) < 3.0:
                return
            aba["foto_em"] = time.monotonic()
            try:
                aba["pagina"].screenshot(path=str(pasta_ao_vivo() / f"aba_{aba['n']}.jpg"), type="jpeg", quality=55)
            except Exception:  # noqa: BLE001
                pass

        try:
            while True:
                ocupadas = [a for a in abas if a.get("trab")]
                parar_envio = cancelar() or limite is not None
                if not ocupadas and (not fila or parar_envio):
                    break
                # ---- envia o próximo trabalho numa aba livre
                if fila and not parar_envio and time.monotonic() >= proximo_envio:
                    livre = next((a for a in abas if not a.get("trab")), None)
                    if livre is None and len(abas) < n_abas:
                        livre = {"n": len(abas) + 1, "pagina": None, "trab": None, "vistas": set(), "midias": set()}
                        abas.append(livre)
                    if livre is not None:
                        # a aba pega primeiro a animação cujo frame foi gerado NELA (a imagem já está naquele
                        # projeto: escolhe da lista, sem enviar arquivo); evita pegar as que são de outra aba
                        def _de(t, mids):
                            return t.get("tipo") == "animar" and t.get("media_id") and t.get("media_id") in mids
                        minhas = livre.get("midias", set())
                        outras = set().union(*[a.get("midias", set()) for a in abas if a is not livre])
                        idx = next((k for k, t in enumerate(fila) if _de(t, minhas)), None)
                        if idx is None:
                            idx = next((k for k, t in enumerate(fila) if not _de(t, outras)), 0)
                        trab = fila[idx]
                        del fila[idx]
                        if not trab.get("forcar") and arquivo_do_cache(trab):
                            _ev(tipo="fim", id=trab.get("id"), trab=trab, arquivo=arquivo_do_cache(trab), aba=None, cache=True)
                            continue
                        try:
                            if livre["pagina"] is None:
                                _ev(tipo="aba", aba=livre["n"], estado="abrindo um projeto novo no Flow")
                                livre["pagina"] = self._nova_aba_projeto(item.cfg)
                                livre["vistas"], livre["midias"] = set(), set()
                            _ev(tipo="inicio", id=trab.get("id"), trab=trab, aba=livre["n"])
                            livre["estado"] = (submeter_direto(livre["pagina"], trab, item.cfg) if modo_direto(item.cfg)
                                               else submeter_trabalho(livre["pagina"], trab, limite_txt))
                            livre["trab"], livre["t0"] = trab, time.monotonic()
                            _ev(tipo="aba", aba=livre["n"], estado=("animando" if trab["tipo"] == "animar" else "gerando imagem")
                                + f" · {trab.get('rotulo') or trab.get('id')}")
                        except GoogleFlowLimitReached as exc:
                            limite = exc
                            fila.appendleft(trab)
                        except GoogleFlowLoginRequired:
                            fila.appendleft(trab)
                            raise
                        except Exception as exc:  # noqa: BLE001
                            diag = _descartar(livre, f"{type(exc).__name__}: {exc}")
                            tentativas = int(trab.get("_tentativas") or 0) + 1
                            if isinstance(exc, _AntesDeGerar) and tentativas < 3:
                                # nada foi gerado (nem cobrado): tenta de novo num projeto novo
                                trab["_tentativas"] = tentativas
                                fila.appendleft(trab)
                                _ev(tipo="aba", aba=livre["n"], estado=f"tentando de novo ({tentativas + 1}/3) num projeto novo: {str(exc)[:120]}")
                            else:
                                _ev(tipo="erro", id=trab.get("id"), trab=trab, aba=livre["n"],
                                    erro=str(exc) + (f" (depois de {tentativas} tentativas)" if tentativas > 1 else "")
                                    + (_aviso_diag(diag) if diag else ""))
                        espera = random.uniform(float(cd_min), float(cd_max))
                        proximo_envio = time.monotonic() + espera
                        if fila:
                            _ev(tipo="cooldown", segundos=round(espera, 1))
                # ---- confere as abas que estão gerando
                for aba in abas:
                    trab = aba.get("trab")
                    if not trab:
                        _foto(aba)
                        continue
                    try:
                        urls = (checar_direto(aba["pagina"], aba["estado"]) if aba["estado"].get("direto")
                                else checar_trabalho(aba["pagina"], aba["estado"], aba["vistas"], limite_txt))
                        limite_s = max(int(item.timeout_s or 0), TIMEOUT_VIDEO_MIN_S) if trab["tipo"] == "animar" else TIMEOUT_IMAGEM_LOTE_S
                        if urls:
                            aba["vistas"].update(urls)
                            chave = trab["chave"]
                            media_id = ""
                            if trab["tipo"] == "animar":
                                baixar_videos(self.contexto, aba["pagina"], urls[-1:], trab["prompt"], chave)
                            else:
                                try:
                                    baixar_imagens(self.contexto, [_url_original(urls[-1])], trab["prompt"], chave)
                                except GoogleFlowError:
                                    baixar_imagens(self.contexto, urls[-1:], trab["prompt"], chave)
                                media_id = media_id_da_url(urls[-1])
                                if media_id:
                                    aba.setdefault("midias", set()).add(media_id)
                            aba["trab"] = None
                            _ev(tipo="fim", id=trab.get("id"), trab=trab, arquivo=arquivo_do_cache(trab), aba=aba["n"],
                                segundos=round(time.monotonic() - aba["t0"]), media_id=media_id,
                                reaproveitou_frame=bool((aba.get("estado") or {}).get("reaproveitou")))
                            _ev(tipo="aba", aba=aba["n"], estado="livre")
                        elif time.monotonic() - aba["t0"] > limite_s:
                            raise GoogleFlowError(f"Tempo esgotado ({limite_s}s) esperando o Flow.")
                    except GoogleFlowLimitReached as exc:
                        limite = exc
                        fila.appendleft(trab)
                        aba["trab"] = None
                    except Exception as exc:  # noqa: BLE001
                        aba["trab"] = None
                        diag = _descartar(aba, f"{type(exc).__name__}: {exc}")
                        _ev(tipo="erro", id=trab.get("id"), trab=trab, aba=aba["n"],
                            erro=str(exc) + (_aviso_diag(diag) if diag else ""))
                    _foto(aba)
                time.sleep(PAUSA_POLLING_S)
        finally:
            for aba in abas:
                if aba.get("trab"):  # interrompido no meio: volta pra fila
                    fila.appendleft(aba["trab"])
                    aba["trab"] = None
            if limite is not None or cancelar():
                for aba in abas:
                    _descartar(aba, "fim do lote")
                abas.clear()
        if limite is not None:
            _ev(tipo="limite", erro=str(limite))
            raise limite

    def _apos_falha(self, exc: BaseException) -> None:
        """A conversa pode ter ficado num estado estranho: descarta e recomeça num
        projeto novo no próximo pedido. Só fecha o navegador se o erro for de
        login ou inesperado (ex: o usuário fechou a janela)."""
        pagina = self.pagina or getattr(exc.__cause__, "page", None)  # modo direto: a aba onde o passo falhou
        if pagina is not None and not isinstance(exc, GoogleFlowLoginRequired):
            caminho = salvar_diagnostico(pagina, f"{type(exc).__name__}: {exc}")
            if caminho and isinstance(exc, GoogleFlowError):
                exc.args = (f"{exc}{_aviso_diag(caminho)}",)
        self._fechar_pagina()
        if isinstance(exc, GoogleFlowLoginRequired) or not isinstance(exc, GoogleFlowError):
            self._fechar_contexto()

    def _fechar_pagina(self) -> None:
        if self.pagina is not None:
            try:
                self.pagina.close()
            except Exception:  # noqa: BLE001
                pass
            self.pagina = None

    def _fechar_contexto(self) -> None:
        if self.contexto is not None:
            salvar_sessao(self.contexto, self.conta or CONTA_PADRAO)
            if self.fechar_contexto:
                try:
                    self.contexto.close()
                except Exception:  # noqa: BLE001
                    pass
            self.contexto = None
        self.conta = None

    def _fechar_tudo(self) -> None:
        for aba in getattr(self, "abas_lote", None) or []:
            try:
                if aba.get("pagina") is not None:
                    aba["pagina"].close()
            except Exception:  # noqa: BLE001
                pass
        self.abas_lote = []
        self._fechar_pagina()
        self._fechar_contexto()


def _enviar(chave, cfg: Dict[str, Any], fabrica, pedido: _Pedido) -> None:
    """Põe o pedido na fila da sessão; cria a sessão se não houver (ou troca
    por uma nova se a configuração do navegador mudou — a antiga termina o que
    já está na fila e fecha)."""
    global _TRABALHADOR
    with _REG_LOCK:
        t = _TRABALHADOR
        if t is not None and (t.encerrado or t.chave != chave):
            if not t.encerrado:
                t.parar()
            t = None
        if t is None:
            t = _Trabalhador(chave, cfg, fabrica)
            _TRABALHADOR = t
            t.start()
        t.fila.put(pedido)


def encerrar_sessao(timeout: float = 30.0) -> None:
    """Fecha o navegador da sessão de geração (termina os pedidos já na fila)."""
    global _TRABALHADOR
    with _REG_LOCK:
        t, _TRABALHADOR = _TRABALHADOR, None
        if t is not None and not t.encerrado:
            t.parar()
    if t is not None:
        t.join(timeout)
