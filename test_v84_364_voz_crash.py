"""v84_364: 🎙 motor de voz travou (crash nativo 3221225477) com 2 juntas → a fila passa a 1 de cada vez e tenta de novo."""
import threading
import time

import fila_voz as FV


def test_crash_com_duas_juntas_vira_um_por_vez():
    f = FV.Fila(modo_fn=lambda: "auto", vram_fn=lambda: {"nome": "RTX 3060", "total": 12.0, "livre": 11.0})
    assert f.limite() == 2
    libera = threading.Event()
    rodando = []

    def trabalho(nome):
        def fn():
            rodando.append(nome)
            libera.wait(5)
        return fn
    f.iniciar("a", "chatterbox_turbo", trabalho("a"))
    f.iniciar("b", "chatterbox_turbo", trabalho("b"))
    t0 = time.time()
    while len(rodando) < 2 and time.time() - t0 < 3:
        time.sleep(0.02)
    assert len(rodando) == 2  # 2 juntas na placa
    assert f.marcar_crash() is True and f.limite() == 1 and f.estado()["um_por_vez"]
    sozinho = {}
    th = threading.Thread(target=lambda: sozinho.__setitem__("ok", f.esperar_sozinho("a", timeout=5)))
    th.start()
    time.sleep(0.2)
    assert "ok" not in sozinho  # ainda tem o "b" junto
    libera.set()
    th.join(6)
    assert f.esperar_vazia(5)
    assert f.marcar_crash() is False  # sozinho: não muda nada


def test_um_fixo_continua_valendo():
    f = FV.Fila(modo_fn=lambda: "2", vram_fn=lambda: None)
    f.um_por_vez = True
    assert f.limite() == 2  # a escolha da pessoa manda


def test_app_tenta_de_novo_uma_vez(monkeypatch):
    import app as A
    chamadas = []

    def falso(job_id, *a):
        chamadas.append(job_id)
        st = A._GERAR_VOZ_STATUS[job_id]
        st.update(running=False, pronto=True,
                  erro="O motor de voz travou o processo (código de saída 3221225477: acesso inválido à memória)" if len(chamadas) == 1 else None)
    monkeypatch.setattr(A, "_gerar_voz_em_background", falso)
    monkeypatch.setattr(A, "_avisar_fim", lambda *a, **k: None)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    A._GERAR_VOZ_STATUS["jtest"] = {"running": True, "log": "", "erro": None, "pronto": False, "texto_inicio": "x"}
    A._gerar_voz_e_avisar("jtest", "chatterbox_turbo", "texto", "/tmp/x.wav", {}, {}, False)
    st = A._GERAR_VOZ_STATUS.pop("jtest")
    assert len(chamadas) == 2 and st["erro"] is None and st["tentou_de_novo"] and "tentando de novo" in st["log"]
