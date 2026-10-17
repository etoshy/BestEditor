import dp_destaques
import dp_editorial


def test_linha_tempo_aceita_data_com_dois_pontos():
    assert dp_editorial._itens_linha_tempo("1969: Verlässt Berkeley\nJUN | fato\n1978 – Fabrik") == [
        ("1969", "Verlässt Berkeley"), ("JUN", "fato"), ("1978", "Fabrik")]


def test_ficha_sem_ponto_do_rosto():
    assert "ponto_x" not in [c[0] for c in dp_editorial.campos("ficha")]


def test_destaque_da_ia_sai_de_cima_de_quadro_com_texto():
    ds = [{"start": 1, "end": 3, "origem": "ia"}, {"start": 1, "end": 3}, {"start": 10, "end": 12, "origem": "ia"}]
    fica = dp_destaques.sem_conflito(ds, [{"start": 0, "end": 5}], [])
    assert len(fica) == 2 and all(not (d.get("origem") == "ia" and d["start"] == 1) for d in fica)
