"""v84_103 — ⚡ geração rápida: várias instâncias do motor de voz gerando blocos diferentes do MESMO áudio ao mesmo
tempo (processos de verdade, com um motor falso), escolha pela VRAM/RAM/CPU e aviso de que o PC pode ficar lento."""
import os
import subprocess
import time

import pytest

import app  # noqa: F401,E402 — põe toolkit/ no caminho (o pacote tts)
import tts_paralelo as tp
from tts import voice_generator as vg

V = lambda: {"livre": 11.0, "total": 12.0, "nome": "RTX"}  # noqa: E731
R = lambda: {"livre": 20.0, "total": 32.0}  # noqa: E731


def _dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
                                capture_output=True, text=True).stdout.strip())


def test_escolher_por_vram_ram_e_cpu(monkeypatch):
    assert tp.escolher("chatterbox", "1", False, 30000, V, R)[0] == 1          # desligada
    assert tp.escolher("chatterbox", "auto", False, 800, V, R)[0] == 1         # texto curto
    n, por = tp.escolher("chatterbox_turbo", "auto", False, 30000, V, R)
    assert n == 2 and "VRAM" in por                                            # (11-0.8)//3.5
    n, por = tp.escolher("chatterbox", "4", False, 30000, V, lambda: {"livre": 7.0, "total": 16.0})
    assert n == 1 and "RAM" in por                                             # (7-2.5)//4.5
    assert tp.escolher("xtts", "auto", False, 30000, lambda: None, R)[1].count("sem placa NVIDIA")
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert tp.escolher("kokoro", "auto", False, 30000, V, R)[0] == 3 and tp.escolher("fish_s2", "4", False, 30000, V, R)[0] == 2
    assert "lento" in tp.AVISO and tp.ler_ram() is None or tp.ler_ram()["total"] > 0


def test_dividir_blocos():
    t = "\n\n".join(("Satz eins ist hier. " * 12).strip() for _ in range(20))
    assert tp.dividir_blocos(t, 1) == [t]
    b = tp.dividir_blocos(t, 3)
    assert len(b) >= 6 and all(x.endswith(".") for x in b)
    assert " ".join(" ".join(b).split()) == " ".join(t.split())  # nada some, nada repete


@pytest.fixture
def falso(monkeypatch):
    monkeypatch.setenv("VOICE_GENERATOR_TESTE_MOTOR_FALSO", "1")


def test_paralelo_em_processos_de_verdade(falso, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_GENERATOR_TESTE_LENTO", "1.0")
    itens = [("teste", "x" * 60, str(tmp_path / f"b{i}.wav"), {}) for i in range(6)]
    vistos = []
    t0 = time.time()
    erros = vg.gerar_audio_isolado_paralelo(itens, 3, on_progresso=lambda i, e, w: vistos.append((i, e, w)), intervalo_inicio=0.2)
    gasto = time.time() - t0
    assert erros == {} and sorted(i for i, _e, _w in vistos) == list(range(6))
    assert len({w for _i, _e, w in vistos}) >= 2  # mais de uma instância trabalhou
    assert all(os.path.exists(x[2]) for x in itens)
    assert gasto < 6 * 1.0 + 8  # 6 blocos de 1 s com 3 instâncias (+ partida dos processos)


def test_gerar_partes_junta_na_ordem(falso, tmp_path):
    textos = ["Primeira parte. " * 60, "", "Segunda parte. " * 80]
    saidas = tp.gerar_partes("teste", textos, str(tmp_path / "p"), {}, 2)
    assert saidas[1] is None and os.path.exists(saidas[0]) and os.path.exists(saidas[2])
    esperado = sum(max(0.2, min(20.0, len(b) / 60.0)) for b in tp.dividir_blocos(textos[2], 2))
    assert abs(_dur(saidas[2]) - esperado) < 0.3
    out = str(tmp_path / "um.wav")
    tp.gerar_texto("teste", textos[0], out, {}, 2)
    assert os.path.exists(out) and not os.path.isdir(str(tmp_path / "um_blocos"))


def test_rotas_previa_e_config(monkeypatch, tmp_path):
    import app as _app
    import site_config
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))
    c = _app.app.test_client()
    d = c.get("/gerar-voz/instancias/previa").get_json()
    assert d["modo"] == "1" and d["instancias"] == 1 and "lento" in d["aviso"] and "nucleos" in d
    assert c.post("/gerar-voz/instancias/config", json={"modo": "auto"}).get_json()["ok"]
    assert tp.modo_salvo() == "auto"
    assert c.post("/gerar-voz/instancias/config", json={"modo": "9"}).status_code == 400
    h = c.get("/gerar-voz").get_data(as_text=True)
    assert 'id="inst-on"' in h and "um pouco lento" in h
