"""
revisao_diretor.py — 🎬 Revisão do diretor (v84_92)
=====================================================

Depois das prévias, o "diretor" passa pela timeline e aponta o que NÃO combina — e resolve:

  1. Problemas automáticos (sem IA, de graça), pela miniatura e pelos dados da prévia:
       sem_previa · formato (em pé num vídeo deitado, ou o contrário) · desenho (3D/vetor/recorte num vídeo de imagens
       reais) · nota_baixa (o juiz deu < 5 ou a prévia veio com ⚠) · repetida (a mesma mídia em outro trecho).
  2. Com a 🤖 IA (recurso "revisao"): ela OLHA a miniatura de cada trecho junto com a fala de antes, a do trecho e a de
     depois (e a ficha do vídeo) e decide uma ação:
       manter  — está bom;
       busca   — buscas novas + o buscador com MAIS chance de achar (banco de vídeo, buscador de imagem, Wikipedia,
                 YouTube — só os marcados no vídeo);
       grafico — a fala cita números/comparação: um 📊 gráfico NATIVO do editor (dados só da fala) sobre um fundo;
       cartao  — ideia abstrata sem imagem real que sirva: 🃏 cartão de texto (fundo + a frase);
       manual  — é específico demais pra qualquer buscador: 🔎 "procure na mão" (diz o quê).
  Sem IA, os trechos com problema ganham "busca" (as reservas que o trecho já tem) ou "manual".

O Estúdio mostra a lista, você marca o que aplicar; as buscas novas são CONFERIDAS (prévia nova, pulando desenho e
formato errado) e o que mesmo assim não achar vira 🔎 "procurar na mão" — marcado na timeline.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

ACOES = ("manter", "busca", "grafico", "cartao", "manual")
LOTE = 8
ROTULOS_PROBLEMA = {
    "sem_previa": "sem prévia", "formato": "formato errado (em pé num vídeo deitado, ou o contrário)",
    "desenho": "desenho/3D/recorte num vídeo de imagens reais", "nota_baixa": "nota baixa do juiz / com ⚠",
    "repetida": "a mesma mídia já aparece em outro trecho",
}
BANCOS_VIDEO = ("pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "moviepexels",
                "animepexels_online", "moviepexels_online")
BUSCADORES_FOTO = ("google", "bing", "brave", "yandex", "startpage", "wikipedia")
_PULA = ("produto", "material", "flow", "cartao")


# ------------------------------------------------------------------ o que está disponível
def disponiveis(providers: List[str]) -> Dict[str, List[str]]:
    """Os buscadores que a revisão pode sugerir (só os marcados no vídeo)."""
    p = list(providers or [])
    video = [x for x in p if x in BANCOS_VIDEO]
    foto = [x for x in p if x in BUSCADORES_FOTO] + (["pexels"] if "pexels" in p else [])
    return {"video": video, "foto": foto, "youtube": ["youtube"] if "youtube" in p else []}


def _todos(d: Dict[str, List[str]]) -> List[str]:
    return list(dict.fromkeys(d["video"] + d["foto"] + d["youtube"]))


# ------------------------------------------------------------------ trechos
def montar_trechos(segmentos: List[Dict[str, Any]], falas: List[str], previas: List[Optional[Dict[str, Any]]],
                   miniatura: Callable[[int, Dict[str, Any], Dict[str, Any]], str]) -> List[Dict[str, Any]]:
    """Os trechos do Estúdio (estado atual) + fala/antes/depois + a prévia de cada um. Os que VOCÊ escolheu (arquivo,
    link, biblioteca, YouTube cortado) e os cartões/Flow/produto ficam de fora ("pulado")."""
    out = []
    for i, s in enumerate(segmentos):
        pv = (previas[i] if i < len(previas) else None) or {}
        ov = s.get("override_source") or {}
        pulado = ""
        if ov.get("source") or (s.get("provider") in _PULA):
            pulado = "cartão" if ov.get("cartao") else ("escolhido por você" if ov.get("source") else s.get("provider"))
        elif s.get("provider") == "youtube":
            pulado = "YouTube (escolha no painel)"
        out.append({
            "i": i, "start": float(s.get("start") or 0), "end": float(s.get("end") or 0),
            "fala": falas[i] if i < len(falas) else "", "antes": falas[i - 1] if 0 < i <= len(falas) else "",
            "depois": falas[i + 1] if i + 1 < len(falas) else "",
            "provider": str(s.get("provider") or ""), "query": str(s.get("query") or ""),
            "media_type": str(s.get("media_type") or "video"), "alternativas": [str(a) for a in s.get("alternativas") or [] if a][:4],
            "thumb": miniatura(i, s, pv) if not pulado else "", "label": str(pv.get("label") or ""),
            "erro": pv.get("error") or pv.get("erro") or "", "ia_nota": pv.get("ia_nota"),
            "result_url": str(pv.get("result_url") or ""), "pulado": pulado, "flags": [],
        })
    return out


def problemas_automaticos(trechos: List[Dict[str, Any]], orientacao: Optional[str], so_real: bool = True,
                          analisar: Optional[Callable[[str], Dict[str, str]]] = None) -> None:
    """Preenche t["flags"] (sem IA). `analisar(thumb)` → {"estilo", "formato"} (estilo_imagem.analisar_url)."""
    import estilo_imagem as ei
    analisar = analisar or ei.analisar_url
    alvos = [t for t in trechos if not t["pulado"]]
    with ThreadPoolExecutor(max_workers=6) as ex:
        analises = list(ex.map(lambda t: analisar(t["thumb"]) if t["thumb"] else {"estilo": "", "formato": ""}, alvos))
    vistos: Dict[str, int] = {}
    for t, a in zip(alvos, analises):
        f = t["flags"]
        if not t["thumb"] or t["erro"]:
            f.append("sem_previa")
        if ei.formato_errado((a or {}).get("formato") or "", orientacao):
            f.append("formato")
        if so_real and (a or {}).get("estilo") and t["provider"] not in BANCOS_VIDEO[5:]:
            f.append("desenho")
        try:
            nota_baixa = t["ia_nota"] is not None and float(t["ia_nota"]) < 5
        except (TypeError, ValueError):
            nota_baixa = False
        if nota_baixa or t["label"].startswith("⚠"):
            f.append("nota_baixa")
        chave = t["result_url"] or t["thumb"]
        if chave:
            if chave in vistos:
                f.append("repetida")
            else:
                vistos[chave] = t["i"]


# ------------------------------------------------------------------ IA
_N = {"type": "number"}
_S = {"type": "string"}


def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def schema(tipos_grafico: List[str]) -> Dict[str, Any]:
    return _obj({"trechos": {"type": "array", "items": _obj({
        "n": {"type": "integer"}, "ok": {"type": "boolean"}, "problema": _S,
        "acao": {"type": "string", "enum": list(ACOES)},
        "buscas": {"type": "array", "items": _S}, "buscador": _S, "midia": {"type": "string", "enum": ["video", "foto"]},
        "grafico": _obj({"tipo": {"type": "string", "enum": tipos_grafico}, "titulo": _S, "unidade": _S,
                         "dados": {"type": "array", "items": _obj({"rotulo": _S, "valor": _N})}}),
        "frase": _S, "procurar": _S})}})


SISTEMA = """Você é o DIRETOR de um vídeo narrado. Para cada trecho você vê a MÍDIA que está na timeline (miniatura; ou
"sem prévia") e a narração: a fala de ANTES, a do TRECHO e a de DEPOIS. Diga se a mídia combina com o que está sendo
contado naquele momento da história e, se não combinar, o que fazer.

Problemas comuns: não tem nada a ver com a história (pegou uma palavra solta da frase); genérica demais; desenho, boneco
3D, ilustração vetorial ou objeto recortado em fundo liso num vídeo de imagens reais; mídia EM PÉ num vídeo deitado
(ou o contrário); a mesma imagem de outro trecho; sem prévia. Os "problemas automáticos" de cada trecho já foram medidos
— confirme olhando a imagem.

Ações (escolha UMA):
- "manter": a mídia serve.
- "busca": 2-3 buscas NOVAS, da mais específica pra mais genérica, e o "buscador" com MAIS chance de achar, só entre
  os disponíveis: pessoa, lugar, evento, objeto ou documento REAL e específico → buscadores de imagem (google, bing…)
  ou wikipedia, com "midia": "foto" e o nome próprio na busca; cena genérica, ação, ambiente, clima → bancos de vídeo
  (pexels, pixabay…), "midia": "video", busca curta em INGLÊS descrevendo a CENA (pessoas e lugares reais, nada de
  "cartoon", "3d", "vector", "illustration", "isolated"); alguém FALANDO (entrevista, discurso) → "youtube" se estiver
  disponível.
- "grafico": a fala cita NÚMEROS (valores, porcentagens, comparação, evolução, ranking) e um gráfico explica melhor que
  qualquer imagem → preencha "grafico" (tipo, título curto, unidade, dados SÓ com os números ditos na narração — nunca
  invente). O editor desenha o gráfico animado sobre um fundo.
- "cartao": ideia abstrata, conceito, citação ou virada da história sem imagem real que sirva → "frase" com até 8
  palavras (a ideia do trecho, forte o bastante pra aparecer sozinha na tela).
- "manual": específico demais pra qualquer buscador achar (print de um documento/post específico, foto particular,
  cena de um vídeo que só existe num lugar) → "procurar": o que a pessoa deve procurar e onde.
Prefira "busca"; use "grafico"/"cartao" quando eles contam melhor a história do que uma imagem de banco.
Campos que não se aplicam à ação: deixe vazios (listas vazias, textos ""). "problema": uma frase curta (vazio se ok).
Mantenha o "n" de cada trecho."""


def _linha(t: Dict[str, Any], orientacao: str) -> str:
    probs = ", ".join(ROTULOS_PROBLEMA.get(f, f) for f in t["flags"]) or "nenhum"
    return (f"[{t['n']}] {t['start']:.1f}–{t['end']:.1f}s · mídia atual: {t['provider']} “{t['query']}”"
            + (f" ({t['label'][:80]})" if t["label"] else "") + f" · problemas automáticos: {probs}\n"
            + (f"   antes: {t['antes'][:220]}\n" if t["antes"] else "")
            + f"   TRECHO: {t['fala'][:400]}\n"
            + (f"   depois: {t['depois'][:220]}" if t["depois"] else ""))


def revisar_ia(trechos: List[Dict[str, Any]], ficha: Optional[Dict[str, Any]], disp: Dict[str, List[str]],
               orientacao: str, tipos_grafico: List[str], job: Optional[str] = None,
               chamar: Optional[Callable[..., Any]] = None, imagem: Optional[Callable[[str], Any]] = None,
               progresso: Optional[Callable[[str], None]] = None, paralelo: int = 3) -> Dict[int, Dict[str, Any]]:
    """{i: decisão da IA} — vazio sem IA. Em lotes de 8 trechos (com as miniaturas), alguns ao mesmo tempo."""
    import ia_servico as ia
    chamar = chamar or ia.chamar
    imagem = imagem or (lambda u: ia.imagem_bloco(u, 320))
    alvos = [t for t in trechos if not t["pulado"]]
    for k, t in enumerate(alvos, start=1):
        t["n"] = k
    if not alvos:
        return {}
    contexto = (f"\n\n## VÍDEO\nFormato: {orientacao or '16:9'} ({'deitado' if orientacao != '9:16' else 'em pé'})."
                f"\nBuscadores disponíveis: vídeo = {', '.join(disp['video']) or 'nenhum'}; foto = {', '.join(disp['foto']) or 'nenhum'}"
                f"{'; youtube' if disp['youtube'] else ''}.\nTipos de gráfico: {', '.join(tipos_grafico)}."
                + ("\n\n## FICHA DO VÍDEO\n" + json.dumps(ficha, ensure_ascii=False)[:6000] if ficha else ""))
    lotes = [alvos[k:k + LOTE] for k in range(0, len(alvos), LOTE)]
    feitos = [0]

    def _lote(lote: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        conteudo: List[Dict[str, Any]] = []
        for t in lote:
            conteudo.append({"type": "text", "text": _linha(t, orientacao)})
            bloco = imagem(t["thumb"]) if t["thumb"] else None
            if bloco:
                conteudo.append(bloco)
            else:
                conteudo.append({"type": "text", "text": "   (sem miniatura)"})
        r = chamar("revisao", SISTEMA + contexto, conteudo, schema(tipos_grafico), max_tokens=4000, effort="low", job=job)
        feitos[0] += 1
        if progresso:
            progresso(f"🎬 diretor olhando os trechos… {min(len(alvos), feitos[0] * LOTE)}/{len(alvos)}")
        por_n = {t["n"]: t["i"] for t in lote}
        out = {}
        for x in (r or {}).get("trechos") or []:
            try:
                n = int(x.get("n"))
            except (TypeError, ValueError):
                continue
            if n in por_n:
                out[por_n[n]] = x
        return out
    res: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as ex:
        for parte in ex.map(_lote, lotes):
            res.update(parte)
    return res


# ------------------------------------------------------------------ plano
def _frase(texto: str, n: int = 8) -> str:
    p = re.sub(r"\s+", " ", str(texto or "")).strip().strip("\"“”'")
    return " ".join(p.split()[:n])


def plano(trechos: List[Dict[str, Any]], decisoes: Dict[int, Dict[str, Any]], disp: Dict[str, List[str]],
          duracao: Optional[float] = None, com_ia: bool = False) -> Dict[str, Any]:
    """A lista que o Estúdio mostra: um item por trecho com problema (ou que a IA quer mudar), validado."""
    import dp_graficos
    todos = _todos(disp)
    itens: List[Dict[str, Any]] = []
    avisos: List[str] = []
    for t in trechos:
        if t["pulado"]:
            continue
        d = decisoes.get(t["i"])
        base = {"i": t["i"], "start": t["start"], "end": t["end"], "fala": t["fala"][:300], "flags": list(t["flags"]),
                "atual": {"provider": t["provider"], "query": t["query"], "thumb": t["thumb"]}, "origem": "ia" if d else "auto"}
        if d is None:
            if not t["flags"]:
                continue
            if com_ia:  # a IA não respondeu esse trecho: fica o automático
                avisos.append(f"Trecho {t['i'] + 1}: a IA não respondeu — sugestão automática.")
            alt = [a for a in t["alternativas"] if a and a != t["query"]]
            if alt:  # sem IA: tenta as reservas que o trecho já tem
                itens.append(dict(base, acao="busca", problema=", ".join(ROTULOS_PROBLEMA[f] for f in t["flags"]),
                                  buscas=alt[:3], buscador=t["provider"], midia="foto" if t["media_type"] == "image" else "video"))
            else:
                itens.append(dict(base, acao="manual", problema=", ".join(ROTULOS_PROBLEMA[f] for f in t["flags"]),
                                  procurar=f"uma mídia pra: “{_frase(t['fala'], 18)}”"))
            continue
        acao = d.get("acao") if d.get("acao") in ACOES else "manter"
        if d.get("ok") and acao == "manter" and not t["flags"]:
            continue
        if acao == "manter":
            if t["flags"]:
                itens.append(dict(base, acao="manter", problema=str(d.get("problema") or "a IA achou que serve")[:200]))
            continue
        item = dict(base, acao=acao, problema=str(d.get("problema") or "")[:200])
        if acao == "busca":
            buscas = [str(b).strip()[:120] for b in d.get("buscas") or [] if str(b).strip()][:3]
            midia = "foto" if d.get("midia") == "foto" else "video"
            buscador = str(d.get("buscador") or "").strip().lower()
            lista = disp["foto"] if midia == "foto" else disp["video"]
            if buscador == "youtube" and disp["youtube"]:
                midia = "video"
            elif buscador not in todos or buscador not in (lista or todos):
                buscador = (lista or todos or [t["provider"]])[0]
            if not buscas:
                item.update(acao="manual", procurar=f"uma mídia pra: “{_frase(t['fala'], 18)}”")
            else:
                item.update(buscas=buscas, buscador=buscador, midia=midia)
        elif acao == "grafico":
            g = dict(d.get("grafico") or {}, start=t["start"], end=t["end"], posicao="tela_cheia", origem="revisao")
            gn = dp_graficos.normalizar(g, duracao)
            if gn:
                gn["origem"] = "revisao"
                item.update(grafico=gn)
            else:  # sem dados que dê pra desenhar: vira cartão com a ideia
                item.update(acao="cartao", frase=_frase(d.get("frase") or (d.get("grafico") or {}).get("titulo") or t["fala"]))
                avisos.append(f"Trecho {t['i'] + 1}: o gráfico veio sem dados suficientes — virou cartão.")
        if item["acao"] == "cartao":
            item["frase"] = _frase(item.get("frase") or d.get("frase") or t["fala"])
        if item["acao"] == "manual":
            item["procurar"] = str(item.get("procurar") or d.get("procurar") or f"uma mídia pra: “{_frase(t['fala'], 18)}”")[:300]
        itens.append(item)
    cont: Dict[str, int] = {}
    for it in itens:
        cont[it["acao"]] = cont.get(it["acao"], 0) + 1
    return {"itens": itens, "contagem": cont, "avisos": avisos, "com_ia": com_ia,
            "revisados": sum(1 for t in trechos if not t["pulado"]), "pulados": sum(1 for t in trechos if t["pulado"])}
