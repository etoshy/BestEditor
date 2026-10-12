"""v84_75 — 📜 Histórico de áudios: baixar o .zip (narração + legenda + info.json) mesmo depois de reiniciar o site."""
import io
import json
import zipfile

import pytest

import historico_voz as hv


@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(_app, "VOZES_DIR", str(tmp_path))
    monkeypatch.setattr(hv, "duracao_audio", lambda c: 1.0)
    return _app


def _entrada(pasta, jid, **extra):
    (pasta / f"{jid}.wav").write_bytes(b"RIFF....WAVE")
    (pasta / f"{jid}.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nOi\n", encoding="utf-8")
    st = dict({"resultado_filename": f"{jid}.wav", "resultado_srt_filename": f"{jid}.srt", "engine": "kokoro",
               "idioma": "pt", "texto_inicio": "Oi"}, **extra)
    hv.registrar(str(pasta), jid, st)


def test_zip_do_historico_sem_status_na_memoria(A, tmp_path):
    _entrada(tmp_path, "abc123", roteiro_id="r9")
    (tmp_path / "abc123_ch.json").write_text("[]", encoding="utf-8")
    e = hv._ler(str(tmp_path))
    e[0]["chamadas"] = "abc123_ch.json"
    hv._gravar(str(tmp_path), e)
    A._GERAR_VOZ_STATUS.pop("abc123", None)
    c = A.app.test_client()
    it = c.get("/gerar-voz/historico").get_json()["itens"][0]
    assert it["zip_url"].endswith("/gerar-voz/baixar-zip/abc123")
    assert c.get("/gerar-voz/status/abc123").get_json()["resultado"]["zip_url"] == it["zip_url"]
    r = c.get(it["zip_url"])
    assert r.status_code == 200 and r.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert set(z.namelist()) == {"narracao.wav", "legenda.srt", "info.json", "chamadas.json"}
    info = json.loads(z.read("info.json"))
    assert info.get("roteiro_id") == "r9" and info.get("idioma") == "pt"


def test_sem_zip_quando_deu_erro_ou_id_estranho(A, tmp_path):
    hv.registrar(str(tmp_path), "ruim1", {"erro": "falhou", "engine": "piper"})
    c = A.app.test_client()
    it = c.get("/gerar-voz/historico").get_json()["itens"][0]
    assert "zip_url" not in it
    assert c.get("/gerar-voz/baixar-zip/ruim1").status_code == 404
    assert c.get("/gerar-voz/baixar-zip/n%C3%A3o..existe").status_code == 404
