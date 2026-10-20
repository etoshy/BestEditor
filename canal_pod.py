"""
canal_pod.py — 🎨 o pacote do canal manda na 🏭 Produção no pod (v84_181)
===========================================================================

O .zip do canal (marcas/<slug>/: brand_guide.json, personagens.json, reforcos.json, referências, pacote.json) passa a
valer nas imagens do pod — o mesmo motor da aba 🎨 Identidade visual (marca_visual.py):

  • % de cenas no pod: a do pacote ("producao_pod": {"pct": 100} no pacote.json; padrão 100 em canal de pacote) —
    o campo do lote não vale pra esses roteiros;
  • estética: o prompt de cada cena é o template + style_lock do brand_guide.json (marca_visual.montar_prompt), em vez
    do "photorealistic documentary photograph" do true crime;
  • personagens (a regra do canal):
      - cena com uma PESSOA GENÉRICA (alguém, um morador, um cientista…) → essa pessoa vira o personagem do canal
        (o mascote numa pose, ou Mira/Vanta…), com a ficha dele como referência no FLUX.2 klein;
      - personagem FALANDO no trecho (as tags [mira], [vanta] do roteiro) → ele aparece reagindo/perguntando;
      - PESSOA REAL citada (elenco do 🕵️ Modelo de vídeo, com foto) → o rosto dela, sem personagem;
      - cena sem pessoa → sem personagem;
  • fotos marcadas no roteiro ([I3]) → vão de referência e saem REDESENHADAS na estética do canal (canal 100% IA);
    com "fotos_do_roteiro": "real" no pacote, entram como estão (igual ao true crime).

Mudar a estética de um canal = editar o zip (brand_guide.json / personagens.json / pacote.json) e importar de novo
em 🎨 Identidade visual. O 📦 Zip do canal leva tudo isso pra outro PC.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

PADRAO = {"pct": 100, "personagens": True, "fotos_do_roteiro": "referencia", "estilo_fotos": "", "ref_estilo": False,
          "cenas": "canal", "texto_na_imagem": ""}  # 🖼 v84_191: "padrao" = as cenas como no roteiro sem canal (foto documental de sempre)
BLOCO_IA = 20
PARALELO_IA = 3


# ------------------------------------------------------------------ qual canal
def slug_do_item(base: str, it: Dict[str, Any], cfg_lote: Optional[Dict[str, Any]] = None) -> str:
    """O canal (slug da marca) deste roteiro: o escolhido no lote; senão o do 🕵️ Modelo de vídeo; "-" = nenhum."""
    escolha = str((cfg_lote or {}).get("canal") or "").strip()
    if escolha == "-":
        return ""
    if escolha:
        return escolha if os.path.isfile(os.path.join(base, "marcas", escolha, "brand_guide.json")) else ""
    if it.get("origem") != "dossie" or not it.get("origem_id"):
        return ""
    try:
        import dossies
        p = dossies.carregar(base, it["origem_id"])
        return str((dossies.MODELOS.get((p.get("config") or {}).get("modelo") or "") or {}).get("identidade_visual") or "")
    except Exception:  # noqa: BLE001 — modelo apagado etc.
        return ""


def carregar(base: str, slug: str) -> Optional[Dict[str, Any]]:
    if not slug:
        return None
    try:
        import marca_visual
        return marca_visual.carregar(base, slug)
    except Exception:  # noqa: BLE001
        return None


def config(m: Dict[str, Any]) -> Dict[str, Any]:
    """O bloco "producao_pod" do pacote.json (o que faltar = PADRAO)."""
    try:
        with open(os.path.join(m["dir"], "pacote.json"), encoding="utf-8") as f:
            pac = json.load(f)
    except (OSError, ValueError):
        pac = {}
    c = dict(PADRAO, **{k: v for k, v in ((pac or {}).get("producao_pod") or {}).items() if k in PADRAO})
    try:
        c["pct"] = max(0, min(100, int(c["pct"])))
    except (TypeError, ValueError):
        c["pct"] = 100
    if c["texto_na_imagem"] not in ("", "setas_numeros"):  # "setas_numeros" = esquema só com setas/formas/números
        c["texto_na_imagem"] = ""
    if c["cenas"] not in ("canal", "padrao"):
        c["cenas"] = "canal"
    if c["fotos_do_roteiro"] not in ("referencia", "real"):
        c["fotos_do_roteiro"] = "referencia"
    if c["estilo_fotos"] not in ("foto", "ilustracao"):  # pela estética: colagem de fotos de arquivo × desenho/anime
        estilo = str(((m["guia"].get("generation_system") or {}).get("style_lock_en")) or "").lower()
        c["estilo_fotos"] = "foto" if ("photograph" in estilo or "photo " in estilo) else "ilustracao"
    return c


def personagens(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    import marca_visual
    return list((marca_visual.perfil_de(m) or {}).get("personagens") or [])


def tem_mascote(m: Dict[str, Any]) -> bool:
    return bool(((m["guia"].get("mascot") or {}).get("prompt_lock_en"))) and not personagens(m)


def tipos_imagem(m: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, str]:
    import marca_visual
    # 🖼 sem "diagrama" nos canais de pacote — gráfico gerado sai com letras/números tortos; gráfico entra na edição
    # (as setas/números só valem no modo "padrao", o do canal do espaço)
    t = {k: v for k, v in marca_visual.TIPOS_IMAGEM.items() if k not in ("mascote", "diagrama")}
    if cfg.get("estilo_fotos") == "ilustracao":
        t.pop("arquivo", None)  # canal desenhado: nada de "foto de arquivo monocromática"
    return t


# ------------------------------------------------------------------ IA: descrever as cenas no jeito do canal
def _schema(com_elenco: bool):
    from ia_midia import _I, _S, _lista, _obj
    cena = {"n": _I, "visual": _S, "busca": _S, "dificil": _I, "ano": _I, "assunto_en": _S, "pergunta_visual_en": _S,
            "composicao_en": _S, "tipo_imagem": _S, "pessoa": _S, "fala_de": _S, "mascote": _S, "acao_en": _S,
            "personagens": _lista(_S)}
    if com_elenco:
        cena.update(pessoas=_lista(_obj({"nome": _S, "idade": _I})), lugar=_S)
    return _obj({"cenas": _lista(_obj(cena))})


def system(m: Dict[str, Any], cfg: Dict[str, Any], bloco_elenco: str = "") -> str:
    import marca_visual
    g = m["guia"]
    p = g.get("project") or {}
    gs = g.get("generation_system") or {}
    tipos = tipos_imagem(m, cfg)
    pers = personagens(m)
    L = [f"""Você é o diretor de arte do canal “{p.get('name') or m['slug']}” ({p.get('channel_language') or ''}). Planeja as
IMAGENS de um vídeo narrado, cena por cena (cada cena tem uns segundos de fala). TODAS as imagens seguem a estética do
canal (o site acrescenta o estilo e as referências sozinho — você descreve o CONTEÚDO).
Estética do canal: {gs.get('style_lock_en') or ''}
{('Regra editorial: ' + str(p.get('editorial_rule'))) if p.get('editorial_rule') else ''}

Para CADA cena devolva:
- "visual": uma linha, em português, do que aparece na tela;
- "busca": a busca em INGLÊS (2 a 6 palavras) pra um banco de stock (se a cena ficar pro banco);
- "dificil": 0 a 10, quão difícil é achar essa imagem pronta em banco (0-2 genérica … 9-10 só gerando);
- "ano": o ano em que a cena se passa na história (0 se não é um momento datado);
- "assunto_en": em INGLÊS, 25 a 60 palavras, o ASSUNTO concreto da imagem: o objeto/fenômeno/lugar, a ação, a época,
  materiais e o que está em primeiro plano. Sem nome de pessoa real (descreva idade, roupa, época). Sem estilo (o site
  põe o do canal). Nada de texto/letreiro na imagem;
- "pergunta_visual_en": a pergunta que o quadro faz o espectador se perguntar (inglês, curta);
- "composicao_en": plano (aberto, médio, detalhe), ângulo e ponto focal, em inglês — varie entre as cenas;
- "tipo_imagem": um de {list(tipos)} ({'; '.join(f'{k} = {v}' for k, v in tipos.items())});
- "pessoa": "nenhuma" (a imagem não mostra gente: lugar, objeto, fenômeno, mapa…), "generica" (mostraria alguém
  ANÔNIMO: um morador, um cientista, um soldado, "as pessoas", uma criança, um viajante…) ou "real" (mostra uma pessoa
  REAL citada no roteiro){' — pessoa real só se ela está no ELENCO abaixo; senão é "generica"' if bloco_elenco else ''};"""]
    com_pers = bool(cfg.get("personagens", True))  # 🧍 v84_191: false = ninguém do canal é desenhado na cena (entram por cima)
    if pers and not com_pers:
        L.append("- \"fala_de\": o slug do PERSONAGEM que está falando nesta cena (pelas tags de voz [mira], [vanta|curiosa]… "
                 "no ROTEIRO), ou \"\" se é o narrador; \"personagens\": [] e \"mascote\": \"\" SEMPRE; \"acao_en\": \"\".")
    elif pers:
        L.append("- \"fala_de\": o slug do PERSONAGEM que está falando nesta cena (pelas tags de voz [mira], [vanta|curiosa]… "
                 "no ROTEIRO), ou \"\" se é o narrador;")
        L.append("- \"personagens\": os slugs dos personagens que aparecem NA IMAGEM (0, 1 ou 2). REGRA DO CANAL: quem está "
                 "FALANDO aparece (reagindo, perguntando, apontando); numa cena \"generica\" a pessoa anônima VIRA um "
                 "personagem do canal (quem fala ali ou o que combina mais); cena \"real\" ou \"nenhuma\" sem fala de "
                 "personagem → lista vazia;")
        L.append("- \"acao_en\": o que o(s) personagem(ns) faz(em) e sente(m) neste quadro, em inglês (vazio se não aparece "
                 "ninguém). \"mascote\": sempre \"\".")
        L.append("\nPERSONAGENS DO CANAL:")
        for x in pers:
            L.append(f"- {x['slug']} = {x.get('nome') or x['slug']}" + (f" ({x['epiteto']})" if x.get("epiteto") else "")
                     + (f" · papel: {x['papel']}" if x.get("papel") else ""))
    elif tem_mascote(m) and com_pers:
        poses = "; ".join(f"{k} = {v['en']}" for k, v in marca_visual.todas_poses(m).items())
        L.append(f"""- "mascote": REGRA DO CANAL: só numa cena "generica" — a pessoa anônima VIRA o mascote do canal
  ({(g.get('mascot') or {}).get('role') or 'o guia do canal'}). Escolha a pose: {poses}. Cena "real" ou "nenhuma" → "".
- "acao_en": se tem mascote, o que ele faz no lugar daquela pessoa (ex.: "carrying a heavy sack across the muddy
  field like a 19th-century farmer"), em inglês. "fala_de": "", "personagens": [].""")
    elif not pers:
        L.append('- "fala_de": "", "mascote": "", "acao_en": "", "personagens": [] (este canal não tem personagens na imagem).')
    if not com_pers:
        L.append("""
REGRA DAS IMAGENS DESTE CANAL (muito importante):
- QUEM FALA NUNCA APARECE na imagem: nem o narrador (é só a voz), nem os personagens/mascote do canal (eles entram por
  cima do vídeo depois, à parte). Não invente uma pessoa "reagindo", "perguntando", "olhando espantada" ou "pensativa"
  no lugar de quem fala — a imagem mostra o ASSUNTO da fala: o fenômeno, o objeto, o lugar, o processo.
- Gente só quando a fala é SOBRE pessoas (ex.: os astrônomos chineses de 1054, uma multidão, um cientista trabalhando);
  aí "pessoa": "generica" (ou "real" do elenco). Nos outros casos "pessoa": "nenhuma".
- NADA de texto na imagem: sem perguntas, títulos, legendas, rótulos, setas com nome, logo — os textos entram na edição.
  Também nada de enfeite solto: ponto de interrogação/exclamação, setas, rabiscos, anotações, folhas/páginas de livro
  coladas nos cantos, gráficos com números. Uma imagem limpa do assunto.
  Letras só quando fazem parte de um objeto real da cena (um livro, um cartaz, uma placa).
- VARIE os cenários: não repita o mesmo lugar (ex.: observatório) cena após cena; cada imagem mostra o que a frase diz.""")
    if bloco_elenco:
        import elenco as _el
        L.append("\n" + _el.REGRA_CENAS.replace("\"prompt_imagem\"", "\"assunto_en\"") + "\n\n" + bloco_elenco)
    L.append("\nMantenha o \"n\" de cada cena. Coerência com as cenas vizinhas (mesmo lugar, mesma época).")
    return "\n".join(x for x in L if x is not None)


def descrever(cenas: List[Dict[str, Any]], roteiro: str, idioma: str, m: Dict[str, Any], elenco: Optional[Dict[str, Any]] = None,
              ficha: Optional[Dict[str, Any]] = None, job: Optional[str] = None, on_passo=None) -> Dict[int, Dict[str, Any]]:
    """{n (1-based): {visual, busca, dificil, ano, assunto_en, …, pessoa, fala_de, mascote, acao_en, personagens,
    pessoas?, lugar?}} — vazio sem IA (ou se ela falhar). Já com a regra dos personagens aplicada."""
    import ia_servico as ia
    if not cenas or not ia.ativo("producao_pod"):
        return {}
    import elenco as _el
    cfg = config(m)
    bloco_el = _el.bloco_para_cenas(elenco or {})
    nomes_el = {x["nome"].lower(): x["nome"] for x in (elenco or {}).get("pessoas") or [] if x.get("usar", True)}
    locais_el = {x["nome"].lower(): x["nome"] for x in (elenco or {}).get("locais") or [] if x.get("usar", True)}
    sis = system(m, cfg, bloco_el) + ("\n\n## FICHA DO VÍDEO\n" + json.dumps(ficha, ensure_ascii=False) if ficha else "") \
        + (f"\n\nIdioma da narração: {idioma}" if idioma else "") + ("\n\n## ROTEIRO (com as tags de voz)\n" + roteiro[:60000] if roteiro else "")
    tipos = tipos_imagem(m, cfg)
    out: Dict[int, Dict[str, Any]] = {}

    def linha(j: int) -> str:
        c = cenas[j]
        antes = cenas[j - 1]["fala"][-160:] if j else ""
        depois = cenas[j + 1]["fala"][:160] if j + 1 < len(cenas) else ""
        return (f"[{j + 1}] ({c['end'] - c['start']:.1f}s)" + (f" antes: {antes} |" if antes else "")
                + f" FALA: {c['fala'][:400]}" + (f" | depois: {depois}" if depois else ""))

    def bloco(idx: List[int]) -> Dict[int, Dict[str, Any]]:
        r = ia.chamar("producao_pod", sis, "## CENAS\n" + "\n".join(linha(j) for j in idx), _schema(bool(bloco_el)),
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
                 "dificil": max(0, min(10, _int(x.get("dificil")))),
                 "ano": max(0, min(2100, _int(x.get("ano")))),
                 "assunto_en": " ".join(str(x.get("assunto_en") or "").split())[:900],
                 "pergunta_visual_en": " ".join(str(x.get("pergunta_visual_en") or "").split())[:300],
                 "composicao_en": " ".join(str(x.get("composicao_en") or "").split())[:400],
                 "tipo_imagem": x.get("tipo_imagem") if x.get("tipo_imagem") in tipos else "",
                 "pessoa": x.get("pessoa") if x.get("pessoa") in ("nenhuma", "generica", "real") else "nenhuma",
                 "fala_de": str(x.get("fala_de") or "").strip(), "mascote": str(x.get("mascote") or "").strip(),
                 "acao_en": " ".join(str(x.get("acao_en") or "").split())[:300],
                 "personagens": [str(s) for s in x.get("personagens") or [] if isinstance(s, str)][:3],
                 "pessoas": [], "lugar": ""}
            if bloco_el:
                ps = []
                for pc in x.get("pessoas") or []:
                    nome = nomes_el.get(str((pc or {}).get("nome") or "").strip().lower())
                    if nome and not any(q["nome"] == nome for q in ps):
                        ps.append({"nome": nome, "idade": max(0, min(110, _int(pc.get("idade"))))})
                d["pessoas"] = ps[:3]
                d["lugar"] = locais_el.get(str(x.get("lugar") or "").strip().lower(), "")
            if d["assunto_en"]:
                res[n] = aplicar_regra(m, d, cfg)
        return res

    from concurrent.futures import ThreadPoolExecutor, as_completed
    todos = list(range(len(cenas)))
    for tentativa in (1, 2):
        faltam = [j for j in todos if j + 1 not in out]
        if not faltam:
            break
        blocos = [faltam[k:k + BLOCO_IA] for k in range(0, len(faltam), BLOCO_IA)]
        feitos = 0
        with ThreadPoolExecutor(max_workers=PARALELO_IA) as ex:
            for f in as_completed([ex.submit(bloco, b) for b in blocos]):
                try:
                    out.update(f.result())
                except Exception:  # noqa: BLE001 — esse bloco vai de novo na 2ª volta
                    pass
                feitos += 1
                if on_passo:
                    on_passo(f"🎨 {'refazendo as que faltaram: ' if tentativa == 2 else ''}cenas no estilo do canal — "
                             f"bloco {feitos}/{len(blocos)} · {len(out)} de {len(cenas)} prontas")
    return out


def _int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def aplicar_regra(m: Dict[str, Any], d: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A regra dos personagens, sem depender de a IA acertar tudo:
    pessoa real do elenco → sem personagem · personagem falando → aparece · pessoa genérica → vira personagem ·
    sem pessoa → nada. Normaliza "mascote" (pose do catálogo) e "personagens" ([{slug, acao_en}])."""
    import marca_visual
    cfg = cfg or config(m)
    d = dict(d)
    d["mascote"], pers_ok = "", []
    if not cfg.get("personagens", True) or d.get("pessoas") or d.get("pessoa") == "real":
        d["personagens"] = []
        return d
    pers = personagens(m)
    if pers:
        import canal_perfil
        slugs = [x["slug"] for x in pers]
        fala = canal_perfil._slug(d.get("fala_de") or "") if d.get("fala_de") else ""
        escolhidos = [canal_perfil._slug(s) for s in d.get("personagens") or []]
        escolhidos = [s for s in dict.fromkeys(escolhidos) if s in slugs]
        if fala in slugs and fala not in escolhidos:
            escolhidos.insert(0, fala)
        if d.get("pessoa") == "generica" and not escolhidos:
            escolhidos = [fala if fala in slugs else slugs[0]]
        if d.get("pessoa") == "nenhuma" and fala not in slugs:
            escolhidos = []  # cena sem gente e sem fala de personagem: imagem do assunto, sem personagem
        pers_ok = [{"slug": s, "acao_en": d.get("acao_en") or ""} for s in escolhidos[:2]]
    elif tem_mascote(m) and d.get("pessoa") == "generica":
        poses = marca_visual.todas_poses(m)
        pose = d.get("mascote") if d.get("mascote") in poses else marca_visual.pose_mais_proxima(
            f"{d.get('mascote') or ''} {d.get('acao_en') or ''}")
        d["mascote"] = pose if pose in poses else "curioso"
    d["personagens"] = pers_ok
    return d


def sem_ia(cena: Dict[str, Any], m: Dict[str, Any]) -> Dict[str, Any]:
    """Sem a IA: a fala vira o assunto e o personagem aparece quando a tag de voz dele cai na cena."""
    return aplicar_regra(m, {"assunto_en": cena.get("fala") or "", "pessoa": "nenhuma", "fala_de": cena.get("fala_de") or "",
                             "visual": (cena.get("fala") or "")[:200], "busca": "", "dificil": 0, "ano": 0})


# ------------------------------------------------------------------ prompt + referências de uma cena
def _nome_ref(papel: str, cam: str) -> str:
    ext = os.path.splitext(cam)[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png"
    return f"{papel[:30]}_{hashlib.sha1(os.path.abspath(cam).encode('utf-8')).hexdigest()[:10]}{ext}"


def prompt_e_refs(m: Dict[str, Any], d: Dict[str, Any], origem_id: str = "", foto: str = "", estilo_extra: str = "",
                  cfg: Optional[Dict[str, Any]] = None) -> Tuple[str, List[List[str]]]:
    """O prompt final da cena (template + style_lock + trava do mascote/personagens + "Avoid:") e as referências pro
    klein: [[nome do arquivo, caminho no PC]] (até 4). `foto`: a foto marcada no roteiro nesta cena (vira referência)."""
    import marca_visual
    cfg = cfg or config(m)
    b = {"assunto_en": d.get("assunto_en") or d.get("visual") or "", "pergunta_visual_en": d.get("pergunta_visual_en") or "",
         "composicao_en": d.get("composicao_en") or "", "tipo_imagem": d.get("tipo_imagem") or "",
         "mascote": d.get("mascote") or "", "acao_mascote_en": d.get("acao_en") if d.get("mascote") else "",
         "personagens": d.get("personagens") or [], "pessoas": d.get("pessoas") or [], "lugar": d.get("lugar") or "",
         "ano": d.get("ano") or 0}
    p = {"origem": {"tipo": "dossie", "id": origem_id} if origem_id else {}, "ref_estilo_sempre": bool(cfg.get("ref_estilo"))}
    cena = marca_visual.cena_da_batida(m, p, b)  # 🎭 elenco (rosto na idade da cena) + lugar
    if foto and os.path.isfile(foto) and foto not in cena["refs_extras"]:
        cena["refs_extras"].append(foto)
        cena["fotos_info"].append({"descricao_en": "", "estilo": cfg.get("estilo_fotos") or "ilustracao",
                                   "frase": "this scene is about the real subject in this photo — keep what makes it "
                                            "recognizable (shape, features, layout)"})
    refs = marca_visual.referencias_para(m, cena, "pod")
    prompt = marca_visual.montar_prompt(m, cena, refs)
    if estilo_extra:
        prompt = f"{prompt} {estilo_extra.strip()}"
    return prompt, [[_nome_ref(papel, cam), cam] for papel, cam in refs]
