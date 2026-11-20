"""v84_438 — base numerada (número AO LADO, sem cobrir) e prancha de referências (mais de 6 imagens)."""
import os

from PIL import Image

import flow_montar as FM
import flow_rascunho as FR


def _img(p, cor):
    Image.new("RGB", (400, 300), cor).save(p)
    return str(p)


def test_numero_ao_lado_nao_cobre_o_ponto(tmp_path):
    base = _img(tmp_path / "b.png", (200, 230, 200))
    out = FR.desenhar_marcas(base, str(tmp_path / "n.png"), [{"n": 1, "x": 0.5, "y": 0.5, "tipo": "pessoa"}], ao_lado=True)
    im = Image.open(out)
    assert im.getpixel((200, 150))[0] > 150  # o ponto marcado não ficou embaixo do círculo vermelho grande
    ex, ey = FR._lugar_da_etiqueta({"x": 0.5, "y": 0.5}, [], 400, 300, 14)
    assert (ex, ey) != (200, 150)


def test_prancha_e_base_numerada(tmp_path):
    base = _img(tmp_path / "base.png", (220, 220, 220))
    itens = [{"papel": "base", "arquivo": base, "marcas": [{"x": .3, "y": .4}, {"x": .7, "y": .4}, {"x": .5, "y": .8, "tipo": "objeto"}]}]
    cores = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255), (90, 90, 90)]
    for k, c in enumerate(cores):
        alvo = f"entra no lugar da figura {k + 1}" if k < 2 else ("no lugar do elemento 3" if k == 2 else "")
        itens.append({"papel": "personagem" if k < 2 else "objeto", "nome": f"P{k}", "obs": alvo,
                      "arquivo": _img(tmp_path / f"r{k}.png", c)})
    pac = FM.novo_pacote(str(tmp_path), itens, "", "", base_numerada=True)  # 8 imagens → prancha sozinha
    assert pac.get("prancha") and os.path.isfile(pac["prancha"]) and pac["base_numerada"]
    paineis = [r.get("painel") for r in pac["refs"][1:]]
    assert paineis[:3] == ["1", "2", "3"] and paineis[3] == "A"
    refs = FM.referencias_flow(pac)
    assert len(refs) == 2 and refs[0]["arquivo"].endswith("_base_numerada.png") and refs[1]["papel"] == "prancha"
    p = FM.prompt_basico(pac)
    assert "the panel marked 1 on the reference sheet (reference image 2)" in p and "REMOVE them completely" in p
    assert "REFERENCE SHEET" in p and "COMPLETELY replaced" in p
    blocos = FM.conteudo_ia(pac, lambda f: None)
    assert any("HOW FLOW RECEIVES" in b.get("text", "") for b in blocos)


def test_sem_opcoes_igual_antes(tmp_path):
    base = _img(tmp_path / "base.png", (220, 220, 220))
    pac = FM.novo_pacote(str(tmp_path), [{"papel": "base", "arquivo": base},
                                         {"papel": "personagem", "nome": "Ana", "arquivo": _img(tmp_path / "a.png", (1, 2, 3))}])
    assert not pac.get("prancha") and not pac["base_numerada"]
    assert [r["arquivo"] for r in FM.referencias_flow(pac)] == [r["arquivo"] for r in pac["refs"]]
    assert "reference image 2" in FM.prompt_basico(pac)
