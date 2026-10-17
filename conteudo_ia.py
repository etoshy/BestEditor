"""🤖 Conteúdo IA (v84_145) — selo nas cenas geradas por IA.

Toda cena gerada por IA (🟣 Runpod / pod, Google Flow) ganha um texto discreto num canto — padrão: "Simulação:
conteúdo gerado por IA", no canto superior direito, no IDIOMA DO VÍDEO. Mensagens prontas (presets) em vários
idiomas + as suas. O selo vira overlays de texto normais (faixa Overlays da timeline, marcados como "selo_ia"),
refeitos sozinhos na montagem — se você trocar uma cena de IA por uma real, o selo daquele trecho some.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

GERADORES = ("runpod", "flow")
POSICOES = {"top-right": "↗ superior direito", "top-left": "↖ superior esquerdo", "bottom-right": "↘ inferior direito",
            "bottom-left": "↙ inferior esquerdo", "top-center": "⬆ em cima, no meio", "bottom-center": "⬇ embaixo, no meio"}

PRESETS: Dict[str, Dict[str, str]] = {
    "simulacao": {"pt": "Simulação: conteúdo gerado por IA", "en": "Simulation: AI-generated content",
                  "es": "Simulación: contenido generado por IA", "de": "Simulation: KI-generierter Inhalt",
                  "fr": "Simulation : contenu généré par IA", "it": "Simulazione: contenuto generato dall'IA",
                  "nl": "Simulatie: door AI gegenereerde inhoud", "pl": "Symulacja: treść wygenerowana przez AI"},
    "recriacao": {"pt": "Recriação gerada por IA", "en": "AI-generated recreation", "es": "Recreación generada por IA",
                  "de": "KI-generierte Nachstellung", "fr": "Reconstitution générée par IA",
                  "it": "Ricostruzione generata dall'IA", "nl": "Reconstructie gegenereerd door AI",
                  "pl": "Rekonstrukcja wygenerowana przez AI"},
    "ilustrativa": {"pt": "Imagem ilustrativa (IA)", "en": "Illustrative image (AI)", "es": "Imagen ilustrativa (IA)",
                    "de": "Symbolbild (KI)", "fr": "Image d'illustration (IA)", "it": "Immagine illustrativa (IA)",
                    "nl": "Illustratieve afbeelding (AI)", "pl": "Obraz ilustracyjny (AI)"},
    "dramatizacao": {"pt": "Dramatização – imagem gerada por IA", "en": "Dramatization – AI-generated image",
                     "es": "Dramatización – imagen generada por IA", "de": "Dramatisierung – KI-generiertes Bild",
                     "fr": "Dramatisation – image générée par IA", "it": "Drammatizzazione – immagine generata dall'IA",
                     "nl": "Dramatisering – door AI gegenereerd beeld", "pl": "Dramatyzacja – obraz wygenerowany przez AI"},
    "nao_real": {"pt": "Imagem não real – criada por IA", "en": "Not a real image – created by AI",
                 "es": "Imagen no real – creada con IA", "de": "Kein echtes Foto – mit KI erstellt",
                 "fr": "Image non réelle – créée par IA", "it": "Immagine non reale – creata con l'IA",
                 "nl": "Geen echte foto – gemaakt met AI", "pl": "To nie jest prawdziwe zdjęcie – stworzone przez AI"},
    "ia": {"pt": "Gerado por IA", "en": "AI-generated", "es": "Generado por IA", "de": "KI-generiert",
           "fr": "Généré par IA", "it": "Generato dall'IA", "nl": "Gegenereerd door AI", "pl": "Wygenerowane przez AI"},
}
NOMES_PRESET = {"simulacao": "🧪 Simulação", "recriacao": "🎬 Recriação", "ilustrativa": "🖼 Imagem ilustrativa",
                "dramatizacao": "🎭 Dramatização", "nao_real": "⚠ Não é real", "ia": "🤖 Gerado por IA"}

PADRAO = {"ativo": True, "preset": "simulacao", "texto": "", "posicao": "top-right", "tamanho": 2.6,
          "fundo": True, "contorno": False, "fade": True, "min_dur": 0.0}


def _arquivo_presets(base: str) -> str:
    return os.path.join(base, "conteudo_ia_presets.json")


def presets_meus(base: str) -> List[Dict[str, str]]:
    try:
        with open(_arquivo_presets(base), encoding="utf-8") as f:
            d = json.load(f)
        return [x for x in d if isinstance(x, dict) and str(x.get("texto") or "").strip()][:50]
    except (OSError, ValueError):
        return []


def salvar_preset(base: str, nome: str, texto: str) -> List[Dict[str, str]]:
    import arquivo_seguro
    lista = [x for x in presets_meus(base) if x.get("nome") != nome]
    lista.append({"id": "m_" + uuid.uuid4().hex[:6], "nome": (nome or texto)[:40], "texto": texto.strip()[:120]})
    arquivo_seguro.gravar_json(_arquivo_presets(base), lista[-50:], indent=1)
    return lista


def apagar_preset(base: str, pid: str) -> List[Dict[str, str]]:
    import arquivo_seguro
    lista = [x for x in presets_meus(base) if x.get("id") != pid]
    arquivo_seguro.gravar_json(_arquivo_presets(base), lista, indent=1)
    return lista


def idioma_do_job(job: Dict[str, Any]) -> str:
    try:
        import idiomas
        return idiomas.normalizar(job.get("language") or job.get("idioma")) or "pt"
    except Exception:  # noqa: BLE001
        return str(job.get("language") or "pt")[:2]


def config(job: Dict[str, Any]) -> Dict[str, Any]:
    return {**PADRAO, **(job.get("selo_ia") or {})}


def texto(job: Dict[str, Any], base: str = "") -> str:
    c = config(job)
    if (c.get("texto") or "").strip():
        return c["texto"].strip()[:120]
    if str(c.get("preset") or "").startswith("m_") and base:
        m = next((x for x in presets_meus(base) if x["id"] == c["preset"]), None)
        if m:
            return m["texto"]
    p = PRESETS.get(c.get("preset") or "simulacao") or PRESETS["simulacao"]
    return p.get(idioma_do_job(job)) or p["en"]


def trechos_ia(job: Dict[str, Any]) -> List[Dict[str, float]]:
    """Janelas [início, fim] dos trechos com mídia gerada por IA (trechos vizinhos viram uma janela só)."""
    out: List[Dict[str, float]] = []
    for d in job.get("pending_segments") or []:
        if d.get("provider") not in GERADORES:
            continue
        a, b = float(d["start"]), float(d["end"])
        if out and a - out[-1]["end"] < 0.05:
            out[-1]["end"] = max(out[-1]["end"], b)
        else:
            out.append({"start": a, "end": b})
    return out


def selos(job: Dict[str, Any], base: str = "") -> List[Dict[str, Any]]:
    c = config(job)
    if not c.get("ativo"):
        return []
    t = texto(job, base)
    estilo = {"position": c.get("posicao") if c.get("posicao") in POSICOES else "top-right", "font": "bold",
              "font_size_pct": max(1.5, min(8.0, float(c.get("tamanho") or 2.6))), "background": bool(c.get("fundo")),
              "border": bool(c.get("contorno")), "animation": "fade" if c.get("fade") else "none",
              "animation_duration": 0.3}
    return [{"id": "selo_" + uuid.uuid4().hex[:6], "media_type": "text", "text": t, "start": round(j["start"], 3),
             "end": round(j["end"], 3), "style": dict(estilo), "origem": "selo_ia"}
            for j in trechos_ia(job) if j["end"] - j["start"] >= float(c.get("min_dur") or 0)]


def sincronizar(job: Dict[str, Any], base: str = "") -> int:
    """Tira os selos antigos e põe de novo, nos trechos de IA de agora. Devolve quantos."""
    novos = selos(job, base)
    job["overlays"] = [ov for ov in job.get("overlays") or [] if ov.get("origem") != "selo_ia"] + novos
    return len(novos)


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str, jobs: Dict[str, Any], salvar_estado) -> None:
    from flask import jsonify, request

    def _estado(job: Dict[str, Any]) -> Dict[str, Any]:
        lang = idioma_do_job(job)
        return {"ok": True, "config": config(job), "idioma": lang, "texto": texto(job, base_dir),
                "presets": [{"id": k, "nome": NOMES_PRESET[k], "texto": v.get(lang) or v["en"]} for k, v in PRESETS.items()],
                "meus": presets_meus(base_dir), "posicoes": POSICOES,
                "trechos": len(trechos_ia(job)), "cenas_ia": sum(1 for d in job.get("pending_segments") or [] if d.get("provider") in GERADORES),
                "selos": sum(1 for ov in job.get("overlays") or [] if ov.get("origem") == "selo_ia")}

    @app.route("/job/<job_id>/conteudo-ia", methods=["GET", "POST"])
    def conteudo_ia_rota(job_id: str):
        job = jobs.get(job_id)
        if not job:
            return jsonify({"erro": "Projeto não encontrado."}), 404
        if request.method == "POST":
            c = request.get_json(silent=True) or {}
            if c.get("acao") == "salvar_preset":
                if not str(c.get("texto") or "").strip():
                    return jsonify({"erro": "Escreva a mensagem."}), 400
                salvar_preset(base_dir, str(c.get("nome") or ""), str(c["texto"]))
                return jsonify(_estado(job))
            if c.get("acao") == "apagar_preset":
                apagar_preset(base_dir, str(c.get("id") or ""))
                return jsonify(_estado(job))
            cfg = config(job)
            for k in ("ativo", "fundo", "contorno", "fade"):
                if k in c:
                    cfg[k] = bool(c[k])
            if c.get("preset"):
                cfg["preset"] = str(c["preset"])[:20]
            if "texto" in c:
                cfg["texto"] = str(c.get("texto") or "").strip()[:120]
            if c.get("posicao") in POSICOES:
                cfg["posicao"] = c["posicao"]
            if c.get("tamanho") is not None:
                try:
                    cfg["tamanho"] = max(1.5, min(8.0, float(c["tamanho"])))
                except (TypeError, ValueError):
                    pass
            if c.get("min_dur") is not None:
                try:
                    cfg["min_dur"] = max(0.0, min(10.0, float(c["min_dur"])))
                except (TypeError, ValueError):
                    pass
            job["selo_ia"] = cfg
            sincronizar(job, base_dir)
            salvar_estado(job_id)
        return jsonify(_estado(job))
