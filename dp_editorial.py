"""
🗞 Quadros editoriais — o estilo "documentário editorial" (papel bege com
vinheta, serifada, versalete espaçado, acento vermelho), recriado a partir de
vídeos de referência que a pessoa mandou:

  ficha         linha sai do rosto até um cartão escuro (nome + dados linha a linha)   [sobre o vídeo]
  nome          nome serifado + cargo em versalete, com um traço vermelho               [sobre o vídeo]
  post          post (X/Instagram…) sobre o vídeo desfocado + tradução em itálico       [sobre o vídeo]
  titulo_video  título gigante com o VÍDEO dentro das letras + definição digitada       [máscara]
  terminal      texto mono digitando com cursor, erros em vermelho                     [tela cheia]
  pagina        print de página num navegador inclinado, flutuando                      [tela cheia]
  linha_tempo   meses passando numa linha, o atual aceso                                [tela cheia]
  grade_pontos  centenas de pontos, alguns acendem, contadores embaixo                  [tela cheia]
  recortes      manchetes em papel caem numa mesa + número grande vermelho              [tela cheia]
  mural         fotos P&B com borda, câmera deslizando, citações em etiquetas           [tela cheia]
  bilhetes      foto (ou o vídeo do trecho) + bilhetes de papel aparecendo              [tela cheia]
  reescrita     frase digitada, riscada em vermelho, digitada de novo                   [tela cheia]
  numero        número grande contando, o % em vermelho                                 [tela cheia]
  explosao      texto/equação que explode em pedaços + mancha de tinta                  [tela cheia]

Cada quadro é desenhado com o PIL, quadro a quadro (30 fps), vira um .mov com
transparência e entra por cima do vídeo no tempo dele (um passe do ffmpeg,
como os gráficos). "post" desfoca o vídeo por baixo; "titulo_video" usa uma
máscara (as letras mostram o vídeo); "bilhetes" pode pôr o próprio vídeo do
trecho dentro da moldura. A prévia do Estúdio pede um quadro desenhado aqui
mesmo (o mesmo código) — telinha = vídeo.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

FPS = 30
ENTRA_S, SAI_S = 0.35, 0.35
VERMELHO = "#D0443E"

# ------------------------------------------------------------------ catálogo
# campo: (chave, rótulo, tipo, padrão, dica)   tipos: texto, linhas, num, img, imgs, escolha:a|b, cor
_C_CREDITO = ("credito", "Crédito/fonte (canto)", "texto", "", "ex.: BBC NEWS · 24/09/2026")
TIPOS: Dict[str, Dict[str, Any]] = {
    "ficha": {
        "nome": "🪪 Ficha de pessoa", "camada": "sobre", "dur": 5.0,
        "quando": "apresentar alguém que aparece no vídeo (nome + cargo + dados), com uma linha saindo do rosto",
        "campos": [("rotulo", "Rótulo em vermelho", "texto", "PERFIL", "ex.: AUSTRÁLIA"),
                   ("nome", "Nome", "texto", "Nome da Pessoa", ""),
                   ("linhas", "Dados (um por linha: Rótulo: valor)", "linhas", "Cargo: Primeiro-ministro\nNo cargo desde: Maio de 2022", ""),
                   ("ponto_x", "Ponto do rosto X (0–1)", "num", 0.5, "onde a linha começa"),
                   ("ponto_y", "Ponto do rosto Y (0–1)", "num", 0.25, ""),
                   ("lado", "Lado do cartão", "escolha:direita|esquerda", "direita", ""), _C_CREDITO],
    },
    "nome": {
        "nome": "🏷 Nome do entrevistado", "camada": "sobre", "dur": 4.0,
        "quando": "quando alguém aparece falando pela 1ª vez",
        "campos": [("nome", "Nome", "texto", "Nome da Pessoa", ""), ("cargo", "Cargo", "texto", "CEO DA EMPRESA", ""), _C_CREDITO],
    },
    "post": {
        "nome": "💬 Post (X/Instagram…)", "camada": "sobre", "dur": 5.0,
        "quando": "citar um post/tweet real; o vídeo por baixo fica desfocado e a tradução aparece embaixo",
        "campos": [("nome", "Nome", "texto", "Nome", ""), ("usuario", "@usuário", "texto", "@usuario", ""),
                   ("texto", "Texto do post", "linhas", "Texto do post.", ""), ("data", "Data", "texto", "", "ex.: 8 de set. de 2026"),
                   ("traducao", "Tradução (itálico, embaixo)", "linhas", "", ""),
                   ("rede", "Rede", "escolha:x|instagram|threads|bluesky|linkedin", "x", ""), _C_CREDITO],
    },
    "titulo_video": {
        "nome": "🔠 Título com o vídeo nas letras", "camada": "mascara", "dur": 5.0,
        "quando": "um conceito-chave dito na fala (uma palavra grande), com a definição embaixo",
        "campos": [("titulo", "Título (1–2 palavras)", "texto", "SINGULARIDADE", ""),
                   ("subtitulo", "Definição (digitada)", "texto", "", ""), _C_CREDITO],
    },
    "terminal": {
        "nome": "⌨ Terminal digitando", "camada": "tela", "dur": 8.0, "fundo": "escuro",
        "quando": "mostrar o que um sistema/IA fez passo a passo (comandos, tentativas, erros)",
        "campos": [("cabecalho", "Cabeçalho", "texto", "SISTEMA · LOG", "ex.: OPENAI · MODELO INTERNO · 18/06/2026"),
                   ("linhas", "Linhas (! no começo = vermelho)", "linhas", "> tarefa: pesquisar\n> buscando dados...\n!403 ACESSO NEGADO", ""), _C_CREDITO],
    },
    "pagina": {
        "nome": "🖥 Página/print em 3D", "camada": "tela", "dur": 5.0, "fundo": "escuro",
        "quando": "mostrar uma notícia/página como prova (o print flutua inclinado)",
        "campos": [("imagem", "Print (imagem da biblioteca)", "img", "", "ou deixe vazio e use o link/título"),
                   ("url", "Link da página (tira o print sozinho)", "texto", "", "https://…"),
                   ("site", "Endereço na barra", "texto", "site.com", ""),
                   ("titulo", "Manchete (se não tiver print)", "texto", "Manchete da notícia", ""),
                   ("subtitulo", "Linha fina (se não tiver print)", "texto", "", ""), _C_CREDITO],
    },
    "linha_tempo": {
        "nome": "🗓 Linha do tempo deslizante", "camada": "tela", "dur": 6.0, "fundo": "escuro",
        "quando": "uma sequência de datas/meses (o que aconteceu em cada um)",
        "campos": [("ano", "Ano/título pequeno", "texto", "2026", ""),
                   ("itens", "Itens (MÊS | o que aconteceu)", "linhas", "JUN | Primeiro fato\nJUL | Segundo fato\nAGO | Terceiro fato", ""), _C_CREDITO],
    },
    "grade_pontos": {
        "nome": "⠿ Grade de pontos + contadores", "camada": "tela", "dur": 5.0, "fundo": "escuro",
        "quando": "mostrar escala (muitos participantes, poucos se destacam) com contadores",
        "campos": [("titulo", "Título pequeno", "texto", "", "ex.: OLIMPÍADA INTERNACIONAL DE MATEMÁTICA · 2026"),
                   ("total", "Total de pontos", "num", 666, ""), ("acesos", "Pontos que acendem", "num", 7, ""),
                   ("contadores", "Contadores (NÚMERO | rótulo; o último fica vermelho)", "linhas", "666 | competidores\n7 | nota máxima", ""), _C_CREDITO],
    },
    "recortes": {
        "nome": "📰 Recortes caindo na mesa", "camada": "tela", "dur": 7.0, "fundo": "mesa",
        "quando": "várias notícias/acontecimentos seguidos (um recorte por fato) + um número que resume",
        "campos": [("manchetes", "Recortes (DATA/FONTE | manchete)", "linhas", "22 DE SETEMBRO | Primeira manchete\nOPENAI | Segunda manchete", ""),
                   ("imagens", "Imagens dos recortes (opcional, na ordem)", "imgs", "", ""),
                   ("numero", "Número grande (vermelho)", "texto", "", "ex.: 4"),
                   ("rotulo_numero", "Rótulo do número", "texto", "", "ex.: MODELOS DE PONTA EM UM MÊS"), _C_CREDITO],
    },
    "mural": {
        "nome": "🖼 Mural de fotos com citações", "camada": "tela", "dur": 6.0, "fundo": "papel",
        "quando": "comparar o que várias pessoas disseram (uma foto + uma frase curta cada)",
        "campos": [("imagens", "Fotos (biblioteca, na ordem)", "imgs", "", ""),
                   ("nomes", "Nomes (um por foto)", "linhas", "", ""),
                   ("citacoes", "Citações curtas (uma por foto; a última fica vermelha)", "linhas", "primeira\nsegunda\nterceira", ""), _C_CREDITO],
    },
    "bilhetes": {
        "nome": "📝 Foto + bilhetes", "camada": "tela", "dur": 6.0, "fundo": "papel",
        "quando": "explicar um processo/rotina com passos curtos ao lado de uma imagem",
        "campos": [("imagem", "Imagem (biblioteca) — vazio = o vídeo do trecho", "img", "", ""),
                   ("notas", "Bilhetes (um por linha; o último fica amarelo)", "linhas", "primeiro passo\nsegundo passo\nterceiro passo", ""),
                   ("legenda", "Legenda embaixo da foto", "texto", "", ""), _C_CREDITO],
    },
    "reescrita": {
        "nome": "✍ Reescrita (riscar e refazer)", "camada": "tela", "dur": 7.0, "fundo": "papel",
        "quando": "mostrar tentativas que deram errado até a certa",
        "campos": [("tentativas", "Tentativas (a última é a certa)", "linhas", "Primeira tentativa\nSegunda tentativa\nA versão certa.", ""),
                   ("rotulo", "Rótulo vermelho no fim", "texto", "", ""), _C_CREDITO],
    },
    "numero": {
        "nome": "💯 Número grande", "camada": "tela", "dur": 5.0, "fundo": "papel",
        "quando": "um número que é a notícia (porcentagem, valor, contagem)",
        "campos": [("de", "Começa em", "num", 0, ""), ("ate", "Termina em", "num", 98, ""),
                   ("prefixo", "Antes do número", "texto", "", "ex.: R$"), ("sufixo", "Depois (vermelho)", "texto", "%", ""),
                   ("rotulo", "Rótulo (versalete)", "texto", "", ""), ("subtexto", "Linha em itálico", "texto", "", ""), _C_CREDITO],
    },
    "explosao": {
        "nome": "💥 Texto que explode (tinta)", "camada": "tela", "dur": 4.0, "fundo": "papel",
        "quando": "algo que 'quebra', 'explode', 'desmorona' (uma fórmula, uma frase, uma regra)",
        "campos": [("texto", "Texto/equação", "texto", "a = b + c", ""), ("rotulo", "Rótulo embaixo", "texto", "", ""),
                   ("palavra_final", "Palavra que fica (itálico)", "texto", "explodem.", ""), _C_CREDITO],
    },
}
_COMUNS = [("cor", "Cor de acento", "cor", "", "vazio = vermelho editorial"),
           ("fundo", "Fundo", "escolha:escuro|papel|mesa", "", "só nos de tela cheia"),
           ("som", "Som", "escolha:auto|nenhum", "auto", "auto = os sons da biblioteca que combinam com o quadro")]


def campos(tipo: str) -> List[Tuple[str, str, str, Any, str]]:
    t = TIPOS.get(tipo) or {}
    return list(t.get("campos") or []) + [c for c in _COMUNS if c[0] != "fundo" or t.get("camada") == "tela"]


def para_editor() -> Dict[str, Any]:
    return {k: {"nome": v["nome"], "camada": v["camada"], "dur": v["dur"], "quando": v["quando"], "fundo": v.get("fundo"),
                "campos": [dict({"k": c[0], "rotulo": c[1], "tipo": c[2], "padrao": c[3], "dica": c[4]},
                                **({"rotulos": v["rotulos"][c[0]]} if c[0] in (v.get("rotulos") or {}) else {})) for c in campos(k)]}
            for k, v in TIPOS.items()}


def bloco_para_prompt(tipos: Optional[List[str]] = None) -> str:
    out = []
    for k, v in TIPOS.items():
        if tipos and k not in tipos:
            continue
        cs = ", ".join(f"{c[0]}" + (" (linhas separadas por \\n)" if c[2] in ("linhas",) else "") for c in v["campos"] if c[2] not in ("img", "imgs"))
        out.append(f"- {k} = {v['nome'][2:].strip()} — {v['quando']}. Campos: {cs}")
    return "\n".join(out)


def _num(v: Any, padrao: float) -> float:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return float(padrao)


def normalizar(x: Any, duracao: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Valida um quadro (da IA ou do editor). None se não der."""
    if not isinstance(x, dict) or x.get("tipo") not in TIPOS:
        return None
    t = TIPOS[x["tipo"]]
    ini = max(0.0, _num(x.get("start"), 0))
    fim = _num(x.get("end"), ini + t["dur"])
    if fim - ini < 1.2:
        fim = ini + max(1.2, t["dur"])
    if duracao:
        fim = min(fim, float(duracao))
        if fim - ini < 1.2:
            return None
    out: Dict[str, Any] = {"id": str(x.get("id") or hashlib.md5(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()[:8])[:16],
                           "tipo": x["tipo"], "start": round(ini, 3), "end": round(fim, 3)}
    for (k, _r, tipo, padrao, _d) in campos(x["tipo"]):
        v = x.get(k, padrao)
        if tipo == "num":
            out[k] = _num(v, padrao if padrao != "" else 0)
        elif tipo == "linhas":
            if isinstance(v, list):
                v = "\n".join(str(i) for i in v)
            out[k] = "\n".join(l.rstrip() for l in str(v or "").replace("\r", "").split("\n"))[:2000].strip("\n")
        elif tipo == "imgs":
            lista = v if isinstance(v, list) else [s.strip() for s in str(v or "").split(",")]
            out[k] = [str(i).strip()[:200] for i in lista if str(i).strip()][:8]
        elif tipo == "cor":
            out[k] = str(v).upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", str(v or "")) else ""
        elif tipo.startswith("escolha:"):
            ops = tipo.split(":", 1)[1].split("|")
            out[k] = v if v in ops else ("" if k == "fundo" else ops[0])
        else:
            out[k] = str(v if v is not None else "").strip()[:300]
    if x.get("origem"):
        out["origem"] = str(x["origem"])[:10]
    if x.get("_idioma_video"):  # 📅 idioma "auto" dos calendários = o idioma do vídeo (o site preenche)
        out["_idioma_video"] = str(x["_idioma_video"])[:8]
    return out


def com_idioma_do_video(itens: Optional[List[Dict[str, Any]]], idioma: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Cópia dos quadros com o idioma do vídeo anotado (usado pelos quadros com idioma "auto")."""
    if not itens:
        return itens
    if not idioma:
        return list(itens)
    return [dict(i, _idioma_video=idioma) if isinstance(i, dict) else i for i in itens]


# ------------------------------------------------------------------ sons de cada quadro
# Os sons são os da biblioteca do site (assets/sons, os do editor original). Para trocar o som de um
# papel, mude o id aqui (a lista está na aba 🔊 Áudios ou em `python dp_guia.py listar sons`).
SONS = {
    "cartao": "cinema/cinema_14",            # a ficha entrando
    "nome": "pop/pop_click_1_escala",        # o nome do entrevistado
    "post": "transicoes/foco_optico",        # o post aparece e o vídeo desfoca
    "titulo": "impacto/riser_5",             # sobe até a última letra do título
    "terminal": "digital/digital_12",        # o terminal liga
    "digitando": "foley/digitacao_5_longa",  # digitação do terminal
    "linha": "foley/tecla_suave",            # cada linha nova do terminal
    "erro": "transicoes/pulso_digital_curto",  # a 1ª linha vermelha
    "pagina": "transicoes/whoosh",           # a página entra
    "passo": "foley/catraca_rolagem",        # cada mês da linha do tempo / o número contando
    "grade": "impacto/riser_solto_3",        # os pontos acendendo
    "papel": "transicoes/folha_seca",        # recorte caindo, bilhete
    "foto": "foley/camera_14",               # cada foto/citação do mural
    "numero_fim": "impacto/impacto_5",       # o número chegou
    "recortes_numero": "impacto/impacto_11",  # o número grande dos recortes
    "digitar_frase": "foley/digitacao_6_curta",  # cada tentativa da reescrita
    "risco": "foley/escrita_giz",            # o risco vermelho da reescrita
    "explosao": "impacto/impacto_15",        # o texto explode
    "explosao_ar": "variados/whoosh_grave_4",  # a tinta se espalhando
}


def _linhas_txt(it: Dict[str, Any], chave: str) -> List[str]:
    return [l for l in str(it.get(chave) or "").split("\n") if l.strip()]


def batidas(it: Dict[str, Any]) -> List[Tuple[float, str, float, str]]:
    """Os sons de um quadro: (segundos desde o começo do quadro, id do som, volume, "pico" | "inicio")."""
    if not isinstance(it, dict) or it.get("som") == "nenhum" or it.get("tipo") not in TIPOS:
        return []
    tipo, dur = it["tipo"], float(it["end"]) - float(it["start"])
    S = SONS
    b: List[Tuple[float, str, float, str]] = []
    if tipo == "ficha":
        b.append((0.3, S["cartao"], 0.7, "pico"))
    elif tipo == "nome":
        b.append((0.2, S["nome"], 0.5, "pico"))
    elif tipo == "post":
        b.append((0.15, S["post"], 0.6, "pico"))
    elif tipo == "titulo_video":
        b.append((min(dur - 0.3, 0.15 + 0.45 * dur + 0.3), S["titulo"], 0.7, "pico"))
    elif tipo == "terminal":
        b.append((0.0, S["terminal"], 0.5, "inicio"))
        if dur >= 4.5:  # a digitação longa tem ~5 s
            b.append((0.3, S["digitando"], 0.4, "inicio"))
        linhas = []
        for l in str(it.get("linhas") or "").split("\n"):
            verm = l.startswith("!") or bool(re.search(r"^\s*\d{3}\b|ERRO|ERROR|NEGADO|DENIED|FALHOU|FAILED|BLOQUEADO", l))
            linhas.append((l[1:] if l.startswith("!") else l, verm))
        total = sum(len(l) + 6 for l, _v in linhas) or 1
        janela_dig = max(0.6, 0.85 * dur - 0.4)
        acum, alerta = 0, False
        for i, (l, verm) in enumerate(linhas[:10]):
            ti = 0.3 + janela_dig * acum / total
            if i:
                b.append((ti, S["linha"], 0.5, "pico"))
            if verm and not alerta:
                b.append((ti, S["erro"], 0.6, "pico"))
                alerta = True
            acum += len(l) + 6
    elif tipo == "pagina":
        b.append((0.2, S["pagina"], 0.55, "pico"))
    elif tipo == "linha_tempo":
        n = max(1, len(_linhas_txt(it, "itens")))
        seg = max(0.4, (dur - 0.8) / n)
        b += [(0.3 + kk * seg, S["passo"], 0.4, "inicio") for kk in range(1, min(n, 10))]
    elif tipo == "grade_pontos":
        b.append((min(dur - 0.3, 0.45 + 0.45 * dur), S["grade"], 0.6, "pico"))
    elif tipo == "recortes":
        n = max(1, len(_linhas_txt(it, "manchetes")))
        gap = min(1.1, (dur * 0.6) / n)
        b += [(0.25 + i * gap + 0.45, S["papel"], 0.65, "pico") for i in range(min(n, 8))]
        if it.get("numero"):
            b.append((0.25 + n * gap + 0.35, S["recortes_numero"], 0.65, "pico"))
    elif tipo == "mural":
        n = max(1, len(_linhas_txt(it, "citacoes")))
        b += [(0.3 + i * (0.75 * dur / n), S["foto"], 0.45, "pico") for i in range(min(n, 8))]
    elif tipo == "bilhetes":
        n = max(1, len(_linhas_txt(it, "notas")))
        b += [(0.5 + i * (0.6 * dur / n) + 0.1, S["papel"], 0.5, "pico") for i in range(min(n, 8))]
    elif tipo == "reescrita":
        tent = [l.strip() for l in _linhas_txt(it, "tentativas")][:5] or [""]
        orc = max(1.0, 0.85 * dur - 0.4 - 0.7 * (len(tent) - 1) - (0.8 if it.get("rotulo") else 0))
        cps = _cl(sum(len(x) for x in tent) / orc, 10, 45)
        tc = 0.3
        for i, x in enumerate(tent):
            b.append((tc, S["digitar_frase"], 0.4, "inicio"))
            tc += len(x) / cps
            if i < len(tent) - 1:
                b.append((tc + 0.4, S["risco"], 0.55, "pico"))  # o risco vermelho
                tc += 0.7
    elif tipo == "numero":
        b += [(0.15, S["passo"], 0.4, "inicio"), (1.25, S["numero_fim"], 0.7, "pico")]
    elif tipo == "explosao":
        t_exp = max(1.0, 0.35 * dur)
        b += [(t_exp + 0.05, S["explosao"], 0.75, "pico"), (t_exp + 0.4, S["explosao_ar"], 0.45, "pico")]
    else:
        import dp_calendario  # 📅 calendários / folhinha / placar / lista riscada (v84_93)
        import dp_escrita  # ✍️ escrita no papel: mão / máquina / computador (v84_94)
        if tipo in dp_calendario.TIPOS:
            b += dp_calendario.batidas(it, dur, S)
        elif tipo in dp_escrita.TIPOS:
            b += dp_escrita.batidas(it, dur, S)
    return [(round(max(0.0, min(t, dur)), 3), sid, v, al) for t, sid, v, al in b]


def eventos_sonoros(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Eventos de som (dp_sons.evento) de todos os quadros, no tempo do vídeo."""
    import dp_sons
    ev = []
    for it in itens or []:
        for t, sid, vol, al in batidas(it):
            e = dp_sons.evento(sid, float(it["start"]) + t, vol, alinhar=al)
            if e:
                ev.append(e)
    return ev


# ------------------------------------------------------------------ desenho: utilitários
def _fonte_arq(familia: str, negrito: bool = False, italico: bool = False) -> str:
    import dp_destaques
    return dp_destaques.arquivo_da_fonte(familia, negrito, italico)


@lru_cache(maxsize=256)
def _f(qual: str, px: int):
    from PIL import ImageFont
    fam, neg, ita = {"serif": ("DP Eb Garamond", False, False), "serif_i": ("DP Eb Garamond", False, True),
                     "serif_b": ("DP Eb Garamond", True, False), "sans": ("DP Inter", False, False),
                     "sans_b": ("DP Inter", True, False), "sans_i": ("DP Inter", False, True),
                     "mono": ("DP Jetbrains Mono", False, False)}[qual]
    return ImageFont.truetype(_fonte_arq(fam, neg, ita), max(6, int(px)))


_SIMBOLOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "simbolos")


@lru_cache(maxsize=64)
def _f_simbolos(px: int, italico: bool = False):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(_SIMBOLOS, "DejaVuSerif-Italic.ttf" if italico else "DejaVuSerif.ttf"), max(6, int(px)))


@lru_cache(maxsize=8192)
def _sem_glifo(caminho: str, px: int, ch: str) -> bool:
    """A fonte não tem esse caractere (∂, ∇, ν…)? — compara com o desenho do "glifo que falta"."""
    from PIL import ImageFont
    if ch.isspace() or ord(ch) < 0x250:
        return False
    f = ImageFont.truetype(caminho, px)
    try:
        return f.getmask(ch).tobytes() == f.getmask("\uffff").tobytes()
    except Exception:  # noqa: BLE001
        return True


def _fonte_do_char(fonte, ch: str):
    if _sem_glifo(fonte.path, int(fonte.size), ch):
        return _f_simbolos(int(fonte.size * 0.92), "Italic" in os.path.basename(fonte.path))
    return fonte


def _rgb(c: str) -> Tuple[int, int, int]:
    c = (c or "#000000").lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _cl(v: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if v < a else b if v > b else v


def _ease(p: float) -> float:
    p = _cl(p)
    return 1 - (1 - p) ** 3


def _janela(t: float, t0: float, d: float) -> float:
    return _ease((t - t0) / d) if d > 0 else (1.0 if t >= t0 else 0.0)


def _largura(txt: str, fonte, espaco: float = 0) -> float:
    if not txt:
        return 0.0
    return fonte.getlength(txt) + espaco * max(0, len(txt) - 1)


def _espacado(d, x: float, y: float, txt: str, fonte, cor, espaco: float, ancora: str = "l") -> float:
    """Versalete espaçado (letra por letra). ancora l/r = x é a esquerda/direita. Devolve a largura."""
    w = _largura(txt, fonte, espaco)
    if ancora == "r":
        x -= w
    for ch in txt:
        d.text((x, y), ch, font=fonte, fill=cor, anchor="ls")
        x += fonte.getlength(ch) + espaco
    return w


def _quebrar(txt: str, fonte, larg: float) -> List[str]:
    out: List[str] = []
    for par in str(txt or "").split("\n"):
        linha = ""
        for p in par.split():
            cand = (linha + " " + p).strip()
            if linha and fonte.getlength(cand) > larg:
                out.append(linha)
                linha = p
            else:
                linha = cand
        out.append(linha)
    return out


def _com_alfa(im, k: float):
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    if k >= 0.999:
        return im
    a = im.getchannel("A").point(lambda v: int(v * max(0.0, k)))
    im = im.copy()
    im.putalpha(a)
    return im


def _sombra(w: int, h: int, raio: int, alfa: int = 150, r_canto: int = 0):
    from PIL import Image, ImageDraw, ImageFilter
    m = raio * 3
    im = Image.new("RGBA", (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    ImageDraw.Draw(im, "RGBA").rounded_rectangle([m, m, m + w, m + h], radius=r_canto, fill=(0, 0, 0, alfa))
    return im.filter(ImageFilter.GaussianBlur(raio)), m


@lru_cache(maxsize=12)
def _fundo(tipo: str, W: int, H: int):
    """Papel bege com vinheta e grão / escuro azulado com vinheta / mesa de madeira escura."""
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W * 0.45) / (W * 0.62)) ** 2 + ((yy - H * 0.42) / (H * 0.66)) ** 2)
    if tipo == "papel":
        luz = np.clip(1.05 - 0.42 * r ** 2.2, 0.48, 1.0)[..., None]
        base = np.array([236, 231, 220], np.float32) * luz + np.array([-6, -4, 2], np.float32) * (1 - luz)
        base += rng.normal(0, 4.5, (H, W, 1))
    elif tipo == "mesa":
        veio = np.sin(yy / H * 90 + np.sin(xx / W * 7) * 2.2 + rng.normal(0, 0.02, (H, W))) * 0.5 + 0.5
        veio2 = np.sin(yy / H * 23 + np.sin(xx / W * 3.1 + 1) * 1.4) * 0.5 + 0.5
        tom = 0.55 + 0.25 * veio * veio2
        luz = np.clip(1.15 - 0.75 * r ** 1.6, 0.25, 1.0)
        base = (np.array([62, 46, 36], np.float32) * (tom * luz)[..., None])
        base += rng.normal(0, 3, (H, W, 1))
    else:  # escuro
        luz = np.clip(1.0 - 0.55 * r ** 1.8, 0.35, 1.0)[..., None]
        base = np.array([22, 26, 33], np.float32) * luz + rng.normal(0, 1.6, (H, W, 1))
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def _credito(d, it: Dict[str, Any], W: int, H: int, u: float, fundo: str, k: float = 1.0) -> None:
    txt = (it.get("credito") or "").upper()
    if not txt:
        return
    f = _f("mono", 15 * u)
    if fundo == "papel":
        cor = (90, 84, 76, int(230 * k))
        d.ellipse([W * 0.037 - 4 * u, H * 0.062 - 9 * u, W * 0.037 + 4 * u, H * 0.062 - 1 * u], fill=_rgb(_acento(it)) + (int(255 * k),))
        _espacado(d, W * 0.037 + 12 * u, H * 0.062, txt, f, cor, 2.2 * u)
    else:
        _espacado(d, W * 0.94, H * 0.155, txt, f, (200, 204, 210, int(200 * k)), 2.6 * u, ancora="r")


def _acento(it: Dict[str, Any]) -> str:
    return it.get("cor") or VERMELHO


def _vert(W: int, H: int) -> bool:
    return H > W * 1.2


def _u(W: int, H: int) -> float:
    return (H if not _vert(W, H) else W * 1.0) / 1080.0


# ------------------------------------------------------------------ desenho: peças
def _nova(W: int, H: int):
    from PIL import Image
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def _cola(im, camada, x: float, y: float, k: float = 1.0) -> None:
    """alpha_composite de uma camada (com alfa extra k) em (x, y) — corta o que sai da tela."""
    if k <= 0.003 or camada is None:
        return
    c = _com_alfa(camada, k)
    x, y = int(round(x)), int(round(y))
    W, H = im.size
    cx0, cy0 = max(0, -x), max(0, -y)
    cx1, cy1 = min(c.width, W - x), min(c.height, H - y)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    if (cx0, cy0, cx1, cy1) != (0, 0, c.width, c.height):
        c = c.crop((cx0, cy0, cx1, cy1))
    if im.mode == "RGB":  # fundo opaco: mistura de verdade (paste com a máscara de alfa)
        im.paste(c.convert("RGB"), (x + cx0, y + cy0), c.getchannel("A"))
    else:
        im.alpha_composite(c, dest=(x + cx0, y + cy0))


def _cache(ctx: Dict[str, Any], chave: str, fazer):
    c = ctx.setdefault("_cache", {})
    if chave not in c:
        c[chave] = fazer()
    return c[chave]


def _img(ctx: Dict[str, Any], ref: str):
    """Imagem da biblioteca (ref "bib:<id>" ou caminho) como PIL RGB — vídeo vira o quadro de 1 s."""
    if not ref:
        return None
    caminho = (ctx.get("imagens") or {}).get(ref) or (ref if os.path.isfile(ref) else None)
    if not caminho or not os.path.isfile(caminho):
        return None

    def abrir():
        from PIL import Image
        alvo = caminho
        if os.path.splitext(caminho)[1].lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif"):
            alvo = os.path.join(ctx.get("pasta") or os.path.dirname(caminho), "_quadro_" + hashlib.md5(caminho.encode()).hexdigest()[:10] + ".jpg")
            if not os.path.exists(alvo):
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", caminho, "-frames:v", "1", alvo], capture_output=True, timeout=120)
                if not os.path.exists(alvo):
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", caminho, "-frames:v", "1", alvo], capture_output=True, timeout=120)
        try:
            return Image.open(alvo).convert("RGB")
        except Exception:  # noqa: BLE001
            return None
    return _cache(ctx, "img:" + caminho, abrir)


def _cobrir(img, w: int, h: int):
    """Redimensiona cobrindo w×h (corta o excesso, centro um pouco pra cima — rostos)."""
    from PIL import Image
    w, h = max(1, int(w)), max(1, int(h))
    s = max(w / img.width, h / img.height)
    nw, nh = max(w, int(img.width * s + 0.5)), max(h, int(img.height * s + 0.5))
    r = img.resize((nw, nh), Image.LANCZOS)
    x0 = (nw - w) // 2
    y0 = int((nh - h) * 0.35)
    return r.crop((x0, y0, x0 + w, y0 + h))


def _papel_retangulo(w: int, h: int, cor=(240, 236, 227), sombra: float = 1.0, u: float = 1.0, raio: int = 0):
    """Pedaço de papel (cor + leve grão) com sombra embaixo. Devolve (imagem, margem)."""
    import numpy as np
    from PIL import Image
    sh, m = _sombra(w, h, max(2, int(10 * u)), int(150 * sombra), raio)
    rng = np.random.default_rng(w * 31 + h)
    arr = np.clip(np.array(cor, np.float32)[None, None, :] + rng.normal(0, 3.0, (h, w, 1)), 0, 255).astype(np.uint8)
    papel = Image.fromarray(arr, "RGB").convert("RGBA")
    sh.alpha_composite(papel, dest=(m, int(m - 3 * u)))
    return sh, m


def _rotacionar(im, graus: float):
    from PIL import Image
    if abs(graus) < 0.05:
        return im
    return im.rotate(graus, resample=Image.BICUBIC, expand=True)


def _k_tela(t: float, dur: float) -> float:
    return min(_cl(t / ENTRA_S), _cl((dur - t) / SAI_S))


# ------------------------------------------------------------------ os quadros
def _d_ficha(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    im = _nova(W, H)
    k_out = _cl((dur - t) / SAI_S)
    vert = _vert(W, H)
    cw = int(W * 0.86) if vert else int(max(W * 0.30, 540 * u))
    if vert:
        x0, y0 = int(W * 0.07), int(H * 0.08)
    else:
        x0 = int(W * 0.963 - cw) if it.get("lado") != "esquerda" else int(W * 0.037)
        y0 = int(H * 0.168)
    pad = int(30 * u)
    linhas = []
    for l in (it.get("linhas") or "").split("\n"):
        if l.strip():
            a, _sep, b = l.partition(":")
            linhas.append((a.strip().upper(), b.strip()) if _sep else ("", l.strip()))
    lh = int(46 * u)
    topo_linhas = pad + int(24 * u) + int(66 * u) + int(30 * u)
    ch = topo_linhas + lh * len(linhas) + pad - int(8 * u)

    def base():
        from PIL import Image
        c = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        d = ImageDraw.Draw(c, "RGBA")
        d.rectangle([0, 0, cw - 1, ch - 1], fill=(13, 17, 23, 222), outline=(255, 255, 255, 28))
        _espacado(d, pad, pad + int(14 * u), (it.get("rotulo") or "").upper(), _f("sans", 15 * u), _rgb(_acento(it)) + (255,), 3.2 * u)
        d.text((pad, pad + int(24 * u) + int(52 * u)), it.get("nome") or "", font=_f("serif", 58 * u), fill=(242, 240, 236, 255), anchor="ls")
        yr = pad + int(24 * u) + int(66 * u) + int(4 * u)
        d.line([pad, yr, pad + int(38 * u), yr], fill=(255, 255, 255, 90), width=max(1, int(1.5 * u)))
        return c

    def linha_img(i):
        from PIL import Image
        a, b = linhas[i]
        c = Image.new("RGBA", (cw, lh), (0, 0, 0, 0))
        d = ImageDraw.Draw(c, "RGBA")
        _espacado(d, pad, int(lh * 0.62), a, _f("sans", 13.5 * u), (140, 146, 156, 255), 3.0 * u)
        d.text((cw - pad, int(lh * 0.64)), b, font=_f("sans", 22 * u), fill=(236, 236, 236, 255), anchor="rs")
        if i < len(linhas) - 1:
            d.line([pad, lh - 1, cw - pad, lh - 1], fill=(255, 255, 255, 24), width=1)
        return c
    a_card = _janela(t, 0.15, 0.4) * k_out
    dx = (1 - _janela(t, 0.15, 0.4)) * 26 * u * (1 if it.get("lado") != "esquerda" else -1)
    _cola(im, _cache(ctx, "ficha_base", base), x0 + dx, y0, a_card)
    for i in range(len(linhas)):
        _cola(im, _cache(ctx, f"ficha_l{i}", lambda i=i: linha_img(i)), x0 + dx, y0 + topo_linhas + i * lh, _janela(t, 0.55 + 0.13 * i, 0.3) * k_out)
    # linha do rosto até o cartão
    if not vert:
        px, py = float(it.get("ponto_x", 0.5)) * W, float(it.get("ponto_y", 0.25)) * H
        ex = x0 + dx if it.get("lado") != "esquerda" else x0 + dx + cw
        ey = y0 + pad + int(24 * u) + int(30 * u)
        p = _janela(t, 0.0, 0.4)
        if p > 0 and k_out > 0:
            d = ImageDraw.Draw(im, "RGBA")
            qx, qy = px + (ex - px) * p, py + (ey - py) * p
            al = int(225 * k_out)
            d.line([px, py, qx, qy], fill=(240, 240, 240, al), width=max(1, int(1.6 * u)))
            r = 4.5 * u
            d.ellipse([px - r, py - r, px + r, py + r], fill=(250, 250, 250, al))
    _credito(ImageDraw.Draw(im, "RGBA"), it, W, H, u, "escuro", k_out * _cl(t / ENTRA_S))
    return im


def _d_nome(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    im = _nova(W, H)
    k = _cl((dur - t) / SAI_S)
    a = _janela(t, 0.1, 0.5) * k

    def sombra():
        import numpy as np
        w = int(W * 0.6)
        g = np.clip(1 - np.linspace(0, 1, w), 0, 1) ** 1.6 * 120
        arr = np.zeros((H, w, 4), np.uint8)
        arr[..., 3] = g[None, :].astype(np.uint8)
        return Image.fromarray(arr, "RGBA")
    _cola(im, _cache(ctx, "nome_sombra", sombra), 0, 0, a)
    d = ImageDraw.Draw(im, "RGBA")
    x = W * 0.0625 + (1 - a) * -24 * u
    y = H * 0.278
    lw = 62 * u * _janela(t, 0.05, 0.45)
    if lw > 1:
        d.rectangle([x, y - 2 * u, x + lw, y + 1 * u], fill=_rgb(_acento(it)) + (int(255 * k),))
    camada = _cache(ctx, "nome_txt", lambda: _nome_txt(it, u))
    _cola(im, camada, x, y + 6 * u, a)
    _credito(d, it, W, H, u, "escuro", a)
    return im


def _nome_txt(it, u):
    from PIL import Image, ImageDraw
    fn, fc = _f("serif", 66 * u), _f("sans", 17 * u)
    w = int(max(fn.getlength(it.get("nome") or ""), _largura((it.get("cargo") or "").upper(), fc, 3.4 * u)) + 20 * u)
    c = Image.new("RGBA", (w, int(130 * u)), (0, 0, 0, 0))
    d = ImageDraw.Draw(c, "RGBA")
    d.text((0, int(62 * u)), it.get("nome") or "", font=fn, fill=(246, 244, 240, 255), anchor="ls")
    _espacado(d, 2 * u, int(100 * u), (it.get("cargo") or "").upper(), fc, (222, 220, 216, 235), 3.4 * u)
    return c


def _d_post(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    im = _nova(W, H)
    k = _cl((dur - t) / SAI_S)
    a = _janela(t, 0.0, 0.4) * k
    _cola(im, _cache(ctx, "post_escuro", lambda: Image.new("RGBA", (W, H), (0, 0, 0, 95))), 0, 0, _cl(t / ENTRA_S) * k)
    cw = int(W * (0.88 if _vert(W, H) else 0.63))
    pad = int(48 * u)
    ft, fn, fu, fd = _f("sans", 37 * u), _f("sans_b", 33 * u), _f("sans", 26 * u), _f("sans", 24 * u)
    linhas = _quebrar(it.get("texto") or "", ft, cw - 2 * pad)
    ch = pad + int(78 * u) + int(30 * u) + len(linhas) * int(54 * u) + int(26 * u) + (int(34 * u) if it.get("data") else 0) + pad - int(10 * u)

    def cartao():
        c = Image.new("RGBA", (cw + 2, ch + 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(c, "RGBA")
        d.rounded_rectangle([0, 0, cw, ch], radius=int(20 * u), fill=(4, 4, 6, 238), outline=(255, 255, 255, 30), width=max(1, int(u)))
        r = int(32 * u)
        cx, cy = pad + r, pad + r
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(58, 61, 68, 255))
        ini = (it.get("nome") or "?").strip()[:1].upper()
        d.text((cx, cy), ini, font=_f("sans_b", 30 * u), fill=(220, 222, 226, 255), anchor="mm")
        d.text((cx + r + int(18 * u), cy - int(4 * u)), it.get("nome") or "", font=fn, fill=(255, 255, 255, 255), anchor="ls")
        d.text((cx + r + int(18 * u), cy + int(30 * u)), it.get("usuario") or "", font=fu, fill=(130, 136, 145, 255), anchor="ls")
        rede = it.get("rede") or "x"
        ix = cw - pad
        if rede == "x":  # o logo do X (duas barras cruzadas), desenhado — nenhuma fonte tem o 𝕏
            s_ = 15 * u
            d.line([ix - 2 * s_, cy - s_, ix, cy + s_], fill=(255, 255, 255, 255), width=max(2, int(5 * u)))
            d.line([ix, cy - s_, ix - 2 * s_, cy + s_], fill=(255, 255, 255, 255), width=max(1, int(2 * u)))
        elif rede == "instagram":
            s = int(30 * u)
            d.rounded_rectangle([ix - s, cy - s // 2 - s // 2, ix, cy + s // 2], radius=int(9 * u), outline=(255, 255, 255, 255), width=max(2, int(2.6 * u)))
            d.ellipse([ix - s * 0.75, cy - s * 0.25, ix - s * 0.25, cy + s * 0.25], outline=(255, 255, 255, 255), width=max(2, int(2.4 * u)))
        else:
            d.text((ix, cy), {"threads": "@", "bluesky": "🦋", "linkedin": "in"}.get(rede, ""), font=_f("sans_b", 34 * u), fill=(255, 255, 255, 255), anchor="rm")
        y = pad + int(78 * u) + int(30 * u) + int(40 * u)
        for l in linhas:
            d.text((pad, y), l, font=ft, fill=(242, 242, 242, 255), anchor="ls")
            y += int(54 * u)
        if it.get("data"):
            d.text((pad, y + int(14 * u)), it.get("data"), font=fd, fill=(120, 126, 134, 255), anchor="ls")
        return c
    x0 = (W - cw) / 2
    y0 = H * 0.46 - ch / 2 - (1 - _janela(t, 0, 0.4)) * -22 * u
    sh, m = _cache(ctx, "post_sombra", lambda: _sombra(cw, ch, int(18 * u), 120, int(20 * u)))
    _cola(im, sh, x0 - m, y0 - m + 8 * u, a)
    _cola(im, _cache(ctx, "post_cartao", cartao), x0, y0, a)
    if it.get("traducao"):
        def trad():
            fi = _f("serif_i", 31 * u)
            ls = _quebrar("“" + it["traducao"].strip().strip('"“”') + "”", fi, cw)
            c = Image.new("RGBA", (cw, int(len(ls) * 40 * u + 20 * u)), (0, 0, 0, 0))
            d = ImageDraw.Draw(c, "RGBA")
            for i, l in enumerate(ls):
                d.text((0, int((i + 1) * 40 * u) - int(8 * u)), l, font=fi, fill=(214, 210, 204, 255), anchor="ls")
            return c
        _cola(im, _cache(ctx, "post_trad", trad), x0, y0 + ch + 26 * u, _janela(t, 0.75, 0.5) * k)
    _credito(ImageDraw.Draw(im, "RGBA"), it, W, H, u, "escuro", a)
    return im


def _tem_glifo(fonte, ch: str) -> bool:
    try:
        return fonte.getmask(ch).getbbox() is not None and fonte.getlength(ch) > 0
    except Exception:  # noqa: BLE001
        return False


def _titulo_medidas(it, W, H):
    u = _u(W, H)
    tit = (it.get("titulo") or "").upper()
    f100 = _f("serif", 100)
    larg = max(1.0, f100.getlength(tit))
    px = min(0.86 * W / larg * 100, (0.22 if not _vert(W, H) else 0.14) * H / 0.72)
    f = _f("serif", px)
    w = f.getlength(tit)
    x0 = (W - w) / 2
    return tit, f, x0, H * 0.43, u


def mascara(it, t, W, H):
    """titulo_video: 255 onde o vídeo aparece (dentro das letras)."""
    from PIL import Image, ImageDraw
    dur = it["end"] - it["start"]
    tit, f, x0, yb, _u_ = _titulo_medidas(it, W, H)
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    k = _k_tela(t, dur)
    n = max(1, len(tit.replace(" ", "")))
    passo = (0.45 * dur) / n
    x, j = x0, 0
    for ch in tit:
        if ch != " ":
            a = 0.16 + 0.84 * _janela(t, 0.15 + j * passo, 0.3)
            d.text((x, yb), ch, font=f, fill=int(255 * a * k), anchor="ls")
            j += 1
        x += f.getlength(ch)
    return m


def _d_titulo_video(it, t, W, H, ctx):
    """Só o que vai POR CIMA (definição digitada + crédito); as letras com vídeo vêm da máscara."""
    from PIL import ImageDraw
    dur = it["end"] - it["start"]
    im = _nova(W, H)
    d = ImageDraw.Draw(im, "RGBA")
    tit, f, x0, yb, u = _titulo_medidas(it, W, H)
    k = _k_tela(t, dur)
    d.rectangle([0, 0, W, H], fill=(0, 0, 0, int(250 * k)))
    sub = it.get("subtitulo") or ""
    if sub:
        n = int(len(sub) * _cl((t - 0.5 * dur) / max(0.3, 0.3 * dur)))
        fs = _f("serif", 40 * u)
        d.text((max(W * 0.05, x0), yb + 120 * u), sub[:n], font=fs, fill=(244, 242, 238, int(255 * k)), anchor="ls")
    _credito(d, it, W, H, u, "escuro", k)
    return im


def _d_terminal(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "escuro"
    im = _fundo(fundo, W, H).copy()
    d = ImageDraw.Draw(im, "RGBA")
    claro = fundo == "papel"
    x0 = W * (0.16 if not _vert(W, H) else 0.07)
    yh = H * 0.36
    if it.get("cabecalho"):
        _espacado(d, x0, yh, it["cabecalho"].upper(), _f("mono", 16 * u), (100, 96, 90) if claro else (108, 114, 124), 3.6 * u)
    fm = _f("mono", 31 * u if not _vert(W, H) else 26 * u)
    lh = int(56 * u)
    linhas = []
    for l in (it.get("linhas") or "").split("\n"):
        verm = l.startswith("!") or bool(re.search(r"^\s*\d{3}\b|ERRO|ERROR|NEGADO|DENIED|FALHOU|FAILED|BLOQUEADO", l))
        linhas.append((l[1:] if l.startswith("!") else l, verm))
    total = sum(len(l) + 6 for l, _v in linhas) or 1
    janela_dig = max(0.6, 0.85 * dur - 0.4)
    feitos = int(_cl((t - 0.3) / janela_dig) * total)
    vis, resto, digitando = [], feitos, False
    for l, verm in linhas:
        if resto <= 0:
            break
        n = min(len(l), resto)
        vis.append((l[:n], verm))
        if n < len(l):
            digitando = True
            break
        resto -= len(l) + 6
    vis = vis[-6:] or [("", False)]
    y = yh + 70 * u
    cor_n = (70, 66, 60) if claro else (206, 210, 215)
    cor_v = _rgb(_acento(it))
    for i, (l, verm) in enumerate(vis):
        d.text((x0, y + i * lh), l, font=fm, fill=cor_v if verm else cor_n, anchor="ls")
    ult, verm = vis[-1]
    if digitando or (t * 2) % 1 < 0.6:
        cx = x0 + fm.getlength(ult) + 2 * u
        cy = y + (len(vis) - 1) * lh
        d.rectangle([cx, cy - 26 * u, cx + 15 * u, cy + 6 * u], fill=cor_v if verm else cor_n)
    _credito(d, it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


def _pagina_falsa(it, w: int, h: int, u: float):
    """Página de notícia montada com a manchete (quando não tem print)."""
    from PIL import Image, ImageDraw
    c = Image.new("RGB", (w, h), (250, 250, 248))
    d = ImageDraw.Draw(c, "RGBA")
    m = int(w * 0.035)
    d.text((m, int(46 * u)), (it.get("site") or "").split("/")[0].upper(), font=_f("sans_b", 22 * u), fill=(30, 30, 30), anchor="ls")
    d.line([m, int(64 * u), w - m, int(64 * u)], fill=(220, 220, 220), width=max(1, int(u)))
    fh = _f("serif_b", 64 * u)
    y = int(150 * u)
    for l in _quebrar(it.get("titulo") or "", fh, w - 2 * m)[:3]:
        d.text((m, y), l, font=fh, fill=(28, 28, 30), anchor="ls")
        y += int(74 * u)
    if it.get("subtitulo"):
        for l in _quebrar(it["subtitulo"], _f("sans", 26 * u), w - 2 * m)[:2]:
            d.text((m, y + int(10 * u)), l, font=_f("sans", 26 * u), fill=(90, 90, 92), anchor="ls")
            y += int(36 * u)
    y += int(40 * u)
    d.rectangle([m, y, int(w * 0.48), h], fill=(40, 42, 48))
    d.rectangle([int(w * 0.5), y, w - m, h], fill=(70, 72, 90))
    return c


def _navegador(it, ctx, w: int, h: int, u: float):
    from PIL import Image, ImageDraw
    barra = int(46 * u)
    c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(c, "RGBA")
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=int(10 * u), fill=(236, 236, 236, 255))
    for i, cor in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = int((24 + i * 22) * u)
        d.ellipse([cx - 7 * u, barra / 2 - 7 * u, cx + 7 * u, barra / 2 + 7 * u], fill=cor)
    d.rounded_rectangle([int(110 * u), int(9 * u), int(w * 0.62), barra - int(9 * u)], radius=int(8 * u), fill=(250, 250, 250))
    d.text((int(138 * u), barra / 2 + 6 * u), it.get("site") or "", font=_f("sans", 17 * u), fill=(90, 90, 96), anchor="ls")
    pag = _img(ctx, it.get("imagem")) or _img(ctx, (ctx.get("prints") or {}).get(it.get("url") or "", "")) or _pagina_falsa(it, w, h - barra, u)
    pag = pag.resize((w, max(1, int(pag.height * w / pag.width))), Image.LANCZOS)
    pag = pag.crop((0, 0, w, h - barra)) if pag.height >= h - barra else pag
    c.paste(pag, (0, barra))
    # fundo da página some no escuro (como na referência)
    import numpy as np
    alt = h - barra
    g = np.clip((np.arange(alt) - alt * 0.72) / (alt * 0.28), 0, 1) ** 1.3
    arr = np.zeros((alt, w, 4), np.uint8)
    arr[..., :3] = (18, 21, 27)
    arr[..., 3] = (g[:, None] * 235).astype(np.uint8)
    c.alpha_composite(Image.fromarray(arr, "RGBA"), dest=(0, barra))
    return c


def _coef_perspectiva(dst, src):
    """Coeficientes do PIL (saída→entrada) que levam o quadrilátero src pro dst."""
    import numpy as np
    m = []
    for (x, y), (X, Y) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        m.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    a = np.array(m, dtype=float)
    b = np.array(src, dtype=float).reshape(8)
    return np.linalg.solve(a, b).tolist()


def _d_pagina(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "escuro"
    im = _fundo(fundo, W, H).copy()
    cw = int(W * (0.90 if _vert(W, H) else 0.62))
    ch = int(min(H * 0.66, cw * 0.62))
    nav = _cache(ctx, "pag_nav", lambda: _navegador(it, ctx, cw, ch, u))
    p = t / max(0.1, dur)
    s = 0.97 + 0.07 * p
    incl = 0.035 - 0.02 * p
    a = _janela(t, 0, 0.5)
    w2, h2 = cw * s, ch * s
    cx, cy = W / 2, H * 0.43 + (1 - a) * 40 * u - p * 8 * u
    tl = (cx - w2 / 2 + w2 * incl, cy - h2 / 2)
    tr = (cx + w2 / 2 - w2 * incl * 0.6, cy - h2 / 2 + h2 * 0.01)
    br = (cx + w2 / 2, cy + h2 / 2)
    bl = (cx - w2 / 2, cy + h2 / 2)
    xs, ys = [q[0] for q in (tl, tr, br, bl)], [q[1] for q in (tl, tr, br, bl)]
    bx0, by0 = int(min(xs)), int(min(ys))
    bw, bh = int(max(xs)) - bx0 + 2, int(max(ys)) - by0 + 2
    dst = [(q[0] - bx0, q[1] - by0) for q in (tl, tr, br, bl)]
    coef = _coef_perspectiva(dst, [(0, 0), (cw, 0), (cw, ch), (0, ch)])
    tr_img = nav.transform((bw, bh), Image.PERSPECTIVE, coef, Image.BICUBIC)
    sh, m = _cache(ctx, "pag_sombra", lambda: _sombra(cw, ch, int(30 * u), 170, int(10 * u)))
    _cola(im, sh.resize((int(sh.width * s), int(sh.height * s))), bx0 - m * s, by0 - m * s + 18 * u, a)
    _cola(im, tr_img, bx0, by0, a)
    _credito(ImageDraw.Draw(im, "RGBA"), it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


def _particulas(d, W, H, u, t, n=26, semente=3, cor=(200, 205, 215)):
    rng = random.Random(semente)
    for _ in range(n):
        x0, y0 = rng.random() * W, rng.random() * H
        vx, vy = (rng.random() - 0.5) * 18 * u, (rng.random() - 0.5) * 10 * u
        r = (0.8 + rng.random() * 2.2) * u
        al = int(30 + rng.random() * 70)
        x, y = (x0 + vx * t) % W, (y0 + vy * t) % H
        d.ellipse([x - r, y - r, x + r, y + r], fill=cor + (al,))


def _d_linha_tempo(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "escuro"
    im = _fundo(fundo, W, H).copy()
    d = ImageDraw.Draw(im, "RGBA")
    claro = fundo == "papel"
    itens = []
    for l in (it.get("itens") or "").split("\n"):
        if l.strip():
            a, _s, b = l.partition("|")
            itens.append((a.strip().upper(), b.strip()))
    n = max(1, len(itens))
    S = W * (0.27 if not _vert(W, H) else 0.52)
    X0 = W * 0.078
    seg = max(0.4, (dur - 0.8) / n)
    foco = -0.8 + 0.8 * _ease(t / 0.7)
    for kk in range(1, n):
        foco += _ease((t - 0.3 - kk * seg) / 0.75)
    yl = H * 0.5
    _particulas(d, W, H, u, t, cor=(120, 110, 95) if claro else (200, 205, 215))
    d.line([0, yl, W, yl], fill=(90, 84, 76, 90) if claro else (200, 205, 215, 60), width=max(1, int(1.2 * u)))
    if it.get("ano"):
        _espacado(d, X0, H * 0.195, it["ano"].upper(), _f("sans", 15 * u), (110, 104, 96) if claro else (120, 126, 136), 4 * u)
    ativo = int(round(_cl(foco, 0, n - 1)))
    for i, (rot, desc) in enumerate(itens):
        x = X0 + (i - foco) * S
        if x < -S or x > W + S:
            continue
        on = i == ativo
        perto = max(0.0, 1 - abs(i - foco))
        al = 0.32 + 0.68 * perto
        cor = (24, 22, 20) if claro else (238, 238, 240)
        f = _f("serif_i" if on else "serif", 80 * u)
        d.text((x, yl - 24 * u), rot, font=f, fill=cor + (int(255 * al),), anchor="ls")
        r = 4.5 * u
        d.ellipse([x + 6 * u - r, yl - r, x + 6 * u + r, yl + r], fill=cor + (int(255 * al),))
        if desc:
            d.text((x - 10 * u, yl + 50 * u), desc, font=_f("sans_i", 21 * u), fill=((90, 84, 76) if claro else (150, 156, 166)) + (int(255 * al),), anchor="ls")
    _credito(d, it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


def _d_grade_pontos(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "escuro"
    im = _fundo(fundo, W, H).copy()
    d = ImageDraw.Draw(im, "RGBA")
    claro = fundo == "papel"
    N = int(max(4, min(3000, it.get("total") or 666)))
    K = int(max(0, min(N, it.get("acesos") or 0)))
    cols = max(2, int(round(math.sqrt(N * 2.1))))
    rows = max(1, math.ceil(N / cols))
    ag = _janela(t, 0, 0.7)
    y0, y1 = H * 0.21, H * 0.64
    pos = []
    for idx in range(N):
        r, c = divmod(idx, cols)
        v = r / max(1, rows - 1)
        larg = W * (0.60 + 0.20 * v)
        x = W * 0.52 - larg / 2 + larg * (c / max(1, cols - 1))
        y = y0 + (y1 - y0) * (v ** 1.12)
        pos.append((x, y, v))
    cor_p = (90, 84, 76) if claro else (120, 128, 140)
    for (x, y, v) in pos:
        r = 2.1 * u * (0.8 + 0.45 * v)
        d.ellipse([x - r, y - r, x + r, y + r], fill=cor_p + (int(110 * ag),))
    rng = random.Random(str(it.get("id")))
    acesos = rng.sample(range(N), K) if K else []
    passo = (0.45 * dur) / max(1, K)
    for j, idx in enumerate(acesos):
        q = _janela(t, 0.45 + j * passo, 0.35)
        if q <= 0:
            continue
        x, y, v = pos[idx]
        r = (2.2 + 4.2 * q) * u
        d.ellipse([x - r * 2.2, y - r * 2.2, x + r * 2.2, y + r * 2.2], fill=((40, 36, 30) if claro else (255, 255, 255)) + (int(28 * q),))
        d.ellipse([x - r, y - r, x + r, y + r], fill=((30, 28, 24) if claro else (250, 250, 250)) + (int(255 * q),))
    if it.get("titulo"):
        _espacado(d, W * 0.078, H * 0.17, it["titulo"].upper(), _f("sans", 15 * u), (110, 104, 96) if claro else (118, 124, 134), 4 * u)
    cont = [l.partition("|") for l in (it.get("contadores") or "").split("\n") if l.strip()]
    for i, (num, _s, rot) in enumerate(cont):
        q = _janela(t, 0.35 * dur + i * 0.45, 0.4)
        if q <= 0:
            continue
        x = W * 0.078 + i * W * 0.125
        yb = H * 0.705
        cor_n = (24, 22, 20) if claro else ((175, 175, 180) if i == 0 and len(cont) > 1 else (240, 240, 242))
        d.text((x, yb), num.strip(), font=_f("serif", 74 * u), fill=cor_n + (int(255 * q),), anchor="ls")
        ultimo = i == len(cont) - 1 and len(cont) > 1
        _espacado(d, x, yb + 30 * u, rot.strip().upper(), _f("sans", 14 * u),
                  (_rgb(_acento(it)) if ultimo else ((110, 104, 96) if claro else (132, 138, 148))) + (int(255 * q),), 3.2 * u)
    _credito(d, it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


def _recorte_img(it, ctx, i, kicker, manchete, cw, ch, u):
    from PIL import Image, ImageDraw
    papel, m = _papel_retangulo(cw, ch, (236, 231, 218), 1.0, u)
    c = Image.new("RGBA", papel.size, (0, 0, 0, 0))
    c.alpha_composite(papel)
    d = ImageDraw.Draw(c, "RGBA")
    ox, oy = m, m - int(3 * u)
    pad = int(34 * u)
    if kicker:
        _espacado(d, ox + pad, oy + int(46 * u), kicker.upper(), _f("mono", 16 * u), _rgb(_acento(it)) + (255,), 3.0 * u)
    fh = _f("serif", 52 * u)
    y = oy + int(46 * u) + int(58 * u)
    for l in _quebrar(manchete, fh, cw - 2 * pad)[:2]:
        d.text((ox + pad, y), l, font=fh, fill=(30, 28, 25, 255), anchor="ls")
        y += int(58 * u)
    imgs = it.get("imagens") or []
    foto = _img(ctx, imgs[i]) if i < len(imgs) else None
    bloco_y = y - int(18 * u)
    if foto is not None:
        fw, fhh = int(cw * 0.42), max(10, oy + ch - pad - bloco_y)
        c.paste(_cobrir(foto, fw, fhh), (ox + pad, bloco_y))
        lx = ox + pad + fw + int(24 * u)
    else:
        lx = ox + pad
    for k in range(4):
        yy = bloco_y + int(10 * u) + k * int(22 * u)
        if yy > oy + ch - pad:
            break
        d.rectangle([lx, yy, ox + cw - pad - (k % 2) * int(60 * u), yy + int(7 * u)], fill=(178, 172, 160, 255))
    return c, m


_POS_RECORTES = [(-0.17, -0.11, -2.4), (0.11, -0.07, 1.3), (-0.07, 0.05, -0.9), (0.07, 0.11, 0.7), (-0.13, 0.15, 1.9), (0.15, 0.16, -1.5)]


def _d_recortes(it, t, W, H, ctx):
    from PIL import Image, ImageDraw, ImageFilter
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "mesa"
    comp = _fundo(fundo, W, H).copy()
    itens = []
    for l in (it.get("manchetes") or "").split("\n"):
        if l.strip():
            a, s, b = l.partition("|")
            itens.append((a.strip(), b.strip()) if s else ("", a.strip()))
    itens = itens[:6]
    n = max(1, len(itens))
    vert = _vert(W, H)
    cw, ch = int(W * (0.80 if vert else 0.40)), int(H * (0.22 if vert else 0.30))
    gap = min(1.1, (dur * 0.6) / n)
    cx0, cy0 = W * 0.45, H * 0.45
    for i, (kick, man) in enumerate(itens):
        ti = 0.25 + i * gap
        p = _cl((t - ti) / 0.5)
        if p <= 0:
            continue
        e = _ease(p)
        dx, dy, ang = _POS_RECORTES[i % len(_POS_RECORTES)]
        if vert:
            dx, dy = dx * 0.4, dy * 1.6
        base, m = _cache(ctx, f"rec_{i}", lambda i=i, kick=kick, man=man: _recorte_img(it, ctx, i, kick, man, cw, ch, u))
        nivel = int(round((1 - e) * 3))
        def borrado(nivel=nivel, base=base, i=i):
            r = _rotacionar(base, ang)
            return r.filter(ImageFilter.GaussianBlur(nivel * 5 * u)) if nivel else r
        rot = _cache(ctx, f"rec_{i}_b{nivel}", borrado)
        s = 1 + 0.45 * (1 - e)
        if abs(s - 1) > 0.002:
            rot = rot.resize((max(1, int(rot.width * s)), max(1, int(rot.height * s))), Image.BILINEAR)
        x = cx0 + dx * W - rot.width / 2
        y = cy0 + dy * H - rot.height / 2
        _cola(comp, rot, x, y, _cl(p * 3))
    tn = 0.25 + n * gap + 0.2
    if it.get("numero"):
        q = _janela(t, tn, 0.45)
        if q > 0:
            d = ImageDraw.Draw(comp, "RGBA")
            fx, fy = (W * 0.765, H * 0.36) if not vert else (W * 0.12, H * 0.84)
            fnum = _f("serif_i", 200 * u * (1 + 0.25 * (1 - q)))
            d.text((fx, fy), it["numero"], font=fnum, fill=_rgb(_acento(it)) + (int(255 * min(1, q * 1.5)),), anchor="ls")
            if it.get("rotulo_numero"):
                fl = _f("sans", 19 * u)
                ys = fy + 44 * u
                for l in _quebrar(it["rotulo_numero"].upper(), fl, W * (0.2 if not vert else 0.7))[:3]:
                    _espacado(d, fx, ys, l, fl, (232, 228, 220, int(255 * q)), 4 * u)
                    ys += 28 * u
    z = 1.10 - 0.10 * _ease(t / max(0.1, dur))
    if z > 1.001:
        cwz, chz = W / z, H / z
        comp = comp.crop((int((W - cwz) / 2), int((H - chz) / 2), int((W + cwz) / 2), int((H + chz) / 2))).resize((W, H), Image.BILINEAR)
    _credito(ImageDraw.Draw(comp, "RGBA"), it, W, H, u, "escuro")
    return _com_alfa(comp, _k_tela(t, dur))


def _foto_polaroid(foto, w: int, h: int, u: float, nome: str = "", pb: bool = True, borda: float = 12):
    from PIL import Image, ImageDraw, ImageEnhance, ImageOps
    b = int(borda * u)
    papel, m = _papel_retangulo(w, h, (246, 244, 238), 1.1, u)
    c = Image.new("RGBA", papel.size, (0, 0, 0, 0))
    c.alpha_composite(papel)
    iw, ih = w - 2 * b, h - 2 * b
    if foto is not None:
        f = _cobrir(foto, iw, ih)
        if pb:
            f = ImageEnhance.Contrast(ImageOps.grayscale(f).convert("RGB")).enhance(1.18)
    else:
        f = Image.new("RGB", (iw, ih), (70, 70, 72))
        dd = ImageDraw.Draw(f, "RGBA")
        dd.text((iw / 2, ih / 2), (nome or "?")[:1].upper(), font=_f("serif", ih * 0.3), fill=(150, 150, 152), anchor="mm")
    c.paste(f, (m + b, m - int(3 * u) + b))
    if nome:
        d = ImageDraw.Draw(c, "RGBA")
        _espacado(d, m + b + int(22 * u), m - int(3 * u) + h - b - int(26 * u), nome.upper(), _f("sans", 14 * u), (238, 238, 238, 235), 3.2 * u)
    return c, m


def _etiqueta(txt: str, u: float, fundo, cor_txt, px: float = 44):
    from PIL import Image, ImageDraw
    f = _f("serif", px * u)
    w = int(f.getlength(txt) + 40 * u)
    h = int(px * 1.45 * u)
    papel, m = _papel_retangulo(w, h, fundo, 0.9, u)
    c = Image.new("RGBA", papel.size, (0, 0, 0, 0))
    c.alpha_composite(papel)
    ImageDraw.Draw(c, "RGBA").text((m + w / 2, m - int(3 * u) + h * 0.66), txt, font=f, fill=cor_txt + (255,), anchor="ms")
    return c, m


def _d_mural(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = _fundo(fundo, W, H).copy()
    imgs = it.get("imagens") or []
    nomes = [l.strip() for l in (it.get("nomes") or "").split("\n")]
    cits = [l.strip() for l in (it.get("citacoes") or "").split("\n") if l.strip()]
    n = max(1, len(imgs), len(cits))
    vert = _vert(W, H)
    pw, ph = int(W * (0.62 if vert else 0.29)), int(H * (0.50 if vert else 0.70))
    gap = int(W * 0.04)
    passo = pw + gap
    larg = n * passo - gap
    xi0 = W * 0.06
    falta = max(0.0, xi0 + larg - W * 0.94)
    pan = falta * (0.5 - 0.5 * math.cos(math.pi * _cl(t / max(0.1, dur))))
    top = H * (0.13 if not vert else 0.22)
    angs = [-2.2, 1.4, -1.1, 2.0, -1.6, 1.0, -0.8, 1.7]
    for i in range(n):
        x = xi0 + i * passo - pan
        if x > W + 50 or x + pw < -50:
            continue
        foto = _img(ctx, imgs[i]) if i < len(imgs) else None
        nome = nomes[i] if i < len(nomes) else ""
        card, m = _cache(ctx, f"mur_{i}", lambda foto=foto, nome=nome: _foto_polaroid(foto, pw, ph, u, nome))
        rot = _cache(ctx, f"mur_{i}_r", lambda card=card, i=i: _rotacionar(card, angs[i % len(angs)]))
        dx, dy = (rot.width - card.width) / 2, (rot.height - card.height) / 2
        _cola(im, rot, x - m - dx, top - m - dy, 1.0)
    for i, cit in enumerate(cits[:n]):
        ti = 0.3 + i * (0.75 * dur / n)
        q = _janela(t, ti, 0.25)
        if q <= 0:
            continue
        ultimo = i == len(cits) - 1 and len(cits) > 1
        tag, m = _cache(ctx, f"mur_t{i}", lambda cit=cit, ultimo=ultimo: _etiqueta("“" + cit.strip('"“”') + "”", u,
                                                                                    _rgb(_acento(it)) if ultimo else (241, 237, 228),
                                                                                    (255, 255, 255) if ultimo else (30, 28, 25)))
        s = 0.82 + 0.18 * q
        tg = tag.resize((max(1, int(tag.width * s)), max(1, int(tag.height * s))), Image.BILINEAR) if s < 0.999 else tag
        x = xi0 + i * passo - pan - W * 0.045
        y = top + ph * 0.46
        _cola(im, tg, x - m * s, y - m * s, min(1, q * 2))
    _credito(ImageDraw.Draw(im, "RGBA"), it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


def janela(it: Dict[str, Any], W: int, H: int, ctx: Optional[Dict[str, Any]] = None) -> Optional[Tuple[int, int, int, int]]:
    """Retângulo (x, y, w, h) onde o VÍDEO do trecho entra (bilhetes sem imagem)."""
    if it.get("tipo") != "bilhetes" or (ctx is not None and _img(ctx, it.get("imagem"))) or (ctx is None and it.get("imagem")):
        return None
    x, y, w, h = _bilhete_foto(W, H)
    b = int(12 * _u(W, H))
    return (int(x + b) // 2 * 2, int(y + b) // 2 * 2, int(w - 2 * b) // 2 * 2, int(h - 2 * b) // 2 * 2)


def _bilhete_foto(W, H):
    if _vert(W, H):
        return W * 0.06, H * 0.08, W * 0.88, H * 0.36
    return W * 0.03, H * 0.12, W * 0.50, H * 0.62


def _d_bilhetes(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = _fundo(fundo, W, H).copy()
    fx, fy, fw, fh = _bilhete_foto(W, H)
    foto = _img(ctx, it.get("imagem"))
    if foto is not None:
        card, m = _cache(ctx, "bil_foto", lambda: _foto_polaroid(foto, int(fw), int(fh), u, "", pb=False))
        rot = _cache(ctx, "bil_foto_r", lambda: _rotacionar(card, 1.2))
        _cola(im, rot, fx - m - (rot.width - card.width) / 2, fy - m - (rot.height - card.height) / 2)
    else:  # moldura com um buraco: o vídeo do trecho entra aqui (ffmpeg) — o buraco é feito no fim
        papel, m = _cache(ctx, "bil_moldura", lambda: _papel_retangulo(int(fw), int(fh), (246, 244, 238), 1.1, u))
        _cola(im, papel, fx - m, fy - m + int(3 * u))
    notas = [l.strip() for l in (it.get("notas") or "").split("\n") if l.strip()][:5]
    vert = _vert(W, H)
    posicoes = ([(0.10, 0.50, -1.5), (0.40, 0.60, 1.8), (0.08, 0.72, -0.8), (0.42, 0.82, 1.2), (0.20, 0.90, -1.0)] if vert
                else [(0.575, 0.15, -1.5), (0.64, 0.40, 1.8), (0.555, 0.62, -0.8), (0.66, 0.78, 1.2), (0.58, 0.88, -1.0)])
    for i, txt in enumerate(notas):
        q = _janela(t, 0.5 + i * (0.6 * dur / max(1, len(notas))), 0.28)
        if q <= 0:
            continue
        ultimo = i == len(notas) - 1 and len(notas) > 1
        tag, m = _cache(ctx, f"bil_n{i}", lambda txt=txt, ultimo=ultimo: _etiqueta(txt, u, (240, 206, 84) if ultimo else (241, 237, 228), (30, 28, 25), 40))
        px_, py_, ang = posicoes[i]
        rot = _cache(ctx, f"bil_n{i}_r", lambda tag=tag, ang=ang: _rotacionar(tag, ang))
        s = 0.85 + 0.15 * q
        rr = rot.resize((max(1, int(rot.width * s)), max(1, int(rot.height * s))), Image.BILINEAR) if s < 0.999 else rot
        _cola(im, rr, W * px_ - m, H * py_ - m, min(1, q * 2))
    d = ImageDraw.Draw(im, "RGBA")
    if it.get("legenda"):
        _espacado(d, W * 0.038, fy + fh + 64 * u, it["legenda"].upper(), _f("sans", 17 * u), (104, 98, 90), 4.2 * u)
    _credito(d, it, W, H, u, fundo)
    out = _com_alfa(im, _k_tela(t, dur))
    jan = janela(it, W, H, ctx)
    if jan:
        jx, jy, jw, jh = jan
        out.paste((0, 0, 0, 0), (jx, jy, jx + jw, jy + jh))
    return out


def _d_reescrita(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = _fundo(fundo, W, H).copy()
    d = ImageDraw.Draw(im, "RGBA")
    claro = fundo != "escuro"
    tent = [l.strip() for l in (it.get("tentativas") or "").split("\n") if l.strip()][:5] or [""]
    f = _f("serif", (46 if not _vert(W, H) else 38) * u)
    x0, y0, lh = W * 0.09, H * 0.27, H * 0.105
    pausas = 0.35 + 0.35
    orc = max(1.0, 0.85 * dur - 0.4 - pausas * (len(tent) - 1) - (0.8 if it.get("rotulo") else 0))
    cps = _cl(sum(len(s) for s in tent) / orc, 10, 45)
    tc = 0.3
    acento = _rgb(_acento(it))
    cor_dig = (70, 66, 60) if claro else (200, 200, 205)
    for i, s in enumerate(tent):
        ult = i == len(tent) - 1
        td = len(s) / cps
        nchar = int(len(s) * _cl((t - tc) / max(0.05, td)))
        if t < tc:
            break
        y = y0 + i * lh
        risco = 0.0 if ult else _cl((t - (tc + td + 0.35)) / 0.35)
        cor = ((28, 26, 24) if claro else (240, 240, 240)) if ult else (cor_dig if risco <= 0 else ((130, 124, 116) if claro else (140, 140, 146)))
        d.text((x0, y), s[:nchar], font=f, fill=cor, anchor="ls")
        if nchar < len(s):
            cx = x0 + f.getlength(s[:nchar]) + 3 * u
            d.rectangle([cx, y - 40 * u, cx + 2.5 * u, y + 8 * u], fill=cor_dig)
            break
        if risco > 0:
            wl = f.getlength(s) * _ease(risco)
            d.rectangle([x0 - 4 * u, y - 15 * u, x0 - 4 * u + wl, y - 11 * u], fill=acento)
        tc += td + (0 if ult else pausas)
        if ult and it.get("rotulo"):
            r = it["rotulo"].upper()
            nr = int(len(r) * _cl((t - tc - 0.2) / 0.8))
            _espacado(d, x0, y + H * 0.12, r[:nr], _f("sans", 17 * u), acento, 4.2 * u)
    _credito(d, it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


def _fmt_num(v: float, casas: int) -> str:
    s = f"{v:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _d_numero(it, t, W, H, ctx):
    from PIL import ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = _fundo(fundo, W, H).copy()
    d = ImageDraw.Draw(im, "RGBA")
    claro = fundo != "escuro"
    de, ate = float(it.get("de") or 0), float(it.get("ate") or 0)
    casas = 0 if float(ate).is_integer() and float(de).is_integer() else 1
    v = de + (ate - de) * _ease((t - 0.15) / 1.1)
    f = _f("serif", (300 if not _vert(W, H) else 200) * u)
    x, yb = W * 0.065, H * 0.47
    cor = (24, 22, 20) if claro else (240, 240, 242)
    txt = (it.get("prefixo") or "") + _fmt_num(v, casas)
    d.text((x, yb), txt, font=f, fill=cor, anchor="ls")
    if it.get("sufixo"):
        d.text((x + f.getlength(txt) + 6 * u, yb), it["sufixo"], font=f, fill=_rgb(_acento(it)), anchor="ls")
    if it.get("rotulo"):
        q = _janela(t, 0.9, 0.5)
        _espacado(d, x + 10 * u, H * 0.565, it["rotulo"].upper(), _f("sans", 21 * u), ((70, 66, 60) if claro else (170, 175, 182)) + (int(255 * q),), 5 * u)
    if it.get("subtexto"):
        q = _janela(t, 1.3, 0.5)
        d.text((x + 10 * u, H * 0.635), it["subtexto"], font=_f("serif_i", 34 * u), fill=((60, 56, 52) if claro else (200, 200, 205)) + (int(255 * q),), anchor="ls")
    _credito(d, it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


@lru_cache(maxsize=4)
def _ruido(w: int, h: int, semente: int):
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(semente)
    tot = np.zeros((h, w), np.float32)
    amp, soma = 1.0, 0.0
    for esc in (4, 8, 16, 32):
        g = rng.random((max(2, h // esc), max(2, w // esc))).astype(np.float32)
        tot += amp * np.array(Image.fromarray((g * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32) / 255
        soma += amp
        amp *= 0.55
    return tot / soma


def _tinta(W, H, u, cx, cy, R):
    import numpy as np
    from PIL import Image
    q = 4
    w, h = W // q, H // q
    nz = _ruido(w, h, 11)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y = (xx * q - cx), (yy * q - cy)
    dcorpo = np.sqrt((x / (R * 0.62)) ** 2 + (y / R) ** 2) + 0.55 * (nz - 0.5)
    haste = np.where(yy * q < cy, np.abs(x) / (R * 0.30 + 1) + 0.6 * (nz - 0.5), 9)
    dd = np.minimum(dcorpo, haste)
    a = np.clip((1 - dd) / 0.10, 0, 1)
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2] = 16, 14, 12
    arr[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA").resize((W, H), Image.BILINEAR)


def _d_explosao(it, t, W, H, ctx):
    from PIL import Image, ImageDraw
    u, dur = _u(W, H), it["end"] - it["start"]
    fundo = it.get("fundo") or "papel"
    im = _fundo(fundo, W, H).copy()
    d = ImageDraw.Draw(im, "RGBA")
    claro = fundo != "escuro"
    cor_l = (120, 112, 100, 70) if claro else (200, 205, 215, 45)
    for k in range(16):
        pts = []
        fase = k * 0.7 + t * 0.35 * (1 if k % 2 else -1)
        for j in range(0, 61):
            x = W * j / 60
            y = H * (0.30 + 0.025 * k) + H * 0.05 * math.sin(x / W * 6.3 * (0.6 + 0.08 * k) + fase)
            pts.append((x, y))
        d.line(pts, fill=cor_l, width=max(1, int(1.1 * u)))
    texto = it.get("texto") or ""
    f = _f("serif", 92 * u)
    larg0 = sum(_fonte_do_char(f, ch).getlength(ch) for ch in texto)
    if larg0 > W * 0.9:
        f = _f("serif", 92 * u * W * 0.9 / larg0)
    tw = sum(_fonte_do_char(f, ch).getlength(ch) for ch in texto)
    x0, yb = (W - tw) / 2, H * 0.53
    t_exp = max(1.0, 0.35 * dur)
    cor_t = (24, 22, 20) if claro else (240, 240, 242)
    p = _cl((t - t_exp) / 0.9)
    rng = random.Random(str(it.get("id")) + texto)
    x = x0
    for ch in texto:
        fc = _fonte_do_char(f, ch)
        wch = fc.getlength(ch)
        vx, vy, vr = (rng.random() - 0.5) * 0.5 * W, (rng.random() - 0.65) * 0.5 * H, (rng.random() - 0.5) * 160
        if ch.strip():
            if p <= 0:
                d.text((x, yb), ch, font=fc, fill=cor_t, anchor="ls")
            elif p < 1:
                e = _ease(p)
                c = Image.new("RGBA", (int(wch + 40 * u), int(150 * u)), (0, 0, 0, 0))
                ImageDraw.Draw(c, "RGBA").text((20 * u, 110 * u), ch, font=fc, fill=cor_t + (255,), anchor="ls")
                c = c.rotate(vr * e, resample=Image.BICUBIC, expand=True)
                _cola(im, c, x - 20 * u + vx * e - (c.width - wch - 40 * u) / 2, yb - 110 * u + vy * e, 1 - p)
        x += wch
    if it.get("rotulo"):
        fr = _f("sans", 15 * u)
        r = it["rotulo"].upper()
        _espacado(d, (W - _largura(r, fr, 5 * u)) / 2, H * 0.645, r, fr, ((100, 94, 86) if claro else (150, 156, 166)) + (int(255 * (1 - p)),), 5 * u)
    q = _cl((t - t_exp + 0.15) / 1.5)
    if q > 0:
        R = H * (0.02 + 0.26 * _ease(q) + 0.03 * max(0, t - t_exp - 1.5))
        _cola(im, _tinta(W, H, u, W * 0.68, H * (0.10 + 0.18 * _ease(q)), R), 0, 0)
    if it.get("palavra_final"):
        a = _janela(t, t_exp + 0.5, 0.6)
        d.text((W * 0.08, H * 0.63), it["palavra_final"], font=_f("serif_i", 76 * u), fill=((40, 36, 32) if claro else (230, 230, 232)) + (int(255 * a),), anchor="ls")
    _credito(d, it, W, H, u, fundo)
    return _com_alfa(im, _k_tela(t, dur))


_DESENHOS = {"ficha": _d_ficha, "nome": _d_nome, "post": _d_post, "titulo_video": _d_titulo_video, "terminal": _d_terminal,
             "pagina": _d_pagina, "linha_tempo": _d_linha_tempo, "grade_pontos": _d_grade_pontos, "recortes": _d_recortes,
             "mural": _d_mural, "bilhetes": _d_bilhetes, "reescrita": _d_reescrita, "numero": _d_numero, "explosao": _d_explosao}


def novo_ctx(imagens: Optional[Dict[str, str]] = None, prints: Optional[Dict[str, str]] = None, pasta: str = "") -> Dict[str, Any]:
    return {"imagens": dict(imagens or {}), "prints": dict(prints or {}), "pasta": pasta, "_cache": {}}


def desenhar(it: Dict[str, Any], t: float, W: int, H: int, ctx: Optional[Dict[str, Any]] = None):
    """Quadro RGBA W×H do quadro editorial `it` no instante t (s desde o início dele)."""
    ctx = ctx if ctx is not None else novo_ctx()
    dur = float(it["end"]) - float(it["start"])
    q = _DESENHOS[it["tipo"]](it, _cl(t, 0, dur), W, H, ctx)
    return q if q.mode == "RGBA" else q.convert("RGBA")


def previa_png(it: Dict[str, Any], t: float, W: int, H: int, destino: str, ctx: Optional[Dict[str, Any]] = None) -> str:
    """Quadro da prévia (no titulo_video, as letras viram branco translúcido sobre preto)."""
    from PIL import Image
    ctx = ctx if ctx is not None else novo_ctx()
    q = desenhar(it, t, W, H, ctx)
    if it["tipo"] == "titulo_video":  # na telinha as letras ficam claras (o vídeo dentro delas só no vídeo final)
        letras = Image.new("RGBA", (W, H), (235, 228, 220, 0))
        letras.putalpha(mascara(it, t, W, H).point(lambda v: int(v * 0.9)))
        q.alpha_composite(letras)
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    q.save(destino)
    return destino



# ------------------------------------------------------------------ print de uma página (tipo "pagina" com link)
def capturar_print(url: str, pasta: str, timeout_ms: int = 30000) -> Optional[str]:
    """Print do topo da página (1440×900, como um navegador) — guardado por link. None se não abrir."""
    if not re.match(r"^https?://", url or "", re.I):
        return None
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, "print_" + hashlib.md5(url.encode()).hexdigest()[:12] + ".png")
    if os.path.exists(destino):
        return destino
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
                pg.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                pg.wait_for_timeout(1500)
                pg.screenshot(path=destino)
            finally:
                b.close()
    except Exception:  # noqa: BLE001
        return None
    return destino if os.path.exists(destino) else None


# ------------------------------------------------------------------ vídeo (.mov com alfa) + o passe do ffmpeg
def _ff(args: List[str], timeout: int = 1800) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-600:])


def _quadros_para_mov(gerar, n: int, pasta: str, saida: str, modo: str) -> str:
    """gerar(i) -> PIL, mandado cru pro ffmpeg pelo stdin (sem PNG no disco): RGBA vira ProRes 4444
    com alfa (leve e rápido de ler), a máscara (L) vira FFV1 cinza. O desenho e a compressão rodam juntos."""
    q0 = gerar(0)
    W, H = q0.size
    fmt = "rgba" if modo == "RGBA" else "gray"
    codec = (["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-qscale:v", "11", "-vendor", "apl0"] if modo == "RGBA"
             else ["-c:v", "ffv1", "-pix_fmt", "gray"])
    tmp = saida + ".tmp" + os.path.splitext(saida)[1]
    p = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", fmt, "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-"] + codec + [tmp], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        anterior = None
        for i in range(n):
            q = q0 if i == 0 else gerar(i)
            b = q.tobytes()
            p.stdin.write(b if b != anterior else anterior)
            anterior = b
        p.stdin.close()
        erro = p.stderr.read().decode("utf-8", "replace")
        if p.wait(timeout=1800) != 0:
            raise RuntimeError(f"ffmpeg falhou ao gerar o quadro editorial: {erro.strip()[-400:]}")
    except BrokenPipeError:
        p.wait()
        raise RuntimeError("ffmpeg fechou no meio do quadro editorial: " + p.stderr.read().decode("utf-8", "replace")[-400:])
    os.replace(tmp, saida)
    return saida


def renderizar(it: Dict[str, Any], W: int, H: int, pasta: str, ctx: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """{"mov": quadro com alfa, "mascara": só no titulo_video} — guardados pelo conteúdo (não refaz)."""
    os.makedirs(pasta, exist_ok=True)
    chave = hashlib.md5(json.dumps([it, W, H, sorted((ctx.get("imagens") or {}).items()), sorted((ctx.get("prints") or {}).items()), 2],
                                   sort_keys=True, default=str).encode()).hexdigest()[:12]
    dur = float(it["end"]) - float(it["start"])
    n = max(1, int(round(dur * FPS)))
    mov = os.path.join(pasta, f"ed_{it['tipo']}_{chave}.mov")
    if not os.path.exists(mov):
        _quadros_para_mov(lambda i: desenhar(it, i / FPS, W, H, ctx), n, pasta, mov, "RGBA")
    out: Dict[str, Optional[str]] = {"mov": mov, "mascara": None}
    if it["tipo"] == "titulo_video":
        m = os.path.join(pasta, f"ed_mask_{chave}.mkv")
        if not os.path.exists(m):
            _quadros_para_mov(lambda i: mascara(it, i / FPS, W, H), n, pasta, m, "L")
        out["mascara"] = m
    return out


def _grupos(itens: List[Dict[str, Any]], fps: int) -> List[Tuple[int, int, List[Dict[str, Any]]]]:
    """Janelas (quadro inicial, quadro final) que juntam quadros que se encostam/sobrepõem."""
    out: List[Tuple[int, int, List[Dict[str, Any]]]] = []
    for it in sorted(itens, key=lambda x: float(x["start"])):
        a, b = int(math.floor(float(it["start"]) * fps)), int(math.ceil(float(it["end"]) * fps))
        if out and a <= out[-1][1]:
            fa, fb, lst = out[-1]
            out[-1] = (fa, max(fb, b), lst + [it])
        else:
            out.append((a, b, [it]))
    return out


def _janela_com_quadros(video_in: str, saida: str, f0: int, f1: int, itens: List[Dict[str, Any]], W: int, H: int,
                        work_dir: str, imagens, prints) -> None:
    """Só o pedaço [f0, f1) do vídeo, com os quadros por cima (as entradas são poucas e curtas)."""
    s0 = f0 / FPS
    entradas = ["-ss", f"{s0:.4f}", "-i", video_in]
    grafo = [f"[0:v]fps={FPS},scale={W}:{H},setsar=1,setpts=PTS-STARTPTS,format=yuv420p[c0]"]
    cur, idx = "c0", 1
    for k, it in enumerate(itens, start=1):
        ctx = novo_ctx(imagens, prints, work_dir)
        r = renderizar(it, W, H, os.path.join(work_dir, "quadros"), ctx)
        a, b = float(it["start"]) - s0, float(it["end"]) - s0
        en = f"between(t,{a:.3f},{b:.3f})"
        entradas += ["-itsoffset", f"{a:.4f}", "-i", r["mov"]]
        im_ = idx
        idx += 1
        grafo.append(f"[{im_}:v]format=rgba[e{k}]")
        if it["tipo"] == "post":
            grafo.append(f"[{cur}]gblur=sigma={max(6, H // 45)}:enable='{en}'[g{k}]")
            cur = f"g{k}"
        jan = janela(it, W, H, ctx)
        if it["tipo"] == "titulo_video" and r["mascara"]:
            entradas += ["-itsoffset", f"{a:.4f}", "-i", r["mascara"]]
            mk = idx
            idx += 1
            grafo.append(f"[{cur}]split=2[s{k}a][s{k}b]")
            grafo.append(f"[s{k}b]trim=start={max(0.0, a):.3f}:end={b:.3f},setpts=PTS-STARTPTS,format=yuva420p[t{k}]")
            grafo.append(f"[{mk}:v]setpts=PTS-STARTPTS,format=gray,scale={W}:{H}[m{k}]")
            grafo.append(f"[t{k}][m{k}]alphamerge,setpts=PTS+{max(0.0, a):.3f}/TB[f{k}]")
            grafo.append(f"[s{k}a][e{k}]overlay=0:0:eof_action=pass:format=auto:enable='{en}'[o{k}]")
            grafo.append(f"[o{k}][f{k}]overlay=0:0:eof_action=pass:format=auto:enable='{en}'[c{k}]")
        elif jan:
            jx, jy, jw, jh = jan
            grafo.append(f"[{cur}]split=2[s{k}a][s{k}b]")
            grafo.append(f"[s{k}b]trim=start={max(0.0, a):.3f}:end={b:.3f},setpts=PTS-STARTPTS,scale={jw}:{jh}:force_original_aspect_ratio=increase,"
                         f"crop={jw}:{jh},setpts=PTS+{max(0.0, a):.3f}/TB[v{k}]")
            grafo.append(f"[s{k}a][e{k}]overlay=0:0:eof_action=pass:format=auto:enable='{en}'[o{k}]")
            grafo.append(f"[o{k}][v{k}]overlay={jx}:{jy}:eof_action=pass:enable='{en}'[c{k}]")
        else:
            grafo.append(f"[{cur}][e{k}]overlay=0:0:eof_action=pass:format=auto:enable='{en}'[c{k}]")
        cur = f"c{k}"
    grafo.append(f"[{cur}]format=yuv420p[vout]")
    _ff(entradas + ["-filter_complex", ";".join(grafo), "-map", "[vout]", "-frames:v", str(f1 - f0), "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS), saida], timeout=3600)


def _pedaco(video_in: str, saida: str, f0: int, f1: int, W: int, H: int) -> None:
    _ff(["-ss", f"{f0 / FPS:.4f}", "-i", video_in, "-vf", f"fps={FPS},scale={W}:{H},setsar=1,format=yuv420p", "-frames:v", str(f1 - f0), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", "-r", str(FPS), saida], timeout=3600)


def aplicar_editoriais(video_in: str, video_out: str, itens: List[Dict[str, Any]], W: int, H: int, work_dir: str,
                       imagens: Optional[Dict[str, str]] = None, paleta: Optional[Dict[str, str]] = None) -> str:
    """Põe os quadros no vídeo: cada janela com quadros vira um pedaço próprio (post desfoca o vídeo por
    baixo; titulo_video põe o vídeo dentro das letras; bilhetes sem imagem põe o vídeo do trecho na
    moldura); o resto do vídeo vira pedaços sem mexer; tudo é juntado com o áudio original.

    (Antes era um passe só com todos os quadros como entradas do ffmpeg: ele lia todos desde o começo
    e guardava na memória até a hora de cada um — com vários quadros em 1080p a memória estourava.)"""
    from video_assembler import _probe_duration
    validos = [x for x in (normalizar(i) for i in itens or []) if x]
    if not validos:
        return video_in
    os.makedirs(work_dir, exist_ok=True)
    dur = _probe_duration(video_in)
    total = int(round(dur * FPS))
    prints: Dict[str, str] = {}
    for it in validos:
        if it["tipo"] == "pagina" and it.get("url") and not it.get("imagem"):
            p = capturar_print(it["url"], os.path.join(work_dir, "prints"))
            if p:
                prints[it["url"]] = p
    pecas = os.path.join(work_dir, "pecas_" + hashlib.md5(video_in.encode()).hexdigest()[:6])
    shutil.rmtree(pecas, ignore_errors=True)
    os.makedirs(pecas)
    lista, pos, n = [], 0, 0
    for (f0, f1, grupo) in _grupos(validos, FPS):
        f0, f1 = max(0, min(f0, total)), max(0, min(f1, total))
        if f1 <= f0:
            continue
        if f0 > pos:
            n += 1
            arq = os.path.join(pecas, f"p{n:03d}.mp4")
            _pedaco(video_in, arq, pos, f0, W, H)
            lista.append(arq)
        n += 1
        arq = os.path.join(pecas, f"p{n:03d}.mp4")
        _janela_com_quadros(video_in, arq, f0, f1, grupo, W, H, work_dir, imagens, prints)
        lista.append(arq)
        pos = f1
    if pos < total:
        n += 1
        arq = os.path.join(pecas, f"p{n:03d}.mp4")
        _pedaco(video_in, arq, pos, total, W, H)
        lista.append(arq)
    txt = os.path.join(pecas, "lista.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("".join(f"file '{os.path.abspath(a)}'\n" for a in lista))
    import qualidade_export
    r = qualidade_export.rodar(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", txt, "-i", video_in,
                                "-map", "0:v", "-map", "1:a?", "-t", f"{dur:.3f}", "-c:v", "copy", "-c:a", "copy", video_out], timeout=3600)
    shutil.rmtree(pecas, ignore_errors=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou nos quadros editoriais: {r.stderr.strip()[-600:]}")
    return video_out


# ------------------------------------------------------------------ exemplos (miniaturas da galeria e quadro novo no Estúdio)
EXEMPLOS: Dict[str, Dict[str, Any]] = {
    "ficha": {"rotulo": "Entrevistada", "nome": "Helena Duarte", "linhas": "Cargo: Diretora de pesquisa\nNo cargo desde: Março de 2021\nÁrea: Inteligência artificial\nFala: Entrevista · out/2026", "ponto_x": 0.33, "ponto_y": 0.38, "_t": 2.6},
    "nome": {"nome": "Helena Duarte", "cargo": "Diretora de pesquisa", "credito": "Entrevista", "_t": 1.8},
    "post": {"nome": "Ana Ribeiro", "usuario": "@anaribeiro", "texto": "\"Nobody expected this to happen so fast. We are not ready.\"", "data": "8 de out. de 2026",
             "traducao": "Ninguém esperava que isso acontecesse tão rápido. Não estamos prontos.", "credito": "Post no X", "_t": 3.0},
    "titulo_video": {"titulo": "Virada", "subtitulo": "o momento em que tudo muda de uma vez", "_t": 3.8},
    "terminal": {"cabecalho": "Sistema · log interno · 11/10/2026", "linhas": "> tarefa: baixar relatório público\n> conectando ao servidor...\n!403 ACESSO NEGADO\n> tentando de novo...\n!403 ACESSO NEGADO", "_t": 7.0},
    "pagina": {"site": "jornal.com/noticia", "titulo": "Sistema automático faz em horas o que levava meses", "subtitulo": "Especialistas dizem que o ritmo surpreendeu até os criadores", "credito": "Jornal · 11/10/2026", "_t": 2.5},
    "linha_tempo": {"ano": "2026", "itens": "JUN | O primeiro aviso\nJUL | O recorde\nAGO | A virada\nSET | Dois lançamentos\nOUT | Tudo em 2 horas", "_t": 4.2},
    "grade_pontos": {"titulo": "Competição internacional · 2026", "total": 666, "acesos": 7, "contadores": "666 | competidores\n7 | nota máxima\n1 | máquina", "_t": 4.2},
    "recortes": {"manchetes": "22 de setembro | Primeiro lançamento do mês\nMesmo dia | Concorrente responde\n25 de setembro | Mais um modelo novo\n29 de setembro | O quarto em uma semana", "numero": "4", "rotulo_numero": "lançamentos em um mês", "_t": 6.0},
    "mural": {"nomes": "Pesquisadora\nEmpresário\nProfessor", "citacoes": "em poucos anos\nmetade dos empregos\nopcional", "_t": 4.5},
    "bilhetes": {"notas": "escreve um texto\ncorrige aqui\nreescreve", "legenda": "Até pouco tempo atrás", "credito": "Vídeo ilustrativo", "_t": 5.0},
    "reescrita": {"tentativas": "Prezado cliente, segue o relatorio\nPrezado cliente, segue o relatório do mês\nOlá, Marina! Segue o relatório de setembro.", "rotulo": "Você conferindo cada passo", "_t": 6.6},
    "numero": {"de": 64, "ate": 98, "sufixo": "%", "rotulo": "Prova · nível 4 · a parte mais difícil", "subtexto": "segundo a própria empresa", "credito": "Fonte · site oficial", "_t": 3.0},
    "explosao": {"texto": "∂u/∂t + (u·∇)u = −∇p + ν∇²u", "rotulo": "Equações de Navier-Stokes", "palavra_final": "explodem.", "credito": "O que o estudo diz", "_t": 1.7},
}


def exemplo(tipo: str, start: float = 0.0) -> Dict[str, Any]:
    """Quadro novo com o texto de exemplo (o Estúdio põe no cursor e a pessoa troca os textos)."""
    t = TIPOS[tipo]
    base = {k: v for k, v in EXEMPLOS.get(tipo, {}).items() if not k.startswith("_")}
    return normalizar(dict(base, tipo=tipo, start=start, end=start + t["dur"])) or {}


def gerar_miniaturas(pasta: str, fundo_foto: Optional[str] = None, so: Optional[List[str]] = None, W: int = 480, H: int = 270) -> int:
    """galeria/editorial/<tipo>.jpg — um quadro de cada tipo com o texto de exemplo."""
    from PIL import Image
    os.makedirs(pasta, exist_ok=True)
    feitas = 0
    for tipo, ex in EXEMPLOS.items():
        if so is not None and tipo not in so:
            continue
        it = exemplo(tipo)
        q = desenhar(it, ex.get("_t", 2.0), W * 2, H * 2, novo_ctx())
        if tipo == "titulo_video":
            letras = Image.new("RGBA", q.size, (235, 228, 220, 0))
            letras.putalpha(mascara(it, ex.get("_t", 2.0), W * 2, H * 2).point(lambda v: int(v * 0.9)))
            q.alpha_composite(letras)
        bg = Image.open(fundo_foto).convert("RGBA").resize(q.size) if fundo_foto and os.path.exists(fundo_foto) else Image.new("RGBA", q.size, (40, 40, 44, 255))
        bg.alpha_composite(q)
        bg.convert("RGB").resize((W, H), Image.LANCZOS).save(os.path.join(pasta, f"{tipo}.jpg"), quality=86)
        feitas += 1
    return feitas


# 📅 v84_93 — calendário marcado, ano inteiro, folhinha de parede, placar de datas e lista riscada (dp_calendario.py)
import dp_calendario as _calendario  # noqa: E402
if hasattr(_calendario, "registrar"):  # importado por dp_calendario primeiro: ele mesmo registra no fim
    _calendario.registrar()
import dp_escrita as _escrita  # noqa: E402  ✍️ v84_94
if hasattr(_escrita, "registrar"):
    _escrita.registrar()
