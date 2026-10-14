"""v84_106 — ⛔ lista negra de sites EDITÁVEL (Magnific/Freepik + bancos com marca d'água): imagem/vídeo de lá nunca
entra (buscadores e bancos), e o 🤖 juiz dá nota 0 pra miniatura com marca d'água (busca outra / vira cartão)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))

import lista_negra as ln  # noqa: E402
import site_config  # noqa: E402


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.setattr(site_config, "CONFIG_PATH", str(tmp_path / "site_config.json"))
    return tmp_path


def test_casa_os_enderecos(cfg):
    assert ln.sites() == ln.PADRAO and "magnific" in ln.PADRAO and "freepik" in ln.PADRAO
    assert ln.bloqueado("https://img.freepik.com/foto.jpg") == "freepik"
    assert ln.bloqueado("https://cdn.magnific.ai/v.mp4") == "magnific"
    assert ln.bloqueado("https://c8.alamy.com/x.jpg") == "alamy" and ln.bloqueado("https://t4.ftcdn.net/a") == "ftcdn.net"
    assert ln.bloqueado("https://upload.wikimedia.org/a.jpg") is None and ln.bloqueado("https://notalamyx.com") is None
    assert ln.provedor_bloqueado("magnific") and not ln.provedor_bloqueado("pexels")
    assert ln.sem_bloqueados(["pexels", "magnific", "mixkit"]) == ["pexels", "mixkit"]
    assert ln.normalizar("https://www.Shutterstock.com/abc\n# comentário\nmagnific, freepik") == ["shutterstock.com", "magnific", "freepik"]
    assert ln.titulo_de_banco("Red apple - Free Photo | Freepik")


def test_editavel(cfg):
    site_config.save_site_config({"sites_bloqueados": ["meusite.com"]})
    assert ln.sites() == ["meusite.com"] and not ln.provedor_bloqueado("magnific")
    assert ln.bloqueado("https://img.meusite.com/a.png") == "meusite.com"
    import buscador_imagens_unificado as bu
    assert bu._url_com_marca_dagua("https://img.meusite.com/a.png") and not bu._url_com_marca_dagua("https://c8.alamy.com/x")
    site_config.save_site_config({"sites_bloqueados": None})
    img = bu.ImagemBuscador(title="Apple", source_page="https://www.freepik.com/x", original_url="https://img.freepik.com/x.jpg")
    assert bu.tem_marca_dagua(img) and bu.sem_marca_dagua([img]) == []


def test_prompt_e_bancos_sem_o_bloqueado(cfg):
    import prompt_builder
    import video_assembler as va
    segs = [{"start": 0.0, "end": 5.0, "text": "uma maçã"}]
    t = prompt_builder.build_prompt(segs, providers=["pexels", "magnific"])
    assert "Escolha um provedor **exclusivamente** dentre estes, EXATAMENTE como escritos, pra cada segmento: pexels." in t
    assert va._sem_bloqueados(["magnific", "pexels"], {"sites_bloqueados": []}) == ["magnific", "pexels"]
    assert va._sem_bloqueados(["magnific", "pexels"]) == ["pexels"]


def test_juiz_marca_dagua_nota_zero_e_vai_pro_fim(monkeypatch):
    import ia_midia
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: True)
    monkeypatch.setattr(ia_servico, "imagem_bloco", lambda url: {"type": "text", "text": "img"})
    monkeypatch.setattr(ia_servico, "chamar", lambda *a, **k: {"notas": [
        {"n": 1, "nota": 9, "motivo": "ótima, mas tem Shutterstock por cima", "problemas": ["marca_dagua"]},
        {"n": 2, "nota": 6, "motivo": "ok", "problemas": []}], "melhor": 1, "nova_busca": ""})
    cands = [{"thumbnail": "https://x/1.jpg", "label": "A"}, {"thumbnail": "https://x/2.jpg", "label": "B"}]
    j = ia_midia.julgar(cands, "uma maçã")
    assert j["notas"][0]["nota"] == 0 and j["melhor"] == 1
    lista = ia_midia.reordenar(cands, j)
    assert lista[0]["label"] == "B" and lista[-1]["marca_dagua"] and lista[-1]["label"].startswith("⛔ marca d'água")
    assert "MARCA D'ÁGUA" in ia_midia._SYS_JUIZ and "Magnific/Freepik" in ia_midia._SYS_JUIZ


def test_tela_de_configuracoes(cfg):
    import app as _app
    c = _app.app.test_client()
    h = c.get("/settings").get_data(as_text=True)
    assert 'name="sites_bloqueados"' in h and "magnific\nfreepik" in h and "<b>magnific</b> fora" in h
    c.post("/settings", data={"sites_bloqueados": "shutterstock.com\n# nada\nalamy\n"})
    assert ln.sites() == ["shutterstock.com", "alamy"]
    c.post("/settings", data={"sites_bloqueados": "", "sites_bloqueados_padrao": "on"})
    assert ln.sites() == ln.PADRAO
