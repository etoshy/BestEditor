"""v84_169: 🧵 o título é a promessa (abertura, pontes, fechamento), 🔁 frase repetida sai sozinha, pedido do autor no topo
da revisão e 📐 roteiro exemplo pra modelar (só a estrutura)."""
import json

import dossies as ds
import metodo_roteiro as mr
import revisao_roteiro as rv

REP = ("Kiefernreinbestände gelten als besonders brandanfällig; deshalb sollen sie in Mischwälder umgebaut werden. "
       "Kiefernreinbestände sollen deshalb nach und nach in Mischwälder umgebaut werden [I4]. Das dauert Jahrzehnte.")


def _p(**cfg):
    p = {"id": "abcdef0123", "tema": "Brandenburg: O Pior Lugar da Alemanha", "roteiro_base": "Wespen und Nutrias.",
         "fontes": [], "midias": [], "config": dict(ds.CONFIG_PADRAO, idioma="de", minutos=12, **cfg)}
    return p


def test_titulo_vira_promessa_no_prompt():
    t = ds.prompt_roteiro(_p())
    assert "O TÍTULO É A PROMESSA" in t and "Brandenburg: O Pior Lugar da Alemanha" in t
    assert "TRANSIÇÕES" in t and "RESPONDA" in t
    t2 = ds.prompt_roteiro(_p(titulo="Brandenburg: das gefährlichste Bundesland?"))
    assert "“Brandenburg: das gefährlichste Bundesland?”" in t2


def test_frase_repetida_sai():
    texto, tiradas = mr.tirar_repeticoes(REP)
    assert len(tiradas) == 1 and "nach und nach" not in texto and "[I4]" in texto  # a marca fica
    assert mr.tirar_repeticoes("Das Gesetz kam 1937 in Kraft und galt im ganzen Land. Das Gesetz kam 1970 in Kraft und galt im ganzen Land.")[1] == []
    d = {"roteiro": REP, "titulos": ["x"]}
    r = ds.ler_resultado(json.dumps(d), _p())
    assert "nach und nach" not in r["roteiro"] and any("repetida" in a for a in r["avisos"])
    ap = rv.aplicar(REP, json.dumps({"trocas": []}))
    assert any(x["motivo"] == "repetição (site)" for x in ap["aplicadas"])


def test_revisao_pedido_no_topo_e_fio_condutor():
    rot = "Wespen kommen. " * 30 + "\n\n" + "Nutrias graben. " * 30
    t = rv.prompt(rot, "alemão", tema="Brandenburg: O Pior Lugar da Alemanha", foco="o título não é abordado", modo="titulo")
    assert t.index("PEDIDO DO AUTOR") < t.index("O que melhorar") and "FIO CONDUTOR" in t and "FOCO DESTA REVISÃO" in t
    assert "A ABERTURA não apresenta a tese" in t
    assert "titulo" in rv.MODOS


def test_roteiro_exemplo_modelar():
    t = ds.prompt_roteiro(_p(referencia="Existe um lugar da Amazônia onde as correntes arrastam casas inteiras.", referencia_modo="modelar"))
    assert "modele a ESTRUTURA" in t and "Amazônia" in t
    t = ds.prompt_roteiro(_p(referencia="abc", referencia_modo="inspirar"))
    assert "inspiração, não molde" in t
    assert ds._contexto_partes(_p(referencia="R" * 20000, referencia_modo="modelar"))["referencia"] == "R" * 9000


def test_rota_link_do_exemplo(monkeypatch):
    import app as a
    import roteiros_yt as ry
    monkeypatch.setattr(ry, "extrair_transcricao", lambda url, pasta, on_log=None: {"titulo": "Rio Madeira", "segmentos": []})
    monkeypatch.setattr(ry, "texto_da_transcricao", lambda tr, com_tempo=False: "Existe um lugar da Amazônia…")
    c = a.app.test_client()
    p = ds.criar(a.BASE_DIR, "Teste exemplo")
    try:
        d = c.post(f"/modelos-video/{p['id']}/referencia/link", json={"url": "https://youtu.be/abcdefghijk"}).get_json()
        import time
        import tarefas_bg
        for _ in range(50):
            t = tarefas_bg.pegar(d["tarefa"])
            if t and t["status"] != "rodando":
                break
            time.sleep(0.1)
        assert t["status"] == "pronto" and ds.carregar(a.BASE_DIR, p["id"])["config"]["referencia"].startswith("Existe um lugar")
        r = c.post(f"/modelos-video/{p['id']}/config", json={"referencia_modo": "modelar", "titulo": "Brandenburg?"}).get_json()
        assert r["config"]["referencia_modo"] == "modelar" and r["config"]["titulo"] == "Brandenburg?"
    finally:
        ds.excluir(a.BASE_DIR, p["id"])
