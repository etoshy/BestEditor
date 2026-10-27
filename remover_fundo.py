"""
remover_fundo.py — 🧽 Remover fundo (v84_240)
===============================================

Ferramenta à parte (aba 🧰 Ferramentas → 🧽 Remover fundo):
  • 📦 manda um ZIP com imagens (fundo verde é o melhor — chroma key) e recebe O MESMO zip, nas mesmas pastas e com os
    mesmos nomes, só que cada imagem virou PNG transparente (os outros arquivos do zip voltam iguais);
  • 🖼 manda uma (ou várias) imagem(ns) e recebe o PNG sem fundo (várias = um zip).

Como tira o fundo (modo "auto" escolhe olhando a borda da imagem):
  • 🟩 verde — chroma key com a mesma limpeza das poses dos 🧍 Personagens (o verde preso entre os fios sai, a borda
    esverdeada é neutralizada, pontinhos soltos somem);
  • ⬜ branco / 🎨 cor lisa — o fundo é a cor da borda: sai o que é dessa cor E encosta na borda (o branco DENTRO da
    figura — olho, camisa — fica), com a borda suavizada.
Opções: recortar na figura (com margem) e o tamanho máximo.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageFilter

EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
MODOS = {"auto": "🤖 automático (olha a borda)", "verde": "🟩 fundo verde (chroma key)", "branco": "⬜ fundo branco",
         "cor": "🎨 fundo de uma cor lisa (a cor da borda)"}
MAX_ARQUIVOS = 2000


class FundoErro(Exception):
    pass


def _borda(img: Image.Image):
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=np.int16)
    k = max(2, min(a.shape[0], a.shape[1]) // 60)
    return np.concatenate([a[:k].reshape(-1, 3), a[-k:].reshape(-1, 3), a[:, :k].reshape(-1, 3), a[:, -k:].reshape(-1, 3)])


def detectar(img: Image.Image) -> str:
    """verde / branco / cor — pela borda da imagem."""
    import numpy as np
    b = _borda(img)
    r, g, bl = b[:, 0], b[:, 1], b[:, 2]
    if float(((g >= 90) & (g > np.maximum(r, bl) * 1.35 + 20)).mean()) > 0.5:
        return "verde"
    if float(((b.min(axis=1) >= 225) & ((b.max(axis=1) - b.min(axis=1)) <= 20)).mean()) > 0.5:
        return "branco"
    return "cor"


def _alfa_cor(img: Image.Image, tol: float = 38.0) -> Image.Image:
    """O fundo de cor lisa: o que é parecido com a cor da borda E está ligado à borda (flood fill) = transparente."""
    import numpy as np
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    cor = np.median(_borda(img), axis=0).astype(np.float32)
    dist = np.sqrt(((rgb - cor) ** 2).sum(axis=2))
    parecido = dist < tol
    try:
        import cv2
        n, lab = cv2.connectedComponents(parecido.astype(np.uint8), connectivity=4)
        h, w = parecido.shape
        borda_lab = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist()) - {0}
        fundo = np.isin(lab, list(borda_lab)) & parecido
    except ImportError:
        fundo = parecido
    a = np.ones(parecido.shape, np.float32)
    a[fundo] = 0.0
    # borda macia: perto da cor do fundo e encostada nele fica meio transparente
    try:
        import cv2
        perto = cv2.dilate(fundo.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        suave = perto & ~fundo & (dist < tol * 2.2)
        a[suave] = np.clip((dist[suave] - tol) / (tol * 1.2), 0.15, 1.0)
    except ImportError:
        pass
    return Image.fromarray((a * 255).astype(np.uint8), "L")


def remover(img: Image.Image, modo: str = "auto", recortar: bool = False, margem: int = 12,
            lado_max: int = 0) -> Tuple[Image.Image, Dict[str, Any]]:
    """Uma imagem → (PNG RGBA sem fundo, o que fez)."""
    import personagens_limpeza as L
    if getattr(img, "is_animated", False):
        img.seek(0)
    tinha_alfa = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if tinha_alfa:  # já vem transparente: compõe sobre a cor do fundo que ela imita (não perde o recorte que já tem)
        rgba = img.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 250:
            info = {"modo": "ja_transparente"}
            return _finalizar(rgba, info, recortar, margem, lado_max)
    rgb = img.convert("RGB")
    m = modo if modo in ("verde", "branco", "cor") else detectar(rgb)
    info: Dict[str, Any] = {"modo": m}
    if m == "verde":
        alfa = L.alfa_do_verde(rgb)
        limpo, alfa, feito = L.limpar(rgb, alfa, {"fundo": "verde", "erodir": 1})
    elif m == "branco":
        alfa = _alfa_cor(rgb, 30.0)
        limpo, alfa, feito = L.limpar(rgb, alfa, {"fundo": "branco", "erodir": 0, "fundo_preso": False})
    else:
        alfa = _alfa_cor(rgb)
        limpo, alfa, feito = L.limpar(rgb, alfa, {"fundo": "cor", "erodir": 0, "halo": False, "fundo_preso": False})
    info["limpeza"] = {k: v for k, v in feito.items() if isinstance(v, (int, float, str))}
    out = limpo.convert("RGBA")
    out.putalpha(alfa)
    import numpy as np
    sobrou = float((np.asarray(alfa) > 128).mean())
    if sobrou > 0.97:
        info["aviso"] = "quase nada saiu — o fundo não é da cor que o modo esperava (tente outro modo)"
    elif sobrou < 0.005:
        info["aviso"] = "sumiu quase tudo — a figura é da mesma cor do fundo? (tente outro modo)"
    return _finalizar(out, info, recortar, margem, lado_max)


def _finalizar(out: Image.Image, info: Dict[str, Any], recortar: bool, margem: int, lado_max: int):
    if recortar:
        caixa = out.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
        if caixa:
            x0, y0, x1, y1 = caixa
            m = max(0, int(margem))
            out = out.crop((max(0, x0 - m), max(0, y0 - m), min(out.width, x1 + m), min(out.height, y1 + m)))
    if lado_max and max(out.size) > lado_max:
        k = lado_max / max(out.size)
        out = out.resize((max(1, round(out.width * k)), max(1, round(out.height * k))), Image.LANCZOS)
    return out, info


def _png_bytes(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG", optimize=True)
    return b.getvalue()


def _nome_png(nome: str, usados: set) -> str:
    raiz, _ext = os.path.splitext(nome)
    n = raiz + ".png"
    k = 2
    while n.lower() in usados:
        n = f"{raiz}_{k}.png"
        k += 1
    usados.add(n.lower())
    return n


def processar_zip(dados: bytes, modo: str = "auto", recortar: bool = False, margem: int = 12,
                  lado_max: int = 0) -> Tuple[bytes, Dict[str, Any]]:
    """📦 O mesmo zip (mesmas pastas e nomes), com cada imagem em PNG sem fundo; o resto volta igual."""
    try:
        zin = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        raise FundoErro("Isso não é um arquivo .zip válido.")
    infos = [i for i in zin.infolist() if not i.is_dir()]
    if len(infos) > MAX_ARQUIVOS:
        raise FundoErro(f"Zip com arquivos demais ({len(infos)}; máximo {MAX_ARQUIVOS}).")
    rel: Dict[str, Any] = {"imagens": 0, "copiados": 0, "avisos": [], "modos": {}}
    usados = {i.filename.lower() for i in infos if not i.filename.lower().endswith(EXTS)}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in infos:
            nome = i.filename
            if "__MACOSX/" in nome or os.path.basename(nome).startswith("._"):
                continue
            conteudo = zin.read(i)
            if nome.lower().endswith(EXTS):
                try:
                    im = Image.open(io.BytesIO(conteudo))
                    im.load()
                    out, info = remover(im, modo, recortar, margem, lado_max)
                except Exception as exc:  # noqa: BLE001
                    rel["avisos"].append(f"{nome}: não abriu ({str(exc)[:80]}) — foi igual")
                    zout.writestr(nome, conteudo)
                    rel["copiados"] += 1
                    continue
                zout.writestr(_nome_png(nome, usados), _png_bytes(out))
                rel["imagens"] += 1
                rel["modos"][info["modo"]] = rel["modos"].get(info["modo"], 0) + 1
                if info.get("aviso"):
                    rel["avisos"].append(f"{nome}: {info['aviso']}")
            else:
                zout.writestr(nome, conteudo)
                rel["copiados"] += 1
    if not rel["imagens"]:
        raise FundoErro("Nenhuma imagem dentro do zip (png, jpg, webp…).")
    return buf.getvalue(), rel


def processar_imagens(arquivos: List[Tuple[str, bytes]], modo: str = "auto", recortar: bool = False, margem: int = 12,
                      lado_max: int = 0) -> Tuple[bytes, str, Dict[str, Any]]:
    """🖼 Uma imagem → o PNG; várias → um zip com os PNGs. → (bytes, nome do arquivo, relatório)."""
    rel: Dict[str, Any] = {"imagens": 0, "avisos": [], "modos": {}}
    saidas: List[Tuple[str, bytes]] = []
    usados: set = set()
    for nome, b in arquivos:
        try:
            im = Image.open(io.BytesIO(b))
            im.load()
        except Exception:  # noqa: BLE001
            rel["avisos"].append(f"{nome}: não é uma imagem")
            continue
        out, info = remover(im, modo, recortar, margem, lado_max)
        saidas.append((_nome_png(os.path.basename(nome) or "imagem.png", usados), _png_bytes(out)))
        rel["imagens"] += 1
        rel["modos"][info["modo"]] = rel["modos"].get(info["modo"], 0) + 1
        if info.get("aviso"):
            rel["avisos"].append(f"{nome}: {info['aviso']}")
    if not saidas:
        raise FundoErro("Nenhuma imagem válida.")
    if len(saidas) == 1:
        return saidas[0][1], saidas[0][0], rel
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in saidas:
            z.writestr(n, b)
    return buf.getvalue(), "sem_fundo.zip", rel


# ------------------------------------------------------------------ rotas
def registrar(app) -> None:
    import json
    from urllib.parse import quote
    from flask import jsonify, render_template, request, send_file

    def _opcoes():
        f = request.form
        try:
            margem = max(0, min(400, int(f.get("margem") or 12)))
            lado = max(0, min(8000, int(f.get("lado_max") or 0)))
        except ValueError:
            margem, lado = 12, 0
        return (f.get("modo") if f.get("modo") in MODOS else "auto"), f.get("recortar") == "1", margem, lado

    def _resp(dados: bytes, nome: str, mime: str, rel: Dict[str, Any]):
        r = send_file(io.BytesIO(dados), mimetype=mime, as_attachment=True, download_name=nome)
        r.headers["X-Relatorio"] = quote(json.dumps(rel, ensure_ascii=False))
        r.headers["X-Nome"] = quote(nome)
        return r

    @app.route("/remover-fundo", methods=["GET"])
    def remover_fundo_pagina():
        return render_template("remover_fundo.html", modos=MODOS)

    @app.route("/remover-fundo/zip", methods=["POST"])
    def remover_fundo_zip():
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return jsonify({"ok": False, "erro": "Escolha o .zip."}), 400
        modo, rec, margem, lado = _opcoes()
        try:
            dados, rel = processar_zip(arq.read(), modo, rec, margem, lado)
        except FundoErro as exc:
            return jsonify({"ok": False, "erro": str(exc)}), 400
        raiz = os.path.splitext(os.path.basename(arq.filename))[0] or "imagens"
        return _resp(dados, f"{raiz}_png.zip", "application/zip", rel)

    @app.route("/remover-fundo/imagens", methods=["POST"])
    def remover_fundo_imagens():
        arqs = [(f.filename, f.read()) for f in request.files.getlist("arquivos") if f and f.filename][:200]
        if not arqs:
            return jsonify({"ok": False, "erro": "Escolha a(s) imagem(ns)."}), 400
        modo, rec, margem, lado = _opcoes()
        try:
            dados, nome, rel = processar_imagens(arqs, modo, rec, margem, lado)
        except FundoErro as exc:
            return jsonify({"ok": False, "erro": str(exc)}), 400
        return _resp(dados, nome, "application/zip" if nome.endswith(".zip") else "image/png", rel)
