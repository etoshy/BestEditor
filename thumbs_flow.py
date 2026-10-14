"""
🖼 thumbs_flow.py — as THUMBNAILS que a IA recomenda, geradas no Google Flow (v84_96)
===================================================================================

Onde a IA recomenda thumbnail (🕵️ Modelos de vídeo → "thumbnails"; 📜 Roteiro do YouTube → títulos/descrição;
📊 Analisador de canal → sugestões de vídeo), cada ideia vira um card com:
  • "texto"  — 2 a 4 palavras GRANDES que vão na miniatura;
  • "prompt" — a cena da imagem, em inglês, pro Flow (16:9, um assunto claro, contraste, espaço vazio pro texto, SEM texto
               escrito — o Flow erra letra; o site põe o texto por cima, com contorno, do jeito das thumbs de documentário).
Botão 🎨 Gerar no Flow (uma ou todas) — roda em segundo plano (🔔 avisa) e guarda:
  thumbs/<origem>_<id>/thumb_<n>_<t>.png      a imagem do Flow (limpa)
  thumbs/<origem>_<id>/thumb_<n>_<t>_final.jpg  1280×720 com o texto (pronta pra subir no YouTube)
"""
from __future__ import annotations

import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional

PASTA = "thumbs"
ORIGENS = ("dossie", "roteiro_yt", "canal")
_TRAVA = threading.Lock()

ESTILO_PADRAO = ("YouTube documentary thumbnail, 16:9, cinematic photo, one clear focal subject, dramatic high-contrast lighting, "
                 "shallow depth of field, strong emotion, clean background, large empty negative space on the {lado} third for a "
                 "big title, no text, no letters, no words, no watermark, no logo, no gore, no blood, monetization-friendly")


class ThumbErro(Exception):
    pass


def _valido(origem: str, pid: str) -> bool:
    return origem in ORIGENS and bool(re.fullmatch(r"[A-Za-z0-9_\-]{3,64}", str(pid or "")))


def pasta(base: str, origem: str, pid: str) -> str:
    if not _valido(origem, pid):
        raise ThumbErro("Projeto inválido.")
    return os.path.join(base, PASTA, f"{origem}_{pid}")


def _arq(base: str, origem: str, pid: str) -> str:
    return os.path.join(pasta(base, origem, pid), "thumbs.json")


def carregar(base: str, origem: str, pid: str) -> Dict[str, Any]:
    try:
        with open(_arq(base, origem, pid), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"itens": []}
    except (OSError, ValueError):
        return {"itens": []}


def salvar(base: str, origem: str, pid: str, d: Dict[str, Any]) -> None:
    os.makedirs(pasta(base, origem, pid), exist_ok=True)
    tmp = _arq(base, origem, pid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    arquivo_seguro.trocar(tmp, _arq(base, origem, pid))


def normalizar(x: Any) -> Optional[Dict[str, str]]:
    """Uma ideia de thumbnail (texto solto também vale: vira a "ideia")."""
    if isinstance(x, str):
        x = {"ideia": x}
    if not isinstance(x, dict):
        return None
    ideia = " ".join(str(x.get("ideia") or x.get("descricao") or x.get("thumb") or "").split())[:400]
    texto = " ".join(str(x.get("texto") or x.get("texto_na_thumb") or "").split())[:40]
    prompt = " ".join(str(x.get("prompt") or x.get("prompt_imagem") or "").split())[:900]
    if not (ideia or prompt):
        return None
    return {"ideia": ideia or prompt, "texto": texto, "prompt": prompt}


def sincronizar(base: str, origem: str, pid: str, ideias: List[Any]) -> Dict[str, Any]:
    """Junta as ideias que a IA recomendou com as que já estão salvas (as geradas/editadas ficam)."""
    with _TRAVA:
        d = carregar(base, origem, pid)
        itens = d.setdefault("itens", [])
        conhecidas = {i.get("ideia") for i in itens}
        prox = max([int(i.get("n") or 0) for i in itens] or [0]) + 1
        for x in ideias or []:
            n = normalizar(x)
            if n and n["ideia"] not in conhecidas:
                itens.append(dict(n, n=prox, status="", imagem="", final="", erro="", da_ia=True))
                conhecidas.add(n["ideia"])
                prox += 1
        salvar(base, origem, pid, d)
        return d


def editar(base: str, origem: str, pid: str, n: int, **campos: Any) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(base, origem, pid)
        it = next((i for i in d.get("itens") or [] if int(i.get("n") or 0) == int(n)), None)
        if campos.get("novo"):
            prox = max([int(i.get("n") or 0) for i in d.get("itens") or []] or [0]) + 1
            nn = normalizar(campos) or {"ideia": "thumbnail", "texto": "", "prompt": ""}
            d.setdefault("itens", []).append(dict(nn, n=prox, status="", imagem="", final="", erro=""))
        elif campos.get("apagar") and it:
            d["itens"] = [i for i in d["itens"] if i is not it]
        elif it:
            for k, lim in (("texto", 40), ("prompt", 900), ("ideia", 400)):
                if k in campos:
                    it[k] = " ".join(str(campos[k] or "").split())[:lim]
            if "texto" in campos and it.get("imagem") and os.path.isfile(it["imagem"]):  # o texto mudou: refaz a final na hora
                it["final"] = compor(it["imagem"], it.get("texto") or "", it["imagem"].rsplit(".", 1)[0] + "_final.jpg")
        salvar(base, origem, pid, d)
        return d


def prompt_flow(it: Dict[str, Any], lado: str = "right") -> str:
    """A cena (prompt da IA, em inglês, ou a ideia) + o estilo de thumbnail."""
    cena = (it.get("prompt") or it.get("ideia") or "").strip().rstrip(".,")
    return f"{cena}. {ESTILO_PADRAO.format(lado=lado)}"


# ------------------------------------------------------------------ o texto por cima
def compor(imagem: str, texto: str, saida: str, W: int = 1280, H: int = 720) -> str:
    """1280×720: a imagem cobrindo a tela + o texto grande (contorno preto, sombra) no lado mais vazio."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat
    im = Image.open(imagem).convert("RGB")
    k = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * k + 0.5), int(im.height * k + 0.5)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x0, y0, x0 + W, y0 + H))
    texto = " ".join(str(texto or "").split()).upper()
    if texto:
        # o lado mais "calmo" (menos detalhe) recebe o texto
        g = im.convert("L").filter(ImageFilter.FIND_EDGES)
        esq = ImageStat.Stat(g.crop((0, 0, W // 2, H))).mean[0]
        dir_ = ImageStat.Stat(g.crop((W // 2, 0, W, H))).mean[0]
        lado_esq = esq <= dir_
        fonte = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "dp", "bebas-neue-Bold.ttf")
        palavras = texto.split()
        linhas = [" ".join(palavras[i:i + 2]) for i in range(0, len(palavras), 2)][:3]
        area_w = W * 0.46
        px = int(H * 0.26)
        while px > 30:
            f = ImageFont.truetype(fonte, px) if os.path.exists(fonte) else ImageFont.load_default()
            if max(f.getlength(l) for l in linhas) <= area_w and px * 0.95 * len(linhas) <= H * 0.8:
                break
            px = int(px * 0.92)
        d = ImageDraw.Draw(im)
        # um degradê escuro atrás do texto, pra ler em qualquer foto
        som = Image.new("L", (W, H), 0)
        ds = ImageDraw.Draw(som)
        for i in range(int(W * 0.55)):
            a = int(150 * (1 - i / (W * 0.55)) ** 1.6)
            xx = i if lado_esq else W - 1 - i
            ds.line([xx, 0, xx, H], fill=a)
        im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, som)
        d = ImageDraw.Draw(im)
        alt = px * 0.95 * len(linhas)
        y = (H - alt) / 2 + px * 0.8
        for i, l in enumerate(linhas):
            w = f.getlength(l)
            x = W * 0.05 if lado_esq else W * 0.95 - w
            cor = (255, 214, 0) if i == len(linhas) - 1 and len(linhas) > 1 else (255, 255, 255)
            d.text((x + px * 0.05, y + px * 0.06), l, font=f, fill=(0, 0, 0), anchor="ls")
            d.text((x, y), l, font=f, fill=cor, anchor="ls", stroke_width=max(2, px // 14), stroke_fill=(0, 0, 0))
            y += px * 0.95
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    im.save(saida, quality=92)
    return saida


# ------------------------------------------------------------------ gerar no Flow
def cliente_padrao():
    from googleflow.googleflow_client import GoogleFlowClient
    from site_config import load_site_config
    cfg = dict(load_site_config())
    cfg.update(orientation="16:9", flow_proporcao_imagem="16:9")
    return GoogleFlowClient(cfg)


def gerar(base: str, origem: str, pid: str, ns: Optional[List[int]] = None, forcar: bool = False,
          cliente: Any = None, log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Gera no Flow as thumbnails pedidas (ns = None: as que ainda não têm imagem). Uma de cada vez."""
    d = carregar(base, origem, pid)
    alvo = [i for i in d.get("itens") or [] if (ns is None and not i.get("imagem")) or (ns is not None and int(i["n"]) in ns)]
    if not alvo:
        log("Nada pra gerar — todas já têm imagem.")
        return d
    cliente = cliente or cliente_padrao()
    feitas = 0
    for k, it in enumerate(alvo, start=1):
        n = int(it["n"])
        editar_status(base, origem, pid, n, status="gerando", erro="")
        log(f"🎨 thumbnail {k}/{len(alvo)}: {it.get('ideia', '')[:80]}")
        try:
            fotos = cliente.gerar_imagem_prompt(prompt_flow(it), forcar=forcar or bool(it.get("imagem")))
            origem_img = next((f.local_path for f in fotos if getattr(f, "local_path", "") and os.path.isfile(f.local_path)), None)
            if not origem_img:
                raise ThumbErro("o Flow não devolveu a imagem")
            p = pasta(base, origem, pid)
            os.makedirs(p, exist_ok=True)
            destino = os.path.join(p, f"thumb_{n}_{int(time.time() * 1000)}{os.path.splitext(origem_img)[1] or '.png'}")
            shutil.copyfile(origem_img, destino)
            final = compor(destino, it.get("texto") or "", destino.rsplit(".", 1)[0] + "_final.jpg")
            editar_status(base, origem, pid, n, status="pronto", imagem=destino, final=final, erro="", prompt_usado=prompt_flow(it))
            feitas += 1
        except Exception as exc:  # noqa: BLE001 — uma que falha não para as outras
            editar_status(base, origem, pid, n, status="erro", erro=str(exc)[:300])
            log(f"✖ thumbnail {n}: {exc}")
    log(f"✅ {feitas} de {len(alvo)} thumbnail(s) gerada(s).")
    return carregar(base, origem, pid)


def editar_status(base: str, origem: str, pid: str, n: int, **campos: Any) -> None:
    with _TRAVA:
        d = carregar(base, origem, pid)
        for it in d.get("itens") or []:
            if int(it.get("n") or 0) == int(n):
                it.update(campos)
        salvar(base, origem, pid, d)


def iniciar(base: str, origem: str, pid: str, ns: Optional[List[int]] = None, forcar: bool = False, pagina: str = "",
            cliente_fn: Optional[Callable[[], Any]] = None) -> str:
    """Em segundo plano (🔔 avisa quando terminar). Devolve o id da tarefa."""
    import tarefas_bg
    for it in carregar(base, origem, pid).get("itens") or []:
        if (ns is None and not it.get("imagem")) or (ns is not None and int(it["n"]) in ns):
            editar_status(base, origem, pid, int(it["n"]), status="fila", erro="")
    return tarefas_bg.iniciar("thumbs_flow", "🖼 Thumbnails no Google Flow",
                              lambda t: gerar(base, origem, pid, ns, forcar, (cliente_fn or cliente_padrao)(), t.progresso),
                              pagina=pagina)


def para_json(d: Dict[str, Any], url_base: str) -> Dict[str, Any]:
    """Pra página: sem caminhos do disco, com as URLs."""
    out = []
    for it in d.get("itens") or []:
        x = {k: it.get(k) for k in ("n", "ideia", "texto", "prompt", "status", "erro", "da_ia")}
        x["url_imagem"] = f"{url_base}/{it['n']}/imagem?v={int(os.path.getmtime(it['imagem']))}" if it.get("imagem") and os.path.isfile(it["imagem"]) else ""
        x["url_final"] = f"{url_base}/{it['n']}/final?v={int(os.path.getmtime(it['final']))}" if it.get("final") and os.path.isfile(it["final"]) else ""
        out.append(x)
    return {"itens": out}


# ------------------------------------------------------------------ pra pôr nos prompts
BLOCO_PROMPT = (
    "THUMBNAILS: em \"thumbnails\", sugira 3 thumbnails diferentes pro vídeo, cada uma com: \"ideia\" (o que mostra e por que dá "
    "clique, em 1 frase), \"texto\" (2 a 4 palavras GRANDES na miniatura, no idioma do vídeo, que completam o título sem repeti-lo) "
    "e \"prompt\" (a cena da imagem EM INGLÊS pra um gerador de imagem: um assunto principal claro, expressão/ação, lugar, luz, "
    "enquadramento — sem pedir texto escrito na imagem, sem violência gráfica). A imagem vai ser gerada no Google Flow e o texto "
    "entra por cima.")
EXEMPLO_JSON = [{"ideia": "o que a thumbnail mostra e por que dá clique", "texto": "2-4 PALAVRAS",
                 "prompt": "in English: the image scene for an AI image generator (no text in the image)"}]
