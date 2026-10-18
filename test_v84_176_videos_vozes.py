"""v84_176 — 🎬 link de vídeo na criação do projeto (e nos que tinham falhado como matéria) vira transcrição nas
anotações; 🗣️ perfis de voz aparecem no 🎭 Vozes dos personagens (vira voz Chatterbox sozinha); 📋 copiar os links."""
import pytest

import multivoz as mv


@pytest.fixture
def app_(tmp_path, monkeypatch):
    import app as a
    monkeypatch.setattr(mv, "ARQUIVO", str(tmp_path / "vozes_multi.json"))
    return a


def test_video_na_criacao_e_os_que_falharam(app_, monkeypatch):
    import dossies as ds
    import roteiros_yt as ry
    import tarefas_bg
    monkeypatch.setattr(ry, "extrair_transcricao", lambda url, pasta, on_log=None: {"titulo": "Vídeo " + url[-3:], "url": url})
    monkeypatch.setattr(ry, "texto_da_transcricao", lambda tr, com_tempo=False: "Fala do vídeo " + tr["url"][-3:])
    monkeypatch.setattr(tarefas_bg, "iniciar", lambda tipo, titulo, fn, pagina="": fn(type("T", (), {"progresso": lambda s, m: None})()) and "t1")
    c = app_.app.test_client()
    r = c.post("/modelos-video/novo", data={"tema": "Teste vídeos", "modelo": "true_crime",
                                            "fontes": "https://www.youtube.com/watch?v=EUUbPEXdL-0&sttick=0"})
    pid = r.headers["Location"].rstrip("/").split("/")[-1]
    try:
        p = ds.carregar(app_.BASE_DIR, pid)
        assert not p["fontes"] and "Fala do vídeo L-0" in p["roteiro_base"]
        # um projeto antigo, com o vídeo que entrou como matéria e falhou
        p["fontes"].append({"id": "F1", "url": "https://youtu.be/abcdefghijk", "estado": "erro",
                            "erro": "Não achei texto nem imagens nessa página."})
        ds.salvar(app_.BASE_DIR, p)
        h = c.get(f"/modelos-video/{pid}").get_data(as_text=True)
        p = ds.carregar(app_.BASE_DIR, pid)
        assert not p["fontes"] and "(https://www.youtube.com/watch?v=abcdefghijk)" in p["roteiro_base"]
        assert 'id="btnCopiarLinks"' in h
    finally:
        ds.excluir(app_.BASE_DIR, pid)


def test_voz_de_perfil(app_):
    v = mv.voz_de_perfil("Mariana_LeBlanc")
    assert v["slug"] == "mariana_leblanc" and v["motor"] == "chatterbox" and v["config"] == {"vozPerfil": "Mariana_LeBlanc"}
    assert mv.voz_de_perfil("Mariana_LeBlanc")["slug"] == "mariana_leblanc" and len(mv.listar()) == 1  # reaproveita
    mv.salvar({"nome": "Outra", "slug": "lucas", "motor": "xtts", "config": {"vozPerfil": "Lucas"}})
    assert mv.voz_de_perfil("Lucas")["slug"] == "lucas_2"  # o slug ocupado não é sobrescrito


def test_config_com_perfil_cria_a_voz(app_):
    import dossies as ds
    p = ds.criar(app_.BASE_DIR, "Teste vozes", modelo="true_crime")
    try:
        c = app_.app.test_client()
        d = c.post(f"/modelos-video/{p['id']}/config", json={"vozes_personagens": {
            "mira": {"voz": "perfil:Mariana_LeBlanc", "exag": "0.6"}}}).get_json()
        assert d["config"]["vozes_personagens"]["mira"] == {"voz": "mariana_leblanc", "exag": 0.6}
        assert any(v["slug"] == "mariana_leblanc" for v in d["vozes_multi"])
        d = c.post(f"/modelos-video/{p['id']}/config", json={"tema": "x"}).get_json()
        assert "vozes_multi" not in d
    finally:
        ds.excluir(app_.BASE_DIR, p["id"])


def test_shorts_vira_watch():
    import dossies as ds
    for u in ("https://www.youtube.com/shorts/12Ze2SRpfhU", "https://youtube.com/shorts/12Ze2SRpfhU?si=x",
              "https://youtu.be/12Ze2SRpfhU?t=3", "https://www.youtube.com/watch?v=12Ze2SRpfhU?xstg=CAMS%3D",
              "https://m.youtube.com/watch?feature=share&v=12Ze2SRpfhU"):
        assert ds.link_video_padrao(u) == "https://www.youtube.com/watch?v=12Ze2SRpfhU", u
    assert ds.link_video_padrao("https://www.tiktok.com/@a/video/1") == "https://www.tiktok.com/@a/video/1"


def test_fontes_com_shorts_transcreve_o_watch(app_, monkeypatch):
    import dossies as ds
    import roteiros_yt as ry
    import tarefas_bg
    vistos = []
    monkeypatch.setattr(ry, "extrair_transcricao", lambda url, pasta, on_log=None: vistos.append(url) or {"titulo": "S", "url": url})
    monkeypatch.setattr(ry, "texto_da_transcricao", lambda tr, com_tempo=False: "fala")
    monkeypatch.setattr(tarefas_bg, "iniciar", lambda tipo, titulo, fn, pagina="": fn(type("T", (), {"progresso": lambda s, m: None})()) and "t1")
    p = ds.criar(app_.BASE_DIR, "Shorts", modelo="true_crime")
    try:
        c = app_.app.test_client()
        c.post(f"/modelos-video/{p['id']}/fontes", json={"urls": "https://www.youtube.com/shorts/12Ze2SRpfhU\nhttps://youtu.be/12Ze2SRpfhU"})
        assert vistos == ["https://www.youtube.com/watch?v=12Ze2SRpfhU"]  # o mesmo vídeo uma vez só
        assert "(https://www.youtube.com/watch?v=12Ze2SRpfhU)" in ds.carregar(app_.BASE_DIR, p["id"])["roteiro_base"]
    finally:
        ds.excluir(app_.BASE_DIR, p["id"])
