"""🤖 v84_145: selo "Simulação: conteúdo gerado por IA" nas cenas de IA."""
import conteudo_ia as ci


def test_selos_nos_trechos_de_ia_no_idioma_do_video(tmp_path):
    job = {"language": "de", "pending_segments": [
        {"start": 0, "end": 2, "provider": "runpod"}, {"start": 2, "end": 3.5, "provider": "runpod"},
        {"start": 3.5, "end": 5, "provider": "pexels"}, {"start": 5, "end": 6, "provider": "flow"}],
        "overlays": [{"id": "x", "media_type": "text", "text": "meu", "start": 0, "end": 1}]}
    assert ci.sincronizar(job, str(tmp_path)) == 2
    s = [o for o in job["overlays"] if o.get("origem") == "selo_ia"]
    assert [(o["start"], o["end"]) for o in s] == [(0.0, 3.5), (5.0, 6.0)]
    assert s[0]["text"] == "Simulation: KI-generierter Inhalt" and s[0]["style"]["position"] == "top-right"
    assert any(o["id"] == "x" for o in job["overlays"])  # overlay do usuário fica
    job["pending_segments"][0]["provider"] = "material"  # trocou por foto real: o selo daquele trecho some
    ci.sincronizar(job, str(tmp_path))
    assert [(o["start"], o["end"]) for o in job["overlays"] if o.get("origem") == "selo_ia"] == [(2.0, 3.5), (5.0, 6.0)]
    job["selo_ia"] = {"ativo": False}
    assert ci.sincronizar(job, str(tmp_path)) == 0 and len(job["overlays"]) == 1


def test_presets_meus_e_texto_proprio(tmp_path):
    base = str(tmp_path)
    ci.salvar_preset(base, "Recon", "Reconstituição — IA")
    meu = ci.presets_meus(base)[0]
    job = {"language": "pt", "selo_ia": {"preset": meu["id"]}, "pending_segments": []}
    assert ci.texto(job, base) == "Reconstituição — IA"
    job["selo_ia"]["texto"] = "Outro texto"
    assert ci.texto(job, base) == "Outro texto"
    assert ci.texto({"language": "ja"}, base) == "Simulation: AI-generated content"  # idioma sem tradução: inglês
    assert ci.apagar_preset(base, meu["id"]) == []


def test_rota(tmp_path, monkeypatch):
    import app as A
    jid = "teste_ci"
    A._JOBS[jid] = {"job_id": jid, "language": "pt", "pending_segments": [{"start": 0, "end": 4, "provider": "runpod"}], "overlays": []}
    monkeypatch.setattr(A, "_save_state", lambda *a, **k: None)
    try:
        c = A.app.test_client()
        d = c.get(f"/job/{jid}/conteudo-ia").get_json()
        assert d["texto"] == "Simulação: conteúdo gerado por IA" and d["cenas_ia"] == 1
        d = c.post(f"/job/{jid}/conteudo-ia", json={"posicao": "bottom-left", "preset": "recriacao", "tamanho": 3}).get_json()
        assert d["selos"] == 1 and A._JOBS[jid]["overlays"][0]["style"]["position"] == "bottom-left"
        assert A._JOBS[jid]["overlays"][0]["text"] == "Recriação gerada por IA"
    finally:
        A._JOBS.pop(jid, None)
