"""
Outros jeitos de pegar a legenda / o áudio / o vídeo do YouTube quando o yt-dlp
leva "Sign in to confirm you're not a bot" (e os cookies não resolvem).

Na ordem em que o site tenta:
  1. yt-dlp com outros "clientes" do YouTube (tv, web_safari, mweb, android…) —
     o bloqueio às vezes vale só pro cliente padrão;
  2. youtube-transcript-api — só a legenda, por outro caminho (pip install youtube-transcript-api);
  3. um NAVEGADOR de verdade (o Chromium do Playwright que o site já usa): abre o vídeo
     como uma pessoa, liga a legenda e lê o que o próprio player baixou — ou o painel
     "Mostrar transcrição" (o jeito do projeto transcript-youtube-video, que o site
     tenta PRIMEIRO desde a v84_52: `legenda_painel`);
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


# ------------------------------------------------------------------ painel "Mostrar transcrição"
# Do projeto transcript-youtube-video (github.com/flameastro/transcript-youtube-video), que funciona:
# abre o vídeo, clica em "…mais" na descrição e em "Mostrar transcrição" e lê o painel. O YouTube
# trocou o painel: os trechos agora são <transcript-segment-view-model> (o tempo num <div>, o texto
# num <span>) dentro de <macro-markers-panel-item-view-model>; o antigo era <ytd-transcript-segment-renderer>.
_JS_PAINEL = """() => {
  const out = [];
  document.querySelectorAll('transcript-segment-view-model').forEach(e => {
    const div = e.querySelector(':scope > div') || e.querySelector('div');
    const sp = e.querySelector('span');
    out.push([div ? div.innerText : '', sp ? sp.innerText : '']);
  });
  if (!out.length) document.querySelectorAll('ytd-transcript-segment-renderer').forEach(e => out.push([
    (e.querySelector('.segment-timestamp') || {}).textContent || '', (e.querySelector('.segment-text') || {}).textContent || '']));
  return out;
}"""
_SELETOR_TRECHOS = "transcript-segment-view-model, ytd-transcript-segment-renderer"
_BOTOES_TRANSCRICAO = (
    "ytd-video-description-transcript-section-renderer #primary-button button",  # o do transcript-youtube-video
    "#primary-button ytd-button-renderer yt-button-shape button",
    "ytd-video-description-transcript-section-renderer button",
    "button[aria-label*='ranscri']",
)


def _segundos(ts: str) -> Optional[float]:
    partes = [int(x) for x in re.findall(r"\d+", ts or "")]
    if not partes:
        return None
    seg = 0
    for x in partes[-3:]:
        seg = seg * 60 + x
    return float(seg)


def linhas_do_painel(segs: List[Any]) -> List[Dict[str, Any]]:
    """[[tempo, texto], …] do painel -> [{"inicio", "fim", "texto"}] (o fim = começo da próxima)."""
    out = []
    for ts, tx in segs or []:
        ini = _segundos(ts)
        tx = " ".join(str(tx or "").split())
        if ini is None or not tx:
            continue  # cabeçalho de capítulo, linha vazia
        out.append({"inicio": ini, "fim": ini + 3.0, "texto": tx})
    out.sort(key=lambda l: l["inicio"])
    for k in range(len(out) - 1):
        out[k]["fim"] = max(out[k]["inicio"] + 0.5, out[k + 1]["inicio"])
    return out


def _painel_transcricao(pg, timeout_ms: int = 15000) -> List[Dict[str, Any]]:
    """Na página do vídeo já aberta: "…mais" → "Mostrar transcrição" → lê o painel."""
    try:
        if not pg.locator(_SELETOR_TRECHOS).count():
            for sel in ("#description-inline-expander #expand", "tp-yt-paper-button#expand", "#expand"):
                try:
                    loc = pg.locator(sel)
                    if loc.count():
                        loc.first.click(timeout=3000)
                        break
                except Exception:  # noqa: BLE001
                    continue
            pg.wait_for_timeout(800)
            for sel in _BOTOES_TRANSCRICAO:
                try:
                    loc = pg.locator(sel)
                    if loc.count():
                        loc.first.scroll_into_view_if_needed(timeout=2000)
                        loc.first.click(timeout=3000)
                        break
                except Exception:  # noqa: BLE001
                    continue
        pg.wait_for_selector(_SELETOR_TRECHOS, timeout=timeout_ms)
        pg.wait_for_timeout(1500)  # o painel termina de encher
        anterior = -1
        for _ in range(40):  # painel comprido: rola até parar de aparecer trecho novo
            n = pg.locator(_SELETOR_TRECHOS).count()
            if n == anterior:
                break
            anterior = n
            pg.evaluate("() => { const l = document.querySelectorAll('transcript-segment-view-model, ytd-transcript-segment-renderer'); if (l.length) l[l.length - 1].scrollIntoView(); }")
            pg.wait_for_timeout(400)
        return linhas_do_painel(pg.evaluate(_JS_PAINEL))
    except Exception:  # noqa: BLE001
        return []


def legenda_painel(url: str, log: Callable[[str], None] = lambda _m: None, headless: bool = True,
                   timeout_s: int = 60) -> Optional[Dict[str, Any]]:
    """O jeito do transcript-youtube-video: abre o vídeo num Chromium, como uma pessoa, e lê o
    painel "Mostrar transcrição" (a legenda que o YouTube mostra, automática ou do vídeo)."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        raise RuntimeError("playwright não está instalado (pip install playwright && playwright install chromium)")
    vid = video_id(url)
    if not vid:
        return None
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=headless, args=["--mute-audio", "--disable-blink-features=AutomationControlled"])
        try:
            ctx = nav.new_context(locale="pt-BR", viewport={"width": 1366, "height": 900},
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
            pg = ctx.new_page()
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
            base = {"titulo": (info or {}).get("titulo") or "", "canal": (info or {}).get("canal") or "", "duracao": (info or {}).get("duracao")}
            pg.wait_for_timeout(1500)
            linhas = _painel_transcricao(pg)
            if not linhas:
                pg.wait_for_timeout(2500)  # 2ª tentativa (o transcript-youtube-video também pede "tente de novo")
                linhas = _painel_transcricao(pg)
            trilhas = (info or {}).get("trilhas") or []
            auto = all(t.get("auto") for t in trilhas) if trilhas else None
            lang = (trilhas[0].get("lang") if len(trilhas) == 1 else None) if trilhas else None
            if linhas:
                log(f"  painel de transcrição: {len(linhas)} trechos")
            return dict(base, linhas=linhas, lang=lang, auto=auto, tem_legenda=bool(trilhas) if info else None)
        finally:
            nav.close()


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
