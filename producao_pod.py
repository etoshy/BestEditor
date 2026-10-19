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
    cfg["pct"] = int(_num(config.get("pct"), 30, 0, 100))
    cfg["orientacao"] = config.get("orientacao") if config.get("orientacao") in ("16:9", "9:16", "1:1") else "16:9"
    cfg["estilo_extra"] = " ".join(str(config.get("estilo_extra") or "").split())[:300]
    cfg["rostos"] = config.get("rostos", True) is not False  # 🎭 rosto das pessoas do elenco (FLUX.2 klein no pod)
    cfg["epoca"] = config.get("epoca", True) is not False  # 🎞 visual de foto do ano de cada cena
    canal = str(config.get("canal") or "").strip()  # 🎨 v84_181: "" = o do 🕵️ Modelo de vídeo · "-" = nenhum · slug da marca
    cfg["canal"] = canal if canal == "-" or re.fullmatch(r"[a-z0-9_-]{1,60}", canal) else ""
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
        try:  # 🎨 o canal (pacote) deste roteiro — pro 📦 Zip do canal e pra mostrar no lote
            import canal_pod
            prontos[-1]["canal"] = canal_pod.slug_do_item(_BASE, prontos[-1], cfg) or None
        except Exception:  # noqa: BLE001
            prontos[-1]["canal"] = None
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


def _url_valida(url: str) -> str:
    u = str(url or "").strip().rstrip("/")
    if u and not re.fullmatch(r"https?://[^\s\"'<>]+", u):
        raise ProducaoErro("Esse link do pod não parece um endereço (ex.: https://<id>-8000.proxy.runpod.net).")
    return u


def _aplicar_pod_novo(lote: Dict[str, Any], url: str) -> bool:
    """🔗 v84_181: troca o pod do lote (VPS nova). Os jobs do pod antigo não existem no novo: os itens esquecem eles
    (o que já veio pro PC fica) e os 🗣️ perfis de voz vão de novo. Também vira o pod das ⚙️ Configurações (o editor
    usa o mesmo). → True se mudou."""
    url = _url_valida(url)
    if not url or url == (lote.get("pod_url") or ""):
        return False
    lote.setdefault("pods_antigos", []).append(lote.get("pod_url") or "")
    lote["pod_url"] = url
    for it in lote["itens"]:
        it["pod_imgs"] = []
        it["reenvios_img"] = 0
        it["falhas_pod"] = 0
        if it.get("pod_img"):
            it["pod_img_antigo"] = it["pod_img"]
            it["pod_img"] = None
    _PERFIS_ENVIADOS.pop(lote["id"], None)
    try:
        from site_config import save_site_config
        save_site_config({"runpod_pod_url": url})
    except Exception:  # noqa: BLE001 — o lote já guarda o link; as Configurações são só conveniência
        pass
    return True


def trocar_pod(lid: str, url: str) -> Dict[str, Any]:
    """🔗 Só troca o link do pod do lote (os itens que estavam esperando o pod antigo precisam de 🔁 Tentar de novo)."""
    with _TRAVA:
        lote = carregar(lid)
        if not _url_valida(url):
            raise ProducaoErro("Cole o link do pod.")
        mudou = _aplicar_pod_novo(lote, url)
        salvar(lote)
    return {"ok": True, "mudou": mudou, "pod_url": lote["pod_url"]}


def tentar_de_novo(lid: str, iid: str, pod_url: str = "") -> Dict[str, Any]:
    """Volta o item pra etapa onde parou (se o áudio já veio, não narra de novo).
    🔗 v84_181: com `pod_url` novo (VPS nova) — sem áudio, pede a narração de novo; com áudio e cenas, manda pro pod
    novo SÓ as imagens que ainda não estão no PC."""
    with _TRAVA:
        lote = carregar(lid)
        it = next((x for x in lote["itens"] if x["id"] == iid), None)
        if not it:
            raise ProducaoErro("Roteiro não encontrado no lote.")
        if _aplicar_pod_novo(lote, pod_url):
            _log(it, f"🔗 pod novo: {lote['pod_url']}")
        pasta_i = pasta_item(lid, iid)
        tem_imgs = os.path.isdir(os.path.join(pasta_i, "imagens")) and any(
            n.endswith(".png") for n in os.listdir(os.path.join(pasta_i, "imagens")))
        tem_cenas = os.path.exists(os.path.join(pasta_i, "cenas.json"))
        tem_audio = (it.get("zip") and os.path.exists(it["zip"])) or (
            it.get("audio") and os.path.exists(it["audio"]) and it.get("transcricao") and os.path.exists(it["transcricao"]))
        faltam = faltam_no_pc(lid, iid) if tem_cenas else -1
        if (not it.get("job_id") and tem_imgs and it.get("zip") and os.path.exists(it["zip"]) and tem_cenas
                and (faltam == 0 or (not it.get("pod_img") and not lote.get("pod_url")))):
            # narração e imagens já estão no PC: só monta o projeto de novo (não precisa do pod)
            it.update(estado="montando", erro=None, mensagem="montando o projeto de novo")
            lote["status"] = "rodando"
            salvar(lote)
            garantir_runner()
            return lote
        if tem_cenas and tem_audio and (it.get("pod_img") or it.get("pod_img_antigo")):
            # já tinha mandado as imagens: no MESMO pod só baixa de novo; num pod NOVO (pod_img vazio) o _tick manda
            # pra ele só as que faltam no PC (não narra nem planeja de novo)
            it.update(estado="imagens", erro=None, reenvios_img=0,
                      mensagem="baixando as imagens de novo" if it.get("pod_img")
                      else f"🔁 mandando pro pod novo as {faltam} imagem(ns) que faltam")
            lote["status"] = "rodando"
            salvar(lote)
            garantir_runner()
            return lote
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
                    _mudar(lid, it["id"], mensagem=f"🗣️ {st.get('mensagem') or st['status']} {p.get('feito', 0)}/{p.get('total', 0)}{fila}"
                                                   + _vigiar_parado(it, st))
            elif it["estado"] == "cenas":
                _em_segundo_plano(lid, it["id"], _planejar_cenas)
            elif it["estado"] == "imagens" and not it.get("pod_img"):
                # 🔗 pod novo (ou o job sumiu): manda só as imagens que faltam no PC
                _em_segundo_plano(lid, it["id"], lambda l, i: _reenviar_faltantes(l, i, manual=True, pod_novo=True))
            elif it["estado"] == "imagens":
                try:
                    st = pod_studio.job(it["pod_img"], cfg)
                except pod_studio.PodErro as exc:
                    if "404" not in str(exc):
                        raise
                    # o pod não conhece esse job (reiniciou do zero / outro pod no mesmo link): manda de novo o que falta
                    _mudar(lid, it["id"], pod_img=None, pod_img_antigo=it["pod_img"],
                           _log="⚠ o pod não tem mais o job das imagens — mandando de novo as que faltam")
                    continue
                if st["status"] in pod_studio.FINAIS:
                    if (st.get("erros") and int(it.get("reenvios_img") or 0) < 1
                            and st["status"] != "cancelado"):  # 🔁 falhou alguma (ex.: memória): manda só essas de novo, 1 vez
                        _em_segundo_plano(lid, it["id"], _reenviar_faltantes)
                    else:
                        _em_segundo_plano(lid, it["id"], _receber_imagens)
                else:
                    p = st.get("progresso") or {}
                    _mudar(lid, it["id"], mensagem=f"🖼 {p.get('feito', 0)}/{p.get('total', 0)} imagens"
                                                   + (f" — {st['posicao_fila']}º na fila" if st.get("posicao_fila") else "")
                                                   + _vigiar_parado(it, st))
                    _baixar_parciais_bg(lid, it["id"], st)
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


_BAIXANDO: Dict[str, float] = {}
PARADO_S = 600  # ⏱ 10 min sem andar nada no pod = provavelmente travou
_MARCOS: Dict[str, Any] = {}


def _vigiar_parado(it: Dict[str, Any], st: Dict[str, Any]) -> str:
    """⏱ v84_181: o job do pod não anda (ex.: "0/8 imagens — 1º na fila" pra sempre: o processo de imagens do pod
    caiu e ninguém pega a fila). Depois de PARADO_S sem mudar nada, o aviso diz o que fazer. → o texto do aviso ou ""."""
    p = st.get("progresso") or {}
    marco = (st.get("status"), p.get("feito"), p.get("total"), st.get("posicao_fila"), st.get("mensagem"))
    chave = f"{it['id']}:{it.get('pod_img') if it['estado'] == 'imagens' else it.get('pod_voz')}"
    antes = _MARCOS.get(chave)
    agora = time.time()
    if not antes or antes[0] != marco:
        _MARCOS[chave] = (marco, agora)
        return ""
    parado = agora - antes[1]
    if parado < PARADO_S:
        return ""
    return (f" — ⚠ parado há {int(parado // 60)} min: o pod pode ter travado (veja os logs do pod). "
            "Se ligou outro pod, cole o link novo no topo e clique em 🔁 Tentar de novo")


def _baixar_parciais_bg(lid: str, iid: str, st: Dict[str, Any]) -> None:
    """👀 Enquanto o pod gera, as imagens que ficaram prontas já vêm pro PC (de 20 em 20 s), pra você ver como está
    ficando no lote. Não trava o acompanhamento; erro aqui é ignorado (a etapa final baixa o que faltar)."""
    if _BAIXANDO.get(iid, 0) > time.time() - 20:
        return
    _BAIXANDO[iid] = time.time()
    prontos = [n for n in st.get("arquivos") or [] if re.fullmatch(r"cena-\d{4}\.png", n)]
    if not prontos:
        return

    def _rodar():
        try:
            import pod_studio
            lote = carregar(lid)
            it = next(x for x in lote["itens"] if x["id"] == iid)
            pasta_img = os.path.join(pasta_item(lid, iid), "imagens")
            os.makedirs(pasta_img, exist_ok=True)
            novas = [n for n in prontos if not os.path.exists(os.path.join(pasta_img, n))][:40]
            for n in novas:
                pod_studio.baixar(it["pod_img"], n, os.path.join(pasta_img, n), _cfg_pod(lote))
            if novas:
                tem = sorted((x for x in os.listdir(pasta_img) if x.endswith(".png")),
                             key=lambda x: os.path.getmtime(os.path.join(pasta_img, x)))
                _mudar(lid, iid, baixadas=len(tem), recentes=tem[-12:][::-1])
        except Exception:  # noqa: BLE001
            pass
        finally:
            _BAIXANDO[iid] = time.time()

    threading.Thread(target=_rodar, daemon=True).start()


def galeria(lid: str, iid: str) -> List[Dict[str, Any]]:
    """As imagens do pod que já estão no PC, com o prompt e se a cena tem rosto/local do elenco."""
    pasta = pasta_item(lid, iid)
    pasta_img = os.path.join(pasta, "imagens")
    try:
        with open(os.path.join(pasta, "cenas.json"), encoding="utf-8") as f:
            segs = json.load(f).get("segments") or []
    except (OSError, ValueError):
        segs = []
    try:
        with open(os.path.join(pasta, "rostos.json"), encoding="utf-8") as f:
            rostos = json.load(f)
    except (OSError, ValueError):
        rostos = {}
    out = []
    for n in sorted(os.listdir(pasta_img)) if os.path.isdir(pasta_img) else []:
        m = re.fullmatch(r"cena-(\d{4})\.png", n)
        if not m:
            continue
        k = int(m.group(1)) - 1
        s = segs[k] if 0 <= k < len(segs) else {}
        out.append({"nome": n, "cena": k + 1, "inicio": s.get("start"), "prompt": (s.get("query") or "")[:600],
                    "visual": s.get("visual") or "", "rostos": s.get("rostos") or [], "com_referencia": str(k) in rostos})
    return out


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


# ------------------------------------------------------------------ 🎭 várias vozes num roteiro (v84_180)
def _texto_com_vozes(it: Dict[str, Any]) -> str:
    """Canal com personagens (🕵️ Modelo de vídeo do pacote): [mira|curiosa] → [<voz escolhida>|exag=..|cfg=..]."""
    if it.get("origem") != "dossie" or not it.get("origem_id"):
        return it["texto"]
    try:
        import dossies
        p = dossies.carregar(_BASE, it["origem_id"])
        perfil = dossies.perfil_do_modelo((p.get("config") or {}).get("modelo"))
    except Exception:  # noqa: BLE001
        return it["texto"]
    if not perfil:
        return it["texto"]
    import canal_perfil
    cfg = p.get("config") or {}
    texto, faltam = canal_perfil.converter_para_vozes(it["texto"], perfil, cfg.get("vozes_personagens") or {},
                                                      usar_emocao=cfg.get("ia_emocao", True) is not False)
    if faltam:
        raise ProducaoErro("falta escolher a voz de " + ", ".join(faltam) + " (🕵️ Modelo de vídeo → 🎭 Vozes dos personagens)")
    return texto


def multivoz_para_pod(texto: str, it: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Roteiro com tags de voz → UM texto pro pod com {{perfil=…, emocao=…, cfg=…}} antes de cada fala (o pod troca a voz
    e a emoção no meio e devolve um áudio só, transcrito). → {"texto", "perfis", "legenda"} ou None (uma voz só).
    No pod só roda Chatterbox: cada voz usada precisa ser Chatterbox com um 🗣️ perfil de voz."""
    import multivoz as mv
    vozes = mv.por_slug()
    d = mv.dividir(texto, vozes)
    if not d["usadas"]:
        return None
    perfis: List[str] = []
    blocos: List[str] = []
    for f in d["falas"]:
        v = vozes.get(f["slug"]) if f["slug"] else None
        c = (v or {}).get("config") or {}
        if v is not None:
            if v.get("motor") not in ("chatterbox", "chatterbox_turbo") or not c.get("vozPerfil"):
                raise ProducaoErro(f"a voz [{v['slug']}] usa {v.get('motor')}"
                                   + ("" if c.get("vozPerfil") else " sem perfil de voz")
                                   + " — no pod só roda Chatterbox com um 🗣️ perfil de voz (troque em 🎙 Gerador de voz → 🎭 Vozes)")
            perfil = c["vozPerfil"]
        else:
            perfil = it.get("perfil") or ""
        aj = f.get("ajustes") or {}
        exag = aj.get("exag", c.get("chatterboxExaggeration", it.get("exaggeration", 0.5)))
        cfgw = aj.get("cfg", c.get("chatterboxCfgWeight", it.get("cfg_weight", 0.5)))
        fala = texto_para_tts(f["texto"], it["idioma"], it["motor"])
        if not fala:
            continue
        # 🎭 v84_187: quem fala (a voz do personagem / narrador) → o pod devolve o <nome>.falas.json com o tempo exato
        marca = [f"emocao={float(exag):.2f}", f"cfg={float(cfgw):.2f}", f"quem={f['slug'] or 'narrador'}"]
        if perfil:
            marca.insert(0, f"perfil={perfil}")
            if perfil not in perfis:
                perfis.append(perfil)
        blocos.append("{{" + ", ".join(marca) + "}} " + fala)
    if not blocos:
        return None
    # a legenda é o roteiro sem as tags de voz (as chamadas [[INSCREVA]]/[[VENDA]] ficam: o site alinha elas)
    sem_tags = mv._RE_TAG.sub(lambda m: "" if mv.slugify(m.group(1).partition("|")[0]) in vozes else m.group(0), texto)
    return {"texto": "\n\n".join(blocos), "perfis": perfis, "legenda": re.sub(r"[ \t]{2,}", " ", sem_tags).strip()}


_PERFIS_ENVIADOS: Dict[str, set] = {}  # lote → perfis já mandados (uma vez por lote: não troca a voz no meio de outra narração)


def _mandar_perfis(perfis: List[str], cfg: Dict[str, Any], lote_id: str = "") -> None:
    """Os 🗣️ perfis usados no roteiro vão pro pod (o mesmo .zip do 📦 Exportar; substitui o que já estava lá)."""
    ja = _PERFIS_ENVIADOS.setdefault(lote_id, set())
    novos = [x for x in perfis if x not in ja]
    if not novos:
        return
    import perfis_pacote
    import pod_studio
    pod_studio.importar_perfis(perfis_pacote.exportar(novos), cfg)
    ja.update(novos)


# ------------------------------------------------------------------ etapas
def _referencia(perfil: str) -> Optional[str]:
    if not perfil:
        return None
    from tts import voice_generator as vg
    return vg.caminho_perfil_de_voz(perfil)[0]


def _enviar_narracao(lote: Dict[str, Any], it: Dict[str, Any], cfg: Dict[str, Any]) -> None:
    import pod_studio
    mv = multivoz_para_pod(_texto_com_vozes(it), it)  # 🎭 v84_180: várias vozes, cada uma com a sua emoção
    if mv:
        _mandar_perfis(mv["perfis"], cfg, lote["id"])
        jid = pod_studio.enviar_narracao(mv["texto"], motor="chatterbox", idioma=it["idioma"], referencia=None,
                                         exaggeration=it["exaggeration"], cfg_weight=it["cfg_weight"],
                                         transcrever=True, nome="narracao", cfg=cfg, marcacoes=True)
        _mudar(lote["id"], it["id"], estado="narrando", pod_voz=jid, inicio=time.time(), falhas_pod=0,
               texto_legenda=mv["legenda"],
               _log=f"🗣️ narração com {len(mv['perfis'])} voz(es) na fila do pod ({len(mv['legenda'].split())} palavras): "
                    + ", ".join(mv["perfis"]))
        return
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
    falas = next((a for a in arqs if a.endswith(".falas.json")), None)
    extra: Dict[str, Any] = {}
    if falas:  # 🎭 v84_187: quem falou quando (exato) — o editor põe as personagens do canal nesses momentos
        try:
            extra["falas_pod"] = pod_studio.baixar(it["pod_voz"], falas, os.path.join(pasta, "falas.json"), cfg)
        except Exception:  # noqa: BLE001 — sem ele o editor casa o roteiro com as palavras
            pass
    _mudar(lote["id"], it["id"], audio=audio, transcricao=tr, **extra,
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
        ms = {m["id"].upper(): m for m in dossies.midias_para_editor(_BASE, p)}
        por_cena = cenas_lote.cenas_dos_momentos(cenas, [mo for mo in momentos if str(mo.get("midia") or "").upper() in ms])
        return {i: {"id": mid, "tipo": ms[mid]["tipo"], "provider": "material", "caminho": ms[mid].get("caminho") or ""}
                for i, mid in por_cena.items()}
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
    import canal_pod
    marca = canal_pod.carregar(_BASE, canal_pod.slug_do_item(_BASE, it, cfg_lote))
    if marca:  # 🎨 v84_181: roteiro de um canal de pacote — % , estética e personagens do zip do canal
        resposta, rostos, escolhidas, avisos = _planejar_canal(lid, iid, it, cfg_lote, cenas, roteiro, marca)
        ficha = resposta.get("_ficha")
    else:
        resposta, rostos, escolhidas, avisos, ficha = _planejar_padrao(lid, iid, it, cfg_lote, cenas, roteiro)
    _enviar_cenas(lid, iid, it, lote, cenas, resposta, rostos, escolhidas, avisos)


def _planejar_padrao(lid: str, iid: str, it: Dict[str, Any], cfg_lote: Dict[str, Any], cenas: List[Dict[str, Any]],
                     roteiro: str):
    """O planejamento de sempre (true crime / roteiro sem canal): as ~pct% mais difíceis, foto realista."""
    import cenas_lote
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
        notas = [-1 if i in materiais else min(10, (info.get(i + 1) or {}).get("dificil", 0)
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
    rostos = _rostos(it, resposta, info) if info else {}
    if rostos:
        avisos.append(f"🎭 {len(rostos)} cena(s) com o rosto de pessoas reais ou um local do elenco (fotos de referência) — "
                      "FLUX.2 klein no pod")
    return resposta, rostos, escolhidas, avisos, ficha


def _planejar_canal(lid: str, iid: str, it: Dict[str, Any], cfg_lote: Dict[str, Any], cenas: List[Dict[str, Any]],
                    roteiro: str, m: Dict[str, Any]):
    """🎨 v84_181 — canal de pacote (canal_pod.py): a % do pacote, o prompt na estética da marca e os personagens
    (pessoa genérica → personagem; personagem falando → aparece; pessoa real → rosto do elenco)."""
    import canal_pod
    import cenas_lote
    import ia_servico
    ccfg = canal_pod.config(m)
    nome = (m["guia"].get("project") or {}).get("name") or m["slug"]
    _mudar(lid, iid, canal=m["slug"], _log=f"🎨 canal {nome}: {ccfg['pct']}% das cenas no pod, estética e personagens do pacote "
                                         "(o % do lote não vale pra este roteiro)")
    avisos: List[str] = []
    ficha = None
    texto_tags = it.get("texto") or roteiro  # com as tags [mira|…]: a IA sabe quem fala em cada cena
    if ia_servico.ativo("producao_pod"):
        try:
            import ia_midia
            if ia_servico.ativo("buscas"):
                _mudar(lid, iid, mensagem="🤖 lendo o roteiro (ficha do vídeo)…")
                ficha = ia_midia.ficha_visual(roteiro, it["titulo"], it["idioma"])
        except Exception:  # noqa: BLE001
            ficha = None
        el = _elenco_do_item(lid, iid, it, cfg_lote)
        info = canal_pod.descrever(cenas, texto_tags, it["idioma"], m, elenco=el, ficha=ficha,
                                   on_passo=lambda t: _mudar(lid, iid, mensagem=t))
    else:
        info = {}
        avisos.append("🤖 IA desligada (recurso “🏭 Produção no pod”): as imagens saem na estética do canal, mas o assunto é a "
                      "própria fala e sem personagens — ligue a IA em 🤖 IA pra a regra dos personagens funcionar.")
    if not info:
        info = {i + 1: canal_pod.sem_ia(c, m) for i, c in enumerate(cenas)}
    materiais = _materiais_do_modelo(it, cenas)
    # 📷 fotos marcadas no roteiro: canal 100% IA → viram referência e saem redesenhadas; vídeos entram como estão
    fotos_ref = {i: x["caminho"] for i, x in materiais.items()
                 if ccfg["fotos_do_roteiro"] == "referencia" and x.get("tipo") == "foto" and x.get("caminho")}
    materiais = {i: x for i, x in materiais.items() if i not in fotos_ref}
    if fotos_ref:
        _mudar(lid, iid, _log=f"📷 {len(fotos_ref)} foto(s) marcada(s) no roteiro vão de referência e saem no estilo do canal")
    if materiais:
        _mudar(lid, iid, _log=f"🕵️ {len(materiais)} cena(s) com os vídeos/fotos do modelo como estão")
    pct = ccfg["pct"] / 100.0
    notas = [-1 if i in materiais else (10 if i in fotos_ref else min(10, (info.get(i + 1) or {}).get("dificil", 0)
             + (2 if (info.get(i + 1) or {}).get("pessoas") or (info.get(i + 1) or {}).get("personagens")
                or (info.get(i + 1) or {}).get("mascote") else 0)))
             for i in range(len(cenas))]
    escolhidas = cenas_lote.escolher(notas, pct) if pct < 1 else {i for i in range(len(cenas)) if i not in materiais}
    escolhidas |= {i for i in fotos_ref if pct > 0}
    resposta = cenas_lote.montar_json(cenas, info, escolhidas, "", materiais, epoca=False)
    resposta["_ficha"] = ficha
    rostos: Dict[str, List[List[str]]] = {}
    n_pers = n_real = 0
    for k, sg in enumerate(resposta["segments"]):
        if sg["provider"] != "runpod":
            continue
        d = info.get(k + 1) or canal_pod.sem_ia(cenas[k], m)
        prompt, refs = canal_pod.prompt_e_refs(m, d, it.get("origem_id") if it.get("origem") == "dossie" else "",
                                               foto=fotos_ref.get(k, ""), estilo_extra=cfg_lote.get("estilo_extra") or "",
                                               cfg=ccfg)
        sg["query"] = prompt
        quem = [x["slug"] for x in d.get("personagens") or []] + ([f"mascote:{d['mascote']}"] if d.get("mascote") else [])
        if quem:
            sg["personagens"] = quem
            n_pers += 1
        if d.get("pessoas"):
            sg["rostos"] = [x["nome"] for x in d["pessoas"]]
            n_real += 1
        if refs:
            rostos[str(k)] = refs
    avisos.append(f"🎨 {nome}: {len(escolhidas)} cena(s) na estética do canal · 🎭 {n_pers} com personagem · "
                  f"👤 {n_real} com rosto real do elenco · {len(rostos)} com referência (FLUX.2 klein)")
    return resposta, rostos, escolhidas, avisos


def _enviar_cenas(lid: str, iid: str, it: Dict[str, Any], lote: Dict[str, Any], cenas: List[Dict[str, Any]],
                  resposta: Dict[str, Any], rostos: Dict[str, Any], escolhidas, avisos: List[str]) -> None:
    import cenas_lote
    import pod_studio
    cfg_lote = lote["config"]
    pasta = pasta_item(lid, iid)
    with open(os.path.join(pasta, "rostos.json"), "w", encoding="utf-8") as f:
        json.dump(rostos, f, ensure_ascii=False, indent=1)
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


def _prontos_no_pod(it: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, str]:
    """{nome do arquivo: id do job do pod que tem ele} — juntando o job das imagens e os de reenvio."""
    import pod_studio
    out: Dict[str, str] = {}
    for jid in [j for j in list(it.get("pod_imgs") or []) + [it.get("pod_img")] if j]:
        try:
            st = pod_studio.job(jid, cfg)
        except Exception:  # noqa: BLE001 — job antigo apagado: segue com os outros
            continue
        for n in st.get("arquivos") or []:
            out[n] = jid
    return out


def faltam_no_pc(lid: str, iid: str) -> int:
    """Quantas cenas do pod ainda não têm a imagem neste PC (-1 se as cenas ainda não foram planejadas)."""
    pasta = pasta_item(lid, iid)
    try:
        with open(os.path.join(pasta, "cenas.json"), encoding="utf-8") as f:
            segs = json.load(f).get("segments") or []
    except (OSError, ValueError):
        return -1
    pasta_img = os.path.join(pasta, "imagens")
    no_pc = set(os.listdir(pasta_img)) if os.path.isdir(pasta_img) else set()
    return sum(1 for k, s in enumerate(segs) if s.get("provider") == "runpod" and f"cena-{k + 1:04d}.png" not in no_pc)


def _reenviar_faltantes(lid: str, iid: str, manual: bool = False, pod_novo: bool = False) -> int:
    """🔁 As imagens que o pod não fez (erro, falta de memória…) vão de novo num job só com elas (com as mesmas fotos
    de referência). Devolve quantas foram. `pod_novo`: o pod é outro (VPS nova) — nada do pod antigo existe lá, então
    vai tudo que não está no PC; sem nada faltando, segue direto pro projeto."""
    import pod_studio
    lote = carregar(lid)
    it = next(x for x in lote["itens"] if x["id"] == iid)
    cfg = _cfg_pod(lote)
    pasta = pasta_item(lid, iid)
    with open(os.path.join(pasta, "cenas.json"), encoding="utf-8") as f:
        resposta = json.load(f)
    try:
        with open(os.path.join(pasta, "rostos.json"), encoding="utf-8") as f:
            rostos = json.load(f)
    except (OSError, ValueError):
        rostos = {}
    prontos = {} if pod_novo else _prontos_no_pod(it, cfg)
    pasta_img = os.path.join(pasta, "imagens")
    no_pc = set(os.listdir(pasta_img)) if os.path.isdir(pasta_img) else set()
    pedidos = []
    for k, s in enumerate(resposta["segments"]):
        nome = f"cena-{k + 1:04d}"
        if s["provider"] == "runpod" and f"{nome}.png" not in prontos and f"{nome}.png" not in no_pc:
            refs = [r for r in rostos.get(str(k)) or [] if os.path.isfile(r[1])]  # foto apagada do PC: vai sem ela
            pedidos.append({"prompt": s["query"], "nome": nome, **({"referencias": refs} if refs else {})})
    if not pedidos:
        if pod_novo:  # nada faltando: o que está no PC basta
            _mudar(lid, iid, estado="pronto" if it.get("job_id") else "montando",
                   _log="✅ todas as imagens já estão no PC" + (" — no editor clique em 🔁 Pôr as imagens do pod de volta"
                                                              if it.get("job_id") else ""))
        elif not manual:
            _receber_imagens(lid, iid)
        return 0
    w, h = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1024, 1024)}[lote["config"]["orientacao"]]
    jid, _sem = pod_studio.enviar_imagens_com_refs(pedidos, largura=w, altura=h, nome=(it["titulo"] + " (de novo)")[:40], cfg=cfg)
    antigos = [] if pod_novo else [j for j in list(it.get("pod_imgs") or []) + [it.get("pod_img")] if j]
    _mudar(lid, iid, estado="imagens", pod_imgs=antigos, pod_img=jid,
           reenvios_img=int(it.get("reenvios_img") or 0) + 1, erro=None, faltam_img=0,
           _log=(f"🔁 {len(pedidos)} imagem(ns) que faltavam foram pro pod novo" if pod_novo
                 else f"🔁 {len(pedidos)} imagem(ns) que o pod não fez foram de novo pra fila"))
    return len(pedidos)


def refazer_imagens(lid: str, iid: str, pod_url: str = "") -> Dict[str, Any]:
    """Botão 🔁 Gerar de novo as que falharam (o pod precisa estar ligado). 🔗 v84_181: com `pod_url` novo, manda pro
    pod novo todas as que não estão no PC."""
    with _TRAVA:
        lote = carregar(lid)
        it = next((x for x in lote["itens"] if x["id"] == iid), None)
        if not it or not os.path.exists(os.path.join(pasta_item(lid, iid), "cenas.json")):
            raise ProducaoErro("Esse roteiro ainda não mandou imagens pro pod.")
        pod_novo = _aplicar_pod_novo(lote, pod_url) or not it.get("pod_img")
        lote["status"] = "rodando"  # senão ninguém acompanha o job novo (o lote já estava concluído)
        salvar(lote)
    n = _reenviar_faltantes(lid, iid, manual=True, pod_novo=pod_novo)
    if not n:
        with _TRAVA:
            lote = carregar(lid)
            if lote.get("status") == "rodando" and all(x["estado"] in ESTADOS_FINAIS for x in lote["itens"]):
                lote["status"] = "concluido"
                salvar(lote)
        raise ProducaoErro("Não falta nenhuma imagem — todas já estão no PC.")
    garantir_runner()
    return {"ok": True, "reenviadas": n}


def _receber_imagens(lid: str, iid: str) -> None:
    import pod_studio
    import runpod_gerador
    lote = carregar(lid)
    it = next(x for x in lote["itens"] if x["id"] == iid)
    cfg = _cfg_pod(lote)
    pasta = pasta_item(lid, iid)
    pasta_img = os.path.join(pasta, "imagens")
    try:
        if not it.get("pod_img"):
            raise ProducaoErro("sem job de imagens neste pod")
        pod_studio.job(it["pod_img"], cfg)
        donos = _prontos_no_pod(it, cfg)
    except Exception:
        # pod desligado: usa só as imagens que já estão no PC
        if not (os.path.isdir(pasta_img) and os.listdir(pasta_img)):
            raise
        donos = {}
    if os.path.isdir(pasta_img):
        for n in os.listdir(pasta_img):
            if n.endswith(".png"):
                donos.setdefault(n, "")
    with open(os.path.join(pasta, "cenas.json"), encoding="utf-8") as f:
        resposta = json.load(f)
    prontos = set(donos)
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
            local = pod_studio.baixar(donos.get(nome) or it["pod_img"], nome, local, cfg)
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
    msg = f"🖼 {feitas} imagens prontas" + (f" ({faltaram} falharam no pod — 🔁 dá pra gerar de novo no lote, ou o editor tenta)" if faltaram else "")
    if faltaram:
        _mudar(lid, iid, faltam_img=faltaram)
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
