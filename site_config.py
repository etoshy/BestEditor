"""
site_config.py
================

Configuração central do site, editável pela página /settings e usada
automaticamente por `video_assembler.py` na hora de montar o vídeo.
Persistida em `site_config.json` na raiz do projeto.

Campos
------
orientation: "16:9" (paisagem, padrão pra YouTube normal) ou "9:16"
    (retrato, pra Shorts/Reels/TikTok) — define a resolução de SAÍDA
    do vídeo final (a moldura que tudo é ajustado pra caber). Não
    controla mais a orientação dos vídeos BUSCADOS por padrão — ver
    `search_orientation` abaixo pra isso.

search_orientation: "match_export" (padrão) | "16:9" | "9:16" | "mixed"
    — controla qual orientação é pedida como filtro de busca pros
    provedores que suportam isso (Pexels, Pixabay, Mixkit, Magnific,
    Anime Pexels Local), INDEPENDENTE da orientação de exportação:
        "match_export": busca sempre na mesma orientação da exportação
            (comportamento de sempre, antes desse campo existir).
        "16:9" / "9:16": força essa orientação na busca, mesmo que a
            exportação seja a outra (o `aspect_fill` cuida de encaixar
            o resultado na moldura final).
        "mixed": não aplica nenhum filtro de orientação na busca —
            aceita o que vier (paisagem ou retrato, misturados entre
            trechos diferentes do mesmo vídeo), deixando o `aspect_fill`
            (preto/mosaico/zoom) lidar com a diferença de proporção em
            cada trecho individualmente.

provider_priority: ordem de preferência das fontes. Usada como
    fallback: se o provedor que a IA escolheu pra um segmento não
    conseguir entregar nada (nem com os termos alternativos), tenta o
    próximo da lista antes de desistir do segmento.

pexels_api_fallback_to_browser: se a API oficial do Pexels falhar (chave
    inválida, todas as chaves em rate limit, etc.), usa automaticamente
    o scraping por navegador como alternativa em vez de falhar o
    segmento inteiro.

browser_visible: True = mostra a janela do navegador (útil pra depurar);
    False (padrão) = navegador OCULTO (sem janela). Vale pra TODOS os
    processos que abrem navegador: buscas por scraping nos bancos (Chrome
    via Selenium), captura de página (Playwright) e a geração de imagens
    no Google Flow. Na tela de Configurações aparece invertido, como
    "Ocultar o navegador" (marcado = browser_visible False). Também pode
    ser sobrescrito por vídeo, na página do prompt (ver `job["cfg_overrides"]`
    em app.py). Exceção prática: o PRIMEIRO login no Google Flow precisa de
    janela visível (botão "Fazer login no Flow" nas Configurações) — depois
    disso a sessão fica salva e o modo oculto funciona.

flow_navegador / flow_exe / flow_timeout_seconds: ajustes do provedor
    "flow" (geração de imagens com IA no Google Flow, ver
    `toolkit/googleflow/googleflow_client.py`). `flow_navegador`: "auto"
    (padrão, tenta Chrome, Edge, Chromium, Firefox, WebKit), um deles, ou
    "cdp" (conecta a um Chrome seu já aberto com --remote-debugging-port=9222;
    nesse modo a janela é a sua, "ocultar" não se aplica). `flow_exe`:
    caminho de um navegador baseado em Chromium (Brave, Opera, Vivaldi...),
    vazio = não usar. `flow_timeout_seconds`: quanto esperar UMA geração.
    O Flow usa UM navegador e UMA conversa pro vídeo inteiro (as imagens são
    geradas uma atrás da outra no mesmo projeto). `flow_configurar_projeto`
    (padrão True): ao criar o projeto, abre as configurações do agente e escolhe
    "Confirmar antes de gerar = Nunca" + "1 imagem" (sem isso o agente para
    pedindo confirmação a cada imagem). `flow_seletor_configuracoes`: seletor
    CSS do botão que abre esse painel — só preencha se o site não achar sozinho
    (o erro lista os botões da tela pra você escolher).
    `flow_modelo_video`: nome exato do modelo padrão pra geração de vídeo do projeto
    (ex: "Veo 3.1 - Lite", como aparece no seletor do Flow) -- configurado junto com
    o resto (Confirmar=Nunca, x1 de imagem, x1 de vídeo) na primeira vez que uma
    conta usa o Flow. Vazio = não mexe no modelo (fica o que o Flow já tiver como
    padrão). O site ainda não GERA vídeo pelo Flow (só imagem) -- isso aqui deixa
    o projeto configurado do jeito certo pra quando essa capacidade existir, e
    também ajuda quem usa o Flow por fora do site com a mesma conta.

    VÁRIAS CONTAS: as contas Google ficam em `flow_dados/contas.json` (cada uma com o
    seu perfil de navegador; gerenciadas na tela de Configurações). Quando o Flow
    avisa que o limite acabou, a conta fica "esgotada" por `flow_horas_ate_liberar`
    horas (padrão 24 — confirmado pelo usuário: é exatamente esse o tempo que o
    Google leva pra liberar a conta de novo) e o site troca pra próxima.
    `flow_palavras_limite`: palavras EXTRAS (separadas por vírgula) que, na
    resposta do Flow, indicam limite esgotado.

browser_shared_across_providers: True = usa UM único navegador pra
    TODOS os provedores da montagem (a economia de recursos mais
    agressiva — só funciona sequencial entre provedores). False
    (padrão) = um navegador por provedor, reaproveitado entre os
    segmentos daquele provedor.

browser_mode: "reuse_session" (padrão) = mantém a mesma sessão/aba do
    navegador entre um download e o próximo, só muda o termo de busca;
    "close_each_download" = fecha e abre um navegador novo depois de
    CADA vídeo baixado (mais lento e pesado, mas isola cada download
    por completo — útil se estiver suspeitando de algum estado
    "grudado" entre buscas).

export_quality: "480p" | "720p" | "1080p" | "1440p" | "2160p" — altura
    de exportação do vídeo final. A largura é calculada a partir da
    `orientation` pra manter a proporção (ex: 720p em 16:9 = 1280x720;
    720p em 9:16 = 720x1280).

clip_trim_position: quando um vídeo baixado é mais longo que o segmento
    que ele vai preencher, de onde cortar o trecho usado:
    "start" (padrão, do começo do vídeo), "middle" (do meio), ou
    "random" (um ponto aleatório válido) — vídeos de banco de imagem
    costumam ter a parte mais "parada"/genérica no início, então "middle"
    ou "random" às vezes dá um resultado visualmente melhor.

magnific_only_free: True (padrão) = só busca vídeos gratuitos no
    Magnific (nunca premium/com marca d'água) — evita o problema na
    raiz, em vez de aceitar baixar com marca d'água como último recurso.

evitar_repeticao_clipes: True (padrão) = nunca deixa a MESMA cena/foto
    aparecer em dois trechos diferentes do vídeo (nas prévias E na
    montagem final; só fotos da Wikipedia podem repetir — ver
    `video_assembler.NO_REPEAT_EXEMPT_PROVIDERS`) — se um trecho
    tentar usar um vídeo/foto que outro trecho já usou, pula pro
    próximo resultado da busca automaticamente (só recorre a repetir se
    a busca genuinamente esgotar sem achar nada novo, em vez de deixar
    o trecho sem mídia nenhuma). Desligar volta ao comportamento livre
    de sempre — cada trecho escolhe o melhor resultado da busca dele,
    mesmo que ele já tenha aparecido em outro trecho antes.

buscadores_imagem_paralelo: True (padrão) = nos buscadores de imagem por
    navegador (Bing/Brave/Yandex/Startpage), cada buscador abre UM navegador
    só e pesquisa nele todos os termos que estão com ele; buscadores
    diferentes rodam ao mesmo tempo (no máximo 1 navegador por buscador).
    False = um buscador de cada vez (no máximo 1 navegador aberto no total,
    mais lento, mas o mínimo de RAM).

whisper_device: "auto" (padrão) = detecta sozinho se há uma placa de
    vídeo (GPU/CUDA) instalada e usa ela automaticamente pra transcrever
    mais rápido, sem você precisar saber o modelo da placa; "cpu" força
    processar pela CPU mesmo se houver GPU disponível (mais lento, mas
    útil se a GPU estiver com problema ou você quiser deixá-la livre pra
    outra coisa); "gpu" força usar a GPU (cai pra CPU automaticamente se
    a GPU pedida falhar ao carregar — driver quebrado, sem memória
    suficiente, etc. — em vez de travar a transcrição inteira).

provider_attempt_timeout_seconds: 25 (padrão) — quantos segundos no
    máximo esperar por UM provedor (busca + download) antes de desistir
    dele e já partir pro próximo da lista de prioridade, mesmo que esse
    provedor pudesse eventualmente responder. Sem isso, um banco lento
    ou momentaneamente travado podia segurar um segmento inteiro por
    muito tempo antes do fallback normal (que só reage a FALHA, não a
    LENTIDÃO) entrar em ação. Baixe esse valor se preferir trocar de
    banco mais rápido (mesmo arriscando desistir de um banco que ia
    funcionar, só devagar); suba se seus bancos costumam ser lentos mas
    confiáveis e você prefere esperar a trocar sem necessidade.

animepexels_online_url / animepexels_online_api_key — servidor ONLINE do
    Anime Pexels (modo servidor) e a chave de API dele. Valem pras fontes
    "animepexels_online" e "moviepexels_online"; não mexem nas locais.

animepexels_base_url: "http://localhost:5000" (padrão) — endereço do
    servidor LOCAL do "Anime Pexels Local" (o `app.py` do projeto
    original, rodando na sua própria máquina). Só precisa mudar se você
    rodar esse servidor numa porta diferente, ou em outra máquina da
    sua rede local. Esse banco é diferente dos outros 5: é um acervo de
    clipes de ANIME já processados/indexados por você mesmo, com
    termos de busca em inglês — não é um banco genérico de vídeo de
    estoque, então a IA só deveria escolher ele quando o conteúdo do
    vídeo realmente combinar com clipes de anime.

Um 8º provedor, "flow" (Google Flow — imagens geradas por IA), também
    está em `ALL_PROVIDERS`: só devolve imagens (media_type "image"), é
    lento (cada geração leva de dezenas de segundos a minutos) e usa a
    sua conta Google — por isso vem desmarcado por padrão na página
    inicial e fica por último na prioridade.

Um 7º provedor, "wikipedia", também está disponível em `ALL_PROVIDERS`:
    busca na Wikipedia/Wikimedia Commons, não precisa de chave de API
    nenhuma, mas só devolve FOTOS (não vídeo) de coisas reais/documentadas
    (pessoas, lugares, obras de arte, objetos históricos etc) — ver
    `PHOTO_SEARCH_PROVIDERS` em `prompt_builder.py` e a regra dedicada que
    `build_prompt()` inclui no prompt da IA sempre que esse provedor está
    entre os selecionados.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_config.json")

VALID_ORIENTATIONS = ("16:9", "9:16", "1:1")
VALID_BROWSER_MODES = ("reuse_session", "close_each_download")
VALID_EXPORT_QUALITIES = ("480p", "720p", "1080p", "1440p", "2160p")
VALID_TRIM_POSITIONS = ("start", "middle", "random")
VALID_WHISPER_DEVICES = ("auto", "cpu", "gpu")
# Mesma lista de video_assembler.TRANSICOES_VALIDAS -- duplicada aqui de
# propósito (em vez de importar) pra evitar import circular (video_
# assembler.py já importa DESTE módulo).
VALID_TRANSITION_TYPES = {
    "none",
    "fade", "fadeblack", "fadewhite", "fadegrays", "fadefast", "fadeslow",
    "dissolve", "pixelize", "distance", "radial", "hblur",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "wipetl", "wipetr", "wipebl", "wipebr",
    "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose", "circlecrop", "rectcrop",
    "vertopen", "vertclose", "horzopen", "horzclose",
    "diagtl", "diagtr", "diagbl", "diagbr",
    "hlslice", "hrslice", "vuslice", "vdslice",
    "hlwind", "hrwind", "vuwind", "vdwind",
    "squeezeh", "squeezev", "zoomin",
    "coverleft", "coverright", "coverup", "coverdown",
    "revealleft", "revealright", "revealup", "revealdown",
    # Transições CUSTOMIZADAS (xfade modo "custom", expressão própria —
    # ver video_assembler.TRANSICOES_CUSTOMIZADAS pros detalhes de cada uma).
    "blinds_h", "blinds_v", "checkerboard", "noise_dissolve", "iris_blur",
    "diamond_iris", "pinwheel", "wave_wipe", "fade_grayscale",
}
VALID_SEARCH_ORIENTATIONS = ("match_export", "16:9", "9:16", "1:1", "mixed")
# (valor, rótulo) de cada transição, na ordem em que aparecem nos seletores
TRANSITION_LABELS = [('none', '✂️ Corte seco'), ('fade', '🌗 Fade (mistura suave)'), ('dissolve', '💫 Dissolve'), ('fadeblack', '⬛ Fade pra preto'), ('fadewhite', '⬜ Fade pra branco'), ('wipeleft', '◀️ Wipe (esquerda)'), ('wiperight', '▶️ Wipe (direita)'), ('wipeup', '🔼 Wipe (cima)'), ('wipedown', '🔽 Wipe (baixo)'), ('slideleft', '⬅️ Slide (esquerda)'), ('slideright', '➡️ Slide (direita)'), ('slideup', '⬆️ Slide (cima)'), ('slidedown', '⬇️ Slide (baixo)'), ('circleopen', '⭕ Círculo abrindo'), ('circleclose', '⚫ Círculo fechando'), ('circlecrop', '⭕ Círculo (corte)'), ('rectcrop', '▭ Retângulo (corte)'), ('smoothleft', '〰️ Suave (esquerda)'), ('smoothright', '〰️ Suave (direita)'), ('smoothup', '〰️ Suave (cima)'), ('smoothdown', '〰️ Suave (baixo)'), ('vertopen', '↕️ Vertical abrindo'), ('vertclose', '↕️ Vertical fechando'), ('horzopen', '↔️ Horizontal abrindo'), ('horzclose', '↔️ Horizontal fechando'), ('wipetl', '↖️ Wipe (diagonal sup. esq.)'), ('wipetr', '↗️ Wipe (diagonal sup. dir.)'), ('wipebl', '↙️ Wipe (diagonal inf. esq.)'), ('wipebr', '↘️ Wipe (diagonal inf. dir.)'), ('diagtl', '◤ Diagonal (sup. esq.)'), ('diagtr', '◥ Diagonal (sup. dir.)'), ('diagbl', '◣ Diagonal (inf. esq.)'), ('diagbr', '◢ Diagonal (inf. dir.)'), ('hlslice', '▤ Fatias horizontais (esq.)'), ('hrslice', '▤ Fatias horizontais (dir.)'), ('vuslice', '▥ Fatias verticais (cima)'), ('vdslice', '▥ Fatias verticais (baixo)'), ('pixelize', '▦ Pixelizar'), ('hblur', '💨 Desfoque horizontal'), ('fadegrays', '◐ Fade (preto e branco)'), ('fadefast', '⚡ Fade rápido'), ('fadeslow', '🐢 Fade lento'), ('distance', '🌫️ Distância'), ('radial', '🕐 Radial (ponteiro)'), ('squeezeh', '↔️ Espremer horizontal'), ('squeezev', '↕️ Espremer vertical'), ('zoomin', '🔍 Zoom in'), ('hlwind', '🍃 Vento (esquerda)'), ('hrwind', '🍃 Vento (direita)'), ('vuwind', '🍃 Vento (cima)'), ('vdwind', '🍃 Vento (baixo)'), ('coverleft', '🔲 Cobrir (esquerda)'), ('coverright', '🔲 Cobrir (direita)'), ('coverup', '🔲 Cobrir (cima)'), ('coverdown', '🔲 Cobrir (baixo)'), ('revealleft', '🔳 Revelar (esquerda)'), ('revealright', '🔳 Revelar (direita)'), ('revealup', '🔳 Revelar (cima)'), ('revealdown', '🔳 Revelar (baixo)'), ('blinds_h', '🎞️ Persianas (horizontal)'), ('blinds_v', '🎞️ Persianas (vertical)'), ('checkerboard', '▦ Xadrez'), ('noise_dissolve', '✨ Dissolve com ruído'), ('iris_blur', '🔮 Íris (borda suave)'), ('diamond_iris', '💎 Íris em losango'), ('pinwheel', '🌀 Cata-vento'), ('wave_wipe', '🌊 Varredura ondulada'), ('fade_grayscale', '⚫ Dissolve com passagem por cinza')]
ALL_PROVIDERS = ["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "moviepexels", "animepexels_online", "moviepexels_online", "wikipedia", "flow", "runpod"]
# Provedores que foram ADICIONADOS depois da primeira versão da config: um
# `site_config.json` antigo (ou um formulário antigo) não os tem em
# `provider_priority` — em vez de dar erro de "faltando provedor", completa
# no fim da lista automaticamente. Provedores fora desta lista continuam
# obrigatórios (uma lista realmente incompleta ainda é rejeitada).
PROVEDORES_ADICIONADOS_DEPOIS = ("flow", "moviepexels", "animepexels_online", "moviepexels_online", "runpod")
VALID_FLOW_BROWSERS = ("auto", "chrome", "edge", "chromium", "firefox", "webkit", "cdp")

# altura de exportação, em pixels, pra cada opção de qualidade
_EXPORT_HEIGHTS = {"480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}

DEFAULT_CONFIG: Dict[str, Any] = {
    "orientation": "16:9",
    "search_orientation": "match_export",
    "export_quality": "1080p",
    "clip_trim_position": "start",
    "aspect_fill": "black",
    "trim_start_frames": 10,
    "provider_priority": list(ALL_PROVIDERS),
    "pexels_api_fallback_to_browser": True,
    "pixabay_api_fallback_to_browser": True,
    "magnific_only_free": True,
    "evitar_repeticao_clipes": True,
    "buscadores_imagem_paralelo": True,
    "templates_cena_ia": True,
    "sons_auto": {"transicoes": True, "cenas": True, "destaques": True, "editoriais": True},
    "sons_volume": 0.55,
    "transition_type": "none",
    "transition_duration": 0.6,
    "browser_visible": False,
    "browser_shared_across_providers": False,
    "browser_mode": "reuse_session",
    "preview_fetch_concurrency": 3,
    "assembly_fetch_concurrency": 3,
    "encoder_video": "auto",  # auto = usa a placa de vídeo (NVENC/QSV/AMF) se tiver; "cpu" = só libx264
    "whisper_device": "auto",
    "provider_attempt_timeout_seconds": 25,
    "animepexels_base_url": "http://localhost:5000",
    # Anime Pexels ONLINE (o mesmo projeto em modo servidor): endereço + chave de API (gerada no
    # /dashboard do servidor). Uma chave só pras duas fontes online (anime e filmes/séries).
    "animepexels_online_url": "http://84.247.133.185",
    "animepexels_online_api_key": "",
    "flow_navegador": "auto",
    "flow_exe": "",
    "flow_timeout_seconds": 300,
    "flow_configurar_projeto": True,
    "flow_seletor_configuracoes": "",
    "flow_seletor_video": "",
    # proporção das imagens do Bing/Brave/Yandex/Startpage (ver video_assembler.proporcao_dos_buscadores)
    "buscadores_proporcao": "auto",
    # 🎞️ estilo das imagens: "auto" (imagens reais, a não ser que a ficha do vídeo diga ilustração/misto),
    # "real" (sempre pula desenho/3D/vetor/recorte em fundo chapado) ou "qualquer" (não filtra) — ver estilo_imagem.py
    "estilo_imagens": "auto",
    "flow_horas_ate_liberar": 24,
    "flow_palavras_limite": "",
    "flow_modelo_video": "Veo 3.1 - Lite",
    # 🎬 v84_74: "direto" = automação nova (seletores do HTML real, passo a passo conferido); "antigo" = a de antes
    "flow_modo_automacao": "direto",
    # 🐟 Fish Audio S2 (motor de voz): "local" = servidor do fish-speech rodando à parte; "nuvem" = API paga da Fish Audio
    "fish_modo": "local",
    "fish_url": "http://127.0.0.1:8080",
    "fish_modelo": "s2-pro",
    "fish_api_key": "",        # chave da API da Fish Audio (modo nuvem) — pessoal, fica só no site_config.json
    "fish_api_key_local": "",  # --api-key do servidor local, se você subiu ele com uma
    # 🔎 IA do Google (app ia_google/, à parte): porta e quando o agente do YouTube usa ela pra achar o momento
    "ia_google_porta": 8852,
    "ia_google_youtube": "complemento",  # complemento (sem legenda / a legenda não achou) | sempre | desligado
    # 🖼️ buscador de imagem "google" (Google Imagens pelo Modo IA): imagens com o maior lado ≥ isto vêm primeiro (0 = qualquer)
    "ia_google_imagens_min_lado": 800,
    # 📺 v84_95: o nome do seu canal — os prompts de roteiro (🕵️ Modelos de vídeo, 📜 Roteiro do YouTube, 🎞️ Vídeos
    # modelados) pedem pra IA falar ele no momento certo (cada projeto pode trocar)
    "nome_canal": "",
    "voz_simultaneos": "auto",  # 🎛 quantos áudios o Gerador de voz gera ao mesmo tempo (fila_voz.py)
    "export_paralelo": "auto",
    # 🟣 Runpod (runpod_gerador.py): imagens/vídeos gerados por IA pagos do saldo da conta
    "runpod_api_key": "", "runpod_modelo_imagem": "z-image-turbo", "runpod_modelo_video": "p-video",
    "runpod_video_duracao": 5, "runpod_video_rascunho": False, "runpod_video_1080p": False,
    "runpod_reserva_flow": False,  # Flow sem crédito (vídeo/foto) → gera no Runpod antes de ir pra pesquisa  # ⚡ exportação em pedaços paralelos ("1" = desligada; export_paralelo.py)
    "voz_instancias": "1",      # ⚡ geração rápida: cópias do motor num MESMO áudio ("1" = desligada; tts_paralelo.py)
    # ⛔ lista negra de sites (lista_negra.py): imagem/vídeo de lá nunca entra (marca d'água); editável em Configurações
    "sites_bloqueados": None,
}


def _completar_provedores_novos(priority: Any) -> Any:
    """Acrescenta, no fim, os provedores de `PROVEDORES_ADICIONADOS_DEPOIS`
    que faltam numa lista `provider_priority` (só se for uma lista)."""
    if not isinstance(priority, list):
        return priority
    return priority + [p for p in PROVEDORES_ADICIONADOS_DEPOIS if p not in priority]


class SiteConfigError(Exception):
    """Configuração inválida (valor fora do permitido, etc.)."""


def load_site_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Carrega a config do disco, mesclada com os padrões (qualquer
    campo que faltar no arquivo usa o valor padrão). Nunca falha por o
    arquivo não existir.
    """
    path = path or CONFIG_PATH  # resolvido a cada chamada, não na definição da função —
    # importante pra permitir sobrescrever CONFIG_PATH (ex: em testes) e ter efeito de verdade.
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    if not os.path.exists(path):
        return merged
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return merged
    merged.update({k: v for k, v in user_config.items() if k in DEFAULT_CONFIG})
    merged["provider_priority"] = _completar_provedores_novos(merged["provider_priority"])
    return merged


def save_site_config(new_values: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    """Valida e salva a configuração. Recebe um dict parcial ou
    completo — mescla com o que já existe no disco (não apaga campos
    não mencionados). Levanta SiteConfigError com mensagem clara se
    algum valor for inválido. Retorna a configuração final salva.
    """
    path = path or CONFIG_PATH
    current = load_site_config(path)
    current.update(new_values)

    if current["orientation"] not in VALID_ORIENTATIONS:
        raise SiteConfigError(f"orientation precisa ser um de {VALID_ORIENTATIONS}, recebi {current['orientation']!r}.")

    if current["search_orientation"] not in VALID_SEARCH_ORIENTATIONS:
        raise SiteConfigError(f"search_orientation precisa ser um de {VALID_SEARCH_ORIENTATIONS}, recebi {current['search_orientation']!r}.")

    if current["export_quality"] not in VALID_EXPORT_QUALITIES:
        raise SiteConfigError(f"export_quality precisa ser um de {VALID_EXPORT_QUALITIES}, recebi {current['export_quality']!r}.")

    if current["clip_trim_position"] not in VALID_TRIM_POSITIONS:
        raise SiteConfigError(f"clip_trim_position precisa ser um de {VALID_TRIM_POSITIONS}, recebi {current['clip_trim_position']!r}.")

    if current.get("aspect_fill", "black") not in ("black", "mosaic", "zoom", "smart", "cartao"):
        raise SiteConfigError("aspect_fill precisa ser black, mosaic ou zoom.")
    try:
        trim_frames = int(current.get("trim_start_frames", 10))
    except (TypeError, ValueError):
        raise SiteConfigError("trim_start_frames precisa ser um número inteiro.")
    if not (0 <= trim_frames <= 120):
        raise SiteConfigError("trim_start_frames precisa estar entre 0 e 120.")
    current["trim_start_frames"] = trim_frames

    if current["browser_mode"] not in VALID_BROWSER_MODES:
        raise SiteConfigError(f"browser_mode precisa ser um de {VALID_BROWSER_MODES}, recebi {current['browser_mode']!r}.")

    if current["whisper_device"] not in VALID_WHISPER_DEVICES:
        raise SiteConfigError(f"whisper_device precisa ser um de {VALID_WHISPER_DEVICES}, recebi {current['whisper_device']!r}.")

    if current.get("transition_type", "none") not in VALID_TRANSITION_TYPES:
        raise SiteConfigError(f"transition_type precisa ser um de {sorted(VALID_TRANSITION_TYPES)}, recebi {current['transition_type']!r}.")
    try:
        transition_duration = float(current.get("transition_duration", 0.6))
    except (TypeError, ValueError):
        raise SiteConfigError("transition_duration precisa ser um número.")
    if not (0.05 <= transition_duration <= 5.0):
        raise SiteConfigError("transition_duration precisa estar entre 0.05 e 5.0 segundos.")
    current["transition_duration"] = transition_duration

    try:
        provider_timeout = int(current["provider_attempt_timeout_seconds"])
    except (TypeError, ValueError):
        raise SiteConfigError(f"provider_attempt_timeout_seconds precisa ser um número inteiro, recebi {current['provider_attempt_timeout_seconds']!r}.")
    if not (5 <= provider_timeout <= 300):
        raise SiteConfigError(f"provider_attempt_timeout_seconds precisa estar entre 5 e 300, recebi {provider_timeout}.")
    current["provider_attempt_timeout_seconds"] = provider_timeout

    animepexels_url = str(current.get("animepexels_base_url", "")).strip()
    if not animepexels_url.startswith(("http://", "https://")):
        raise SiteConfigError(f"animepexels_base_url precisa começar com http:// ou https://, recebi {animepexels_url!r}.")
    current["animepexels_base_url"] = animepexels_url.rstrip("/")
    online_url = str(current.get("animepexels_online_url") or "").strip() or DEFAULT_CONFIG["animepexels_online_url"]
    if not online_url.startswith(("http://", "https://")):
        raise SiteConfigError(f"animepexels_online_url precisa começar com http:// ou https://, recebi {online_url!r}.")
    current["animepexels_online_url"] = online_url.rstrip("/")
    chave = current.get("animepexels_online_api_key") or ""
    if not isinstance(chave, str) or len(chave) > 300 or any(c.isspace() for c in chave.strip()):
        raise SiteConfigError("A chave de API do Anime Pexels online parece inválida (sem espaços, até 300 caracteres).")
    current["animepexels_online_api_key"] = chave.strip()

    if current["flow_navegador"] not in VALID_FLOW_BROWSERS:
        raise SiteConfigError(f"flow_navegador precisa ser um de {VALID_FLOW_BROWSERS}, recebi {current['flow_navegador']!r}.")
    if not isinstance(current["flow_exe"], str):
        raise SiteConfigError("flow_exe precisa ser um texto (caminho do navegador, ou vazio).")
    current["flow_exe"] = current["flow_exe"].strip()
    try:
        flow_timeout = int(current["flow_timeout_seconds"])
    except (TypeError, ValueError):
        raise SiteConfigError(f"flow_timeout_seconds precisa ser um número inteiro, recebi {current['flow_timeout_seconds']!r}.")
    if not (30 <= flow_timeout <= 1800):
        raise SiteConfigError(f"flow_timeout_seconds precisa estar entre 30 e 1800, recebi {flow_timeout}.")
    current["flow_timeout_seconds"] = flow_timeout
    if not isinstance(current["flow_configurar_projeto"], bool):
        raise SiteConfigError(f"flow_configurar_projeto precisa ser verdadeiro/falso, recebi {current['flow_configurar_projeto']!r}.")
    if not isinstance(current["flow_seletor_configuracoes"], str):
        raise SiteConfigError("flow_seletor_configuracoes precisa ser um texto (seletor CSS, ou vazio).")
    current["flow_seletor_configuracoes"] = current["flow_seletor_configuracoes"].strip()
    _props = ("auto", "horizontal_quadrada", "horizontal", "quadrada", "vertical_quadrada", "vertical", "qualquer")
    if current.get("buscadores_proporcao", "auto") not in _props:
        raise SiteConfigError(f"buscadores_proporcao precisa ser um de {_props}, recebi {current.get('buscadores_proporcao')!r}.")
    if current.get("flow_modo_automacao") not in ("direto", "antigo"):
        current["flow_modo_automacao"] = "direto"
    current["nome_canal"] = " ".join(str(current.get("nome_canal") or "").split())[:80]
    if current.get("estilo_imagens") not in ("auto", "real", "qualquer"):
        current["estilo_imagens"] = "auto"
    if current.get("ia_google_youtube") not in ("complemento", "sempre", "desligado"):
        current["ia_google_youtube"] = "complemento"
    try:
        current["ia_google_porta"] = int(current.get("ia_google_porta") or 8852)
        if not 1024 <= current["ia_google_porta"] <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        current["ia_google_porta"] = 8852
    try:
        current["ia_google_imagens_min_lado"] = int(current.get("ia_google_imagens_min_lado", 800) or 0)
    except (TypeError, ValueError):
        current["ia_google_imagens_min_lado"] = 800
    if current["ia_google_imagens_min_lado"] not in (0, 800, 1280, 1920, 3840):
        current["ia_google_imagens_min_lado"] = 800
    if current.get("fish_modo") not in ("local", "nuvem"):
        current["fish_modo"] = "local"
    _fu = str(current.get("fish_url") or "").strip().rstrip("/")
    current["fish_url"] = _fu if re.fullmatch(r"https?://[^\s\"'<>]+", _fu) else "http://127.0.0.1:8080"
    current["fish_modelo"] = re.sub(r"[^a-z0-9.\-]", "", str(current.get("fish_modelo") or "s2-pro").lower())[:30] or "s2-pro"
    for _k in ("fish_api_key", "fish_api_key_local"):
        current[_k] = str(current.get(_k) or "").strip()[:200]
    if not isinstance(current.get("flow_seletor_video", ""), str):
        raise SiteConfigError("flow_seletor_video precisa ser um texto (seletor CSS, ou vazio).")
    current["flow_seletor_video"] = str(current.get("flow_seletor_video", "")).strip()
    try:
        horas_liberar = int(current["flow_horas_ate_liberar"])
    except (TypeError, ValueError):
        raise SiteConfigError(f"flow_horas_ate_liberar precisa ser um número inteiro, recebi {current['flow_horas_ate_liberar']!r}.")
    if not (1 <= horas_liberar <= 720):
        raise SiteConfigError(f"flow_horas_ate_liberar precisa estar entre 1 e 720, recebi {horas_liberar}.")
    current["flow_horas_ate_liberar"] = horas_liberar
    if not isinstance(current["flow_palavras_limite"], str):
        raise SiteConfigError("flow_palavras_limite precisa ser um texto (palavras separadas por vírgula, ou vazio).")
    current["flow_palavras_limite"] = current["flow_palavras_limite"].strip()
    if not isinstance(current["flow_modelo_video"], str):
        raise SiteConfigError("flow_modelo_video precisa ser um texto (nome do modelo, ou vazio pra não mexer nele).")
    current["flow_modelo_video"] = current["flow_modelo_video"].strip()

    try:
        concurrency = int(current["preview_fetch_concurrency"])
    except (TypeError, ValueError):
        raise SiteConfigError(f"preview_fetch_concurrency precisa ser um número inteiro, recebi {current['preview_fetch_concurrency']!r}.")
    if not (1 <= concurrency <= 10):
        raise SiteConfigError(f"preview_fetch_concurrency precisa estar entre 1 e 10, recebi {concurrency}.")
    current["preview_fetch_concurrency"] = concurrency

    try:
        assembly_concurrency = int(current["assembly_fetch_concurrency"])
    except (TypeError, ValueError):
        raise SiteConfigError(f"assembly_fetch_concurrency precisa ser um número inteiro, recebi {current['assembly_fetch_concurrency']!r}.")
    if not (1 <= assembly_concurrency <= 10):
        raise SiteConfigError(f"assembly_fetch_concurrency precisa estar entre 1 e 10, recebi {assembly_concurrency}.")
    current["assembly_fetch_concurrency"] = assembly_concurrency

    priority = _completar_provedores_novos(current["provider_priority"])
    current["provider_priority"] = priority
    if not isinstance(priority, list) or not priority:
        raise SiteConfigError("provider_priority precisa ser uma lista não-vazia.")
    invalid = [p for p in priority if p not in ALL_PROVIDERS]
    if invalid:
        raise SiteConfigError(f"provider_priority tem provedor(es) desconhecido(s): {invalid}.")
    missing = [p for p in ALL_PROVIDERS if p not in priority]
    if missing:
        raise SiteConfigError(f"provider_priority está faltando provedor(es): {missing} (inclua todos os {len(ALL_PROVIDERS)}, mesmo que no fim da lista).")

    for bool_field in ("pexels_api_fallback_to_browser", "pixabay_api_fallback_to_browser", "browser_visible", "browser_shared_across_providers", "magnific_only_free", "evitar_repeticao_clipes", "buscadores_imagem_paralelo", "templates_cena_ia"):
        if not isinstance(current[bool_field], bool):
            raise SiteConfigError(f"{bool_field} precisa ser verdadeiro/falso, recebi {current[bool_field]!r}.")

    if current["browser_shared_across_providers"] and current["browser_mode"] == "close_each_download":
        raise SiteConfigError(
            "Não dá pra combinar 'navegador compartilhado entre fontes' com 'fechar a cada "
            "download': a sessão compartilhada precisa ficar aberta pras outras fontes ainda "
            "usarem, então fechá-la a cada download não teria efeito nenhum. Escolha um dos "
            "dois: desligue o navegador compartilhado, ou mude para 'reaproveitar a mesma sessão'."
        )

    if current["browser_shared_across_providers"] and (
        current["preview_fetch_concurrency"] > 1 or current["assembly_fetch_concurrency"] > 1
    ):
        raise SiteConfigError(
            "Não dá pra combinar 'navegador compartilhado entre fontes' com buscar mais de 1 "
            "trecho ao mesmo tempo: cada busca em paralelo usa sua PRÓPRIA sessão de navegador "
            "(sessões Selenium não são seguras pra compartilhar entre buscas simultâneas) — "
            "então 'compartilhado' + concorrência > 1 na prática abre um navegador POR busca "
            "paralela, o oposto do que a opção promete. Escolha um dos dois: desligue o "
            "navegador compartilhado (e pode subir a concorrência à vontade), ou mantenha o "
            "compartilhado e deixe as duas concorrências em 1."
        )

    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    return current


def resolution_for_orientation(orientation: str, export_quality: str = "1080p") -> tuple:
    """(largura, altura) de saída pra cada orientação + qualidade,
    mantendo sempre a proporção 16:9 ou 9:16 corretamente.
    """
    height = _EXPORT_HEIGHTS.get(export_quality, 1080)
    width = int(round(height * 16 / 9))
    # garante numero par (exigido por muitos codecs de video, incluindo libx264)
    width += width % 2

    if orientation == "9:16":
        return (height, width)  # inverte largura/altura pra ficar vertical
    if orientation == "1:1":
        return (height, height)  # quadrado: o lado é a "altura" da qualidade (1080p = 1080x1080)
    return (width, height)

# Shutters do DarkPlanner (cenas_dp.SHUTTERS) — transições de obturador
from cenas_dp import ROTULOS_SHUTTER as _ROTULOS_SHUTTER  # noqa: E402
VALID_TRANSITION_TYPES |= {v for v, _r in _ROTULOS_SHUTTER}
TRANSITION_LABELS = TRANSITION_LABELS + list(_ROTULOS_SHUTTER)

# Catálogo de transições do DarkPlanner (dp_visual.py) — valores "dp:<id>"
import dp_visual as _dp_visual  # noqa: E402
_ROTULOS_DP = _dp_visual.rotulos_transicoes()
VALID_TRANSITION_TYPES |= {v for v, _r in _ROTULOS_DP}
TRANSITION_LABELS = TRANSITION_LABELS + _ROTULOS_DP
