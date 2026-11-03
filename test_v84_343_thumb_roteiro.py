"""v84_343: no cartão do Link — escolher o print da thumb no player do vídeo original (os seus ficam quando a IA escolhe
outros), a tradução do roteiro pro português e pedir mudanças no roteiro pra IA (com ↶ versão anterior)."""
import os
import subprocess

import curtos as CT
import curtos_comentario as CC
import curtos_link as CL
import curtos_rotas as CR
from test_v84_320_lote_por_etapa import _app


def _proj_com_clipe(base):
    p = CT.criar(base, "", "🔗 x", modelo="comentario")
    d = CT.pasta(base, p["id"])
    os.makedirs(d, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:d=4:r=10", "-pix_fmt", "yuv420p",
                    os.path.join(d, "m1.mp4")], check=True, timeout=60)
    p["midias"] = [{"id": "M1", "arquivo": "m1.mp4", "tipo": "video", "dur": 4.0}]
    p["roteiro"] = {"idioma": "en", "blocos": [{"id": "B1", "fala": "This chocolate hides a cake.", "fala_en": "This chocolate hides a cake.",
                                                "fala_pt": "Esse chocolate esconde um bolo.", "cenas": []}]}
    p["link_rapido"] = {"link": "https://a.com/1", "criado": 1}
    CT.salvar(base, p)
    return p["id"]


def test_salvar_momento_apagar_e_manter_os_seus(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    pid = _proj_com_clipe(base)
    v = next(x for x in cl.get("/curtos/link/estado").get_json()["videos"] if x["id"] == pid)
    assert v["tem_original"] and v["roteiro_pt"] == "Esse chocolate esconde um bolo." and v["roteiro_idioma"] == "en"
    assert cl.get(f"/curtos/{pid}/voz/clipe").status_code == 200  # o player usa o original
    j = cl.post(f"/curtos/{pid}/thumb/salvar", json={"t": 1.5}).get_json()
    assert j["ok"] and j["k"] == 1
    t = CT.carregar(base, pid)["thumbs"][0]
    assert t["manual"] and t["arquivo"] == "manual_1500.jpg" and os.path.isfile(os.path.join(CT.pasta(base, pid), "thumbs", t["arquivo"]))
    assert cl.get(f"/curtos/{pid}/thumb/1.jpg").status_code == 200
    cl.post(f"/curtos/{pid}/thumb/salvar", json={"t": 2.5})
    # a IA escolhe outros: os seus 2 ficam na frente
    monkeypatch.setattr(CL, "prints_para_thumb", lambda *a, **k: [{"arquivo": "thumb_1.jpg", "t": 0.5, "por_que": "ia"}])
    open(os.path.join(CT.pasta(base, pid), "thumbs", "thumb_1.jpg"), "wb").write(b"x")
    assert cl.post(f"/curtos/{pid}/thumbs").get_json()["ok"]
    assert [x["arquivo"] for x in CT.carregar(base, pid)["thumbs"]] == ["manual_1500.jpg", "manual_2500.jpg", "thumb_1.jpg"]
    # a capa escolhida acompanha quando um print sai
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["link_rapido"]["escolha"] = {"capa": 3}
        CT.salvar(base, q)
    assert cl.post(f"/curtos/{pid}/thumb/1/apagar").get_json()["ok"]
    q = CT.carregar(base, pid)
    assert [x["arquivo"] for x in q["thumbs"]] == ["manual_2500.jpg", "thumb_1.jpg"] and q["link_rapido"]["escolha"]["capa"] == 2
    assert not os.path.isfile(os.path.join(CT.pasta(base, pid), "thumbs", "manual_1500.jpg"))
    assert cl.post(f"/curtos/{pid}/thumb/9/apagar").status_code == 404
    assert cl.post(f"/curtos/{pid}/thumb/salvar", json={"t": "x"}).status_code == 400
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert "data-tsalvar" in html and "data-rajustar" in html and "data-origph" in html


def test_pedir_mudanca_desfazer_e_traduzir(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    base = str(tmp_path)
    pid = _proj_com_clipe(base)
    vistos = []

    def ia(rec, sys_, conteudo, **k):
        vistos.append(conteudo)
        return {"blocos": [{"id": "B1", "funcao": "gancho", "fala_en": "Nobody expects what is inside this chocolate.",
                            "fala_pt": "Ninguém espera o que tem dentro desse chocolate.", "cenas": []}]}
    r = CC.revisar_roteiro(base, pid, "o gancho ficou fraco, comece pela surpresa", chamar=ia)
    txt = vistos[0] if isinstance(vistos[0], str) else " ".join(x.get("text", "") for x in vistos[0] if isinstance(x, dict))
    assert "comece pela surpresa" in txt and "This chocolate hides a cake." in txt  # o pedido + o roteiro de antes
    assert r["blocos"][0]["fala"].startswith("Nobody expects")
    p = CT.carregar(base, pid)
    assert len(p["roteiro_historico"]) == 1 and p["roteiro_historico"][0]["blocos"][0]["fala"] == "This chocolate hides a cake."
    assert "extra" not in (p.get("config") or {}) or "REVISION" not in (p["config"].get("extra") or "")  # não sujou o pedido extra
    # pela rota (com a IA de mentira) + o aviso de refazer
    monkeypatch.setattr(CC, "revisar_roteiro", lambda b, i, ped: CC.__dict__["_guardar_versao"] and None)
    j = cl.post(f"/curtos/{pid}/roteiro/ajustar", json={"pedido": "mais engraçado"}).get_json()
    v = next(x for x in j["videos"] if x["id"] == pid)
    assert v["roteiro_mudou"] and v["roteiro_versoes"] == 1
    assert cl.post(f"/curtos/{pid}/roteiro/ajustar", json={"pedido": ""}).status_code == 400
    j = cl.post(f"/curtos/{pid}/roteiro/desfazer").get_json()
    assert j["ok"] and CT.carregar(base, pid)["roteiro"]["blocos"][0]["fala"] == "This chocolate hides a cake."
    assert cl.post(f"/curtos/{pid}/roteiro/desfazer").status_code == 400  # não tem mais versão
    # traduzir o que não tem tradução
    with CT._TRAVA:
        q = CT.carregar(base, pid)
        q["roteiro"]["blocos"][0]["fala_pt"] = ""
        CT.salvar(base, q)
    n = CC.traduzir_roteiro(base, pid, chamar=lambda *a, **k: {"blocos": [{"id": "B1", "pt": "Esse chocolate esconde um bolo!"}]})
    assert n == 1 and CT.carregar(base, pid)["roteiro"]["blocos"][0]["fala_pt"] == "Esse chocolate esconde um bolo!"
    assert CC.traduzir_roteiro(base, pid, chamar=lambda *a, **k: 1 / 0) == 0  # já tem: nem chama
