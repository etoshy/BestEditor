"""
📜 Roteiro do YouTube — pega a transcrição de um vídeo e trabalha o roteiro com a IA.

Fluxo (cada projeto fica em roteiros_yt/<id>/projeto.json):
  1. transcrição: link do YouTube → legenda do próprio vídeo (manual ou
     automática, via yt-dlp, sem baixar o vídeo); sem legenda → baixa só o
     áudio e transcreve com o Whisper. Ou cola o texto direto.
  2. prompt 1 (um MODELO escolhido — tem os de fábrica e os seus): a IA
     reescreve o roteiro trocando exemplos específicos demais por
     equivalentes, tira o que não faz sentido fora do vídeo original, e
     LISTA AS CENAS de filmes/séries/animes/jogos que aparecem (obra, tipo,
     momento, onde aparece no vídeo original) → JSON.
  3. prompt 2 (você marca o que quer): traduzir (ex.: inglês), pôr as tags
     de voz do Chatterbox Turbo, achar os melhores momentos pra anúncio,
     chamadas pra ação (like/inscrever/comentar), adaptar pra não precisar
     das cenas, marcar onde cada cena entra… → JSON.
  4. resultado: roteiro final (pro Gerador de voz), lista de cenas (buscar no
     YouTube / cortar do vídeo original → Cortar do YouTube), anúncios,
     chamadas, títulos.

Sem rede nos testes: `extrair_transcricao` aceita um módulo yt-dlp falso.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

PASTA = "roteiros_yt"

TAGS_SOM = ["laugh", "chuckle", "gasp", "cough", "sigh", "groan", "sniff", "shush", "clear throat"]
TAGS_ESTILO = ["angry", "crying", "dramatic", "fear", "happy", "narration", "sarcastic", "surprised", "whispering", "advertisement"]
TIPOS_OBRA = ("filme", "serie", "anime", "desenho", "jogo", "documentario", "novela", "outro")


class RoteiroError(Exception):
    pass


# ------------------------------------------------------------------ projetos
def _pasta(base: str, pid: str = "") -> str:
    return os.path.join(base, PASTA, pid) if pid else os.path.join(base, PASTA)


def _arquivo(base: str, pid: str) -> str:
    return os.path.join(_pasta(base, pid), "projeto.json")


def _valido(pid: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{10}", pid or ""))


def criar_projeto(base: str, url: str = "", texto: str = "", titulo: str = "") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    p = {"id": pid, "criado": time.time(), "atualizado": time.time(), "url": (url or "").strip(),
         "titulo": (titulo or "").strip()[:200], "transcricao": None,
         "modelo_id": (opcoes_usadas(base).get("passo1") or {}).get("modelo_id") or "reescrever_cenas",
         "analise": None, "acoes": None, "resultado": None}
    if texto and texto.strip():
        p["transcricao"] = transcricao_de_texto(texto)
    salvar_projeto(base, p)
    return p


def carregar_projeto(base: str, pid: str) -> Dict[str, Any]:
    if not _valido(pid) or not os.path.exists(_arquivo(base, pid)):
        raise RoteiroError("Projeto não encontrado.")
    with open(_arquivo(base, pid), encoding="utf-8") as f:
        return json.load(f)


def salvar_projeto(base: str, p: Dict[str, Any]) -> None:
    os.makedirs(_pasta(base, p["id"]), exist_ok=True)
    p["atualizado"] = time.time()
    tmp = _arquivo(base, p["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _arquivo(base, p["id"]))


def listar_projetos(base: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isdir(_pasta(base)):
        return out
    for pid in os.listdir(_pasta(base)):
        try:
            p = carregar_projeto(base, pid)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": pid, "titulo": p.get("titulo") or p.get("url") or "(sem título)", "url": p.get("url"),
                    "etapa": etapa(p), "atualizado": p.get("atualizado", 0)})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir_projeto(base: str, pid: str) -> None:
    import shutil
    if _valido(pid):
        shutil.rmtree(_pasta(base, pid), ignore_errors=True)


def etapa(p: Dict[str, Any]) -> str:
    if p.get("resultado"):
        return "pronto"
    if p.get("analise"):
        return "cenas listadas"
    if p.get("transcricao"):
        return "transcrito"
    return "novo"


# ------------------------------------------------------------------ transcrição
def _fmt(seg: float) -> str:
    seg = max(0, int(seg))
    h, m, s = seg // 3600, (seg % 3600) // 60, seg % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _juntar_linhas(linhas: List[Dict[str, Any]], alvo_s: float = 12.0) -> List[Dict[str, Any]]:
    """Legenda vem em pedacinhos de 2-3 s; junta em blocos de ~12 s (cortando
    em fim de frase quando dá) — o prompt fica menor e a IA ainda sabe ONDE
    cada coisa acontece no vídeo."""
    blocos: List[Dict[str, Any]] = []
    atual: Optional[Dict[str, Any]] = None
    for ln in linhas:
        txt = " ".join(str(ln.get("texto") or "").split())
        if not txt:
            continue
        if atual is None:
            atual = {"inicio": float(ln["inicio"]), "fim": float(ln.get("fim", ln["inicio"])), "texto": txt}
            if atual["fim"] - atual["inicio"] >= alvo_s:  # linha que já é um bloco grande fica sozinha
                blocos.append(atual)
                atual = None
            continue
        atual["texto"] += " " + txt
        atual["fim"] = float(ln.get("fim", ln["inicio"]))
        dur = atual["fim"] - atual["inicio"]
        if dur >= alvo_s * 2 or (dur >= alvo_s and re.search(r"[.!?…]\s*$", atual["texto"])):
            blocos.append(atual)
            atual = None
    if atual:
        blocos.append(atual)
    return blocos


def _de_json3(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    linhas = []
    for ev in dados.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        txt = "".join(str(s.get("utf8") or "") for s in segs).replace("\n", " ").strip()
        if not txt:
            continue
        ini = float(ev.get("tStartMs") or 0) / 1000.0
        linhas.append({"inicio": ini, "fim": ini + float(ev.get("dDurationMs") or 0) / 1000.0, "texto": txt})
    return linhas


def _tempo_vtt(t: str) -> float:
    partes = t.replace(",", ".").split(":")
    try:
        partes_f = [float(x) for x in partes]
    except ValueError:
        return 0.0
    while len(partes_f) < 3:
        partes_f.insert(0, 0.0)
    return partes_f[0] * 3600 + partes_f[1] * 60 + partes_f[2]


def _de_vtt(texto: str) -> List[Dict[str, Any]]:
    """VTT/SRT → linhas. Legenda automática do YouTube em VTT repete cada
    linha na seguinte ("rolando"): tira a repetição e as tags <00:00:01.000><c>."""
    linhas: List[Dict[str, Any]] = []
    ultimo = ""
    for bloco in re.split(r"\n\s*\n", texto.replace("\r", "")):
        m = re.search(r"(\d[\d:.,]*)\s*-->\s*(\d[\d:.,]*)", bloco)
        if not m:
            continue
        corpo = bloco[m.end():].split("\n", 1)[1] if "\n" in bloco[m.end():] else ""
        corpo = re.sub(r"<[^>]+>", "", corpo)
        partes = [p.strip() for p in corpo.split("\n") if p.strip()]
        novas = [p for p in partes if p != ultimo and not ultimo.endswith(p)]
        if partes:
            ultimo = partes[-1]
        txt = " ".join(novas).strip()
        if txt:
            linhas.append({"inicio": _tempo_vtt(m.group(1)), "fim": _tempo_vtt(m.group(2)), "texto": txt})
    return linhas


def transcricao_de_texto(texto: str) -> Dict[str, Any]:
    """Transcrição colada à mão. Aceita linhas com tempo ("0:12 texto",
    "[01:02] texto", "00:01:02.000 --> ...") ou texto corrido."""
    texto = str(texto or "").strip()
    if "-->" in texto:
        linhas = _de_vtt(texto)
    else:
        linhas = []
        for ln in texto.splitlines():
            m = re.match(r"\s*\[?((?:\d{1,2}:)?\d{1,2}:\d{2})\]?\s*[-–—]?\s*(.+)", ln)
            if m:
                linhas.append({"inicio": _tempo_vtt(m.group(1)), "texto": m.group(2)})
            elif linhas and ln.strip():
                linhas[-1]["texto"] += " " + ln.strip()
        for a, b in zip(linhas, linhas[1:] + [None]):
            a["fim"] = b["inicio"] if b else a["inicio"] + 5
    if linhas:
        return {"fonte": "colada", "idioma": None, "blocos": _juntar_linhas(linhas), "com_tempo": True}
    return {"fonte": "colada", "idioma": None, "com_tempo": False,
            "blocos": [{"inicio": 0.0, "fim": 0.0, "texto": p.strip()} for p in re.split(r"\n\s*\n", texto) if p.strip()]}


def _escolher_legenda(info: Dict[str, Any], preferidos: List[str]) -> Optional[Dict[str, Any]]:
    """Melhor faixa de legenda: manual > automática no idioma ORIGINAL do vídeo
    (a "-orig") > idiomas preferidos. Devolve {"lang", "auto", "formatos"}."""
    manuais = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    lingua = (info.get("language") or "").split("-")[0].lower()
    ordem = [lingua] + [p.lower() for p in preferidos] if lingua else [p.lower() for p in preferidos]

    def _achar(d: Dict[str, Any], chaves: List[str]) -> Optional[str]:
        for c in chaves:
            for k in d:
                if k.lower() == c or k.lower().startswith(c + "-"):
                    return k
        return None

    k = _achar({k: v for k, v in manuais.items() if k != "live_chat"}, [c for c in ordem if c])
    if k:
        return {"lang": k, "auto": False, "formatos": manuais[k]}
    orig = next((k for k in autos if k.endswith("-orig")), None)
    if orig:
        return {"lang": orig, "auto": True, "formatos": autos[orig]}
    k = _achar(autos, [c for c in ordem if c])
    if k:
        return {"lang": k, "auto": True, "formatos": autos[k]}
    if manuais:
        k = next(iter(k for k in manuais if k != "live_chat"), None)
        if k:
            return {"lang": k, "auto": False, "formatos": manuais[k]}
    return None


def extrair_transcricao(url: str, pasta: str, preferidos: Optional[List[str]] = None, ytdlp_module: Any = None,
                        on_log: Callable[[str], None] = lambda _m: None, whisper_fn: Optional[Callable] = None,
                        usar_whisper: bool = True, alternativas: Optional[Any] = None) -> Dict[str, Any]:
    """Transcrição de um vídeo do YouTube. 1º a legenda do próprio vídeo (não
    baixa o vídeo, é rápido); sem legenda, baixa só o áudio e usa o Whisper.

    Se o YouTube bloquear o yt-dlp ("Sign in to confirm you're not a bot"):
    outros clientes do YouTube → cookies dos navegadores → youtube-transcript-api →
    um navegador de verdade lendo a legenda do player → pytubefix pro áudio (ver
    yt_alternativas.py). `alternativas` = módulo (pra teste)."""
    if ytdlp_module is None:
        try:
            import yt_dlp as ytdlp_module  # type: ignore
        except ImportError as exc:
            raise RoteiroError("yt-dlp não está instalado (pip install -U \"yt-dlp[default]\").") from exc
    import yt_cookies
    alt = alternativas
    if alt is None:
        import yt_alternativas as alt
    preferidos = preferidos or ["pt", "en", "es"]
    os.makedirs(pasta, exist_ok=True)
    on_log("Lendo as informações do vídeo…")

    def _abrir(ck):
        # sem cookies: tenta também os outros clientes do YouTube (o bloqueio às vezes é só no padrão)
        clientes = [None] + (list(alt.CLIENTES) if not ck else [])
        ultimo = None
        for cli in clientes:
            opts = {"quiet": True, "no_warnings": True, "skip_download": True, **ck}
            if cli:
                opts["extractor_args"] = {"youtube": {"player_client": list(cli)}}
            y = ytdlp_module.YoutubeDL(opts)
            try:
                return y, y.extract_info(url, download=False), dict(ck, **({"extractor_args": opts["extractor_args"]} if cli else {}))
            except Exception as exc:  # noqa: BLE001
                try:
                    y.close()
                except Exception:  # noqa: BLE001
                    pass
                if cli is None and not yt_cookies.eh_bloqueio(exc):
                    raise
                if cli is None:  # erro de um cliente alternativo ("page needs to be reloaded"…) não para: tenta o próximo
                    ultimo = exc
                if cli is None and len(clientes) > 1:
                    on_log("  o YouTube bloqueou o yt-dlp — tentando outros clientes do YouTube…")
        raise ultimo

    bloqueio = None
    try:  # "Sign in to confirm you're not a bot": clientes + cookies dos navegadores (yt_cookies)
        ydl0, info, cookies = yt_cookies.tentar(_abrir, on_log)
    except yt_cookies.YoutubeBloqueado as exc:
        bloqueio = exc
    except Exception as exc:  # noqa: BLE001
        # qualquer falha do yt-dlp ("page needs to be reloaded", formato novo do YouTube…):
        # ainda dá pra pegar a legenda pelos outros caminhos
        on_log(f"  yt-dlp não leu o vídeo: {yt_cookies.limpar(exc)[:200]}")
        bloqueio = exc
    if bloqueio is not None:
        return _transcricao_sem_ytdlp(url, pasta, preferidos, on_log, whisper_fn, usar_whisper, alt, bloqueio)

    with ydl0 as ydl:
        base = {"titulo": info.get("title") or "", "canal": info.get("channel") or info.get("uploader") or "",
                "duracao": info.get("duration"), "url": info.get("webpage_url") or url}
        faixa = _escolher_legenda(info, preferidos)
        if faixa:
            fmts = {f.get("ext"): f.get("url") for f in faixa["formatos"] if f.get("url")}
            on_log(f"Legenda {'automática' if faixa['auto'] else 'do próprio vídeo'} em “{faixa['lang']}” — baixando…")
            for ext in ("json3", "vtt", "srv3", "srt"):
                if not fmts.get(ext):
                    continue
                try:
                    bruto = ydl.urlopen(fmts[ext]).read().decode("utf-8", "replace")
                    linhas = _de_json3(json.loads(bruto)) if ext == "json3" else _de_vtt(bruto)
                except Exception as exc:  # noqa: BLE001
                    on_log(f"  formato {ext} falhou ({exc}); tentando outro")
                    continue
                if linhas:
                    on_log(f"✔ {len(linhas)} linhas de legenda")
                    return dict(base, fonte="legenda automática" if faixa["auto"] else "legenda do vídeo",
                                idioma=faixa["lang"].replace("-orig", ""), blocos=_juntar_linhas(linhas), com_tempo=True)
    if not usar_whisper:
        raise RoteiroError("O vídeo não tem legenda. Cole a transcrição à mão, ou deixe marcado \"transcrever o áudio com Whisper\".")
    on_log("Sem legenda — baixando só o áudio pra transcrever com o Whisper (demora alguns minutos)…")
    opts = {"quiet": True, "no_warnings": True, "format": "bestaudio/best",
            "outtmpl": os.path.join(pasta, "audio.%(ext)s"), "noplaylist": True, **cookies}
    try:
        with ytdlp_module.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            caminho = ydl.prepare_filename(info)
    except Exception as exc:  # noqa: BLE001
        if not yt_cookies.eh_bloqueio(exc):
            raise
        on_log("  o YouTube bloqueou o download do áudio — tentando com o pytubefix…")
        caminho, _inf = alt.audio_pytubefix(url, pasta, on_log)
    return dict(base, **_whisper(caminho, whisper_fn, on_log))


def _whisper(caminho: str, whisper_fn: Optional[Callable], on_log: Callable[[str], None]) -> Dict[str, Any]:
    if whisper_fn is None:
        try:
            from whisper_transcribe import transcribe_audio as whisper_fn  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RoteiroError(f"O vídeo não tem legenda e o Whisper não está disponível ({exc}). Cole a transcrição à mão.") from exc
    extra: Dict[str, Any] = {}
    segs = whisper_fn(caminho, info=extra)
    try:
        os.remove(caminho)
    except OSError:
        pass
    linhas = [{"inicio": float(s["start"]), "fim": float(s["end"]), "texto": s["text"]} for s in segs]
    on_log(f"✔ Whisper: {len(linhas)} trechos")
    return {"fonte": "whisper", "idioma": extra.get("language"), "blocos": _juntar_linhas(linhas), "com_tempo": True}


def _transcricao_sem_ytdlp(url: str, pasta: str, preferidos: List[str], on_log: Callable[[str], None],
                           whisper_fn: Optional[Callable], usar_whisper: bool, alt: Any, bloqueio: Exception) -> Dict[str, Any]:
    """O yt-dlp foi bloqueado: pega a legenda por outros caminhos (yt_alternativas)."""
    import yt_cookies
    erros = [f"yt-dlp: {__import__('yt_cookies').limpar(bloqueio)[:160]}"]
    base = {"titulo": "", "canal": "", "duracao": None, "url": url}
    if hasattr(alt, "titulo_oembed"):  # título e canal por um caminho que quase nunca é bloqueado
        base.update({k: v for k, v in (alt.titulo_oembed(url) or {}).items() if v})
    on_log("🔁 O yt-dlp não conseguiu — pegando a legenda por outro caminho (youtube-transcript-api)…")
    try:
        r = alt.legenda_transcript_api(url, preferidos)
        if r and r.get("linhas"):
            on_log(f"✔ {len(r['linhas'])} linhas de legenda (youtube-transcript-api)")
            return dict(base, fonte="legenda automática" if r["auto"] else "legenda do vídeo", idioma=(r["lang"] or "").replace("-orig", ""),
                        blocos=_juntar_linhas(r["linhas"]), com_tempo=True)
        erros.append("youtube-transcript-api: o vídeo não tem legenda")
    except Exception as exc:  # noqa: BLE001
        erros.append(f"youtube-transcript-api: {yt_cookies.limpar(exc)[:160]}")
        on_log(f"  youtube-transcript-api não deu: {yt_cookies.limpar(exc)[:160]}")
    sem_legenda = False
    try:
        import site_config
        oculto = not bool(site_config.load_site_config().get("browser_visible"))
    except Exception:  # noqa: BLE001
        oculto = True
    for headless in ([True, False] if oculto else [False]):
        on_log("🌐 Abrindo o vídeo num navegador (como uma pessoa) pra ler a legenda do player…" if headless else
               "🌐 Tentando de novo com a janela do navegador visível…")
        try:
            r = alt.legenda_navegador(url, preferidos, on_log, headless=headless)
        except Exception as exc:  # noqa: BLE001
            erros.append(f"navegador{'' if headless else ' visível'}: {yt_cookies.limpar(exc)[:160]}")
            on_log(f"  navegador não deu: {yt_cookies.limpar(exc)[:160]}")
            continue
        if r:
            base.update({k: r.get(k) for k in ("titulo", "canal", "duracao") if r.get(k)})
            if r.get("linhas"):
                on_log(f"✔ {len(r['linhas'])} linhas de legenda (navegador)")
                return dict(base, fonte="legenda automática" if r["auto"] else "legenda do vídeo", idioma=(r["lang"] or "").replace("-orig", ""),
                            blocos=_juntar_linhas(r["linhas"]), com_tempo=True)
            if r.get("lang") is None:
                sem_legenda = True
                erros.append("navegador: o vídeo não tem legenda")
                break
            erros.append("navegador: achou a legenda mas não conseguiu ler")
    if usar_whisper:
        on_log("🎧 Sem legenda por esses caminhos — baixando o áudio com o pytubefix pra transcrever com o Whisper…")
        try:
            caminho, inf = alt.audio_pytubefix(url, pasta, on_log)
            base.update({k: v for k, v in {"titulo": inf.get("titulo"), "canal": inf.get("canal"), "duracao": inf.get("duracao")}.items() if v})
            return dict(base, **_whisper(caminho, whisper_fn, on_log))
        except RoteiroError:
            raise
        except Exception as exc:  # noqa: BLE001
            erros.append(f"pytubefix (áudio): {yt_cookies.limpar(exc)[:160]}")
    raise RoteiroError(
        ("O vídeo não tem legenda e o YouTube bloqueou o download do áudio. " if sem_legenda else
         "O YouTube bloqueou todos os jeitos de pegar a transcrição. ")
        + "Saídas: cole a transcrição à mão (no YouTube: “…mais” → “Mostrar transcrição”, selecione e copie), "
        "ou envie um cookies.txt em Configurações → YouTube, ou entre na sua conta do YouTube no Firefox e tente de novo. "
        "Tentativas: " + " ; ".join(erros))


def texto_da_transcricao(tr: Dict[str, Any], com_tempo: bool = True) -> str:
    if not tr:
        return ""
    if com_tempo and tr.get("com_tempo"):
        return "\n".join(f"[{_fmt(b['inicio'])}] {b['texto']}" for b in tr.get("blocos") or [])
    return "\n\n".join(b["texto"] for b in tr.get("blocos") or [])


# ------------------------------------------------------------------ modelos de prompt (passo 1)
_FORMATO_ANALISE = """## Formato de resposta — IMPORTANTE

Responda **apenas** com um JSON válido (sem texto antes ou depois), assim:

{
  "titulo": "título curto do assunto do vídeo",
  "idioma": "idioma do roteiro reescrito (ex.: pt-BR)",
  "roteiro": "o roteiro reescrito, completo, em parágrafos separados por \\n\\n",
  "cenas": [
    {
      "obra": "nome oficial da obra (ex.: Reservoir Dogs / Cães de Aluguel)",
      "tipo": "filme | serie | anime | desenho | jogo | documentario | novela | outro",
      "ano": "1992",
      "momento": "o que acontece na cena, do jeito que alguém procuraria (ex.: Mr. Blonde dançando 'Stuck in the Middle with You' com a navalha)",
      "episodio_ou_tempo": "temporada/episódio ou minuto aproximado na obra, se souber (senão vazio)",
      "no_video_original": {"inicio": "3:12", "fim": "3:25"},
      "trecho_do_roteiro": "a frase do roteiro reescrito em que essa cena entra",
      "busca_youtube": "o que digitar no YouTube pra achar essa cena (nome da obra + momento, no idioma em que ela é mais conhecida)",
      "certeza": "alta | media | baixa"
    }
  ],
  "removidos": ["o que você tirou ou trocou e por quê (curto)"],
  "plano": {"objetivo_comum": "...", "problema_superficie": "...", "problema_profundo": "...", "publico": "...", "comeco_e_fim": "...", "jornada": ["..."], "lacos_abertos": ["..."]},
  "observacoes": "algo importante pra quem vai editar (opcional)"
}

"no_video_original": entre que tempos a cena aparece (ou é comentada) no vídeo ORIGINAL, pelos [tempos] da transcrição — vazio se não der pra saber. Liste TODA cena de filme, série, anime, desenho, jogo etc. que o vídeo mostra ou descreve — inclusive as citadas só de passagem. Se não tiver certeza de qual obra/momento é, diga em "certeza" em vez de inventar."""

MODELOS_FABRICA: List[Dict[str, Any]] = [
    {
        "id": "reescrever_cenas",
        "nome": "Reescrever o roteiro + listar as cenas (padrão)",
        "texto": (
            "Você é roteirista de canal do YouTube. Abaixo está a transcrição de um vídeo{titulo_entre}.\n\n"
            "Faça três coisas:\n"
            "1. Veja se o vídeo usa CENAS de filmes, séries, animes, desenhos ou jogos — mostradas na tela ou descritas — e "
            "anote cada uma.\n"
            "2. Reescreva o roteiro inteiro com as suas palavras, mantendo o assunto, a ordem das ideias e o tom. Troque "
            "exemplos específicos demais (do canal original, do apresentador, de pessoas comuns, datas e números que só fazem "
            "sentido lá) por outros EQUIVALENTES que funcionem pra qualquer público; tire o que não faz sentido fora do vídeo "
            "original (\"como eu disse no vídeo passado\", patrocinador, recados do canal, \"deixa o like\", piadas internas, "
            "\"olha aqui na tela\"). O roteiro tem que fazer sentido sozinho, lido como narração.\n"
            "3. Liste as cenas no JSON, dizendo de que obra veio cada uma e qual é o momento.\n\n"
            "Escreva o roteiro em {idioma}.\n\n"
            "## Transcrição\n\n{transcricao}"
        ),
    },
    {
        "id": "so_cenas",
        "nome": "Só listar as cenas (sem reescrever)",
        "texto": (
            "Abaixo está a transcrição de um vídeo do YouTube{titulo_entre}. Liste TODAS as cenas de filmes, séries, animes, "
            "desenhos, jogos etc. que o vídeo mostra ou descreve: de que obra vem cada uma, o que acontece e onde aparece no "
            "vídeo. Em \"roteiro\", devolva a transcrição limpa (sem os tempos, sem repetições, pontuada), em {idioma}, sem "
            "reescrever.\n\n## Transcrição\n\n{transcricao}"
        ),
    },
    {
        "id": "reescrever_curto",
        "nome": "Reescrever mais curto (versão Short / 60 s) + cenas",
        "texto": (
            "Você é roteirista de Shorts. Abaixo está a transcrição de um vídeo{titulo_entre}. Escreva um roteiro NOVO e curto "
            "(até ~150 palavras, ~60 s de narração) com o melhor do vídeo: gancho forte na 1ª frase, sem enrolação, final que "
            "prende. Troque exemplos específicos demais por equivalentes e tire o que só faz sentido no vídeo original. Liste as "
            "cenas de filmes/séries/animes/jogos que aparecem no vídeo (mesmo as que ficaram de fora do roteiro curto — "
            "\"trecho_do_roteiro\" vazio nesse caso). Escreva em {idioma}.\n\n## Transcrição\n\n{transcricao}"
        ),
    },
]


def _arquivo_opcoes(base: str) -> str:
    return os.path.join(_pasta(base), "opcoes_usadas.json")


def opcoes_usadas(base: str) -> Dict[str, Any]:
    """Histórico das escolhas do 1º passo e do "O que fazer com o roteiro"
    (vale pra todos os projetos): {"passo1": {...}, "ultima": {...}, "historico": [..]}.
    Projeto novo já abre com a última combinação marcada."""
    try:
        with open(_arquivo_opcoes(base), encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("historico", [])
            return d
    except (OSError, ValueError):
        pass
    return {"historico": []}


def _salvar_opcoes(base: str, d: Dict[str, Any]) -> None:
    os.makedirs(_pasta(base), exist_ok=True)
    tmp = _arquivo_opcoes(base) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _arquivo_opcoes(base))


def lembrar_acoes(base: str, op: Dict[str, Any], limite: int = 12) -> None:
    validas = [k for k, _n, _d in ACOES]
    op = {"acoes": [k for k in validas if k in (op.get("acoes") or [])], "idioma": str(op.get("idioma") or "en")[:20],
          "extra": str(op.get("extra") or "")[:1500], "cta_no_texto": op.get("cta_no_texto", True) is not False}
    nomes = {k: n for k, n, _d in ACOES}
    if not op["acoes"] and not op["extra"].strip():
        return
    d = opcoes_usadas(base)
    chave = (tuple(op["acoes"]), op["idioma"] if "traduzir" in op["acoes"] else "", op["extra"].strip(), op["cta_no_texto"])
    hist = [h for h in d.get("historico") or []
            if (tuple(h.get("acoes") or []), h.get("idioma", "") if "traduzir" in (h.get("acoes") or []) else "",
                str(h.get("extra") or "").strip(), h.get("cta_no_texto", True) is not False) != chave]
    rotulo = " + ".join(nomes[k].split(" ", 1)[1] if " " in nomes[k] else nomes[k] for k in op["acoes"])
    if "traduzir" in op["acoes"]:
        rotulo += f" ({op['idioma']})"
    if op["extra"].strip():
        rotulo += " + pedido: " + op["extra"].strip()[:40]
    d["ultima"] = op
    d["historico"] = [dict(op, rotulo=rotulo[:160], usado_em=time.time())] + hist[:limite - 1]
    _salvar_opcoes(base, d)


def lembrar_passo1(base: str, op: Dict[str, Any]) -> None:
    d = opcoes_usadas(base)
    d["passo1"] = {"modelo_id": str(op.get("modelo_id") or "")[:60], "idioma": str(op.get("idioma") or "")[:20],
                   "marcar_chamadas": op.get("marcar_chamadas", True) is not False,
                   "sem_experiencias": op.get("sem_experiencias", True) is not False}
    _salvar_opcoes(base, d)


def esquecer_historico(base: str) -> None:
    d = opcoes_usadas(base)
    d["historico"] = []
    _salvar_opcoes(base, d)


def _arquivo_modelos(base: str) -> str:
    return os.path.join(_pasta(base), "modelos.json")


def modelos(base: str) -> List[Dict[str, Any]]:
    proprios: List[Dict[str, Any]] = []
    try:
        with open(_arquivo_modelos(base), encoding="utf-8") as f:
            proprios = [m for m in json.load(f) if isinstance(m, dict) and m.get("id") and m.get("texto")]
    except (OSError, ValueError):
        pass
    ids = {m["id"] for m in proprios}
    return [dict(m, fabrica=True) for m in MODELOS_FABRICA if m["id"] not in ids] + [dict(m, fabrica=False) for m in proprios]


def obter_modelo(base: str, mid: str) -> Dict[str, Any]:
    return next((m for m in modelos(base) if m["id"] == mid), dict(MODELOS_FABRICA[0], fabrica=True))


def salvar_modelo(base: str, nome: str, texto: str, mid: str = "") -> Dict[str, Any]:
    nome, texto = (nome or "").strip()[:80], (texto or "").strip()
    if not nome or not texto:
        raise RoteiroError("O modelo precisa de nome e texto.")
    if "{transcricao}" not in texto:
        texto += "\n\n## Transcrição\n\n{transcricao}"
    try:
        with open(_arquivo_modelos(base), encoding="utf-8") as f:
            proprios = json.load(f)
    except (OSError, ValueError):
        proprios = []
    # id existente (seu ou de fábrica) = editar (o de fábrica editado fica por
    # cima do original; excluir ele volta o de fábrica); sem id = modelo novo
    mid = re.sub(r"[^a-z0-9_]", "", (mid or "").lower())
    conhecidos = {m["id"] for m in MODELOS_FABRICA} | {m.get("id") for m in proprios}
    if mid not in conhecidos:
        mid = "meu_" + uuid.uuid4().hex[:6]
    novo = {"id": mid, "nome": nome, "texto": texto}
    proprios = [m for m in proprios if m.get("id") != mid] + [novo]
    os.makedirs(_pasta(base), exist_ok=True)
    with open(_arquivo_modelos(base), "w", encoding="utf-8") as f:
        json.dump(proprios, f, ensure_ascii=False, indent=2)
    return novo


def excluir_modelo(base: str, mid: str) -> None:
    try:
        with open(_arquivo_modelos(base), encoding="utf-8") as f:
            proprios = json.load(f)
    except (OSError, ValueError):
        return
    with open(_arquivo_modelos(base), "w", encoding="utf-8") as f:
        json.dump([m for m in proprios if m.get("id") != mid], f, ensure_ascii=False, indent=2)


REGRA_MARCAS = (
    "## Pausas pra vídeo de like/inscreva-se e de venda\n\n"
    "Coloque no roteiro, cada uma SOZINHA numa linha (com uma linha em branco antes e depois), estas duas marcas — "
    "escritas exatamente assim, colchete DUPLO e em maiúsculas, sem nenhuma frase dentro. Ali o editor pausa a narração "
    "e entra um vídeo pronto, então o texto antes e depois de cada marca tem que fazer sentido sem ela (não escreva "
    "\"deixa o like\", \"se inscreve\" nem fale de anúncio/patrocínio — o vídeo já faz isso):\n"
    "- [[INSCREVA]] = chamada pra ação (like/inscreva-se). 2 ou 3 no vídeo: uma logo depois do gancho/introdução "
    "(quando a pessoa já se interessou, nunca na 1ª frase), uma no meio num respiro natural, e uma perto do fim "
    "(antes da conclusão ou logo depois dela).\n"
    "- [[VENDA]] = momento de anúncio/venda. Logo depois de um gancho ou suspense (\"…e o que aconteceu depois mudou "
    "tudo.\") ou numa troca de assunto — nunca no meio de uma explicação, nem nos primeiros 15% do roteiro. Mais ou "
    "menos uma a cada 3-4 minutos de narração (~450-600 palavras); roteiro curto (menos de ~400 palavras) leva uma só.\n"
    "- Nunca duas marcas seguidas, nem uma colada na outra: deixe pelo menos alguns parágrafos entre elas."
)
REGRA_SEM_EXPERIENCIAS = (
    "## Sem experiências anteriores nem referências a outros vídeos\n\n"
    "REMOVA do roteiro tudo que depende do canal ou da vida de quem gravou o vídeo original: citações a outros vídeos "
    "(\"como eu falei no vídeo passado\", \"no meu vídeo sobre X\", \"link aqui em cima\", \"comenta no vídeo anterior\", "
    "\"essa série do canal\", \"parte 2\"), experiências e histórias pessoais do apresentador (\"quando eu era criança\", "
    "\"eu assisti isso no cinema com meu pai\", \"aconteceu comigo\", \"minha esposa\", \"no meu trabalho\"), menções à equipe, "
    "aos inscritos, a comentários, lives, patrocinadores ou ao próprio canal pelo nome. Se a ideia for importante pra "
    "história, reescreva de forma neutra e geral (\"muita gente lembra de ver isso no cinema\"); se não, apenas tire — e "
    "costure o texto em volta pra continuar fluindo. Liste o que tirou em \"removidos\"."
)
REGRA_MANTER_MARCAS = ("MANTENHA todas as marcas [[INSCREVA]] e [[VENDA]] que já estão no roteiro, cada uma sozinha numa "
                       "linha, exatamente no mesmo ponto da história — mesmo traduzindo, adaptando ou limpando o texto. "
                       "Não traduza, não reescreva e não apague essas marcas.")


def regra_tags_turbo() -> str:
    """Instrução das TAGS DE VOZ do Chatterbox Turbo (só funcionam com a voz em INGLÊS) — usada nos prompts
    do 🛒 Vídeo de venda e dos 🕵️ Modelos de vídeo quando o idioma de saída é inglês."""
    return ("TAGS DE VOZ (o roteiro vai ser narrado em inglês pelo Chatterbox Turbo): insira tags especiais DIRETO no texto do "
            "roteiro, entre colchetes, onde quiser que aconteçam. Exemplo: \"Hi there [chuckle], welcome back!\". "
            "Sons (no ponto exato do som): " + " ".join(f"[{t}]" for t in TAGS_SOM) + ". "
            "Estilo (funcionam melhor no INÍCIO da frase): " + " ".join(f"[{t}]" for t in TAGS_ESTILO) + ". "
            "Use com bom senso, onde um narrador de verdade faria aquilo ([whispering] num segredo, [dramatic] numa virada, "
            "[chuckle] depois de uma ironia, [sigh] num lamento) — em média uma tag a cada 2-4 frases. Escreva exatamente "
            "assim, em inglês, e nunca invente tags fora dessa lista. Não confunda com as marcas de mídia ([M2], [I4]).")


def marcas_no_texto(texto: str) -> Dict[str, int]:
    import chamadas as _ch
    out = {"inscreva": 0, "venda": 0}
    for p in _ch.dividir(texto or ""):
        if p["tipo"] in out:
            out[p["tipo"]] += 1
    return out


def prompt_analise(p: Dict[str, Any], modelo: Dict[str, Any], idioma: str = "o mesmo idioma da transcrição",
                   marcar_chamadas: bool = True, sem_experiencias: bool = True) -> str:
    tr = p.get("transcricao")
    if not tr or not tr.get("blocos"):
        raise RoteiroError("Primeiro pegue (ou cole) a transcrição.")
    titulo = p.get("titulo") or tr.get("titulo") or ""
    campos = {
        "transcricao": texto_da_transcricao(tr),
        "titulo": titulo, "titulo_entre": f" (\"{titulo}\")" if titulo else "",
        "idioma": idioma, "url": p.get("url") or "", "canal": tr.get("canal") or "",
    }
    texto = modelo["texto"]
    for k, v in campos.items():
        texto = texto.replace("{" + k + "}", str(v))
    import metodo_roteiro  # 🧭 método de roteiro em todo prompt que escreve roteiro
    if modelo.get("id") != "so_cenas":  # "só listar as cenas" não reescreve nada
        curto = modelo.get("id") == "reescrever_curto" or "short" in str(modelo.get("nome") or "").lower()
        texto = texto.strip() + "\n\n" + metodo_roteiro.bloco("curto" if curto else "reescrita")
    if sem_experiencias:
        texto = texto.strip() + "\n\n" + REGRA_SEM_EXPERIENCIAS
    if marcar_chamadas:
        texto = texto.strip() + "\n\n" + REGRA_MARCAS
    return texto.strip() + "\n\n" + _FORMATO_ANALISE


# ------------------------------------------------------------------ leitura da análise
def extrair_json(texto: str) -> Any:
    import modelados
    try:
        return modelados.extrair_json(texto)
    except Exception as exc:  # noqa: BLE001
        raise RoteiroError(str(exc)) from exc


def _tempo_txt(v: Any) -> str:
    v = str(v or "").strip()
    return v if re.fullmatch(r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?|\d+(?:\.\d+)?", v) else ""


def _cena(c: Dict[str, Any], k: int) -> Optional[Dict[str, Any]]:
    obra = str(c.get("obra") or c.get("titulo") or c.get("midia") or "").strip()
    momento = str(c.get("momento") or c.get("cena") or c.get("descricao") or "").strip()
    if not obra and not momento:
        return None
    tipo = str(c.get("tipo") or "outro").strip().lower().replace("série", "serie").replace("documentário", "documentario")
    nv = c.get("no_video_original") if isinstance(c.get("no_video_original"), dict) else {}
    return {
        "id": k, "obra": obra[:160], "tipo": tipo if tipo in TIPOS_OBRA else "outro", "ano": str(c.get("ano") or "")[:10],
        "momento": momento[:400], "episodio_ou_tempo": str(c.get("episodio_ou_tempo") or "")[:80],
        "inicio": _tempo_txt(nv.get("inicio") or c.get("inicio")), "fim": _tempo_txt(nv.get("fim") or c.get("fim")),
        "trecho_do_roteiro": str(c.get("trecho_do_roteiro") or "")[:400],
        "busca_youtube": str(c.get("busca_youtube") or f"{obra} {momento}")[:160].strip(),
        "certeza": str(c.get("certeza") or "").lower()[:10],
        "marcador": str(c.get("marcador") or "")[:20],
        "link": "", "link_inicio": "", "link_fim": "",
    }


def ler_analise(texto: str) -> Dict[str, Any]:
    d = extrair_json(texto)
    if not isinstance(d, dict):
        raise RoteiroError("Esperava um objeto JSON com \"roteiro\" e \"cenas\".")
    roteiro = str(d.get("roteiro") or d.get("roteiro_reescrito") or "").strip()
    cenas_raw = d.get("cenas") or []
    if not roteiro and not cenas_raw:
        raise RoteiroError("O JSON não tem \"roteiro\" nem \"cenas\".")
    cenas = [c for c in (_cena(x, k) for k, x in enumerate(cenas_raw if isinstance(cenas_raw, list) else []) if isinstance(x, dict)) if c]
    for k, c in enumerate(cenas, start=1):
        c["id"] = k
    return {"titulo": str(d.get("titulo") or "").strip()[:200], "idioma": str(d.get("idioma") or "").strip()[:20],
            "roteiro": roteiro, "cenas": cenas, "marcas": marcas_no_texto(roteiro),
            "removidos": [str(x)[:300] for x in (d.get("removidos") or []) if str(x).strip()][:60],
            "observacoes": str(d.get("observacoes") or "").strip()[:1500],
            "plano": __import__("metodo_roteiro").ler_plano(d.get("plano"))}


# ------------------------------------------------------------------ passo 2: o que fazer com o roteiro
ACOES = [
    ("traduzir", "🌐 Traduzir o roteiro", "Reescreve no idioma escolhido (natural, não tradução literal)."),
    ("tags", "🏷 Tags de voz (Chatterbox Turbo)", "Sons e estilos nos lugares certos — o Turbo só lê tags em inglês."),
    ("ads", "💰 Melhores momentos pra anúncio", "Pontos de virada/suspense onde um mid-roll não corta uma ideia."),
    ("cta", "👍 Chamadas pra ação (like, inscrever, comentar)", "Frases curtas e naturais nos melhores pontos."),
    ("sem_experiencias", "🙅 Tirar experiências pessoais e citações a outros vídeos", "Remove \"como falei no vídeo passado\", histórias do apresentador, menções ao canal."),
    ("sem_cenas", "🎬→📝 Adaptar pra não precisar das cenas", "Narra o que acontecia na cena em vez de mostrar."),
    ("marcar_cenas", "📍 Marcar onde cada cena entra", "Põe [CENA n] no roteiro, no ponto exato."),
    ("titulos", "🔥 Títulos e gancho", "Sugestões de título e uma 1ª frase mais forte."),
    ("descricao", "📝 Descrição com capítulos (timestamps) + títulos", "Descrição pro YouTube com capítulos 0:00…, título original (traduzido se traduzir) e títulos alternativos."),
    ("limpar_tts", "🧹 Limpar pro TTS (palavras erradas, símbolos)", "Corrige palavras escritas errado e escreve número, sigla e símbolo do jeito que se fala."),
]


def prompt_acoes(p: Dict[str, Any], acoes: List[str], idioma: str = "en", extra: str = "", cta_no_texto: bool = True) -> str:
    an = p.get("analise")
    if not an or not an.get("roteiro"):
        raise RoteiroError("Primeiro cole o JSON do 1º passo (roteiro + cenas).")
    acoes = [a for a in acoes if a in {k for k, _n, _d in ACOES}]
    if not acoes and not (extra or "").strip():
        raise RoteiroError("Marque pelo menos uma coisa pra IA fazer (ou escreva o que quer).")
    import idiomas
    alvo = idiomas.nome_para_prompt(idiomas.normalizar(idioma)) if "traduzir" in acoes else "o mesmo idioma do roteiro"
    if "tags" in acoes and "traduzir" not in acoes and not str(an.get("idioma") or "").lower().startswith("en"):
        tags_aviso = (" ATENÇÃO: as tags do Chatterbox Turbo só funcionam com o modelo em INGLÊS — se o roteiro não estiver "
                      "em inglês, ponha as tags mesmo assim (elas ficam prontas pra quando traduzir).")
    else:
        tags_aviso = ""
    tarefas = []
    if "sem_experiencias" in acoes:
        tarefas.append(REGRA_SEM_EXPERIENCIAS.split("\n\n", 1)[1])
    if "sem_cenas" in acoes:
        tarefas.append("ADAPTE o roteiro pra funcionar SEM mostrar as cenas: onde ele dependia de ver a cena (\"olha isso\", "
                       "\"nessa cena\"), narre o que acontece nela em uma ou duas frases vivas, sem citar tempo de tela.")
    if "marcar_cenas" in acoes:
        tarefas.append("MARQUE no roteiro final, com [CENA n] numa linha própria, o ponto exato onde cada cena da lista entra "
                       "(n = o número da cena). Toda cena da lista que ainda fizer sentido ganha um marcador.")
    if "traduzir" in acoes:
        tarefas.append(f"TRADUZA o roteiro final pra {alvo} — natural, como um narrador nativo falaria, adaptando expressões "
                       "e exemplos culturais (não traduza palavra por palavra). Nomes de obras: use o título oficial nesse idioma.")
    if "tags" in acoes:
        tarefas.append(
            "Ponha TAGS DE VOZ do Chatterbox Turbo no roteiro final, escritas exatamente assim, entre colchetes, em inglês." + tags_aviso + "\n"
            "   Sons (no ponto exato em que o som acontece): " + " ".join(f"[{t}]" for t in TAGS_SOM) + "\n"
            "   Estilo (funcionam melhor no INÍCIO da frase): " + " ".join(f"[{t}]" for t in TAGS_ESTILO) + "\n"
            "   Use com bom senso — onde um narrador de verdade faria aquilo (ex.: [whispering] num segredo, [dramatic] numa "
            "virada, [chuckle] depois de uma ironia, [sigh] num lamento). Em média uma tag a cada 2-4 frases; nunca invente "
            "tags fora dessa lista.")
    if "ads" in acoes:
        tarefas.append("ACHE os melhores momentos pra ANÚNCIO/VENDA: logo depois de um gancho/suspense ou numa troca de "
                       "assunto, nunca no meio de uma explicação nem nos primeiros 15% do roteiro. Um a cada ~3-4 minutos de "
                       "narração (~450-600 palavras). "
                       + ("NO ROTEIRO FINAL, ponha a marca [[VENDA]] sozinha numa linha em cada um desses pontos (colchete DUPLO, "
                          "maiúsculas, sem frase — ali entra um vídeo pronto de venda; se o roteiro já tem [[VENDA]], ajuste as "
                          "posições em vez de duplicar), e liste em \"ads\"."
                          if cta_no_texto else "Liste em \"ads\"."))
    if "cta" in acoes:
        tarefas.append("Crie CHAMADAS PRA AÇÃO curtas e naturais (deixar o like, se inscrever, comentar uma pergunta ligada ao "
                       "assunto), nos melhores pontos: uma leve no começo (depois do gancho), uma no meio, uma no fim. "
                       + ("NO ROTEIRO FINAL, ponha só a marca [[INSCREVA]] numa linha própria em cada um desses pontos (colchete "
                          "DUPLO, em maiúsculas, sem frase — ali entra um vídeo pronto de like/inscreva-se; se o roteiro já tem "
                          "[[INSCREVA]], ajuste as posições em vez de duplicar), e liste em \"ctas\" a frase que você sugeriria."
                          if cta_no_texto else "NÃO escreva no roteiro — só liste em \"ctas\" com o ponto onde entra."))
    if "limpar_tts" in acoes:
        tarefas.append(
            "DEIXE O TEXTO À PROVA DE TTS (o gerador de voz lê tudo literalmente e engasga com o que não é palavra): corrija "
            "palavras escritas errado, letras trocadas e palavras coladas/cortadas (erros comuns de legenda automática); "
            "escreva por extenso o que se fala diferente do que se escreve — números e anos do jeito que se lê (\"1992\" → "
            "\"mil novecentos e noventa e dois\" / \"nineteen ninety-two\"), porcentagem, moeda, horas, \"km\", \"nº\", "
            "\"etc.\", \"vs\", \"&\", siglas que se soletram (\"FBI\" → \"F B I\") e abreviações; tire emojis, hashtags, "
            "@menções, links, markdown (*, #, _), aspas e travessões decorativos, parênteses de nota, \"(risos)\", "
            "\"[música]\", \"[aplausos]\" e qualquer marcação de legenda; troque reticências em excesso e \"!!!\"/\"???\" "
            "por pontuação simples; nada de letras repetidas (\"muuuito\"). NÃO mexa nas tags de voz da lista (colchetes "
            "com as palavras exatas) nem nos [CENA n], nem nas marcas [[INSCREVA]] e [[VENDA]].")
    if "titulos" in acoes:
        tarefas.append("Sugira 5 TÍTULOS fortes pro vídeo e uma 1ª frase (gancho) mais forte, em \"titulos\" e \"gancho\".")
    titulo_orig = (p.get("titulo") or ((p.get("transcricao") or {}).get("titulo")) or "").strip()
    if "descricao" in acoes:
        idioma_desc = alvo if "traduzir" in acoes else "o mesmo idioma do roteiro_final"
        tarefas.append(
            f"Escreva a DESCRIÇÃO do vídeo pro YouTube, em {idioma_desc}: 2-3 parágrafos curtos que prendem (o 1º com a promessa "
            "do vídeo, sem spoiler do final), depois 3-5 hashtags no fim. Em \"descricao\" (sem os capítulos — o site monta os "
            "tempos). Divida o roteiro_final em CAPÍTULOS (5 a 12, cada um com pelo menos ~30 s de fala, o 1º começando no "
            "início do roteiro) e liste em \"capitulos\": título curto e chamativo de cada um + \"comeca_em\" = as primeiras "
            "6-10 palavras EXATAS do roteiro_final onde o capítulo começa (cópia exata, pra o site achar e calcular o tempo). "
            + (f"Traduza também o título do vídeo original (“{titulo_orig}”) em \"titulo_original\" e " if titulo_orig and "traduzir" in acoes else
               (f"Em \"titulo_original\" repita o título original (“{titulo_orig}”) e " if titulo_orig else ""))
            + f"sugira 5 TÍTULOS alternativos em \"titulos\" ({idioma_desc}; fortes, até ~70 caracteres, sem clickbait mentiroso).")
    if (extra or "").strip():
        tarefas.append("Pedido extra de quem está editando (siga com prioridade): " + extra.strip()[:1500])
    if {"sem_cenas", "sem_experiencias", "traduzir"} & set(acoes) or (extra or "").strip():
        import metodo_roteiro  # reescrevendo o texto: o mesmo método de roteiro do 1º passo
        tarefas.append("Ao mexer no texto do roteiro, siga o MÉTODO DE ROTEIRO abaixo (sem mudar os fatos):\n"
                       + metodo_roteiro.bloco("reescrita").split("\n", 1)[1])
    cenas_txt = "\n".join(
        f"{c['id']}. {c['obra']} ({c['tipo']}{', ' + c['ano'] if c.get('ano') else ''}) — {c['momento']}"
        + (f" | entra em: \"{c['trecho_do_roteiro']}\"" if c.get("trecho_do_roteiro") else "")
        for c in an.get("cenas") or []) or "(nenhuma)"
    marcas = marcas_no_texto(an.get("roteiro") or "")
    if any(marcas.values()):
        tarefas.append(REGRA_MANTER_MARCAS)
    lista = "\n".join(f"{k}. {t}" for k, t in enumerate(tarefas, start=1))
    return f"""Você é roteirista e editor de um canal do YouTube. Abaixo está um roteiro já reescrito e a lista de cenas de filmes/séries/animes que ele usa.{chr(10) + chr(10) + "Título do vídeo original: " + titulo_orig if titulo_orig else ""}

## O que fazer

{lista}

Mantenha o conteúdo e a ordem das ideias; não corte partes importantes. O "roteiro_final" vai direto pra um gerador de voz: só o texto falado (sem títulos, sem "Narrador:", sem marcações de câmera) — fora as tags, os [CENA n] e as marcas [[INSCREVA]]/[[VENDA]].

## Roteiro

{an['roteiro']}

## Cenas

{cenas_txt}

## Formato de resposta — IMPORTANTE

Responda **apenas** com um JSON válido (sem texto antes ou depois), assim (omita as chaves do que não foi pedido):

{{
  "idioma": "{idioma if 'traduzir' in acoes else (an.get('idioma') or '')}",
  "roteiro_final": "o roteiro completo, pronto pra narrar, parágrafos separados por \\n\\n",
  "ads": [{{"depois_de": "as últimas palavras da frase depois da qual entra o anúncio (cópia exata do roteiro_final)", "motivo": "por que ali"}}],
  "ctas": [{{"tipo": "like | inscrever | comentar", "texto": "a frase da chamada", "depois_de": "as últimas palavras da frase anterior (cópia exata)"}}],
  "cenas": [{{"id": 1, "obra": "...", "momento": "...", "marcador": "[CENA 1]", "como_ficou": "mostrada | narrada | removida"}}],
  "titulos": ["..."],
  "gancho": "...",
  "titulo_original": "...",
  "descricao": "...",
  "capitulos": [{{"titulo": "...", "comeca_em": "as primeiras palavras exatas do capítulo no roteiro_final"}}],
  "observacoes": "..."
}}"""


def _onde(roteiro: str, depois_de: str) -> Optional[float]:
    """Posição (0-1) de um trecho no roteiro — pra mostrar onde o anúncio cai
    e estimar o tempo depois que o áudio existir."""
    alvo = " ".join((depois_de or "").lower().split())
    texto = " ".join((roteiro or "").lower().split())
    if not alvo or not texto:
        return None
    i = texto.find(alvo)
    if i < 0 and len(alvo) > 30:
        i = texto.find(alvo[-30:])
        alvo = alvo[-30:]
    return round((i + len(alvo)) / len(texto), 4) if i >= 0 else None


def ler_resultado(texto: str, p: Dict[str, Any]) -> Dict[str, Any]:
    d = extrair_json(texto)
    if not isinstance(d, dict):
        raise RoteiroError("Esperava um objeto JSON com \"roteiro_final\".")
    roteiro = str(d.get("roteiro_final") or d.get("roteiro") or "").strip()
    if not roteiro and not d.get("ads") and not d.get("ctas") and not d.get("titulos") and not d.get("descricao"):
        raise RoteiroError("O JSON não tem \"roteiro_final\" (nem ads/ctas/títulos).")
    avisos: List[str] = []
    validas = set(TAGS_SOM) | set(TAGS_ESTILO)
    import chamadas as _ch
    usadas = [t.strip().lower() for t in re.findall(r"\[([^\]\[]{2,30})\]", _ch.MARCADOR.sub(" ", roteiro))]
    desconhecidas = sorted({t for t in usadas if t not in validas and not re.fullmatch(r"cena \d+", t)})
    if desconhecidas:
        avisos.append("Tags que o Chatterbox Turbo não conhece (vão ser lidas em voz alta): " + ", ".join(f"[{t}]" for t in desconhecidas))
    palavras = len(re.sub(r"\[[^\]]*\]", " ", _ch.MARCADOR.sub(" ", roteiro)).split())
    ref = roteiro or (p.get("analise") or {}).get("roteiro", "")
    antes = marcas_no_texto((p.get("analise") or {}).get("roteiro") or "")
    depois = marcas_no_texto(roteiro)
    for tipo, nome in (("inscreva", "[[INSCREVA]]"), ("venda", "[[VENDA]]")):
        if roteiro and antes[tipo] and depois[tipo] < antes[tipo]:
            avisos.append(f"A IA tirou {antes[tipo] - depois[tipo]} marca(s) {nome} que estavam no roteiro — confira (ou peça de novo).")

    def _lista(chave: str, campos: List[str]) -> List[Dict[str, Any]]:
        out = []
        for x in d.get(chave) or []:
            if not isinstance(x, dict):
                continue
            item = {c: str(x.get(c) or "").strip()[:500] for c in campos}
            item["posicao"] = _onde(ref, item.get("depois_de", ""))
            if item.get("depois_de") and item["posicao"] is None:
                avisos.append(f"{'Anúncio' if chave == 'ads' else 'Chamada'} \"…{item['depois_de'][-40:]}\" não foi achado no roteiro (a IA mudou o texto).")
            out.append(item)
        return sorted(out, key=lambda i: (i["posicao"] is None, i["posicao"] or 0))

    cenas_base = {c["id"]: c for c in (p.get("analise") or {}).get("cenas") or []}
    cenas = []
    for x in d.get("cenas") or []:
        if not isinstance(x, dict):
            continue
        try:
            cid = int(x.get("id"))
        except (TypeError, ValueError):
            cid = None
        base = dict(cenas_base.get(cid) or {})
        base.update({k: str(x.get(k) or "").strip()[:300] for k in ("marcador", "como_ficou") if x.get(k)})
        if not base.get("obra") and x.get("obra"):
            c = _cena(x, cid or len(cenas) + 1)
            if c:
                base = dict(c, **{k: str(x.get(k) or "") for k in ("marcador", "como_ficou") if x.get(k)})
        if base:
            cenas.append(base)
    return {
        "idioma": str(d.get("idioma") or "").strip()[:20], "roteiro_final": roteiro, "palavras": palavras,
        "minutos": round(palavras / 150, 1) if palavras else 0,
        "tags": sorted({t for t in usadas if t in validas}),
        "ads": _lista("ads", ["depois_de", "motivo"]),
        "ctas": _lista("ctas", ["tipo", "texto", "depois_de"]),
        "cenas": cenas,
        "titulos": [str(t).strip()[:150] for t in (d.get("titulos") or []) if str(t).strip()][:10],
        "titulo_original": str(d.get("titulo_original") or "").strip()[:200],
        "descricao": str(d.get("descricao") or "").strip()[:4500],
        "capitulos": _capitulos(d.get("capitulos"), ref, palavras, avisos),
        "gancho": str(d.get("gancho") or "").strip()[:400],
        "observacoes": str(d.get("observacoes") or "").strip()[:1500],
        "avisos": avisos,
    }


def _capitulos(lista: Any, roteiro: str, palavras: int, avisos: List[str]) -> List[Dict[str, Any]]:
    """Capítulos da IA -> posição no roteiro (0-1) e tempo estimado (150 palavras/min;
    o 1º sempre em 0:00, como o YouTube exige)."""
    out = []
    for x in lista or []:
        if not isinstance(x, dict) or not str(x.get("titulo") or "").strip():
            continue
        pos = _onde(roteiro, str(x.get("comeca_em") or ""))
        if pos is not None:  # posição em PALAVRAS (o tempo de fala anda por palavra, não por letra)
            texto = " ".join((roteiro or "").lower().split())
            tot = max(1, len(texto.split()))
            pos = len(texto[:int(round(pos * len(texto)))].split()) / tot
        if pos is None and x.get("comeca_em"):
            avisos.append(f"Capítulo “{str(x['titulo'])[:40]}”: não achei “{str(x['comeca_em'])[:40]}…” no roteiro — tempo estimado pela ordem.")
        out.append({"titulo": str(x["titulo"]).strip()[:100], "comeca_em": str(x.get("comeca_em") or "")[:200], "posicao": pos})
    if not out:
        return out
    # sem posição: entre o anterior e o próximo (pela ordem)
    for k, c in enumerate(out):
        if c["posicao"] is None:
            ant = next((out[j]["posicao"] for j in range(k - 1, -1, -1) if out[j]["posicao"] is not None), 0.0)
            prox = next((out[j]["posicao"] for j in range(k + 1, len(out)) if out[j]["posicao"] is not None), 1.0)
            c["posicao"] = ant + (prox - ant) / 2
    out.sort(key=lambda c: c["posicao"])
    out[0]["posicao"] = 0.0
    total = palavras / 150 * 60 if palavras else 0
    for c in out:
        c["segundos"] = round(c["posicao"] * total)
    return out


def _toks(t: str) -> List[str]:
    import unicodedata
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9']+", t)


def capitulos_pelo_audio(p: Dict[str, Any], palavras: List[Dict[str, Any]], duracao: Optional[float]) -> List[Dict[str, Any]]:
    """Tempo REAL de cada capítulo no áudio gerado (TTS): acha as primeiras palavras do
    capítulo nas palavras que o Whisper ouviu no áudio (com o tempo de cada uma).
    Sem as palavras, usa a posição no texto × a duração do áudio."""
    res = p.get("resultado") or {}
    caps = res.get("capitulos") or []
    if not caps:
        return []
    import chamadas as _ch
    falado = re.sub(r"\[[^\]]*\]", " ", _ch.MARCADOR.sub(" ", roteiro_para_voz(p)))
    tf = _toks(falado)
    ouvidas = [(_toks(str(w.get("word") or w.get("text") or "")), float(w.get("start") or 0)) for w in palavras or []]
    seq = [(tok, ini) for toks, ini in ouvidas for tok in toks[:1] if toks]  # 1 token por palavra ouvida
    out = []
    for k, c in enumerate(caps):
        alvo = _toks(c.get("comeca_em") or "")[:5]
        idx = None
        if alvo:  # posição do capítulo no texto falado
            for i in range(len(tf) - len(alvo) + 1):
                if tf[i:i + len(alvo)] == alvo:
                    idx = i
                    break
        if idx is None:
            idx = int(round((c.get("posicao") or 0) * len(tf)))
        seg = None
        if k == 0:
            seg = 0.0
        elif seq and tf:
            est = int(round(idx / max(1, len(tf)) * len(seq)))
            melhor, nota = None, -1
            for j in range(max(0, est - 60), min(len(seq), est + 60)):
                n = sum(1 for a, b in zip(alvo, [x[0] for x in seq[j:j + len(alvo)]]) if a == b)
                if n > nota or (n == nota and melhor is not None and abs(j - est) < abs(melhor - est)):
                    melhor, nota = j, n
            if melhor is not None and nota >= max(1, min(2, len(alvo))):
                seg = seq[melhor][1]
            else:
                seg = seq[min(len(seq) - 1, est)][1]
        elif duracao:
            seg = (idx / max(1, len(tf))) * duracao
        out.append(dict(c, segundos_audio=None if seg is None else round(seg, 1)))
    # o YouTube exige ordem crescente e 10 s entre capítulos
    for k in range(1, len(out)):
        if out[k]["segundos_audio"] is not None and out[k - 1]["segundos_audio"] is not None and out[k]["segundos_audio"] < out[k - 1]["segundos_audio"] + 10:
            out[k]["segundos_audio"] = round(out[k - 1]["segundos_audio"] + 10, 1)
    return out


def aplicar_tempos_do_audio(base: str, pid: str, palavras: List[Dict[str, Any]], duracao: Optional[float], origem: str = "") -> Optional[Dict[str, Any]]:
    """Grava no projeto os tempos reais dos capítulos (depois de gerar a voz)."""
    import time as _time
    p = carregar_projeto(base, pid)
    res = p.get("resultado") or {}
    if not res.get("capitulos"):
        return None
    res["capitulos"] = capitulos_pelo_audio(p, palavras, duracao)
    res["audio"] = {"duracao": round(duracao, 1) if duracao else None, "gerado_em": _time.time(), "origem": origem,
                    "com_palavras": bool(palavras)}
    p["resultado"] = res
    salvar_projeto(base, p)
    return res


def descricao_com_capitulos(res: Dict[str, Any], segundos_total: Optional[float] = None) -> str:
    """Texto pronto pra colar na descrição do YouTube: a descrição + "0:00 Capítulo"."""
    caps = res.get("capitulos") or []
    total = segundos_total or ((res.get("audio") or {}).get("duracao")) or (res.get("palavras", 0) / 150 * 60)
    linhas = []
    for c in caps:
        s = int(round(c["segundos_audio"] if c.get("segundos_audio") is not None and not segundos_total else (c.get("posicao") or 0) * total))
        linhas.append(f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d} {c['titulo']}" if total >= 3600 else f"{s // 60}:{s % 60:02d} {c['titulo']}")
    partes = [res.get("descricao") or ""]
    if linhas:
        partes.append("\n".join(linhas))
    return "\n\n".join(p for p in partes if p).strip()


# ------------------------------------------------------------------ saídas
def cenas_atuais(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """As cenas do resultado (com marcador) se existir; senão as da análise."""
    res = p.get("resultado") or {}
    return res.get("cenas") or (p.get("analise") or {}).get("cenas") or []


def texto_para_cortar(p: Dict[str, Any], ids: Optional[List[int]] = None, do_original: bool = False) -> str:
    """Texto no formato que a aba ✂️ Cortar do YouTube entende (link + tempo +
    descrição, uma por linha): cada cena com link escolhido; com
    `do_original`, as que só têm o tempo do vídeo original saem dele."""
    linhas = []
    for c in cenas_atuais(p):
        if ids and c.get("id") not in ids:
            continue
        desc = f"{c.get('id')}. {c.get('obra')} — {c.get('momento')}"[:160]
        if c.get("link"):
            tempo = f"{c['link_inicio']} - {c['link_fim']}" if c.get("link_inicio") and c.get("link_fim") else ""
            linhas.append(f"{c['link']} {tempo} {desc}".replace("  ", " ").strip())
        elif do_original and p.get("url") and c.get("inicio"):
            fim = c.get("fim") or c["inicio"]
            linhas.append(f"{p['url']} {c['inicio']} - {fim} {desc}")
    return "\n".join(linhas)


def roteiro_para_voz(p: Dict[str, Any], sem_marcadores: bool = True) -> str:
    res = p.get("resultado") or {}
    t = res.get("roteiro_final") or (p.get("analise") or {}).get("roteiro") or ""
    if sem_marcadores:
        import chamadas
        t = chamadas.tirar_marcas_de_cena(t)[0]
    return re.sub(r"\n{3,}", "\n\n", t).strip()



# ------------------------------------------------------------------ limpeza local pro TTS (sem IA)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF\U0000FE0F\U0000200D\U000020E3]+")
_INVISIVEIS = re.compile("[​‌‎‏⁠﻿­\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
_TROCAS = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "´": "'", "`": "'",
    "—": ", ", "–": ", ", "―": ", ", "…": "...", "•": ", ", "·": " ", "▪": ", ", "►": "", "▶": "", "→": ", ",
    "™": "", "®": "", "©": "", "°": " graus", " ": " ", " ": " ", " ": " ",
}
_MARCACOES_LEGENDA = re.compile(
    r"[\[(](?:m[uú]sica|music|aplausos|applause|risos|laughter|laughs|inaud[ií]vel|inaudible|sil[eê]ncio|silence|"
    r"barulho|noise|ru[ií]do|♪+)[\])]", re.IGNORECASE)


def limpar_para_tts(texto: str, idioma: str = "") -> Dict[str, Any]:
    """Limpeza SEM IA do que faz o gerador de voz engasgar ou ler coisa
    estranha: emojis, caracteres invisíveis, marcações de legenda ([Música],
    (risos)), markdown, links, @menções, #hashtags, aspas/travessões
    tipográficos, pontuação repetida, letras repetidas ("muuuito"), tags
    entre colchetes que o Chatterbox Turbo não conhece. As tags válidas e os
    [CENA n] ficam. Devolve {"texto", "mudancas": [contagem por tipo]}.
    (Palavra escrita errado e número por extenso precisam de contexto — isso é
    a opção 🧹 do passo 3, feita pela IA.)"""
    validas = set(TAGS_SOM) | set(TAGS_ESTILO)
    ingles = str(idioma or "").lower().startswith("en")
    mud: Dict[str, int] = {}

    def _sub(nome: str, padrao, troca, t: str, flags: int = 0) -> str:
        novo, n = (padrao.subn(troca, t) if hasattr(padrao, "subn") else re.subn(padrao, troca, t, flags=flags))
        if n:
            mud[nome] = mud.get(nome, 0) + n
        return novo

    t = str(texto or "").replace("\r\n", "\n").replace("\r", "\n")
    # chamadas [[INSCREVA: ...]] (ver chamadas.py): ficam, com o texto de dentro limpo também
    import chamadas as _ch
    guardadas: List[str] = []

    def _guarda(m: "re.Match[str]") -> str:
        if not _ch.tipo_do_nome(m.group(1)):
            return m.group(0)
        dentro = limpar_para_tts(m.group(2), idioma)["texto"] if m.group(2) else ""
        guardadas.append(f"[[{m.group(1).strip().upper()}" + (f": {dentro}" if dentro else "") + "]]")
        return f"QQCHAMADA{len(guardadas) - 1}QQ"
    t = _ch.MARCADOR.sub(_guarda, t)
    t = _sub("caracteres invisíveis", _INVISIVEIS, "", t)
    t = _sub("emojis", _EMOJI, "", t)
    t = _sub("marcações de legenda ([Música], (risos)…)", _MARCACOES_LEGENDA, "", t)
    t = _sub("links", r"https?://\S+|www\.\S+", "", t)
    t = _sub("@menções", r"(?<!\w)@\w+", "", t)
    t = _sub("#hashtags", r"(?<!\w)#\w+", "", t)
    t = _sub("markdown (*, #, _)", r"^\s{0,3}#{1,6}\s*|\*{1,3}|(?<!\w)_{1,2}|_{1,2}(?!\w)|^\s*[-*+]\s+(?=\S)|^\s*>\s?", "", t, re.MULTILINE)

    def _tag(m: "re.Match[str]") -> str:
        dentro = m.group(1).strip().lower()
        if dentro in validas or re.fullmatch(r"cena \d+", dentro):
            return m.group(0)
        mud["tags desconhecidas entre colchetes"] = mud.get("tags desconhecidas entre colchetes", 0) + 1
        return ""
    t = re.sub(r"\[([^\[\]\n]{1,40})\]", _tag, t)
    # o que sobrou de colchete/chave solto (as tags válidas já estão inteiras: ficam)
    partes = re.split(r"(\[[^\[\]\n]{1,40}\])", t)
    for k in range(0, len(partes), 2):
        partes[k] = _sub("colchetes/chaves soltos", r"[\[\]{}<>|\\^~]+", " ", partes[k])
    t = "".join(partes)
    n_troca = 0
    for de, para in _TROCAS.items():
        if de in t:
            n_troca += t.count(de)
            t = t.replace(de, para if not (de == "°" and ingles) else " degrees")
    if n_troca:
        mud["aspas, travessões e símbolos tipográficos"] = n_troca
    t = _sub("& escrito por extenso", r"\s*&\s*", " and " if ingles else " e ", t)
    t = _sub("pontuação repetida", r"([!?])[!?]+", r"\1", t)
    t = _sub("reticências em excesso", r"\.{4,}", "...", t)
    t = _sub("letras repetidas (muuuito)", r"([a-zà-ÿ])\1{2,}", r"\1", t)  # só minúsculas: "Rocky III" fica
    t = _sub("pontuação colada/duplicada", r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r",\s*,+", ",", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    t = re.sub(r"QQCHAMADA(\d+)QQ", lambda m: guardadas[int(m.group(1))], t)
    return {"texto": t, "mudancas": [{"tipo": k, "quantas": v} for k, v in mud.items()]}


def aplicar_limpeza(p: Dict[str, Any]) -> Dict[str, Any]:
    """🧹 do resultado: limpa o roteiro final (ou o reescrito, se ainda não tem
    final) e guarda o anterior pra desfazer."""
    res = p.get("resultado")
    alvo = res if res and res.get("roteiro_final") else p.get("analise")
    chave = "roteiro_final" if alvo is res else "roteiro"
    if not alvo or not alvo.get(chave):
        raise RoteiroError("Ainda não tem roteiro pra limpar.")
    idioma = (res or {}).get("idioma") or (p.get("analise") or {}).get("idioma") or ""
    feito = limpar_para_tts(alvo[chave], idioma)
    if feito["texto"] != alvo[chave]:
        alvo.setdefault("antes_da_limpeza", alvo[chave])
        alvo[chave] = feito["texto"]
        if alvo.get("avisos"):  # o aviso de tag desconhecida perde o sentido depois da limpeza
            alvo.setdefault("avisos_antes_da_limpeza", list(alvo["avisos"]))
            alvo["avisos"] = [a for a in alvo["avisos"] if not a.startswith("Tags que o Chatterbox")]
    return {"texto": feito["texto"], "mudancas": feito["mudancas"], "pode_desfazer": bool(alvo.get("antes_da_limpeza"))}


def desfazer_limpeza(p: Dict[str, Any]) -> bool:
    for alvo, chave in ((p.get("resultado"), "roteiro_final"), (p.get("analise"), "roteiro")):
        if alvo and alvo.get("antes_da_limpeza"):
            alvo[chave] = alvo.pop("antes_da_limpeza")
            if "avisos_antes_da_limpeza" in alvo:
                alvo["avisos"] = alvo.pop("avisos_antes_da_limpeza")
            return True
    return False
