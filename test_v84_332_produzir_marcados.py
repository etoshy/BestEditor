"""v84_332: ▶ produzir os marcados que estão na fila (um por vez ou 🧩 por etapa); opções do envio ficam salvas + ↺ padrão."""
import curtos as CT
import curtos_rotas as CR
from test_v84_320_lote_por_etapa import _app, _espera, _falsos


def test_produz_so_os_marcados_por_etapa_e_um_por_vez(tmp_path, monkeypatch):
    base = str(tmp_path)
    cl = _app(tmp_path, monkeypatch)
    log, junto = _falsos(base, monkeypatch)
    a, b, c, d = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2\nhttps://a.com/3\nhttps://a.com/4",
                                                   "exportar": False, "voz": "v1"}).get_json()["criados"]
    r = cl.post("/curtos/link/iniciar-marcados", json={"ids": [a, b], "por_etapa": True}).get_json()
    assert r["iniciados"] == 2 and r["por_etapa"]
    _espera([a, b])
    assert {x[1] for x in log if x[0] == "editor"} == {a, b} and junto["max"] == 2  # em paralelo na rede
    assert CT.carregar(base, c)["link_rapido"]["aguardando"] and c not in CR.TAREFAS  # o não marcado nem começou
    r = cl.post("/curtos/link/iniciar-marcados", json={"ids": [a, c], "por_etapa": False}).get_json()
    assert r["iniciados"] == 1 and r["pulados"] == 1 and not r["por_etapa"]  # o a já está pronto (no editor)
    _espera([c])
    assert any(x[0] == "editor" and x[1] == c for x in log) and CT.carregar(base, d)["link_rapido"]["aguardando"]
    assert cl.post("/curtos/link/iniciar-marcados", json={"ids": [a]}).get_json()["iniciados"] == 0


def test_tela_tem_padrao_e_produzir(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    html = cl.get("/curtos/link").get_data(as_text=True)
    assert "lkPadrao()" in html and "voltar ao padrão" in html and "data-selini" in html and "lk_sel" in html
