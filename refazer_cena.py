"""
🎬 v84_408 — REFAZER CENA (só Google Flow): a mesma cena, com outros personagens, outro cenário e/ou outras falas.

  1. Você manda o vídeo da cena → o site acha os cortes (planos; mais de 8 s vira dois, que é o tamanho de um vídeo do
     Veo) e tira o primeiro quadro de cada plano. O Whisper ouve as falas.
  2. 🤖 A IA olha 3 quadros de cada plano + as falas e escreve: quem é cada pessoa da cena (A, B, C… — as mesmas em
     todos os planos), o cenário, e em cada plano onde cada pessoa está, a ação e o movimento da câmera.
  3. Você diz UMA vez quem entra no lugar de A, B, C (nome + foto, a pessoa inteira), o cenário novo, o estilo e as
     falas (as mesmas, novas escritas pela IA com a mesma ideia, ou sem fala).
  4. Pra cada plano: 🖼 o QUADRO NOVO sai da 🧩 Montar cena (o quadro original como base + as fotos) e 🎞 o VÍDEO sai
     do Veo começando nesse quadro, com a ação, a câmera e a fala do plano. Dá pra refazer só um plano.
  5. 🎬 Juntar: os vídeos na ordem, cada um no tamanho do plano original.

O Veo RECRIA o movimento pela descrição (não copia o gesto quadro a quadro) e cada vídeo dele tem até ~8 s.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

MAX_PLANO = 8.0      # o Veo faz ~8 s por vídeo
MIN_PLANO = 1.0
MAX_PLANOS = 24
LIMIAR_CORTE = 0.32
EXT_VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".m4v")
_TRAVA = threading.Lock()
_RODANDO: Dict[str, Dict[str, Any]] = {}
_RE_ID = re.compile(r"\d{8}_\d{6}_[0-9a-f]{6}")


class RefazerErro(ValueError):
    pass


# ------------------------------------------------------------------ pastas e projeto
def raiz(base: str) -> str:
    p = os.path.join(base, "refazer")
    os.makedirs(p, exist_ok=True)
    return p


def pasta(base: str, pid: str) -> str:
    if not _RE_ID.fullmatch(str(pid or "")):
        raise RefazerErro("Projeto inválido.")
    return os.path.join(raiz(base), pid)


def carregar(base: str, pid: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(base, pid), "projeto.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise RefazerErro("Esse projeto não existe.") from None


def salvar(base: str, p: Dict[str, Any]) -> None:
    d = pasta(base, p["id"])
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "projeto.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "projeto.json"))


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    for n in sorted(os.listdir(raiz(base)), reverse=True):
        if _RE_ID.fullmatch(n):
            try:
                p = carregar(base, n)
                out.append({"id": p["id"], "nome": p.get("nome") or n, "planos": len(p.get("planos") or []), "criado": p.get("criado"),
                            "final": bool(p.get("final"))})
            except RefazerErro:
                pass
    return out


def apagar(base: str, pid: str) -> None:
    shutil.rmtree(pasta(base, pid), ignore_errors=True)


def _mudar(base: str, pid: str, fn: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    with _TRAVA:
        p = carregar(base, pid)
        fn(p)
        salvar(base, p)
        return p


def _estado(base: str, pid: str, **k: Any) -> None:
    try:
        _mudar(base, pid, lambda p: p.setdefault("estado", {}).update(k))
    except RefazerErro:
        pass


# ------------------------------------------------------------------ vídeo: medidas, cortes, quadros
def medidas(video: str) -> Dict[str, float]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-show_entries", "format=duration", "-of", "json", video], capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        return {"w": int(s.get("width") or 0), "h": int(s.get("height") or 0), "dur": float((d.get("format") or {}).get("duration") or 0)}
    except (ValueError, TypeError):
        return {"w": 0, "h": 0, "dur": 0.0}


def proporcao_de(w: int, h: int) -> str:
    """O Veo faz 16:9 ou 9:16 — o mais perto do vídeo original."""
    return "9:16" if h > w else "16:9"


def cortes(video: str, limiar: float = LIMIAR_CORTE) -> List[float]:
    """Os instantes de troca de plano (detecção de cena do ffmpeg)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", video, "-vf", f"select='gt(scene,{limiar})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    return sorted({round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", r.stderr or "")})


def planos_de(cortes_: List[float], dur: float, max_plano: float = MAX_PLANO, min_plano: float = MIN_PLANO) -> List[Dict[str, float]]:
    """Cortes → planos [{ini, fim}]: os curtos demais grudam no anterior; os longos viram pedaços de até `max_plano`."""
    marcas = [0.0] + [c for c in cortes_ if 0 < c < dur] + [dur]
    brutos: List[List[float]] = []
    for a, b in zip(marcas, marcas[1:]):
        if b - a <= 0.01:
            continue
        if brutos and b - a < min_plano:
            brutos[-1][1] = b
        else:
            brutos.append([a, b])
    if len(brutos) > 1 and brutos[0][1] - brutos[0][0] < min_plano:
        brutos[1][0] = brutos[0][0]
        brutos.pop(0)
    out: List[Dict[str, float]] = []
    for a, b in brutos:
        n = max(1, int((b - a - 1e-6) // max_plano) + 1)
        passo = (b - a) / n
        for k in range(n):
            out.append({"ini": round(a + k * passo, 2), "fim": round(a + (k + 1) * passo, 2)})
    return out[:MAX_PLANOS]


def quadro(video: str, t: float, saida: str, largura: int = 0) -> str:
    vf = ["-vf", f"scale={largura}:-2"] if largura else []
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", video, "-frames:v", "1", *vf, saida],
                   capture_output=True, timeout=120)
    if not os.path.isfile(saida):
        raise RefazerErro(f"Não consegui tirar o quadro em {t:.1f} s.")
    return saida


def criar(base: str, video_origem: str, nome: str = "") -> Dict[str, Any]:
    """Copia o vídeo, acha os planos e tira o primeiro quadro de cada um (rápido; a análise da IA vem depois)."""
    if not os.path.isfile(video_origem) or os.path.splitext(video_origem)[1].lower() not in EXT_VIDEO:
        raise RefazerErro("Mande um vídeo (.mp4, .mov, .webm, .mkv).")
    pid = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
    d = pasta(base, pid)
    os.makedirs(os.path.join(d, "quadros"), exist_ok=True)
    video = os.path.join(d, "original" + os.path.splitext(video_origem)[1].lower())
    shutil.copy(video_origem, video)
    m = medidas(video)
    if m["dur"] <= 0.3:
        shutil.rmtree(d, ignore_errors=True)
        raise RefazerErro("Não consegui ler esse vídeo.")
    planos = planos_de(cortes(video), m["dur"])
    for k, pl in enumerate(planos, 1):
        pl.update(n=k, quadro=f"quadros/p{k:02d}.png", acao_en="", camera_en="", pessoas=[], fala=[], quadro_novo="", video_novo="",
                  erro="", prompt_quadro="", prompt_video="")
        quadro(video, pl["ini"] + min(0.08, (pl["fim"] - pl["ini"]) / 4), os.path.join(d, pl["quadro"]))
    p = {"id": pid, "nome": " ".join(str(nome or os.path.splitext(os.path.basename(video_origem))[0]).split())[:80],
         "criado": time.time(), "video": os.path.basename(video), "dur": round(m["dur"], 2), "w": m["w"], "h": m["h"],
         "proporcao": proporcao_de(m["w"], m["h"]), "planos": planos, "personagens": [], "cenario": {"descricao": "", "novo": "", "foto": ""},
         "estilo": "", "falas_modo": "manter", "idioma_falas": "", "transcricao": [], "analisado": False, "final": "",
         "estado": {"rodando": False, "msg": "", "erro": ""}}
    salvar(base, p)
    return p


# ------------------------------------------------------------------ 🤖 análise
SISTEMA = """You analyse a video SCENE split into numbered shots so it can be REMADE with other characters, another setting
and/or other lines — same idea, same staging. For every shot you get 3 frames (start, middle, end) and the speech heard in it.
Return:
- "personagens": every distinct person across the whole scene with a stable id (A, B, C…) and a short Brazilian Portuguese
  description (clothes, build, role) — the SAME person keeps the same id in every shot; never identify real people;
- "cenario": the place, in Portuguese;
- "planos": for EVERY shot n: "pessoas" = who is visible in its FIRST frame with a point on their head (x,y fractions 0..1
  from the top-left); "acao_en" = what happens in the shot (movements, gestures, expressions, interactions) in concrete
  English for a video model, 1–3 sentences, describing people by role/position (not by real names); "camera_en" = the
  camera (static, slow push-in, pan left, handheld…); "fala" = the lines spoken in the shot attributed to the ids, in the
  original language (empty list if none)."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["personagens", "cenario", "planos"], "properties": {
    "personagens": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "descricao"],
                                               "properties": {"id": {"type": "string"}, "descricao": {"type": "string"}}}},
    "cenario": {"type": "string"},
    "planos": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                          "required": ["n", "pessoas", "acao_en", "camera_en", "fala"], "properties": {
        "n": {"type": "integer"}, "acao_en": {"type": "string"}, "camera_en": {"type": "string"},
        "pessoas": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "x", "y"],
                                               "properties": {"id": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}}},
        "fala": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "texto"],
                                            "properties": {"id": {"type": "string"}, "texto": {"type": "string"}}}}}}}}}


def transcrever(video: str, transcrever_fn: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    try:
        if transcrever_fn is None:
            import whisper_transcribe as wt
            transcrever_fn = lambda a: wt.transcribe_audio(a, model_size="base")  # noqa: E731
        segs = transcrever_fn(video) or []
    except Exception:  # noqa: BLE001 — sem fala / sem Whisper: segue sem as falas
        return []
    return [{"start": round(float(s.get("start") or 0), 2), "end": round(float(s.get("end") or 0), 2),
             "text": " ".join(str(s.get("text") or "").split())} for s in segs if str(s.get("text") or "").strip()]


def falas_do_plano(transcricao: List[Dict[str, Any]], ini: float, fim: float) -> str:
    return " ".join(s["text"] for s in transcricao if s["end"] > ini + 0.1 and s["start"] < fim - 0.1)


def conteudo_ia(base: str, p: Dict[str, Any], bloco_imagem: Callable[[str], Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    d = pasta(base, p["id"])
    video = os.path.join(d, p["video"])
    c: List[Dict[str, Any]] = []
    tmp = os.path.join(d, "_analise")
    os.makedirs(tmp, exist_ok=True)
    for pl in p["planos"]:
        fala = falas_do_plano(p.get("transcricao") or [], pl["ini"], pl["fim"])
        c.append({"type": "text", "text": f"SHOT {pl['n']} ({pl['ini']:.1f}–{pl['fim']:.1f} s)" + (f" — speech: {fala}" if fala else " — no speech")})
        for k, f in enumerate((0.0, 0.5, 0.92)):
            t = pl["ini"] + (pl["fim"] - pl["ini"]) * f + (0.08 if k == 0 else 0)
            try:
                b = bloco_imagem(quadro(video, t, os.path.join(tmp, f"p{pl['n']:02d}_{k}.jpg"), 384))
            except RefazerErro:
                b = None
            if b:
                c.append(b)
    return c


def ler_analise(p: Dict[str, Any], r: Dict[str, Any]) -> None:
    ids = []
    pers = []
    for x in r.get("personagens") or []:
        i = re.sub(r"[^A-Z0-9]", "", str(x.get("id") or "").upper())[:3]
        if i and i not in ids:
            ids.append(i)
            pers.append({"id": i, "descricao": " ".join(str(x.get("descricao") or "").split())[:300], "nome": "", "obs": "", "foto": ""})
    velhos = {x["id"]: x for x in p.get("personagens") or []}
    for x in pers:  # reanalisar não perde o que você já escolheu
        if x["id"] in velhos:
            x.update({k: velhos[x["id"]][k] for k in ("nome", "obs", "foto") if velhos[x["id"]].get(k)})
    p["personagens"] = pers
    p["cenario"]["descricao"] = " ".join(str(r.get("cenario") or "").split())[:400]
    por_n = {int(x.get("n") or 0): x for x in r.get("planos") or [] if isinstance(x, dict)}
    for pl in p["planos"]:
        a = por_n.get(pl["n"]) or {}
        pl["acao_en"] = " ".join(str(a.get("acao_en") or "").split())[:800]
        pl["camera_en"] = " ".join(str(a.get("camera_en") or "").split())[:200]
        pl["pessoas"] = []
        for q in a.get("pessoas") or []:
            i = re.sub(r"[^A-Z0-9]", "", str(q.get("id") or "").upper())[:3]
            try:
                x_, y_ = float(q.get("x")), float(q.get("y"))
            except (TypeError, ValueError):
                continue
            if i in ids and 0 <= x_ <= 1 and 0 <= y_ <= 1:
                pl["pessoas"].append({"id": i, "x": round(x_, 4), "y": round(y_, 4)})
        pl["fala"] = [{"id": re.sub(r"[^A-Z0-9]", "", str(f.get("id") or "").upper())[:3] or "?",
                       "texto": " ".join(str(f.get("texto") or "").split())[:400]} for f in a.get("fala") or [] if str(f.get("texto") or "").strip()]
        pl["fala_original"] = [dict(f) for f in pl["fala"]]
    p["analisado"] = True


def analisar(base: str, pid: str, chamar: Optional[Callable[..., Any]] = None,
             bloco_imagem: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
             transcrever_fn: Optional[Callable[..., Any]] = None, prog: Callable[[str], None] = lambda s: None) -> Dict[str, Any]:
    if chamar is None or bloco_imagem is None:
        import ia_servico
        chamar = chamar or ia_servico.chamar
        bloco_imagem = bloco_imagem or (lambda f: ia_servico.imagem_bloco(f, 384))
    p = carregar(base, pid)
    if not p.get("transcricao"):
        prog("🎙 ouvindo as falas…")
        tr = transcrever(os.path.join(pasta(base, pid), p["video"]), transcrever_fn)
        p = _mudar(base, pid, lambda q: q.update(transcricao=tr))
    prog(f"🤖 a IA está olhando os {len(p['planos'])} planos…")
    r = chamar("refazer_cena", SISTEMA, conteudo_ia(base, p, bloco_imagem), schema=SCHEMA, max_tokens=8000, effort="medium",
               timeout=300)
    if not isinstance(r, dict):
        raise RefazerErro("A IA não respondeu (ou está desligada) — veja 🤖 IA: chaves e modelos.")
    return _mudar(base, pid, lambda q: ler_analise(q, r))


# ------------------------------------------------------------------ 🗣 falas novas (mesma ideia)
SISTEMA_FALAS = """Rewrite the dialogue of a scene so it is NEW but keeps the same idea, intention and emotion of each line,
the same speaker and roughly the same length (it must fit the shot duration). Keep the language requested. Use the new
character names if given. Return every shot n with its new lines."""
SCHEMA_FALAS = {"type": "object", "additionalProperties": False, "required": ["planos"], "properties": {"planos": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["n", "fala"], "properties": {"n": {"type": "integer"}, "fala": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "texto"],
                                   "properties": {"id": {"type": "string"}, "texto": {"type": "string"}}}}}}}}}


def reescrever_falas(base: str, pid: str, pedido: str = "", idioma: str = "", chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    p = carregar(base, pid)
    nomes = {x["id"]: x.get("nome") or x["id"] for x in p.get("personagens") or []}
    linhas = [f"Shot {pl['n']} ({pl['fim'] - pl['ini']:.1f} s): " + " | ".join(f"{nomes.get(f['id'], f['id'])} ({f['id']}): {f['texto']}"
                                                                                for f in pl.get("fala_original") or pl.get("fala") or [])
              for pl in p["planos"] if pl.get("fala_original") or pl.get("fala")]
    if not linhas:
        raise RefazerErro("Essa cena não tem fala pra reescrever.")
    cont = ("LANGUAGE: " + (idioma or "same as the original") + "\nREQUEST: " + (pedido or "(none)") + "\nCHARACTERS: "
            + ", ".join(f"{k} = {v}" for k, v in nomes.items()) + "\n\n" + "\n".join(linhas))
    r = chamar("refazer_cena", SISTEMA_FALAS, cont, schema=SCHEMA_FALAS, max_tokens=3000, effort="medium", timeout=180)
    if not isinstance(r, dict):
        raise RefazerErro("A IA não respondeu (ou está desligada).")
    por_n = {int(x.get("n") or 0): x for x in r.get("planos") or [] if isinstance(x, dict)}

    def aplicar(q):
        for pl in q["planos"]:
            if pl["n"] in por_n:
                pl["fala"] = [{"id": str(f.get("id") or "?")[:3].upper(), "texto": " ".join(str(f.get("texto") or "").split())[:400]}
                              for f in por_n[pl["n"]].get("fala") or [] if str(f.get("texto") or "").strip()]
        q["falas_modo"] = "novas"
    return _mudar(base, pid, aplicar)


# ------------------------------------------------------------------ 🖼 quadro novo + 🎞 vídeo, plano a plano
def pacote_do_plano(base: str, p: Dict[str, Any], pl: Dict[str, Any], gal_base: str) -> Dict[str, Any]:
    """A 🧩 Montar cena do plano: o quadro original é a BASE; cada pessoa marcada é trocada pela pessoa nova inteira."""
    import flow_montar as FM
    d = pasta(base, p["id"])
    pers = {x["id"]: x for x in p.get("personagens") or []}
    marcas, itens, ja = [], [{"papel": "base", "arquivo": os.path.join(d, pl["quadro"]),
                              "obs": "a composição, as poses e o enquadramento deste quadro (de um vídeo)"}], set()
    for q in pl.get("pessoas") or []:
        x = pers.get(q["id"]) or {}
        nome = x.get("nome") or ""
        marcas.append({"x": q["x"], "y": q["y"], "tipo": "pessoa", "nome": nome or f"pessoa {q['id']}",
                       "obs": ("mantém como está" if not (nome or x.get("foto")) else "") + (x.get("obs") or "")})
        if x.get("foto") and q["id"] not in ja and os.path.isfile(os.path.join(d, x["foto"])):
            ja.add(q["id"])
            itens.append({"papel": "personagem", "nome": nome or f"pessoa {q['id']}", "obs": x.get("obs") or "",
                          "arquivo": os.path.join(d, x["foto"])})
    cen = p.get("cenario") or {}
    if cen.get("foto") and os.path.isfile(os.path.join(d, cen["foto"])):
        itens.append({"papel": "cenario", "nome": cen.get("novo") or "", "obs": "o cenário novo", "arquivo": os.path.join(d, cen["foto"])})
    itens[0]["marcas"] = marcas
    itens[0]["cena"] = {"camera": "", "cenario": cen.get("descricao") or "", "cenario_novo": cen.get("novo") or ""}
    return FM.novo_pacote(gal_base, itens[:FM.MAX_REFS], "", p.get("estilo") or "")


def prompt_video(p: Dict[str, Any], pl: Dict[str, Any]) -> str:
    """Ação + câmera + falas (com os nomes novos) + estilo — começando do quadro novo."""
    import flow_montar as FM
    nomes = {x["id"]: (x.get("nome") or f"the person {x['id']}") for x in p.get("personagens") or []}
    partes = ["Start exactly from the given first frame and keep every character's look identical to it."]
    if pl.get("acao_en"):
        partes.append(pl["acao_en"])
    if pl.get("camera_en"):
        partes.append("Camera: " + pl["camera_en"].rstrip(".") + ".")
    modo = p.get("falas_modo") or "manter"
    if modo != "sem":
        for f in pl.get("fala") or []:
            partes.append(f'{nomes.get(f["id"], "Someone")} says: "{f["texto"]}"')
    else:
        partes.append("No dialogue.")
    if (p.get("cenario") or {}).get("novo"):
        partes.append("Setting: " + p["cenario"]["novo"] + ".")
    e = FM.estilo_en(p.get("estilo") or "")
    if e:
        partes.append("Style: " + e.rstrip(".") + ".")
    else:  # sem estilo escolhido: o do quadro novo (que já segue o dos personagens novos)
        partes.append("Keep exactly the art style of the first frame.")
    return " ".join(partes)[:3800]


def _copiar_pro_projeto(base: str, pid: str, origem: str, nome: str) -> str:
    d = pasta(base, pid)
    os.makedirs(os.path.join(d, "novos"), exist_ok=True)
    rel = f"novos/{nome}{os.path.splitext(origem)[1].lower()}"
    shutil.copy(origem, os.path.join(d, rel))
    return rel


def gerar(base: str, gal_base: str, pid: str, ns: List[int], etapa: str, rodar: Callable[..., List[Dict[str, Any]]],
          montar: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None, parar: Callable[[], bool] = lambda: False,
          prog: Callable[[str], None] = lambda s: None) -> Dict[str, Any]:
    """etapa: "quadro" (só os quadros novos, pra você conferir), "video" (anima os quadros que já existem) ou "tudo"."""
    import flow_montar as FM
    montar = montar or FM.montar_prompt
    p = carregar(base, pid)
    alvos = [pl for pl in p["planos"] if not ns or pl["n"] in ns]
    for k, pl in enumerate(alvos, 1):
        if parar():
            raise RefazerErro("Parado por você.")
        n = pl["n"]
        try:
            if etapa in ("quadro", "tudo") or (etapa == "video" and not pl.get("quadro_novo")):
                prog(f"🖼 plano {n} ({k}/{len(alvos)}): montando o quadro novo…")
                pac = pacote_do_plano(base, p, pl, gal_base)
                pr = montar(pac)["prompt"]
                res = rodar({"tipo": "imagem", "prompt": pr, "referencias": FM.referencias_flow(pac), "proporcao": p["proporcao"]})
                img = next((r for r in res if r.get("tipo") == "imagem"), None)
                if not img:
                    raise RefazerErro("o Flow não devolveu a imagem")
                rel = _copiar_pro_projeto(base, pid, img["caminho"], f"q{n:02d}_{secrets.token_hex(2)}")
                p = _mudar(base, pid, lambda q: next(x for x in q["planos"] if x["n"] == n).update(
                    quadro_novo=rel, prompt_quadro=pr, video_novo="", erro=""))
                pl = next(x for x in p["planos"] if x["n"] == n)
            if etapa in ("video", "tudo"):
                prog(f"🎞 plano {n} ({k}/{len(alvos)}): animando no Veo…")
                pv = prompt_video(p, pl)
                res = rodar({"tipo": "video", "prompt": pv, "inicio": {"arquivo": os.path.join(pasta(base, pid), pl["quadro_novo"])},
                             "proporcao": p["proporcao"]})
                vid = next((r for r in res if r.get("tipo") == "video"), None)
                if not vid:
                    raise RefazerErro("o Flow não devolveu o vídeo")
                rel = _copiar_pro_projeto(base, pid, vid["caminho"], f"v{n:02d}_{secrets.token_hex(2)}")
                p = _mudar(base, pid, lambda q: next(x for x in q["planos"] if x["n"] == n).update(video_novo=rel, prompt_video=pv, erro=""))
        except RefazerErro:
            raise
        except Exception as exc:  # noqa: BLE001 — um plano com erro não para os outros
            msg = str(exc)[:300]
            if "Parado" in msg:
                raise RefazerErro("Parado por você.") from None
            p = _mudar(base, pid, lambda q: next(x for x in q["planos"] if x["n"] == n).update(erro=msg))
    return carregar(base, pid)


# ------------------------------------------------------------------ 🎬 juntar
def juntar(base: str, pid: str) -> str:
    """Os vídeos novos na ordem, cada um cortado no tamanho do plano original (o plano sem vídeo novo usa o original)."""
    p = carregar(base, pid)
    d = pasta(base, pid)
    if not any(pl.get("video_novo") for pl in p["planos"]):
        raise RefazerErro("Nenhum plano tem vídeo novo ainda.")
    W, H = (1080, 1920) if p["proporcao"] == "9:16" else (1920, 1080)
    tmp = os.path.join(d, "_juntar")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    partes = []
    for pl in p["planos"]:
        dur = max(0.3, pl["fim"] - pl["ini"])
        if pl.get("video_novo") and os.path.isfile(os.path.join(d, pl["video_novo"])):
            ent, ss = os.path.join(d, pl["video_novo"]), 0.0
        else:
            ent, ss = os.path.join(d, p["video"]), pl["ini"]
        saida = os.path.join(tmp, f"{pl['n']:02d}.mp4")
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", ent,
                            "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                            "-filter_complex", f"[0:v]{vf}[v];[0:a]aresample=48000,apad[a0];[a0][1:a]amix=inputs=2:duration=shortest[a]",
                            "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", saida], capture_output=True, timeout=900)
        if r.returncode != 0:  # sem áudio no arquivo: só o silêncio
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", ent,
                                "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                                "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a", "-t", f"{dur:.3f}",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", saida],
                               capture_output=True, timeout=900)
        if r.returncode != 0 or not os.path.isfile(saida):
            raise RefazerErro(f"Não consegui preparar o plano {pl['n']}: " + (r.stderr or b"").decode("utf-8", "replace")[-200:])
        partes.append(saida)
    lista = os.path.join(tmp, "lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.writelines(f"file '{x}'\n" for x in partes)
    final = f"final_{time.strftime('%H%M%S')}.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy",
                        "-movflags", "+faststart", os.path.join(d, final)], capture_output=True, timeout=900)
    shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        raise RefazerErro("Não consegui juntar os planos.")
    _mudar(base, pid, lambda q: q.update(final=final))
    return final


# ------------------------------------------------------------------ segundo plano
def rodar_em_fundo(base: str, pid: str, rotulo: str, fn: Callable[[Callable[[str], None], Callable[[], bool]], Any]) -> None:
    with _TRAVA:
        if (_RODANDO.get(pid) or {}).get("rodando"):
            raise RefazerErro("Esse projeto já está rodando — espere ou clique em Parar.")
        _RODANDO[pid] = {"rodando": True, "parar": False}
    _estado(base, pid, rodando=True, msg=rotulo, erro="", inicio=time.time())

    def prog(m: str) -> None:
        _estado(base, pid, msg=str(m)[:300])

    def corpo() -> None:
        erro = ""
        try:
            fn(prog, lambda: bool(_RODANDO.get(pid, {}).get("parar")))
        except Exception as exc:  # noqa: BLE001
            erro = str(exc)[:500]
            if not isinstance(exc, RefazerErro):
                traceback.print_exc()
        finally:
            _RODANDO[pid] = {"rodando": False, "parar": False}
            _estado(base, pid, rodando=False, erro=erro, msg="" if erro else "✅ pronto", fim=time.time())
    threading.Thread(target=corpo, daemon=True).start()


def parar(pid: str) -> None:
    if pid in _RODANDO:
        _RODANDO[pid]["parar"] = True


def publico(p: Dict[str, Any], url: Callable[[str], str]) -> Dict[str, Any]:
    """O projeto pra tela (com os links dos arquivos)."""
    out = json.loads(json.dumps(p))
    out["video_url"] = url(p["video"])
    for pl in out["planos"]:
        pl["quadro_url"] = url(pl["quadro"])
        pl["quadro_novo_url"] = url(pl["quadro_novo"]) if pl.get("quadro_novo") else ""
        pl["video_novo_url"] = url(pl["video_novo"]) if pl.get("video_novo") else ""
    for x in out.get("personagens") or []:
        x["foto_url"] = url(x["foto"]) if x.get("foto") else ""
    c = out.get("cenario") or {}
    c["foto_url"] = url(c["foto"]) if c.get("foto") else ""
    out["final_url"] = url(p["final"]) if p.get("final") else ""
    out["estado"]["rodando"] = bool((_RODANDO.get(p["id"]) or {}).get("rodando"))
    out.pop("transcricao", None)
    return out


# ------------------------------------------------------------------ rotas
def registrar(app, FE) -> None:
    from flask import jsonify, render_template, request, send_from_directory

    def base() -> str:
        return os.path.join(os.path.dirname(FE.pasta_galeria()), "flow_refazer")

    def _url(pid: str) -> Callable[[str], str]:
        return lambda rel: f"/flow/refazer/{pid}/arq/{rel}"

    def _pub(p):
        return jsonify({"ok": True, "projeto": publico(p, _url(p["id"]))})

    def _erro(msg, cod=400):
        return jsonify({"erro": msg}), cod

    def _salvar_upload(campo: str, exts) -> Optional[str]:
        arq = request.files.get(campo)
        gid = (request.form.get(campo + "_galeria") or "").strip()
        if gid:
            e = FE.item_da_galeria(gid)
            if e and os.path.isfile(os.path.join(FE.pasta_galeria(), e["arquivo"])):
                return os.path.join(FE.pasta_galeria(), e["arquivo"])
            raise RefazerErro("Esse item não está mais na galeria.")
        if not arq or not arq.filename:
            return None
        ext = os.path.splitext(arq.filename)[1].lower()
        if ext not in exts:
            raise RefazerErro("Formato não aceito: " + ", ".join(exts))
        tmp = os.path.join(raiz(base()), f"_envio_{secrets.token_hex(4)}{ext}")
        arq.save(tmp)
        return tmp

    @app.route("/flow/refazer")
    def flow_refazer_pagina():
        import flow_montar as FM
        return render_template("flow_refazer.html", estilos_finais=FM.estilos(), max_planos=MAX_PLANOS)

    @app.route("/flow/refazer/lista")
    def flow_refazer_lista():
        return jsonify({"projetos": listar(base())})

    @app.route("/flow/refazer/novo", methods=["POST"])
    def flow_refazer_novo():
        try:
            cam = _salvar_upload("video", EXT_VIDEO)
            if not cam:
                return _erro("Mande o vídeo da cena.")
            try:
                p = criar(base(), cam, request.form.get("nome") or "")
            finally:
                if os.path.basename(cam).startswith("_envio_"):
                    try:
                        os.remove(cam)
                    except OSError:
                        pass
        except RefazerErro as exc:
            return _erro(str(exc))
        pid = p["id"]
        try:
            rodar_em_fundo(base(), pid, "🤖 analisando a cena…", lambda prog, parar_: analisar(base(), pid, prog=prog))
        except RefazerErro:
            pass
        return _pub(carregar(base(), pid))

    @app.route("/flow/refazer/<pid>")
    def flow_refazer_ver(pid: str):
        try:
            return _pub(carregar(base(), pid))
        except RefazerErro as exc:
            return _erro(str(exc), 404)

    @app.route("/flow/refazer/<pid>/arq/<path:rel>")
    def flow_refazer_arq(pid: str, rel: str):
        try:
            d = pasta(base(), pid)
        except RefazerErro:
            return "inválido", 400
        if ".." in rel or rel.endswith(".json") or not re.fullmatch(r"[\w./\-]+", rel):
            return "inválido", 400
        return send_from_directory(d, rel, as_attachment=request.args.get("baixar") == "1")

    @app.route("/flow/refazer/<pid>/analisar", methods=["POST"])
    def flow_refazer_analisar(pid: str):
        try:
            carregar(base(), pid)
            rodar_em_fundo(base(), pid, "🤖 analisando a cena…", lambda prog, parar_: analisar(base(), pid, prog=prog))
        except RefazerErro as exc:
            return _erro(str(exc))
        return jsonify({"ok": True})

    @app.route("/flow/refazer/<pid>/salvar", methods=["POST"])
    def flow_refazer_salvar(pid: str):
        b = request.get_json(silent=True) or {}

        def aplicar(p):
            por_id = {x["id"]: x for x in p.get("personagens") or []}
            for x in b.get("personagens") or []:
                alvo = por_id.get(str(x.get("id") or ""))
                if alvo:
                    alvo["nome"] = " ".join(str(x.get("nome") or "").split())[:60]
                    alvo["obs"] = " ".join(str(x.get("obs") or "").split())[:300]
                    if x.get("tirar_foto"):
                        alvo["foto"] = ""
            if isinstance(b.get("cenario"), dict):
                p["cenario"]["novo"] = " ".join(str(b["cenario"].get("novo") or "").split())[:300]
                if b["cenario"].get("tirar_foto"):
                    p["cenario"]["foto"] = ""
            if "estilo" in b:
                import flow_montar as FM
                p["estilo"] = b["estilo"] if FM.estilo_en(b.get("estilo") or "") else ""
            if b.get("falas_modo") in ("manter", "novas", "sem"):
                p["falas_modo"] = b["falas_modo"]
                if b["falas_modo"] == "manter":
                    for pl in p["planos"]:
                        pl["fala"] = [dict(f) for f in pl.get("fala_original") or pl.get("fala") or []]
            por_n = {int(x.get("n") or 0): x for x in b.get("planos") or [] if isinstance(x, dict)}
            for pl in p["planos"]:
                x = por_n.get(pl["n"])
                if not x:
                    continue
                if "acao_en" in x:
                    pl["acao_en"] = " ".join(str(x.get("acao_en") or "").split())[:800]
                if "camera_en" in x:
                    pl["camera_en"] = " ".join(str(x.get("camera_en") or "").split())[:200]
                if isinstance(x.get("fala"), list):
                    pl["fala"] = [{"id": str(f.get("id") or "?")[:3].upper(), "texto": " ".join(str(f.get("texto") or "").split())[:400]}
                                  for f in x["fala"] if str(f.get("texto") or "").strip()]
        try:
            return _pub(_mudar(base(), pid, aplicar))
        except RefazerErro as exc:
            return _erro(str(exc))

    @app.route("/flow/refazer/<pid>/foto", methods=["POST"])
    def flow_refazer_foto(pid: str):
        alvo = str(request.form.get("alvo") or "")
        try:
            carregar(base(), pid)
            cam = _salvar_upload("foto", FE.EXT_IMAGEM)
            if not cam:
                return _erro("Mande a foto.")
            d = pasta(base(), pid)
            os.makedirs(os.path.join(d, "fotos"), exist_ok=True)
            rel = f"fotos/{re.sub(r'[^a-z0-9]', '_', alvo.lower())[:20]}_{secrets.token_hex(2)}{os.path.splitext(cam)[1].lower()}"
            shutil.copy(cam, os.path.join(d, rel))
            if os.path.basename(cam).startswith("_envio_"):
                os.remove(cam)

            def aplicar(p):
                if alvo == "cenario":
                    p["cenario"]["foto"] = rel
                    return
                x = next((x for x in p.get("personagens") or [] if "personagem:" + x["id"] == alvo), None)
                if not x:
                    raise RefazerErro("Pessoa não encontrada.")
                x["foto"] = rel
            return _pub(_mudar(base(), pid, aplicar))
        except RefazerErro as exc:
            return _erro(str(exc))

    @app.route("/flow/refazer/<pid>/falas", methods=["POST"])
    def flow_refazer_falas(pid: str):
        b = request.get_json(silent=True) or {}
        try:
            carregar(base(), pid)
            rodar_em_fundo(base(), pid, "🗣 escrevendo as falas novas…",
                           lambda prog, parar_: reescrever_falas(base(), pid, str(b.get("pedido") or "")[:500], str(b.get("idioma") or "")[:30]))
        except RefazerErro as exc:
            return _erro(str(exc))
        return jsonify({"ok": True})

    @app.route("/flow/refazer/<pid>/gerar", methods=["POST"])
    def flow_refazer_gerar(pid: str):
        b = request.get_json(silent=True) or {}
        etapa = b.get("etapa") if b.get("etapa") in ("quadro", "video", "tudo") else "tudo"
        ns = [int(n) for n in b.get("planos") or [] if str(n).isdigit()]
        opc = {"visivel": bool(b.get("visivel")), "conta": str(b.get("conta") or ""), "trocar_conta": b.get("trocar_conta", True) is not False}
        try:
            p = carregar(base(), pid)
            if not p.get("analisado"):
                return _erro("Espere a análise da cena terminar (ou clique em 🤖 analisar de novo).")
            if etapa == "video" and any(not pl.get("quadro_novo") for pl in p["planos"] if not ns or pl["n"] in ns):
                etapa_ = "tudo"  # plano sem quadro novo: faz o quadro antes
            else:
                etapa_ = etapa

            def fazer(prog, parar_):
                gerar(base(), FE.pasta_galeria(), pid, ns, etapa_,
                      lambda pedido: FE.rodar_e_esperar(dict(pedido, **opc), parar=parar_), parar=parar_, prog=prog)
                if etapa_ in ("video", "tudo") and not ns:
                    prog("🎬 juntando os planos…")
                    juntar(base(), pid)
            rotulo = {"quadro": "🖼 fazendo os quadros novos…", "video": "🎞 animando no Veo…", "tudo": "🎬 refazendo a cena…"}[etapa_]
            rodar_em_fundo(base(), pid, rotulo, fazer)
        except RefazerErro as exc:
            return _erro(str(exc))
        return jsonify({"ok": True})

    @app.route("/flow/refazer/<pid>/juntar", methods=["POST"])
    def flow_refazer_juntar(pid: str):
        try:
            juntar(base(), pid)
            return _pub(carregar(base(), pid))
        except RefazerErro as exc:
            return _erro(str(exc))

    @app.route("/flow/refazer/<pid>/parar", methods=["POST"])
    def flow_refazer_parar(pid: str):
        parar(pid)
        return jsonify({"ok": True})

    @app.route("/flow/refazer/<pid>/apagar", methods=["POST"])
    def flow_refazer_apagar(pid: str):
        try:
            if (_RODANDO.get(pid) or {}).get("rodando"):
                return _erro("Ainda está rodando — pare antes.")
            apagar(base(), pid)
        except RefazerErro as exc:
            return _erro(str(exc))
        return jsonify({"ok": True})
