"""
Lê o JSON que a gente cola da IA (ChatGPT, Gemini, Claude…) mesmo quando ele
vem "estragado" pelo copiar/colar. Usado em todo lugar que recebe a resposta
colada (prompt principal, edição, roteiro do YouTube, modelados…).

O que conserta sozinho:
- ```json … ``` (cercas de código), texto antes/depois, "json" / "Copiar código"
  / "Copy code" que vêm junto quando copia o bloco;
- tudo numa linha só ou quebrado em lugar errado; quebra de linha e TAB de
  verdade dentro de um texto (o JSON exige \\n);
- barras de markdown do botão copiar: \\[\\[VENDA\\]\\], \\_, \\*, \\# …;
- aspas curvas “ ” ‘ ’ no lugar das aspas normais; espaço invisível/NBSP;
- aspas sem escape dentro de um texto ("ele disse "oi" pra ela");
- vírgula sobrando no fim ou faltando entre itens; comentários // e /* */;
- chave sem aspas, 'aspas simples', True/False/None do Python;
- resposta cortada no fim (fecha os textos, listas e objetos abertos);
- links que viraram markdown: [https://x](https://x) → https://x.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional

_INVISIVEIS = re.compile("[​‌‍⁠﻿­]")
_ESPACOS = re.compile("[      ]")
_ABRE_CURVA = "“„‟«"
_FECHA_CURVA = "”»"
_ESCAPES_OK = set('"\\/bfnrtu')
_LINHAS_LIXO = re.compile(r"^\s*(?:json|javascript|js|copiar c[oó]digo|copy code|copy|copiar|editar|edit|"
                          r"código|code)\s*$", re.IGNORECASE)
_LINK_MD = re.compile(r"\[(https?://[^\]\s]+)\]\((https?://[^)\s]+)\)")


def _limpar_bruto(texto: str) -> str:
    t = str(texto or "").replace("\r\n", "\n").replace("\r", "\n")
    t = _INVISIVEIS.sub("", t)
    t = _ESPACOS.sub(" ", t)
    return t.strip()


def _candidatos(texto: str) -> List[str]:
    """Pedaços que podem ser o JSON: o conteúdo de cada cerca ``` e o texto
    inteiro (sem as linhas "json"/"Copiar código")."""
    t = _limpar_bruto(texto)
    out: List[str] = []
    for m in re.finditer(r"```[ \t]*[A-Za-z]*[ \t]*\n?(.*?)(?:```|\Z)", t, re.S):
        if re.search(r"[{\[]", m.group(1)):
            out.append(m.group(1).strip())
    sem = "\n".join(l for l in t.replace("```", "\n").split("\n") if not _LINHAS_LIXO.match(l))
    out.append(sem.strip())
    # "json{...}" grudado (copiar com o mouse junta o rótulo do bloco)
    out = [re.sub(r"^(?:json|javascript)\s*(?=[{\[])", "", c, flags=re.IGNORECASE) for c in out]
    vistos, unicos = set(), []
    for c in out:
        if c and c not in vistos:
            vistos.add(c)
            unicos.append(c)
    return unicos


def _proximo_nao_espaco(t: str, i: int) -> int:
    n = len(t)
    while i < n and t[i] in " \t\n":
        i += 1
    return i


def _parece_chave(t: str, i: int) -> bool:
    """Em t[i] começa algo como "chave": ?"""
    return bool(re.match(r'["“][^"\n“”]{0,80}["”]\s*:', t[i:i + 90]))


class Cortado(ValueError):
    """A resposta acabou no meio (texto/lista/objeto sem fechar)."""


def consertar(texto: str, info: Optional[dict] = None) -> str:
    """Devolve o texto reescrito como JSON válido (ou o melhor possível).
    `info["cortado"]` = True se teve que fechar coisa aberta no fim."""
    t = _LINK_MD.sub(lambda m: m.group(2), texto)
    ini = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if ini < 0:
        return t
    out: List[str] = []
    pilha: List[str] = []
    n = len(t)
    i = ini
    ultimo = ""  # "valor" (acabou um valor), "abre", "virgula", "dois_pontos"

    def _pede_virgula() -> None:
        if ultimo == "valor" and pilha:
            out.append(",")

    while i < n:
        ch = t[i]
        if ch in " \t\n":
            i += 1
            continue
        # comentários
        if t.startswith("//", i):
            fim = t.find("\n", i)
            i = n if fim < 0 else fim
            continue
        if t.startswith("/*", i):
            fim = t.find("*/", i + 2)
            i = n if fim < 0 else fim + 2
            continue
        if ch == "\\" and i + 1 < n and t[i + 1] in "[]{}_*#\"'":
            # barra de markdown fora de texto: \[ \] \{ … → só o caractere
            i += 1
            continue
        if ch in "{[":
            _pede_virgula()
            out.append(ch)
            pilha.append("}" if ch == "{" else "]")
            ultimo = "abre"
            i += 1
            continue
        if ch in "}]":
            if not pilha:
                break
            while out and out[-1] in (",", ":"):
                out.pop()
            # fecha o que estiver aberto até achar o par certo
            if ch in pilha:
                while pilha and pilha[-1] != ch:
                    out.append(pilha.pop())
                out.append(pilha.pop())
            i += 1
            ultimo = "valor"
            if not pilha:
                break
            continue
        if ch == ",":
            if ultimo not in ("abre", "virgula", "dois_pontos"):
                out.append(",")
                ultimo = "virgula"
            i += 1
            continue
        if ch == ":":
            out.append(":")
            ultimo = "dois_pontos"
            i += 1
            continue
        if ch in '"\'' or ch in _ABRE_CURVA or ch in _FECHA_CURVA or ch in "‘’":
            _pede_virgula()
            abre = ch
            i += 1
            buf: List[str] = []
            while i < n:
                c = t[i]
                if c == "\\":
                    if i + 1 >= n:
                        i += 1
                        break
                    prox = t[i + 1]
                    if prox in _ESCAPES_OK and not (prox == "u" and not re.match(r"[0-9a-fA-F]{4}", t[i + 2:i + 6])):
                        buf.append(c + prox)
                    elif prox == "\n":
                        buf.append("\\n")
                    elif prox == "'":
                        buf.append("'")
                    else:
                        buf.append(prox if prox != '"' else '\\"')  # \[ \_ \* … do markdown
                    i += 2
                    continue
                fecha = (c == '"' if abre == '"' else
                         c == "'" if abre == "'" else
                         c in _FECHA_CURVA + '"' if abre in _ABRE_CURVA + _FECHA_CURVA else
                         c in "’'")
                if fecha:
                    j = _proximo_nao_espaco(t, i + 1)
                    seg = t[j] if j < n else ""
                    entre = t[i + 1:j]
                    if (seg in ",:}]" or j >= n or (seg in "{[" and "\n" in entre)
                            or (seg in '"“' and ("\n" in entre or _parece_chave(t, j)))
                            or (seg == "/" and t.startswith("//", j))):
                        i += 1
                        break
                    buf.append('\\"' if c == '"' else c)  # aspas de dentro do texto
                    i += 1
                    continue
                if c == '"':
                    buf.append('\\"')
                elif c == "\n":
                    buf.append("\\n")
                elif c == "\t":
                    buf.append("\\t")
                elif ord(c) < 32:
                    buf.append(" ")
                else:
                    buf.append(c)
                i += 1
            else:
                if info is not None:
                    info["cortado"] = True
            out.append('"' + "".join(buf) + '"')
            ultimo = "valor"
            continue
        # número, true/false/null, palavra solta (chave sem aspas)
        m = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", t[i:])
        if m:
            _pede_virgula()
            out.append(m.group(0))
            i += len(m.group(0))
            ultimo = "valor"
            continue
        m = re.match(r"[A-Za-z_À-ÿ][\w\-À-ÿ]*", t[i:])
        if m:
            palavra = m.group(0)
            j = _proximo_nao_espaco(t, i + len(palavra))
            _pede_virgula()
            if j < n and t[j] == ":":
                out.append(json.dumps(palavra))
            else:
                out.append({"true": "true", "false": "false", "null": "null", "none": "null", "nil": "null",
                            "undefined": "null", "nan": "null"}.get(palavra.lower(), json.dumps(palavra)))
            i += len(palavra)
            ultimo = "valor"
            continue
        i += 1  # caractere estranho fora de texto: ignora
    while out and out[-1] in (",", ":"):
        if out[-1] == ":":
            out.append("null")
            break
        out.pop()
    if pilha and info is not None:
        info["cortado"] = True
    while pilha:
        out.append(pilha.pop())
    return "".join(out)


def _contexto(t: str, pos: int) -> str:
    return t[max(0, pos - 40):pos + 40].replace("\n", " ")


def _sem_links_md(d: Any) -> Any:
    if isinstance(d, str):
        return _LINK_MD.sub(lambda m: m.group(2), d) if "](" in d else d
    if isinstance(d, list):
        return [_sem_links_md(x) for x in d]
    if isinstance(d, dict):
        return {k: _sem_links_md(v) for k, v in d.items()}
    return d


def carregar(texto: str, aceitar_cortado: bool = False) -> Any:
    """JSON da resposta colada. ValueError com uma mensagem amigável se nem
    consertando der pra ler. Resposta cortada no fim (a IA parou no meio) só
    passa com aceitar_cortado=True — senão avisa pra pedir pra IA continuar."""
    return _sem_links_md(_carregar(texto, aceitar_cortado))


def _carregar(texto: str, aceitar_cortado: bool = False) -> Any:
    if not str(texto or "").strip():
        raise ValueError("Cole a resposta da IA (o JSON).")
    cands = _candidatos(texto)
    primeiro_erro: Optional[json.JSONDecodeError] = None
    for c in cands:
        try:
            return json.loads(c)
        except json.JSONDecodeError as exc:
            primeiro_erro = primeiro_erro or exc
    tem_json = False
    for c in cands:
        if not re.search(r"[{\[]", c):
            continue
        tem_json = True
        info: dict = {}
        try:
            d = json.loads(consertar(c, info))
        except json.JSONDecodeError:
            continue
        if info.get("cortado") and not aceitar_cortado:
            raise Cortado("O JSON está incompleto — a IA cortou a resposta no meio. Peça pra ela continuar "
                          "(ou gerar de novo) e cole a resposta inteira.")
        return d
    try:  # se tiver o pacote json_repair instalado, é a última tentativa
        from json_repair import repair_json  # type: ignore
        for c in cands:
            if re.search(r"[{\[]", c):
                d = json.loads(repair_json(c))
                if isinstance(d, (dict, list)) and d:
                    return d
    except Exception:  # noqa: BLE001
        pass
    if not tem_json:
        raise ValueError("Não achei um JSON na resposta (tem que ter { … }).")
    e = primeiro_erro
    raise ValueError("Não consegui ler o JSON nem consertando"
                     + (f" — erro perto de “…{_contexto(e.doc, e.pos)}…”" if e else "")
                     + ". Confira se copiou a resposta inteira (se a IA cortou, peça pra ela continuar).")


def objeto(texto: str) -> Any:
    """Igual a carregar(), mas se vier uma lista com um objeto só, devolve o objeto."""
    d = carregar(texto)
    if isinstance(d, list) and len(d) == 1 and isinstance(d[0], dict):
        return d[0]
    return d
