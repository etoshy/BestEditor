"""Lateral de recomendados de um vídeo real (HTML enviado pelo usuário), reduzida ao que o parser lê.

Os 21 itens abaixo são os da lateral capturada: títulos, canais, selos, views e idades reais.
O HTML gerado replica a estrutura e as classes do layout ``yt-lockup-view-model`` (SVGs encurtados).
"""
from datetime import datetime, timedelta

CHECK = "check"      # selo de verificado (círculo com check)
SELO = "selo"        # selo recortado (canal oficial/verificado), aparece ao lado do nome

# id, título, canal, selo, views (texto), views (aria), quando (texto), quando (aria), duração, "Novo"
LATERAL_REAL = [
    ("iOL2SMkyn3I", "PETISTAS estão PESSIMISTAS, acham que LULA VAI PERDER e até já ENCONTRARAM um CULPADO", "ANCAPSU", CHECK, "310 mil", "310 mil visualizações", "há 14 h", "há 14 horas", "17:44", True),
    ("c8ysBDqu38E", "Безумная мощь сильнейшего! Реакция на аниме Магическая битва 1 сезон 20 серия", "akS", None, "69", "69 visualizações", "há 5 dias", "há 5 dias", "20:46", True),
    ("RkClGpnTwfU", "Explicando Letras: Peso do Ódio (Gon Berserk)", "Novatroop", SELO, "", "", "há 1 ano", "há 1 ano", "4:50", False),
    ("tJiTPwVVrXw", "7 Minutoz - MONSTRO | Johan Liebert (Monster)", "7 Minutoz", SELO, "742 mil", "742 mil visualizações", "há 2 dias", "há 2 dias", "5:08", True),
    ("7beAvWZOSVs", "Tempo | Rafão | Aki Hayakawa (Chainsaw Man)", "Rafão Music", SELO, "166 mil", "166 mil visualizações", "há 1 ano", "há 1 ano", "4:02", False),
    ("7F176Ym4J9c", "Сукуна пробудился! Магическая битва | 2 сезон 15 серия | Реакция на аниме", "Капитан Флинт", None, "179", "179 visualizações", "há 3 dias", "há 3 dias", "24:11", True),
    ("vmYEelMGVkc", "COMO será o FUTURO da PROPAGANDA no YOUTUBE? CADA vez mais PRÓXIMO da TV ABERTA? OU TUDO NOVO?", "ANCAPSU", CHECK, "33 mil", "33 mil visualizações", "há 3 h", "há 3 horas", "13:11", True),
    ("5TOmOGjFVNw", "Огляд 3 сезону Магічної битви", "Olsior reacts", None, "4,5 mil", "4,5 mil visualizações", "há 11 dias", "há 11 dias", "11:13", False),
    ("m4Rz8S1yUqU", "Estão Me Perseguindo...", "Mistere", None, "90 mil", "90 mil visualizações", "há 3 dias", "há 3 dias", "32:56", True),
    ("1Dj247BKsTI", "Rap do Scar (Fullmetal Alchemist) | Cicatrizes | Enygma 72", "Enygma", CHECK, "1,3 mi", "1,3 milhão de visualizações", "há 6 anos", "há 6 anos", "3:59", False),
    ("1fQcvMqsXII", "wojaks", "JJ", CHECK, "199 mil", "199 mil visualizações", "há 17 h", "há 17 horas", "9:52", True),
    ("XBODjgZ6hyY", 'Lain Iwakura [Serial Experiments Lain] - " Conexão " | Akkay 03', "Viktor Galvão", None, "3,4 mil", "3,4 mil visualizações", "há 2 anos", "há 2 anos", "3:24", False),
    ("6COk1VYyIlY", "Daarui - Não Tenho Inimigos (Thorfinn)", "Daarui", CHECK, "1 mi", "milhão de visualizações", "há 1 ano", "há 1 ano", "5:14", False),
    ("USfFY2ACnm4", "♪ SHINJUKU | Sukuna Vs Feiticeiros | AniRap", "AniRap", CHECK, "17 mi", "17 milhões de visualizações", "há 1 ano", "há 1 ano", "13:10", False),
    ("qODmr8S9TGw", "Montagem Zumbi | Rafão | Don Lorenzo (Blue Lock)", "Rafão Music", SELO, "756 mil", "756 mil visualizações", "há 1 ano", "há 1 ano", "3:40", False),
    ("tYBj0S08Jvg", "Procurar e Destruir | Alucard (Hellsing) | Enygma", "Enygma", CHECK, "3,2 mi", "3,2 milhões de visualizações", "há 2 anos", "há 2 anos", "4:32", False),
    ("RgQzdbRIyzA", "Lucas A.R.T. Reage a O Monstro Sem Nome | Johan Liebert (Monster) | Enygma 99", "Lucas A.R.T. CORTES", CHECK, "37 mil", "37 mil visualizações", "há 19 h", "há 19 horas", "11:41", True),
    ("kkKwzZ02tVw", "Новые силы Итадори! Реакция на аниме Магическая битва 1 сезон 19 серия", "akS", None, "49", "49 visualizações", "há 7 dias", "há 7 dias", "20:43", False),
    ("wr5tMxciPko", "Sem Conexão I Lain Iwakura (Serial Experiments Lain) I Remary ft Shooter_sz & Giu Matsu", "remary e Shooter_sz", SELO, "40 mil", "40 mil visualizações", "há 2 anos", "há 2 anos", "3:40", False),
    ("oJ4VdTVD5tA", "Rap do Kurapika (Hunter x Hunter) | Minhas Correntes | Enygma 91", "Enygma", CHECK, "2,7 mi", "2,7 milhões de visualizações", "há 5 anos", "há 5 anos", "4:48", False),
    ("dqjbcGHv3GM", "Claude + ChatGPT = R$ 202.712,82 em 90 dias com 1 canal no youtube", "Diego Alex", None, "13 mil", "13 mil visualizações", "há 16 h", "há 16 horas", "19:31", True),
]

# canal -> (url do canal, nome) usado nas páginas de vídeo simuladas
CANAIS = {
    "Mistere": "https://www.youtube.com/@mistere",
    "Olsior reacts": "https://www.youtube.com/@olsiorreacts",
    "akS": "https://www.youtube.com/@aks",
    "Капитан Флинт": "https://www.youtube.com/@%D0%9A%D0%B0%D0%BF%D0%B8%D1%82%D0%B0%D0%BD",
    "Diego Alex": "https://www.youtube.com/@diegoalex",
    "Viktor Galvão": "https://www.youtube.com/@viktorgalvao",
}

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" height="24" viewBox="0 0 24 24" width="24"><path d="M12 1C5.9 1 1 5.9 1 12s4.9 11 11 11 11-4.9 11-11S18 1 12 1Z"></path></svg>'


def _icone():
    return ('<span class="ytAttributedStringLinkInheritColor" dir="auto" style="color: rgb(96, 96, 96);"><span class="ytAttributedStringInlineBlockMod" style="margin-left: 4px;">'
            '<span class="ytIconWrapperHost ytAttributedStringImageElement ytAttributedStringImageAlignmentVerticalCenter" role="img" aria-label="" aria-hidden="true" style="height: 14px; width: 14px;">'
            f'<span class="yt-icon-shape ytSpecIconShapeHost"><div style="width: 100%; height: 100%; display: block; fill: currentcolor;">{_SVG}</div></span></span></span></span>')


def _esc(t):
    return t.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def lockup(vid, titulo, canal, selo, views, views_aria, quando, quando_aria, dur, novo, href=None, extra_badges=""):
    """Um <yt-lockup-view-model> no formato da lateral atual do YouTube."""
    href = href or f"/watch?v={vid}&amp;pp=ugUHEgVwdC1CUg%3D%3D"
    icone = _icone() if selo else ""
    if selo and canal == "remary e Shooter_sz":
        icone = _icone() + " e Shooter_sz" + _icone()
        canal_html = f'<span class="" dir="auto">remary{_icone()} </span>e Shooter_sz{_icone()}'
    else:
        canal_html = f"{_esc(canal)}{icone}"
    linha_views = ""
    if views or quando:
        partes = '<span class="ytIconWrapperHost ytContentMetadataViewModelLeadingIcon" style="width: 12px; height: 12px;"><span class="yt-icon-shape ytSpecIconShapeHost"><div>' + _SVG + "</div></span></span>"
        if views:
            partes += (f'<span class="ytAttributedStringHost ytContentMetadataViewModelMetadataText ytAttributedStringWhiteSpacePreWrap ytAttributedStringLinkInheritColor" dir="auto" aria-label="{_esc(views_aria)}" role="text">{_esc(views).replace(" ", "&nbsp;")}</span>'
                       '<span aria-hidden="true" class="ytContentMetadataViewModelDelimiter"> </span>')
        partes += (f'<span class="ytAttributedStringHost ytContentMetadataViewModelMetadataText ytContentMetadataViewModelMetadataTextLastPart ytAttributedStringWhiteSpacePreWrap ytAttributedStringLinkInheritColor" dir="auto" aria-label="{_esc(quando_aria)}" role="text">{_esc(quando)}</span>')
        linha_views = f'<div class="ytContentMetadataViewModelMetadataRow" role="group">{partes}</div>'
    badges = ""
    if novo or extra_badges:
        badges = ('<div class="ytContentMetadataViewModelMetadataRow ytContentMetadataViewModelMetadataRowMetadataRowWrap" role="group">'
                  + ('<div class="ytContentMetadataViewModelBadge"><yt-badge-view-model class="ytBadgeViewModelHost"><badge-shape class="ytBadgeShapeHost ytBadgeShapeDefault ytBadgeShapeTypography"><div class="ytBadgeShapeText">Novo</div></badge-shape></yt-badge-view-model></div>' if novo else "")
                  + extra_badges + "</div>")
    badge_dur = (f'<badge-shape class="ytBadgeShapeHost ytBadgeShapeThumbnailDefault ytBadgeShapeThumbnailBadge ytBadgeShapeTypography" role="img" aria-label="{dur}"><div class="ytBadgeShapeText">{dur}</div></badge-shape>'
                 if dur else "")
    return (
        '<yt-lockup-view-model class="ytd-item-section-renderer lockup ytLockupViewModelWrapper">'
        f'<div class="ytLockupViewModelHost ytLockupViewModelHorizontal content-id-{vid} ytLockupViewModelCompact ytLockupViewModelUpdatedCompactPadding ytLockupViewModelFlexNone">'
        f'<a href="{href}" rel="nofollow" class="ytLockupViewModelContentImage" tabindex="-1" aria-hidden="true" style="width: 62.5%;">'
        '<yt-thumbnail-view-model class="ytThumbnailViewModelHost ytThumbnailViewModelAspectRatio16By9 ytThumbnailViewModelMedium"><div class="ytThumbnailViewModelImage"><img class="ytCoreImageHost" alt=""></div>'
        f'<yt-thumbnail-bottom-overlay-view-model class="ytThumbnailBottomOverlayViewModelHost"><div class="ytThumbnailBottomOverlayViewModelBadgeContainer ytThumbnailBottomOverlayViewModelBadgeContainerMedium"><yt-thumbnail-badge-view-model class="ytThumbnailBadgeViewModelHost ytThumbnailBottomOverlayViewModelBadge">{badge_dur}</yt-thumbnail-badge-view-model></div></yt-thumbnail-bottom-overlay-view-model>'
        '</yt-thumbnail-view-model></a>'
        '<div class="ytLockupViewModelMetadata"><yt-lockup-metadata-view-model class="ytLockupMetadataViewModelHost ytLockupMetadataViewModelHorizontal">'
        f'<div class="ytLockupMetadataViewModelAvatar"><yt-decorated-avatar-view-model class="ytDecoratedAvatarViewModelHost"><yt-avatar-shape><div class="ytSpecAvatarShapeHost ytSpecAvatarShapeButton" aria-label="Acessar o canal {_esc(canal)}" role="button" tabindex="0"><img class="ytCoreImageHost" alt=""></div></yt-avatar-shape></yt-decorated-avatar-view-model></div>'
        '<div class="ytLockupMetadataViewModelTextContainer">'
        f'<h3 class="ytLockupMetadataViewModelHeadingReset" title="{_esc(titulo)}" aria-label="{_esc(titulo)}"><a href="{href}" rel="nofollow" class="ytLockupMetadataViewModelTitle" aria-label="{_esc(titulo)} 17 minutos"><span class="ytAttributedStringHost ytAttributedStringWhiteSpacePreWrap" dir="auto" role="text">{_esc(titulo)}</span></a></h3>'
        '<div class="ytLockupMetadataViewModelMetadata"><yt-content-metadata-view-model class="ytContentMetadataViewModelHost">'
        f'<div class="ytContentMetadataViewModelMetadataRow" role="group"><span class="ytAttributedStringHost ytContentMetadataViewModelMetadataText ytContentMetadataViewModelMetadataTextLastPart ytAttributedStringWhiteSpacePreWrap ytAttributedStringLinkInheritColor" dir="auto" role="text">{canal_html}</span></div>'
        f'{linha_views}{badges}</yt-content-metadata-view-model></div></div>'
        '<div class="ytLockupMetadataViewModelMenuButton"><button-view-model><button aria-label="Mais ações"></button></button-view-model></div>'
        '</yt-lockup-metadata-view-model></div></div></yt-lockup-view-model>'
    )


def lockups_reais(n=None):
    itens = LATERAL_REAL if n is None else LATERAL_REAL[:n]
    return "".join(lockup(*i) for i in itens)


def lockup_playlist():
    return lockup("PLxxxxxxxxxxxxxxxx0", "Playlist de animes", "Canal Lista", None, "", "", "", "", "", False, href="/playlist?list=PLxxxxxxxxxxxxxxxx0")


def lockup_short():
    return lockup("SHORTid0001", "Um short qualquer", "Canal Short", None, "5 mil", "5 mil visualizações", "há 1 dia", "há 1 dia", "", False, href="/shorts/SHORTid0001")


def lockup_ao_vivo():
    return lockup("LIVEid00001", "Live agora", "Canal Live", None, "1,2 mil", "1,2 mil assistindo", "", "", "", False,
                  extra_badges='<div class="ytContentMetadataViewModelBadge"><badge-shape class="ytBadgeShapeHost"><div class="ytBadgeShapeText">AO VIVO</div></badge-shape></div>')


def lockup_layout_antigo(vid="OLDVID00001", titulo="Título no layout antigo", canal="Canal Antigo", verificado=False, views="12 mil visualizações", quando="há 2 semanas", dur="10:05"):
    selo = '<ytd-badge-supported-renderer><div class="badge badge-style-type-verified"></div></ytd-badge-supported-renderer>' if verificado else ""
    return (f'<ytd-compact-video-renderer><div id="dismissible"><a id="thumbnail" class="yt-simple-endpoint" href="/watch?v={vid}"><ytd-thumbnail-overlay-time-status-renderer><span>{dur}</span></ytd-thumbnail-overlay-time-status-renderer></a>'
            f'<div class="details"><a href="/watch?v={vid}"><h3><span id="video-title" title="{titulo}">{titulo}</span></h3>'
            f'<ytd-channel-name><div id="container"><div id="text-container"><yt-formatted-string id="text">{canal}</yt-formatted-string></div></div>{selo}</ytd-channel-name>'
            f'<div id="metadata-line"><span>{views}</span><span>{quando}</span></div></a></div></div></ytd-compact-video-renderer>')


def pagina_watch(titulo, lockups, atraso_ms=0):
    """Página de vídeo com a lateral (o container do YouTube é ytd-watch-next-secondary-results-renderer)."""
    return (f"<!doctype html><html><head><title>{titulo} - YouTube</title></head><body>"
            "<video></video><div id='related'><ytd-watch-next-secondary-results-renderer>"
            f"<div id='items'><ytd-item-section-renderer><div id='contents'>{lockups}</div></ytd-item-section-renderer></div>"
            "</ytd-watch-next-secondary-results-renderer></div></body></html>")


def pagina_video_candidato(titulo, canal_url, canal_nome, dias_atras, patrocinado=False, sem_dono=False):
    """Página de um vídeo aprovado: data real (meta) + dono do canal."""
    data = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d")
    dono = "" if sem_dono else (
        f'<ytd-video-owner-renderer><a href="{canal_url.replace("https://www.youtube.com", "")}"></a><ytd-channel-name><a href="{canal_url.replace("https://www.youtube.com", "")}">{canal_nome}</a></ytd-channel-name></ytd-video-owner-renderer>'
        f'<span itemprop="author"><link itemprop="url" href="{canal_url}"><link itemprop="name" content="{canal_nome}"></span>')
    aviso = "<div>Inclui promoção paga</div>" if patrocinado else ""
    return (f'<!doctype html><html><head><title>{titulo} - YouTube</title><meta itemprop="datePublished" content="{data}"></head>'
            f"<body>{aviso}<h1>{titulo}</h1>{dono}</body></html>")
