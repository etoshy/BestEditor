"""
producao_pod.py — 🏭 Produção no pod: vários roteiros → narração + cenas + imagens → projetos prontos (v84_122)
================================================================================================================

Aba /producao-pod. Você escolhe vários roteiros (📜 Roteiro do YouTube, 🕵️ Modelos de vídeo ou texto colado), cada um
com idioma, voz (perfil), intensidade emocional e aderência à referência — ou "aplicar a todos" — e o endereço do seu
pod (servidor studio-ia). O site faz sozinho, roteiro por roteiro:

  1. 🗣️ manda TODAS as narrações pro pod de uma vez (ele narra em fila e transcreve com o Whisper na GPU);
  2. 🎬 quando uma narração volta: corta em cenas de ~5 s, a 🤖 IA descreve cada uma e escolhe as ~30% mais
     DIFÍCEIS de achar em banco, bem espaçadas (cenas_lote.py);
  3. 🖼 manda as imagens dessas cenas pro pod num lote só (Z-Image Turbo);
  4. 📂 cria o projeto do editor: as cenas do pod já com imagem, as outras ⏳ PENDENTES. No editor, "Completar cenas
     pendentes" escolhe as fontes (Pexels, YouTube, buscadores…) e a IA escreve as buscas de cada uma.

O pod trabalha sem parar: enquanto narra o roteiro 3, já gera as imagens do 1 e do 2.

Tudo fica em producao_pod/: <lote>.json (estado) e arquivos/<lote>/<item>/ (áudio, transcrição, imagens).
Se o site fechar no meio, ao abrir a aba o lote continua de onde parou (os pedidos ficam guardados no pod).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Optional

import arquivo_seguro

_BASE = os.path.dirname(os.path.abspath(__file__))
if os.path.join(_BASE, "toolkit") not in __import__("sys").path:  # tts.voice_generator (perfis, tags do Turbo)
    __import__("sys").path.insert(0, os.path.join(_BASE, "toolkit"))
PASTA = os.environ.get("PRODUCAO_POD_DIR") or os.path.join(_BASE, "producao_pod")

ESTADOS_FINAIS = ("pronto", "erro", "cancelado")
ROTULOS = {
    "aguardando": "⏳ aguardando", "narrando": "🗣️ narrando no pod", "cenas": "🎬 planejando as cenas",
    "imagens": "🖼 gerando imagens no pod", "montando": "📂 criando o projeto", "pronto": "✅ pronto",
    "erro": "❌ erro", "cancelado": "⏹ cancelado",
}
PADRAO_ITEM = {"idioma": "pt", "motor": "chatterbox", "perfil": "", "exaggeration": 0.5, "cfg_weight": 0.5}
PADRAO_LOTE = {"intervalo": 5.0, "pct": 30, "orientacao": "16:9", "estilo_extra": "", "transcrever": True, "rostos": True, "epoca": True,
               "legenda": {"modo": "legenda", "max_palavras": 5}}

_TRAVA = threading.RLock()
_RUNNER: Dict[str, Any] = {"thread": None}
_CRIAR_PROJETO: Dict[str, Callable] = {}
INTERVALO_TICK = 4.0


class ProducaoErro(Exception):
    pass


# ------------------------------------------------------------------ guardar
def _arq(lid: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{6,32}", lid or ""):
        raise ProducaoErro("lote inválido")
    return os.path.join(PASTA, f"{lid}.json")


def pasta_item(lid: str, iid: str) -> str:
    p = os.path.join(PASTA, "arquivos", lid, iid)
    os.makedirs(p, exist_ok=True)
    return p


def carregar(lid: str) -> Dict[str, Any]:
    try:
        with open(_arq(lid), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ProducaoErro("Lote não encontrado.")


def salvar(lote: Dict[str, Any]) -> None:
    os.makedirs(PASTA, exist_ok=True)
    lote["atualizado"] = time.time()
    tmp = _arq(lote["id"]) + f".{uuid.uuid4().hex[:6]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lote, f, ensure_ascii=False, indent=1)
    arquivo_seguro.trocar(tmp, _arq(lote["id"]))


def listar() -> List[Dict[str, Any]]:
    if not os.path.isdir(PASTA):
        return []
    out = []
    for n in os.listdir(PASTA):
        if n.endswith(".json"):
            try:
                out.append(carregar(n[:-5]))
            except Exception:  # noqa: BLE001
                continue
    return sorted(out, key=lambda l: -l.get("criado", 0))


def excluir(lid: str) -> None:
    lote = carregar(lid)
    if lote.get("status") == "rodando":
        raise ProducaoErro("O lote está rodando — cancele antes.")
    os.remove(_arq(lid))
    shutil.rmtree(os.path.join(PASTA, "arquivos", lid), ignore_errors=True)


# ------------------------------------------------------------------ roteiros disponíveis
def roteiros_disponiveis(base: str = _BASE) -> List[Dict[str, Any]]:
    """Os roteiros prontos do site: 📜 Roteiro do YouTube e 🕵️ Modelos de vídeo (só os que têm roteiro)."""
    out = []
    try:
        import roteiros_yt
        for p in roteiros_yt.listar_projetos(base):
            try:
                texto = roteiros_yt.roteiro_para_voz(roteiros_yt.carregar_projeto(base, p["id"]))
            except Exception:  # noqa: BLE001
                continue
            if texto.strip():
                out.append({"origem": "roteiro", "id": p["id"], "titulo": p["titulo"], "palavras": len(texto.split()),
                            "idioma": "", "atualizado": p.get("atualizado", 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        import dossies
        for p in dossies.listar(base):
            if not p.get("tem_roteiro"):
                continue
            try:
                d = dossies.carregar(base, p["id"])
                texto = dossies.roteiro_para_voz(d)
            except Exception:  # noqa: BLE001
                continue
            if texto.strip():
                out.append({"origem": "dossie", "id": p["id"], "titulo": p["nome"], "palavras": len(texto.split()),
                            "idioma": d["config"].get("idioma") or "", "atualizado": p.get("atualizado", 0)})
    except Exception:  # noqa: BLE001
        pass
    return sorted(out, key=lambda x: -x["atualizado"])


def texto_do_roteiro(origem: str, pid: str, base: str = _BASE) -> str:
    if origem == "roteiro":
        import roteiros_yt
        return roteiros_yt.roteiro_para_voz(roteiros_yt.carregar_projeto(base, pid))
    if origem == "dossie":
        import dossies
        return dossies.roteiro_para_voz(dossies.carregar(base, pid))
    raise ProducaoErro(f"origem desconhecida: {origem}")


def texto_para_tts(texto: str, idioma: str, motor: str) -> str:
    """Mesma limpeza do Gerador de voz: emojis/símbolos (roteiros_yt) e pontuação/marcadores (narracoes)."""
    try:
        import roteiros_yt
        texto = roteiros_yt.limpar_para_tts(texto, idioma)["texto"]
    except Exception:  # noqa: BLE001
        pass
    import narracoes
    return narracoes.limpar_texto_para_tts(texto, motor=motor).strip()


# ------------------------------------------------------------------ criar
def _num(v: Any, padrao: float, a: float, b: float) -> float:
    try:
        return max(a, min(b, float(v)))
    except (TypeError, ValueError):
        return padrao


def criar(itens: List[Dict[str, Any]], config: Dict[str, Any], pod_url: str = "", nome: str = "") -> Dict[str, Any]:
    """itens: [{origem: "roteiro"|"dossie"|"texto", id?, titulo?, texto?, idioma, motor, perfil, exaggeration, cfg_weight}]."""
    import idiomas
    if not itens:
        raise ProducaoErro("Escolha pelo menos um roteiro.")
    cfg = dict(PADRAO_LOTE)
    cfg["intervalo"] = _num(config.get("intervalo"), 5.0, 2.0, 30.0)
    cfg["pct"] = int(_num(config.get("pct"), 30, 0, 50))
    cfg["orientacao"] = config.get("orientacao") if config.get("orientacao") in ("16:9", "9:16", "1:1") else "16:9"
    cfg["estilo_extra"] = " ".join(str(config.get("estilo_extra") or "").split())[:300]
    cfg["rostos"] = config.get("rostos", True) is not False  # 🎭 rosto das pessoas do elenco (FLUX.2 klein no pod)
    cfg["epoca"] = config.get("epoca", True) is not False  # 🎞 visual de foto do ano de cada cena
    leg = config.get("legenda") if isinstance(config.get("legenda"), dict) else {}
    cfg["legenda"] = {"modo": leg.get("modo") if leg.get("modo") in ("legenda", "tempo", "palavra") else "legenda",
                      "max_palavras": int(_num(leg.get("max_palavras"), 5, 1, 15))}
    prontos = []
    for k, it in enumerate(itens):
        origem = it.get("origem") or "texto"
        texto = str(it.get("texto") or "").strip()
        if origem in ("roteiro", "dossie") and not texto:
            texto = texto_do_roteiro(origem, str(it.get("id") or ""))
        if len(texto.split()) < 5:
            raise ProducaoErro(f"O roteiro {k + 1} ({it.get('titulo') or origem}) está vazio ou curto demais.")
        motor = it.get("motor") if it.get("motor") in ("chatterbox", "chatterbox_turbo") else "chatterbox"
        idioma = "en" if motor == "chatterbox_turbo" else (idiomas.normalizar(it.get("idioma")) or "pt")
        prontos.append({
            "id": uuid.uuid4().hex[:8], "titulo": str(it.get("titulo") or f"Roteiro {k + 1}")[:120],
            "origem": origem, "origem_id": str(it.get("id") or ""), "texto": texto,
            "idioma": idioma, "motor": motor, "perfil": str(it.get("perfil") or "").strip(),
            "exaggeration": _num(it.get("exaggeration"), 0.5, 0.25, 2.0),
            "cfg_weight": _num(it.get("cfg_weight"), 0.5, 0.0, 1.0),
            "estado": "aguardando", "mensagem": "", "log": [], "pod_voz": None, "pod_img": None,
            "job_id": None, "erro": None, "inicio": None, "fim": None, "cenas": None,
        })
    lote = {"id": uuid.uuid4().hex[:10], "nome": (nome or time.strftime("Lote %d/%m %H:%M")).strip()[:80],
            "criado": time.time(), "status": "rodando", "pod_url": (pod_url or "").strip().rstrip("/"),
            "config": cfg, "itens": prontos}
    with _TRAVA:
        salvar(lote)
    garantir_runner()
    return lote


def cancelar(lid: str) -> Dict[str, Any]:
    with _TRAVA:
        lote = carregar(lid)
        for it in lote["itens"]:
            if it["estado"] not in ESTADOS_FINAIS:
                it["estado"], it["mensagem"] = "cancelado", "cancelado (o que já estava na fila do pod pode terminar lá)"
        lote["status"] = "cancelado"
        salvar(lote)
    return lote


def baixar_imagens_de_novo(lid: str, iid: str) -> Dict[str, Any]:
    """🖼 Baixa de novo as imagens que o pod já gerou (o pod precisa estar ligado) e põe no cache da fonte runpod."""
    with _TRAVA:
        lote = carregar(lid)
        it = next((x for x in lote["itens"] if x["id"] == iid), None)
        if not it or not it.get("pod_img"):
            raise ProducaoErro("Esse roteiro ainda não tem imagens no pod.")
        it.update(estado="imagens", erro=None)
        _log(it, "🖼 baixando as imagens do pod de novo")
        lote["status"] = "rodando"
        salvar(lote)
    garantir_runner()
    return lote


def tentar_de_novo(lid: str, iid: str) -> Dict[str, Any]:
    """Volta o item pra etapa onde parou (se o áudio já veio, não narra de novo)."""
    with _TRAVA:
        lote = carregar(lid)
        it = next((x for x in lote["itens"] if x["id"] == iid), None)
        if not it:
            raise ProducaoErro("Roteiro não encontrado no lote.")
        pasta_i = pasta_item(lid, iid)
        tem_imgs = os.path.isdir(os.path.join(pasta_i, "imagens")) and any(
            n.endswith(".png") for n in os.listdir(os.path.join(pasta_i, "imagens")))
        if (not it.get("job_id") and tem_imgs and it.get("zip") and os.path.exists(it["zip"])
                and os.path.exists(os.path.join(pasta_i, "cenas.json"))):
            # narração e imagens já estão no PC: só monta o projeto de novo (não precisa do pod)
            it.update(estado="montando", erro=None, mensagem="montando o projeto de novo")
            lote["status"] = "rodando"
            salvar(lote)
            garantir_runner()
            return lote
        if it.get("pod_img") and os.path.exists(os.path.join(pasta_item(lid, iid), "cenas.json")):
            # as imagens já estavam no pod: só baixa de novo (não narra nem gera de novo)
            it.update(estado="imagens", erro=None, mensagem="baixando as imagens de novo")
            lote["status"] = "rodando"
            salvar(lote)
            garantir_runner()
            return lote
        tem_audio = (it.get("zip") and os.path.exists(it["zip"])) or (
            it.get("audio") and os.path.exists(it["audio"]) and it.get("transcricao") and os.path.exists(it["transcricao"]))
        it.update(estado="cenas" if tem_audio else "aguardando", erro=None, mensagem="tentando de novo",
                  pod_img=None, pod_voz=None if not tem_audio else it.get("pod_voz"))
        lote["status"] = "rodando"
        salvar(lote)
    garantir_runner()
    return lote


# ------------------------------------------------------------------ o motor
def configurar(criar_projeto: Callable[..., str], registrar_narracao: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
    """O app passa as funções que precisam dele: registrar a narração como uma geração do 🎙️ Gerador de voz (legenda,
    histórico, .zip) e criar o projeto do editor a partir desse .zip."""
    _CRIAR_PROJETO["fn"] = criar_projeto
    if registrar_narracao:
        _CRIAR_PROJETO["narracao"] = registrar_narracao


def garantir_runner() -> None:
    with _TRAVA:
        t = _RUNNER.get("thread")
        if t and t.is_alive():
            return
        if not any(l.get("status") == "rodando" for l in listar()):
            return
        t = threading.Thread(target=_loop, daemon=True, name="producao_pod")
        _RUNNER["thread"] = t
        t.start()


def _loop() -> None:
    while True:
        rodando = [l for l in listar() if l.get("status") == "rodando"]
        if not rodando:
            return
        for lote in rodando:
            try:
                _tick(lote["id"])
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        time.sleep(INTERVALO_TICK)


def _cfg_pod(lote: Dict[str, Any]) -> Dict[str, Any]:
    import pod_studio
    base = pod_studio._cfg(None)
    return dict(base, runpod_pod_url=lote.get("pod_url") or base.get("runpod_pod_url") or "")


def _log(it: Dict[str, Any], msg: str) -> None:
    it["mensagem"] = msg
    it.setdefault("log", []).append(f"{time.strftime('%H:%M:%S')} {msg}")
    it["log"] = it["log"][-40:]


def _mudar(lid: str, iid: str, **mudancas: Any) -> Dict[str, Any]:
    with _TRAVA:
        lote = carregar(lid)
        it = next(x for x in lote["itens"] if x["id"] == iid)
        msg = mudancas.pop("_log", None)
        if mudancas.get("estado") and mudancas["estado"] != "erro":
            mudancas.setdefault("erro", None)
        it.update(mudancas)
        if msg:
            _log(it, msg)
        if all(x["estado"] in ESTADOS_FINAIS for x in lote["itens"]) and lote.get("status") == "rodando":
            lote["status"] = "concluido"
            lote["concluido"] = time.time()
            _avisar_lote(lote)
        salvar(lote)
        return it


def _avisar_lote(lote: Dict[str, Any]) -> None:
    try:
        import notificacoes
        ok = sum(1 for x in lote["itens"] if x["estado"] == "pronto")
        notificacoes.avisar(f"🏭 {lote['nome']}: {ok} de {len(lote['itens'])} projeto(s) pronto(s)",
                            "Abra cada um no editor pra completar as cenas pendentes.", f"/producao-pod/{lote['id']}",
                            "ok" if ok == len(lote["itens"]) else "erro", "producao_pod")
    except Exception:  # noqa: BLE001
        pass


_OCUPADOS: Dict[str, bool] = {}


def _tick(lid: str) -> None:
    import pod_studio
    lote = carregar(lid)
    cfg = _cfg_pod(lote)
    for it in lote["itens"]:
        if it["estado"] in ESTADOS_FINAIS or _OCUPADOS.get(it["id"]):
            continue
        try:
            if it["estado"] == "aguardando":
                _enviar_narracao(lote, it, cfg)
            elif it["estado"] == "narrando":
                st = pod_studio.job(it["pod_voz"], cfg)
                if st["status"] in pod_studio.FINAIS:
                    _em_segundo_plano(lid, it["id"], lambda l, i, _st=st: _receber_narracao(carregar(l), next(
                        x for x in carregar(l)["itens"] if x["id"] == i), _st, cfg))
                else:
                    p = st.get("progresso") or {}
                    fila = f" — {st['posicao_fila']}º na fila" if st.get("posicao_fila") else ""
                    _mudar(lid, it["id"], mensagem=f"🗣️ {st.get('mensagem') or st['status']} {p.get('feito', 0)}/{p.get('total', 0)}{fila}")
            elif it["estado"] == "cenas":
                _em_segundo_plano(lid, it["id"], _planejar_cenas)
            elif it["estado"] == "imagens":
                st = pod_studio.job(it["pod_img"], cfg)
                if st["status"] in pod_studio.FINAIS:
                    _em_segundo_plano(lid, it["id"], _receber_imagens)
                else:
                    p = st.get("progresso") or {}
                    _mudar(lid, it["id"], mensagem=f"🖼 {p.get('feito', 0)}/{p.get('total', 0)} imagens"
                                                   + (f" — {st['posicao_fila']}º na fila" if st.get("posicao_fila") else ""))
            elif it["estado"] == "montando":
                _em_segundo_plano(lid, it["id"], _montar)
        except pod_studio.PodErro as exc:
            n = int(it.get("falhas_pod") or 0) + 1
            if n >= 8:  # ~30 s sem conseguir falar com o pod
                _mudar(lid, it["id"], estado="erro", erro=str(exc), falhas_pod=0, _log=f"❌ {exc}")
            else:
                _mudar(lid, it["id"], falhas_pod=n, mensagem=f"⚠ {exc} (tentando de novo)")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            _mudar(lid, it["id"], estado="erro", erro=f"{type(exc).__name__}: {exc}", _log=f"❌ {exc}")


def _em_segundo_plano(lid: str, iid: str, fn: Callable[[str, str], None]) -> None:
    """Etapas demoradas (IA, baixar imagens, criar o projeto) não travam o acompanhamento dos outros roteiros."""
    _OCUPADOS[iid] = True

    def _rodar():
        try:
            fn(lid, iid)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            _mudar(lid, iid, estado="erro", erro=f"{type(exc).__name__}: {exc}", _log=f"❌ {exc}")
        finally:
            _OCUPADOS.pop(iid, None)

    threading.Thread(target=_rodar, daemon=True).start()


# ------------------------------------------------------------------ etapas
def _referencia(perfil: str) -> Optional[str]:
    if not perfil:
        return None
    from tts import voice_generator as vg
    return vg.caminho_perfil_de_voz(perfil)[0]


def _enviar_narracao(lote: Dict[str, Any], it: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    import pod_studio
    texto = texto_para_tts(it["texto"], it["idioma"], it["motor"])
    jid = pod_studio.enviar_narracao(texto, motor=it["motor"], idioma=it["idioma"], referencia=_referencia(it["perfil"]),
                                     exaggeration=it["exaggeration"], cfg_weight=it["cfg_weight"],
                                     transcrever=True, nome="narracao", cfg=cfg)
    _mudar(lote["id"], it["id"], estado="narrando", pod_voz=jid, inicio=time.time(), falhas_pod=0,
           _log=f"🗣️ narração na fila do pod ({len(texto.split())} palavras)")


def _receber_narracao(lote: Dict[str, Any], it: Dict[str, Any], st: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    import pod_studio
    if st["status"] not in ("concluido", "concluido_com_erros"):
        erros = "; ".join(str(e.get("erro")) for e in (st.get("erros") or [])[:3])
        raise ProducaoErro(f"o pod não narrou ({st['status']}): {st.get('mensagem') or ''} {erros}".strip())
    arqs = st.get("arquivos") or []
    wav = next((a for a in arqs if a.endswith(".wav")), None)
    trans = next((a for a in arqs if a.endswith(".transcricao.json")), None)
    if not wav or not trans:
        raise ProducaoErro("o pod não devolveu o áudio e a transcrição (o Whisper está instalado no pod? veja voz-1.log)")
    pasta = pasta_item(lote["id"], it["id"])
    audio = pod_studio.baixar(it["pod_voz"], wav, os.path.join(pasta, "narracao.wav"), cfg)
    tr = pod_studio.baixar(it["pod_voz"], trans, os.path.join(pasta, "transcricao.json"), cfg)
    _mudar(lote["id"], it["id"], audio=audio, transcricao=tr,
           _log="✅ narração e transcrição recebidas" + (" (com avisos do pod)" if st["status"] != "concluido" else ""))
    _gerar_zip(lote["id"], it["id"])


def _gerar_zip(lid: str, iid: str) -> None:
    """Igual ao 🎙️ Gerador de voz: legenda com o texto do roteiro, chamadas, capítulos, 📜 Histórico e o .zip."""
    fn = _CRIAR_PROJETO.get("narracao")
    if not fn:
        raise ProducaoErro("o site não registrou o Gerador de voz (reinicie o site)")
    lote = carregar(lid)
    it = next(x for x in lote["itens"] if x["id"] == iid)
    with open(it["transcricao"], encoding="utf-8") as f:
        segs = json.load(f)
    if not segs:
        raise ProducaoErro("a transcrição veio vazia")
    r = fn(item=it, lote=lote, wav=it["audio"], segments=segs)
    _mudar(lid, iid, estado="cenas", gv_id=r["gv_id"], zip=r["zip"], total=r["total"],
           _log="📜 narração + legenda no Histórico do Gerador de voz (.zip pronto)")


def _elenco_do_item(lid: str, iid: str, it: Dict[str, Any], cfg_lote: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """🎭 O elenco do Modelo de vídeo (monta com a IA se ainda não tem)."""
    if not cfg_lote.get("rostos", True) or it.get("origem") != "dossie" or not it.get("origem_id"):
        return None
    try:
        import dossies
        import elenco
        p = dossies.carregar(_BASE, it["origem_id"])
        if not p.get("elenco"):
            _mudar(lid, iid, mensagem="🎭 a IA está montando o elenco (quem é quem nas fotos e com que idade)…")
        el = elenco.do_projeto(_BASE, p, criar=True, job=it["origem_id"])
        n = len([x for x in el.get("pessoas") or [] if x.get("usar", True)])
        nl = len([x for x in el.get("locais") or [] if x.get("usar", True)])
        if n or nl:
            _mudar(lid, iid, _log=f"🎭 elenco: {n} pessoa(s) e {nl} local(is) com foto — "
                   + ", ".join(x["nome"] for x in (el.get("pessoas") or [])[:6]))
        return el if (n or nl) else None
    except Exception as exc:  # noqa: BLE001
        _mudar(lid, iid, _log=f"🎭 sem elenco ({str(exc)[:120]}) — imagens sem rosto real")
        return None


def _rostos(it: Dict[str, Any], resposta: Dict[str, Any], info: Dict[int, Dict[str, Any]]) -> Dict[str, List[List[str]]]:
    """Cenas do pod com pessoa do elenco: o prompt ganha "image 1…" e as fotos de referência.
    → {"índice da cena": [[nome do arquivo, caminho], …]} (e o "query" da cena muda no `resposta`)."""
    if it.get("origem") != "dossie":
        return {}
    import dossies
    import elenco
    p = dossies.carregar(_BASE, it["origem_id"])
    el = p.get("elenco") or {}
    out: Dict[str, List[List[str]]] = {}
    for k, s in enumerate(resposta["segments"]):
        pessoas = (info.get(k + 1) or {}).get("pessoas") or []
        lugar = (info.get(k + 1) or {}).get("lugar") or ""
        if s["provider"] != "runpod" or not (pessoas or lugar):
            continue
        prompt, refs = elenco.rostos_da_cena(el, pessoas, s["query"], _BASE, p, lugar=lugar,
                                             ano=(info.get(k + 1) or {}).get("ano") or 0)
        s["query"] = prompt  # 📍 local sem foto: a descrição dele entra no prompt mesmo sem referência
        if refs:
            s["rostos"] = [x["nome"] for x in pessoas]
            out[str(k)] = [[n, c] for n, c in refs]
    return out


def _materiais_do_modelo(it: Dict[str, Any], cenas: List[Dict[str, Any]]) -> Dict[int, Dict[str, str]]:
    """🕵️ Roteiro de um Modelo de vídeo: as cenas onde caem as marcas [I3] viram a própria foto/vídeo do modelo."""
    if it.get("origem") != "dossie" or not it.get("origem_id"):
        return {}
    try:
        import cenas_lote
        import dossies
        p = dossies.carregar(_BASE, it["origem_id"])
        momentos = (p.get("resultado") or {}).get("momentos") or []
        tipos = {m["id"].upper(): m["tipo"] for m in dossies.midias_para_editor(_BASE, p)}
        por_cena = cenas_lote.cenas_dos_momentos(cenas, [mo for mo in momentos if str(mo.get("midia") or "").upper() in tipos])
        return {i: {"id": mid, "tipo": tipos[mid], "provider": "material"} for i, mid in por_cena.items()}
    except Exception:  # noqa: BLE001 — modelo apagado etc.: segue sem as fotos
        return {}


def _planejar_cenas(lid: str, iid: str) -> None:
    import cenas_lote
    import pod_studio
    lote = carregar(lid)
    it = next(x for x in lote["itens"] if x["id"] == iid)
    cfg_lote = lote["config"]
    with open(it["transcricao"], encoding="utf-8") as f:
        segs = json.load(f)
    if not segs:
        raise ProducaoErro("a transcrição veio vazia")
    if not it.get("zip"):  # lote de antes desta versão: monta o .zip agora
        _gerar_zip(lid, iid)
        it = next(x for x in carregar(lid)["itens"] if x["id"] == iid)
    total = float(it.get("total") or segs[-1]["end"])  # = fim da legenda do .zip (o projeto usa esse tempo)
    cenas = cenas_lote.cortar_cenas(segs, cfg_lote["intervalo"], total=total)
    _mudar(lid, iid, _log=f"🎬 {len(cenas)} cenas de ~{cfg_lote['intervalo']:g} s")
    roteiro = " ".join(str(s.get("text") or "").strip() for s in segs)
    ficha = None
    import ia_servico
    avisos = []
    if ia_servico.ativo("producao_pod"):
        try:
            import ia_midia
            if ia_servico.ativo("buscas"):
                _mudar(lid, iid, mensagem="🤖 lendo o roteiro (ficha do vídeo)…")
                ficha = ia_midia.ficha_visual(roteiro, it["titulo"], it["idioma"])
        except Exception:  # noqa: BLE001
            ficha = None
        el = _elenco_do_item(lid, iid, it, cfg_lote)
        info = cenas_lote.descrever(cenas, roteiro, it["idioma"], ficha,
                                    on_passo=lambda m: _mudar(lid, iid, mensagem=m), elenco=el)
    else:
        info = {}
        avisos.append("🤖 IA desligada (recurso “🏭 Produção no pod”): as cenas do pod foram espalhadas por igual e o "
                      "prompt é a própria fala — ligue a IA em 🤖 IA pra escolher as difíceis e escrever prompts bons.")
    pct = cfg_lote["pct"] / 100.0
    materiais = _materiais_do_modelo(it, cenas)
    if materiais:
        _mudar(lid, iid, _log=f"🕵️ {len(materiais)} cenas com as fotos do modelo de vídeo (marcas [I…] do roteiro)")
    if info:
        # 🎭 cena com pessoa do elenco ganha +2 (o rosto real só o pod faz)
        notas = [0 if i in materiais else min(10, (info.get(i + 1) or {}).get("dificil", 0)
                                              + (2 if (info.get(i + 1) or {}).get("pessoas") else 0)
                                              + (1 if (info.get(i + 1) or {}).get("lugar") else 0))
                 for i in range(len(cenas))]
        escolhidas = cenas_lote.escolher(notas, pct)
    else:
        escolhidas = cenas_lote.escolher_sem_ia(len(cenas), pct)
    escolhidas = {i for i in escolhidas if i not in materiais}
    resposta = cenas_lote.montar_json(cenas, info, escolhidas, cfg_lote.get("estilo_extra") or "", materiais,
                                      epoca=cfg_lote.get("epoca", True))
    resposta["_ficha"] = ficha
    pasta = pasta_item(lid, iid)
    rostos = _rostos(it, resposta, info) if info else {}
    with open(os.path.join(pasta, "rostos.json"), "w", encoding="utf-8") as f:
        json.dump(rostos, f, ensure_ascii=False, indent=1)
    if rostos:
        avisos.append(f"🎭 {len(rostos)} cena(s) com o rosto de pessoas reais ou um local do elenco (fotos de referência) — "
                      "FLUX.2 klein no pod")
    with open(os.path.join(pasta, "cenas.json"), "w", encoding="utf-8") as f:
        json.dump(resposta, f, ensure_ascii=False, indent=1)
    res = cenas_lote.resumo(cenas, escolhidas)
    if not escolhidas:
        _mudar(lid, iid, estado="montando", cenas=res, avisos=avisos,
               _log="🖼 nenhuma cena pro pod (porcentagem 0 ou nada difícil) — indo pro projeto")
        return
    w, h = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}[cfg_lote["orientacao"]]
    pedidos = [{"prompt": s["query"], "nome": f"cena-{k + 1:04d}",
                **({"referencias": rostos[str(k)]} if str(k) in rostos else {})}
               for k, s in enumerate(resposta["segments"]) if s["provider"] == "runpod"]
    jid, sem_refs = pod_studio.enviar_imagens_com_refs(pedidos, largura=w, altura=h, nome=it["titulo"][:40], cfg=_cfg_pod(lote))
    if sem_refs:
        avisos.append("🎭 O pod ainda não tem o FLUX.2 klein (código antigo): as cenas com rosto foram no Z-Image, sem o "
                      "rosto. No pod: git pull && bash setup.sh && bash start.sh.")
    _mudar(lid, iid, estado="imagens", pod_img=jid, cenas=res, avisos=avisos,
           _log=f"🖼 {len(pedidos)} imagens na fila do pod ({res['pct']}% das cenas)")


def _receber_imagens(lid: str, iid: str) -> None:
    import pod_studio
    import runpod_gerador
    lote = carregar(lid)
    it = next(x for x in lote["itens"] if x["id"] == iid)
    cfg = _cfg_pod(lote)
    pasta = pasta_item(lid, iid)
    pasta_img = os.path.join(pasta, "imagens")
    try:
        st = pod_studio.job(it["pod_img"], cfg)
    except Exception:
        # pod desligado: usa só as imagens que já estão no PC
        if not (os.path.isdir(pasta_img) and os.listdir(pasta_img)):
            raise
        st = {"arquivos": [n for n in os.listdir(pasta_img) if n.endswith(".png")]}
    with open(os.path.join(pasta, "cenas.json"), encoding="utf-8") as f:
        resposta = json.load(f)
    prontos = set(st.get("arquivos") or [])
    cfg_rp = {"orientation": lote["config"]["orientacao"]}
    feitas = faltaram = 0
    pasta_img = os.path.join(pasta, "imagens")
    os.makedirs(pasta_img, exist_ok=True)
    for k, s in enumerate(resposta["segments"]):
        if s["provider"] != "runpod":
            continue
        nome = f"cena-{k + 1:04d}.png"
        if nome not in prontos:
            faltaram += 1
            continue
        local = os.path.join(pasta_img, nome)
        if not (os.path.exists(local) and os.path.getsize(local) > 0):
            local = pod_studio.baixar(it["pod_img"], nome, local, cfg)
        for tentativa in range(3):  # o cache.json pode estar preso por um instante no Windows
            try:
                runpod_gerador.guardar_do_pod(s["query"], local, s["query"], cfg_rp)
                break
            except OSError:
                if tentativa == 2:
                    raise
                time.sleep(1.5)
        feitas += 1
        if feitas % 10 == 0:
            _mudar(lid, iid, mensagem=f"⬇ baixando imagens {feitas}…")
    msg = f"🖼 {feitas} imagens prontas" + (f" ({faltaram} falharam no pod — o editor tenta de novo)" if faltaram else "")
    if it.get("job_id"):  # o projeto já existe (baixou de novo): não cria outro
        _mudar(lid, iid, estado="pronto", _log=msg + " — no editor clique em 🔁 Pôr as imagens do pod de volta")
        return
    _mudar(lid, iid, estado="montando", _log=msg)


def _registrar_imagens_locais(lote: Dict[str, Any], pasta: str, resposta: Dict[str, Any]) -> int:
    """Põe no cache da fonte runpod as imagens do pod que já estão no PC (se o registro falhou antes, ex. WinError 5)."""
    import runpod_gerador
    pasta_img = os.path.join(pasta, "imagens")
    cfg_rp = {"orientation": lote["config"]["orientacao"]}
    n = 0
    for k, s in enumerate(resposta.get("segments") or []):
        local = os.path.join(pasta_img, f"cena-{k + 1:04d}.png")
        if s.get("provider") != "runpod" or not os.path.exists(local):
            continue
        try:
            runpod_gerador.guardar_do_pod(s["query"], local, s["query"], cfg_rp)
            n += 1
        except OSError:
            pass
    return n


def _montar(lid: str, iid: str) -> None:
    lote = carregar(lid)
    it = next(x for x in lote["itens"] if x["id"] == iid)
    fn = _CRIAR_PROJETO.get("fn")
    if not fn:
        raise ProducaoErro("o site não registrou a criação de projetos (reinicie o site)")
    pasta = pasta_item(lid, iid)
    with open(os.path.join(pasta, "cenas.json"), encoding="utf-8") as f:
        resposta = json.load(f)
    ficha = resposta.pop("_ficha", None)
    _registrar_imagens_locais(lote, pasta, resposta)
    job_id = fn(item=it, lote=lote, zip_path=it["zip"], resposta=resposta, ficha=ficha)
    _mudar(lid, iid, estado="pronto", job_id=job_id, fim=time.time(),
           _log="✅ projeto criado — abra no editor e complete as cenas pendentes")


def resumo_lote(lote: Dict[str, Any]) -> Dict[str, Any]:
    cont: Dict[str, int] = {}
    for it in lote["itens"]:
        cont[it["estado"]] = cont.get(it["estado"], 0) + 1
    fim = lote.get("concluido") or time.time()
    return {"contagem": cont, "minutos": round((fim - lote.get("criado", fim)) / 60, 1),
            "prontos": cont.get("pronto", 0), "total": len(lote["itens"])}
