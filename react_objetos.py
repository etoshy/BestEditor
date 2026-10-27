"""🍿 React — os ITENS DA MESA, uma mesa por sofá e o "mapa" da sala pras imagens (v84_238i).

- 🍿 Itens da mesa: cada item (pipoca, refrigerante, salgadinho, controle, bolo…) é uma camada separada, gerada no
  Flow (fundo verde → recortada) e posta EM CIMA da mesa escolhida (a da frente ou a ⧉ de outro sofá). Dá pra arrastar
  no 🎛 palco como qualquer camada.
- 🛋🛋 Dois sofás: cada sofá ganha a SUA mesa (a da direita é uma cópia automática — esconda com 👁 se não quiser).
- 🗺 Mapa da sala: quem está sentado em qual sofá (da esquerda pra direita), onde ficam as mesas, os itens em cima de
  cada uma e a TV — vai no pedido de cada imagem importante (briga, interação, cena), junto com o QUADRO ATUAL do react
  como referência, pra imagem sair com cada um no lugar dele, as mesas e os itens certos. E vai pro roteiro, pra IA
  saber quem pode pegar o quê de quem.
- ⚡ Poderes e jeito: a ficha tem 'poderes' (pt) e 'poderes_en' — quem tem poder usa ele nas interações (a Tatsumaki
  levita a pipoca com telecinese, o Luffy estica o braço de borracha até a mesa do outro sofá, cara de desenho/toon), e
  o jeito de cada um aparece (o estressado bufa, derruba, aperta a lata).
"""
from __future__ import annotations

import os
import secrets
from typing import Any, Dict, List, Optional

import react_personagens as R

SUGESTOES = [("Pipoca", "a big bowl of buttered popcorn"), ("Refrigerante", "two cans of soda"),
             ("Salgadinho", "an open bag of chips"), ("Controle", "a game controller"),
             ("Pizza", "an open pizza box with a few slices"), ("Copo de suco", "a glass of orange juice with a straw")]


def objetos(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    return p.setdefault("objetos", [])


def novo(p: Dict[str, Any], nome: str, en: str = "", mesa: str = "mesa") -> Dict[str, Any]:
    nome = " ".join(str(nome or "").split())[:60]
    if not nome:
        raise R.ReactErro("Diga o nome do item.")
    o = {"id": "o" + secrets.token_hex(3), "nome": nome, "en": " ".join(str(en or "").split())[:300] or nome,
         "mesa": mesa or "mesa", "img": {}}
    objetos(p).append(o)
    return o


def editar(p: Dict[str, Any], oid: str, dados: Dict[str, Any]) -> None:
    o = next((x for x in objetos(p) if x["id"] == oid), None)
    if not o:
        raise R.ReactErro("Item não encontrado.")
    if dados.get("apagar"):
        p["objetos"] = [x for x in objetos(p) if x["id"] != oid]
        for lay in (p.get("posicoes") or {}).values():
            lay.pop(f"o:{oid}", None)
        return
    for k, n in (("nome", 60), ("en", 300), ("mesa", 40)):
        if k in dados:
            o[k] = " ".join(str(dados[k] or "").split())[:n] or o.get(k)


def arquivo(p: Dict[str, Any], o: Dict[str, Any], base: str) -> Optional[str]:
    a = (o.get("img") or {}).get("arquivo")
    cam = os.path.join(R.pasta(p["id"], base), "cenario", a) if a else None
    return cam if cam and os.path.isfile(cam) else None


# ------------------------------------------------------------------ 🎨 gerar no Flow
def prompt(p: Dict[str, Any], o: Dict[str, Any]) -> str:
    if R.layout_de(p) in R.CINEMA:
        return (f"{o.get('en') or o['nome']}, a single movie-theater snack or item, the kind a person holds in the hand or puts "
                "in the cup holder of a cinema seat, seen from the FRONT slightly from above, the whole object visible with "
                "margin, isolated on a flat solid chroma-key green background (#00FF00), no hands, no seat, no people, no text. "
                + R.ESTILO_TXT[R.estilo_final(p)] + ".")[:3900]
    return (f"{o.get('en') or o['nome']}, a single object for a cozy streamer living room in a reaction video, sitting on "
            "a coffee table, seen from the FRONT slightly from above, the whole object visible with margin, isolated on a "
            "flat solid chroma-key green background (#00FF00), no table, no shadow on the background, no people, no text. "
            + R.ESTILO_TXT[R.estilo_final(p)] + ".")[:3900]


def gerar(pid: str, base: str = R._BASE, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    import flow_lote
    with R._TRAVA:
        p = R.carregar(pid, base)
        alvo = [o for o in objetos(p) if (ids and o["id"] in ids) or (not ids and not arquivo(p, o, base)
                                                                       and (o.get("img") or {}).get("estado") not in ("fila", "gerando"))]
        if not alvo:
            raise R.ReactErro("Nenhum item pra gerar (todos já têm imagem ou estão na fila).")
        ref = R.camada_arquivo(p, "mesa", base) or R.camada_arquivo(p, "fundo", base)
        itens = []
        for o in alvo:
            it = {"prompt": prompt(p, o), "tipo": "imagem", "origem": "react"}
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
        try:
            novos = flow_lote.lote().adicionar(itens, proporcao="1:1", quantidade="x1")
        except ValueError as exc:
            raise R.ReactErro(str(exc))
        for o, j in zip(alvo, novos):
            o.setdefault("img", {}).update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow")
        R.log(p, f"🍿 {len(alvo)} item(ns) da mesa pro Flow")
        R.salvar(p, base)
    aviso = ""
    try:
        flow_lote.lote().iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]})"
    return {"enviadas": len(alvo), "aviso": aviso}


def guardar(p: Dict[str, Any], o: Dict[str, Any], img, base: str, origem: str = "flow") -> str:
    d = os.path.join(R.pasta(p["id"], base), "cenario")
    os.makedirs(d, exist_ok=True)
    tem_alfa = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250
    if tem_alfa:
        im = img.convert("RGBA")
        cx = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
        im = im.crop(cx) if cx else im
    else:
        im = R.recortar_verde(img.convert("RGB"))
    arq = f"obj_{o['id']}_{secrets.token_hex(3)}.png"
    im.save(os.path.join(d, arq))
    st = o.setdefault("img", {})
    st.update(arquivo=arq, estado="pronta", erro=None, msg=None, origem=origem, versoes=([arq] + (st.get("versoes") or []))[:6])
    return arq


def acompanhar(pid: str, base: str = R._BASE) -> bool:
    import flow_lote
    p = R.carregar(pid, base)
    if not any((o.get("img") or {}).get("estado") in ("fila", "gerando") for o in objetos(p)):
        return False
    lote = flow_lote.lote()
    with lote.trava:
        fila = {j["id"]: dict(j) for j in lote.fila}
    mudou = False
    with R._TRAVA:
        p = R.carregar(pid, base)
        for o in objetos(p):
            st = o.get("img") or {}
            if st.get("estado") not in ("fila", "gerando") or not st.get("job"):
                continue
            fj = fila.get(st["job"])
            antes = (st.get("estado"), st.get("msg"))
            if fj is None:
                st.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa — gere de novo")
            elif fj["estado"] == "ok":
                ok = False
                for r in fj.get("resultados") or []:
                    try:
                        import flow_estudio as FE
                        from PIL import Image
                        orig = os.path.join(FE.pasta_galeria(), r.get("arquivo") or "")
                        if r.get("tipo") == "imagem" and os.path.isfile(orig):
                            guardar(p, o, Image.open(orig), base)
                            ok = True
                            break
                    except Exception as exc:  # noqa: BLE001
                        st.update(estado="erro", erro=f"a imagem chegou mas o recorte falhou: {str(exc)[:160]}")
                if not ok and st.get("estado") != "erro":
                    st.update(estado="erro", erro="o Flow terminou sem imagem")
            elif fj["estado"] == "erro":
                st.update(estado="erro", erro=str(fj.get("erro") or "o Flow falhou")[:300])
            elif fj["estado"] in ("rodando", "convertendo"):
                st.update(estado="gerando", msg="🎨 gerando no Flow")
            o["img"] = st
            if (st.get("estado"), st.get("msg")) != antes:
                mudou = True
        if mudou:
            R.salvar(p, base)
    return mudou


# ------------------------------------------------------------------ 📐 onde ficam (em cima da mesa)
def mesas(lay: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """As mesas da disposição: 'mesa' e as ⧉ cópias dela (inclusive a automática do 2º sofá)."""
    out = {"mesa": lay["mesa"]}
    for cp in lay.get("copias") or []:
        if cp.get("de") == "mesa":
            out[cp["chave"]] = cp
    return out


def geometria(p: Dict[str, Any], lay: Dict[str, Any], base: str, ajuste) -> List[Dict[str, Any]]:
    """Cada item com imagem: em cima da mesa dele, espalhados na largura do tampo (base do item no tampo). 🎬 No cinema
    não tem mesa: o item fica com um personagem ('mesa' = 'p:<id>'; sem dono, vai passando de um em um) — no colo (de
    frente) ou no braço da poltrona (de costas)."""
    if lay.get("layout") in R.CINEMA:
        return _geometria_cinema(p, lay, base, ajuste)
    ms = mesas(lay)
    por_mesa: Dict[str, List[Dict[str, Any]]] = {}
    for o in objetos(p):
        cam = arquivo(p, o, base)
        if not cam:
            continue
        por_mesa.setdefault(o.get("mesa") if o.get("mesa") in ms else "mesa", []).append((o, cam))
    out = []
    for mk, lista in por_mesa.items():
        m = ms[mk]
        topo = m["cy"] - m["h"] * 0.30  # o tampo (a mesa é vista de frente, um pouco de cima)
        n = len(lista)
        for k, (o, cam) in enumerate(lista):
            iw, ih = R._tam(cam, (1, 1))
            w = min(m["w"] * 0.22, m["w"] * 0.8 / max(1, n))
            h = w * ih / max(1, iw)
            cx = m["cx"] + m["w"] * 0.7 * ((k + 0.5) / n - 0.5)
            d = {"id": o["id"], "chave": f"o:{o['id']}", "nome": o["nome"], "cam": cam, "mesa": mk,
                 "cx": cx, "cy": topo - h / 2 + h * 0.08, "w": w, "h": h, "espelhar": False}
            ajuste(d, d["chave"])
            out.append(d)
    return out


def _geometria_cinema(p: Dict[str, Any], lay: Dict[str, Any], base: str, ajuste) -> List[Dict[str, Any]]:
    assentos = {f"p:{a['cid']}": a for a in lay.get("assentos") or []}
    if not assentos:
        return []
    chaves = list(assentos)
    out, k = [], 0
    for o in objetos(p):
        cam = arquivo(p, o, base)
        if not cam:
            continue
        dono = o.get("mesa") if o.get("mesa") in assentos else chaves[k % len(chaves)]
        k += 1
        a = assentos[dono]
        iw, ih = R._tam(cam, (1, 1))
        w = a["w"] * 0.40
        h = w * ih / max(1, iw)
        if lay["layout"] == "cinema_costas":  # no braço da poltrona, à direita de quem senta
            s = lay["sofas"][a.get("fila", 0)] if a.get("fila", 0) < len(lay["sofas"]) else lay["sofas"][0]
            base_y = s["cy"] - s["h"] / 2 + s["h"] * 0.12
            cx, ref = a["cx"] + a["w"] * 0.42, f"sofa{a.get('fila', 0)}"
        elif lay["layout"] == "cinema_plateia":  # de perto: na mão, na altura do peito (acima dos encostos da frente)
            base_y = a["cy"] + a["h"] * 0.14
            cx, ref = a["cx"] + a["w"] * 0.16, dono
        else:  # no colo
            base_y = a["cy"] + a["h"] * 0.36
            cx, ref = a["cx"] + a["w"] * 0.12, dono
        d = {"id": o["id"], "chave": f"o:{o['id']}", "nome": o["nome"], "cam": cam, "mesa": ref, "dono": dono,
             "cx": cx, "cy": base_y - h / 2, "w": w, "h": h, "espelhar": False}
        ajuste(d, d["chave"])
        out.append(d)
    return out


SUGESTOES_CINEMA = [("Balde de pipoca", "a big red-and-white striped cinema popcorn bucket overflowing with popcorn"),
                    ("Refrigerante de cinema", "a large cinema soda cup with a lid and a straw"),
                    ("Nachos", "a cinema nachos tray with melted cheddar cheese"),
                    ("Caixa de doces", "a small box of colorful movie-theater candy"),
                    ("Óculos 3D", "a pair of 3D cinema glasses"), ("Cachorro-quente", "a hot dog in a paper sleeve")]


# ------------------------------------------------------------------ 🗺 o mapa da sala (pras imagens e pro roteiro)
def _lado(cx: float) -> str:
    return "left" if cx < R.W * 0.4 else "center" if cx < R.W * 0.6 else "right"


def mapa(p: Dict[str, Any], lay: Dict[str, Any], ingles: bool = True) -> str:
    sofas = lay.get("sofas") or []
    if lay.get("layout") in R.CINEMA:  # 🎬 as fileiras (a 1ª = a mais perto da câmera) e o que cada um segura
        nomes = {a["cid"]: R.personagem(p, a["cid"])["nome"] for a in lay.get("assentos") or []}
        segura: Dict[str, List[str]] = {}
        for o in lay.get("objetos") or []:
            oo = next((x for x in objetos(p) if x["id"] == o["id"]), {})
            segura.setdefault(o.get("dono", "")[2:], []).append(oo.get("en") or o["nome"] if ingles else o["nome"])
        L = []
        for k in range(len(sofas)):
            quem = sorted([a for a in lay["assentos"] if a.get("fila") == k], key=lambda a: a["cx"])
            desc = ", ".join(nomes[a["cid"]] + (f" (holding {', '.join(segura[a['cid']])})" if ingles and segura.get(a["cid"]) else
                                                f" (com {', '.join(segura[a['cid']])})" if segura.get(a["cid"]) else "") for a in quem)
            L.append((f"row {k + 1} ({'closest to the camera' if k == 0 else 'further back'}): {desc}" if ingles else
                      f"fileira {k + 1} ({'a mais perto da câmera' if k == 0 else 'mais atrás'}): {desc}"))
        if ingles:
            vista = ("a dark movie theater seen from BEHIND the audience: the big glowing screen ahead, everyone seen from "
                     "the back in red cinema seats" if lay["layout"] == "cinema_costas" else
                     "a movie theater seen up close from the row in front, like an anime ending: the main row of red "
                     "cinema seats facing the camera, a smaller row behind, the backs of the front-row seats in the "
                     "foreground, warm hazy projector light" if lay["layout"] == "cinema_plateia" else
                     "a dark movie theater seen from the screen: the audience facing the camera in stepped rows of red "
                     "cinema seats, faces lit by the screen")
            return f"SCENE LAYOUT (keep it): {vista}; " + "; ".join(L) + " (from left to right)."
        return ("MAPA DA SALA: cinema " + ("visto de trás (as costas e o telão)" if lay["layout"] == "cinema_costas" else
                                            "de perto (a fileira de frente pra câmera)" if lay["layout"] == "cinema_plateia" else "visto de frente (a plateia)") + "; " + "; ".join(L) + " (da esquerda pra direita).")
    linhas = []
    for k, s in enumerate(sofas):
        quem = sorted([a for a in lay["assentos"] if min(range(len(sofas)), key=lambda i: abs(sofas[i]["cx"] - a["cx"])) == k],
                      key=lambda a: a["cx"])
        nomes = [R.personagem(p, a["cid"])["nome"] for a in quem]
        if ingles:
            linhas.append(f"the {_lado(s['cx'])} sofa: {', '.join(nomes) or 'empty'} (from left to right)")
        else:
            linhas.append(f"sofá da {'esquerda' if s['cx'] < R.W / 2 else 'direita'}: {', '.join(nomes) or 'vazio'} (da esquerda pra direita)")
    ms = mesas(lay)
    for mk, m in ms.items():
        its = [o["nome"] if not ingles else (o.get("en") or o["nome"]) for o in objetos(p) if (o.get("mesa") if o.get("mesa") in ms else "mesa") == mk]
        if ingles:
            linhas.append(f"a low coffee table in front of the {_lado(m['cx'])} side" + (f" with {', '.join(its)} on it" if its else ""))
        else:
            linhas.append(f"mesa na frente do lado {'esquerdo' if m['cx'] < R.W / 2 else 'direito'}" + (f" com: {', '.join(its)}" if its else ""))
    t = lay["tela"]
    linhas.append(f"the TV on the {_lado(t['cx'])} side" if ingles else f"a TV no lado {'esquerdo' if t['cx'] < R.W * 0.4 else 'do meio' if t['cx'] < R.W * 0.6 else 'direito'}")
    return ("SCENE LAYOUT (keep it): " if ingles else "MAPA DA SALA: ") + "; ".join(linhas) + "."


def poderes_en(p: Dict[str, Any], cids: List[str]) -> str:
    """⚡ Os poderes e o jeito visual de quem está na imagem — pra ele USAR na interação."""
    xs = []
    for cid in cids:
        c = next((x for x in p["personagens"] if x["id"] == cid), None)
        if c and (c.get("poderes_en") or "").strip():
            xs.append(f"{c['nome']}: {c['poderes_en']}")
    return ("POWERS / VISUAL QUIRKS (show them being used in the action when it fits): " + "; ".join(xs) + ".") if xs else ""


REGRAS_ROTEIRO = (
    "- 🍿 OBJETOS E PODERES: a sala tem o MAPA abaixo (quem senta onde, as mesas e o que tem em cima). Use os itens "
    "nas interações: alguém pega a pipoca, come, oferece pro outro, rouba do sofá do lado, joga a lata, derruba o "
    "refrigerante no colo de alguém — e cada um interage do SEU jeito: quem tem PODER usa o poder (a Tatsumaki "
    "levita a pipoca com telecinese verde, o Luffy estica o braço de borracha até a mesa do outro sofá, cara de "
    "desenho/toon na piada), o estressado bufa e amassa a lata, o preguiçoso pede pros outros pegarem. Uma ação com "
    "objeto pode virar 2–3 eventos SEGUIDOS (um por quadro: pega → oferece → joga), cada um com a sua 'imagem_en' "
    "dizendo quem está em qual sofá, de onde pra onde vai o item e o poder usado.\n")
