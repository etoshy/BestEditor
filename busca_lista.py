"""busca_lista.py — 🗂 Busca em lista (v84_293).

Cola uma LISTA de termos (um por linha). O site pesquisa cada termo nos buscadores de imagem que o site já tem
(Brave por padrão; também Google pelo Modo IA, Bing, Yandex e Startpage — os mesmos de `buscador_imagens_unificado`),
baixa N fotos por termo e dá o nome do termo ao arquivo (ex.: `binions_horseshoe_1990s_01.jpg`). Você pode renomear
cada foto, apagar as ruins, buscar mais de um termo só, e também ENVIAR fotos e vídeos do PC (renomeando ou não).

Dois jeitos de buscar:
  🧲 GUIAS (o jeito das outras ferramentas): o site abre o Google Imagens no navegador do site (o Brave com o userscript
     "Capturar links"), uma guia por termo, N de cada vez. Em cada guia você marca as fotos certas e clica em "Capturar e
     enviar ao site" → elas chegam aqui já com o nome do termo. "➡ Próximas guias" fecha as prontas e abre os próximos.
  🤖 AUTOMÁTICO: o site pesquisa sozinho (Brave/Bing/Yandex/Startpage/Google Modo IA) e baixa as N primeiras.

No fim: ⬇ um ZIP com todos os arquivos + `lista.txt` (arquivo → busca, buscador, página de origem e link da imagem).

Pasta: <BASE>/busca_lista/<id>/  (arquivos/, projeto.json)
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import threading
import time
import unicodedata
import uuid
import zipfile
from typing import Any, Callable, Dict, List, Optional

import arquivo_seguro

TAREFAS: Dict[str, Dict[str, Any]] = {}
TRAVA = threading.Lock()

MOTORES = {"brave": "Brave", "google": "Google (Modo IA)", "bing": "Bing", "yandex": "Yandex", "startpage": "Startpage"}
MOTORES_PADRAO = ["brave"]
EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".heic", ".heif", ".tif", ".tiff"}
EXT_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts", ".wmv", ".flv"}
ORIENTACOES = {"any": "qualquer", "horizontal": "horizontal", "vertical": "vertical", "square": "quadrada"}


class ListaErro(Exception):
    pass


# ---------------------------------------------------------------------------------------------------- projeto
def raiz(base: str) -> str:
    return os.environ.get("BUSCA_LISTA_DIR") or os.path.join(base, "busca_lista")


def pasta(base: str, pid: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{10}", pid or ""):
        raise ListaErro("projeto inválido")
    return os.path.join(raiz(base), pid)


def pasta_arq(base: str, pid: str) -> str:
    return os.path.join(pasta(base, pid), "arquivos")


def carregar(base: str, pid: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(base, pid), "projeto.json")
    if not os.path.isfile(cam):
        raise ListaErro("projeto não existe")
    with open(cam, encoding="utf-8") as f:
        return json.load(f)


def salvar(base: str, p: Dict[str, Any]) -> None:
    os.makedirs(pasta(base, p["id"]), exist_ok=True)
    arquivo_seguro.gravar_json(os.path.join(pasta(base, p["id"]), "projeto.json"), p)


def novo(base: str, titulo: str = "") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    p = {"id": pid, "titulo": (titulo or "").strip()[:120] or time.strftime("Busca %d/%m %H:%M"), "criado": time.time(),
         "termos": [], "config": {"motores": list(MOTORES_PADRAO), "qtd": 4, "orientacao": "any", "modo": "completar",
                                  "mostrar": False}, "itens": []}
    os.makedirs(pasta_arq(base, pid), exist_ok=True)
    salvar(base, p)
    return p


def listar(base: str) -> List[Dict[str, Any]]:
    r = raiz(base)
    out = []
    for nome in os.listdir(r) if os.path.isdir(r) else []:
        try:
            p = carregar(base, nome)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": p["id"], "titulo": p["titulo"], "criado": p.get("criado") or 0, "termos": len(p.get("termos") or []),
                    "n": len(p.get("itens") or [])})
    return sorted(out, key=lambda x: -x["criado"])


def apagar_projeto(base: str, pid: str) -> None:
    import shutil
    shutil.rmtree(pasta(base, pid), ignore_errors=True)


# ---------------------------------------------------------------------------------------------------- nomes
def slug(texto: str, max_len: int = 60) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\- ]+", " ", t).strip().lower()
    t = re.sub(r"[\s\-]+", "_", t).strip("_")
    return (t[:max_len].strip("_")) or "arquivo"


def nome_limpo(nome: str) -> str:
    """Nome escolhido pela pessoa → seguro pra arquivo (sem a extensão). Mantém maiúsculas e acentos viram letra simples."""
    t = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\-. ]+", " ", t).strip()
    t = re.sub(r"\s+", "_", t).strip("._")
    return t[:100] or "arquivo"


def nome_livre(pasta_a: str, stem: str, ext: str, ignorar: str = "") -> str:
    ext = ext.lower()
    cand, k = stem + ext, 2
    while os.path.exists(os.path.join(pasta_a, cand)) and cand != ignorar:
        cand, k = f"{stem}_{k}{ext}", k + 1
    return cand


def proximo_numerado(pasta_a: str, stem: str, ext: str = ".jpg") -> str:
    k = 1
    while True:
        cand = f"{stem}_{k:02d}{ext}"
        if not any(os.path.exists(os.path.join(pasta_a, cand[:-len(ext)] + e)) for e in (ext, ".jpg", ".png", ".webp")):
            return cand
        k += 1


def tipo_por_ext(nome: str) -> Optional[str]:
    e = os.path.splitext(nome)[1].lower()
    return "foto" if e in EXT_FOTO else "video" if e in EXT_VIDEO else None


def termos_do_texto(texto: str) -> List[str]:
    """Um termo por linha (também aceita ; ). Tira numeração/marcadores do começo ("1.", "-", "•") e repetidos."""
    out: List[str] = []
    for linha in re.split(r"[\r\n;]+", texto or ""):
        t = re.sub(r"^\s*(?:[-*•·]+|\d{1,3}[.)\-:]|\d{1,3}\s+-)\s*", "", linha).strip().strip('"').strip()
        t = " ".join(t.split())[:150]
        if t and t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out[:300]


# ---------------------------------------------------------------------------------------------------- busca
def _bu():
    import sys
    tk = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    import buscador_imagens_unificado as bu
    return bu


def buscar(base: str, pid: str, termos: List[str], prog: Callable[[Dict[str, Any]], None] = lambda e: None,
           parar: Callable[[], bool] = lambda: False) -> Dict[str, Any]:
    """Pesquisa os termos (um navegador por buscador, todos os termos na mesma aba) e baixa as fotos.
    modo "completar": pega `qtd` por termo, indo pro próximo buscador só no que faltou.
    modo "cada": pega `qtd` de CADA buscador marcado."""
    bu = _bu()
    with TRAVA:
        p = carregar(base, pid)
    cfg = p.get("config") or {}
    motores = [m for m in (cfg.get("motores") or MOTORES_PADRAO) if m in MOTORES] or list(MOTORES_PADRAO)
    qtd = max(1, min(30, int(cfg.get("qtd") or 4)))
    orient = cfg.get("orientacao") if cfg.get("orientacao") in ORIENTACOES else "any"
    modo = "cada" if cfg.get("modo") == "cada" else "completar"
    headless = not bool(cfg.get("mostrar"))
    pa = pasta_arq(base, pid)
    os.makedirs(pa, exist_ok=True)
    termos = [t for t in termos if t]
    ja_urls = {i.get("url") for i in p.get("itens") or [] if i.get("url")}
    assin = []
    for i in p.get("itens") or []:
        if i.get("tipo") == "foto":
            try:
                assin.append(bu.assinatura_visual(os.path.join(pa, i["arq"])))
            except Exception:  # noqa: BLE001
                pass
    falta = {t: qtd for t in termos}
    feitos = {t: 0 for t in termos}
    est = {"termos": {t: {"st": "fila", "fotos": 0, "erro": ""} for t in termos}, "passo": 0,
           "passos": len(termos) * len(motores), "msg": "começando…"}
    prog(est)
    novos: List[Dict[str, Any]] = []
    for motor in motores:
        if parar():
            break
        alvo = [t for t in termos if falta[t] > 0] if modo == "completar" else list(termos)
        if not alvo:
            break
        for t in alvo:
            est["termos"][t]["st"] = f"🔎 {MOTORES[motor]}"
        est["msg"] = f"🔎 {MOTORES[motor]}: pesquisando {len(alvo)} termo(s)…"
        prog(est)
        quer = {t: (falta[t] if modo == "completar" else qtd) for t in alvo}
        try:
            r = bu.buscar_lote(motor, alvo, limit=max(quer.values()) + 4, headless=headless, orientation=orient)
        except Exception as exc:  # noqa: BLE001
            r = {"por_termo": {}, "erros": {t: str(exc) for t in alvo}, "erro_geral": str(exc)}
        por_norm = {bu._norm(k): v for k, v in (r.get("por_termo") or {}).items()}
        erros_norm = {bu._norm(k): v for k, v in (r.get("erros") or {}).items()}
        for t in alvo:
            if parar():
                break
            cands = por_norm.get(bu._norm(t)) or []
            pegou = 0
            est["termos"][t]["st"] = f"⬇ {MOTORES[motor]}"
            prog(est)
            for img in cands:
                if pegou >= quer[t]:
                    break
                if img.original_url and img.original_url in ja_urls:
                    continue
                stem = proximo_numerado(pa, slug(t))[:-4]
                try:
                    cam = bu.baixar_imagem(img, pa, stem=stem, timeout_s=40)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    a = bu.assinatura_visual(cam)
                except Exception:  # noqa: BLE001
                    a = None
                if a is not None and any(bu.parecidas(a, b) for b in assin if b is not None):
                    os.remove(cam)  # a mesma foto (outro link) — fica de fora
                    continue
                assin.append(a)
                ja_urls.add(img.original_url)
                w = h = None
                try:
                    from PIL import Image
                    with Image.open(cam) as im:
                        w, h = im.size
                except Exception:  # noqa: BLE001
                    pass
                item = {"id": uuid.uuid4().hex[:8], "arq": os.path.basename(cam), "tipo": "foto", "origem": "busca",
                        "termo": t, "motor": motor, "url": img.original_url or "", "pagina": img.source_page or "",
                        "titulo": (img.title or "")[:200], "w": w, "h": h, "usar": True, "quando": time.time()}
                novos.append(item)
                with TRAVA:
                    q = carregar(base, pid)
                    q.setdefault("itens", []).append(item)
                    salvar(base, q)
                pegou += 1
                feitos[t] += 1
                est["termos"][t]["fotos"] = feitos[t]
                prog(est)
            if modo == "completar":
                falta[t] = max(0, falta[t] - pegou)
            if not pegou and not feitos[t]:
                est["termos"][t]["erro"] = (erros_norm.get(bu._norm(t)) or "nada baixou")[:200]
            est["passo"] += 1
            est["termos"][t]["st"] = "✅" if (falta[t] == 0 if modo == "completar" else feitos[t]) else "…"
            prog(est)
    for t in termos:
        if not feitos[t]:
            est["termos"][t]["st"] = "❌"
        elif modo == "completar" and falta[t]:
            est["termos"][t]["st"] = f"⚠ {feitos[t]}/{qtd}"
        else:
            est["termos"][t]["st"] = "✅"
    est["msg"] = f"pronto: {len(novos)} foto(s) de {len(termos)} termo(s)"
    est["passo"] = est["passos"]
    prog(est)
    return {"novos": len(novos), "estado": est}


# ---------------------------------------------------------------------------------------------------- 🧲 guias
def termo_id(termo: str) -> str:
    return "t" + hashlib.md5(" ".join(str(termo).split()).lower().encode()).hexdigest()[:8]


def termo_por_id(p: Dict[str, Any], tid: str) -> Optional[str]:
    return next((t for t in p.get("termos") or [] if termo_id(t) == tid), None)


def destino(site: str, pid: str, termo: str) -> str:
    d = {"u": site.rstrip("/"), "p": pid, "q": termo_id(termo), "r": "🗂 " + termo[:110], "m": "lista"}
    return base64.urlsafe_b64encode(json.dumps(d, ensure_ascii=False).encode()).decode().rstrip("=")


def tem_foto(p: Dict[str, Any], termo: str) -> bool:
    return any(i.get("termo") == termo for i in p.get("itens") or [])


def proximos(p: Dict[str, Any], quantas: int = 5, so: Optional[List[str]] = None) -> List[str]:
    """Os próximos termos pra abrir guia: sem foto ainda e sem guia aberta/vazia (ou os pedidos)."""
    if so:
        return [t for t in p.get("termos") or [] if t in so or termo_id(t) in so][:20]
    g = p.get("guias") or {}
    fila = [t for t in p.get("termos") or [] if not tem_foto(p, t) and g.get(termo_id(t)) not in ("aberta", "vazia")]
    return fila[:max(1, min(10, int(quantas or 5)))]


def abrir_guias(base: str, pid: str, site: str, quantas: int = 5, trocar: bool = False, so: Optional[List[str]] = None,
                reabrir: bool = False, cfg: Optional[Dict[str, Any]] = None, sem_navegador: bool = False) -> Dict[str, Any]:
    import navegador_imagens as ni
    if cfg is None:
        from site_config import load_site_config
        cfg = load_site_config()
    troca = ni.fechar_terminadas(pid, cfg) if trocar else {"fechadas": [], "mantidas": []}
    with TRAVA:
        p = carregar(base, pid)
        g = p.setdefault("guias", {})
        fech = set(troca["fechadas"])
        for t in p.get("termos") or []:
            k = termo_id(t)
            if k in fech:  # guia fechada: sem foto = não achou (fica marcado, dá pra reabrir)
                g[k] = "feita" if tem_foto(p, t) else "vazia"
        if reabrir:
            for k in list(g):
                if g[k] in ("aberta", "vazia"):
                    g.pop(k)
        termos = proximos(p, quantas, so)
        if not termos:
            salvar(base, p)
            return {"ok": True, "abertas": 0, "fechadas": len(fech), "mantidas": troca["mantidas"],
                    "msg": "Nenhum termo pendente (todos com foto, sem resultado ou com guia aberta)."}
        urls = [ni.url_google(t, destino(site, pid, t)) for t in termos]
        r = {"ok": True, "confirmadas": list(range(len(urls)))} if sem_navegador else \
            ni.abrir(base, urls, cfg, chaves=[termo_id(t) for t in termos], pid=pid)
        conf = set(r.get("confirmadas") or [])
        for k, t in enumerate(termos):
            if k in conf:
                g[termo_id(t)] = "aberta"
        salvar(base, p)
    if not r.get("ok"):
        return {"ok": False, "erro": r.get("erro"), "urls": urls}
    faltam = len(proximos(carregar(base, pid), 999))
    return {"ok": True, "abertas": len(conf), "navegador": r.get("navegador"), "faltam": faltam, "urls": urls,
            "fechadas": len(fech), "mantidas": troca["mantidas"], "aviso": r.get("aviso") or ""}


def _bytes_para_arquivo(dados: bytes, pa: str, stem: str) -> str:
    from PIL import Image
    if not dados or len(dados) > 40 * 1024 * 1024:
        raise ListaErro("imagem vazia ou grande demais")
    try:
        im = Image.open(io.BytesIO(dados))
        fmt = (im.format or "").lower()
    except Exception:  # noqa: BLE001
        raise ListaErro("o que veio não é uma imagem")
    ext = {"jpeg": ".jpg", "png": ".png", "gif": ".gif"}.get(fmt)
    if not ext:  # webp/avif/bmp… viram jpg (abre em qualquer editor)
        cam = os.path.join(pa, stem + ".jpg")
        im.convert("RGB").save(cam, quality=93)
        return cam
    cam = os.path.join(pa, stem + ext)
    with open(cam, "wb") as fh:
        fh.write(dados)
    return cam


def _baixar_url(url: str, pa: str, stem: str) -> tuple:
    """→ (caminho, tipo, pagina_og). Link direto (foto/vídeo) → baixador dos buscadores → foto principal da página."""
    import vendas as vd
    if not url.lower().startswith(("http://", "https://")):
        raise ListaErro("o link tem que começar com http:// ou https://")
    try:
        cam, tipo = vd.baixar_arquivo(url, pa, stem)
        return cam, tipo, None
    except Exception as exc:  # noqa: BLE001
        erro1 = str(exc)
    try:
        bu = _bu()
        im = bu.ImagemBuscador(title="", description="", source_page="", original_url=url, thumbnail_url="",
                               width=None, height=None, query="", engine="")
        return bu.baixar_imagem(im, pa, stem=stem, timeout_s=40), "foto", None
    except Exception:  # noqa: BLE001
        pass
    try:
        html, final = vd.baixar_html(url, navegador=False)
        og = vd.ler_og(html, final)
    except Exception:  # noqa: BLE001
        raise ListaErro(f"não consegui baixar ({erro1[:120]})")
    for u in (og.get("imagem"), og.get("video")):
        if u:
            try:
                cam, tipo = vd.baixar_arquivo(u, pa, stem)
                return cam, tipo, url
            except Exception:  # noqa: BLE001
                continue
    raise ListaErro("a página não tem imagem principal")


def receber_link(base: str, pid: str, tid: str, url: str = "", dados_b64: str = "", pagina: str = "") -> Dict[str, Any]:
    """🧲 Uma foto que o userscript mandou da guia do termo `tid`. Fica com o nome do termo (termo_01.jpg…)."""
    p = carregar(base, pid)
    termo = termo_por_id(p, tid) or ""
    pa = pasta_arq(base, pid)
    os.makedirs(pa, exist_ok=True)
    url = (url or "").strip()
    if url and any(i.get("url") == url for i in p.get("itens") or []):
        raise ListaErro("essa imagem já está na lista")
    with TRAVA:  # reserva o nome (duas guias podem mandar ao mesmo tempo)
        stem = proximo_numerado(pa, slug(termo or "google"))[:-4]
        open(os.path.join(pa, stem + ".part"), "w").close()
    try:
        if dados_b64:
            cam, tipo, og = _bytes_para_arquivo(base64.b64decode(str(dados_b64).split(",")[-1]), pa, stem), "foto", None
        else:
            cam, tipo, og = _baixar_url(url, pa, stem)
    finally:
        try:
            os.remove(os.path.join(pa, stem + ".part"))
        except OSError:
            pass
    if tipo == "foto":
        try:
            cam = _bu().converter_para_jpg(cam)
        except Exception:  # noqa: BLE001
            pass
    w = h = None
    if tipo == "foto":
        try:
            from PIL import Image
            with Image.open(cam) as im:
                w, h = im.size
        except Exception:  # noqa: BLE001
            pass
    item = {"id": uuid.uuid4().hex[:8], "arq": os.path.basename(cam), "tipo": tipo, "origem": "guia", "termo": termo,
            "motor": "google", "url": url, "pagina": pagina or og or "", "titulo": "", "w": w, "h": h, "usar": True,
            "quando": time.time()}
    with TRAVA:
        q = carregar(base, pid)
        q.setdefault("itens", []).append(item)
        if termo:
            q.setdefault("guias", {})[tid] = "feita"
        salvar(base, q)
    return item


def guia_feita(base: str, pid: str, tid: str, enviadas: int) -> None:
    with TRAVA:
        p = carregar(base, pid)
        t = termo_por_id(p, tid)
        if t:
            p.setdefault("guias", {})[tid] = "feita" if (enviadas or tem_foto(p, t)) else "vazia"
            salvar(base, p)


# ---------------------------------------------------------------------------------------------------- itens
def _item(p: Dict[str, Any], iid: str) -> Dict[str, Any]:
    for i in p.get("itens") or []:
        if i["id"] == iid:
            return i
    raise ListaErro("arquivo não existe")


def renomear(base: str, pid: str, iid: str, nome: str) -> Dict[str, Any]:
    with TRAVA:
        p = carregar(base, pid)
        i = _item(p, iid)
        pa = pasta_arq(base, pid)
        ext = os.path.splitext(i["arq"])[1]
        stem = nome_limpo(os.path.splitext(nome)[0] if os.path.splitext(nome)[1].lower() == ext.lower() else nome)
        novo_arq = nome_livre(pa, stem, ext, ignorar=i["arq"])
        if novo_arq != i["arq"]:
            os.replace(os.path.join(pa, i["arq"]), os.path.join(pa, novo_arq))
            i["arq"] = novo_arq
        salvar(base, p)
        return i


def renomear_por_termo(base: str, pid: str) -> int:
    """Renomeia as fotos da busca pra `<termo>_01`, `_02`… (na ordem), útil depois de apagar algumas."""
    n = 0
    with TRAVA:
        p = carregar(base, pid)
        pa = pasta_arq(base, pid)
        por: Dict[str, List[Dict[str, Any]]] = {}
        for i in p.get("itens") or []:
            if i.get("termo") and i.get("origem") in ("busca", "guia"):
                por.setdefault(i["termo"], []).append(i)
        for t, its in por.items():
            tmp = []
            for i in its:  # 1º pra nomes temporários (evita colisão ao trocar a ordem)
                tn = f"__tmp_{i['id']}{os.path.splitext(i['arq'])[1]}"
                os.replace(os.path.join(pa, i["arq"]), os.path.join(pa, tn))
                tmp.append((i, tn))
            for k, (i, tn) in enumerate(tmp, 1):
                ext = os.path.splitext(tn)[1]
                novo_arq = nome_livre(pa, f"{slug(t)}_{k:02d}", ext)
                os.replace(os.path.join(pa, tn), os.path.join(pa, novo_arq))
                n += novo_arq != i["arq"]
                i["arq"] = novo_arq
        salvar(base, p)
    return n


def apagar_item(base: str, pid: str, iid: str) -> None:
    with TRAVA:
        p = carregar(base, pid)
        i = _item(p, iid)
        try:
            os.remove(os.path.join(pasta_arq(base, pid), i["arq"]))
        except OSError:
            pass
        p["itens"] = [x for x in p["itens"] if x["id"] != iid]
        salvar(base, p)


def editar_item(base: str, pid: str, iid: str, campos: Dict[str, Any]) -> Dict[str, Any]:
    with TRAVA:
        p = carregar(base, pid)
        i = _item(p, iid)
        if "usar" in campos:
            i["usar"] = bool(campos["usar"])
        if "nota" in campos:
            i["nota"] = str(campos["nota"] or "")[:300]
        if "termo" in campos and i.get("origem") == "pc":
            i["termo"] = str(campos["termo"] or "")[:150]
        salvar(base, p)
        return i


def enviar(base: str, pid: str, arquivo, nome: str = "", termo: str = "") -> Dict[str, Any]:
    """Foto ou vídeo do PC. `nome` vazio = mantém o nome original."""
    orig = os.path.basename(arquivo.filename or "")
    tipo = tipo_por_ext(orig)
    if not tipo:
        raise ListaErro(f"{orig}: formato não aceito (foto ou vídeo)")
    pa = pasta_arq(base, pid)
    os.makedirs(pa, exist_ok=True)
    ext = os.path.splitext(orig)[1].lower()
    stem = nome_limpo(os.path.splitext(nome)[0] if nome.strip() else os.path.splitext(orig)[0])
    with TRAVA:
        arq = nome_livre(pa, stem, ext)
        arquivo.save(os.path.join(pa, arq))
        cam = os.path.join(pa, arq)
        w = h = None
        if tipo == "foto":
            try:
                from PIL import Image
                with Image.open(cam) as im:
                    w, h = im.size
            except Exception:  # noqa: BLE001
                pass
        item = {"id": uuid.uuid4().hex[:8], "arq": arq, "tipo": tipo, "origem": "pc", "termo": (termo or "").strip()[:150],
                "motor": "", "url": "", "pagina": "", "titulo": orig, "w": w, "h": h, "usar": True, "quando": time.time()}
        p = carregar(base, pid)
        p.setdefault("itens", []).append(item)
        salvar(base, p)
    return item


# ---------------------------------------------------------------------------------------------------- lista + zip
def lista_texto(p: Dict[str, Any], so_marcados: bool = True) -> str:
    itens = [i for i in p.get("itens") or [] if i.get("usar", True) or not so_marcados]
    linhas = [f"{p['titulo']}", f"{len(itens)} arquivo(s) · gerado em {time.strftime('%d/%m/%Y %H:%M')}", ""]
    ordem = [t for t in p.get("termos") or []]
    for i in itens:
        if i.get("termo") and i["termo"] not in ordem:
            ordem.append(i["termo"])
    grupos = [(t, [i for i in itens if i.get("termo") == t]) for t in ordem]
    soltos = [i for i in itens if not i.get("termo")]
    if soltos:
        grupos.append(("(enviados do PC)", soltos))
    for t, its in grupos:
        if not its:
            continue
        linhas.append(f"=== {t} ===")
        for i in its:
            linhas.append(f"{i['arq']}")
            if i.get("origem") in ("busca", "guia"):
                linhas.append(f"    busca: {i.get('termo')}  ·  buscador: {MOTORES.get(i.get('motor'), i.get('motor'))}"
                              + ("  ·  escolhida na guia" if i.get("origem") == "guia" else ""))
                if i.get("pagina"):
                    linhas.append(f"    página: {i['pagina']}")
                if i.get("url"):
                    linhas.append(f"    imagem: {i['url']}")
            else:
                linhas.append(f"    enviado do PC (original: {i.get('titulo')})")
            if i.get("w"):
                linhas.append(f"    tamanho: {i['w']}x{i['h']}")
            if i.get("nota"):
                linhas.append(f"    nota: {i['nota']}")
        linhas.append("")
    falhou = [t for t in p.get("termos") or [] if not any(i.get("termo") == t for i in p.get("itens") or [])]
    if falhou:
        linhas += ["=== sem resultado ===", *falhou, ""]
    return "\n".join(linhas)


def zip_bytes(base: str, pid: str, so_marcados: bool = True) -> bytes:
    p = carregar(base, pid)
    pa = pasta_arq(base, pid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i in p.get("itens") or []:
            if so_marcados and not i.get("usar", True):
                continue
            cam = os.path.join(pa, i["arq"])
            if os.path.isfile(cam):
                z.write(cam, i["arq"])
        z.writestr("lista.txt", lista_texto(p, so_marcados))
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------------- rotas
def registrar(app, base: str) -> None:
    from flask import abort, jsonify, redirect, render_template, request, send_file, send_from_directory

    def _ok(**kw):
        return jsonify(dict(ok=True, **kw))

    def _erro(msg, cod=400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    def _p(pid):
        try:
            return carregar(base, pid)
        except ListaErro:
            abort(404)

    def _rodando(pid):
        t = TAREFAS.get(pid)
        return bool(t and not t.get("fim"))

    @app.route("/busca-lista")
    def bl_lista():
        return render_template("busca_lista.html", p=None, projetos=listar(base), motores=MOTORES, orientacoes=ORIENTACOES)

    @app.route("/busca-lista/novo", methods=["POST"])
    def bl_novo():
        p = novo(base, request.form.get("titulo") or "")
        txt = request.form.get("termos") or ""
        if txt.strip():
            p["termos"] = termos_do_texto(txt)
            salvar(base, p)
        return redirect(f"/busca-lista/{p['id']}")

    @app.route("/busca-lista/<pid>")
    def bl_projeto(pid):
        return render_template("busca_lista.html", p=_p(pid), projetos=[], motores=MOTORES, orientacoes=ORIENTACOES)

    @app.route("/busca-lista/<pid>/estado")
    def bl_estado(pid):
        p = _p(pid)
        t = TAREFAS.get(pid)
        g = p.get("guias") or {}
        info = [{"termo": x, "id": termo_id(x), "fotos": sum(1 for i in p.get("itens") or [] if i.get("termo") == x),
                 "guia": g.get(termo_id(x)) or ""} for x in p.get("termos") or []]
        return _ok(projeto=p, termos=info, tarefa=dict(t, rodando=not t.get("fim")) if t else None)

    @app.route("/busca-lista/<pid>/config", methods=["POST"])
    def bl_config(pid):
        c = request.get_json(silent=True) or {}
        with TRAVA:
            p = _p(pid)
            cfg = p.setdefault("config", {})
            if "titulo" in c:
                p["titulo"] = str(c["titulo"] or "").strip()[:120] or p["titulo"]
            if "termos" in c:
                p["termos"] = termos_do_texto(c["termos"] if isinstance(c["termos"], str) else "\n".join(c["termos"]))
            if "motores" in c:
                cfg["motores"] = [m for m in c["motores"] if m in MOTORES] or list(MOTORES_PADRAO)
            if "qtd" in c:
                cfg["qtd"] = max(1, min(30, int(c["qtd"] or 4)))
            if c.get("orientacao") in ORIENTACOES:
                cfg["orientacao"] = c["orientacao"]
            if c.get("modo") in ("completar", "cada"):
                cfg["modo"] = c["modo"]
            if "mostrar" in c:
                cfg["mostrar"] = bool(c["mostrar"])
            salvar(base, p)
        return _ok(projeto=p)

    @app.route("/busca-lista/<pid>/buscar", methods=["POST"])
    def bl_buscar(pid):
        p = _p(pid)
        if _rodando(pid):
            return _erro("já tem uma busca rodando")
        c = request.get_json(silent=True) or {}
        termos = c.get("termos")
        if isinstance(termos, str):
            termos = termos_do_texto(termos)
        if not termos:
            termos = list(p.get("termos") or [])
            if c.get("so_faltando"):
                termos = [t for t in termos if not any(i.get("termo") == t for i in p.get("itens") or [])]
        if not termos:
            return _erro("cole pelo menos um termo")
        with TRAVA:  # termos novos (ex.: "buscar mais" de um termo digitado) entram na lista
            q = carregar(base, pid)
            for t in termos:
                if t not in q["termos"]:
                    q["termos"].append(t)
            salvar(base, q)
        TAREFAS[pid] = {"inicio": time.time(), "fim": None, "erro": None, "estado": {}, "parar": False}

        def corpo():
            try:
                buscar(base, pid, termos, prog=lambda e: TAREFAS[pid].__setitem__("estado", json.loads(json.dumps(e))),
                       parar=lambda: TAREFAS[pid].get("parar"))
            except Exception as exc:  # noqa: BLE001
                TAREFAS[pid]["erro"] = f"{type(exc).__name__}: {exc}"[:500]
            finally:
                TAREFAS[pid]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True, name="busca-lista:" + pid).start()
        return _ok()

    @app.route("/busca-lista/<pid>/parar", methods=["POST"])
    def bl_parar(pid):
        if pid in TAREFAS:
            TAREFAS[pid]["parar"] = True
        return _ok()

    @app.route("/busca-lista/<pid>/enviar", methods=["POST"])
    def bl_enviar(pid):
        _p(pid)
        nomes = request.form.getlist("nomes")
        termo = request.form.get("termo") or ""
        feitos, erros = [], []
        for k, arq in enumerate(request.files.getlist("arquivos")):
            if not arq or not arq.filename:
                continue
            try:
                feitos.append(enviar(base, pid, arq, nomes[k] if k < len(nomes) else "", termo))
            except ListaErro as exc:
                erros.append(str(exc))
        return _ok(itens=feitos, erros=erros)

    @app.route("/busca-lista/<pid>/item/<iid>", methods=["POST", "DELETE"])
    def bl_item(pid, iid):
        _p(pid)
        try:
            if request.method == "DELETE":
                apagar_item(base, pid, iid)
                return _ok()
            c = request.get_json(silent=True) or {}
            i = renomear(base, pid, iid, c["nome"]) if (c.get("nome") or "").strip() else None
            i = editar_item(base, pid, iid, c) if any(k in c for k in ("usar", "nota", "termo")) else i
            return _ok(item=i)
        except ListaErro as exc:
            return _erro(exc)

    @app.route("/busca-lista/<pid>/renomear-por-termo", methods=["POST"])
    def bl_ren_termo(pid):
        _p(pid)
        return _ok(n=renomear_por_termo(base, pid))

    @app.route("/busca-lista/<pid>/arquivo/<path:nome>")
    def bl_arquivo(pid, nome):
        _p(pid)
        return send_from_directory(pasta_arq(base, pid), nome)

    @app.route("/busca-lista/<pid>/lista.txt")
    def bl_txt(pid):
        p = _p(pid)
        return app.response_class(lista_texto(p, request.args.get("todos") != "1"), mimetype="text/plain; charset=utf-8")

    @app.route("/busca-lista/<pid>/zip")
    def bl_zip(pid):
        p = _p(pid)
        dados = zip_bytes(base, pid, request.args.get("todos") != "1")
        return send_file(io.BytesIO(dados), mimetype="application/zip", as_attachment=True,
                         download_name=slug(p["titulo"]) + ".zip")

    # ---- 🧲 guias no navegador do site (o userscript manda pra cá: /link, /guia-feita, /guias)
    def _corpo():
        c = request.get_json(silent=True, force=True)
        if c is None:
            try:
                c = json.loads(request.get_data(as_text=True) or "{}")
            except ValueError:
                c = {}
        return c or {}

    @app.route("/busca-lista/<pid>/guias", methods=["POST"])
    def bl_guias(pid):
        _p(pid)
        c = _corpo()
        r = abrir_guias(base, pid, request.host_url.rstrip("/"), int(c.get("quantas") or 5), bool(c.get("trocar")),
                        [str(x) for x in c.get("termos") or []] or None, bool(c.get("reabrir")),
                        sem_navegador=bool(c.get("sem_navegador")))
        return jsonify(r), (200 if r.get("ok") else 400)

    @app.route("/busca-lista/<pid>/link", methods=["POST"])
    def bl_link(pid):
        _p(pid)
        c = _corpo()
        try:
            i = receber_link(base, pid, str(c.get("pergunta") or "")[:20], str(c.get("url") or ""), str(c.get("dados_b64") or ""),
                             str(c.get("pagina") or ""))
        except ListaErro as exc:
            if "já está na lista" in str(exc):
                return _ok(repetida=True)
            return _erro(exc)
        except Exception as exc:  # noqa: BLE001
            return _erro(f"não consegui baixar ({str(exc)[:120]})")
        return _ok(item=i)

    @app.route("/busca-lista/<pid>/guia-feita", methods=["POST"])
    def bl_guia_feita(pid):
        _p(pid)
        c = _corpo()
        guia_feita(base, pid, str(c.get("pergunta") or "")[:20], int(c.get("enviadas") or 0))
        return _ok()

    @app.after_request
    def _cors_lista(resp):  # o script no Google manda direto pra cá (sem GM_xmlhttpRequest: fetch)
        if request.path.startswith("/busca-lista/") and request.path.rsplit("/", 1)[-1] in ("link", "guia-feita", "guias"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp

    @app.route("/busca-lista/<pid>/apagar", methods=["POST"])
    def bl_apagar(pid):
        _p(pid)
        apagar_projeto(base, pid)
        return redirect("/busca-lista")
