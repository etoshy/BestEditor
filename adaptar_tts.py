"""
🎙 adaptar_tts.py — ADAPTAR O ROTEIRO PRO TTS, por idioma (v84_96)
=================================================================

Depois que o roteiro está pronto (🕵️ Modelos de vídeo ou 📜 Roteiro do YouTube), um prompt prepara o texto pra
síntese de voz no idioma dele: frases naturais pra ouvir, pontuação que dá as pausas, números/datas/siglas do jeito
que se fala, nada que o TTS leia em voz alta por engano — SEM mudar fatos nem encurtar. Cada idioma tem as suas
regras (o alemão é o primeiro com regras próprias; os outros usam o modelo geral até ganharem o deles) e a DIREÇÃO
NARRATIVA muda com o tipo de vídeo (true crime, história, biografia, mistério…).

As marcas do site ficam onde estão: [[INSCREVA]], [[VENDA]], [I3]/[M2] (mídia), [CENA n] e as tags de voz.

A resposta é SÓ o texto (não JSON). ler_resposta() limpa, confere as marcas e o tamanho; quem chama guarda o anterior
pra ↩ desfazer.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------ direção narrativa (seção 4) por tipo de vídeo
DIRECOES: Dict[str, Dict[str, Any]] = {
    "true_crime": {
        "nome": "🕵️ True crime (documentário criminal)",
        "tom": "um documentário criminal profissional: sóbrio, investigativo, envolvente e controlado",
        "partes": [
            ("Abertura e gancho", "Comece com frases diretas, claras e impactantes. Revele informações na ordem original, sem inventar "
                                  "suspense nem antecipar fatos que o roteiro ainda não apresentou."),
            ("Contexto e investigação", "Utilize um ritmo estável e informativo. Torne claras as relações entre pessoas, acontecimentos, "
                                        "evidências e cronologia."),
            ("Revelações importantes", "Isole informações decisivas em frases próprias quando isso melhorar a compreensão e o impacto "
                                       "narrativo. Use pausas naturais antes ou depois de uma revelação, sem exagerar nas reticências."),
            ("Momentos tensos", "Prefira frases mais controladas, com estrutura simples e vocabulário preciso. Não transforme toda "
                                "informação em uma revelação dramática."),
            ("Conclusão", "Reduza gradualmente a intensidade textual. Favoreça frases reflexivas, claras e naturais, sem inserir "
                          "moralizações ou conclusões que não existam no original."),
        ],
        "conferir": "A narração mantém o tom sóbrio, investigativo e cinematográfico",
    },
    "historia": {
        "nome": "📜 História (documentário histórico)",
        "tom": "um documentário histórico profissional: claro, imersivo, com senso de época e sem pompa",
        "partes": [
            ("Abertura e gancho", "Frases diretas que coloquem o ouvinte no momento histórico, sem antecipar o desfecho."),
            ("Contexto", "Ritmo estável e explicativo: época, lugar e o que estava em jogo, com as relações de causa bem claras."),
            ("Acontecimentos e viradas", "Cada virada em frases próprias; datas e nomes espaçados para o ouvinte acompanhar a cronologia."),
            ("Clímax", "Frases mais curtas e controladas, vocabulário concreto; sem dramatizar além do que as fontes sustentam."),
            ("Consequências e conclusão", "Desacelere: frases reflexivas sobre o legado, sem acrescentar juízos que não estão no original."),
        ],
        "conferir": "A narração soa como um documentário histórico claro e imersivo",
    },
    "biografia": {
        "nome": "👤 Biografia",
        "tom": "uma biografia documental: próxima, humana, respeitosa e bem ritmada",
        "partes": [
            ("Abertura", "Apresente o momento-chave da vida da pessoa com frases claras, sem entregar o fim."),
            ("Origem e trajetória", "Ritmo de relato: uma etapa da vida por parágrafo, com as datas e lugares fáceis de acompanhar."),
            ("Conquistas e crises", "Isole as viradas em frases próprias; acusações e polêmicas sempre atribuídas, nunca como fato."),
            ("Legado", "Reduza a intensidade; frases calmas e reflexivas, sem elogio ou julgamento que não esteja no original."),
        ],
        "conferir": "A narração é humana, clara e respeitosa com a pessoa retratada",
    },
    "misterio": {
        "nome": "👽 Mistério / internet / rabbit hole",
        "tom": "um documentário de mistério: curioso, intrigante, com suspense contido e sem sensacionalismo",
        "partes": [
            ("Abertura", "Comece pelo detalhe mais estranho em frases curtas e concretas, sem prometer respostas que o texto não dá."),
            ("O que se sabe", "Ritmo estável; separe com clareza o que é confirmado do que é relato, boato ou teoria."),
            ("Pistas e teorias", "Uma pista ou teoria por bloco; cada teoria atribuída a quem a defende."),
            ("Fechamento", "Desacelere e deixe a pergunta em aberto com naturalidade, sem dramatizar."),
        ],
        "conferir": "O suspense vem da ordem das informações, não de exageros",
    },
    "documentario": {
        "nome": "🎞 Documentário geral (negócios, ciência, desastres)",
        "tom": "um documentário profissional: claro, envolvente, preciso e bem ritmado",
        "partes": [
            ("Abertura", "Frases diretas que confirmem a promessa do vídeo logo no começo."),
            ("Explicação", "Ritmo estável; do contexto ao detalhe, um conceito por frase, números espaçados."),
            ("Viradas", "Isole as informações decisivas em frases próprias, com pausas naturais."),
            ("Conclusão", "Reduza a intensidade; frases claras sobre o resultado, sem conclusões novas."),
        ],
        "conferir": "A narração é clara e envolvente do começo ao fim",
    },
}
# 🕵️ modelo de vídeo -> direção
DIRECAO_DO_MODELO = {"true_crime": "true_crime", "historia": "historia", "biografia": "biografia", "desastres": "documentario",
                     "misterios": "misterio", "rabbit_holes": "misterio", "exposicao_internet": "misterio",
                     "negocios": "documentario", "ciencia": "documentario"}

# ------------------------------------------------------------------ regras por idioma
# "especifico": True = regras escritas pra esse idioma. Os outros usam o modelo GERAL (com o nome do idioma).
IDIOMAS: Dict[str, Dict[str, Any]] = {
    "de": {
        "nome": "alemão", "especifico": True,
        "natural": [
            "Reescreva as frases para que soem naturais quando pronunciadas por um narrador profissional alemão.",
            "Priorize o alemão padrão contemporâneo (Hochdeutsch), com construções idiomáticas e vocabulário apropriado para "
            "documentários {genero}.",
        ],
        "evite": ["Frases excessivamente longas com várias orações subordinadas.",
                  "Construções que funcionem bem na escrita, mas soem artificiais em voz alta.",
                  "Traduções literais de expressões estrangeiras.",
                  "Sequências de substantivos compostos difíceis de compreender auditivamente.",
                  "Repetições desnecessárias, aliterações involuntárias e frases com ritmo mecânico."],
        "ortografia": "Preserve a ortografia alemã, incluindo ä, ö, ü e ß.",
        "numeros": "Prepare números e expressões para uma leitura alemã correta.",
        "datas": "Utilize a forma falada natural em alemão para datas e horários.",
        "siglas": "Se uma sigla for normalmente pronunciada como palavra em alemão, preserve essa convenção; se for soletrada, "
                  "use uma representação textual clara quando necessário.",
        "ouvintes": "Compreensão imediata por ouvintes nativos de alemão.",
    },
}


def _idioma_geral(cod: str) -> Dict[str, Any]:
    import idiomas
    nome = idiomas.nome_para_prompt(cod) if cod else "o idioma do roteiro"
    return {
        "nome": nome, "especifico": False,
        "natural": [f"Reescreva as frases para que soem naturais quando pronunciadas por um narrador profissional nativo ({nome}).",
                    "Priorize a norma padrão contemporânea do idioma, com construções idiomáticas e vocabulário apropriado para "
                    "documentários {genero}."],
        "evite": ["Frases excessivamente longas com várias orações subordinadas.",
                  "Construções que funcionem bem na escrita, mas soem artificiais em voz alta.",
                  "Traduções literais de expressões estrangeiras.",
                  "Acúmulo de substantivos e termos técnicos difíceis de compreender auditivamente.",
                  "Repetições desnecessárias, aliterações involuntárias e frases com ritmo mecânico."],
        "ortografia": "Preserve a ortografia do idioma, incluindo acentos e letras especiais.",
        "numeros": f"Prepare números e expressões para uma leitura correta em {nome}.",
        "datas": f"Utilize a forma falada natural em {nome} para datas e horários.",
        "siglas": "Se uma sigla for normalmente pronunciada como palavra, preserve essa convenção; se for soletrada, use uma "
                  "representação textual clara quando necessário.",
        "ouvintes": f"Compreensão imediata por ouvintes nativos ({nome}).",
    }


def regras_do_idioma(cod: str) -> Dict[str, Any]:
    cod = (cod or "").lower()[:2]
    return IDIOMAS.get(cod) or _idioma_geral(cod)


def idiomas_especificos() -> List[str]:
    return [k for k, v in IDIOMAS.items() if v.get("especifico")]


MOTORES = {"chatterbox": "Chatterbox TTS", "chatterbox_turbo": "Chatterbox Turbo", "xtts": "XTTS", "fish": "Fish Audio S2",
           "kokoro": "Kokoro", "piper": "Piper", "": "o gerador de voz (TTS)"}

_GENERO = {"true_crime": "investigativos", "historia": "históricos", "biografia": "biográficos", "misterio": "de mistério",
           "documentario": "informativos"}


# ------------------------------------------------------------------ o prompt
def prompt(texto: str, idioma: str, direcao: str = "true_crime", canal: str = "", motor: str = "chatterbox",
           inicios_capitulos: Optional[List[str]] = None) -> str:
    """O prompt de adaptação pro TTS (com o roteiro no fim). A resposta esperada é SÓ o texto adaptado."""
    texto = str(texto or "").strip()
    if not texto:
        raise ValueError("Ainda não tem roteiro pra adaptar.")
    R = regras_do_idioma(idioma)
    D = DIRECOES.get(direcao) or DIRECOES["documentario"]
    lingua = R["nome"]
    nome_motor = MOTORES.get(motor, MOTORES[""])
    genero = _GENERO.get(direcao, "informativos")
    canal = " ".join(str(canal or "").split())[:80]
    titulo = "SISTEMA DE ADAPTAÇÃO DE ROTEIROS PARA TTS" + (f" — {canal.upper()}" if canal else "")
    tags_ok = motor == "chatterbox_turbo"
    L: List[str] = [f"# {titulo}", "", "## FUNÇÃO", "",
                    f"Você é um especialista em direção de voz, preparação de roteiros para síntese de fala e narrativa documental "
                    f"({D['nome'].split(' ', 1)[1]}) em {lingua}.", "",
                    f"Sua tarefa é transformar o roteiro em {lingua} fornecido em uma versão otimizada para narração pelo {nome_motor}, "
                    "priorizando naturalidade, clareza, ritmo, suspense e pronúncia correta.", "",
                    "O resultado será utilizado diretamente como entrada de um sistema de síntese de voz. Portanto, você deve entregar "
                    "exclusivamente o roteiro final preparado para TTS, sem explicações, comentários, introduções ou relatórios.", "",
                    "## 1. PRESERVAÇÃO DO CONTEÚDO", "",
                    "- Preserve integralmente os fatos, nomes, datas, locais, números, citações, argumentos e conclusões do roteiro original.",
                    "- Não invente informações, não acrescente acontecimentos e não altere o significado de nenhuma afirmação.",
                    "- Não elimine informações relevantes apenas para encurtar o texto.",
                    "- Não transforme suspeitas em fatos comprovados.",
                    "- Preserve a distinção entre fatos confirmados, alegações, hipóteses e informações desconhecidas.",
                    f"- Não traduza o roteiro para outro idioma. O texto de entrada já está em {lingua} e a saída deve continuar em {lingua}.",
                    "- Corrija erros gramaticais evidentes e formulações pouco naturais somente quando o sentido original permanecer intacto.",
                    "", f"## 2. {lingua.upper()} NATURAL PARA NARRAÇÃO", ""]
    L += [x.replace("{genero}", genero) for x in R["natural"]]
    L += ["", "Evite:", ""] + [f"- {x}" for x in R["evite"]]
    L += ["", "Divida períodos longos em unidades de sentido menores, preservando a relação lógica entre as informações.", "",
          "Não simplifique excessivamente o vocabulário nem transforme a narração em linguagem infantil.", "",
          "## 3. PONTUAÇÃO E PAUSAS", ""]
    if tags_ok:
        L.append("Este motor aceita as TAGS DE VOZ do Chatterbox Turbo que já estão no texto (ex.: [whispering], [sigh]): mantenha-as "
                 "onde estão; fora delas, a interpretação vem da construção do texto e da pontuação.")
    else:
        L.append(f"O {nome_motor} não utiliza tags explícitas de emoção neste fluxo. Portanto, a interpretação deve ser orientada "
                 "principalmente pela construção do texto e pela pontuação.")
    L += ["", "Use:", "",
          "- Vírgulas para pausas curtas e relações naturais entre orações.",
          "- Pontos finais para separar ideias completas e permitir pausas mais claras.",
          "- Parágrafos curtos para separar unidades narrativas.",
          "- Reticências apenas em momentos excepcionais de suspense, quando houver uma interrupção deliberada do pensamento.", "",
          "Não utilize reticências em todas as frases, não fragmente excessivamente o texto e não introduza quebras de linha sem "
          "finalidade narrativa.", ""]
    if not tags_ok:
        L += ["Evite escrever indicações como [pausa], [sussurrando], [dramático], [voz grave] ou instruções semelhantes. Elas podem "
              "ser pronunciadas literalmente pelo TTS ou não produzir efeito algum.", ""]
    L += [f"Não use letras maiúsculas para forçar ênfase. {R['ortografia']}", "",
          "## 4. DIREÇÃO NARRATIVA", "",
          f"A narração deve lembrar {D['tom']}.", "",
          "Adapte o ritmo textual conforme a função de cada trecho.", ""]
    for nome, regra in D["partes"]:
        L += [f"### {nome}", "", regra, ""]
    L += ["## 5. NÚMEROS, DATAS, HORÁRIOS E ABREVIATURAS", "", R["numeros"], "",
          "- Escreva por extenso números, datas, horários, quantidades e valores monetários quando isso melhorar a pronúncia e não "
          "prejudicar a compreensão.",
          f"- {R['datas']}",
          "- Preserve números de processos, códigos, identificadores e outras sequências que precisem ser reproduzidas literalmente.",
          "- Expanda abreviaturas quando a forma por extenso for a maneira natural de pronunciá-las.",
          "- Evite alterar números que tenham relevância documental ou jurídica.",
          "- Preserve a distinção entre datas, intervalos de tempo, idades e quantidades.", "",
          "Antes de modificar qualquer expressão numérica, confirme que sua leitura por extenso conserva exatamente o significado original.",
          "", "## 6. NOMES PRÓPRIOS E TERMOS ESTRANGEIROS", "",
          "Preserve a grafia correta de nomes de pessoas, cidades, organizações, instituições e locais.", "",
          "Não invente pronúncias para nomes desconhecidos e não substitua nomes próprios por aproximações fonéticas no texto principal.", "",
          f"Mantenha termos estrangeiros, títulos e nomes de instituições na forma apropriada. {R['siglas']}", "",
          "Não adicione explicações fonéticas entre parênteses, a menos que elas façam parte indispensável do conteúdo original.", "",
          f"## 7. OTIMIZAÇÃO PARA A VOZ DO {nome_motor.upper()}", "",
          "O objetivo é obter uma voz documental natural, e não uma interpretação teatral.", "",
          "Prepare o texto para favorecer:", "",
          "- Articulação clara.", "- Velocidade de fala estável.", "- Pausas naturais entre ideias.",
          "- Ênfase discreta nas informações importantes.", "- Variação de ritmo sem mudanças emocionais artificiais.",
          "- Fluidez em frases longas e curtas.", f"- {R['ouvintes']}", "",
          "Evite estruturas que provoquem aceleração involuntária, como frases muito extensas separadas apenas por vírgulas.", "",
          "Não tente imitar emoções por meio de pontuação excessiva. O suspense deve surgir da narrativa, da ordem das informações e "
          "das pausas naturais.", "",
          "Não reduza o conteúdo apenas para acelerar a narração. Preserve a duração aproximada do roteiro original, admitindo somente "
          "as variações naturais provocadas pela reformulação textual.", "",
          "## 8. FORMATAÇÃO DA SAÍDA", "",
          f"Entregue exclusivamente o roteiro final em {lingua}, pronto para ser copiado diretamente no {nome_motor}.", "",
          "- Preserve os parágrafos que correspondam a unidades narrativas.",
          "- Não inclua títulos técnicos, notas de edição, instruções de voz ou comentários externos.",
          "- Remova marcações de produção, indicações de câmera, timestamps e instruções visuais que não devam ser pronunciadas — "
          "EXCETO as marcas do site da seção 8.1.",
          "- Preserve diálogos e citações relevantes, adaptando apenas a pontuação necessária para uma leitura natural.",
          "- Não inclua Markdown, listas explicativas ou blocos de código.",
          "- Não acrescente uma saudação ou uma frase de encerramento que não existia no roteiro original.", "",
          "### 8.1 MARCAS DO SITE — mantenha EXATAMENTE como estão, no mesmo ponto da história", "",
          "Estas marcas não são lidas pelo TTS (o site tira antes de narrar) e controlam a edição do vídeo. Não traduza, não "
          "reescreva, não junte e não apague nenhuma delas:", "",
          "- [[INSCREVA]] e [[VENDA]] — sempre sozinhas numa linha, com uma linha em branco antes e depois;",
          "- marcas de mídia como [I3], [M2], [T1] — logo antes da frase em que a imagem aparece;",
          "- marcas de cena como [CENA 4];"]
    if tags_ok:
        L.append("- tags de voz do Chatterbox Turbo (ex.: [whispering], [sigh]).")
    if inicios_capitulos:
        L += ["", "Mantenha também EXATAMENTE estas frases de começo de capítulo (o site usa pra achar os capítulos): "
              + "; ".join(f"“{c}”" for c in inicios_capitulos if c) + "."]
    n = 1
    L += ["", "## 9. REVISÃO FINAL OBRIGATÓRIA", "",
          "Antes de entregar o resultado, revise silenciosamente o roteiro inteiro e verifique:", ""]
    for item in ["Todos os fatos e detalhes relevantes foram preservados.",
                 f"O {lingua} soa natural quando lido em voz alta.",
                 "A pontuação favorece pausas e ritmo naturais.",
                 "Datas, números, nomes e abreviaturas podem ser pronunciados corretamente.",
                 "Não existem tags de emoção, instruções técnicas ou comentários que possam ser lidos pelo TTS." if not tags_ok else
                 "Não existem instruções técnicas ou comentários que possam ser lidos pelo TTS (as tags de voz da lista ficam).",
                 "O texto não contém repetições introduzidas durante a adaptação.",
                 f"{D['conferir']}" + (f" de {canal}." if canal else "."),
                 "Todas as marcas do site (seção 8.1) continuam no texto, nos mesmos pontos.",
                 "O texto final está pronto para síntese, sem necessidade de limpeza manual."]:
        L.append(f"{n}. {item}")
        n += 1
    L += ["", "Se uma formulação original for ambígua, preserve o significado mais fielmente sustentado pelo contexto. Não invente uma "
          "solução factual para eliminar uma ambiguidade.", "",
          "## ENTRADA", "", f"A seguir, o roteiro original em {lingua}. Adapte-o integralmente segundo todas as regras anteriores.", "",
          "<<<ROTEIRO", texto, "ROTEIRO>>>", "",
          "## SAÍDA", "", f"Somente o roteiro final em {lingua}, otimizado para o {nome_motor} — TEXTO PURO (sem JSON, sem ``` "
          "em volta, sem título e sem comentário antes ou depois), do começo ao fim, sem cortar nada."]
    return "\n".join(L)


# ------------------------------------------------------------------ a resposta
_MIDIA = re.compile(r"\[\s*([MIT]\d+)\s*\]", re.I)
_CENA = re.compile(r"\[\s*cena\s*(\d+)[^\]]*\]", re.I)


def marcas(texto: str) -> Dict[str, Any]:
    import chamadas
    n = {"inscreva": 0, "venda": 0}
    for p in chamadas.dividir(texto or ""):
        if p["tipo"] in n:
            n[p["tipo"]] += 1
    return {**n, "midias": sorted({m.upper() for m in _MIDIA.findall(texto or "")}),
            "cenas": sorted({int(c) for c in _CENA.findall(texto or "")})}


def palavras(texto: str) -> int:
    return len(re.sub(r"\[\[[^\]]*\]\]|\[[^\]]*\]", " ", str(texto or "")).split())


def ler_resposta(resposta: str, original: str) -> Dict[str, Any]:
    """O texto adaptado (limpo) + avisos (marca que sumiu, texto que encolheu)."""
    t = str(resposta or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*\n|\n?```\s*$", "", t).strip()
    if t.startswith("{"):
        try:
            d = json.loads(t)
            if isinstance(d, dict):  # v84_99: qualquer chave — fica o maior texto do JSON
                strs = [v for v in d.values() if isinstance(v, str)]
                t = str(d.get("roteiro") or d.get("roteiro_final") or d.get("texto") or (max(strs, key=len) if strs else "")).strip()
        except ValueError:
            pass
    t = t.replace("<<<ROTEIRO", "").replace("ROTEIRO>>>", "").strip()
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if not t:
        raise ValueError("A resposta está vazia — cole o texto que a IA devolveu.")
    avisos: List[str] = []
    a, b = marcas(original), marcas(t)
    for k, nome in (("inscreva", "[[INSCREVA]]"), ("venda", "[[VENDA]]")):
        if b[k] < a[k]:
            avisos.append(f"Sumiram {a[k] - b[k]} marca(s) {nome} — confira antes de gerar a voz.")
    faltam = [m for m in a["midias"] if m not in b["midias"]]
    if faltam:
        avisos.append("Marcas de mídia que sumiram: " + ", ".join(f"[{m}]" for m in faltam) + " (essas imagens não entram no vídeo).")
    faltam_c = [c for c in a["cenas"] if c not in b["cenas"]]
    if faltam_c:
        avisos.append("Marcas de cena que sumiram: " + ", ".join(f"[CENA {c}]" for c in faltam_c) + ".")
    pa, pb = palavras(original), palavras(t)
    if pa and pb < pa * 0.85:
        avisos.append(f"O texto encolheu: {pa} → {pb} palavras ({100 * pb // pa}%). A adaptação não devia encurtar — confira se "
                      "nada importante sumiu.")
    sobras = sorted({x for x in re.findall(r"\[([^\[\]\n]{2,30})\]", re.sub(r"\[\[[^\]]*\]\]", " ", t))
                     if not re.fullmatch(r"[MIT]\d+|cena \d+.*", x.strip(), re.I)})
    return {"texto": t, "avisos": avisos, "palavras_antes": pa, "palavras_depois": pb, "colchetes": sobras}
