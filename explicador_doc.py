"""
explicador_doc.py — 🎞 o modo DOCUMENTÁRIO do Explicador animado (v84_281)
==========================================================================

Cenas com material de arquivo e linguagem de documentário:
  • foto     — Ken Burns (zoom/pan lento) com fundo desfocado quando a foto não é 16:9, P&B opcional, rótulo de data/local;
  • video    — trecho de um vídeo seu (arquivo antigo, 360p…): recorte automático das bordas pretas, limpeza (denoise),
               ampliação com nitidez, zoom no que importa, câmera lenta; vários cortes por cena; selo "ARCHIVAL FOOTAGE";
  • capitulo — cartão de capítulo (CHAPTER ONE · THE KID FROM MANHATTAN) sobre uma foto escurecida;
  • citacao  — citação real em serifa com o autor;
  • linha_tempo — os anos acendendo numa linha.
Estilo "documentario" (opção): serifas, grão de filme, cor quente, sem tremida/cortina, trilha lenta e efeitos de cinema.

Os vídeos viram quadros JPG (30 fps) num cache por trecho; a página troca a imagem quadro a quadro (determinístico,
igual na prévia e no MP4).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

FPS = 30
VERSAO_QUADROS = "v2"  # muda quando o tratamento dos quadros muda (refaz o cache)
GRADE = "colorchannelmixer=rr=0.96:rg=0.06:rb=0:gr=0.03:gg=0.93:gb=0.03:br=0.02:bg=0.06:bb=0.86"


def pasta_midia(pid_dir: str) -> str:
    return os.path.join(pid_dir, "midia")


def pasta_cache(pid_dir: str) -> str:
    return os.path.join(pid_dir, "cache")


# ------------------------------------------------------------------ informações da mídia (com cache)
def info_midia(cam: str) -> Dict[str, Any]:
    """{tipo, w, h, dur, crop:[x,y,w,h]} — o crop tira as bordas pretas (vídeo antigo dentro de tela 16:9 ou vertical)."""
    st = os.stat(cam)
    cache = cam + ".info.json"
    try:
        with open(cache, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("_m") == st.st_mtime and d.get("_s") == st.st_size:
            return d
    except (OSError, ValueError):
        pass
    ext = os.path.splitext(cam)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        from PIL import Image
        with Image.open(cam) as im:
            w, h = im.size
        d = {"tipo": "foto", "w": w, "h": h, "dur": 0, "crop": [0, 0, w, h]}
    else:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                            "-of", "json", cam], capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or "{}")
        s = (j.get("streams") or [{}])[0]
        w, h = int(s.get("width") or 0), int(s.get("height") or 0)
        dur = float((j.get("format") or {}).get("duration") or 0)
        crop = [0, 0, w, h]
        votos: Dict[Tuple[int, int, int, int], int] = {}
        for k in range(5):  # cropdetect em 5 pontos do vídeo
            t0 = dur * (k + 0.5) / 5
            rr = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{t0:.2f}", "-i", cam, "-t", "2", "-vf", "cropdetect=24:2:0", "-an", "-f", "null", "-"],
                                capture_output=True, text=True, timeout=120)
            for m in re.finditer(r"crop=(\d+):(\d+):(\d+):(\d+)", rr.stderr):
                c = tuple(int(x) for x in m.groups())
                votos[(c[2], c[3], c[0], c[1])] = votos.get((c[2], c[3], c[0], c[1]), 0) + 1
        if votos:
            x, y, cw, ch = max(votos, key=lambda c: (votos[c], c[2] * c[3]))
            if cw >= w * 0.3 and ch >= h * 0.3:
                crop = [x, y, cw, ch]
        d = {"tipo": "video", "w": w, "h": h, "dur": dur, "crop": crop}
    d.update(_m=st.st_mtime, _s=st.st_size)
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass
    return d


# ------------------------------------------------------------------ os quadros dos trechos de vídeo
def preparar_clipes(clipes: List[Dict[str, Any]], pid_dir: str, prog: Callable[[str], None] = lambda _m: None) -> None:
    """Extrai, limpa e amplia cada trecho (uma vez — fica no cache)."""
    for k, c in enumerate(clipes):
        d = os.path.join(pasta_cache(pid_dir), c["h"])
        feito = os.path.join(d, "ok")
        if os.path.isfile(feito):
            _fundo_clip(c, d)
            continue
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        prog(f"🎞 preparando o trecho {k + 1}/{len(clipes)} ({os.path.basename(c['fonte'])} em {c['ini']:.1f} s)…")
        x, y, w, h = c["recorte"]
        vel = c["vel"]
        filtros = [f"delogo=x={c['delogo'][0]}:y={c['delogo'][1]}:w={c['delogo'][2]}:h={c['delogo'][3]}"] if c.get("delogo") else []
        filtros += [f"crop={w}:{h}:{x}:{y}", "hqdn3d=1.5:1.5:6:6", f"setpts=PTS/{vel:.4f}", f"fps={FPS}",
                   f"scale={c['ow']}:{c['oh']}:flags=lanczos", "unsharp=5:5:0.7:5:5:0.0", "eq=contrast=1.06:saturation=1.0:gamma=0.98", GRADE]
        if c.get("pb"):
            filtros.append("hue=s=0")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{c['ini']:.3f}", "-t", f"{c['dur_fonte'] + 0.2:.3f}", "-i", c["fonte"],
                            "-vf", ",".join(filtros), "-an", "-q:v", "3", "-frames:v", str(c["n"]), os.path.join(d, "%05d.jpg")],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError("ffmpeg (trecho): " + r.stderr[-300:])
        if not os.path.isfile(os.path.join(d, "00001.jpg")):
            raise RuntimeError(f"o trecho em {c['ini']:.1f} s de {os.path.basename(c['fonte'])} não tem quadros (passou do fim do vídeo?)")
        open(feito, "w").close()
        _fundo_clip(c, d)


def _fundo_clip(c: Dict[str, Any], d: str) -> None:
    """Os quadros pequenos (192x108) do fundo desfocado — desfocar a imagem grande a cada quadro deixava o 4K lento."""
    fb = os.path.join(d, "b")
    if os.path.isfile(os.path.join(fb, "ok")):
        return
    os.makedirs(fb, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-start_number", "1", "-i", os.path.join(d, "%05d.jpg"),
                        "-vf", "scale=192:108:force_original_aspect_ratio=increase,crop=192:108,boxblur=6:2,eq=brightness=-0.16:saturation=0.75", "-q:v", "5",
                        os.path.join(fb, "%05d.jpg")], capture_output=True, text=True, timeout=1800)
    if r.returncode == 0:
        open(os.path.join(fb, "ok"), "w").close()


# ------------------------------------------------------------------ cenas
DOC_CSS = r"""
@font-face{font-family:'DP Garamond';font-weight:400;src:url('__F__/eb-garamond-Regular.ttf')}
@font-face{font-family:'DP Garamond';font-weight:700;src:url('__F__/eb-garamond-Bold.ttf')}
@font-face{font-family:'DP Garamond';font-style:italic;src:url('__F__/eb-garamond-Italic.ttf')}
@font-face{font-family:'DP Cinzel';font-weight:400;src:url('__F__/cinzel-Regular.ttf')}
@font-face{font-family:'DP Cinzel';font-weight:700;src:url('__F__/cinzel-Bold.ttf')}
.kb,.vbox{position:absolute;inset:0;overflow:hidden;background:#000}
.kb img,.vbox img{position:absolute;will-change:transform}
.kb .bg,.vbox .bg{left:-40px;top:-40px;width:2000px;height:1160px;object-fit:cover}
.kb .im{left:50%;top:50%;transform-origin:50% 50%;box-shadow:0 30px 90px #000}
.vbox .im{left:50%;top:50%;box-shadow:0 0 0 2px #ffffff18,0 30px 90px #000}
.kb .im.cheia,.vbox .im.cheia{box-shadow:none}
.lt3{display:flex;align-items:stretch;gap:22px;filter:drop-shadow(0 6px 18px #000c)}
.lt3 i{width:8px;background:var(--ac);border-radius:2px}
.lt3 b{display:block;font-family:'DP Cinzel','DP Garamond',serif;font-weight:700;font-size:46px;letter-spacing:4px;color:#fff;line-height:1.1;white-space:nowrap}
.lt3 span{display:block;font-family:'DP Garamond',serif;font-size:36px;color:#e7dcc3;letter-spacing:1px;white-space:nowrap}
.arq{font-family:'DP Inter',sans-serif;font-weight:700;font-size:24px;letter-spacing:6px;color:#ffffffb0;display:flex;align-items:center;gap:12px}
.arq::before{content:'';width:14px;height:14px;border-radius:50%;background:#ef4444;box-shadow:0 0 12px #ef4444}
.capw{display:flex;flex-direction:column;align-items:center;gap:26px;text-align:center}
.capw small{font-family:'DP Cinzel',serif;font-weight:700;font-size:44px;letter-spacing:18px;color:var(--ac)}
.capw b{font-family:'DP Garamond',serif;font-weight:700;font-size:130px;line-height:1;color:#fff;letter-spacing:2px;text-shadow:0 10px 40px #000}
.capw .ln{height:3px;background:linear-gradient(90deg,transparent,var(--ac),transparent);width:900px}
.capw em{font-family:'DP Garamond',serif;font-style:italic;font-size:46px;color:#e7dcc3}
.quote{width:1500px;text-align:center;font-family:'DP Garamond',serif}
.quote .qm{font-size:260px;line-height:.6;color:var(--ac);opacity:.9}
.quote p{font-style:italic;font-size:84px;line-height:1.15;color:#fff;text-shadow:0 8px 30px #000}
.quote cite{display:block;margin-top:40px;font-family:'DP Cinzel',serif;font-style:normal;font-weight:700;font-size:40px;letter-spacing:8px;color:var(--ac)}
.tl{position:absolute;left:160px;right:160px;top:600px;height:4px;background:#ffffff26}
.tl .fill{position:absolute;left:0;top:0;bottom:0;background:var(--ac);box-shadow:0 0 14px var(--ac)}
.tlp{position:absolute;top:-14px;width:32px;height:32px;margin-left:-16px;border-radius:50%;background:#1a1a1a;border:4px solid #ffffff55}
.tlp.on{background:var(--ac);border-color:var(--ac);box-shadow:0 0 30px var(--ac)}
.tlp b{position:absolute;bottom:52px;left:50%;transform:translateX(-50%);font-family:'DP Garamond',serif;font-weight:700;font-size:64px;color:#ffffff66;white-space:nowrap}
.tlp span{position:absolute;top:56px;left:50%;transform:translateX(-50%);width:300px;text-align:center;font-family:'DP Inter',sans-serif;font-weight:700;font-size:26px;letter-spacing:2px;color:#ffffff55;line-height:1.2}
.tlp.on b{color:var(--ac)}.tlp.on span{color:#fff}
#grao{position:absolute;inset:-80px;z-index:55;pointer-events:none;opacity:0;background-size:256px 256px}
body.doc #grao{display:none}
body.doc #vig{background:radial-gradient(ellipse at center,transparent 45%,#000c 100%)}

body.doc .h{font-family:'DP Garamond','DP Poppins',serif;font-weight:700;letter-spacing:1px}
body.doc .tag{font-family:'DP Cinzel','DP Poppins',serif;letter-spacing:3px;border-radius:6px}
body.doc .chap{font-family:'DP Cinzel','DP Poppins',serif;letter-spacing:6px;border-radius:4px}
body.doc .callout{font-family:'DP Garamond',serif;font-size:44px;border-radius:6px}
body.doc .caso{border-radius:8px}body.doc .caso b,body.doc .caso span{font-family:'DP Cinzel',serif;letter-spacing:3px}
"""

GRAO_JS = r"""
(function(){const c=document.createElement('canvas');c.width=c.height=256;const x=c.getContext('2d'),d=x.createImageData(256,256);
let s=7;for(let i=0;i<d.data.length;i+=4){s=(s*16807)%2147483647;const v=(s%255);d.data[i]=d.data[i+1]=d.data[i+2]=v;d.data[i+3]=255}
x.putImageData(d,0,0);const g=document.getElementById('grao');if(g)g.style.backgroundImage=`url(${c.toDataURL()})`;})();
"""


def _e(s: Any) -> str:
    import html
    return html.escape(str(s if s is not None else ""), quote=True)


def foto_tratada(cam: str, pid_dir: str, pb: bool) -> Tuple[str, str]:
    """A foto com a cor do documentário (ou P&B) + o fundo pequeno e desfocado — caminhos relativos pra página."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    st = os.stat(cam)
    h = hashlib.sha1(json.dumps([VERSAO_QUADROS, os.path.basename(cam), st.st_size, st.st_mtime, pb]).encode()).hexdigest()[:14]
    d = os.path.join(pasta_cache(pid_dir), "fotos")
    os.makedirs(d, exist_ok=True)
    im_p, bg_p = os.path.join(d, h + ".jpg"), os.path.join(d, h + "_b.jpg")
    if not (os.path.isfile(im_p) and os.path.isfile(bg_p)):
        with Image.open(cam) as im0:
            im = ImageOps.exif_transpose(im0).convert("RGB")
        if max(im.size) > 2400:
            im.thumbnail((2400, 2400), Image.LANCZOS)
        elif max(im.size) < 1400:  # foto pequena: amplia com suavidade (o navegador ampliaria pior)
            k = 1400 / max(im.size)
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS).filter(ImageFilter.UnsharpMask(2, 60, 2))
        if pb:
            im = ImageEnhance.Contrast(ImageOps.grayscale(im).convert("RGB")).enhance(1.08)
        else:
            r, g, b_ = im.split()
            im = Image.merge("RGB", (r, g.point(lambda v: round(v * 0.97)), b_.point(lambda v: round(v * 0.88))))  # cor quente
            im = ImageEnhance.Contrast(im).enhance(1.04)
        im.save(im_p, quality=92)
        bg = im.copy()
        bg.thumbnail((192, 192))
        bg = bg.filter(ImageFilter.GaussianBlur(6))
        bg = ImageEnhance.Brightness(bg).enhance(0.42)
        bg.save(bg_p, quality=85)
    return "../cache/fotos/" + h + ".jpg", "../cache/fotos/" + h + "_b.jpg"


def _kb_html(src: str, info: Dict[str, Any], efeito: str, foco: List[float], a: float, b: float, pb: bool, src_bg: str = "") -> str:
    w, h = max(1, info["w"]), max(1, info["h"])
    ar = w / h
    cheia = ar >= 1.55
    if cheia:
        sw, sh = (1920, 1920 / ar) if ar < 16 / 9 else (1080 * ar, 1080)
        sw, sh = max(1920, sw), max(1080, sh)
    else:
        sh = 1000
        sw = sh * ar
    cfg = {"a": a, "b": b, "ef": efeito or "zoom_in", "fx": float(foco[0]), "fy": float(foco[1]), "w": sw, "h": sh}
    bg = "" if cheia else f'<img class="bg" src="{_e(src_bg or src)}">'
    return (f'<div class="kb" data-kb="{_e(json.dumps(cfg))}">{bg}<img class="im{" cheia" if cheia else ""}" '
            f'src="{_e(src)}" style="width:{sw:.0f}px;height:{sh:.0f}px;margin-left:{-sw / 2:.0f}px;margin-top:{-sh / 2:.0f}px"></div>')


# 🎞 v84_291: no estilo DINÂMICO as cenas de foto/vídeo/capítulo/citação usam a letra do dinâmico (sem serifa) e cantos redondos
DIN_CSS = """
body:not(.doc) .lt3 b{font-family:'DP Poppins','DP Inter',sans-serif;font-weight:800;letter-spacing:2px;text-transform:uppercase}
body:not(.doc) .lt3 span{font-family:'DP Inter','DP Poppins',sans-serif;font-weight:600;color:#ffffffd0}
body:not(.doc) .capw small{font-family:'DP Poppins',sans-serif;font-weight:800;letter-spacing:10px}
body:not(.doc) .capw b{font-family:'DP Poppins',sans-serif;font-weight:900;letter-spacing:0;text-transform:uppercase}
body:not(.doc) .capw em{font-family:'DP Inter',sans-serif;font-style:normal;font-weight:600}
body:not(.doc) .quote{font-family:'DP Poppins',sans-serif}
body:not(.doc) .quote p{font-style:normal;font-weight:800}
body:not(.doc) .quote cite{font-family:'DP Poppins',sans-serif}
body:not(.doc) .tlp b{font-family:'DP Poppins',sans-serif;font-weight:900}
body:not(.doc) .vbox .im:not(.cheia){border-radius:18px}
"""


def instalar(Construtor: Any, X: Any) -> None:
    """Liga os tipos de cena de documentário no Construtor do explicador."""

    def _midia(self, nome: Any) -> Optional[Tuple[str, Dict[str, Any]]]:
        nome = os.path.basename(str(nome or ""))
        cam = os.path.join(pasta_midia(self.pid_dir), nome)
        if not nome or not os.path.isfile(cam):
            self.avisos.append(f"mídia não encontrada: “{nome}” (suba em 📁 Fotos e vídeos)")
            return None
        return cam, info_midia(cam)

    def _rotulo(self, r: Any, a: float, b: float) -> str:
        if not r:
            return ""
        r = r if isinstance(r, dict) else {"texto": str(r)}
        partes = [x.strip() for x in str(r.get("texto") or "").split("·", 1)]
        t0 = self.t(r.get("em"), a, a + 0.7, "rótulo")
        t1 = self.t(r.get("ate"), t0, -1) if r.get("ate") else None
        t1 = t1 if t1 and t1 > t0 else min(b - 0.4, t0 + float(r.get("dur") or 5.5))
        html = (f'<div class="lt3"><i></i><div><b>{_e(partes[0])}</b>' + (f'<span>{_e(partes[1])}</span>' if len(partes) > 1 else "") + "</div></div>")
        return self.E(t0, html, "left", b=t1, x=90, y=860, snd=None)

    def c_foto(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        fotos = c.get("fotos") if isinstance(c.get("fotos"), list) else [c]
        itens, prev = [], a
        for i, f in enumerate([x for x in fotos if isinstance(x, dict)]):
            m = self._midia(f.get("arquivo"))
            if not m:
                continue
            t0 = a if i == 0 else self.t(f.get("em"), prev, prev + 3, "foto")
            prev = t0
            itens.append((t0, f, m))
        body = ""
        for i, (t0, f, (cam, info)) in enumerate(itens):
            t1 = itens[i + 1][0] + 0.6 if i + 1 < len(itens) else b
            ef = f.get("efeito") or ["zoom_in", "pan_dir", "zoom_out", "pan_esq"][(k + i) % 4]
            pbf = bool(f.get("pb") or c.get("pb"))
            src, sbg = foto_tratada(cam, self.pid_dir, pbf)
            body += self.E(t0, _kb_html(src, info, ef, f.get("foco") or [0.5, 0.42], t0, t1, pbf, sbg),
                           "fade", b=t1, x=0, y=0, style="width:1920px;height:1080px", snd=None)
            if f.get("rotulo"):
                body += self._rotulo(f["rotulo"], t0, t1)
        if c.get("rotulo") and len(fotos) > 1:
            body += self._rotulo(c["rotulo"], a, b)
        body += self.linhas(c.get("linhas") or [], a, b, 120, 760)
        self.cena(a, b, body)

    def c_video(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        cortes = c.get("cortes") if isinstance(c.get("cortes"), list) else [c]
        if c.get("trecho"):
            ins = self.trecho(c["trecho"])
            if ins:
                cortes = [dict(cortes[0], arquivo=ins["arquivo"], ini=ins["ini"] + float(cortes[0].get("desloc") or 0))] + list(cortes[1:])
        itens, prev = [], a
        for i, cc in enumerate([x for x in cortes if isinstance(x, dict)]):
            m = self._midia(cc.get("arquivo") or c.get("arquivo"))
            if not m:
                continue
            t0 = a if i == 0 else self.t(cc.get("em"), prev, prev + 3, "corte")
            prev = t0
            itens.append((t0, cc, m))
        body = ""
        padrao_fontes = ((self.p.get("plano") or {}).get("fontes") or {})
        for i, (t0, cc, (cam, info)) in enumerate(itens):
            cc = dict(padrao_fontes.get(os.path.basename(cam)) or {}, **{k: v for k, v in c.items() if k in ("zoom", "foco", "enquadrar", "pb", "velocidade", "delogo")}, **cc)
            t1 = itens[i + 1][0] + 0.35 if i + 1 < len(itens) else b
            vel = max(0.25, min(2.0, float(cc.get("velocidade") or c.get("velocidade") or 1.0)))
            dur_v = t1 - t0 + 0.2
            ini = float(cc.get("ini") or 0)
            x, y, w, h = info["crop"]
            z = cc.get("zoom") or c.get("zoom")
            fx, fy = (cc.get("foco") or c.get("foco") or [0.5, 0.5])[:2]
            if z and float(z) > 1:  # recorta já na preparação (fica mais nítido que ampliar na tela)
                z = float(z)
                nw, nh = int(w / z) // 2 * 2, int(h / z) // 2 * 2
                x = int(x + max(0, min(w - nw, fx * w - nw / 2)))
                y = int(y + max(0, min(h - nh, fy * h - nh / 2)))
                w, h = nw, nh
            enq = cc.get("enquadrar") or c.get("enquadrar") or "moldura"
            if enq == "cheia":  # corta pra 16:9
                if w / h < 16 / 9:
                    nh = int(w * 9 / 16) // 2 * 2
                    y = int(y + max(0, min(h - nh, fy * h - nh / 2)))
                    h = nh
                ow, oh = 1920, 1080
            else:
                oh = 1080
                ow = int(round(oh * w / h / 2) * 2)
                if ow > 1920:
                    ow, oh = 1920, int(round(1920 * h / w / 2) * 2)
            n = int(math.ceil(dur_v * FPS)) + 2
            fonte_dur = dur_v * vel
            if info.get("dur") and ini + fonte_dur > info["dur"]:
                fonte_dur = max(0.5, info["dur"] - ini - 0.05)
            pb = bool(cc.get("pb") or c.get("pb"))
            dl = cc.get("delogo") if isinstance(cc.get("delogo"), list) and len(cc["delogo"]) == 4 else None
            chave = json.dumps([VERSAO_QUADROS, os.path.basename(cam), os.path.getsize(cam), round(ini, 3), round(vel, 3), [x, y, w, h], ow, oh, n, pb, dl])
            hh = hashlib.sha1(chave.encode()).hexdigest()[:14]
            self.clipes.append({"h": hh, "fonte": cam, "ini": ini, "vel": vel, "recorte": [x, y, w, h], "ow": ow, "oh": oh, "n": n,
                                "dur_fonte": fonte_dur, "pb": pb, "delogo": dl})
            cfg = {"t0": t0, "vel": 1, "n": n, "dir": f"../cache/{hh}/", "a": t0, "b": t1, "push": float(cc.get("aproximar", c.get("aproximar", 0.06)))}
            cheia = enq == "cheia"
            bg = "" if cheia else '<img class="bg vf2">'
            body += self.E(t0, f'<div class="vbox" data-v="{_e(json.dumps(cfg))}">{bg}<img class="im vf{" cheia" if cheia else ""}" '
                               f'style="width:{ow}px;height:{oh}px;margin-left:{-ow / 2}px;margin-top:{-oh / 2}px"></div>',
                           "fade", b=t1, x=0, y=0, style="width:1920px;height:1080px", snd=None)
            if cc.get("rotulo"):
                body += self._rotulo(cc["rotulo"], t0, t1)
        selo = c.get("selo", "ARCHIVAL FOOTAGE")
        if selo:
            body += self.E(a + 0.4, f'<div class="arq">{_e(selo)}</div>', "fade", x=70, y=60, snd=None)
        if c.get("rotulo"):
            body += self._rotulo(c["rotulo"], a, b)
        body += self.linhas(c.get("linhas") or [], a, b, 120, 760)
        pv = a
        for dsq in [x for x in c.get("destaques") or [] if isinstance(x, dict)]:
            t0 = self.t(dsq.get("em"), pv, a + 1)
            pv = t0
            t1 = self.t(dsq.get("ate"), t0, -1) if dsq.get("ate") else None
            body += self._destaque(dsq, t0, t1 if t1 and t1 > t0 else None, lambda _n: None, 960)
        self.cena(a, b, body)

    def c_capitulo(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        body = ""
        if c.get("arquivo"):
            m = self._midia(c["arquivo"])
            if m:
                cam, info = m
                src, sbg = foto_tratada(cam, self.pid_dir, bool(c.get("pb", True)))
                body += self.E(a, _kb_html(src, info, c.get("efeito") or "zoom_in", c.get("foco") or [0.5, 0.4],
                                           a, b, bool(c.get("pb", True)), sbg), "fade", x=0, y=0, style="width:1920px;height:1080px;opacity:.5", snd=None)
                body += '<div style="position:absolute;inset:0;background:radial-gradient(ellipse at center,#000a 0%,#000e 75%)"></div>'
        t0 = self.t(c.get("em"), a, a + 0.2)
        num = _e(c.get("numero") or "")
        html = (f'<div class="capw"><small>{num}</small><div class="ln"></div><b>{_e(c.get("titulo") or "")}</b>'
                + (f'<em>{_e(c["sub"])}</em>' if c.get("sub") else "") + "</div>")
        body += self.E(t0, html, "zoom", x=960, y=540, cls="c", snd="capitulo")
        self.cena(a, b, body)

    def c_citacao(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        body = ""
        if c.get("arquivo"):
            m = self._midia(c["arquivo"])
            if m:
                cam, info = m
                src, sbg = foto_tratada(cam, self.pid_dir, True)
                body += self.E(a, _kb_html(src, info, "zoom_in", c.get("foco") or [0.5, 0.4], a, b, True, sbg),
                               "fade", x=0, y=0, style="width:1920px;height:1080px;opacity:.35", snd=None)
        t0 = self.t(c.get("em"), a, a + 0.3)
        body += self.E(t0, f'<div class="quote"><div class="qm">“</div><p>{_e(c.get("texto") or "")}</p><cite>— {_e(c.get("autor") or "")}</cite></div>',
                       "up", x=960, y=540, cls="c", snd="capitulo")
        self.cena(a, b, body)

    def c_linha_tempo(self, c: Dict[str, Any], a: float, b: float, k: int) -> None:
        itens = [x for x in c.get("itens") or [] if isinstance(x, dict)][:9]
        ts, pv = [], a
        for i, it in enumerate(itens):
            ts.append(self.t(it.get("em"), pv, a + 1 + i * 2, "linha do tempo"))
            pv = ts[-1]
        n = len(itens)
        pts = ""
        for i, it in enumerate(itens):
            left = (i / max(1, n - 1)) * 100 if n > 1 else 50
            pts += (f'<div class="tlp" data-on="{ts[i]:.3f},99999" style="left:{left:.2f}%"><b>{_e(it.get("ano") or "")}</b>'
                    f'<span>{_e(it.get("texto") or "")}</span></div>')
            self.snd.append((round(ts[i], 3), "tick"))
        fills = json.dumps([[ts[i], (i / max(1, n - 1)) * 100] for i in range(n)])
        body = self.linhas(c.get("linhas") or ([{"texto": c["titulo"], "estilo": "medio", "cor": "acento"}] if c.get("titulo") else []), a, b, 140, 380)
        body += self.E(a + 0.2, f'<div class="tl" style="position:relative;left:0;top:0;width:1600px"><div class="fill" data-fill="{_e(fills)}"></div>{pts}</div>',
                       "fade", x=160, y=600, snd=None)
        self.cena(a, b, body)

    for nome, fn in (("_midia", _midia), ("_rotulo", _rotulo), ("c_foto", c_foto), ("c_video", c_video), ("c_capitulo", c_capitulo),
                     ("c_citacao", c_citacao), ("c_linha_tempo", c_linha_tempo)):
        setattr(Construtor, nome, fn)


# ------------------------------------------------------------------ trilha de documentário
def musica_doc(n: int, sr: int = 48000) -> Any:
    """Trilha lenta e grave (Am-F-C-E, 66 BPM): pad, baixo longo, piano suave em colcheias espaçadas — sem bateria."""
    import numpy as np
    t = np.arange(n) / sr
    beat = 60 / 66
    bar = 4 * beat

    def nota(m: float) -> float:
        return 440 * 2 ** ((m - 69) / 12)
    prog_ = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [52, 56, 59]]
    ci = ((t // bar).astype(int)) % 4
    pad = np.zeros(n)
    for v in range(3):
        f = np.array([nota(prog_[c][v]) for c in range(4)])[ci]
        ph, ph2 = np.cumsum(2 * np.pi * f / sr), np.cumsum(2 * np.pi * f * 1.003 / sr)
        pad += np.sin(ph) + 0.5 * np.sin(ph2)
    lb = (t % bar) / bar
    mus = 0.045 * pad * np.minimum(1, lb * 3) * (1 - 0.25 * lb)
    fb = np.array([nota(prog_[c][0] - 24) for c in range(4)])[ci]
    mus += 0.10 * np.sin(np.cumsum(2 * np.pi * fb / sr)) * (0.6 + 0.4 * np.exp(-lb * 2))
    e = beat  # piano: uma nota por tempo, arpejo descendo
    arp = np.array([prog_[c][(3 - i) % 3] + 12 for c in range(4) for i in range(4)])
    fa = np.array([nota(x) for x in arp])[ci * 4 + ((t // e).astype(int) % 4)]
    te = t % e
    ph = np.cumsum(2 * np.pi * fa / sr)
    mus += 0.05 * (np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.1 * np.sin(3 * ph)) * np.exp(-te * 2.2)
    return mus.astype("float32")


# ------------------------------------------------------------------ 🎙 narração + trechos com o som original
def _pausa(rms: Any, t: float) -> float:
    """Onde cortar a narração perto de t (s): a pausa mais longa em [t-1,2; t+0,6] — o fim da frase anterior."""
    import numpy as np
    a, b = max(0, int((t - 1.2) * 100)), min(len(rms) - 1, int((t + 0.6) * 100))
    if b <= a:
        return t
    jan = rms[a:b + 1]
    fala = rms[rms > np.percentile(rms, 30)] if len(rms) > 10 else rms
    limiar = max(1e-5, 0.12 * float(np.median(fala)) if len(fala) else 1e-3)
    baixo = jan < limiar
    melhor, ini = None, None
    for k, v in enumerate(list(baixo) + [False]):
        if v and ini is None:
            ini = k
        elif not v and ini is not None:
            dur, centro = k - ini, (ini + k) / 2
            nota = dur - 0.15 * abs(a + centro - t * 100)  # pausa longa e perto
            if dur >= 5 and (melhor is None or nota > melhor[0]):
                melhor = (nota, centro)
            ini = None
    if melhor is None:
        return (a + int(np.argmin(jan))) / 100
    return (a + melhor[1]) / 100

def _ler_audio(cam: str, ini: float = 0.0, dur: float = 0.0, af: str = "", sr: int = 48000) -> Any:
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"]
    if ini:
        cmd += ["-ss", f"{ini:.3f}"]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-i", cam, "-vn"]
    if af:
        cmd += ["-af", af]
    cmd += ["-f", "f32le", "-ac", "2", "-ar", str(sr), "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()


def montar_audio(pid_dir: str, narr: str, segs: List[List[Any]], trechos: List[Dict[str, Any]], tempos_cls: Any,
                 sr: int = 48000) -> Dict[str, Any]:
    """Corta a narração nos pontos certos e encaixa os trechos com o som original (limpo e no mesmo volume da voz).
    trechos: [{"arquivo", "ini", "fim", "antes_de": frase onde a narração volta}] — vários no mesmo ponto entram em fila.
    Devolve {"wav", "segs" (a legenda com os tempos novos), "inseridos": [{"i", "t0", "t1", "arquivo", "ini", "fim"}], "dur"}."""
    import numpy as np
    chave = hashlib.sha1(json.dumps([os.path.getsize(narr), os.path.getmtime(narr), trechos], sort_keys=True).encode()).hexdigest()[:14]
    destino = os.path.join(pid_dir, f"narracao_montada_{chave}.wav")
    meta = destino + ".json"
    if os.path.isfile(destino) and os.path.isfile(meta):
        with open(meta, encoding="utf-8") as f:
            return json.load(f)
    T = tempos_cls(segs)
    nar = _ler_audio(narr, sr=sr)
    # energia em janelas de 10 ms (pra cortar no silêncio entre as palavras)
    hop = sr // 100
    mono = nar[:, 0] if len(nar) else np.zeros(1, np.float32)
    nfr = len(mono) // hop
    rms = np.sqrt((mono[:nfr * hop].reshape(nfr, hop) ** 2).mean(axis=1)) if nfr else np.zeros(1)
    rms = np.convolve(rms, np.ones(12) / 12, "same")
    pontos, frases_t = [], []
    ult = 0.0
    for i, tr in enumerate(trechos):
        frase = tr.get("antes_de")
        t = T.quando(frase, ult) if frase not in (None, "") else None
        if t is None:
            raise RuntimeError(f"trecho {i + 1}: não achei na narração a frase “{frase}”")
        corte = _pausa(rms, t)  # a pausa mais longa perto do começo da frase (fim da frase anterior)
        pontos.append((corte, i))
        frases_t.append((corte, t))
        ult = t
    # a legenda: um trecho que atravessa um corte vira dois, partindo na palavra onde a frase começa
    novos_segs = []
    for a0, b0, tx in segs:
        partes = [(a0, b0, str(tx))]
        for c, tf in sorted(set(frases_t)):
            res = []
            for pa, pb, pt in partes:
                if pa < max(c, tf) - 0.02 and pb > min(c, tf) + 0.02 and pa < tf < pb and " " in pt.strip():
                    pos = len(pt) * (min(max(c, pa), pb) - pa) / max(1e-6, pb - pa)
                    limites = [m.start() + 1 for m in re.finditer(r" ", pt)]
                    pont = [x for x in limites if pt[x - 2] in ".?!,;:\"”"]
                    k = min(pont or limites, key=lambda x: abs(x - pos) + (0 if pont else 0))
                    meio = min(max(c, pa + 0.01), pb - 0.01)
                    res += [(pa, meio, pt[:k].strip()), (meio, pb, pt[k:].strip())]
                else:
                    res.append((pa, pb, pt))
            partes = res
        novos_segs += [list(x) for x in partes if x[2]]
    segs = novos_segs
    pedacos, inseridos, novo_t, pos = [], [], 0.0, 0.0
    deslocs: List[Tuple[float, float]] = []  # (tempo original do corte, quanto foi empurrado depois dele)
    acum = 0.0
    pausa = np.zeros((int(0.35 * sr), 2), np.float32)
    k = 0
    while k < len(pontos):
        corte = pontos[k][0]
        grupo = [pontos[k][1]]
        while k + 1 < len(pontos) and abs(pontos[k + 1][0] - corte) < 0.05:
            k += 1
            grupo.append(pontos[k][1])
        a, b = int(pos * sr), int(corte * sr)
        pedacos.append(nar[a:b])
        novo_t += (b - a) / sr
        add = 0.0
        pedacos.append(pausa)
        novo_t += 0.35
        add += 0.35
        for gi in grupo:
            tr = trechos[gi]
            cam = os.path.join(pasta_midia(pid_dir), os.path.basename(str(tr["arquivo"])))
            ini, fim = float(tr["ini"]), float(tr["fim"])
            if not tr.get("exato"):  # acha a pausa mais próxima do começo e do fim (pra não cortar no meio da palavra)
                folga = 0.7
                bruto = _ler_audio(cam, max(0.0, ini - folga), fim - ini + 2 * folga, "", sr)
                if len(bruto) > sr:
                    mb = bruto[:, 0]
                    nb = len(mb) // hop
                    rb = np.convolve(np.sqrt((mb[:nb * hop].reshape(nb, hop) ** 2).mean(axis=1)), np.ones(8) / 8, "same")
                    o = min(folga, ini)

                    def quieto(c: float, raio: float = 0.5) -> float:
                        a_, b_ = max(0, int((c - raio) * 100)), min(len(rb) - 1, int((c + raio) * 100))
                        if b_ <= a_:
                            return c
                        return (a_ + int(np.argmin(rb[a_:b_ + 1] + 0.002 * np.abs(np.arange(a_, b_ + 1) - c * 100)))) / 100
                    ini2, fim2 = max(0.0, ini - o + quieto(o)), ini - o + quieto(o + fim - ini)
                    if fim2 - ini2 > 1.0:
                        ini, fim = ini2, fim2
            x = _ler_audio(cam, ini, fim - ini, "highpass=f=90,afftdn=nf=-25,loudnorm=I=-17:TP=-2:LRA=7,"
                                                "afade=t=in:d=0.12,areverse,afade=t=in:d=0.25,areverse", sr)
            inseridos.append({"i": gi, "t0": round(novo_t, 3), "t1": round(novo_t + len(x) / sr, 3), "arquivo": tr["arquivo"], "ini": ini, "fim": fim})
            pedacos.append(x)
            novo_t += len(x) / sr
            add += len(x) / sr
            pedacos.append(pausa)
            novo_t += 0.35
            add += 0.35
        acum += add
        deslocs.append((corte, acum))
        pos = corte
        k += 1
    pedacos.append(nar[int(pos * sr):])
    tudo = np.concatenate(pedacos).astype(np.float32)

    def novo(tt: float) -> float:
        d = 0.0
        for c, ac in deslocs:
            if tt >= c:
                d = ac
        return tt + d
    cortes_sorted = sorted({c for c, _ in pontos})

    def ajusta(a: float, b: float) -> float:  # legenda que começa colada no corte e passa dele é da frase que vem depois
        for c in cortes_sorted:
            if c - 0.45 <= a < c and b > c + 0.1:
                return c + 0.002
        return a
    segs = [[ajusta(a, b), b, t] for a, b, t in segs]
    novos = [[round(novo(a + 0.001), 3), round(novo(b - 0.001) if b - 0.001 > a else novo(a), 3), t] for a, b, t in segs]
    raw = destino + ".f32"
    tudo.tofile(raw)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", raw, destino], check=True, timeout=900)
    os.remove(raw)
    res = {"wav": destino, "segs": novos, "inseridos": inseridos, "dur": round(len(tudo) / sr, 3)}
    with open(meta, "w", encoding="utf-8") as f:
        json.dump(res, f)
    for f in os.listdir(pid_dir):  # as montagens antigas
        if f.startswith("narracao_montada_") and chave not in f:
            try:
                os.remove(os.path.join(pid_dir, f))
            except OSError:
                pass
    return res
