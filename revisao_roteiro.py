"""
🪄 revisao_roteiro.py — REVISÃO do roteiro INTEIRO sem encolher (v84_98)
=======================================================================

Depois que o roteiro foi escrito em partes (ou mesmo de uma vez), uma passada no TEXTO TODO deixa ele com cara de um
roteiro só, trabalhado — e não de capítulos colados ou de "texto de IA": costuras entre os capítulos, repetições,
frases genéricas/clichês, ritmo, concretude, laços abertos que não fecharam.

O truque pra não voltar MENOR (no modo 🪄 melhorar): a IA não reescreve o roteiro inteiro (é aí que ela resume). Ela devolve só as TROCAS
— {"de": trecho exato, "para": versão melhor} — e o site aplica cada uma no texto. O que não for achado é avisado.

v84_99: modo ✂️ ENXUGAR (automático quando o roteiro passou de 110% do tempo pedido): as trocas podem encurtar ou apagar
("para": "") — corta repetição entre capítulos, recapitulações, suspense vazio e fórmulas de análise até o tamanho certo.
E o "de" é achado mesmo com aspas/travessões diferentes („…“ × "…").
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

CLICHES = ["Mas isso não é tudo", "Prepare-se", "uma história que vai te deixar sem palavras", "o que aconteceu a seguir vai te chocar",
           "Mas a verdade era ainda mais", "Nada seria como antes", "E é aqui que tudo muda", "Fique até o final",
           "Neste vídeo, vamos", "Sem mais delongas", "A resposta pode te surpreender", "uma reviravolta inesperada"]


MODOS = {"auto": "🤖 automático (enxuga se passou do tempo)", "melhorar": "🪄 melhorar sem encurtar",
         "enxugar": "✂️ enxugar até o tempo pedido", "titulo": "🧵 amarrar ao título (tese, pontes, fechamento)",
         "escopo": "🎯 tirar o que foge do título (assunto vizinho vira 1 frase + “outro vídeo”)"}


def _palavras_titulo(titulo: str) -> List[str]:
    import metodo_roteiro
    return list(dict.fromkeys(metodo_roteiro._conteudo(titulo)))


def achados_titulo(roteiro: str, titulo: str) -> List[str]:
    """🧵 O título aparece na abertura e no fechamento? (sinal simples, sem IA)"""
    import metodo_roteiro
    chaves = _palavras_titulo(titulo)
    if not chaves or not roteiro.strip():
        return []
    pal = roteiro.split()
    n = len(pal)
    ini = set(metodo_roteiro._conteudo(" ".join(pal[:max(60, n // 7)])))
    fim = set(metodo_roteiro._conteudo(" ".join(pal[-max(60, n // 7):])))
    out = []
    faltam_ini = [c for c in chaves if c not in ini]
    faltam_fim = [c for c in chaves if c not in fim]
    if len(faltam_ini) > len(chaves) / 2:
        out.append(f"- 🧵 A ABERTURA não apresenta a tese do título “{titulo}” (faltam as ideias dele no começo).")
    if len(faltam_fim) > len(chaves) / 2:
        out.append(f"- 🧵 O FECHAMENTO não volta ao título “{titulo}” nem responde a ele.")
    return out


def palavras(texto: str) -> int:
    return len(re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]", " ", str(texto or "")).split())


def modo_efetivo(modo: str, n: int, alvo: int) -> str:
    modo = modo if modo in MODOS else "auto"
    if modo == "auto":
        return "enxugar" if alvo and n > alvo * 1.1 else "melhorar"
    return modo


def prompt(roteiro: str, idioma: str = "o idioma do roteiro", tema: str = "", foco: str = "", alvo_palavras: int = 0,
           minutos: float = 0, modo: str = "auto", titulo: str = "") -> str:
    import metodo_roteiro
    roteiro = str(roteiro or "").strip()
    if not roteiro:
        raise ValueError("Ainda não tem roteiro pra revisar.")
    n = palavras(roteiro)
    modo = modo_efetivo(modo, n, alvo_palavras)
    enx = modo == "enxugar"
    cortar = max(0, n - alvo_palavras) if alvo_palavras else int(n * 0.2)
    fio = modo == "titulo"
    esc = modo == "escopo"  # 🎯 v84_179
    titulo = " ".join(str(titulo or tema or "").split())[:200]
    max_trocas = max(15, min(60, n // 60)) if not enx else max(25, min(90, n // 50))
    if fio:
        max_trocas = max(20, min(70, n // 45))
    if esc:
        max_trocas = max(25, min(90, n // 45))
    L = [f"Você é o roteirista-chefe revisando o roteiro COMPLETO de um vídeo{(' sobre ' + tema) if tema else ''} (~{n} palavras, "
         f"em {idioma}). Ele foi escrito em partes; agora ele precisa soar como UM roteiro só, escrito com cuidado por uma "
         "pessoa — não como capítulos colados nem como texto genérico de IA.", ""]
    if (foco or "").strip():  # 🙋 v84_169: o pedido do autor vem PRIMEIRO (antes ficava no fim e a IA quase ignorava)
        L += ["## 🙋 PEDIDO DO AUTOR — PRIORIDADE MÁXIMA",
              foco.strip()[:1500],
              "Isto vem antes de tudo abaixo: faça as trocas que forem precisas pra cumprir o pedido (pode usar muitas), "
              "mesmo que isso mude a estrutura (abertura, transições, fechamento).", ""]
    if titulo and not enx and not esc:
        L += [f"## 🧵 FIO CONDUTOR — o título é a promessa: “{titulo}”" + (" (FOCO DESTA REVISÃO)" if fio else ""),
              "O roteiro tem de entregar o que o título promete e amarrar TODOS os assuntos nele. Confira e conserte com trocas:",
              "A. ABERTURA: logo depois do gancho, a TESE do título com as palavras dele (ou bem perto) + 2-4 frases que mostram de "
              "relance os assuntos que vêm aí como provas da tese. → troque o 1º ou 2º parágrafo por ele mesmo + essas frases.",
              "B. PONTES: em CADA troca de assunto, a 1ª frase do assunto novo ganha antes uma frase-ponte que liga o anterior ao "
              "próximo e ao título (ex.: “Mas o perigo não vem só pelo ar…”). → \"de\": a 1ª frase do assunto novo; \"para\": "
              "a frase-ponte + a mesma frase. Nenhum pulo seco de assunto pode sobrar.",
              "C. FIM DE CADA BLOCO: uma frase dizendo o que aquilo acrescenta à pergunta do título.",
              "D. FECHAMENTO: o último parágrafo volta ao título e RESPONDE a ele somando as provas (sim / não / depende, com os "
              "fatos), e termina com uma pergunta ao público ligada ao título. → troque o último parágrafo.",
              "E. Título exagerado (“o pior”, “o mais…”): trate como pergunta a investigar — sem inventar pra confirmar.",
              "F. Frase repetida (a mesma frase ou ideia dita de novo logo em seguida): apague a repetição (\"para\": \"\").", ""]
    if esc:
        L += [f"## 🎯 MODO ESCOPO — o vídeo cobre SÓ o necessário pra entender o título “{titulo}”",
              "1. Primeiro decida (pra você): quais 3 a 6 passos a pessoa PRECISA entender pra responder o título. Esse é o vídeo.",
              "2. Todo trecho que não serve a esses passos é ASSUNTO VIZINHO (outra época, outro objeto famoso, outra descoberta, "
              "história paralela): apague o trecho inteiro (\"para\": \"\") — ou, se a falta dele deixaria um buraco, troque por "
              "UMA frase simples que diga que isso terá um vídeo próprio (no idioma do roteiro; ex. em alemão: „Das ist eine "
              "eigene Geschichte — darüber machen wir ein eigenes Video.“). No máximo 2 desses avisos no roteiro inteiro.",
              "3. A mesma história contada em dois lugares (o mesmo evento, a mesma descoberta): fica UMA vez, no lugar mais forte.",
              "4. Conceito complexo que É necessário e ficou difícil: troque por uma analogia do dia a dia + uma frase do mecanismo.",
              "5. Costure: depois de um corte, a frase seguinte precisa continuar fazendo sentido (ajuste a ponte se precisar).",
              "6. Saudação repetida no meio (“Willkommen zurück”), referência a outro episódio e fonte dita em voz alta (“so X in "
              "ihrem Vortrag”) saem.",
              "O roteiro vai ficar MAIS CURTO — tudo bem: é melhor 4 ideias bem entendidas que 9 de passagem"
              + (f" (o vídeo pedido tem ~{alvo_palavras} palavras; agora tem {n})." if alvo_palavras else "."), ""]
    if enx:
        alvo_txt = f"~{alvo_palavras} palavras" + (f" (≈ {minutos:g} min de narração)" if minutos else "")
        L += ["## ✂️ MODO ENXUGAR — o roteiro está LONGO demais",
              f"Ele tem {n} palavras e o vídeo pedido tem {alvo_txt}: corte ~{cortar} palavras "
              f"(~{round(100 * cortar / max(1, n))}% do texto). O vídeo fica melhor mais curto e denso — sem perder fatos essenciais.",
              "Onde cortar primeiro:",
              "1. REPETIÇÃO ENTRE CAPÍTULOS: a mesma ideia ou fato contado de novo (ex.: \"a polícia ignorou os sinais\", "
              "\"as vítimas eram jovens vulneráveis\", o informante da polícia) — fica só a 1ª vez (ou a melhor), as outras saem.",
              "2. RECAPITULAÇÕES: prisão, julgamento, incertezas e legado que refazem o resumo do caso — corte o resumo, fique com "
              "o que é NOVO em cada um.",
              "3. ENCHIMENTO: frases de suspense vazias, transições que só anunciam, fórmulas de análise, explicação em dobro.",
              "4. Parágrafos inteiros que não trazem fato novo nem consequência.", ""]
    try:  # o que o site já achou: repetições entre parágrafos, assuntos que voltam, fórmulas, fragmentos
        import checagem_roteiro
        achados = checagem_roteiro.resumo_texto(checagem_roteiro.analisar(roteiro, tema), roteiro)
    except Exception:  # noqa: BLE001
        achados = []
    if titulo and not enx:
        achados = achados_titulo(roteiro, titulo) + achados
    try:  # 🔁 frases quase iguais em sequência
        import metodo_roteiro as _mr
        _t, rep = _mr.tirar_repeticoes(roteiro)
        achados += [f"- 🔁 Frase repetida logo em seguida (apague): “{x[:160]}”" for x in rep[:12]]
    except Exception:  # noqa: BLE001
        pass
    if achados:
        L += ["## O que o site já achou no texto (as linhas são do roteiro abaixo, 1ª linha = 1) — resolva primeiro"] + achados + [""]
    L += ["## O que melhorar (em ordem de importância)",
          "1. COSTURAS: a passagem entre um capítulo e o próximo — retomadas repetidas (\"Como vimos\", \"Agora\", \"Voltando\"), "
          "ganchos que não se cumprem, a mesma informação dita duas vezes em partes diferentes.",
          "2. GENÉRICO / CLICHÊ DE IA: troque frases vazias e de efeito por algo CONCRETO do próprio caso (um detalhe, um nome, "
          "uma data, uma imagem). Ex. de frases a eliminar: " + "; ".join(f"“{c}”" for c in CLICHES[:8]) + ".",
          "3. REPETIÇÕES de palavras, estruturas e começos de frase (\"Ele…\", \"Mas…\", \"E…\") em sequência.",
          "4. RITMO: frases do mesmo tamanho seguidas; frase que amontoa informação (divida em unidades de sentido).",
          "5. LAÇOS: pergunta plantada que nunca é respondida, ou revelação adiantada antes da hora.",
          "6. Clareza pra quem OUVE: referência ambígua (\"ele\" com dois homens na cena), número/data difícil de acompanhar.",
          "", "## Regras de narração (confira o roteiro inteiro contra cada uma)"]
    L += [f"- {r}" for r in metodo_roteiro.REGRAS_NARRACAO]
    L += ["", "## Regras das trocas",
          f"- Devolva no máximo {max_trocas} trocas, as que mais fazem diferença.",
          "- \"de\": um trecho COPIADO EXATAMENTE do roteiro (uma frase, poucas frases seguidas ou um parágrafo inteiro — mesma "
          "pontuação, mesmas aspas, mesmas maiúsculas) — o site procura esse texto e troca."]
    if esc:
        L += ["- \"para\": \"\" (vazio) pra APAGAR o assunto vizinho, ou a frase curta que o substitui. Pode cortar parágrafos "
              "inteiros (copie o parágrafo inteiro no \"de\"). Não corte o que a pergunta do título precisa."]
    elif enx:
        L += ["- \"para\": a versão mais curta daquele trecho — ou \"\" (vazio) pra APAGAR o trecho inteiro. Some as palavras "
              f"cortadas: o total tem que chegar perto de {cortar}. Não corte fatos essenciais nem a distinção entre fato, "
              "alegação e interpretação; quando cortar uma conclusão sem fonte, troque por uma versão atribuída ou suavizada."]
    else:
        L += ["- \"para\": a versão melhorada daquele trecho. NUNCA mais curta no geral: o roteiro final tem que ficar do MESMO "
              "tamanho ou maior. Pode acrescentar um detalhe concreto que já esteja no roteiro ou nas fontes desta conversa — "
              "nunca invente fatos."]
    L += ["- Não mexa nas marcas: [[INSCREVA]], [[VENDA]], [I3], [M2], [CENA 4] e tags de voz ficam exatamente onde estão "
          "(não inclua elas no \"de\").",
          "- Mantenha os fatos, a ordem da história e o tom; mantenha a distinção entre fato, alegação e interpretação."]
    if foco:
        L.append(f"- Lembrete — o pedido do autor (lá em cima) é a prioridade: {foco.strip()[:300]}")
    L += ["", "## Resposta — SOMENTE um JSON válido, assim:",
          json.dumps({"trocas": [{"de": "trecho exato do roteiro", "para": "trecho melhorado" + (" (ou \"\" pra apagar)" if enx else ""),
                                  "motivo": "repetição | enchimento | costura | clichê | prova | fórmula | ritmo | laço | clareza"}],
                      "observacoes": "o que mais você mudaria (opcional)"}, ensure_ascii=False, indent=1),
          "", "## Roteiro", roteiro]
    return "\n".join(L)


# aspas, apóstrofos, travessões e reticências: a IA costuma trocar „…“ por "…", – por -, … por ...
_EQUIV = [("\"“”„‟«»‹›＂", '["“”„‟«»‹›＂]'), ("'‘’‚‛`´", "['‘’‚‛`´]"), ("-–—‒", "[-–—‒]")]


def _padrao(de: str) -> str:
    out = []
    for tok in de.split():
        t = tok.replace("…", "...")
        p = ""
        i = 0
        while i < len(t):
            if t.startswith("...", i):
                p += r"(?:\.\.\.|…)"
                i += 3
                continue
            ch = t[i]
            cls = next((c for chars, c in _EQUIV if ch in chars), None)
            p += cls if cls else re.escape(ch)
            i += 1
        out.append(p)
    return r"\s+".join(out)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def aplicar(roteiro: str, resposta: str, apagar: bool = True) -> Dict[str, Any]:
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
        if not de.strip() or de == para or (not para.strip() and not apagar):
            continue
        if re.search(r"\[\[|\]\]", de) and not re.search(r"\[\[|\]\]", para):  # não deixa sumir marca de chamada
            nao.append({"de": de[:120], "motivo": "a troca apagava uma marca [[…]]"})
            continue
        if de in texto:
            texto = texto.replace(de, para, 1)
            aplicadas.append({"de": de[:200], "para": para[:300], "motivo": str(t.get("motivo") or "")[:40]})
            continue
        # tolerante a espaço/quebra de linha, aspas („“ × ""), apóstrofos, travessões e reticências diferentes
        m = re.search(_padrao(de), texto)
        if m:
            texto = texto[:m.start()] + para + texto[m.end():]
            aplicadas.append({"de": de[:200], "para": para[:300], "motivo": str(t.get("motivo") or "")[:40]})
        else:
            nao.append({"de": de[:120], "motivo": "trecho não achado no roteiro"})

    texto = re.sub(r"[ \t]+\n", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()  # parágrafos apagados não deixam buraco
    texto = re.sub(r"(\[\[[^\]]+\]\])(\s*\n\s*\1)+", r"\1", texto)  # duas marcas iguais coladas (o trecho entre elas saiu)
    import marcas_seguras  # 🔒 marca de imagem/cena que sumiu numa troca volta pro mesmo ponto
    texto, _volta = marcas_seguras.restaurar(str(roteiro or ""), texto, chamadas=False)
    import metodo_roteiro  # 🔁 v84_169: frase quase igual logo em seguida sai (mesmo se a IA não pegou)
    texto, repetidas = metodo_roteiro.tirar_repeticoes(texto)
    for x in repetidas:
        aplicadas.append({"de": x[:200], "para": "", "motivo": "repetição (site)"})
    pal = palavras
    return {"texto": texto, "aplicadas": aplicadas, "nao_achadas": nao, "palavras_antes": pal(roteiro), "palavras_depois": pal(texto),
            "observacoes": str((d.get("observacoes") if isinstance(d, dict) else "") or "")[:1500]}
