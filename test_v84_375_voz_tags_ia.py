"""v84_375: 🤖🎭 o Claude coloca as tags de emoção (expressivo pt e Turbo en) sem mudar o texto."""
import time

import voz_tags_ia as V


def _fake(resposta):
    vistos = []

    def chamar(recurso, system, conteudo, **kw):
        vistos.append((recurso, system, conteudo, kw))
        return {"texto": resposta(conteudo) if callable(resposta) else resposta}
    return chamar, vistos


def test_aceita_so_tags_e_recusa_palavra_mudada():
    orig = "Ele abriu a porta. Não havia ninguém.\n\nE então ouviu um grito."
    bom = "[suspense] Ele abriu a porta. [pausa] Não havia *ninguém*.\n\n[respira] E então ouviu um grito."
    assert V.mesmo_texto(orig, bom, "pt")
    assert not V.mesmo_texto(orig, bom.replace("grito", "berro"), "pt")
    assert V.mesmo_texto("He laughed. Funny.", "He laughed. [chuckle] [happy] Funny.", "en")


def test_aplicar_pt_com_ia_falsa():
    chamar, vistos = _fake(lambda t: "[plena] " + t.replace("ninguém", "*ninguém*"))
    novo, info = V.aplicar("Não havia ninguém ali.", "pt", chamar=chamar)
    assert novo == "[plena] Não havia *ninguém* ali." and info["ok"] == 1
    rec, system, _, kw = vistos[0]
    assert rec == "voz_tags" and "[soprosa]" in system and "NUNCA troque" in system and kw["schema"] == V.SCHEMA


def test_pedaco_estragado_fica_original():
    V.MAX_CHARS_POR_PEDIDO, antigo = 40, V.MAX_CHARS_POR_PEDIDO
    try:
        texto = "Primeiro parágrafo bem curto aqui.\n\nSegundo parágrafo também curto aqui."
        chamar, vistos = _fake(lambda t: ("[calma] " + t) if t.startswith("Primeiro") else "[calma] Texto trocado.")
        avisos = []
        novo, info = V.aplicar(texto, "pt", chamar=chamar, on_log=avisos.append)
        assert len(vistos) == 2 and info == {"pedacos": 2, "ok": 1, "recusados": 1, "sem_ia": 0}
        assert novo == "[calma] Primeiro parágrafo bem curto aqui.\n\nSegundo parágrafo também curto aqui." and avisos
    finally:
        V.MAX_CHARS_POR_PEDIDO = antigo


def test_instrucoes_pt_pt_e_en():
    assert "[fungadela]" in V.sistema("pt", "pt-PT") and "português de Portugal" in V.sistema("pt", "pt-PT")
    s = V.sistema("en")
    assert "[whispering]" in s and "[clear throat]" in s and "ABSOLUTE RULES" in s


def test_tem_tags():
    assert V.tem_tags("Oi [risada] tudo", "pt") and not V.tem_tags("Oi tudo", "pt")
    assert V.tem_tags("Hi [laugh] there", "en") and not V.tem_tags("Hi [nota] there", "en")


def test_endpoint(monkeypatch):
    import app as A
    monkeypatch.setattr(V, "motivo_sem_ia", lambda: None)
    monkeypatch.setattr(V, "aplicar", lambda t, m, v, on_log=None: ("[plena] " + t, {"ok": 1, "pedacos": 1, "recusados": 0, "sem_ia": 0}))
    c = A.app.test_client()
    d = c.post("/gerar-voz/ia-tags", json={"texto": "Olá a todos.", "modo": "pt"}).get_json()
    assert d["texto"] == "[plena] Olá a todos."
    monkeypatch.setattr(V, "motivo_sem_ia", lambda: "falta a chave da API")
    r = c.post("/gerar-voz/ia-tags", json={"texto": "Olá.", "modo": "pt"})
    assert r.status_code == 400 and "chave" in r.get_json()["erro"]
    g = c.get("/gerar-voz").get_data(as_text=True)
    assert 'name="chatterbox_ia_tags"' in g and 'name="turbo_ia_tags"' in g


def test_ao_gerar_coloca_as_tags_e_legenda_fica_sem(monkeypatch):
    import app as A
    monkeypatch.setattr(V, "motivo_sem_ia", lambda: None)
    monkeypatch.setattr(V, "aplicar", lambda t, m, v, on_log=None: ("[dramatica] " + t, {"ok": 1, "pedacos": 1, "recusados": 0, "sem_ia": 0}))
    recebido = {}

    def falso(engine, texto, saida, **kw):
        recebido.update(texto=texto, kw=kw)
        open(saida, "wb").write(b"RIFF")
        return saida
    monkeypatch.setattr(A, "tts_gerar_audio_isolado", falso)
    c = A.app.test_client()
    r = c.post("/gerar-voz/gerar", data={"engine": "chatterbox", "texto": "Ninguém imaginava o que viria depois.",
                                         "chatterbox_idioma": "pt", "chatterbox_expressivo": "on", "chatterbox_ia_tags": "on"})
    jid = r.get_json()["job_id"]
    for _ in range(100):
        if recebido:
            break
        time.sleep(0.05)
    assert recebido["texto"] == "[dramatica] Ninguém imaginava o que viria depois."
    for _ in range(100):
        if not A._GERAR_VOZ_STATUS[jid]["running"]:
            break
        time.sleep(0.05)
    assert "O Claude está colocando as tags" in A._GERAR_VOZ_STATUS[jid]["log"]


def test_sem_a_opcao_nao_chama_a_ia(monkeypatch):
    import app as A
    chamou = []
    monkeypatch.setattr(V, "aplicar", lambda *a, **k: chamou.append(1))
    recebido = {}
    monkeypatch.setattr(A, "tts_gerar_audio_isolado", lambda e, t, s, **kw: recebido.update(texto=t) or open(s, "wb").write(b"RIFF") or s)
    c = A.app.test_client()
    c.post("/gerar-voz/gerar", data={"engine": "chatterbox", "texto": "Texto normal sem nada de tag aqui.",
                                     "chatterbox_idioma": "pt", "chatterbox_expressivo": "on"})
    for _ in range(100):
        if recebido:
            break
        time.sleep(0.05)
    assert not chamou and recebido["texto"] == "Texto normal sem nada de tag aqui."
