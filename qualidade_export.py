"""
Qualidade da exportação (escolhida no Estúdio ao montar):

  normal  — como sempre foi (mais rápido)
  alta    — etapas intermediárias com CRF 17 + passe final CRF 18 / preset medium
  maxima  — etapas intermediárias com CRF 14 + passe final CRF 15 / preset slow

A resolução (480p…2160p) é a `export_quality` do job (site_config).
As etapas intermediárias (clipes, cenas, efeitos, destaques) passam por
`ajustar(cmd)`, que põe o CRF da qualidade escolhida nos comandos libx264.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Dict, List, Optional

QUALIDADES: Dict[str, Dict] = {
    "rapida": {"nome": "⚡ Rápida (pra conferir — mais leve na qualidade)", "crf": None, "preset": None, "crf_inter": None, "audio": None,
               "preset_inter": "ultrafast"},
    "normal": {"nome": "Normal", "crf": None, "preset": None, "crf_inter": None, "audio": None},
    "alta": {"nome": "Alta", "crf": 18, "preset": "medium", "crf_inter": 17, "audio": "192k"},
    "maxima": {"nome": "Máxima (arquivo maior, demora mais)", "crf": 15, "preset": "slow", "crf_inter": 14, "audio": "256k"},
}
RESOLUCOES = ["480p", "720p", "1080p", "1440p", "2160p"]
_estado = {"crf_inter": None, "preset_inter": None}
_trava = threading.Lock()

# ------------------------------------------------------------------ encoder de vídeo da placa (GPU)
# NVIDIA (NVENC), Intel (Quick Sync) ou AMD (AMF) codificam H.264 várias vezes mais
# rápido que o libx264 na CPU. Detecta uma vez (um teste de 1 quadro) e, se a placa
# falhar num comando (limite de sessões, driver), aquele comando roda de novo na CPU.
# Config: site_config "encoder_video" = "auto" (padrão) | "cpu" | "h264_nvenc" | "h264_qsv" | "h264_amf".
_HW_CANDIDATOS = ["h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"]
_hw = {"testado": False, "encoder": None, "pedido": None}
_sessoes_hw = threading.BoundedSemaphore(3)  # placas de consumo aceitam poucas codificações ao mesmo tempo


def _testa_encoder(enc: str) -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2:r=30",
                            "-frames:v", "3", "-c:v", enc, "-pix_fmt", "yuv420p", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def encoder_hw() -> Optional[str]:
    """O encoder da placa que vai ser usado (None = CPU/libx264)."""
    try:
        import site_config
        pedido = str(site_config.load_site_config().get("encoder_video") or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        pedido = "auto"
    if os.environ.get("NARRATION_SITE_SEM_GPU") == "1":
        pedido = "cpu"
    with _trava:
        if _hw["testado"] and _hw["pedido"] == pedido:
            return _hw["encoder"]
        enc = None
        if pedido not in ("cpu", "libx264", "nenhum"):
            for cand in ([pedido] if pedido in _HW_CANDIDATOS else _HW_CANDIDATOS):
                if _testa_encoder(cand):
                    enc = cand
                    break
        _hw.update(testado=True, encoder=enc, pedido=pedido)
        if enc:
            print(f"[montagem] ⚡ codificando o vídeo na placa: {enc}", flush=True)
        return enc


def _para_hw(cmd: List[str], enc: str) -> List[str]:
    """Troca libx264 (+ preset/crf) pelo encoder da placa, com qualidade parecida."""
    out, k, crf, rapido = [], 0, None, False
    while k < len(cmd):
        a = cmd[k]
        if a == "-crf" and k + 1 < len(cmd):
            crf = cmd[k + 1]
            k += 2
            continue
        if a == "-preset" and k + 1 < len(cmd):
            rapido = cmd[k + 1] in ("ultrafast", "superfast")
            k += 2
            continue
        if a == "-tune" and k + 1 < len(cmd):
            k += 2
            continue
        out.append(enc if a == "libx264" else a)
        k += 1
    q = str(crf or 21)
    i = out.index(enc) + 1
    extra = {"h264_nvenc": ["-preset", "p1" if rapido else "p4", "-rc", "vbr", "-cq", q, "-b:v", "0"],
             "h264_qsv": ["-preset", "veryfast" if rapido else "medium", "-global_quality", q],
             "h264_amf": ["-quality", "speed" if rapido else "balanced", "-rc", "cqp", "-qp_i", q, "-qp_p", q],
             "h264_videotoolbox": ["-q:v", "60"]}.get(enc, [])
    return out[:i] + extra + out[i:]


def usa_hw(cmd: List[str]) -> bool:
    return any(c in cmd for c in _HW_CANDIDATOS)


def executar(cmd: List[str], timeout: int = 3600, **kw) -> "subprocess.CompletedProcess":
    """Roda um comando do ffmpeg já ajustado; se a placa falhar, roda de novo na CPU."""
    original = kw.pop("_original", None)
    import progresso_ffmpeg  # v84_114: dentro da montagem, o andamento de cada passe vai pra tela
    if usa_hw(cmd):
        with _sessoes_hw:
            r = progresso_ffmpeg.rodar(cmd, timeout=timeout, **kw)
        if r.returncode == 0 or original is None:
            return r
        print(f"[montagem] a placa falhou nesse passo ({r.stderr.strip()[-160:]}) — refazendo na CPU", flush=True)
        cmd = original
    return progresso_ffmpeg.rodar(cmd, timeout=timeout, **kw)


def rodar(cmd: List[str], timeout: int = 3600, **kw) -> "subprocess.CompletedProcess":
    """ajustar + executar (com volta pra CPU se a placa falhar)."""
    base = _ajustar_cpu(cmd)
    final = ajustar(cmd)
    return executar(final, timeout=timeout, _original=base, **kw)


def valida(q: Optional[str]) -> str:
    return q if q in QUALIDADES else "normal"


def definir(q: Optional[str]) -> None:
    with _trava:
        _estado["crf_inter"] = QUALIDADES[valida(q)]["crf_inter"]
        _estado["preset_inter"] = QUALIDADES[valida(q)].get("preset_inter")


def limpar() -> None:
    with _trava:
        _estado["crf_inter"] = None
        _estado["preset_inter"] = None


def _ajustar_cpu(cmd: List[str]) -> List[str]:
    if "libx264" not in cmd:
        return cmd
    crf = _estado.get("crf_inter")
    preset = _estado.get("preset_inter")
    if preset and "-preset" in cmd:
        k = cmd.index("-preset")
        if k + 1 < len(cmd) and cmd[k + 1] in ("veryfast", "faster", "fast", "medium"):
            cmd = cmd[:k + 1] + [preset] + cmd[k + 2:]
    if not crf or "-crf" in cmd:
        return cmd
    k = cmd.index("libx264")
    return cmd[:k + 1] + ["-crf", str(crf)] + cmd[k + 1:]


def ajustar(cmd: List[str]) -> List[str]:
    """Qualidade escolhida (CRF/preset das etapas intermediárias) + encoder da placa, se tiver."""
    cmd = _ajustar_cpu(cmd)
    if "libx264" in cmd:
        enc = encoder_hw()
        if enc:
            cmd = _para_hw(cmd, enc)
    return cmd


def passe_final(caminho: str, q: Optional[str]) -> bool:
    """Re-codifica o vídeo pronto com a qualidade escolhida (normal = nada)."""
    cfg = QUALIDADES[valida(q)]
    if not cfg["crf"] or not os.path.exists(caminho):
        return False
    tmp = caminho + ".q.mp4"
    import export_paralelo  # ⚡ v84_115: o vídeo em pedaços paralelos (o áudio é copiado do original)
    try:
        from video_assembler import _probe_duration
        _dur = _probe_duration(caminho)
    except Exception:  # noqa: BLE001
        _dur = 0.0
    if export_paralelo.tentar("qualidade final", lambda: export_paralelo.vf_em_pedacos(
            caminho, tmp, "", _dur, caminho + "_pedacos", "qualidade",
            extra=["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"]])):
        shutil.move(tmp, caminho)
        try:
            shutil.rmtree(caminho + "_pedacos", ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
        return True
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", caminho, "-map", "0:v:0", "-map", "0:a?",
           "-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"], "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", cfg["audio"], "-movflags", "+faststart", tmp]
    r = rodar(cmd, timeout=7200)
    if r.returncode != 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg falhou no passe final de qualidade: {r.stderr.strip()[-500:]}")
    shutil.move(tmp, caminho)
    return True
