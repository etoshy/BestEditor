"""v84_404: 🎚 acabamento da voz — 🎬 takes (fica o melhor pelo Whisper), ✂ silêncio morto (pausas de propósito ficam), 🎛 EQ."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
import historico_voz as hv  # noqa: E402
import narracoes  # noqa: E402
from tts import voice_generator as vg  # noqa: E402
from tts import voz_polimento as vp  # noqa: E402


def _wav(caminho, partes):
    """partes = [("tom"|"sil", segundos)] → .wav 16 kHz."""
    filtros, ins = [], []
    for k, (tipo, s) in enumerate(partes):
        src = f"sine=frequency=330:duration={s}:sample_rate=16000" if tipo == "tom" else f"anullsrc=r=16000:cl=mono:d={s}"
        ins += ["-f", "lavfi", "-t", str(s), "-i", src]
        filtros.append(f"[{k}:a]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", "".join(filtros) + f"concat=n={len(partes)}:v=0:a=1,aformat=channel_layouts=mono",
                    "-ar", "16000", caminho], check=True, capture_output=True)
    return caminho


def _dur(c):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", c],
                                capture_output=True, text=True).stdout)


def test_normalizar_padrao_desligado():
    assert vp.normalizar(None) == {"takes": 1, "cortar_silencios": False, "eq": ""}
    assert vp.normalizar({"takes": "9", "cortar_silencios": True, "eq": "crispy", "lixo": 1}) == {"takes": 3, "cortar_silencios": True, "eq": "crispy"}
    assert vp.normalizar({"eq": "inventado", "takes": "x"})["eq"] == "" and vp.normalizar({"takes": "x"})["takes"] == 1


def test_plano_mantem_as_pausas_de_proposito():
    gaps = [(0.0, 0.6), (1.6, 3.6), (4.6, 5.5), (6.5, 6.9), (7.9, 9.0)]  # ponta, 2.0 s, 0.9 s, 0.4 s, ponta
    # sem pausa de propósito: os dois buracos viram 0.4 s; o de 0.4 fica; as pontas viram 0.15
    c = vp.plano_de_cortes(gaps, 9.0, 0)
    tirado = {round(b - a, 2) for a, b in c}
    assert tirado == {0.45, 1.6, 0.5, 0.95}
    # com 1 "..." no texto: o MAIOR buraco segura até 1,2 s
    c1 = vp.plano_de_cortes(gaps, 9.0, 1)
    assert round(sum(b - a for a, b in c1), 2) == round(0.45 + 0.8 + 0.5 + 0.95, 2)
    assert vp.pausas_intencionais("Ele abriu a porta... e — silêncio. [pausa longa] Fim, ok.") == 3


def test_cortar_silencios_no_arquivo(tmp_path):
    c = _wav(str(tmp_path / "a.wav"), [("tom", 1), ("sil", 2), ("tom", 1), ("sil", 1), ("tom", 1)])
    assert abs(_dur(c) - 6) < 0.05
    tirou = vp.cortar_silencios(c, "Uma frase... outra frase e mais uma.")
    assert 1.2 < tirou < 1.6  # o de 2 s (de propósito) vira 1,2 (-0,8); o de 1 s vira 0,4 (-0,6)
    assert abs(_dur(c) - (6 - tirou)) < 0.1


def test_nota_e_escolha_do_take():
    t = "The instructor made one huge mistake during training."
    bom = "the instructor made one huge mistake during training".split()
    engoliu = "the instructor made mistake training".split()
    repetiu = "the instructor instructor made one huge huge mistake during training".split()
    assert vp.nota_take(t, bom, 3, 8) == 100
    assert vp.nota_take(t, engoliu, 3, 8) < vp.nota_take(t, repetiu, 3, 8) < 100
    assert vp.nota_take(t, bom, 12, 8) < 100 and vp.nota_take(t, bom, 3, 8, lixo_s=1.0) < 100
    ouvido = {"a": engoliu, "b": bom, "c": repetiu}
    melhor, notas = vp.escolher_take(t, ["a", "b", "c"], ouvido.get, lambda c: 3.0, 8)
    assert melhor == 1 and len(notas) == 3


def test_guarda_com_takes_fica_o_melhor(tmp_path, monkeypatch):
    texto = "The instructor made one huge mistake during training."
    falas = [["the", "instructor", "made", "mistake"], texto.lower().rstrip(".").split(), ["the", "the", "instructor"]]
    feitos = []

    def gerar(t, caminho):
        k = len(feitos)
        _wav(caminho, [("tom", 1 + k * 0.5)])
        feitos.append(caminho)
        ouvido[caminho] = falas[k]
    ouvido = {}
    monkeypatch.setattr(vg, "_ouvir_palavras", lambda c: ouvido.get(c, []))
    monkeypatch.setattr(vg, "trechos_sem_fala", lambda c, m=2.0: [])
    monkeypatch.setitem(vg._PROTECAO, "ativa", False)
    monkeypatch.setattr(vg, "_POLIMENTO", {"takes": 3, "cortar_silencios": False, "eq": "", "engine": "chatterbox_turbo"})
    dest = str(tmp_path / "out.wav")
    vg._gerar_com_guarda(gerar, texto, dest)
    assert len(feitos) == 3 and abs(_dur(dest) - 1.5) < 0.05  # o 2º take (o certinho, 1,5 s) ficou
    assert sorted(os.listdir(tmp_path)) == ["out.wav"]  # os outros takes foram apagados
    # motor que não é Chatterbox (ou só [laugh]): 1 take, como antes
    feitos.clear()
    vg._POLIMENTO["engine"] = "kokoro"
    vg._gerar_com_guarda(gerar, texto, dest)
    assert len(feitos) == 1
    feitos.clear()
    vg._POLIMENTO["engine"] = "chatterbox"
    vg._gerar_com_guarda(gerar, "[laugh]", dest)
    assert len(feitos) == 1


def test_eq(tmp_path):
    c = _wav(str(tmp_path / "v.wav"), [("tom", 1)])
    for p in vp.EQ_PRESETS:
        out = vp.aplicar_eq(c, vp.caminho_faixa(c, p), p)
        assert os.path.isfile(out) and out.endswith(f"_eq_{p}.wav")
    vp.aplicar_eq(c, c, "limpa")  # no lugar
    assert abs(_dur(c) - 1) < 0.05
    with pytest.raises(ValueError):
        vp.aplicar_eq(c, c, "nada")


def test_reticencias_ficam_com_o_corte_ligado(monkeypatch):
    t = "He opened the door... and then. Nothing."
    monkeypatch.setattr(narracoes, "_guardar_reticencias", lambda: False)
    assert "..." not in narracoes.limpar_texto_para_tts(t, motor="chatterbox_turbo")
    monkeypatch.setattr(narracoes, "_guardar_reticencias", lambda: True)
    assert narracoes.limpar_texto_para_tts(t, motor="chatterbox_turbo") == "He opened the door... and then, Nothing"
    assert "..." not in narracoes.limpar_texto_para_tts(t, motor="kokoro")


@pytest.fixture
def A(monkeypatch, tmp_path):
    import app as _app
    import site_config
    _app.app.config["TESTING"] = True
    monkeypatch.setattr(_app, "VOZES_DIR", str(tmp_path))
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    return _app


def test_rotas(A, tmp_path):
    c = A.app.test_client()
    j = c.get("/gerar-voz/polimento").get_json()
    assert j["polimento"] == vp.PADRAO and {e["id"] for e in j["eqs"]} == set(vp.EQ_PRESETS)
    c.post("/gerar-voz/polimento", json={"takes": 2, "cortar_silencios": True, "eq": "radio"})
    assert c.get("/gerar-voz/polimento").get_json()["polimento"] == {"takes": 2, "cortar_silencios": True, "eq": "radio"}
    assert vg._polimento_salvo()["takes"] == 2  # o processo do motor lê a mesma config
    # faixas extras com EQ no histórico
    _wav(str(tmp_path / "j1.wav"), [("tom", 1)])
    hv.registrar(str(tmp_path), "j1", {"resultado_filename": "j1.wav", "engine": "chatterbox", "texto_inicio": "Oi"})
    assert c.post("/gerar-voz/historico/j1/eq", json={"presets": []}).status_code == 400
    r = c.post("/gerar-voz/historico/j1/eq", json={"presets": ["limpa", "crispy"]}).get_json()
    assert [f["preset"] for f in r["faixas"]] == ["limpa", "crispy"]
    it = c.get("/gerar-voz/historico").get_json()["itens"][0]
    assert {f["preset"] for f in it["faixas_eq"]} == {"limpa", "crispy"} and all(f["url"] for f in it["faixas_eq"])
    assert os.path.isfile(tmp_path / "j1_eq_crispy.wav")
    html = c.get("/gerar-voz").get_data(as_text=True)
    assert 'id="pol-box"' in html and "hist-eq-gerar" in html
    hv.apagar(str(tmp_path), "j1")
    assert not os.path.exists(tmp_path / "j1_eq_crispy.wav")
