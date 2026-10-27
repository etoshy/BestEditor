"""📖 Animação 2D — adaptar um MANGÁ (as suas páginas) em anime.

1. As páginas entram em ordem (📤 ou a pasta `manga/` do zip).
2. 🤖 A IA lê tudo e devolve a ADAPTAÇÃO (o "segundo JSON"): os personagens como estão no mangá (a base) e como
   ficam na versão anime (`design_en`), os locais, os itens, as cenas com as páginas de cada uma e notas de adaptação —
   e onde cada personagem/lugar aparece melhor (a página e o recorte, que viram as referências).
3. 🎨 Cada personagem ganha o DESIGN ANIME no Flow (a partir dos recortes do mangá + o estilo). Você ✔ APROVA (ou
   🔁 refaz com um pedido / 📁 manda o seu). Só depois de aprovado as poses (quadros, 2º quadro, bocas) são geradas —
   com o design aprovado como referência principal.
4. 🤖 Escrever as cenas: cada cena vai com as SUAS páginas anexadas — balão por balão, na ordem de leitura do mangá
   (direita → esquerda), narração nas caixas de texto, onomatopeias anotadas como 🔊 som.
O resto é o fluxo normal (fundos/itens no Flow → vozes escolhidas na página → editor).
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

import anime2d as A
import react_personagens as R

MAX_PAGINAS = 60
EXT_PAG = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

_CAIXA = {"type": "object", "additionalProperties": False, "required": ["pagina", "x0", "y0", "x1", "y1"],
          "properties": {"pagina": {"type": "integer"}, "x0": {"type": "number"}, "y0": {"type": "number"},
                         "x1": {"type": "number"}, "y1": {"type": "number"}}}

SCHEMA_ADAPTACAO = {
    "type": "object", "additionalProperties": False,
    "required": ["titulo", "sinopse", "tom", "estilo_sugerido", "notas", "personagens", "locais", "itens", "cenas"],
    "properties": {
        "titulo": {"type": "string"}, "sinopse": {"type": "string"}, "tom": {"type": "string"},
        "estilo_sugerido": {"type": "string", "enum": list(A.ESTILOS)},
        "notas": {"type": "array", "items": {"type": "string"}},
        "personagens": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nome", "descricao", "personalidade", "jeito_de_falar", "aparencia_manga_en", "design_en",
                         "mudancas_anime", "genero", "idade", "recorte"],
            "properties": {
                "nome": {"type": "string"}, "descricao": {"type": "string"}, "personalidade": {"type": "string"},
                "jeito_de_falar": {"type": "string"}, "aparencia_manga_en": {"type": "string"}, "design_en": {"type": "string"},
                "mudancas_anime": {"type": "string"},
                "genero": {"type": "string", "enum": ["masculino", "feminino", "neutro"]},
                "idade": {"type": "string", "enum": ["crianca", "jovem", "adulto", "idoso"]},
                "recorte": _CAIXA}}},
        "locais": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nome", "descricao", "prompt_en", "frente_en", "recorte", "props", "lugares"],
            "properties": dict(A.SCHEMA_LOCAL["properties"], recorte=_CAIXA)}},
        "itens": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "required": A.SCHEMA_ITEM["required"] + ["recorte"],
                                             "properties": dict(A.SCHEMA_ITEM["properties"], recorte=_CAIXA)}},
        "cenas": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["titulo", "local", "resumo", "personagens", "paginas", "nota_adaptacao"],
            "properties": {"titulo": {"type": "string"}, "local": {"type": "string"}, "resumo": {"type": "string"},
                           "personagens": {"type": "array", "items": {"type": "string"}},
                           "paginas": {"type": "array", "items": {"type": "integer"}},
                           "nota_adaptacao": {"type": "string"}}}},
    },
}


class MangaErro(A.AnimeErro):
    pass


# ------------------------------------------------------------------ páginas
def _ordem_natural(n: str) -> List[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", n)]


def guardar_paginas(p: Dict[str, Any], arquivos: List[Tuple[str, bytes]], base: str = A._BASE, substituir: bool = False) -> int:
    """As páginas (nome, bytes) → manga/pg_001.jpg… na ordem natural do nome (1, 2, …, 10). → quantas entraram."""
    from PIL import Image
    d = os.path.join(A.pasta(p["id"], base), "manga")
    os.makedirs(d, exist_ok=True)
    pg = [] if substituir else A.paginas_manga(p)
    n = 0
    for nome, dados in sorted(arquivos, key=lambda x: _ordem_natural(os.path.basename(x[0]))):
        if len(pg) >= MAX_PAGINAS:
            break
        try:
            im = Image.open(io.BytesIO(dados))
            im.load()
        except Exception:  # noqa: BLE001
            continue
        im = im.convert("RGB")
        if max(im.size) > 2400:
            im.thumbnail((2400, 2400))
        arq = f"pg_{len(pg) + 1:03d}_{secrets.token_hex(2)}.jpg"
        im.save(os.path.join(d, arq), "JPEG", quality=90)
        pg.append(arq)
        n += 1
    p.setdefault("manga", {})["paginas"] = pg
    if substituir or not p["manga"].get("tempos"):
        p["manga"].pop("fonte", None)
        p["manga"].pop("tempos", None)
    if n:
        A.log(p, f"📖 {n} página(s) do mangá ({len(pg)} no total)")
    return n


def quadros_do_video(cam: str, destino: str, max_quadros: int = 48, cena: float = 0.28, passo: float = 2.5) -> List[Tuple[float, str]]:
    """Os quadros-chave do vídeo: cada corte (mudança de cena) e, num plano longo, um a cada `passo` s. → [(segundo, arquivo)]."""
    import re as _re
    import subprocess
    os.makedirs(destino, exist_ok=True)
    for f in os.listdir(destino):
        os.remove(os.path.join(destino, f))
    filtro = (f"select='isnan(prev_selected_t)+gt(scene\\,{cena})+gte(t-prev_selected_t\\,{passo})',"
              "scale='min(1280,iw)':-2,showinfo")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", cam, "-vf", filtro, "-vsync", "vfr", "-q:v", "3",
                        os.path.join(destino, "q_%05d.jpg")], capture_output=True, text=True, timeout=900)
    tempos = [float(x) for x in _re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    arqs = sorted(f for f in os.listdir(destino) if f.startswith("q_"))
    pares = list(zip(tempos, arqs))
    if len(pares) > max_quadros:  # muitos cortes: espalha
        k = len(pares) / float(max_quadros)
        pares = [pares[int(i * k)] for i in range(max_quadros)]
    return [(t, os.path.join(destino, a)) for t, a in pares]


def guardar_video(p: Dict[str, Any], nome: str, dados: bytes, base: str = A._BASE, usar_audio: bool = True) -> Dict[str, Any]:
    """🎬 v84_238: um VÍDEO de referência (cena de anime, filme, gente real) → os quadros-chave viram as “páginas” (com o
    segundo de cada um) e, se pedir, o áudio vira o áudio do episódio (🎧 modo áudio, transcrito). Daí em diante é o
    mesmo fluxo do mangá: 🤖 ler → personagens/cenários/cenas → aprovar os designs → gerar."""
    d = A.pasta(p["id"], base)
    vd = os.path.join(d, "video")
    os.makedirs(vd, exist_ok=True)
    cam = os.path.join(vd, "referencia" + (os.path.splitext(nome)[1].lower() or ".mp4"))
    with open(cam, "wb") as f:
        f.write(dados)
    pares = quadros_do_video(cam, os.path.join(vd, "_quadros"))
    if not pares:
        raise MangaErro("Não consegui tirar quadros desse vídeo (o arquivo abriu?).")
    arqs = []
    for t, q in pares:
        with open(q, "rb") as f:
            arqs.append((f"{len(arqs) + 1:04d}.jpg", f.read()))
    n = guardar_paginas(p, arqs, base, substituir=True)
    p["manga"].update(fonte="video", tempos=[round(t, 2) for t, _ in pares][:n], video={"arquivo": os.path.basename(cam), "nome": nome[:120]})
    if usar_audio:
        try:
            A.guardar_audio(p, nome, dados, base)
        except A.AnimeErro:
            pass
    A.log(p, f"🎬 vídeo de referência: {n} quadro(s)" + (" + o áudio dele" if usar_audio else ""))
    return {"quadros": n, "audio": bool(usar_audio and A.audio_ok(p, base))}


def recortar(p: Dict[str, Any], pagina: int, caixa: Any, tipo: str, nome: str, base: str = A._BASE, nota: str = "") -> Optional[Dict[str, Any]]:
    """✂ Um pedaço da página (caixa em 0–1: x0, y0, x1, y1) vira uma 📎 referência do personagem/local/item `nome`."""
    from PIL import Image
    cam = A.arquivo_pagina(p, pagina, base)
    if not cam:
        return None
    if isinstance(caixa, dict):
        caixa = [caixa.get(k) for k in ("x0", "y0", "x1", "y1")]
    try:
        x0, y0, x1, y1 = [max(0.0, min(1.0, float(v))) for v in caixa]
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < 0.03 or y1 - y0 < 0.03:
        return None
    im = Image.open(cam).convert("RGB")
    W, H = im.size
    pedaco = im.crop((round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H)))
    b = io.BytesIO()
    pedaco.save(b, "PNG")
    r = A.guardar_referencia(p, f"manga_p{pagina}.png", b.getvalue(), tipo, nome, nota or f"recorte da página {pagina} do mangá", base)
    r["manga"] = {"pagina": int(pagina), "caixa": [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]}
    return r


# ------------------------------------------------------------------ 🤖 ler o mangá → a adaptação
def sys_adaptacao(p: Dict[str, Any]) -> str:
    est = A.ESTILOS.get(p.get("estilo") or "anime", A.ESTILOS["anime"])
    if A.e_video(p):
        return sys_video(p, est)
    return (
        "Você é diretor de uma ADAPTAÇÃO DE MANGÁ PARA ANIME feita do jeito simples: o episódio é montado com IMAGENS (o "
        "fundo de cada lugar, os personagens recortados em poses com 2 quadros e boca que abre quando falam, objetos, "
        "imagens de destaque em tela cheia) e câmera (zoom/pan/tremida) — não é vídeo gerado por IA.\n"
        "Leia TODAS as páginas anexadas (ordem de leitura japonesa: quadros da DIREITA pra esquerda, de cima pra baixo) e "
        "entenda a história, quem é quem, o tom e os lugares. Devolva:\n"
        "- titulo, sinopse (3–6 frases), tom (ex.: comédia do cotidiano com reações exageradas).\n"
        f"- estilo_sugerido: o estilo do catálogo que melhor combina (o usuário escolheu: {est[0]}).\n"
        "- notas: decisões da adaptação (o que vira destaque em tela cheia, o que vira câmera tremida, ritmo, o que corta).\n"
        "- personagens: TODOS que aparecem. 'aparencia_manga_en' = como é NO MANGÁ (em inglês, concreto: cabelo, olhos, "
        "orelhas/cauda, roupa, acessórios, corpo); 'design_en' = a VERSÃO ANIME dele (em inglês): o mesmo personagem "
        f"redesenhado no estilo \"{est[1]}\" — se o estilo for colorido, com as CORES decididas (o mangá é P&B: escolha "
        "cores coerentes de cabelo, olhos, roupa); se o estilo for P&B/monocromático, descreva os TONS (preto, cinza "
        "escuro, cinza claro, branco) e as texturas/hachuras de cada parte — fiel ao mangá; 'mudancas_anime' = o que muda do mangá pra versão anime (em português); "
        "personalidade e jeito_de_falar pelo que se vê nas falas; 'recorte' = onde o personagem aparece MELHOR (de corpo "
        "inteiro ou o maior possível, sozinho no quadro): a página (1, 2, …) e a caixa em frações da página (x0,y0 = canto "
        "de cima à esquerda; x1,y1 = canto de baixo à direita; 0–1).\n"
        "- locais: cada lugar (loja, rua, floresta, casa por fora, sala…). 'prompt_en' = o FUNDO em inglês, VAZIO de "
        "pessoas, visto de frente na altura dos olhos, com o chão embaixo; 'frente_en' = objeto de primeiro plano opcional "
        "(\"\" se não tiver); 'recorte' = o quadro que melhor mostra o lugar.\n"
        "- locais.props: os MÓVEIS em que alguém senta/se apoia/fica atrás (mesa, cadeira, balcão, sofá) — cada um uma "
        "camada separada ('prompt_en' do objeto sozinho; 'camada' 'atras' = cadeira/encosto, 'frente' = mesa/balcão) e "
        "FORA do 'prompt_en' do fundo (o fundo deixa o espaço livre). locais.lugares: onde os personagens ficam (\"atrás da "
        "mesa\" sentado=true, \"na porta\"…), além dos padrões esquerda/centro/direita.\n"
        + A._PL.INSTRUCOES_IA +
        "- 📖 Monte a PLANTA olhando os quadros: junte o que aparece em quadros diferentes do MESMO lugar (a janela de "
        "um quadro, a fornalha de outro) num cômodo só e coerente — cada objeto num lugar fixo, com o tamanho certo.\n"
        "- itens: objetos importantes ('objeto', recortado em cena: a carteira, o saco de doces) e momentos de impacto "
        "que pedem uma imagem em tela cheia ('destaque': o soco, a reação exagerada, o close dramático). 'personagens' = "
        "quem aparece na imagem (vai a referência do design aprovado — mesmo cabelo e cores); 'texto' = o texto ESCRITO "
        "que é parte da cena e da piada (a etiqueta da pasta, o que está no bilhete, inclusive o riscado), exatamente "
        "como deve aparecer — \"\" se nenhum.\n"
        "- 🚫 NUNCA balões, onomatopeias, caixas de narração ou legendas desenhados nas imagens (isso vai pra fala/"
        "narração/legenda/🔊 som). MANTENHA o texto que é parte do mundo e da lógica da cena (placas, etiquetas, papéis, "
        "bilhetes, quadros, telas, diagramas): ele vai no 'texto' do item, exatamente. O 'recorte' de personagem/lugar "
        "deve evitar balões, caixas de texto e onomatopeias sempre que der.\n"
        "- 📖 FIDELIDADE AO MANGÁ: os quadros mais marcantes (reações, revelações, a piada visual) viram itens 'destaque' "
        "com 'recorte' = aquele quadro (a composição é recriada no estilo do anime). Itens sem quadro: 'recorte' com "
        "pagina 0.\n"
        "- 🎞 Crie também destaques de EXEMPLO (cutaways) quando alguém descreve uma situação que não aparece (\"sou "
        "baixinho e excluído\" → ele minúsculo entre alunos gigantes na educação física) e imagens CINEMATOGRÁFICAS pros "
        "momentos fortes (a saída decidida).\n"
        "- locais.props/lugares: o 'prompt_en' do móvel descreve o lado que a CÂMERA vê (a mesa de quem senta de frente "
        "pra câmera mostra o painel da frente; gavetas e vão das pernas ficam escondidos); lugares atrás de mesa = "
        "corpo 'cintura'.\n"
        "- cenas: na ordem, cada uma num local, com quem está, as PÁGINAS que ela adapta e uma 'nota_adaptacao' (ritmo, "
        "câmera, o que destacar). Normalmente uma cena por mudança de lugar/tempo.\n"
        f"- Escreva em {p.get('idioma') or 'português do Brasil'} (menos os campos _en). Use os nomes como aparecem nas falas."
    )


def sys_video(p: Dict[str, Any], est: Tuple[str, str]) -> str:
    """🎬 v84_238: um VÍDEO de referência (cena de anime, filme, gente real) → a mesma estrutura da adaptação, mas com os
    PERSONAGENS DO USUÁRIO no lugar de quem aparece (ou os do vídeo redesenhados, se ele pedir)."""
    return (
        "Você é diretor de um ANIME 2D montado com imagens (cenários, personagens recortados em poses, móveis em camadas, "
        "planos de câmera geral/médio/close/reação) e vai RECRIAR uma cena a partir de um VÍDEO DE REFERÊNCIA. Os quadros "
        "anexados são os cortes do vídeo em ordem, com o segundo de cada um (e, se houver, a transcrição do áudio). Entenda "
        "a encenação: quem está onde, quem entra, as ações, os planos, o ritmo, o lugar e o tom. Devolva:\n"
        "- titulo, sinopse, tom, notas (como a cena foi adaptada: o que virou corte, destaque, câmera).\n"
        f"- estilo_sugerido: o do catálogo que melhor combina (o usuário escolheu: {est[0]}).\n"
        "- personagens: os PERSONAGENS DO PROJETO/das instruções do usuário (ele diz quem faz o papel de quem no vídeo — "
        "\"o homem de terno = Kenta\"). Se ele não disser, crie personagens ORIGINAIS de anime pra cada papel (NUNCA copie o "
        "rosto de uma pessoa real nem um personagem de outra obra): 'aparencia_manga_en' = como a pessoa/personagem do "
        "VÍDEO é (só a roupa/silhueta, pra referência de papel); 'design_en' = o personagem do projeto no estilo "
        f"\"{est[1]}\" (com cores, ou os tons se o estilo for P&B); 'mudancas_anime' = quem faz o papel de quem; 'recorte' = "
        "um quadro onde o papel aparece (só referência de pose — o rosto não é usado).\n"
        "- locais: os lugares do vídeo como cenários de anime ('prompt_en' do fundo VAZIO, de frente, chão embaixo; os "
        "móveis em que sentam/se apoiam em 'props' separados — 'atras'/'frente' — e os 'lugares' onde cada um fica); "
        "'recorte' = o quadro que melhor mostra o lugar.\n"
        "- itens: objetos importantes ('objeto') e momentos de impacto em tela cheia ('destaque'), com 'personagens' e o "
        "'texto' escrito que faz parte da cena (\"\" se nenhum). NUNCA balões, onomatopeias ou legendas nas imagens.\n"
        "- cenas: na ordem, cada uma num local, com quem está, os QUADROS (números) que ela recria em 'paginas' e uma "
        "'nota_adaptacao' (planos, ritmo, o que destacar).\n"
        f"- Escreva em {p.get('idioma') or 'português do Brasil'} (menos os campos _en)."
    )


def prompt_adaptacao(p: Dict[str, Any]) -> str:
    n = len(A.paginas_manga(p))
    L = [f"TÍTULO (provisório): {p.get('titulo') or ''}",
         (f"QUADROS DO VÍDEO DE REFERÊNCIA: {n} (anexados em ordem, cada um com o segundo do vídeo)" if A.e_video(p) else
          f"PÁGINAS DO MANGÁ: {n} (anexadas em ordem, “📖 Página 1”, “📖 Página 2”…)")]
    au = p.get("audio") or {}
    if A.e_video(p) and au.get("transcricao"):
        L.append("🎧 TRANSCRIÇÃO DO ÁUDIO DO VÍDEO (segundo · texto):")
        L += [f"- {x['ini']:.1f} · {x['texto']}" for x in au["transcricao"]][:600]
    if (p.get("premissa") or "").strip():
        L.append(f"INSTRUÇÕES / CONTEXTO DO USUÁRIO:\n{p['premissa']}")
    ja = [c["nome"] for c in p["personagens"]]
    if ja:
        L.append("PERSONAGENS QUE JÁ EXISTEM NO PROJETO (use os mesmos nomes): " + ", ".join(ja))
    return "\n".join(L)


def prompt_copiar(p: Dict[str, Any]) -> str:
    return (sys_adaptacao(p) + "\n\n" + prompt_adaptacao(p) +
            "\n\n(ANEXE as páginas do mangá nesta conversa, em ordem.)\n\nResponda SÓ com um JSON neste formato (JSON Schema):\n"
            + json.dumps(SCHEMA_ADAPTACAO, ensure_ascii=False))


def ler_manga(pid: str, base: str = A._BASE) -> Dict[str, Any]:
    p = A.carregar(pid, base)
    n = len(A.paginas_manga(p))
    if not n:
        raise MangaErro("Envie as páginas do mangá antes.")
    lado = 1400 if n <= 12 else 1100 if n <= 24 else 900
    conteudo: List[Dict[str, Any]] = [{"type": "text", "text": prompt_adaptacao(p)}] + A.blocos_paginas(p, range(1, n + 1), base, lado, MAX_PAGINAS)
    r = A._ia().chamar("anime2d", sys_adaptacao(p), conteudo, schema=SCHEMA_ADAPTACAO, max_tokens=12000, effort="medium",
                       timeout=400, cache_local=False)
    if r is None:
        raise MangaErro("A IA não respondeu (desligada, sem crédito ou erro) — copie o prompt, anexe as páginas em outra IA e cole a resposta.")
    with A._TRAVA:
        p = A.carregar(pid, base)
        rel = aplicar_adaptacao(p, r, base)
        A.salvar(p, base)
    return rel


def _txt(v: Any, n: int = 900) -> str:
    return " ".join(str(v or "").split())[:n]


def aplicar_adaptacao(p: Dict[str, Any], r: Any, base: str = A._BASE) -> Dict[str, Any]:
    """A adaptação (da IA, colada ou do zip) → personagens (base do mangá + design anime pra aprovar), locais, itens,
    cenas com as páginas, e os recortes do mangá como referências. Fica guardada (é o JSON da adaptação)."""
    if not isinstance(r, dict) or not isinstance(r.get("personagens"), list):
        raise MangaErro("A adaptação precisa ter \"personagens\", \"locais\", \"itens\" e \"cenas\".")
    rel = {"personagens": 0, "locais": 0, "itens": 0, "cenas": 0, "recortes": 0}
    n_pag = len(A.paginas_manga(p))
    for x in r.get("personagens") or []:
        if not isinstance(x, dict) or not _txt(x.get("nome")):
            continue
        nome = _txt(x["nome"], 60)
        c = next((y for y in p["personagens"] if R._norm(y["nome"]) == R._norm(nome)), None)
        if c is None:
            c = {"id": A._id("c"), "nome": nome, "refs": [], "voz": "", "pod": {}, "cor": A.CORES[len(p["personagens"]) % len(A.CORES)]}
            p["personagens"].append(c)
        for k in ("descricao", "personalidade", "jeito_de_falar", "aparencia_manga_en", "mudancas_anime"):
            if _txt(x.get(k)):
                c[k] = _txt(x[k], 1200)
        if _txt(x.get("design_en")):
            c["design_en"] = _txt(x["design_en"], 1200)
            c["aparencia_en"] = c["design_en"]  # as poses seguem a versão anime
            c.setdefault("design", {})
        for k in ("genero", "idade"):
            if x.get(k):
                c[k] = x[k]
        rel["personagens"] += 1
        rc = x.get("recorte")
        if isinstance(rc, dict) and 1 <= int(rc.get("pagina") or 0) <= n_pag and not c.get("refs") and not A.e_video(p):
            if recortar(p, int(rc["pagina"]), rc, "personagem", nome, base, "recorte do mangá (a IA escolheu)"):
                rel["recortes"] += 1
    for x in r.get("locais") or []:
        if not isinstance(x, dict) or not _txt(x.get("nome")):
            continue
        nome = _txt(x["nome"], 60)
        lo = next((y for y in p["locais"] if R._norm(y["nome"]) == R._norm(nome)), None)
        if lo is None:
            lo = {"id": A._id("l"), "nome": nome, "refs": [], "img": {}, "frente": {}}
            p["locais"].append(lo)
        for k in ("descricao", "prompt_en", "frente_en"):
            if x.get(k) is not None and (_txt(x.get(k)) or k == "frente_en"):
                lo[k] = _txt(x[k])
        A.aplicar_props_lugares(lo, x)
        rel["locais"] += 1
        rc = x.get("recorte")
        if isinstance(rc, dict) and 1 <= int(rc.get("pagina") or 0) <= n_pag and not lo.get("refs"):
            if recortar(p, int(rc["pagina"]), rc, "local", nome, base, "recorte do mangá (a IA escolheu)"):
                rel["recortes"] += 1
    for x in r.get("itens") or []:
        if not isinstance(x, dict) or not _txt(x.get("nome")):
            continue
        nome = _txt(x["nome"], 60)
        it = next((y for y in p["itens"] if R._norm(y["nome"]) == R._norm(nome)), None)
        if it is None:
            it = {"id": A._id("i"), "nome": nome, "refs": [], "img": {}}
            p["itens"].append(it)
        it["tipo"] = x.get("tipo") if x.get("tipo") in ("objeto", "destaque") else it.get("tipo") or "objeto"
        if _txt(x.get("prompt_en")):
            it["prompt_en"] = _txt(x["prompt_en"])
        A.aplicar_item_extras(p, it, x)
        rc = x.get("recorte")
        if isinstance(rc, dict) and 1 <= int(rc.get("pagina") or 0) <= n_pag and not it.get("refs"):
            if recortar(p, int(rc["pagina"]), rc, "item", nome, base, "o quadro do mangá (composição a recriar)"):
                it["painel"] = True
                rel["recortes"] += 1
        rel["itens"] += 1
    cenas = [s for s in r.get("cenas") or [] if isinstance(s, dict)]
    if cenas:
        A.aplicar_plano(p, {"personagens": [], "locais": [], "itens": [], "titulo": r.get("titulo") or p["titulo"],
                            "sinopse": r.get("sinopse") or "", "duracao_min": 0,
                            "cenas": [{"titulo": s.get("titulo") or f"Cena {k + 1}", "local": s.get("local") or "",
                                       "resumo": s.get("resumo") or "", "personagens": s.get("personagens") or [],
                                       "inicio_audio": 0} for k, s in enumerate(cenas)]})
        for s, x in zip(p["cenas"], cenas):
            s["paginas"] = [int(n) for n in x.get("paginas") or [] if str(n).isdigit() and 1 <= int(n) <= n_pag][:12]
            if _txt(x.get("nota_adaptacao")):
                s["nota_adaptacao"] = _txt(x["nota_adaptacao"], 600)
        rel["cenas"] = len(cenas)
        if not (p.get("plano") or {}).get("duracao_min") or float(p.get("duracao_alvo") or 0) <= 0:
            p["plano"]["duracao_min"] = max(0.5, round(sum(len(s["paginas"]) for s in p["cenas"]) * 0.45, 1))  # ~27 s por página
    if (not (p.get("titulo") or "").strip() or p["titulo"] == "Animação sem título") and _txt(r.get("titulo")):
        p["titulo"] = _txt(r["titulo"], 200)
    if not (p.get("premissa") or "").strip() and _txt(r.get("sinopse")):
        p["premissa"] = _txt(r["sinopse"], 4000)
    p.setdefault("manga", {})["adaptacao"] = {
        "titulo": _txt(r.get("titulo"), 200), "sinopse": _txt(r.get("sinopse"), 2000), "tom": _txt(r.get("tom"), 300),
        "estilo_sugerido": r.get("estilo_sugerido") if r.get("estilo_sugerido") in A.ESTILOS else "",
        "notas": [_txt(n, 400) for n in r.get("notas") or []][:30], "quando": time.time()}
    A.vincular_referencias(p)
    A.log(p, f"📖 adaptação: {rel['personagens']} personagem(ns), {rel['locais']} local(is), {rel['itens']} item(ns), "
             f"{rel['cenas']} cena(s), {rel['recortes']} recorte(s) do mangá")
    return rel


def json_adaptacao(p: Dict[str, Any]) -> Dict[str, Any]:
    """⬇ O JSON da adaptação (o "segundo JSON"): do mangá → como fica no anime, com o estado de aprovação."""
    ad = (p.get("manga") or {}).get("adaptacao") or {}
    refs = {r["arquivo"]: r for r in p["referencias"]}
    out = {"formato": "anime2d_adaptacao_v1", "titulo": p["titulo"], "sinopse": ad.get("sinopse") or "", "tom": ad.get("tom") or "",
           "estilo": p["estilo"], "estilo_en": A.estilo_en(p), "estilo_sugerido": ad.get("estilo_sugerido") or "",
           "notas": ad.get("notas") or [], "paginas": len(A.paginas_manga(p)), "personagens": [], "locais": [], "itens": [], "cenas": []}
    for c in p["personagens"]:
        rc = next(((refs.get(a) or {}).get("manga") for a in c.get("refs") or [] if (refs.get(a) or {}).get("manga")), None)
        d = c.get("design") or {}
        out["personagens"].append({
            "nome": c["nome"], "descricao": c.get("descricao") or "", "personalidade": c.get("personalidade") or "",
            "jeito_de_falar": c.get("jeito_de_falar") or "", "aparencia_manga_en": c.get("aparencia_manga_en") or "",
            "design_en": c.get("design_en") or c.get("aparencia_en") or "", "mudancas_anime": c.get("mudancas_anime") or "",
            "genero": c.get("genero") or "neutro", "idade": c.get("idade") or "adulto", "voz": c.get("voz") or "",
            "recorte": ({"pagina": rc["pagina"], "x0": rc["caixa"][0], "y0": rc["caixa"][1], "x1": rc["caixa"][2], "y1": rc["caixa"][3]}
                        if rc else None),
            "design": {"estado": "aprovado" if d.get("aprovado") else d.get("estado") or ("sem design" if not d else "falta gerar"),
                       "versoes": len(d.get("versoes") or [])}})
    for lo in p["locais"]:
        rc = next(((refs.get(a) or {}).get("manga") for a in lo.get("refs") or [] if (refs.get(a) or {}).get("manga")), None)
        out["locais"].append({"nome": lo["nome"], "descricao": lo.get("descricao") or "", "prompt_en": lo.get("prompt_en") or "",
                              "frente_en": lo.get("frente_en") or "",
                              "props": [{k: pr.get(k) for k in ("nome", "prompt_en", "camada", "x", "y", "w") if pr.get(k) is not None}
                                        for pr in lo.get("props") or []],
                              "lugares": [dict(lg) for lg in lo.get("lugares") or []], "chao": lo.get("chao") or {},
                              "recorte": ({"pagina": rc["pagina"], "x0": rc["caixa"][0], "y0": rc["caixa"][1], "x1": rc["caixa"][2],
                                           "y1": rc["caixa"][3]} if rc else None)})
    for it in p["itens"]:
        out["itens"].append({"nome": it["nome"], "tipo": it.get("tipo") or "objeto", "prompt_en": it.get("prompt_en") or "",
                             "personagens": it.get("personagens") or [], "texto": it.get("texto") or ""})
    for s in p["cenas"]:
        lo = next((x for x in p["locais"] if x["id"] == s.get("local")), None)
        out["cenas"].append({"titulo": s.get("titulo") or "", "local": (lo or {}).get("nome") or "", "resumo": s.get("resumo") or "",
                             "personagens": [A.nome_de(p, x) for x in s.get("personagens") or []], "paginas": s.get("paginas") or [],
                             "nota_adaptacao": s.get("nota_adaptacao") or "", "momentos": len(s.get("momentos") or [])})
    return out


# ------------------------------------------------------------------ 🎨 o design anime (pra aprovar)
def ref_design(p: Dict[str, Any], c: Dict[str, Any], base: str = A._BASE) -> Tuple[Optional[str], List[str]]:
    """A colagem do design: os recortes do mangá, a 🌈 foto colorida (se tiver) e o estilo — e o que é cada painel."""
    from PIL import Image
    import personagens_limpeza as L
    cams, rot = [], []
    for cam in A.refs_de(p, c, base)[:2]:
        cams.append(cam)
        rot.append("the manga picture of the character (the SHAPE and design to follow)")
    cor = A.cor_ref(p, c, base)
    if cor:
        cams.append(cor)
        rot.append("a COLORED picture of the same character (ONLY its REAL COLORS)")
    for cam in A.refs_estilo(p, base)[:1]:
        cams.append(cam)
        rot.append("the ART STYLE reference")
    ims = []
    for cam in cams:
        try:
            im = Image.open(cam).convert("RGBA")
            fundo = Image.new("RGBA", im.size, (128, 128, 128, 255))
            fundo.alpha_composite(im)
            ims.append(fundo.convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
    if not ims or len(ims) != len(rot):
        return A._ref_flow(p, c, base), []
    col = L.colagem(ims) if len(ims) > 1 else ims[0]
    d = os.path.join(A.pasta(p["id"], base), "imagens")
    os.makedirs(d, exist_ok=True)
    cam = os.path.join(d, f"_ref_design_{c['id']}_{secrets.token_hex(2)}.png")
    col.save(cam)
    return cam, rot


def prompt_design(p: Dict[str, Any], c: Dict[str, Any], paineis: Optional[List[str]] = None) -> str:
    pre = ""
    if paineis and len(paineis) > 1:
        pre = ("The reference image has " + str(len(paineis)) + " panels side by side, from left to right: "
               + "; ".join(f"{k + 1}) {t}" for k, t in enumerate(paineis)) + ". ")
    if c.get("cor_ref"):
        pre += ("COLORS: copy the REAL colors of the COLORED picture exactly (hair, eyes, skin, outfit, accessories) — "
                "they win over any color written below. ")
    return pre + (f"Official anime character design of {c['nome']} for the anime adaptation of a manga: "
            f"{c.get('design_en') or c.get('aparencia_en') or c['nome']}. "
            "Redraw the character from the manga reference faithfully (same face shape, hairstyle, ears/tail, outfit, "
            "accessories and body proportions) as an anime character with the colors/tones described. FULL BODY from head to "
            "feet, standing, 3/4 view turned to the RIGHT, neutral expression, the whole figure inside the image with "
            "margin, one single figure, plain flat light gray background, no panels, no screentone background. " + A.SEM_TEXTO + " "
            f"ART STYLE: {A.estilo_en(p)}.")[:3900]


def gerar_designs(pid: str, cids: Optional[List[str]] = None, pedido: str = "", base: str = A._BASE) -> Dict[str, Any]:
    """🎨 O design anime de cada personagem no 🚀 Flow em massa (com os recortes do mangá + o estilo de referência).
    Sem cids: os que ainda não têm design nem estão na fila."""
    import flow_lote
    with A._TRAVA:
        p = A.carregar(pid, base)
        alvo = []
        for c in p["personagens"]:
            d = c.get("design")
            if d is None and not c.get("design_en"):
                continue
            d = c.setdefault("design", {})
            if cids:
                if c["id"] in cids and d.get("estado") not in ("fila", "gerando"):
                    alvo.append(c)
            elif not d.get("arquivo") and d.get("estado") not in ("fila", "gerando"):
                alvo.append(c)
        if not alvo:
            raise MangaErro("Nada pra gerar (sem design anime pedido, já gerado ou na fila).")
        itens = []
        for c in alvo:
            ref, paineis = ref_design(p, c, base)
            pr = prompt_design(p, c, paineis)
            if pedido:
                pr = (pr + " " + pedido)[:3990]
            it = {"prompt": pr, "tipo": "imagem", "origem": "anime2d"}
            if ref:
                it["referencia_arquivo"] = ref
            itens.append(it)
        lote = flow_lote.lote()
        try:
            feitos = lote.adicionar(itens, proporcao="3:4", quantidade="x1")
        except ValueError as exc:
            raise MangaErro(str(exc))
        for c, j in zip(alvo, feitos):
            c["design"].update(estado="fila", job=j["id"], erro=None, msg="⏳ na fila do Flow", recortar=False)
        A.log(p, f"🎨 {len(alvo)} design(s) anime pro Flow" + (f" (pedido: {pedido[:80]})" if pedido else ""))
        A.salvar(p, base)
    aviso = ""
    try:
        lote.iniciar()
    except Exception as exc:  # noqa: BLE001
        aviso = f"o Flow em massa não ligou agora ({str(exc)[:160]}) — ▶ Continuar na aba Flow"
    return {"enviadas": len(alvo), "aviso": aviso}


def aprovar_design(p: Dict[str, Any], cid: str, arquivo: str = "", aprovar: bool = True) -> Dict[str, Any]:
    c = next((x for x in p["personagens"] if x["id"] == cid), None)
    if not c:
        raise MangaErro("Personagem não encontrado.")
    d = c.setdefault("design", {})
    if not aprovar:
        d.pop("aprovado", None)
        A.log(p, f"🎨 {c['nome']}: aprovação do design desfeita")
        return d
    arquivo = arquivo or d.get("arquivo") or ""
    if not arquivo or arquivo not in (d.get("versoes") or [d.get("arquivo")]):
        raise MangaErro("Essa versão do design não existe.")
    d["aprovado"] = arquivo
    d["arquivo"] = arquivo
    d["aprovado_em"] = time.time()
    A.log(p, f"✔ {c['nome']}: design anime aprovado — as poses podem ser geradas")
    return d


def design_seu(p: Dict[str, Any], cid: str, dados: bytes, base: str = A._BASE) -> Dict[str, Any]:
    c = next((x for x in p["personagens"] if x["id"] == cid), None)
    if not c:
        raise MangaErro("Personagem não encontrado.")
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(dados))
        im.load()
    except Exception:  # noqa: BLE001
        raise MangaErro("Não consegui abrir essa imagem.")
    A.guardar_img(p, c.setdefault("design", {}), im, False, base, origem="sua")
    return c["design"]
