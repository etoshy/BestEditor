"""
🤖 Busca de mídia com IA (LEIA-ME "Busca de mídia com o Claude Haiku 5.5"):

  Fase 0  ficha_visual()      — lê o roteiro UMA vez: quem é quem, lugares, época, tom,
                                 glossário de duplo sentido, o que evitar sempre.
  Fase 1  buscas_melhores()   — 2-4 buscas em inglês por trecho (da específica pra genérica).
  Fase 2  julgar()            — juiz visual: nota 0-10 por miniatura, a melhor, nova busca.
  Fase 3  (no video_assembler) — nota < 5: busca de novo com a sugestão (até 2x), depois a
                                 melhor das reprovadas com ⚠.
  YouTube ordenar_youtube() / achar_momento() — 20 resultados ordenados; o momento pela legenda.
  Wikipedia desambiguar()     — "Paris" é a cidade ou a Paris Hilton?

Tudo devolve None quando a IA está desligada/sem crédito/falhou — quem chama segue igual a antes.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import ia_servico as ia

BLOCO_BUSCAS = 100


def _obj(props: Dict[str, Any], obrig: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": obrig if obrig is not None else list(props), "additionalProperties": False}


_S = {"type": "string"}
_I = {"type": "integer"}
_N = {"type": "number"}
_B = {"type": "boolean"}


def _lista(item: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": item}


# ------------------------------------------------------------------ Fase 0: ficha visual
SCHEMA_FICHA = _obj({
    "tema": _S, "epoca": _S, "tom": _S,
    "personagens": _lista(_obj({"id": _S, "nome": _S, "busca": _S, "como_aparece": _S, "tipo": _S, "epoca": _S,
                                "wikipedia_pt": _S, "wikipedia_en": _S})),
    "lugares": _lista(_obj({"id": _S, "nome": _S, "busca": _S, "evitar": _S, "wikipedia_pt": _S, "wikipedia_en": _S})),
    "glossario": _lista(_obj({"no_roteiro": _S, "significa": _S, "nunca_buscar": _lista(_S)})),
    "evitar_sempre": _lista(_S), "visual_geral": _S,
})

_SYS_FICHA = """Você prepara a FICHA VISUAL de um vídeo narrado (documentário/YouTube) para quem vai buscar as imagens.
Leia o roteiro inteiro e devolva o que importa para a IMAGEM:
- tema, época (lugar + anos) e tom;
- personagens: nome, "busca" (o nome que funciona em bancos de imagem e buscadores, não o apelido da narração),
  como aparece (idade/época/visual), tipo (pessoa, grupo, empresa, animal, obra…), época, e o título do artigo na
  Wikipedia em português e em inglês (vazio se não tiver certeza);
- lugares: nome, "busca" (em inglês, com a época quando importa, ex.: "Medellin Colombia 1980s"), o que evitar;
- glossário: palavras do roteiro com duplo sentido e o que NÃO buscar (ex.: "a queda" = derrota, nunca "waterfall");
- evitar_sempre: o que nunca deve aparecer (memes, atores de série no lugar da pessoa real, logos…);
- visual_geral: uma linha com o visual do vídeo.
Não invente: se o roteiro não diz, deixe vazio."""


def ficha_visual(roteiro: str, titulo: str = "", idioma: str = "", estilo: str = "", job: Optional[str] = None) -> Optional[Dict[str, Any]]:
    roteiro = (roteiro or "").strip()
    if not roteiro or not ia.ativo("buscas"):
        return None
    txt = (f"Título/tema: {titulo}\n" if titulo else "") + (f"Idioma: {idioma}\n" if idioma else "") \
        + (f"Estilo do canal: {estilo}\n" if estilo else "") + "\n## ROTEIRO\n" + roteiro[:60000]
    return ia.chamar("buscas", _SYS_FICHA, txt, SCHEMA_FICHA, max_tokens=8000, effort="medium", pensar=True, job=job)


def ficha_texto(ficha: Optional[Dict[str, Any]]) -> str:
    return json.dumps(ficha or {}, ensure_ascii=False)


# ------------------------------------------------------------------ Fase 1: buscas melhores
SCHEMA_BUSCAS = _obj({"trechos": _lista(_obj({"n": _I, "buscas": _lista(_S), "midia": {"type": "string", "enum": [
    "foto", "video", "youtube", "ia", "cartao"]}, "real": _B, "visual": _S, "frase_tela": _S}))})

_SYS_BUSCAS = """Você escreve as BUSCAS de mídia de cada trecho de um vídeo narrado. Use a FICHA e o ROTEIRO para saber
quem/onde/quando ("ele", "a cidade", "naquela noite" viram nomes concretos) e o glossário para não cair em duplo sentido.
Para cada trecho devolva:
- "buscas": 2 a 4 buscas em INGLÊS, da mais específica para a mais genérica; a ÚLTIMA tem que existir em qualquer
  banco de stock. Nomes próprios na grafia mais comum. Nada da lista evitar_sempre.
- "midia": foto | video | youtube (alguém falando: entrevista, discurso, declaração) | ia | cartao (trecho abstrato,
  sem imagem real que sirva);
- "real": true quando o trecho fala de uma pessoa, lugar, evento, objeto ou documento REAL e ESPECÍFICO (com nome,
  data ou caso) — banco de stock não tem isso, então vai para foto real/notícia/YouTube; false para clima, ambiente,
  ação genérica ou ideia abstrata;
- "visual": uma linha, em português, do que deveria aparecer;
- "frase_tela": a ideia do trecho em até 8 palavras, em português, forte o bastante para aparecer sozinha na tela
  (usada num cartão de texto quando nenhuma imagem serve).
Mantenha o "n" de cada trecho."""


def buscas_melhores(trechos: List[Dict[str, Any]], ficha: Optional[Dict[str, Any]], roteiro: str = "",
                    job: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """trechos: [{"n", "fala", "visual"?, "query"?}] → {n: {"buscas", "midia", "visual"}} (vazio = sem IA)."""
    if not trechos or not ia.ativo("buscas"):
        return {}
    system = _SYS_BUSCAS + "\n\n## FICHA DO VÍDEO\n" + ficha_texto(ficha) + ("\n\n## ROTEIRO\n" + roteiro[:60000] if roteiro else "")
    out: Dict[int, Dict[str, Any]] = {}
    for k in range(0, len(trechos), BLOCO_BUSCAS):
        bloco = trechos[k:k + BLOCO_BUSCAS]
        linhas = []
        for t in bloco:
            linhas.append(f"[{t['n']}] fala: {str(t.get('fala') or '')[:400]}"
                          + (f" | visual pedido: {t['visual']}" if t.get("visual") else "")
                          + (f" | busca atual: {t['query']}" if t.get("query") else ""))
        r = ia.chamar("buscas", system, "## TRECHOS\n" + "\n".join(linhas), SCHEMA_BUSCAS, max_tokens=12000, effort="low", job=job)
        for x in (r or {}).get("trechos") or []:
            try:
                n = int(x.get("n"))
            except (TypeError, ValueError):
                continue
            buscas = [str(b).strip()[:120] for b in x.get("buscas") or [] if str(b).strip()][:4]
            if buscas:
                out[n] = {"buscas": buscas, "midia": x.get("midia") or "", "visual": str(x.get("visual") or "")[:300],
                          "real": bool(x.get("real")), "frase_tela": " ".join(str(x.get("frase_tela") or "").split()[:10])}
    return out


# ------------------------------------------------------------------ Fase 2: juiz visual
PROBLEMAS = ["epoca_errada", "lugar_errado", "assunto_errado", "texto_na_imagem", "marca_dagua", "logo_de_canal",
             "meme_ou_montagem", "print_de_site", "baixa_qualidade", "repetida", "evitar_sempre"]
SCHEMA_JUIZ = _obj({
    "notas": _lista(_obj({"n": _I, "nota": _I, "motivo": _S, "problemas": _lista({"type": "string", "enum": PROBLEMAS})})),
    "melhor": _I, "nova_busca": _S})

_SYS_JUIZ = """Você escolhe a imagem de fundo de UM trecho de um vídeo narrado. Use a FICHA para saber
quem/onde/quando. Dê nota 0-10 a cada candidato:
10 mostra exatamente o assunto do trecho; 7 combina bem (assunto, época, lugar, clima);
4 genérico, só em último caso; 0 nada a ver, enganoso ou inadequado.
Tire pontos de: época/lugar errados, texto grande ou legenda na imagem, marca d'água, logo de
canal, meme, montagem, print de site, tela dividida, baixa qualidade, algo da lista "evitar_sempre".
Se a imagem parece muito com a do trecho anterior, tire 2 pontos.
Não identifique pessoas pelo rosto: julgue pelo contexto (título, legenda, cenário, época).
Quando a imagem é um vídeo, ela pode vir como 3 momentos lado a lado do mesmo vídeo.
Se todas ficarem abaixo de 5, sugira em "nova_busca" uma busca nova em inglês que tenha mais chance de achar
(senão, deixe vazio)."""


def julgar(candidatos: List[Dict[str, Any]], fala: str, ficha: Optional[Dict[str, Any]] = None, anterior: str = "",
           seguinte: str = "", visual: str = "", busca: str = "", recurso: str = "juiz", job: Optional[str] = None,
           miniatura: str = "thumbnail") -> Optional[Dict[str, Any]]:
    """Nota de cada candidato (na ordem da lista). Devolve {"notas": {i: {"nota","motivo","problemas"}},
    "ordem": [i...] (melhor primeiro), "melhor": i, "nova_busca": str} — ou None (sem IA)."""
    if not candidatos or not ia.ativo(recurso):
        return None
    lista = candidatos[:12]
    with ThreadPoolExecutor(max_workers=6) as ex:
        imgs = list(ex.map(lambda c: ia.imagem_bloco(c.get(miniatura) or c.get("thumbnail") or c.get("miniatura_url") or "")
                           if (c.get(miniatura) or c.get("thumbnail") or c.get("miniatura_url")) else None, lista))
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text":
                                       f"Trecho anterior: {anterior[:300]}\nTRECHO ATUAL: {fala[:500]}\nTrecho seguinte: {seguinte[:300]}\n"
                                       f"O que deveria aparecer: {visual or '(não informado)'}\nBusca usada: {busca}"}]
    for i, (c, im) in enumerate(zip(lista, imgs), start=1):
        conteudo.append({"type": "text", "text": f"[{i}] {str(c.get('label') or c.get('titulo') or '')[:100]}" + ("" if im else " (sem miniatura)")})
        if im:
            conteudo.append(im)
    system = _SYS_JUIZ + "\n\n## FICHA DO VÍDEO\n" + ficha_texto(ficha)
    r = ia.chamar(recurso, system, conteudo, SCHEMA_JUIZ, max_tokens=900, effort="low", job=job)
    if not isinstance(r, dict):
        return None
    notas: Dict[int, Dict[str, Any]] = {}
    for x in r.get("notas") or []:
        try:
            i = int(x.get("n")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(lista):
            notas[i] = {"nota": max(0, min(10, int(x.get("nota") or 0))), "motivo": str(x.get("motivo") or "")[:200],
                        "problemas": [p for p in x.get("problemas") or [] if p in PROBLEMAS]}
    if not notas:
        return None
    ordem = sorted(notas, key=lambda i: (-notas[i]["nota"], i)) + [i for i in range(len(lista)) if i not in notas]
    return {"notas": notas, "ordem": ordem, "melhor": ordem[0], "nova_busca": str(r.get("nova_busca") or "").strip()[:120]}


def reordenar(candidatos: List[Dict[str, Any]], j: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Os candidatos na ordem da nota, cada um com ia_nota/ia_motivo (o que não foi julgado vai no fim)."""
    if not j:
        return candidatos
    out = []
    for i in j["ordem"]:
        if i < len(candidatos):
            c = dict(candidatos[i])
            n = j["notas"].get(i)
            if n:
                c.update(ia_nota=n["nota"], ia_motivo=n["motivo"], ia_problemas=n["problemas"])
            out.append(c)
    vistos = set(j["ordem"])
    out += [c for k, c in enumerate(candidatos) if k not in vistos]
    return out


# ------------------------------------------------------------------ YouTube
SCHEMA_YT = _obj({"videos": _lista(_obj({"n": _I, "nota": _I, "motivo": _S})), "busca_melhor": _S})
_SYS_YT = """Você ordena resultados de busca do YouTube para achar o vídeo de onde cortar UM trecho de um documentário.
Dê nota 0-10 a cada vídeo pelo título, canal, duração e descrição, pensando no que a narração pede:
- prefira canal oficial, de notícia, o vídeo ORIGINAL (entrevista, discurso, coletiva, reportagem);
- tire pontos de react/reação, compilation, edit, meme, AMV, Shorts, reupload, "fan made", lyric video;
- a duração precisa ser compatível (um vídeo de 15 s raramente tem o momento; uma live de 6 h é difícil);
- o idioma certo para quem fala.
Em "busca_melhor" sugira uma busca do YouTube melhor (ou vazio)."""


def ordenar_youtube(resultados: List[Dict[str, Any]], fala: str, termo: str = "", ficha: Optional[Dict[str, Any]] = None,
                    job: Optional[str] = None, com_capas: int = 0, ja_vistos: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Nota de cada resultado. `com_capas`: manda também a CAPA (miniatura) dos N primeiros — a IA vê o que o vídeo mostra."""
    if not resultados or not ia.ativo("youtube_ordem"):
        return None
    linhas = [f"[{i}] {r.get('titulo', '')} | canal: {r.get('canal', '')} | duração: {r.get('duracao_formatada') or r.get('duracao_segundos') or '?'}"
              + (f" | {str(r.get('descricao') or '')[:160]}" if r.get("descricao") else "") for i, r in enumerate(resultados[:20], start=1)]
    txt = (f"O que a narração diz neste trecho: {fala[:600]}\nBusca usada: {termo}\n"
           + (f"Vídeos já conferidos que NÃO tinham o momento: {'; '.join(ja_vistos[:10])}\n" if ja_vistos else "")
           + "\n## RESULTADOS\n" + "\n".join(linhas))
    conteudo: Any = txt
    if com_capas:
        lista = resultados[:min(com_capas, 12)]
        with ThreadPoolExecutor(max_workers=6) as ex:
            imgs = list(ex.map(lambda r: ia.imagem_bloco(r["miniatura_url"]) if r.get("miniatura_url") else None, lista))
        conteudo = [{"type": "text", "text": txt + "\n\n## CAPAS (na mesma numeração)"}]
        for i, im in enumerate(imgs, start=1):
            if im:
                conteudo += [{"type": "text", "text": f"capa [{i}]"}, im]
    system = _SYS_YT + ("\n\n## FICHA DO VÍDEO\n" + ficha_texto(ficha) if ficha else "")
    r = ia.chamar("youtube_ordem", system, conteudo, SCHEMA_YT, max_tokens=1500, effort="low", job=job)
    if not isinstance(r, dict):
        return None
    notas = {}
    for x in r.get("videos") or []:
        try:
            i = int(x.get("n")) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(resultados):
            notas[i] = {"nota": max(0, min(10, int(x.get("nota") or 0))), "motivo": str(x.get("motivo") or "")[:160]}
    if not notas:
        return None
    ordem = sorted(range(len(resultados)), key=lambda i: (-(notas.get(i) or {"nota": -1})["nota"], i))
    lista = []
    for i in ordem:
        v = dict(resultados[i])
        if i in notas:
            v.update(ia_nota=notas[i]["nota"], ia_motivo=notas[i]["motivo"])
        lista.append(v)
    return {"resultados": lista, "busca_melhor": str(r.get("busca_melhor") or "")[:120]}


SCHEMA_NOVA_BUSCA = _obj({"busca": _S, "por_que": _S})
_SYS_NOVA_BUSCA = """Você procura no YouTube o vídeo de onde cortar UM trecho de um documentário. As buscas abaixo não
acharam o momento (os vídeos não falavam disso ou não tinham legenda). Sugira UMA busca nova e DIFERENTE das já feitas:
mais específica (nome completo, evento, data, lugar, "entrevista", "discurso", "coletiva", "reportagem"), no idioma em que
o vídeo original provavelmente está. Responda vazio se não houver outra busca razoável."""


def nova_busca_youtube(fala: str, feitas: List[str], motivos: List[str], ficha: Optional[Dict[str, Any]] = None,
                       job: Optional[str] = None) -> str:
    """Uma busca nova do YouTube depois das que falharam ("" se a IA não tiver outra ideia)."""
    if not ia.ativo("youtube_ordem"):
        return ""
    txt = (f"O que a narração diz: {fala[:700]}\nBuscas já feitas: " + " | ".join(feitas)
           + "\nO que aconteceu: " + "; ".join(motivos[-8:]))
    system = _SYS_NOVA_BUSCA + ("\n\n## FICHA DO VÍDEO\n" + ficha_texto(ficha) if ficha else "")
    r = ia.chamar("youtube_ordem", system, txt, SCHEMA_NOVA_BUSCA, max_tokens=400, effort="low", job=job)
    busca = str((r or {}).get("busca") or "").strip()[:120] if isinstance(r, dict) else ""
    return "" if busca.lower() in {f.lower() for f in feitas} else busca


SCHEMA_MOMENTO = _obj({"achou": _B, "inicio": _N, "fim": _N, "frase": _S, "traducao": _S, "confianca": _N,
                       "outros_momentos": _lista(_obj({"inicio": _N, "fim": _N, "frase": _S}))})
_SYS_MOMENTO = """Você acha, na LEGENDA de um vídeo do YouTube (com os tempos), o momento que corresponde ao que a
narração de um documentário diz. Devolva início e fim em segundos (o trecho exato da fala, 3-20 s), a frase dita,
a tradução se for outro idioma, a confiança (0-1) e outros momentos possíveis. Se o vídeo não fala disso,
"achou": false. A legenda não diz quem fala: confirme pelo contexto (título, canal) e não chute."""


def _janelas(linhas: List[Dict[str, Any]], fala: str, ficha: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Vídeo longo: só as janelas de ~3 min em volta das palavras-chave (achadas aqui, de graça)."""
    texto_total = sum(len(l.get("texto") or "") for l in linhas)
    if texto_total < 40000:
        return linhas
    chaves = {w.lower() for w in re.findall(r"\w{5,}", fala or "")}
    for p in (ficha or {}).get("personagens") or []:
        chaves |= {w.lower() for w in re.findall(r"\w{4,}", p.get("nome") or "")}
    tempos = [l["inicio"] for l in linhas if chaves & {w.lower() for w in re.findall(r"\w{4,}", l.get("texto") or "")}]
    if not tempos:
        return linhas[:600]
    sel = [l for l in linhas if any(abs(l["inicio"] - t) <= 90 for t in tempos[:40])]
    return sel[:1500]


def achar_momento(linhas: List[Dict[str, Any]], fala: str, titulo: str = "", canal: str = "", duracao_alvo: Optional[float] = None,
                  ficha: Optional[Dict[str, Any]] = None, job: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """linhas = [{"inicio","fim","texto"}] (a legenda). Devolve {achou, inicio, fim, frase, traducao, confianca, outros_momentos}."""
    if not linhas or not ia.ativo("youtube_momento"):
        return None

    def mmss(s):
        s = int(s)
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    leg = "\n".join(f"[{mmss(l['inicio'])} = {l['inicio']:.1f}s] {l['texto']}" for l in _janelas(linhas, fala, ficha))
    txt = (f"Vídeo: {titulo} | canal: {canal}\nO que a narração diz: {fala[:800]}\n"
           + (f"Duração desejada do corte: ~{duracao_alvo:.1f}s\n" if duracao_alvo else "") + "\n## LEGENDA\n" + leg)
    system = _SYS_MOMENTO + ("\n\n## FICHA DO VÍDEO\n" + ficha_texto(ficha) if ficha else "")
    r = ia.chamar("youtube_momento", system, txt, SCHEMA_MOMENTO, max_tokens=1200, effort="medium", job=job)
    if not isinstance(r, dict):
        return None
    try:
        ini, fim = float(r.get("inicio") or 0), float(r.get("fim") or 0)
    except (TypeError, ValueError):
        return None
    if r.get("achou") and fim > ini:
        ini, fim = max(0.0, ini - 0.4), fim + 0.4  # a legenda automática atrasa: folga
    return {"achou": bool(r.get("achou")) and fim > ini, "inicio": round(ini, 2), "fim": round(fim, 2),
            "frase": str(r.get("frase") or "")[:400], "traducao": str(r.get("traducao") or "")[:400],
            "confianca": float(r.get("confianca") or 0), "outros_momentos": (r.get("outros_momentos") or [])[:4]}


# ------------------------------------------------------------------ Wikipedia
SCHEMA_WIKI = _obj({"escolhas": _lista(_obj({"nome": _S, "titulo": _S, "motivo": _S}))})
_SYS_WIKI = """Você escolhe o artigo CERTO da Wikipedia para cada nome citado num roteiro (ex.: "Paris" pode ser a cidade
ou a Paris Hilton). Para cada dúvida vem o contexto e os candidatos (título + descrição). Devolva o título exato
de um candidato, ou "nenhum" se nenhum serve."""


def desambiguar(duvidas: List[Dict[str, Any]], ficha: Optional[Dict[str, Any]] = None, roteiro: str = "",
                job: Optional[str] = None) -> Dict[str, str]:
    """duvidas = [{"nome", "contexto", "candidatos": [{"titulo","descricao"}]}] → {nome: título | ""}."""
    if not duvidas or not ia.ativo("wikipedia"):
        return {}
    linhas = []
    for d in duvidas[:60]:
        cands = "; ".join(f"“{c.get('titulo')}” — {str(c.get('descricao') or '')[:120]}" for c in (d.get("candidatos") or [])[:5])
        linhas.append(f"- {d['nome']} (contexto: {str(d.get('contexto') or '')[:200]}): {cands}")
    system = _SYS_WIKI + ("\n\n## FICHA DO VÍDEO\n" + ficha_texto(ficha) if ficha else "") + ("\n\n## ROTEIRO\n" + roteiro[:20000] if roteiro else "")
    r = ia.chamar("wikipedia", system, "## DÚVIDAS\n" + "\n".join(linhas), SCHEMA_WIKI, max_tokens=2000, effort="low", job=job)
    out = {}
    for x in (r or {}).get("escolhas") or []:
        t = str(x.get("titulo") or "").strip()
        out[str(x.get("nome") or "")] = "" if t.lower() in ("nenhum", "none", "") else t
    return out
