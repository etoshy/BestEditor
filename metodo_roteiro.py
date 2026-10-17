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

import re
from typing import Any, Dict, List, Tuple

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
    "UMA IDEIA POR FRASE (unidades de sentido): não amontoe informação numa frase só. Quando uma frase junta data + lugar + "
    "nome + cargo + resultado (\"Em 1987, aos 9 anos, em Ohio, depois de ser avaliado por dois psiquiatras que…\"), divida em "
    "frases curtas, cada uma com UM fato principal, na ordem em que o espectador precisa saber. Vale ainda mais nos trechos "
    "cheios de dados (infância, histórico, laudos/avaliações médicas, investigação, processos, números). Quem ouve não pode "
    "voltar a frase.",
    "AUTOCRÍTICA: antes de escrever a versão final, critique o seu próprio esboço — o que falta, o que está chato, o que sobra, "
    "se a virada surpreende — e corrija. Entregue só a versão final.",
    "SEM MANIPULAÇÃO: nada de isca de raiva, promessa falsa, gancho que o vídeo não cumpre, nem cortar a parte útil só pra "
    "segurar retenção. Valor de verdade primeiro.",
]

# v84_99 — o que deixava o roteiro longo, repetitivo e com "cara de IA" (crítica de um roteiro real em alemão)
REGRAS_NARRACAO = [
    "SEM ENCHIMENTO: cada fato importante é contado UMA vez, no lugar certo. Não reconte o que já foi dito — a prisão, o "
    "julgamento, as incertezas e o legado NÃO refazem o resumo do caso. Uma ideia já dita (\"a polícia ignorou os sinais\", "
    "\"as vítimas eram jovens vulneráveis\") só volta com um fato NOVO, nunca como eco.",
    "FIM DE SEÇÃO COM SUBSTÂNCIA: cada trecho termina com uma revelação, uma consequência concreta ou uma pergunta realmente "
    "necessária — nunca com suspense vazio pra preencher tempo (\"A pergunta de quem bateu à porta naquela noite continua nos "
    "acompanhando\", \"Mas isso era só o começo\").",
    "AFIRMAÇÃO DO TAMANHO DA PROVA: conclusões sobre motivos, acordos, omissões ou causas (\"Em troca, a polícia fazia vista "
    "grossa aos pequenos delitos dele\") só com a fonte ESPECÍFICA dita no texto (\"segundo os autos do processo de 1924…\", "
    "\"como o comissário X admitiu no julgamento…\"). Sem uma fonte assim, suavize (\"há indícios de que…\", \"historiadores "
    "suspeitam que…\") ou corte.",
    "SEM FÓRMULAS DE ANÁLISE: \"Aqui está a verdadeira questão\", \"É preciso ter cuidado neste ponto\", \"Uma leitura possível "
    "é\", \"É preciso se perguntar\" e equivalentes no idioma do roteiro (em alemão: „Hier liegt die eigentliche Frage“, „Man "
    "muss an dieser Stelle vorsichtig sein“, „Eine mögliche Lesart ist“, „Man muss sich fragen“) — no máximo UMA vez no "
    "vídeo inteiro. Frase-fragmento de efeito („Mit der Guillotine.“) só nas revelações de verdade, não como tique. Mostre a dúvida pelos fatos, sem "
    "anunciar que vai analisar. Varie as construções: nada de começar frases seguidas do mesmo jeito.",
    "CRONOLOGIA COERENTE: datas, idades e o início/fim de cada relação ou situação têm que bater do começo ao fim (não "
    "diga que algo começou \"a partir de 1924\" se outro trecho mostra isso em 1918). Sem data exata nas fontes, não "
    "invente uma — diga \"pelo menos desde…\" ou atribua.",
    "NÚMEROS COM NOME: o número pelo qual alguém foi condenado, o da acusação, os casos que a polícia ligou, o que o "
    "acusado alegou e as estimativas NÃO são intercambiáveis — diga sempre qual é qual, igual no vídeo inteiro.",
    "FALA, NÃO ENSAIO: escreva como um narrador conta, não como um artigo; nos momentos de tensão, frases curtas (5–12 "
    "palavras), sem orações encaixadas; frase longa só em trecho calmo de contexto. Uma voz sintética se perde em período longo.",
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
        itens += REGRAS_NARRACAO
    if tipo == "reescrita":
        extra += (" Ao REESCREVER, mantenha os FATOS, mas crie a SUA linha de storytelling (ângulo, gancho, ordem das revelações) "
                  "seguindo esse método — o original é só um guia, não um molde (sem inventar fatos).")
    return ("## 🧭 Método de roteiro (siga ao escrever)\n" + "\n".join(f"- {x}" for x in itens) + f"\n- {extra}\n"
            "- Notas de edição (imagem, música, efeito) NÃO vão no texto narrado — se tiver, ponha em \"plano\".\"notas_edicao\".")


# ------------------------------------------------------------------ títulos (Kit Iniciante YouTube · cap. 05)
# "Títulos que dão vontade de clicar": curto (até ~60 caracteres), palavra principal no começo e
# uma promessa que o vídeo cumpre. Todo título gerado pelo site segue uma destas fórmulas.
FORMULAS_TITULO = [
    ("[Tema] Explicado em [N] Minutos", "A Segunda Guerra Explicada em 12 Minutos"),
    ("O Fim de [algo famoso]", "O Fim da Blockbuster"),
    ("Por que [fato surpreendente]?", "Por que os Faraós Odiavam Moscas?"),
    ("[A] vs [B]: Quem Vence?", "Leão vs Tigre: Quem Vence?"),
    ("O que Ninguém te Conta sobre [tema]", "O que Ninguém te Conta sobre Tubarões"),
    ("A Verdade sobre [mito]", "A Verdade sobre os Gladiadores"),
    ("[N] [coisas] Mais [adjetivo] de [tema]", "7 Animais Mais Perigosos da Amazônia"),
    ("Por que Ninguém Mais [ação]", "Por que Ninguém Mais Usa Orkut"),
    ("Você Sobreviveria [situação]?", "Você Sobreviveria 24h em Pompeia?"),
    ("O Maior Erro de [pessoa/empresa]", "O Maior Erro da Nokia"),
    ("O Dia em que [evento]", "O Dia em que a Internet Parou"),
    ("[Tema] do Pior ao Melhor", "Todos os Shreks do Pior ao Melhor"),
    ("[Tema]: a História Real", "Titanic: a História Real"),
    ("O Mistério de [caso]", "O Mistério do Navio Fantasma"),
    ("Como [algo] Realmente Funciona", "Como a Bolsa Realmente Funciona"),
    ("[N] Sinais de que [situação]", "7 Sinais de que Seu Cachorro te Ama"),
    ("Eu Testei [X] por [tempo]", "Eu Testei Acordar às 5h por 30 Dias"),
    ("Isso Mudou [tema] para Sempre", "Isso Mudou os Games para Sempre"),
    ("[Coisa] que Você Usa Errado", "5 Coisas que Você Usa Errado na Cozinha"),
    ("O Lado Sombrio de [algo]", "O Lado Sombrio da Disney"),
]
TITULO_MAX = 60


def bloco_titulos(qtd: int = 5, idioma: str = "") -> str:
    """Regras + fórmulas de título pra pôr no prompt (todo título que o site pede à IA)."""
    formulas = "\n".join(f"  - {f}  (ex.: {e})" for f, e in FORMULAS_TITULO)
    return ("## 🏷 Títulos — SEMPRE nesta estrutura\n"
            f"- Cada título: curto (até ~{TITULO_MAX} caracteres), com a PALAVRA PRINCIPAL no começo e uma PROMESSA que o vídeo "
            "cumpre de verdade.\n"
            f"- Os {qtd} títulos usam fórmulas DIFERENTES desta lista (escolha as que combinam com o assunto; troque os "
            "colchetes pelo tema real"
            + (f"; escreva em {idioma}, adaptando a fórmula ao idioma" if idioma else "") + "):\n" + formulas + "\n"
            "- NUNCA minta no título: clique enganado vira saída rápida, e o YouTube para de recomendar o vídeo. Só prometa o "
            "que o roteiro entrega (números, nomes e fatos que estão no vídeo).")


def titulo_ok(t: str) -> bool:
    return 0 < len(str(t or "").strip()) <= TITULO_MAX + 10


def bloco_referencia(texto: str, modo: str = "inspirar") -> str:
    """Transcrição de um vídeo/short que viralizou: INSPIRAÇÃO de estrutura (não um molde ponto a ponto).
    v84_169: modo "modelar" = seguir a MESMA sequência de blocos do exemplo, com o meu tema e os meus fatos."""
    t = str(texto or "").strip()
    if not t:
        return ""
    if modo == "modelar":
        return ("## 📐 ROTEIRO EXEMPLO — modele a ESTRUTURA dele, com o MEU tema (o assunto do exemplo NÃO entra)\n"
                "1. Antes de escrever, mapeie (por dentro, sem pôr na resposta) o exemplo em BLOCOS: o que cada bloco FAZ (ex.: "
                "gancho com 3 perigos seguidos → frase de impacto → “no vídeo de hoje…” → por que este lugar é diferente dos "
                "outros → perigo 1 com a causa curiosa → perigo 2 … → virada → fechamento), o ritmo das frases, como cada "
                "bloco puxa o próximo e como ele termina.\n"
                "2. Escreva o MEU roteiro com a MESMA sequência de funções: cada bloco do exemplo vira um bloco equivalente do meu "
                "tema (o “perigo da natureza” do exemplo vira um perigo/curiosidade do meu tema, a apresentação vira a minha "
                "apresentação etc.). As mesmas técnicas de gancho, de transição e de final.\n"
                "3. NÃO copie frases, nomes, lugares, números nem fatos do exemplo; interjeições, palavrões e “[ __ ]” do exemplo não "
                "entram. Os fatos vêm SÓ das minhas fontes — se faltar fato pra um bloco, junte ou pule o bloco, nunca invente.\n"
                "4. O tamanho pedido (seção 📏) vale mais que o do exemplo; o título/a promessa (🧵) também manda.\n\n"
                + t[:40000])
    return ("## 📐 Referência (um vídeo que viralizou) — inspiração, não molde\n"
            "Observe o que faz este roteiro funcionar — o tipo de gancho, como ele segura a atenção, o ritmo das frases, como "
            "termina — e use essas LIÇÕES no MEU tema, com os MEUS fatos e a SUA linha de storytelling. Não siga a sequência "
            "dele ponto a ponto e não copie frases, nomes nem o assunto. O tamanho pedido (seção 📏) vale mais que o dele.\n\n"
            + t[:40000])


def bloco_guia(origem: str = "o roteiro/as anotações", tem_tamanho: bool = True) -> str:
    """✍️ O roteiro/as referências que a pessoa colou são GUIA: a IA cria a própria linha de storytelling (v84_95)."""
    return ("## ✍️ Sua própria linha de storytelling (" + origem + " é só um GUIA)\n"
            f"- {origem[0].upper() + origem[1:]} serve pra você saber o assunto, os fatos e o que eu quero destacar — NÃO é um "
            "molde pra clonar.\n"
            "- Crie a SUA forma de contar, como um roteirista profissional faria: escolha o ângulo, o gancho, por onde começar "
            "(pode abrir pelo momento mais forte e voltar no tempo), a ordem das revelações, onde ficam os laços abertos, as "
            "viradas e o final — o que contar MELHOR esta história pra este público.\n"
            "- NÃO siga ponto a ponto, NÃO repita a mesma sequência de parágrafos, NÃO reaproveite frases, aberturas, "
            "transições, metáforas nem a divisão de capítulos do guia. Lado a lado, o seu roteiro não pode parecer uma "
            "paráfrase do guia.\n"
            "- Mantenha os FATOS corretos (nada inventado) e o texto claro e fácil de entender: contexto antes do detalhe, uma "
            "ideia por frase.\n"
            + ("- O TAMANHO pedido (seção 📏) vale mais que o tamanho do guia.\n" if tem_tamanho else
               "- Mantenha mais ou menos o tamanho/duração do original.\n"))


def bloco_canal(nome: str, curto: bool = False) -> str:
    """📺 O nome do canal, dito no momento certo (v84_95)."""
    nome = " ".join(str(nome or "").split())[:80]
    if not nome:
        return ""
    if curto:
        return ("## 📺 Nome do canal: " + nome + "\n"
                f"- Diga o nome do canal UMA vez, no fim, numa frase curta e natural (ex.: “Mais casos assim aqui no {nome}.”). "
                "Nunca na 1ª frase — o gancho vem primeiro.\n"
                f"- Escreva exatamente “{nome}”.")
    return ("## 📺 Nome do canal: " + nome + "\n"
            f"- Fale o nome do canal de forma natural, como um apresentador faria: UMA vez no começo, logo DEPOIS do gancho, "
            f"quando apresenta o tema (ex.: “Hoje, aqui no {nome}, a gente vai entender…”) — nunca na 1ª frase; e UMA vez no "
            f"fechamento (ex.: “Esse foi o caso de hoje no {nome}.”). Em vídeo longo, no máximo mais uma vez numa transição do "
            "meio. No máximo 3 vezes no total.\n"
            "- Não junte o nome a pedido de like/inscrição nem cole numa marca [[INSCREVA]] (o vídeo de inscreva-se já faz isso).\n"
            f"- Escreva exatamente “{nome}”. O nome de OUTROS canais (dos vídeos/fontes de referência) não aparece no roteiro.")


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


# ------------------------------------------------------------------ 📏 tamanho do roteiro (v84_92)
# As IAs de chat encurtam roteiro longo: com "~18 min (~2700 palavras)" só no título do formato, voltava um de ~8 min.
# Agora o tamanho vira uma seção própria perto do FIM do prompt (a IA respeita mais), com o MÍNIMO de palavras e quanto
# cada parte da estrutura deve ter; ao ler a resposta o site confere e, se faltou, gera um prompt pra completar.
TOLERANCIA_TAMANHO = 0.85  # abaixo de 85% do alvo = curto demais (avisa e oferece o "completar")


def palavras_do_texto(texto: str) -> int:
    """Palavras faladas (sem marcas [I3], [CENA 2], [[INSCREVA]], tags de voz)."""
    import re
    t = re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]", " ", str(texto or ""))
    return len(t.split())


def _orcamento(partes: List[str], total: int) -> List[int]:
    """Palavras por parte: o gancho (1ª) leva ~1/3 de cota, as outras dividem o resto por igual."""
    if not partes:
        return []
    pesos = [0.35] + [1.0] * (len(partes) - 1)
    soma = sum(pesos)
    return [max(30, int(round(total * w / soma / 10.0)) * 10) for w in pesos]


def bloco_tamanho(minutos: float, palavras: int, partes: List[str] = None, reescrita: bool = False) -> str:
    """Seção "📏 TAMANHO" do prompt. `partes` = a estrutura do formato (vira o orçamento de palavras por parte)."""
    if not minutos or not palavras or minutos <= 1:
        return ""
    minimo = int(palavras * 0.95)
    L = [f"## 📏 TAMANHO DO ROTEIRO — obrigatório (é o que mais erra)",
         f"- O texto NARRADO tem que durar ~{minutos:g} minutos: NO MÍNIMO {minimo} palavras (alvo: ~{palavras}). "
         f"Isso é BEM longo (~{palavras * 6 // 1000} mil caracteres) — um roteiro de {minutos / 2:g} min é a METADE e está errado.",
         "- NÃO resuma e NÃO pule partes: desenvolva cada fato com contexto, detalhes das fontes, causas, consequências, "
         "o que as pessoas envolvidas disseram, e transições entre as partes. Nada de encher linguiça repetindo frases — "
         "aprofunde o conteúdo."]
    orc = _orcamento(list(partes or []), palavras)
    if orc:
        L.append("- Palavras por parte (aproximado):")
        L += [f"  {k}. {str(p)[:90]} → ~{n} palavras" for k, (p, n) in enumerate(zip(partes, orc), start=1)]
    if reescrita:
        L.append("- Se o vídeo original for mais curto que isso, expanda com mais explicação e contexto sobre o mesmo assunto "
                 "(sem inventar fatos). Se for mais longo, condense mantendo o essencial.")
    L.append("- Este tamanho vale mais do que o tamanho de qualquer referência ou exemplo acima.")
    L.append("- Antes de responder, estime as palavras do roteiro; se ficou abaixo do mínimo, continue escrevendo até chegar. "
             "Se precisar economizar espaço na resposta, encurte os OUTROS campos do JSON — nunca o roteiro.")
    return "\n".join(L)


def aviso_tamanho(palavras: int, alvo_palavras: int, minutos: float, ppm: int = 150) -> str:
    """"" se está ok; senão o aviso de que ficou curto."""
    if not alvo_palavras or not minutos or minutos <= 1 or palavras >= alvo_palavras * TOLERANCIA_TAMANHO:
        return ""
    return (f"O roteiro ficou CURTO: {palavras} palavras (~{palavras / max(1, ppm):.1f} min), o alvo era ~{minutos:g} min "
            f"(~{alvo_palavras} palavras). Use “📏 Prompt pra completar o tamanho”.")


TOLERANCIA_LONGO = 1.15  # v84_99: acima de 115% do alvo = longo demais (avisa e oferece a 🪄 revisão "enxugar")


def aviso_longo(palavras: int, alvo_palavras: int, minutos: float, ppm: int = 150) -> str:
    """"" se está ok; senão o aviso de que ficou LONGO (o vídeo passa do tempo pedido)."""
    if not alvo_palavras or not minutos or minutos <= 1 or palavras <= alvo_palavras * TOLERANCIA_LONGO:
        return ""
    return (f"O roteiro ficou LONGO: {palavras} palavras (~{palavras / max(1, ppm):.0f} min), o pedido era ~{minutos:g} min "
            f"(~{alvo_palavras} palavras). Use a “🪄 Revisão do roteiro inteiro” no modo ✂️ enxugar — ela corta repetições e "
            "enchimento até o tamanho certo.")


def prompt_completar(roteiro: str, palavras: int, alvo_palavras: int, minutos: float, inicios_capitulos: List[str] = None,
                     idioma: str = "", regras_extra: List[str] = None) -> str:
    """Prompt pra IA ESTICAR o roteiro que ficou curto (na mesma conversa, que já tem as fontes).
    A resposta é só {"roteiro": "..."} — o resto (títulos, descrição, cenas…) o site mantém."""
    minimo = int(alvo_palavras * 0.95)
    L = [f"O roteiro que você escreveu ficou CURTO: tem {palavras} palavras, e o vídeo precisa de ~{minutos:g} minutos de "
         f"narração = NO MÍNIMO {minimo} palavras (alvo ~{alvo_palavras}). Faltam ~{max(0, alvo_palavras - palavras)} palavras.",
         "",
         "Reescreva o roteiro COMPLETO, do começo ao fim, chegando nesse tamanho:",
         "- mantenha a história, a ordem, o tom, o gancho e o final; NÃO resuma nada do que já existe;",
         "- aprofunde cada parte com mais contexto, detalhes e fatos das MESMAS fontes que eu te passei nesta conversa "
         "(se esta for uma conversa nova, use só o que está no roteiro e não invente fatos), causas e consequências, "
         "o que as pessoas disseram, e transições melhores — sem repetir frases pra encher;",
         "- mantenha TODAS as marcas que estão no texto, no mesmo ponto da história: imagens ([I3], [M2]…), cenas ([CENA 2]), "
         "[[INSCREVA]], [[VENDA]] e tags de voz;"]
    if inicios_capitulos:
        L.append("- mantenha EXATAMENTE estas frases de começo de capítulo (o site usa pra achar os capítulos): "
                 + "; ".join(f"“{c}”" for c in inicios_capitulos if c) + ";")
    L += [f"- {r}" for r in (regras_extra or [])]
    if idioma:
        L.append(f"- escreva em {idioma}.")
    L += ["", "Antes de responder, conte as palavras; se ainda estiver abaixo do mínimo, continue.", "",
          "Responda SOMENTE com um JSON válido, assim (só este campo — o resto eu já tenho):",
          '{"roteiro": "o roteiro completo, já no tamanho certo"}', "", "## Roteiro atual", str(roteiro or "").strip()]
    return "\n".join(L)


# ------------------------------------------------------------------ 🧵 v84_169: o título é a promessa + sem frase repetida
def bloco_promessa(titulo: str, curto: bool = False) -> str:
    """🧵 O título/tema do vídeo é uma PROMESSA: o roteiro inteiro tem de entregar e amarrar tudo nela (fio condutor)."""
    titulo = " ".join(str(titulo or "").split())[:200]
    if not titulo:
        return ""
    if curto:
        return (f"## 🧵 O título é a promessa: “{titulo}”\n"
                "- A 1ª frase já põe a ideia do título; cada frase seguinte prova ou complica essa ideia; a última responde a ela.")
    return (f"## 🧵 O TÍTULO É A PROMESSA (obrigatório): “{titulo}”\n"
            "O vídeo existe pra cumprir o que esse título promete. Ele é o FIO CONDUTOR (o “roter Faden”) que liga todos os assuntos:\n"
            "- ABERTURA: depois do gancho, apresente a TESE do título com as palavras dele (ou bem perto delas) e diga por que "
            "ela faz sentido — em 2-4 frases, mostre de relance os assuntos que vêm aí como provas dessa tese (ex.: “pragas que "
            "chegam pelo ar e pela água, javalis dentro da cidade e bombas da guerra debaixo de florestas que pegam fogo”).\n"
            "- CADA BLOCO/CAPÍTULO: é uma PROVA (ou um contraponto) da tese. Termine o bloco dizendo, numa frase, o que ele "
            "acrescenta à pergunta do título.\n"
            "- TRANSIÇÕES: nunca pule de assunto a seco (“efeito mosaico”). Toda troca de assunto começa com uma frase-ponte que "
            "liga o anterior ao próximo e ao título (ex.: “Mas o perigo não vem só pelo ar…”, “Se a superfície já parece "
            "perigosa, o pior está debaixo da terra…”).\n"
            "- FECHAMENTO: volte ao título e RESPONDA a ele com honestidade (sim, não, ou “depende” — com os fatos na mão), "
            "somando as provas; termine com uma pergunta ao público ligada ao título.\n"
            "- Título exagerado (“o pior”, “o mais perigoso”): trate como pergunta a investigar — mostre os fatos que sustentam e "
            "os que relativizam; nunca invente pra confirmar.\n"
            "- Cada frase traz informação NOVA: nada de repetir a mesma frase ou ideia com outras palavras logo em seguida.")


_PALAVRAS_VAZIAS = set("""a o os as um uma uns umas de do da dos das em no na nos nas por para pra com sem que e ou mas se
como mais muito já não também ele ela eles elas isso esse essa este esta the and or of to in on at for with is are was were be
it this that der die das den dem des ein eine einen einem einer und oder aber nicht auch ist sind war waren wird werden wurde
im in am an auf aus bei mit nach von vor zu zum zur sich sie er es so dass wie noch nur schon el la los las y del al un una""".split())


def _conteudo(frase: str) -> List[str]:
    t = re.sub(r"\[[^\]]*\]", " ", frase.lower())
    return [w[:6] for w in re.findall(r"[^\W\d_]{3,}", t) if w not in _PALAVRAS_VAZIAS]  # raiz curta: Feuerwehr ≈ Feuerwehrleute


def tirar_repeticoes(texto: str, janela: int = 3, limite: float = 0.72) -> Tuple[str, List[str]]:
    """🔁 Tira a frase que repete (quase igual) uma das `janela` frases anteriores do mesmo parágrafo — o erro comum de IA
    (“X gelten als brandanfällig; deshalb sollen sie umgebaut werden. X sollen deshalb … umgebaut werden.”).
    Mantém as marcas da frase tirada ([I3], [[INSCREVA]]…) na frase que ficou. → (texto, frases tiradas)."""
    tiradas: List[str] = []
    paragrafos = re.split(r"(\n\s*\n)", str(texto or ""))
    out = []
    for par in paragrafos:
        if not par.strip() or re.fullmatch(r"\n\s*\n", par):
            out.append(par)
            continue
        frases = re.split(r"(?<=[.!?…])\s+(?=\S)", par)
        ficam: List[str] = []
        for f in frases:
            c = _conteudo(f)
            repetida = False
            if len(c) >= 5:
                cs = set(c)
                nums = set(re.findall(r"\d+", re.sub(r"\[[^\]]*\]", " ", f)))
                for ant in ficam[-janela:]:
                    ca = set(_conteudo(ant))
                    nums_a = set(re.findall(r"\d+", re.sub(r"\[[^\]]*\]", " ", ant)))
                    if nums != nums_a:  # números diferentes (1937 × 1970): é outra informação, não repetição
                        continue
                    if len(ca) >= 5 and len(cs & ca) / min(len(cs), len(ca)) >= limite:
                        repetida = True
                        break
            if repetida:
                marcas = re.findall(r"\[\[?[^\]]+\]\]?", f)
                if marcas and ficam:
                    ficam[-1] = ficam[-1].rstrip() + " " + " ".join(m for m in marcas if m not in ficam[-1])
                tiradas.append(f.strip())
            else:
                ficam.append(f)
        out.append(" ".join(ficam))
    return "".join(out), tiradas
