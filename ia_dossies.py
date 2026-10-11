"""
🤖 Modelos de vídeo (🕵️ dossiês) e 🛒 Vídeo de venda com IA (LEIA-ME §9):

  passo A  duplicadas()        — a mesma foto em vários tamanhos vira UMA (hash perceptual, de graça);
  passo B  fichar_imagens()    — ficha de cada imagem: o que é, quem/o quê, texto na imagem, tipo
                                 (lixo/anúncio são descartados, dá pra recuperar), sensível, qualidade;
  passo C  ler_pdf()            — PDF escaneado/com tabela lido pela IA (partes de 25 páginas);
           condensar()          — arquivo grande → dossiê condensado (fatos com a página de cada um);
  passo D  (fichar_imagens nas mídias do PC sem descrição);
  passo E  conferir_marcas()    — as marcas [I3] em frases que não combinam com a imagem.

Tudo devolve None/{} sem IA — o dossiê segue como antes.
"""
from __future__ import annotations

import io
import os
import re
from typing import Any, Callable, Dict, List, Optional

import ia_servico as ia
from ia_midia import _B, _I, _S, _lista, _obj

TIPOS_IMAGEM = ["foto_real", "documento", "print", "mapa", "infografico", "arte", "anuncio", "lixo"]
SENSIVEL = ["nao", "violencia", "corpo", "menor", "dados_pessoais"]
SCHEMA_IMAGENS = _obj({"imagens": _lista(_obj({
    "id": _S, "descricao": _S, "quem_ou_o_que": _S, "tipo": {"type": "string", "enum": TIPOS_IMAGEM},
    "texto_na_imagem": _S, "epoca": _S, "util": _B, "sensivel": {"type": "string", "enum": SENSIVEL},
    "qualidade": {"type": "string", "enum": ["boa", "media", "ruim"]}}))})

_SYS_IMAGENS = """Você descreve as imagens de um dossiê de vídeo (documentário/true crime/notícia) para quem vai escrever
o roteiro. Para cada imagem [ID] devolva:
- descricao: o que aparece (pessoa, lugar, objeto, documento), época aparente;
- quem_ou_o_que: quem/o quê É, tirado da LEGENDA e do CONTEXTO (título da matéria, texto em volta). Você não reconhece
  pessoas pelo rosto: diga "provavelmente" quando vier do contexto, e vazio se não der pra saber;
- tipo: foto_real | documento | print | mapa | infografico | arte | anuncio | lixo (logo, banner, "leia também",
  foto do jornalista, ícone);
- texto_na_imagem: o texto legível (manchete, placa, documento, mensagem), resumido;
- util: serve para contar ESTE caso/tema?;
- sensivel: nao | violencia | corpo | menor | dados_pessoais (CPF, endereço, telefone…);
- qualidade: boa | media | ruim."""

_SYS_VENDA = """Você descreve as fotos e materiais de um PRODUTO para quem vai escrever o roteiro de um vídeo de venda.
Para cada imagem [ID] devolva: descricao (o ângulo: frente, lado, detalhe, em uso, embalagem, antes/depois),
quem_ou_o_que (o que a imagem prova/mostra do produto), tipo (foto_real | print | infografico | arte | anuncio | lixo),
texto_na_imagem (preço, selo, texto da embalagem), util (serve pro vídeo?), sensivel ("nao" quase sempre) e qualidade."""


# ------------------------------------------------------------------ passo A: duplicadas (de graça)
def _dhash(caminho: str) -> Optional[int]:
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            g = im.convert("L").resize((9, 8))
            px = list(g.tobytes())
        return sum(1 << i for i in range(64) if px[(i // 8) * 9 + i % 8] > px[(i // 8) * 9 + i % 8 + 1])
    except Exception:  # noqa: BLE001
        return None


def duplicadas(caminhos: Dict[str, str], limite: int = 5) -> Dict[str, str]:
    """{id: caminho} → {id_duplicada: id_original} (a mesma foto em outro tamanho/recorte leve)."""
    vistos: List[tuple] = []
    out: Dict[str, str] = {}
    for mid, cam in caminhos.items():
        h = _dhash(cam)
        if h is None:
            continue
        orig = next((o for o, hh in vistos if bin(h ^ hh).count("1") <= limite), None)
        if orig:
            out[mid] = orig
        else:
            vistos.append((mid, h))
    return out


# ------------------------------------------------------------------ passo B/D: ficha das imagens
def fichar_imagens(itens: List[Dict[str, Any]], venda: bool = False, job: Optional[str] = None,
                   recurso: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """itens = [{"id", "caminho", "contexto"}] (contexto: legenda, título/linha fina da matéria…).
    Em grupos de 10, imagens a ~640 px (vídeo = 3 momentos lado a lado). → {id: ficha}."""
    recurso = recurso or ("venda_imagens" if venda else "dossie_imagens")
    if not itens or not ia.ativo(recurso):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for k in range(0, len(itens), 10):
        grupo = itens[k:k + 10]
        conteudo: List[Dict[str, Any]] = []
        for it in grupo:
            bloco = ia.imagem_bloco(it["caminho"], largura=640)
            if not bloco:
                continue
            conteudo.append({"type": "text", "text": f"[{it['id']}] contexto: {str(it.get('contexto') or '(sem legenda)')[:600]}"})
            conteudo.append(bloco)
        if not conteudo:
            continue
        r = ia.chamar(recurso, _SYS_VENDA if venda else _SYS_IMAGENS, conteudo, SCHEMA_IMAGENS, max_tokens=4000, effort="low", job=job)
        for x in (r or {}).get("imagens") or []:
            mid = str(x.get("id") or "").strip().strip("[]").upper()
            if mid and any(it["id"].upper() == mid for it in grupo):
                out[mid] = {"descricao": str(x.get("descricao") or "")[:400], "quem_ou_o_que": str(x.get("quem_ou_o_que") or "")[:300],
                            "tipo": x.get("tipo") if x.get("tipo") in TIPOS_IMAGEM else "foto_real",
                            "texto_na_imagem": str(x.get("texto_na_imagem") or "")[:300], "epoca": str(x.get("epoca") or "")[:60],
                            "util": bool(x.get("util", True)), "sensivel": x.get("sensivel") if x.get("sensivel") in SENSIVEL else "nao",
                            "qualidade": x.get("qualidade") or "media"}
    return out


def texto_da_ficha(f: Dict[str, Any]) -> str:
    partes = [f.get("descricao")]
    if f.get("quem_ou_o_que"):
        partes.append(f["quem_ou_o_que"])
    if f.get("texto_na_imagem"):
        partes.append(f"texto na imagem: “{f['texto_na_imagem']}”")
    if f.get("sensivel") and f["sensivel"] != "nao":
        partes.append(f"⚠ sensível ({f['sensivel']})")
    return " — ".join(x for x in partes if x)


def descartar(f: Dict[str, Any]) -> bool:
    return f.get("tipo") in ("lixo", "anuncio") or not f.get("util", True)


# ------------------------------------------------------------------ passo C: PDF e dossiê condensado
SCHEMA_PDF = _obj({"paginas": _lista(_obj({"pagina": _I, "texto": _S}))})
_SYS_PDF = """Você transcreve um PDF (pode ser escaneado, com tabelas, carimbos, fotos) para texto, página por página,
para virar fonte de um roteiro. Mantenha os fatos, nomes, datas e números exatamente; tabelas viram linhas
"coluna: valor"; descreva entre colchetes fotos/plantas/carimbos importantes ([foto: …]). O número da página é o
do arquivo, começando no número informado."""

SCHEMA_CONDENSADO = _obj({
    "fatos": _lista(_obj({"data": _S, "fato": _S, "pagina": _S})),
    "pessoas": _lista(_obj({"nome": _S, "papel": _S, "paginas": _S})),
    "lugares": _lista(_obj({"nome": _S, "o_que": _S, "paginas": _S})),
    "citacoes": _lista(_obj({"texto": _S, "quem": _S, "pagina": _S})),
    "contradicoes": _lista(_obj({"entre": _S, "sobre": _S})),
    "imagens_uteis": _lista(_obj({"pagina": _S, "o_que_mostra": _S}))})
_SYS_CONDENSAR = """Você lê um documento longo (livro, processo, relatório) e monta um DOSSIÊ CONDENSADO para quem vai escrever
o roteiro de um vídeo: os fatos em ordem (com data quando houver), as pessoas e o papel de cada uma, os lugares,
as citações fortes, as contradições entre partes do documento e as páginas com imagem útil. SEMPRE com a página
de onde veio cada item (o texto marca as páginas como [pág. N]). Não invente nada que não está no texto."""


def ler_pdf(caminho: str, paginas_idx: Optional[List[int]] = None, job: Optional[str] = None,
            on_log: Callable[[str], None] = lambda _m: None) -> Optional[str]:
    """PDF lido pela IA (escaneado/tabela) em partes de 25 páginas → texto com [pág. N]. None sem IA."""
    if not ia.ativo("dossie_pdf"):
        return None
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return None
    leitor = PdfReader(caminho)
    idx = paginas_idx if paginas_idx is not None else list(range(len(leitor.pages)))
    partes: List[str] = []
    for k in range(0, len(idx), 25):
        bloco = idx[k:k + 25]
        w = PdfWriter()
        for i in bloco:
            w.add_page(leitor.pages[i])
        buf = io.BytesIO()
        w.write(buf)
        on_log(f"🤖 lendo as páginas {bloco[0] + 1}–{bloco[-1] + 1} com a IA…")
        r = ia.chamar("dossie_pdf", _SYS_PDF, [ia.pdf_bloco(buf.getvalue()),
                                               {"type": "text", "text": f"Este pedaço começa na página {bloco[0] + 1} do arquivo. Transcreva."}],
                      SCHEMA_PDF, max_tokens=16000, effort="medium", pensar=False, job=job)
        for pg in (r or {}).get("paginas") or []:
            t = str(pg.get("texto") or "").strip()
            if t:
                partes.append(f"[pág. {pg.get('pagina')}] {t}")
    return "\n\n".join(partes) or None


def condensar(texto: str, titulo: str = "", job: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Arquivo grande → dossiê condensado (lido em partes de ~60 mil caracteres, juntado no fim)."""
    if not texto or not ia.ativo("dossie_pdf"):
        return None
    total: Dict[str, List[Any]] = {k: [] for k in SCHEMA_CONDENSADO["properties"]}
    for k in range(0, len(texto), 60000):
        r = ia.chamar("dossie_pdf", _SYS_CONDENSAR, f"Documento: {titulo}\n\n" + texto[k:k + 60000], SCHEMA_CONDENSADO,
                      max_tokens=12000, effort="medium", job=job)
        if not r:
            continue
        for chave in total:
            total[chave] += (r.get(chave) or [])
    return total if any(total.values()) else None


def condensado_para_prompt(c: Dict[str, Any]) -> str:
    L = []
    if c.get("fatos"):
        L.append("Fatos (em ordem):")
        L += [f"- {('[' + f['data'] + '] ') if f.get('data') else ''}{f.get('fato')} (pág. {f.get('pagina')})" for f in c["fatos"][:400]]
    if c.get("pessoas"):
        L.append("Pessoas: " + "; ".join(f"{p.get('nome')} — {p.get('papel')} (pág. {p.get('paginas')})" for p in c["pessoas"][:120]))
    if c.get("lugares"):
        L.append("Lugares: " + "; ".join(f"{x.get('nome')} — {x.get('o_que')} (pág. {x.get('paginas')})" for x in c["lugares"][:80]))
    if c.get("citacoes"):
        L.append("Citações:")
        L += [f"- “{q.get('texto')}” — {q.get('quem')} (pág. {q.get('pagina')})" for q in c["citacoes"][:60]]
    if c.get("contradicoes"):
        L.append("Contradições: " + "; ".join(f"{x.get('entre')}: {x.get('sobre')}" for x in c["contradicoes"][:30]))
    return "\n".join(L)


# ------------------------------------------------------------------ passo E: conferir as marcas
SCHEMA_MARCAS = _obj({"problemas": _lista(_obj({"marca": _S, "frase": _S, "motivo": _S, "sugestao": _S}))})
_SYS_MARCAS = """Você confere um roteiro em que cada marca [I3] diz qual imagem aparece na frase seguinte. Para cada marca vem a
frase e a ficha da imagem. Aponte SÓ as que não combinam (ex.: a foto da vítima numa frase sobre o suspeito, um
mapa numa frase sobre uma pessoa) e sugira a marca de outra imagem do dossiê que combina (ou vazio)."""


def conferir_marcas(roteiro: str, fichas: Dict[str, str], job: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """fichas = {"I3": "o que é a imagem"}. → [{"marca", "frase", "motivo", "sugestao"}] (lista vazia = tudo certo)."""
    if not roteiro or not fichas or not ia.ativo("dossie_marcas"):
        return None
    usos = []
    for m in re.finditer(r"\[(I\d+)\]\s*([^\[]{0,300})", roteiro):
        mid = m.group(1).upper()
        usos.append(f"[{mid}] frase: {m.group(2).strip()[:250]} | imagem: {fichas.get(mid, '(não existe no dossiê)')[:250]}")
    if not usos:
        return []
    catalogo = "\n".join(f"{k}: {v[:160]}" for k, v in list(fichas.items())[:300])
    r = ia.chamar("dossie_marcas", _SYS_MARCAS + "\n\n## IMAGENS DO DOSSIÊ\n" + catalogo, "## MARCAS NO ROTEIRO\n" + "\n".join(usos[:400]),
                  SCHEMA_MARCAS, max_tokens=4000, effort="low", job=job)
    if r is None:
        return None
    return [{"marca": str(x.get("marca") or "")[:10], "frase": str(x.get("frase") or "")[:300], "motivo": str(x.get("motivo") or "")[:300],
             "sugestao": str(x.get("sugestao") or "")[:10]} for x in r.get("problemas") or []]
