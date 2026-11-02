"""v84_313: controle de memória — lote de links, retomada, geração de voz e pools menores não estouram a RAM."""
import sys
import types

import memoria_ram as MR


def _ram(*valores_gb):
    leituras = {"n": 0}

    def livre():
        leituras["n"] += 1
        i = min(leituras["n"], len(valores_gb)) - 1
        return types.SimpleNamespace(available=valores_gb[i] * 1024 ** 3)
    return types.SimpleNamespace(virtual_memory=livre)


def test_espera_ram_aguarda_ate_ter_memoria(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", _ram(1, 1, 8))
    monkeypatch.setattr(MR.time, "sleep", lambda s: None)
    liberou = []
    monkeypatch.setattr(MR, "liberar_pesados", lambda: liberou.append(1))
    msgs = []
    MR.espera_ram(msgs.append)
    assert len(msgs) == 2 and all("pouca memória" in m for m in msgs)
    assert len(liberou) == 3  # soltou a cada espera e ao sair


def test_espera_ram_sem_psutil_nao_faz_nada(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)
    msgs = []
    MR.espera_ram(msgs.append)
    assert msgs == []


def test_liberar_solta_modelos_ja_carregados(monkeypatch):
    chamadas = []
    monkeypatch.setitem(sys.modules, "whisper_transcribe",
                        types.SimpleNamespace(descarregar_modelos=lambda: chamadas.append("whisper") or True))
    monkeypatch.setitem(sys.modules, "momentos_yt", types.SimpleNamespace(liberar_moondream=lambda: chamadas.append("moondream")))
    MR.liberar_pesados()
    assert chamadas == ["whisper", "moondream"]


def test_liberar_nao_importa_o_que_nao_foi_carregado(monkeypatch):
    monkeypatch.delitem(sys.modules, "whisper_transcribe", raising=False)
    monkeypatch.delitem(sys.modules, "momentos_yt", raising=False)
    MR.liberar_pesados()
    assert "whisper_transcribe" not in sys.modules and "momentos_yt" not in sys.modules


def test_motor_de_voz_espera_ram_antes_do_processo(monkeypatch):
    import toolkit.tts.voice_generator as VG
    chamadas = []
    monkeypatch.setattr(MR, "espera_ram", lambda prog=None, limite_s=900: chamadas.append(1))
    VG._memoria_antes_do_processo()
    assert chamadas == [1]


def test_whisper_descarrega_em_1_minuto(monkeypatch):
    import whisper_transcribe as WT
    monkeypatch.delenv("WHISPER_OCIOSO_S", raising=False)
    assert WT._ocioso_s() == 60.0
