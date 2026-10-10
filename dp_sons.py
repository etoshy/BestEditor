"""
Sons do editor original (DarkPlanner) — assets/sons/<categoria>/<som>.m4a,
convertidos do audios.zip (cada pasta do zip = uma categoria).

Os nomes dos arquivos não batem 1:1 com os nomes que o darkplanner.json usa
("camera_1.mp3", "woosh_24.mp3", "tpl:wh_cinema_4.mp3"…) — o mapeamento
abaixo foi feito por análise (número + família do nome) e por chute onde não
havia correspondência (ex.: matchcut_* e musica_doc não vieram no zip).

Uso na montagem: todos os eventos de som (transições automáticas, entrada de
take das cenas, destaques de texto e os sons que a pessoa põe na timeline)
são mixados com a narração ANTES do mux — o pico do som cai no instante do
evento (início da transição, entrada do take, impacto do destaque).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from functools import lru_cache
from typing import Any, Dict, List, Optional

_AQUI = os.path.dirname(os.path.abspath(__file__))
SONS_DIR = os.path.join(_AQUI, "assets", "sons")


@lru_cache(maxsize=1)
def _manifesto() -> Dict[str, Any]:
    with open(os.path.join(SONS_DIR, "sons.json"), encoding="utf-8") as f:
        return json.load(f)


def sons() -> List[Dict[str, Any]]:
    return list(_manifesto()["sons"])


def som(sid: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sid:
        return None
    return next((s for s in _manifesto()["sons"] if s["id"] == sid), None)


def caminho(sid: str) -> Optional[str]:
    s = som(sid)
    return os.path.join(SONS_DIR, s["arquivo"]) if s else None


def categorias() -> List[Dict[str, Any]]:
    cats: Dict[str, List[Dict[str, Any]]] = {}
    for s in sons():
        cats.setdefault(s["categoria"], []).append(s)
    ordem = ["transições", "variados", "passagem", "cinema", "impacto", "pop", "foley", "digital", "fogo", "vento", "respiro"]
    return [{"nome": c, "sons": cats[c]} for c in sorted(cats, key=lambda c: (ordem.index(c) if c in ordem else 99, c))]


# ------------------------------------------------------------------ nomes do darkplanner.json -> arquivos do zip
MAPA_DP = {
    "camera_1": "foley/camera_1", "camera_14": "foley/camera_14", "woosh_24": "variados/whoosh_24", "woosh_29": "variados/whoosh_29",
    "pop_click_1": "pop/pop_click_1_escala", "pop_click_2": "pop/pop_click_2_escala", "pop_click_3": "pop/pop_click_3_escala",
    "click_ms_2": "pop/click_mouse_1_up", "wh_breath_2": "respiro/respiro_2", "wh_breath_3": "respiro/respiro_3",
    "wh_breath_4": "vento/vento_suave_26", "wh_solto_1": "variados/whoosh_solto_1", "wh_cinema_1": "cinema/cinema_1",
    "wh_cinema_4": "cinema/cinema_4", "wh_cinema_6": "cinema/cinema_6", "wh_cinema_12": "cinema/cinema_12",
    "wh_cinema_14": "cinema/cinema_14", "wh_hit_11": "impacto/impacto_11", "wh_hit_5": "impacto/impacto_5",
    "key_click_1": "foley/tecla_suave", "catraca_1": "foley/catraca_rolagem", "typing_5": "foley/digitacao_5_longa",
    "typing_6": "foley/digitacao_6_curta", "matchcut_1": "transicoes/impacto_curto", "matchcut_2": "transicoes/zoom_curto",
    "matchcut_3": "transicoes/passagem_curta", "matchcut_4": "transicoes/disparo_de_camera", "musica_doc": "cinema/cinema_longo_20",
}


def do_darkplanner(nome: str) -> Optional[str]:
    """'tpl:wh_cinema_4.mp3' / 'camera_1.mp3' -> id do som no site."""
    base = re.sub(r"^tpl:", "", nome or "")
    base = os.path.splitext(base)[0]
    sid = MAPA_DP.get(base)
    return sid if sid and som(sid) else None


# ------------------------------------------------------------------ som automático de cada transição
_TR_ESPECIFICO = {
    "dp_shutter": "transicoes/obturador_mecanico", "dp_shutter_laminas": "transicoes/obturador_mecanico",
    "dp_shutter_filme": "transicoes/pelicula_curta", "dp_shutter_dossie": "foley/camera_14",
    "dp_shutter_foco": "transicoes/foco_optico", "dp_shutter_finale": "transicoes/impacto",
    "dp_shutter_deslize": "transicoes/passagem_curta", "dp_shutter_refoco": "transicoes/foco_optico",
    "dp_shutter_pulso": "transicoes/pulso_digital_curto",
    "dp:film_burn": "transicoes/film_burn_queima", "dp:ft_filmburn2": "transicoes/film_burn_queima",
    "dp:ft_filmburn4": "transicoes/film_burn_4", "dp:ft_filmburn5": "transicoes/film_burn_5", "dp:ft_filmburn6": "transicoes/film_burn_6",
    "dp:ft_filmburn7": "transicoes/film_burn_7", "dp:ft_filmburn9": "transicoes/film_burn_9", "dp:ft_fogo": "transicoes/fogo",
    "dp:film_fire_sweep": "transicoes/varredura_de_fogo", "dp:film_burn_aperture": "transicoes/abertura_de_pelicula",
    "dp:ft_pk_film": "transicoes/pelicula_curta", "dp:film_roll": "transicoes/pelicula_curta", "dp:camera_shutter": "transicoes/obturador_mecanico",
    "dp:camera_flash": "transicoes/disparo_de_camera", "dp:camera_focus": "transicoes/foco_optico", "dp:gl_oss_wind": "transicoes/vento",
    "dp:gl_oss_cannabisleaf": "transicoes/folha_seca", "dp:gl_woosh": "transicoes/whoosh", "dp:gl_punch": "transicoes/impacto_curto",
    "dp:gl_flash": "transicoes/disparo_de_camera", "dp:gl_glitch": "transicoes/digital", "dp:ft_pk_glitch": "transicoes/digital",
    "dp:ft_pk2_glitch": "transicoes/pulso_digital_curto", "dp:gl_zoom_cross": "transicoes/zoom_curto", "dp:cb_zoom": "transicoes/zoom_curto",
    "dp:zoom_in_out": "transicoes/zoom_curto", "dp:ft_poeira": "transicoes/ar_suave", "dp:cb_respiro": "respiro/respiro_2",
    "dp:gl_fade_suave": "transicoes/ar_suave", "dp:gl_fade_escuro": "respiro/respiro_3", "dp:gl_fade_grao": "transicoes/ar_suave",
    "dp:gl_fade_brilho": "cinema/cinema_1", "dp:cb_mergulho": "cinema/cinema_6", "dp:cb_foco": "transicoes/foco_optico",
    "dp:ft_splash_4": "variados/whoosh_grave_3", "dp:ft_pk2_suave": "transicoes/ar_suave",
}
_TR_FAMILIA = {  # família do catálogo -> sons possíveis (escolhido pelo nome, sempre o mesmo pra mesma transição)
    "fade": ["transicoes/ar_suave", "respiro/respiro_2", "vento/vento_suave_28"],
    "luz": ["cinema/cinema_4", "cinema/cinema_12", "cinema/cinema_14", "cinema/cinema_2"],
    "varredura": ["transicoes/whoosh", "variados/whoosh_1", "variados/whoosh_5", "variados/whoosh_10", "variados/whoosh_26"],
    "forma": ["transicoes/passagem_curta", "passagem/passagem_3", "passagem/passagem_8", "passagem/passagem_10", "passagem/passagem_19", "variados/whoosh_solto_2"],
    "impacto": ["transicoes/impacto_curto", "impacto/impacto_5", "impacto/impacto_15"],
    "glitch": ["transicoes/digital", "digital/digital_1", "digital/digital_3", "digital/digital_5", "transicoes/pulso_digital_curto"],
    "combo": ["transicoes/passagem", "passagem/passagem_21"], "splash": ["variados/whoosh_grave_4", "variados/whoosh_grave_3"],
}


def _um_de(lista, chave: str) -> str:
    import zlib
    return lista[zlib.crc32(chave.encode()) % len(lista)]


def som_da_transicao(tipo: Optional[str]) -> Optional[str]:
    """Som que combina com a transição (o "som automático" do DarkPlanner)."""
    if not tipo or tipo in ("none", "global", "site"):
        return None
    if tipo in _TR_ESPECIFICO:
        return _TR_ESPECIFICO[tipo]
    if tipo.startswith("dp:"):
        import dp_visual
        fam = next((t.get("familia") for t in dp_visual.transicoes() if t["id"] == tipo), None)
        if tipo.startswith("dp:ft_pk") and "leak" in tipo:
            return _um_de(["cinema/cinema_12", "cinema/cinema_16", "cinema/cinema_17", "cinema/cinema_1"], tipo)
        if "burn" in tipo:
            return "transicoes/film_burn_queima"
        return _um_de(_TR_FAMILIA.get(fam or "", ["transicoes/passagem_curta"]), tipo)
    if tipo in ("fade", "dissolve", "fadeslow", "fadegrays", "fade_grayscale", "distance", "hblur"):
        return "transicoes/ar_suave"
    if tipo in ("fadeblack", "fadewhite", "fadefast"):
        return "respiro/respiro_3" if tipo == "fadeblack" else "transicoes/disparo_de_camera"
    if re.match(r"^(wipe|slide|smooth|cover|reveal)|wind$", tipo):
        return "transicoes/whoosh"
    if re.search(r"circle|iris|radial|pinwheel|diamond|zoomin|rectcrop", tipo):
        return "transicoes/zoom_curto"
    if re.search(r"slice|blinds|checker|noise|pixel|squeeze|open|close|diag", tipo):
        return "transicoes/passagem_curta"
    return "transicoes/passagem_curta"


# ------------------------------------------------------------------ eventos e mixagem
def evento(sid: str, t: float, volume: float = 1.0, alinhar: str = "pico") -> Optional[Dict[str, Any]]:
    """Evento de som: o PICO (ou o início do som) cai no instante t."""
    s = som(sid)
    if not s:
        return None
    ref = s.get("pico", 0) if alinhar == "pico" else s.get("inicio_som", 0)
    return {"som": sid, "inicio": round(max(0.0, t - ref), 3), "volume": float(volume)}


def mixar(narracao: str, eventos: List[Dict[str, Any]], saida: str, volume_sfx: float = 0.55) -> str:
    """Narração + efeitos sonoros num WAV só (a narração não muda de volume)."""
    eventos = [e for e in eventos if caminho(e.get("som")) and os.path.exists(caminho(e["som"]))]
    if not eventos:
        return narracao
    eventos = sorted(eventos, key=lambda e: e["inicio"])[:400]
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", narracao]
    partes = []
    for k, e in enumerate(eventos, start=1):
        args += ["-i", caminho(e["som"])]
        atraso = int(round(float(e["inicio"]) * 1000))
        vol = max(0.0, min(3.0, float(e.get("volume", 1.0)) * volume_sfx))
        partes.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol:.3f},adelay={atraso}|{atraso}[s{k}]")
    rot = "".join(f"[s{k}]" for k in range(1, len(eventos) + 1))
    partes.append(f"{rot}amix=inputs={len(eventos)}:normalize=0:dropout_transition=0[sfx]")
    partes.append("[0:a]aresample=48000,aformat=channel_layouts=stereo[nar]")
    partes.append("[nar][sfx]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[out]")
    script = saida + ".filtro.txt"
    with open(script, "w", encoding="utf-8") as f:
        f.write(";\n".join(partes))
    cmd = args + ["-filter_complex_script", script, "-map", "[out]", "-c:a", "pcm_s16le", saida]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0 and "filter_complex_script" in r.stderr and ("nrecognized" in r.stderr or "not found" in r.stderr):
        k = cmd.index("-filter_complex_script")
        r = subprocess.run(cmd[:k] + ["-/filter_complex"] + cmd[k + 1:], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    try:
        os.remove(script)
    except OSError:
        pass
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao mixar os sons: {r.stderr.strip()[-600:]}")
    return saida


def eventos_automaticos(segments, plano_transicoes, grupos, destaques, opcoes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sons automáticos: transições (no começo da transição), entrada de cada
    take das cenas (os sons que o template pede) e destaques de texto (o som
    do estilo, alinhado com o impacto)."""
    import cenas_dp
    import dp_destaques
    ev: List[Dict[str, Any]] = []
    if opcoes.get("transicoes", True):
        for i, (tipo, d) in enumerate(plano_transicoes):
            if tipo == "none" or d <= 0:
                continue
            escolha = getattr(segments[i], "transition_som", None)
            if escolha == "nenhum":
                continue
            sid = escolha if escolha and som(escolha) else som_da_transicao(tipo)
            if sid:
                e = evento(sid, segments[i].end + d * 0.35)
                if e:
                    ev.append(e)
    if opcoes.get("cenas", True):
        for a, b, tid in grupos:
            if not tid:
                continue
            import dp_visual
            fis = ((dp_visual.dp()["templates"].get(tid) or {}).get("fisica") or {})
            nomes = [do_darkplanner(s) for s in (fis.get("sons") or [])]
            nomes = [n for n in nomes if n]
            if not nomes:
                continue
            for k in range(a, b + 1):
                # 1º take: o som principal; os seguintes: o "take"/contextual (ou o mesmo)
                sid = nomes[0] if k == a else nomes[-1]
                e = evento(sid, segments[k].start + 0.12, 0.9)
                if e:
                    ev.append(e)
    if opcoes.get("destaques", True):
        for d in destaques or []:
            if d.get("som") == "nenhum":
                continue
            h = dp_destaques.estilo(d.get("estilo")) or {}
            au = h.get("audio") or {}
            sid = d.get("som") if som(d.get("som")) else next((do_darkplanner(a) for a in (au.get("assets") or []) if do_darkplanner(a)), None)
            if not sid:
                continue
            jan = au.get("janela") or {}
            tipo_ev = au.get("evento") or "assentamento"
            ini_d, fim_d = float(d["start"]), float(d["end"])
            if tipo_ev == "porBatida" and not d.get("som"):
                # um som por palavra que entra (nos tempos da fala, quando dá), alternando os do estilo
                sons_est = [x for x in (do_darkplanner(a) for a in (au.get("assets") or [])) if x] or [sid]
                ws = [w for w in (opcoes.get("palavras") or []) if ini_d - 0.2 <= float(w.get("start", -1)) <= fim_d - 0.15]
                n_pal = max(1, len(str(d.get("texto") or "").split()))
                if len(ws) >= n_pal * 0.6:
                    batidas = [float(w["start"]) for w in ws][:n_pal]
                else:
                    passo = min(0.22, (fim_d - ini_d) * 0.6 / n_pal)
                    batidas = [ini_d + k * passo for k in range(n_pal)]
                for k, tb in enumerate(batidas[:12]):
                    e = evento(sons_est[k % len(sons_est)], max(ini_d, tb), 0.55)
                    if e:
                        ev.append(e)
                continue
            if tipo_ev in ("tipagem", "cama", "rolagem", "entrada"):
                # som que acompanha (digitação, cama, catraca): começa junto com o texto
                e = evento(sid, ini_d + float(jan.get("visualStartS") or 0), 0.6 if tipo_ev == "cama" else 0.75, alinhar="inicio")
                if e:
                    ev.append(e)
                continue
            alvo = ini_d + float(jan.get("visualStartS") or 0) + (float(jan.get("peakTargetS") or 0.12) if isinstance(jan.get("peakTargetS"), (int, float)) else 0.12)
            e = evento(sid, alvo, 0.8)
            if e:
                ev.append(e)
    return ev
