"""v84_425 — aba Economia de IA: interruptores, recomendado, voltar e testar tudo."""
import ia_economia as ie
import ia_local as il


def _isolar(monkeypatch, tmp_path):
    import ia_servico as ia
    monkeypatch.setattr(ia, "CONFIG_PATH", str(tmp_path / "ia_config.json"))
    return ia


def test_padrao_ja_vem_com_o_recomendado(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    monkeypatch.delenv("BESTEDITOR_IA_SO_API", raising=False)
    c = ia.config()
    assert c["texto_via"] == "claude" and c["local"]["ativo"] and "buscas" in c["local"]["recursos"]


def test_salvar_recomendado_e_voltar(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    monkeypatch.setattr(il, "listar_modelos", lambda c=None, url="": ["qwen3:8b", "qwen2.5vl:7b"])
    ie.voltar()
    assert ia.config()["texto_via"] == "api" and not ia.config()["local"]["ativo"]
    e = ie.recomendado()
    assert e["texto_via"] == "claude" and e["local"]["ativo"]
    assert e["local"]["modelo"] == "qwen3:8b" and e["local"]["modelo_visao"] == "qwen2.5vl:7b" and e["juiz_modo"] == "off"
    assert ia.config()["antes_economia"]["texto_via"] == "api"
    ie.salvar({"local": {"recursos": ["buscas"]}})
    assert ia.config()["local"]["recursos"] == ["buscas"] and ia.config()["local"]["modelo"] == "qwen3:8b"


def test_testar_tudo_sem_nada_instalado_mostra_os_passos(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    import ia_assinatura as ias
    monkeypatch.setattr(ias, "executavel", lambda modo: None)
    monkeypatch.setattr(il, "listar_modelos", lambda c=None, url="": [])
    monkeypatch.setattr(ia, "chave", lambda c=None: "")
    ie.salvar({"texto_via": "claude", "local": {"ativo": True}})
    itens = ie.testar_tudo()
    por = {x["nome"]: x for x in itens}
    assert por["🟠 Assinatura do Claude (Claude Code)"]["ok"] is False and por["🟠 Assinatura do Claude (Claude Code)"]["instrucao"] == "claude"
    assert por["🖥 IA local — servidor"]["ok"] is False and por["🖥 IA local — servidor"]["instrucao"] == "local"
    assert "nodejs.org" in " ".join(ie.INSTRUCOES["claude"]["passos"]) and "ollama pull" in " ".join(ie.INSTRUCOES["local"]["passos"])


def test_testar_tudo_com_qwen(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    import ia_assinatura as ias
    monkeypatch.setattr(ias, "executavel", lambda modo: None)
    monkeypatch.setattr(ia, "chave", lambda c=None: "")
    monkeypatch.setattr(il, "listar_modelos", lambda c=None, url="": ["qwen2.5:7b", "qwen2.5vl:7b"])
    ie.salvar({"local": {"ativo": True, "modelo": "qwen2.5:7b", "modelo_visao": "qwen2.5vl:7b"}})
    monkeypatch.setattr(il, "chamar", lambda m, s, cont, schema, **k: {"cor": "vermelho"} if isinstance(cont, list) else {"ok": True})
    por = {x["nome"]: x for x in ie.testar_tudo()}
    assert por["🖥 IA local — modelo de texto (buscas)"]["ok"] and por["🖥 IA local — modelo com visão (juiz das cenas)"]["ok"]


def test_local_fora_do_ar_pausa_e_nao_atrasa(monkeypatch):
    il._FALHA.update(ate=0, avisado=0)
    assert il.marcar_falha(il.LocalErro("a IA local não respondeu em http://x (refused)")) is True
    assert il.fora_do_ar()
    assert il.marcar_falha(il.LocalErro("a IA local não respondeu em http://x")) is False  # não enche o log
    il._FALHA.update(ate=0, avisado=0)


def test_pagina(monkeypatch):
    import re
    import subprocess
    import app as A
    h = A.app.test_client().get("/ia/economia").get_data(as_text=True)
    assert "ecTestar" in h and "Voltar como era antes" in h and "Aplicar o recomendado" in h
    sc = [x for x in re.findall(r"<script>(.*?)</script>", h, re.S) if "ecTestar" in x][0]
    import tempfile, os
    f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
    f.write(sc); f.close()
    try:
        r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.remove(f.name)


def test_juiz_tres_modos(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    import ia_economia as ie2
    ie2.salvar({"local": {"ativo": True, "modelo_visao": "qwen2.5vl:7b"}})
    e = ie2.salvar({"juiz_modo": "off"})
    assert e["juiz_modo"] == "off" and not ia.config()["recursos"]["juiz"]
    e = ie2.salvar({"juiz_modo": "local"})
    assert e["juiz_modo"] == "local" and "juiz" in ia.config()["local"]["so_local"] and ia.config()["recursos"]["juiz"]
    # só local: o Qwen falhou → NÃO cai na API
    api = []
    monkeypatch.setattr(ia, "_transporte", lambda p, k, t: (api.append(1) or 200, {"content": [{"type": "text", "text": "API"}], "usage": {}}))
    monkeypatch.setattr(ia, "_registrar", lambda *a, **k: None)
    monkeypatch.setattr(ia, "chave", lambda c=None: "sk-ant-x")
    monkeypatch.setattr(il, "chamar", lambda *a, **k: (_ for _ in ()).throw(il.LocalErro("travou")))
    ia.salvar_config({"ativo": True})
    img = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "A"}}, {"type": "text", "text": "x"}]
    assert ia.chamar("juiz", "s", img, cache_local=False) is None and not api
    e = ie2.salvar({"juiz_modo": "api"})
    assert e["juiz_modo"] == "api" and ia.chamar("juiz", "s", img, cache_local=False) == "API"


def test_juiz_fica_desligado_no_recomendado_e_no_voltar(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    monkeypatch.delenv("BESTEDITOR_IA_SO_API", raising=False)
    assert ia.config()["recursos"]["juiz"] is False  # padrão novo: desligado
    monkeypatch.setattr(il, "listar_modelos", lambda c=None, url="": ["qwen2.5:7b", "qwen2.5vl:7b"])
    assert ie.recomendado()["juiz_modo"] == "off"
    ie.salvar({"juiz_modo": "api"})
    assert ie.voltar()["juiz_modo"] == "off"


def test_sem_juiz_continua_sem_repetir_clipe(monkeypatch):
    """O juiz desligado (ou o Qwen falhou): a prévia fica com o melhor resultado AINDA NÃO usado (e no máximo 3x)."""
    import video_assembler as va
    from test_flow_e_nao_repetir import _FabricaFalsa, _Res, _previa
    monkeypatch.setattr(va, "julgar_candidatos_ia", lambda *a, **k: None)  # o Qwen não respondeu
    fabrica = _FabricaFalsa([_Res("a"), _Res("b"), _Res("c")])
    t = va.UsedClipsTracker(3)
    vistos = [_previa("pexels", fabrica, t)["thumbnail_url"] for _ in range(3)]
    assert vistos == ["http://t/a.jpg", "http://t/b.jpg", "http://t/c.jpg"]


def test_migrar_uma_vez(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    monkeypatch.delenv("BESTEDITOR_IA_SO_API", raising=False)
    monkeypatch.setattr(il, "listar_modelos", lambda c=None, url="": [])
    ia.salvar_config({"texto_via": "api", "recursos": {"juiz": True}})
    assert ie.migrar_uma_vez() is True
    c = ia.config()
    assert c["texto_via"] == "claude" and not c["recursos"]["juiz"] and c["economia_aplicada"]
    ie.voltar()
    assert ie.migrar_uma_vez() is False and ia.config()["texto_via"] == "api"  # não volta a mexer
