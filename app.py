"""
app.py
=======

Site Flask que junta as quatro peças do pipeline:

  1) Upload de áudio -> transcrição via Whisper (whisper_transcribe.py)
  2) Transcrição -> prompt pronto pra colar em outra IA (prompt_builder.py)
  3) Você cola a resposta (JSON) da IA de volta no site
  4) JSON validado -> busca/baixa vídeos de cada trecho e monta o vídeo
     final sincronizado com o áudio (video_assembler.py, que usa o
     toolkit em toolkit/ pra falar com Pexels/Pixabay/Magnific/Mixkit/
     VistaCreate)

Cada "job" (uma narração processada) vira uma pasta em jobs/<job_id>/
com tudo daquele processamento: áudio, transcrição, prompt gerado, JSON
colado, e o vídeo final.

Rodar
-----
    pip install -r requirements.txt
    python app.py
    # abre http://localhost:5050 (porta 5050 de propósito — 5000 é a
    # porta padrão do servidor local do Anime Pexels Local, então usar
    # a mesma aqui causaria conflito se os dois rodarem ao mesmo tempo
    # na mesma máquina). Pra mudar, defina a variável de ambiente PORT.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
from contextlib import nullcontext
import json
import re
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import shutil
import subprocess
import sys
import time
import threading
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

from prompt_builder import BROWSER_IMAGE_SEARCH_PROVIDERS, DEFAULT_PROVIDERS, PHOTO_SEARCH_PROVIDERS, PromptBuilderError, VideoSegment, build_animepexels_prompt, build_buscadores_search_terms_prompt, build_prompt, build_wikipedia_search_terms_prompt, parse_ai_response, parse_wikipedia_search_terms_response
import wikipedia_enrichment
import buscadores_enrichment
from webpage_capture import WebpageCaptureError, capturar_pagina
from webpage_animator import renderizar_clipe_pagina
from youtube_clipper import YoutubeClipperError, QUALIDADES as YT_QUALIDADES, QUALIDADE_PADRAO as YT_QUALIDADE_PADRAO, processar_pedido as yt_processar_pedido, buscar_videos_youtube, baixar_video as yt_baixar_video, cortar_trecho as yt_cortar_trecho, extrair_perfil_de_voz_do_youtube as yt_extrair_perfil_de_voz_do_youtube, extrair_links_canal
from video_assembler import (
    ClientFactory,
    UsedClipsTracker,
    VideoAssemblyError,
    assemble_video,
    burn_captions,
    prefetch_browser_images,
    fetch_segment_preview,
    fetch_segment_preview_lightweight,
    generate_thumbnail,
    generate_waveform_image,
    generate_word_captions_ass,
    insert_cutaways,
    photo_api_configuration_error,
    resolve_overlay_source,
    search_candidates,
    shift_timestamps_for_cutaways,
)
from video_assembler import _probe_duration as _probe_media_duration
from video_assembler import _PROVIDERS_WITH_URL_RESOLUTION as PROVIDERS_WITH_URL_RESOLUTION
from whisper_transcribe import TranscriptionError, get_audio_duration, transcribe_audio
import legendas as lg
from perf_log import PerfLog
from video_assembler import _ZOOM_DIRECTIONS_VALIDAS  # noqa: E402
from site_config import ALL_PROVIDERS, TRANSITION_LABELS, SiteConfigError, load_site_config, save_site_config, resolution_for_orientation
import narracoes as na
import conversa as cv
import redes_sociais
from redes_sociais.qualidade import checar_qualidade
from redes_sociais import RedesSociaisError
import transcrever_avulso as ta_avulso
from tts.voice_generator import (
    ENGINES as tts_ENGINES,
    KOKORO_MODEL_VARIANTS as tts_KOKORO_MODEL_VARIANTS,
    KOKORO_PRECISIONS as tts_KOKORO_PRECISIONS,
    DEFAULT_KOKORO_PRECISION as tts_DEFAULT_KOKORO_PRECISION,
    DEFAULT_KOKORO_VARIANT as tts_DEFAULT_KOKORO_VARIANT,
    KOKORO_VOZES as tts_KOKORO_VOZES,
    MAX_CLIPES_POR_PERFIL as tts_MAX_CLIPES_POR_PERFIL,
    PIPER_VOZES_SUGERIDAS as tts_PIPER_VOZES_SUGERIDAS,
    XTTS_CHECKPOINTS_CONHECIDOS as tts_XTTS_CHECKPOINTS_CONHECIDOS,
    XTTS_IDIOMAS as tts_XTTS_IDIOMAS,
    CHATTERBOX_IDIOMAS as tts_CHATTERBOX_IDIOMAS,
    VoiceGeneratorError,
    caminho_perfil_de_voz as tts_caminho_perfil_de_voz,
    diagnosticar_gpu as tts_diagnosticar_gpu,
    excluir_perfil_de_voz as tts_excluir_perfil_de_voz,
    gerar_audio as tts_gerar_audio,
    gerar_audio_isolado as tts_gerar_audio_isolado,
    gerar_audio_isolado_lote as tts_gerar_audio_isolado_lote,
    gpu_status as tts_gpu_status,
    listar_perfis_de_voz as tts_listar_perfis_de_voz,
    piper_download_voice_now as tts_piper_download_voice_now,
    piper_search_voices as tts_piper_search_voices,
    salvar_perfil_de_voz as tts_salvar_perfil_de_voz,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
JOBS_DIR = os.path.join(BASE_DIR, "jobs")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")

for d in (UPLOADS_DIR, JOBS_DIR, OUTPUTS_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)


def _avisar(titulo: str, msg: str = "", link: str = "", nivel: str = "ok", tipo: str = "", chave: str = "") -> None:
    """🔔 Notificação no sininho (v84_87) — nunca derruba quem chamou."""
    try:
        import notificacoes
        notificacoes.avisar(titulo, msg, link, nivel, tipo=tipo, chave=chave)
    except Exception:  # noqa: BLE001
        pass


def _thread_com_aviso(fn, estado_fn, nome: str, link: str, tipo: str = "", chave_ok: str = "", ao_fim=None) -> None:
    """Roda `fn` numa thread e, no fim, avisa no 🔔 conforme o dict de estado (status "erro" / campo "erro")."""
    def _w():
        try:
            fn()
        finally:
            if ao_fim is not None:
                try:
                    ao_fim()
                except Exception:  # noqa: BLE001
                    pass
            st = (estado_fn() if estado_fn else None) or {}
            erro = st.get("erro") or (("falhou" if st.get("status") == "erro" else None))
            if erro:
                _avisar(f"❌ {nome} — deu erro", str(erro)[:500], link, "erro", tipo)
            else:
                _avisar(f"✅ {nome} — pronto", "", link, "ok", tipo, chave=chave_ok)
    threading.Thread(target=_w, daemon=True).start()


def _nome_job(job_id: str) -> str:
    job = _JOBS.get(job_id) or {}
    return str(job.get("nome_projeto") or job.get("original_filename") or job_id)[:60]


def _avisar_fim(nome: str, erro: Any, link: str, tipo: str = "", msg_ok: str = "") -> None:
    """Aviso padrão de fim: ✅ pronto ou ❌ deu erro."""
    if erro:
        _avisar(f"❌ {nome} — deu erro", str(erro)[:500], link, "erro", tipo)
    else:
        _avisar(f"✅ {nome} — pronto", msg_ok, link, "ok", tipo)


@app.route("/favicon.ico")
def favicon():
    # Evita 404 no console quando o navegador procura automaticamente pelo favicon.
    return "", 204
# 200MB seria generoso pra UM áudio, mas o formulário de confirmar
# segmentos pode ter VÁRIOS vídeos enviados manualmente ao mesmo tempo
# (um por trecho, via "upload" no editor) — a soma de poucos vídeos em
# boa qualidade já estoura 200MB facilmente, causando
# "413 Request Entity Too Large" mesmo em uso normal. 2GB por padrão,
# configurável via variável de ambiente se precisar de mais/menos.
# Não limitar o tamanho TOTAL da requisição multipart no Flask.
# O editor pode enviar vários vídeos manuais na confirmação; o limite
# global fazia o Flask rejeitar a requisição antes de confirm_segments()
# conseguir processar os arquivos. Os limites específicos devem ser
# aplicados por arquivo/endpoint, não pela soma da requisição inteira.
app.config["MAX_CONTENT_LENGTH"] = None

# A partir do Flask 3.1 / Werkzeug 3.1, zerar MAX_CONTENT_LENGTH não
# basta: o parser de multipart passou a ter DOIS limites próprios,
# independentes desse, e com defaults baixos —
# MAX_FORM_MEMORY_SIZE (500KB) e MAX_FORM_PARTS (1000). O primeiro é
# o culpado do 413 mesmo em upload normal de vídeo: ele limita o
# buffer bruto de leitura do multipart (werkzeug.sansio.multipart.
# MultipartDecoder.receive_data), que é compartilhado por campos de
# texto E arquivos antes de o parser separar um do outro — ou seja,
# mesmo dados de arquivo (que depois vão pra disco, não pra memória)
# estouram esse limite quase de imediato. Zerando os dois aqui.
app.config["MAX_FORM_MEMORY_SIZE"] = None
app.config["MAX_FORM_PARTS"] = None

# O app.config acima só é lido automaticamente a partir do Flask 3.1
# (é quando o Flask passou a repassar MAX_FORM_MEMORY_SIZE/MAX_FORM_PARTS
# pro objeto request). Se o Flask instalado for mais antigo que isso mas
# o Werkzeug já for 3.1+ (os dois evoluem/instalam separadamente, não
# são a mesma lib), o app.config fica "surdo": o Werkzeug aplica os
# próprios defaults (500KB / 1000 campos) e ignora a config do Flask —
# foi exatamente o que apareceu no diagnóstico do 413 (app.config None,
# mas request.max_form_memory_size ainda 500000). Por isso setamos aqui
# também DIRETO na request, antes do formulário ser parseado — esses
# atributos existem no Request do Werkzeug independente da versão do
# Flask, então isso funciona mesmo quando o app.config é ignorado.
@app.before_request
def _relax_multipart_limits():
    # Versões diferentes de Flask/Werkzeug implementam isso de formas
    # diferentes: em algumas é um atributo comum (sempre sobrescrevível),
    # em outras é uma @property com getter E setter, e em pelo menos uma
    # variação (viu-se isso rodando Python 3.14) é uma @property só com
    # getter — tentar atribuir direto derruba a request inteira com
    # AttributeError. Como não dá pra saber de antemão qual é o caso,
    # tenta setar e ignora se não for permitido: quando não é permitido
    # setar por aqui, a implementação já deve estar lendo do app.config
    # (que setamos acima com os mesmos valores), então nada se perde.
    for attr in ("max_content_length", "max_form_memory_size", "max_form_parts"):
        try:
            setattr(request, attr, None)
        except AttributeError:
            pass


@app.errorhandler(413)
def _upload_too_large(error):
    # Diagnóstico: imprime no console os valores efetivos no momento do
    # erro (não só os configurados no app.py) e o Content-Length que o
    # navegador mandou, pra saber se é MAX_FORM_MEMORY_SIZE/MAX_FORM_PARTS
    # ainda ativos (config não aplicada / servidor não reiniciado /
    # versão de Werkzeug sem suporte a essas chaves), ou algo fora do
    # Flask (proxy, antivírus, extensão de navegador limitando o POST).
    import werkzeug
    try:
        werkzeug_version = werkzeug.__version__
    except AttributeError:
        # Werkzeug moderno não expõe mais __version__ no módulo; a forma
        # correta de obter a versão é via metadados do pacote instalado.
        import importlib.metadata
        try:
            werkzeug_version = importlib.metadata.version("werkzeug")
        except importlib.metadata.PackageNotFoundError:
            werkzeug_version = "desconhecida"
    print("=== 413 recebido em", request.path, "===")
    print("Werkzeug version:", werkzeug_version)
    print("Content-Length do request:", request.headers.get("Content-Length"))
    print("app.config MAX_CONTENT_LENGTH:", app.config.get("MAX_CONTENT_LENGTH"))
    print("app.config MAX_FORM_MEMORY_SIZE:", app.config.get("MAX_FORM_MEMORY_SIZE"))
    print("app.config MAX_FORM_PARTS:", app.config.get("MAX_FORM_PARTS"))
    print("request.max_content_length:", request.max_content_length)
    print("request.max_form_memory_size:", request.max_form_memory_size)
    print("request.max_form_parts:", request.max_form_parts)
    print("================================")
    return (
        "O servidor recusou o envio por tamanho. O editor não impõe mais "
        "limite global de tamanho na confirmação de segmentos. Verifique "
        "também o limite do servidor HTTP/proxy, se houver.",
        413,
    )

# Estado dos jobs em memória (processo único) — pra produção de verdade,
# troque por um banco de dados ou arquivo por job (já gravamos em disco
# também, então dá pra reconstruir isso a partir de jobs/<id>/state.json
# se preferir não depender só de memória).
_JOBS: Dict[str, Dict[str, Any]] = {}
_PERF_LOGS: Dict[str, PerfLog] = {}  # separado de _JOBS de propósito — PerfLog não é serializável em JSON,
# e _save_state() faz json.dump(_JOBS[job_id]) direto, então nunca pode entrar ali dentro.

_STATUS_EM_ANDAMENTO = ("transcrevendo", "buscando_termos_wikipedia", "buscando_termos_buscadores", "buscando_previas", "montando")


def _carregar_projetos_salvos() -> int:
    """Recarrega os projetos (jobs) gravados em jobs/<id>/state.json — sem
    isso a galeria/histórico ficava vazia toda vez que o servidor reiniciava,
    mesmo com tudo salvo em disco. O que estava rodando quando o servidor caiu
    volta num estado onde dá pra continuar (editor ou erro claro)."""
    if os.environ.get("NARRATION_SITE_NAO_CARREGAR_PROJETOS") == "1" or not os.path.isdir(JOBS_DIR):
        return 0
    carregados = 0
    for nome in os.listdir(JOBS_DIR):
        caminho = os.path.join(JOBS_DIR, nome, "state.json")
        if nome in _JOBS or not os.path.isfile(caminho):
            continue
        try:
            with open(caminho, encoding="utf-8") as f:
                job = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or job.get("job_id") != nome:
            continue
        status = job.get("status")
        if status in _STATUS_EM_ANDAMENTO:
            if status == "buscando_previas" and job.get("pending_segments") and any(
                    pv is None for pv in (job.get("segment_previews") or [None])):
                job["status"] = "previas_pausadas"  # ⏸ v84_108: o servidor caiu no meio — dá pra ▶ retomar de onde parou
                job["pausar_previas"] = False
            elif job.get("pending_segments"):
                job["status"] = "pronto_para_editar"
                if status == "montando":
                    job["assembly_error"] = "A montagem foi interrompida (o servidor reiniciou). Confira e confirme de novo."
                    job["assembly_error_segment_index"] = None
            elif job.get("prompt"):
                job["status"] = "aguardando_json"
            else:
                job["status"] = "erro_transcricao"
                job["error"] = "O servidor reiniciou no meio da transcrição — envie o áudio de novo."
        if not job.get("created_at"):
            try:
                job["created_at"] = os.path.getmtime(caminho)
            except OSError:
                job["created_at"] = 0
        _JOBS[nome] = job
        carregados += 1
    return carregados


_carregar_projetos_salvos()
if os.environ.get("NARRATION_SITE_NAO_CARREGAR_PROJETOS") != "1":  # nos testes, só quando uma página pedir
    threading.Timer(1.0, lambda: _gpu_cache()).start()

# Estado das capturas de página (feature "Capturar página" — print +
# mapa de blocos + galeria de qualquer site, ver webpage_capture.py) —
# mesmo espírito do _JOBS acima, só que separado por ser um fluxo
# totalmente independente do resto do pipeline de vídeo.
_CAPTURAS_PAGINA: Dict[str, Dict[str, Any]] = {}
CAPTURAS_DIR = os.path.join(OUTPUTS_DIR, "capturas_pagina")
os.makedirs(CAPTURAS_DIR, exist_ok=True)

# Estado dos jobs de "Cortar do YouTube" (baixa + corta trechos, zip +
# info.json, ver youtube_clipper.py) — mesmo espírito do _JOBS acima.
_YT_CLIPPER_JOBS: Dict[str, Dict[str, Any]] = {}
YT_CLIPPER_DIR = os.path.join(OUTPUTS_DIR, "youtube_clipper")
os.makedirs(YT_CLIPPER_DIR, exist_ok=True)

# Estado dos jobs de "Baixar de outras redes" (TikTok/Instagram/Twitter(X)/
# Facebook/Kwai — ver toolkit/redes_sociais/) — baixa cada link na maior
# qualidade disponível e devolve um zip com todos.
_REDES_SOCIAIS_JOBS: Dict[str, Dict[str, Any]] = {}
REDES_SOCIAIS_DIR = os.path.join(OUTPUTS_DIR, "redes_sociais")
os.makedirs(REDES_SOCIAIS_DIR, exist_ok=True)

# Estado dos jobs de "Transcrever" (baixa de qualquer fonte, ou usa um
# arquivo enviado, e opcionalmente transcreve com Whisper — ver
# transcrever_avulso.py). Ferramenta avulsa, fora do pipeline de narração.
_TRANSCRICOES_AVULSAS_JOBS: Dict[str, Dict[str, Any]] = {}
TRANSCRICOES_AVULSAS_DIR = os.path.join(OUTPUTS_DIR, "transcricoes_avulsas")
os.makedirs(TRANSCRICOES_AVULSAS_DIR, exist_ok=True)


# 🕘 histórico das ferramentas avulsas (v84_87): cada job salva um _job.json na pasta dele e volta ao abrir o site
def _historico_salvar(pasta_raiz: str, job: Optional[Dict[str, Any]]) -> None:
    if not job or not job.get("id"):
        return
    try:
        d = os.path.join(pasta_raiz, job["id"])
        os.makedirs(d, exist_ok=True)
        dados = dict(job, log=str(job.get("log") or "")[-4000:])
        with open(os.path.join(d, "_job.json"), "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        pass


def _historico_carregar(pasta_raiz: str, destino: Dict[str, Dict[str, Any]], limite: int = 200) -> None:
    try:
        nomes = [n for n in os.listdir(pasta_raiz) if os.path.isfile(os.path.join(pasta_raiz, n, "_job.json"))]
    except OSError:
        return
    nomes.sort(key=lambda n: os.path.getmtime(os.path.join(pasta_raiz, n, "_job.json")))
    for n in nomes[-limite:]:
        try:
            with open(os.path.join(pasta_raiz, n, "_job.json"), encoding="utf-8") as f:
                j = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(j, dict) or j.get("id") != n or n in destino:
            continue
        if j.get("status") in ("processando", "capturando"):
            j.update(status="erro", erro="O site foi fechado enquanto isso rodava.")
        destino[n] = j


for _pasta_h, _dict_h in ((CAPTURAS_DIR, _CAPTURAS_PAGINA), (YT_CLIPPER_DIR, _YT_CLIPPER_JOBS), (REDES_SOCIAIS_DIR, _REDES_SOCIAIS_JOBS),
                          (TRANSCRICOES_AVULSAS_DIR, _TRANSCRICOES_AVULSAS_JOBS)):
    _historico_carregar(_pasta_h, _dict_h)


def _job_dir(job_id: str) -> str:
    return os.path.join(JOBS_DIR, job_id)


def _parse_caption_style_from_form(form, suffix: str = "") -> Dict[str, Any]:
    """Lê os campos de personalização visual da legenda do formulário
    (cor primária, borda, sombra, brilho, fonte, tamanho, posição) —
    usado tanto no upload inicial quanto no fluxo de reaproveitar JSON.
    `suffix` diferencia os nomes dos campos entre os dois formulários
    (ex: "_reuse"), igual já acontece com `add_word_captions`.
    """
    style: Dict[str, Any] = {}
    primary = form.get(f"caption_primary_color{suffix}", "").strip()
    if primary:
        style["primary_color"] = primary
    border_color = form.get(f"caption_border_color{suffix}", "").strip()
    if border_color:
        style["border_color"] = border_color
    border_width = form.get(f"caption_border_width{suffix}", "").strip()
    if border_width:
        try:
            style["border_width"] = int(border_width)
        except ValueError:
            pass
    shadow_depth = form.get(f"caption_shadow_depth{suffix}", "").strip()
    if shadow_depth:
        try:
            style["shadow_depth"] = int(shadow_depth)
        except ValueError:
            pass
    glow = form.get(f"caption_glow{suffix}", "").strip()
    if glow:
        try:
            style["glow"] = int(glow)
        except ValueError:
            pass
    font = form.get(f"caption_font{suffix}", "").strip()
    if font in ("regular", "bold"):
        style["font"] = font
    font_size = form.get(f"caption_font_size{suffix}", "").strip()
    if font_size:
        try:
            style["font_size"] = int(font_size)
        except ValueError:
            pass
    position = form.get(f"caption_position{suffix}", "").strip()
    if position in ("bottom", "middle", "top"):
        style["position"] = position
    return style


def _save_state(job_id: str) -> None:
    job_dir = _job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)  # garante a pasta ANTES de escrever —
    # sem isso, qualquer rota que só mexe em memória (sem nunca ter salvo
    # um arquivo no job antes) falharia ao tentar salvar o estado.
    path = os.path.join(job_dir, "state.json")
    # cópia rasa ANTES de serializar — sem isso, se outra thread (ex: a
    # montagem em segundo plano) adicionar/remover uma chave do job
    # ENQUANTO o json.dump está no meio da iteração, o Python levanta
    # "dictionary changed size during iteration" e a chamada falha.
    # Uma cópia rasa tira uma "foto" atômica das chaves de primeiro
    # nível, imune a essa mutação concorrente específica.
    snapshot = dict(_JOBS[job_id])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------- #
# Página 1: upload do áudio + configuração
# --------------------------------------------------------------------- #

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", providers=DEFAULT_PROVIDERS)


@app.route("/jobs", methods=["GET"])
def jobs_history_page():
    """Lista todos os jobs desta sessão do servidor (em memória — reinicia
    zerado se o servidor for reiniciado), do mais recente pro mais
    antigo, com status e um link pra continuar de onde parou. Sem isso,
    a única forma de voltar a um job era ter guardado a URL — com várias
    narrações rodando ao longo do dia, isso vira um problema de verdade.
    """
    import datetime

    jobs_sorted = sorted(_JOBS.values(), key=lambda j: j.get("created_at", 0), reverse=True)
    jobs_for_display = []
    for job in jobs_sorted:
        display = dict(job)  # cópia rasa — não mexe no dicionário original do job
        created_at = job.get("created_at")
        display["created_at_display"] = (
            datetime.datetime.fromtimestamp(created_at).strftime("%d/%m %H:%M") if created_at else None
        )
        capa = next((p for p in (job.get("segment_previews") or []) if p and p.get("ok") and p.get("thumbnail_url")), None)
        display["capa_url"] = capa["thumbnail_url"] if capa else None
        display["num_trechos"] = len(job.get("pending_segments") or [])
        display["duracao_display"] = f"{job['total_duration']:.0f}s" if job.get("total_duration") else None
        display["tem_video"] = bool(job.get("output_path") and os.path.exists(job["output_path"]))
        display["em_andamento"] = job.get("status") in _STATUS_EM_ANDAMENTO
        jobs_for_display.append(display)
    return render_template("jobs_history.html", jobs=jobs_for_display, apagado=request.args.get("apagado"))


@app.route("/jobs/<job_id>/renomear", methods=["POST"])
def projeto_renomear(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Projeto não encontrado.", 404
    job["nome_projeto"] = (request.form.get("nome") or "").strip()[:120]
    _save_state(job_id)
    return redirect(url_for("jobs_history_page"))


def _apagar_arquivos_do_projeto(job_id: str) -> None:
    """Apaga tudo do projeto no servidor: a pasta jobs/<id> (narração, trilha,
    clipes baixados, cortes do YouTube, imagens, biblioteca de mídia, estado)
    e os vídeos finais em outputs/<id>*.mp4."""
    pasta = os.path.realpath(os.path.join(JOBS_DIR, job_id))
    if os.path.dirname(pasta) == os.path.realpath(JOBS_DIR) and os.path.isdir(pasta):
        shutil.rmtree(pasta, ignore_errors=True)
    if os.path.isdir(OUTPUTS_DIR):
        for nome in os.listdir(OUTPUTS_DIR):
            if nome.startswith(job_id) and os.path.isfile(os.path.join(OUTPUTS_DIR, nome)):
                try:
                    os.remove(os.path.join(OUTPUTS_DIR, nome))
                except OSError:
                    pass


@app.route("/jobs/<job_id>/apagar", methods=["POST"])
def projeto_apagar(job_id: str):
    """Botão "Apagar" da galeria: remove o projeto e TODOS os arquivos dele
    do servidor. Não apaga enquanto algo está rodando nele (a thread
    gravaria o estado de novo e recriaria a pasta)."""
    job = _JOBS.get(job_id)
    if not job:
        return "Projeto não encontrado.", 404
    if job.get("status") in _STATUS_EM_ANDAMENTO:
        return (f"Esse projeto ainda está em andamento ({job.get('status')}). Cancele ou espere terminar antes de apagar.", 409)
    _JOBS.pop(job_id, None)
    _PERF_LOGS.pop(job_id, None)
    _apagar_arquivos_do_projeto(job_id)
    return redirect(url_for("jobs_history_page", apagado=job.get("nome_projeto") or job.get("original_filename") or job_id))


# --------------------------------------------------------------------- #
# Gerador de voz — texto -> áudio narrado, com 3 motores locais à escolha
# (Piper TTS / XTTS v2 / Kokoro). Ver toolkit/tts/voice_generator.py.
# Geração em segundo plano com status ao vivo (mesmo padrão do Roteiro
# para Áudio) -- antes disso a página ficava travada e sem feedback
# nenhum enquanto gerava, o que é especialmente ruim com XTTS (pode
# demorar bastante em CPU).
# --------------------------------------------------------------------- #

VOZES_DIR = os.path.join(OUTPUTS_DIR, "vozes")
os.makedirs(VOZES_DIR, exist_ok=True)

_GERAR_VOZ_STATUS: Dict[str, Dict[str, Any]] = {}  # job_id -> {"running", "log", "erro", "pronto", "engine", "resultado_filename"}


# 🎙 fila do Gerador de voz (v84_65): vários pedidos de uma vez; 2 ao mesmo tempo se a VRAM deixar
import fila_voz as _fila_voz  # noqa: E402
import historico_voz as _hist_voz  # noqa: E402


def _fila_voz_mudou(jid: str, info: Dict[str, Any]) -> None:
    st = _GERAR_VOZ_STATUS.get(jid)
    if not st:
        return
    if info.get("iniciou"):
        st["na_fila"], st["posicao"], st["iniciou_em"] = False, None, info["iniciou"]
        st["log"] = (st.get("log") or "") + "▶ Começou a gerar.\n"
    elif info.get("posicao"):
        st["posicao"] = info["posicao"]


_FILA_VOZ = _fila_voz.Fila(modo_fn=lambda: str(load_site_config().get("voz_simultaneos", "auto")), ao_mudar=_fila_voz_mudou)


def _voz_do_kwargs(engine: str, kwargs: Dict[str, Any]) -> str:
    for k in ("nome_voz", "voz", "voice_profile", "speaker", "reference_id"):
        if kwargs.get(k):
            return str(kwargs[k])
    if kwargs.get("speaker_wav"):
        return "áudio de referência"
    return ""

# "Simular Conversa" -- geração de UMA fala é assíncrona (motor de voz
# pode demorar, principalmente XTTS), chave "<conversa_id>:<fala_id>".
_CONVERSA_FALA_STATUS: Dict[str, Dict[str, Any]] = {}


# Diagnóstico de GPU: antes rodava a CADA abertura do Gerador de voz / Roteiro
# para Áudio — `import torch` + teste de CUDA + `nvidia-smi` + onnxruntime, que
# no Windows com PyTorch instalado leva de vários segundos a dezenas. E, enquanto
# o torch carregava, o lock de import do Python segurava as OUTRAS páginas também.
# Agora roda UMA vez, em segundo plano, quando o servidor sobe; as páginas usam o
# resultado guardado ("verificando GPU…" enquanto não terminou).
_GPU_CACHE: Dict[str, Any] = {"pronto": False, "gpu": {}, "diag": {}}


def _verificar_gpu_em_segundo_plano() -> None:
    try:
        _GPU_CACHE["gpu"] = tts_gpu_status()
        _GPU_CACHE["diag"] = tts_diagnosticar_gpu()
    except Exception as exc:  # noqa: BLE001 -- diagnóstico nunca derruba o site
        _GPU_CACHE["diag"] = {"diagnostico": f"Não consegui verificar a GPU: {exc}"}
    finally:
        _GPU_CACHE["pronto"] = True


def _gpu_cache() -> Dict[str, Any]:
    if not _GPU_CACHE.get("iniciado"):
        _GPU_CACHE["iniciado"] = True
        threading.Thread(target=_verificar_gpu_em_segundo_plano, name="diagnostico-gpu", daemon=True).start()
    return _GPU_CACHE


@app.route("/gerar-voz/gpu", methods=["GET"])
def gerar_voz_gpu():
    """Resultado do diagnóstico de GPU (a página consulta enquanto ele não termina)."""
    c = _gpu_cache()
    return jsonify({"pronto": c["pronto"], "gpu": c["gpu"], "diag": c["diag"]})


@app.route("/gerar-voz/fish/status", methods=["GET"])
def gerar_voz_fish_status():
    """🐟 O servidor do Fish Audio S2 está no ar? (ou: tem chave da API?) — nunca devolve a chave."""
    from tts import voice_generator as _vg
    return jsonify(_vg.fish_status(timeout=4.0))


@app.route("/gerar-voz", methods=["GET"])
def gerar_voz_page():
    return render_template(
        "gerar_voz.html",
        engines=tts_ENGINES,
        piper_vozes=tts_PIPER_VOZES_SUGERIDAS,
        xtts_idiomas=sorted(tts_XTTS_IDIOMAS),
        xtts_checkpoints=tts_XTTS_CHECKPOINTS_CONHECIDOS,
        chatterbox_idiomas=sorted(tts_CHATTERBOX_IDIOMAS),
        kokoro_vozes=tts_KOKORO_VOZES,
        kokoro_variantes=tts_KOKORO_MODEL_VARIANTS,
        kokoro_precisoes=tts_KOKORO_PRECISIONS,
        perfis_de_voz=tts_listar_perfis_de_voz(),
        fish_tags=__import__("tts.voice_generator", fromlist=["x"]).FISH_TAGS_EXEMPLO,
        gpu=_gpu_cache()["gpu"],
        gpu_diagnostico=_gpu_cache()["diag"],
        gpu_verificando=not _gpu_cache()["pronto"],
        idiomas=[(k, v[0]) for k, v in __import__("idiomas").IDIOMAS.items()],
        texto_inicial=(_texto_do_roteiro_yt(request.args.get("roteiro")) or _texto_da_venda(request.args.get("venda"))
                       or _texto_do_dossie(request.args.get("dossie"))),
        roteiro_id=request.args.get("roteiro") if _texto_do_roteiro_yt(request.args.get("roteiro")) else "",
        venda_id=request.args.get("venda") if _texto_da_venda(request.args.get("venda")) else "",
        dossie_id=request.args.get("dossie") if _texto_do_dossie(request.args.get("dossie")) else "",
        idioma_inicial=_idioma_do_projeto(request.args.get("venda"), request.args.get("dossie")),
        projetos_voz=_projetos_para_voz(),
        vozes_canal=_info_vozes_dossie(request.args.get("dossie")),
    )


def _projetos_para_voz() -> list:
    """🎙 v84_170: os projetos com roteiro, pro seletor do Gerar voz (abre com o texto e o projeto ligados)."""
    out = []
    try:
        import dossies
        out += [{"param": "dossie", "id": x["id"], "nome": x["nome"], "grupo": "🕵️ Modelos de vídeo", "atualizado": x["atualizado"]}
                for x in dossies.listar(BASE_DIR) if x.get("tem_roteiro")]
    except Exception:  # noqa: BLE001
        pass
    try:
        import roteiros_yt
        out += [{"param": "roteiro", "id": x["id"], "nome": x["titulo"], "grupo": "📜 Roteiro do YouTube", "atualizado": x["atualizado"]}
                for x in roteiros_yt.listar_projetos(BASE_DIR)]
    except Exception:  # noqa: BLE001
        pass
    try:
        import vendas
        out += [{"param": "venda", "id": x["id"], "nome": x["nome"], "grupo": "🛒 Vídeo de venda", "atualizado": x["atualizado"]}
                for x in vendas.listar(BASE_DIR) if x.get("tem_roteiro")]
    except Exception:  # noqa: BLE001
        pass
    return out[:300]


def _normalizar_multivoz(entrada: str, saida: str) -> None:
    na.normalizar_volume_wav(Path(entrada), Path(saida))
    if not os.path.exists(saida) or os.path.getsize(saida) < 100:
        shutil.copy(entrada, saida)


def _gerar_voz_com_chamadas(engine: str, partes: List[Dict[str, Any]], output_path: str, kwargs: Dict[str, Any], log,
                            instancias: int = 1) -> List[Dict[str, Any]]:
    """Texto com [[INSCREVA: ...]] etc (ver chamadas.py): gera cada pedaço
    separado (no mesmo processo, sem recarregar o modelo), junta e devolve
    onde cada chamada começa e termina no áudio final — exato, sem depender
    de transcrição."""
    import chamadas as ch
    pasta = os.path.splitext(output_path)[0] + "_partes"
    shutil.rmtree(pasta, ignore_errors=True)
    os.makedirs(pasta, exist_ok=True)
    try:
        itens, arquivo_da_parte = [], {}
        for k, p in enumerate(partes):
            limpo = na.limpar_texto_para_tts(p["texto"], motor=engine).strip()
            if re.search(r"\w", limpo):
                arq = os.path.join(pasta, f"parte_{k:03d}.wav")
                arquivo_da_parte[k] = arq
                itens.append((engine, limpo, arq, kwargs))
        log(f"📣 {sum(1 for p in partes if p['tipo'])} chamada(s) no texto — gerando em {len(itens)} pedaço(s) pra saber onde cada uma fica.")
        if instancias > 1:  # ⚡ v84_103: várias instâncias do motor dividindo os blocos de todos os pedaços
            import tts_paralelo
            ks = sorted(arquivo_da_parte)
            prontos = tts_paralelo.gerar_partes(engine, [t for (_e, t, _a, _k) in itens], os.path.join(pasta, "_blocos"),
                                                kwargs, instancias, log)
            for k, arq in zip(ks, prontos):
                shutil.move(arq, arquivo_da_parte[k])
        else:
            erros = tts_gerar_audio_isolado_lote(itens, on_progresso=lambda i, e: log(f"  pedaço {i + 1}/{len(itens)} " + ("⚠ " + e if e else "pronto")))
            if erros:
                raise VoiceGeneratorError("Falhou ao gerar: " + "; ".join(f"pedaço {i + 1}: {e}" for i, e in sorted(erros.items()))[:800])
        arquivos = [arquivo_da_parte[k] for k in sorted(arquivo_da_parte)]
        duracoes = [(_probe_media_duration(arquivo_da_parte[k]) if k in arquivo_da_parte else 0.0) for k in range(len(partes))]
        taxa = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", arquivos[0]],
                              capture_output=True, text=True, timeout=30).stdout.strip() or "24000"
        entradas = []
        for a in arquivos:
            entradas += ["-i", a]
        filtro = "".join(f"[{i}:a]aresample={taxa},aformat=channel_layouts=mono[a{i}];" for i in range(len(arquivos)))
        filtro += "".join(f"[a{i}]" for i in range(len(arquivos))) + f"concat=n={len(arquivos)}:v=0:a=1[out]"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error"] + entradas + ["-filter_complex", filtro, "-map", "[out]", "-c:a", "pcm_s16le", output_path],
                       check=True, capture_output=True, timeout=1800)
        return ch.de_duracoes(partes, duracoes)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _salvar_chamadas_voz(status: dict, output_path: str, lista: List[Dict[str, Any]], log) -> None:
    import chamadas as ch
    caminho = os.path.splitext(output_path)[0] + ".chamadas.json"
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"chamadas": lista}, f, ensure_ascii=False, indent=2)
    status["resultado_chamadas_filename"] = os.path.basename(caminho)
    status["chamadas"] = lista
    for c in lista:
        log(f"📣 {ch.rotulo(c['tipo'])}: {c['inicio']:.1f}s → {c['fim']:.1f}s" + (f" “{c['texto'][:60]}”" if c.get("texto") else " (ponto)"))


def _gerar_voz_em_background(job_id: str, engine: str, texto: str, output_path: str, kwargs: Dict[str, Any], legenda_kwargs: Optional[Dict[str, Any]] = None,
                             multivoz: bool = False) -> None:
    status = _GERAR_VOZ_STATUS[job_id]
    import chamadas as ch
    partes_ch = ch.dividir(texto)
    tem_chamadas = any(p["tipo"] for p in partes_ch)

    def log(linha: str) -> None:
        status["log"] += linha + "\n"

    try:
        label = tts_ENGINES.get(engine, {}).get("label", engine)
        log(f"Motor escolhido: {label}.")
        if engine == "xtts":
            log("XTTS v2 é o motor mais pesado — em CPU pode demorar bem mais que Piper/Kokoro.")
        # Mesma limpeza que o Roteiro para Áudio já fazia (tirava
        # aspas/reticências/parênteses etc antes de mandar pro motor)
        # -- faltava aqui no Gerador de Voz avulso, que mandava o texto
        # cru e às vezes acabava com o motor "lendo" a pontuação em voz
        # alta (falando "aspas", "reticências"...).
        if multivoz:
            import multivoz as mv
            log("🎭 Modo multi voice: as tags [slug] trocam a voz e não são lidas.")
            try:
                r = mv.gerar(ch.remover_marcadores(texto), output_path, engine, kwargs, tts_gerar_audio_isolado,
                             lambda t, m: na.limpar_texto_para_tts(t, motor=m if isinstance(m, str) else ("chatterbox_turbo" if m else "")),
                             pausa_troca=float((legenda_kwargs or {}).get("pausa_troca", 0.35)), on_log=log, normalizar_fn=_normalizar_multivoz)
            except mv.MultiVozError as exc:
                raise VoiceGeneratorError(str(exc)) from exc
            log(f"{r['falas']} fala(s), vozes: " + (", ".join(r["vozes"]) or "só a padrão") + ".")
        elif tem_chamadas:
            _salvar_chamadas_voz(status, output_path, _gerar_voz_com_chamadas(engine, partes_ch, output_path, kwargs, log,
                                                                              int(status.get("instancias") or 1)), log)
        else:
            texto_limpo = na.limpar_texto_para_tts(texto, motor=engine)
            if int(status.get("instancias") or 1) > 1:  # ⚡ v84_103: vários blocos ao mesmo tempo
                import tts_paralelo
                tts_paralelo.gerar_texto(engine, texto_limpo, output_path, kwargs, int(status["instancias"]), log)
            else:
                tts_gerar_audio_isolado(engine, texto_limpo, output_path, **kwargs)
        status["resultado_filename"] = os.path.basename(output_path)
        log("Pronto!")

        # Legenda (SRT): sempre tenta gerar depois do áudio -- transcreve
        # o próprio áudio já pronto com timestamp por palavra e quebra
        # no formato escolhido (ou no padrão, se a pessoa não mexeu nas
        # opções avançadas). Se a transcrição falhar por qualquer motivo,
        # o áudio já gerado continua válido -- só registra o erro no log
        # e segue sem legenda, em vez de derrubar o job inteiro.
        try:
            # ✍️ o TTS não diz em que instante cada palavra é falada: o Whisper só MEDE o tempo; o texto da
            # legenda é o do roteiro (nomes, acentos, números e pontuação como você escreveu) — legenda_texto.py
            import legenda_texto as _lt
            log("⏱ Medindo no áudio o tempo de cada palavra (o texto da legenda é o do seu roteiro)...")
            try:
                segmentos = transcribe_audio(output_path, word_timestamps=True)
                segmentos, _inf_leg = _lt.com_texto(segmentos, texto)
                if _inf_leg["usou_texto"]:
                    log(f"✍️ Legenda com o texto do roteiro ({_inf_leg['casadas']}% das palavras achadas no áudio; o resto ganhou o tempo do trecho).")
                else:
                    log(f"⚠ O áudio não bateu com o texto ({_inf_leg['casadas']}% das palavras) — a legenda ficou com o que o Whisper ouviu.")
            except TranscriptionError as exc_tr:
                segmentos = _lt.estimar(texto, get_audio_duration(output_path))
                if not segmentos:
                    raise
                log(f"⚠ Whisper indisponível ({str(exc_tr)[:160]}) — legenda com o texto do roteiro e tempos ESTIMADOS pelo tamanho das palavras.")
            if multivoz and tem_chamadas:  # áudio saiu de uma vez: acha as chamadas nas palavras ditas
                _salvar_chamadas_voz(status, output_path, ch.alinhar(partes_ch, [w for sg in segmentos for w in sg.get("words", [])]), log)
            modo = (legenda_kwargs or {}).get("modo", "legenda")
            srt_texto = lg.gerar_srt(
                segmentos,
                modo=modo,
                duracao_alvo_s=(legenda_kwargs or {}).get("duracao_alvo_s", 5.0),
                max_palavras=(legenda_kwargs or {}).get("max_palavras", 5),
                palavras_por_linha=(legenda_kwargs or {}).get("palavras_por_linha", 5),
            )
            srt_path = os.path.splitext(output_path)[0] + ".srt"
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_texto)
            status["resultado_srt_filename"] = os.path.basename(srt_path)
            log("Legenda gerada.")
            _capitulos_do_roteiro(status, output_path, [w for sg in segmentos for w in sg.get("words", [])], log)
        except (TranscriptionError, lg.LegendaError) as exc:
            log(f"Não foi possível gerar a legenda: {exc} (o áudio continua disponível normalmente)")
            _capitulos_do_roteiro(status, output_path, [], log)
        except Exception as exc:  # noqa: BLE001
            log(f"Não foi possível gerar a legenda (erro inesperado): {exc} (o áudio continua disponível normalmente)")
    except VoiceGeneratorError as exc:
        status["erro"] = str(exc)
        log(f"\nERRO: {exc}")
    except Exception as exc:  # noqa: BLE001
        status["erro"] = f"Falha inesperada ao gerar o áudio: {exc}"
        log(f"\nERRO inesperado: {traceback.format_exc()}")
    finally:
        status["running"] = False
        status["pronto"] = True
        try:
            _hist_voz.registrar(VOZES_DIR, job_id, status)
        except Exception:  # noqa: BLE001 — o histórico nunca derruba a geração
            pass


def _capitulos_do_roteiro(status: Dict[str, Any], audio: str, palavras: List[Dict[str, Any]], log) -> None:
    """Áudio gerado a partir do Roteiro do YouTube: põe nos capítulos da descrição o
    tempo em que cada um começa DE VERDADE no áudio."""
    if status.get("dossie_id") and not status.get("roteiro_id"):
        _capitulos_do_dossie(status, audio, palavras, log)
        return
    pid = status.get("roteiro_id")
    if not pid:
        return
    try:
        import roteiros_yt
        dur = None
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                               capture_output=True, text=True, timeout=30)
            dur = float(r.stdout.strip())
        except Exception:  # noqa: BLE001
            pass
        res = roteiros_yt.aplicar_tempos_do_audio(BASE_DIR, pid, palavras, dur, origem=os.path.basename(audio))
        if res and res.get("capitulos"):
            status["capitulos"] = [{"titulo": c["titulo"], "segundos": c.get("segundos_audio")} for c in res["capitulos"]]
            status["roteiro_descricao"] = roteiros_yt.descricao_com_capitulos(res)
            log(f"📝 Capítulos do roteiro ajustados ao áudio ({len(res['capitulos'])}): "
                + ", ".join(f"{int(c.get('segundos_audio') or 0) // 60}:{int(c.get('segundos_audio') or 0) % 60:02d} {c['titulo']}" for c in res["capitulos"][:12]))
    except Exception as exc:  # noqa: BLE001
        log(f"(não consegui ajustar os capítulos do roteiro ao áudio: {exc})")


def _capitulos_do_dossie(status: Dict[str, Any], audio: str, palavras: List[Dict[str, Any]], log) -> None:
    """Áudio do 🕵️ Modelo de vídeo: capítulos da descrição com o tempo real do áudio."""
    try:
        import dossies
        dur = None
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                               capture_output=True, text=True, timeout=30)
            dur = float(r.stdout.strip())
        except Exception:  # noqa: BLE001
            pass
        res = dossies.aplicar_tempos_do_audio(BASE_DIR, status["dossie_id"], palavras, dur, origem=os.path.basename(audio))
        if res and res.get("capitulos"):
            status["capitulos"] = [{"titulo": c["titulo"], "segundos": c.get("segundos_audio")} for c in res["capitulos"]]
            status["roteiro_descricao"] = dossies.descricao_completa(dossies.carregar(BASE_DIR, status["dossie_id"]))
            log(f"📝 Capítulos ajustados ao áudio ({len(res['capitulos'])}).")
    except Exception as exc:  # noqa: BLE001
        log(f"(não consegui ajustar os capítulos ao áudio: {exc})")


@app.route("/gerar-voz/gerar", methods=["POST"])
def gerar_voz_gerar():
    texto = request.form.get("texto", "").strip()
    # [CENA 3] e afins são marcas do roteiro, não fala: nunca vão pro gerador de voz
    import chamadas as _chm_cena
    texto, _n_cenas = _chm_cena.tirar_marcas_de_cena(texto)
    engine = request.form.get("engine", "piper").strip().lower()
    velocidade_raw = request.form.get("velocidade", "1.0").strip()
    try:
        velocidade = float(velocidade_raw) if velocidade_raw else 1.0
    except ValueError:
        velocidade = 1.0
    forcar_cpu = request.form.get("forcar_cpu") == "on"

    if not texto:
        return jsonify({"erro": "Escreva algum texto pra narrar antes de gerar o áudio."}), 400
    if engine not in tts_ENGINES:
        return jsonify({"erro": f"Motor de voz desconhecido: {engine!r}."}), 400

    kwargs: Dict[str, Any] = {}
    if engine == "piper":
        nome_voz = request.form.get("piper_voz", "").strip() or "pt_BR-faber-medium"
        kwargs = {"nome_voz": nome_voz, "velocidade": velocidade, "use_gpu": (False if forcar_cpu else None)}
    elif engine == "xtts":
        idioma = request.form.get("xtts_idioma", "pt").strip() or "pt"
        speaker = request.form.get("xtts_speaker", "").strip()
        perfil_selecionado = request.form.get("xtts_perfil", "").strip()
        salvar_como_perfil = request.form.get("xtts_salvar_perfil") == "on"
        nome_novo_perfil = request.form.get("xtts_nome_novo_perfil", "").strip()
        checkpoint_conhecido = request.form.get("xtts_checkpoint", "").strip() or "padrao"
        kwargs = {"idioma": idioma, "use_gpu": (False if forcar_cpu else None)}
        if checkpoint_conhecido != "padrao":
            kwargs["checkpoint_conhecido"] = checkpoint_conhecido

        speaker_wav_file = request.files.get("xtts_speaker_wav")
        if speaker_wav_file and speaker_wav_file.filename:
            safe_name = secure_filename(speaker_wav_file.filename)
            ref_path = os.path.join(VOZES_DIR, f"ref_{uuid.uuid4().hex}_{safe_name}")
            speaker_wav_file.save(ref_path)
            if salvar_como_perfil:
                if not nome_novo_perfil:
                    return jsonify({"erro": "Dê um nome pro novo perfil de voz antes de salvar."}), 400
                try:
                    tts_salvar_perfil_de_voz(nome_novo_perfil, ref_path)
                except VoiceGeneratorError as exc:
                    return jsonify({"erro": str(exc)}), 400
                kwargs["voice_profile"] = nome_novo_perfil
            else:
                kwargs["speaker_wav"] = ref_path
        elif perfil_selecionado:
            kwargs["voice_profile"] = perfil_selecionado
        elif speaker:
            kwargs["speaker"] = speaker
        # sem nenhum dos três: xtts_synthesize já cai pra 1a voz pronta do modelo sozinho
    elif engine == "chatterbox":
        idioma = request.form.get("chatterbox_idioma", "pt").strip() or "pt"
        perfil_selecionado = request.form.get("chatterbox_perfil", "").strip()
        salvar_como_perfil = request.form.get("chatterbox_salvar_perfil") == "on"
        nome_novo_perfil = request.form.get("chatterbox_nome_novo_perfil", "").strip()
        try:
            exaggeration = float(request.form.get("chatterbox_exaggeration", "0.5") or 0.5)
        except ValueError:
            exaggeration = 0.5
        try:
            cfg_weight = float(request.form.get("chatterbox_cfg_weight", "0.5") or 0.5)
        except ValueError:
            cfg_weight = 0.5
        kwargs = {
            "idioma": idioma, "exaggeration": exaggeration, "cfg_weight": cfg_weight,
            "use_gpu": (False if forcar_cpu else None),
        }

        # O mesmo perfil de voz (VOICE_PROFILES_DIR) é compartilhado
        # entre XTTS e Chatterbox -- os dois só precisam de um áudio
        # de referência curto pra clonar a voz.
        speaker_wav_file = request.files.get("chatterbox_speaker_wav")
        if speaker_wav_file and speaker_wav_file.filename:
            safe_name = secure_filename(speaker_wav_file.filename)
            ref_path = os.path.join(VOZES_DIR, f"ref_{uuid.uuid4().hex}_{safe_name}")
            speaker_wav_file.save(ref_path)
            if salvar_como_perfil:
                if not nome_novo_perfil:
                    return jsonify({"erro": "Dê um nome pro novo perfil de voz antes de salvar."}), 400
                try:
                    tts_salvar_perfil_de_voz(nome_novo_perfil, ref_path)
                except VoiceGeneratorError as exc:
                    return jsonify({"erro": str(exc)}), 400
                kwargs["voice_profile"] = nome_novo_perfil
            else:
                kwargs["speaker_wav"] = ref_path
        elif perfil_selecionado:
            kwargs["voice_profile"] = perfil_selecionado
        # sem nenhum dos dois: chatterbox_synthesize gera com a voz "neutra" padrão do modelo
    elif engine == "chatterbox_turbo":
        perfil_selecionado = request.form.get("chatterbox_turbo_perfil", "").strip()
        salvar_como_perfil = request.form.get("chatterbox_turbo_salvar_perfil") == "on"
        nome_novo_perfil = request.form.get("chatterbox_turbo_nome_novo_perfil", "").strip()
        kwargs = {"use_gpu": (False if forcar_cpu else None)}

        # mesmo perfil compartilhado com XTTS/Chatterbox multilíngue
        speaker_wav_file = request.files.get("chatterbox_turbo_speaker_wav")
        if speaker_wav_file and speaker_wav_file.filename:
            safe_name = secure_filename(speaker_wav_file.filename)
            ref_path = os.path.join(VOZES_DIR, f"ref_{uuid.uuid4().hex}_{safe_name}")
            speaker_wav_file.save(ref_path)
            if salvar_como_perfil:
                if not nome_novo_perfil:
                    return jsonify({"erro": "Dê um nome pro novo perfil de voz antes de salvar."}), 400
                try:
                    tts_salvar_perfil_de_voz(nome_novo_perfil, ref_path)
                except VoiceGeneratorError as exc:
                    return jsonify({"erro": str(exc)}), 400
                kwargs["voice_profile"] = nome_novo_perfil
            else:
                kwargs["speaker_wav"] = ref_path
        elif perfil_selecionado:
            kwargs["voice_profile"] = perfil_selecionado
        # sem nenhum dos dois: chatterbox_turbo_synthesize gera com a voz "neutra" padrão do modelo
    elif engine == "fish_s2":
        perfil_selecionado = request.form.get("fish_perfil", "").strip()
        salvar_como_perfil = request.form.get("fish_salvar_perfil") == "on"
        nome_novo_perfil = request.form.get("fish_nome_novo_perfil", "").strip()
        texto_ref = " ".join((request.form.get("fish_texto_referencia") or "").split())[:1000]
        reference_id = re.sub(r"[^0-9a-zA-Z_-]", "", request.form.get("fish_reference_id", ""))[:64]
        try:
            temperatura = max(0.1, min(1.0, float(request.form.get("fish_temperatura", "0.8") or 0.8)))
        except ValueError:
            temperatura = 0.8
        kwargs = {"idioma": request.form.get("fish_idioma", "pt").strip() or "pt", "velocidade": velocidade,
                  "temperatura": temperatura}
        speaker_wav_file = request.files.get("fish_speaker_wav")
        if speaker_wav_file and speaker_wav_file.filename:
            safe_name = secure_filename(speaker_wav_file.filename)
            ref_path = os.path.join(VOZES_DIR, f"ref_{uuid.uuid4().hex}_{safe_name}")
            speaker_wav_file.save(ref_path)
            if salvar_como_perfil:
                if not nome_novo_perfil:
                    return jsonify({"erro": "Dê um nome pro novo perfil de voz antes de salvar."}), 400
                try:
                    tts_salvar_perfil_de_voz(nome_novo_perfil, ref_path)
                except VoiceGeneratorError as exc:
                    return jsonify({"erro": str(exc)}), 400
                kwargs["voice_profile"] = nome_novo_perfil
            else:
                kwargs["speaker_wav"] = ref_path
                if texto_ref:
                    kwargs["texto_referencia"] = texto_ref
        elif perfil_selecionado:
            kwargs["voice_profile"] = perfil_selecionado
        elif reference_id:
            kwargs["reference_id"] = reference_id
    elif engine == "kokoro":
        voz = request.form.get("kokoro_voz", "").strip() or "pf_dora"
        idioma = request.form.get("kokoro_idioma", "").strip() or None
        variante = request.form.get("kokoro_variante", "").strip() or tts_DEFAULT_KOKORO_VARIANT
        precisao = request.form.get("kokoro_precisao", "").strip() or tts_DEFAULT_KOKORO_PRECISION
        kwargs = {"voz": voz, "velocidade": velocidade, "idioma": idioma, "variante": variante, "precisao": precisao}

    job_id = uuid.uuid4().hex
    output_path = os.path.join(VOZES_DIR, f"{job_id}.wav")

    # Legenda (SRT) -- opções avançadas (o toggle "avançado" na tela só
    # controla se esses campos aparecem pra edição; a legenda em si é
    # SEMPRE gerada depois do áudio, com esses valores ou os padrões).
    legenda_modo = request.form.get("legenda_modo", "legenda").strip().lower()
    if legenda_modo not in lg.MODOS_VALIDOS:
        legenda_modo = "legenda"
    try:
        legenda_duracao_alvo_s = float(request.form.get("legenda_duracao_alvo_s", "5") or 5)
    except ValueError:
        legenda_duracao_alvo_s = 5.0
    try:
        legenda_max_palavras = int(request.form.get("legenda_max_palavras", "5") or 5)
    except ValueError:
        legenda_max_palavras = 5
    try:
        legenda_palavras_por_linha = int(request.form.get("legenda_palavras_por_linha", "5") or 5)
    except ValueError:
        legenda_palavras_por_linha = 5
    legenda_kwargs = {
        "modo": legenda_modo,
        "duracao_alvo_s": legenda_duracao_alvo_s,
        "max_palavras": legenda_max_palavras,
        "palavras_por_linha": legenda_palavras_por_linha,
    }

    multivoz_on = request.form.get("multivoz") == "on"
    import idiomas
    # idioma da narração (vai no info.json do .zip): o escolhido na tela > o da voz > o do texto.
    # No multi voice cada fala pode ter outro motor: aí o texto manda.
    _idioma = idiomas.descobrir("" if multivoz_on else engine, kwargs, texto, request.form.get("idioma_narracao"))
    _GERAR_VOZ_STATUS[job_id] = {
        "running": True, "log": "", "erro": None, "pronto": False,
        "engine": engine, "resultado_filename": None, "resultado_srt_filename": None,
        "idioma": _idioma["codigo"], "idioma_origem": _idioma["origem"],
        # pra página poder voltar a acompanhar (recarregou, fechou a aba, abriu em outra)
        "criado_em": time.time(), "texto_inicio": " ".join(texto.split())[:90], "palavras": len(texto.split()),
        # veio do Roteiro do YouTube: no fim, os capítulos ganham o tempo REAL do áudio
        "roteiro_id": (request.form.get("roteiro_id") or "").strip() if re.fullmatch(r"[0-9a-f]{6,40}", (request.form.get("roteiro_id") or "").strip()) else None,
        # 🛒 projeto de venda: vai no info.json do .zip — o Novo vídeo já escolhe o projeto sozinho
        "venda_id": (request.form.get("venda_id") or "").strip() if re.fullmatch(r"[0-9a-f]{10}", (request.form.get("venda_id") or "").strip()) else None,
        "dossie_id": (request.form.get("dossie_id") or "").strip() if re.fullmatch(r"[0-9a-f]{10}", (request.form.get("dossie_id") or "").strip()) else None,
    }
    if multivoz_on:
        import multivoz as mv
        conf = mv.dividir(texto)
        if conf["desconhecidas"]:
            return jsonify({"erro": "Tag(s) sem voz cadastrada: " + ", ".join(f"[{x}]" for x in conf["desconhecidas"])
                                    + " — cadastre a voz com esse slug em 🎭 Vozes ou corrija o texto."}), 400
        try:
            legenda_kwargs["pausa_troca"] = max(0.0, min(3.0, float(request.form.get("multivoz_pausa", "0.35") or 0.35)))
        except ValueError:
            pass
    st = _GERAR_VOZ_STATUS[job_id]
    st.update(na_fila=True, voz=_voz_do_kwargs(engine, kwargs), multivoz=multivoz_on, log="⏳ Na fila…\n")
    if not (st.get("dossie_id") or st.get("roteiro_id") or st.get("venda_id")):
        try:  # 📑 roteiro de um modelo de vídeo colado à mão: liga sozinho (capítulos + .zip com o projeto)
            import dossies
            _achado = dossies.achar_pelo_texto(BASE_DIR, texto)
            if _achado:
                st["dossie_id"] = _achado
                st["log"] += f"🕵️ Esse texto é o roteiro do modelo de vídeo “{dossies.nome_do_projeto(dossies.carregar(BASE_DIR, _achado))}” — os capítulos vão pro tempo do áudio.\n"
            else:
                _rid = dossies.achar_roteiro_yt_pelo_texto(BASE_DIR, texto)
                if _rid:
                    st["roteiro_id"] = _rid
                    st["log"] += "📝 Esse texto é o roteiro de um projeto do Roteiro do YouTube — os capítulos vão pro tempo do áudio.\n"
        except Exception:  # noqa: BLE001
            pass
    # ⚡ v84_103: quantas instâncias do motor geram ESTE áudio (blocos ao mesmo tempo)
    import tts_paralelo
    _modo_inst = str(request.form.get("instancias") or tts_paralelo.modo_salvo())
    _n_inst, _por_que = (1, "multi voice: 1 instância") if multivoz_on else tts_paralelo.escolher(
        engine, _modo_inst, forcar_cpu or kwargs.get("use_gpu") is False, len(texto))
    st["instancias"] = _n_inst
    st["log"] += f"⚡ {_por_que}.\n" + (tts_paralelo.AVISO + "\n" if _n_inst > 1 else "")
    pos = _FILA_VOZ.iniciar(
        job_id, engine,
        lambda: _gerar_voz_e_avisar(job_id, engine, texto, output_path, kwargs, legenda_kwargs, multivoz_on),
        cpu=forcar_cpu, instancias=_n_inst)
    if st.get("na_fila"):
        st["posicao"] = _FILA_VOZ.posicao(job_id)
    return jsonify({"ok": True, "job_id": job_id, "posicao": st.get("posicao") or (pos if st.get("na_fila") else None)})


def _gerar_voz_e_avisar(job_id: str, *a: Any) -> None:
    try:
        _gerar_voz_em_background(job_id, *a)
    finally:
        st = _GERAR_VOZ_STATUS.get(job_id) or {}
        _avisar_fim("🎙️ Áudio “" + (st.get("texto_inicio") or "")[:50] + "…”", st.get("erro"), "/gerar-voz#historico", "voz",
                    "Ouça ou baixe no histórico do Gerador de voz.")


def _config_voz_do_form(form) -> Tuple[str, Dict[str, Any]]:
    """Motor + config (chaves do Roteiro para Áudio) do que está escolhido na tela do Gerador de voz."""
    engine = (form.get("engine") or "piper").strip().lower()
    try:
        vel = float(form.get("velocidade") or 1.0)
    except ValueError:
        vel = 1.0
    c: Dict[str, Any] = {"usarGpu": form.get("forcar_cpu") != "on"}
    if engine == "piper":
        c.update(voz=form.get("piper_voz") or "pt_BR-faber-medium", velocidade=vel)
    elif engine == "kokoro":
        c.update(voz=form.get("kokoro_voz") or "pf_dora", velocidade=vel, idioma=form.get("kokoro_idioma") or "",
                 kokoroVariante=form.get("kokoro_variante") or "", kokoroPrecisao=form.get("kokoro_precisao") or "")
    elif engine == "xtts":
        c.update(idioma=form.get("xtts_idioma") or "pt", vozPerfil=form.get("xtts_perfil") or "", voz=form.get("xtts_speaker") or "",
                 xttsCheckpoint=form.get("xtts_checkpoint") or "")
    elif engine == "chatterbox":
        c.update(idioma=form.get("chatterbox_idioma") or "pt", vozPerfil=form.get("chatterbox_perfil") or "",
                 chatterboxExaggeration=form.get("chatterbox_exaggeration") or 0.5, chatterboxCfgWeight=form.get("chatterbox_cfg_weight") or 0.5)
    elif engine == "chatterbox_turbo":
        c.update(vozPerfil=form.get("chatterbox_turbo_perfil") or "")
    elif engine == "fish_s2":
        c.update(vozPerfil=form.get("fish_perfil") or "", velocidade=vel, idioma=form.get("fish_idioma") or "pt",
                 fishReferenceId=re.sub(r"[^0-9a-zA-Z_-]", "", form.get("fish_reference_id") or "")[:64],
                 fishTemperatura=form.get("fish_temperatura") or 0.8)
    for k in ("velocidade", "chatterboxExaggeration", "chatterboxCfgWeight", "fishTemperatura"):
        if k in c:
            try:
                c[k] = float(c[k])
            except (TypeError, ValueError):
                c.pop(k)
    return engine, c


def _vozes_json():
    import multivoz as mv
    return [dict(v, resumo=mv.resumo(v), genero=v.get("genero") or "", idade=v.get("idade") or "", descricao=v.get("descricao") or "",
                 genero_rotulo=mv.rotulo_genero(v), herdado=v.get("herdado") or []) for v in mv.listar()]


@app.route("/gerar-voz/vozes", methods=["GET"])
def multivoz_listar():
    import multivoz as mv
    return jsonify({"ok": True, "vozes": _vozes_json(), "instrucao_ia": mv.instrucao_para_ia()})


@app.route("/gerar-voz/vozes", methods=["POST"])
def multivoz_salvar():
    """Salva a voz configurada na tela como personagem com slug ([ricardo])."""
    import multivoz as mv
    engine, config = _config_voz_do_form(request.form)
    if request.files.get(f"{engine}_speaker_wav") and request.files[f"{engine}_speaker_wav"].filename:
        return jsonify({"erro": "Pra salvar uma voz clonada, salve antes o áudio de referência como PERFIL (caixa 'salvar como perfil') e escolha o perfil."}), 400
    try:
        v = mv.salvar({"nome": request.form.get("mv_nome"), "slug": request.form.get("mv_slug"), "motor": engine, "config": config,
                       "cor": request.form.get("mv_cor"), "genero": request.form.get("mv_genero"), "idade": request.form.get("mv_idade"),
                       "descricao": request.form.get("mv_descricao")}, slug_antigo=(request.form.get("mv_slug_antigo") or None))
    except mv.MultiVozError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "voz": v, "vozes": _vozes_json(), "instrucao_ia": mv.instrucao_para_ia()})


@app.route("/gerar-voz/vozes/<slug>/genero", methods=["POST"])
def multivoz_genero(slug: str):
    """Define o gênero (masculino/feminino/neutro) e a descrição curta de uma voz
    — vai pra instrução da IA (multi voice e Vídeos modelados)."""
    import multivoz as mv
    corpo = request.get_json(silent=True) or request.form
    try:
        mv.definir_genero(slug, corpo.get("genero"), corpo.get("descricao"), corpo.get("idade"))
    except mv.MultiVozError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "vozes": _vozes_json(), "instrucao_ia": mv.instrucao_para_ia()})


@app.route("/gerar-voz/vozes/<slug>/excluir", methods=["POST"])
def multivoz_excluir(slug: str):
    import multivoz as mv
    if not mv.apagar(slug):
        return jsonify({"erro": "Voz não encontrada."}), 404
    return jsonify({"ok": True, "vozes": _vozes_json(), "instrucao_ia": mv.instrucao_para_ia()})


@app.route("/gerar-voz/vozes/conferir", methods=["POST"])
def multivoz_conferir():
    """Como o texto vai ser dividido entre as vozes (prévia ao digitar)."""
    import multivoz as mv
    corpo = request.get_json(silent=True) or {}
    vozes = mv.por_slug()
    d = mv.dividir(str(corpo.get("texto") or ""), vozes)
    for f in d["falas"]:
        v = vozes.get(f["slug"]) if f["slug"] else None
        f["nome"] = v["nome"] if v else "voz padrão"
        f["cor"] = v["cor"] if v else "#9AA0A6"
    return jsonify({"ok": True, **d})


@app.route("/gerar-voz/vozes/<slug>/testar", methods=["POST"])
def multivoz_testar(slug: str):
    """Gera uma frase curta com a voz (pra ouvir antes de usar)."""
    import multivoz as mv
    v = mv.por_slug().get(slug)
    if not v:
        return jsonify({"erro": "Voz não encontrada."}), 404
    motor, kwargs = mv.kwargs_da_voz(v)
    texto = (request.get_json(silent=True) or {}).get("texto") or f"Olá, eu sou {v['nome']}. Esta é a minha voz."
    job_id = uuid.uuid4().hex
    _GERAR_VOZ_STATUS[job_id] = {"running": True, "log": "", "erro": None, "pronto": False, "engine": motor,
                                 "resultado_filename": None, "resultado_srt_filename": None}

    def _run():
        st = _GERAR_VOZ_STATUS[job_id]
        try:
            out = os.path.join(VOZES_DIR, f"teste_{slug}_{job_id[:8]}.wav")
            tts_gerar_audio_isolado(motor, na.limpar_texto_para_tts(texto, motor=motor), out, **kwargs)
            st["resultado_filename"] = os.path.basename(out)
        except Exception as exc:  # noqa: BLE001
            st["erro"] = str(exc)
        finally:
            st["running"], st["pronto"] = False, True
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/gerar-voz/em-andamento", methods=["GET"])
def gerar_voz_em_andamento():
    """Gerações rodando (e as que terminaram na última hora) — a página do Gerar voz
    usa pra voltar a acompanhar depois de recarregar/fechar a aba."""
    agora = time.time()
    itens = []
    for jid, st in list(_GERAR_VOZ_STATUS.items()):
        criado = st.get("criado_em") or 0
        if st.get("running") or agora - criado < 3600:
            itens.append({"job_id": jid, "running": bool(st.get("running")), "erro": bool(st.get("erro")),
                          "pronto": bool(st.get("pronto")) and not st.get("erro"), "engine": st.get("engine"),
                          "criado_em": criado, "texto_inicio": st.get("texto_inicio") or "", "palavras": st.get("palavras"),
                          "na_fila": bool(st.get("na_fila")), "posicao": st.get("posicao"), "cancelado": bool(st.get("cancelado")),
                          "iniciou_em": st.get("iniciou_em")})
    itens.sort(key=lambda x: (not (x["running"] and not x["na_fila"]), not x["na_fila"], x["posicao"] or 0, -x["criado_em"]))
    return jsonify({"geracoes": itens[:30], "fila": _FILA_VOZ.estado()})


@app.route("/gerar-voz/fila", methods=["GET"])
def gerar_voz_fila():
    e = _FILA_VOZ.estado()
    e["vram_gb"] = _fila_voz.VRAM_GB
    return jsonify(e)


@app.route("/gerar-voz/fila/config", methods=["POST"])
def gerar_voz_fila_config():
    modo = str((request.get_json(silent=True) or request.form).get("modo") or "auto")
    if modo not in _fila_voz.MODOS:
        return jsonify({"erro": "Use auto, 1, 2 ou 3."}), 400
    cfg = load_site_config()
    cfg["voz_simultaneos"] = modo
    save_site_config(cfg)
    return jsonify(dict(_FILA_VOZ.estado(), ok=True))


@app.route("/gerar-voz/instancias/config", methods=["POST"])
def gerar_voz_instancias_config():
    """⚡ Quantas instâncias do motor geram cada áudio (auto, 1–4) — vale no Gerador de voz e no Roteiro para Áudio."""
    import tts_paralelo
    modo = str((request.get_json(silent=True) or request.form).get("modo") or "auto")
    if modo not in tts_paralelo.MODOS:
        return jsonify({"erro": "Use auto, 1, 2, 3 ou 4."}), 400
    cfg = load_site_config()
    cfg["voz_instancias"] = modo
    save_site_config(cfg)
    return jsonify({"ok": True, "modo": modo})


@app.route("/gerar-voz/instancias/previa", methods=["GET"])
def gerar_voz_instancias_previa():
    """Quantas instâncias o automático usaria agora (pra mostrar do lado da opção)."""
    import tts_paralelo
    engine = str(request.args.get("engine") or "chatterbox_turbo")
    n, por_que = tts_paralelo.escolher(engine, str(request.args.get("modo") or tts_paralelo.modo_salvo()),
                                       request.args.get("cpu") == "1", int(request.args.get("caracteres") or 20000))
    return jsonify({"instancias": n, "motivo": por_que, "modo": tts_paralelo.modo_salvo(), **tts_paralelo.recursos()})


@app.route("/gerar-voz/cancelar/<job_id>", methods=["POST"])
def gerar_voz_cancelar(job_id: str):
    """Tira da fila (o que já está gerando termina)."""
    st = _GERAR_VOZ_STATUS.get(job_id)
    if not st or not _FILA_VOZ.cancelar(job_id):
        return jsonify({"erro": "Essa geração não está mais na fila (já começou ou terminou)."}), 400
    st.update(running=False, pronto=True, na_fila=False, posicao=None, cancelado=True, erro="Cancelada antes de começar.")
    st["log"] = (st.get("log") or "") + "✖ Cancelada.\n"
    return jsonify({"ok": True})


@app.route("/gerar-voz/historico", methods=["GET"])
def gerar_voz_historico():
    try:
        pagina = max(0, int(request.args.get("pagina") or 0))
    except ValueError:
        pagina = 0
    r = _hist_voz.listar(VOZES_DIR, q=request.args.get("q") or "", limite=50, pagina=pagina)
    for it in r["itens"]:
        if it.get("arquivo") and not it.get("sumiu"):
            it["audio_url"] = url_for("gerar_voz_audio", filename=it["arquivo"])
            if not it.get("erro"):
                it["zip_url"] = url_for("gerar_voz_baixar_zip", job_id=it["id"])
        if it.get("srt") and os.path.exists(os.path.join(VOZES_DIR, it["srt"])):
            it["srt_url"] = url_for("gerar_voz_legenda", filename=it["srt"])
    return jsonify(r)


@app.route("/gerar-voz/historico/<job_id>/apagar", methods=["POST"])
def gerar_voz_historico_apagar(job_id: str):
    st = _GERAR_VOZ_STATUS.get(job_id)
    if st and st.get("running"):
        return jsonify({"erro": "Ainda está gerando."}), 409
    if not _hist_voz.apagar(VOZES_DIR, job_id):
        return jsonify({"erro": "Não achei esse áudio no histórico."}), 404
    _GERAR_VOZ_STATUS.pop(job_id, None)
    return jsonify({"ok": True})


@app.route("/gerar-voz/status/<job_id>", methods=["GET"])
def gerar_voz_status(job_id: str):
    status = _GERAR_VOZ_STATUS.get(job_id)
    if not status:
        h = _hist_voz.obter(VOZES_DIR, job_id)  # o site reiniciou: o histórico ainda sabe do áudio
        if h and h.get("arquivo") and os.path.exists(os.path.join(VOZES_DIR, h["arquivo"])):
            res = {"audio_url": url_for("gerar_voz_audio", filename=h["arquivo"]), "engine": h.get("motor"), "idioma": h.get("idioma")}
            if not h.get("erro"):
                res["zip_url"] = url_for("gerar_voz_baixar_zip", job_id=job_id)
            if h.get("srt") and os.path.exists(os.path.join(VOZES_DIR, h["srt"])):
                res["srt_url"] = url_for("gerar_voz_legenda", filename=h["srt"])
            return jsonify({"running": False, "log": "(do histórico)", "erro": None, "pronto": True, "resultado": res})
        return jsonify({"running": False, "log": "", "erro": "Essa geração não foi encontrada.", "pronto": True, "resultado": None})
    resultado = None
    if status.get("resultado_filename"):
        resultado = {
            "audio_url": url_for("gerar_voz_audio", filename=status["resultado_filename"]),
            "engine": status.get("engine"),
            "idioma": status.get("idioma"), "idioma_origem": status.get("idioma_origem"),
            "idioma_nome": __import__("idiomas").nome(status.get("idioma")) if status.get("idioma") else None,
        }
        if status.get("resultado_srt_filename"):
            resultado["srt_url"] = url_for("gerar_voz_legenda", filename=status["resultado_srt_filename"])
        if status.get("resultado_srt_filename") or status.get("chamadas"):
            resultado["zip_url"] = url_for("gerar_voz_baixar_zip", job_id=job_id)
        if status.get("chamadas"):
            import chamadas as _chm
            resultado["chamadas"] = [dict(c, rotulo=_chm.rotulo(c["tipo"])) for c in status["chamadas"]]
        if status.get("roteiro_descricao"):
            resultado["roteiro_descricao"] = status["roteiro_descricao"]
            resultado["roteiro_url"] = (f"/roteiros-yt/{status.get('roteiro_id')}" if status.get("roteiro_id")
                                        else f"/modelos-video/{status.get('dossie_id')}")
    return jsonify({
        "running": status["running"], "log": status["log"], "erro": status["erro"],
        "pronto": status["pronto"], "resultado": resultado,
        "na_fila": bool(status.get("na_fila")), "posicao": status.get("posicao"),
    })


# --------------------------------------------------------------------- #
# Simular Conversa — várias falas em sequência, CADA UMA com motor/voz
# próprios (diferente do Roteiro para Áudio, que usa um motor só pro
# projeto inteiro) — pensado pra simular um diálogo entre "pessoas"
# diferentes. Gera cada fala individualmente (dá pra baixar uma por
# uma) e/ou combina tudo num único áudio.
# --------------------------------------------------------------------- #

def _conversa_ctx_comuns() -> Dict[str, Any]:
    return {
        "engines": tts_ENGINES,
        "piper_vozes": tts_PIPER_VOZES_SUGERIDAS,
        "xtts_checkpoints": tts_XTTS_CHECKPOINTS_CONHECIDOS,
        "kokoro_vozes": tts_KOKORO_VOZES,
        "perfis_de_voz": tts_listar_perfis_de_voz(),
    }


@app.route("/gerar-voz/conversa", methods=["GET"])
def conversa_lista():
    return render_template("conversa_lista.html", conversas=cv.listar_conversas(BASE_DIR))


@app.route("/gerar-voz/conversa", methods=["POST"])
def conversa_criar():
    nome = request.form.get("nome", "")
    nova = cv.criar_conversa(BASE_DIR, nome)
    return redirect(url_for("conversa_detalhe", conversa_id=nova["conversaId"]))


@app.route("/gerar-voz/conversa/<conversa_id>", methods=["GET"])
def conversa_detalhe(conversa_id: str):
    if not cv.conversa_existe(BASE_DIR, conversa_id):
        return "Conversa não encontrada.", 404
    conversa = cv.carregar_conversa(BASE_DIR, conversa_id)
    return render_template("conversa_detalhe.html", conversa=conversa, error=None, **_conversa_ctx_comuns())


@app.route("/gerar-voz/conversa/<conversa_id>/renomear", methods=["POST"])
def conversa_renomear(conversa_id: str):
    try:
        cv.renomear_conversa(BASE_DIR, conversa_id, request.form.get("nome", ""))
    except cv.ConversaError:
        pass
    return redirect(url_for("conversa_detalhe", conversa_id=conversa_id))


@app.route("/gerar-voz/conversa/<conversa_id>/excluir", methods=["POST"])
def conversa_excluir(conversa_id: str):
    cv.excluir_conversa(BASE_DIR, conversa_id)
    return redirect(url_for("conversa_lista"))


@app.route("/gerar-voz/conversa/<conversa_id>/pausa", methods=["POST"])
def conversa_salvar_pausa(conversa_id: str):
    try:
        cv.salvar_pausa(BASE_DIR, conversa_id, request.form.get("pausa_segundos", 0.6))
    except cv.ConversaError:
        pass
    return redirect(url_for("conversa_detalhe", conversa_id=conversa_id))


@app.route("/gerar-voz/conversa/<conversa_id>/fala", methods=["POST"])
def conversa_adicionar_fala(conversa_id: str):
    try:
        cv.adicionar_fala(
            BASE_DIR, conversa_id,
            texto=request.form.get("texto", ""), motor=request.form.get("motor", "piper"),
            voz=request.form.get("voz", ""), velocidade=float(request.form.get("velocidade", 1.0) or 1.0),
            idioma=request.form.get("idioma", ""),
        )
    except cv.ConversaError as exc:
        conversa = cv.carregar_conversa(BASE_DIR, conversa_id)
        return render_template("conversa_detalhe.html", conversa=conversa, error=str(exc), **_conversa_ctx_comuns())
    return redirect(url_for("conversa_detalhe", conversa_id=conversa_id))


@app.route("/gerar-voz/conversa/<conversa_id>/fala/<fala_id>/editar", methods=["POST"])
def conversa_editar_fala(conversa_id: str, fala_id: str):
    try:
        cv.editar_fala(
            BASE_DIR, conversa_id, fala_id,
            texto=request.form.get("texto"), motor=request.form.get("motor"),
            voz=request.form.get("voz"), idioma=request.form.get("idioma"),
            velocidade=float(request.form["velocidade"]) if request.form.get("velocidade") else None,
        )
    except cv.ConversaError:
        pass
    return redirect(url_for("conversa_detalhe", conversa_id=conversa_id))


@app.route("/gerar-voz/conversa/<conversa_id>/fala/<fala_id>/excluir", methods=["POST"])
def conversa_excluir_fala(conversa_id: str, fala_id: str):
    cv.remover_fala(BASE_DIR, conversa_id, fala_id)
    return redirect(url_for("conversa_detalhe", conversa_id=conversa_id))


@app.route("/gerar-voz/conversa/<conversa_id>/fala/<fala_id>/mover", methods=["POST"])
def conversa_mover_fala(conversa_id: str, fala_id: str):
    try:
        cv.mover_fala(BASE_DIR, conversa_id, fala_id, request.form.get("direcao", ""))
    except cv.ConversaError:
        pass
    return redirect(url_for("conversa_detalhe", conversa_id=conversa_id))


@app.route("/gerar-voz/conversa/<conversa_id>/fala/<fala_id>/gerar", methods=["POST"])
def conversa_gerar_fala(conversa_id: str, fala_id: str):
    chave = f"{conversa_id}:{fala_id}"
    _CONVERSA_FALA_STATUS[chave] = {"running": True, "erro": None, "pronto": False}

    def _run():
        status = _CONVERSA_FALA_STATUS[chave]
        try:
            cv.gerar_audio_fala(BASE_DIR, conversa_id, fala_id)
        except cv.ConversaError as exc:
            status["erro"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            status["erro"] = f"Falha inesperada: {exc}"
        finally:
            status["running"] = False
            status["pronto"] = True
            if status["erro"]:
                _avisar("❌ Conversa — uma fala deu erro", status["erro"], f"/gerar-voz/conversa/{conversa_id}", "erro", "conversa")
            else:
                _avisar("✅ Conversa — fala gerada", "", f"/gerar-voz/conversa/{conversa_id}", "ok", "conversa", chave=f"conversa:{conversa_id}")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/gerar-voz/conversa/<conversa_id>/fala/<fala_id>/status", methods=["GET"])
def conversa_status_fala(conversa_id: str, fala_id: str):
    chave = f"{conversa_id}:{fala_id}"
    status = _CONVERSA_FALA_STATUS.get(chave)
    if not status:
        return jsonify({"running": False, "pronto": True, "erro": None})
    return jsonify(status)


@app.route("/gerar-voz/conversa/<conversa_id>/fala/<fala_id>/audio", methods=["GET"])
def conversa_audio_fala(conversa_id: str, fala_id: str):
    try:
        caminho = cv.caminho_audio_fala(BASE_DIR, conversa_id, fala_id)
    except cv.ConversaError:
        return "Áudio não encontrado.", 404
    return send_file(str(caminho), mimetype="audio/wav")


@app.route("/gerar-voz/conversa/<conversa_id>/gerar-tudo", methods=["POST"])
def conversa_gerar_tudo(conversa_id: str):
    try:
        resultado = cv.gerar_audio_completo(BASE_DIR, conversa_id)
    except cv.ConversaError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "duracaoSegundos": resultado["duracaoSegundos"], "quantidadeFalas": resultado["quantidadeFalas"]})


@app.route("/gerar-voz/conversa/<conversa_id>/completo", methods=["GET"])
def conversa_audio_completo(conversa_id: str):
    try:
        caminho = cv.caminho_audio_completo(BASE_DIR, conversa_id)
    except cv.ConversaError:
        return "Ainda não foi gerado um áudio combinado.", 404
    return send_file(str(caminho), as_attachment=True, download_name=f"conversa_{conversa_id}.mp3")


@app.route("/gerar-voz/perfis/<nome>/excluir", methods=["POST"])
def gerar_voz_excluir_perfil(nome: str):
    tts_excluir_perfil_de_voz(nome)
    return redirect(url_for("gerar_voz_page"))


# --------------------------------------------------------------------- #
# Perfis de voz — aba dedicada pra criar/gerenciar perfis de clonagem
# do XTTS (upload de um ou mais áudios + nome), separada do fluxo
# rápido de geração. Aqui dá pra mandar VÁRIOS clipes de uma vez, ou um
# áudio único que o site divide sozinho em trechos espalhados (ver
# `dividir_audio_em_clipes` em voice_generator.py) em vez de só
# aproveitar o começo dele.
# --------------------------------------------------------------------- #

@app.route("/perfis-de-voz", methods=["GET"])
def perfis_de_voz_page():
    perfis = []
    for nome in tts_listar_perfis_de_voz():
        try:
            clipes = tts_caminho_perfil_de_voz(nome)
        except VoiceGeneratorError:
            clipes = []
        perfis.append({"nome": nome, "quantidade_clipes": len(clipes)})
    return render_template(
        "perfis_de_voz.html", perfis=_perfis_com_info(perfis), max_clipes=tts_MAX_CLIPES_POR_PERFIL, error=None,
    )


def _perfis_com_info(perfis: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta gênero/idade/descrição (perfis_info.py) e as vozes com slug que usam cada perfil."""
    import multivoz as mv
    import perfis_info
    info = perfis_info.todos()
    usos: Dict[str, List[str]] = {}
    for v in mv.listar():
        pf = (v.get("config") or {}).get("vozPerfil")
        if pf:
            usos.setdefault(pf, []).append(v["slug"])
    import perfis_limpeza
    out = []
    for p in perfis:
        lp = perfis_limpeza.info(p["nome"])
        out.append(dict(p, genero=(info.get(p["nome"]) or {}).get("genero", ""), idade=(info.get(p["nome"]) or {}).get("idade", ""),
                        descricao=(info.get(p["nome"]) or {}).get("descricao", ""), vozes_slug=usos.get(p["nome"], []),
                        audio=lp["audio"], limpeza=lp["limpeza"], n_originais=len(perfis_limpeza.originais(p["nome"])),
                        clipes=_clipes_info(p["nome"])))
    return out


# ------------------------------------------------------------------ 🎧 voz limpa nos perfis (v84_92)
@app.route("/perfis-de-voz/<nome>/audio", methods=["POST"])
def perfis_de_voz_audio(nome: str):
    """🎧 Marca o perfil: {"audio": "limpo" | "musica" | ""}. Com 🎵 música: já começa a limpar (uma vez)."""
    import perfis_limpeza
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    audio = str((request.get_json(silent=True) or request.form).get("audio") or "")
    try:
        perfis_limpeza.marcar(nome, audio)
    except perfis_limpeza.LimpezaErro as exc:
        return jsonify({"erro": str(exc)}), 400
    tid = perfis_limpeza.iniciar(nome) if perfis_limpeza.precisa_limpar(nome) else None
    return jsonify({"ok": True, "tarefa": tid, **perfis_limpeza.info(nome)})


@app.route("/perfis-de-voz/<nome>/limpar", methods=["POST"])
def perfis_de_voz_limpar(nome: str):
    """🧹 Limpa agora (só os clipes ainda não limpos; {"forcar": true} refaz todos a partir dos originais)."""
    import perfis_limpeza
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    forcar = bool((request.get_json(silent=True) or {}).get("forcar"))
    return jsonify({"ok": True, "tarefa": perfis_limpeza.iniciar(nome, forcar=forcar), **perfis_limpeza.info(nome)})


@app.route("/perfis-de-voz/<nome>/restaurar", methods=["POST"])
def perfis_de_voz_restaurar(nome: str):
    """↩ Volta os clipes pros áudios como vieram (com a música de fundo)."""
    import perfis_limpeza
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    n = perfis_limpeza.restaurar(nome)
    return jsonify({"ok": True, "voltaram": n, **perfis_limpeza.info(nome)})


@app.route("/perfis-de-voz/<nome>/estado")
def perfis_de_voz_estado(nome: str):
    import perfis_limpeza
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    return jsonify({"ok": True, **perfis_limpeza.info(nome), "n_originais": len(perfis_limpeza.originais(nome))})


@app.route("/perfis-de-voz/<nome>/original/<int:indice>")
def perfis_de_voz_original(nome: str, indice: int):
    """O clipe como veio (antes da limpeza) — pra comparar."""
    import perfis_limpeza
    try:
        lista = perfis_limpeza.clipes(nome)
    except Exception:  # noqa: BLE001
        return "Perfil não encontrado.", 404
    if not (0 <= indice < len(lista)):
        return "Clipe não encontrado.", 404
    o = os.path.join(os.path.dirname(lista[indice]), perfis_limpeza.PASTA_ORIGINAL, os.path.basename(lista[indice]))
    if not os.path.isfile(o):
        return "Esse clipe não foi limpo.", 404
    return send_file(o, mimetype="audio/wav")


# ------------------------------------------------------------------ ✂ clipe a clipe (v84_174)
def _limpeza_sem(nome: str, base: str) -> None:
    """Tira o clipe apagado da lista de "já limpos" — um clipe novo com o mesmo nome tem de ser limpo de novo."""
    import perfis_info
    lp = dict((perfis_info.obter(nome) or {}).get("limpeza") or {})
    if base in (lp.get("clipes") or []):
        lp["clipes"] = [c for c in lp["clipes"] if c != base]
        perfis_info.atualizar(nome, limpeza=lp)


@app.route("/perfis-de-voz/<nome>/clipe/<int:indice>/excluir", methods=["POST"])
def perfis_de_voz_clipe_excluir(nome: str, indice: int):
    """🗑 Apaga UM clipe ruim do perfil (e o original dele)."""
    from tts import voice_generator as _vg
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    try:
        base = _vg.excluir_clipe_do_perfil(nome, indice)
    except VoiceGeneratorError as exc:
        return jsonify({"erro": str(exc)}), 400
    _limpeza_sem(nome, base)
    return jsonify({"ok": True, "apagado": base, "clipes": _clipes_info(nome)})


@app.route("/perfis-de-voz/<nome>/clipe/<int:indice>/principal", methods=["POST"])
def perfis_de_voz_clipe_principal(nome: str, indice: int):
    """⭐ Esse clipe vai primeiro — é o único que o Chatterbox usa."""
    from tts import voice_generator as _vg
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    try:
        _vg.definir_clipe_principal(nome, indice)
    except VoiceGeneratorError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "clipes": _clipes_info(nome)})


@app.route("/perfis-de-voz/<nome>/adicionar", methods=["POST"])
def perfis_de_voz_adicionar(nome: str):
    """➕ Junta mais áudio(s)/vídeo(s) no perfil sem apagar os clipes que ele já tem."""
    from tts import voice_generator as _vg
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    arquivos = [f for f in request.files.getlist("audios") if f and f.filename]
    if not arquivos:
        return jsonify({"erro": "Escolha pelo menos um áudio ou vídeo."}), 400
    if len(arquivos) > tts_MAX_CLIPES_POR_PERFIL:
        return jsonify({"erro": f"No máximo {tts_MAX_CLIPES_POR_PERFIL} arquivos de uma vez."}), 400
    os.makedirs(VOZES_DIR, exist_ok=True)
    tmps = []
    try:
        for arq in arquivos:
            t = os.path.join(VOZES_DIR, f"perfiladd_{uuid.uuid4().hex}_{secure_filename(arq.filename) or 'audio'}")
            arq.save(t)
            tmps.append(t)
        origem = tmps[0] if len(tmps) == 1 else tmps
        novos = _vg.adicionar_clipes_ao_perfil(nome, origem, dividir_audio_longo=request.form.get("dividir", "on") == "on")
    except VoiceGeneratorError as exc:
        return jsonify({"erro": str(exc)}), 400
    finally:
        for t in tmps:
            try:
                os.remove(t)
            except OSError:
                pass
    import perfis_limpeza
    tid = perfis_limpeza.iniciar(nome) if perfis_limpeza.precisa_limpar(nome) else None  # 🎵 perfil com música: limpa só os novos
    return jsonify({"ok": True, "adicionados": len(novos), "tarefa": tid, "clipes": _clipes_info(nome)})


def _clipes_info(nome: str) -> List[Dict[str, Any]]:
    """[{indice, arquivo, segundos, principal}] na ordem da página (o ⭐ primeiro)."""
    from tts import voice_generator as _vg
    try:
        lista = tts_caminho_perfil_de_voz(nome)
    except VoiceGeneratorError:
        return []
    return [{"indice": i, "arquivo": os.path.basename(c), "segundos": _vg.duracao_wav(c), "principal": i == 0}
            for i, c in enumerate(lista)]


@app.route("/perfis-de-voz/<nome>/info", methods=["POST"])
def perfis_de_voz_info(nome: str):
    """Gênero (masculino/feminino/neutro), idade (criança/jovem/adulto/idoso) e
    descrição de um perfil — as vozes com slug que usam o perfil herdam isso."""
    import perfis_info
    if nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": "Perfil não encontrado."}), 404
    corpo = request.get_json(silent=True) or request.form
    try:
        info = perfis_info.definir(nome, corpo.get("genero"), corpo.get("idade"), corpo.get("descricao"))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "info": info})


@app.route("/perfis-de-voz/criar", methods=["POST"])
def perfis_de_voz_criar():
    nome = request.form.get("nome", "").strip()
    arquivos = [f for f in request.files.getlist("audios") if f and f.filename]
    dividir_automaticamente = request.form.get("dividir_automaticamente") == "on"

    if not nome:
        perfis = [{"nome": n, "quantidade_clipes": len(tts_caminho_perfil_de_voz(n))} for n in tts_listar_perfis_de_voz()]
        return render_template(
            "perfis_de_voz.html", perfis=perfis, max_clipes=tts_MAX_CLIPES_POR_PERFIL,
            error="Dê um nome pro perfil antes de salvar.",
        )
    if not arquivos:
        perfis = [{"nome": n, "quantidade_clipes": len(tts_caminho_perfil_de_voz(n))} for n in tts_listar_perfis_de_voz()]
        return render_template(
            "perfis_de_voz.html", perfis=perfis, max_clipes=tts_MAX_CLIPES_POR_PERFIL,
            error="Envie pelo menos um arquivo de áudio.",
        )

    caminhos_temporarios = []
    try:
        for arquivo in arquivos:
            safe_name = secure_filename(arquivo.filename)
            caminho_tmp = os.path.join(VOZES_DIR, f"perfilupload_{uuid.uuid4().hex}_{safe_name}")
            arquivo.save(caminho_tmp)
            caminhos_temporarios.append(caminho_tmp)

        origem = caminhos_temporarios[0] if len(caminhos_temporarios) == 1 else caminhos_temporarios
        tts_salvar_perfil_de_voz(nome, origem, dividir_audio_longo=dividir_automaticamente)
        if request.form.get("audio") in ("limpo", "musica"):  # 🎧 com música de fundo: limpa uma vez, em segundo plano
            import perfis_limpeza
            from tts.voice_generator import _nome_perfil_seguro as _nps
            perfis_limpeza.marcar(_nps(nome), request.form["audio"])
            if request.form["audio"] == "musica":
                perfis_limpeza.iniciar(_nps(nome))
        if any(request.form.get(k) for k in ("genero", "idade", "descricao")):
            import perfis_info
            from tts.voice_generator import _nome_perfil_seguro
            nome_salvo = _nome_perfil_seguro(nome)  # o mesmo nome que o perfil recebeu na pasta
            try:
                perfis_info.definir(nome_salvo, request.form.get("genero") or "", request.form.get("idade") or "",
                                    request.form.get("descricao") or "")
            except ValueError:
                pass
    except VoiceGeneratorError as exc:
        perfis = [{"nome": n, "quantidade_clipes": len(tts_caminho_perfil_de_voz(n))} for n in tts_listar_perfis_de_voz()]
        return render_template(
            "perfis_de_voz.html", perfis=perfis, max_clipes=tts_MAX_CLIPES_POR_PERFIL, error=str(exc),
        )
    finally:
        for caminho in caminhos_temporarios:
            try:
                os.remove(caminho)
            except OSError:
                pass

    return redirect(url_for("perfis_de_voz_page"))


# ------------------------------------------------------------------ 📦 exportar / importar perfis em .zip
@app.route("/perfis-de-voz/exportar", methods=["GET"])
def perfis_de_voz_exportar():
    """📦 Baixa um .zip com os perfis (?nomes=a&nomes=b; sem nomes = todos) — clipes, originais e informações."""
    import perfis_pacote
    nomes = [n for n in request.args.getlist("nomes") if n.strip()]
    try:
        dados = perfis_pacote.exportar(nomes or None)
    except (perfis_pacote.PacoteErro, VoiceGeneratorError) as exc:
        return str(exc), 404
    import io
    if len(nomes) == 1:
        rotulo = secure_filename(nomes[0]) or "perfil"
    else:
        rotulo = f"{len(nomes)}_perfis" if nomes else "todos"
    nome_arq = f"perfis_de_voz_{rotulo}_{time.strftime('%Y%m%d_%H%M')}.zip"
    return send_file(io.BytesIO(dados),mimetype="application/zip", as_attachment=True, download_name=nome_arq)


@app.route("/perfis-de-voz/<nome>/exportar", methods=["GET"])
def perfis_de_voz_exportar_um(nome: str):
    return redirect(url_for("perfis_de_voz_exportar", nomes=nome))


@app.route("/perfis-de-voz/importar", methods=["POST"])
def perfis_de_voz_importar():
    """📦 Importa um .zip: exportado daqui (com manifesto.json) ou só com áudios (raiz = 1 perfil; pastas = 1 por pasta)."""
    import perfis_pacote
    arquivo = request.files.get("zip")
    quer_json = request.headers.get("Accept", "").startswith("application/json") or request.args.get("json") == "1"

    def _erro(msg: str):
        if quer_json:
            return jsonify({"erro": msg}), 400
        perfis = [{"nome": n, "quantidade_clipes": len(tts_caminho_perfil_de_voz(n))} for n in tts_listar_perfis_de_voz()]
        return render_template("perfis_de_voz.html", perfis=_perfis_com_info(perfis), max_clipes=tts_MAX_CLIPES_POR_PERFIL, error=msg)

    if not arquivo or not arquivo.filename:
        return _erro("Escolha um arquivo .zip pra importar.")
    if not arquivo.filename.lower().endswith(".zip"):
        return _erro("O arquivo precisa ser um .zip.")
    tmp = os.path.join(VOZES_DIR, f"perfilimport_{uuid.uuid4().hex}.zip")
    os.makedirs(VOZES_DIR, exist_ok=True)
    try:
        arquivo.save(tmp)
        res = perfis_pacote.importar(
            tmp, nome=request.form.get("nome", ""), substituir=request.form.get("substituir") == "on",
            dividir=request.form.get("dividir_automaticamente", "on") == "on", nome_zip=arquivo.filename,
        )
    except (perfis_pacote.PacoteErro, VoiceGeneratorError) as exc:
        return _erro(str(exc))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if quer_json:
        return jsonify({"ok": True, "importados": res})
    return redirect(url_for("perfis_de_voz_page", importados=",".join(r["nome"] for r in res)))


@app.route("/perfis-de-voz/<nome>/excluir", methods=["POST"])
def perfis_de_voz_excluir(nome: str):
    tts_excluir_perfil_de_voz(nome)
    __import__("perfis_info").remover(nome)
    return redirect(url_for("perfis_de_voz_page"))


@app.route("/perfis-de-voz/<nome>/clipe/<int:indice>", methods=["GET"])
def perfis_de_voz_clipe(nome: str, indice: int):
    try:
        clipes = tts_caminho_perfil_de_voz(nome)
    except VoiceGeneratorError:
        return "Perfil não encontrado.", 404
    if not (0 <= indice < len(clipes)):
        return "Clipe não encontrado.", 404
    return send_file(clipes[indice], mimetype="audio/wav")


# job_id -> {"status", "log", "erro", "criado_em", "quantidade_clipes", "nome_perfil"}
_PERFIL_YOUTUBE_JOBS: Dict[str, Dict[str, Any]] = {}


@app.route("/perfis-de-voz/youtube/buscar", methods=["GET"])
def perfis_de_voz_youtube_buscar():
    """Mesma busca do Cortar do YouTube — reaproveitada aqui pra achar
    o vídeo de onde extrair a voz."""
    termo = (request.args.get("termo") or "").strip()
    if not termo:
        return jsonify({"erro": "Digite um termo de busca."}), 400
    try:
        pular = int(request.args.get("pular") or 0) if str(request.args.get("pular") or "0").isdigit() else 0
        resultados = (buscar_videos_youtube(termo, quantidade=12, pular=pular) if pular  # ➕ "Buscar outros vídeos"
                      else buscar_videos_youtube(termo, quantidade=15))
    except YoutubeClipperError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada na busca:\n{traceback.format_exc()}"}), 500
    return jsonify({"ok": True, "resultados": resultados})


@app.route("/perfis-de-voz/youtube/extrair", methods=["POST"])
def perfis_de_voz_youtube_extrair():
    """Baixa vídeo(s) do YouTube, corta os trechos marcados, e já salva
    tudo direto como um perfil de voz — sem precisar baixar/editar o
    áudio manualmente antes."""
    corpo = request.get_json(silent=True) or {}
    nome = (corpo.get("nome") or "").strip()
    itens = corpo.get("itens") or []
    qualidade = (corpo.get("qualidade") or YT_QUALIDADE_PADRAO).strip()
    audio_tipo = corpo.get("audio") if corpo.get("audio") in ("limpo", "musica") else ""  # 🎧
    adicionar = bool(corpo.get("adicionar"))  # ➕ juntar num perfil que já existe (v84_174)

    if not nome:
        return jsonify({"erro": "Dê um nome pro perfil antes de extrair."}), 400
    if adicionar and nome not in tts_listar_perfis_de_voz():
        return jsonify({"erro": f"O perfil {nome!r} não existe — escolha um da lista."}), 400
    if not itens:
        return jsonify({"erro": "Adicione pelo menos um vídeo com um trecho."}), 400

    job_id = uuid.uuid4().hex[:12]
    _PERFIL_YOUTUBE_JOBS[job_id] = {
        "id": job_id, "status": "processando", "log": "", "erro": None,
        "criado_em": time.time(), "nome_perfil": nome, "quantidade_clipes": None,
    }

    def _run():
        job = _PERFIL_YOUTUBE_JOBS[job_id]

        def log(linha: str) -> None:
            job["log"] += linha + "\n"

        try:
            salvos = yt_extrair_perfil_de_voz_do_youtube(itens, nome, qualidade=qualidade, on_log=log, **({"adicionar": True} if adicionar else {}))
            import perfis_limpeza
            from tts.voice_generator import _nome_perfil_seguro as _nps
            if audio_tipo and not (adicionar and audio_tipo == "limpo"):  # ➕ juntando: "limpo" não desmarca o 🎵 do perfil
                perfis_limpeza.marcar(_nps(nome), audio_tipo)
            if perfis_limpeza.precisa_limpar(_nps(nome)):  # 🎵 com música de fundo: limpa os clipes agora (uma vez)
                try:
                    perfis_limpeza.limpar(_nps(nome), log=log)
                except Exception as exc:  # noqa: BLE001 — o perfil fica criado; dá pra limpar depois na página
                    log(f"⚠ Não consegui limpar a música de fundo: {exc}")
            job["status"] = "pronto"
            job["quantidade_clipes"] = len(tts_caminho_perfil_de_voz(nome)) if adicionar else len(salvos)
            job["adicionados"] = len(salvos)
        except (YoutubeClipperError, VoiceGeneratorError) as exc:
            job["status"] = "erro"
            job["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            job["status"] = "erro"
            job["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"

    _thread_com_aviso(_run, lambda: _PERFIL_YOUTUBE_JOBS.get(job_id), f"🗣️ Perfil de voz “{nome}” do YouTube", "/perfis-de-voz", "perfil_voz")
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/perfis-de-voz/youtube/<job_id>/status", methods=["GET"])
def perfis_de_voz_youtube_status(job_id: str):
    job = _PERFIL_YOUTUBE_JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "job não encontrado"}), 404
    return jsonify({
        "status": job["status"], "erro": job.get("erro"), "log": job.get("log", ""),
        "nome_perfil": job.get("nome_perfil"), "quantidade_clipes": job.get("quantidade_clipes"),
        "adicionados": job.get("adicionados"),
    })


@app.route("/gerar-voz/piper-vozes", methods=["GET"])
def gerar_voz_piper_buscar_vozes():
    """Busca no catálogo COMPLETO de vozes do Piper (centenas delas,
    baixado do repositório oficial na primeira vez e depois cacheado)
    — usado pela busca "ao vivo" na página do Gerador de Voz.
    """
    busca = request.args.get("q", "").strip()
    idioma = request.args.get("idioma", "").strip()
    qualidade = request.args.get("qualidade", "").strip()
    try:
        resultados = tts_piper_search_voices(busca=busca, idioma=idioma, qualidade=qualidade, max_resultados=40)
    except VoiceGeneratorError as exc:
        return jsonify({"erro": str(exc), "resultados": []}), 502
    return jsonify({"erro": None, "resultados": resultados})


@app.route("/gerar-voz/piper-vozes/baixar", methods=["POST"])
def gerar_voz_piper_baixar_voz():
    """Baixa uma voz do Piper AGORA (sem gerar áudio nenhum ainda) —
    botão "baixar" nos resultados da busca, pra próxima geração com
    essa voz não precisar esperar o download."""
    nome_voz = request.form.get("nome_voz", "").strip()
    if not nome_voz:
        return jsonify({"erro": "Informe o nome da voz."}), 400
    try:
        resultado = tts_piper_download_voice_now(nome_voz)
    except VoiceGeneratorError as exc:
        return jsonify({"erro": str(exc)}), 502
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada ao baixar: {exc}"}), 500
    return jsonify({"erro": None, "resultado": resultado})


@app.route("/gerar-voz/audio/<filename>", methods=["GET"])
def gerar_voz_audio(filename: str):
    # secure_filename também no GET: o nome vem de um uuid4().hex gerado
    # por nós mesmos, mas nunca custa evitar um path traversal aqui.
    safe_name = secure_filename(filename)
    path = os.path.join(VOZES_DIR, safe_name)
    if not os.path.exists(path):
        return "Áudio não encontrado.", 404
    return send_file(path, mimetype="audio/wav")


@app.route("/gerar-voz/legenda/<filename>", methods=["GET"])
def gerar_voz_legenda(filename: str):
    safe_name = secure_filename(filename)
    path = os.path.join(VOZES_DIR, safe_name)
    if not os.path.exists(path):
        return "Legenda não encontrada.", 404
    return send_file(path, mimetype="text/plain", as_attachment=True, download_name=safe_name)


def _status_do_historico_voz(job_id: str) -> Optional[Dict[str, Any]]:
    """Monta, a partir da entrada do 📜 histórico, o mesmo que o zip precisa do status da geração."""
    h = _hist_voz.obter(VOZES_DIR, job_id)
    if not h or not h.get("arquivo") or h.get("erro"):
        return None
    st: Dict[str, Any] = {"resultado_filename": h["arquivo"], "resultado_srt_filename": h.get("srt"),
                          "resultado_chamadas_filename": h.get("chamadas"),
                          "idioma": h.get("idioma") or None, "engine": h.get("motor") or None}
    chave, _, valor = str(h.get("projeto") or "").partition(":")
    if chave in ("roteiro_id", "dossie_id", "venda_id") and valor:
        st[chave] = valor
    return st


@app.route("/gerar-voz/baixar-zip/<job_id>", methods=["GET"])
def gerar_voz_baixar_zip(job_id: str):
    if not re.fullmatch(r"[\w\-]+", job_id or ""):
        return "Essa geração não foi encontrada.", 404
    status = _GERAR_VOZ_STATUS.get(job_id)
    if not status or not status.get("resultado_filename"):
        status = _status_do_historico_voz(job_id)  # 📜 do histórico (o site reiniciou ou é um áudio antigo)
    if not status or not status.get("resultado_filename"):
        return "Essa geração não foi encontrada (ou ainda não terminou).", 404
    audio_path = os.path.join(VOZES_DIR, secure_filename(status["resultado_filename"]))
    if not os.path.exists(audio_path):
        return "Áudio não encontrado.", 404
    zip_path = _zip_da_voz(job_id, status)
    return send_file(zip_path, mimetype="application/zip", as_attachment=True, download_name="narracao_e_legenda.zip")


def _zip_da_voz(job_id: str, status: Dict[str, Any]) -> str:
    """O .zip de narração do Gerador de voz (narracao.wav + legenda.srt + info.json + chamadas.json) — o mesmo que
    o Novo vídeo aceita. Também usado pela 🏭 Produção no pod."""
    audio_path = os.path.join(VOZES_DIR, secure_filename(status["resultado_filename"]))
    zip_path = os.path.join(VOZES_DIR, f"{job_id}.zip")
    # monta o zip sob demanda (só na primeira vez que baixarem -- depois
    # reaproveita, já que áudio e legenda não mudam mais uma vez prontos)
    if not os.path.exists(zip_path):
        import idiomas
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(audio_path, arcname="narracao.wav")
            # idioma da narração: ao gerar o vídeo com este .zip, o site usa sozinho (ver _idioma_do_zip)
            zf.writestr("info.json", idiomas.info_json(status.get("idioma"), motor=status.get("engine"),
                                                        origem_idioma=status.get("idioma_origem"),
                                                        **({"venda_id": status["venda_id"]} if status.get("venda_id") else {}),
                                                        **({"dossie_id": status["dossie_id"]} if status.get("dossie_id") else {}),
                                                        **({"roteiro_id": status["roteiro_id"]} if status.get("roteiro_id") else {})))
            if status.get("resultado_chamadas_filename"):
                ch_path = os.path.join(VOZES_DIR, secure_filename(status["resultado_chamadas_filename"]))
                if os.path.exists(ch_path):
                    zf.write(ch_path, arcname="chamadas.json")  # o editor cria as chamadas sozinho (ver chamadas.py)
            srt_filename = status.get("resultado_srt_filename")
            if srt_filename:
                srt_path = os.path.join(VOZES_DIR, secure_filename(srt_filename))
                if os.path.exists(srt_path):
                    zf.write(srt_path, arcname="legenda.srt")
    return zip_path


# --------------------------------------------------------------------- #
# Roteiro para Áudio — projetos avulsos de narração (texto colado ->
# falas -> áudio final), SEM vídeo nenhum envolvido. Ver narracoes.py.
# --------------------------------------------------------------------- #

_NARRACAO_STATUS: Dict[str, Dict[str, Any]] = {}  # projeto_id -> {"running", "log", "erro", "pronto"}


def _narracao_ctx_comuns() -> Dict[str, Any]:
    """Dados que toda página do Roteiro para Áudio precisa pra montar os
    seletores de motor/voz — os mesmos usados na aba Gerador de Voz.
    """
    return dict(
        tts_engines=tts_ENGINES,
        piper_vozes=tts_PIPER_VOZES_SUGERIDAS,
        xtts_idiomas=sorted(tts_XTTS_IDIOMAS),
        xtts_checkpoints=tts_XTTS_CHECKPOINTS_CONHECIDOS,
        chatterbox_idiomas=sorted(tts_CHATTERBOX_IDIOMAS),
        kokoro_vozes=tts_KOKORO_VOZES,
        kokoro_variantes=tts_KOKORO_MODEL_VARIANTS,
        kokoro_precisoes=tts_KOKORO_PRECISIONS,
        perfis_de_voz=tts_listar_perfis_de_voz(),
        gpu=_gpu_cache()["gpu"],
        gpu_verificando=not _gpu_cache()["pronto"],
    )


@app.route("/narracoes", methods=["GET"])
def narracoes_page():
    projetos = na.listar_projetos(BASE_DIR)
    return render_template("narracoes.html", projetos=projetos)


@app.route("/narracoes", methods=["POST"])
def narracoes_criar():
    nome = request.form.get("nome", "").strip()
    projeto = na.criar_projeto(BASE_DIR, nome)
    return redirect(url_for("narracao_detalhe", projeto_id=projeto["projetoId"]))


@app.route("/narracoes/<projeto_id>/excluir", methods=["POST"])
def narracoes_excluir(projeto_id: str):
    na.excluir_projeto(BASE_DIR, projeto_id)
    _NARRACAO_STATUS.pop(projeto_id, None)
    return redirect(url_for("narracoes_page"))


@app.route("/narracoes/<projeto_id>", methods=["GET"])
def narracao_detalhe(projeto_id: str):
    if not na.projeto_existe(BASE_DIR, projeto_id):
        return "Projeto não encontrado.", 404
    projeto = na.carregar_projeto(BASE_DIR, projeto_id)
    roteiro = na.carregar_roteiro(BASE_DIR, projeto_id)
    geracoes = na.carregar_geracoes(BASE_DIR, projeto_id)
    gravacoes = na.listar_gravacoes(BASE_DIR, projeto_id)
    return render_template(
        "narracao_detalhe.html",
        projeto=projeto, roteiro=roteiro, geracoes=geracoes, gravacoes=gravacoes,
        status=_NARRACAO_STATUS.get(projeto_id), error=None,
        **_narracao_ctx_comuns(),
    )


@app.route("/narracoes/<projeto_id>/roteiro", methods=["POST"])
def narracao_importar_roteiro(projeto_id: str):
    texto = request.form.get("texto", "")
    modo = request.form.get("modo_separacao", "linha")
    try:
        na.importar_roteiro(BASE_DIR, projeto_id, texto, modo)
    except na.NarracaoError as exc:
        projeto = na.carregar_projeto(BASE_DIR, projeto_id)
        roteiro = na.carregar_roteiro(BASE_DIR, projeto_id)
        geracoes = na.carregar_geracoes(BASE_DIR, projeto_id)
        gravacoes = na.listar_gravacoes(BASE_DIR, projeto_id)
        return render_template(
            "narracao_detalhe.html", projeto=projeto, roteiro=roteiro, geracoes=geracoes, gravacoes=gravacoes,
            status=_NARRACAO_STATUS.get(projeto_id), error=str(exc), **_narracao_ctx_comuns(),
        )
    return redirect(url_for("narracao_detalhe", projeto_id=projeto_id))


@app.route("/narracoes/<projeto_id>/fala/adicionar", methods=["POST"])
def narracao_adicionar_fala(projeto_id: str):
    try:
        na.adicionar_fala(BASE_DIR, projeto_id, request.form.get("texto", ""))
    except na.NarracaoError:
        pass  # texto vazio -- ignora silenciosamente, nada foi adicionado
    return redirect(url_for("narracao_detalhe", projeto_id=projeto_id))


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/editar", methods=["POST"])
def narracao_editar_fala(projeto_id: str, indice: int):
    try:
        na.editar_fala(BASE_DIR, projeto_id, indice, request.form.get("texto", ""))
    except na.NarracaoError:
        pass
    return redirect(url_for("narracao_detalhe", projeto_id=projeto_id))


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/remover", methods=["POST"])
def narracao_remover_fala(projeto_id: str, indice: int):
    try:
        na.remover_fala(BASE_DIR, projeto_id, indice)
    except na.NarracaoError:
        pass
    return redirect(url_for("narracao_detalhe", projeto_id=projeto_id))


# --------------------------------------------------------------------- #
# Gravação da própria voz, por fala (múltiplos takes) — portado do
# recurso "Minha Voz" do projeto shortmaker. Grava pelo microfone do
# navegador (MediaRecorder) em vez de usar o motor de IA nessa fala.
# --------------------------------------------------------------------- #

@app.route("/narracoes/<projeto_id>/gravacoes", methods=["GET"])
def narracao_listar_gravacoes(projeto_id: str):
    if not na.projeto_existe(BASE_DIR, projeto_id):
        return jsonify({"erro": "projeto não encontrado"}), 404
    return jsonify(na.listar_gravacoes(BASE_DIR, projeto_id))


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravar", methods=["POST"])
def narracao_gravar_fala(projeto_id: str, indice: int):
    arquivo = request.files.get("audio")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "envie o áudio gravado no campo 'audio'."}), 400

    safe_name = secure_filename(arquivo.filename) or "gravacao.webm"
    caminho_bruto = os.path.join(VOZES_DIR, f"gravacao_bruta_{uuid.uuid4().hex}_{safe_name}")
    arquivo.save(caminho_bruto)
    try:
        resultado = na.salvar_gravacao(BASE_DIR, projeto_id, indice, caminho_bruto)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    finally:
        try:
            os.remove(caminho_bruto)
        except OSError:
            pass
    return jsonify(resultado)


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/usar-gravacao", methods=["POST"])
def narracao_usar_gravacao(projeto_id: str, indice: int):
    corpo = request.get_json(silent=True) or {}
    usar = bool(corpo.get("usar", True))
    try:
        entrada = na.marcar_uso_gravacao(BASE_DIR, projeto_id, indice, usar)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(entrada)


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/selecionar-take", methods=["POST"])
def narracao_selecionar_take(projeto_id: str, indice: int):
    corpo = request.get_json(silent=True) or {}
    take_id = (corpo.get("takeId") or "").strip()
    try:
        entrada = na.selecionar_take(BASE_DIR, projeto_id, indice, take_id)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(entrada)


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/excluir", methods=["POST"])
def narracao_excluir_take(projeto_id: str, indice: int, take_id: str):
    na.excluir_take(BASE_DIR, projeto_id, indice, take_id)
    return jsonify({"ok": True})


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/audio", methods=["GET"])
def narracao_audio_take(projeto_id: str, indice: int, take_id: str):
    try:
        caminho = na.caminho_take(BASE_DIR, projeto_id, indice, take_id)
    except na.NarracaoError:
        return "Take não encontrado.", 404
    return send_file(str(caminho), mimetype="audio/wav")


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/realce", methods=["POST"])
def narracao_gerar_realce(projeto_id: str, indice: int, take_id: str):
    corpo = request.get_json(silent=True) or {}
    marcar_como_usar = bool(corpo.get("marcarComoUsar", True))
    try:
        resultado = na.gerar_realce_de_take(BASE_DIR, projeto_id, indice, take_id, marcar_como_usar=marcar_como_usar)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(resultado)


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/usar-realce", methods=["POST"])
def narracao_usar_realce(projeto_id: str, indice: int, take_id: str):
    corpo = request.get_json(silent=True) or {}
    usar_enhance = bool(corpo.get("usarEnhance", True))
    try:
        take = na.usar_realce_de_take(BASE_DIR, projeto_id, indice, take_id, usar_enhance)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(take)


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/audio-realce", methods=["GET"])
def narracao_audio_take_realce(projeto_id: str, indice: int, take_id: str):
    try:
        caminho = na.caminho_take_realce(BASE_DIR, projeto_id, indice, take_id)
    except na.NarracaoError:
        return "Realce ainda não foi gerado pra esse take.", 404
    return send_file(str(caminho), mimetype="audio/wav")


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/recortar", methods=["POST"])
def narracao_recortar_take(projeto_id: str, indice: int, take_id: str):
    corpo = request.get_json(silent=True) or {}
    try:
        inicio = float(corpo.get("inicio", 0))
        fim = float(corpo.get("fim", 0))
    except (TypeError, ValueError):
        return jsonify({"erro": "início/fim precisam ser números (segundos)."}), 400
    try:
        resultado = na.recortar_take(BASE_DIR, projeto_id, indice, take_id, inicio, fim)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(resultado)


@app.route("/narracoes/<projeto_id>/fala/<int:indice>/gravacao/<take_id>/desfazer-corte", methods=["POST"])
def narracao_desfazer_corte(projeto_id: str, indice: int, take_id: str):
    try:
        resultado = na.desfazer_recorte_take(BASE_DIR, projeto_id, indice, take_id)
    except na.NarracaoError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(resultado)


@app.route("/narracoes/<projeto_id>/config", methods=["POST"])
def narracao_salvar_config(projeto_id: str):
    try:
        na.salvar_config(
            BASE_DIR, projeto_id,
            nome=request.form.get("nome"),
            motor=request.form.get("motor"),
            voz=request.form.get("voz"),
            idioma=request.form.get("idioma"),
            velocidade=request.form.get("velocidade"),
            pausa_segundos=request.form.get("pausa_segundos"),
            usar_gpu=(request.form.get("usar_gpu") == "on"),
            voz_perfil=request.form.get("voz_perfil"),
            xtts_checkpoint=request.form.get("xtts_checkpoint"),
            chatterbox_exaggeration=request.form.get("chatterbox_exaggeration"),
            chatterbox_cfg_weight=request.form.get("chatterbox_cfg_weight"),
            kokoro_variante=request.form.get("kokoro_variante"),
            kokoro_precisao=request.form.get("kokoro_precisao"),
            cortar_silencio_gravacoes=(request.form.get("cortar_silencio_gravacoes") == "on"),
            multi_voz=(request.form.get("multi_voz") == "on"),
            fish_reference_id=request.form.get("fish_reference_id"),
            fish_temperatura=request.form.get("fish_temperatura"),
        )
    except na.NarracaoError:
        pass
    return redirect(url_for("narracao_detalhe", projeto_id=projeto_id))


def _narracao_gerar_em_background(projeto_id: str) -> None:
    status = _NARRACAO_STATUS[projeto_id]

    def log(linha: str) -> None:
        status["log"] += linha + "\n"

    try:
        na.gerar_audio_projeto(BASE_DIR, projeto_id, on_log=log)
        status["erro"] = None
    except (na.NarracaoError, VoiceGeneratorError) as exc:
        status["erro"] = str(exc)
        log(f"\nERRO: {exc}")
    except Exception as exc:  # noqa: BLE001
        status["erro"] = f"Erro inesperado: {exc}"
        log(f"\nERRO inesperado: {traceback.format_exc()}")
    finally:
        status["running"] = False
        status["pronto"] = True
        _avisar_fim("📝 Narração do roteiro", status.get("erro"), f"/narracoes/{projeto_id}", "narracao",
                    "O áudio do roteiro ficou pronto.")


@app.route("/narracoes/<projeto_id>/gerar", methods=["POST"])
def narracao_gerar(projeto_id: str):
    if not na.projeto_existe(BASE_DIR, projeto_id):
        return jsonify({"erro": "projeto não encontrado"}), 404
    status_atual = _NARRACAO_STATUS.get(projeto_id)
    if status_atual and status_atual.get("running"):
        return jsonify({"erro": "já tem uma geração rodando pra esse projeto"}), 409
    _NARRACAO_STATUS[projeto_id] = {"running": True, "log": "", "erro": None, "pronto": False}
    threading.Thread(target=_narracao_gerar_em_background, args=(projeto_id,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/narracoes/<projeto_id>/gerar/status", methods=["GET"])
def narracao_gerar_status(projeto_id: str):
    status = _NARRACAO_STATUS.get(projeto_id)
    if not status:
        return jsonify({"running": False, "log": "", "erro": None, "pronto": False})
    return jsonify(status)


@app.route("/narracoes/<projeto_id>/geracoes/<geracao_id>/audio", methods=["GET"])
def narracao_baixar_geracao(projeto_id: str, geracao_id: str):
    geracao_id_segura = "".join(c for c in geracao_id if c.isalnum() or c == "_")
    caminho = na.narracoes_dir(BASE_DIR) / projeto_id / "geracoes" / f"{geracao_id_segura}.mp3"
    if not caminho.exists():
        return "Geração não encontrada.", 404
    projeto = na.carregar_projeto(BASE_DIR, projeto_id)
    import re
    nome_sanitizado = re.sub(r"[^\w\-. ]", "_", projeto.get("nome") or "narracao").strip() or "narracao"
    return send_file(
        str(caminho), mimetype="audio/mpeg", as_attachment=True,
        download_name=f"{nome_sanitizado}_{geracao_id_segura}.mp3",
    )


@app.route("/narracoes/<projeto_id>/geracoes/<geracao_id>/remover", methods=["POST"])
def narracao_remover_geracao(projeto_id: str, geracao_id: str):
    na.excluir_geracao(BASE_DIR, projeto_id, geracao_id)
    return redirect(url_for("narracao_detalhe", projeto_id=projeto_id))


# --------------------------------------------------------------------- #
# Página de configurações gerais do site
# --------------------------------------------------------------------- #

@app.route("/settings", methods=["GET"])
def settings_page():
    import lista_negra
    return render_template("settings.html", config=load_site_config(), all_providers=ALL_PROVIDERS,
                           runpod=__import__("runpod_gerador").resumo(rede=False),
                           sites_bloqueados=lista_negra.sites(), sites_padrao=lista_negra.PADRAO,
                           provedores_bloqueados=[p for p in ALL_PROVIDERS if lista_negra.provedor_bloqueado(p)],
                           vinhetas={t: os.path.basename(__import__("canal").clipe_padrao(t) or "") for t in __import__("canal").VINHETAS})


@app.route("/youtube-cookies", methods=["GET"])
def youtube_cookies_status():
    import yt_cookies
    p = yt_cookies.prefs()
    return jsonify({"descricao": yt_cookies.descrever(), "navegador": p.get("navegador") or "",
                    "navegador_que_funcionou": p.get("navegador_que_funcionou"), "tem_arquivo": bool(yt_cookies.arquivo_cookies())})


@app.route("/youtube-cookies", methods=["POST"])
def youtube_cookies_salvar():
    """Configurações → YouTube: navegador dos cookies e/ou cookies.txt (yt_cookies.py)."""
    import yt_cookies
    nav = (request.form.get("navegador") or "").strip().lower()
    if nav and nav not in yt_cookies.NAVEGADORES + ["nenhum"]:
        nav = ""
    yt_cookies.salvar_prefs(navegador=nav or None)
    if request.form.get("apagar_arquivo") == "on":
        try:
            os.remove(yt_cookies.ARQ_COOKIES)
        except OSError:
            pass
    arq = request.files.get("arquivo")
    if arq and arq.filename:
        try:
            yt_cookies.salvar_arquivo(arq.read())
        except ValueError as exc:
            return f"{exc} <a href='{url_for('settings_page')}#youtube-cookies'>voltar</a>", 400
    return redirect(url_for("settings_page") + "#youtube-cookies")


@app.route("/contas-google", methods=["GET"])
def contas_google_page():
    from googleflow import googleflow_client as gf
    return render_template("contas_google.html", keyring_disponivel=gf.keyring_disponivel())


@app.route("/settings/ordem-fontes", methods=["POST"])
def salvar_ordem_fontes():
    """Ordem de preferência das fontes de vídeo — salva NA HORA, ao soltar o item arrastado (v84_103)."""
    ordem = [str(x) for x in ((request.get_json(silent=True) or {}).get("ordem") or [])]
    try:
        cfg = save_site_config({"provider_priority": ordem})
    except SiteConfigError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "ordem": cfg["provider_priority"]})


@app.route("/settings", methods=["POST"])
def save_settings():
    new_values = {
        "orientation": request.form.get("orientation", "16:9"),
        "search_orientation": request.form.get("search_orientation", "match_export"),
        "export_quality": request.form.get("export_quality", "1080p"),
        "clip_trim_position": request.form.get("clip_trim_position", "start"),
        "encoder_video": request.form.get("encoder_video", "auto") if request.form.get("encoder_video") in ("auto", "cpu", "h264_nvenc", "h264_qsv", "h264_amf") else "auto",
        "aspect_fill": request.form.get("aspect_fill", "black"),
        "trim_start_frames": request.form.get("trim_start_frames", 10),
        "provider_priority": request.form.getlist("provider_priority") or ALL_PROVIDERS,
        "pexels_api_fallback_to_browser": request.form.get("pexels_api_fallback_to_browser") == "on",
        "pixabay_api_fallback_to_browser": request.form.get("pixabay_api_fallback_to_browser") == "on",
        "magnific_only_free": request.form.get("magnific_only_free") == "on",
        "evitar_repeticao_clipes": request.form.get("evitar_repeticao_clipes") == "on",
        "transition_type": request.form.get("transition_type", "none"),
        "transition_duration": float(request.form.get("transition_duration", 0.6) or 0.6),
        # A tela mostra "Ocultar o navegador" (marcado = oculto); o campo-marcador
        # avisa que ela foi enviada (checkbox desmarcado não vem no POST). Sem o
        # marcador, vale o campo antigo `browser_visible` (formulários antigos/testes).
        "browser_visible": (
            request.form.get("ocultar_navegador") != "on"
            if request.form.get("ocultar_navegador_enviado") == "1"
            else request.form.get("browser_visible") == "on"
        ),
        "browser_shared_across_providers": request.form.get("browser_shared_across_providers") == "on",
        "browser_mode": request.form.get("browser_mode", "reuse_session"),
        "preview_fetch_concurrency": request.form.get("preview_fetch_concurrency", 3),
        "assembly_fetch_concurrency": request.form.get("assembly_fetch_concurrency", 3),
        "whisper_device": request.form.get("whisper_device", "auto"),
        "provider_attempt_timeout_seconds": request.form.get("provider_attempt_timeout_seconds", 25),
        "animepexels_base_url": request.form.get("animepexels_base_url", "http://localhost:5000"),
    }
    if "animepexels_online_url" in request.form:  # formulários antigos não têm: mantém o que já estava salvo
        new_values["animepexels_online_url"] = request.form["animepexels_online_url"]
    if (request.form.get("animepexels_online_api_key") or "").strip():  # em branco = mantém a chave salva
        new_values["animepexels_online_api_key"] = request.form["animepexels_online_api_key"]
    if request.form.get("animepexels_online_apagar_chave") == "on":
        new_values["animepexels_online_api_key"] = ""
    if "runpod_modelo_imagem" in request.form:  # 🟣 Runpod (v84_116)
        import runpod_gerador as _rp
        if (request.form.get("runpod_api_key") or "").strip():  # em branco = mantém a chave salva
            new_values["runpod_api_key"] = request.form["runpod_api_key"].strip()
        if request.form.get("runpod_apagar_chave") == "on":
            new_values["runpod_api_key"] = ""
        if request.form.get("runpod_modelo_imagem") in _rp.MODELOS:
            new_values["runpod_modelo_imagem"] = request.form["runpod_modelo_imagem"]
        if request.form.get("runpod_modelo_video") in _rp.MODELOS:
            new_values["runpod_modelo_video"] = request.form["runpod_modelo_video"]
        try:
            new_values["runpod_video_duracao"] = max(1, min(10, int(request.form.get("runpod_video_duracao") or 5)))
        except ValueError:
            pass
        for _b in ("runpod_video_rascunho", "runpod_video_1080p", "runpod_reserva_flow"):
            new_values[_b] = request.form.get(_b) == "on"
        if "runpod_modo" in request.form:  # 🖥️ Meu pod (pod_studio.py, v84_121)
            new_values["runpod_modo"] = request.form.get("runpod_modo")
            new_values["runpod_pod_url"] = (request.form.get("runpod_pod_url") or "").strip()
            if (request.form.get("runpod_pod_chave") or "").strip():  # em branco = mantém a chave salva
                new_values["runpod_pod_chave"] = request.form["runpod_pod_chave"].strip()
            if request.form.get("runpod_pod_chave_apagar") == "on":
                new_values["runpod_pod_chave"] = ""
            new_values["chatterbox_onde"] = "pod" if request.form.get("chatterbox_no_pod") == "on" else "local"
            new_values["chatterbox_pod_ptbr"] = request.form.get("chatterbox_pod_ptbr") == "on"
    if "sites_bloqueados" in request.form:  # ⛔ lista negra de sites (v84_106)
        import lista_negra
        new_values["sites_bloqueados"] = (list(lista_negra.PADRAO) if request.form.get("sites_bloqueados_padrao") == "on"
                                          else lista_negra.normalizar(request.form["sites_bloqueados"]))
    if "nome_canal" in request.form:  # 📺 v84_95 (v84_101: vale pro 📺 perfil ativo também)
        new_values["nome_canal"] = request.form["nome_canal"]
        try:
            import perfis_canal
            perfis_canal.editar(perfis_canal.ativo_id(), nome_canal=request.form["nome_canal"])
        except Exception:  # noqa: BLE001
            pass
    if "estilo_imagens" in request.form:  # 🎞️ imagens reais × ilustração
        new_values["estilo_imagens"] = request.form["estilo_imagens"]
    for chave_ig in ("ia_google_youtube", "ia_google_porta", "ia_google_imagens_min_lado"):  # 🔎 IA do Google
        if chave_ig in request.form:
            new_values[chave_ig] = request.form[chave_ig]
    for chave_fish in ("fish_modo", "fish_url", "fish_modelo"):  # 🐟 Fish Audio S2
        if chave_fish in request.form:
            new_values[chave_fish] = request.form[chave_fish]
    for chave_fish in ("fish_api_key", "fish_api_key_local"):
        if (request.form.get(chave_fish) or "").strip():  # em branco = mantém a chave salva
            new_values[chave_fish] = request.form[chave_fish]
        if request.form.get(chave_fish + "_apagar") == "on":
            new_values[chave_fish] = ""
    for chave_flow in ("flow_navegador", "flow_exe", "flow_timeout_seconds", "flow_seletor_configuracoes",
                       "flow_horas_ate_liberar", "flow_palavras_limite", "flow_modelo_video", "flow_seletor_video",
                       "flow_modo_automacao"):
        if chave_flow in request.form:  # formulários antigos não têm: mantém o que já estava salvo
            new_values[chave_flow] = request.form[chave_flow]
    if "buscadores_proporcao" in request.form:
        new_values["buscadores_proporcao"] = request.form["buscadores_proporcao"]
    if request.form.get("buscadores_imagem_paralelo_enviado") == "1":  # checkbox desmarcado não vem no POST
        new_values["buscadores_imagem_paralelo"] = request.form.get("buscadores_imagem_paralelo") == "on"
    if "flow_navegador" in request.form:  # a seção do Flow veio no formulário => o checkbox desmarcado não é enviado
        new_values["flow_configurar_projeto"] = request.form.get("flow_configurar_projeto") == "on"
    try:
        saved = save_site_config(new_values)
        return render_template("settings.html", config=saved, all_providers=ALL_PROVIDERS, success=True,
                               runpod=__import__("runpod_gerador").resumo(rede=False))
    except SiteConfigError as exc:
        # devolve o que a pessoa tentou salvar (não o que já estava no
        # disco), pra ela ver exatamente o que causou o erro e corrigir.
        return render_template("settings.html", config={**load_site_config(), **new_values}, all_providers=ALL_PROVIDERS, error=str(exc),
                               runpod=__import__("runpod_gerador").resumo(rede=False))


# --------------------------------------------------------------------- #
# Google Flow (imagens geradas por IA): servir as imagens + login
# --------------------------------------------------------------------- #

def gf_conta_padrao() -> str:
    from googleflow import googleflow_client as gf
    return gf.CONTA_PADRAO


@app.route("/flow/imagens/<path:nome>", methods=["GET"])
def flow_imagem(nome: str):
    """Serve uma imagem gerada no Flow (as prévias do editor apontam pra cá)."""
    from googleflow import googleflow_client as gf
    return send_from_directory(str(gf.pasta_imagens()), os.path.basename(nome))


_FLOW_LOGIN: Dict[str, Any] = {"status": "ocioso", "erro": None}


@app.route("/flow/login", methods=["POST"])
def flow_login():
    """Abre uma janela VISÍVEL do navegador pra entrar na conta Google no
    Flow (uma vez só). Roda em segundo plano; acompanhe em /flow/login/status."""
    if _FLOW_LOGIN["status"] == "aguardando_login":
        return jsonify({"erro": "Já tem uma janela de login aberta."}), 409
    corpo = request.get_json(silent=True) or {}
    from googleflow import googleflow_client as gf
    conta_pedida = str(corpo.get("conta") or request.form.get("conta") or "").strip()
    conta = conta_pedida or gf.CONTA_PADRAO
    email = str(corpo.get("email") or "").strip()
    senha = str(corpo.get("senha") or "")             # nunca é logada nem gravada em lugar nenhum daqui
    salvar = bool(corpo.get("salvar_senha"))
    if conta not in gf.nomes_das_contas():
        return jsonify({"erro": f"Conta '{conta}' não encontrada."}), 400
    contas_por_nome = {c["nome"]: c for c in gf.listar_contas()}
    if not senha:  # ninguém digitou agora: usa a senha salva, se houver (login automático "de um clique")
        senha = gf.obter_senha(conta) or ""
    if senha and not email:
        email = contas_por_nome.get(conta, {}).get("email", "")
        if not email:
            return jsonify({"erro": "Essa conta não tem e-mail cadastrado — informe o e-mail pra usar o login automático."}), 400
    cfg = load_site_config()
    _FLOW_LOGIN.update({"status": "aguardando_login", "erro": None})

    def _run():
        try:
            from googleflow.googleflow_client import GoogleFlowClient
            cliente = GoogleFlowClient(site_cfg=cfg)
            if senha:
                cliente.login_automatico(conta, email, senha)
                if salvar:
                    gf.salvar_senha(conta, senha)
            else:
                cliente.login_interativo(conta=conta) if conta_pedida else cliente.login_interativo()
            _FLOW_LOGIN.update({"status": "ok", "erro": None})
            gf.despular_conta(conta or None)  # ⏭ logou: a conta pulada volta pra troca de contas
        except Exception as exc:  # noqa: BLE001
            _FLOW_LOGIN.update({"status": "erro", "erro": str(exc)})

    _thread_com_aviso(_run, lambda: _FLOW_LOGIN, f"🔑 Login no Flow ({conta})", "/contas-google", "flow")
    return jsonify({"ok": True})


@app.route("/flow/contas", methods=["GET"])
def flow_contas_listar():
    """Contas do Flow + estado (esgotada até quando, já logada)."""
    from googleflow import googleflow_client as gf
    return jsonify(gf.listar_contas())


def _flow_conta_acao(acao):
    from googleflow import googleflow_client as gf
    try:
        acao(gf)
    except gf.GoogleFlowError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify(gf.listar_contas())


@app.route("/flow/contas", methods=["POST"])
def flow_contas_adicionar():
    corpo = request.get_json(silent=True) or {}
    nome, email = str(corpo.get("nome", "")), str(corpo.get("email", ""))
    return _flow_conta_acao(lambda gf: gf.adicionar_conta(nome, email))


@app.route("/flow/contas/<nome>/email", methods=["POST"])
def flow_contas_definir_email(nome: str):
    email = str((request.get_json(silent=True) or {}).get("email", ""))
    return _flow_conta_acao(lambda gf: gf.definir_email(nome, email))


@app.route("/flow/contas/<nome>/senha", methods=["POST"])
def flow_contas_salvar_senha(nome: str):
    senha = str((request.get_json(silent=True) or {}).get("senha", ""))
    if not senha:
        return jsonify({"erro": "Informe a senha."}), 400
    return _flow_conta_acao(lambda gf: gf.salvar_senha(nome, senha))


@app.route("/flow/contas/<nome>/senha", methods=["GET"])
def flow_contas_ver_senha(nome: str):
    """Devolve a senha salva dessa conta (pro botão "Ver senha" na tela) --
    seja a que você salvou manualmente ou a gerada automaticamente numa troca."""
    from googleflow import googleflow_client as gf
    if nome not in gf.nomes_das_contas():
        return jsonify({"erro": f"Conta '{nome}' não encontrada."}), 400
    senha = gf.obter_senha(nome)
    if senha is None:
        return jsonify({"erro": "Essa conta não tem senha salva."}), 404
    return jsonify({"senha": senha})


@app.route("/flow/contas/<nome>/senha/remover", methods=["POST"])
def flow_contas_remover_senha(nome: str):
    return _flow_conta_acao(lambda gf: gf.remover_senha(nome))


# --------------------------------------------------------------------- #
# Google Flow: troca de senha (gera uma nova e troca de verdade na conta)
# --------------------------------------------------------------------- #

_FLOW_TROCAR_SENHA: Dict[str, Any] = {"status": "ocioso", "erro": None, "conta": None, "nova_senha": None}


@app.route("/flow/contas/<nome>/trocar-senha", methods=["POST"])
def flow_contas_trocar_senha(nome: str):
    """Troca a senha da conta de verdade no Google (fluxo em segundo plano,
    acompanhe em /flow/trocar-senha/status). A senha ATUAL é obrigatória —
    o Google sempre pede pra confirmar identidade antes de trocar; ela passa
    só por esta chamada, nunca é salva. A senha nova é gerada automaticamente
    (10 caracteres, letras minúsculas e números) a menos que você informe uma."""
    from googleflow import googleflow_client as gf
    if nome not in gf.nomes_das_contas():
        return jsonify({"erro": f"Conta '{nome}' não encontrada."}), 400
    if _FLOW_TROCAR_SENHA["status"] == "trocando":
        return jsonify({"erro": "Já tem uma troca de senha em andamento."}), 409
    corpo = request.get_json(silent=True) or {}
    senha_atual = str(corpo.get("senha_atual") or "")
    nova_senha = str(corpo.get("nova_senha") or "").strip() or None
    if not senha_atual:
        return jsonify({"erro": "Informe a senha atual da conta."}), 400

    cfg = load_site_config()
    _FLOW_TROCAR_SENHA.update({"status": "trocando", "erro": None, "conta": nome, "nova_senha": None})

    def _run():
        try:
            from googleflow.googleflow_client import GoogleFlowClient
            senha_gerada = GoogleFlowClient(site_cfg=cfg).trocar_senha(nome, senha_atual, nova_senha)
            _FLOW_TROCAR_SENHA.update({"status": "ok", "erro": None, "nova_senha": senha_gerada})
        except Exception as exc:  # noqa: BLE001
            _FLOW_TROCAR_SENHA.update({"status": "erro", "erro": str(exc)})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/flow/trocar-senha/status", methods=["GET"])
def flow_trocar_senha_status():
    return jsonify(dict(_FLOW_TROCAR_SENHA))


# --------------------------------------------------------------------- #
# Google Flow: exportar/importar contas (e-mail + senha) via JSON
# --------------------------------------------------------------------- #

@app.route("/flow/contas/exportar", methods=["GET"])
def flow_contas_exportar():
    """Baixa um JSON com e-mail + senha de toda conta que tem senha salva
    (a principal inclusive, agora que também pode ter e-mail cadastrado).
    ⚠️ O arquivo fica com as senhas em TEXTO PURO — guarde/apague com cuidado."""
    from googleflow import googleflow_client as gf
    dados = []
    for c in gf.listar_contas():
        senha = gf.obter_senha(c["nome"])
        if senha is None:
            continue
        dados.append({"nome": c["nome"], "email": c["email"], "senha": senha})
    corpo = json.dumps({"contas": dados}, ensure_ascii=False, indent=2)
    resposta = jsonify(json.loads(corpo))
    resposta.headers["Content-Disposition"] = "attachment; filename=contas_flow.json"
    return resposta


@app.route("/flow/contas/importar", methods=["POST"])
def flow_contas_importar():
    """Importa contas de um JSON no mesmo formato do exportar (`{"contas":
    [{"nome", "email", "senha"}, ...]}`). Conta que já existe: só atualiza
    e-mail/senha (não duplica nem apaga o que não veio no arquivo). Devolve
    quais entraram e quais deram erro, sem parar no primeiro problema."""
    from googleflow import googleflow_client as gf
    corpo = request.get_json(silent=True) or {}
    contas = corpo.get("contas")
    if not isinstance(contas, list):
        return jsonify({"erro": 'Formato inválido: esperava {"contas": [...]}.'}), 400
    importadas, erros = [], []
    for item in contas:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "").strip()
        email = str(item.get("email") or "").strip()
        senha = item.get("senha")
        if not nome:
            continue
        try:
            if nome not in gf.nomes_das_contas():
                gf.adicionar_conta(nome, email)
            elif email:
                gf.definir_email(nome, email)
            if senha:
                gf.salvar_senha(nome, str(senha))
            importadas.append(nome)
        except gf.GoogleFlowError as exc:
            erros.append(f"{nome}: {exc}")
    return jsonify({"contas": gf.listar_contas(), "importadas": importadas, "erros": erros})


@app.route("/flow/contas/<nome>/remover", methods=["POST"])
def flow_contas_remover(nome: str):
    return _flow_conta_acao(lambda gf: gf.remover_conta(nome))


@app.route("/flow/contas/<nome>/esgotada", methods=["POST"])
def flow_contas_esgotada(nome: str):
    """Marca a conta como esgotada (ou libera, com {"esgotada": false}) à mão."""
    esgotada = bool((request.get_json(silent=True) or {}).get("esgotada", True))
    horas = load_site_config().get("flow_horas_ate_liberar", 24)

    def _acao(gf):
        if nome not in gf.nomes_das_contas():
            raise gf.GoogleFlowError(f"Conta '{nome}' não encontrada.")
        gf.marcar_esgotada(nome, horas) if esgotada else gf.liberar_conta(nome)

    return _flow_conta_acao(_acao)


@app.route("/flow/login/status", methods=["GET"])
def flow_login_status():
    return jsonify(dict(_FLOW_LOGIN))


@app.route("/reuse-json", methods=["POST"])
def reuse_json():
    """Cria um job usando um áudio + JSON de uma tentativa anterior.

    IMPORTANTE: este fluxo NÃO chama Whisper e NÃO monta um novo prompt.
    Ele salva o áudio, valida o JSON usando a duração real do áudio e vai
    diretamente para a extração/busca das prévias.
    """
    audio_file = request.files.get("audio_reuse")
    json_file = request.files.get("json_reuse")
    json_text = (request.form.get("json_reuse_text") or "").strip()

    if not audio_file or not audio_file.filename:
        return render_template("index.html", providers=DEFAULT_PROVIDERS,
                               error="No modo JSON existente, selecione o áudio.")
    has_file = bool(json_file and json_file.filename)
    if not has_file and not json_text:
        return render_template("index.html", providers=DEFAULT_PROVIDERS,
                               error="No modo JSON existente, selecione o arquivo JSON ou cole o texto do JSON.")

    selected_providers = [p for p in request.form.getlist("providers_reuse") if p in DEFAULT_PROVIDERS] or DEFAULT_PROVIDERS
    add_word_captions = request.form.get("add_word_captions_reuse") == "on"
    caption_style = _parse_caption_style_from_form(request.form, suffix="_reuse")

    job_id = uuid.uuid4().hex[:12]
    job_dir = _job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)

    safe_audio = secure_filename(audio_file.filename)
    audio_ext = os.path.splitext(safe_audio)[1] or ".bin"
    audio_path = os.path.join(job_dir, "narracao" + audio_ext)
    audio_file.save(audio_path)

    # o JSON pode vir de um arquivo .json OU colado direto como texto
    # na caixa -- se os dois vierem preenchidos, o arquivo tem
    # prioridade (mesma prioridade que já existia implicitamente antes,
    # já que só o arquivo era aceito).
    reused_json_label = None
    if has_file:
        try:
            raw_json = json_file.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return render_template("index.html", providers=DEFAULT_PROVIDERS,
                                   error="O JSON precisa estar em UTF-8.")
        reused_json_label = json_file.filename
    else:
        raw_json = json_text
        reused_json_label = "colado manualmente"

    try:
        parsed_json = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        import json_ia  # conserta o que o copiar/colar da IA estraga
        try:
            parsed_json = json_ia.carregar(raw_json)
        except ValueError:
            return render_template("index.html", providers=DEFAULT_PROVIDERS,
                                   error=f"JSON inválido: {exc}")

    json_path = os.path.join(job_dir, "json_reutilizado.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(parsed_json, f, ensure_ascii=False, indent=2)

    try:
        total_duration = get_audio_duration(audio_path)
        if not total_duration or total_duration <= 0:
            raise ValueError("não foi possível determinar a duração do áudio")
        # A validação é a mesma do fluxo normal, mas nenhuma transcrição é feita.
        parsed = parse_ai_response(
            raw_json,
            valid_providers=selected_providers,
            total_duration=total_duration,
        )
        __import__("chamadas").limpar_buscas(parsed.segments)  # 🚫 inscreva-se/venda não viram busca de imagem
    except PromptBuilderError as exc:
        return render_template("index.html", providers=DEFAULT_PROVIDERS,
                               error=f"JSON não compatível com o áudio: {exc}")
    except Exception as exc:
        return render_template("index.html", providers=DEFAULT_PROVIDERS,
                               error=f"Não foi possível reutilizar o JSON: {exc}")

    job = {
        "job_id": job_id,
        "audio_path": audio_path,
        "music_path": None,
        "music_volume": 0.18,
        "providers": selected_providers,
        "add_word_captions": add_word_captions,
        "caption_style": caption_style,
        "status": "buscando_previas",
        "created_at": time.time(),
        "cancel_requested": False,
        "original_filename": audio_file.filename,
        "reused_json": True,
        "reused_json_filename": reused_json_label,
        "reused_json_path": json_path,
        "segments": [s.to_dict() for s in parsed.segments],
        "pending_segments": [s.to_dict() for s in parsed.segments],
        "soundtrack_suggestion": parsed.soundtrack_suggestion,
        "total_duration": total_duration,
        "prompt": "",
        "whisper_skipped": True,
        "preview_progress": {"current": 0, "total": len(parsed.segments)},
    }
    if add_word_captions:
        job["word_timestamps"] = []
    job["mix_midia"] = __import__("mix_midia").do_form(request.form, sufixo="_reuse")
    job["bibliotecas"] = _bibliotecas_do_form(request.form, selected_providers, sufixo="_reuse")
    if _formato_do_form(request.form, "formato_reuse"):
        job["orientation"] = _formato_do_form(request.form, "formato_reuse")
    _aplicar_mix_midia(job, parsed)
    _aplicar_padroes_biblioteca(job, parsed)
    _avisar_buscas(job)
    _marcar_textos_da_1a_ia(job)
    _aplicar_extras_dp(job, parsed)

    _JOBS[job_id] = job
    perf = PerfLog(job_dir, job_id=job_id)
    _PERF_LOGS[job_id] = perf
    perf.save()
    _save_state(job_id)

    _fetch_previews(job_id, job, parsed.segments)
    return redirect(url_for("fetching_previews_page", job_id=job_id))


_EXTENSOES_AUDIO_ZIP = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".webm", ".wma", ".aif", ".aiff")


def _decodificar_srt(dados: bytes) -> str:
    """.srt salvo por outros programas nem sempre é UTF-8 (Windows costuma
    salvar em UTF-16 ou ANSI/cp1252) — tenta as codificações comuns."""
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dados.decode("utf-16")
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("utf-8", errors="replace")


def _extrair_audio_e_srt_do_zip(zip_path: str, job_dir: str):
    """Abre um .zip enviado no lugar do áudio -- o mesmo formato que o
    Gerador de Voz oferece pra baixar (áudio + legenda.srt juntos, ver
    `/gerar-voz/baixar-zip/<job_id>`) -- e devolve `(audio_path,
    segments)`: o áudio extraído pra dentro de `job_dir`, e os
    segmentos já parseados do .srt (mesmo formato que
    `whisper_transcribe.transcribe_audio()` devolve), prontos pra pular
    a transcrição inteira. Levanta `legendas.LegendaError` com uma
    mensagem clara se o zip não tiver os dois arquivos esperados, ou se
    o .srt não puder ser lido.
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise lg.LegendaError("o arquivo enviado não é um .zip válido.") from exc

    with zf:
        # ignora diretórios e o lixo que o macOS/Windows põem no zip
        # ("__MACOSX/._narracao.wav", ".DS_Store", "Thumbs.db") — o "._arquivo.wav"
        # tem extensão de áudio mas não é áudio, e era escolhido no lugar do real.
        infos = [
            i for i in zf.infolist()
            if not i.is_dir() and "__MACOSX" not in i.filename.split("/")
            and not os.path.basename(i.filename).startswith(".")
        ]
        audios = [i for i in infos if os.path.splitext(i.filename)[1].lower() in _EXTENSOES_AUDIO_ZIP]
        srts = [i for i in infos if i.filename.lower().endswith(".srt")]
        # mais de um áudio: o maior é a narração (os outros costumam ser prévias/trechos)
        nome_audio = max(audios, key=lambda i: i.file_size).filename if audios else None
        nome_srt = max(srts, key=lambda i: i.file_size).filename if srts else None
        if not nome_audio:
            raise lg.LegendaError(
                "não encontrei nenhum arquivo de áudio dentro do .zip (procurei por "
                + ", ".join(_EXTENSOES_AUDIO_ZIP) + ")."
            )
        if not nome_srt:
            raise lg.LegendaError("não encontrei nenhum arquivo .srt dentro do .zip.")

        audio_ext = os.path.splitext(nome_audio)[1]
        audio_path = os.path.join(job_dir, "narracao" + audio_ext)
        with zf.open(nome_audio) as origem, open(audio_path, "wb") as destino:
            shutil.copyfileobj(origem, destino)

        srt_texto = _decodificar_srt(zf.read(nome_srt))

    segments = lg.parse_srt(srt_texto)
    return audio_path, segments


def _chamadas_do_zip(zip_path: str) -> List[Dict[str, Any]]:
    """`chamadas.json` do Gerar voz (onde ficam as chamadas de inscreva-se/venda/link)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            nome = next((n for n in zf.namelist() if "__MACOSX" not in n and os.path.basename(n).lower() == "chamadas.json"), None)
            if not nome:
                return []
            d = json.loads(zf.read(nome).decode("utf-8", "replace"))
    except (zipfile.BadZipFile, OSError, KeyError, ValueError):
        return []
    lista = d.get("chamadas") if isinstance(d, dict) else d
    return [c for c in (lista or []) if isinstance(c, dict) and c.get("tipo") and c.get("inicio") is not None]


def _cortes_com_chamadas(job: dict, cortes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cortes da IA + as chamadas do roteiro. Colar o JSON da IA de novo não
    apaga as chamadas que já existem (nem o clipe que você enviou pra elas)."""
    ja = [c for c in job.get("cutaway_suggestions") or [] if c.get("chamada")]
    return list(cortes) + (ja or __import__("chamadas").para_cortes(job.get("chamadas"), __import__("perfis_canal").do_job(job)))


# 🛒 projeto de venda e 🕵️ modelo de vídeo: mídias do próprio projeto que entram no vídeo
# {tipo: (módulo, provider que a IA usa nos trechos, chave no job, chave no info.json, rótulo)}
_PROJETOS_MIDIA = {
    "venda": ("vendas", "produto", "venda_id", "🛒 projeto de venda"),
    "dossie": ("dossies", "material", "dossie_id", "🕵️ modelo de vídeo"),
}


def _projeto_do_zip(zip_path: str) -> Tuple[str, str]:
    """(tipo, id) gravado no info.json do .zip do Gerador de voz (("", "") se não tem)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info = next((n for n in zf.namelist() if os.path.basename(n).lower() == "info.json"), None)
            if info:
                d = json.loads(zf.read(info).decode("utf-8", "replace")) or {}
                for tipo, (_m, _p, chave, _r) in _PROJETOS_MIDIA.items():
                    vid = str(d.get(chave) or "")
                    if re.fullmatch(r"[0-9a-f]{10}", vid):
                        return tipo, vid
    except (zipfile.BadZipFile, OSError, KeyError, ValueError, AttributeError):
        pass
    return "", ""


def _roteiro_do_zip(zip_path: str) -> str:
    """id do 📝 Roteiro do YouTube gravado no info.json do .zip do Gerar voz ("" se não tem)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info = next((n for n in zf.namelist() if os.path.basename(n).lower() == "info.json"), None)
            if info:
                rid = str((json.loads(zf.read(info).decode("utf-8", "replace")) or {}).get("roteiro_id") or "")
                if re.fullmatch(r"[0-9a-f]{6,40}", rid):
                    return rid
    except (zipfile.BadZipFile, OSError, KeyError, ValueError, AttributeError):
        pass
    return ""


def _venda_do_zip(zip_path: str) -> str:
    tipo, vid = _projeto_do_zip(zip_path)
    return vid if tipo == "venda" else ""


def _projeto_do_job(job: dict):
    """(tipo, módulo, projeto, provider) do projeto ligado ao vídeo, ou None."""
    import importlib
    for tipo, (mod_nome, prov, chave, _r) in _PROJETOS_MIDIA.items():
        if job.get(chave):
            mod = importlib.import_module(mod_nome)
            try:
                return tipo, mod, mod.carregar(BASE_DIR, job[chave]), prov
            except Exception:  # noqa: BLE001
                return None
    return None


def _ligar_projeto(job: dict, tipo: str, pid: str) -> bool:
    """Liga o projeto (venda ou modelo) ao vídeo: guarda o id e põe as fotos/vídeos
    dele na biblioteca do Estúdio (arrastáveis pra qualquer trecho)."""
    import importlib
    if tipo not in _PROJETOS_MIDIA:
        return False
    mod_nome, _prov, chave, _r = _PROJETOS_MIDIA[tipo]
    mod = importlib.import_module(mod_nome)
    try:
        p = mod.carregar(BASE_DIR, pid)
    except Exception:  # noqa: BLE001
        return False
    for _t, (_m, _p, ch, _r2) in _PROJETOS_MIDIA.items():
        job.pop(ch, None)
    job[chave] = pid
    job.pop("direcao_do_projeto", None)
    if tipo == "dossie":  # o modelo de vídeo pode sugerir uma direção de edição
        try:
            _sug = (mod.MODELOS.get((p.get("config") or {}).get("modelo")) or {}).get("direcao_sugerida")
            if _sug:
                job["direcao_do_projeto"] = _sug
        except Exception:  # noqa: BLE001
            pass
    lib = job.setdefault("media_library", [])
    ja = {it.get("path") for it in lib}
    for m in mod.midias_para_editor(BASE_DIR, p):
        if m["caminho"] in ja:
            continue
        lib.append({"id": "v" + uuid.uuid4().hex[:7], "filename": f"{m['id']} · {m['o_que_e'][:60]}", "path": m["caminho"],
                    "media_type": "image" if m["tipo"] == "foto" else "video", "venda_midia": m["id"]})
    return True


def _ligar_venda(job: dict, venda_id: str) -> bool:
    return _ligar_projeto(job, "venda", venda_id)


def _com_produto(job: dict, prompt_text: str) -> str:
    """Prompt do editor + o bloco das mídias do projeto ligado (venda ou modelo) + a regra das chamadas."""
    prompt_text = prompt_text + "\n" + __import__("chamadas").bloco_prompt_buscas(job.get("chamadas"))  # 🚫 chamada não vira busca
    prompt_text += _bloco_cenas_do_roteiro(job)
    pj = _projeto_do_job(job)
    if not pj:
        return prompt_text
    _t, mod, p, _prov = pj
    bloco = mod.bloco_prompt_editor(BASE_DIR, p)
    return prompt_text + ("\n" + bloco if bloco else "")


def _cenas_do_roteiro(job: dict) -> List[Dict[str, Any]]:
    """📝 Cenas do projeto do Roteiro do YouTube ligado, com o tempo na narração DESTE vídeo (guardadas no job)."""
    if not job.get("roteiro_id"):
        return []
    if job.get("roteiro_cenas") is not None:
        return job["roteiro_cenas"]
    try:
        import roteiro_no_editor
        import roteiros_yt
        p = roteiros_yt.carregar_projeto(BASE_DIR, job["roteiro_id"])
        job["roteiro_cenas"] = roteiro_no_editor.cenas_com_tempo(p, _palavras_da_narracao(job), job.get("total_duration"))
    except Exception:  # noqa: BLE001 — projeto apagado/sem roteiro: segue sem as cenas
        job["roteiro_cenas"] = []
    return job["roteiro_cenas"]


def _youtube_marcado(job: dict) -> bool:
    """A fonte 🎬 youtube foi marcada no vídeo? Sem ela, NADA vira clipe do YouTube (nem as cenas de um projeto
    do Roteiro do YouTube / modelo de vídeo, nem os cortes reais)."""
    return "youtube" in (job.get("providers") or [])


def _reserva_sem_youtube(job: dict) -> Tuple[str, str]:
    """(provider, media_type) pra um trecho que pedia YouTube com a fonte desmarcada: o 1º banco de VÍDEO marcado;
    sem nenhum, a 1ª fonte de foto marcada; sem nada, pexels."""
    import mix_midia
    marcados = [p for p in job.get("providers") or [] if p not in ("youtube", "produto", "material", "flow", "runpod")]
    video = next((p for p in marcados if p not in mix_midia.SO_FOTO), None)
    if video:
        return video, "video"
    foto = next((p for p in marcados if p in PHOTO_SEARCH_PROVIDERS), None)
    return (foto, "image") if foto else ("pexels", "video")


def _tirar_youtube_desmarcado(job: dict, segments: List[VideoSegment]) -> int:
    """Trecho "youtube" (sem arquivo escolhido) num vídeo SEM a fonte youtube marcada vira o banco marcado
    (mesma busca). Devolve quantos mudaram."""
    if _youtube_marcado(job):
        return 0
    prov, tipo = _reserva_sem_youtube(job)
    n = 0
    for s in segments:
        if getattr(s, "provider", None) == "youtube" and not getattr(s, "override_source", None):
            s.provider, s.media_type = prov, tipo
            n += 1
    return n


def _bloco_cenas_do_roteiro(job: dict) -> str:
    cenas = _cenas_do_roteiro(job)
    if not cenas:
        return ""
    try:
        import roteiro_no_editor
        import roteiros_yt
        return "\n" + roteiro_no_editor.bloco_prompt(roteiros_yt.carregar_projeto(BASE_DIR, job["roteiro_id"]), cenas,
                                                     com_youtube=_youtube_marcado(job))
    except Exception:  # noqa: BLE001
        return ""


def _aplicar_cenas_do_roteiro(job: dict, segments: List[VideoSegment]) -> List[int]:
    """Depois da resposta da 1ª IA: o trecho de cada cena vira YouTube com a busca da cena — só com a fonte
    youtube marcada (sem ela, a IA já ilustrou as cenas com os bancos marcados)."""
    if not _youtube_marcado(job):
        return []
    cenas = _cenas_do_roteiro(job)
    if not cenas:
        return []
    import roteiro_no_editor
    return roteiro_no_editor.aplicar(segments, cenas)


def _usar_links_do_roteiro(job_id: str, job: dict) -> int:
    """As cenas que já têm link (com início/fim) escolhido na página do roteiro: baixa e corta sozinho, em segundo plano."""
    import roteiro_no_editor
    if not _youtube_marcado(job):
        return 0
    pend = job.get("pending_segments") or []
    por_id = {c["id"]: c for c in _cenas_do_roteiro(job)}
    n = 0
    for i, sg in enumerate(pend):
        c = por_id.get(sg.get("roteiro_cena"))
        if not c or sg.get("override_source") or sg.get("provider") != "youtube":
            continue
        esc = roteiro_no_editor.escolha_do_link(c, float(sg["end"]) - float(sg["start"]))
        it = _youtube_item(job, f"seg-{i}")
        if not esc or it is None or it.get("escolha"):
            continue
        it["ia"] = {"estado": "baixando", "msg": "📝 link escolhido no roteiro — baixando e cortando…", "log": []}

        def _run(item_id=f"seg-{i}", escolha=esc):
            it2 = _youtube_item(_JOBS.get(job_id) or {}, item_id)
            try:
                _youtube_baixar_e_aplicar(job_id, item_id, escolha)
                if it2 is not None:
                    it2["ia"] = {"estado": "pronto", "msg": f"📝 do roteiro: {escolha['titulo'][:80]}", "log": []}
            except Exception as exc:  # noqa: BLE001
                if it2 is not None:
                    it2["ia"] = {"estado": "erro", "msg": f"o link do roteiro não baixou ({str(exc)[:120]}) — escolha à mão", "log": []}
        threading.Thread(target=_run, daemon=True).start()
        n += 1
    return n


def _provider_do_projeto(job: dict) -> List[str]:
    if job.get("producao_pod"):  # 🏭 cenas ⏳ pendentes (completar depois, no editor) + 🕵️ fotos do modelo
        return ["adiado"] + [prov for _t, (_m, prov, chave, _r) in _PROJETOS_MIDIA.items() if job.get(chave)]
    for _t, (_m, prov, chave, _r) in _PROJETOS_MIDIA.items():
        if job.get(chave):
            return [prov]
    return []


def _recortar_midia(job: dict, caminho: str, ini: Optional[float], fim: Optional[float], com_audio: bool = True) -> str:
    """Pedaço [ini, fim] (segundos do próprio vídeo) de uma mídia do projeto, num arquivo
    do job. Sem início/fim (ou inválido): o arquivo inteiro."""
    if ini is None and fim is None:
        return caminho
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho],
                                   capture_output=True, text=True, timeout=30).stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        dur = 0.0
    ini = max(0.0, float(ini or 0))
    fim = float(fim) if fim is not None else (dur or ini + 5)
    if dur:
        fim = min(fim, dur)
    if fim - ini < 0.3:
        return caminho
    pasta = os.path.join(_job_dir(job["job_id"]), "midias_projeto")
    os.makedirs(pasta, exist_ok=True)
    dest = os.path.join(pasta, f"{os.path.splitext(os.path.basename(caminho))[0][:40]}_{ini:.1f}_{fim:.1f}{'' if com_audio else '_mudo'}.mp4")
    if not os.path.isfile(dest):
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.3f}", "-i", caminho, "-t", f"{fim - ini:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
        cmd += (["-c:a", "aac", "-b:a", "192k"] if com_audio else ["-an"]) + [dest]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.isfile(dest):
            return caminho
    return dest


def _aplicar_cortes_do_projeto(job: dict) -> int:
    """Cortes da IA com "midia" (vídeo do projeto com o ÁUDIO ORIGINAL, a narração pausa):
    recorta o pedaço e já deixa o corte resolvido. Devolve quantos."""
    pj = _projeto_do_job(job)
    if not pj:
        return 0
    import midia_transcricao as mt
    _t, mod, p, _prov = pj
    por_id = {m["id"].upper(): m for m in mod.midias_para_editor(BASE_DIR, p)}
    n = 0
    for c in job.get("cutaway_suggestions") or []:
        m = por_id.get(str(c.get("midia") or "").upper())
        if not m or c.get("resolved_path"):
            continue
        c["resolved_path"] = _recortar_midia(job, m["caminho"], mt.segundos(c.get("inicio")), mt.segundos(c.get("fim")))
        c["audio_mode"] = c.get("audio_mode") or "pause"
        c["do_projeto"] = m["id"]
        n += 1
    return n


def _aplicar_produto(job: dict, segmentos: list) -> int:
    """Trechos com provider "produto"/"material" (query = ID da mídia) viram o arquivo
    do projeto (override local). ID desconhecido: o trecho cai pros bancos marcados
    com a busca do "visual". Devolve quantos usaram arquivo do projeto."""
    pj = _projeto_do_job(job)
    if not pj:
        return 0
    _t, mod, p, prov_proj = pj
    por_id = {m["id"].upper(): m for m in mod.midias_para_editor(BASE_DIR, p)}
    reserva = next((x for x in job.get("providers") or [] if x not in ("produto", "material", "youtube", "flow", "runpod", "wikipedia")), "pexels")
    n = 0
    for s in segmentos:
        d = s if isinstance(s, dict) else None
        prov = d.get("provider") if d is not None else getattr(s, "provider", None)
        if prov not in ("produto", "material"):
            continue
        bruto = str((d.get("query") if d is not None else s.query) or "").strip().upper()
        q, _, pedaco = bruto.partition("@")  # "M3@12-25": só esse pedaço do vídeo (sem o som, sob a narração)
        q = re.sub(r"[^A-Z0-9]", "", q)
        m = por_id.get(q)
        if m:
            arquivo = m["caminho"]
            if pedaco and m["tipo"] == "video":
                import midia_transcricao as mt
                a_, _, b_ = pedaco.replace("–", "-").partition("-")
                arquivo = _recortar_midia(job, arquivo, mt.segundos(a_), mt.segundos(b_), com_audio=False)
            ov = {"source": "local_file", "value": arquivo, "kind": "image" if m["tipo"] == "foto" else "video"}
            mt = "image" if m["tipo"] == "foto" else "video"
            if d is not None:
                d["override_source"], d["media_type"], d["venda_midia"] = ov, mt, m["id"]
            else:
                s.override_source, s.media_type = ov, mt
            n += 1
        else:
            vis = (d.get("visual") if d is not None else getattr(s, "visual", None)) or ("product close up" if prov_proj == "produto" else "dark city street night")
            if d is not None:
                d["provider"], d["query"] = reserva, vis
            else:
                s.provider, s.query = reserva, vis
    return n


def _idioma_do_zip(zip_path: str) -> Dict[str, Any]:
    """Idioma de um .zip de narração: o `info.json` do Gerador de voz; sem ele,
    adivinha pelo texto da legenda. {"codigo", "origem"} (codigo None = não sei)."""
    import idiomas
    try:
        with zipfile.ZipFile(zip_path) as zf:
            nomes = [n for n in zf.namelist() if "__MACOSX" not in n]
            info = next((n for n in nomes if os.path.basename(n).lower() == "info.json"), None)
            if info:
                cod = idiomas.ler_info(zf.read(info).decode("utf-8", "replace"))
                if cod:
                    return {"codigo": cod, "origem": "zip"}
            srt = next((n for n in nomes if n.lower().endswith(".srt")), None)
            if srt:
                cod = idiomas.detectar_do_texto(_decodificar_srt(zf.read(srt)))
                if cod:
                    return {"codigo": cod, "origem": "legenda"}
    except (zipfile.BadZipFile, OSError, KeyError):
        pass
    return {"codigo": None, "origem": None}


def _hint_idioma(language: Optional[str]) -> str:
    """Como o idioma do job entra nos prompts (\"português do Brasil (pt-BR)\")."""
    import idiomas
    return idiomas.nome_para_prompt(idiomas.normalizar(language) or "pt")


@app.route("/transcribe", methods=["POST"])
def transcribe():
    audio_file = request.files.get("audio")
    if not audio_file or not audio_file.filename:
        return render_template("index.html", providers=DEFAULT_PROVIDERS, error="Selecione um arquivo de áudio.")

    try:
        interval_seconds = float(request.form.get("interval_seconds", 7))
    except (TypeError, ValueError):
        return render_template(
            "index.html", providers=DEFAULT_PROVIDERS,
            error="'Trocar de vídeo a cada quantos segundos' precisa ser um número.",
        )
    if not (1.0 <= interval_seconds <= 120.0):
        return render_template(
            "index.html", providers=DEFAULT_PROVIDERS,
            error="'Trocar de vídeo a cada quantos segundos' precisa estar entre 1 e 120.",
        )
    ritmo_cenas = request.form.get("ritmo_cenas") if request.form.get("ritmo_cenas") in ("livre", "fixo") else "livre"

    selected_providers = [p for p in request.form.getlist("providers") if p in DEFAULT_PROVIDERS] or DEFAULT_PROVIDERS
    import idiomas
    language_escolhido = idiomas.normalizar(request.form.get("language", "auto"))  # None = automático
    language = language_escolhido
    language_origem = "escolhido" if language_escolhido else None
    extra_instructions = request.form.get("extra_instructions", "").strip()
    add_word_captions = request.form.get("add_word_captions") == "on"
    caption_style = _parse_caption_style_from_form(request.form)
    usar_wikipedia_inteligente = request.form.get("usar_wikipedia_inteligente") == "on"
    if usar_wikipedia_inteligente and "wikipedia" not in selected_providers:
        # a checkbox já implica em usar o provedor -- não faz sentido
        # pedir a busca inteligente sem ele estar disponível pra IA.
        selected_providers = selected_providers + ["wikipedia"]
    usar_buscadores_inteligente = request.form.get("usar_buscadores_inteligente") == "on"
    if usar_buscadores_inteligente and not any(p in selected_providers for p in BROWSER_IMAGE_SEARCH_PROVIDERS):
        # mesmo raciocínio do wikipedia acima -- se marcou a busca
        # inteligente mas não tem NENHUM dos 4 buscadores selecionado,
        # adiciona pelo menos um (bing, o mais "genérico"/conhecido)
        # pra ter algum provedor de verdade pra confirmar os termos.
        selected_providers = selected_providers + ["bing"]

    job_id = uuid.uuid4().hex[:12]
    job_dir = _job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)

    safe_filename = secure_filename(audio_file.filename)
    segments_do_zip = None  # só é preenchido se o upload for um .zip com legenda pronta (pula a transcrição)
    chamadas_do_zip: List[Dict[str, Any]] = []
    if os.path.splitext(safe_filename)[1].lower() == ".zip":
        zip_path = os.path.join(job_dir, "upload.zip")
        audio_file.save(zip_path)
        try:
            audio_path, segments_do_zip = _extrair_audio_e_srt_do_zip(zip_path, job_dir)
            # chamadas (inscreva-se/venda/link): o chamadas.json do Gerar voz e/ou
            # marcadores [[INSCREVA: ...]] escritos na própria legenda
            segments_do_zip, _ch_srt = __import__("chamadas").do_srt(segments_do_zip)
            chamadas_do_zip = _chamadas_do_zip(zip_path) + _ch_srt
            if not language:  # "Automático": o idioma gravado no .zip (ou o da legenda)
                _iz = _idioma_do_zip(zip_path)
                language, language_origem = _iz["codigo"], _iz["origem"]
        except lg.LegendaError as exc:
            return render_template(
                "index.html", providers=DEFAULT_PROVIDERS,
                error=f"Não consegui usar esse .zip: {exc}",
            )
    else:
        audio_path = os.path.join(job_dir, "narracao" + os.path.splitext(safe_filename)[1])
        audio_file.save(audio_path)

    music_path = None
    music_file = request.files.get("music")
    if music_file and music_file.filename:
        safe_music_filename = secure_filename(music_file.filename)
        music_path = os.path.join(job_dir, "trilha" + os.path.splitext(safe_music_filename)[1])
        music_file.save(music_path)

    try:
        music_volume = float(request.form.get("music_volume", 0.18))
    except (TypeError, ValueError):
        music_volume = 0.18
    music_volume = max(0.0, min(music_volume, 1.0))

    _JOBS[job_id] = {
        "job_id": job_id,
        "audio_path": audio_path,
        "music_path": music_path,
        "music_volume": music_volume,
        "providers": selected_providers,
        "add_word_captions": add_word_captions,
        "caption_style": caption_style,
        "status": "transcrevendo",
        "fase": "Transcrevendo o áudio...",
        "created_at": time.time(),
        "cancel_requested": False,
        "original_filename": audio_file.filename,
        # guardados aqui (em vez de só no fechamento de _run_transcription)
        # porque, no modo "fontes da Wikipedia", a etapa de montar o
        # prompt final só acontece numa requisição SEPARADA e bem depois
        # (quando o usuário cola a resposta do prompt de busca de termos)
        # -- esse fechamento original não vai mais existir nesse momento.
        "interval_seconds": interval_seconds,
        "ritmo_cenas": ritmo_cenas,
        "language": language or "pt", "language_origem": language_origem,
        "extra_instructions": extra_instructions,
        "usar_wikipedia_inteligente": usar_wikipedia_inteligente,
        "usar_buscadores_inteligente": usar_buscadores_inteligente,
        # proporção fotos × vídeos (opcional; ver mix_midia.py)
        "mix_midia": __import__("mix_midia").do_form(request.form),
        "bibliotecas": _bibliotecas_do_form(request.form, selected_providers),
        "chamadas": chamadas_do_zip,
    }
    # 🛒 venda / 🕵️ modelo de vídeo: o escolhido aqui ("venda:ID" / "dossie:ID"), ou o que veio no
    # info.json do .zip do Gerar voz
    _pm = (request.form.get("projeto_midias") or "").strip()
    _tipo, _, _pid = _pm.partition(":")
    if not _pid and (request.form.get("venda_id") or "").strip():
        _tipo, _pid = "venda", request.form["venda_id"].strip()
    if not _pid and segments_do_zip is not None:
        _tipo, _pid = _projeto_do_zip(os.path.join(job_dir, "upload.zip"))
    if _pid and _tipo == "roteiro":  # 📝 projeto do Roteiro do YouTube escolhido aqui
        if re.fullmatch(r"[0-9a-f]{6,40}", _pid):
            _JOBS[job_id]["roteiro_id"] = _pid
            # (v84_92) não marca mais o "youtube" sozinho: as cenas só viram YouTube se VOCÊ marcou a fonte
    elif _pid:
        _ligar_projeto(_JOBS[job_id], _tipo, _pid)
    if segments_do_zip is not None and not _JOBS[job_id].get("roteiro_id"):  # 📝 Roteiro do YouTube: capítulos no tempo do vídeo final
        _rid = _roteiro_do_zip(os.path.join(job_dir, "upload.zip"))
        if _rid:
            _JOBS[job_id]["roteiro_id"] = _rid
    if _formato_do_form(request.form):
        _JOBS[job_id]["orientation"] = _formato_do_form(request.form)
    perf = PerfLog(_job_dir(job_id), job_id=job_id)
    _PERF_LOGS[job_id] = perf
    _save_state(job_id)

    def _run_transcription():
        try:
            if segments_do_zip is not None:
                # .zip com áudio + .srt prontos -- pula a transcrição
                # inteira. O .srt não tem timestamp por palavra (só por
                # bloco/linha), então legenda-por-palavra não tem como
                # funcionar nesse caminho -- desliga em vez de travar ou
                # fingir que funcionou; a pessoa ainda ganhou a
                # transcrição pronta, que era o pedido principal.
                segments = segments_do_zip
                if add_word_captions:
                    job_tmp = _JOBS[job_id]
                    job_tmp["add_word_captions"] = False
                    job_tmp["aviso_legenda_palavra_desligada"] = (
                        "Legenda palavra-por-palavra desligada: o .srt enviado não tem "
                        "timestamp por palavra (só por bloco), então não dá pra gerar esse "
                        "tipo de legenda a partir dele."
                    )
            else:
                whisper_device = load_site_config().get("whisper_device", "auto")
                with perf.timed("transcricao", device=whisper_device):
                    _info_whisper: Dict[str, Any] = {}
                    segments = transcribe_audio(
                        audio_path, model_size="base", language=language, word_timestamps=add_word_captions,
                        device=whisper_device, info=_info_whisper,
                    )
                if not language:  # "Automático" com áudio solto: o idioma que o Whisper detectou
                    _det = idiomas.normalizar(_info_whisper.get("language")) or idiomas.detectar_do_texto(
                        " ".join(sg["text"] for sg in segments))
                    if _det:
                        _JOBS[job_id]["language"] = _det
                        _JOBS[job_id]["language_origem"] = "whisper"
            total_duration = segments[-1]["end"]
            job = _JOBS[job_id]
            job["segments"] = segments
            job["total_duration"] = total_duration
            if job["add_word_captions"]:
                job["word_timestamps"] = [w for seg in segments for w in seg.get("words", [])]

            if usar_wikipedia_inteligente:
                # Modo "fontes da Wikipedia": em vez da heurística de texto
                # decidir sozinha quais termos pesquisar, é a PRÓPRIA IA
                # (que lê o roteiro inteiro com contexto) quem sugere --
                # gera esse prompt intermediário e PARA aqui; o resto
                # (buscar de verdade na Wikipedia + montar o prompt
                # principal) só continua depois que o usuário colar a
                # resposta dessa etapa (ver job_colar_termos_wikipedia()).
                with perf.timed("montar_prompt_termos_wikipedia"):
                    job["prompt_termos_wikipedia"] = build_wikipedia_search_terms_prompt(
                        segments, language_hint=_hint_idioma(_JOBS[job_id]["language"]),
                    )
                job["status"] = "aguardando_termos_wikipedia"
                job["fase"] = "Pronto! Cole a resposta da IA com os termos de busca da Wikipedia."
            elif usar_buscadores_inteligente:
                # Mesma ideia do modo Wikipedia acima, mas pros 4
                # buscadores de imagem por navegador (bing/brave/yandex/
                # startpage) -- ver buscadores_enrichment.py. Se os dois
                # checkboxes foram marcados ao mesmo tempo, o Wikipedia
                # tem prioridade (ramo acima) e este aqui nem roda.
                with perf.timed("montar_prompt_termos_buscadores"):
                    job["prompt_termos_buscadores"] = build_buscadores_search_terms_prompt(
                        segments, language_hint=_hint_idioma(_JOBS[job_id]["language"]),
                    )
                job["status"] = "aguardando_termos_buscadores"
                job["fase"] = "Pronto! Cole a resposta da IA com os termos de busca pros buscadores de imagem."
            else:
                with perf.timed("montar_prompt"):
                    if __import__("acervos").so_acervo(selected_providers):
                        # único banco marcado é o acervo local de anime —
                        # usa o prompt DEDICADO (orientação sobre queries
                        # concretas, keyword_weight/semantic_weight, etc.)
                        # em vez do genérico pensado pra stock footage real.
                        prompt_text = build_animepexels_prompt(
                            segments,
                            interval_seconds=interval_seconds, ritmo=ritmo_cenas,
                            language_hint=_hint_idioma(_JOBS[job_id]["language"]),
                            extra_instructions=extra_instructions, bibliotecas=_bibliotecas_prompt(job_id), provider=_JOBS[job_id]["providers"][0] if job_id in _JOBS else "animepexels")
                    else:
                        prompt_text = build_prompt(
                            segments,
                            interval_seconds=interval_seconds, ritmo=ritmo_cenas,
                            providers=selected_providers,
                            language_hint=_hint_idioma(_JOBS[job_id]["language"]),
                            extra_instructions=extra_instructions, usar_templates=_usa_templates_cena(),
                            mix_midia=job.get("mix_midia"), formato=_orientacao_do_job(job), bibliotecas=_bibliotecas_prompt(job_id))
                job["prompt"] = _com_produto(job, prompt_text)
                job["status"] = "aguardando_json"
                job["fase"] = "Pronto!"
        except TranscriptionError as exc:
            _JOBS[job_id]["status"] = "erro_transcricao"
            _JOBS[job_id]["error"] = str(exc)
        except Exception:  # noqa: BLE001
            _JOBS[job_id]["status"] = "erro_transcricao"
            _JOBS[job_id]["error"] = f"Erro inesperado na transcrição:\n{traceback.format_exc()}"
        finally:
            perf.save()
            _save_state(job_id)
            _j = _JOBS.get(job_id) or {}
            _avisar_fim(f"📝 Transcrição de “{_nome_job(job_id)}”",
                        _j.get("error") if str(_j.get("status", "")).startswith("erro") else None,
                        f"/job/{job_id}/transcribing", "transcricao", str(_j.get("fase") or ""))

    threading.Thread(target=_run_transcription, daemon=True).start()

    return redirect(url_for("transcribing_status_page", job_id=job_id))


@app.route("/job/<job_id>/transcribing", methods=["GET"])
def transcribing_status_page(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    return render_template("transcribing.html", job=job)


@app.route("/job/<job_id>/transcribing-status", methods=["GET"])
def transcribing_status_api(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job não encontrado"}), 404
    return jsonify({"status": job.get("status"), "error": job.get("error"), "fase": job.get("fase")})


# --------------------------------------------------------------------- #
# Modo "fontes da Wikipedia" — etapa intermediária de duas rodadas:
# 1) gera um prompt pedindo pra IA sugerir termos de busca (baseado no
#    roteiro inteiro, com contexto real, em vez da heurística de texto);
# 2) o usuário cola a resposta aqui; o site então PESQUISA DE VERDADE
#    esses termos na Wikipedia e só então monta o prompt principal de
#    edição, já com as entidades confirmadas embutidas.
# --------------------------------------------------------------------- #

@app.route("/job/<job_id>/termos-wikipedia", methods=["GET"])
def show_termos_wikipedia(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado (talvez o servidor tenha reiniciado).", 404
    return render_template("termos_wikipedia.html", job=job, error=None)


@app.route("/job/<job_id>/termos-wikipedia", methods=["POST"])
def submit_termos_wikipedia(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    raw_resposta = request.form.get("resposta_termos", "")
    try:
        termos = parse_wikipedia_search_terms_response(raw_resposta)
    except PromptBuilderError as exc:
        return render_template("termos_wikipedia.html", job=job, error=str(exc))

    job["status"] = "buscando_termos_wikipedia"
    job["fase"] = (
        f"Pesquisando {len(termos)} termo(s) na Wikipedia..." if termos
        else "Nenhum termo sugerido pela IA — montando o roteiro sem entidades da Wikipedia..."
    )
    perf = _PERF_LOGS.get(job_id)

    def _run_busca_e_prompt_final():
        try:
            with (perf.timed("busca_wikipedia") if perf else nullcontext()):
                confirmadas = wikipedia_enrichment.buscar_entidades_confirmadas_na_wikipedia(termos) if termos else []
            job["wikipedia_entidades"] = confirmadas
            if confirmadas:
                nomes = ", ".join(e["termo"] for e in confirmadas)
                job["fase"] = f"Confirmado na Wikipedia: {nomes}. Montando o roteiro..."
            else:
                job["fase"] = "Nenhum dos termos sugeridos foi confirmado na Wikipedia. Montando o roteiro..."

            segments = job["segments"]
            with (perf.timed("montar_prompt") if perf else nullcontext()):
                if __import__("acervos").so_acervo(job["providers"]):
                    prompt_text = build_animepexels_prompt(
                        segments, interval_seconds=job["interval_seconds"], ritmo=job.get("ritmo_cenas", "livre"),
                        language_hint=_hint_idioma(job["language"]),
                        extra_instructions=job["extra_instructions"], bibliotecas=_bibliotecas_prompt(job_id), provider=_JOBS[job_id]["providers"][0] if job_id in _JOBS else "animepexels")
                else:
                    prompt_text = build_prompt(
                        segments, interval_seconds=job["interval_seconds"], ritmo=job.get("ritmo_cenas", "livre"), providers=job["providers"],
                        language_hint=_hint_idioma(job["language"]),
                        extra_instructions=job["extra_instructions"],
                        wikipedia_entidades_confirmadas=confirmadas, usar_templates=_usa_templates_cena(),
                        mix_midia=job.get("mix_midia"), formato=_orientacao_do_job(job), bibliotecas=_bibliotecas_prompt(job_id))
            job["prompt"] = _com_produto(job, prompt_text)
            job["status"] = "aguardando_json"
            job["fase"] = "Pronto!"
        except Exception:  # noqa: BLE001
            job["status"] = "erro_transcricao"
            job["error"] = f"Erro ao buscar na Wikipedia/montar o prompt:\n{traceback.format_exc()}"
        finally:
            if perf:
                perf.save()
            _save_state(job_id)
            _avisar_fim(f"📝 Prompt de “{_nome_job(job_id)}”", job.get("error") if str(job.get("status", "")).startswith("erro") else None,
                        f"/job/{job_id}/transcribing", "transcricao", "O prompt das cenas está pronto.")

    threading.Thread(target=_run_busca_e_prompt_final, daemon=True).start()
    return redirect(url_for("transcribing_status_page", job_id=job_id))


# --------------------------------------------------------------------- #
# Modo "este vídeo usa buscadores de imagem" — mesma ideia de duas
# rodadas do modo Wikipedia acima, mas pros 4 buscadores de imagem por
# navegador (bing/brave/yandex/startpage). Ver buscadores_enrichment.py.
# --------------------------------------------------------------------- #

@app.route("/job/<job_id>/termos-buscadores", methods=["GET"])
def show_termos_buscadores(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado (talvez o servidor tenha reiniciado).", 404
    return render_template("termos_buscadores.html", job=job, error=None)


@app.route("/job/<job_id>/termos-buscadores", methods=["POST"])
def submit_termos_buscadores(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    raw_resposta = request.form.get("resposta_termos", "")
    try:
        termos = parse_wikipedia_search_terms_response(raw_resposta)  # mesmo formato/parser do modo Wikipedia
    except PromptBuilderError as exc:
        return render_template("termos_buscadores.html", job=job, error=str(exc))

    buscadores_providers = [p for p in job["providers"] if p in BROWSER_IMAGE_SEARCH_PROVIDERS]
    job["status"] = "buscando_termos_buscadores"
    job["fase"] = (
        f"Pesquisando {len(termos)} termo(s) nos buscadores de imagem..." if termos
        else "Nenhum termo sugerido pela IA — montando o roteiro sem confirmação prévia..."
    )
    perf = _PERF_LOGS.get(job_id)

    def _run_busca_e_prompt_final_buscadores():
        try:
            with (perf.timed("busca_buscadores") if perf else nullcontext()):
                confirmados = (
                    buscadores_enrichment.buscar_confirmados_nos_buscadores(termos, buscadores_providers)
                    if termos and buscadores_providers else []
                )
            job["buscadores_confirmados"] = confirmados
            if confirmados:
                nomes = ", ".join(e["termo"] for e in confirmados)
                job["fase"] = f"Confirmado nos buscadores de imagem: {nomes}. Montando o roteiro..."
            else:
                job["fase"] = "Nenhum dos termos sugeridos foi confirmado. Montando o roteiro..."

            segments = job["segments"]
            with (perf.timed("montar_prompt") if perf else nullcontext()):
                if __import__("acervos").so_acervo(job["providers"]):
                    prompt_text = build_animepexels_prompt(
                        segments, interval_seconds=job["interval_seconds"], ritmo=job.get("ritmo_cenas", "livre"),
                        language_hint=_hint_idioma(job["language"]),
                        extra_instructions=job["extra_instructions"], bibliotecas=_bibliotecas_prompt(job_id), provider=_JOBS[job_id]["providers"][0] if job_id in _JOBS else "animepexels")
                else:
                    prompt_text = build_prompt(
                        segments, interval_seconds=job["interval_seconds"], ritmo=job.get("ritmo_cenas", "livre"), providers=job["providers"],
                        language_hint=_hint_idioma(job["language"]),
                        extra_instructions=job["extra_instructions"],
                        buscadores_confirmados=confirmados, usar_templates=_usa_templates_cena(),
                        mix_midia=job.get("mix_midia"), formato=_orientacao_do_job(job), bibliotecas=_bibliotecas_prompt(job_id))
            job["prompt"] = _com_produto(job, prompt_text)
            job["status"] = "aguardando_json"
            job["fase"] = "Pronto!"
        except Exception:  # noqa: BLE001
            job["status"] = "erro_transcricao"
            job["error"] = f"Erro ao buscar nos buscadores de imagem/montar o prompt:\n{traceback.format_exc()}"
        finally:
            if perf:
                perf.save()
            _save_state(job_id)
            _avisar_fim(f"📝 Prompt de “{_nome_job(job_id)}”", job.get("error") if str(job.get("status", "")).startswith("erro") else None,
                        f"/job/{job_id}/transcribing", "transcricao", "O prompt das cenas está pronto.")

    threading.Thread(target=_run_busca_e_prompt_final_buscadores, daemon=True).start()
    return redirect(url_for("transcribing_status_page", job_id=job_id))


# --------------------------------------------------------------------- #
# Página 2: mostra o prompt pra copiar, e o formulário pra colar o JSON
# --------------------------------------------------------------------- #

@app.route("/job/<job_id>/prompt", methods=["GET"])
def show_prompt(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado (talvez o servidor tenha reiniciado).", 404
    return render_template("prompt.html", job=job, opcoes=_opcoes_do_job(job), all_providers=DEFAULT_PROVIDERS)


@app.route("/job/<job_id>/atualizar-providers", methods=["POST"])
def atualizar_providers(job_id: str):
    """Troca os bancos marcados DEPOIS que o áudio já foi transcrito, sem
    precisar transcrever de novo -- reaproveita `job["segments"]` (já
    guardados) e só remonta o texto do prompt (passo 2) com a lista nova.
    Pensado pra quando a pessoa muda de ideia sobre quais bancos usar
    depois de já ter visto o prompt original."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado (talvez o servidor tenha reiniciado).", 404
    if not job.get("segments"):
        return (
            "Esse job ainda não tem uma transcrição pronta -- espere a transcrição "
            "terminar antes de trocar os bancos.", 400,
        )

    novos_providers = [p for p in request.form.getlist("providers") if p in DEFAULT_PROVIDERS]
    if not novos_providers:
        # nada marcado -- não dá pra montar prompt sem nenhum banco; mantém
        # como estava em vez de deixar o job sem providers nenhum
        return redirect(url_for("show_prompt", job_id=job_id))

    job["providers"] = novos_providers
    if request.form.get("mix_enviado") == "1":
        job["mix_midia"] = __import__("mix_midia").do_form(request.form)
    if any(k.startswith("bib_") for k in request.form):
        job["bibliotecas"] = _bibliotecas_do_form(request.form, novos_providers)
    job.pop("_bibliotecas_cache", None)  # bancos mudaram: relê obras/personagens do acervo
    _remontar_prompt(job_id, job)
    return redirect(url_for("show_prompt", job_id=job_id))


def _remontar_prompt(job_id: str, job: dict) -> None:
    """Monta de novo o texto do prompt com os bancos/acervos atuais do job."""
    novos_providers = job["providers"]
    segments = job["segments"]
    if __import__("acervos").so_acervo(novos_providers):
        prompt_text = build_animepexels_prompt(
            segments, interval_seconds=job["interval_seconds"], ritmo=job.get("ritmo_cenas", "livre"),
            language_hint=_hint_idioma(job["language"]),
            extra_instructions=job["extra_instructions"], bibliotecas=_bibliotecas_prompt(job_id), provider=_JOBS[job_id]["providers"][0] if job_id in _JOBS else "animepexels")
    else:
        prompt_text = build_prompt(
            segments, interval_seconds=job["interval_seconds"], ritmo=job.get("ritmo_cenas", "livre"), providers=novos_providers,
            language_hint=_hint_idioma(job["language"]),
            extra_instructions=job["extra_instructions"],
            wikipedia_entidades_confirmadas=job.get("wikipedia_entidades"), usar_templates=_usa_templates_cena(),
            mix_midia=job.get("mix_midia"), formato=_orientacao_do_job(job), bibliotecas=_bibliotecas_prompt(job_id))
    job["prompt"] = _com_produto(job, prompt_text)
    _save_state(job_id)


# Opções que a pessoa pode escolher SÓ PARA UM VÍDEO, na página do prompt —
# sobrescrevem a config do site (Configurações) apenas nesse job.
_JOB_CFG_OVERRIDE_KEYS = ("browser_visible", "evitar_repeticao_clipes")


@app.context_processor
def _formato_padrao_ctx():
    try:
        return {"formato_padrao": load_site_config().get("orientation", "16:9")}
    except Exception:  # noqa: BLE001
        return {"formato_padrao": "16:9"}


# 🔄 v84_102: o servidor que está rodando é o código que está no disco? (atualizou o site com ele aberto → as páginas
# novas chamam rotas que o processo velho não tem e os botões dão 404). base.html avisa com uma faixa no topo.
_CODIGO_ID = uuid.uuid4().hex[:12]


def _mtimes_codigo() -> Dict[str, float]:
    out = {}
    try:
        for nome in os.listdir(BASE_DIR):
            if nome.endswith(".py") and not nome.startswith("test_"):
                try:
                    out[nome] = os.path.getmtime(os.path.join(BASE_DIR, nome))
                except OSError:
                    pass
    except OSError:
        pass
    return out


_CODIGO_NO_INICIO = _mtimes_codigo()


@app.route("/versao-codigo")
def versao_codigo():
    agora = _mtimes_codigo()
    mudou = sorted(n for n, t in agora.items() if _CODIGO_NO_INICIO.get(n) != t)
    return jsonify({"id": _CODIGO_ID, "desatualizado": bool(mudou), "arquivos": mudou[:12]})


@app.context_processor
def _versao_codigo_ctx():
    return {"versao_codigo": _CODIGO_ID}


@app.context_processor
def _idiomas_ctx():
    import idiomas
    return {"idiomas_lista": [(k, v[0]) for k, v in idiomas.IDIOMAS.items()]}


def _orientacao_do_job(job: dict) -> str:
    """Formato do vídeo DESTE job (16:9, 9:16 ou 1:1): o escolhido no envio do
    áudio / no Estúdio; sem escolha, o das Configurações."""
    from site_config import VALID_ORIENTATIONS
    o = (job or {}).get("orientation")
    return o if o in VALID_ORIENTATIONS else load_site_config().get("orientation", "16:9")


def _formato_do_form(form, nome: str = "formato") -> Optional[str]:
    from site_config import VALID_ORIENTATIONS
    v = form.get(nome)
    return v if v in VALID_ORIENTATIONS else None


def _cartao_fundo_do_form(bruto: Any) -> Optional[Dict[str, Any]]:
    """🪧 config do fundo dos cartões que o Estúdio manda (JSON) → validada. None = não veio."""
    if not bruto:
        return None
    try:
        d = json.loads(bruto) if isinstance(bruto, str) else dict(bruto)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    import video_assembler as _va
    out: Dict[str, Any] = {"modo": "video" if d.get("modo") == "video" else "gerado",
                           "estilo": d.get("estilo") if d.get("estilo") in _va.FUNDOS_CARTAO else "cor_gradiente",
                           "cor": d["cor"].upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", str(d.get("cor") or "")) else "",
                           "biblioteca": re.sub(r"[^\w-]", "", str(d.get("biblioteca") or ""))[:40],
                           "busca": " ".join(str(d.get("busca") or "").split())[:120]}
    for k, padrao, a, b in (("desfocar", 4.0, 0.0, 30.0), ("escurecer", 0.15, 0.0, 0.6)):
        try:
            out[k] = max(a, min(b, float(d.get(k, padrao))))
        except (TypeError, ValueError):
            out[k] = padrao
    return out


def _job_site_cfg(job: dict) -> dict:
    """Config do site + o que a pessoa escolheu só pra este vídeo na página
    do prompt (`job["cfg_overrides"]`). Usada nas prévias e na montagem."""
    cfg = load_site_config()
    if job.get("providers"):  # v84_110: Flow sem crédito nenhum → pesquisa só nos mecanismos marcados pra este vídeo
        cfg["_providers_marcados"] = list(job["providers"])
    for chave, valor in (job.get("cfg_overrides") or {}).items():
        if chave in _JOB_CFG_OVERRIDE_KEYS and isinstance(valor, bool):
            cfg[chave] = valor
    _est = ((job.get("ia") or {}).get("ficha") or {}).get("estilo_imagem")  # 🎞️ a ficha diz se o vídeo é de imagens reais
    if _est:
        cfg["_estilo_ficha"] = _est
    # transição escolhida no editor só pra este vídeo ("site" = a das Configurações)
    # formato (16:9 / 9:16 / 1:1) escolhido pra ESTE vídeo
    if job.get("orientation"):
        cfg["orientation"] = _orientacao_do_job(job)
    # resolução escolhida no modal "Montar" do Estúdio (só deste vídeo) — antes
    # ficava guardada no job mas a montagem usava a das Configurações.
    if job.get("export_quality") in __import__("qualidade_export").RESOLUCOES:
        cfg["export_quality"] = job["export_quality"]
    editor = job.get("editor_defaults") or {}
    if "filtro_cor" in editor:  # inclusive "original" (sem filtro): o que o Estúdio mostra é o que sai
        cfg["filtro_cor"] = editor["filtro_cor"]
    if isinstance(editor.get("paleta"), dict):
        cfg["paleta"] = editor["paleta"]
    cf = dict(editor.get("cartao_fundo") or {})  # 🪧 fundo dos cartões: o clipe da biblioteca vira o caminho do arquivo
    if cf.get("biblioteca"):
        it = next((x for x in job.get("media_library") or [] if x.get("id") == cf["biblioteca"]), None)
        if it and os.path.isfile(it.get("path") or ""):
            cf["video_path"] = it["path"]
    if not cf.get("cor") and (editor.get("paleta") or {}).get("primaria"):
        cf["cor"] = editor["paleta"]["primaria"]
    if cf:
        cfg["cartao_fundo"] = cf
    if isinstance(editor.get("sons_auto"), dict):
        cfg["sons_auto"] = editor["sons_auto"]
    if editor.get("sons_volume") is not None:
        cfg["sons_volume"] = editor["sons_volume"]
    tipo = editor.get("transition_type")
    if tipo and tipo != "site" and tipo in {v for v, _r in TRANSITION_LABELS}:
        cfg["transition_type"] = tipo
        try:
            cfg["transition_duration"] = max(0.1, min(3.0, float(editor.get("transition_duration", cfg.get("transition_duration", 0.6)))))
        except (TypeError, ValueError):
            pass
    # 🚫 v84_72: só os bancos/buscadores MARCADOS neste vídeo. Antes a reserva (quando um banco falha) vinha da
    # prioridade das Configurações — por padrão TODOS os bancos — e os 4 buscadores de imagem rodavam sempre,
    # cada um abrindo um navegador.
    provs = [p for p in (job.get("providers") or []) if isinstance(p, str) and p]
    if provs:
        base = cfg.get("provider_priority") or ALL_PROVIDERS
        cfg["provider_priority"] = [p for p in base if p in provs] + [p for p in provs if p not in base]
        cfg["provedores_do_job"] = provs
    return cfg


def _opcoes_do_job(job: dict) -> dict:
    """Estado inicial dos checkboxes da página do prompt, já no sentido
    que aparece pra pessoa (ocultar navegador / não repetir)."""
    cfg = _job_site_cfg(job)
    return {
        "ocultar_navegador": not cfg.get("browser_visible", False),
        "nao_repetir_midia": bool(cfg.get("evitar_repeticao_clipes", True)),
    }


def _aplicar_mix_midia(job: dict, parsed=None) -> None:
    """Confere a proporção fotos × vídeos escolhida (mix_midia.py) nos trechos que
    a IA mandou e ajusta o que fugiu dela (nos dicts do job E nos VideoSegment de
    `parsed`, que alimentam as prévias); o aviso aparece no editor."""
    import mix_midia
    from dataclasses import replace as _replace
    mix = job.get("mix_midia") or {}
    if not mix or not job.get("pending_segments"):
        return
    _n, avisos = mix_midia.aplicar(job["pending_segments"], mix, job.get("providers") or [])
    if _n and parsed is not None and len(parsed.segments) == len(job["pending_segments"]):
        parsed.segments[:] = [
            _replace(seg, provider=d.get("provider", seg.provider), media_type=d.get("media_type") or "video")
            for seg, d in zip(parsed.segments, job["pending_segments"])
        ]
    if avisos:
        job["aviso_mix_midia"] = " ".join(avisos)
    else:
        job.pop("aviso_mix_midia", None)


# ------------------------------------------------------------------ acervos locais (anime / filmes e séries)
_BIBLIOTECAS_LOCAIS = ("animepexels", "moviepexels", "animepexels_online", "moviepexels_online")  # acervos.TODOS


def _juntar_varios(valor) -> str:
    """Várias obras/personagens separados por | ("Naruto | Death Note"): limpa e junta (até 12)."""
    itens = []
    for x in str(valor or "").split("|"):
        x = x.strip()[:120]
        if x and x not in itens:
            itens.append(x)
    return " | ".join(itens[:12])


def _bibliotecas_do_form(form, providers: List[str], sufixo: str = "") -> dict:
    """Obra e personagem/ator escolhidos pra cada acervo local marcado
    (campos bib_<provedor>_obra / bib_<provedor>_personagem)."""
    out = {}
    for prov in _BIBLIOTECAS_LOCAIS:
        if prov not in providers:
            continue
        obra = _juntar_varios(form.get(f"bib_{prov}_obra{sufixo}"))
        pers = _juntar_varios(form.get(f"bib_{prov}_personagem{sufixo}"))
        if obra or pers:
            out[prov] = {"obra": obra, "personagem": pers}
    return out


def _cliente_biblioteca(prov: str, timeout: int = 4):
    """Cliente do acervo `prov` — local (animepexels/moviepexels) ou online (…_online, com a chave)."""
    import acervos
    if acervos.eh_online(prov):
        timeout = max(timeout, 12)  # servidor na internet: mais folga que o do próprio PC
    return acervos.cliente(prov, load_site_config(), timeout=timeout)


def _personagens_da_obra(cli, prov: str, obra: Optional[str]) -> List[Dict[str, Any]]:
    """Personagens (filmes: "Personagem (Ator)") da obra no acervo, com nº de clipes.
    Se o acervo não devolver nenhum com clipe, tenta sem o filtro de clipes e, no
    de filmes, o elenco da ficha da obra (TMDB/IMDb)."""
    lista = [c for c in cli.list_characters(obra=obra or None, limit=400) if c.get("nome")]
    if not lista and obra:
        lista = [c for c in cli.list_characters(obra=obra, with_clips=False, limit=400) if c.get("nome")]
    if not lista and obra and prov in ("moviepexels", "moviepexels_online"):
        try:
            fic = cli.work_credits(obra) or {}
        except Exception:  # noqa: BLE001
            fic = {}
        for chave in ("cast", "elenco", "characters", "personagens"):
            for c in (fic.get(chave) or [])[:80] if isinstance(fic, dict) else []:
                if isinstance(c, dict):
                    pers = c.get("character") or c.get("personagem") or ""
                    ator = c.get("name") or c.get("nome") or c.get("actor") or ""
                    nome = f"{pers} ({ator})" if pers and ator else (pers or ator)
                    if nome:
                        lista.append({"nome": nome, "clipes": 0, "do_elenco": True})
            if lista:
                break
    lista.sort(key=lambda c: -int(c.get("clipes") or 0))
    return lista


def _bibliotecas_prompt(job_id: str) -> dict:
    """O que vai pro prompt sobre cada acervo local: obra/personagem fixados
    pela pessoa + as listas do PRÓPRIO acervo (obras e personagens com clipes),
    pra IA usar os nomes exatos. Com a obra escolhida, os personagens DELA vão
    sempre pro prompt (mesmo com um personagem fixado: a IA pode trocar por
    trecho quando a fala é de outro). O servidor fora do ar não atrapalha o
    prompt — fica um aviso na página do prompt (job["bibliotecas_info"])."""
    job = _JOBS.get(job_id) or {}
    provs = [p for p in job.get("providers") or [] if p in _BIBLIOTECAS_LOCAIS]
    if not provs:
        return {}
    cache = job.get("_bibliotecas_cache")
    if cache is not None:
        return cache
    out, info = {}, {}
    for prov in provs:
        b = dict((job.get("bibliotecas") or {}).get(prov) or {})
        inf = {"obra": b.get("obra") or "", "personagem": b.get("personagem") or "", "personagens": [], "erro": None}
        try:
            cli = _cliente_biblioteca(prov, timeout=15)
            if not b.get("obra"):
                b["obras"] = [w["nome"] for w in cli.list_works()][:120]
            if b.get("obra") or not b.get("personagem"):
                b["personagens"] = _personagens_da_obra(cli, prov, b.get("obra"))[:150 if b.get("obra") else 60]
            inf["personagens"] = [c["nome"] for c in b.get("personagens") or []]
        except Exception as exc:  # noqa: BLE001
            inf["erro"] = str(exc)[:300]
            print(f"[{prov}] não consegui ler obras/personagens do acervo ({exc}) — prompt segue sem as listas", flush=True)
        out[prov] = b
        info[prov] = inf
    job["_bibliotecas_cache"] = out
    job["bibliotecas_info"] = info
    return out


def _aplicar_padroes_biblioteca(job: dict, parsed=None) -> None:
    """Obra/personagem escolhidos pro vídeo inteiro entram nos trechos do
    acervo que a IA deixou sem (o da IA, quando ela pôs, vale mais)."""
    bib = job.get("bibliotecas") or {}
    if not bib:
        return
    segs = job.get("pending_segments") or []
    for k, s in enumerate(segs):
        padrao = bib.get(s.get("provider")) or {}
        for campo in ("obra", "personagem"):
            if padrao.get(campo) and not s.get(campo):
                s[campo] = padrao[campo]
                if parsed is not None and k < len(parsed.segments):
                    setattr(parsed.segments[k], campo, padrao[campo])


@app.route("/job/<job_id>/bibliotecas/recarregar", methods=["POST"])
def recarregar_bibliotecas(job_id: str):
    """Lê de novo os personagens/obras do acervo e remonta o prompt (ex.: o
    servidor do acervo estava desligado quando o prompt foi feito)."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    job.pop("_bibliotecas_cache", None)
    if job.get("segments") and job.get("providers"):
        _remontar_prompt(job_id, job)
    return redirect(url_for("show_prompt", job_id=job_id))


@app.route("/biblioteca-local/<prov>/obras")
def biblioteca_local_obras(prov: str):
    if prov not in _BIBLIOTECAS_LOCAIS:
        return jsonify({"erro": "Acervo desconhecido."}), 404
    try:
        return jsonify({"ok": True, "obras": _cliente_biblioteca(prov).list_works()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui falar com o acervo ({exc}). O app.py do anime-pexels-local está rodando?"}), 502


@app.route("/biblioteca-local/<prov>/personagens")
def biblioteca_local_personagens(prov: str):
    if prov not in _BIBLIOTECAS_LOCAIS:
        return jsonify({"erro": "Acervo desconhecido."}), 404
    try:
        lista = _cliente_biblioteca(prov).list_characters(obra=request.args.get("obra") or None, q=request.args.get("q") or None)
        return jsonify({"ok": True, "personagens": lista})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui falar com o acervo ({exc})."}), 502


PEDIDOS_LISTA_IA = {
    "viloes": "Diga quais desses personagens são VILÕES (ou antagonistas). Para cada um: nome exatamente como está na lista, obra e uma frase do porquê. Do mais marcante pro menos.",
    "herois": "Diga quais desses personagens são HERÓIS / protagonistas. Para cada um: nome exatamente como está na lista, obra e uma frase do porquê.",
    "classificar": "Classifique CADA personagem da lista como: vilão, herói, anti-herói, coadjuvante ou outro. Use o nome exatamente como está na lista.",
    "temas": "Agrupe essas obras por tema/gênero e sugira 10 ideias de vídeo para o YouTube que usem cenas delas (diga quais obras cada ideia usa).",
}


def _lista_para_copiar(cli, prov: str, oque: str, obra: str) -> Dict[str, Any]:
    """Texto (uma por linha) com todas as obras do acervo, ou todos os
    personagens — das obras escolhidas ou do acervo inteiro, agrupados por obra."""
    from animepexels.animepexels_client import varios
    rot = "Filme/série" if prov in ("moviepexels", "moviepexels_online") else "Anime"
    if oque == "obras":
        obras = cli.list_works()
        linhas = [o["nome"] + (f" — {', '.join(o.get('generos') or [])}" if o.get("generos") else "") for o in obras]
        return {"texto": "\n".join(linhas), "quantos": len(linhas), "titulo": f"{rot}s do acervo ({len(linhas)})"}
    grupos: Dict[str, List[str]] = {}
    escolhidas = varios(obra)
    if escolhidas:
        for o in escolhidas:
            grupos[o] = [c["nome"] for c in _personagens_da_obra(cli, prov, o)]
    else:
        todos = [c for c in cli.list_characters(obra=None, limit=20000) if c.get("nome")]
        if not todos:  # servidor que só lista por obra
            for o in cli.list_works():
                grupos[o["nome"]] = [c["nome"] for c in cli.list_characters(obra=o["nome"], limit=2000) if c.get("nome")]
        for c in todos:
            grupos.setdefault(c.get("obra") or "(sem obra)", []).append(c["nome"])
    partes, n = [], 0
    for o, nomes in grupos.items():
        nomes = list(dict.fromkeys(nomes))
        if not nomes:
            continue
        n += len(nomes)
        partes.append(f"## {o} ({len(nomes)})\n" + "\n".join(f"- {x}" for x in nomes))
    return {"texto": "\n\n".join(partes), "quantos": n,
            "titulo": f"Personagens{' de ' + ' | '.join(escolhidas) if escolhidas else ' do acervo inteiro'} ({n})"}


@app.route("/biblioteca-local/<prov>/copiar")
def biblioteca_local_copiar(prov: str):
    """📋 Copiar a lista inteira (obras ou personagens) — pra mandar pra uma IA
    analisar (ex.: quais são vilões). ?o=obras|personagens&obra=A | B&pedido=viloes|…|texto livre"""
    if prov not in _BIBLIOTECAS_LOCAIS:
        return jsonify({"erro": "Acervo desconhecido."}), 404
    oque = "obras" if request.args.get("o") == "obras" else "personagens"
    try:
        d = _lista_para_copiar(_cliente_biblioteca(prov, timeout=30), prov, oque, request.args.get("obra") or "")
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui falar com o acervo ({exc})."}), 502
    if not d["quantos"]:
        return jsonify({"erro": "O acervo não devolveu nenhum nome pra copiar."}), 404
    pedido = (request.args.get("pedido") or "").strip()
    pedido = PEDIDOS_LISTA_IA.get(pedido, pedido)[:1500]
    texto = d["texto"]
    if pedido:
        texto = (f"{pedido}\n\nResponda em português. Use só nomes que estão na lista abaixo (é o que eu tenho de cenas no meu acervo).\n\n"
                 f"=== {d['titulo']} ===\n\n{d['texto']}")
    return jsonify({"ok": True, "texto": texto, "quantos": d["quantos"], "titulo": d["titulo"]})


@app.route("/acervo-online/config", methods=["GET", "POST"])
def acervo_online_config():
    """🌐 Anime Pexels ONLINE: endereço + chave de API (uma chave pras duas fontes
    online). POST {"chave", "url"} salva no site_config.json (fica só no seu PC).
    A chave nunca volta inteira pro navegador — só o começo, pra você reconhecer."""
    import acervos
    if request.method == "POST":
        corpo = request.get_json(silent=True) or request.form
        novos = {}
        if "url" in corpo:
            novos["animepexels_online_url"] = str(corpo.get("url") or "").strip() or acervos.URL_ONLINE_PADRAO
        if "chave" in corpo and (str(corpo.get("chave") or "").strip() or corpo.get("apagar")):
            novos["animepexels_online_api_key"] = "" if corpo.get("apagar") else str(corpo.get("chave")).strip()
        try:
            save_site_config(novos)
        except SiteConfigError as exc:
            return jsonify({"erro": str(exc)}), 400
        for j in _JOBS.values():  # listas de obras/personagens em cache foram pegas com a chave antiga
            if isinstance(j, dict):
                j.pop("_bibliotecas_cache", None)
    on = acervos.config_online(load_site_config())
    ch = on["chave"]
    return jsonify({"ok": True, "url": on["url"], "tem_chave": bool(ch),
                    "chave_inicio": (ch[:8] + "…") if ch else ""})


@app.route("/acervo-online/testar")
def acervo_online_testar():
    """Testa a chave nos dois catálogos online (anime e filmes/séries)."""
    out = {}
    for prov in ("animepexels_online", "moviepexels_online"):
        try:
            obras = _cliente_biblioteca(prov, timeout=15).list_works()
            out[prov] = {"ok": True, "obras": len(obras)}
        except Exception as exc:  # noqa: BLE001
            out[prov] = {"ok": False, "erro": str(exc)[:300]}
    return jsonify({"ok": any(v["ok"] for v in out.values()), "catalogos": out})


@app.route("/biblioteca-local/<prov>/creditos")
def biblioteca_local_creditos(prov: str):
    if prov not in _BIBLIOTECAS_LOCAIS or not request.args.get("obra"):
        return jsonify({"erro": "Informe o acervo e a obra."}), 400
    try:
        return jsonify({"ok": True, "creditos": _cliente_biblioteca(prov).work_credits(request.args["obra"])})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui falar com o acervo ({exc})."}), 502


def _marcar_textos_da_1a_ia(job: dict) -> None:
    """Guarda o texto na tela que a 1ª IA (a das buscas) pôs em cada trecho:
    quando a IA de edição do Estúdio mandar os destaques dela, esses textos
    saem — mas só se a pessoa não mexeu neles."""
    for s in job.get("pending_segments") or []:
        if s.get("on_screen_text"):
            s["texto_da_ia"] = s["on_screen_text"]


def _avisar_buscas(job: dict) -> None:
    """Aviso no Estúdio quando as buscas da IA têm cara de vídeo ruim (fora do
    inglês, repetidas, longas demais) — ver prompt_builder.avisos_buscas."""
    from prompt_builder import avisos_buscas
    avisos = avisos_buscas(job.get("pending_segments") or [])
    if avisos:
        job["aviso_buscas"] = " ".join(avisos)
    else:
        job.pop("aviso_buscas", None)


@app.route("/job/<job_id>/submit-json", methods=["POST"])
def submit_json(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    # opções "só deste vídeo" (checkbox desmarcado não é enviado pelo
    # navegador, por isso o campo-marcador `opcoes_job_enviadas`).
    if request.form.get("opcoes_job_enviadas") == "1":
        job["cfg_overrides"] = {
            "browser_visible": request.form.get("ocultar_navegador") != "on",
            "evitar_repeticao_clipes": request.form.get("nao_repetir_midia") == "on",
        }

    raw_json = request.form.get("ai_response", "")
    try:
        parsed = parse_ai_response(
            raw_json,
            valid_providers=job["providers"] + _provider_do_projeto(job),
            total_duration=job["total_duration"],
        )
    except PromptBuilderError as exc:
        return render_template("prompt.html", job=job, json_error=str(exc), previous_json=raw_json, opcoes=_opcoes_do_job(job), all_providers=DEFAULT_PROVIDERS)

    _aplicar_produto(job, parsed.segments)  # 🛒 "produto" -> arquivo do projeto de venda
    # ✂️ trecho de 1-2 min que a IA mandou (cansou no fim da transcrição): vira pedaços do tamanho do intervalo
    import trechos_longos
    _antes = len(parsed.segments)
    parsed.segments = trechos_longos.dividir_segmentos(parsed.segments, job.get("interval_seconds"),
                                                       trechos_longos.pausas_da_fala(job.get("segments")))
    job["trechos_longos_divididos"] = len(parsed.segments) - _antes
    __import__("chamadas").limpar_buscas(parsed.segments, job.get("chamadas"))  # 🚫 inscreva-se/venda não viram busca de imagem
    _cenas_idx = _aplicar_cenas_do_roteiro(job, parsed.segments)  # 📝 cenas do Roteiro do YouTube → YouTube
    job["youtube_desmarcado"] = _tirar_youtube_desmarcado(job, parsed.segments)  # 🎬 sem a fonte youtube: nada vira YouTube
    job["pending_segments"] = [s.to_dict() for s in parsed.segments]
    for _i in _cenas_idx:
        job["pending_segments"][_i]["roteiro_cena"] = getattr(parsed.segments[_i], "roteiro_cena", None)
    _aplicar_mix_midia(job, parsed)
    _aplicar_padroes_biblioteca(job, parsed)
    _avisar_buscas(job)
    job["soundtrack_suggestion"] = parsed.soundtrack_suggestion
    _aplicar_extras_dp(job, parsed)

    # overlays sugeridos pela própria IA (texto, ou imagem/vídeo via
    # busca) — cada um recebe um id, igual aos criados manualmente no
    # editor, pra poder ser removido/editado do mesmo jeito.
    for ov in parsed.overlays:
        ov["id"] = uuid.uuid4().hex[:8]
        ov["origem"] = "ia_busca"
    job["overlays"] = parsed.overlays
    _marcar_textos_da_1a_ia(job)

    # sugestões de CORTE REAL (vídeo+áudio, não camada) — aparecem no
    # editor esperando a pessoa fazer upload do clipe de verdade;
    # sem upload, a sugestão simplesmente não é aplicada na montagem.
    for cut in parsed.cutaway_suggestions:
        cut["id"] = uuid.uuid4().hex[:8]
        cut["resolved_path"] = None
    job["cutaway_suggestions"] = _cortes_com_chamadas(job, parsed.cutaway_suggestions)
    _aplicar_cortes_do_projeto(job)  # 🛒/🕵️ vídeo do projeto com o áudio original: já recortado e resolvido

    # tudo que a IA pediu do YouTube já começa a ser pesquisado AGORA, em
    # paralelo com as prévias — quando o editor abrir, os resultados já estão lá.
    job["youtube_itens"] = []
    _youtube_itens_sincronizar(job)
    _usar_links_do_roteiro(job_id, job)  # 📝 cena com link já escolhido no roteiro: baixa sozinho

    _save_state(job_id)

    if job["youtube_itens"]:
        _youtube_buscar_pendentes(job_id)

    _fetch_previews(job_id, job, parsed.segments)

    return redirect(url_for("fetching_previews_page", job_id=job_id))


_IA_PULA_BUSCA = {"youtube", "flow", "runpod", "produto", "material", "adiado"}


# 🧭 v84_70: cada trecho vai pra FONTE CERTA (só entre os bancos que você ligou no projeto)
_FOTOS_REAIS = ("bing", "brave", "startpage", "yandex", "google", "wikipedia")  # foto de verdade de uma pessoa/caso/lugar
_BANCOS_STOCK = ("pexels", "pixabay", "magnific", "mixkit", "vistacreate")


def _rotear_trecho(job: dict, sg: VideoSegment, nb: Dict[str, Any]) -> Dict[str, Any]:
    """Decide a fonte do trecho pelo que a IA disse dele ("midia" + "real"):
      - pessoa FALANDO (entrevista, discurso) e real → YouTube (o 🤖 do painel acha o momento);
      - pessoa/caso/lugar/objeto REAL e específico → foto real (buscadores de imagem / Wikipedia),
        porque banco de stock não tem — ele devolvia algo "parecido";
      - pede imagem gerada → Flow (se ligado);
      - "cartao" (ideia abstrata) → busca normal, mas o juiz fica RIGOROSO e, sem nada bom, vira cartão de texto;
      - clima/ambiente → banco de stock, como sempre.
    Muda o trecho (provider/media_type) e devolve o que gravar no pending_segments."""
    ligados = set(job.get("providers") or [])
    midia = nb.get("midia") or ""
    real = bool(nb.get("real"))
    out: Dict[str, Any] = {}
    if midia == "youtube" and real and "youtube" in ligados:
        sg.provider, sg.media_type = "youtube", "video"
        out = {"provider": "youtube", "media_type": "video", "ia_rota": "youtube"}
    elif real and midia in ("foto", "video", ""):
        foto = next((p for p in _FOTOS_REAIS if p in ligados), None)
        if foto and sg.provider not in _FOTOS_REAIS:
            sg.provider, sg.media_type = foto, "image"
            out = {"provider": foto, "media_type": "image", "ia_rota": "foto_real"}
    elif midia == "ia" and ("flow" in ligados or "runpod" in ligados):
        sg.provider = "flow" if "flow" in ligados else "runpod"
        out = {"provider": sg.provider, "ia_rota": sg.provider}
    elif midia == "cartao":
        out = {"ia_rigoroso": True, "ia_rota": "abstrato"}
    elif midia in ("foto", "video") and not real and sg.provider in _FOTOS_REAIS:
        stock = next((p for p in _BANCOS_STOCK if p in ligados), None)  # clima num buscador de imagem: stock é melhor
        if stock:
            sg.provider = stock
            out = {"provider": stock, "ia_rota": "stock"}
    return out


_CARTAO_PADRAO = ("clean_arquivo_escuro", "minimal", "capitulo")


def _estilo_do_cartao(job: dict) -> str:
    """Tipografia do cartão: um destaque de TELA CHEIA da direção do projeto (ex.: a cartela do Dallas);
    sem nenhum, um cartão escuro discreto."""
    import dp_destaques
    try:
        import dp_direcao
        did = (job.get("editor_defaults") or {}).get("direcao") or job.get("direcao_do_projeto")
        p = dp_direcao.direcao(did) if did else None
        for forma in ("centro_frase", "centro_titulo"):
            for e in ((p or {}).get("destaques") or {}).get("estilos") or []:
                est = dp_destaques.estilo(e) or {}
                if (est.get("cena") or {}).get("assumeTela") and est.get("forma") == forma:
                    return e
    except Exception:  # noqa: BLE001
        pass
    return next((e for e in _CARTAO_PADRAO if dp_destaques.estilo(e)), "capitulo")


def _frase_do_cartao(fala: str, frase_ia: str, estilo: str) -> str:
    import dp_destaques
    faixa = (dp_destaques.estilo(estilo) or {}).get("palavras") or [1, 8]
    maximo = max(2, min(int(faixa[1]), 8))
    texto = (frase_ia or "").strip() or " ".join(re.sub(r"\s+", " ", fala or "").split()[:maximo])
    return " ".join(texto.split()[:maximo]).strip(" ,;")


def _cartao_no_trecho(job_id: str, job: dict, i: int, sg: VideoSegment, fala: str, motivo: str) -> Dict[str, Any]:
    """🃏 O trecho vira um CARTÃO: fundo escuro gerado aqui (sem banco nenhum) + a frase do trecho num destaque de
    tela cheia. Devolve a prévia do trecho. A pessoa troca no editor como qualquer trecho."""
    import cenas_dp
    W, H = {"9:16": (1080, 1920), "1:1": (1080, 1080)}.get(_orientacao_do_job(job), (1920, 1080))
    pal = (job.get("paleta") or {}) if isinstance(job.get("paleta"), dict) else {}
    fundo = cenas_dp.gerar_fundo("escuro", W, H, os.path.join(_job_dir(job_id), "cartoes"), tom=pal.get("primaria"))
    estilo = _estilo_do_cartao(job)
    frase = _frase_do_cartao(fala, getattr(sg, "_frase_tela", "") or "", estilo)
    override = {"source": "local_file", "value": fundo, "kind": "image", "cartao": True, "zoom_direction": "in"}
    sg.override_source, sg.media_type = dict(override), "image"
    pend = job.get("pending_segments") or []
    if i < len(pend):
        pend[i].update(override_source=dict(override), media_type="image",
                       cartao={"estilo": estilo, "texto": frase, "motivo": motivo})
    if frase:
        ds = [d for d in job.get("destaques") or [] if not (d.get("origem") == "cartao" and d.get("trecho") == i)]
        ds.append({"id": uuid.uuid4().hex[:8], "estilo": estilo, "start": round(float(sg.start), 2),
                   "end": round(float(sg.end), 2), "texto": frase, "campos": {}, "avulso": True,
                   "origem": "cartao", "trecho": i})
        job["destaques"] = sorted(ds, key=lambda d: float(d.get("start") or 0))
    return {"index": i, "ok": True, "thumbnail_url": f"/job/{job_id}/thumbnail/{i}", "thumbnail_path": fundo,
            "result_url": None, "label": f"🃏 cartão: “{frase}” — {motivo}", "error": None, "video_preview_url": None,
            "provider": "cartao", "original_provider": sg.provider, "cartao": True}


def _contar_rotas(pend: List[Dict[str, Any]]) -> Dict[str, int]:
    c: Dict[str, int] = {}
    for p in pend:
        if p.get("ia_rota"):
            c[p["ia_rota"]] = c.get(p["ia_rota"], 0) + 1
    return c


def _ia_preparar_buscas(job_id: str, job: dict, segments: List[VideoSegment]) -> Optional[List[Dict[str, Any]]]:
    """🤖 Fases 0 e 1 (com a IA ligada): a FICHA do vídeo (lida do roteiro uma vez) e as buscas
    melhores de cada trecho (query = a 1ª, alternativas = as outras + a busca original). Devolve o
    contexto de cada trecho pro juiz (ou None sem IA). Qualquer falha: segue com as buscas de sempre."""
    import ia_servico
    if not (ia_servico.ativo("juiz") or ia_servico.ativo("buscas")):
        return None
    info = job.setdefault("ia", {})
    blocos = [b for b in job.get("segments") or [] if (b.get("text") or "").strip()]
    roteiro = " ".join(str(b["text"]).strip() for b in blocos)
    try:
        falas, _p = _falas_por_trecho(job, segments)
    except Exception:  # noqa: BLE001
        falas = [""] * len(segments)
    for k, sg in enumerate(segments):
        if not falas[k]:
            falas[k] = " ".join(str(b["text"]).strip() for b in blocos if float(b["start"]) < sg.end and float(b["end"]) > sg.start)
    try:
        import ia_midia
        if info.get("ficha") is None and ia_servico.ativo("buscas"):
            job["preview_ia"] = "🤖 lendo o roteiro (ficha do vídeo)…"
            info["ficha"] = ia_midia.ficha_visual(roteiro, job.get("titulo") or job.get("nome") or "", job.get("language") or "", job=job_id)
        if not info.get("buscas_feitas") and ia_servico.ativo("buscas"):
            import chamadas as _ch
            _jan = _ch.janelas(job.get("chamadas"))
            elegiveis = [k for k, sg in enumerate(segments)
                         if not sg.override_source and sg.provider not in _IA_PULA_BUSCA
                         and not any(min(sg.end, b) - max(sg.start, a) >= (sg.end - sg.start) * 0.5 for a, b in _jan)
                         and not (sg.provider in _BIBLIOTECAS_LOCAIS and (getattr(sg, "obra", None) or getattr(sg, "personagem", None)))]
            if elegiveis:
                job["preview_ia"] = "🤖 escrevendo buscas melhores…"
                # 🧭 cada trecho vai com a fala de ANTES e a de DEPOIS (v84_92): a busca entende a cena, não palavras soltas
                novas = ia_midia.buscas_melhores([{"n": k + 1, "fala": falas[k], "visual": getattr(segments[k], "visual", None),
                                                   "antes": falas[k - 1] if k else "",
                                                   "depois": falas[k + 1] if k + 1 < len(falas) else "",
                                                   "query": segments[k].query} for k in elegiveis], info.get("ficha"), roteiro, job=job_id)
                pend = job.get("pending_segments") or []
                mudou = 0
                foi_pro_youtube = False
                for k in elegiveis:
                    nb = novas.get(k + 1)
                    if not nb:
                        continue
                    sg = segments[k]
                    original = sg.query
                    sg.query = nb["buscas"][0]
                    sg.alternativas = [b for b in nb["buscas"][1:] + [original] if b and b != sg.query][:5]
                    if nb.get("visual"):
                        sg.visual = nb["visual"]
                    rota = _rotear_trecho(job, sg, nb)
                    if k < len(pend):
                        pend[k].update(query=sg.query, alternativas=sg.alternativas, ia_busca_original=original,
                                       ia_midia=nb.get("midia") or None, ia_real=bool(nb.get("real")),
                                       **({"frase_tela": nb["frase_tela"]} if nb.get("frase_tela") else {}),
                                       **({"visual": sg.visual} if nb.get("visual") else {}), **rota)
                    if rota.get("provider") == "youtube":
                        foi_pro_youtube = True
                    mudou += 1
                _ch.limpar_buscas(segments, job.get("chamadas"))  # a IA também não busca inscreva-se/venda
                for k, sg in enumerate(segments):
                    if k < len(pend) and pend[k].get("query") != sg.query:
                        pend[k].update(query=sg.query, alternativas=list(sg.alternativas or []))
                info["buscas_feitas"] = True
                info["buscas_trocadas"] = mudou
                info["rotas"] = _contar_rotas(pend)
                if foi_pro_youtube:  # pessoa falando (entrevista/discurso): o painel do YouTube já começa a pesquisar
                    _youtube_itens_sincronizar(job)
                    _youtube_buscar_pendentes(job_id)
    except Exception as exc:  # noqa: BLE001 — a IA nunca trava a prévia
        info["erro"] = str(exc)[:300]
    job.pop("preview_ia", None)
    ficha = info.get("ficha")
    pend = job.get("pending_segments") or []
    for k, sg in enumerate(segments):  # o que a IA marcou: rigor do juiz e a frase do cartão
        if k < len(pend):
            sg._rigoroso = bool(pend[k].get("ia_rigoroso"))
            sg._frase_tela = pend[k].get("frase_tela") or ""
    return [{"ficha": ficha, "fala": falas[k], "anterior": falas[k - 1] if k else "",
             "seguinte": falas[k + 1] if k + 1 < len(falas) else "", "visual": getattr(segments[k], "visual", None) or "",
             "job": job_id} for k in range(len(segments))]


def _ia_escolher_imagem(res: dict, ctx: Optional[dict], cache: dict, termo: str, termo_unico: bool) -> dict:
    """🤖 buscadores de imagem (Bing, Brave…: onde mais vem lixo): o juiz olha as imagens já baixadas
    (a 1ª e as extras) e fica com a melhor. Com o termo usado só por esse trecho, a escolha vai pro
    cache (a montagem reaproveita a mesma)."""
    if not ctx or not res.get("ok") or not res.get("extras"):
        return res
    from video_assembler import julgar_candidatos_ia
    variantes = [dict(res, extras=None)] + [dict(res, **{c: v.get(c) for c in ("path", "engine", "title", "original_url", "thumbnail_url", "source_page", "assinatura")})
                                         for v in res.get("extras") or [] if v.get("path") and os.path.exists(v["path"])]
    cands = [{"path": v["path"], "label": f"{v.get('engine')}: {v.get('title') or ''}", "_v": k} for k, v in enumerate(variantes)]
    j = julgar_candidatos_ia(cands, ctx, termo, miniatura="path")
    if not j or not j["lista"]:
        return res
    melhor = j["lista"][0]
    if melhor.get("marca_dagua"):  # ⛔ v84_106: todas as baixadas têm marca d'água — nenhuma entra
        return dict(res, ok=False, erro="o 🤖 juiz viu marca d'água em todas as imagens achadas", marca_dagua=True)
    escolhida = dict(variantes[melhor["_v"]], extras=res.get("extras"))
    escolhida.update(ia_nota=melhor.get("ia_nota"), ia_motivo=melhor.get("ia_motivo"),
                     ia_aviso=melhor.get("ia_nota", 0) < int((__import__("ia_servico").config() or {}).get("nota_minima") or 7))
    if termo_unico and melhor["_v"] and termo in cache:
        antigo = dict(cache[termo])
        outras = [dict(antigo, extras=None)] + [v for k, v in enumerate(antigo.get("extras") or []) if k != melhor["_v"] - 1]
        cache[termo] = dict(antigo, **{c: escolhida.get(c) for c in ("path", "engine", "title", "original_url", "thumbnail_url", "source_page", "assinatura")},
                                   extras=[{c: o.get(c) for c in ("path", "engine", "title", "original_url", "thumbnail_url", "source_page", "assinatura")} for o in outras])
    return escolhida


def _fetch_previews(job_id: str, job: dict, segments: List[VideoSegment], retomar: bool = False) -> None:
    """Dispara em segundo plano: busca (SEM baixar nada) uma prévia de
    cada segmento, usando o thumbnail que o próprio provedor já entrega
    na busca (hospedado no CDN dele) — o navegador carrega essa imagem
    direto de lá. Falha em UM segmento não trava os outros (o editor
    mostra "sem prévia" e deixa escolher manualmente pra esse).

    Antes disso, cada prévia baixava o VÍDEO INTEIRO só pra tirar um
    frame com ffmpeg — em narrações com muitos trechos, isso sozinho já
    explicava boa parte dos minutos de espera relatados. Trocando pra
    só buscar (sem baixar), essa etapa fica muito mais rápida — o
    download de verdade só acontece na montagem final (que já roda em
    paralelo também, veja `assembly_fetch_concurrency`).

    Busca vários segmentos EM PARALELO (`preview_fetch_concurrency` nas
    configurações, padrão 3). Cada worker usa sua PRÓPRIA `ClientFactory`
    (sessão de navegador própria) — sessões Selenium não são seguras pra
    usar de várias threads ao mesmo tempo, então paralelizar exige uma
    sessão por worker, não uma compartilhada.
    """
    job["status"] = "buscando_previas"
    job["pausar_previas"] = False
    # ⏸ v84_108: retomar = mantém as prévias que já ficaram prontas e busca só as que faltam
    anteriores = list(job.get("segment_previews") or []) if retomar else []
    anteriores = (anteriores + [None] * len(segments))[:len(segments)]
    faltam = {k for k, pv in enumerate(anteriores) if pv is None}
    job["preview_progress"] = {"current": len(segments) - len(faltam), "total": len(segments)}
    job["segment_previews"] = anteriores
    _save_state(job_id)

    ia_ctxs: List[Optional[dict]] = [None] * len(segments)

    def _fetch_one(i: int, segment: VideoSegment, cfg: dict, tracker=None) -> dict:
        if job.get("pausar_previas"):  # ⏸ pausado: nem começa (o que já estava buscando termina)
            return {"index": i, "_pausado": True}
        factory = ClientFactory(cfg)
        perf = _PERF_LOGS.get(job_id)
        pl = perf.timed if perf else (lambda *a, **k: nullcontext())
        try:
            with pl(f"previa:segmento_{i}:busca", provider=segment.provider, query=segment.query):
                result = fetch_segment_preview_lightweight(
                    segment, site_cfg=cfg, client_factory=factory, used_tracker=tracker,
                    **({"ia_ctx": ia_ctxs[i]} if ia_ctxs[i] is not None else {}),
                )
        finally:
            factory.close_all()

        if result.get("cartao"):
            try:
                return _cartao_no_trecho(job_id, job, i, segment, (ia_ctxs[i] or {}).get("fala") or "",
                                         result.get("error") or "nenhuma imagem boa")
            except Exception:  # noqa: BLE001 — sem cartão: o trecho fica sem prévia (como antes)
                pass
        out = {
            "index": i, "ok": result["ok"], "thumbnail_url": result["thumbnail_url"],
            "result_url": result["result_url"], "label": result["label"], "error": result["error"],
            "video_preview_url": result.get("video_preview_url"),
            "provider": result.get("provider"),
            "original_provider": segment.provider,
            "query": segment.query, "media_type": segment.media_type,
        }
        for k in ("ia_nota", "ia_motivo", "ia_aviso", "ia_busca"):
            if result.get(k) is not None:
                out[k] = result[k]
        return out

    def _run():
        job_dir = _job_dir(job_id)
        os.makedirs(job_dir, exist_ok=True)
        cfg = _job_site_cfg(job)
        # "não repetir": UM tracker pra todas as prévias do vídeo — se o melhor
        # resultado já apareceu num trecho, o próximo mostra o 2º melhor, etc.
        tracker = UsedClipsTracker() if cfg.get("evitar_repeticao_clipes", True) else None
        perf = _PERF_LOGS.get(job_id)
        # 🤖 com a IA ligada: ficha do vídeo + buscas melhores ANTES de buscar; contexto pro juiz
        ctxs = _ia_preparar_buscas(job_id, job, segments)
        if ctxs:
            ia_ctxs[:] = ctxs
            _save_state(job_id)

        completed = len(segments) - len(faltam)
        cancelled = False
        pausado = False
        progress_lock = threading.Lock()

        def _publicar(i: int, preview: dict) -> None:
            nonlocal completed
            with progress_lock:
                updated = list(job["segment_previews"])
                updated[i] = preview
                job["segment_previews"] = updated
                completed += 1
                job["preview_progress"] = {"current": completed, "total": len(segments)}

        # 0) 🛒 mídias do produto (projeto de venda): o arquivo já está aqui — prévia na hora
        produto_idx = [i for i, s in enumerate(segments) if s.provider in ("produto", "material") and s.override_source and i in faltam]
        for i in produto_idx:
            _publicar(i, {
                "index": i, "ok": True, "thumbnail_url": f"/job/{job_id}/segment-thumb/{i}", "result_url": None,
                "label": f"{'🛒 mídia do produto' if segments[i].provider == 'produto' else '🕵️ imagem do tema'} {segments[i].query}",
                "error": None, "video_preview_url": None,
                "provider": segments[i].provider, "original_provider": segments[i].provider,
            })

        # 1) trechos do YouTube: sem prévia automática — o vídeo e a faixa de
        #    tempo são escolhidos no painel do editor (a busca já está rodando).
        youtube_idx = [i for i, s in enumerate(segments) if s.provider == "youtube" and not s.override_source and i in faltam]
        for i in youtube_idx:
            _publicar(i, {
                "index": i, "ok": False, "thumbnail_url": None, "result_url": None, "label": None,
                "error": "YouTube: escolha o vídeo e o trecho no painel \"Vídeos do YouTube\" do editor.",
                "video_preview_url": None, "provider": "youtube", "original_provider": "youtube",
            })

        # 1b) 🏭 cenas ⏳ PENDENTES (Produção no pod): sem prévia agora — "Completar cenas pendentes" no editor
        adiado_idx = [i for i, s in enumerate(segments) if s.provider == "adiado" and not s.override_source and i in faltam]
        for i in adiado_idx:
            _publicar(i, {
                "index": i, "ok": False, "thumbnail_url": None, "result_url": None, "label": None, "adiado": True,
                "error": "⏳ cena pendente — use “Completar cenas pendentes” (escolha as fontes e a IA escreve a busca).",
                "video_preview_url": None, "provider": "adiado", "original_provider": "adiado",
            })

        # 2) trechos com buscador de imagem por navegador: TODOS de uma vez,
        #    1 navegador por buscador (não 1 por trecho), já baixando a 1ª
        #    imagem — a montagem reaproveita o arquivo sem buscar de novo.
        imagem_items = [
            (i, s) for i, s in enumerate(segments)
            if not s.override_source and getattr(s, "media_type", "video") == "image"
            and s.provider in BROWSER_IMAGE_SEARCH_PROVIDERS and i in faltam
        ]
        imagem_thread = None
        if imagem_items:
            pasta_imagens = os.path.join(job_dir, "buscadores_imagens")

            _termos = [" ".join((s.query or "").split()) for _i, s in imagem_items]

            def _on_imagem(i: int, res: dict) -> None:
                if ia_ctxs[i] is not None:
                    try:
                        _t = " ".join((segments[i].query or "").split())
                        res = _ia_escolher_imagem(res, ia_ctxs[i], job.setdefault("imagens_buscadores", {}), _t, _termos.count(_t) == 1)
                    except Exception:  # noqa: BLE001
                        pass
                    import ia_servico as _ias
                    _corte = int((_ias.config() or {}).get("nota_minima") or 7) if getattr(segments[i], "_rigoroso", False) else 5
                    if ((res.get("ok") and res.get("ia_nota") is not None and res["ia_nota"] < _corte) or res.get("marca_dagua")) \
                            and _ias.ativo("cartao"):  # nada bom (ou ⛔ só com marca d'água): gera um cartão no lugar
                        try:
                            _publicar(i, _cartao_no_trecho(job_id, job, i, segments[i], ia_ctxs[i].get("fala") or "",
                                                           "⛔ só achei imagens com marca d'água" if res.get("marca_dagua")
                                                           else f"nenhuma imagem boa (melhor nota {res['ia_nota']})"))
                            return
                        except Exception:  # noqa: BLE001
                            pass
                _publicar(i, {
                    "index": i, "ok": bool(res.get("ok")),
                    "thumbnail_url": f"/job/{job_id}/thumbnail/{i}" if res.get("ok") else None,
                    "thumbnail_path": res.get("path") if res.get("ok") else None,
                    "result_url": res.get("source_page") or None,
                    "label": (("⚠ " if res.get("ia_aviso") else "") + f"{res.get('engine')}: {res.get('title') or res.get('query')}" + (" (⚠ repetida: nenhum buscador achou outra)" if res.get("repetida") else "") if res.get("ok") else None),
                    **({k: res[k] for k in ("ia_nota", "ia_motivo", "ia_aviso") if res.get(k) is not None}),
                    "error": None if res.get("ok") else res.get("erro"),
                    "video_preview_url": None, "provider": res.get("engine"),
                    "original_provider": segments[i].provider,
                })

            def _buscar_imagens() -> None:
                try:
                    with (perf.timed("previa:buscadores_imagem_lote", trechos=len(imagem_items)) if perf else nullcontext()):
                        prefetch_browser_images(
                            imagem_items, pasta_imagens, cfg,
                            cache=job.setdefault("imagens_buscadores", {}), on_result=_on_imagem,
                        )
                except Exception as exc:  # noqa: BLE001
                    for i, _s in imagem_items:
                        if not (job["segment_previews"][i] or {}).get("ok"):
                            _on_imagem(i, {"ok": False, "erro": f"Erro inesperado: {exc}"})

            imagem_thread = threading.Thread(target=_buscar_imagens, daemon=True)
            imagem_thread.start()

        # 3) o resto: como sempre, em paralelo
        especiais = set(youtube_idx) | set(produto_idx) | set(adiado_idx) | {i for i, _s in imagem_items}
        restantes = [(i, s) for i, s in enumerate(segments) if i not in especiais and i in faltam]
        concurrency = max(1, min(cfg.get("preview_fetch_concurrency", 3), max(1, len(restantes))))
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            future_to_index = {
                executor.submit(_fetch_one, i, segment, cfg, tracker): i
                for i, segment in restantes
            }
            for future in concurrent.futures.as_completed(future_to_index):
                if job.get("cancel_requested"):
                    cancelled = True
                    for f in future_to_index:
                        f.cancel()
                    break
                i = future_to_index[future]
                try:
                    preview = future.result()
                except concurrent.futures.CancelledError:
                    continue
                except Exception as exc:  # noqa: BLE001
                    preview = {"index": i, "ok": False, "thumbnail_url": None,
                               "result_url": None, "label": None, "error": f"Erro inesperado: {exc}"}
                if preview.get("_pausado"):
                    pausado = True
                    continue
                # atualiza incrementalmente — permite a pagina de progresso
                # mostrar cada thumbnail assim que fica pronta, em vez de
                # so uma porcentagem sem conteudo visual ate tudo terminar
                # de uma vez. Reatribui a lista inteira (em vez de so o
                # indice) pra manter a leitura de fora sempre vendo um
                # snapshot consistente.
                _publicar(i, preview)

        if imagem_thread is not None:
            imagem_thread.join()

        if (pausado or job.get("pausar_previas")) and not cancelled and any(pv is None for pv in job["segment_previews"]):
            if perf:
                perf.save()
            job["status"] = "previas_pausadas"  # ⏸ retoma depois em /job/<id>/previas/retomar
            _save_state(job_id)
            return

        if cancelled:
            if perf:
                perf.save()
            job["status"] = "cancelado"
            _save_state(job_id)
            return

        waveform_path = os.path.join(job_dir, "waveform.png")
        try:
            generate_waveform_image(job["audio_path"], waveform_path)
            job["waveform_path"] = waveform_path
        except Exception:  # noqa: BLE001
            job["waveform_path"] = None

        if perf:
            perf.save()

        job["status"] = "pronto_para_editar"
        _save_state(job_id)
        _avisar_fim(f"🖼️ Prévias de “{_nome_job(job_id)}”", None, f"/job/{job_id}/edit-segments", "previas",
                    "Pronto pra editar a timeline.")
        _prebaixar_iniciar(job_id, job)  # ⬇ já vai baixando os clipes enquanto a pessoa edita

    threading.Thread(target=_run, daemon=True).start()


def previas_faltando(job: dict) -> int:
    """Quantos trechos ainda estão sem prévia (nem buscada) — pra ▶ continuar a busca de onde parou."""
    segs = job.get("pending_segments") or []
    pv = list(job.get("segment_previews") or [])
    return sum(1 for k in range(len(segs)) if k >= len(pv) or pv[k] is None)


app.jinja_env.globals["previas_faltando"] = previas_faltando


@app.route("/job/<job_id>/previas/pausar", methods=["POST"])
def previas_pausar(job_id: str):
    """⏸ Pausa a busca de prévias: o que já está buscando termina, o resto espera (e fica salvo pra retomar)."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    if job.get("status") != "buscando_previas":
        return jsonify({"erro": "Não está buscando prévias agora.", "status": job.get("status")}), 400
    job["pausar_previas"] = True
    _save_state(job_id)
    return jsonify({"ok": True, "status": job.get("status")})


@app.route("/job/<job_id>/previas/retomar", methods=["POST"])
def previas_retomar(job_id: str):
    """▶ Retoma: busca só as prévias que faltam (as prontas ficam)."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    if job.get("status") == "buscando_previas" and job.get("pausar_previas"):
        job["pausar_previas"] = False  # ainda nem parou: só desfaz o pedido de pausa
        return jsonify({"ok": True, "status": job["status"]})
    # também um projeto interrompido ANTES (servidor fechou no meio da busca e ele abriu no editor com trechos sem prévia)
    if job.get("status") not in ("previas_pausadas", "pronto_para_editar") or not previas_faltando(job):
        return jsonify({"erro": "Não tem prévia faltando pra buscar.", "status": job.get("status")}), 400
    segs = [_segmento_obj(d) for d in job.get("pending_segments") or []]
    _fetch_previews(job_id, job, segs, retomar=True)
    return jsonify({"ok": True, "status": job.get("status")})


@app.route("/job/<job_id>/fetching-previews", methods=["GET"])
def fetching_previews_page(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    youtube_itens_lista = _youtube_itens_sincronizar(job) if job.get("pending_segments") else []
    if any(it.get("status") == "pendente" for it in youtube_itens_lista):
        _youtube_buscar_pendentes(job_id)
    return render_template("fetching_previews.html", job=job, youtube_itens=youtube_itens_lista)


@app.route("/job/<job_id>/fetching-previews-status", methods=["GET"])
def fetching_previews_status_api(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job não encontrado"}), 404
    previews = job.get("segment_previews", [])
    # só o resumo (sem caminho de arquivo local) — o JS usa isso pra ir
    # desenhando cada thumbnail assim que ela fica pronta, em vez de só
    # uma porcentagem sem nenhum conteúdo visual até tudo terminar.
    # A lista é pré-alocada com None nas posições ainda não prontas
    # (busca em paralelo, a ordem de conclusão não é a ordem do índice)
    # — filtra isso antes de montar o resumo.
    previews_summary = [
        {"index": p["index"], "ok": p["ok"], "thumbnail_url": p.get("thumbnail_url"),
         "provider": p.get("provider") or p.get("original_provider"), "error": p.get("error"),
         "label": p.get("label"), "ia_nota": p.get("ia_nota"), "ia_motivo": p.get("ia_motivo")}
        for p in previews if p is not None
    ]
    return jsonify({
        "status": job.get("status"),
        "progress": job.get("preview_progress"),
        "previews": previews_summary,
        "ia": job.get("preview_ia"),
        "pausando": bool(job.get("pausar_previas")) and job.get("status") == "buscando_previas",
    })


@app.route("/job/<job_id>/thumbnail/<int:index>", methods=["GET"])
def segment_thumbnail(job_id: str, index: int):
    job = _JOBS.get(job_id)
    previews = (job or {}).get("segment_previews", [])
    if not job or index >= len(previews) or not previews[index] or not previews[index].get("thumbnail_path"):
        return "Sem thumbnail.", 404
    return send_file(previews[index]["thumbnail_path"])


@app.route("/job/<job_id>/waveform-image", methods=["GET"])
def waveform_image(job_id: str):
    job = _JOBS.get(job_id)
    if not job or not job.get("waveform_path"):
        return "Sem forma de onda.", 404
    return send_file(job["waveform_path"])


@app.route("/job/<job_id>/narration-audio", methods=["GET"])
def narration_audio(job_id: str):
    job = _JOBS.get(job_id)
    if not job or not job.get("audio_path") or not os.path.exists(job["audio_path"]):
        return "Áudio não encontrado.", 404
    return send_file(job["audio_path"])


def _probe_video_resolution(video_path: str):
    """(largura, altura) de um vídeo já pronto, via ffprobe — usado pra
    dimensionar a fonte da legenda igual à resolução final do vídeo.
    """
    import subprocess as _subprocess

    result = _subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "json", video_path],
        capture_output=True, text=True, timeout=30, check=True,
    )
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _palavras_da_narracao(job: dict) -> List[Dict[str, Any]]:
    """Palavras com tempo (as do Whisper; sem elas, divide o texto de cada
    frase transcrita igualmente no tempo dela)."""
    ws = [w for w in (job.get("word_timestamps") or []) if str(w.get("word", "")).strip()]
    if ws:
        return ws
    import dp_legendas
    return dp_legendas.palavras_dos_blocos([sg for sg in job.get("segments") or [] if sg.get("text")])


def _falas_por_trecho(job: dict, segmentos: List[Any]):
    """(texto falado, palavras) de cada trecho — usado pelas cenas que mostram a fala."""
    todas = _palavras_da_narracao(job)
    falas, palavras = [], []
    for sg in segmentos:
        ini = sg.start if hasattr(sg, "start") else float(sg["start"])
        fim = sg.end if hasattr(sg, "end") else float(sg["end"])
        ws = [w for w in todas if ini - 0.05 <= (float(w["start"]) + float(w.get("end", w["start"]))) / 2 < fim]
        palavras.append(ws)
        falas.append(" ".join(str(w["word"]).strip() for w in ws).strip())
    return falas, palavras


def _janelas_que_cobrem_legenda(segmentos: List[Any]) -> List[tuple]:
    """Intervalos (início, fim) das cenas que mostram a fala — a legenda
    queimada some ali (regra do DarkPlanner: nunca duplicar a legenda)."""
    import cenas_dp
    tids = [getattr(sg, "template", None) for sg in segmentos]
    janelas = []
    for (a, b, tid) in cenas_dp.planejar_grupos(tids):
        campos = getattr(segmentos[a], "template_campos", None) or {}
        if tid and cenas_dp.cobre_legenda(tid) and campos.get("_fala", True) is not False:
            janelas.append((segmentos[a].start, segmentos[b].end))
    return janelas


def _efeitos_dp_do_form(form, i: int, base: dict) -> dict:
    """efeito / entrada / saída do catálogo DarkPlanner pro trecho i (sem o
    campo no form — editor clássico — mantém o que já estava)."""
    import dp_visual
    validos = {
        "efeito": {e["id"] for e in dp_visual.efeitos()},
        "entrada": {e["id"] for e in dp_visual.entradas()},
        "saida": {e["id"] for e in dp_visual.entradas()},
    }
    out = {}
    for chave, ok in validos.items():
        nome = f"seg_{i}_{chave}"
        valor = (form.get(nome) if nome in form else base.get(chave)) or ""
        valor = valor.strip()
        out[chave] = valor if valor in ok and valor != "none" else None
    return out


def _template_do_form(form, i: int, base: dict):
    """Template de cena do trecho i vindo do editor (Estúdio manda
    seg_i_template + seg_i_template_campos em JSON). Sem o campo no form
    (editor clássico), mantém o que já estava salvo."""
    import cenas_dp
    if f"seg_{i}_template" not in form:
        tid, campos = base.get("template"), base.get("template_campos")
    else:
        tid = (form.get(f"seg_{i}_template") or "").strip() or None
        try:
            campos = json.loads(form.get(f"seg_{i}_template_campos") or "{}")
        except ValueError:
            campos = {}
    if not tid or not cenas_dp.template(tid):
        return None, None
    if not isinstance(campos, dict):
        campos = {}
    validos = {c["key"]: int(c["maxChars"] or 120) for c in cenas_dp.campos_de_texto(tid)}
    limpos = {}
    for k, v in campos.items():
        if k == "_fala":
            if v is False or str(v).lower() in ("false", "0", "off"):
                limpos["_fala"] = False
        elif k == "_legenda":
            if v in ("manter", "ocultar"):
                limpos["_legenda"] = v
        elif k == "_fundo":
            if v and str(v) in cenas_dp.fundos_do_template(tid) + sorted(__import__("dp_fundos").IDS_CENA):
                limpos["_fundo"] = str(v)
        elif k == "_fundo_cor":
            if re.fullmatch(r"#[0-9a-fA-F]{6}", str(v or "")):
                limpos["_fundo_cor"] = str(v).upper()
        elif k in validos and v is not None and str(v).strip():
            limpos[k] = str(v).strip()[: validos[k]]
    return tid, (limpos or None)


def _aplicar_extras_dp(job: dict, parsed) -> None:
    """O que a IA pediu do DarkPlanner na raiz do JSON: Direção (preenche só o
    que a IA deixou vazio), filtro de cor e destaques de texto (com o tempo
    recalculado pela fala)."""
    import dp_destaques
    import dp_direcao
    defaults = job.setdefault("editor_defaults", {})
    # 🎬 a IA não escolheu direção, mas o modelo de vídeo ligado sugere uma (ex.: 🕳 Rabbit holes → estilo Mistere)
    _dir = getattr(parsed, "direcao", None) or (job.get("direcao_do_projeto") if dp_direcao.direcao(job.get("direcao_do_projeto") or "") else None)
    if _dir:
        segs = job["pending_segments"]
        plano = dp_direcao.planejar(
            [{"start": s["start"], "end": s["end"], "foto": s.get("media_type") == "image", "template": s.get("template"),
              "transition": s.get("transition"), "efeito": s.get("efeito"), "entrada": s.get("entrada"), "saida": s.get("saida")} for s in segs],
            _dir, semente=1, so_vazios=True)
        for s, p in zip(segs, plano["trechos"]):
            for k in ("transition", "efeito", "entrada", "saida", "template"):
                if p.get(k) and p[k] != "none" and not s.get(k):
                    s[k] = p[k]
        defaults["direcao"] = _dir
        if plano.get("filtro_cor") and not getattr(parsed, "filtro_cor", None):
            defaults["filtro_cor"] = plano["filtro_cor"]
        if plano.get("cores") and not getattr(parsed, "paleta", None):
            import dp_cores
            defaults["paleta"] = dp_cores.normalizar(plano["cores"])
        if plano.get("legenda") and not job.get("legendas"):
            import dp_legendas
            job["legendas"] = dp_legendas.normalizar(plano["legenda"])
    if getattr(parsed, "filtro_cor", None):
        defaults["filtro_cor"] = parsed.filtro_cor
    if getattr(parsed, "paleta", None):
        defaults["paleta"] = parsed.paleta
    if getattr(parsed, "graficos", None):
        import dp_graficos
        job["graficos"] = [g for g in (dp_graficos.normalizar(x, job.get("total_duration")) for x in parsed.graficos) if g]
    if getattr(parsed, "destaques", None):
        for d in parsed.destaques:
            d["id"] = uuid.uuid4().hex[:8]
            d["origem"] = "ia_busca"  # da 1ª IA (a das buscas): sai quando a IA de edição mandar os dela
        job["destaques"] = dp_destaques.ancorar(parsed.destaques, _palavras_da_narracao(job), job.get("total_duration"))
    else:
        job.setdefault("destaques", [])


def _destaques_do_form(job: dict, form) -> None:
    """Estúdio manda a lista inteira de destaques em JSON (destaques_json)."""
    import dp_destaques
    if "destaques_json" not in form:
        return
    try:
        lista = json.loads(form.get("destaques_json") or "[]")
    except ValueError:
        return
    limpos = []
    for d in lista if isinstance(lista, list) else []:
        if not isinstance(d, dict) or not dp_destaques.estilo(str(d.get("estilo") or "")):
            continue
        try:
            ini, fim = float(d["start"]), float(d["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if fim - ini < 0.2:
            continue
        campos = d.get("campos") if isinstance(d.get("campos"), dict) else {}
        item = {"id": str(d.get("id") or uuid.uuid4().hex[:8])[:16], "estilo": d["estilo"], "start": round(ini, 3), "end": round(fim, 3),
                "texto": str(d.get("texto") or "")[:300], "campos": {str(k): str(v)[:200] for k, v in campos.items() if v not in (None, "")}}
        if d.get("avulso"):
            item["avulso"] = True
        if d.get("sem_fundo"):
            item["sem_fundo"] = True
        if d.get("zona") in ("centro", "alto", "baixo", "terco_inf", "esq", "dir", "canto_tl", "canto_tr", "canto_bl", "canto_br", "terco_sup"):
            item["zona"] = d["zona"]
        if d.get("som") == "nenhum" or _dp_sons_valido(str(d.get("som") or "")):
            item["som"] = d["som"]
        if d.get("origem") in ("auto", "ia", "ia_busca", "cartao"):
            item["origem"] = d["origem"]
        if d.get("origem") == "cartao" and isinstance(d.get("trecho"), int):
            item["trecho"] = d["trecho"]
        if d.get("legenda") in ("manter", "ocultar"):
            item["legenda"] = d["legenda"]
        _fundo_do_destaque(item, d)
        item.update(__import__("prompt_edicao").estilo_de_texto(d))
        limpos.append(item)
    job["destaques"] = sorted(limpos, key=lambda x: x["start"])
    if "hl_fundo_json" in form:
        try:
            pad = _fundo_do_destaque({}, json.loads(form.get("hl_fundo_json") or "{}"))
        except (ValueError, AttributeError):
            pad = {}
        job.setdefault("editor_defaults", {})["hl_fundo"] = pad or None
    import dp_cores
    if form.get("paleta_json"):
        try:
            job.setdefault("editor_defaults", {})["paleta"] = dp_cores.normalizar(json.loads(form.get("paleta_json")))
        except ValueError:
            pass
    else:
        pal = form.get("paleta_primaria", "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", pal or ""):
            job.setdefault("editor_defaults", {})["paleta"] = dp_cores.normalizar(dict(dp_destaques.paleta_padrao(), primaria=pal))


@app.route("/job/<job_id>/destaques/sugerir", methods=["POST"])
def destaques_sugerir(job_id: str):
    """Motor local de destaques (anos, %, dinheiro, datas, contagens, frases de impacto…)."""
    import dp_destaques
    import dp_direcao
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    blocos = [{"start": float(s["start"]), "end": float(s["end"]), "text": s.get("text", "")} for s in job.get("segments") or [] if s.get("text")]
    kit, dens = None, corpo.get("densidade") or "equilibrado"
    kit_job = corpo.get("kit") if isinstance(corpo.get("kit"), dict) else ((job.get("editor_defaults") or {}).get("kit") or {})
    did = corpo.get("direcao") or (job.get("editor_defaults") or {}).get("direcao") or ""
    d = dp_direcao.direcao(did, kit_job)
    kit_pred = None
    if d and d.get("destaques"):
        kit_pred = d["destaques"].get("estilos") or None
        dens = corpo.get("densidade") or d["destaques"].get("densidade") or dens
    # estilos marcados NA predefinição mandam; senão, o que a pessoa marcou na galeria (kit)
    kit = kit_pred if (kit_pred and did != "kit") else (kit_job.get("destaques") or kit_pred)
    lista = dp_destaques.sugerir(blocos, kit=kit, densidade=dens, semente=corpo.get("semente", 1),
                                 palavras=_palavras_da_narracao(job), duracao=job.get("total_duration"))
    for x in lista:
        x["id"] = uuid.uuid4().hex[:8]
    return jsonify({"ok": True, "destaques": lista})


def _fundo_do_destaque(item: dict, d: dict) -> dict:
    """Fundo escolhido pra um destaque (ou o padrão do projeto): id, cor, intensidade e cor do texto."""
    import dp_fundos
    if not isinstance(d, dict):
        return item
    if d.get("fundo") in dp_fundos.IDS_DESTAQUE:
        item["fundo"] = d["fundo"]
    for k in ("fundo_cor", "cor"):
        v = str(d.get(k) or "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            item[k] = v.upper()
    try:
        if d.get("fundo_int") not in (None, ""):
            item["fundo_int"] = round(max(0.15, min(1.0, float(d["fundo_int"]))), 2)
    except (TypeError, ValueError):
        pass
    return item


def _destaques_para_montar(job: dict):
    """Destaques com o fundo padrão do projeto aplicado onde a pessoa não escolheu um."""
    import dp_destaques
    lista = dp_destaques.sem_conflito(job.get("destaques") or [], job.get("editoriais"), job.get("pending_segments") or job.get("segments"))
    pad = (job.get("editor_defaults") or {}).get("hl_fundo") or {}
    if not pad.get("fundo"):
        return lista or None
    out = []
    for d in lista:
        if not d.get("fundo") and not d.get("sem_fundo"):
            d = dict(d, fundo=pad["fundo"], **({"fundo_cor": pad["fundo_cor"]} if pad.get("fundo_cor") and not d.get("fundo_cor") else {}),
                     **({"fundo_int": pad["fundo_int"]} if pad.get("fundo_int") is not None and d.get("fundo_int") is None else {}))
        out.append(d)
    return out or None


def _dp_sons_valido(sid: str) -> bool:
    import dp_sons
    return bool(sid) and dp_sons.som(sid) is not None


def _sfx_do_form(job: dict, form) -> None:
    """Sons que a pessoa pôs na faixa "Sons" do Estúdio (sfx_json)."""
    if "sfx_json" not in form:
        return
    try:
        lista = json.loads(form.get("sfx_json") or "[]")
    except ValueError:
        return
    limpos = []
    for x in lista if isinstance(lista, list) else []:
        if not isinstance(x, dict) or not _dp_sons_valido(str(x.get("som") or "")):
            continue
        try:
            ini = max(0.0, float(x.get("start", 0)))
            vol = max(0.0, min(3.0, float(x.get("volume", 1.0))))
        except (TypeError, ValueError):
            continue
        item = {"id": str(x.get("id") or uuid.uuid4().hex[:8])[:16], "som": x["som"], "start": round(ini, 3), "volume": round(vol, 2)}
        if x.get("origem") == "ia":  # reaplicar a resposta da IA troca estes em vez de duplicar
            item["origem"] = "ia"
        limpos.append(item)
    job["sfx"] = sorted(limpos, key=lambda x: x["start"])


@app.route("/textos")
def textos_avulsos_page():
    """Página de textos animados avulsos: qualquer texto em qualquer um dos 207
    estilos, exportado como vídeo (fundo preto, verde ou transparente)."""
    import dp_destaques
    return render_template("textos.html", estilos=_estilos_destaque_editor(), fundos=dp_destaques.FUNDOS_AVULSO)


@app.route("/textos/gerar", methods=["POST"])
def textos_avulsos_gerar():
    import dp_destaques
    corpo = request.get_json(silent=True) or {}
    texto = str(corpo.get("texto") or "").strip()[:300]
    if not texto:
        return jsonify({"erro": "Escreva o texto."}), 400
    if not dp_destaques.estilo(str(corpo.get("estilo") or "")):
        return jsonify({"erro": "Escolha um estilo."}), 400
    orient = corpo.get("orientacao") if corpo.get("orientacao") in ("16:9", "9:16", "1:1") else "16:9"
    qual = corpo.get("qualidade") if corpo.get("qualidade") in ("720p", "1080p") else "1080p"
    if orient == "1:1":
        W = H = 1080 if qual == "1080p" else 720
    else:
        W, H = resolution_for_orientation(orient, qual)
    try:
        dur = float(corpo.get("duracao") or 3)
    except (TypeError, ValueError):
        dur = 3.0
    pal = str(corpo.get("cor") or "")
    paleta = dict(dp_destaques.paleta_padrao(), primaria=pal) if re.fullmatch(r"#[0-9a-fA-F]{6}", pal) else None
    pasta = os.path.join(OUTPUTS_DIR, "textos")
    os.makedirs(pasta, exist_ok=True)
    nome = f"texto_{corpo['estilo']}_{uuid.uuid4().hex[:6]}"
    try:
        saida = dp_destaques.renderizar_avulso(corpo["estilo"], texto, dur, W, H, str(corpo.get("fundo") or "preto"),
                                               os.path.join(pasta, nome), os.path.join(pasta, "_trab_" + nome),
                                               campos={str(k): str(v) for k, v in (corpo.get("campos") or {}).items() if v},
                                               zona=corpo.get("zona") or None, paleta=paleta, com_tratamento=bool(corpo.get("tratamento", True)))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": str(exc)[-400:]}), 500
    finally:
        shutil.rmtree(os.path.join(pasta, "_trab_" + nome), ignore_errors=True)
    return jsonify({"ok": True, "url": url_for("textos_avulsos_baixar", arquivo=os.path.basename(saida)), "arquivo": os.path.basename(saida)})


@app.route("/textos/baixar/<arquivo>")
def textos_avulsos_baixar(arquivo: str):
    return send_from_directory(os.path.join(OUTPUTS_DIR, "textos"), secure_filename(arquivo), as_attachment=request.args.get("ver") != "1")


@app.route("/sons/<path:arquivo>")
def servir_som(arquivo: str):
    import dp_sons
    return send_from_directory(dp_sons.SONS_DIR, arquivo)


def _grupos_para_legenda(segmentos: List[Any]) -> List[tuple]:
    import cenas_dp
    out = []
    for (a, b, tid) in cenas_dp.planejar_grupos([getattr(sg, "template", None) for sg in segmentos]):
        if not tid:
            continue
        campos = getattr(segmentos[a], "template_campos", None) or {}
        mostra = cenas_dp.cobre_legenda(tid) and campos.get("_fala", True) is not False
        out.append((segmentos[a].start, segmentos[b].end, mostra, campos.get("_legenda")))
    return out


def _gerar_legendas_dp(job_id: str, job: dict, segments: List[Any], output_path: str, cutaways_to_apply: list) -> None:
    """Legendas do Estúdio (aba 📝 Legendas): .srt do zip ou palavras do Whisper,
    estilos de bloco/karaokê, escondidas sob cenas/destaques conforme a regra."""
    import dp_legendas
    cfg = dp_legendas.normalizar(job.get("legendas"))
    palavras = _palavras_da_narracao(job)
    if not palavras:
        return
    palavras = dp_legendas.filtrar(palavras, dp_legendas.janelas_ocultas(cfg, _grupos_para_legenda(segments), job.get("destaques") or []))
    if cutaways_to_apply:
        cut = [{"insertion_point": c["insertion_point"], "remove_ate": c.get("remove_ate"), "duration": _probe_media_duration(c["resolved_path"])} for c in cutaways_to_apply]
        palavras = shift_timestamps_for_cutaways(palavras, cut)
    width, height = _probe_video_resolution(output_path)
    ass_path = os.path.join(_job_dir(job_id), "legendas_dp.ass")
    dp_legendas.gerar_ass(palavras, cfg, width, height, ass_path, (job.get("editor_defaults") or {}).get("paleta"))
    captioned_path = os.path.join(OUTPUTS_DIR, f"{job_id}_legendado.mp4")
    dp_legendas.queimar(output_path, ass_path, captioned_path)
    job["captioned_output_path"] = captioned_path


def _usa_templates_cena() -> bool:
    try:
        return bool(load_site_config().get("templates_cena_ia", True))
    except Exception:  # noqa: BLE001
        return True


# v84_114: as etapas da montagem, na ordem, com o nome que aparece na tela
NOMES_ETAPAS_MONTAGEM = {
    "iniciando": "Preparando", "youtube_automatico": "Escolhendo os vídeos do YouTube", "buscando_imagens": "Buscando imagens nos buscadores",
    "buscando": "Buscando os clipes", "processando": "Baixando e preparando os clipes", "normalizando": "Ajustando os clipes",
    "compondo_cenas": "Compondo as cenas (templates)", "concatenando": "Juntando os clipes e as transições", "filtro_cor": "Filtro de cor",
    "censura": "Censura (blur/tarja)", "sons": "Efeitos sonoros", "sincronizando_audio": "Juntando a narração e a trilha",
    "aplicando_overlays": "Overlays", "editoriais": "Quadros editoriais", "destaques": "Destaques de texto", "graficos": "Gráficos",
    "cortes": "Chamadas, abertura e encerramento", "gerando_legendas": "Legendas", "qualidade_final": "Passe final de qualidade",
}


def _etapas_planejadas(job: dict, segments: List[VideoSegment]) -> List[str]:
    """As etapas que ESTA montagem deve ter (as que não têm nada a fazer ficam de fora)."""
    e = ["iniciando"]
    if any(s.provider == "youtube" and not s.override_source for s in segments):
        e.append("youtube_automatico")
    e.append("processando")
    if any(getattr(s, "template", None) for s in segments):
        e.append("compondo_cenas")
    e.append("concatenando")
    try:
        if __import__("dp_visual").cadeia_filtro(_job_site_cfg(job).get("filtro_cor")):
            e.append("filtro_cor")
    except Exception:  # noqa: BLE001
        pass
    try:
        if __import__("dp_censura").de_video(__import__("dp_censura").normalizar(job.get("censura") or [])):
            e.append("censura")
    except Exception:  # noqa: BLE001
        pass
    e += ["sons", "sincronizando_audio"]
    for chave, etapa in (("overlays", "aplicando_overlays"), ("editoriais", "editoriais")):
        if job.get(chave):
            e.append(etapa)
    if _destaques_para_montar(job):
        e.append("destaques")
    if job.get("graficos"):
        e.append("graficos")
    if any(c.get("resolved_path") for c in job.get("cutaway_suggestions") or []) or __import__("canal").cortes_para_montagem(job):
        e.append("cortes")
    if (job.get("legendas") or {}).get("ativa") or (job.get("add_word_captions") and job.get("word_timestamps")):
        e.append("gerando_legendas")
    if __import__("qualidade_export").valida(job.get("qualidade_exportacao")) != "normal":
        e.append("qualidade_final")
    return e


def _progresso_etapa(job: dict, stage: str, current: int, total: int, detalhe: Optional[str] = None,
                     agora: Optional[float] = None) -> dict:
    """Atualiza job["progress"]: a etapa atual (com a fração e o detalhe), a lista de etapas (feita / rodando /
    pulada / pendente, com o tempo de cada), quando começou e as estimativas (desta etapa e do total)."""
    agora = agora or time.time()
    prog = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    etapas = list(prog.get("etapas") or [])
    k = next((i for i, x in enumerate(etapas) if x["id"] == stage), None)
    if k is None:  # etapa que não estava no plano (ex.: buscar imagens): entra logo depois da que está rodando
        pos = max([i + 1 for i, x in enumerate(etapas) if x["estado"] != "pendente"] or [0])
        etapas.insert(pos, {"id": stage, "nome": NOMES_ETAPAS_MONTAGEM.get(stage, stage), "estado": "pendente"})
        k = pos
    for i, x in enumerate(etapas):
        if i < k and x["estado"] == "pendente":
            x["estado"] = "pulada"
        elif i != k and x["estado"] == "rodando":
            x.update(estado="feita", fim=agora)
    atual = etapas[k]
    if atual["estado"] != "rodando":
        atual.update(estado="rodando", inicio=agora, fim=None)
    frac = (current / total) if total else 0.0
    frac = max(0.0, min(1.0, frac))
    decorrido = agora - float(atual.get("inicio") or agora)
    eta = None
    if 0.01 <= frac < 1 and decorrido >= 3:
        eta = round(decorrido * (1 - frac) / frac)
    hist = job.get("montagem_tempos") or {}  # quanto cada etapa levou na montagem anterior deste vídeo
    pendentes = [x["id"] for x in etapas if x["estado"] == "pendente"]
    eta_total = None
    if eta is not None or frac >= 1 or not pendentes:
        conhecidas = [hist[i] for i in pendentes if i in hist]
        if len(conhecidas) == len(pendentes):
            eta_total = round((eta or 0) + sum(conhecidas))
    prog.update(stage=stage, nome=atual["nome"], current=current, total=total, detalhe=detalhe or "",
                estimated_seconds_remaining=eta, eta_total=eta_total, etapas=etapas,
                inicio=prog.get("inicio") or agora, agora=agora, etapa_inicio=atual.get("inicio"))
    job["progress"] = prog
    return prog


def _start_assembly(job_id: str, job: dict, segments: List[VideoSegment]) -> None:
    """Salva os segmentos finais no job e dispara a montagem em segundo
    plano — chamado depois que os segmentos (já revisados/editados no
    editor) estão prontos.
    """
    job["video_segments"] = [s.to_dict() for s in segments]
    job["status"] = "montando"
    job["progress"] = {"stage": "iniciando", "current": 0, "total": len(segments), "inicio": time.time(),
                       "etapas": [{"id": e, "nome": NOMES_ETAPAS_MONTAGEM.get(e, e), "estado": "pendente"}
                                  for e in _etapas_planejadas(job, segments)]}
    _progresso_etapa(job, "iniciando", 0, 1)
    job.pop("assembly_error", None)  # limpa erro de uma tentativa anterior, se houver
    job.pop("assembly_error_segment_index", None)
    job.pop("assembly_error_segments", None)
    job["cancel_requested"] = False
    _save_state(job_id)

    def _run():
        assembly_start_time = time.time()

        def on_progress(stage, current, total, detalhe=None):
            # v84_114: a lista de etapas (feitas / rodando / que faltam), a fração da etapa atual — nas etapas
            # finais vem do próprio ffmpeg (até onde ele já chegou no vídeo) — e as estimativas de tempo
            _progresso_etapa(job, stage, current, total, detalhe)

        def acompanhar(stage):
            import progresso_ffmpeg
            try:
                dur = _probe_media_duration(output_path)
            except Exception:  # noqa: BLE001
                dur = 0
            return progresso_ffmpeg.acompanhar(lambda f, det: on_progress(stage, int(round(f * 1000)), 1000, det), dur)

        perf = _PERF_LOGS.get(job_id)
        final_status: Optional[str] = None

        try:
            output_path = os.path.join(OUTPUTS_DIR, f"{job_id}.mp4")
            try:  # avisos de uma montagem anterior não valem pra esta
                os.remove(os.path.join(_job_dir(job_id), "avisos_montagem.json"))
            except OSError:
                pass

            # Sempre limpa erros de overlay de uma tentativa anterior —
            # sem isso, se a pessoa REMOVER todos os overlays depois de
            # uma tentativa que falhou parcialmente, o aviso antigo
            # ficaria "grudado" na tela mesmo sem nenhum overlay mais.
            job["overlay_errors"] = []

            # trechos do YouTube que ficaram sem escolha: 1º resultado, do começo
            if any(s.provider == "youtube" and not s.override_source for s in segments):
                on_progress("youtube_automatico", 0, len(segments))
                _youtube_escolher_automatico(job_id, job, segments, log=print)
                job["video_segments"] = [s.to_dict() for s in segments]

            try:  # 🤖 v84_145: selo "Simulação: conteúdo gerado por IA" nos trechos de IA de AGORA (aba 🤖 Conteúdo IA)
                import conteudo_ia as _cia
                _cia.sincronizar(job, BASE_DIR)
            except Exception:  # noqa: BLE001
                pass
            resolved_overlays = None
            if job.get("overlays"):
                resolved_overlays = []
                overlay_factory = ClientFactory(_job_site_cfg(job))
                for ov in job["overlays"]:
                    if ov.get("media_type") == "text":
                        # overlay de texto não tem fonte pra resolver
                        # (upload/link/busca) — vai direto pra lista final.
                        resolved_overlays.append({
                            "media_type": "text", "text": ov.get("text", ""),
                            "start": ov["start"], "end": ov["end"],
                            "style": ov.get("style"),
                        })
                        continue
                    try:
                        with (perf.timed("montagem:resolver_overlay", overlay_id=ov.get("id")) if perf else nullcontext()):
                            resolved_path, kind = resolve_overlay_source(
                                ov["source"], _job_dir(job_id), overlay_factory.get_client,
                            )
                        resolved_overlays.append({
                            "resolved_path": resolved_path, "media_type": kind,
                            "start": ov["start"], "end": ov["end"],
                            "position": ov.get("position", "top-right"),
                            "size_percent": ov.get("size_percent", 20),
                        })
                    except VideoAssemblyError as exc:
                        # um overlay que falha (link quebrado, busca sem
                        # resultado, etc.) não deveria travar o vídeo
                        # inteiro por causa disso — pula só ele, avisa,
                        # e segue com os que deram certo.
                        job["overlay_errors"].append(f"Overlay {ov.get('id', '?')}: {exc}")

            import qualidade_export
            qualidade_export.definir(job.get("qualidade_exportacao"))
            __import__("export_paralelo").definir(job.get("export_paralelo"))  # ⚡ v84_115
            _falas = _falas_por_trecho(job, segments) if any(getattr(sg, "template", None) for sg in segments) else (None, None)
            assemble_video(
                segments=segments,
                audio_path=job["audio_path"],
                output_path=output_path,
                work_dir=_job_dir(job_id),
                on_progress=on_progress,
                music_path=job.get("music_path"),
                music_volume=job.get("music_volume", 0.18),
                perf_log=perf,
                cancel_check=lambda: job.get("cancel_requested", False),
                overlays=resolved_overlays,
                site_cfg=_job_site_cfg(job),
                image_search_cache=job.setdefault("imagens_buscadores", {}),
                falas_por_trecho=_falas[0],
                palavras_por_trecho=_falas[1],
                destaques=_destaques_para_montar(job),
                palavras_narracao=_palavras_da_narracao(job),
                sfx=job.get("sfx") or None,
                graficos=job.get("graficos") or None,
                editoriais=__import__("dp_editorial").com_idioma_do_video(job.get("editoriais"), __import__("idiomas").normalizar(job.get("language"))) or None,
                imagens_editorial=_imagens_da_biblioteca(job),
                censura=job.get("censura") or None,
            )
            job["output_path"] = output_path
            try:  # v84_119: etapas puladas por cortar a imagem do vídeo (aparecem na tela do resultado)
                _av = os.path.join(_job_dir(job_id), "avisos_montagem.json")
                job["avisos_montagem"] = json.load(open(_av, encoding="utf-8")) if os.path.exists(_av) else []
                if os.path.exists(_av):
                    os.remove(_av)
            except Exception:  # noqa: BLE001
                job["avisos_montagem"] = []

            # Cortes reais (vídeo+áudio, não camada) — aplicados DEPOIS
            # dos overlays, no vídeo já pronto. Só os que já têm upload
            # (resolved_path) — sem isso, a sugestão fica só anotada,
            # nunca aplicada. LIMITAÇÃO CONHECIDA: como um corte estica
            # o vídeo final, qualquer overlay com tempo ABSOLUTO
            # marcado pra depois do ponto de inserção vai parecer
            # "adiantado" em relação ao que era esperado (o overlay não
            # sabe que um corte empurrou o resto do vídeo pra frente) —
            # útil sobretudo pra vídeos que usam OU overlay OU corte,
            # não muito os dois se cruzando na mesma região de tempo.
            cutaways_to_apply = [
                {
                    "resolved_path": c["resolved_path"],
                    "insertion_point": c["insertion_point"],
                    "audio_mode": c.get("audio_mode", "pause"),
                    # chamada (inscreva-se/venda/link): o clipe ENTRA NO LUGAR desse trecho da narração
                    "remove_ate": c.get("remove_ate"),
                }
                for c in job.get("cutaway_suggestions", []) if c.get("resolved_path") and os.path.isfile(c["resolved_path"])
            ]
            # 🎬 abertura e 🏁 encerramento do canal (canal.py): cortes reais no começo e no fim
            cutaways_to_apply += [dict(v, insertion_point=min(float(v["insertion_point"]), _probe_media_duration(output_path)))
                                  for v in __import__("canal").cortes_para_montagem(job)]
            if cutaways_to_apply:
                target_width, target_height = resolution_for_orientation(
                    _orientacao_do_job(job), job.get("export_quality", "1080p"),
                )
                cutaway_output = os.path.join(_job_dir(job_id), "_with_cutaways.mp4")
                on_progress("cortes", 0, 1000)
                with (perf.timed("montagem:cortes", quantidade=len(cutaways_to_apply)) if perf else nullcontext()), acompanhar("cortes"):
                    insert_cutaways(output_path, cutaways_to_apply, cutaway_output, _job_dir(job_id), target_width, target_height)
                _ev = __import__("export_paralelo")
                _dv_a, _dv_d = _ev.duracao_do_video(output_path), _ev.duracao_do_video(cutaway_output)
                if _dv_a and _dv_d and _dv_d < _dv_a - 1.0:  # v84_119: com cortes o vídeo só pode CRESCER
                    job.setdefault("avisos_montagem", []).append(
                        f"As chamadas/abertura/encerramento cortaram a imagem do vídeo em {int(_dv_d // 60)}:{_dv_d % 60:04.1f} — foram puladas.")
                else:
                    shutil.move(cutaway_output, output_path)

            _leg_cfg = (job.get("legendas") or {})
            if _leg_cfg.get("ativa"):
                on_progress("gerando_legendas", len(segments), len(segments))
                try:
                    with (perf.timed("montagem:legendas_dp") if perf else nullcontext()), acompanhar("gerando_legendas"):
                        _gerar_legendas_dp(job_id, job, segments, output_path, cutaways_to_apply)
                except Exception:  # noqa: BLE001
                    job["captions_error"] = traceback.format_exc()
            elif job.get("add_word_captions") and job.get("word_timestamps"):
                on_progress("gerando_legendas", len(segments), len(segments))
                try:
                    with (perf.timed("montagem:gerar_legendas") if perf else nullcontext()), acompanhar("gerando_legendas"):
                        width, height = _probe_video_resolution(output_path)
                        # Bug real: um corte real desloca tudo que vem
                        # depois dele pra frente no vídeo final, mas a
                        # legenda é gerada a partir da transcrição do
                        # áudio ORIGINAL (antes de qualquer corte) — sem
                        # ajustar isso, a legenda de uma palavra dita
                        # DEPOIS de um corte aparecia adiantada, fora de
                        # sincronia com a fala de verdade.
                        word_timestamps = job["word_timestamps"]
                        if cutaways_to_apply:
                            cutaways_with_duration = [
                                {"insertion_point": c["insertion_point"], "remove_ate": c.get("remove_ate"), "duration": _probe_media_duration(c["resolved_path"])}
                                for c in cutaways_to_apply
                            ]
                            word_timestamps = shift_timestamps_for_cutaways(word_timestamps, cutaways_with_duration)
                        _cobertas = _janelas_que_cobrem_legenda(segments) + [
                            (float(d["start"]), float(d["end"])) for d in (job.get("destaques") or []) if not d.get("avulso")
                        ]
                        if _cobertas and not cutaways_to_apply:
                            word_timestamps = [
                                w for w in word_timestamps
                                if not any(a <= float(w.get("start", 0)) < b for (a, b) in _cobertas)
                            ] or word_timestamps
                        ass_path = os.path.join(_job_dir(job_id), "captions.ass")
                        generate_word_captions_ass(word_timestamps, ass_path, width, height, style=job.get("caption_style"))
                        captioned_path = os.path.join(OUTPUTS_DIR, f"{job_id}_legendado.mp4")
                        burn_captions(output_path, ass_path, captioned_path)
                        _ev = __import__("export_paralelo")
                        _dv_a, _dv_d = _ev.duracao_do_video(output_path), _ev.duracao_do_video(captioned_path)
                        if _dv_a and _dv_d and _dv_d < _dv_a - 1.0:  # v84_119: legenda que corta a imagem → refaz num passe só
                            _ev.definir("1")
                            try:
                                burn_captions(output_path, ass_path, captioned_path)
                            finally:
                                _ev.definir(job.get("export_paralelo"))
                        job["captioned_output_path"] = captioned_path
                except Exception:  # noqa: BLE001
                    # a versao sem legenda ja esta pronta e continua valendo —
                    # nao falha o job inteiro so porque a legenda deu problema.
                    job["captions_error"] = traceback.format_exc()

            _capitulos_do_video_final(job_id, job, output_path, cutaways_to_apply)
            if qualidade_export.valida(job.get("qualidade_exportacao")) != "normal":
                on_progress("qualidade_final", len(segments), len(segments))
                with (perf.timed("montagem:qualidade_final", qualidade=job.get("qualidade_exportacao")) if perf else nullcontext()), acompanhar("qualidade_final"):
                    for _arq in {output_path, job.get("captioned_output_path")} - {None}:
                        qualidade_export.passe_final(_arq, job.get("qualidade_exportacao"))
            final_status = "concluido"
            # ⏱ quanto cada etapa levou: a próxima montagem deste vídeo usa pra estimar o tempo total
            _agora = time.time()
            job["montagem_tempos"] = {x["id"]: round((x.get("fim") or _agora) - x["inicio"], 1)
                                      for x in (job.get("progress") or {}).get("etapas") or [] if x.get("inicio")}
            for x in (job.get("progress") or {}).get("etapas") or []:
                if x["estado"] == "rodando":
                    x.update(estado="feita", fim=_agora)
                elif x["estado"] == "pendente":
                    x["estado"] = "pulada"
        except VideoAssemblyError as exc:
            if job.get("cancel_requested"):
                # cancelamento pedido pela pessoa, não é uma falha de
                # verdade — status próprio, sem a mensagem de erro
                # assustadora nem a opção de "trocar fonte e tentar de
                # novo" (a pessoa já decidiu que não queria mais isso).
                final_status = "cancelado"
            else:
                # volta pro editor em vez de travar num "erro" sem saída — a
                # pessoa pode escolher outra fonte pro trecho que falhou e
                # montar de novo, em vez de precisar recomeçar o processo
                # inteiro (colar o JSON de novo, esperar a transcrição etc).
                final_status = "pronto_para_editar"
                job["assembly_error"] = str(exc)
            job["assembly_error_segment_index"] = getattr(exc, "segment_index", None)
            job["assembly_error_segments"] = getattr(exc, "segment_indices", None)
        except Exception:  # noqa: BLE001
            final_status = "pronto_para_editar"
            job["assembly_error"] = f"Erro inesperado:\n{traceback.format_exc()}"
            job["assembly_error_segment_index"] = None
        finally:
            try:
                import qualidade_export
                qualidade_export.limpar()
                __import__("export_paralelo").limpar()
            except Exception:  # noqa: BLE001
                pass
            if perf:
                perf.save()
            # o status final SÓ muda depois do log de tempo estar salvo —
            # sem essa ordem, existe uma janela de corrida real onde
            # alguém observando o status (um teste, ou a própria pessoa
            # no navegador clicando em "baixar log de tempo" assim que
            # vê "concluído") pode ler o arquivo ANTES dele refletir a
            # montagem inteira, pegando um log incompleto/desatualizado.
            if final_status:
                job["status"] = final_status
            _save_state(job_id)
            if final_status == "concluido":
                _avisar_fim(f"🎬 Vídeo “{_nome_job(job_id)}”", None, f"/job/{job_id}/status-page", "montagem",
                            "A montagem terminou — assista ou baixe.")
            elif final_status == "pronto_para_editar" and job.get("assembly_error"):
                _avisar_fim(f"🎬 Montagem de “{_nome_job(job_id)}”", str(job.get("assembly_error"))[-400:],
                            f"/job/{job_id}/edit-segments", "montagem")
            if final_status == "concluido":
                # diagnóstico (vídeo × telinha) DEPOIS de liberar o vídeo: não atrasa a entrega
                _diagnostico_em_segundo_plano(job_id, job)

    threading.Thread(target=_run, daemon=True).start()


def _capitulos_do_video_final(job_id: str, job: dict, output_path: str, cortes_aplicados: List[Dict[str, Any]]) -> None:
    """📑 Vídeo de um 🕵️ modelo de vídeo ou 📝 Roteiro do YouTube: capítulos da descrição no tempo do VÍDEO FINAL (a narração
    deste vídeo + o empurrão das chamadas/cortes). Nunca derruba a montagem."""
    job.pop("capitulos_video", None)
    job.pop("descricao_youtube", None)
    if not (job.get("dossie_id") or job.get("roteiro_id")):
        return
    try:
        import capitulos_video
        cortes = [{"insertion_point": c["insertion_point"], "remove_ate": c.get("remove_ate"),
                   "duration": _probe_media_duration(c["resolved_path"])} for c in cortes_aplicados or []]
        r = capitulos_video.para_job(job, BASE_DIR, _palavras_da_narracao(job), cortes, _probe_media_duration(output_path))
        if r:
            job["capitulos_video"], job["descricao_youtube"] = r
    except Exception:  # noqa: BLE001
        job["capitulos_video_erro"] = traceback.format_exc()[-1500:]


def _diagnostico_em_segundo_plano(job_id: str, job: dict) -> None:
    def _diag():
        job["diagnostico_gerando"] = True
        try:
            import diagnostico_export
            diagnostico_export.gerar(job_id, job, _job_dir(job_id), job.get("output_path"))
            job.pop("diagnostico_erro", None)
        except Exception:  # noqa: BLE001
            job["diagnostico_erro"] = traceback.format_exc()[-2000:]
        finally:
            job["diagnostico_gerando"] = False
    threading.Thread(target=_diag, daemon=True).start()


# --------------------------------------------------------------------- #
# Página 2.5: editor de segmentos — revisar/editar cada trecho antes de
# montar (trocar termo/fonte, subir arquivo próprio, colar link de post,
# ou usar uma imagem com efeito Ken Burns)
# --------------------------------------------------------------------- #

@app.route("/job/<job_id>/edit-segments", methods=["GET"])
def edit_segments_page(job_id: str):
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return "Job não encontrado, ou ainda não tem segmentos pra editar.", 404
    # Estúdio (timeline arrastável) é o padrão; ?modo=classico abre o editor em
    # lista de sempre. A escolha fica num cookie pra os redirecionamentos (enviar
    # arquivo, overlay, corte...) voltarem pro mesmo editor.
    modo = request.args.get("modo") or request.cookies.get("editor_modo") or "estudio"
    if modo not in ("estudio", "classico"):
        modo = "estudio"
    if modo == "estudio":
        resp = app.make_response(_render_estudio(job_id, job))
    else:
        resp = app.make_response(_render_editor_classico(job_id, job))
    if request.args.get("modo") in ("estudio", "classico"):
        resp.set_cookie("editor_modo", modo, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


def _seg_estudio(job_id: str, job: dict, i: int) -> Dict[str, Any]:
    """Um trecho como o Estúdio usa (com a prévia em `_preview`)."""
    import timelines as _tlm
    previews = job.get("segment_previews") or []
    seg = job["pending_segments"][i]
    p = previews[i] if i < len(previews) and previews[i] else {}
    ov = seg.get("override_source") or {}
    v = f"?tl={_tlm.estado(job)['ativa']}"  # a mesma URL muda de conteúdo ao trocar de timeline
    midia_local = f"/job/{job_id}/segment-media/{i}{v}" if ov.get("source") == "local_file" else None
    thumb = p.get("thumbnail_url") if p.get("ok") else None
    if thumb and thumb.startswith(f"/job/{job_id}/") and "?" not in thumb:
        thumb += v
    # 💾 o que já foi guardado no PC sai do disco (reabrir o projeto não baixa tudo de novo)
    thumb_remoto = thumb
    thumb = _previa_local(job_id, thumb, "imagem") or thumb
    return dict(seg, _preview={
        "thumb_remoto": thumb_remoto if thumb != thumb_remoto else None,
        "video_remoto": p.get("video_preview_url") if _previa_local(job_id, p.get("video_preview_url"), "video") else None,
        "thumbnail_url": (f"/job/{job_id}/segment-thumb/{i}{v}" if midia_local else None) or thumb,
        "video_preview_url": _previa_local(job_id, p.get("video_preview_url"), "video") or p.get("video_preview_url"),
        "label": p.get("label"), "erro": None if p.get("ok") else p.get("error"),
        "provider": p.get("provider"), "midia_local": midia_local,
        "nao_fixa": bool(p.get("nao_fixa")) and not ov,
        # pro "desfazer" das buscas e pro diagnóstico pós-export saberem qual clipe era
        "result_url": p.get("result_url"), "query": p.get("query"), "media_type": p.get("media_type"),
        "duracao": p.get("duracao"),
    })


def _timelines_estudio(job_id: str, job: dict) -> Dict[str, Any]:
    import timelines as _tlm
    st = _tlm.estado(job)
    return {"ativa": st["ativa"], "tem_2": _tlm.tem_2(job), "gerando": st.get("gerando"),
            "nomes": _tlm.NOMES, "escolhas": _tlm.escolhas(job) if st["ativa"] == "3" else None}


def _dados_estudio(job_id: str, job: dict) -> Dict[str, Any]:
    """Tudo que o Estúdio precisa, num JSON só (o JS monta a interface)."""
    segs = [_seg_estudio(job_id, job, i) for i in range(len(job["pending_segments"]))]
    overlays = []
    for ov in job.get("overlays") or []:
        o = dict(ov)
        src = ov.get("source") or {}
        o["_url"] = (f"/job/{job_id}/overlay/{ov['id']}" if src.get("source") == "local_file"
                     else src.get("value") if src.get("source") == "url" else None)
        overlays.append(o)
    clipes_ch = {t: _clipes_do_tipo(job, t) for t in {c.get("tipo") for c in job.get("cutaway_suggestions") or [] if c.get("chamada")} if t}
    cortes = [{k: c.get(k) for k in ("id", "insertion_point", "description", "audio_mode", "query", "chamada", "tipo", "texto", "remove_ate", "clipe_padrao")}
              | {"resolvido": bool(c.get("resolved_path")), "arquivo": os.path.basename(c["resolved_path"]) if c.get("resolved_path") else None,
                 "clipe_id": next((x["id"] for x in clipes_ch.get(c.get("tipo"), []) if x["caminho"] == c.get("resolved_path")), None)}
              for c in job.get("cutaway_suggestions") or []]
    biblioteca = [{"id": it["id"], "filename": it["filename"], "media_type": it["media_type"],
                   "descricao": it.get("descricao") or "", "rotulo": it.get("rotulo") or "",
                   "url": f"/job/{job_id}/library-file/{it['id']}"} for it in job.get("media_library") or []]
    try:
        falas, _pal = _falas_por_trecho(job, job["pending_segments"])
    except Exception:  # noqa: BLE001
        falas = [""] * len(segs)
    for sg, fala in zip(segs, falas):
        sg["_fala"] = fala
    return {
        "destaques": job.get("destaques") or [],
        "sfx": job.get("sfx") or [],
        "palavras": [{"w": w["word"], "s": round(float(w["start"]), 2), "e": round(float(w.get("end", w["start"])), 2)} for w in _palavras_da_narracao(job)],
        "legendas": job.get("legendas") or {},
        "kit": (job.get("editor_defaults") or {}).get("kit") or {},
        "graficos": job.get("graficos") or [],
        "editoriais": job.get("editoriais") or [],
        "editorial_tipos": __import__("dp_editorial").para_editor(),
        "censura": job.get("censura") or [],
        "graficos_tipos": __import__("dp_graficos").TIPOS, "graficos_posicoes": __import__("dp_graficos").POSICOES,
        "exportacao": {"resolucao": job.get("export_quality", "1080p"), "qualidade": job.get("qualidade_exportacao") or "normal",
                       "orientacao": _orientacao_do_job(job),
                       "resolucoes": [[q, "x".join(str(v) for v in resolution_for_orientation(_orientacao_do_job(job), q))] for q in __import__("qualidade_export").RESOLUCOES],
                       "resolucoes_por_formato": {o: [[q, "x".join(str(v) for v in resolution_for_orientation(o, q))] for q in __import__("qualidade_export").RESOLUCOES] for o in ("16:9", "9:16", "1:1")},
                       "qualidades": [[k, v["nome"]] for k, v in __import__("qualidade_export").QUALIDADES.items()],
                       "paralelo": dict(__import__("export_paralelo").recursos(), modo=job.get("export_paralelo") or __import__("export_paralelo").modo_atual())},
        "origem_legenda": "srt" if (job.get("segments") and not job.get("word_timestamps")) else "whisper",
        "blocos_fala": [{"start": float(b["start"]), "end": float(b["end"]), "text": b.get("text", "")} for b in job.get("segments") or [] if b.get("text")],
        "job_id": job_id, "segmentos": segs, "overlays": overlays, "cortes": cortes, "biblioteca": biblioteca,
        "links_tela": job.get("links_tela") or [],
        "intervalo": job.get("interval_seconds") or 7,
        "clipes_chamada": {t: [{"id": x["id"], "nome": x["nome"], "padrao": bool(x.get("padrao"))} for x in l] for t, l in clipes_ch.items()},
        "vinhetas": _vinhetas_editor(job),
        "perfis_canal": dict(__import__("perfis_canal").resumo(), do_video=__import__("perfis_canal").do_job(job)),
        "duracao": job.get("total_duration") or (job["pending_segments"][-1]["end"] if job["pending_segments"] else 0),
        "erro_indice": job.get("assembly_error_segment_index"),
        "erro_indices": job.get("assembly_error_segments") or [],
        "timelines": _timelines_estudio(job_id, job),
    }


@app.route("/job/<job_id>/direcao/plano", methods=["POST"])
def direcao_plano(job_id: str):
    """Monta o plano de uma Direção do DarkPlanner pros trechos que o Estúdio
    mandou (o Estúdio aplica e a pessoa salva/monta)."""
    import dp_direcao
    if job_id not in _JOBS:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    try:
        kit = corpo.get("kit") if isinstance(corpo.get("kit"), dict) else (_JOBS[job_id].get("editor_defaults") or {}).get("kit")
        plano = dp_direcao.planejar(corpo.get("segmentos") or [], str(corpo.get("direcao") or ""),
                                    semente=corpo.get("semente", 1), ritmo=corpo.get("ritmo") or None,
                                    so_vazios=bool(corpo.get("so_vazios")), kit=kit)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, **plano})


# ---- predefinições (perfis de direção) e paletas criadas pela pessoa
@app.route("/predefinicoes", methods=["GET"])
def predefinicoes_listar():
    import dp_direcao
    return jsonify({"ok": True, "direcoes": dp_direcao.direcoes(), "paletas": dp_direcao.paletas_usuario()})


@app.route("/predefinicoes/edicao", methods=["POST"])
def predefinicoes_edicao():
    """Cópia completa de uma predefinição (sistema, da pessoa ou o kit) pra abrir no editor."""
    import dp_direcao
    corpo = request.get_json(silent=True) or {}
    p = dp_direcao.para_edicao(str(corpo.get("id") or ""), corpo.get("kit") if isinstance(corpo.get("kit"), dict) else None)
    if not p:
        return jsonify({"erro": "Predefinição não encontrada."}), 404
    return jsonify({"ok": True, "predefinicao": p})


@app.route("/predefinicoes", methods=["POST"])
def predefinicoes_salvar():
    import dp_direcao
    try:
        p = dp_direcao.salvar_predefinicao(request.get_json(silent=True) or {})
    except (ValueError, TypeError) as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "predefinicao": p, "direcoes": dp_direcao.direcoes()})


@app.route("/predefinicoes/<pid>", methods=["DELETE"])
def predefinicoes_apagar(pid: str):
    import dp_direcao
    if not dp_direcao.apagar_predefinicao(pid):
        return jsonify({"erro": "Predefinição não encontrada (as do sistema não podem ser apagadas)."}), 404
    return jsonify({"ok": True, "direcoes": dp_direcao.direcoes()})


@app.route("/paletas", methods=["POST"])
def paletas_salvar():
    import dp_direcao
    try:
        p = dp_direcao.salvar_paleta(request.get_json(silent=True) or {})
    except (ValueError, TypeError) as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "paleta": p, "paletas": dp_direcao.paletas_usuario()})


@app.route("/paletas/<pid>", methods=["DELETE"])
def paletas_apagar(pid: str):
    import dp_direcao
    if not dp_direcao.apagar_paleta(pid):
        return jsonify({"erro": "Paleta não encontrada."}), 404
    return jsonify({"ok": True, "paletas": dp_direcao.paletas_usuario()})


def _catalogo_dp_editor() -> dict:
    import dp_direcao
    import dp_visual
    return {
        "filtros": [{k: f[k] for k in ("id", "rotulo", "grupo", "css")} for f in dp_visual.filtros()],
        "efeitos": dp_visual.efeitos(), "entradas": dp_visual.entradas(),
        "transicoes": dp_visual.transicoes(), "direcoes": dp_direcao.direcoes(),
        "paletas": __import__("dp_cores").PALETAS, "paletas_usuario": dp_direcao.paletas_usuario(), "paleta_padrao": __import__("dp_cores").padrao(),
        "legenda_estilos": __import__("dp_legendas").ESTILOS, "legenda_padrao": __import__("dp_legendas").padrao(),
        "fontes": sorted(set(__import__("dp_destaques")._FONTE.values())),
        "fundos": __import__("dp_fundos").para_editor(),
        "anims_entrada": __import__("dp_destaques").ANIMS_ENTRADA, "anims_saida": __import__("dp_destaques").ANIMS_SAIDA,
        "fontes_hl": {k: v for k, v in __import__("dp_destaques")._FONTE.items() if k != "default"},
        "graficos_esquemas": __import__("dp_graficos").ESQUEMAS, "graficos_cartoes": __import__("dp_graficos").CARTOES,
        "censura_tipos": __import__("dp_censura").TIPOS, "censura_formas": __import__("dp_censura").FORMAS,
    }


def _sons_editor():
    import dp_sons
    trans = {v: dp_sons.som_da_transicao(v) for v, _r in TRANSITION_LABELS if v != "none"}
    return {"categorias": dp_sons.categorias(), "por_transicao": trans}


def _estilos_destaque_editor():
    import dp_destaques
    return {"estilos": dp_destaques.catalogo_para_editor(), "paleta": dp_destaques.paleta_padrao()}


@app.route("/dp-galeria/previa/<estilo>.mp4")
def dp_galeria_previa(estilo: str):
    """Prévia animada de um destaque (gerada na 1ª vez e guardada)."""
    import dp_galeria
    try:
        caminho = dp_galeria.previa_destaque(estilo, os.path.join(OUTPUTS_DIR, "previas_destaques"))
    except ValueError:
        return "estilo desconhecido", 404
    return send_file(caminho, mimetype="video/mp4")


@app.route("/dp-galeria/<path:arquivo>")
def dp_galeria_arquivo(arquivo: str):
    import dp_galeria
    return send_from_directory(dp_galeria.GALERIA_DIR, arquivo, max_age=86400)


@app.route("/dp-fonte/<path:nome>")
def dp_fonte(nome: str):
    """Fontes dos destaques (as mesmas que o ffmpeg usa) pra prévia no Estúdio."""
    import dp_destaques
    return send_from_directory(dp_destaques.FONTES_DIR, nome)


@app.route("/dp-fontes.css")
def dp_fontes_css():
    import dp_destaques
    mapa = dp_destaques.fontes_json()  # fontes.json + fontes dos extras
    css = []
    for info in mapa.values():
        for est, arq in info["arquivos"].items():
            peso = "800" if est == "Bold" else "400"
            estilo_css = "italic" if est == "Italic" else "normal"
            css.append(f"@font-face{{font-family:'{info['familia']}';src:url('/dp-fonte/{arq}') format('truetype');font-weight:{peso};font-style:{estilo_css};font-display:swap}}")
    return app.response_class("\n".join(css), mimetype="text/css")


def _cenas_catalogo_editor():
    import cenas_dp
    return cenas_dp.catalogo_para_editor()


def _render_estudio(job_id: str, job: dict):
    target_width, target_height = resolution_for_orientation(
        _orientacao_do_job(job), job.get("export_quality", "1080p")
    )
    youtube_itens_lista = _youtube_itens_sincronizar(job)
    if any(it.get("status") == "pendente" for it in youtube_itens_lista):
        _youtube_buscar_pendentes(job_id)
    cfg = load_site_config()
    correcao = job.pop("ultima_correcao", None)
    return render_template(
        "estudio.html", correcao=correcao, job=job, dados=_dados_estudio(job_id, job),
        cenas=_cenas_catalogo_editor(), dp_cat=_catalogo_dp_editor(), estilos_destaque=_estilos_destaque_editor(),
        sons_cat=_sons_editor(),
        youtube_itens=youtube_itens_lista,
        video_providers=["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "moviepexels", "animepexels_online", "moviepexels_online", "youtube"],
        photo_providers=[p for p in DEFAULT_PROVIDERS if p in PHOTO_SEARCH_PROVIDERS],
        providers_with_url_support=sorted(PROVIDERS_WITH_URL_RESOLUTION),
        transicoes=TRANSITION_LABELS,
        transicao_do_site=dict(TRANSITION_LABELS).get(cfg.get("transition_type", "none"), "corte seco"),
        editor_defaults=job.get("editor_defaults", {"aspect_fill": cfg.get("aspect_fill", "black"), "trim_start_frames": cfg.get("trim_start_frames", 10)}),
        video_target_width=target_width, video_target_height=target_height,
        has_waveform=bool(job.get("waveform_path")),
        transicao_site_valor=cfg.get("transition_type", "none"),
        transicao_site_dur=cfg.get("transition_duration", 0.6),
    )


def _reindexar_previas_e_youtube(job: dict) -> None:
    # os itens do YouTube são identificados pelo índice do trecho: depois de
    # dividir/juntar, recria a lista (termos e resultados pesquisados se perdem
    # só pros trechos que mudaram de posição; são pesquisados de novo)
    antigos = {it.get("termo_original"): it for it in job.get("youtube_itens") or [] if it.get("tipo") == "segmento"}
    job["youtube_itens"] = [it for it in job.get("youtube_itens") or [] if it.get("tipo") != "segmento"]
    _youtube_itens_sincronizar(job)
    for it in job["youtube_itens"]:
        velho = antigos.get(it.get("termo_original"))
        if it.get("tipo") == "segmento" and velho and it.get("status") == "pendente":
            it.update({k: velho[k] for k in ("termo", "status", "resultados", "erro") if k in velho})


def _limpar_erro_do_trecho(job: dict, i: int) -> None:
    """A pessoa trocou a mídia do trecho que tinha falhado: o aviso some."""
    if job.get("assembly_error_segment_index") == i:
        job.pop("assembly_error", None)
        job["assembly_error_segment_index"] = None


def _trocar_pela_reserva(seg: dict, o_que: str) -> Optional[str]:
    """Busca que nada achou e a IA deixou reservas: passa pra 1ª reserva (as
    outras continuam de reserva). Devolve a mensagem, ou None sem reserva."""
    alts = [a for a in (seg.get("alternativas") or []) if a and str(a).strip()]
    if not alts:
        return None
    antiga = seg.get("query") or ""
    seg["query"] = alts[0]
    seg["alternativas"] = alts[1:] or None
    return f"Nada achou {o_que} pra “{antiga}” — trocado pela busca reserva da IA “{seg['query']}”"


def _corrigir_trecho(job_id: str, job: dict, i: int) -> str:
    """Diagnostica e conserta sozinho o trecho que derrubou a montagem.
    Devolve uma frase dizendo o que foi feito."""
    from video_assembler import _infer_media_kind, _probe_duration, garantir_imagem_compativel

    seg = job["pending_segments"][i]
    ov = seg.get("override_source") or {}
    fonte = ov.get("source")
    if fonte == "local_file":
        caminho = ov.get("value") or ""
        if not caminho or not os.path.isfile(caminho):
            seg["override_source"] = None
            return "O arquivo escolhido não existe mais — o trecho voltou pra busca automática."
        if _infer_media_kind(caminho) == "image" or ov.get("kind") == "image":
            try:
                novo = garantir_imagem_compativel(caminho)
            except Exception:  # noqa: BLE001
                seg["override_source"] = None
                return "A imagem escolhida não pôde ser lida (arquivo corrompido) — o trecho voltou pra busca automática."
            seg["override_source"] = dict(ov, value=novo, kind="image")
            seg["media_type"] = "image"
            if novo != caminho:
                return f"A imagem estava em {os.path.splitext(caminho)[1].upper().lstrip('.')} (formato que o ffmpeg não lê bem) e foi convertida pra JPG."
            return "A imagem foi conferida e está legível — o trecho foi marcado como FOTO."
        try:
            if _probe_duration(caminho) > 0:
                return "O vídeo escolhido é legível — nada pra corrigir nele (tente montar de novo)."
        except Exception:  # noqa: BLE001
            pass
        reparado = os.path.splitext(caminho)[0] + "_reparado.mp4"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-err_detect", "ignore_err", "-i", caminho,
                            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", reparado],
                           check=True, capture_output=True, timeout=600)
            if _probe_duration(reparado) > 0:
                seg["override_source"] = dict(ov, value=reparado, kind="video")
                return "O vídeo estava com problema e foi recodificado (reparado)."
        except Exception:  # noqa: BLE001
            pass
        seg["override_source"] = None
        return "O vídeo escolhido estava ilegível e não deu pra reparar — o trecho voltou pra busca automática."
    if fonte in ("url", "provider_url"):
        seg["override_source"] = None
        return "O link escolhido não funcionou — o trecho voltou pra busca automática."
    # busca automática que falhou
    cache = job.get("imagens_buscadores") or {}
    cache.pop(" ".join((seg.get("query") or "").split()), None)
    if (seg.get("media_type") or "video") == "image":
        if seg.get("provider") not in BROWSER_IMAGE_SEARCH_PROVIDERS:
            antigo = seg.get("provider")
            seg["provider"] = "bing"
            return f"A busca de foto em {antigo} falhou — trocado pros buscadores de imagem (Bing, e se não achar Brave/Yandex/Startpage)."
        _msg = _trocar_pela_reserva(seg, "a imagem")
        if _msg:
            return _msg + "."
        palavras = (seg.get("query") or "").split()
        if len(palavras) > 3:
            seg["query"] = " ".join(palavras[:3])
            return f"Nenhum buscador achou a imagem — termo simplificado pra “{seg['query']}”."
        return "Busca limpa — os 4 buscadores vão tentar de novo na próxima montagem."
    if seg.get("provider") == "youtube":
        return "Trecho do YouTube sem vídeo escolhido — na montagem ele usa o 1º resultado ou os bancos normais."
    _msg = _trocar_pela_reserva(seg, "vídeo")
    if _msg:
        return _msg + " (a montagem tenta todos os bancos)."
    palavras = (seg.get("query") or "").split()
    if len(palavras) > 3:
        seg["query"] = " ".join(palavras[:3])
        return f"Nenhum banco achou vídeo — termo simplificado pra “{seg['query']}” (a montagem tenta todos os bancos)."
    return "Nada específico pra corrigir — a montagem vai tentar todos os bancos de novo."


@app.route("/job/<job_id>/corrigir-trecho", methods=["POST"])
def corrigir_trecho(job_id: str):
    """Botão "🔧 Corrigir automaticamente" do aviso de montagem que falhou."""
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or request.form
    try:
        i = int(corpo.get("indice", job.get("assembly_error_segment_index")))
    except (TypeError, ValueError):
        i = -1
    if not (0 <= i < len(job["pending_segments"])):
        return jsonify({"erro": "Não sei qual trecho corrigir — a montagem não apontou um trecho."}), 400
    mensagem = _corrigir_trecho(job_id, job, i)
    job.pop("assembly_error", None)
    job["assembly_error_segment_index"] = None
    job["ultima_correcao"] = f"Trecho {i + 1}: {mensagem}"
    previews = list(job.get("segment_previews") or [])
    if i < len(previews) and previews[i] and not (job["pending_segments"][i].get("override_source")):
        previews[i] = dict(previews[i], ok=False, error="corrigido — será buscado de novo na montagem")
        job["segment_previews"] = previews
    _save_state(job_id)
    if request.is_json:
        return jsonify({"ok": True, "mensagem": mensagem, "indice": i, "segmento": job["pending_segments"][i]})
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/editor/dividir", methods=["POST"])
def editor_dividir(job_id: str):
    """Divide um trecho em dois no instante indicado (o 2º herda termo/banco,
    sem o arquivo escolhido — pra você escolher outra mídia pra ele)."""
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    try:
        i, t = int(corpo["indice"]), float(corpo["tempo"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"erro": "Informe 'indice' e 'tempo'."}), 400
    segs = job["pending_segments"]
    if not (0 <= i < len(segs)):
        return jsonify({"erro": "Trecho inexistente."}), 404
    seg = segs[i]
    if not (seg["start"] + 0.3 <= t <= seg["end"] - 0.3):
        return jsonify({"erro": "Escolha um ponto a pelo menos 0,3s das pontas do trecho."}), 400
    novo = dict(seg, start=round(t, 3), override_source=None)
    novo.pop("template", None)  # a cena começa no 1º pedaço; o 2º vira um take dela (se couber)
    novo.pop("template_campos", None)
    seg = dict(seg, end=round(t, 3))
    seg.pop("transition", None)
    seg.pop("transition_duration", None)
    segs[i:i + 1] = [seg, novo]
    previews = list(job.get("segment_previews") or [])
    if i < len(previews):
        previews.insert(i + 1, dict(previews[i], index=i + 1) if previews[i] else None)
        job["segment_previews"] = [dict(p, index=k) if p else None for k, p in enumerate(previews)]
    _reindexar_previas_e_youtube(job)
    _save_state(job_id)
    return jsonify({"ok": True})


@app.route("/job/<job_id>/editor/dividir-longo", methods=["POST"])
def editor_dividir_longo(job_id: str):
    """✂️ Divide um trecho longo (ou TODOS os longos, sem "indice") em pedaços do tamanho do intervalo, nas pausas
    da fala. Os pedaços novos ganham busca própria (as reservas da IA — e, com a 🤖 IA, a busca pela fala de cada um)
    e prévia nova em segundo plano."""
    import trechos_longos
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    segs = job["pending_segments"]
    intervalo = job.get("interval_seconds") or 7
    if corpo.get("indice") is not None:
        try:
            alvos = [int(corpo["indice"])]
        except (TypeError, ValueError):
            return jsonify({"erro": "Índice inválido."}), 400
        if not (0 <= alvos[0] < len(segs)):
            return jsonify({"erro": "Trecho inexistente."}), 404
        s0 = segs[alvos[0]]
        if float(s0["end"]) - float(s0["start"]) < 2 * max(3.0, float(intervalo)) or s0.get("template"):
            return jsonify({"erro": "Esse trecho não é longo (ou é uma cena) — use ✂️ Dividir no cursor."}), 400
    else:
        alvos = [i for i, sg in enumerate(segs) if trechos_longos.pode_dividir(sg, intervalo)]
    if not alvos:
        return jsonify({"ok": True, "divididos": 0, "novos": 0})
    pausas = trechos_longos.pausas_da_fala(job.get("segments"))
    previews = list(job.get("segment_previews") or [None] * len(segs))
    novos_idx: List[int] = []
    for i in sorted(alvos, reverse=True):
        partes = trechos_longos.pedacos(segs[i], intervalo, pausas)  # o 1º pedaço fica com a mídia escolhida
        segs[i:i + 1] = partes
        prev_i = previews[i] if i < len(previews) else None
        previews[i:i + 1] = [prev_i] + [None] * (len(partes) - 1)
        novos_idx = [n + len(partes) - 1 for n in novos_idx] + list(range(i + 1, i + len(partes)))
    job["segment_previews"] = [dict(p, index=k) if p else None for k, p in enumerate(previews)]
    _reindexar_previas_e_youtube(job)
    _save_state(job_id)
    threading.Thread(target=_previas_dos_pedacos, args=(job_id, sorted(novos_idx)), daemon=True).start()
    return jsonify({"ok": True, "divididos": len(alvos), "novos": len(novos_idx)})


def _previas_dos_pedacos(job_id: str, idx: List[int]) -> None:
    """Pedaços novos: com a 🤖 IA, a busca de cada um pela fala dele; depois a prévia de cada um."""
    job = _JOBS.get(job_id)
    if not job or not idx:
        return
    segs = job["pending_segments"]
    try:
        import ia_midia
        import ia_servico
        if ia_servico.ativo("buscas"):
            falas, _p = _falas_por_trecho(job, [segs[i] for i in idx])
            _ant, _p1 = _falas_por_trecho(job, [segs[i - 1] if i > 0 else {"start": 0, "end": 0} for i in idx])
            _dep, _p2 = _falas_por_trecho(job, [segs[i + 1] if i + 1 < len(segs) else {"start": 0, "end": 0} for i in idx])
            _viz = (_ant, _dep)
            novas = ia_midia.buscas_melhores([{"n": k + 1, "fala": f, "query": segs[i].get("query"), "antes": _viz[0][k],
                                               "depois": _viz[1][k]} for k, (i, f) in enumerate(zip(idx, falas))],
                                             (job.get("ia") or {}).get("ficha"), job=job_id)
            for k, i in enumerate(idx):
                nb = novas.get(k + 1)
                if nb and i < len(segs) and not segs[i].get("override_source"):
                    segs[i].update(query=nb["buscas"][0], alternativas=nb["buscas"][1:] or None,
                                   **({"visual": nb["visual"]} if nb.get("visual") else {}))
    except Exception:  # noqa: BLE001 — sem IA: ficam as reservas
        pass
    for i in idx:
        if i >= len(segs) or segs[i].get("override_source"):
            continue
        try:
            with app.test_request_context(json={"alternativas": segs[i].get("alternativas") or []}):
                buscas_previa(job_id, i)
        except Exception:  # noqa: BLE001
            continue
    _save_state(job_id)


@app.route("/job/<job_id>/editor/juntar", methods=["POST"])
def editor_juntar(job_id: str):
    """Junta o trecho `indice` com o PRÓXIMO (o primeiro estica até o fim do
    segundo, que some)."""
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    try:
        i = int((request.get_json(silent=True) or {})["indice"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"erro": "Informe 'indice'."}), 400
    segs = job["pending_segments"]
    if not (0 <= i < len(segs) - 1):
        return jsonify({"erro": "Não há próximo trecho pra juntar."}), 400
    proximo = segs[i + 1]
    segs[i] = dict(segs[i], end=proximo["end"])
    for k in ("transition", "transition_duration"):
        if k in proximo:
            segs[i][k] = proximo[k]
        else:
            segs[i].pop(k, None)
    del segs[i + 1]
    previews = list(job.get("segment_previews") or [])
    if i + 1 < len(previews):
        del previews[i + 1]
        job["segment_previews"] = [dict(p, index=k) if p else None for k, p in enumerate(previews)]
    _reindexar_previas_e_youtube(job)
    _save_state(job_id)
    return jsonify({"ok": True})


def _render_editor_classico(job_id: str, job: dict):
    # Resolução real de saída (largura/altura em px) do vídeo final,
    # conforme orientação + qualidade escolhidas no job — o monitor de
    # composição usa isso pra escalar o texto na prévia no MESMO
    # tamanho relativo que ele vai sair no vídeo renderizado (sem isso,
    # o font-size em px era aplicado direto na prévia, que é bem menor
    # na tela que a resolução final, deixando o texto desproporcional).
    target_width, target_height = resolution_for_orientation(
        _orientacao_do_job(job), job.get("export_quality", "1080p")
    )
    youtube_itens_lista = _youtube_itens_sincronizar(job)
    if any(it.get("status") == "pendente" for it in youtube_itens_lista):
        _youtube_buscar_pendentes(job_id)
    return render_template(
        "edit_segments.html", job=job, segments=job["pending_segments"],
        youtube_itens=youtube_itens_lista,
        video_providers=["pexels", "pixabay", "magnific", "mixkit", "vistacreate", "animepexels", "moviepexels", "animepexels_online", "moviepexels_online", "youtube"],
        photo_providers=[p for p in DEFAULT_PROVIDERS if p in PHOTO_SEARCH_PROVIDERS],
        browser_image_providers=list(BROWSER_IMAGE_SEARCH_PROVIDERS),
        transicoes=TRANSITION_LABELS,
        transicao_do_site=dict(TRANSITION_LABELS).get(load_site_config().get("transition_type", "none"), "corte seco"),
        previews=job.get("segment_previews", []),
        has_waveform=bool(job.get("waveform_path")),
        providers_with_url_support=["pexels", "pixabay", "mixkit"],
        providers_with_pin_support=sorted(PROVIDERS_WITH_URL_RESOLUTION),
        overlays=job.get("overlays", []),
        cutaway_suggestions=job.get("cutaway_suggestions", []),
        media_library=job.get("media_library", []),
        all_providers=DEFAULT_PROVIDERS,
        editor_defaults=job.get("editor_defaults", {"aspect_fill": load_site_config().get("aspect_fill", "black"), "trim_start_frames": load_site_config().get("trim_start_frames", 10)}),
        video_target_width=target_width,
        video_target_height=target_height,
    )


@app.route("/job/<job_id>/edit-captions", methods=["GET"])
def edit_captions_page(job_id: str):
    """Página de edição manual de cada palavra da legenda — texto e
    tempo (início/fim) de cada uma, individualmente. Só acessível
    quando o job tem `word_timestamps` (marcou a opção de gerar
    legenda no upload)."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    if not job.get("word_timestamps"):
        return "Este job não tem legenda por palavra pra editar (a opção não foi marcada no upload).", 404
    return render_template("edit_captions.html", job=job, words=job["word_timestamps"])


@app.route("/job/<job_id>/save-captions", methods=["POST"])
def save_captions(job_id: str):
    """Salva as edições manuais feitas nas palavras da legenda (texto
    e/ou tempo de cada uma) — a lista inteira é reconstruída a partir
    do formulário, na mesma ordem de sempre."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    if not job.get("word_timestamps"):
        return "Este job não tem legenda por palavra pra editar.", 404

    original = job["word_timestamps"]
    updated = []
    for i in range(len(original)):
        word = request.form.get(f"word_{i}_text", "").strip()
        if not word:
            continue  # deixar o campo de texto vazio remove essa palavra da legenda
        try:
            start = float(request.form.get(f"word_{i}_start", original[i]["start"]))
            end = float(request.form.get(f"word_{i}_end", original[i]["end"]))
        except (TypeError, ValueError):
            return f"Palavra {i}: tempo inválido — 'início'/'fim' precisam ser números.", 400
        if end <= start:
            return f"Palavra {i} ({word!r}): 'fim' precisa ser maior que 'início'.", 400
        updated.append({"word": word, "start": start, "end": end})

    if not updated:
        return "A legenda não pode ficar totalmente vazia — mantenha pelo menos uma palavra.", 400

    job["word_timestamps"] = updated
    _save_state(job_id)
    return redirect(url_for("edit_captions_page", job_id=job_id))


@app.route("/job/<job_id>/add-overlay", methods=["POST"])
def add_overlay(job_id: str):
    """Adiciona um overlay (imagem/vídeo sobreposto ao vídeo final, com
    posição/tamanho/janela de tempo PRÓPRIOS, independentes dos
    segmentos) — pode vir de upload, link direto, ou busca num banco.
    """
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    try:
        start = float(request.form.get("start", "0"))
        end = float(request.form.get("end", "0"))
    except ValueError:
        return "'start'/'end' precisam ser números.", 400
    if end <= start:
        return "'end' precisa ser maior que 'start'.", 400

    source_mode = request.form.get("source_mode", "upload")
    if source_mode == "upload":
        uploaded = request.files.get("overlay_file")
        if not uploaded or not uploaded.filename:
            return "Nenhum arquivo enviado.", 400
        overlays_dir = os.path.join(_job_dir(job_id), "overlay_uploads")
        os.makedirs(overlays_dir, exist_ok=True)
        safe_name = secure_filename(uploaded.filename)
        dest = os.path.join(overlays_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
        uploaded.save(dest)
        ext = os.path.splitext(safe_name)[1].lower()
        kind = "image" if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif") else "video"
        source = {"source": "local_file", "value": dest, "kind": kind}
    elif source_mode == "url":
        url = request.form.get("overlay_url", "").strip()
        if not url:
            return "Informe o link do arquivo.", 400
        source = {"source": "url", "value": url}
    elif source_mode == "search":
        provider = request.form.get("overlay_provider", "").strip().lower()
        query = request.form.get("overlay_query", "").strip()
        if not provider or not query:
            return "Informe o banco e o termo de busca.", 400
        source = {"source": "provider_search", "provider": provider, "query": query}
    else:
        return f"'source_mode' desconhecido: {source_mode!r}.", 400

    overlay = {
        "id": uuid.uuid4().hex[:8],
        "source": source,
        "start": start, "end": end,
        "position": request.form.get("position", "top-right"),
        "size_percent": max(1.0, min(100.0, float(request.form.get("size_percent", 20) or 20))),
        "x_percent": max(0.0, min(100.0, float(request.form.get("x_percent", 80) or 80))),
        "y_percent": max(0.0, min(100.0, float(request.form.get("y_percent", 20) or 20))),
    }
    job.setdefault("overlays", []).append(overlay)
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/add-text-overlay", methods=["POST"])
def add_text_overlay(job_id: str):
    """Adiciona um overlay de TEXTO puro (título/chamada) — independente
    de um trecho da narração, com tempo/posição/estilo próprios.
    Reaproveita a mesma lista `job["overlays"]` dos overlays de imagem/
    vídeo (distinguidos por `media_type: "text"`) — assim a remoção
    (`remove_overlay`) já funciona pra esse tipo sem precisar de rota
    própria.
    """
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    text = request.form.get("text", "").strip()
    if not text:
        return "Informe o texto.", 400
    try:
        start = float(request.form.get("start", "0"))
        end = float(request.form.get("end", "0"))
    except ValueError:
        return "'start'/'end' precisam ser números.", 400
    if end <= start:
        return "'end' precisa ser maior que 'start'.", 400

    style = {
        "position": request.form.get("position", "bottom-center"),
        "font": request.form.get("font", "bold"),
        "border": request.form.get("border") == "on",
        "background": request.form.get("background") == "on",
        "x_percent": max(0.0, min(100.0, float(request.form.get("x_percent", 50) or 50))),
        "y_percent": max(0.0, min(100.0, float(request.form.get("y_percent", 88) or 88))),
    }
    font_size_raw = request.form.get("font_size", "").strip()
    if font_size_raw:
        try:
            style["font_size"] = int(font_size_raw)
        except ValueError:
            pass  # valor inválido -- ignora e usa o tamanho automático

    overlay = {
        "id": uuid.uuid4().hex[:8],
        "media_type": "text",
        "text": text,
        "start": start, "end": end,
        "style": style,
    }
    job.setdefault("overlays", []).append(overlay)
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/update-overlay/<overlay_id>", methods=["POST"])
def update_overlay(job_id: str, overlay_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job não encontrado."}), 404
    ov = next((x for x in job.get("overlays", []) if x.get("id") == overlay_id), None)
    if not ov:
        return jsonify({"error": "Overlay não encontrado."}), 404
    data = request.get_json(silent=True) or {}
    try:
        if "start" in data: ov["start"] = max(0.0, float(data["start"]))
        if "end" in data: ov["end"] = max(ov.get("start", 0.0), float(data["end"]))
        if "x_percent" in data: ov["x_percent"] = max(0.0, min(100.0, float(data["x_percent"])))
        if "y_percent" in data: ov["y_percent"] = max(0.0, min(100.0, float(data["y_percent"])))
        if "size_percent" in data: ov["size_percent"] = max(1.0, min(100.0, float(data["size_percent"])))
        if "position" in data: ov["position"] = str(data["position"])[:20]
        if ov.get("media_type") == "text":
            if "text" in data and str(data["text"]).strip():
                ov["text"] = str(data["text"]).strip()[:300]
            estilo = ov.setdefault("style", {})
            if "x_percent" in data: estilo["x_percent"] = ov["x_percent"]
            if "y_percent" in data: estilo["y_percent"] = ov["y_percent"]
            if "font_size" in data and data["font_size"] not in (None, ""):
                estilo["font_size"] = max(8, min(400, int(float(data["font_size"]))))
    except (TypeError, ValueError):
        return jsonify({"error": "Valores inválidos."}), 400
    _save_state(job_id)
    return jsonify({"ok": True, "overlay": ov})


@app.route("/job/<job_id>/segment-media/<int:index>", methods=["GET"])
def serve_segment_media(job_id: str, index: int):
    job = _JOBS.get(job_id)
    if not job or index < 0 or index >= len(job.get("pending_segments", [])):
        return "Trecho não encontrado.", 404
    seg = job["pending_segments"][index]
    src = seg.get("override_source") or {}
    path = src.get("value") if src.get("source") == "local_file" else None
    if path and os.path.isfile(path):
        return send_file(path)
    return "Arquivo local do trecho não está disponível para preview.", 404


@app.route("/job/<job_id>/segment-thumb/<int:index>", methods=["GET"])
def serve_segment_thumb(job_id: str, index: int):
    """Miniatura do arquivo escolhido pra um trecho (upload, biblioteca, clipe
    do YouTube, imagem baixada) — pra timeline do Estúdio mostrar o que de
    fato vai entrar, não só a prévia da busca. Gerada uma vez e guardada."""
    job = _JOBS.get(job_id)
    if not job or index < 0 or index >= len(job.get("pending_segments", [])):
        return "Trecho não encontrado.", 404
    src = job["pending_segments"][index].get("override_source") or {}
    path = src.get("value") if src.get("source") == "local_file" else None
    if not path or not os.path.isfile(path):
        return "Sem arquivo local.", 404
    pasta = os.path.join(_job_dir(job_id), "miniaturas")
    os.makedirs(pasta, exist_ok=True)
    chave = uuid.uuid5(uuid.NAMESPACE_URL, f"{path}|{os.path.getmtime(path)}").hex[:16]
    destino = os.path.join(pasta, f"{chave}.jpg")
    if not os.path.exists(destino):
        try:
            generate_thumbnail(path, destino)
        except Exception:  # noqa: BLE001
            return "Não deu pra gerar a miniatura.", 500
    return send_file(destino)


@app.route("/job/<job_id>/overlay/<overlay_id>", methods=["GET"])
def serve_overlay(job_id: str, overlay_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    ov = next((x for x in job.get("overlays", []) if x.get("id") == overlay_id), None)
    if not ov:
        return "Overlay não encontrado.", 404
    path = (ov.get("source") or {}).get("value") if (ov.get("source") or {}).get("source") == "local_file" else None
    if path and os.path.isfile(path):
        return send_file(path)
    resolved = ov.get("resolved_path")
    if resolved and os.path.isfile(resolved):
        return send_file(resolved)
    return "Arquivo do overlay ainda não está disponível para preview.", 404


@app.route("/job/<job_id>/remove-overlay/<overlay_id>", methods=["POST"])
def remove_overlay(job_id: str, overlay_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    job["overlays"] = [ov for ov in job.get("overlays", []) if ov["id"] != overlay_id]
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/overlays/textos-1a-ia", methods=["POST"])
def overlays_textos_1a_ia(job_id: str):
    """Overlays de TEXTO que a 1ª IA (a das buscas) sugeriu: "remover" tira do
    vídeo (guardados no job pra o ↩ Desfazer) e "restaurar" põe de volta."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    acao = (request.get_json(silent=True) or {}).get("acao")
    guardados = job.setdefault("overlays_1a_ia_removidos", [])
    if acao == "remover":
        sair = [ov for ov in job.get("overlays") or [] if ov.get("origem") == "ia_busca" and ov.get("media_type") == "text"]
        ids = {ov["id"] for ov in sair}
        job["overlays"] = [ov for ov in job.get("overlays") or [] if ov["id"] not in ids]
        guardados.extend(sair)
    elif acao == "restaurar":
        existentes = {ov["id"] for ov in job.get("overlays") or []}
        sair = [ov for ov in guardados if ov["id"] not in existentes]
        job["overlays"] = (job.get("overlays") or []) + sair
        job["overlays_1a_ia_removidos"] = []
    else:
        return jsonify({"erro": "acao = remover ou restaurar"}), 400
    _save_state(job_id)
    return jsonify({"ok": True, "overlays": sair})


@app.route("/job/<job_id>/bulk-update-overlays", methods=["POST"])
def bulk_update_overlays(job_id: str):
    """Aplica a MESMA configuração (posição x/y, tamanho) a vários
    overlays de uma vez — pedido explícito: em vez de configurar cada
    overlay de texto/imagem/vídeo individualmente, selecionar vários na
    listagem e aplicar um valor comum pra todos (ex: "y=50, tamanho=80
    pra estes 4 aqui").

    Só atualiza os campos que a pessoa efetivamente preencheu no
    formulário — deixar um campo vazio significa "não mexer nesse
    aspecto desses overlays", não "zerar".
    """
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    selected_ids = set(request.form.getlist("overlay_ids"))
    if not selected_ids:
        return "Selecione pelo menos um overlay.", 400

    x_percent_raw = request.form.get("x_percent", "").strip()
    y_percent_raw = request.form.get("y_percent", "").strip()
    size_raw = request.form.get("size", "").strip()  # font_size (texto) OU size_percent (imagem/vídeo), conforme o tipo de cada overlay

    updated = 0
    for ov in job.get("overlays", []):
        if ov["id"] not in selected_ids:
            continue
        updated += 1
        is_text = ov.get("media_type") == "text"
        target = ov.setdefault("style", {}) if is_text else ov

        if x_percent_raw:
            try:
                target["x_percent"] = max(0.0, min(100.0, float(x_percent_raw)))
            except ValueError:
                pass
        if y_percent_raw:
            try:
                target["y_percent"] = max(0.0, min(100.0, float(y_percent_raw)))
            except ValueError:
                pass
        if size_raw:
            try:
                size_value = float(size_raw)
            except ValueError:
                pass
            else:
                if is_text:
                    target["font_size"] = int(size_value)
                else:
                    target["size_percent"] = max(1.0, min(100.0, size_value))

    if updated == 0:
        return "Nenhum dos overlays selecionados foi encontrado (pode já ter sido removido).", 400

    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/upload-cutaway/<cutaway_id>", methods=["POST"])
def upload_cutaway(job_id: str, cutaway_id: str):
    """Recebe o upload do clipe real pra uma sugestão de CORTE (vídeo+
    áudio, não camada) que a IA identificou — sem isso, a sugestão fica
    só como uma anotação no editor, nunca é aplicada na montagem.
    Também permite trocar o `audio_mode` sugerido pela IA, se a pessoa
    preferir o outro comportamento.
    """
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    cutaway = next((c for c in job.get("cutaway_suggestions", []) if c["id"] == cutaway_id), None)
    if cutaway is None:
        return "Sugestão de corte não encontrada.", 404

    uploaded = request.files.get("cutaway_file")
    if not uploaded or not uploaded.filename:
        return "Nenhum arquivo enviado.", 400

    cutaways_dir = os.path.join(_job_dir(job_id), "cutaway_uploads")
    os.makedirs(cutaways_dir, exist_ok=True)
    safe_name = secure_filename(uploaded.filename)
    dest = os.path.join(cutaways_dir, f"{cutaway_id}_{safe_name}")
    uploaded.save(dest)

    cutaway["resolved_path"] = dest
    cutaway["clipe_padrao"] = False
    cutaway.pop("desligada", None)
    if cutaway.get("chamada"):
        _registrar_clipe_chamada(job, cutaway["tipo"], dest, uploaded.filename)
    audio_mode = request.form.get("audio_mode", "").strip().lower()
    if audio_mode in ("pause", "continue"):
        cutaway["audio_mode"] = audio_mode
    if cutaway.get("chamada") and request.form.get("padrao") == "on":
        # vira o padrão do tipo (entra na 1ª marca desse tipo dos próximos vídeos). As outras
        # marcas deste vídeo NÃO ganham o clipe sozinhas: só uma por tipo, a não ser que a
        # pessoa ligue mais na aba ✂️ Cortes.
        import chamadas as _chm
        _chm.definir_padrao(cutaway["tipo"], dest)

    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/chamada/nova", methods=["POST"])
def chamada_nova(job_id: str):
    """Chamada (inscreva-se/venda/link) marcada à mão no Estúdio — pra áudio
    que não veio do Gerar voz com os marcadores. Início = fim: o clipe entra
    naquele ponto (a narração pausa); com um intervalo, substitui esse trecho."""
    import chamadas as _chm
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    tipo = str(corpo.get("tipo") or "inscreva")
    if tipo not in _chm.TIPOS:
        return jsonify({"erro": "Tipo de chamada desconhecido."}), 400
    total = float(job.get("total_duration") or 0) or 1e9
    try:
        ini = max(0.0, min(total, float(corpo.get("inicio") or 0)))
        fim = max(ini, min(total, float(corpo.get("fim") if corpo.get("fim") not in (None, "") else ini)))
    except (TypeError, ValueError):
        return jsonify({"erro": "Tempo inválido."}), 400
    novo = _chm.para_cortes([{"tipo": tipo, "texto": str(corpo.get("texto") or "")[:300], "inicio": ini, "fim": fim}])[0]
    job.setdefault("cutaway_suggestions", []).append(novo)
    _save_state(job_id)
    return jsonify({"ok": True, "id": novo["id"]})


@app.route("/job/<job_id>/chamada/<cutaway_id>/tirar-clipe", methods=["POST"])
def chamada_tirar_clipe(job_id: str, cutaway_id: str):
    """Tira o clipe da chamada (a narração volta a valer ali) sem apagar a chamada.
    `padrao=1` também deixa de usar o clipe padrão desse tipo nos próximos vídeos."""
    import chamadas as _chm
    job = _JOBS.get(job_id)
    cut = next((c for c in (job or {}).get("cutaway_suggestions", []) if c["id"] == cutaway_id), None)
    if not cut:
        return jsonify({"erro": "Chamada não encontrada."}), 404
    cut["resolved_path"] = None
    cut["clipe_padrao"] = False
    if (request.get_json(silent=True) or {}).get("padrao") and cut.get("tipo") in _chm.TIPOS:
        _chm.definir_padrao(cut["tipo"], None, __import__("perfis_canal").do_job(job))
    _save_state(job_id)
    return jsonify({"ok": True})


def _clipes_do_tipo(job: dict, tipo: str) -> List[Dict[str, Any]]:
    """Vídeos de chamada (venda / like-inscreva-se) deste projeto: os do 📺 perfil do canal do vídeo (v84_101) + os
    enviados só pra ele + os que já estão em alguma marca. Cada um com um id estável."""
    import hashlib

    import perfis_canal
    pid = perfis_canal.do_job(job)
    do_perfil = perfis_canal.videos(tipo, pid)
    padrao = perfis_canal.caminho_padrao(tipo, pid)
    dos_perfis = {v["arquivo"] for v in do_perfil}
    proprios = [dict(c, so_deste=True) for c in (job.setdefault("clipes_chamada", {})).get(tipo) or []
                if c.get("caminho") and c["caminho"] not in dos_perfis]
    lista: List[Dict[str, Any]] = []
    caminhos: List[str] = []

    def por(cam, nome, **extra):
        if cam and cam not in caminhos and os.path.isfile(cam):
            lista.append({"id": hashlib.md5(cam.encode("utf-8")).hexdigest()[:10], "caminho": cam, "nome": nome,
                          "padrao": cam == padrao, **extra})
            caminhos.append(cam)
    for v in do_perfil:
        por(v["arquivo"], "📺 " + v["nome"], perfil=True)
    for c in proprios:
        por(c["caminho"], c.get("nome") or os.path.basename(c["caminho"]), so_deste=True)
    for c in job.get("cutaway_suggestions", []):
        if c.get("chamada") and c.get("tipo") == tipo:
            por(c.get("resolved_path"), os.path.basename(c.get("resolved_path") or ""))
    job["clipes_chamada"][tipo] = [c for c in lista if c.get("so_deste")]
    return lista


def _registrar_clipe_chamada(job: dict, tipo: str, caminho: str, nome: str) -> Dict[str, Any]:
    import hashlib
    _clipes_do_tipo(job, tipo)
    lista = job["clipes_chamada"].setdefault(tipo, [])
    item = next((c for c in lista if c["caminho"] == caminho), None)
    if not item:
        item = {"id": hashlib.md5(caminho.encode("utf-8")).hexdigest()[:10], "caminho": caminho, "nome": nome, "so_deste": True}
        lista.append(item)
    item["nome"] = nome or item["nome"]
    return item


@app.route("/job/<job_id>/chamadas/<tipo>/enviar", methods=["POST"])
def chamadas_enviar(job_id: str, tipo: str):
    """Mais um vídeo de venda / like-inscreva-se pro projeto (sem pôr em marca nenhuma ainda)."""
    import chamadas as _chm
    job = _JOBS.get(job_id)
    if not job or tipo not in _chm.TIPOS:
        return "Job ou tipo não encontrado.", 404
    up = request.files.get("arquivo")
    if not up or not up.filename:
        return "Nenhum arquivo enviado.", 400
    pasta = os.path.join(_job_dir(job_id), "cutaway_uploads")
    os.makedirs(pasta, exist_ok=True)
    nome = secure_filename(up.filename)
    dest = os.path.join(pasta, f"{tipo}_{uuid.uuid4().hex[:6]}_{nome}")
    up.save(dest)
    if request.form.get("perfil") == "on":  # 📺 guarda na biblioteca do perfil deste vídeo (serve pros próximos vídeos)
        import perfis_canal
        perfis_canal.adicionar_video(perfis_canal.do_job(job), tipo, dest, up.filename)
        try:
            os.remove(dest)
        except OSError:
            pass
    else:
        _registrar_clipe_chamada(job, tipo, dest, up.filename)
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id) + "#cortes")


@app.route("/job/<job_id>/vinhetas/<tipo>", methods=["POST"])
def job_vinheta(job_id: str, tipo: str):
    """🎬 abertura / 🏁 encerramento deste vídeo: liga/desliga ("usar") ou envia um vídeo só pra ele (e, se pedir, padrão)."""
    import canal
    job = _JOBS.get(job_id)
    if not job or tipo not in canal.VINHETAS:
        return jsonify({"erro": "Job ou tipo não encontrado."}), 404
    up = request.files.get("arquivo")
    if up and up.filename:
        tmp = os.path.join(_job_dir(job_id), "cutaway_uploads")
        os.makedirs(tmp, exist_ok=True)
        orig = os.path.join(tmp, f"_up_{uuid.uuid4().hex[:6]}_{secure_filename(up.filename)}")
        up.save(orig)
        if request.form.get("padrao") == "on":  # vai pra biblioteca do 📺 perfil deste vídeo, como ⭐ padrão
            import perfis_canal
            pid = perfis_canal.do_job(job)
            perfis_canal.adicionar_video(pid, tipo, orig, up.filename, padrao=True)
            v = job.setdefault("vinhetas", {}).setdefault(tipo, {})
            v.pop("caminho", None)
            v.pop("video_id", None)
            v["usar"] = True
        else:
            canal.guardar_no_job(job, tipo, _job_dir(job_id), orig, up.filename)
        try:
            os.remove(orig)
        except OSError:
            pass
        _save_state(job_id)
        return redirect(url_for("edit_segments_page", job_id=job_id) + "#cortes")
    corpo = request.get_json(silent=True) or {}
    v = job.setdefault("vinhetas", {}).setdefault(tipo, {})
    if "usar" in corpo:
        v["usar"] = bool(corpo["usar"])
    if corpo.get("voltar_ao_padrao"):
        v.pop("caminho", None)
        v.pop("video_id", None)
    if "video_id" in corpo:  # 📺 qual vídeo do perfil entra ("" = o ⭐ padrão do perfil)
        v.pop("caminho", None)
        if corpo["video_id"]:
            v["video_id"] = str(corpo["video_id"])[:20]
            v["usar"] = True
        else:
            v.pop("video_id", None)
    _save_state(job_id)
    return jsonify({"ok": True, "vinhetas": _vinhetas_editor(job)})


def _vinhetas_editor(job: dict) -> Dict[str, Any]:
    import canal
    return {t: {k: v[k] for k in ("usar", "nome", "proprio", "rotulo", "video_id", "opcoes")}
            | {"tem": bool(v["caminho"]), "padrao": any(o["padrao"] for o in v["opcoes"])}
            for t, v in canal.do_job(job).items()}


@app.route("/job/<job_id>/perfil-canal", methods=["POST"])
def job_perfil_canal(job_id: str):
    """📺 Troca o perfil do canal deste vídeo: as chamadas que estavam com o vídeo ⭐ padrão passam pro padrão do
    perfil novo; intro/final voltam pro padrão do perfil novo (o vídeo enviado só pra este vídeo continua)."""
    import chamadas as _chm
    import perfis_canal
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    pid = str((request.get_json(silent=True) or {}).get("perfil") or "")
    if not perfis_canal.existe(pid):
        return jsonify({"erro": "Perfil não encontrado."}), 404
    velho = perfis_canal.do_job(job)
    job["perfil_canal"] = pid
    trocadas = 0
    for c in job.get("cutaway_suggestions", []):
        if not c.get("chamada") or c.get("tipo") not in _chm.TIPOS or c.get("desligada"):
            continue
        do_velho = c.get("clipe_padrao") or (c.get("resolved_path") and any(
            v["arquivo"] == c.get("resolved_path") for v in perfis_canal.videos(c["tipo"], velho)))
        if do_velho or not c.get("resolved_path"):
            novo = _chm.clipe_padrao(c["tipo"], pid)
            if novo != c.get("resolved_path"):
                trocadas += 1
            c["resolved_path"] = novo
            c["clipe_padrao"] = bool(novo)
    for v in (job.get("vinhetas") or {}).values():
        v.pop("video_id", None)
    _save_state(job_id)
    return jsonify({"ok": True, "perfil": pid, "trocadas": trocadas})


@app.route("/vinhetas/<tipo>", methods=["POST"])
def vinheta_padrao(tipo: str):
    """⚙️ Configurações → 📺 Seu canal: abertura/encerramento padrão (entra em todo vídeo)."""
    import canal
    if tipo not in canal.VINHETAS:
        return "Tipo desconhecido.", 404
    if request.form.get("remover") == "on":
        canal.definir_padrao(tipo, None)
    else:
        up = request.files.get("arquivo")
        if not up or not up.filename:
            return "Nenhum arquivo enviado.", 400
        tmp = os.path.join(BASE_DIR, "chamadas_padrao")
        os.makedirs(tmp, exist_ok=True)
        orig = os.path.join(tmp, f"_up_{uuid.uuid4().hex[:6]}{os.path.splitext(secure_filename(up.filename))[1] or '.mp4'}")
        up.save(orig)
        try:
            canal.definir_padrao(tipo, orig)
        finally:
            try:
                os.remove(orig)
            except OSError:
                pass
    return redirect(url_for("settings_page") + "#canal")


@app.route("/vinhetas/<tipo>/arquivo")
def vinheta_arquivo(tipo: str):
    import canal
    cam = canal.clipe_padrao(tipo)
    if not cam:
        return "Sem vídeo.", 404
    return send_file(cam, conditional=True)


@app.route("/job/<job_id>/chamadas/escolher", methods=["POST"])
def chamadas_escolher(job_id: str):
    """Várias marcas [[VENDA]] / [[INSCREVA]]: a pessoa escolhe em QUAIS o clipe entra.
    As marcadas recebem o clipe do tipo (o já enviado neste projeto, senão o padrão);
    as desmarcadas ficam sem clipe (narração normal) e o padrão não volta pra elas."""
    import chamadas as _chm
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    tipo = str(corpo.get("tipo") or "")
    ligadas = {str(x) for x in corpo.get("ligadas") or []}
    do_tipo = [c for c in job.get("cutaway_suggestions", []) if c.get("chamada") and c.get("tipo") == tipo]
    if not do_tipo:
        return jsonify({"erro": "Nenhuma chamada desse tipo."}), 404
    if isinstance(corpo.get("escolhas"), dict):
        # qual vídeo em cada marca ("" = sem vídeo: a narração segue normal ali)
        clipes = {c["id"]: c for c in _clipes_do_tipo(job, tipo)}
        for c in do_tipo:
            cid = str(corpo["escolhas"].get(c["id"], "") or "")
            if cid and cid in clipes:
                c["resolved_path"] = clipes[cid]["caminho"]
                c["clipe_padrao"] = bool(clipes[cid].get("padrao"))
                c.pop("desligada", None)
            elif c["id"] in corpo["escolhas"]:
                c["resolved_path"] = None
                c["clipe_padrao"] = False
                c["desligada"] = True
        _save_state(job_id)
        return jsonify({"ok": True, "com_clipe": sum(1 for c in do_tipo if c.get("resolved_path")), "total": len(do_tipo)})
    clipe = next((c["resolved_path"] for c in do_tipo if c.get("resolved_path") and os.path.isfile(c["resolved_path"]) and not c.get("clipe_padrao")), None) \
        or next((c["resolved_path"] for c in do_tipo if c.get("resolved_path") and os.path.isfile(c["resolved_path"])), None) \
        or _chm.clipe_padrao(tipo, __import__("perfis_canal").do_job(job))
    if ligadas and not clipe:
        return jsonify({"erro": "Ainda não tem clipe desse tipo: envie o vídeo numa das chamadas primeiro."}), 400
    for c in do_tipo:
        if c["id"] in ligadas:
            if not c.get("resolved_path"):
                c["resolved_path"] = clipe
                c["clipe_padrao"] = clipe == _chm.clipe_padrao(tipo, __import__("perfis_canal").do_job(job))
            c.pop("desligada", None)
        else:
            c["resolved_path"] = None
            c["clipe_padrao"] = False
            c["desligada"] = True
    _save_state(job_id)
    return jsonify({"ok": True, "com_clipe": sum(1 for c in do_tipo if c.get("resolved_path")), "total": len(do_tipo)})


@app.route("/job/<job_id>/chamada/<cutaway_id>/tempo", methods=["POST"])
def chamada_tempo(job_id: str, cutaway_id: str):
    job = _JOBS.get(job_id)
    cut = next((c for c in (job or {}).get("cutaway_suggestions", []) if c["id"] == cutaway_id), None)
    if not cut:
        return jsonify({"erro": "Chamada não encontrada."}), 404
    corpo = request.get_json(silent=True) or {}
    try:
        ini = max(0.0, float(corpo.get("inicio")))
        fim = max(ini, float(corpo.get("fim"))) if cut.get("chamada") else None
    except (TypeError, ValueError):
        return jsonify({"erro": "Tempo inválido."}), 400
    cut["insertion_point"] = round(ini, 3)
    if fim is not None:
        cut["remove_ate"] = round(fim, 3)
    _save_state(job_id)
    return jsonify({"ok": True})


@app.route("/job/<job_id>/remove-cutaway/<cutaway_id>", methods=["POST"])
def remove_cutaway(job_id: str, cutaway_id: str):
    """Descarta uma sugestão de corte da IA (ou um upload já feito pra
    ela) — não é obrigatório usar toda sugestão que a IA fizer."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    job["cutaway_suggestions"] = [c for c in job.get("cutaway_suggestions", []) if c["id"] != cutaway_id]
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


# job de background pra baixar+cortar um trecho do YouTube pra um corte
# específico (ver /job/<id>/cutaway/<id>/youtube) -- yt_job_id (uuid
# curto) -> {"status": "processando"|"pronto"|"erro", "erro": str|None}.
# Separado de _JOBS de propósito: não é um job de vídeo inteiro, é só o
# download+corte de UM clipe, pode rodar vários ao mesmo tempo pra
# cortes diferentes do mesmo job de vídeo.
_CUTAWAY_YT_JOBS: Dict[str, Dict[str, Any]] = {}


@app.route("/job/<job_id>/cutaway/<cutaway_id>/youtube-buscar", methods=["GET"])
def cutaway_youtube_buscar(job_id: str, cutaway_id: str):
    """Mesma busca da ferramenta \"Cortar do YouTube\" (`buscar_videos_youtube`,
    sem chave de API) -- reaproveitada aqui pra achar um clipe pra um
    corte sugerido pela IA, sem sair da tela de edição."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    termo = (request.args.get("termo") or "").strip()
    if not termo:
        return jsonify({"erro": "Digite um termo de busca."}), 400
    try:
        pular = int(request.args.get("pular") or 0) if str(request.args.get("pular") or "0").isdigit() else 0
        resultados = (buscar_videos_youtube(termo, quantidade=12, pular=pular) if pular  # ➕ "Buscar outros vídeos"
                      else buscar_videos_youtube(termo, quantidade=15))
    except YoutubeClipperError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada na busca:\n{traceback.format_exc()}"}), 500
    return jsonify({"ok": True, "resultados": resultados})


@app.route("/job/<job_id>/cutaway/<cutaway_id>/youtube", methods=["POST"])
def cutaway_youtube_baixar(job_id: str, cutaway_id: str):
    """Baixa o vídeo do YouTube indicado e corta só o trecho [inicio,
    fim] pedido, em segundo plano (pode demorar dependendo do tamanho
    do vídeo) -- devolve um `yt_job_id` pra acompanhar em
    `cutaway_youtube_status`. Ao terminar com sucesso, já deixa o corte
    pronto (`cutaway["resolved_path"]`), exatamente como se a pessoa
    tivesse feito upload do arquivo manualmente."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    cutaway = next((c for c in job.get("cutaway_suggestions", []) if c["id"] == cutaway_id), None)
    if cutaway is None:
        return jsonify({"erro": "Esse corte não existe (talvez já tenha sido descartado)."}), 404

    corpo = request.get_json(silent=True) or {}
    url = (corpo.get("url") or "").strip()
    if not url:
        return jsonify({"erro": "URL do vídeo não informada."}), 400
    try:
        inicio = float(corpo.get("inicio", 0))
        fim = float(corpo.get("fim", 0))
    except (TypeError, ValueError):
        return jsonify({"erro": "Início/fim precisam ser números (segundos)."}), 400
    if fim <= inicio:
        return jsonify({"erro": f"Fim ({fim}) precisa vir depois do início ({inicio})."}), 400

    yt_job_id = uuid.uuid4().hex[:12]
    _CUTAWAY_YT_JOBS[yt_job_id] = {"status": "processando", "erro": None}

    def _run():
        status = _CUTAWAY_YT_JOBS[yt_job_id]
        cutaways_dir = os.path.join(_job_dir(job_id), "cutaway_uploads")
        os.makedirs(cutaways_dir, exist_ok=True)
        tmp_dir = os.path.join(cutaways_dir, f"_tmp_{yt_job_id}")
        try:
            baixado = yt_baixar_video(url, tmp_dir)
            output_path = os.path.join(cutaways_dir, f"{cutaway_id}_{yt_job_id}_youtube.mp4")
            yt_cortar_trecho(baixado["caminho"], inicio, fim, output_path)
            cutaway_atual = next(
                (c for c in _JOBS.get(job_id, {}).get("cutaway_suggestions", []) if c["id"] == cutaway_id), None,
            )
            if cutaway_atual is not None:
                cutaway_atual["resolved_path"] = output_path
                _save_state(job_id)
            status["status"] = "pronto"
        except YoutubeClipperError as exc:
            status["status"] = "erro"
            status["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            status["status"] = "erro"
            status["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    _thread_com_aviso(_run, lambda: _CUTAWAY_YT_JOBS.get(yt_job_id), f"✂️ Corte do YouTube em “{_nome_job(job_id)}”", f"/job/{job_id}/edit-segments", "youtube", chave_ok=f"yt:{job_id}")
    return jsonify({"ok": True, "yt_job_id": yt_job_id})


@app.route("/cutaway-youtube-status/<yt_job_id>", methods=["GET"])
def cutaway_youtube_status(yt_job_id: str):
    status = _CUTAWAY_YT_JOBS.get(yt_job_id)
    if not status:
        return jsonify({"erro": "Job não encontrado (talvez o servidor tenha reiniciado)."}), 404
    return jsonify(status)


# --------------------------------------------------------------------- #
# Painel "Vídeos do YouTube" do editor: tudo que a IA pediu do YouTube
# (trechos com provider "youtube" + cortes reais sugeridos) numa lista só,
# com os termos JÁ PESQUISADOS em segundo plano assim que a resposta da IA
# é colada. A pessoa só escolhe o vídeo mais promissor e a faixa de tempo
# (pode trocar o termo e pesquisar de novo); o site baixa e corta.
# --------------------------------------------------------------------- #

YOUTUBE_RESULTADOS_POR_TERMO = 8
YOUTUBE_RESULTADOS_COM_IA = 20


def _youtube_fala_do_item(job: dict, item: dict) -> str:
    """O que a narração diz no trecho do item (ou a descrição do corte)."""
    if item.get("tipo") == "segmento" and item.get("indice") is not None:
        segs = job.get("pending_segments") or []
        i = item["indice"]
        if 0 <= i < len(segs):
            try:
                falas, _p = _falas_por_trecho(job, [segs[i]])
                if falas and falas[0]:
                    return falas[0]
            except Exception:  # noqa: BLE001
                pass
            return " ".join(str(b.get("text") or "").strip() for b in job.get("segments") or []
                            if float(b.get("start", 0)) < float(segs[i]["end"]) and float(b.get("end", 0)) > float(segs[i]["start"]))
    return str(item.get("descricao") or item.get("termo") or "")


def _legenda_com_tempos(url: str, pasta: str, pode_visivel: bool = True) -> Dict[str, Any]:
    """Legenda de um vídeo do YouTube em linhas curtas com os tempos (pra achar o momento).
    youtube-transcript-api → painel "Mostrar transcrição" → a transcrição do Roteiro do YouTube."""
    import yt_alternativas as alt
    erros = []
    try:
        r = alt.legenda_transcript_api(url, ["pt", "en", "es"])
        if r and r.get("linhas"):
            return {"linhas": r["linhas"], "fonte": "youtube-transcript-api"}
    except Exception as exc:  # noqa: BLE001
        erros.append(str(exc)[:120])
    # navegador VISÍVEL só no botão 🎯 (um vídeo); o 🤖 que lê vários vídeos nunca abre janela
    for headless in ((True, False) if pode_visivel else (True,)):
        try:
            r = alt.legenda_painel(url, headless=headless)
            if r and r.get("linhas"):
                return {"linhas": r["linhas"], "fonte": "painel de transcrição", "titulo": r.get("titulo"), "canal": r.get("canal")}
            if r and r.get("tem_legenda") is False:
                break
        except Exception as exc:  # noqa: BLE001
            erros.append(str(exc)[:120])
    try:
        import roteiros_yt
        tr = roteiros_yt.extrair_transcricao(url, pasta, usar_whisper=False, painel_primeiro=False)
        linhas = [{"inicio": b["inicio"], "fim": b.get("fim", b["inicio"]), "texto": b["texto"]} for b in tr.get("blocos") or []]
        if linhas:
            return {"linhas": linhas, "fonte": tr.get("fonte") or "legenda", "titulo": tr.get("titulo"), "canal": tr.get("canal")}
    except Exception as exc:  # noqa: BLE001
        erros.append(str(exc)[:160])
    return {"linhas": [], "erro": "; ".join(erros) or "o vídeo não tem legenda"}
_YOUTUBE_BUSCAS_RODANDO: set = set()
_YOUTUBE_BUSCAS_LOCK = threading.Lock()


def _youtube_itens_sincronizar(job: dict) -> List[Dict[str, Any]]:
    """(Re)monta `job["youtube_itens"]` a partir dos trechos com provider
    "youtube" e dos cortes reais sugeridos — preservando o que já existia
    (termo editado, resultados, escolha) e descartando o que não se aplica
    mais (trecho que deixou de ser youtube, corte descartado)."""
    antigos = {it["id"]: it for it in job.get("youtube_itens") or []}
    novos: List[Dict[str, Any]] = []

    for i, seg in enumerate(job.get("pending_segments") or []):
        if (seg.get("provider") or "").lower() != "youtube" or (seg.get("media_type") or "video") != "video":
            continue
        item_id = f"seg-{i}"
        dur = max(0.1, float(seg.get("end", 0)) - float(seg.get("start", 0)))
        item = antigos.get(item_id)
        if item is None or item.get("termo_original") != seg.get("query"):
            item = {
                "id": item_id, "tipo": "segmento", "indice": i, "cutaway_id": None,
                "termo": seg.get("query") or "", "termo_original": seg.get("query") or "",
                "status": "pendente", "resultados": [], "erro": None, "escolha": None,
            }
        item.update(
            indice=i, descricao=f"Trecho {i + 1} ({float(seg['start']):.1f}s – {float(seg['end']):.1f}s)",
            duracao_alvo=round(dur, 2),
        )
        novos.append(item)

    for cut in job.get("cutaway_suggestions") or []:
        if cut.get("chamada") or cut.get("do_projeto"):  # clipe seu (chamada / vídeo do projeto), não vem do YouTube
            continue
        if not _youtube_marcado(job):  # 🎬 sem a fonte youtube: o corte real fica só pra você enviar o clipe
            continue
        item_id = f"cut-{cut['id']}"
        termo = (cut.get("query") or cut.get("description") or "").strip()
        item = antigos.get(item_id) or {
            "id": item_id, "tipo": "corte", "indice": None, "cutaway_id": cut["id"],
            "termo": termo, "termo_original": termo,
            "status": "pendente", "resultados": [], "erro": None, "escolha": None,
        }
        item.update(
            descricao=f"Corte real em {float(cut['insertion_point']):.1f}s — {cut.get('description', '')}",
            duracao_alvo=None,
        )
        if cut.get("resolved_path") and not item.get("escolha"):
            item["escolha"] = {"titulo": "arquivo enviado", "url": None}
        novos.append(item)

    job["youtube_itens"] = novos
    return novos


def _youtube_buscar_pendentes(job_id: str) -> None:
    """Pesquisa em segundo plano todo item com status "pendente" (sem
    navegador: `buscar_videos_youtube` usa o yt-dlp). Uma thread por job
    no máximo — se já tem uma rodando, ela pega os novos pendentes."""
    with _YOUTUBE_BUSCAS_LOCK:
        if job_id in _YOUTUBE_BUSCAS_RODANDO:
            return
        _YOUTUBE_BUSCAS_RODANDO.add(job_id)

    def _run():
        try:
            while True:
                job = _JOBS.get(job_id)
                if not job:
                    return
                pendente = next((it for it in job.get("youtube_itens") or [] if it.get("status") == "pendente"), None)
                if pendente is None:
                    return
                pendente["status"] = "buscando"
                termo = (pendente.get("termo") or "").strip()
                try:
                    if not termo:
                        raise YoutubeClipperError("Termo de busca vazio — digite um termo e clique em Buscar.")
                    import ia_servico
                    com_ia = ia_servico.ativo("youtube_ordem")
                    # 🤖 com a IA: 20 de uma vez (uma consulta só), ordenados pela nota; o painel mostra 8 + "Outros vídeos"
                    resultados = buscar_videos_youtube(termo, quantidade=YOUTUBE_RESULTADOS_COM_IA if com_ia else YOUTUBE_RESULTADOS_POR_TERMO)
                    if pendente.get("termo", "").strip() != termo:
                        continue  # termo mudou durante a busca: o item já voltou a "pendente"
                    pendente["ia_ordenado"] = False
                    if com_ia and resultados:
                        try:
                            import ia_midia
                            o = ia_midia.ordenar_youtube(resultados, _youtube_fala_do_item(job, pendente), termo,
                                                         (job.get("ia") or {}).get("ficha"), job=job_id)
                        except Exception:  # noqa: BLE001
                            o = None
                        if o:
                            resultados = o["resultados"]
                            pendente["ia_ordenado"] = True
                            pendente["ia_busca_melhor"] = o.get("busca_melhor") or ""
                    pendente["resultados"] = resultados
                    pendente["erro"] = None if resultados else "Nenhum vídeo encontrado — tente outro termo."
                    pendente["status"] = "pronto"
                except YoutubeClipperError as exc:
                    pendente["resultados"] = []
                    pendente["erro"] = str(exc)
                    pendente["status"] = "erro"
                except Exception as exc:  # noqa: BLE001
                    pendente["resultados"] = []
                    pendente["erro"] = f"Falha inesperada na busca: {exc}"
                    pendente["status"] = "erro"
                _save_state(job_id)
        finally:
            with _YOUTUBE_BUSCAS_LOCK:
                _YOUTUBE_BUSCAS_RODANDO.discard(job_id)
            # corrida: um item pode ter virado "pendente" depois do último
            # `next(...)` e antes de sair do conjunto acima — confere de novo.
            job = _JOBS.get(job_id)
            if job and any(it.get("status") == "pendente" for it in job.get("youtube_itens") or []):
                _youtube_buscar_pendentes(job_id)

    threading.Thread(target=_run, daemon=True).start()


def _youtube_item(job: dict, item_id: str) -> Optional[Dict[str, Any]]:
    return next((it for it in job.get("youtube_itens") or [] if it["id"] == item_id), None)


@app.route("/job/<job_id>/youtube/itens", methods=["GET"])
def youtube_itens(job_id: str):
    """Lista do painel (e dispara a busca dos itens que ainda não foram
    pesquisados). O editor chama isso ao abrir e fica consultando até
    nenhum item estar "pendente"/"buscando"."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    itens = _youtube_itens_sincronizar(job)
    with _YOUTUBE_BUSCAS_LOCK:
        rodando = job_id in _YOUTUBE_BUSCAS_RODANDO
    if not rodando:
        # "buscando" sem thread nenhuma = sobrou de antes do servidor reiniciar
        for it in itens:
            if it.get("status") == "buscando":
                it["status"] = "pendente"
    if any(it.get("status") == "pendente" for it in itens):
        _youtube_buscar_pendentes(job_id)
    ia_geral = job.get("youtube_ia") or {}
    if ia_geral.get("rodando") and not any(t.name == "yt-ia-" + job_id for t in threading.enumerate()) \
            and time.time() - float(ia_geral.get("inicio") or time.time()) > 30:
        ia_geral["rodando"] = False  # sobrou de antes do servidor reiniciar
    return jsonify({
        "ok": True, "itens": itens, "ia": ia_geral,
        "buscando": any(it.get("status") in ("pendente", "buscando") for it in itens) or bool(ia_geral.get("rodando")),
    })


@app.route("/job/<job_id>/youtube/item/<item_id>/buscar", methods=["POST"])
def youtube_item_buscar(job_id: str, item_id: str):
    """Troca o termo de um item e pesquisa de novo (em segundo plano)."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    _youtube_itens_sincronizar(job)
    item = _youtube_item(job, item_id)
    if item is None:
        return jsonify({"erro": "Esse item não existe mais (o trecho mudou ou o corte foi descartado)."}), 404
    termo = ((request.get_json(silent=True) or {}).get("termo") or "").strip()
    if not termo:
        return jsonify({"erro": "Digite um termo de busca."}), 400
    item.update(termo=termo, status="pendente", resultados=[], erro=None)
    _save_state(job_id)
    _youtube_buscar_pendentes(job_id)
    return jsonify({"ok": True})


@app.route("/job/<job_id>/youtube/item/<item_id>/momento", methods=["POST"])
def youtube_item_momento(job_id: str, item_id: str):
    """🤖 Acha, pela legenda do vídeo escolhido, o momento que fala o que a narração pede
    (início e fim já preenchidos; você confere e clica em Usar)."""
    import ia_servico
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    motivo = ia_servico.motivo_desligado("youtube_momento")
    if motivo:
        return jsonify({"erro": "IA: " + motivo}), 400
    item = _youtube_item(job, item_id)
    if item is None:
        return jsonify({"erro": "Esse item não existe mais."}), 404
    corpo = request.get_json(silent=True) or {}
    url = (corpo.get("url") or "").strip()
    if not url:
        return jsonify({"erro": "Escolha um vídeo primeiro."}), 400
    leg = _youtube_legenda(job_id, job, url)
    if not leg.get("linhas"):
        return jsonify({"erro": "Não consegui a legenda desse vídeo (" + str(leg.get("erro") or "sem legenda") + ") — marque o trecho à mão."}), 200
    import ia_midia
    r = ia_midia.achar_momento(leg["linhas"], _youtube_fala_do_item(job, item), str(corpo.get("titulo") or leg.get("titulo") or ""),
                               str(corpo.get("canal") or leg.get("canal") or ""), item.get("duracao_alvo"),
                               (job.get("ia") or {}).get("ficha"), job=job_id)
    if r is None:
        return jsonify({"erro": "A IA não respondeu agora (" + (ia_servico.motivo_desligado("youtube_momento") or "tente de novo") + ")."}), 200
    _save_state(job_id)
    return jsonify({"ok": True, **r, "fonte_legenda": leg.get("fonte")})


@app.route("/job/<job_id>/youtube/item/<item_id>/usar", methods=["POST"])
def youtube_item_usar(job_id: str, item_id: str):
    """Baixa o vídeo escolhido e corta só [inicio, fim] em segundo plano.
    Ao terminar: num TRECHO, vira o arquivo do trecho (igual a um upload
    manual); num CORTE real, vira o clipe do corte. Acompanhe em
    `/cutaway-youtube-status/<yt_job_id>`."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    _youtube_itens_sincronizar(job)
    item = _youtube_item(job, item_id)
    if item is None:
        return jsonify({"erro": "Esse item não existe mais (o trecho mudou ou o corte foi descartado)."}), 404

    corpo = request.get_json(silent=True) or {}
    url = (corpo.get("url") or "").strip()
    if not url:
        return jsonify({"erro": "Escolha um vídeo primeiro."}), 400
    try:
        inicio = float(corpo.get("inicio", 0))
        fim = float(corpo.get("fim", 0))
    except (TypeError, ValueError):
        return jsonify({"erro": "Início/fim precisam ser números (segundos)."}), 400
    if inicio < 0:
        return jsonify({"erro": "O início não pode ser negativo."}), 400
    if fim <= inicio:
        return jsonify({"erro": f"Fim ({fim}) precisa vir depois do início ({inicio})."}), 400

    escolha = {
        "url": url, "inicio": inicio, "fim": fim,
        "titulo": str(corpo.get("titulo") or "")[:200],
        "miniatura_url": str(corpo.get("miniatura_url") or ""),
    }
    yt_job_id = uuid.uuid4().hex[:12]
    _CUTAWAY_YT_JOBS[yt_job_id] = {"status": "processando", "erro": None}

    def _run():
        status = _CUTAWAY_YT_JOBS[yt_job_id]
        try:
            _youtube_baixar_e_aplicar(job_id, item_id, escolha, yt_job_id)
            status["status"] = "pronto"
        except YoutubeClipperError as exc:
            status["status"] = "erro"
            status["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            status["status"] = "erro"
            status["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"

    _thread_com_aviso(_run, lambda: _CUTAWAY_YT_JOBS.get(yt_job_id), f"✂️ Clipe do YouTube em “{_nome_job(job_id)}”", f"/job/{job_id}/edit-segments", "youtube", chave_ok=f"yt:{job_id}")
    return jsonify({"ok": True, "yt_job_id": yt_job_id})


def _youtube_baixar_e_aplicar(job_id: str, item_id: str, escolha: Dict[str, Any], tag: str = "") -> str:
    """Baixa o vídeo da escolha, corta [inicio, fim] e põe no trecho (arquivo do trecho) ou no corte real
    (clipe do corte). Levanta YoutubeClipperError se não der. → caminho do clipe."""
    url, inicio, fim = escolha["url"], float(escolha["inicio"]), float(escolha["fim"])
    tag = tag or uuid.uuid4().hex[:12]
    destino_dir = os.path.join(_job_dir(job_id), "youtube_clipes")
    os.makedirs(destino_dir, exist_ok=True)
    tmp_dir = os.path.join(destino_dir, f"_tmp_{tag}")
    try:
        baixado = yt_baixar_video(url, tmp_dir)
        output_path = os.path.join(destino_dir, f"{item_id}_{tag}.mp4")
        yt_cortar_trecho(baixado["caminho"], inicio, fim, output_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    job_atual = _JOBS.get(job_id) or {}
    item_atual = _youtube_item(job_atual, item_id)
    if item_atual is not None and item_atual["tipo"] == "segmento":
        idx = item_atual["indice"]
        segs = job_atual.get("pending_segments") or []
        if 0 <= idx < len(segs):
            segs[idx]["override_source"] = {"source": "local_file", "value": output_path, "kind": "video"}
            segs[idx]["media_type"] = "video"
            _limpar_erro_do_trecho(job_atual, idx)
            previews = list(job_atual.get("segment_previews") or [])
            if idx < len(previews):
                previews[idx] = {
                    "index": idx, "ok": True, "thumbnail_url": escolha.get("miniatura_url") or None,
                    "result_url": url, "label": f"YouTube: {escolha.get('titulo') or ''}", "error": None,
                    "video_preview_url": None, "provider": "youtube", "original_provider": "youtube",
                }
                job_atual["segment_previews"] = previews
    elif item_atual is not None and item_atual["tipo"] == "corte":
        cut = next((c for c in job_atual.get("cutaway_suggestions", []) if c["id"] == item_atual["cutaway_id"]), None)
        if cut is not None:
            cut["resolved_path"] = output_path
    if item_atual is not None:
        item_atual["escolha"] = dict(escolha, arquivo=output_path)
    if job_atual:
        _save_state(job_id)
    return output_path


def _youtube_legenda(job_id: str, job: dict, url: str, pode_visivel: bool = True) -> Dict[str, Any]:
    """Legenda com tempos de um vídeo (guardada no job: as últimas 12)."""
    cache = job.setdefault("ia_legendas", {})
    leg = cache.get(url)
    if not leg or not leg.get("linhas"):
        leg = _legenda_com_tempos(url, os.path.join(_job_dir(job_id), "youtube_legendas"), pode_visivel=pode_visivel)
        if leg.get("linhas"):
            cache[url] = leg
            while len(cache) > 12:
                cache.pop(next(iter(cache)))
    return leg


# ------------------------------------------------------------------ 🤖 a IA acha os vídeos do YouTube (v84_69)
_YOUTUBE_IA_PARAR: set = set()


def _youtube_ia_item(job_id: str, item_id: str, modo: str = "") -> None:
    """Roda o agente (yt_agente.procurar) num item e, se achou, baixa e corta o momento."""
    import ia_midia
    import yt_agente
    job = _JOBS.get(job_id) or {}
    item = _youtube_item(job, item_id)
    if item is None:
        return
    st = {"estado": "procurando", "log": [], "inicio": time.time()}
    item["ia"] = st
    ficha = (job.get("ia") or {}).get("ficha")
    fala = _youtube_fala_do_item(job, item)

    def log(m: str) -> None:
        st["log"] = (st["log"] + [m])[-40:]

    def ordenar(resultados, termo, vistos):
        return ia_midia.ordenar_youtube(resultados, fala, termo, ficha, job=job_id, com_capas=12, ja_vistos=vistos)

    import yt_google

    def _guardar(v, m, tipo, erro=""):  # 🧾 cada resposta da IA fica no histórico do clipe (v84_90)
        item["ia_respostas"] = yt_google.guardar_resposta(item.get("ia_respostas"), yt_google.resposta(v, m, tipo=tipo, erro=erro))

    def achar(linhas, v):
        m = ia_midia.achar_momento(linhas, fala, str(v.get("titulo") or ""), str(v.get("canal") or ""),
                                   item.get("duracao_alvo"), ficha, job=job_id)
        _guardar(v, m, "legenda")
        return m

    def _com_historico(fn):
        def assistir_v(v):
            try:
                m = fn(v)
            except Exception as exc:  # noqa: BLE001
                _guardar(v, None, "google", str(exc)[:160])
                raise
            _guardar(v, m, "google")
            return m
        return assistir_v

    assistir, assistir_sempre = None, False
    try:  # 🔎 IA do Google: "assiste" o vídeo (sem legenda / a legenda não achou — ou sempre)
        import ia_google_rotas as _igr
        if _igr.instalado() and (_igr.modo_youtube() != "desligado" or modo == "google"):
            assistir = lambda v: _igr.momento(v["url"], fala, item.get("duracao_alvo"))  # noqa: E731
            assistir_sempre = _igr.modo_youtube() == "sempre"
    except Exception:  # noqa: BLE001
        assistir = None
    if assistir is not None:
        assistir = _com_historico(assistir)
    if modo == "google":
        st["log"] = ["🤖🔎 Claude busca e escolhe os vídeos · a IA do Google assiste e acha o momento"]
    if modo == "perguntar":  # 🔎 pergunta pra IA do Google ONDE achar (ela indica link + tempo e depois assiste pra confirmar)
        st["log"] = ["🔎 perguntando pra IA do Google onde achar essa cena no YouTube…"]

        def _resp(resp):
            item["ia_respostas"] = yt_google.guardar_resposta(item.get("ia_respostas"), resp)
        try:
            p = yt_google.perguntar_onde(fala, item.get("duracao_alvo"), log=log, ao_responder=_resp,
                                         parar=lambda: job_id in _YOUTUBE_IA_PARAR)
        except Exception as exc:  # noqa: BLE001
            p = {"achou": False, "motivo": str(exc)[:200]}
        r = {"achou": bool(p.get("achou")), "motivo": p.get("motivo") or "não achei", "buscas": [], "conferidos": [],
             "inicio": p.get("inicio"), "fim": p.get("fim"), "frase": p.get("frase") or "", "confianca": 0.7,
             "video": {"url": p.get("url"), "titulo": p.get("titulo") or "", "miniatura_url": p.get("miniatura_url") or ""}}
    else:
        r = None
    r = r or yt_agente.procurar(
        fala, item.get("termo") or item.get("termo_original") or "", item.get("duracao_alvo"),
        assistir=assistir, assistir_sempre=assistir_sempre, so_google=modo == "google",
        buscar=lambda t: buscar_videos_youtube(t, quantidade=YOUTUBE_RESULTADOS_COM_IA),
        ordenar=ordenar, legenda=lambda u: _youtube_legenda(job_id, job, u, pode_visivel=False), achar=achar,
        nova_busca=lambda feitas, motivos: ia_midia.nova_busca_youtube(fala, feitas, motivos, ficha, job=job_id),
        log=log, parar=lambda: job_id in _YOUTUBE_IA_PARAR)
    st["buscas"], st["conferidos"] = r.get("buscas") or [], r.get("conferidos") or []
    if not r["achou"]:
        st.update(estado="nao_achou", msg=r["motivo"])
        if r.get("resultados"):  # deixa os da última busca pra escolher à mão
            item.update(termo=r.get("termo_resultados") or r["buscas"][-1], resultados=r["resultados"], status="pronto", erro=None, ia_ordenado=True)
        _save_state(job_id)
        return
    v = r["video"]
    alvo = item.get("duracao_alvo")
    ini, fim = float(r["inicio"]), float(r["fim"])
    if alvo and fim - ini < alvo:  # o trecho do vídeo é maior que a fala achada: completa depois dela
        fim = ini + float(alvo)
        if v.get("duracao_segundos"):
            fim = min(fim, float(v["duracao_segundos"]))
    escolha = {"url": v["url"], "inicio": round(ini, 2), "fim": round(fim, 2), "titulo": str(v.get("titulo") or "")[:200],
               "miniatura_url": str(v.get("miniatura_url") or ""), "ia": True, "frase": r.get("frase") or "",
               "confianca": r.get("confianca")}
    st.update(estado="baixando", msg=f"achei em “{escolha['titulo'][:60]}” ({ini:.1f}s) — baixando e cortando…")
    try:
        _youtube_baixar_e_aplicar(job_id, item_id, escolha)
        st.update(estado="pronto", msg=f"✅ “{escolha['titulo'][:60]}” {ini:.1f}s → {fim:.1f}s: “{escolha['frase'][:90]}”")
    except Exception as exc:  # noqa: BLE001
        st.update(estado="erro", msg=f"achei o momento mas o download falhou ({str(exc)[:120]}) — tente Usar à mão",
                  achado=escolha)
    _save_state(job_id)


def _youtube_ia_rodar(job_id: str, ids: List[str], modo: str = "") -> None:
    job = _JOBS.get(job_id) or {}
    geral = {"rodando": True, "total": len(ids), "feitos": 0, "achados": 0, "atual": None, "inicio": time.time()}
    job["youtube_ia"] = geral
    for item_id in ids:
        if job_id in _YOUTUBE_IA_PARAR:
            break
        geral["atual"] = item_id
        try:
            _youtube_ia_item(job_id, item_id, modo)
        except Exception as exc:  # noqa: BLE001
            it = _youtube_item(job, item_id)
            if it is not None:
                it["ia"] = {"estado": "erro", "msg": f"falha inesperada: {str(exc)[:160]}", "log": []}
        it = _youtube_item(job, item_id)
        geral["feitos"] += 1
        geral["achados"] += 1 if it is not None and (it.get("ia") or {}).get("estado") == "pronto" else 0
    for it in job.get("youtube_itens") or []:  # parou no meio: o que ficou na fila volta ao normal
        if (it.get("ia") or {}).get("estado") == "na_fila":
            it.pop("ia", None)
    geral.update(rodando=False, atual=None, parado=job_id in _YOUTUBE_IA_PARAR)
    _YOUTUBE_IA_PARAR.discard(job_id)
    _save_state(job_id)
    _avisar(f"✅ 🤖 Agente do YouTube em “{_nome_job(job_id)}” — achou {geral['achados']} de {geral['feitos']}",
            "Parado por você." if geral.get("parado") else "", f"/job/{job_id}/edit-segments",
            "ok" if geral["achados"] else "aviso", "youtube_ia")


@app.route("/job/<job_id>/youtube/ia", methods=["POST"])
def youtube_ia(job_id: str):
    """🤖 A IA acha os vídeos: os itens pedidos (ou todos os que estão sem vídeo), um depois do outro."""
    import ia_servico
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    modo = corpo.get("modo") if corpo.get("modo") in ("google", "perguntar") else ""
    if modo:  # 🤖🔎 alternativa (v84_88): Claude busca/escolhe, a IA do Google assiste e acha o momento
        import yt_google
        motivo = yt_google.disponivel()
        if motivo:
            return jsonify({"erro": "🔎 IA do Google: " + motivo}), 400
    else:
        for rec in ("youtube_ordem", "youtube_momento"):
            motivo = ia_servico.motivo_desligado(rec)
            if motivo:
                return jsonify({"erro": "IA: " + motivo + " — ligue em 🤖 IA (“Ordenar os vídeos do YouTube” e “Achar o momento”)."}), 400
    if (job.get("youtube_ia") or {}).get("rodando"):
        return jsonify({"erro": "A IA já está procurando — espere ou clique em Parar."}), 409
    itens = _youtube_itens_sincronizar(job)
    pedidos = corpo.get("itens")
    if pedidos:
        ids = [it["id"] for it in itens if it["id"] in set(pedidos)]
    else:
        ids = [it["id"] for it in itens if not it.get("escolha") or (it["escolha"] or {}).get("automatico")]
    if not ids:
        return jsonify({"erro": "Nenhum vídeo do YouTube sem escolha."}), 400
    for it in itens:
        if it["id"] in ids:
            it["ia"] = {"estado": "na_fila", "log": []}
    job["youtube_ia"] = {"rodando": True, "total": len(ids), "feitos": 0, "achados": 0, "atual": None}
    _YOUTUBE_IA_PARAR.discard(job_id)  # um "Parar" antigo não vale pra esta rodada
    _save_state(job_id)
    threading.Thread(target=_youtube_ia_rodar, args=(job_id, ids, modo), name="yt-ia-" + job_id, daemon=True).start()
    return jsonify({"ok": True, "total": len(ids)})


def _youtube_olhar_de_novo(job_id: str, item_id: str, errados: List[Dict[str, Any]]) -> None:
    """🔁 A IA do Google errou o momento desse item: pede de novo na mesma conversa (sem os momentos errados)."""
    import yt_google
    job = _JOBS.get(job_id) or {}
    geral = job.get("youtube_ia") or {}
    item = _youtube_item(job, item_id)
    try:
        if item is None:
            return
        esc0 = dict(item.get("escolha") or {})
        fala = _youtube_fala_do_item(job, item)
        st = {"estado": "procurando", "log": [f"🔁 pedindo pra IA do Google olhar de novo “{str(esc0.get('titulo') or esc0.get('url'))[:60]}” "
                                             f"(sem {len(errados)} momento(s) errado(s))…"], "inicio": time.time()}
        item["ia"] = st
        try:
            m = yt_google.momento_no_link(esc0["url"], fala, item.get("duracao_alvo"), evitar=errados)
        except Exception as exc:  # noqa: BLE001
            m = None
            st["log"].append(str(exc)[:200])
        item["google_errados"] = errados
        item["ia_respostas"] = yt_google.guardar_resposta(item.get("ia_respostas"), yt_google.resposta(esc0, m, tipo="olhar de novo"))
        if not (m and m.get("achou")):
            st.update(estado="nao_achou", msg="olhou de novo e não achou outro momento nesse vídeo — tente 🤖🔎 Claude + Google (outros vídeos) ou escolha à mão")
            return
        ini, fim = float(m["inicio"]), float(m["fim"])
        alvo = item.get("duracao_alvo")
        if alvo and fim - ini < alvo:
            fim = ini + float(alvo)
        escolha = dict(esc0, inicio=round(ini, 2), fim=round(fim, 2), ia=True, frase=str(m.get("frase") or ""), automatico=False)
        escolha.pop("arquivo", None)
        st.update(estado="baixando", msg=f"novo momento {ini:.1f}s → {fim:.1f}s — baixando e cortando…")
        try:
            _youtube_baixar_e_aplicar(job_id, item_id, escolha)
            item["google_errados"] = errados
            st.update(estado="pronto", msg=f"🔁✅ olhou de novo: {ini:.1f}s → {fim:.1f}s “{escolha['frase'][:90]}”")
            geral["achados"] = 1
        except Exception as exc:  # noqa: BLE001
            st.update(estado="erro", msg=f"achei outro momento mas o download falhou ({str(exc)[:120]})", achado=escolha)
    finally:
        geral.update(rodando=False, atual=None, feitos=1)
        _save_state(job_id)


@app.route("/job/<job_id>/youtube/item/<item_id>/mais", methods=["POST"])
def youtube_item_mais(job_id: str, item_id: str):
    """➕ Buscar outros vídeos: os próximos 12 resultados da mesma busca (sem repetir os que já estão)."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    item = _youtube_item(job, item_id)
    if item is None:
        return jsonify({"erro": "Esse item não existe mais."}), 404
    termo = str(item.get("termo") or "").strip()
    if not termo:
        return jsonify({"erro": "Sem termo de busca."}), 400
    atuais = list(item.get("resultados") or [])
    try:
        novos = buscar_videos_youtube(termo, quantidade=12, pular=len(atuais))
    except YoutubeClipperError as exc:
        return jsonify({"erro": str(exc)}), 400
    vistos = {v.get("url") for v in atuais}
    novos = [v for v in novos if v.get("url") not in vistos]
    item["resultados"] = atuais + novos
    _save_state(job_id)
    return jsonify({"ok": True, "novos": len(novos), "total": len(item["resultados"])})


@app.route("/job/<job_id>/youtube/item/<item_id>/momento-google", methods=["POST"])
def youtube_item_momento_google(job_id: str, item_id: str):
    """🔎 A IA do Google assiste o vídeo ESCOLHIDO (um que já está na lista) e acha o momento — em segundo plano."""
    import tarefas_bg
    import yt_google
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    item = _youtube_item(job, item_id)
    if item is None:
        return jsonify({"erro": "Esse item não existe mais."}), 404
    corpo = request.get_json(silent=True) or {}
    url = str(corpo.get("url") or "").strip()
    if not yt_google._RE_LINK_YT.search(url):
        return jsonify({"erro": "Escolha um vídeo primeiro."}), 400
    motivo = yt_google.disponivel()
    if motivo:
        return jsonify({"erro": "🔎 IA do Google: " + motivo}), 400
    video = {"url": url, "titulo": str(corpo.get("titulo") or "")[:160], "miniatura_url": str(corpo.get("miniatura_url") or "")}
    fala = _youtube_fala_do_item(job, item)

    def _tarefa(t):
        t.progresso("🔎 a IA do Google está assistindo o vídeo…")
        m = yt_google.momento_no_link(url, fala, item.get("duracao_alvo"))
        item["ia_respostas"] = yt_google.guardar_resposta(item.get("ia_respostas"), yt_google.resposta(video, m, tipo="google"))
        _save_state(job_id)
        return {"achou": bool(m and m.get("achou")), **({"inicio": m["inicio"], "fim": m["fim"], "frase": m.get("frase") or ""} if m and m.get("achou") else {})}
    tid = tarefas_bg.iniciar("achar_google", f"🔎 Momento no vídeo (“{_nome_job(job_id)}”)", _tarefa, pagina=f"/job/{job_id}/edit-segments")
    return jsonify({"ok": True, "tarefa": tid})


@app.route("/job/<job_id>/youtube/item/<item_id>/olhar-de-novo", methods=["POST"])
def youtube_olhar_de_novo(job_id: str, item_id: str):
    """🔁 O momento que a IA do Google deu está errado: ela olha o MESMO vídeo de novo, na mesma conversa, sabendo que
    esse(s) momento(s) não tinham o que buscamos (e com o que buscamos reafirmado)."""
    import yt_google
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    item = _youtube_item(job, item_id)
    esc0 = (item or {}).get("escolha") or {}
    if not esc0.get("url"):
        return jsonify({"erro": "Esse item ainda não tem vídeo escolhido."}), 400
    motivo = yt_google.disponivel()
    if motivo:
        return jsonify({"erro": "🔎 IA do Google: " + motivo}), 400
    if (job.get("youtube_ia") or {}).get("rodando"):
        return jsonify({"erro": "A IA já está procurando — espere ou clique em Parar."}), 409
    anteriores = item.get("google_errados") or []
    if anteriores and item.get("google_errados_url") != esc0["url"]:
        anteriores = []  # trocou de vídeo
    errados = [e for e in anteriores if isinstance(e, dict)] + [{"inicio": float(esc0.get("inicio") or 0),
                                                                 "fim": float(esc0.get("fim") or float(esc0.get("inicio") or 0) + 5)}]
    item["google_errados_url"] = esc0["url"]
    job["youtube_ia"] = {"rodando": True, "total": 1, "feitos": 0, "achados": 0, "atual": item_id, "inicio": time.time()}
    item["ia"] = {"estado": "na_fila", "log": []}
    threading.Thread(target=_youtube_olhar_de_novo, args=(job_id, item_id, errados), name="yt-ia-" + job_id, daemon=True).start()
    return jsonify({"ok": True, "errados": errados})


@app.route("/job/<job_id>/youtube/ia/parar", methods=["POST"])
def youtube_ia_parar(job_id: str):
    if not _JOBS.get(job_id):
        return jsonify({"erro": "Job não encontrado."}), 404
    _YOUTUBE_IA_PARAR.add(job_id)
    return jsonify({"ok": True})


@app.route("/job/<job_id>/edicao/prompt", methods=["POST"])
def edicao_prompt(job_id: str):
    """Prompt de edição (2ª etapa) com o estado ATUAL do Estúdio."""
    import prompt_edicao
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    estado = request.get_json(silent=True) or {}
    if not estado.get("blocos"):
        estado["blocos"] = [{"start": float(b["start"]), "end": float(b["end"]), "text": b.get("text", "")} for b in job.get("segments") or [] if b.get("text")]
    if estado.get("segmentos"):
        falas, _p = _falas_por_trecho(job, estado["segmentos"])
        for sg, f in zip(estado["segmentos"], falas):
            sg["_fala"] = f
    try:
        if estado.get("partes_min"):  # ✂️ opcional: vídeo longo em partes (ex.: 12 min cada), um prompt por parte
            segs = estado.get("segmentos") or job.get("pending_segments") or []
            total = float(job.get("total_duration") or (segs[-1]["end"] if segs else 0))
            # 🎨 a direção de arte vem da resposta da PARTE 1 e entra nos prompts das outras (o vídeo tem uma cara só)
            arte, erro_arte = "", None
            if str(estado.get("resposta_parte1") or "").strip():
                try:
                    p1 = prompt_edicao.ler_resposta(str(estado["resposta_parte1"]), len(segs), total, _palavras_da_narracao(job))
                    arte = prompt_edicao.arte_da_parte1(p1)
                except ValueError as exc:
                    erro_arte = f"Não li a resposta da parte 1: {exc}"
            partes = []
            for pt in prompt_edicao.dividir_partes(segs, total, float(estado["partes_min"])):
                txt = prompt_edicao.montar_prompt(job, dict(estado, parte=pt, arte=arte))
                partes.append(dict(pt, prompt=txt, caracteres=len(txt)))
            return jsonify({"ok": True, "partes": partes, "prompt": partes[0]["prompt"], "caracteres": sum(x["caracteres"] for x in partes),
                            "arte": arte, "erro_arte": erro_arte})
        texto = prompt_edicao.montar_prompt(job, estado)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui montar o prompt: {exc}"}), 400
    return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto)})


@app.route("/job/<job_id>/edicao/ia", methods=["POST"])
def edicao_ia(job_id: str):
    """🤖 Manda o prompt de edição (ou UMA parte dele) direto pra IA configurada em /ia e devolve a resposta."""
    import ia_servico
    if not _JOBS.get(job_id):
        return jsonify({"erro": "Job não encontrado."}), 404
    motivo = ia_servico.motivo_desligado("edicao")
    if motivo:
        return jsonify({"erro": "IA: " + motivo}), 400
    corpo = request.get_json(silent=True) or {}
    prompt = str(corpo.get("prompt") or "")
    if not prompt.strip():
        return jsonify({"erro": "Gere o prompt primeiro."}), 400

    def _chamar() -> Optional[str]:
        return ia_servico.chamar("edicao", "Você é editor de vídeo. Siga o pedido do usuário e responda SÓ com o JSON pedido, sem texto antes ou depois.",
                                 prompt, schema=None, max_tokens=20000, effort="medium", job=job_id, timeout=300)
    if corpo.get("bg"):  # ⏳ v84_87: em segundo plano — a resposta fica guardada (🕘 Histórico) mesmo fechando o Estúdio
        import tarefas_bg

        def _tarefa(t):
            texto_bg = _chamar()
            if not texto_bg:
                raise RuntimeError("A IA não respondeu (" + (ia_servico.motivo_desligado("edicao") or "veja os detalhes em 🤖 IA") + ").")
            return {"texto": texto_bg}
        parte = str(corpo.get("parte") or "")[:20]
        tid = tarefas_bg.iniciar("ia_edicao", f"🪄 Edição pela IA de “{_nome_job(job_id)}”" + (f" (parte {parte})" if parte else ""),
                                 _tarefa, pagina=f"/job/{job_id}/edit-segments", alvo={"parte": parte})
        return jsonify({"ok": True, "tarefa": tid})
    texto = _chamar()
    if not texto:
        return jsonify({"erro": "A IA não respondeu (" + (ia_servico.motivo_desligado("edicao") or "veja os detalhes em 🤖 IA") + ") — copie o prompt e use outra IA."}), 200
    return jsonify({"ok": True, "texto": texto})


@app.route("/job/<job_id>/edicao/conversa", methods=["POST"])
def edicao_conversa(job_id: str):
    """💬 Conversa com a IA no Estúdio: pedido + o que está selecionado → plano pequeno (só o que muda) + resposta."""
    import conversa_edicao
    import ia_servico
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    motivo = ia_servico.motivo_desligado("edicao")
    if motivo:
        return jsonify({"erro": "IA desligada: " + motivo, "ia_desligada": True}), 400
    corpo = request.get_json(silent=True) or {}
    pedido = " ".join(str(corpo.get("pedido") or "").split())[:2000]
    if not pedido:
        return jsonify({"erro": "Escreva o que você quer mudar."}), 400
    estado = corpo.get("estado") if isinstance(corpo.get("estado"), dict) else {}
    if not estado.get("blocos"):
        estado["blocos"] = [{"start": float(b["start"]), "end": float(b["end"]), "text": b.get("text", "")} for b in job.get("segments") or [] if b.get("text")]
    if estado.get("segmentos"):
        falas, _p = _falas_por_trecho(job, estado["segmentos"])
        for sg, f in zip(estado["segmentos"], falas):
            sg["_fala"] = f
    foco = corpo.get("foco") if isinstance(corpo.get("foco"), dict) else {}
    historico = corpo.get("historico") if isinstance(corpo.get("historico"), list) else []
    try:
        prompt = conversa_edicao.montar_prompt(job, estado, pedido, foco, historico)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Não consegui montar o pedido: {exc}"}), 400
    texto = ia_servico.chamar("edicao", conversa_edicao.sistema(), prompt, max_tokens=4000, effort="low", job=job_id,
                              cache_local=False, timeout=120)
    if not texto:
        return jsonify({"erro": "A IA não respondeu (" + (ia_servico.motivo_desligado("edicao") or "veja os detalhes em 🤖 IA") + ")."}), 502
    try:
        plano = conversa_edicao.ler(texto, job, estado, _palavras_da_narracao(job))
    except ValueError as exc:
        return jsonify({"erro": f"A IA respondeu fora do formato: {exc}"}), 502
    for d in (plano.get("destaques") or []) + (plano.get("editoriais") or []):
        d["id"] = uuid.uuid4().hex[:8]
    return jsonify({"ok": True, **plano})


@app.route("/job/<job_id>/edicao/resposta", methods=["POST"])
def edicao_resposta(job_id: str):
    """Lê o JSON que a IA devolveu e devolve o plano validado (o Estúdio aplica)."""
    import prompt_edicao
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    n = int(corpo.get("n_trechos") or len(job.get("pending_segments") or []))
    textos = [str(t) for t in corpo.get("textos") or [] if str(t or "").strip()]  # ✂️ uma resposta por parte
    # 🎬 v84_172: só vale o que a direção escolhida tem (o que a IA trouxer de fora sai, com aviso)
    _dir = prompt_edicao.direcao_escolhida(job, corpo.get("direcao"), corpo.get("kit")) if corpo.get("so_direcao", True) is not False else None
    _bib = {it["id"]: it["media_type"] for it in job.get("media_library") or []
            if it.get("media_type") in ("image", "video") and os.path.exists(it.get("path") or "")}
    try:
        if textos:
            planos = []
            for k, t in enumerate(textos, start=1):
                try:
                    planos.append(prompt_edicao.ler_resposta(t, n, float(job.get("total_duration") or 0), _palavras_da_narracao(job), corpo.get("foto"),
                                                             biblioteca=_bib, direcao=_dir))
                except ValueError as exc:
                    raise ValueError(f"Parte {k}: {exc}") from exc
            plano = prompt_edicao.juntar_planos(planos)
        else:
            plano = prompt_edicao.ler_resposta(str(corpo.get("texto") or ""), n, float(job.get("total_duration") or 0),
                                               _palavras_da_narracao(job), corpo.get("foto"), biblioteca=_bib, direcao=_dir)
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    for d in (plano.get("destaques") or []) + (plano.get("editoriais") or []):
        d["id"] = uuid.uuid4().hex[:8]
    _gerar_coberturas(job_id, job, plano)
    return jsonify({"ok": True, **plano})


def _gerar_coberturas(job_id: str, job: dict, plano: dict) -> None:
    """⬛ v84_111: trecho SEM CENA que a IA cobriu ("cobrir": {"fundo", "cor"}) → gera o fundo (uma FOTO na pasta
    coberturas/ do projeto) e devolve no plano o caminho; o Estúdio põe ela no trecho (com desfazer)."""
    import cenas_dp
    trechos = [t for t in plano.get("trechos") or [] if t.get("cobrir")]
    if not trechos:
        return
    W, H = {"9:16": (1080, 1920), "1:1": (1080, 1080)}.get(_orientacao_do_job(job), (1920, 1080))
    pasta = os.path.join(_job_dir(job_id), "coberturas")
    os.makedirs(pasta, exist_ok=True)
    pal = (job.get("paleta") or {}) if isinstance(job.get("paleta"), dict) else {}
    for t in trechos:
        fundo, cor = t["cobrir"]["fundo"], t["cobrir"].get("cor") or pal.get("primaria")
        try:
            if fundo in cenas_dp._FUNDOS_DESENHO:
                caminho = cenas_dp._fundo_desenhado(fundo, W, H, pasta, cor or "#7C8AA5")
            else:
                caminho = cenas_dp.gerar_fundo(fundo, W, H, pasta, tom=cor)
            t["cobertura"] = {"value": caminho, "fundo": fundo}
        except Exception as exc:  # noqa: BLE001
            plano.setdefault("avisos", []).append(f"T{t['indice'] + 1}: não gerei o fundo '{fundo}' ({exc}).")


def _trechos_para_revisao(job: dict, segmentos: list) -> list:
    """Trechos do Estúdio (estado atual, pode estar sem salvar) + a fala de
    cada um. Sem palavras com tempo (SRT sem Whisper), usa os blocos da fala
    que encostam no trecho."""
    trechos = []
    for sg in segmentos or []:
        if not isinstance(sg, dict):
            continue
        try:
            ini, fim = float(sg.get("start", 0)), float(sg.get("end", 0))
        except (TypeError, ValueError):
            continue
        trechos.append({
            "start": ini, "end": fim, "provider": str(sg.get("provider") or ""), "query": str(sg.get("query") or ""),
            "media_type": sg.get("media_type") or "video", "override_source": sg.get("override_source") or None,
            "alternativas": [str(a) for a in (sg.get("alternativas") or []) if a][:3], "visual": sg.get("visual"),
        })
    try:
        falas, _p = _falas_por_trecho(job, trechos)
    except Exception:  # noqa: BLE001
        falas = [""] * len(trechos)
    blocos = [b for b in job.get("segments") or [] if b.get("text")]
    for t, fala in zip(trechos, falas):
        if not fala:
            fala = " ".join(str(b["text"]).strip() for b in blocos
                            if float(b["start"]) < t["end"] and float(b["end"]) > t["start"])
        t["fala"] = fala
    return trechos


@app.route("/job/<job_id>/buscas/prompt", methods=["POST"])
def buscas_prompt(job_id: str):
    """🧠 Revisar buscas com IA: prompt focado SÓ nas buscas (fala de cada
    trecho + busca atual), com o estado atual do Estúdio."""
    from prompt_builder import build_revisao_buscas_prompt
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    trechos = _trechos_para_revisao(job, corpo.get("segmentos") or job.get("pending_segments") or [])
    try:
        texto = build_revisao_buscas_prompt(
            trechos, language_hint=_hint_idioma(job.get("language")),
            formato=_orientacao_do_job(job), objetivo=str(corpo.get("objetivo") or "")[:600],
        )
    except PromptBuilderError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, "prompt": texto, "caracteres": len(texto),
                    "revisaveis": sum(1 for t in trechos if __import__("prompt_builder").trecho_revisavel(t))})


@app.route("/job/<job_id>/buscas/resposta", methods=["POST"])
def buscas_resposta(job_id: str):
    """Lê o JSON da revisão de buscas; o Estúdio mostra antes → depois e aplica."""
    from prompt_builder import ler_revisao_buscas
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    trechos = _trechos_para_revisao(job, corpo.get("segmentos") or job.get("pending_segments") or [])
    try:
        plano = ler_revisao_buscas(str(corpo.get("texto") or ""), trechos)
    except PromptBuilderError as exc:
        return jsonify({"erro": str(exc)}), 400
    return jsonify({"ok": True, **plano})


# ------------------------------------------------------------------ 🎬 revisão do diretor (v84_92)
def _miniatura_para_revisao(job_id: str, job: dict, i: int, thumb: str) -> str:
    """Miniatura que a revisão olha: link remoto, ou o arquivo por trás das rotas locais da prévia."""
    thumb = str(thumb or "")
    if thumb.startswith(("http://", "https://")):
        return thumb
    previas = job.get("segment_previews") or []
    pv = previas[i] if i < len(previas) else None
    if thumb.startswith(f"/job/{job_id}/thumbnail/") and pv and pv.get("thumbnail_path") and os.path.isfile(pv["thumbnail_path"]):
        return pv["thumbnail_path"]
    if pv:
        if pv.get("thumbnail_path") and os.path.isfile(pv["thumbnail_path"]):
            return pv["thumbnail_path"]
        if str(pv.get("thumbnail_url") or "").startswith(("http://", "https://")):
            return pv["thumbnail_url"]
    return ""


def _revisar_diretor(job_id: str, job: dict, segmentos: list, previas: list, progresso=lambda _m: None) -> Dict[str, Any]:
    import dp_graficos
    import estilo_imagem
    import ia_servico
    import revisao_diretor as rd
    falas, _p = _falas_por_trecho(job, segmentos)
    blocos = [b for b in job.get("segments") or [] if b.get("text")]
    for k, sg in enumerate(segmentos):  # SRT sem palavras: a fala pelos blocos que encostam
        if not falas[k]:
            falas[k] = " ".join(str(b["text"]).strip() for b in blocos if float(b["start"]) < float(sg.get("end") or 0)
                                and float(b["end"]) > float(sg.get("start") or 0))
    cfg = _job_site_cfg(job)
    orient = _orientacao_do_job(job)
    trechos = rd.montar_trechos(segmentos, falas, previas,
                                lambda i, s, pv: _miniatura_para_revisao(job_id, job, i, pv.get("thumb") or pv.get("thumbnail_url") or ""))
    progresso("🎬 conferindo as miniaturas (formato, desenho, repetidas)…")
    rd.problemas_automaticos(trechos, orient, estilo_imagem.modo_real(cfg))
    disp = rd.disponiveis(job.get("providers") or [])
    decisoes: Dict[int, Dict[str, Any]] = {}
    com_ia = ia_servico.ativo("revisao")
    if com_ia:
        decisoes = rd.revisar_ia(trechos, (job.get("ia") or {}).get("ficha"), disp, orient, list(dp_graficos.TIPOS),
                                 job=job_id, progresso=progresso)
    return rd.plano(trechos, decisoes, disp, job.get("total_duration"), com_ia=bool(com_ia and decisoes))


@app.route("/job/<job_id>/revisao-diretor", methods=["POST"])
def revisao_diretor_rota(job_id: str):
    """🎬 Revisão do diretor: {segmentos: estado do Estúdio, previas: [{thumb, label, erro, ia_nota, result_url}]}.
    Roda em segundo plano (pode fechar o Estúdio — o resultado volta sozinho e chega um aviso no 🔔)."""
    import tarefas_bg
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    segmentos = [s for s in corpo.get("segmentos") or job.get("pending_segments") or [] if isinstance(s, dict)]
    previas = corpo.get("previas") if isinstance(corpo.get("previas"), list) else (job.get("segment_previews") or [])
    previas = [p if isinstance(p, dict) else {} for p in previas]
    if not segmentos:
        return jsonify({"erro": "Sem trechos."}), 400
    tid = tarefas_bg.iniciar("revisao_diretor", f"🎬 Revisão do diretor — {_nome_job(job_id)}",
                             lambda t: _revisar_diretor(job_id, job, segmentos, previas, t.progresso),
                             pagina=f"/job/{job_id}/edit-segments")
    return jsonify({"ok": True, "tarefa": tid})


@app.route("/job/<job_id>/revisao/fundo/<int:indice>", methods=["POST"])
def revisao_fundo(job_id: str, indice: int):
    """🎬 Aplica no servidor o fundo de um trecho que virou 🃏 cartão ({"tipo": "cartao", "frase"}) ou 📊 gráfico
    ({"tipo": "grafico"} — só o fundo; o gráfico o Estúdio põe na faixa dele). Devolve o que o Estúdio copia."""
    job = _JOBS.get(job_id)
    if not job or not (0 <= indice < len(job.get("pending_segments") or [])):
        return jsonify({"erro": "Trecho não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    tipo = "grafico" if corpo.get("tipo") == "grafico" else "cartao"
    pend = job["pending_segments"][indice]
    sg = VideoSegment(start=float(pend["start"]), end=float(pend["end"]), provider=str(pend.get("provider") or "pexels"),
                      query=str(pend.get("query") or ""))
    frase = " ".join(str(corpo.get("frase") or "").split()[:12]) if tipo == "cartao" else ""
    sg._frase_tela = frase
    previa = _cartao_no_trecho(job_id, job, indice, sg, frase, "🎬 revisão do diretor" + (": gráfico" if tipo == "grafico" else ""))
    if tipo == "grafico":  # sem a frase por cima: o gráfico é o destaque
        job["destaques"] = [d for d in job.get("destaques") or [] if not (d.get("origem") == "cartao" and d.get("trecho") == indice)]
        previa["label"] = "📊 fundo do gráfico (revisão do diretor)"
    previas = list(job.get("segment_previews") or [])
    while len(previas) < len(job["pending_segments"]):
        previas.append(None)
    previas[indice] = previa
    job["segment_previews"] = previas
    _save_state(job_id)
    pend = job["pending_segments"][indice]
    destaque = next((d for d in job.get("destaques") or [] if d.get("origem") == "cartao" and d.get("trecho") == indice), None)
    return jsonify({"ok": True, "override_source": pend.get("override_source"), "media_type": "image", "preview": previa,
                    "destaque": destaque})


@app.route("/job/<job_id>/buscas/previa/<int:indice>", methods=["POST"])
def buscas_previa(job_id: str, indice: int):
    """Prévia nova de UM trecho depois que a busca dele mudou (revisão com IA):
    busca a principal e, sem resultado, as reservas — mesma ordem da montagem —
    e guarda em `segment_previews`, pra miniatura continuar certa depois de
    recarregar. Com {"definir": prévia} só grava (o ↩ Desfazer usa)."""
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    if not (0 <= indice < len(job["pending_segments"])):
        return jsonify({"erro": "Trecho inexistente."}), 404
    corpo = request.get_json(silent=True) or {}
    seg = job["pending_segments"][indice]
    if isinstance(corpo.get("definir"), dict):
        d = corpo["definir"]
        previa = {"index": indice, "ok": bool(d.get("ok")), "thumbnail_url": d.get("thumbnail_url"), "result_url": d.get("result_url") or None,
                  "label": str(d.get("label") or ""), "error": d.get("error"), "video_preview_url": d.get("video_preview_url"),
                  "provider": d.get("provider") or seg.get("provider"), "original_provider": seg.get("provider")}
        if d.get("query") is not None:  # prévia devolvida pelo "desfazer": continua fixável na montagem
            previa.update(query=str(d["query"]), media_type=str(d.get("media_type") or seg.get("media_type") or "video"))
    else:
        query = str(corpo.get("query") or seg.get("query") or "").strip()
        provider = str(corpo.get("provider") or seg.get("provider") or "").strip().lower()
        media_type = str(corpo.get("media_type") or seg.get("media_type") or "video").strip().lower()
        if not query or not provider:
            return jsonify({"erro": "Faltou a busca ou o banco."}), 400
        tentativas = [query] + [str(a).strip() for a in (corpo.get("alternativas") or []) if str(a).strip()][:3]
        previa, erro, reserva = None, None, None
        _cfg_p = _job_site_cfg(job)
        import estilo_imagem as _ei
        # 🎞️🖼️ (v84_92) pede alguns e pula desenho/3D/recorte e mídia no formato errado (acervos de anime e Flow: não)
        _filtra = _ei.filtro_ativo(_cfg_p) and provider not in _BIBLIOTECAS_LOCAIS and provider not in ("flow", "runpod", "produto", "material")
        for q in tentativas:
            try:
                cands = search_candidates(provider, q, media_type=media_type, max_results=6 if _filtra else 1, site_cfg=_cfg_p,
                                          obra=(corpo.get("obra") or seg.get("obra") or None),
                                          personagem=(corpo.get("personagem") or seg.get("personagem") or None))
            except VideoAssemblyError as exc:
                erro = str(exc)
                continue
            if cands and _filtra:
                cands = _ei.ordenar_candidatos(cands, _cfg_p)
            if cands:
                c = cands[0]
                problema = "desenho/3D/recorte" if c.get("estilo_problema") else ("formato errado" if c.get("formato_errado") else "")
                p_ = {"index": indice, "ok": True, "thumbnail_url": c.get("thumbnail") or c.get("image_url"),
                      "result_url": c.get("url"), "label": ("⚠ " if problema else "") + (f"(reserva “{q}”) " if q != query else "") + str(c.get("label") or ""),
                      "error": None, "video_preview_url": c.get("video_preview_url"),
                      "provider": provider, "original_provider": provider,
                      "query": query, "media_type": media_type}
                if problema:  # só achou isso nessa busca: guarda e tenta a próxima
                    p_["problema"] = problema
                    reserva = reserva or p_
                    continue
                previa = p_
                break
        if previa is None and reserva is not None:
            previa = reserva  # nada melhor: fica com ⚠ (a 🎬 revisão marca como "procurar na mão")
        if previa is None:
            previa = {"index": indice, "ok": False, "thumbnail_url": None, "result_url": None, "label": "",
                      "error": erro or f"Nenhum resultado em {provider} pra “{query}” nem nas reservas — a montagem tenta os outros bancos.",
                      "video_preview_url": None, "provider": provider, "original_provider": provider}
    previews = list(job.get("segment_previews") or [])
    while len(previews) < len(job["pending_segments"]):
        previews.append(None)
    previews[indice] = previa
    job["segment_previews"] = previews
    _save_state(job_id)
    return jsonify({"ok": True, "preview": previa})


def _imagens_da_biblioteca(job: dict) -> Dict[str, str]:
    """"bib:<id>" -> caminho, pros quadros editoriais (prints, fotos do mural, recortes…)."""
    return {"bib:" + it["id"]: it["path"] for it in job.get("media_library") or [] if it.get("path") and os.path.exists(it["path"])}


@app.route("/editorial/exemplo/<tipo>")
def editorial_exemplo(tipo: str):
    import dp_editorial
    if tipo not in dp_editorial.TIPOS:
        return jsonify({"erro": "Tipo desconhecido."}), 404
    return jsonify(dp_editorial.exemplo(tipo))


@app.route("/editorial/sons", methods=["POST"])
def editorial_sons():
    """Os sons dos quadros (para tocar junto na prévia do Estúdio)."""
    import dp_editorial
    itens = [q for q in (dp_editorial.normalizar(x) for x in ((request.get_json(silent=True) or {}).get("itens") or [])[:200]) if q]
    return jsonify({"eventos": dp_editorial.eventos_sonoros(itens)})


@app.route("/job/<job_id>/editorial/previa", methods=["POST"])
def editorial_previa(job_id: str):
    """Um quadro do quadro editorial (o MESMO desenho do vídeo final) pra telinha do Estúdio."""
    import dp_editorial
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    it = dp_editorial.normalizar(dict(corpo.get("item") or {}, _idioma_video=__import__("idiomas").normalizar(job.get("language")) or ""))
    if not it:
        return jsonify({"erro": "Quadro inválido."}), 400
    orient = corpo.get("orientacao") if corpo.get("orientacao") in ("16:9", "9:16", "1:1") else _orientacao_do_job(job)
    W, H = {"16:9": (960, 540), "9:16": (540, 960), "1:1": (720, 720)}[orient]
    try:
        t = max(0.0, float(corpo.get("t") or 0))
    except (TypeError, ValueError):
        t = 0.0
    pasta = os.path.join(_job_dir(job_id), "editorial_previa")
    imagens = _imagens_da_biblioteca(job)
    prints = {}
    if it["tipo"] == "pagina" and it.get("url") and not it.get("imagem"):
        p = dp_editorial.capturar_print(it["url"], os.path.join(_job_dir(job_id), "editorial_prints"))
        if p:
            prints[it["url"]] = p
    chave = hashlib.md5(json.dumps([it, W, H, round(t, 2), sorted(imagens.items()), prints], sort_keys=True, default=str).encode()).hexdigest()[:14]
    destino = os.path.join(pasta, chave + ".png")
    if not os.path.exists(destino):
        os.makedirs(pasta, exist_ok=True)
        dp_editorial.previa_png(it, t, W, H, destino, dp_editorial.ctx_da_previa(it, W, H, imagens, prints, pasta))
    return send_file(destino, mimetype="image/png", max_age=3600)


@app.route("/job/<job_id>/grafico/previa", methods=["POST"])
def grafico_previa(job_id: str):
    """PNG transparente do gráfico pronto (último quadro da entrada) pra prévia do Estúdio."""
    import dp_graficos
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    g = dp_graficos.normalizar(corpo.get("grafico") or {})
    if not g:
        return jsonify({"erro": "Gráfico sem dados suficientes (precisa de pelo menos 2 valores; número/porcentagem: 1)."}), 400
    W, H = 960, 540
    _ori = corpo.get("orientacao") if corpo.get("orientacao") in ("16:9", "9:16", "1:1") else _orientacao_do_job(job)
    if _ori == "9:16":
        W, H = 540, 960
    elif _ori == "1:1":
        W, H = 720, 720
    cor = str(corpo.get("primaria") or "#FFD60A")
    destino = os.path.join(_job_dir(job_id), "graficos_previa", hashlib.md5(json.dumps([g, W, H, cor], sort_keys=True).encode()).hexdigest()[:12] + ".png")
    if not os.path.exists(destino):
        dp_graficos.previa_png(g, W, H, destino, cor if re.fullmatch(r"#[0-9a-fA-F]{6}", cor) else "#FFD60A")
    return send_file(destino, mimetype="image/png", max_age=3600)


@app.route("/job/<job_id>/youtube/texto", methods=["POST"])
def youtube_texto(job_id: str):
    """Links do YouTube com o tempo colados como texto (uma linha por trecho).
    `aplicar=false` só mostra como ficou a leitura; `aplicar=true` baixa
    (cada vídeo uma vez só), corta e põe em cada trecho em segundo plano —
    acompanhe em `/cutaway-youtube-status/<yt_job_id>`."""
    import yt_texto
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    segs = job.get("pending_segments") or []
    duracoes = [float(s["end"]) - float(s["start"]) for s in segs]
    alvos = corpo.get("alvos")
    alvos = [int(i) for i in alvos] if isinstance(alvos, list) and alvos else None
    linhas = yt_texto.distribuir(str(corpo.get("texto") or ""), duracoes, alvos)
    validas = [l for l in linhas if not l.get("erro")]
    if not corpo.get("aplicar"):
        return jsonify({"ok": True, "linhas": linhas})
    if not validas:
        return jsonify({"erro": "Nenhuma linha válida pra aplicar.", "linhas": linhas}), 400
    yt_job_id = uuid.uuid4().hex[:12]
    estado = {"status": "processando", "erro": None,
              "itens": [{"indice": l["indice"], "status": "na fila", "erro": None, "miniatura_url": l["miniatura_url"]} for l in validas]}
    _CUTAWAY_YT_JOBS[yt_job_id] = estado

    def _run():
        destino_dir = os.path.join(_job_dir(job_id), "youtube_clipes")
        os.makedirs(destino_dir, exist_ok=True)
        baixados: Dict[str, str] = {}
        tmp_dirs = []
        try:
            for l, it in zip(validas, estado["itens"]):
                try:
                    if l["url"] not in baixados:
                        # cache por vídeo: copiar/colar o mesmo link em outro trecho não baixa de novo
                        cache = os.path.join(destino_dir, "_cache", re.sub(r"[^\w-]", "_", l["id"]))
                        pronto = next((os.path.join(cache, f) for f in (os.listdir(cache) if os.path.isdir(cache) else [])
                                       if f.lower().endswith((".mp4", ".mkv", ".webm", ".mov"))), None)
                        if pronto:
                            baixados[l["url"]] = pronto
                        else:
                            it["status"] = "baixando"
                            tmp = os.path.join(destino_dir, f"_tmp_txt_{yt_job_id}_{len(tmp_dirs)}")
                            tmp_dirs.append(tmp)
                            _qual_yt = "melhor" if (_JOBS.get(job_id) or {}).get("export_quality") in ("1440p", "2160p") else "1080p"
                            orig = yt_baixar_video(l["url"], tmp, _qual_yt)["caminho"]
                            os.makedirs(cache, exist_ok=True)
                            destino_cache = os.path.join(cache, "video" + os.path.splitext(orig)[1])
                            shutil.move(orig, destino_cache)
                            baixados[l["url"]] = destino_cache
                    it["status"] = "cortando"
                    saida = os.path.join(destino_dir, f"seg-{l['indice']}_txt_{yt_job_id}.mp4")
                    yt_cortar_trecho(baixados[l["url"]], l["inicio"], l["fim"], saida)
                    job_atual = _JOBS.get(job_id) or {}
                    pend = job_atual.get("pending_segments") or []
                    idx = l["indice"]
                    if 0 <= idx < len(pend):
                        pend[idx]["override_source"] = {"source": "local_file", "value": saida, "kind": "video"}
                        pend[idx]["media_type"] = "video"
                        pend[idx]["youtube_link"] = {"url": l["url"], "inicio": l["inicio"], "fim": l["fim"]}
                        _limpar_erro_do_trecho(job_atual, idx)
                        previews = list(job_atual.get("segment_previews") or [])
                        if idx < len(previews):
                            previews[idx] = {"index": idx, "ok": True, "thumbnail_url": l["miniatura_url"], "result_url": l["url"],
                                             "label": f"YouTube {l['inicio']:g}–{l['fim']:g}s", "error": None, "video_preview_url": None,
                                             "provider": "youtube", "original_provider": pend[idx].get("provider")}
                            job_atual["segment_previews"] = previews
                        _save_state(job_id)
                    it["status"] = "pronto"
                except YoutubeClipperError as exc:
                    it["status"], it["erro"] = "erro", str(exc)
                except Exception as exc:  # noqa: BLE001
                    it["status"], it["erro"] = "erro", f"Falha inesperada: {exc}"
        finally:
            for t in tmp_dirs:
                shutil.rmtree(t, ignore_errors=True)
            erros = [it for it in estado["itens"] if it["status"] == "erro"]
            estado["status"] = "erro" if len(erros) == len(estado["itens"]) else "pronto"
            if erros:
                estado["erro"] = f"{len(erros)} de {len(estado['itens'])} falharam: " + "; ".join(f"trecho {e['indice'] + 1}: {e['erro']}" for e in erros)[:600]

    _thread_com_aviso(_run, lambda: estado, f"✂️ Links do YouTube em “{_nome_job(job_id)}”", f"/job/{job_id}/edit-segments", "youtube")
    return jsonify({"ok": True, "yt_job_id": yt_job_id, "linhas": linhas})


@app.route("/job/<job_id>/youtube/auto", methods=["POST"])
def youtube_auto(job_id: str):
    """Liga/desliga a escolha automática (1º resultado, do começo, com a
    duração do trecho) pros trechos do YouTube que ficarem sem escolha."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    job["youtube_auto"] = bool((request.get_json(silent=True) or {}).get("ativo", True))
    _save_state(job_id)
    return jsonify({"ok": True, "ativo": job["youtube_auto"]})


def _youtube_escolher_automatico(job_id: str, job: dict, segments: List[VideoSegment], log=lambda _m: None) -> int:
    """Antes de montar: cada trecho "youtube" ainda sem vídeo escolhido usa
    o 1º resultado da busca (se falhar o download, o 2º, o 3º), do segundo
    0 até a duração do trecho. Devolve quantos trechos foram resolvidos.
    Desligado pela caixa do painel (`job["youtube_auto"] = False`)."""
    if not job.get("youtube_auto", True):
        return 0
    _youtube_itens_sincronizar(job)
    resolvidos = 0
    for idx, seg in enumerate(segments):
        if seg.provider != "youtube" or seg.override_source or getattr(seg, "media_type", "video") != "video":
            continue
        item = _youtube_item(job, f"seg-{idx}")
        resultados = (item or {}).get("resultados") or []
        if not resultados and item is not None and (item.get("termo") or "").strip():
            try:  # a busca ainda não tinha rodado/terminado: faz agora
                resultados = buscar_videos_youtube(item["termo"], quantidade=YOUTUBE_RESULTADOS_POR_TERMO)
            except Exception:  # noqa: BLE001
                resultados = []
        for video in resultados[:3]:
            destino_dir = os.path.join(_job_dir(job_id), "youtube_clipes")
            os.makedirs(destino_dir, exist_ok=True)
            tmp_dir = os.path.join(destino_dir, f"_tmp_auto_{idx}")
            fim = round(seg.duration, 2)
            if video.get("duracao_segundos"):
                fim = min(fim, float(video["duracao_segundos"]))
            try:
                log(f"YouTube automático: trecho {idx + 1} <- {video.get('titulo')}")
                baixado = yt_baixar_video(video["url"], tmp_dir)
                saida = os.path.join(destino_dir, f"seg-{idx}_auto.mp4")
                yt_cortar_trecho(baixado["caminho"], 0.0, max(0.5, fim), saida)
            except Exception:  # noqa: BLE001
                continue
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            override = {"source": "local_file", "value": saida, "kind": "video"}
            seg.override_source = override
            pend = job.get("pending_segments") or []
            if idx < len(pend):
                pend[idx]["override_source"] = dict(override)
            if item is not None:
                item["escolha"] = {
                    "url": video["url"], "inicio": 0.0, "fim": fim, "titulo": video.get("titulo") or "",
                    "miniatura_url": video.get("miniatura_url") or "", "arquivo": saida, "automatico": True,
                }
            resolvidos += 1
            break
    if resolvidos:
        _save_state(job_id)
    return resolvidos


@app.route("/job/<job_id>/youtube/item/<item_id>/limpar", methods=["POST"])
def youtube_item_limpar(job_id: str, item_id: str):
    """Desfaz a escolha de um item: o trecho volta à busca automática
    (bancos normais) / o corte volta a ficar sem clipe."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    _youtube_itens_sincronizar(job)
    item = _youtube_item(job, item_id)
    if item is None:
        return jsonify({"erro": "Esse item não existe mais."}), 404
    escolha = item.get("escolha") or {}
    if item["tipo"] == "segmento":
        seg = (job.get("pending_segments") or [])[item["indice"]]
        if (seg.get("override_source") or {}).get("value") == escolha.get("arquivo"):
            seg["override_source"] = None
    else:
        cut = next((c for c in job.get("cutaway_suggestions", []) if c["id"] == item["cutaway_id"]), None)
        if cut is not None:
            cut["resolved_path"] = None
    item["escolha"] = None
    _save_state(job_id)
    return jsonify({"ok": True})


_MEDIA_LIBRARY_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".heic", ".heif", ".tif", ".tiff", ".jfif")


@app.route("/job/<job_id>/upload-to-library", methods=["POST"])
def upload_to_library(job_id: str):
    """Envia um arquivo pra BIBLIOTECA DE MÍDIA do job — uma área
    própria, sempre disponível no editor, pra guardar arquivos que
    você pode arrastar depois pra qualquer lugar que aceita upload
    (um trecho, um overlay de imagem/vídeo, ou um corte real), sem
    precisar reenviar o mesmo arquivo em cada lugar separadamente.

    Só GUARDA o arquivo aqui — não atribui ele a nada sozinho; a
    atribuição de verdade acontece nas rotas específicas de cada
    destino (arrastando o cartão na interface, que dispara a chamada
    certa: confirmar segmento com override_source, add-overlay, ou
    upload-cutaway).
    """
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    uploaded = request.files.get("library_file")
    if not uploaded or not uploaded.filename:
        return "Nenhum arquivo enviado.", 400

    library_dir = os.path.join(_job_dir(job_id), "media_library")
    os.makedirs(library_dir, exist_ok=True)
    safe_name = secure_filename(uploaded.filename)
    item_id = uuid.uuid4().hex[:8]
    dest = os.path.join(library_dir, f"{item_id}_{safe_name}")
    uploaded.save(dest)

    ext = os.path.splitext(safe_name)[1].lower()
    media_type = "image" if ext in _MEDIA_LIBRARY_IMAGE_EXTENSIONS else "video"

    item = {
        "id": item_id, "filename": safe_name, "path": dest, "media_type": media_type,
    }
    job.setdefault("media_library", []).append(item)
    _save_state(job_id)
    if request.args.get("json") == "1":
        return jsonify({"ok": True, "item": {k: item[k] for k in ("id", "filename", "media_type")}})
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/remove-from-library/<item_id>", methods=["POST"])
def remove_from_library(job_id: str, item_id: str):
    """Remove um arquivo da biblioteca de mídia — não desfaz nenhuma
    atribuição já feita com ele (um trecho/overlay/corte que já usou
    esse arquivo continua funcionando, só o arquivo some da lista pra
    arrastar de novo)."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    job["media_library"] = [item for item in job.get("media_library", []) if item["id"] != item_id]
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/library-item/<item_id>/descricao", methods=["POST"])
def library_item_descricao(job_id: str, item_id: str):
    """📝 O que é essa mídia ("print do site X", "foto do fulano") — a IA da edição usa pra pôr no trecho certo."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    item = next((i for i in job.get("media_library") or [] if i["id"] == item_id), None)
    if item is None:
        return jsonify({"erro": "Arquivo não encontrado na biblioteca."}), 404
    item["descricao"] = " ".join(str((request.get_json(silent=True) or {}).get("descricao") or "").split())[:200]
    _save_state(job_id)
    return jsonify({"ok": True, "descricao": item["descricao"]})


@app.route("/job/<job_id>/links-tela", methods=["POST"])
def links_tela(job_id: str):
    """🖥 Links que o vídeo pode mostrar na tela (a IA da edição põe o print da página quando a fala cita)."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    bruto = (request.get_json(silent=True) or {}).get("links") or ""
    linhas = bruto.splitlines() if isinstance(bruto, str) else [str(x) for x in bruto]
    job["links_tela"] = [u.strip() for u in linhas if re.match(r"^https?://\S+$", u.strip())][:40]
    _save_state(job_id)
    return jsonify({"ok": True, "links": job["links_tela"]})


@app.route("/job/<job_id>/library-file/<item_id>", methods=["GET"])
def serve_library_file(job_id: str, item_id: str):
    """Serve o arquivo da biblioteca de mídia — usado pra gerar a
    miniatura/preview do cartão arrastável na interface."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    item = next((i for i in job.get("media_library", []) if i["id"] == item_id), None)
    if item is None:
        return "Arquivo não encontrado na biblioteca.", 404
    return send_file(item["path"])


# --------------------------------------------------------------------- #
# Importar clipe de "Capturar página" ou "Cortar do YouTube" DIRETO pra
# biblioteca de mídia do job, sem precisar baixar e reenviar na mão —
# reaproveita o mesmo mecanismo de arrastar-pro-trecho que já existe
# pra qualquer outro arquivo da biblioteca (o resto do editor/pipeline
# de montagem não precisa saber de onde o arquivo veio).
# --------------------------------------------------------------------- #

def _listar_clipes_importaveis() -> List[Dict[str, Any]]:
    """Lista TODOS os clipes já gerados em 'Capturar página' e 'Cortar
    do YouTube', prontos pra importar em qualquer job — é a mesma
    lista tanto pra mostrar na tela de importação quanto pra validar
    o que o formulário de import pode de fato pedir (nunca confia num
    caminho de arquivo que veio direto do POST sem checar aqui antes).
    """
    itens: List[Dict[str, Any]] = []
    for captura_id, estado in _CAPTURAS_PAGINA.items():
        if estado.get("status") != "pronto":
            continue
        for c in estado.get("clipes_gerados", []):
            itens.append({
                "origem": "captura_pagina", "origem_id": captura_id, "arquivo": c["arquivo"],
                "caminho": c["caminho"],
                "label": f"🖼️ {estado.get('titulo') or estado.get('url')} — {c['descricao']} ({c['duracao']}s)",
            })
    for job_id_yt, job_yt in _YT_CLIPPER_JOBS.items():
        if job_yt.get("status") != "pronto" or not job_yt.get("info"):
            continue
        pasta_clipes = os.path.join(YT_CLIPPER_DIR, job_id_yt, "clipes")
        for video in job_yt["info"]["videos"]:
            for c in video["clipes"]:
                itens.append({
                    "origem": "youtube", "origem_id": job_id_yt, "arquivo": c["arquivo"],
                    "caminho": os.path.join(pasta_clipes, c["arquivo"]),
                    "label": f"▶️ {video['titulo_original']} — {c['inicio']} a {c['fim']}" + (f" ({c['descricao']})" if c.get("descricao") else ""),
                })
    itens.sort(key=lambda i: i["label"])
    return itens


@app.route("/job/<job_id>/importar-biblioteca", methods=["GET"])
def importar_biblioteca_page(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    return render_template("importar_biblioteca.html", job_id=job_id, itens=_listar_clipes_importaveis())


@app.route("/job/<job_id>/importar-biblioteca", methods=["POST"])
def importar_biblioteca_submit(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404

    origem = request.form.get("origem", "")
    origem_id = request.form.get("origem_id", "")
    arquivo = request.form.get("arquivo", "")

    # Nunca confia direto no caminho que o form manda -- só aceita se
    # bater EXATAMENTE com um item que a listagem de verdade conhece
    # (evita path traversal via um form manipulado na mão).
    escolhido = next(
        (i for i in _listar_clipes_importaveis()
         if i["origem"] == origem and i["origem_id"] == origem_id and i["arquivo"] == arquivo),
        None,
    )
    if not escolhido or not os.path.exists(escolhido["caminho"]):
        return "Esse clipe não foi encontrado (pode ter sido removido).", 404

    library_dir = os.path.join(_job_dir(job_id), "media_library")
    os.makedirs(library_dir, exist_ok=True)
    item_id = uuid.uuid4().hex[:8]
    safe_name = secure_filename(os.path.basename(escolhido["caminho"]))
    dest = os.path.join(library_dir, f"{item_id}_{safe_name}")
    shutil.copy(escolhido["caminho"], dest)

    item = {
        "id": item_id, "filename": safe_name, "path": dest, "media_type": "video",
        "origem": escolhido["origem"], "rotulo": re.sub(r"^\W+", "", escolhido.get("label") or "")[:200],
    }
    job.setdefault("media_library", []).append(item)
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


def _arquivo_da_biblioteca_ou_local(job_id: str, job: dict, bib_id: str, valor: str) -> Optional[dict]:
    """override_source de um arquivo da biblioteca (pelo id) ou de um arquivo que já está DENTRO da pasta
    do projeto (o desfazer da IA manda o caminho de volta) — nunca aceita caminho de fora do projeto."""
    if bib_id:
        item = next((i for i in job.get("media_library") or [] if i["id"] == bib_id), None)
        if item and os.path.exists(item.get("path") or ""):
            return {"source": "local_file", "value": item["path"], "kind": item["media_type"], "biblioteca": item["id"]}
    if valor:
        real = os.path.realpath(valor)
        permitidos = [os.path.realpath(_job_dir(job_id))] + [os.path.realpath(os.path.dirname(i["path"]))
                                                            for i in job.get("media_library") or [] if i.get("path")]
        if os.path.isfile(real) and any(real == d or real.startswith(d + os.sep) for d in permitidos):
            item = next((i for i in job.get("media_library") or [] if os.path.realpath(i.get("path") or "") == real), None)
            ext = os.path.splitext(real)[1].lower()
            kind = item["media_type"] if item else ("image" if ext in _MEDIA_LIBRARY_IMAGE_EXTENSIONS else "video")
            cob = os.path.realpath(os.path.join(_job_dir(job_id), "coberturas"))
            extra = {"cobertura": True, "fundo": _fundo_da_cobertura(real)} if real.startswith(cob + os.sep) else {}
            return {"source": "local_file", "value": valor, "kind": kind, **({"biblioteca": item["id"]} if item else {}), **extra}
    return None


def _fundo_da_cobertura(caminho: str) -> str:
    """fundo_papel_ab12cd34ef.png → papel; <tipo>_..._rgb.png (desenhado) → o 1º pedaço conhecido."""
    import prompt_edicao
    nome = os.path.basename(caminho)
    for f in sorted(prompt_edicao.IDS_COBERTURA, key=len, reverse=True):
        if nome.startswith("fundo_" + f + "_") or nome.startswith("fd_" + f + "_"):
            return f
    return "?"


def _trocou_arquivo(job_id: str, job: dict, base: dict, bib_id: str, valor: str) -> bool:
    """O formulário pede um arquivo DIFERENTE do que o trecho já tinha salvo? (igual: segue o caminho antigo,
    que guarda todos os detalhes do arquivo de antes)."""
    novo = _arquivo_da_biblioteca_ou_local(job_id, job, bib_id, valor)
    if not novo:
        return False
    atual = base.get("override_source") or {}
    return atual.get("source") != "local_file" or os.path.realpath(atual.get("value") or "") != os.path.realpath(novo["value"])


def _get_library_item(job: dict, item_id: str):
    item = next((i for i in job.get("media_library", []) if i["id"] == item_id), None)
    if item is None:
        raise ValueError(f"Arquivo {item_id!r} não encontrado na biblioteca de mídia.")
    return item


@app.route("/job/<job_id>/assign-library-to-segment/<int:segment_index>", methods=["POST"])
def assign_library_to_segment(job_id: str, segment_index: int):
    """Atribui um arquivo já enviado pra biblioteca a um TRECHO
    específico, sem precisar reenviar o arquivo — arrastar o cartão da
    biblioteca até o trecho na interface chama essa rota."""
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return "Job não encontrado, ou ainda não tem segmentos pra editar.", 404
    item_id = request.form.get("item_id", "")
    try:
        item = _get_library_item(job, item_id)
    except ValueError as exc:
        return str(exc), 404
    if not (0 <= segment_index < len(job["pending_segments"])):
        return f"Índice de segmento inválido: {segment_index}.", 400

    job["pending_segments"][segment_index]["override_source"] = {
        "source": "local_file", "value": item["path"], "kind": item["media_type"], "biblioteca": item["id"],
    }
    job["pending_segments"][segment_index]["media_type"] = item["media_type"]
    _limpar_erro_do_trecho(job, segment_index)
    _save_state(job_id)
    if request.args.get("json") == "1":
        return jsonify({"ok": True, "segmento": job["pending_segments"][segment_index]})
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/assign-library-to-overlay", methods=["POST"])
def assign_library_to_overlay(job_id: str):
    """Cria um overlay novo (imagem/vídeo) a partir de um arquivo já
    enviado pra biblioteca, sem reenviar — arrastar o cartão até a
    área de overlays chama essa rota. Usa uma janela de tempo padrão
    (os primeiros 5s do vídeo, canto superior direito) que a pessoa
    pode ajustar depois normalmente."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    item_id = request.form.get("item_id", "")
    try:
        item = _get_library_item(job, item_id)
    except ValueError as exc:
        return str(exc), 404

    overlay = {
        "id": uuid.uuid4().hex[:8],
        "media_type": item["media_type"],
        "source": {"source": "local_file", "value": item["path"], "kind": item["media_type"]},
        "start": 0.0, "end": 5.0,
        "position": "top-right", "size_percent": 20,
    }
    job.setdefault("overlays", []).append(overlay)
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/assign-library-to-cutaway/<cutaway_id>", methods=["POST"])
def assign_library_to_cutaway(job_id: str, cutaway_id: str):
    """Atribui um arquivo já enviado pra biblioteca a uma sugestão de
    CORTE, sem reenviar — arrastar o cartão até a sugestão chama essa
    rota."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    item_id = request.form.get("item_id", "")
    try:
        item = _get_library_item(job, item_id)
    except ValueError as exc:
        return str(exc), 404

    cutaway = next((c for c in job.get("cutaway_suggestions", []) if c["id"] == cutaway_id), None)
    if cutaway is None:
        return "Sugestão de corte não encontrada.", 404

    cutaway["resolved_path"] = item["path"]
    _save_state(job_id)
    return redirect(url_for("edit_segments_page", job_id=job_id))


@app.route("/job/<job_id>/search-candidates", methods=["POST"])
def search_candidates_api(job_id: str):
    """Busca ao vivo (sem baixar nada) pra mostrar algumas opções reais
    com thumbnail no editor, antes de a pessoa decidir qual usar num
    segmento — chamado via JS quando clica em "Buscar" no painel de um
    trecho.
    """
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job não encontrado."}), 404

    query = (request.json or {}).get("query", "").strip()
    provider = (request.json or {}).get("provider", "").strip().lower()
    media_type = (request.json or {}).get("media_type", "video").strip().lower()
    if not query or not provider:
        return jsonify({"error": "Faltou 'query' ou 'provider'."}), 400

    import ia_servico
    indice = (request.json or {}).get("indice")
    usar_ia = isinstance(indice, int) and ia_servico.ativo("juiz_manual") and 0 <= indice < len(job.get("pending_segments") or [])
    try:
        candidates = search_candidates(provider, query, media_type=media_type,
                                       max_results=int(ia_servico.config().get("candidatos") or 10) if usar_ia else 6, site_cfg=_job_site_cfg(job),
                                       obra=((request.json or {}).get("obra") or "").strip() or None,
                                       personagem=((request.json or {}).get("personagem") or "").strip() or None)
    except VideoAssemblyError as exc:
        return jsonify({"error": str(exc)}), 200  # erro de busca, não de servidor — mostra na tela

    julgado = False
    if usar_ia and candidates:  # 🤖 os resultados na ordem da nota do juiz, com o motivo
        from video_assembler import julgar_candidatos_ia
        ctx = _ia_ctx_do_trecho(job_id, job, indice)
        j = julgar_candidatos_ia([c for c in candidates if c.get("thumbnail")], ctx, query, recurso="juiz_manual")
        if j:
            candidates, julgado = j["lista"], True
    return jsonify({"candidates": candidates, "can_pin": provider in PROVIDERS_WITH_URL_RESOLUTION, "ia": julgado})


def _ia_ctx_do_trecho(job_id: str, job: dict, indice: int) -> dict:
    """Contexto do juiz pra UM trecho (fala dele + a anterior e a seguinte, ficha do vídeo)."""
    segs = job.get("pending_segments") or []
    vizinhos = [k for k in (indice - 1, indice, indice + 1) if 0 <= k < len(segs)]
    try:
        falas, _p = _falas_por_trecho(job, [segs[k] for k in vizinhos])
    except Exception:  # noqa: BLE001
        falas = [""] * len(vizinhos)
    f = dict(zip(vizinhos, falas))
    return {"ficha": (job.get("ia") or {}).get("ficha"), "fala": f.get(indice, ""), "anterior": f.get(indice - 1, ""),
            "seguinte": f.get(indice + 1, ""), "visual": segs[indice].get("visual") or "", "job": job_id}


def _duracao_de_url(url: Optional[str], job_id: str = "") -> Optional[float]:
    """Duração (s) de um vídeo pelo link (ffprobe lê só o começo do arquivo)."""
    if not url:
        return None
    alvo = url
    m = re.match(r"^/job/([^/]+)/segment-media/(\d+)", url)
    if m:  # arquivo local do trecho
        job = _JOBS.get(m.group(1)) or {}
        segs = job.get("pending_segments") or []
        k = int(m.group(2))
        alvo = ((segs[k].get("override_source") or {}).get("value") if k < len(segs) else None) or ""
    elif url.startswith("/"):
        return None
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", alvo],
                           capture_output=True, text=True, timeout=20)
        d = float(r.stdout.strip())
        return d if d > 0 else None
    except Exception:  # noqa: BLE001
        return None


@app.route("/job/<job_id>/duracao-clipe/<int:indice>", methods=["GET"])
def duracao_clipe(job_id: str, indice: int):
    """Duração do clipe que a telinha mostra nesse trecho (quando o navegador não conseguiu ler)."""
    job = _JOBS.get(job_id)
    if not job or indice >= len(job.get("pending_segments") or []):
        return jsonify({"erro": "Trecho inexistente."}), 404
    url = request.args.get("url") or ""
    d = _duracao_de_url(url) if url and not url.startswith("/job/") else None
    if d is None:
        ov = job["pending_segments"][indice].get("override_source") or {}
        if ov.get("source") == "local_file" and ov.get("value"):
            d = _duracao_de_url(f"/job/{job_id}/segment-media/{indice}")
    if d is not None:
        previews = job.get("segment_previews") or []
        if indice < len(previews) and isinstance(previews[indice], dict):
            previews[indice]["duracao"] = d
    return jsonify({"duracao": d})


def _dividir_em_clipes(job: dict, i: int, dur0: float, extras: List[Dict[str, Any]], corte: float,
                       previews: List[Any], query: str) -> int:
    """Divide o trecho i: o 1º pedaço fica com o clipe atual, cada clipe extra vira um
    trecho seguinte (mesma busca, clipe fixado). O último absorve o que sobrar."""
    segs = job["pending_segments"]
    seg = segs[i]
    ini, fim = float(seg["start"]), float(seg["end"])
    cortes, acc = [], ini + dur0
    for c in extras[:-1]:
        if acc >= fim - 0.3:
            break
        cortes.append(acc)
        acc += max(0.1, float(c["duracao"]) - corte)
    if acc < fim - 0.3:
        cortes.append(acc)
    cortes = [round(t, 3) for t in cortes if ini + 0.3 <= t <= fim - 0.3]
    limites = [ini] + cortes + [fim]
    pedacos = []
    for k in range(len(limites) - 1):
        novo = dict(seg, start=round(limites[k], 3), end=round(limites[k + 1], 3))
        novo.pop("clipes_extra", None)
        novo.pop("curto", None)
        if k > 0:
            c = extras[k - 1]
            novo["override_source"] = {"source": "provider_url", "provider": c["provider"], "value": c["value"], "kind": "video"}
            novo["provider"] = c["provider"]
            for chave in ("template", "template_campos", "on_screen_text", "on_screen_text_style", "entrada"):
                novo.pop(chave, None)
        if k < len(limites) - 2:  # emenda nova: segue a transição do vídeo (dá pra trocar no losango)
            novo.pop("transition", None)
            novo.pop("transition_duration", None)
            novo.pop("saida", None)
        pedacos.append(novo)
    segs[i:i + 1] = pedacos
    while len(previews) < len(segs) - (len(pedacos) - 1):
        previews.append(None)
    novas_previas = []
    for k in range(1, len(pedacos)):
        c = extras[k - 1]
        novas_previas.append({"index": i + k, "ok": True, "thumbnail_url": c.get("thumbnail"), "result_url": c["value"], "label": c.get("label") or "",
                              "error": None, "video_preview_url": c.get("video_preview_url"), "provider": c["provider"],
                              "original_provider": c["provider"], "query": query, "media_type": "video", "duracao": c.get("duracao")})
    previews[i + 1:i + 1] = novas_previas
    return len(pedacos)


@app.route("/job/<job_id>/clipes-curtos/<int:indice>", methods=["POST"])
def clipes_curtos(job_id: str, indice: int):
    """Aba ⏱ Clipes curtos do Estúdio — um clique por trecho, sem mexer nos outros:
      completar: a mesma busca, o 2º, 3º… resultado em seguida até cobrir o trecho;
      maior:     a mesma busca, o 1º resultado com duração >= a do trecho;
      loop:      o clipe atual repete (não entra outra cena);
      padrao:    desfaz (volta ao comportamento normal da montagem)."""
    job = _JOBS.get(job_id)
    if not job or indice >= len(job.get("pending_segments") or []):
        return jsonify({"erro": "Trecho inexistente."}), 404
    corpo = request.get_json(silent=True) or {}
    acao = corpo.get("acao")
    if acao not in ("completar", "maior", "loop", "padrao"):
        return jsonify({"erro": "Ação desconhecida."}), 400
    seg = job["pending_segments"][indice]
    previews = list(job.get("segment_previews") or [])
    while len(previews) < len(job["pending_segments"]):
        previews.append(None)
    p = dict(previews[indice] or {})
    precisa = float(seg["end"]) - float(seg["start"])
    query = str(corpo.get("query") or seg.get("query") or "").strip()
    provider = str(corpo.get("provider") or seg.get("provider") or "").strip().lower()
    prov_busca = p.get("provider") if p.get("provider") in PROVIDERS_WITH_URL_RESOLUTION and not seg.get("override_source") else provider
    ov = seg.get("override_source") or {}

    def _fixar_atual() -> Optional[str]:
        """O clipe que a telinha mostra vira escolha fixa (precisa pra completar/repetir)."""
        if ov.get("source"):
            return None
        if p.get("ok") and p.get("result_url") and p.get("provider") in PROVIDERS_WITH_URL_RESOLUTION:
            seg["override_source"] = {"source": "provider_url", "provider": p["provider"], "value": p["result_url"], "kind": "video"}
            seg["provider"] = p["provider"]
            return None
        return (f"o clipe da telinha não dá pra fixar (banco {p.get('provider') or provider} não baixa um resultado específico) — "
                "use 🎯 Trocar por um maior, ou escolha o clipe em 🔍 Buscar")

    def _buscar() -> List[Dict[str, Any]]:
        cands = search_candidates(prov_busca, query, media_type="video", max_results=12, site_cfg=_job_site_cfg(job),
                                  obra=seg.get("obra") or None, personagem=seg.get("personagem") or None)
        usados = set()
        for k, s2 in enumerate(job["pending_segments"]):
            o2 = s2.get("override_source") or {}
            if o2.get("value"):
                usados.add(o2["value"])
            for c in s2.get("clipes_extra") or []:
                usados.add(c.get("value"))
            p2 = previews[k] if k < len(previews) else None
            if k != indice and p2 and p2.get("result_url"):
                usados.add(p2["result_url"])
        atual = ov.get("value") or p.get("result_url")
        cands = [c for c in cands if c.get("url") and c["url"] != atual]
        livres = [c for c in cands if c["url"] not in usados]
        cands = livres + [c for c in cands if c["url"] in usados]  # repetidos só no fim
        sem = [c for c in cands[:10] if not c.get("duracao")]
        if sem:  # o banco não deu a duração: mede pelo link do vídeo
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=4) as ex:
                for c, d in zip(sem, ex.map(lambda c: _duracao_de_url(c.get("video_preview_url")), sem)):
                    c["duracao"] = d
        return cands

    try:
        if acao == "padrao":
            seg.pop("clipes_extra", None)
            seg.pop("curto", None)
            msg = "voltou ao normal"
        elif acao == "loop":
            erro = _fixar_atual()
            if erro:
                return jsonify({"erro": erro}), 400
            seg.pop("clipes_extra", None)
            seg["curto"] = "loop"
            msg = "o clipe vai repetir até o fim do trecho"
        elif acao == "maior":
            if prov_busca not in PROVIDERS_WITH_URL_RESOLUTION:
                return jsonify({"erro": f"o banco {prov_busca} não deixa escolher um resultado específico"}), 400
            cands = _buscar()
            bom = next((c for c in cands if c.get("duracao") and c["duracao"] >= precisa - 0.05), None)
            if not bom:
                maior = max((c.get("duracao") or 0 for c in cands), default=0)
                return jsonify({"erro": f"nenhum dos {len(cands)} resultados de “{query}” tem {precisa:.1f}s ou mais (o maior tem {maior:.1f}s) — use ➕ Completar"}), 404
            seg["override_source"] = {"source": "provider_url", "provider": prov_busca, "value": bom["url"], "kind": "video"}
            seg["provider"] = prov_busca
            seg.pop("clipes_extra", None)
            seg.pop("curto", None)
            p = {"index": indice, "ok": True, "thumbnail_url": bom.get("thumbnail"), "result_url": bom["url"], "label": bom.get("label") or "",
                 "error": None, "video_preview_url": bom.get("video_preview_url"), "provider": prov_busca, "original_provider": provider,
                 "query": query, "media_type": "video", "duracao": bom["duracao"]}
            previews[indice] = p
            msg = f"trocado por um clipe de {bom['duracao']:.1f}s"
        else:  # completar
            erro = _fixar_atual()
            if erro:
                return jsonify({"erro": erro}), 400
            dur_atual = corpo.get("dur_atual") or p.get("duracao") or _duracao_de_url(p.get("video_preview_url"))
            try:
                dur_atual = float(dur_atual)
            except (TypeError, ValueError):
                return jsonify({"erro": "não consegui medir a duração do clipe atual"}), 400
            p["duracao"] = dur_atual
            prov_extra = (seg.get("override_source") or {}).get("provider") or prov_busca
            if prov_extra not in PROVIDERS_WITH_URL_RESOLUTION:
                return jsonify({"erro": f"o banco {prov_extra} não deixa escolher um resultado específico"}), 400
            corte = float(seg.get("trim_start_frames") or 0) / 30.0
            total, extras = max(0.1, dur_atual - corte), []
            for c in _buscar():
                if total >= precisa - 0.05 or len(extras) >= 8:
                    break
                if not c.get("duracao"):
                    continue
                extras.append({"source": "provider_url", "provider": prov_extra, "value": c["url"], "duracao": round(c["duracao"], 3),
                               "video_preview_url": c.get("video_preview_url"), "thumbnail": c.get("thumbnail"), "label": c.get("label")})
                total += max(0.1, c["duracao"] - corte)
            if not extras:
                return jsonify({"erro": f"a busca “{query}” não trouxe outros resultados com duração conhecida"}), 404
            previews[indice] = p
            if corpo.get("separados", True):
                # cada clipe vira um TRECHO próprio (dá pra pôr transição, efeito, entrada… entre eles)
                n = _dividir_em_clipes(job, indice, max(0.1, dur_atual - corte), extras, corte, previews, query)
                job["segment_previews"] = [dict(x, index=k) if x else None for k, x in enumerate(previews)]
                _reindexar_previas_e_youtube(job)
                _save_state(job_id)
                return jsonify({"ok": True, "dividido": n, "recarregar": True,
                                "msg": f"virou {n} trechos com clipes diferentes: {min(total, precisa):.1f}s de {precisa:.1f}s"
                                       + ("" if total >= precisa - 0.05 else " (o último repete o resto)")})
            seg["clipes_extra"] = extras
            seg.pop("curto", None)
            msg = f"completado com {len(extras)} clipe(s): {total:.1f}s de {precisa:.1f}s" + ("" if total >= precisa - 0.05 else " (o último repete o resto)")
    except VideoAssemblyError as exc:
        return jsonify({"erro": str(exc)}), 502
    job["segment_previews"] = previews
    _save_state(job_id)
    pv = previews[indice] or {}
    return jsonify({"ok": True, "msg": msg, "segmento": seg,
                    "preview": {k: pv.get(k) for k in ("thumbnail_url", "video_preview_url", "result_url", "query", "provider", "duracao", "label") if pv.get(k) is not None}})


@app.route("/job/<job_id>/segmento/<int:indice>/usar-candidato", methods=["POST"])
def usar_candidato(job_id: str, indice: int):
    """Botão "✅ Usar esta" do editor: troca a mídia do trecho pelo resultado
    clicado na busca. FOTO: baixa na hora (original; se o site bloquear, a
    miniatura do buscador) e vira o arquivo do trecho. VÍDEO: fixa o post
    (Pexels/Pixabay/Mixkit) ou usa o link direto do vídeo quando o banco
    entrega um."""
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    segs = job["pending_segments"]
    if not (0 <= indice < len(segs)):
        return jsonify({"erro": "Trecho inexistente."}), 404
    corpo = request.get_json(silent=True) or {}
    provider = (corpo.get("provider") or "").strip().lower()
    media_type = (corpo.get("media_type") or segs[indice].get("media_type") or "video").strip().lower()
    seg = segs[indice]
    anterior = seg.get("override_source") or {}
    animacao = {k: anterior[k] for k in ("zoom_direction", "focus_x", "focus_y") if k in anterior}

    if media_type == "image":
        urls = [u for u in (corpo.get("image_url"), corpo.get("thumbnail")) if u]
        if not urls:
            return jsonify({"erro": "Esse resultado não tem link de imagem."}), 400
        try:
            from buscador_imagens_unificado import BuscadorImagensError, ImagemBuscador, baixar_imagem

            img = ImagemBuscador(
                original_url=urls[0], thumbnail_url=urls[-1] if len(urls) > 1 else "",
                source_page=corpo.get("url") or "", engine=provider, query=seg.get("query") or "",
            )
            pasta = os.path.join(_job_dir(job_id), "escolhas_editor")
            caminho = baixar_imagem(img, pasta, stem=f"trecho{indice}_{uuid.uuid4().hex[:6]}")
        except BuscadorImagensError as exc:
            return jsonify({"erro": f"Não consegui baixar essa imagem: {exc}"}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"erro": f"Falha ao baixar: {exc}"}), 500
        seg["override_source"] = {"source": "local_file", "value": caminho, "kind": "image", **animacao}
        seg["media_type"] = "image"  # trecho de vídeo que ganhou uma foto (todas as fontes aparecem no Buscar)
        thumb = f"/job/{job_id}/thumbnail/{indice}"
        preview_extra = {"thumbnail_path": caminho}
        modo = "upload"
    else:
        if provider in PROVIDERS_WITH_URL_RESOLUTION and corpo.get("url"):
            seg["override_source"] = {"source": "provider_url", "provider": provider, "value": corpo["url"]}
            modo = "post_url"
        elif corpo.get("video_url"):
            seg["override_source"] = {"source": "url", "value": corpo["video_url"], "kind": "video"}
            modo = "url"
        else:
            return jsonify({"erro": f"O banco {provider!r} não deixa escolher um resultado específico — use 'colar link' ou envie o arquivo."}), 400
        seg["media_type"] = "video"
        thumb = corpo.get("thumbnail") or None
        preview_extra = {}

    _limpar_erro_do_trecho(job, indice)
    previews = list(job.get("segment_previews") or [])
    if indice < len(previews):
        previews[indice] = {
            "index": indice, "ok": True, "thumbnail_url": thumb, "result_url": corpo.get("url") or None,
            "label": corpo.get("label") or "", "error": None, "video_preview_url": corpo.get("video_url") or None,
            "provider": provider, "original_provider": seg.get("provider"), **preview_extra,
        }
        job["segment_previews"] = previews
    _save_state(job_id)
    _prebaixar_iniciar(job_id, job)  # ⬇ o clipe escolhido já começa a baixar
    return jsonify({"ok": True, "modo": modo, "thumbnail_url": thumb, "override_source": seg["override_source"]})


# --------------------------------------------------------------------- #
# Timelines alternativas do Estúdio (ver timelines.py): Timeline 2 = 2ª
# melhor opção de cada cena; "Juntar" = trecho a trecho, da 1 ou da 2.
# --------------------------------------------------------------------- #
import timelines as _tl  # noqa: E402


def _segmento_obj(d: dict) -> VideoSegment:
    import dataclasses
    nomes = {f.name for f in dataclasses.fields(VideoSegment)}
    return VideoSegment(**{k: v for k, v in d.items() if k in nomes})


def _midia_igual_a_1(f1: Optional[dict], seg: dict, motivo: str) -> dict:
    """Trecho sem 2ª opção possível: a timeline 2 repete a mídia da 1."""
    f = dict(f1) if f1 else _tl.fatia(seg, None)
    f = dict(f, start=float(seg["start"]), end=float(seg["end"]))
    p = dict(f.get("preview") or {"ok": False, "thumbnail_url": None, "result_url": None, "error": None})
    p["label"] = ((p.get("label") or "") + f" (igual à timeline 1: {motivo})").strip()
    f["preview"] = p
    f["igual_a_1"] = motivo
    return f


def _segunda_foto(job_id: str, seg: dict, cfg: dict, evitar: set, usados: set, i: int) -> Optional[dict]:
    """Foto de banco (Pexels/Wikipedia): 1º resultado que a timeline 1 não usa, baixado."""
    from buscador_imagens_unificado import ImagemBuscador, baixar_imagem
    cands = search_candidates(seg["provider"], seg["query"], media_type="image", max_results=8, site_cfg=cfg)
    for c in cands:
        chave = c.get("url") or c.get("image_url")
        if not chave or chave in evitar or chave in usados:
            continue
        urls = [u for u in (c.get("image_url"), c.get("thumbnail")) if u]
        if not urls:
            continue
        try:
            img = ImagemBuscador(original_url=urls[0], thumbnail_url=urls[-1] if len(urls) > 1 else "",
                                 source_page=c.get("url") or "", engine=seg["provider"], query=seg["query"])
            caminho = baixar_imagem(img, os.path.join(_job_dir(job_id), "timeline2"), stem=f"trecho{i}_{uuid.uuid4().hex[:6]}")
        except Exception:  # noqa: BLE001
            continue
        usados.add(chave)
        return {"override_source": {"source": "local_file", "value": caminho, "kind": "image"}, "media_type": "image",
                "preview": {"ok": True, "thumbnail_url": None, "thumbnail_path": caminho, "result_url": c.get("url"),
                            "label": "2ª opção · " + (c.get("label") or seg["query"]), "error": None,
                            "provider": seg["provider"], "original_provider": seg["provider"]}}
    return None


def _gerar_timeline2(job_id: str) -> None:
    job = _JOBS[job_id]
    st = _tl.estado(job)
    cfg = _job_site_cfg(job)
    segs = [dict(s) for s in job["pending_segments"]]
    base1 = _tl.fatias_da(job, "1")
    evitar = _tl.urls(base1)
    prog = st["gerando"] = {"atual": 0, "total": len(segs), "erro": None}
    _save_state(job_id)
    saida: List[Optional[dict]] = [None] * len(segs)
    lock = threading.Lock()

    def _pronto(i: int, f: dict) -> None:
        with lock:
            saida[i] = dict(f, start=float(segs[i]["start"]), end=float(segs[i]["end"]))
            prog["atual"] = sum(1 for x in saida if x is not None)

    def _f1(i):
        return _tl.melhor(base1, float(segs[i]["start"]), float(segs[i]["end"]))

    try:
        imagens, fotos, videos = [], [], []
        for i, sd in enumerate(segs):
            prov, tipo = sd.get("provider"), sd.get("media_type") or "video"
            if prov == "youtube":
                _pronto(i, _midia_igual_a_1(_f1(i), sd, "YouTube é escolhido à mão"))
            elif prov in ("flow", "runpod"):
                _pronto(i, _midia_igual_a_1(_f1(i), sd, "imagem gerada por IA"))
            elif tipo == "image" and prov in BROWSER_IMAGE_SEARCH_PROVIDERS:
                imagens.append((i, _segmento_obj(dict(sd, override_source=None))))
            elif tipo == "image":
                fotos.append(i)
            else:
                videos.append(i)

        def _imagens():
            if not imagens:
                return
            cache1 = job.get("imagens_buscadores") or {}
            evitar_img = [x for r in cache1.values() if isinstance(r, dict) and r.get("ok")
                          for v in [r] + list(r.get("extras") or [])
                          for x in (v.get("original_url"), v.get("thumbnail_url"), v.get("assinatura")) if x]

            def _on(i, res):
                if res.get("ok") and res.get("path"):
                    _pronto(i, {"override_source": {"source": "local_file", "value": res["path"], "kind": "image"}, "media_type": "image",
                                "preview": {"ok": True, "thumbnail_url": None, "thumbnail_path": res["path"],
                                            "result_url": res.get("source_page") or None,
                                            "label": f"2ª opção · {res.get('engine')}: {res.get('title') or res.get('query')}", "error": None,
                                            "provider": res.get("engine"), "original_provider": segs[i]["provider"]}})
                else:
                    _pronto(i, _midia_igual_a_1(_f1(i), segs[i], res.get("erro") or "nenhum buscador achou outra imagem"))
            job["imagens_buscadores_t2"] = {}
            prefetch_browser_images(imagens, os.path.join(_job_dir(job_id), "timeline2"), cfg,
                                    cache=job["imagens_buscadores_t2"], on_result=_on, evitar_extra=evitar_img)

        th = threading.Thread(target=_imagens, daemon=True)
        th.start()

        usados_foto: set = set()
        for i in fotos:
            try:
                f = _segunda_foto(job_id, segs[i], cfg, evitar, usados_foto, i)
            except Exception as exc:  # noqa: BLE001
                f = None
                print(f"[timeline 2] trecho {i + 1}: {exc}", flush=True)
            _pronto(i, f or _midia_igual_a_1(_f1(i), segs[i], "o banco não trouxe outra foto"))

        tracker = UsedClipsTracker()

        def _video(i):
            factory = ClientFactory(cfg)
            try:
                return fetch_segment_preview_lightweight(_segmento_obj(dict(segs[i], override_source=None)), site_cfg=cfg,
                                                         client_factory=factory, used_tracker=tracker, evitar=evitar)
            finally:
                factory.close_all()

        conc = max(1, min(cfg.get("preview_fetch_concurrency", 3), max(1, len(videos))))
        with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as ex:
            fut = {ex.submit(_video, i): i for i in videos}
            for f in concurrent.futures.as_completed(fut):
                i = fut[f]
                try:
                    r = f.result()
                except Exception as exc:  # noqa: BLE001
                    r = {"ok": False, "error": str(exc)}
                if not r.get("ok"):
                    _pronto(i, _midia_igual_a_1(_f1(i), segs[i], r.get("error") or "sem outro resultado"))
                    continue
                prov = r.get("provider") or segs[i]["provider"]
                ov = ({"source": "provider_url", "provider": prov, "value": r["result_url"]}
                      if prov in PROVIDERS_WITH_URL_RESOLUTION and r.get("result_url") else None)
                _pronto(i, {"override_source": ov, "media_type": "video", "provider": prov,
                            "preview": {"ok": True, "thumbnail_url": r.get("thumbnail_url"), "result_url": r.get("result_url"),
                                        "label": "2ª opção · " + (r.get("label") or segs[i]["query"]), "error": None,
                                        "video_preview_url": r.get("video_preview_url"), "provider": prov,
                                        "original_provider": segs[i]["provider"], "query": segs[i]["query"], "media_type": "video",
                                        **({} if ov else {"nao_fixa": True})}})
        th.join()
        fatias = [f or _midia_igual_a_1(_f1(i), segs[i], "falhou") for i, f in enumerate(saida)]
        _tl.guardar_gerada(job, "2", fatias)
        st["gerando"] = None
        st["gerada_em"] = time.time()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        prog["erro"] = str(exc)
    _save_state(job_id)
    _avisar_fim(f"🎞️ Timeline 2 de “{_nome_job(job_id)}”", prog.get("erro"), f"/job/{job_id}/edit-segments", "timeline")


@app.route("/job/<job_id>/timeline/gerar", methods=["POST"])
def timeline_gerar(job_id: str):
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    st = _tl.estado(job)
    if (st.get("gerando") or {}).get("total") and not (st.get("gerando") or {}).get("erro"):
        return jsonify({"ok": True, "ja_gerando": True})
    if st["ativa"] == "3":
        return jsonify({"erro": "Saia do Juntar (vá pra timeline 1 ou 2) pra gerar a timeline 2 de novo."}), 400
    st["gerando"] = {"atual": 0, "total": len(job["pending_segments"]), "erro": None}  # já aparece "gerando" antes da thread começar
    threading.Thread(target=_gerar_timeline2, args=(job_id,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/job/<job_id>/timeline/status", methods=["GET"])
def timeline_status(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Job não encontrado."}), 404
    st = _tl.estado(job)
    return jsonify({"ativa": st["ativa"], "tem_2": _tl.tem_2(job), "gerando": st.get("gerando")})


@app.route("/job/<job_id>/timeline/trocar", methods=["POST"])
def timeline_trocar(job_id: str):
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    para = str((request.get_json(silent=True) or {}).get("para") or "")
    st = _tl.estado(job)
    if (st.get("gerando") or {}).get("total") and not st["gerando"].get("erro") and para != st["ativa"]:
        return jsonify({"erro": "Espere a timeline 2 terminar de ser gerada."}), 409
    try:
        _tl.trocar(job, para)
    except LookupError:
        return jsonify({"precisa_gerar": True}), 409
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400
    job.pop("assembly_error_segment_index", None)
    _save_state(job_id)
    return jsonify({"ok": True, "ativa": st["ativa"]})


@app.route("/job/<job_id>/timeline/escolher", methods=["POST"])
def timeline_escolher(job_id: str):
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"erro": "Job não encontrado."}), 404
    corpo = request.get_json(silent=True) or {}
    indices = corpo.get("indices")
    if indices == "todos":
        indices = list(range(len(job["pending_segments"])))
    try:
        indices = [int(x) for x in (indices if isinstance(indices, list) else [corpo.get("indice")])]
        _tl.escolher(job, indices, str(corpo.get("de") or ""))
    except (TypeError, ValueError) as exc:
        return jsonify({"erro": str(exc) or "pedido inválido"}), 400
    _save_state(job_id)
    return jsonify({"ok": True, "segmentos": {i: _seg_estudio(job_id, job, i) for i in indices if 0 <= i < len(job["pending_segments"])},
                    "escolhas": _tl.escolhas(job)})


@app.route("/job/<job_id>/timeline/<tl>/thumb/<int:indice>", methods=["GET"])
def timeline_thumb(job_id: str, tl: str, indice: int):
    """Miniatura da mídia que a timeline `tl` usa nesse trecho (pro Juntar comparar)."""
    job = _JOBS.get(job_id)
    if not job or not (0 <= indice < len(job.get("pending_segments") or [])):
        return "Trecho não encontrado.", 404
    s = job["pending_segments"][indice]
    f = _tl.melhor(_tl.fatias_da(job, tl), float(s["start"]), float(s["end"]))
    if not f:
        return "Sem mídia.", 404
    ov = f.get("override_source") or {}
    p = f.get("preview") or {}
    path = ov.get("value") if ov.get("source") == "local_file" else p.get("thumbnail_path")
    if path and os.path.isfile(path):
        pasta = os.path.join(_job_dir(job_id), "miniaturas")
        os.makedirs(pasta, exist_ok=True)
        destino = os.path.join(pasta, uuid.uuid5(uuid.NAMESPACE_URL, f"{path}|{os.path.getmtime(path)}").hex[:16] + ".jpg")
        if not os.path.exists(destino):
            try:
                generate_thumbnail(path, destino)
            except Exception:  # noqa: BLE001
                return send_file(path)
        return send_file(destino)
    if p.get("thumbnail_url"):
        return redirect(p["thumbnail_url"])
    return "Sem miniatura.", 404


def _busca_do_form(form, i: int, base: dict, query: str) -> dict:
    """"visual", "alternativas" e "busca_reserva" do trecho (ver VideoSegment).
    O Estúdio manda os três (a revisão de buscas com IA muda eles); o editor
    clássico não — aí ficam os da IA, e as alternativas só continuam valendo
    se a pessoa não trocou a busca (alternativa de outra busca não serve)."""
    from prompt_builder import alternativas_do_item, limpar_query
    if f"seg_{i}_alternativas" in form:
        try:
            _alts = json.loads(form.get(f"seg_{i}_alternativas") or "[]")
        except ValueError:
            _alts = []
        alternativas = alternativas_do_item({"alternativas": _alts if isinstance(_alts, list) else []}, query)
    else:
        alternativas = list(base.get("alternativas") or []) if query == base.get("query") else []
    visual = (form.get(f"seg_{i}_visual") if f"seg_{i}_visual" in form else base.get("visual")) or ""
    reserva = form.get("busca_reserva") if "busca_reserva" in form else base.get("busca_reserva")
    return {
        "visual": visual.strip()[:240] or None,
        "alternativas": alternativas or None,
        "busca_reserva": (limpar_query(reserva or "")[:100] or None),
        "texto_da_ia": base.get("texto_da_ia") or None,
        "obra": _juntar_varios(form.get(f"seg_{i}_obra") if f"seg_{i}_obra" in form else base.get("obra")) or None,
        "personagem": _juntar_varios(form.get(f"seg_{i}_personagem") if f"seg_{i}_personagem" in form else base.get("personagem")) or None,
        **_clipes_curtos_do_form(form, i, base),
    }


def _clipes_curtos_do_form(form, i: int, base: dict) -> dict:
    """Clipe curto (aba ⏱ Clipes curtos): clipes que completam o trecho e/ou "loop"."""
    extra = base.get("clipes_extra")
    if f"seg_{i}_clipes_extra" in form:
        try:
            extra = json.loads(form.get(f"seg_{i}_clipes_extra") or "[]")
        except ValueError:
            extra = base.get("clipes_extra")
    limpos = []
    for c in extra if isinstance(extra, list) else []:
        if isinstance(c, dict) and c.get("value") and c.get("source") in ("provider_url", "url", "local_file"):
            limpos.append({k: c.get(k) for k in ("source", "provider", "value", "duracao", "video_preview_url", "thumbnail", "label") if c.get(k) is not None})
    curto = form.get(f"seg_{i}_curto") if f"seg_{i}_curto" in form else base.get("curto")
    return {"clipes_extra": limpos[:8] or None, "curto": curto if curto == "loop" else None}


@app.route("/job/<job_id>/confirm-segments", methods=["POST"])
def confirm_segments(job_id: str):
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return "Job não encontrado, ou ainda não tem segmentos pra editar.", 404

    job_dir = _job_dir(job_id)
    uploads_subdir = os.path.join(job_dir, "manual_uploads")
    segments: List[VideoSegment] = []

    global_aspect_fill = request.form.get("global_aspect_fill", load_site_config().get("aspect_fill", "black")).strip().lower()
    if global_aspect_fill not in ("black", "mosaic", "zoom", "smart", "cartao"):
        global_aspect_fill = "black"
    try:
        global_trim_frames = max(0, min(120, int(request.form.get("global_trim_start_frames", load_site_config().get("trim_start_frames", 10)))))
    except (TypeError, ValueError):
        global_trim_frames = 10
    _defaults_antes = job.get("editor_defaults") or {}
    job["editor_defaults"] = {"aspect_fill": global_aspect_fill, "trim_start_frames": global_trim_frames}
    _cf = _cartao_fundo_do_form(request.form.get("global_cartao_fundo"))  # 🪧 fundo dos cartões (v84_85)
    if _cf is not None:
        job["editor_defaults"]["cartao_fundo"] = _cf
    elif _defaults_antes.get("cartao_fundo"):
        job["editor_defaults"]["cartao_fundo"] = _defaults_antes["cartao_fundo"]
    # filtro de cor global e Direção (DarkPlanner): o editor clássico não manda -> mantém
    import dp_visual
    if "global_filtro_cor" in request.form:
        _filtro = request.form.get("global_filtro_cor", "").strip()
        job["editor_defaults"]["filtro_cor"] = _filtro if (_filtro and dp_visual.cadeia_filtro(_filtro)) else "original"
    elif _defaults_antes.get("filtro_cor"):
        job["editor_defaults"]["filtro_cor"] = _defaults_antes["filtro_cor"]
    if "global_sons_enviados" in request.form:
        job["editor_defaults"]["sons_auto"] = {k: request.form.get(f"global_sons_{k}") == "on" for k in ("transicoes", "cenas", "destaques", "editoriais")}
        try:
            job["editor_defaults"]["sons_volume"] = max(0.0, min(2.0, float(request.form.get("global_sons_volume", 0.55))))
        except (TypeError, ValueError):
            job["editor_defaults"]["sons_volume"] = 0.55
    else:
        for _k in ("sons_auto", "sons_volume"):
            if _k in _defaults_antes:
                job["editor_defaults"][_k] = _defaults_antes[_k]
    _dir = request.form.get("global_direcao", _defaults_antes.get("direcao") or "").strip()
    if _dir:
        job["editor_defaults"]["direcao"] = _dir
    transicoes_validas = {v for v, _r in TRANSITION_LABELS}
    global_transicao = request.form.get("global_transition_type", "site").strip()
    if global_transicao in transicoes_validas:
        job["editor_defaults"]["transition_type"] = global_transicao
        try:
            job["editor_defaults"]["transition_duration"] = max(0.1, min(3.0, float(request.form.get("global_transition_duration", 0.6))))
        except (TypeError, ValueError):
            job["editor_defaults"]["transition_duration"] = 0.6

    for i, base in enumerate(job["pending_segments"]):
        try:
            seg_start = max(0.0, float(request.form.get(f"seg_{i}_start", base["start"])))
            seg_end = max(seg_start + 0.05, float(request.form.get(f"seg_{i}_end", base["end"])))
        except (TypeError, ValueError):
            seg_start, seg_end = float(base["start"]), float(base["end"])
        query = request.form.get(f"seg_{i}_query", base["query"]).strip() or base["query"]
        provider = request.form.get(f"seg_{i}_provider", base["provider"]).strip().lower() or base["provider"]
        on_screen_text = request.form.get(f"seg_{i}_on_screen_text", base.get("on_screen_text") or "").strip() or None

        # personalização visual do texto na tela — todos os campos têm
        # um padrão que reproduz o visual de sempre, então isso não
        # muda nada pra quem não mexer nesses controles. O campo oculto
        # "_text_style_submitted" distingue "checkbox desmarcada de
        # propósito" de "formulário nem tinha esse campo" (chamada
        # antiga, ou um teste enviando só alguns campos) — checkbox
        # desmarcada some do form igual a campo ausente, então sem essa
        # marcação não daria pra saber qual dos dois casos é esse.
        base_style = base.get("on_screen_text_style") or {}
        if request.form.get(f"seg_{i}_text_style_submitted") == "1":
            text_size_raw = request.form.get(f"seg_{i}_text_size", "").strip()
            on_screen_text_style = {
                "position": request.form.get(f"seg_{i}_text_position", "bottom-center"),
                "font": request.form.get(f"seg_{i}_text_font", "bold"),
                "border": request.form.get(f"seg_{i}_text_border") == "on",
                "background": request.form.get(f"seg_{i}_text_background") == "on",
                "shadow": request.form.get(f"seg_{i}_text_shadow") == "on",
                "x_percent": float(request.form.get(f"seg_{i}_text_x", 50) or 50),
                "y_percent": float(request.form.get(f"seg_{i}_text_y", 88) or 88),
            }
            font_color_raw = request.form.get(f"seg_{i}_text_font_color", "").strip()
            if font_color_raw:
                on_screen_text_style["font_color"] = font_color_raw
            border_color_raw = request.form.get(f"seg_{i}_text_border_color", "").strip()
            if border_color_raw:
                on_screen_text_style["border_color"] = border_color_raw
            border_width_raw = request.form.get(f"seg_{i}_text_border_width", "").strip()
            if border_width_raw:
                try:
                    on_screen_text_style["border_width"] = int(border_width_raw)
                except ValueError:
                    pass
            shadow_color_raw = request.form.get(f"seg_{i}_text_shadow_color", "").strip()
            if shadow_color_raw:
                on_screen_text_style["shadow_color"] = shadow_color_raw
            shadow_offset_raw = request.form.get(f"seg_{i}_text_shadow_offset", "").strip()
            if shadow_offset_raw:
                try:
                    on_screen_text_style["shadow_offset"] = int(shadow_offset_raw)
                except ValueError:
                    pass
            animation_raw = request.form.get(f"seg_{i}_text_animation", "none").strip()
            if animation_raw in ("none", "fade", "slide", "zoom"):
                on_screen_text_style["animation"] = animation_raw
            animation_duration_raw = request.form.get(f"seg_{i}_text_animation_duration", "").strip()
            if animation_duration_raw:
                try:
                    on_screen_text_style["animation_duration"] = max(0.05, float(animation_duration_raw))
                except ValueError:
                    pass
            slide_direction_raw = request.form.get(f"seg_{i}_text_slide_direction", "").strip()
            if slide_direction_raw in ("left", "right", "top", "bottom"):
                on_screen_text_style["slide_direction"] = slide_direction_raw
            on_screen_text_style["x_percent"] = max(0.0, min(100.0, on_screen_text_style["x_percent"]))
            on_screen_text_style["y_percent"] = max(0.0, min(100.0, on_screen_text_style["y_percent"]))
            if text_size_raw:
                try:
                    on_screen_text_style["font_size"] = int(text_size_raw)
                except ValueError:
                    pass  # valor inválido -- ignora e usa o tamanho automático
            # Janela de tempo PRÓPRIA do texto dentro do trecho (em
            # segundos, relativa ao início do trecho) — permite o texto
            # aparecer só numa PARTE do trecho (arrastado no bloco
            # amarelo da timeline), independente da duração do vídeo.
            # Sem os dois campos (ou inválidos), o texto continua
            # cobrindo o trecho inteiro, como sempre foi.
            text_start_raw = request.form.get(f"seg_{i}_text_start_offset", "").strip()
            text_end_raw = request.form.get(f"seg_{i}_text_end_offset", "").strip()
            if text_start_raw and text_end_raw:
                try:
                    seg_duration = seg_end - seg_start
                    so = max(0.0, min(seg_duration, float(text_start_raw)))
                    eo = max(0.0, min(seg_duration, float(text_end_raw)))
                    if eo > so:
                        on_screen_text_style["start_offset"] = so
                        on_screen_text_style["end_offset"] = eo
                except ValueError:
                    pass  # valores inválidos -- ignora e o texto cobre o trecho inteiro
        else:
            on_screen_text_style = base_style or None

        media_type = base.get("media_type", "video")
        source_mode = request.form.get(f"seg_{i}_source_mode", "auto")
        if source_mode == "auto" and request.form.get(f"seg_{i}_media_type") in ("video", "image"):
            media_type = request.form[f"seg_{i}_media_type"]  # ↩ desfazer a mídia da IA: o trecho volta a ser vídeo/foto

        # segmentos de foto (media_type="image") só têm busca de verdade
        # via provedores em PHOTO_SEARCH_PROVIDERS (Pexels e Wikipedia,
        # hoje) — o dropdown de banco no editor não distingue isso
        # visualmente, então força de volta pra "pexels" em vez de deixar
        # salvo um par media_type=image + provider=outro banco (ex:
        # mixkit, magnific), que nunca funcionaria de verdade (ver
        # PHOTO_SEARCH_PROVIDERS em prompt_builder.py).
        if media_type == "image" and provider not in PHOTO_SEARCH_PROVIDERS:
            provider = "pexels"

        override_source = None

        if source_mode == "upload":
            uploaded = request.files.get(f"seg_{i}_file")
            if uploaded and uploaded.filename:
                os.makedirs(uploads_subdir, exist_ok=True)
                safe_name = secure_filename(uploaded.filename)
                dest = os.path.join(uploads_subdir, f"seg{i}_{safe_name}")
                uploaded.save(dest)
                override_source = {
                    "source": "local_file", "value": dest,
                    "zoom_direction": request.form.get(f"seg_{i}_zoom_direction", "in"),
                    "focus_x": float(request.form.get(f"seg_{i}_focus_x", 0.5) or 0.5),
                    "focus_y": float(request.form.get(f"seg_{i}_focus_y", 0.5) or 0.5),
                }
            elif _trocou_arquivo(job_id, job, base, request.form.get(f"seg_{i}_biblioteca", ""),
                                 request.form.get(f"seg_{i}_local_value", "")):
                # 📁 v84_67: a edição da IA (ou o desfazer dela) pôs/voltou um arquivo da biblioteca ou um já enviado
                override_source = _arquivo_da_biblioteca_ou_local(job_id, job, request.form.get(f"seg_{i}_biblioteca", ""),
                                                                  request.form.get(f"seg_{i}_local_value", ""))
                media_type = override_source["kind"] or media_type
                override_source.update({
                    "zoom_direction": request.form.get(f"seg_{i}_zoom_direction", "in"),
                    "focus_x": float(request.form.get(f"seg_{i}_focus_x", 0.5) or 0.5),
                    "focus_y": float(request.form.get(f"seg_{i}_focus_y", 0.5) or 0.5),
                })
            elif (base.get("override_source") or {}).get("source") == "local_file":
                # modo "upload" reenviado sem escolher um arquivo novo —
                # não dá pra pré-preencher um <input type="file"> por
                # segurança do navegador, então sem isso a pessoa
                # precisaria re-enviar o mesmo arquivo TODA vez que
                # confirmar de novo (ex: depois de corrigir outro
                # trecho que falhou). Reaproveita o upload anterior —
                # mas com a animação de câmera escolhida AGORA no formulário.
                override_source = dict(base["override_source"])
                if f"seg_{i}_zoom_direction" in request.form:
                    override_source["zoom_direction"] = request.form.get(f"seg_{i}_zoom_direction", "in")
                    try:
                        override_source["focus_x"] = float(request.form.get(f"seg_{i}_focus_x", 0.5) or 0.5)
                        override_source["focus_y"] = float(request.form.get(f"seg_{i}_focus_y", 0.5) or 0.5)
                    except ValueError:
                        pass
        elif source_mode == "url":
            url = request.form.get(f"seg_{i}_url", "").strip()
            if url:
                override_source = {
                    "source": "url", "value": url,
                    "zoom_direction": request.form.get(f"seg_{i}_zoom_direction", "in"),
                    "focus_x": float(request.form.get(f"seg_{i}_focus_x", 0.5) or 0.5),
                    "focus_y": float(request.form.get(f"seg_{i}_focus_y", 0.5) or 0.5),
                }
        elif source_mode == "post_url":
            url = request.form.get(f"seg_{i}_post_url", "").strip()
            post_provider = request.form.get(f"seg_{i}_post_provider", "").strip().lower()
            if url and post_provider:
                override_source = {"source": "provider_url", "provider": post_provider, "value": url}
        else:
            # "auto" (padrão): se o termo/banco não mudaram desde a prévia
            # Reaproveita a prévia já baixada como arquivo final SÓ pra
            # a prévia agora só BUSCA (não baixa nada — usa o thumbnail
            # do próprio provedor), então não tem mais um arquivo local
            # pra reaproveitar diretamente. Em vez disso, se o segmento
            # não foi editado, "fixamos" o EXATO resultado que apareceu
            # na prévia via link de post — assim a montagem final busca
            # esse resultado específico (não um resultado novo,
            # potencialmente diferente), sem precisar baixar de novo na
            # etapa de prévia. Só funciona pra fixar em provedores com
            # resolução por URL (Pexels/Pixabay/Mixkit); pros outros
            # dois (Magnific/VistaCreate), a montagem faz uma busca nova
            # com o mesmo termo — o resultado pode variar ligeiramente.
            unchanged = query == base["query"] and provider == base["provider"]
            preview = next((p for p in job.get("segment_previews", []) if p and p["index"] == i), None)
            # NOTA: antes, um segmento "auto" sem edição nenhuma fixava
            # automaticamente o mesmo resultado exato da prévia (via
            # link direto) — isso mantinha consistência com a
            # miniatura mostrada, mas fazia TODO trecho não editado
            # (a maioria, numa narração normal) pular por completo a
            # busca de cena extra pra completar a duração e o
            # rastreamento de cenas já usadas em outros trechos, já que
            # um "override_source" é tratado como escolha deliberada e
            # nunca passa por essas duas melhorias. Removido de
            # propósito: agora um trecho não editado faz uma busca
            # nova na montagem (podendo trazer um resultado
            # ligeiramente diferente do mostrado na prévia), mas
            # ganhando as duas melhorias em TODOS os trechos, não só
            # nos editados manualmente.
            #
            # Ainda assim, se a prévia já descobriu que o banco
            # ORIGINAL da IA estava fora do ar/bloqueado e caiu pro
            # próximo da prioridade, começa a busca de verdade já por
            # esse banco que se sabe que funciona — sem isso, a
            # montagem tentaria o banco original de novo à toa antes
            # de cair no fallback (que ela mesma já tem).
            if unchanged and preview and preview.get("provider") and preview["provider"] != provider:
                provider = preview["provider"]
            # trecho do YouTube com vídeo já escolhido no painel: o clipe
            # cortado vale mesmo com o seletor em "buscar automaticamente"
            # (o painel não recarrega a página, então o seletor pode não ter mudado).
            if provider == "youtube" and (base.get("override_source") or {}).get("source") == "local_file":
                override_source = base["override_source"]

        aspect_choice = request.form.get(f"seg_{i}_aspect_fill", "global").strip().lower()
        aspect_fill = global_aspect_fill if aspect_choice == "global" else aspect_choice
        if aspect_fill not in ("black", "zoom", "mosaic", "smart", "cartao"):
            aspect_fill = global_aspect_fill
        trim_choice = request.form.get(f"seg_{i}_trim_frames", "global").strip().lower()
        try:
            trim_frames = global_trim_frames if trim_choice == "global" else max(0, min(120, int(trim_choice)))
        except ValueError:
            trim_frames = global_trim_frames

        # animação de entrada/saída da FOTO (media_type="image") — não
        # confundir com "animation" do on_screen_text_style acima, que é
        # do TEXTO; essas checkboxes só aparecem/importam pra segmentos
        # de imagem no editor, mas ler mesmo assim (sem checar
        # media_type) não tem custo nem risco: o campo simplesmente não
        # existe no form pra um segmento de vídeo, então some
        # silenciosamente.
        image_fade_in = request.form.get(f"seg_{i}_image_fade_in") == "on"
        image_fade_out = request.form.get(f"seg_{i}_image_fade_out") == "on"
        image_fade_duration_raw = request.form.get(f"seg_{i}_image_fade_duration", "").strip()
        try:
            image_fade_duration = max(0.05, float(image_fade_duration_raw)) if image_fade_duration_raw else 0.5
        except ValueError:
            image_fade_duration = 0.5

        blur_sigma_raw = request.form.get(f"seg_{i}_blur_sigma", "").strip()
        try:
            blur_sigma = max(0.0, float(blur_sigma_raw)) if blur_sigma_raw else 0.0
        except ValueError:
            blur_sigma = 0.0

        # zoom_direction/focus_x/focus_y do PRÓPRIO segmento (não só do
        # override) -- assim a animação de câmera de uma foto escolhida
        # automaticamente pela busca (media_type="image", sem upload/url
        # manual) também pode ser configurada, não só quando a origem é
        # manual (o campo já aparece no formulário pra imagem em
        # qualquer modo, ver ken_burns_fields no template).
        zoom_direction_raw = request.form.get(f"seg_{i}_zoom_direction", "in").strip()
        if zoom_direction_raw not in _ZOOM_DIRECTIONS_VALIDAS:
            zoom_direction_raw = "in"
        try:
            focus_x = max(0.0, min(1.0, float(request.form.get(f"seg_{i}_focus_x", 0.5) or 0.5)))
        except ValueError:
            focus_x = 0.5
        try:
            focus_y = max(0.0, min(1.0, float(request.form.get(f"seg_{i}_focus_y", 0.5) or 0.5)))
        except ValueError:
            focus_y = 0.5

        transicao_seg = request.form.get(f"seg_{i}_transition", base.get("transition") or "global").strip()
        if transicao_seg not in transicoes_validas:
            transicao_seg = None  # "global" (ou valor estranho) = segue a transição do vídeo
        transicao_dur_raw = request.form.get(f"seg_{i}_transition_duration", "").strip()
        try:
            transicao_dur = max(0.1, min(3.0, float(transicao_dur_raw))) if transicao_dur_raw else None
        except ValueError:
            transicao_dur = None

        template_id, template_campos = _template_do_form(request.form, i, base)
        efeitos_dp = _efeitos_dp_do_form(request.form, i, base)
        _som_tr = (request.form.get(f"seg_{i}_transition_som") if f"seg_{i}_transition_som" in request.form else base.get("transition_som")) or ""
        efeitos_dp["transition_som"] = _som_tr if (_som_tr == "nenhum" or _dp_sons_valido(_som_tr)) else None

        segments.append(VideoSegment(
            start=seg_start, end=seg_end, provider=provider, query=query,
            on_screen_text=on_screen_text, on_screen_text_style=on_screen_text_style, media_type=media_type,
            aspect_fill=aspect_fill, trim_start_frames=trim_frames, override_source=override_source,
            image_fade_in=image_fade_in, image_fade_out=image_fade_out, image_fade_duration=image_fade_duration,
            blur_sigma=blur_sigma, zoom_direction=zoom_direction_raw, focus_x=focus_x, focus_y=focus_y,
            transition=transicao_seg, transition_duration=transicao_dur,
            template=template_id, template_campos=template_campos,
            **_busca_do_form(request.form, i, base, query),
            **efeitos_dp,
        ))

    # Salva os segmentos RECÉM-CONFIRMADOS de volta em pending_segments —
    # sem isso, uma falha de montagem posterior (num trecho DIFERENTE)
    # faz a página do editor recarregar mostrando os valores ORIGINAIS
    # da IA de novo, descartando qualquer correção manual já feita nesta
    # ou em tentativas anteriores. Bug real relatado: corrigir o Trecho
    # 16, a montagem falhar depois no Trecho 21, e ao voltar pro editor
    # o Trecho 16 aparecer de volta com a fonte quebrada original.
    _antigos = job.get("pending_segments") or []
    _novos = [s.to_dict() for s in segments]
    for _k, _nv in enumerate(_novos):  # o link do YouTube colado continua junto do clipe dele
        _velho = _antigos[_k] if _k < len(_antigos) else {}
        _rv = request.form.get(f"seg_{_k}_revisao")  # 🎬 marca da revisão do diretor ("procurar na mão")
        if _rv is not None:
            try:
                _rv = json.loads(_rv) if _rv else None
            except ValueError:
                _rv = None
            if isinstance(_rv, dict) and _rv.get("manual"):
                _nv["revisao"] = {k: str(_rv.get(k) or "")[:300] for k in ("procurar", "motivo")}
                _nv["revisao"]["manual"] = True
        elif isinstance(_velho.get("revisao"), dict) and _velho.get("query") == _nv.get("query"):
            _nv["revisao"] = _velho["revisao"]  # editor clássico (sem o campo): mantém
        if _velho.get("youtube_link") and (_nv.get("override_source") or {}).get("value") == (_velho.get("override_source") or {}).get("value"):
            _nv["youtube_link"] = _velho["youtube_link"]
    # 🎞 v84_182: a animação do Flow fica no trecho (achada pelo id — o número muda quando divide/junta). O servidor é
    # quem manda nela: se o vídeo chegou enquanto a página estava aberta, o trecho fica com ele.
    _animacoes = {(_s.get("animacao") or {}).get("id"): _s for _s in _antigos if (_s.get("animacao") or {}).get("id")}
    _usados_anim: set = set()
    for _k, _nv in enumerate(_novos):
        _aid = request.form.get(f"seg_{_k}_animacao_id")
        if _aid is None:  # editor clássico (sem o campo): pelo número
            _vel = _antigos[_k] if _k < len(_antigos) else {}
            _aid = (_vel.get("animacao") or {}).get("id") if (_vel.get("start"), _vel.get("end")) == (_nv.get("start"), _nv.get("end")) else ""
        _dono = _animacoes.get(_aid or "")
        if not _dono:
            continue
        if _aid in _usados_anim:  # dividiu um trecho animado: a 2ª parte volta pra imagem (a animação fica na 1ª)
            if os.path.normpath(str((_nv.get("override_source") or {}).get("value") or "")) == \
                    os.path.normpath(str(_dono["animacao"].get("corte") or "-")):
                _antes = _dono["animacao"].get("antes") or {}
                _nv["override_source"] = _antes.get("override_source")
                _nv["media_type"] = _antes.get("media_type") or "image"
            continue
        _usados_anim.add(_aid)
        _nv["animacao"] = _dono["animacao"]
        _ov_srv = _dono.get("override_source") or {}
        if _ov_srv.get("animacao") == _aid and _animar.em_uso(_dono) and not (_nv.get("override_source") or {}).get("animacao") \
                and (_nv.get("override_source") or {}).get("value") == ((_dono["animacao"].get("antes") or {}).get("override_source") or {}).get("value"):
            _nv["override_source"], _nv["media_type"] = _ov_srv, "video"  # a página não sabia do vídeo novo
    job["pending_segments"] = _novos
    _destaques_do_form(job, request.form)
    _sfx_do_form(job, request.form)
    if "censura_json" in request.form:
        import dp_censura
        try:
            _cz = json.loads(request.form.get("censura_json") or "[]")
        except ValueError:
            _cz = None
        if isinstance(_cz, list):
            job["censura"] = dp_censura.normalizar(_cz[:80], job.get("total_duration"))
    if "editoriais_json" in request.form:
        import dp_editorial
        try:
            _eds = json.loads(request.form.get("editoriais_json") or "[]")
        except ValueError:
            _eds = None
        if isinstance(_eds, list):
            job["editoriais"] = [e for e in (dp_editorial.normalizar(x, job.get("total_duration")) for x in _eds[:60]) if e]
    if "graficos_json" in request.form:
        import dp_graficos
        try:
            _gs = json.loads(request.form.get("graficos_json") or "[]")
        except ValueError:
            _gs = None
        if isinstance(_gs, list):
            job["graficos"] = [g for g in (dp_graficos.normalizar(x, job.get("total_duration")) for x in _gs[:60]) if g]
    if request.form.get("kit_json"):
        try:
            _kit = json.loads(request.form["kit_json"])
            if isinstance(_kit, dict):
                job.setdefault("editor_defaults", {})["kit"] = {str(k)[:24]: [str(x)[:64] for x in v][:400] for k, v in _kit.items() if isinstance(v, list)}
        except ValueError:
            pass
    if _formato_do_form(request.form, "orientacao"):
        job["orientation"] = _formato_do_form(request.form, "orientacao")
    if request.form.get("export_quality") in __import__("qualidade_export").RESOLUCOES:
        job["export_quality"] = request.form["export_quality"]
    if request.form.get("qualidade_exportacao"):
        job["qualidade_exportacao"] = __import__("qualidade_export").valida(request.form["qualidade_exportacao"])
    if request.form.get("export_paralelo") in __import__("export_paralelo").MODOS:  # ⚡ v84_115
        job["export_paralelo"] = request.form["export_paralelo"]
        try:  # vira o padrão dos próximos vídeos também
            save_site_config({"export_paralelo": request.form["export_paralelo"]})
        except Exception:  # noqa: BLE001
            pass
    if request.form.get("legendas_json"):
        import dp_legendas
        try:
            job["legendas"] = dp_legendas.normalizar(json.loads(request.form["legendas_json"]))
        except ValueError:
            pass

    # foto do que a telinha do Estúdio mostrava (pro diagnóstico pós-export)
    if request.form.get("previa_snapshot_json") and request.form.get("acao") != "salvar":
        _snap = request.form.get("previa_snapshot_json") or ""
        if len(_snap) < 6_000_000:
            try:
                json.loads(_snap)
                with open(os.path.join(job_dir, "previa_snapshot.json"), "w", encoding="utf-8") as _f:
                    _f.write(_snap)
            except (ValueError, OSError):
                pass

    # "💾 Salvar" do editor (sem montar): guarda tudo e volta pro editor
    if request.form.get("acao") == "salvar":
        _save_state(job_id)
        _prebaixar_iniciar(job_id, job)  # ⬇ trocou clipe/busca: baixa o que mudou
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": True, "pending_segments": job["pending_segments"]})
        return redirect(url_for("edit_segments_page", job_id=job_id))

    # Checagem ANTECIPADA — bug real relatado: um trecho com
    # media_type="image" sem PEXELS_API_KEYS configurado só descobria
    # isso DEPOIS de rodar a montagem inteira (podendo levar minutos em
    # vídeos longos), obrigando a pessoa a esperar tudo pra só então ver
    # o erro e ter que confirmar de novo. Detecta isso ANTES de sequer
    # começar a baixar qualquer coisa, e já mostra o mesmo aviso/destaque
    # vermelho de sempre, sem gastar tempo à toa.
    #
    # Testa uma vez por PROVEDOR de foto distinto usado nos segmentos
    # (não só "a config vale pro site inteiro" como antes) — agora que
    # existe mais de um provedor de foto (Pexels precisa de chave,
    # Wikipedia não precisa de nada), um segmento em "wikipedia" não deve
    # falhar por causa de uma chave do Pexels ausente, e vice-versa.
    checked_photo_providers: set = set()
    for i, seg in enumerate(segments):
        if seg.media_type == "image" and not seg.override_source and seg.provider not in checked_photo_providers:
            checked_photo_providers.add(seg.provider)
            photo_error = photo_api_configuration_error(provider=seg.provider)
            if photo_error:
                job["status"] = "pronto_para_editar"
                job["assembly_error"] = (
                    f"Trecho {i + 1}: Não consigo buscar fotos (media_type='image') com "
                    f"'{seg.provider}': {photo_error}"
                )
                job["assembly_error_segment_index"] = i
                _save_state(job_id)
                return redirect(url_for("job_status_page", job_id=job_id))

    _start_assembly(job_id, job, _fixar_midias_da_previa(job, segments))
    return redirect(url_for("job_status_page", job_id=job_id))


def _fixar_midias_da_previa(job: dict, segments: List[VideoSegment]) -> List[VideoSegment]:
    """O vídeo exportado usa os MESMOS clipes que o Estúdio mostrou.

    Antes, todo trecho sem mídia escolhida à mão fazia uma busca NOVA na
    montagem — e a busca nova (com "não repetir" e outros candidatos) trazia
    outras cenas: o vídeo exportado não batia com o que a pessoa editou em
    cima. Agora, se a prévia do trecho foi achada com a MESMA busca e o banco
    sabe baixar um resultado específico pelo link (Pexels, Pixabay, Mixkit),
    a montagem usa exatamente aquele vídeo. Se ele for mais curto que o
    trecho, a montagem ainda completa com outra cena (como faz com mídia
    escolhida). Só pra montar: não vai pro `pending_segments`, então o trecho
    continua "automático" no editor (trocar a busca depois volta a buscar).
    Desliga com `fixar_midias_da_previa: false` nas configurações."""
    from dataclasses import replace as _replace
    from video_assembler import _PROVIDERS_WITH_URL_RESOLUTION
    previews = job.get("segment_previews") or []
    ligado = _job_site_cfg(job).get("fixar_midias_da_previa", True)
    saida = []
    motivos = []  # pro diagnóstico pós-export: por que cada trecho usou (ou não) o clipe da telinha
    fixados: set = set()  # trecho dividido herda a prévia: o mesmo clipe não é fixado duas vezes
    for i, seg in enumerate(segments):
        p = previews[i] if i < len(previews) and isinstance(previews[i], dict) else {}
        motivo, fixou = None, False
        flow_local = None
        if not seg.override_source and p.get("ok") and (p.get("provider") or seg.provider) in ("flow", "runpod") \
                and (p.get("query") is None or " ".join(str(p["query"]).split()) == " ".join(seg.query.split())):
            from video_assembler import flow_arquivo_local as _fal
            flow_local = next((x for x in (_fal(p.get(k)) for k in ("video_preview_url", "result_url", "thumbnail_url")) if x), None)
        if seg.override_source:
            motivo = "mídia escolhida à mão (" + str(seg.override_source.get("source")) + ") — entra a que você escolheu"
        elif flow_local:  # v84_112: o Flow já gerou na prévia — a montagem usa ESSE arquivo (não gera de novo)
            fixou = True
            motivo = "mídia do Flow gerada na prévia — entra o mesmo arquivo"
            kind = "image" if __import__("video_assembler")._infer_media_kind(flow_local) == "image" else "video"
            seg = _replace(seg, override_source={"source": "local_file", "value": flow_local, "kind": kind, "da_previa": True},
                           media_type=kind)
        elif not ligado:
            motivo = "fixar_midias_da_previa desligado nas configurações — a montagem busca de novo"
        elif (seg.media_type or "video") != "video":
            motivo = "foto: a montagem busca a foto de novo (pode vir outra)"
        elif not p:
            motivo = "o trecho não tem prévia gravada no servidor — a montagem busca de novo"
        elif not p.get("ok"):
            motivo = "a prévia desse trecho tinha falhado — a montagem busca de novo"
        elif not p.get("result_url"):
            motivo = "a prévia não guardou o link do clipe (prévia trocada sem link) — a montagem busca de novo"
        elif p.get("provider") not in _PROVIDERS_WITH_URL_RESOLUTION:
            motivo = f"o banco {p.get('provider')} não deixa baixar um resultado específico — a montagem busca de novo"
        elif p.get("query") is None:
            motivo = "a prévia não guardou com qual busca foi achada — a montagem busca de novo"
        elif " ".join(str(p["query"]).split()) != " ".join(seg.query.split()):
            motivo = f"a busca mudou depois da prévia (“{p['query']}” → “{seg.query}”): a telinha ainda mostrava o clipe da busca antiga"
        elif (p.get("media_type") or "video") != "video":
            motivo = "a prévia era foto e o trecho é vídeo — a montagem busca de novo"
        elif p["result_url"] in fixados:
            motivo = "o mesmo clipe já foi fixado em outro trecho (trecho dividido) — a montagem busca outra cena"
        else:
            fixados.add(p["result_url"])
            fixou = True
            motivo = "clipe da telinha fixado pelo link"
            seg = _replace(seg, provider=p["provider"], override_source={
                "source": "provider_url", "provider": p["provider"], "value": p["result_url"], "kind": "video", "da_previa": True})
        motivos.append({"trecho": i + 1, "fixado": fixou, "motivo": motivo, "link_previa": p.get("result_url"),
                        "video_previa": p.get("video_preview_url"), "busca_previa": p.get("query"), "banco_previa": p.get("provider")})
        saida.append(seg)
    job["fixacao_previa"] = motivos
    return saida


# --------------------------------------------------------------------- #
# ⬇ Pré-download no Estúdio: enquanto a pessoa edita, os clipes que a
# montagem vai usar (clipe da prévia, link, resultado escolhido, clipes
# curtos extras) já vão sendo baixados em segundo plano pra
# jobs/<id>/prebaixados. A montagem acha o arquivo lá e não baixa de novo.
# --------------------------------------------------------------------- #
_PREBAIXAR: Dict[str, dict] = {}
_PREBAIXAR_LOCK = threading.Lock()


def _prebaixar_lista(job: dict) -> list:
    """As mídias (override_source) que a montagem baixaria AGORA, na mesma
    regra de `_fixar_midias_da_previa`."""
    import video_assembler as _va
    segs_d = job.get("pending_segments") or []
    if not segs_d:
        return []
    diag = job.get("fixacao_previa")
    try:
        segs = _fixar_midias_da_previa(job, [_segmento_obj(d) for d in segs_d])
    finally:
        if diag is None:
            job.pop("fixacao_previa", None)
        else:
            job["fixacao_previa"] = diag
    lista = []
    for s in segs:
        if _va.chave_prebaixado(s.override_source):
            lista.append(dict(s.override_source))
        for c in (getattr(s, "clipes_extra", None) or []):
            if isinstance(c, dict) and _va.chave_prebaixado(c):
                lista.append(dict(c, kind="video"))
    return lista


PREVIAS_CACHE = "previas_cache"
PREVIA_MAX_BYTES = 80 * 1024 * 1024


def _nome_previa(url: str, tipo: str) -> str:
    """Nome do arquivo guardado de uma prévia (vídeo/miniatura) remota."""
    import hashlib
    from urllib.parse import urlparse
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext not in (".mp4", ".webm", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        ext = ".mp4" if tipo == "video" else ".jpg"
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:24] + ext


def _previa_local(job_id: str, url: Optional[str], tipo: str) -> Optional[str]:
    """URL local (/job/<id>/cache-previa/<nome>) se essa prévia já foi guardada."""
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    nome = _nome_previa(url, tipo)
    arq = os.path.join(_job_dir(job_id), PREVIAS_CACHE, nome)
    try:
        if os.path.getsize(arq) > 0:
            return f"/job/{job_id}/cache-previa/{nome}"
    except OSError:
        pass
    return None


def _urls_de_previa(job: dict) -> list:
    """(url, tipo) de tudo que a telinha do Estúdio carrega da internet: vídeo e miniatura de cada trecho
    (e os clipes curtos extras)."""
    vistos, lista = set(), []

    def _add(u, tipo):
        if isinstance(u, str) and u.startswith(("http://", "https://")) and u not in vistos:
            vistos.add(u)
            lista.append((u, tipo))
    for p in job.get("segment_previews") or []:
        if isinstance(p, dict) and p.get("ok"):
            _add(p.get("video_preview_url"), "video")
            _add(p.get("thumbnail_url"), "imagem")
    for d in job.get("pending_segments") or []:
        for c in (d.get("clipes_extra") or []) if isinstance(d, dict) else []:
            if isinstance(c, dict):
                _add(c.get("video_preview_url"), "video")
                _add(c.get("thumbnail"), "imagem")
    return lista


def _baixar_previa(url: str, destino: str) -> bool:
    import requests
    tmp = destino + ".part"
    try:
        with requests.get(url, stream=True, timeout=(10, 60), headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            total = 0
            with open(tmp, "wb") as f:
                for bloco in r.iter_content(chunk_size=512 * 1024):
                    if bloco:
                        total += len(bloco)
                        if total > PREVIA_MAX_BYTES:
                            raise ValueError("prévia grande demais")
                        f.write(bloco)
        if total <= 0:
            raise ValueError("vazio")
        arquivo_seguro.trocar(tmp, destino)
        return True
    except Exception:  # noqa: BLE001 — sem a cópia local, a telinha usa o link da internet como antes
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _guardar_previas(job_id: str, job: dict, pb: dict, cancel=None) -> None:
    """Guarda no disco (jobs/<id>/previas_cache) os vídeos/miniaturas que a telinha mostra:
    ao reabrir o projeto, o Estúdio carrega tudo do PC em vez de baixar de novo da internet."""
    import concurrent.futures as _cf
    pasta = os.path.join(_job_dir(job_id), PREVIAS_CACHE)
    lista = [(u, t) for (u, t) in _urls_de_previa(job) if not _previa_local(job_id, u, t)]
    pb["previas_total"] = len(_urls_de_previa(job))
    pb["previas"] = pb["previas_total"] - len(lista)
    if not lista:
        return
    os.makedirs(pasta, exist_ok=True)

    def _um(item):
        if cancel and cancel():
            return False
        u, t = item
        return _baixar_previa(u, os.path.join(pasta, _nome_previa(u, t)))

    n = max(1, min(int(_job_site_cfg(job).get("assembly_fetch_concurrency", 3) or 3) + 1, len(lista)))
    with _cf.ThreadPoolExecutor(max_workers=n) as ex:
        for ok in ex.map(_um, lista):
            if ok:
                pb["previas"] = pb.get("previas", 0) + 1


@app.route("/job/<job_id>/cache-previa/<nome>")
def cache_previa(job_id: str, nome: str):
    """Serve uma prévia guardada (com suporte a Range pro <video> poder pular)."""
    if job_id not in _JOBS or not re.fullmatch(r"[0-9a-f]{24}\.[a-z0-9]{2,5}", nome):
        return "não encontrado", 404
    resp = send_from_directory(os.path.join(_job_dir(job_id), PREVIAS_CACHE), nome, conditional=True, max_age=60 * 60 * 24 * 30)
    return resp


def _prebaixar_iniciar(job_id: str, job: dict) -> bool:
    """Liga (ou re-agenda) o download em segundo plano. Devolve True se vai rodar."""
    if os.environ.get("NARRATION_SEM_PREBAIXAR"):  # testes: nada de baixar em segundo plano
        return False
    cfg = _job_site_cfg(job)
    if not cfg.get("prebaixar_no_editor", True) or not job.get("pending_segments"):
        return False
    with _PREBAIXAR_LOCK:
        est = _PREBAIXAR.setdefault(job_id, {"rodando": False, "de_novo": False})
        if est["rodando"]:
            est["de_novo"] = True  # mudou algo no meio: roda mais uma volta no fim
            return True
        est["rodando"], est["de_novo"] = True, False

    def _run():
        import video_assembler as _va
        try:
            while True:
                lista = _prebaixar_lista(job)
                pb = {"estado": "baixando", "feitos": 0, "total": 0, "falhas": 0, "baixados": 0, "inicio": time.time()}
                job["prebaixar"] = pb

                def _item(feitos, total, _ok):
                    pb["feitos"], pb["total"] = feitos, total

                # 1º as prévias da telinha (leves): ao reabrir o projeto elas saem do disco
                _guardar_previas(job_id, job, pb, cancel=lambda: job.get("status") == "montando"
                                 or _PREBAIXAR.get(job_id, {}).get("de_novo"))
                res = _va.prebaixar_midias(
                    lista, os.path.join(_job_dir(job_id), "prebaixados"), cfg, on_item=_item,
                    cancel_check=lambda: job.get("status") == "montando" or _PREBAIXAR.get(job_id, {}).get("de_novo"),
                )
                pb.update(estado="pronto", previas=pb.get("previas", 0), previas_total=pb.get("previas_total", 0), feitos=res["baixados"] + res["ja_tinha"], total=res["total"], falhas=res["falhas"], baixados=res["baixados"], ja_tinha=res["ja_tinha"],
                          erros=res["erros"][:5], fim=time.time())
                with _PREBAIXAR_LOCK:
                    est = _PREBAIXAR[job_id]
                    if not est["de_novo"] or job.get("status") == "montando":
                        est["rodando"] = est["de_novo"] = False
                        return
                    est["de_novo"] = False
        except Exception as exc:  # noqa: BLE001 — nunca derruba nada: a montagem baixa como antes
            job["prebaixar"] = {"estado": "erro", "erro": str(exc)[:300]}
            with _PREBAIXAR_LOCK:
                _PREBAIXAR[job_id] = {"rodando": False, "de_novo": False}

    threading.Thread(target=_run, daemon=True).start()
    return True


def _verificar_montagem(job_id: str, job: dict, baixar: bool = True) -> dict:
    """🔎 Confere TUDO que pode derrubar a montagem, de uma vez, antes de começar:
    arquivos que sumiram, links que não baixam, banco de foto sem chave, busca
    vazia, cena (template) que não existe, YouTube sem vídeo, espaço em disco…
    Os links escolhidos à mão já são baixados aqui (vão pro pré-download), então
    o que passar nessa checagem não falha mais por download na montagem.

    Devolve {"ok", "erros", "avisos", "problemas": [{"trecho", "indice", "tipo", "msg"}]}."""
    import shutil as _sh
    import video_assembler as _va
    import cenas_dp
    segs_d = job.get("pending_segments") or []
    probs: list = []

    def _p(i, tipo, msg):
        probs.append({"indice": i, "trecho": (i + 1) if i is not None else None, "tipo": tipo, "msg": msg})

    fotos_ok: dict = {}
    links: list = []  # (indice, override, é_extra)
    for i, d in enumerate(segs_d):
        try:
            seg = _segmento_obj(d)
        except Exception as exc:  # noqa: BLE001
            _p(i, "erro", f"trecho com dados inválidos ({exc})")
            continue
        ov = seg.override_source or {}
        if float(seg.end) - float(seg.start) < 0.05:
            _p(i, "erro", "o trecho tem duração zero — junte com o vizinho ou ajuste o tempo")
        tid = getattr(seg, "template", None)
        if tid and not cenas_dp.template(tid):
            _p(i, "erro", f"a cena (template) “{tid}” não existe mais — troque ou tire do trecho")
        if ov.get("source") == "local_file":
            caminho = ov.get("value")
            if not caminho or not os.path.exists(caminho):
                _p(i, "erro", "o arquivo escolhido pra esse trecho não existe mais no disco — envie de novo ou troque a mídia")
            else:
                try:
                    _va._validate_downloaded_file(caminho)
                except Exception as exc:  # noqa: BLE001
                    _p(i, "erro", f"o arquivo escolhido está corrompido/ilegível ({str(exc)[:160]}) — troque a mídia")
        elif ov.get("source") == "provider_url" and ov.get("provider") not in _va._PROVIDERS_WITH_URL_RESOLUTION:
            _p(i, "erro", f"o banco {ov.get('provider')} não deixa baixar um resultado pelo link — escolha de outro banco ou envie o arquivo")
        elif ov.get("source") in ("url", "provider_url"):
            links.append((i, dict(ov), False))
        elif ov.get("source"):
            _p(i, "erro", f"mídia com origem desconhecida ({ov.get('source')}) — escolha de novo")
        for c in (getattr(seg, "clipes_extra", None) or []):
            if isinstance(c, dict) and _va.chave_prebaixado(c):
                links.append((i, dict(c, kind="video"), True))
        if not ov:
            if not (seg.query or "").strip() and seg.provider not in ("youtube",):
                _p(i, "erro", "o trecho está sem busca e sem mídia — escreva o que buscar ou escolha uma mídia")
            if seg.provider == "youtube":
                _p(i, "aviso", "YouTube sem vídeo escolhido — vai usar o 1º resultado ou os bancos normais")
            if (seg.media_type or "video") == "image" and seg.provider not in fotos_ok:
                fotos_ok[seg.provider] = photo_api_configuration_error(provider=seg.provider)
            if (seg.media_type or "video") == "image" and fotos_ok.get(seg.provider):
                _p(i, "erro", f"não dá pra buscar foto em “{seg.provider}”: {fotos_ok[seg.provider]}")

    # links escolhidos à mão: baixa AGORA (o que não baixar aparece aqui, não no meio da montagem)
    if links and baixar:
        cache_dir = os.path.join(_job_dir(job_id), "prebaixados")
        faltam = [ov for (_i, ov, _e) in links if not _va.prebaixado(ov, cache_dir)]
        if faltam:
            _va.prebaixar_midias(faltam, cache_dir, _job_site_cfg(job))
        for (i, ov, extra) in links:
            if not _va.prebaixado(ov, cache_dir):
                if extra:
                    _p(i, "aviso", f"um clipe curto extra não baixou ({ov.get('value')}) — o trecho fica sem ele")
                else:
                    _p(i, "erro", f"o link escolhido não baixa ({ov.get('value')}) — cole outro link, escolha outro resultado ou envie o arquivo")

    # clipes da prévia que não baixaram no pré-download: a montagem busca outro (só avisa)
    try:
        cache_dir = os.path.join(_job_dir(job_id), "prebaixados")
        for i, s in enumerate(_fixar_midias_da_previa(dict(job), [_segmento_obj(d) for d in segs_d])):
            ov = s.override_source or {}
            if ov.get("da_previa") and not _va.prebaixado(ov, cache_dir) and (job.get("prebaixar") or {}).get("estado") == "pronto" \
                    and not _PREBAIXAR.get(job_id, {}).get("rodando"):
                _p(i, "aviso", "o clipe que a telinha mostra não baixou — a montagem vai buscar outra cena pra esse trecho")
    except Exception:  # noqa: BLE001
        pass

    for k, ov in enumerate(job.get("overlays") or []):
        src = (ov.get("source") or {}) if isinstance(ov, dict) else {}
        if src.get("source") == "local_file" and not os.path.exists(str(src.get("value") or "")):
            _p(None, "aviso", f"o overlay {ov.get('id', k + 1)} usa um arquivo que não existe mais — ele vai ficar de fora")
    if job.get("music_path") and not os.path.exists(job["music_path"]):
        _p(None, "aviso", "a música de fundo não está mais no disco — o vídeo sai sem ela")
    if not job.get("audio_path") or not os.path.exists(job.get("audio_path") or ""):
        _p(None, "erro", "a narração (áudio) não está mais no disco — gere ou envie o áudio de novo")
    try:
        livre = _sh.disk_usage(_job_dir(job_id)).free
        precisa = max(2.0, len(segs_d) * 0.03)  # ~30 MB por trecho, no mínimo 2 GB
        if livre < precisa * 1024 ** 3:
            _p(None, "erro" if livre < 0.5 * 1024 ** 3 else "aviso",
               f"pouco espaço em disco ({livre / 1024 ** 3:.1f} GB livres; a montagem precisa de uns {precisa:.0f} GB)")
    except OSError:
        pass
    if not _sh.which("ffmpeg"):
        _p(None, "erro", "o ffmpeg não foi encontrado — sem ele não dá pra montar")

    probs.sort(key=lambda p: (p["tipo"] != "erro", p["indice"] if p["indice"] is not None else -1))
    erros = sum(1 for p in probs if p["tipo"] == "erro")
    return {"ok": erros == 0, "erros": erros, "avisos": len(probs) - erros, "problemas": probs}


@app.route("/job/<job_id>/verificar-montagem", methods=["POST"])
def verificar_montagem_api(job_id: str):
    job = _JOBS.get(job_id)
    if not job or "pending_segments" not in job:
        return jsonify({"error": "job não encontrado"}), 404
    try:
        return jsonify(_verificar_montagem(job_id, job))
    except Exception as exc:  # noqa: BLE001 — a checagem nunca impede de montar
        return jsonify({"ok": True, "erros": 0, "avisos": 0, "problemas": [], "falhou": str(exc)[:300]})


@app.route("/job/<job_id>/prebaixar", methods=["GET", "POST"])
def prebaixar_api(job_id: str):
    """GET: andamento do pré-download. POST: (re)começa."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job não encontrado"}), 404
    if request.method == "POST" and job.get("status") != "montando":
        _prebaixar_iniciar(job_id, job)
    pb = dict(job.get("prebaixar") or {"estado": "parado"})
    pb["rodando"] = bool(_PREBAIXAR.get(job_id, {}).get("rodando"))
    return jsonify(pb)


# --------------------------------------------------------------------- #
# Página 3: acompanhar o progresso da montagem, e baixar o resultado
# --------------------------------------------------------------------- #

@app.route("/job/<job_id>/status-page", methods=["GET"])
def job_status_page(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    return render_template("result.html", job=job)


@app.route("/job/<job_id>/status", methods=["GET"])
def job_status_api(job_id: str):
    """Endpoint JSON, consultado via polling pela página de status."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job não encontrado"}), 404
    return jsonify({
        "status": job.get("status"),
        "progress": job.get("progress"),
        "error": job.get("error"),
        "assembly_error": job.get("assembly_error"),
        "assembly_error_segment_index": job.get("assembly_error_segment_index"),
        "prebaixar": job.get("prebaixar"),
        "avisos_montagem": job.get("avisos_montagem") or [] if job.get("status") == "concluido" else [],
        "descricao_youtube": job.get("descricao_youtube") if job.get("status") == "concluido" else None,
        "capitulos_video": job.get("capitulos_video") if job.get("status") == "concluido" else None,
    })


@app.route("/job/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id: str):
    """Pede pra cancelar um job em andamento (busca de prévias ou
    montagem final). Não mata threads na força — segmentos já em
    andamento no momento do pedido terminam normalmente, mas nenhum
    segmento NOVO começa depois disso. Só faz sentido pra jobs ainda
    rodando; pra outros status, não tem efeito (não é um erro, só uma
    operação sem nada a fazer).
    """
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job não encontrado"}), 404
    if job.get("status") in ("buscando_previas", "montando"):
        job["cancel_requested"] = True
    return jsonify({"status": job.get("status"), "cancel_requested": job.get("cancel_requested", False)})


@app.route("/job/<job_id>/download", methods=["GET"])
def download_result(job_id: str):
    job = _JOBS.get(job_id)
    if not job or job.get("status") != "concluido":
        return "Vídeo ainda não está pronto.", 404
    return send_file(job["output_path"], as_attachment=True, download_name=f"video_{job_id}.mp4")


@app.route("/job/<job_id>/stream", methods=["GET"])
def stream_result(job_id: str):
    """Serve o vídeo final SEM forçar download (sem
    `Content-Disposition: attachment`) — usado pelo "Monitor de
    Programa" (uma tag `<video>` de verdade na página de resultado, que
    toca o vídeo direto, com busca/seek funcionando via requisições
    Range que o Flask já responde por padrão).
    """
    job = _JOBS.get(job_id)
    if not job or job.get("status") != "concluido":
        return "Vídeo ainda não está pronto.", 404
    return send_file(job["output_path"], mimetype="video/mp4", conditional=True)


@app.route("/job/<job_id>/stream-captioned", methods=["GET"])
def stream_captioned_result(job_id: str):
    """Igual a `/stream`, mas pra versão com legenda queimada — permite
    o Monitor de Programa alternar entre as duas sem precisar baixar
    nenhuma delas antes.
    """
    job = _JOBS.get(job_id)
    if not job or job.get("status") != "concluido" or not job.get("captioned_output_path"):
        return "Versão legendada não está disponível.", 404
    return send_file(job["captioned_output_path"], mimetype="video/mp4", conditional=True)


@app.route("/job/<job_id>/download-captioned", methods=["GET"])
def download_captioned_result(job_id: str):
    job = _JOBS.get(job_id)
    if not job or job.get("status") != "concluido" or not job.get("captioned_output_path"):
        return "Versão legendada não está disponível.", 404
    return send_file(job["captioned_output_path"], as_attachment=True, download_name=f"video_{job_id}_legendado.mp4")


@app.route("/job/<job_id>/download-diagnostico", methods=["GET"])
def download_diagnostico(job_id: str):
    """Relatório em texto: o que pode ter deixado o vídeo exportado diferente da
    telinha do Estúdio (clipes trocados, fonte/tamanho, escurecimento, cenas).
    `?refazer=1` gera de novo a partir do vídeo que já está pronto."""
    job = _JOBS.get(job_id)
    if not job:
        return "Job não encontrado.", 404
    caminho = os.path.join(_job_dir(job_id), "diagnostico_export.txt")
    saida = job.get("output_path")
    for _ in range(180):  # ainda gerando em segundo plano (logo depois da montagem): espera um pouco
        if not job.get("diagnostico_gerando"):
            break
        time.sleep(0.5)
    if (request.args.get("refazer") or not os.path.exists(caminho)) and saida and os.path.exists(saida):
        try:
            import diagnostico_export
            diagnostico_export.gerar(job_id, job, _job_dir(job_id), saida)
        except Exception:  # noqa: BLE001
            return f"Não consegui gerar o diagnóstico:\n{traceback.format_exc()[-1500:]}", 500, {"Content-Type": "text/plain; charset=utf-8"}
    if not os.path.exists(caminho):
        return "Ainda não tem diagnóstico — ele é gerado quando a montagem termina.", 404
    if request.args.get("ver"):
        with open(caminho, encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/plain; charset=utf-8"}
    return send_file(caminho, as_attachment=True, download_name=f"diagnostico_{job_id}.txt", mimetype="text/plain")


@app.route("/job/<job_id>/download-timing-log", methods=["GET"])
def download_timing_log(job_id: str):
    """Baixa o log de tempo por etapa (`timing_log.json`) desse job —
    quanto tempo cada segmento levou pra buscar, baixar, normalizar, e
    quanto tempo as etapas de transcrição/concatenação/mixagem levaram.
    Disponível assim que a pré-busca de prévias terminar (não precisa
    esperar o vídeo final ficar pronto) — útil pra identificar gargalos
    mesmo se o job ainda estiver rodando ou tiver falhado no meio.
    """
    if not _JOBS.get(job_id):
        return "Job não encontrado.", 404
    log_path = os.path.join(_job_dir(job_id), "timing_log.json")
    if not os.path.exists(log_path):
        return "Log de tempo ainda não disponível pra esse job.", 404
    return send_file(log_path, as_attachment=True, download_name=f"timing_log_{job_id}.json", mimetype="application/json")


# --------------------------------------------------------------------- #
# Capturar página — print + mapa de blocos de texto + galeria de imagens
# de QUALQUER site (ver webpage_capture.py), com um clipe de vídeo
# animado (rolagem ou foco num trecho, ver webpage_animator.py) gerado
# a partir do resultado. O clipe final é um .mp4 comum — use como
# origem manual (upload/override) de um segmento no editor pra encaixar
# na timeline na posição que quiser.
# --------------------------------------------------------------------- #

@app.route("/capturar-pagina", methods=["GET"])
def capturar_pagina_page():
    return render_template("capturar_pagina.html", capturas=list(reversed(list(_CAPTURAS_PAGINA.values()))))


@app.route("/capturar-pagina", methods=["POST"])
def capturar_pagina_submit():
    url = request.form.get("url", "").strip()
    if not url:
        return jsonify({"erro": "Informe a URL da página."}), 400
    if not (url.startswith("http://") or url.startswith("https://")):
        return jsonify({"erro": "A URL precisa começar com http:// ou https://."}), 400

    captura_id = uuid.uuid4().hex[:12]
    pasta = os.path.join(CAPTURAS_DIR, captura_id)
    _CAPTURAS_PAGINA[captura_id] = {
        "id": captura_id, "url": url, "status": "capturando", "erro": None,
        "criado_em": time.time(), "pasta": pasta,
    }

    def _run_captura():
        estado = _CAPTURAS_PAGINA[captura_id]
        try:
            resultado = capturar_pagina(url, pasta, headless=not load_site_config().get("browser_visible", False))
            estado.update({
                "status": "pronto",
                "titulo": resultado["titulo"],
                "blocos": resultado["blocos"],
                "galeria": resultado["galeria"],
                "screenshot_path": resultado["screenshot_path"],
            })
        except WebpageCaptureError as exc:
            estado["status"] = "erro"
            estado["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            estado["status"] = "erro"
            estado["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"

    _thread_com_aviso(_run_captura, lambda: _CAPTURAS_PAGINA.get(captura_id), "🖼️ Captura de " + url[:60],
                      f"/capturar-pagina/{captura_id}", "captura", ao_fim=lambda: _historico_salvar(CAPTURAS_DIR, _CAPTURAS_PAGINA.get(captura_id)))
    return jsonify({"ok": True, "captura_id": captura_id})


@app.route("/capturar-pagina/<captura_id>/status", methods=["GET"])
def capturar_pagina_status(captura_id: str):
    estado = _CAPTURAS_PAGINA.get(captura_id)
    if not estado:
        return jsonify({"erro": "captura não encontrada"}), 404
    return jsonify({
        "status": estado["status"], "erro": estado.get("erro"),
        "titulo": estado.get("titulo"),
        "quantidade_blocos": len(estado.get("blocos") or []),
        "quantidade_galeria": len(estado.get("galeria") or []),
    })


@app.route("/capturar-pagina/<captura_id>", methods=["GET"])
def capturar_pagina_detalhe(captura_id: str):
    estado = _CAPTURAS_PAGINA.get(captura_id)
    if not estado:
        return "Captura não encontrada.", 404
    return render_template("capturar_pagina_detalhe.html", captura=estado)


@app.route("/capturar-pagina/<captura_id>/screenshot", methods=["GET"])
def capturar_pagina_screenshot(captura_id: str):
    estado = _CAPTURAS_PAGINA.get(captura_id)
    if not estado or not estado.get("screenshot_path"):
        return "Captura não encontrada.", 404
    return send_file(estado["screenshot_path"], mimetype="image/png")


@app.route("/capturar-pagina/<captura_id>/galeria/<nome_arquivo>", methods=["GET"])
def capturar_pagina_galeria_arquivo(captura_id: str, nome_arquivo: str):
    estado = _CAPTURAS_PAGINA.get(captura_id)
    if not estado:
        return "Captura não encontrada.", 404
    safe_name = secure_filename(nome_arquivo)
    caminho = os.path.join(estado["pasta"], "galeria", safe_name)
    if not os.path.exists(caminho):
        return "Imagem não encontrada.", 404
    return send_file(caminho)


@app.route("/capturar-pagina/<captura_id>/renderizar", methods=["POST"])
def capturar_pagina_renderizar(captura_id: str):
    estado = _CAPTURAS_PAGINA.get(captura_id)
    if not estado or estado["status"] != "pronto":
        return jsonify({"erro": "Captura não encontrada ou ainda não terminou."}), 404

    modo = request.form.get("modo", "scroll").strip()
    try:
        duracao = float(request.form.get("duracao", 8))
    except (TypeError, ValueError):
        return jsonify({"erro": "Duração inválida."}), 400

    kwargs: Dict[str, Any] = {"modo": modo, "duracao": duracao}
    if modo == "scroll":
        kwargs["direcao_scroll"] = request.form.get("direcao_scroll", "baixo").strip()
    elif modo == "foco":
        bloco_id = request.form.get("bloco_id", "").strip()
        bloco = next((b for b in estado["blocos"] if b["id"] == bloco_id), None)
        if not bloco:
            return jsonify({"erro": f"Bloco {bloco_id!r} não encontrado nessa captura."}), 400
        kwargs["bloco"] = bloco
        efeito = request.form.get("efeito", "").strip()
        if efeito:
            kwargs["efeito"] = efeito
        try:
            kwargs["zoom_foco"] = float(request.form.get("zoom_foco", 1.4))
        except (TypeError, ValueError):
            pass

    clipes_dir = os.path.join(estado["pasta"], "clipes")
    os.makedirs(clipes_dir, exist_ok=True)
    nome_clipe = f"clipe_{uuid.uuid4().hex[:8]}.mp4"
    output_path = os.path.join(clipes_dir, nome_clipe)

    try:
        renderizar_clipe_pagina(estado["screenshot_path"], output_path, **kwargs)
    except VideoAssemblyError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada ao renderizar: {exc}"}), 500

    # Registra o clipe gerado na lista PERSISTENTE da captura -- antes
    # só devolvíamos o link uma vez na resposta do fetch(), sem guardar
    # em lugar nenhum: gerar um segundo clipe (outro bloco/modo) fazia
    # o primeiro "sumir" da tela (o arquivo continuava no disco, mas
    # não tinha como redescobrir ele pela interface depois de recarregar
    # a página). Agora fica listado e reaproveitável — inclusive pra
    # importar direto pro editor (ver /job/<job_id>/importar-biblioteca).
    descricao_partes = [f"modo: {modo}"]
    if modo == "foco" and kwargs.get("bloco"):
        descricao_partes.append(f"foco em: {kwargs['bloco']['texto'][:40]}")
    elif modo == "scroll":
        descricao_partes.append(f"direção: {kwargs.get('direcao_scroll')}")
    clipe_registrado = {
        "id": nome_clipe, "arquivo": nome_clipe, "caminho": output_path,
        "modo": modo, "duracao": duracao, "descricao": "; ".join(descricao_partes),
        "criado_em": time.time(),
    }
    estado.setdefault("clipes_gerados", []).append(clipe_registrado)

    return jsonify({"ok": True, "clipe_url": url_for("capturar_pagina_clipe", captura_id=captura_id, nome_arquivo=nome_clipe)})


@app.route("/capturar-pagina/<captura_id>/clipe/<nome_arquivo>", methods=["GET"])
def capturar_pagina_clipe(captura_id: str, nome_arquivo: str):
    estado = _CAPTURAS_PAGINA.get(captura_id)
    if not estado:
        return "Captura não encontrada.", 404
    safe_name = secure_filename(nome_arquivo)
    caminho = os.path.join(estado["pasta"], "clipes", safe_name)
    if not os.path.exists(caminho):
        return "Clipe não encontrado.", 404
    return send_file(caminho, mimetype="video/mp4")


# --------------------------------------------------------------------- #
# Cortar do YouTube — cola um ou vários links, define os trechos (com
# descrição opcional) de cada um, escolhe a qualidade, e baixa+corta
# tudo de uma vez — zip final com os clipes + um info.json (título
# original, link, e os trechos de cada vídeo). Ver youtube_clipper.py.
# --------------------------------------------------------------------- #

@app.route("/cortar-youtube", methods=["GET"])
def cortar_youtube_page():
    texto_inicial = ""
    if request.args.get("roteiro"):  # vindo da aba 📜 Roteiro do YouTube
        import roteiros_yt
        try:
            _p = roteiros_yt.carregar_projeto(BASE_DIR, request.args["roteiro"])
            _ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
            texto_inicial = roteiros_yt.texto_para_cortar(_p, _ids or None, do_original=request.args.get("original") == "1")
        except Exception:  # noqa: BLE001
            texto_inicial = ""
    return render_template(
        "cortar_youtube.html",
        qualidades=YT_QUALIDADES, qualidade_padrao=YT_QUALIDADE_PADRAO,
        jobs=list(reversed(list(_YT_CLIPPER_JOBS.values()))), texto_inicial=texto_inicial,
    )


@app.route("/cortar-youtube/buscar", methods=["GET"])
def cortar_youtube_buscar():
    termo = (request.args.get("termo") or "").strip()
    if not termo:
        return jsonify({"erro": "Digite um termo de busca."}), 400
    try:
        pular = int(request.args.get("pular") or 0) if str(request.args.get("pular") or "0").isdigit() else 0
        resultados = (buscar_videos_youtube(termo, quantidade=12, pular=pular) if pular  # ➕ "Buscar outros vídeos"
                      else buscar_videos_youtube(termo, quantidade=15))
    except YoutubeClipperError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada na busca:\n{traceback.format_exc()}"}), 500
    return jsonify({"ok": True, "resultados": resultados})


@app.route("/cortar-youtube", methods=["POST"])
def cortar_youtube_submit():
    corpo = request.get_json(silent=True) or {}
    itens = corpo.get("itens") or []
    qualidade = (corpo.get("qualidade") or YT_QUALIDADE_PADRAO).strip()

    if not itens:
        return jsonify({"erro": "Adicione pelo menos um vídeo com um trecho."}), 400

    job_id = uuid.uuid4().hex[:12]
    pasta = os.path.join(YT_CLIPPER_DIR, job_id)
    _YT_CLIPPER_JOBS[job_id] = {
        "id": job_id, "status": "processando", "log": "", "erro": None,
        "criado_em": time.time(), "quantidade_videos": len(itens), "qualidade": qualidade,
    }

    def _run():
        job = _YT_CLIPPER_JOBS[job_id]

        def log(linha: str) -> None:
            job["log"] += linha + "\n"

        try:
            resultado = yt_processar_pedido(itens, pasta, qualidade=qualidade, on_log=log)
            job["status"] = "pronto"
            job["zip_path"] = resultado["zip_path"]
            job["info"] = resultado["info"]
        except YoutubeClipperError as exc:
            job["status"] = "erro"
            job["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            job["status"] = "erro"
            job["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"

    _thread_com_aviso(_run, lambda: _YT_CLIPPER_JOBS.get(job_id), f"✂️ Cortes do YouTube ({len(itens)} vídeo(s))", f"/cortar-youtube#j-{job_id}", "cortar_youtube", ao_fim=lambda: _historico_salvar(YT_CLIPPER_DIR, _YT_CLIPPER_JOBS.get(job_id)))
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/cortar-youtube/achar-google", methods=["POST"])
def cortar_youtube_achar_google():
    """🤖🔎 (v84_88) Com link: a IA do Google assiste e acha o trecho da descrição. Sem link: o Claude busca no YouTube e
    escolhe os vídeos, e a IA do Google assiste cada um. Em segundo plano (tarefa)."""
    import tarefas_bg
    import yt_google
    corpo = request.get_json(silent=True) or {}
    url = str(corpo.get("url") or "").strip()
    descricao = " ".join(str(corpo.get("descricao") or "").split())[:600]
    if len(descricao) < 4:
        return jsonify({"erro": "Escreva o que a cena mostra."}), 400
    if url and not re.match(r"https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", url):
        return jsonify({"erro": "O link precisa ser do YouTube."}), 400
    motivo = yt_google.disponivel()
    if motivo:
        return jsonify({"erro": "🔎 IA do Google: " + motivo}), 400
    errados = []  # 🔁 olhar de novo: os momentos que ela deu e estavam errados
    for e in (corpo.get("errados") or [])[:20] if isinstance(corpo.get("errados"), list) else []:
        ini = yt_google.tempo_seg((e or {}).get("inicio")) if isinstance(e, dict) else None
        if ini is not None:
            fim = yt_google.tempo_seg(e.get("fim"))
            errados.append({"inicio": ini, "fim": fim if fim and fim > ini else ini + 5})
    if errados and not url:
        return jsonify({"erro": "Pra olhar de novo precisa do link do vídeo."}), 400
    perguntar = corpo.get("modo") == "perguntar"  # 🔎 pergunta pra IA do Google ONDE achar (ela indica link + tempo)

    def _tarefa(t):
        if perguntar:
            r = yt_google.perguntar_onde(descricao, log=t.progresso)
        elif url:
            t.progresso("🔁 a IA do Google está olhando o vídeo de novo…" if errados else "🔎 a IA do Google está assistindo o vídeo…")
            m = yt_google.momento_no_link(url, descricao, evitar=errados) if errados else yt_google.momento_no_link(url, descricao)
            r = dict(m or {"achou": False, "motivo": "a IA do Google não achou esse momento no vídeo"}, url=url)
        else:
            r = yt_google.achar(descricao, "", log=t.progresso)
        if r.get("achou"):
            r["inicio_txt"], r["fim_txt"] = yt_google.mmss(r["inicio"]), yt_google.mmss(r["fim"])
        for x in r.get("respostas") or []:  # 🧾 cada resposta da IA do Google (um por vídeo olhado)
            if x.get("achou"):
                x["inicio_txt"], x["fim_txt"] = yt_google.mmss(x["inicio"]), yt_google.mmss(x["fim"])
            else:
                x.setdefault("motivo", x.get("erro") or "não achou nesse vídeo")
        r.pop("video", None)
        r.pop("resultados", None)
        return r
    tid = tarefas_bg.iniciar("achar_google", ("🔎 Perguntar ao Google: " if perguntar else "🔁 Olhar de novo: " if errados
                                              else "🤖🔎 Achar trecho: ") + descricao[:70], _tarefa,
                             pagina="/cortar-youtube")
    return jsonify({"ok": True, "tarefa": tid})


@app.route("/cortar-youtube/interpretar", methods=["POST"])
def cortar_youtube_interpretar():
    """Texto colado (links + tempos + descrições opcionais) -> vídeos e trechos prontos."""
    from youtube_clipper import interpretar_texto
    corpo = request.get_json(silent=True) or request.form
    texto = str(corpo.get("texto") or "")
    if not texto.strip():
        return jsonify({"erro": "Cole um texto com pelo menos um link do YouTube."}), 400
    return jsonify({"ok": True, **interpretar_texto(texto)})


@app.route("/cortar-youtube/<job_id>/status", methods=["GET"])
def cortar_youtube_status(job_id: str):
    job = _YT_CLIPPER_JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "job não encontrado"}), 404
    return jsonify({
        "status": job["status"], "erro": job.get("erro"), "log": job.get("log", ""),
        "quantidade_videos": job.get("quantidade_videos"),
        "quantidade_clipes": sum(len(v["clipes"]) for v in job["info"]["videos"]) if job.get("info") else None,
    })


@app.route("/cortar-youtube/<job_id>/download", methods=["GET"])
def cortar_youtube_download(job_id: str):
    job = _YT_CLIPPER_JOBS.get(job_id)
    if not job or job.get("status") != "pronto" or not job.get("zip_path"):
        return "Esse job ainda não terminou ou não foi encontrado.", 404
    return send_file(job["zip_path"], as_attachment=True, download_name=f"clipes_youtube_{job_id}.zip")


# --------------------------------------------------------------------------
# Baixar de outras redes -- aba "Baixar de outras redes": baixa vídeos do
# TikTok, Instagram, Twitter/X, Facebook e Kwai (o YouTube já tem sua
# própria aba, "Cortar do YouTube") -- sempre na maior qualidade
# disponível -- e checa a qualidade máxima de um link sem baixar nada.
# --------------------------------------------------------------------------

@app.route("/redes-sociais", methods=["GET"])
def redes_sociais_page():
    return render_template("redes_sociais.html", jobs=list(reversed(list(_REDES_SOCIAIS_JOBS.values()))))


@app.route("/redes-sociais/checar-qualidade", methods=["POST"])
def redes_sociais_checar_qualidade():
    corpo = request.get_json(silent=True) or {}
    url = (corpo.get("url") or "").strip()
    if not url:
        return jsonify({"erro": "Informe o link do vídeo."}), 400
    try:
        resultado = checar_qualidade(url)
    except RedesSociaisError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada:\n{traceback.format_exc()}"}), 500
    return jsonify({"ok": True, "resultado": resultado})


@app.route("/redes-sociais", methods=["POST"])
def redes_sociais_submit():
    corpo = request.get_json(silent=True) or {}
    urls = [u.strip() for u in (corpo.get("urls") or []) if u and u.strip()]
    if not urls:
        return jsonify({"erro": "Adicione pelo menos um link."}), 400

    job_id = uuid.uuid4().hex[:12]
    pasta = os.path.join(REDES_SOCIAIS_DIR, job_id)
    _REDES_SOCIAIS_JOBS[job_id] = {
        "id": job_id, "status": "processando", "log": "", "erro": None,
        "criado_em": time.time(), "quantidade": len(urls),
    }

    def _run():
        job = _REDES_SOCIAIS_JOBS[job_id]

        def log(linha: str) -> None:
            job["log"] += linha + "\n"

        try:
            os.makedirs(pasta, exist_ok=True)
            baixados = []
            for i, url in enumerate(urls, start=1):
                dominio = redes_sociais.obter_dominio(url)
                nome_amigavel = redes_sociais.NOMES_AMIGAVEIS.get(dominio, dominio)
                log(f"[{i}/{len(urls)}] Baixando de {nome_amigavel}: {url}")
                subpasta = os.path.join(pasta, f"_tmp_{i}")
                caminho = redes_sociais.baixar_video(url, subpasta)
                nome_final = os.path.join(pasta, f"{i:02d}_{dominio}.mp4")
                shutil.move(caminho, nome_final)
                shutil.rmtree(subpasta, ignore_errors=True)
                baixados.append(nome_final)
                log("  ✓ Salvo.")

            zip_path = os.path.join(pasta, "videos.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for caminho in baixados:
                    zf.write(caminho, os.path.basename(caminho))
            job["status"] = "pronto"
            job["zip_path"] = zip_path
            job["quantidade_baixados"] = len(baixados)
        except RedesSociaisError as exc:
            job["status"] = "erro"
            job["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            job["status"] = "erro"
            job["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"

    _thread_com_aviso(_run, lambda: _REDES_SOCIAIS_JOBS.get(job_id), f"📲 Download de {len(urls)} vídeo(s) de redes", f"/redes-sociais#j-{job_id}", "redes", ao_fim=lambda: _historico_salvar(REDES_SOCIAIS_DIR, _REDES_SOCIAIS_JOBS.get(job_id)))
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/redes-sociais/<job_id>/status", methods=["GET"])
def redes_sociais_status(job_id: str):
    job = _REDES_SOCIAIS_JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "job não encontrado"}), 404
    return jsonify({
        "status": job["status"], "erro": job.get("erro"), "log": job.get("log", ""),
        "quantidade": job.get("quantidade"), "quantidade_baixados": job.get("quantidade_baixados"),
    })


@app.route("/redes-sociais/<job_id>/download", methods=["GET"])
def redes_sociais_download(job_id: str):
    job = _REDES_SOCIAIS_JOBS.get(job_id)
    if not job or job.get("status") != "pronto" or not job.get("zip_path"):
        return "Esse job ainda não terminou ou não foi encontrado.", 404
    return send_file(job["zip_path"], as_attachment=True, download_name=f"videos_{job_id}.zip")


# --------------------------------------------------------------------------
# Extrair links de canal -- aba "Extrair links de canal": lista título+link
# de todo Short (ou vídeo normal) de um canal do YouTube, sem baixar nada.
# --------------------------------------------------------------------------

@app.route("/extrair-links-canal", methods=["GET"])
def extrair_links_canal_page():
    return render_template("extrair_links_canal.html")


@app.route("/extrair-links-canal/buscar", methods=["POST"])
def extrair_links_canal_buscar():
    corpo = request.get_json(silent=True) or {}
    url = (corpo.get("url") or "").strip()
    tipo = (corpo.get("tipo") or "shorts").strip().lower()
    ordem = (corpo.get("ordem") or "mais_novos").strip().lower()
    if corpo.get("bg"):  # ⏳ em segundo plano: pode fechar a aba (v84_87)
        if not url:
            return jsonify({"erro": "Cole o link do canal primeiro."}), 400
        import tarefas_bg

        def _tarefa(t):
            t.progresso("listando os vídeos do canal…")
            return extrair_links_canal(url, tipo=tipo, ordem=ordem)
        tid = tarefas_bg.iniciar("links_canal", "🔗 Links de " + url[:70], _tarefa, pagina="/extrair-links-canal")
        return jsonify({"ok": True, "tarefa": tid})
    try:
        resultado = extrair_links_canal(url, tipo=tipo, ordem=ordem)
    except YoutubeClipperError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception:  # noqa: BLE001
        return jsonify({"erro": f"Falha inesperada:\n{traceback.format_exc()}"}), 500
    return jsonify({"ok": True, **resultado})


# --------------------------------------------------------------------------
# Transcrever -- aba "Transcrever": baixa um vídeo de qualquer fonte
# suportada (sempre na maior qualidade) e, opcionalmente, transcreve a
# fala com Whisper (idioma forçado ou automático + trechos com
# início/fim). Também aceita um vídeo enviado direto pelo navegador.
# Ferramenta AVULSA -- fora do pipeline de "Roteiro para Áudio".
# --------------------------------------------------------------------------

_TRANSCRICAO_AVULSA_ARQUIVOS_PERMITIDOS = {
    "video.mp4", "transcricao.txt", "transcricao.srt", "transcricao.json",
}


@app.route("/transcrever", methods=["GET"])
def transcrever_page():
    return render_template("transcrever.html", jobs=list(reversed(list(_TRANSCRICOES_AVULSAS_JOBS.values()))))


@app.route("/transcrever", methods=["POST"])
def transcrever_submit():
    url = (request.form.get("url") or "").strip()
    arquivo = request.files.get("arquivo")
    tem_arquivo = bool(arquivo and arquivo.filename)
    modo = (request.form.get("modo") or "transcrever").strip()
    whisper_model = (request.form.get("whisper_model") or "base").strip()
    idioma = (request.form.get("idioma") or "").strip() or None
    device = (request.form.get("device") or "auto").strip()
    max_height_bruto = (request.form.get("max_height") or "").strip()
    max_height = int(max_height_bruto) if max_height_bruto.isdigit() else None

    if bool(url) == tem_arquivo:
        return jsonify({"erro": "Informe um link OU envie um arquivo (não os dois, nem nenhum)."}), 400

    job_id = uuid.uuid4().hex[:12]
    pasta = os.path.join(TRANSCRICOES_AVULSAS_DIR, job_id)
    os.makedirs(pasta, exist_ok=True)

    arquivo_path = None
    if tem_arquivo:
        safe_name = secure_filename(arquivo.filename) or "video.mp4"
        arquivo_path = os.path.join(pasta, f"enviado_{safe_name}")
        arquivo.save(arquivo_path)

    _TRANSCRICOES_AVULSAS_JOBS[job_id] = {
        "id": job_id, "status": "processando", "log": "", "erro": None,
        "criado_em": time.time(), "modo": modo, "url": url or None,
    }

    def _run():
        job = _TRANSCRICOES_AVULSAS_JOBS[job_id]

        def log(linha: str) -> None:
            job["log"] += linha + "\n"

        try:
            resultado = ta_avulso.processar(
                pasta, url=url or None, arquivo_path=arquivo_path, modo=modo,
                whisper_model=whisper_model, idioma=idioma, device=device,
                max_height=max_height, on_log=log,
            )
            job["status"] = "pronto"
            job["resultado"] = resultado
        except ta_avulso.TranscreverAvulsoError as exc:
            job["status"] = "erro"
            job["erro"] = str(exc)
        except Exception:  # noqa: BLE001
            job["status"] = "erro"
            job["erro"] = f"Falha inesperada:\n{traceback.format_exc()}"

    _thread_com_aviso(_run, lambda: _TRANSCRICOES_AVULSAS_JOBS.get(job_id), "📝 " + ("Transcrição" if modo == "transcrever" else "Download") + " avulsa", f"/transcrever#j-{job_id}", "transcrever", ao_fim=lambda: _historico_salvar(TRANSCRICOES_AVULSAS_DIR, _TRANSCRICOES_AVULSAS_JOBS.get(job_id)))
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/transcrever/<job_id>/status", methods=["GET"])
def transcrever_status(job_id: str):
    job = _TRANSCRICOES_AVULSAS_JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "job não encontrado"}), 404
    return jsonify({
        "status": job["status"], "erro": job.get("erro"), "log": job.get("log", ""),
        "resultado": job.get("resultado"),
    })


@app.route("/transcrever/<job_id>/arquivo/<nome>", methods=["GET"])
def transcrever_arquivo(job_id: str, nome: str):
    job = _TRANSCRICOES_AVULSAS_JOBS.get(job_id)
    if not job or job.get("status") != "pronto" or nome not in _TRANSCRICAO_AVULSA_ARQUIVOS_PERMITIDOS:
        return "Arquivo não encontrado.", 404
    caminho = os.path.join(TRANSCRICOES_AVULSAS_DIR, job_id, nome)
    if not os.path.exists(caminho):
        return "Arquivo não encontrado.", 404
    return send_file(caminho, as_attachment=True, download_name=nome)


# --------------------------------------------------------------------- #
# 🎞️ Vídeos modelados (estilo + roteiro da IA + vozes + Flow -> Short pronto)
# --------------------------------------------------------------------- #
import modelados_rotas  # noqa: E402

modelados_rotas.registrar(app, BASE_DIR, _JOBS, _save_state, _job_dir, load_site_config,
                          waveform=generate_waveform_image)

# 📜 Roteiro do YouTube (transcrição -> IA reescreve + lista as cenas -> tags/ads/CTA)
import roteiros_yt_rotas  # noqa: E402

roteiros_yt_rotas.registrar(app, BASE_DIR)

# 🛒 Vídeo de venda (produto -> materiais -> como vender -> roteiro -> voz -> editor)
import vendas_rotas  # noqa: E402

vendas_rotas.registrar(app, BASE_DIR)

# 🕵️ Modelos de vídeo (True Crime…): tema + fontes (matérias + imagens) -> roteiro -> voz -> editor
import dossies_rotas  # noqa: E402

dossies_rotas.registrar(app, BASE_DIR)
import fotos_roteiro  # noqa: E402  (📸 v84_127: a IA pergunta que fotos você tem e posiciona no roteiro)
fotos_roteiro.registrar(app, BASE_DIR)
import elenco as _elenco  # noqa: E402  (🎭 v84_128: rostos e idades das fotos pro pod)
_elenco.registrar(app, BASE_DIR)
import piloto as _piloto  # noqa: E402  (🚀 v84_157: piloto automático do Modelo de vídeo)
_piloto.registrar(app, BASE_DIR)
import navegador_imagens as _nav_img  # noqa: E402  (🧲 v84_150: Brave do site + userscript que manda os links)
_nav_img.registrar(app, BASE_DIR)
import pesquisa_rotas as _pesquisa_rotas  # noqa: E402  (📰 v84_165: buscador de casos e notícias)
_pesquisa_rotas.registrar(app, BASE_DIR)
import marca_rotas as _marca_rotas  # noqa: E402  (🎨 v84_168: identidade visual — imagens 100% IA na marca)
_marca_rotas.registrar(app, BASE_DIR)


@app.after_request
def _cors_das_guias(resp):  # 🧲 o script no Google manda os links (fallback com fetch, sem GM_xmlhttpRequest)
    if request.path in ("/navegador-imagens/aba", "/navegador-imagens/fechar") or (request.path.startswith("/modelos-video/") and any(
            k in request.path for k in ("/fotos-roteiro/link", "/fotos-roteiro/guia-feita", "/fotos-roteiro/guias"))):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp

# 🖼 thumbnails no Google Flow + 🎙 adaptar o roteiro pro TTS por idioma (v84_96)
import thumbs_tts_rotas  # noqa: E402

thumbs_tts_rotas.registrar(app, BASE_DIR)

# 📺 perfis do canal: biblioteca de vídeos de intro / inscreva-se / venda / final (v84_101)
import perfis_canal_rotas  # noqa: E402

perfis_canal_rotas.registrar(app, BASE_DIR)

import guia as _guia  # noqa: E402
_guia.registrar(app, BASE_DIR)
import ia_rotas as _ia_rotas  # noqa: E402  🤖 IA nas buscas e modelos (v84_53)
_ia_rotas.registrar(app, BASE_DIR)
import analisador_rotas as _analisador_rotas  # noqa: E402  (📊 Analisador de canal + ⛏ Niche Miner)
_analisador_rotas.registrar(app, BASE_DIR)
import runpod_gerador as _runpod  # noqa: E402  🟣 Runpod: mídias geradas, saldo e teste (v84_116)
_runpod.registrar(app)


# --------------------------------------------------------------------- #
# 🏭 Produção no pod (v84_122): roteiros → narração/transcrição/imagens no pod → projeto com cenas ⏳ pendentes
# --------------------------------------------------------------------- #
def _registrar_narracao_do_pod(item: dict, lote: dict, wav: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A narração que veio do pod vira uma geração do 🎙️ Gerador de voz, feita do MESMO jeito: legenda com o texto do
    roteiro nos tempos do Whisper, chamadas ([[INSCREVA]]/[[VENDA]]), capítulos do roteiro, 📜 Histórico e o .zip
    (narracao.wav + legenda.srt + info.json + chamadas.json)."""
    import chamadas as _ch
    import legenda_texto as _lt
    os.makedirs(VOZES_DIR, exist_ok=True)
    gv_id = uuid.uuid4().hex
    output_path = os.path.join(VOZES_DIR, f"{gv_id}.wav")
    shutil.copyfile(wav, output_path)
    texto = item.get("texto_legenda") or item.get("texto") or ""  # 🎭 v84_180: várias vozes → a legenda sem as tags
    perfil = item.get("perfil") or ""
    status: Dict[str, Any] = {
        "running": False, "log": "🏭 Produção no pod: narrado e transcrito no pod.\n", "erro": None, "pronto": True,
        "engine": item.get("motor") or "chatterbox", "resultado_filename": os.path.basename(output_path),
        "resultado_srt_filename": None, "idioma": item.get("idioma") or "pt", "idioma_origem": "escolhido",
        "criado_em": item.get("inicio") or time.time(), "iniciou_em": item.get("inicio"),
        "texto_inicio": " ".join(texto.split())[:90], "palavras": len(texto.split()),
        "voz": f"🖥️ pod · {perfil or 'voz padrão do modelo'}",
        "roteiro_id": item.get("origem_id") if item.get("origem") == "roteiro" else None,
        "dossie_id": item.get("origem_id") if item.get("origem") == "dossie" else None,
    }

    def log(linha: str) -> None:
        status["log"] += linha + "\n"

    try:
        segmentos, inf = _lt.com_texto(segments, texto)
        log(f"✍️ Legenda com o texto do roteiro ({inf['casadas']}% das palavras achadas no áudio).")
    except Exception:  # noqa: BLE001
        segmentos = segments
    if not any(sg.get("words") for sg in segmentos or []):
        segmentos = _lt.estimar(texto, get_audio_duration(output_path))
        log("⚠ Sem o tempo das palavras: legenda com tempos estimados.")
    palavras = [w for sg in segmentos for w in sg.get("words", [])]
    partes = _ch.dividir(texto)
    if any(p["tipo"] for p in partes):
        _salvar_chamadas_voz(status, output_path, _ch.alinhar(partes, palavras), log)
    leg = (lote.get("config") or {}).get("legenda") or {}
    n = int(leg.get("max_palavras") or 5)
    srt_texto = lg.gerar_srt(segmentos, modo=leg.get("modo") or "legenda", duracao_alvo_s=5.0, max_palavras=n,
                             palavras_por_linha=n)
    srt_path = os.path.splitext(output_path)[0] + ".srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_texto)
    status["resultado_srt_filename"] = os.path.basename(srt_path)
    log("Legenda gerada.")
    _capitulos_do_roteiro(status, output_path, palavras, log)
    _GERAR_VOZ_STATUS[gv_id] = status
    try:
        _hist_voz.registrar(VOZES_DIR, gv_id, status, voz=status["voz"])
    except Exception:  # noqa: BLE001
        pass
    zip_path = _zip_da_voz(gv_id, status)
    blocos = lg.parse_srt(srt_texto)
    return {"gv_id": gv_id, "zip": zip_path, "total": float(blocos[-1]["end"]) if blocos else float(segments[-1]["end"])}


def _criar_job_producao(item: dict, lote: dict, zip_path: str, resposta: dict, ficha: Optional[dict] = None) -> str:
    """Cria o projeto do editor pelo MESMO caminho de quem envia o .zip do Gerador de voz na página inicial
    (legenda pronta, idioma e projeto do info.json, chamadas) e depois "cola" o JSON das cenas."""
    cfg_lote = lote.get("config") or {}
    marca = {"lote": lote.get("id"), "item": item.get("id")}
    for jid, j in list(_JOBS.items()):  # 🔁 tentar de novo: reaproveita o projeto que ficou esperando o JSON
        if j.get("producao_pod") == marca and j.get("status") == "aguardando_json":
            return _colar_json_producao(jid, resposta)
    with open(zip_path, "rb") as f:
        dados = {"audio": (f, "narracao_e_legenda.zip"), "interval_seconds": str(cfg_lote.get("intervalo") or 5),
                 "ritmo_cenas": "livre", "providers": "runpod", "language": item.get("idioma") or "auto",
                 "formato": cfg_lote.get("orientacao") or "16:9"}
        with app.test_request_context("/transcribe", method="POST", data=dados, content_type="multipart/form-data"):
            resp = transcribe()
    m = re.search(r"/job/([0-9a-f]+)/", getattr(resp, "location", "") or "")
    if not m:
        raise RuntimeError("o site não aceitou o .zip da narração (veja a página inicial com esse .zip)")
    job_id = m.group(1)
    job = _JOBS[job_id]
    fim = time.time() + 180
    while job.get("status") == "transcrevendo" and time.time() < fim:
        time.sleep(0.2)
    if job.get("status") != "aguardando_json":
        raise RuntimeError(f"o projeto não ficou pronto ({job.get('status')}): {str(job.get('error') or '')[:300]}")
    job["nome_projeto"] = item.get("titulo") or ""
    job["producao_pod"] = {"lote": lote.get("id"), "item": item.get("id")}
    if ficha:
        job.setdefault("ia", {})["ficha"] = ficha
    _save_state(job_id)
    return _colar_json_producao(job_id, resposta)


def _colar_json_producao(job_id: str, resposta: dict) -> str:
    """Ajusta os tempos ao áudio do projeto (início 0, sem buracos, fim exato) e cola o JSON das cenas."""
    import cenas_lote
    job = _JOBS[job_id]
    resposta = cenas_lote.ajustar_tempos(resposta, float(job.get("total_duration") or 0))
    texto = json.dumps(resposta, ensure_ascii=False)
    try:
        parse_ai_response(texto, valid_providers=job["providers"] + _provider_do_projeto(job),
                          total_duration=job["total_duration"])
    except PromptBuilderError as exc:
        raise RuntimeError(f"o JSON das cenas não passou na validação do site: {exc}"[:500]) from None
    with app.test_request_context(f"/job/{job_id}/submit-json", method="POST", data={"ai_response": texto}):
        submit_json(job_id)
    if job.get("status") == "aguardando_json":
        raise RuntimeError("o JSON das cenas não passou na validação do site — veja o projeto " + job_id)
    return job_id


def pendentes_info(job: dict) -> Dict[str, Any]:
    """Quantas cenas ⏳ pendentes o projeto tem (e as fontes que dá pra escolher pra completar)."""
    pend = job.get("pending_segments") or []
    n = sum(1 for s in pend if s.get("provider") == "adiado")
    fontes = [p for p in DEFAULT_PROVIDERS if p not in ("adiado",)]
    return {"n": n, "fontes": fontes, "marcadas": [p for p in (job.get("providers_completar") or []) if p in fontes],
            "pod_refazer": len(_cenas_pod_para_refazer(job))}


app.jinja_env.globals["pendentes_info"] = pendentes_info


def _completar_pendentes(job_id: str, fontes: List[str]) -> Dict[str, Any]:
    """⏳ → fonte de verdade: a 🤖 IA escreve as buscas de cada cena pendente (e decide YouTube/foto real/IA, só entre
    as fontes escolhidas); sem IA, a busca em inglês que a 1ª etapa já escreveu vai pras fontes em rodízio. Depois
    busca só as prévias dessas cenas (as do pod e as que você já escolheu ficam)."""
    job = _JOBS.get(job_id)
    if not job:
        raise ValueError("Projeto não encontrado.")
    fontes = [p for p in fontes if p in DEFAULT_PROVIDERS and p != "adiado"]
    if not fontes:
        raise ValueError("Escolha pelo menos uma fonte.")
    if job.get("status") == "buscando_previas":
        raise ValueError("O projeto ainda está buscando prévias — espere terminar.")
    pend = job.get("pending_segments") or []
    idx = [k for k, d in enumerate(pend) if d.get("provider") == "adiado" and not d.get("override_source")]
    if not idx:
        raise ValueError("Não tem cena pendente neste projeto.")
    job["providers"] = list(dict.fromkeys(fontes + [p for p in (job.get("providers") or []) if p != "adiado"]))
    job["providers_completar"] = fontes
    segs = [_segmento_obj(d) for d in pend]
    # rodízio entre as fontes marcadas (bancos de vídeo primeiro); YouTube só quando a IA pede (busca precisa ser outra)
    _videos = [p for p in fontes if p not in PHOTO_ONLY_PROVIDERS_COMPLETAR and p not in ("youtube", "flow", "runpod")]
    _fotos = [p for p in fontes if p in PHOTO_ONLY_PROVIDERS_COMPLETAR]
    padrao_rodizio = (_videos + _fotos) or [p for p in fontes if p != "youtube"] or fontes
    novas: Dict[int, Dict[str, Any]] = {}
    import ia_servico
    if ia_servico.ativo("buscas"):
        try:
            import ia_midia
            info = job.setdefault("ia", {})
            blocos = [b for b in job.get("segments") or [] if (b.get("text") or "").strip()]
            roteiro = " ".join(str(b["text"]).strip() for b in blocos)
            if info.get("ficha") is None:
                info["ficha"] = ia_midia.ficha_visual(roteiro, job.get("nome_projeto") or "", job.get("language") or "", job=job_id)
            falas, _p = _falas_por_trecho(job, segs)
            novas = ia_midia.buscas_melhores([{"n": k + 1, "fala": falas[k], "visual": segs[k].visual,
                                               "antes": falas[k - 1] if k else "",
                                               "depois": falas[k + 1] if k + 1 < len(falas) else "",
                                               "query": segs[k].query} for k in idx], info.get("ficha"), roteiro, job=job_id)
        except Exception:  # noqa: BLE001 — sem IA: segue com a regra
            novas = {}
    usou_ia = 0
    for j, k in enumerate(idx):
        sg = segs[k]
        nb = novas.get(k + 1)
        sg.provider = padrao_rodizio[j % len(padrao_rodizio)]
        sg.media_type = "image" if sg.provider in PHOTO_ONLY_PROVIDERS_COMPLETAR else "video"
        mud: Dict[str, Any] = {}
        if nb:
            usou_ia += 1
            original = sg.query
            sg.query = nb["buscas"][0]
            sg.alternativas = [b for b in nb["buscas"][1:] + [original] if b and b != sg.query][:5]
            if nb.get("visual"):
                sg.visual = nb["visual"]
            if nb.get("midia") == "foto" and "pexels" in fontes and sg.provider not in PHOTO_ONLY_PROVIDERS_COMPLETAR:
                sg.provider, sg.media_type = "pexels", "image"
            mud = _rotear_trecho(job, sg, nb)
            if sg.provider in ("flow", "runpod"):
                sg.media_type = "image"
                sg.query = sg.visual or sg.query
        pend[k].update(provider=sg.provider, query=sg.query, media_type=sg.media_type,
                       alternativas=sg.alternativas, visual=sg.visual, **{x: v for x, v in mud.items() if x != "provider"})
    previas = list(job.get("segment_previews") or []) + [None] * len(pend)
    previas = previas[:len(pend)]
    for k in idx:
        previas[k] = None
    job["segment_previews"] = previas
    if any(pend[k].get("provider") == "youtube" for k in idx):  # 🎬 cenas que a IA mandou pro YouTube: já pesquisa
        _youtube_itens_sincronizar(job)
        _youtube_buscar_pendentes(job_id)
    _save_state(job_id)
    _fetch_previews(job_id, job, [_segmento_obj(d) for d in pend], retomar=True)
    return {"ok": True, "cenas": len(idx), "com_ia": usou_ia, "fontes": fontes}


PHOTO_ONLY_PROVIDERS_COMPLETAR = ("wikipedia", "bing", "brave", "yandex", "startpage", "google")


def _cenas_pod_para_refazer(job: dict) -> List[int]:
    """Cenas do pod (runpod) que viraram 🃏 cartão ou ficaram sem prévia (o juiz da IA trocava a imagem gerada por um
    cartão até a v84_123) — a imagem continua no cache, é só buscar de novo."""
    pend = job.get("pending_segments") or []
    pv = list(job.get("segment_previews") or [])
    out = []
    for k, d in enumerate(pend):
        if d.get("provider") != "runpod":
            continue
        o = d.get("override_source") or {}
        p = pv[k] if k < len(pv) else None
        if o.get("cartao") or d.get("cartao") or (p is not None and not (p or {}).get("ok")) or (p or {}).get("cartao"):
            if not o or o.get("cartao"):  # não mexe no que VOCÊ escolheu no editor
                out.append(k)
    return out


def _refazer_cenas_pod(job_id: str) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if not job:
        raise ValueError("Projeto não encontrado.")
    if job.get("status") == "buscando_previas":
        raise ValueError("O projeto ainda está buscando prévias — espere terminar.")
    idx = _cenas_pod_para_refazer(job)
    if not idx:
        raise ValueError("Nenhuma cena do pod pra refazer.")
    pend = job["pending_segments"]
    for k in idx:
        pend[k]["override_source"] = None
        pend[k].pop("cartao", None)
        pend[k]["media_type"] = "image"
    job["destaques"] = [d for d in job.get("destaques") or [] if not (d.get("origem") == "cartao" and d.get("trecho") in idx)]
    previas = (list(job.get("segment_previews") or []) + [None] * len(pend))[:len(pend)]
    for k in idx:
        previas[k] = None
    job["segment_previews"] = previas
    _save_state(job_id)
    _fetch_previews(job_id, job, [_segmento_obj(d) for d in pend], retomar=True)
    return {"ok": True, "cenas": len(idx)}


@app.route("/job/<job_id>/refazer-cenas-pod", methods=["POST"])
def refazer_cenas_pod_rota(job_id: str):
    try:
        return jsonify(_refazer_cenas_pod(job_id))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


# ------------------------------------------------------------------ 🕵️ projeto no editor (v84_141)
def _momentos_do_projeto(mod, p: dict) -> List[Dict[str, Any]]:
    """Os momentos planejados no roteiro do projeto (marcas [I3] / [M2 0:12-0:25]) → [{midia, trecho, inicio?, fim?, tipo}]."""
    out = []
    for m in mod.midias_para_editor(BASE_DIR, p):
        for u in m.get("usos") or []:
            if (u.get("trecho") or "").strip():
                out.append({"midia": m["id"], "trecho": u["trecho"], "inicio": u.get("inicio"), "fim": u.get("fim"),
                            "audio": bool(u.get("audio")), "tipo": m["tipo"]})
    return out


def info_projeto_editor(job: dict) -> Dict[str, Any]:
    """Pra caixa 🕵️ do editor: projeto ligado, quantos momentos/fotos, se dá pra desfazer."""
    out: Dict[str, Any] = {"tipo": "", "id": "", "nome": "", "momentos": 0, "midias": 0, "canal": "",
                           "encaixadas": sum(1 for d in job.get("pending_segments") or [] if d.get("_antes_material"))}
    if job.get("roteiro_id"):
        out.update(tipo="roteiro", id=job["roteiro_id"])
        try:
            import roteiros_yt
            out["nome"] = (roteiros_yt.carregar_projeto(BASE_DIR, job["roteiro_id"]).get("titulo") or "")[:80]
        except Exception:  # noqa: BLE001
            pass
    pj = _projeto_do_job(job)
    if pj:
        tipo, mod, p, _prov = pj
        out.update(tipo=tipo, id=p.get("id"), nome=(mod.nome_do_projeto(p) if hasattr(mod, "nome_do_projeto") else p.get("nome") or "")[:80])
        if tipo == "dossie":  # 🎨 v84_181: o canal (pacote) do modelo — botão 📦 Zip do canal
            out["canal"] = str((getattr(mod, "MODELOS", {}).get((p.get("config") or {}).get("modelo") or "") or {}).get("identidade_visual") or "")
        try:
            out["momentos"] = len(_momentos_do_projeto(mod, p))
            out["midias"] = len(mod.midias_para_editor(BASE_DIR, p))
        except Exception:  # noqa: BLE001
            pass
    return out


app.jinja_env.globals["info_projeto_editor"] = info_projeto_editor


@app.route("/job/<job_id>/ligar-projeto", methods=["POST"])
def ligar_projeto_rota(job_id: str):
    """📦 Liga (ou troca) o projeto do vídeo DEPOIS de criado: 🕵️ modelo de vídeo, 🛒 venda ou 📝 roteiro do YouTube."""
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"erro": "Projeto não encontrado."}), 404
    valor = str((request.get_json(silent=True) or {}).get("projeto") or "").strip()
    tipo, _, pid = valor.partition(":")
    if not valor:
        for _t, (_m, _p, ch, _r) in _PROJETOS_MIDIA.items():
            job.pop(ch, None)
        job.pop("roteiro_id", None)
        job.pop("roteiro_cenas", None)
    elif tipo == "roteiro":
        if not re.fullmatch(r"[0-9a-f]{6,40}", pid):
            return jsonify({"erro": "Roteiro inválido."}), 400
        job["roteiro_id"] = pid
        job.pop("roteiro_cenas", None)
    elif not _ligar_projeto(job, tipo, pid):
        return jsonify({"erro": "Não achei esse projeto."}), 404
    _save_state(job_id)
    return jsonify({"ok": True, **info_projeto_editor(job)})


def _encaixar_projeto(job_id: str, modo: str = "ia") -> Dict[str, Any]:
    """🕵️ Põe as fotos/vídeos REAIS do projeto ligado nos momentos que o roteiro planejou (marcas [I3]): acha a frase
    de cada marca na fala dos trechos e troca a mídia daquele trecho pela real. modo "ia" = só troca cena de IA
    (pod/Flow/Runpod), ⏳ pendente ou sem mídia; "tudo" = troca qualquer uma (menos as que já são do projeto).
    Guarda o que tinha antes em cada trecho (dá pra desfazer)."""
    import cenas_lote
    job = _JOBS.get(job_id)
    if not job:
        raise ValueError("Projeto não encontrado.")
    if job.get("status") == "buscando_previas":
        raise ValueError("O projeto ainda está buscando prévias — espere terminar.")
    pj = _projeto_do_job(job)
    if not pj:
        raise ValueError("Ligue um 🕵️ Modelo de vídeo (ou 🛒 venda) neste vídeo primeiro.")
    _t, mod, p, prov = pj
    momentos = _momentos_do_projeto(mod, p)
    if not momentos:
        raise ValueError("O roteiro do projeto não tem marcas de imagem [I…] — no Modelo de vídeo, use 📍 Posicionar.")
    pend = job.get("pending_segments") or []
    segs = [_segmento_obj(d) for d in pend]
    falas, _pal = _falas_por_trecho(job, segs)
    mapa = cenas_lote.cenas_dos_momentos([{"fala": f} for f in falas], momentos)
    por_id = {}
    for mo in momentos:
        por_id.setdefault(mo["midia"], []).append(mo)
    trocadas = []
    for k, mid in sorted(mapa.items()):
        d = pend[k]
        if d.get("provider") in ("produto", "material"):
            continue
        ia_ou_vazio = d.get("provider") in ("runpod", "flow", "adiado") or not d.get("override_source")
        if modo != "tudo" and not ia_ou_vazio:
            continue
        mo = next((x for x in por_id.get(mid, []) if x.get("inicio") is not None), por_id.get(mid, [{}])[0])
        d.setdefault("_antes_material", {kk: d.get(kk) for kk in ("provider", "query", "override_source", "media_type", "venda_midia")})
        d["provider"] = prov
        d["query"] = mid + (f"@{mo['inicio']}-{mo['fim']}" if mo.get("tipo") == "video" and mo.get("inicio") is not None
                            and mo.get("fim") is not None else "")
        d["override_source"] = None
        trocadas.append(k)
    if not trocadas:
        raise ValueError("Nenhum trecho pra trocar (os momentos caem em trechos que você já escolheu — use “trocar todas”).")
    _aplicar_produto(job, [pend[k] for k in trocadas])
    # 🌐 v84_160: foto que é print de SITE (veio com o link) → o quadro 🖥 Página animada naquele momento
    sites = {m["id"]: m for m in (p.get("midias") or []) if m.get("site_url")}
    paginas = 0
    if sites:
        import dp_editorial
        eds = [e for e in job.get("editoriais") or [] if e.get("origem") != "projeto_site"]
        for k, mid in sorted(mapa.items()):
            m = sites.get(mid)
            if not m or k >= len(pend):
                continue
            try:
                ini, fim = float(pend[k]["start"]), float(pend[k]["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if any(float(e["start"]) < fim and float(e["end"]) > ini for e in eds):
                continue  # já tem um quadro ali
            q = dp_editorial.normalizar({"tipo": "pagina", "start": ini, "end": max(fim, ini + 3.5), "url": m["site_url"],
                                         "site": m.get("site_dominio") or "", "titulo": (m.get("descricao") or "")[:120]},
                                        job.get("total_duration"))
            if q:
                q["origem"] = "projeto_site"
                eds.append(q)
                paginas += 1
        job["editoriais"] = sorted(eds, key=lambda e: float(e["start"]))
    previas = (list(job.get("segment_previews") or []) + [None] * len(pend))[:len(pend)]
    for k in trocadas:
        previas[k] = None
    job["segment_previews"] = previas
    _save_state(job_id)
    _fetch_previews(job_id, job, [_segmento_obj(d) for d in pend], retomar=True)
    return {"ok": True, "trocadas": len(trocadas), "momentos": len(momentos), "achados": len(mapa), "paginas": paginas}


def _desfazer_encaixe(job_id: str) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if not job:
        raise ValueError("Projeto não encontrado.")
    pend = job.get("pending_segments") or []
    idx = [k for k, d in enumerate(pend) if d.get("_antes_material")]
    if not idx:
        raise ValueError("Nada pra desfazer.")
    job["editoriais"] = [e for e in job.get("editoriais") or [] if e.get("origem") != "projeto_site"]
    previas = (list(job.get("segment_previews") or []) + [None] * len(pend))[:len(pend)]
    for k in idx:
        pend[k].update(pend[k].pop("_antes_material"))
        previas[k] = None
    job["segment_previews"] = previas
    _save_state(job_id)
    _fetch_previews(job_id, job, [_segmento_obj(d) for d in pend], retomar=True)
    return {"ok": True, "voltaram": len(idx)}


@app.route("/job/<job_id>/encaixar-projeto", methods=["POST"])
def encaixar_projeto_rota(job_id: str):
    corpo = request.get_json(silent=True) or {}
    try:
        if corpo.get("desfazer"):
            return jsonify(_desfazer_encaixe(job_id))
        return jsonify(_encaixar_projeto(job_id, "tudo" if corpo.get("modo") == "tudo" else "ia"))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


@app.route("/job/<job_id>/completar-pendentes", methods=["POST"])
def completar_pendentes_rota(job_id: str):
    corpo = request.get_json(silent=True) or {}
    fontes = corpo.get("fontes") or request.form.getlist("fontes")
    try:
        return jsonify(_completar_pendentes(job_id, [str(f) for f in fontes]))
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 400


import producao_pod as _producao  # noqa: E402
import producao_pod_rotas as _producao_rotas  # noqa: E402

_producao.configurar(_criar_job_producao, _registrar_narracao_do_pod)
_producao_rotas.registrar(app, BASE_DIR)
import animar_flow as _animar  # noqa: E402  🎞 animar cenas de imagem com o Google Flow (v84_182)
_animar.registrar(app, _JOBS.get, _save_state, _job_dir,
                  lambda job: _falas_por_trecho(job, job.get("pending_segments") or [])[0],
                  _seg_estudio, _orientacao_do_job, lambda job: str(job.get("language") or ""))
import personagens_pod_rotas as _personagens_rotas  # noqa: E402  🧍 poses PNG das personagens no pod (v84_183)
_personagens_rotas.registrar(app, BASE_DIR)
import conteudo_ia as _conteudo_ia  # noqa: E402  🤖 selo nas cenas geradas por IA (v84_145)
_conteudo_ia.registrar(app, BASE_DIR, _JOBS, _save_state)
import clonar as _clonar  # noqa: E402  📑 clonar projeto (modelo de vídeo, roteiro, editor) (v84_146)
_clonar.registrar(app, BASE_DIR, _JOBS, _job_dir, _save_state)
try:
    _producao.garantir_runner()  # ▶ lote que estava rodando quando o site fechou: continua
except Exception:  # noqa: BLE001
    pass
import flow_estudio as _flow_estudio  # noqa: E402  🎬 aba Google Flow: gerar, galeria e 🧪 testar (v84_76)
_flow_estudio.registrar(app, BASE_DIR)
import ia_google_rotas as _ia_google_rotas  # noqa: E402  🔎 IA do Google (app à parte, porta 8852) (v84_86)
_ia_google_rotas.registrar(app, BASE_DIR)
import notificacoes as _notif  # noqa: E402  🔔 sininho + 🕘 histórico (v84_87)
_notif.registrar(app, BASE_DIR)
import tarefas_bg as _tarefas_bg  # noqa: E402  ⏳ tarefas de segundo plano genéricas (v84_87)
_tarefas_bg.registrar(app, BASE_DIR)
import espaco as _espaco  # noqa: E402  (🧹 Espaço em disco)


def _apagar_projeto_inteiro(job_id: str) -> None:
    _JOBS.pop(job_id, None)
    _PERF_LOGS.pop(job_id, None)
    _apagar_arquivos_do_projeto(job_id)


_espaco.registrar(app, BASE_DIR, lambda: _espaco.Contexto(
    BASE_DIR, _JOBS, lambda j: j.get("status") in _STATUS_EM_ANDAMENTO, apagar_projeto=_apagar_projeto_inteiro))


def _texto_do_dossie(pid: Optional[str]) -> str:
    if not pid:
        return ""
    import dossies
    try:
        p = dossies.carregar(BASE_DIR, pid)
        texto = dossies.roteiro_para_voz(p)
        return _vozes_do_canal(p, texto)[0]
    except Exception:  # noqa: BLE001
        return ""


def _vozes_do_canal(p: Dict[str, Any], texto: str):
    """🎭 v84_173: canal com personagens — [mira|curiosa] vira a voz escolhida pra Mira com a emoção da fala.
    → (texto, faltam, é_multivoz)."""
    import dossies
    perfil = dossies.perfil_do_modelo((p.get("config") or {}).get("modelo"))
    if not perfil:
        return texto, [], False
    import canal_perfil
    cfg = p.get("config") or {}
    t, faltam = canal_perfil.converter_para_vozes(texto, perfil, cfg.get("vozes_personagens") or {},
                                                  usar_emocao=cfg.get("ia_emocao", True) is not False)
    return t, faltam, True


def _info_vozes_dossie(pid: Optional[str]) -> Dict[str, Any]:
    if not pid:
        return {}
    import dossies
    try:
        p = dossies.carregar(BASE_DIR, pid)
    except Exception:  # noqa: BLE001
        return {}
    _t, faltam, multi = _vozes_do_canal(p, dossies.roteiro_para_voz(p))
    return {"multivoz": multi, "faltam": faltam} if multi else {}


def _idioma_do_projeto(venda: Optional[str], dossie: Optional[str]) -> str:
    """Idioma de saída escolhido no projeto (🛒/🕵️) — o Gerar voz já abre nele."""
    import importlib
    for mod_nome, pid in (("vendas", venda), ("dossies", dossie)):
        if pid:
            try:
                return importlib.import_module(mod_nome).carregar(BASE_DIR, pid)["config"].get("idioma") or ""
            except Exception:  # noqa: BLE001
                return ""
    return ""


def _texto_da_venda(pid: Optional[str]) -> str:
    if not pid:
        return ""
    import vendas
    try:
        return vendas.roteiro_para_voz(vendas.carregar(BASE_DIR, pid))
    except Exception:  # noqa: BLE001
        return ""


def _texto_do_roteiro_yt(pid: Optional[str]) -> str:
    if not pid:
        return ""
    import roteiros_yt
    try:
        return roteiros_yt.roteiro_para_voz(roteiros_yt.carregar_projeto(BASE_DIR, pid))
    except Exception:  # noqa: BLE001
        return ""


def _padroes_excluidos_do_reloader() -> list:
    """Pastas que só guardam dados/arquivos gerados (nunca código-fonte)
    — não precisam disparar um reinício do reloader do modo debug, e
    excluir elas evita que o reloader fique cada vez mais lento
    conforme o site é usado (modelos de voz baixados, áudios/vídeos
    gerados, e os states de cada job só crescem com o uso)."""
    pastas_sem_codigo = [
        os.path.join(BASE_DIR, "outputs"),
        os.path.join(BASE_DIR, "jobs"),
        os.path.join(BASE_DIR, "narracoes"),
        os.path.join(BASE_DIR, "conversas"),
        os.path.join(BASE_DIR, "modelados"),
        os.path.join(BASE_DIR, "roteiros_yt"),
        os.path.join(BASE_DIR, "vendas"),
        os.path.join(BASE_DIR, "dossies"),
        os.path.join(BASE_DIR, "toolkit", "tts", "models"),  # inclui os perfis de voz salvos (models/perfis_de_voz)
    ]
    return [os.path.join(p, "*") for p in pastas_sem_codigo]


if __name__ == "__main__":
    print("=== Narração → Vídeo v84 — 🎞️ Vídeos modelados · 📜 Roteiro do YouTube · 🌐 idioma do .zip · Flow em abas ===", flush=True)
    # Porta 5050 por padrão (não 5000) de propósito: 5000 é a porta
    # padrão do servidor local do Anime Pexels Local — usar a mesma
    # aqui causaria "Address already in use" se os dois precisarem
    # rodar ao mesmo tempo na mesma máquina (o que é o caso normal, já
    # que o provedor "animepexels" depende do outro servidor estar de
    # pé). Pra mudar a porta, defina a variável de ambiente PORT antes
    # de rodar (ex: no Windows, `set PORT=5001 && python app.py`).
    port = int(os.environ.get("PORT", 5050))
    app.run(debug=True, host="0.0.0.0", port=port, threaded=True, exclude_patterns=_padroes_excluidos_do_reloader())
