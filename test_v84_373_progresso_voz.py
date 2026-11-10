"""v84_373: 📊 barra de % real no Gerador de voz (trecho N de M gravado pelo motor)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import voice_generator as vg  # noqa: E402


def test_motor_grava_trechos_e_tira_a_chave_antes_do_motor(tmp_path, monkeypatch):
    arq = tmp_path / "p.json"
    vistos = []

    def falso(texto, saida, **kw):
        assert "progresso_arquivo" not in kw  # o motor nunca recebe a chave
        for i in range(3):
            vg.informar_progresso(i, 3, "gerando", interno=True)
            vistos.append(json.loads(arq.read_text())["feito"])
        vg.informar_progresso(3, 3, "gerando", interno=True)
        open(saida, "wb").close()
        return saida
    monkeypatch.setattr(vg, "chatterbox_synthesize", falso)
    monkeypatch.setitem(vg._PROGRESSO, "arq", None)
    vg.gerar_audio("chatterbox", "Olá, mundo.", str(tmp_path / "a.wav"), progresso_arquivo=str(arq))
    assert vistos == [0, 1, 2] and json.loads(arq.read_text())["total"] == 3


def test_expressivo_conta_os_proprios_trechos(tmp_path, monkeypatch):
    monkeypatch.setitem(vg._PROGRESSO, "arq", str(tmp_path / "p.json"))
    monkeypatch.setitem(vg._PROGRESSO, "silenciar_trechos", True)
    vg.informar_progresso(5, 9, interno=True)  # pedaço interno: ignorado
    assert not (tmp_path / "p.json").exists()
    vg.informar_progresso(2, 9)
    assert json.loads((tmp_path / "p.json").read_text())["feito"] == 2


def test_porcentagem_com_tempo_estimado(tmp_path):
    import app as A
    arq = tmp_path / "p.json"
    st = {"running": True, "progresso_arquivo": str(arq)}
    assert A._progresso_voz(st)["texto"].startswith("⏳ carregando")
    agora = time.time()
    arq.write_text(json.dumps({"feito": 0, "total": 10, "etapa": "gerando", "t": agora - 20}))
    p = A._progresso_voz(st)
    assert p["pct"] == 0 and "trecho 1 de 10" in p["texto"]
    arq.write_text(json.dumps({"feito": 4, "total": 10, "etapa": "gerando", "t": agora - 2}))  # 4 em 18 s = 4,5 s cada
    p = A._progresso_voz(st)
    assert 36 <= p["pct"] <= 40 and "trecho 5 de 10" in p["texto"] and "faltam" in p["texto"]
    arq.write_text(json.dumps({"feito": 10, "total": 10, "etapa": "montando", "t": agora}))
    assert A._progresso_voz(st)["pct"] == 90
    st["fase"] = "legenda"
    assert A._progresso_voz(st)["pct"] == 95
    assert A._progresso_voz({"running": False}) is None


def test_rota_manda_o_arquivo_de_progresso(monkeypatch):
    import app as A
    recebido = {}

    def falso(engine, texto, saida, **kw):
        recebido.update(kw)
        open(saida, "wb").write(b"RIFF")
        return saida
    monkeypatch.setattr(A, "tts_gerar_audio_isolado", falso)
    c = A.app.test_client()
    r = c.post("/gerar-voz/gerar", data={"engine": "chatterbox", "texto": "Olá, tudo bem com você hoje?", "chatterbox_idioma": "pt"})
    assert r.status_code == 200
    for _ in range(100):
        if recebido:
            break
        time.sleep(0.05)
    assert recebido["progresso_arquivo"].endswith(".progresso.json")
    assert "pv-barra" in c.get("/gerar-voz").get_data(as_text=True)
