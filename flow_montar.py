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
        if papel == "personagem":  # 🙂 v84_408c: "inteira" (rosto, corpo, roupa) ou "rosto" (só a cabeça; o resto da cena fica)
            r["troca"] = i.get("troca") if i.get("troca") in ("rosto", "inteira") else "auto"  # 🤖 v84_408d: padrão automático
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
            "scenery and objects unless replaced below; the people marked below are replaced as described (the whole figure, or only "
            "the face/head)",
    "personagem": "{nome} replaces the WHOLE figure: face, hair, body type, skin tone, clothes and their colors all come from the "
                  "person in reference image {n} — only the place, the pose and the FACIAL EXPRESSION (the emotion of the "
                  "figure being replaced) come from the base",
    "cenario": "use the location/background from reference image {n}",
    "roupa": "dress {alvo} in the outfit shown in reference image {n}",
    "objeto": "include the object from reference image {n}",
    "personagem_auto": "{nome} (look from reference image {n}) takes the place of that figure, in the same pose, place and "
                       "expression; whatever the scene shows of that figure that reference image {n} does not (body, clothes, "
                       "hands, shoes…) is DESIGNED to match both {nome}'s look (palette, style, personality) and the scene's "
                       "context (place, era, action), and anything in reference image {n} the scene does not need (its pose, "
                       "props, background) is left out",
    "personagem_rosto": "ONLY the face/head of the figure is replaced by {nome}'s face/head design from reference image {n} "
                        "(its features, colors and head shape) — everything else in the base stays exactly as it is: body, "
                        "clothes, hands, surroundings, framing and light; the new face makes the SAME expression, gaze and head "
                        "angle as the original face and is lit and blended like it was there",
    "estilo": "match the lighting, colors and art style of reference image {n}",
    "cores": "take ONLY the color palette and lighting from reference image {n} (not its people, objects or composition)",
    "outro": "use reference image {n} as described",
}


IGNORAR_REF = ("From the character reference images take ONLY what the character looks like (face/head design, body shape, "
               "colors, outfit, art style) — IGNORE the pose, gesture, hand position, objects it holds and facial expression "
               "shown in those references unless a note asks to keep them.")


def prompt_basico(pac: Dict[str, Any]) -> str:
    """O comando sem a IA: a BASE primeiro (refazer o quadro igual, só trocando quem está nele), uma frase por imagem, o
    "ignore a pose/objetos da foto do personagem" e o estilo. 🩹 v84_408c: antes o Flow colava o personagem com a pose e os
    objetos da própria foto dele (ex.: o boneco de joinha com o caneco) em vez de fazer a pose/expressão da base."""
    pers = [r for r in pac["refs"] if r["papel"] == "personagem"]
    nomes = [r["nome"] or f"the character from image {r['n']}" for r in pers]
    alvo = nomes[0] if len(nomes) == 1 else "the characters"
    base = next((r for r in pac["refs"] if r["papel"] in ("base", "pose")), None)
    partes = []
    if base and nomes and all(r.get("troca") == "rosto" for r in pers):
        quem = ", ".join(nomes[:-1]) + (" and " if len(nomes) > 1 else "") + nomes[-1]
        partes.append(f"Keep reference image {base['n']} exactly as it is — same scene, framing, crop, body, clothes, hands, "
                      f"light and photo look — and replace ONLY the face/head with the face/head of {quem}, making the very "
                      f"same expression, gaze direction and head angle as the original face, blended into the shot.")
    elif base and nomes:
        quem = ", ".join(nomes[:-1]) + (" and " if len(nomes) > 1 else "") + nomes[-1]
        partes.append(f"Recreate reference image {base['n']} shot-for-shot — the same framing and crop, camera angle, what is "
                      f"visible of each figure, body pose, head angle, gaze direction and facial expression — but with {quem} "
                      f"in place of the original {'person' if len(nomes) == 1 else 'people'}. The result must look like image "
                      f"{base['n']} re-shot, not like the character reference.")
    elif nomes:
        partes.append(("A single image of " + ", ".join(nomes[:-1]) + (" and " if len(nomes) > 1 else "") + nomes[-1]) + ".")
    else:
        partes.append("A single image.")
    for r in pac["refs"]:
        regra = r["papel"]
        if r["papel"] == "personagem":
            regra = {"rosto": "personagem_rosto", "inteira": "personagem"}.get(r.get("troca") or "auto", "personagem_auto")
        frase = _REGRA_PAPEL[regra].format(n=r["n"], nome=r["nome"] or f"the character from image {r['n']}", alvo=alvo)
        partes.append(frase[0].upper() + frase[1:] + (f" (note: {r['obs']})" if r["obs"] else "") + ".")
    if pers:
        partes.append(IGNORAR_REF)
    so_rosto = bool(pers) and all(r.get("troca") == "rosto" for r in pers)
    if pac.get("obs_geral"):
        partes.append("Scene: " + pac["obs_geral"] + ".")
    if pac.get("estilo_en"):
        partes.append("Art style of the final image: " + pac["estilo_en"].rstrip(".") + ".")
    elif so_rosto and base:  # só o rosto: a cena fica como está (a foto continua foto)
        partes.append(f"Keep the look of reference image {base['n']} exactly (same photo/film look, colors and light); only the "
                      "face/head changes.")
    elif pers:  # sem estilo escolhido: segue o dos personagens novos (desenho → cena desenhada; foto → realista)
        partes.append("Art style of the final image: the SAME look as the new character reference images (if they are "
                      "drawings/anime, render the whole scene in that drawn style; if they are photos, photorealistic) — "
                      "never the style of the base or pose image.")
    partes.append("Keep every character's identity consistent with their reference; natural, coherent result.")
    return " ".join(partes)


# ------------------------------------------------------------------ com IA (olhando as fotos)
SISTEMA = """You write ONE image-generation prompt for Google Flow (Nano Banana / Imagen) that will receive the reference
images below IN THIS ORDER (reference image 1, 2, 3…). The user said what each image is for and may add notes per image and
a general note (often in Portuguese).
THE MOST COMMON FAILURE: the model pastes the character reference as it is (its own pose, gesture, props, expression) on
top of the base. Prevent it: when there is a BASE or POSE image, START the prompt with a precise description of that image
written as the target — "Recreate reference image 1 shot-for-shot: <framing and crop; exactly what is visible of each figure
(e.g. only the face pushed through a jagged hole smashed in a wooden bathroom door); body pose; head tilt; gaze direction;
facial expression (e.g. manic wide grin showing teeth, eyes darting sideways); hands; light> — with <character> in place of
<the person>." Then say plainly that from each character reference only its LOOK is used (face/head design, body shape,
colors, outfit, art style) and that its pose, gesture (e.g. a thumbs-up), held objects (e.g. a beer mug) and expression are
IGNORED unless a note asks to keep them. Adapt the new character's anatomy to the base pose (a cartoon mascot can lean,
grin, peek through a hole…).
CONTEXT FIRST (for every character marked "SWAP: AUTOMATIC" — the default): look at what the BASE shows of the figure
being replaced (only a face through a hole? a full body in a suit? hands holding something?) and at what the CHARACTER
reference really shows (only a head? half body? full body with an outfit and props?). Then:
  • what the scene shows but the reference does not (e.g. the body, clothes, hands, shoes) → DESIGN it and DESCRIBE it in
    the prompt so it matches BOTH the character (its palette, style, species, personality) and the scene (place, era,
    situation, action) — e.g. a character given only as a face, placed in a full-body shot at a fancy party, gets an outfit
    in its own colors that fits a fancy party;
  • what the reference has that the scene does not use (its pose, gesture, props, background) → leave it out;
  • vice versa: if a detail of the base clashes with the character (e.g. a human hand gesture for a creature with paws, a
    prop that makes no sense for it), adapt that detail so the character fits naturally, keeping the idea of the scene;
  • say in "explicacao" what you invented or adapted.
A character marked "SWAP THE WHOLE FIGURE": everything about the figure comes from the photo (still in the base pose and
expression). A character marked "SWAP FACE/HEAD ONLY": only the head/face of that figure changes into the character's head design; the
body, clothes, hands, the whole scene, the framing AND the look (photo stays photo) of the base stay exactly the same, and
the new face makes the original expression, gaze and head angle — like a face replacement, not a new scene.
Your prompt must also:
- say explicitly what to take from each reference by its number: a POSE image gives only body pose / framing / camera
  angle (never its identity, clothes or background); a BASE image (a real photo used as base) gives the whole composition —
  framing, positions, poses, scenery and objects unless replaced — but its PEOPLE are placeholders replaced entirely; a
  CHARACTER image replaces the WHOLE figure (face, hair, body type, skin tone, clothes AND their colors — never just the
  face; keep the base pose AND the facial expression/emotion of the figure being replaced — the new face shows the ORIGINAL
  emotion, never the expression of the character photo) — call the character by the given name; SCENERY gives the place; OUTFIT the clothes; OBJECT
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
- be concrete about the final image (action, expressions, setting, light, lens) in natural English, 80–200 words;
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
                                         + ({"rosto": " — SWAP FACE/HEAD ONLY (keep the rest of the base as it is)",
                                             "inteira": " — SWAP THE WHOLE FIGURE (face, body, clothes from this photo)"}.get(
                                                 r.get("troca") or "", " — SWAP: AUTOMATIC (you decide; complete what is missing)")
                                            if r["papel"] == "personagem" else "")
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
