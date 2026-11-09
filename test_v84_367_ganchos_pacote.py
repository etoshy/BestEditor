"""v84_367: ganchos genéricos que um pacote de canal pode usar (ex.: CenarioM, canal de filosofia realista).

- brand_guide.generation_system.allowed_image_types / image_types_en / real_subject_render_en
- modelo_roteiro.json: "chamadas": {"venda": 0} (canal sem venda) e "escopo_enxuto"
- pacote.json producao_pod: "intervalo", "intervalo_min", "intervalo_max" (troca de imagem de 5 a 10 s)
"""
import cenas_lote
import canal_pod
import marca_visual as mv
import roteiro_partes as rp
import roteiros_yt


def _marca(gs=None):
    return {"slug": "x", "dir": "/nao/existe", "guia": {"generation_system": gs or {}}}


def test_tipos_imagem_filtrados_pela_marca():
    m = _marca({"allowed_image_types": ["ambiente", "close"]})
    assert set(mv.tipos_imagem_da_marca(m)) == {"ambiente", "close", "mascote"}
    assert set(canal_pod.tipos_imagem(m, {"estilo_fotos": "foto"})) == {"ambiente", "close"}
    # sem o campo: todos, como antes
    assert set(mv.tipos_imagem_da_marca(_marca())) == set(mv.TIPOS_IMAGEM)
    # lista só com tipos desconhecidos não zera a escolha
    assert set(mv.tipos_imagem_da_marca(_marca({"allowed_image_types": ["xyz"]}))) == set(mv.TIPOS_IMAGEM)


def test_prompt_usa_textos_da_marca_pra_tipo_e_foto_real():
    m = _marca({"style_lock_en": "Photorealistic film still.", "allowed_image_types": ["ambiente"],
                "image_types_en": {"ambiente": "wide realistic shot"},
                "real_subject_render_en": "as a living person in full color"})
    cena = {"tipo": "cena", "assunto_en": "a philosopher in the agora", "tipo_imagem": "ambiente",
            "fotos_info": [{"descricao_en": "marble bust", "estilo": "foto"}]}
    p = mv.montar_prompt(m, cena, [("foto_1", "/x.jpg")])
    assert "Image type: wide realistic shot." in p
    assert "as a living person in full color" in p
    assert "grayscale archival" not in p
    # tipo fora da lista da marca não entra
    assert "Image type" not in mv.montar_prompt(m, dict(cena, tipo_imagem="arquivo", fotos_info=[]))


def test_prompt_sem_ganchos_continua_igual():
    m = _marca({"style_lock_en": "Noir collage."})
    cena = {"tipo": "cena", "assunto_en": "a lighthouse", "tipo_imagem": "arquivo",
            "fotos_info": [{"descricao_en": "", "estilo": "foto"}]}
    p = mv.montar_prompt(m, cena, [("foto_1", "/x.jpg")])
    assert "Image type: monochrome archival photograph." in p
    assert "grayscale archival photograph" in p


def test_regra_marcas_sem_venda():
    r = roteiros_yt.regra_marcas(1, 0)
    assert "- [[VENDA]] =" not in r and "NÃO use [[VENDA]]" in r
    assert "UMA SÓ" in r
    assert roteiros_yt.regra_marcas(1) == roteiros_yt.regra_marcas(1, None)
    assert "- [[VENDA]] =" in roteiros_yt.regra_marcas()
    r0 = roteiros_yt.regra_marcas(0, 0)
    assert "- [[INSCREVA]]" not in r0 and "- [[VENDA]] =" not in r0


def test_montar_partes_sem_venda():
    partes = [{"titulo": f"P{i}", "texto": " ".join(["palavra"] * 400)} for i in range(6)]
    com, _ = rp.montar(partes, True, 0, max_inscreva=1)
    sem, _ = rp.montar(partes, True, 0, max_inscreva=1, max_venda=0)
    assert "[[VENDA]]" in com
    assert "[[VENDA]]" not in sem and sem.count("[[INSCREVA]]") == 1


def _segs(n=60, dur=0.5):
    return [{"start": i * dur, "end": i * dur + dur * 0.9, "text": f"palavra{i}." if i % 4 == 3 else f"palavra{i}",
             "words": [{"word": f"palavra{i}." if i % 4 == 3 else f"palavra{i}", "start": i * dur, "end": i * dur + dur * 0.9}]}
            for i in range(n)]


def test_cortar_cenas_com_faixa_do_canal():
    cenas = cenas_lote.cortar_cenas(_segs(200), 7.5, minimo=5, maximo=10)
    durs = [c["end"] - c["start"] for c in cenas[:-1]]
    assert durs and all(4.9 <= d <= 10.1 for d in durs), durs
    # sem faixa: o padrão de sempre (0,6× a 1,4×)
    assert cenas_lote.cortar_cenas(_segs(200), 5.0) == cenas_lote.cortar_cenas(_segs(200), 5.0, minimo=None, maximo=None)


def test_intervalos_do_pacote():
    assert canal_pod.intervalos({"intervalo": 7.5, "intervalo_min": 5, "intervalo_max": 10}) == \
        {"intervalo": 7.5, "intervalo_min": 5.0, "intervalo_max": 10.0}
    assert canal_pod.intervalos({"intervalo_min": 10, "intervalo_max": 5})["intervalo"] == 7.5
    assert canal_pod.intervalos({}) == {"intervalo": None, "intervalo_min": None, "intervalo_max": None}
    assert canal_pod.intervalos({"intervalo": "abc"})["intervalo"] is None
