"""📸 Fotos pro roteiro (v84_127) — passo OPCIONAL do 🕵️ Modelo de vídeo, depois que o roteiro está pronto.

1. ❓ A IA lê o roteiro e PERGUNTA que fotos você tem: das pessoas, lugares, objetos, documentos, cenas… que o roteiro
   cita (qualquer nicho). Você responde enviando as fotos de cada pergunta (com uma descrição) — ou outras imagens soltas.
2. 📍 A IA POSICIONA as imagens: o roteiro vai dividido em frases numeradas e ela diz em quais frases cada imagem entra.
   O site põe as marcas [I9] antes dessas frases (as marcas não são lidas pela voz) — e dá pra desfazer.

Os dois passos funcionam com a 🤖 IA do site (botão) ou copiando o prompt pra qualquer IA e colando a resposta.
"""
from __future__ import annotations

import json
import re
import time
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
                                    "vezes": 4, "dica": "onde achar", "ja_tem": ["I3"]}]}, ensure_ascii=False, indent=2)]
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
        return {"ok": True, "perguntas": fr.get("perguntas") or [], "enviadas": enviadas, "uso": uso_das_imagens(p),
                "tem_roteiro": bool((p.get("resultado") or {}).get("roteiro")),
                "pode_desfazer": bool((p.get("resultado") or {}).get("roteiro_antes_fotos")),
                "imagens": len(_imagens(p))}

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
