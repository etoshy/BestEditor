"""🕵️ v84_141: ligar o projeto no editor e encaixar as fotos/vídeos reais nos momentos do roteiro."""
import json
import os

import pytest

import dossies as ds


@pytest.fixture
def cena(monkeypatch):
    import app as A
    from PIL import Image
    base = A.BASE_DIR
    p = ds.criar(base, "Teste encaixe")
    os.makedirs(ds.pasta_midias(base, p["id"]), exist_ok=True)
    for n in ("a.jpg", "b.jpg"):
        Image.new("RGB", (32, 32)).save(os.path.join(ds.pasta_midias(base, p["id"]), n))
    ds.adicionar_midia(p, tipo="foto", arquivo="a.jpg", descricao="John List")
    ds.adicionar_midia(p, tipo="foto", arquivo="b.jpg", descricao="a casa")
    rot = "Em 1971 tudo mudou. [I1] John List matou a família inteira.\n\n[I2] A casa ficou vazia por semanas."
    p["resultado"] = ds.ler_resultado(json.dumps({"roteiro": rot, "titulos": ["t"]}), p)
    ds.salvar(base, p)
    frases = ["Em 1971 tudo mudou.", "John List matou a família inteira.", "A casa ficou vazia por semanas."]
    words, t = [], 0.0
    for f in frases:
        for w in f.split():
            words.append({"word": w, "start": t, "end": t + 0.4})
            t += 0.5
    jid = "teste_encaixe_" + p["id"]
    pend = [{"start": 0.0, "end": 2.0, "provider": "runpod", "query": "x", "media_type": "image",
             "override_source": {"source": "local_file", "value": "/tmp/ia1.png", "kind": "image"}},
            {"start": 2.0, "end": 5.0, "provider": "adiado", "query": "murder family 1971", "media_type": "video"},
            {"start": 5.0, "end": t + 1, "provider": "pexels", "query": "empty house", "media_type": "video",
             "override_source": {"source": "local_file", "value": "/tmp/escolhida.mp4", "kind": "video"}}]
    A._JOBS[jid] = {"job_id": jid, "status": "pronto_para_editar", "word_timestamps": words, "pending_segments": pend,
                    "segment_previews": [None] * 3, "providers": ["pexels"], "total_duration": t + 1}
    monkeypatch.setattr(A, "_fetch_previews", lambda *a, **k: None)
    monkeypatch.setattr(A, "_save_state", lambda *a, **k: None)
    yield A, jid, p
    A._JOBS.pop(jid, None)
    ds.excluir(base, p["id"])


def test_ligar_e_encaixar(cena):
    A, jid, p = cena
    c = A.app.test_client()
    with pytest.raises(ValueError):
        A._encaixar_projeto(jid)  # sem projeto ligado
    d = c.post(f"/job/{jid}/ligar-projeto", json={"projeto": f"dossie:{p['id']}"}).get_json()
    assert d["ok"] and d["tipo"] == "dossie" and d["momentos"] == 2
    d = c.post(f"/job/{jid}/encaixar-projeto", json={}).get_json()
    assert d["trocadas"] == 1  # o trecho escolhido à mão (pexels) fica
    pend = A._JOBS[jid]["pending_segments"]
    assert pend[1]["provider"] == "material" and pend[1]["override_source"]["value"].endswith("a.jpg")
    assert pend[2]["provider"] == "pexels"
    d = c.post(f"/job/{jid}/encaixar-projeto", json={"modo": "tudo"}).get_json()
    assert d["trocadas"] == 1 and pend[2]["override_source"]["value"].endswith("b.jpg")
    d = c.post(f"/job/{jid}/encaixar-projeto", json={"desfazer": True}).get_json()
    assert d["voltaram"] == 2 and pend[1]["provider"] == "adiado" and pend[2]["override_source"]["value"] == "/tmp/escolhida.mp4"
    assert c.post(f"/job/{jid}/ligar-projeto", json={"projeto": ""}).get_json()["tipo"] == ""
