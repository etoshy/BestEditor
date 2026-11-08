"""v84_363: 🌐 a conexão cai no download (Instagram 10054) → tenta de novo sozinho e, se não der, explica em português."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "toolkit"))
from redes_sociais import _ytdlp_base as YB  # noqa: E402
RedesSociaisError = YB.RedesSociaisError

ERRO = ("ERROR: [download] Got error: ('Connection broken: ConnectionResetError(10054, 'Foi forçado o cancelamento de uma "
        "conexão existente pelo host remoto', None, 10054, None)')")


def _falso(falhas):
    estado = {"n": 0, "opcoes": None}

    class YDL:
        def __init__(self, opcoes):
            estado["opcoes"] = opcoes
            self.o = opcoes

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def download(self, urls):
            estado["n"] += 1
            if estado["n"] <= falhas:
                raise Exception(ERRO)
            open(self.o["outtmpl"].replace("%(ext)s", "mp4"), "wb").write(b"0")

    return type("M", (), {"YoutubeDL": YDL}), estado


def test_tenta_de_novo_quando_a_conexao_cai(tmp_path):
    m, st = _falso(2)
    cam = YB.baixar_com_ytdlp("https://www.instagram.com/reel/x/", tmp_path, ytdlp_module=m)
    assert cam.endswith("original.mp4") and st["n"] == 3
    assert st["opcoes"]["retries"] == 10 and st["opcoes"]["socket_timeout"] == 30


def test_desiste_com_mensagem_clara(tmp_path):
    m, st = _falso(99)
    try:
        YB.baixar_com_ytdlp("https://www.instagram.com/reel/x/", tmp_path, ytdlp_module=m)
        assert False
    except RedesSociaisError as e:
        assert "conexão com o site caiu" in str(e) and "tentar de novo" in str(e)
    assert st["n"] == len(YB.ESPERAS_REDE_S) + 1
    assert YB.erro_de_rede(ERRO) and not YB.erro_de_rede("Unsupported URL")
