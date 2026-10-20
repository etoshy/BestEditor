"""
pod_studio.py — 🖥️ Meu pod: o Studio IA rodando num pod da RunPod (v84_121)
=============================================================================

Cliente do servidor `studio-ia` (pasta à parte, sobe no pod com setup.sh/start.sh). No pod rodam:
  • 🖼 Z-Image Turbo — imagens (o site usa no lugar dos Public Endpoints pagos por imagem: modo "Meu pod" do 🟣 Runpod)
  • 🗣️ Chatterbox — Multilingual V3 (23 idiomas), pacote dedicado pt-BR e Chatterbox Turbo (inglês com tags)

O pod é cobrado por hora (não por geração): ligue, gere tudo, desligue.

Configurações (⚙️ Configurações → 🟣 Runpod):
  runpod_modo          "endpoints" (API paga por geração) | "pod" (imagens no seu pod)
  runpod_pod_url       https://<id-do-pod>-8000.proxy.runpod.net
  runpod_pod_chave     só se você subiu o pod com API_KEY=... (por padrão o pod não pede chave)
  chatterbox_onde      "local" (este PC) | "pod" — vale pro Chatterbox e pro Chatterbox Turbo
  chatterbox_pod_ptbr  português pelo modelo dedicado pt-BR (senão o multilíngue)
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

MOTORES_NO_POD = ("chatterbox", "chatterbox_turbo")
FINAIS = ("concluido", "concluido_com_erros", "erro", "cancelado")


class PodErro(RuntimeError):
    pass


def _cfg(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if cfg is not None and "runpod_pod_url" in cfg:
        return cfg
    try:
        from site_config import load_site_config
        base = load_site_config() or {}
    except Exception:  # noqa: BLE001
        base = {}
    return dict(base, **(cfg or {}))


def url(cfg: Optional[Dict[str, Any]] = None) -> str:
    u = str(_cfg(cfg).get("runpod_pod_url") or os.environ.get("STUDIO_POD_URL") or "").strip().rstrip("/")
    return u if re.fullmatch(r"https?://[^\s\"'<>]+", u) else ""


def configurado(cfg: Optional[Dict[str, Any]] = None) -> bool:
    return bool(url(cfg))


def imagens_no_pod(cfg: Optional[Dict[str, Any]] = None) -> bool:
    c = _cfg(cfg)
    return str(c.get("runpod_modo") or "endpoints") == "pod" and configurado(c)


def motor_no_pod(engine: str, cfg: Optional[Dict[str, Any]] = None) -> bool:
    """Esse motor de voz gera no pod (e não na placa deste PC)?"""
    c = _cfg(cfg)
    return engine in MOTORES_NO_POD and str(c.get("chatterbox_onde") or "local") == "pod" and configurado(c)


def _cabecalhos(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    k = str(_cfg(cfg).get("runpod_pod_chave") or os.environ.get("STUDIO_POD_CHAVE") or "").strip()
    return {"X-API-Key": k} if k else {}


def _pedir(metodo: str, caminho: str, cfg: Optional[Dict[str, Any]] = None, timeout: float = 60, **kw: Any):
    import requests
    base = url(cfg)
    if not base:
        raise PodErro("Sem o endereço do pod — cole em ⚙️ Configurações → 🟣 Runpod → Meu pod.")
    try:
        r = requests.request(metodo, base + caminho, headers=_cabecalhos(cfg), timeout=timeout, **kw)
    except requests.exceptions.ConnectionError:
        raise PodErro(f"O pod não respondeu em {base} — ele está ligado? Rodou o start.sh? A porta 8000 está exposta?")
    except requests.exceptions.Timeout:
        raise PodErro(f"O pod demorou mais de {int(timeout)} s pra responder.")
    if r.status_code == 401:
        raise PodErro("O pod recusou a chave (401) — confira a chave do pod nas Configurações.")
    if r.status_code in (502, 503, 504):
        raise PodErro(f"O pod está fora do ar (HTTP {r.status_code}) — rode o start.sh no pod ou espere ele subir.")
    if r.status_code >= 400:
        try:
            det = r.json().get("detail")
        except Exception:  # noqa: BLE001
            det = r.text[:300]
        raise PodErro(f"O pod respondeu {r.status_code}: {det}")
    return r


def status(cfg: Optional[Dict[str, Any]] = None, timeout: float = 8) -> Dict[str, Any]:
    """{"ok", "msg", "workers", "gpu"} — pra tela de Configurações."""
    if not configurado(cfg):
        return {"ok": False, "msg": "sem o endereço do pod"}
    try:
        d = _pedir("GET", "/status", cfg, timeout=timeout).json()
    except PodErro as exc:
        return {"ok": False, "msg": str(exc)}
    w = d.get("workers") or {}
    partes = [f"{'🖼' if t == 'imagem' else '🗣️'} {t}: {(w.get(t) or {}).get('estado', '?')}" for t in ("imagem", "voz")]
    gpu = d.get("gpu") or []
    if gpu:
        g = gpu[0]
        u, t = g.get("vram_usada_mb"), g.get("vram_total_mb")  # alguns pods não deixam ler a memória (vem None)
        partes.append(f"GPU {g.get('nome') or '?'}" + (f" ({u // 1024}/{t // 1024} GB)" if isinstance(u, int) and isinstance(t, int) else ""))
    return {"ok": True, "msg": " · ".join(partes), "workers": w, "gpu": gpu}


def esperar(job_id: str, cfg: Optional[Dict[str, Any]] = None, timeout_s: float = 1800,
            on_passo: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    fim = time.time() + timeout_s
    pausa = 0.5
    while True:
        st = _pedir("GET", f"/jobs/{job_id}", cfg, timeout=30).json()
        if st.get("status") in FINAIS:
            if st["status"] in ("erro", "cancelado") or not st.get("arquivos"):
                erros = "; ".join(str(e.get("erro")) for e in (st.get("erros") or [])[:3])
                raise PodErro(f"O pod não gerou ({st.get('status')}): {st.get('mensagem') or ''} {erros}".strip())
            return st
        if time.time() > fim:
            raise PodErro(f"O pod não terminou em {int(timeout_s)} s (job {job_id}).")
        if on_passo:
            p = st.get("progresso") or {}
            fila = f", {st['posicao_fila']}º na fila" if st.get("posicao_fila") else ""
            on_passo(f"pod: {st.get('status')} {p.get('feito', 0)}/{p.get('total', 0)}{fila}")
        time.sleep(pausa)
        pausa = min(3.0, pausa * 1.5)


def baixar(job_id: str, arquivo: str, destino: str, cfg: Optional[Dict[str, Any]] = None) -> str:
    r = _pedir("GET", f"/jobs/{job_id}/arquivos/{arquivo}", cfg, timeout=300, stream=True)
    os.makedirs(os.path.dirname(os.path.abspath(destino)) or ".", exist_ok=True)
    tmp = destino + ".parte"
    with open(tmp, "wb") as f:
        for bloco in r.iter_content(1 << 16):
            f.write(bloco)
    os.replace(tmp, destino)
    return destino


# ------------------------------------------------------------------ 🖼 imagem
def gerar_imagem(prompt: str, destino: str, largura: int = 1280, altura: int = 720, seed: Optional[int] = None,
                 passos: int = 9, cfg: Optional[Dict[str, Any]] = None,
                 on_passo: Optional[Callable[[str], None]] = None, timeout_s: float = 900) -> str:
    corpo: Dict[str, Any] = {"prompts": [{"prompt": prompt, "nome": "imagem"}], "nome": "site",
                             "largura": int(largura), "altura": int(altura), "passos": int(passos), "formato": "png"}
    if seed is not None and int(seed) >= 0:
        corpo["seed"] = int(seed)
    job = _pedir("POST", "/imagens", cfg, json=corpo).json()
    st = esperar(job["id"], cfg, timeout_s=timeout_s, on_passo=on_passo)
    nome = next((a for a in st["arquivos"] if a.lower().endswith(".png")), None)
    if not nome:
        raise PodErro(f"O pod terminou mas não mandou a imagem: {st.get('erros') or st.get('mensagem')}")
    return baixar(job["id"], nome, destino, cfg)


# ------------------------------------------------------------------ 🗣️ voz
def narrar(texto: str, destino: str, motor: str = "chatterbox", idioma: str = "pt",
           referencia: Optional[str] = None, perfil: Optional[str] = None,
           exaggeration: float = 0.5, cfg_weight: float = 0.5, temperature: float = 0.8,
           cfg: Optional[Dict[str, Any]] = None, on_passo: Optional[Callable[[str], None]] = None,
           timeout_s: float = 7200) -> str:
    """Narra `texto` no pod e salva o .wav em `destino`. Voz: `referencia` (áudio deste PC, vai junto no pedido)
    ou `perfil` (nome de um perfil já importado no pod). Sem nenhum: voz padrão do modelo."""
    c = _cfg(cfg)
    dados = {"texto": texto, "motor": motor if motor in MOTORES_NO_POD else "chatterbox",
             "idioma": "en" if motor == "chatterbox_turbo" else (idioma or "pt"),
             "exaggeration": str(float(exaggeration)), "cfg_weight": str(float(cfg_weight)),
             "temperature": str(float(temperature)),
             "pacote_dedicado": "true" if c.get("chatterbox_pod_ptbr", True) else "false",
             "marcacoes": "false", "normalizar": "false", "legenda_srt": "false", "nome": "narracao"}
    if perfil and not referencia:
        dados["perfil"] = perfil
    arquivos = None
    if referencia:
        arquivos = {"referencia": (os.path.basename(referencia), open(referencia, "rb"), "application/octet-stream")}
    try:
        job = _pedir("POST", "/voz/texto", c, timeout=120, data=dados, files=arquivos).json()
    finally:
        if arquivos:
            arquivos["referencia"][1].close()
    st = esperar(job["id"], c, timeout_s=timeout_s, on_passo=on_passo)
    nome = next((a for a in st["arquivos"] if a.lower().endswith(".wav")), None)
    if not nome:
        raise PodErro(f"O pod terminou mas não mandou o áudio: {st.get('erros') or st.get('mensagem')}")
    return baixar(job["id"], nome, destino, c)


# ------------------------------------------------------------------ 🏭 pedidos sem esperar (Produção no pod)
def job(job_id: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Status de um job do pod (sem esperar)."""
    return _pedir("GET", f"/jobs/{job_id}", cfg, timeout=30).json()


def cancelar(job_id: str, cfg: Optional[Dict[str, Any]] = None) -> None:
    """Cancela um job no pod (na fila ou rodando) — pra não narrar duas vezes o mesmo roteiro."""
    _pedir("POST", f"/jobs/{job_id}/cancelar", cfg, timeout=15)


def enviar_narracao(texto: str, motor: str = "chatterbox", idioma: str = "pt", referencia: Optional[str] = None,
                    exaggeration: float = 0.5, cfg_weight: float = 0.5, temperature: float = 0.8,
                    transcrever: bool = True, nome: str = "narracao", cfg: Optional[Dict[str, Any]] = None,
                    marcacoes: bool = False) -> str:
    """Põe uma narração na fila do pod e devolve o id do job (o pod narra e, com `transcrever`, transcreve)."""
    c = _cfg(cfg)
    dados = {"texto": texto, "motor": motor if motor in MOTORES_NO_POD else "chatterbox",
             "idioma": "en" if motor == "chatterbox_turbo" else (idioma or "pt"),
             "exaggeration": str(float(exaggeration)), "cfg_weight": str(float(cfg_weight)),
             "temperature": str(float(temperature)),
             "pacote_dedicado": "true" if c.get("chatterbox_pod_ptbr", True) else "false",
             "marcacoes": "true" if marcacoes else "false", "normalizar": "true", "legenda_srt": "false",
             "transcrever": "true" if transcrever else "false", "nome": nome or "narracao",
             "pausa_ms": "180", "pausa_paragrafo_ms": "450"}
    arquivos = None
    if referencia:
        arquivos = {"referencia": (os.path.basename(referencia), open(referencia, "rb"), "application/octet-stream")}
    try:
        return _pedir("POST", "/voz/texto", c, timeout=120, data=dados, files=arquivos).json()["id"]
    finally:
        if arquivos:
            arquivos["referencia"][1].close()


def importar_perfis(zip_bytes: bytes, cfg: Optional[Dict[str, Any]] = None) -> Any:
    """🗣️ Manda perfis de voz pro pod (o .zip do 📦 Exportar) — substitui os de mesmo nome. v84_180."""
    return _pedir("POST", "/vozes/importar", cfg, timeout=300, data={"substituir": "true", "dividir": "false"},
                  files={"arquivo": ("perfis.zip", zip_bytes, "application/zip")}).json()


def enviar_imagens(itens: List[Dict[str, Any]], largura: int = 1280, altura: int = 720, nome: str = "lote",
                   cfg: Optional[Dict[str, Any]] = None) -> str:
    """Um lote de imagens num job só: itens = [{"prompt", "nome", "seed"?}]. Devolve o id do job."""
    corpo = {"prompts": [{k: v for k, v in it.items() if k in ("prompt", "nome", "seed") and v is not None} for it in itens],
             "nome": nome, "largura": int(largura), "altura": int(altura), "passos": 9, "formato": "png"}
    return _pedir("POST", "/imagens", cfg, timeout=120, json=corpo).json()["id"]


def enviar_imagens_com_refs(itens: List[Dict[str, Any]], largura: int = 1280, altura: int = 720, nome: str = "lote",
                            cfg: Optional[Dict[str, Any]] = None) -> Tuple[str, bool]:
    """🎭 Igual ao enviar_imagens, mas itens podem ter "referencias": [[nome do arquivo, caminho no PC], …] — o pod usa
    o FLUX.2 klein nesses (rosto da foto). → (id do job, True se o pod é antigo e foi tudo sem as fotos)."""
    if not any(it.get("referencias") for it in itens):
        return enviar_imagens(itens, largura=largura, altura=altura, nome=nome, cfg=cfg), False
    import json as _json
    arquivos: Dict[str, str] = {}
    prompts = []
    for it in itens:
        item = {k: v for k, v in it.items() if k in ("prompt", "nome", "seed") and v is not None}
        if it.get("referencias"):
            item["referencias"] = []
            for n, cam in it["referencias"]:
                arquivos.setdefault(n, cam)
                item["referencias"].append(n)
        prompts.append(item)
    corpo = {"prompts": prompts, "nome": nome, "largura": int(largura), "altura": int(altura), "passos": 9, "formato": "png"}
    abertos = []
    try:
        files = []
        for n, cam in arquivos.items():
            f = open(cam, "rb")
            abertos.append(f)
            files.append(("arquivos", (n, f, "image/png" if n.endswith(".png") else "image/jpeg")))
        try:
            r = _pedir("POST", "/imagens/referencias", cfg, timeout=300, data={"pedido": _json.dumps(corpo, ensure_ascii=False)},
                       files=files)
            return r.json()["id"], False
        except PodErro as exc:
            if "respondeu 404" not in str(exc) and "respondeu 405" not in str(exc):
                raise
    finally:
        for f in abertos:
            f.close()
    sem = [{k: v for k, v in it.items() if k != "referencias"} for it in itens]  # pod antigo: tudo no Z-Image
    return enviar_imagens(sem, largura=largura, altura=altura, nome=nome, cfg=cfg), True
