"""
cenas_lote.py — 🏭 Produção no pod: da narração transcrita às cenas do projeto (v84_122)
=========================================================================================

1. `cortar_cenas`  — corta a narração em cenas de ~N s (entre 0,6× e 1,4×) pelo tempo de cada palavra (Whisper), sem cortar palavra e
                     preferindo pontuação/pausa. As cenas cobrem o áudio inteiro, sem buraco.
2. `descrever`     — 🤖 a IA do site (recurso "producao_pod") descreve cada cena: o que aparece, a busca em inglês pros
                     bancos, a NOTA DE DIFICULDADE (0–10: quão difícil é achar isso em banco/web) e o prompt de imagem
                     pro Z-Image. Sem IA: regra simples (aviso na tela).
3. `escolher`      — quais cenas o pod gera: as ~30% mais difíceis, BEM ESPAÇADAS (nunca duas seguidas e no máximo
                     ⌈pct·10⌉+1 em qualquer janela de 10 cenas).
4. `montar_json`   — o JSON no formato do site ("segments"), que entra pelo mesmo caminho do "colar JSON":
                       • cena do pod → provider "runpod", media_type "image", query = o prompt de imagem;
                       • as outras  → provider "adiado" (⏳ pendente): sem prévia agora; no editor, "Completar cenas
                         pendentes" escolhe as fontes e a IA escreve as buscas (ver app.completar_pendentes).
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Set

PROVIDER_ADIADO = "adiado"
BLOCO_IA = 20  # v84_142: blocos menores = prompt melhor em cada cena (eram 60)
PARALELO_IA = 3
_FIM_FRASE = re.compile(r"[.!?…;:,]$")


# ------------------------------------------------------------------ 1. cenas
def _palavras(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for sg in segments or []:
        ws = sg.get("words") or []
        if ws:
            out += [{"word": str(w.get("word") or "").strip(), "start": float(w["start"]), "end": float(w["end"])}
                    for w in ws if str(w.get("word") or "").strip()]
        else:  # sem tempo por palavra: espalha as palavras do bloco no tempo dele
            toks = str(sg.get("text") or "").split()
            a, b = float(sg["start"]), float(sg["end"])
            passo = (b - a) / max(1, len(toks))
            out += [{"word": t, "start": a + i * passo, "end": a + (i + 1) * passo} for i, t in enumerate(toks)]
    return out


def cortar_cenas(segments: List[Dict[str, Any]], intervalo: float = 5.0, total: Optional[float] = None) -> List[Dict[str, Any]]:
    """[{start, end, fala}] cobrindo 0 → total, cada uma com ~`intervalo` s (entre 0,6× e 1,4×)."""
    ws = _palavras(segments)
    if not ws:
        return []
    total = float(total if total is not None else max(float(segments[-1]["end"]), ws[-1]["end"]))
    intervalo = max(1.5, float(intervalo or 5.0))
    minimo, maximo = intervalo * 0.6, intervalo * 1.4
    cortes: List[float] = []
    inicio, ultimo_bom = 0.0, None
    for i, w in enumerate(ws[:-1]):
        prox = ws[i + 1]
        fim_aqui = (w["end"] + prox["start"]) / 2
        dur = fim_aqui - inicio
        pausa = prox["start"] - w["end"]
        bom = bool(_FIM_FRASE.search(w["word"])) or pausa >= 0.25
        if dur >= minimo and bom:
            ultimo_bom = fim_aqui
        if dur >= intervalo and bom:
            cortes.append(fim_aqui)
            inicio, ultimo_bom = fim_aqui, None
        elif dur >= maximo:
            corte = ultimo_bom if ultimo_bom and ultimo_bom - inicio >= minimo else fim_aqui
            cortes.append(corte)
            inicio, ultimo_bom = corte, None
    if cortes and total - cortes[-1] < minimo * 0.5:  # sobra minúscula no fim: junta com a última
        cortes.pop()
    limites = [0.0] + cortes + [total]
    cenas = []
    for a, b in zip(limites, limites[1:]):
        fala = " ".join(w["word"] for w in ws if w["start"] >= a - 0.01 and w["start"] < b)
        cenas.append({"start": round(a, 3), "end": round(b, 3), "fala": fala.strip()})
    return cenas


# ------------------------------------------------------------------ 2. descrever (IA)
def _schema(com_elenco: bool = False, setas: bool = False):
    from ia_midia import _I, _S, _lista, _obj
    cena = {"n": _I, "visual": _S, "busca": _S, "dificil": _I, "prompt_imagem": _S, "ano": _I}
    if setas:
        cena["esquema"] = {"type": "boolean"}
    if com_elenco:
        cena.update(pessoas=_lista(_obj({"nome": _S, "idade": _I})), lugar=_S)
    return _obj({"cenas": _lista(_obj(cena))})


SEM_TEXTO = ("A single realistic scene, not a diagram, not an infographic, not a chart; no text, no letters, no numbers, "
             "no labels, no arrows.")
# 🖼 v84_199: canal com "texto_na_imagem": "setas_numeros" no pacote (o do espaço) — esquema só com setas/formas/números
SEM_TEXTO_SETAS = ("No words and no letters anywhere in the image (no labels, no captions, no titles); if it explains something, "
                   "use only clean arrows, shapes and at most a few large digits.")
REGRA_EXPLICACAO = """Explicação, conceito ou processo (camadas, etapas, comparação de tamanhos, linha do tempo)
  NUNCA vira diagrama, infográfico, gráfico, esquema com setas/rótulos/números, ícones lado a lado ou fundo branco:
  mostre UMA cena realista do fenômeno como seria vista de verdade, sem rótulos."""
REGRA_EXPLICACAO_SETAS = """Explicação, conceito ou processo (camadas de uma estrela, etapas, comparação de tamanhos,
  linha do tempo): de preferência UMA cena realista do fenômeno como seria vista de verdade (ex.: "a huge glowing red
  supergiant star in deep space, turbulent surface, Hubble-style astrophotography"); quando precisar mostrar
  etapas/comparação, pode ser um esquema visual limpo SÓ com formas, SETAS e no máximo NÚMEROS grandes (1, 2, 3, 10×) —
  NUNCA palavras, nomes, rótulos ou legendas (o gerador escreve tudo errado; o texto entra na edição). Fundo escuro,
  nunca branco. Esquema é EXCEÇÃO (só onde a fala explica etapas/comparação — poucas cenas no vídeo todo): marque
  "esquema": true SÓ nelas; em todas as outras "esquema": false e o prompt não fala em setas nem números."""

_SYS = """Você planeja as IMAGENS de um vídeo narrado de YouTube, cena por cena (cada cena tem uns segundos de fala).
Use a FICHA (quem é quem, lugares, época, estilo) e o ROTEIRO para entender do que cada fala trata de verdade
("ele", "a cidade", "naquela noite" viram coisas concretas). Para CADA cena devolva:
- "visual": uma linha, em português, do que deve aparecer na tela;
- "busca": a busca em INGLÊS, 2 a 6 palavras, que acharia isso num banco de vídeo/foto de stock (cena real e filmável);
- "dificil": 0 a 10 — quão DIFÍCIL é achar essa imagem pronta em banco de stock ou na web:
    0-2 ambiente/ação genérica (cidade, gente andando, dinheiro, mar, escritório);
    3-5 algo específico mas comum (um tipo de lugar, objeto ou época que bancos costumam ter);
    6-8 muito específico (um momento histórico sem foto, um lugar exato numa época, uma ação rara, um objeto único);
    9-10 só existe gerando: SIMULAÇÃO ou RECONSTRUÇÃO (processo científico, dentro do corpo, espaço, catástrofe,
         cena hipotética, "como seria se…", acontecimento antigo sem registro visual).
  Pessoa real FAMOSA falando/aparecendo não é difícil para IA: é caso de foto real (nota 3-5), não de gerar.
- "prompt_imagem": em INGLÊS, 40 a 80 palavras, para o gerador Z-Image Turbo: assunto principal primeiro, depois ação,
  cenário, época, roupas/materiais, luz, enquadramento e lente, e o estilo da ficha (vídeo de imagens REAIS =
  "photorealistic documentary photograph"; ilustração só se a ficha disser). Nada de texto, letreiro ou legenda na
  imagem. {REGRA_EXPLICACAO} Nunca o NOME de uma pessoa real (descreva: idade, roupa, época). Coerência com as cenas vizinhas.
- "ano": o ano em que a cena SE PASSA na história (não o de hoje), pela cronologia do roteiro; 0 se não é um momento
  datado (explicação genérica, conceito). Carros, roupas, objetos e tecnologia do prompt são DESSE ano.
Mantenha o "n" de cada cena."""


def descrever(cenas: List[Dict[str, Any]], roteiro: str = "", idioma: str = "", ficha: Optional[Dict[str, Any]] = None,
              job: Optional[str] = None, on_passo=None, elenco: Optional[Dict[str, Any]] = None,
              setas: bool = False) -> Dict[int, Dict[str, Any]]:
    """{n (1-based): {visual, busca, dificil, prompt_imagem, pessoas?, ano?}} — vazio sem IA (ou se ela falhar).
    Com `elenco` (🎭 pessoas reais com foto): diz quem aparece em cada cena e com que IDADE naquele momento."""
    import ia_servico as ia
    if not cenas or not ia.ativo("producao_pod"):
        return {}
    import json
    import elenco as _el
    bloco_el = _el.bloco_para_cenas(elenco or {})
    nomes_el = {x["nome"].lower(): x["nome"] for x in (elenco or {}).get("pessoas") or [] if x.get("usar", True)}
    locais_el = {x["nome"].lower(): x["nome"] for x in (elenco or {}).get("locais") or [] if x.get("usar", True)}
    system = _SYS.replace("{REGRA_EXPLICACAO}", REGRA_EXPLICACAO_SETAS if setas else REGRA_EXPLICACAO) + ("\n\n" + _el.REGRA_CENAS + "\n\n" + bloco_el if bloco_el else "") \
        + "\n\n## FICHA DO VÍDEO\n" + json.dumps(ficha or {}, ensure_ascii=False) \
        + (f"\n\nIdioma da narração: {idioma}" if idioma else "") + ("\n\n## ROTEIRO\n" + roteiro[:60000] if roteiro else "")
    out: Dict[int, Dict[str, Any]] = {}

    def linha(j: int) -> str:
        c = cenas[j]
        antes = cenas[j - 1]["fala"][-160:] if j else ""
        depois = cenas[j + 1]["fala"][:160] if j + 1 < len(cenas) else ""
        return (f"[{j + 1}] ({c['end'] - c['start']:.1f}s)" + (f" antes: {antes} |" if antes else "")
                + f" FALA: {c['fala'][:400]}" + (f" | depois: {depois}" if depois else ""))

    def bloco(idx: List[int]) -> Dict[int, Dict[str, Any]]:
        """Uma chamada pra IA com ~20 cenas (o roteiro, a ficha e o elenco vão no começo, guardados em cache)."""
        r = ia.chamar("producao_pod", system, "## CENAS\n" + "\n".join(linha(j) for j in idx), _schema(bool(bloco_el), setas),
                      max_tokens=12000, effort="low", job=job, timeout=300)
        res: Dict[int, Dict[str, Any]] = {}
        for x in (r or {}).get("cenas") or []:
            try:
                n = int(x.get("n"))
            except (TypeError, ValueError):
                continue
            if n - 1 not in idx:
                continue
            d = {"visual": " ".join(str(x.get("visual") or "").split())[:300],
                 "busca": " ".join(str(x.get("busca") or "").split())[:120],
                 "dificil": max(0, min(10, int(x.get("dificil") or 0))),
                 "prompt_imagem": " ".join(str(x.get("prompt_imagem") or "").split())[:1200],
                 "ano": max(0, min(2100, int(x.get("ano") or 0))),
                 "esquema": bool(setas and x.get("esquema"))}
            if bloco_el:
                ps = []
                for pc in x.get("pessoas") or []:
                    nome = nomes_el.get(str((pc or {}).get("nome") or "").strip().lower())
                    if nome and not any(q["nome"] == nome for q in ps):
                        ps.append({"nome": nome, "idade": max(0, min(110, int(pc.get("idade") or 0)))})
                d["pessoas"] = ps[:3]
                d["lugar"] = locais_el.get(str(x.get("lugar") or "").strip().lower(), "")
            if d["prompt_imagem"]:
                res[n] = d
        return res

    from concurrent.futures import ThreadPoolExecutor, as_completed
    todos = list(range(len(cenas)))
    for tentativa in (1, 2):  # 2ª volta: só as cenas que ficaram sem resposta (bloco que falhou ou veio incompleto)
        faltam = [j for j in todos if j + 1 not in out]
        if not faltam:
            break
        blocos = [faltam[k:k + BLOCO_IA] for k in range(0, len(faltam), BLOCO_IA)]
        feitos = 0
        with ThreadPoolExecutor(max_workers=PARALELO_IA) as ex:
            futuros = [ex.submit(bloco, b) for b in blocos]
            for f in as_completed(futuros):
                try:
                    out.update(f.result())
                except Exception:  # noqa: BLE001 — esse bloco vai de novo na 2ª volta
                    pass
                feitos += 1
                if on_passo:
                    on_passo(f"🤖 {'refazendo as que faltaram: ' if tentativa == 2 else ''}descrevendo as cenas — "
                             f"bloco {feitos}/{len(blocos)} · {len(out)} de {len(cenas)} cenas prontas")
    return out


# ------------------------------------------------------------------ 3. escolher (espaçadas)
def escolher(notas: List[int], pct: float = 0.30, nota_minima: Optional[int] = None) -> Set[int]:
    """Índices (0-based) das cenas que o pod gera: as de nota mais alta, ~pct do total, espalhadas (no máximo
    ⌈pct·10⌉+1 em qualquer janela de 10 cenas). Nota < 0 = nunca (ex.: cena com foto real do modelo).
    Até 45%: nunca duas vizinhas e só cena com nota ≥ 3. Acima (v84_140, até 90%): primeiro espalhadas, depois
    completa permitindo vizinhas, e entra cena mais fácil (nota ≥ 1 até 60%; qualquer uma acima disso)."""
    n = len(notas)
    pct = max(0.0, min(1.0, pct))
    alvo = int(round(n * pct))
    if not alvo:
        return set()
    if nota_minima is None:
        nota_minima = 3 if pct <= 0.45 else (1 if pct <= 0.6 else 0)
    teto_janela = math.ceil(pct * 10) + 1
    ordem = sorted(range(n), key=lambda i: (-notas[i], i))
    escolhidas: Set[int] = set()
    for passe in (1, 2):
        for i in ordem:
            if len(escolhidas) >= alvo:
                break
            if i in escolhidas or notas[i] < 0 or notas[i] < nota_minima:
                continue
            if passe == 1 and ((i - 1) in escolhidas or (i + 1) in escolhidas):
                continue
            if teto_janela < 10 and any(sum(1 for j in range(a, a + 10) if j in escolhidas or j == i) > teto_janela
                                        for a in range(max(0, i - 9), min(i, n - 1) + 1)):
                continue
            escolhidas.add(i)
        if pct <= 0.45:
            break
    return escolhidas


def escolher_sem_ia(n: int, pct: float = 0.30) -> Set[int]:
    """Sem IA (não dá pra saber quais são difíceis): espalha por igual."""
    alvo = int(round(n * max(0.0, min(1.0, pct))))
    if not alvo:
        return set()
    passo = n / alvo
    return {min(n - 1, int(passo * k + passo / 2)) for k in range(alvo)}


# ------------------------------------------------------------------ 4. JSON do site
def look_da_epoca(ano: int) -> str:
    """🎞 O "jeito de foto" do ano da cena — o vídeo parece feito com as câmeras daquela época."""
    if not ano or ano < 1850:
        return ""
    if ano < 1900:
        t = "19th-century albumen photograph look, sepia, soft focus, long exposure"
    elif ano < 1940:
        t = f"{ano // 10 * 10}s black and white photograph, silver gelatin print look, film grain"
    elif ano < 1960:
        t = f"{ano // 10 * 10}s black and white 35mm film photograph, high contrast, grain"
    elif ano < 1970:
        t = "1960s color slide film photograph, Kodachrome colors, slight vignette"
    elif ano < 1980:
        t = "1970s 35mm color film photograph, warm faded colors, soft grain"
    elif ano < 1990:
        t = "1980s color film snapshot, direct flash, saturated colors, grain"
    elif ano < 2003:
        t = "1990s consumer 35mm film photo, slightly washed colors"
    elif ano < 2012:
        t = "2000s early digital camera photo"
    else:
        t = "modern digital photograph"
    return f"{t}; period-accurate cars, clothing, hairstyles, objects and signs of {ano}"


def montar_json(cenas: List[Dict[str, Any]], info: Dict[int, Dict[str, Any]], escolhidas: Set[int],
                estilo_extra: str = "", materiais: Optional[Dict[int, Dict[str, str]]] = None,
                epoca: bool = False, setas: bool = False) -> Dict[str, Any]:
    """materiais = {índice da cena: {"id": "I3", "tipo": "foto"|"video", "provider": "material"}} (fotos do modelo)."""
    segs = []
    for i, c in enumerate(cenas):
        d = info.get(i + 1) or {}
        visual = d.get("visual") or c["fala"][:200]
        busca = d.get("busca") or " ".join(c["fala"].split()[:8]) or "cinematic background"
        if materiais and i in materiais:
            m = materiais[i]
            segs.append({"start": c["start"], "end": c["end"], "provider": m.get("provider") or "material", "query": m["id"],
                         "visual": visual, "media_type": "video"})  # o site troca pelo arquivo (foto ou vídeo) ao ler o JSON
        elif i in escolhidas:
            prompt = d.get("prompt_imagem") or (
                f"{c['fala']}. Photorealistic documentary photograph, natural light, sharp focus, clean frame without text")
            if epoca and d.get("ano"):
                prompt = f"{prompt.rstrip('. ')}. {look_da_epoca(d['ano'])}"
            # 🖼 v84_196: o gerador escreve rótulos tortos em qualquer "diagrama" — sempre uma cena real, sem texto
            # setas/números SÓ na cena marcada como esquema (falar disso no prompt de toda cena fazia o gerador pôr
            # setas e números em todas)
            prompt = f"{prompt.rstrip('. ')}. {SEM_TEXTO_SETAS if setas and d.get('esquema') else SEM_TEXTO}"
            if estilo_extra:
                prompt = f"{prompt.rstrip('. ')}. {estilo_extra.strip()}"
            segs.append({"start": c["start"], "end": c["end"], "provider": "runpod", "media_type": "image",
                         "query": prompt, "visual": visual})
        else:
            segs.append({"start": c["start"], "end": c["end"], "provider": PROVIDER_ADIADO, "query": busca,
                         "visual": visual, "media_type": "video"})
    return {"segments": segs}


def ajustar_tempos(resposta: Dict[str, Any], total: float, minimo: float = 0.35) -> Dict[str, Any]:
    """Deixa as cenas do jeito que o site exige: começa em 0, sem buraco/sobreposição, termina no fim exato do áudio,
    nenhuma cena curta demais e nenhuma busca vazia. (A legenda costuma começar depois de 0 e acabar antes do fim
    do áudio — e o site recusa o JSON por causa disso.)"""
    segs = [dict(s) for s in resposta.get("segments") or [] if isinstance(s, dict)]
    segs.sort(key=lambda s: float(s.get("start") or 0))
    total = float(total or 0)
    if total > 0:
        segs = [s for s in segs if float(s.get("start") or 0) < total - minimo] or segs[:1]
    for k, s in enumerate(segs):
        s["start"] = 0.0 if k == 0 else segs[k - 1]["end"]
        fim = float(segs[k + 1]["start"]) if k + 1 < len(segs) else (total or float(s.get("end") or 0))
        s["end"] = round(max(fim, s["start"]), 3)
        if not str(s.get("query") or "").strip():
            s["query"] = str(s.get("visual") or "").strip()[:200] or "cinematic background"
    # junta as cenas curtas demais na vizinha (a da direita, ou a de antes se for a última)
    k = 0
    while k < len(segs) and len(segs) > 1:
        if segs[k]["end"] - segs[k]["start"] >= minimo:
            k += 1
            continue
        if k + 1 < len(segs):
            segs[k + 1]["start"] = segs[k]["start"]
        else:
            segs[k - 1]["end"] = segs[k]["end"]
        segs.pop(k)
    if segs and total > 0:
        segs[-1]["end"] = round(total, 3)
    out = dict(resposta)
    out["segments"] = segs
    return out


def _toks(t: str) -> List[str]:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", str(t or "").lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[^\W_]+", t)


def cenas_dos_momentos(cenas: List[Dict[str, Any]], momentos: List[Dict[str, Any]]) -> Dict[int, str]:
    """🕵️ Em que cena cai cada marca [I3] do roteiro do modelo de vídeo (pelo "trecho" — a frase que vem depois da
    marca — achado na fala das cenas). → {índice da cena: "I3"}. Uma imagem por cena; na ordem do roteiro."""
    palavras, dona = [], []
    for i, c in enumerate(cenas):
        for w in _toks(c.get("fala")):
            palavras.append(w)
            dona.append(i)
    out: Dict[int, str] = {}
    pos = 0
    for mo in momentos or []:
        alvo = _toks(mo.get("trecho"))[:6]
        mid = str(mo.get("midia") or "").upper()
        if len(alvo) < 3 or not mid:
            continue
        achou = None
        for ini in list(range(pos, len(palavras))) + list(range(0, pos)):  # procura pra frente; senão, do começo
            janela = palavras[ini:ini + len(alvo)]
            if janela and janela[0] == alvo[0] and sum(a == b for a, b in zip(janela, alvo)) >= max(3, len(alvo) - 2):
                achou = ini
                break
        if achou is None:
            continue
        cena = dona[achou]
        if cena in out and cena + 1 < len(cenas):
            cena += 1  # já tem imagem nessa cena: vai pra próxima
        if cena not in out:
            out[cena] = mid
        pos = achou + 1
    return out


def resumo(cenas: List[Dict[str, Any]], escolhidas: Set[int]) -> Dict[str, Any]:
    return {"cenas": len(cenas), "no_pod": len(escolhidas), "pendentes": len(cenas) - len(escolhidas),
            "pct": round(100 * len(escolhidas) / max(1, len(cenas)))}
