"""📚 Texto bruto → vários vídeos (v84_368).

Você manda UM arquivo de texto bruto (transcrição de curso/aula/palestra, livro, anotações) e escolhe o 🕵️ Modelo de vídeo
(ex.: 🏛 CenarioM — Filosofia, que vem do pacote do canal). Aí:

  1. 🤖 a IA lê o texto inteiro e separa os TEMAS que rendem um vídeo sozinho — título, o que o vídeo cobre, por que
     funciona em vídeo, uma ideia de abertura, o formato do modelo que combina e o TEMPO estimado (com o porquê);
  2. você marca os que quer (e muda título, formato ou minutos);
  3. 🚀 o site cria um Modelo de vídeo por tema e, em paralelo, para cada um: a IA escreve as NOTAS do tema (só o que o
     texto diz sobre ele, sem nada do curso/aula/de quem falou), que viram a fonte do projeto → roteiro completo →
     (opcional) 🪄 revisão + 🎙 adaptar pro TTS;
  4. 🏭 os roteiros prontos vão pra Produção no pod (narração no pod + cenas), já marcados.

Tudo fica em <base>/temas_bruto/<id>/ (analise.json + texto.txt) — fora do Git.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import arquivo_seguro  # noqa: F401  (os.replace sem WinError 5)

PASTA = "temas_bruto"
MAX_TEXTO = 600_000          # caracteres guardados do arquivo bruto
BLOCO_ANALISE = 220_000      # acima disso, a análise roda em blocos e junta no fim
MAX_TEMAS = 30

# 🧩 v84_411 — quantos vídeos sair de um texto. Antes: "de 4 a 15 temas" → uma aula virava 12 vídeos quase iguais, cada um
# com um pedaço; agora o padrão é POUCOS vídeos COMPLETOS, cada um juntando o que a aula diz sobre o eixo em qualquer parte.
DIVISOES = {
    "denso": {"nome": "💎 Vídeos densos (6 a 8)", "faixa": (6, 8), "min": (18, 35), "palavras": (2500, 5000)},
    "auto": {"nome": "🤖 A IA escolhe a quantidade", "faixa": (2, 10), "min": (12, 35), "palavras": (1500, 5000)},
    "completo": {"nome": "🧩 Poucos vídeos, completos (2 a 5)", "faixa": (2, 5), "min": (14, 30), "palavras": (1500, 3500)},
    "equilibrado": {"nome": "⚖ Equilibrado (4 a 8)", "faixa": (4, 8), "min": (10, 20), "palavras": (900, 2400)},
    "maximo": {"nome": "📚 O máximo de vídeos (até 15)", "faixa": (4, 15), "min": (6, 20), "palavras": (600, 1800)},
    # 🎯 v84_468: juntar TUDO num vídeo só, ou vídeos do tamanho que você escolher
    "um": {"nome": "🎯 Um vídeo só, com TODO o conteúdo", "faixa": (1, 1), "min": (15, 90), "palavras": (3000, 14000)},
    "tempo": {"nome": "⏱ Vídeos do tamanho que eu escolher (só os assuntos que rendem esse tempo)", "faixa": (1, 15),
              "min": (8, 30), "palavras": (1200, 6000)},
}
MINUTOS_MAX = 120


def minutos_alvo(a: Dict[str, Any]) -> int:
    try:
        v = int(float((a or {}).get("minutos_alvo") or 0))
    except (TypeError, ValueError):
        return 0
    return max(1, min(MINUTOS_MAX, v)) if v > 0 else 0


def faixa_palavras(a: Dict[str, Any]) -> Tuple[int, int]:
    n = minutos_alvo(a)
    if n and divisao(a) in ("tempo", "um"):
        return (int(n * 150 * 0.9), int(n * 150 * 1.1))
    return DIVISOES[divisao(a)]["palavras"]


def faixa_minutos(a: Dict[str, Any]) -> Tuple[int, int]:
    """Os minutos que a IA mira: o tamanho que você escolheu (⏱ / 🎯 com tempo) ou a faixa da divisão."""
    n = minutos_alvo(a)
    if n and divisao(a) in ("tempo", "um"):
        return (n, n)
    return DIVISOES[divisao(a)]["min"]
DIVISAO_PADRAO = "denso"  # v84_431: era "completo"


def divisao(a: Dict[str, Any]) -> str:
    d = str((a or {}).get("divisao") or "")
    return d if d in DIVISOES else ("maximo" if (a or {}).get("temas") and not (a or {}).get("divisao") else DIVISAO_PADRAO)
_TRAVA = threading.RLock()
_RE_ID = re.compile(r"^[0-9a-f]{10}$")


class TemasErro(Exception):
    pass


# ------------------------------------------------------------------ arquivos
def _pasta(base: str, aid: str = "") -> str:
    if aid and not _RE_ID.match(aid):
        raise TemasErro("Análise não encontrada.")
    return os.path.join(base, PASTA, aid) if aid else os.path.join(base, PASTA)


def _gravar(caminho: str, d: Any) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def carregar(base: str, aid: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(_pasta(base, aid), "analise.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        raise TemasErro("Análise não encontrada.") from exc


def salvar(base: str, a: Dict[str, Any]) -> None:
    a["atualizado"] = time.time()
    _gravar(os.path.join(_pasta(base, a["id"]), "analise.json"), a)


def mexer(base: str, aid: str, fn) -> Dict[str, Any]:
    """Lê, muda e grava com a trava (várias threads gerando ao mesmo tempo)."""
    with _TRAVA:
        a = carregar(base, aid)
        fn(a)
        salvar(base, a)
        return a


def texto(base: str, aid: str) -> str:
    with open(os.path.join(_pasta(base, aid), "texto.txt"), encoding="utf-8") as f:
        return f.read()


def listar(base: str) -> List[Dict[str, Any]]:
    raiz = _pasta(base)
    out = []
    if not os.path.isdir(raiz):
        return out
    for aid in os.listdir(raiz):
        if not _RE_ID.match(aid):
            continue
        try:
            a = carregar(base, aid)
        except TemasErro:
            continue
        out.append({"id": aid, "nome": a.get("nome") or aid, "modelo": a.get("modelo_nome") or "", "estado": a.get("estado"),
                    "temas": len(a.get("temas") or []), "criados": sum(1 for t in a.get("temas") or [] if t.get("projeto")),
                    "atualizado": a.get("atualizado") or 0, "criado": a.get("criado") or 0})
    return sorted(out, key=__import__("tempo_ui").mais_novo)  # 🔝 v84_422: o mais novo em cima


def excluir(base: str, aid: str) -> None:
    import shutil
    d = _pasta(base, aid)
    if os.path.isdir(d):
        shutil.rmtree(d)


# ------------------------------------------------------------------ texto bruto
_RE_TEMPO = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?\s*(-->\s*[\d:.,]+)?\s*", re.M)


def limpar(texto_bruto: str) -> str:
    """Tira os tempos de transcrição (0:00 / 00:01:02,500 --> …), numeração de SRT, linhas repetidas em bloco
    (transcrição colada duas vezes) e espaços sobrando."""
    t = (texto_bruto or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"^\s*WEBVTT.*$", "", t, flags=re.M)
    t = re.sub(r"^\s*\d+\s*$", "", t, flags=re.M)  # numeração de SRT
    t = _RE_TEMPO.sub("", t)
    linhas = [ln.strip() for ln in t.split("\n")]
    linhas = [ln for ln in linhas if ln]
    n = len(linhas)
    for metade in (n // 2, (n + 1) // 2):  # o texto inteiro colado duas vezes seguidas
        if metade > 20 and linhas[:metade] == linhas[metade:metade * 2]:
            linhas = linhas[:metade]
            break
    t = "\n".join(linhas)
    return re.sub(r"[ \t]+", " ", t).strip()


def criar(base: str, nome: str, modelo: str, conteudo: bytes, nome_arquivo: str, divisao_: str = "",
          extras: Optional[List[Tuple[bytes, str]]] = None, minutos_alvo_: Any = None) -> Dict[str, Any]:
    """📚 Um texto bruto — ou VÁRIOS (🧩 v84_468: `extras` = mais transcrições do mesmo assunto, juntas num material só)."""
    import dossies as ds
    if modelo not in ds.MODELOS:
        raise TemasErro("Escolha um modelo de vídeo.")
    arquivos = [(conteudo, nome_arquivo)] + [x for x in (extras or []) if x and x[0]]
    for _c, n in arquivos:
        ext = os.path.splitext(n or "")[1].lower() or ".txt"
        if ext not in ds.EXT_ARQUIVO_FONTE:
            raise TemasErro("Arquivo: " + ", ".join(ds.EXT_ARQUIVO_FONTE) + f" ({n}).")
    aid = uuid.uuid4().hex[:10]
    d = _pasta(base, aid)
    os.makedirs(d, exist_ok=True)
    pedacos = []
    for k, (cont, n) in enumerate(arquivos, 1):
        ext = os.path.splitext(n or "")[1].lower() or ".txt"
        orig = os.path.join(d, ("original" if k == 1 else f"original_{k}") + ext)
        with open(orig, "wb") as f:
            f.write(cont)
        if ext in (".txt", ".md", ".srt", ".vtt"):
            bruto = cont.decode("utf-8-sig", errors="replace")
        else:
            try:
                bruto = ds.ler_arquivo(orig)["texto"]
            except ds.DossieError as exc:
                excluir(base, aid)
                raise TemasErro(f"{n}: {exc}") from exc
        t = limpar(bruto)
        if t.strip():
            pedacos.append((n, t))
    if len(pedacos) > 1:  # cada transcrição marcada (a IA sabe que são várias, do mesmo assunto)
        limpo = "\n\n".join(f"=== TEXTO {k} de {len(pedacos)}: {os.path.splitext(os.path.basename(n or ''))[0][:80]} ===\n{t}"
                             for k, (n, t) in enumerate(pedacos, 1))[:MAX_TEXTO]
    else:
        limpo = (pedacos[0][1] if pedacos else "")[:MAX_TEXTO]
    if len(limpo.split()) < 150:
        excluir(base, aid)
        raise TemasErro("O texto é curto demais pra separar em vários vídeos (menos de 150 palavras).")
    with open(os.path.join(d, "texto.txt"), "w", encoding="utf-8") as f:
        f.write(limpo)
    a = {"id": aid, "nome": (nome or os.path.splitext(os.path.basename(nome_arquivo))[0] or "Texto bruto")[:160],
         "arquivo": ", ".join(os.path.basename(n or "")[:80] for n, _t in pedacos)[:400], "textos": len(pedacos),
         "modelo": modelo, **({"minutos_alvo": minutos_alvo({"minutos_alvo": minutos_alvo_})} if minutos_alvo_ else {}),
         "modelo_nome": ds.sem_emoji(ds.MODELOS[modelo].get("nome") or modelo), "palavras": len(limpo.split()),
         "estado": "novo", "erro": "", "temas": [], "criado": time.time(),
         "divisao": divisao_ if divisao_ in DIVISOES else DIVISAO_PADRAO}
    salvar(base, a)
    return a


# ------------------------------------------------------------------ 1. separar os temas (IA)
def _formatos(modelo: str) -> Dict[str, Dict[str, Any]]:
    import dossies as ds
    return (ds.MODELOS.get(modelo) or {}).get("formatos") or {}


def _schema_temas(com_historias: bool = False) -> Dict[str, Any]:
    from ia_midia import _I, _S, _lista, _obj
    tema = _obj({"titulo": _S, "tema": _S, "pontos": _lista(_S), "por_que": _S, "abertura": _S, "formato": _S,
                 "minutos": _I, "por_que_tempo": _S, "forca": _I, "referencias": _lista(_S),
                 "de_onde": _S})
    if com_historias:
        return _obj({"historias": _lista(_obj({"resumo": _S, "palavras": _lista(_S)})), "temas": _lista(tema)})
    return _obj({"temas": _lista(tema)})


# 🟠 v84_471 — Raciocínio Maldito: a análise lista as HISTÓRIAS do texto e uma 2ª passada reescreve os temas sem elas
# (a regra sozinha no prompt não bastou: a IA recontava a história de quem fala no título e na abertura). A lista também vai pras
# notas e pra lapidação, e as palavras concretas de cada história são conferidas no título/tema/pontos/abertura.
def norm(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode()


def ler_historias(d: Any) -> List[Dict[str, Any]]:
    out = []
    for h in (d.get("historias") if isinstance(d, dict) else None) or []:
        if isinstance(h, dict) and str(h.get("resumo") or "").strip():
            pal = [" ".join(str(p).split())[:40] for p in h.get("palavras") or [] if len(str(p).strip()) >= 3][:12]
            out.append({"resumo": " ".join(str(h["resumo"]).split())[:300], "palavras": pal})
    return out[:20]


def bloco_historias(a: Dict[str, Any]) -> str:
    hs = a.get("historias") or []
    if not hs:
        return ""
    return ("\nHISTÓRIAS/CASOS DO TEXTO — NÃO podem aparecer, nem disfarçados, nem com os detalhes concretos deles "
            "(no lugar, só a ideia geral que ilustram):\n" + "\n".join(
                f"- {h['resumo']}" + (f" (detalhes proibidos: {', '.join(h['palavras'])})" if h.get("palavras") else "")
                for h in hs) + "\n")


def _campos_texto(t: Dict[str, Any]) -> str:
    return " ".join([t.get("titulo") or "", t.get("tema") or "", t.get("abertura") or ""] + list(t.get("pontos") or []))


def vazamentos(t: Dict[str, Any], historias: List[Dict[str, Any]]) -> List[str]:
    """As palavras concretas das histórias do texto que sobraram no tema (título, tema, pontos, abertura)."""
    alvo = " " + norm(_campos_texto(t)) + " "
    achou = []
    for h in historias or []:
        for p in h.get("palavras") or []:
            n = norm(p).strip()
            if len(n) >= 4 and re.search(r"(?<![a-z0-9])" + re.escape(n), alvo) and p not in achou:
                achou.append(p)
    return achou


def _schema_reescrita() -> Dict[str, Any]:
    from ia_midia import _S, _lista, _obj
    return _obj({"temas": _lista(_obj({"id": _S, "titulo": _S, "tema": _S, "pontos": _lista(_S), "por_que": _S,
                                       "abertura": _S, "referencias": _lista(_S)}))})


def system_sem_historias(a: Dict[str, Any]) -> str:
    return f"""Você revisa os TEMAS de vídeos de um canal de YouTube de psicologia/comportamento. Os temas foram tirados de
uma transcrição em que quem fala explica as ideias contando histórias DELE (ou de conhecidos/pacientes). O canal NUNCA
reconta essas histórias: usa só a IDEIA geral e cria exemplos NOVOS do zero.
{bloco_historias(a)}
Reescreva CADA tema:
- "titulo": até 50 caracteres, sobre o MECANISMO (o porquê do comportamento), em linguagem do povo, chamativo. Sem nenhum
  detalhe das histórias acima (nem o objeto, o hábito, o lugar, a doença, as pessoas delas). Em vez de "Como <alguém>
  fez <tal coisa>" → "Por que <o mecanismo> pega todo mundo".
- "tema" e "pontos": a ideia e os passos do raciocínio em termos GERAIS. Ponto que só conta a história ("exemplo de como X
  fez Y") vira o princípio que ela mostra ou sai.
- "abertura": uma cena NOVA criada do zero — outra pessoa, outro cenário e OUTRO hábito/problema que os das histórias
  acima (ou um experimento/estudo real e conhecido). Nunca o mesmo vício/hábito da história.
- "por_que": sem citar "gancho pessoal" nem a história.
- "referencias": só conceitos, estudos, autores e áreas do cérebro (nada de pessoa da história).
Mantenha o "id" de cada tema. Responda só o JSON."""


def tirar_historias(a: Dict[str, Any], temas: List[Dict[str, Any]], progresso=None) -> List[Dict[str, Any]]:
    """2ª passada: reescreve os temas sem as histórias do texto (até 2 vezes se ainda sobrar detalhe concreto)."""
    import ia_servico as ia
    hs = a.get("historias") or []
    for tent in range(2):
        alvo = temas if tent == 0 else [t for t in temas if vazamentos(t, hs)]
        if not alvo:
            break
        if progresso:
            progresso("🧠 tirando as histórias da aula dos temas…")
        envio = [{k: t.get(k) for k in ("id", "titulo", "tema", "pontos", "por_que", "abertura", "referencias")} for t in alvo]
        pedido = "Reescreva estes temas:\n" + json.dumps(envio, ensure_ascii=False, indent=1)
        if tent:
            pedido += "\n\nAINDA sobraram detalhes das histórias: " + "; ".join(
                f"{t['titulo']}: {', '.join(vazamentos(t, hs))}" for t in alvo) + ". Tire TODOS."
        try:
            with ia.rotulo("🧠 Temas sem histórias: " + a["nome"][:50]):
                d = ia.chamar("roteiros", system_sem_historias(a), pedido, schema=_schema_reescrita(), max_tokens=12000,
                              effort="medium", timeout=600, cache_local=False)
        except Exception:  # noqa: BLE001 — a revisão é extra: se falhar, ficam os temas da análise
            break
        novos = {str(x.get("id")): x for x in (d or {}).get("temas") or [] if isinstance(x, dict)}
        for t in temas:
            x = novos.get(t["id"])
            if not x or not str(x.get("titulo") or "").strip():
                continue
            t["titulo"] = " ".join(str(x["titulo"]).split())[:120]
            for k, lim in (("tema", 400), ("por_que", 400), ("abertura", 500)):
                if str(x.get(k) or "").strip():
                    t[k] = str(x[k]).strip()[:lim]
            for k, lim in (("pontos", 10), ("referencias", 12)):
                if isinstance(x.get(k), list) and x[k]:
                    t[k] = [str(p).strip()[:400] for p in x[k] if str(p).strip()][:lim]
    return temas


def _regra_divisao(a: Dict[str, Any]) -> str:
    d = divisao(a)
    lo, hi = DIVISOES[d]["faixa"]
    comum = ("- NADA DE SOBREPOSIÇÃO: cada ideia, exemplo, exercício e citação do texto pertence a UM vídeo só. Se dois temas "
             "dividem a mesma ideia central, os mesmos exemplos ou o mesmo exercício, ou um só faz sentido com o outro, "
             "eles viram UM vídeo. Tema raso ou só citado de passagem não entra.\n"
             "- Aulas e palestras VOLTAM aos assuntos: um tema começa no início, reaparece no meio e fecha no fim. Junte "
             "tudo o que o texto diz sobre o tema em QUALQUER parte — não corte o texto em fatias pela ordem.")
    n = minutos_alvo(a)
    if d == "um":
        return ("- Devolva UM tema só: o vídeo COMPLETO que junta TUDO o que o material tem de bom — todos os eixos, na ordem "
                "em que um vídeo contaria (do mais básico ao mais profundo), costurados numa história só. O que o material "
                "repete entra uma vez. Nada de deixar eixo forte de fora.\n"
                + (f"- O vídeo deve ter ~{n} minutos: se o material rende MAIS, escolha o melhor e deixe o resto de fora (diga "
                   f"o que ficou de fora em por_que_tempo); se rende MENOS, não estique — diga em por_que_tempo quanto ele "
                   f"sustenta de verdade.\n" if n else
                   "- \"minutos\": o tamanho que o material inteiro sustenta SEM enrolar (pode passar de 30 min, se render).\n")
                + comum)
    if d == "tempo":
        n = n or 12
        return (f"- TODOS os vídeos têm ~{n} minutos (entre {round(n * 0.85)} e {round(n * 1.15)}): é o tamanho que o canal "
                f"quer. Primeiro faça o MAPA do material. Só devolva temas que o material SUSTENTA nesse tamanho, densos e sem "
                f"enrolar: tema que não chega a {n} min junta com o parecido mais próximo ou fica de fora; tema que passaria "
                f"muito de {n} min vira dois vídeos de {n} min (cada um com começo, meio e fim, e sem repetir o outro). "
                f"Quantos vídeos sair do material (até {DIVISOES['tempo']['faixa'][1]}) — melhor poucos e bons. Em "
                f"por_que_tempo, diga por que este tema dá {n} min.\n" + comum)
    if d == "completo":
        return (f"- Primeiro faça o MAPA do texto inteiro: quais são os GRANDES eixos (não os subtópicos). Cada vídeo é um eixo "
                f"COMPLETO, com começo, desenvolvimento e conclusão, reunindo a base teórica, os exemplos, os exercícios e "
                f"as objeções desse eixo. Devolva de {lo} a {hi} vídeos — prefira MENOS vídeos mais ricos a muitos vídeos "
                f"parecidos. Se o texto só tem um eixo forte, devolva {lo} mesmo assim só se o segundo se sustentar; senão 1.\n"
                + comum)
    if d == "denso":
        return (f"- Primeiro faça o MAPA do texto inteiro. Devolva de {lo} a {hi} vídeos DENSOS: cada um é um eixo que o texto "
                f"desenvolve de verdade, com base teórica, exemplos, exercícios, objeções e conclusão — material pra "
                f"{DIVISOES[d]['min'][0]} a {DIVISOES[d]['min'][1]} minutos SEM enrolar. Cada trecho do texto vai alimentar "
                f"um vídeo só, então divida o texto inteiro entre eles (o que é logística ou repetição fica de fora).\n"
                + comum)
    if d == "auto":
        return (f"- Primeiro faça o MAPA do texto inteiro e VOCÊ decide quantos vídeos ele sustenta (de {lo} a {hi}): um "
                f"vídeo só existe se tiver material próprio pra pelo menos {DIVISOES[d]['min'][0]} minutos densos, sem "
                f"repetir outro. Texto longo e rico → mais vídeos; texto curto ou com um eixo só → poucos. Em por_que_tempo, "
                f"diga em uma frase por que essa quantidade.\n" + comum)
    if d == "equilibrado":
        return f"- Separe os temas que o texto realmente desenvolve: de {lo} a {hi} vídeos.\n" + comum
    return f"- Separe tudo o que o texto realmente desenvolve: em geral de {lo} a {hi} temas (no máximo {MAX_TEMAS}).\n" + comum


def _regra_varios(a: Dict[str, Any]) -> str:
    n = int((a or {}).get("textos") or 1)
    if n < 2:
        return ""
    return (f"- O material junta {n} TEXTOS (transcrições) do mesmo assunto, separados por \"=== TEXTO k de {n} ===\". Trate "
            "como UM material só: um vídeo pode (e deve) juntar o que textos diferentes dizem sobre o mesmo tema — é isso "
            "que deixa o vídeo mais completo. O que dois textos repetem conta UMA vez; quando se complementam, some os dois.\n")


def _so_ideias(a: Dict[str, Any]) -> bool:
    """🟠 v84_470 — modelos com exemplos_proprios (🧠 Raciocínio Maldito): do texto só sai a IDEIA, nunca a história."""
    import dossies as ds
    return bool((ds.MODELOS.get(a.get("modelo") or "") or {}).get("exemplos_proprios"))


REGRA_SO_IDEIA_TEMAS = """- SÓ A IDEIA, NUNCA A HISTÓRIA DO TEXTO (regra mais importante deste canal): quem fala costuma explicar a ideia com
  uma história dele (algo que ele viveu, a família, a escola/faculdade, um paciente, um conhecido) ou com um caso/exemplo
  próprio. Essa história é só o VEÍCULO — o vídeo NUNCA reconta ela, nem disfarçada ("um homem que…", "um jovem que…",
  "narrativa de superação"). Tire dela só o MECANISMO geral: em vez de "como <alguém> fez <tal coisa>" → "por que
  <o mecanismo> acontece com qualquer pessoa".
- "titulo", "tema" e "pontos" falam do MECANISMO/da ideia, nunca do caso contado no texto (nada de "como X conseguiu…",
  nem os detalhes da história: os objetos, o hábito, o lugar, a doença, os números, as pessoas dela).
- "abertura": uma situação NOVA, criada do zero, com outro cenário, outra pessoa e outro hábito/problema que o do texto
  — ou um estudo/experimento real e conhecido. PROIBIDO reaproveitar a história, o caso ou o exemplo do texto.
- Estudos, autores, dados e conceitos científicos citados no texto PODEM entrar (são ideias, não histórias).
"""

REGRA_LISTAR_HISTORIAS = """- "historias" (ANTES dos temas): liste TODAS as histórias, casos e exemplos concretos do texto (pessoais de quem
  fala, de pacientes, conhecidos, alunos — os estudos científicos NÃO entram aqui). Cada uma: "resumo" (1 frase) e
  "palavras" (3 a 8 detalhes CONCRETOS e próprios dela: o objeto, o hábito, o esporte, o lugar, a doença, a distância —
  os substantivos que só aquela história tem; nunca o conceito geral que ela ilustra, como "medo", "vício", "hábito").
"""

REGRA_SO_IDEIA_NOTAS = """- SÓ A IDEIA, NUNCA A HISTÓRIA (regra mais importante deste canal): toda história, caso, paciente, conhecido ou
  exemplo contado no texto (inclusive em 3ª pessoa) NÃO entra. No lugar dele, escreva só O QUE ele ilustra, em termos
  gerais e sem detalhes ("[o texto ilustra com um caso pessoal: <o princípio, em uma frase>]") — sem lugar, idade,
  doença, objetos, números, pessoas ou falas da história. O
  roteirista vai criar exemplos NOVOS do zero; ele não pode ver a história original.
- Estudos, autores, dados, regiões do cérebro e conceitos citados FICAM (são ideias, não histórias).
"""


def system_analise(a: Dict[str, Any], texto_bruto: str, parte: str = "") -> str:
    import dossies as ds
    mod = ds.MODELOS.get(a["modelo"]) or {}
    canal = ds.canal_do_modelo(a["modelo"]) or ""
    fmts = "\n".join(f"- \"{k}\": {v.get('nome')} (~{v.get('minutos')} min)" for k, v in _formatos(a["modelo"]).items())
    return f"""Você é o editor-chefe de um canal de YouTube{(' (“' + canal + '”)') if canal else ''}: {ds.sem_emoji(mod.get('nome') or '')}.
{mod.get('descricao') or ''}

Abaixo vem um TEXTO BRUTO{(' (' + parte + ')') if parte else ''} — pode ser a transcrição de um curso, aula, palestra ou live,
um livro ou anotações. Ele é só MATÉRIA-PRIMA de ideias: o canal nunca fala do curso, da aula, de quem falou, dos alunos,
nem das experiências pessoais de quem fala. Ignore a parte de organização (avisos, inscrições, perguntas por telefone,
datas de aula, apresentações) e as histórias pessoais.

Sua tarefa: separar os TEMAS que rendem, cada um, UM vídeo que se sustenta sozinho (quem nunca viu o canal entende).
{_regra_varios(a)}{_regra_divisao(a)}
- NÃO é tema: a tese ou a polêmica PESSOAL de quem dá a aula (as brigas dele com um professor, um jornalista, uma
  universidade, um político, citados pelo nome) nem a análise do próprio discurso de quem fala. O tema é a IDEIA (um
  pensador, um conceito, uma obra, um problema), contada pelo narrador do canal, sem dono e sem alvo.
- "titulo": o título do vídeo em português, CURTO (até 50 caracteres), chamativo e honesto (estilo YouTube: uma ideia só,
  palavras concretas, curiosidade ou conflito — nada de "filosofia", "interpretação", "análise" nem duas partes coladas).
- "tema": em uma frase, a ideia central do vídeo.
- "pontos": de 3 a 7 tópicos curtos do que o vídeo cobre, NA ORDEM em que o vídeo contaria, com o que o texto diz
  (argumentos, exemplos, autores e obras citados).
- "por_que": por que esse tema funciona em vídeo (prático? polêmico? curiosidade? exercício que gera comentário?).
- "abertura": uma ideia de abertura fria pro vídeo — uma história real, um caso, um experimento ou uma pergunta concreta
  que encarna o tema (pode vir de fora do texto, se for conhecido e verdadeiro).
{(REGRA_SO_IDEIA_TEMAS + REGRA_LISTAR_HISTORIAS) if _so_ideias(a) else ""}- "formato": a chave do formato do modelo que melhor combina:
{fmts}
- "minutos": a duração IDEAL do vídeo, pelo tanto que o texto rende sobre o tema (sem enrolação), em geral entre
  {faixa_minutos(a)[0]} e {faixa_minutos(a)[1]} min. Shorts = 1.
- "de_onde": de que partes do texto o vídeo tira o material (ex.: "começo da aula + exemplo do meio + conclusão do fim").
- "por_que_tempo": a justificativa do tempo em uma frase (ex.: "um exercício prático + duas bases filosóficas").
- "forca": de 1 a 10, o potencial do vídeo no YouTube (interesse, clareza, gancho).
- "referencias": pensadores, obras e conceitos citados no texto que entram no vídeo.
Ordene do tema mais forte pro mais fraco. Responda só o JSON.

=== TEXTO BRUTO ===
{texto_bruto}
=== FIM DO TEXTO ==="""


def prompt_analise(base: str, aid: str) -> str:
    """O pedido completo (pra copiar e colar numa IA, quando a 🤖 IA do site está desligada)."""
    a = carregar(base, aid)
    exemplo = {"temas": [{"titulo": "…", "tema": "…", "pontos": ["…"], "por_que": "…", "abertura": "…",
                          "formato": next(iter(_formatos(a["modelo"])), ""), "minutos": 12, "por_que_tempo": "…",
                          "forca": 8, "referencias": ["…"], "de_onde": "…"}]}
    return (system_analise(a, texto(base, aid)) + "\n\nResponda SÓ com o JSON, sem texto antes ou depois, neste formato:\n"
            + json.dumps(exemplo, ensure_ascii=False))


def _num(v: Any, padrao: float, a: float, b: float) -> float:
    try:
        return max(a, min(b, float(v)))
    except (TypeError, ValueError):
        return padrao


def ler_temas(d: Any, modelo: str, a: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Limpa a lista de temas que a IA devolveu. Com ⏱/🎯 + tempo escolhido, os minutos ficam no tamanho pedido."""
    fixo = minutos_alvo(a) if a and divisao(a) in ("tempo", "um") else 0
    teto = MINUTOS_MAX if a and divisao(a) == "um" else 60
    if isinstance(d, dict):
        d = d.get("temas")
    fmts = _formatos(modelo)
    padrao_fmt = next(iter(fmts), "")
    out = []
    for x in d if isinstance(d, list) else []:
        if not isinstance(x, dict) or not str(x.get("titulo") or "").strip():
            continue
        fmt = str(x.get("formato") or "")
        if fmt not in fmts:
            fmt = padrao_fmt
        minutos = fixo or _num(x.get("minutos"), float((fmts.get(fmt) or {}).get("minutos") or 10), 1, teto)
        out.append({"id": uuid.uuid4().hex[:8], "titulo": " ".join(str(x["titulo"]).split())[:120],
                    "tema": str(x.get("tema") or "").strip()[:400],
                    "pontos": [str(p).strip()[:400] for p in x.get("pontos") or [] if str(p).strip()][:10],
                    "por_que": str(x.get("por_que") or "").strip()[:400],
                    "abertura": str(x.get("abertura") or "").strip()[:500],
                    "formato": fmt, "minutos": int(round(minutos)),
                    "por_que_tempo": str(x.get("por_que_tempo") or "").strip()[:300],
                    "forca": int(_num(x.get("forca"), 5, 1, 10)),
                    "referencias": [str(r).strip()[:120] for r in x.get("referencias") or [] if str(r).strip()][:12],
                    "de_onde": str(x.get("de_onde") or "").strip()[:300],
                    "marcado": False, "projeto": "", "estado": "", "msg": ""})
    out.sort(key=lambda t: -t["forca"])
    return out[:MAX_TEMAS]


_CAMPOS = ("titulo", "tema", "pontos", "por_que", "abertura", "formato", "minutos", "por_que_tempo", "forca", "referencias",
           "de_onde")


def _juntar(temas: List[Dict[str, Any]], a: Dict[str, Any], de_partes: bool = True) -> List[Dict[str, Any]]:
    """🧩 Junta os temas que se sobrepõem (texto em blocos, ou uma lista com vídeos parecidos demais)."""
    import ia_servico as ia
    d = divisao(a)
    lo, hi = DIVISOES[d]["faixa"]
    lista = json.dumps([{k: t.get(k) for k in _CAMPOS} for t in temas], ensure_ascii=False)
    origem = "tirados de PARTES diferentes do mesmo texto" if de_partes else "separados do mesmo texto (uma aula/palestra)"
    system = (f"Você recebe temas de vídeo {origem}. Muitos se sobrepõem: dividem a ideia central, os exemplos, o exercício "
              "ou só fazem sentido juntos. JUNTE os que se sobrepõem num vídeo só e mais completo — somando os pontos (na "
              "ordem em que o vídeo contaria), as referências e o \"de_onde\", e ajustando os minutos pelo material somado; "
              "o título novo cobre o eixo inteiro. Tire os rasos. Cada ideia, exemplo e citação fica em UM vídeo só. "
              f"Devolva de {lo} a {hi} vídeos (prefira menos e mais ricos), do mais forte pro mais fraco, no mesmo formato. "
              "Só o JSON.")
    r = ia.chamar("roteiros", system, lista, schema=_schema_temas(), max_tokens=16000, effort="medium", timeout=600)
    return ler_temas(r, a["modelo"], a) if r else temas


def _palavras_chave(t: Dict[str, Any]) -> set:
    import unicodedata
    txt = " ".join([t.get("titulo") or "", t.get("tema") or ""] + list(t.get("pontos") or []) + list(t.get("referencias") or []))
    txt = unicodedata.normalize("NFKD", txt.lower()).encode("ascii", "ignore").decode()
    return {w[:7] for w in re.findall(r"[a-z]{5,}", txt)} - _VAZIAS


_VAZIAS = {"sobre", "porque", "quando", "outro", "outra", "mesmo", "entre", "pode", "ser", "como", "video", "videos", "sobre",
           "ideia", "ideias", "texto", "coisa", "tamb", "muito", "dessa", "desse", "nossa", "nosso", "sempre", "realm",
           "verda", "pesso", "exemp", "mostr", "quem", "porqu", "algum", "cada", "parte", "forma", "fazer", "aquil", "isso"}


def parecidos(temas: List[Dict[str, Any]], limite: float = 0.28) -> Dict[str, List[str]]:
    """{id: [títulos dos temas muito parecidos]} — pelo quanto as palavras-chave se repetem (sem IA)."""
    chaves = {t["id"]: _palavras_chave(t) for t in temas}
    out: Dict[str, List[str]] = {}
    for i, t in enumerate(temas):
        for u in temas[i + 1:]:
            a_, b_ = chaves[t["id"]], chaves[u["id"]]
            if not a_ or not b_:
                continue
            j = len(a_ & b_) / max(1, min(len(a_), len(b_)))
            if j >= limite:
                out.setdefault(t["id"], []).append(u["titulo"])
                out.setdefault(u["id"], []).append(t["titulo"])
    return out


def juntar_parecidos(base: str, aid: str, progresso=None) -> int:
    """🧩 Pega a lista atual (os temas que ainda não viraram projeto) e junta os que se sobrepõem."""
    import ia_servico as ia
    motivo = ia.motivo_desligado("roteiros")
    if motivo:
        raise TemasErro("IA: " + motivo)
    a = carregar(base, aid)
    livres = [t for t in a.get("temas") or [] if not t.get("projeto")]
    if len(livres) < 2:
        raise TemasErro("Precisa de pelo menos 2 temas que ainda não viraram projeto.")
    if progresso:
        progresso("juntando os temas parecidos…")
    with ia.rotulo("🧩 Juntar temas: " + a["nome"][:60]):
        novos = _juntar(livres, a, de_partes=False)
    mexer(base, aid, lambda x: x.update(estado="temas", erro="", temas=_manter_criados(x.get("temas") or [], novos)))
    return len(novos)


def analisar(base: str, aid: str, progresso=None) -> int:
    """🤖 Separa os temas (roda em segundo plano). Devolve quantos temas achou."""
    import ia_servico as ia
    motivo = ia.motivo_desligado("roteiros")
    if motivo:
        raise TemasErro("IA: " + motivo + " — ligue em 🤖 IA (📝 Roteiros direto na IA) ou use 📋 Copiar o pedido.")
    a = mexer(base, aid, lambda x: x.update(estado="analisando", erro=""))
    tx = texto(base, aid)
    blocos = [tx[i:i + BLOCO_ANALISE] for i in range(0, len(tx), BLOCO_ANALISE)] or [tx]
    temas: List[Dict[str, Any]] = []
    so_ideia, historias = _so_ideias(a), []  # type: ignore[var-annotated]
    try:
        with ia.rotulo("📚 Temas: " + a["nome"][:60]):
            for k, bl in enumerate(blocos, 1):
                if progresso:
                    progresso(f"lendo o texto{f' (parte {k} de {len(blocos)})' if len(blocos) > 1 else ''}…")
                parte = f"parte {k} de {len(blocos)}" if len(blocos) > 1 else ""
                d = ia.chamar("roteiros", system_analise(a, bl, parte), "Separe os temas deste texto.",
                              schema=_schema_temas(so_ideia), max_tokens=16000, effort="medium", timeout=900)
                if d is None:
                    raise TemasErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
                temas += ler_temas(d, a["modelo"], a)
                historias += ler_historias(d)
            hi = DIVISOES[divisao(a)]["faixa"][1]
            if temas and (len(blocos) > 1 or len(temas) > hi or (divisao(a) != "maximo" and parecidos(temas))):
                if progresso:
                    progresso("juntando os temas que se sobrepõem…")
                temas = _juntar(temas, a, de_partes=len(blocos) > 1)
        if so_ideia and temas:
            a = mexer(base, aid, lambda x: x.update(historias=historias[:20]))
            temas = tirar_historias(a, temas, progresso)
    except Exception as exc:
        mexer(base, aid, lambda x: x.update(estado="erro", erro=str(exc)[:400]))
        raise
    if not temas:
        mexer(base, aid, lambda x: x.update(estado="erro", erro="a IA não achou nenhum tema"))
        raise TemasErro("a IA não achou nenhum tema")
    mexer(base, aid, lambda x: x.update(estado="temas", temas=_manter_criados(x.get("temas") or [], temas)))
    return len(temas)


def _manter_criados(antigos: List[Dict[str, Any]], novos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analisar de novo não perde os temas que já viraram projeto."""
    return [t for t in antigos if t.get("projeto")] + novos


def ler_resposta(base: str, aid: str, resposta: str) -> int:
    """📋 A resposta colada de outra IA (quando a do site está desligada)."""
    import json_ia
    try:
        d = json_ia.carregar(resposta)
    except Exception as exc:  # noqa: BLE001
        raise TemasErro(f"Não consegui ler o JSON: {exc}") from exc
    a = carregar(base, aid)
    temas = ler_temas(d, a["modelo"], a)
    if not temas:
        raise TemasErro("Não achei nenhum tema na resposta.")
    mexer(base, aid, lambda x: x.update(estado="temas", erro="", temas=_manter_criados(x.get("temas") or [], temas)))
    return len(temas)


def editar_tema(base: str, aid: str, tid: str, campos: Dict[str, Any]) -> Dict[str, Any]:
    fmts = None

    def f(a):
        nonlocal fmts
        fmts = _formatos(a["modelo"])
        for t in a.get("temas") or []:
            if t["id"] != tid:
                continue
            if "titulo" in campos and str(campos["titulo"]).strip():
                t["titulo"] = " ".join(str(campos["titulo"]).split())[:120]
            if campos.get("formato") in fmts:
                t["formato"] = campos["formato"]
            if "minutos" in campos:
                t["minutos"] = int(_num(campos["minutos"], t.get("minutos") or 10, 1, 60))
            if "marcado" in campos:
                t["marcado"] = bool(campos["marcado"])
    return mexer(base, aid, f)


# ------------------------------------------------------------------ 2. notas de cada tema (IA) → fonte do projeto
def system_notas(a: Dict[str, Any], texto_bruto: str) -> str:
    """O texto bruto vai no SYSTEM (fica no cache da IA por 1 h: as notas dos vários temas leem o mesmo texto)."""
    return f"""Você prepara as NOTAS DE PESQUISA de um vídeo de YouTube a partir de um TEXTO BRUTO (transcrição de curso, aula,
palestra, livro ou anotações). As notas são a ÚNICA fonte que o roteirista vai ler.

Regras das notas:
- Só o que o texto diz sobre o tema pedido: as ideias, os argumentos na ordem lógica, as explicações, os exemplos, as
  distinções, os autores e as obras citados (com o que o texto atribui a cada um), os termos técnicos com a explicação,
  as objeções e as respostas. Reorganize por lógica (não pela ordem em que apareceu no texto) e escreva em português claro.
- NADA do evento: não mencione curso, aula, palestra, professor, palestrante, alunos, turma, perguntas do público,
  inscrições, datas, nem o nome de quem fala. Nada de experiências, histórias ou opiniões pessoais de quem fala sobre a
  própria vida. O que for tese própria de quem fala (não de um autor clássico), escreva como "uma leitura possível: …".
- Corrija os erros óbvios de transcrição (palavras trocadas pelo reconhecimento de voz) pelo contexto; o que não der pra
  entender, deixe de fora.
- Não invente fatos, datas, citações ou estudos que não estão no texto. No fim, numa seção "Sugestões (fora do texto)",
  você pode listar de 2 a 5 exemplos, casos históricos ou experimentos CONHECIDOS e verdadeiros que ajudariam a explicar o
  tema num vídeo leve — marcados como sugestão.
- O texto VOLTA aos assuntos: junte tudo o que ele diz sobre o tema em QUALQUER parte (começo, meio e fim), não só o
  trecho onde o tema aparece primeiro.
- Formato: texto puro em tópicos e parágrafos curtos, de {faixa_palavras(a)[0]} a
  {faixa_palavras(a)[1]} palavras conforme o material. Sem JSON.
{(REGRA_SO_IDEIA_NOTAS + bloco_historias(a)) if _so_ideias(a) else ""}
=== TEXTO BRUTO ===
{texto_bruto}
=== FIM DO TEXTO ==="""


def pedido_notas(t: Dict[str, Any], outros: Optional[List[Dict[str, Any]]] = None) -> str:
    resto = [o for o in outros or [] if o.get("id") != t.get("id") and (o.get("marcado") or o.get("projeto"))]
    return (f"Tema do vídeo: {t['titulo']}\nIdeia central: {t.get('tema') or ''}\n"
            f"O que o vídeo cobre: " + "; ".join(t.get("pontos") or []) +
            (f"\nReferências: {', '.join(t['referencias'])}" if t.get("referencias") else "") +
            (f"\nDe onde vem no texto: {t['de_onde']}" if t.get("de_onde") else "") +
            ("\n\nOUTROS vídeos da mesma série (não repita o que é deles — cada ideia/exemplo fica num vídeo só):\n"
             + "\n".join(f"- {o['titulo']}: {o.get('tema') or ''}" for o in resto[:12]) if resto else "") +
            "\n\nEscreva as notas de pesquisa deste tema (texto puro).")


_CACHE_NOTAS: Dict[str, Dict[str, Any]] = {}  # 💸 v84_424: aula → {"trava", "quente" (quando o cache da IA ficou pronto)}
_TRAVA_CACHE = threading.Lock()
CACHE_VALE_S = 50 * 60  # o cache do texto na IA vale 1 h; 50 min pra ter folga


def gerar_notas(base: str, a: Dict[str, Any], t: Dict[str, Any]) -> str:
    """As notas de um tema. 💸 v84_424: o texto inteiro da aula vai no cache da IA (as notas seguintes leem por ~10% do
    preço). Com vários temas ao mesmo tempo, o PRIMEIRO grava o cache e os outros esperam por ele — antes os 3 primeiros
    gravavam juntos e cada um pagava a gravação (2×)."""
    import ia_servico as ia
    tx = texto(base, a["id"])
    if len(tx) > BLOCO_ANALISE:  # texto enorme: as notas leem os blocos que mais falam do tema (system diferente por tema)
        tx = _trechos_do_tema(tx, t)
        return _notas(ia, a, t, tx)
    with _TRAVA_CACHE:
        st = _CACHE_NOTAS.setdefault(a["id"], {"trava": threading.Lock(), "quente": 0.0})
    if time.time() - st["quente"] < CACHE_VALE_S:
        return _notas(ia, a, t, tx)
    with st["trava"]:  # o primeiro grava o cache; os outros esperam aqui
        if time.time() - st["quente"] >= CACHE_VALE_S:
            notas = _notas(ia, a, t, tx)
            st["quente"] = time.time()
            return notas
    return _notas(ia, a, t, tx)


def _notas(ia, a: Dict[str, Any], t: Dict[str, Any], tx: str) -> str:
    with ia.rotulo("📚 Notas: " + t["titulo"][:60]):
        notas = ia.chamar("roteiros", system_notas(a, tx), pedido_notas(t, a.get("temas")), max_tokens=12000, effort="low", timeout=600)
    if not notas or len(str(notas).split()) < 80:
        raise TemasErro("a IA não escreveu as notas do tema")
    return str(notas).strip()


def _trechos_do_tema(tx: str, t: Dict[str, Any]) -> str:
    """Os blocos do texto com mais palavras do tema (título, pontos, referências) até BLOCO_ANALISE caracteres."""
    import unicodedata

    def norm(s):
        return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    chaves = {w for w in re.findall(r"[a-z]{5,}", norm(" ".join([t["titulo"], t.get("tema") or ""] + (t.get("pontos") or [])
                                                                  + (t.get("referencias") or []))))}
    tam = 20_000
    blocos = [tx[i:i + tam] for i in range(0, len(tx), tam)]
    nota = [(sum(norm(b).count(c) for c in chaves), k) for k, b in enumerate(blocos)]
    escolhidos = sorted(k for _n, k in sorted(nota, reverse=True)[:max(1, BLOCO_ANALISE // tam)])
    return "\n\n[…]\n\n".join(blocos[k] for k in escolhidos)


# ------------------------------------------------------------------ 3. 💎 v84_431 — base "lapidada": o próprio texto da aula
# Em vez de um RESUMO (as notas), cada vídeo recebe os TRECHOS da aula que são dele — divididos sem sobreposição (um trecho
# vai pra um vídeo só) — e esses trechos são LAPIDADOS (limpos e organizados, sem resumir). O roteiro sai bem mais denso.
BASES = {"lapidado": "💎 Trechos da aula, divididos entre os vídeos e lapidados (mais denso)",
         "notas": "📝 Notas (um resumo do que a aula diz sobre o tema)"}
BASE_PADRAO = "lapidado"
FATIA_PALAVRAS = 400
LAPIDAR_PALAVRAS = 5000  # pedaço máximo lapidado de uma vez


def base_video(a: Dict[str, Any]) -> str:
    b = str((a or {}).get("base") or "")
    return b if b in BASES else BASE_PADRAO


def fatiar(tx: str, alvo: int = FATIA_PALAVRAS) -> List[str]:
    """O texto em trechos de ~`alvo` palavras, cortando no fim de uma frase."""
    frases = re.split(r"(?<=[.!?…])\s+|\n{2,}", tx or "")
    out: List[str] = []
    atual: List[str] = []
    n = 0
    for f in frases:
        f = f.strip()
        if not f:
            continue
        atual.append(f)
        n += len(f.split())
        if n >= alvo:
            out.append(" ".join(atual))
            atual, n = [], 0
    if atual:
        if out and n < alvo // 3:
            out[-1] += " " + " ".join(atual)
        else:
            out.append(" ".join(atual))
    return out


def _schema_fatias() -> Dict[str, Any]:
    from ia_midia import _S, _lista, _obj
    return _obj({"fatias": _lista(_obj({"c": _S, "video": _S}))})


def system_distribuir(temas: List[Dict[str, Any]]) -> str:
    vids = "\n".join(f"- {t['id']}: {t['titulo']} — {t.get('tema') or ''} (cobre: {'; '.join(t.get('pontos') or [])})"
                     for t in temas)
    return f"""Você divide uma aula (transcrição) entre os vídeos de uma série. O texto vem em TRECHOS numerados [C1], [C2]…
Para CADA trecho, diga a qual vídeo ele pertence. Regras:
- Cada trecho vai para UM vídeo só (o que ele mais desenvolve). Nada de sobreposição.
- Não deixe o vídeo magro: tudo o que serve de base, exemplo, explicação, objeção ou citação de um vídeo vai pra ele.
- "fora" só para o que não serve a nenhum: avisos, logística do curso, intervalos, cumprimentos, repetição pura do que
  já foi dito, conversa que não é conteúdo.
- Responda TODOS os trechos, na ordem.

Vídeos (use o id):
{vids}
- fora: nenhum vídeo"""


def distribuir(base: str, aid: str, ids: List[str], progresso=None) -> Dict[str, Any]:
    """Divide os trechos da aula entre os temas `ids` (uma vez por geração). Guarda em a["fatias"]."""
    import ia_servico as ia
    a = carregar(base, aid)
    temas = [t for t in a.get("temas") or [] if t["id"] in ids]
    if not temas:
        raise TemasErro("nenhum tema marcado")
    fatias = fatiar(texto(base, aid))
    validos = {t["id"] for t in temas}
    dono: Dict[str, str] = {}
    blocos: List[List[int]] = [[]]
    tam = 0
    for i, f in enumerate(fatias):
        if tam + len(f) > BLOCO_ANALISE and blocos[-1]:
            blocos.append([])
            tam = 0
        blocos[-1].append(i)
        tam += len(f)
    for nb, bl in enumerate(blocos, 1):
        if progresso:
            progresso(f"✂ dividindo a aula entre os vídeos ({nb}/{len(blocos)})…")
        conteudo = "\n\n".join(f"[C{i + 1}] {fatias[i]}" for i in bl)
        with ia.rotulo(f"✂ Dividir a aula: {a['nome'][:50]}"):
            d = ia.chamar("roteiros", system_distribuir(temas), conteudo, schema=_schema_fatias(), max_tokens=8000,
                          effort="low", timeout=600)
        for x in (d or {}).get("fatias") or []:
            c = str(x.get("c") or "").strip().upper().lstrip("[").rstrip("]")
            v = str(x.get("video") or "").strip()
            if c.startswith("C") and c[1:].isdigit():
                dono[c] = v if v in validos else ("fora" if v.lower() == "fora" else "")
    # o que a IA pulou vai pro tema com mais palavras em comum (pra não perder conteúdo)
    chaves = {t["id"]: _palavras_chave(t) for t in temas}
    sem = 0
    for i, f in enumerate(fatias):
        c = f"C{i + 1}"
        if dono.get(c):
            continue
        sem += 1
        import unicodedata
        n = unicodedata.normalize("NFKD", f.lower()).encode("ascii", "ignore").decode()
        pal = {w[:7] for w in re.findall(r"[a-z]{5,}", n)}
        dono[c] = max(temas, key=lambda t: len(chaves[t["id"]] & pal))["id"]
    res = {"trechos": fatias, "dono": dono, "ids": sorted(validos), "em": time.time(), "adivinhados": sem}
    mexer(base, aid, lambda x: x.update(fatias=res))
    return res


def bruto_do_tema(a: Dict[str, Any], tid: str) -> str:
    fz = a.get("fatias") or {}
    tr, dono = fz.get("trechos") or [], fz.get("dono") or {}
    return "\n\n".join(tr[i] for i in range(len(tr)) if dono.get(f"C{i + 1}") == tid)


def resumo_fatias(a: Dict[str, Any]) -> Dict[str, Any]:
    fz = a.get("fatias") or {}
    tr, dono = fz.get("trechos") or [], fz.get("dono") or {}
    cont: Dict[str, int] = {}
    for i, f in enumerate(tr):
        k = dono.get(f"C{i + 1}") or "fora"
        cont[k] = cont.get(k, 0) + len(f.split())
    return cont


def _regra_exemplos_lapidar(a: Dict[str, Any]) -> str:
    if _so_ideias(a):
        return (REGRA_SO_IDEIA_NOTAS.replace("NÃO entra.", "NÃO entra (mesmo que fique bem mais curto que o original).")
                + bloco_historias(a))
    return """- EXEMPLOS CONCRETOS FICAM CONCRETOS: personagem, obra, autor, caso real, episódio contado (ex.: "numa prova, a maioria
  escolheu <tal personagem> de <tal livro>") ficam COM o nome e o detalhe — nunca vire "imagine um personagem…" ou "em certas
  interpretações…". É o que deixa o vídeo denso.
"""


def system_lapidar(a: Dict[str, Any], t: Dict[str, Any]) -> str:
    return f"""Você LAPIDA o material bruto de UM vídeo de YouTube: trechos de uma aula (transcrição) que já foram separados
para este vídeo. O resultado é a base que o roteirista vai ler — quanto mais conteúdo, melhor o vídeo.

Vídeo: {t['titulo']}
Ideia central: {t.get('tema') or ''}

Regras:
- NÃO RESUMA. Mantenha TODAS as ideias, argumentos, explicações, exemplos, analogias, distinções, termos técnicos,
  autores, obras e citações (com o que o texto atribui a cada um). O resultado fica com 70% a 90% do tamanho do original
  — só sai o que é ruído{" (e as histórias/casos do texto, que viram só a ideia que ilustram — veja abaixo)" if _so_ideias(a) else ""}.
- Tire o ruído da fala: hesitações, repetições, "né", "então", frases quebradas, idas e vindas.
- Corrija os erros óbvios de transcrição pelo contexto. NOMES deformados pelo reconhecimento de voz (autor, obra,
  personagem, lugar, evento) você RECONSTRÓI pelo contexto e pelo que você sabe (o som parecido + o assunto) e escreve
  certo — não descarte um exemplo só porque o nome veio torto. MAS o nome reconstruído tem que bater com TUDO o que o
  trecho conta (o que a pessoa/o personagem fez, a obra, a época): um nome que só soa parecido e não combina com a
  história contada é ERRO — nesse caso conte o exemplo sem o nome ("um personagem da literatura brasileira que…").
  Só deixe de fora o que for realmente incompreensível.
{_regra_exemplos_lapidar(a)}- Mantenha também o PORQUÊ que o texto dá (a explicação/a causa que quem fala propõe), não só a constatação.
- Organize na ordem LÓGICA (não precisa ser a ordem da fala), juntando o que fala da mesma coisa, com subtítulos curtos.
- NADA do evento: não mencione curso, aula, palestra, professor, alunos, perguntas do público, datas, nem o nome de quem
  fala. Nada de histórias pessoais de quem fala sobre a própria vida. O que for tese própria de quem fala (não de um autor
  clássico), escreva como "uma leitura possível: …".
- Não acrescente fatos, datas, citações ou estudos que não estão nos trechos.
- Texto puro (tópicos e parágrafos), em português claro. Sem JSON, sem comentários seus."""


def _pedacos(txt: str, maximo: int = LAPIDAR_PALAVRAS) -> List[str]:
    paras = [x for x in txt.split("\n\n") if x.strip()]
    out: List[str] = []
    atual: List[str] = []
    n = 0
    for p in paras:
        if atual and n + len(p.split()) > maximo:
            out.append("\n\n".join(atual))
            atual, n = [], 0
        atual.append(p)
        n += len(p.split())
    if atual:
        out.append("\n\n".join(atual))
    return out


def lapidar(base: str, a: Dict[str, Any], t: Dict[str, Any], progresso=None) -> str:
    """O bruto do tema, lapidado (pedaços de até LAPIDAR_PALAVRAS palavras)."""
    import ia_servico as ia
    bruto = bruto_do_tema(a, t["id"])
    if len(bruto.split()) < 80:
        raise TemasErro("nenhum trecho da aula ficou com este vídeo — refaça a divisão ou junte com outro tema")
    pedacos = _pedacos(bruto)
    saida: List[str] = []
    for k, pd in enumerate(pedacos, 1):
        if progresso:
            progresso(f"💎 lapidando o material ({k}/{len(pedacos)})…")
        pedido = ("Lapide este material (parte {k} de {n} — as outras partes são lapidadas à parte; não escreva introdução "
                  "nem conclusão geral):\n\n" if len(pedacos) > 1 else "Lapide este material:\n\n").format(k=k, n=len(pedacos)) + pd
        r = ""
        for _tent in range(2):
            with ia.rotulo("💎 Lapidar: " + t["titulo"][:60]):
                r = str(ia.chamar("roteiros", system_lapidar(a, t), pedido, max_tokens=16000, effort="low", timeout=900,
                                  cache_local=not _tent) or "").strip()
            if len(r.split()) >= (0.15 if _so_ideias(a) else 0.5) * len(pd.split()):
                break  # encolheu demais = resumiu: tenta de novo uma vez
        if len(r.split()) < 40:
            r = pd  # a IA falhou: fica o bruto mesmo (melhor que perder o trecho)
        saida.append(r)
    extra = ""
    if t.get("referencias"):
        extra = "\n\nReferências citadas: " + ", ".join(t["referencias"])
    return "\n\n".join(saida).strip() + extra


# ------------------------------------------------------------------ ⏱ v84_441: os minutos cabem no material
PALAVRAS_POR_MIN = 150
APROVEITA = 0.85  # do bruto que ficou com o vídeo, quanto vira roteiro (sai o ruído da fala; entram explicações/exemplos)


def minutos_possiveis(palavras_aula: int) -> float:
    return round(palavras_aula * APROVEITA / PALAVRAS_POR_MIN, 1)


def ajustar_minutos(base: str, aid: str, ids: List[str]) -> Dict[str, Any]:
    """Depois da divisão: se a aula tem pouco sobre um tema pros minutos pedidos (ex.: 24 min com ~2.000 palavras = um
    roteiro de 11 min "esticado" em vão), baixa os minutos pro que o material sustenta e avisa. Nunca sobe."""
    cont = resumo_fatias(carregar(base, aid))
    mudou: Dict[str, Any] = {}

    def f(a):
        for t in a.get("temas") or []:
            if t["id"] not in ids or t.get("projeto") or not cont.get(t["id"]):
                continue
            pode = minutos_possiveis(cont[t["id"]])
            pediu = float(t.get("minutos") or 0)
            if pediu and pode and pediu > pode * 1.15:
                novo = max(3.0, round(pode))
                t.setdefault("minutos_pedidos", pediu)
                t["minutos"] = novo
                mudou[t["id"]] = (pediu, novo, cont[t["id"]])
    mexer(base, aid, f)
    return mudou
