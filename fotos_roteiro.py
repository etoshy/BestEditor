"""📸 Fotos pro roteiro (v84_127) — passo OPCIONAL do 🕵️ Modelo de vídeo, depois que o roteiro está pronto.

1. ❓ A IA lê o roteiro e PERGUNTA que fotos você tem: das pessoas, lugares, objetos, documentos, cenas… que o roteiro
   cita (qualquer nicho). Você responde enviando as fotos de cada pergunta (com uma descrição) — ou outras imagens soltas.
2. 📍 A IA POSICIONA as imagens: o roteiro vai dividido em frases numeradas e ela diz em quais frases cada imagem entra.
   O site põe as marcas [I9] antes dessas frases (as marcas não são lidas pela voz) — e dá pra desfazer.

Os dois passos funcionam com a 🤖 IA do site (botão) ou copiando o prompt pra qualquer IA e colando a resposta.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import marcas_seguras

TIPOS = {"pessoa": "👤", "lugar": "📍", "objeto": "🔧", "documento": "📄", "cena": "🎬", "veiculo": "🚗", "outro": "🖼"}
_MIDIA_ID = re.compile(r"\[\s*([MIT]\d+)", re.I)


# ------------------------------------------------------------------ o roteiro em frases
def frases(roteiro: str) -> List[Dict[str, Any]]:
    """[{n, ini (onde a frase começa no roteiro), texto (sem marcas), midias (IDs já marcados nela)}].
    Só conta frase com pelo menos 3 palavras (a linha só com [[INSCREVA]] não é frase)."""
    out: List[Dict[str, Any]] = []
    chamadas = [(c.start(), c.end()) for c in re.finditer(r"\[\[.*?\]\]", roteiro or "", re.S)]  # [[VENDA: …]] não é frase
    for m in re.finditer(r"[^\n.!?…]+(?:[.!?…]+[\"”»')]*)?", roteiro or ""):
        bruto = m.group(0)
        if any(a <= m.start() < b or a <= m.end() - 1 < b for a, b in chamadas):
            continue
        txt = re.sub(r"\s+", " ", marcas_seguras.MARCA.sub(" ", bruto)).strip()
        mids = [x.upper() for x in _MIDIA_ID.findall(bruto)]
        if len(txt.split()) < 3:
            continue
        ini = m.start() + (len(bruto) - len(bruto.lstrip()))
        out.append({"n": len(out) + 1, "ini": ini, "texto": txt, "midias": mids})
    # marca sozinha numa linha ANTES da frase conta como dessa frase
    for m in marcas_seguras.MARCA.finditer(roteiro or ""):
        mid = _MIDIA_ID.match(m.group(0))
        if not mid:
            continue
        prox = next((f for f in out if f["ini"] >= m.end()), None)
        if prox and mid.group(1).upper() not in prox["midias"] and not roteiro[m.end():prox["ini"]].strip():
            prox["midias"].append(mid.group(1).upper())
    return out


def _imagens(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    import dossies as ds
    return [m for m in p.get("midias") or [] if m["tipo"] in ("foto", "video") and not m.get("descartada")
            and not m.get("duplicada_de")]


def _descr(m: Dict[str, Any]) -> str:
    import dossies as ds
    d = ds.o_que_e(m)[:260]
    if m.get("pergunta_alvo"):
        d = f"[pra: {m['pergunta_alvo']}] " + d
    return d


def _texto_voz(p: Dict[str, Any]) -> str:
    res = p.get("resultado") or {}
    return res.get("roteiro_final") or marcas_seguras.MARCA.sub("", res.get("roteiro") or "")


# ------------------------------------------------------------------ 1 · perguntas
def prompt_perguntas(p: Dict[str, Any]) -> str:
    roteiro = _texto_voz(p).strip()
    if not roteiro:
        raise ValueError("Ainda não tem roteiro.")
    imgs = _imagens(p)
    L = ["Você é o editor de um vídeo do YouTube. Leia o ROTEIRO abaixo (o texto narrado) e a lista das IMAGENS que eu já "
         "tenho. Depois, me PERGUNTE que fotos eu tenho (ou consigo achar) pra ilustrar o vídeo com imagens reais.",
         "",
         "## Como perguntar",
         "- Pergunte só sobre coisas que estão NO ROTEIRO e ficam muito melhores com imagem real: pessoas citadas pelo nome, "
         "lugares (cidade, casa, rua, prédio, cena do crime), objetos, documentos (cartas, jornais, fichas, processos), "
         "veículos, produtos, logotipos, mapas, prints, fotos de época — vale pra qualquer nicho.",
         "- UMA pergunta por pessoa/lugar/coisa (não repita). Ordene pela importância no vídeo (quanto aparece e quanto pesa).",
         "- Se eu já tenho imagem daquilo (lista abaixo), ponha os IDs em \"ja_tem\" e só pergunte se valeria outra (outra "
         "época, outro ângulo, o lugar por dentro…) — senão, não pergunte.",
         "- Entre 5 e 25 perguntas. Escreva as perguntas em PORTUGUÊS, curtas e diretas (ex.: \"Você tem foto de Helen "
         "List, a esposa?\"), mesmo que o roteiro esteja em outro idioma.",
         "- \"trecho\": uma frase curta COPIADA do roteiro onde aquilo aparece. \"vezes\": quantas vezes (mais ou menos) o "
         "roteiro fala daquilo. \"dica\": onde costuma ter essa foto (ex.: arquivo de jornal da época, Find a Grave, site "
         "da prefeitura, Google Street View) — curta.",
         "",
         "## Imagens que eu já tenho",
         *([f"- {m['id']}: {_descr(m)}" for m in imgs[:200]] or ["(nenhuma)"]),
         "",
         "## Roteiro",
         roteiro[:60000],
         "",
         "## Resposta — SOMENTE um JSON válido, assim:",
         json.dumps({"perguntas": [{"tipo": "pessoa | lugar | objeto | documento | cena | veiculo | outro",
                                    "alvo": "quem/o quê (ex.: Helen List)", "pergunta": "Você tem foto de …?",
                                    "por_que": "por que vale a imagem (curto)", "trecho": "frase exata do roteiro",
                                    "vezes": 4, "dica": "onde achar",
                                    "busca": "termo pra buscar a foto no Bing/Google (ex.: Linda Patrik Unabomber)",
                                    "ja_tem": ["I3"]}]}, ensure_ascii=False, indent=2),
         "\"busca\": o que digitar no Bing/Google Imagens pra achar ESSA foto: o nome + o termo do caso que desambigua "
         "(ex.: \"Linda Patrik Unabomber\", \"Kaczynski cabin Montana\"), SEMPRE EM INGLÊS (é onde se acha mais foto) — "
         "nome próprio fica como é. 2 a 6 palavras."]
    return "\n".join(L)


def ler_perguntas(texto: str, p: Dict[str, Any]) -> List[Dict[str, Any]]:
    import json_ia
    try:
        d = json_ia.carregar(texto)
    except ValueError as exc:
        raise ValueError(f"Não consegui ler o JSON: {exc}") from exc
    lista = d.get("perguntas") if isinstance(d, dict) else d
    if not isinstance(lista, list) or not lista:
        raise ValueError("O JSON não tem \"perguntas\".")
    ids = {m["id"].upper() for m in p.get("midias") or []}
    velhas = {(q.get("alvo") or "").lower(): q for q in (p.get("fotos_roteiro") or {}).get("perguntas") or []}
    out = []
    for k, q in enumerate(lista[:40]):
        if not isinstance(q, dict) or not str(q.get("pergunta") or q.get("alvo") or "").strip():
            continue
        tipo = str(q.get("tipo") or "outro").strip().lower().split()[0].replace("í", "i")
        alvo = str(q.get("alvo") or "").strip()[:120]
        antiga = velhas.get(alvo.lower()) or {}
        out.append({"id": antiga.get("id") or f"P{k + 1}", "tipo": tipo if tipo in TIPOS else "outro", "alvo": alvo,
                    "pergunta": str(q.get("pergunta") or f"Você tem foto de {alvo}?").strip()[:300],
                    "por_que": str(q.get("por_que") or "").strip()[:300], "trecho": str(q.get("trecho") or "").strip()[:300],
                    "dica": str(q.get("dica") or "").strip()[:200],
                    "busca": " ".join(str(q.get("busca") or "").split())[:120] or antiga.get("busca") or "",
                    "vezes": int(q.get("vezes") or 0) if str(q.get("vezes") or "0").isdigit() else 0,
                    "ja_tem": [str(x).strip("[] ").upper() for x in q.get("ja_tem") or [] if str(x).strip("[] ").upper() in ids][:10],
                    "pulada": bool(antiga.get("pulada"))})
    usados = set()
    for q in out:  # ids únicos
        if q["id"] in usados:
            q["id"] = f"P{max([int(x[1:]) for x in usados if x[1:].isdigit()] + [0]) + 1}"
        usados.add(q["id"])
    if not out:
        raise ValueError("Nenhuma pergunta válida no JSON.")
    return out


# ------------------------------------------------------------------ 2 · posicionar
def prompt_posicionar(p: Dict[str, Any], modo: str = "todas") -> str:
    res = p.get("resultado") or {}
    fr = frases(res.get("roteiro") or "")
    if not fr:
        raise ValueError("Ainda não tem roteiro.")
    imgs = _imagens(p)
    marcadas = {x for f in fr for x in f["midias"]}
    alvo = [m for m in imgs if modo != "novas" or m["id"].upper() not in marcadas]
    if not alvo:
        raise ValueError("Não tem imagem nova pra posicionar (todas já estão no roteiro)." if modo == "novas"
                         else "Este modelo ainda não tem imagens.")
    import roteiro_partes
    L = ["Você é o editor de um vídeo do YouTube. Abaixo está o roteiro dividido em FRASES numeradas e as IMAGENS que eu "
         "tenho. Decida em quais frases cada imagem aparece: ela entra no começo da frase e fica na tela enquanto a frase é "
         "narrada.",
         "",
         "## Regras",
         "- " + roteiro_partes.REGRA,
         "- No máximo 1 imagem por frase. Frases com \"(já tem I3)\" já têm imagem — não use essas.",
         "- Só ponha a imagem onde a frase fala MESMO daquilo (a pessoa, o lugar, o objeto, o documento) ou do momento direto "
         "ligado a ele (ex.: a casa quando a frase fala do crime que aconteceu nela). Nunca a foto de uma pessoa numa frase "
         "sobre outra pessoa.",
         "- Imagens com \"[pra: …]\" eu enviei respondendo a uma pergunta sobre aquilo — dê prioridade a elas nesses trechos.",
         "- Espalhe pelo vídeo inteiro (começo, meio e fim), sem amontoar: a mesma imagem com pelo menos 3 frases de distância.",
         "- Imagem que não combina com nenhuma frase: deixe de fora (não force).",
         "",
         "## Imagens" + (" (posicione só estas — as outras já estão no roteiro)" if modo == "novas" else ""),
         *[f"- {m['id']}: {_descr(m)}" for m in alvo[:200]],
         "",
         "## Roteiro em frases",
         *[f"S{f['n']}: {f['texto'][:400]}" + (f" (já tem {', '.join(f['midias'])})" if f["midias"] else "") for f in fr],
         "",
         "## Resposta — SOMENTE um JSON válido, assim (os números são os das frases S…):",
         json.dumps({"usos": [{"midia": "I9", "frases": [12, 40, 88]}, {"midia": "I3", "frases": [5, 31]}]}, ensure_ascii=False)]
    return "\n".join(L)


def aplicar_posicoes(roteiro: str, resposta: str, ids_validos: set) -> Tuple[str, Dict[str, Any]]:
    """Põe as marcas nas frases que a IA escolheu. → (roteiro novo, {postas, ignoradas, por_imagem})."""
    import json_ia
    try:
        d = json_ia.carregar(resposta)
    except ValueError as exc:
        raise ValueError(f"Não consegui ler o JSON: {exc}") from exc
    usos = d.get("usos") if isinstance(d, dict) else d
    if not isinstance(usos, list):
        raise ValueError("O JSON não tem \"usos\".")
    fr = frases(roteiro)
    por_n = {f["n"]: f for f in fr}
    ocupada = {f["n"] for f in fr if f["midias"]}
    onde: Dict[str, List[int]] = {}
    for f in fr:
        for x in f["midias"]:
            onde.setdefault(x, []).append(f["n"])
    novas: Dict[int, str] = {}
    ignoradas = 0
    for u in usos:
        if not isinstance(u, dict):
            continue
        mid = str(u.get("midia") or "").strip("[] ").upper()
        if mid not in ids_validos:
            ignoradas += len(u.get("frases") or [])
            continue
        for n in u.get("frases") or []:
            try:
                n = int(str(n).strip().lstrip("Ss"))
            except ValueError:
                ignoradas += 1
                continue
            if n not in por_n or n in ocupada or n in novas or any(abs(n - x) < 3 for x in onde.get(mid, [])):
                ignoradas += 1
                continue
            novas[n] = mid
            onde.setdefault(mid, []).append(n)
    texto = roteiro
    for n in sorted(novas, reverse=True):
        ini = por_n[n]["ini"]
        texto = texto[:ini] + f"[{novas[n]}] " + texto[ini:]
    cont: Dict[str, int] = {}
    for mid in novas.values():
        cont[mid] = cont.get(mid, 0) + 1
    return texto, {"postas": len(novas), "ignoradas": ignoradas, "por_imagem": cont}


def uso_das_imagens(p: Dict[str, Any]) -> Dict[str, int]:
    """Quantas vezes cada imagem está marcada no roteiro."""
    cont: Dict[str, int] = {}
    for m in marcas_seguras.MARCA.finditer((p.get("resultado") or {}).get("roteiro") or ""):
        i = _MIDIA_ID.match(m.group(0))
        if i:
            cont[i.group(1).upper()] = cont.get(i.group(1).upper(), 0) + 1
    return cont


# ------------------------------------------------------------------ 🔎 buscar as fotos (Bing + Google Modo IA)
MOTORES = ("bing", "google")
BUSCA: Dict[str, Dict[str, Any]] = {}  # {pid: {ativo, msg, feitas, total, achadas, erro}} — em segundo plano


def termo_da_pergunta(p: Dict[str, Any], q: Dict[str, Any]) -> str:
    """O termo de busca: o que a IA escreveu ("Linda Patrik Unabomber"); senão o NOME da pessoa/lugar (nome próprio
    funciona em qualquer língua — a descrição em português, ", o irmão", fica de fora)."""
    if (q.get("busca") or "").strip():
        return q["busca"].strip()
    return re.split(r"[,(—–-]| o | a | do | da ", " " + (q.get("alvo") or q.get("pergunta") or "") + " ")[0].strip()[:120]


def termos_em_ingles(p: Dict[str, Any], qs: List[Dict[str, Any]], job: Optional[str] = None) -> Dict[str, str]:
    """🌐 As perguntas sem termo: a IA escreve a busca EM INGLÊS (nome + o termo do caso que desambigua).
    {} sem IA — aí vai só o nome (ver termo_da_pergunta)."""
    import ia_servico as ia
    if not qs or not ia.ativo("buscas"):
        return {}
    import dossies as ds
    from ia_midia import _S, _lista, _obj
    system = ("Você escreve termos de busca de IMAGEM (Bing/Google Imagens) SEMPRE EM INGLÊS: o nome próprio como é + 1 a 3 "
              "palavras em inglês do caso que desambiguam (ex.: \"Linda Patrik Unabomber\", \"Kaczynski cabin Montana\", "
              "\"Westfield New Jersey List mansion 1971\"). 2 a 6 palavras. Mantenha o \"id\".")
    linhas = [f"{q['id']}: {q.get('alvo') or ''} — {q.get('pergunta') or ''}" + (f" (trecho: {q['trecho'][:120]})" if q.get("trecho") else "")
              for q in qs]
    r = ia.chamar("buscas", system, f"Tema do vídeo: {ds.nome_do_projeto(p)}\n\n" + "\n".join(linhas),
                  _obj({"termos": _lista(_obj({"id": _S, "busca": _S}))}), max_tokens=2000, effort="low", job=job)
    ids = {q["id"] for q in qs}
    return {str(x.get("id")): " ".join(str(x.get("busca") or "").split())[:120]
            for x in (r or {}).get("termos") or [] if str(x.get("id")) in ids and str(x.get("busca") or "").strip()}


def buscar_fotos(base: str, pid: str, pedidos: List[Dict[str, Any]], motores: List[str], quantidade: int = 4,
                 trava=None) -> Dict[str, Any]:
    """pedidos = [{"id": "P3", "busca": "termo (opcional)"}]. Pesquisa cada termo nos buscadores (um navegador por
    buscador, todos os termos na mesma aba), baixa até `quantidade` fotos por buscador e põe no modelo como
    resposta da pergunta (🔎 "a conferir"). Repetidas (iguais a uma foto que já está no modelo) ficam de fora."""
    import contextlib
    import dossies as ds
    import buscador_imagens_unificado as bu
    trava = trava or contextlib.nullcontext()
    estado = BUSCA.setdefault(pid, {})
    with trava:
        p = ds.carregar(base, pid)
    qs = {q["id"]: q for q in (p.get("fotos_roteiro") or {}).get("perguntas") or []}
    termos: Dict[str, str] = {}
    for ped in pedidos:
        q = qs.get(str(ped.get("id") or ""))
        if q and not q.get("pulada"):
            if (ped.get("busca") or "").strip():
                q["busca"] = " ".join(str(ped["busca"]).split())[:120]
            termos[q["id"]] = termo_da_pergunta(p, q)
    if not termos:
        raise ValueError("Nenhuma pergunta pra buscar.")
    sem = [qs[i] for i in termos if not (qs[i].get("busca") or "").strip()]
    if sem:  # 🌐 sem termo: a IA escreve em inglês (e fica guardado na pergunta)
        estado.update(ativo=True, msg="🌐 a IA está escrevendo os termos em inglês…")
        novos_t = termos_em_ingles(p, sem, job=pid)
        termos.update(novos_t)
        if novos_t:
            with trava:
                q2 = ds.carregar(base, pid)
                for x in (q2.get("fotos_roteiro") or {}).get("perguntas") or []:
                    if x["id"] in novos_t:
                        x["busca"] = novos_t[x["id"]]
                ds.salvar(base, q2)
    motores = [m for m in motores if m in MOTORES] or ["bing"]
    import ia_servico
    conferir_ia = ia_servico.ativo("dossie_imagens")
    nome_m = {"bing": "Bing", "google": "Google (Modo IA)"}
    t0 = time.time()
    pp = {qid: {"st": "fila", "achou": {}, "fotos": 0, "termo": termos[qid], "alvo": qs[qid].get("alvo") or qid} for qid in termos}
    estado.update(ativo=True, inicio=t0, etapa="pesquisa", passo=0, passos=len(termos) * len(motores) + len(termos) + (1 if conferir_ia else 0),
                  atual="começando…", msg="🔎 buscando…", feitas=0, total=len(termos), achadas=0, erro="", por_pergunta=pp, eta_s=None)

    def avancar(n: int = 1, atual: str = "") -> None:
        estado["passo"] = min(estado["passos"], estado["passo"] + n)
        if atual:
            estado["atual"] = atual
        gasto = time.time() - t0
        estado["eta_s"] = round(gasto / estado["passo"] * (estado["passos"] - estado["passo"])) if estado["passo"] else None
        estado["msg"] = estado["atual"]

    # o que já existe no modelo (pra não trazer a mesma foto de novo)
    assin = []
    for m in p.get("midias") or []:
        cam = ds.caminho_midia(base, p, m)
        if cam and m.get("tipo") == "foto":
            a = bu.assinatura_visual(cam)
            if a is not None:
                assin.append(a)
    achados: Dict[str, List[Any]] = {qid: [] for qid in termos}
    erros = []
    ids = list(termos)
    for motor in motores:
        # Bing: de 4 em 4 termos no mesmo navegador (dá pra mostrar o andamento); Google: um por vez (o app tem fila)
        passo_lote = 1 if motor == "google" else 4
        for k in range(0, len(ids), passo_lote):
            grupo = ids[k:k + passo_lote]
            for qid in grupo:
                pp[qid]["st"] = "pesquisando"
            estado["atual"] = (f"🔎 {nome_m[motor]} · termo {k + 1}" + (f"–{k + len(grupo)}" if len(grupo) > 1 else "")
                               + f" de {len(ids)}: " + " · ".join(f"“{termos[q]}”" for q in grupo))
            estado["msg"] = estado["atual"]
            r = bu.buscar_lote(motor, [termos[q] for q in grupo], limit=max(quantidade * 2, 6), orientation="any")
            if r.get("erro_geral"):
                erros.append(f"{nome_m[motor]}: {str(r['erro_geral'])[:160]}")
            for qid in grupo:
                imgs = bu.sem_marca_dagua(r["por_termo"].get(bu._norm(termos[qid])) or [])
                achados[qid] += [(motor, im) for im in imgs]
                pp[qid]["achou"][motor] = len(imgs)
                pp[qid]["st"] = "fila" if motor != motores[-1] else ("achou" if achados[qid] else "nada")
            avancar(len(grupo))
    pasta = ds.pasta_midias(base, pid)
    os.makedirs(pasta, exist_ok=True)
    novos: List[str] = []
    estado["etapa"] = "download"
    for n, (qid, lista) in enumerate(achados.items(), start=1):
        q = qs[qid]
        if not lista:
            pp[qid]["st"] = "nada"
            avancar(1)
            continue
        pp[qid]["st"] = "baixando"
        estado.update(atual=f"⬇ baixando as fotos de {q.get('alvo') or qid} ({n}/{len(achados)})", feitas=n - 1)
        estado["msg"] = estado["atual"]
        por_motor: Dict[str, int] = {}
        vistos = set()
        for motor, im in lista:
            if por_motor.get(motor, 0) >= quantidade or im.original_url in vistos:
                continue
            vistos.add(im.original_url)
            try:
                cam = bu.baixar_imagem(im, pasta, stem=f"busca_{qid}_{motor}_{len(vistos)}_{uuid.uuid4().hex[:4]}", timeout_s=30)
            except Exception:  # noqa: BLE001 — essa não baixou: vai a próxima
                continue
            a = bu.assinatura_visual(cam)
            if a is not None and any(bu.parecidas(a, b) for b in assin):
                try:
                    os.remove(cam)
                except OSError:
                    pass
                continue
            if a is not None:
                assin.append(a)
            with trava:
                p = ds.carregar(base, pid)
                m = ds.adicionar_midia(p, tipo="foto", origem="busca", arquivo=os.path.basename(cam), url=im.source_page or "",
                                       nome=(im.title or q.get("alvo") or "")[:200],
                                       og={"titulo": im.title or "", "descricao": f"busca {motor}: {termos[qid]}"},
                                       descricao=q.get("alvo") or "", usar="ambos")
                m.update(pergunta=qid, pergunta_alvo=(q.get("alvo") or "")[:120], a_conferir=True, buscador=motor)
                for x in (p.get("fotos_roteiro") or {}).get("perguntas") or []:  # guarda o termo usado
                    if x["id"] == qid:
                        x["busca"] = termos[qid]
                ds.salvar(base, p)
            novos.append(m["id"])
            por_motor[motor] = por_motor.get(motor, 0) + 1
            pp[qid]["fotos"] += 1
            estado["achadas"] = len(novos)
        pp[qid]["st"] = "pronto" if pp[qid]["fotos"] else "nada"
        avancar(1)
    estado.update(feitas=len(achados), etapa="conferir")
    if novos and conferir_ia:  # 🤖 a ficha de cada uma (e tira lixo/anúncio)
        estado["atual"] = estado["msg"] = f"🤖 a IA está conferindo as {len(novos)} foto(s) (tira lixo/anúncio)…"
        try:
            ds.ia_analisar_imagens(base, pid, trava=trava, ids=novos)
        except Exception:  # noqa: BLE001
            pass
    avancar(estado["passos"])
    dur = time.time() - t0
    estado.update(ativo=False, etapa="fim", duracao_s=round(dur), atual="",
                  msg=f"✔ {len(novos)} foto(s) novas em {int(dur // 60)} min {int(dur % 60)} s — confira e tire as que não servem"
                  + (f" · ⚠ {'; '.join(erros)}" if erros else ""), erro="" if novos or not erros else "; ".join(erros))
    return {"novas": novos, "erros": erros}


def baixar_link(base: str, pid: str, url: str) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """🔗 Um link colado: link direto da imagem/vídeo (baixa) ou de uma página (pega a imagem do OG da página).
    → (nome do arquivo, tipo "foto"|"video", og ou None). Levanta ValueError se não deu."""
    import dossies as ds
    import vendas as vd
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("o link tem que começar com http:// ou https://")
    pasta = ds.pasta_midias(base, pid)
    os.makedirs(pasta, exist_ok=True)
    nome = f"link_{uuid.uuid4().hex[:6]}"
    try:  # 1) o próprio link é a foto/vídeo (o tipo vem do Content-Type)
        cam, tipo = vd.baixar_arquivo(url, pasta, nome)
        return os.path.basename(cam), tipo, None
    except vd.VendaError as exc:
        erro1 = str(exc)
    if vd.tipo_do_arquivo(url.split("?")[0]):  # 2) parece imagem mas o site barrou: baixador dos buscadores (referer, proxy)
        try:
            import buscador_imagens_unificado as bu
            im = bu.ImagemBuscador(title="", description="", source_page="", original_url=url, thumbnail_url="",
                                   width=None, height=None, query="", engine="")
            cam = bu.baixar_imagem(im, pasta, stem=nome, timeout_s=40)
            return os.path.basename(cam), "foto", None
        except Exception:  # noqa: BLE001
            pass
    try:  # 3) é uma página: a imagem do OG (a foto principal da matéria)
        html, final = vd.baixar_html(url, navegador=False)
        og = vd.ler_og(html, final)
    except vd.VendaError:
        raise ValueError(f"não consegui baixar ({erro1[:120]})")
    for u in (og.get("imagem"), og.get("video")):
        if u:
            try:
                cam, tipo = vd.baixar_arquivo(u, pasta, nome)
                return os.path.basename(cam), tipo, og
            except vd.VendaError:
                continue
    raise ValueError("a página não tem imagem principal — copie o link da própria imagem (botão direito → copiar endereço da imagem)")


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str) -> None:
    from flask import jsonify, request
    import dossies as ds
    import dossies_rotas

    def _carregar(pid: str):
        try:
            return ds.carregar(base_dir, pid)
        except ds.DossieError:
            return None

    def _corpo() -> Dict[str, Any]:
        return request.get_json(silent=True) or {}

    def _estado(p: Dict[str, Any]) -> Dict[str, Any]:
        fr = p.get("fotos_roteiro") or {}
        enviadas: Dict[str, List[str]] = {}
        for m in p.get("midias") or []:
            if m.get("pergunta"):
                enviadas.setdefault(m["pergunta"], []).append(m["id"])
        info = {m["id"]: {"url": ds.url_midia(p, m), "a_conferir": bool(m.get("a_conferir")),
                          "link": (m.get("url") or "")[:300], "da_pagina": bool(m.get("da_pagina")),
                          "buscador": m.get("buscador") or "", "fora": bool(m.get("descartada") or m.get("duplicada_de"))}
                for m in p.get("midias") or [] if m.get("pergunta")}
        return {"ok": True, "perguntas": fr.get("perguntas") or [], "enviadas": enviadas, "uso": uso_das_imagens(p),
                "midias": info, "busca": BUSCA.get(p["id"]) or None,
                "termos": {q["id"]: (q.get("busca") or "") for q in fr.get("perguntas") or []},
                "tem_roteiro": bool((p.get("resultado") or {}).get("roteiro")),
                "pode_desfazer": bool((p.get("resultado") or {}).get("roteiro_antes_fotos")),
                "imagens": len(_imagens(p)),
                "de_busca": sum(1 for m in p.get("midias") or [] if m.get("origem") == "busca"),
                "de_busca_conferir": sum(1 for m in p.get("midias") or [] if m.get("origem") == "busca" and m.get("a_conferir"))}

    @app.route("/modelos-video/<pid>/fotos-roteiro")
    def fotos_roteiro_estado(pid: str):
        p = _carregar(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        return jsonify(_estado(p))

    @app.route("/modelos-video/<pid>/fotos-roteiro/perguntas/prompt", methods=["POST"])
    def fotos_roteiro_perguntas_prompt(pid: str):
        p = _carregar(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            return jsonify({"ok": True, "prompt": prompt_perguntas(p)})
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400

    @app.route("/modelos-video/<pid>/fotos-roteiro/perguntas/ler", methods=["POST"])
    def fotos_roteiro_perguntas_ler(pid: str):
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            try:
                qs = ler_perguntas(str(_corpo().get("texto") or ""), p)
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 400
            p["fotos_roteiro"] = {"perguntas": qs, "gerado_em": time.time()}
            ds.marcar_mudanca(p, "📸 fotos pro roteiro", f"{len(qs)} perguntas")
            ds.salvar(base_dir, p)
            return jsonify(_estado(p))

    @app.route("/modelos-video/<pid>/fotos-roteiro/perguntas/<qid>", methods=["POST"])
    def fotos_roteiro_pergunta(pid: str, qid: str):
        """pular / voltar uma pergunta."""
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            q = next((x for x in ((p or {}).get("fotos_roteiro") or {}).get("perguntas") or [] if x["id"] == qid), None)
            if not q:
                return jsonify({"erro": "Pergunta não encontrada."}), 404
            q["pulada"] = bool(_corpo().get("pulada"))
            ds.salvar(base_dir, p)
            return jsonify(_estado(p))

    @app.route("/modelos-video/<pid>/fotos-roteiro/buscar", methods=["POST"])
    def fotos_roteiro_buscar(pid: str):
        """🔎 Busca as fotos de uma pergunta (ou de todas) no Bing / Google Modo IA — em segundo plano."""
        import threading
        p = _carregar(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        if (BUSCA.get(pid) or {}).get("ativo"):
            return jsonify({"erro": "Já tem uma busca rodando neste modelo — espere terminar."}), 409
        c = _corpo()
        pedidos = c.get("perguntas")
        if pedidos == "todas" or not pedidos:
            pedidos = [{"id": q["id"]} for q in (p.get("fotos_roteiro") or {}).get("perguntas") or [] if not q.get("pulada")]
        if not pedidos:
            return jsonify({"erro": "Não tem pergunta pra buscar — gere as perguntas primeiro."}), 400
        motores = [m for m in (c.get("motores") or ["bing", "google"]) if m in MOTORES]
        qtd = max(1, min(10, int(c.get("quantidade") or 4)))
        BUSCA[pid] = {"ativo": True, "msg": "🔎 começando…", "feitas": 0, "total": len(pedidos), "achadas": 0, "erro": ""}

        def rodar():
            try:
                buscar_fotos(base_dir, pid, pedidos, motores, qtd, trava=dossies_rotas._TRAVA)
            except Exception as exc:  # noqa: BLE001
                BUSCA[pid] = {"ativo": False, "msg": "", "erro": str(exc)[:300]}

        threading.Thread(target=rodar, daemon=True).start()
        return jsonify(_estado(p))

    @app.route("/modelos-video/<pid>/fotos-roteiro/link", methods=["POST"])
    def fotos_roteiro_link(pid: str):
        """🔗 Baixa UM link (a tela manda um por vez, pra mostrar o andamento) e põe no modelo — como envio manual:
        já conta como conferida. Com "pergunta", vira resposta dela."""
        c = _corpo()
        if not _carregar(pid):
            return jsonify({"erro": "Projeto não encontrado."}), 404
        url = str(c.get("url") or "").strip()
        try:
            arquivo, tipo, og = baixar_link(base_dir, pid, url)
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        qid = str(c.get("pergunta") or "")[:10]
        desc = str(c.get("descricao") or "").strip()[:2000]
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            q = next((x for x in (p.get("fotos_roteiro") or {}).get("perguntas") or [] if x["id"] == qid), None)
            m = ds.adicionar_midia(p, tipo=tipo, origem="url", url=url, arquivo=arquivo,
                                   nome=((og or {}).get("titulo") or url[-80:])[:200],
                                   og={"titulo": og.get("titulo"), "descricao": og.get("descricao")} if og and (og.get("titulo") or og.get("descricao")) else None,
                                   descricao=desc or ((q or {}).get("alvo") or ""), usar="ambos")
            if q:
                m.update(pergunta=qid, pergunta_alvo=(q.get("alvo") or "")[:120])
            if og:
                m["da_pagina"] = True  # 📄 veio da foto principal da página (pode não ser a que você queria)
            ds.salvar(base_dir, p)
        import ia_servico
        if ia_servico.ativo("dossie_imagens"):
            import threading
            threading.Thread(target=lambda: ds.ia_analisar_imagens(base_dir, pid, trava=dossies_rotas._TRAVA, ids=[m["id"]]),
                             daemon=True).start()
        return jsonify({"ok": True, "midia": {"id": m["id"], "tipo": tipo}, "da_pagina": bool(og)})

    @app.route("/modelos-video/<pid>/fotos-roteiro/conferidas", methods=["POST"])
    def fotos_roteiro_conferidas(pid: str):
        """✓ as fotos achadas foram conferidas (tira o 🔎 "a conferir")."""
        ids = {str(x).upper() for x in _corpo().get("ids") or []}
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            for m in p.get("midias") or []:
                if m["id"].upper() in ids:
                    m.pop("a_conferir", None)
            ds.salvar(base_dir, p)
            return jsonify(_estado(p))

    @app.route("/modelos-video/<pid>/fotos-roteiro/posicionar/prompt", methods=["POST"])
    def fotos_roteiro_posicionar_prompt(pid: str):
        p = _carregar(pid)
        if not p:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            return jsonify({"ok": True, "prompt": prompt_posicionar(p, str(_corpo().get("modo") or "todas"))})
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400

    def _gravar_roteiro(p: Dict[str, Any], novo: str, antes: Optional[str], hist: str) -> None:
        velho = p.get("resultado") or {}
        res = ds.roteiro_editado(p, novo)
        for k, v in velho.items():  # as marcas não mudam a fala: áudio, partes, "voltar"… continuam valendo
            if k not in res:
                res[k] = v
        res["avisos"] = [a for a in res.get("avisos") or [] if not a.startswith("📸")]
        if antes is None:
            res.pop("roteiro_antes_fotos", None)
        else:
            res["roteiro_antes_fotos"] = antes
        p["resultado"] = res
        ds.marcar_mudanca(p, "📸 fotos pro roteiro", hist)
        ds.salvar(base_dir, p)

    @app.route("/modelos-video/<pid>/fotos-roteiro/apagar-buscas", methods=["POST"])
    def fotos_roteiro_apagar_buscas(pid: str):
        """🗑 Apaga as fotos que vieram das 🔎 buscas automáticas (todas, ou só as ainda "a conferir"; ou de uma pergunta).
        As enviadas à mão e as das matérias ficam. Tira também as marcas delas do roteiro e do 🎭 elenco."""
        c = _corpo()
        so_conferir = bool(c.get("so_a_conferir"))
        pergunta = str(c.get("pergunta") or "")
        if (BUSCA.get(pid) or {}).get("ativo"):
            return jsonify({"erro": "Tem uma busca rodando — espere terminar."}), 409
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            if not p:
                return jsonify({"erro": "Projeto não encontrado."}), 404
            sai = [m for m in p.get("midias") or [] if m.get("origem") == "busca"
                   and (not so_conferir or m.get("a_conferir")) and (not pergunta or m.get("pergunta") == pergunta)]
            if not sai:
                return jsonify({"erro": "Não tem foto de busca automática pra apagar."}), 400
            ids = {m["id"].upper() for m in sai}
            for m in sai:
                cam = ds.caminho_midia(base_dir, p, m)
                if cam:
                    try:
                        os.remove(cam)
                    except OSError:
                        pass
            p["midias"] = [m for m in p["midias"] if m["id"].upper() not in ids]
            el = p.get("elenco")
            if el:  # 🎭 as fotos apagadas saem do elenco (pessoa sem foto nenhuma sai; local fica se tem descrição)
                for x in el.get("pessoas") or []:
                    x["fotos"] = [f for f in x.get("fotos") or [] if f.get("midia", "").upper() not in ids]
                el["pessoas"] = [x for x in el.get("pessoas") or [] if x["fotos"]]
                for x in el.get("locais") or []:
                    x["fotos"] = [f for f in x.get("fotos") or [] if str(f).upper() not in ids]
            rot = (p.get("resultado") or {}).get("roteiro") or ""
            tirou = 0
            if rot:
                padrao = re.compile(r"\[\s*(" + "|".join(sorted(ids)) + r")(?:\s[^\]\n]*)?\]\s?", re.I)
                novo, tirou = padrao.subn("", rot)
                if tirou:
                    _gravar_roteiro(p, novo, (p.get("resultado") or {}).get("roteiro_antes_fotos"),
                                    f"🗑 {len(ids)} foto(s) de busca apagadas ({tirou} marcas)")
                    p = _carregar(pid)
            ds.marcar_mudanca(p, "📸 fotos pro roteiro", f"🗑 {len(ids)} foto(s) das buscas automáticas apagadas")
            ds.salvar(base_dir, p)
            return jsonify({**_estado(p), "apagadas": len(ids), "marcas_tiradas": tirou})

    @app.route("/modelos-video/<pid>/fotos-roteiro/posicionar/ler", methods=["POST"])
    def fotos_roteiro_posicionar_ler(pid: str):
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            res = (p or {}).get("resultado") or {}
            if not res.get("roteiro"):
                return jsonify({"erro": "Ainda não tem roteiro."}), 400
            ids = {m["id"].upper() for m in _imagens(p)}
            try:
                novo, info = aplicar_posicoes(res["roteiro"], str(_corpo().get("texto") or ""), ids)
            except ValueError as exc:
                return jsonify({"erro": str(exc)}), 400
            if not info["postas"]:
                return jsonify({"erro": "Nenhuma marca nova coube (frases já ocupadas ou números errados).", **info}), 400
            _gravar_roteiro(p, novo, res.get("roteiro_antes_fotos") or res["roteiro"],
                            f"{info['postas']} marcas de imagem postas")
            return jsonify({**_estado(p), **info})

    @app.route("/modelos-video/<pid>/fotos-roteiro/desfazer", methods=["POST"])
    def fotos_roteiro_desfazer(pid: str):
        with dossies_rotas._TRAVA:
            p = _carregar(pid)
            antes = ((p or {}).get("resultado") or {}).get("roteiro_antes_fotos")
            if not antes:
                return jsonify({"erro": "Não tem posicionamento pra desfazer."}), 400
            _gravar_roteiro(p, antes, None, "↩ voltou às marcas de antes")
            return jsonify(_estado(p))
