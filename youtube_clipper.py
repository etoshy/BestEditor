"""
youtube_clipper.py
=====================

"Cortar do YouTube" — cola um (ou vários) link(s) de vídeo do YouTube,
define os trechos que quer (com descrição opcional pra cada um, tipo
"00:12 até 01:45 — gameplay"), escolhe a qualidade, e o site baixa o
vídeo inteiro uma vez só e corta os trechos pedidos — tudo isso pra
cada link, se você colar vários de uma vez. No final, monta um `.zip`
com os clipes cortados + um `info.json` dizendo, pra cada vídeo
original: título, link, e a lista dos clipes cortados dele (nome do
arquivo, início/fim, e a descrição que você deu).

O download em si usa `yt-dlp` — o parâmetro `ytdlp_module` de
`baixar_video()` existe pra poder injetar um "yt-dlp" falso nos testes
(sem precisar de internet de verdade pra baixar um vídeo do YouTube só
pra testar); em uso normal, deixe esse parâmetro de fora.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional


class YoutubeClipperError(Exception):
    """URL inválida, yt-dlp não instalado, trecho fora da duração do
    vídeo, ffmpeg falhou ao cortar, etc."""


# Formatos do yt-dlp pra cada opção de qualidade -- sempre com um teto
# de altura (exceto "melhor"), então se aquela qualidade não existir
# pro vídeo, cai pra melhor disponível ABAIXO do teto, nunca acima.
QUALIDADES: Dict[str, str] = {
    # vídeo e áudio SEPARADOS (é assim que o YouTube entrega acima de 360p) + junta com ffmpeg;
    # "b" (vídeo único) só como último recurso
    "1080p": "bv*[height<=1080]+ba/bv*+ba/b[height<=1080]/b",  # "Full HD", padrão
    "720p": "bv*[height<=720]+ba/bv*+ba/b[height<=720]/b",
    "480p": "bv*[height<=480]+ba/bv*+ba/b[height<=480]/b",
    "melhor": "bv*+ba/b",  # sem teto -- a melhor que existir, pode passar de 1080p
}
# altura que a qualidade pede (usada pra conferir o que veio e ordenar os formatos)
ALTURA_ALVO: Dict[str, Optional[int]] = {"1080p": 1080, "720p": 720, "480p": 480, "melhor": None}
# clientes do YouTube tentados em ordem. O "android" sozinho hoje costuma entregar só 360p:
# fica por último, e o resultado de cada tentativa é MEDIDO — se veio abaixo do pedido, tenta o próximo
# e fica com o melhor.
CLIENTES_YOUTUBE: List[Optional[List[str]]] = [None, ["tv", "web_safari"], ["mweb"], ["android"]]
QUALIDADE_PADRAO = "1080p"


def parse_tempo(texto: str) -> float:
    """Converte um tempo escrito como "MM:SS" ou "HH:MM:SS" (aceita
    também só segundos, "SS") em segundos — ex: "01:45" -> 105.0,
    "01:00:34" -> 3634.0.
    """
    texto = (texto or "").strip()
    if not texto:
        raise YoutubeClipperError("Tempo vazio.")
    partes = texto.split(":")
    if len(partes) > 3 or len(partes) == 0:
        raise YoutubeClipperError(f"Tempo {texto!r} inválido — use MM:SS ou HH:MM:SS.")
    try:
        numeros = [float(p) for p in partes]
    except ValueError:
        raise YoutubeClipperError(f"Tempo {texto!r} inválido — use só números e ':'.")
    for n in numeros:
        if n < 0:
            raise YoutubeClipperError(f"Tempo {texto!r} não pode ser negativo.")

    segundos = 0.0
    for n in numeros:
        segundos = segundos * 60 + n
    return segundos


# ----------------------------------------------------------- colar texto -> itens
# Interpreta um texto livre com links e tempos (o que a pessoa cola de uma
# anotação, de uma IA ou dos capítulos de um vídeo) e monta os `itens` de
# `processar_pedido`. Aceita, por exemplo:
#
#   https://youtu.be/abc123
#   0:15 - 0:42 chegada do herói
#   1:10 a 1:30 | a luta
#   de 2:00 até 2:20 - final
#   2:40 até o fim
#
#   https://www.youtube.com/watch?v=xyz 00:05-00:20 abertura
#   https://youtu.be/qqq            (sem tempo = o vídeo inteiro)
#   explosão: 45s - 1m20s           (descrição antes do tempo também vale)
_RE_URL = re.compile(r"(?:https?://)?(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/[^\s<>\"'\)\]]+|https?://[^\s<>\"'\)\]]+",
                     re.IGNORECASE)
_T = r"(?:\d{1,2}:\d{1,2}:\d{1,2}(?:[.,]\d+)?|\d{1,3}:\d{1,2}(?:[.,]\d+)?|\d+\s*h\s*\d*\s*m?\s*\d*\s*s?|\d+\s*m(?:in)?\s*\d*\s*s?|\d+(?:[.,]\d+)?\s*s(?:eg)?)"
_SEP = r"\s*(?:-{1,2}|–|—|→|->|>|~|\bat[eé]\b|\ba\b|\bao\b|\bto\b|\buntil\b)\s*"
_FIM_TXT = r"(?:o\s+)?(?:fim|final|end)(?:\s+do\s+v[ií]deo)?"
_RE_FAIXA = re.compile(r"(?:\bde\s+|\bfrom\s+)?\[?(" + _T + r")\]?(?:" + _SEP + r"\[?(" + _T + r"|" + _FIM_TXT + r")\]?|\s*(-|–|—|→)\s*(?=$|\s*[|:,;]|\s+[^\d\s]))",
                       re.IGNORECASE)
_RE_CAPITULO = re.compile(r"^\[?(" + _T + r")\]?\s+(?![-–—→>~]|(?:at[eé]|a|ao|to)\s+\d)(.+)$", re.IGNORECASE)
_RE_SO_INICIO = re.compile(r"(?:\ba\s+partir\s+de|\bdesde|\bfrom)\s+(" + _T + r")", re.IGNORECASE)
_RE_MARCADOR = re.compile(r"^\s*(?:[-*•▪►▶➤]+|\d{1,3}[.)]\s+|#\d+\s*)\s*")
_RE_LIXO_BORDA = re.compile(r"^[\s|:;,–—\-·•]+|[\s|:;,–—\-·•]+$")


def _tempo_flex(t: str) -> float:
    """"1:23" / "01:02:03" / "45s" / "1m20s" / "1h2m" / "90" -> segundos."""
    t = (t or "").strip().lower().replace(",", ".")
    if ":" in t:
        return parse_tempo(t)
    m = re.fullmatch(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?\s*(?:(\d+(?:\.\d+)?)\s*s(?:eg)?)?", t)
    if m and any(m.groups()):
        h, mi, se = (float(x) if x else 0.0 for x in m.groups())
        return h * 3600 + mi * 60 + se
    return float(t)


def _limpa_desc(texto: str) -> str:
    return re.sub(r"\s{2,}", " ", _RE_LIXO_BORDA.sub("", texto or "")).strip()[:200]


def interpretar_texto(texto: str) -> Dict[str, Any]:
    """Texto colado -> {"itens": [{"url", "trechos": [{"inicio","fim","descricao"}]}], "avisos": [...]}.
    `inicio`/`fim` saem como "HH:MM:SS" ("" no fim = até o fim do vídeo). Vídeo sem
    nenhum tempo vira um trecho com o vídeo inteiro. O mesmo link repetido junta os trechos."""
    itens: List[Dict[str, Any]] = []
    por_url: Dict[str, Dict[str, Any]] = {}
    avisos: List[str] = []
    atual: Optional[Dict[str, Any]] = None
    desc_pendente = ""

    def _novo(url: str) -> Dict[str, Any]:
        url = url.rstrip(".,;")
        if not url.lower().startswith("http"):
            url = "https://" + url
        if url in por_url:
            return por_url[url]
        item = {"url": url, "trechos": [], "_desc_video": "", "_capitulos": []}
        por_url[url] = item
        itens.append(item)
        return item

    for n, linha_bruta in enumerate((texto or "").splitlines(), start=1):
        linha = _RE_MARCADOR.sub("", linha_bruta).strip()
        if not linha:
            continue
        urls = list(_RE_URL.finditer(linha))
        for u in urls:
            # texto solto antes do link: descreve o vídeo anterior (se ele ainda não tem tempo)
            # ou é o título deste
            anterior_sem_tempo = atual is not None and not atual["trechos"] and not atual["_capitulos"]
            if desc_pendente and anterior_sem_tempo and not atual["_desc_video"]:
                atual["_desc_video"], desc_pendente = desc_pendente, ""
            atual = _novo(u.group(0))
            if desc_pendente and not atual["_desc_video"]:
                atual["_desc_video"] = desc_pendente
            desc_pendente = ""
        resto = _RE_URL.sub(" ", linha)
        faixas = list(_RE_FAIXA.finditer(resto))
        so_inicio = None if faixas else _RE_SO_INICIO.search(resto)
        capitulo = None if (faixas or so_inicio) else _RE_CAPITULO.match(resto.strip())
        if capitulo and atual is not None:
            # lista de capítulos ("0:00 Intro", "1:23 Parte 2"): cada um vai até o início do próximo
            try:
                atual["_capitulos"].append((_tempo_flex(capitulo.group(1)), _limpa_desc(capitulo.group(2))))
            except (YoutubeClipperError, ValueError):
                avisos.append(f"Linha {n}: tempo inválido ({capitulo.group(1)}) — ignorado.")
            continue
        if not faixas and not so_inicio:
            if re.fullmatch(r"[^:]{1,40}:\s*", resto.strip()) and not urls:
                continue  # cabeçalho tipo "Capítulos:" / "Trechos:"
            desc = _limpa_desc(resto)
            if desc and not urls:
                if atual is None:
                    desc_pendente = desc  # título antes do 1º link
                elif atual["trechos"] or atual["_capitulos"]:
                    if atual["trechos"] and not atual["trechos"][-1]["descricao"]:
                        atual["trechos"][-1]["descricao"] = desc
                    else:
                        desc_pendente = desc  # provável título do próximo link
                elif not atual["_desc_video"]:
                    atual["_desc_video"] = desc
                else:
                    desc_pendente = desc
            elif desc and urls and not atual["_desc_video"]:
                atual["_desc_video"] = desc  # "link  descrição" na mesma linha, sem tempo
            continue
        if atual is None:
            avisos.append(f"Linha {n}: tem tempo mas nenhum link antes — ignorada: {linha_bruta.strip()[:80]}")
            continue
        # descrição = o texto da linha sem os tempos (antes ou depois deles)
        sobra = _RE_FAIXA.sub(" ", resto) if faixas else resto.replace(so_inicio.group(0), " ")
        desc = _limpa_desc(sobra) or desc_pendente
        desc_pendente = ""
        pares = ([(f.group(1), f.group(2) or "") for f in faixas] if faixas else [(so_inicio.group(1), "")])
        for k, (ini_txt, fim_txt) in enumerate(pares):
            try:
                ini = _tempo_flex(ini_txt)
                fim = None if (not fim_txt or re.fullmatch(_FIM_TXT, fim_txt.strip(), re.IGNORECASE)) else _tempo_flex(fim_txt)
            except (YoutubeClipperError, ValueError):
                avisos.append(f"Linha {n}: tempo inválido ({ini_txt} → {fim_txt or 'fim'}) — ignorado.")
                continue
            if fim is not None and fim <= ini:
                avisos.append(f"Linha {n}: o fim ({fim_txt}) vem antes do início ({ini_txt}) — ignorado.")
                continue
            atual["trechos"].append({"inicio": formatar_tempo(ini) if ini % 1 == 0 else f"{ini:.2f}",
                                     "fim": "" if fim is None else (formatar_tempo(fim) if fim % 1 == 0 else f"{fim:.2f}"),
                                     "descricao": desc + (f" ({k + 1})" if len(pares) > 1 and desc else "")})
    if desc_pendente and atual is not None and not atual["trechos"] and not atual["_capitulos"]:
        atual["_desc_video"] = desc_pendente
    for item in itens:
        caps = sorted(item.pop("_capitulos", []), key=lambda c: c[0])
        for k, (ini, desc) in enumerate(caps):
            fim = caps[k + 1][0] if k + 1 < len(caps) else None
            if fim is not None and fim <= ini:
                continue
            item["trechos"].append({"inicio": formatar_tempo(ini) if ini % 1 == 0 else f"{ini:.2f}",
                                    "fim": "" if fim is None else (formatar_tempo(fim) if fim % 1 == 0 else f"{fim:.2f}"),
                                    "descricao": desc})
        for t in item["trechos"]:  # trecho sem descrição usa o título do vídeo
            if not t["descricao"] and item["_desc_video"]:
                t["descricao"] = item["_desc_video"]
        if not item["trechos"]:
            item["trechos"].append({"inicio": "", "fim": "", "descricao": item["_desc_video"] or "vídeo inteiro"})
            avisos.append(f"{item['url']}: sem tempo — vai o vídeo inteiro.")
        item.pop("_desc_video", None)
    if not itens:
        avisos.append("Não achei nenhum link no texto.")
    return {"itens": itens, "avisos": avisos,
            "resumo": {"videos": len(itens), "trechos": sum(len(i["trechos"]) for i in itens)}}


def formatar_tempo(segundos: float) -> str:
    """O inverso de `parse_tempo` — usado nos nomes de arquivo e no
    `info.json`, pra ficar legível (ex: 105.0 -> "00:01:45")."""
    segundos = max(0, int(round(segundos)))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _duracao_arquivo_segundos(caminho: str) -> Optional[float]:
    """Duração real de um arquivo já baixado, via ffprobe — mais
    confiável que a duração reportada pelos metadados do yt-dlp (que
    às vezes vem errada, arredondada ou simplesmente ausente)."""
    try:
        resultado = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", caminho],
            capture_output=True, text=True, timeout=15,
        )
        return float(resultado.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def _resolver_inicio_fim(trecho: Dict[str, Any], duracao_video: Optional[float]) -> tuple:
    """Resolve o início/fim de UM trecho a partir do dict pedido —
    `inicio`/`fim` vazios, ausentes ou `None` são tratados como "o
    vídeo inteiro" (início = 0, fim = duração real do vídeo) em vez de
    dar erro, pra não obrigar a pessoa a digitar o tempo de fim exato
    quando ela só quer o vídeo do jeito que ele é.

    `duracao_video`: duração real do vídeo já baixado (via
    `_duracao_arquivo_segundos`) — usada como valor de `fim` quando
    ele não foi informado. Se vier `None` (não deu pra medir) e `fim`
    também não foi informado, levanta erro pedindo pra informar um fim
    manualmente.
    """
    inicio_bruto = trecho.get("inicio")
    fim_bruto = trecho.get("fim")

    if inicio_bruto is None or (isinstance(inicio_bruto, str) and not inicio_bruto.strip()):
        inicio = 0.0
    else:
        inicio = inicio_bruto if isinstance(inicio_bruto, (int, float)) else parse_tempo(str(inicio_bruto))

    if fim_bruto is None or (isinstance(fim_bruto, str) and not fim_bruto.strip()):
        if duracao_video is None:
            raise YoutubeClipperError(
                "Não consegui medir a duração do vídeo pra usar como fim do trecho (deixado em "
                "branco) — informe um tempo de fim manualmente."
            )
        fim = duracao_video
    else:
        fim = fim_bruto if isinstance(fim_bruto, (int, float)) else parse_tempo(str(fim_bruto))

    return inicio, fim


def _slug(texto: str, tamanho_max: int = 60) -> str:
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", texto).strip("_")
    return (texto or "video")[:tamanho_max]


def buscar_videos_youtube(termo: str, quantidade: int = 12, ytdlp_module: Any = None, pular: int = 0) -> List[Dict[str, Any]]:
    """Busca vídeos no YouTube por um termo de texto (igual digitar na
    busca do próprio site) e devolve os resultados — sem precisar de
    chave de API nenhuma: usa o pseudo-URL `ytsearchN:termo` do yt-dlp,
    que faz o yt-dlp buscar e devolver os metadados direto.

    Cada resultado: `{"id", "titulo", "url", "duracao_segundos",
    "miniatura_url", "descricao", "canal"}`. `duracao_segundos` pode vir
    `None` pra transmissões ao vivo; `descricao` pode vir vazia (a
    busca traz os metadados "resumidos" de cada vídeo, não a página
    inteira — pedir a descrição completa de cada um deixaria a busca
    bem mais lenta, com uma requisição extra por vídeo).

    `pular` (➕ "Buscar outros vídeos"): pula os N primeiros da busca e devolve os `quantidade` seguintes.
    """
    termo = (termo or "").strip()
    if not termo:
        raise YoutubeClipperError("Termo de busca vazio.")
    quantidade = max(1, min(int(quantidade or 12), 50))
    pular = max(0, min(int(pular or 0), 150))

    if ytdlp_module is not None:
        yt_dlp = ytdlp_module
    else:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise YoutubeClipperError(
                "yt-dlp não está instalado. Rode: pip install yt-dlp"
            ) from exc

    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "skip_download": True, **__import__("yt_cookies").opcoes()}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{quantidade + pular}:{termo}", download=False)
    except Exception as exc:  # noqa: BLE001
        raise YoutubeClipperError(f"Não consegui buscar por {termo!r}: {exc}") from exc

    resultados = []
    for entrada in list((info or {}).get("entries") or [])[pular:pular + quantidade]:
        if not entrada:
            continue
        video_id = entrada.get("id")
        miniaturas = entrada.get("thumbnails") or []
        miniatura_url = miniaturas[-1]["url"] if miniaturas else (entrada.get("thumbnail") or "")
        resultados.append({
            "id": video_id,
            "titulo": entrada.get("title") or "(sem título)",
            "url": entrada.get("webpage_url") or entrada.get("url") or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""),
            "duracao_segundos": entrada.get("duration"),
            "duracao_formatada": formatar_tempo(entrada["duration"]) if entrada.get("duration") else None,
            "miniatura_url": miniatura_url,
            "descricao": (entrada.get("description") or "").strip(),
            "canal": entrada.get("channel") or entrada.get("uploader") or "",
        })
    return resultados


def _normalizar_url_canal_youtube(url: str, tipo: str) -> str:
    """Converte um link de canal/base do YouTube (`@fulano`, `/channel/...`,
    ou já apontando pra alguma aba) na URL da aba "/shorts" ou "/videos"."""
    url = (url or "").strip()
    if not url:
        raise YoutubeClipperError("Informe o link do canal do YouTube.")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    url = url.split("?", 1)[0].rstrip("/")
    if tipo == "shorts":
        if url.endswith("/shorts"):
            return url
        url = re.sub(r"/(?:videos|featured|live|streams|playlists)$", "", url, flags=re.I)
        return url + "/shorts"
    if url.endswith("/videos"):
        return url
    url = re.sub(r"/(?:shorts|featured|live|streams|playlists)$", "", url, flags=re.I)
    return url + "/videos"


def extrair_links_canal(
    url: str, tipo: str = "shorts", ordem: str = "mais_novos", ytdlp_module: Any = None,
) -> Dict[str, Any]:
    """Lista título + link de todo Short (ou vídeo normal) de um canal do
    YouTube, SEM baixar nada — útil pra montar rapidamente uma lista
    grande de URLs pra colar em "Cortar do YouTube" ou "Transcrever".

    `url`: link do canal (com ou sem `/videos`/`/shorts` no final — ex:
        "youtube.com/@canal", "youtube.com/@canal/shorts").
    `tipo`: "shorts" (padrão) ou "videos".
    `ordem`: "mais_novos" (padrão) ou "mais_antigos" — só é confiável
        quando o yt-dlp devolve a data de publicação de cada vídeo (o
        normal); sem isso, apenas inverte a ordem que a página trouxe.

    Devolve `{"canal", "tipo", "ordem", "total", "itens": [{"indice",
    "titulo", "link", "id", "upload_date"}, ...]}`.
    """
    if tipo not in ("shorts", "videos"):
        raise YoutubeClipperError("Tipo inválido — use 'shorts' ou 'videos'.")
    canal_url = _normalizar_url_canal_youtube(url, tipo)

    if ytdlp_module is not None:
        yt_dlp = ytdlp_module
    else:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise YoutubeClipperError(
                "yt-dlp não está instalado. Rode: pip install yt-dlp"
            ) from exc

    ydl_opts = {
        "extract_flat": True, "skip_download": True, "ignoreerrors": True,
        "quiet": True, "no_warnings": True, "playlistend": None, **__import__("yt_cookies").opcoes(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            resultado = ydl.extract_info(canal_url, download=False)
    except Exception as exc:  # noqa: BLE001
        raise YoutubeClipperError(f"Não consegui extrair o canal: {type(exc).__name__}: {exc}") from exc

    if not resultado or "entries" not in resultado:
        raise YoutubeClipperError("Nenhum vídeo foi encontrado nesse canal.")

    itens = []
    for entrada in resultado.get("entries") or []:
        if not entrada:
            continue
        video_id = entrada.get("id")
        if not video_id:
            continue
        titulo = (entrada.get("title") or "Sem título").strip()
        upload_date = entrada.get("upload_date") or ""
        link = f"https://www.youtube.com/shorts/{video_id}" if tipo == "shorts" else f"https://www.youtube.com/watch?v={video_id}"
        itens.append({"indice": len(itens) + 1, "titulo": titulo, "link": link, "id": video_id, "upload_date": upload_date})

    # Normalmente o yt-dlp já devolve a ordem da própria página. Quando dá
    # pra confiar na data de publicação (pelo menos 2 itens com ela), essa
    # ordenação garante que "mais antigos"/"mais novos" sejam confiáveis
    # de verdade em vez de só espelhar a ordem que a página trouxe.
    com_data = [x for x in itens if re.match(r"^\d{8}$", x.get("upload_date", ""))]
    if len(com_data) >= 2:
        itens.sort(key=lambda x: x.get("upload_date", ""), reverse=(ordem != "mais_antigos"))
    elif ordem == "mais_antigos":
        itens.reverse()
    for i, item in enumerate(itens, start=1):
        item["indice"] = i

    return {"canal": canal_url, "tipo": tipo, "ordem": ordem, "total": len(itens), "itens": itens}


def altura_do_video(caminho: str) -> Optional[int]:
    """Altura real (em pixels) do vídeo baixado, via ffprobe. None se não der pra medir."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
                            "-of", "csv=p=0", caminho], capture_output=True, text=True, timeout=20)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def _nome_cliente(cliente: Optional[List[str]]) -> str:
    return "padrão" if not cliente else "+".join(cliente)


def baixar_video(url: str, output_dir: str, qualidade: str = QUALIDADE_PADRAO, ytdlp_module: Any = None,
                 on_log: Optional[Any] = None) -> Dict[str, Any]:
    """Baixa `url` (precisa ser um vídeo, não uma playlist/canal) pra
    dentro de `output_dir`, na `qualidade` pedida (ver `QUALIDADES`).
    Devolve `{"caminho", "titulo", "duracao_segundos", "url", "id", "altura", "cliente"}`.

    Tenta os clientes do YouTube de `CLIENTES_YOUTUBE` em ordem. Uma
    tentativa que falha (ex: "HTTP Error 403: Forbidden" — o YouTube muda a
    autenticação do cliente "web" com frequência) passa pra próxima. Uma
    tentativa que funciona mas vem ABAIXO da qualidade pedida (o cliente
    "android", por exemplo, hoje costuma entregar só 360p) também passa pra
    próxima — no fim fica com o arquivo de maior resolução.

    `ytdlp_module`: injeta um módulo yt-dlp alternativo (só pra teste —
    em uso normal, não passe nada, usa o `yt_dlp` de verdade).
    """
    if qualidade not in QUALIDADES:
        raise YoutubeClipperError(f"Qualidade {qualidade!r} inválida — use uma de {sorted(QUALIDADES)}.")
    log = on_log or (lambda _m: None)

    if ytdlp_module is not None:
        yt_dlp = ytdlp_module
    else:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise YoutubeClipperError(
                "yt-dlp não está instalado. Rode: pip install yt-dlp"
            ) from exc

    os.makedirs(output_dir, exist_ok=True)
    alvo = ALTURA_ALVO.get(qualidade)
    ffmpeg = shutil.which("ffmpeg")

    def _opcoes(pasta: str, cliente: Optional[List[str]], ck: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        opcoes: Dict[str, Any] = {
            **(ck or {}),
            "format": QUALIDADES[qualidade],
            # entre os formatos permitidos: maior resolução (até o alvo), depois fps, depois H.264 (abre em qualquer editor)
            "format_sort": ([f"res:{alvo}"] if alvo else ["res"]) + ["fps", "vcodec:avc", "acodec:m4a"],
            "outtmpl": os.path.join(pasta, "%(id)s.%(ext)s"),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        if ffmpeg:  # sem achar o ffmpeg o yt-dlp não junta vídeo+áudio e cai num formato único de baixa qualidade
            opcoes["ffmpeg_location"] = os.path.dirname(ffmpeg)
        if cliente:
            opcoes["extractor_args"] = {"youtube": {"player_client": list(cliente)}}
        return opcoes

    erros: List[str] = []

    def _rodada(ck: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Tenta os clientes do YouTube com esses cookies; erro de login sobe pro yt_cookies tentar outro navegador."""
        melhor: Optional[Dict[str, Any]] = None
        for k, cliente in enumerate(CLIENTES_YOUTUBE):
            pasta = os.path.join(output_dir, f"_tentativa_{k}")
            os.makedirs(pasta, exist_ok=True)
            try:
                with yt_dlp.YoutubeDL(_opcoes(pasta, cliente, ck)) as ydl:
                    info = ydl.extract_info(url, download=True)
                    caminho = ydl.prepare_filename(info)
            except Exception as exc:  # noqa: BLE001
                erros.append(f"cliente {_nome_cliente(cliente)}: {exc}")
                shutil.rmtree(pasta, ignore_errors=True)
                continue
            # merge_output_format="mp4" pode ter trocado a extensão (ex: .webm -> .mp4 depois do merge)
            base, _ext = os.path.splitext(caminho)
            if os.path.exists(base + ".mp4"):
                caminho = base + ".mp4"
            if not os.path.exists(caminho):
                erros.append(f"cliente {_nome_cliente(cliente)}: o download terminou, mas o arquivo não apareceu")
                shutil.rmtree(pasta, ignore_errors=True)
                continue
            altura = altura_do_video(caminho)
            atual = {"caminho": caminho, "pasta": pasta, "info": info, "altura": altura, "cliente": _nome_cliente(cliente)}
            if melhor is None or (altura or 0) > (melhor["altura"] or 0):
                if melhor is not None:
                    shutil.rmtree(melhor["pasta"], ignore_errors=True)
                melhor = atual
            else:
                shutil.rmtree(pasta, ignore_errors=True)
            suficiente = altura is None or (alvo is not None and altura >= alvo * 0.95) or (alvo is None and altura >= 1080)
            if suficiente:
                break
            log(f"  ⚠ veio em {altura}p (cliente {_nome_cliente(cliente)}), abaixo de {qualidade} — tentando outro cliente do YouTube...")
        if melhor is None:  # sobe o erro: se for "confirme que não é um robô", o yt_cookies tenta outro navegador
            bloq = [e for e in erros[-len(CLIENTES_YOUTUBE):] if yt_cookies.eh_bloqueio(e)]
            raise YoutubeClipperError(bloq[-1] if bloq else (erros[-1] if erros else "nenhum cliente baixou"))
        return melhor

    import yt_cookies
    try:  # "Sign in to confirm you're not a bot": cookies do navegador (yt_cookies)
        melhor = yt_cookies.tentar(_rodada, log)
    except yt_cookies.YoutubeBloqueado as exc:
        # outro jeito de baixar: pytubefix (outra biblioteca, outros clientes do YouTube)
        if ytdlp_module is not None and not getattr(ytdlp_module, "usar_pytubefix", False):
            raise YoutubeClipperError(str(exc)) from exc
        log("  🔁 o YouTube bloqueou o yt-dlp — tentando baixar com o pytubefix…")
        try:
            import yt_alternativas
            r = yt_alternativas.video_pytubefix(url, output_dir, alvo, log)
        except Exception as exc2:  # noqa: BLE001
            raise YoutubeClipperError(f"{exc} | pytubefix: {yt_cookies.limpar(exc2)[:300]}") from exc2
        log(f"  ✔ baixado com o pytubefix em {r.get('altura')}p")
        return dict(r, url=url, cliente="pytubefix")
    except YoutubeClipperError:
        melhor = None

    if melhor is None:
        raise YoutubeClipperError(
            f"Não consegui baixar {url!r} com nenhum cliente do YouTube (cliente padrão, tv/web_safari, mweb e "
            f"\"android\" — esse último é o jeito mais comum de contornar um \"HTTP Error 403: Forbidden\", mas às "
            f"vezes nem ele resolve). Causas mais prováveis: o yt-dlp está desatualizado (o YouTube muda com "
            f"frequência — rode `pip install -U \"yt-dlp[default]\"`), o vídeo é privado/restrito por idade/"
            f"bloqueado na sua região, ou falta o Deno instalado (runtime de JavaScript que o yt-dlp usa pra resolver "
            f"alguns desafios do YouTube — https://deno.com). Erros: " + " | ".join(erros)
        )
    # move o escolhido pra pasta de downloads
    destino = os.path.join(output_dir, os.path.basename(melhor["caminho"]))
    shutil.move(melhor["caminho"], destino)
    shutil.rmtree(melhor["pasta"], ignore_errors=True)
    info = melhor["info"]
    altura = melhor["altura"]
    if altura:
        log(f"  ✔ baixado em {altura}p (cliente {melhor['cliente']})"
            + (f" — o YouTube não entregou {qualidade} pra este vídeo com nenhum cliente. Atualizar o yt-dlp "
               f"(pip install -U \"yt-dlp[default]\") e instalar o Deno (https://deno.com) costuma resolver."
               if alvo and altura < alvo * 0.95 else ""))
    return {
        "caminho": destino,
        "titulo": info.get("title") or url,
        "duracao_segundos": info.get("duration"),
        "url": url,
        "id": info.get("id") or uuid.uuid4().hex[:11],
        "altura": altura,
        "cliente": melhor["cliente"],
    }


def cortar_trecho(video_path: str, inicio_segundos: float, fim_segundos: float, output_path: str) -> str:
    """Corta [`inicio_segundos`, `fim_segundos`] de `video_path` (re-
    codifica, pra garantir um corte EXATO no ponto certo — um corte só
    por `-c copy` só consegue parar em keyframes, o que quase nunca
    bate certinho com o segundo pedido pelo usuário)."""
    if fim_segundos <= inicio_segundos:
        raise YoutubeClipperError(
            f"Fim ({formatar_tempo(fim_segundos)}) precisa vir depois do início ({formatar_tempo(inicio_segundos)})."
        )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    resultado = subprocess.run(
        # CRF 17 = praticamente sem perda visível (o padrão do x264, 23, deixava o clipe borrado)
        ["ffmpeg", "-y", "-i", video_path, "-ss", f"{inicio_segundos:.3f}", "-to", f"{fim_segundos:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", output_path],
        capture_output=True, timeout=600,
    )
    if resultado.returncode != 0 or not os.path.exists(output_path):
        raise YoutubeClipperError(
            f"ffmpeg não conseguiu cortar o trecho: {resultado.stderr.decode(errors='replace')[-400:]}"
        )
    return output_path


def processar_pedido(
    itens: List[Dict[str, Any]],
    output_dir: str,
    qualidade: str = QUALIDADE_PADRAO,
    on_log: Optional[Any] = None,
    ytdlp_module: Any = None,
) -> Dict[str, Any]:
    """Processa vários vídeos de uma vez — baixa cada um (uma vez só,
    mesmo com vários trechos pedidos dele) e corta todos os trechos
    pedidos. Monta um `info.json` com tudo, zipa os clipes + o json, e
    devolve o caminho do `.zip` final.

    `itens`: `[{"url": "...", "trechos": [{"inicio": "00:12", "fim":
        "01:45", "descricao": "gameplay"}, ...]}, ...]` — `inicio`/
        `fim` aceitam "MM:SS", "HH:MM:SS" ou um número de segundos.
        Vazios/ausentes viram o VÍDEO INTEIRO (início = 0, fim =
        duração real dele) — não precisa marcar os dois se quiser o
        vídeo do jeito que ele é. `descricao` é opcional.

    Levanta `YoutubeClipperError` na primeira falha (download ou
    corte) — nada de zip parcial: ou processa tudo, ou nada é gerado.
    """
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not itens:
        raise YoutubeClipperError("Nenhum vídeo informado.")
    for item in itens:
        if not (item.get("url") or "").strip():
            raise YoutubeClipperError("Um dos itens está sem URL.")
        if not item.get("trechos"):
            raise YoutubeClipperError(f"O vídeo {item['url']!r} não tem nenhum trecho definido.")

    os.makedirs(output_dir, exist_ok=True)
    pasta_downloads = os.path.join(output_dir, "_downloads_originais")
    pasta_clipes = os.path.join(output_dir, "clipes")
    os.makedirs(pasta_clipes, exist_ok=True)

    info_videos = []
    for i, item in enumerate(itens, start=1):
        url = item["url"].strip()
        log(f"[{i}/{len(itens)}] Baixando: {url}")
        info_download = baixar_video(url, pasta_downloads, qualidade=qualidade, ytdlp_module=ytdlp_module, on_log=log)
        titulo_slug = _slug(info_download["titulo"])

        clipes_desse_video = []
        duracao_real = _duracao_arquivo_segundos(info_download["caminho"]) or info_download.get("duracao_segundos")
        for j, trecho in enumerate(item["trechos"], start=1):
            inicio, fim = _resolver_inicio_fim(trecho, duracao_real)
            descricao = (trecho.get("descricao") or "").strip()

            if duracao_real and inicio >= duracao_real:
                raise YoutubeClipperError(
                    f"O trecho {formatar_tempo(inicio)}-{formatar_tempo(fim)} começa depois do fim do vídeo "
                    f"({formatar_tempo(duracao_real)})."
                )

            nome_arquivo = f"{titulo_slug}_{formatar_tempo(inicio).replace(':', '-')}_a_{formatar_tempo(fim).replace(':', '-')}.mp4"
            log(f"  Cortando trecho {j}: {formatar_tempo(inicio)} até {formatar_tempo(fim)}" + (f" ({descricao})" if descricao else ""))
            cortar_trecho(info_download["caminho"], inicio, fim, os.path.join(pasta_clipes, nome_arquivo))

            clipes_desse_video.append({
                "arquivo": nome_arquivo,
                "inicio": formatar_tempo(inicio),
                "fim": formatar_tempo(fim),
                "inicio_segundos": inicio,
                "fim_segundos": fim,
                "descricao": descricao or None,
            })

        info_videos.append({
            "titulo_original": info_download["titulo"],
            "url": info_download["url"],
            "duracao_segundos": info_download.get("duracao_segundos"),
            "resolucao": f"{info_download['altura']}p" if info_download.get("altura") else None,
            "clipes": clipes_desse_video,
        })

    log("Montando o info.json e o zip final...")
    info_json = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "qualidade": qualidade, "videos": info_videos}
    caminho_info = os.path.join(pasta_clipes, "info.json")
    with open(caminho_info, "w", encoding="utf-8") as f:
        json.dump(info_json, f, ensure_ascii=False, indent=2)

    caminho_zip = os.path.join(output_dir, "clipes_cortados.zip")
    with zipfile.ZipFile(caminho_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome in os.listdir(pasta_clipes):
            zf.write(os.path.join(pasta_clipes, nome), arcname=nome)

    if os.path.isdir(pasta_downloads):
        shutil.rmtree(pasta_downloads, ignore_errors=True)  # não precisa mais do vídeo original inteiro

    log("Pronto!")
    return {"zip_path": caminho_zip, "info": info_json}


def extrair_perfil_de_voz_do_youtube(
    itens: List[Dict[str, Any]],
    nome_perfil: str,
    qualidade: str = QUALIDADE_PADRAO,
    on_log: Optional[Any] = None,
    ytdlp_module: Any = None,
    adicionar: bool = False,
) -> List[str]:
    """(`adicionar=True`: junta os clipes num perfil que já existe, sem apagar os que ele tem — v84_174.)

    Baixa vídeo(s) do YouTube, corta os trechos pedidos, e salva
    tudo direto como um PERFIL DE VOZ reutilizável (ver
    `tts.voice_generator.salvar_perfil_de_voz`) — um jeito rápido de
    montar um perfil sem precisar baixar e editar o áudio manualmente
    antes.

    `itens`: MESMO formato do `processar_pedido()` —
    `[{"url": "...", "trechos": [{"inicio": "00:12", "fim": "01:45"}, ...]}, ...]`
    (`descricao` nos trechos é ignorada aqui, não faz diferença pro
    perfil). `inicio`/`fim` vazios ou ausentes viram o VÍDEO INTEIRO
    (início = 0, fim = duração real dele) — não precisa marcar os dois
    se quiser o vídeo do jeito que ele é.

    Cada trecho cortado vira um ou mais CLIPES DE REFERÊNCIA do
    perfil: se o trecho sair curto, vira um clipe só; se sair longo
    (ex: o vídeo inteiro, ou um trecho de vários minutos), é dividido
    automaticamente em vários clipes curtos e espalhados — o MESMO
    mecanismo já usado quando alguém sobe um único áudio longo direto
    pro perfil (`voice_generator.dividir_audio_em_clipes`). Não
    precisa se preocupar em marcar trechos curtos à mão só por causa
    disso.

    Levanta `YoutubeClipperError` (download/corte) ou
    `VoiceGeneratorError` (nome do perfil, limite de clipes etc) na
    primeira falha — nada de perfil parcial.
    """
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    if not itens:
        raise YoutubeClipperError("Nenhum vídeo informado.")
    for item in itens:
        if not (item.get("url") or "").strip():
            raise YoutubeClipperError("Um dos itens está sem URL.")
        if not item.get("trechos"):
            raise YoutubeClipperError(f"O vídeo {item['url']!r} não tem nenhum trecho definido.")

    # Import tardio (e sys.path defensivo) pro módulo de TTS — evita
    # criar uma dependência rígida em `youtube_clipper.py` pra quem só
    # usa as outras funções dele (ex: `test_youtube_clipper.py` roda
    # sozinho, sem o `toolkit/` no sys.path, que normalmente é o
    # `app.py` quem configura).
    import sys
    toolkit_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
    if toolkit_dir not in sys.path:
        sys.path.insert(0, toolkit_dir)
    from tts.voice_generator import salvar_perfil_de_voz, dividir_audio_em_clipes, adicionar_clipes_ao_perfil

    import tempfile
    pasta_tmp = tempfile.mkdtemp(prefix="perfil_youtube_")
    pasta_downloads = os.path.join(pasta_tmp, "_downloads")
    pasta_trechos = os.path.join(pasta_tmp, "trechos")
    os.makedirs(pasta_trechos, exist_ok=True)

    caminhos_trechos: List[str] = []
    pastas_extras_para_limpar: List[str] = []
    try:
        for i, item in enumerate(itens, start=1):
            url = item["url"].strip()
            log(f"[{i}/{len(itens)}] Baixando: {url}")
            info_download = baixar_video(url, pasta_downloads, qualidade=qualidade, ytdlp_module=ytdlp_module)
            titulo_slug = _slug(info_download["titulo"])
            duracao_real = _duracao_arquivo_segundos(info_download["caminho"]) or info_download.get("duracao_segundos")

            for j, trecho in enumerate(item["trechos"], start=1):
                inicio, fim = _resolver_inicio_fim(trecho, duracao_real)

                if duracao_real and inicio >= duracao_real:
                    raise YoutubeClipperError(
                        f"O trecho {formatar_tempo(inicio)}-{formatar_tempo(fim)} começa depois do fim do "
                        f"vídeo ({formatar_tempo(duracao_real)})."
                    )

                nome_arquivo = f"{titulo_slug}_{formatar_tempo(inicio).replace(':', '-')}_a_{formatar_tempo(fim).replace(':', '-')}.mp4"
                log(f"  Cortando trecho {j}: {formatar_tempo(inicio)} até {formatar_tempo(fim)}")
                caminho_trecho = os.path.join(pasta_trechos, nome_arquivo)
                cortar_trecho(info_download["caminho"], inicio, fim, caminho_trecho)

                # Se o trecho cortado ainda for longo (ex: marcou o
                # vídeo inteiro, ou um trecho de vários minutos), divide
                # ele em vários clipes curtos espalhados -- MESMO
                # mecanismo já usado quando alguém sobe um único áudio
                # longo direto pro perfil (`dividir_audio_em_clipes`).
                # Um trecho já curto passa direto, sem dividir nada
                # (a própria função decide isso sozinha).
                pedacos = dividir_audio_em_clipes(caminho_trecho)
                if len(pedacos) > 1:
                    log(f"    Trecho longo — dividido em {len(pedacos)} clipes menores")
                    pastas_extras_para_limpar.append(os.path.dirname(pedacos[0]))
                caminhos_trechos.extend(pedacos)

        log(f"Salvando o perfil de voz {nome_perfil!r} com {len(caminhos_trechos)} clipe(s)...")
        # já são os trechos exatos que a pessoa escolheu -- não deixa a
        # divisão automática de áudio longo mexer neles de novo.
        if adicionar:
            salvos = adicionar_clipes_ao_perfil(nome_perfil, caminhos_trechos, dividir_audio_longo=False)
        else:
            salvos = salvar_perfil_de_voz(nome_perfil, caminhos_trechos, dividir_audio_longo=False)
        log("Pronto!")
        return salvos
    finally:
        for pasta_extra in pastas_extras_para_limpar:
            shutil.rmtree(pasta_extra, ignore_errors=True)
        shutil.rmtree(pasta_tmp, ignore_errors=True)
