"""🎙 v84_301: a voz guia não recomeça do zero — o bloco já gerado (mesmo texto + mesma voz) é reaproveitado."""
import subprocess

import pytest

import curtos as CT


def _wav(cam, dur=1.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=300:d={dur}", "-ar", "48000", cam], check=True)


def test_continua_do_bloco_que_travou(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "curtos"))
    monkeypatch.setattr(CT.time, "sleep", lambda s: None)
    base = str(tmp_path)
    p = CT.criar(base, "", "t", [], "x", modelo="comentario")
    p["roteiro"] = {"blocos": [{"id": f"B{i}", "fala": f"fala numero {i}", "cenas": []} for i in range(1, 6)]}
    CT.salvar(base, p)
    voz = {"motor": "piper", "config": {"voz": "pt_BR-faber-medium"}}
    chamadas = []

    def tts_quebra(motor, texto, saida, **kw):
        chamadas.append(texto)
        if "3" in texto:
            raise RuntimeError("O motor de voz travou o processo (código de saída 3221225477)")
        _wav(saida)
    with pytest.raises(RuntimeError):
        CT.gerar_voz_guia(base, p["id"], tts_quebra, voz=voz)
    assert chamadas == ["fala numero 1", "fala numero 2"] + ["fala numero 3"] * 3

    chamadas.clear()

    def tts_ok(motor, texto, saida, **kw):
        chamadas.append(texto)
        _wav(saida)
    info = CT.gerar_voz_guia(base, p["id"], tts_ok, voz=voz)
    assert chamadas == ["fala numero 3", "fala numero 4", "fala numero 5"]  # 1 e 2 já estavam prontos
    assert info["dur"] > 4.5

    chamadas.clear()  # mudou a fala do bloco 2: só ele é refeito
    p = CT.carregar(base, p["id"])
    p["roteiro"]["blocos"][1]["fala"] = "fala nova"
    CT.salvar(base, p)
    CT.gerar_voz_guia(base, p["id"], tts_ok, voz=voz)
    assert chamadas == ["fala nova"]
