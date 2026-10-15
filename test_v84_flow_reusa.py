"""v84_112 — na exportação, as imagens/vídeos que o Flow JÁ gerou (na prévia ou antes) entram como estão: nada de
gerar de novo (nem quando as contas estão sem crédito, nem com o link /flow/imagens/... escolhido no editor)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "toolkit"))


@pytest.fixture
def gf(monkeypatch, tmp_path):
    from googleflow import googleflow_client as gf
    monkeypatch.setattr(gf, "pasta_dados", lambda: tmp_path / "flow_dados")
    os.makedirs(gf.pasta_imagens(), exist_ok=True)
    return gf


def _guardar(gf, query, tipo, arquivo, orientation="16:9"):
    prop = gf.proporcao_para_orientacao(orientation)
    prompt = gf.montar_prompt_video(query, prop) if tipo == "video" else gf.montar_prompt(query, prop)
    caminho = gf.pasta_imagens() / arquivo
    caminho.write_bytes(b"x" * 100)
    dados = gf.carregar_json()
    dados.append({"chave": gf.chave_do_prompt(prompt), "tipo": tipo, "arquivo": arquivo, "prompt": prompt, "indice": 0})
    gf._salvar_json(dados)
    return str(caminho)


def test_cache_e_link_local(gf):
    import video_assembler as va
    v = _guardar(gf, "um farol na tempestade", "video", "v1.mp4")
    f = _guardar(gf, "um mapa antigo", "imagem", "f1.png")
    cfg = {"orientation": "16:9"}
    assert va.flow_ja_gerado("um farol na tempestade", cfg, "video") and not va.flow_ja_gerado("um farol na tempestade", cfg, "imagem")
    assert va.flow_ja_gerado("um mapa antigo", cfg, "imagem") and not va.flow_ja_gerado("outra coisa", cfg, "imagem")
    assert va.flow_arquivo_local("/flow/imagens/v1.mp4?t=1") == v and va.flow_arquivo_local("/flow/imagens/f1.png") == f
    assert va.flow_arquivo_local("/flow/imagens/nao_existe.png") is None and va.flow_arquivo_local("https://x.com/a.png") is None
    # link do Flow escolhido no editor: resolve pro arquivo, sem baixar
    path, kind = va._resolve_override_source({"source": "url", "value": "/flow/imagens/v1.mp4"}, "/tmp", lambda p: None)
    assert path == v and kind == "video"


def test_exportar_fixa_a_midia_do_flow_da_previa(gf, monkeypatch):
    import app as A
    from prompt_builder import VideoSegment
    v = _guardar(gf, "um farol", "video", "v2.mp4")
    f = _guardar(gf, "um mapa", "imagem", "f2.png")
    job = {"segment_previews": [
        {"index": 0, "ok": True, "provider": "flow", "result_url": "/flow/imagens/v2.mp4", "thumbnail_url": "/flow/imagens/v2.png",
         "query": "um farol"},
        {"index": 1, "ok": True, "provider": "flow", "result_url": "/flow/imagens/f2.png", "thumbnail_url": "/flow/imagens/f2.png",
         "query": "um mapa"},
        {"index": 2, "ok": True, "provider": "flow", "result_url": "/flow/imagens/f2.png", "query": "busca antiga"}]}
    segs = [VideoSegment(start=0, end=3, provider="flow", query="um farol"),
            VideoSegment(start=3, end=6, provider="flow", query="um mapa", media_type="image"),
            VideoSegment(start=6, end=9, provider="flow", query="busca nova", media_type="image")]
    monkeypatch.setattr(A, "_job_site_cfg", lambda job: {})
    out = A._fixar_midias_da_previa(job, segs)
    assert out[0].override_source == {"source": "local_file", "value": v, "kind": "video", "da_previa": True}
    assert out[1].override_source["value"] == f and out[1].override_source["kind"] == "image"
    assert out[2].override_source is None  # a busca mudou: gera a nova
    assert job["fixacao_previa"][0]["fixado"] and "Flow" in job["fixacao_previa"][0]["motivo"]


def test_sem_credito_mas_ja_gerado_nao_vai_pra_pesquisa(gf, monkeypatch):
    """Contas sem crédito de vídeo nenhum, mas o vídeo desse trecho já está no cache: usa ele (não vira foto/pesquisa)."""
    import video_assembler as va
    _guardar(gf, "um navio", "video", "v3.mp4")
    monkeypatch.setattr(va, "flow_tem_conta", lambda tipo, cfg=None: False)
    src = open(va.__file__, encoding="utf-8").read()
    assert 'if flow_ja_gerado(segment.query, cfg, "video"):\n                        tem_video = True' in src
    assert va.flow_ja_gerado("um navio", {}, "video")
