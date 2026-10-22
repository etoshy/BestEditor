"""
flow_correcoes.py — 🩹 Corrigir o Flow quando o Google muda a tela (v84_236)
===========================================================================

Fica na aba 🎬 Google Flow → 🩹 Corrigir. Quando um passo do Flow dá erro (o 🩺 diagnóstico guarda a foto e o HTML da
tela), dá pra:

  1. 🤖 Analisar com a IA do site: ela recebe o erro, a foto, o HTML da tela e o TRECHO do código envolvido (a função
     que deu o erro e os seletores que ela usa) e devolve o diagnóstico + as mudanças no código ({"arquivo", "de",
     "para"});
  2. 📋 Gerar o prompt completo pra OUTRA IA (ChatGPT, Claude, Gemini…): o que rolou, o texto e o HTML da tela, o código
     com o caminho e o número das linhas, as regras e o formato da resposta — e colar a resposta dela de volta.

As mudanças NUNCA tocam no código original (toolkit/googleflow/). Cada correção é uma CÓPIA inteira do pacote do Flow em
flow_correcoes/<id>/googleflow/ (a partir do código que está em uso — as correções se empilham), com as mudanças
aplicadas, catalogada em flow_correcoes/catalogo.json (quando, de que erro, o diagnóstico, as mudanças, o diff, os
testes, o estado). Testes antes de usar:
  • 🧪 compilar (py_compile);
  • 🧪 no HTML do erro: abre a página guardada num Chromium e conta quantos elementos cada seletor acha — no código
    original × na cópia (e os seletores que a correção diz que têm que achar);
  • 🧪 a suíte do Flow simulado (toolkit/googleflow/test_flow_direto.py) rodando CONTRA a cópia (~8 min).

✔ Ativar: o pacote `googleflow` passa a carregar da cópia (o original fica atrás, como reserva). ↩ Voltar ao original
desfaz na hora. A escolha vale também quando o site abre de novo. Com o Flow trabalhando (lote/janela aberta), a troca
fica pra próxima vez que o site abrir.
"""
from __future__ import annotations

import ast
import difflib
import io
import json
import os
import py_compile
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

_BASE = os.path.dirname(os.path.abspath(__file__))
ORIGINAL = os.path.join(_BASE, "toolkit", "googleflow")
ARQUIVOS = ("flow_direto.py", "googleflow_client.py")  # o que a correção pode mudar
_TRAVA = threading.RLock()
RE_ID = re.compile(r"^c\d{3,5}$")
TESTES: Dict[str, Dict[str, Any]] = {}  # id → a suíte rodando


class CorrecaoErro(Exception):
    pass


def pasta(base: str = _BASE) -> str:
    return os.environ.get("FLOW_CORRECOES_DIR") or os.path.join(base, "flow_correcoes")


def _cat_path(base: str = _BASE) -> str:
    return os.path.join(pasta(base), "catalogo.json")


def catalogo(base: str = _BASE) -> Dict[str, Any]:
    try:
        with open(_cat_path(base), encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    c.setdefault("ativa", None)
    c.setdefault("itens", [])
    return c


def _salvar_cat(c: Dict[str, Any], base: str = _BASE) -> None:
    os.makedirs(pasta(base), exist_ok=True)
    tmp = _cat_path(base) + f".{secrets.token_hex(3)}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _cat_path(base))


def item(c: Dict[str, Any], cid: str) -> Dict[str, Any]:
    x = next((i for i in c["itens"] if i["id"] == cid), None)
    if not x:
        raise CorrecaoErro("Correção não encontrada.")
    return x


def pasta_copia(cid: str, base: str = _BASE) -> str:
    if not RE_ID.match(cid or ""):
        raise CorrecaoErro("correção inválida")
    return os.path.join(pasta(base), cid, "googleflow")


def codigo_em_uso(base: str = _BASE) -> str:
    """A pasta do pacote do Flow que está valendo agora (a cópia ativa ou o original)."""
    a = catalogo(base).get("ativa")
    if a and os.path.isdir(pasta_copia(a, base)):
        return pasta_copia(a, base)
    return ORIGINAL


def _ler(caminho: str) -> str:
    with open(caminho, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ ✔ ativar / ↩ voltar (o pacote carrega da cópia)
def _flow_ocupado() -> str:
    try:
        import flow_lote
        if flow_lote.reservado():
            return "o 🚀 Flow em massa (ou uma janela de conta) está usando o Flow"
        if flow_lote.lote().rodando:
            return "o 🚀 Flow em massa está rodando"
    except Exception:  # noqa: BLE001
        pass
    try:
        import flow_estudio as FE
        if FE._ESTADO.get("rodando"):
            return "uma geração da aba Flow está rodando"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _apontar(copia: Optional[str], recarregar: bool = True) -> None:
    """Faz `import googleflow.X` achar a cópia primeiro (o original fica atrás, como reserva)."""
    import importlib
    tk = os.path.join(_BASE, "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    # a cópia mora em outra pasta: os dados do Flow (contas, sessões, galeria) continuam em flow_dados/ do site
    os.environ.setdefault("GOOGLEFLOW_DATA_DIR", os.path.join(_BASE, "flow_dados"))
    import googleflow
    caminhos = [os.path.abspath(ORIGINAL)]
    if copia:
        caminhos.insert(0, os.path.abspath(copia))
    googleflow.__path__[:] = caminhos
    if recarregar:
        for nome in ("googleflow.googleflow_client", "googleflow.flow_direto"):
            m = sys.modules.get(nome)
            if m is not None:
                importlib.reload(m)


def aplicar_no_boot(base: str = _BASE) -> Optional[str]:
    """Chamado pelo app.py ao abrir o site (antes de qualquer `import googleflow`)."""
    try:
        a = catalogo(base).get("ativa")
        if a and os.path.isdir(pasta_copia(a, base)):
            _apontar(pasta_copia(a, base), recarregar=True)
            return a
    except Exception:  # noqa: BLE001
        pass
    return None


def ativar(cid: Optional[str], base: str = _BASE) -> Dict[str, Any]:
    """✔ Usa a correção `cid` (None = ↩ o código original). Com o Flow trabalhando, vale quando o site abrir de novo."""
    with _TRAVA:
        c = catalogo(base)
        if cid:
            x = item(c, cid)
            if x["estado"] == "falhou":
                raise CorrecaoErro("Essa correção não foi aplicada inteira (veja o que falhou) — não dá pra ativar.")
            if not os.path.isdir(pasta_copia(cid, base)):
                raise CorrecaoErro("Os arquivos dessa correção sumiram.")
        antes = c.get("ativa")
        for x in c["itens"]:
            if x["id"] == antes and antes != cid:
                x["estado"] = "revertida"
                x.setdefault("historico", []).append({"quando": time.time(), "o_que": "↩ desativada"})
        c["ativa"] = cid
        if cid:
            x = item(c, cid)
            x["estado"] = "ativa"
            x.setdefault("historico", []).append({"quando": time.time(), "o_que": "✔ ativada"})
        _salvar_cat(c, base)
    ocupado = _flow_ocupado()
    if ocupado:
        return {"ok": True, "agora": False, "aviso": f"{ocupado} — a troca vale quando o site abrir de novo (ou pare e clique de novo)."}
    try:
        _apontar(pasta_copia(cid, base) if cid else None, recarregar=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": True, "agora": False, "aviso": f"não recarreguei agora ({type(exc).__name__}: {str(exc)[:160]}) — reinicie o site."}
    return {"ok": True, "agora": True}


# ------------------------------------------------------------------ 🩺 o erro (diagnóstico guardado)
def _gf():
    tk = os.path.join(_BASE, "toolkit")
    if tk not in sys.path:
        sys.path.insert(0, tk)
    from googleflow import googleflow_client as gf
    return gf


def diagnostico(diag: str) -> Dict[str, Any]:
    """O erro guardado pelo 🩺: o motivo (1ª linha), o passo ([config_agente]), o texto da página, o HTML, a foto."""
    if not re.fullmatch(r"\d{8}_\d{6}_\d{6}", diag or ""):
        raise CorrecaoErro("diagnóstico inválido")
    arqs = {a.name[len(diag):]: str(a) for a in _gf().arquivos_do_diagnostico(diag)}
    if not arqs:
        raise CorrecaoErro("Esse diagnóstico não existe mais (só os 20 últimos ficam guardados).")
    txt = _ler(arqs[".txt"]) if ".txt" in arqs else ""
    motivo = txt.split("\n", 1)[0].strip()
    texto_pagina = txt.split("--- texto da página ---", 1)[-1].strip() if "--- texto da página ---" in txt else ""
    m = re.search(r"\[(\w+)\]", motivo)
    return {"id": diag, "motivo": motivo, "passo": m.group(1) if m else "", "texto_pagina": texto_pagina[:6000],
            "html_importante": _ler(arqs["_html.txt"]).split("\n", 2)[-1] if "_html.txt" in arqs else "",
            "pagina": arqs.get("_pagina.html"), "foto": arqs.get(".png")}


def html_resumido(html: str, chaves: List[str], limite: int = 28000) -> str:
    """O HTML sem o que não importa pra achar um botão (scripts, estilos, svg, atributos do Angular) e, se ainda for
    grande, só os pedaços em volta das palavras dos seletores envolvidos."""
    h = re.sub(r"<head\b.*?</head>", "", html or "", flags=re.S | re.I)
    h = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", "", h, flags=re.S | re.I)
    h = re.sub(r"<(?:meta|link)\b[^>]*>", "", h, flags=re.I)
    h = re.sub(r'="([^"]{160})[^"]{40,}"', r'="\1…"', h)  # links enormes (imagens com token) encurtados
    try:
        h = _gf().limpar_dados_pessoais(h)  # e-mail, nome da conta e foto do perfil saem
    except Exception:  # noqa: BLE001
        h = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "email@removido", h)
    h = re.sub(r"<!--.*?-->", "", h, flags=re.S)
    h = re.sub(r'\s(?:_ngcontent|_nghost)-[\w-]+=""', "", h)
    h = re.sub(r'\s(?:style|jsaction|jslog|data-ved|nonce|mat-ripple-loader-[\w-]+)="[^"]*"', "", h)
    h = re.sub(r"\s+", " ", h)
    if len(h) <= limite:
        return h
    janelas: List[Tuple[int, int]] = []
    for ch in chaves:
        for m in re.finditer(re.escape(ch), h):
            janelas.append((max(0, m.start() - 1200), min(len(h), m.end() + 1200)))
            if len(janelas) > 80:
                break
    if not janelas:  # nada dos seletores: a caixa de comando e os botões costumam estar no fim
        return h[:limite // 3] + " … " + h[-(limite * 2 // 3):]
    janelas.sort()
    juntas: List[List[int]] = []
    for a, b in janelas:
        if juntas and a <= juntas[-1][1]:
            juntas[-1][1] = max(juntas[-1][1], b)
        else:
            juntas.append([a, b])
    out, total = [], 0
    for a, b in juntas:
        if total >= limite:
            break
        out.append(h[a:b])
        total += b - a
    return " … ".join(out)[:limite]


# ------------------------------------------------------------------ 🔎 o código envolvido
def _seletores(fonte: str) -> Dict[str, Any]:
    """Os dicionários de seletores do arquivo (S do flow_direto, PISTAS do googleflow_client) → {chave: valor}."""
    out: Dict[str, Any] = {}
    try:
        arv = ast.parse(fonte)
    except SyntaxError:
        return out
    for no in arv.body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name) \
                and no.targets[0].id in ("S", "PISTAS") and isinstance(no.value, ast.Dict):
            try:
                d = ast.literal_eval(no.value)
            except ValueError:
                continue
            for k, v in d.items():
                out[f"{no.targets[0].id}[{k}]"] = v
    return out


def _lista_sel(v: Any) -> List[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, str)]
    return []


def trecho_do_codigo(diag: Dict[str, Any], raiz: str) -> Dict[str, Any]:
    """Acha no código a função que deu o erro (pela mensagem ou pelo passo) e os seletores que ela usa.
    → {"funcoes": [{arquivo, nome, ini, fim, codigo}], "seletores": {chave: valor}, "chamadas": [...], "chaves_html": [...]}"""
    msg = re.sub(r"^\s*\[\w+\]\s*", "", diag.get("motivo") or "")
    msg = re.sub(r"^\w+(?:Erro|Error|Exception)\s*:\s*", "", msg)
    msg = re.sub(r"\s*\(conta [^)]*\)\s*$", "", msg)  # o lote junta a conta no fim
    pedacos = [p for p in re.split(r'["“”()]', msg) if len(p.strip()) >= 12][:3] or [msg[:40]]
    funcoes: List[Dict[str, Any]] = []
    sels: Dict[str, Any] = {}
    inteira = msg.strip()[:70]
    achou_inteira = len(inteira) >= 15 and any(
        os.path.isfile(os.path.join(raiz, a)) and inteira in _ler(os.path.join(raiz, a)) for a in ARQUIVOS)
    for arq in ARQUIVOS:
        cam = os.path.join(raiz, arq)
        if not os.path.isfile(cam):
            continue
        fonte = _ler(cam)
        linhas = fonte.split("\n")
        todos = _seletores(fonte)
        try:
            defs = [n for n in ast.walk(ast.parse(fonte)) if isinstance(n, ast.FunctionDef)]
        except SyntaxError:
            defs = []
        # 1º a mensagem inteira (como está no código); senão as linhas com MAIS pedaços dela
        alvo_linhas = [k for k, ln in enumerate(linhas, 1) if inteira in ln] if achou_inteira else []
        if not alvo_linhas and not achou_inteira:
            notas = [(sum(1 for p in pedacos if p.strip() and p.strip()[:50] in ln), k) for k, ln in enumerate(linhas, 1)]
            melhor = max([n for n, _k in notas] or [0])
            alvo_linhas = [k for n, k in notas if n and n == melhor]
        if not alvo_linhas and diag.get("passo"):
            alvo_linhas = [k for k, ln in enumerate(linhas, 1) if f'"{diag["passo"]}"' in ln][:3]
        for k in alvo_linhas[:3]:
            f = min((d for d in defs if d.lineno <= k <= (d.end_lineno or d.lineno)), key=lambda d: d.end_lineno - d.lineno, default=None)
            if f is None or any(x["arquivo"] == arq and x["nome"] == f.name for x in funcoes):
                continue
            codigo = "\n".join(linhas[f.lineno - 1:f.end_lineno])
            funcoes.append({"arquivo": arq, "nome": f.name, "ini": f.lineno, "fim": f.end_lineno, "codigo": codigo[:9000]})
            for chave in set(re.findall(r'S\["(\w+)"\]', codigo)):
                if f"S[{chave}]" in todos:
                    sels[f"{arq}: S[{chave}]"] = todos[f"S[{chave}]"]
            for chave in set(re.findall(r'_achar\(\w+, "(\w+)"', codigo)) | set(re.findall(r'PISTAS\["(\w+)"\]', codigo)):
                if f"PISTAS[{chave}]" in todos:
                    sels[f"{arq}: PISTAS[{chave}]"] = todos[f"PISTAS[{chave}]"]
            # quem a chama no mesmo arquivo (ex.: configurar_agente → _configurar_agente), se for curta
            for g in defs:
                if g is f or len(funcoes) >= 5 or any(x["nome"] == g.name for x in funcoes) or (g.end_lineno - g.lineno) > 60:
                    continue
                cod_g = "\n".join(linhas[g.lineno - 1:g.end_lineno])
                if re.search(rf"\b{re.escape(f.name)}\(", cod_g):
                    funcoes.append({"arquivo": arq, "nome": g.name, "ini": g.lineno, "fim": g.end_lineno, "codigo": cod_g[:6000]})
            # as funções do mesmo arquivo que ela chama e que usam seletores (ex.: ligar_agente dentro de configurar_agente)
            for chamada in set(re.findall(r"\b(\w+)\(", codigo)):
                g = next((d for d in defs if d.name == chamada and d is not f), None)
                if g is not None and len(funcoes) < 5 and not any(x["nome"] == g.name for x in funcoes):
                    cod_g = "\n".join(linhas[g.lineno - 1:g.end_lineno])
                    if 'S["' in cod_g and (g.end_lineno - g.lineno) < 80:
                        funcoes.append({"arquivo": arq, "nome": g.name, "ini": g.lineno, "fim": g.end_lineno, "codigo": cod_g[:6000]})
                        for chave in set(re.findall(r'S\["(\w+)"\]', cod_g)):
                            if f"S[{chave}]" in todos:
                                sels[f"{arq}: S[{chave}]"] = todos[f"S[{chave}]"]
    chamadas = []
    for f in funcoes[:2]:
        for arq in ARQUIVOS:
            cam = os.path.join(raiz, arq)
            if os.path.isfile(cam):
                for k, ln in enumerate(_ler(cam).split("\n"), 1):
                    if re.search(rf"\b{re.escape(f['nome'])}\(", ln) and not ln.lstrip().startswith("def "):
                        chamadas.append(f"{arq}:{k}: {ln.strip()[:160]}")
    chaves_html: List[str] = []
    for v in sels.values():
        for s in _lista_sel(v):
            chaves_html += [t for t in re.findall(r"[a-z][\w-]{3,}", s) if "-" in t or t.startswith("flow")]
    return {"funcoes": funcoes, "seletores": sels, "chamadas": chamadas[:12],
            "chaves_html": list(dict.fromkeys(chaves_html))[:30] or ["flow-prompt-box", "button"]}


# ------------------------------------------------------------------ 🤖 IA do site / 📋 prompt pra outra IA
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["diagnostico", "causa", "confianca", "mudancas", "seletores_esperados", "observacoes"],
    "properties": {
        "diagnostico": {"type": "string"}, "causa": {"type": "string"},
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "mudancas": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                "required": ["arquivo", "de", "para", "motivo"],
                                                "properties": {"arquivo": {"type": "string", "enum": list(ARQUIVOS)},
                                                               "de": {"type": "string"}, "para": {"type": "string"},
                                                               "motivo": {"type": "string"}}}},
        "seletores_esperados": {"type": "array", "items": {"type": "string"}},
        "observacoes": {"type": "string"},
    },
}

REGRAS = (
    "- O sistema automatiza o Google Flow (flow.google.com) com Python + Playwright (sync). O Google muda a tela de vez "
    "em quando (botões somem, mudam de nome/classe, viram outro componente) e o passo quebra.\n"
    "- Descubra pelo HTML e pela foto O QUE MUDOU na tela e corrija o código com a MENOR mudança possível.\n"
    "- Prefira deixar o código TOLERANTE às duas versões: ADICIONE o seletor novo junto do antigo (separados por vírgula "
    "no mesmo texto de seletor), em vez de apagar o antigo. Se um recurso SUMIU da tela (ex.: um botão/modo que não existe "
    "mais), faça o passo detectar isso e seguir sem ele (registrando com on_passo) — não invente cliques.\n"
    "- Os seletores são do Playwright (CSS + :has(), :has-text(), :text-is()). Use o que está no HTML de verdade (tags "
    "flow-*, classes, aria-label em português).\n"
    "- Cada mudança é uma troca de TEXTO: \"de\" = um trecho COPIADO EXATAMENTE do código mostrado (com a mesma "
    "indentação; ÚNICO no arquivo — inclua linhas vizinhas se precisar), \"para\" = o trecho novo. O código final tem "
    "que ser Python válido. Não mexa em nada que não tem a ver com o erro.\n"
    "- \"seletores_esperados\": os seletores que, com a sua correção, TÊM que achar elemento no HTML desta tela (o "
    "sistema testa no HTML guardado).\n"
    "- Comentários em português, no estilo do código. Responda em português."
)


def contexto(diag_id: str, base: str = _BASE) -> Dict[str, Any]:
    d = diagnostico(diag_id)
    raiz = codigo_em_uso(base)
    tr = trecho_do_codigo(d, raiz)
    pagina = _ler(d["pagina"]) if d.get("pagina") else ""
    html = html_resumido(d["html_importante"] if len(d["html_importante"]) > 4000 or not pagina else pagina, tr["chaves_html"])
    if pagina and len(html) < 20000:  # a parte importante é pequena: junta o resumo da página inteira
        html += "\n<!-- ===== PÁGINA INTEIRA (resumida) ===== -->\n" + html_resumido(pagina, tr["chaves_html"], 26000 - len(html))
    return {"diag": d, "trecho": tr, "html": html, "raiz": raiz,
            "raiz_rel": os.path.relpath(raiz, _BASE).replace(os.sep, "/")}


def _texto_contexto(ctx: Dict[str, Any], com_foto: bool) -> str:
    d, tr = ctx["diag"], ctx["trecho"]
    L = ["## O erro", f"Mensagem: {d['motivo']}", f"Passo: {d['passo'] or '?'}",
         f"Código em uso: {ctx['raiz_rel']}/" + (" (uma correção anterior já ativa)" if "flow_correcoes" in ctx["raiz_rel"] else " (o original)")]
    if com_foto:
        L.append("A foto da tela no momento do erro vai junto (imagem).")
    L += ["", "## O que a tela mostrava (texto visível, resumido)", (d["texto_pagina"] or "(sem texto)")[:3500],
          "", "## O HTML da tela (resumido — sem scripts/estilos/svg; só os pedaços em volta dos seletores envolvidos)",
          "```html", ctx["html"], "```", "", "## O código envolvido"]
    for f in tr["funcoes"]:
        L += [f"### {ctx['raiz_rel']}/{f['arquivo']} — `{f['nome']}()` (linhas {f['ini']}–{f['fim']})", "```python", f["codigo"], "```"]
    if tr["seletores"]:
        L += ["### Os seletores que essas funções usam", "```python"]
        L += [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in tr["seletores"].items()]
        L += ["```"]
    if tr["chamadas"]:
        L += ["### Quem chama", *[f"- {x}" for x in tr["chamadas"]]]
    return "\n".join(L)


def prompt_outra_ia(diag_id: str, base: str = _BASE) -> str:
    """📋 O prompt completo pra mandar pra outra IA (com tudo que ela precisa pra entender e corrigir)."""
    ctx = contexto(diag_id, base)
    return ("# Corrigir a automação do Google Flow — a tela do Flow mudou e um passo quebrou\n\n"
            "Você é um engenheiro Python experiente em Playwright. Abaixo estão o erro, a tela (texto e HTML) e o código "
            "envolvido. Descubra o que mudou e devolva a correção.\n\n## Regras\n" + REGRAS + "\n\n"
            + _texto_contexto(ctx, com_foto=False)
            + "\n\n(Se puder, eu mando a foto da tela também.)\n\n## Resposta — SOMENTE um JSON válido, neste formato:\n```json\n"
            + json.dumps({"diagnostico": "o que mudou na tela do Flow", "causa": "por que o código quebrou",
                          "confianca": "alta | media | baixa",
                          "mudancas": [{"arquivo": "flow_direto.py", "de": "trecho EXATO do código atual", "para": "trecho novo",
                                        "motivo": "por que"}],
                          "seletores_esperados": ["seletor que tem que achar elemento nesta tela"],
                          "observacoes": "algo que eu deva saber/testar"}, ensure_ascii=False, indent=1)
            + "\n```")


def analisar_ia(diag_id: str, base: str = _BASE) -> Dict[str, Any]:
    """🤖 A IA do site analisa e devolve a correção → vira um item do catálogo (cópia + mudanças + teste no HTML)."""
    import ia_servico
    ctx = contexto(diag_id, base)
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": _texto_contexto(ctx, com_foto=bool(ctx["diag"].get("foto")))}]
    if ctx["diag"].get("foto"):
        b = ia_servico.imagem_bloco(ctx["diag"]["foto"], largura=1200)
        if b:
            conteudo.append(b)
    sistema = ("Você corrige a automação do Google Flow (Python + Playwright) quando a tela do Flow muda.\n" + REGRAS)
    r = ia_servico.chamar("flow_correcao", sistema, conteudo, schema=SCHEMA, max_tokens=8000, effort="high", pensar=True,
                          timeout=300, cache_local=False)
    if r is None:
        raise CorrecaoErro("A IA não respondeu (desligada, sem crédito ou erro) — use 📋 o prompt pra outra IA.")
    return criar(r, diag_id, "🤖 IA do site", base)


# ------------------------------------------------------------------ 🗂 criar a correção (cópia + mudanças), testar
def _novo_id(c: Dict[str, Any]) -> str:
    n = max([int(i["id"][1:]) for i in c["itens"]] or [0]) + 1
    return f"c{n:03d}"


def _diff(a: str, b: str, nome: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), f"original/{nome}", f"corrigido/{nome}", n=2))


def criar(resposta: Any, diag_id: str, origem: str, base: str = _BASE) -> Dict[str, Any]:
    """A resposta (da IA do site ou colada de outra) → copia o código em uso inteiro pra flow_correcoes/<id>/googleflow,
    aplica as mudanças NA CÓPIA, compila e testa no HTML do erro. O original não é tocado."""
    if isinstance(resposta, str):
        import json_ia
        try:
            resposta = json_ia.carregar(resposta, aceitar_cortado=True)
        except ValueError as exc:
            raise CorrecaoErro(f"Não consegui ler o JSON da resposta: {exc}")
    if not isinstance(resposta, dict) or not isinstance(resposta.get("mudancas"), list):
        raise CorrecaoErro("A resposta precisa ter a lista \"mudancas\" (veja o formato no fim do prompt).")
    with _TRAVA:
        c = catalogo(base)
        cid = _novo_id(c)
        base_ativa = c.get("ativa")
        origem_codigo = codigo_em_uso(base)
        destino = pasta_copia(cid, base)
        shutil.copytree(origem_codigo, destino, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        mudancas = []
        for m in resposta["mudancas"][:30]:
            if not isinstance(m, dict):
                continue
            arq = os.path.basename(str(m.get("arquivo") or ""))
            de, para = str(m.get("de") or ""), str(m.get("para") or "")
            reg = {"arquivo": arq, "de": de[:20000], "para": para[:20000], "motivo": str(m.get("motivo") or "")[:600],
                   "aplicada": False, "erro": ""}
            cam = os.path.join(destino, arq)
            if arq not in ARQUIVOS or not os.path.isfile(cam):
                reg["erro"] = f"arquivo fora do que pode ser mudado ({', '.join(ARQUIVOS)})"
            elif not de.strip():
                reg["erro"] = "o \"de\" veio vazio"
            else:
                fonte = _ler(cam)
                n = fonte.count(de)
                if n == 0:  # tolera diferença só de espaço no fim das linhas
                    de_ = "\n".join(l.rstrip() for l in de.split("\n"))
                    fonte_ = "\n".join(l.rstrip() for l in fonte.split("\n"))
                    if fonte_.count(de_) == 1:
                        fonte, de, n = fonte_, de_, 1
                if n == 0:
                    reg["erro"] = "o trecho \"de\" não está no código (a IA não copiou igual)"
                elif n > 1:
                    reg["erro"] = f"o trecho \"de\" aparece {n} vezes — precisa ser único"
                else:
                    with open(cam, "w", encoding="utf-8") as f:
                        f.write(fonte.replace(de, para, 1))
                    reg["aplicada"] = True
            mudancas.append(reg)
        diffs, compilou = {}, []
        for arq in ARQUIVOS:
            a, b = os.path.join(ORIGINAL, arq), os.path.join(destino, arq)
            if os.path.isfile(a) and os.path.isfile(b):
                d = _diff(_ler(a), _ler(b), arq)
                if d:
                    diffs[arq] = d[:60000]
            try:
                py_compile.compile(b, doraise=True, cfile=os.path.join(pasta(base), cid, "_compilado.pyc"))
            except py_compile.PyCompileError as exc:
                compilou.append(f"{arq}: {str(exc)[-400:]}")
        aplicadas = sum(1 for m in mudancas if m["aplicada"])
        estado = "falhou" if (not aplicadas or compilou or aplicadas < len(mudancas)) else "pronta"
        d = {}
        try:
            d = diagnostico(diag_id)
        except CorrecaoErro:
            pass
        x = {"id": cid, "criado": time.time(), "origem": origem, "diag": diag_id, "erro": d.get("motivo") or "",
             "passo": d.get("passo") or "", "base": base_ativa or "original",
             "titulo": (str(resposta.get("diagnostico") or "") or d.get("motivo") or "correção")[:160],
             "diagnostico": str(resposta.get("diagnostico") or "")[:2000], "causa": str(resposta.get("causa") or "")[:2000],
             "confianca": str(resposta.get("confianca") or "")[:10], "observacoes": str(resposta.get("observacoes") or "")[:2000],
             "seletores_esperados": [str(s)[:500] for s in resposta.get("seletores_esperados") or [] if str(s).strip()][:20],
             "mudancas": mudancas, "diffs": diffs, "compilacao": compilou, "estado": estado, "testes": {},
             "historico": [{"quando": time.time(), "o_que": f"criada ({origem}) — {aplicadas}/{len(mudancas)} mudança(s) aplicada(s) na cópia"}]}
        c["itens"].insert(0, x)
        c["itens"] = c["itens"][:60]
        _salvar_cat(c, base)
        with open(os.path.join(pasta(base), cid, "correcao.json"), "w", encoding="utf-8") as f:
            json.dump(dict(x, resposta_original=resposta), f, ensure_ascii=False, indent=1)
    if not compilou and aplicadas:
        try:
            testar_html(cid, base)
        except Exception:  # noqa: BLE001
            pass
    return item(catalogo(base), cid)


def _contar(page, sels: List[str]) -> Tuple[int, str]:
    total, erro = 0, ""
    for s in sels:
        try:
            total += page.locator(s).count()
        except Exception as exc:  # noqa: BLE001 — seletor inválido
            erro = str(exc).split("\n")[0][:160]
    return total, erro


def testar_html(cid: str, base: str = _BASE) -> Dict[str, Any]:
    """🧪 Abre o HTML guardado do erro num Chromium e conta quantos elementos cada seletor acha — no código ORIGINAL
    (o que estava em uso quando a correção foi criada) × na CÓPIA, e os seletores que a correção diz que têm que achar."""
    c = catalogo(base)
    x = item(c, cid)
    d = diagnostico(x["diag"])
    if not d.get("pagina"):
        raise CorrecaoErro("Esse erro não guardou a página inteira — sem HTML pra testar.")
    html = _ler(d["pagina"])
    base_dir = ORIGINAL if x["base"] == "original" else pasta_copia(x["base"], base)
    antes, depois = {}, {}
    for arq in ARQUIVOS:
        for k, v in _seletores(_ler(os.path.join(base_dir, arq))).items():
            antes[f"{arq}: {k}"] = v
        cam = os.path.join(pasta_copia(cid, base), arq)
        if os.path.isfile(cam):
            for k, v in _seletores(_ler(cam)).items():
                depois[f"{arq}: {k}"] = v
    envolvidos = set(trecho_do_codigo(d, base_dir)["seletores"])
    from playwright.sync_api import sync_playwright
    linhas = []
    with sync_playwright() as pw:
        nav = pw.chromium.launch(headless=True)
        try:
            pg = nav.new_page()
            pg.set_content(re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I), wait_until="domcontentloaded", timeout=60000)
            for k in sorted(set(antes) | set(depois)):
                mudou = antes.get(k) != depois.get(k)
                if not mudou and k not in envolvidos:
                    continue
                na, ea = _contar(pg, _lista_sel(antes.get(k))) if k in antes else (None, "")
                nd, ed = _contar(pg, _lista_sel(depois.get(k))) if k in depois else (None, "")
                linhas.append({"seletor": k, "mudou": mudou, "envolvido": k in envolvidos, "antes": na, "depois": nd,
                               "erro": ed or "", "valor": depois.get(k, antes.get(k))})
            esperados = []
            for s in x.get("seletores_esperados") or []:
                n, e = _contar(pg, [s])
                esperados.append({"seletor": s, "achou": n, "erro": e})
        finally:
            nav.close()
    ok_esp = all(e["achou"] > 0 for e in esperados) if esperados else None
    invalidos = [l["seletor"] for l in linhas if l["erro"]] + [e["seletor"] for e in esperados if e["erro"]]
    resumo = ("✔ " if ok_esp and not invalidos else "⚠ " if esperados else "") + (
        f"{sum(1 for e in esperados if e['achou'])}/{len(esperados)} seletor(es) esperado(s) acham elemento nesta tela"
        if esperados else "a correção não disse que seletores testar") + (f" · ❌ {len(invalidos)} seletor(es) inválido(s)" if invalidos else "")
    r = {"quando": time.time(), "linhas": linhas, "esperados": esperados, "ok": bool(ok_esp) and not invalidos, "resumo": resumo}
    with _TRAVA:
        c = catalogo(base)
        x = item(c, cid)
        x.setdefault("testes", {})["html"] = r
        if x["estado"] == "pronta" and r["ok"]:
            x["estado"] = "testada"
        x.setdefault("historico", []).append({"quando": time.time(), "o_que": f"🧪 teste no HTML do erro: {resumo}"})
        _salvar_cat(c, base)
    return r


def testar_suite(cid: str, base: str = _BASE) -> Dict[str, Any]:
    """🧪 A suíte do Flow SIMULADO (test_flow_direto.py) rodando contra a CÓPIA (~8 min, em segundo plano)."""
    raiz = os.path.join(pasta(base), cid)
    copia = pasta_copia(cid, base)
    teste = os.path.join(copia, "test_flow_direto.py")
    if not os.path.isfile(teste):
        raise CorrecaoErro("A cópia não tem a suíte do Flow simulado.")
    with open(os.path.join(raiz, "pytest.ini"), "w", encoding="utf-8") as f:
        f.write("[pytest]\n")
    env = dict(os.environ, GOOGLEFLOW_DATA_DIR=os.path.join(raiz, "_dados_teste"), PYTHONDONTWRITEBYTECODE="1")
    t0 = time.time()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", raiz, "-c",
                        os.path.join(raiz, "pytest.ini"), teste], cwd=raiz, env=env, capture_output=True, text=True, timeout=3600)
    saida = (r.stdout or "") + (r.stderr or "")
    fim = [l for l in saida.strip().split("\n") if re.search(r"passed|failed|error|skipped", l)][-1:] or [saida.strip()[-200:]]
    res = {"quando": time.time(), "ok": r.returncode == 0, "resumo": fim[0][:300], "segundos": round(time.time() - t0),
           "saida": saida[-6000:]}
    with _TRAVA:
        c = catalogo(base)
        x = item(c, cid)
        x.setdefault("testes", {})["suite"] = res
        x.setdefault("historico", []).append({"quando": time.time(), "o_que": f"🧪 suíte do Flow simulado: {res['resumo']}"})
        _salvar_cat(c, base)
    shutil.rmtree(os.path.join(raiz, "_dados_teste"), ignore_errors=True)
    return res


def apagar(cid: str, base: str = _BASE) -> None:
    with _TRAVA:
        c = catalogo(base)
        item(c, cid)
        if c.get("ativa") == cid:
            raise CorrecaoErro("Essa correção está ativa — volte ao original (ou ative outra) antes de apagar.")
        if any(i.get("base") == cid for i in c["itens"]):
            pass  # as que foram feitas em cima dela são cópias inteiras: continuam funcionando
        c["itens"] = [i for i in c["itens"] if i["id"] != cid]
        _salvar_cat(c, base)
    shutil.rmtree(os.path.join(pasta(base), cid), ignore_errors=True)


def zip_da_correcao(cid: str, base: str = _BASE) -> bytes:
    """⬇ Os arquivos mudados + o diff + o registro (pra guardar, mandar pra alguém ou levar pro código de vez)."""
    c = catalogo(base)
    x = item(c, cid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in ARQUIVOS:
            if arq in (x.get("diffs") or {}):
                z.write(os.path.join(pasta_copia(cid, base), arq), f"{cid}/googleflow/{arq}")
                z.writestr(f"{cid}/{arq}.diff", x["diffs"][arq])
        z.writestr(f"{cid}/correcao.json", json.dumps(x, ensure_ascii=False, indent=1))
    return buf.getvalue()


def para_tela(base: str = _BASE) -> Dict[str, Any]:
    c = catalogo(base)
    return {"ativa": c.get("ativa"), "itens": c["itens"], "testes_rodando": {k: v for k, v in TESTES.items() if not v.get("fim")},
            "ocupado": _flow_ocupado()}


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str = _BASE) -> None:
    from flask import Response, jsonify, request

    def _erro(msg: str, cod: int = 400):
        return jsonify({"ok": False, "erro": str(msg)}), cod

    @app.route("/flow/correcoes")
    def flow_correcoes_estado():
        return jsonify(dict(para_tela(base_dir), ok=True))

    @app.route("/flow/correcoes/prompt/<diag>")
    def flow_correcoes_prompt(diag: str):
        try:
            return jsonify({"ok": True, "prompt": prompt_outra_ia(diag, base_dir)})
        except CorrecaoErro as exc:
            return _erro(str(exc))

    def _fundo(chave: str, rotulo: str, fn: Callable[[], Any]):
        t = TESTES.get(chave)
        if t and not t.get("fim"):
            return _erro(f"Já está rodando: {t['rotulo']}", 409)
        TESTES[chave] = {"rotulo": rotulo, "inicio": time.time(), "fim": None, "erro": None}

        def corpo():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                TESTES[chave]["erro"] = str(exc)[:500]
                try:
                    import notificacoes
                    notificacoes.avisar(f"❌ 🩹 {rotulo}", str(exc)[:400], "/flow#correcoes", "erro", tipo="flow")
                except Exception:  # noqa: BLE001
                    pass
            finally:
                TESTES[chave]["fim"] = time.time()
        threading.Thread(target=corpo, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/flow/correcoes/analisar/<diag>", methods=["POST"])
    def flow_correcoes_analisar(diag: str):
        try:
            diagnostico(diag)
        except CorrecaoErro as exc:
            return _erro(str(exc))
        return _fundo("ia:" + diag, "🤖 Analisando o erro com a IA", lambda: analisar_ia(diag, base_dir))

    @app.route("/flow/correcoes/colar", methods=["POST"])
    def flow_correcoes_colar():
        c = request.get_json(silent=True) or {}
        try:
            x = criar(str(c.get("texto") or ""), str(c.get("diag") or ""), "📋 outra IA", base_dir)
        except CorrecaoErro as exc:
            return _erro(str(exc))
        return jsonify({"ok": True, "item": x})

    @app.route("/flow/correcoes/<cid>/<acao>", methods=["POST"])
    def flow_correcoes_acao(cid: str, acao: str):
        try:
            if acao == "ativar":
                return jsonify(ativar(cid, base_dir))
            if acao == "testar_html":
                return jsonify({"ok": True, "teste": testar_html(cid, base_dir)})
            if acao == "testar_suite":
                return _fundo("suite:" + cid, f"🧪 Suíte do Flow simulado ({cid})", lambda: testar_suite(cid, base_dir))
            if acao == "apagar":
                apagar(cid, base_dir)
                return jsonify({"ok": True})
        except CorrecaoErro as exc:
            return _erro(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _erro(f"{type(exc).__name__}: {str(exc)[:300]}")
        return _erro("ação desconhecida", 404)

    @app.route("/flow/correcoes/original", methods=["POST"])
    def flow_correcoes_original():
        return jsonify(ativar(None, base_dir))

    @app.route("/flow/correcoes/<cid>.zip")
    def flow_correcoes_zip(cid: str):
        try:
            dados = zip_da_correcao(cid, base_dir)
        except CorrecaoErro as exc:
            return str(exc), 404
        return Response(dados, mimetype="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="correcao_flow_{cid}.zip"'})
