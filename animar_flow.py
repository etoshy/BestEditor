"""
animar_flow.py — 🎞 Animar cenas com o Google Flow (v84_182)
=============================================================

No Estúdio (editor), uma cena de IMAGEM vira VÍDEO no Flow (image-to-video, frame de Início = a própria imagem):

  • 🎞 Animar com Flow (trecho selecionado) e a aba 🎞 Animar cenas (vários de uma vez);
  • ✨ Sugerir: a 🤖 IA olha as cenas de imagem e diz quais MAIS ganham com movimento (nota + motivo); você marca
    na lista e manda;
  • ✍ o prompt de movimento: a IA escreve a partir do PROMPT que gerou a imagem (cena de IA: pod/Flow/Runpod) ou do
    CONTEXTO da cena (fala, o que a imagem mostra — ela olha a miniatura); sem IA, uma regra simples. Dá pra editar;
  • 🚀 os pedidos entram no Flow em massa (várias contas em paralelo, fila que sobrevive a reiniciar o site); quando
    o vídeo volta, ele é CORTADO no tempo da cena (nunca passa do trecho) e já entra no lugar da imagem;
  • ⏮ ⏺ ⏭ qual parte do vídeo usar: início, meio, fim ou um ponto livre — sempre com a duração da cena; cena mais
    longa que o vídeo: o vídeo fica um pouco mais lento (até 1,6×) pra cobrir;
  • 🖼 / 🎬 voltar pra imagem (o frame) ou pro vídeo a qualquer hora, sem gerar de novo.

Tudo da animação fica no próprio trecho (`seg["animacao"]`, com um id — o trecho pode mudar de número quando você
divide/junta) e os arquivos em jobs/<id>/animar/.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

VEL_MAX = 1.6           # cena mais longa que o vídeo: até 1,6× mais lento
JANELAS = ("inicio", "meio", "fim", "livre")
JANELA_PADRAO = "inicio"  # o 1º frame do vídeo É a imagem da cena: a troca imagem → vídeo fica contínua
PROVEDORES_IA = ("runpod", "flow")
INTERVALO_SYNC = 6.0
ESTADOS_ESPERA = ("fila", "gerando", "parado")


class AnimarErro(Exception):
    pass


# o vigia (segundo plano) e as rotas mexem nos mesmos trechos/arquivos: um de cada vez (senão dois cortam o mesmo vídeo
# e um apaga o corte do outro)
_TRAVA_SYNC = threading.RLock()


# ------------------------------------------------------------------ que cena dá pra animar
def _preview(job: Dict[str, Any], i: int) -> Dict[str, Any]:
    pv = job.get("segment_previews") or []
    return pv[i] if i < len(pv) and isinstance(pv[i], dict) else {}


def e_imagem(job: Dict[str, Any], i: int) -> bool:
    """A cena mostra uma IMAGEM parada agora (ou mostrava, antes de virar animação)?"""
    seg = job["pending_segments"][i]
    an = seg.get("animacao") or {}
    if an.get("imagem"):
        return True
    ov = seg.get("override_source") or {}
    if ov.get("source") == "local_file":
        return ov.get("kind") == "image" or seg.get("media_type") == "image"
    return seg.get("media_type") == "image" or seg.get("provider") in PROVEDORES_IA


def em_uso(seg: Dict[str, Any]) -> bool:
    """O vídeo da animação é o que está no trecho agora?"""
    an = seg.get("animacao") or {}
    ov = seg.get("override_source") or {}
    if not an.get("corte") or ov.get("source") != "local_file":
        return False
    return (bool(an.get("id")) and ov.get("animacao") == an["id"]) or \
        os.path.normpath(str(ov.get("value") or "")) == os.path.normpath(an["corte"])


def _baixar(url: str, destino: str) -> str:
    import requests
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(destino, "wb") as f:
        f.write(r.content)
    return destino


def frame_do_trecho(job: Dict[str, Any], i: int, pasta: str) -> str:
    """A imagem da cena (vira o frame de Início no Flow): o arquivo escolhido no trecho, a imagem gerada (pod/Flow)
    guardada na prévia, ou a foto do banco baixada agora."""
    seg = job["pending_segments"][i]
    an = seg.get("animacao") or {}
    if an.get("imagem") and os.path.isfile(an["imagem"]):
        return an["imagem"]
    if not e_imagem(job, i):
        raise AnimarErro("Essa cena é vídeo — animar é pra cena de imagem.")
    ov = seg.get("override_source") or {}
    if ov.get("source") == "local_file" and ov.get("value") and os.path.isfile(ov["value"]) and ov.get("kind") != "video":
        return ov["value"]
    pv = _preview(job, i)
    if pv.get("thumbnail_path") and os.path.isfile(pv["thumbnail_path"]):
        return pv["thumbnail_path"]
    # 🖼 v84_208: imagem gerada no pod (🏭 Produção no pod / RunPod) — a prévia aponta pra "/runpod/midias/<arquivo>"
    # (link do próprio site, não http): é o arquivo no disco
    try:
        import runpod_gerador as rg
        for url in (pv.get("result_url"), pv.get("thumbnail_url"), pv.get("url")):
            c = rg.arquivo_local(url)
            if c and re.search(r"\.(jpe?g|png|webp)$", c, re.I):
                return c
        if seg.get("provider") in PROVEDORES_IA and seg.get("query"):  # pelo prompt da cena, no cache das geradas
            q = " ".join(str(seg["query"]).split())[:600]
            for reg in list(rg._cache().values())[::-1]:
                if isinstance(reg, dict) and reg.get("tipo") == "imagem" and reg.get("arquivo") \
                        and " ".join(str(reg.get("descricao") or "").split())[:600] == q:
                    c = os.path.join(rg.pasta(), "midias", reg["arquivo"])
                    if os.path.isfile(c):
                        return c
    except Exception:  # noqa: BLE001
        pass
    for url in (pv.get("result_url") if re.search(r"\.(jpe?g|png|webp)(\?|$)", str(pv.get("result_url") or ""), re.I) else None,
                pv.get("thumbnail_url")):
        if url and str(url).startswith(("http://", "https://")):
            os.makedirs(pasta, exist_ok=True)
            try:
                return _baixar(url, os.path.join(pasta, f"frame_{secrets.token_hex(4)}.jpg"))
            except Exception:  # noqa: BLE001
                continue
    raise AnimarErro("Não achei a imagem dessa cena no PC (espere a prévia carregar ou escolha a imagem no trecho).")


# ------------------------------------------------------------------ o prompt de movimento
_SYS_PROMPT = """You write the prompt for Google Flow (Veo) to ANIMATE a still image: the image is the START FRAME of an
~8-second clip that replaces it in a narrated YouTube video. Write ONLY what moves:
- the subject's natural action and the living details of the scene (smoke, water, fire, hair, cloth, leaves, light,
  crowd, vehicles, particles…), believable and coherent with the narration;
- exactly ONE camera move (slow push-in, gentle pan, slow parallax dolly, subtle orbit or a steady locked shot) —
  slow and subtle unless the narration is action;
- keep EXACTLY the same characters, faces, outfits, art style, colors, lighting and composition as the start frame;
  no new people or objects, no text, captions, logos or watermarks, no scene cut or transition;
- nobody talks or lip-syncs (the clip is muted; the narration plays over it); motion visible from the first second.
40 to 90 words, in English, present tense. Also return "resumo_pt": one short line in Portuguese saying what moves."""

_SYS_SUGERIR = """Você escolhe quais cenas de IMAGEM de um vídeo narrado de YouTube MAIS ganham se virarem um vídeo curto
animado (imagem → vídeo no Google Flow, ~8 s; cada animação custa crédito). Para cada cena dê:
- "nota" 0 a 10: alta quando há algo que se move naturalmente (ação, gente, animal, fogo, água, fumaça, céu, máquina,
  multidão), um momento forte/emocionante da narração, um gancho, uma revelação, ou uma cena longa que cansa parada;
  baixa para documento, mapa, texto, gráfico, retrato que só "olha", logotipo, cena curtinha (< 2,5 s);
- "motivo": uma linha em português;
- "movimento": em português, o que deveria se mexer (curto).
Espalhe: evite várias animações seguidas, a não ser que a sequência peça. Mantenha o "i" de cada cena."""


def _schema_prompt():
    from ia_midia import _S, _obj
    return _obj({"prompt": _S, "resumo_pt": _S})


def _schema_sugerir():
    from ia_midia import _I, _S, _lista, _obj
    return _obj({"cenas": _lista(_obj({"i": _I, "nota": _I, "motivo": _S, "movimento": _S}))})


def prompt_da_imagem(seg: Dict[str, Any]) -> str:
    """O prompt que GEROU a imagem (cena de IA) — no pod/Flow/Runpod a "busca" do trecho é o próprio prompt."""
    if seg.get("provider") in PROVEDORES_IA:
        return " ".join(str(seg.get("query") or "").split())[:1500]
    return ""


def prompt_regra(seg: Dict[str, Any], fala: str = "") -> str:
    base = prompt_da_imagem(seg) or " ".join(str(seg.get("visual") or seg.get("query") or fala or "").split())
    base = re.sub(r"\b(Avoid|Image \d+ is)\b.*", "", base, flags=re.S)[:320].strip()
    return (f"Animate this exact frame{': ' + base if base else ''}. Subtle natural motion in the scene, slow cinematic "
            "camera push-in, the same characters, composition, colors and art style as the start frame, no new elements, "
            "no text, no scene cut, nobody talking.")


def escrever_prompt(seg: Dict[str, Any], fala: str = "", antes: str = "", depois: str = "", frame: str = "",
                    idioma: str = "") -> Tuple[str, str, str]:
    """→ (prompt em inglês, resumo em português, quem escreveu: "ia" | "regra")."""
    import ia_servico as ia
    if ia.ativo("animar"):
        partes: List[Any] = []
        bl = ia.imagem_bloco(frame, largura=640) if frame and os.path.isfile(frame) else None
        if bl:
            partes.append(bl)
        txt = []
        pi = prompt_da_imagem(seg)
        if pi:
            txt.append(f"PROMPT THAT CREATED THIS IMAGE (AI image): {pi}")
        elif seg.get("visual") or seg.get("query"):
            txt.append(f"WHAT THE IMAGE SHOWS (search/description): {seg.get('visual') or ''} {seg.get('query') or ''}".strip())
        txt.append(f"NARRATION OF THIS SCENE{' (' + idioma + ')' if idioma else ''}: {fala[:600] or '(none)'}")
        if antes:
            txt.append(f"Narration just before: {antes[-300:]}")
        if depois:
            txt.append(f"Narration right after: {depois[:300]}")
        if not bl:
            txt.append("(The image itself could not be attached — rely on the prompt/description.)")
        partes.append({"type": "text", "text": "\n".join(txt)})
        try:
            with ia.rotulo("Animar com Flow: prompt"):
                r = ia.chamar("animar", _SYS_PROMPT, partes, _schema_prompt(), max_tokens=600)
        except Exception:  # noqa: BLE001
            r = None
        p = " ".join(str((r or {}).get("prompt") or "").split())
        if len(p.split()) >= 8:
            return p[:1500], " ".join(str((r or {}).get("resumo_pt") or "").split())[:200], "ia"
    return prompt_regra(seg, fala), "movimento sutil + aproximação lenta da câmera", "regra"


def escrever_prompts(job: Dict[str, Any], indices: List[int], pasta: str, falas: List[str], idioma: str = "",
                     paralelo: int = 3) -> Dict[int, Dict[str, str]]:
    """Os prompts de várias cenas de uma vez (3 em paralelo). Cena sem imagem/fora do lugar fica de fora (o enviar
    explica). → {índice: {"prompt", "resumo", "por"}}."""
    segs = job["pending_segments"]

    def um(i: int) -> Optional[Tuple[int, str]]:
        try:
            frame = frame_do_trecho(job, i, pasta)
        except AnimarErro:
            return None
        p, resumo, por = escrever_prompt(segs[i], falas[i] if i < len(falas) else "", falas[i - 1] if 0 < i <= len(falas) else "",
                                         falas[i + 1] if i + 1 < len(falas) else "", frame, idioma)
        return i, {"prompt": p, "resumo": resumo, "por": por}

    alvo = [i for i in dict.fromkeys(indices) if 0 <= i < len(segs)
            and (segs[i].get("animacao") or {}).get("estado") not in ESTADOS_ESPERA]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as ex:
        return {r[0]: r[1] for r in ex.map(um, alvo) if r}


def sugerir(job: Dict[str, Any], falas: List[str], maximo: int = 0) -> List[Dict[str, Any]]:
    """As cenas de imagem com nota (0–10), motivo e o que mexer — da IA (recurso "animar") ou de uma regra simples."""
    segs = job["pending_segments"]
    cands = [i for i in range(len(segs)) if e_imagem(job, i)]
    if not cands:
        return []
    import ia_servico as ia
    out: Dict[int, Dict[str, Any]] = {}
    if ia.ativo("animar"):
        linhas = []
        for i in cands[:300]:
            s = segs[i]
            dur = float(s["end"]) - float(s["start"])
            desc = prompt_da_imagem(s)[:220] or str(s.get("visual") or s.get("query") or "")[:160]
            linhas.append(f"[{i}] {dur:.1f}s · {'imagem de IA' if s.get('provider') in PROVEDORES_IA else 'foto'}: {desc} "
                          f"| FALA: {(falas[i] if i < len(falas) else '')[:260]}")
        try:
            with ia.rotulo("Animar cenas: sugerir"):
                r = ia.chamar("animar", _SYS_SUGERIR, "## CENAS\n" + "\n".join(linhas), _schema_sugerir(),
                              max_tokens=8000, timeout=180)
        except Exception:  # noqa: BLE001
            r = None
        for x in (r or {}).get("cenas") or []:
            try:
                i = int(x.get("i"))
            except (TypeError, ValueError):
                continue
            if i in cands:
                out[i] = {"i": i, "nota": max(0, min(10, int(x.get("nota") or 0))), "motivo": str(x.get("motivo") or "")[:200],
                          "movimento": str(x.get("movimento") or "")[:200], "por": "ia"}
    for i in cands:  # sem IA (ou o que ela pulou): imagem de IA e cena longa primeiro
        if i in out:
            continue
        s = segs[i]
        dur = float(s["end"]) - float(s["start"])
        nota = 3 + (2 if s.get("provider") in PROVEDORES_IA else 0) + min(3, int(dur // 2)) - (3 if dur < 2.5 else 0)
        out[i] = {"i": i, "nota": max(0, min(10, nota)), "motivo": f"imagem parada de {dur:.1f} s", "movimento": "", "por": "regra"}
    lista = sorted(out.values(), key=lambda x: (-x["nota"], x["i"]))
    return lista[:maximo] if maximo else lista


# ------------------------------------------------------------------ vídeo: duração, corte, usar / voltar
def duracao(caminho: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", caminho],
                       capture_output=True, text=True, timeout=30)
    import json
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise AnimarErro("Não consegui ler a duração do vídeo do Flow.")


def calcular_janela(dur_video: float, dur_cena: float, janela: str = JANELA_PADRAO, offset: float = 0.0) -> Tuple[float, float]:
    """→ (início no vídeo, velocidade). Sempre `dur_cena` de vídeo: cena maior que o vídeo = mais lento (até VEL_MAX)."""
    if dur_cena >= dur_video - 0.05:
        return 0.0, round(min(VEL_MAX, max(1.0, dur_cena / max(0.1, dur_video))), 3)
    folga = dur_video - dur_cena
    ini = {"inicio": 0.0, "meio": folga / 2, "fim": folga}.get(janela, max(0.0, min(folga, float(offset or 0))))
    return round(ini, 3), 1.0


def cortar(an: Dict[str, Any], dur_cena: float, pasta: str) -> str:
    """Corta o vídeo do Flow na janela escolhida, com a duração da cena, sem áudio. Guarda em an["corte"]."""
    ini, vel = calcular_janela(float(an["duracao_video"]), dur_cena, an.get("janela") or JANELA_PADRAO, an.get("offset") or 0)
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, f"{an['id']}_corte_{int(ini * 1000)}_{int(dur_cena * 1000)}_{int(vel * 100)}.mp4")
    if not (os.path.isfile(destino) and os.path.getsize(destino) > 0):
        filtro = [f"setpts={vel}*PTS"] if vel > 1.001 else []
        cmd = (["ffmpeg", "-y", "-loglevel", "error"] + (["-ss", f"{ini:.3f}"] if ini > 0 else []) + ["-i", an["video"]]
               + (["-vf", ",".join(filtro)] if filtro else []) + ["-t", f"{dur_cena:.3f}", "-an", "-c:v", "libx264",
                                                                   "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                                                                   "-movflags", "+faststart", destino])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not os.path.isfile(destino):
            raise AnimarErro(f"Não consegui cortar o vídeo: {(r.stderr or '')[-300:]}")
    antigo = an.get("corte")
    an.update(corte=destino, inicio_corte=ini, velocidade=vel, dur_corte=round(dur_cena, 3))
    if antigo and antigo != destino and os.path.isfile(antigo):
        try:
            os.remove(antigo)
        except OSError:
            pass
    return destino


def usar(seg: Dict[str, Any], modo: str) -> None:
    """modo "video" = o trecho mostra a animação · "imagem" = volta pro que era antes (a imagem/frame)."""
    an = seg.get("animacao") or {}
    if modo == "video":
        if not an.get("corte") or not os.path.isfile(an["corte"]):
            raise AnimarErro("A animação ainda não está pronta.")
        if not em_uso(seg):
            an["antes"] = {"override_source": seg.get("override_source"), "media_type": seg.get("media_type")}
        seg["override_source"] = {"source": "local_file", "value": an["corte"], "kind": "video", "animacao": an["id"]}
        seg["media_type"] = "video"
        an["usando"] = "video"
    else:
        antes = an.get("antes")
        if em_uso(seg):
            if antes is not None:
                seg["override_source"] = antes.get("override_source")
                seg["media_type"] = antes.get("media_type") or "image"
            else:  # sem o registro de antes: a imagem que foi animada
                seg["override_source"] = {"source": "local_file", "value": an.get("imagem"), "kind": "image"}
                seg["media_type"] = "image"
        an["usando"] = "imagem"
    seg["animacao"] = an


def reajustar(seg: Dict[str, Any], pasta: str) -> bool:
    """A cena mudou de tamanho depois (dividir/arrastar): corta de novo pra caber. → True se mudou."""
    an = seg.get("animacao") or {}
    if an.get("estado") != "pronto" or not an.get("video") or not os.path.isfile(an["video"]):
        return False
    dur = round(float(seg["end"]) - float(seg["start"]), 3)
    if abs(float(an.get("dur_corte") or 0) - dur) < 0.05 and an.get("corte") and os.path.isfile(an["corte"]):
        return False
    estava = em_uso(seg)
    cortar(an, dur, pasta)
    if estava:
        seg["override_source"] = {"source": "local_file", "value": an["corte"], "kind": "video", "animacao": an["id"]}
    return True


# ------------------------------------------------------------------ fila (Flow em massa)
def _lote():
    import flow_lote
    return flow_lote.lote()


def enviar(job: Dict[str, Any], indices: List[int], pasta: str, prompts: Optional[Dict[int, Any]] = None,
           falas: Optional[List[str]] = None, proporcao: str = "16:9", idioma: str = "") -> Dict[str, Any]:
    """Põe as cenas na fila do 🚀 Flow em massa (vídeo com o frame de Início) e liga o lote."""
    segs = job["pending_segments"]
    prompts = prompts or {}
    falas = falas or []
    itens, alvo, erros = [], [], []
    for i in sorted(set(int(x) for x in indices)):
        if not (0 <= i < len(segs)):
            continue
        seg = segs[i]
        an_velho = seg.get("animacao") or {}
        if an_velho.get("estado") in ESTADOS_ESPERA:
            erros.append(f"trecho {i + 1}: já está na fila")
            continue
        try:
            frame = frame_do_trecho(job, i, pasta)
        except AnimarErro as exc:
            erros.append(f"trecho {i + 1}: {exc}")
            continue
        v = prompts.get(i) if i in prompts else prompts.get(str(i))
        resumo, por = "", "voce"
        if isinstance(v, dict):  # escrito antes (escrever_prompts) pela IA ou pela regra
            resumo, por, v = str(v.get("resumo") or ""), str(v.get("por") or "ia"), v.get("prompt")
        p = " ".join(str(v or "").split())
        if not p:
            p, resumo, por = escrever_prompt(seg, falas[i] if i < len(falas) else "", falas[i - 1] if 0 < i <= len(falas) else "",
                                             falas[i + 1] if i + 1 < len(falas) else "", frame, idioma)
        an = {"id": an_velho.get("id") or secrets.token_hex(5), "estado": "fila", "prompt": p[:1500], "resumo": resumo,
              "prompt_por": por, "imagem": frame, "criado": time.time(), "janela": an_velho.get("janela") or JANELA_PADRAO,
              "offset": an_velho.get("offset") or 0, "msg": "na fila do Flow", "erro": None,
              "antes": an_velho.get("antes") if em_uso(seg) else None, "usando": an_velho.get("usando")}
        if an_velho.get("video"):  # animar de novo: a versão anterior continua até a nova chegar
            an["anterior"] = {k: an_velho.get(k) for k in ("video", "corte", "duracao_video", "prompt")}
        seg["animacao"] = an
        itens.append({"prompt": an["prompt"], "tipo": "video", "inicio_arquivo": frame, "origem": "animar"})
        alvo.append(seg)
    if not itens:
        raise AnimarErro("; ".join(erros) or "Nenhuma cena de imagem escolhida.")
    lote = _lote()
    novos = lote.adicionar(itens, proporcao=proporcao if proporcao in ("16:9", "9:16", "1:1", "4:3", "3:4") else "16:9")
    for seg, j in zip(alvo, novos):
        seg["animacao"]["flow_job"] = j["id"]
    aviso = iniciar_lote()
    return {"enviadas": len(novos), "erros": erros, "aviso": aviso}


def iniciar_lote() -> str:
    """Liga o Flow em massa (se já está rodando, os pedidos novos entram sozinhos). → aviso ("" = ok)."""
    try:
        _lote().iniciar()
        return ""
    except Exception as exc:  # noqa: BLE001 — Flow ocupado (aba Flow gerando), sem pendente…
        return f"o Flow em massa não ligou agora ({str(exc)[:200]}) — os pedidos ficam na fila; clique em ▶ Continuar"


def _arquivo_da_galeria(arquivo: str) -> str:
    import flow_estudio as FE
    return os.path.join(FE.pasta_galeria(), arquivo)


def sincronizar(job: Dict[str, Any], pasta: str) -> List[int]:
    """Olha a fila do Flow em massa e atualiza as animações deste projeto (vídeo pronto → baixa, corta e põe no
    trecho). → índices dos trechos que mudaram."""
    with _TRAVA_SYNC:
        return _sincronizar(job, pasta)


def _sincronizar(job: Dict[str, Any], pasta: str) -> List[int]:
    segs = job.get("pending_segments") or []
    esperando = [(i, s) for i, s in enumerate(segs) if (s.get("animacao") or {}).get("estado") in ESTADOS_ESPERA]
    mudou: List[int] = []
    if esperando:
        lote = _lote()
        with lote.trava:
            fila = {j["id"]: dict(j) for j in lote.fila}
            rodando, fim_msg = lote.rodando, lote.fim_msg
            st_contas = dict(lote.status_conta)
        for i, seg in esperando:
            an = seg["animacao"]
            j = fila.get(an.get("flow_job") or "")
            antes = (an.get("estado"), an.get("msg"), an.get("erro"))
            if j is None:
                an.update(estado="erro", erro="o pedido sumiu da fila do 🚀 Flow em massa (alguém limpou a fila?) — anime de novo")
            elif j["estado"] == "ok":
                vid = next((r for r in j.get("resultados") or [] if r.get("tipo") == "video"), None)
                origem = _arquivo_da_galeria(vid["arquivo"]) if vid else ""
                if not vid or not os.path.isfile(origem):
                    an.update(estado="erro", erro="o Flow terminou mas não veio vídeo")
                else:
                    try:
                        os.makedirs(pasta, exist_ok=True)
                        destino = os.path.join(pasta, f"{an['id']}_flow_{j['id']}.mp4")
                        shutil.copyfile(origem, destino)
                        an.update(video=destino, duracao_video=round(duracao(destino), 3), estado="pronto", erro=None,
                                  msg="✅ pronto", pronto_em=time.time(), conta=j.get("conta"), anterior=None)
                        cortar(an, float(seg["end"]) - float(seg["start"]), pasta)
                        usar(seg, "video")
                    except Exception as exc:  # noqa: BLE001
                        traceback.print_exc()
                        an.update(estado="erro", erro=f"o vídeo chegou mas não consegui usar: {str(exc)[:200]}")
            elif j["estado"] == "erro":
                an.update(estado="erro", erro=str(j.get("erro") or "o Flow falhou")[:300])
            elif j["estado"] in ("rodando", "convertendo"):
                an.update(estado="gerando", msg=f"🎬 gerando no Flow (conta “{j.get('conta')}”: {st_contas.get(j.get('conta'), '')})")
            elif not rodando:
                an.update(estado="parado", msg="⏸ o Flow em massa está parado" + (f": {fim_msg}" if fim_msg else "")
                          + " — clique em ▶ Continuar")
            else:
                pos = 1 + sum(1 for x in fila.values() if x["estado"] == "pendente" and x.get("criado", 0) < j.get("criado", 0))
                an.update(estado="fila", msg=f"⏳ na fila do Flow ({pos}º)")
            if (an.get("estado"), an.get("msg"), an.get("erro")) != antes:
                if an.get("estado") == "erro" and an.get("anterior") and an["anterior"].get("video"):
                    an.update({k: v for k, v in an["anterior"].items() if k != "prompt"}, estado="pronto",
                              msg="⚠ a nova animação falhou — ficou a anterior")
                mudou.append(i)
    for i, seg in enumerate(segs):  # cena que mudou de tamanho: corta de novo
        try:
            if reajustar(seg, pasta) and i not in mudou:
                mudou.append(i)
        except Exception:  # noqa: BLE001
            pass
    return mudou


def publico(seg: Dict[str, Any]) -> Dict[str, Any]:
    an = dict(seg.get("animacao") or {})
    an.pop("antes", None)
    an["em_uso"] = em_uso(seg)
    return an


# ------------------------------------------------------------------ vigia em segundo plano
_VIGIA: Dict[str, Any] = {"thread": None, "jobs": set()}
_TRAVA = threading.Lock()


def vigiar(job_id: str, obter: Callable[[str], Optional[Dict[str, Any]]], salvar: Callable[[str], None],
           pasta_de: Callable[[str], str]) -> None:
    """Enquanto houver animação esperando, sincroniza a cada INTERVALO_SYNC s (o vídeo entra no trecho mesmo com o
    editor fechado)."""
    with _TRAVA:
        _VIGIA["jobs"].add(job_id)
        t = _VIGIA.get("thread")
        if t and t.is_alive():
            return

        def _loop():
            while True:
                time.sleep(INTERVALO_SYNC)
                with _TRAVA:
                    jobs = list(_VIGIA["jobs"])
                if not jobs:
                    with _TRAVA:
                        if not _VIGIA["jobs"]:
                            _VIGIA["thread"] = None
                            return
                for jid in jobs:
                    job = obter(jid)
                    if not job:
                        with _TRAVA:
                            _VIGIA["jobs"].discard(jid)
                        continue
                    try:
                        if sincronizar(job, pasta_de(jid)):
                            salvar(jid)
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()
                    if not any((s.get("animacao") or {}).get("estado") in ("fila", "gerando")
                               for s in job.get("pending_segments") or []):
                        with _TRAVA:
                            _VIGIA["jobs"].discard(jid)

        t = threading.Thread(target=_loop, daemon=True, name="animar_flow")
        _VIGIA["thread"] = t
        t.start()


# ------------------------------------------------------------------ rotas
def registrar(app, obter: Callable[[str], Optional[Dict[str, Any]]], salvar: Callable[[str], None],
              job_dir: Callable[[str], str], falas_de: Callable[[Dict[str, Any]], List[str]],
              seg_estudio: Callable[[str, Dict[str, Any], int], Dict[str, Any]],
              proporcao_de: Callable[[Dict[str, Any]], str], idioma_de: Callable[[Dict[str, Any]], str]) -> None:
    from flask import jsonify, request, send_file

    def pasta(job_id: str) -> str:
        return os.path.join(job_dir(job_id), "animar")

    import functools

    def travado(fn):
        @functools.wraps(fn)
        def _f(*a, **k):
            with _TRAVA_SYNC:
                return fn(*a, **k)
        return _f

    def _job(job_id: str):
        job = obter(job_id)
        if not job or "pending_segments" not in job:
            return None
        return job

    def _indice(job: Dict[str, Any], i: int, aid: str = "") -> int:
        """O trecho pelo id da animação (o número pode ter mudado) ou pelo número."""
        if aid:
            for k, s in enumerate(job["pending_segments"]):
                if (s.get("animacao") or {}).get("id") == aid:
                    return k
        if 0 <= i < len(job["pending_segments"]):
            return i
        raise AnimarErro("Trecho inexistente.")

    def _resposta_trecho(job_id: str, job: Dict[str, Any], i: int) -> Dict[str, Any]:
        s = seg_estudio(job_id, job, i)
        return {"i": i, "animacao": publico(job["pending_segments"][i]), "override_source": s.get("override_source"),
                "media_type": s.get("media_type"), "_preview": s.get("_preview")}

    @app.route("/job/<job_id>/animar/estado", methods=["GET"])
    def animar_estado(job_id: str):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            if sincronizar(job, pasta(job_id)):
                salvar(job_id)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return jsonify({"erro": f"não consegui olhar a fila do Flow: {exc}"}), 500
        itens = [_resposta_trecho(job_id, job, i) for i, s in enumerate(job["pending_segments"]) if s.get("animacao")]
        esperando = any(x["animacao"].get("estado") in ESTADOS_ESPERA for x in itens)
        if esperando:
            vigiar(job_id, obter, salvar, pasta)
        try:
            import ia_servico
            ia_ok = ia_servico.ativo("animar")
        except Exception:  # noqa: BLE001
            ia_ok = False
        return jsonify({"itens": itens, "esperando": esperando, "ia": ia_ok,
                        "animaveis": [i for i in range(len(job["pending_segments"])) if e_imagem(job, i)],
                        "sugestoes": job.get("animar_sugestoes") or []})

    @app.route("/job/<job_id>/animar/sugerir", methods=["POST"])
    def animar_sugerir(job_id: str):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        lista = sugerir(job, falas_de(job))
        job["animar_sugestoes"] = lista
        salvar(job_id)
        return jsonify({"ok": True, "sugestoes": lista})

    @app.route("/job/<job_id>/animar/prompt/<int:i>", methods=["POST"])
    def animar_prompt(job_id: str, i: int):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        try:
            i = _indice(job, i)
            frame = frame_do_trecho(job, i, pasta(job_id))
        except AnimarErro as exc:
            return jsonify({"erro": str(exc)}), 400
        falas = falas_de(job)
        p, resumo, por = escrever_prompt(job["pending_segments"][i], falas[i] if i < len(falas) else "",
                                         falas[i - 1] if 0 < i <= len(falas) else "", falas[i + 1] if i + 1 < len(falas) else "",
                                         frame, idioma_de(job))
        return jsonify({"ok": True, "prompt": p, "resumo": resumo, "por": por})

    @app.route("/job/<job_id>/animar/enviar", methods=["POST"])
    def animar_enviar(job_id: str):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        d = request.get_json(silent=True) or {}
        try:
            indices = [int(x) for x in d.get("indices") or []]
            prompts = {int(k): str(v) for k, v in (d.get("prompts") or {}).items() if str(v).strip()}
        except ValueError as exc:
            return jsonify({"erro": str(exc)}), 400
        falas = falas_de(job)
        prompts.update(escrever_prompts(job, [i for i in indices if i not in prompts], pasta(job_id), falas, idioma_de(job)))
        try:
            with _TRAVA_SYNC:  # a IA já escreveu (fora da trava): aqui só põe na fila
                r = enviar(job, indices, pasta(job_id), prompts, falas, proporcao_de(job), idioma_de(job))
        except AnimarErro as exc:
            return jsonify({"erro": str(exc)}), 400
        salvar(job_id)
        vigiar(job_id, obter, salvar, pasta)
        return jsonify({"ok": True, **r, "itens": [_resposta_trecho(job_id, job, k) for k in indices
                                                     if 0 <= k < len(job["pending_segments"])
                                                     and job["pending_segments"][k].get("animacao")]})

    @app.route("/job/<job_id>/animar/continuar", methods=["POST"])
    def animar_continuar(job_id: str):
        aviso = iniciar_lote()
        return (jsonify({"erro": aviso}), 409) if aviso else jsonify({"ok": True})

    @app.route("/job/<job_id>/animar/<int:i>/usar", methods=["POST"])
    @travado
    def animar_usar(job_id: str, i: int):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        d = request.get_json(silent=True) or {}
        try:
            i = _indice(job, i, str(d.get("id") or ""))
            usar(job["pending_segments"][i], "video" if d.get("modo") == "video" else "imagem")
        except AnimarErro as exc:
            return jsonify({"erro": str(exc)}), 400
        salvar(job_id)
        return jsonify({"ok": True, **_resposta_trecho(job_id, job, i)})

    @app.route("/job/<job_id>/animar/<int:i>/janela", methods=["POST"])
    @travado
    def animar_janela(job_id: str, i: int):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        d = request.get_json(silent=True) or {}
        try:
            i = _indice(job, i, str(d.get("id") or ""))
            seg = job["pending_segments"][i]
            an = seg.get("animacao") or {}
            if an.get("estado") != "pronto" or not an.get("video"):
                raise AnimarErro("A animação ainda não está pronta.")
            j = d.get("janela") if d.get("janela") in JANELAS else "livre"
            an.update(janela=j, offset=max(0.0, float(d.get("offset") or 0)))
            cortar(an, float(seg["end"]) - float(seg["start"]), pasta(job_id))
            seg["animacao"] = an
            usar(seg, "video")  # escolher a parte = usar o vídeo (o "antes" continua sendo a imagem)
        except (AnimarErro, ValueError) as exc:
            return jsonify({"erro": str(exc)}), 400
        salvar(job_id)
        return jsonify({"ok": True, **_resposta_trecho(job_id, job, i)})

    @app.route("/job/<job_id>/animar/<int:i>/cancelar", methods=["POST"])
    @travado
    def animar_cancelar(job_id: str, i: int):
        job = _job(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        d = request.get_json(silent=True) or {}
        try:
            i = _indice(job, i, str(d.get("id") or ""))
        except AnimarErro as exc:
            return jsonify({"erro": str(exc)}), 400
        seg = job["pending_segments"][i]
        an = seg.get("animacao") or {}
        if an.get("estado") in ESTADOS_ESPERA and an.get("flow_job"):
            try:
                _lote().remover(an["flow_job"])
            except Exception as exc:  # noqa: BLE001 — já está gerando
                return jsonify({"erro": f"não deu pra tirar da fila: {exc}"}), 400
        if em_uso(seg):
            usar(seg, "imagem")
        if an.get("anterior") and an["anterior"].get("video"):
            an.update({k: v for k, v in an["anterior"].items() if k != "prompt"}, estado="pronto", msg="", anterior=None)
            seg["animacao"] = an
        else:
            seg.pop("animacao", None)
        salvar(job_id)
        return jsonify({"ok": True, **_resposta_trecho(job_id, job, i)})

    @app.route("/job/<job_id>/animar/<int:i>/video", methods=["GET"])
    def animar_video(job_id: str, i: int):
        job = _job(job_id)
        if not job:
            return "Projeto não encontrado.", 404
        try:
            i = _indice(job, i, request.args.get("id") or "")
        except AnimarErro:
            return "Trecho inexistente.", 404
        an = job["pending_segments"][i].get("animacao") or {}
        cam = an.get("video") if request.args.get("qual") == "completo" else an.get("corte")
        if request.args.get("qual") == "frame":
            cam = an.get("imagem")
        if not cam or not os.path.isfile(cam):
            return "Sem arquivo.", 404
        return send_file(cam, max_age=0)
