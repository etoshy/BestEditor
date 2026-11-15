"""v84_393: 🃏 no Estúdio — liga/desliga o cartão e busca de novo as cenas que viraram cartão ou ficaram sem mídia."""
import app as A
import ia_servico


def _job():
    pend = [
        {"start": 0, "end": 3, "query": "a", "provider": "pexels", "media_type": "video", "override_source": None},
        {"start": 3, "end": 6, "query": "b", "provider": "pexels", "media_type": "image", "cartao": {"texto": "x"},
         "override_source": {"source": "local_file", "value": "/x.png", "kind": "image", "cartao": True}},
        {"start": 6, "end": 9, "query": "c", "provider": "pixabay", "media_type": "video", "override_source": None},
        {"start": 9, "end": 12, "query": "d", "provider": "pexels", "media_type": "video",
         "override_source": {"source": "local_file", "value": "/meu.mp4", "kind": "video"}},
    ]
    pv = [{"ok": True}, {"ok": True, "cartao": True, "provider": "cartao"}, {"ok": False, "error": "nada"}, {"ok": True}]
    return {"job_id": "tfalt", "status": "pronto_para_editar", "pending_segments": pend, "segment_previews": pv,
            "providers": ["pexels", "pixabay"], "segments": [], "destaques": [{"origem": "cartao", "trecho": 1}]}


def test_conta_e_rebusca(monkeypatch):
    job = _job()
    monkeypatch.setitem(A._JOBS, "tfalt", job)
    monkeypatch.setattr(A, "_save_state", lambda *a, **k: None)
    chamado = {}
    monkeypatch.setattr(A, "_fetch_previews", lambda jid, j, segs, retomar=False: chamado.update(n=len(segs), r=retomar))
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: False)
    c = A.app.test_client()
    d = c.get("/job/tfalt/cenas-faltaram").get_json()
    assert d["cartoes"] == 1 and d["sem_midia"] == 1
    r = c.post("/job/tfalt/cenas-faltaram", json={"buscar": True, "quais": "tudo", "fontes": ["pixabay"]}).get_json()
    assert r["cenas"] == 2 and r["cartoes"] == 1 and chamado["r"]
    p = job["pending_segments"]
    assert not p[1]["override_source"] and "cartao" not in p[1] and p[1]["provider"] == "pixabay"
    assert p[3]["override_source"]["value"] == "/meu.mp4"  # o que você escolheu fica
    assert job["segment_previews"][1] is None and job["segment_previews"][2] is None and job["segment_previews"][0]["ok"]
    assert not job["destaques"]


def test_liga_desliga_cartao(monkeypatch):
    monkeypatch.setitem(A._JOBS, "tfalt", _job())
    salvo = {}
    monkeypatch.setattr(ia_servico, "salvar_config", lambda n: salvo.update(n))
    d = A.app.test_client().post("/job/tfalt/cenas-faltaram", json={"cartao": False}).get_json()
    assert d["ok"] and salvo == {"recursos": {"cartao": False}}


def test_botao_no_estudio(monkeypatch):
    job = _job()
    html = A.app.jinja_env.from_string("{% set _fi = faltaram_info(job) %}{{ _fi.cartoes }}/{{ _fi.sem_midia }}").render(job=job)
    assert html == "1/1"
    src = open("templates/estudio.html", encoding="utf-8").read()
    assert 'id="btnFaltaram"' in src and 'id="faltaramCartao"' in src
