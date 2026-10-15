"""
Prompt de EDIÇÃO (segunda etapa, feita no Estúdio).

O primeiro prompt (prompt_builder) só decide as mídias, cenas e textos
simples. Este aqui manda pra IA a edição COMO ESTÁ: a direção escolhida e o
que ela permite (com %/pesos), a timeline trecho a trecho (mídia, cena,
transição, efeitos), os destaques e gráficos atuais e a fala com os tempos
(transcrição/SRT) — e pede um JSON mais caprichado: transições e efeitos por
trecho, cenas com textos, destaques ancorados na fala, GRÁFICOS com os dados
citados, filtro, paleta, legenda e sons.

`montar_prompt(job, estado)` → texto pra copiar.
`ler_resposta(texto, ...)` → plano validado (ids desconhecidos saem, com aviso)
que o Estúdio aplica (com desfazer).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

import cenas_dp
import dp_destaques
import dp_direcao
import dp_fundos
import dp_graficos
import dp_visual


def _t(s: float) -> str:
    s = max(0.0, float(s))
    return f"{int(s // 60)}:{s % 60:04.1f}"


# ------------------------------------------------------------------ catálogos (filtrados pela direção)
def _transicoes_validas() -> Dict[str, str]:
    import site_config
    return {v: r for v, r in site_config.TRANSITION_LABELS}


def _itens_eixo(p: Dict[str, Any], eixo: str) -> List[Tuple[str, int]]:
    return [(i["id"], int(i.get("peso") or 1)) for i in (p.get(eixo) or {}).get("itens", [])]


def _linha_eixo(p: Dict[str, Any], eixo: str, nome: str, rotulos: Dict[str, str], sistema: bool) -> str:
    cat = p.get(eixo) or {}
    pct = cat.get("pct", 0)
    itens = _itens_eixo(p, eixo)
    if not pct:
        return f"- {nome}: NÃO usar (0%)."
    if itens:
        lst = ", ".join(f"{rotulos.get(i, i) if i in rotulos else i} [{i}] peso {w}" for i, w in itens)
        return f"- {nome}: ~{pct}% — use SÓ estes (mais peso = mais vezes): {lst}"
    return f"- {nome}: ~{pct}% — {'qualquer um do catálogo abaixo' if sistema else 'nenhum marcado (não usar)'}"


# ⬛ v84_111: trecho SEM CENA (nenhum banco achou mídia) → a IA cobre com um fundo gerado + o que a fala pede, como
# se fosse escolha de edição. Quando a pessoa põe uma mídia ali e gera a edição de novo, ele volta a ser um trecho normal.
FUNDOS_COBERTURA: List[Tuple[str, str]] = [
    ("escuro", "escuro com grão (neutro, sério)"), ("concreto", "concreto (cru, investigação)"),
    ("papel", "papel de arquivo (documento, história)"), ("filme", "película (memória, arquivo antigo)"),
    ("clarao", "clarão de luz no centro (revelação)"), ("luz", "luz diagonal (dramático)"),
    ("grade_pontos", "grade de pontos (dados, técnico)"), ("registro", "marcas de registro (gráfico, impresso)"),
    ("cantoneiras", "cantoneiras (moldura de dossiê)"), ("borda_queimada", "borda queimada (passado, tensão)"),
    ("grade_ondulada", "grade ondulada (tecnologia, sinal)"), ("grade_3d", "grade 3D (futuro, digital)"),
    ("ondas", "ondas (som, fluxo)"), ("linhas", "linhas (moderno, limpo)"), ("cor_gradiente", "gradiente da cor (marca, leve)"),
]
IDS_COBERTURA = {f for f, _ in FUNDOS_COBERTURA}


def sem_cena(s: Dict[str, Any]) -> bool:
    """O trecho está sem cena de verdade: nenhuma mídia (`sem_midia`, mandado pelo Estúdio) ou coberto pela IA antes."""
    ov = s.get("override_source") or {}
    return bool(ov.get("cobertura")) or (bool(s.get("sem_midia")) and not ov.get("source"))


# 🖥 quadros que mostram a PROVA que a fala cita (liberados em qualquer direção)
TIPOS_PROVA = ("pagina", "post")
_RE_LINK = re.compile(r"\b((?:https?://)?(?:www\.)?[a-z0-9][a-z0-9\-]{1,62}(?:\.[a-z0-9\-]{2,63})*\.(?:com|net|org|br|gov|edu|io|co|tv|me|info|news|app|ai)(?:\.[a-z]{2})?(?:/[^\s\"'<>)]*)?)", re.I)


def _id_da_biblioteca(job: Dict[str, Any], ov: Dict[str, Any]) -> Optional[str]:
    """Id da biblioteca que o trecho usa (pelo id gravado ou pelo caminho do arquivo)."""
    lib = job.get("media_library") or []
    if ov.get("biblioteca") and any(b.get("id") == ov["biblioteca"] for b in lib):
        return str(ov["biblioteca"])
    v = ov.get("value")
    return next((b["id"] for b in lib if v and b.get("path") == v), None)


def descricao_midia(b: Dict[str, Any]) -> str:
    """O que a mídia da biblioteca é: a nota da pessoa > o rótulo de onde veio > o nome do arquivo."""
    d = str(b.get("descricao") or b.get("rotulo") or "").strip()
    nome = str(b.get("filename") or "").strip()
    return (d + (f" [{nome}]" if nome and nome not in d else "")) if d else nome


def links_do_projeto(job: Dict[str, Any]) -> List[Dict[str, str]]:
    """Links que o vídeo pode mostrar na tela: as fontes do modelo de vídeo (🕵️) ligado + o que a pessoa colou."""
    out: List[Dict[str, str]] = []
    if job.get("dossie_id"):
        try:
            import dossies
            import os as _os
            base = _os.path.dirname(_os.path.abspath(__file__))
            for f in (dossies.carregar(base, job["dossie_id"]).get("fontes") or []):
                if f.get("url"):
                    out.append({"url": f["url"], "titulo": str(f.get("titulo") or f.get("site") or "")[:120]})
        except Exception:  # noqa: BLE001
            pass
    for u in job.get("links_tela") or []:
        if isinstance(u, str) and u.strip():
            out.append({"url": u.strip(), "titulo": ""})
    vistos, uniq = set(), []
    for x in out:
        if x["url"] not in vistos:
            vistos.add(x["url"])
            uniq.append(x)
    return uniq[:40]


def _bloco_midias_e_links(job: Dict[str, Any], estado: Dict[str, Any], segs: List[Dict[str, Any]]) -> List[str]:
    L: List[str] = []
    lib = [b for b in (job.get("media_library") or []) if b.get("media_type") in ("image", "video")]
    if lib:
        usos: Dict[str, List[int]] = {}
        for i, s in enumerate(segs):
            bid = _id_da_biblioteca(job, s.get("override_source") or {})
            if bid:
                usos.setdefault(bid, []).append(i + 1)
        L.append("\n## 📁 Mídias que a pessoa ENVIOU (use no trecho com \"midia\": \"bib:<id>\"; as fotos também servem em "
                 "\"imagem\"/\"imagens\" dos quadros pagina, recortes, mural, bilhetes)")
        for b in lib[:60]:
            ja = usos.get(b["id"])
            L.append(f"- bib:{b['id']} — {'foto' if b['media_type'] == 'image' else 'vídeo'}: {descricao_midia(b)[:160]}"
                     + (f" · já está em T{', T'.join(map(str, ja))}" if ja else " · AINDA NÃO USADA"))
    links = links_do_projeto(job)
    falados = []
    for b in estado.get("blocos") or job.get("segments") or []:
        for m in _RE_LINK.findall(str(b.get("text") or "")):
            if m.lower() not in {x.lower() for x in falados}:
                falados.append(m)
    if links or falados:
        L.append("\n## 🖥 Sites que o vídeo pode mostrar na tela (quadro \"pagina\" com \"url\")")
        for x in links:
            L.append(f"- {x['url']}" + (f" — {x['titulo']}" if x["titulo"] else ""))
        if falados:
            L.append("- citados na fala: " + ", ".join(falados[:20]))
    return L


def montar_prompt(job: Dict[str, Any], estado: Dict[str, Any]) -> str:
    """estado (vem do Estúdio, pode estar sem salvar): segmentos, destaques,
    graficos, direcao, kit, ritmo, paleta, legenda, objetivo, opcoes."""
    segs = estado.get("segmentos") or job.get("pending_segments") or []
    destaques = estado.get("destaques") if estado.get("destaques") is not None else (job.get("destaques") or [])
    graficos = estado.get("graficos") if estado.get("graficos") is not None else (job.get("graficos") or [])
    did = str(estado.get("direcao") or (job.get("editor_defaults") or {}).get("direcao") or "sys_tudo")
    p = dp_direcao.direcao(did, estado.get("kit")) or dp_direcao.direcao("sys_tudo")
    sistema = bool(p.get("sistema") or p.get("universo") == "sistema")
    ritmo = estado.get("ritmo") or p.get("ritmo") or "equilibrado"
    op = estado.get("opcoes") or {}
    total = float(job.get("total_duration") or (segs[-1]["end"] if segs else 0))

    rot_tr = _transicoes_validas()
    rot_ef = {e["id"]: e["rotulo"] for e in dp_visual.efeitos()}
    rot_en = {e["id"]: e["rotulo"] for e in dp_visual.entradas()}
    rot_fi = {f["id"]: f["rotulo"] for f in dp_visual.filtros()}
    rot_tr_dp = {t["dp_id"]: t["rotulo"] for t in dp_visual.transicoes()}
    eixos = [("transicoes", "Transições (por emenda)", {**rot_tr, **rot_tr_dp}), ("efeitos", "Movimento/efeito (por trecho; câmera só em FOTO)", rot_ef),
             ("overlays", "Overlays de atmosfera (por trecho)", rot_ef), ("entradas", "Animação de entrada (por trecho)", rot_en),
             ("saidas", "Animação de saída (por trecho, só antes de corte seco)", rot_en), ("filtros", "Filtro de cor (UM pro vídeo todo)", rot_fi),
             ("templates", "Cenas/takes (templates; ocupam N trechos seguidos)", {})]
    L: List[str] = []
    L.append("Você é um editor de vídeo de documentário/YouTube. Abaixo está um vídeo JÁ MONTADO no meu editor (trechos, mídias, "
             "cenas, efeitos e textos) e a fala com os tempos. Quero que você APERFEIÇOE a edição seguindo a DIREÇÃO escolhida: "
             "transições e efeitos com intenção (nada aleatório), cenas/takes onde a fala pede, destaques de texto nos momentos "
             "certos e GRÁFICOS ANIMADOS sempre que a narração citar dados (números, porcentagens, valores, comparações, evolução no tempo).")
    if estado.get("objetivo"):
        L.append("\n## O que eu quero nesta edição (pedido da pessoa — prioridade)\n" + str(estado["objetivo"]).strip()[:2000])

    L.append(f"\n## Direção escolhida: {p.get('nome')} [{did}] · ritmo {ritmo}")
    if p.get("descricao"):
        L.append(p["descricao"])
    L.append("Respeite as porcentagens e os pesos (a % é de trechos/emendas que recebem o eixo; o resto fica sem):")
    for eixo, nome, rot in eixos:
        L.append(_linha_eixo(p, eixo, nome, rot, sistema))
    dsq = p.get("destaques") or {}
    kit_hl = [e for e in (dsq.get("estilos") or []) if dp_destaques.estilo(e)]
    L.append(f"- Destaques de texto: densidade {dsq.get('densidade', 'equilibrado')}" + (f" — use SÓ estes estilos: {', '.join(kit_hl)}" if kit_hl else " — estilos do catálogo abaixo"))
    ped = dp_direcao.editoriais_da(p)
    if ped["ativo"]:
        L.append(f"- Quadros editoriais: ~1 a cada {ped['segundos']} s" + (f" — use SÓ estes tipos: {', '.join(ped['tipos'])}" if ped["tipos"] else " — qualquer tipo do catálogo abaixo"))
    else:
        L.append("- Quadros editoriais: NÃO usar nesta direção (exceto os de PROVA abaixo).")
    # 🖥 v84_67: mostrar o site/post que a fala cita é CONTEÚDO, não estilo — vale em qualquer direção
    tipos_prova = [t for t in TIPOS_PROVA if not (ped["ativo"] and (not ped["tipos"] or t in ped["tipos"]))]
    if tipos_prova:
        L.append(f"- Quadros de PROVA ({', '.join(tipos_prova)}): liberados em qualquer direção, sempre que a fala citar um site, "
                 "uma página, uma notícia ou um post — não contam na frequência acima.")
    cs = p.get("cores") or {}
    if cs.get("modo") == "predef":
        L.append(f"- Cores: use a paleta da direção (primária {cs.get('primaria')}).")
    elif cs.get("modo") == "auto":
        L.append("- Cores: cada estilo com a sua cor original (não mande paleta).")
    else:
        pal = estado.get("paleta") or {}
        if pal.get("primaria"):
            L.append(f"- Cores: paleta do projeto primária {pal.get('primaria')}, secundária {pal.get('secundaria')}, acento {pal.get('acento')} (pode sugerir outra coerente).")
    if p.get("legenda"):
        L.append(f"- Legenda: estilo {p['legenda'].get('estilo')}.")

    # ---------------- catálogos
    L.append("\n## Catálogos (use SÓ ids destas listas; id fora da lista é descartado)")
    tr_ok = [i for i, _w in _itens_eixo(p, "transicoes")]
    if tr_ok:
        L.append("Transições: " + ", ".join(dp_visual.valor_transicao(i) for i in tr_ok) + ", none (corte seco)")
    elif (p.get("transicoes") or {}).get("pct", 0):
        L.append("Transições: " + "; ".join(f"{v} = {r}" for v, r in rot_tr.items()))
    ef = _itens_eixo(p, "efeitos") + _itens_eixo(p, "overlays")
    if ef:
        L.append("Efeitos: " + ", ".join(i for i, _w in ef))
    else:
        L.append("Efeitos (câmera, só foto): " + ", ".join(e for e in dp_visual.EFEITO_PARA_ZOOM))
        L.append("Efeitos (atmosfera/overlay): " + ", ".join(e["id"] for e in dp_visual.efeitos() if e["id"] != "none" and not dp_visual.efeito_e_movimento(e["id"])))
    en = _itens_eixo(p, "entradas") + _itens_eixo(p, "saidas")
    L.append("Entradas/saídas: " + ", ".join(sorted({i for i, _w in en})) if en else "Entradas/saídas: " + ", ".join(e["id"] for e in dp_visual.entradas() if e["id"] != "none"))
    fi = _itens_eixo(p, "filtros")
    L.append("Filtros: " + ", ".join(i for i, _w in fi) if fi else "Filtros: " + ", ".join(rot_fi))
    tpl_itens = [i for i, _w in _itens_eixo(p, "templates")]
    if tpl_itens or ((p.get("templates") or {}).get("pct", 0) and sistema):
        bloco = cenas_dp.bloco_para_prompt(400).splitlines()
        if tpl_itens:
            bloco = [b for b in bloco if b.split(" | ")[0][2:] in tpl_itens]
        L.append("Cenas/takes (id | nome | trechos | duração | campos | quando):\n" + "\n".join(bloco[:120]))
    hl = dp_destaques.bloco_para_prompt().splitlines()
    if kit_hl:
        hl = [b for b in hl if b.split(" | ")[0][2:] in kit_hl]
    L.append("Destaques de texto (id | papel(subtipo) | palavras | quando):\n" + "\n".join(hl))
    L.append("Fundos de destaque (opcional, campo \"fundo\"): " + ", ".join(f[0] for f in dp_fundos.FUNDOS_DESTAQUE))
    L.append("Animação de entrada do texto (campo \"anim_entrada\", opcional — sobrepõe a do estilo): " + ", ".join(dp_destaques.ANIMS_ENTRADA)
             + ". Saída (\"anim_saida\"): " + ", ".join(dp_destaques.ANIMS_SAIDA) + ". Movimento interno (\"interna\"): brilho, flutua, nenhuma.")
    L.append("Fontes (campo \"fonte\", opcional): " + ", ".join(k for k in dp_destaques._FONTE if k != "default")
             + ". Posições do texto (\"zona\"): centro, alto, baixo, terco_inf, terco_sup, esq, dir, canto_tl, canto_tr, canto_bl, canto_br.")
    L.append("Composição do trecho: \"bordas\" = black | zoom | mosaic | smart (smart tira barra preta embutida); em FOTO \"camera\" = "
             + ", ".join(sorted(__import__("video_assembler")._ZOOM_DIRECTIONS_VALIDAS)) + " e \"foco\" = {\"x\": 0-1, \"y\": 0-1} (o ponto de interesse da imagem).")
    import dp_legendas
    L.append("Legenda (opcional): estilos " + ", ".join(e["id"] for e in dp_legendas.ESTILOS) + "; posicao base|meio|topo; tamanho 0.04–0.09; maiusculas; cor_ativa #hex.")
    L.append("Gráficos — cores (todas opcionais): \"cor\" principal, \"cor_secundaria\" (itens fora de destaque), \"esquema\" = "
             + " | ".join(dp_graficos.ESQUEMAS) + ", \"cartao\" = " + " | ".join(dp_graficos.CARTOES)
             + ", \"fundo_cor\", \"fundo_opacidade\" 0–1, \"texto_cor\" e \"cor\" em cada item de \"dados\".")
    import dp_sons
    L.append("Sons (opcional, campo \"sons\"; transições, destaques e quadros editoriais já ganham som automático): "
             + "; ".join(f"{c['nome']}: " + ", ".join(x["id"] for x in c["sons"]) for c in dp_sons.categorias()))
    L.append("Gráficos (campo \"tipo\"): " + "; ".join(f"{k} = {v}" for k, v in dp_graficos.TIPOS.items())
             + ". Posições: " + ", ".join(dp_graficos.POSICOES))
    import dp_editorial
    if ped["ativo"] or tipos_prova:
        tipos_cat = (None if ped["ativo"] and not ped["tipos"] else
                     list(dict.fromkeys((ped["tipos"] if ped["ativo"] else []) + tipos_prova)))
        L.append("Quadros editoriais (campo \"editoriais\", opcional — o estilo documentário: papel bege, serifada, acento vermelho; "
                 "\"start\"/\"end\" em segundos, 3–8 s, cobrindo a fala daquilo; os de tela cheia cobrem a cena; "
                 "cada um já vem com o som dele — \"som\": \"nenhum\" tira):\n" + dp_editorial.bloco_para_prompt(tipos_cat))
    L.extend(_bloco_midias_e_links(job, estado, segs))

    # ---------------- estado atual
    parte = estado.get("parte") if isinstance(estado.get("parte"), dict) else None
    p_ini, p_fim = (float(parte["ini"]), float(parte["fim"])) if parte else (0.0, float("inf"))

    def na_parte(a, b=None) -> bool:
        a = float(a or 0)
        b = float(b if b is not None else a)
        return b > p_ini and a < p_fim
    if parte:
        L.append(f"\n## ⚠ PARTE {parte['k']} de {parte['n']} — só de {_t(p_ini)} até {_t(min(p_fim, total))}")
        L.append("O vídeo é longo e está dividido em partes (cada uma num prompt). Edite SÓ esta parte: trechos, destaques, "
                 "gráficos, quadros e sons com tempo DENTRO dela. Os números dos trechos (T…) são os do vídeo inteiro — use-os "
                 "como estão." + (" Filtro, paleta e legenda valem pro vídeo todo: mande só nesta parte 1." if parte["k"] == 1
                                  else " NÃO mande filtro_cor, paleta nem legenda (já foram decididos na parte 1)."))
        if parte["k"] == 1:
            L.append("Como esta é a PARTE 1, você DECIDE a direção de arte do vídeo inteiro (as outras partes vão seguir igual): "
                     "mande também \"direcao_arte\" com o resumo do visual — estilos de destaque e fontes, cores, animações, "
                     "zonas, transições e efeitos preferidos, estilo dos gráficos e dos quadros, e as regras que você seguiu.")
        elif estado.get("arte"):
            L.append(str(estado["arte"]))
        else:
            L.append("⚠ A direção de arte da parte 1 ainda não veio: mantenha o visual coerente e discreto.")
    L.append(f"\n## Timeline atual ({len(segs)} trechos, {_t(total)})" + (" — trechos desta parte:" if parte else ""))
    for i, s in enumerate(segs):
        if parte and not na_parte(s["start"], s["end"]):
            continue
        ov = s.get("override_source") or {}
        midia = ("foto" if (ov.get("kind") or s.get("media_type")) == "image" else "vídeo") + f" '{s.get('query', '')}'"
        if ov.get("cobertura"):
            midia = (f"⬛ SEM CENA — coberto na edição anterior (fundo {ov.get('fundo') or '?'}); nenhuma mídia achada pra "
                     f"'{s.get('query', '')}' — refaça a cobertura (regra 13)")
        elif sem_cena(s):
            midia = f"⬛ SEM CENA — nenhuma mídia achada pra '{s.get('query', '')}' — COBRIR (regra 13)"
        elif ov.get("cartao"):
            midia = f"🃏 cartão de texto (nenhuma imagem boa pra '{s.get('query', '')}') — não ponha destaque nem quadro em cima; troque por uma mídia enviada se alguma combinar"
        elif ov.get("source") == "local_file":
            bid = _id_da_biblioteca(job, ov)
            midia += f" (= bib:{bid}, já colocada)" if bid else " (arquivo escolhido pela pessoa — não troque)"
        if (s.get("youtube_link") or {}).get("url"):
            midia += " (YouTube escolhido)"
        extra = [f"{k}={s.get(k)}" for k in ("transition", "efeito", "entrada", "saida", "template") if s.get(k)]
        fala = (s.get("_fala") or "").strip()
        L.append(f"T{i + 1} [{_t(s['start'])}→{_t(s['end'])}] {midia}" + (" · " + ", ".join(extra) if extra else "") + (f" · fala: \"{fala[:160]}\"" if fala else ""))
    if parte:
        destaques = [d for d in destaques if na_parte(d.get("start"), d.get("end"))]
        graficos = [g for g in graficos if na_parte(g.get("start"), g.get("end"))]
    if destaques and op.get("destaques_atuais", True):
        L.append("\nDestaques atuais: " + "; ".join(f"{d.get('estilo')} {_t(d['start'])} \"{(d.get('texto') or '')[:40]}\"" for d in destaques[:60]))
    eds = estado.get("editoriais") if estado.get("editoriais") is not None else (job.get("editoriais") or [])
    if parte:
        eds = [q for q in eds if na_parte(q.get("start"), q.get("end"))]
    if eds:
        L.append("Quadros editoriais atuais: " + "; ".join(f"{q.get('tipo')} {_t(float(q.get('start') or 0))}" for q in eds[:40]))
    if graficos:
        L.append("Gráficos atuais: " + "; ".join(f"{g.get('tipo')} {_t(g['start'])} \"{g.get('titulo', '')}\"" for g in graficos))

    blocos = [b for b in (estado.get("blocos") or job.get("segments") or []) if (b.get("text") or "").strip()
              and (not parte or na_parte(b.get("start"), b.get("end")))]
    if blocos:
        L.append("\n## Fala com os tempos (transcrição/SRT)")
        for b in blocos:
            L.append(f"[{_t(b['start'])}→{_t(b['end'])}] {b['text'].strip()}")

    # ---------------- regras + formato
    L.append("""
## Regras
1. Respeite a direção: os eixos com 0% ficam de fora; use só os ids permitidos; as % são aproximadas e os pesos dizem o que aparece mais.
2. Transição na emenda ENTRE o trecho N e o N+1 vai no trecho N. Dentro de uma cena (template) as emendas ficam "none".
3. Efeitos de câmera só em FOTO. Uma cena (template) ocupa os trechos seguidos que ela pede, começando no trecho indicado.
4. Destaques: no máximo um por vez, cada um ancorado na fala — "texto" usa as palavras ditas (ou um resumo curto) e "palavra" é a PRIMEIRA palavra falada daquele momento (eu calculo o tempo exato). Não exagere: siga a densidade.
5. Gráficos: SÓ com dados que a narração realmente cita (não invente números). 2 a 8 valores, rótulos curtos, "unidade" ("%", "R$", "US$ bi", "mi", "km"…), "start"/"end" em segundos cobrindo a fala dos dados (3–8 s). Evite gráfico e destaque ao mesmo tempo no mesmo ponto.
6. Mande SÓ o que muda: trechos sem alteração podem ficar de fora. Use "null" pra tirar um efeito/cena existente.
7. REFINO FINO — você decide a composição e a tipografia: em cada destaque escolha "zona" (onde fica na tela, sem cobrir o rosto/assunto da imagem), "enfase" (1–3 palavras do texto que ganham a cor de acento — o número, o nome, a palavra-chave), e se quiser "fonte", "maiusculas", "escala" (0.6–1.6), "anim_entrada"/"anim_saida"/"interna", "cor" (acento só dele), "fundo"/"fundo_cor"/"fundo_int" e "som" (id, ou "nenhum"). Textos livres que não seguem a fala: "avulso": true com "start"/"end".
8. Sons: as transições e destaques já ganham som automático; use "sons" pra acentos extras (impacto numa revelação, whoosh numa virada, riser antes de um clímax), com "volume" 0.2–1.2, sem poluir.
9. Quadros editoriais: use com moderação (a frequência da direção acima), SÓ com fatos que a narração cita (nomes, datas, números, posts, manchetes reais); "ficha"/"nome" quando a pessoa aparece; "post" pra citação de rede social (com "traducao" se for em outro idioma); "numero" pra um número-chave; "recortes"/"linha_tempo" pra sequência de fatos. Não ponha quadro e destaque ao mesmo tempo.
10. Composição dos trechos: "bordas" (smart pra vídeo com barra preta/baixa qualidade), "camera"/"foco" em fotos, "transition_som" (id ou "nenhum") pra trocar o som de uma transição.
11. MÍDIAS ENVIADAS (lista "📁" acima): a pessoa mandou esses arquivos pra entrarem no vídeo — elas valem MAIS que o banco de imagens. Ponha cada uma no trecho em que a fala combina com ela usando "midia": "bib:<id>" no trecho (vídeo de site/página no trecho que fala do site; foto de pessoa quando falam dela). Use TODAS pelo menos uma vez (só deixe de fora a que não combina com nada e diga em "observacoes"); a mesma mídia pode voltar mais tarde. Não troque um trecho marcado "arquivo escolhido pela pessoa".
12. SITE NA TELA: sempre que a fala citar um site, uma página, uma notícia ou um post, MOSTRE: se tem um vídeo/print dele nas mídias enviadas, use (rule 11); senão um quadro "pagina" com "url" (o endereço completo — dos links abaixo ou o que a fala diz; o print é tirado sozinho) e "site" (o domínio na barra), ou "post" pra post de rede social. Não invente endereço: sem o link, use "site" + "titulo" (a manchete).
{regra_cobrir}
## Responda SÓ com este JSON (sem texto antes/depois)
{
  "filtro_cor": "id ou null",
  "paleta": {"primaria": "#RRGGBB", "secundaria": "#RRGGBB", "acento": "#RRGGBB"},
  "legenda": {"estilo": "id", "posicao": "base", "tamanho": 0.06, "maiusculas": false, "cor_ativa": "#RRGGBB"},
  "trechos": [
    {"trecho": 2, "midia": "bib:<id> (mídia enviada pela pessoa — opcional)"},{exemplo_cobrir}
    {"trecho": 3, "transition": "id ou none", "transition_duration": 0.6, "transition_som": "id opcional", "efeito": "id ou null", "entrada": "id ou null", "saida": "id ou null",
     "template": "id ou null", "template_campos": {"campo": "texto", "_fundo": "id opcional", "_fundo_cor": "#RRGGBB"},
     "bordas": "smart", "camera": "in", "foco": {"x": 0.5, "y": 0.35}}
  ],
  "destaques": [
    {"estilo": "id", "texto": "texto curto", "palavra": "primeira palavra falada", "start": 12.3, "campos": {},
     "zona": "terco_inf", "enfase": ["1945"], "fonte": "anton", "maiusculas": true, "escala": 1.1, "anim_entrada": "punch", "anim_saida": "riscar",
     "interna": "brilho", "cor": "#RRGGBB", "fundo": "id", "fundo_cor": "#RRGGBB", "fundo_int": 0.8, "som": "id ou nenhum"},
    {"estilo": "id", "avulso": true, "texto": "texto livre", "start": 30.0, "end": 33.5, "zona": "canto_tr"}
  ],
  "substituir_destaques": true,
  "graficos": [
    {"tipo": "barras", "titulo": "População do Brasil", "dados": [{"rotulo": "1950", "valor": 52}, {"rotulo": "2022", "valor": 203}],
     "unidade": "mi", "fonte": "IBGE", "start": 40.2, "end": 46.0, "posicao": "centro", "destaque": 1,
     "cor": "#RRGGBB", "esquema": "unica", "cartao": "escuro", "fundo_opacidade": 0.85}
  ],
  "sons": [{"som": "id", "start": 10.5, "volume": 0.8}],
  "editoriais": [
    {"tipo": "ficha", "start": 4.2, "end": 9.0, "rotulo": "AUSTRÁLIA", "nome": "Nome Sobrenome", "linhas": "Cargo: …\nNo cargo desde: …", "ponto_x": 0.5, "ponto_y": 0.25, "credito": "fonte"},
    {"tipo": "numero", "start": 20.0, "end": 25.0, "de": 0, "ate": 98, "sufixo": "%", "rotulo": "o que é", "subtexto": "segundo quem"},
    {"tipo": "pagina", "start": 31.0, "end": 36.0, "url": "https://site.com/a-pagina-citada", "site": "site.com", "titulo": "manchete", "credito": "site.com"}
  ],
  "observacoes": "2-3 frases dizendo o que você mudou e por quê"
}""" + ("""
(Só na PARTE 1, acrescente: "direcao_arte": {"resumo": "1-2 frases", "destaques": "estilos/fontes/animações/zonas que você usou e quando",
 "cores": "como usou a paleta", "transicoes": "quais e quando", "efeitos": "quais", "graficos": "esquema/cartão/cores",
 "quadros": "quadros editoriais: cor/fundo/quando", "regras": ["regra que as outras partes devem seguir"]})""" if (parte and parte["k"] == 1) else ""))
    vazios = [i + 1 for i, s in enumerate(segs) if sem_cena(s) and (not parte or na_parte(s["start"], s["end"]))]
    regra = ""
    if vazios:
        regra = ("13. TRECHOS SEM CENA (⬛: " + ", ".join(f"T{n}" for n in vazios[:80]) + "): nenhum banco achou mídia pra eles. "
                 "COBRE cada um como se fosse uma ESCOLHA de edição (nunca pode parecer buraco ou erro): no trecho mande "
                 "\"cobrir\": {\"fundo\": \"id\", \"cor\": \"#RRGGBB\"} (um fundo gerado que combina com o assunto — lista abaixo) "
                 "e, POR CIMA, o que a fala daquele momento pede: uma cena/template com os textos (se a direção permite), um "
                 "quadro editorial de tela cheia (numero, recortes, linha_tempo, ficha…), um gráfico se a fala cita dados, ou "
                 "um destaque avulso de tela cheia com a frase-chave (\"avulso\": true, start/end do trecho). Pode pôr "
                 "\"efeito\" de atmosfera e \"camera\" (o fundo é uma FOTO). Trechos sem cena seguidos: varie o fundo e o "
                 "que vai por cima. Se a pessoa já pôs uma mídia num trecho que antes era ⬛, ele aparece normal na lista — "
                 "edite como qualquer clipe.\n    Fundos (\"cobrir.fundo\"): "
                 + "; ".join(f"{f} = {d}" for f, d in FUNDOS_COBERTURA))
    L[-1] = L[-1].replace("{regra_cobrir}", regra).replace(
        "{exemplo_cobrir}", f'\n    {{"trecho": {vazios[0]}, "cobrir": {{"fundo": "papel", "cor": "#RRGGBB"}}, "camera": "in", "efeito": "id ou null"}},' if vazios else "")
    try:  # o vídeo fala um idioma só: textos de destaques/gráficos/cenas no idioma da narração
        import idiomas
        L.append("")
        L.append(idiomas.regra_para_prompt(idiomas.normalizar(job.get("language")) or "pt"))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(L)


# ------------------------------------------------------------------ prompt em partes (vídeo longo)
def dividir_partes(segs: List[Dict[str, Any]], total: float, minutos: float = 12.0) -> List[Dict[str, Any]]:
    """Partes de ~`minutos` cortadas no começo de um trecho (nunca no meio de uma cena/template).
    Uma IA editando 1 hora de uma vez perde qualidade; 5 prompts de 12 min ficam bem melhores."""
    alvo = max(2.0, float(minutos or 12)) * 60
    if not segs or total <= alvo * 1.25:
        return [{"k": 1, "n": 1, "ini": 0.0, "fim": float(total or (segs[-1]["end"] if segs else 0))}]
    cortes = [0.0]
    for i, s in enumerate(segs):
        if i and float(s["start"]) - cortes[-1] >= alvo and not segs[i - 1].get("template") and (total - float(s["start"])) >= alvo * 0.35:
            cortes.append(float(s["start"]))
    cortes.append(float(total))
    partes = [{"ini": a, "fim": b} for a, b in zip(cortes, cortes[1:]) if b > a]
    n = len(partes)
    return [dict(x, k=k, n=n) for k, x in enumerate(partes, start=1)]


def _contagem(itens, chave) -> List[str]:
    from collections import Counter
    c = Counter(str(x.get(chave)) for x in itens or [] if x.get(chave) not in (None, "", "none", "null"))
    return [f"{k} ({n}x)" if n > 1 else k for k, n in c.most_common(8)]


def arte_da_parte1(plano: Dict[str, Any]) -> str:
    """✂️ O que a parte 1 decidiu (filtro, paleta, legenda, estilos de destaque, fontes, animações, transições,
    efeitos, gráficos, quadros + o "direcao_arte" que ela mandou) → bloco que vai nos prompts das partes 2..N,
    pra o vídeo inteiro ter UMA cara só."""
    L = ["## 🎨 DIREÇÃO DE ARTE JÁ DECIDIDA NA PARTE 1 — siga IGUAL (o vídeo é um só)",
         "Use os MESMOS estilos, fontes, cores, animações, zonas, transições e efeitos abaixo, com a mesma frequência. "
         "Só use algo diferente se a fala pedir muito, e mesmo assim da mesma família."]
    if plano.get("filtro_cor"):
        L.append(f"- Filtro do vídeo: {plano['filtro_cor']} (já aplicado — não mande filtro_cor).")
    pal = plano.get("paleta") or {}
    if pal.get("primaria"):
        L.append(f"- Paleta: primária {pal.get('primaria')}, secundária {pal.get('secundaria')}, acento {pal.get('acento')} — "
                 "use SÓ essas cores em \"cor\"/\"fundo_cor\" de destaques, gráficos e quadros.")
    leg = plano.get("legenda") or {}
    if leg.get("estilo"):
        L.append(f"- Legenda: {leg.get('estilo')} (já decidida — não mande legenda).")
    ds = plano.get("destaques") or []
    if ds:
        L.append("- Destaques: estilos " + ", ".join(_contagem(ds, "estilo"))
                 + (" · fontes " + ", ".join(_contagem(ds, "fonte")) if _contagem(ds, "fonte") else "")
                 + (" · entrada " + ", ".join(_contagem(ds, "anim_entrada")) if _contagem(ds, "anim_entrada") else "")
                 + (" · saída " + ", ".join(_contagem(ds, "anim_saida")) if _contagem(ds, "anim_saida") else "")
                 + (" · zonas " + ", ".join(_contagem(ds, "zona")) if _contagem(ds, "zona") else "")
                 + (" · fundos " + ", ".join(_contagem(ds, "fundo")) if _contagem(ds, "fundo") else "")
                 + (" · cores " + ", ".join(_contagem(ds, "cor")) if _contagem(ds, "cor") else "")
                 + f" — {len(ds)} destaques na parte 1 (mantenha a densidade).")
        mai = [x.get("maiusculas") for x in ds if isinstance(x.get("maiusculas"), bool)]
        if mai:
            L.append(f"  Maiúsculas: {'sim' if sum(mai) >= len(mai) / 2 else 'não'}.")
    tr = plano.get("trechos") or []
    if _contagem(tr, "transition"):
        L.append("- Transições: " + ", ".join(_contagem(tr, "transition")))
    if _contagem(tr, "efeito"):
        L.append("- Efeitos/movimento: " + ", ".join(_contagem(tr, "efeito")))
    if _contagem(tr, "entrada") or _contagem(tr, "saida"):
        L.append("- Animações dos trechos: " + ", ".join(_contagem(tr, "entrada") + _contagem(tr, "saida")))
    if _contagem(tr, "template"):
        L.append("- Cenas/takes: " + ", ".join(_contagem(tr, "template")))
    gs = plano.get("graficos") or []
    if gs:
        L.append("- Gráficos: " + ", ".join(_contagem(gs, "tipo")) + (" · esquema " + ", ".join(_contagem(gs, "esquema")) if _contagem(gs, "esquema") else "")
                 + (" · cartão " + ", ".join(_contagem(gs, "cartao")) if _contagem(gs, "cartao") else "")
                 + (" · cores " + ", ".join(_contagem(gs, "cor")) if _contagem(gs, "cor") else ""))
    eds = plano.get("editoriais") or []
    if eds:
        L.append("- Quadros editoriais: " + ", ".join(_contagem(eds, "tipo")) + (" · cor " + ", ".join(_contagem(eds, "cor")) if _contagem(eds, "cor") else "")
                 + (" · fundo " + ", ".join(_contagem(eds, "fundo")) if _contagem(eds, "fundo") else ""))
    sons = plano.get("sons") or []
    if sons:
        L.append("- Sons extras: " + ", ".join(_contagem(sons, "som")))
    da = plano.get("direcao_arte") or {}
    if da:
        L.append("- O que a parte 1 disse da direção de arte:")
        for k, v in da.items():
            if isinstance(v, list):
                L += [f"  • {x}" for x in v]
            elif v:
                L.append(f"  • {k}: {v}")
    if len(L) == 2:
        return ""
    return "\n".join(L)


def juntar_planos(planos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """As respostas de cada parte → um plano só (os trechos não se repetem; o resto soma)."""
    out: Dict[str, Any] = {"trechos": [], "destaques": None, "graficos": None, "editoriais": None, "avisos": [], "observacoes": ""}
    trechos: Dict[int, Dict[str, Any]] = {}
    obs = []
    for k, p in enumerate(planos, start=1):
        for t in p.get("trechos") or []:
            trechos[t["indice"]] = dict(trechos.get(t["indice"], {}), **t)
        for chave in ("destaques", "graficos", "editoriais", "sons"):
            if p.get(chave):
                out[chave] = (out.get(chave) or []) + list(p[chave])
        for chave in ("filtro_cor", "paleta", "legenda"):
            if p.get(chave) and not out.get(chave):
                out[chave] = p[chave]
        if p.get("substituir_destaques"):
            out["substituir_destaques"] = True
        if k == 1 and p.get("direcao_arte"):
            out["direcao_arte"] = p["direcao_arte"]
        out["avisos"] += [f"Parte {k}: {a}" for a in p.get("avisos") or []]
        if p.get("observacoes"):
            obs.append(f"Parte {k}: {p['observacoes']}")
    out["trechos"] = [trechos[i] for i in sorted(trechos)]
    for chave in ("destaques", "graficos", "editoriais", "sons"):
        if out.get(chave):
            out[chave].sort(key=lambda x: float(x.get("start") or 0))
    out["observacoes"] = " ".join(obs)[:2400]
    return out


# ------------------------------------------------------------------ leitura da resposta
ZONAS = ("centro", "alto", "baixo", "terco_inf", "terco_sup", "esq", "dir", "canto_tl", "canto_tr", "canto_bl", "canto_br")


def estilo_de_texto(x: Dict[str, Any], avisos: Optional[List[str]] = None) -> Dict[str, Any]:
    """Campos de composição/tipografia de um destaque (IA ou editor), validados."""
    import dp_sons
    out: Dict[str, Any] = {}
    if x.get("avulso"):
        out["avulso"] = True
    if x.get("zona") in ZONAS:
        out["zona"] = x["zona"]
    enf = x.get("enfase")
    if isinstance(enf, str):
        enf = [e for e in re.split(r"[,;|]", enf) if e.strip()]
    if isinstance(enf, list):
        enf = [str(e).strip()[:40] for e in enf if str(e).strip()][:6]
        if enf:
            out["enfase"] = enf
    if x.get("fonte") in dp_destaques._FONTE and x.get("fonte") != "default":
        out["fonte"] = x["fonte"]
    for k in ("maiusculas", "italico"):
        if isinstance(x.get(k), bool):
            out[k] = x[k]
    try:
        if x.get("escala") not in (None, ""):
            out["escala"] = round(max(0.6, min(1.6, float(x["escala"]))), 2)
        if x.get("fundo_int") not in (None, ""):
            out["fundo_int"] = round(max(0.15, min(1.0, float(x["fundo_int"]))), 2)
    except (TypeError, ValueError):
        pass
    if x.get("anim_entrada") in dp_destaques.ANIMS_ENTRADA:
        out["anim_entrada"] = x["anim_entrada"]
    elif x.get("anim_entrada") and avisos is not None:
        avisos.append(f"Animação de entrada '{x['anim_entrada']}' desconhecida.")
    if x.get("anim_saida") in dp_destaques.ANIMS_SAIDA:
        out["anim_saida"] = x["anim_saida"]
    if x.get("interna") in ("brilho", "flutua", "nenhuma"):
        out["interna"] = x["interna"]
    for k in ("cor", "fundo_cor"):
        if re.fullmatch(r"#[0-9a-fA-F]{6}", str(x.get(k) or "")):
            out[k] = str(x[k]).upper()
    som = x.get("som")
    if som == "nenhum" or (som and dp_sons.som(str(som))):
        out["som"] = str(som)
    if x.get("legenda") in ("manter", "ocultar"):
        out["legenda"] = x["legenda"]
    return out
def extrair_json(texto: str) -> Dict[str, Any]:
    import json_ia
    d = json_ia.carregar(texto)  # conserta o que o copiar/colar estraga; ValueError com mensagem amigável
    if isinstance(d, list) and len(d) == 1 and isinstance(d[0], dict):
        d = d[0]
    if not isinstance(d, dict):
        raise ValueError("O JSON precisa ser um objeto { ... }.")
    return d


def _nulo(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none", "nenhum", "nenhuma"))


def ler_resposta(texto: str, n_trechos: int, duracao: float, palavras: List[Dict[str, Any]],
                 foto: Optional[List[bool]] = None, biblioteca: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Valida a resposta da IA → {trechos, destaques, substituir_destaques, graficos,
    filtro_cor, paleta, legenda, sons, observacoes, avisos}."""
    import dp_cores
    import dp_legendas
    import dp_sons
    d = extrair_json(texto)
    avisos: List[str] = []
    rot_tr = _transicoes_validas()
    ef_ok = {e["id"] for e in dp_visual.efeitos()}
    en_ok = {e["id"] for e in dp_visual.entradas()}
    fi_ok = {f["id"] for f in dp_visual.filtros()}
    out: Dict[str, Any] = {"trechos": [], "destaques": None, "graficos": None, "editoriais": None, "avisos": avisos,
                           "observacoes": str(d.get("observacoes") or "")[:1200]}
    da = d.get("direcao_arte")
    if isinstance(da, dict):  # ✂️ parte 1: a direção de arte que as outras partes seguem
        out["direcao_arte"] = {str(k)[:30]: ([str(x)[:300] for x in v][:12] if isinstance(v, list) else str(v)[:600])
                               for k, v in list(da.items())[:12]}
    elif isinstance(da, str) and da.strip():
        out["direcao_arte"] = {"resumo": da.strip()[:1200]}

    def tr_valida(v):
        if _nulo(v):
            return "none"
        v = str(v)
        if v in rot_tr:
            return v
        if dp_visual.valor_transicao(v) in rot_tr:
            return dp_visual.valor_transicao(v)
        return None

    for it in d.get("trechos") or []:
        if not isinstance(it, dict):
            continue
        try:
            n = int(it.get("trecho", it.get("indice", it.get("index"))))
        except (TypeError, ValueError):
            avisos.append("Trecho sem número ignorado.")
            continue
        i = n - 1
        if not 0 <= i < n_trechos:
            avisos.append(f"Trecho {n} não existe (o projeto tem {n_trechos}).")
            continue
        r: Dict[str, Any] = {"indice": i}
        cob = it.get("cobrir")
        if isinstance(cob, str):
            cob = {"fundo": cob}
        if isinstance(cob, dict) and cob.get("fundo") not in (None, "", "null"):
            fundo = str(cob.get("fundo")).strip()
            if fundo not in IDS_COBERTURA:
                avisos.append(f"T{n}: fundo de cobertura '{fundo}' desconhecido — usei 'escuro'.")
                fundo = "escuro"
            r["cobrir"] = {"fundo": fundo}
            if re.fullmatch(r"#[0-9a-fA-F]{6}", str(cob.get("cor") or "")):
                r["cobrir"]["cor"] = str(cob["cor"]).upper()
            if foto is not None and i < len(foto):  # coberto = vira FOTO (o fundo): câmera e efeitos de foto valem
                foto = list(foto)
                foto[i] = True
        if it.get("midia") not in (None, "", "null"):  # 📁 mídia que a pessoa enviou → o trecho passa a usar ela
            bid = re.sub(r"^bib:", "", str(it["midia"]).strip(), flags=re.I)
            if biblioteca is not None and bid in biblioteca:
                r["midia"] = bid
                if foto is not None and i < len(foto):
                    foto = list(foto)
                    foto[i] = biblioteca[bid] == "image"
            else:
                avisos.append(f"T{n}: mídia '{it['midia']}' não está na biblioteca — ignorada.")
        if "transition" in it:
            v = tr_valida(it["transition"])
            if v is None:
                avisos.append(f"T{n}: transição '{it['transition']}' desconhecida.")
            else:
                r["transition"] = v
                try:
                    if it.get("transition_duration") is not None:
                        r["transition_duration"] = round(max(0.1, min(3.0, float(it["transition_duration"]))), 2)
                except (TypeError, ValueError):
                    pass
        for campo, ok in (("efeito", ef_ok), ("entrada", en_ok), ("saida", en_ok)):
            if campo in it:
                v = it[campo]
                if _nulo(v):
                    r[campo] = None
                elif str(v) in ok:
                    if campo == "efeito" and dp_visual.efeito_e_movimento(str(v)) and foto is not None and i < len(foto) and not foto[i]:
                        avisos.append(f"T{n}: '{v}' é movimento de câmera e o trecho é vídeo — ignorado.")
                        continue
                    r[campo] = str(v)
                else:
                    avisos.append(f"T{n}: {campo} '{v}' desconhecido.")
        if it.get("bordas") in ("black", "zoom", "mosaic", "smart", "cartao"):
            r["bordas"] = it["bordas"]
        cam = it.get("camera") or it.get("zoom_direction")
        if cam:
            import video_assembler as _va
            if str(cam) in _va._ZOOM_DIRECTIONS_VALIDAS and (foto is None or i >= len(foto) or foto[i]):
                r["camera"] = str(cam)
            else:
                avisos.append(f"T{n}: câmera '{cam}' inválida ou o trecho é vídeo.")
        if isinstance(it.get("foco"), dict):
            try:
                r["foco"] = {"x": round(max(0.0, min(1.0, float(it["foco"].get("x", 0.5)))), 3), "y": round(max(0.0, min(1.0, float(it["foco"].get("y", 0.5)))), 3)}
            except (TypeError, ValueError):
                pass
        if "transition_som" in it:
            import dp_sons as _ds
            v = it["transition_som"]
            if _nulo(v) or v == "nenhum":
                r["transition_som"] = "nenhum"
            elif _ds.som(str(v)):
                r["transition_som"] = str(v)
        if "template" in it:
            v = it["template"]
            if _nulo(v):
                r["template"] = None
            elif cenas_dp.template(str(v)):
                r["template"] = str(v)
                campos = it.get("template_campos") if isinstance(it.get("template_campos"), dict) else {}
                validos = {c["key"]: int(c.get("maxChars") or 120) for c in cenas_dp.campos_de_texto(str(v))}
                tc = {k: str(x).strip()[:validos[k]] for k, x in campos.items() if k in validos and str(x or "").strip()}
                if campos.get("_fundo") in cenas_dp.fundos_do_template(str(v)) + sorted(dp_fundos.IDS_CENA):
                    tc["_fundo"] = campos["_fundo"]
                if re.fullmatch(r"#[0-9a-fA-F]{6}", str(campos.get("_fundo_cor") or "")):
                    tc["_fundo_cor"] = campos["_fundo_cor"].upper()
                if campos.get("_legenda") in ("manter", "ocultar"):
                    tc["_legenda"] = campos["_legenda"]
                if campos.get("_fala") is False:
                    tc["_fala"] = False
                r["template_campos"] = tc or None
            else:
                avisos.append(f"T{n}: cena '{v}' desconhecida.")
        if len(r) > 1:
            out["trechos"].append(r)

    if isinstance(d.get("destaques"), list):
        hl = []
        ws = [w for w in palavras or [] if str(w.get("word", "")).strip()]
        for x in d["destaques"]:
            if not isinstance(x, dict) or not dp_destaques.estilo(str(x.get("estilo") or "")):
                if isinstance(x, dict):
                    avisos.append(f"Destaque com estilo '{x.get('estilo')}' desconhecido — ignorado.")
                continue
            texto_hl = str(x.get("texto") or "").strip()[:300]
            try:
                ini = float(x.get("start")) if x.get("start") is not None else None
            except (TypeError, ValueError):
                ini = None
            alvo = dp_destaques._norm(str(x.get("palavra") or (texto_hl.split() or [""])[0]))
            if alvo and ws:  # acha a palavra falada mais perto do tempo sugerido
                cand = [w for w in ws if dp_destaques._norm(w["word"]) == alvo]
                if cand:
                    w = min(cand, key=lambda w: abs(float(w["start"]) - ini)) if ini is not None else cand[0]
                    ini = float(w["start"])
            if x.get("avulso"):  # texto livre: o tempo é o que a IA mandou
                ini = ini if ini is not None else None
            if ini is None:
                avisos.append(f"Destaque \"{texto_hl[:30]}\" sem tempo nem palavra encontrada — ignorado.")
                continue
            try:
                fim = float(x["end"]) if x.get("end") is not None else ini + 2.5
            except (TypeError, ValueError):
                fim = ini + 2.5
            item = {"estilo": str(x["estilo"]), "start": max(0.0, ini), "end": min(duracao or 1e9, max(fim, ini + 0.8)), "texto": texto_hl,
                    "campos": {str(k): str(v)[:200] for k, v in (x.get("campos") or {}).items() if v not in (None, "")} if isinstance(x.get("campos"), dict) else {},
                    "origem": "ia"}
            if x.get("fundo") in dp_fundos.IDS_DESTAQUE:
                item["fundo"] = x["fundo"]
            item.update(estilo_de_texto(x, avisos))
            for k in ("fundo_cor", "cor"):
                if re.fullmatch(r"#[0-9a-fA-F]{6}", str(x.get(k) or "")):
                    item[k] = str(x[k]).upper()
            hl.append(item)
        out["destaques"] = dp_destaques.ancorar(hl, palavras, duracao) if palavras else hl  # avulsos mantêm o tempo
        out["substituir_destaques"] = d.get("substituir_destaques", True) is not False

    if isinstance(d.get("editoriais"), list):
        import dp_editorial
        eds = []
        for x in d["editoriais"][:30]:
            q = dp_editorial.normalizar(x, duracao)
            if q:
                eds.append(q)
            else:
                avisos.append(f"Quadro editorial \"{(x or {}).get('tipo', '?')}\" inválido — ignorado.")
        out["editoriais"] = eds

    if isinstance(d.get("graficos"), list):
        gs = []
        for x in d["graficos"]:
            g = dp_graficos.normalizar(x, duracao)
            if g:
                gs.append(g)
            else:
                avisos.append(f"Gráfico \"{(x or {}).get('titulo', '')}\" sem dados suficientes — ignorado.")
        out["graficos"] = gs

    if "filtro_cor" in d:
        v = d.get("filtro_cor")
        if _nulo(v):
            out["filtro_cor"] = "original"
        elif str(v) in fi_ok:
            out["filtro_cor"] = str(v)
        else:
            avisos.append(f"Filtro '{v}' desconhecido.")
    if isinstance(d.get("paleta"), dict) and re.fullmatch(r"#[0-9a-fA-F]{6}", str(d["paleta"].get("primaria") or "")):
        prim = str(d["paleta"]["primaria"]).upper()
        base = dict(dp_cores.derivar(prim))
        for k in ("secundaria", "acento"):
            if re.fullmatch(r"#[0-9a-fA-F]{6}", str(d["paleta"].get(k) or "")):
                base[k] = str(d["paleta"][k]).upper()
        out["paleta"] = base
    if isinstance(d.get("legenda"), dict) and d["legenda"].get("estilo") in {e["id"] for e in dp_legendas.ESTILOS}:
        lg = {"estilo": d["legenda"]["estilo"]}
        if d["legenda"].get("posicao") in ("base", "meio", "topo"):
            lg["posicao"] = d["legenda"]["posicao"]
        try:
            if d["legenda"].get("tamanho") is not None:
                lg["tamanho"] = round(max(0.035, min(0.1, float(d["legenda"]["tamanho"]))), 3)
        except (TypeError, ValueError):
            pass
        if isinstance(d["legenda"].get("maiusculas"), bool):
            lg["maiusculas"] = d["legenda"]["maiusculas"]
        if re.fullmatch(r"#[0-9a-fA-F]{6}", str(d["legenda"].get("cor_ativa") or "")):
            lg["cor_ativa"] = d["legenda"]["cor_ativa"].upper()
        if d["legenda"].get("fonte") in dp_destaques._FONTE.values():
            lg["fonte"] = d["legenda"]["fonte"]
        out["legenda"] = lg
    if isinstance(d.get("sons"), list):
        sons = []
        for x in d["sons"][:80]:
            try:
                if isinstance(x, dict) and dp_sons.som(str(x.get("som"))):
                    sons.append({"som": str(x["som"]), "start": round(max(0.0, float(x.get("start", 0))), 2),
                                 "volume": round(max(0.1, min(1.5, float(x.get("volume", 1.0) or 1.0))), 2)})
            except (TypeError, ValueError):
                continue
        out["sons"] = sons
    return out
