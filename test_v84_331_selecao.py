"""v84_331: ☑ marcar vídeos na página de links — exportar (ZIP com JSON + capas, ou só JSON), apagar arquivos ou tirar da lista."""
import io
import json
import os
import zipfile

import curtos as CT
import curtos_rotas as CR
from test_v84_320_lote_por_etapa import _app


def _tres(cl, base, tmp_path):
    ids = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2\nhttps://a.com/3"}).get_json()["criados"]
    for k, pid in enumerate(ids):
        with CT._TRAVA:
            p = CT.carregar(base, pid)
            os.makedirs(os.path.join(CT.pasta(base, pid), "thumbs"), exist_ok=True)
            for j in (1, 2):
                with open(os.path.join(CT.pasta(base, pid), "thumbs", f"p{j}.jpg"), "wb") as f:
                    f.write(b"\xff\xd8jpg")
            p["thumbs"] = [{"arquivo": "p1.jpg", "por_que": "a"}, {"arquivo": "p2.jpg", "por_que": "b"}]
            p["roteiro"] = {"blocos": [{"id": "B1", "fala": f"fala {k}"}], "descricao": "d", "hashtags": ["#x"]}
            if k == 0:
                p["link_rapido"]["escolha"] = {"titulo": "Meu título", "capa": 2}
            CT.salvar(base, p)
    return ids


def test_exportar_marcados_zip_e_json(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    a, b, c = _tres(cl, base, tmp_path)
    r = cl.get(f"/curtos/link/exportar-escolhidos?formato=zip&ids={a},{b}")
    z = zipfile.ZipFile(io.BytesIO(r.data))
    pac = json.loads(z.read("pacote.json"))
    assert pac["total"] == 2 and {v["id"] for v in pac["videos"]} == {a, b}  # o c (não marcado) fica de fora
    va = next(v for v in pac["videos"] if v["id"] == a)
    vb = next(v for v in pac["videos"] if v["id"] == b)
    assert va["titulo_escolhido"] == "Meu título" and va["capa"]["arquivo"] == f"capas/{a}_2.jpg"  # a capa escolhida
    assert [x["arquivo"] for x in vb["prints"]] == [f"capas/{b}_print1.jpg", f"capas/{b}_print2.jpg"]  # sem escolha: os prints
    assert set(z.namelist()) == {"pacote.json", f"capas/{a}_2.jpg", f"capas/{b}_print1.jpg", f"capas/{b}_print2.jpg"}
    j = cl.get(f"/curtos/link/exportar-escolhidos?formato=json&ids={c}").get_json()
    assert j["total"] == 1 and j["videos"][0]["id"] == c
    sem = cl.get("/curtos/link/exportar-escolhidos?formato=json").get_json()  # sem marcar: como antes (só os com escolha)
    assert [v["id"] for v in sem["videos"]] == [a]


def test_apagar_e_tirar_marcados(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    a, b, c = _tres(cl, base, tmp_path)
    CR.TAREFAS[c] = {"rotulo": "x", "inicio": 0, "fim": None}  # rodando: fica de fora
    j = cl.post("/curtos/link/selecionados", json={"ids": [a, c], "acao": "apagar"}).get_json()
    assert j["feitos"] == 1 and "rodando" in j["falhas"][0]
    assert CT.carregar(base, a)["link_rapido"]["apagado"] and not os.path.isdir(os.path.join(CT.pasta(base, a), "thumbs"))
    j = cl.post("/curtos/link/selecionados", json={"ids": [a, b], "acao": "tirar"}).get_json()
    assert j["feitos"] == 2 and {v["id"] for v in j["videos"]} == {c}
    assert not os.path.exists(CT.pasta(base, b))
    assert cl.post("/curtos/link/selecionados", json={"ids": [c], "acao": "xx"}).status_code == 400
    CR.TAREFAS.pop(c, None)
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert "data-selacao" in html and "data-sel=" in html
