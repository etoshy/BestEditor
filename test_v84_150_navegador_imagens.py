import base64
import json

import fotos_roteiro
import navegador_imagens as ni


def _dec(s):
    return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode())


def test_destino_vai_no_endereco_e_volta():
    d = ni.destino("http://localhost:5050/", "ab12", "Q3", rotulo="Quem é a vítima?")
    url = ni.url_google("Ted Kaczynski 1978", d)
    assert url.startswith("https://www.google.com/search?udm=2&q=Ted%20Kaczynski%201978#bes=")
    assert _dec(url.split("#bes=")[1]) == {"u": "http://localhost:5050", "p": "ab12", "q": "Q3", "r": "Quem é a vítima?"}


def test_proximas_pula_feitas_puladas_e_abertas():
    qs = [{"id": "Q1", "alvo": "a"}, {"id": "Q2", "alvo": "b", "pulada": True}, {"id": "Q3", "alvo": "c", "guia": "aberta"},
          {"id": "Q4", "alvo": "d"}, {"id": "Q5", "alvo": "e"}]
    assert [q["id"] for q in ni.proximas(qs, {"Q1": ["I1"]}, 5)] == ["Q4", "Q5"]
    assert [q["id"] for q in ni.proximas(qs, {}, 1)] == ["Q1"]


def test_foto_da_guia_entra_na_pessoa_do_elenco():
    p = {"elenco": {"pessoas": [{"nome": "Ted Kaczynski", "fotos": []}], "locais": []}}
    fotos_roteiro._ligar_ao_elenco(p, {"id": "I9"}, "pessoa", "ted kaczynski")
    fotos_roteiro._ligar_ao_elenco(p, {"id": "I10"}, "local", "Cabana em Montana")
    assert p["elenco"]["pessoas"][0]["fotos"][0]["midia"] == "I9"
    assert p["elenco"]["locais"][0]["fotos"] == ["I10"]


def test_script_com_o_endereco_do_site():
    s = ni.script("http://127.0.0.1:5050")
    assert "@updateURL    http://127.0.0.1:5050/navegador-imagens/script.user.js" in s and "GM_xmlhttpRequest" in s


def test_troca_fecha_as_prontas_e_deixa_a_marcada(monkeypatch):
    import time
    vivas = [{"id": "A", "type": "page"}, {"id": "B", "type": "page"}]
    fechou = []
    monkeypatch.setattr(ni, "_cdp", lambda porta, cam, metodo="GET", timeout=3.0: vivas if cam == "/json/list" else fechou.append(cam) or True)
    ni.ABAS["PX"] = [{"id": "A", "chave": "Q1"}, {"id": "B", "chave": "Q2"}, {"id": "C", "chave": "Q3"}]
    ni.ESTADOS["PX|Q2"] = {"estado": "marcada", "marcadas": 1, "t": time.time()}
    r = ni.fechar_terminadas("PX", {})
    assert sorted(r["fechadas"]) == ["Q1", "Q3"] and r["mantidas"][0]["chave"] == "Q2"
    assert fechou == ["/json/close/A"] and [a["chave"] for a in ni.ABAS["PX"]] == ["Q2"]
