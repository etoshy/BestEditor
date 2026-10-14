"""
tarefas_bg.py
=============

⏳ TAREFAS DE SEGUNDO PLANO GENÉRICAS — pra tudo que antes precisava ficar com a aba aberta esperando a resposta
(🤖 "Gerar com a IA" dos roteiros, 🪄 prompt de edição pela IA, ✅ checar fatos, 🔗 extrair links de canal…).

Agora a página só INICIA a tarefa e pode ser fechada:
  • o servidor roda e guarda o resultado em outputs/tarefas/<id>.json (sobrevive a fechar o site);
  • ao terminar, chega uma 🔔 notificação com o link da página;
  • voltando na página, ela vê a tarefa pronta e aplica sozinha (preenche a resposta / mostra o resultado) — e marca
    como "aplicada" pra não aplicar duas vezes;
  • tudo fica no 🕘 Histórico (/historico), com o resultado pra copiar.

  tid = iniciar(tipo, titulo, fn, pagina="/roteiros-yt/abc", alvo={"resp": "campoResp"})
        fn(t) roda numa thread; t.progresso("…") atualiza o texto de andamento; o que fn devolver vira "resultado".
"""
from __future__ import annotations

import json
import os
import arquivo_seguro  # noqa: E402  (v84_99: os.replace sem WinError 5)
import re
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional

import notificacoes

PASTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "tarefas")
_TRAVA = threading.RLock()
_BOOT = uuid.uuid4().hex[:8]  # tarefas "rodando" de outra execução do site foram interrompidas
_RE_ID = re.compile(r"^[0-9a-f]{12}$")


def _caminho(tid: str) -> str:
    return os.path.join(PASTA, tid + ".json")


def _gravar(t: Dict[str, Any]) -> None:
    with _TRAVA:
        os.makedirs(PASTA, exist_ok=True)
        tmp = _caminho(t["id"]) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False)
        arquivo_seguro.trocar(tmp, _caminho(t["id"]))


def pegar(tid: str) -> Optional[Dict[str, Any]]:
    if not _RE_ID.match(str(tid or "")):
        return None
    try:
        with open(_caminho(tid), encoding="utf-8") as f:
            t = json.load(f)
    except (OSError, ValueError):
        return None
    if t.get("status") == "rodando" and t.get("boot") != _BOOT:
        t.update(status="erro", erro="O site foi fechado enquanto esta tarefa rodava — inicie de novo.", fim=t.get("fim") or time.time())
    return t


def listar(limite: int = 100, tipo: str = "", pagina: str = "") -> List[Dict[str, Any]]:
    try:
        nomes = [n for n in os.listdir(PASTA) if n.endswith(".json")]
    except OSError:
        return []
    nomes.sort(key=lambda n: os.path.getmtime(os.path.join(PASTA, n)), reverse=True)
    out = []
    for n in nomes:
        t = pegar(n[:-5])
        if not t or (tipo and t.get("tipo") != tipo) or (pagina and t.get("pagina") != pagina):
            continue
        out.append(t)
        if len(out) >= limite:
            break
    return out


class _Andamento:
    def __init__(self, t: Dict[str, Any]):
        self._t = t

    def parcial(self, dados: Any) -> None:
        """Resultado parcial (a página vai mostrando enquanto roda)."""
        self._t["parcial"] = dados
        try:
            _gravar(self._t)
        except OSError:
            pass

    def progresso(self, texto: str) -> None:
        self._t["progresso"] = str(texto or "")[:300]
        try:
            _gravar(self._t)
        except OSError:
            pass


def iniciar(tipo: str, titulo: str, fn: Callable[[_Andamento], Any], *, pagina: str = "", link: str = "",
            alvo: Optional[Dict[str, Any]] = None, avisar: bool = True, rodar_ja: bool = False) -> str:
    """Começa a tarefa numa thread e devolve o id. `pagina` = de onde veio (pra reaplicar ao voltar);
    `link` = pra onde a notificação leva (padrão: a própria página)."""
    tid = uuid.uuid4().hex[:12]
    t = {"id": tid, "tipo": str(tipo)[:40], "titulo": str(titulo or tipo)[:160], "status": "rodando", "progresso": "",
         "pagina": notificacoes.link_seguro(pagina), "link": notificacoes.link_seguro(link or pagina),
         "alvo": alvo or {}, "criado": time.time(), "fim": None, "resultado": None, "erro": None,
         "aplicada": False, "boot": _BOOT}
    _gravar(t)

    def _rodar():
        try:
            t["resultado"] = fn(_Andamento(t))
            t["status"] = "pronto"
        except Exception as exc:  # noqa: BLE001
            t["status"] = "erro"
            t["erro"] = str(exc)[:1500] or exc.__class__.__name__
            t["trace"] = traceback.format_exc()[-3000:]
        t["fim"] = time.time()
        t["progresso"] = ""
        if avisar:  # o aviso ANTES de gravar o status final: quem vê "pronto" já acha o aviso no 🔔 (v84_92)
            ok = t["status"] == "pronto"
            try:
                notificacoes.avisar(("✅ " if ok else "❌ ") + t["titulo"] + (" — pronto" if ok else " — deu erro"),
                                    "" if ok else t["erro"], t["link"] or "/historico", "ok" if ok else "erro", tipo=t["tipo"])
            except Exception:  # noqa: BLE001 — o aviso nunca impede de guardar o resultado
                pass
        try:
            _gravar(t)
        except OSError:
            pass

    if rodar_ja:
        _rodar()
    else:
        threading.Thread(target=_rodar, name="tarefa-" + tid, daemon=True).start()
    return tid


def esperar(tid: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        t = pegar(tid)
        if t and t["status"] != "rodando":
            return t
        time.sleep(0.05)
    return pegar(tid)


def marcar_aplicada(tid: str) -> bool:
    with _TRAVA:
        t = pegar(tid)
        if not t:
            return False
        t["aplicada"] = True
        _gravar(t)
        return True


def apagar(tid: str) -> bool:
    if not _RE_ID.match(str(tid or "")):
        return False
    try:
        os.remove(_caminho(tid))
        return True
    except OSError:
        return False


def publico(t: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in t.items() if k not in ("trace", "boot")}


# ------------------------------------------------------------------ rotas
def registrar(app, base_dir: str) -> None:
    from flask import abort, jsonify, request

    global PASTA  # noqa: PLW0603
    PASTA = os.environ.get("TAREFAS_PASTA") or os.path.join(base_dir, "outputs", "tarefas")

    @app.route("/tarefas")
    def tarefas_lista():
        a = request.args
        ts = listar(int(a.get("limite") or 50), tipo=a.get("tipo") or "", pagina=a.get("pagina") or "")
        if a.get("pendentes") == "1":  # o que a página ainda não aplicou (rodando, ou pronta/erro e não vista)
            ts = [t for t in ts if not t.get("aplicada")]
        return jsonify({"tarefas": [publico(t) for t in ts]})

    @app.route("/tarefas/<tid>")
    def tarefas_ver(tid: str):
        t = pegar(tid)
        if not t:
            abort(404)
        return jsonify(publico(t))

    @app.route("/tarefas/<tid>/aplicada", methods=["POST"])
    def tarefas_aplicada(tid: str):
        return jsonify({"ok": marcar_aplicada(tid)})

    @app.route("/tarefas/<tid>/apagar", methods=["POST"])
    def tarefas_apagar(tid: str):
        return jsonify({"ok": apagar(tid)})
