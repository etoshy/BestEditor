"""v84_175 — 🪟 WinError 1455 ("arquivo de paginação muito pequeno") na 1ª carga do Chatterbox: tenta de novo sozinho."""
import pytest

import perfis_limpeza as pl

vg = pl._vg()


def test_tenta_de_novo_no_1455(monkeypatch):
    monkeypatch.setattr(vg.time, "sleep", lambda s: None)
    n = []

    def carregar():
        n.append(1)
        if len(n) == 1:
            raise OSError("O arquivo de paginação é muito pequeno para que esta operação seja concluída. (os error 1455)")
        return "modelo"
    assert vg._carregar_com_nova_tentativa(carregar, "Chatterbox") == "modelo" and len(n) == 2


def test_desiste_com_explicacao_e_nao_mexe_em_outros_erros(monkeypatch):
    monkeypatch.setattr(vg.time, "sleep", lambda s: None)

    def sempre():
        raise OSError("[WinError 1455] The paging file is too small")
    with pytest.raises(vg.VoiceGeneratorError, match="Memória virtual"):
        vg._carregar_com_nova_tentativa(sempre, "Chatterbox")
    n = []

    def outro():
        n.append(1)
        raise RuntimeError("CUDA out of memory")
    with pytest.raises(RuntimeError):
        vg._carregar_com_nova_tentativa(outro, "Chatterbox")
    assert len(n) == 1
