"""
🧭 v84_405 — o mapa do site pra NOVA interface: todas as páginas, agrupadas pelo que a pessoa QUER FAZER (e não por como
o código foi crescendo), com nome em português simples, uma frase do que cada uma faz, palavras pra busca (Ctrl+K) e,
quando a ferramenta tem ajustes guardados na página de Configurações, o atalho pra eles (e o caminho de volta).

A interface antiga (base_classica.html) continua igual e selecionável em ⚙ Configurações → Aparência.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Cada item: url, icone (Font Awesome), nome, desc (uma frase, sem jargão), palavras (sinônimos pra busca),
# ativo_em (outros caminhos que contam como esta página), ajustes ([(âncora em /settings, rótulo)]).
GRUPOS: List[Dict[str, Any]] = [
    {"id": "videos", "icone": "clapperboard", "nome": "Criar vídeos", "cor": "#7c4dff",
     "desc": "Vídeos longos para o YouTube: do roteiro ou do áudio até o vídeo pronto.",
     "itens": [
         {"url": "/novo-video", "icone": "wand-magic-sparkles", "nome": "Novo vídeo",
          "desc": "Envie a narração (ou o texto) e o site monta o vídeo com cenas, legendas e música.",
          "palavras": "montar video narração audio cenas legenda novo projeto"},
         {"url": "/jobs", "icone": "photo-film", "nome": "Meus vídeos",
          "desc": "Todos os vídeos que você começou — continue de onde parou ou abra no editor.",
          "palavras": "galeria projetos jobs editor estudio continuar", "ativo_em": ["/job/", "/estudio"]},
         {"url": "/modelos-video", "icone": "user-secret", "nome": "Vídeo a partir de um modelo",
          "desc": "Copie a fórmula de um vídeo que deu certo (dossiê, react, caso) para um assunto novo.",
          "palavras": "modelos dossie react caso formula"},
         {"url": "/temas-bruto", "icone": "layer-group", "nome": "Vários vídeos de um texto",
          "desc": "Cole um texto grande e o site separa em vários temas, cada um vira um vídeo.",
          "palavras": "texto bruto temas lote varios"},
         {"url": "/modelados", "icone": "film", "nome": "Vídeos modelados",
          "desc": "Vídeos feitos em cima de um formato fixo seu, em série.",
          "palavras": "modelados serie formato"},
         {"url": "/vendas", "icone": "cart-shopping", "nome": "Vídeo de venda",
          "desc": "Vídeo que apresenta um produto, com chamada para comprar.",
          "palavras": "venda produto anuncio afiliado"},
         {"url": "/explicador", "icone": "chalkboard", "nome": "Explicador animado",
          "desc": "Vídeo didático com textos, setas e ícones animados (motion).",
          "palavras": "explicador motion animado didatico"},
         {"url": "/textos", "icone": "font", "nome": "Textos animados",
          "desc": "Frases animadas prontas para colocar por cima do vídeo.",
          "palavras": "texto animado titulo letreiro"},
         {"url": "/juntar", "icone": "object-group", "nome": "Juntar vídeos",
          "desc": "Junte vários arquivos de vídeo em um só, na ordem que quiser.",
          "palavras": "juntar unir concatenar emendar"},
         {"url": "/predefinicoes", "icone": "sliders", "nome": "Predefinições do editor",
          "desc": "Estilos salvos de legenda, efeitos e cortes para reaproveitar.",
          "palavras": "predefinicao preset estilo kit"},
     ]},
    {"id": "curtos", "icone": "mobile-screen-button", "nome": "Vídeos curtos", "cor": "#ec4899",
     "desc": "Shorts, TikTok e Reels — a partir de um link, de um vídeo longo ou do zero.",
     "itens": [
         {"url": "/curtos/link", "icone": "link", "nome": "Link → short pronto",
          "desc": "Cole o link de um vídeo e receba o short narrado, legendado e editado.",
          "palavras": "link short tiktok reels comentario reverse rage narração"},
         {"url": "/curtos", "icone": "bolt", "nome": "Meus shorts",
          "desc": "Todos os vídeos curtos e os canais deles.",
          "palavras": "curtos shorts lista canais", "ativo_em": ["/curtos/canal", "/curtos/p/"]},
         {"url": "/momentos-yt", "icone": "fire", "nome": "Cortes de um vídeo longo",
          "desc": "Acha os momentos mais assistidos de um vídeo do YouTube e vira shorts.",
          "palavras": "momentos mais vistos cortes highlights longo"},
         {"url": "/curtos/modelo/comentario", "icone": "comment-dots", "nome": "Comentário de clipe",
          "desc": "Narração por cima de um clipe viral, contando a história.",
          "palavras": "comentario clipe viral narrar"},
         {"url": "/curtos/modelo/noticia", "icone": "newspaper", "nome": "Notícia em short",
          "desc": "Short de notícia com imagens da matéria (formato Laestro).",
          "palavras": "noticia laestro jornal"},
         {"url": "/curtos/modelo/explicativo", "icone": "lightbulb", "nome": "Curiosidades",
          "desc": "Short explicativo de curiosidades, com cenas buscadas sozinho.",
          "palavras": "explicativo curiosidade fatos"},
         {"url": "/curtos/roteiro-comentario", "icone": "pen-nib", "nome": "Só o roteiro do comentário",
          "desc": "Escreve o roteiro de comentário sem montar o vídeo.",
          "palavras": "roteiro comentario texto"},
         {"url": "/shorts-ia", "icone": "dragon", "nome": "Séries com imagens de IA",
          "desc": "Shorts em capítulos com personagens e cenas geradas por IA.",
          "palavras": "shorts ia serie anime personagens", "ativo_em": ["/shorts-ia/s"]},
         {"url": "/poker", "icone": "diamond", "nome": "Poker",
          "desc": "Mesa animada, ranking e roteiros para o canal de poker.",
          "palavras": "poker mesa ranking", "ativo_em": ["/poker/doc"]},
         {"url": "/minerador", "icone": "person-digging", "nome": "Garimpar no TikTok",
          "desc": "Encontra vídeos virais do TikTok para usar como base.",
          "palavras": "minerador tiktok garimpar virais"},
         {"url": "/curtos/personalizar", "icone": "palette", "nome": "Aparência dos meus canais",
          "desc": "@ do canal, legenda, cores, voz, persona e estilo dos concorrentes de cada canal.",
          "palavras": "personalizar canal legenda fonte @ voz persona concorrentes acabamento"},
     ]},
    {"id": "ideias", "icone": "lightbulb", "nome": "Ideias e roteiros", "cor": "#f59e0b",
     "desc": "Pesquise assuntos, estude canais e escreva roteiros.",
     "itens": [
         {"url": "/roteiros-yt", "icone": "scroll", "nome": "Roteiro para YouTube",
          "desc": "Escreve o roteiro de um vídeo longo, em partes, com capítulos.",
          "palavras": "roteiro youtube escrever capitulos"},
         {"url": "/pesquisas", "icone": "magnifying-glass", "nome": "Buscador de casos",
          "desc": "Procura casos e histórias reais para virar vídeo.",
          "palavras": "casos pesquisa historias buscar"},
         {"url": "/ia-google", "icone": "magnifying-glass-chart", "nome": "Pesquisar com a IA do Google",
          "desc": "Usa o Modo IA do Google para juntar fontes e notícias de um assunto.",
          "palavras": "google modo ia pesquisa fontes noticias", "ajustes": [("ia-google", "IA do Google")]},
         {"url": "/analisador-canal", "icone": "chart-column", "nome": "Analisar um canal",
          "desc": "Mostra o que funciona num canal: vídeos que mais cresceram, temas, títulos.",
          "palavras": "analisador canal estatisticas concorrente"},
         {"url": "/niche-miner", "icone": "gem", "nome": "Garimpeiro de nichos",
          "desc": "Encontra nichos e canais pequenos que estão crescendo (Niche Miner).",
          "palavras": "niche miner nicho mineracao canais"},
         {"url": "/perfis-canal", "icone": "tv", "nome": "Perfis do meu canal",
          "desc": "Nome, intro, inscreva-se e final de cada canal seu.",
          "palavras": "perfil canal intro final inscreva", "ajustes": [("canal", "Seu canal")]},
     ]},
    {"id": "voz", "icone": "microphone", "nome": "Voz e áudio", "cor": "#10b981",
     "desc": "Narração com IA ou com a sua voz, trilha, efeitos e legendas.",
     "itens": [
         {"url": "/gerar-voz", "icone": "microphone", "nome": "Gerar narração",
          "desc": "Transforma texto em fala com vozes de IA (inclusive a sua, clonada).",
          "palavras": "tts voz narração gerar falar chatterbox turbo expressivo takes eq",
          "ajustes": [("fish", "Fish Audio")]},
         {"url": "/narracoes", "icone": "file-pen", "nome": "Roteiro para áudio",
          "desc": "Narração fala por fala, misturando IA e gravações suas.",
          "palavras": "narracoes roteiro audio falas"},
         {"url": "/gravar-voz", "icone": "microphone-lines", "nome": "Gravar minha voz",
          "desc": "Teleprompter: lê o texto na tela e grava aos poucos, com realce.",
          "palavras": "gravar microfone minha voz teleprompter"},
         {"url": "/perfis-de-voz", "icone": "id-badge", "nome": "Minhas vozes (clonagem)",
          "desc": "Guarde amostras de voz para a IA falar igual.",
          "palavras": "perfis voz clonar amostra"},
         {"url": "/sound-design", "icone": "headphones", "nome": "Trilha e efeitos (sound design)",
          "desc": "Coloca ambiente, música pela emoção, efeitos e mixagem num vídeo ou áudio.",
          "palavras": "sound design trilha musica efeitos mixagem ambiente"},
         {"url": "/transcrever", "icone": "closed-captioning", "nome": "Transcrever",
          "desc": "Vira o áudio de um vídeo em texto e legenda (.srt).",
          "palavras": "transcrever whisper legenda srt texto", "ajustes": [("whisper", "Transcrição")]},
     ]},
    {"id": "imagens", "icone": "image", "nome": "Imagens e personagens", "cor": "#3b82f6",
     "desc": "Thumbnails, identidade visual, personagens e imagens geradas por IA.",
     "itens": [
         {"url": "/thumbs-avulsas", "icone": "image", "nome": "Thumbnails",
          "desc": "Ideias e imagens de capa para qualquer vídeo, no estilo que escolher.",
          "palavras": "thumbnail capa miniatura"},
         {"url": "/marca", "icone": "palette", "nome": "Identidade visual",
          "desc": "Cores, fontes e estilo de arte do canal, usados nas imagens e thumbs.",
          "palavras": "marca identidade visual estilo arte rusty"},
         {"url": "/flow", "icone": "clapperboard", "nome": "Imagens no Google Flow",
          "desc": "Gera imagens e vídeos de IA pelo Google Flow, com várias contas.",
          "palavras": "flow google imagens ia veo imagen",
          "ajustes": [("flow", "Google Flow"), ("navegador", "Navegador")]},
         {"url": "/producao-pod", "icone": "server", "nome": "Produção no pod (GPU)",
          "desc": "Gera imagens, vídeos e vozes no seu servidor de GPU (Runpod).",
          "palavras": "pod runpod gpu producao studio", "ajustes": [("runpod", "Runpod")]},
         {"url": "/personagens-pod", "icone": "person", "nome": "Personagens",
          "desc": "Personagens fixos para aparecerem iguais em todas as cenas.",
          "palavras": "personagens consistencia"},
         {"url": "/criador-personagens", "icone": "user-pen", "nome": "Criar personagens e lugares",
          "desc": "Monta personagens e cenários do zero, com estilo e época.",
          "palavras": "criador personagens lugares cenario"},
         {"url": "/remover-fundo", "icone": "eraser", "nome": "Remover fundo",
          "desc": "Tira o fundo de imagens.", "palavras": "remover fundo recortar png"},
         {"url": "/rastrear", "icone": "crosshairs", "nome": "Seguir um objeto no vídeo",
          "desc": "Marca algo no vídeo e o site acompanha o movimento (para censura, setas…).",
          "palavras": "rastrear tracking seguir objeto"},
         {"url": "/capturar-pagina", "icone": "camera", "nome": "Print de uma página",
          "desc": "Tira print de um site ou matéria para usar no vídeo.",
          "palavras": "capturar pagina print screenshot site"},
     ]},
    {"id": "publicar", "icone": "paper-plane", "nome": "Publicar", "cor": "#ef4444",
     "desc": "Agendar no YouTube e acompanhar o que foi postado.",
     "itens": [
         {"url": "/youtube", "icone": "upload", "nome": "Enviar para o YouTube",
          "desc": "Agenda os vídeos no seu canal, com título, descrição e capa.",
          "palavras": "youtube enviar agendar upload postar"},
         {"url": "/publicacoes", "icone": "bullhorn", "nome": "Publicações",
          "desc": "O que já foi publicado e onde.", "palavras": "publicacoes postado"},
         {"url": "/assistir", "icone": "eye", "nome": "Assistir posts",
          "desc": "Cole links de posts e assista em sequência, com notas.",
          "palavras": "assistir posts links players notas"},
     ]},
    {"id": "ferramentas", "icone": "toolbox", "nome": "Ferramentas rápidas", "cor": "#64748b",
     "desc": "Baixar, cortar e achar coisas — tarefas de um clique.",
     "itens": [
         {"url": "/cortar-youtube", "icone": "scissors", "nome": "Cortar do YouTube",
          "desc": "Baixa só um trecho de um vídeo do YouTube.",
          "palavras": "cortar youtube trecho baixar", "ajustes": [("youtube-cookies", "Login do YouTube")]},
         {"url": "/redes-sociais", "icone": "download", "nome": "Baixar de outras redes",
          "desc": "Baixa vídeos do TikTok, Instagram, X, Facebook e Kwai.",
          "palavras": "baixar download tiktok instagram twitter facebook kwai"},
         {"url": "/achar-fonte", "icone": "magnifying-glass-plus", "nome": "Achar a origem de uma imagem",
          "desc": "Procura de onde veio uma imagem (Google Lens).", "palavras": "achar fonte lens origem imagem"},
         {"url": "/busca-lista", "icone": "list-check", "nome": "Buscar fotos de uma lista",
          "desc": "Uma lista de nomes vira uma pasta de fotos.", "palavras": "busca lista fotos nomes"},
         {"url": "/extrair-links-canal", "icone": "list", "nome": "Links de todos os vídeos de um canal",
          "desc": "Lista todos os links de um canal do YouTube.", "palavras": "extrair links canal lista"},
     ]},
    {"id": "ajustes", "icone": "gear", "nome": "Ajustes", "cor": "#475569",
     "desc": "Configurações, chaves de IA, contas e espaço em disco.",
     "itens": [
         {"url": "/settings", "icone": "sliders", "nome": "Configurações",
          "desc": "Formato do vídeo, bancos de imagem, IA, voz, contas e aparência — separado por abas.",
          "palavras": "configuracoes ajustes settings opcoes aparencia interface"},
         {"url": "/ia", "icone": "robot", "nome": "IA: chaves e modelos",
          "desc": "Liga a IA (Claude, Gemini…) e escolhe qual usar em cada parte do site.",
          "palavras": "ia claude gemini chave api modelos credito"},
         {"url": "/contas-google", "icone": "key", "nome": "Contas Google",
          "desc": "As contas Google que o site usa (Flow, IA do Google…).",
          "palavras": "contas google login"},
         {"url": "/espaco", "icone": "broom", "nome": "Espaço em disco",
          "desc": "Vê o que ocupa espaço e apaga o que não precisa mais.",
          "palavras": "espaco disco limpar apagar"},
         {"url": "/historico", "icone": "bell", "nome": "Avisos",
          "desc": "Tudo que terminou (ou deu erro) enquanto você fazia outra coisa.",
          "palavras": "historico avisos notificacoes sino"},
         {"url": "/guia", "icone": "book", "nome": "Guia de efeitos",
          "desc": "O que cada efeito, transição e opção do editor faz.",
          "palavras": "guia ajuda efeitos manual"},
     ]},
]

# o que fica no topo da tela inicial, em ordem: os caminhos mais comuns pra quem chega
ATALHOS_INICIO = ["/novo-video", "/curtos/link", "/gerar-voz", "/roteiros-yt", "/thumbs-avulsas", "/youtube"]


def todos() -> List[Dict[str, Any]]:
    out = []
    for g in GRUPOS:
        for it in g["itens"]:
            out.append(dict(it, grupo=g["id"], grupo_nome=g["nome"], grupo_icone=g["icone"], cor=g["cor"]))
    return out


def _bate(caminho: str, url: str) -> bool:
    return caminho == url or caminho.startswith(url.rstrip("/") + "/")


def atual(caminho: str) -> Optional[Dict[str, Any]]:
    """O item do catálogo desta página (o mais específico que bate)."""
    if caminho == "/":
        return None
    melhor, tam = None, -1
    for it in todos():
        for u in [it["url"]] + list(it.get("ativo_em") or []):
            if (_bate(caminho, u) or (u.endswith("/") and caminho.startswith(u))) and len(u) > tam:
                melhor, tam = it, len(u)
    return melhor


def busca_json() -> List[Dict[str, Any]]:
    """O índice da busca (Ctrl+K) — vai embutido na página."""
    return [{"u": it["url"], "n": it["nome"], "d": it["desc"], "g": it["grupo_nome"], "i": it["icone"],
             "p": it.get("palavras", "")} for it in todos()]


def grupo(gid: str) -> Optional[Dict[str, Any]]:
    return next((g for g in GRUPOS if g["id"] == gid), None)


def item(url: str) -> Optional[Dict[str, Any]]:
    return next((it for it in todos() if it["url"] == url), None)


# ⚙ Configurações na nova interface: cada seção (pelo título) vai pra uma aba, com o atalho pra ferramenta que usa
ABAS_AJUSTES: List[Dict[str, Any]] = [
    {"id": "geral", "nome": "Geral", "icone": "house"},
    {"id": "bancos", "nome": "Bancos de vídeo e imagem", "icone": "photo-film"},
    {"id": "ia-imagens", "nome": "Imagens por IA", "icone": "wand-magic-sparkles"},
    {"id": "voz", "nome": "Voz e legenda", "icone": "microphone"},
    {"id": "contas", "nome": "Contas e acessos", "icone": "key"},
    {"id": "aparencia", "nome": "Aparência", "icone": "palette"},
]
# (trecho do título, aba, âncora, [(url da ferramenta, nome)])
SECOES_AJUSTES: List[tuple] = [  # a ORDEM importa: o primeiro trecho que aparece no título ganha
    ("aparência", "aparencia", "aparencia", []),
    ("seu canal", "geral", "canal", [("/perfis-canal", "Perfis do meu canal")]),
    ("abertura", "geral", "vinhetas", [("/perfis-canal", "Perfis do meu canal")]),
    ("fontes de vídeo", "bancos", "fontes", [("/novo-video", "Novo vídeo")]),
    ("anime pexels online", "bancos", "animepexels-online", []),
    ("anime pexels", "bancos", "animepexels", []),
    ("ia do google", "contas", "ia-google", [("/ia-google", "Pesquisar com a IA do Google")]),
    ("navegador", "bancos", "navegador", [("/flow", "Imagens no Google Flow"), ("/capturar-pagina", "Print de uma página")]),
    ("google flow", "ia-imagens", "flow", [("/flow", "Imagens no Google Flow")]),
    ("runpod", "ia-imagens", "runpod", [("/producao-pod", "Produção no pod")]),
    ("transcrição", "voz", "whisper", [("/transcrever", "Transcrever")]),
    ("fish audio", "voz", "fish", [("/gerar-voz", "Gerar narração")]),
    ("youtube", "contas", "youtube-cookies", [("/cortar-youtube", "Cortar do YouTube"), ("/roteiros-yt", "Roteiro para YouTube")]),
    ("vídeo", "geral", "video", [("/novo-video", "Novo vídeo")]),
]


def ajustes_json() -> Dict[str, Any]:
    return {"abas": ABAS_AJUSTES,
            "secoes": [{"t": t, "aba": a, "id": i, "links": [{"u": u, "n": n} for u, n in ls]} for t, a, i, ls in SECOES_AJUSTES],
            # e o caminho contrário: ferramentas que hoje ficam no menu mas são AJUSTE
            "extras": [{"aba": "contas", "u": "/ia", "n": "IA: chaves e modelos", "d": "Liga a IA e escolhe o modelo de cada parte do site."},
                       {"aba": "contas", "u": "/contas-google", "n": "Contas Google", "d": "As contas que o site usa no Flow e na IA do Google."},
                       {"aba": "voz", "u": "/perfis-de-voz", "n": "Minhas vozes (clonagem)", "d": "Amostras de voz para a IA falar igual."},
                       {"aba": "geral", "u": "/perfis-canal", "n": "Perfis do meu canal", "d": "Intro, inscreva-se e final de cada canal."},
                       {"aba": "geral", "u": "/espaco", "n": "Espaço em disco", "d": "Apague o que não precisa mais."}]}
