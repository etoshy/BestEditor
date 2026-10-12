"""v84_65 — 🎙 Gerador de voz: fila, 2 ao mesmo tempo quando a VRAM deixa, e histórico dos áudios."""
import os
import threading
import time

import pytest

import fila_voz as fv
import historico_voz as hv


def _tarefa(log, nome, dur=0.15):
    def _f():
        log.append(("ini", nome, time.time()))
        time.sleep(dur)
        log.append(("fim", nome, time.time()))
    return _f


def _max_juntos(log):
    n = m = 0
    for ev, _nome, _t in sorted(log, key=lambda x: (x[2], x[0] == "ini")):
        n += 1 if ev == "ini" else -1
        m = max(m, n)
    return m


def test_sem_placa_um_por_vez_na_ordem():
    f = fv.Fila(modo_fn=lambda: "auto", vram_fn=lambda: None)
    log = []
    for k in range(3):
        f.iniciar(f"j{k}", "xtts", _tarefa(log, k))
    assert f.esperar_vazia()
    assert [n for e, n, _ in log if e == "ini"] == [0, 1, 2] and _max_juntos(log) == 1


def test_com_vram_dois_ao_mesmo_tempo():
    f = fv.Fila(modo_fn=lambda: "auto", vram_fn=lambda: {"nome": "RTX", "total": 12.0, "livre": 11.0})
    log = []
    for k in range(4):
        f.iniciar(f"j{k}", "xtts", _tarefa(log, k))
    assert f.esperar_vazia()
    assert _max_juntos(log) == 2  # 2 × 3,5 GB cabem em 12 GB; o auto não passa de 2


def test_vram_pouca_nao_junta_motor_pesado():
    f = fv.Fila(modo_fn=lambda: "auto", vram_fn=lambda: {"nome": "GTX", "total": 6.0, "livre": 5.5})
    log = []
    for k in range(3):
        f.iniciar(f"c{k}", "chatterbox", _tarefa(log, k))  # 5 GB cada
    assert f.esperar_vazia()
    assert _max_juntos(log) == 1
    log2 = []
    for k in range(2):
        f.iniciar(f"k{k}", "kokoro", _tarefa(log2, k))  # 1 GB cada: cabem 2
    assert f.esperar_vazia()
    assert _max_juntos(log2) == 2


def test_modo_fixo_e_cancelar():
    f = fv.Fila(modo_fn=lambda: "1", vram_fn=lambda: {"nome": "RTX", "total": 24.0, "livre": 23.0})
    log, mudou = [], []
    f.ao_mudar = lambda jid, info: mudou.append((jid, info))
    trava = threading.Event()
    f.iniciar("a", "piper", lambda: trava.wait(2))
    f.iniciar("b", "piper", _tarefa(log, "b"))
    f.iniciar("c", "piper", _tarefa(log, "c"))
    time.sleep(0.2)
    assert f.posicao("b") == 1 and f.posicao("c") == 2 and f.limite() == 1
    assert f.cancelar("c") and not f.cancelar("a")
    trava.set()
    assert f.esperar_vazia()
    assert [n for e, n, _ in log if e == "ini"] == ["b"]
    assert ("b", {"posicao": None, "iniciou": pytest.approx(time.time(), abs=5)}) in [(j, i) for j, i in mudou if "iniciou" in i]


def test_historico(tmp_path):
    p = str(tmp_path)
    open(os.path.join(p, "a1.wav"), "wb").write(b"RIFF")
    open(os.path.join(p, "a1.srt"), "w").write("1\n")
    st = {"engine": "xtts", "criado_em": 100.0, "iniciou_em": 110.0, "texto_inicio": "Era uma vez", "palavras": 3,
          "resultado_filename": "a1.wav", "resultado_srt_filename": "a1.srt", "idioma": "pt", "voz": "minha_voz"}
    e = hv.registrar(p, "a1", st)
    assert e["levou"] > 0 and e["bytes"] == 4 and e["voz"] == "minha_voz"
    hv.registrar(p, "a2", dict(st, resultado_filename=None, erro="falhou", texto_inicio="Outro texto"))
    r = hv.listar(p)
    assert r["total"] == 2 and r["itens"][0]["id"] == "a2"
    assert hv.listar(p, q="era uma")["total"] == 1
    assert hv.apagar(p, "a1") and not os.path.exists(os.path.join(p, "a1.wav")) and not os.path.exists(os.path.join(p, "a1.srt"))
    assert not hv.apagar(p, "a1") and hv.listar(p)["total"] == 1


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_rotas_da_fila_e_do_historico(A, monkeypatch, tmp_path):
    monkeypatch.setattr(A, "VOZES_DIR", str(tmp_path))
    monkeypatch.setattr(A._FILA_VOZ, "vram_fn", lambda: None)
    monkeypatch.setattr(A._FILA_VOZ, "_vram_cache", {"quando": 0.0, "v": None})
    monkeypatch.setattr(A._FILA_VOZ, "modo_fn", lambda: "1")
    trava = threading.Event()
    feitos = []

    def _fake(job_id, engine, texto, output_path, kwargs, *a, **k):
        st = A._GERAR_VOZ_STATUS[job_id]
        if texto.startswith("primeiro"):
            trava.wait(3)
        open(output_path, "wb").write(b"RIFFxxxx")
        st["resultado_filename"] = os.path.basename(output_path)
        st["running"], st["pronto"] = False, True
        A._hist_voz.registrar(str(tmp_path), job_id, st)
        feitos.append(texto)
    monkeypatch.setattr(A, "_gerar_voz_em_background", _fake)
    c = A.app.test_client()
    j1 = c.post("/gerar-voz/gerar", data={"texto": "primeiro áudio", "engine": "piper"}).get_json()
    j2 = c.post("/gerar-voz/gerar", data={"texto": "segundo áudio", "engine": "piper"}).get_json()
    j3 = c.post("/gerar-voz/gerar", data={"texto": "terceiro áudio", "engine": "piper"}).get_json()
    time.sleep(0.2)
    s2 = c.get(f"/gerar-voz/status/{j2['job_id']}").get_json()
    assert s2["na_fila"] and s2["posicao"] == 1 and "Na fila" in s2["log"]
    em = c.get("/gerar-voz/em-andamento").get_json()
    assert em["fila"]["limite"] == 1 and len(em["fila"]["fila"]) == 2
    assert c.post(f"/gerar-voz/cancelar/{j3['job_id']}").get_json()["ok"]
    assert c.post(f"/gerar-voz/cancelar/{j1['job_id']}").status_code == 400  # já está gerando
    trava.set()
    assert A._FILA_VOZ.esperar_vazia(5)
    assert feitos == ["primeiro áudio", "segundo áudio"]
    h = c.get("/gerar-voz/historico").get_json()
    assert h["total"] == 2 and h["itens"][0]["audio_url"].endswith(".wav")
    assert c.post(f"/gerar-voz/historico/{j1['job_id']}/apagar").get_json()["ok"]
    assert c.get("/gerar-voz/historico").get_json()["total"] == 1
    assert c.post("/gerar-voz/fila/config", json={"modo": "9"}).status_code == 400
    html = c.get("/gerar-voz").get_data(as_text=True)
    assert 'id="fila-modo"' in html and "Histórico de áudios gerados" in html


# ------------------------------------------------------------------ estilos de vídeo de IA (colagem de papel)
def test_estilos_novos_de_videos_modelados():
    import modelados as md
    ids = [e["id"] for e in md.listar_estilos()]
    assert ids[:3] == ["kamishibai", "dossie_colagem", "arquivo_mesa"]
    e = md.obter_estilo("dossie_colagem")
    assert "{cena}" in e["prompt_imagem"] and "{ar}" in e["prompt_imagem"] and "{movimento}" in e["prompt_animacao"]
    assert "No capítulo anterior" in e["instrucoes_roteiro"] and "nunca peça o rosto realista" in e["instrucoes_roteiro"]
    assert e["formato"] == "9:16" and e["direcao"] == "sys_dossie_papel"
    import dp_direcao
    d = dp_direcao.direcao("sys_dossie_papel")
    assert d and d["destaques"]["estilos"] and d["transicoes"]["itens"]
