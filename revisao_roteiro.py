"""
🪄 revisao_roteiro.py — REVISÃO do roteiro INTEIRO sem encolher (v84_98)
=======================================================================

Depois que o roteiro foi escrito em partes (ou mesmo de uma vez), uma passada no TEXTO TODO deixa ele com cara de um
roteiro só, trabalhado — e não de capítulos colados ou de "texto de IA": costuras entre os capítulos, repetições,
frases genéricas/clichês, ritmo, concretude, laços abertos que não fecharam.

O truque pra não voltar MENOR: a IA não reescreve o roteiro inteiro (é aí que ela resume). Ela devolve só as TROCAS
— {"de": trecho exato, "para": versão melhor} — e o site aplica cada uma no texto. O que não for achado é avisado.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

CLICHES = ["Mas isso não é tudo", "Prepare-se", "uma história que vai te deixar sem palavras", "o que aconteceu a seguir vai te chocar",
           "Mas a verdade era ainda mais", "Nada seria como antes", "E é aqui que tudo muda", "Fique até o final",
           "Neste vídeo, vamos", "Sem mais delongas", "A resposta pode te surpreender", "uma reviravolta inesperada"]


def prompt(roteiro: str, idioma: str = "o idioma do roteiro", tema: str = "", foco: str = "") -> str:
    roteiro = str(roteiro or "").strip()
    if not roteiro:
        raise ValueError("Ainda não tem roteiro pra revisar.")
    n = len(re.sub(r"\[[^\]]*\]", " ", roteiro).split())
    max_trocas = max(15, min(60, n // 60))
    L = [f"Você é o roteirista-chefe revisando o roteiro COMPLETO de um vídeo{(' sobre ' + tema) if tema else ''} (~{n} palavras, "
         f"em {idioma}). Ele foi escrito em partes; agora ele precisa soar como UM roteiro só, escrito com cuidado por uma "
         "pessoa — não como capítulos colados nem como texto genérico de IA.", "",
         "## O que melhorar (em ordem de importância)",
         "1. COSTURAS: a passagem entre um capítulo e o próximo — retomadas repetidas (\"Como vimos\", \"Agora\", \"Voltando\"), "
         "ganchos que não se cumprem, a mesma informação dita duas vezes em partes diferentes.",
         "2. GENÉRICO / CLICHÊ DE IA: troque frases vazias e de efeito por algo CONCRETO do próprio caso (um detalhe, um nome, "
         "uma data, uma imagem). Ex. de frases a eliminar: " + "; ".join(f"“{c}”" for c in CLICHES[:8]) + ".",
         "3. REPETIÇÕES de palavras, estruturas e começos de frase (\"Ele…\", \"Mas…\", \"E…\") em sequência.",
         "4. RITMO: frases do mesmo tamanho seguidas; frase que amontoa informação (divida em unidades de sentido).",
         "5. LAÇOS: pergunta plantada que nunca é respondida, ou revelação adiantada antes da hora.",
         "6. Clareza pra quem OUVE: referência ambígua (\"ele\" com dois homens na cena), número/data difícil de acompanhar.", "",
         "## Regras das trocas",
         f"- Devolva no máximo {max_trocas} trocas, as que mais fazem diferença.",
         "- \"de\": um trecho COPIADO EXATAMENTE do roteiro (uma frase ou poucas frases seguidas, mesma pontuação, mesmas "
         "maiúsculas) — o site procura esse texto e troca.",
         "- \"para\": a versão melhorada daquele trecho. NUNCA mais curta no geral: o roteiro final tem que ficar do MESMO "
         "tamanho ou maior. Pode acrescentar um detalhe concreto que já esteja no roteiro ou nas fontes desta conversa — "
         "nunca invente fatos.",
         "- Não mexa nas marcas: [[INSCREVA]], [[VENDA]], [I3], [M2], [CENA 4] e tags de voz ficam exatamente onde estão "
         "(não inclua elas no \"de\").",
         "- Mantenha os fatos, a ordem da história e o tom; mantenha a distinção entre fato, alegação e interpretação."]
    if foco:
        L.append(f"- Pedido extra (prioridade): {foco.strip()[:800]}")
    L += ["", "## Resposta — SOMENTE um JSON válido, assim:",
          json.dumps({"trocas": [{"de": "trecho exato do roteiro", "para": "trecho melhorado", "motivo": "costura | clichê | repetição | ritmo | laço | clareza"}],
                      "observacoes": "o que mais você mudaria (opcional)"}, ensure_ascii=False, indent=1),
          "", "## Roteiro", roteiro]
    return "\n".join(L)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def aplicar(roteiro: str, resposta: str) -> Dict[str, Any]:
    """Aplica as trocas (exatas; ou ignorando espaços/quebras). → {texto, aplicadas, nao_achadas, palavras_antes/depois}."""
    import json_ia
    try:
        d = json_ia.carregar(resposta)
    except ValueError as exc:
        raise ValueError(f"Não consegui ler o JSON das trocas: {exc}") from exc
    trocas = (d.get("trocas") if isinstance(d, dict) else d) or []
    texto = str(roteiro or "")
    aplicadas, nao = [], []
    for t in trocas if isinstance(trocas, list) else []:
        if not isinstance(t, dict):
            continue
        de, para = str(t.get("de") or ""), str(t.get("para") or "")
        if not de.strip() or not para.strip() or de == para:
            continue
        if re.search(r"\[\[|\]\]", de) and not re.search(r"\[\[|\]\]", para):  # não deixa sumir marca de chamada
            nao.append({"de": de[:120], "motivo": "a troca apagava uma marca [[…]]"})
            continue
        if de in texto:
            texto = texto.replace(de, para, 1)
            aplicadas.append({"de": de[:200], "para": para[:300], "motivo": str(t.get("motivo") or "")[:40]})
            continue
        # tolerante a espaço/quebra de linha diferentes
        padrao = r"\s+".join(re.escape(x) for x in de.split())
        m = re.search(padrao, texto)
        if m:
            texto = texto[:m.start()] + para + texto[m.end():]
            aplicadas.append({"de": de[:200], "para": para[:300], "motivo": str(t.get("motivo") or "")[:40]})
        else:
            nao.append({"de": de[:120], "motivo": "trecho não achado no roteiro"})

    def pal(x):
        return len(re.sub(r"\[[^\]]*\]", " ", x).split())
    return {"texto": texto, "aplicadas": aplicadas, "nao_achadas": nao, "palavras_antes": pal(roteiro), "palavras_depois": pal(texto),
            "observacoes": str((d.get("observacoes") if isinstance(d, dict) else "") or "")[:1500]}
