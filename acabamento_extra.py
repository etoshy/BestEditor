"""🎨 v84_333: acabamento avançado dos curtos (vindo do shortmaker) — por canal, como o resto do acabamento.

@ do canal: fonte (inclusive a SUA, enviada), cor, tamanho, opacidade, BORDA (cor + espessura), SOMBRA (cor + distância),
            DEGRADÊ de 2 cores (horizontal/vertical) e ajuste fino X/Y em pixels.
Legenda:    BORDA (cor + espessura), SOMBRA (cor + distância), OPACIDADE e o estilo "rolante" (desliza) — dp_legendas.
Tarja:      esconde a legenda que JÁ VEM gravada no vídeo original (faixa de y0% a y1%): desfoque ou cor sólida.
            (só pra legenda/texto do original — o crédito/marca d'água do criador fica.)
Prévia:     o quadro de verdade (um clipe do canal, ou um fundo) com a tarja, a legenda e o @ queimados pelo próprio libass.
Valores em px são na escala de um vídeo 1080×1920 (o site converte pro tamanho real).
Vazio = como era antes (nada muda nos canais que você não mexer).
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List, Optional

PADRAO: Dict[str, Any] = {
    # 🏷 @ do canal
    "marca_fonte": "", "marca_cor": "", "marca_tamanho": "", "marca_opacidade": "", "marca_borda": "", "marca_borda_cor": "",
    "marca_sombra": "", "marca_sombra_cor": "", "marca_gradiente": False, "marca_cor2": "", "marca_grad_dir": "horizontal",
    "marca_x": 0, "marca_y": 0, "marca_altura": "",  # ↕ v84_334: com a posição "livre" (arrastada na prévia), % de cima
    # 🔤 legenda
    "legenda_borda": "", "legenda_borda_cor": "", "legenda_sombra": "", "legenda_sombra_cor": "", "legenda_opacidade": "",
    # ▭ tarja sobre a legenda do vídeo original
    "tarja_modo": "", "tarja_y0": "", "tarja_y1": "", "tarja_cor": "#000000",
    # 📐 v84_335: o formato do canal ("" = o que estiver no envio) e se sai também a versão 1:1
    "proporcao": "", "tambem_quadrado": False,
}
_HEX = re.compile(r"#[0-9A-F]{6}")


def _num(v: Any, lo: float, hi: float, inteiro: bool = True) -> Any:
    if v in (None, ""):
        return ""
    try:
        x = max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return ""
    return int(round(x)) if inteiro else round(x, 4)


def _cor(v: Any) -> str:
    v = str(v or "").strip().upper()
    if re.fullmatch(r"[0-9A-F]{6}", v):
        v = "#" + v
    return v if _HEX.fullmatch(v) else ""


def familias() -> Dict[str, str]:
    """Fontes que dá pra usar (as de fábrica da lista + as que você enviou)."""
    import curtos as CT
    out = dict(CT.FONTES_LEGENDA)
    try:
        import dp_destaques
        for v in dp_destaques.fontes_json().values():
            fam = str(v.get("familia") or "")
            if fam.startswith("DP ") and fam not in out:
                out[fam] = fam[3:] + " (sua)"
    except Exception:  # noqa: BLE001
        pass
    return out


def limpar(k: str, v: Any) -> Any:
    """Valida uma chave nova do acabamento (None = não é minha)."""
    if k not in PADRAO:
        return None
    if k in ("marca_fonte",):
        return v if v in familias() and v else ""
    if k in ("marca_cor", "marca_borda_cor", "marca_sombra_cor", "marca_cor2", "legenda_borda_cor", "legenda_sombra_cor"):
        return _cor(v)
    if k == "tarja_cor":
        return _cor(v) or "#000000"
    if k == "proporcao":
        return v if v in ("", "9:16", "1:1") else ""
    if k == "tambem_quadrado":
        return v not in (False, "0", "false", "", None)
    if k == "marca_gradiente":
        return v not in (False, "0", "false", "", None)
    if k == "marca_grad_dir":
        return v if v in ("horizontal", "vertical") else "horizontal"
    if k == "tarja_modo":
        return v if v in ("", "blur", "solida") else ""
    if k == "marca_tamanho":
        return _num(v, 1, 12, False)  # % da altura
    if k in ("marca_opacidade", "legenda_opacidade"):
        return _num(v, 5, 100)
    if k in ("marca_borda", "legenda_borda"):
        return _num(v, 0, 20)
    if k in ("marca_sombra", "legenda_sombra"):
        return _num(v, 0, 20)
    if k in ("marca_x", "marca_y"):
        return _num(v, -600, 600) or 0
    if k in ("tarja_y0", "tarja_y1", "marca_altura"):
        return _num(v, 0, 100, False)
    return v


def aplicar_no_projeto(cfg: Dict[str, Any], a: Dict[str, Any]) -> None:
    """As chaves novas do acabamento → config.marca / config.legenda / config.tarja do curto."""
    m = dict(cfg.get("marca") or {})
    mapa = {"marca_fonte": "fonte", "marca_cor": "cor", "marca_borda_cor": "borda_cor", "marca_sombra_cor": "sombra_cor"}
    for ka, km in mapa.items():
        if a.get(ka):
            m[km] = a[ka]
    if a.get("marca_tamanho") not in (None, ""):
        m["tamanho"] = float(a["marca_tamanho"]) / 100
    if a.get("marca_opacidade") not in (None, ""):
        m["opacidade"] = float(a["marca_opacidade"]) / 100
    for ka, km in (("marca_borda", "borda"), ("marca_sombra", "sombra")):
        if a.get(ka) not in (None, ""):
            m[km] = int(a[ka])
    if a.get("marca_gradiente") and a.get("marca_cor2"):  # (a direção e a cor 2 só valem com o degradê ligado)
        m.update(gradiente=True, cor2=a["marca_cor2"], grad_dir=a.get("marca_grad_dir") or "horizontal")
    if a.get("marca_posicao") == "livre" and a.get("marca_altura") not in (None, ""):
        m["altura"] = float(a["marca_altura"]) / 100
    for ka, km in (("marca_x", "desvio_x_px"), ("marca_y", "desvio_y_px")):
        if int(a.get(ka) or 0):
            m[km] = int(a[ka])
    if m:
        cfg["marca"] = m
    leg = cfg.get("legenda")
    if isinstance(leg, dict):
        for ka, kl in (("legenda_borda", "borda"), ("legenda_sombra", "sombra"), ("legenda_opacidade", "opacidade")):
            if a.get(ka) not in (None, ""):
                leg[kl] = int(a[ka])
        for ka, kl in (("legenda_borda_cor", "borda_cor"), ("legenda_sombra_cor", "sombra_cor")):
            if a.get(ka):
                leg[kl] = a[ka]
    if a.get("proporcao") in ("9:16", "1:1"):  # 📐 v84_335: o formato do canal
        cfg["proporcao"] = a["proporcao"]
    if a.get("tambem_quadrado") and a.get("proporcao") != "1:1":
        cfg["tambem_quadrado"] = True
    t = tarja_de(a)
    if t:
        cfg["tarja"] = t
    else:
        cfg.pop("tarja", None)


def tarja_de(a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if a.get("tarja_modo") not in ("blur", "solida"):
        return None
    try:
        y0, y1 = sorted((float(a.get("tarja_y0") or 0), float(a.get("tarja_y1") or 0)))
    except (TypeError, ValueError):
        return None
    if y1 - y0 < 1:
        return None
    return {"modo": a["tarja_modo"], "y0": round(y0 / 100, 4), "y1": round(min(100.0, y1) / 100, 4), "cor": a.get("tarja_cor") or "#000000"}


def filtro_tarja(t: Dict[str, Any]) -> str:
    """O filtro do ffmpeg que cobre a faixa (frações da altura) com desfoque forte ou cor sólida."""
    y0, y1 = float(t["y0"]), float(t["y1"])
    if t.get("modo") == "solida":
        cor = "0x" + str(t.get("cor") or "#000000").lstrip("#")
        return f"drawbox=x=0:y=ih*{y0:.4f}:w=iw:h=ih*{y1 - y0:.4f}:color={cor}@1:t=fill"
    return (f"split[a][b];[b]crop=iw:ih*{y1 - y0:.4f}:0:ih*{y0:.4f},boxblur=luma_radius=min(h\\,w)/4:luma_power=3[f];"
            f"[a][f]overlay=0:H*{y0:.4f}")


def aplicar_tarja(video: str, t: Optional[Dict[str, Any]]) -> bool:
    """Queima a tarja NO clipe (guarda o original ao lado, _sem_tarja). False se não tem tarja / não deu."""
    if not t or not os.path.isfile(video):
        return False
    base, ext = os.path.splitext(video)
    original = base + "_sem_tarja" + ext
    if not os.path.isfile(original):
        os.replace(video, original)
    saida = base + "_tarja_tmp" + ext
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", original, "-filter_complex", "[0:v]" + filtro_tarja(t) + "[v]",
                        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
                        "-c:a", "copy", saida], capture_output=True, timeout=1800)
    if r.returncode != 0 or not os.path.isfile(saida):
        if not os.path.isfile(video):
            os.replace(original, video)
        return False
    os.replace(saida, video)
    return True


# ------------------------------------------------------------------ 🔤 fontes enviadas
def instalar_fonte(arquivo: str, nome: str) -> Dict[str, Any]:
    """.ttf/.otf → fonte "DP <nome>" (o mesmo instalador do 📘 Guia: renomeia a família pro libass achar e registra)."""
    import dp_guia
    import dp_extras
    nome = " ".join(str(nome or "").split())[:40]
    if not nome:
        try:
            from fontTools.ttLib import TTFont
            n = TTFont(arquivo)["name"]
            nome = str(n.getDebugName(16) or n.getDebugName(1) or "").strip()[:40]
        except Exception:  # noqa: BLE001
            nome = ""
    chave = re.sub(r"[^a-z0-9_]", "", re.sub(r"\s+", "_", nome.lower()))[:30] or "minha_fonte"
    if not re.match(r"[a-z0-9]", chave):
        chave = "f_" + chave
    chave = "usr_" + chave
    try:
        it = dp_guia.adicionar_fonte(arquivo, chave, nome)
    except SystemExit as exc:  # o instalador do Guia avisa com SystemExit
        raise ValueError(str(exc)) from exc
    for f in ("carregar",):
        try:
            getattr(dp_extras, f).cache_clear()
        except AttributeError:
            pass
    try:
        import dp_destaques
        dp_destaques._ESCALA_LIBASS.pop(it["familia"], None)
        dp_destaques._FONTES_PIL.clear()
    except Exception:  # noqa: BLE001
        pass
    try:
        import dp_legendas
        dp_legendas._mapa_fontes.cache_clear()
        dp_legendas._fonte_pil.cache_clear()
    except Exception:  # noqa: BLE001
        pass
    return it


# ------------------------------------------------------------------ 🖼 prévia de verdade
def _quadro_base(base: str, canal_id: str, destino: str) -> str:
    """Um quadro de um clipe recente do canal (9:16, preenchendo); sem clipe, um fundo em degradê."""
    import curtos as CT
    alvo = None
    try:
        for x in sorted(CT.listar(base), key=lambda y: str(y.get("criado") or ""), reverse=True)[:80]:
            try:
                p = CT.carregar(base, x["id"])
            except CT.CurtoErro:
                continue
            if canal_id and p.get("canal_id") != canal_id:
                continue
            for m in p.get("midias") or []:
                if m.get("tipo") == "video" and str(m.get("id") or "").startswith("M"):
                    cam = CT.caminho_midia(base, p, m)
                    if cam:
                        sem = os.path.splitext(cam)[0] + "_sem_tarja" + os.path.splitext(cam)[1]
                        alvo = (sem if os.path.isfile(sem) else cam, float(m.get("dur") or 0))
                        break
            if alvo:
                break
    except Exception:  # noqa: BLE001
        alvo = None
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if alvo:
        t = max(0.0, (alvo[1] or 4.0) * 0.4)
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", alvo[0], "-frames:v", "1", "-vf", vf, destino],
                           capture_output=True, timeout=60)
        if r.returncode == 0 and os.path.isfile(destino):
            return destino
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "gradients=s=1080x1920:c0=0x2b3a55:c1=0x0d1220:n=2:d=1", "-frames:v", "1",
                    destino], capture_output=True, timeout=60)
    if not os.path.isfile(destino):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1b2437:s=1080x1920:d=1", "-frames:v", "1", destino],
                       capture_output=True, timeout=60)
    return destino


def previa(base: str, a: Dict[str, Any], canal_id: str, pasta_tmp: str, texto: str = "ESSA PALAVRA AQUI") -> str:
    """O quadro com a tarja + a legenda (a 2ª palavra falando) + o @ — renderizado pelo mesmo libass do vídeo final."""
    import curtos as CT
    import dp_destaques
    import dp_legendas
    import marca_canal
    from video_assembler import _escape_path_for_ffmpeg_filter
    os.makedirs(pasta_tmp, exist_ok=True)
    W, H = 1080, 1920
    fundo = _quadro_base(base, canal_id, os.path.join(pasta_tmp, "fundo.jpg"))
    p = {"id": "previa", "modelo": "comentario", "canal_id": canal_id, "config": {}}
    CT.aplicar_acabamento(p, a)
    cfg = p["config"]
    perfil_leg: Dict[str, Any] = {}
    try:
        perfil_leg = dict(CT.perfil_do(base, p).get("legenda") or {})
    except Exception:  # noqa: BLE001
        pass
    leg = dict(perfil_leg)
    leg.update(cfg.get("legenda") or {})
    leg["ativa"] = True
    if leg.get("estilo") in (None, "", "seguir"):
        leg.setdefault("estilo", "classico")
    palavras, t0 = [], 0.0
    for w in texto.split():
        palavras.append({"word": w, "start": round(t0, 2), "end": round(t0 + 0.45, 2)})
        t0 += 0.5
    ass_leg = dp_legendas.gerar_ass(palavras, leg, W, H, os.path.join(pasta_tmp, "leg.ass"))
    filtros = []
    t_ = cfg.get("tarja")
    if t_:
        filtros.append(filtro_tarja(t_))
    fd = _escape_path_for_ffmpeg_filter(dp_destaques.FONTES_DIR)
    filtros.append(f"ass='{_escape_path_for_ffmpeg_filter(ass_leg)}':fontsdir='{fd}'")
    m = CT.normalizar_marca(cfg.get("marca") or {}, "seucanal")
    if not str(m.get("texto") or "").strip() or m.get("texto") == "@":
        m["texto"] = "@seucanal"
    m["ativa"] = True
    ass_m = marca_canal.gerar_ass(m, W, H, 3.0, os.path.join(pasta_tmp, "marca.ass"), leg.get("posicao") or "",
                                  marca_canal.centro_legenda(dp_legendas.normalizar(leg)))
    filtros.append(f"ass='{_escape_path_for_ffmpeg_filter(ass_m)}':fontsdir='{fd}'")
    saida = os.path.join(pasta_tmp, "previa.jpg")
    vf = "[0:v]loop=loop=-1:size=1:start=0,trim=duration=1.2,setpts=N/30/TB," + ",".join(
        f if not f.startswith("split") else f for f in filtros) + "[v]"
    vf = vf.replace(",split[a][b];", ",split[a][b];")  # (a tarja de desfoque usa um grafo com rótulos)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", fundo, "-filter_complex", vf, "-map", "[v]", "-ss", "0.75", "-frames:v", "1",
                        "-q:v", "3", saida], capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise RuntimeError((r.stderr or "")[-300:] or "a prévia não saiu")
    return saida


SORTEIO_DOC = "🎲 o sorteio é feito na página (JS): fonte, paleta, borda, sombra, degradê e estilo — você salva se gostar."
