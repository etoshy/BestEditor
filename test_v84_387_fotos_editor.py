"""v84_387: 📸 Coisas do roteiro no Estúdio — IA acha, Brave manda, substitui a cena ou vira camada."""
import base64
import io
import os

import fotos_editor as FE


def _png():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def _job():
    return {"job_id": "jfe1", "total_duration": 30.0,
            "segments": [{"start": 0, "end": 5, "text": "Immanuel Kant nasceu em Königsberg."},
                         {"start": 5, "end": 12, "text": "Ele escreveu a Crítica da Razão Pura."}],
            "pending_segments": [{"start": 0, "end": 4, "provider": "pexels"}, {"start": 4, "end": 9, "provider": "pexels"},
                                 {"start": 9, "end": 14, "provider": "pexels", "override_source": {"source": "local_file", "value": "/x.jpg"}}],
            "media_library": [], "overlays": []}


def test_analisar_le_a_resposta_da_ia():
    vistos = {}

    def chamar(rec, system, conteudo, **kw):
        vistos.update(rec=rec, conteudo=conteudo, schema=kw.get("schema"))
        return {"itens": [{"nome": "Immanuel Kant", "tipo": "pessoa", "busca": "Immanuel Kant portrait", "start": 0, "end": 2,
                           "frase": "Immanuel Kant", "por_que": "rosto"},
                          {"nome": "Immanuel Kant", "tipo": "pessoa", "busca": "dup", "start": 1, "end": 2, "frase": "", "por_que": ""},
                          {"nome": "Crítica da Razão Pura", "tipo": "obra", "busca": "Critique of Pure Reason 1781", "start": 5, "end": 12,
                           "frase": "", "por_que": ""}]}
    itens = FE.analisar(_job(), chamar=chamar)
    assert [i["nome"] for i in itens] == ["Immanuel Kant", "Crítica da Razão Pura"]
    assert itens[0]["end"] - itens[0]["start"] >= 3.0  # janela mínima
    assert "[0.0–5.0] Immanuel Kant" in vistos["conteudo"] and vistos["rec"] == "buscas"


def test_substituir_camada_e_desfazer():
    job = _job()
    item = {"id": "it1", "start": 3.0, "end": 9.5}
    feitos = FE.substituir(job, item, ["/a.jpg", "/b.jpg"])
    assert [f["trecho"] for f in feitos] == [0, 1] or [f["trecho"] for f in feitos] == [1, 2]
    i = feitos[0]["trecho"]
    assert job["pending_segments"][i]["override_source"]["value"] == "/a.jpg" and job["pending_segments"][i]["media_type"] == "image"
    for f in feitos:
        FE.desfazer(job, f)
    assert "override_source" not in job["pending_segments"][0] or job["pending_segments"][0]["override_source"] is None
    assert job["pending_segments"][2]["override_source"]["value"] == "/x.jpg"  # o que já tinha volta
    cf = FE.camada(job, {"id": "it2", "start": 5, "end": 11}, ["/c.jpg", "/d.jpg"], "centro")
    assert len(job["overlays"]) == 2 and job["overlays"][0]["position"] == "center" and job["overlays"][1]["start"] == 8.0
    FE.desfazer(job, cf[0])
    assert len(job["overlays"]) == 1


def test_rotas_link_e_aplicar(monkeypatch, tmp_path):
    import app as A
    job = _job()
    job["fotos_editor"] = {"itens": [{"id": "it1", "nome": "Kant", "tipo": "pessoa", "busca": "Kant", "start": 0, "end": 4}]}
    monkeypatch.setitem(A._JOBS, "jfe1", job)
    monkeypatch.setattr(A, "_job_dir", lambda j: str(tmp_path))
    monkeypatch.setattr(A, "_save_state", lambda j: None)
    import fotos_editor
    c = A.app.test_client()
    r = c.post("/job/jfe1/fotos-editor/link", data='{"pergunta": "it1", "url": "https://x/k.png", "dados_b64": "%s"}' % _png(),
               content_type="text/plain", headers={"Origin": "https://www.google.com"})  # vem da guia do Google
    assert r.status_code == 200 and r.headers.get("Access-Control-Allow-Origin") == "*"
    st = c.get("/job/jfe1/fotos-editor/estado").get_json()
    bib = st["fotos"]["it1"][0]["bib"]
    assert c.get(f"/job/jfe1/fotos-editor/foto/{bib}").status_code == 200
    d = c.post("/job/jfe1/fotos-editor/aplicar", json={"item": "it1", "fotos": [bib], "modo": "substituir"}).get_json()
    assert d["ok"] and job["pending_segments"][0]["override_source"]["source"] == "local_file"
    fid = d["feitos"]["it1"][0]["id"]
    c.post("/job/jfe1/fotos-editor/desfazer", json={"id": fid})
    assert not job["pending_segments"][0].get("override_source")
    assert "Coisas do roteiro" in c.get("/job/jfe1/fotos-editor").get_data(as_text=True)


def test_userscript_manda_pro_estudio():
    import navegador_imagens as nav
    assert "/fotos-editor" in nav.script() and "2.7.0" in nav.script()
    d = nav.destino("http://localhost:5050", "jfe1", "it1", rotulo="Kant", modo="estudio")
    import json
    assert json.loads(base64.urlsafe_b64decode(d + "==").decode())["m"] == "estudio"


def test_auto_ia_monta_depois_da_transcricao(monkeypatch):
    import app as A
    import ia_rotas
    job = {"job_id": "jauto", "status": "aguardando_json", "prompt": "PROMPT", "auto_ia_montar": True}
    monkeypatch.setitem(A._JOBS, "jauto", job)
    monkeypatch.setattr(A, "_save_state", lambda j: None)
    monkeypatch.setattr(ia_rotas, "gerar_roteiro", lambda p: '[{"start":0,"end":5,"provider":"pexels","query":"x"}]')
    aplicado = []
    monkeypatch.setattr(A, "_aplicar_resposta_ia", lambda jid, t: aplicado.append((jid, t)) or job.update(status="editando"))
    A._auto_ia_montar("jauto", esperar_previas=True)
    assert aplicado and aplicado[0][0] == "jauto"
    job2 = {"job_id": "jsem", "status": "aguardando_json", "prompt": "P", "auto_ia_montar": False}
    monkeypatch.setitem(A._JOBS, "jsem", job2)
    A._auto_ia_montar("jsem")
    assert len(aplicado) == 1  # sem a opção, para no prompt como sempre


def test_auto_ia_sem_ia_fica_no_prompt(monkeypatch):
    import app as A
    import ia_rotas
    job = {"job_id": "jx", "status": "aguardando_json", "prompt": "P", "auto_ia_montar": True}
    monkeypatch.setitem(A._JOBS, "jx", job)
    monkeypatch.setattr(A, "_save_state", lambda j: None)
    monkeypatch.setattr(A, "_avisar_fim", lambda *a, **k: None)

    def falha(p):
        raise RuntimeError("401 chave")
    monkeypatch.setattr(ia_rotas, "gerar_roteiro", falha)
    A._auto_ia_montar("jx")
    assert job["status"] == "aguardando_json" and "não montou sozinha" in job["fase"]
