"""
🕵️ Modelos de vídeo — começa pelo TRUE CRIME.

A pessoa dá um TEMA (o caso), um roteiro opcional e junta materiais:
  - fontes: links de matérias de QUALQUER site. O sistema salva título,
    linha fina, autor, data, subtítulos e o texto inteiro (por seção), e
    baixa TODAS as imagens da matéria com a legenda/alt e a OG da página;
  - fotos, vídeos e textos do PC (dizendo o que é cada um) ou de links (OG).
Tudo vira um prompt no FORMATO do modelo (ex.: caso completo, mistério não
resolvido, Shorts). A IA devolve um JSON com títulos, ideias, descrição do
caso, capítulos, o roteiro completo (marcas [I3] onde cada imagem entra) e
tags. Depois: Gerar voz (os capítulos ganham o tempo real do áudio) e Novo
vídeo escolhendo o projeto — o editor recebe as imagens (provider
"material", query = ID) e põe nos momentos certos.

Projetos em <base>/dossies/<id>/projeto.json, arquivos em .../midias/.
"""
from __future__ import annotations

import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import vendas as _vd  # baixar páginas/arquivos, OG

PASTA = "dossies"
MAX_IMAGENS_POR_FONTE = 40
MAX_TEXTO_POR_FONTE = 40000
MAX_TEXTO_ARQUIVO = 150000  # livros/PDFs: bem mais que uma matéria (o site avisa se o prompt ficar grande)
EXT_ARQUIVO_FONTE = (".txt", ".md", ".pdf", ".epub", ".docx", ".srt", ".vtt", ".html", ".htm", ".rtf")

MODELOS: Dict[str, Dict[str, Any]] = {
    "true_crime": {
        "nome": "🕵️ True Crime",
        "descricao": "Casos criminais reais contados como documentário: fatos, linha do tempo, investigação, julgamento. "
                     "No editor, combina com a direção “True crime investigativo (documentário de caso)”.",
        "direcao_sugerida": "sys_true_crime",  # 🎬 v84_171
        "afirmacoes": True,  # v84_95: lista de afirmações importantes com tipo (fato/alegação/interpretação) e fonte
        "formatos": {
            "caso_completo": {
                "nome": "📁 Caso completo (cronológico)", "minutos": 18,
                "estrutura": [
                    "GANCHO (0-30 s): o momento mais intrigante do caso, sem entregar o desfecho; termine com uma pergunta",
                    "Apresentação da(s) vítima(s) como pessoas — quem eram, família, sonhos (com respeito)",
                    "Contexto: lugar, época, o dia em que tudo aconteceu",
                    "O crime / o desaparecimento: os fatos, na ordem, sem detalhe gráfico",
                    "A investigação: pistas, suspeitos, reviravoltas, erros e acertos da polícia",
                    "Prisão, julgamento e sentença (ou onde o caso parou)",
                    "Desdobramentos: o que aconteceu depois, como está hoje",
                    "Fechamento: reflexão respeitosa + pergunta pro público comentar",
                ],
            },
            "misterio": {
                "nome": "❓ Mistério não resolvido", "minutos": 15,
                "estrutura": [
                    "GANCHO: o detalhe mais estranho do caso",
                    "Quem era a pessoa / o que se sabe com certeza",
                    "Linha do tempo das últimas horas / dos fatos conhecidos",
                    "As pistas e as perguntas sem resposta",
                    "As teorias (cada uma com o que a sustenta e o que a enfraquece) — SEM acusar ninguém",
                    "Onde o caso está hoje",
                    "Fechamento: o que você acha? (pergunta pro público)",
                ],
            },
            "curto": {
                "nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1,
                "estrutura": [
                    "Gancho na 1ª frase (o fato mais chocante, sem detalhe gráfico)",
                    "3-5 fatos-chave em frases curtas",
                    "Reviravolta ou desfecho",
                    "Chamada: 'o caso completo está no canal' ou uma pergunta",
                ],
            },
            "lista": {
                "nome": "🔢 Lista de casos (top N)", "minutos": 15,
                "estrutura": [
                    "Gancho: o que une os casos da lista",
                    "Cada caso: quem, o que aconteceu, a reviravolta, como terminou (2-4 min cada)",
                    "Do menos ao mais impactante",
                    "Fechamento: qual caso mais te marcou?",
                ],
            },
        },
        "regras": [
            "Só FATOS que estão nas fontes abaixo. Não invente nomes, datas, falas, provas, números nem cenas. Se as fontes "
            "discordam, diga que discordam. O que for suposição, deixe claro que é suposição.",
            "Presunção de inocência: quem não foi condenado é 'suspeito', 'acusado', 'investigado'. Nunca afirme culpa sem condenação.",
            "Respeito às vítimas e às famílias: sem sensacionalismo, sem detalhe gráfico de violência, sem glamourizar o criminoso.",
            "Linguagem amigável à monetização do YouTube: evite descrições explícitas; prefira 'tirou a vida', 'foi encontrada sem vida', "
            "'violência', em vez de detalhes crus.",
            "Narração de documentário: frases claras, ritmo de suspense, ganchos no fim de cada capítulo pra segurar até o próximo.",
            "Nomes de menores de idade envolvidos: não cite (diga 'uma criança de 9 anos', por exemplo).",
            # v84_95: fato × alegação × interpretação, com a fonte de cada afirmação importante
            "FATO, ALEGAÇÃO E INTERPRETAÇÃO — deixe SEMPRE claro, na própria narração, de qual dos três se trata: "
            "(1) FATO DOCUMENTADO = está em documento/registro (autos do processo, laudo, boletim, sentença, registro oficial, "
            "reportagem que apurou) — diga de onde vem (\"segundo os autos do processo\", \"o laudo do Instituto Médico Legal "
            "registrou\", \"de acordo com a reportagem do G1\"); (2) ALEGAÇÃO = o que alguém afirmou e não foi comprovado "
            "(acusação, defesa, testemunha, familiar, o próprio suspeito) — atribua sempre (\"a promotoria sustentou que\", "
            "\"ele alegou que\", \"uma vizinha contou à polícia que\") e nunca narre como fato; (3) INTERPRETAÇÃO DO NARRADOR "
            "= leitura, hipótese ou opinião — marque como tal (\"uma leitura possível é\", \"tudo indica que\", \"é difícil "
            "não pensar que\"). Datas, causa da morte, diagnósticos/laudos, provas, acusações, confissões e sentenças são "
            "afirmações IMPORTANTES: cada uma precisa de fonte (dita no texto quando couber e listada em \"afirmacoes\").",
            "UNIDADES DE SENTIDO: frases que acumulam informação histórica (datas, idades, lugares, nomes, instituições, "
            "diagnósticos, resultados) viram VÁRIAS frases curtas, uma informação principal em cada, na ordem em que o "
            "espectador precisa entender. Isso vale principalmente nos trechos sobre a INFÂNCIA e o histórico familiar, as "
            "AVALIAÇÕES MÉDICAS/PSIQUIÁTRICAS e laudos, e a INVESTIGAÇÃO POLICIAL (prazos, depoimentos, perícias, prisões). "
            "Ex.: em vez de \"Em 1998, aos 12 anos, depois de ser avaliado por dois psiquiatras do hospital estadual, que o "
            "diagnosticaram com transtorno de conduta, ele foi transferido para um abrigo em Ohio\", escreva: \"Era 1998. Ele "
            "tinha 12 anos. Dois psiquiatras do hospital estadual o avaliaram. O diagnóstico, segundo o prontuário citado pelo "
            "jornal: transtorno de conduta. Pouco depois, ele foi transferido para um abrigo em Ohio.\"",
        ],
    },
    "historia": {
        "nome": "📜 História",
        "descricao": "Fatos e mistérios históricos contados como documentário — guerras, impérios, eventos que mudaram o mundo.",
        "formatos": {
            "documentario": {"nome": "🎞 Documentário (cronológico)", "minutos": 18, "estrutura": [
                "GANCHO: o momento mais dramático ou surpreendente da história, sem entregar o fim",
                "Contexto: época, lugar, como era a vida e o que estava em jogo",
                "As pessoas centrais (quem eram, o que queriam)",
                "Os acontecimentos em ordem, com as viradas principais",
                "O clímax / o ponto sem volta",
                "Consequências: o que mudou depois e o que ficou até hoje",
                "Fechamento: a lição ou a pergunta que fica"]},
            "verdade": {"nome": "🔍 O que realmente aconteceu (mito × fato)", "minutos": 14, "estrutura": [
                "GANCHO: a versão que todo mundo conhece",
                "De onde veio essa versão (filme, livro, boato)",
                "O que as fontes dizem de verdade, ponto a ponto",
                "O que ainda é debatido pelos historiadores",
                "Fechamento: por que o mito pegou"]},
            "curto": {"nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1, "estrutura": [
                "Fato surpreendente na 1ª frase", "Contexto em 2-3 frases", "A virada", "Pergunta ou 'história completa no canal'"]},
            "lista": {"nome": "🔢 Lista (top N fatos/eventos)", "minutos": 12, "estrutura": [
                "Gancho: o que une os itens", "Cada item: o fato, o contexto curto e por que importa", "Do menos ao mais impressionante",
                "Fechamento: qual te surpreendeu mais?"]},
        },
        "regras": [
            "Só fatos que estão nas fontes; datas, nomes e números exatos como nas fontes. Onde os historiadores discordam, diga.",
            "Diferencie fato, interpretação e lenda ('segundo a tradição', 'há quem diga').",
            "Sem anacronismo: explique os valores da época sem justificar violências.",
            "Narração de documentário: imagens mentais fortes, frases claras, ganchos no fim de cada capítulo.",
        ],
    },
    "biografia": {
        "nome": "👤 Biografias",
        "descricao": "A vida de uma pessoa famosa ou histórica: origem, ascensão, crises, legado.",
        "formatos": {
            "completa": {"nome": "📖 Biografia completa", "minutos": 16, "estrutura": [
                "GANCHO: o momento-chave da vida dela (o auge ou a queda)",
                "Infância e origem (família, onde cresceu, o que a marcou)",
                "O começo da carreira / da jornada",
                "A ascensão: as conquistas, com números e datas das fontes",
                "Crises, polêmicas e viradas (com o que é fato e o que é acusação)",
                "Hoje / o fim da vida e o legado",
                "Fechamento: o que essa história ensina"]},
            "ascensao_queda": {"nome": "📉 Ascensão e queda", "minutos": 14, "estrutura": [
                "GANCHO: o auge e a queda lado a lado", "Como chegou ao topo", "Os sinais do problema", "A queda",
                "Onde está hoje", "Fechamento: o que deu errado"]},
            "o_que_aconteceu": {"nome": "❓ O que aconteceu com…", "minutos": 10, "estrutura": [
                "GANCHO: quem era e por que sumiu dos holofotes", "O auge", "O que fez a pessoa sumir", "A vida hoje", "Fechamento"]},
            "curto": {"nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1, "estrutura": [
                "Fato chocante ou inspirador na 1ª frase", "3-4 marcos da vida", "Onde está hoje", "Pergunta"]},
        },
        "regras": [
            "Só fatos das fontes. Fofoca, boato e 'dizem que' NÃO entram como fato — se citar, diga que é boato não confirmado.",
            "Acusações sem condenação são acusações. Nada de diagnóstico de saúde ou de vida íntima que as fontes não confirmem.",
            "Respeito: sem deboche da aparência, da família ou de tragédias pessoais.",
            "Pessoa viva: tom equilibrado, mostrando mais de um lado das polêmicas.",
        ],
    },
    "negocios": {
        "nome": "💼 Negócios e marcas",
        "descricao": "Como empresas e marcas cresceram, quebraram ou mudaram o mercado.",
        "formatos": {
            "historia_empresa": {"nome": "🏢 A história da empresa", "minutos": 15, "estrutura": [
                "GANCHO: o número ou a virada mais impressionante (faturamento, falência, aposta maluca)",
                "Os fundadores e o problema que queriam resolver", "Os primeiros anos e o produto que deu certo",
                "O crescimento: estratégia, números, concorrentes", "Crises e viradas", "Onde a empresa está hoje",
                "Fechamento: a lição de negócio"]},
            "ascensao_queda": {"nome": "📉 Ascensão e queda", "minutos": 14, "estrutura": [
                "GANCHO: o valor no auge × hoje", "Como dominou o mercado", "Os erros (decisões, concorrência, mudanças)",
                "A queda", "O que sobrou / o que fazem hoje", "Fechamento: o que outras empresas aprenderam"]},
            "estrategia": {"nome": "🧠 Estratégia explicada", "minutos": 10, "estrutura": [
                "GANCHO: a jogada que ninguém entende", "Como o modelo de negócio funciona de verdade", "Os números por trás",
                "Por que funciona (e os riscos)", "Fechamento: o que dá pra aplicar"]},
            "curto": {"nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1, "estrutura": [
                "Número ou fato chocante", "A história em 3 passos", "A lição", "Pergunta"]},
        },
        "regras": [
            "Números (valor de mercado, faturamento, datas) exatamente como nas fontes, dizendo o ano de cada número.",
            "Nada de conselho de investimento ('compre ações de…'). Opinião é opinião; fato é fato.",
            "Acusações contra empresas e executivos: só o que está nas fontes, dizendo o estado do processo.",
            "Explique termos de negócio em linguagem simples.",
        ],
    },
    "desastres": {
        "nome": "🌋 Desastres e tragédias",
        "descricao": "Acidentes aéreos, de engenharia e desastres naturais: o que aconteceu, o que deu errado e o que mudou.",
        "formatos": {
            "reconstrucao": {"nome": "🛠 Reconstrução (o que deu errado)", "minutos": 16, "estrutura": [
                "GANCHO: o último momento normal antes do desastre (sem detalhe gráfico)",
                "Contexto: o lugar, a máquina/estrutura, as pessoas envolvidas",
                "A linha do tempo, minuto a minuto quando as fontes permitem",
                "A investigação: as causas técnicas e humanas (relatórios oficiais)",
                "As vítimas e sobreviventes (com respeito)",
                "O que mudou depois: leis, normas, engenharia",
                "Fechamento: a lição que salva vidas hoje"]},
            "natural": {"nome": "🌪 Desastre natural", "minutos": 14, "estrutura": [
                "GANCHO", "Como o fenômeno funciona (explicação simples)", "Os sinais antes", "O dia do desastre",
                "Resposta e resgate", "Consequências e prevenção hoje"]},
            "curto": {"nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1, "estrutura": [
                "O fato em 1 frase", "A causa", "O que mudou depois", "Pergunta"]},
        },
        "regras": [
            "Base nos relatórios oficiais e nas fontes; causa 'provável' é provável. Não culpe pessoas antes da conclusão oficial.",
            "Respeito às vítimas: sem sensacionalismo, sem detalhe gráfico de ferimentos, sem 'entretenimento' com a dor.",
            "Linguagem amigável à monetização do YouTube.",
            "Explique a parte técnica de forma que um leigo entenda.",
        ],
    },
    "misterios": {
        "nome": "👽 Mistérios e inexplicáveis",
        "descricao": "OVNIs, lugares assombrados, enigmas e fenômenos estranhos — com investigação honesta.",
        "formatos": {
            "investigacao": {"nome": "🔦 Investigação de um mistério", "minutos": 14, "estrutura": [
                "GANCHO: o relato mais arrepiante", "O caso: quando, onde, quem viu",
                "As evidências (fotos, documentos, testemunhos) — o que cada uma prova e o que não prova",
                "As explicações: das sobrenaturais às científicas, com o peso de cada uma",
                "O que se sabe hoje", "Fechamento: e você, acredita?"]},
            "lista": {"nome": "🔢 Lista de mistérios", "minutos": 12, "estrutura": [
                "Gancho", "Cada mistério: o relato, a evidência, a melhor explicação conhecida", "Do mais leve ao mais estranho",
                "Fechamento: qual é o mais difícil de explicar?"]},
            "curto": {"nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1, "estrutura": [
                "Relato estranho na 1ª frase", "O detalhe que ninguém explica", "A explicação mais provável (ou falta dela)", "Pergunta"]},
        },
        "regras": [
            "Clima de mistério, mas honesto: nunca apresente boato ou relato como prova; diga o que foi verificado e o que não.",
            "Sempre mostre a explicação científica/cética mais aceita quando existir.",
            "Nada de inventar testemunhas, documentos ou datas. Nada que incentive alguém a se arriscar (invadir lugares, etc.).",
        ],
    },
    # 🕳 tirado da análise de um vídeo do canal Mistere (compilado de 5 casos em 30 min: teaser de 10 s,
    # cada caso um bloco seco de 4-10 min, narração rápida ~175 palavras/min, números e datas o tempo todo)
    "rabbit_holes": {
        "nome": "🕳 Rabbit holes bizarros",
        "descricao": "Casos bizarros, arquivos secretos e histórias sombrias pouco conhecidas, contados sem enrolação "
                     "(estilo Mistere: compilado, caso de arquivo oficial ou “tutorial” irônico). No editor, combina com a "
                     "direção “Rabbit hole sombrio (estilo Mistere)”.",
        "palavras_por_minuto": 170,
        "direcao_sugerida": "sys_mistere",
        "formatos": {
            "compilado": {
                "nome": "🕳 Compilado de rabbit holes (vários casos)", "minutos": 25,
                "estrutura": [
                    "TEASER (0-10 s): uma pergunta direta tipo “Tu sabia que…” com o fato mais chocante de um dos casos "
                    "(de preferência um que vem mais pra frente), com número e data; termine numa frase cortada que deixa "
                    "curiosidade. Nada de “olá”, nada de apresentar o canal",
                    "CADA CASO É UM BLOCO INDEPENDENTE (4-10 min), na ordem: título do caso numa linha própria (vira capítulo e "
                    "cartela na tela) → 1ª frase já diz O QUE é a coisa ou QUEM é a pessoa → contexto rápido (época, lugar, "
                    "por que isso importa) → os fatos em ordem cronológica, com datas, números e nomes de lugar exatos → o "
                    "momento mais pesado ou mais bizarro → um trecho de reportagem/documento/declaração lido em voz alta "
                    "(“abre aspas … fecha aspas”) quando as fontes tiverem → o que aconteceu depois e como está hoje → UMA "
                    "frase seca ou irônica fechando o caso",
                    "Entre um caso e outro NÃO existe ponte (“agora vamos para o próximo”): o próximo caso começa direto no "
                    "título dele",
                    "Ordem dos casos: abre com um caso forte e curto, alterna pesado e bizarro-curioso, e deixa o caso mais "
                    "longo e mais tenso por último",
                    "FIM: sem resumo — logo depois da frase final do último caso, uma chamada curtíssima (curtir/inscrever)",
                ],
            },
            "caso_unico": {
                "nome": "🔎 Um rabbit hole (caso único)", "minutos": 10,
                "estrutura": [
                    "TEASER (0-10 s): “Tu sabia que…” + o fato mais estranho do caso, com número/data, sem entregar o fim",
                    "Título do caso numa linha própria",
                    "O que é / quem é, em uma frase; depois o contexto (época, lugar)",
                    "Os fatos em ordem cronológica, com datas, números e lugares exatos",
                    "Reviravolta ou o momento mais bizarro",
                    "Trecho de reportagem/documento lido em voz alta (“abre aspas … fecha aspas”), se as fontes tiverem",
                    "O que se confirmou e o que é só relato; como está hoje",
                    "Frase seca/irônica final + chamada curtíssima",
                ],
            },
            # v84_62: "A CIA encontrou um fantasma no Brasil" (33 min) — caso único a partir de arquivo oficial
            "arquivo_oficial": {
                "nome": "📂 Caso de arquivo oficial (documento desclassificado)", "minutos": 30,
                "estrutura": [
                    "ABERTURA FRIA (0-50 s): de onde vem o documento (lei de acesso, arquivo, projeto secreto) e por que ele "
                    "existe; termine apontando pro caso (“e uma dessas pastas é sobre…”). Depois, o título do caso numa linha própria",
                    "Chamada curtíssima (curtir/inscrever) logo depois do título — 1 frase",
                    "O que é o fenômeno/assunto, explicado do zero e com uma piada leve no máximo",
                    "“Agora vamos conhecer as pessoas dessa história”: cada personagem em 1-2 frases (nome, idade, profissão, "
                    "relação com os outros) — os nomes viram texto grande na tela",
                    "O caso em PARTES numeradas (Parte 1, Parte 2…), cada uma com data de início e fim, os fatos em ordem e "
                    "o depoimento das testemunhas lido “nas palavras dele” (entre aspas, como está na fonte)",
                    "Um recado “guarda isso, vai ser importante” antes do detalhe que volta nas explicações",
                    "Resumo de 2 frases (“esse foi o resumo bem resumido…”) e onde ler o documento completo",
                    "AS EXPLICAÇÕES: 3 (a dos envolvidos, uma alternativa, a do investigador/ciência), cada uma com o que a "
                    "sustenta e o que a enfraquece; depois a sua opinião em 1-2 frases, com humor seco",
                    "FIM: chamada (curtir, inscrever, virar membro) e despedida curta",
                ],
            },
            # v84_62: "Tutorial de como deixar alguém esquizofrênico" (34 min) — história contada como manual irônico
            "tutorial_ironico": {
                "nome": "🎓 “Tutorial” irônico (história real contada como manual)", "minutos": 30,
                "estrutura": [
                    "ABERTURA: “Parabéns, tu foi um dos selecionados do algoritmo pra esse tutorial…” — apresenta o “tutorial” "
                    "com cara de aula séria e agradece “aos financiadores dessa pesquisa”",
                    "“Antes do tutorial, conheça os criadores desse método”: o contexto histórico (país, época, instituição) com "
                    "datas e números",
                    "O nome técnico do método, de onde vem a palavra e como era definido nos documentos oficiais",
                    "LIÇÕES numeradas (algarismos romanos: I, II, III…), cada uma um aspecto do método REAL como os "
                    "documentos descrevem (objetivo, quem fazia, fases), com citação do documento",
                    "Depois de cada lição, um exemplo de vítima real (nome, o que fizeram com ela, a fonte) e um exemplo "
                    "hipotético do cotidiano narrado em 2ª pessoa (“imagina tu chegar em casa e…”) pra ficar concreto",
                    "O que aconteceu com o programa/instituição depois e quantas vítimas se conhecem",
                    "FIM irônico: “espero que tenham gostado do tutorial e usem com sabedoria… vejo vocês no próximo tutorial”",
                ],
            },
            "curto": {
                "nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1,
                "estrutura": [
                    "“Tu sabia que…” + o fato mais bizarro, com número",
                    "3-4 fatos em frases curtíssimas, em ordem",
                    "O detalhe que ninguém espera",
                    "Frase seca final",
                ],
            },
        },
        "regras": [
            "Só FATOS que estão nas fontes. Não invente nomes, datas, números, falas nem documentos. O que é relato, boato ou "
            "nunca foi confirmado tem que ser dito assim (“segundo relatos”, “isso nunca foi confirmado”).",
            "Tom de quem está contando um caso pra um amigo: 2ª pessoa informal (“tu sabia”, “imagina”), frases curtas e "
            "diretas, ritmo rápido. Ironia só em uma frase de vez em quando — NUNCA às custas das vítimas.",
            "Escreva números, anos, medidas e quantidades em algarismos (2006, 27 pessoas, 2,7 metros, 340 quilos): eles viram "
            "texto gigante na tela. Diga o nome dos lugares (cidade, região, país) — também vira texto na tela.",
            "Palavras-chave de impacto (ex.: CONSERVADOR, PENA, PROIBIDO) podem aparecer isoladas numa frase curta, pra virar "
            "cartela em máquina de escrever.",
            "Temas pesados (mortes, violência, crimes): conte o que aconteceu sem detalhe gráfico, com linguagem amigável à "
            "monetização (“tirou a vida”, “foi morto”, “os corpos foram encontrados”).",
            "Sem nome de canal, bordões ou vinhetas de outros criadores; sem “como eu disse no outro vídeo”.",
            "Vídeo longo: divida em partes/lições com título curto numa linha própria (viram cartela de capítulo entre "
            "barras de cor) e diga as datas de cada parte.",
            "Formato “tutorial”: a ironia é só a moldura. Conte o que os documentos dizem que FOI feito, no passado, com as "
            "vítimas e as consequências; nunca escreva um passo a passo aplicável hoje pra prejudicar, vigiar ou enganar "
            "alguém, e deixe claro que era crime/abuso.",
        ],
    },
    # 🕸 v84_66: tirado de 3 vídeos do canal Dallas ("BONES", "CAPPERS", "EXPONDO a líder de um culto"): 12–16 min,
    # narração ~170 palavras/min, abre com um caso real e chocante, explica a comunidade/o golpe e escala em NÍVEIS.
    "exposicao_internet": {
        "nome": "🕸 Exposição da internet (comunidades, golpes e cultos)",
        "descricao": "Expõe um lado sombrio da internet — uma comunidade, um mercado, um golpe ou uma pessoa que manipulava "
                     "outras — com casos reais, em tom de alerta (estilo Dallas). No editor, combina com a direção "
                     "“Exposição da internet (estilo Dallas)”.",
        "palavras_por_minuto": 170,
        "direcao_sugerida": "sys_dallas",
        "formatos": {
            "niveis": {
                "nome": "🧊 Comunidade/mercado em NÍVEIS (do menos ao mais grave)", "minutos": 13,
                "estrutura": [
                    "ABERTURA (0-30 s): uma frase que diz o que existe AGORA na internet e a promessa (“e eu vou te mostrar "
                    "não só como funciona, mas como isso pode escalar…”); diga que o assunto está dividido em níveis",
                    "Caso de entrada: um caso real e recente, com data, lugar e o que a polícia/jornal descobriu — termine com "
                    "“Mas quer saber de algo ainda mais chocante?”",
                    "O que é essa comunidade/mercado: como se chamam, onde se reúnem (sites, redes, apps), o vocabulário "
                    "próprio deles explicado termo a termo, e como o dinheiro (ou a “vitória”) circula",
                    "NÍVEL 1, NÍVEL 2, NÍVEL 3 — cada nível numa linha própria com um nome curto (vira cartela vermelha): "
                    "casos reais com nome público, data e fonte, cada nível mais grave que o anterior",
                    "Viradas entre os blocos com perguntas curtas (“Mas sabe qual é a pior parte?”, “Só que agora vem a pior "
                    "parte.”, “Ou…”) numa linha própria — viram cartela de terminal no preto",
                    "Consequências: prisões, julgamentos, leis que mudaram — e o que continua acontecendo hoje",
                    "FECHAMENTO: o alerta pro público (como reconhecer e se proteger, onde denunciar) e uma frase final seca",
                ],
            },
            "expondo_pessoa": {
                "nome": "🎭 Expondo uma pessoa (líder de culto, golpista, manipulador)", "minutos": 15,
                "estrutura": [
                    "ABERTURA: um momento real e documentado (vídeo, evento, post) que parecia normal e esconde algo — "
                    "“o que eles não sabiam é que…” — e quem essa pessoa realmente era",
                    "O contexto: a comunidade/fandom/plataforma onde tudo aconteceu, explicado pra quem nunca ouviu falar",
                    "Como ela se aproximou das vítimas (sem nome de vítima que não é pública: “um usuário que vou chamar de X”)",
                    "A escalada: as regras, as histórias inventadas, o controle, o dinheiro — em ordem, com datas e com trechos "
                    "de mensagens/posts/e-mails lidos em voz alta (entre aspas)",
                    "O ponto de virada: quem saiu, quem denunciou, o que veio a público",
                    "Onde essa pessoa está hoje e o que aconteceu com as vítimas",
                    "FECHAMENTO: o padrão de manipulação pra o público reconhecer e uma frase final",
                ],
            },
            "curto": {
                "nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1,
                "estrutura": [
                    "O fato mais chocante na 1ª frase, com data",
                    "O que é a comunidade/o golpe em 2 frases",
                    "O detalhe que ninguém imagina",
                    "Alerta curto + “o vídeo completo está no canal”",
                ],
            },
        },
        "regras": [
            "Só FATOS que estão nas fontes, com data e fonte (polícia, tribunal, jornal). Acusado não é culpado: diga "
            "“foi acusado”, “responde pelo crime”, “foi condenado” conforme a fonte.",
            "Fale direto com quem assiste (“você”, “eu vou te mostrar”), frases curtas, ritmo rápido, perguntas de virada numa "
            "linha própria. A frase-chave de cada trecho deve caber em até 8 palavras — ela vira a tarja na tela.",
            "PROTEÇÃO: nunca dê nome, foto ou detalhe que identifique vítima menor de idade ou vítima não pública; nunca "
            "explique COMO cometer o crime ou o golpe (sem passo a passo, sem onde comprar/achar, sem nome de site ativo "
            "que facilite) — explique o que aconteceu e como se proteger.",
            "Monetização: sem detalhe gráfico; temas como abuso, suicídio e violência sexual com palavras neutras "
            "(“tirou a própria vida”, “material de abuso”, “crime sexual”). As palavras sensíveis podem aparecer na TELA com "
            "símbolos (ex.: S#XUAL), mas a narração continua natural e respeitosa.",
            "Rostos de vítimas, menores e conteúdo impróprio: marque [CENSURAR] na frase — no editor vira 🙈 censura (pixel).",
        ],
    },
    "ciencia": {
        "nome": "🔬 Ciência e curiosidades",
        "descricao": "Explicações de 'por que…', 'como funciona', 'e se…?' — ciência, corpo humano, espaço, tecnologia.",
        "formatos": {
            "explicacao": {"nome": "💡 Explicação (por que / como funciona)", "minutos": 10, "estrutura": [
                "GANCHO: a pergunta curiosa ou o fato que parece impossível", "A resposta curta",
                "A explicação passo a passo, com analogias do dia a dia", "Um detalhe surpreendente a mais",
                "Onde isso aparece na vida real", "Fechamento: a próxima pergunta"]},
            "e_se": {"nome": "🤔 E se…? (cenário hipotético)", "minutos": 10, "estrutura": [
                "GANCHO: a pergunta 'e se…'", "O que a ciência diz que aconteceria primeiro", "Em minutos, dias, anos",
                "O limite do que sabemos", "Fechamento"]},
            "lista": {"nome": "🔢 Lista de curiosidades", "minutos": 10, "estrutura": [
                "Gancho", "Cada curiosidade: o fato + a explicação em 2-3 frases", "Fechamento: qual você não sabia?"]},
            "curto": {"nome": "⚡ Shorts / Reels (até 60 s)", "minutos": 1, "estrutura": [
                "Pergunta ou fato surpreendente", "A explicação simples", "O detalhe extra", "Pergunta"]},
        },
        "regras": [
            "Só ciência que está nas fontes e é consenso; o que é hipótese, diga que é hipótese.",
            "Nada de conselho médico ou de saúde como orientação; números com a unidade e a fonte.",
            "Analogias simples, sem errar a ciência pra simplificar.",
        ],
    },
}

TIPOS_MIDIA = {"foto": "🖼 Foto", "video": "🎥 Vídeo", "texto": "📝 Texto", "link": "🔗 Link/página"}

CONFIG_PADRAO: Dict[str, Any] = {"modelo": "true_crime", "formato": "caso_completo", "idioma": "pt", "minutos": 18,
                                 "tom": "", "extra": "", "formato_video": "16:9",
                                 # 🙅 tirar experiências pessoais / citações a outros vídeos das fontes
                                 "sem_experiencias": True,
                                 # 📣 marcas [[INSCREVA]] / [[VENDA]] nos pontos mais oportunos (viram as pausas do Gerar voz)
                                 "marcar_chamadas": True,
                                 # 🛒 a IA sugere um produto adequado ao tema (aparece separado)
                                 "sugerir_produto": False,
                                 # 📐 transcrição de um vídeo que viralizou: a IA copia a estrutura
                                 "referencia": "",
                                 # 📐 v84_169: "inspirar" (aprende o gancho/ritmo) ou "modelar" (segue a mesma sequência de blocos)
                                 "referencia_modo": "inspirar",
                                 # 📺 nome do canal deste projeto ("" = o das Configurações; "-" = não falar)
                                 "nome_canal": "",
                                 # ✍️ roteiro escrito capítulo por capítulo: "auto" (a partir de ~8 min), "sim", "nao"
                                 "modo_partes": "auto"}

REGRA_SEM_PESSOAL = (
    "CONTEÚDO DAS FONTES: muitas fontes são textos ou transcrições de OUTROS criadores. NÃO traga pro roteiro as experiências "
    "e histórias pessoais deles (\"quando eu era criança\", \"aconteceu comigo\", \"minha mãe\", \"no meu trabalho\"), "
    "citações a vídeos e conteúdos anteriores (\"como falei no vídeo passado\", \"no meu canal\", \"parte 2\", \"link aqui em "
    "cima\"), menções a inscritos, lives, patrocinadores ou ao canal deles, nem detalhes muito pessoais/íntimos de alguém que "
    "não são necessários pra contar a história. Use só os FATOS; se uma ideia importa, reescreva de forma neutra e geral.")
REGRA_PRODUTO = (
    "PRODUTO SUGERIDO: sugira UM produto real que combine de verdade com o tema e com o público deste vídeo (ex.: um livro sobre "
    "o caso/assunto, um documentário, um item útil ligado ao tema — nunca algo de mau gosto em relação às vítimas). Ele "
    "aparece SEPARADO, em \"produto_sugerido\" — NÃO fale dele no roteiro (a chamada de venda é um vídeo à parte, que entra "
    "na marca [[VENDA]]).")


class DossieError(Exception):
    pass


# ------------------------------------------------------------------ projetos
def _pasta(base: str, pid: str = "") -> str:
    return os.path.join(base, PASTA, pid) if pid else os.path.join(base, PASTA)


def pasta_midias(base: str, pid: str) -> str:
    return os.path.join(_pasta(base, pid), "midias")


def _arquivo(base: str, pid: str) -> str:
    return os.path.join(_pasta(base, pid), "projeto.json")


def valido(pid: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{10}", str(pid or "")))


def criar(base: str, tema: str = "", modelo: str = "true_crime") -> Dict[str, Any]:
    pid = uuid.uuid4().hex[:10]
    cfg = dict(CONFIG_PADRAO, modelo=modelo if modelo in MODELOS else "true_crime")
    fk, fv = next(iter(MODELOS[cfg["modelo"]]["formatos"].items()))
    cfg.update(formato=fk, minutos=fv["minutos"])
    import ultimas_escolhas as ue  # 🔁 v84_161: idioma e canal da última vez
    ult = ue.ler(base)
    if ult.get("idioma"):
        cfg["idioma"] = ult["idioma"]
    if "nome_canal" in ult:
        cfg["nome_canal"] = ult["nome_canal"]
    aplicar_padroes_do_modelo(cfg, cfg["modelo"])
    p = {"id": pid, "criado": time.time(), "atualizado": time.time(), "tema": (tema or "").strip()[:300],
         "roteiro_base": "", "config": cfg, "fontes": [], "midias": [], "resultado": None}
    salvar(base, p)
    return p


def carregar(base: str, pid: str) -> Dict[str, Any]:
    if not valido(pid) or not os.path.exists(_arquivo(base, pid)):
        raise DossieError("Projeto não encontrado.")
    with open(_arquivo(base, pid), encoding="utf-8") as f:
        p = json.load(f)
    p["config"] = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    import idiomas
    p["config"]["idioma"] = idiomas.normalizar(p["config"].get("idioma")) or "pt"  # "pt-BR" antigo -> "pt"
    return p


def marcar_mudanca(p: Dict[str, Any], origem: str, mensagem: str = "") -> None:
    """🕘 Diz de onde veio a próxima mudança do roteiro (vai pro histórico de versões no próximo salvar)."""
    p["_mudanca"] = {"origem": origem, "mensagem": mensagem}


def salvar(base: str, p: Dict[str, Any]) -> None:
    os.makedirs(_pasta(base, p["id"]), exist_ok=True)
    mud = p.pop("_mudanca", None) or {}
    p["atualizado"] = time.time()
    tmp = _arquivo(base, p["id"]) + f".{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    arquivo_seguro.trocar(tmp, _arquivo(base, p["id"]))
    rot = (p.get("resultado") or {}).get("roteiro") or ""
    if rot.strip():
        try:  # 🕘 histórico de versões (só grava se o roteiro mudou)
            import historico_roteiro
            historico_roteiro.registrar(_pasta(base, p["id"]), rot, mud.get("origem") or "alteração", mud.get("mensagem") or "")
        except Exception:  # noqa: BLE001 — o histórico nunca impede de salvar
            pass


def listar(base: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isdir(_pasta(base)):
        return out
    for pid in os.listdir(_pasta(base)):
        try:
            p = carregar(base, pid)
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": p["id"], "nome": nome_do_projeto(p), "modelo": (MODELOS.get(p["config"]["modelo"]) or {}).get("nome", ""),
                    "atualizado": p.get("atualizado") or 0, "fontes": len(p.get("fontes") or []),
                    "midias": len(p.get("midias") or []), "tem_roteiro": bool(p.get("resultado"))})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(base: str, pid: str) -> None:
    import shutil
    if valido(pid) and os.path.isdir(_pasta(base, pid)):
        shutil.rmtree(_pasta(base, pid), ignore_errors=True)


def nome_do_projeto(p: Dict[str, Any]) -> str:
    return (p.get("apelido") or p.get("tema") or ((p.get("resultado") or {}).get("titulos") or [""])[0] or "Projeto sem tema")[:120]


# ------------------------------------------------------------------ matérias (qualquer site)
_LIXO_IMG = re.compile(r"logo|icon|avatar|sprite|pixel|spinner|placeholder|blank\.|1x1|badge|banner-ad|/ads?/|emoji|gravatar|"
                       r"facebook\.com/tr|doubleclick|share|whatsapp|twitter|selo|favicon", re.IGNORECASE)
_LIXO_TXT = re.compile(r"^(leia (também|mais)|veja (também|mais)|publicidade|anúncio|compartilh|siga[- ]nos|inscreva-se|"
                       r"assine|clique aqui|newsletter|receba (as )?not[ií]cias|copiar link|comentários?$|tags?:|"
                       r"advertisement|related|read more|sign up|subscribe)", re.IGNORECASE)


def _maior_do_srcset(srcset: str) -> str:
    melhor, w = "", -1
    for parte in (srcset or "").split(","):
        bits = parte.strip().split()
        if not bits:
            continue
        val = 0
        if len(bits) > 1:
            m = re.match(r"(\d+(?:\.\d+)?)[wx]", bits[1])
            val = float(m.group(1)) if m else 0
        if val > w:
            melhor, w = bits[0], val
    return melhor


def ler_materia(html: str, url: str) -> Dict[str, Any]:
    """Título, linha fina, autor, data, seções (subtítulo + texto), texto inteiro
    e imagens (url + legenda/alt) de uma matéria/página."""
    from bs4 import BeautifulSoup
    og = _vd.ler_og(html, url)
    sopa = BeautifulSoup(html, "html.parser")

    def meta(*nomes):
        for n in nomes:
            t = sopa.find("meta", attrs={"property": n}) or sopa.find("meta", attrs={"name": n})
            if t and t.get("content"):
                return t["content"].strip()
        return ""
    autor = meta("article:author", "author", "parsely-author", "sailthru.author")
    data = meta("article:published_time", "datePublished", "pubdate", "date", "parsely-pub-date")
    if not data:
        tm = sopa.find("time")
        data = (tm.get("datetime") or tm.get_text(" ", strip=True)) if tm else ""
    for t in sopa(["script", "style", "noscript", "iframe", "form", "svg", "button", "nav", "footer", "aside"]):
        t.decompose()
    for t in sopa.find_all(attrs={"class": re.compile(r"(^|\s|-)(related|newsletter|share|social|comment|advert|ads?|promo|"
                                                      r"recommend|outbrain|taboola|cookie|footer|menu|breadcrumb)(\s|-|$)", re.I)}):
        t.decompose()
    cands = sopa.find_all(["article", "main"]) or []
    if not cands:
        cands = sopa.find_all(["div", "section"])

    def pontos(el):
        return sum(len(p.get_text(" ", strip=True)) for p in el.find_all("p", recursive=True))
    raiz = max(cands, key=pontos) if cands else sopa.body or sopa
    if pontos(raiz) < 200 and sopa.body is not None:
        raiz = sopa.body
    h1 = raiz.find("h1") or sopa.find("h1")
    titulo = (h1.get_text(" ", strip=True) if h1 else "") or og["titulo"]
    linha_fina = og["descricao"]
    sub = raiz.find(attrs={"class": re.compile(r"subtitle|subtit|lead|linha-fina|standfirst|dek|summary", re.I)})
    if sub and 20 < len(sub.get_text(" ", strip=True)) < 600:
        linha_fina = sub.get_text(" ", strip=True)
    secoes: List[Dict[str, Any]] = [{"titulo": "", "texto": []}]
    vistos = set()
    for el in raiz.find_all(["h2", "h3", "h4", "p", "li", "blockquote"]):
        txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if not txt or txt in vistos or _LIXO_TXT.match(txt):
            continue
        if el.name == "li" and (len(txt) < 25 or el.find_parent(["nav", "header"])):
            continue
        if el.name == "p" and el.find_parent("blockquote"):
            continue
        vistos.add(txt)
        if el.name in ("h2", "h3", "h4"):
            if len(txt) < 160:
                secoes.append({"titulo": txt, "texto": []})
            continue
        if el.name == "blockquote":
            txt = f"“{txt}”"
        secoes[-1]["texto"].append(txt)
    secoes = [{"titulo": s["titulo"], "texto": "\n".join(s["texto"])} for s in secoes if s["texto"] or s["titulo"]]
    texto = "\n\n".join(((f"## {s['titulo']}\n" if s["titulo"] else "") + s["texto"]) for s in secoes).strip()[:MAX_TEXTO_POR_FONTE]
    imagens: List[Dict[str, str]] = []
    vist = set()

    def add_img(src, legenda):
        if not src or src.startswith("data:"):
            return
        u = urljoin(url, src.strip())
        if not u.lower().startswith(("http://", "https://")) or u in vist or _LIXO_IMG.search(u) or u.lower().split("?")[0].endswith(".svg"):
            return
        vist.add(u)
        imagens.append({"url": u, "legenda": re.sub(r"\s+", " ", legenda or "").strip()[:400]})
    if og["imagem"]:
        add_img(og["imagem"], og["titulo"])
    for img in raiz.find_all("img"):
        src = (_maior_do_srcset(img.get("srcset") or img.get("data-srcset") or "")
               or img.get("data-src") or img.get("data-lazy-src") or img.get("data-original") or img.get("src") or "")
        fig = img.find_parent("figure")
        cap = fig.find("figcaption") if fig else None
        leg = (cap.get_text(" ", strip=True) if cap else "") or img.get("alt") or img.get("title") or ""
        try:
            if int(img.get("width") or 999) < 120 or int(img.get("height") or 999) < 90:
                continue
        except ValueError:
            pass
        add_img(src, leg)
    for v in raiz.find_all(["video", "source"]):
        src = v.get("src") or ""
        if src and re.search(r"\.(mp4|webm|mov)(\?|$)", src, re.I):
            add_img(src, v.get("title") or "vídeo da matéria")
    if not texto and not imagens:
        raise DossieError("Não achei texto nem imagens nessa página.")
    return {"url": url, "site": og.get("site") or urlparse(url).netloc, "titulo": titulo[:300], "linha_fina": linha_fina[:800],
            "autor": autor[:120], "data": data[:40], "secoes": secoes[:80], "texto": texto, "imagens": imagens[:MAX_IMAGENS_POR_FONTE],
            "og": {k: og.get(k) for k in ("titulo", "descricao", "imagem", "site")}}


# ------------------------------------------------------------------ mídias
def _novo_id(p: Dict[str, Any], prefixo: str) -> str:
    """Próximo ID (I42…). NUNCA reaproveita o de uma mídia apagada (v84_139): o mesmo ID com outra foto confundia o
    navegador (mostrava a foto antiga do cache), o roteiro e o elenco."""
    usados = {m["id"] for m in p.get("midias") or []}
    nums = [int(i[len(prefixo):]) for i in usados if i.startswith(prefixo) and i[len(prefixo):].isdigit()]
    seq = p.setdefault("seq_ids", {})
    k = max(nums + [int(seq.get(prefixo) or 0)]) + 1
    while f"{prefixo}{k}" in usados:
        k += 1
    seq[prefixo] = k
    return f"{prefixo}{k}"


def url_midia(p: Dict[str, Any], m: Optional[Dict[str, Any]]) -> str:
    """Link da mídia pra tela — com o nome do arquivo no fim, pra o navegador nunca mostrar a foto antiga do cache."""
    if not m:
        return ""
    from urllib.parse import quote
    return f"/modelos-video/{p['id']}/arquivo/{m['id']}?v={quote(os.path.basename(m.get('arquivo') or '')[:80])}"


def adicionar_midia(p: Dict[str, Any], **c: Any) -> Dict[str, Any]:
    tipo = c.get("tipo") if c.get("tipo") in TIPOS_MIDIA else "foto"
    desc = (c.get("descricao") or "").strip()[:2000]
    m = {"id": _novo_id(p, "T" if tipo == "texto" else "I"), "tipo": tipo, "origem": c.get("origem") or "pc",
         "arquivo": c.get("arquivo") or "", "url": c.get("url") or "", "nome": (c.get("nome") or "")[:200],
         "og": c.get("og") or None, "legenda": (c.get("legenda") or "").strip()[:400], "fonte": c.get("fonte") or "",
         "descricao": desc, "conteudo": (c.get("conteudo") or "").strip()[:12000],
         "usar": c.get("usar") if c.get("usar") in ("og", "descricao", "ambos") else ("ambos" if desc else "og"),
         "criado": time.time()}
    p.setdefault("midias", []).append(m)
    return m


def midia(p: Dict[str, Any], mid: str) -> Optional[Dict[str, Any]]:
    return next((m for m in p.get("midias") or [] if m["id"].upper() == str(mid or "").strip().upper()), None)


def caminho_midia(base: str, p: Dict[str, Any], m: Optional[Dict[str, Any]]) -> Optional[str]:
    if not m or not m.get("arquivo"):
        return None
    c = os.path.join(pasta_midias(base, p["id"]), os.path.basename(m["arquivo"]))
    return c if os.path.isfile(c) else None


def o_que_e(m: Dict[str, Any], p: Optional[Dict[str, Any]] = None) -> str:
    if m.get("ia") and not (m.get("descricao") and m.get("usar") == "descricao"):  # 🤖 ficha da imagem (descrição de verdade)
        import ia_dossies
        txt = ia_dossies.texto_da_ficha(m["ia"])
        if txt:
            return txt + (f" (legenda: {m['legenda']})" if m.get("legenda") else "") + (f" | {m['descricao']}" if m.get("descricao") else "")
    og = m.get("og") or {}
    partes_og = [x for x in (m.get("legenda"), og.get("titulo") and f"da página “{og.get('titulo')}”",
                             og.get("descricao") if not m.get("legenda") else "") if x]
    og_txt = " — ".join(partes_og)
    desc = m.get("descricao") or ""
    if m.get("usar") == "og" and og_txt:
        return og_txt
    if m.get("usar") == "descricao" and desc:
        return desc
    return " | ".join(x for x in (desc, og_txt) if x) or (m.get("nome") or "(sem descrição)")


def _imagem_pequena(caminho: str) -> bool:
    try:
        from PIL import Image
        with Image.open(caminho) as im:
            return im.width < 220 or im.height < 160
    except Exception:  # noqa: BLE001
        return False


def processar_fonte(base: str, pid: str, fid: str, trava=None) -> Dict[str, Any]:
    """Lê a matéria da fonte `fid` e baixa as imagens dela (cada uma vira uma mídia I…).
    A parte lenta (rede) roda SEM a trava; o projeto só é mexido com ela (a pessoa
    pode continuar editando a página enquanto isso)."""
    import contextlib
    trava = trava or contextlib.nullcontext()

    def mexer(fn):
        with trava:
            p = carregar(base, pid)
            f = next((x for x in p.get("fontes") or [] if x["id"] == fid), None)
            if f is None:
                return None
            out = fn(p, f)
            salvar(base, p)
            return out
    url = mexer(lambda p, f: (f.update(estado="lendo", erro=None), f.get("arquivo") and ("arquivo:" + f["arquivo"]) or f["url"])[1])
    if not url:
        raise DossieError("Fonte não encontrada.")
    try:
        if url.startswith("arquivo:"):  # 📄 arquivo enviado (txt, pdf, livro…)
            paginas = mexer(lambda p, f: f.get("paginas") or "")
            dados = ler_arquivo(os.path.join(_pasta(base, pid), "fontes", os.path.basename(url[8:])), paginas, job=pid)
        else:
            html, final = _vd.baixar_html(url)
            dados = ler_materia(html, final)
    except (_vd.VendaError, DossieError) as exc:
        mexer(lambda p, f: f.update(estado="erro", erro=str(exc)))
        return {"erro": str(exc)}
    mexer(lambda p, f: f.update({**{k: dados[k] for k in ("site", "titulo", "linha_fina", "autor", "data", "secoes", "texto", "og")},
                                 "estado": f"baixando {len(dados['imagens'])} imagens", "imagens_achadas": len(dados["imagens"])}))
    baixadas = []
    for im in dados["imagens"]:
        try:
            cam, tipo = _vd.baixar_arquivo(im["url"], pasta_midias(base, pid), f"{fid.lower()}_{uuid.uuid4().hex[:6]}")
        except _vd.VendaError:
            continue
        if tipo == "foto" and _imagem_pequena(cam):
            os.remove(cam)
            continue
        baixadas.append((im, cam, tipo))

    def juntar(p, f):
        ja = {m.get("url") for m in p.get("midias") or []}
        n = 0
        for im, cam, tipo in baixadas:
            if im["url"] in ja:
                try:
                    os.remove(cam)
                except OSError:
                    pass
                continue
            n += 1
            adicionar_midia(p, tipo=tipo, origem="url", url=im["url"], arquivo=os.path.basename(cam), nome=os.path.basename(cam),
                            legenda=im["legenda"], fonte=fid, og={"titulo": dados["titulo"], "descricao": dados["linha_fina"]}, usar="og")
        f.update(estado="pronta", imagens=n)
        return n
    n = mexer(juntar)
    # 🤖 arquivo grande → dossiê condensado (fatos com a página de cada um) em vez de jogar tudo no prompt
    if url.startswith("arquivo:") and len(dados.get("texto") or "") > LIMITE_CONDENSAR:
        try:
            import ia_dossies
            mexer(lambda p, f: f.update(estado="🤖 condensando com a IA…"))
            cond = ia_dossies.condensar(dados["texto"], dados.get("titulo") or "", job=pid)
            if cond:
                mexer(lambda p, f: f.update(condensado=cond))
        except Exception:  # noqa: BLE001
            pass
        mexer(lambda p, f: f.update(estado="pronta"))
    ia_analisar_imagens(base, pid, trava=trava, fonte=fid)  # 🤖 ficha das imagens (sem IA não faz nada)
    import midia_transcricao as mt
    for _im, cam, tipo in baixadas:  # vídeos da matéria: transcrição com os tempos (segundo plano)
        if tipo == "video" and os.path.isfile(cam):
            mt.agendar(cam)
    return {"ok": True, "imagens": n}


# ------------------------------------------------------------------ fontes por ARQUIVO (txt, pdf, livro…)
def _intervalo(paginas: str, total: int) -> List[int]:
    """"10-45, 50" -> índices (0-based) das páginas; vazio -> todas."""
    out: List[int] = []
    for parte in re.split(r"[,;\s]+", str(paginas or "").strip()):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", parte)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out.extend(range(max(1, a) - 1, min(total, max(a, b))))
    return sorted(set(out)) or list(range(total))


LIMITE_CONDENSAR = 40000  # caracteres: acima disso, com a IA ligada, a fonte vira um dossiê condensado


def ia_analisar_imagens(base: str, pid: str, trava=None, fonte: Optional[str] = None, ids: Optional[List[str]] = None,
                        refazer: bool = False) -> Dict[str, Any]:
    """🤖 Duplicadas (hash, de graça) + ficha de cada imagem (o que é, quem, texto, lixo/anúncio, sensível).
    Sem IA: não faz nada. As descartadas/duplicadas ficam no projeto (dá pra recuperar), só saem do prompt."""
    import contextlib
    import ia_dossies
    import ia_servico
    if not ia_servico.ativo("dossie_imagens"):
        return {"ok": False, "erro": ia_servico.motivo_desligado("dossie_imagens")}
    trava = trava or contextlib.nullcontext()
    with trava:
        p = carregar(base, pid)
    fontes = {f["id"]: f for f in p.get("fontes") or []}
    alvo = [m for m in p.get("midias") or [] if m["tipo"] in ("foto", "video")
            and (ids is None or m["id"] in ids) and (fonte is None or m.get("fonte") == fonte) and (refazer or not m.get("ia"))]
    cams = {m["id"]: caminho_midia(base, p, m) for m in alvo}
    cams = {k: v for k, v in cams.items() if v}
    fotos = {k: v for k, v in cams.items() if not v.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".m4v"))}
    dup = ia_dossies.duplicadas(fotos)
    itens = []
    for m in alvo:
        if m["id"] not in cams or m["id"] in dup:
            continue
        f = fontes.get(m.get("fonte") or "") or {}
        ctx = " | ".join(x for x in (m.get("legenda") and f"legenda: {m['legenda']}", f.get("titulo") and f"matéria: {f['titulo']}",
                                     f.get("linha_fina"), m.get("descricao") and f"o que eu disse: {m['descricao']}",
                                     not f and m.get("nome") and f"arquivo: {m['nome']}") if x)
        itens.append({"id": m["id"], "caminho": cams[m["id"]], "contexto": ctx})
    fichas = ia_dossies.fichar_imagens(itens, job=pid)
    with trava:
        p = carregar(base, pid)
        n = 0
        for m in p.get("midias") or []:
            if m["id"] in dup:
                m["duplicada_de"] = dup[m["id"]]
            if m["id"] in fichas:
                m["ia"] = fichas[m["id"]]
                m["descartada"] = ia_dossies.descartar(fichas[m["id"]])
                n += 1
        salvar(base, p)
    return {"ok": True, "fichas": n, "duplicadas": len(dup), "descartadas": sum(1 for k in fichas if ia_dossies.descartar(fichas[k]))}


def ia_conferir_marcas(p: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """🤖 Passo E: as marcas [I3] do roteiro que não combinam com a imagem (None sem IA)."""
    import ia_dossies
    roteiro = ((p.get("resultado") or {}).get("roteiro") or "")
    fichas = {m["id"].upper(): o_que_e(m, p) for m in p.get("midias") or [] if m["tipo"] in ("foto", "video") and not m.get("descartada")}
    return ia_dossies.conferir_marcas(roteiro, fichas, job=p.get("id"))


def _texto_pdf(caminho: str, paginas: str) -> Tuple[str, List[Dict[str, Any]], int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DossieError("Pra ler PDF instale o pypdf:  pip install pypdf") from exc
    leitor = PdfReader(caminho)
    total = len(leitor.pages)
    secoes = []
    for i in _intervalo(paginas, total):
        try:
            t = leitor.pages[i].extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"-\n(\w)", r"\1", t)  # palavra quebrada no fim da linha
        t = re.sub(r"(?<![.!?:])\n(?!\n)", " ", t).strip()
        if t:
            secoes.append({"titulo": f"Página {i + 1}", "texto": t})
    if not secoes:
        raise DossieError("Não achei texto nesse PDF (pode ser só imagem escaneada — precisaria de OCR).")
    return "\n\n".join(f"[pág. {s['titulo'].split()[-1]}] {s['texto']}" for s in secoes), secoes, total


def _texto_epub(caminho: str) -> Tuple[str, List[Dict[str, Any]], str]:
    import zipfile
    from bs4 import BeautifulSoup
    with zipfile.ZipFile(caminho) as z:
        nomes = z.namelist()
        cont = next((n for n in nomes if n.endswith(".opf")), None)
        ordem, titulo = [], ""
        if cont:
            opf = BeautifulSoup(z.read(cont).decode("utf-8", "replace"), "html.parser")
            t = opf.find(["dc:title", "title"])
            titulo = t.get_text(strip=True) if t else ""
            itens = {i.get("id"): i.get("href") for i in opf.find_all("item")}
            raiz = os.path.dirname(cont)
            for ref in opf.find_all("itemref"):
                h = itens.get(ref.get("idref"))
                if h:
                    ordem.append(os.path.normpath(os.path.join(raiz, h)).replace("\\", "/"))
        ordem = [n for n in ordem if n in nomes] or sorted(n for n in nomes if n.lower().endswith((".xhtml", ".html", ".htm")))
        secoes = []
        for n in ordem:
            sopa = BeautifulSoup(z.read(n).decode("utf-8", "replace"), "html.parser")
            h = sopa.find(["h1", "h2", "h3"])
            texto = "\n".join(x.get_text(" ", strip=True) for x in sopa.find_all(["p", "blockquote", "li"]) if x.get_text(strip=True))
            if texto:
                secoes.append({"titulo": h.get_text(" ", strip=True)[:150] if h else "", "texto": texto})
    return "\n\n".join(((f"## {s['titulo']}\n" if s["titulo"] else "") + s["texto"]) for s in secoes), secoes, titulo


def _texto_docx(caminho: str) -> Tuple[str, List[Dict[str, Any]]]:
    import zipfile
    from xml.etree import ElementTree as ET
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(caminho) as z:
        raiz = ET.fromstring(z.read("word/document.xml"))
    secoes: List[Dict[str, Any]] = [{"titulo": "", "texto": []}]
    for par in raiz.iter(w + "p"):
        txt = "".join(t.text or "" for t in par.iter(w + "t")).strip()
        if not txt:
            continue
        estilo = par.find(f"{w}pPr/{w}pStyle")
        val = (estilo.get(w + "val") if estilo is not None else "") or ""
        if re.match(r"(Heading|Ttulo|Título|Titulo)\s*\d?", val, re.I) and len(txt) < 160:
            secoes.append({"titulo": txt, "texto": []})
        else:
            secoes[-1]["texto"].append(txt)
    secoes = [{"titulo": s["titulo"], "texto": "\n".join(s["texto"])} for s in secoes if s["texto"] or s["titulo"]]
    return "\n\n".join(((f"## {s['titulo']}\n" if s["titulo"] else "") + s["texto"]) for s in secoes), secoes


def _ler_texto_solto(caminho: str) -> str:
    bruto = open(caminho, "rb").read()
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return bruto.decode(cod)
        except UnicodeDecodeError:
            continue
    return bruto.decode("utf-8", "replace")


def _pdf_com_ia(caminho: str, paginas: str, job: Optional[str]) -> Tuple[str, List[Dict[str, Any]], int]:
    """🤖 PDF escaneado (ou com páginas sem texto): as páginas sem texto vão pra IA (partes de 25)."""
    import ia_dossies
    from pypdf import PdfReader
    total = len(PdfReader(caminho).pages)
    idx = _intervalo(paginas, total)
    try:
        texto, secoes, _t = _texto_pdf(caminho, paginas)
    except DossieError:
        texto, secoes = "", []
    com_texto = {int(s["titulo"].split()[-1]) - 1 for s in secoes}
    sem = [i for i in idx if i not in com_texto]
    if sem and len(sem) <= 400:
        lido = ia_dossies.ler_pdf(caminho, sem, job=job)
        if lido:
            for m in re.finditer(r"\[pág\. (\d+)\] (.*?)(?=\n\n\[pág\. \d+\] |\Z)", lido, re.S):
                secoes.append({"titulo": f"Página {m.group(1)}", "texto": m.group(2).strip(), "ia": True})
            secoes.sort(key=lambda s: int(s["titulo"].split()[-1]))
            texto = "\n\n".join(f"[pág. {s['titulo'].split()[-1]}] {s['texto']}" for s in secoes)
    if not texto.strip():
        raise DossieError("Não achei texto nesse PDF (pode ser só imagem escaneada — ligue a 🤖 IA pra ler PDF escaneado, ou use OCR).")
    return texto, secoes, total


def ler_arquivo(caminho: str, paginas: str = "", job: Optional[str] = None) -> Dict[str, Any]:
    """Texto (e seções) de um arquivo de fonte: TXT/MD, PDF (com intervalo de páginas),
    EPUB, DOCX, SRT/VTT (sem os tempos), HTML, RTF (texto simples)."""
    nome = os.path.basename(caminho)
    ext = os.path.splitext(nome)[1].lower()
    titulo, secoes, extra = os.path.splitext(nome)[0].split("_", 1)[-1], [], ""
    if ext == ".pdf":
        import ia_servico
        if ia_servico.ativo("dossie_pdf"):
            texto, secoes, total = _pdf_com_ia(caminho, paginas, job)
        else:
            texto, secoes, total = _texto_pdf(caminho, paginas)
        extra = f"PDF de {total} páginas" + (f", usadas: {paginas}" if paginas else "") + (" (🤖 páginas escaneadas lidas pela IA)" if any(s.get("ia") for s in secoes) else "")
    elif ext == ".epub":
        texto, secoes, t = _texto_epub(caminho)
        titulo = t or titulo
        extra = f"livro (EPUB), {len(secoes)} capítulos"
    elif ext == ".docx":
        texto, secoes = _texto_docx(caminho)
    elif ext in (".html", ".htm"):
        return dict(ler_materia(_ler_texto_solto(caminho), "file:///" + nome), imagens=[])
    else:
        texto = _ler_texto_solto(caminho)
        if ext in (".srt", ".vtt"):
            texto = re.sub(r"^\s*\d+\s*$|^\s*[\d:.,]+\s*-->\s*[\d:.,]+.*$|^WEBVTT.*$", "", texto, flags=re.M)
            texto = re.sub(r"<[^>]+>", "", texto)
        elif ext == ".rtf":
            texto = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", texto)
        texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if not texto.strip():
        raise DossieError("Não achei texto nesse arquivo.")
    cortado = len(texto) > MAX_TEXTO_ARQUIVO
    texto = texto[:MAX_TEXTO_ARQUIVO]
    return {"url": "", "site": extra or ext.lstrip(".").upper(), "titulo": titulo[:300],
            "linha_fina": (f"⚠ só os primeiros {MAX_TEXTO_ARQUIVO // 1000} mil caracteres (arquivo grande — escolha as páginas)" if cortado else ""),
            "autor": "", "data": "", "secoes": secoes[:400], "texto": texto, "imagens": [], "og": {}}


def adicionar_fonte_arquivo(base: str, p: Dict[str, Any], nome: str, conteudo: bytes, paginas: str = "") -> Dict[str, Any]:
    ext = os.path.splitext(nome or "")[1].lower()
    if ext not in EXT_ARQUIVO_FONTE:
        raise DossieError("Arquivo de fonte: " + ", ".join(EXT_ARQUIVO_FONTE) + ".")
    usados = {x["id"] for x in p.get("fontes") or []}
    k = 1
    while f"F{k}" in usados:
        k += 1
    pasta = os.path.join(_pasta(base, p["id"]), "fontes")
    os.makedirs(pasta, exist_ok=True)
    seguro = re.sub(r"[^\w.\- ]+", "_", os.path.basename(nome))[:120] or f"fonte{ext}"
    destino = os.path.join(pasta, f"F{k}_{seguro}")
    with open(destino, "wb") as fh:
        fh.write(conteudo)
    f = {"id": f"F{k}", "url": "", "arquivo": os.path.basename(destino), "paginas": str(paginas or "").strip()[:60],
         "estado": "na fila", "erro": None, "titulo": os.path.splitext(seguro)[0], "linha_fina": "", "autor": "", "data": "",
         "site": "arquivo", "secoes": [], "texto": "", "imagens": 0, "imagens_achadas": 0, "og": {}}
    p.setdefault("fontes", []).append(f)
    return f


_RX_VIDEO = re.compile(
    r"^https?://(?:[\w-]+\.)*(?:youtube\.com/(?:watch|shorts/|live/|embed/)|youtu\.be/|vimeo\.com/\d|player\.vimeo\.com/|"
    r"tiktok\.com/.+/video/|vm\.tiktok\.com/|instagram\.com/(?:reel|reels|tv|p)/|facebook\.com/(?:.+/videos/|watch|reel/)|fb\.watch/|"
    r"dailymotion\.com/video/|dai\.ly/|twitch\.tv/videos/|rumble\.com/v|kwai\.com/|(?:x|twitter)\.com/[^/]+/status/)", re.I)


def eh_link_de_video(url: str) -> bool:
    """🎬 v84_161: link de vídeo (YouTube, TikTok, Instagram, Vimeo, Facebook, X…) — vira transcrição nas anotações."""
    return bool(_RX_VIDEO.match(str(url or "").strip()))


_RX_YT_ID = re.compile(r"^https?://(?:[\w-]+\.)*(?:youtube\.com/(?:watch\?(?:[^#\s]*?&)?v=|shorts/|live/|embed/|v/)|youtu\.be/)"
                       r"([A-Za-z0-9_-]{11})", re.I)


def link_video_padrao(url: str) -> str:
    """🎬 v84_177: qualquer link do YouTube (Shorts, youtu.be, live, embed, com ?si=/&xstg=/&sttick=…) vira
    https://www.youtube.com/watch?v=ID — o formato que a transcrição entende. Os outros sites ficam como estão."""
    u = str(url or "").strip()
    m = _RX_YT_ID.match(u)
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else u


def adicionar_fonte(p: Dict[str, Any], url: str) -> Dict[str, Any]:
    url = _vd._checar_url(url)
    if any(x["url"] == url for x in p.get("fontes") or []):
        raise DossieError("Essa fonte já está no projeto.")
    usados = {x["id"] for x in p.get("fontes") or []}
    k = 1
    while f"F{k}" in usados:
        k += 1
    f = {"id": f"F{k}", "url": url, "estado": "na fila", "erro": None, "titulo": "", "linha_fina": "", "autor": "", "data": "",
         "site": urlparse(url).netloc, "secoes": [], "texto": "", "imagens": 0, "imagens_achadas": 0, "og": {}}
    p.setdefault("fontes", []).append(f)
    return f


# ------------------------------------------------------------------ prompt do roteiro
def alvo_tamanho(p: Dict[str, Any]) -> Tuple[float, int, int]:
    """(minutos, palavras, palavras por minuto) que o roteiro deste projeto tem que ter."""
    cfg = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    mod = MODELOS.get(cfg["modelo"]) or MODELOS["true_crime"]
    fmt = mod["formatos"].get(cfg["formato"]) or next(iter(mod["formatos"].values()))
    try:
        minutos = max(0.5, min(120, float(cfg.get("minutos") or fmt["minutos"])))
    except (TypeError, ValueError):
        minutos = fmt["minutos"]
    ppm = int(mod.get("palavras_por_minuto") or 150)
    return minutos, int(minutos * ppm), ppm


def prompt_roteiro(p: Dict[str, Any], base: Optional[str] = None) -> str:
    cfg = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    mod = MODELOS.get(cfg["modelo"]) or MODELOS["true_crime"]
    fmt = mod["formatos"].get(cfg["formato"]) or next(iter(mod["formatos"].values()))
    fontes = [f for f in p.get("fontes") or [] if f.get("texto")]
    if not (p.get("tema") or "").strip():
        raise DossieError("Escreva o tema do vídeo (ex.: o nome do caso).")
    if not fontes and not (p.get("roteiro_base") or "").strip() and not any(m["tipo"] == "texto" for m in p.get("midias") or []):
        raise DossieError("Adicione pelo menos uma fonte (link de matéria), um texto ou o roteiro base — sem isso a IA inventaria.")
    minutos, palavras, _ppm = alvo_tamanho(p)
    import metodo_roteiro
    L: List[str] = []
    L.append(f"Você é roteirista de um canal de {sem_emoji(mod['nome'])} no YouTube. Escreva o roteiro NARRADO completo "
             f"(alguém vai ler em voz alta) de um vídeo sobre o tema abaixo, usando SÓ as fontes e materiais que eu juntei.")
    L.append("")
    L.append(f"## Tema\n{p['tema'].strip()}")
    L.append("")
    _prom = metodo_roteiro.bloco_promessa(titulo_promessa(p), curto=minutos <= 1 or cfg.get("formato") == "curto")
    if _prom:  # 🧵 v84_169: o título/tema é a promessa — o roteiro inteiro amarra nele
        L.append(_prom)
        L.append("")
    _esc = metodo_roteiro.bloco_escopo(titulo_promessa(p), idioma=__import__("idiomas").normalizar(cfg.get("idioma")) or "pt",
                                       curto=minutos <= 1 or cfg.get("formato") == "curto", enxuto=escopo_enxuto(mod))
    L.append(_esc)  # 🎯 v84_178: só o necessário pro título; o assunto vizinho é outro vídeo
    L.append("")
    import idiomas
    nome_idioma = idiomas.nome_para_prompt(idiomas.normalizar(cfg.get("idioma")) or "pt")
    if (idiomas.normalizar(cfg.get("idioma")) or "pt") == "en":
        import roteiros_yt
        L.insert(1, roteiros_yt.regra_tags_turbo())
    L.insert(1, f"IDIOMA DE SAÍDA: escreva TUDO em {nome_idioma} — roteiro, títulos, ideias, descrição, capítulos e tags —, "
                "mesmo que as fontes estejam em outro idioma (traduza os fatos com fidelidade; nomes próprios, de lugares e de "
                "obras ficam como são, com a tradução oficial quando existir).")
    L.append(f"## Formato: {sem_emoji(fmt['nome'])} — ~{minutos:g} min (~{palavras} palavras), em {nome_idioma}")
    L.append("Estrutura (siga a ordem; cada parte pode virar um ou mais capítulos):")
    L.extend(f"{k}. {e}" for k, e in enumerate(fmt["estrutura"], start=1))
    L.append("")
    L.append("## Regras do modelo (obrigatórias)")
    L.extend(f"- {r}" for r in mod["regras"])
    if (cfg.get("tom") or "").strip():
        L.append(f"- Tom: {cfg['tom'].strip()[:400]}")
    if (cfg.get("extra") or "").strip():
        L.append(f"- Pedido extra (siga com prioridade): {cfg['extra'].strip()[:1500]}")
    if cfg.get("sem_experiencias", True):
        L.append("- " + REGRA_SEM_PESSOAL)
    _perfil = perfil_do_modelo(cfg.get("modelo"))
    if _perfil:  # 🎭 v84_173: canal com personagens — falas multi voz, emoção por fala, lore, continuidade, histórico
        import canal_perfil
        L.append("")
        L.append(canal_perfil.bloco_roteiro(_perfil, ia_emocao=cfg.get("ia_emocao", True) is not False,
                                            curto=minutos <= 1 or cfg.get("formato") == "curto"))
    if cfg.get("marcar_chamadas", True) and fmt.get("minutos", 10) > 1:
        import roteiros_yt
        L.append("")
        L.append(roteiros_yt.regra_marcas((mod.get("chamadas") or {}).get("inscreva")))  # 📣 v84_218: o canal pode pedir só 1
        L.append("")
    if cfg.get("sugerir_produto"):
        L.append("- " + REGRA_PRODUTO)
    if (p.get("roteiro_base") or "").strip():
        L.append("")
        L.append("## Meu roteiro / anotações — GUIA (os fatos e o que eu quero destacar; confira e complete com as fontes)")
        L.append(p["roteiro_base"].strip()[:120000])  # v84_161: cabe a transcrição de vídeos
        L.append("")
        L.append(metodo_roteiro.bloco_guia("o meu roteiro/as minhas anotações"))
    if fontes:
        L.append("")
        L.append("## Fontes (matérias que eu salvei — cite o site quando usar um fato importante)")
        for f in fontes:
            cab = f"### {f['id']} — {f.get('titulo') or f.get('url') or f.get('arquivo')}"
            info = " · ".join(x for x in (f.get("site"), f.get("autor"), f.get("data")) if x)
            L.append(cab + (f"\n({info})" if info else "") + (f"\n{f['url']}" if f.get("url") else f"\n(arquivo: {f.get('arquivo')})"))
            if f.get("linha_fina"):
                L.append(f"Linha fina: {f['linha_fina']}")
            if f.get("condensado"):  # 🤖 arquivo grande: o dossiê condensado (com as páginas) no lugar do texto inteiro
                import ia_dossies
                L.append("(dossiê condensado pela IA — confira os fatos pela página)\n" + ia_dossies.condensado_para_prompt(f["condensado"]))
            else:
                L.append(f.get("texto") or "")
    textos = [m for m in p.get("midias") or [] if m["tipo"] == "texto"]
    if textos:
        L.append("")
        L.append("## Textos de apoio")
        for m in textos:
            L.append(f"### {m['id']}" + (f" — {m['descricao']}" if m.get("descricao") else "") + f"\n{m.get('conteudo') or ''}")
    vis = [m for m in p.get("midias") or [] if m["tipo"] in ("foto", "video") and not m.get("descartada") and not m.get("duplicada_de")]
    if vis:
        L.append("")
        L.append("## Imagens e vídeos que eu tenho (vão aparecer no vídeo — use os IDs)")
        import midia_transcricao as mt
        for m in vis[:300]:
            cam = caminho_midia(base, p, m) if base else None
            L.append(f"- {m['id']} ({'vídeo' if m['tipo'] == 'video' else 'foto'}{', ' + m['fonte'] if m.get('fonte') else ''}): {o_que_e(m)}"
                     + (mt.para_prompt(cam) if cam and m["tipo"] == "video" else ""))
        L.append("No ROTEIRO, ponha a marca do ID (ex.: [I4]) sozinha logo ANTES da frase em que aquela imagem deve aparecer — "
                 "só imagens que mostram MESMO o que a frase fala (pessoa, lugar, objeto, documento). As marcas não são lidas. "
                 + __import__("roteiro_partes").REGRA)
        if any(m["tipo"] == "video" for m in vis):
            L.append(mt.instrucao_roteiro("I7"))
    L.append("")
    L.append(metodo_roteiro.bloco("curto" if (minutos <= 1 or cfg.get("formato") == "curto") else "longo"))
    if (cfg.get("referencia") or "").strip():
        L.append("")
        L.append(metodo_roteiro.bloco_referencia(cfg["referencia"], cfg.get("referencia_modo") or "inspirar"))
    import canal  # 📺 o nome do canal, falado no momento certo
    _canal = canal.nome_do_projeto(nome_canal_cfg(cfg))
    if _canal:
        L.append("")
        L.append(metodo_roteiro.bloco_canal(_canal, curto=minutos <= 1 or cfg.get("formato") == "curto"))
    L.append("")
    _cod = idiomas.normalizar(cfg.get("idioma")) or "pt"
    L.append(metodo_roteiro.bloco_titulos(5, "" if _cod == "pt" else nome_idioma))
    L.append("")
    import roteiro_partes
    em_partes = roteiro_partes.usa_partes(cfg, minutos)
    _tam = (roteiro_partes.bloco_plano(minutos, palavras, fmt.get("estrutura"), enxuto=escopo_enxuto(mod)) if em_partes
            else metodo_roteiro.bloco_tamanho(minutos, palavras, fmt.get("estrutura")))  # 📏 perto do fim: a IA respeita mais
    if _tam:
        L.append(_tam)
        L.append("")
    L.append("## Resposta — SOMENTE um JSON válido, assim:")
    if em_partes:  # ✍️ só o PLANO agora (os capítulos vêm um por um, em texto puro)
        L.append(json.dumps({
            "plano": metodo_roteiro.PLANO_JSON,
            "escopo": metodo_roteiro.ESCOPO_JSON,
            "titulos": ["5 títulos (até ~60 caracteres, cada um numa fórmula diferente da lista de títulos)"],
            "capitulos": roteiro_partes.exemplo_capitulos(),
            "descricao": "descrição do caso pra descrição do YouTube (2-4 parágrafos, sem os capítulos — o site monta os tempos)",
            "thumbnails": __import__("thumbs_flow").EXEMPLO_JSON,
            "ideias": ["ideias de ganchos / vídeos derivados"],
            "tags": ["tags do YouTube"],
            "fontes_usadas": ["F1", "F2"],
            "observacoes": "pontos que eu devo conferir (fatos duvidosos, fontes que discordam)",
            **({"produto_sugerido": {"nome": "nome do produto", "por_que": "por que combina com este vídeo e com o público",
                                     "busca": "o que digitar na Amazon pra achar", "chamada": "2-3 frases de venda pro vídeo da [[VENDA]]"}}
               if cfg.get("sugerir_produto") else {}),
            **({"lore_registro": __import__("canal_perfil").EXEMPLO_REGISTRO} if _perfil else {}),
        }, ensure_ascii=False, indent=2))
        if _perfil:
            L.append(__import__("canal_perfil").bloco_registro())
        L.append("NÃO inclua \"roteiro\" nesta resposta — só o plano. " + __import__("thumbs_flow").BLOCO_PROMPT)
        L.append("")
        L.append(idiomas.lembrete_final(idiomas.normalizar(cfg.get("idioma")) or "pt"))
        return "\n".join(L)
    L.append(json.dumps({
        "roteiro": "Texto narrado COMPLETO, no tamanho pedido... [I3] frase em que a imagem I3 aparece...",
        "plano": metodo_roteiro.PLANO_JSON,
        "escopo": metodo_roteiro.ESCOPO_JSON,
        "titulos": ["5 títulos (até ~60 caracteres, cada um numa fórmula diferente da lista de títulos)"],
        "ideias": ["ideias de ganchos / vídeos derivados"],
        "thumbnails": __import__("thumbs_flow").EXEMPLO_JSON,
        "descricao": "descrição do caso pra descrição do YouTube (2-4 parágrafos, sem os capítulos — o site monta os tempos)",
        "capitulos": [{"titulo": "Título curto do capítulo", "comeca_em": "as primeiras 6-10 palavras EXATAS do roteiro onde ele começa"}],
        "momentos": [{"midia": "I3", "trecho": "frase exata do roteiro em que a imagem entra"}],
        "tags": ["tags do YouTube"],
        "fontes_usadas": ["F1", "F2"],
        **({"afirmacoes": [{"trecho": "a frase do roteiro (cópia curta)", "tipo": "fato | alegacao | interpretacao",
                            "fonte": "F2 — de onde vem (site/documento) · ou quem alega"}]}
           if mod.get("afirmacoes") else {}),
        "observacoes": "pontos que eu devo conferir (fatos duvidosos, fontes que discordam)",
        **({"produto_sugerido": {"nome": "nome do produto", "por_que": "por que combina com este vídeo e com o público",
                                 "busca": "o que digitar na Amazon pra achar", "chamada": "2-3 frases de venda pro vídeo da [[VENDA]]"}}
           if cfg.get("sugerir_produto") else {}),
        **({"lore_registro": __import__("canal_perfil").EXEMPLO_REGISTRO} if _perfil else {}),
    }, ensure_ascii=False, indent=2))
    if _perfil:
        L.append(__import__("canal_perfil").bloco_registro())
    L.append("O 1º capítulo começa no início do roteiro. 5 a 15 capítulos (Shorts: nenhum).")
    L.append(__import__("thumbs_flow").BLOCO_PROMPT)
    L.append("")
    L.append(idiomas.lembrete_final(idiomas.normalizar(cfg.get("idioma")) or "pt"))  # 🌐 o idioma de novo, no FIM (a IA respeita mais)
    return "\n".join(L)


def _texto_voz(roteiro: str) -> str:
    import midia_transcricao as mt
    return mt.tirar_marcas(roteiro)


def ler_resultado(texto: str, p: Dict[str, Any]) -> Dict[str, Any]:
    import json_ia
    import roteiros_yt
    try:
        d = json_ia.carregar(texto)
    except ValueError as exc:
        raise DossieError(str(exc)) from exc
    if isinstance(d, list) and len(d) == 1 and isinstance(d[0], dict):
        d = d[0]
    import roteiro_partes as _rp
    if isinstance(d, dict) and not str(d.get("roteiro") or "").strip() and _rp.eh_plano(d.get("capitulos")):
        return _resultado_plano(d, p)  # ✍️ veio o PLANO: os capítulos são escritos um por um
    if not isinstance(d, dict) or not str(d.get("roteiro") or "").strip():
        raise DossieError("O JSON não tem o \"roteiro\".")
    _esc = __import__("metodo_roteiro").ler_escopo(d.get("escopo")) or ((p.get("resultado") or {}).get("escopo") or {})
    if isinstance(d.get("lore_registro"), dict) or _esc.get("fica_para_outro_video"):
        registrar_lore(p, d.get("lore_registro") or {}, _esc)  # 🎭 v84_173 (+ 🎯 os vídeos prometidos)
    rot = str(d["roteiro"]).strip()
    ids = {m["id"].upper() for m in p.get("midias") or []}
    avisos: List[str] = []
    import metodo_roteiro as _mr
    _perf = perfil_do_modelo((p.get("config") or {}).get("modelo"))
    if _perf:  # 🎭 v84_178: [narrator|contemplativ] → [narrador|contemplativo]; fala vazia sai
        import canal_perfil as _cp
        rot, _cons = _cp.normalizar_falas(rot, _perf)
        if _cons:
            avisos.append("🎭 Tags corrigidas: " + " · ".join(_cons[:6]) + (f" (+{len(_cons) - 6})" if len(_cons) > 6 else ""))
        _sem_tag = _cp.paragrafos_sem_tag(rot, _perf)  # 🎭 v84_218: cada fala com quem fala
        if _sem_tag:
            avisos.insert(0, f"🎭 {_sem_tag} parágrafo(s) sem a tag de quem fala (narrador / personagem) — no ✍ Correção, "
                             "clique em 🎭 Marcar quem fala.")
    _max_insc = (_modelo_cfg(p).get("chamadas") or {}).get("inscreva")
    if _max_insc is not None:  # 📣 v84_218: o canal quer no máximo N [[INSCREVA]]
        import canal_perfil as _cp2
        rot, _tir = _cp2.limitar_inscreva(rot, _max_insc)
        if _tir:
            avisos.append(f"📣 {_tir} [[INSCREVA]] a mais tirada(s) — o canal usa {_max_insc} por vídeo.")
    rot, _rep = _mr.tirar_repeticoes(rot)  # 🔁 v84_169: frase quase igual logo em seguida sai
    if _rep:
        avisos.append(f"🔁 {len(_rep)} frase(s) repetida(s) logo em seguida tirada(s): " + " · ".join(f"“{x[:70]}…”" for x in _rep[:3]))
    import midia_transcricao as mt
    momentos, sem = mt.momentos_do_roteiro(rot, ids, d.get("momentos"))
    if sem:
        avisos.append("A IA citou imagens que não existem: " + ", ".join(sem) + " (ignoradas).")
    voz = _texto_voz(rot)
    n_pal = len(voz.split())
    caps = roteiros_yt._capitulos(d.get("capitulos") or [], voz, n_pal, avisos)
    import metodo_roteiro
    _min, _alvo, _ppm = alvo_tamanho(p)
    _av = metodo_roteiro.aviso_tamanho(metodo_roteiro.palavras_do_texto(voz), _alvo, _min, _ppm)
    if _av:
        avisos.insert(0, "📏 " + _av)
    _lg = metodo_roteiro.aviso_longo(metodo_roteiro.palavras_do_texto(voz), _alvo, _min, _ppm)
    if _lg:
        avisos.insert(0, "📏 " + _lg)
    return {"alvo": {"minutos": _min, "palavras": _alvo, "ppm": _ppm, "curto": bool(_av), "longo": bool(_lg)},"titulos": [str(x)[:150] for x in d.get("titulos") or [] if str(x).strip()][:10],
            "ideias": _ideias_com_escopo(d.get("ideias"), _esc),
            **({"escopo": _esc} if _esc else {}),
            "descricao": str(d.get("descricao") or "").strip()[:5000], "capitulos": caps, "palavras": n_pal,
            "roteiro": rot, "roteiro_final": voz, "momentos": momentos,
            "tags": [str(x)[:60] for x in d.get("tags") or [] if str(x).strip()][:30],
            "fontes_usadas": [str(x)[:10] for x in d.get("fontes_usadas") or []][:30],
            "afirmacoes": _afirmacoes(d.get("afirmacoes")),
            "thumbnails": [t for t in (__import__("thumbs_flow").normalizar(x) for x in (d.get("thumbnails") or [])[:6]) if t],
            **({"partes": d["partes"]} if isinstance(d.get("partes"), list) and d["partes"] else {}),
            "observacoes": str(d.get("observacoes") or "").strip()[:2000], "avisos": avisos, "gerado_em": time.time(),
            **({"lore_registro": d["lore_registro"]} if isinstance(d.get("lore_registro"), dict) else {}),
            "produto_sugerido": _produto(d.get("produto_sugerido")),
            "plano": __import__("metodo_roteiro").ler_plano(d.get("plano")),
            "chamadas": {"inscreva": len(re.findall(r"\[\[\s*INSCREVA", rot, re.I)), "venda": len(re.findall(r"\[\[\s*VENDA", rot, re.I))}}


def _resultado_plano(d: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
    """✍️ O 1º prompt devolveu o PLANO (vídeo longo): guarda títulos, descrição etc. e as partes a escrever."""
    import roteiro_partes as rp
    _esc = __import__("metodo_roteiro").ler_escopo(d.get("escopo"))
    if isinstance(d.get("lore_registro"), dict) or _esc.get("fica_para_outro_video"):
        registrar_lore(p, d.get("lore_registro") or {}, _esc)  # 🎭 v84_173 (+ 🎯 os vídeos prometidos)
    _min, _alvo, _ppm = alvo_tamanho(p)
    partes = rp.de_plano(d.get("capitulos") or [], _alvo)
    if not partes:
        raise DossieError("O plano veio sem capítulos.")
    afirm = _afirmacoes(d.get("afirmacoes")) or [
        {"trecho": f["fato"][:300], "tipo": f["tipo"], "fonte": f.get("fonte") or ""} for pt in partes for f in pt["fatos"]][:80]
    return {"alvo": {"minutos": _min, "palavras": _alvo, "ppm": _ppm, "curto": False},
            "titulos": [str(x)[:150] for x in d.get("titulos") or [] if str(x).strip()][:10],
            "ideias": _ideias_com_escopo(d.get("ideias"), _esc),
            **({"escopo": _esc} if _esc else {}),
            "descricao": str(d.get("descricao") or "").strip()[:5000],
            "capitulos": [{"titulo": pt["titulo"], "comeca_em": ""} for pt in partes], "palavras": 0,
            "roteiro": "", "roteiro_final": "", "momentos": [],
            "tags": [str(x)[:60] for x in d.get("tags") or [] if str(x).strip()][:30],
            "fontes_usadas": [str(x)[:10] for x in d.get("fontes_usadas") or []][:30],
            "observacoes": str(d.get("observacoes") or "").strip()[:2000],
            "avisos": [f"✍️ Plano pronto: {len(partes)} capítulos (~{_alvo} palavras no total). Agora escreva as partes — "
                       "uma por vez, em texto puro (ou 🤖 todas com a IA)."],
            "gerado_em": time.time(), "produto_sugerido": _produto(d.get("produto_sugerido")),
            "plano": __import__("metodo_roteiro").ler_plano(d.get("plano")),
            "afirmacoes": afirm,
            "thumbnails": [t for t in (__import__("thumbs_flow").normalizar(x) for x in (d.get("thumbnails") or [])[:6]) if t],
            "partes": partes, "chamadas": {"inscreva": 0, "venda": 0},
            **({"lore_registro": d["lore_registro"]} if isinstance(d.get("lore_registro"), dict) else {})}


# ------------------------------------------------------------------ ✍️ roteiro em partes
def _contexto_partes(p: Dict[str, Any], base: Optional[str] = None) -> Dict[str, Any]:
    import canal
    import idiomas
    cfg = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    mod = MODELOS.get(cfg["modelo"]) or MODELOS["true_crime"]
    minutos, _alvo, _ppm = alvo_tamanho(p)
    vis = [m for m in p.get("midias") or [] if m["tipo"] in ("foto", "video") and not m.get("descartada") and not m.get("duplicada_de")]
    regras = list(mod["regras"])
    if (cfg.get("tom") or "").strip():
        regras.append(f"Tom: {cfg['tom'].strip()[:400]}")
    if (cfg.get("extra") or "").strip():
        regras.append(f"Pedido extra (siga com prioridade): {cfg['extra'].strip()[:1500]}")
    _perfil = perfil_do_modelo(cfg.get("modelo"))
    _pb = ""
    if _perfil:
        import canal_perfil
        _pb = canal_perfil.bloco_roteiro(_perfil, ia_emocao=cfg.get("ia_emocao", True) is not False, curto=True, n_hist=6)
    return {"personagens_bloco": _pb,
            "escopo": (p.get("resultado") or {}).get("escopo") or {}, "enxuto": escopo_enxuto(mod),  # 🎯 v84_178
            "idioma_cod": idiomas.normalizar(cfg.get("idioma")) or "pt",
            "referencia": (cfg.get("referencia") or "")[:9000] if cfg.get("referencia_modo") == "modelar" else "",
            "tema": (p.get("tema") or "").strip(), "promessa": titulo_promessa(p), "nome_modelo": sem_emoji(mod["nome"]), "minutos": minutos,
            "idioma": idiomas.nome_para_prompt(idiomas.normalizar(cfg.get("idioma")) or "pt"),
            "regras": regras, "canal": canal.nome_do_projeto(nome_canal_cfg(cfg)),
            "midias": {m["id"].upper(): o_que_e(m)[:300] for m in vis}, "plano": (p.get("resultado") or {}).get("plano") or {}}


def _fontes_texto(p: Dict[str, Any], limite: int = 60000) -> str:
    """As fontes, em texto (pra quando a IA do site escreve as partes numa conversa nova)."""
    L: List[str] = []
    for f in p.get("fontes") or []:
        if not f.get("texto"):
            continue
        L.append(f"### {f['id']} — {f.get('titulo') or f.get('url') or f.get('arquivo')}")
        if f.get("condensado"):
            import ia_dossies
            L.append(ia_dossies.condensado_para_prompt(f["condensado"]))
        else:
            L.append(f.get("texto") or "")
    for m in p.get("midias") or []:
        if m["tipo"] == "texto":
            L.append(f"### {m['id']}" + (f" — {m['descricao']}" if m.get("descricao") else "") + f"\n{m.get('conteudo') or ''}")
    if (p.get("roteiro_base") or "").strip():
        L.append("### Roteiro/anotações do autor (guia)\n" + p["roteiro_base"].strip()[:20000])
    t = "\n\n".join(L)
    return t[:limite]


def iniciar_completar(p: Dict[str, Any]) -> Dict[str, Any]:
    """📏 O roteiro ficou curto: corta em partes (nos capítulos) pra reescrever só as curtas."""
    import roteiro_partes as rp
    res = p.get("resultado") or {}
    if not res.get("roteiro"):
        raise DossieError("Ainda não tem roteiro.")
    minutos, alvo, _ppm = alvo_tamanho(p)
    if minutos <= 1:
        raise DossieError("Shorts não tem tamanho mínimo pra completar.")
    res["partes"] = rp.de_roteiro(res["roteiro"], res.get("capitulos") or [], alvo, rp.n_capitulos(minutos))
    return res


def prompt_parte(p: Dict[str, Any], k: int, com_fontes: bool = False) -> str:
    import roteiro_partes as rp
    partes = (p.get("resultado") or {}).get("partes") or []
    if not any(x["k"] == k for x in partes):
        raise DossieError("Parte não encontrada.")
    return rp.prompt_parte(_contexto_partes(p), partes, k, _fontes_texto(p) if com_fontes else "")


def salvar_parte(p: Dict[str, Any], k: int, texto: str) -> Dict[str, Any]:
    """Guarda o texto de uma parte; com todas prontas, monta o roteiro (marcas e capítulos) e refaz o resultado."""
    import roteiro_partes as rp
    res = p.get("resultado") or {}
    partes = res.get("partes") or []
    parte = next((x for x in partes if x["k"] == k), None)
    if not parte:
        raise DossieError("Parte não encontrada.")
    parte.pop("aceita_curta", None)
    try:
        parte["texto"] = rp.ler_parte(texto, parte)
    except ValueError as exc:
        raise DossieError(str(exc)) from exc
    parte["status"] = rp.status_de(parte)
    if any(not x.get("texto") for x in partes):
        res["avisos"] = [f"✍️ Partes escritas: {sum(1 for x in partes if x.get('texto'))} de {len(partes)}."]
        return res
    return montar_partes(p)


def montar_partes(p: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json
    import roteiro_partes as rp
    res = p.get("resultado") or {}
    partes = res.get("partes") or []
    cfg = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    _min, alvo, _ppm = alvo_tamanho(p)
    roteiro, caps = rp.montar(partes, cfg.get("marcar_chamadas", True) is not False, alvo,
                              max_inscreva=(_modelo_cfg(p).get("chamadas") or {}).get("inscreva"))  # 📣 v84_218
    d = {k: res.get(k) for k in ("titulos", "ideias", "descricao", "tags", "fontes_usadas", "observacoes", "produto_sugerido", "plano",
                                 "afirmacoes", "thumbnails", "lore_registro", "escopo")}
    d.update(roteiro=roteiro, capitulos=caps, momentos=[], partes=partes)
    novo = ler_resultado(_json.dumps(d, ensure_ascii=False), p)
    try:  # 🔁 v84_179: a mesma informação contada em duas partes (o plano deu o mesmo assunto a dois capítulos)
        import checagem_roteiro as _ch
        _fr = [r for r in _ch.frases_repetidas(novo.get("roteiro") or "") if r["b"] != r["a"]]
        if _fr:
            novo["avisos"].append("🔁 A mesma informação em partes diferentes: " + " · ".join(
                f"„{r['frase_a'][:60]}…“ × „{r['frase_b'][:60]}…“" for r in _fr[:3])
                + " — use a 🪄 revisão (ela recebe a lista) ou peça de novo a parte que repete.")
    except Exception:  # noqa: BLE001
        pass
    curtas = [x["k"] for x in partes if x.get("status") == "curta"]
    if curtas:
        novo["avisos"].append("✍️ Partes abaixo do tamanho: " + ", ".join(map(str, curtas)) + " — dá pra pedir de novo só elas.")
    longas = [x["k"] for x in partes if x.get("status") == "longa"]
    if longas:
        novo["avisos"].append("✍️ Partes bem acima do tamanho: " + ", ".join(map(str, longas)) + " — peça de novo só elas (o prompt "
                              "pede a versão enxuta) ou use a 🪄 revisão no modo ✂️ enxugar.")
    return novo


def _afirmacoes(x: Any) -> List[Dict[str, str]]:
    """🔎 Afirmações importantes do roteiro: fato documentado / alegação / interpretação + a fonte."""
    out = []
    for a in x if isinstance(x, list) else []:
        if not isinstance(a, dict) or not str(a.get("trecho") or "").strip():
            continue
        t = str(a.get("tipo") or "").strip().lower()
        t = "alegacao" if t.startswith(("aleg", "alleg", "claim")) else "interpretacao" if t.startswith("interp") else "fato"
        out.append({"trecho": str(a["trecho"]).strip()[:300], "tipo": t, "fonte": str(a.get("fonte") or "").strip()[:200]})
    return out[:80]


def _produto(x: Any) -> Optional[Dict[str, str]]:
    if isinstance(x, str) and x.strip():
        x = {"nome": x}
    if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
        return None
    return {k: str(x.get(k) or "").strip()[:lim] for k, lim in (("nome", 200), ("por_que", 800), ("busca", 200), ("chamada", 800))}


def prompt_completar(p: Dict[str, Any]) -> str:
    """📏 O roteiro ficou curto: prompt pra IA esticar até o tamanho (resposta só {"roteiro"})."""
    import idiomas
    import metodo_roteiro
    res = p.get("resultado") or {}
    if not res.get("roteiro"):
        raise DossieError("Ainda não tem roteiro.")
    minutos, alvo, _ppm = alvo_tamanho(p)
    if minutos <= 1:
        raise DossieError("Shorts não tem tamanho mínimo pra completar.")
    cfg = dict(CONFIG_PADRAO, **(p.get("config") or {}))
    return metodo_roteiro.prompt_completar(
        res["roteiro"], metodo_roteiro.palavras_do_texto(res.get("roteiro_final") or res["roteiro"]), alvo, minutos,
        [c.get("comeca_em") for c in res.get("capitulos") or [] if c.get("comeca_em")],
        idiomas.nome_para_prompt(idiomas.normalizar(cfg.get("idioma")) or "pt"))


def ler_resposta(texto: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """Resposta colada: o JSON completo do prompt do roteiro, OU só {"roteiro"} (resposta do 📏 completar) — nesse
    caso troca só o roteiro e mantém títulos, descrição, capítulos etc."""
    import json_ia
    try:
        d = json_ia.carregar(texto)
    except ValueError as exc:
        # texto puro (sem JSON) colado depois de já ter roteiro = o roteiro novo (ex.: resposta do 📏 completar)
        if (p.get("resultado") or {}).get("roteiro") and len(str(texto or "").split()) > 80 and "{" not in str(texto)[:5]:
            return roteiro_editado(p, str(texto).strip())
        raise DossieError(str(exc)) from exc
    if isinstance(d, list) and len(d) == 1 and isinstance(d[0], dict):
        d = d[0]
    so_roteiro = isinstance(d, dict) and str(d.get("roteiro") or "").strip() and \
        not any(d.get(k) for k in ("titulos", "descricao", "capitulos", "tags", "ideias"))
    if so_roteiro and (p.get("resultado") or {}).get("roteiro"):
        return roteiro_editado(p, str(d["roteiro"]))
    return ler_resultado(texto, p)


def roteiro_editado(p: Dict[str, Any], novo: str) -> Dict[str, Any]:
    """O roteiro mexido à mão (ex.: [[VENDA]] em outro lugar): refaz a voz, os momentos e as
    posições dos capítulos, mantendo títulos, descrição etc."""
    import json as _json
    res = p.get("resultado") or {}
    if not str(novo or "").strip():
        raise DossieError("O roteiro ficou vazio.")
    d = {k: res.get(k) for k in ("titulos", "ideias", "descricao", "tags", "fontes_usadas", "observacoes", "produto_sugerido", "plano",
                                 "afirmacoes", "thumbnails", "lore_registro", "escopo")}
    d["capitulos"] = [{"titulo": c["titulo"], "comeca_em": c.get("comeca_em")} for c in res.get("capitulos") or []]
    d["momentos"] = [m for m in res.get("momentos") or [] if not m.get("inicio")]
    d["roteiro"] = novo
    return ler_resultado(_json.dumps(d, ensure_ascii=False), p)


def aplicar_padroes_do_modelo(cfg: Dict[str, Any], modelo: str) -> None:
    """Modelo de canal: o roteiro exemplo do pacote entra no 📐 (se você ainda não pôs outro) e o nome do canal."""
    mod = MODELOS.get(modelo or "") or {}
    if mod.get("referencia_padrao") and not str(cfg.get("referencia") or "").strip():
        cfg["referencia"] = mod["referencia_padrao"]
        cfg["referencia_modo"] = mod.get("referencia_modo_padrao") or "modelar"
    if canal_do_modelo(modelo) and not str(cfg.get("nome_canal") or "").strip():
        cfg["nome_canal"] = canal_do_modelo(modelo)
    if mod.get("perfil_canal") and not cfg.get("vozes_personagens"):
        cfg["vozes_personagens"] = vozes_lembradas(modelo)


def _arq_vozes(modelo: str) -> Optional[str]:
    slug = (MODELOS.get(modelo or "") or {}).get("perfil_canal")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "marcas", slug, "vozes_escolhidas.json") if slug else None


def lembrar_vozes(modelo: str, vozes: Dict[str, Any]) -> None:
    cam = _arq_vozes(modelo)
    if cam and os.path.isdir(os.path.dirname(cam)):
        try:
            with open(cam, "w", encoding="utf-8") as f:
                json.dump(vozes, f, ensure_ascii=False, indent=1)
        except OSError:
            pass


def vozes_lembradas(modelo: str) -> Dict[str, Any]:
    cam = _arq_vozes(modelo)
    try:
        with open(cam, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _modelo_cfg(p: Dict[str, Any]) -> Dict[str, Any]:
    return MODELOS.get(str((p.get("config") or {}).get("modelo") or "")) or {}


def perfil_do_modelo(modelo: Any) -> Optional[Dict[str, Any]]:
    """🎭 v84_173: o perfil do canal (personagens, lore…) do modelo que veio de um pacote com personagens.json."""
    slug = (MODELOS.get(str(modelo or "")) or {}).get("perfil_canal")
    if not slug:
        return None
    try:
        import canal_perfil
        return canal_perfil.carregar(os.path.dirname(os.path.abspath(__file__)), slug)
    except Exception:  # noqa: BLE001
        return None


def registrar_lore(p: Dict[str, Any], registro: Any, escopo: Optional[Dict[str, Any]] = None) -> None:
    """O "lore_registro" do roteiro entra no histórico do canal (e as pistas mudam de estado). 🎯 v84_178: os assuntos
    que o vídeo deixou "pra outro vídeo" ficam anotados no episódio (o canal lembra o que prometeu)."""
    slug = (MODELOS.get((p.get("config") or {}).get("modelo") or "") or {}).get("perfil_canal")
    if not slug or not isinstance(registro, dict):
        return
    if escopo and escopo.get("fica_para_outro_video"):
        registro = dict(registro, proximos_videos=list(escopo["fica_para_outro_video"]))
    try:
        import canal_perfil
        canal_perfil.registrar_episodio(os.path.dirname(os.path.abspath(__file__)), slug, p.get("id") or "",
                                        titulo_promessa(p) or p.get("tema") or "", registro)
    except Exception:  # noqa: BLE001
        pass


def escopo_enxuto(mod: Dict[str, Any]) -> bool:
    """🎯 v84_178: vídeo EXPLICATIVO (ciência, canal com personagens): plano com menos fatos por capítulo e sem dizer a fonte
    em voz alta. O true crime e os outros documentários continuam densos. O pacote pode forçar com "escopo_enxuto"."""
    mod = mod or {}
    if "escopo_enxuto" in mod:
        return bool(mod["escopo_enxuto"])
    return bool(mod.get("perfil_canal")) or mod is MODELOS.get("ciencia")


def _ideias_com_escopo(ideias: Any, escopo: Dict[str, Any]) -> List[str]:
    out = [str(x)[:300] for x in ideias or [] if str(x).strip()][:15]
    for t in (escopo or {}).get("fica_para_outro_video") or []:
        item = f"🎬 Próximo vídeo (ficou de fora deste): {t}"
        if item not in out:
            out.append(item)
    return out[:25]


def sem_emoji(nome: str) -> str:
    """"🕵️ True Crime" → "True Crime" (e nomes sem emoji, de pacotes, ficam como estão)."""
    nome = str(nome or "").strip()
    primeiro, _, resto = nome.partition(" ")
    return resto if resto and not any(ch.isalnum() for ch in primeiro) else nome


def titulo_promessa(p: Dict[str, Any]) -> str:
    """🧵 v84_169: o título do vídeo (a promessa) — o campo próprio ou, vazio, o tema."""
    cfg = p.get("config") or {}
    return " ".join(str(cfg.get("titulo") or p.get("tema") or "").split())[:200]


def canal_do_modelo(modelo: str) -> str:
    """🎨 v84_168: o modelo ligado a uma identidade visual fala SEMPRE o nome do canal da marca (ex.: Dinge erklären)."""
    mod = MODELOS.get(modelo or "") or {}
    if mod.get("nome_canal"):
        return str(mod["nome_canal"])
    slug = mod.get("identidade_visual")
    if slug:
        try:
            import marca_visual
            return str((marca_visual.carregar(os.path.dirname(os.path.abspath(__file__)), slug)["guia"].get("project") or {}).get("name") or "")
        except Exception:  # noqa: BLE001
            return ""
    return ""


def nome_canal_cfg(cfg: Dict[str, Any]) -> str:
    """O nome do canal do projeto; vazio = o do modelo (canal da marca) e, sem ele, o das Configurações."""
    v = str(cfg.get("nome_canal") or "").strip()
    return v or canal_do_modelo(cfg.get("modelo") or "")


def roteiro_para_voz(p: Dict[str, Any]) -> str:
    return ((p.get("resultado") or {}).get("roteiro_final") or "").strip()


def parecido(texto: str, candidatos: List[Tuple[str, str]]) -> Optional[str]:
    """O texto é (quase) igual a qual roteiro? candidatos = [(id, roteiro)] → id, ou None.
    Compara os pares de palavras do começo e o tamanho (edições pequenas não atrapalham)."""
    import roteiros_yt
    alvo = roteiros_yt._toks(texto or "")
    if len(alvo) < 40:
        return None
    ini, n = set(zip(alvo[:200], alvo[1:201])), len(alvo)
    melhor, nota_m = None, 0.0
    for pid, rot in candidatos:
        tk = roteiros_yt._toks(rot or "")
        if not tk or not 0.7 <= n / len(tk) <= 1.4:
            continue
        pares = set(zip(tk[:200], tk[1:201]))
        nota = len(ini & pares) / max(1, min(len(ini), len(pares)))
        if nota > nota_m:
            melhor, nota_m = pid, nota
    return melhor if nota_m >= 0.6 else None


def achar_pelo_texto(base: str, texto: str) -> Optional[str]:
    """📑 O texto mandado pro Gerador de voz é o roteiro de algum modelo de vídeo? (colado à mão, sem
    vir do botão "Gerar voz com este roteiro") → id do projeto, pra os capítulos ganharem o tempo do áudio."""
    cands = []
    for it in listar(base):
        if not it.get("tem_roteiro"):
            continue
        try:
            p = carregar(base, it["id"])
        except Exception:  # noqa: BLE001
            continue
        if (p.get("resultado") or {}).get("capitulos"):
            cands.append((p["id"], roteiro_para_voz(p)))
    return parecido(texto, cands)


def achar_roteiro_yt_pelo_texto(base: str, texto: str) -> Optional[str]:
    """Igual, pros projetos do 📝 Roteiro do YouTube."""
    import roteiros_yt
    cands = []
    for it in roteiros_yt.listar_projetos(base):
        try:
            p = roteiros_yt.carregar_projeto(base, it["id"])
        except Exception:  # noqa: BLE001
            continue
        if (p.get("resultado") or {}).get("capitulos"):
            cands.append((it["id"], roteiros_yt.roteiro_para_voz(p)))
    return parecido(texto, cands)


def descricao_completa(p: Dict[str, Any]) -> str:
    """Descrição + capítulos (0:00 …) + fontes, pronta pro YouTube."""
    import roteiros_yt
    res = p.get("resultado") or {}
    cv = res.get("capitulos_video") or {}
    if cv.get("capitulos"):  # 📑 já tem vídeo montado: os tempos do VÍDEO FINAL (com as chamadas/cortes)
        import capitulos_video
        txt = "\n\n".join(x for x in (res.get("descricao") or "", capitulos_video.linhas(cv["capitulos"], cv.get("duracao"))) if x).strip()
    else:
        txt = roteiros_yt.descricao_com_capitulos(res)
    usadas = set(res.get("fontes_usadas") or [])
    fontes = [f for f in p.get("fontes") or [] if f.get("titulo") and (not usadas or f["id"] in usadas)]
    if fontes:
        txt += "\n\nFontes:\n" + "\n".join(f"- {f['titulo']}" + (f" ({f.get('site') or ''}): {f['url']}" if f.get("url") else "")
                                             for f in fontes)
    return txt.strip()


def aplicar_tempos_do_audio(base: str, pid: str, palavras: List[Dict[str, Any]], duracao: Optional[float], origem: str = "") -> Optional[Dict[str, Any]]:
    """Depois de gerar a voz: o tempo REAL de cada capítulo no áudio."""
    import roteiros_yt
    p = carregar(base, pid)
    res = p.get("resultado") or {}
    if not res.get("capitulos"):
        return None
    res["capitulos"] = roteiros_yt.capitulos_pelo_audio({"resultado": res}, palavras, duracao)
    res.pop("capitulos_video", None)  # áudio novo: o vídeo antigo não vale mais
    res["audio"] = {"duracao": round(duracao, 1) if duracao else None, "gerado_em": time.time(), "origem": origem,
                    "com_palavras": bool(palavras)}
    p["resultado"] = res
    salvar(base, p)
    return res


# ------------------------------------------------------------------ editor
def midias_para_editor(base: str, p: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []  # mesma forma da venda (vendas.linhas_editor)
    momentos = (p.get("resultado") or {}).get("momentos") or []
    import midia_transcricao as mt
    for m in p.get("midias") or []:
        cam = caminho_midia(base, p, m)
        tipo = _vd.tipo_do_arquivo(cam or "")
        if not cam or not tipo:
            continue
        usos = [mo for mo in momentos if mo.get("midia") == m["id"]]
        out.append({"id": m["id"], "tipo": tipo, "caminho": cam, "o_que_e": o_que_e(m), "usos": usos,
                    "trecho": (usos[0] if usos else {}).get("trecho") or "", "texto_na_tela": "",
                    "transcricao": mt.para_prompt(cam) if tipo == "video" else ""})
    return out


def bloco_prompt_editor(base: str, p: Dict[str, Any]) -> str:
    ms = midias_para_editor(base, p)
    if not ms:
        return ""
    no_roteiro = [m for m in ms if m["trecho"]]
    outras = [m for m in ms if not m["trecho"]]
    L = ["", f"## 🕵️ Imagens e vídeos do TEMA (projeto “{nome_do_projeto(p)}”) — use primeiro!",
         "Estas são fotos e vídeos REAIS do tema (das matérias e dos meus arquivos). Nos trechos em que a narração fala de uma "
         "pessoa, lugar, objeto ou documento que uma delas mostra, use-a com `\"provider\": \"material\"` e `\"query\": \"<ID>\"` "
         "(ex.: `{\"start\": 12.0, \"end\": 16.5, \"provider\": \"material\", \"query\": \"I4\"}`) — sem \"alternativas\". "
         "Cada \"trecho sugerido\" é um ponto em que o roteiro planejou a imagem: ache CADA um na transcrição e use a imagem "
         "ali (a mesma imagem aparece em vários pontos — use em todos). Além deles, use de novo toda vez que a narração "
         "voltar a falar daquela pessoa/lugar/objeto (alterne entre as fotos da mesma pessoa; pelo menos ~10 s entre dois "
         "usos da mesma foto). Nenhuma imagem útil fica de fora. Prefira essas imagens sempre que combinarem; nos outros trechos, use os bancos normais pra clima (cidade à noite, fita de isolamento, "
         "documentos, viatura) — nunca uma pessoa de banco de imagem no lugar de uma pessoa real do caso."]
    L.extend(_vd.linhas_editor(no_roteiro + outras[:150]))
    return "\n".join(L)
