"""v84_121 — 🖥️ Meu pod: imagens (Z-Image Turbo) e Chatterbox/Turbo gerados no SEU pod da RunPod (servidor studio-ia)."""
import io
import json
import os
import sys
import zipfile

import pytest

import pod_studio
import runpod_gerador as rp

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))
from tts import voice_generator as vg  # noqa: E402

POD = {"runpod_modo": "pod", "runpod_pod_url": "https://abc123-8000.proxy.runpod.net", "runpod_pod_chave": "",
       "chatterbox_onde": "pod", "chatterbox_pod_ptbr": True, "runpod_api_key": "", "orientation": "16:9"}


@pytest.fixture
def cfg_site(monkeypatch):
    estado = dict(POD)
    monkeypatch.setattr(pod_studio, "_cfg", lambda cfg=None: dict(estado, **(cfg or {})))
    monkeypatch.setattr(rp, "_cfg", lambda cfg=None: dict(estado, **(cfg or {})))
    return estado


class _Resp:
    def __init__(self, status=200, dados=None, conteudo=b""):
        self.status_code, self._dados, self.content, self.text = status, dados, conteudo, json.dumps(dados or {})

    def json(self):
        return self._dados

    def iter_content(self, n):
        yield self.content


@pytest.fixture
def pod_falso(monkeypatch, cfg_site):
    """Simula o servidor studio-ia: cria o job, responde o status e entrega o arquivo."""
    import requests
    pedidos = []

    def request(metodo, url, headers=None, timeout=None, **kw):
        caminho = url.split(".runpod.net", 1)[1]
        pedidos.append((metodo, caminho, kw))
        if metodo == "POST" and caminho == "/imagens":
            return _Resp(200, {"id": "img-1"})
        if metodo == "POST" and caminho == "/voz/texto":
            return _Resp(200, {"id": "voz-1"})
        if caminho in ("/jobs/img-1", "/jobs/voz-1"):
            nome = "imagem.png" if "img" in caminho else "narracao.wav"
            return _Resp(200, {"status": "concluido", "arquivos": [nome, "metadados.json"], "progresso": {}})
        if caminho.startswith("/jobs/") and "/arquivos/" in caminho:
            return _Resp(200, conteudo=b"PNG" if caminho.endswith(".png") else b"RIFF....WAVE")
        if caminho == "/status":
            return _Resp(200, {"workers": {"imagem": {"estado": "pronto"}, "voz": {"estado": "pronto"}},
                               "gpu": [{"nome": "L40S", "vram_usada_mb": 20000, "vram_total_mb": 46000}]})
        raise AssertionError(caminho)

    monkeypatch.setattr(requests, "request", request)
    monkeypatch.setattr(pod_studio.time, "sleep", lambda s: None)
    return pedidos


def test_configuracao_e_motores(cfg_site):
    assert pod_studio.imagens_no_pod() and pod_studio.motor_no_pod("chatterbox") and pod_studio.motor_no_pod("chatterbox_turbo")
    assert not pod_studio.motor_no_pod("xtts") and not pod_studio.motor_no_pod("fish_s2")
    cfg_site["chatterbox_onde"] = "local"
    assert not pod_studio.motor_no_pod("chatterbox")
    cfg_site["runpod_pod_url"] = "não é url"
    assert not pod_studio.configurado() and not pod_studio.imagens_no_pod()


def test_site_config_valida_pod(tmp_path):
    import site_config
    caminho = str(tmp_path / "c.json")
    c = site_config.save_site_config({"runpod_modo": "xyz", "runpod_pod_url": "javascript:alert(1)",
                                      "chatterbox_onde": "nuvem"}, path=caminho)
    assert (c["runpod_modo"], c["runpod_pod_url"], c["chatterbox_onde"]) == ("endpoints", "", "local")
    c = site_config.save_site_config({"runpod_modo": "pod", "runpod_pod_url": "https://x-8000.proxy.runpod.net/",
                                      "chatterbox_onde": "pod"}, path=caminho)
    assert (c["runpod_modo"], c["runpod_pod_url"], c["chatterbox_onde"]) == ("pod", "https://x-8000.proxy.runpod.net", "pod")


def test_imagem_no_pod_sem_chave_sem_saldo_e_com_cache(monkeypatch, tmp_path, pod_falso):
    monkeypatch.setenv("RUNPOD_DADOS_DIR", str(tmp_path / "rp"))
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    monkeypatch.setattr(rp, "saldo", lambda *a, **k: pytest.fail("no pod não confere saldo"))
    assert rp.configurado() and rp.modo() == "pod" and rp.tem_saldo("imagem") is True
    r = rp.gerar("um farol no litoral ao pôr do sol", "imagem")
    assert r["modelo"] == "pod:z-image-turbo" and r["custo"] == 0.0 and not r["reaproveitado"]
    assert open(r["caminho"], "rb").read() == b"PNG"
    corpo = next(kw["json"] for m, c, kw in pod_falso if c == "/imagens")
    assert (corpo["largura"], corpo["altura"]) == (1280, 720) and corpo["prompts"][0]["prompt"]
    n = len(pod_falso)
    assert rp.gerar("um farol no litoral ao pôr do sol", "imagem")["reaproveitado"] and len(pod_falso) == n
    assert rp.uso()["por_modelo"]["pod:z-image-turbo"] == 0.0


def test_video_no_modo_pod_sem_chave_vira_foto(cfg_site):
    assert rp.tem_saldo("video") is False
    with pytest.raises(rp.RunpodSemChave):
        rp.gerar("ondas quebrando", "video")


def test_chatterbox_e_turbo_geram_no_pod(monkeypatch, tmp_path, pod_falso):
    monkeypatch.setattr(vg, "chatterbox_load", lambda **k: pytest.fail("não pode carregar o modelo local"))
    monkeypatch.setattr(vg, "chatterbox_turbo_load", lambda **k: pytest.fail("não pode carregar o modelo local"))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    monkeypatch.setattr(vg, "_preparar_audio_referencia", lambda c, **k: str(c))
    saida = vg.chatterbox_synthesize("Olá, mundo.", str(tmp_path / "a.wav"), idioma="pt", speaker_wav=str(ref),
                                     exaggeration=0.7)
    assert open(saida, "rb").read().startswith(b"RIFF")
    m, c, kw = next(p for p in pod_falso if p[1] == "/voz/texto")
    assert kw["data"]["motor"] == "chatterbox" and kw["data"]["idioma"] == "pt" and kw["data"]["exaggeration"] == "0.7"
    assert kw["data"]["pacote_dedicado"] == "true" and "referencia" in kw["files"]
    pod_falso.clear()
    vg.chatterbox_turbo_synthesize("Hi [laugh] there", str(tmp_path / "b.wav"))
    m, c, kw = next(p for p in pod_falso if p[1] == "/voz/texto")
    assert kw["data"]["motor"] == "chatterbox_turbo" and kw["data"]["idioma"] == "en" and not kw["files"]


def test_chatterbox_local_quando_nao_esta_no_pod(monkeypatch, tmp_path, cfg_site):
    cfg_site["chatterbox_onde"] = "local"
    monkeypatch.setattr(vg, "_narrar_no_pod", lambda *a, **k: pytest.fail("não devia ir pro pod"))

    class Modelo:
        sr = 24000

        def generate(self, texto, **kw):
            return [0.0] * 10

    monkeypatch.setattr(vg, "chatterbox_load", lambda **k: Modelo())
    monkeypatch.setattr(vg, "_salvar_audio_chatterbox", lambda wav, destino, sr: open(destino, "wb").write(b"L"))
    vg.chatterbox_synthesize("Olá.", str(tmp_path / "c.wav"), idioma="pt")
    assert open(tmp_path / "c.wav", "rb").read() == b"L"


def test_erro_do_pod_vira_erro_de_voz_claro(monkeypatch, tmp_path, cfg_site):
    import requests

    def cai(*a, **k):
        raise requests.exceptions.ConnectionError("x")

    monkeypatch.setattr(requests, "request", cai)
    with pytest.raises(vg.VoiceGeneratorError, match="Pod: O pod não respondeu"):
        vg.chatterbox_synthesize("Olá.", str(tmp_path / "d.wav"), idioma="pt")


def test_fila_e_geracao_rapida_nao_contam_vram_deste_pc(cfg_site):
    import fila_voz
    import tts_paralelo
    assert fila_voz._no_pod("chatterbox") and not fila_voz._no_pod("kokoro")
    n, motivo = tts_paralelo.escolher("chatterbox", "auto", caracteres=50000,
                                      vram_fn=lambda: {"livre": 0.5, "total": 8, "nome": "placa"},
                                      ram_fn=lambda: {"livre": 1.0, "total": 8})
    assert n == 2 and "pod" in motivo


def test_status_do_pod(pod_falso):
    s = pod_studio.status()
    assert s["ok"] and "pronto" in s["msg"] and "L40S" in s["msg"]
