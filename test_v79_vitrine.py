"""v79 — correções achadas montando o vídeo-vitrine com a própria ferramenta."""
import json

from PIL import Image

import app as app_module
import dp_graficos


def test_resolucao_do_modal_montar_chega_na_montagem():
    assert app_module._job_site_cfg({"export_quality": "720p"})["export_quality"] == "720p"
    # valor inválido não sobrepõe a configuração do site
    base = app_module.load_site_config().get("export_quality", "1080p")
    assert app_module._job_site_cfg({"export_quality": "999p"}).get("export_quality", "1080p") == base


def test_sons_da_ia_guardam_origem_pra_nao_duplicar():
    job = {}

    class F(dict):
        pass
    form = F(sfx_json=json.dumps([
        {"id": "a", "som": "impacto/riser_5", "start": 1.0, "volume": 0.5, "origem": "ia"},
        {"id": "b", "som": "impacto/riser_5", "start": 2.0, "volume": 0.5},
    ]))
    app_module._sfx_do_form(job, form)
    assert [x.get("origem") for x in job["sfx"]] == ["ia", None]


def test_comparacao_com_numeros_grandes_nao_encosta(tmp_path):
    g = dp_graficos.normalizar({"tipo": "comparacao", "titulo": "Diâmetro", "unidade": "km", "start": 0, "end": 5,
                                "posicao": "esquerda", "dados": [{"rotulo": "Júpiter", "valor": 139820},
                                                                 {"rotulo": "Terra", "valor": 12742}]})
    destino = str(tmp_path / "c.png")
    dp_graficos.previa_png(g, 1280, 720, destino)
    im = Image.open(destino).convert("RGB")
    assert im.size == (1280, 720)
