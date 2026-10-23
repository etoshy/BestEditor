"""📦 Animação 2D — um ZIP com tudo: história, configurações, personagens (fotos, personalidade, poses prontas),
locais (fundo e frente prontos ou fotos de referência), itens/destaques, estilo de desenho, áudio e até as cenas.

O zip é lido na memória (nada é extraído pelo nome que vem dentro dele). Pastas e arquivos são reconhecidos pelo
nome — sem acento/maiúscula importar — e tudo é opcional: o que não vier, a IA cria (🤖 Fazer o plano) ou o Flow
gera (🚀). Importar num projeto que já existe JUNTA: personagem/local/item com o mesmo nome é completado, não
duplicado. O mesmo formato sai no ⬇ Exportar (pra guardar, levar pra outro PC ou reaproveitar num episódio novo).
"""
from __future__ import annotations

import io
import json
import os
import posixpath
import re
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import anime2d as A
import react_personagens as R

MAX_ZIP = 400 * 1024 * 1024  # 400 MB
MAX_ARQUIVOS = 1500
MAX_IMG = 40 * 1024 * 1024  # uma imagem
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".mp4", ".webm")

# nomes de pasta aceitos (sem acento, minúsculo)
PASTAS = {
    "personagens": ("personagens", "personagem", "characters", "character", "chars"),
    "locais": ("locais", "local", "lugares", "cenarios", "cenario", "places", "locations", "backgrounds", "fundos"),
    "itens": ("itens", "item", "objetos", "objeto", "items", "props", "destaques", "fotos"),
    "estilo": ("estilo", "estilos", "style", "styles"),
    "referencias": ("referencias", "referencia", "refs", "references"),
    "manga": ("manga", "mangas", "paginas", "pages", "capitulo", "chapter"),
    "video": ("video", "videos", "referencia_video", "video_referencia"),
}
ARQ_FICHA = {"personagens": ("personagem.json", "ficha.json", "character.json"),
             "locais": ("local.json", "ficha.json", "place.json"),
             "itens": ("item.json", "ficha.json")}
NOMES_FUNDO = ("fundo", "background", "bg", "cenario")
NOMES_FRENTE = ("frente", "foreground", "primeiro_plano", "primeiro plano")
NOMES_ITEM_IMG = ("imagem", "image", "pronta", "pronto", "final")

GUIA_ZIP = """📦 COMO MONTAR O ZIP DA ANIMAÇÃO 2D
(tudo é opcional — mande só o que você já tem; o resto a IA cria e o Flow gera)

meu_episodio.zip
├── projeto.json          ← título, estilo, formato, duração, idioma, narrador, legendas… e a história
├── historia.txt          ← (ou) a história / premissa / instruções em texto puro
├── audio.mp3             ← (opcional) o áudio pronto do episódio: vira o modo 🎧 áudio
├── cenas.json            ← (opcional) as cenas já escritas (senão: 🤖 Fazer o plano + Escrever as cenas)
├── manga/                ← (opcional) 📖 as páginas de um mangá SEU pra adaptar: 001.jpg, 002.jpg… (em ordem)
├── video/                ← (opcional) 🎬 UM vídeo de referência (cena de anime, filme, gente real): os cortes viram
│                            os quadros que a IA lê e recria com OS SEUS personagens (diga quem é quem na história)
├── adaptacao.json        ← (opcional) a adaptação mangá → anime já pronta (o ⬇ JSON da adaptação de outro projeto)
├── estilo/               ← imagens que mostram o JEITO de desenhar (vão junto em todas as gerações)
│   └── qualquer_nome.png
├── personagens/
│   └── Kenta/                    ← o nome da pasta = o nome do personagem
│       ├── personagem.json       ← personalidade, jeito de falar, aparência (inglês), gênero, idade, voz
│       ├── foto1.png, foto2.jpg  ← fotos de REFERÊNCIA (o Flow desenha o personagem a partir delas)
│       ├── design_anime.png      ← (adaptação) o design anime já feito; "design_aprovado": true no json = aprovado
│       └── poses/                ← (opcional) poses JÁ DESENHADAS — não vão pro Flow
│           ├── neutro.png            (a ⭐ principal; de pé, corpo inteiro, virado pra DIREITA)
│           ├── correndo.png          (nomes do catálogo: neutro, feliz, rindo, triste, chorando, bravo,
│           ├── correndo_b.png         assustado, surpreso, pensando, envergonhado, apontando, correndo,
│           ├── neutro_boca.png        andando, pulando, sentado, deitado, comendo, dormindo…)
│           └── escondido atras do sofa.png   (nome livre = pose nova; nas cenas use esse mesmo nome)
├── locais/
│   └── Sala/
│       ├── local.json            ← descrição + prompt_en do fundo + frente_en (objeto na frente)
│       ├── fundo.png             ← (opcional) o fundo PRONTO, vazio de pessoas, na proporção do vídeo
│       ├── frente.png            ← (opcional) a camada da frente pronta (PNG transparente: balcão, arbusto…)
│       └── ref_qualquer.jpg      ← outras imagens = REFERÊNCIA pro Flow gerar o fundo
└── itens/
    └── Vaso quebrado/
        ├── item.json             ← tipo "objeto" (aparece recortado na cena) ou "destaque" (tela cheia)
        ├── imagem.png            ← (opcional) a imagem PRONTA (objeto: PNG transparente; destaque: a foto)
        └── ref.jpg               ← outras imagens = referência

ATALHOS (também valem):
• personagens/Kenta.png  ou  personagens/Kenta.json  (arquivo solto com o nome do personagem)
• locais/Sala.png = o fundo pronto da Sala · itens/Vaso.png = a imagem pronta do Vaso
• uma pasta "referencias/" com imagens soltas: o nome do arquivo liga ao personagem/local/item de mesmo nome
• o zip pode ter uma pasta por fora (meu_episodio/…) — tanto faz

POSES PRONTAS — dicas:
• PNG com fundo TRANSPARENTE (ou fundo verde chapado #00FF00, que é recortado). Fundo branco não é recortado.
• Corpo inteiro, pés embaixo, virado pra DIREITA (o sistema espelha quando ele olha pra esquerda).
• Todas as poses do mesmo personagem no mesmo tamanho de tela — assim o “_b” (2º quadro de movimento) e a
  “_boca” (boca aberta pra fala) encaixam certinho em cima da pose.
• Sem “_boca”: a boca é gerada no Flow quando você clicar 🚀 (ou o personagem fala sem mexer a boca).

MANGÁ → ANIME:
• Com a pasta manga/, use 📖 “Ler o mangá” na página: a IA monta a adaptação (personagens do mangá → a versão anime
  de cada um, locais, itens, cenas com as páginas de cada uma) e recorta cada personagem/lugar das páginas.
• personagem.json pode ter "design_en" (a versão anime em inglês), "aparencia_manga_en" e "mudancas_anime".
• Com "design_en" o personagem passa pela etapa 🎨 design anime: gerar → você aprova → só então as poses.
• Nas cenas, "paginas": [3, 4] liga a cena às páginas (a IA escreve os momentos lendo elas) e "som" anota o efeito
  sonoro de cada momento (a busca de efeitos vem depois).

NOMES: maiúscula, acento e _ ou espaço não importam (“Mãe”, “mae”, “MAE” são o mesmo personagem).
JSON: UTF-8; campos que você não souber, deixe de fora.
"""

EXEMPLO_PROJETO = {
    "titulo": "O vaso quebrado",
    "historia": "Kenta, 5 anos, quebra o vaso favorito da mãe e tenta esconder antes que ela volte do mercado. "
                "O cachorro Bolinha só atrapalha. No final, a mãe confessa que também quebrou algo.",
    "estilo": "cartoon",
    "estilo_extra": "contornos grossos, cores chapadas",
    "proporcao": "16:9",
    "duracao_min": 0,
    "idioma": "português do Brasil",
    "narrador": True,
    "narrador_voz": "",
    "legendas": True,
    "paralaxe": True,
    "_estilos_aceitos": list(A.ESTILOS),
    "_duracao_min": "0 = automática (a IA decide pelo tamanho da história)",
}
EXEMPLO_PERSONAGEM = {
    "nome": "Kenta",
    "descricao": "menino de 5 anos, protagonista",
    "personalidade": "sapeca, mente mal, faz caretas quando está nervoso",
    "jeito_de_falar": "rápido, inventa desculpas absurdas; bordão: 'não fui eu!'",
    "aparencia_en": "5 year old boy, spiky black hair, big round eyes, red t-shirt, blue shorts, white sneakers",
    "genero": "masculino",
    "idade": "crianca",
    "voz": "",
    "cor": "#ffd54a",
    "_genero": "masculino | feminino | neutro",
    "_idade": "crianca | jovem | adulto | idoso",
    "_voz": "o código (slug) de uma voz do Gerador de voz — ou deixe vazio e escolha na página",
}
EXEMPLO_LOCAL = {
    "nome": "Sala",
    "descricao": "sala simples de uma casa japonesa, sofá azul, janela, um vaso numa mesinha",
    "prompt_en": "simple living room of a small japanese house, blue sofa, window with curtains, small table, wooden floor",
    "frente_en": "",
    "props": [{"nome": "Mesa", "prompt_en": "a low wooden table seen from the front", "camada": "frente", "x": 0.5, "y": 1.0, "w": 0.45},
              {"nome": "Sofá", "prompt_en": "a blue sofa seen from the front", "camada": "atras", "x": 0.5, "y": 0.85, "w": 0.5}],
    "lugares": [{"nome": "no sofá", "sentado": True, "descricao": "sentado no sofá, atrás da mesa", "x": 0.5, "y": 0.8, "escala": 0.9}],
    "_props": "móveis em camadas separadas: 'atras' (cadeira, sofá — atrás de quem senta) ou 'frente' (mesa, balcão). O fundo vem SEM eles. x/y/w opcionais (frações da tela; y = a base) — ajuste depois no 📐 Montar o cenário",
    "_lugares": "onde os personagens ficam além de esquerda/centro_esq/centro/centro_dir/direita; sentado=true pede pose sentada",
}
EXEMPLO_ITEM = {
    "nome": "Vaso quebrado",
    "tipo": "objeto",
    "prompt_en": "a broken blue ceramic vase in pieces on the floor",
    "personagens": [],
    "texto": "",
    "_tipo": "objeto (recortado, aparece na cena) | destaque (imagem em tela cheia num momento forte)",
    "_personagens": "quem aparece na imagem (vai a referência do design deles: mesmo cabelo e cores)",
    "_texto": "o texto ESCRITO que faz parte da cena (placa, etiqueta, bilhete) — exatamente como deve aparecer; vazio = nenhum",
}
EXEMPLO_CENAS = [
    {"titulo": "O acidente", "local": "Sala", "resumo": "Kenta brinca de bola dentro de casa e quebra o vaso.",
     "personagens": ["Kenta"],
     "momentos": [
         {"tipo": "narracao", "quem": "Narrador", "texto": "Era uma tarde tranquila. Tranquila demais.", "camera": "zoom_in",
          "em_cena": [{"personagem": "Kenta", "posicao": "centro", "pose": "feliz", "olha": "direita"}]},
         {"tipo": "acao", "quem": "Kenta", "texto": "Kenta chuta a bola e acerta o vaso", "camera": "tremida",
          "objeto": "Vaso quebrado", "duracao": 2,
          "em_cena": [{"personagem": "Kenta", "posicao": "esquerda", "pose": "correndo", "olha": "direita"}]},
         {"tipo": "fala", "quem": "Kenta", "texto": "Não fui eu!", "camera": "fixa", "som": "vaso se espatifando",
          "em_cena": [{"personagem": "Kenta", "posicao": "centro", "pose": "escondido atras do sofa", "olha": "esquerda"}]},
     ]},
]
EXEMPLO_CENAS_NOTAS = {
    "tipo": list(A.TIPOS_MOMENTO), "camera": list(A.CAMERAS), "posicao": list(A.POSICOES), "olha": ["direita", "esquerda"],
    "pose": list(A.POSES) + ["(ou o nome de uma pose pronta / uma descrição livre — vira pose nova)"],
    "objeto": "nome de um item tipo objeto", "destaque": "nome de um item tipo destaque (use tipo 'destaque')",
    "duracao": "segundos (ação/destaque; fala e narração usam o tempo da voz)",
    "tempo": "só no modo áudio: o segundo do áudio em que o momento começa",
    "som": "efeito sonoro do momento, em texto (por enquanto só anotado)",
    "plano": list(A.PLANOS) + ["(o corte de câmera: geral = o cenário todo, medio = da cintura pra cima do foco, close = o rosto, reacao = o rosto num fundo abstrato)"],
    "foco": "o nome de quem a câmera enquadra (normalmente quem fala)",
    "fundo_reacao": list(A.FUNDOS_REACAO),
    "posicao": "esquerda, centro_esq, centro, centro_dir, direita ou um dos 'lugares' do local",
    "poses_seguintes (em em_cena)": "poses em sequência dentro do momento (catálogo ou inglês curto), ex.: [\"raising the paper\", \"slamming the paper\"]",
    "paginas (na cena)": "páginas do mangá que a cena adapta (com a pasta manga/)",
}


class ZipErro(A.AnimeErro):
    pass


# ------------------------------------------------------------------ ler o zip
def _norm(s: Any) -> str:
    return R._norm(str(s or "").replace("_", " ").replace("-", " "))


def _tipo_pasta(nome: str) -> Optional[str]:
    n = _norm(nome).replace(" ", "")
    for k, nomes in PASTAS.items():
        if n in {x.replace(" ", "").replace("_", "") for x in nomes}:
            return k
    return None


def _ler_json(dados: bytes, onde: str, avisos: List[str]) -> Any:
    try:
        return json.loads(dados.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        avisos.append(f"⚠ {onde}: o JSON não abriu ({str(exc)[:80]}) — ignorei")
        return None


def _arquivos(z: zipfile.ZipFile) -> Dict[str, bytes]:
    """caminho (com / e sem a pasta de fora) → bytes. Pula pastas, lixo do Mac e arquivos ocultos."""
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > MAX_ARQUIVOS:
        raise ZipErro(f"O zip tem {len(infos)} arquivos (máximo {MAX_ARQUIVOS}).")
    if sum(i.file_size for i in infos) > MAX_ZIP:
        raise ZipErro("O zip descompactado passa de 400 MB.")
    out: Dict[str, bytes] = {}
    for i in infos:
        nome = i.filename.replace("\\", "/")
        partes = [x for x in nome.split("/") if x not in ("", ".")]
        if not partes or ".." in partes or any(x.startswith(".") for x in partes) or "__MACOSX" in partes:
            continue
        if partes[-1].lower() in ("thumbs.db", "desktop.ini"):
            continue
        if i.file_size > MAX_IMG and not partes[-1].lower().endswith(AUDIO_EXT):
            continue
        out["/".join(partes)] = z.read(i)
    # uma pasta por fora (meu_episodio/…): tira
    while out:
        tops = {k.split("/")[0] for k in out}
        if len(tops) == 1 and all("/" in k for k in out) and _tipo_pasta(next(iter(tops))) is None:
            t = next(iter(tops)) + "/"
            out = {k[len(t):]: v for k, v in out.items()}
        else:
            break
    return out


def _e_img(n: str) -> bool:
    return n.lower().endswith(IMG_EXT)


def _stem(n: str) -> str:
    return os.path.splitext(posixpath.basename(n))[0]


def _abrir_img(dados: bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(dados))
    im.load()
    return im


def ler_estrutura(arqs: Dict[str, bytes], avisos: List[str]) -> Dict[str, Any]:
    """O zip → {projeto, historia, audio, cenas, estilo[], refs[], personagens{nome: {...}}, locais{}, itens{}}."""
    e: Dict[str, Any] = {"projeto": {}, "historia": "", "audio": None, "cenas": None, "estilo": [], "refs": [],
                         "personagens": {}, "locais": {}, "itens": {}, "manga": [], "adaptacao": None, "video": None}

    def grupo(tipo: str, nome: str) -> Dict[str, Any]:
        d = e[tipo]
        k = _norm(nome)
        if k not in d:
            d[k] = {"nome": " ".join(nome.replace("_", " ").split())[:60], "ficha": {}, "refs": [], "poses": {},
                    "fundo": None, "frente": None, "imagem": None, "design": None}
        return d[k]

    for cam, dados in sorted(arqs.items()):
        partes = cam.split("/")
        base_n = partes[-1]
        low = base_n.lower()
        if len(partes) == 1:  # na raiz
            if low in ("projeto.json", "project.json", "config.json", "episodio.json"):
                e["projeto"] = _ler_json(dados, base_n, avisos) or {}
            elif low in ("adaptacao.json", "adaptation.json") or (low.startswith("adaptacao") and low.endswith(".json")):
                e["adaptacao"] = _ler_json(dados, base_n, avisos)
            elif low in ("cenas.json", "scenes.json", "roteiro.json"):
                e["cenas"] = _ler_json(dados, base_n, avisos)
            elif low.endswith((".txt", ".md")) and _norm(_stem(low)) in ("historia", "premissa", "instrucoes", "roteiro", "story", "leia me", "leiame"):
                if _norm(_stem(low)) not in ("leia me", "leiame"):
                    e["historia"] = (e["historia"] + "\n\n" if e["historia"] else "") + dados.decode("utf-8-sig", "replace").strip()
            elif low.endswith(AUDIO_EXT) and e["audio"] is None:
                e["audio"] = (base_n, dados)
            elif _e_img(low):
                e["refs"].append((base_n, dados, "", ""))
            continue
        tipo = _tipo_pasta(partes[0])
        if tipo is None:
            if _e_img(low):
                e["refs"].append((base_n, dados, "", ""))
            continue
        if tipo == "video":  # 🎬 o vídeo de referência
            if low.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")) and e["video"] is None:
                e["video"] = (base_n, dados)
            continue
        if tipo == "manga":
            if _e_img(low):
                e["manga"].append(("/".join(partes[1:]), dados))
            continue
        if tipo == "estilo":
            if _e_img(low):
                e["estilo"].append((base_n, dados))
            continue
        if tipo == "referencias":
            if _e_img(low):
                e["refs"].append((base_n, dados, "", _stem(base_n).replace("_", " ")))
            continue
        if len(partes) == 2:  # arquivo solto: personagens/Kenta.png · locais/Sala.json
            g = grupo(tipo, _stem(base_n))
            if low.endswith(".json"):
                g["ficha"] = _ler_json(dados, cam, avisos) or {}
            elif _e_img(low):
                if tipo == "personagens":
                    g["refs"].append((base_n, dados))
                elif tipo == "locais":
                    g["fundo"] = g["fundo"] or (base_n, dados)
                else:
                    g["imagem"] = g["imagem"] or (base_n, dados)
            continue
        g = grupo(tipo, partes[1])
        resto = partes[2:]
        if len(resto) >= 2 and tipo == "locais" and _norm(resto[0]) in ("props", "moveis", "movel", "camadas"):
            if _e_img(low):
                g.setdefault("props_img", {})[_stem(base_n)] = dados
            continue
        if len(resto) >= 2 and tipo == "personagens" and _norm(resto[0]) in ("poses", "pose", "quadros"):
            if _e_img(low):
                g["poses"][_stem(base_n)] = dados
            continue
        if low.endswith(".json"):
            f = _ler_json(dados, cam, avisos)
            if isinstance(f, dict):
                g["ficha"] = {**g["ficha"], **f}
            continue
        if not _e_img(low):
            continue
        st = _norm(_stem(base_n))
        if tipo == "personagens" and st in {_norm(x) for x in ("design anime", "design", "anime", "design_anime")}:
            g["design"] = (base_n, dados)
        elif tipo == "locais" and st in {_norm(x) for x in NOMES_FUNDO}:
            g["fundo"] = (base_n, dados)
        elif tipo == "locais" and st in {_norm(x) for x in NOMES_FRENTE}:
            g["frente"] = (base_n, dados)
        elif tipo == "itens" and st in {_norm(x) for x in NOMES_ITEM_IMG}:
            g["imagem"] = (base_n, dados)
        else:
            g["refs"].append((base_n, dados))
    return e


# ------------------------------------------------------------------ aplicar no projeto
def _estilo(v: Any) -> Optional[str]:
    if not v:
        return None
    n = _norm(v)
    for k, (rot, en) in A.ESTILOS.items():
        if n in (_norm(k), _norm(rot)) or _norm(k) in n or n in _norm(rot):
            return k
    return None


def _config(p: Dict[str, Any], cfg: Dict[str, Any], historia: str, avisos: List[str], novo: bool) -> None:
    if not isinstance(cfg, dict):
        return
    if cfg.get("titulo") and (novo or p["titulo"] in ("", "Animação sem título")):
        p["titulo"] = " ".join(str(cfg["titulo"]).split())[:200]
    h = str(cfg.get("historia") or cfg.get("premissa") or cfg.get("instrucoes") or "").strip()
    texto = "\n\n".join(x for x in (h, historia.strip()) if x)
    if texto:
        p["premissa"] = texto[:20000] if not p.get("premissa", "").strip() else (p["premissa"].rstrip() + "\n\n" + texto)[:20000]
    if cfg.get("estilo"):
        e = _estilo(cfg["estilo"])
        if e:
            p["estilo"] = e
        else:
            avisos.append(f"⚠ estilo “{cfg['estilo']}” não existe — use um de: {', '.join(A.ESTILOS)}")
    if cfg.get("estilo_extra"):
        p["estilo_extra"] = str(cfg["estilo_extra"])[:300]
    if cfg.get("proporcao") in A.PROPORCOES:
        p["proporcao"] = cfg["proporcao"]
    dur = cfg.get("duracao_min", cfg.get("duracao"))
    if dur not in (None, ""):
        try:
            v = float(dur)
            p["duracao_alvo"] = 0.0 if v <= 0 else max(0.5, min(40.0, v))
        except (TypeError, ValueError):
            pass
    if cfg.get("idioma"):
        p["idioma"] = str(cfg["idioma"])[:60]
    nar = cfg.get("narrador")
    if isinstance(nar, dict):
        p["narrador"] = {"ativo": bool(nar.get("ativo", True)), "voz": str(nar.get("voz") or p["narrador"].get("voz") or "")[:40]}
    elif nar is not None:
        p["narrador"]["ativo"] = bool(nar)
    if cfg.get("narrador_voz"):
        p["narrador"]["voz"] = _voz(cfg["narrador_voz"], avisos, "narrador") or p["narrador"].get("voz", "")
    for k in ("legendas", "paralaxe"):
        if k in cfg:
            p[k] = bool(cfg[k])


def _voz(v: Any, avisos: List[str], quem: str) -> str:
    v = str(v or "").strip()
    if not v:
        return ""
    vozes = A.vozes_disponiveis()
    achou = next((x for x in vozes if x.get("slug") == v), None) or next(
        (x for x in vozes if _norm(x.get("nome")) == _norm(v) or _norm(x.get("slug")) == _norm(v)), None)
    if achou:
        return achou["slug"]
    avisos.append(f"⚠ voz “{v}” ({quem}) não existe no Gerador de voz — escolha na página")
    return ""


CAMPOS_PERS = ("descricao", "personalidade", "jeito_de_falar", "aparencia_en")


def _personagem(p: Dict[str, Any], g: Dict[str, Any], avisos: List[str]) -> Dict[str, Any]:
    f = g["ficha"] if isinstance(g["ficha"], dict) else {}
    nome = " ".join(str(f.get("nome") or g["nome"]).split())[:60]
    c = next((x for x in p["personagens"] if A.R._norm(x["nome"]) == A.R._norm(nome)), None)
    if c is None:
        c = {"id": A._id("c"), "nome": nome, "refs": [], "voz": "", "pod": {}, "cor": A.CORES[len(p["personagens"]) % len(A.CORES)]}
        p["personagens"].append(c)
    aliases = {"aparencia": "aparencia_en", "appearance": "aparencia_en", "personality": "personalidade",
               "fala": "jeito_de_falar", "bordoes": "jeito_de_falar", "description": "descricao", "biblia": "personalidade"}
    for k, v in f.items():
        k2 = aliases.get(k, k)
        if k2 in CAMPOS_PERS and str(v or "").strip():
            c[k2] = " ".join(str(v).split())[:1500]
    if f.get("genero") in ("masculino", "feminino", "neutro"):
        c["genero"] = f["genero"]
    if f.get("idade") in ("crianca", "jovem", "adulto", "idoso"):
        c["idade"] = f["idade"]
    if f.get("voz"):
        c["voz"] = _voz(f["voz"], avisos, nome) or c.get("voz", "")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", str(f.get("cor") or "")):
        c["cor"] = f["cor"]
    for k in ("aparencia_manga_en", "mudancas_anime"):
        if str(f.get(k) or "").strip():
            c[k] = " ".join(str(f[k]).split())[:1500]
    if str(f.get("design_en") or "").strip():  # 📖 adaptação: a versão anime (o design passa por aprovação)
        c["design_en"] = " ".join(str(f["design_en"]).split())[:1500]
        c["aparencia_en"] = c["design_en"]
        c.setdefault("design", {})
    return c


def _local(p: Dict[str, Any], g: Dict[str, Any]) -> Dict[str, Any]:
    f = g["ficha"] if isinstance(g["ficha"], dict) else {}
    nome = " ".join(str(f.get("nome") or g["nome"]).split())[:60]
    lo = next((x for x in p["locais"] if A.R._norm(x["nome"]) == A.R._norm(nome)), None)
    if lo is None:
        lo = {"id": A._id("l"), "nome": nome, "refs": [], "img": {}, "frente": {}}
        p["locais"].append(lo)
    for k in ("descricao", "prompt_en", "frente_en"):
        if str(f.get(k) or "").strip():
            lo[k] = " ".join(str(f[k]).split())[:900]
    A.aplicar_props_lugares(lo, f)  # 🪑 móveis e lugares
    return lo


def _item(p: Dict[str, Any], g: Dict[str, Any]) -> Dict[str, Any]:
    f = g["ficha"] if isinstance(g["ficha"], dict) else {}
    nome = " ".join(str(f.get("nome") or g["nome"]).split())[:60]
    it = next((x for x in p["itens"] if A.R._norm(x["nome"]) == A.R._norm(nome)), None)
    if it is None:
        it = {"id": A._id("i"), "nome": nome, "refs": [], "img": {}, "tipo": "objeto"}
        p["itens"].append(it)
    if f.get("tipo") in ("objeto", "destaque"):
        it["tipo"] = f["tipo"]
    for k in ("prompt_en", "descricao"):
        if str(f.get(k) or "").strip():
            it[k] = " ".join(str(f[k]).split())[:900]
    A.aplicar_item_extras(p, it, f)  # quem aparece e o texto escrito
    return it


def nome_pose_arquivo(stem: str) -> Tuple[str, str, str]:
    """"correndo_b" → ("correndo", "b", "") · "neutro_boca" → ("neutro", "boca", "") · "escondido atras do sofa" →
    ("x_escondido_atras_do_sofa", "", "escondido atras do sofa"). → (nome da pose, variante, texto da pose livre)."""
    s = stem.strip()
    var = ""
    m = re.match(r"^(.*?)[ _\-](b|boca|falando|pisca|piscando)$", s, re.I)
    if m and m.group(1).strip():
        g2 = m.group(2).lower()
        s, var = m.group(1).strip(), "boca" if g2 in ("boca", "falando") else "pisca" if g2.startswith("pisca") else "b"
    n = _norm(s).replace(" ", "_")
    if n in A.POSES:
        return n, var, ""
    mb = re.match(r"^busto[ _\-]+(.+)$", s, re.I)  # 🙂 o busto (close) de uma expressão
    if mb and _norm(mb.group(1)).replace(" ", "_") in A.POSES:
        return "busto_" + _norm(mb.group(1)).replace(" ", "_"), var, ""
    livre = " ".join(s.replace("_", " ").split())
    return A.nome_pose("outra", livre), var, livre


def _preparar_pose(dados: bytes, caixa: Optional[Tuple[int, ...]] = None):
    """A imagem da pose → (PNG transparente 1200×1800 com a figura de pé embaixo, a caixa usada, avisos)."""
    from PIL import Image
    im = _abrir_img(dados)
    aviso = ""
    tem_alfa = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    if tem_alfa and im.convert("RGBA").getchannel("A").getextrema()[0] < 250:
        im = im.convert("RGBA")
    else:
        rgb = im.convert("RGB")
        px = [rgb.getpixel((x, y)) for x, y in ((2, 2), (rgb.width - 3, 2), (2, rgb.height - 3), (rgb.width - 3, rgb.height - 3))]
        if sum(1 for r, g, b in px if g > 150 and r < 120 and b < 120) >= 3:
            try:
                im = R.recortar_verde(rgb)
            except R.ReactErro:
                im = rgb.convert("RGBA")
        else:
            im = rgb.convert("RGBA")
            aviso = "sem fundo transparente"
    if caixa is not None and im.size == (caixa[4], caixa[5]):
        caixa_ = caixa  # o _b / a _boca no mesmo recorte da pose (encaixam certinho)
    else:
        bb = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox() or (0, 0, im.width, im.height)
        caixa_ = (*bb, im.width, im.height)
    x0, y0, x1, y1 = caixa_[:4]
    fig = im.crop((x0, y0, x1, y1))
    W, Hc = 1200, 1800
    k = min(Hc * 0.95 / fig.height, W * 0.95 / fig.width)
    fig = fig.resize((max(1, round(fig.width * k)), max(1, round(fig.height * k))), Image.LANCZOS)
    tela = Image.new("RGBA", (W, Hc), (0, 0, 0, 0))
    tela.paste(fig, ((W - fig.width) // 2, Hc - fig.height - round(Hc * 0.01)), fig)
    return tela, caixa_, aviso


def _importar_poses(p: Dict[str, Any], c: Dict[str, Any], poses: Dict[str, bytes], base: str, avisos: List[str]) -> int:
    """As poses prontas do zip → o projeto 🧍 do personagem (como imagens já prontas — não vão pro Flow)."""
    import personagens_pod as pp
    import secrets
    if not poses:
        return 0
    sl = R._slug(c["nome"])
    grupos: Dict[str, Dict[str, Any]] = {}
    for stem, dados in poses.items():
        nome, var, livre = nome_pose_arquivo(stem)
        g = grupos.setdefault(nome, {"livre": livre, "img": {}})
        g["img"][var] = dados
        if livre:
            g["livre"] = livre
    entradas: List[Dict[str, Any]] = []
    imagens: List[Tuple[str, Any]] = []
    for nome, g in grupos.items():
        if "" not in g["img"]:
            avisos.append(f"⚠ {c['nome']}: “{nome}_b/_boca” sem a pose “{nome}” — ignorei")
            continue
        try:
            tela, caixa, av = _preparar_pose(g["img"][""])
        except Exception:  # noqa: BLE001
            avisos.append(f"⚠ {c['nome']}: não abri a pose “{nome}”")
            continue
        if av:
            avisos.append(f"⚠ {c['nome']} · {nome}: {av} (o fundo vai aparecer — use PNG transparente ou verde)")
        en = A.POSES[nome][1] if nome in A.POSES else A.POSES[nome[6:]][1] if nome.startswith("busto_") and nome[6:] in A.POSES else g["livre"]
        arq = f"{sl}_{nome}.png"
        entradas.append({"arquivo": arq, "tipo": "pose", "prioridade": 1, "grupo": "anime2d", "mestre": nome == "neutro",
                         "descricao_pt": A.POSES[nome][0] if nome in A.POSES else g["livre"], "prompt": f"{en}.", "do_zip": True})
        imagens.append((arq, tela))
        for var, rot in (("b", "2º quadro"), ("boca", "falando (boca aberta)"), ("pisca", "piscando")):
            if var not in g["img"]:
                continue
            try:
                tv, _cx, _av = _preparar_pose(g["img"][var], caixa)
            except Exception:  # noqa: BLE001
                continue
            a2 = f"{sl}_{nome}_{var}.png"
            e2 = {"arquivo": a2, "tipo": "boca" if var == "boca" else "pose", "prioridade": 2, "grupo": "boca" if var == "boca" else "anime2d",
                  "descricao_pt": f"{en} — {rot}", "prompt": pp.PROMPT_BOCA if var == "boca" else A.PROMPT_PISCA if var == "pisca" else f"{A.QUADRO_B.get(nome, en)}.", "do_zip": True}
            if var == "boca":
                e2["base"] = arq
            else:
                e2["pose_base"] = arq
            entradas.append(e2)
            imagens.append((a2, tv))
        if g["livre"]:
            c.setdefault("poses_zip", [])
            if g["livre"] not in c["poses_zip"]:
                c["poses_zip"].append(g["livre"])
    if not imagens:
        return 0
    novos = {x["arquivo"] for x in entradas}
    proj = None
    if (c.get("pod") or {}).get("pid"):
        try:
            proj = pp.carregar(c["pod"]["pid"], base)
        except pp.PersErro:
            proj = None
    if proj is None:
        dados = A.poses_json(p, c)
        dados["poses"] = entradas
        if not any(x.get("mestre") for x in entradas):
            next(x for x in entradas if x["tipo"] == "pose")["mestre"] = True
        proj = pp.criar(f"🎞 {c['nome']} ({p['titulo'][:30]})", json.dumps(dados, ensure_ascii=False), [], base=base, motor="flow")
        c["pod"] = {"pid": proj["id"], "fase": "zip", "criado": time.time()}
    else:
        dados = proj["dados"]
        dados["poses"] = [x for x in dados["poses"] if x["arquivo"] not in novos] + entradas
        pp.trocar_json(proj["id"], json.dumps(dados, ensure_ascii=False), base)
    with pp._TRAVA:
        proj = pp.carregar(c["pod"]["pid"], base)
        d = pp._pasta(proj["id"], base)
        for arq, tela in imagens:
            local = f"{arq[:-4]}_zip_{secrets.token_hex(2)}.png"
            tela.save(os.path.join(d, "imagens", local))
            it = proj["imagens"].setdefault(arq, {"estado": "nova", "versoes": [], "atual": -1, "erro": None, "job": None})
            it["versoes"].append({"local": local, "quando": time.time(), "veio_do_zip": True})
            it.update(atual=len(it["versoes"]) - 1, estado="aprovada", erro=None, job=None)
        if not proj.get("mestre"):
            m = next((a for a, _t in imagens if a == f"{sl}_neutro.png"), None) or next(
                a for a, _t in imagens if not a.endswith(("_b.png", "_boca.png")))
            it = proj["imagens"][m]
            proj["mestre"] = {"arquivo": m, "local": it["versoes"][it["atual"]]["local"], "quando": time.time(), "bruto": None}
        pp._log(proj, f"📦 {len(imagens)} pose(s) prontas que vieram no zip da 🎞 Animação 2D")
        pp.salvar(proj, base)
    return len(imagens)


def _guardar_img_pronta(p: Dict[str, Any], st: Dict[str, Any], dados: bytes, recortar: bool, tela_cheia: bool,
                        base: str, avisos: List[str], rot: str) -> bool:
    try:
        im = _abrir_img(dados)
    except Exception:  # noqa: BLE001
        avisos.append(f"⚠ {rot}: não abri a imagem")
        return False
    A.guardar_img(p, st, im, recortar, base, origem="zip", tela_cheia=tela_cheia)
    return True


def _cenas(p: Dict[str, Any], cenas: Any, avisos: List[str]) -> Tuple[int, int]:
    if isinstance(cenas, dict):
        cenas = cenas.get("cenas")
    if not isinstance(cenas, list) or not cenas:
        return 0, 0
    lista = [s for s in cenas if isinstance(s, dict)]
    for s in lista:  # pose fora do catálogo = pose livre (a do zip com o mesmo nome, ou uma nova pro Flow)
        if not s.get("local") and p["locais"]:
            s["local"] = p["locais"][0]["nome"]
        for m in s.get("momentos") or []:
            if not isinstance(m, dict):
                continue
            for y in [m] + [y for y in m.get("em_cena") or [] if isinstance(y, dict)]:
                po = str(y.get("pose") or "").strip()
                if po and po not in A.POSES and po != "outra":
                    n = _norm(po).replace(" ", "_")
                    if n in A.POSES:
                        y["pose"] = n
                    else:
                        y["pose"], y["pose_en"] = "outra", y.get("pose_en") or po
            if not s.get("personagens"):
                s["personagens"] = []
            for y in m.get("em_cena") or []:
                if isinstance(y, dict) and y.get("personagem") and y["personagem"] not in s["personagens"]:
                    s["personagens"].append(y["personagem"])
    r = {"personagens": [], "locais": [], "itens": [],
         "cenas": [{"titulo": s.get("titulo") or f"Cena {k + 1}", "local": s.get("local") or "", "resumo": s.get("resumo") or "",
                    "personagens": s.get("personagens") or [], "inicio_audio": s.get("inicio_audio") or 0} for k, s in enumerate(lista)],
         "titulo": p["titulo"], "sinopse": "", "duracao_min": p.get("duracao_alvo") or 0}
    for s in lista:  # local que só aparece nas cenas
        if s.get("local") and not next((x for x in p["locais"] if A.R._norm(x["nome"]) == A.R._norm(s["local"])), None):
            p["locais"].append({"id": A._id("l"), "nome": " ".join(str(s["local"]).split())[:60], "refs": [], "img": {}, "frente": {}})
    A.aplicar_plano(p, r)
    for s_, x in zip(p["cenas"], lista):
        if x.get("paginas"):
            s_["paginas"] = [int(n) for n in x["paginas"] if str(n).isdigit()][:12]
        if x.get("nota_adaptacao"):
            s_["nota_adaptacao"] = " ".join(str(x["nota_adaptacao"]).split())[:600]
    momentos = 0
    for k, s in enumerate(lista):
        if s.get("momentos"):
            try:
                momentos += A.aplicar_cena(p, k, {"momentos": s["momentos"]})
            except A.AnimeErro as exc:
                avisos.append(f"⚠ cena {k + 1} ({s.get('titulo') or ''}): {exc}")
    return len(lista), momentos


def importar(pid: str, dados_zip: bytes, base: str = A._BASE, novo: bool = False) -> Dict[str, Any]:
    """📦 O zip → o projeto. → relatório {personagens, locais, itens, refs, estilo, poses, imagens, cenas, momentos, audio, avisos}."""
    if len(dados_zip) > MAX_ZIP:
        raise ZipErro("O zip passa de 400 MB.")
    try:
        z = zipfile.ZipFile(io.BytesIO(dados_zip))
    except zipfile.BadZipFile:
        raise ZipErro("Isso não é um arquivo .zip válido.")
    avisos: List[str] = []
    arqs = _arquivos(z)
    if not arqs:
        raise ZipErro("O zip está vazio.")
    e = ler_estrutura(arqs, avisos)
    rel = {"personagens": 0, "locais": 0, "itens": 0, "refs": 0, "estilo": 0, "poses": 0, "imagens": 0, "cenas": 0,
           "momentos": 0, "audio": False, "historia": False, "paginas": 0, "adaptacao": False}
    with A._TRAVA:
        p = A.carregar(pid, base)
        _config(p, e["projeto"], e["historia"], avisos, novo)
        if e["manga"]:  # 📖 as páginas do mangá (antes da adaptação: os recortes saem delas)
            import anime2d_manga as AM
            rel["paginas"] = AM.guardar_paginas(p, e["manga"], base, substituir=True)
        if e["video"]:  # 🎬 o vídeo de referência: os quadros-chave viram as páginas (+ o áudio, se o projeto.json não disser não)
            import anime2d_manga as AM
            try:
                rv = AM.guardar_video(p, e["video"][0], e["video"][1], base,
                                      usar_audio=bool((e["projeto"] or {}).get("usar_audio_do_video", True)) and not e["audio"])
                rel["paginas"] = rv["quadros"]
                rel["video"] = True
                rel["audio"] = rel.get("audio") or rv["audio"]
            except A.AnimeErro as exc:
                avisos.append(f"⚠ vídeo: {exc}")
        rel["historia"] = bool(e["historia"] or (e["projeto"] or {}).get("historia") or (e["projeto"] or {}).get("premissa"))
        pers = [(g, _personagem(p, g, avisos)) for g in e["personagens"].values()]
        locs = [(g, _local(p, g)) for g in e["locais"].values()]
        its = [(g, _item(p, g)) for g in e["itens"].values()]
        rel.update(personagens=len(pers), locais=len(locs), itens=len(its))
        # referências (o nome liga à ficha)
        for g, c in pers:
            for n, b in g["refs"]:
                try:
                    A.guardar_referencia(p, n, b, "personagem", c["nome"], "veio do zip", base)
                    rel["refs"] += 1
                except A.AnimeErro:
                    avisos.append(f"⚠ {c['nome']}: não abri {n}")
        for g, lo in locs:
            for n, b in g["refs"]:
                try:
                    A.guardar_referencia(p, n, b, "local", lo["nome"], "veio do zip", base)
                    rel["refs"] += 1
                except A.AnimeErro:
                    avisos.append(f"⚠ {lo['nome']}: não abri {n}")
        for g, it in its:
            for n, b in g["refs"]:
                try:
                    A.guardar_referencia(p, n, b, "item", it["nome"], "veio do zip", base)
                    rel["refs"] += 1
                except A.AnimeErro:
                    avisos.append(f"⚠ {it['nome']}: não abri {n}")
        for n, b in e["estilo"]:
            try:
                A.guardar_referencia(p, n, b, "estilo", "", "veio do zip", base)
                rel["estilo"] += 1
            except A.AnimeErro:
                avisos.append(f"⚠ estilo: não abri {n}")
        for n, b, _t, nome in e["refs"]:  # soltas: o nome do arquivo diz de quem é
            tipo = ("personagem" if A.achar(p["personagens"], nome) else "local" if A.achar(p["locais"], nome)
                    else "item" if A.achar(p["itens"], nome) else "estilo" if _norm(nome).startswith("estilo") else "personagem")
            try:
                A.guardar_referencia(p, n, b, tipo, nome, "veio do zip", base)
                rel["refs"] += 1
            except A.AnimeErro:
                avisos.append(f"⚠ não abri {n}")
        # imagens prontas
        for g, lo in locs:
            if g["fundo"] and _guardar_img_pronta(p, lo.setdefault("img", {}), g["fundo"][1], False, True, base, avisos, f"{lo['nome']} (fundo)"):
                rel["imagens"] += 1
            for nome_pr, dados in (g.get("props_img") or {}).items():  # 🪑 o móvel pronto (props/<nome>.png)
                pr = next((x for x in lo.get("props") or [] if R._norm(x["nome"]) == R._norm(nome_pr.replace("_", " "))), None)
                if pr is None:
                    pr = {"id": A._id("p"), "nome": nome_pr.replace("_", " ")[:60], "img": {}, "camada": "frente", "prompt_en": nome_pr}
                    lo.setdefault("props", []).append(pr)
                if _guardar_img_pronta(p, pr.setdefault("img", {}), dados, True, False, base, avisos, f"{lo['nome']} · {pr['nome']}"):
                    rel["imagens"] += 1
            if g["frente"] and _guardar_img_pronta(p, lo.setdefault("frente", {}), g["frente"][1], True, False, base, avisos, f"{lo['nome']} (frente)"):
                rel["imagens"] += 1
                if not lo.get("frente_en"):
                    lo["frente_en"] = "(imagem pronta do zip)"
        for g, c in pers:  # 🎨 o design anime que já veio (aprovado se o personagem.json disser)
            if g["design"] and _guardar_img_pronta(p, c.setdefault("design", {}), g["design"][1], False, False, base, avisos,
                                                   f"{c['nome']} (design anime)"):
                rel["imagens"] += 1
                f = g["ficha"] if isinstance(g["ficha"], dict) else {}
                if f.get("design_aprovado"):
                    c["design"]["aprovado"] = c["design"]["arquivo"]
        if isinstance(e["adaptacao"], dict):
            import anime2d_manga as AM
            try:
                ra = AM.aplicar_adaptacao(p, e["adaptacao"], base)
                rel["adaptacao"] = True
                rel["cenas"] = ra["cenas"]
            except A.AnimeErro as exc:
                avisos.append(f"⚠ adaptacao.json: {exc}")
        for g, it in its:
            if g["imagem"] and _guardar_img_pronta(p, it.setdefault("img", {}), g["imagem"][1], it.get("tipo") != "destaque",
                                                   it.get("tipo") == "destaque", base, avisos, it["nome"]):
                rel["imagens"] += 1
        A.salvar(p, base)
    # poses prontas (fora da trava do projeto: mexe no projeto 🧍)
    for g, c in pers:
        if g["poses"]:
            try:
                n = _importar_poses(p, c, g["poses"], base, avisos)
                rel["poses"] += n
            except Exception as exc:  # noqa: BLE001
                avisos.append(f"⚠ {c['nome']}: as poses não entraram ({str(exc)[:120]})")
    with A._TRAVA:
        q = A.carregar(pid, base)
        for c in p["personagens"]:  # o que mudou nas fichas durante as poses (pod, poses_zip)
            cq = next((x for x in q["personagens"] if x["id"] == c["id"]), None)
            if cq is not None:
                cq["pod"], cq["poses_zip"] = c.get("pod") or cq.get("pod") or {}, c.get("poses_zip") or cq.get("poses_zip") or []
        p = q
        if e["audio"]:
            try:
                A.guardar_audio(p, e["audio"][0], e["audio"][1], base)
                rel["audio"] = True
            except A.AnimeErro as exc:
                avisos.append(f"⚠ áudio: {exc}")
        if e["cenas"] is not None:
            try:
                rel["cenas"], rel["momentos"] = _cenas(p, e["cenas"], avisos)
            except A.AnimeErro as exc:
                avisos.append(f"⚠ cenas.json: {exc}")
        A.log(p, "📦 zip: " + resumo(rel))
        A.salvar(p, base)
    rel["avisos"] = avisos[:60]
    rel["resumo"] = resumo(rel)
    return rel


def resumo(rel: Dict[str, Any]) -> str:
    partes = []
    for k, rot in (("paginas", "página(s) de mangá"), ("personagens", "personagem(ns)"), ("poses", "pose(s) pronta(s)"), ("locais", "local(is)"), ("itens", "item(ns)"),
                   ("imagens", "imagem(ns) pronta(s)"), ("refs", "referência(s)"), ("estilo", "imagem(ns) de estilo"),
                   ("cenas", "cena(s)"), ("momentos", "momento(s)")):
        if rel.get(k):
            partes.append(f"{rel[k]} {rot}")
    if rel.get("historia"):
        partes.append("a história")
    if rel.get("audio"):
        partes.append("o áudio")
    if rel.get("adaptacao"):
        partes.append("a adaptação do mangá")
    if rel.get("video"):
        partes.append("o vídeo de referência")
    return ", ".join(partes) or "nada reconhecido"


# ------------------------------------------------------------------ exemplo e exportar
def _png_exemplo(cor: Tuple[int, int, int], tam: Tuple[int, int], transparente: bool = False, texto: str = "") -> bytes:
    from PIL import Image, ImageDraw
    if transparente:
        im = Image.new("RGBA", tam, (0, 0, 0, 0))
        w, h = tam
        ImageDraw.Draw(im).rounded_rectangle([w * 0.3, h * 0.08, w * 0.7, h * 0.98], radius=int(w * 0.08), fill=cor + (255,))
        ImageDraw.Draw(im).ellipse([w * 0.33, h * 0.02, w * 0.67, h * 0.25], fill=cor + (255,))
    else:
        im = Image.new("RGB", tam, cor)
    if texto:
        ImageDraw.Draw(im).text((10, 10), texto, fill=(0, 0, 0))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def exemplo() -> bytes:
    """⬇ Um zip de exemplo com a estrutura certa (JSONs preenchidos + imagens de mentirinha pra trocar pelas suas)."""
    b = io.BytesIO()
    js = lambda x: json.dumps(x, ensure_ascii=False, indent=2)  # noqa: E731
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        r = "exemplo_animacao_2d/"
        z.writestr(r + "LEIA-ME.txt", GUIA_ZIP)
        z.writestr(r + "projeto.json", js(EXEMPLO_PROJETO))
        z.writestr(r + "historia.txt", "(opcional — pode escrever a história aqui em vez de no projeto.json)\n\n" + A.EXEMPLO_INSTRUCOES)
        z.writestr(r + "cenas.json", js(EXEMPLO_CENAS))
        z.writestr(r + "cenas_valores_aceitos.json", js(EXEMPLO_CENAS_NOTAS))
        z.writestr(r + "estilo/exemplo_estilo.png", _png_exemplo((250, 220, 120), (512, 512), texto="troque pela sua imagem de estilo"))
        z.writestr(r + "personagens/Kenta/personagem.json", js(EXEMPLO_PERSONAGEM))
        z.writestr(r + "personagens/Kenta/foto_referencia.png", _png_exemplo((230, 80, 80), (512, 768), texto="foto do Kenta"))
        for nome, cor in (("neutro", (220, 60, 60)), ("neutro_boca", (230, 90, 90)), ("correndo", (200, 40, 40)),
                          ("correndo_b", (180, 30, 30)), ("escondido atras do sofa", (150, 40, 40))):
            z.writestr(r + f"personagens/Kenta/poses/{nome}.png", _png_exemplo(cor, (600, 900), True))
        z.writestr(r + "personagens/Mae/personagem.json", js({**EXEMPLO_PERSONAGEM, "nome": "Mãe", "descricao": "a mãe do Kenta",
                                                               "personalidade": "carinhosa, mas assustadora quando brava",
                                                               "jeito_de_falar": "grita KENTAAA!", "genero": "feminino",
                                                               "idade": "adulto", "cor": "#4fc3ff",
                                                               "aparencia_en": "woman in her 30s, brown hair in a bun, green apron"}))
        z.writestr(r + "personagens/Mae/foto.jpg", _png_exemplo((80, 120, 230), (512, 768), texto="foto da Mae"))
        z.writestr(r + "locais/Sala/local.json", js(EXEMPLO_LOCAL))
        z.writestr(r + "locais/Sala/fundo.png", _png_exemplo((150, 190, 230), (1920, 1080), texto="fundo pronto (opcional)"))
        z.writestr(r + "locais/Sala/frente.png", _png_exemplo((120, 80, 40), (900, 300), True))
        z.writestr(r + "locais/Quintal/local.json", js({"nome": "Quintal", "descricao": "quintal com grama e cerca",
                                                        "prompt_en": "small backyard with green grass and a wooden fence, sunny day",
                                                        "frente_en": ""}))
        z.writestr(r + "locais/Quintal/referencia.jpg", _png_exemplo((90, 170, 90), (800, 450), texto="foto de referencia"))
        z.writestr(r + "itens/Vaso quebrado/item.json", js(EXEMPLO_ITEM))
        z.writestr(r + "itens/Vaso quebrado/imagem.png", _png_exemplo((60, 90, 200), (400, 400), True))
        z.writestr(r + "itens/Mae gigante/item.json", js({"nome": "Mãe gigante", "tipo": "destaque",
                                                          "prompt_en": "extreme close up of the angry mother's face, dramatic shadows"}))
    return b.getvalue()


def exportar(pid: str, base: str = A._BASE) -> bytes:
    """⬇ O projeto no mesmo formato do zip (pra guardar, levar pra outro PC ou começar outro episódio daqui)."""
    p = A.carregar(pid, base)
    b = io.BytesIO()
    js = lambda x: json.dumps(x, ensure_ascii=False, indent=2)  # noqa: E731
    d = A.pasta(pid, base)
    usados: set = set()

    def pasta_nome(n: str) -> str:
        s = re.sub(r'[\\/:*?"<>|]+', " ", n).strip() or "sem nome"
        k, i = s, 2
        while _norm(k) in usados:
            k, i = f"{s} {i}", i + 1
        usados.add(_norm(k))
        return k

    def ler(cam: str) -> Optional[bytes]:
        try:
            with open(cam, "rb") as f:
                return f.read()
        except OSError:
            return None

    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEIA-ME.txt", GUIA_ZIP)
        z.writestr("projeto.json", js({"titulo": p["titulo"], "historia": p.get("premissa") or "", "estilo": p["estilo"],
                                       "estilo_extra": p.get("estilo_extra") or "", "proporcao": p["proporcao"],
                                       "duracao_min": p.get("duracao_alvo") or 0, "idioma": p.get("idioma"),
                                       "narrador": bool((p.get("narrador") or {}).get("ativo")),
                                       "narrador_voz": (p.get("narrador") or {}).get("voz") or "",
                                       "legendas": bool(p.get("legendas", True)), "paralaxe": bool(p.get("paralaxe", True))}))
        for r in p["referencias"]:
            if r["tipo"] == "estilo":
                x = ler(os.path.join(d, "refs", r["arquivo"]))
                if x:
                    z.writestr(f"estilo/{r['arquivo']}", x)
        for k, a in enumerate(A.paginas_manga(p), 1):  # 📖
            x = ler(os.path.join(d, "manga", a))
            if x:
                z.writestr(f"manga/{k:03d}.jpg", x)
        if A.paginas_manga(p) or (p.get("manga") or {}).get("adaptacao"):
            import anime2d_manga as AM
            ad = AM.json_adaptacao(p)
            ad["cenas"] = []  # as cenas vão completas no cenas.json
            z.writestr("adaptacao.json", js(ad))
        for c in p["personagens"]:
            pn = "personagens/" + pasta_nome(c["nome"]) + "/"
            dz = c.get("design") or {}
            z.writestr(pn + "personagem.json", js({"nome": c["nome"], **{k: c.get(k) or "" for k in CAMPOS_PERS},
                                                   "genero": c.get("genero") or "", "idade": c.get("idade") or "",
                                                   "voz": c.get("voz") or "", "cor": c.get("cor") or "",
                                                   **({"design_en": c.get("design_en") or "", "aparencia_manga_en": c.get("aparencia_manga_en") or "",
                                                       "mudancas_anime": c.get("mudancas_anime") or "",
                                                       "design_aprovado": bool(dz.get("aprovado"))} if "design" in c else {})}))
            cam = A.arquivo_img(p, {"arquivo": dz.get("aprovado") or dz.get("arquivo")}, base) if dz else None
            x = ler(cam) if cam else None
            if x:
                z.writestr(pn + "design_anime.png", x)
            for a in c.get("refs") or []:
                x = ler(os.path.join(d, "refs", a))
                if x:
                    z.writestr(pn + a, x)
            for nome, f in A.poses_prontas(c, base).items():
                livre = next((t for t in c.get("poses_zip") or [] if A.nome_pose("outra", t) == nome), None)
                stem = livre or (nome[2:].replace("_", " ") if nome.startswith("x_") else nome)
                for var, cam in (("", f.get("pose")), ("_b", f.get("b")), ("_boca", f.get("boca")), ("_pisca", f.get("pisca"))):
                    x = ler(cam) if cam else None
                    if x:
                        z.writestr(pn + f"poses/{stem}{var}.png", x)
        usados.clear()
        for lo in p["locais"]:
            pn = "locais/" + pasta_nome(lo["nome"]) + "/"
            z.writestr(pn + "local.json", js({"nome": lo["nome"], **{k: lo.get(k) or "" for k in ("descricao", "prompt_en", "frente_en")},
                                              "props": [{k: pr.get(k) for k in ("nome", "prompt_en", "camada", "x", "y", "w") if pr.get(k) is not None}
                                                        for pr in lo.get("props") or []],
                                              "lugares": [dict(lg) for lg in lo.get("lugares") or []], "chao": lo.get("chao") or {}}))
            for pr in lo.get("props") or []:
                cam = A.arquivo_img(p, pr.get("img") or {}, base)
                x = ler(cam) if cam else None
                if x:
                    z.writestr(pn + f"props/{pr['nome']}.png", x)
            for campo, arq in (("img", "fundo.png"), ("frente", "frente.png")):
                cam = A.arquivo_img(p, lo.get(campo) or {}, base)
                x = ler(cam) if cam else None
                if x:
                    z.writestr(pn + arq, x)
            for a in lo.get("refs") or []:
                x = ler(os.path.join(d, "refs", a))
                if x:
                    z.writestr(pn + a, x)
        usados.clear()
        for it in p["itens"]:
            pn = "itens/" + pasta_nome(it["nome"]) + "/"
            z.writestr(pn + "item.json", js({"nome": it["nome"], "tipo": it.get("tipo") or "objeto", "prompt_en": it.get("prompt_en") or "",
                                             "personagens": it.get("personagens") or [], "texto": it.get("texto") or ""}))
            cam = A.arquivo_img(p, it.get("img") or {}, base)
            x = ler(cam) if cam else None
            if x:
                z.writestr(pn + "imagem.png", x)
            for a in it.get("refs") or []:
                x = ler(os.path.join(d, "refs", a))
                if x:
                    z.writestr(pn + a, x)
        if p["cenas"]:
            cenas = []
            for s in p["cenas"]:
                lo = next((x for x in p["locais"] if x["id"] == s.get("local")), None)
                ms = []
                for m in s.get("momentos") or []:
                    mm = {"tipo": m["tipo"], "quem": A.nome_de(p, m["quem"]) if m["quem"] else "", "texto": m.get("texto") or "",
                          "camera": m.get("camera") or "fixa",
                          "em_cena": [{"personagem": A.nome_de(p, e["cid"]), "posicao": e["posicao"],
                                       "pose": e["pose"] if e["pose"] != "outra" else (e.get("pose_en") or "neutro"), "olha": e["olha"]}
                                      for e in m.get("em_cena") or []]}
                    for k in ("objeto", "destaque"):
                        if m.get(k):
                            mm[k] = next((i["nome"] for i in p["itens"] if i["id"] == m[k]), "")
                    if m.get("duracao"):
                        mm["duracao"] = m["duracao"]
                    if m.get("som"):
                        mm["som"] = m["som"]
                    if m.get("tempo") is not None:
                        mm["tempo"] = m["tempo"]
                    ms.append(mm)
                cenas.append({"titulo": s.get("titulo") or "", "local": (lo or {}).get("nome") or "", "resumo": s.get("resumo") or "",
                              "personagens": [A.nome_de(p, x) for x in s.get("personagens") or []], "momentos": ms,
                              **({"paginas": s["paginas"]} if s.get("paginas") else {}),
                              **({"nota_adaptacao": s["nota_adaptacao"]} if s.get("nota_adaptacao") else {})})
            z.writestr("cenas.json", js(cenas))
        if A.audio_ok(p, base):
            x = ler(os.path.join(d, p["audio"]["arquivo"]))
            if x:
                z.writestr("audio.wav", x)
    return b.getvalue()
