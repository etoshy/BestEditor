"""🧪 v84_486 — Verificação de qualidade do roteiro DEPOIS de pronto (não mexe em como ele é escrito).

Uma IA (a do site ou outra, pelo prompt) lê o roteiro inteiro + as notas/fonte + o mapa do tema e devolve só as
correções, trecho a trecho, num JSON: {"correcoes": [{"tipo", "de", "para", "porque"}], "resumo"}. O site aplica as trocas
(o mesmo aplicador da 🪄 revisão / 🔎 checagem) e guarda uma versão no 🕘 histórico.

O que ela procura (os erros que apareceram nos roteiros do texto bruto):
  repeticao, contradicao, conceito_errado, exemplo_ruim, referencia_orfa, frase_quebrada, bastidor, faltou, fechamento, chamada
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

TIPOS = {
    "repeticao": "🔁 repetição",
    "contradicao": "⚖ contradição",
    "conceito_errado": "📐 conceito errado",
    "exemplo_ruim": "🧩 exemplo que não funciona",
    "referencia_orfa": "👻 referência órfã",
    "frase_quebrada": "🩹 frase quebrada",
    "bastidor": "🎬 bastidor",
    "faltou": "➕ faltou do mapa",
    "fechamento": "🔚 fechamento",
    "chamada": "📣 chamada",
}
MAX_CORRECOES = 30


def prompt(roteiro: str, tema: str = "", fonte: str = "", mapa: str = "", idioma: str = "português do Brasil",
           alvo_palavras: int = 0, canal: str = "") -> str:
    roteiro = str(roteiro or "").strip()
    if not roteiro:
        raise ValueError("Ainda não tem roteiro pra verificar.")
    n = len(re.sub(r"\[[^\]]*\]", " ", roteiro).split())
    L = [f"Você é o EDITOR-CHEFE que confere um roteiro de YouTube JÁ PRONTO{(' sobre: ' + tema) if tema else ''}"
         f"{(' (canal ' + canal + ')') if canal else ''}, em {idioma}. Ele vai ser narrado em voz alta. NÃO reescreva o "
         "roteiro: ache os ERROS e devolva só a correção de cada trecho.", "",
         "## O que procurar (nesta ordem de importância)",
         "1. conceito_errado — uma definição ou explicação que contradiz a FONTE abaixo (ex.: o roteiro chama de \"resposta "
         "indireta\" o que a fonte chama de fuga). A fonte manda.",
         "2. contradicao — um trecho do roteiro diz uma coisa e outro diz o contrário (ex.: \"isso não desmente a regra\" × "
         "\"isso é o que desmente a regra\"). Fica a versão certa; a errada é corrigida.",
         "3. exemplo_ruim — cena absurda, exemplo que não mostra a ideia (ou mostra outra), ligação forçada entre dois "
         "assuntos que não se ligam.",
         "4. repeticao — a mesma explicação, regra, frase-modelo ou pergunta ao público em dois ou mais lugares. Fica a melhor "
         "vez; nas outras, troque por conteúdo NOVO do mesmo tamanho (ver TAMANHO) ou por uma frase-ponte curta.",
         "5. referencia_orfa — \"o colega do prazo\", \"como no caso de…\", \"também\" no começo, citando algo que NÃO "
         "aparece antes no roteiro.",
         "6. frase_quebrada — frase sem verbo, cortada, que não fecha, ou que começa solta depois de um corte.",
         "7. bastidor — \"a parte anterior\", \"onde a conversa anterior parou\", \"este roteiro\", \"eu sou o narrador\", "
         "falar das notas/da aula/do curso.",
         "8. faltou — ponto do MAPA abaixo que o roteiro não cobriu (ou só citou de passagem): escreva o trecho que falta, "
         "no lugar certo da ordem.",
         "9. fechamento — conceito novo que aparece só no fim, duas conclusões seguidas, pergunta ao público incompleta.",
         "10. chamada — mais de uma pergunta \"comenta aí\" espalhada, ou a última ficou sem a pergunta.", ""]
    if mapa.strip():
        L += ["## MAPA do vídeo (o que ele tem de cobrir)", mapa.strip()[:2000], ""]
    L += ["## Como responder — SÓ um JSON, sem texto antes ou depois",
          '{"correcoes": [{"tipo": "repeticao", "de": "trecho EXATO copiado do roteiro", "para": "o texto novo (vazio = '
          'apagar)", "porque": "1 frase"}], "resumo": "2-3 frases: o que estava errado e o que mudou"}',
          "Regras:",
          "- \"de\": COPIE do roteiro, letra por letra (1 a 3 frases inteiras, até ~600 caracteres). Sem resumir, sem "
          "corrigir nada dentro dele — senão o site não acha o trecho.",
          "- \"para\": o texto que entra no lugar, no mesmo tom e idioma, pronto pra ser narrado. Pra INSERIR conteúdo "
          "(tipo \"faltou\"), \"de\" = a última frase do parágrafo antes de onde ele entra, e \"para\" = essa mesma frase + "
          "\\n\\n + o parágrafo novo.",
          "- APAGOU ou trocou um parágrafo? Confira o parágrafo SEGUINTE: se ele começa apontando pro que saiu (\"Essa "
          "separação…\", \"Isso…\", \"Também…\", um exemplo que só tinha sido apresentado no trecho apagado), corrija ele "
          "também (outra correção) — nenhuma correção pode criar uma referência órfã nova.",
          "- Confira as DEFINIÇÕES do roteiro contra a fonte, uma por uma (ex.: o que é resposta direta, indireta, réplica) — "
          "definição que não bate com a fonte é conceito_errado, mesmo que soe bem.",
          "- Mantenha todas as marcas que estiverem no \"de\" ([I3], [M2], [CENA 2], [[INSCREVA]], [[VENDA]], tags de voz).",
          f"- No máximo {MAX_CORRECOES} correções — as mais importantes primeiro. Roteiro sem erro = \"correcoes\": [].",
          "- Exemplo novo: criado do zero, plausível e de uma área da vida que o roteiro ainda não usou.",
          "- Fato, nome, data, estudo: só o que está na fonte ou é conhecido e verdadeiro — nunca invente."]
    if alvo_palavras:
        L.append(f"- TAMANHO: o roteiro tem {n} palavras e o vídeo pede ~{alvo_palavras}. As correções NÃO podem deixar "
                 f"o roteiro abaixo de ~{int(alvo_palavras * 0.9)} palavras: o que sair por repetição volta como conteúdo "
                 "novo (o porquê, a objeção e a resposta, um exemplo de outra área, um ponto do mapa que faltou).")
    if fonte.strip():
        L += ["", "## FONTE (o que o vídeo tem de dizer — é a referência pra conferir os conceitos)", fonte.strip()[:40000]]
    L += ["", "## ROTEIRO", roteiro]
    return "\n".join(L)


def _txt(x: Any) -> str:
    return str(x or "").strip()


def ler(resposta: str) -> Dict[str, Any]:
    """{"trocas": [{"de", "para", "tipo", "porque", "motivo"}], "resumo"} — aceita variações dos nomes das chaves."""
    import json_ia
    try:
        d = json_ia.carregar(resposta)
    except ValueError as exc:
        raise ValueError(f"Não consegui ler o JSON: {exc}") from exc
    if isinstance(d, list):
        d = {"correcoes": d}
    if not isinstance(d, dict):
        raise ValueError("O JSON tem de ser um objeto com \"correcoes\".")
    lista = next((d[k] for k in ("correcoes", "correções", "trocas", "problemas", "erros", "corrections") if isinstance(d.get(k), list)), [])
    trocas = []
    for c in lista[:60]:
        if not isinstance(c, dict):
            continue
        de = _txt(c.get("de") or c.get("trecho") or c.get("original") or c.get("from"))
        para = c.get("para", c.get("correcao", c.get("novo", c.get("to"))))
        para = "" if para is None else str(para).strip()
        if not de or de == para:
            continue
        tipo = _txt(c.get("tipo") or c.get("type")).lower().replace(" ", "_")
        tipo = tipo if tipo in TIPOS else next((k for k in TIPOS if tipo.startswith(k[:5])), "outro")
        trocas.append({"de": de, "para": para, "tipo": tipo, "porque": _txt(c.get("porque") or c.get("motivo") or c.get("why"))[:300],
                       "motivo": TIPOS.get(tipo, "🧪 verificação")})
    return {"trocas": trocas, "resumo": _txt(d.get("resumo") or d.get("summary"))[:800]}


def aplicar(roteiro: str, d: Dict[str, Any]) -> Dict[str, Any]:
    import revisao_roteiro as rv
    r = rv.aplicar(roteiro, json.dumps({"trocas": d["trocas"]}, ensure_ascii=False))
    for a in r["aplicadas"]:  # o tipo e o porquê de cada troca aplicada (pra mostrar na tela)
        orig = next((t for t in d["trocas"] if t["de"][:200] == a["de"]), None)
        if orig:
            a["tipo"], a["porque"] = orig["tipo"], orig["porque"]
    return r
