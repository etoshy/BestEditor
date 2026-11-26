"""🧑 v84_496 — Thumbnails no estilo PERSONAGEM (o "mascote" do canal na cena, tipo os canais de YouTube de crescimento):

  o personagem grande, da cintura pra cima, com uma emoção forte, segurando/usando um OBJETO-SÍMBOLO enorme do tema
  (celular gigante, botão vermelho, papel pegando fogo…), 1 a 3 palavras GIGANTES em amarelo com contorno preto no
  alto, fundo com PERSPECTIVA (corredor, palco, sala que foge pro fundo, luzes), cores saturadas e luz de contorno —
  pintura digital semirrealista.

O PERSONAGEM vem de uma FOTO DE REFERÊNCIA que você envia: o rosto, o cabelo e a ROUPA COMPLETA (o estilo de vestimenta
inteiro) são copiados dela em toda thumb. A foto fica salva como PADRÃO do canal (do 🕵️ modelo de vídeo — ex.: 🧠
Raciocínio Maldito) e os outros projetos desse canal já começam com ela; num projeto dá pra trocar por outra só nele.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional

PASTA = "thumbs_personagens"
EXT_OK = (".png", ".jpg", ".jpeg", ".webp")
N_PADRAO = 3

REGRA = (
    "ESTILO PERSONAGEM — o personagem do canal é o protagonista da thumb, do jeito dos canais grandes de YouTube "
    "(as thumbs de \"Como eu fiz X\", \"Explodi um canal\"): aplique ao ROTEIRO DESTE vídeo, sem copiar exemplo.\n"
    "1) O NERVO: qual é a promessa ou o choque do vídeo pra quem assiste? A thumb mostra ESSE momento.\n"
    "2) O OBJETO-SÍMBOLO: UMA coisa concreta, ENORME e óbvia que resume o tema e que o personagem segura, aperta, usa "
    "ou encara (um celular gigante com um número, um botão vermelho, um papel pegando fogo, um microfone, uma balança, "
    "um cérebro de vidro, uma corrente quebrada…). Nada de cena com muitos objetos.\n"
    "3) A EMOÇÃO: rosto bem expressivo e legível no celular — confiante, chocado, desconfiado, sorriso de canto, "
    "olhando pra câmera; o gesto nasce do objeto (segurar, apontar, apertar, mostrar). Nunca o joinha.\n"
    "4) A PALAVRA: \"texto\" = 1 a 3 palavras GRANDES (no idioma do vídeo, MAIÚSCULAS, do povo, até ~14 letras no "
    "total) que vão ESCRITAS na imagem, no alto — complementam o título, não repetem. Pode ser um número forte "
    "(\"+196K\", \"1 SEGUNDO\").\n"
    "5) O FUNDO com PERSPECTIVA: um lugar ligado ao tema que FOGE pro fundo (corredor, palco com luzes, sala de "
    "servidores, rua à noite, estúdio, biblioteca), com profundidade e luz forte atrás do personagem; cores saturadas "
    "e contrastantes (vermelho × azul, amarelo × roxo, laranja × ciano). Nada de fundo chapado.\n"
    "6) RUIM: personagem pequeno, cena genérica, muitos elementos, texto longo, repetir a cena/objeto de outra thumb.\n"
    "7) Monetizável: nada de sangue real, nudez, pessoa famosa ou criança. NÃO descreva o rosto nem a roupa do "
    "personagem no prompt (vêm da foto de referência) — descreva pose, expressão, o objeto e o fundo.")

ESTILO = ("Bold viral YouTube thumbnail, 16:9, semi-realistic digital painting with crisp illustrated edges (like a "
          "high-end editorial illustration), very saturated complementary colors, strong rim light and glow, dramatic "
          "depth with a background in strong PERSPECTIVE (vanishing point behind the character), the character big "
          "in the foreground from the waist up, shallow depth of field behind")


def _raiz(base: str) -> str:
    return os.path.join(base, PASTA)


def _arq_presets(base: str) -> str:
    return os.path.join(_raiz(base), "presets.json")


def presets(base: str) -> Dict[str, Any]:
    try:
        with open(_arq_presets(base), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_presets(base: str, d: Dict[str, Any]) -> None:
    os.makedirs(_raiz(base), exist_ok=True)
    tmp = _arq_presets(base) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _arq_presets(base))


def chave_canal(base: str, origem: str, pid: str) -> str:
    """O "canal" do preset: o 🕵️ modelo de vídeo do projeto (ex.: raciocinio_maldito); sem modelo = "padrao"."""
    if origem == "dossie":
        try:
            import dossies as ds
            return str((ds.carregar(base, pid).get("config") or {}).get("modelo") or "padrao")
        except Exception:  # noqa: BLE001
            return "padrao"
    if origem == "avulso":
        try:
            import thumbs_flow as tf
            return re.sub(r"[^\w-]", "", str(tf.carregar(base, origem, pid).get("canal") or "")) or "padrao"
        except Exception:  # noqa: BLE001
            return "padrao"
    return "padrao"


def referencia(base: str, origem: str, pid: str) -> Dict[str, Any]:
    """{"arquivo", "de": "projeto"|"canal"|"", "canal"} — a foto deste projeto, ou a padrão do canal."""
    import thumbs_flow as tf
    d = tf.carregar(base, origem, pid)
    proj = (d.get("personagem") or {}).get("arquivo") or ""
    canal = chave_canal(base, origem, pid)
    if proj and os.path.isfile(proj):
        return {"arquivo": proj, "de": "projeto", "canal": canal}
    pre = (presets(base).get(canal) or {}).get("arquivo") or ""
    if pre and os.path.isfile(pre):
        return {"arquivo": pre, "de": "canal", "canal": canal}
    return {"arquivo": "", "de": "", "canal": canal}


def salvar_referencia(base: str, origem: str, pid: str, conteudo: bytes, nome: str, como_padrao: bool = True) -> Dict[str, Any]:
    """A foto enviada vira a referência deste projeto e (se marcado) a PADRÃO do canal — os outros projetos já usam."""
    import thumbs_flow as tf
    ext = os.path.splitext(nome or "")[1].lower() or ".png"
    if ext not in EXT_OK:
        raise tf.ThumbErro("Mande uma imagem .png, .jpg ou .webp.")
    if not conteudo or len(conteudo) < 1000:
        raise tf.ThumbErro("A imagem veio vazia.")
    if len(conteudo) > 15_000_000:
        raise tf.ThumbErro("Imagem grande demais (máx. 15 MB).")
    canal = chave_canal(base, origem, pid)
    os.makedirs(_raiz(base), exist_ok=True)
    destino = os.path.join(_raiz(base), f"{canal}_{int(time.time())}{ext}")
    with open(destino, "wb") as f:
        f.write(conteudo)
    with tf._TRAVA:
        d = tf.carregar(base, origem, pid)
        d["personagem"] = {"arquivo": destino, "quando": time.time()}
        tf.salvar(base, origem, pid, d)
    if como_padrao:
        pr = presets(base)
        pr[canal] = {"arquivo": destino, "quando": time.time()}
        _gravar_presets(base, pr)
    return referencia(base, origem, pid)


def usar_padrao(base: str, origem: str, pid: str) -> Dict[str, Any]:
    """Este projeto volta a usar a foto padrão do canal."""
    import thumbs_flow as tf
    with tf._TRAVA:
        d = tf.carregar(base, origem, pid)
        d.pop("personagem", None)
        tf.salvar(base, origem, pid, d)
    return referencia(base, origem, pid)


def tornar_padrao(base: str, origem: str, pid: str) -> Dict[str, Any]:
    """A foto deste projeto vira a padrão do canal."""
    r = referencia(base, origem, pid)
    if r["arquivo"]:
        pr = presets(base)
        pr[r["canal"]] = {"arquivo": r["arquivo"], "quando": time.time()}
        _gravar_presets(base, pr)
    return referencia(base, origem, pid)


def prompt(it: Dict[str, Any], com_referencia: bool = True) -> str:
    """O prompt do Flow de uma thumb modo "personagem" (a palavra vai DENTRO da imagem)."""
    cena = (it.get("prompt") or it.get("ideia") or "").strip().rstrip(".,")
    palavra = " ".join(str(it.get("texto") or "").upper().split())[:30]
    ref = ("CHARACTER: use the person in the attached reference image as the character — keep EXACTLY the same face, hair, "
           "facial hair, skin tone and body type, and copy the COMPLETE outfit from the reference (every garment, the cut, "
           "the colors, patterns and accessories — the whole clothing style, head to toe as far as it shows). Same "
           "character in the same clothes, only the pose, expression and scene change; render him in the illustration "
           "style below (not a photo). " if com_referencia else
           "CHARACTER: one recognizable adult character, expressive face, distinctive outfit. ")
    letras = (f'TEXT: huge bold heavy sans-serif capital letters spelling exactly "{palavra}" at the top of the image '
              "(or the top-left), bright yellow (#FFD400) with a thick black outline and a soft drop shadow, perfectly "
              "spelled, easy to read on a phone, partly overlapping the background but never covering the face. "
              "Only that text, nothing else written. " if palavra else "No text or letters anywhere in the image. ")
    return (f"{ESTILO}. {ref}SCENE: {cena}. The symbolic object is huge, close to the camera and obvious at thumbnail size; "
            f"the face is large, lit and very expressive. {letras}"
            "NO thumbs-up gesture. Keep the illustration style described at the start.").replace(". .", ".")


def pedir_ideias(titulo: str, contexto: str, ja: List[Dict[str, Any]], q: int = N_PADRAO, idioma: str = "pt",
                 modelo: str = "", outros: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, Any]]:
    """🤖 `q` thumbnails no estilo personagem (cada uma com cena, objeto e palavra próprios + 2 títulos)."""
    import ia_servico as ia
    import thumbs_flow as tf
    motivo = None if str(modelo or "").startswith("cc:") else ia.motivo_desligado("roteiros")
    if motivo:
        raise tf.ThumbErro("IA: " + motivo + " — ligue em 🤖 IA (📝 Roteiros direto na IA).")
    existentes = "\n".join(f"- [{i.get('texto') or ''}] {i.get('ideia')}" for i in ja if i.get("ideia"))[:3000]
    system = f"""Você cria THUMBNAILS de YouTube que dão MUITO clique sem enganar. Para o vídeo abaixo, crie {q} thumbnails no
estilo PERSONAGEM, cada uma com "modo": "personagem".
{REGRA}
Para cada uma:
- "ideia": a cena e por que dá clique (1 frase, em português);
- "texto": as 1 a 3 palavras GRANDES escritas na imagem (idioma do vídeo: {idioma});
- "prompt": a cena EM INGLÊS pro Google Flow: pose e expressão do personagem, o objeto-símbolo (grande, o que ele faz
  com ele), o fundo em perspectiva e a luz/cores — SEM descrever o rosto nem a roupa (vêm da foto) e SEM descrever as
  letras (o site põe);
- "modo": "personagem";
- "titulos": 2 títulos pra ESTA thumbnail. {tf.REGRA_TITULOS_THUMB}
Cada thumbnail com um objeto e um fundo DIFERENTES.
{('Já existem estas (NÃO repita a cena, o objeto nem a palavra):' + chr(10) + existentes) if existentes else ''}
{tf.bloco_outros(outros or [])}
Responda só o JSON."""
    conteudo = f"Título do vídeo: {titulo}\n\nSobre o vídeo / roteiro:\n{(contexto or '')[:12000]}"
    with ia.rotulo("🧑 Thumbs personagem: " + (titulo or "")[:60]):
        d = ia.chamar("roteiros", system, conteudo, schema=tf._schema_ideias(), max_tokens=1500 + 1200 * q, effort="medium",
                      timeout=300, cache_local=False, modelo=modelo)
    if not d:
        raise tf.ThumbErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
    out = []
    for x in (d.get("thumbnails") if isinstance(d, dict) else d) or []:
        t = tf.normalizar(dict(x, modo="personagem") if isinstance(x, dict) else x)
        if t and not tf.repete_outro_video(t, outros or []):
            out.append(t)
    if not out:
        raise tf.ThumbErro("a IA não sugeriu nenhuma thumbnail")
    _mq = ia.ultimo_modelo()
    return [dict(t, modelo_ia=_mq) if _mq else t for t in out[:q]]
