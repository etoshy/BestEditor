"""v84_402: 📤 Link → vídeo com o ARQUIVO enviado (o link não baixa: idade, privado…) + a transcrição junto."""
import io
import os

import curtos as CT
import curtos_comentario as CC
import curtos_link as CL
from test_v84_320_lote_por_etapa import _app, _falsos


def test_enviar_cria_o_video_com_o_arquivo(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    _falsos(base, monkeypatch)
    dados = {"arquivo": (io.BytesIO(b"\x00\x00\x00 ftypmp42 video falso"), "Briga no Transito!.mp4"),
             "transcricao": "0:01 he gets out of the car\n0:04 he slaps the biker", "link_original": "https://www.youtube.com/watch?v=9dleS6MdHfw",
             "opcoes": '{"roteiro_reverso": true, "exportar": false}'}
    j = cl.post("/curtos/link/enviar", data=dados, content_type="multipart/form-data").get_json()
    pid = j["criados"][0]
    p = CT.carregar(base, pid)
    url = p["link_rapido"]["link"]
    assert CL.eh_arquivo(url) and p["config"]["estilo_roteiro"] == "reverso"
    assert os.path.isfile(CL.caminho_envio(url)) and CL.meta_envio(url)["transcricao"].startswith("0:01")
    # baixar = copiar o arquivo enviado
    cam = CC.baixar_link(url, str(tmp_path / "dl"))
    assert open(cam, "rb").read().endswith(b"video falso")
    # crédito: o link original (sem link: nada)
    assert "youtube" in CL.com_fonte("Desc.", url, {}).lower() or CL.com_fonte("Desc.", url, {}) == "Desc."
    assert CL.link_de_credito(url) == "https://www.youtube.com/watch?v=9dleS6MdHfw"
    # sem arquivo / extensão errada
    assert cl.post("/curtos/link/enviar", data={"opcoes": "{}"}, content_type="multipart/form-data").status_code == 400
    r = cl.post("/curtos/link/enviar", data={"arquivo": (io.BytesIO(b"x"), "nota.txt")}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert 'id="envArq"' in cl.get("/curtos/link").get_data(as_text=True)


def test_info_de_arquivo_sem_link_nao_chama_o_ytdlp(tmp_path, monkeypatch):
    CL.PASTA_ENVIOS = str(tmp_path)
    f = tmp_path / "x.mp4"
    f.write_bytes(b"v")
    url = CL.guardar_envio(str(f), "x.mp4", "", "")
    chamou = []
    monkeypatch.setattr(CL.subprocess, "run", lambda *a, **k: chamou.append(1))
    assert CL.baixar_info(url) == {"comentarios": []} and not chamou
    assert CL.link_de_credito(url) == "" and CL.com_fonte("Desc.", url, {}) == "Desc."
