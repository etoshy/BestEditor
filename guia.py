"""
📘 Guia — a página /guia do site mostra os READMEs de docs/guia/ (como criar
transições, efeitos, destaques, textos, legendas, sons, cenas…) e o estado dos
➕ extras (assets/darkplanner/extras): quais arquivos foram lidos, quantos itens
de cada tipo e os erros.

O markdown é convertido aqui mesmo (um conversor pequeno, sem dependência):
títulos, parágrafos, listas, blocos de código, `código`, **negrito**, *itálico*,
links e tabelas — o suficiente pros arquivos do guia.
"""
from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, List, Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
PASTA_GUIA = os.path.join(_AQUI, "docs", "guia")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,60}$")


def paginas() -> List[Dict[str, str]]:
    """[{slug, titulo}] na ordem dos nomes (01-…, 02-…)."""
    out = []
    if not os.path.isdir(PASTA_GUIA):
        return out
    for nome in sorted(os.listdir(PASTA_GUIA)):
        if not nome.endswith(".md") or nome == "README.md":
            continue
        slug = nome[:-3]
        out.append({"slug": slug, "titulo": titulo_de(os.path.join(PASTA_GUIA, nome)) or slug})
    return out


def titulo_de(caminho: str) -> str:
    try:
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("# "):
                    return linha[2:].strip()
    except OSError:
        pass
    return ""


def ler(slug: str) -> Optional[str]:
    if slug in ("", "readme", "README"):
        caminho = os.path.join(PASTA_GUIA, "README.md")
    elif _SLUG.match(slug):
        caminho = os.path.join(PASTA_GUIA, slug + ".md")
    else:
        return None
    if not os.path.isfile(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return f.read()


# ------------------------------------------------------------------ markdown -> html
def _link(m: "re.Match[str]") -> str:
    texto, alvo = m.group(1), m.group(2)
    if not re.match(r"^(https?://|/|#)", alvo):
        base, _, ancora = alvo.partition("#")
        if base.endswith(".md"):
            nome = os.path.basename(base)[:-3]
            alvo = "/guia" + ("" if nome == "README" else "/" + nome) + (("#" + ancora) if ancora else "")
        elif base.startswith("exemplos/"):
            alvo = "/guia/" + base
    externo = alvo.startswith("http")
    return f'<a href="{alvo}"' + (' target="_blank" rel="noopener"' if externo else "") + f">{texto}</a>"


def _inline(t: str) -> str:
    partes = re.split(r"(`[^`]+`)", t)
    out = []
    for p in partes:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append("<code>" + html.escape(p[1:-1]) + "</code>")
            continue
        p = html.escape(p, quote=False)
        p = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, p)
        p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", p)
        out.append(p)
    return "".join(out)


def _ancora(t: str) -> str:
    t = re.sub(r"[^\w\s-]", "", t.lower(), flags=re.UNICODE).strip()
    return re.sub(r"[\s]+", "-", t)


def markdown_para_html(md: str) -> str:
    linhas = md.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    i = 0
    par: List[str] = []

    def fecha_par():
        if par:
            out.append("<p>" + _inline(" ".join(x.strip() for x in par)) + "</p>")
            par.clear()

    while i < len(linhas):
        ln = linhas[i]
        if ln.startswith("```"):
            fecha_par()
            lang = ln[3:].strip()
            bloco = []
            i += 1
            while i < len(linhas) and not linhas[i].startswith("```"):
                bloco.append(linhas[i])
                i += 1
            out.append(f'<pre class="lang-{html.escape(lang)}"><code>' + html.escape("\n".join(bloco)) + "</code></pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            fecha_par()
            n = len(m.group(1))
            out.append(f'<h{n} id="{_ancora(m.group(2))}">' + _inline(m.group(2)) + f"</h{n}>")
            i += 1
            continue
        if re.match(r"^\s*\|.*\|\s*$", ln) and i + 1 < len(linhas) and re.match(r"^\s*\|[\s:\-|]+\|\s*$", linhas[i + 1]):
            fecha_par()
            cab = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            corpo = []
            while i < len(linhas) and re.match(r"^\s*\|.*\|\s*$", linhas[i]):
                corpo.append([c.strip() for c in linhas[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cab) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in corpo) + "</tbody></table>")
            continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
        if m:
            fecha_par()
            ordenada = m.group(2)[0].isdigit()
            itens: List[List[str]] = []
            while i < len(linhas):
                m2 = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", linhas[i])
                if m2 and len(m2.group(1)) < 2:
                    itens.append([m2.group(3)])
                elif m2 or (linhas[i].startswith("  ") and linhas[i].strip() and itens):
                    itens[-1].append(linhas[i])
                else:
                    break
                i += 1
            tag = "ol" if ordenada else "ul"
            out.append(f"<{tag}>" + "".join("<li>" + _item_lista(it) + "</li>" for it in itens) + f"</{tag}>")
            continue
        if ln.startswith(">"):
            fecha_par()
            bloco = []
            while i < len(linhas) and linhas[i].startswith(">"):
                bloco.append(linhas[i][1:].strip())
                i += 1
            out.append("<blockquote>" + _inline(" ".join(bloco)) + "</blockquote>")
            continue
        if not ln.strip():
            fecha_par()
        elif re.match(r"^-{3,}$", ln.strip()):
            fecha_par()
            out.append("<hr>")
        else:
            par.append(ln)
        i += 1
    fecha_par()
    return "\n".join(out)


def _item_lista(linhas: List[str]) -> str:
    principal = [linhas[0]]
    filhos = []
    for ln in linhas[1:]:
        if re.match(r"^\s+([-*]|\d+\.)\s+", ln) or filhos:
            filhos.append(ln[2:] if ln.startswith("  ") else ln)
        else:
            principal.append(ln.strip())
    out = _inline(" ".join(principal))
    if filhos:
        out += markdown_para_html("\n".join(filhos))
    return out


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str) -> None:
    from flask import abort, jsonify, render_template, send_from_directory

    def _extras() -> Dict[str, Any]:
        try:
            import dp_extras
            return dp_extras.resumo()
        except Exception as exc:  # noqa: BLE001
            return {"pasta": "", "arquivos": [], "erros": [str(exc)], "contagem": {}}

    @app.route("/guia")
    @app.route("/guia/<slug>")
    def guia_page(slug: str = ""):
        md = ler(slug)
        if md is None:
            abort(404)
        return render_template("guia.html", corpo=markdown_para_html(md), paginas=paginas(), atual=slug,
                               extras=_extras(), titulo=(re.search(r"^# (.+)$", md, re.M) or [None, "Guia"])[1])

    @app.route("/guia/exemplos/<path:nome>")
    def guia_exemplo(nome: str):
        return send_from_directory(os.path.join(PASTA_GUIA, "exemplos"), nome, as_attachment=False, mimetype="application/json")

    @app.route("/guia/extras/recarregar", methods=["POST"])
    def guia_extras_recarregar():
        import dp_extras
        dp_extras.recarregar()
        return jsonify({"ok": True, **_extras(),
                        "aviso": "Destaques, filtros, efeitos, cenas, paletas, sons e fontes já valem. Transição NOVA só entra "
                                 "na lista de transições válidas depois de reiniciar o site (python app.py)."})
