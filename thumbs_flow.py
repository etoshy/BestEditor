"""
🖼 thumbs_flow.py — as THUMBNAILS que a IA recomenda, geradas no Google Flow (v84_96)
===================================================================================

Onde a IA recomenda thumbnail (🕵️ Modelos de vídeo → "thumbnails"; 📜 Roteiro do YouTube → títulos/descrição;
📊 Analisador de canal → sugestões de vídeo), cada ideia vira um card com:
  • "texto"  — 2 a 4 palavras GRANDES que vão na miniatura;
  • "prompt" — a cena da imagem, em inglês, pro Flow (16:9, um assunto claro, contraste, espaço vazio pro texto, SEM texto
               escrito — o Flow erra letra; o site põe o texto por cima, com contorno, do jeito das thumbs de documentário).
Botão 🎨 Gerar no Flow (uma ou todas) — roda em segundo plano (🔔 avisa) e guarda:
  thumbs/<origem>_<id>/thumb_<n>_<t>.png      a imagem do Flow (limpa)
  thumbs/<origem>_<id>/thumb_<n>_<t>_final.jpg  1280×720 com o texto (pronta pra subir no YouTube)
"""
from __future__ import annotations

import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional

PASTA = "thumbs"
ORIGENS = ("dossie", "roteiro_yt", "canal", "avulso")  # 🖼 v84_368: "avulso" = thumbnail de qualquer vídeo (página própria)
_TRAVA = threading.Lock()

ESTILO_PADRAO = ("YouTube documentary thumbnail, 16:9, cinematic photo, one clear focal subject, dramatic high-contrast lighting, "
                 "shallow depth of field, strong emotion, clean background, large empty negative space on the {lado} third for a "
                 "big title, no text, no letters, no words, no watermark, no logo, no gore, no blood, monetization-friendly")


_INCOMUM = re.compile(r"atividade incomum|unusual activity|extens[õo]es do navegador|browser extensions", re.IGNORECASE)
MSG_INCOMUM = ("o Google Flow acusou “atividade incomum” (desconfiou da automação — nada foi cobrado). Parei as próximas. "
               "Espere ~1 hora e gere de novo, poucas de cada vez.")


class ThumbErro(Exception):
    pass


def _valido(origem: str, pid: str) -> bool:
    return origem in ORIGENS and bool(re.fullmatch(r"[A-Za-z0-9_\-]{3,64}", str(pid or "")))


def pasta(base: str, origem: str, pid: str) -> str:
    if not _valido(origem, pid):
        raise ThumbErro("Projeto inválido.")
    return os.path.join(base, PASTA, f"{origem}_{pid}")


def _arq(base: str, origem: str, pid: str) -> str:
    return os.path.join(pasta(base, origem, pid), "thumbs.json")


def carregar(base: str, origem: str, pid: str) -> Dict[str, Any]:
    try:
        with open(_arq(base, origem, pid), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"itens": []}
    except (OSError, ValueError):
        return {"itens": []}


def salvar(base: str, origem: str, pid: str, d: Dict[str, Any]) -> None:
    os.makedirs(pasta(base, origem, pid), exist_ok=True)
    tmp = _arq(base, origem, pid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    arquivo_seguro.trocar(tmp, _arq(base, origem, pid))


def normalizar(x: Any) -> Optional[Dict[str, str]]:
    """Uma ideia de thumbnail (texto solto também vale: vira a "ideia")."""
    if isinstance(x, str):
        x = {"ideia": x}
    if not isinstance(x, dict):
        return None
    ideia = " ".join(str(x.get("ideia") or x.get("descricao") or x.get("thumb") or "").split())[:400]
    texto = " ".join(str(x.get("texto") or x.get("texto_na_thumb") or "").split())[:40]
    prompt = " ".join(str(x.get("prompt") or x.get("prompt_imagem") or "").split())[:900]
    if not (ideia or prompt):
        return None
    out = {"ideia": ideia or prompt, "texto": texto, "prompt": prompt}
    if str(x.get("modo") or x.get("estilo") or "").lower() in ("albert", "palavra", "palavra_gigante"):  # 🔥 v84_417
        out["modo"] = "albert"
        out["texto"] = re.sub(r"[^\w-]", "", (texto or str(x.get("palavra") or "")).split()[0] if (texto or x.get("palavra")) else "",
                              flags=re.UNICODE).upper()[:14]
    tits = [" ".join(str(t).split())[:100] for t in (x.get("titulos") or []) if str(t).strip()][:3]
    if tits:  # 🏷 v84_429: os títulos que combinam com ESTA thumbnail
        out["titulos"] = tits
    import estilos_arte
    if str(x.get("estilo_arte") or "") in estilos_arte.ESTILOS:  # 🎨 v84_397: o estilo próprio desta thumbnail
        out["estilo_arte"] = str(x["estilo_arte"])
    return out


def sincronizar(base: str, origem: str, pid: str, ideias: List[Any]) -> Dict[str, Any]:
    """Junta as ideias que a IA recomendou com as que já estão salvas (as geradas/editadas ficam)."""
    with _TRAVA:
        d = carregar(base, origem, pid)
        itens = d.setdefault("itens", [])
        conhecidas = {i.get("ideia") for i in itens}
        prox = max([int(i.get("n") or 0) for i in itens] or [0]) + 1
        for x in ideias or []:
            n = normalizar(x)
            if n and n["ideia"] not in conhecidas:
                itens.append(dict(n, n=prox, status="", imagem="", final="", erro="", da_ia=True))
                conhecidas.add(n["ideia"])
                prox += 1
        salvar(base, origem, pid, d)
        return d


# ------------------------------------------------------------------ ✏ v84_433: pedir uma mudança numa thumb ("em pé", "uma criança")
def ajustar(base: str, origem: str, pid: str, n: int, pedido: str, chamar=None) -> Dict[str, Any]:
    """A IA reescreve o prompt DESTA thumb aplicando o pedido (pessoa, idade, pose, roupa, cenário, objeto, expressão…) e
    mantendo o resto da cena, a ironia, a palavra e o estilo. Devolve os itens."""
    pedido = " ".join(str(pedido or "").split())[:600]
    if not pedido:
        raise ThumbErro("Escreva o que mudar (ex.: \"em vez da mulher velha, uma garota\", \"em pé, não deitada\").")
    d = carregar(base, origem, pid)
    it = next((i for i in d.get("itens") or [] if int(i.get("n") or 0) == int(n)), None)
    if not it:
        raise ThumbErro("Thumbnail não encontrada.")
    import ia_servico as ia
    if chamar is None:
        motivo = ia.motivo_desligado("roteiros")
        if motivo:
            raise ThumbErro("IA: " + motivo)
    from ia_midia import _S, _obj
    system = ("Você ajusta o PROMPT de imagem de UMA thumbnail de YouTube (vai pro Google Flow). Aplique EXATAMENTE a mudança "
              "pedida (pessoa, idade, gênero, pose, roupa, expressão, cenário, objeto, enquadramento, luz…) e mantenha TODO o "
              "resto: a mesma cena, a mesma ironia/ideia, o mesmo enquadramento quando não pedirem pra mudar. "
              "O prompt continua EM INGLÊS, só a cena (o estilo de arte o site põe; NÃO descreva letras nem texto na imagem). "
              "Se o pedido trocar a pessoa, ajuste tudo que dependia dela (pose, roupa, expressão) pra ficar coerente. "
              "Criança: descreva de forma neutra e apropriada (roupa comum, situação segura). Sem violência gráfica. "
              "\"ideia\": a ideia da thumb em 1 frase em português, já com a mudança. \"texto\": a palavra/texto da thumb — "
              "igual ao de antes, a menos que o pedido mande mudar. Responda só o JSON.")
    ant = it.get("ajustes") or []
    conteudo = (f"IDEIA ATUAL: {it.get('ideia') or ''}\nTEXTO ATUAL: {it.get('texto') or ''}\n"
                f"PROMPT ATUAL (inglês): {it.get('prompt') or it.get('ideia') or ''}\n"
                + (("PEDIDOS ANTERIORES (continuam valendo): " + " | ".join(ant[-4:]) + "\n") if ant else "")
                + f"\nMUDANÇA PEDIDA AGORA: {pedido}")
    with ia.rotulo("✏ Ajustar thumb"):
        r = (chamar or ia.chamar)("roteiros", system, conteudo, schema=_obj({"prompt": _S, "ideia": _S, "texto": _S}),
                                  max_tokens=1200, effort="low", timeout=180, cache_local=False)
    if not isinstance(r, dict) or not str(r.get("prompt") or "").strip():
        raise ThumbErro("a IA não devolveu o prompt novo (veja as últimas chamadas em 🤖 IA)")
    with _TRAVA:
        d = carregar(base, origem, pid)
        it = next((i for i in d.get("itens") or [] if int(i.get("n") or 0) == int(n)), None)
        if not it:
            raise ThumbErro("Thumbnail não encontrada.")
        it["prompt_antes"] = it.get("prompt") or ""
        it["prompt"] = " ".join(str(r["prompt"]).split())[:900]
        if str(r.get("ideia") or "").strip():
            it["ideia"] = " ".join(str(r["ideia"]).split())[:400]
        if str(r.get("texto") or "").strip():
            it["texto"] = " ".join(str(r["texto"]).split())[:40]
        it["ajustes"] = (ant + [pedido])[-8:]
        salvar(base, origem, pid, d)
        return d


def editar(base: str, origem: str, pid: str, n: int, **campos: Any) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(base, origem, pid)
        it = next((i for i in d.get("itens") or [] if int(i.get("n") or 0) == int(n)), None)
        if campos.get("novo"):
            prox = max([int(i.get("n") or 0) for i in d.get("itens") or []] or [0]) + 1
            nn = normalizar(campos) or {"ideia": "thumbnail", "texto": "", "prompt": ""}
            d.setdefault("itens", []).append(dict(nn, n=prox, status="", imagem="", final="", erro=""))
        elif campos.get("apagar") and it:
            d["itens"] = [i for i in d["itens"] if i is not it]
        elif it:
            for k, lim in (("texto", 40), ("prompt", 900), ("ideia", 400)):
                if k in campos:
                    it[k] = " ".join(str(campos[k] or "").split())[:lim]
            if "estilo_arte" in campos:  # 🎨 v84_397: "" = o do canal
                import estilos_arte
                v = str(campos["estilo_arte"] or "")
                it["estilo_arte"] = v if v in estilos_arte.ESTILOS else ""
            if "titulos" in campos:  # 🏷 v84_429
                it["titulos"] = [" ".join(str(t).split())[:100] for t in (campos["titulos"] or []) if str(t).strip()][:3]
            if "modo" in campos:  # 🔥 v84_417: "albert" (palavra na imagem) ou "" (texto por cima, o de sempre)
                it["modo"] = "albert" if campos["modo"] == "albert" else ""
            if ("texto" in campos or "modo" in campos) and it.get("imagem") and os.path.isfile(it["imagem"]):  # refaz a final na hora
                it["final"] = compor(it["imagem"], "" if it.get("modo") == "albert" else (it.get("texto") or ""),
                                     it["imagem"].rsplit(".", 1)[0] + "_final.jpg")
        salvar(base, origem, pid, d)
        return d


def prompt_flow(it: Dict[str, Any], lado: str = "right", estilo: str = "") -> str:
    """A cena (prompt da IA, em inglês, ou a ideia) + o estilo de thumbnail (o do canal, quando tem — v84_368)."""
    cena = (it.get("prompt") or it.get("ideia") or "").strip().rstrip(".,")
    lead = ""
    if it.get("estilo_arte"):  # 🎨 v84_397: a thumbnail tem estilo próprio (vale mais que o do canal)
        import estilos_arte
        estilo = estilos_arte.estilo_thumb(str(it["estilo_arte"])) or estilo
        lead = estilos_arte.lead(str(it["estilo_arte"]))
    elif estilo.startswith("@@"):  # o estilo do canal com o começo marcado (estilo_da_marca)
        lead, _, estilo = estilo[2:].partition("@@")
    elif "@@" in estilo:
        estilo = estilo.replace("@@", "")
    # 🎨 v84_398: o estilo ABRE o prompt — o gerador dá mais peso ao começo
    est = (estilo or ESTILO_PADRAO).format(lado=lado)
    if it.get("modo") == "albert":  # 🔥 v84_417: a palavra gigante vai DENTRO da imagem, atrás do personagem
        palavra = str(it.get("texto") or "").upper().strip()
        est = re.sub(r"(?i)large empty negative space on the \w+ third for a (big )?title( added later)?|\bno (text|letters|words)\b",
                     "", est)
        est = re.sub(r"\s*([,.])(\s*[,.])+", r"\1", est).strip(" ,.")
        letras = (f'Huge bold condensed capital letters spelling exactly "{palavra}" fill the whole width of the image behind '
                  "the main subject: SOLID, BRIGHT, fully saturated pure red (#E50914), 100% opaque, crisp sharp edges, the "
                  "brightest and most contrasting element of the image (a few small drips only at the bottom edge), set "
                  "against a darker background so it pops; the subject stands in the center IN FRONT of the word, covering "
                  "only part of the middle letters, the word still easy to read. Only that one word, no other text"
                  if palavra else "")
        # 🎨 v84_419: o estilo de arte do canal ABRE o prompt (no fim, depois das letras, o Flow ignorava e fazia foto)
        return (f"{lead + ': ' if lead else ''}{est}. SCENE: {cena}. The absurd/ironic element of the scene is big, obvious "
                f"and readable at thumbnail size; centered composition, high contrast. {letras}. "
                "Keep EXACTLY the art style described at the start (same rendering, not a different style).").replace(". .", ".")
    return f"{lead + ': ' if lead else ''}{cena}. {est}"


# ------------------------------------------------------------------ 🎨 o estilo do canal (v84_368)
def estilo_da_marca(base: str, slug: str) -> str:
    """Thumbnail no jeito do canal do pacote: o style_lock do brand_guide + as regras de thumbnail (sem texto na imagem)."""
    if not slug:
        return ""
    try:
        import marca_visual
        gs = (marca_visual.carregar(base, slug)["guia"].get("generation_system")) or {}
    except Exception:  # noqa: BLE001 — canal apagado etc.
        return ""
    # 🎨 v84_394: o estilo de arte escolhido no canal pras thumbnails (ex.: 🖌 Rusty Art) vale por cima do pacote
    estilo = " ".join(str(gs.get("thumb_style_lock_en") or gs.get("style_lock_en") or "").split())
    if not estilo:
        return ""
    neg = " ".join(str(gs.get("thumb_negative_en") if "thumb_negative_en" in gs else gs.get("negative_prompt_global_en") or "").split())
    lead = str(gs.get("thumb_lead_en") or "")
    return (("@@" + lead + "@@" if lead else "") + "YouTube thumbnail, 16:9, one strong focal subject, strong emotion, dramatic light and clear contrast, large empty "
            "negative space on the {lado} third for a big title added later. " + estilo.replace("{", "(").replace("}", ")")
            + " No text, no letters, no words, no watermark, no logo." + (f" Avoid: {neg.replace('{', '(').replace('}', ')')}." if neg else ""))


def estilo(base: str, origem: str, pid: str) -> str:
    """O estilo das thumbs deste projeto: o do canal escolhido na thumb avulsa ou o do 🕵️ modelo (pacote de canal)."""
    d = carregar(base, origem, pid)
    slug = str(d.get("canal") or "")
    if not slug and origem == "dossie":
        try:
            import dossies as ds
            p = ds.carregar(base, pid)
            slug = str((ds.MODELOS.get((p.get("config") or {}).get("modelo") or "") or {}).get("identidade_visual") or "")
        except Exception:  # noqa: BLE001
            slug = ""
    return estilo_da_marca(base, slug)


# ------------------------------------------------------------------ 🔥 v84_417: estilo "palavra gigante + ironia"
N_ALBERT = 2  # além das 5 de sempre, 2 nesse estilo (0 = desliga — Configurações)
REGRA_ALBERT = (
    "ESTILO PALAVRA GIGANTE — PROVOCATIVO, no jeito do canal Albert (psicologia/comportamento, thumbs que explodem). "
    "COMO ELE PENSA (aplique ao ROTEIRO DESTE vídeo — não copie palavras nem cenas de exemplo nenhum):\n"
    "1) LEIA o roteiro e ache o NERVO: qual é a verdade incômoda, a acusação ou o tabu que o vídeo revela sobre quem "
    "assiste (\"você é X sem saber\", \"todo mundo faz Y e finge que não\")? A thumb vende ESSE incômodo.\n"
    "2) A PALAVRA: UMA só — um RÓTULO DE PESSOA, a acusação que o nervo faz a quem assiste: um defeito, um vício, uma "
    "condição, um tipo de gente que ninguém quer ser (adjetivo ou substantivo de pessoa: um \"-ado\", um \"-ista\", um "
    "\"-ente\"), ou o tabu cru. TESTE: quem lê pensa \"será que EU sou isso?\" e sente um soco. "
    "A palavra vem do NERVO do vídeo, NÃO das imagens do roteiro: NUNCA use um objeto, um lugar ou uma metáfora que o "
    "roteiro usou pra explicar (peneira, pedra, régua, ampulheta, caverna, náufrago, relógio, trilho — isso é ilustração, "
    "não acusação), nem conceito técnico ou abstrato (concessão, finitude, reflexão, linguagem, memória, silêncio). "
    "Nada de frase. 4 a 10 letras, MAIÚSCULAS, no idioma do vídeo.\n"
    "3) A CENA: o personagem do canal VIVENDO a palavra de forma LITERAL, absurda e meio escandalosa — o corpo, a roupa ou "
    "a situação dele É a metáfora (não \"ele ao lado de um objeto\"). Pergunte: se essa palavra virasse uma foto ridícula "
    "e chocante do personagem, como seria? Pra calibrar o NÍVEL (são de OUTROS temas — NÃO repita): ZOÓFILO = ele na "
    "cama abraçado com um cachorro; CANIBAL = o próprio rosto dele servido num prato; NECRÓFILO = ele casando com um "
    "esqueleto de véu; MORTE = sorrindo e fazendo joinha segurando uma corda.\n"
    "4) A IRONIA: expressão que CONTRADIZ a cena — sorriso largo, confiante ou debochado, olhando pra câmera, como se "
    "fosse normal.\n"
    "5) LEITURA EM 1 SEGUNDO no celular: um só assunto grande no centro, na frente da palavra; fundo simples ligado ao "
    "tema; o elemento absurdo GRANDE e óbvio.\n"
    "6) RUIM: cartaz/plaquinha escrita; objetos soltos sem relação com o corpo dele; personagem só posando; cena genérica; "
    "repetir a mesma palavra ou a mesma ideia de cena em duas thumbs; usar palavra que o roteiro não sustenta.\n"
    "7) Limites (monetizável): sugestivo, nunca explícito — nada de nudez, sexo, sangue de verdade, ferimento realista, "
    "pessoa real famosa ou crianças. O personagem é o do canal, no ESTILO DE ARTE do canal (que não muda).\n"
    "8) O TÍTULO conversa com a palavra: ele diz o ASSUNTO do vídeo e faz a MESMA acusação (a palavra ou o sentido dela "
    "aparece no título, como pergunta ou afirmação incômoda) — palavra e título são o mesmo soco.\n"
    "Antes de responder, liste pra você umas 10 palavras candidatas (rótulos de pessoa que o nervo do vídeo sustenta), "
    "dê a cada uma uma nota de 0 a 10 no teste \"será que eu sou isso?\", descarte objetos, metáforas, mornas e "
    "repetidas, e entregue SÓ as de nota mais alta e mais diferentes entre si, cada uma com uma cena própria.")


REGRA_TITULOS_THUMB = (
    "TÍTULOS DA THUMB: cada thumbnail vem com 2 títulos (\"titulos\") que servem pro VÍDEO e conversam com ESTA thumb. "
    "Ordem de prioridade: (1) o título diz DO QUE o vídeo trata — quem lê só o título entende o ASSUNTO (ex.: \"história "
    "universal\"), e ele cumpre a promessa do vídeo; (2) ele parte dos títulos do vídeo (os títulos originais são a base: "
    "ajuste um deles pra casar com a thumb, sem perder o assunto); (3) a thumb COMPLEMENTA: ela mostra a emoção/o choque, o "
    "título dá o assunto e a promessa. NUNCA explique a metáfora da thumb no título (thumb COSTURA num vídeo sobre história "
    "universal → ruim: \"Costura. Quem está fazendo esse remendo?\"; bom: \"A História Universal é um Remendo?\" ou "
    "\"História Universal. Quem Costurou Essa Versão?\"). A palavra da thumb só entra se couber natural no assunto. O jeito "
    "\"Assunto. Pergunta?\" usa o ASSUNTO real do vídeo antes do ponto (\"História Universal. Por Que Ela Não Existe?\"), "
    "não a palavra da thumb. Nas thumbs PALAVRA GIGANTE, pelo menos 1 dos 2 títulos junta o ASSUNTO com a ACUSAÇÃO da "
    "palavra (a palavra ou o sentido dela, dirigido a quem assiste — \"você\") — provocativo, sem perder o assunto. "
    "Até ~60 caracteres, no idioma do vídeo, honestos (o vídeo entrega).")


def ativo_albert(cfg: Optional[Dict[str, Any]] = None) -> int:
    """Quantas thumbs/títulos a mais no estilo palavra gigante (Configurações → 0 desliga)."""
    if cfg is None:
        try:
            from site_config import load_site_config
            cfg = load_site_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    try:
        return max(0, min(4, int((cfg or {}).get("thumbs_albert", N_ALBERT))))
    except (TypeError, ValueError):
        return N_ALBERT


# ------------------------------------------------------------------ 🤖 mais ideias pela IA (v84_368)
N_IDEIAS = 5
ANGULOS = ("rosto/emoção forte de uma pessoa da história", "um objeto-símbolo em close", "contraste/antes e depois ou dois lados",
           "a cena mais dramática do vídeo", "mistério: algo escondido ou uma pergunta visual")


def _schema_ideias() -> Dict[str, Any]:
    from ia_midia import _S, _lista, _obj
    return _obj({"thumbnails": _lista(_obj({"ideia": _S, "texto": _S, "prompt": _S, "angulo": _S, "modo": _S, "titulos": _lista(_S)}))})


def pedir_ideias(titulo: str, contexto: str, ja: List[Dict[str, Any]], n: int = N_IDEIAS, idioma: str = "pt",
                 estilo_canal: str = "", estilos: Optional[List[str]] = None, albert: int = 0,
                 estilo_albert: str = "marcado") -> List[Dict[str, str]]:
    """🤖 `n` thumbnails BEM diferentes entre si (e das que já existem). 🎨 v84_397 `estilos`: os estilos de arte
    marcados — as ideias são distribuídas entre eles (em rodízio) e a IA pensa a cena pra caber em cada um."""
    import estilos_arte
    estilos = [e for e in (estilos or []) if e in estilos_arte.ESTILOS]
    por_ideia = [estilos[k % len(estilos)] for k in range(n)] if estilos else []
    # 🎨 v84_431: as de palavra gigante seguem o estilo MARCADO abaixo (automático) ou o estilo do canal
    por_alb = [estilos[k % len(estilos)] for k in range(albert)] if estilos and estilo_albert != "canal" else []
    txt_alb = ("ESTILO DE ARTE de cada thumbnail palavra gigante, NA ORDEM (pense a cena pra funcionar nesse estilo; não descreva "
               "o estilo no prompt, o site põe): " + "; ".join(f"{k + 1}) {estilos_arte.ESTILOS[e]['nome']}"
                                                              for k, e in enumerate(por_alb))) if por_alb else ""

    def _pos_alb(lst):
        # 🔁 v84_435: a mesma PALAVRA em duas thumbs (ex.: PEDRA e PEDRA) — fica só a primeira
        vistas = {str(i.get("texto") or "").strip().upper() for i in ja if i.get("modo") == "albert" and i.get("texto")}
        unicas = []
        for t in lst:
            w = str(t.get("texto") or "").strip().upper()
            if w and w in vistas:
                continue
            vistas.add(w)
            unicas.append(t)
        lst[:] = unicas or lst[:1]
        for k, t in enumerate(lst):
            if por_alb:
                t["estilo_arte"] = por_alb[k % len(por_alb)]
            elif estilo_albert == "canal":
                t["estilo_arte"] = ""
        return lst
    import ia_servico as ia
    motivo = ia.motivo_desligado("roteiros")
    if motivo:
        raise ThumbErro("IA: " + motivo + " — ligue em 🤖 IA (📝 Roteiros direto na IA).")
    existentes = "\n".join(f"- {('[' + i['texto'] + '] ') if i.get('modo') == 'albert' and i.get('texto') else ''}{i.get('ideia')}"
                           for i in ja if i.get("ideia"))[:3000]
    if n <= 0 and albert:  # 🔥 v84_418: só as de palavra gigante
        system = f"""Você cria THUMBNAILS de YouTube que dão MUITO clique sem enganar. Para o vídeo abaixo, crie {albert} thumbnails
no estilo PALAVRA GIGANTE, cada uma com "modo": "albert".
{REGRA_ALBERT}
Para cada uma:
- "ideia": a cena e qual é a ironia/o choque (1 frase, em português);
- "texto": a PALAVRA gigante (só ela, no idioma do vídeo: {idioma});
- "prompt": a cena EM INGLÊS pro Google Flow (o personagem, o que o corpo/a situação dele mostra, a expressão irônica,
  o fundo) — NÃO descreva as letras, o site põe;
- "modo": "albert";
- "titulos": 2 títulos pra ESTA thumbnail. {REGRA_TITULOS_THUMB}
{('Estética do canal (a cena tem que caber nela): ' + estilo_canal.replace('@@', ' ')[:900]) if estilo_canal and not por_alb else ''}
{txt_alb}
Se o estilo é desenho/anime/cartoon, descreva o personagem como desenho (expressão, pose, roupa), sem detalhes de foto.
{('Já existem estas (NÃO repita a PALAVRA entre colchetes nem a ideia da cena):' + chr(10) + existentes) if existentes else ''}
Responda só o JSON."""
        conteudo = f"Título do vídeo: {titulo}\n\nSobre o vídeo / roteiro:\n{(contexto or '')[:12000]}"
        with ia.rotulo("🔥 Thumbs palavra gigante: " + (titulo or "")[:60]):
            d = ia.chamar("roteiros", system, conteudo, schema=_schema_ideias(), max_tokens=3000, effort="medium", timeout=300,
                         cache_local=False)  # 🔁 v84_420: clicar de novo traz ideias NOVAS (não a mesma resposta guardada)
        if not d:
            raise ThumbErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
        out = [t for t in (normalizar(dict(x, modo="albert") if isinstance(x, dict) else x)
                           for x in (d.get("thumbnails") if isinstance(d, dict) else d) or []) if t]
        if not out:
            raise ThumbErro("a IA não sugeriu nenhuma thumbnail")
        return _pos_alb(out[:albert])
    system = f"""Você cria THUMBNAILS de YouTube que dão clique sem enganar. Para o vídeo abaixo, crie {n} thumbnails BEM
DIFERENTES entre si — cada uma com um ângulo próprio (use estes, um por thumbnail, na ordem que fizer sentido:
{'; '.join(ANGULOS)}). Nada de repetir a mesma cena com outra luz.
Para cada uma:
- "ideia": o que a thumbnail mostra e por que dá clique (1 frase, em português);
- "texto": 2 a 4 palavras GRANDES que vão na miniatura (idioma do vídeo: {idioma}), que completam o título sem repeti-lo;
- "prompt": a cena da imagem EM INGLÊS para o Google Flow: um assunto principal claro, expressão/ação, lugar, época, luz e
  enquadramento, com espaço vazio de um lado pro título. NUNCA peça texto escrito, letras, setas, círculos ou marcações na
  imagem (o texto entra depois, por cima). Sem violência gráfica. Pessoa real famosa: descreva (idade, roupa, época), sem o nome.
- "angulo": qual dos ângulos acima ela usa.
- "titulos": 2 títulos pra ESTA thumbnail. {REGRA_TITULOS_THUMB}
{(f"""
E MAIS {albert} thumbnail(s) a mais (depois das {n}), com "modo": "albert", neste estilo:
{REGRA_ALBERT}
Nelas: "texto" = a PALAVRA gigante (só ela); "prompt" = a cena EM INGLÊS (o personagem, a expressão irônica, o objeto-símbolo,
o fundo) — NÃO descreva as letras no prompt, o site põe; "ideia" = qual é a ironia. Cada uma com uma ironia diferente.
{txt_alb}""") if albert else ''}
{('Estética do canal (a cena tem que caber nela): ' + estilo_canal.replace('@@', ' ')[:900]) if estilo_canal and not por_ideia else ''}
Se o estilo é desenho/anime/cartoon, descreva as pessoas como PERSONAGENS desenhados (expressão, pose, roupa, cabelo), sem
detalhes de foto realista (pele, rugas, poros, lente, "cinematic").
{('ESTILO DE ARTE de cada thumbnail, NA ORDEM (pense a cena pra funcionar nesse estilo; não descreva o estilo no prompt, o site põe): '
  + '; '.join(f'{k + 1}) {estilos_arte.ESTILOS[e]["nome"]}' for k, e in enumerate(por_ideia))) if por_ideia else ''}
{('Já existem estas (NÃO repita a ideia nem o ângulo delas):' + chr(10) + existentes) if existentes else ''}
Responda só o JSON."""
    conteudo = f"Título do vídeo: {titulo}\n\nSobre o vídeo / roteiro:\n{(contexto or '')[:12000]}"
    with ia.rotulo("🖼 Thumbs: " + (titulo or "")[:60]):
        d = ia.chamar("roteiros", system, conteudo, schema=_schema_ideias(), max_tokens=4000, effort="low", timeout=300,
                         cache_local=False)
    if not d:
        raise ThumbErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
    out = [t for t in (normalizar(x) for x in (d.get("thumbnails") if isinstance(d, dict) else d) or []) if t]
    if not out:
        raise ThumbErro("a IA não sugeriu nenhuma thumbnail")
    normais = [t for t in out if t.get("modo") != "albert"][:max(1, n)]
    alb = [t for t in out if t.get("modo") == "albert"][:albert]
    if albert and len(normais) > n - 1 and not alb and len(out) > n:  # a IA esqueceu o "modo": as que passaram das n são as albert
        alb = [dict(t, modo="albert") for t in out[n:n + albert]]
    for k, t in enumerate(normais):
        if por_ideia:
            t["estilo_arte"] = por_ideia[k % len(por_ideia)]
    return normais + _pos_alb(alb)


def adicionar_ideias(base: str, origem: str, pid: str, ideias: List[Dict[str, str]]) -> Dict[str, Any]:
    """As ideias novas entram no fim (as que já existem ficam)."""
    with _TRAVA:
        d = carregar(base, origem, pid)
        itens = d.setdefault("itens", [])
        conhecidas = {i.get("ideia") for i in itens}
        prox = max([int(i.get("n") or 0) for i in itens] or [0]) + 1
        for n in ideias:
            if n["ideia"] in conhecidas:
                continue
            itens.append(dict(n, n=prox, status="", imagem="", final="", erro="", da_ia=True))
            conhecidas.add(n["ideia"])
            prox += 1
        salvar(base, origem, pid, d)
        return d


# ------------------------------------------------------------------ 🖼 thumbnail avulsa (qualquer vídeo) — v84_368
def criar_avulsa(base: str, titulo: str, sobre: str, canal: str = "", idioma: str = "pt") -> str:
    import uuid
    pid = uuid.uuid4().hex[:10]
    salvar(base, "avulso", pid, {"titulo": " ".join(str(titulo or "").split())[:200], "sobre": str(sobre or "")[:20000],
                                 "canal": str(canal or "")[:60], "idioma": str(idioma or "pt")[:10], "criado": time.time(),
                                 "itens": []})
    return pid


def listar_avulsas(base: str) -> List[Dict[str, Any]]:
    raiz = os.path.join(base, PASTA)
    out = []
    if not os.path.isdir(raiz):
        return out
    for nome in os.listdir(raiz):
        if not nome.startswith("avulso_"):
            continue
        pid = nome[len("avulso_"):]
        if not _valido("avulso", pid):
            continue
        d = carregar(base, "avulso", pid)
        out.append({"id": pid, "titulo": d.get("titulo") or "(sem título)", "itens": len(d.get("itens") or []),
                    "prontas": sum(1 for i in d.get("itens") or [] if i.get("final")), "criado": d.get("criado") or 0, "atualizado": d.get("atualizado") or 0})
    return sorted(out, key=lambda x: -x["criado"])


# ------------------------------------------------------------------ o texto por cima
def compor(imagem: str, texto: str, saida: str, W: int = 1280, H: int = 720) -> str:
    """1280×720: a imagem cobrindo a tela + o texto grande (contorno preto, sombra) no lado mais vazio."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat
    im = Image.open(imagem).convert("RGB")
    k = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * k + 0.5), int(im.height * k + 0.5)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    im = im.crop((x0, y0, x0 + W, y0 + H))
    texto = " ".join(str(texto or "").split()).upper()
    if texto:
        # o lado mais "calmo" (menos detalhe) recebe o texto
        g = im.convert("L").filter(ImageFilter.FIND_EDGES)
        esq = ImageStat.Stat(g.crop((0, 0, W // 2, H))).mean[0]
        dir_ = ImageStat.Stat(g.crop((W // 2, 0, W, H))).mean[0]
        lado_esq = esq <= dir_
        fonte = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts", "dp", "bebas-neue-Bold.ttf")
        palavras = texto.split()
        linhas = [" ".join(palavras[i:i + 2]) for i in range(0, len(palavras), 2)][:3]
        area_w = W * 0.46
        px = int(H * 0.26)
        while px > 30:
            f = ImageFont.truetype(fonte, px) if os.path.exists(fonte) else ImageFont.load_default()
            if max(f.getlength(l) for l in linhas) <= area_w and px * 0.95 * len(linhas) <= H * 0.8:
                break
            px = int(px * 0.92)
        d = ImageDraw.Draw(im)
        # um degradê escuro atrás do texto, pra ler em qualquer foto
        som = Image.new("L", (W, H), 0)
        ds = ImageDraw.Draw(som)
        for i in range(int(W * 0.55)):
            a = int(150 * (1 - i / (W * 0.55)) ** 1.6)
            xx = i if lado_esq else W - 1 - i
            ds.line([xx, 0, xx, H], fill=a)
        im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, som)
        d = ImageDraw.Draw(im)
        alt = px * 0.95 * len(linhas)
        y = (H - alt) / 2 + px * 0.8
        for i, l in enumerate(linhas):
            w = f.getlength(l)
            x = W * 0.05 if lado_esq else W * 0.95 - w
            cor = (255, 214, 0) if i == len(linhas) - 1 and len(linhas) > 1 else (255, 255, 255)
            d.text((x + px * 0.05, y + px * 0.06), l, font=f, fill=(0, 0, 0), anchor="ls")
            d.text((x, y), l, font=f, fill=cor, anchor="ls", stroke_width=max(2, px // 14), stroke_fill=(0, 0, 0))
            y += px * 0.95
    os.makedirs(os.path.dirname(saida) or ".", exist_ok=True)
    im.save(saida, quality=92)
    return saida


# ------------------------------------------------------------------ gerar no Flow
def cliente_padrao():
    from googleflow.googleflow_client import GoogleFlowClient
    from site_config import load_site_config
    cfg = dict(load_site_config())
    cfg.update(orientation="16:9", flow_proporcao_imagem="16:9")
    return GoogleFlowClient(cfg)


def gerar(base: str, origem: str, pid: str, ns: Optional[List[int]] = None, forcar: bool = False,
          cliente: Any = None, log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Gera no Flow as thumbnails pedidas (ns = None: as que ainda não têm imagem). Uma de cada vez."""
    d = carregar(base, origem, pid)
    alvo = [i for i in d.get("itens") or [] if (ns is None and not i.get("imagem")) or (ns is not None and int(i["n"]) in ns)]
    if not alvo:
        log("Nada pra gerar — todas já têm imagem.")
        return d
    cliente = cliente or cliente_padrao()
    est = estilo(base, origem, pid)  # 🎨 v84_368: o estilo do canal (vazio = o padrão de documentário)
    feitas = 0
    for k, it in enumerate(alvo, start=1):
        n = int(it["n"])
        editar_status(base, origem, pid, n, status="gerando", erro="")
        log(f"🎨 thumbnail {k}/{len(alvo)}: {it.get('ideia', '')[:80]}")
        try:
            pf = prompt_flow(it, estilo=est)
            fotos = cliente.gerar_imagem_prompt(pf, forcar=forcar or bool(it.get("imagem")))
            origem_img = next((f.local_path for f in fotos if getattr(f, "local_path", "") and os.path.isfile(f.local_path)), None)
            if not origem_img:
                raise ThumbErro("o Flow não devolveu a imagem")
            p = pasta(base, origem, pid)
            os.makedirs(p, exist_ok=True)
            destino = os.path.join(p, f"thumb_{n}_{int(time.time() * 1000)}{os.path.splitext(origem_img)[1] or '.png'}")
            shutil.copyfile(origem_img, destino)
            final = compor(destino, "" if it.get("modo") == "albert" else (it.get("texto") or ""),
                           destino.rsplit(".", 1)[0] + "_final.jpg")  # 🔥 albert: a palavra já vem na imagem
            editar_status(base, origem, pid, n, status="pronto", imagem=destino, final=final, erro="", prompt_usado=pf)
            feitas += 1
        except Exception as exc:  # noqa: BLE001 — uma que falha não para as outras
            if _INCOMUM.search(str(exc)):
                # 🛑 v84_395: o Google desconfiou da automação — insistir agora só piora; para e deixa o resto na fila
                editar_status(base, origem, pid, n, status="erro", erro=MSG_INCOMUM)
                for resto in alvo[k:]:
                    editar_status(base, origem, pid, int(resto["n"]), status="", erro="")
                log("⏸ " + MSG_INCOMUM)
                break
            editar_status(base, origem, pid, n, status="erro", erro=str(exc)[:300])
            log(f"✖ thumbnail {n}: {exc}")
    log(f"✅ {feitas} de {len(alvo)} thumbnail(s) gerada(s).")
    return carregar(base, origem, pid)


def editar_status(base: str, origem: str, pid: str, n: int, **campos: Any) -> None:
    with _TRAVA:
        d = carregar(base, origem, pid)
        for it in d.get("itens") or []:
            if int(it.get("n") or 0) == int(n):
                it.update(campos)
        salvar(base, origem, pid, d)


def iniciar(base: str, origem: str, pid: str, ns: Optional[List[int]] = None, forcar: bool = False, pagina: str = "",
            cliente_fn: Optional[Callable[[], Any]] = None) -> str:
    """Em segundo plano (🔔 avisa quando terminar). Devolve o id da tarefa."""
    import tarefas_bg
    for it in carregar(base, origem, pid).get("itens") or []:
        if (ns is None and not it.get("imagem")) or (ns is not None and int(it["n"]) in ns):
            editar_status(base, origem, pid, int(it["n"]), status="fila", erro="")
    return tarefas_bg.iniciar("thumbs_flow", "🖼 Thumbnails no Google Flow",
                              lambda t: gerar(base, origem, pid, ns, forcar, (cliente_fn or cliente_padrao)(), t.progresso),
                              pagina=pagina)


def para_json(d: Dict[str, Any], url_base: str, estilo_canal: str = "") -> Dict[str, Any]:
    """Pra página: sem caminhos do disco, com as URLs (e o prompt completo pra colar no Flow à mão — v84_368)."""
    out = []
    for it in d.get("itens") or []:
        x = {k: it.get(k) for k in ("n", "ideia", "texto", "prompt", "status", "erro", "da_ia", "estilo_arte", "modo", "titulos",
                                    "ajustes")}
        x["prompt_flow"] = prompt_flow(it, estilo=estilo_canal)
        x["url_imagem"] = f"{url_base}/{it['n']}/imagem?v={int(os.path.getmtime(it['imagem']))}" if it.get("imagem") and os.path.isfile(it["imagem"]) else ""
        x["url_final"] = f"{url_base}/{it['n']}/final?v={int(os.path.getmtime(it['final']))}" if it.get("final") and os.path.isfile(it["final"]) else ""
        out.append(x)
    import estilos_arte
    return {"itens": out, "estilos": estilos_arte.opcoes()}


# ------------------------------------------------------------------ pra pôr nos prompts
BLOCO_PROMPT = (
    "THUMBNAILS: em \"thumbnails\", sugira 5 thumbnails BEM diferentes entre si pro vídeo (cada uma com um ângulo próprio: rosto/"
    "emoção, objeto-símbolo em close, contraste/dois lados, a cena mais dramática, mistério/pergunta visual), cada uma com: \"ideia\" (o que mostra e por que dá "
    "clique, em 1 frase), \"texto\" (2 a 4 palavras GRANDES na miniatura, no idioma do vídeo, que completam o título sem repeti-lo) "
    "e \"prompt\" (a cena da imagem EM INGLÊS pra um gerador de imagem: um assunto principal claro, expressão/ação, lugar, luz, "
    "enquadramento — sem pedir texto escrito na imagem, sem violência gráfica). A imagem vai ser gerada no Google Flow e o texto "
    "entra por cima.")


def bloco_prompt(albert: Optional[int] = None) -> str:
    """O pedido das thumbnails nos prompts do roteiro — as 5 de sempre + as do 🔥 estilo palavra gigante (v84_417)
    + 🏷 2 títulos casados com cada uma (v84_429)."""
    a = ativo_albert() if albert is None else albert
    if not a:
        return BLOCO_PROMPT + " " + REGRA_TITULOS_THUMB
    return (BLOCO_PROMPT + f" DEPOIS dessas 5, mais {a} thumbnail(s) com \"modo\": \"albert\" — {REGRA_ALBERT} Nelas, \"texto\" "
            "= a PALAVRA gigante (só ela) e o \"prompt\" descreve a cena (personagem, expressão irônica, objeto-símbolo, fundo) "
            "sem descrever as letras — o site põe. " + REGRA_TITULOS_THUMB)


EXEMPLO_JSON = [{"ideia": "o que a thumbnail mostra e por que dá clique", "texto": "2-4 PALAVRAS",
                 "prompt": "in English: the image scene for an AI image generator (no text in the image)",
                 "titulos": ["título 1 que casa com esta thumb", "título 2"]}]



# ------------------------------------------------------------------ 🏷 v84_429: 2 títulos pra cada thumbnail que já existe
def _schema_titulos() -> Dict[str, Any]:
    from ia_midia import _I, _S, _lista, _obj
    return _obj({"thumbs": _lista(_obj({"n": _I, "titulos": _lista(_S)}))})


def pedir_titulos(titulo: str, contexto: str, itens: List[Dict[str, Any]], idioma: str = "pt",
                  originais: Optional[List[str]] = None) -> Dict[int, List[str]]:
    """{n: [2 títulos]} pras thumbnails pedidas — a palavra e a imagem da thumb NÃO mudam."""
    import ia_servico as ia
    motivo = ia.motivo_desligado("roteiros")
    if motivo:
        raise ThumbErro("IA: " + motivo)
    if not itens:
        raise ThumbErro("Nenhuma thumbnail pra dar título.")
    import metodo_roteiro as mr
    formulas = "\n".join(f"  - {a}  (ex.: {b})" for a, b in mr.TITULOS_ALBERT)
    lista = "\n".join(f"- n={it['n']}: {'PALAVRA GIGANTE' if it.get('modo') == 'albert' else 'texto na thumb'} „{it.get('texto') or ''}“"
                       f" — cena: {it.get('ideia') or it.get('prompt') or ''}" for it in itens)
    system = f"""Você escreve TÍTULOS de YouTube pro VÍDEO que conversam com a THUMBNAIL — como os canais de psicologia/
comportamento que explodem: a thumb dá a emoção, o título dá o assunto e a promessa, e juntos dão o clique.
{REGRA_TITULOS_THUMB}
Fórmulas do jeito "Assunto. Pergunta?" (o ASSUNTO do vídeo antes do ponto — adapte):
{formulas}
Pra cada thumbnail da lista, devolva "n" e 2 "titulos" (idioma: {idioma}). Não mude a palavra nem a cena da thumb.
Responda só o JSON."""
    orig = [t for t in (originais or []) if str(t).strip()] or ([titulo] if titulo else [])
    conteudo = ("Títulos ORIGINAIS do vídeo (a base — o dono gostou deles; mantenha o assunto e a promessa):\n"
                + "\n".join(f"- {t}" for t in orig[:8])
                + f"\n\nSobre o vídeo / roteiro:\n{(contexto or '')[:9000]}\n\nThumbnails:\n{lista}")
    with ia.rotulo("🏷 Títulos das thumbs: " + (titulo or "")[:50]):
        d = ia.chamar("roteiros", system, conteudo, schema=_schema_titulos(), max_tokens=2500, effort="low", timeout=240,
                      cache_local=False)
    if not isinstance(d, dict):
        raise ThumbErro("a IA não respondeu (veja as últimas chamadas em 🤖 IA)")
    pedidos = {int(it["n"]) for it in itens}
    out: Dict[int, List[str]] = {}
    for x in d.get("thumbs") or []:
        try:
            n = int(x.get("n"))
        except (TypeError, ValueError):
            continue
        tits = [" ".join(str(t).split())[:100] for t in x.get("titulos") or [] if str(t).strip()][:3]
        if n in pedidos and tits:
            out[n] = tits
    if not out:
        raise ThumbErro("a IA não devolveu títulos")
    return out


def gravar_titulos(base: str, origem: str, pid: str, titulos: Dict[int, List[str]]) -> Dict[str, Any]:
    with _TRAVA:
        d = carregar(base, origem, pid)
        for it in d.get("itens") or []:
            if int(it.get("n") or 0) in titulos:
                it["titulos"] = titulos[int(it["n"])]
        salvar(base, origem, pid, d)
        return d
