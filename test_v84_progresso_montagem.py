"""v84_114 — a montagem mostra as etapas (feitas / rodando / puladas / que faltam), quando começou, quanto falta
de cada etapa e do total; nas etapas finais a fração vem do próprio ffmpeg (-progress)."""
import subprocess

import progresso_ffmpeg as pf


def _base(tmp_path, d=4):
    base = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:d={d}:r=30", "-f", "lavfi", "-i", f"sine=d={d}",
                    "-pix_fmt", "yuv420p", "-shortest", str(base)], check=True)
    return str(base)


def test_rodar_avisa_o_andamento_do_ffmpeg(tmp_path):
    base = _base(tmp_path)
    visto = []
    with pf.acompanhar(lambda f, d: visto.append((round(f, 3), d)), 4.0):
        with pf.parte(2, 2, "segunda metade"):
            r = pf.rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", base, "-c:v", "libx264", "-preset", "ultrafast", str(tmp_path / "o.mp4")])
    assert r.returncode == 0
    assert visto[0] == (0.5, "segunda metade") and visto[-1] == (1.0, "segunda metade")
    assert all(0.5 <= f <= 1.0 for f, _d in visto)
    # fora do acompanhar: igual ao subprocess.run de sempre
    r = pf.rodar(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "nao_existe.mp4", "-f", "null", "-"])
    assert r.returncode != 0 and "nao_existe" in r.stderr


def test_destaques_em_lotes_dizem_qual_lote(tmp_path):
    import dp_destaques as dd
    base = _base(tmp_path)
    ds = [{"estilo": "selo_ano", "start": k * 0.8, "end": k * 0.8 + 0.6, "texto": f"T{k}", "fundo": "faixas",
           "fundo_cor": f"#{k * 40:02X}2020"} for k in range(4)]
    visto = []
    with pf.acompanhar(lambda f, d: visto.append((f, d)), 4.0):
        dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), ds, 320, 180, str(tmp_path / "w"), lote=2)
    detalhes = [d for _f, d in visto]
    assert "fundos: lote 1 de 2 (até 2 por vez)" in detalhes and "textos (último passe)" in detalhes
    fr = [f for f, _d in visto]
    assert fr == sorted(fr) and fr[-1] == 1.0  # só anda pra frente


def test_etapas_e_estimativas():
    import app as A
    job = {"progress": {"etapas": [{"id": e, "nome": e, "estado": "pendente"} for e in ("iniciando", "processando", "concatenando", "destaques")]}}
    A._progresso_etapa(job, "iniciando", 0, 1, agora=100.0)
    A._progresso_etapa(job, "processando", 2, 10, agora=110.0)
    p = A._progresso_etapa(job, "processando", 5, 10, agora=130.0)
    assert p["estimated_seconds_remaining"] == 20 and p["inicio"] == 100.0 and p["nome"] == "processando"
    p = A._progresso_etapa(job, "destaques", 250, 1000, "lote 1 de 3", agora=200.0)
    estados = {e["id"]: e["estado"] for e in p["etapas"]}
    assert estados == {"iniciando": "feita", "processando": "feita", "concatenando": "pulada", "destaques": "rodando"}
    assert p["detalhe"] == "lote 1 de 3"
    p = A._progresso_etapa(job, "destaques", 500, 1000, agora=260.0)
    assert p["estimated_seconds_remaining"] == 60 and p["eta_total"] == 60  # nada depois dela
    # etapa fora do plano entra depois da que está rodando
    p = A._progresso_etapa(job, "graficos", 0, 1000, agora=270.0)
    assert [e["id"] for e in p["etapas"]][-1] == "graficos" and p["etapas"][-2]["estado"] == "feita"


def test_pagina_de_status_tem_as_etapas():
    import app as A
    A.app.config["TESTING"] = True
    A._JOBS["prog1"] = {"job_id": "prog1", "status": "montando", "progress": {"stage": "destaques", "current": 1, "total": 2}}
    try:
        c = A.app.test_client()
        h = c.get("/job/prog1/status-page").get_data(as_text=True)
        assert 'id="mt-etapas"' in h and "começou às" in h and "falta ~" in h and "previsão" in h
        assert c.get("/job/prog1/status").get_json()["progress"]["stage"] == "destaques"
    finally:
        A._JOBS.pop("prog1", None)


def test_graficos_e_quadros_contam_cada_passo(tmp_path):
    """v84_118: as etapas que desenham em Python antes do ffmpeg (gráficos, quadros) também andam a barra."""
    import dp_graficos
    base = _base(tmp_path, 6)
    visto = []
    with pf.acompanhar(lambda f, d: visto.append((round(f, 3), d)), 6.0):
        dp_graficos.aplicar_graficos(base, str(tmp_path / "g.mp4"), [{"tipo": "barras", "titulo": "X", "dados": [["a", 5], ["b", 8]],
                                                                      "start": 1.0, "end": 4.0}], 320, 180, str(tmp_path / "wg"))
    detalhes = [d for _f, d in visto]
    assert "desenhando o gráfico 1 de 1" in detalhes and "colocando os gráficos no vídeo" in detalhes
    assert visto[0][0] == 0.0 and visto[-1][0] == 1.0 and [f for f, _d in visto] == sorted(f for f, _d in visto)


def test_pagina_continua_quando_o_servidor_falha():
    html = open("templates/result.html", encoding="utf-8").read()
    assert "falhasSeguidas++" in html and "setInterval(tique, 1000)" in html and "mt-sem-resposta" in html
