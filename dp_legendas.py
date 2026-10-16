"""
Legendas do vídeo (estilo DarkPlanner): a partir do .srt que veio no zip
(ou das palavras do Whisper), com estilos de bloco e de KARAOKÊ:

  Bloco:    Seguir texto, Caixa, Contorno forte, Cinema, Faixa colorida
  Karaokê:  Clássico (a palavra falada muda de cor), Destaque (caixa colorida
            atrás da palavra falada), Pop (a palavra cresce e muda de cor),
            Palavra única (uma palavra por vez, grande), Preenchimento (a cor
            vai enchendo a frase conforme é dita)

O .srt não tem o tempo de cada palavra: dentro de cada bloco as palavras são
distribuídas pelo tamanho delas (palavra comprida = mais tempo).

"Legenda sob templates/destaques" (Automático / Manter / Ocultar):
  * templates — automático: some onde a cena já escreve a fala; ocultar: some
    em toda cena com template; manter: sempre aparece.
  * destaques — automático: some sob destaque que escreve a fala (título,
    frase, citação…) e fica sob SELO/cartão/lower third; ocultar: some sob
    qualquer destaque; manter: sempre aparece.
  * cada cena/destaque pode forçar "manter" ou "ocultar" só nele.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import dp_destaques

ESTILOS = [
    {"id": "seguir", "nome": "Seguir texto", "tipo": "bloco"},
    {"id": "caixa", "nome": "Caixa", "tipo": "bloco"},
    {"id": "contorno", "nome": "Contorno forte", "tipo": "bloco"},
    {"id": "cinema", "nome": "Cinema", "tipo": "bloco"},
    {"id": "faixa", "nome": "Faixa colorida", "tipo": "bloco"},
    {"id": "classico", "nome": "Clássico", "tipo": "karaoke"},
    {"id": "destaque", "nome": "Destaque", "tipo": "karaoke"},
    {"id": "pop", "nome": "Pop", "tipo": "karaoke"},
    {"id": "palavra_unica", "nome": "Palavra única", "tipo": "karaoke"},
    {"id": "preenchimento", "nome": "Preenchimento", "tipo": "karaoke"},
]
_IDS = {e["id"] for e in ESTILOS}
MODOS_SOB = ("auto", "manter", "ocultar")
_FORMAS_SELO = {"selo_canto", "cartao_dado", "terco", "doc", "carimbo", "slab"}


def padrao() -> Dict[str, Any]:
    return {"ativa": False, "estilo": "classico", "posicao": "base", "tamanho": 0.062, "maiusculas": False,
            "max_palavras": 4, "fonte": "DP Inter", "cor_texto": "#FFFFFF", "cor_ativa": None,
            "sob_templates": "auto", "sob_destaques": "auto", "contorno": True}


def normalizar(c: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = padrao()
    if not isinstance(c, dict):
        return out
    out["ativa"] = bool(c.get("ativa"))
    if c.get("estilo") in _IDS:
        out["estilo"] = c["estilo"]
    if c.get("posicao") in ("base", "meio", "topo"):
        out["posicao"] = c["posicao"]
    try:
        out["tamanho"] = max(0.03, min(0.14, float(c.get("tamanho", out["tamanho"]))))
    except (TypeError, ValueError):
        pass
    try:
        out["max_palavras"] = max(1, min(10, int(c.get("max_palavras", out["max_palavras"]))))
    except (TypeError, ValueError):
        pass
    out["maiusculas"] = bool(c.get("maiusculas"))
    out["contorno"] = c.get("contorno", True) is not False
    if c.get("fonte") in set(dp_destaques._FONTE.values()):
        out["fonte"] = c["fonte"]
    for k in ("cor_texto", "cor_ativa"):
        v = str(c.get(k) or "")
        out[k] = v.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else (out[k] if k == "cor_texto" else None)
    for k in ("sob_templates", "sob_destaques"):
        if c.get(k) in MODOS_SOB:
            out[k] = c[k]
    return out


# ------------------------------------------------------------------ palavras
def palavras_dos_blocos(blocos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Blocos do .srt -> palavras com tempo estimado (proporcional ao tamanho)."""
    out = []
    for b in blocos:
        ps = str(b.get("text") or "").split()
        if not ps:
            continue
        ini, fim = float(b["start"]), float(b["end"])
        pesos = [len(p) + 2 for p in ps]
        tot = sum(pesos)
        t = ini
        for p, w in zip(ps, pesos):
            d = (fim - ini) * w / tot
            out.append({"word": p, "start": round(t, 3), "end": round(t + d, 3), "bloco": id(b)})
            t += d
    return out


def janelas_ocultas(cfg: Dict[str, Any], grupos_templates: List[Tuple[float, float, bool, Optional[str]]],
                    destaques: List[Dict[str, Any]]) -> List[Tuple[float, float]]:
    """grupos_templates: [(início, fim, cena_mostra_a_fala, override "manter"/"ocultar"/None)]."""
    j: List[Tuple[float, float]] = []
    for ini, fim, mostra_fala, ov in grupos_templates:
        modo = ov if ov in ("manter", "ocultar") else cfg["sob_templates"]
        if modo == "ocultar" or (modo == "auto" and mostra_fala):
            j.append((ini, fim))
    for d in destaques or []:
        if d.get("avulso"):
            ov = d.get("legenda")
            if ov == "ocultar":
                j.append((float(d["start"]), float(d["end"])))
            continue
        h = dp_destaques.estilo(d.get("estilo")) or {}
        ov = d.get("legenda")
        modo = ov if ov in ("manter", "ocultar") else cfg["sob_destaques"]
        if modo == "ocultar" or (modo == "auto" and h.get("forma") not in _FORMAS_SELO):
            j.append((float(d["start"]), float(d["end"])))
    return j


def filtrar(palavras: List[Dict[str, Any]], janelas: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    def dentro(w):
        m = (float(w["start"]) + float(w.get("end", w["start"]))) / 2
        return any(a <= m < b for a, b in janelas)
    return [w for w in palavras if not dentro(w)]


def agrupar(palavras: List[Dict[str, Any]], max_palavras: int, max_chars: int = 30, pausa: float = 0.6) -> List[List[Dict[str, Any]]]:
    linhas, atual = [], []
    for w in palavras:
        quebra = False
        if atual:
            if len(atual) >= max_palavras or len(" ".join(x["word"] for x in atual + [w])) > max_chars:
                quebra = True
            elif float(w["start"]) - float(atual[-1]["end"]) > pausa or w.get("bloco") != atual[-1].get("bloco"):
                quebra = True
            elif re.search(r"[.!?;:]$", atual[-1]["word"]):
                quebra = True
        if quebra:
            linhas.append(atual)
            atual = []
        atual.append(w)
    if atual:
        linhas.append(atual)
    return linhas


# ------------------------------------------------------------------ medidas (pra caixa atrás da palavra)
@lru_cache(maxsize=1)
def _mapa_fontes() -> Dict[str, Dict[str, str]]:
    with open(os.path.join(dp_destaques.FONTES_DIR, "fontes.json"), encoding="utf-8") as f:
        m = json.load(f)
    return {v["familia"]: v["arquivos"] for v in m.values()}


def _arquivo_fonte(familia: str) -> str:
    arqs = _mapa_fontes().get(familia) or _mapa_fontes()["DP Inter"]
    return os.path.join(dp_destaques.FONTES_DIR, arqs.get("Bold") or arqs.get("Regular") or next(iter(arqs.values())))


def _escala_libass(familia: str) -> float:
    """Quanto 1px de \\fs do libass vale em tamanho de fonte do PIL (medido uma vez por família)."""
    return dp_destaques.escala_libass(familia)


@lru_cache(maxsize=64)
def _fonte_pil(familia: str, fs: int):
    from PIL import ImageFont
    return ImageFont.truetype(_arquivo_fonte(familia), max(4, int(round(fs * _escala_libass(familia)))))


def largura(texto: str, familia: str, fs: int) -> float:
    return _fonte_pil(familia, fs).getlength(texto)


# ------------------------------------------------------------------ ASS
def _c(hex_cor: str, alpha: int = 0) -> str:
    h = hex_cor.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _t(t: float) -> str:
    return dp_destaques._tempo(t)


def gerar_ass(palavras: List[Dict[str, Any]], cfg: Dict[str, Any], W: int, H: int, caminho: str,
              paleta: Optional[Dict[str, Any]] = None) -> str:
    import dp_cores
    cfg = normalizar(cfg)
    fam = cfg["fonte"]
    estilo = cfg["estilo"]
    if estilo == "cinema" and fam == "DP Inter":
        fam = "DP Playfair Display"
    if estilo == "contorno" and fam == "DP Inter":
        fam = "DP Anton"
    # mesmo tamanho de letra da telinha (font-size = altura × tamanho): o \fs do libass
    # mede a "célula" da fonte, então é convertido — antes a legenda saía ~30% menor
    fs_css = H * cfg["tamanho"]
    fs = dp_destaques.fs_libass(fam, fs_css)
    cor_ativa = cfg["cor_ativa"] or ((dp_cores.normalizar(paleta)["primaria"]) if dp_cores.vale_para(paleta, "legendas") else "#FFD60A")
    r, g, b = dp_cores.rgb(cor_ativa)
    sobre_ativa = "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#FFFFFF"
    branco = _c(cfg["cor_texto"])
    an = {"base": 2, "meio": 5, "topo": 8}[cfg["posicao"]]
    cx = W // 2
    cy = {"base": int(H * 0.93), "meio": H // 2, "topo": int(H * 0.06)}[cfg["posicao"]]  # telinha: bottom 7% / top 6%
    bord = max(2, int(round(fs_css / 24))) if cfg["contorno"] else 0  # contorno da telinha: fs/14 centrado na borda da letra
    estilos_ass = [
        f"Style: Leg,{fam},{fs},{branco},{branco},&H00000000,&H80000000,1,{1 if estilo == 'cinema' else 0},0,0,100,100,0,0,1,{bord},{1 if estilo != 'cinema' else 2},{an},20,20,0,1",
        f"Style: Caixa,{fam},{fs},{branco},{branco},&H50000000,&H50000000,1,0,0,0,100,100,0,0,3,{max(4, fs // 5)},0,{an},20,20,0,1",
        f"Style: Faixa,{fam},{fs},{_c(sobre_ativa)},{_c(sobre_ativa)},{_c(cor_ativa)},{_c(cor_ativa)},1,0,0,0,100,100,0,0,3,{max(4, fs // 5)},0,{an},20,20,0,1",
    ]
    linhas_ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
                  "[V4+ Styles]",
                  "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
                  *estilos_ass, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    up = (lambda s: s.upper()) if cfg["maiusculas"] or estilo == "contorno" else (lambda s: s)
    esc = dp_destaques._esc
    pos = f"\\an{an}\\pos({cx},{cy})"
    max_w = W * 0.88

    def ev(t0, t1, txt, style="Leg", layer=1):
        if t1 - t0 >= 0.02:
            linhas_ass.append(f"Dialogue: {layer},{_t(t0)},{_t(t1)},{style},,0,0,0,,{txt}")

    if estilo == "palavra_unica":
        for k, w in enumerate(palavras):
            t0 = float(w["start"])
            t1 = max(float(w.get("end", t0)), min(float(palavras[k + 1]["start"]) if k + 1 < len(palavras) else t0 + 0.6, t0 + 1.0))
            fs2 = int(fs * 1.5)
            ev(t0, t1, f"{{{pos}\\fs{fs2}\\1c{_c(cor_ativa) if k % 3 == 1 else branco}\\fscx70\\fscy70\\t(0,90,\\fscx108\\fscy108)\\t(90,160,\\fscx100\\fscy100)}}{esc(up(w['word']))}")
    else:
        grupos = agrupar(palavras, cfg["max_palavras"])
        for gi, g in enumerate(grupos):
            t_ini = float(g[0]["start"])
            prox = float(grupos[gi + 1][0]["start"]) if gi + 1 < len(grupos) else None
            t_fim = float(g[-1].get("end", g[-1]["start"])) + 0.25
            if prox is not None:
                t_fim = min(max(t_fim, float(g[-1].get("end", 0))), prox) if prox - float(g[-1].get("end", 0)) < 0.3 else min(t_fim, prox)
            textos = [up(w["word"]) for w in g]
            frase = " ".join(textos)
            fs_g = fs
            wl = largura(frase, fam, fs_g)
            if wl > max_w:
                fs_g = int(fs * max_w / wl)
                wl = largura(frase, fam, fs_g)
            fs_tag = f"\\fs{fs_g}" if fs_g != fs else ""
            if estilo in ("seguir", "contorno", "cinema"):
                ev(t_ini, t_fim, f"{{{pos}{fs_tag}\\fad(80,60)}}{esc(frase)}")
            elif estilo == "caixa":
                ev(t_ini, t_fim, f"{{{pos}{fs_tag}\\fad(60,60)}}{esc(frase)}", "Caixa")
            elif estilo == "faixa":
                ev(t_ini, t_fim, f"{{{pos}{fs_tag}\\fad(60,60)}}{esc(frase)}", "Faixa")
            elif estilo == "preenchimento":
                partes = []
                for k, w in enumerate(g):
                    nxt = float(g[k + 1]["start"]) if k + 1 < len(g) else float(w.get("end", w["start"]))
                    cs = max(1, int(round((nxt - float(w["start"])) * 100)))
                    partes.append(f"{{\\kf{cs}}}{esc(textos[k])}" + (" " if k < len(g) - 1 else ""))
                atraso = max(0, int(round((float(g[0]["start"]) - t_ini) * 100)))
                k_atraso = ("\\k" + str(atraso)) if atraso else ""
                ev(t_ini, t_fim, f"{{{pos}{fs_tag}\\1c{_c(cor_ativa)}\\2c{branco}{k_atraso}}}" + "".join(partes))
            else:  # classico, destaque, pop — um evento por palavra ativa
                for k, w in enumerate(g):
                    a0 = t_ini if k == 0 else float(w["start"])
                    a1 = float(g[k + 1]["start"]) if k + 1 < len(g) else t_fim
                    partes = []
                    for j, tx in enumerate(textos):
                        sep = " " if j < len(textos) - 1 else ""
                        if j == k:
                            if estilo == "classico":
                                partes.append(f"{{\\1c{_c(cor_ativa)}}}{esc(tx)}{{\\1c{branco}}}{sep}")
                            elif estilo == "pop":
                                partes.append(f"{{\\1c{_c(cor_ativa)}\\fscx118\\fscy118}}{esc(tx)}{{\\1c{branco}\\fscx100\\fscy100}}{sep}")
                            else:
                                partes.append(f"{{\\1c{_c(sobre_ativa)}\\bord0}}{esc(tx)}{{\\1c{branco}\\bord{bord}}}{sep}")
                        else:
                            partes.append(esc(tx) + sep)
                    ev(a0, a1, f"{{{pos}{fs_tag}}}" + "".join(partes))
                    if estilo == "destaque":
                        # caixa colorida atrás da palavra ativa (medida com a própria fonte)
                        antes = " ".join(textos[:k]) + (" " if k else "")
                        x0 = cx - wl / 2 + largura(antes, fam, fs_g)
                        ww = largura(textos[k], fam, fs_g)
                        alt = fs_g * 1.0
                        yb = {2: cy, 5: cy + alt / 2, 8: cy + alt}[an]
                        pad = fs_g * 0.12
                        ev(a0, a1, f"{{\\an7\\pos({int(x0 - pad)},{int(yb - alt - pad * 0.4)})\\bord0\\shad0\\1c{_c(cor_ativa)}\\p1}}m 0 0 l {int(ww + 2 * pad)} 0 {int(ww + 2 * pad)} {int(alt + pad * 0.8)} 0 {int(alt + pad * 0.8)}", layer=0)
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas_ass) + "\n")
    return caminho


def queimar(video: str, ass: str, saida: str) -> str:
    """Queima as legendas (com as fontes do DarkPlanner) mantendo o áudio."""
    import subprocess
    from video_assembler import _escape_path_for_ffmpeg_filter
    vf = f"ass='{_escape_path_for_ffmpeg_filter(ass)}':fontsdir='{_escape_path_for_ffmpeg_filter(dp_destaques.FONTES_DIR)}'"
    import export_paralelo  # ⚡ pedaços em paralelo (conferidos quadro a quadro); falhou → do jeito de sempre
    try:
        from video_assembler import _probe_duration
        _dur = _probe_duration(video)
    except Exception:  # noqa: BLE001
        _dur = 0.0
    if export_paralelo.tentar("legendas", lambda: export_paralelo.vf_em_pedacos(
            video, saida, vf, _dur, os.path.join(os.path.dirname(os.path.abspath(saida)), "_pedacos_legendas"), "legendas")):
        return saida
    import qualidade_export
    r = qualidade_export.rodar(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-c:a", "copy", saida], timeout=4 * 3600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-600:])
    return saida
