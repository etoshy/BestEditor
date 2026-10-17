import os
import shutil

import fotos_roteiro as fr


def test_pergunta_de_site():
    assert fr.eh_de_site({"tipo": "documento", "pergunta": "Você tem print da página da recompensa que saiu do ar?"})
    assert fr.eh_de_site({"tipo": "site"})
    assert not fr.eh_de_site({"tipo": "pessoa", "pergunta": "Você tem foto do Robert Schultz?"})


def test_rota_site_guarda_print_e_link(monkeypatch):
    import app as a
    import dossies as ds
    import dp_editorial
    from PIL import Image
    p = ds.criar(a.BASE_DIR, "teste site")
    tmp = os.path.join(a.BASE_DIR, "dossies", p["id"], "_t.png")
    try:
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        Image.new("RGB", (20, 20)).save(tmp)
        monkeypatch.setattr(dp_editorial, "capturar_print", lambda url, pasta, timeout_ms=0: tmp)
        p["fotos_roteiro"] = {"perguntas": [{"id": "P1", "tipo": "site", "alvo": "Página da recompensa", "pergunta": "x"}]}
        ds.salvar(a.BASE_DIR, p)
        url = "https://web.archive.org/web/2015/http://www.frauke-liebs.de/belohnung"
        d = a.app.test_client().post(f"/modelos-video/{p['id']}/fotos-roteiro/site", json={"url": url, "pergunta": "P1"}).get_json()
        assert d["ok"] and d["dominio"] == "www.frauke-liebs.de"
        m = next(x for x in ds.carregar(a.BASE_DIR, p["id"])["midias"] if x["id"] == d["midia"]["id"])
        assert m["site_url"] == url and m["pergunta"] == "P1" and m["tipo"] == "foto"
    finally:
        shutil.rmtree(os.path.join(a.BASE_DIR, "dossies", p["id"]), ignore_errors=True)
