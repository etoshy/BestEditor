"""v84_119 — o fim do vídeo não congela mais: pedaço paralelo com quadros faltando → o passe roda do jeito de sempre;
etapa que devolve a imagem mais curta que o áudio → é pulada (com aviso) em vez de entregar um vídeo congelado."""
import json
import os
import subprocess

import export_paralelo as ep


def _base(tmp_path, d=12, nome="b.mp4"):
    base = tmp_path / nome
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:d={d}:r=30", "-f", "lavfi", "-i", "sine=d=12",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(base)], check=True)
    return str(base)


def test_mede_a_imagem_nao_o_arquivo(tmp_path):
    cheio, curto = _base(tmp_path), _base(tmp_path, 7, "curto.mp4")  # imagem 7 s, áudio 12 s
    assert abs(ep.duracao_do_video(cheio) - 12) < 0.1 and abs(ep.duracao_do_video(curto) - 7) < 0.1
    assert ep.contar_quadros(curto) == 210


def test_pedaco_curto_cai_pro_jeito_de_sempre(tmp_path, monkeypatch):
    base = _base(tmp_path)
    monkeypatch.setattr(ep, "MIN_PEDACO_S", 1.0)
    real = ep.contar_quadros
    monkeypatch.setattr(ep, "contar_quadros", lambda c: 30 if c.endswith("_f03.mp4") else real(c))  # o 4º pedaço "veio curto"
    assert ep.tentar("teste", lambda: ep.vf_em_pedacos(base, str(tmp_path / "o.mp4"), "hue=s=0", 12.0,
                                                       str(tmp_path / "w"), "f", n=4)) is None


def test_etapa_que_corta_a_imagem_e_pulada(tmp_path):
    import video_assembler as va
    cheio, curto = _base(tmp_path), _base(tmp_path, 7, "curto.mp4")
    assert va._etapa_inteira(cheio, cheio, "x", str(tmp_path)) is True
    assert va._etapa_inteira(cheio, curto, "destaques de texto", str(tmp_path)) is False
    avisos = json.load(open(tmp_path / "avisos_montagem.json", encoding="utf-8"))
    assert "destaques de texto" in avisos[0] and "0:07" in avisos[0] and "PULADA" in avisos[0]
    src = open("app.py", encoding="utf-8").read()
    assert '"avisos_montagem": job.get("avisos_montagem")' in src and "avisos-montagem" in open("templates/result.html", encoding="utf-8").read()
