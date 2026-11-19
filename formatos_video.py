"""📐 v84_421 — Formatos de vídeo: a FÓRMULA do canal aprendida dos roteiros que já ficaram bons.

Pra cada 🕵️ Modelo de vídeo (ex.: 🏛 CenarioM — Filosofia):
  1. 🔎 a IA lê CADA roteiro pronto desse modelo e anota como ele foi construído — blocos (começo/meio/fim) com o
     peso de cada um, abertura, fechamento, recursos (analogia, personagem imaginário, exercício, objeção…), densidade
     (ideias/exemplos/autores por minuto), profundidade, tom e o que nunca aparece;
  2. 🧩 junta tudo numa FICHA do formato (o que se repete nos melhores) — editável;
  3. ✍️ a ficha entra no pedido de todo roteiro novo desse modelo;
  4. 💡 vídeo só com um TEMA: a IA pesquisa na internet e monta as NOTAS de pesquisa no mesmo padrão das que saem de um
     texto bruto (pensadores, obras, distinções, objeções, exemplos) — a base — e o roteiro sai com a ficha.

🔁 Aprender sozinho: DESLIGADO por padrão. Ativar = lê todos os roteiros do modelo; enquanto ativo, cada roteiro novo
entra na ficha. Desligado: o botão 🔄 Atualizar com os novos.

Tudo em <base>/formatos/<modelo>.json (fora do Git).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

import arquivo_seguro  # noqa: F401  (os.replace sem WinError 5)

PASTA = "formatos"
_TRAVA = threading.RLock()
_RODANDO: Dict[str, bool] = {}
MAX_ROTEIRO = 30_000  # caracteres de cada roteiro mandados pra análise
MAX_AMOSTRAS = 60     # análises guardadas (as mais recentes)


BASE: str = ""  # a pasta de dados do site (o formatos_rotas.registrar põe) — pro pedido de cada parte do roteiro


class FormatoErro(Exception):
    pass


def _ok_chave(modelo: str) -> str:
    m = re.sub(r"[^\w.-]", "_", str(modelo or ""))[:80]
    if not m:
        raise FormatoErro("Modelo inválido.")
    return m


def _arq(base: str, modelo: str) -> str:
    return os.path.join(base, PASTA, _ok_chave(modelo) + ".json")


def carregar(base: str, modelo: str) -> Dict[str, Any]:
    try:
        with open(_arq(base, modelo), encoding="utf-8") as f:
            d = json.load(f)
            if isinstance(d, dict):
                return d
    except (OSError, ValueError):
        pass
    return {"modelo": modelo, "ativo": False, "usar": True, "ficha": None, "texto_manual": "", "amostras": [],
            "criados": [], "estado": "", "msg": "", "atualizado": 0}


def salvar(base: str, d: Dict[str, Any]) -> None:
    d["atualizado"] = time.time()
    caminho = _arq(base, d["modelo"])
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def mexer(base: str, modelo: str, fn) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(base, modelo)
        fn(d)
        salvar(base, d)
        return d


# ------------------------------------------------------------------ os roteiros do modelo
def roteiros(base: str, modelo: str) -> List[Dict[str, Any]]:
    """Os projetos desse modelo que têm roteiro pronto: [{pid, titulo, texto, palavras, com_base, atualizado}]."""
    import dossies as ds
    out = []
    raiz = ds._pasta(base)
    for pid in (os.listdir(raiz) if os.path.isdir(raiz) else []):
        try:
            p = ds.carregar(base, pid)
        except Exception:  # noqa: BLE001
            continue
        if ((p.get("config") or {}).get("modelo") or "") != modelo:
            continue
        texto = ds.roteiro_para_voz(p).strip() or ds._texto_voz((p.get("resultado") or {}).get("roteiro") or "").strip()
        if len(texto.split()) < 300:
            continue
        com_base = any(str(f.get("site") or "") == "arquivo" for f in p.get("fontes") or [])  # aula/texto-base enviado
        out.append({"pid": p["id"], "titulo": ds.nome_do_projeto(p), "texto": texto, "palavras": len(texto.split()),
                    "com_base": com_base, "atualizado": p.get("atualizado") or 0})
    return sorted(out, key=lambda r: r["atualizado"])


def pendentes(base: str, modelo: str) -> List[Dict[str, Any]]:
    """Roteiros ainda não analisados (ou que mudaram muito depois da análise)."""
    d = carregar(base, modelo)
    feitos = {a["pid"]: a for a in d.get("amostras") or []}
    return [r for r in roteiros(base, modelo)
            if r["pid"] not in feitos or abs(int(feitos[r["pid"]].get("palavras") or 0) - r["palavras"]) > 150]


# ------------------------------------------------------------------ 🔎 análise de UM roteiro
def _schema_analise() -> Dict[str, Any]:
    from ia_midia import _I, _S, _lista, _obj
    bloco = _obj({"bloco": _S, "funcao": _S, "pct": _I, "como": _S})
    return _obj({"estrutura": _lista(bloco), "abertura": _S, "fechamento": _S, "recursos": _lista(_S),
                 "densidade": _S, "profundidade": _S, "tom": _S, "transicoes": _S, "evitar": _lista(_S),
                 "pontos_fortes": _lista(_S), "pontos_fracos": _lista(_S), "nota": _I})


SYSTEM_ANALISE = """Você é um roteirista-chefe analisando UM roteiro narrado de YouTube de um canal, pra descobrir a FÓRMULA do canal.
Não resuma o assunto: descreva COMO o roteiro é construído, de um jeito que outro roteirista consiga repetir com OUTRO tema.
- "estrutura": os blocos na ordem (gancho, apresentação da pergunta, base teórica, exemplo, passos práticos, erros comuns,
  virada, fechamento…): "bloco" (nome curto), "funcao" (o que ele faz pro espectador), "pct" (quanto do roteiro ocupa, 0-100;
  a soma dá ~100), "como" (a técnica: ex. "cena concreta em 2ª pessoa + pergunta", "personagem imaginário com nome").
- "abertura" e "fechamento": a técnica exata (com o tamanho em frases).
- "recursos": os recursos que aparecem (analogia do cotidiano, personagem imaginário, exercício pra fazer em casa, citação
  de pensador apresentado em poucas palavras, objeção e resposta, pergunta direta ao espectador, lista de passos…).
- "densidade": quantas ideias/conceitos, exemplos e autores por minuto (~150 palavras = 1 min), e como cada ideia é explicada.
- "profundidade": o quanto vai fundo (distinções, mecanismo, por quê) — e onde fica raso.
- "tom": pessoa (eu/você), formalidade, ritmo das frases, humor.
- "transicoes": como um bloco puxa o próximo.
- "evitar": o que o roteiro NÃO faz (ex.: não fala da fonte, não credita o professor) e vícios que aparecem e deveriam sumir.
- "pontos_fortes" / "pontos_fracos": o que faz este roteiro bom e o que o deixa pior.
- "nota": de 1 a 10, o quanto ele prende e entrega.
Responda só o JSON."""


def analisar_um(r: Dict[str, Any], rotulo: str = "") -> Dict[str, Any]:
    import ia_servico as ia
    conteudo = (f"Título: {r.get('titulo')}\nPalavras: {r.get('palavras')} (~{round((r.get('palavras') or 0) / 150)} min)\n"
                f"Feito a partir de uma aula/texto-base: {'sim' if r.get('com_base') else 'não'}\n\n"
                f"=== ROTEIRO ===\n{str(r.get('texto') or '')[:MAX_ROTEIRO]}\n=== FIM ===")
    with ia.rotulo(rotulo or ("📐 Formato: " + str(r.get("titulo") or "")[:50])):
        d = ia.chamar("roteiros", SYSTEM_ANALISE, conteudo, schema=_schema_analise(), max_tokens=3000, effort="low", timeout=300)
    if not isinstance(d, dict):
        raise FormatoErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
    return {"pid": r["pid"], "titulo": r.get("titulo") or "", "palavras": r.get("palavras") or 0, "com_base": bool(r.get("com_base")),
            "quando": time.time(), "analise": d}


# ------------------------------------------------------------------ 🧩 a ficha (junta as análises)
def _schema_ficha() -> Dict[str, Any]:
    from ia_midia import _I, _S, _lista, _obj
    bloco = _obj({"bloco": _S, "funcao": _S, "pct": _I, "como": _S})
    return _obj({"resumo": _S, "palavras": _I, "estrutura": _lista(bloco), "abertura": _S, "fechamento": _S,
                 "recursos_sempre": _lista(_S), "recursos_as_vezes": _lista(_S), "densidade": _S, "profundidade": _S,
                 "tom": _S, "transicoes": _S, "evitar": _lista(_S), "melhorar": _lista(_S), "pesquisa": _S})


SYSTEM_FICHA = """Você recebe as análises de VÁRIOS roteiros do mesmo canal de YouTube. Monte a FICHA DO FORMATO do canal: a
fórmula que outro roteirista vai seguir pra escrever um vídeo novo, com OUTRO tema, tão bom quanto os melhores.
- Use o que se REPETE nos roteiros de nota mais alta e nos feitos a partir de uma aula/texto-base (são a referência de
  profundidade). O que só aparece uma vez fica em "recursos_as_vezes".
- "estrutura": os blocos na ordem, com o peso (pct, soma ~100) e a técnica de cada um ("como").
- "palavras": o tamanho típico (mediana).
- "densidade" e "profundidade": em números e critérios concretos (ex.: "3 a 5 conceitos centrais, cada um com analogia +
  exemplo; 1 a 3 pensadores apresentados em 1 frase; 1 objeção respondida").
- "evitar": vícios e coisas proibidas; "melhorar": o que os piores roteiros erram e como evitar.
- "pesquisa": quando o vídeo for feito SÓ com um tema (sem aula), o que pesquisar pra chegar nessa profundidade (que tipo
  de autor, obra, conceito, exemplo, dado, objeção — e quantos).
- "resumo": a fórmula em 2-3 frases.
Escreva em português, curto e prático. Responda só o JSON."""


def consolidar(amostras: List[Dict[str, Any]], nome_modelo: str = "") -> Dict[str, Any]:
    import ia_servico as ia
    if not amostras:
        raise FormatoErro("Nenhum roteiro analisado ainda.")
    lista = [{"titulo": a.get("titulo"), "palavras": a.get("palavras"), "com_base": a.get("com_base"), **(a.get("analise") or {})}
             for a in amostras[-MAX_AMOSTRAS:]]
    with ia.rotulo("📐 Ficha do formato: " + (nome_modelo or "")[:50]):
        d = ia.chamar("roteiros", SYSTEM_FICHA, json.dumps(lista, ensure_ascii=False)[:120_000], schema=_schema_ficha(),
                      max_tokens=4000, effort="medium", timeout=420)
    if not isinstance(d, dict):
        raise FormatoErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
    d["n_roteiros"] = len(lista)
    return d


def texto_ficha(f: Optional[Dict[str, Any]]) -> str:
    """A ficha em texto (o que vai no pedido do roteiro e o que aparece/edita na página)."""
    if not f:
        return ""
    L = []
    if f.get("resumo"):
        L.append(f"Fórmula: {f['resumo']}")
    if f.get("palavras"):
        L.append(f"Tamanho típico: ~{f['palavras']} palavras (~{round(int(f['palavras']) / 150)} min) — vale o tamanho pedido no projeto.")
    if f.get("estrutura"):
        L.append("Estrutura (na ordem):")
        L += [f"  {k}. {b.get('bloco')} (~{b.get('pct')}%) — {b.get('funcao')}. Como: {b.get('como')}"
              for k, b in enumerate(f["estrutura"], 1)]
    for chave, nome in (("abertura", "Abertura"), ("fechamento", "Fechamento"), ("densidade", "Densidade"),
                        ("profundidade", "Profundidade"), ("tom", "Tom"), ("transicoes", "Transições")):
        if f.get(chave):
            L.append(f"{nome}: {f[chave]}")
    if f.get("recursos_sempre"):
        L.append("Recursos que SEMPRE aparecem: " + "; ".join(f["recursos_sempre"]))
    if f.get("recursos_as_vezes"):
        L.append("Recursos que às vezes aparecem: " + "; ".join(f["recursos_as_vezes"]))
    if f.get("evitar"):
        L.append("Evitar: " + "; ".join(f["evitar"]))
    if f.get("melhorar"):
        L.append("Onde os roteiros mais fracos erraram (não repita): " + "; ".join(f["melhorar"]))
    return "\n".join(L)


def bloco_prompt(base: str, modelo: str) -> str:
    """O bloco que entra no pedido de todo roteiro desse modelo (vazio se não tem ficha ou está desligado)."""
    try:
        d = carregar(base, modelo)
    except FormatoErro:
        return ""
    if not d.get("usar", True):
        return ""
    t = (d.get("texto_manual") or "").strip() or texto_ficha(d.get("ficha"))
    if not t:
        return ""
    n = (d.get("ficha") or {}).get("n_roteiros") or len(d.get("amostras") or [])
    return (f"## 📐 FORMATO DO CANAL (aprendido de {n} roteiro(s) que ficaram bons — siga esta fórmula com o tema deste vídeo; "
            "o tamanho pedido acima manda no tamanho)\n" + t)


# ------------------------------------------------------------------ 🔄 atualizar (em segundo plano)
def atualizar(base: str, modelo: str, refazer: bool = False, progresso=None) -> Dict[str, Any]:
    """Analisa os roteiros que faltam (ou todos, com refazer) e refaz a ficha."""
    import dossies as ds
    chave = _ok_chave(modelo)
    if _RODANDO.get(chave):
        raise FormatoErro("Já está atualizando esse formato — espere terminar.")
    _RODANDO[chave] = True
    try:
        if refazer:
            mexer(base, modelo, lambda d: d.update(amostras=[]))
        fila = pendentes(base, modelo)
        nome = ds.sem_emoji((ds.MODELOS.get(modelo) or {}).get("nome") or modelo)
        erros = 0
        for k, r in enumerate(fila, 1):
            mexer(base, modelo, lambda d: d.update(estado="analisando", msg=f"🔎 lendo o roteiro {k} de {len(fila)}: {r['titulo'][:60]}"))
            if progresso:
                progresso(f"🔎 roteiro {k} de {len(fila)}: {r['titulo'][:60]}")
            try:
                a = analisar_um(r)
            except Exception:  # noqa: BLE001 — um que falha não para os outros
                erros += 1
                continue

            def gravar(d, a=a):
                am = [x for x in d.get("amostras") or [] if x.get("pid") != a["pid"]] + [a]
                d["amostras"] = am[-MAX_AMOSTRAS:]
            mexer(base, modelo, gravar)
        d = carregar(base, modelo)
        if not d.get("amostras"):
            raise FormatoErro("Nenhum roteiro desse modelo pra analisar (precisa de roteiro pronto com 300+ palavras).")
        if fila or refazer or not d.get("ficha"):
            mexer(base, modelo, lambda d: d.update(estado="analisando", msg="🧩 juntando as análises na ficha…"))
            if progresso:
                progresso("🧩 juntando as análises na ficha do formato…")
            ficha = consolidar(d["amostras"], nome)
            d = mexer(base, modelo, lambda x: x.update(ficha=ficha, estado="pronto", msg=f"✅ ficha feita com {ficha['n_roteiros']} roteiro(s)"
                                                       + (f" · ⚠ {erros} não deram" if erros else "")))
        else:
            d = mexer(base, modelo, lambda x: x.update(estado="pronto", msg="✅ nada novo pra analisar"))
        return d
    except Exception as exc:
        mexer(base, modelo, lambda d: d.update(estado="erro", msg=f"❌ {exc}"))
        raise
    finally:
        _RODANDO.pop(chave, None)


def iniciar_atualizacao(base: str, modelo: str, refazer: bool = False) -> str:
    import tarefas_bg
    return tarefas_bg.iniciar("formato_video", "📐 Formato de vídeo: aprendendo dos roteiros",
                              lambda t: {"amostras": len(atualizar(base, modelo, refazer, t.progresso).get("amostras") or [])},
                              pagina="/formatos")


def ao_gerar_roteiro(base: str, p: Dict[str, Any]) -> None:
    """🔁 Chamado quando um roteiro fica pronto: se o formato do modelo está ATIVO, ele entra na ficha (em segundo plano)."""
    try:
        modelo = str((p.get("config") or {}).get("modelo") or "")
        if not modelo or not carregar(base, modelo).get("ativo") or _RODANDO.get(_ok_chave(modelo)):
            return

        def rodar():
            time.sleep(20)  # deixa a revisão/TTS que vem logo depois terminar antes de ler
            try:
                atualizar(base, modelo)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=rodar, name="formato-" + modelo, daemon=True).start()
    except Exception:  # noqa: BLE001 — nunca atrapalha a geração do roteiro
        pass


# ------------------------------------------------------------------ 💡 vídeo só com um TEMA: a pesquisa vira a base
def system_pesquisa(ficha: Optional[Dict[str, Any]], nome_modelo: str = "") -> str:
    o_que = (ficha or {}).get("pesquisa") or ("os pensadores e obras que tratam do tema (com o que cada um diz), as distinções e "
                                             "conceitos centrais, exemplos do cotidiano e casos históricos conhecidos, as "
                                             "objeções mais fortes e as respostas")
    prof = (ficha or {}).get("profundidade") or ""
    return f"""Você é o PESQUISADOR de um canal de YouTube{(' (' + nome_modelo + ')') if nome_modelo else ''}. Vai montar as NOTAS DE
PESQUISA de um vídeo sobre o tema pedido — a ÚNICA base que o roteirista vai ler. Elas têm que ter a profundidade de uma boa
aula sobre o assunto, não de um resumo de internet.
O que pesquisar: {o_que}
{('Profundidade que o canal costuma ter: ' + prof) if prof else ''}
Regras:
- PESQUISE NA INTERNET em fontes confiáveis (enciclopédias de filosofia/ciência, livros, artigos, universidades). Wikipedia
  só como ponto de partida.
- Escreva em português, em tópicos e parágrafos curtos, organizado por LÓGICA (do básico ao mais fundo), de 1500 a 3500
  palavras: os conceitos com a explicação, os argumentos na ordem, as distinções, quem disse o quê (pensador + obra, com a
  frase quando for célebre e verificável), exemplos e analogias do cotidiano, casos históricos REAIS, as objeções e as
  respostas, e o que isso muda na vida de quem assiste.
- Dado, data, citação ou estudo: só o que você confirmou. Dado que muda com o tempo: o mais recente, com o ano.
- No fim, "Fontes:" com os links usados.
- Sem JSON: texto puro."""


def pesquisar(base: str, modelo: str, tema: str, progresso=None) -> str:
    """As notas de pesquisa do tema (🤖 Claude com a busca na internet → 🔷 Gemini se o Claude não der)."""
    import dossies as ds
    import gemini_servico as gm
    import ia_servico as ia
    d = carregar(base, modelo)
    nome = ds.sem_emoji((ds.MODELOS.get(modelo) or {}).get("nome") or modelo)
    system = system_pesquisa(d.get("ficha"), nome)
    pedido = f"Tema do vídeo: {tema}\n\nMonte as notas de pesquisa (texto puro)."
    erros = []
    if ia.motivo_desligado("roteiros") is None:
        if progresso:
            progresso("🌐 pesquisando o tema na internet (🤖 Claude)…")
        with ia.rotulo("💡 Pesquisa: " + tema[:60]):
            r = ia.chamar("roteiros", system, pedido, max_tokens=12000, effort="medium", timeout=600, web=True, cache_local=False)
        if r and len(str(r).split()) > 300:
            return str(r).strip()
        erros.append("🤖 Claude não respondeu")
    if gm.chave():
        if progresso:
            progresso("🌐 pesquisando o tema na internet (🔷 Gemini)…")
        try:
            r = gm.checar(system + "\n\n" + pedido, rotulo="Pesquisa: " + tema[:60])
            t = str(r.get("texto") or "")
            if len(t.split()) > 300:
                fontes = r.get("fontes") or []
                if fontes and "Fontes:" not in t:
                    t += "\n\nFontes:\n" + "\n".join(f"- {x.get('titulo') or ''} {x.get('url') or ''}" for x in fontes[:20])
                return t.strip()
            erros.append("🔷 Gemini devolveu pouco texto")
        except Exception as exc:  # noqa: BLE001
            erros.append(f"🔷 Gemini: {exc}")
    raise FormatoErro("Não deu pra pesquisar o tema — " + (" · ".join(erros) or "ligue a 🤖 IA do site ou a chave do 🔷 Gemini"))


def resumo(base: str, modelo: str) -> Dict[str, Any]:
    d = carregar(base, modelo)
    rs = roteiros(base, modelo)
    feitos = {a["pid"] for a in d.get("amostras") or []}
    return {"modelo": modelo, "ativo": bool(d.get("ativo")), "usar": d.get("usar", True), "estado": d.get("estado") or "",
            "msg": d.get("msg") or "", "rodando": bool(_RODANDO.get(_ok_chave(modelo))), "roteiros": len(rs),
            "analisados": sum(1 for r in rs if r["pid"] in feitos), "pendentes": sum(1 for r in rs if r["pid"] not in feitos),
            "ficha": d.get("ficha"), "texto": (d.get("texto_manual") or "").strip() or texto_ficha(d.get("ficha")),
            "manual": bool((d.get("texto_manual") or "").strip()), "criados": (d.get("criados") or [])[-30:][::-1],
            "atualizado": d.get("atualizado") or 0}
