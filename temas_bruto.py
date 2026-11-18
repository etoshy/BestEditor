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
from typing import Any, Dict, List, Optional

import arquivo_seguro  # noqa: F401  (os.replace sem WinError 5)

PASTA = "temas_bruto"
MAX_TEXTO = 600_000          # caracteres guardados do arquivo bruto
BLOCO_ANALISE = 220_000      # acima disso, a análise roda em blocos e junta no fim
MAX_TEMAS = 30

# 🧩 v84_411 — quantos vídeos sair de um texto. Antes: "de 4 a 15 temas" → uma aula virava 12 vídeos quase iguais, cada um
# com um pedaço; agora o padrão é POUCOS vídeos COMPLETOS, cada um juntando o que a aula diz sobre o eixo em qualquer parte.
DIVISOES = {
    "completo": {"nome": "🧩 Poucos vídeos, completos (2 a 5)", "faixa": (2, 5), "min": (14, 30), "palavras": (1500, 3500)},
    "equilibrado": {"nome": "⚖ Equilibrado (4 a 8)", "faixa": (4, 8), "min": (10, 20), "palavras": (900, 2400)},
    "maximo": {"nome": "📚 O máximo de vídeos (até 15)", "faixa": (4, 15), "min": (6, 20), "palavras": (600, 1800)},
}
DIVISAO_PADRAO = "completo"


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
                    "atualizado": a.get("atualizado") or 0})
    return sorted(out, key=lambda x: -x["atualizado"])


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


def criar(base: str, nome: str, modelo: str, conteudo: bytes, nome_arquivo: str, divisao_: str = "") -> Dict[str, Any]:
    import dossies as ds
    if modelo not in ds.MODELOS:
        raise TemasErro("Escolha um modelo de vídeo.")
    ext = os.path.splitext(nome_arquivo or "")[1].lower() or ".txt"
    if ext not in ds.EXT_ARQUIVO_FONTE:
        raise TemasErro("Arquivo: " + ", ".join(ds.EXT_ARQUIVO_FONTE) + ".")
    aid = uuid.uuid4().hex[:10]
    d = _pasta(base, aid)
    os.makedirs(d, exist_ok=True)
    orig = os.path.join(d, "original" + ext)
    with open(orig, "wb") as f:
        f.write(conteudo)
    if ext in (".txt", ".md", ".srt", ".vtt"):
        bruto = conteudo.decode("utf-8-sig", errors="replace")
    else:
        try:
            bruto = ds.ler_arquivo(orig)["texto"]
        except ds.DossieError as exc:
            excluir(base, aid)
            raise TemasErro(str(exc)) from exc
    limpo = limpar(bruto)[:MAX_TEXTO]
    if len(limpo.split()) < 150:
        excluir(base, aid)
        raise TemasErro("O texto é curto demais pra separar em vários vídeos (menos de 150 palavras).")
    with open(os.path.join(d, "texto.txt"), "w", encoding="utf-8") as f:
        f.write(limpo)
    a = {"id": aid, "nome": (nome or os.path.splitext(os.path.basename(nome_arquivo))[0] or "Texto bruto")[:160],
         "arquivo": os.path.basename(nome_arquivo or "")[:160], "modelo": modelo,
         "modelo_nome": ds.sem_emoji(ds.MODELOS[modelo].get("nome") or modelo), "palavras": len(limpo.split()),
         "estado": "novo", "erro": "", "temas": [], "criado": time.time(),
         "divisao": divisao_ if divisao_ in DIVISOES else DIVISAO_PADRAO}
    salvar(base, a)
    return a


# ------------------------------------------------------------------ 1. separar os temas (IA)
def _formatos(modelo: str) -> Dict[str, Dict[str, Any]]:
    import dossies as ds
    return (ds.MODELOS.get(modelo) or {}).get("formatos") or {}


def _schema_temas() -> Dict[str, Any]:
    from ia_midia import _I, _S, _lista, _obj
    tema = _obj({"titulo": _S, "tema": _S, "pontos": _lista(_S), "por_que": _S, "abertura": _S, "formato": _S,
                 "minutos": _I, "por_que_tempo": _S, "forca": _I, "referencias": _lista(_S),
                 "de_onde": _S})
    return _obj({"temas": _lista(tema)})


def _regra_divisao(a: Dict[str, Any]) -> str:
    d = divisao(a)
    lo, hi = DIVISOES[d]["faixa"]
    comum = ("- NADA DE SOBREPOSIÇÃO: cada ideia, exemplo, exercício e citação do texto pertence a UM vídeo só. Se dois temas "
             "dividem a mesma ideia central, os mesmos exemplos ou o mesmo exercício, ou um só faz sentido com o outro, "
             "eles viram UM vídeo. Tema raso ou só citado de passagem não entra.\n"
             "- Aulas e palestras VOLTAM aos assuntos: um tema começa no início, reaparece no meio e fecha no fim. Junte "
             "tudo o que o texto diz sobre o tema em QUALQUER parte — não corte o texto em fatias pela ordem.")
    if d == "completo":
        return (f"- Primeiro faça o MAPA do texto inteiro: quais são os GRANDES eixos (não os subtópicos). Cada vídeo é um eixo "
                f"COMPLETO, com começo, desenvolvimento e conclusão, reunindo a base teórica, os exemplos, os exercícios e "
                f"as objeções desse eixo. Devolva de {lo} a {hi} vídeos — prefira MENOS vídeos mais ricos a muitos vídeos "
                f"parecidos. Se o texto só tem um eixo forte, devolva {lo} mesmo assim só se o segundo se sustentar; senão 1.\n"
                + comum)
    if d == "equilibrado":
        return f"- Separe os temas que o texto realmente desenvolve: de {lo} a {hi} vídeos.\n" + comum
    return f"- Separe tudo o que o texto realmente desenvolve: em geral de {lo} a {hi} temas (no máximo {MAX_TEMAS}).\n" + comum


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
{_regra_divisao(a)}
- "titulo": o título do vídeo em português, chamativo e honesto (estilo YouTube; pergunta ou promessa clara), até 80 caracteres.
- "tema": em uma frase, a ideia central do vídeo.
- "pontos": de 3 a 7 tópicos curtos do que o vídeo cobre, NA ORDEM em que o vídeo contaria, com o que o texto diz
  (argumentos, exemplos, autores e obras citados).
- "por_que": por que esse tema funciona em vídeo (prático? polêmico? curiosidade? exercício que gera comentário?).
- "abertura": uma ideia de abertura fria pro vídeo — uma história real, um caso, um experimento ou uma pergunta concreta
  que encarna o tema (pode vir de fora do texto, se for conhecido e verdadeiro).
- "formato": a chave do formato do modelo que melhor combina:
{fmts}
- "minutos": a duração IDEAL do vídeo, pelo tanto que o texto rende sobre o tema (sem enrolação), em geral entre
  {DIVISOES[divisao(a)]['min'][0]} e {DIVISOES[divisao(a)]['min'][1]} min. Shorts = 1.
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


def ler_temas(d: Any, modelo: str) -> List[Dict[str, Any]]:
    """Limpa a lista de temas que a IA devolveu."""
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
        minutos = _num(x.get("minutos"), float((fmts.get(fmt) or {}).get("minutos") or 10), 1, 60)
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
    return ler_temas(r, a["modelo"]) if r else temas


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
    try:
        with ia.rotulo("📚 Temas: " + a["nome"][:60]):
            for k, bl in enumerate(blocos, 1):
                if progresso:
                    progresso(f"lendo o texto{f' (parte {k} de {len(blocos)})' if len(blocos) > 1 else ''}…")
                parte = f"parte {k} de {len(blocos)}" if len(blocos) > 1 else ""
                d = ia.chamar("roteiros", system_analise(a, bl, parte), "Separe os temas deste texto.",
                              schema=_schema_temas(), max_tokens=16000, effort="medium", timeout=900)
                if d is None:
                    raise TemasErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
                temas += ler_temas(d, a["modelo"])
            hi = DIVISOES[divisao(a)]["faixa"][1]
            if temas and (len(blocos) > 1 or len(temas) > hi or (divisao(a) != "maximo" and parecidos(temas))):
                if progresso:
                    progresso("juntando os temas que se sobrepõem…")
                temas = _juntar(temas, a, de_partes=len(blocos) > 1)
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
    temas = ler_temas(d, a["modelo"])
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
- Formato: texto puro em tópicos e parágrafos curtos, de {DIVISOES[divisao(a)]['palavras'][0]} a
  {DIVISOES[divisao(a)]['palavras'][1]} palavras conforme o material. Sem JSON.

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


def gerar_notas(base: str, a: Dict[str, Any], t: Dict[str, Any]) -> str:
    import ia_servico as ia
    tx = texto(base, a["id"])
    if len(tx) > BLOCO_ANALISE:  # texto enorme: as notas leem os blocos que mais falam do tema
        tx = _trechos_do_tema(tx, t)
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
