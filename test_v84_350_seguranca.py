"""v84_350: auditoria — o site local não aceita POST vindo de outro site (CSRF), sobe só em 127.0.0.1 e sem o console do
depurador; as rotas do userscript do Google continuam liberadas."""
import os

import pytest


@pytest.fixture()
def cl(tmp_path, monkeypatch):
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    import app as A
    return A.app.test_client()


def test_post_de_outro_site_e_recusado(cl):
    r = cl.post("/curtos/link/limpar", json={"acao": "tirar"}, headers={"Origin": "https://site-malvado.com"})
    assert r.status_code == 403 and "CSRF" in r.get_data(as_text=True)
    r = cl.post("/curtos/link/limpar", data={"acao": "tirar"}, headers={"Referer": "https://site-malvado.com/pagina"})
    assert r.status_code == 403
    assert cl.post("/curtos/link/limpar", json={}, headers={"Origin": "null"}).status_code == 403


def test_o_proprio_site_e_quem_nao_tem_navegador_passam(cl):
    for o in ("http://localhost", "http://127.0.0.1"):
        r = cl.post("/curtos/link/limpar", json={"acao": "x"}, headers={"Origin": o})
        assert r.status_code == 400  # passou da proteção (a rota recusou o "x" sozinha)
    assert cl.post("/curtos/link/limpar", json={"acao": "x"}).status_code == 400  # sem Origin: minerador/scripts locais
    assert cl.get("/curtos/link/estado", headers={"Origin": "https://site-malvado.com"}).status_code == 200  # GET não muda nada


def test_rotas_do_userscript_continuam_liberadas(cl):
    import app as A
    for rota in ("/navegador-imagens/aba", "/busca-lista/abc/link", "/modelos-video/x/fotos-roteiro/guias"):
        assert A._rota_do_script_externo(rota)
    assert not A._rota_do_script_externo("/curtos/link/limpar")
    r = cl.post("/navegador-imagens/aba", json={}, headers={"Origin": "https://www.google.com"})
    assert r.status_code != 403


def test_sobe_so_no_pc_e_sem_console():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), encoding="utf-8").read()
    assert 'host="0.0.0.0"' not in src and 'os.environ.get("BESTEDITOR_HOST", "127.0.0.1")' in src
    assert "use_debugger=_console and" in src


def test_replace_tenta_de_novo_no_acesso_negado(tmp_path, monkeypatch):
    import arquivo_seguro as AS
    chamadas = []

    def falha_2x(src, dst, *a, **k):
        chamadas.append(1)
        if len(chamadas) <= 2:
            raise PermissionError(13, "Acesso negado (teste)")
        return None
    monkeypatch.setattr(AS, "_REPLACE_ORIGINAL", falha_2x)
    monkeypatch.setattr(AS, "ESPERA", 0.001)
    AS._replace_com_retentativa("a", "b")
    assert len(chamadas) == 3
    monkeypatch.setattr(AS, "_REPLACE_ORIGINAL", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("x")))
    with pytest.raises(FileNotFoundError):  # outros erros não ficam tentando
        AS._replace_com_retentativa("a", "b")


def test_gravacoes_de_json_com_nome_unico(tmp_path):
    import threading
    import curtos as CT
    cam = str(tmp_path / "p" / "projeto.json")
    erros = []

    def gravar(k):
        try:
            for i in range(30):
                CT._gravar_json(cam, {"k": k, "i": i, "x": "y" * 2000})
        except Exception as exc:  # noqa: BLE001
            erros.append(exc)
    ts = [threading.Thread(target=gravar, args=(k,)) for k in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    import json
    assert not erros and json.load(open(cam))["i"] == 29  # nunca embaralhado, nenhum erro
    assert not [n for n in os.listdir(tmp_path / "p") if n.endswith(".tmp")]


def test_idempotencia_refazer_e_envio_duplicado(tmp_path, monkeypatch):
    import threading
    import time
    import curtos as CT
    import curtos_rotas as CR
    from test_v84_320_lote_por_etapa import _app
    cl = _app(tmp_path, monkeypatch)
    r1 = cl.post("/curtos/link/novo", json={"link": "https://a.com/1\nhttps://a.com/2"}).get_json()
    assert len(r1["criados"]) == 2
    r2 = cl.post("/curtos/link/novo", json={"link": "https://a.com/1"})  # clique duplo: não cria de novo
    assert r2.status_code == 409 and "repetido" in r2.get_json()["erro"]
    r3 = cl.post("/curtos/link/novo", json={"link": "https://a.com/2\nhttps://a.com/3"}).get_json()
    assert len(r3["criados"]) == 1  # só o novo
    pid = r1["criados"][0]
    trava = threading.Event()
    monkeypatch.setattr(CR, "_espera_memoria", lambda *a, **k: trava.wait(3), raising=False)
    respostas = []
    import curtos_comentario as CC
    monkeypatch.setattr(CC, "baixar_clipe", lambda *a, **k: trava.wait(3) or (_ for _ in ()).throw(CT.CurtoErro("teste")))
    ts = [threading.Thread(target=lambda: respostas.append(cl.post(f"/curtos/link/{pid}/refazer").status_code)) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    trava.set()
    assert sorted(respostas).count(200) == 1 and respostas.count(409) == 4  # 5 cliques juntos: roda UMA vez
    for _ in range(200):
        if (CR.TAREFAS.get(pid) or {}).get("fim"):
            break
        time.sleep(0.02)
