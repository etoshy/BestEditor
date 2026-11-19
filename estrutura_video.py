"""🎲 v84_433 — VARIAR A ESTRUTURA de um vídeo pro outro, sem perder a clareza.

O YouTube (conteúdo "não autêntico", jul/2026) desconfia de canal em que todo vídeo tem a mesma fórmula. A identidade fica
(tom, clareza, voz, a assinatura do canal); o que muda de um vídeo pro outro é:
  • a ABERTURA (cena "imagine…", pergunta direta, caso real, frase histórica, paradoxo, a crença comum…)
  • o ARCO do meio (tese → provas → objeção; a pergunta com respostas erradas antes da certa; dois pensadores; …)
  • o FECHO e a CHAMADA pra comentar.
Cada projeto sorteia uma combinação que não repete as dos últimos vídeos do mesmo modelo (guardada em config["estrutura"]).
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional

ABERTURAS = {
    "cena": ("🎬 Cena imaginada", "Abra com uma CENA concreta que a pessoa imagina (\"Imagine…\") e que carrega a tese do vídeo."),
    "pergunta": ("❓ Pergunta direta", "Abra com UMA pergunta curta e incômoda feita direto a quem assiste — sem \"imagine\". "
                 "Nas frases seguintes, mostre por que a resposta óbvia não basta."),
    "caso_real": ("📜 Caso real", "Abra contando um CASO REAL e conhecido (um episódio histórico, a vida de um pensador, um "
                  "experimento famoso), com nome, lugar e época — só o que é verdade e bem documentado."),
    "frase": ("🖋 Frase histórica", "Abra com uma FRASE célebre (autor + obra) que provoque, e em seguida diga por que ela "
              "incomoda ou parece errada à primeira vista."),
    "paradoxo": ("⚡ Afirmação contraintuitiva", "Abra com uma afirmação que parece ERRADA ou exagerada (o contrário do senso "
                 "comum) e prometa mostrar por que ela faz sentido."),
    "crenca": ("🪞 A crença comum", "Abra descrevendo o que QUASE TODO MUNDO pensa sobre o tema (\"a gente aprende que…\") — "
               "e anuncie que o vídeo vai desmontar ou aprofundar isso."),
    "cotidiano": ("☕ Momento do dia a dia", "Abra com uma situação banal e reconhecível do dia a dia (fila, celular, trabalho, "
                  "família) contada em segunda pessoa — e revele a questão filosófica escondida nela."),
}
ARCOS = {
    "tese": ("🧱 Tese → provas → objeção → síntese", "Apresente a tese cedo, sustente com 2 ou 3 argumentos/exemplos, traga a "
             "MELHOR objeção contra ela, responda e feche numa síntese."),
    "respostas": ("🔍 Respostas erradas antes da certa", "Faça a pergunta central e teste 2 ou 3 respostas comuns que NÃO "
                  "funcionam (mostrando por quê), até chegar à resposta mais sólida."),
    "dois_lados": ("⚖ Dois pensadores em diálogo", "Ponha duas visões (de dois pensadores ou duas tradições) frente a frente, "
                   "dê a cada uma o seu melhor argumento e mostre onde cada uma acerta e onde falha."),
    "historia": ("📖 Uma história em capítulos", "Conduza o vídeo por UMA história (real ou um exemplo assumido) que avança em "
                 "etapas; em cada etapa, a ideia filosófica que ela ilumina."),
    "mito": ("🧨 O mito e o desmonte", "Comece pelo equívoco popular sobre o tema, mostre de onde ele veio, desmonte por partes "
             "e entregue a versão mais verdadeira."),
    "pratica": ("🛠 Problema → ideia → uso", "Parta de um problema prático da vida, traga a ferramenta filosófica que ajuda a "
                "pensá-lo e termine mostrando como usar isso amanhã."),
    "escada": ("🪜 Do simples ao profundo", "Suba em degraus: comece pelo nível mais simples da ideia e a cada bloco vá uma "
               "camada mais fundo, até a pergunta mais radical do tema."),
}
FECHOS = {
    "pergunta": ("❓ Pergunta pra pensar", "Feche com UMA pergunta pessoal pra quem assiste levar consigo."),
    "volta": ("🔁 Volta à abertura", "Feche voltando à imagem/caso/frase da ABERTURA, agora vista com o que o vídeo mostrou."),
    "exercicio": ("✍ Exercício prático", "Feche propondo um exercício concreto e curto pra fazer hoje (escrever, observar, "
                  "decidir algo), dito em uma ou duas frases."),
    "frase": ("🖋 Frase final", "Feche com uma frase célebre (autor + obra) que resuma o vídeo, e uma linha sua depois dela."),
    "virada": ("🔄 Virada", "Feche com uma virada: algo que muda a leitura do que foi dito (o outro lado da tese, a pergunta "
               "que sobra) — sem ser pegadinha."),
    "sintese": ("🎯 Uma frase forte", "Feche resumindo o vídeo inteiro numa frase curta e memorável, sem recapitular tudo."),
}
CHAMADAS = (
    "pergunte a experiência da pessoa com o tema e peça pra contar nos comentários",
    "peça pra pessoa escolher um lado (A ou B) nos comentários e dizer por quê",
    "peça pra pessoa completar uma frase curta nos comentários",
    "convide a sugerir o próximo pensador/tema nos comentários",
    "peça a pessoa que discorde, se discordar, e escreva o melhor argumento contra",
    "sem pedido de comentário: só a despedida do canal",
)
_TRAVA = threading.Lock()
HISTORICO = 12


def _arq(base: str) -> str:
    return os.path.join(base, "estruturas_recentes.json")


def _ler(base: str) -> List[Dict[str, Any]]:
    try:
        with open(_arq(base), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def ativo() -> bool:
    try:
        from site_config import load_site_config
        return bool(load_site_config().get("variar_estrutura", True))
    except Exception:  # noqa: BLE001
        return True


def sortear(recentes: List[Dict[str, Any]], rnd: Optional[random.Random] = None) -> Dict[str, Any]:
    """Uma combinação que não repete a abertura dos 3 últimos, nem o arco/fecho dos 2 últimos."""
    rnd = rnd or random.Random()

    def livre(opcoes, campo, n):
        usados = [r.get(campo) for r in recentes[-n:]]
        ok = [k for k in opcoes if k not in usados]
        return rnd.choice(ok or list(opcoes))
    return {"abertura": livre(ABERTURAS, "abertura", 3), "arco": livre(ARCOS, "arco", 2), "fecho": livre(FECHOS, "fecho", 2),
            "chamada": livre(range(len(CHAMADAS)), "chamada", 2)}


def garantir(base: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """A estrutura do projeto (sorteia e grava no histórico na primeira vez). Mexe em p["config"]; quem chama salva."""
    cfg = p.setdefault("config", {})
    e = cfg.get("estrutura")
    if isinstance(e, dict) and e.get("abertura") in ABERTURAS:
        return e
    modelo = cfg.get("modelo") or ""
    with _TRAVA:
        hist = _ler(base)
        e = sortear([h for h in hist if h.get("modelo") == modelo])
        hist.append(dict(e, modelo=modelo, pid=p.get("id"), em=time.time()))
        try:
            tmp = _arq(base) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(hist[-200:], f, ensure_ascii=False)
            os.replace(tmp, _arq(base))
        except OSError:
            pass
    cfg["estrutura"] = e
    return e


def mudar(p: Dict[str, Any], campos: Dict[str, Any]) -> Dict[str, Any]:
    cfg = p.setdefault("config", {})
    e = dict(cfg.get("estrutura") or {})
    for campo, opcoes in (("abertura", ABERTURAS), ("arco", ARCOS), ("fecho", FECHOS)):
        if campos.get(campo) in opcoes:
            e[campo] = campos[campo]
    if str(campos.get("chamada", "")).isdigit() and int(campos["chamada"]) < len(CHAMADAS):
        e["chamada"] = int(campos["chamada"])
    cfg["estrutura"] = e
    return e


def bloco(e: Optional[Dict[str, Any]], curto: bool = False) -> str:
    if not isinstance(e, dict) or e.get("abertura") not in ABERTURAS:
        return ""
    a, r, f = ABERTURAS[e["abertura"]], ARCOS.get(e.get("arco")) or ARCOS["tese"], FECHOS.get(e.get("fecho")) or FECHOS["pergunta"]
    ch = CHAMADAS[int(e.get("chamada") or 0) % len(CHAMADAS)]
    L = ["## 🎲 ESTRUTURA DESTE VÍDEO (muda de vídeo pra vídeo — o canal não pode ter cara de fórmula)",
         "A IDENTIDADE fica: o tom, a clareza, o ritmo, a voz e a assinatura do canal. O que muda é a forma — e onde ela "
         "conflitar com o FORMATO DO CANAL, ESTA estrutura manda na abertura, no arco e no fecho.",
         f"- ABERTURA — {a[0]}: {a[1]}"]
    if not curto:
        L.append(f"- ARCO — {r[0]}: {r[1]}")
    L += [f"- FECHO — {f[0]}: {f[1]}",
          f"- CHAMADA pra comentar: {ch}.",
          "- Varie também as muletas: não comece frases seguidas com \"Imagine\", \"Pense\", \"Agora\" ou \"E aqui vem\"; "
          "use \"imagine\" no máximo uma vez fora da abertura."]
    return "\n".join(L)


def opcoes() -> Dict[str, Any]:
    return {"aberturas": {k: v[0] for k, v in ABERTURAS.items()}, "arcos": {k: v[0] for k, v in ARCOS.items()},
            "fechos": {k: v[0] for k, v in FECHOS.items()}, "chamadas": list(CHAMADAS)}
