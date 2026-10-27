"""
flow_lote.py
============

🚀 FLOW EM MASSA — parte da aba 🎬 Google Flow (/flow#lote). Gera MUITAS imagens e vídeos de uma vez:

  • 📋 Fila: cole vários prompts (um por linha, ou separados por linha em branco). Cada linha pode começar com
    "foto:" / "imagem:" / "video:" pra escolher o tipo só daquela linha.
  • 👥 Várias contas em PARALELO (padrão 2): cada conta tem o próprio navegador (o perfil dela, já logado) e o
    próprio projeto no Flow.
  • ⏱ Cooldown ESCALONADO entre os envios (padrão 5–10 s): uma conta envia → conta um tempo sorteado entre 5 e 10 s
    → a outra envia → conta de novo… (nunca duas contas clicando em "Iniciar geração" juntas).
  • 💳 Sem crédito: a conta fica marcada (só pro tipo que acabou — vídeo ou imagem) e o pedido volta pra fila pra
    outra conta pegar.
  • 🔁 Vídeo → foto: quando TODAS as contas ficam sem crédito de VÍDEO, os vídeos que faltam viram FOTO — a IA
    reescreve o prompt (tira movimento de câmera, duração, som; escolhe o instante mais marcante da cena).
    Quem reescreve: 🤖 a IA do site (Claude, se ligada) → 🔎 IA do Google (se estiver no ar) → uma regra simples.
  • 🌐 Abrir o navegador de uma conta na mão (fazer login, ativar o premium/teste grátis, conferir os créditos…).
    Enquanto ela está aberta, o lote não usa essa conta; clique em "✔ Concluir" (ou feche a janela) pra devolver.

  • 🎞 Animar (v84_182): o editor manda pedidos de VÍDEO com uma imagem de frame de Início ("inicio_arquivo") — a
    cena de imagem vira vídeo. Esses nunca viram foto (esperam uma conta com crédito de vídeo).
  • 🧍 Personagens (v84_184): pedidos de FOTO com uma imagem de referência ("referencia_arquivo") — a ficha e a
    ⭐ mestre da personagem; o editor recorta o fundo verde no PC.

Tudo o que sai vai pra 🖼 Galeria da aba (outputs/flow_estudio/), como o ✨ Gerar.

Enquanto o lote (ou uma janela aberta na mão) está rodando, ele reserva o Google Flow (`_FLOW_LOCK`): o ✨ Gerar da
aba e a geração de imagens dos vídeos do site esperam terminar (o perfil de cada conta só pode estar aberto uma vez).

Arquivos: flow_dados/lote/fila.json, flow_dados/lote/config.json.
"""
from __future__ import annotations

import json
import os
import random
import re
import secrets
import threading
from datetime import datetime
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

import arquivo_seguro  # noqa: E402  (os.replace sem WinError 5)

PARALELO_MAX = 4
MAX_FILA = 3000
MAX_LOG = 300
ESPERA_LOCK_S = 30
CONFIG_PADRAO: Dict[str, Any] = {
    "paralelo": 2,               # quantas contas geram ao mesmo tempo
    "cooldown_min": 5.0,         # segundos entre um envio e o próximo (sorteado entre min e max)
    "cooldown_max": 10.0,
    "converter_para_foto": True,  # todas sem crédito de vídeo → os vídeos que faltam viram foto (prompt reescrito)
    "visivel": False,            # mostrar os navegadores
    "contas": [],                # quais contas usar ([] = todas, na ordem de 🔑 Contas Google)
    "tentativas": 2,             # erro comum (não é crédito/recusa): tenta de novo até N vezes
}
TIPOS = ("imagem", "video")
QUANTIDADES = ("x1", "x2", "x3", "x4")
# "Notamos uma atividade incomum. As extensões do navegador…" → problema da CONTA: troca de conta (v84_184)
RE_TROCAR_CONTA = re.compile(r"atividade incomum|unusual activity|extens[õo]es do navegador|browser extensions|"
                             r"actividad inusual|ungew[öo]hnliche aktivit", re.I)
MINUTOS_INCOMUM = 60
DESCANSO_MIN = 5            # 🩹 v84_237: conta com erros seguidos / que não abriu o projeto descansa e volta sozinha
DESCANSO_NAVEGADOR_MIN = 2  # o navegador dela não abriu (perfil preso, Chrome fechando…)
PAUSAR_NO_INCOMUM = True  # ⏸ v84_220: "atividade incomum" pausa o lote em vez de passar pra outra conta
_RE_PREFIXO = re.compile(r"^\s*(foto|imagem|image|img|photo|v[ií]deo|video)\s*[:\-–—]\s*", re.I)

INSTRUCAO_FOTO = (
    "Você recebe um comando (prompt) que foi escrito pra gerar um VÍDEO no Google Flow (Veo). As contas ficaram sem "
    "crédito de vídeo, então ele vai virar uma FOTO (imagem estática). Reescreva o comando como prompt de IMAGEM: "
    "mantenha o assunto, as pessoas/objetos, o cenário, a época, o estilo, a luz, as cores e o enquadramento; escolha o "
    "instante MAIS marcante da cena e descreva esse instante congelado; tire tudo o que é de vídeo (movimento de câmera "
    "como push-in, pan, zoom, travelling, drone; duração; cortes; transições; câmera lenta; som, música, falas). "
    "Use o MESMO idioma do comando original. Responda SÓ com o novo comando, texto puro, sem aspas e sem explicação.")

_RE_MOVIMENTO = re.compile(
    r"(?:\bslow(?:ly)?\s+)?(?:\bcinematic\s+)?(?:\bcamera\s+)?\b(?:push(?:es|ing)?[- ]in|pull(?:s|ing)?[- ](?:out|back)|"
    r"pan(?:s|ning)?(?:\s+(?:left|right|across))?|tilt(?:s|ing)?(?:\s+(?:up|down))?|zoom(?:s|ing)?(?:\s+(?:in|out))?|"
    r"dolly(?:\s+(?:in|out))?|tracking shot|travelling|drone shot|aerial shot|orbit(?:s|ing)?|time[- ]?lapse|"
    r"slow[- ]motion|fade[- ]?(?:in|out)|transition|cut to)\b(?:\s+(?:on|onto|over|of|into|toward|towards|around|through|across|to)\b)?"
    r"|\b\d+\s*(?:s|sec|secs|seconds|segundos)\b"
    r"|(?:\ba\s+)?\bc[aâ]mera\s+(?:se\s+)?(?:aproxima|afasta|gira|sobe|desce|avan[çc]a)\w*(?:\s+(?:de|do|da|sobre|em|no|na|para|pelo|pela)\b)?"
    r"|(?:\bem\s+)?\bc[aâ]mera lenta\b", re.I)


# ------------------------------------------------------------------ util
def _gf():
    from googleflow import googleflow_client as gf
    return gf


def _fd():
    from googleflow import flow_direto as fd
    return fd


def _site_cfg() -> Dict[str, Any]:
    try:
        from site_config import load_site_config
        return load_site_config()
    except Exception:  # noqa: BLE001
        return {}


def pasta() -> str:
    p = os.path.join(str(_gf().pasta_dados()), "lote")
    os.makedirs(p, exist_ok=True)
    return p


def _ler_json(nome: str, padrao: Any) -> Any:
    try:
        with open(os.path.join(pasta(), nome), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def _gravar_json(nome: str, dados: Any) -> None:
    dest = os.path.join(pasta(), nome)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=0)
    arquivo_seguro.trocar(tmp, dest)


def normalizar_config(d: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    c = dict(CONFIG_PADRAO)
    c.update({k: v for k, v in (base or {}).items() if k in CONFIG_PADRAO})
    for k, v in (d or {}).items():
        if k not in CONFIG_PADRAO:
            continue
        try:
            if k == "paralelo":
                c[k] = max(1, min(PARALELO_MAX, int(v)))
            elif k in ("cooldown_min", "cooldown_max"):
                c[k] = max(0.0, min(600.0, float(v)))
            elif k == "tentativas":
                c[k] = max(1, min(5, int(v)))
            elif k in ("converter_para_foto", "visivel"):
                c[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "sim", "yes")
            elif k == "contas":
                c[k] = [str(x) for x in (v or []) if str(x).strip()][:50]
        except (TypeError, ValueError):
            pass
    if c["cooldown_max"] < c["cooldown_min"]:
        c["cooldown_max"] = c["cooldown_min"]
    return c


def separar_prompts(texto: str, tipo_padrao: str = "imagem", por: str = "linha") -> List[Dict[str, str]]:
    """Texto colado → [{"prompt", "tipo"}]. `por`: "linha" (um por linha) ou "bloco" (separados por linha em branco).
    "foto: ..." / "video: ..." no começo escolhe o tipo daquele prompt."""
    tipo_padrao = tipo_padrao if tipo_padrao in TIPOS else "imagem"
    pedacos = re.split(r"\n\s*\n", texto or "") if por == "bloco" else (texto or "").splitlines()
    out = []
    for p in pedacos:
        p = " ".join(p.split())
        if not p:
            continue
        tipo = tipo_padrao
        m = _RE_PREFIXO.match(p)
        if m:
            tipo = "video" if m.group(1).lower().startswith("v") else "imagem"
            p = p[m.end():].strip()
        if p:
            out.append({"prompt": p[:4000], "tipo": tipo})
    return out


def prompt_foto_simples(prompt: str) -> str:
    """Sem IA: tira o que é de vídeo (movimento de câmera, duração…) e pede uma foto do instante."""
    t = _RE_MOVIMENTO.sub("", prompt or "")
    t = re.sub(r"\s*([,;])\s*(?:[,;]\s*)+", r"\1 ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" ,.;")
    pt = bool(re.search(r"[ãõçáéíóú]|\b(uma?|de|com|na|no|em)\b", prompt or "", re.I))
    if pt:
        return f"Foto: {t}. Um único instante congelado, imagem estática, nítida e detalhada.".replace("..", ".")
    return f"Still photograph: {t}. A single frozen moment, static image, sharp and detailed.".replace("..", ".")


def reescrever_para_foto(prompt: str, log: Callable[[str, str], None] = lambda m, n="info": None,
                         ia_google: bool = True) -> Dict[str, str]:
    """→ {"prompt": novo, "por": "ia_site" | "ia_google" | "regra"}"""
    # 1) 🤖 a IA do site (Claude)
    try:
        import ia_servico
        if ia_servico.ativo("flow_foto"):
            r = ia_servico.chamar("flow_foto", INSTRUCAO_FOTO, f"Comando de vídeo:\n{prompt}", max_tokens=700)
            novo = str(r or "").strip().strip('"').strip()
            if novo and novo != prompt.strip():
                return {"prompt": novo[:4000], "por": "ia_site"}
    except Exception as exc:  # noqa: BLE001
        log(f"🤖 IA do site não reescreveu ({exc}); tentando a IA do Google…", "aviso")
    # 2) 🔎 IA do Google (Modo IA), se o app dela estiver no ar
    try:
        import ia_google_rotas as IG
        if ia_google and IG.no_ar():
            r = IG.pesquisar(INSTRUCAO_FOTO.replace("Responda SÓ com o novo comando, texto puro, sem aspas e sem explicação.",
                                                    "Coloque o novo comando INTEIRO na resposta objetiva.")
                             + "\n\nComando de vídeo: " + prompt, nova_conversa=True, timeout=240)
            novo = str((r or {}).get("resposta_objetiva") or "").strip().strip('"').strip()
            if len(novo) >= 15 and novo != prompt.strip():
                return {"prompt": novo[:4000], "por": "ia_google"}
    except Exception as exc:  # noqa: BLE001
        log(f"🔎 IA do Google não reescreveu ({exc}); usando a regra simples.", "aviso")
    return {"prompt": prompt_foto_simples(prompt), "por": "regra"}


# ------------------------------------------------------------------ reserva do Flow (_FLOW_LOCK) entre lote e janelas
_RES_OP = threading.Lock()
_DONOS: set = set()


class FlowOcupado(RuntimeError):
    pass


def _reservar(dono: str, timeout: float = ESPERA_LOCK_S) -> None:
    """O lote e as janelas abertas na mão dividem UMA reserva do Flow (o resto do site espera)."""
    gf = _gf()
    with _RES_OP:
        if _DONOS:
            _DONOS.add(dono)
            return
        try:
            import flow_estudio as FE
            if FE._ESTADO.get("rodando"):
                raise FlowOcupado("A aba está gerando agora (✨ Gerar / 🧪 Testar) — espere terminar ou clique em Parar.")
            FE.fechar_navegador()  # o navegador do ✨ Gerar (se estiver aberto) fecha e libera
        except FlowOcupado:
            raise
        except Exception:  # noqa: BLE001
            pass
        if gf._FLOW_LOCK.locked():
            try:
                gf.encerrar_sessao(timeout=timeout)  # a geração do site termina o que tem na fila e fecha
            except Exception:  # noqa: BLE001
                pass
        if not gf._FLOW_LOCK.acquire(timeout=timeout):
            raise FlowOcupado("O Google Flow está ocupado (o site está gerando imagens/vídeos pra um vídeo?). "
                              "Espere terminar e tente de novo.")
        _DONOS.add(dono)


def _liberar(dono: str) -> None:
    with _RES_OP:
        if dono not in _DONOS:
            return
        _DONOS.discard(dono)
        if not _DONOS:
            try:
                _gf()._FLOW_LOCK.release()
            except RuntimeError:
                pass


def reservado() -> bool:
    return bool(_DONOS)


def _chave_ref(caminho: str) -> str:
    """A mesma imagem (mesmo conteúdo) = a mesma chave, mesmo com outro nome de arquivo."""
    import hashlib
    try:
        with open(caminho, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return os.path.abspath(caminho)


# ------------------------------------------------------------------ baixar pra galeria
def baixar_para_galeria(context, midias: List[Dict[str, str]], job: Dict[str, Any], conta: str,
                        projeto: str = "") -> List[Dict[str, Any]]:
    import flow_estudio as FE
    gf = _gf()
    salvos = []
    for m in midias:
        if str(m.get("url") or "").startswith("blob:"):
            raise RuntimeError("o Flow deu um link blob: (não dá pra baixar por fora)")
        resp = None
        for u in ([gf._url_original(m["url"]), m["url"]] if m.get("tipo") == "imagem" else [m["url"]]):
            resp = context.request.get(u)
            if resp.ok:
                break
        if resp is None or not resp.ok:
            raise RuntimeError(f"não baixou (HTTP {resp.status if resp is not None else '?'})")
        ct = resp.headers.get("content-type", "")
        ext = "mp4" if m.get("tipo") == "video" else ("jpg" if "jpeg" in ct else "webp" if "webp" in ct else "png")
        gid = time.strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
        nome = f"{gid}.{ext}"
        with open(os.path.join(FE.pasta_galeria(), nome), "wb") as f:
            f.write(resp.body())
        e = {"id": gid, "tipo": m.get("tipo") or job["tipo"], "arquivo": nome, "media_id": m.get("id") or "",
             "prompt": job.get("prompt") or "", "modelo": job.get("modelo") or "", "proporcao": job.get("proporcao") or "",
             "origem": job.get("origem") or "lote", "frames": bool(job.get("inicio_arquivo")), "referencia": bool(job.get("referencia_arquivo")), "conta": conta, "projeto": projeto,
             "criado": time.time(), "rotulo": "🚀 lote" + (" · 🔁 era vídeo" if job.get("convertido") else ""),
             "prompt_original": job.get("prompt_original") or ""}
        FE.adicionar_na_galeria(e)
        salvos.append(e)
    return salvos


# ------------------------------------------------------------------ o lote
class _Parado(Exception):
    pass


class Lote:
    def __init__(self):
        self.trava = threading.RLock()
        self.cfg = normalizar_config(_ler_json("config.json", {}))
        self.fila: List[Dict[str, Any]] = []
        salvos = _ler_json("fila.json", [])
        for j in salvos if isinstance(salvos, list) else []:
            if isinstance(j, dict) and j.get("id"):
                if j.get("estado") in ("rodando", "convertendo"):
                    j["estado"] = "pendente"
                self.fila.append(j)
        self.logs: List[Dict[str, Any]] = []
        self.rodando = False
        self.pausando = False
        self.parar_ja = False
        self.supervisor: Optional[threading.Thread] = None
        self.trabalhadores: Dict[str, threading.Thread] = {}
        self.status_conta: Dict[str, str] = {}     # conta -> o que está fazendo agora
        self.problema_conta: Dict[str, str] = {}   # conta -> "precisa de login" / erro ao abrir (pula até concluir/limpar)
        # 🩹 v84_237: até quando a conta descansa (time.time()); sem entrada = até você concluir o login. O lote ESPERA
        # uma conta que volta logo em vez de parar com pedidos na fila
        self.problema_ate: Dict[str, float] = {}
        self.esperando_volta: Optional[float] = None
        self.manuais: Dict[str, "_Manual"] = {}
        self.proximo_envio = 0.0
        self.ultimo_envio_conta: Optional[str] = None
        self.fim_msg: Optional[str] = None

    # -- log / persistência
    def log(self, msg: str, nivel: str = "info") -> None:
        with self.trava:
            self.logs.append({"t": time.time(), "msg": str(msg)[:600], "nivel": nivel})
            del self.logs[:-MAX_LOG]

    def _salvar(self) -> None:
        with self.trava:
            _gravar_json("fila.json", self.fila[-MAX_FILA:])

    def salvar_config(self, novos: Dict[str, Any]) -> Dict[str, Any]:
        with self.trava:
            self.cfg = normalizar_config(novos, self.cfg)
            _gravar_json("config.json", self.cfg)
            return dict(self.cfg)

    # -- fila
    def adicionar(self, itens: List[Dict[str, str]], modelo: str = "", proporcao: str = "16:9", quantidade: str = "x1",
                  modelo_video: str = "") -> List[Dict[str, Any]]:
        fd = _fd()
        proporcao = proporcao if proporcao in fd.PROPORCOES else "16:9"
        quantidade = quantidade if quantidade in QUANTIDADES else "x1"
        novos = []
        with self.trava:
            if len(self.fila) + len(itens) > MAX_FILA:
                raise ValueError(f"A fila tem no máximo {MAX_FILA} itens — limpe os concluídos.")
            for it in itens:
                tipo = it["tipo"] if it.get("tipo") in TIPOS else "imagem"
                j = {"id": secrets.token_hex(5), "prompt": it["prompt"], "tipo": tipo, "tipo_pedido": tipo,
                     "modelo": (modelo_video if tipo == "video" else modelo) or "", "proporcao": proporcao,
                     "quantidade": quantidade, "estado": "pendente", "conta": None, "erro": None, "tentativas": 0,
                     "convertido": False, "prompt_original": None, "reescrito_por": None, "resultados": [],
                     "criado": time.time(), "inicio": None, "fim": None}
                # 🎞 v84_182: vídeo a partir de uma imagem (frame de Início) — "Animar com Flow" do editor
                if tipo == "video" and it.get("inicio_arquivo") and os.path.isfile(str(it["inicio_arquivo"])):
                    j["inicio_arquivo"] = os.path.abspath(str(it["inicio_arquivo"]))
                    j["origem"] = str(it.get("origem") or "animar")[:40]
                    # 🎞 v84_193: frame de Fim também (a personagem animada começa e termina na mesma pose)
                    if it.get("fim_arquivo") and os.path.isfile(str(it["fim_arquivo"])):
                        j["fim_arquivo"] = os.path.abspath(str(it["fim_arquivo"]))
                # 🧍 v84_184: foto com UMA imagem de referência ("Personagens" do editor: a ficha + a mestre numa colagem)
                if tipo == "imagem" and it.get("referencia_arquivo") and os.path.isfile(str(it["referencia_arquivo"])):
                    j["referencia_arquivo"] = os.path.abspath(str(it["referencia_arquivo"]))
                    j["origem"] = str(it.get("origem") or "referencia")[:40]
                # ✏️ v84_231: editar uma imagem que já existe num projeto do Flow — a MESMA conta volta àquele projeto e usa
                # a mídia que já está lá (sem subir de novo); sem crédito/ocupada, outra conta pega e sobe o arquivo
                if it.get("conta_pref") and it.get("projeto_url"):
                    j.update(conta_pref=str(it["conta_pref"])[:80], projeto_url=str(it["projeto_url"])[:400],
                             ref_media_id=str(it.get("ref_media_id") or "")[:200])
                self.fila.append(j)
                novos.append(j)
            self._salvar()
        self.log(f"📋 {len(novos)} prompt(s) na fila.")
        return novos

    def remover(self, jid: str) -> None:
        with self.trava:
            j = self._job(jid)
            if j["estado"] in ("rodando", "convertendo"):
                raise ValueError("Esse está rodando agora — espere terminar.")
            self.fila = [x for x in self.fila if x["id"] != jid]
            self._salvar()

    def refazer(self, jid: str) -> None:
        with self.trava:
            j = self._job(jid)
            if j["estado"] in ("rodando", "convertendo", "pendente"):
                return
            j.update(estado="pendente", erro=None, tentativas=0, conta=None, inicio=None, fim=None)
            self._salvar()

    def limpar(self, quais: str = "concluidos") -> int:
        with self.trava:
            antes = len(self.fila)
            if quais == "tudo":
                self.fila = [x for x in self.fila if x["estado"] in ("rodando", "convertendo")]
            elif quais == "erros":
                self.fila = [x for x in self.fila if x["estado"] != "erro"]
            else:
                self.fila = [x for x in self.fila if x["estado"] not in ("ok", "erro")]
            self._salvar()
            return antes - len(self.fila)

    def _job(self, jid: str) -> Dict[str, Any]:
        j = next((x for x in self.fila if x["id"] == jid), None)
        if j is None:
            raise ValueError("Não achei esse item na fila.")
        return j

    # -- contas
    def contas_do_lote(self) -> List[str]:
        gf = _gf()
        if str(_site_cfg().get("flow_navegador") or "auto").lower() == "cdp":
            return [gf.CONTA_PADRAO]  # o Chrome do próprio usuário: um navegador só
        todas = gf.nomes_das_contas()
        escolhidas = [c for c in self.cfg.get("contas") or [] if c in todas]
        return escolhidas or todas

    def _paralelo(self) -> int:
        if str(_site_cfg().get("flow_navegador") or "auto").lower() == "cdp":
            return 1
        return int(self.cfg.get("paralelo") or 1)

    def _serve(self, conta: str, tipo: str) -> bool:
        try:
            return _gf().conta_serve(conta, tipo)
        except Exception:  # noqa: BLE001
            return False

    # -- controle
    def iniciar(self) -> None:
        with self.trava:
            vivo = self.supervisor is not None and self.supervisor.is_alive()
            if self.rodando and not vivo:  # 🩹 v84_237: marcado "rodando" mas o supervisor já tinha saído — começa de novo
                self.rodando, self.pausando, self.parar_ja = False, False, False
            if self.rodando and not self.pausando:
                return
            if self.rodando and self.pausando:  # estava pausando: continua
                self.pausando = False
                self.log("▶ Continuando.")
                return
            if not any(j["estado"] == "pendente" for j in self.fila):
                raise ValueError("A fila não tem nada pendente.")
        _reservar("lote")
        with self.trava:
            self.rodando, self.pausando, self.parar_ja, self.fim_msg = True, False, False, None
            self.problema_conta = {c: m for c, m in self.problema_conta.items() if c in self.manuais}
            self.problema_ate = {c: t for c, t in self.problema_ate.items() if c in self.problema_conta}
            self.esperando_volta = None
            self.supervisor = threading.Thread(target=self._supervisionar, name="flow-lote", daemon=True)
            self.supervisor.start()
        self.log(f"▶ Lote iniciado: até {self._paralelo()} conta(s) em paralelo, cooldown de "
                 f"{self.cfg['cooldown_min']:g}–{self.cfg['cooldown_max']:g} s entre os envios.", "ok")

    def pausar(self, agora: bool = False) -> None:
        with self.trava:
            if not self.rodando:
                return
            self.pausando = True
            if agora:
                self.parar_ja = True
        self.log("⏹ Parando agora (o que está gerando volta pra fila)…" if agora
                 else "⏸ Pausando: termina o que já está gerando e para.", "aviso")

    def deve_parar(self) -> bool:
        return self.parar_ja

    # -- supervisor: abre/fecha contas, converte vídeo → foto, decide quando acabou
    def _supervisionar(self) -> None:
        try:
            while True:
                with self.trava:
                    vivos = {c: t for c, t in self.trabalhadores.items() if t.is_alive()}
                    self.trabalhadores = vivos
                    pend = [j for j in self.fila if j["estado"] == "pendente"]
                    convertendo = any(j["estado"] == "convertendo" for j in self.fila)
                    pausando = self.pausando
                if pausando:
                    if not vivos:
                        self._encerrar("⏸ Lote pausado." if not self.parar_ja else "⏹ Lote parado.")
                        return
                    time.sleep(0.5)
                    continue
                contas = self.contas_do_lote()
                self._devolver_contas_descansadas()
                # 🔁 vídeo → foto: nenhuma conta (do lote) tem crédito de vídeo
                if self.cfg.get("converter_para_foto") and any(j["tipo"] == "video" and not j.get("inicio_arquivo") for j in pend) \
                        and not any(self._serve(c, "video") for c in contas):
                    self._converter_videos()
                    continue
                # abre contas (até o paralelo) que servem pra algum pendente
                for c in contas:
                    if len(vivos) >= self._paralelo():
                        break
                    if c in vivos or c in self.manuais or c in self.problema_conta:
                        continue
                    if any(self._serve(c, j["tipo"]) for j in pend):
                        t = threading.Thread(target=self._trabalhar, args=(c,), name=f"flow-lote-{c}", daemon=True)
                        with self.trava:
                            self.trabalhadores[c] = t
                            self.status_conta[c] = "abrindo o navegador…"
                        vivos[c] = t
                        t.start()
                        time.sleep(0.3)
                if not vivos and not convertendo:
                    if not pend:
                        n_ok = sum(1 for j in self.fila if j["estado"] == "ok")
                        n_err = sum(1 for j in self.fila if j["estado"] == "erro")
                        # 🩹 v84_237: só termina se continuar vazio AGORA (um pedido que chegou nesse meio-tempo — ex.: a
                        # 🎞 Animação 2D mandando mais — fazia o lote parar com coisa na fila)
                        if self._encerrar(f"✅ Lote terminou: {n_ok} ok, {n_err} com erro.", "ok", so_se_vazio=True):
                            return
                        continue
                    volta = self._proxima_volta(contas, pend)
                    if volta is not None:  # 🩹 v84_237: uma conta descansando volta logo — espera em vez de parar
                        if self.esperando_volta != volta:
                            self.esperando_volta = volta
                            self.log(f"⏳ {len(pend)} pedido(s) na fila e as contas estão descansando — volto a tentar às "
                                     f"{time.strftime('%H:%M', time.localtime(volta))} (o lote continua ligado; ⏸ Pausar pra parar).", "aviso")
                        time.sleep(2.0)
                        continue
                    falta = sorted({j["tipo"] for j in pend})
                    motivo = ("; ".join(f"“{c}”: {m}" for c, m in self.problema_conta.items()) if self.problema_conta else "")
                    self._encerrar(f"💳 Parei: {len(pend)} pendente(s) ({', '.join(falta)}) e nenhuma conta com crédito pra isso"
                                   + (f" ({motivo})" if motivo else "")
                                   + ". Adicione/libere uma conta (ou abra o navegador dela pra ativar o premium) e clique em ▶ Iniciar.",
                                   "aviso")
                    return
                time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            self.log(f"❌ O supervisor do lote parou: {exc}\n{traceback.format_exc()[-1500:]}", "erro")
            self.pausar(agora=True)
            for t in list(self.trabalhadores.values()):
                t.join(60)
            self._encerrar(f"❌ Lote parou com erro: {exc}", "erro")

    ESPERA_VOLTA_MAX = 3 * 3600  # s: espera uma conta descansando voltar até isso; mais que isso, para e avisa

    def _devolver_contas_descansadas(self) -> None:
        """A conta que descansou o tempo dela volta pro lote (o login que falhou não volta sozinho)."""
        agora = time.time()
        voltaram = []
        with self.trava:
            for c, ate in list(self.problema_ate.items()):
                if ate and ate <= agora and c not in self.manuais:
                    self.problema_ate.pop(c, None)
                    self.problema_conta.pop(c, None)
                    voltaram.append(c)
        for c in voltaram:
            try:
                _gf().despular_conta(c)
            except Exception:  # noqa: BLE001
                pass
            self.log(f"🔁 A conta “{c}” descansou — voltando a usar.", "ok")

    def _proxima_volta(self, contas: List[str], pend: List[Dict[str, Any]]) -> Optional[float]:
        """Quando (time.time()) a 1ª conta que serviria pra algum pendente volta do descanso — None = nenhuma volta sozinha
        (login, sem crédito) ou demora demais."""
        agora = time.time()
        tipos = {j["tipo"] for j in pend}
        melhor = None
        for c in contas:
            if c in self.manuais:
                continue
            ate = self.problema_ate.get(c) if c in self.problema_conta else None
            if c in self.problema_conta and not ate:
                continue  # precisa de login: só volta com ✔ Concluir
            if ate is None:
                try:
                    info = _gf().conta_pulada(c)
                    ate = datetime.fromisoformat(info["ate"]).timestamp() if info and info.get("ate") else None
                except Exception:  # noqa: BLE001
                    ate = None
            if ate is None:
                continue
            try:  # sem crédito pros tipos da fila não adianta esperar o descanso
                c_info = next((x for x in _gf().listar_contas() if x["nome"] == c), None)
                if c_info is None or c_info.get("esgotada") or all(c_info.get("esgotada_" + _gf().tipo_do_limite(t)) for t in tipos):
                    continue
            except Exception:  # noqa: BLE001
                pass
            if ate - agora <= self.ESPERA_VOLTA_MAX:
                melhor = ate if melhor is None else min(melhor, ate)
        return max(melhor, agora + 1) if melhor is not None else None

    def _encerrar(self, msg: str, nivel: str = "info", so_se_vazio: bool = False) -> bool:
        with self.trava:
            if so_se_vazio and any(j["estado"] in ("pendente", "convertendo") for j in self.fila):
                return False
            self.esperando_volta = None
            self.rodando, self.pausando, self.parar_ja = False, False, False
            self.fim_msg = msg
            for c in list(self.status_conta):
                if c not in self.manuais:
                    self.status_conta.pop(c, None)
        _liberar("lote")
        self.log(msg, nivel)
        try:
            import notificacoes
            notificacoes.avisar("🚀 Flow em massa", msg, "/flow#lote", "ok" if nivel == "ok" else "aviso" if nivel == "aviso" else
                                "erro" if nivel == "erro" else "info", tipo="flow")
        except Exception:  # noqa: BLE001
            pass
        return True

    def _converter_videos(self) -> None:
        with self.trava:
            # 🎞 animação de uma imagem não vira foto (a imagem já existe): ela espera uma conta com crédito de vídeo
            j = next((x for x in self.fila if x["estado"] == "pendente" and x["tipo"] == "video" and not x.get("inicio_arquivo")), None)
            if j is None:
                return
            j["estado"] = "convertendo"
        self.log(f"🔁 Nenhuma conta tem crédito de VÍDEO — convertendo pra FOTO: {j['prompt'][:100]}…", "aviso")
        r = reescrever_para_foto(j["prompt"], self.log)
        with self.trava:
            j.update(prompt_original=j["prompt"], prompt=r["prompt"], reescrito_por=r["por"], tipo="imagem", convertido=True,
                     modelo="", estado="pendente" if j["estado"] == "convertendo" else j["estado"])
            self._salvar()
        quem = {"ia_site": "🤖 IA do site", "ia_google": "🔎 IA do Google", "regra": "regra simples (sem IA)"}[r["por"]]
        self.log(f"🔁 Virou foto ({quem}): {r['prompt'][:160]}")

    # -- vez de enviar (cooldown escalonado entre TODAS as contas)
    def _aguardar_vez(self, conta: str) -> None:
        with self.trava:
            agora = time.monotonic()
            espera = max(0.0, self.proximo_envio - agora)
            pausa = random.uniform(float(self.cfg["cooldown_min"]), float(self.cfg["cooldown_max"]))
            self.proximo_envio = max(agora, self.proximo_envio) + pausa
        if espera > 0:
            self.status_conta[conta] = f"⏱ esperando a vez ({espera:.0f} s)"
            fim = time.monotonic() + espera
            while True:
                if self.parar_ja:
                    raise _Parado()
                resta = fim - time.monotonic()
                if resta <= 0:
                    break
                time.sleep(min(0.25, resta))
        self.ultimo_envio_conta = conta

    def _pegar(self, conta: str) -> Optional[Dict[str, Any]]:
        with self.trava:
            if self.pausando:
                return None
            for j in self.fila:
                if j["estado"] == "pendente" and self._serve(conta, j["tipo"]) and self._pode_pegar(conta, j):
                    j.update(estado="rodando", conta=conta, inicio=time.time(), erro=None)
                    self._salvar()
                    return j
        return None

    def _tem_para(self, conta: str) -> bool:
        with self.trava:
            return not self.pausando and any(j["estado"] == "pendente" and self._serve(conta, j["tipo"]) for j in self.fila)

    ESPERA_CONTA_PREF = 240  # s que um pedido de edição espera a conta dele antes de ir pra outra

    def _pode_pegar(self, conta: str, j: Dict[str, Any]) -> bool:
        """✏️ v84_231: o pedido de edição é da conta que tem o projeto — as outras só pegam se ela não puder (sem
        crédito, fora do lote) ou depois de um tempo esperando."""
        pref = j.get("conta_pref")
        if not pref or pref == conta:
            return True
        try:
            fora = pref not in self.contas_do_lote()
        except Exception:  # noqa: BLE001
            fora = True
        return fora or not self._serve(pref, j["tipo"]) or time.time() - float(j.get("criado") or 0) > self.ESPERA_CONTA_PREF

    def _devolver(self, j: Dict[str, Any], erro: Optional[str] = None) -> None:
        with self.trava:
            j.update(estado="pendente", conta=None, erro=erro)
            self._salvar()

    # -- uma conta: abre o navegador dela e vai pegando pedidos da fila
    def _trabalhar(self, conta: str) -> None:
        gf, fd = _gf(), _fd()
        cfg = _site_cfg()
        visivel = bool(self.cfg.get("visivel"))
        timeout = int(cfg.get("flow_timeout_seconds") or 300)
        p = ctx = page = None
        fechar_ctx = False
        st = self.status_conta

        def on_passo(nome: str, estado: str, detalhe: str) -> None:
            if self.parar_ja:
                raise _Parado()
            st[conta] = f"{nome}: {estado}" + (f" — {detalhe[:120]}" if detalhe else "")

        job = None
        refs_proj: Dict[str, str] = {}  # 🧍 v84_189: imagem de referência → a mídia dela no projeto aberto (sobe UMA vez, depois reusa)
        falhas_seguidas = 0  # ⏭ v84_110: a conta que falha seguido (ou pede login) é pulada — o pedido vai pra outra

        def _pular(motivo: str, minutos: Optional[float] = None) -> None:
            """minutos: a conta descansa e volta sozinha (o lote espera); None = só volta com o login (✔ Concluir)."""
            self.problema_conta[conta] = motivo + (f" (volta em {minutos:g} min)" if minutos else "")
            if minutos:
                self.problema_ate[conta] = time.time() + minutos * 60
            else:
                self.problema_ate.pop(conta, None)
            try:
                gf.pular_conta(conta, motivo, minutos=minutos) if minutos else gf.pular_conta(conta, motivo)
            except Exception:  # noqa: BLE001
                pass
            # 🩹 v84_236: "[passo] não achei…" em TODAS as contas costuma ser o Flow que mudou a tela, não o login
            tela = bool(re.search(r"\[\w+\]\s*(não achei|o painel|o pop-up|cliquei)", motivo))
            self.log(f"⏭ Pulando a conta “{conta}”: {motivo}. Os pedidos dela vão pra outra conta. "
                     + ("(Se isso acontece em todas as contas, o Flow mudou a tela: 🩹 Corrigir, aqui na aba Flow.)" if tela
                        else "(🌐 Abrir navegador → faça o login → ✔ Concluir pra ela voltar.)"), "erro")

        try:
            from playwright.sync_api import sync_playwright
            p = sync_playwright().start()
            ctx, fechar_ctx = gf._abrir(p, cfg, headless=not visivel, conta=conta)
            if fechar_ctx:
                gf.restaurar_sessao(ctx, conta)
            self.log(f"🌐 Conta “{conta}”: navegador aberto ({'visível' if visivel else 'oculto'}).")
            while not self.parar_ja:
                job = self._pegar(conta)
                if job is None:
                    # 🩹 v84_237: ainda tem pedido que essa conta pode fazer (ex.: esperando a conta do projeto dele) —
                    # espera aqui com o navegador aberto em vez de fechar e o lote achar que acabou
                    if self._tem_para(conta):
                        st[conta] = "⏳ esperando um pedido liberar…"
                        time.sleep(2.0)
                        continue
                    break
                try:
                    if page is None or page.is_closed():
                        st[conta] = "abrindo um projeto no Flow…"
                        refs_proj.clear()  # projeto novo: as mídias do outro não existem aqui
                        try:
                            page = fd.preparar_projeto(ctx, gf.FLOW_URL, headless=not visivel, agente=gf.agente_da_cfg(cfg),
                                                       on_passo=on_passo)
                        except (fd.FlowLogin, fd.FlowLimite, _Parado):
                            raise
                        except Exception as exc_proj:  # noqa: BLE001 — a CONTA não abriu o projeto: não é culpa do pedido
                            falhas_seguidas += 1
                            try:  # 🩺 a foto e o HTML da tela vão pros erros recentes (e pro 🩹 Corrigir)
                                pg_erro = getattr(exc_proj, "page", None) or next((x for x in reversed(ctx.pages) if not x.is_closed()), None)
                                if pg_erro is not None:
                                    gf.salvar_diagnostico(pg_erro, f"{str(exc_proj).splitlines()[0][:300] if str(exc_proj) else type(exc_proj).__name__} (conta “{conta}”)")
                            except Exception:  # noqa: BLE001
                                pass
                            self._devolver(job, f"a conta “{conta}” não abriu o projeto: {str(exc_proj)[:200]}")
                            job = None
                            if falhas_seguidas >= 2 or gf.RE_PROBLEMA_DE_LOGIN.search(str(exc_proj)):
                                _pular(f"não abriu o projeto no Flow ({str(exc_proj).splitlines()[0][:140] if str(exc_proj) else type(exc_proj).__name__})",
                                       None if gf.RE_PROBLEMA_DE_LOGIN.search(str(exc_proj)) else DESCANSO_MIN)
                                break
                            self.log(f"⚠ “{conta}” não abriu o projeto ({str(exc_proj)[:160]}) — tentando de novo.", "aviso")
                            page = None
                            continue
                        gf.salvar_sessao(ctx, conta)
                    if job.get("projeto_url") and job.get("conta_pref") == conta and page is not None \
                            and str(getattr(page, "url", "")).split("?")[0] != job["projeto_url"].split("?")[0]:
                        try:  # ✏️ volta ao projeto onde a imagem foi gerada (a mídia dela já está lá)
                            st[conta] = "abrindo o projeto da imagem a editar…"
                            page.goto(job["projeto_url"], wait_until="domcontentloaded", timeout=60_000)
                            refs_proj.clear()
                            if job.get("referencia_arquivo") and job.get("ref_media_id"):
                                refs_proj[_chave_ref(job["referencia_arquivo"])] = job["ref_media_id"]
                        except Exception as exc_ir:  # noqa: BLE001 — não abriu: segue no projeto atual subindo o arquivo
                            self.log(f"⚠ “{conta}” não voltou ao projeto da imagem ({str(exc_ir)[:120]}) — vai com o arquivo.", "aviso")
                    self._aguardar_vez(conta)
                    trab = {"tipo": job["tipo"], "prompt": job["prompt"], "proporcao": job["proporcao"],
                            "modelo": job["modelo"] or str(cfg.get("flow_modelo_" + job["tipo"]) or ""),
                            "quantidade": job["quantidade"]}
                    if job["tipo"] == "video":
                        trab["tipo_video"] = "Elementos"
                        if job.get("inicio_arquivo") and os.path.isfile(job["inicio_arquivo"]):  # 🎞 animar uma imagem
                            trab["inicio"] = {"arquivo": job["inicio_arquivo"]}
                            trab["tipo_video"] = "Frames"
                            # (v84_203: o frame de Fim travava o Flow — os pedidos antigos com fim_arquivo vão só com o Início)
                    elif job.get("referencia_arquivo") and os.path.isfile(job["referencia_arquivo"]):  # 🧍 foto com referência
                        trab["referencia"] = {"arquivo": job["referencia_arquivo"],
                                              "media_id": refs_proj.get(_chave_ref(job["referencia_arquivo"]), "")}
                    self.log(f"✨ “{conta}” enviou {'🎬 vídeo' if job['tipo'] == 'video' else '🖼 foto'}: {job['prompt'][:90]}")
                    midias = fd.gerar_um(page, trab, on_passo, max(timeout, 600) if job["tipo"] == "video" else timeout)
                    if (trab.get("_ref_midia") or {}).get("media_id") and job.get("referencia_arquivo"):
                        refs_proj[_chave_ref(job["referencia_arquivo"])] = trab["_ref_midia"]["media_id"]
                    st[conta] = "baixando…"
                    salvos = baixar_para_galeria(ctx, midias, job, conta, getattr(page, "url", ""))
                    with self.trava:
                        job.update(estado="ok", fim=time.time(), resultados=[{"id": e["id"], "arquivo": e["arquivo"],
                                                                              "tipo": e["tipo"], "media_id": e.get("media_id") or "",
                                                                              "projeto": e.get("projeto") or "", "conta": conta}
                                                                             for e in salvos])
                        if not salvos:
                            job.update(estado="erro", erro="o Flow terminou mas não veio nenhuma mídia")
                        self._salvar()
                    self.log(f"✅ “{conta}”: {len(salvos)} arquivo(s) na galeria — {job['prompt'][:70]}", "ok")
                    job = None
                    falhas_seguidas = 0
                except fd.FlowLimite as exc:
                    tipo_lim = gf.tipo_do_limite(job["tipo"])
                    try:
                        gf.marcar_esgotada(conta, gf._horas_para_liberar(cfg), tipo=tipo_lim)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        gf.salvar_diagnostico(getattr(exc, "page", None) or page, str(exc))
                    except Exception:  # noqa: BLE001
                        pass
                    self.log(f"💳 “{conta}” ficou SEM CRÉDITO de {'vídeo' if tipo_lim == 'video' else 'imagem'} "
                             f"({exc.mensagem[:140]}) — o pedido volta pra fila.", "aviso")
                    self._devolver(job)
                    job = None
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass
                    page = None
                except fd.FlowLogin as exc:
                    _pular(f"precisa de login ({exc.mensagem[:120]})")
                    self._devolver(job)
                    job = None
                    break
                except fd.FlowRecusou as exc:
                    if RE_TROCAR_CONTA.search(exc.mensagem or "") and PAUSAR_NO_INCOMUM:
                        # ⏸ v84_220: o Google desconfiou da automação. Pular pra outra conta só espalha a desconfiança —
                        # o pedido volta pra fila e o LOTE PAUSA; você retoma quando quiser (de preferência mais tarde).
                        with self.trava:
                            job.update(estado="pendente", conta=None,
                                       erro="o Flow acusou “atividade incomum” — lote pausado (o pedido volta pra fila)")
                            self._salvar()
                        try:
                            gf.pular_conta(conta, f"o Flow acusou atividade incomum: {exc.mensagem[:120]}", minutos=MINUTOS_INCOMUM)
                        except Exception:  # noqa: BLE001
                            pass
                        self.problema_conta[conta] = "atividade incomum no Flow (descansando)"
                        self.log(f"⏸ “{conta}”: o Flow acusou “atividade incomum” (o Google desconfiou da automação; nada foi "
                                 f"cobrado). Pausei o lote — o pedido voltou pra fila. Espere um tempo antes de retomar e "
                                 f"mande lotes menores.", "aviso")
                        self.pausar(agora=True)
                        job = None
                        break
                    if RE_TROCAR_CONTA.search(exc.mensagem or ""):
                        # 🔁 v84_184: "Notamos uma atividade incomum / extensões do navegador" é coisa da CONTA (o Google
                        # desconfiou dela), não do prompt: a conta descansa e o pedido vai pra outra conta
                        with self.trava:
                            ja = list(job.get("contas_incomum") or [])
                            if conta not in ja:
                                ja.append(conta)
                            todas = self.contas_do_lote()
                            esgotou = all(c in ja for c in todas)
                            job["contas_incomum"] = ja
                            if esgotou:
                                job.update(estado="erro", fim=time.time(),
                                           erro=f"todas as contas deram “atividade incomum” no Flow: {exc.mensagem[:200]}")
                            else:
                                job.update(estado="pendente", conta=None,
                                           erro=f"a conta “{conta}” deu “atividade incomum” — indo pra outra conta")
                            self._salvar()
                        try:
                            gf.pular_conta(conta, f"o Flow acusou atividade incomum: {exc.mensagem[:120]}", minutos=MINUTOS_INCOMUM)
                        except Exception:  # noqa: BLE001
                            pass
                        self.problema_conta[conta] = "atividade incomum no Flow (descansando)"
                        self.problema_ate[conta] = time.time() + MINUTOS_INCOMUM * 60
                        self.log(f"🔁 “{conta}”: o Flow acusou atividade incomum — a conta descansa {MINUTOS_INCOMUM} min e o "
                                 f"pedido vai pra outra conta" + (" (mas todas já deram isso: erro)" if esgotou else "") + ".", "aviso")
                        job = None
                        break
                    with self.trava:
                        job.update(estado="erro", erro=f"o Flow recusou: {exc.mensagem[:300]}", fim=time.time())
                        self._salvar()
                    self.log(f"🚫 “{conta}”: o Flow recusou — {exc.mensagem[:160]}", "erro")
                    job = None
                except _Parado:
                    raise
                except Exception as exc:  # noqa: BLE001 — passo falhou, rede, download…
                    if gf.RE_PROBLEMA_DE_LOGIN.search(str(exc)):  # "faça login", sessão caiu, verificação da conta…
                        _pular(f"problema de login ({str(exc).splitlines()[0][:120]})")
                        self._devolver(job)
                        job = None
                        break
                    falhas_seguidas += 1
                    diag = None
                    try:
                        diag = gf.salvar_diagnostico(getattr(exc, "page", None) or page, str(exc)) if page is not None else None
                    except Exception:  # noqa: BLE001
                        pass
                    with self.trava:
                        job["tentativas"] = int(job.get("tentativas") or 0) + 1
                        definitivo = job["tentativas"] >= int(self.cfg.get("tentativas") or 2)
                        job.update(estado="erro" if definitivo else "pendente", conta=None if not definitivo else conta,
                                   erro=f"{type(exc).__name__}: {str(exc)[:300]}" + (f" (diagnóstico {os.path.basename(diag)})" if diag else ""),
                                   fim=time.time() if definitivo else None)
                        self._salvar()
                    self.log(f"❌ “{conta}”: {str(exc)[:200]}" + ("" if definitivo else " — vou tentar de novo."), "erro")
                    job = None
                    try:
                        page.close()
                    except Exception:  # noqa: BLE001
                        pass
                    page = None
                    if falhas_seguidas >= 3:  # 3 erros seguidos na mesma conta: o problema é ela
                        _pular(f"{falhas_seguidas} erros seguidos (o último: {str(exc).splitlines()[0][:120] if str(exc) else type(exc).__name__})",
                               DESCANSO_MIN)
                        break
        except _Parado:
            if job is not None:
                self._devolver(job)
        except Exception as exc:  # noqa: BLE001 — não abriu o navegador
            msg = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
            _pular(f"não abriu o navegador: {msg}", DESCANSO_NAVEGADOR_MIN)
            if job is not None:
                self._devolver(job)
        finally:
            for fechar in (lambda: page.close() if page is not None else None,
                           lambda: gf.salvar_sessao(ctx, conta) if ctx is not None else None,
                           lambda: ctx.close() if ctx is not None and fechar_ctx else None,
                           lambda: p.stop() if p is not None else None):
                try:
                    fechar()
                except Exception:  # noqa: BLE001
                    pass
            st.pop(conta, None)

    # -- 🌐 abrir o navegador de uma conta na mão
    def abrir_manual(self, conta: str, url: str = "") -> None:
        gf = _gf()
        if conta not in gf.nomes_das_contas():
            raise ValueError(f"Conta '{conta}' não encontrada.")
        if str(_site_cfg().get("flow_navegador") or "auto").lower() == "cdp":
            raise ValueError("No modo CDP o Flow usa o SEU Chrome — é só usar a janela dele.")
        with self.trava:
            if conta in self.manuais and self.manuais[conta].is_alive():
                raise ValueError("A janela dessa conta já está aberta.")
            t = self.trabalhadores.get(conta)
            if t is not None and t.is_alive():
                raise ValueError("Essa conta está gerando no lote agora — pause o lote (ou espere) e abra de novo.")
        _reservar("manual:" + conta)
        m = _Manual(self, conta, url if str(url or "").startswith("https://") else gf.FLOW_URL)
        with self.trava:
            self.manuais[conta] = m
            self.status_conta[conta] = "🌐 aberta na mão"
        m.start()
        self.log(f"🌐 Abrindo o navegador da conta “{conta}” pra você usar (login, premium, créditos…). "
                 f"Clique em ✔ Concluir (ou feche a janela) quando terminar.")

    def concluir_manual(self, conta: str) -> None:
        m = self.manuais.get(conta)
        if m is not None:
            m.concluir.set()

    def _fim_manual(self, conta: str, erro: Optional[str] = None) -> None:
        with self.trava:
            self.manuais.pop(conta, None)
            self.status_conta.pop(conta, None)
            self.problema_conta.pop(conta, None)  # logou/ativou: o lote volta a tentar essa conta
        try:
            _gf().despular_conta(conta)
        except Exception:  # noqa: BLE001
            pass
        _liberar("manual:" + conta)
        self.log(f"🌐 Conta “{conta}”: " + (f"a janela fechou com erro ({erro})." if erro else "janela fechada, sessão salva."),
                 "erro" if erro else "ok")

    # -- o que a tela mostra
    def estado(self) -> Dict[str, Any]:
        gf = _gf()
        with self.trava:
            fila = [dict(j) for j in self.fila]
            cont = {e: sum(1 for j in fila if j["estado"] == e) for e in ("pendente", "rodando", "convertendo", "ok", "erro")}
            contas = []
            try:
                lista = gf.listar_contas()
            except Exception:  # noqa: BLE001
                lista = []
            usar = set(self.contas_do_lote())
            for c in lista:
                n = c["nome"]
                contas.append({**{k: c.get(k) for k in ("nome", "esgotada", "esgotada_ate", "esgotada_video", "video_ate",
                                                         "esgotada_imagem", "imagem_ate", "logada", "email", "pulada")},
                               "no_lote": n in usar, "gerando": n in self.trabalhadores and self.trabalhadores[n].is_alive(),
                               "manual": n in self.manuais, "agora": self.status_conta.get(n) or "",
                               "problema": self.problema_conta.get(n) or (f"⏭ pulada: {c['pulada']}" if c.get("pulada") else "")})
            espera = max(0.0, self.proximo_envio - time.monotonic())
            return {"rodando": self.rodando, "pausando": self.pausando, "config": dict(self.cfg), "contagem": cont,
                    "fila": fila[-400:], "total": len(fila), "contas": contas, "log": self.logs[-120:],
                    "proximo_envio_s": round(espera, 1), "fim_msg": self.fim_msg, "esperando_volta": self.esperando_volta, "reservado": reservado(),
                    "cdp": str(_site_cfg().get("flow_navegador") or "auto").lower() == "cdp", "paralelo_max": PARALELO_MAX}


class _Manual(threading.Thread):
    def __init__(self, lote: Lote, conta: str, url: str):
        super().__init__(name=f"flow-manual-{conta}", daemon=True)
        self.lote, self.conta, self.url = lote, conta, url
        self.concluir = threading.Event()

    def run(self) -> None:
        gf = _gf()
        p = ctx = None
        fechar_ctx = False
        erro = None
        try:
            from playwright.sync_api import sync_playwright
            p = sync_playwright().start()
            ctx, fechar_ctx = gf._abrir(p, _site_cfg(), headless=False, conta=self.conta)
            if fechar_ctx:
                gf.restaurar_sessao(ctx, self.conta)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            ultimo_backup = time.monotonic()
            while not self.concluir.is_set():
                abertas = [x for x in ctx.pages if not x.is_closed()]
                if not abertas:
                    break  # você fechou a janela
                try:
                    abertas[0].wait_for_timeout(800)  # deixa o navegador processar os eventos
                except Exception:  # noqa: BLE001
                    break
                if time.monotonic() - ultimo_backup > 30:
                    gf.salvar_sessao(ctx, self.conta)
                    ultimo_backup = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            erro = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        finally:
            for fechar in (lambda: gf.salvar_sessao(ctx, self.conta) if ctx is not None else None,
                           lambda: ctx.close() if ctx is not None and fechar_ctx else None,
                           lambda: p.stop() if p is not None else None):
                try:
                    fechar()
                except Exception:  # noqa: BLE001
                    pass
            self.lote._fim_manual(self.conta, erro)


_LOTE: Optional[Lote] = None
_LOTE_TRAVA = threading.Lock()


def lote() -> Lote:
    global _LOTE
    with _LOTE_TRAVA:
        if _LOTE is None:
            _LOTE = Lote()
        return _LOTE


def ocupado() -> Optional[str]:
    """Por que o ✨ Gerar da aba não pode abrir o Flow agora (ou None)."""
    if _LOTE is not None and _LOTE.rodando:
        return "O 🚀 Em massa está gerando no Flow agora — pause o lote (ou espere terminar)."
    if _LOTE is not None and _LOTE.manuais:
        return "Tem uma janela de conta aberta na mão (🚀 Em massa → contas) — clique em ✔ Concluir antes."
    return None


# ------------------------------------------------------------------ rotas
def registrar(app) -> None:
    from flask import jsonify, request

    def _resp(fn):
        try:
            r = fn()
            return jsonify(r if r is not None else {"ok": True})
        except (ValueError, FlowOcupado) as exc:
            return jsonify({"erro": str(exc)}), 400 if isinstance(exc, ValueError) else 409

    @app.route("/flow/lote/estado")
    def flow_lote_estado():
        return jsonify(lote().estado())

    @app.route("/flow/lote/fila", methods=["POST"])
    def flow_lote_fila():
        d = request.get_json(silent=True) or {}

        def _add():
            itens = separar_prompts(str(d.get("texto") or ""), str(d.get("tipo") or "imagem"),
                                    "bloco" if d.get("separar") == "bloco" else "linha")
            try:
                repetir = max(1, min(20, int(d.get("repetir") or 1)))
            except (TypeError, ValueError):
                repetir = 1
            itens = [dict(it) for it in itens for _ in range(repetir)]  # 🔁 cada prompt N vezes (variações)
            if not itens:
                raise ValueError("Cole pelo menos um prompt.")
            novos = lote().adicionar(itens, str(d.get("modelo") or "")[:60], str(d.get("proporcao") or "16:9"),
                                     str(d.get("quantidade") or "x1"), str(d.get("modelo_video") or "")[:60])
            if d.get("iniciar"):
                lote().iniciar()
            return {"ok": True, "adicionados": len(novos)}
        return _resp(_add)

    @app.route("/flow/lote/fila/<jid>/<acao>", methods=["POST"])
    def flow_lote_item(jid: str, acao: str):
        if acao == "remover":
            return _resp(lambda: lote().remover(jid))
        if acao == "refazer":
            return _resp(lambda: lote().refazer(jid))
        return jsonify({"erro": "ação inválida"}), 400

    @app.route("/flow/lote/limpar", methods=["POST"])
    def flow_lote_limpar():
        quais = str((request.get_json(silent=True) or {}).get("quais") or "concluidos")
        return _resp(lambda: {"ok": True, "removidos": lote().limpar(quais)})

    @app.route("/flow/lote/iniciar", methods=["POST"])
    def flow_lote_iniciar():
        return _resp(lambda: lote().iniciar())

    @app.route("/flow/lote/pausar", methods=["POST"])
    def flow_lote_pausar():
        agora = bool((request.get_json(silent=True) or {}).get("agora"))
        return _resp(lambda: lote().pausar(agora))

    @app.route("/flow/lote/config", methods=["POST"])
    def flow_lote_config():
        return _resp(lambda: {"ok": True, "config": lote().salvar_config(request.get_json(silent=True) or {})})

    @app.route("/flow/lote/liberar-todas", methods=["POST"])
    def flow_lote_liberar_todas():
        """↺ Recarregou os créditos / ativou o premium: todas as contas voltam a valer pra vídeo e imagem."""
        def _lib():
            gf = _gf()
            for n in gf.nomes_das_contas():
                gf.liberar_conta(n)
            lote().problema_conta.clear()
            gf.despular_conta(None)
            lote().log("↺ Créditos liberados em todas as contas.", "ok")
            return {"ok": True}
        return _resp(_lib)

    @app.route("/flow/lote/contas/<conta>/abrir", methods=["POST"])
    def flow_lote_abrir(conta: str):
        url = str((request.get_json(silent=True) or {}).get("url") or "")
        return _resp(lambda: lote().abrir_manual(conta, url))

    @app.route("/flow/lote/contas/<conta>/concluir", methods=["POST"])
    def flow_lote_concluir(conta: str):
        return _resp(lambda: lote().concluir_manual(conta))
