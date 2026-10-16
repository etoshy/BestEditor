"""
runpod_gerador.py — 🟣 Runpod: imagens e vídeos gerados por IA (v84_116)
=========================================================================

Outro gerador além do Google Flow, pela API paga do Runpod (Public Endpoints, cobra por geração do saldo da conta):

  • 🖼 Z-Image Turbo (`z-image-turbo`) — imagem, US$ 0,005 cada (rápida, 6B; entende inglês e chinês)
  • 🖼 Flux Schnell (`black-forest-labs-flux-1-schnell`) — imagem, ~US$ 0,0025 por megapixel (aceita prompt negativo)
  • 🎬 Pruna Video (`p-video`) — vídeo de 1–10 s, US$ 0,02/s em 720p (0,005/s no modo rascunho)

Cada modelo recebe o pedido do jeito que ele entende melhor (`adaptar`): em inglês, com o estilo do vídeo, a proporção
certa, prompt negativo onde existe (Flux), movimento de câmera no vídeo… Com a 🤖 IA do site ligada, ela escreve o
prompt de cada modelo a partir da descrição da cena; sem ela, uma regra simples.

💰 O SALDO da conta é conferido antes de cada geração (`saldo()`, pela API GraphQL do Runpod, guardado 60 s): sem saldo
pra pagar o pedido, ele nem é enviado (`RunpodSemSaldo` → o site segue sem o Runpod: foto, outro banco, pesquisa).

Tudo que é gerado fica em `runpod_dados/midias/` com um registro (`cache.json`): o mesmo pedido (modelo + descrição +
proporção) nunca é gerado (nem cobrado) duas vezes — a exportação reaproveita o que a prévia já gerou.

Chave: ⚙️ Configurações → 🟣 Runpod (fica em site_config.json, que não vai pro GitHub) ou a variável RUNPOD_API_KEY.

🖥️ MODO "MEU POD" (v84_121, `runpod_modo = "pod"`): as IMAGENS saem do Z-Image Turbo rodando no SEU pod (servidor
`studio-ia`, ver pod_studio.py) — o pod é cobrado por hora, então não há custo por imagem nem conferência de saldo.
Vídeo continua pelos Public Endpoints (precisa da chave); sem chave, o trecho de vídeo vira foto como sempre.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

API = "https://api.runpod.ai/v2"
GRAPHQL = "https://api.runpod.io/graphql"
_BASE = os.path.dirname(os.path.abspath(__file__))
URL_MIDIAS = "/runpod/midias/"

MODELOS: Dict[str, Dict[str, Any]] = {
    "z-image-turbo": {"nome": "Z-Image Turbo (rápida, US$ 0,005/imagem)", "tipo": "imagem", "negativo": False,
                      "custo": lambda p: 0.005},
    "black-forest-labs-flux-1-schnell": {"nome": "Flux Schnell (aceita prompt negativo, ~US$ 0,0025/MP)", "tipo": "imagem",
                                         "negativo": True,
                                         "custo": lambda p: round(p.get("width", 1024) * p.get("height", 1024) / 1e6 * 0.0024, 5)},
    "p-video": {"nome": "Pruna Video (US$ 0,02/s em 720p; rascunho 0,005/s)", "tipo": "video", "negativo": False,
                "custo": lambda p: (0.04 if p.get("resolution") == "1080p" else 0.02) * (0.25 if p.get("draft") else 1.0)
                * int(p.get("duration") or 5)},
}
IMAGEM_PADRAO = "z-image-turbo"
VIDEO_PADRAO = "p-video"
NEGATIVO_PADRAO = ("text, letters, words, caption, watermark, logo, signature, blurry, low quality, jpeg artifacts, deformed, "
                   "bad anatomy, extra fingers, distorted face")
NEGATIVO_REAL = ", cartoon, illustration, drawing, anime, 3d render, cgi, painting"


class RunpodErro(RuntimeError):
    pass


class RunpodSemChave(RunpodErro):
    pass


class RunpodSemSaldo(RunpodErro):
    pass


# ------------------------------------------------------------------ config
def pasta() -> str:
    p = os.environ.get("RUNPOD_DADOS_DIR") or os.path.join(_BASE, "runpod_dados")
    os.makedirs(os.path.join(p, "midias"), exist_ok=True)
    return p


def _cfg(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if cfg is not None and "runpod_api_key" in cfg:
        return cfg
    try:
        from site_config import load_site_config
        base = load_site_config()
    except Exception:  # noqa: BLE001
        base = {}
    return dict(base, **(cfg or {}))


def chave(cfg: Optional[Dict[str, Any]] = None) -> str:
    return str(_cfg(cfg).get("runpod_api_key") or os.environ.get("RUNPOD_API_KEY") or "").strip()


def chave_mascarada(cfg: Optional[Dict[str, Any]] = None) -> str:
    k = chave(cfg)
    return (k[:6] + "…" + k[-4:]) if len(k) > 12 else ("…" if k else "")


def modo(cfg: Optional[Dict[str, Any]] = None) -> str:
    """"pod" (imagens no seu pod, ver pod_studio.py) ou "endpoints" (API paga por geração)."""
    c = _cfg(cfg)
    return "pod" if str(c.get("runpod_modo") or "") == "pod" and str(c.get("runpod_pod_url") or "").strip() else "endpoints"


def configurado(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Tem chave, ou tem o endereço do seu pod (as imagens feitas na 🏭 Produção no pod ficam no cache)."""
    return bool(chave(cfg)) or modo(cfg) == "pod" or bool(str(_cfg(cfg).get("runpod_pod_url") or "").strip())


def modelo_imagem(cfg: Optional[Dict[str, Any]] = None) -> str:
    m = str(_cfg(cfg).get("runpod_modelo_imagem") or IMAGEM_PADRAO)
    return m if m in MODELOS and MODELOS[m]["tipo"] == "imagem" else IMAGEM_PADRAO


def modelo_video(cfg: Optional[Dict[str, Any]] = None) -> str:
    m = str(_cfg(cfg).get("runpod_modelo_video") or VIDEO_PADRAO)
    return m if m in MODELOS and MODELOS[m]["tipo"] == "video" else VIDEO_PADRAO


# ------------------------------------------------------------------ HTTP (trocável nos testes)
def _http(metodo: str, url: str, chave_api: str, corpo: Optional[Dict[str, Any]] = None, timeout: float = 120) -> Dict[str, Any]:
    import requests
    r = requests.request(metodo, url, json=corpo, timeout=timeout,
                         headers={"Authorization": f"Bearer {chave_api}", "Content-Type": "application/json"})
    if r.status_code == 401:
        raise RunpodSemChave("O Runpod recusou a chave (401) — confira a chave da API em ⚙️ Configurações → 🟣 Runpod.")
    if r.status_code == 402:
        raise RunpodSemSaldo("O Runpod disse que não tem saldo (402) — recarregue em console.runpod.io → Billing.")
    try:
        dados = r.json()
    except ValueError:
        dados = {"erro_http": r.text[:300]}
    if r.status_code >= 400:
        msg = str(dados.get("error") or dados.get("erro_http") or dados)[:300]
        if re.search(r"insufficient|balance|saldo|funds|credit", msg, re.I):
            raise RunpodSemSaldo(f"Sem saldo no Runpod: {msg}")
        raise RunpodErro(f"Runpod respondeu {r.status_code}: {msg}")
    return dados


def _baixar(url: str, destino: str, timeout: float = 300) -> str:
    import requests
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        import uuid
        import arquivo_seguro
        tmp = f"{destino}.{uuid.uuid4().hex[:8]}.parte"
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(1 << 16):
                f.write(bloco)
    arquivo_seguro.trocar(tmp, destino)
    return destino


# ------------------------------------------------------------------ 💰 saldo
_SALDO: Dict[str, Any] = {"valor": None, "quando": 0.0, "erro": None, "gasto_hora": None, "chave": ""}
_SALDO_TRAVA = threading.Lock()
SALDO_VALIDADE_S = 60


def saldo(cfg: Optional[Dict[str, Any]] = None, forcar: bool = False) -> Dict[str, Any]:
    """{"saldo": US$, "gasto_hora", "quando", "erro"} — pergunta ao Runpod no máximo 1× por minuto (ou `forcar`)."""
    k = chave(cfg)
    if not k:
        return {"saldo": None, "erro": "sem chave do Runpod", "quando": None}
    with _SALDO_TRAVA:
        fresco = _SALDO["chave"] == k and _SALDO["valor"] is not None and time.time() - _SALDO["quando"] < SALDO_VALIDADE_S
        if fresco and not forcar:
            return {"saldo": _SALDO["valor"], "gasto_hora": _SALDO["gasto_hora"], "quando": _SALDO["quando"], "erro": None}
    try:
        consulta = {"query": "query { myself { clientBalance currentSpendPerHr spendLimit } }"}
        try:
            d = _http("POST", GRAPHQL, k, consulta, timeout=30)
        except RunpodSemSaldo:
            raise
        except RunpodErro:  # a API GraphQL também aceita a chave na URL (jeito antigo)
            d = _http("POST", f"{GRAPHQL}?api_key={k}", k, consulta, timeout=30)
        eu = ((d.get("data") or {}).get("myself") or {})
        if "clientBalance" not in eu:
            raise RunpodErro(str(d.get("errors") or d)[:200])
        valor = float(eu.get("clientBalance") or 0)
        with _SALDO_TRAVA:
            _SALDO.update(valor=valor, quando=time.time(), erro=None, gasto_hora=eu.get("currentSpendPerHr"), chave=k)
        return {"saldo": valor, "gasto_hora": eu.get("currentSpendPerHr"), "quando": _SALDO["quando"], "erro": None}
    except RunpodErro as exc:
        with _SALDO_TRAVA:
            _SALDO.update(erro=str(exc), chave=k)
        return {"saldo": None, "erro": str(exc), "quando": None}
    except Exception as exc:  # noqa: BLE001 — sem internet etc.: não bloqueia (o Runpod recusa se faltar mesmo)
        return {"saldo": None, "erro": f"não consegui ver o saldo: {exc}", "quando": None}


def _descontar(custo: float) -> None:
    with _SALDO_TRAVA:
        if _SALDO["valor"] is not None:
            _SALDO["valor"] = round(float(_SALDO["valor"]) - float(custo or 0), 5)


def conferir_saldo(custo: float, cfg: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """Antes de gerar: levanta RunpodSemSaldo se o saldo não paga `custo`. Devolve o saldo (None = não deu pra ver)."""
    s = saldo(cfg)
    if s.get("saldo") is not None and float(s["saldo"]) < float(custo):
        raise RunpodSemSaldo(f"Saldo do Runpod: US$ {s['saldo']:.4f} — não paga este pedido (~US$ {custo:.4f}). "
                             "Recarregue em console.runpod.io → Billing.")
    return s.get("saldo")


def tem_saldo(tipo: str = "imagem", cfg: Optional[Dict[str, Any]] = None) -> Optional[bool]:
    """Dá pra gerar `tipo` agora? None = não sei (sem internet) / False = sem chave ou sem saldo."""
    if not configurado(cfg):
        return False
    if modo(cfg) == "pod" and tipo != "video":
        return True  # no seu pod não tem custo por imagem
    if not chave(cfg):
        return False
    m = modelo_video(cfg) if tipo == "video" else modelo_imagem(cfg)
    custo = MODELOS[m]["custo"](parametros_base(m, cfg))
    s = saldo(cfg)
    if s.get("saldo") is None:
        return None
    return float(s["saldo"]) >= custo


def _registrar_uso(modelo: str, custo: float, descricao: str) -> None:
    with _CACHE_TRAVA:
        _registrar_uso_(modelo, custo, descricao)


def _registrar_uso_(modelo: str, custo: float, descricao: str) -> None:
    caminho = os.path.join(pasta(), "uso.json")
    try:
        with open(caminho, encoding="utf-8") as f:
            uso = json.load(f)
    except (OSError, ValueError):
        uso = {"total": 0.0, "por_modelo": {}, "ultimos": []}
    uso["total"] = round(float(uso.get("total") or 0) + float(custo or 0), 5)
    uso.setdefault("por_modelo", {})[modelo] = round(float(uso["por_modelo"].get(modelo) or 0) + float(custo or 0), 5)
    uso.setdefault("ultimos", []).append({"quando": time.time(), "modelo": modelo, "custo": custo, "descricao": descricao[:160]})
    uso["ultimos"] = uso["ultimos"][-50:]
    import arquivo_seguro  # nome temporário único + novas tentativas (WinError 5 no Windows)
    arquivo_seguro.gravar_json(caminho, uso, indent=1)


def uso() -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(), "uso.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"total": 0.0, "por_modelo": {}, "ultimos": []}


# ------------------------------------------------------------------ ✍️ o pedido de cada modelo
def _orientacao(cfg: Optional[Dict[str, Any]]) -> str:
    o = str((cfg or {}).get("orientation") or "16:9")
    return o if o in ("16:9", "9:16", "1:1") else "16:9"


def parametros_base(modelo: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Tamanho/proporção e opções de cada modelo (sem o prompt)."""
    o = _orientacao(cfg)
    c = _cfg(cfg)
    if modelo == "z-image-turbo":
        return {"size": {"16:9": "1280*720", "9:16": "720*1280", "1:1": "1024*1024"}[o], "seed": -1, "output_format": "png",
                "enable_safety_checker": True}
    if modelo == "black-forest-labs-flux-1-schnell":
        w, h = {"16:9": (1344, 768), "9:16": (768, 1344), "1:1": (1024, 1024)}[o]  # múltiplos de 64, até 1536
        return {"width": w, "height": h, "num_inference_steps": 4, "guidance": 3.5, "seed": -1, "image_format": "png"}
    if modelo == "p-video":
        try:
            dur = max(1, min(10, int(c.get("runpod_video_duracao") or 5)))
        except (TypeError, ValueError):
            dur = 5
        return {"duration": dur, "resolution": "1080p" if c.get("runpod_video_1080p") else "720p", "fps": 24,
                "aspect_ratio": o, "draft": bool(c.get("runpod_video_rascunho")), "save_audio": False,
                "prompt_upsampling": True}
    return {}


_GUIA = {
    "z-image-turbo": (
        "Z-Image Turbo (difusão 6B, texto→imagem). Escreva em INGLÊS, uma descrição visual rica e concreta em frases curtas: "
        "assunto principal primeiro, depois ação, cenário, época, roupas, materiais, luz (ex.: soft window light, golden hour), "
        "enquadramento e lente (close-up, wide shot, 35mm), estilo (photorealistic documentary photo…). 40–90 palavras. "
        "NÃO existe prompt negativo: diga o que QUER (ex.: 'clean frame without any text'). Sem texto/letreiros na imagem."),
    "black-forest-labs-flux-1-schnell": (
        "Flux Schnell (rápido, 4 passos). Escreva em INGLÊS, direto e ordenado: assunto → ação → cenário → luz → câmera → estilo. "
        "30–70 palavras, sem listas de adjetivos repetidos. TEM prompt negativo: mande em \"negative_prompt\" o que deve ficar de "
        "fora (texto, marca d'água, deformações, e — se o vídeo é de imagens reais — desenho/3D)."),
    "p-video": (
        "Pruna Video (texto→vídeo curto, 1–10 s). Escreva em INGLÊS UMA tomada contínua: o que aparece, o que SE MOVE (ação "
        "do assunto, vento, fumaça, água, multidão) e o MOVIMENTO DE CÂMERA (slow push-in, gentle pan left, static tripod, "
        "drone flyover…), luz e estilo (cinematic documentary footage). Sem cortes, sem texto na tela, sem falas. 40–80 palavras."),
}


def _estilo(cfg: Optional[Dict[str, Any]]) -> str:
    c = cfg or {}
    est = str(c.get("_estilo_ficha") or c.get("estilo_imagens") or "").lower()
    return "ilustracao" if any(x in est for x in ("ilustr", "desenho", "anima", "cartoon")) else "real"


def _regra(modelo: str, descricao: str, cfg: Optional[Dict[str, Any]]) -> Dict[str, str]:
    d = " ".join((descricao or "").split()).rstrip(".")
    real = _estilo(cfg) == "real"
    estilo = ("photorealistic documentary photograph, natural light, sharp focus, high detail" if real
              else "detailed digital illustration, cohesive color palette")
    if modelo == "p-video":
        return {"prompt": f"{d}. Cinematic {'documentary ' if real else ''}footage, one continuous shot, slow camera movement, "
                          "natural motion, realistic lighting, no text on screen."}
    out = {"prompt": f"{d}. {estilo.capitalize()}, clean frame without any text or watermark."}
    if MODELOS.get(modelo, {}).get("negativo"):
        out["negative_prompt"] = NEGATIVO_PADRAO + (NEGATIVO_REAL if real else "")
    return out


def adaptar(modelo: str, descricao: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """O pedido completo (input do Runpod) desse modelo pra essa cena: prompt do jeito do modelo (+ negativo onde
    existe) e os parâmetros (tamanho, duração…). 🤖 IA do site se ligada (recurso "runpod_prompt"), senão regra."""
    p = dict(parametros_base(modelo, cfg))
    escrito: Optional[Dict[str, str]] = None
    try:
        import ia_servico
        if ia_servico.ativo("runpod_prompt"):
            contexto = []
            if (cfg or {}).get("_estilo_ficha"):
                contexto.append(f"Estilo visual do vídeo: {cfg['_estilo_ficha']}")
            contexto.append("Vídeo de imagens REAIS (fotografia/filmagem)." if _estilo(cfg) == "real" else "Vídeo ilustrado.")
            if modelo == "p-video":
                contexto.append(f"Duração da tomada: {p.get('duration')} s, proporção {p.get('aspect_ratio')}.")
            sistema = ("Você escreve prompts pra modelos de geração de imagem/vídeo. Recebe a DESCRIÇÃO DA CENA (em qualquer "
                       "idioma) de um trecho de vídeo de YouTube e escreve o prompt ideal pro modelo abaixo. Nada de pessoas "
                       "reais/famosas pelo nome, marcas, logotipos ou texto escrito na imagem.\n\nModelo: " + _GUIA[modelo] +
                       "\n\nResponda SÓ com JSON: {\"prompt\": \"...\"" +
                       (", \"negative_prompt\": \"...\"" if MODELOS[modelo]["negativo"] else "") + "}")
            r = ia_servico.chamar("runpod_prompt", sistema, "\n".join(contexto) + f"\n\nDescrição da cena:\n{descricao}",
                                  schema={"type": "object", "properties": {"prompt": {"type": "string"},
                                                                           "negative_prompt": {"type": "string"}},
                                          "required": ["prompt"]}, max_tokens=500)
            if isinstance(r, dict) and str(r.get("prompt") or "").strip():
                escrito = {"prompt": str(r["prompt"]).strip()[:1500]}
                if MODELOS[modelo]["negativo"]:
                    escrito["negative_prompt"] = str(r.get("negative_prompt") or NEGATIVO_PADRAO).strip()[:600]
                escrito["_por"] = "ia"
    except Exception:  # noqa: BLE001
        escrito = None
    escrito = escrito or dict(_regra(modelo, descricao, cfg), _por="regra")
    p.update({k: v for k, v in escrito.items() if not k.startswith("_")})
    p["_por"] = escrito.get("_por", "regra")
    return p


# ------------------------------------------------------------------ cache (o mesmo pedido nunca é cobrado 2×)
_CACHE_TRAVA = threading.RLock()


def chave_pedido(modelo: str, descricao: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    base = parametros_base(modelo, cfg)
    bruto = json.dumps([modelo, " ".join((descricao or "").lower().split()), base.get("size") or [base.get("width"), base.get("height")]
                        or base.get("aspect_ratio"), base.get("aspect_ratio"), base.get("duration"), base.get("resolution"),
                        base.get("draft")], ensure_ascii=False)
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()


def _cache() -> Dict[str, Any]:
    try:
        with open(os.path.join(pasta(), "cache.json"), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def do_cache(chave_p: str) -> Optional[Dict[str, Any]]:
    r = _cache().get(chave_p)
    if r and os.path.isfile(os.path.join(pasta(), "midias", r.get("arquivo", ""))):
        return r
    return None


def _guardar(chave_p: str, registro: Dict[str, Any]) -> None:
    with _CACHE_TRAVA:
        d = _cache()
        d[chave_p] = registro
        import arquivo_seguro  # nome temporário único + novas tentativas (WinError 5 no Windows)
        arquivo_seguro.gravar_json(os.path.join(pasta(), "cache.json"), d, indent=1)


def ja_gerado(descricao: str, tipo: str, cfg: Optional[Dict[str, Any]] = None) -> bool:
    m = modelo_video(cfg) if tipo == "video" else modelo_imagem(cfg)
    return do_cache(chave_pedido(m, descricao, cfg)) is not None


def arquivo_local(url: Any) -> Optional[str]:
    """"/runpod/midias/<arquivo>" → o caminho no disco (ou None)."""
    m = re.search(r"/runpod/midias/([^/?#]+)", str(url or ""))
    if not m:
        return None
    c = os.path.join(pasta(), "midias", os.path.basename(m.group(1)))
    return c if os.path.isfile(c) else None


# ------------------------------------------------------------------ gerar
def _rodar(modelo: str, entrada: Dict[str, Any], k: str, timeout_s: float = 900,
           on_passo: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    d = _http("POST", f"{API}/{modelo}/runsync", k, {"input": entrada}, timeout=180)
    fim = time.time() + timeout_s
    while d.get("status") in ("IN_QUEUE", "IN_PROGRESS") and d.get("id"):  # demorou mais que o runsync espera: acompanha
        if time.time() > fim:
            raise RunpodErro(f"O Runpod não terminou em {int(timeout_s)} s (pedido {d.get('id')}).")
        if on_passo:
            on_passo(f"Runpod: {d.get('status')}…")
        time.sleep(3)
        d = _http("GET", f"{API}/{modelo}/status/{d['id']}", k, timeout=60)
    if d.get("status") != "COMPLETED":
        msg = str(d.get("error") or d.get("output") or d)[:400]
        if re.search(r"insufficient|balance|funds|credit", msg, re.I):
            raise RunpodSemSaldo(f"Sem saldo no Runpod: {msg}")
        if re.search(r"nsfw|safety|policy|moderat", msg, re.I):
            raise RunpodErro(f"O Runpod recusou a cena (filtro de segurança): {msg}")
        raise RunpodErro(f"O Runpod não gerou ({d.get('status')}): {msg}")
    return d.get("output") or {}


def gerar(descricao: str, tipo: str = "imagem", cfg: Optional[Dict[str, Any]] = None, forcar: bool = False,
          on_passo: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Gera (ou reaproveita) a mídia dessa cena. → registro {"arquivo", "caminho", "url", "modelo", "prompt", "custo", …}."""
    cfg = _cfg(cfg)
    if tipo != "video" and not forcar:  # 🏭 já gerada em lote no pod (Produção no pod): usa, em qualquer modo
        r = do_cache(chave_pedido("z-image-turbo", descricao, cfg))
        if r:
            return dict(r, caminho=os.path.join(pasta(), "midias", r["arquivo"]), url=URL_MIDIAS + r["arquivo"], reaproveitado=True)
    if tipo != "video" and modo(cfg) == "pod":
        return _gerar_no_pod(descricao, cfg, forcar=forcar, on_passo=on_passo)
    k = chave(cfg)
    if not k:
        if tipo == "video" and modo(cfg) == "pod":
            raise RunpodSemChave("Vídeo não roda no seu pod (só imagem): pra vídeo pelo Runpod precisa da chave dos "
                                 "Public Endpoints — sem ela o trecho vira foto.")
        raise RunpodSemChave("Sem chave do Runpod — coloque em ⚙️ Configurações → 🟣 Runpod.")
    modelo = modelo_video(cfg) if tipo == "video" else modelo_imagem(cfg)
    ch = chave_pedido(modelo, descricao, cfg)
    if not forcar:
        r = do_cache(ch)
        if r:
            return dict(r, caminho=os.path.join(pasta(), "midias", r["arquivo"]), url=URL_MIDIAS + r["arquivo"], reaproveitado=True)
    entrada = adaptar(modelo, descricao, cfg)
    por = entrada.pop("_por", "regra")
    custo_est = MODELOS[modelo]["custo"](entrada)
    conferir_saldo(custo_est, cfg)  # 💰 sem saldo: nem envia
    if on_passo:
        on_passo(f"Runpod: gerando com {modelo} (~US$ {custo_est:.4f})…")
    saida = _rodar(modelo, entrada, k, on_passo=on_passo)
    url = saida.get("video_url") or saida.get("image_url") or saida.get("url") or \
        (saida.get("images") or [None])[0] if isinstance(saida, dict) else None
    if not url:
        raise RunpodErro(f"O Runpod terminou mas não mandou o link da mídia: {str(saida)[:200]}")
    ext = ".mp4" if tipo == "video" else (os.path.splitext(str(url).split("?")[0])[1].lower() or ".png")
    if ext not in (".mp4", ".png", ".jpg", ".jpeg", ".webp"):
        ext = ".mp4" if tipo == "video" else ".png"
    nome = f"rp_{ch[:16]}{ext}"
    caminho = os.path.join(pasta(), "midias", nome)
    _baixar(url, caminho)  # o link do Runpod expira em 7 dias: baixa na hora
    custo = float(saida.get("cost") if isinstance(saida.get("cost"), (int, float)) else custo_est)
    miniatura = ""
    if tipo == "video":
        miniatura = _miniatura(caminho)
    reg = {"arquivo": nome, "tipo": tipo, "modelo": modelo, "descricao": descricao[:600], "prompt": entrada.get("prompt"),
           "negative_prompt": entrada.get("negative_prompt"), "prompt_por": por, "custo": custo, "quando": time.time(),
           "miniatura": miniatura}
    _guardar(ch, reg)
    _descontar(custo)
    try:
        _registrar_uso(modelo, custo, descricao)
    except OSError:
        pass
    return dict(reg, caminho=caminho, url=URL_MIDIAS + nome, reaproveitado=False)


def _tamanho_pod(cfg: Optional[Dict[str, Any]]) -> tuple:
    return {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}[_orientacao(cfg)]


def _gerar_no_pod(descricao: str, cfg: Dict[str, Any], forcar: bool = False,
                  on_passo: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """🖥️ Imagem no SEU pod (Z-Image Turbo): mesmo cache e mesmo registro do modo pago, custo 0."""
    import pod_studio
    modelo = "z-image-turbo"
    ch = chave_pedido(modelo, descricao, cfg)
    if not forcar:
        r = do_cache(ch)
        if r:
            return dict(r, caminho=os.path.join(pasta(), "midias", r["arquivo"]), url=URL_MIDIAS + r["arquivo"], reaproveitado=True)
    entrada = adaptar(modelo, descricao, cfg)  # o prompt do jeito do Z-Image (🤖 IA ou regra)
    por = entrada.pop("_por", "regra")
    w, h = _tamanho_pod(cfg)
    if on_passo:
        on_passo("Runpod (meu pod): gerando com Z-Image Turbo…")
    nome = f"rp_{ch[:16]}.png"
    caminho = os.path.join(pasta(), "midias", nome)
    try:
        pod_studio.gerar_imagem(entrada.get("prompt") or descricao, caminho, largura=w, altura=h, cfg=cfg, on_passo=on_passo)
    except pod_studio.PodErro as exc:
        raise RunpodErro(str(exc)) from exc
    reg = {"arquivo": nome, "tipo": "imagem", "modelo": "pod:" + modelo, "descricao": descricao[:600],
           "prompt": entrada.get("prompt"), "negative_prompt": None, "prompt_por": por, "custo": 0.0,
           "quando": time.time(), "miniatura": ""}
    _guardar(ch, reg)
    try:
        _registrar_uso("pod:" + modelo, 0.0, descricao)
    except OSError:
        pass
    return dict(reg, caminho=caminho, url=URL_MIDIAS + nome, reaproveitado=False)


def guardar_do_pod(descricao: str, arquivo: str, prompt: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """🏭 Produção no pod: uma imagem gerada em LOTE no pod entra no cache como se a fonte `runpod` tivesse gerado
    essa `descricao` — quando o editor buscar a prévia do trecho, acha pronta (sem gerar de novo)."""
    cfg = _cfg(cfg)
    modelo = "z-image-turbo"
    ch = chave_pedido(modelo, descricao, cfg)
    nome = f"rp_{ch[:16]}.png"
    destino = os.path.join(pasta(), "midias", nome)
    shutil.copyfile(arquivo, destino)
    reg = {"arquivo": nome, "tipo": "imagem", "modelo": "pod:" + modelo, "descricao": descricao[:600], "prompt": prompt,
           "negative_prompt": None, "prompt_por": "lote", "custo": 0.0, "quando": time.time(), "miniatura": ""}
    _guardar(ch, reg)
    return dict(reg, caminho=destino, url=URL_MIDIAS + nome)


def _miniatura(video: str) -> str:
    alvo = os.path.splitext(video)[0] + "_mini.jpg"
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", video, "-frames:v", "1", "-vf", "scale=480:-2", alvo],
                       capture_output=True, timeout=60)
    except Exception:  # noqa: BLE001
        return ""
    return os.path.basename(alvo) if os.path.isfile(alvo) else ""


# ------------------------------------------------------------------ cliente no formato dos bancos (pra montagem/prévia)
@dataclass
class RunpodFoto:
    id: str
    url: str
    sizes: Dict[str, str]
    description: str
    author: str = "Runpod (IA)"
    local_path: str = ""


@dataclass
class RunpodVideo:
    id: str
    url: str
    thumbnail: str = ""
    description: str = ""
    author: str = "Runpod (IA)"
    local_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "thumbnail": self.thumbnail, "title": self.description[:60], "author": self.author,
                "url": self.url, "video_preview_url": self.url}


class _SessaoNula:
    def close(self) -> None:
        pass


class RunpodClient:
    """Banco "runpod": a "busca" GERA (ou reaproveita) a mídia da descrição da cena — igual ao provedor "flow"."""

    def __init__(self, site_cfg: Optional[Dict[str, Any]] = None, **_k: Any):
        self.cfg = _cfg(site_cfg)
        self.session = _SessaoNula()
        if not configurado(self.cfg):
            raise RunpodSemChave("Sem chave do Runpod — coloque em ⚙️ Configurações → 🟣 Runpod.")

    def search_photos_all(self, query: str, max_pages: int = 1, **_k: Any) -> List[RunpodFoto]:
        r = gerar(query, "imagem", self.cfg)
        return [RunpodFoto(id=r["arquivo"], url=r["url"], sizes={"tiny": r["url"], "small": r["url"], "original": r["url"]},
                           description=r.get("prompt") or query, local_path=r["caminho"])]

    def search_all(self, query: str = "", max_pages: int = 1, **_k: Any) -> List[RunpodVideo]:
        r = gerar(query, "video", self.cfg)
        mini = (URL_MIDIAS + r["miniatura"]) if r.get("miniatura") else ""
        return [RunpodVideo(id=r["arquivo"], url=r["url"], thumbnail=mini, description=r.get("prompt") or query,
                            local_path=r["caminho"])]

    def _copiar(self, origem: str, output_dir: Optional[str]) -> str:
        if not origem or not os.path.exists(origem):
            raise RunpodErro(f"Arquivo gerado pelo Runpod não encontrado: {origem!r}")
        if not output_dir:
            return origem
        os.makedirs(output_dir, exist_ok=True)
        destino = os.path.join(output_dir, os.path.basename(origem))
        shutil.copyfile(origem, destino)
        return destino

    def download_photo(self, photo: RunpodFoto, output_dir: Optional[str] = None, **_k: Any) -> str:
        return self._copiar(photo.local_path, output_dir)

    def download_video(self, video: RunpodVideo, output_dir: Optional[str] = None, **_k: Any) -> str:
        return self._copiar(video.local_path, output_dir)


def resumo(cfg: Optional[Dict[str, Any]] = None, forcar: bool = False, rede: bool = True) -> Dict[str, Any]:
    """Pra tela de Configurações: chave (mascarada), modelos, saldo e quanto já foi gasto pelo site.
    `rede=False`: só o saldo já conhecido (a página abre na hora e pergunta o saldo depois)."""
    if not chave(cfg):
        s = {"saldo": None, "erro": "sem chave"}
    elif rede:
        s = saldo(cfg, forcar=forcar)
    else:
        s = {"saldo": _SALDO["valor"] if _SALDO["chave"] == chave(cfg) else None, "erro": None, "gasto_hora": _SALDO["gasto_hora"]}
    u = uso()
    return {"configurado": configurado(cfg), "chave": chave_mascarada(cfg), "saldo": s.get("saldo"), "erro": s.get("erro"),
            "gasto_hora": s.get("gasto_hora"), "gasto_site": u.get("total") or 0.0, "por_modelo": u.get("por_modelo") or {},
            "modelo_imagem": modelo_imagem(cfg), "modelo_video": modelo_video(cfg),
            "tem_chave": bool(chave(cfg)), "modo": modo(cfg), "pod_url": str(_cfg(cfg).get("runpod_pod_url") or ""),
            "modelos": [{"id": m, "nome": v["nome"], "tipo": v["tipo"]} for m, v in MODELOS.items()]}


def registrar(app) -> None:
    """Rotas: as mídias geradas, o saldo e um teste rápido."""
    from flask import jsonify, request, send_from_directory

    @app.route("/runpod/midias/<path:nome>")
    def runpod_midia(nome: str):
        return send_from_directory(os.path.join(pasta(), "midias"), os.path.basename(nome))

    @app.route("/runpod/saldo")
    def runpod_saldo():
        return jsonify(resumo(forcar=request.args.get("forcar") == "1"))

    @app.route("/runpod/pod-status")
    def runpod_pod_status():
        import pod_studio
        url = (request.args.get("url") or "").strip()
        return jsonify(pod_studio.status(dict(pod_studio._cfg(None), runpod_pod_url=url) if url else None))

    @app.route("/runpod/testar", methods=["POST"])
    def runpod_testar():
        d = request.get_json(silent=True) or {}
        tipo = "video" if d.get("tipo") == "video" else "imagem"
        try:
            r = gerar(str(d.get("descricao") or "a lighthouse on a cliff at sunset, ocean waves"), tipo, forcar=bool(d.get("forcar")))
        except RunpodErro as exc:
            return jsonify({"erro": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"erro": f"{type(exc).__name__}: {exc}"}), 400
        return jsonify({"ok": True, "url": r["url"], "prompt": r.get("prompt"), "negative_prompt": r.get("negative_prompt"),
                        "prompt_por": r.get("prompt_por"), "custo": r.get("custo"), "reaproveitado": r.get("reaproveitado"),
                        "saldo": saldo().get("saldo")})
