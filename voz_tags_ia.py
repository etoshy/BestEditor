"""
🤖🎭 v84_375 — o Claude coloca as tags de emoção no roteiro (diretor de locução).

Dois modos:
  "pt"  → modo expressivo do Chatterbox pt (tags em português: [soprosa] [dramatica] [respira] [pausa] *ênfase* …)
  "en"  → Chatterbox Turbo (inglês: [laugh] [sigh] [whispering] [dramatic] …)

Regra de ouro: a IA SÓ insere tags. Se o texto voltar com qualquer palavra trocada, tirada ou acrescentada,
aquele pedaço é descartado e fica o original (o roteiro nunca muda por causa disso).
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

_RAIZ = os.path.dirname(os.path.abspath(__file__))
if os.path.join(_RAIZ, "toolkit") not in sys.path:
    sys.path.insert(0, os.path.join(_RAIZ, "toolkit"))

RECURSO = "voz_tags"
MAX_CHARS_POR_PEDIDO = 5000

TURBO_SOM = ["laugh", "chuckle", "sigh", "gasp", "cough", "clear throat", "sniff", "groan", "shush"]
TURBO_ESTILO = ["narration", "happy", "sarcastic", "surprised", "dramatic", "whispering", "fear", "angry", "crying",
                "advertisement"]
_TAG_TURBO = re.compile(r"\[(" + "|".join(re.escape(t) for t in TURBO_SOM + TURBO_ESTILO) + r")\]", re.IGNORECASE)


def _exp():
    from tts import expressivo  # type: ignore
    return expressivo


def tem_tags(texto: str, modo: str) -> bool:
    if modo == "en":
        return bool(_TAG_TURBO.search(texto or ""))
    return _exp().tem_tags(texto or "")


def sem_tags(texto: str, modo: str) -> str:
    if modo == "en":
        return re.sub(r"[ \t]{2,}", " ", _TAG_TURBO.sub("", texto or "")).strip()
    return _exp().texto_sem_tags(texto or "")


def _palavras(t: str) -> List[str]:
    t = unicodedata.normalize("NFC", t or "").lower()
    return re.findall(r"\w+", t)


def mesmo_texto(original: str, com_tags: str, modo: str) -> bool:
    """A IA só pôs tags? (compara as palavras, ignorando espaço/pontuação extra que a tag possa ter mexido)."""
    return _palavras(sem_tags(com_tags, modo)) == _palavras(original)


# ------------------------------------------------------------------ instruções
_REGRAS_COMUNS = """REGRAS ABSOLUTAS
- Você é um diretor de locução. Sua ÚNICA ação é INSERIR tags no texto. NUNCA troque, corrija, traduza, tire nem
  acrescente palavras, números ou pontuação. Mantenha as quebras de linha e os parágrafos exatamente como estão.
- Marcas como [[INSCREVA]], [[VENDA: ...]] e qualquer outro colchete que não esteja na lista ficam IGUAIS, no mesmo lugar.
- Menos é mais: tag demais soa artificial. Use a tag só onde ela muda de verdade o jeito de falar.
- Devolva o texto COMPLETO, do começo ao fim, com as tags inseridas."""

_SISTEMA_PT = """Você recebe um roteiro de narração em {lingua} e coloca as tags do modo expressivo do Chatterbox.

TAGS PERMITIDAS (só estas):
{tags}

COMO DIRIGIR (técnica de locução profissional)
- A base é a leitura [linear]/[plena]: clara, sem valorizar tudo. Comece o texto com um estilo (normalmente [plena]
  ou [linear]) e só troque quando o CLIMA do trecho mudar (mistério → [suspense]/[dramatica]; algo leve ou engraçado
  → [sorridente]; conversa com quem assiste → [camarada]; notícia/fato → [reportagem]; chamada de venda → [projetada];
  intimidade/segredo → [soprosa]; conclusão serena → [calma]). Estilo vale até o próximo: não repita o mesmo à toa.
- Palavra de valor: *palavra* (asteriscos) em NO MÁXIMO uma palavra ou expressão curta a cada 2–3 frases — a que carrega
  o sentido (a surpresa, o número, o contraste). Nunca em artigos/preposições, nunca duas na mesma frase.
- [respira] no começo de alguns parágrafos novos ou antes de uma frase longa e importante (não em todos).
- [pausa] antes de uma revelação ou depois de uma pergunta retórica; [pausa longa] só em virada forte de clima;
  [pausa curta] para separar itens de efeito. Não ponha pausa onde já há ponto final seguido de parágrafo.
- Sons ({sons}) só quando o texto PEDE claramente (alguém ri, suspira, tosse; uma piada acabou de ser dita).
  No máximo 1 som a cada ~150 palavras. Na dúvida, não ponha.
- As tags ficam entre as palavras, coladas no ponto exato (ex.: "... noite. [pausa] Nunca mais ..." ).

{regras}"""

_SISTEMA_EN = """You receive a narration script for Chatterbox Turbo (English TTS) and insert its paralinguistic tags.

ALLOWED TAGS (only these):
- Sounds (exactly where the sound happens): {sons}
- Delivery (at the START of a sentence, changes how that sentence is read): {estilos}

HOW TO DIRECT
- Most sentences need NO tag. Use a delivery tag only where the mood clearly shifts (a joke → [happy] or [sarcastic];
  a reveal → [surprised]; a secret → [whispering]; a tragic moment → [dramatic]; an ad/call to action → [advertisement]).
- Sounds only when the text implies them (someone laughs, sighs, coughs; right after a joke a [chuckle]).
  At most ~1 sound per 120 words.
- Never translate: if the script is not English, still only insert tags.

{regras}"""

_REGRAS_EN = """ABSOLUTE RULES
- You are a voice director. Your ONLY action is to INSERT tags. NEVER change, fix, translate, remove or add words,
  numbers or punctuation. Keep line breaks and paragraphs exactly as they are.
- Markers like [[INSCREVA]], [[VENDA: ...]] and any other bracket not in the list stay EXACTLY where they are.
- Less is more: too many tags sound fake.
- Return the COMPLETE text, start to end, with the tags inserted."""


def sistema(modo: str, variante: str = "pt-BR") -> str:
    if modo == "en":
        return _SISTEMA_EN.format(sons=" ".join(f"[{t}]" for t in TURBO_SOM),
                                  estilos=" ".join(f"[{t}]" for t in TURBO_ESTILO), regras=_REGRAS_EN)
    e = _exp()
    var = "pt-PT" if variante == "pt-PT" else "pt-BR"
    linhas = []
    for grupo, itens in e.AJUDA[var]:
        linhas.append(f"{grupo}:")
        linhas += [f"  {tag} — {exp_}" for tag, exp_ in itens if tag.startswith(("[", "*"))
                   and not tag.startswith(("[emo", "[cfg", "[velocidade", "[normal"))]  # ajuste fino fica pra você
    sons = [tag for grupo, itens in e.AJUDA[var] for tag, _ in itens if grupo.startswith("Sons")]
    return _SISTEMA_PT.format(lingua="português de Portugal" if var == "pt-PT" else "português do Brasil",
                              tags="\n".join(linhas), sons=" ".join(sons), regras=_REGRAS_COMUNS)


SCHEMA = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"],
          "additionalProperties": False}


def _pedacos(texto: str) -> List[str]:
    """Divide por parágrafos em blocos de até MAX_CHARS_POR_PEDIDO (cada um é validado sozinho)."""
    pars = re.split(r"(\n\s*\n)", texto)
    blocos, atual = [], ""
    for p in pars:
        if len(atual) + len(p) > MAX_CHARS_POR_PEDIDO and atual.strip():
            blocos.append(atual)
            atual = ""
        atual += p
    if atual:
        blocos.append(atual)
    return blocos


def aplicar(texto: str, modo: str = "pt", variante: str = "pt-BR", on_log: Optional[Callable[[str], None]] = None,
            chamar: Optional[Callable[..., Any]] = None, forcar: bool = False) -> Tuple[str, Dict[str, Any]]:
    """Devolve (texto com tags, info). Pedaço que a IA estragou (mudou palavras) volta como estava."""
    log = on_log or (lambda s: None)
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    sis = sistema(modo, variante)
    saida, info = [], {"pedacos": 0, "ok": 0, "recusados": 0, "sem_ia": 0}
    for bloco in _pedacos(texto):
        if not bloco.strip():
            saida.append(bloco)
            continue
        info["pedacos"] += 1
        lead = bloco[:len(bloco) - len(bloco.lstrip())]
        trail = bloco[len(bloco.rstrip()):]
        nucleo = bloco.strip()
        r = chamar(RECURSO, sis, nucleo, schema=SCHEMA, max_tokens=min(16000, len(nucleo) // 2 + 1500),
                   effort="medium", forcar=forcar, timeout=180.0)
        novo = (r or {}).get("texto") if isinstance(r, dict) else None
        if not novo:
            info["sem_ia"] += 1
            saida.append(bloco)
            continue
        if not mesmo_texto(nucleo, novo, modo):
            info["recusados"] += 1
            log("⚠ A IA mexeu nas palavras de um trecho — esse trecho ficou como estava (sem tags).")
            saida.append(bloco)
            continue
        info["ok"] += 1
        saida.append(lead + novo.strip() + trail)
    return "".join(saida), info


def motivo_sem_ia() -> Optional[str]:
    try:
        import ia_servico
        return ia_servico.motivo_desligado(RECURSO)
    except Exception as exc:  # noqa: BLE001
        return str(exc)
