"""🖥 v84_424 — IA LOCAL (Qwen e outros) pras partes simples: buscas de vídeo/imagem, juiz das cenas (com modelo de visão),
Wikipedia, YouTube, sound design. Grátis, roda no seu PC.

Funciona com qualquer servidor no padrão da OpenAI:
  • Ollama     → http://localhost:11434/v1   (ollama pull qwen2.5:7b  ·  com visão: ollama pull qwen2.5vl:7b)
  • LM Studio  → http://localhost:1234/v1    (carregue o modelo e ligue o "Local Server")

Cuidado com a placa de vídeo: o modelo local, o Chatterbox (voz) e o Whisper disputam a mesma VRAM — se a voz estiver
gerando junto, os dois ficam lentos. O Ollama tira o modelo da memória sozinho uns minutos depois do último uso.
Se a IA local falhar (desligada, não responde, JSON quebrado), o pedido segue pelo caminho de sempre (assinatura/API).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

# recursos que podem ir pra IA local (os simples) — o que olha imagem só com modelo de visão
RECURSOS_LOCAIS = {
    "buscas": "🧭 Ficha do vídeo + buscas melhores (texto)",
    "nova_busca": "🔁 Reescrever a busca quando nada presta (texto)",
    "juiz": "⚖️ Juiz visual nas prévias (precisa de modelo com VISÃO, ex.: qwen2.5vl)",
    "juiz_manual": "🔎 Nota no botão Buscar do editor (precisa de VISÃO)",
    "juiz_curtos": "⚖️ Juiz visual nos ⚡ vídeos curtos (precisa de VISÃO)",
    "wikipedia": "📚 Wikipedia: desfazer ambiguidades (texto)",
    "youtube_ordem": "🎬 Ordenar os vídeos do YouTube (texto)",
    "youtube_momento": "🎯 Achar o momento certo pela legenda (texto)",
    "sound_design": "🎧 Sound design: a emoção de cada parte (texto)",
}
VISAO = ("juiz", "juiz_manual", "juiz_curtos")
PADRAO = {"ativo": True, "url": "http://localhost:11434/v1", "modelo": "qwen2.5:7b", "modelo_visao": "", "so_local": [],
          "recursos": ["buscas", "nova_busca", "wikipedia", "youtube_ordem", "youtube_momento", "sound_design"]}


class LocalErro(Exception):
    pass


_FALHA = {"ate": 0.0, "avisado": 0.0}
PAUSA_S = 180  # servidor fechado: não tenta de novo por 3 min


def fora_do_ar() -> bool:
    import time
    return time.time() < _FALHA["ate"]


def marcar_falha(exc: Exception) -> bool:
    """Servidor fora do ar → pausa a IA local por PAUSA_S. Devolve True se vale registrar (no máximo 1 a cada 10 min)."""
    import time
    if "não respondeu em" in str(exc):
        _FALHA["ate"] = time.time() + PAUSA_S
        if time.time() - _FALHA["avisado"] < 600:
            return False
        _FALHA["avisado"] = time.time()
    return True


def config(c: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = dict(PADRAO)
    d.update({k: v for k, v in ((c or {}).get("local") or {}).items() if k in PADRAO})
    d["recursos"] = [r for r in d.get("recursos") or [] if r in RECURSOS_LOCAIS]
    d["so_local"] = [r for r in d.get("so_local") or [] if r in RECURSOS_LOCAIS]  # 💸 v84_425: falhou = não cai na API
    return d


def so_local(recurso: str, c: Optional[Dict[str, Any]] = None) -> bool:
    lc = config(c)
    return bool(lc["ativo"]) and recurso in lc["so_local"] and recurso in lc["recursos"]


def vai_local(recurso: str, conteudo: Any, c: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """O modelo a usar se este pedido vai pra IA local (senão None)."""
    lc = config(c)
    if not lc["ativo"] or recurso not in lc["recursos"]:
        return None
    tem_img = isinstance(conteudo, list) and any(isinstance(b, dict) and b.get("type") == "image" for b in conteudo)
    if tem_img:
        return (lc.get("modelo_visao") or "").strip() or None  # sem modelo de visão: imagem segue pra API
    return (lc.get("modelo") or "").strip() or None


def _mensagens(system: str, conteudo: Any, schema: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    partes: List[Dict[str, Any]] = []
    blocos = conteudo if isinstance(conteudo, list) else [{"type": "text", "text": str(conteudo or "")}]
    for b in blocos:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            partes.append({"type": "text", "text": str(b.get("text") or "")})
        elif b.get("type") == "image":
            src = b.get("source") or {}
            if src.get("type") == "base64":
                partes.append({"type": "image_url",
                               "image_url": {"url": f"data:{src.get('media_type') or 'image/jpeg'};base64,{src.get('data')}"}})
            elif src.get("url"):
                partes.append({"type": "image_url", "image_url": {"url": src["url"]}})
    sys_txt = system + ("\n\nResponda SOMENTE com um JSON válido (sem texto antes ou depois, sem ```) neste formato (JSON Schema):\n"
                        + json.dumps(schema, ensure_ascii=False) if schema else "")
    so_texto = all(p["type"] == "text" for p in partes)
    user: Any = "\n\n".join(p["text"] for p in partes) if so_texto else partes
    return [{"role": "system", "content": sys_txt}, {"role": "user", "content": user}]


def chamar(modelo: str, system: str, conteudo: Any, schema: Optional[Dict[str, Any]] = None, max_tokens: int = 2000,
           timeout: float = 180, c: Optional[Dict[str, Any]] = None, transporte=None) -> Any:
    import requests
    lc = config(c)
    url = lc["url"].rstrip("/") + "/chat/completions"
    corpo: Dict[str, Any] = {"model": modelo, "messages": _mensagens(system, conteudo, schema), "temperature": 0.2,
                             "max_tokens": int(max_tokens), "stream": False}
    if schema:
        corpo["response_format"] = {"type": "json_schema", "json_schema": {"name": "resposta", "schema": schema}}
    post = transporte or (lambda u, j: requests.post(u, json=j, timeout=timeout))
    try:
        r = post(url, corpo)
        if schema and getattr(r, "status_code", 200) == 400:  # servidor sem json_schema: pede só JSON
            corpo["response_format"] = {"type": "json_object"}
            r = post(url, corpo)
        if getattr(r, "status_code", 200) != 200:
            raise LocalErro(f"{r.status_code}: {str(getattr(r, 'text', ''))[:300]}")
        d = r.json()
    except LocalErro:
        raise
    except Exception as exc:  # noqa: BLE001 — servidor desligado, timeout…
        raise LocalErro(f"a IA local não respondeu em {lc['url']} ({exc})") from exc
    try:
        texto = str(d["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LocalErro("resposta estranha da IA local") from exc
    import re
    texto = re.sub(r"(?s)^<think>.*?</think>\s*", "", texto)  # Qwen3 com "pensar" ligado
    if not schema:
        if not texto:
            raise LocalErro("a IA local devolveu vazio")
        return texto
    import json_ia
    try:
        return json_ia.carregar(texto)
    except Exception as exc:  # noqa: BLE001
        raise LocalErro(f"a IA local não devolveu JSON: {texto[:160]}") from exc


def listar_modelos(c: Optional[Dict[str, Any]] = None, url: str = "") -> List[str]:
    import requests
    base = (url or config(c)["url"]).rstrip("/")
    try:
        r = requests.get(base + "/models", timeout=5)
        return sorted(m.get("id") for m in (r.json().get("data") or []) if m.get("id"))
    except Exception:  # noqa: BLE001
        return []


def testar(c: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lc = config(c)
    modelos = listar_modelos(c)
    if not modelos:
        return {"ok": False, "erro": f"nada respondendo em {lc['url']} — abra o Ollama (ou o Local Server do LM Studio)"}
    out = {"modelos": modelos}
    for chave in ("modelo", "modelo_visao"):
        m = (lc.get(chave) or "").strip()
        if not m:
            continue
        if m not in modelos and not any(x.split(":")[0] == m.split(":")[0] for x in modelos):
            out[chave] = f"❌ “{m}” não está instalado (tem: {', '.join(modelos[:8])})"
            continue
        try:
            r = chamar(m, "Responda só o JSON pedido.", "Diga ok.", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                                     "required": ["ok"]}, max_tokens=50, timeout=120, c=c)
            out[chave] = "✅ respondeu" if isinstance(r, dict) and r.get("ok") else f"⚠ respondeu estranho: {r}"
        except LocalErro as exc:
            out[chave] = f"❌ {exc}"
    out["ok"] = any(str(v).startswith("✅") for k, v in out.items() if k in ("modelo", "modelo_visao"))
    return out
