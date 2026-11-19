"""v84_428 — juiz visual só nos ⚡ curtos (API por padrão, ou o Qwen com visão); nos vídeos longos continua desligado."""
import ia_economia as ie
import ia_local as il


def _isolar(monkeypatch, tmp_path):
    import ia_servico as ia
    monkeypatch.setattr(ia, "CONFIG_PATH", str(tmp_path / "ia_config.json"))
    monkeypatch.delenv("BESTEDITOR_IA_SO_API", raising=False)
    return ia


def test_padrao_juiz_so_nos_curtos(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    r = ia.config()["recursos"]
    assert r["juiz"] is False and r["juiz_curtos"] is True
    e = ie.estado()
    assert e["juiz_modo"] == "off" and e["juiz_curtos_modo"] == "api"


def test_modos_dos_curtos(monkeypatch, tmp_path):
    ia = _isolar(monkeypatch, tmp_path)
    ie.salvar({"local": {"ativo": True, "modelo_visao": "qwen2.5vl:7b"}})
    e = ie.salvar({"juiz_curtos_modo": "local"})
    assert e["juiz_curtos_modo"] == "local" and "juiz_curtos" in ia.config()["local"]["so_local"]
    assert e["juiz_modo"] == "off"  # o dos longos não muda
    e = ie.salvar({"juiz_curtos_modo": "off"})
    assert e["juiz_curtos_modo"] == "off" and not ia.config()["recursos"]["nova_busca"]
    e = ie.salvar({"juiz_curtos_modo": "api"})
    assert e["juiz_curtos_modo"] == "api" and "juiz_curtos" not in ia.config()["local"]["recursos"] and ia.config()["recursos"]["nova_busca"]


def test_curto_usa_o_juiz_proprio(monkeypatch):
    import video_assembler as va
    vistos = []
    monkeypatch.setattr(va, "_ia_pode", lambda r: (vistos.append(r) or r == "juiz_curtos"))
    import ia_midia
    monkeypatch.setattr(ia_midia, "julgar", lambda *a, **k: (vistos.append("julgou:" + a[7]) or None))
    cands = [{"id": "a", "thumbnail": "t"}]
    va.julgar_candidatos_ia(cands, {"fala": "x", "recurso_juiz": "juiz_curtos"}, "busca")
    assert "juiz_curtos" in vistos and "julgou:juiz_curtos" in vistos
    vistos.clear()
    assert va.julgar_candidatos_ia(cands, {"fala": "x"}, "busca") is None and vistos == ["juiz"]  # longo: desligado


def test_preparar_buscas_marca_o_curto(monkeypatch):
    import app as A
    import ia_servico
    monkeypatch.setattr(ia_servico, "ativo", lambda r=None: r == "juiz_curtos")
    from video_assembler import VideoSegment
    segs = [VideoSegment(start=0.0, end=2.0, provider="pexels", query="x")]
    job = {"curto_id": "c1", "segments": [{"start": 0.0, "end": 2.0, "text": "olá"}]}
    ctx = A._ia_preparar_buscas("j1", job, segs)
    assert ctx and ctx[0]["recurso_juiz"] == "juiz_curtos"
    assert A._ia_preparar_buscas("j2", {"segments": job["segments"]}, segs) is None  # longo: juiz e buscas desligados
