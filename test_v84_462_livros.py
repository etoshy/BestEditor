import json
import os

import pytest

import dossies as ds
import livros_afiliado as la

ROT = ("Imagine acordar todo dia e empurrar a mesma pedra.\n\nCamus chamou isso de absurdo. A vida não tem sentido dado, "
       "e mesmo assim a gente continua.\n\nO segredo, diz ele, é imaginar Sísifo feliz.\n\nAs fontes estão na descrição. "
       "Comenta aqui embaixo: você vive no absurdo?")


@pytest.fixture
def proj(tmp_path):
    p = ds.criar(str(tmp_path), "Absurdo", "filosofia") if hasattr(ds, "criar") else None
    p["resultado"] = ds.ler_resultado(json.dumps({"titulos": ["Você Vive no Absurdo?"], "descricao": "Um vídeo sobre Camus.",
                                                  "capitulos": [], "roteiro": ROT}), p)
    p["resultado"]["fontes_web"] = {"itens": [{"referencia": "Camus — O Mito de Sísifo", "url": "https://x.edu/c"}]}
    ds.salvar(str(tmp_path), p)
    return str(tmp_path), p


def test_com_tag():
    assert la.com_tag("https://www.amazon.com.br/dp/123?th=1", "derivan-20") == "https://www.amazon.com.br/dp/123?th=1&tag=derivan-20"
    assert la.com_tag("https://www.amazon.com.br/dp/123?tag=outro-20", "derivan-20").endswith("tag=outro-20")
    assert la.com_tag("https://amzn.to/abc", "derivan-20") == "https://amzn.to/abc"


def test_fluxo(proj, monkeypatch):
    base, p = proj
    # 1. sugestões (e "não vale a pena")
    nada = la.sugerir(p, chamar=lambda *a, **k: {"vale_a_pena": False, "motivo": "vídeo de humor", "livros": []})
    assert nada["sugeridos"] == [] and not nada["vale_a_pena"] and "humor" in nada["motivo"]
    lv = la.sugerir(p, chamar=lambda *a, **k: {"vale_a_pena": True, "motivo": "", "livros": [
        {"titulo": "O Mito de Sísifo", "autor": "Albert Camus", "por_que": "é de onde vem a ideia",
         "onde": "Camus chamou isso de absurdo."}]})
    assert lv["sugeridos"][0]["busca"].startswith("https://www.amazon.com.br/s?k=O+Mito")
    # 2. o link → dados + capa
    html = '<span id="productTitle">O Mito de Sísifo: Ensaio sobre o absurdo</span><div id="bylineInfo"><a>Albert Camus</a> (Autor)</div>'

    def baixar_capa(url, pasta, nome):
        os.makedirs(pasta, exist_ok=True)
        cam = os.path.join(pasta, nome + ".jpg")
        open(cam, "wb").write(b"jpg")
        return cam, "foto"
    livro = la.adicionar(base, p, "https://www.amazon.com.br/dp/8501?x=1", 0, baixar_capa=baixar_capa,
                         baixar=lambda u: (html, u), ler=lambda h, u: {"titulo": "O Mito de Sísifo: Ensaio sobre o absurdo",
                                                                       "preco": "R$ 39,90", "imagens": ["https://m.media-amazon.com/c.jpg"]})
    assert livro["titulo_curto"] == "O Mito de Sísifo" and livro["autor"] == "Albert Camus" and livro["capa"].startswith("I")
    # 3. adaptar: a menção com a capa + a linha do fim
    capa = livro["capa"]

    def ia_adaptar(*a, **k):
        return {"trocas": [{"de": "Camus chamou isso de absurdo.", "para": f"[{capa}] Camus chamou isso de absurdo, em O Mito de Sísifo.",
                            "livro": "O Mito de Sísifo"},
                           {"de": "As fontes estão na descrição.", "para": "As fontes e o livro que eu citei estão na descrição."}]}
    novo = la.adaptar(p, chamar=ia_adaptar)
    p["resultado"] = ds.roteiro_editado(p, novo)
    la.estado(p)["ativo"] = True
    R = p["resultado"]
    assert "em O Mito de Sísifo" in R["roteiro_final"] and f"[{capa}]" not in R["roteiro_final"]
    assert any(m["midia"] == capa for m in R["momentos"])  # a capa entra na tela na menção
    assert R["roteiro_sem_livros"] == ROT and R["fontes_web"]  # a versão sem livros e as fontes sobreviveram
    d = ds.descricao_completa(p)
    assert d.startswith("📖 O livro citado neste vídeo:\n- O Mito de Sísifo — Albert Camus: https://www.amazon.com.br/dp/8501")
    assert la.AVISO in d and "x.edu/c" in d
    assert "O livro que eu citei" in la.comentario_fixado(R)
    la.estado(p)["destino"] = "comentario"
    assert "📖" not in ds.descricao_completa(p) and la.comentario_fixado(p["resultado"])
    la.estado(p)["destino"] = "descricao"
    assert la.comentario_fixado(p["resultado"]) == ""
    # 4. voltar pra versão SEM livros: sem menção e sem link
    p["resultado"] = ds.roteiro_editado(p, p["resultado"]["roteiro_sem_livros"])
    la.estado(p)["ativo"] = False
    assert "O Mito de Sísifo" not in p["resultado"]["roteiro_final"] and "📖" not in ds.descricao_completa(p)
    assert p["resultado"]["roteiro_com_livros"]  # dá pra voltar


def test_rotas(proj, monkeypatch):
    import app as A
    A.app.config["TESTING"] = True
    base, p = proj
    monkeypatch.setattr(ds, "carregar", lambda b, pid: ds.__dict__["_carregar_real"](base, pid) if "_carregar_real" in ds.__dict__ else p)
    monkeypatch.setattr(ds, "salvar", lambda b, q: None)
    monkeypatch.setattr(la, "sugerir", lambda q, chamar=None: la.estado(q).update(sugeridos=[], motivo="x") or la.estado(q))
    c = A.app.test_client()
    r = c.post(f"/modelos-video/{p['id']}/livros/sugerir", json={})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert c.post(f"/modelos-video/{p['id']}/livros/destino", json={"destino": "xx"}).status_code == 400
    assert c.post(f"/modelos-video/{p['id']}/livros/versao", json={"versao": "com"}).status_code == 400  # ainda não adaptou
