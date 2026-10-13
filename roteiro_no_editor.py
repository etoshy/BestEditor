"""
roteiro_no_editor.py
====================

📝 PROJETO DO ROTEIRO DO YOUTUBE NO EDITOR (v84_71).

No "Novo vídeo" dá pra escolher um projeto do Roteiro do YouTube (igual a um 🕵️ modelo de vídeo). Aí:

  * cada cena da lista (filme/série/anime/jogo…) que tem o marcador [CENA n] no roteiro é achada na
    NARRAÇÃO (as palavras logo depois do marcador, nas palavras com tempo da transcrição);
  * o prompt da 1ª IA recebe essas cenas com o tempo — "neste ponto, YouTube, buscando X";
  * depois da resposta, o trecho que cobre cada cena vira YouTube com a busca da cena (se a IA não fez);
  * a cena que já tem LINK escolhido (com início/fim) na página do roteiro é baixada e cortada sozinha;
  * as outras ficam no painel 🎬 Vídeos do YouTube — o botão 🤖 acha o momento;
  * e os capítulos da descrição vão pro tempo do vídeo final (capitulos_video.py).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import roteiros_yt


def _marca(cid: Any) -> re.Pattern:
    return re.compile(r"(?:\[{1,2}|\()\s*(?:cena|scene|escena)\s*" + re.escape(str(cid)) + r"\b[^\]\)\n]{0,160}(?:\]{1,2}|\))", re.I)


def cenas_com_tempo(p: Dict[str, Any], palavras: List[Dict[str, Any]], duracao: Optional[float]) -> List[Dict[str, Any]]:
    """As cenas do projeto (menos as removidas) com o segundo da NARRAÇÃO em que cada uma entra (None = sem marcador)."""
    import chamadas
    res = p.get("resultado") or {}
    bruto = str(res.get("roteiro_final") or (p.get("analise") or {}).get("roteiro") or "")
    falado = roteiros_yt.roteiro_para_voz(p)
    n_total = max(1, len(roteiros_yt._toks(falado)))
    cenas = [c for c in roteiros_yt.cenas_atuais(p) if (c.get("como_ficou") or "") != "removida"]
    frases, idx = [], []
    for k, c in enumerate(cenas):
        m = _marca(c.get("id")).search(bruto)
        if not m:
            continue
        depois = chamadas.tirar_marcas_de_cena(bruto[m.end():])[0]
        antes = chamadas.tirar_marcas_de_cena(bruto[:m.start()])[0]
        frase = " ".join(chamadas.remover_marcadores(depois).split()[:8])
        posicao = len(roteiros_yt._toks(antes)) / n_total
        frases.append((frase, posicao))
        idx.append(k)
    tempos = roteiros_yt.tempos_de_frases(falado, frases, palavras, duracao) if frases else []
    t_por_cena = dict(zip(idx, tempos))
    out = []
    for k, c in enumerate(cenas):
        t = t_por_cena.get(k)
        out.append({"id": c.get("id"), "obra": c.get("obra") or "", "momento": c.get("momento") or "",
                    "busca": (c.get("busca_youtube") or f"{c.get('obra') or ''} {c.get('momento') or ''}").strip()[:160],
                    "link": c.get("link") or "", "link_inicio": c.get("link_inicio") or "", "link_fim": c.get("link_fim") or "",
                    "como_ficou": c.get("como_ficou") or "", "tempo": None if t is None else round(float(t), 2)})
    return out


def _mmss(s: float) -> str:
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


def bloco_prompt(p: Dict[str, Any], cenas: List[Dict[str, Any]], com_youtube: bool = True) -> str:
    """`com_youtube=False` (a fonte youtube NÃO foi marcada no vídeo): as cenas entram só como contexto, pra
    ilustrar com os bancos marcados — nada de "provider": "youtube"."""
    if not cenas:
        return ""
    titulo = p.get('titulo') or p.get('url') or 'Roteiro do YouTube'
    if not com_youtube:
        L = ["", f"## 📝 Cenas do roteiro (projeto “{titulo}”) — contexto",
             "O roteiro foi escrito em cima destas cenas (de filmes, séries, animes, jogos…). A fonte YouTube NÃO está "
             "marcada neste vídeo: NÃO use \"youtube\". Nos trechos dessas cenas, ilustre com os bancos marcados acima, "
             "com uma busca que combine com o que acontece na cena."]
        for c in cenas:
            onde = f"em ~{_mmss(c['tempo'])} da narração" if c.get("tempo") is not None else "(sem marcador: ache pelo assunto)"
            L.append(f"- CENA {c['id']} {onde}: {c['obra']} — {c['momento'][:160]}")
        return "\n".join(L)
    L = ["", f"## 📝 Cenas do roteiro (projeto “{titulo}”) — use o YouTube nelas",
         "O roteiro foi escrito em cima destas cenas (de filmes, séries, animes, jogos…). No trecho em que cada uma entra, use "
         "`\"provider\": \"youtube\"` com a busca indicada (a cena de verdade, não uma imagem de banco). Sem o tempo, ache o "
         "momento pelo assunto na transcrição."]
    for c in cenas:
        onde = f"em ~{_mmss(c['tempo'])} da narração" if c.get("tempo") is not None else "(sem marcador: ache pelo assunto)"
        L.append(f"- CENA {c['id']} {onde}: {c['obra']} — {c['momento'][:160]} → busca: \"{c['busca']}\"")
    return "\n".join(L)


def aplicar(segmentos: List[Any], cenas: List[Dict[str, Any]]) -> List[int]:
    """O trecho que cobre o tempo de cada cena vira YouTube com a busca da cena (se ainda não é YouTube nem tem
    arquivo escolhido). Funciona com dicts ou VideoSegment. → índices dos trechos de cena."""
    def g(s, k, d=None):
        return s.get(k, d) if isinstance(s, dict) else getattr(s, k, d)

    def put(s, k, v):
        if isinstance(s, dict):
            s[k] = v
        else:
            setattr(s, k, v)
    usados = []
    for c in cenas:
        t = c.get("tempo")
        if t is None:
            continue
        i = next((k for k, s in enumerate(segmentos) if float(g(s, "start", 0)) <= t < float(g(s, "end", 0))), None)
        if i is None and segmentos and t >= float(g(segmentos[-1], "start", 0)):
            i = len(segmentos) - 1
        if i is None or i in usados:
            continue
        s = segmentos[i]
        usados.append(i)
        put(s, "roteiro_cena", c["id"])
        if g(s, "override_source"):
            continue
        if g(s, "provider") != "youtube":
            put(s, "provider", "youtube")
            put(s, "query", c["busca"])
            put(s, "media_type", "video")
    return usados


def escolha_do_link(c: Dict[str, Any], duracao_trecho: float) -> Optional[Dict[str, Any]]:
    """A cena tem link escolhido na página do roteiro → a escolha pronta pro painel (url, início, fim)."""
    if not c.get("link"):
        return None
    import youtube_clipper as yc
    try:
        ini = yc.parse_tempo(c["link_inicio"]) if c.get("link_inicio") else 0.0
    except Exception:  # noqa: BLE001
        ini = 0.0
    try:
        fim = yc.parse_tempo(c["link_fim"]) if c.get("link_fim") else ini + duracao_trecho
    except Exception:  # noqa: BLE001
        fim = ini + duracao_trecho
    if fim <= ini:
        fim = ini + max(1.0, duracao_trecho)
    return {"url": c["link"], "inicio": round(ini, 2), "fim": round(fim, 2), "titulo": f"{c['obra']} — {c['momento']}"[:200],
            "miniatura_url": "", "roteiro": True}
