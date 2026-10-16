"""🎭 Elenco do vídeo (v84_128) — quem é quem nas fotos do 🕵️ Modelo de vídeo, com a IDADE em cada foto.

Serve pra 🏭 Produção no pod gerar cenas com o ROSTO das pessoas reais (FLUX.2 klein 4B no pod, com a foto de
referência) e na IDADE certa da cena: o filho que só tem foto criança aparece adulto anos depois, o pai envelhece
na cena do julgamento etc.

  montar_com_ia(base, p)          → a IA olha as fotos (com legenda/descrição) e o roteiro e devolve o elenco
  ler(...) / salvar(...)          → normaliza o que veio da IA ou da tela (dá pra corrigir nome, nascimento, idades)
  bloco_para_cenas(el)            → o texto do elenco que vai pra IA que descreve as cenas
  rostos_da_cena(el, pessoas, p)  → o prompt com "image 1 / image 2" + as fotos de referência de cada pessoa
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

MAX_FOTOS_IA = 120
MAX_REFS = 3
_EXT_FOTO = (".jpg", ".jpeg", ".png", ".webp")


def _schema():
    from ia_midia import _B, _I, _S, _lista, _obj
    foto = _obj({"midia": _S, "idade": _I, "ano": _I, "quem_na_foto": _S, "so_ele": _B, "rosto_visivel": _B, "como_sei": _S})
    pessoa = _obj({"nome": _S, "papel": _S, "nascimento": _I, "aparencia": _S, "fotos": _lista(foto)})
    local = _obj({"nome": _S, "tipo": _S, "descricao": _S, "ano": _I, "fotos": _lista(_S)})
    marco = _obj({"ano": _I, "evento": _S})
    return _obj({"pessoas": _lista(pessoa), "locais": _lista(local), "cronologia": _lista(marco)})


_SYS = """Você CATALOGA as fotos de um vídeo documental (muitas foram extraídas de matérias da web): quem é cada PESSOA
real do roteiro e quais são os LUGARES. Isso vira o ELENCO que um gerador de imagem usa pra pôr o rosto certo, na
idade certa, nas cenas.

COMO SABER QUEM É: pelo CONTEXTO de cada foto — legenda, título/descrição OG da matéria, texto em volta, texto
IMPRESSO na imagem (cartaz de DESAPARECIDO/PROCURADO/RECOMPENSA, ficha policial, documento, recorte de jornal) e a
descrição que eu escrevi. Não identifique ninguém pelo rosto: sem contexto que diga quem é, a foto fica de fora.
Na mesma foto com várias pessoas, use a legenda ("da esquerda para a direita…") pra dizer qual é qual.

PESSOAS — cada pessoa do roteiro com pelo menos uma foto em que o ROSTO aparece:
- "nome" (como o roteiro chama) e "papel" curto (ex.: "o pai, assassino", "filho mais novo, vítima", "detetive");
- "nascimento": ano de nascimento (do roteiro, da legenda ou do cartaz: "15 anos em 1971" → 1956), senão 0;
- "aparencia": em INGLÊS, traços estáveis pra um gerador de imagem (cabelo, óculos, formato do rosto, porte) — sem
  roupa e sem idade;
- "fotos": cada foto dela: "midia" (ID), "idade" NAQUELA foto (pelo cartaz/legenda/data; se não diz, estime pela
  aparência), "ano" da foto (0 se não sabe), "quem_na_foto" em INGLÊS dizendo qual pessoa é ela quando há mais gente
  ("the boy on the right"; vazio se está sozinha), "so_ele", "rosto_visivel" (dá pra usar de referência de rosto) e
  "como_sei" curto ("legenda", "cartaz de desaparecido", "OG da matéria", "minha descrição").
LOCAIS — os lugares importantes do caso (a casa, a rua, a cidade, o tribunal, a cena do crime, a escola, o carro…),
COM ou SEM foto: se as FONTES/o roteiro descrevem o lugar em detalhe, ele entra mesmo sem foto ("fotos": []).
- "nome" (como o roteiro chama), "tipo" (casa, rua, cidade, prédio, cena do crime, interior, veículo…),
  "descricao" em INGLÊS pra um gerador de imagem, RICA e fiel às fontes + fotos: arquitetura, número de andares,
  materiais, cores, móveis/objetos citados, entorno, estação/clima se as fontes dizem (60-120 palavras);
- "ano" em que o lugar aparece na história (0 se não sabe), "fotos" (IDs das fotos dele; pode ser vazio).
CRONOLOGIA — 5 a 25 marcos do caso em ordem ("ano", "evento" curto): nascimentos, mudanças, o crime, a fuga, a
captura, o julgamento, a morte… É por ela que cada cena sabe em que ano está e que idade cada pessoa tem.
Não invente. Gente sem nome (multidão, policial anônimo) não entra. Use exatamente os NOMES JÁ CATALOGADOS quando a
pessoa/lugar for o mesmo (vem na lista abaixo das fotos)."""

LOTE_IA = 20


def _fotos(base: str, p: Dict[str, Any], limite: Optional[int] = None) -> List[Dict[str, Any]]:
    import dossies as ds
    out = []
    for m in p.get("midias") or []:
        if m.get("tipo") != "foto" or m.get("descartada") or m.get("duplicada_de"):
            continue
        cam = ds.caminho_midia(base, p, m)
        if cam and cam.lower().endswith(_EXT_FOTO):
            og = m.get("og") or {}
            ctx = ds.o_que_e(m)[:500]
            if og.get("titulo") and og["titulo"] not in ctx:
                ctx += f" | matéria: {og['titulo']}"
            out.append({"id": m["id"].upper(), "caminho": cam, "contexto": ctx[:700], "alvo": m.get("pergunta_alvo") or ""})
    # primeiro as que respondem a uma pergunta (📸), os cartazes/documentos e as que citam gente
    out.sort(key=lambda f: (not f["alvo"],
                            not re.search(r"desaparecid|missing|procurad|wanted|recompensa|reward|cartaz|poster", f["contexto"], re.I),
                            not re.search(r"\b(homem|mulher|menino|menina|man|woman|boy|girl|retrato|portrait|família|family)\b",
                                          f["contexto"], re.I)))
    return out[:limite] if limite else out


def _juntar(acum: Dict[str, Any], novo: Dict[str, Any]) -> None:
    """Junta o lote novo no elenco acumulado (mesma pessoa/lugar = mesmo nome)."""
    for chave, lista_f in (("pessoas", "fotos"), ("locais", "fotos")):
        por_nome = {x["nome"].lower(): x for x in acum[chave]}
        for x in novo.get(chave) or []:
            ja = por_nome.get(x["nome"].lower())
            if not ja:
                acum[chave].append(x)
                por_nome[x["nome"].lower()] = x
                continue
            for f in x[lista_f]:
                mid = f["midia"] if isinstance(f, dict) else f
                if not any((g["midia"] if isinstance(g, dict) else g) == mid for g in ja[lista_f]):
                    ja[lista_f].append(f)
            for k in ("nascimento", "aparencia", "papel", "descricao", "ano", "tipo"):
                if not ja.get(k) and x.get(k):
                    ja[k] = x[k]


def montar_com_ia(base: str, p: Dict[str, Any], job: Optional[str] = None, on_passo=None) -> Optional[Dict[str, Any]]:
    """Cataloga TODAS as fotos (de 20 em 20). None sem IA (ou se ela falhar em tudo)."""
    import ia_servico as ia
    if not ia.ativo("elenco"):
        return None
    fotos = _fotos(base, p)[:MAX_FOTOS_IA]
    ids = {f["id"] for f in _fotos(base, p)}
    import dossies as ds
    roteiro = (p.get("resultado") or {}).get("roteiro_final") or ""
    try:
        fontes = ds._fontes_texto(p, 40000)
    except Exception:  # noqa: BLE001
        fontes = ""
    system = (_SYS + f"\n\n## TEMA\n{ds.nome_do_projeto(p)}\n\n## ROTEIRO\n{roteiro[:50000] or '(ainda sem roteiro — use o tema e as fontes)'}"
              + (f"\n\n## FONTES (descrição do caso)\n{fontes}" if fontes else ""))
    acum: Dict[str, Any] = {"pessoas": [], "locais": [], "cronologia": []}
    alguma = False
    grupos = [fotos[k:k + LOTE_IA] for k in range(0, len(fotos), LOTE_IA)] or [[]]  # sem foto: só locais/cronologia
    for k, grupo in zip(range(0, 10 ** 6, LOTE_IA), grupos):
        if on_passo:
            on_passo(f"🤖 catalogando as fotos {k + 1}–{k + len(grupo)} de {len(fotos)}…")
        conteudo: List[Dict[str, Any]] = []
        for f in grupo:
            bloco = ia.imagem_bloco(f["caminho"], largura=448)
            if not bloco:
                continue
            conteudo.append({"type": "text", "text": f"[{f['id']}] " + (f"(enviada como foto de: {f['alvo']}) " if f["alvo"] else "")
                                                     + f"contexto: {f['contexto']}"})
            conteudo.append(bloco)
        if not conteudo and grupo:
            continue
        if not grupo:
            conteudo.append({"type": "text", "text": "Ainda não tenho fotos: faça só os LOCAIS (pelas fontes) e a CRONOLOGIA."})
        if acum["pessoas"] or acum["locais"]:
            conteudo.append({"type": "text", "text": "JÁ CATALOGADOS (use os mesmos nomes): pessoas: "
                             + "; ".join(f"{x['nome']} ({x['papel']})" for x in acum["pessoas"])
                             + " | locais: " + "; ".join(x["nome"] for x in acum["locais"])})
        r = ia.chamar("elenco", system, conteudo, _schema(), max_tokens=8000, effort="low", job=job, timeout=240)
        if r is None:
            continue
        alguma = True
        lido = ler(r, {f["id"] for f in grupo})
        _juntar(acum, lido)
        if len(lido.get("cronologia") or []) > len(acum["cronologia"]):
            acum["cronologia"] = lido["cronologia"]
    if not alguma:
        return None
    return ler(acum, ids)


def ler(d: Any, ids_validos: set) -> Dict[str, Any]:
    """Normaliza o elenco (da IA ou da tela)."""
    pessoas = []
    for x in (d or {}).get("pessoas") or []:
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        fotos = []
        for f in x.get("fotos") or []:
            mid = str((f or {}).get("midia") or "").strip("[] ").upper()
            if mid not in ids_validos or any(g["midia"] == mid for g in fotos):
                continue
            fotos.append({"midia": mid, "idade": _int(f.get("idade"), 0, 110), "ano": _int(f.get("ano"), 0, 2100),
                          "quem_na_foto": str(f.get("quem_na_foto") or "").strip()[:160],
                          "so_ele": bool(f.get("so_ele", True)), "rosto_visivel": bool(f.get("rosto_visivel", True)),
                          "como_sei": str(f.get("como_sei") or "").strip()[:60]})
        if not fotos:
            continue
        pessoas.append({"nome": str(x["nome"]).strip()[:80], "papel": str(x.get("papel") or "").strip()[:120],
                        "nascimento": _int(x.get("nascimento"), 0, 2100), "aparencia": str(x.get("aparencia") or "").strip()[:300],
                        "usar": x.get("usar", True) is not False, "fotos": fotos[:12]})
    locais = []
    for x in (d or {}).get("locais") or []:
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        fotos = list(dict.fromkeys(str(f).strip("[] ").upper() for f in x.get("fotos") or []
                                   if str(f).strip("[] ").upper() in ids_validos))
        if not fotos and len(str(x.get("descricao") or "").split()) < 12:
            continue  # sem foto, só fica o lugar bem descrito
        locais.append({"nome": str(x["nome"]).strip()[:80], "tipo": str(x.get("tipo") or "").strip()[:40],
                       "descricao": str(x.get("descricao") or "").strip()[:300], "ano": _int(x.get("ano"), 0, 2100),
                       "usar": x.get("usar", True) is not False, "fotos": fotos[:8]})
    crono = sorted(({"ano": _int(c.get("ano"), 1, 2100), "evento": str(c.get("evento") or "").strip()[:160]}
                    for c in (d or {}).get("cronologia") or [] if isinstance(c, dict) and str(c.get("evento") or "").strip()
                    and _int(c.get("ano"), 1, 2100)), key=lambda c: c["ano"])
    return {"pessoas": pessoas[:30], "locais": locais[:40], "cronologia": crono[:40], "gerado_em": time.time(),
            "midias": sorted(ids_validos)}


def _int(v: Any, lo: int, hi: int) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return 0
    return n if lo <= n <= hi else 0


def ids_de_fotos(base: str, p: Dict[str, Any]) -> set:
    return {f["id"] for f in _fotos(base, p, None)}


def do_projeto(base: str, p: Dict[str, Any], criar: bool = True, job: Optional[str] = None) -> Dict[str, Any]:
    """O elenco guardado no modelo; sem ele (e com a IA), monta e guarda."""
    el = p.get("elenco")
    if el or not criar:
        return el or {"pessoas": []}
    novo = montar_com_ia(base, p, job=job)
    if novo is None:
        return {"pessoas": []}
    import dossies as ds
    import dossies_rotas
    with dossies_rotas._TRAVA:
        q = ds.carregar(base, p["id"])
        q["elenco"] = novo
        ds.salvar(base, q)
    return novo


# ------------------------------------------------------------------ nas cenas
def bloco_para_cenas(el: Dict[str, Any]) -> str:
    ps = [x for x in (el or {}).get("pessoas") or [] if x.get("usar", True)]
    ls = [x for x in (el or {}).get("locais") or [] if x.get("usar", True)]
    if not ps and not ls and not (el or {}).get("cronologia"):
        return ""
    L = []
    if ps:
        L.append("## ELENCO (pessoas reais com foto — o gerador põe o ROSTO delas na imagem)")
        for x in ps:
            idades = ", ".join(f"{f['idade']} anos" + (f" em {f['ano']}" if f.get("ano") else "") for f in x["fotos"] if f.get("idade"))
            L.append(f"- {x['nome']} ({x['papel']})" + (f", nasceu em {x['nascimento']}" if x.get("nascimento") else "")
                     + (f" — fotos com {idades}" if idades else ""))
    if ls:
        L.append("## LOCAIS do caso (o gerador mantém cada lugar IGUAL em todas as cenas: pela foto ou pela descrição)")
        L += [f"- {x['nome']} ({x['tipo']})" + (f", {x['ano']}" if x.get("ano") else "") + (" [tem foto]" if x.get("fotos") else "")
              for x in ls]
    cr = (el or {}).get("cronologia") or []
    if cr:
        L.append("## CRONOLOGIA do caso")
        L += [f"- {c['ano']}: {c['evento']}" for c in cr]
    return "\n".join(L)


REGRA_CENAS = """Para CADA cena diga também:
- "pessoas": quem do ELENCO aparece com o ROSTO na imagem dessa cena (nome exato do elenco) e com que "idade" ELE
  ESTÁ NAQUELE MOMENTO DA HISTÓRIA — não na data da narração: pense na linha do tempo (flashback, "anos depois",
  julgamento décadas mais tarde, a criança que cresceu). Use o nascimento/idades das fotos pra calcular. Lista vazia
  quando a cena não mostra ninguém do elenco (lugar, objeto, multidão, pessoa genérica).
- "ano": o ano em que a cena se passa (0 se não dá pra saber).
- "lugar": o nome exato de um dos LOCAIS quando a cena se passa ali (vazio se não) — o lugar sai igual em todas as
  cenas, então use sempre que a cena é nele.
- DOCUMENTOS DA ÉPOCA também são cenas ótimas pro gerador: cartaz de PROCURADO/DESAPARECIDO, primeira página de jornal,
  ficha policial, carteira de motorista, carta. Quando o roteiro fala disso, a cena pode ser o documento: ponha a pessoa
  em "pessoas" com a idade DA FOTO DO DOCUMENTO (a idade dela na data do documento) e no "prompt_imagem" descreva o
  documento da época (papel, tipografia, layout, desgaste) com SÓ textos curtos e REAIS tirados do roteiro (nome, data,
  cidade, "WANTED", "MISSING") — nunca invente fato, número ou recompensa que o roteiro não tem.
- Com pessoa do ELENCO (rosto real): NUNCA violência, sangue, arma apontada, corpo, morte ou o crime acontecendo, e
  nada humilhante. Nesses momentos a cena fica SEM pessoas do elenco (o lugar, objetos, sombra, polícia genérica).
- Quando há pessoa do elenco, o "prompt_imagem" descreve a cena e a pessoa pela idade/roupa/expressão/época ("a man in
  his late 40s in a 1971 suit…"), sem nome; o site cuida do rosto.
- ÉPOCA SEMPRE: carros, roupas, cabelos, objetos, tecnologia e placas do ANO da cena (pela CRONOLOGIA), nada moderno
  num 1971; e coerência entre cenas vizinhas (mesma casa, mesma roupa no mesmo dia, mesma estação)."""


def _melhor_foto(pessoa: Dict[str, Any], idade: int) -> Optional[Dict[str, Any]]:
    fotos = [f for f in pessoa["fotos"] if f.get("rosto_visivel", True)] or pessoa["fotos"]
    if not fotos:
        return None
    return min(fotos, key=lambda f: ((abs((f.get("idade") or idade or 40) - (idade or f.get("idade") or 40))),
                                     not f.get("so_ele", True)))


def _envelhecer(idade: int, dif: int) -> str:
    if dif >= 8:
        if idade >= 65:
            extra = "white or grey hair, deep wrinkles, sagging skin, age spots"
        elif idade >= 45:
            extra = "greying hair, wrinkles around the eyes and forehead, slightly heavier face"
        elif idade >= 18:
            extra = "a grown adult face — the same features matured, adult proportions"
        else:
            extra = "the same child grown older, longer face, the same eyes and features"
        return f", {dif} years older than in the reference photo ({extra})"
    if dif <= -8:
        if idade < 13:
            extra = "a child's face, rounder cheeks, smaller nose"
        elif idade < 20:
            extra = "a teenager's face, smooth skin"
        else:
            extra = "younger skin, fuller hair, no wrinkles"
        return f", {-dif} years younger than in the reference photo ({extra})"
    return ""


def rostos_da_cena(el: Dict[str, Any], pessoas_cena: List[Dict[str, Any]], prompt: str, base: str,
                   p: Dict[str, Any], lugar: str = "", ano: int = 0) -> Tuple[str, List[Tuple[str, str]]]:
    """→ (prompt com as referências, [(nome do arquivo, caminho)]). Sem ninguém do elenco: (prompt, [])."""
    import dossies as ds
    por_nome = {x["nome"].lower(): x for x in (el or {}).get("pessoas") or [] if x.get("usar", True)}
    refs: List[Tuple[str, str]] = []
    frases: List[str] = []
    for pc in pessoas_cena or []:
        x = por_nome.get(str(pc.get("nome") or "").strip().lower())
        if not x or len(refs) >= MAX_REFS:
            continue
        idade = int(pc.get("idade") or 0)
        if not idade and ano and x.get("nascimento"):  # 🕰 pela cronologia: ano da cena − nascimento
            idade = max(0, ano - x["nascimento"])
        f = _melhor_foto(x, idade)
        m = ds.midia(p, f["midia"]) if f else None
        cam = ds.caminho_midia(base, p, m) if m else None
        if not cam:
            continue
        nome_arq = f["midia"] + os.path.splitext(cam)[1].lower()
        if any(n == nome_arq for n, _c in refs):
            continue
        refs.append((nome_arq, cam))
        k = len(refs)
        quem = f.get("quem_na_foto") if not f.get("so_ele", True) and f.get("quem_na_foto") else "the person"
        idade_txt = f", about {idade} years old" if idade else ""
        dif = (idade - f["idade"]) if idade and f.get("idade") else 0
        frases.append(f"Use the face and identity of {quem} in image {k}{idade_txt}{_envelhecer(idade, dif) if idade else ''}"
                      + (f" ({x['aparencia']})" if x.get("aparencia") else ""))
    loc = next((x for x in (el or {}).get("locais") or [] if x.get("usar", True) and lugar
                and x["nome"].lower() == lugar.strip().lower()), None)
    descr_local = ""
    if loc:
        cam = None
        if loc.get("fotos") and len(refs) < MAX_REFS:
            m = ds.midia(p, loc["fotos"][0])
            cam = ds.caminho_midia(base, p, m) if m else None
        if cam:
            refs.append((loc["fotos"][0] + os.path.splitext(cam)[1].lower(), cam))
            frases.append(f"The location is the place shown in image {len(refs)} (same architecture and surroundings"
                          + (f": {loc['descricao']}" if loc.get("descricao") else "") + "), adapted to the time and light of this scene")
        elif loc.get("descricao"):  # 📍 sem foto: a descrição fiel às fontes, igual em todas as cenas
            descr_local = f" Location ({loc['nome']}): {loc['descricao']}"
    if not refs:
        return (prompt.rstrip(". ") + "." + descr_local) if descr_local else prompt, []
    tem_rosto = any(f.startswith("Use the face") for f in frases)
    texto = (prompt.rstrip(". ") + "." + descr_local + " " + ". ".join(frases) + "."
             + (" Keep the same face so the person is clearly recognizable, but NOT the pose, clothes, background or "
                "photo quality of the reference" if tem_rosto else "")
             + " — new scene, photorealistic, consistent with the time period.")
    return texto, refs


# ------------------------------------------------------------------ rotas (🕵️ Modelo de vídeo → cartão 🎭 Elenco)
_RODANDO: Dict[str, Dict[str, Any]] = {}  # catalogação em segundo plano: {pid: {ativo, msg, erro}}

def registrar(app, base_dir: str) -> None:
    from flask import jsonify, request
    import dossies as ds
    import dossies_rotas

    def _p(pid: str):
        try:
            return ds.carregar(base_dir, pid)
        except ds.DossieError:
            return None

    def _estado(p: Dict[str, Any]) -> Dict[str, Any]:
        import ia_servico
        fotos = [{"id": f["id"], "url": ds.url_midia(p, ds.midia(p, f["id"])), "contexto": f["contexto"][:160]}
                 for f in _fotos(base_dir, p, None)]
        return {"ok": True, "elenco": p.get("elenco") or {"pessoas": [], "locais": []}, "fotos": fotos,
                "ia": ia_servico.ativo("elenco"), "ia_motivo": ia_servico.motivo_desligado("elenco") or "",
                "rodando": _RODANDO.get(p["id"]) or None}

    @app.route("/modelos-video/<pid>/elenco")
    def elenco_ver(pid: str):
        p = _p(pid)
        return jsonify(_estado(p)) if p else (jsonify({"erro": "Projeto não encontrado."}), 404)

    @app.route("/modelos-video/<pid>/elenco/ia", methods=["POST"])
    def elenco_ia(pid: str):
        """🤖 Cataloga todas as fotos (pessoas e locais) em segundo plano — a tela acompanha pelo GET."""
        import threading
        import ia_servico
        p = _p(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        if not ia_servico.ativo("elenco"):
            return jsonify({"erro": "IA: " + (ia_servico.motivo_desligado("elenco") or "desligada")}), 400
        if (_RODANDO.get(pid) or {}).get("ativo"):
            return jsonify(_estado(p))
        _RODANDO[pid] = {"ativo": True, "msg": "🤖 começando…", "erro": ""}

        def rodar():
            try:
                novo = montar_com_ia(base_dir, p, job=pid, on_passo=lambda m: _RODANDO[pid].update(msg=m))
                if novo is None:
                    _RODANDO[pid] = {"ativo": False, "msg": "", "erro": "a IA não respondeu — tente de novo"}
                    return
                with dossies_rotas._TRAVA:
                    q = ds.carregar(base_dir, pid)
                    q["elenco"] = novo
                    ds.marcar_mudanca(q, "🎭 elenco", f"{len(novo['pessoas'])} pessoas, {len(novo['locais'])} locais (IA)")
                    ds.salvar(base_dir, q)
                _RODANDO[pid] = {"ativo": False, "msg": f"✔ {len(novo['pessoas'])} pessoa(s) e {len(novo['locais'])} local(is)", "erro": ""}
            except Exception as exc:  # noqa: BLE001
                _RODANDO[pid] = {"ativo": False, "msg": "", "erro": str(exc)[:300]}

        threading.Thread(target=rodar, daemon=True).start()
        return jsonify(_estado(p))

    @app.route("/modelos-video/<pid>/elenco", methods=["POST"])
    def elenco_salvar(pid: str):
        with dossies_rotas._TRAVA:
            p = _p(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            novo = ler(request.get_json(silent=True) or {}, ids_de_fotos(base_dir, p))
            p["elenco"] = novo
            ds.marcar_mudanca(p, "🎭 elenco", f"{len(novo['pessoas'])} pessoas (editado)")
            ds.salvar(base_dir, p)
        return jsonify(_estado(p))
