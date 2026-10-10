"""
🧭 Método de roteiro — usado em TODO prompt que pede pra IA escrever ou
reescrever um roteiro (Roteiro do YouTube, 🛒 Vídeo de venda, 🕵️ Modelos de
vídeo, 🎞️ Vídeos modelados).

Baseado no processo de um roteirista de YouTube (vídeos virais, sem fórmula
mágica nem manipulação):
  1. objetivo comum entre quem assiste e o vídeo (sem isso soa falso);
  2. problema de SUPERFÍCIE + problema PROFUNDO (a luta emocional por baixo),
     plantado cedo e revelado no fim;
  3. entregar a promessa do título/thumbnail;
  4. saber pra quem escreve (avatar) e o nível de complexidade;
  5. pesquisa: o que as fontes NÃO explicaram é a oportunidade;
  6. ponto de partida e de chegada claros (uma transformação);
  7. jornada do herói adaptada (status quo → chamado → ajuda → partida →
     provas → aproximação do problema profundo → crise → recompensa →
     resultado → retorno → resolução);
  8. complexidade crescente (contexto → simples → avançado);
  9. "mostrar sem contar": plantar perguntas e deixar o espectador
     descobrir antes de responder (laços abertos com recompensa);
 10. "mas / portanto" no lugar de "e aí… e então…";
 11. ritmo: frases de tamanhos diferentes;
 12. criticar o próprio esboço antes de escrever a versão final;
 13. sem manipulação: nada de isca de raiva, promessa falsa ou cortar o que
     é útil só pra segurar retenção.
"""
from __future__ import annotations

from typing import Any, Dict, List

_BASE = [
    "OBJETIVO COMUM: descubra por que a pessoa clicou (o que ela quer levar do vídeo) e faça o objetivo do vídeo ser o mesmo. "
    "Se o vídeo quer uma coisa e o público outra, soa falso.",
    "PROBLEMA DE SUPERFÍCIE + PROBLEMA PROFUNDO: além do assunto em si (superfície), ache a questão humana/emocional por "
    "baixo dele (o problema profundo — medo, injustiça, perfeccionismo, ganância, esperança…). Plante esse problema profundo "
    "cedo, sem entregar, e revele/resolva no fim. É isso que faz o vídeo ficar na cabeça.",
    "PROMESSA: o começo confirma rápido a promessa do título/thumbnail e o vídeo ENTREGA essa promessa — nada de enrolar.",
    "PÚBLICO: escreva pra um espectador concreto (quem é, o que já sabe) e ajuste o nível de detalhe a ele.",
    "LACUNA: use o que as fontes NÃO explicam direito (a pergunta que ninguém respondeu) como o diferencial do vídeo.",
    "COMEÇO E FIM CLAROS: deixe explícito onde a história (ou o espectador) está no início e onde estará no fim — uma transformação.",
    "COMPLEXIDADE CRESCENTE: primeiro o contexto pra quem não conhece, depois o simples, e só então o avançado.",
    "MOSTRAR SEM CONTAR: em vez de entregar tudo, plante perguntas e pistas, convide o espectador a tentar adivinhar e responda "
    "depois (laços abertos que SEMPRE se fecham). Isso vira conversa e segura a atenção.",
    "\"MAS / PORTANTO\": ligue os acontecimentos com causa e conflito (\"isso aconteceu, MAS…, PORTANTO…\") em vez de "
    "\"e aí… e então…\". Fica menos previsível.",
    "RITMO: varie o tamanho das frases (curtas, médias, uma longa de vez em quando). Nunca o mesmo comprimento seguido.",
    "AUTOCRÍTICA: antes de escrever a versão final, critique o seu próprio esboço — o que falta, o que está chato, o que sobra, "
    "se a virada surpreende — e corrija. Entregue só a versão final.",
    "SEM MANIPULAÇÃO: nada de isca de raiva, promessa falsa, gancho que o vídeo não cumpre, nem cortar a parte útil só pra "
    "segurar retenção. Valor de verdade primeiro.",
]

_JORNADA = (
    "ESTRUTURA DE HISTÓRIA (jornada do herói adaptada — o \"herói\" pode ser a pessoa/empresa do tema, quem investiga, ou o próprio "
    "espectador aprendendo): status quo (como tudo era) → chamado (o fato que muda tudo: problema, ameaça, oportunidade ou "
    "curiosidade) → ajuda/mentor → partida (a jornada começa) → provas (o miolo: fatos, tentativas, erros, vitórias) → "
    "aproximação (o problema profundo aparece) → crise (o ponto mais baixo, a virada) → recompensa (o que se descobre/aprende) "
    "→ resultado → retorno → resolução (as pontas soltas se fecham). Adapte à estrutura do formato pedido — não force rótulos, "
    "o espectador não precisa perceber a estrutura.")

_VENDA = (
    "MINI-JORNADA DE VENDA: status quo (a vida com o problema) → chamado (o momento em que o problema incomoda) → o produto como "
    "ajuda/mentor → provas (benefícios mostrados, objeções respondidas) → transformação (como fica depois) → chamada pra ação. "
    "O problema profundo é o que a pessoa sente (tempo perdido, insegurança, vergonha, cansaço), não só a característica técnica.")

# Shorts (Reels/TikTok): o que segura o dedo na tela — dois criadores de Shorts com dezenas de milhões de views
_SHORTS = [
    "GANCHO COM O ESPECTADOR DENTRO: na 1ª frase, ponha quem assiste COMO PERSONAGEM da história (\"Você é a maior empresa de café "
    "do mundo e tem um problema…\", \"Imagina que você…\") e diga o PROBLEMA na hora — ele tem algo em jogo e precisa ver até o "
    "fim pra resolver. Dado chocante sozinho não segura: precisa de algo em jogo e de um motivo pra se importar.",
    "TEMA DE DOPAMINA RÁPIDA: curiosidade, \"parece burrice até alguém explicar e você pensar 'que genial'\", algo que faz quem "
    "assiste se sentir mais esperto. Evite o tom de desgraça sem saída — quem está rolando Shorts quer uma recompensa rápida.",
    "SOLUÇÃO EM PASSOS: revele a resposta peça por peça, cada frase entrega uma coisa nova e puxa a próxima — nenhuma frase morta.",
    "FINAL COM RECOMPENSA: termine com a revelação de verdade (quem era, qual foi a jogada, a solução) — nunca só numa piada ou sem "
    "conclusão. Se der, a última frase conversa com a primeira (o vídeo dá a volta e recomeça).",
    "DURAÇÃO: Short é de no MÁXIMO 60 segundos — o roteiro inteiro cabe em ~130-160 palavras faladas (menos se o vídeo pedido "
    "for mais curto). Passou disso, corte.",
    "SIMPLES: explique o fato do jeito mais simples possível (\"Você sabia que…?\" funciona quando o fato é surpreendente de verdade).",
    "FRASES CURTAS: uma ideia (e uma imagem) por frase, pra legenda curta e troca de cena a cada 1-2 s.",
    "TRANSFORMADOR: a narração explica, comenta, conecta — nunca só descreve uma cena de filme/vídeo de outro (conteúdo "
    "reutilizado é desmonetizado e toma direitos autorais).",
    "META: quem vê o 1º segundo não pode arrastar (taxa de visualização > 80%) e quem fica tem que ir até o fim (retenção > 90%). "
    "Corte tudo que não puxa pra próxima frase.",
    "COM ALMA: copie a ESTRUTURA do que viraliza, não o jeito de outro canal — o vídeo tem que ser divertido e ter a sua cara.",
]

PLANO_JSON = {
    "objetivo_comum": "o que o espectador quer + o que o vídeo quer (iguais)",
    "problema_superficie": "o assunto em si",
    "problema_profundo": "a questão humana/emocional por baixo (plantada cedo, revelada no fim)",
    "publico": "pra quem é e o que já sabe",
    "comeco_e_fim": "onde a história/o espectador está no início → onde termina",
    "jornada": ["status quo: …", "chamado: …", "provas: …", "crise: …", "resolução: …"],
    "lacos_abertos": ["pergunta plantada → onde é respondida"],
    "notas_edicao": ["ideias de imagem/música/efeito pra quem edita (opcional)"],
}


def bloco(tipo: str = "longo") -> str:
    """Texto do método pra pôr no prompt. tipo: "longo" (documentário/YouTube),
    "curto" (Shorts), "venda" (vídeo de venda), "venda_curto" (venda em Shorts/Reels),
    "reescrita" (reescrever um roteiro existente)."""
    itens: List[str] = list(_BASE)
    if tipo == "curto":
        itens = [x for x in itens if not x.startswith(("LACUNA", "COMPLEXIDADE", "PÚBLICO"))] + _SHORTS
        extra = ("FORMATO CURTO: uma mini-jornada (você no problema → a virada → a revelação) em poucas frases; o problema "
                 "profundo pode ser só sugerido; um laço aberto no começo que se fecha no fim. Em \"plano\".\"notas_edicao\" "
                 "sugira o que segura a atenção na edição: efeito sonoro + algo visual chamativo no 1º segundo, legendas de 1-3 "
                 "palavras, cena nova a cada 1-2 s, movimento o tempo todo.")
    elif tipo in ("venda", "venda_curto"):
        extra = _VENDA
        if tipo == "venda_curto":
            itens = [x for x in itens if not x.startswith(("LACUNA", "COMPLEXIDADE", "PÚBLICO"))] + _SHORTS
    else:
        extra = _JORNADA
    if tipo == "reescrita":
        extra += (" Ao REESCREVER, mantenha os fatos e a ordem das ideias que funcionam, mas reorganize pra seguir esse método "
                  "quando ajudar (sem inventar fatos).")
    return ("## 🧭 Método de roteiro (siga ao escrever)\n" + "\n".join(f"- {x}" for x in itens) + f"\n- {extra}\n"
            "- Notas de edição (imagem, música, efeito) NÃO vão no texto narrado — se tiver, ponha em \"plano\".\"notas_edicao\".")


def bloco_referencia(texto: str) -> str:
    """Transcrição de um vídeo/short que viralizou: a IA copia a ESTRUTURA (não o conteúdo)."""
    t = str(texto or "").strip()
    if not t:
        return ""
    return ("## 📐 Estrutura de referência (um vídeo que viralizou)\n"
            "Use a ESTRUTURA deste roteiro como molde — tipo de gancho, ordem das revelações, ritmo das frases, tamanho, como "
            "termina — mas com o MEU tema e os MEUS fatos. Não copie frases, nomes nem o assunto dele.\n\n" + t[:12000])


def ler_plano(d: Any) -> Dict[str, Any]:
    """O "plano" que a IA devolveu (limpo, pra mostrar na página)."""
    if not isinstance(d, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ("objetivo_comum", "problema_superficie", "problema_profundo", "publico", "comeco_e_fim"):
        if str(d.get(k) or "").strip():
            out[k] = str(d[k]).strip()[:600]
    for k in ("jornada", "lacos_abertos", "notas_edicao"):
        v = d.get(k)
        if isinstance(v, list):
            out[k] = [str(x).strip()[:300] for x in v if str(x).strip()][:20]
    return out


ROTULOS_PLANO = {
    "objetivo_comum": "🎯 Objetivo comum", "problema_superficie": "📌 Problema de superfície",
    "problema_profundo": "💔 Problema profundo", "publico": "👤 Público", "comeco_e_fim": "🔁 Começo → fim",
    "jornada": "🗺 Jornada", "lacos_abertos": "❓ Laços abertos", "notas_edicao": "🎬 Notas de edição",
}
