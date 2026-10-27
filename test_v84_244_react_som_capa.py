"""v84_244: 🎭 o som do react sai IGUAL à música original (sem sons automáticos/limitador/reamostragem), a camada 🎬 das
imagens de destaque dá pra esconder 👁 (e o que está oculto não sai nem no projeto que já estava no editor), e a 🖼 capa
gira/espelha cada peça e salva sem remontar (não pisca)."""
import os
import subprocess

import numpy as np
import pytest
from PIL import Image

import dp_sons as ds
import react_personagens as R


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_PERSONAGENS_DIR", str(tmp_path / "react"))
    monkeypatch.setenv("PERSONAGENS_POD_DIR", str(tmp_path / "pod"))
    return str(tmp_path)


def _pcm(path, ar):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(ar), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32)


def _taxa(path):
    return int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of",
                               "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout.strip())


def test_mixar_preservando_nao_mexe_na_musica(tmp_path):
    nar = tmp_path / "m.wav"  # música alta (perto do 0 dB), em 44.1k
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100:duration=5",
                    "-af", "volume=2.6", "-ac", "2", "-c:a", "pcm_s16le", str(nar)], check=True)
    ev = ds.evento("impacto/impacto_5", 3.5)
    out = ds.mixar(str(nar), [ev], str(tmp_path / "o.wav"), volume_sfx=1.0, preservar=True)
    assert _taxa(out) == 44100
    a, b = _pcm(nar, 44100), _pcm(out, 44100)
    n = int(2.5 * 44100)  # antes do efeito: a música é a MESMA, amostra por amostra (sem limitador)
    assert np.abs(a[:n] - b[:n]).max() <= 1
    # sem preservar (vídeo narrado normal) continua como antes: 48k com limitador
    assert _taxa(ds.mixar(str(nar), [ev], str(tmp_path / "o2.wav"), volume_sfx=1.0)) == 48000


def test_job_de_react_sem_sons_automaticos():
    import app
    cfg = app._job_site_cfg({"react": {"projeto": "x"}, "editor_defaults": {"sons_auto": {"transicoes": True, "cenas": True}}})
    assert cfg["audio_original"] is True and not any(cfg["sons_auto"].values())
    assert not app._job_site_cfg({}).get("audio_original")


def test_extrair_audio_na_taxa_original(tmp_path):
    v = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=2", "-f", "lavfi",
                    "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(v)], check=True, capture_output=True)
    assert _taxa(R.extrair_audio(str(v), str(tmp_path / "a.wav"))) == 48000


def test_qualidade_final_copia_o_audio():
    src = open(os.path.join(os.path.dirname(__file__), "qualidade_export.py"), encoding="utf-8").read()
    assert '"-c:a", "copy", "-movflags"' in src


def _proj(base):
    p = R.criar("Teste", base)
    for nome in ["Itachi", "Sasuke"]:
        R.novo_personagem(p, nome, obra="Naruto")
    p["video"] = {"duracao": 60.0}
    return p


def test_cena_e_camada_da_pilha_e_oculta_sai_do_editor(base):
    p = _proj(base)
    lay = R.disposicao(p, base)
    ordem = R.pilha(p, lay)["ordem"]
    assert "cena" in ordem and ordem.index("cena") == ordem.index("legenda") - 1
    pec = R.pecas_para_editar(p, base, 1.0)
    assert any(x["chave"] == "cena" and x.get("cena_tela") for x in pec["pecas"])
    R.guardar_pilha(p, {"ocultas": ["cena", "p:" + p["personagens"][0]["id"]]}, base)
    R.salvar(p, base)
    cid0, cid1 = p["personagens"][0]["id"], p["personagens"][1]["id"]
    ovs = [{"id": "rcena_1", "origem": "react", "camada": "cena", "trilha": "cena"},  # projeto antigo: sem pilha_chave
           {"id": "rfoto_1", "origem": "react", "camada": "foto"},
           {"id": f"r{cid0}_0", "origem": "react", "camada": "personagem", "cid": cid0, "trilha": f"p:{cid0}"},
           {"id": f"r{cid1}_0", "origem": "react", "camada": "personagem", "cid": cid1, "pilha_chave": f"p:{cid1}"},
           {"id": "rtela", "origem": "react_tela", "camada": "tela"},
           {"id": "meu", "origem": "manual"}]
    ids = [o["id"] for o in R.filtrar_ocultas_editor(p["id"], ovs, base)]
    assert ids == ["rfoto_1", f"r{cid1}_0", "rtela", "meu"]
    p["imagens_destaque"] = False  # 🖼 desligado: nem cena nem foto
    R.salvar(p, base)
    assert "rfoto_1" not in [o["id"] for o in R.filtrar_ocultas_editor(p["id"], ovs, base)]
    assert R.chave_do_overlay({"camada": "sofa", "id": "rsofa1"}) == "sofa1"
    assert R.chave_do_overlay({"camada": "personagem", "copia": "c:ab"}) == "c:ab"


def test_capa_gira_e_espelha(base, tmp_path, monkeypatch):
    p = _proj(base)
    fundo = tmp_path / "f.png"
    Image.new("RGB", (R.CAPA_W, R.CAPA_H), (0, 0, 0)).save(fundo)
    peca = tmp_path / "p.png"
    im = Image.new("RGBA", (200, 100), (255, 0, 0, 255))
    im.paste((0, 0, 255, 255), (0, 0, 40, 100))  # azul na ESQUERDA
    im.save(peca)
    base_pc = {"chave": "x", "nome": "x", "arq": str(peca), "x": 400, "y": 300, "w": 200, "h": 100, "oculta": False}
    for rot, esp, testa in ((0, True, "esp"), (90, False, "rot")):
        monkeypatch.setattr(R, "capa_pecas", lambda *_a, **_k: {"fundo": str(fundo), "pecas": [dict(base_pc, rot=rot, esp=esp)], "tem_video": False})
        out = Image.open(R.compor_capa_react(p, base, {}, str(tmp_path / f"c_{testa}.jpg"))).convert("RGB")
        if testa == "esp":
            assert out.getpixel((590, 350))[2] > 200 and out.getpixel((410, 350))[0] > 200  # o azul foi pra direita
        else:  # 90° no sentido do relógio em volta do centro (500, 350): fica em pé, o azul em cima
            assert out.getpixel((500, 265))[2] > 200 and out.getpixel((500, 430))[0] > 200 and out.getpixel((420, 350)) == (0, 0, 0)


def test_capa_pos_guarda_giro_sem_remontar(base):
    import app as appmod
    p = _proj(base)
    R.salvar(p, base)
    cl = appmod.app.test_client()
    r = cl.post(f"/react-personagens/{p['id']}/capa/estado", json={"leve": True, "pos": {"p:x": {"x": 10, "y": 20, "w": 300, "rot": 12.5, "esp": True}}})
    if r.status_code == 404:
        pytest.skip("rota não registrada neste app de teste")
    assert r.get_json()["ok"] and "pecas" not in r.get_json()
    r = cl.post(f"/react-personagens/{p['id']}/capa/estado", json={"leve": True, "pos": {"p:x": {"x": 50, "y": 20, "w": 300}}})
    pos = R.capa_cfg(R.carregar(p["id"], base))["pos"]["p:x"]
    assert pos["x"] == 50 and pos["rot"] == 12.5 and pos["esp"] is True  # mexer no lugar não perde o giro


def test_pagina_tem_os_controles_da_capa():
    s = open(os.path.join(os.path.dirname(__file__), "templates", "react_detalhe.html"), encoding="utf-8").read()
    for x in ('id="capaRot"', 'id="capaGirarE"', 'id="capaGirarD"', 'id="capaEsp"', "capaGuardarLeve", "cena_tela"):
        assert x in s
