"""v84_341: a legenda usa o TEXTO do roteiro e o TEMPO do Whisper (corrige "blog"→"bloco", "three"→"3"…); e dá pra ajustar o
texto de cada parte enquanto grava — no envio os ajustes viram o roteiro (as partes mantêm o id)."""
import curtos as CT
import gravar_voz as GV
from test_v84_320_lote_por_etapa import _app


def _w(txt, passo=0.4):
    return [{"word": w, "start": round(i * passo, 2), "end": round(i * passo + 0.35, 2)} for i, w in enumerate(txt.split())]


def test_legenda_pelo_roteiro():
    bl = [{"fala": "Esse bloco de chocolate parece sólido, mas ele esconde uma surpresa."},
          {"fala": "Por dentro, camadas de bolo red velvet [laugh] com recheio branco. São 3 camadas."}]
    ws = _w("esse blog de chocolate parece solido mas ele esconde uma surpresa por dentro camadas de bolo redvelvet "
            "com recheio branco olha que legal sao three camadas")
    out = CT.legenda_pelo_roteiro(bl, ws)
    txt = " ".join(w["word"] for w in out)
    assert txt == ("Esse bloco de chocolate parece sólido, mas ele esconde uma surpresa. Por dentro, camadas de bolo red velvet "
                   "com recheio branco. olha que legal São 3 camadas.")
    bloco = next(w for w in out if w["word"] == "bloco")
    assert bloco["start"] == ws[1]["start"] and bloco["end"] == ws[1]["end"]  # o tempo é o do Whisper
    red, velvet = [w for w in out if w["word"] in ("red", "velvet")]
    assert red["start"] == ws[16]["start"] and velvet["end"] == ws[16]["end"] and red["end"] <= velvet["start"]  # dividiu o tempo
    assert all(out[k]["start"] <= out[k + 1]["start"] for k in range(len(out) - 1))
    # gancho em maiúsculas: só o 1º bloco
    up = CT.legenda_pelo_roteiro(bl, ws, True)
    assert up[1]["word"] == "BLOCO" and up[12]["word"] == "dentro,"
    # falou outra coisa bem diferente num trecho longo: fica o Whisper (não inventa)
    bl2 = [{"fala": "um dois três quatro cinco seis sete oito nove dez"}]
    ws2 = _w("um dois alfa beta gama delta epsilon zeta eta teta iota capa")
    out2 = [w["word"] for w in CT.legenda_pelo_roteiro(bl2, ws2)]
    assert out2[:2] == ["um", "dois"] and "alfa" in out2 and "três" not in out2
    assert CT.legenda_pelo_roteiro([], ws2) == ws2 and CT.legenda_pelo_roteiro(bl2, []) == []


def _proj(base):
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"idioma": "pt", "blocos": [{"id": "B1", "fala": "Esse bloco parece sólido. Mas esconde uma surpresa [gasp]."},
                                               {"id": "B2", "fala": "Você quebraria?"}]}
    CT.salvar(base, p)
    return p["id"]


def test_ajustar_texto_e_aplicar_no_roteiro(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    pid = _proj(base)
    GV.trocar_divisao(base, pid, "frase")
    r = GV.editar_texto(base, pid, "B1_2", "Mas por dentro tem uma surpresa.")
    ps = {x["id"]: x for x in r["partes"][1:]}
    assert ps["B1_2"]["texto"] == "Mas por dentro tem uma surpresa." and ps["B1_2"]["editado"] and ps["B1_2"]["original"] == "Mas esconde uma surpresa ."
    assert r["partes"][0]["texto"].startswith("Esse bloco parece sólido. Mas por dentro")  # o "tudo de uma vez" também
    assert GV.aplicar_textos_no_roteiro(base, pid) == 1
    b1 = CT.carregar(base, pid)["roteiro"]["blocos"][0]
    assert b1["fala"] == "Esse bloco parece sólido. Mas por dentro tem uma surpresa." and "[gasp]" in b1["fala_base_partes"]
    assert [x["id"] for x in GV.partes_de(base, pid)] == ["B1_1", "B1_2", "B2"]  # os ids não mudaram
    assert GV.aplicar_textos_no_roteiro(base, pid) == 0  # nada novo
    GV.editar_texto(base, pid, "B1_2", "")  # ↺ volta ao do roteiro
    assert GV.aplicar_textos_no_roteiro(base, pid) == 1
    b1 = CT.carregar(base, pid)["roteiro"]["blocos"][0]
    assert b1["fala"] == "Esse bloco parece sólido. Mas esconde uma surpresa [gasp]." and "fala_base_partes" not in b1
    try:
        GV.editar_texto(base, pid, "B9", "x")
        raise AssertionError
    except CT.CurtoErro:
        pass


def test_rota_e_pagina(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    pid = _proj(str(tmp_path))
    j = cl.post(f"/curtos/{pid}/voz/texto/B1", json={"texto": "Esse bloco é sólido, mas tem surpresa."}).get_json()
    assert j["ok"] and j["estado"]["partes"][1]["editado"]
    assert cl.post(f"/curtos/{pid}/voz/texto/..x", json={"texto": "a"}).status_code == 400
    html = cl.get(f"/curtos/{pid}/gravar").get_data(as_text=True)
    assert "data-edtexto" in html and "ajustar o texto" in html
    s_ = GV.criar_avulsa(str(tmp_path), "t", "Linha um.\nLinha dois.", "linha")["id"]
    r = cl.post(f"/curtos/{s_}/voz/texto/P2", json={"texto": "Linha dois ajustada."}).get_json()
    assert r["ok"] and r["estado"]["partes"][2]["texto"] == "Linha dois ajustada."
    assert GV.sessao(str(tmp_path), s_)["texto"] == "Linha um.\nLinha dois ajustada."


def test_v84_342_ia_corrige_so_o_que_saiu_do_roteiro():
    bl = [{"fala": "Esse bloco de chocolate parece sólido."}, {"fala": "Você quebraria um desses?"}]
    ws = _w("esse blog de chocolate parece solido e olha so que coisa mais linda voce quebraria um desses")
    pedidos = []

    def ia(trechos):
        pedidos.append(trechos)
        return {"trechos": [{"id": t["id"], "texto": "e olha só que coisa mais linda!"} for t in trechos]}
    out = CT.legenda_pelo_roteiro(bl, ws, False, ia)
    assert len(pedidos) == 1 and [t["texto"] for t in pedidos[0]] == ["e olha so que coisa mais linda"]  # só o improviso
    assert pedidos[0][0]["antes"].endswith("sólido.") and pedidos[0][0]["depois"].startswith("Você")
    txt = " ".join(w["word"] for w in out)
    assert txt == "Esse bloco de chocolate parece sólido. e olha só que coisa mais linda! Você quebraria um desses?"
    so = next(w for w in out if w["word"] == "só")
    assert so["start"] == ws[8]["start"] and "livre" not in so  # o mesmo tempo do Whisper
    # a IA juntou palavras: divide o tempo do trecho
    out2 = CT.legenda_pelo_roteiro(bl, ws, False, lambda t: {"trechos": [{"id": 0, "texto": "e olha que lindo!"}]})
    trecho = [w for w in out2 if w.get("corrigido")]
    assert [w["word"] for w in trecho] == ["e", "olha", "que", "lindo!"] and trecho[0]["start"] == ws[6]["start"] and trecho[-1]["end"] == ws[12]["end"]
    # IA desligada / com erro / inventando demais: fica como o Whisper ouviu
    for ruim in (lambda t: None, lambda t: 1 / 0, lambda t: {"trechos": [{"id": 0, "texto": "x " * 40}]}):
        assert "olha so que" in " ".join(w["word"] for w in CT.legenda_pelo_roteiro(bl, ws, False, ruim))
    # tudo no roteiro: nem chama a IA
    chamou = []
    CT.legenda_pelo_roteiro(bl, _w("esse blog de chocolate parece solido voce quebraria um desses"), False, lambda t: chamou.append(t))
    assert not chamou
