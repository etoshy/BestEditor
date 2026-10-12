"""
analisador_canal.py
===================

📊 ANALISADOR DE CANAL — cola o link de um canal do YouTube e o site junta:

  • o cabeçalho (nome, inscritos, nº de vídeos, views totais, país);
  • os 20 vídeos MAIS RECENTES e os 20 MAIS POPULARES (miniatura, título, duração,
    views, data), lidos pelo mesmo leitor de página do ⛏ Niche Miner
    (niche_miner/yt_scraper.py, Playwright) — com o yt-dlp de reserva;
  • se der, os detalhes de cada vídeo pelo yt-dlp (data exata, likes, comentários, tags);
  • a TRANSCRIÇÃO de cada vídeo direto do YouTube (youtube-transcript-api → painel
    "Mostrar transcrição"), com o gancho (1º minuto) e as palavras por minuto.

Depois calcula as métricas (mediana, fator outlier, views/dia, padrões de título) e manda
tudo pra IA (🤖 IA nas buscas e modelos, recurso "canal") — com as MINIATURAS como imagem.
A IA devolve o que o canal faz bem, que títulos/capas funcionam e quais não, os tipos de
vídeo e quais performam melhor, e sugestões de vídeos novos. Sem a IA ligada, o site
mostra o prompt pra colar numa IA de chat e lê o JSON de volta.

Cada análise fica em analises_canal/<id>/analise.json (fora do GitHub).
"""
from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import os
import re
import shutil
import statistics
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

PASTA = "analises_canal"
N_PADRAO = 20
N_MAX = 50
_AQUI = os.path.dirname(os.path.abspath(__file__))
NICHE_MINER_DIR = os.path.join(_AQUI, "niche_miner")
_TRAVA = threading.Lock()


class AnaliseError(Exception):
    pass


# ------------------------------------------------------------------ link do canal
def normalizar_url_canal(texto: str) -> str:
    """Aceita @nome, youtube.com/@nome, /channel/UC..., /c/nome e /user/nome (com ou sem /videos…)."""
    t = str(texto or "").strip()
    if not t:
        raise AnaliseError("Cole o link do canal.")
    if re.fullmatch(r"@[^\s/?#]+", t):
        return f"https://www.youtube.com/{t}"
    if not re.match(r"^https?://", t, re.I):
        t = "https://" + t.lstrip("/")
    m = re.match(r"^https?://(?:www\.|m\.)?youtube\.com(/[^?#\s]*)?", t, re.I)
    if not m:
        raise AnaliseError("Isso não parece um link do YouTube. Use youtube.com/@nome do canal.")
    caminho = (m.group(1) or "").rstrip("/")
    if re.match(r"^/(watch|shorts|live|playlist|results|feed)\b", caminho):
        raise AnaliseError("Esse é o link de um vídeo. Cole o link do CANAL (youtube.com/@nome).")
    for padrao in (r"^(/@[^/]+)", r"^(/channel/[A-Za-z0-9_-]{10,})", r"^(/c/[^/]+)", r"^(/user/[^/]+)"):
        achou = re.match(padrao, caminho)
        if achou:
            return "https://www.youtube.com" + achou.group(1)
    raise AnaliseError("Não achei o canal nesse link. Use youtube.com/@nome ou youtube.com/channel/...")


# ------------------------------------------------------------------ pasta / disco
def _pasta(base: str) -> str:
    p = os.path.join(base, PASTA)
    os.makedirs(p, exist_ok=True)
    return p


def _arq(base: str, aid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{10}", str(aid or "")):
        raise AnaliseError("Análise não encontrada.")
    return os.path.join(_pasta(base), aid, "analise.json")


def salvar(base: str, a: Dict[str, Any]) -> None:
    caminho = _arq(base, a["id"])
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with _TRAVA:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False, indent=1)
        os.replace(tmp, caminho)


def carregar(base: str, aid: str) -> Dict[str, Any]:
    try:
        with open(_arq(base, aid), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise AnaliseError("Análise não encontrada.") from exc


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    for nome in os.listdir(_pasta(base)):
        try:
            a = carregar(base, nome)
        except AnaliseError:
            continue
        c = a.get("canal") or {}
        out.append({"id": a["id"], "nome": c.get("nome") or a.get("url"), "url": a.get("url"), "criado": a.get("criado", 0),
                    "estado": a.get("estado"), "inscritos": c.get("inscritos_text"), "tem_ia": bool(a.get("ia")),
                    "n_videos": len(a.get("videos") or {})})
    return sorted(out, key=lambda x: -x["criado"])


def apagar(base: str, aid: str) -> None:
    pasta = os.path.dirname(_arq(base, aid))
    if os.path.isdir(pasta):
        shutil.rmtree(pasta, ignore_errors=True)


def nova(base: str, url: str, n: int = N_PADRAO, transcricoes: bool = True) -> Dict[str, Any]:
    a = {"id": uuid.uuid4().hex[:10], "url": normalizar_url_canal(url), "n": max(5, min(N_MAX, int(n or N_PADRAO))),
         "transcricoes": bool(transcricoes), "criado": time.time(), "estado": "na_fila", "etapa": "", "log": [],
         "canal": {}, "videos": {}, "recentes": [], "populares": [], "metricas": {}, "ia": None, "erro": None}
    salvar(base, a)
    return a


# ------------------------------------------------------------------ números
def duracao_s(txt: Any) -> Optional[int]:
    if isinstance(txt, (int, float)):
        return int(txt)
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*", str(txt or ""))
    if not m:
        return None
    p = [int(x) for x in m.groups() if x is not None]
    s = 0
    for x in p:
        s = s * 60 + x
    return s


def fmt_dur(s: Optional[float]) -> str:
    try:
        s = int(round(float(s)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def fmt_num(n: Optional[float]) -> str:
    try:
        n = float(n)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"
    for lim, suf in ((1e9, " bi"), (1e6, " mi"), (1e3, " mil")):
        if abs(n) >= lim:
            v = n / lim
            return (f"{v:.1f}".rstrip("0").rstrip(".") + suf).replace(".", ",")
    return f"{int(n)}"


def _data(v: Dict[str, Any]) -> Optional[date]:
    for k in ("data", "data_aprox"):
        t = str(v.get(k) or "")[:10]
        try:
            return datetime.strptime(t, "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ coleta (Niche Miner / yt-dlp)
_NM_SCRAPER = None


def nm_scraper():
    """O yt_scraper.py do Niche Miner, carregado com um nome próprio (não briga com os módulos do site)."""
    global _NM_SCRAPER
    if _NM_SCRAPER is None:
        caminho = os.path.join(NICHE_MINER_DIR, "yt_scraper.py")
        spec = importlib.util.spec_from_file_location("nm_yt_scraper", caminho)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _NM_SCRAPER = mod
    return _NM_SCRAPER


def _video_do_card(c: Dict[str, Any]) -> Dict[str, Any]:
    vid = c.get("video_id")
    return {"id": vid, "titulo": c.get("titulo") or "", "url": c.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "views": c.get("views_num"), "views_text": c.get("views_text") or "", "quando": c.get("quando") or "",
            "data_aprox": c.get("data_aprox") or "", "duracao_s": duracao_s(c.get("duracao")),
            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}


def coletar_playwright(url: str, n: int, log: Callable[[str], None], headless: bool = True) -> Dict[str, Any]:
    """Cabeçalho + N recentes + N populares pela página do canal (Chromium)."""
    from playwright.sync_api import sync_playwright
    core = nm_scraper()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--mute-audio"])
        try:
            page = browser.new_context(locale="pt-BR").new_page()
            page.set_default_timeout(core.NAV_TIMEOUT)
            log("Lendo o cabeçalho do canal…")
            sobre = core.scrape_channel_about(page, url)
            try:
                nome = re.sub(r"\s*-\s*YouTube\s*$", "", page.title() or "", flags=re.I).strip()
            except Exception:  # noqa: BLE001
                nome = ""
            log(f"Lendo os {n} vídeos mais recentes…")
            core._abrir_videos_canal(page, url, "recentes")
            try:
                nome = re.sub(r"\s*-\s*YouTube\s*$", "", page.title() or "", flags=re.I).strip() or nome
            except Exception:  # noqa: BLE001
                pass
            rec, _fim = core._coletar_cards_canal(page, n)
            log(f"Lendo os {n} mais populares…")
            aplicou = core._abrir_videos_canal(page, url, "populares")
            pop, _ = core._coletar_cards_canal(page, n) if aplicou else ([], False)
            if not aplicou:
                log("⚠ O YouTube não mostrou a ordem 'Populares' — os populares saem dos vídeos mais vistos que deu pra carregar.")
                mais, _ = core._coletar_cards_canal(page, max(4 * n, 80))
                pop = sorted(mais, key=lambda c: c.get("views_num") or -1, reverse=True)[:n]
        finally:
            browser.close()
    canal = {"nome": nome, "inscritos_text": sobre.get("inscritos_text"), "inscritos": sobre.get("inscritos_num"),
             "n_videos": sobre.get("n_videos"), "views_totais": sobre.get("views_totais"),
             "pais": sobre.get("pais_canal"), "idioma": sobre.get("idioma_canal"), "criado_em": sobre.get("data_criacao_canal")}
    return {"canal": canal, "recentes": [_video_do_card(c) for c in rec], "populares": [_video_do_card(c) for c in pop],
            "fonte": "página do canal (Niche Miner)"}


def coletar_ytdlp(url: str, n: int, log: Callable[[str], None], ytdlp_module: Any = None) -> Dict[str, Any]:
    """Reserva: a lista da aba Vídeos pelo yt-dlp (sem abrir navegador). Populares = os mais vistos
    entre os ~200 mais recentes (o yt-dlp não ordena por popularidade)."""
    if ytdlp_module is None:
        import yt_dlp as ytdlp_module  # type: ignore
    log("Lendo a lista de vídeos pelo yt-dlp…")
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist",
            "playlistend": max(n, 200)}
    with ytdlp_module.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url.rstrip("/") + "/videos", download=False)
    ents = [e for e in (info.get("entries") or []) if isinstance(e, dict) and e.get("id")]

    def _v(e):
        vid = e["id"]
        return {"id": vid, "titulo": e.get("title") or "", "url": f"https://www.youtube.com/watch?v={vid}",
                "views": e.get("view_count"), "views_text": "", "quando": "", "data_aprox": "",
                "duracao_s": int(e["duration"]) if e.get("duration") else None,
                "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"}
    vs = [_v(e) for e in ents]
    canal = {"nome": info.get("channel") or info.get("uploader") or info.get("title") or "",
             "inscritos": info.get("channel_follower_count"), "inscritos_text": fmt_num(info.get("channel_follower_count")) + " inscritos"
             if info.get("channel_follower_count") else "", "n_videos": None}
    pop = sorted([v for v in vs if v["views"] is not None], key=lambda v: -v["views"])[:n]
    return {"canal": canal, "recentes": vs[:n], "populares": pop, "fonte": "yt-dlp (populares = mais vistos dos ~200 recentes)"}


def detalhes_ytdlp(vid: str, ytdlp_module: Any = None) -> Dict[str, Any]:
    """Data exata, likes, comentários, tags e o começo da descrição (sem baixar o vídeo)."""
    if ytdlp_module is None:
        import yt_dlp as ytdlp_module  # type: ignore
    with ytdlp_module.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        i = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    d = str(i.get("upload_date") or "")
    out = {"likes": i.get("like_count"), "comentarios": i.get("comment_count"), "tags": (i.get("tags") or [])[:15],
           "descricao": (i.get("description") or "")[:600], "capitulos": [c.get("title") for c in (i.get("chapters") or [])][:20]}
    if re.fullmatch(r"\d{8}", d):
        out["data"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    if i.get("view_count") is not None:
        out["views"] = i["view_count"]
    if i.get("duration"):
        out["duracao_s"] = int(i["duration"])
    return out


def transcricao_youtube(url: str, pasta: str) -> Dict[str, Any]:
    """A transcrição que o próprio YouTube tem (sem baixar o vídeo e sem Whisper)."""
    import yt_alternativas as alt
    erros = []
    try:
        r = alt.legenda_transcript_api(url, ["pt", "en", "es"])
        if r and r.get("linhas"):
            return {"linhas": r["linhas"], "fonte": "youtube-transcript-api"}
    except Exception as exc:  # noqa: BLE001
        erros.append(str(exc)[:120])
    try:
        r = alt.legenda_painel(url, headless=True)
        if r and r.get("linhas"):
            return {"linhas": r["linhas"], "fonte": "painel de transcrição"}
    except Exception as exc:  # noqa: BLE001
        erros.append(str(exc)[:120])
    return {"linhas": [], "erro": "; ".join(erros) or "sem legenda"}


def resumo_transcricao(linhas: List[Dict[str, Any]], duracao: Optional[int]) -> Dict[str, Any]:
    texto = " ".join(str(l.get("texto") or "").strip() for l in linhas).strip()
    texto = re.sub(r"\[(música|music|aplausos|applause|risadas)\]", "", texto, flags=re.I)
    texto = re.sub(r"\s+", " ", texto).strip()
    palavras = len(texto.split())
    gancho = " ".join(str(l.get("texto") or "") for l in linhas if float(l.get("inicio") or 0) < 60).strip()
    fala = None
    if linhas:
        fala = max(1.0, float(linhas[-1].get("fim") or linhas[-1].get("inicio") or 0) - float(linhas[0].get("inicio") or 0))
    ppm = round(palavras / ((fala or duracao or 0) / 60.0)) if (fala or duracao) and palavras else None
    return {"palavras": palavras, "ppm": ppm, "gancho": re.sub(r"\s+", " ", gancho)[:900], "texto": texto[:60000]}


def executar(base: str, aid: str, coletor: Optional[Callable] = None, detalhes: Optional[Callable] = None,
             transcritor: Optional[Callable] = None, depois: Optional[Callable] = None) -> Dict[str, Any]:
    """Roda a coleta inteira (chamado numa thread). Grava o andamento em analise.json."""
    a = carregar(base, aid)

    def log(msg):
        a["log"] = (a.get("log") or [])[-60:] + [time.strftime("%H:%M:%S ") + msg]
        a["etapa"] = msg
        salvar(base, a)

    a["estado"] = "coletando"
    try:
        dados = None
        if coletor is not None:
            dados = coletor(a["url"], a["n"], log)
        else:
            try:
                dados = coletar_playwright(a["url"], a["n"], log)
                if not dados.get("recentes"):
                    raise AnaliseError("a página do canal veio vazia")
            except Exception as exc:  # noqa: BLE001
                log(f"⚠ Navegador não leu o canal ({str(exc)[:160]}) — tentando pelo yt-dlp…")
                dados = coletar_ytdlp(a["url"], a["n"], log)
        if not dados or not (dados.get("recentes") or dados.get("populares")):
            raise AnaliseError("Não consegui ler os vídeos desse canal. Confira o link e se o canal tem vídeos públicos.")
        a["canal"] = dados.get("canal") or {}
        a["fonte"] = dados.get("fonte")
        videos: Dict[str, Dict[str, Any]] = {}
        for lista in ("recentes", "populares"):
            ids = []
            for v in dados.get(lista) or []:
                if not v.get("id"):
                    continue
                videos.setdefault(v["id"], {}).update({k: x for k, x in v.items() if x not in (None, "")})
                videos[v["id"]].setdefault("listas", [])
                if lista not in videos[v["id"]]["listas"]:
                    videos[v["id"]]["listas"].append(lista)
                ids.append(v["id"])
            a[lista] = ids
        a["videos"] = videos
        log(f"{len(a['recentes'])} recentes + {len(a['populares'])} populares ({len(videos)} vídeos diferentes).")

        # detalhes (data exata, likes…) — opcional
        det = detalhes
        if det is None:
            try:
                import yt_dlp  # noqa: F401
                det = detalhes_ytdlp
            except ImportError:
                det = None
        if det is not None:
            log("Lendo data exata, likes e comentários de cada vídeo…")
            feitos = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(det, vid): vid for vid in videos}
                for fut in concurrent.futures.as_completed(futs):
                    try:
                        videos[futs[fut]].update({k: x for k, x in (fut.result() or {}).items() if x not in (None, "", [])})
                        feitos += 1
                    except Exception:  # noqa: BLE001
                        pass
            log(f"Detalhes de {feitos} de {len(videos)} vídeos.")

        # transcrições
        if a.get("transcricoes", True):
            tr = transcritor or transcricao_youtube
            pasta = os.path.join(os.path.dirname(_arq(base, aid)), "legendas")
            ok = 0
            for k, (vid, v) in enumerate(videos.items(), 1):
                a["etapa"] = f"Transcrições: {k}/{len(videos)}"
                if k == 1 or k % 5 == 0:
                    log(a["etapa"])
                try:
                    r = tr(v["url"], pasta)
                except Exception as exc:  # noqa: BLE001
                    r = {"linhas": [], "erro": str(exc)[:160]}
                if r.get("linhas"):
                    v["transcricao"] = resumo_transcricao(r["linhas"], v.get("duracao_s"))
                    ok += 1
                else:
                    v["transcricao_erro"] = r.get("erro") or "sem legenda"
            log(f"Transcrições: {ok} de {len(videos)} vídeos.")
        a["metricas"] = metricas(a)
        a["estado"] = "pronto"
        log("✅ Coleta pronta.")
    except Exception as exc:  # noqa: BLE001
        a["estado"] = "erro"
        a["erro"] = str(exc)[:500]
        log("❌ " + a["erro"])
        return a
    if depois:
        try:
            depois(a)
        except Exception as exc:  # noqa: BLE001
            a["ia_erro"] = str(exc)[:300]
            salvar(base, a)
    return a


# ------------------------------------------------------------------ métricas
_RE_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
CARACTERISTICAS = {
    "numero": ("Tem número", lambda t: bool(re.search(r"\d", t))),
    "pergunta": ("É pergunta", lambda t: "?" in t),
    "maiusculas": ("PALAVRA EM CAIXA ALTA", lambda t: bool(re.search(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{4,}\b", t))),
    "dois_pontos": ("Tem ':' ou '-' (título em 2 partes)", lambda t: bool(re.search(r":|\s[-–—|]\s", t))),
    "parenteses": ("Tem ( ) ou [ ]", lambda t: bool(re.search(r"[\(\[]", t))),
    "emoji": ("Tem emoji", lambda t: bool(_RE_EMOJI.search(t))),
    "primeira_pessoa": ("Fala em 1ª pessoa (eu/meu/minha)", lambda t: bool(re.search(r"\b(eu|meu|minha|me)\b", t, re.I))),
    "segredo": ("Promete segredo/revelação", lambda t: bool(re.search(r"segredo|verdade|ningu[eé]m|real|oculto|proibid|escondid|bizarr|mist[eé]ri", t, re.I))),
    "como": ("Começa com 'Como'/'Tutorial'", lambda t: bool(re.match(r"\s*(como|tutorial|guia)\b", t, re.I))),
}


def _mediana(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def metricas(a: Dict[str, Any], hoje: Optional[date] = None) -> Dict[str, Any]:
    hoje = hoje or date.today()
    vs = a.get("videos") or {}
    for v in vs.values():
        d = _data(v)
        v["idade_dias"] = (hoje - d).days if d else None
        v["views_dia"] = round(v["views"] / max(1, v["idade_dias"]), 1) if v.get("views") is not None and v.get("idade_dias") is not None else None
    rec = [vs[i] for i in a.get("recentes") or [] if i in vs]
    pop = [vs[i] for i in a.get("populares") or [] if i in vs]
    med_rec = _mediana([v.get("views") for v in rec])
    for v in vs.values():
        v["outlier"] = round(v["views"] / med_rec, 1) if v.get("views") is not None and med_rec else None
    datas = sorted(d for d in (_data(v) for v in rec) if d)
    por_semana = None
    if len(datas) >= 2 and (datas[-1] - datas[0]).days > 0:
        por_semana = round((len(datas) - 1) / ((datas[-1] - datas[0]).days / 7.0), 1)
    insc = (a.get("canal") or {}).get("inscritos")
    # padrões de título: mediana de views COM × SEM (todos os vídeos, sem os de < 14 dias)
    maduros = [v for v in vs.values() if v.get("views") is not None and (v.get("idade_dias") is None or v["idade_dias"] >= 14)]
    padroes = []
    for k, (rot, fn) in CARACTERISTICAS.items():
        com = [v["views"] for v in maduros if fn(v.get("titulo") or "")]
        sem = [v["views"] for v in maduros if not fn(v.get("titulo") or "")]
        if com and sem:
            mc, ms = statistics.median(com), statistics.median(sem)
            padroes.append({"id": k, "rotulo": rot, "com": len(com), "sem": len(sem), "mediana_com": mc, "mediana_sem": ms,
                            "fator": round(mc / ms, 2) if ms else None, "poucos": min(len(com), len(sem)) < 5})
    padroes.sort(key=lambda p: -(p["fator"] or 0))
    durs = [v.get("duracao_s") for v in vs.values() if v.get("duracao_s")]
    faixas = []
    for nome, lo, hi in (("até 8 min", 0, 480), ("8–15 min", 480, 900), ("15–25 min", 900, 1500), ("25–40 min", 1500, 2400), ("40+ min", 2400, 10 ** 6)):
        xs = [v["views"] for v in maduros if v.get("duracao_s") and lo <= v["duracao_s"] < hi]
        if xs:
            faixas.append({"faixa": nome, "n": len(xs), "mediana_views": statistics.median(xs)})
    ppms = [v["transcricao"]["ppm"] for v in vs.values() if (v.get("transcricao") or {}).get("ppm")]
    return {
        "mediana_recentes": med_rec, "mediana_populares": _mediana([v.get("views") for v in pop]),
        "media_views_recentes": round(statistics.mean([v["views"] for v in rec if v.get("views") is not None]))
        if any(v.get("views") is not None for v in rec) else None,
        "tracao": round(med_rec / insc, 3) if med_rec and insc else None,
        "por_semana": por_semana, "duracao_mediana_s": _mediana(durs),
        "duracao_mediana_populares_s": _mediana([v.get("duracao_s") for v in pop]),
        "titulo_medio_chars": round(statistics.mean([len(v.get("titulo") or "") for v in vs.values()])) if vs else None,
        "ppm_mediano": _mediana(ppms), "com_transcricao": sum(1 for v in vs.values() if v.get("transcricao")),
        "outliers": sorted([v["id"] for v in vs.values() if (v.get("outlier") or 0) >= 2], key=lambda i: -(vs[i]["outlier"] or 0))[:10],
        "padroes_titulo": padroes, "faixas_duracao": faixas,
    }


# ------------------------------------------------------------------ IA
SCHEMA_ANALISE: Dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["resumo", "faz_bem", "pode_melhorar", "titulos", "thumbs", "tipos_de_video", "ganchos_e_roteiro",
                 "melhores", "piores", "sugestoes"],
    "properties": {
        "resumo": {"type": "string"},
        "faz_bem": {"type": "array", "items": {"type": "string"}},
        "pode_melhorar": {"type": "array", "items": {"type": "string"}},
        "titulos": {"type": "object", "additionalProperties": False, "required": ["formulas", "funcionam", "nao_funcionam"],
                    "properties": {
                        "formulas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                 "required": ["formula", "exemplos", "desempenho"],
                                                                 "properties": {"formula": {"type": "string"},
                                                                                "exemplos": {"type": "array", "items": {"type": "string"}},
                                                                                "desempenho": {"type": "string"}}}},
                        "funcionam": {"type": "array", "items": {"type": "string"}},
                        "nao_funcionam": {"type": "array", "items": {"type": "string"}}}},
        "thumbs": {"type": "object", "additionalProperties": False, "required": ["estilo", "funcionam", "nao_funcionam", "receita"],
                   "properties": {"estilo": {"type": "string"},
                                  "funcionam": {"type": "array", "items": {"type": "string"}},
                                  "nao_funcionam": {"type": "array", "items": {"type": "string"}},
                                  "receita": {"type": "string"}}},
        "tipos_de_video": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                       "required": ["tipo", "descricao", "videos", "desempenho"],
                                                       "properties": {"tipo": {"type": "string"}, "descricao": {"type": "string"},
                                                                      "videos": {"type": "array", "items": {"type": "string"}},
                                                                      "desempenho": {"type": "string"}}}},
        "ganchos_e_roteiro": {"type": "array", "items": {"type": "string"}},
        "melhores": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "por_que"],
                                                 "properties": {"id": {"type": "string"}, "por_que": {"type": "string"}}}},
        "piores": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "por_que"],
                                               "properties": {"id": {"type": "string"}, "por_que": {"type": "string"}}}},
        "sugestoes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                  "required": ["titulo", "tipo", "por_que", "gancho", "thumb"],
                                                  "properties": {"titulo": {"type": "string"}, "tipo": {"type": "string"},
                                                                 "por_que": {"type": "string"}, "gancho": {"type": "string"},
                                                                 "thumb": {"type": "string"}}}},
    },
}

SYSTEM = (
    "Você é um estrategista de canais do YouTube. Analisa um canal com DADOS REAIS (views, datas, durações, miniaturas, "
    "transcrições) e responde em português do Brasil, direto e concreto. Regras: 1) Toda afirmação sobre o que funciona tem "
    "que se apoiar nos números que vieram (cite views, mediana, fator outlier ou o id do vídeo); amostra pequena = diga "
    "que é hipótese. 2) Não invente números, métricas que não vieram (CTR, retenção, receita) nem vídeos. 3) Nos títulos, "
    "descreva a FÓRMULA (estrutura com lacunas, ex.: 'A [instituição] escondeu [coisa] no [lugar]'), não só copie. "
    "4) Nas miniaturas, fale de rosto/expressão, texto (quantas palavras, cor), cores, objeto central, contraste, "
    "consistência entre vídeos e o que muda nas que performam melhor. 5) Nas sugestões, ideias NOVAS que este canal "
    "consegue entregar bem (mesmo público e estilo), com título no padrão que funciona, sem copiar título existente. "
    "6) Os ids dos vídeos (melhores/piores/tipos) têm que ser exatamente os ids que vieram nos dados.")


def _linha_video(v: Dict[str, Any], med: Optional[float]) -> str:
    partes = [f"[{v['id']}]", f"\"{v.get('titulo', '')}\"", f"views {fmt_num(v.get('views'))}"]
    if v.get("outlier") is not None:
        partes.append(f"outlier ×{v['outlier']}")
    if v.get("duracao_s"):
        partes.append(f"duração {fmt_dur(v['duracao_s'])}")
    if v.get("idade_dias") is not None:
        partes.append(f"há {v['idade_dias']} dias")
    if v.get("views_dia") is not None:
        partes.append(f"{fmt_num(v['views_dia'])}/dia")
    if v.get("likes") is not None:
        partes.append(f"likes {fmt_num(v['likes'])}")
    if v.get("comentarios") is not None:
        partes.append(f"coment. {fmt_num(v['comentarios'])}")
    partes.append("listas: " + "+".join(v.get("listas") or []))
    return " · ".join(partes)


def montar_texto(a: Dict[str, Any], max_chars_transcricao: int = 2500) -> str:
    c, m, vs = a.get("canal") or {}, a.get("metricas") or {}, a.get("videos") or {}
    L = [f"# Canal: {c.get('nome') or a.get('url')}", f"Link: {a.get('url')}",
         f"Inscritos: {c.get('inscritos_text') or fmt_num(c.get('inscritos'))} · vídeos no canal: {c.get('n_videos') or '?'} · "
         f"views totais: {fmt_num(c.get('views_totais'))} · país: {c.get('pais') or '?'}",
         f"Mediana de views dos recentes: {fmt_num(m.get('mediana_recentes'))} · dos populares: {fmt_num(m.get('mediana_populares'))} · "
         f"tração (mediana/inscritos): {m.get('tracao') if m.get('tracao') is not None else '?'} · vídeos por semana: {m.get('por_semana') or '?'}",
         f"Duração mediana: {fmt_dur(m.get('duracao_mediana_s'))} (populares: {fmt_dur(m.get('duracao_mediana_populares_s'))}) · "
         f"palavras por minuto (narração): {m.get('ppm_mediano') or '?'}", ""]
    if m.get("padroes_titulo"):
        L.append("## Padrões de título (mediana de views com × sem)")
        for p in m["padroes_titulo"]:
            L.append(f"- {p['rotulo']}: com {p['com']} vídeos → {fmt_num(p['mediana_com'])}; sem {p['sem']} → {fmt_num(p['mediana_sem'])}"
                     f" (×{p['fator']}){' — poucos vídeos' if p['poucos'] else ''}")
        L.append("")
    if m.get("faixas_duracao"):
        L.append("## Views por faixa de duração: " + "; ".join(f"{f['faixa']}: {f['n']} vídeos, mediana {fmt_num(f['mediana_views'])}"
                                                            for f in m["faixas_duracao"]))
        L.append("")
    for nome, lista in (("20 MAIS RECENTES (do mais novo pro mais velho)", a.get("recentes")),
                        ("MAIS POPULARES (do mais visto pro menos)", a.get("populares"))):
        L.append(f"## {nome}")
        for vid in lista or []:
            if vid in vs:
                L.append("- " + _linha_video(vs[vid], m.get("mediana_recentes")))
        L.append("")
    trs = [v for v in vs.values() if v.get("transcricao")]
    if trs:
        L.append("## Transcrições (gancho = 1º minuto; depois o começo do roteiro)")
        for v in trs:
            t = v["transcricao"]
            L.append(f"### [{v['id']}] {v.get('titulo', '')} — {t.get('palavras')} palavras, {t.get('ppm') or '?'} palavras/min")
            L.append("Gancho: " + (t.get("gancho") or "")[:700])
            corpo = (t.get("texto") or "")[:max_chars_transcricao]
            if corpo:
                L.append("Roteiro (começo): " + corpo)
            if v.get("capitulos"):
                L.append("Capítulos: " + " | ".join(v["capitulos"]))
            L.append("")
    return "\n".join(L)


PEDIDO = (
    "Analise o canal acima e responda no JSON pedido:\n"
    "- resumo: 3–5 frases sobre o canal (nicho, público, formato, como está indo).\n"
    "- faz_bem / pode_melhorar: 4–8 itens cada, com números.\n"
    "- titulos: as fórmulas que o canal usa (com 2–3 exemplos reais e o desempenho de cada fórmula), o que funciona e o que não.\n"
    "- thumbs: o estilo das miniaturas, o que está nas que vão melhor e nas que vão pior, e uma 'receita' de miniatura pro canal.\n"
    "- tipos_de_video: agrupe os vídeos em 3–7 tipos (formato/tema), com os ids e o desempenho de cada tipo.\n"
    "- ganchos_e_roteiro: padrões dos ganchos e da estrutura dos roteiros (pelas transcrições), ritmo, CTA, patrocínio.\n"
    "- melhores / piores: até 5 de cada (id + por quê).\n"
    "- sugestoes: 10 vídeos NOVOS que esse canal entregaria bem (título pronto no padrão que funciona, tipo, por quê, "
    "gancho da 1ª frase e ideia de miniatura).")


def prompt_manual(a: Dict[str, Any]) -> str:
    """Pra colar numa IA de chat (sem a IA ligada no site). As miniaturas vão como link."""
    vs = a.get("videos") or {}
    thumbs = "\n".join(f"- [{vid}] {v.get('thumb')}" for vid, v in vs.items())
    return (SYSTEM + "\n\n" + montar_texto(a) + "\n## Miniaturas (abra os links pra ver)\n" + thumbs + "\n\n" + PEDIDO +
            "\n\nResponda SÓ com um JSON neste formato (sem texto antes ou depois):\n" +
            json.dumps(_exemplo_json(), ensure_ascii=False, indent=1))


def _exemplo_json() -> Dict[str, Any]:
    return {"resumo": "...", "faz_bem": ["..."], "pode_melhorar": ["..."],
            "titulos": {"formulas": [{"formula": "...", "exemplos": ["..."], "desempenho": "..."}], "funcionam": ["..."], "nao_funcionam": ["..."]},
            "thumbs": {"estilo": "...", "funcionam": ["..."], "nao_funcionam": ["..."], "receita": "..."},
            "tipos_de_video": [{"tipo": "...", "descricao": "...", "videos": ["id"], "desempenho": "..."}],
            "ganchos_e_roteiro": ["..."], "melhores": [{"id": "...", "por_que": "..."}], "piores": [{"id": "...", "por_que": "..."}],
            "sugestoes": [{"titulo": "...", "tipo": "...", "por_que": "...", "gancho": "...", "thumb": "..."}]}


def validar_ia(obj: Any, ids_validos: Optional[set] = None) -> Dict[str, Any]:
    """Aceita o JSON da IA (texto ou dict), tolerante: campos faltando viram vazios; ids inexistentes saem."""
    if isinstance(obj, str):
        t = obj.strip()
        t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
        ini, fim = t.find("{"), t.rfind("}")
        if ini < 0 or fim < 0:
            raise AnaliseError("Não achei um JSON na resposta.")
        try:
            obj = json.loads(t[ini:fim + 1])
        except ValueError as exc:
            raise AnaliseError(f"O JSON veio quebrado: {exc}") from exc
    if not isinstance(obj, dict):
        raise AnaliseError("A resposta não é um objeto JSON.")

    def _l(x, n=20):
        return [str(i).strip() for i in (x if isinstance(x, list) else []) if str(i).strip()][:n]

    def _o(x):
        return x if isinstance(x, dict) else {}
    ids_validos = ids_validos or set()

    def _ids(lst):
        out = []
        for it in lst if isinstance(lst, list) else []:
            if isinstance(it, dict) and (not ids_validos or str(it.get("id")) in ids_validos):
                out.append({"id": str(it.get("id")), "por_que": str(it.get("por_que") or "")})
        return out[:8]
    tt, th = _o(obj.get("titulos")), _o(obj.get("thumbs"))
    out = {
        "resumo": str(obj.get("resumo") or ""), "faz_bem": _l(obj.get("faz_bem")), "pode_melhorar": _l(obj.get("pode_melhorar")),
        "titulos": {"formulas": [{"formula": str(f.get("formula") or ""), "exemplos": _l(f.get("exemplos"), 5),
                                  "desempenho": str(f.get("desempenho") or "")}
                                 for f in (tt.get("formulas") or []) if isinstance(f, dict)][:12],
                    "funcionam": _l(tt.get("funcionam")), "nao_funcionam": _l(tt.get("nao_funcionam"))},
        "thumbs": {"estilo": str(th.get("estilo") or ""), "funcionam": _l(th.get("funcionam")),
                   "nao_funcionam": _l(th.get("nao_funcionam")), "receita": str(th.get("receita") or "")},
        "tipos_de_video": [{"tipo": str(t.get("tipo") or ""), "descricao": str(t.get("descricao") or ""),
                            "videos": [i for i in _l(t.get("videos"), 50) if not ids_validos or i in ids_validos],
                            "desempenho": str(t.get("desempenho") or "")}
                           for t in (obj.get("tipos_de_video") or []) if isinstance(t, dict)][:10],
        "ganchos_e_roteiro": _l(obj.get("ganchos_e_roteiro")),
        "melhores": _ids(obj.get("melhores")), "piores": _ids(obj.get("piores")),
        "sugestoes": [{k: str(s.get(k) or "") for k in ("titulo", "tipo", "por_que", "gancho", "thumb")}
                      for s in (obj.get("sugestoes") or []) if isinstance(s, dict) and s.get("titulo")][:15],
    }
    if not (out["resumo"] or out["sugestoes"] or out["faz_bem"]):
        raise AnaliseError("A resposta veio sem o resumo, sem o que o canal faz bem e sem sugestões.")
    return out


def analisar_com_ia(a: Dict[str, Any], com_miniaturas: bool = True) -> Optional[Dict[str, Any]]:
    """Manda pra IA (recurso 'canal'), com as miniaturas como imagem. None se a IA estiver desligada/falhar."""
    import ia_servico as ia
    if not ia.ativo("canal"):
        return None
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": montar_texto(a)}]
    if com_miniaturas:
        conteudo.append({"type": "text", "text": "## Miniaturas (cada uma depois do id)"})
        vs = a.get("videos") or {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            blocos = list(ex.map(lambda vid: (vid, ia.imagem_bloco(vs[vid].get("thumb") or "", largura=320)), list(vs)))
        for vid, b in blocos:
            if b:
                conteudo.append({"type": "text", "text": f"[{vid}] {vs[vid].get('titulo', '')}"})
                conteudo.append(b)
    conteudo.append({"type": "text", "text": PEDIDO})
    r = ia.chamar("canal", SYSTEM, conteudo, schema=SCHEMA_ANALISE, max_tokens=12000, effort="medium", timeout=300,
                  job=a.get("id"))
    if not r:
        return None
    return validar_ia(r, set((a.get("videos") or {}).keys()))
