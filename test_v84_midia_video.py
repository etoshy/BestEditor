"""
Vídeos dos projetos (🛒 venda / 🕵️ modelo): transcrição com os tempos no prompt;
a IA decide tocar um pedaço com o ÁUDIO ORIGINAL (corte, a narração pausa) ou mostrar
SEM som sob a narração (trecho "M3@12-25"). E os 6 modelos novos de nicho.
"""
import json
import os
import subprocess

import pytest

import dossies as ds
import midia_transcricao as mt
import vendas as vd


def _video(caminho, dur=4):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=25:duration={dur}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", caminho], check=True)
    return caminho


def _falso(caminho, **k):
    return [{"start": 0.0, "end": 1.5, "text": "Olha como fecha bem."}, {"start": 1.5, "end": 3.2, "text": "Não vaza nada!"}]


def test_transcricao_com_tempos(tmp_path):
    v = _video(str(tmp_path / "a.mp4"))
    d = mt.transcrever(v, transcrever_fn=_falso)
    assert d["estado"] == "pronta" and d["duracao"] > 3.5 and d["segmentos"][1]["texto"] == "Não vaza nada!"
    assert mt.resumo(v)["texto"] == "[0:00–0:02] Olha como fecha bem.\n[0:02–0:03] Não vaza nada!"
    pp = mt.para_prompt(v)
    assert pp.startswith(" (vídeo de 0:04). O que é dito nele:") and "[0:02–0:03] Não vaza nada!" in pp
    assert not mt.agendar(v)  # já tem
    assert not mt.agendar(str(tmp_path / "foto.jpg"))
    mudo = str(tmp_path / "mudo.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2", "-pix_fmt", "yuv420p", mudo], check=True)
    assert mt.transcrever(mudo, transcrever_fn=_falso)["sem_fala"] is True and "sem fala" in mt.para_prompt(mudo)


def test_marcas_com_trecho_e_audio():
    r = "Gancho.\n[M2 0:01-0:03 áudio]\nDepois disso, tudo mudou. [M1] Olha. [M2 5-8] Sem som."
    ms = mt.marcas(r)
    assert ms[0] == {"id": "M2", "inicio": 1.0, "fim": 3.0, "audio": True, "pos": ms[0]["pos"]}
    assert mt.tirar_marcas(r) == "Gancho.\nDepois disso, tudo mudou. Olha. Sem som."
    mom, sem = mt.momentos_do_roteiro(r, {"M1", "M2"}, [])
    assert [(m["midia"], m.get("inicio"), m.get("audio", False), m["trecho"]) for m in mom] == [
        ("M2", 1.0, True, "Depois disso, tudo mudou."), ("M1", None, False, "Olha."), ("M2", 5.0, False, "Sem som.")]
    assert "COM o áudio original" in mt.uso_sugerido(mom[0]) and "sem o som" in mt.uso_sugerido(mom[2])


def test_seis_modelos_novos_geram_prompt():
    novos = ["historia", "biografia", "negocios", "desastres", "misterios", "ciencia"]
    assert all(k in ds.MODELOS for k in novos)
    for k in novos:
        for fk, f in ds.MODELOS[k]["formatos"].items():
            p = {"tema": "Tema teste", "config": {"modelo": k, "formato": fk}, "fontes": [], "midias": [], "roteiro_base": "anotações"}
            pr = ds.prompt_roteiro(p)
            assert f["nome"].split(" ", 1)[1] in pr and ds.MODELOS[k]["regras"][0][:30] in pr
    assert ds.criar.__defaults__  # criar() usa o 1º formato do modelo


@pytest.fixture
def A():
    import app as _app
    _app.app.config["TESTING"] = True
    return _app


def test_venda_com_video_no_prompt_e_no_editor(A, tmp_path):
    p = vd.criar(A.BASE_DIR, nome="vídeo")
    try:
        pasta = vd.pasta_midias(A.BASE_DIR, p["id"])
        os.makedirs(pasta, exist_ok=True)
        cam = _video(os.path.join(pasta, "demo.mp4"))
        mt.transcrever(cam, transcrever_fn=_falso)
        p["produto"]["titulo"] = "Pote hermético"
        vd.adicionar_midia(p, tipo="video", origem="pc", arquivo="demo.mp4", descricao="demonstração fechando o pote")
        vd.salvar(A.BASE_DIR, p)
        pr = vd.prompt_roteiro(p, base=A.BASE_DIR)
        assert "- M1 (vídeo): demonstração fechando o pote (vídeo de 0:04). O que é dito nele:" in pr
        assert "[M3 0:12-0:25 áudio]" in pr  # a IA sabe que pode tocar com o áudio original
        d = A.app.test_client().get(f"/vendas/{p['id']}/dados").get_json()
        assert d["midias"][0]["transcricao"]["estado"] == "pronta"
        p["roteiro"] = vd.ler_roteiro(json.dumps({"roteiro": "Gancho. [M1 0:01-0:03 áudio] Viu? Fecha de verdade. [M1 0-1] Prático."}), p)
        vd.salvar(A.BASE_DIR, p)
        assert vd.roteiro_para_voz(p) == "Gancho. Viu? Fecha de verdade. Prático."
        job_id = "mv-job"
        os.makedirs(A._job_dir(job_id), exist_ok=True)
        job = {"job_id": job_id, "providers": ["pexels"], "media_library": []}
        A._ligar_projeto(job, "venda", p["id"])
        bloco = A._com_produto(job, "P")
        assert "Não vaza nada!" in bloco and "COM o áudio original (corte)" in bloco and '"midia": \\"<ID>\\"'.replace("\\", "") in bloco.replace("\\", "")
        # (a) sem som, sob a narração: só o pedaço pedido, sem áudio
        segs = [{"provider": "produto", "query": "M1@1-2.5", "start": 0, "end": 2}]
        assert A._aplicar_produto(job, segs) == 1
        corte = segs[0]["override_source"]["value"]
        assert corte != cam and corte.endswith("_mudo.mp4")
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", corte],
                                         capture_output=True, text=True).stdout)
        assert abs(float(info["format"]["duration"]) - 1.5) < 0.2 and not any(s["codec_type"] == "audio" for s in info["streams"])
        # (b) com o áudio original: o corte já sai resolvido (e não vai pro YouTube)
        import prompt_builder as pb
        r = pb.parse_ai_response(json.dumps({"segments": [{"start": 0, "end": 5, "provider": "pexels", "query": "kitchen"}],
                                             "cutaway_suggestions": [{"insertion_point": 2.0, "description": "M1 — demonstração", "audio_mode": "pause",
                                                                      "midia": "M1", "inicio": "0:01", "fim": 3}]}), total_duration=5)
        assert r.cutaway_suggestions[0]["midia"] == "M1" and r.cutaway_suggestions[0]["inicio"] == "0:01"
        job["cutaway_suggestions"] = [dict(r.cutaway_suggestions[0], id="c1", resolved_path=None)]
        assert A._aplicar_cortes_do_projeto(job) == 1
        c = job["cutaway_suggestions"][0]
        assert c["do_projeto"] == "M1" and c["resolved_path"].endswith("_1.0_3.0.mp4") and os.path.isfile(c["resolved_path"])
        assert not [it for it in A._youtube_itens_sincronizar(job) if it.get("tipo") == "corte"]
    finally:
        vd.excluir(A.BASE_DIR, p["id"])
