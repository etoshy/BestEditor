"""
🧩 v84_406 — MONTAR CENA no Google Flow: uma pose + as fotos dos personagens (+ cenário, roupa, objeto…), cada uma com a
sua observação (opcional), e uma observação geral. A IA olha as fotos e escreve o comando do Flow dizendo o que vem de
cada imagem ("a pose da imagem 1", "o rosto da Ana é o da imagem 2"…); o Flow gera com TODAS as imagens de referência
na caixa, na mesma ordem.

Sem a IA (desligada / sem crédito) o site monta um comando básico com as mesmas regras — dá pra editar antes de gerar.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

MAX_REFS = 6          # o Flow aceita várias imagens na caixa; mais que isso confunde o modelo
MAX_OBS = 600
PAPEIS = {
    "pose": "pose / composição",
    "base": "foto base (composição)",
    "cores": "cores e luz",
    "personagem": "personagem",
    "cenario": "cenário / lugar",
    "roupa": "roupa / figurino",
    "objeto": "objeto",
    "estilo": "estilo / luz / cores",
    "outro": "outra referência",
}
_PACOTES: Dict[str, Dict[str, Any]] = {}

# 🎨 v84_407: o estilo de arte da imagem FINAL (os da 🎨 Identidade visual entram também)
ESTILOS_BASE = {
    "foto": ("📷 Foto realista", "photorealistic photograph, natural skin texture, real lighting, shot on a full-frame camera"),
    "anime": ("🌸 Anime", "modern anime illustration, clean cel shading, expressive eyes, vibrant colors, anime key visual"),
    "manga": ("📖 Mangá (preto e branco)", "black and white manga panel, ink lines, screentone shading, dynamic manga composition"),
    "cartoon": ("🎨 Cartoon / animação 3D", "stylized 3D animated movie look, soft lighting, appealing cartoon proportions"),
    "quadrinho": ("💥 Quadrinho americano", "american comic book art, bold ink outlines, flat colors with halftone shading"),
    "pixel": ("👾 Pixel art", "detailed pixel art, limited palette, crisp pixels, retro game scene"),
}


def estilos() -> List[Dict[str, str]]:
    out = [{"id": k, "nome": v[0]} for k, v in ESTILOS_BASE.items()]
    try:
        import estilos_arte
        out += [{"id": "arte:" + k, "nome": n} for k, n in estilos_arte.opcoes()]
    except Exception:  # noqa: BLE001
        pass
    return out


def estilo_en(eid: str) -> str:
    eid = str(eid or "")
    if eid in ESTILOS_BASE:
        return ESTILOS_BASE[eid][1]
    if eid.startswith("arte:"):
        try:
            import estilos_arte
            e = estilos_arte.ESTILOS.get(eid[5:])
            return " ".join(str((e or {}).get("en") or "").split())[:900]
        except Exception:  # noqa: BLE001
            return ""
    return ""


class MontarErro(ValueError):
    pass


def _limpo(t: Any, n: int = MAX_OBS) -> str:
    return " ".join(str(t or "").split())[:n]


def pasta_pacotes(base: str) -> str:
    p = os.path.join(base, "montar")
    os.makedirs(p, exist_ok=True)
    return p


def _limpar_velhos(base: str, horas: float = 48) -> None:
    raiz = pasta_pacotes(base)
    for n in os.listdir(raiz):
        c = os.path.join(raiz, n)
        try:
            if os.path.isdir(c) and time.time() - os.path.getmtime(c) > horas * 3600:
                shutil.rmtree(c, ignore_errors=True)
        except OSError:
            pass


def novo_pacote(base: str, itens: List[Dict[str, Any]], obs_geral: str = "", estilo: str = "") -> Dict[str, Any]:
    """itens = [{papel, nome, obs, arquivo (caminho de origem)}] na ordem em que vão pro Flow (a pose primeiro).
    Copia as imagens pra uma pasta só deste pacote e guarda."""
    _limpar_velhos(base)
    ok = [i for i in itens if i.get("arquivo") and os.path.isfile(i["arquivo"])]
    if not ok:
        raise MontarErro("Mande pelo menos uma foto (a pose ou um personagem).")
    if len(ok) > MAX_REFS:
        raise MontarErro(f"No máximo {MAX_REFS} imagens por cena (o Flow se confunde com mais).")
    ok.sort(key=lambda i: 0 if i.get("papel") in ("pose", "base") else 1)  # a pose/base sempre é a imagem 1
    pid = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
    pasta = os.path.join(pasta_pacotes(base), pid)
    os.makedirs(pasta, exist_ok=True)
    refs = []
    for k, i in enumerate(ok, 1):
        ext = os.path.splitext(i["arquivo"])[1].lower() or ".png"
        dest = os.path.join(pasta, f"{k:02d}_{i.get('papel') or 'outro'}{ext}")
        shutil.copy(i["arquivo"], dest)
        papel = i.get("papel") if i.get("papel") in PAPEIS else "outro"
        r = {"n": k, "papel": papel, "nome": _limpo(i.get("nome"), 60), "obs": _limpo(i.get("obs")), "arquivo": dest}
        if papel in ("pose", "base") and (i.get("marcas") or i.get("cena")):  # ✏️ v84_407: figuras numeradas do rascunho → quem fica em cada uma
            import flow_rascunho as FR
            marcas = FR.limpar_marcas(i.get("marcas") or [])
            cena = FR.limpar_cena(i.get("cena") or {})
            if marcas or any(cena.values()):
                r["marcas"] = marcas
                extra = "; ".join(x for x in (FR.texto_cena(cena), FR.texto_marcas(marcas)) if x)
                r["obs"] = _limpo((r["obs"] + " · " if r["obs"] else "") + "Na cena: " + extra, 1600)
                try:
                    if marcas:
                        r["arquivo_ia"] = FR.desenhar_marcas(dest, os.path.join(pasta, f"{k:02d}_pose_numerada.png"),
                                                             marcas)
                except Exception:  # noqa: BLE001 — sem a cópia numerada, a IA lê só a observação
                    pass
        refs.append(r)
    pac = {"id": pid, "refs": refs, "obs_geral": _limpo(obs_geral, 1500), "criado": time.time(),
           "estilo": estilo if estilo_en(estilo) else "", "estilo_en": estilo_en(estilo)}
    with open(os.path.join(pasta, "pacote.json"), "w", encoding="utf-8") as f:
        json.dump(pac, f, ensure_ascii=False, indent=1)
    _PACOTES[pid] = pac
    return pac


def carregar_pacote(base: str, pid: str) -> Dict[str, Any]:
    if not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{6}", str(pid or "")):
        raise MontarErro("Montagem inválida.")
    if pid in _PACOTES:
        return _PACOTES[pid]
    try:
        with open(os.path.join(pasta_pacotes(base), pid, "pacote.json"), encoding="utf-8") as f:
            pac = json.load(f)
    except (OSError, ValueError):
        raise MontarErro("Essa montagem não existe mais — monte de novo.") from None
    _PACOTES[pid] = pac
    return pac


def _quem(r: Dict[str, Any]) -> str:
    if r["papel"] == "personagem":
        return f"personagem “{r['nome']}”" if r["nome"] else "personagem"
    return PAPEIS[r["papel"]] + (f" “{r['nome']}”" if r["nome"] else "")


# ------------------------------------------------------------------ sem IA: o comando básico
_REGRA_PAPEL = {
    "pose": "copy ONLY the body pose, framing and camera angle from reference image {n} — not the person, clothes or background",
    "base": "use reference image {n} as the BASE of the composition: same framing, camera angle, positions and poses, and the same "
            "scenery and objects unless replaced below; the people in it are only placeholders and are replaced ENTIRELY",
    "personagem": "{nome} replaces the WHOLE figure: face, hair, body type, skin tone, clothes and their colors all come from the "
                  "person in reference image {n} — only the place and pose come from the base",
    "cenario": "use the location/background from reference image {n}",
    "roupa": "dress {alvo} in the outfit shown in reference image {n}",
    "objeto": "include the object from reference image {n}",
    "estilo": "match the lighting, colors and art style of reference image {n}",
    "cores": "take ONLY the color palette and lighting from reference image {n} (not its people, objects or composition)",
    "outro": "use reference image {n} as described",
}


def prompt_basico(pac: Dict[str, Any]) -> str:
    """O comando sem a IA: uma frase por imagem, na ordem, + as observações (em português mesmo — o Flow entende)."""
    pers = [r for r in pac["refs"] if r["papel"] == "personagem"]
    nomes = [r["nome"] or f"the person in image {r['n']}" for r in pers]
    alvo = nomes[0] if len(nomes) == 1 else "the characters"
    partes = []
    if nomes:
        partes.append(("A single image of " + ", ".join(nomes[:-1]) + (" and " if len(nomes) > 1 else "") + nomes[-1]) + ".")
    else:
        partes.append("A single image.")
    for r in pac["refs"]:
        frase = _REGRA_PAPEL[r["papel"]].format(n=r["n"], nome=r["nome"] or f"the person in image {r['n']}", alvo=alvo)
        partes.append(frase[0].upper() + frase[1:] + (f" (note: {r['obs']})" if r["obs"] else "") + ".")
    if pac.get("obs_geral"):
        partes.append("Scene: " + pac["obs_geral"] + ".")
    if pac.get("estilo_en"):
        partes.append("Art style of the final image: " + pac["estilo_en"].rstrip(".") + ".")
    elif pers:  # sem estilo escolhido: segue o dos personagens novos (desenho → cena desenhada; foto → realista)
        partes.append("Art style of the final image: the SAME look as the new character reference images (if they are "
                      "drawings/anime, render the whole scene in that drawn style; if they are photos, photorealistic) — "
                      "never the style of the base or pose image.")
    partes.append("Keep every character's identity consistent with their reference; natural, coherent result.")
    return " ".join(partes)


# ------------------------------------------------------------------ com IA (olhando as fotos)
SISTEMA = """You write ONE image-generation prompt for Google Flow (Nano Banana / Imagen) that will receive the reference
images below IN THIS ORDER (reference image 1, 2, 3…). The user said what each image is for and may add notes per image and
a general note (often in Portuguese). Your prompt must:
- say explicitly what to take from each reference by its number: a POSE image gives only body pose / framing / camera
  angle (never its identity, clothes or background); a BASE image (a real photo used as base) gives the whole composition —
  framing, positions, poses, scenery and objects unless replaced — but its PEOPLE are placeholders replaced entirely; a
  CHARACTER image replaces the WHOLE figure (face, hair, body type, skin tone, clothes AND their colors — never just the
  face; keep the base pose) — call the character by the given name; SCENERY gives the place; OUTFIT the clothes; OBJECT
  the object; STYLE the light/colors/art style; COLORS gives ONLY the palette and lighting;
- when there is a pose and several characters, say who takes which position in the pose (follow the notes; if unsaid,
  decide sensibly and say it);
- describe the identity features you SEE in each character photo in a few words (helps consistency), without naming real
  people or celebrities even if you recognize them;
- a POSE image may come to YOU with numbered circles (red = person, blue = object) and a note saying who goes in figure
  1, 2…, what replaces each object and whether the scenery changes; Flow gets the CLEAN image (no numbers), so describe each
  place by position/pose ("the figure on the left leaning in", "the car behind them"), never by the number; a replaced
  object/scenery keeps the place and size of the original unless a note says otherwise; "mantém" = keep it as in the sketch;
- follow every note; the general note wins on scene/mood/action;
- render the FINAL ART STYLE given (realistic photo, anime, manga…) and say it clearly in the prompt; the identities stay
  recognizable in that style; when no style is chosen, the style comes from the NEW CHARACTER images (a drawn character makes
  the whole scene drawn in that same style, a photo makes it photorealistic) — a base photo or a pencil-sketch pose never
  sets the style;
- be concrete about the final image (action, expressions, setting, light, lens) in natural English, 60–160 words;
- no markdown, no lists, no quotes around the prompt.
Also give "explicacao": 1–3 short sentences in Brazilian Portuguese saying how you used each image, and "avisos": problems
in Portuguese (e.g. a photo too small, conflicting notes) — empty list if none."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["prompt", "explicacao", "avisos"],
          "properties": {"prompt": {"type": "string"}, "explicacao": {"type": "string"},
                         "avisos": {"type": "array", "items": {"type": "string"}}}}


def conteudo_ia(pac: Dict[str, Any], bloco_imagem: Callable[[str], Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    c: List[Dict[str, Any]] = []
    for r in pac["refs"]:
        c.append({"type": "text", "text": f"Reference image {r['n']} — {r['papel'].upper()}"
                                         + (f" — name: {r['nome']}" if r["nome"] else "")
                                         + (f" — note: {r['obs']}" if r["obs"] else "")})
        b = bloco_imagem(r.get("arquivo_ia") or r["arquivo"])
        if b:
            c.append(b)
    c.append({"type": "text", "text": "GENERAL NOTE: " + (pac.get("obs_geral") or "(none)")})
    c.append({"type": "text", "text": "FINAL ART STYLE: " + (pac.get("estilo_en") or "(not chosen — use the SAME style as the NEW "
                                                                                    "CHARACTER images: drawn/anime characters → the whole scene "
                                                                                    "drawn in that style; photos → photorealistic. The base/pose "
                                                                                    "image never sets the style)")})
    return c


def montar_prompt(pac: Dict[str, Any], chamar: Optional[Callable[..., Any]] = None,
                  bloco_imagem: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """→ {prompt, explicacao, avisos, com_ia}. Sem IA (ou se ela não responder): o comando básico."""
    if chamar is None or bloco_imagem is None:
        import ia_servico
        chamar = chamar or ia_servico.chamar
        bloco_imagem = bloco_imagem or (lambda f: ia_servico.imagem_bloco(f, 768))
    r = None
    try:
        r = chamar("flow_montar", SISTEMA, conteudo_ia(pac, bloco_imagem), schema=SCHEMA, max_tokens=1500,
                   effort="medium", timeout=120)
    except Exception:  # noqa: BLE001
        r = None
    if isinstance(r, dict) and str(r.get("prompt") or "").strip():
        return {"prompt": " ".join(str(r["prompt"]).split())[:3800], "explicacao": str(r.get("explicacao") or "")[:600],
                "avisos": [str(a)[:200] for a in (r.get("avisos") or [])][:5], "com_ia": True}
    return {"prompt": prompt_basico(pac), "explicacao": "Comando montado sem a IA (ela está desligada ou não respondeu) — "
            "uma frase pra cada imagem, na ordem. Dá pra editar antes de gerar.", "avisos": [], "com_ia": False}


def referencias_flow(pac: Dict[str, Any]) -> List[Dict[str, str]]:
    """As imagens na ordem certa pro Flow (a mesma numeração do comando)."""
    return [{"arquivo": r["arquivo"]} for r in pac["refs"]]


def resumo(pac: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"n": r["n"], "papel": r["papel"], "papel_nome": PAPEIS[r["papel"]], "quem": _quem(r), "nome": r["nome"],
             "obs": r["obs"], "arquivo": os.path.basename(r["arquivo"])} for r in pac["refs"]]
