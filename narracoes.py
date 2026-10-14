"""
narracoes.py
==============

"Roteiro para Áudio": projetos AVULSOS de narração — sem vídeo nenhum
envolvido. Você cola um texto bruto (um roteiro escrito à mão, um
script, qualquer coisa), ele separa em falas, e cada fala vira uma
narração com o motor de voz escolhido (Piper / XTTS v2 / Kokoro — ver
`toolkit/tts/voice_generator.py`), juntas num único áudio final.

Portado do projeto "shortmaker" (aba "Narrações" do editor de
dublagem) e adaptado pra este site: o modo de gravar a PRÓPRIA voz
("Minha Voz") não foi trazido — aqui todas as falas usam um dos três
motores de IA. A separação do texto em falas, a limpeza do texto antes
de mandar pro TTS (evita o modelo "falar" pontuação em voz alta) e a
normalização de volume em duas passadas (EBU R128/loudnorm) do áudio
final são as mesmas técnicas do projeto original.

Fluxo
-----
    criar_projeto("Meu roteiro")
        -> projeto_id

    importar_roteiro(projeto_id, texto="Fala um.\\nFala dois.", modo_separacao="linha")
        -> quebra em falas, uma por linha

    salvar_config(projeto_id, motor="piper", voz="pt_BR-faber-medium", pausa_segundos=0.6)

    gerar_audio_projeto(projeto_id, base_dir, on_log=print)
        -> gera cada fala com o motor escolhido, junta tudo com pausas
           entre as falas, normaliza o volume final, exporta .mp3

Armazenamento
-------------
Cada projeto vira uma pasta em `<base_dir>/narracoes/<projeto_id>/`:

    projeto.json     -- nome, motor, voz, idioma, velocidade, pausa
    roteiro.json     -- {"falas": [{"texto": "..."}]}
    geracoes.json    -- histórico de áudios já gerados
    geracoes/*.mp3   -- os áudios em si
"""

from __future__ import annotations

import json
import math
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

MOTORES_VALIDOS = ("piper", "xtts", "chatterbox", "chatterbox_turbo", "kokoro", "fish_s2")

CONFIG_PADRAO: Dict[str, Any] = {
    "motor": "piper",
    "voz": "pt_BR-faber-medium",
    "idioma": "",  # só usado por xtts/chatterbox/kokoro; vazio = deixa o motor decidir sozinho
    "velocidade": 1.0,
    "pausaSegundos": 0.6,
    "usarGpu": True,
    "vozPerfil": "",  # xtts/chatterbox: nome de um perfil salvo (voice_generator.salvar_perfil_de_voz) -- tem prioridade sobre "voz"
    "xttsCheckpoint": "",  # xtts: chave de XTTS_CHECKPOINTS_CONHECIDOS ("" ou "padrao" = modelo oficial)
    "chatterboxExaggeration": 0.5,  # chatterbox: intensidade emocional (0.0 a 1.0)
    "chatterboxCfgWeight": 0.5,  # chatterbox: aderência ao estilo/sotaque da voz de referência (0.0 a 1.0)
    "kokoroVariante": "v1.0",  # kokoro: "v1.0" ou "v1.1-zh" (ver KOKORO_MODEL_VARIANTS)
    "kokoroPrecisao": "fp32",  # kokoro: "fp32"/"fp16"/"int8" (ver KOKORO_PRECISIONS)
    "fishReferenceId": "",  # fish_s2 (API da Fish Audio): id de uma voz salva na conta — sem perfil de voz
    "fishTemperatura": 0.8,  # fish_s2: 0.1–1.0 (mais alto = mais variado/expressivo)
    "multiVoz": False,  # 🎭 multi voice: [slug] no texto troca pra voz salva com esse slug (multivoz.py) e não é lido
    "cortarSilencioGravacoes": True,  # corta automaticamente o silêncio do início/fim das SUAS gravações (não mexe em pausa no meio da fala) na hora de gerar -- não modifica o take salvo, só o áudio final
}


class NarracaoError(Exception):
    """Erro de uso (projeto não encontrado, roteiro vazio, texto inválido etc.)."""


# ============================================================ #
# Armazenamento — uma pasta por projeto
# ============================================================ #

def narracoes_dir(base_dir: str) -> Path:
    d = Path(base_dir) / "narracoes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pasta_projeto(base_dir: str, projeto_id: str) -> Path:
    p = narracoes_dir(base_dir) / projeto_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _projeto_path(base_dir: str, projeto_id: str) -> Path:
    return _pasta_projeto(base_dir, projeto_id) / "projeto.json"


def projeto_existe(base_dir: str, projeto_id: str) -> bool:
    # Não passa por `_pasta_projeto()` de propósito -- ela CRIA a pasta
    # como efeito colateral (necessário pros caminhos de ESCRITA), o
    # que deixaria uma pasta vazia no disco toda vez que alguém checasse
    # a existência de um id que não existe.
    return (narracoes_dir(base_dir) / projeto_id / "projeto.json").exists()


def _gerar_id_projeto() -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex[:8]}"


def criar_projeto(base_dir: str, nome: str = "") -> Dict[str, Any]:
    nome = (nome or "").strip() or time.strftime("Narração %d/%m/%Y %H:%M")
    projeto_id = _gerar_id_projeto()
    projeto = {"nome": nome, "criadoEm": time.time(), **CONFIG_PADRAO}
    _projeto_path(base_dir, projeto_id).write_text(
        json.dumps(projeto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"projetoId": projeto_id, **projeto}


def carregar_projeto(base_dir: str, projeto_id: str) -> Dict[str, Any]:
    # Mesmo motivo do `projeto_existe()` acima: lê sem passar por
    # `_pasta_projeto()`, que criaria a pasta mesmo pra um id inexistente.
    caminho = narracoes_dir(base_dir) / projeto_id / "projeto.json"
    if not caminho.exists():
        raise NarracaoError(f"Projeto {projeto_id!r} não encontrado.")
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    # mescla com o padrão -- projetos criados antes de um novo campo existir
    # (ex: "usarGpu") não quebram, só usam o valor padrão dele.
    return {**CONFIG_PADRAO, **dados, "projetoId": projeto_id}


def salvar_config(
    base_dir: str,
    projeto_id: str,
    nome: Optional[str] = None,
    motor: Optional[str] = None,
    voz: Optional[str] = None,
    idioma: Optional[str] = None,
    velocidade: Optional[float] = None,
    pausa_segundos: Optional[float] = None,
    usar_gpu: Optional[bool] = None,
    voz_perfil: Optional[str] = None,
    xtts_checkpoint: Optional[str] = None,
    chatterbox_exaggeration: Optional[float] = None,
    chatterbox_cfg_weight: Optional[float] = None,
    kokoro_variante: Optional[str] = None,
    kokoro_precisao: Optional[str] = None,
    cortar_silencio_gravacoes: Optional[bool] = None,
    multi_voz: Optional[bool] = None,
    fish_reference_id: Optional[str] = None,
    fish_temperatura: Optional[float] = None,
) -> Dict[str, Any]:
    projeto = carregar_projeto(base_dir, projeto_id)
    if nome is not None and nome.strip():
        projeto["nome"] = nome.strip()
    if motor is not None:
        if motor not in MOTORES_VALIDOS:
            raise NarracaoError(f"Motor {motor!r} inválido — use um de {MOTORES_VALIDOS}.")
        projeto["motor"] = motor
    if voz is not None:
        projeto["voz"] = voz.strip()
    if idioma is not None:
        projeto["idioma"] = idioma.strip()
    if velocidade is not None:
        try:
            projeto["velocidade"] = max(0.5, min(float(velocidade), 2.0))
        except (TypeError, ValueError):
            pass
    if pausa_segundos is not None:
        try:
            projeto["pausaSegundos"] = max(0.0, min(float(pausa_segundos), 10.0))
        except (TypeError, ValueError):
            pass
    if usar_gpu is not None:
        projeto["usarGpu"] = bool(usar_gpu)
    if voz_perfil is not None:
        projeto["vozPerfil"] = voz_perfil.strip()
    if xtts_checkpoint is not None:
        projeto["xttsCheckpoint"] = xtts_checkpoint.strip()
    if chatterbox_exaggeration is not None:
        try:
            projeto["chatterboxExaggeration"] = max(0.0, min(float(chatterbox_exaggeration), 1.0))
        except (TypeError, ValueError):
            pass
    if chatterbox_cfg_weight is not None:
        try:
            projeto["chatterboxCfgWeight"] = max(0.0, min(float(chatterbox_cfg_weight), 1.0))
        except (TypeError, ValueError):
            pass
    if kokoro_variante is not None:
        projeto["kokoroVariante"] = kokoro_variante.strip() or CONFIG_PADRAO["kokoroVariante"]
    if kokoro_precisao is not None:
        projeto["kokoroPrecisao"] = kokoro_precisao.strip() or CONFIG_PADRAO["kokoroPrecisao"]
    if cortar_silencio_gravacoes is not None:
        projeto["cortarSilencioGravacoes"] = bool(cortar_silencio_gravacoes)
    if multi_voz is not None:
        projeto["multiVoz"] = bool(multi_voz)
    if fish_reference_id is not None:
        projeto["fishReferenceId"] = re.sub(r"[^0-9a-zA-Z_-]", "", str(fish_reference_id))[:64]
    if fish_temperatura not in (None, ""):
        try:
            projeto["fishTemperatura"] = max(0.1, min(float(fish_temperatura), 1.0))
        except (TypeError, ValueError):
            pass

    projeto_salvo = {k: v for k, v in projeto.items() if k != "projetoId"}
    _projeto_path(base_dir, projeto_id).write_text(
        json.dumps(projeto_salvo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return projeto


def listar_projetos(base_dir: str) -> List[Dict[str, Any]]:
    raiz = narracoes_dir(base_dir)
    projetos = []
    for pasta in sorted(raiz.iterdir(), reverse=True):
        caminho = pasta / "projeto.json"
        if not caminho.exists():
            continue
        try:
            projeto = carregar_projeto(base_dir, pasta.name)
        except Exception:  # noqa: BLE001
            continue
        roteiro = carregar_roteiro(base_dir, pasta.name)
        projeto["quantidadeFalas"] = len(roteiro["falas"])
        projeto["quantidadeGeracoes"] = len(carregar_geracoes(base_dir, pasta.name))
        projetos.append(projeto)
    projetos.sort(key=lambda p: p.get("criadoEm", 0), reverse=True)
    return projetos


def excluir_projeto(base_dir: str, projeto_id: str) -> None:
    pasta = narracoes_dir(base_dir) / projeto_id
    if pasta.exists():
        shutil.rmtree(pasta)


# ============================================================ #
# Roteiro (as falas)
# ============================================================ #

def separar_texto_bruto(texto: str, modo: str = "linha") -> List[str]:
    """Separa o texto colado em falas.

    "linha": uma fala por linha não vazia (o jeito mais previsível de
        colar um roteiro que já veio quebrado por fala).
    "frase": separa em `.`, `!` ou `?` seguido de espaço/quebra — útil
        quando o texto vem em parágrafo corrido, sem quebra manual.
    """
    texto = (texto or "").strip()
    if not texto:
        return []
    if modo == "frase":
        pedacos = re.split(r"(?<=[.!?])\s+", texto.replace("\n", " "))
    else:
        pedacos = texto.splitlines()
    return [p.strip() for p in pedacos if p.strip()]


def _roteiro_path(base_dir: str, projeto_id: str) -> Path:
    return _pasta_projeto(base_dir, projeto_id) / "roteiro.json"


def carregar_roteiro(base_dir: str, projeto_id: str) -> Dict[str, Any]:
    caminho = _roteiro_path(base_dir, projeto_id)
    if not caminho.exists():
        return {"falas": []}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or not isinstance(dados.get("falas"), list):
            return {"falas": []}
        return dados
    except Exception:  # noqa: BLE001
        return {"falas": []}


def _salvar_roteiro(base_dir: str, projeto_id: str, roteiro: Dict[str, Any]) -> None:
    _roteiro_path(base_dir, projeto_id).write_text(
        json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def importar_roteiro(base_dir: str, projeto_id: str, texto: str, modo_separacao: str = "linha") -> Dict[str, Any]:
    """Substitui o roteiro inteiro do projeto pelas falas separadas de
    `texto`. Levanta `NarracaoError` se não sobrar nenhuma fala depois
    de separar (texto vazio, ou só espaços/quebras de linha).
    """
    if not projeto_existe(base_dir, projeto_id):
        raise NarracaoError(f"Projeto {projeto_id!r} não encontrado.")
    falas_texto = separar_texto_bruto(texto, modo_separacao)
    if not falas_texto:
        raise NarracaoError("Cole o texto bruto do roteiro antes de importar.")
    roteiro = {"falas": [{"texto": t} for t in falas_texto]}
    _salvar_roteiro(base_dir, projeto_id, roteiro)
    return roteiro


def adicionar_fala(base_dir: str, projeto_id: str, texto: str) -> Dict[str, Any]:
    texto = (texto or "").strip()
    if not texto:
        raise NarracaoError("Digite o texto dessa fala antes de adicionar.")
    roteiro = carregar_roteiro(base_dir, projeto_id)
    roteiro["falas"].append({"texto": texto})
    _salvar_roteiro(base_dir, projeto_id, roteiro)
    return roteiro


def editar_fala(base_dir: str, projeto_id: str, indice: int, texto: str) -> Dict[str, Any]:
    texto = (texto or "").strip()
    if not texto:
        raise NarracaoError("O texto da fala não pode ficar vazio.")
    roteiro = carregar_roteiro(base_dir, projeto_id)
    if not (0 <= indice < len(roteiro["falas"])):
        raise NarracaoError(f"Essa fala (índice {indice}) não existe.")
    roteiro["falas"][indice]["texto"] = texto
    _salvar_roteiro(base_dir, projeto_id, roteiro)
    return roteiro


def remover_fala(base_dir: str, projeto_id: str, indice: int) -> Dict[str, Any]:
    roteiro = carregar_roteiro(base_dir, projeto_id)
    if not (0 <= indice < len(roteiro["falas"])):
        raise NarracaoError(f"Essa fala (índice {indice}) não existe.")
    roteiro["falas"].pop(indice)
    _salvar_roteiro(base_dir, projeto_id, roteiro)
    return roteiro


# ============================================================ #
# Limpeza de texto antes do TTS
# ============================================================ #

MOTORES_COM_TAGS_LIVRES = ("fish_s2",)   # entendem QUALQUER [descrição] curta: [whisper], [excited], [rindo baixinho]


def motor_aceita_tags(motor: str) -> bool:
    return motor == "chatterbox_turbo" or motor in MOTORES_COM_TAGS_LIVRES


def limpar_texto_para_tts(texto: str, preservar_tags_chatterbox_turbo: bool = False, motor: str = "") -> str:
    """Limpa o texto ANTES de mandar pro motor de voz, pra evitar que o
    modelo vocalize sinais de pontuação literalmente (falar "aspas",
    "reticências" etc — comum em Piper/Kokoro com pontuação incomum).
    Não altera o texto salvo no roteiro, só o que é enviado ao TTS.

    `preservar_tags_chatterbox_turbo` (padrão False): quando True,
    tags reconhecidas do Chatterbox Turbo (ex: "[laugh]",
    "[whispering]") são preservadas EXATAMENTE como estão, em vez de
    perder os colchetes junto com o resto da pontuação -- só faz
    sentido ligar isso quando o motor de destino é o Chatterbox Turbo
    (o único que entende essas tags); nos outros motores, colchetes
    são só pontuação normal e continuam sendo removidos como sempre.
    """
    if not texto:
        return texto
    import chamadas as _ch
    t = _ch.remover_marcadores(texto)  # [[INSCREVA: texto]] -> só o texto (ver chamadas.py)

    tags_preservadas: List[str] = []
    if motor == "chatterbox_turbo":
        preservar_tags_chatterbox_turbo = True
    if motor in MOTORES_COM_TAGS_LIVRES:  # 🐟 Fish S2: toda [tag] curta fica como está (é emoção/efeito)
        def _preservar_livre(m: "re.Match") -> str:
            conteudo = " ".join(m.group(1).split())
            if not conteudo or re.fullmatch(r"[\d\s.,:-]+", conteudo):
                return m.group(0)  # [3], [00:12] etc.: não é tag
            tags_preservadas.append(f"[{conteudo}]")
            return f"\x00TAG{len(tags_preservadas) - 1}\x00"
        t = re.sub(r"\[([^\[\]]{1,40})\]", _preservar_livre, t)
    if preservar_tags_chatterbox_turbo:
        from tts.voice_generator import CHATTERBOX_TURBO_TAGS

        def _preservar_se_for_tag_conhecida(m: "re.Match") -> str:
            conteudo = m.group(1).strip().lower()
            if conteudo in CHATTERBOX_TURBO_TAGS:
                marcador = f"\x00TAG{len(tags_preservadas)}\x00"
                tags_preservadas.append(f"[{conteudo}]")
                return marcador
            return m.group(0)  # colchete comum (não é uma tag reconhecida) -- limpa normalmente depois

        t = re.sub(r"\[([^\[\]]{1,30})\]", _preservar_se_for_tag_conhecida, t)

    t = re.sub(r"[\"'\u201c\u201d\u2018\u2019\u201e\u201f\u00ab\u00bb`´]", "", t)
    t = re.sub(r"[()\[\]{}]", "", t)
    t = t.replace("\u2026", ",")
    t = re.sub(r"\.{2,}", ",", t)
    t = re.sub(r"(?<!\d)\.(?!\d)", ",", t)  # ponto solto (não decimal) -> vírgula, pausa em vez de "ponto"
    t = re.sub(r"[*_~#]", "", t)
    t = re.sub(r"([!?,;:])\1+", r"\1", t)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"^[,;:\s]+", "", t)
    t = re.sub(r"[,;:\s]+$", "", t)
    resultado = t.strip()

    for i, tag in enumerate(tags_preservadas):
        resultado = resultado.replace(f"\x00TAG{i}\x00", tag)
    return resultado


# ============================================================ #
# Normalização de volume (loudnorm/EBU R128, duas passadas)
# ============================================================ #

def _medir_loudnorm(caminho: Path, alvo_lufs: float, tp: float = -1.5, lra: float = 11) -> Optional[dict]:
    """1a passada: mede as estatísticas reais do áudio (sem alterar
    nada), pra 2a passada aplicar o ganho certo com precisão — uma
    passada só costuma ficar imprecisa em áudio curto, como é o caso
    de uma fala por vez.
    """
    resultado = subprocess.run(
        ["ffmpeg", "-i", str(caminho), "-af",
         f"loudnorm=I={alvo_lufs}:TP={tp}:LRA={lra}:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    saida = resultado.stderr
    inicio, fim = saida.rfind("{"), saida.rfind("}")
    if inicio == -1 or fim == -1:
        return None
    try:
        return json.loads(saida[inicio:fim + 1])
    except Exception:  # noqa: BLE001
        return None


def _filtro_loudnorm_duas_passadas(caminho: Path, alvo_lufs: float, tp: float = -1.5, lra: float = 11) -> str:
    stats = _medir_loudnorm(caminho, alvo_lufs, tp, lra)
    if not stats:
        return f"loudnorm=I={alvo_lufs}:TP={tp}:LRA={lra}"
    try:
        medido_i = float(stats["input_i"])
        medido_tp = float(stats["input_tp"])
        medido_lra = float(stats["input_lra"])
        medido_thresh = float(stats["input_thresh"])
        medido_offset = float(stats["target_offset"])
    except (KeyError, TypeError, ValueError):
        return f"loudnorm=I={alvo_lufs}:TP={tp}:LRA={lra}"
    if not all(math.isfinite(v) for v in (medido_i, medido_tp, medido_lra, medido_thresh, medido_offset)):
        # Áudio silencioso (ou quase) -- nada pra normalizar mesmo, e a
        # passada única lida com silêncio sem quebrar (valores -inf
        # medidos fariam o ffmpeg rejeitar o comando).
        return f"loudnorm=I={alvo_lufs}:TP={tp}:LRA={lra}"
    return (
        f"loudnorm=I={alvo_lufs}:TP={tp}:LRA={lra}:"
        f"measured_I={medido_i}:measured_TP={medido_tp}:"
        f"measured_LRA={medido_lra}:measured_thresh={medido_thresh}:"
        f"offset={medido_offset}:linear=true"
    )


def normalizar_volume_wav(wav_in: Path, wav_out: Path, alvo_lufs: float = -16.0) -> None:
    """Normaliza o volume do áudio final (loudnorm/EBU R128, duas
    passadas) pra um nível padrão — deixa o resultado num volume
    consistente independente do motor/voz escolhido.
    """
    filtro = _filtro_loudnorm_duas_passadas(wav_in, alvo_lufs)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_in), "-af", filtro, str(wav_out)],
        capture_output=True,
    )


# ============================================================ #
# Geração do áudio final
# ============================================================ #

def _geracoes_path(base_dir: str, projeto_id: str) -> Path:
    return _pasta_projeto(base_dir, projeto_id) / "geracoes.json"


def carregar_geracoes(base_dir: str, projeto_id: str) -> List[Dict[str, Any]]:
    caminho = _geracoes_path(base_dir, projeto_id)
    if not caminho.exists():
        return []
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except Exception:  # noqa: BLE001
        return []


def _salvar_geracoes(base_dir: str, projeto_id: str, geracoes: List[Dict[str, Any]]) -> None:
    _geracoes_path(base_dir, projeto_id).write_text(
        json.dumps(geracoes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def excluir_geracao(base_dir: str, projeto_id: str, geracao_id: str) -> None:
    geracao_id_segura = "".join(c for c in geracao_id if c.isalnum() or c == "_")
    caminho = _pasta_projeto(base_dir, projeto_id) / "geracoes" / f"{geracao_id_segura}.mp3"
    if caminho.exists():
        caminho.unlink()
    geracoes = [g for g in carregar_geracoes(base_dir, projeto_id) if g.get("id") != geracao_id]
    _salvar_geracoes(base_dir, projeto_id, geracoes)


def _kwargs_motor(projeto: Dict[str, Any]) -> Dict[str, Any]:
    """Monta os kwargs certos pra `tts.voice_generator.gerar_audio()` a
    partir da config do projeto — cada motor usa nomes de parâmetro
    diferentes (ver voice_generator.py), então esse é o único lugar que
    precisa saber disso.
    """
    motor = projeto["motor"]
    use_gpu = None if projeto.get("usarGpu", True) else False
    if motor == "piper":
        return {"nome_voz": projeto["voz"] or "pt_BR-faber-medium",
                "velocidade": projeto.get("velocidade", 1.0), "use_gpu": use_gpu}
    if motor == "xtts":
        kwargs: Dict[str, Any] = {"idioma": projeto.get("idioma") or "pt", "use_gpu": use_gpu}
        # prioridade: perfil salvo > voz/speaker pronta do modelo (o
        # mesmo critério que xtts_synthesize já usa pra speaker_wav vs
        # speaker -- um perfil é sempre clonagem, então "ganha" de uma
        # voz pronta se os dois estiverem preenchidos).
        if projeto.get("vozPerfil"):
            kwargs["voice_profile"] = projeto["vozPerfil"]
        elif projeto.get("voz"):
            kwargs["speaker"] = projeto["voz"]
        checkpoint = projeto.get("xttsCheckpoint")
        if checkpoint and checkpoint != "padrao":
            kwargs["checkpoint_conhecido"] = checkpoint
        return kwargs
    if motor == "chatterbox":
        kwargs = {
            "idioma": projeto.get("idioma") or "pt", "use_gpu": use_gpu,
            "exaggeration": projeto.get("chatterboxExaggeration", 0.5),
            "cfg_weight": projeto.get("chatterboxCfgWeight", 0.5),
        }
        # mesmo perfil de voz que o XTTS já usa -- os dois só precisam
        # de um áudio de referência pra clonar a voz.
        if projeto.get("vozPerfil"):
            kwargs["voice_profile"] = projeto["vozPerfil"]
        return kwargs
    if motor == "chatterbox_turbo":
        kwargs = {"use_gpu": use_gpu}
        # mesmo perfil de voz que XTTS/Chatterbox já usam -- sem
        # idioma/exaggeration/cfg_weight, o Turbo não aceita nenhum
        # dos três (só inglês, sem esses controles).
        if projeto.get("vozPerfil"):
            kwargs["voice_profile"] = projeto["vozPerfil"]
        return kwargs
    if motor == "fish_s2":
        kwargs = {"idioma": projeto.get("idioma") or "pt", "velocidade": projeto.get("velocidade", 1.0)}
        try:
            kwargs["temperatura"] = max(0.1, min(1.0, float(projeto.get("fishTemperatura") or 0.8)))
        except (TypeError, ValueError):
            pass
        # mesmo perfil de voz do XTTS/Chatterbox (clonagem) — ou uma voz salva na conta da Fish Audio
        if projeto.get("vozPerfil"):
            kwargs["voice_profile"] = projeto["vozPerfil"]
        elif projeto.get("fishReferenceId"):
            kwargs["reference_id"] = projeto["fishReferenceId"]
        return kwargs
    # kokoro
    return {
        "voz": projeto["voz"] or "pf_dora", "velocidade": projeto.get("velocidade", 1.0),
        "idioma": projeto.get("idioma") or None,
        "variante": projeto.get("kokoroVariante") or CONFIG_PADRAO["kokoroVariante"],
        "precisao": projeto.get("kokoroPrecisao") or CONFIG_PADRAO["kokoroPrecisao"],
    }


# ============================================================ #
# Gravações da própria voz (por fala) — grave direto pelo microfone do
# navegador em vez de usar o motor de IA nessa fala específica.
# Suporta MÚLTIPLOS "takes" por fala (grava de novo quantas vezes
# quiser sem apagar as gravações anteriores, e escolhe qual usar).
# Portado do recurso "Minha Voz" do projeto shortmaker, adaptado ao
# modelo de falas do Roteiro para Áudio -- aqui não precisa ajustar
# velocidade pra caber num tempo fixo (diferente de dublagem sobre um
# vídeo já cortado): a gravação entra igual a uma fala gerada por TTS,
# com a pausa configurada entre uma e outra.
#
# Cada take pode opcionalmente ter uma versão com REALCE ("audio
# enhance" -- redução de ruído, equalização, compressão, normalização;
# ver `aplicar_realce_de_voz()` em toolkit/tts/voice_generator.py)
# gerada sob demanda, sem sobrescrever o original -- ver
# `gerar_realce_de_take`/`usar_realce_de_take` mais abaixo.
# ============================================================ #

def _gravacoes_dir(base_dir: str, projeto_id: str) -> Path:
    d = _pasta_projeto(base_dir, projeto_id) / "gravacoes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gravacoes_config_path(base_dir: str, projeto_id: str) -> Path:
    return _gravacoes_dir(base_dir, projeto_id) / "config.json"


def _carregar_gravacoes_config(base_dir: str, projeto_id: str) -> Dict[str, Any]:
    caminho = _gravacoes_config_path(base_dir, projeto_id)
    if not caminho.exists():
        return {}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _salvar_gravacoes_config(base_dir: str, projeto_id: str, dados: Dict[str, Any]) -> None:
    _gravacoes_config_path(base_dir, projeto_id).write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def listar_gravacoes(base_dir: str, projeto_id: str) -> Dict[str, Any]:
    """`{"<indice da fala>": {"usar": bool, "takeAtivo": id|None, "takes": [{"id","duracaoSegundos","criadoEm"}, ...]}}`"""
    return _carregar_gravacoes_config(base_dir, projeto_id)


def _duracao_audio(caminho) -> Optional[float]:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(caminho)],
            capture_output=True, text=True, timeout=15,
        )
        return round(float(r.stdout.strip()), 2)
    except Exception:  # noqa: BLE001
        return None


def salvar_gravacao(base_dir: str, projeto_id: str, indice_fala: int, caminho_audio_bruto: str) -> Dict[str, Any]:
    """Recebe uma gravação NOVA (geralmente webm/ogg vindo do
    MediaRecorder do navegador), converte pra wav mono e salva como um
    TAKE NOVO dessa fala — não apaga takes anteriores. O take recém-
    gravado já fica marcado como ativo e com "usar" ligado (mais fácil
    comparar "o que acabei de gravar" primeiro; dá pra trocar depois).
    """
    if not projeto_existe(base_dir, projeto_id):
        raise NarracaoError(f"Projeto {projeto_id!r} não encontrado.")
    roteiro = carregar_roteiro(base_dir, projeto_id)
    if not (0 <= indice_fala < len(roteiro["falas"])):
        raise NarracaoError(f"Essa fala (índice {indice_fala}) não existe.")
    if not os.path.exists(caminho_audio_bruto):
        raise NarracaoError(f"Áudio gravado não encontrado: {caminho_audio_bruto!r}")

    pasta = _gravacoes_dir(base_dir, projeto_id)
    take_id = uuid.uuid4().hex[:8]
    destino = pasta / f"seg_{indice_fala:04d}_{take_id}.wav"

    resultado = subprocess.run(
        ["ffmpeg", "-y", "-i", caminho_audio_bruto, "-ar", "24000", "-ac", "1", str(destino)],
        capture_output=True, timeout=60,
    )
    if resultado.returncode != 0 or not destino.exists():
        raise NarracaoError(
            f"ffmpeg não conseguiu converter a gravação: "
            f"{resultado.stderr.decode(errors='replace')[-300:]}"
        )

    duracao = _duracao_audio(destino)

    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave, {"takes": [], "takeAtivo": None, "usar": False})
    entrada.setdefault("takes", [])
    entrada["takes"].append({
        "id": take_id, "duracaoSegundos": duracao,
        "criadoEm": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    entrada["takeAtivo"] = take_id
    entrada["usar"] = True
    dados[chave] = entrada
    _salvar_gravacoes_config(base_dir, projeto_id, dados)

    return {"indice": indice_fala, "takeId": take_id, "duracaoSegundos": duracao, "usar": True}


def marcar_uso_gravacao(base_dir: str, projeto_id: str, indice_fala: int, usar: bool) -> Dict[str, Any]:
    """Liga/desliga o uso da gravação nessa fala (sem mexer em qual take
    está selecionado) — desligado, a fala volta a usar o motor de IA."""
    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave, {"takes": [], "takeAtivo": None, "usar": False})
    entrada["usar"] = bool(usar)
    dados[chave] = entrada
    _salvar_gravacoes_config(base_dir, projeto_id, dados)
    return entrada


def selecionar_take(base_dir: str, projeto_id: str, indice_fala: int, take_id: str) -> Dict[str, Any]:
    """Marca qual dos takes gravados pra essa fala deve ser usado (grave
    vários e escolha o melhor depois)."""
    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave)
    if not entrada:
        raise NarracaoError("Essa fala ainda não tem gravações.")
    ids_existentes = {t["id"] for t in entrada.get("takes", [])}
    if take_id not in ids_existentes:
        raise NarracaoError("Esse take não existe pra essa fala.")
    entrada["takeAtivo"] = take_id
    dados[chave] = entrada
    _salvar_gravacoes_config(base_dir, projeto_id, dados)
    return entrada


def excluir_take(base_dir: str, projeto_id: str, indice_fala: int, take_id: str) -> None:
    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave)
    if not entrada:
        return
    entrada["takes"] = [t for t in entrada.get("takes", []) if t.get("id") != take_id]
    if entrada.get("takeAtivo") == take_id:
        entrada["takeAtivo"] = entrada["takes"][-1]["id"] if entrada["takes"] else None
        if not entrada["takes"]:
            entrada["usar"] = False
    dados[chave] = entrada
    _salvar_gravacoes_config(base_dir, projeto_id, dados)

    pasta = _gravacoes_dir(base_dir, projeto_id)
    caminho = pasta / f"seg_{indice_fala:04d}_{take_id}.wav"
    if caminho.exists():
        caminho.unlink()
    caminho_realce = pasta / f"seg_{indice_fala:04d}_{take_id}_enhanced.wav"
    if caminho_realce.exists():
        caminho_realce.unlink()
    caminho_raw = pasta / f"seg_{indice_fala:04d}_{take_id}_raw.wav"
    if caminho_raw.exists():
        caminho_raw.unlink()


def caminho_take(base_dir: str, projeto_id: str, indice_fala: int, take_id: str) -> Path:
    take_id_seguro = "".join(c for c in take_id if c.isalnum())
    caminho = _gravacoes_dir(base_dir, projeto_id) / f"seg_{indice_fala:04d}_{take_id_seguro}.wav"
    if not caminho.exists():
        raise NarracaoError("Esse take não foi encontrado.")
    return caminho


def _caminho_take_raw(base_dir: str, projeto_id: str, indice_fala: int, take_id_seguro: str) -> Path:
    """Cópia intacta do take ANTES de qualquer corte — só é criada na
    primeira vez que `recortar_take()` é chamado pra esse take, e serve
    pra `desfazer_recorte_take()` conseguir voltar ao estado original
    (sem perda de qualidade acumulada de cortes em cima de cortes)."""
    return _gravacoes_dir(base_dir, projeto_id) / f"seg_{indice_fala:04d}_{take_id_seguro}_raw.wav"


def recortar_take(
    base_dir: str, projeto_id: str, indice_fala: int, take_id: str,
    inicio_segundos: float, fim_segundos: float,
) -> Dict[str, Any]:
    """Corta o take pro trecho [`inicio_segundos`, `fim_segundos`] —
    útil pra tirar silêncio/ruído do começo ou do fim de uma gravação
    (comum: o clique do botão de gravar, ou uma pausa antes de começar
    a falar). SEMPRE corta a partir do áudio ORIGINAL intacto (guardado
    à parte na primeira vez que corta esse take), nunca de um corte
    anterior — então cortar de novo com limites diferentes não perde
    qualidade nem "esquece" o que já foi cortado fora antes; dá pra
    ajustar o corte quantas vezes quiser.

    Se o take já tinha um realce gerado, ele é descartado (foi gerado
    em cima do áudio de ANTES do corte, ficaria com a duração errada)
    — gere de novo depois de ajustar o corte, se quiser.
    """
    if fim_segundos <= inicio_segundos:
        raise NarracaoError("O fim do corte precisa vir depois do início.")
    if inicio_segundos < 0:
        raise NarracaoError("O início do corte não pode ser negativo.")

    take_id_seguro = "".join(c for c in take_id if c.isalnum())
    caminho_atual = caminho_take(base_dir, projeto_id, indice_fala, take_id)
    caminho_raw = _caminho_take_raw(base_dir, projeto_id, indice_fala, take_id_seguro)
    if not caminho_raw.exists():
        shutil.copy(str(caminho_atual), str(caminho_raw))

    duracao_original = _duracao_audio(caminho_raw)
    if duracao_original is not None and inicio_segundos >= duracao_original:
        raise NarracaoError(
            f"O início do corte ({inicio_segundos:.1f}s) precisa ser menor que a duração da "
            f"gravação original ({duracao_original:.1f}s)."
        )

    destino_tmp = caminho_atual.with_name(caminho_atual.stem + ".tmp.wav")
    resultado = subprocess.run(
        ["ffmpeg", "-y", "-i", str(caminho_raw), "-ss", f"{inicio_segundos:.3f}",
         "-to", f"{fim_segundos:.3f}", "-ar", "24000", "-ac", "1", str(destino_tmp)],
        capture_output=True, timeout=60,
    )
    if resultado.returncode != 0 or not destino_tmp.exists():
        raise NarracaoError(
            f"ffmpeg não conseguiu cortar a gravação: {resultado.stderr.decode(errors='replace')[-300:]}"
        )
    arquivo_seguro.trocar(str(destino_tmp), str(caminho_atual))

    nova_duracao = _duracao_audio(caminho_atual)
    _invalidar_realce_apos_edicao(base_dir, projeto_id, indice_fala, take_id_seguro, nova_duracao, recortado=True)

    return {
        "indice": indice_fala, "takeId": take_id_seguro,
        "duracaoSegundos": nova_duracao, "recortado": True,
        "duracaoOriginalSegundos": duracao_original,
    }


def desfazer_recorte_take(base_dir: str, projeto_id: str, indice_fala: int, take_id: str) -> Dict[str, Any]:
    """Restaura o take pro áudio ORIGINAL, antes de qualquer corte."""
    take_id_seguro = "".join(c for c in take_id if c.isalnum())
    caminho_raw = _caminho_take_raw(base_dir, projeto_id, indice_fala, take_id_seguro)
    if not caminho_raw.exists():
        raise NarracaoError("Esse take não tem nenhum corte aplicado pra desfazer.")

    caminho_atual = caminho_take(base_dir, projeto_id, indice_fala, take_id)
    shutil.copy(str(caminho_raw), str(caminho_atual))
    caminho_raw.unlink()

    nova_duracao = _duracao_audio(caminho_atual)
    _invalidar_realce_apos_edicao(base_dir, projeto_id, indice_fala, take_id_seguro, nova_duracao, recortado=False)

    return {"indice": indice_fala, "takeId": take_id_seguro, "duracaoSegundos": nova_duracao, "recortado": False}


def _invalidar_realce_apos_edicao(
    base_dir: str, projeto_id: str, indice_fala: int, take_id_seguro: str,
    nova_duracao: Optional[float], recortado: bool,
) -> None:
    """Depois de cortar (ou desfazer o corte de) um take, o realce
    gerado anteriormente (se houver) não bate mais com o áudio atual --
    descarta o arquivo e desliga o uso dele, em vez de deixar o usuário
    ouvindo sem querer um realce desatualizado."""
    pasta = _gravacoes_dir(base_dir, projeto_id)
    caminho_realce = pasta / f"seg_{indice_fala:04d}_{take_id_seguro}_enhanced.wav"
    if caminho_realce.exists():
        caminho_realce.unlink()

    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave)
    if entrada:
        for take in entrada.get("takes", []):
            if take.get("id") == take_id_seguro:
                take["duracaoSegundos"] = nova_duracao
                take["enhancedGerado"] = False
                take["usarEnhance"] = False
                take["recortado"] = recortado
        dados[chave] = entrada
        _salvar_gravacoes_config(base_dir, projeto_id, dados)


def caminho_take_realce(base_dir: str, projeto_id: str, indice_fala: int, take_id: str) -> Path:
    take_id_seguro = "".join(c for c in take_id if c.isalnum())
    caminho = _gravacoes_dir(base_dir, projeto_id) / f"seg_{indice_fala:04d}_{take_id_seguro}_enhanced.wav"
    if not caminho.exists():
        raise NarracaoError("O realce desse take ainda não foi gerado.")
    return caminho


def gerar_realce_de_take(
    base_dir: str, projeto_id: str, indice_fala: int, take_id: str, marcar_como_usar: bool = True,
) -> Dict[str, Any]:
    """Gera a versão com REALCE (audio enhance — redução de ruído,
    equalização de clareza, compressão e normalização) de um take
    específico, salva como um arquivo à PARTE (o original nunca é
    sobrescrito). Por padrão já liga o uso dela automaticamente (fica
    marcada como a versão usada no vídeo final); passe
    `marcar_como_usar=False` se quiser só gerar e comparar antes de
    decidir, sem trocar o que está em uso.
    """
    from tts.voice_generator import VoiceGeneratorError, aplicar_realce_de_voz

    origem = caminho_take(base_dir, projeto_id, indice_fala, take_id)
    take_id_seguro = "".join(c for c in take_id if c.isalnum())
    destino = _gravacoes_dir(base_dir, projeto_id) / f"seg_{indice_fala:04d}_{take_id_seguro}_enhanced.wav"

    try:
        aplicar_realce_de_voz(str(origem), str(destino))
    except VoiceGeneratorError as exc:
        raise NarracaoError(f"Falha ao gerar o realce: {exc}") from exc

    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave)
    if entrada:
        for take in entrada.get("takes", []):
            if take.get("id") == take_id_seguro:
                take["enhancedGerado"] = True
                if marcar_como_usar:
                    take["usarEnhance"] = True
        dados[chave] = entrada
        _salvar_gravacoes_config(base_dir, projeto_id, dados)

    return {"indice": indice_fala, "takeId": take_id_seguro, "enhancedGerado": True, "usarEnhance": marcar_como_usar}


def usar_realce_de_take(base_dir: str, projeto_id: str, indice_fala: int, take_id: str, usar_enhance: bool) -> Dict[str, Any]:
    """Escolhe, PRA ESSE TAKE, se a geração final deve usar a versão com
    realce ou a gravação original — só faz efeito de verdade quando
    esse take estiver ativo (selecionado) na fala."""
    take_id_seguro = "".join(c for c in take_id if c.isalnum())
    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    chave = str(indice_fala)
    entrada = dados.get(chave)
    if not entrada:
        raise NarracaoError("Essa fala ainda não tem gravações.")
    take = next((t for t in entrada.get("takes", []) if t.get("id") == take_id_seguro), None)
    if not take:
        raise NarracaoError("Esse take não existe pra essa fala.")
    if usar_enhance and not take.get("enhancedGerado"):
        raise NarracaoError("Gere o realce desse take antes de ativar o uso dele.")
    take["usarEnhance"] = bool(usar_enhance)
    dados[chave] = entrada
    _salvar_gravacoes_config(base_dir, projeto_id, dados)
    return take


def caminho_take_ativo(base_dir: str, projeto_id: str, indice_fala: int) -> Path:
    dados = _carregar_gravacoes_config(base_dir, projeto_id)
    entrada = dados.get(str(indice_fala))
    take_id = entrada.get("takeAtivo") if entrada else None
    if not take_id:
        raise NarracaoError("Essa fala não tem uma gravação ativa.")

    take = next((t for t in entrada.get("takes", []) if t.get("id") == take_id), None)
    if take and take.get("usarEnhance") and take.get("enhancedGerado"):
        try:
            return caminho_take_realce(base_dir, projeto_id, indice_fala, take_id)
        except NarracaoError:
            pass  # arquivo do realce sumiu por fora -- cai pro original em vez de quebrar
    return caminho_take(base_dir, projeto_id, indice_fala, take_id)


def gerar_audio_projeto(
    base_dir: str,
    projeto_id: str,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Gera o áudio final do projeto: uma narração por fala (com o
    motor/voz configurados), juntas com uma pausa de silêncio entre
    cada uma, com o volume final normalizado. Devolve a entrada salva
    em `geracoes.json` (id, arquivo, duração, quantidade de falas).

    `on_log`: função opcional chamada com uma linha de texto a cada
    passo importante — pra alimentar uma barra de progresso/log na UI
    (ver `_narracao_gerar_em_background` em app.py).
    """
    # import local pra este módulo não exigir as libs de TTS instaladas
    # só pra importar (o resto das funções acima não precisa delas).
    from tts.voice_generator import VoiceGeneratorError, gerar_audio_isolado

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    projeto = carregar_projeto(base_dir, projeto_id)
    roteiro = carregar_roteiro(base_dir, projeto_id)
    falas = roteiro["falas"]
    if not falas:
        raise NarracaoError("O roteiro não tem nenhuma fala — importe/cole o texto primeiro.")

    indices_com_texto = [i for i, f in enumerate(falas) if (f.get("texto") or "").strip()]
    if not indices_com_texto:
        raise NarracaoError("Nenhuma fala do roteiro tem texto pra narrar.")

    pasta = _pasta_projeto(base_dir, projeto_id)
    tmp_dir = pasta / "_tmp_gerar_audio"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    motor = projeto["motor"]
    kwargs_motor = _kwargs_motor(projeto)
    log(f"Motor escolhido: {motor} (voz: {projeto.get('voz') or '(padrão)'}).")

    gravacoes = _carregar_gravacoes_config(base_dir, projeto_id)

    # 🎭 multi voice: confere as tags ANTES de gastar tempo gerando
    multi = bool(projeto.get("multiVoz"))
    vozes_mv: Dict[str, Any] = {}
    if multi:
        import multivoz
        vozes_mv = multivoz.por_slug()
        desconhecidas = sorted({t for i in indices_com_texto for t in multivoz.dividir(falas[i]["texto"], vozes_mv)["desconhecidas"]})
        if desconhecidas:
            raise NarracaoError("Tag(s) sem voz cadastrada: " + ", ".join(f"[{t}]" for t in desconhecidas)
                                + " — cadastre em Gerador de voz → 🎭 Vozes com slug, ou corrija o roteiro.")
        log("🎭 Modo multi voice ligado: [slug] troca a voz (e continua até a próxima tag).")
    voz_atual: Optional[str] = None

    # ⚡ v84_103: as falas de TTS são geradas ANTES, todas de uma vez — num processo só (o modelo carrega 1 vez, não 1
    # por fala) ou em várias instâncias do motor ao mesmo tempo (tts_paralelo: ⚡ no Gerador de voz). O que falhar aqui
    # é gerado de novo no laço abaixo, fala por fala, como antes.
    pre: Dict[int, str] = {}
    if not multi:
        tts_idx = [i for i in indices_com_texto
                   if not ((gravacoes.get(str(i)) or {}).get("usar") and (gravacoes.get(str(i)) or {}).get("takeAtivo"))]
        if len(tts_idx) > 1:
            try:
                import tts_paralelo
                from tts.voice_generator import gerar_audio_isolado_paralelo
                n_inst, por_que = tts_paralelo.escolher(motor, tts_paralelo.modo_salvo(), kwargs_motor.get("use_gpu") is False,
                                                        sum(len(falas[i]["texto"]) for i in tts_idx))
                n_inst = min(n_inst, len(tts_idx))
                log(f"⚡ {por_que} — gerando as {len(tts_idx)} falas" + (" ao mesmo tempo." if n_inst > 1 else " num processo só (o modelo carrega uma vez)."))
                if n_inst > 1:
                    log(tts_paralelo.AVISO)
                itens_pre = [(motor, limpar_texto_para_tts(falas[i]["texto"].strip(), motor=motor), str(tmp_dir / f"fala_{i:04d}.wav"), kwargs_motor)
                             for i in tts_idx]
                cont = {"n": 0}

                def _prog(k, erro, inst):
                    cont["n"] += 1
                    log(f"[{cont['n']}/{len(itens_pre)}] fala {tts_idx[k] + 1} " + (f"⚠ {str(erro)[:120]}" if erro else "pronta")
                        + (f" (instância {inst})" if n_inst > 1 else ""))
                erros_pre = gerar_audio_isolado_paralelo(itens_pre, n_inst, on_progresso=_prog)
                pre = {tts_idx[k]: itens_pre[k][2] for k in range(len(itens_pre)) if k not in erros_pre and os.path.exists(itens_pre[k][2])}
            except Exception as exc:  # noqa: BLE001 — o caminho de sempre (uma por uma) continua valendo
                log(f"(⚡ não deu pra gerar tudo de uma vez — seguindo fala por fala: {exc})")

    try:
        caminhos_segmentos = []
        for pos, i in enumerate(indices_com_texto, start=1):
            texto_original = falas[i]["texto"].strip()
            saida = tmp_dir / f"fala_{i:04d}.wav"

            entrada_gravacao = gravacoes.get(str(i)) or {}
            take_ativo = entrada_gravacao.get("takeAtivo")
            if entrada_gravacao.get("usar") and take_ativo:
                log(f"[{pos}/{len(indices_com_texto)}] Usando gravação própria: \"{texto_original[:60]}\"")
                try:
                    origem = caminho_take_ativo(base_dir, projeto_id, i)
                except NarracaoError as exc:
                    raise NarracaoError(f"Falha na fala {i + 1} (gravação própria): {exc}") from exc

                if projeto.get("cortarSilencioGravacoes", True):
                    from tts.voice_generator import cortar_silencio_pontas
                    origem_cortada = tmp_dir / f"fala_{i:04d}_sem_silencio.wav"
                    cortar_silencio_pontas(str(origem), str(origem_cortada))
                    origem = origem_cortada

                # reconverte pro formato certo (mono, taxa de amostragem
                # consistente) antes de concatenar com os segmentos
                # gerados por TTS -- já sai correto desde salvar_gravacao(),
                # mas isso garante consistência mesmo depois do corte
                # de silêncio acima (que não força sample rate/canais).
                resultado = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(origem), "-ar", "24000", "-ac", "1", str(saida)],
                    capture_output=True, timeout=60,
                )
                if resultado.returncode != 0 or not saida.exists():
                    raise NarracaoError(
                        f"Falha na fala {i + 1}: ffmpeg não conseguiu preparar a gravação própria."
                    )
            elif multi:
                import multivoz
                partes = multivoz.dividir(texto_original, vozes_mv, voz_inicial=voz_atual)
                voz_atual = partes["ultima"]
                sub = []
                for k, parte in enumerate(partes["falas"]):
                    if parte["slug"]:
                        m_, kw_ = multivoz.kwargs_da_voz(vozes_mv[parte["slug"]])
                        quem = vozes_mv[parte["slug"]]["nome"]
                    else:
                        m_, kw_, quem = motor, kwargs_motor, "voz do projeto"
                    log(f"[{pos}/{len(indices_com_texto)}] {quem} ({m_}): \"{parte['texto'][:60]}\"")
                    bruto = tmp_dir / f"fala_{i:04d}_{k:02d}_bruto.wav"
                    try:
                        gerar_audio_isolado(m_, limpar_texto_para_tts(parte["texto"], motor=m_), str(bruto), **kw_)
                    except VoiceGeneratorError as exc:
                        raise NarracaoError(f"Falha na fala {i + 1} ({quem}): {exc}") from exc
                    norm = tmp_dir / f"fala_{i:04d}_{k:02d}.wav"
                    subprocess.run(["ffmpeg", "-y", "-i", str(bruto), "-ar", "24000", "-ac", "1", str(norm)], capture_output=True, timeout=120)
                    sub.append(str(norm))
                if not sub:
                    continue
                if len(sub) == 1:
                    shutil.copy(sub[0], saida)
                else:
                    multivoz.concatenar(sub, str(saida), [0.0] + [0.3] * (len(sub) - 1), str(tmp_dir))
            elif i in pre:
                pass  # ⚡ já gerada lá em cima
            else:
                texto_limpo = limpar_texto_para_tts(texto_original, motor=motor)
                log(f"[{pos}/{len(indices_com_texto)}] Gerando com {motor}: \"{texto_original[:60]}\"")
                try:
                    gerar_audio_isolado(motor, texto_limpo, str(saida), **kwargs_motor)
                except VoiceGeneratorError as exc:
                    raise NarracaoError(f"Falha na fala {i + 1}: {exc}") from exc
            caminhos_segmentos.append(saida)

        pausa_segundos = float(projeto.get("pausaSegundos", 0.6) or 0.0)
        log(f"Juntando {len(caminhos_segmentos)} fala(s) num único áudio "
            f"(pausa de {pausa_segundos:.2f}s entre cada uma)...")

        entradas: List[str] = []
        if pausa_segundos > 0:
            silencio_wav = tmp_dir / "silencio.wav"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(pausa_segundos), str(silencio_wav),
            ], capture_output=True)
            for caminho in caminhos_segmentos:
                entradas.append(str(caminho))
                entradas.append(str(silencio_wav))
            entradas = entradas[:-1]  # sem pausa depois da última fala
        else:
            entradas = [str(c) for c in caminhos_segmentos]

        lista_concat = tmp_dir / "lista_concat.txt"
        with open(lista_concat, "w", encoding="utf-8") as f:
            for caminho in entradas:
                caminho_escapado = str(Path(caminho).resolve()).replace("'", "'\\''")
                f.write(f"file '{caminho_escapado}'\n")

        audio_bruto = tmp_dir / "audio_bruto.wav"
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista_concat),
             "-ar", "44100", "-ac", "1", str(audio_bruto)],
            capture_output=True,
        )
        if resultado.returncode != 0 or not audio_bruto.exists():
            raise NarracaoError(
                f"ffmpeg falhou ao juntar as falas: {resultado.stderr.decode(errors='replace')[-400:]}"
            )

        log("Normalizando o volume final...")
        audio_normalizado = tmp_dir / "audio_normalizado.wav"
        normalizar_volume_wav(audio_bruto, audio_normalizado)
        if not audio_normalizado.exists():
            audio_normalizado = audio_bruto  # normalização falhou -- usa sem normalizar em vez de travar tudo

        geracao_id = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        arquivo_final = pasta / "geracoes" / f"{geracao_id}.mp3"
        arquivo_final.parent.mkdir(parents=True, exist_ok=True)
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_normalizado), "-c:a", "libmp3lame", "-b:a", "192k",
             str(arquivo_final)],
            capture_output=True,
        )
        if resultado.returncode != 0 or not arquivo_final.exists():
            raise NarracaoError(
                f"ffmpeg não conseguiu exportar o .mp3 final: {resultado.stderr.decode(errors='replace')[-400:]}"
            )

        duracao = None
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(arquivo_final)],
                capture_output=True, text=True, timeout=15,
            )
            duracao = round(float(r.stdout.strip()), 1)
        except Exception:  # noqa: BLE001
            pass

        entrada_geracao = {
            "id": geracao_id, "criadoEm": time.time(), "arquivo": f"{geracao_id}.mp3",
            "duracaoSegundos": duracao, "quantidadeFalas": len(caminhos_segmentos), "motor": motor,
        }
        geracoes = carregar_geracoes(base_dir, projeto_id)
        geracoes.insert(0, entrada_geracao)
        _salvar_geracoes(base_dir, projeto_id, geracoes)
        log(f"Pronto! Áudio final gerado ({duracao}s, {len(caminhos_segmentos)} fala(s)).")
        return entrada_geracao
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
