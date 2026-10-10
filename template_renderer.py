"""Renderer genérico dos templates definidos pela biblioteca editorial.

A biblioteca fornece a intenção editorial (slots, composição, motion, fundos,
audio e campos de texto). Este módulo traduz isso para uma composição FFmpeg
reprodutível, preservando a duração das janelas e usando os takes reais que
já foram baixados/normalizados pelo editor.
"""
from __future__ import annotations

import math
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from template_library import get_template, resolve_audio

TARGET_FPS = 30


def _ffmpeg_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _ffmpeg_text(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _run_ffmpeg(args: List[str], timeout: int = 900) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou: {' '.join(cmd)}\n{result.stderr[-2000:]}")


def _duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return max(0.05, float(result.stdout.strip()))


def _color_for_background(name: str) -> str:
    n = (name or "").lower()
    if "papel" in n or "archive" in n or "essay" in n:
        return "#3a3835"
    if "metal" in n or "tech" in n or "grade" in n:
        return "#20232b"
    if "luz" in n or "clarao" in n or "light" in n:
        return "#30303a"
    if "nevoa" in n or "bruma" in n or "haze" in n:
        return "#292a32"
    if "vidro" in n or "glass" in n:
        return "#222934"
    if n.startswith("c50v2_bg_"):
        try:
            idx = int(n.rsplit("_", 1)[-1])
        except ValueError:
            idx = 1
        palette = ["#171a22", "#1d2430", "#20252d", "#261f25", "#25292a", "#1d2631", "#2a2027", "#24242d"]
        return palette[(idx - 1) % len(palette)]
    if n.startswith("c50solo_bg_"):
        try:
            idx = int(n.rsplit("_", 1)[-1])
        except ValueError:
            idx = 51
        palette = ["#191b22", "#25242a", "#21282c", "#2b2520", "#252a31"]
        return palette[idx % len(palette)]
    if "concreto" in n or "registro" in n or "grao" in n:
        return "#27272d"
    return "#1b1d24"


def _background_filter(name: str, label: str, width: int, height: int, duration: float) -> str:
    color = _color_for_background(name)
    n = (name or "").lower()
    filters = [f"format=rgba", f"colorchannelmixer=aa=1"]
    if "grao" in n:
        filters.append("noise=alls=10:allf=t+u")
    if "grade" in n or "grid" in n:
        filters.append("drawgrid=width=96:height=96:thickness=1:color=white@0.055")
    if "clarao" in n or n.startswith("luz") or "light" in n:
        filters.append("eq=brightness=0.045:saturation=1.08")
    if "vinheta" in n:
        filters.append("vignette=PI/5")
    return f"color=c={color}:s={width}x{height}:r={TARGET_FPS}:d={duration:.3f}," + ",".join(filters)


def _layout_boxes(template: Dict[str, Any], visible_count: int, width: int, height: int) -> List[Tuple[int, int, int, int]]:
    """Retorna caixas em pixels para os N takes visíveis da fase atual."""
    f = template.get("fisica") or {}
    p = template.get("perfil") or {}
    family = str(p.get("familia") or "").lower()
    motion = " ".join(map(str, f.get("motion") or [])).lower()
    name = str(template.get("nome") or "").lower()
    phrase = " ".join(map(str, template.get("whenToUse") or [])).lower()

    margin = int(min(width, height) * 0.045)
    gap = int(min(width, height) * 0.018)
    inner_w = width - 2 * margin
    inner_h = height - 2 * margin

    if visible_count <= 1:
        return [(margin, margin, inner_w, inner_h)]

    def hsplit(left_frac: float = 0.5):
        w1 = int((inner_w - gap) * left_frac)
        w2 = inner_w - gap - w1
        return [
            (margin, margin, w1, inner_h),
            (margin + w1 + gap, margin, w2, inner_h),
        ]

    if visible_count == 2:
        if "direita fixa" in name or "right" in family or "margem" in family or "painel_esq" in family:
            return hsplit(0.62)
        if "esquerda" in name or "left" in family or "painel_dir" in family:
            return [hsplit(0.38)[1], hsplit(0.38)[0]]
        if "diagonal" in phrase or "diag" in motion or "degraus" in family or "encontro" in family or "contrafluxo" in family:
            return [
                (margin, margin, int(inner_w * 0.63), int(inner_h * 0.63)),
                (margin + int(inner_w * 0.30), margin + int(inner_h * 0.29), int(inner_w * 0.61), int(inner_h * 0.64)),
            ]
        if "frente" in family or "contexto" in family or "profundidade" in phrase or "depth" in family:
            return [
                (margin, margin, int(inner_w * 0.66), int(inner_h * 0.80)),
                (margin + int(inner_w * 0.58), margin + int(inner_h * 0.42), int(inner_w * 0.36), int(inner_h * 0.38)),
            ]
        return hsplit(0.54)

    if visible_count == 3:
        if "triptico" in family or "trio" in name or "tres" in name:
            w = (inner_w - 2 * gap) // 3
            return [(margin + i * (w + gap), margin, w, inner_h) for i in range(3)]
        main_w = int(inner_w * 0.60)
        small_w = inner_w - gap - main_w
        small_h = (inner_h - gap) // 2
        return [
            (margin, margin, main_w, inner_h),
            (margin + main_w + gap, margin, small_w, small_h),
            (margin + main_w + gap, margin + small_h + gap, small_w, small_h),
        ]

    # 4+: grid 2x2 por padrão, com exceção de mosaico/rosácea que recebe o mesmo
    # tratamento estável; a intenção do catálogo continua guardada no JSON.
    cols = 2
    rows = math.ceil(visible_count / cols)
    cell_w = (inner_w - gap * (cols - 1)) // cols
    cell_h = (inner_h - gap * (rows - 1)) // rows
    boxes = []
    for i in range(visible_count):
        c = i % cols
        r = i // cols
        boxes.append((margin + c * (cell_w + gap), margin + r * (cell_h + gap), cell_w, cell_h))
    return [(x, y, max(2, w - (w % 2)), max(2, h - (h % 2))) for x, y, w, h in boxes]


def _motion_direction(template: Dict[str, Any]) -> str:
    f = template.get("fisica") or {}
    p = template.get("perfil") or {}
    motion = [str(x).lower() for x in (f.get("motion") or [])]
    family = str(p.get("familia") or "").lower()
    phrase = " ".join(map(str, template.get("whenToUse") or [])).lower()
    alltxt = " ".join(motion + [family, phrase])
    if "esq" in alltxt or "left" in alltxt:
        return "left"
    if "dir" in alltxt or "right" in alltxt:
        return "right"
    if "cima" in alltxt or "up" in alltxt or "alto" in alltxt:
        return "up"
    if "baixo" in alltxt or "down" in alltxt:
        return "down"
    if "diag" in alltxt:
        return "diag"
    return "up"


def _entrance_expression(template: Dict[str, Any], box: Tuple[int, int, int, int], width: int, height: int) -> Tuple[str, str, str]:
    """x/y/alpha expressions para o take que acabou de chegar."""
    x, y, w, h = box
    direction = _motion_direction(template)
    f = template.get("fisica") or {}
    vm = f.get("visualMotion") or {}
    exit_pt = str(vm.get("exitPt") or "fade").lower()
    motions = [str(x).lower() for x in f.get("motion") or []]
    enter = 0.42
    xexpr, yexpr = str(x), str(y)
    if direction == "left":
        xexpr = f"if(lt(t,{enter}),{x}-(1-t/{enter})*{w*0.45:.1f},{x})"
    elif direction == "right":
        xexpr = f"if(lt(t,{enter}),{x}+(1-t/{enter})*{w*0.45:.1f},{x})"
    elif direction == "down":
        yexpr = f"if(lt(t,{enter}),{y}-(1-t/{enter})*{h*0.35:.1f},{y})"
    else:
        yexpr = f"if(lt(t,{enter}),{y}-(1-t/{enter})*{h*0.35:.1f},{y})"
    if "dissolve_foco" in motions or exit_pt == "fade" or "fade" in motions:
        aexpr = f"if(lt(t,{enter}),t/{enter},1)"
    else:
        aexpr = "1"
    return xexpr, yexpr, aexpr


def _render_phase(
    template: Dict[str, Any],
    source_paths: Sequence[str],
    source_durations: Sequence[float],
    active_count: int,
    phase_duration: float,
    output_path: str,
    width: int,
    height: int,
    text_values: Optional[Dict[str, str]] = None,
    background_name: Optional[str] = None,
) -> None:
    boxes = _layout_boxes(template, active_count, width, height)
    bg_name = background_name or ((template.get("fisica") or {}).get("fundos") or ["concreto"])[0]
    args: List[str] = ["-f", "lavfi", "-i", _background_filter(bg_name, "bg", width, height, phase_duration)]

    filters: List[str] = []
    current = "[0:v]"
    filters.append(f"{current}format=rgba[bg]")
    current = "[bg]"

    # Cada fase conhece somente as fontes que já chegaram. Fontes antigas
    # são apresentadas pelo último frame; a fonte atual continua tocando.
    for j in range(active_count):
        path = source_paths[j]
        is_current = j == active_count - 1
        if is_current:
            args += ["-i", path]
        else:
            # último frame do take anterior
            args += ["-sseof", "-0.08", "-i", path]

        inp = f"[{j+1}:v]"
        if is_current:
            vf = f"{inp}trim=duration={phase_duration:.3f},setpts=PTS-STARTPTS,fps={TARGET_FPS},scale={max(2, boxes[j][2])}:{max(2, boxes[j][3])}:force_original_aspect_ratio=decrease,pad={boxes[j][2]}:{boxes[j][3]}:(ow-iw)/2:(oh-ih)/2,format=rgba"
        else:
            vf = f"{inp}trim=duration=0.08,setpts=PTS-STARTPTS,fps={TARGET_FPS},scale={max(2, boxes[j][2])}:{max(2, boxes[j][3])}:force_original_aspect_ratio=decrease,pad={boxes[j][2]}:{boxes[j][3]}:(ow-iw)/2:(oh-ih)/2,format=rgba,tpad=stop_mode=clone:stop_duration={phase_duration:.3f}"
        label = f"[src{j}]"
        filters.append(vf + label)

        x, y, w, h = boxes[j]
        xexpr, yexpr = str(x), str(y)
        if is_current:
            xexpr, yexpr, aexpr = _entrance_expression(template, boxes[j], width, height)
            if aexpr != "1":
                filters.append(f"[src{j}]fade=t=in:st=0:d=0.42:alpha=1[src{j}a]")
                src_label = f"[src{j}a]"
            else:
                src_label = f"[src{j}]"
        else:
            src_label = f"[src{j}]"
        out_label = f"[ov{j}]"
        filters.append(f"{current}{src_label}overlay=x='{xexpr}':y='{yexpr}':eof_action=pass:shortest=0{out_label}")
        current = out_label

    # Text fields da biblioteca: campos fixed usam default; legenda usa a fala
    # fornecida pelo editor, quando houver.
    for key, value in (text_values or {}).items():
        if not value:
            continue
        # posicionamento legível e estável; A/B ficam próximos de cada take.
        if key.lower().startswith("legenda"):
            tx, ty = 5, 88
        elif key == "ANTES":
            tx, ty = 8, 82
        elif key == "DEPOIS":
            tx, ty = 70, 82
        else:
            tx, ty = 6, 10
        escaped = _ffmpeg_text(value)
        # usar caixas escuras sutis atrás do texto sem exigir fontconfig
        font = os.path.join(os.path.dirname(__file__), "assets", "fonts", "DejaVuSans-Bold.ttf")
        if os.path.exists(font):
            fontopt = f"fontfile='{_ffmpeg_path(font)}'"
        else:
            fontopt = "font='Sans'"
        out_label = "[txtout]"
        filters.append(f"{current}drawtext={fontopt}:text='{escaped}':fontcolor=white:fontsize={max(26, int(height*0.035))}:x=w*{tx/100:.3f}:y=h*{ty/100:.3f}:box=1:boxcolor=black@0.48:boxborderw=12{out_label}")
        current = out_label

    filters.append(f"{current}format=yuv420p,setsar=1[vout]")
    args += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-t", f"{phase_duration:.3f}",
        "-r", str(TARGET_FPS), "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", output_path,
    ]
    _run_ffmpeg(args)


def _concat_raw(parts: Sequence[str], durations: Sequence[float], output_path: str, work_dir: str) -> None:
    list_path = os.path.join(work_dir, f"_tpl_concat_{uuid.uuid4().hex[:8]}.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")
    _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path])
    try:
        os.remove(list_path)
    except OSError:
        pass


def render_template(
    template_id: str,
    source_paths: Sequence[str],
    source_durations: Sequence[float],
    output_path: str,
    work_dir: str,
    width: int,
    height: int,
    text_values: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Renderiza uma instância de template com N takes reais.

    O comportamento de 1..4+ fontes é derivado de slots/composition/familia
    e o timing usa as durações reais dos takes; isso mantém o contrato de
    janelas sem depender dos `durS` de catálogo como duração rígida.
    """
    template = get_template(template_id)
    if not template:
        raise ValueError(f"Template desconhecido: {template_id}")
    if not source_paths:
        raise ValueError("Template sem fontes de mídia.")

    slots = int((template.get("fisica") or {}).get("slots") or 1)
    slots = max(1, min(slots, len(source_paths)))
    paths = list(source_paths[:slots])
    durations = [max(0.05, float(x)) for x in source_durations[:slots]]
    total_duration = sum(durations)

    # Solo sem renderer específico também passa pelo renderer genérico —
    # a biblioteca continua determinando slots, fundos, textos e motion.
    phases: List[Tuple[int, float, float]] = []
    elapsed = 0.0
    for i in range(slots):
        phases.append((i + 1, elapsed, durations[i]))
        elapsed += durations[i]

    phase_paths: List[str] = []
    for phase_idx, (_active, phase_start, phase_duration) in enumerate(phases):
        phase_out = os.path.join(work_dir, f"_template_{template_id}_{phase_idx}_{uuid.uuid4().hex[:8]}.mp4")
        _render_phase(
            template=template,
            source_paths=paths,
            source_durations=durations,
            active_count=phase_idx + 1,
            phase_duration=phase_duration,
            output_path=phase_out,
            width=width,
            height=height,
            text_values=text_values if phase_idx == slots - 1 else None,
            background_name=((template.get("fisica") or {}).get("fundos") or ["concreto"])[phase_idx % max(1, len((template.get("fisica") or {}).get("fundos") or ["concreto"]))],
        )
        phase_paths.append(phase_out)

    _concat_raw(phase_paths, durations, output_path, work_dir)
    for p in phase_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    # Audio: devolve eventos absolutos, sem misturar aqui para não duplicar a
    # narração principal. O caller adiciona esses efeitos ao mux final.
    sounds = list((template.get("fisica") or {}).get("sons") or [])
    if not sounds:
        audio = (template.get("perfil") or {}).get("audio") or {}
        for key in ("principal", "apoio", "contextual"):
            if audio.get(key):
                sounds.append(str(audio[key]))
    audio_events = []
    for idx, sound in enumerate(sounds):
        path = resolve_audio(sound)
        if path:
            if idx == 0:
                at = 0.0
            else:
                at = min(total_duration - 0.05, sum(durations[:min(idx, len(durations))]))
            audio_events.append({"path": path, "start": max(0.0, at), "name": Path(path).name})

    return {
        "template_id": template_id,
        "output_path": output_path,
        "duration": total_duration,
        "slots": slots,
        "audio_events": audio_events,
    }
