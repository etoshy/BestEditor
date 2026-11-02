"""
⚡ VÍDEOS CURTOS (v84_246) — modelagem de Shorts/Reels/TikTok de um canal (ex.: Laestro).

Duas coisas guardadas (pasta `curtos/`, ou CURTOS_DIR):

  🧬 CANAL  (curtos/canais/<id>/canal.json) — o "molde" do canal:
      • até 10+ vídeos de REFERÊNCIA (arquivo ou link). Cada um é MEDIDO aqui
        (duração, cortes por segundo, duração dos planos, quando entra a 1ª fala,
        palavras por segundo, se tem música de fundo, se tem som nos cortes),
        TRANSCRITO (Whisper, palavra a palavra) e a IA olha os quadros de cada
        plano (uma folha de contato) e escreve a FICHA do vídeo;
      • o PERFIL DE ESTILO, juntando tudo: gancho, estrutura, composições visuais,
        legenda (já no preset do editor), textos na tela, efeitos sonoros, CTA,
        o que evitar — editável, e sai também como prompt pra outra IA.

  ⚡ PROJETO (curtos/projetos/<id>/projeto.json) — um vídeo:
      1. NOTÍCIA: link(s) da matéria (o site lê o texto e baixa as fotos → I1, I2…)
         e/ou texto colado; mais fotos/vídeos seus (M1, M2…);
      2. ROTEIRO no estilo do canal: blocos de fala, cada um com os PLANOS
         (composição + busca de mídia), texto na tela e as deixas de SOM;
      3. VOZ GUIA (TTS) pra ouvir o ritmo — ou usar no vídeo;
      4. SUA VOZ: grava na página (teleprompter) ou sobe o arquivo → Whisper →
         alinha a fala ao roteiro (o tempo de cada bloco/plano/texto/som segue o
         ritmo da SUA voz), corta pausas longas e repetições;
      5. EDITOR: vira um projeto do Estúdio — buscas nos bancos, mídias da
         matéria, legenda do canal, destaques, efeitos sonoros já no lugar.

A IA (ia_servico, recurso "curtos") melhora, mas nunca é obrigatória: todo passo
com IA tem o prompt pra copiar e colar a resposta de outra IA.
"""
from __future__ import annotations

import difflib
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import threading
import time
import unicodedata
import uuid
import zlib
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import arquivo_seguro  # noqa: F401  (v84_99: os.replace sem WinError 5)
import ffmpeg_sem_stdin  # noqa: E402,F401  (v84_329: ffmpeg nunca espera o teclado do console)

_AQUI = os.path.dirname(os.path.abspath(__file__))
_TRAVA = threading.RLock()

MAX_REFERENCIAS = 20
EXT_VIDEO = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")
EXT_AUDIO = (".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".aac", ".opus")
EXT_FOTO = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".gif")
LIMIAR_CENA = 0.30          # ffmpeg select=gt(scene,…): troca de plano
MAX_QUADROS_FOLHA = 20      # quadros na folha de contato da IA


class CurtoErro(Exception):
    pass


# ------------------------------------------------------------------ catálogos
# composições que o editor sabe montar sozinho (a IA encaixa as do canal nelas)
LAYOUTS: Dict[str, Tuple[str, str]] = {
    "video": ("🎞 vídeo de banco", "clima, ação ou ambiente genérico — vídeo de banco (Pexels, Pixabay…)"),
    "foto": ("🖼 foto de banco com movimento", "ideia ou objeto genérico — foto de banco com zoom/pan"),
    "foto_real": ("📸 foto real", "pessoa, lugar, empresa, produto ou objeto ESPECÍFICO e real — buscadores de imagem / Wikipedia"),
    "clipe_real": ("📺 clipe real", "imagem de arquivo, TV, entrevista ou o acontecimento filmado — YouTube"),
    "materia": ("📰 mídia da notícia / sua / do canal", "uma foto/vídeo da matéria (I1…), que você subiu (M1…) ou um meme/bordão "
                "recorrente do canal (K1…) — use sempre que mostrar o fato"),
    "meme": ("😂 meme de reação", "meme/reação conhecido (anime, bicho, famoso fazendo cara) — busca de imagem/GIF pelo nome do meme"),
    "cartao_cinza": ("⬜ cartão cinza", "foto/print/meme PEQUENO no centro de um fundo cinza liso, com sombra — pra explicar, listar, "
                     "mostrar quem é quem, um tweet ou uma manchete (a imagem pode trocar a cada 1-2 s no mesmo fundo)"),
    "anime_reacao": ("🎌 reação em anime", "clipe de anime em que um personagem REAGE com a emoção do momento (choque, risada, choro, "
                     "raiva, vergonha, sorriso maligno, cara de 'que?') — o meme de reação, só que de anime"),
    "anime_cena": ("🎌 cena de anime que explica", "cena de anime que mostra POR COMPARAÇÃO o que está acontecendo (traição, plano maligno, "
                   "alguém sendo humilhado, poder subindo, caos, multidão revoltada, dinheiro, fuga) — metáfora visual, não o fato real"),
    "cartao": ("🃏 cartão de texto", "número, data ou frase de impacto sobre fundo escuro, sem imagem"),
    "ia": ("✨ imagem gerada", "cena que não existe em banco nem na matéria — gerada no Flow/Runpod"),
    "ia_video": ("🎬 vídeo gerado", "cena com MOVIMENTO gerada no Flow (vídeo de ~8 s) — sem Flow, vira a imagem gerada"),
}
LAYOUTS_ANIME = ("anime_reacao", "anime_cena")
PROVEDORES_ANIME = ("animepexels", "animepexels_online")
MODOS_ANIME = {"nao": "não", "reacoes": "🎌 reações e sentimentos", "tudo": "🎌 tudo que não precisa ser real"}
EMOCOES_ANIME = ("choque", "risada", "choro", "raiva", "vergonha", "medo", "sorriso_maligno", "confusao", "decepcao", "determinacao",
                 "alivio", "nojo", "tedio", "orgulho", "tristeza")
EFEITOS_CURTOS = ("zoom_in", "zoom_out", "zoom_rapido", "pan_esq", "pan_dir", "pan_cima", "zoom_respiro", "flicker", "chroma")
ENTRADAS_CURTOS = ("punch_in", "pop", "flash", "shake", "zoom_in", "slide_left", "slide_up", "blur_in", "none")

# deixas de som → onde procurar na base (id começa com / contém) + busca em inglês pro Pixabay
TIPOS_SFX: Dict[str, Dict[str, Any]] = {
    "whoosh": {"nome": "💨 whoosh (passagem rápida)", "ids": ["variados/whoosh_", "transicoes/whoosh"], "tags": ["whoosh", "swoosh", "swish"], "pixabay": "whoosh"},
    "swipe": {"nome": "↔ swipe / passagem", "ids": ["passagem/", "transicoes/passagem"], "tags": ["swipe", "pass", "transition"], "pixabay": "swipe transition"},
    "impacto": {"nome": "💥 impacto / hit", "ids": ["impacto/impacto_", "transicoes/impacto"], "tags": ["impact", "hit", "punch"], "pixabay": "cinematic hit"},
    "boom": {"nome": "🔊 boom grave", "ids": ["variados/whoosh_grave", "impacto/impacto_subida"], "tags": ["boom", "bass", "sub drop"], "pixabay": "boom bass drop"},
    "riser": {"nome": "📈 riser (tensão subindo)", "ids": ["impacto/riser", "impacto/impacto_subida"], "tags": ["riser", "rise", "tension"], "pixabay": "riser"},
    "pop": {"nome": "🫧 pop (texto/ícone surgindo)", "ids": ["pop/pop_"], "tags": ["pop", "bubble"], "pixabay": "pop"},
    "clique": {"nome": "🖱 clique", "ids": ["pop/click", "foley/tecla", "pop/pop_click"], "tags": ["click", "mouse", "tap"], "pixabay": "mouse click"},
    "ding": {"nome": "🔔 ding / notificação", "ids": ["foley/maquina_ding", "pop/pop_multi"], "tags": ["ding", "bell", "notification"], "pixabay": "notification ding"},
    "camera": {"nome": "📷 câmera / flash", "ids": ["foley/camera_", "transicoes/disparo_de_camera", "transicoes/obturador", "foley/click_de_camera"], "tags": ["camera", "shutter", "flash"], "pixabay": "camera shutter"},
    "glitch": {"nome": "📺 glitch / digital", "ids": ["digital/", "transicoes/digital", "transicoes/pulso_digital"], "tags": ["glitch", "digital", "error"], "pixabay": "glitch"},
    "digitacao": {"nome": "⌨ digitação", "ids": ["foley/digitacao", "foley/maquina_datilografando"], "tags": ["typing", "keyboard"], "pixabay": "keyboard typing"},
    "cinema": {"nome": "🎬 brilho cinematográfico", "ids": ["cinema/"], "tags": ["cinematic", "shimmer"], "pixabay": "cinematic transition"},
    "vento": {"nome": "🌬 vento / ar", "ids": ["vento/", "transicoes/ar_", "transicoes/vento"], "tags": ["wind", "air"], "pixabay": "wind whoosh"},
    "respiro": {"nome": "😮‍💨 respiro / suspense", "ids": ["respiro/"], "tags": ["breath", "suspense"], "pixabay": "suspense breath"},
}
CENA_CARTAO_CINZA = "CURTO_CARTAO_CINZA"
CENAS_EXTRAS = {CENA_CARTAO_CINZA: {
    "nome": "Curto - Cartão cinza", "slots": 1, "janelas": [[0.29, 0.57, 0.42, 0.23]], "fundo_fixo": "cor_solida",
    "cor_fundo": "#8E8E8E", "borda": 0, "sem_transpor": True, "movimento": "assenta", "textFields": [], "coversCaption": False,
    "manualOnly": True, "papel": "apoio", "familia": "meus", "durMinS": 0.4, "durIdealS": 1.5, "durMaxS": 30,
    "whenToUse": ["Short: small photo/meme centered on flat gray, caption above"]}}


def garantir_cenas() -> bool:
    """Põe a cena ⬜ cartão cinza nos extras do DarkPlanner (uma vez). True se mudou algo."""
    try:
        import dp_extras
        cam = os.path.join(dp_extras.pasta(), "curtos_cenas.json")
        atual = _ler_json(cam) if os.path.isfile(cam) else {}
        if atual.get("cenas") == CENAS_EXTRAS:
            return False
        os.makedirs(dp_extras.pasta(), exist_ok=True)
        _gravar_json(cam, {"_sobre": "⚡ Vídeos curtos (curtos.py) — gerado sozinho, não precisa mexer", "cenas": CENAS_EXTRAS})
        dp_extras.recarregar()
        return True
    except Exception:  # noqa: BLE001
        return False


FUNCOES_BLOCO = ("gancho", "contexto", "fato", "virada", "detalhe", "consequencia", "contraponto", "reflexao", "pergunta", "cta", "final")

PERFIL_PADRAO: Dict[str, Any] = {
    "resumo": "",
    "idioma": "",
    "duracao_alvo_s": 45,
    "ritmo": {"plano_medio_s": 1.8, "palavras_por_s": 2.8, "cortes": "corte seco a cada frase/ideia",
              "pausa_max_s": 0.30},
    "gancho": {"descricao": "", "duracao_s": 3, "exemplos": []},
    "estrutura": [],
    "tom": "",
    "linguagem": "",
    "composicoes": [],
    "textos_tela": {"usa": True, "descricao": "", "estilo_destaque": "impacto_red", "frequencia": "1 a cada 2 blocos"},
    "legenda": {"ativa": True, "estilo": "pop", "posicao": "meio", "tamanho": 0.075, "maiusculas": True,
                "max_palavras": 3, "fonte": "DP Inter", "cor_texto": "#FFFFFF", "cor_ativa": "#FFE600", "contorno": True},
    "sfx": {"usa": True, "nos_cortes": True, "descricao": "whoosh curto nas trocas de assunto, impacto nas revelações, pop nos textos",
            "tipos_preferidos": ["whoosh", "impacto", "pop"], "volume": 0.8},
    "musica": {"usa": True, "descricao": "batida eletrônica tensa, baixinha"},
    "cta": {"texto": "", "onde": "final"},
    "gancho_maiusculas": False,
    # 🧭 v84_249: o canal não só dá a notícia — traz um contraponto e uma pequena reflexão (padrão: ligado)
    "anime": {"modo": "nao", "obras": ""},  # 🎌 v84_250: padrão do canal (o projeto pode trocar)
    "ponto_de_vista": {"usa": True, "descricao": "Além de dar a notícia, traga pelo menos um ponto de discordância ou contraponto (o outro "
                       "lado, o que a manchete não conta, o que a reação geral exagera ou esquece) e feche com uma pequena reflexão."},
    "titulos": {"descricao": "", "exemplos": []},
    "evitar": [],
    # v84_253/255: 💬📚 o enquadramento do vídeo de outra proporção, cortes/tamanho pelo conteúdo, 1º plano curto e a 🏷 marca
    "enquadramento": "",
    "cortes_por_contexto": False,
    "duracao_pelo_conteudo": False,
    "primeiro_plano_max_s": None,
    "marca": {},
    "estilo_ia": "",  # v84_256: imagem/vídeo gerado (Flow) "realista" ou livre
}


def _hoje() -> float:
    return time.time()


def _novo_id() -> str:
    return uuid.uuid4().hex[:10]


def _valido(i: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{10}", str(i or "")))


# ------------------------------------------------------------------ pastas
def raiz(base: str) -> str:
    return os.environ.get("CURTOS_DIR") or os.path.join(base, "curtos")


def pasta_canal(base: str, cid: str) -> str:
    if not _valido(cid):
        raise CurtoErro("Canal inválido.")
    return os.path.join(raiz(base), "canais", cid)


def pasta(base: str, pid: str) -> str:
    if not _valido(pid):
        raise CurtoErro("Projeto inválido.")
    return os.path.join(raiz(base), "projetos", pid)


def _gravar_json(caminho: str, dados: Any) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def _ler_json(caminho: str) -> Any:
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ 🧬 canais
def criar_canal(base: str, nome: str, idioma: str = "", descricao: str = "") -> Dict[str, Any]:
    nome = " ".join(str(nome or "").split())[:80]
    if not nome:
        raise CurtoErro("Dê um nome ao canal.")
    c = {"id": _novo_id(), "nome": nome, "idioma": str(idioma or "")[:8], "descricao": str(descricao or "").strip()[:1500],
         "criado": _hoje(), "referencias": [],
         "perfil": json.loads(json.dumps(PERFIL_PADRAO)), "perfil_ia": False, "metricas": {}, "atualizado": _hoje()}
    salvar_canal(base, c)
    return c


def salvar_canal(base: str, c: Dict[str, Any]) -> None:
    c["atualizado"] = _hoje()
    _gravar_json(os.path.join(pasta_canal(base, c["id"]), "canal.json"), c)


def carregar_canal(base: str, cid: str) -> Dict[str, Any]:
    cam = os.path.join(pasta_canal(base, cid), "canal.json")
    if not os.path.isfile(cam):
        raise CurtoErro("Canal não encontrado.")
    c = _ler_json(cam)
    c.setdefault("referencias", [])
    c["perfil"] = normalizar_perfil(c.get("perfil"))
    return c


def perfis_prontos() -> Dict[str, Dict[str, Any]]:
    """Perfis que vêm com o site (assets/curtos/perfis/*.json) — ex.: o Laestro, analisado dos vídeos de referência."""
    d = os.path.join(_AQUI, "assets", "curtos", "perfis")
    out = {}
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if f.endswith(".json"):
            try:
                out[f[:-5]] = _ler_json(os.path.join(d, f))
            except (OSError, ValueError):
                continue
    return out


def garantir_canais_prontos(base: str) -> List[str]:
    """Os canais de perfil pronto (ex.: Laestro) já existem desde o 1º uso — criados UMA vez (se você apagar, não volta).
    Devolve os ids criados agora."""
    marca = os.path.join(raiz(base), "prontos_criados.json")
    try:
        feitos = set(_ler_json(marca)) if os.path.isfile(marca) else set()
    except (OSError, ValueError):
        feitos = set()
    novos = []
    with _TRAVA:
        for chave, pr in perfis_prontos().items():
            if chave in feitos:
                _atualizar_pronto(base, chave, pr)
                continue
            c = criar_canal(base, pr.get("nome") or chave, pr.get("idioma") or "")
            c["perfil"] = aplicar_perfil(c["perfil"], pr.get("perfil") or {})
            c["perfil_ia"] = True
            c["perfil_origem"] = chave
            c["perfil_versao"] = int(pr.get("versao") or 1)
            if pr.get("modelo"):
                c["modelo"] = pr["modelo"]
            salvar_canal(base, c)
            feitos.add(chave)
            novos.append(c["id"])
        if novos:
            _gravar_json(marca, sorted(feitos))
    return novos


def _atualizar_pronto(base: str, chave: str, pr: Dict[str, Any]) -> None:
    """O perfil pronto mudou de versão (ex.: Laestro v2 tirou o bordão e ganhou contraponto + reflexão): o canal que veio dele
    recebe SÓ os campos que mudaram naquela versão (legenda, ritmo e o resto que você ajustou ficam)."""
    versao = int(pr.get("versao") or 1)
    d = os.path.join(raiz(base), "canais")
    for cid in os.listdir(d) if os.path.isdir(d) else []:
        try:
            c = carregar_canal(base, cid)
        except (CurtoErro, OSError, ValueError):
            continue
        if c.get("perfil_origem") != chave or int(c.get("perfil_versao") or 1) >= versao:
            continue
        for v in range(int(c.get("perfil_versao") or 1) + 1, versao + 1):
            for campo in (pr.get("atualiza") or {}).get(str(v)) or []:
                if campo in (pr.get("perfil") or {}):
                    c["perfil"][campo] = json.loads(json.dumps(pr["perfil"][campo]))
        c["perfil"] = normalizar_perfil(c["perfil"])
        c["perfil_versao"] = versao
        salvar_canal(base, c)


def listar_canais(base: str) -> List[Dict[str, Any]]:
    d = os.path.join(raiz(base), "canais")
    out = []
    for cid in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        try:
            c = carregar_canal(base, cid)
        except (CurtoErro, OSError, ValueError):
            continue
        refs = c.get("referencias") or []
        out.append({"id": c["id"], "nome": c["nome"], "refs": len(refs),
                    "analisadas": sum(1 for r in refs if r.get("estado") == "pronta"),
                    "perfil_ia": bool(c.get("perfil_ia")), "atualizado": c.get("atualizado") or 0,
                    "modelo": c.get("modelo") or "noticia"})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir_canal(base: str, cid: str) -> None:
    shutil.rmtree(pasta_canal(base, cid), ignore_errors=True)


def adicionar_midia_canal(base: str, c: Dict[str, Any], caminho: str, tipo: str, descricao: str = "") -> Dict[str, Any]:
    """😂 Meme/bordão/vinheta que o canal usa SEMPRE (ex.: a reação de sempre, a vinheta de abertura):
    sobe uma vez e entra em todos os curtos do canal como K1, K2…"""
    c.setdefault("midias", [])
    n = [int(m["id"][1:]) for m in c["midias"] if m["id"][1:].isdigit()]
    mid = f"K{1 + max(n or [0])}"
    d = os.path.join(pasta_canal(base, c["id"]), "midias")
    os.makedirs(d, exist_ok=True)
    destino = os.path.join(d, mid.lower() + (os.path.splitext(caminho)[1].lower() or ".mp4"))
    if os.path.abspath(caminho) != os.path.abspath(destino):
        shutil.move(caminho, destino)
    m = {"id": mid, "arquivo": os.path.relpath(destino, pasta_canal(base, c["id"])).replace("\\", "/"), "tipo": tipo,
         "descricao": " ".join(str(descricao or "").split())[:400]}
    c["midias"].append(m)
    return m


def midias_do_canal(base: str, c: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for m in (c or {}).get("midias") or []:
        cam = os.path.join(pasta_canal(base, c["id"]), m.get("arquivo") or "_")
        if os.path.isfile(cam):
            out.append(dict(m, caminho=cam))
    return out


def normalizar_perfil(p: Any) -> Dict[str, Any]:
    """Perfil completo (os campos que faltam vêm do padrão) e a legenda num preset válido do editor."""
    out = json.loads(json.dumps(PERFIL_PADRAO))
    if isinstance(p, dict):
        for k, v in p.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            elif v is not None:
                out[k] = v
    try:
        import dp_legendas
        leg = dict(out["legenda"])
        leg["ativa"] = out["legenda"].get("ativa", True) is not False
        out["legenda"] = dp_legendas.normalizar(leg)
    except Exception:  # noqa: BLE001
        pass
    try:
        out["duracao_alvo_s"] = max(10, min(180, int(float(out.get("duracao_alvo_s") or 45))))
    except (TypeError, ValueError):
        out["duracao_alvo_s"] = 45
    r = out["ritmo"]
    for k, lo, hi, pad in (("plano_medio_s", 0.5, 8.0, 1.8), ("palavras_por_s", 1.2, 5.0, 2.8), ("pausa_max_s", 0.1, 1.5, 0.3)):
        try:
            r[k] = round(max(lo, min(hi, float(r.get(k) or pad))), 2)
        except (TypeError, ValueError):
            r[k] = pad
    s = out["sfx"]
    s["tipos_preferidos"] = [t for t in (s.get("tipos_preferidos") or []) if t in TIPOS_SFX] or ["whoosh", "impacto", "pop"]
    try:
        s["volume"] = round(max(0.1, min(2.0, float(s.get("volume") or 0.8))), 2)
    except (TypeError, ValueError):
        s["volume"] = 0.8
    for k in ("estrutura", "composicoes", "evitar"):
        if not isinstance(out.get(k), list):
            out[k] = []
    an = out.get("anime") if isinstance(out.get("anime"), dict) else {}
    out["anime"] = {"modo": an.get("modo") if an.get("modo") in MODOS_ANIME else "nao", "obras": str(an.get("obras") or "")[:300]}
    tt = out["textos_tela"]
    try:
        import dp_destaques
        if not dp_destaques.estilo(str(tt.get("estilo_destaque") or "")):
            tt["estilo_destaque"] = "impacto_red" if dp_destaques.estilo("impacto_red") else "branco"
    except Exception:  # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------------ 🎞 referências (medição)
def _rodar(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")


def sondar(video: str) -> Dict[str, Any]:
    """duração, largura, altura, fps e se tem áudio."""
    r = _rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate",
                "-of", "json", video], 60)
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        d = {}
    dur = float((d.get("format") or {}).get("duration") or 0)
    w = h = 0
    fps = 0.0
    audio = False
    for s in d.get("streams") or []:
        if s.get("codec_type") == "video" and not w:
            w, h = int(s.get("width") or 0), int(s.get("height") or 0)
            try:
                a, b = str(s.get("avg_frame_rate") or "0/1").split("/")
                fps = round(float(a) / float(b or 1), 2) if float(b or 1) else 0.0
            except (ValueError, ZeroDivisionError):
                fps = 0.0
        elif s.get("codec_type") == "audio":
            audio = True
    if dur <= 0:
        raise CurtoErro("Não consegui ler esse vídeo (ffprobe).")
    return {"dur": round(dur, 3), "largura": w, "altura": h, "fps": fps, "tem_audio": audio,
            "vertical": h > w if w and h else None}


def detectar_cortes(video: str, fps: int = 8, minimo: float = 0.3, limiar: float = 9.0) -> List[float]:
    """Instantes (s) das trocas de plano, olhando o vídeo a `fps` quadros/s (edição de short é rápida: o filtro de cena
    padrão perdia metade dos cortes). Corte = um PICO de diferença entre quadros vizinhos bem acima do que vem antes e
    depois (movimento de câmera dá diferença alta mas contínua, não pico); a fusão rápida (~0,25 s) é pega comparando
    quadros a 2 passos. Sem numpy: cai no filtro de cena do ffmpeg."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return _cortes_ffmpeg(video, LIMIAR_CENA, minimo)
    w, h = 48, 86
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-an", "-vf", f"fps={fps},scale={w}:{h},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True, timeout=900)
    n = len(r.stdout) // (w * h)
    if n < 3:
        return []
    x = np.frombuffer(r.stdout[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    candidatos: List[Tuple[float, float]] = []
    for passo in (1, 2):
        d = np.abs(x[passo:] - x[:-passo]).mean(axis=(1, 2))
        for i in range(len(d)):
            viz = np.concatenate([d[max(0, i - 3 - passo):max(0, i - passo + 1)], d[i + passo: i + 3 + passo]])
            base = float(np.median(viz)) if len(viz) else 0.0
            fator = 2.2 if passo == 1 else 2.6
            if d[i] >= limiar * (1 if passo == 1 else 1.3) and d[i] >= fator * base + 2:
                candidatos.append(((i + passo / 2 + 0.5) / fps, float(d[i])))
    out: List[float] = []
    for t, _forca in sorted(candidatos):
        if t < minimo:
            continue
        if out and t - out[-1] < max(minimo, 0.4):
            continue
        out.append(round(t, 3))
    return out


def _cortes_ffmpeg(video: str, limiar: float = LIMIAR_CENA, minimo: float = 0.25) -> List[float]:
    r = _rodar(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-an", "-vf",
                f"scale=192:-2,select='gt(scene,{limiar})',showinfo", "-f", "null", "-"], 900)
    out: List[float] = []
    for t in sorted(float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr or "")):
        if t >= minimo and (not out or t - out[-1] >= minimo):
            out.append(round(t, 3))
    return out


def folhas_densas(video: str, destino: str, dur: float, fps: float = 4.0, colunas: int = 8, linhas: int = 5,
                  largura: int = 135, max_folhas: int = 8) -> List[str]:
    """O vídeo INTEIRO a `fps` quadros/s, em folhas de colunas×linhas (cada folha = colunas×linhas/fps segundos).
    Vídeo longo demais pro limite de folhas: baixa o fps pra caber. É o que a IA lê pra ver o ritmo, as legendas e as fusões."""
    por_folha = colunas * linhas
    fps = min(fps, max_folhas * por_folha / max(1.0, dur))
    os.makedirs(destino, exist_ok=True)
    for velho in os.listdir(destino):
        if velho.startswith("densa_"):
            os.remove(os.path.join(destino, velho))
    _rodar(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf",
            f"fps={fps:.4f},scale={largura}:-2,drawtext=text='%{{pts\\:hms}}':x=3:y=3:fontsize=11:fontcolor=yellow:box=1:boxcolor=black@0.6,"
            f"tile={colunas}x{linhas}", "-q:v", "4", os.path.join(destino, "densa_%02d.jpg")], 900)
    folhas = sorted(os.path.join(destino, f) for f in os.listdir(destino) if f.startswith("densa_"))
    if not folhas:  # drawtext sem fonte (alguns ffmpeg do Windows): sem o relógio
        _rodar(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"fps={fps:.4f},scale={largura}:-2,tile={colunas}x{linhas}",
                "-q:v", "4", os.path.join(destino, "densa_%02d.jpg")], 900)
        folhas = sorted(os.path.join(destino, f) for f in os.listdir(destino) if f.startswith("densa_"))
    return folhas[:max_folhas]


def planos(cortes: List[float], dur: float) -> List[Tuple[float, float]]:
    marcos = [0.0] + [c for c in cortes if 0 < c < dur] + [dur]
    return [(marcos[i], marcos[i + 1]) for i in range(len(marcos) - 1) if marcos[i + 1] - marcos[i] > 0.01]


def envelope(caminho: str, janela: float = 0.05, taxa: int = 8000) -> List[float]:
    """Energia (dBFS) do áudio em janelas de `janela` s. Lista vazia se não tem áudio."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return []
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", caminho, "-vn", "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"],
                       capture_output=True, timeout=600)
    if not r.stdout:
        return []
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    n = max(1, int(taxa * janela))
    k = len(x) // n
    if k == 0:
        return []
    x = x[: k * n].reshape(k, n)
    rms = np.sqrt(np.mean(x * x, axis=1) + 1e-12)
    return [round(float(v), 1) for v in 20 * np.log10(rms)]


def metricas_audio(env: List[float], palavras: List[Dict[str, Any]], cortes: List[float], janela: float = 0.05) -> Dict[str, Any]:
    """O que dá pra OUVIR sem ouvido: música de fundo (energia nos buracos entre as palavras) e
    som nos cortes (um pico de energia junto da troca de plano, acima do que vinha antes)."""
    if not env:
        return {"musica_fundo": None, "nivel_buracos_db": None, "sfx_nos_cortes": None, "transientes": 0}
    n = len(env)
    fala = [False] * n
    for w in palavras or []:
        a, b = int(float(w["start"]) / janela), int(math.ceil(float(w["end"]) / janela))
        for i in range(max(0, a - 1), min(n, b + 1)):
            fala[i] = True
    buracos = [env[i] for i in range(n) if not fala[i]]
    nivel = statistics.median(buracos) if len(buracos) >= 10 else None
    musica = None if nivel is None else bool(nivel > -42.0)
    # transientes: salto ≥ 8 dB sobre a média dos 300 ms anteriores
    trans = []
    for i in range(6, n):
        antes = sum(env[i - 6:i]) / 6
        if env[i] - antes >= 8.0 and env[i] > -30:
            if not trans or i - trans[-1] > 4:
                trans.append(i)
    tt = [i * janela for i in trans]
    com_som = sum(1 for c in cortes if any(abs(c - t) <= 0.18 for t in tt))
    return {"musica_fundo": musica, "nivel_buracos_db": None if nivel is None else round(nivel, 1),
            "sfx_nos_cortes": round(com_som / len(cortes), 2) if cortes else None, "transientes": len(tt)}


def metricas_fala(palavras: List[Dict[str, Any]], dur: float) -> Dict[str, Any]:
    if not palavras:
        return {"palavras": 0, "palavras_por_s": None, "primeira_fala_s": None, "ultima_fala_s": None,
                "pausa_media_s": None, "gancho": ""}
    ini, fim = float(palavras[0]["start"]), float(palavras[-1]["end"])
    pausas = [float(palavras[i + 1]["start"]) - float(palavras[i]["end"]) for i in range(len(palavras) - 1)]
    pausas = [p for p in pausas if p > 0.05]
    gancho = " ".join(str(w["word"]).strip() for w in palavras if float(w["start"]) < ini + 3.2)
    return {"palavras": len(palavras), "palavras_por_s": round(len(palavras) / max(0.5, fim - ini), 2),
            "primeira_fala_s": round(ini, 2), "ultima_fala_s": round(fim, 2), "silencio_final_s": round(max(0.0, dur - fim), 2),
            "pausa_media_s": round(statistics.mean(pausas), 2) if pausas else 0.0,
            "pausas_longas": sum(1 for p in pausas if p > 0.45), "gancho": gancho[:300]}


def folha_de_contato(video: str, trechos: List[Tuple[float, float]], destino: str, colunas: int = 5,
                     largura_quadro: int = 216) -> Tuple[str, List[str]]:
    """Um quadro do meio de cada plano (até MAX_QUADROS_FOLHA, espalhados), com o tempo escrito embaixo,
    numa imagem só (é o que a IA olha). Devolve (folha.jpg, [quadros])."""
    from PIL import Image, ImageDraw
    os.makedirs(destino, exist_ok=True)
    if len(trechos) > MAX_QUADROS_FOLHA:
        passo = len(trechos) / MAX_QUADROS_FOLHA
        trechos = [trechos[int(i * passo)] for i in range(MAX_QUADROS_FOLHA)]
    quadros: List[Tuple[str, float]] = []
    for k, (a, b) in enumerate(trechos):
        t = a + (b - a) * 0.5
        saida = os.path.join(destino, f"q{k:02d}.jpg")
        _rodar(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                "-vf", f"scale={largura_quadro}:-2", "-q:v", "4", saida], 60)
        if os.path.isfile(saida):
            quadros.append((saida, t))
    if not quadros:
        raise CurtoErro("Não consegui tirar quadros do vídeo.")
    ims = [Image.open(q).convert("RGB") for q, _t in quadros]
    h = max(i.height for i in ims)
    lin = math.ceil(len(ims) / colunas)
    rot = 22
    tela = Image.new("RGB", (colunas * largura_quadro, lin * (h + rot)), (16, 16, 16))
    dr = ImageDraw.Draw(tela)
    for k, (im, (_q, t)) in enumerate(zip(ims, quadros)):
        x, y = (k % colunas) * largura_quadro, (k // colunas) * (h + rot)
        tela.paste(im, (x, y))
        dr.text((x + 6, y + h + 4), f"#{k + 1}  {t:.1f}s", fill=(250, 220, 80))
    folha = os.path.join(destino, "folha.jpg")
    tela.save(folha, quality=82)
    return folha, [q for q, _t in quadros]


def adicionar_referencia(base: str, c: Dict[str, Any], arquivo: str = "", link: str = "", titulo: str = "") -> Dict[str, Any]:
    if len(c["referencias"]) >= MAX_REFERENCIAS:
        raise CurtoErro(f"No máximo {MAX_REFERENCIAS} vídeos de referência por canal.")
    rid = "R" + str(1 + max([int(r["id"][1:]) for r in c["referencias"] if r["id"][1:].isdigit()] or [0]))
    r = {"id": rid, "titulo": (titulo or os.path.basename(arquivo) or link)[:160], "link": link[:500], "arquivo": "",
         "estado": "na fila", "erro": None, "medidas": {}, "transcricao": {}, "ficha": None, "criado": _hoje()}
    if arquivo:
        destino_dir = os.path.join(pasta_canal(base, c["id"]), "refs", rid)
        os.makedirs(destino_dir, exist_ok=True)
        ext = os.path.splitext(arquivo)[1].lower() or ".mp4"
        destino = os.path.join(destino_dir, "video" + ext)
        if os.path.abspath(arquivo) != os.path.abspath(destino):
            shutil.move(arquivo, destino)
        r["arquivo"] = os.path.relpath(destino, pasta_canal(base, c["id"])).replace("\\", "/")
    elif not link:
        raise CurtoErro("Mande o arquivo ou o link do vídeo.")
    c["referencias"].append(r)
    return r


def caminho_ref(base: str, c: Dict[str, Any], r: Dict[str, Any]) -> Optional[str]:
    if not r.get("arquivo"):
        return None
    cam = os.path.join(pasta_canal(base, c["id"]), r["arquivo"])
    return cam if os.path.isfile(cam) else None


def baixar_referencia(base: str, cid: str, rid: str, baixador: Optional[Callable[[str, str], Dict[str, Any]]] = None) -> str:
    """Link (YouTube Shorts, TikTok, Instagram, Kwai… — o yt-dlp) → arquivo da referência."""
    c = carregar_canal(base, cid)
    r = next((x for x in c["referencias"] if x["id"] == rid), None)
    if not r or not r.get("link"):
        raise CurtoErro("Referência sem link.")
    destino_dir = os.path.join(pasta_canal(base, cid), "refs", rid)
    os.makedirs(destino_dir, exist_ok=True)
    if baixador is None:
        import youtube_clipper
        baixador = lambda u, d: youtube_clipper.baixar_video(u, d, qualidade="720p")  # noqa: E731
    info = baixador(r["link"], destino_dir) or {}
    cam = info.get("caminho")
    if not cam or not os.path.isfile(cam):
        raise CurtoErro("Não consegui baixar o vídeo desse link.")
    with _TRAVA:
        c = carregar_canal(base, cid)
        r = next(x for x in c["referencias"] if x["id"] == rid)
        r["arquivo"] = os.path.relpath(cam, pasta_canal(base, cid)).replace("\\", "/")
        if info.get("titulo") and (not r.get("titulo") or r["titulo"] == r.get("link")):
            r["titulo"] = str(info["titulo"])[:160]
        salvar_canal(base, c)
    return cam


def medir_referencia(base: str, cid: str, rid: str, transcrever: Optional[Callable[..., List[Dict[str, Any]]]] = None,
                     on_log: Callable[[str], None] = lambda _m: None) -> Dict[str, Any]:
    """Mede a referência (sem IA): planos, folha de contato, fala (Whisper) e áudio."""
    c = carregar_canal(base, cid)
    r = next((x for x in c["referencias"] if x["id"] == rid), None)
    if not r:
        raise CurtoErro("Referência não encontrada.")
    if not caminho_ref(base, c, r) and r.get("link"):
        on_log(f"⬇ {rid}: baixando…")
        baixar_referencia(base, cid, rid)
        c = carregar_canal(base, cid)
        r = next(x for x in c["referencias"] if x["id"] == rid)
    video = caminho_ref(base, c, r)
    if not video:
        raise CurtoErro("O arquivo dessa referência sumiu.")
    pr = os.path.join(pasta_canal(base, cid), "refs", rid)
    on_log(f"📏 {rid}: medindo os planos…")
    info = sondar(video)
    cortes = detectar_cortes(video)
    tr = planos(cortes, info["dur"])
    durs = [b - a for a, b in tr]
    folha, quadros = folha_de_contato(video, tr, os.path.join(pr, "quadros"))
    on_log(f"🎞 {rid}: folhas a 4 quadros/s…")
    densas = folhas_densas(video, os.path.join(pr, "quadros"), info["dur"])
    palavras: List[Dict[str, Any]] = []
    texto = ""
    idioma = c.get("idioma") or None
    if info["tem_audio"] and transcrever:
        on_log(f"📝 {rid}: transcrevendo…")
        audio = os.path.join(pr, "audio.wav")
        _rodar(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", audio], 300)
        try:
            meta: Dict[str, Any] = {}
            segs = transcrever(audio, language=idioma, word_timestamps=True, info=meta)
            palavras = [w for s in segs for w in s.get("words") or []]
            texto = " ".join(s.get("text", "").strip() for s in segs).strip()
            if meta.get("language") and not c.get("idioma"):
                idioma = meta["language"]
        except Exception as exc:  # noqa: BLE001 — sem fala (só música) também cai aqui
            on_log(f"⚠ {rid}: transcrição: {str(exc)[:120]}")
    env = envelope(video) if info["tem_audio"] else []
    medidas = dict(info)
    medidas.update({
        "cortes": cortes, "n_planos": len(tr),
        "plano_medio_s": round(statistics.mean(durs), 2) if durs else None,
        "plano_mediano_s": round(statistics.median(durs), 2) if durs else None,
        "plano_mais_longo_s": round(max(durs), 2) if durs else None,
        "cortes_por_s": round(len(cortes) / info["dur"], 2) if info["dur"] else None,
        "primeiro_corte_s": cortes[0] if cortes else None,
    })
    medidas.update(metricas_fala(palavras, info["dur"]))
    medidas.update(metricas_audio(env, palavras, cortes))
    with _TRAVA:
        c = carregar_canal(base, cid)
        r = next(x for x in c["referencias"] if x["id"] == rid)
        r["medidas"] = medidas
        r["transcricao"] = {"texto": texto, "palavras": palavras}
        r["folha"] = os.path.relpath(folha, pasta_canal(base, cid)).replace("\\", "/")
        r["quadros"] = [os.path.relpath(q, pasta_canal(base, cid)).replace("\\", "/") for q in quadros]
        r["densas"] = [os.path.relpath(q, pasta_canal(base, cid)).replace("\\", "/") for q in densas]
        if idioma and not c.get("idioma"):
            c["idioma"] = idioma
        r["estado"] = "medida"
        r["erro"] = None
        salvar_canal(base, c)
    return medidas


# ------------------------------------------------------------------ 🤖 schemas
def _o(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _s() -> Dict[str, Any]:
    return {"type": "string"}


def _ls() -> Dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _n() -> Dict[str, Any]:
    return {"type": "number"}


def _b() -> Dict[str, Any]:
    return {"type": "boolean"}


FICHA_SCHEMA = _o({
    "resumo": _s(),
    "gancho": _o({"texto": _s(), "tipo": _s(), "visual": _s(), "por_que_prende": _s()}),
    "estrutura": {"type": "array", "items": _o({"parte": _s(), "de_s": _n(), "ate_s": _n(), "o_que": _s()})},
    "composicoes": {"type": "array", "items": _o({"nome": _s(), "descricao": _s(), "layout": {"type": "string", "enum": list(LAYOUTS)},
                                                  "quadros": {"type": "array", "items": {"type": "integer"}}})},
    "legenda": _o({"tem": _b(), "descricao": _s(), "posicao": {"type": "string", "enum": ["base", "meio", "topo"]},
                   "maiusculas": _b(), "palavras_por_vez": {"type": "integer"}, "cor_texto": _s(), "cor_destaque": _s()}),
    "textos_tela": _o({"tem": _b(), "descricao": _s(), "exemplos": _ls()}),
    "movimento": _s(),
    "tom": _s(),
    "cta": _s(),
    "pontos_fortes": _ls(),
})

FICHA_SYS = (
    "Você é editor-chefe de vídeos curtos (YouTube Shorts, Reels, TikTok) de NOTÍCIAS e analisa um vídeo de referência de um "
    "canal pra que outros vídeos sejam feitos no MESMO estilo. Você recebe: a FOLHA DE CONTATO (um quadro do meio de cada plano, "
    "na ordem, com o número e o segundo embaixo), as FOLHAS DENSAS (o vídeo inteiro a ~4 quadros/s, pra ver o ritmo REAL: a cada "
    "quanto a legenda troca, fusões rápidas, zooms, imagens que trocam dentro de um mesmo fundo), as MEDIDAS feitas por código (duração, cortes, ritmo da fala, música de fundo, "
    "som nos cortes) e a TRANSCRIÇÃO com o tempo. Seja concreto e operacional: o que se vê em cada tipo de plano (enquadramento, "
    "foto x vídeo, pessoa real, print/manchete, texto grande, tela dividida, zoom), como é a legenda (posição, maiúsculas, quantas "
    "palavras por vez, cores), os textos na tela, o gancho dos 3 primeiros segundos e a estrutura da fala. 'layout' de cada "
    "composição = o mais próximo destes, que o editor sabe montar: " + "; ".join(f"{k} = {v[1]}" for k, v in LAYOUTS.items())
    + ". 'quadros' = os números da folha que mostram aquela composição. Cores em #RRGGBB. Responda em português.")

PERFIL_SCHEMA = _o({
    "resumo": _s(),
    "duracao_alvo_s": {"type": "integer"},
    "ritmo": _o({"plano_medio_s": _n(), "palavras_por_s": _n(), "cortes": _s(), "pausa_max_s": _n()}),
    "gancho": _o({"descricao": _s(), "duracao_s": _n(), "exemplos": _ls()}),
    "estrutura": {"type": "array", "items": _o({"funcao": {"type": "string", "enum": list(FUNCOES_BLOCO)}, "descricao": _s(),
                                                "segundos": _n()})},
    "tom": _s(),
    "linguagem": _s(),
    "composicoes": {"type": "array", "items": _o({"id": _s(), "nome": _s(), "layout": {"type": "string", "enum": list(LAYOUTS)},
                                                  "descricao": _s(), "quando": _s()})},
    "textos_tela": _o({"usa": _b(), "descricao": _s(), "estilo_destaque": _s(), "frequencia": _s()}),
    "legenda": _o({"estilo": _s(), "posicao": {"type": "string", "enum": ["base", "meio", "topo"]}, "maiusculas": _b(),
                   "max_palavras": {"type": "integer"}, "cor_texto": _s(), "cor_ativa": _s(), "tamanho": _n()}),
    "sfx": _o({"usa": _b(), "nos_cortes": _b(), "descricao": _s(),
               "tipos_preferidos": {"type": "array", "items": {"type": "string", "enum": list(TIPOS_SFX)}}}),
    "musica": _o({"usa": _b(), "descricao": _s()}),
    "cta": _o({"texto": _s(), "onde": _s()}),
    "gancho_maiusculas": _b(),
    "ponto_de_vista": _o({"usa": _b(), "descricao": _s()}),
    "titulos": _o({"descricao": _s(), "exemplos": _ls()}),
    "evitar": _ls(),
})


def _catalogo_legendas() -> str:
    try:
        import dp_legendas
        return ", ".join(f"{e['id']} ({e['nome']})" for e in dp_legendas.ESTILOS)
    except Exception:  # noqa: BLE001
        return "classico, pop, contorno, caixa, destaque"


def _catalogo_destaques(limite: int = 40) -> str:
    try:
        import dp_destaques
        return "\n".join(dp_destaques.bloco_para_prompt().splitlines()[:limite])
    except Exception:  # noqa: BLE001
        return "- impacto_red | destaque | 1-5 palavras | frase de impacto em vermelho"


PERFIL_SYS = (
    "Você monta o GUIA DE ESTILO de um canal de vídeos curtos de notícias a partir das fichas e medidas de vários vídeos dele. "
    "O guia será usado por outra IA pra escrever roteiros NOVOS no mesmo estilo e pelo editor de vídeo pra montar. Generalize o que "
    "se repete (não descreva um vídeo só), com números (use as MEDIDAS: são medidas de verdade, não chute). "
    "'estrutura' = a sequência típica de blocos (função + o que faz + quantos segundos). 'composicoes' = 3 a 8 composições "
    "visuais recorrentes, cada uma com um 'id' curto (letras minúsculas e _), o 'layout' mais próximo do que o editor monta "
    "e QUANDO usar. 'legenda.estilo' = um destes presets do editor: {legendas}. 'textos_tela.estilo_destaque' = o id de UM "
    "estilo de destaque desta lista que mais se parece com os textos grandes do canal:\n{destaques}\n"
    "'ritmo.pausa_max_s' = a maior pausa entre frases que o canal deixa (pausas maiores são cortadas). 'gancho.exemplos' e "
    "'titulos.exemplos' = frases REAIS dos vídeos. 'evitar' = o que quebraria o estilo. Responda em português; os exemplos, "
    "no idioma do canal.")


# ------------------------------------------------------------------ 🤖 ficha de cada referência
def _texto_medidas(m: Dict[str, Any]) -> str:
    pedacos = [f"duração {m.get('dur')} s", f"{m.get('largura')}x{m.get('altura')}", f"{m.get('n_planos')} planos",
               f"plano médio {m.get('plano_medio_s')} s (mediano {m.get('plano_mediano_s')} s, mais longo {m.get('plano_mais_longo_s')} s)",
               f"{m.get('cortes_por_s')} cortes/s", f"1ª fala em {m.get('primeira_fala_s')} s",
               f"{m.get('palavras_por_s')} palavras/s", f"pausa média {m.get('pausa_media_s')} s",
               f"silêncio no fim {m.get('silencio_final_s')} s"]
    if m.get("musica_fundo") is not None:
        pedacos.append(("tem" if m["musica_fundo"] else "NÃO tem") + f" música/fundo sonoro nos buracos da fala ({m.get('nivel_buracos_db')} dB)")
    if m.get("sfx_nos_cortes") is not None:
        pedacos.append(f"{int(round(100 * m['sfx_nos_cortes']))}% dos cortes têm um pico de som junto (whoosh/impacto)")
    return " · ".join(pedacos)


def _transcricao_com_tempo(palavras: List[Dict[str, Any]], passo: float = 2.5, limite: int = 4000) -> str:
    linhas, atual, t0 = [], [], None
    for w in palavras:
        if t0 is None:
            t0 = float(w["start"])
        atual.append(str(w["word"]).strip())
        if float(w["end"]) - t0 >= passo:
            linhas.append(f"[{t0:.1f}s] {' '.join(atual)}")
            atual, t0 = [], None
    if atual:
        linhas.append(f"[{t0:.1f}s] {' '.join(atual)}")
    return "\n".join(linhas)[:limite]


def conteudo_ficha(base: str, c: Dict[str, Any], r: Dict[str, Any]) -> List[Dict[str, Any]]:
    import ia_servico
    blocos: List[Dict[str, Any]] = []
    if r.get("folha"):
        b = ia_servico.imagem_bloco(os.path.join(pasta_canal(base, c["id"]), r["folha"]), largura=1100)
        if b:
            blocos.append({"type": "text", "text": "FOLHA 1 — um quadro do meio de cada plano:"})
            blocos.append(b)
    for k, d in enumerate(r.get("densas") or []):
        b = ia_servico.imagem_bloco(os.path.join(pasta_canal(base, c["id"]), d), largura=1080)
        if b:
            blocos.append({"type": "text", "text": f"FOLHA DENSA {k + 1} — o vídeo a ~4 quadros por segundo, em ordem (esquerda→direita, "
                                                   "linha por linha), com o relógio no canto:"})
            blocos.append(b)
    m = r.get("medidas") or {}
    blocos.append({"type": "text", "text": f"Canal: {c['nome']}\nVídeo: {r.get('titulo')}\n\nMEDIDAS: {_texto_medidas(m)}\n\n"
                                            f"Cortes (s): {', '.join(str(x) for x in (m.get('cortes') or [])[:80])}\n\n"
                                            f"TRANSCRIÇÃO:\n{_transcricao_com_tempo((r.get('transcricao') or {}).get('palavras') or []) or '(sem fala)'}"})
    return blocos


def fichar_referencia(base: str, cid: str, rid: str, chamar: Optional[Callable[..., Any]] = None) -> Optional[Dict[str, Any]]:
    c = carregar_canal(base, cid)
    r = next((x for x in c["referencias"] if x["id"] == rid), None)
    if not r or not r.get("medidas"):
        raise CurtoErro("Meça o vídeo antes (📏).")
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    ficha = chamar("curtos", FICHA_SYS, conteudo_ficha(base, c, r), schema=FICHA_SCHEMA, max_tokens=2500, job=cid)
    with _TRAVA:
        c = carregar_canal(base, cid)
        r = next(x for x in c["referencias"] if x["id"] == rid)
        if ficha:
            r["ficha"] = ficha
        r["estado"] = "pronta"
        salvar_canal(base, c)
    return ficha


def analisar_referencia(base: str, cid: str, rid: str, transcrever=None, chamar=None, usar_ia: bool = True,
                        on_log: Callable[[str], None] = lambda _m: None) -> None:
    try:
        with _TRAVA:
            c = carregar_canal(base, cid)
            r = next(x for x in c["referencias"] if x["id"] == rid)
            r["estado"], r["erro"] = "analisando", None
            salvar_canal(base, c)
        medir_referencia(base, cid, rid, transcrever, on_log)
        if usar_ia:
            on_log(f"🤖 {rid}: a IA está olhando os planos…")
            fichar_referencia(base, cid, rid, chamar)
        else:
            with _TRAVA:
                c = carregar_canal(base, cid)
                next(x for x in c["referencias"] if x["id"] == rid)["estado"] = "pronta"
                salvar_canal(base, c)
    except Exception as exc:  # noqa: BLE001
        with _TRAVA:
            try:
                c = carregar_canal(base, cid)
                r = next(x for x in c["referencias"] if x["id"] == rid)
                r["estado"], r["erro"] = "erro", str(exc)[:400]
                salvar_canal(base, c)
            except Exception:  # noqa: BLE001
                pass
        raise


# ------------------------------------------------------------------ 🧬 perfil do canal
def _mediana(xs: Iterable[Any]) -> Optional[float]:
    v = [float(x) for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(v), 2) if v else None


def metricas_canal(c: Dict[str, Any]) -> Dict[str, Any]:
    ms = [r.get("medidas") or {} for r in c.get("referencias") or [] if r.get("medidas")]
    if not ms:
        return {}
    bools = lambda k: [m[k] for m in ms if isinstance(m.get(k), bool)]  # noqa: E731
    mus = bools("musica_fundo")
    vert = bools("vertical")
    return {
        "videos": len(ms),
        "dur": _mediana(m.get("dur") for m in ms),
        "plano_medio_s": _mediana(m.get("plano_medio_s") for m in ms),
        "plano_mediano_s": _mediana(m.get("plano_mediano_s") for m in ms),
        "cortes_por_s": _mediana(m.get("cortes_por_s") for m in ms),
        "palavras_por_s": _mediana(m.get("palavras_por_s") for m in ms),
        "primeira_fala_s": _mediana(m.get("primeira_fala_s") for m in ms),
        "pausa_media_s": _mediana(m.get("pausa_media_s") for m in ms),
        "palavras": _mediana(m.get("palavras") for m in ms),
        "sfx_nos_cortes": _mediana(m.get("sfx_nos_cortes") for m in ms),
        "musica_fundo": (sum(mus) / len(mus)) if mus else None,
        "vertical": (sum(vert) / len(vert)) if vert else None,
    }


def perfil_das_medidas(c: Dict[str, Any]) -> Dict[str, Any]:
    """Sem IA: o perfil padrão com os NÚMEROS do canal (ritmo, duração, música, som nos cortes)."""
    m = metricas_canal(c)
    p = normalizar_perfil(c.get("perfil"))
    if not m:
        return p
    if m.get("dur"):
        p["duracao_alvo_s"] = int(round(m["dur"]))
    if m.get("plano_mediano_s"):
        p["ritmo"]["plano_medio_s"] = m["plano_mediano_s"]
    if m.get("palavras_por_s"):
        p["ritmo"]["palavras_por_s"] = m["palavras_por_s"]
    if m.get("pausa_media_s") is not None:
        p["ritmo"]["pausa_max_s"] = round(max(0.15, min(0.6, (m["pausa_media_s"] or 0.2) * 1.6)), 2)
    if m.get("sfx_nos_cortes") is not None:
        p["sfx"]["nos_cortes"] = m["sfx_nos_cortes"] >= 0.35
        p["sfx"]["usa"] = m["sfx_nos_cortes"] >= 0.15 or p["sfx"]["usa"]
    if m.get("musica_fundo") is not None:
        p["musica"]["usa"] = m["musica_fundo"] >= 0.5
    gs = [((r.get("medidas") or {}).get("gancho") or "") for r in c.get("referencias") or []]
    gs = [g for g in gs if g]
    if gs and not p["gancho"].get("exemplos"):
        p["gancho"]["exemplos"] = gs[:6]
    return normalizar_perfil(p)


def texto_para_perfil(c: Dict[str, Any], limite_transcricao: int = 1400) -> str:
    L = [f"CANAL: {c['nome']} (idioma {c.get('idioma') or '?'})", "",
         "MEDIDAS DO CANAL (mediana de todos os vídeos): " + json.dumps(metricas_canal(c), ensure_ascii=False), ""]
    for r in c.get("referencias") or []:
        if not r.get("medidas"):
            continue
        L.append(f"### {r['id']} — {r.get('titulo')}")
        L.append("Medidas: " + _texto_medidas(r["medidas"]))
        if r.get("ficha"):
            L.append("Ficha: " + json.dumps(r["ficha"], ensure_ascii=False))
        tx = (r.get("transcricao") or {}).get("texto") or ""
        if tx:
            L.append("Transcrição: " + tx[:limite_transcricao])
        L.append("")
    return "\n".join(L)


def _sys_perfil() -> str:
    return PERFIL_SYS.replace("{legendas}", _catalogo_legendas()).replace("{destaques}", _catalogo_destaques())


def gerar_perfil(base: str, cid: str, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    c = carregar_canal(base, cid)
    if not any(r.get("medidas") for r in c["referencias"]):
        raise CurtoErro("Analise pelo menos um vídeo de referência antes.")
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    bruto = chamar("curtos", _sys_perfil(), texto_para_perfil(c), schema=PERFIL_SCHEMA, max_tokens=4000, job=cid)
    with _TRAVA:
        c = carregar_canal(base, cid)
        base_p = perfil_das_medidas(c)
        if bruto:
            c["perfil"] = aplicar_perfil(base_p, bruto)
            c["perfil_ia"] = True
        else:
            c["perfil"] = base_p
        c["metricas"] = metricas_canal(c)
        salvar_canal(base, c)
    if not bruto:
        raise CurtoErro(motivo_ia() + " Os números do canal já entraram no perfil; use o 📋 prompt pra outra IA se quiser o resto.")
    return c["perfil"]


def aplicar_perfil(atual: Dict[str, Any], novo: Any) -> Dict[str, Any]:
    """Resposta da IA (dict ou texto JSON) por cima do perfil atual. Os números MEDIDOS só mudam se a IA mandar valor."""
    if isinstance(novo, str):
        import json_ia
        try:
            novo = json_ia.carregar(novo)
        except Exception as exc:  # noqa: BLE001
            raise CurtoErro(f"Não entendi o JSON do perfil: {exc}") from exc
    if not isinstance(novo, dict):
        raise CurtoErro("O perfil precisa ser um objeto JSON {…}.")
    out = json.loads(json.dumps(atual))
    for k, v in novo.items():
        if k not in PERFIL_PADRAO and k != "idioma":
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update({kk: vv for kk, vv in v.items() if vv not in (None, "")})
        elif v not in (None, ""):
            out[k] = v
    for comp in out.get("composicoes") or []:
        if isinstance(comp, dict):
            comp["id"] = "_".join(norm(x) for x in str(comp.get("id") or comp.get("nome") or "").replace("_", " ").split() if norm(x))[:30] or "comp"
            if comp.get("layout") not in LAYOUTS:
                comp["layout"] = "video"
    return normalizar_perfil(out)


def prompt_perfil(c: Dict[str, Any]) -> str:
    """O mesmo pedido do 🤖, pra colar em outra IA (anexe as folhas de contato, se a IA aceitar imagens)."""
    return (_sys_perfil() + "\n\n" + texto_para_perfil(c, 2500) + "\n\nResponda APENAS com um JSON neste formato (sem ```):\n"
            + json.dumps(_exemplo_schema(PERFIL_SCHEMA), ensure_ascii=False, indent=1))


def _exemplo_schema(s: Dict[str, Any]) -> Any:
    t = s.get("type")
    if t == "object":
        return {k: _exemplo_schema(v) for k, v in (s.get("properties") or {}).items()}
    if t == "array":
        return [_exemplo_schema(s.get("items") or {"type": "string"})]
    if "enum" in s:
        return "|".join(str(x) for x in s["enum"])
    return {"string": "…", "number": 0, "integer": 0, "boolean": True}.get(t, "…")


def texto_do_perfil(p: Dict[str, Any]) -> str:
    """O perfil em texto corrido (vai no prompt do roteiro)."""
    p = normalizar_perfil(p)
    L = []
    if p.get("resumo"):
        L.append(f"ESTILO: {p['resumo']}")
    r = p["ritmo"]
    L.append(f"DURAÇÃO: ~{p['duracao_alvo_s']} s · RITMO: um plano a cada ~{r['plano_medio_s']} s; fala a ~{r['palavras_por_s']} "
             f"palavras/s; {r.get('cortes') or ''}")
    g = p["gancho"]
    if g.get("descricao") or g.get("exemplos"):
        L.append(f"GANCHO (primeiros {g.get('duracao_s') or 3} s): {g.get('descricao') or ''}"
                 + (" — exemplos reais: " + " | ".join(g.get("exemplos")[:5]) if g.get("exemplos") else ""))
    if p.get("estrutura"):
        L.append("ESTRUTURA: " + " → ".join(f"{e.get('funcao')} ({e.get('segundos', '?')} s: {e.get('descricao', '')})" for e in p["estrutura"]
                                           if isinstance(e, dict)))
    if p.get("tom") or p.get("linguagem"):
        L.append(f"TOM: {p.get('tom') or ''} · LINGUAGEM: {p.get('linguagem') or ''}")
    if p.get("composicoes"):
        L.append("COMPOSIÇÕES DO CANAL:")
        for comp in p["composicoes"]:
            if isinstance(comp, dict):
                L.append(f"  - {comp.get('id')} ({comp.get('layout')}): {comp.get('nome', '')} — {comp.get('descricao', '')}. Quando: {comp.get('quando', '')}")
    t = p["textos_tela"]
    if t.get("usa"):
        L.append(f"TEXTOS NA TELA: {t.get('descricao') or ''} (frequência: {t.get('frequencia') or '?'})")
    s = p["sfx"]
    if s.get("usa"):
        L.append(f"EFEITOS SONOROS: {s.get('descricao') or ''}; preferidos: {', '.join(s['tipos_preferidos'])}"
                 + ("; som em quase todo corte" if s.get("nos_cortes") else ""))
    pv = p.get("ponto_de_vista") or {}
    if pv.get("usa"):
        L.append(f"PONTO DE VISTA (obrigatório): {pv.get('descricao') or ''}")
    if p["cta"].get("texto"):
        L.append(f"CTA ({p['cta'].get('onde') or 'final'}): {p['cta']['texto']}")
    if p["titulos"].get("descricao") or p["titulos"].get("exemplos"):
        L.append(f"TÍTULOS: {p['titulos'].get('descricao') or ''} " + " | ".join(p["titulos"].get("exemplos") or [])[:400])
    if p.get("evitar"):
        L.append("EVITAR: " + "; ".join(str(x) for x in p["evitar"]))
    return "\n".join(L)


# ------------------------------------------------------------------ ⚡ projetos
MODELOS = {"noticia": "📰 Notícia (estilo Laestro)", "comentario": "💬 Comentário (clipe viral narrado)",
           "explicativo": "📚 Explicativo (curiosidade explicada com vários vídeos)"}
MODELOS_CLIPE = ("comentario", "explicativo")  # os que montam com os vídeos que você sobe (curtos_comentario.py)
PROPORCOES = {"9:16": "📱 9:16 (vertical)", "1:1": "⬛ 1:1 (quadrado)"}
LINGUAS = {"en": "English", "pt": "Português (Brasil)", "es": "Español", "it": "Italiano", "fr": "Français", "de": "Deutsch"}


TEXTO_QUADRADO_PT = ("FORMATO: QUADRADO 1:1 (não vertical) — pense cada plano pro quadrado: o que importa no CENTRO, "
                     "nada de coisa alta e estreita que só funciona no vertical; buscas de vídeo/foto podem ser horizontais.")
TEXTO_QUADRADO_EN = ("FORMAT: SQUARE 1:1 (not vertical) — think every shot for a square frame: what matters in the CENTER; "
                     "horizontal sources work well, tall narrow shots do not.")


ESTILO_REALISTA = (". Photorealistic, looks like real footage shot on a real camera, natural light, true-to-life colors and textures, "
                   "documentary style — no illustration, no cartoon, no 3D render look, no text, no watermark")
ESTILOS_IA = {"realista": "📷 realista (parece filmado)", "livre": "🎨 livre (o que a cena pedir)"}


def estilo_ia_do(p: Dict[str, Any], perfil: Optional[Dict[str, Any]] = None) -> str:
    v = (p.get("config") or {}).get("estilo_ia") or (perfil or {}).get("estilo_ia") or ""
    return v if v in ESTILOS_IA else "livre"


def motivo_ia(recurso: str = "curtos") -> str:
    """Por que a IA não respondeu — o motivo DE VERDADE (desligada, sem crédito, resposta cortada, tempo esgotado, chave…)."""
    try:
        import ia_servico
        m = ia_servico.motivo_desligado(recurso)
        if m:
            return f"A IA está desligada aqui: {m}"
        ult = next((r for r in reversed(ia_servico._RECENTES) if r.get("recurso") == recurso and not r.get("ok")
                    and time.time() - float(r.get("quando") or 0) < 600), None)
    except Exception:  # noqa: BLE001
        ult = None
    if not ult:
        return "A IA não respondeu (sem detalhe — veja as últimas chamadas em /ia)."
    e = str(ult.get("erro") or "")
    traducao = [("max_tokens", "a resposta ficou grande demais e foi cortada"), ("refusal", "a IA se recusou a responder esse pedido"),
                ("timed out", "demorou demais (tempo esgotado)"), ("rede:", "falha de rede"), ("401", "a chave da IA é inválida (/ia)"),
                ("credit", "sem crédito na conta da IA"), ("429", "limite de uso da IA — espere um pouco"),
                ("json", "a IA respondeu fora do formato"), ("529", "a IA está sobrecarregada — tente de novo")]
    for k, t in traducao:
        if k in e.lower():
            return f"A IA não respondeu: {t} ({e[:120]})."
    return f"A IA não respondeu: {e[:200]}"


def proporcao_do(p: Dict[str, Any]) -> str:
    v = (p.get("config") or {}).get("proporcao")
    return v if v in PROPORCOES else "9:16"


def idioma_narrado(p: Dict[str, Any], perfil: Optional[Dict[str, Any]] = None) -> str:
    """O idioma da voz: no 💬/📚 é o da postagem ou o português (o que você escolheu narrar); no 📰, o do canal."""
    c = p.get("comentario") or {}
    if p.get("modelo") in MODELOS_CLIPE and c:
        return "pt" if c.get("idioma") == "pt" else (c.get("lingua_post") or "en")
    return (perfil or {}).get("idioma") or ""


# ------------------------------------------------------------------ 🏷 marca do canal (@canal por cima do vídeo)
MARCA_POSICOES = ("meio", "topo", "base", "terco", "sup_esq", "sup_dir", "inf_esq", "inf_dir", "legenda")  # legenda = ligada à legenda


def marca_padrao(nome_canal: str = "") -> Dict[str, Any]:
    slug = re.sub(r"[^a-z0-9_.]+", "", unicodedata.normalize("NFKD", str(nome_canal or "")).encode("ascii", "ignore").decode().lower())
    return {"ativa": True, "texto": f"@{slug}" if slug else "@seucanal", "posicao": "meio", "tamanho": 0.035, "opacidade": 0.5,
            "fonte": "DP Poppins", "cor": "#FFFFFF", "contorno": True, "desvio_y": 0.0,
            "lado": "acima", "distancia": 0.10}  # (a ligação com a legenda só vale com posicao "legenda")


def normalizar_marca(m: Any, nome_canal: str = "") -> Dict[str, Any]:
    out = marca_padrao(nome_canal)
    if isinstance(m, dict):
        if "ativa" in m:
            out["ativa"] = m["ativa"] is not False and str(m["ativa"]).lower() not in ("0", "false", "nao", "não", "off")
        if str(m.get("texto") or "").strip():
            out["texto"] = " ".join(str(m["texto"]).split())[:60]
        if m.get("posicao") in MARCA_POSICOES:
            out["posicao"] = m["posicao"]
        for k, lo, hi in (("tamanho", 0.012, 0.12), ("opacidade", 0.05, 1.0), ("desvio_y", -0.45, 0.45)):
            try:
                if m.get(k) not in (None, ""):
                    out[k] = round(max(lo, min(hi, float(m[k]))), 3)
            except (TypeError, ValueError):
                pass
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(m.get("cor") or "")):
            out["cor"] = m["cor"].upper()
        if str(m.get("fonte") or "").startswith("DP "):
            out["fonte"] = str(m["fonte"])[:40]
        if m.get("lado") in ("acima", "abaixo"):  # 🏷 v84_311: com posicao "legenda": X% (distancia) ou N px (distancia_px) do centro da legenda
            out["lado"] = m["lado"]
        try:
            if m.get("distancia_px") not in (None, "", 0, "0"):
                out["distancia_px"] = max(4, min(400, int(float(m["distancia_px"]))))
                out.pop("distancia", None)
            elif m.get("distancia") not in (None, ""):
                out["distancia"] = round(max(0.01, min(0.40, float(m["distancia"]) / (100 if float(m["distancia"]) > 1 else 1))), 3)
                out.pop("distancia_px", None)
        except (TypeError, ValueError):
            pass
        if "contorno" in m:
            out["contorno"] = bool(m["contorno"])
    return out


def marca_do(base: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """A marca do vídeo: a do projeto (se você mexeu) por cima da do canal."""
    c = canal_do(base, p)
    m = dict((c or {}).get("perfil", {}).get("marca") or {})
    m.update((p.get("config") or {}).get("marca") or {})
    return normalizar_marca(m, "" if (c or {}).get("perfil_origem") else (c or {}).get("nome") or "")  # canal pronto: @seucanal


def canal_do_modelo(base: str, modelo: str) -> str:
    """O canal pronto que veio do perfil daquele modelo (ex.: 💬 comentário) — o id, ou ""."""
    garantir_canais_prontos(base)
    for c in listar_canais(base):
        try:
            cc = carregar_canal(base, c["id"])
        except CurtoErro:
            continue
        if cc.get("perfil_origem") == modelo and not cc.get("nicho"):
            return cc["id"]
    for c in listar_canais(base):  # 💡 os canais de nicho (v84_256) não são o "padrão" do modelo
        try:
            cc = carregar_canal(base, c["id"])
        except CurtoErro:
            continue
        if cc.get("modelo") == modelo and not cc.get("nicho"):
            return cc["id"]
    return ""


# ------------------------------------------------------------------ 🎨 v84_302: acabamento padrão de TODOS os shorts
ACABAMENTO_PADRAO = {"arroba": "", "legenda_estilo": "", "legenda_tamanho": 0.05, "legenda_posicao": "terco",
                     "legenda_maiusculas": True, "sons_pixabay": False, "aplicar_noticia": False,
                     "legenda_altura": None, "legenda_margem": 0.10, "sons_nivel": "poucos",
                     "legenda_fonte": "", "legenda_cor": "", "legenda_cor_ativa": "", "destaques": "precisa",
                     "marca_posicao": "", "marca_lado": "acima", "marca_distancia": 10, "marca_px": 0}  # 🏷 o @ do canal (vazio = como era)
FONTES_LEGENDA = {"": "padrão (a do estilo)", "DP Inter": "Inter", "DP Poppins": "Poppins", "DP Montserrat": "Montserrat",
                  "DP Anton": "Anton", "DP Bebas Neue": "Bebas Neue", "DP Oswald": "Oswald", "DP Archivo": "Archivo",
                  "DP Barlow Condensed": "Barlow Condensed", "DP Roboto Condensed": "Roboto Condensed", "DP Fjalla One": "Fjalla One",
                  "DP Staatliches": "Staatliches", "DP Teko": "Teko", "DP Rajdhani": "Rajdhani", "DP Work Sans": "Work Sans",
                  "DP Alfa Slab One": "Alfa Slab One", "DP Abril Fatface": "Abril Fatface", "DP Playfair Display": "Playfair Display",
                  "DP Merriweather": "Merriweather", "DP Lora": "Lora", "DP Eb Garamond": "EB Garamond", "DP Cinzel": "Cinzel",
                  "DP Special Elite": "Special Elite (máquina de escrever)", "DP Jetbrains Mono": "JetBrains Mono"}
CORES_LEGENDA = {"": "padrão", "#FFFFFF": "branco", "#FFD60A": "amarelo", "#FF9500": "laranja", "#FF3B30": "vermelho",
                 "#FF2D55": "rosa", "#B388FF": "lilás", "#00E5FF": "ciano", "#39FF14": "verde neon", "#2ECC71": "verde",
                 "#1E90FF": "azul", "#000000": "preto"}


def acabamento(base: str, canal_id: str = "") -> Dict[str, Any]:
    """O acabamento padrão de todos os shorts; com canal_id, o do canal (o que ele guardou por cima do padrão) — 🎚 v84_310."""
    cam = os.path.join(raiz(base), "_acabamento.json")
    out = dict(ACABAMENTO_PADRAO)
    try:
        with open(cam, encoding="utf-8") as f:
            out.update({k: v for k, v in json.load(f).items() if k in ACABAMENTO_PADRAO})
    except (OSError, ValueError):
        pass
    if canal_id:
        try:
            out.update(carregar_canal(base, canal_id).get("acabamento") or {})
        except CurtoErro:
            pass
    return out


def limpar_acabamento(novos: Dict[str, Any]) -> Dict[str, Any]:
    """Só as chaves do acabamento, com os valores validados (fonte/cor/posição/altura/margem/sons…)."""
    out: Dict[str, Any] = {}
    for k, v in (novos or {}).items():
        if k not in ACABAMENTO_PADRAO:
            continue
        if k == "legenda_tamanho":
            try:
                v = round(max(0.03, min(0.09, float(v))), 3)
            except (TypeError, ValueError):
                continue
        elif k in ("legenda_maiusculas", "sons_pixabay", "aplicar_noticia"):
            v = v not in (False, "0", "false", "", None)
        elif k == "legenda_altura":
            try:
                v = None if v in (None, "", "0", 0, "auto") else round(max(0.05, min(0.95, float(v) / (100 if float(v) > 1 else 1))), 3)
            except (TypeError, ValueError):
                v = None
        elif k == "legenda_margem":
            try:
                v = round(max(0.0, min(0.25, float(v) / (100 if float(v) > 1 else 1))), 3)
            except (TypeError, ValueError):
                continue
        elif k == "destaques":
            v = v if v in ("precisa", "nunca", "livre") else "precisa"
        elif k == "marca_posicao":
            v = v if v in MARCA_POSICOES else ""
        elif k == "marca_lado":
            v = v if v in ("acima", "abaixo") else "acima"
        elif k in ("marca_distancia", "marca_px"):
            try:
                v = max(0, min(400 if k == "marca_px" else 40, int(float(v))))
            except (TypeError, ValueError):
                v = 0 if k == "marca_px" else 10
        elif k == "legenda_fonte":
            v = v if v in FONTES_LEGENDA else ""
        elif k in ("legenda_cor", "legenda_cor_ativa"):
            v = str(v or "").upper()
            v = v if re.fullmatch(r"#[0-9A-F]{6}", v) else ""
        elif k == "sons_nivel":
            v = v if v in ("nenhum", "poucos", "normal") else "poucos"
        elif k == "legenda_posicao":
            v = v if v in ("base", "meio", "topo", "terco") else "terco"
        else:
            v = " ".join(str(v or "").split())[:40]
        out[k] = v
    return out


def salvar_acabamento(base: str, novos: Dict[str, Any], canal_id: str = "") -> Dict[str, Any]:
    """Salva o padrão de todos (canal_id vazio) ou só o de um canal (o que não for dele segue o padrão)."""
    limpos = limpar_acabamento(novos)
    if canal_id:
        with _TRAVA:
            c = carregar_canal(base, canal_id)
            c["acabamento"] = dict(c.get("acabamento") or {}, **limpos)
            salvar_canal(base, c)
        return acabamento(base, canal_id)
    a = acabamento(base)
    a.update(limpos)
    os.makedirs(raiz(base), exist_ok=True)
    with open(os.path.join(raiz(base), "_acabamento.json"), "w", encoding="utf-8") as f:
        json.dump(a, f, ensure_ascii=False, indent=1)
    return a


def aplicar_acabamento(p: Dict[str, Any], a: Dict[str, Any]) -> None:
    """O @ do canal e a legenda do acabamento padrão entram no projeto (o perfil do canal continua valendo pro resto: fonte,
    cores…). Notícia (Laestro) só se marcado — ela tem a legenda do canal modelado."""
    cfg = p.setdefault("config", {})
    cfg["sons_nivel"] = a.get("sons_nivel") or "poucos"
    cfg["destaques"] = a.get("destaques") or "precisa"
    if a.get("marca_posicao"):  # 🏷 a posição do @ (ou ligada à legenda: X% ou N px acima/abaixo dela)
        m_ = dict(cfg.get("marca") or {}, posicao=a["marca_posicao"])
        if a["marca_posicao"] == "legenda":
            m_["lado"] = a.get("marca_lado") or "acima"
            if int(a.get("marca_px") or 0):
                m_["distancia_px"] = int(a["marca_px"])
                m_.pop("distancia", None)
            else:
                m_["distancia"] = float(a.get("marca_distancia") or 10) / 100
                m_.pop("distancia_px", None)
        cfg["marca"] = m_
    arroba = str(a.get("arroba") or "").strip()
    if arroba:
        cfg["marca"] = dict(cfg.get("marca") or {}, ativa=True, texto=arroba if arroba.startswith("@") else "@" + arroba)
    if p.get("modelo") != "noticia" or a.get("aplicar_noticia"):
        est = a.get("legenda_estilo") or ""  # vazio = o estilo do canal (só o tamanho/posição/margem mudam)
        cfg["legenda"] = {"tamanho": float(a.get("legenda_tamanho") or 0.05), "posicao": a.get("legenda_posicao") or "terco",
                          "maiusculas": bool(a.get("legenda_maiusculas", True)), "altura": a.get("legenda_altura"),
                          "margem": a.get("legenda_margem", 0.10)}
        if est:
            cfg["legenda"].update(estilo=est, max_palavras=1 if est == "palavra_unica" else 3)
        for k_a, k_l in (("legenda_fonte", "fonte"), ("legenda_cor", "cor_texto"), ("legenda_cor_ativa", "cor_ativa")):
            if a.get(k_a):  # 🎨 v84_308: vazio = o que o estilo/canal já usa (o padrão de hoje)
                cfg["legenda"][k_l] = a[k_a]


def criar(base: str, canal_id: str = "", titulo: str = "", links: Iterable[str] = (), texto: str = "",
          modelo: str = "noticia") -> Dict[str, Any]:
    if canal_id:
        carregar_canal(base, canal_id)  # confere
    p = {"id": _novo_id(), "canal_id": canal_id or "", "titulo": " ".join(str(titulo or "").split())[:120] or "Novo curto",
         "criado": _hoje(), "noticia": {"fontes": [], "texto": str(texto or "")[:60000]}, "midias": [],
         "config": {"duracao_alvo_s": 0, "extra": "", "providers": [], "voz_tts": "", "motor_perfil": "xtts",
                    "camera_exp": True},  # 🎥 v84_322: câmera experimental ligada nos vídeos novos
         "roteiro": None, "tts": None, "gravacao": None, "editor": None, "modelo": modelo if modelo in MODELOS else "noticia"}
    if p["modelo"] in MODELOS_CLIPE:
        p["config"]["motor_perfil"] = "chatterbox_turbo"
        if p["modelo"] == "explicativo":  # 💡 sugestões aceitas: foto real (buscadores), YouTube, imagem gerada
            p["config"]["providers"] = ["pexels", "pixabay", "brave", "google", "bing", "wikipedia", "youtube", "flow", "runpod"]
        p["comentario"] = {"linhas": [], "referencia": "", "idioma": "en", "lingua_post": "en"}
    for u in links:
        u = str(u or "").strip()
        if re.match(r"https?://", u) and len(p["noticia"]["fontes"]) < 8:
            p["noticia"]["fontes"].append({"url": u[:800], "estado": "na fila", "titulo": "", "texto": "", "erro": None})
    aplicar_acabamento(p, acabamento(base, canal_id or ""))  # 🎨 @ do canal + legenda padrão (o do canal, se ele tiver)
    salvar(base, p)
    return p


def salvar(base: str, p: Dict[str, Any]) -> None:
    p["atualizado"] = _hoje()
    _gravar_json(os.path.join(pasta(base, p["id"]), "projeto.json"), p)


def carregar(base: str, pid: str) -> Dict[str, Any]:
    cam = os.path.join(pasta(base, pid), "projeto.json")
    if not os.path.isfile(cam):
        raise CurtoErro("Projeto não encontrado.")
    p = _ler_json(cam)
    p.setdefault("midias", [])
    p.setdefault("config", {})
    return p


def listar(base: str) -> List[Dict[str, Any]]:
    d = os.path.join(raiz(base), "projetos")
    canais = {c["id"]: c["nome"] for c in listar_canais(base)}
    out = []
    for pid in os.listdir(d) if os.path.isdir(d) else []:
        try:
            p = carregar(base, pid)
        except (CurtoErro, OSError, ValueError):
            continue
        g = p.get("gravacao") or {}
        out.append({"id": p["id"], "titulo": p.get("titulo") or "", "canal": canais.get(p.get("canal_id") or "", ""),
                    "blocos": len((p.get("roteiro") or {}).get("blocos") or []), "gravado": bool(g.get("arquivo")),
                    "dur": g.get("dur"), "editor": (p.get("editor") or {}).get("job_id"), "atualizado": p.get("atualizado") or 0,
                    "modelo": p.get("modelo") or "noticia"})
    return sorted(out, key=lambda x: -x["atualizado"])


def excluir(base: str, pid: str) -> None:
    shutil.rmtree(pasta(base, pid), ignore_errors=True)


def nome_do_projeto(p: Dict[str, Any]) -> str:
    return f"⚡ {p.get('titulo') or 'curto'}"


def canal_do(base: str, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not p.get("canal_id"):
        return None
    try:
        return carregar_canal(base, p["canal_id"])
    except CurtoErro:
        return None


def anime_do(base: str, p: Dict[str, Any]) -> Dict[str, str]:
    """🎌 modo anime do projeto (ou o padrão do canal): {"modo": nao|reacoes|tudo, "obras": "Naruto, One Piece…"}."""
    pa = (perfil_do(base, p).get("anime") or {}) if p.get("canal_id") else {}
    cfg = p.get("config") or {}
    modo = cfg.get("modo_anime") or pa.get("modo") or "nao"
    return {"modo": modo if modo in MODOS_ANIME else "nao", "obras": str(cfg.get("anime_obras") or pa.get("obras") or "")[:300]}


REGRA_ANIME = (
    "\n## 🎌 MODO ANIME ({modo})\n"
    "Este vídeo usa CENAS DE ANIME pra exemplificar momentos e sentimentos. {quando}\n"
    "- 'anime_reacao' = um personagem de anime REAGINDO com a emoção da frase — preencha 'emocao' ({emocoes}). Use no lugar do "
    "meme de reação, a cada virada forte. Busca de emoção: rosto/corpo + emoção + contexto, ex.: 'anime girl shocked wide eyes', "
    "'anime boy laughing on floor', 'villain evil smile shadow', 'character crying in rain', 'anime facepalm embarrassed'.\n"
    "- 'anime_cena' = uma cena de anime que mostra POR COMPARAÇÃO o que acontece na notícia (metáfora visual): traição → "
    "'friend stabbing in the back', plano maligno → 'villain plotting dark room', caos → 'city destroyed explosion', humilhação → "
    "'character kneeling defeated', poder → 'aura power up scream', multidão revoltada → 'angry crowd shouting'.\n"
    "- A busca do acervo de anime é por DESCRIÇÃO VISUAL LITERAL: cena concreta e filmável, 2 a 5 palavras em inglês "
    "([personagem/tipo] + [ação/pose] + [cenário]); NUNCA conceito solto ('betrayal', 'sense of power'). 2 'alternativas' cada vez "
    "mais simples. 'obra'/'personagem' SÓ quando você tem certeza que a cena existe naquele anime (ex.: 'Naruto' + 'Naruto Uzumaki' "
    "pra 'boy crying alone in rain'); senão deixe vazio.{obras}\n"
    "- Fato REAL (quem é a pessoa, o que ela postou, o vídeo do acontecimento) continua com 'materia'/'foto_real'/'clipe_real'/"
    "'cartao_cinza' — anime é pra reação, sentimento e comparação, nunca pra fingir que mostra o fato.\n")


def _regra_anime(anime: Dict[str, str]) -> str:
    if (anime or {}).get("modo", "nao") == "nao":
        return "\nNÃO use os layouts 'anime_reacao' nem 'anime_cena' neste vídeo.\n"
    quando = ("Troque os memes de reação por 'anime_reacao' e use 'anime_cena' pra comparar; o resto segue o estilo do canal."
              if anime["modo"] == "reacoes" else
              "Use anime em TUDO que não precisa ser real: reações ('anime_reacao') e ilustrações/comparações ('anime_cena') no lugar "
              "de meme, vídeo e foto de banco.")
    obras = (f" Animes preferidos deste canal (use quando combinar, pra manter coerência): {anime['obras']}." if anime.get("obras") else "")
    return (REGRA_ANIME.replace("{modo}", MODOS_ANIME[anime["modo"]]).replace("{quando}", quando)
            .replace("{emocoes}", ", ".join(EMOCOES_ANIME)).replace("{obras}", obras))


def ids_extras(base: str, p: Dict[str, Any]) -> List[str]:
    return [m["id"] for m in midias_do_canal(base, canal_do(base, p))]


def perfil_do(base: str, p: Dict[str, Any]) -> Dict[str, Any]:
    c = canal_do(base, p)
    if not c and p.get("modelo") in MODELOS_CLIPE:  # 💬 sem canal: o perfil pronto do modelo
        pr = perfis_prontos().get(p["modelo"]) or {}
        return normalizar_perfil(pr.get("perfil"))
    return normalizar_perfil((c or {}).get("perfil"))


# ------------------------------------------------------------------ 📰 notícia e mídias
def _proximo_id(p: Dict[str, Any], letra: str) -> str:
    n = [int(m["id"][1:]) for m in p.get("midias") or [] if m["id"][:1] == letra and m["id"][1:].isdigit()]
    return f"{letra}{1 + max(n or [0])}"


def bordas_pretas(video: str, minimo: float = 0.02, quase_sempre: float = 0.90) -> Optional[Tuple[int, int, int, int]]:
    """⬛ v84_302/304: as faixas pretas FIXAS do vídeo (vídeo deitado dentro de um vertical, 4:3 dentro de 16:9…).
    Mede a faixa de cada lado em cada quadro (2 por segundo) e fica com a que existe em `quase_sempre` (90%) dos quadros —
    um flash, uma transição ou um quadro de abertura não impede mais o corte; uma faixa que só aparece numa parte do vídeo
    continua não sendo cortada. → (w, h, x, y) pra cortar, ou None."""
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
                       capture_output=True, text=True, timeout=60)
    try:
        W, H = (int(v) for v in p.stdout.strip().split(",")[:2])
    except ValueError:
        return None
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-an", "-vf", "fps=2,cropdetect=limit=24:round=2:reset=1",
                        "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    lados: Dict[str, List[int]] = {"top": [], "bottom": [], "left": [], "right": []}
    for m in re.finditer(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr or ""):
        w, h, x, y = (int(v) for v in m.groups())
        if w < W * 0.3 or h < H * 0.3 or w > W or h > H:  # quadro quase todo preto (fade): não conta
            continue
        lados["top"].append(y)
        lados["bottom"].append(max(0, H - (y + h)))
        lados["left"].append(x)
        lados["right"].append(max(0, W - (x + w)))
    if len(lados["top"]) < 3:
        return None

    def faixa(vs: List[int]) -> int:  # a faixa que existe em ~90% dos quadros (percentil 10)
        vs = sorted(vs)
        return vs[min(len(vs) - 1, int(len(vs) * (1 - quase_sempre)))]
    t, b, l, rr = faixa(lados["top"]), faixa(lados["bottom"]), faixa(lados["left"]), faixa(lados["right"])
    t, b = (t if t >= H * minimo else 0), (b if b >= H * minimo else 0)
    l, rr = (l if l >= W * minimo else 0), (rr if rr >= W * minimo else 0)
    if not (t or b or l or rr):
        return None
    w, h = (W - l - rr) // 2 * 2, (H - t - b) // 2 * 2
    if w < W * 0.3 or h < H * 0.3:
        return None
    return w, h, l, t


def aparar_bordas(video: str) -> bool:
    """Corta as bordas pretas permanentes do arquivo (no lugar). Devolve True se cortou."""
    cr = bordas_pretas(video)
    if not cr:
        return False
    w, h, x, y = cr
    tmp = video + ".sem_bordas" + os.path.splitext(video)[1]
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"crop={w}:{h}:{x}:{y}", "-c:v", "libx264", "-preset", "medium",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", tmp],
                       capture_output=True, timeout=1800)
    if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1000:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    os.replace(tmp, video)
    return True


def adicionar_midia(base: str, p: Dict[str, Any], caminho: str, tipo: str, descricao: str = "", letra: str = "M",
                    origem: str = "", aparar: Optional[bool] = None) -> Dict[str, Any]:
    if tipo == "video" and (aparar if aparar is not None else letra == "M"):
        try:
            if aparar_bordas(caminho):  # ⬛ o clipe do post vem com faixas pretas fixas (TikTok/Reels de vídeo deitado…)
                descricao = (descricao + " (bordas pretas cortadas)").strip()
        except Exception:  # noqa: BLE001  (sem ffmpeg/arquivo estranho: segue com o original)
            pass
    mid = _proximo_id(p, letra)
    d = os.path.join(pasta(base, p["id"]), "midias")
    os.makedirs(d, exist_ok=True)
    destino = os.path.join(d, mid.lower() + (os.path.splitext(caminho)[1].lower() or ".jpg"))
    if os.path.abspath(caminho) != os.path.abspath(destino):
        shutil.move(caminho, destino)
    m = {"id": mid, "arquivo": os.path.relpath(destino, pasta(base, p["id"])).replace("\\", "/"), "tipo": tipo,
         "descricao": " ".join(str(descricao or "").split())[:400], "origem": origem[:500]}
    if tipo == "video":
        m["dur"] = duracao_audio(destino)
    p["midias"].append(m)
    return m


def caminho_midia(base: str, p: Dict[str, Any], m: Dict[str, Any]) -> Optional[str]:
    cam = os.path.join(pasta(base, p["id"]), m.get("arquivo") or "_")
    return cam if os.path.isfile(cam) else None


def tipo_arquivo(nome: str) -> Optional[str]:
    ext = os.path.splitext(nome or "")[1].lower()
    return "foto" if ext in EXT_FOTO else "video" if ext in EXT_VIDEO else None


def ler_noticias(base: str, pid: str, baixar_html=None, ler_materia=None, baixar_arquivo=None, max_imagens: int = 8) -> int:
    """Lê cada link da notícia (texto + fotos, que viram I1, I2…). Devolve quantas fontes leu."""
    if baixar_html is None or ler_materia is None or baixar_arquivo is None:
        import dossies
        import vendas
        baixar_html = baixar_html or vendas.baixar_html
        ler_materia = ler_materia or dossies.ler_materia
        baixar_arquivo = baixar_arquivo or vendas.baixar_arquivo
    p = carregar(base, pid)
    lidas = 0
    for i, f in enumerate(p["noticia"]["fontes"]):
        if f.get("estado") == "lida":
            continue
        try:
            html, final = baixar_html(f["url"])
            d = ler_materia(html, final)
        except Exception as exc:  # noqa: BLE001
            with _TRAVA:
                q = carregar(base, pid)
                q["noticia"]["fontes"][i].update(estado="erro", erro=str(exc)[:300])
                salvar(base, q)
            continue
        imgs = []
        tmp = os.path.join(pasta(base, pid), "_baixando")
        for im in (d.get("imagens") or [])[:max_imagens]:
            try:
                cam, tipo = baixar_arquivo(im["url"], tmp, uuid.uuid4().hex[:8])
            except Exception:  # noqa: BLE001
                continue
            if tipo == "foto" and _foto_pequena(cam):
                os.remove(cam)
                continue
            imgs.append((cam, tipo, im.get("legenda") or "", im["url"]))
        with _TRAVA:
            q = carregar(base, pid)
            ff = q["noticia"]["fontes"][i]
            ff.update(estado="lida", erro=None, titulo=d.get("titulo") or "", site=d.get("site") or "", data=d.get("data") or "",
                      linha_fina=d.get("linha_fina") or "", texto=(d.get("texto") or "")[:20000])
            for cam, tipo, leg, url in imgs:
                adicionar_midia(base, q, cam, tipo, leg or d.get("titulo") or "", "I", url)
            if q.get("titulo") in ("", "Novo curto") and d.get("titulo"):
                q["titulo"] = d["titulo"][:120]
            salvar(base, q)
        shutil.rmtree(tmp, ignore_errors=True)
        lidas += 1
    return lidas


def _foto_pequena(cam: str) -> bool:
    try:
        from PIL import Image
        with Image.open(cam) as im:
            return min(im.size) < 220
    except Exception:  # noqa: BLE001
        return True


def midias_para_editor(base: str, p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mesmo formato do 🕵️/🛒 (app._PROJETOS_MIDIA): as mídias da notícia e as suas entram no Estúdio."""
    out = []
    for m in p.get("midias") or []:
        cam = caminho_midia(base, p, m)
        if not cam:
            continue
        out.append({"id": m["id"], "tipo": m.get("tipo") or tipo_arquivo(cam) or "foto", "caminho": cam,
                    "o_que_e": m.get("descricao") or m["id"], "usos": [], "trecho": "", "texto_na_tela": "", "transcricao": ""})
    try:
        c = canal_do(base, p) if p.get("canal_id") else None
    except Exception:  # noqa: BLE001
        c = None
    for m in midias_do_canal(base, c):
        out.append({"id": m["id"], "tipo": m.get("tipo") or tipo_arquivo(m["caminho"]) or "video", "caminho": m["caminho"],
                    "o_que_e": "😂 " + (m.get("descricao") or m["id"]), "usos": [], "trecho": "", "texto_na_tela": "", "transcricao": ""})
    return out


def bloco_prompt_editor(base: str, p: Dict[str, Any]) -> str:
    ms = [m for m in midias_para_editor(base, p) if not m["id"].startswith("C")]
    if not ms:
        return ""
    L = ["", f"## ⚡ Mídias da notícia (projeto “{p.get('titulo')}”)",
         "Fotos/vídeos REAIS do fato. Use com `\"provider\": \"material\"` e `\"query\": \"<ID>\"` quando a fala mostrar o que elas mostram."]
    L += [f"- {m['id']} ({m['tipo']}): {m['o_que_e'][:160]}" for m in ms]
    return "\n".join(L)


def texto_noticia(p: Dict[str, Any], limite: int = 9000) -> str:
    partes = []
    for f in p["noticia"].get("fontes") or []:
        if f.get("estado") == "lida":
            partes.append(f"### {f.get('titulo') or f['url']}\n({f.get('site') or ''} {f.get('data') or ''})\n"
                          f"{f.get('linha_fina') or ''}\n{f.get('texto') or ''}")
    if (p["noticia"].get("texto") or "").strip():
        partes.append("### Texto/anotações\n" + p["noticia"]["texto"].strip())
    t = "\n\n".join(partes).strip()
    return t[:limite]


# ------------------------------------------------------------------ 📝 roteiro
ROTEIRO_SCHEMA = _o({
    "titulo_video": _s(),
    "titulos_alt": _ls(),
    "descricao": _s(),
    "hashtags": _ls(),
    "blocos": {"type": "array", "items": _o({
        "funcao": {"type": "string", "enum": list(FUNCOES_BLOCO)},
        "fala": _s(),
        "cenas": {"type": "array", "items": _o({
            "layout": {"type": "string", "enum": list(LAYOUTS)},
            "composicao": _s(), "visual": _s(), "query": _s(), "alternativas": _ls(), "material": _s(), "palavra": _s(),
            "efeito": {"type": "string", "enum": list(EFEITOS_CURTOS) + [""]},
            "entrada": {"type": "string", "enum": list(ENTRADAS_CURTOS)},
            "emocao": {"type": "string", "enum": list(EMOCOES_ANIME) + [""]}, "obra": _s(), "personagem": _s()})},
        "texto_tela": _o({"texto": _s(), "estilo": _s(), "palavra": _s()}),
        "sfx": {"type": "array", "items": _o({"tipo": {"type": "string", "enum": list(TIPOS_SFX)}, "palavra": _s(), "busca": _s()})},
    })},
})

ROTEIRO_SYS = (
    "Você é roteirista e diretor de vídeos curtos de NOTÍCIAS (Shorts/Reels/TikTok, 9:16). Escreva o roteiro de UM vídeo a partir "
    "da notícia, imitando o GUIA DE ESTILO do canal (ritmo, gancho, estrutura, tom, composições, textos na tela, sons). Regras:\n"
    "1. Só fatos da notícia — não invente número, nome, data nem declaração. Se faltar informação, fale menos.\n"
    "2. 'fala' = exatamente o que o apresentador vai LER, no idioma do canal, frases curtas e faladas (sem emoji, sem hashtags, "
    "sem marcações). O gancho tem que prender nos 2-3 primeiros segundos. O total de palavras é o pedido (±10%).\n"
    "3. Cada bloco tem as 'cenas' (planos) na ordem em que aparecem; a 1ª começa com o bloco e cada outra começa na "
    "'palavra' (uma palavra QUE ESTÁ na fala do bloco, onde o corte acontece). RITMO: a imagem troca a cada {plano} s, então "
    "conte as palavras — um bloco de N palavras precisa de ~N/({pps}×{plano}) cenas (até 8). Plano parado demais quebra o estilo.\n"
    "4. 'layout' de cada cena = o que o editor monta: {layouts}. 'composicao' = o id da composição do canal que você está "
    "imitando (ou ''). 'material' = o ID de uma mídia da notícia (I1…/M1…) quando layout='materia' (senão ''). Prefira as "
    "mídias da notícia sempre que mostrarem o fato; pessoa/lugar/empresa REAL e específica = 'foto_real' (nunca banco).\n"
    "5. 'query' = busca em INGLÊS, concreta e visual (o que aparece na imagem), 2-6 palavras; pra foto_real/clipe_real, o "
    "nome próprio + contexto (ex.: 'Elon Musk press conference'). 'alternativas' = 2 buscas de reserva, da mais específica à "
    "mais simples. 'visual' = em português, o que deve aparecer.\n"
    "6. 'efeito' (movimento da câmera na mídia) de: {efeitos} ou ''. 'entrada' (gesto no corte) de: {entradas}.\n"
    "7. 'texto_tela' = frase CURTA (1-5 palavras) que aparece grande, nos momentos fortes (número, nome, revelação) — "
    "'texto' vazio quando o bloco não tem. 'estilo' = id de destaque (use o do canal: {destaque}). 'palavra' = onde entra.\n"
    "8. 'sfx' = as deixas de efeito sonoro do bloco (tipo + a 'palavra' onde o som bate, '' = no começo do bloco) seguindo o "
    "estilo de som do canal; 'busca' = termos em inglês pra procurar esse som no Pixabay. Não exagere: 0 a 2 por bloco.\n"
    "9. Palavras de ÊNFASE (o que o apresentador fala mais forte) vão em MAIÚSCULAS na própria fala — a legenda copia.\n"
    "{ponto_de_vista}"
    "10. Termine com o CTA do canal quando ele tiver (sem propaganda de produto/curso, a não ser que o PEDIDO EXTRA peça). 'titulo_video' + 3 'titulos_alt' no estilo dos títulos do canal; "
    "'descricao' curta; 3 a 6 'hashtags'.")


def _sys_roteiro(perfil: Dict[str, Any]) -> str:
    est = (perfil.get("textos_tela") or {}).get("estilo_destaque") or "impacto_red"
    r = perfil.get("ritmo") or {}
    pv = perfil.get("ponto_de_vista") or {}
    regra_pv = ("9b. PONTO DE VISTA — não seja só mais um canal que repete a notícia: depois do fato, um bloco 'contraponto' com PELO "
                "MENOS um ponto de discordância (o outro lado com o melhor argumento dele, não um espantalho; o que a manchete não conta; "
                "o que a reação da internet exagera ou esquece; a pergunta incômoda) e um bloco 'reflexao' curto (1-2 frases, sem sermão) "
                "— dá pra fechar perguntando o que quem assiste acha. Opinião soa como opinião ('agora pensa comigo…'), separada do fato; "
                "nada de fato, número ou fala inventada pra sustentar o contraponto. " + (pv.get("descricao") or "") + "\n") if pv.get("usa", True) else ""
    return (ROTEIRO_SYS.replace("{ponto_de_vista}", regra_pv).replace("{plano}", str(r.get("plano_medio_s") or 1.8)).replace("{pps}", str(r.get("palavras_por_s") or 2.8))
            .replace("{layouts}", "; ".join(f"{k} = {v[1]}" for k, v in LAYOUTS.items()))
            .replace("{efeitos}", ", ".join(EFEITOS_CURTOS)).replace("{entradas}", ", ".join(ENTRADAS_CURTOS))
            .replace("{destaque}", est))


TAGS_TURBO = ("gasp", "laugh", "chuckle", "sigh", "groan", "sniff", "surprised", "sarcastic", "dramatic", "whispering", "happy")


def usa_turbo(p: Dict[str, Any]) -> bool:
    """🌍 a narração sai no Chatterbox Turbo (inglês, entende as tags de expressão [gasp], [laugh]…)?"""
    cfg = p.get("config") or {}
    slug = str(cfg.get("voz_tts") or "")
    if slug and not slug.startswith("perfil:"):  # 🎭 voz do multi voice: vale o motor DELA
        try:
            import multivoz
            v = next((x for x in multivoz.listar() if x.get("slug") == slug), None)
            if v:
                return v.get("motor") == "chatterbox_turbo"
        except Exception:  # noqa: BLE001
            pass
    return (cfg.get("motor_perfil") or "") == "chatterbox_turbo"


def regra_tags_turbo(p: Dict[str, Any]) -> str:
    """📰 v84_291: notícia narrada no Chatterbox Turbo → a fala sai em INGLÊS com as tags de expressão."""
    if not usa_turbo(p):
        return ""
    return ("\n\nVOZ — CHATTERBOX TURBO (inglês): escreva TODA a 'fala' de cada bloco em INGLÊS natural de shorts (mesmo que a "
            "notícia ou o guia do canal estejam em outra língua; textos na tela e buscas também em inglês). Coloque de 1 a 4 tags de "
            "expressão no vídeo inteiro, nos momentos certos, escolhidas destas: "
            + ", ".join(f"[{t}]" for t in TAGS_TURBO)
            + " (ex.: '[gasp] And then the unthinkable happened…', 'He said WHAT? [laugh]'). A tag fica DENTRO da fala, colada na frase "
            "que ela colore; nunca outros colchetes; nada de tag em texto_tela.")


def _sys_roteiro_do(p: Dict[str, Any], perfil: Dict[str, Any]) -> str:
    return _sys_roteiro(perfil) + regra_tags_turbo(p)


def palavras_alvo(perfil: Dict[str, Any], duracao: Optional[float] = None) -> int:
    d = float(duracao or perfil.get("duracao_alvo_s") or 45)
    return int(round(d * float(perfil["ritmo"].get("palavras_por_s") or 2.8)))


def conteudo_roteiro(base: str, p: Dict[str, Any]) -> str:
    perfil = perfil_do(base, p)
    c = canal_do(base, p)
    dur = float((p.get("config") or {}).get("duracao_alvo_s") or 0) or perfil["duracao_alvo_s"]
    idioma = perfil.get("idioma") or (c or {}).get("idioma") or "o idioma da notícia"
    if usa_turbo(p):
        idioma = "INGLÊS (Chatterbox Turbo, com tags de expressão)"
    L = [f"CANAL: {(c or {}).get('nome') or '(sem canal — estilo padrão de shorts de notícia)'} · idioma da fala: {idioma}",
         f"DURAÇÃO DO VÍDEO: ~{int(dur)} s → cerca de {palavras_alvo(perfil, dur)} palavras de fala no total.",
         *([TEXTO_QUADRADO_PT] if proporcao_do(p) == "1:1" else []), "",
         "## GUIA DE ESTILO DO CANAL", texto_do_perfil(perfil), ""]
    ms = [m for m in p.get("midias") or [] if not m["id"].startswith("C")]
    if ms:
        L.append("## MÍDIAS DA NOTÍCIA (use com layout 'materia' e o ID em 'material')")
        L += [f"- {m['id']} ({m.get('tipo')}): {m.get('descricao') or 'sem legenda'}" for m in ms]
        L.append("")
    km = midias_do_canal(base, c)
    if km:
        L.append("## MEMES / BORDÕES RECORRENTES DO CANAL (use com layout 'materia' e o ID em 'material', nos momentos que eles pedem)")
        L += [f"- {m['id']} ({m.get('tipo')}): {m.get('descricao') or 'sem descrição'}" for m in km]
        L.append("")
    L.append(_regra_anime(anime_do(base, p)))
    if perfil["textos_tela"].get("usa", True) is False:
        L += ["⚠ Este canal NÃO usa texto grande separado na tela (a legenda faz esse papel): deixe 'texto_tela.texto' vazio, "
              "a não ser num layout 'cartao'.", ""]
    L += ["## NOTÍCIA", texto_noticia(p) or "(sem texto — escreva só com o que está no título)"]
    if (p.get("config") or {}).get("extra"):
        L += ["", "## PEDIDO EXTRA", p["config"]["extra"]]
    return "\n".join(L)


def prompt_roteiro(base: str, p: Dict[str, Any]) -> str:
    perfil = perfil_do(base, p)
    return (_sys_roteiro_do(p, perfil) + "\n\n" + conteudo_roteiro(base, p) + "\n\nResponda APENAS com um JSON neste formato (sem ```):\n"
            + json.dumps(_exemplo_schema(ROTEIRO_SCHEMA), ensure_ascii=False, indent=1))


def gerar_roteiro(base: str, pid: str, chamar: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    p = carregar(base, pid)
    if not texto_noticia(p) and not p.get("titulo"):
        raise CurtoErro("Ponha a notícia (link ou texto) antes.")
    if chamar is None:
        import ia_servico
        chamar = ia_servico.chamar
    perfil = perfil_do(base, p)
    r = chamar("curtos", _sys_roteiro_do(p, perfil), conteudo_roteiro(base, p), schema=ROTEIRO_SCHEMA, max_tokens=6000,
               effort="medium", job=pid, cache_local=False)
    if not r:
        raise CurtoErro(motivo_ia() + " Use o 📋 prompt numa outra IA e cole a resposta.")
    with _TRAVA:
        p = carregar(base, pid)
        p["roteiro"] = ler_roteiro(r, p, ids_extras(base, p))
        p["tts"] = None
        salvar(base, p)
    return p["roteiro"]


def _limpo(v: Any, n: int) -> str:
    return " ".join(str(v or "").split())[:n]


def ler_roteiro(dados: Any, p: Dict[str, Any], extras_ids: Iterable[str] = ()) -> Dict[str, Any]:
    """Resposta da IA (dict ou texto) ou o que veio da tela → roteiro normalizado (ids B1…, cenas válidas)."""
    if isinstance(dados, str):
        import json_ia
        try:
            dados = json_ia.carregar(dados)
        except Exception as exc:  # noqa: BLE001
            raise CurtoErro(f"Não entendi o JSON do roteiro: {exc}") from exc
    if isinstance(dados, list):
        dados = {"blocos": dados}
    if not isinstance(dados, dict) or not isinstance(dados.get("blocos"), list) or not dados["blocos"]:
        raise CurtoErro("O roteiro precisa ter a lista \"blocos\".")
    mids = {m["id"].upper() for m in p.get("midias") or []} | {str(x).upper() for x in extras_ids}
    blocos = []
    for i, b in enumerate(dados["blocos"]):
        if isinstance(b, str):
            b = {"fala": b}
        if not isinstance(b, dict):
            continue
        fala = _limpo(b.get("fala") or b.get("texto"), 1500)
        if not fala:
            continue
        cenas = []
        for cn in (b.get("cenas") or [])[:8]:
            if not isinstance(cn, dict):
                continue
            lay = cn.get("layout") if cn.get("layout") in LAYOUTS else "video"
            mat = re.sub(r"[^A-Z0-9]", "", str(cn.get("material") or "").upper())
            if lay == "materia" and mat not in mids:
                lay = "foto_real" if mat else "video"
                mat = ""
            if mat and mat not in mids:
                mat = ""
            if lay not in ("materia", "cartao_cinza"):
                mat = ""
            q = _limpo(cn.get("query"), 120) or _limpo(cn.get("visual"), 120)
            if lay not in ("materia", "cartao") and not q and not mat:
                continue
            cenas.append({"layout": lay, "composicao": _limpo(cn.get("composicao"), 40),
                          "visual": _limpo(cn.get("visual"), 240), "query": q,
                          "alternativas": [_limpo(a, 120) for a in (cn.get("alternativas") or []) if _limpo(a, 120)][:4],
                          "material": mat, "palavra": _limpo(cn.get("palavra"), 60),
                          "efeito": cn.get("efeito") if cn.get("efeito") in EFEITOS_CURTOS else "",
                          "entrada": cn.get("entrada") if cn.get("entrada") in ENTRADAS_CURTOS else "none",
                          **({"emocao": cn["emocao"] if cn.get("emocao") in EMOCOES_ANIME else "",
                              "obra": _limpo(cn.get("obra"), 80), "personagem": _limpo(cn.get("personagem"), 80)}
                             if lay in LAYOUTS_ANIME else {}),
                          **(_trecho_da_cena(cn) if mat else {}), **_sugestao_da_cena(cn)})
        if not cenas:
            cenas = [{"layout": "video", "composicao": "", "visual": fala[:120], "query": "breaking news background", "alternativas": [],
                      "material": "", "palavra": "", "efeito": "zoom_in", "entrada": "none"}]
        tt = b.get("texto_tela") if isinstance(b.get("texto_tela"), dict) else {"texto": b.get("texto_tela") or ""}
        tt = {"texto": _limpo(tt.get("texto"), 80), "estilo": _limpo(tt.get("estilo"), 40), "palavra": _limpo(tt.get("palavra"), 60)}
        sfx = []
        for s in (b.get("sfx") or [])[:4]:
            if isinstance(s, str):
                s = {"tipo": s}
            if isinstance(s, dict) and s.get("tipo") in TIPOS_SFX:
                item = {"tipo": s["tipo"], "palavra": _limpo(s.get("palavra"), 60),
                        "busca": _limpo(s.get("busca"), 80) or TIPOS_SFX[s["tipo"]]["pixabay"]}
                if s.get("som"):
                    item["som"] = _limpo(s["som"], 80)
                if s.get("volume") not in (None, ""):
                    try:
                        item["volume"] = round(max(0.0, min(3.0, float(s["volume"]))), 2)
                    except (TypeError, ValueError):
                        pass
                sfx.append(item)
        blocos.append({"id": f"B{len(blocos) + 1}", "funcao": b.get("funcao") if b.get("funcao") in FUNCOES_BLOCO else ("gancho" if not blocos else "fato"),
                       "fala": fala, "cenas": cenas, "texto_tela": tt, "sfx": sfx,
                       **({"fala_pt": _limpo(b.get("fala_pt"), 1500)} if b.get("fala_pt") else {}),
                       **({"fala_en": _limpo(b.get("fala_en"), 1500)} if b.get("fala_en") else {})})
    if not blocos:
        raise CurtoErro("Nenhum bloco com fala no roteiro.")
    return {**({k: dados[k] for k in ("ganchos", "finais", "titulos", "roteiro_en", "roteiro_pt", "idioma", "titulo_pt",
                                    "ganchos_escolhido", "finais_escolhido", "titulos_escolhido") if dados.get(k) not in (None, "", [])}),
            "titulo_video": _limpo(dados.get("titulo_video"), 140), "titulos_alt": [_limpo(t, 140) for t in dados.get("titulos_alt") or []][:5],
            "descricao": str(dados.get("descricao") or "")[:2000], "hashtags": [_limpo(h, 40) for h in dados.get("hashtags") or []][:10],
            "blocos": blocos}


def _trecho_da_cena(cn: Dict[str, Any]) -> Dict[str, Any]:
    """💬 cena de clipe: de/até (segundos do vídeo cru) e o destaque (círculo/seta rastreando algo)."""
    out: Dict[str, Any] = {}
    try:
        if cn.get("de") not in (None, ""):
            out["de"] = round(max(0.0, float(cn["de"])), 2)
            out["ate"] = round(max(out["de"], float(cn.get("ate") if cn.get("ate") not in (None, "") else out["de"])), 2)
    except (TypeError, ValueError):
        pass
    if _limpo(cn.get("foco"), 80):  # 🎥 v84_296: o objeto em que o vertical foca nessa cena (o que a fala está mostrando)
        out["foco"] = _limpo(cn["foco"], 80)
    if _limpo(cn.get("zoom_detalhe"), 120):  # 🎥 v84_322: a câmera aproxima nesse detalhe
        out["zoom_detalhe"] = _limpo(cn["zoom_detalhe"], 120)
    cg = cn.get("congelar") if isinstance(cn.get("congelar"), dict) else {}
    if _limpo(cg.get("texto"), 60):  # ⏸ congela com o cartão
        out["congelar"] = {"texto": _limpo(cg["texto"], 60)}
    d = cn.get("destaque") if isinstance(cn.get("destaque"), dict) else {}
    if d.get("alvo"):
        import rastreio
        out["destaque"] = {"alvo": _limpo(d["alvo"], 120), "tipo": d.get("tipo") if d.get("tipo") in rastreio.TIPOS else "circulo",
                           "texto": _limpo(d.get("texto"), 40)}
    return out


def _sugestao_da_cena(cn: Dict[str, Any]) -> Dict[str, Any]:
    """💡 📚 a mídia que a IA sugere buscar (e, se você aceitou, o seu vídeo que estava ali — pra voltar)."""
    out: Dict[str, Any] = {}
    sg = cn.get("sugestao") if isinstance(cn.get("sugestao"), dict) else {}
    if sg.get("layout") in ("foto_real", "clipe_real", "ia", "ia_video") and _limpo(sg.get("query"), 160):
        out["sugestao"] = {"layout": sg["layout"], "query": _limpo(sg["query"], 160), "por_que": _limpo(sg.get("por_que"), 160)}
        if isinstance(cn.get("reserva"), dict) and cn["reserva"].get("material"):
            out["reserva"] = {k: cn["reserva"][k] for k in ("layout", "material", "de", "ate", "destaque") if k in cn["reserva"]}
    return out


def texto_completo(roteiro: Optional[Dict[str, Any]]) -> str:
    return "\n".join(b["fala"] for b in (roteiro or {}).get("blocos") or [])


def chave_roteiro(roteiro: Optional[Dict[str, Any]]) -> str:
    return format(zlib.crc32(texto_completo(roteiro).encode("utf-8")), "08x")


# ------------------------------------------------------------------ 🎙 voz guia (TTS)
def duracao_audio(cam: str) -> float:
    r = _rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", cam], 60)
    try:
        return round(float((r.stdout or "0").strip() or 0), 3)
    except ValueError:
        return 0.0


def _silencio_wav(cam: str, segundos: float, taxa: int = 48000) -> str:
    """Um WAV de silêncio (mono, 16 bits) escrito direto em Python."""
    import wave
    with wave.open(cam, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(b"\x00\x00" * max(1, int(round(segundos * taxa))))
    return cam


def gerar_voz_guia(base: str, pid: str, tts: Callable[..., Any], limpar: Callable[[str, str], str] = lambda t, m: t,
                   voz: Optional[Dict[str, Any]] = None, pausa: float = 0.12,
                   on_log: Callable[[str], None] = lambda _m: None, sub: str = "tts", guardar: bool = True) -> Dict[str, Any]:
    """Uma fala por bloco (dá o tempo de cada bloco) → guia.wav com uma pausinha entre os blocos."""
    import multivoz
    p = carregar(base, pid)
    blocos = (p.get("roteiro") or {}).get("blocos") or []
    if not blocos:
        raise CurtoErro("Faça o roteiro antes.")
    if not voz:
        raise CurtoErro("Escolha a voz da voz guia.")
    motor, kw = multivoz.kwargs_da_voz(voz)
    d = os.path.join(pasta(base, pid), sub)
    os.makedirs(d, exist_ok=True)  # 🎙 v84_301: NÃO apaga — o bloco já gerado (mesmo texto + mesma voz) é reaproveitado
    partes, por_bloco = [], []
    assinatura_voz = json.dumps([motor, {k: v for k, v in sorted(kw.items()) if isinstance(v, (str, int, float, bool))}], ensure_ascii=False)
    silencio = os.path.join(d, "_pausa.wav")
    _silencio_wav(silencio, pausa)  # 🧯 v84_329: sem ffmpeg (no Windows ele chegou a travar 60 s só pra isso)
    for i, b in enumerate(blocos):
        on_log(f"🎙 bloco {i + 1}/{len(blocos)}")
        bruto, arq = os.path.join(d, f"_b{i}.wav"), os.path.join(d, f"b{i}.wav")
        texto_tts = limpar(b["fala"], motor)
        chave_b = format(zlib.crc32((assinatura_voz + "|" + texto_tts).encode("utf-8")), "08x")
        marca = os.path.join(d, f"_b{i}.chave")
        try:
            with open(marca, encoding="utf-8") as f:
                ja = f.read().strip() == chave_b and os.path.isfile(bruto) and os.path.getsize(bruto) > 1000
        except OSError:
            ja = False
        if ja:
            on_log(f"🎙 bloco {i + 1}/{len(blocos)} (já gerado)")
        for tentativa in range(1, 4) if not ja else ():  # 🎙 o motor às vezes trava (crash nativo do PyTorch): tenta de novo
            try:
                if os.path.isfile(marca):
                    os.remove(marca)
                tts(motor, texto_tts, bruto, **kw)
                if os.path.isfile(bruto) and os.path.getsize(bruto) > 1000:
                    with open(marca, "w", encoding="utf-8") as f:
                        f.write(chave_b)
                    break
                raise CurtoErro("o motor de voz não gerou o áudio")
            except Exception as exc:  # noqa: BLE001
                if tentativa == 3:
                    raise
                nativo = "3221225477" in str(exc) or "travou o processo" in str(exc)
                espera = (10 if tentativa == 1 else 20) if nativo else 3 * tentativa
                on_log(f"🎙 bloco {i + 1}: o motor de voz {'travou (memória?)' if nativo else 'falhou'} — esperando {espera} s e "
                       f"tentando de novo ({tentativa + 1}/3)")
                import gc
                gc.collect()
                time.sleep(espera)
        _rodar(["ffmpeg", "-v", "error", "-y", "-i", bruto, "-af",
                "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.25:stop_threshold=-45dB",
                "-ar", "48000", "-ac", "1", arq], 120)
        if not os.path.isfile(arq):
            shutil.copy(bruto, arq)
        partes += [arq, silencio] if i < len(blocos) - 1 else [arq]
        por_bloco.append({"bloco": b["id"], "dur": duracao_audio(arq)})
    lista = os.path.join(d, "lista.txt")
    with open(lista, "w", encoding="utf-8") as f:
        f.writelines(f"file '{os.path.basename(x)}'\n" for x in partes)
    guia = os.path.join(d, "guia.wav")
    r = _rodar(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-ar", "48000", "-ac", "1", guia], 300)
    if not os.path.isfile(guia):
        raise CurtoErro(f"Não consegui juntar a voz guia: {(r.stderr or '')[-200:]}")
    info = {"arquivo": f"{sub}/guia.wav", "dur": duracao_audio(guia), "por_bloco": por_bloco, "voz": voz.get("slug") or "",
            "chave": chave_roteiro(p.get("roteiro")), "quando": _hoje()}
    if guardar:
        with _TRAVA:
            q = carregar(base, pid)
            q["tts"] = info
            salvar(base, q)
    return info


# ------------------------------------------------------------------ 🎤 alinhar a fala ao roteiro
def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", t)


RE_TAG_VOZ = re.compile(r"\[[^\[\]]{1,30}\]")  # [gasp], [surprised]… do Chatterbox: não são faladas


def sem_tags(texto: str) -> str:
    return re.sub(r"\s{2,}", " ", RE_TAG_VOZ.sub(" ", str(texto or ""))).strip()


def tokens(texto: str) -> List[str]:
    return [x for x in (norm(w) for w in sem_tags(texto).split()) if x]


def _tokens_roteiro(blocos: List[Dict[str, Any]]) -> Tuple[List[str], List[int]]:
    toks, dono = [], []
    for i, b in enumerate(blocos):
        for t in tokens(b["fala"]):
            toks.append(t)
            dono.append(i)
    return toks, dono


def alinhar(blocos: List[Dict[str, Any]], palavras: List[Dict[str, Any]], dur: Optional[float] = None) -> Dict[str, Any]:
    """Casa as palavras faladas (Whisper) com o texto do roteiro.
    Devolve {"blocos": [{bloco, ini_w, fim_w, start, end, falado, similaridade}], "mapa": {indice token do roteiro: indice palavra}}.
    `start` do bloco = 1ª palavra dele; `end` = começo do próximo (o último vai até o fim do áudio)."""
    S, dono = _tokens_roteiro(blocos)
    W = [norm(w["word"]) for w in palavras]
    n = len(blocos)
    if not palavras or not n:
        return {"blocos": [], "mapa": {}}
    sm = difflib.SequenceMatcher(None, S, W, autojunk=False)
    mapa: Dict[int, int] = {}
    for a, b, k in sm.get_matching_blocks():
        for j in range(k):
            mapa[a + j] = b + j
    primeiros: List[Optional[int]] = [None] * n
    for si, wi in sorted(mapa.items()):
        bi = dono[si]
        if primeiros[bi] is None:
            primeiros[bi] = wi
    # blocos que não casaram nada: interpola pelo número de palavras do roteiro
    tam = [sum(1 for d in dono if d == i) for i in range(n)]
    for i in range(n):
        if primeiros[i] is not None:
            continue
        ant = max([k for k in range(i) if primeiros[k] is not None], default=None)
        pos = min([k for k in range(i + 1, n) if primeiros[k] is not None], default=None)
        a_w = primeiros[ant] if ant is not None else 0
        b_w = primeiros[pos] if pos is not None else len(W)
        a_s = sum(tam[: ant if ant is not None else 0])
        b_s = sum(tam[: pos if pos is not None else n])
        frac = (sum(tam[:i]) - a_s) / max(1, b_s - a_s)
        primeiros[i] = int(round(a_w + (b_w - a_w) * frac))
    primeiros[0] = 0  # o que veio antes do 1º bloco (respiração, "é…") fica no 1º
    for i in range(1, n):  # sempre em ordem
        primeiros[i] = max(int(primeiros[i]), int(primeiros[i - 1]))
    total = float(dur or palavras[-1]["end"])
    out = []
    for i in range(n):
        ini_w = int(primeiros[i])
        fim_w = (int(primeiros[i + 1]) if i + 1 < n else len(W)) - 1
        vazio = fim_w < ini_w or ini_w >= len(W)
        ws = [] if vazio else palavras[ini_w: fim_w + 1]
        start = float(palavras[min(ini_w, len(W) - 1)]["start"]) if not vazio else (out[-1]["end"] if out else 0.0)
        if i == 0:
            start = 0.0
        falado = " ".join(str(w["word"]).strip() for w in ws)
        sim = difflib.SequenceMatcher(None, tokens(blocos[i]["fala"]), tokens(falado), autojunk=False).ratio() if ws else 0.0
        out.append({"bloco": blocos[i]["id"], "ini_w": ini_w, "fim_w": fim_w, "start": round(start, 3),
                    "fala_fim": round(float(ws[-1]["end"]), 3) if ws else round(start, 3), "falado": falado, "similaridade": round(sim, 2)})
    for i in range(n):
        out[i]["end"] = round(out[i + 1]["start"] if i + 1 < n else total, 3)
        if out[i]["end"] < out[i]["start"]:
            out[i]["end"] = out[i]["start"]
    return {"blocos": out, "mapa": mapa}


MULETAS = {"eee", "ahn", "hum", "hm", "hmm", "uh", "uhm", "erm", "aeh", "ahm", "ehm", "mm", "aham"}
MULETAS_COM_PAUSA = {"e", "eh", "ah", "an", "um", "er", "ae", "o"}  # também são palavras ("e", "o"): só sai com pausa em volta


def repeticoes(blocos: List[Dict[str, Any]], palavras: List[Dict[str, Any]], minimo: int = 2, muletas: bool = True) -> List[Tuple[int, int]]:
    """Trechos falados que SOBRAM: uma TENTATIVA refeita logo depois (você errou e falou de novo — palavras a mais,
    fora do roteiro, que terminam igual ao começo do que vem em seguida) e muletas soltas ("é…", "ahn", "hum").
    [(i_palavra_ini, i_palavra_fim)]."""
    S, _d = _tokens_roteiro(blocos)
    W = [norm(w["word"]) for w in palavras]
    sm = difflib.SequenceMatcher(None, S, W, autojunk=False)
    out = []
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag not in ("insert", "replace") or j2 <= j1:
            continue
        run = W[j1:j2]
        seguinte = W[j2: j2 + len(run) + 1]
        achou = 0
        for k in range(min(len(run), len(seguinte)), 0, -1):
            suf = run[-k:]
            if suf[:-1] == seguinte[: k - 1] and (suf[-1] == seguinte[k - 1] or (len(suf[-1]) >= 2 and seguinte[k - 1].startswith(suf[-1]))):
                if k >= minimo or (len(suf[-1]) >= 2 and seguinte[k - 1] != suf[-1]):
                    achou = k
                    break
        if achou:
            resto = run[: len(run) - achou]
            ini = j1 if all(t in MULETAS for t in resto) or achou >= 0.5 * len(run) else j2 - achou
            out.append((ini, j2 - 1))
        elif muletas and tag == "insert":
            for k in range(j1, j2):
                antes = float(palavras[k]["start"]) - float(palavras[k - 1]["end"]) if k > 0 else 9.0
                depois = float(palavras[k + 1]["start"]) - float(palavras[k]["end"]) if k + 1 < len(palavras) else 9.0
                if W[k] in MULETAS or (W[k] in MULETAS_COM_PAUSA and max(antes, depois) >= 0.25):
                    out.append((k, k))
    return sorted(set(out))


def intervalos_de_corte(palavras: List[Dict[str, Any]], dur: float, pausa_max: float = 0.3, manter: Optional[float] = None,
                        repetidas: Iterable[Tuple[int, int]] = (), cortar_pausas: bool = True) -> List[Tuple[float, float]]:
    """O que SAI do áudio: silêncio do começo/fim, pausas maiores que `pausa_max` (fica `manter` s de respiro) e
    as tentativas refeitas. Intervalos ordenados e sem sobreposição."""
    if not palavras:
        return []
    manter = max(0.08, pausa_max * 0.6) if manter is None else manter
    cortes: List[Tuple[float, float]] = []
    if cortar_pausas:
        ini = float(palavras[0]["start"])
        if ini > 0.15:
            cortes.append((0.0, ini - 0.08))
        for i in range(len(palavras) - 1):
            a, b = float(palavras[i]["end"]), float(palavras[i + 1]["start"])
            if b - a > pausa_max:
                cortes.append((a + manter / 2, b - manter / 2))
        fim = float(palavras[-1]["end"])
        if dur - fim > 0.35:
            cortes.append((fim + 0.25, dur))
    for i, j in repetidas:
        a = float(palavras[i]["start"]) - 0.03
        b = float(palavras[j + 1]["start"]) - 0.04 if j + 1 < len(palavras) else float(palavras[j]["end"])
        if b > a:
            cortes.append((max(0.0, a), b))
    cortes.sort()
    junto: List[List[float]] = []
    for a, b in cortes:
        if b - a < 0.04:
            continue
        if junto and a <= junto[-1][1] + 0.02:
            junto[-1][1] = max(junto[-1][1], b)
        else:
            junto.append([a, b])
    return [(round(a, 3), round(min(b, dur), 3)) for a, b in junto if min(b, dur) - a >= 0.04]


def remapear(t: float, cortes: List[Tuple[float, float]]) -> float:
    """Tempo no áudio original → tempo no áudio cortado."""
    tira = 0.0
    for a, b in cortes:
        if t >= b:
            tira += b - a
        elif t > a:
            tira += t - a
            break
        else:
            break
    return round(t - tira, 3)


def palavras_remapeadas(palavras: List[Dict[str, Any]], cortes: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
    out = []
    for w in palavras:
        a, b = float(w["start"]), float(w["end"])
        if any(x <= a and b <= y for x, y in cortes):  # a palavra inteira saiu (tentativa refeita)
            continue
        na, nb = remapear(a, cortes), remapear(b, cortes)
        out.append({"word": w["word"], "start": na, "end": max(nb, na + 0.02)})
    return out


def cortar_audio(entrada: str, saida: str, cortes: List[Tuple[float, float]], dur: float, fade: float = 0.008) -> str:
    """Áudio sem os `cortes` (com um fade curtinho em cada emenda, sem clique). 48 kHz mono."""
    manter, t = [], 0.0
    for a, b in cortes:
        if a > t:
            manter.append((t, a))
        t = max(t, b)
    if dur > t:
        manter.append((t, dur))
    manter = [(a, b) for a, b in manter if b - a > 0.02]
    if not cortes or not manter:
        _rodar(["ffmpeg", "-v", "error", "-y", "-i", entrada, "-ar", "48000", "-ac", "1", saida], 600)
        return saida
    filtros = []
    for k, (a, b) in enumerate(manter):
        f = min(fade, (b - a) / 3)
        filtros.append(f"[0:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,"
                       f"afade=t=in:d={f:.4f},afade=t=out:st={max(0.0, b - a - f):.4f}:d={f:.4f}[p{k}]")
    filtros.append("".join(f"[p{k}]" for k in range(len(manter))) + f"concat=n={len(manter)}:v=0:a=1[out]")
    script = saida + ".filtro.txt"
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(filtros))
    r = _rodar(["ffmpeg", "-v", "error", "-y", "-i", entrada, "-filter_complex_script", script, "-map", "[out]",
                "-ar", "48000", "-ac", "1", saida], 900)
    try:
        os.remove(script)
    except OSError:
        pass
    if not os.path.isfile(saida):
        raise CurtoErro(f"Não consegui cortar o áudio: {(r.stderr or '')[-300:]}")
    return saida


def processar_gravacao(base: str, pid: str, transcrever: Callable[..., List[Dict[str, Any]]], arquivo: str = "",
                       opcoes: Optional[Dict[str, Any]] = None, on_log: Callable[[str], None] = lambda _m: None,
                       fonte: str = "") -> Dict[str, Any]:
    """Sua gravação (ou a voz guia): Whisper palavra a palavra → tira pausas longas e repetições → alinha ao roteiro."""
    p = carregar(base, pid)
    blocos = (p.get("roteiro") or {}).get("blocos") or []
    if not blocos:
        raise CurtoErro("Faça o roteiro antes de gravar.")
    perfil = perfil_do(base, p)
    op = {"cortar_pausas": True, "cortar_repeticoes": True, "pausa_max": perfil["ritmo"]["pausa_max_s"]}
    op.update({k: v for k, v in (opcoes or {}).items() if k in op})
    d = os.path.join(pasta(base, pid), "voz")
    os.makedirs(d, exist_ok=True)
    g = p.get("gravacao") or {}
    original = arquivo or (os.path.join(pasta(base, pid), g["original"]) if g.get("original") else "")
    if not original or not os.path.isfile(original):
        raise CurtoErro("Mande a gravação.")
    wav_final = os.path.join(d, "original.wav")
    wav = wav_final
    if os.path.abspath(original) != os.path.abspath(wav_final):
        wav = os.path.join(d, "_novo.wav")  # só substitui o original.wav depois que tudo deu certo
        r = _rodar(["ffmpeg", "-v", "error", "-y", "-i", original, "-vn", "-ar", "48000", "-ac", "1", wav], 600)
        if not os.path.isfile(wav):
            raise CurtoErro(f"Não consegui ler esse áudio: {(r.stderr or '')[-200:]}")
    dur = duracao_audio(wav)
    c = canal_do(base, p)
    palavras = g.get("palavras_original") if (not arquivo and g.get("palavras_original")) else None
    if palavras is None:
        on_log("📝 transcrevendo a sua voz (Whisper, palavra por palavra)…")
        meta: Dict[str, Any] = {}
        segs = transcrever(wav, language=(idioma_narrado(p, perfil) or (c or {}).get("idioma") or None),
                           word_timestamps=True, info=meta)
        palavras = [{"word": str(w["word"]).strip(), "start": float(w["start"]), "end": float(w["end"])}
                    for s in segs for w in s.get("words") or [] if str(w.get("word", "")).strip()]
    if not palavras:
        raise CurtoErro("Não achei fala nessa gravação.")
    rep = repeticoes(blocos, palavras) if op["cortar_repeticoes"] else []
    cortes = intervalos_de_corte(palavras, dur, float(op["pausa_max"]), repetidas=rep, cortar_pausas=bool(op["cortar_pausas"]))
    final = os.path.join(d, "voz.wav")
    on_log(f"✂ tirando {len(cortes)} pausa(s)/repetição(ões)…" if cortes else "🎚 preparando o áudio…")
    cortar_audio(wav, final, cortes, dur)
    if wav != wav_final:
        os.replace(wav, wav_final)
        wav = wav_final
    novas = palavras_remapeadas(palavras, cortes)
    dur_final = duracao_audio(final)
    al = alinhar(blocos, novas, dur_final)
    info = {"original": os.path.relpath(wav, pasta(base, pid)).replace("\\", "/"), "arquivo": "voz/voz.wav",
            "palavras_original": palavras, "palavras": novas, "cortes": cortes,
            "repeticoes": [" ".join(palavras[k]["word"] for k in range(i, j + 1)) for i, j in rep],
            "alinhamento": al["blocos"], "mapa": {str(k): v for k, v in al["mapa"].items()}, "dur_original": dur, "dur": dur_final,
            "opcoes": op, "chave_roteiro": chave_roteiro(p.get("roteiro")), "quando": _hoje(),
            "fonte": fonte or (g.get("fonte") if not arquivo else "") or "gravacao"}
    with _TRAVA:
        q = carregar(base, pid)
        q["gravacao"] = info
        salvar(base, q)
    return info


def realinhar(base: str, pid: str) -> Optional[Dict[str, Any]]:
    """Roteiro mudou depois da gravação: refaz só o alinhamento (sem Whisper de novo)."""
    with _TRAVA:
        p = carregar(base, pid)
        g = p.get("gravacao") or {}
        blocos = (p.get("roteiro") or {}).get("blocos") or []
        if not g.get("palavras") or not blocos:
            return None
        al = alinhar(blocos, g["palavras"], g.get("dur"))
        g["alinhamento"], g["mapa"] = al["blocos"], {str(k): v for k, v in al["mapa"].items()}
        g["chave_roteiro"] = chave_roteiro(p.get("roteiro"))
        salvar(base, p)
        return g


def usar_o_que_falei(base: str, pid: str, blocos_ids: Optional[List[str]] = None) -> int:
    """A fala do roteiro vira o que você REALMENTE disse (a legenda e os textos seguem a gravação)."""
    with _TRAVA:
        p = carregar(base, pid)
        g = p.get("gravacao") or {}
        mudou = 0
        por_id = {a["bloco"]: a for a in g.get("alinhamento") or []}
        for b in (p.get("roteiro") or {}).get("blocos") or []:
            a = por_id.get(b["id"])
            if not a or not a.get("falado") or (blocos_ids and b["id"] not in blocos_ids):
                continue
            if tokens(a["falado"]) != tokens(b["fala"]):
                b["fala"] = a["falado"]
                mudou += 1
        salvar(base, p)
    realinhar(base, pid)
    return mudou


def caixa_da_legenda(blocos: List[Dict[str, Any]], palavras: List[Dict[str, Any]], mapa: Dict[int, int],
                     al: List[Dict[str, Any]], gancho_maiusculas: bool = False) -> List[Dict[str, Any]]:
    """A legenda sai do Whisper (tudo minúsculo). Aqui ela ganha a ÊNFASE do roteiro: palavra que está em MAIÚSCULAS no
    roteiro fica em maiúsculas na legenda; com `gancho_maiusculas`, o 1º bloco (o gancho) sai todo em maiúsculas."""
    crus = [w for b in blocos for w in sem_tags(b["fala"]).split() if norm(w)]
    out = [dict(w) for w in palavras]
    for si, wi in mapa.items():
        if si < len(crus) and wi < len(out):
            limpo = re.sub(r"[^\w]", "", crus[si])
            if len(limpo) >= 2 and limpo.isupper():
                out[wi]["word"] = str(out[wi]["word"]).upper()
    if gancho_maiusculas and al:
        for wi in range(0, min(len(out), al[0]["fim_w"] + 1)):
            out[wi]["word"] = str(out[wi]["word"]).upper()
    return out


def tempo_da_palavra(blocos: List[Dict[str, Any]], bi: int, palavra: str, palavras: List[Dict[str, Any]],
                     mapa: Dict[int, int], al: List[Dict[str, Any]]) -> Optional[float]:
    """Instante (no áudio final) em que a `palavra` (ou expressão) do bloco `bi` é falada."""
    alvo = tokens(palavra)
    if not alvo or bi >= len(al):
        return None
    deslocamento = sum(len(tokens(b["fala"])) for b in blocos[:bi])
    bt = tokens(blocos[bi]["fala"])
    pos = next((k for k in range(len(bt)) if bt[k: k + len(alvo)] == alvo), None)
    if pos is None:
        pos = next((k for k, t in enumerate(bt) if t.startswith(alvo[0][:5])), None)
    if pos is not None:
        for k in range(pos, len(bt)):
            wi = mapa.get(deslocamento + k)
            if wi is not None and wi < len(palavras):
                return float(palavras[wi]["start"])
    a = al[bi]  # não casou: procura direto no que foi falado no bloco
    for wi in range(max(0, a["ini_w"]), min(len(palavras), a["fim_w"] + 1)):
        if norm(palavras[wi]["word"]) == alvo[0]:
            return float(palavras[wi]["start"])
    return None


# ------------------------------------------------------------------ 🔊 efeitos sonoros
def sons_do_tipo(tipo: str, sons: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Sons da base (assets/sons + extras, incluindo os do Pixabay) que servem pra deixa `tipo`."""
    if sons is None:
        import dp_sons
        sons = dp_sons.sons()
    t = TIPOS_SFX.get(tipo) or {}
    prefixos = t.get("ids") or []
    tags = [x.lower() for x in t.get("tags") or []]
    out = []
    for s in sons:
        sid = s["id"]
        if any(sid.startswith(px) for px in prefixos):
            out.append(s)
            continue
        texto = " ".join([sid, str(s.get("nome") or ""), " ".join(s.get("tags") or []), str(s.get("descricao") or "")]).lower()
        if sid.startswith("pixabay/") and any(tg in texto for tg in tags):
            out.append(s)
    return out


def escolher_som(tipo: str, semente: str, evitar: Optional[str] = None, sons: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """Um som do tipo, sempre o mesmo pra mesma deixa (semente), variando entre deixas vizinhas."""
    cands = sons_do_tipo(tipo, sons)
    if not cands:
        return None
    pix = [s for s in cands if s["id"].startswith("pixabay/")]  # os que você trouxe do Pixabay têm a preferência
    lista = pix or cands
    k = zlib.crc32(semente.encode("utf-8")) % len(lista)
    if len(lista) > 1 and lista[k]["id"] == evitar:
        k = (k + 1) % len(lista)
    return lista[k]["id"]


def deixas_de_som(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Todas as deixas do roteiro, com o som escolhido (o seu, se você trocou; senão o da base)."""
    out, ultimo = [], None
    for b in (p.get("roteiro") or {}).get("blocos") or []:
        for k, s in enumerate(b.get("sfx") or []):
            som = s.get("som") or escolher_som(s["tipo"], f"{p['id']}|{b['id']}|{k}", ultimo)
            ultimo = som
            out.append({"bloco": b["id"], "indice": k, "tipo": s["tipo"], "palavra": s.get("palavra") or "",
                        "busca": s.get("busca") or TIPOS_SFX[s["tipo"]]["pixabay"], "som": som, "escolhido": bool(s.get("som")),
                        "volume": s.get("volume")})
    return out


# ------------------------------------------------------------------ 🎬 o projeto do editor
_BANCOS_VIDEO = ("pexels", "pixabay", "mixkit", "vistacreate", "magnific")
_FOTOS_REAIS = ("bing", "brave", "google", "startpage", "yandex", "wikipedia")
PROVIDERS_PADRAO = ["pexels", "pixabay", "bing", "wikipedia", "youtube"]


def rota_da_cena(layout: str, providers: List[str]) -> Tuple[str, str]:
    """(provider, media_type) da cena pelo layout, só entre as fontes ligadas."""
    lig = [x for x in providers if x]
    video = next((x for x in _BANCOS_VIDEO if x in lig), None)
    real = next((x for x in _FOTOS_REAIS if x in lig), None)
    if layout == "materia":
        return "material", "video"
    if layout in LAYOUTS_ANIME:  # 🎌 acervo de anime (local, depois o online); sem ele: YouTube, depois foto de anime
        for pv in PROVEDORES_ANIME + ("youtube",):
            if pv in lig:
                return pv, "video"
    if layout == "clipe_real" and "youtube" in lig:
        return "youtube", "video"
    if layout in ("foto_real", "clipe_real", "meme", "cartao_cinza") and real:
        return real, "image"
    if layout == "ia_video" and "flow" in lig:  # 🎬 vídeo do Flow (Veo); sem Flow, segue como a imagem gerada
        return "flow", "video"
    if layout in ("ia", "ia_video"):
        if "flow" in lig:
            return "flow", "image"
        if "runpod" in lig:
            return "runpod", "image"
    if layout in ("foto", "foto_real", "ia", "ia_video", "clipe_real", "meme", "cartao_cinza") and "pexels" in lig:
        return "pexels", "image"
    if video:
        return video, "video"
    if real:
        return real, "image"
    return (lig[0] if lig else "pexels"), "video"


def _divisoes(a: float, b: float, n: int, palavras: List[Dict[str, Any]]) -> List[float]:
    """n-1 pontos de corte entre a e b, cada um no começo de uma palavra (corte na fala, não no meio dela)."""
    pts = []
    inicios = [float(w["start"]) for w in palavras if a + 0.35 < float(w["start"]) < b - 0.35]
    for k in range(1, n):
        alvo = a + (b - a) * k / n
        t = min(inicios, key=lambda x: abs(x - alvo)) if inicios else alvo
        if (not pts or t > pts[-1] + 0.35) and a + 0.35 < t < b - 0.35:
            pts.append(t)
    return pts


def _layout_no_modo(layout: str, modo: str) -> str:
    """🎌 o modo anime manda: meme vira reação de anime; em "tudo", banco genérico/IA vira cena de anime."""
    if modo in ("reacoes", "tudo") and layout == "meme":
        return "anime_reacao"
    if modo == "tudo" and layout in ("video", "foto", "ia"):
        return "anime_cena"
    if modo == "nao" and layout in LAYOUTS_ANIME:
        return "meme" if layout == "anime_reacao" else "video"
    return layout


def planos_do_video(p: Dict[str, Any], providers: List[str], perfil: Optional[Dict[str, Any]] = None,
                    modo_anime: str = "nao") -> List[Dict[str, Any]]:
    """Os PLANOS no tempo da gravação: cada cena do roteiro começa na palavra dela; plano longo demais pro ritmo do canal é
    dividido (com as buscas de reserva da cena). Cobre o áudio de 0 até o fim, sem buracos."""
    g = p.get("gravacao") or {}
    blocos = (p.get("roteiro") or {}).get("blocos") or []
    al = g.get("alinhamento") or []
    palavras = g.get("palavras") or []
    if not blocos or not al or len(al) != len(blocos):
        raise CurtoErro("Grave (ou use a voz guia) e alinhe antes de montar.")
    perfil = normalizar_perfil(perfil or {})
    alvo = float(perfil["ritmo"]["plano_medio_s"])
    mapa = {int(k): int(v) for k, v in (g.get("mapa") or {}).items()}
    dur = float(g.get("dur") or al[-1]["end"])
    out: List[Dict[str, Any]] = []
    for bi, (b, a) in enumerate(zip(blocos, al)):
        ini, fim = (0.0 if bi == 0 else float(a["start"])), (dur if bi == len(blocos) - 1 else float(a["end"]))
        if fim - ini < 0.05:
            continue
        cenas = b["cenas"]
        marcos = [ini]
        for cn in cenas[1:]:
            t = tempo_da_palavra(blocos, bi, cn.get("palavra") or "", palavras, mapa, al)
            if t is None or t <= marcos[-1] + 0.4 or t >= fim - 0.4:
                t = None
            marcos.append(t)
        # cenas sem palavra achada: espalha entre os vizinhos
        for k in range(1, len(marcos)):
            if marcos[k] is None:
                prox = next((marcos[j] for j in range(k + 1, len(marcos)) if marcos[j] is not None), fim)
                falta = sum(1 for j in range(k, len(marcos)) if marcos[j] is None and (j == k or marcos[j - 1] is None))
                marcos[k] = marcos[k - 1] + (prox - marcos[k - 1]) / (falta + 1)
        marcos = [m for k, m in enumerate(marcos) if k == 0 or m > marcos[k - 1] + 0.3] + [fim]
        for k in range(len(marcos) - 1):
            cn = dict(cenas[min(k, len(cenas) - 1)])
            cn["layout"] = _layout_no_modo(cn["layout"], modo_anime)
            s0, s1 = marcos[k], marcos[k + 1]
            clipe = cn.get("material") and cn.get("de") not in (None, "")  # 💬 pedaço do vídeo cru (comentário)
            contexto = clipe and perfil.get("cortes_por_contexto")  # 💬 os cortes são os do roteiro; só um plano MUITO longo ganha um respiro
            n = max(1, int(round((s1 - s0) / (alvo * (2.2 if contexto else 1.35))))) if (cn["layout"] not in ("cartao", "materia") and not cn.get("material")) or clipe else 1
            n = min(n, 1 + len(cn.get("alternativas") or []), 4) if cn["layout"] not in ("video", "foto") and not clipe else min(n, 4)
            cortes = _divisoes(s0, s1, n, palavras) if n > 1 else []
            limites = [s0] + cortes + [s1]
            buscas = [cn["query"]] + list(cn.get("alternativas") or [])
            for j in range(len(limites) - 1):
                prov, mt = ("material", "video") if cn.get("material") else rota_da_cena(
                    "ia" if cn["layout"] == "ia_video" and (p.get("config") or {}).get("flow_video") is False else cn["layout"], providers)
                q = cn["material"] if prov == "material" else buscas[j % len(buscas)] if buscas else cn.get("visual") or "news"
                alts = [x for x in buscas if x != q][:3] if prov != "material" else []
                out.append({"start": round(limites[j], 3), "end": round(limites[j + 1], 3), "bloco": b["id"], "cena": k, "parte": j,
                            "layout": cn["layout"], "provider": prov, "media_type": mt, "query": q or "news", "alternativas": alts,
                            "visual": cn.get("visual") or "", "efeito": cn.get("efeito") or "",
                            "template": CENA_CARTAO_CINZA if cn["layout"] == "cartao_cinza" else "",
                            **({"emocao": cn.get("emocao") or "", "obra": cn.get("obra") or "", "personagem": cn.get("personagem") or ""}
                               if cn["layout"] in LAYOUTS_ANIME else {}),
                            "entrada": (cn.get("entrada") if j == 0 else ("punch_in" if cn.get("entrada") in ("punch_in", "flash", "shake") else "none")) or "none",
                            **({"clipe": {"mid": cn["material"], "de": float(cn["de"]), "ate": float(cn.get("ate") or cn["de"]),
                                          "off": round(limites[j] - s0, 3), "foco": cn.get("foco") or ""},
                                "efeito": (cn.get("efeito") or "") if j == 0 else
                                (_efeito_seguinte(cn.get("efeito") or "", j) if contexto else ("zoom_in", "zoom_out", "zoom_respiro")[j % 3]),
                                "entrada": (cn.get("entrada") or "none") if j == 0 else ("none" if contexto else "punch_in")} if clipe else {}),
                            **({"destaque": cn["destaque"]} if clipe and j == 0 and (cn.get("destaque") or {}).get("alvo") else {}),
                            **({"zoom_detalhe": cn["zoom_detalhe"]} if clipe and j == 0 and cn.get("zoom_detalhe") else {}),
                            **({"congelar": (cn.get("congelar") or {}).get("texto")}
                               if clipe and j == 0 and (cn.get("congelar") or {}).get("texto") else {})})
    # sem buracos: cada plano termina onde o próximo começa, o último no fim
    out = [x for x in out if x["end"] - x["start"] >= 0.05]
    for i in range(len(out)):
        out[i]["start"] = 0.0 if i == 0 else out[i - 1]["end"]
        if i == len(out) - 1:
            out[i]["end"] = round(dur, 3)
    junto: List[Dict[str, Any]] = []
    for x in out:  # plano curtinho (< 0.35 s) gruda no anterior
        if junto and x["end"] - x["start"] < 0.35:
            junto[-1]["end"] = x["end"]
        else:
            junto.append(x)
    if len(junto) > 1 and junto[0]["end"] - junto[0]["start"] < 0.35:
        junto[1]["start"] = 0.0
        junto.pop(0)
    pmax = perfil.get("primeiro_plano_max_s")
    if pmax and junto and junto[0]["end"] - junto[0]["start"] > float(pmax) + 0.2:  # 1º plano curto (retém o swipe)
        a0 = dict(junto[0])
        corte = _divisoes(0.0, min(a0["end"], float(pmax) * 2), 2, palavras)
        t = corte[0] if corte and corte[0] <= float(pmax) + 0.3 else float(pmax)
        b0 = dict(a0, start=round(t, 3), parte=(a0.get("parte") or 0) + 100, entrada="punch_in",
                  efeito="zoom_out" if a0.get("efeito") != "zoom_out" else "zoom_in")
        b0.pop("destaque", None)
        if b0.get("clipe"):
            b0["clipe"] = dict(b0["clipe"], off=round(b0["clipe"]["off"] + t, 3))
        a0["end"] = round(t, 3)
        junto[0:1] = [a0, b0]
    return junto


def _efeito_seguinte(efeito: str, j: int) -> str:
    """Continuação de um momento longo do clipe: o movimento segue o sentido do anterior (aproxima → continua devagar; afasta → assenta)."""
    return {"zoom_in": "zoom_respiro", "zoom_rapido": "zoom_respiro", "zoom_out": "zoom_respiro", "": "zoom_respiro" if j % 2 else ""}.get(efeito, "zoom_respiro")


def chave_enquadrado(x: Dict[str, Any]) -> str:
    """🎥 v84_296: o pedaço vertical já enquadrado (no objeto da fala) de um plano de clipe deitado."""
    c = x.get("clipe") or {}
    if not c or "ini" not in c:
        return ""
    return f"{c.get('mid')}|{float(c['ini']):.2f}|{float(c['fim']):.2f}|{c.get('foco') or ''}"


def chave_destaque(x: Dict[str, Any]) -> str:
    c, d = x.get("clipe") or {}, x.get("destaque") or {}
    if not c or not d.get("alvo"):
        return ""
    return f"{c.get('mid')}|{c.get('ini')}|{c.get('fim')}|{d.get('alvo')}|{d.get('tipo')}|{d.get('texto', '')}"


def fixar_trechos_do_clipe(planos_v: List[Dict[str, Any]], duracoes: Dict[str, float]) -> None:
    """💬 Cada plano de clipe vira "M1@ini-fim": começa onde a cena manda (+ o quanto o plano já andou dentro dela), dura
    o tempo do plano (a fala manda) e cabe no vídeo cru (se passar do fim, recua)."""
    for x in planos_v:
        c = x.get("clipe")
        if not c:
            continue
        d = max(0.3, float(x["end"]) - float(x["start"]))
        total = float(duracoes.get(c["mid"]) or 0) or (c["ate"] + d)
        ini = float(c["de"]) + float(c.get("off") or 0)
        if ini + d > total:
            ini = max(0.0, total - d)
        x["query"] = f"{c['mid']}@{ini:.2f}-{min(total, ini + d):.2f}"
        x["clipe"] = dict(c, ini=round(ini, 3), fim=round(min(total, ini + d), 3))


def cartao_fundo(base: str, p: Dict[str, Any], tom: Optional[str] = None) -> str:
    import cenas_dp
    return cenas_dp.gerar_fundo("escuro", 1080, 1920, os.path.join(pasta(base, p["id"]), "cartoes"), tom=tom)


def destaques_do_video(p: Dict[str, Any], perfil: Dict[str, Any], planos_v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    import dp_destaques
    g = p["gravacao"]
    blocos = p["roteiro"]["blocos"]
    al, palavras = g["alinhamento"], g["palavras"]
    mapa = {int(k): int(v) for k, v in (g.get("mapa") or {}).items()}
    padrao = perfil["textos_tela"].get("estilo_destaque") or "impacto_red"
    usa = perfil["textos_tela"].get("usa", True) is not False
    out = []
    for bi, b in enumerate(blocos):
        tt = b.get("texto_tela") or {}
        cartoes = [x for x in planos_v if x["bloco"] == b["id"] and x["layout"] == "cartao"]
        texto = (tt.get("texto") or "") if usa or cartoes else ""
        if not texto and cartoes:
            texto = " ".join(sem_tags(b["fala"]).split()[:5])
        if not texto:
            continue
        est = tt.get("estilo") if dp_destaques.estilo(tt.get("estilo") or "") else padrao
        if cartoes:
            ini, fim = cartoes[0]["start"], cartoes[0]["end"]
        else:
            t = tempo_da_palavra(blocos, bi, tt.get("palavra") or texto, palavras, mapa, al)
            ini = t if t is not None else float(al[bi]["start"]) + 0.15
            fim = min(float(al[bi]["end"]), ini + max(1.2, 0.45 * len(texto.split()) + 0.8))
        if fim - ini < 0.5:
            continue
        out.append({"estilo": est, "texto": texto, "start": round(ini, 3), "end": round(fim, 3)})
    return out


def poucos_sons(sons: List[Dict[str, Any]], dur: float = 0.0) -> List[Dict[str, Any]]:
    """🔊 v84_304: só o que conta — no máx. 1 som a cada ~8 s e 1,2 s entre eles; os eventos da cena (bola lançada, chegada…)
    têm prioridade sobre os sons que o roteiro pediu. Cada som tem "_t" (segundos)."""
    dur = dur or max([e["_t"] for e in sons] + [10.0])
    limite = max(2, int(dur / 8))
    prio = sorted(sons, key=lambda e: (0 if str(e.get("curto", "")).startswith("evento:") else 1, e["_t"]))
    fica: List[Dict[str, Any]] = []
    for e in prio:
        if len(fica) >= limite:
            break
        if all(abs(e["_t"] - f["_t"]) >= 1.2 for f in fica):
            fica.append(e)
    return fica


def sfx_do_video(p: Dict[str, Any], perfil: Dict[str, Any], planos_v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Eventos do Estúdio (faixa Sons): o PICO do som cai na palavra da deixa (ou no começo do bloco)."""
    import dp_sons
    nivel = (p.get("config") or {}).get("sons_nivel") or "normal"  # (projetos antigos: como era)
    if not perfil["sfx"].get("usa", True) or nivel == "nenhum":
        return []
    g = p["gravacao"]
    blocos = p["roteiro"]["blocos"]
    al, palavras = g["alinhamento"], g["palavras"]
    mapa = {int(k): int(v) for k, v in (g.get("mapa") or {}).items()}
    vol = float(perfil["sfx"].get("volume") or 0.8)
    out: List[Dict[str, Any]] = []
    deixas = {(d["bloco"], d["indice"]): d for d in deixas_de_som(p)}
    for bi, b in enumerate(blocos):
        for k, s in enumerate(b.get("sfx") or []):
            d = deixas.get((b["id"], k)) or {}
            som = d.get("som")
            if not som or not dp_sons.som(som):
                continue
            t = tempo_da_palavra(blocos, bi, s.get("palavra") or "", palavras, mapa, al) if s.get("palavra") else None
            if t is None:
                t = 0.0 if bi == 0 else float(al[bi]["start"])
            ev = dp_sons.evento(som, t, float(s.get("volume") or vol))
            if ev:
                out.append({"id": uuid.uuid4().hex[:8], "som": som, "start": ev["inicio"], "volume": round(ev["volume"], 2),
                            "origem": "ia", "curto": f"{b['id']}:{s['tipo']}", "_t": t})
    if perfil["sfx"].get("nos_cortes") and nivel != "poucos":  # o canal põe som nas trocas de assunto: whoosh em cada bloco novo
        tipo = next((t for t in perfil["sfx"]["tipos_preferidos"] if t in ("whoosh", "swipe", "glitch", "cinema")), "whoosh")
        ultimo = None
        for bi in range(1, len(blocos)):
            t = float(al[bi]["start"])
            if any(abs(e["_t"] - t) < 0.5 for e in out):
                continue
            som = escolher_som(tipo, f"{p['id']}|corte|{bi}", ultimo)
            ultimo = som
            ev = dp_sons.evento(som, t, vol * 0.7) if som else None
            if ev:
                out.append({"id": uuid.uuid4().hex[:8], "som": som, "start": ev["inicio"], "volume": round(ev["volume"], 2),
                            "origem": "ia", "curto": f"B{bi + 1}:corte", "_t": t})
    out += sons_dos_eventos(p, planos_v, vol, out)
    if nivel == "poucos":
        out = poucos_sons(out, float(g.get("dur") or 0))
    for e in out:
        e.pop("_t", None)
    return sorted(out, key=lambda e: e["start"])


def sons_dos_eventos(p: Dict[str, Any], planos_v: List[Dict[str, Any]], vol: float, ja: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """🔊 v84_292: o que ACONTECE no clipe ganha som (a câmera virtual marcou: a bola saiu da mão → whoosh, chegou na cesta →
    impacto). O segundo do clipe vira o segundo do vídeo pelo plano que mostra aquele pedaço."""
    import dp_sons
    out: List[Dict[str, Any]] = []
    ultimo = None
    for k, ev in enumerate(p.get("eventos_som") or []):
        for x in planos_v:
            c = x.get("clipe")
            if not c or c.get("mid") != ev.get("mid") or "ini" not in c:
                continue
            if not (float(c["ini"]) <= float(ev["t"]) < float(c["fim"])):
                continue
            t = float(x["start"]) + float(ev["t"]) - float(c["ini"])
            if t >= float(x["end"]) or any(abs(float(e.get("_t", e["start"])) - t) < 0.35 for e in ja + out):
                break
            som = escolher_som(ev.get("tipo") or "whoosh", f"{p['id']}|ev|{k}", ultimo)
            ultimo = som
            evt = dp_sons.evento(som, t, vol * 0.9) if som else None
            if evt:
                out.append({"id": uuid.uuid4().hex[:8], "som": som, "start": evt["inicio"], "volume": round(evt["volume"], 2),
                            "origem": "ia", "curto": f"evento:{ev.get('o_que') or ev.get('tipo')}", "_t": t})
            break
    return out


def montar_dados_editor(base: str, pid: str, providers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Tudo que o Estúdio precisa: áudio, palavras, trechos (JSON no formato da 1ª IA), legenda, destaques e sons."""
    import dp_legendas
    p = carregar(base, pid)
    g = p.get("gravacao") or {}
    if not g.get("arquivo"):
        raise CurtoErro("Grave a sua voz (ou use a voz guia) antes de montar.")
    if g.get("chave_roteiro") != chave_roteiro(p.get("roteiro")):
        realinhar(base, pid)
        p = carregar(base, pid)
        g = p["gravacao"]
    perfil = perfil_do(base, p)
    garantir_cenas()
    providers = [x for x in (providers or (p.get("config") or {}).get("providers") or PROVIDERS_PADRAO) if x]
    if p.get("modelo") in MODELOS_CLIPE and (p.get("config") or {}).get("midia") == "flow":
        providers = ["flow"] + [x for x in providers if x == "runpod"]  # 🖼 só gerado — nada de banco/buscador da internet
        if any(m.get("tipo") == "video" and m["id"].startswith("M") for m in p.get("midias") or []):
            providers.append("material")
    anime = anime_do(base, p)
    planos_v = planos_do_video(p, providers, perfil, anime["modo"])
    fixar_trechos_do_clipe(planos_v, {m["id"]: float(m.get("dur") or 0) for m in p.get("midias") or []})
    for x in planos_v:  # 🎥 o pedaço vertical que focou no objeto da fala (curtos_comentario.enquadrar_planos)
        v = ((p.get("enquadrados") or {}).get(chave_enquadrado(x)) or {}).get("mid")
        if v and any(m["id"] == v for m in p.get("midias") or []):
            x.update(query=v, enquadrado=v)
    for x in planos_v:  # 🎯 destaque já rastreado (curtos_comentario.preparar_destaques): o pedaço com o círculo/seta
        pronto = (p.get("destaques_prontos") or {}).get(chave_destaque(x))
        if pronto and any(m["id"] == pronto for m in p.get("midias") or []):
            x.update(query=pronto, destaque_pronto=pronto)
            rid = (p.get("destaques_rastreio") or {}).get(chave_destaque(x))
            if rid:
                x["destaque_rastreio"] = rid
    import camera_exp
    if camera_exp.ligada(p):  # 🎥 v84_322: o pedaço com o zoom no detalhe / congelado com o cartão
        for x in planos_v:
            if x.get("destaque_pronto"):
                continue
            pronto = (p.get("camera_prontos") or {}).get(camera_exp.chave(x))
            if pronto and any(m["id"] == pronto for m in p.get("midias") or []):
                x.update(query=pronto, camera_pronto=pronto, efeito="")  # o movimento já está no pedaço
    # 🃏 cartões: um fundo escuro gerado aqui vira a mídia C1, C2… do projeto
    precisa_cartao = any(x["layout"] == "cartao" for x in planos_v)
    if precisa_cartao:
        fundo = cartao_fundo(base, p)
        with _TRAVA:
            q = carregar(base, pid)
            c_id = next((m["id"] for m in q["midias"] if m["id"].startswith("C")), None)
            if not c_id:
                tmp = os.path.join(pasta(base, pid), "_cartao.png")
                shutil.copy(fundo, tmp)
                c_id = adicionar_midia(base, q, tmp, "foto", "🃏 fundo do cartão de texto", "C")["id"]
                salvar(base, q)
            p = q
        for x in planos_v:
            if x["layout"] == "cartao":
                x.update(provider="material", query=c_id, media_type="video", alternativas=[])
    segs = []
    for x in planos_v:
        s = {"start": x["start"], "end": x["end"], "provider": x["provider"], "query": x["query"],
             "visual": (x.get("visual") or "")[:200]}
        if x["provider"] != "material":
            s["alternativas"] = x["alternativas"]
            s["media_type"] = x["media_type"]
        if x.get("efeito"):
            s["efeito"] = x["efeito"]
        if x.get("template"):
            s["template"] = x["template"]
        if x.get("entrada") and x["entrada"] != "none":
            s["entrada"] = x["entrada"]
        if x["layout"] in ("ia", "ia_video") and x["provider"] in ("flow", "runpod") and estilo_ia_do(p, perfil) == "realista":
            s["query"] = (s["query"].rstrip(" .") + ESTILO_REALISTA)[:600]  # 📷 parece filmado de verdade
        if x["layout"] in LAYOUTS_ANIME:
            if x["provider"] in PROVEDORES_ANIME:  # 🎌 o acervo: emoção → peso semântico; cena concreta → peso na palavra
                s["keyword_weight"], s["semantic_weight"] = (0.5, 2) if x["layout"] == "anime_reacao" else (2, 0.5)
                for k in ("obra", "personagem"):
                    if x.get(k):
                        s[k] = x[k]
            else:  # sem o acervo: busca "anime" no YouTube / buscador de imagem
                s["query"] = (s["query"] + " anime").strip()
                if s.get("alternativas"):
                    s["alternativas"] = [a + " anime" for a in s["alternativas"]]
        segs.append(s)
    dests = destaques_do_video(p, perfil, planos_v)
    resposta = {"busca_reserva": "breaking news background", "segments": segs, "highlights": dests,
                "soundtrack_suggestion": perfil["musica"].get("descricao") if perfil["musica"].get("usa") else None}
    cortes_reais = cortes_com_som_original(p)
    if cortes_reais:
        resposta["cutaway_suggestions"] = cortes_reais
    blocos = p["roteiro"]["blocos"]
    trechos = []
    for b, a in zip(blocos, g["alinhamento"]):
        ws = g["palavras"][a["ini_w"]: a["fim_w"] + 1] if a["fim_w"] >= a["ini_w"] else []
        if not ws:
            continue
        trechos.append({"start": float(ws[0]["start"]), "end": float(ws[-1]["end"]), "text": a.get("falado") or b["fala"], "words": ws})
    leg = dict(perfil["legenda"])
    leg.update({k: v for k, v in ((p.get("config") or {}).get("legenda") or {}).items()
                if k in ("estilo", "tamanho", "posicao", "maiusculas", "max_palavras", "fonte", "cor_texto", "cor_ativa", "altura", "margem")})  # 🔤
    leg["ativa"] = perfil["legenda"].get("ativa", True) is not False
    prop = proporcao_do(p)
    if prop == "1:1":  # ⬛ quadrado: a letra (que é medida pela altura) cresce pra ocupar a mesma largura de antes
        leg["tamanho"] = round(min(0.12, float(leg.get("tamanho") or 0.06) * 1.35), 4)
    mapa = {int(k): int(v) for k, v in (g.get("mapa") or {}).items()}
    palavras_leg = caixa_da_legenda(blocos, g["palavras"], mapa, g["alinhamento"], bool(perfil.get("gancho_maiusculas")))
    for t in trechos:
        t["words"] = [w for w in palavras_leg if t["start"] - 0.01 <= float(w["start"]) <= t["end"] + 0.01]
    return {"projeto": p, "perfil": perfil, "providers": providers, "audio": os.path.join(pasta(base, pid), g["arquivo"]),
            "dur": float(g["dur"]), "palavras": palavras_leg, "trechos": trechos, "resposta": resposta,
            "resposta_json": json.dumps(resposta, ensure_ascii=False), "sfx": sfx_do_video(p, perfil, planos_v),
            "legendas": dp_legendas.normalizar(leg), "planos": planos_v, "idioma": idioma_narrado(p, perfil),
            "sons_volume": perfil["sfx"].get("volume"), "orientation": prop, "marca": marca_do(base, p),
            "so_flow": p.get("modelo") in MODELOS_CLIPE and (p.get("config") or {}).get("midia") == "flow",
            # ⬛ v84_304: canal antigo sem "enquadramento" caía nas BARRAS PRETAS do editor — os shorts usam sempre o preencher
            # inteligente (tira as faixas embutidas; proporção parecida → preenche cortando o mínimo; bem diferente → o próprio
            # vídeo desfocado atrás, nunca barra preta)
            "enquadramento": perfil.get("enquadramento") or "smart"}


def bloco_do_momento(p: Dict[str, Any], mo: Dict[str, Any]) -> Optional[int]:
    """O bloco que ANUNCIA o momento (a cena dele mostra o mesmo vídeo-fonte nesses segundos). Sem cena que bata: o último
    bloco que usa aquela fonte; sem nenhum: o bloco no meio do vídeo."""
    blocos = (p.get("roteiro") or {}).get("blocos") or []
    if not blocos:
        return None
    mat, de, ate = str(mo.get("material") or ""), float(mo.get("de") or 0), float(mo.get("ate") or 0)
    melhor, usa = None, None
    for i, b in enumerate(blocos):
        for cn in b.get("cenas") or []:
            if str(cn.get("material") or "") != mat or not mat:
                continue
            usa = i
            try:
                c0, c1 = float(cn.get("de") or 0), float(cn.get("ate") or 0)
            except (TypeError, ValueError):
                continue
            if ate > de and min(c1, ate) - max(c0, de) > 0:
                melhor = i if melhor is None else min(melhor, i)
    if melhor is not None:
        return melhor
    if usa is not None:
        return usa
    return max(0, len(blocos) // 2 - 1)


def cortes_com_som_original(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    """🔥 v84_291: o MOMENTO-CHAVE (ex.: a cesta do robô) toca com o SOM ORIGINAL logo depois da frase que o anuncia — a
    narração para e volta depois. Vira um corte real do Estúdio ("cutaway", áudio "pause") com a mídia do projeto."""
    mo = p.get("momento_original") or {}
    if not mo.get("midia"):
        return []
    g = p.get("gravacao") or {}
    al = g.get("alinhamento") or []
    i = bloco_do_momento(p, mo)
    if i is None or i >= len(al):
        return []
    dur = float(g.get("dur") or (al[-1]["end"] if al else 0))
    t = min(dur, float(al[i]["end"]) + 0.15)
    out = {"insertion_point": round(t, 3), "description": str(mo.get("descricao") or "momento com o som original")[:200],
           "audio_mode": "pause", "midia": str(mo["midia"])}
    for k in ("inicio", "fim"):
        if mo.get(k) not in (None, ""):
            out[k] = f"{float(mo[k]):.2f}"
    return [out]


# ------------------------------------------------------------------ tela
def resumo_tela(base: str, p: Dict[str, Any]) -> Dict[str, Any]:
    """O que a página do projeto mostra (sem as listas enormes de palavras)."""
    out = json.loads(json.dumps(p))
    g = out.get("gravacao") or {}
    for k in ("palavras_original", "palavras", "mapa"):
        g.pop(k, None)
    if g:
        g["desatualizada"] = g.get("chave_roteiro") != chave_roteiro(p.get("roteiro"))
    t = out.get("tts") or {}
    if t:
        t["desatualizada"] = t.get("chave") != chave_roteiro(p.get("roteiro"))
    out["deixas"] = deixas_de_som(p) if p.get("roteiro") else []
    try:
        import dp_sons
        for d in out["deixas"]:
            d["arquivo"] = (dp_sons.som(d["som"]) or {}).get("arquivo") if d.get("som") else None
    except Exception:  # noqa: BLE001
        pass
    out["midias_canal"] = [{k: m[k] for k in ("id", "tipo", "descricao")} for m in midias_do_canal(base, canal_do(base, p))]
    out["marca"] = marca_do(base, p)
    out["proporcao"] = proporcao_do(p)
    perfil = perfil_do(base, p)
    out["palavras_alvo"] = palavras_alvo(perfil, (p.get("config") or {}).get("duracao_alvo_s") or None)
    out["palavras_roteiro"] = len(texto_completo(p.get("roteiro")).split())
    return out


# ------------------------------------------------------------------ 🔁 trocar a voz de um projeto que já está no editor
def chave_do_plano(x: Dict[str, Any]) -> str:
    return f"{x.get('bloco')}:{x.get('cena')}:{x.get('parte')}"


def mapear_tempo(t: float, antigo: List[Dict[str, Any]], novo: List[Dict[str, Any]]) -> float:
    """Tempo na voz ANTIGA → tempo na voz NOVA, bloco a bloco (dentro do bloco, proporcional)."""
    por_id = {a["bloco"]: a for a in novo}
    for a in antigo:
        n = por_id.get(a["bloco"])
        if n is None:
            continue
        a0, a1 = float(a["start"]), float(a["end"])
        if a0 <= t <= a1 or a is antigo[-1] and t > a1:
            frac = 0.0 if a1 <= a0 else min(1.0, max(0.0, (t - a0) / (a1 - a0)))
            return round(float(n["start"]) + frac * (float(n["end"]) - float(n["start"])), 3)
    return round(t, 3)


def reencaixar_planos(pendentes: List[Dict[str, Any]], previas: List[Any], novos: List[Dict[str, Any]],
                      campos_novos: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
                      ) -> Tuple[List[Dict[str, Any]], List[Any], List[int]]:
    """Os trechos do editor nos tempos da voz NOVA, mantendo a mídia que cada um já tem (a prévia/escolha).
    Cada trecho do editor guarda a "curto_chave" do plano (bloco:cena:parte). Se você dividiu um trecho no editor
    (várias com a mesma chave), o tempo novo do plano é repartido na mesma proporção. Plano sem par (o roteiro mudou):
    trecho novo, sem prévia (índice devolvido em `sem_previa`)."""
    por_chave: Dict[str, List[int]] = {}
    for i, s in enumerate(pendentes):
        if s.get("curto_chave"):
            por_chave.setdefault(s["curto_chave"], []).append(i)
    por_cena: Dict[str, int] = {}
    for i, s in enumerate(pendentes):
        if s.get("curto_chave"):
            por_cena.setdefault(s["curto_chave"].rsplit(":", 1)[0], i)
    out_s: List[Dict[str, Any]] = []
    out_p: List[Any] = []
    sem: List[int] = []
    for pl in novos:
        k = chave_do_plano(pl)
        a, b = float(pl["start"]), float(pl["end"])
        velhos = por_chave.get(k) or []
        if velhos:
            durs = [max(0.05, float(pendentes[i]["end"]) - float(pendentes[i]["start"])) for i in velhos]
            tot = sum(durs)
            t = a
            for j, (i, dd) in enumerate(zip(velhos, durs)):
                fim = b if j == len(velhos) - 1 else round(t + (b - a) * dd / tot, 3)
                out_s.append(dict(pendentes[i], start=round(t, 3), end=round(fim, 3)))
                out_p.append(previas[i] if i < len(previas) else None)
                t = fim
            continue
        base = pendentes[por_cena[k.rsplit(":", 1)[0]]] if k.rsplit(":", 1)[0] in por_cena else None
        if base is not None:  # mesma cena, pedaço a mais: mesma busca, mídia própria
            novo = {kk: vv for kk, vv in base.items() if kk not in ("override_source", "venda_midia", "_antes_material")}
            if pl.get("provider") == "material":  # mídia da notícia: é o mesmo arquivo
                novo = dict(base)
        else:
            novo = dict(campos_novos(pl) if campos_novos else {"provider": pl["provider"], "query": pl["query"],
                                                              "media_type": pl.get("media_type") or "video"})
        novo.update(start=round(a, 3), end=round(b, 3), curto_chave=k)
        out_s.append(novo)
        out_p.append(None)
        sem.append(len(out_s) - 1)
    for i in range(1, len(out_s)):  # sem buraco nem sobra
        out_s[i]["start"] = out_s[i - 1]["end"]
    return out_s, out_p, sem
