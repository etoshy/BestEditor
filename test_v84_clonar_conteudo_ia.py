"""📑 v84_146 clonar projeto · 🤖 v84_145 selo nas cenas de IA."""
import json
import os

import conteudo_ia as ci
import dossies as ds


def test_selos_nos_trechos_de_ia(tmp_path):
    job = {"language": "de", "pending_segments": [
        {"start": 0, "end": 2, "provider": "runpod"}, {"start": 2, "end": 3.5, "provider": "runpod"},
        {"start": 3.5, "end": 5, "provider": "pexels"}, {"start": 5, "end": 6, "provider": "flow"}],
        "overlays": [{"id": "x", "media_type": "text", "text": "meu", "start": 0, "end": 1}]}
    assert ci.sincronizar(job, str(tmp_path)) == 2
    s = [o for o in job["overlays"] if o.get("origem") == "selo_ia"]
    assert [(o["start"], o["end"]) for o in s] == [(0.0, 3.5), (5.0, 6.0)] and s[0]["text"] == "Simulation: KI-generierter Inhalt"
    job["pending_segments"][0]["provider"] = "material"
    ci.sincronizar(job, str(tmp_path))
    assert [(o["start"], o["end"]) for o in job["overlays"] if o.get("origem") == "selo_ia"] == [(2.0, 3.5), (5.0, 6.0)]
    job["selo_ia"] = {"ativo": False}
    assert ci.sincronizar(job, str(tmp_path)) == 0 and len(job["overlays"]) == 1
    ci.salvar_preset(str(tmp_path), "R", "Reconstituição — IA")
    meu = ci.presets_meus(str(tmp_path))[0]
    assert ci.texto({"language": "pt", "selo_ia": {"preset": meu["id"]}}, str(tmp_path)) == "Reconstituição — IA"
    assert ci.texto({"language": "ja"}) == "Simulation: AI-generated content"


def test_clonar_dossie_e_job(tmp_path):
    import clonar
    base = str(tmp_path)
    p = ds.criar(base, "Unabomber")
    os.makedirs(ds.pasta_midias(base, p["id"]), exist_ok=True)
    open(os.path.join(ds.pasta_midias(base, p["id"]), "a.jpg"), "wb").write(b"x")
    ds.adicionar_midia(p, tipo="foto", arquivo="a.jpg", descricao="Ted")
    ds.salvar(base, p)
    r = clonar.clonar_dossie(base, p["id"], "ângulo psicológico")
    q = ds.carregar(base, r["id"])
    assert q["apelido"] == "ângulo psicológico" and q["clonado_de"] == p["id"] and ds.caminho_midia(base, q, q["midias"][0])
    q["tema"] = "mudou"
    ds.salvar(base, q)
    assert ds.carregar(base, p["id"])["tema"] == "Unabomber"
    jobs, jd = {}, lambda j: os.path.join(base, "jobs", j)
    os.makedirs(jd("j1"), exist_ok=True)
    open(os.path.join(jd("j1"), "narr.wav"), "wb").write(b"a")
    open(os.path.join(jd("j1"), "final.mp4"), "wb").write(b"v")
    jobs["j1"] = {"job_id": "j1", "status": "concluido", "audio_path": os.path.join(jd("j1"), "narr.wav"),
                  "output_path": os.path.join(jd("j1"), "final.mp4"), "nome_projeto": "Una",
                  "pending_segments": [{"override_source": {"value": os.path.join(jd("j1"), "narr.wav")}}]}
    salvos = []
    r = clonar.clonar_job(jobs, jd, salvos.append, "j1", "")
    n = jobs[r["id"]]
    assert n["audio_path"] == os.path.join(jd(r["id"]), "narr.wav") and os.path.exists(n["audio_path"])
    assert n["pending_segments"][0]["override_source"]["value"].startswith(jd(r["id"]))
    assert "output_path" not in n and not os.path.exists(os.path.join(jd(r["id"]), "final.mp4"))
    assert n["nome_projeto"] == "Una 2" and n["status"] == "pronto_para_editar" and salvos == [r["id"]]
