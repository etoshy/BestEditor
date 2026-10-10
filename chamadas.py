"""Chamadas no roteiro: like/inscreva-se e venda — vídeos prontos seus.

No texto que vai pro TTS (Gerar voz, Roteiro do YouTube), numa linha própria:

    E foi assim que tudo começou.
    [[INSCREVA]]
    Mas a história não para por aí...
    [[VENDA]]

- O marcador não é lido; a geração de voz guarda o PONTO exato dele no áudio.
- No editor, cada chamada aparece na aba ✂️ Cortes. Com um vídeo (o seu de
  like/inscreva-se ou o de venda, com o áudio dele), a narração PAUSA ali, o
  vídeo toca inteiro e a narração continua. Sem vídeo, nada muda.
- Clipe padrão por tipo: envia uma vez e ele entra sozinho em todas as
  chamadas desse tipo, neste vídeo e nos próximos.
(Também aceita [[INSCREVA: frase]] — a frase é narrada e, com vídeo, sai e o
vídeo entra no lugar dela —, mas o uso normal é só a marca.)
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import unicodedata
import uuid
from typing import Any, Dict, List, Optional, Tuple

TIPOS: Dict[str, Dict[str, Any]] = {
    "inscreva": {"rotulo": "👍 Like / inscreva-se", "nomes": ["INSCREVA", "INSCREVASE", "INSCREVA-SE", "INSCREVER", "INSCRICAO", "LIKE", "CURTIR", "SUBSCRIBE", "SUB"]},
    "venda": {"rotulo": "🛒 Venda", "nomes": ["VENDA", "VENDER", "PRODUTO", "OFERTA", "AD", "ADS", "ANUNCIO", "PROPAGANDA", "PATROCINIO", "PUBLI", "SPONSOR"]},
}
_NOME_PARA_TIPO = {n: t for t, info in TIPOS.items() for n in info["nomes"]}
# [[NOME]] ou [[NOME: texto]] — o texto pode ter várias linhas
MARCADOR = re.compile(r"\[\[\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\- ]{0,20}?)\s*(?::\s*(.*?))?\s*\]\]", re.S)

PASTA_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chamadas_padrao")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def tipo_do_nome(nome: str) -> Optional[str]:
    n = _sem_acento(nome or "").upper().replace(" ", "")
    return _NOME_PARA_TIPO.get(n) or _NOME_PARA_TIPO.get(n.replace("-", ""))


def rotulo(tipo: str) -> str:
    return TIPOS.get(tipo, {}).get("rotulo", tipo)


def dividir(texto: str) -> List[Dict[str, Any]]:
    """Texto -> partes em ordem: {"tipo": None (narração comum) | "inscreva"|"venda",
    "texto": o que é falado}. Marcador de nome desconhecido vira texto comum."""
    partes: List[Dict[str, Any]] = []
    pos = 0
    for m in MARCADOR.finditer(texto or ""):
        tipo = tipo_do_nome(m.group(1))
        if not tipo:
            continue
        if m.start() > pos:
            partes.append({"tipo": None, "texto": texto[pos:m.start()]})
        partes.append({"tipo": tipo, "texto": (m.group(2) or "").strip()})
        pos = m.end()
    if pos < len(texto or ""):
        partes.append({"tipo": None, "texto": texto[pos:]})
    return [p for p in partes if p["tipo"] or p["texto"].strip()]


def tem_marcadores(texto: str) -> bool:
    return any(p["tipo"] for p in dividir(texto))


def remover_marcadores(texto: str) -> str:
    """Pra narrar: `[[INSCREVA: deixa o like]]` -> `deixa o like`; `[[INSCREVA]]` some."""
    def _troca(m):
        if not tipo_do_nome(m.group(1)):
            return m.group(0)
        return (m.group(2) or "").strip()
    return MARCADOR.sub(_troca, texto or "")


def desconhecidos(texto: str) -> List[str]:
    return sorted({m.group(1).strip() for m in MARCADOR.finditer(texto or "") if not tipo_do_nome(m.group(1))})


# ------------------------------------------------------------------ tempos
def de_duracoes(partes: List[Dict[str, Any]], duracoes: List[float]) -> List[Dict[str, Any]]:
    """Partes geradas uma a uma (duração de cada uma) -> chamadas com início/fim."""
    out, t = [], 0.0
    for p, d in zip(partes, duracoes):
        if p["tipo"]:
            out.append({"tipo": p["tipo"], "texto": p["texto"], "inicio": round(t, 3), "fim": round(t + (d if p["texto"] else 0.0), 3)})
        t += d
    return out


def _tokens(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", _sem_acento((s or "").lower()))


def alinhar(partes: List[Dict[str, Any]], palavras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Quando o áudio sai de uma vez só (multi voice): acha o texto de cada
    chamada nas palavras transcritas (Whisper) — tolera palavras trocadas."""
    toks: List[str] = []
    dono: List[int] = []
    for k, p in enumerate(partes):
        for tk in _tokens(p["texto"]):
            toks.append(tk)
            dono.append(k)
    ditas = [_tokens(w.get("word", "")) for w in palavras]
    plano, origem = [], []
    for j, tw in enumerate(ditas):
        for tk in tw:
            plano.append(tk)
            origem.append(j)
    casou: Dict[int, int] = {}
    for a, b, n in difflib.SequenceMatcher(None, toks, plano, autojunk=False).get_matching_blocks():
        for x in range(n):
            casou[a + x] = origem[b + x]
    out = []
    total = float(palavras[-1]["end"]) if palavras else 0.0
    for k, p in enumerate(partes):
        if not p["tipo"]:
            continue
        idx = [i for i, d in enumerate(dono) if d == k and i in casou]
        if idx:
            ini, fim = float(palavras[casou[idx[0]]]["start"]), float(palavras[casou[idx[-1]]]["end"])
        else:  # sem texto (ou não achou): ponto depois da última palavra antes dela
            antes = [casou[i] for i, d in enumerate(dono) if d < k and i in casou]
            depois = [casou[i] for i, d in enumerate(dono) if d > k and i in casou]
            ini = float(palavras[antes[-1]]["end"]) if antes else (float(palavras[depois[0]]["start"]) if depois else total)
            fim = ini
        out.append({"tipo": p["tipo"], "texto": p["texto"], "inicio": round(ini, 3), "fim": round(max(ini, fim), 3)})
    return out


def do_srt(segmentos: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Legenda (.srt) escrita/editada à mão com marcadores: tira o código da
    legenda e devolve as chamadas (a fala com marcador ocupa o bloco inteiro)."""
    limpos, chamadas = [], []
    for s in segmentos or []:
        txt = s.get("text") or ""
        partes = dividir(txt)
        if any(p["tipo"] for p in partes):
            for p in partes:
                if p["tipo"]:
                    com_texto = bool(p["texto"])
                    chamadas.append({"tipo": p["tipo"], "texto": p["texto"], "inicio": float(s["start"]),
                                     "fim": float(s["end"]) if com_texto else float(s["start"])})
            txt = " ".join(remover_marcadores(txt).split())
        if txt.strip():
            limpos.append(dict(s, text=txt))
    return limpos, chamadas


# ------------------------------------------------------------------ editor / montagem
def para_cortes(chamadas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chamadas -> itens da aba ✂️ Cortes (sem clipe = narração normal).
    Com várias marcas do mesmo tipo, o clipe padrão entra SÓ NA PRIMEIRA de
    cada tipo; as outras ficam desligadas (a narração segue normal ali) até a
    pessoa escolher, na aba ✂️ Cortes, em quais o vídeo entra."""
    out = []
    ja_tem: set = set()
    for c in sorted(chamadas or [], key=lambda x: float(x.get("inicio") or 0)):
        tipo = c.get("tipo") if c.get("tipo") in TIPOS else "inscreva"
        ini, fim = float(c.get("inicio") or 0), float(c.get("fim") or c.get("inicio") or 0)
        padrao = clipe_padrao(tipo) if tipo not in ja_tem else None
        item = {
            "id": uuid.uuid4().hex[:8], "chamada": True, "tipo": tipo, "texto": c.get("texto") or "",
            "insertion_point": round(ini, 3), "remove_ate": round(max(ini, fim), 3), "audio_mode": "pause",
            "description": f"{rotulo(tipo)}" + (f": “{c['texto']}”" if c.get("texto") else " (ponto marcado)"),
            "query": None, "resolved_path": padrao, "clipe_padrao": bool(padrao),
        }
        if tipo in ja_tem:
            item["desligada"] = True
        ja_tem.add(tipo)
        out.append(item)
    return out


def _mapa_padrao() -> Dict[str, str]:
    try:
        with open(os.path.join(PASTA_PADRAO, "padrao.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def clipe_padrao(tipo: str) -> Optional[str]:
    p = _mapa_padrao().get(tipo)
    return p if p and os.path.isfile(p) else None


def definir_padrao(tipo: str, caminho: Optional[str]) -> Optional[str]:
    """Guarda uma CÓPIA do clipe como padrão do tipo (None tira o padrão)."""
    if tipo not in TIPOS:
        raise ValueError("Tipo de chamada desconhecido.")
    os.makedirs(PASTA_PADRAO, exist_ok=True)
    mapa = _mapa_padrao()
    destino = None
    if caminho:
        destino = os.path.join(PASTA_PADRAO, f"{tipo}_{uuid.uuid4().hex[:6]}{os.path.splitext(caminho)[1].lower() or '.mp4'}")
        shutil.copy(caminho, destino)
        antigo = mapa.get(tipo)
        if antigo and antigo != destino and os.path.dirname(os.path.abspath(antigo)) == os.path.abspath(PASTA_PADRAO):
            try:
                os.remove(antigo)
            except OSError:
                pass
        mapa[tipo] = destino
    else:
        mapa.pop(tipo, None)
    with open(os.path.join(PASTA_PADRAO, "padrao.json"), "w", encoding="utf-8") as f:
        json.dump(mapa, f, ensure_ascii=False, indent=2)
    return destino


GUIA_TEXTO = (
    "Chamadas: escreva [[INSCREVA]] ou [[VENDA]] numa linha, onde o seu vídeo pronto deve entrar. "
    "O marcador não é lido; no editor, com o vídeo enviado, a narração pausa ali, o vídeo toca e a narração continua."
)


# marcas de cena do roteiro ([CENA 3], [Cena 2: luta no telhado], [[SCENE 4]], (CENA 5)…): não são pra
# ser faladas — o gerador de voz tira antes de narrar. As tags de voz ([laugh]) e as chamadas ficam.
MARCA_CENA = re.compile(r"(?:\[{1,2}|\()\s*(?:cena|scene|escena)\b[^\]\)\n]{0,160}(?:\]{1,2}|\))", re.IGNORECASE)


def tirar_marcas_de_cena(texto: str) -> Tuple[str, int]:
    """Texto sem as marcas de cena + quantas tirou."""
    # linha que só tem a marca some inteira (senão sobrava uma linha em branco = pausa a mais na voz)
    novo, n1 = re.subn(r"^[ \t]*(?:" + MARCA_CENA.pattern + r")[ \t]*(?:\n|$)", "", str(texto or ""), flags=re.IGNORECASE | re.MULTILINE)
    novo, n2 = MARCA_CENA.subn("", novo)
    n = n1 + n2
    if n:
        novo = re.sub(r"[ \t]+\n", "\n", novo)
        novo = re.sub(r"\n{3,}", "\n\n", novo)
        novo = re.sub(r"[ \t]{2,}", " ", novo).strip()
    return novo, n
