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
STATUS_NOVOS = ("atualizado", "trocado", "hipotetico", "tirado", "mantido")

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


def regra_sem_fonte(pol: str, com_web: bool) -> str:
    """O passo 2 do prompt da checagem: o que fazer com o que está errado, velho ou sem confirmação."""
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
    for c in (d.get("correcoes") if isinstance(d, dict) else d) or []:
        if not isinstance(c, dict) or not str(c.get("de") or "").strip() or c.get("para") is None:
            continue
        st = str(c.get("status") or "").strip().lower().split()[0] if str(c.get("status") or "").strip() else ""
        out.append({"item": str(c.get("item") or "").replace(" ", "").upper()[:6], "de": str(c["de"]), "para": str(c["para"]),
                    "status": st if st in STATUS_NOVOS + ("corrigido",) else "", "fonte": str(c.get("fonte") or "")[:300],
                    "motivo": str(c.get("problema") or "")[:200], "eixo": "alegacao"})
    return out


def chamar_ia(prompt: str, acao: str, rotulo: str) -> Tuple[str, str]:
    """(resposta, quem): com a busca do Google (🔷 Gemini) quando precisa de internet e tem chave; senão a 🤖 IA do site."""
    import gemini_servico as gm
    precisa_web = acao in ("atualizar", "equivalente")
    if precisa_web and gm.chave():
        r = gm.checar(prompt, rotulo=rotulo)
        return str(r.get("texto") or ""), "gemini"
    import ia_servico as ia
    if ia.motivo_desligado("roteiros") is None:
        with ia.rotulo(rotulo):
            r = ia.chamar("roteiros", "Responda só o JSON pedido.", prompt, max_tokens=6000, effort="low", timeout=300)
        if r:
            return str(r), "ia_site"
    if gm.chave():
        r = gm.checar(prompt, rotulo=rotulo)
        return str(r.get("texto") or ""), "gemini"
    raise RuntimeError("Sem IA pra isso: ligue a 🤖 IA do site (Roteiros) ou cole a chave do 🔷 Gemini na checagem."
                       + (" Pra atualizar/trocar por caso confirmado o melhor é o Gemini (tem a busca do Google)." if precisa_web else ""))
