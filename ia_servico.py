"""
🤖 IA nas buscas e nos Modelos de vídeo (v84_53).

Um "serviço de IA" do site: hoje só o Claude (Anthropic), pensado pra caber outras IAs
depois (PROVEDORES). Liga/desliga em /ia (link junto dos outros links úteis).

Regra de ouro: a IA melhora, mas NUNCA bloqueia. Desligada, sem chave, sem crédito,
passou do limite de gasto, deu erro, recusou, demorou → as funções devolvem None e
quem chamou segue com a lógica de sempre.

O que vai pra IA e como (plano do LEIA-ME "Busca de mídia com o Claude Haiku 5.5"):
  * JSON garantido por `output_config.format` (JSON Schema) — sem texto antes/depois;
  * o que é fixo (instruções + ficha do vídeo) vai no `system` com `cache_control`
    (cache de 1 h): as centenas de chamadas do juiz pagam o "system" quase de graça;
  * thinking desligado onde não precisa (juiz, buscas) — pensar é cobrado como saída;
  * miniaturas pequenas (320 px), mandadas em base64 (CDN que bloqueia link direto);
  * cache local por conteúdo (ia_cache/): reabrir/montar de novo não paga de novo;
  * o custo de cada chamada (usage) vai pra ia_uso.json e aparece na página /ia.

Arquivos (fora do Git — têm a sua chave / o seu uso): ia_config.json, ia_uso.json, ia_cache/.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_AQUI = os.path.dirname(os.path.abspath(__file__))
_DADOS = os.environ.get("IA_DADOS_DIR") or _AQUI  # os testes apontam pra uma pasta própria (a sua chave não é usada)
CONFIG_PATH = os.path.join(_DADOS, "ia_config.json")
USO_PATH = os.path.join(_DADOS, "ia_uso.json")
CACHE_DIR = os.path.join(_DADOS, "ia_cache")
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSAO = "2023-06-01"
CACHE_DIAS = 30
_TRAVA = threading.Lock()

# ------------------------------------------------------------------ provedores (hoje só o Claude)
PROVEDORES: Dict[str, Dict[str, Any]] = {
    "claude": {
        "nome": "Claude (Anthropic)",
        "chave_env": "ANTHROPIC_API_KEY",
        "chave_dica": "sk-ant-…  (platform.claude.com → API keys)",
        "prefixo_chave": "sk-ant-",
        "console": "https://platform.claude.com/settings/billing",
        "modelos": [
            # preços em US$ por 1 milhão de tokens (até 100 mil tokens no pedido; acima: *_longo)
            {"id": "claude-haiku-5-5", "nome": "Claude Haiku 5.5 (rápido e barato — o recomendado)",
             "entrada": 0.10, "saida": 0.50, "cache_leitura": 0.01, "entrada_longo": 0.50, "saida_longo": 2.50},
        ],
    },
}

# recurso → (nome, o que faz, ligado por padrão)
RECURSOS: Dict[str, Tuple[str, str, bool]] = {
    "buscas": ("🧭 Ficha do vídeo + buscas melhores",
               "Lê o roteiro uma vez (quem é quem, lugares, época, o que evitar) e reescreve as buscas de cada trecho, "
               "da mais específica pra mais genérica, em inglês pros bancos.", True),
    "juiz": ("⚖️ Juiz visual nas prévias",
             "Olha as miniaturas dos candidatos de cada trecho e escolhe a melhor (não a 1ª). Nota 5–6 = usa com ⚠.", True),
    "juiz_manual": ("🔎 Nota no botão Buscar do editor",
                    "Quando você busca à mão no editor, os resultados vêm ordenados pela nota, com o motivo.", True),
    "nova_busca": ("🔁 Reescrever a busca quando nada presta",
                   "Se todos os candidatos ficam abaixo de 5, busca de novo com a sugestão da IA (no máximo 2 vezes).", True),
    "cartao": ("🃏 Sem imagem boa → cartão de texto",
               "Quando o juiz reprova tudo (nota abaixo de 5 — ou abaixo da nota mínima num trecho abstrato), o trecho NÃO "
               "usa a menos pior: vira um cartão (fundo escuro + a frase do trecho na tipografia da direção).", True),
    "youtube_ordem": ("🎬 Ordenar os vídeos do YouTube",
                      "Busca 20 vídeos, dá nota (canal oficial/original sobe; react, compilação, reupload descem) e mostra "
                      "os 8 melhores + \"Outros vídeos\".", True),
    "youtube_momento": ("🎯 Achar o momento certo pela legenda",
                        "Lê a legenda do vídeo escolhido e preenche o início e o fim do trecho que fala o que a narração pede.", True),
    "wikipedia": ("📚 Wikipedia: desfazer ambiguidades",
                  "Quando um nome tem vários artigos (Paris, Mercury…), a IA escolhe o certo pelo contexto do roteiro.", True),
    "dossie_imagens": ("🕵️ Modelos de vídeo: ficha de cada imagem",
                       "Descreve cada imagem das matérias (quem/o quê, texto na imagem, se é lixo/anúncio, se é sensível).", True),
    "dossie_pdf": ("📄 Modelos de vídeo: PDF escaneado e dossiê condensado",
                   "Lê PDF escaneado/com tabela e resume arquivo grande em fatos com a página de cada um.", True),
    "dossie_marcas": ("✅ Conferir onde cada imagem entrou no roteiro",
                      "Aponta as marcas [I3] em frases que não combinam com a imagem e sugere outra.", True),
    "venda_imagens": ("🛒 Vídeo de venda: ficha das fotos do produto",
                      "Diz o ângulo, se mostra o produto em uso, a embalagem, os detalhes e se tem texto/preço na imagem.", True),
    "roteiros": ("📝 Roteiros direto na IA",
                 "Botão 🤖 Gerar com a IA nos Modelos de vídeo, Vídeo de venda, Roteiro do YouTube e Vídeos modelados: gera o "
                 "prompt, manda pra IA e já lê a resposta (sem copiar e colar).", True),
    "revisao": ("🎬 Revisão do diretor",
                "No Estúdio (aba 🤖 IA), a IA olha a miniatura de cada trecho com a fala de antes e de depois e diz o que não "
                "combina — e o que fazer: busca nova no buscador com mais chance, gráfico nativo, cartão ou \"procure na mão\".", True),
    "voz_tags": ("🎭 Tags de emoção na voz",
                 "No Gerador de voz (Chatterbox expressivo em português ou Turbo em inglês), o Claude lê o roteiro e coloca as "
                 "tags de estilo, pausa, respiração, ênfase e sons onde fazem sentido — sem mudar nenhuma palavra.", True),
    "edicao": ("✂️ Prompt de edição direto na IA",
               "No Estúdio (aba 🤖 IA), um botão manda o prompt de edição (ou cada parte dele) pra IA e cola a resposta.", True),
    "flow_famosos": ("🚫 Flow recusou \"pessoa famosa\" → reescrever o comando",
                     "Quando o Google Flow falha com \"pode violar nossas políticas contra a geração de imagens de pessoas famosas\", "
                     "a IA troca o nome da pessoa real por uma descrição genérica (roupa, época, cenário) e o Flow tenta de novo "
                     "(a geração recusada é reembolsada pelo Google).", True),
    "runpod_prompt": ("🟣 Runpod: prompt do jeito de cada modelo",
                      "Antes de gerar no Runpod, a IA escreve o prompt próprio do modelo (Z-Image, Flux, Pruna Video): em "
                      "inglês, com o estilo do vídeo, prompt negativo no Flux e movimento de câmera no vídeo.", True),
    "flow_foto": ("🔁 Flow em massa: vídeo → foto",
                  "No 🚀 Em massa da aba Google Flow, quando TODAS as contas ficam sem crédito de vídeo, a IA reescreve o "
                  "prompt de cada vídeo que falta como prompt de FOTO (o instante mais marcante, sem movimento de câmera).", True),
    "producao_pod": ("🏭 Produção no pod: cenas e prompts",
                     "Na aba 🏭 Produção no pod, lê a narração de cada roteiro, descreve cada cena, diz quais são DIFÍCEIS de "
                     "achar em banco (essas o seu pod gera com o Z-Image) e escreve o prompt de imagem de cada uma.", True),
    "elenco": ("🎭 Elenco: rostos e idades nas fotos",
               "No 🕵️ Modelo de vídeo (e sozinho na 🏭 Produção no pod), olha as fotos e o roteiro e diz quem é quem, a "
               "idade de cada pessoa em cada foto e o ano de nascimento — pra o pod gerar as cenas com o rosto certo, na "
               "idade certa daquele momento da história.", True),
    "animar": ("🎞 Animar cenas com o Google Flow",
               "No Estúdio, sugere quais cenas de imagem MAIS ganham com movimento e escreve o prompt de cada animação "
               "(imagem → vídeo no Flow): a partir do prompt que gerou a imagem (cena de IA) ou do contexto da cena — "
               "olhando a própria imagem.", True),
    "personagens": ("🧍 Personagens no vídeo: momentos, poses e animação",
                    "No Estúdio (aba 🧍 Personagens) e nos projetos novos de um canal com personagens: escolhe os MELHORES "
                    "momentos pra cada personagem aparecer (não todas as falas), a pose que combina com o que ela diz e a "
                    "animação de entrada/saída.", True),
    "flow_correcao": ("🩹 Flow: corrigir quando a tela muda",
                      "Na aba 🎬 Google Flow → 🩹 Corrigir: lê o erro, a foto e o HTML da tela e o trecho do código e propõe a "
                      "correção — aplicada numa CÓPIA do código do Flow (o original não muda), testada e reversível.", True),
    "react": ("🎭 React de personagens: elenco e roteiro",
              "Na aba 🕵️ Modelos de vídeo → 🎭 React de personagens: lê a transcrição e olha quadros do vídeo, sugere os "
              "personagens (da obra, hypados, contraste), completa a ficha de cada um e escreve as falas — quem fala, quando, "
              "com qual expressão e quem reage.", True),
    "anime2d": ("🎞 Animação 2D: plano, roteiro e cenas",
                "Na aba 🕵️ Modelos de vídeo → 🎞 Animação 2D: a partir da premissa cria os personagens, os locais e os "
                "itens, escreve as cenas (falas, narração, poses, câmera, imagens de destaque) e os prompts de cada imagem.", True),
    "criador": ("🧬 Criador de personagens: ficha, nomes e mistura",
                "Na aba 🕵️ Modelos de vídeo → 🧬 Criador de personagens: olha as imagens de referência (o que pegar de cada "
                "uma), as inspirações e o estilo e escreve a ficha — ideias de nome, a aparência travada pros prompts, "
                "personalidade, jeito de falar, história, voz, paleta — e avisa se ficou parecido demais com alguém.", True),
    "anime_cine": ("🎬 Anime quadro a quadro: planos e desenhos",
                   "Na aba 🕵️ Modelos de vídeo → 🎬 Anime quadro a quadro: lê o roteiro e as páginas de mangá e divide a cena em "
                   "planos (câmera, efeitos, falas, sons) e os desenhos do movimento de cada um.", True),
    "sons_pixabay": ("🔊 Efeitos sonoros do Pixabay: a ficha de cada som",
                     "No teste dos sons do Pixabay (pixabay_sons_teste.py --ia): olha o título, as tags, as medidas e o "
                     "espectrograma de cada efeito baixado e escreve o nome, a descrição, a categoria e onde usar.", True),
    "curtos": ("⚡ Vídeos curtos: estilo do canal e roteiro",
               "Na aba ⚡ Vídeos curtos: olha os quadros (4 por segundo) e as medidas de cada vídeo de referência e escreve a "
               "ficha, junta tudo no perfil de estilo do canal e escreve o roteiro de cada notícia nesse estilo (falas, planos, "
               "buscas, textos na tela e efeitos sonoros).", True),
    "canal": ("📊 Analisador de canal",
              "Lê os números, as miniaturas e as transcrições dos 20 vídeos recentes e dos 20 populares de um canal e diz o que "
              "funciona (títulos, capas, tipos de vídeo) e sugere vídeos novos.", True),
    "explicador": ("🎬 Explicador animado: plano das cenas",
                   "Na aba 🎬 Explicador animado: lê a narração com os tempos e monta o plano de motion graphics (textos, "
                   "cartas, ranking, listas, dicas, mãos de poker no simulador) com cada coisa entrando na frase certa.", True),
    "marca": ("🎨 Identidade visual: batidas, poses novas e revisão",
              "Na aba 🎨 Identidade visual, divide a narração em batidas (tipo de imagem, pose do mascote, textos em alemão), "
              "traduz uma pose/emoção nova que você descreve e olha cada imagem gerada contra o guia da marca (mascote igual, "
              "paleta, sem texto) — aprovar, revisar ou reprovar com o motivo.", True),
}

PADRAO: Dict[str, Any] = {
    "ativo": False, "provedor": "claude", "modelo": "claude-haiku-5-5", "chave": "",
    "recursos": {k: v[2] for k, v in RECURSOS.items()},
    "nota_minima": 7, "candidatos": 10, "limite_usd": 5.0,
    "credito_usd": 0.0,  # 🪙 v84_161: quanto você pôs de crédito na conta (pro saldo ao lado do sininho); 0 = só mostra o gasto
    "sem_credito": None,  # {"quando": ts, "erro": "..."} — desliga sozinho até você tentar de novo
}

_RECENTES: List[Dict[str, Any]] = []  # últimas chamadas (mostradas na página /ia)
_CTX = threading.local()  # 🪙 v84_161: rótulo da ação que está chamando a IA (aparece no saldo: "Roteiro: Hinterkaifeck")
LOG_MAX = 300
_SEM_PARAM: set = set()  # parâmetros que a API recusou (thinking/effort) — não manda de novo


class IAErro(Exception):
    pass


# ------------------------------------------------------------------ config
def _ler(caminho: str, padrao: Any) -> Any:
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar(caminho: str, dados: Any) -> None:
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    arquivo_seguro.trocar(tmp, caminho)


def config() -> Dict[str, Any]:
    c = json.loads(json.dumps(PADRAO))
    salvo = _ler(CONFIG_PATH, {})
    if isinstance(salvo, dict):
        for k, v in salvo.items():
            if k == "recursos" and isinstance(v, dict):
                c["recursos"].update({r: bool(x) for r, x in v.items() if r in RECURSOS})
            elif k in c:
                c[k] = v
    if c["provedor"] not in PROVEDORES:
        c["provedor"] = "claude"
    if c["modelo"] not in {m["id"] for m in PROVEDORES[c["provedor"]]["modelos"]}:
        c["modelo"] = PROVEDORES[c["provedor"]]["modelos"][0]["id"]
    return c


def salvar_config(novos: Dict[str, Any]) -> Dict[str, Any]:
    with _TRAVA:
        c = config()
        for k in ("ativo",):
            if k in novos:
                c[k] = bool(novos[k])
        if novos.get("provedor") in PROVEDORES:
            c["provedor"] = novos["provedor"]
        if novos.get("modelo") in {m["id"] for m in PROVEDORES[c["provedor"]]["modelos"]}:
            c["modelo"] = novos["modelo"]
        if "chave" in novos and novos["chave"] is not None:
            c["chave"] = str(novos["chave"]).strip()
        if isinstance(novos.get("recursos"), dict):
            c["recursos"].update({r: bool(x) for r, x in novos["recursos"].items() if r in RECURSOS})
        for k, lo, hi in (("nota_minima", 3, 10), ("candidatos", 4, 12)):
            if k in novos:
                try:
                    c[k] = int(max(lo, min(hi, int(float(novos[k])))))
                except (TypeError, ValueError):
                    pass
        if "credito_usd" in novos:
            try:
                c["credito_usd"] = round(max(0.0, float(str(novos["credito_usd"] or 0).replace(",", "."))), 2)
            except (TypeError, ValueError):
                pass
        if "limite_usd" in novos:
            try:
                c["limite_usd"] = round(max(0.0, float(str(novos["limite_usd"]).replace(",", "."))), 2)
            except (TypeError, ValueError):
                pass
        if novos.get("limpar_sem_credito") or "chave" in novos:
            c["sem_credito"] = None
        _gravar(CONFIG_PATH, c)
    return c


def chave(c: Optional[Dict[str, Any]] = None) -> str:
    c = c or config()
    return (c.get("chave") or os.environ.get(PROVEDORES[c["provedor"]]["chave_env"]) or "").strip()


def chave_mascarada(c: Optional[Dict[str, Any]] = None) -> str:
    k = chave(c)
    return (k[:8] + "…") if k else ""


def modelo_info(c: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    c = c or config()
    return next(m for m in PROVEDORES[c["provedor"]]["modelos"] if m["id"] == c["modelo"])


# 🔓 v84_378: um 401/sem crédito desligava a IA do site INTEIRO até alguém clicar em "Testar" — e um erro passageiro
# (proxy, troca de chave, instabilidade) deixava tudo travado com a chave boa. Agora o bloqueio vale só pra MESMA
# chave e só por alguns minutos: depois a próxima chamada tenta de novo (401 não cobra nada) e, se ainda for erro,
# bloqueia de novo.
SEM_CREDITO_EXPIRA_S = 600


def _impressao_chave(k: str) -> str:
    return hashlib.sha256((k or "").encode("utf-8")).hexdigest()[:12]


def sem_credito_valendo(c: Optional[Dict[str, Any]] = None) -> bool:
    c = c or config()
    sc = c.get("sem_credito")
    if not sc:
        return False
    if sc.get("chave") and sc["chave"] != _impressao_chave(chave(c)):
        return False  # trocou a chave depois do erro
    return time.time() - float(sc.get("quando") or 0) < SEM_CREDITO_EXPIRA_S


def motivo_desligado(recurso: Optional[str] = None, c: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """None = pode usar. Senão, por que não (mostrado na página/avisos)."""
    c = c or config()
    if not c.get("ativo"):
        return "a IA está desligada (🤖 IA nas configurações)"
    if not chave(c):
        return "falta a chave da API"
    if sem_credito_valendo(c):
        return "sem crédito / chave recusada: " + str(c["sem_credito"].get("erro") or "")[:160]
    if recurso and not c["recursos"].get(recurso, False):
        return f"o recurso “{RECURSOS.get(recurso, (recurso,))[0]}” está desligado"
    lim = float(c.get("limite_usd") or 0)
    if lim and gasto()["usd"] >= lim:
        return f"chegou no limite de gasto de US$ {lim:.2f} (mude em 🤖 IA)"
    return None


def ativo(recurso: Optional[str] = None) -> bool:
    try:
        return motivo_desligado(recurso) is None
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ uso e custo
def _custo(u: Dict[str, Any], m: Dict[str, Any]) -> float:
    ent = int(u.get("input_tokens") or 0)
    cl = int(u.get("cache_read_input_tokens") or 0)
    ce = int(u.get("cache_creation_input_tokens") or 0)
    sai = int(u.get("output_tokens") or 0)
    longo = (ent + cl + ce) > 100_000
    p_in = m["entrada_longo"] if longo else m["entrada"]
    p_out = m["saida_longo"] if longo else m["saida"]
    return (ent * p_in + ce * p_in * 2.0 + cl * m["cache_leitura"] + sai * p_out) / 1_000_000


def gasto() -> Dict[str, Any]:
    d = _ler(USO_PATH, {})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("usd", 0.0)
    d.setdefault("chamadas", 0)
    d.setdefault("por_recurso", {})
    d.setdefault("desde", None)
    return d


class rotulo:
    """`with ia.rotulo("Roteiro: Hinterkaifeck"):` — as chamadas feitas dentro levam esse nome no 🪙 saldo."""

    def __init__(self, texto: str):
        self.texto = str(texto or "").strip()[:120]
        self.antes = None

    def __enter__(self):
        self.antes = getattr(_CTX, "rotulo", None)
        _CTX.rotulo = self.texto
        return self

    def __exit__(self, *_a):
        _CTX.rotulo = self.antes
        return False


def _entrada_log(recurso: str, u: Dict[str, Any], custo: float, job: Optional[str], ok: bool, erro: str = "",
                 cache: bool = False) -> Dict[str, Any]:
    e = {"quando": round(time.time(), 1), "recurso": recurso, "usd": round(custo, 6), "ok": bool(ok),
         "entrada": int(u.get("input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0),
         "saida": int(u.get("output_tokens") or 0), "cache_lido": int(u.get("cache_read_input_tokens") or 0)}
    rot = getattr(_CTX, "rotulo", None) or ""
    if rot:
        e["rotulo"] = rot
    if job:
        e["job"] = str(job)[:60]
    if erro:
        e["erro"] = str(erro)[:200]
    if cache:
        e["cache"] = True
    return e


def _guardar_log(d: Dict[str, Any], e: Dict[str, Any]) -> None:
    log = d.setdefault("log", [])
    log.append(e)
    del log[:-LOG_MAX]


def _registrar_cache(recurso: str, job: Optional[str]) -> None:
    """Resposta que já estava guardada (não paga de novo) — entra no histórico do saldo como grátis."""
    with _TRAVA:
        d = gasto()
        _guardar_log(d, _entrada_log(recurso, {}, 0.0, job, True, cache=True))
        try:
            _gravar(USO_PATH, d)
        except OSError:
            pass


def _registrar(recurso: str, u: Dict[str, Any], custo: float, job: Optional[str], ok: bool, erro: str = "") -> None:
    with _TRAVA:
        d = gasto()
        _guardar_log(d, _entrada_log(recurso, u, custo, job, ok, erro))
        d["desde"] = d["desde"] or time.time()
        d["usd"] = round(d["usd"] + custo, 6)
        d["chamadas"] += 1
        r = d["por_recurso"].setdefault(recurso, {"usd": 0.0, "chamadas": 0, "cache_lido": 0})
        r["usd"] = round(r["usd"] + custo, 6)
        r["chamadas"] += 1
        r["cache_lido"] += int(u.get("cache_read_input_tokens") or 0)
        if job:
            pj = d.setdefault("por_job", {})
            pj[job] = round(pj.get(job, 0.0) + custo, 6)
            if len(pj) > 300:
                for k in list(pj)[:-300]:
                    pj.pop(k, None)
        try:
            _gravar(USO_PATH, d)
        except OSError:
            pass
        _RECENTES.append({"quando": time.time(), "recurso": recurso, "ok": ok, "usd": round(custo, 6), "erro": erro[:200],
                          "entrada": int(u.get("input_tokens") or 0), "saida": int(u.get("output_tokens") or 0),
                          "cache_lido": int(u.get("cache_read_input_tokens") or 0)})
        del _RECENTES[:-40]


def recentes() -> List[Dict[str, Any]]:
    return list(reversed(_RECENTES))


def zerar_gasto() -> None:
    with _TRAVA:
        _gravar(USO_PATH, {"usd": 0.0, "chamadas": 0, "por_recurso": {}, "desde": time.time(), "log": []})


def nome_recurso(recurso: str) -> str:
    """Nome do recurso sem o emoji do começo (pro saldo)."""
    nome = RECURSOS.get(recurso, (recurso or "outro",))[0]
    return re.sub(r"^[^\w(]+", "", nome).strip() or nome


def saldo() -> Dict[str, Any]:
    """🪙 v84_161: o que aparece ao lado do sininho — gasto, crédito informado, saldo, hoje, custo por ação e as últimas chamadas."""
    c = config()
    g = gasto()
    log = [x for x in (g.get("log") or []) if isinstance(x, dict)]
    t0 = time.localtime()
    meia_noite = time.mktime((t0.tm_year, t0.tm_mon, t0.tm_mday, 0, 0, 0, 0, 0, -1))
    hoje = sum(float(x.get("usd") or 0) for x in log if float(x.get("quando") or 0) >= meia_noite)
    por = [{"recurso": k, "nome": nome_recurso(k), "usd": round(float(v.get("usd") or 0), 6), "chamadas": int(v.get("chamadas") or 0)}
           for k, v in (g.get("por_recurso") or {}).items() if isinstance(v, dict)]
    por.sort(key=lambda x: -x["usd"])
    cred = float(c.get("credito_usd") or 0)
    gasto_usd = round(float(g.get("usd") or 0), 6)
    return {
        "ativo": bool(c.get("ativo")), "motivo": motivo_desligado(None, c), "modelo": c.get("modelo") or "",
        "gasto_usd": gasto_usd, "chamadas": int(g.get("chamadas") or 0), "desde": g.get("desde"),
        "hoje_usd": round(hoje, 6), "credito_usd": round(cred, 2), "saldo_usd": round(cred - gasto_usd, 6) if cred else None,
        "limite_usd": float(c.get("limite_usd") or 0), "console": PROVEDORES[c["provedor"]].get("console") or "",
        "por_recurso": por[:20],
        "log": [dict(x, nome=nome_recurso(str(x.get("recurso") or ""))) for x in reversed(log[-60:])],
    }


def _marcar_sem_credito(erro: str) -> None:
    with _TRAVA:
        c = config()
        c["sem_credito"] = {"quando": time.time(), "erro": erro[:300], "chave": _impressao_chave(chave(c))}
        _gravar(CONFIG_PATH, c)


# ------------------------------------------------------------------ imagens
def imagem_bloco(fonte: str, largura: int = 320, timeout: float = 12.0) -> Optional[Dict[str, Any]]:
    """Miniatura (link ou arquivo) → bloco de imagem em base64, reduzida pra `largura` px.
    None se não abrir (o candidato vai só com o texto)."""
    try:
        from PIL import Image
        if re.match(r"https?://", str(fonte or "")):
            import requests
            r = requests.get(fonte, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (BestEditor)"})
            if r.status_code != 200 or not r.content:
                return None
            im = Image.open(io.BytesIO(r.content))
        elif fonte and os.path.isfile(fonte):
            if os.path.splitext(fonte)[1].lower() in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
                return mosaico_video(fonte, largura)
            im = Image.open(fonte)
        else:
            return None
        im = im.convert("RGB")
        if im.width > largura:
            im = im.resize((largura, max(1, int(im.height * largura / im.width))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                            "data": base64.b64encode(buf.getvalue()).decode()}}
    except Exception:  # noqa: BLE001
        return None


def mosaico_video(fonte: str, largura: int = 320) -> Optional[Dict[str, Any]]:
    """3 momentos do vídeo (15%, 50%, 85%) lado a lado — um quadro só engana."""
    import subprocess
    import tempfile
    try:
        from PIL import Image
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", fonte],
                           capture_output=True, text=True, timeout=30)
        dur = float(r.stdout.strip() or 0)
        quadros = []
        with tempfile.TemporaryDirectory() as tmp:
            for k, f in enumerate((0.15, 0.5, 0.85)):
                saida = os.path.join(tmp, f"{k}.jpg")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, dur * f):.2f}", "-i", fonte, "-frames:v", "1",
                                "-vf", f"scale={largura}:-2", saida], capture_output=True, timeout=60)
                if os.path.isfile(saida):
                    quadros.append(Image.open(saida).convert("RGB"))
        if not quadros:
            return None
        h = min(q.height for q in quadros)
        tela = Image.new("RGB", (sum(q.width for q in quadros), h))
        x = 0
        for q in quadros:
            tela.paste(q.crop((0, 0, q.width, h)), (x, 0))
            x += q.width
        buf = io.BytesIO()
        tela.save(buf, "JPEG", quality=80)
        return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}
    except Exception:  # noqa: BLE001
        return None


def pdf_bloco(dados: bytes) -> Dict[str, Any]:
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(dados).decode()}}


# ------------------------------------------------------------------ transporte (trocável nos testes)
def _transporte(payload: Dict[str, Any], chave_api: str, timeout: float) -> Tuple[int, Dict[str, Any]]:
    import requests
    r = requests.post(API_URL, json=payload, timeout=timeout,
                      headers={"x-api-key": chave_api, "anthropic-version": API_VERSAO, "content-type": "application/json"})
    try:
        corpo = r.json()
    except ValueError:
        corpo = {"error": {"message": r.text[:300]}}
    return r.status_code, corpo


def _chave_cache(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def _cache_ler(k: str) -> Optional[Any]:
    cam = os.path.join(CACHE_DIR, k[:2], k + ".json")
    try:
        if time.time() - os.path.getmtime(cam) > CACHE_DIAS * 86400:
            return None
        with open(cam, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_gravar(k: str, valor: Any) -> None:
    try:
        cam = os.path.join(CACHE_DIR, k[:2], k + ".json")
        os.makedirs(os.path.dirname(cam), exist_ok=True)
        _gravar(cam, valor)
    except OSError:
        pass


def _sem_credito(status: int, msg: str) -> bool:
    m = msg.lower()
    return status in (401, 402) or (status in (400, 403) and any(x in m for x in (
        "credit balance", "billing", "insufficient", "quota", "invalid x-api-key", "authentication", "permission")))


def chamar(recurso: str, system: str, conteudo: Any, schema: Optional[Dict[str, Any]] = None, max_tokens: int = 800,
           effort: str = "low", pensar: bool = False, job: Optional[str] = None, cache_local: bool = True,
           timeout: float = 90.0, forcar: bool = False) -> Optional[Any]:
    """Uma chamada à IA. Com `schema`: devolve o objeto (dict/list). Sem: o texto.
    None em QUALQUER problema (desligada, sem crédito, erro, recusa) — quem chamou segue sem a IA.
    `forcar`: ignora o liga/desliga do recurso (botão "Testar")."""
    c = config()
    if not forcar and motivo_desligado(recurso, c) is not None:
        return None
    if forcar and not chave(c):
        return None
    m = modelo_info(c)
    if isinstance(conteudo, str):
        conteudo = [{"type": "text", "text": conteudo}]
    payload: Dict[str, Any] = {
        "model": c["modelo"], "max_tokens": int(max_tokens),
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        "messages": [{"role": "user", "content": conteudo}],
    }
    oc: Dict[str, Any] = {}
    if schema:
        oc["format"] = {"type": "json_schema", "schema": schema}
    if effort and "effort" not in _SEM_PARAM:
        oc["effort"] = effort
    if oc:
        payload["output_config"] = oc
    if not pensar and "thinking" not in _SEM_PARAM:
        payload["thinking"] = {"type": "disabled"}

    k = _chave_cache(payload) if cache_local else ""
    if k:
        guardado = _cache_ler(k)
        if guardado is not None:
            _RECENTES.append({"quando": time.time(), "recurso": recurso, "ok": True, "usd": 0.0, "erro": "", "cache_local": True,
                              "entrada": 0, "saida": 0, "cache_lido": 0})
            _registrar_cache(recurso, job)
            return guardado.get("v")

    tentativas, espera = 0, 2.0
    while True:
        tentativas += 1
        try:
            status, corpo = _transporte(payload, chave(c), timeout)
        except Exception as exc:  # noqa: BLE001 — rede caiu, timeout…
            if tentativas < 3:
                time.sleep(espera)
                espera *= 2
                continue
            _registrar(recurso, {}, 0.0, job, False, f"rede: {exc}")
            return None
        msg = str(((corpo or {}).get("error") or {}).get("message") or "")
        if status == 400 and any(p in msg for p in ("thinking", "effort")) and tentativas < 3:
            for p in ("thinking", "effort"):  # a API (ou o modelo) não aceita esse parâmetro: tira e tenta de novo
                if p in msg:
                    _SEM_PARAM.add(p)
                    payload.pop("thinking", None) if p == "thinking" else (payload.get("output_config") or {}).pop("effort", None)
            if not payload.get("output_config"):
                payload.pop("output_config", None)
            continue
        if status in (429, 500, 502, 503, 504, 529) and tentativas < 4:
            time.sleep(espera)
            espera *= 2
            continue
        if status != 200:
            if _sem_credito(status, msg):
                _marcar_sem_credito(f"{status}: {msg}")
            _registrar(recurso, {}, 0.0, job, False, f"{status}: {msg}")
            return None
        break

    u = corpo.get("usage") or {}
    custo = _custo(u, m)
    if corpo.get("stop_reason") in ("refusal", "max_tokens"):
        _registrar(recurso, u, custo, job, False, f"stop_reason={corpo.get('stop_reason')}")
        return None
    texto = "".join(b.get("text", "") for b in corpo.get("content") or [] if b.get("type") == "text").strip()
    valor: Any = texto
    if schema:
        try:
            valor = json.loads(texto)
        except ValueError:
            try:
                import json_ia
                valor = json_ia.carregar(texto, aceitar_cortado=True)
            except Exception:  # noqa: BLE001
                _registrar(recurso, u, custo, job, False, "resposta sem JSON")
                return None
    _registrar(recurso, u, custo, job, True)
    if k:
        _cache_gravar(k, {"v": valor, "quando": time.time()})
    return valor


def testar() -> Dict[str, Any]:
    """Botão "Testar": uma chamada mínima (não usa o cache)."""
    c = config()
    if not chave(c):
        return {"ok": False, "erro": "Falta a chave da API."}
    antes = len(_RECENTES)
    r = chamar("teste", "Responda só com o JSON pedido.", "Diga ok.",
               schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
               max_tokens=50, cache_local=False, forcar=True)
    if r is None:
        ult = _RECENTES[-1] if len(_RECENTES) > antes else {}
        return {"ok": False, "erro": ult.get("erro") or "sem resposta"}
    with _TRAVA:
        c2 = config()
        c2["sem_credito"] = None
        _gravar(CONFIG_PATH, c2)
    return {"ok": True}


def resumo_publico() -> Dict[str, Any]:
    """Pra página e pros outros módulos — a chave NUNCA vai inteira."""
    c = config()
    g = gasto()
    return {"ativo": c["ativo"], "provedor": c["provedor"], "modelo": c["modelo"], "chave": chave_mascarada(c),
            "chave_do_ambiente": bool(not c.get("chave") and chave(c)),
            "chave_suspeita": bool(chave(c)) and not chave(c).startswith(PROVEDORES[c["provedor"]].get("prefixo_chave") or ""),
            "recursos": c["recursos"], "nota_minima": c["nota_minima"], "candidatos": c["candidatos"], "limite_usd": c["limite_usd"],
            "sem_credito": c["sem_credito"] if sem_credito_valendo(c) else None, "motivo": motivo_desligado(None, c), "gasto": g}
