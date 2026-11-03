"""v84_339: gravar a sua voz em pedaços menores — por bloco do roteiro, até o ponto ou frases curtas (vírgula, ; e :).
A legenda continua sincronizada porque o Whisper lê a gravação inteira (processar_gravacao) e alinha ao roteiro."""
import curtos as CT
import gravar_voz as GV
from test_v84_320_lote_por_etapa import _app
from test_v84_325_minha_voz import _som


def _proj(base):
    p = CT.criar(base, "", "t", modelo="comentario")
    p["roteiro"] = {"idioma": "en", "blocos": [
        {"id": "B1", "fala": "This sloth is slow. But honestly, it can swim really fast, way faster than you think.",
         "fala_pt": "Essa preguiça é lenta. Mas sinceramente, ela nada muito rápido, bem mais do que você pensa."},
        {"id": "B2", "fala": "Wild, right?"}]}
    CT.salvar(base, p)
    return p["id"]


def test_frases_curtas():
    assert GV.frases_curtas("Hoje, eu vou testar o microfone novo, e ele parece bom. Ok.") == \
        ["Hoje, eu vou testar o microfone novo,", "e ele parece bom.", "Ok."]
    assert GV.separar_texto("Uma frase aqui, outra parte longa aqui. Fim.", "curta") == ["Uma frase aqui,", "outra parte longa aqui.", "Fim."]


def test_divisao_takes_e_juntar(tmp_path, monkeypatch):
    base = str(tmp_path)
    monkeypatch.setenv("CURTOS_DIR", str(tmp_path / "c"))
    pid = _proj(base)
    assert [x["id"] for x in GV.partes_de(base, pid)] == ["B1", "B2"] and GV.resumo(base, pid)["divisao"] == "bloco"
    GV.adicionar_take(base, pid, "B1", _som(str(tmp_path / "a.wav"), 1.0))  # um take gravado na divisão por bloco
    r = GV.trocar_divisao(base, pid, "frase")
    ids = [x["id"] for x in r["partes"][1:]]
    assert ids == ["B1_1", "B1_2", "B2"] and r["divisao"] == "frase"
    assert r["partes"][1]["traducao"] == "Essa preguiça é lenta."  # a tradução dividida junto
    assert GV.faltando(base, pid) == ids  # os pedaços novos estão por gravar
    r = GV.trocar_divisao(base, pid, "curta")
    assert [x["id"] for x in r["partes"][1:]] == ["B1_1", "B1_2", "B1_3", "B2"]
    for k, parte in enumerate(["B1_1", "B1_2", "B1_3", "B2"]):
        GV.adicionar_take(base, pid, parte, _som(str(tmp_path / f"{parte}.wav"), 0.5, 300 + 100 * k))
    assert GV.faltando(base, pid) == []
    dur = CT.duracao_audio(GV.juntar(base, pid))
    assert abs(dur - (4 * 0.5 + 4 * GV.PAUSA_ENTRE_PARTES_S)) < 0.3  # os 4 pedaços, na ordem
    assert GV.trocar_divisao(base, pid, "bloco")["faltando"] == []  # voltar: o take do B1 de antes continua lá (e o B2 é o mesmo)
    try:
        GV.trocar_divisao(base, pid, "inventada")
        raise AssertionError
    except CT.CurtoErro:
        pass


def test_rota_divisao(tmp_path, monkeypatch):
    cl = _app(tmp_path, monkeypatch)
    pid = _proj(str(tmp_path))
    j = cl.post(f"/curtos/{pid}/voz/divisao", json={"divisao": "curta"}).get_json()
    assert j["ok"] and j["estado"]["divisao"] == "curta" and len(j["estado"]["partes"]) == 5
    html = cl.get(f"/curtos/{pid}/gravar").get_data(as_text=True)
    assert 'id="divisao"' in html and 'value="curta"' in html
    assert cl.post(f"/curtos/{pid}/voz/divisao", json={"divisao": "x"}).status_code == 400
