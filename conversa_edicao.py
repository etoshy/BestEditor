"""
conversa_edicao.py
==================

💬 CONVERSAR COM A IA NO ESTÚDIO — a pessoa seleciona uma parte (um trecho, uma emenda, um destaque, vários itens…
ou nada = o vídeo todo) e escreve o que quer: "deixa mais dramático", "tira esse zoom", "troca a transição por algo
mais suave", "muda o texto desse destaque pra …". A IA responde com o MESMO formato do prompt de edição (só o que
muda) e uma frase curta; o Estúdio aplica na hora (com ↩ desfazer).

  montar_prompt(job, estado, pedido, foco, historico) → texto pra IA
  ler(texto, job, estado, palavras)                    → plano validado (prompt_edicao.ler_resposta) + resposta
                                                         + mudar_destaques / remover_destaques
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import dp_destaques
import dp_visual
import prompt_edicao as pe

VIZINHOS = 2          # trechos de contexto de cada lado do que está selecionado
MAX_TRECHOS = 160     # vídeo todo sem seleção: até isso de linhas (o resto vira resumo)
MAX_HISTORICO = 6


def _t(s: float) -> str:
    return pe._t(float(s or 0))


def foco_em_trechos(foco: Dict[str, Any], segs: List[Dict[str, Any]], destaques: List[Dict[str, Any]]) -> List[int]:
    """Índices (0-based) dos trechos que a seleção toca. Vazio = o vídeo todo."""
    idx: set = set()
    for i in foco.get("trechos") or []:
        if isinstance(i, int) and 0 <= i < len(segs):
            idx.add(i)
    for i in foco.get("emendas") or []:  # emenda i = entre o trecho i e o i+1
        if isinstance(i, int) and 0 <= i < len(segs):
            idx.update(k for k in (i, i + 1) if k < len(segs))
    for k in foco.get("destaques") or []:
        if isinstance(k, int) and 0 <= k < len(destaques):
            d = destaques[k]
            idx.update(i for i, s in enumerate(segs) if float(s["start"]) < float(d.get("end") or 0) and float(s["end"]) > float(d.get("start") or 0))
    try:
        a, b = float(foco["start"]), float(foco["end"])
        idx.update(i for i, s in enumerate(segs) if float(s["start"]) < b and float(s["end"]) > a)
    except (KeyError, TypeError, ValueError):
        pass
    return sorted(idx)


def sistema() -> str:
    """A parte FIXA (catálogos + regras + formato): vai no "system" da IA, que fica em cache entre as mensagens."""
    L: List[str] = ["Você é o editor de vídeo ao meu lado, no meu editor. O vídeo já está montado; eu vou pedir mudanças "
                    "e você responde SÓ com um JSON com o que muda (o editor aplica na hora)."]
    # ---------------- catálogos (ids que valem)
    L.append("\n## Catálogos (use SÓ estes ids)")
    L.append("Transições: " + "; ".join(f"{k} = {v}" for k, v in pe._transicoes_validas().items() if k != "none") + "; none = corte seco")
    L.append("Efeitos: " + "; ".join(f"{e['id']} = {e['rotulo']}" + (" (só FOTO)" if dp_visual.efeito_e_movimento(e["id"]) else "")
                                     for e in dp_visual.efeitos() if e["id"] != "none"))
    L.append("Entradas/saídas: " + "; ".join(f"{e['id']} = {e['rotulo']}" for e in dp_visual.entradas() if e["id"] != "none"))
    L.append("Filtros de cor (um pro vídeo todo): " + ", ".join(f["id"] for f in dp_visual.filtros()))
    L.append("Estilos de destaque (id | papel | palavras | quando):\n" + dp_destaques.bloco_para_prompt())
    L.append("Destaque — campos de estilo opcionais: zona (" + ", ".join(pe.ZONAS) + "), enfase [palavras], fonte ("
             + ", ".join(k for k in dp_destaques._FONTE if k != "default") + "), maiusculas, escala 0.6–1.6, anim_entrada ("
             + ", ".join(dp_destaques.ANIMS_ENTRADA) + "), anim_saida (" + ", ".join(dp_destaques.ANIMS_SAIDA) + "), cor #hex.")
    import video_assembler as _va
    L.append("Trecho com FOTO: camera = " + ", ".join(sorted(_va._ZOOM_DIRECTIONS_VALIDAS)) + "; bordas = black | zoom | mosaic | smart.")

    L.append("""
## Regras
1. Mude SÓ o que eu pedi. Trechos/destaques que não mudam ficam de fora do JSON.
2. Transição na emenda entre T(n) e T(n+1) vai no trecho n. Efeitos de câmera só em FOTO.
3. Pra tirar um efeito/entrada/saída/cena: valor null. Pra tirar a transição: "none".
4. Destaque que já existe: mude em "mudar_destaques" (pelo número D…) ou tire em "remover_destaques". Destaque NOVO em "destaques" (ancorado na fala: "palavra" = primeira palavra dita).
5. Se o pedido não der pra fazer com o que existe, diga em "resposta" e não mude nada.
6. "resposta": 1–2 frases em português, dizendo o que você mudou.

## Responda SÓ com este JSON
{
  "resposta": "Troquei o zoom do T5 por um balanço suave e tirei a entrada.",
  "trechos": [{"trecho": 5, "efeito": "id ou null", "entrada": "id ou null", "saida": "id ou null", "transition": "id ou none", "transition_duration": 0.6, "camera": "in", "template": "id ou null"}],
  "mudar_destaques": [{"destaque": 3, "estilo": "id", "texto": "novo texto", "zona": "terco_inf", "anim_entrada": "id", "cor": "#RRGGBB"}],
  "remover_destaques": [4],
  "destaques": [{"estilo": "id", "texto": "texto curto", "palavra": "primeira palavra falada", "start": 12.3}],
  "filtro_cor": "id (só se eu pedir a cor do vídeo)"
}""")
    return "\n".join(L)


def montar_prompt(job: Dict[str, Any], estado: Dict[str, Any], pedido: str, foco: Optional[Dict[str, Any]] = None,
                  historico: Optional[List[Dict[str, str]]] = None) -> str:
    segs = estado.get("segmentos") or job.get("pending_segments") or []
    destaques = estado.get("destaques") if isinstance(estado.get("destaques"), list) else (job.get("destaques") or [])
    foco = foco or {}
    alvo = foco_em_trechos(foco, segs, destaques)
    total = float(job.get("total_duration") or (segs[-1]["end"] if segs else 0))
    if alvo:
        janela = sorted({k for i in alvo for k in range(i - VIZINHOS, i + VIZINHOS + 1) if 0 <= k < len(segs)})
        ini, fim = float(segs[janela[0]]["start"]), float(segs[janela[-1]]["end"])
    else:
        janela, ini, fim = list(range(min(len(segs), MAX_TRECHOS))), 0.0, total

    L: List[str] = ["## O que eu selecionei"]
    if alvo:
        partes = []
        if foco.get("trechos"):
            partes.append("trecho(s) " + ", ".join(f"T{i + 1}" for i in foco["trechos"] if isinstance(i, int)))
        if foco.get("emendas"):
            partes.append("emenda(s) " + ", ".join(f"T{i + 1}→T{i + 2}" for i in foco["emendas"] if isinstance(i, int)))
        if foco.get("destaques"):
            partes.append("destaque(s) " + ", ".join(f"D{k + 1}" for k in foco["destaques"] if isinstance(k, int)))
        if foco.get("start") is not None and not partes:
            partes.append(f"o pedaço {_t(foco['start'])}→{_t(foco['end'])}")
        L.append("; ".join(partes) + f" (de {_t(ini)} a {_t(fim)}). Quando eu falar \"esse\", \"aqui\", \"isso\", é ISSO. "
                 "Mexa só aí, a menos que eu peça outra coisa.")
    else:
        L.append("Nada — o pedido vale pro vídeo todo (ou pro que eu citar: \"T5\", \"o destaque D3\", \"em 1:20\").")

    # ---------------- o que está na tela agora
    L.append(f"\n## Timeline ({len(segs)} trechos, {_t(total)})" + (" — a parte selecionada e os vizinhos:" if alvo else ":"))
    for i in janela:
        s = segs[i]
        ov = s.get("override_source") or {}
        midia = "foto" if (ov.get("kind") or s.get("media_type")) == "image" else "vídeo"
        extra = [f"{k}={s.get(k)}" for k in ("transition", "efeito", "entrada", "saida", "template") if s.get(k)]
        fala = (s.get("_fala") or "").strip()
        marca = " ◀ SELECIONADO" if i in alvo else ""
        L.append(f"T{i + 1} [{_t(s['start'])}→{_t(s['end'])}] {midia} '{s.get('query', '')}'"
                 + (" · " + ", ".join(extra) if extra else " · sem efeito") + (f" · fala: \"{fala[:140]}\"" if fala else "") + marca)
    if not alvo and len(segs) > MAX_TRECHOS:
        L.append(f"(… mais {len(segs) - MAX_TRECHOS} trechos depois — cite pelo número se precisar)")
    dsel = set(foco.get("destaques") or [])
    ds = [(k, d) for k, d in enumerate(destaques) if float(d.get("end") or 0) > ini and float(d.get("start") or 0) < fim]
    if ds:
        L.append("\nDestaques (texto na tela):")
        for k, d in ds[:80]:
            L.append(f"D{k + 1} {d.get('estilo')} [{_t(d.get('start'))}→{_t(d.get('end'))}] \"{(d.get('texto') or '')[:60]}\""
                     + (" ◀ SELECIONADO" if k in dsel else ""))
    blocos = [b for b in (estado.get("blocos") or job.get("segments") or []) if (b.get("text") or "").strip()
              and float(b.get("end") or 0) > ini and float(b.get("start") or 0) < fim]
    if blocos:
        L.append("\nFala nessa parte:")
        for b in blocos[:120]:
            L.append(f"[{_t(b['start'])}→{_t(b['end'])}] {b['text'].strip()}")

    hist = [h for h in (historico or []) if isinstance(h, dict)][-MAX_HISTORICO:]
    if hist:
        L.append("\n## Conversa até agora")
        for h in hist:
            L.append(f"Eu: {str(h.get('pedido') or '')[:400]}")
            if h.get("resposta"):
                L.append(f"Você: {str(h['resposta'])[:400]}")

    L.append("\n## Meu pedido agora\n" + pedido.strip()[:2000])
    try:
        import idiomas
        L.append(idiomas.regra_para_prompt(idiomas.normalizar(job.get("language")) or "pt"))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(L)


def ler(texto: str, job: Dict[str, Any], estado: Dict[str, Any], palavras: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Valida a resposta → plano (mesmo formato do /edicao/resposta) + resposta + mudar/remover destaques."""
    segs = estado.get("segmentos") or job.get("pending_segments") or []
    destaques = estado.get("destaques") if isinstance(estado.get("destaques"), list) else (job.get("destaques") or [])
    d = pe.extrair_json(texto)
    total = float(job.get("total_duration") or (segs[-1]["end"] if segs else 0))
    foto = [((s.get("override_source") or {}).get("kind") or s.get("media_type")) == "image" for s in segs]
    plano = pe.ler_resposta(texto, len(segs), total, palavras, foto,
                            direcao=pe.direcao_escolhida(job, estado.get("direcao"), estado.get("kit")))  # 🎬 só o que a direção tem
    plano["substituir_destaques"] = False  # na conversa, destaque novo SOMA (nunca apaga os outros)
    plano["resposta"] = str(d.get("resposta") or d.get("observacoes") or "").strip()[:600]
    avisos = plano["avisos"]
    ids = [str(x.get("id") or "") for x in destaques]

    def _num(v) -> Optional[int]:
        try:
            k = int(str(v).lstrip("Dd")) - 1
        except (TypeError, ValueError):
            return None
        return k if 0 <= k < len(destaques) else None

    remover = []
    for v in d.get("remover_destaques") or []:
        k = _num(v)
        if k is None:
            avisos.append(f"Destaque {v} não existe — não removi.")
        elif ids[k]:
            remover.append(ids[k])
    mudar = []
    for x in d.get("mudar_destaques") or []:
        if not isinstance(x, dict):
            continue
        k = _num(x.get("destaque", x.get("indice")))
        if k is None or not ids[k]:
            avisos.append(f"Destaque {x.get('destaque')} não existe — não mudei.")
            continue
        m: Dict[str, Any] = {"id": ids[k]}
        if x.get("estilo"):
            if dp_destaques.estilo(str(x["estilo"])):
                m["estilo"] = str(x["estilo"])
            else:
                avisos.append(f"D{k + 1}: estilo '{x['estilo']}' desconhecido.")
        if isinstance(x.get("texto"), str) and x["texto"].strip():
            m["texto"] = x["texto"].strip()[:300]
        for c in ("start", "end"):
            try:
                if x.get(c) is not None:
                    m[c] = max(0.0, min(total or 1e9, float(x[c])))
            except (TypeError, ValueError):
                pass
        m.update(pe.estilo_de_texto(x, avisos))
        if len(m) > 1:
            mudar.append(m)
    plano["remover_destaques"] = remover
    plano["mudar_destaques"] = mudar
    return plano
