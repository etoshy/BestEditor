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


class _BraveFalso:
    """Porta de controle falsa: `quebrado` = a porta responde mas as guias não aparecem (o caso do Brave travado)."""

    def __init__(self, quebrado_ate=0, sobe=True):
        self.guias, self.n, self.quebrado_ate, self.reinicios, self.sobe, self.ativou = [], 0, quebrado_ate, 0, sobe, []

    def cdp(self, porta, cam, metodo="GET", timeout=3.0):
        if cam == "/json/version":
            return {"Browser": "Brave"} if self.sobe else None
        if cam.startswith("/json/new"):
            self.n += 1
            gid = f"g{self.n}"
            if self.reinicios >= self.quebrado_ate:
                self.guias.append(gid)
            return {"id": gid}
        if cam == "/json/list":
            return [{"id": g, "type": "page"} for g in self.guias]
        if cam.startswith("/json/activate/"):
            self.ativou.append(cam)
        return True

    def matar(self, base):
        self.reinicios += 1
        return True


def _brave(monkeypatch, falso):
    import navegador_imagens as ni
    monkeypatch.setattr(ni, "achar", lambda cfg=None: "C:/brave.exe")
    monkeypatch.setattr(ni, "_cdp", falso.cdp)
    monkeypatch.setattr(ni, "matar_navegador_do_site", falso.matar)
    monkeypatch.setattr(ni, "_iniciar", lambda exe, perfil, porta, espera_s=20.0: falso.sobe)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return ni


def test_abrir_confirma_as_guias(monkeypatch, tmp_path):
    f = _BraveFalso()
    ni = _brave(monkeypatch, f)
    r = ni.abrir(str(tmp_path), ["https://a", "https://b"], {}, chaves=["q1", "q2"], pid="p")
    assert r["ok"] and r["confirmadas"] == [0, 1] and not r["reiniciou"] and f.ativou


def test_brave_travado_e_reiniciado_sozinho(monkeypatch, tmp_path):
    f = _BraveFalso(quebrado_ate=1)  # na 1ª tentativa as guias não aparecem
    ni = _brave(monkeypatch, f)
    r = ni.abrir(str(tmp_path), ["https://a"], {}, chaves=["q1"], pid="p")
    assert r["ok"] and r["reiniciou"] and f.reinicios == 1 and r["confirmadas"] == [0]


def test_brave_que_nao_abre_nao_finge(monkeypatch, tmp_path):
    f = _BraveFalso(quebrado_ate=99)
    ni = _brave(monkeypatch, f)
    r = ni.abrir(str(tmp_path), ["https://a"], {}, chaves=["q1"], pid="p")
    assert not r["ok"] and r["confirmadas"] == [] and "não abriu" in r["erro"]
