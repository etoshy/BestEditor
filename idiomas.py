"""
idiomas.py
===========

O IDIOMA DO VÍDEO segue o idioma da narração — de ponta a ponta:

  * o Gerador de voz descobre o idioma da narração (o escolhido na tela; senão
    pela voz/motor: voz Piper `pt_BR-...`, voz Kokoro `pf_...`, idioma do
    XTTS/Chatterbox, Chatterbox Turbo = inglês; senão pelo próprio texto) e
    grava num `info.json` dentro do .zip de narração + legenda;
  * ao enviar esse .zip pra gerar o vídeo, o idioma vem dele sozinho (o campo
    "Idioma da narração" fica em "Automático"; escolher um idioma ali sobrepõe);
  * .zip sem info.json: detecta pelo texto da legenda; áudio solto: o Whisper detecta;
  * todos os prompts pra IA levam a REGRA DE IDIOMA: todo texto que aparece no
    vídeo (textos na tela, destaques, títulos, gráficos, overlays) tem que
    estar no idioma da narração — nada em outra língua.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Dict, Optional

# código -> (nome em português, nome no próprio idioma)
IDIOMAS: Dict[str, tuple] = {
    "pt": ("Português", "português do Brasil"),
    "en": ("Inglês", "English"),
    "es": ("Espanhol", "español"),
    "fr": ("Francês", "français"),
    "it": ("Italiano", "italiano"),
    "de": ("Alemão", "Deutsch"),
    "nl": ("Holandês", "Nederlands"),
    "pl": ("Polonês", "polski"),
    "ru": ("Russo", "русский"),
    "tr": ("Turco", "Türkçe"),
    "ar": ("Árabe", "العربية"),
    "hi": ("Hindi", "हिन्दी"),
    "ja": ("Japonês", "日本語"),
    "ko": ("Coreano", "한국어"),
    "zh": ("Chinês", "中文"),
}
AUTO = "auto"

_NOMES = {
    "portugues": "pt", "portuguese": "pt", "brasileiro": "pt", "portugues do brasil": "pt",
    "ingles": "en", "english": "en", "espanhol": "es", "spanish": "es", "espanol": "es", "castellano": "es",
    "frances": "fr", "french": "fr", "francais": "fr", "italian": "it",
    "alemao": "de", "german": "de", "deutsch": "de", "holandes": "nl", "dutch": "nl",
    "polones": "pl", "polish": "pl", "russo": "ru", "russian": "ru", "turco": "tr", "turkish": "tr",
    "arabe": "ar", "arabic": "ar", "japones": "ja", "japanese": "ja", "coreano": "ko", "korean": "ko",
    "chines": "zh", "chinese": "zh", "mandarim": "zh",
}
# 1ª letra da voz do Kokoro = idioma (a/b = inglês americano/britânico, p = português...)
_KOKORO_LETRA = {"a": "en", "b": "en", "e": "es", "f": "fr", "h": "hi", "i": "it", "j": "ja", "p": "pt", "z": "zh"}


def normalizar(v: Any) -> Optional[str]:
    """"pt", "pt-BR", "pt_BR", "Português", "English" -> código; "auto"/vazio/desconhecido -> None."""
    if v is None:
        return None
    t = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().strip().lower()
    if not t or t == AUTO:
        return None
    if t in IDIOMAS:
        return t
    if t in _NOMES:
        return _NOMES[t]
    base = re.split(r"[-_ (]", t)[0]
    if base in IDIOMAS:
        return base
    return _NOMES.get(base)


def nome(codigo: Optional[str]) -> str:
    """"pt" -> "Português" (nome pra mostrar na tela)."""
    return IDIOMAS.get(codigo or "", (codigo or "?",))[0]


def lembrete_final(codigo: Optional[str]) -> str:
    """Última linha dos prompts de roteiro: repete o idioma de saída (as instruções e as fontes costumam estar em
    português — sem isso a IA tende a escrever em português mesmo pedindo outro idioma). Leva o código numa
    marca que o /ia/gerar lê."""
    if not codigo:
        return ""
    pt, proprio = IDIOMAS.get(codigo, (codigo, codigo))
    if codigo == "pt":
        return "LEMBRETE FINAL: escreva TODOS os textos do JSON em português do Brasil. (output language code: pt)"
    return (f"LEMBRETE FINAL / FINAL REMINDER: escreva TODOS os textos do JSON em {pt.lower()} ({proprio}) — roteiro, títulos, "
            f"capítulos, descrição, ideias, tags, CTA, observações —, mesmo com estas instruções e as fontes em português. "
            f"Write EVERY text value of the JSON in {proprio} (not Portuguese); keep the JSON keys exactly as given. "
            f"(output language code: {codigo})")


def nome_para_prompt(codigo: Optional[str]) -> str:
    """"pt" -> "português do Brasil (pt-BR)" — como o idioma aparece nos prompts."""
    if not codigo:
        return "o mesmo idioma da narração"
    if codigo == "pt":
        return "português do Brasil (pt-BR)"
    pt, proprio = IDIOMAS.get(codigo, (codigo, codigo))
    return f"{pt.lower()} — {proprio} ({codigo})"


_STOP = {
    "pt": "de que não um uma para com os as está você mas foi ele ela isso muito também então porque quando ainda já são seu sua pelo pela".split(),
    "en": "the and is are you that with this for was have not but they his her what there from were would which their been".split(),
    "es": "que de el los las una por con para está pero muy también cuando porque ella usted eso esto fue sus hay donde".split(),
    "fr": "le la les des est une pour avec dans pas que qui sur mais vous nous ils elle cette sont été très aussi".split(),
    "it": "il la che di non una per con sono anche questo della nel gli ma più molto quando perché lei lui".split(),
    "de": "der die das und ist nicht ein eine mit sich auf für ich sie es den dem auch wie aber wenn noch".split(),
}


def detectar_do_texto(texto: str) -> Optional[str]:
    """Adivinha o idioma do texto. None se não der pra saber."""
    t = str(texto or "")
    if not t.strip():
        return None
    for cod, rx in (("ja", r"[぀-ヿ]"), ("ko", r"[가-힯]"), ("zh", r"[一-鿿]"),
                    ("ru", r"[Ѐ-ӿ]"), ("ar", r"[؀-ۿ]"), ("hi", r"[ऀ-ॿ]")):
        if len(re.findall(rx, t)) >= 3:
            return cod
    palavras = re.findall(r"[a-zà-ÿ]+", re.sub(r"\[[^\]]*\]", " ", t.lower()))
    if len(palavras) < 3:
        return None
    contagem = {cod: sum(1 for p in palavras if p in set(lista)) for cod, lista in _STOP.items()}
    contagem["pt"] += 2 * len(re.findall(r"[ãõç]|ção|ções", t.lower()))
    contagem["es"] += 2 * len(re.findall(r"[ñ¿¡]|ción", t.lower()))
    melhor = max(contagem, key=contagem.get)
    ordenado = sorted(contagem.values(), reverse=True)
    if ordenado[0] < 2 or ordenado[0] == ordenado[1]:
        return None
    return melhor


def idioma_do_motor(engine: str, config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """O idioma que o motor de voz vai falar com essa configuração (None = não dá pra saber)."""
    c = config or {}
    engine = (engine or "").lower()
    if engine == "chatterbox_turbo":
        return "en"
    if engine == "piper":
        voz = str(c.get("nome_voz") or c.get("voz") or "")
        return normalizar(voz.split("-")[0]) if voz else None
    if engine == "kokoro":
        if c.get("idioma"):
            return normalizar(c["idioma"])
        voz = str(c.get("voz") or "")
        return _KOKORO_LETRA.get(voz[:1].lower()) if voz else None
    if engine in ("xtts", "chatterbox"):
        return normalizar(c.get("idioma"))
    return None


def descobrir(engine: str, config: Optional[Dict[str, Any]], texto: str, escolhido: Any = None) -> Dict[str, Any]:
    """Idioma da narração: o escolhido na tela > o do motor > o do texto."""
    for origem, cod in (("escolhido", normalizar(escolhido)), ("voz", idioma_do_motor(engine, config)),
                        ("texto", detectar_do_texto(texto))):
        if cod:
            return {"codigo": cod, "nome": nome(cod), "origem": origem}
    return {"codigo": None, "nome": "desconhecido", "origem": None}


def info_json(codigo: Optional[str], **extras: Any) -> str:
    """Conteúdo do `info.json` que vai dentro do .zip de narração."""
    return json.dumps({"idioma": codigo, "idioma_nome": nome(codigo) if codigo else None,
                       "gerado_por": "narration_video_site", **extras}, ensure_ascii=False, indent=1)


def ler_info(texto: Any) -> Optional[str]:
    """Idioma gravado num `info.json` (ou None)."""
    try:
        d = json.loads(texto)
    except (ValueError, TypeError):
        return None
    return normalizar(d.get("idioma") or d.get("language")) if isinstance(d, dict) else None


def regra_para_prompt(idioma: Optional[str]) -> str:
    """Bloco que entra nos prompts pra IA: o vídeo fala um idioma só.
    Aceita o código ("pt") ou um nome já pronto ("português do Brasil")."""
    cod = normalizar(idioma) if idioma else None
    alvo = nome_para_prompt(cod) if cod else (str(idioma) if idioma else nome_para_prompt(None))
    return (
        f"IDIOMA DO VÍDEO: {alvo}. A narração está nesse idioma, então TODO texto que vai APARECER no vídeo também tem "
        f"que estar em {alvo}: textos na tela (on_screen_text), destaques/títulos/selos, campos das cenas/templates, "
        "overlays de texto, gráficos (título, rótulos dos itens, unidade e fonte), nomes de capítulo e qualquer outra "
        "palavra escrita. Não misture idiomas, não traduza a fala e não deixe termos de outra língua (ex.: \"Breaking news\", "
        "\"Chapter 1\", \"Source:\") — escreva o equivalente no idioma do vídeo. Números, datas e moeda no formato desse "
        "idioma. Exceções: nomes próprios continuam como são, e os campos de BUSCA (\"query\", termos de pesquisa) e as "
        "descrições pra gerar imagem/animação podem ficar em inglês, porque não aparecem no vídeo."
    )
