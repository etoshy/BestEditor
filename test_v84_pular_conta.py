"""v84_110 — ⏭ conta que pede login (ou falha seguido) é PULADA e o pedido vai pra outra; e no vídeo do site: contas do
Flow sem crédito de vídeo → foto; sem crédito nenhum → PESQUISA a cena (bancos de vídeo / buscadores de imagem)."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from test_v84_flow_lote import ctx, _esperar_fim  # noqa: E402,F401


def test_pular_conta_sai_da_troca_e_volta(ctx):
    c, FL, FE, gf, tmp = ctx
    gf.despular_conta(None)
    try:
        gf.pular_conta("principal", "pediu login")
        assert not gf.conta_serve("principal", "video") and gf.conta_serve("reserva", "video")
        assert gf.escolher_conta_disponivel(tipo="imagem") == "reserva"
        info = {x["nome"]: x for x in gf.listar_contas()}
        assert info["principal"]["pulada"] == "pediu login" and info["reserva"]["pulada"] is None
        gf.pular_conta("reserva", "não abriu")
        with pytest.raises(gf.GoogleFlowSemContas) as e:
            gf.escolher_conta_disponivel(tipo="imagem")
        assert "foi pulada" in str(e.value) and "login" in str(e.value)
        gf.liberar_conta("principal")  # ♻ liberar também despula
        assert gf.conta_serve("principal", "imagem")
        gf.pular_conta("reserva", "x", minutos=-1)  # passou o tempo: volta sozinha
        assert gf.conta_serve("reserva", "imagem")
        assert gf.RE_PROBLEMA_DE_LOGIN.search("Faça login pra continuar") and not gf.RE_PROBLEMA_DE_LOGIN.search("timeout")
    finally:
        gf.despular_conta(None)


def test_lote_pula_conta_com_login_e_conta_que_falha(ctx, monkeypatch):
    """'principal' pede login; 'reserva' gera tudo. Nenhum pedido fica com erro por culpa da conta."""
    c, FL, FE, gf, tmp = ctx
    from googleflow import flow_direto as fd
    gf.despular_conta(None)

    class _Ctx:
        pages = []

        def close(self):
            pass

    class _Page:
        url = "https://flow/proj"

        def is_closed(self):
            return False

        def close(self):
            pass
    abriu = []
    monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": abriu.append(conta) or (_Ctx(), True))

    feitos = []

    def gerar_um(page, trab, on_passo, timeout):
        conta = FL.threading.current_thread().name.replace("flow-lote-", "")
        if conta == "principal":
            raise fd.FlowLogin("abrir", "o Flow pediu login (accounts.google.com)")
        feitos.append((conta, trab["prompt"]))
        return [{"id": "m", "url": "https://x/image/m", "tipo": "imagem"}]
    monkeypatch.setattr(fd, "preparar_projeto", lambda *a, **k: _Page())
    monkeypatch.setattr(fd, "gerar_um", gerar_um)
    monkeypatch.setattr(FL, "baixar_para_galeria", lambda ctx_, midias, job, conta, projeto="": [
        {"id": job["id"], "arquivo": job["id"] + ".png", "tipo": "imagem"}])
    FL.lote().salvar_config({"paralelo": 2, "cooldown_min": 0.05, "cooldown_max": 0.1})
    c.post("/flow/lote/fila", json={"texto": "a\nb\nc\nd", "tipo": "imagem", "iniciar": True})
    d = _esperar_fim(FL, 60)
    try:
        assert d["contagem"]["ok"] == 4 and d["contagem"]["erro"] == 0, d["log"]
        assert {x for x, _ in feitos} == {"reserva"}
        contas = {x["nome"]: x for x in d["contas"]}
        assert "login" in contas["principal"]["problema"] and gf.conta_pulada("principal")
        assert any("⏭ Pulando a conta “principal”" in l["msg"] for l in d["log"])
        # ✔ concluiu o login na mão → volta
        FL.lote()._fim_manual("principal")
        assert gf.conta_pulada("principal") is None
    finally:
        gf.despular_conta(None)


def test_lote_conta_que_nao_abre_o_projeto_e_pulada_sem_estragar_o_pedido(ctx, monkeypatch):
    c, FL, FE, gf, tmp = ctx
    from googleflow import flow_direto as fd
    gf.despular_conta(None)

    class _Ctx:
        pages = []

        def close(self):
            pass

    class _Page:
        url = "https://flow/proj"

        def is_closed(self):
            return False

        def close(self):
            pass
    monkeypatch.setattr(gf, "_abrir", lambda p, cfg, headless, conta="x": (_Ctx(), True))

    def preparar(*a, **k):
        if FL.threading.current_thread().name == "flow-lote-principal":
            raise RuntimeError("não achei o botão Novo projeto")
        return _Page()
    monkeypatch.setattr(fd, "preparar_projeto", preparar)
    monkeypatch.setattr(fd, "gerar_um", lambda page, trab, on_passo, timeout: [{"id": "m", "url": "https://x/m", "tipo": "imagem"}])
    monkeypatch.setattr(FL, "baixar_para_galeria", lambda ctx_, midias, job, conta, projeto="": [
        {"id": job["id"], "arquivo": job["id"] + ".png", "tipo": "imagem"}])
    FL.lote().salvar_config({"paralelo": 2, "cooldown_min": 0.05, "cooldown_max": 0.1, "tentativas": 1})
    c.post("/flow/lote/fila", json={"texto": "a\nb\nc", "tipo": "imagem", "iniciar": True})
    d = _esperar_fim(FL, 60)
    try:
        assert d["contagem"]["ok"] == 3 and d["contagem"]["erro"] == 0, d["log"]
        assert all(j["conta"] == "reserva" for j in d["fila"])
        assert gf.conta_pulada("principal") and "não abriu o projeto" in gf.conta_pulada("principal")["motivo"]
    finally:
        gf.despular_conta(None)


# ------------------------------------------------------------------ vídeo do site: Flow esgotado → foto → pesquisa
def test_flow_tem_conta(monkeypatch):
    import video_assembler as va
    from googleflow import googleflow_client as gf
    monkeypatch.setattr(gf, "escolher_conta_disponivel", lambda tipo=None: "principal")
    assert va.flow_tem_conta("video", {}) is True
    assert va.flow_tem_conta("video", {"flow_navegador": "cdp"}) is None

    def sem(tipo=None):
        raise gf.GoogleFlowSemContas("todas esgotadas")
    monkeypatch.setattr(gf, "escolher_conta_disponivel", sem)
    assert va.flow_tem_conta("imagem", {}) is False


def test_pesquisa_no_lugar_do_flow(monkeypatch, tmp_path):
    import video_assembler as va
    from prompt_builder import VideoSegment
    seg = VideoSegment(start=0, end=4, provider="flow", query="A lonely lighthouse on a cliff during a violent storm at night",
                       media_type="video", alternativas=["lighthouse storm"])
    chamadas = []

    def videos(segment, downloads_dir, factory, prioridade, orientation, **k):
        chamadas.append(("video", segment.provider, segment.query, list(prioridade)))
        raise va.VideoAssemblyError("nada no banco")
    monkeypatch.setattr(va, "_download_segment_with_fallbacks", videos)
    monkeypatch.setattr(va, "prefetch_browser_images", lambda items, d, cfg, **k: chamadas.append(
        ("imagem", items[0][1].provider, items[0][1].query)) or {0: {"ok": True, "path": str(tmp_path / "a.jpg")}})
    paths, kind = va._pesquisa_no_lugar_do_flow(seg, str(tmp_path), None, {"sites_bloqueados": []},
                                                ["pexels", "flow", "youtube", "bing", "pixabay"], None, video=True)
    assert kind == "image" and paths == [str(tmp_path / "a.jpg")]
    assert chamadas[0] == ("video", "pexels", "lighthouse storm", ["pexels", "pixabay"])
    assert chamadas[1] == ("imagem", "bing", "lighthouse storm")
    # sem alternativa: o núcleo da descrição
    seg2 = VideoSegment(start=0, end=4, provider="flow", query="A lonely lighthouse on a cliff at night", media_type="image")
    assert va._termo_de_pesquisa(seg2) == "lonely lighthouse cliff" or len(va._termo_de_pesquisa(seg2).split()) <= 6
    monkeypatch.setattr(va, "prefetch_browser_images", lambda *a, **k: {0: {"ok": False, "erro": "nada"}})
    monkeypatch.setattr(va, "_download_image_segment_with_fallbacks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem chave")))
    with pytest.raises(va.VideoAssemblyError) as e:
        va._pesquisa_no_lugar_do_flow(seg2, str(tmp_path), None, {}, ["bing", "pexels"], None, motivo="todas as contas sem crédito")
    assert "todas as contas sem crédito" in str(e.value) and "bing" in str(e.value) and "pexels (fotos)" in str(e.value)


def test_pesquisa_so_nos_mecanismos_marcados_e_foto_primeiro_pro_trecho_de_foto(monkeypatch, tmp_path):
    import video_assembler as va
    from prompt_builder import VideoSegment
    seg = VideoSegment(start=0, end=4, provider="flow", query="old map on a desk", media_type="image")
    ordem = []
    monkeypatch.setattr(va, "prefetch_browser_images", lambda items, d, cfg, **k: ordem.append(("buscador", items[0][1].provider))
                        or {0: {"ok": False, "erro": "nada"}})
    monkeypatch.setattr(va, "_download_image_segment_with_fallbacks", lambda segment, *a, **k: ordem.append(("foto", segment.provider))
                        or (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(va, "_download_segment_with_fallbacks", lambda segment, d, f, prio, o, **k: ordem.append(("video", tuple(prio)))
                        or ["v.mp4"])
    # marcou só yandex + pixabay pra este vídeo (a prioridade das Configurações tem mais coisa)
    cfg = {"_providers_marcados": ["yandex", "pixabay", "flow"], "sites_bloqueados": []}
    paths, kind = va._pesquisa_no_lugar_do_flow(seg, str(tmp_path), None, cfg, ["pexels", "bing", "pixabay", "yandex"], None)
    assert (paths, kind) == (["v.mp4"], "video")
    assert ordem == [("buscador", "yandex"), ("video", ("pixabay",))]  # foto primeiro; pixabay não tem fotos; vídeo por último


def test_prompt_de_video_vira_prompt_de_foto(monkeypatch):
    import video_assembler as va
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    p = va.prompt_de_foto("Slow push-in on a lighthouse in a storm, 8 seconds")
    assert "push-in" not in p.lower() and "8 seconds" not in p and "lighthouse" in p
