"""🧭 v84_414 — o que fazer com o que a checagem NÃO confirmou.

Antes: "sem fonte" só era atribuído/suavizado ("conta-se que…") e o que ficava sem resposta continuava no roteiro do
jeito que estava. Agora, por item (ou todos de uma vez), dá pra escolher:

  🔄 atualizar    — dado velho (aula de 20–30 anos atrás): troca pelo dado MAIS RECENTE confirmado, com o ano
  🔁 equivalente  — caso/história sem fonte: troca por um caso REAL e documentado que mostra o MESMO ponto (com link)
  🧪 hipotético   — vira exemplo assumido ("Imagine uma estudante de medicina…") — honesto, sem fingir que aconteceu
  ✂ tirar         — sai do roteiro, costurando a frase de antes com a de depois
  ✔ manter        — você conferiu / é opinião assumida: fica como está

E a POLÍTICA automática (o que a checagem na internet faz sozinha com o que não confirma): por padrão "auto" =
atualiza o que é dado velho, troca caso sem fonte por um equivalente confirmado, e se não achar vira hipotético ou sai.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

ACOES = {
    "auto": ("🧭 automático (a IA escolhe)", "corrigido"),
    "atualizar": ("🔄 atualizar", "atualizado"),
    "equivalente": ("🔁 trocar por caso confirmado", "trocado"),
    "hipotetico": ("🧪 virar exemplo hipotético", "hipotetico"),
    "tirar": ("✂ tirar do roteiro", "tirado"),
    "manter": ("✔ manter", "mantido"),
}
POLITICAS = {
    "auto": "🧭 automático: atualiza dado velho, troca caso sem fonte por um equivalente confirmado; se não achar, vira hipotético ou sai",
    "suavizar": "〰 só atribuir/suavizar (o jeito antigo)",
    "tirar": "✂ tirar tudo que não se confirma",
}
POLITICA_PADRAO = "auto"
STATUS_NOVOS = ("atualizado", "trocado", "hipotetico", "tirado", "mantido", "confirmado", "falso", "sem_fonte")

FONTE_ANTIGA = ("O material de origem pode ser uma aula/curso de 20 a 30 anos atrás: número, estatística, \"hoje em dia\", "
                "\"atualmente\", recorde, \"o maior/mais recente\" e o estado de uma pesquisa podem estar DESATUALIZADOS — "
                "isso não é erro de quem falou, é tempo.")


def politica(cfg: Dict[str, Any] = None) -> str:
    if cfg is None:
        try:
            import site_config
            cfg = site_config.load_site_config()
        except Exception:  # noqa: BLE001
            cfg = {}
    p = str((cfg or {}).get("checagem_sem_fonte") or "")
    return p if p in POLITICAS else POLITICA_PADRAO


# ✍ v84_432: a correção trocava a frase e deixava a velha do lado ("Um emprego, um relacionamento…" duas vezes seguidas)
REGRA_TROCA = (" CADA CORREÇÃO SUBSTITUI o trecho (\"de\" = a frase inteira como está, \"para\" = a frase nova): nunca "
               "deixe a frase velha e a nova juntas, nem repita na frase nova o que a frase vizinha já diz. Mantenha o tamanho e "
               "o ritmo de fala; no máximo UMA ressalva curta — nada de \"não é uma reação automática, mas um exemplo para "
               "pensar\", \"alguns filósofos argumentam…, mas isso não significa…\". Citação: autor + obra na fala; ano e "
               "página não entram (vão nas fontes da descrição). A correção NÃO desmonta a tese do vídeo: se a tese precisa de "
               "ressalva, a ressalva é curta e o texto em volta continua coerente com ela (nada de uma frase solta que "
               "contradiz o resto); e não repita um parágrafo inteiro com outras palavras ao lado do original.")


def regra_sem_fonte(pol: str, com_web: bool) -> str:
    """O passo 2 do prompt da checagem: o que fazer com o que está errado, velho ou sem confirmação."""
    extra = ""
    try:  # 🚫 v84_444: a IA de fora (com internet) descobria de quem é a aula e atribuía a tese a ele
        import metodo_roteiro as _mr
        extra = " " + _mr.regra_nomes(_mr.nomes_proibidos()) + (
            " NUNCA diga de onde o roteiro saiu (aula, palestra, curso, data, \"o falante\", \"o trecho\"): uma tese sem "
            "autor histórico fica como \"uma leitura possível\", na voz do narrador.")
    except Exception:  # noqa: BLE001
        pass
    return _regra_sem_fonte(pol, com_web) + REGRA_TROCA + extra


def _regra_sem_fonte(pol: str, com_web: bool) -> str:
    if pol == "suavizar":
        return ("Errado → corrija. Sem confirmação → atribua (\"segundo…\", \"de acordo com…\"), suavize ou tire o detalhe. "
                "NUNCA invente um dado pra tapar buraco.")
    if pol == "tirar":
        return ("Errado → corrija. Dado desatualizado → troque pelo mais recente confirmado, com o ano (status \"atualizado\"). "
                "Sem confirmação → TIRE do roteiro e costure a frase de antes com a de depois (status \"tirado\"). "
                "NUNCA invente um dado pra tapar buraco.")
    busca = ("que você CONFIRMOU na internet (com o link em \"fonte\")" if com_web
             else "MUITO conhecido e bem documentado (marque em \"fonte\" onde conferir)")
    return (FONTE_ANTIGA + "\n   Errado → corrija (\"corrigido\"). DADO DESATUALIZADO → troque pelo dado MAIS RECENTE "
            f"{busca}, dizendo o ano (\"segundo dados de 2023…\") — status \"atualizado\". "
            "CASO/HISTÓRIA/ANEDOTA SEM FONTE (alguém, um lugar, um episódio que ilustra a ideia) → troque por um caso REAL "
            f"equivalente {busca}, que mostre o MESMO ponto, mudando o mínimo do resto — status \"trocado\"; se não achar "
            "nenhum confiável, reescreva como exemplo ASSUMIDO (\"Imagine uma estudante de medicina…\") — status "
            "\"hipotetico\". NÚMERO/DATA/CITAÇÃO SEM FONTE e sem equivalente → tire o dado ou a frase — status \"tirado\". "
            "História pessoal de quem deu a aula (o pai dele, a vida dele) → generalize sem dono ou tire. "
            "NUNCA invente um dado, um caso ou uma citação pra tapar o buraco.")


# ------------------------------------------------------------------ resolver itens escolhidos
def _contexto(roteiro: str, afirmacao: str) -> Tuple[int, str]:
    import checagem_roteiro as ch
    pars = ch.paragrafos(roteiro)
    n = ch._linha_de(pars, afirmacao)
    texto = dict(pars)
    if not n:
        return 0, ""
    viz = [texto[k] for k in (n - 1, n, n + 1) if k in texto]
    return n, "\n\n".join(viz)


def prompt_resolver(roteiro: str, itens: List[Tuple[int, Dict[str, Any]]], acao: str, idioma: str = "português",
                    com_web: bool = True) -> str:
    if acao not in ACOES or acao == "manter":
        raise ValueError("Ação inválida.")
    blocos = []
    for i, v in itens:
        n, ctx = _contexto(roteiro, v.get("afirmacao") or "")
        blocos.append(f"### V{i + 1}\nAfirmação: „{v.get('afirmacao')}“\nPor que conferir: {v.get('por_que') or '—'}\n"
                      + (f"O que a checagem achou: {v.get('nota_web')}\n" if v.get("nota_web") else "")
                      + (f"Trecho do roteiro (linhas {n - 1}–{n + 1}):\n{ctx}" if ctx else "Trecho: ache no roteiro abaixo."))
    web = ("Você tem a BUSCA NA INTERNET: pesquise em fontes confiáveis (jornais, artigos científicos, órgãos oficiais, "
           "livros) e ponha o link em \"fonte\"." if com_web else
           "Você está SEM internet: use só o que é muito conhecido e bem documentado, e diga em \"fonte\" onde conferir.")
    o_que = {
        "auto": "Para CADA item, escolha o melhor caminho e diga qual em \"status\":\n   "
                + regra_sem_fonte("auto", com_web) + "\n   Se o item estiver CERTO (você confirmou), não mexa: devolva \"de\" = "
                "\"para\" com status \"confirmado\" e o link.",
        "atualizar": "ATUALIZE o dado pelo MAIS RECENTE que você confirmar, dizendo o ano (\"segundo dados de 2023…\"). Se "
                     "não houver dado novo confiável, deixe o antigo DATADO (\"nos anos 1990, estimava-se…\").",
        "equivalente": "TROQUE o caso/a história por um caso REAL e documentado que mostre o MESMO ponto (mesma função no "
                       "argumento), com nome, lugar e data quando houver. Mude o mínimo do resto do parágrafo. Se não achar "
                       "nenhum caso confiável, reescreva como exemplo ASSUMIDO (\"Imagine…\") e use o status \"hipotetico\".",
        "hipotetico": "REESCREVA como exemplo ASSUMIDO, sem fingir que aconteceu (\"Imagine uma estudante de medicina…\", "
                      "\"Pense num médico que…\"), mantendo o ponto que o trecho queria mostrar. Tire nomes, datas e números "
                      "que davam ar de fato.",
        "tirar": "TIRE a afirmação do roteiro. Se a frase inteira depende dela, tire a frase e ajuste a frase de antes ou a "
                 "de depois pra transição continuar natural (mínimo de mudança).",
    }[acao]
    st = ACOES[acao][1]
    return "\n".join([
        f"Você ajusta trechos de um roteiro narrado de YouTube em {idioma}. A checagem não conseguiu confirmar as afirmações "
        "abaixo. " + FONTE_ANTIGA, "", "## O que fazer com CADA item", o_que, web,
        "NUNCA invente dado, caso ou citação. Mantenha o tom e a língua do roteiro; não mexa em marcas [[...]] / [I3] / [CENA 2].",
        "", "## Itens", *blocos, "",
        "## Resposta — SOMENTE um JSON válido:",
        json.dumps({"correcoes": [{"item": "V1", "de": "trecho COPIADO EXATAMENTE do roteiro", "para": "o trecho novo (\"\" = apagar)",
                                   "status": f"{st} (ou hipotetico/tirado se não deu)", "fonte": "https://…",
                                   "problema": "o que mudou e por quê, em 1 frase"}]}, ensure_ascii=False, indent=1),
        "", "## Roteiro completo (pra achar os trechos)", roteiro])


def ler(resposta: str) -> List[Dict[str, Any]]:
    import json_ia
    try:
        d = json_ia.carregar(resposta)
    except ValueError as exc:
        raise ValueError(f"Não consegui ler o JSON: {exc}") from exc
    out = []
    lista = d
    if isinstance(d, dict):  # 🩹 v84_448: o JSON colado de outra IA às vezes vem com outra chave ("trocas", "correções"…)
        lista = next((d[k] for k in ("correcoes", "correções", "trocas", "corrections", "itens", "items") if isinstance(d.get(k), list)),
                     [d] if str(d.get("de") or "").strip() else [])
    for c in lista or []:
        if not isinstance(c, dict) or not str(c.get("de") or c.get("trecho") or "").strip():
            continue
        if "de" not in c:
            c = dict(c, de=c.get("trecho"))
        st = str(c.get("status") or "").strip().lower().split()[0] if str(c.get("status") or "").strip() else ""
        if c.get("para") is None:  # null = apagar só quando a IA disse que tirou; senão é resposta incompleta
            if st not in ("tirado", "falso"):
                continue
            c = dict(c, para="")
        out.append({"item": str(c.get("item") or "").replace(" ", "").upper()[:6], "de": str(c["de"]), "para": str(c["para"]),
                    "status": st if st in STATUS_NOVOS + ("corrigido",) else "", "fonte": str(c.get("fonte") or "")[:300],
                    "motivo": str(c.get("problema") or "")[:200], "eixo": "alegacao"})
    return out


def paragrafo_parecido(roteiro: str, trecho: str) -> str:
    """O parágrafo do roteiro mais parecido com um "de" que não bateu (pra IA copiar certo na 2ª tentativa)."""
    import difflib

    import checagem_roteiro as ch
    pars = [t for _n, t in ch.paragrafos(roteiro)]
    if not pars:
        return ""
    alvo = set(str(trecho or "").lower().split())

    def nota(t: str) -> float:
        pal = set(t.lower().split())
        return len(alvo & pal) / max(1, len(alvo)) + 0.3 * difflib.SequenceMatcher(None, trecho.lower(), t.lower()).ratio()
    return max(pars, key=nota)


def prompt_reacertar(roteiro: str, erradas: List[Dict[str, Any]], idioma: str = "português") -> str:
    """🎯 v84_448: a correção veio certa mas o "de" não bateu com o texto (a IA copiou a AFIRMAÇÃO resumida, não a frase
    do roteiro) → mostra o parágrafo de verdade e pede o "de" copiado letra por letra."""
    L = [f"Você ajusta um roteiro em {idioma}. Estas correções estão CERTAS, mas o trecho \"de\" não foi achado no roteiro "
         "(foi resumido ou reescrito). Para CADA uma: ache no PARÁGRAFO dado a frase (ou frases) que a correção muda e devolva "
         "\"de\" COPIADO LETRA POR LETRA desse parágrafo (sem as marcas [[…]] / [I3]), e \"para\" = essa mesma frase já "
         "corrigida, no mesmo tom. Se a correção não se aplica a esse parágrafo, não devolva o item.", ""]
    for k, t in enumerate(erradas, 1):
        L += [f"### C{k} (item {t.get('item') or '—'})", f"\"de\" que não bateu: {t['de']}", f"Correção pedida: {t['para'] or '(apagar)'}",
              f"Parágrafo do roteiro:\n{paragrafo_parecido(roteiro, t['de'])}", ""]
    L += ["## Resposta — SOMENTE um JSON válido:",
          json.dumps({"correcoes": [{"item": "V1", "de": "frase COPIADA do parágrafo", "para": "a frase corrigida",
                                     "status": "corrigido", "fonte": "", "problema": ""}]}, ensure_ascii=False, indent=1)]
    return "\n".join(L)


def chamar_ia(prompt: str, acao: str, rotulo: str) -> Tuple[str, str]:
    """(resposta, quem). Precisa de internet (atualizar / caso confirmado / automático): 🔷 Gemini → se ele falhar
    (cota, sem chave) → 🤖 Claude do site COM a busca na internet. Sem internet (hipotético / tirar): Claude → Gemini."""
    import gemini_servico as gm
    import ia_servico as ia
    precisa_web = acao in ("atualizar", "equivalente", "auto")
    erros = []

    def gemini():
        r = gm.checar(prompt, rotulo=rotulo)
        return str(r.get("texto") or "")

    def claude():
        if ia.motivo_desligado("roteiros") is not None:
            raise RuntimeError("a 🤖 IA do site está desligada (" + str(ia.motivo_desligado("roteiros")) + ")")
        with ia.rotulo(rotulo):
            r = ia.chamar("roteiros", "Responda só o JSON pedido.", prompt, max_tokens=8000, effort="low", timeout=420,
                          web=precisa_web)
        if not r:
            raise RuntimeError("o Claude não respondeu (veja as últimas chamadas em 🤖 IA)")
        return str(r)

    ordem = ([("gemini", gemini)] if gm.chave() else []) + [("ia_site", claude)] if precisa_web else \
        [("ia_site", claude)] + ([("gemini", gemini)] if gm.chave() else [])
    for quem, f in ordem:
        try:
            t = f()
            if t.strip():
                return t, quem
        except Exception as exc:  # noqa: BLE001 — cota do Gemini, rede…
            erros.append(f"{'🔷 Gemini' if quem == 'gemini' else '🤖 Claude'}: {str(exc)[:200]}")
    raise RuntimeError("Nenhuma IA respondeu — " + " · ".join(erros or ["ligue a 🤖 IA do site ou cole a chave do 🔷 Gemini"])
                       + ". Dá pra usar 📋 o prompt numa outra IA com internet e colar a resposta.")
