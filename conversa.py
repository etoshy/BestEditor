"""
conversa.py
=============

"Simular Conversa" — like o Roteiro para Áudio (narracoes.py), só que
cada FALA pode usar um motor/voz DIFERENTE da anterior — pensado pra
simular um diálogo entre duas ou mais "pessoas" (cada uma com sua
própria voz), ao contrário do Roteiro para Áudio, onde o motor/voz é
uma configuração ÚNICA pro projeto inteiro.

Cada fala é gerada e guardada separadamente (dá pra baixar uma por
uma), e opcionalmente todas juntas viram um único áudio combinado
(com uma pausa configurável entre cada fala, igual ao Roteiro para
Áudio faz).
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from narracoes import limpar_texto_para_tts, normalizar_volume_wav

MOTORES_VALIDOS = {"piper", "xtts", "chatterbox", "chatterbox_turbo", "kokoro"}


class ConversaError(Exception):
    """Erro genérico — conversa/fala não encontrada, motor inválido,
    falha do próprio motor de voz, etc."""


# ============================================================ #
# Armazenamento — uma pasta por conversa (mesmo espírito de
# narracoes.py, só numa subpasta própria pra não misturar os dois)
# ============================================================ #

def conversas_dir(base_dir: str) -> Path:
    d = Path(base_dir) / "conversas"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pasta_conversa(base_dir: str, conversa_id: str) -> Path:
    p = conversas_dir(base_dir) / conversa_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _conversa_path(base_dir: str, conversa_id: str) -> Path:
    return _pasta_conversa(base_dir, conversa_id) / "conversa.json"


def conversa_existe(base_dir: str, conversa_id: str) -> bool:
    return (conversas_dir(base_dir) / conversa_id / "conversa.json").exists()


def _gerar_id() -> str:
    return f"{int(time.time())}_{uuid.uuid4().hex[:8]}"


def _salvar(base_dir: str, conversa_id: str, dados: Dict[str, Any]) -> None:
    caminho = _conversa_path(base_dir, conversa_id)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def criar_conversa(base_dir: str, nome: str = "") -> Dict[str, Any]:
    nome = (nome or "").strip() or time.strftime("Conversa %d/%m/%Y %H:%M")
    conversa_id = _gerar_id()
    dados = {"nome": nome, "criadoEm": time.time(), "falas": [], "pausaSegundos": 0.6}
    _salvar(base_dir, conversa_id, dados)
    return {"conversaId": conversa_id, **dados}


def carregar_conversa(base_dir: str, conversa_id: str) -> Dict[str, Any]:
    caminho = conversas_dir(base_dir) / conversa_id / "conversa.json"
    if not caminho.exists():
        raise ConversaError(f"Conversa {conversa_id!r} não encontrada.")
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    dados.setdefault("pausaSegundos", 0.6)
    dados.setdefault("falas", [])
    return {**dados, "conversaId": conversa_id}


def listar_conversas(base_dir: str) -> List[Dict[str, Any]]:
    raiz = conversas_dir(base_dir)
    conversas = []
    for pasta in raiz.iterdir():
        if not pasta.is_dir() or not (pasta / "conversa.json").exists():
            continue
        try:
            conversas.append(carregar_conversa(base_dir, pasta.name))
        except ConversaError:
            continue
    conversas.sort(key=lambda c: c.get("criadoEm", 0), reverse=True)
    return conversas


def excluir_conversa(base_dir: str, conversa_id: str) -> None:
    pasta = conversas_dir(base_dir) / conversa_id
    if pasta.exists():
        import shutil
        shutil.rmtree(pasta)


def renomear_conversa(base_dir: str, conversa_id: str, nome: str) -> Dict[str, Any]:
    conversa = carregar_conversa(base_dir, conversa_id)
    nome = (nome or "").strip()
    if nome:
        conversa["nome"] = nome
    dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
    _salvar(base_dir, conversa_id, dados_salvos)
    return conversa


def salvar_pausa(base_dir: str, conversa_id: str, pausa_segundos: float) -> Dict[str, Any]:
    conversa = carregar_conversa(base_dir, conversa_id)
    try:
        conversa["pausaSegundos"] = max(0.0, min(float(pausa_segundos), 10.0))
    except (TypeError, ValueError):
        pass
    dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
    _salvar(base_dir, conversa_id, dados_salvos)
    return conversa


# ============================================================ #
# Falas — cada uma com motor/voz PRÓPRIOS
# ============================================================ #

def _nova_fala(texto: str, motor: str, voz: str, velocidade: float, idioma: str) -> Dict[str, Any]:
    return {
        "id": f"fala_{uuid.uuid4().hex[:8]}",
        "texto": texto,
        "motor": motor,
        "voz": voz,
        "velocidade": velocidade,
        "idioma": idioma,
        "status": "pendente",  # pendente | gerando | pronto | erro
        "erro": None,
        "duracaoSegundos": None,
    }


def adicionar_fala(
    base_dir: str, conversa_id: str, texto: str, motor: str,
    voz: str = "", velocidade: float = 1.0, idioma: str = "",
) -> Dict[str, Any]:
    texto = (texto or "").strip()
    if not texto:
        raise ConversaError("Escreva algum texto pra essa fala.")
    if motor not in MOTORES_VALIDOS:
        raise ConversaError(f"Motor {motor!r} inválido — use um de {sorted(MOTORES_VALIDOS)}.")

    conversa = carregar_conversa(base_dir, conversa_id)
    fala = _nova_fala(texto, motor, (voz or "").strip(), velocidade, (idioma or "").strip())
    conversa["falas"].append(fala)
    dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
    _salvar(base_dir, conversa_id, dados_salvos)
    return fala


def _indice_fala(conversa: Dict[str, Any], fala_id: str) -> int:
    for i, f in enumerate(conversa["falas"]):
        if f["id"] == fala_id:
            return i
    raise ConversaError(f"Fala {fala_id!r} não encontrada nessa conversa.")


def editar_fala(
    base_dir: str, conversa_id: str, fala_id: str,
    texto: Optional[str] = None, motor: Optional[str] = None,
    voz: Optional[str] = None, velocidade: Optional[float] = None, idioma: Optional[str] = None,
) -> Dict[str, Any]:
    conversa = carregar_conversa(base_dir, conversa_id)
    idx = _indice_fala(conversa, fala_id)
    fala = conversa["falas"][idx]

    if texto is not None and texto.strip():
        fala["texto"] = texto.strip()
    if motor is not None:
        if motor not in MOTORES_VALIDOS:
            raise ConversaError(f"Motor {motor!r} inválido — use um de {sorted(MOTORES_VALIDOS)}.")
        fala["motor"] = motor
    if voz is not None:
        fala["voz"] = voz.strip()
    if velocidade is not None:
        try:
            fala["velocidade"] = max(0.5, min(float(velocidade), 2.0))
        except (TypeError, ValueError):
            pass
    if idioma is not None:
        fala["idioma"] = idioma.strip()

    # qualquer edição invalida o áudio já gerado (pode não bater mais
    # com o texto/voz novos) -- evita "esquecer" de gerar de novo e
    # acabar usando um áudio desatualizado no combinado.
    fala["status"] = "pendente"
    fala["erro"] = None
    fala["duracaoSegundos"] = None
    caminho_audio = _pasta_conversa(base_dir, conversa_id) / "falas" / f"{fala_id}.wav"
    if caminho_audio.exists():
        caminho_audio.unlink()

    dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
    _salvar(base_dir, conversa_id, dados_salvos)
    return fala


def remover_fala(base_dir: str, conversa_id: str, fala_id: str) -> None:
    conversa = carregar_conversa(base_dir, conversa_id)
    idx = _indice_fala(conversa, fala_id)
    conversa["falas"].pop(idx)
    dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
    _salvar(base_dir, conversa_id, dados_salvos)

    caminho_audio = _pasta_conversa(base_dir, conversa_id) / "falas" / f"{fala_id}.wav"
    if caminho_audio.exists():
        caminho_audio.unlink()


def mover_fala(base_dir: str, conversa_id: str, fala_id: str, direcao: str) -> Dict[str, Any]:
    """`direcao`: "cima" ou "baixo" -- troca essa fala de posição com a
    vizinha nessa direção (não faz nada, sem erro, se já estiver na
    ponta correspondente)."""
    if direcao not in ("cima", "baixo"):
        raise ConversaError('direcao precisa ser "cima" ou "baixo".')
    conversa = carregar_conversa(base_dir, conversa_id)
    idx = _indice_fala(conversa, fala_id)
    novo_idx = idx - 1 if direcao == "cima" else idx + 1
    if 0 <= novo_idx < len(conversa["falas"]):
        conversa["falas"][idx], conversa["falas"][novo_idx] = conversa["falas"][novo_idx], conversa["falas"][idx]
        dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
        _salvar(base_dir, conversa_id, dados_salvos)
    return conversa


def caminho_audio_fala(base_dir: str, conversa_id: str, fala_id: str) -> Path:
    caminho = _pasta_conversa(base_dir, conversa_id) / "falas" / f"{fala_id}.wav"
    if not caminho.exists():
        raise ConversaError("Essa fala ainda não tem áudio gerado.")
    return caminho


def _kwargs_motor_fala(fala: Dict[str, Any]) -> Dict[str, Any]:
    """Monta os kwargs certos pra `gerar_audio()` a partir de UMA fala
    (não do projeto inteiro, como em narracoes.py — aqui cada fala tem
    seu próprio motor/voz).
    """
    motor = fala["motor"]
    velocidade = fala.get("velocidade", 1.0)
    voz = (fala.get("voz") or "").strip()
    idioma = (fala.get("idioma") or "").strip() or None

    if motor == "piper":
        return {"nome_voz": voz or "pt_BR-faber-medium", "velocidade": velocidade}

    if motor == "xtts":
        kwargs: Dict[str, Any] = {"idioma": idioma or "pt"}
        if voz:
            # se o nome bater com um perfil salvo, usa clonagem; senão
            # trata como o nome de uma voz PRONTA do modelo -- um campo
            # só cobre os dois casos mais comuns sem precisar de dois
            # campos separados na tela.
            from tts.voice_generator import listar_perfis_de_voz
            if voz in listar_perfis_de_voz():
                kwargs["voice_profile"] = voz
            else:
                kwargs["speaker"] = voz
        return kwargs

    if motor == "chatterbox":
        kwargs = {"idioma": idioma or "pt", "exaggeration": 0.5, "cfg_weight": 0.5}
        if voz:
            # diferente do XTTS, o Chatterbox não tem o conceito de
            # "voz pronta com nome" -- só clonagem (voice_profile) ou a
            # voz neutra padrão. Se o nome não bater com nenhum perfil
            # salvo, ignora (cai pra voz neutra) em vez de dar erro.
            from tts.voice_generator import listar_perfis_de_voz
            if voz in listar_perfis_de_voz():
                kwargs["voice_profile"] = voz
        return kwargs

    if motor == "chatterbox_turbo":
        kwargs = {}  # só inglês -- sem idioma/exaggeration/cfg_weight
        if voz:
            from tts.voice_generator import listar_perfis_de_voz
            if voz in listar_perfis_de_voz():
                kwargs["voice_profile"] = voz
        return kwargs

    # kokoro
    return {"voz": voz or "pf_dora", "velocidade": velocidade, "idioma": idioma}


def gerar_audio_fala(base_dir: str, conversa_id: str, fala_id: str) -> Dict[str, Any]:
    """Gera (ou regenera) o áudio de UMA fala específica, com o motor/
    voz dela — as outras falas da conversa não são tocadas."""
    from tts.voice_generator import VoiceGeneratorError, gerar_audio_isolado

    conversa = carregar_conversa(base_dir, conversa_id)
    idx = _indice_fala(conversa, fala_id)
    fala = conversa["falas"][idx]

    pasta_falas = _pasta_conversa(base_dir, conversa_id) / "falas"
    pasta_falas.mkdir(parents=True, exist_ok=True)
    destino = pasta_falas / f"{fala_id}.wav"

    texto_limpo = limpar_texto_para_tts(fala["texto"], preservar_tags_chatterbox_turbo=(fala["motor"] == "chatterbox_turbo"))
    kwargs = _kwargs_motor_fala(fala)
    try:
        gerar_audio_isolado(fala["motor"], texto_limpo, str(destino), **kwargs)
    except VoiceGeneratorError as exc:
        fala["status"] = "erro"
        fala["erro"] = str(exc)
        dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
        _salvar(base_dir, conversa_id, dados_salvos)
        raise ConversaError(str(exc)) from exc

    duracao = _duracao_audio(destino)
    fala["status"] = "pronto"
    fala["erro"] = None
    fala["duracaoSegundos"] = duracao
    dados_salvos = {k: v for k, v in conversa.items() if k != "conversaId"}
    _salvar(base_dir, conversa_id, dados_salvos)
    return fala


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


def gerar_audio_completo(base_dir: str, conversa_id: str) -> Dict[str, Any]:
    """Combina TODAS as falas que já têm áudio gerado (na ordem da
    conversa) num único arquivo — mesma técnica de concatenação +
    normalização de volume que o Roteiro para Áudio usa. Falas sem
    áudio gerado ainda são simplesmente puladas (não travam o
    combinado inteiro por causa de uma fala pendente).
    """
    conversa = carregar_conversa(base_dir, conversa_id)
    pasta = _pasta_conversa(base_dir, conversa_id)
    pasta_falas = pasta / "falas"

    falas_prontas = [f for f in conversa["falas"] if f["status"] == "pronto"]
    caminhos = [pasta_falas / f"{f['id']}.wav" for f in falas_prontas]
    caminhos = [c for c in caminhos if c.exists()]
    if not caminhos:
        raise ConversaError("Nenhuma fala tem áudio gerado ainda — gere pelo menos uma antes de combinar.")

    pausa_segundos = float(conversa.get("pausaSegundos", 0.6) or 0.0)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        entradas: List[str] = []
        if pausa_segundos > 0:
            silencio_wav = tmp_dir / "silencio.wav"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(pausa_segundos), str(silencio_wav),
            ], capture_output=True)
            for caminho in caminhos:
                entradas.append(str(caminho))
                entradas.append(str(silencio_wav))
            entradas = entradas[:-1]
        else:
            entradas = [str(c) for c in caminhos]

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
            raise ConversaError(
                f"ffmpeg falhou ao juntar as falas: {resultado.stderr.decode(errors='replace')[-400:]}"
            )

        audio_normalizado = tmp_dir / "audio_normalizado.wav"
        normalizar_volume_wav(audio_bruto, audio_normalizado)
        if not audio_normalizado.exists():
            audio_normalizado = audio_bruto

        arquivo_final = pasta / "completo.mp3"
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_normalizado), "-c:a", "libmp3lame", "-b:a", "192k", str(arquivo_final)],
            capture_output=True,
        )
        if resultado.returncode != 0 or not arquivo_final.exists():
            raise ConversaError(
                f"ffmpeg não conseguiu exportar o .mp3 final: {resultado.stderr.decode(errors='replace')[-400:]}"
            )

    duracao = _duracao_audio(arquivo_final)
    return {"arquivo": str(arquivo_final), "duracaoSegundos": duracao, "quantidadeFalas": len(caminhos)}


def caminho_audio_completo(base_dir: str, conversa_id: str) -> Path:
    caminho = _pasta_conversa(base_dir, conversa_id) / "completo.mp3"
    if not caminho.exists():
        raise ConversaError("Ainda não foi gerado um áudio combinado pra essa conversa.")
    return caminho
