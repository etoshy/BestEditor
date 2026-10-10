"""
Upload de .zip (áudio + .srt) indo até a tela do prompt — casos que
travavam ou falhavam na prática:

- com "usar buscadores de imagem" marcado, a página de "transcrevendo" não
  conhecia o status `aguardando_termos_buscadores` e ficava parada pra sempre;
- zip criado no macOS (pasta __MACOSX com "._narracao.wav", que tem extensão
  de áudio mas não é áudio);
- .srt salvo em UTF-16/ANSI, com ponto em vez de vírgula nos milissegundos.
"""
import io
import os
import subprocess
import time
import zipfile

import pytest

import legendas as lg

SRT = "1\r\n00:00:00,000 --> 00:00:03,000\r\nOlá mundo\r\n\r\n2\r\n00:00:03,000 --> 00:00:06,000\r\nSegunda frase\r\n"


@pytest.fixture
def wav_bytes(tmp_path):
    p = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=6", str(p)], check=True)
    return p.read_bytes()


def _zip(arquivos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nome, dados in arquivos.items():
            zf.writestr(nome, dados)
    buf.seek(0)
    return buf


@pytest.fixture
def client():
    import app as A
    A.app.config["TESTING"] = True
    return A, A.app.test_client()


def _enviar(client, buf, **extra):
    A, c = client
    r = c.post("/transcribe", data={"audio": (buf, "narracao_e_legenda.zip"), "interval_seconds": "7",
                                    "providers": ["pexels", "bing"], **extra}, content_type="multipart/form-data")
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    job_id = r.headers["Location"].rstrip("/").split("/")[-2]
    deadline = time.time() + 10
    while A._JOBS[job_id]["status"] == "transcrevendo" and time.time() < deadline:
        time.sleep(0.05)
    return A._JOBS[job_id]


def test_zip_do_gerador_de_voz_vai_pro_prompt(client, wav_bytes):
    job = _enviar(client, _zip({"narracao.wav": wav_bytes, "legenda.srt": SRT.encode()}))
    assert job["status"] == "aguardando_json", job.get("error")
    assert job["segments"][1]["text"] == "Segunda frase"


def test_zip_com_modo_buscadores_e_pagina_de_espera_sabe_pra_onde_ir(client, wav_bytes):
    job = _enviar(client, _zip({"narracao.wav": wav_bytes, "legenda.srt": SRT.encode()}),
                  usar_buscadores_inteligente="on")
    assert job["status"] == "aguardando_termos_buscadores"
    A, c = client
    html = c.get(f"/job/{job['job_id']}/transcribing").get_data(as_text=True)
    assert "aguardando_termos_buscadores" in html
    assert f"/job/{job['job_id']}/termos-buscadores" in html


def test_zip_do_macos_ignora_arquivos_fantasma(client, wav_bytes):
    job = _enviar(client, _zip({
        "__MACOSX/._narracao.wav": b"\x00\x05\x16\x07lixo", "__MACOSX/._legenda.srt": b"\x00lixo",
        "pasta/narracao.wav": wav_bytes, "pasta/legenda.srt": SRT.encode(), ".DS_Store": b"x",
    }))
    assert job["status"] == "aguardando_json", job.get("error")
    assert open(job["audio_path"], "rb").read() == wav_bytes


def test_srt_em_utf16_e_ansi(client, wav_bytes):
    for dados in (SRT.encode("utf-16"), SRT.encode("cp1252")):
        job = _enviar(client, _zip({"narracao.wav": wav_bytes, "legenda.srt": dados}))
        assert job["status"] == "aguardando_json", job.get("error")
        assert job["segments"][0]["text"] == "Olá mundo"


def test_zip_sem_srt_mostra_erro_na_tela(client, wav_bytes):
    A, c = client
    r = c.post("/transcribe", data={"audio": (_zip({"narracao.wav": wav_bytes}), "x.zip"), "interval_seconds": "7"},
               content_type="multipart/form-data")
    assert r.status_code == 200
    assert "não encontrei nenhum arquivo .srt" in r.get_data(as_text=True)


@pytest.mark.parametrize("linha, inicio, fim", [
    ("00:00:01,500 --> 00:00:03,250", 1.5, 3.25),
    ("00:00:01.500 --> 00:00:03.250", 1.5, 3.25),   # ponto no lugar da vírgula
    ("0:00:01,5 --> 0:00:03,25", 1.5, 3.25),         # hora com 1 dígito, ms curto
])
def test_parse_srt_aceita_variacoes_de_tempo(linha, inicio, fim):
    segs = lg.parse_srt(f"1\n{linha}\ntexto\n")
    assert segs[0]["start"] == pytest.approx(inicio) and segs[0]["end"] == pytest.approx(fim)
