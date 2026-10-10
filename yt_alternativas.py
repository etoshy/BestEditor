"""
Outros jeitos de pegar a legenda / o áudio / o vídeo do YouTube quando o yt-dlp
leva "Sign in to confirm you're not a bot" (e os cookies não resolvem).

Na ordem em que o site tenta:
  1. yt-dlp com outros "clientes" do YouTube (tv, web_safari, mweb, android…) —
     o bloqueio às vezes vale só pro cliente padrão;
  2. youtube-transcript-api — só a legenda, por outro caminho (pip install youtube-transcript-api);
  3. um NAVEGADOR de verdade (o Chromium do Playwright que o site já usa): abre o vídeo
     como uma pessoa, liga a legenda e lê o que o próprio player baixou — ou o painel
     "Mostrar transcrição";
  4. pytubefix — baixa o áudio (pro Whisper) ou o vídeo por outra biblioteca
     (pip install pytubefix).
Tudo opcional: o que não estiver instalado é pulado com um aviso no log.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

CLIENTES = [["tv_simply"], ["tv"], ["web_safari"], ["mweb"], ["android"], ["ios"]]


def video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", url or "")
    if m:
        return m.group(1)
    return url if re.fullmatch(r"[A-Za-z0-9_-]{11}", url or "") else None


def _linhas_xml(texto: str) -> List[Dict[str, Any]]:
    """srv1/srv3 (<text start dur> ou <p t d>) -> linhas."""
    out = []
    for m in re.finditer(r'<text start="([\d.]+)"(?: dur="([\d.]+)")?[^>]*>(.*?)</text>', texto, re.S):
        ini, dur = float(m.group(1)), float(m.group(2) or 2)
        t = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if t:
            out.append({"inicio": ini, "fim": ini + dur, "texto": t})
    if out:
        return out
    for m in re.finditer(r'<p t="(\d+)"(?: d="(\d+)")?[^>]*>(.*?)</p>', texto, re.S):
        ini, dur = int(m.group(1)) / 1000, int(m.group(2) or 2000) / 1000
        t = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        if t:
            out.append({"inicio": ini, "fim": ini + dur, "texto": t})
    return out


def linhas_de_texto(bruto: str) -> List[Dict[str, Any]]:
    """Legenda em json3, vtt ou xml -> [{"inicio", "fim", "texto"}]."""
    import roteiros_yt
    bruto = (bruto or "").strip()
    if not bruto:
        return []
    if bruto.startswith("{"):
        try:
            return roteiros_yt._de_json3(json.loads(bruto))
        except ValueError:
            return []
    if "WEBVTT" in bruto[:20] or "-->" in bruto:
        return roteiros_yt._de_vtt(bruto)
    return _linhas_xml(bruto)


def _escolher(trilhas: List[Dict[str, Any]], preferidos: List[str]) -> Optional[Dict[str, Any]]:
    """Feita à mão no idioma preferido > feita à mão qualquer > automática."""
    def lang(t):
        return (t.get("lang") or "").split("-")[0].lower()
    manuais = [t for t in trilhas if not t.get("auto")]
    autos = [t for t in trilhas if t.get("auto")]
    for grupo in (manuais, autos):
        for p in preferidos:
            for t in grupo:
                if lang(t) == p.split("-")[0].lower():
                    return t
        if grupo:
            return grupo[0]
    return None


def titulo_oembed(url: str) -> Dict[str, Any]:
    """Título e canal pelo oEmbed público do YouTube (não usa o player, raramente é bloqueado)."""
    try:
        import requests
        r = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=15)
        if r.ok:
            d = r.json()
            return {"titulo": d.get("title") or "", "canal": d.get("author_name") or ""}
    except Exception:  # noqa: BLE001
        pass
    return {}


# ------------------------------------------------------------------ 2. youtube-transcript-api
def legenda_transcript_api(url: str, preferidos: List[str]) -> Optional[Dict[str, Any]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        raise RuntimeError("youtube-transcript-api não está instalado (pip install youtube-transcript-api)")
    vid = video_id(url)
    if not vid:
        return None
    api = YouTubeTranscriptApi()
    lista = list(api.list(vid))
    trilhas = [{"lang": t.language_code, "auto": t.is_generated, "obj": t} for t in lista]
    esc = _escolher(trilhas, preferidos)
    if not esc:
        return None
    dados = esc["obj"].fetch()
    linhas = [{"inicio": float(s.start), "fim": float(s.start) + float(s.duration), "texto": s.text.replace("\n", " ").strip()}
              for s in dados if s.text.strip()]
    return {"linhas": linhas, "lang": esc["lang"], "auto": esc["auto"]} if linhas else None


# ------------------------------------------------------------------ 3. navegador de verdade (Playwright)
_JS_INFO = """() => {
  const r = window.ytInitialPlayerResponse || (document.querySelector('#movie_player') && document.querySelector('#movie_player').getPlayerResponse && document.querySelector('#movie_player').getPlayerResponse());
  if (!r) return null;
  const tr = (((r.captions || {}).playerCaptionsTracklistRenderer || {}).captionTracks || []).map(t => ({url: t.baseUrl, lang: t.languageCode, auto: t.kind === 'asr', nome: (t.name || {}).simpleText || ''}));
  const v = r.videoDetails || {};
  return {titulo: v.title || '', canal: v.author || '', duracao: Number(v.lengthSeconds) || null, trilhas: tr, status: (r.playabilityStatus || {}).status || ''};
}"""


def legenda_navegador(url: str, preferidos: List[str], log: Callable[[str], None] = lambda _m: None,
                      headless: bool = True, timeout_s: int = 45) -> Optional[Dict[str, Any]]:
    """Abre o vídeo num Chromium, como uma pessoa, e lê a legenda que o próprio player
    baixa (com os tokens que o YouTube exige). Último caso: o painel "Mostrar transcrição"."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        raise RuntimeError("playwright não está instalado (pip install playwright && playwright install chromium)")
    vid = video_id(url)
    if not vid:
        return None
    capturadas: List[Tuple[str, str]] = []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=headless, args=["--autoplay-policy=no-user-gesture-required", "--mute-audio"])
        try:
            ctx = nav.new_context(locale="pt-BR", viewport={"width": 1280, "height": 800},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
            pg = ctx.new_page()

            def _resp(r):
                if "/api/timedtext" in r.url:
                    try:
                        capturadas.append((r.url, r.text()))
                    except Exception:  # noqa: BLE001
                        pass
            pg.on("response", _resp)
            pg.goto(f"https://www.youtube.com/watch?v={vid}", timeout=timeout_s * 1000, wait_until="domcontentloaded")
            for rot in ("Aceitar tudo", "Accept all", "Rejeitar tudo", "Reject all"):  # aviso de cookies (Europa)
                try:
                    pg.get_by_role("button", name=rot).first.click(timeout=1500)
                    break
                except Exception:  # noqa: BLE001
                    pass
            info = None
            for _ in range(20):
                info = pg.evaluate(_JS_INFO)
                if info:
                    break
                pg.wait_for_timeout(500)
            if not info:
                raise RuntimeError("a página do vídeo não carregou o player (o YouTube pode ter pedido login também no navegador)")
            base = {"titulo": info["titulo"], "canal": info["canal"], "duracao": info["duracao"]}
            if not info["trilhas"]:
                return dict(base, linhas=[], lang=None, auto=None)
            esc = _escolher(info["trilhas"], preferidos)
            log(f"  navegador: legenda {'automática' if esc['auto'] else 'do vídeo'} em “{esc['lang']}”")
            # a) pede o arquivo direto, de dentro da página (mesmos cookies/tokens)
            bruto = pg.evaluate("async (u) => { try { const r = await fetch(u); return await r.text(); } catch (e) { return ''; } }",
                                esc["url"] + "&fmt=json3")
            linhas = linhas_de_texto(bruto)
            if not linhas:
                # b) liga a legenda no player e pega o que ELE baixou (já vem com o token "pot")
                try:
                    pg.evaluate("() => { const v = document.querySelector('video'); if (v) { v.muted = true; v.play(); } }")
                    pg.wait_for_timeout(1500)
                    pg.evaluate("(l) => { const m = document.querySelector('#movie_player'); if (m && m.setOption) { m.loadModule && m.loadModule('captions'); m.setOption('captions', 'track', {languageCode: l}); } }", esc["lang"])
                    btn = pg.locator(".ytp-subtitles-button")
                    if btn.count() and btn.first.get_attribute("aria-pressed") != "true":
                        btn.first.click(timeout=3000)
                except Exception:  # noqa: BLE001
                    pass
                for _ in range(20):
                    if capturadas:
                        break
                    pg.wait_for_timeout(500)
                for _u, corpo in capturadas:
                    linhas = linhas_de_texto(corpo)
                    if linhas:
                        break
            if not linhas:
                # c) painel "Mostrar transcrição"
                linhas = _painel_transcricao(pg)
            return dict(base, linhas=linhas, lang=esc["lang"], auto=esc["auto"])
        finally:
            nav.close()


def _painel_transcricao(pg) -> List[Dict[str, Any]]:
    try:
        pg.evaluate("() => { const b = document.querySelector('tp-yt-paper-button#expand, #description-inline-expander #expand'); if (b) b.click(); }")
        pg.wait_for_timeout(800)
        for seletor in ("ytd-video-description-transcript-section-renderer button", "button[aria-label*='ranscri']"):
            loc = pg.locator(seletor)
            if loc.count():
                loc.first.click(timeout=3000)
                break
        pg.wait_for_selector("ytd-transcript-segment-renderer", timeout=10000)
        segs = pg.evaluate("""() => [...document.querySelectorAll('ytd-transcript-segment-renderer')].map(e => [
            (e.querySelector('.segment-timestamp') || {}).textContent || '', (e.querySelector('.segment-text') || {}).textContent || ''])""")
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ts, tx in segs:
        partes = [int(x) for x in re.findall(r"\d+", ts)]
        if not partes or not tx.strip():
            continue
        seg = 0
        for x in partes:
            seg = seg * 60 + x
        out.append({"inicio": float(seg), "fim": float(seg) + 3.0, "texto": " ".join(tx.split())})
    for k in range(len(out) - 1):
        out[k]["fim"] = max(out[k]["inicio"] + 0.5, out[k + 1]["inicio"])
    return out


# ------------------------------------------------------------------ 4. pytubefix (áudio / vídeo)
_CLIENTES_PYTUBE = ["WEB", "MWEB", "TV", "ANDROID_VR", "IOS"]


def _pytube(url: str, log: Callable[[str], None]):
    try:
        from pytubefix import YouTube  # type: ignore
    except ImportError:
        raise RuntimeError("pytubefix não está instalado (pip install pytubefix)")
    erros = []
    for cli in _CLIENTES_PYTUBE:
        try:
            yt = YouTube(url, client=cli)
            yt.streams  # força a leitura (é aqui que o YouTube bloqueia)
            return yt
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{cli}: {str(exc)[:120]}")
    raise RuntimeError("pytubefix também foi bloqueado — " + " ; ".join(erros))


def audio_pytubefix(url: str, pasta: str, log: Callable[[str], None] = lambda _m: None) -> Tuple[str, Dict[str, Any]]:
    yt = _pytube(url, log)
    st = yt.streams.get_audio_only() or yt.streams.filter(only_audio=True).order_by("abr").desc().first()
    if not st:
        raise RuntimeError("o vídeo não tem faixa de áudio pra baixar")
    os.makedirs(pasta, exist_ok=True)
    caminho = st.download(output_path=pasta, filename="audio_pytube." + (st.subtype or "m4a"))
    return caminho, {"titulo": yt.title or "", "canal": getattr(yt, "author", "") or "", "duracao": yt.length, "id": yt.video_id}


def video_pytubefix(url: str, pasta: str, altura_alvo: Optional[int] = 1080,
                    log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Melhor vídeo até `altura_alvo` + melhor áudio, juntos num .mp4 (ffmpeg)."""
    yt = _pytube(url, log)
    os.makedirs(pasta, exist_ok=True)

    def _alt(s):
        try:
            return int(str(s.resolution or "0p").rstrip("p"))
        except ValueError:
            return 0
    videos = [s for s in yt.streams.filter(adaptive=True, only_video=True) if _alt(s)]
    videos.sort(key=lambda s: (_alt(s) <= (altura_alvo or 99999), _alt(s) if _alt(s) <= (altura_alvo or 99999) else -_alt(s),
                               (s.subtype == "mp4"), s.fps or 0), reverse=True)
    destino = os.path.join(pasta, f"{yt.video_id}.mp4")
    if videos and shutil.which("ffmpeg"):
        v = videos[0]
        a = yt.streams.get_audio_only()
        pv = v.download(output_path=pasta, filename=f"{yt.video_id}_v.{v.subtype}")
        pa = a.download(output_path=pasta, filename=f"{yt.video_id}_a.{a.subtype}") if a else None
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", pv] + (["-i", pa] if pa else []) + [
            "-map", "0:v:0"] + (["-map", "1:a:0"] if pa else []) + ["-c:v", "copy" if v.subtype == "mp4" else "libx264", "-c:a", "aac", destino]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        for f in (pv, pa):
            try:
                if f:
                    os.remove(f)
            except OSError:
                pass
        if r.returncode != 0:
            raise RuntimeError("ffmpeg não juntou vídeo+áudio do pytubefix: " + r.stderr[-300:])
        altura = _alt(v)
    else:
        prog = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
        if not prog:
            raise RuntimeError("pytubefix não achou um formato de vídeo pra baixar")
        destino = prog.download(output_path=pasta, filename=f"{yt.video_id}.mp4")
        altura = _alt(prog)
    return {"caminho": destino, "titulo": yt.title or url, "duracao_segundos": yt.length, "id": yt.video_id, "altura": altura}
