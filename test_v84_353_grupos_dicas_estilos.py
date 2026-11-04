"""v84_353: 💡 o texto antes do link na mesma linha = dica pra IA (se não for grupo/canal conhecido); 📂 vários termos por grupo
separados por vírgula (sem ligar pra maiúscula/acento); 🤖 5 estilos (@ + legenda) sugeridos pela IA pelo nicho do canal."""
import acabamento_extra as AX
import curtos as CT
import curtos_comentario as CC
import curtos_rotas as CR
from test_v84_320_lote_por_etapa import _app

LISTA = """Radical:
Eclipse com skate: https://www.instagram.com/reel/A1/
https://www.instagram.com/reel/A2/

comida, FOOD, Culinária:
Melancia: https://www.instagram.com/reel/B1/ , https://www.instagram.com/reel/B2/
https://www.instagram.com/reel/B3/

Animais: https://www.instagram.com/reel/C1/"""


def test_dica_e_grupos_pelo_envio(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    rad = cl.post("/curtos/canais/novo", json={"nome": "RadicalWow"}).get_json()["id"]
    food = cl.post("/curtos/canais/novo", json={"nome": "FoodYum2"}).get_json()["id"]
    ani = cl.post("/curtos/canais/novo", json={"nome": "AnimalIQ"}).get_json()["id"]
    cl.post("/curtos/link/grupos", json={"nome": "Radical", "canal_id": rad})
    cl.post("/curtos/link/grupos", json={"nome": "Food", "canal_id": food})   # um dos termos do grupo "comida, FOOD, Culinária"
    cl.post("/curtos/link/grupos", json={"nome": "ANIMAIS", "canal_id": ani})  # maiúscula/acento não importam
    r = cl.post("/curtos/link/novo", json={"link": LISTA}).get_json()
    ps = [CT.carregar(base, i) for i in r["criados"]]
    por_link = {p["link_rapido"]["link"]: p for p in ps}
    a1 = por_link["https://www.instagram.com/reel/A1/"]
    assert a1["canal_id"] == rad and a1["link_rapido"]["dica"] == "Eclipse com skate"
    assert por_link["https://www.instagram.com/reel/A2/"]["canal_id"] == rad and "dica" not in por_link["https://www.instagram.com/reel/A2/"]["link_rapido"]
    b1 = por_link["https://www.instagram.com/reel/B1/"]
    assert b1["config"]["composto"] == 2 and b1["canal_id"] == food and b1["link_rapido"]["dica"] == "Melancia"
    assert por_link["https://www.instagram.com/reel/B3/"]["canal_id"] == food
    assert por_link["https://www.instagram.com/reel/C1/"]["canal_id"] == ani  # 'Animais:' na mesma linha = grupo conhecido
    assert "## WHAT THE CREATOR SAYS THIS VIDEO IS ABOUT" in CC.conteudo_roteiro(base, a1) and "Eclipse com skate" in CC.conteudo_roteiro(base, a1)
    v = next(x for x in cl.get("/curtos/link/estado?por=50").get_json()["videos"] if x["id"] == a1["id"])
    assert v["dica"] == "Eclipse com skate"
    # ligar "x, y" liga cada termo também
    cl.post("/curtos/link/grupos", json={"nome": "Lugares incríveis, places", "canal_id": rad})
    g = {x["chave"]: x["canal_id"] for x in cl.get("/curtos/link/grupos").get_json()["grupos"]}
    assert g.get("lugares incriveis") == rad and g.get("places") == rad


def test_separar_sem_eh_grupo_continua_igual():
    assert CR._separar_grupos("Animais: https://a.com/1") == [("https://a.com/1", "Animais")]  # (sem o verificador: como antes)
    d = {}
    assert CR._separar_grupos("Bichos:\nfofo demais: https://a.com/1", lambda t: False, d) == [("https://a.com/1", "Bichos")]
    assert d == {"https://a.com/1": "fofo demais"}


def test_estilos_pela_ia(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    base = str(tmp_path)
    c = CT.criar_canal(base, "FoodYum2", "")
    c["descricao"] = "comida de rua do mundo"
    CT.salvar_canal(base, c)
    vistos = []

    def ia(rec, sis, prompt, **k):
        vistos.append(prompt)
        e = {"nome": "Feira de rua", "por_que": "cores quentes de comida", "marca": {"fonte": "DP Bebas Neue", "estilo": "caixa",
             "cor": "#ffffff", "estilo_cor": "#E63946", "borda": 4, "borda_cor": "#000000", "maiusculas": True, "italico": False},
             "legenda": {"fonte": "DP Anton", "estilo": "pop", "cor": "#FFFFFF", "cor_ativa": "#FFD60A", "borda": 6, "borda_cor": "#1a1a1a",
                         "maiusculas": True}}
        ruim = {"nome": "Inventada", "por_que": "x", "marca": dict(e["marca"], fonte="Comic Sans", estilo="laser", cor="vermelho"),
                "legenda": dict(e["legenda"], estilo="explosao", borda=99)}
        return {"estilos": [e, ruim]}
    out = AX.sugerir_estilos(base, c["id"], chamar=ia)
    assert "comida de rua do mundo" in vistos[0] and "DP Bebas Neue" in vistos[0] and "caixa" in vistos[0]
    assert out[0]["marca"]["marca_fonte"] == "DP Bebas Neue" and out[0]["marca"]["marca_estilo"] == "caixa"
    assert out[0]["marca"]["marca_cor"] == "#FFFFFF" and out[0]["legenda"]["legenda_cor_ativa"] == "#FFD60A"
    r = out[1]  # o que a IA inventou é descartado/corrigido
    assert r["marca"]["marca_fonte"] == "" and r["marca"]["marca_estilo"] == "" and r["marca"]["marca_cor"] == ""
    assert r["legenda"]["legenda_estilo"] == "classico" and r["legenda"]["legenda_borda"] == 20
    try:
        AX.sugerir_estilos(base, c["id"], chamar=lambda *a, **k: None)
        raise AssertionError
    except CT.CurtoErro as exc:
        assert "sortear" in str(exc)


def test_pagina_tem_os_estilos_ia(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    html = cl.get("/curtos/personalizar").get_data(as_text=True)
    assert 'id="bIaEstilos"' in html and "data-ir-ia" in html and "ehGrupoConhecido" in html
    assert cl.post("/curtos/acabamento/sugerir", json={"canal_id": ""}).status_code in (200, 400)
