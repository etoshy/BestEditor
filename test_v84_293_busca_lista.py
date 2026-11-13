"""🗂 v84_293 — Busca em lista: termos → guias do Google (userscript) ou automático → renomear → zip com lista.txt."""
import base64
import io
import json
import os
import time
import zipfile

import pytest
from flask import Flask

import busca_lista as BL


def _png(cor=(200, 30, 30), tam=(64, 48)):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", tam, cor).save(b, "PNG")
    return b.getvalue()


def _jpg_com_desenho(k):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (120, 90), (k * 40 % 255, 90, 200 - k * 30 % 200))
    d = ImageDraw.Draw(im)
    d.rectangle([k * 10, 5, k * 10 + 30, 60], fill=(255, 255, 255))
    d.ellipse([60 - k * 5, 40, 110, 85], fill=(0, 0, 0))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("BUSCA_LISTA_DIR", str(tmp_path / "bl"))
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    BL.registrar(app, str(tmp_path))
    return app.test_client(), str(tmp_path)


def test_termos_do_texto():
    t = BL.termos_do_texto("1. Archie Karas\n- Binion's Horseshoe 1990s\n\n• Stu Ungar; archie karas\n  craps table  ")
    assert t == ["Archie Karas", "Binion's Horseshoe 1990s", "Stu Ungar", "craps table"]
    assert BL.slug("Binion's Horseshoe — 1990s") == "binion_s_horseshoe_1990s"
    assert BL.nome_limpo("Archie com fichas!.jpg") == "Archie_com_fichas_.jpg" or BL.nome_limpo("Archie com fichas") == "Archie_com_fichas"


def test_guias_link_renomear_zip(cli, monkeypatch):
    c, base = cli
    import navegador_imagens as ni
    abertas = []
    monkeypatch.setattr(ni, "abrir", lambda b, urls, cfg=None, chaves=None, pid="": (abertas.extend(urls), ni.ABAS.setdefault(pid, []).extend(
        {"id": f"g{k}", "chave": ch} for k, ch in enumerate(chaves or [])), {"ok": True, "navegador": "Brave", "confirmadas": list(range(len(urls)))})[-1])
    monkeypatch.setattr(ni, "fechar_terminadas", lambda pid, cfg=None, espera_s=0: {"fechadas": [a["chave"] for a in ni.ABAS.pop(pid, [])], "mantidas": []})
    r = c.post("/busca-lista/novo", data={"titulo": "Archie", "termos": "Archie Karas\nBinion's Horseshoe\nStu Ungar"})
    pid = r.headers["Location"].rsplit("/", 1)[-1]
    assert c.get(f"/busca-lista/{pid}").status_code == 200
    # 🧲 abre 2 guias; o endereço leva o destino do userscript (m: lista)
    j = c.post(f"/busca-lista/{pid}/guias", json={"quantas": 2}).get_json()
    assert j["ok"] and j["abertas"] == 2 and j["faltam"] == 1
    assert "udm=2" in abertas[0] and "#bes=" in abertas[0]
    d = abertas[0].split("#bes=")[1]
    d = json.loads(base64.urlsafe_b64decode(d + "=" * (-len(d) % 4)))
    assert d["m"] == "lista" and d["p"] == pid and d["q"] == BL.termo_id("Archie Karas")
    # o script manda 2 fotos (bytes, como quando o site da imagem barra o servidor) — CORS liberado
    for k in (1, 2):
        r = c.post(f"/busca-lista/{pid}/link", data=json.dumps({"url": f"https://x/{k}.png", "pergunta": d["q"],
                   "dados_b64": base64.b64encode(_png((k * 90, 10, 10))).decode(), "origem": "guia"}), content_type="text/plain")
        assert r.get_json()["ok"], r.get_json()
        assert r.headers.get("Access-Control-Allow-Origin") == "*"
    assert c.post(f"/busca-lista/{pid}/link", json={"url": "https://x/1.png", "pergunta": d["q"]}).get_json().get("repetida")
    c.post(f"/busca-lista/{pid}/guia-feita", json={"pergunta": d["q"], "enviadas": 2})
    e = c.get(f"/busca-lista/{pid}/estado").get_json()
    its = e["projeto"]["itens"]
    assert [i["arq"] for i in its] == ["archie_karas_01.png", "archie_karas_02.png"]
    assert e["termos"][0]["fotos"] == 2 and e["termos"][1]["guia"] == "aberta"
    # ➡ próximas: fecha as 2 (a do Binion's sem foto vira "vazia") e abre o Stu
    j = c.post(f"/busca-lista/{pid}/guias", json={"trocar": True, "quantas": 5}).get_json()
    assert j["abertas"] == 1 and "Stu" in abertas[-1]
    e = c.get(f"/busca-lista/{pid}/estado").get_json()
    assert e["termos"][1]["guia"] == "vazia"
    # renomear, tirar do zip, apagar
    a, b = its
    j = c.post(f"/busca-lista/{pid}/item/{a['id']}", json={"nome": "Archie jovem com fichas"}).get_json()
    assert j["item"]["arq"] == "Archie_jovem_com_fichas.png"
    c.post(f"/busca-lista/{pid}/item/{b['id']}", json={"usar": False})
    # 💻 do PC: foto renomeada + vídeo com o nome original, ligados a um termo
    r = c.post(f"/busca-lista/{pid}/enviar", data={"arquivos": [(io.BytesIO(_png()), "IMG_0001.PNG"), (io.BytesIO(b"\x00" * 900), "clip.mp4")],
                                                    "nomes": ["binions fachada", ""], "termo": "Binion's Horseshoe"},
               content_type="multipart/form-data").get_json()
    assert r["ok"] and [i["arq"] for i in r["itens"]] == ["binions_fachada.png", "clip.mp4"] and r["itens"][1]["tipo"] == "video"
    assert c.post(f"/busca-lista/{pid}/enviar", data={"arquivos": [(io.BytesIO(b"x"), "a.exe")]},
                  content_type="multipart/form-data").get_json()["erros"]
    # ⬇ zip: só os marcados + lista.txt ligando arquivo → busca
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/busca-lista/{pid}/zip").data))
    nomes = set(z.namelist())
    assert nomes == {"Archie_jovem_com_fichas.png", "binions_fachada.png", "clip.mp4", "lista.txt"}
    txt = z.read("lista.txt").decode()
    assert "=== Archie Karas ===" in txt and "Archie_jovem_com_fichas.png" in txt and "imagem: https://x/1.png" in txt
    assert "=== Binion's Horseshoe ===" in txt and "enviado do PC (original: IMG_0001.PNG)" in txt
    assert "=== sem resultado ===\nStu Ungar" in txt
    assert len(zipfile.ZipFile(io.BytesIO(c.get(f"/busca-lista/{pid}/zip?todos=1").data)).namelist()) == 5
    # 🔤 renumerar: depois de apagar a 1ª, a outra vira _01
    c.delete(f"/busca-lista/{pid}/item/{a['id']}")
    assert c.post(f"/busca-lista/{pid}/renomear-por-termo").get_json()["n"] == 1
    arqs = [i["arq"] for i in c.get(f"/busca-lista/{pid}/estado").get_json()["projeto"]["itens"]]
    assert "archie_karas_01.png" in arqs and os.path.isfile(os.path.join(BL.pasta_arq(base, pid), "archie_karas_01.png"))


def test_automatico_completa_no_proximo_buscador(cli, monkeypatch):
    c, base = cli
    bu = BL._bu()

    def img(t, k, m):
        return bu.ImagemBuscador(title=f"{t} {k}", description="", source_page=f"https://pag/{m}/{k}", original_url=f"https://{m}/{t}/{k}.jpg",
                                 thumbnail_url="", width=None, height=None, query=t, engine=m)
    chamadas = []

    def lote(motor, termos, limit=1, headless=True, orientation="any", **kw):
        chamadas.append((motor, list(termos)))
        n = {"brave": 1, "bing": 5}[motor]  # o Brave só acha 1 de cada
        return {"por_termo": {t: [img(t, k, motor) for k in range(n)] for t in termos}, "erros": {}, "erro_geral": None}
    cont = iter(range(100))

    def baixar(im, pasta, stem=None, timeout_s=45):
        cam = os.path.join(pasta, stem + ".jpg")
        open(cam, "wb").write(_jpg_com_desenho(next(cont)))
        return cam
    monkeypatch.setattr(bu, "buscar_lote", lote)
    monkeypatch.setattr(bu, "baixar_imagem", baixar)
    monkeypatch.setattr(bu, "parecidas", lambda a, b, limite=0: False)
    pid = BL.novo(base, "x")["id"]
    c.post(f"/busca-lista/{pid}/config", json={"termos": "Stu Ungar\nChip Reese", "motores": ["brave", "bing"], "qtd": 3})
    assert c.post(f"/busca-lista/{pid}/buscar", json={}).get_json()["ok"]
    for _ in range(100):
        e = c.get(f"/busca-lista/{pid}/estado").get_json()
        if e["tarefa"] and not e["tarefa"]["rodando"]:
            break
        time.sleep(0.05)
    assert not e["tarefa"]["erro"], e["tarefa"]
    its = e["projeto"]["itens"]
    assert len(its) == 6 and [x[0] for x in chamadas] == ["brave", "bing"]
    assert sorted(i["arq"] for i in its if i["termo"] == "Stu Ungar") == ["stu_ungar_01.jpg", "stu_ungar_02.jpg", "stu_ungar_03.jpg"]
    assert [i["motor"] for i in its if i["termo"] == "Chip Reese"] == ["brave", "bing", "bing"]
    assert e["tarefa"]["estado"]["termos"]["Chip Reese"]["st"] == "✅"


def test_script_manda_pra_busca_lista():
    import navegador_imagens as ni
    s = ni.script("http://localhost:5050")
    assert "DEST.m === 'lista'" in s and "/busca-lista/" in s and "@version      2.7.0" in s
