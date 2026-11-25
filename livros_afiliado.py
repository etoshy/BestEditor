"""📖 v84_462 — LIVROS CITADOS com link de afiliado da Amazon (monetizar antes do YPP).

Fluxo (na página do roteiro, aba 📖 Livros):
  1. 🤖 a IA lê o roteiro e sugere 0 a 3 livros que REALMENTE combinam com o vídeo (e onde citar cada um). Se o tema não
     tem livro que alguém compraria, ela diz que não vale — e não sugere nada.
  2. você procura na Amazon (botão 🔎), copia o SEU link de afiliado e cola aqui → o site lê a página (título, autor,
     capa) e guarda a capa como imagem do projeto.
  3. ✍️ "Adaptar o roteiro": a IA põe UMA menção curta e natural de cada livro escolhido no melhor ponto (onde a ideia
     do livro aparece — nada de propaganda no meio do raciocínio), com a capa entrando na tela nessa frase, e uma
     linha no fim ("os livros citados estão na descrição"). Fica guardada a versão SEM livros: dá pra alternar.
  4. o link vai no topo da descrição e/ou no comentário fixado (o texto pronto pra colar) — com o aviso da Amazon.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

AVISO = "Como associado da Amazon, ganho com compras qualificadas."
DESTINOS = {"ambos": "descrição + comentário fixado", "descricao": "só na descrição", "comentario": "só no comentário fixado"}
MAX_LIVROS = 3


class LivroErro(Exception):
    pass


# ------------------------------------------------------------------ estado no projeto
def estado(p: Dict[str, Any]) -> Dict[str, Any]:
    res = p.setdefault("resultado", {})
    lv = res.setdefault("livros", {})
    lv.setdefault("sugeridos", [])
    lv.setdefault("escolhidos", [])
    lv.setdefault("destino", "ambos")
    return lv


def tag_afiliado() -> str:
    try:
        from site_config import load_site_config
        return str(load_site_config().get("amazon_tag") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def com_tag(link: str, tag: str = "") -> str:
    """O link com o SEU código de afiliado (?tag=…) — se você já colou o link do SiteStripe (com tag) ou um amzn.to, fica igual."""
    link = str(link or "").strip()
    tag = (tag or tag_afiliado()).strip()
    if not link or not tag:
        return link
    u = urlparse(link)
    if not re.search(r"(^|\.)amazon\.", u.netloc or ""):
        return link  # link curto (amzn.to, link.amazon) já vem com a tag de quem gerou
    q = dict(parse_qsl(u.query))
    if q.get("tag"):
        return link
    q["tag"] = tag
    return urlunparse(u._replace(query=urlencode(q)))


def busca_amazon(livro: Dict[str, Any]) -> str:
    termo = " ".join(x for x in (livro.get("titulo"), livro.get("autor")) if x)
    return "https://www.amazon.com.br/s?k=" + quote_plus(termo) + "&i=stripbooks"


# ------------------------------------------------------------------ 1. sugestões da IA
SISTEMA_SUGERIR = """Você escolhe LIVROS pra indicar com link de afiliado num vídeo narrado de YouTube (o canal ganha uma
comissão pequena se alguém comprar). Leia o roteiro e responda com honestidade:
- Só indique livro que quem ASSISTIU a este vídeo teria vontade real de ler: a obra de onde vem a ideia central, o
  clássico que o vídeo cita, ou um livro acessível que aprofunda exatamente o tema. Nada genérico, nada só "relacionado".
- 0 a 3 livros, do mais forte pro menos forte. Se o vídeo não tem livro que alguém compraria (tema do dia a dia, humor,
  fofoca, algo sem obra por trás), devolva "livros": [] e diga o porquê em "motivo" — não force.
- Prefira edições que existem em português no Brasil. Título e autor como aparecem na capa.
- "onde": a frase do roteiro (copiada letra por letra, curta) em que citar o livro cai NATURAL — onde a ideia dele
  aparece; nunca no gancho do começo nem no meio de um raciocínio que ainda não fechou.
- "por_que": 1 frase do que o livro acrescenta pra quem assistiu (vai virar a menção no vídeo).
Responda SÓ o JSON."""


def _schema_sugerir() -> Dict[str, Any]:
    from ia_midia import _S, _obj
    item = _obj({"titulo": _S, "autor": _S, "por_que": _S, "onde": _S})
    return _obj({"vale_a_pena": {"type": "boolean"}, "motivo": _S, "livros": {"type": "array", "items": item}})


def sugerir(p: Dict[str, Any], chamar=None) -> Dict[str, Any]:
    res = p.get("resultado") or {}
    rot = _roteiro_base(p)
    if not rot.strip():
        raise LivroErro("Ainda não tem roteiro.")
    import ia_servico as ia
    chamar = chamar or ia.chamar
    if chamar is ia.chamar:
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            raise LivroErro("IA: " + motivo)
    conteudo = (f"Tema/título: {p.get('tema') or ''} — {(res.get('titulos') or [''])[0]}\n\nROTEIRO:\n{rot[:24000]}")
    with ia.rotulo("📖 Livros pra indicar: " + str(p.get("tema") or "")[:50]):
        d = chamar("roteiros", SISTEMA_SUGERIR, conteudo, schema=_schema_sugerir(), max_tokens=1500, effort="medium",
                   timeout=180, cache_local=False)
    if not isinstance(d, dict):
        raise LivroErro("A IA não respondeu (veja em 🤖 IA).")
    livros = []
    for x in (d.get("livros") or [])[:MAX_LIVROS]:
        if isinstance(x, dict) and str(x.get("titulo") or "").strip():
            lv = {k: " ".join(str(x.get(k) or "").split())[:300] for k in ("titulo", "autor", "por_que", "onde")}
            lv["busca"] = busca_amazon(lv)
            livros.append(lv)
    lv = estado(p)
    lv.update(sugeridos=livros, vale_a_pena=bool(d.get("vale_a_pena", bool(livros))) and bool(livros),
              motivo=" ".join(str(d.get("motivo") or "").split())[:400], sugerido_em=time.time())
    return lv


# ------------------------------------------------------------------ 2. o link de afiliado → dados + capa
def ler_link(link: str, baixar=None, ler=None) -> Dict[str, Any]:
    """Abre o link da Amazon e lê título, autor e a capa (reaproveita o leitor do 🛒 Vídeo de venda)."""
    import vendas as vd
    link = str(link or "").strip()
    if not re.match(r"https?://", link):
        raise LivroErro("Cole o link completo da Amazon (começa com https://).")
    if not vd._eh_amazon(link):
        raise LivroErro("Esse link não é da Amazon.")
    try:
        html, final = (baixar or vd.baixar_html)(link)
        d = (ler or vd.ler_amazon)(html, final)
    except vd.VendaError as exc:
        raise LivroErro(str(exc)) from exc
    titulo = str(d.get("titulo") or "").strip()
    autor = ""
    m = re.search(r'id="bylineInfo"[^>]*>(.*?)</div>', html or "", re.S) or re.search(r'class="author[^"]*"[^>]*>(.*?)</span>', html or "", re.S)
    if m:
        autor = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        autor = re.sub(r"\((Autor|Author|Tradutor|Translator)[^)]*\)|Formato:.*$|Seguir", "", autor).strip(" ,|")[:120]
    return {"titulo": titulo[:200], "autor": autor, "preco": d.get("preco") or "", "capa_url": (d.get("imagens") or [""])[0],
            "url_final": final or link}


def adicionar(base: str, p: Dict[str, Any], link: str, sugerido: Optional[int] = None, baixar_capa=None, **kw) -> Dict[str, Any]:
    """Cola o link de afiliado de um livro (sugerido pela IA ou outro): lê a página e guarda a capa como imagem do projeto."""
    import dossies as ds
    lv = estado(p)
    if len(lv["escolhidos"]) >= MAX_LIVROS:
        raise LivroErro(f"No máximo {MAX_LIVROS} livros por vídeo (mais que isso vira propaganda).")
    info = ler_link(link, **kw)
    sug = lv["sugeridos"][sugerido] if sugerido is not None and 0 <= sugerido < len(lv["sugeridos"]) else {}
    livro = {"id": f"L{int(time.time() * 1000) % 10_000_000}", "titulo": info["titulo"] or sug.get("titulo") or "livro",
             "titulo_curto": sug.get("titulo") or _curto(info["titulo"]), "autor": info["autor"] or sug.get("autor") or "",
             "link": com_tag(link), "preco": info["preco"], "por_que": sug.get("por_que") or "", "onde": sug.get("onde") or "",
             "capa": ""}
    if info.get("capa_url"):
        try:
            import vendas as vd
            cam, tipo = (baixar_capa or vd.baixar_arquivo)(info["capa_url"], ds.pasta_midias(base, p["id"]), f"capa_{livro['id']}")
            if tipo == "foto":
                m = ds.adicionar_midia(p, tipo="foto", origem="amazon", arquivo=os.path.basename(cam), url=info["capa_url"],
                                       nome=livro["titulo_curto"][:200], legenda=f"capa do livro {livro['titulo_curto']}",
                                       descricao=f"Capa do livro “{livro['titulo_curto']}”{' de ' + livro['autor'] if livro['autor'] else ''} "
                                                 "(aparece quando o vídeo cita o livro)", usar="descricao")
                livro["capa"] = m["id"]
        except Exception:  # noqa: BLE001 — sem capa o link funciona igual
            pass
    lv["escolhidos"].append(livro)
    return livro


def _curto(titulo: str) -> str:
    """"O Mito de Sísifo: Ensaio sobre o absurdo (Português) Capa comum – 1 janeiro 2018" → "O Mito de Sísifo"."""
    t = re.split(r"\s[\(\[–—|]|\s-\s|:\s", str(titulo or ""))[0].strip()
    return t[:120] or str(titulo or "")[:120]


def remover(p: Dict[str, Any], lid: str) -> None:
    lv = estado(p)
    lv["escolhidos"] = [x for x in lv["escolhidos"] if x.get("id") != lid]


# ------------------------------------------------------------------ 3. adaptar o roteiro (com / sem livros)
SISTEMA_ADAPTAR = """Você ajusta um roteiro narrado de YouTube pra citar LIVROS com naturalidade (o link fica na descrição).
Regras — a menção tem que somar, nunca parecer anúncio:
- Para CADA livro: UMA menção curta (1 frase, no máximo 2) no ponto em que a ideia do livro aparece no roteiro — de
  preferência o "onde" indicado; se ele não for bom, escolha o melhor ponto: depois que a ideia fechou, nunca no gancho do
  começo nem cortando um raciocínio. Diga título e autor do jeito que se fala ("como Camus escreve em O Mito de Sísifo…",
  "isso está todo em ‘O Mito de Sísifo’, do Camus"). Pode dizer por que vale ler em meia frase. Nada de "compre", "link",
  "promoção", "patrocinado", nada de preço.
- Logo ANTES da frase da menção, ponha a marca da capa (ex.: [I7]) — é a imagem da capa entrando na tela nessa hora.
- No FIM do roteiro (perto da despedida, junto do aviso de que as fontes estão na descrição, se houver), UMA frase:
  os livros citados estão na descrição (ex.: "Os livros que eu citei estão na descrição, se você quiser ir mais fundo.").
  Se já existe a frase das fontes/correções, junte as duas numa só.
- Mude o MÍNIMO: só as frases onde a menção entra. Mesmo tom, mesma língua, mesmas marcas [[...]] e [I…] do resto.
- "de": trecho COPIADO letra por letra do roteiro (a frase onde a menção entra, inteira); "para": essa frase + a menção
  (ou a menção encaixada nela). Não repita o mesmo "de" em duas trocas.
Responda SÓ o JSON: {"trocas": [{"de": "...", "para": "...", "livro": "título"}]}"""


def _roteiro_base(p: Dict[str, Any]) -> str:
    res = p.get("resultado") or {}
    return str(res.get("roteiro_sem_livros") or res.get("roteiro") or "")


def adaptar(p: Dict[str, Any], chamar=None) -> str:
    """O roteiro COM os livros escolhidos (a partir da versão SEM livros, guardada). Devolve o roteiro novo."""
    import ia_servico as ia
    import revisao_roteiro as rv
    from ia_midia import _S, _obj
    lv = estado(p)
    livros = lv["escolhidos"]
    if not livros:
        raise LivroErro("Cole o link de pelo menos um livro antes.")
    res = p["resultado"]
    base_rot = _roteiro_base(p)
    if not base_rot.strip():
        raise LivroErro("Ainda não tem roteiro.")
    chamar = chamar or ia.chamar
    if chamar is ia.chamar:
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            raise LivroErro("IA: " + motivo)
    lista = "\n".join(f"- “{x['titulo_curto']}”{' — ' + x['autor'] if x['autor'] else ''} · marca da capa: "
                      f"{'[' + x['capa'] + ']' if x.get('capa') else '(sem capa — não ponha marca)'}"
                      f"{' · por que: ' + x['por_que'] if x.get('por_que') else ''}{' · onde: “' + x['onde'] + '”' if x.get('onde') else ''}"
                      for x in livros)
    schema = _obj({"trocas": {"type": "array", "items": _obj({"de": _S, "para": _S, "livro": _S})}})
    with ia.rotulo("📖 Roteiro com os livros: " + str(p.get("tema") or "")[:50]):
        d = chamar("roteiros", SISTEMA_ADAPTAR, f"LIVROS:\n{lista}\n\nROTEIRO:\n{base_rot}", schema=schema, max_tokens=4000,
                   effort="medium", timeout=300, cache_local=False)
    trocas = [t for t in (d or {}).get("trocas") or [] if isinstance(t, dict) and str(t.get("de") or "").strip()]
    if not trocas:
        raise LivroErro("A IA não devolveu onde citar os livros (veja em 🤖 IA).")
    r = rv.aplicar(base_rot, json.dumps({"trocas": [{"de": t["de"], "para": t.get("para") or "", "motivo": "📖 livro"}
                                                    for t in trocas]}, ensure_ascii=False))
    if not r["aplicadas"]:
        raise LivroErro("Os trechos que a IA escolheu não bateram com o roteiro — tente de novo.")
    res["roteiro_sem_livros"] = base_rot
    res["roteiro_com_livros"] = r["texto"]
    lv["adaptado_em"] = time.time()
    lv["nao_achadas"] = len(r["nao_achadas"])
    return r["texto"]


# ------------------------------------------------------------------ 4. descrição e comentário fixado
def _linhas(livros: List[Dict[str, Any]]) -> List[str]:
    return [f"- {x['titulo_curto']}{' — ' + x['autor'] if x.get('autor') else ''}: {x['link']}" for x in livros if x.get("link")]


def bloco_descricao(res: Dict[str, Any]) -> str:
    lv = (res or {}).get("livros") or {}
    if not lv.get("escolhidos") or lv.get("destino") == "comentario" or not lv.get("ativo"):
        return ""
    ls = _linhas(lv["escolhidos"])
    if not ls:
        return ""
    return ("📖 Livros citados neste vídeo:\n" if len(ls) > 1 else "📖 O livro citado neste vídeo:\n") + "\n".join(ls) + f"\n({AVISO})"


def comentario_fixado(res: Dict[str, Any]) -> str:
    lv = (res or {}).get("livros") or {}
    if not lv.get("escolhidos") or lv.get("destino") == "descricao" or not lv.get("ativo"):
        return ""
    ls = _linhas(lv["escolhidos"])
    if not ls:
        return ""
    return ("📖 Os livros que eu citei no vídeo, pra quem quiser ir mais fundo:\n" if len(ls) > 1 else
            "📖 O livro que eu citei no vídeo, pra quem quiser ir mais fundo:\n") + "\n".join(ls) + f"\n\n{AVISO}"
