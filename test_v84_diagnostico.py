"""
Vídeo exportado = telinha do Estúdio (v84_20) + diagnóstico pós-export.

- destaques: mesma quebra de linha, tamanho de letra e fonte da telinha
  (o \\fs do libass é convertido; a quebra usa a largura real das letras);
- fundo "escurecer" multiplica a luz como a camada preta da telinha;
- fundo próprio das cenas não é pintado pela paleta (a telinha não pinta);
- takes dentro de cena não ganham entrada/saída (a telinha não mostra);
- cada trecho registra por que usou (ou não) o clipe da telinha;
- diagnostico_export.txt aponta fonte/quebra/escurecimento/clipe trocado.
"""
import json
import os
import subprocess

import pytest

import cenas_dp
import dp_destaques
import dp_fundos


def _video(path, cor="0x808080", dur=3, s="320x180"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color={cor}:s={s}:d={dur}:r=25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)
    return path


class TestDestaqueIgualTelinha:
    def test_quebra_como_a_telinha_no_centro(self):
        d = {"id": "a", "estilo": "glow_01", "texto": "Built on purpose", "fonte": "playfair", "maiusculas": False, "start": 0, "end": 3}
        m = dp_destaques.medidas_texto(d, 1920, 1080)
        # a telinha quebra no espaço à direita da âncora (50% no centro): 2 linhas
        assert m["linhas"] == ["Built on", "purpose"]
        assert abs(m["tam_px"] - 0.12 * 1080) < 1
        assert m["fonte"] == "DP Playfair Display"

    def test_fs_do_libass_compensa_a_celula_da_fonte(self):
        # libass mede a "célula" (ascendente+descendente): pra mesma letra o \fs precisa ser maior
        assert dp_destaques.fs_libass("DP Playfair Display", 100) > 120
        assert dp_destaques.fs_libass("DP Anton", 100) > dp_destaques.fs_libass("DP Cinzel", 100)

    def test_texto_longo_encolhe_como_a_telinha(self):
        d = {"id": "b", "estilo": "glow_06", "texto": "Here's something most people never notice", "fonte": "playfair", "maiusculas": False, "start": 0, "end": 3}
        m = dp_destaques.medidas_texto(d, 1920, 1080)
        assert abs(m["tam_px"] - 0.082 * 1080 * 0.7) < 1  # > 40 letras: 70%, igual à telinha
        assert len(m["linhas"]) == 2

    def test_ass_sem_contorno_grosso_e_com_fs_convertido(self, tmp_path):
        d = {"id": "a", "estilo": "glow_01", "texto": "Built on purpose", "fonte": "playfair", "maiusculas": False, "start": 0, "end": 3}
        ass = dp_destaques.gerar_ass([d], 1920, 1080, str(tmp_path / "d.ass"))
        txt = open(ass, encoding="utf-8").read()
        m = dp_destaques.medidas_texto(d, 1920, 1080)
        assert f"\\fs{m['fs_ass']}" in txt and "\\N" in txt
        assert "\\3a&HFF&" in txt  # contorno invisível: só a sombra suave, como na telinha

    def test_alinhado_a_direita_nao_quebra_palavra_por_linha(self):
        e = next(k for k, h in dp_destaques.catalogo().items() if h.get("forma") == "centro_frase")
        d = {"id": "c", "estilo": e, "texto": "Uma frase curta aqui", "zona": "canto_tr", "start": 0, "end": 3}
        m = dp_destaques.medidas_texto(d, 1920, 1080)
        assert len(m["linhas"]) <= 2 and m["an"] == 9


class TestEscurecerIgualTelinha:
    def test_camada_preta_multiplica(self, tmp_path):
        f = dp_fundos.escurecer_igual_previa(0.35, "1", None, "0:v").replace("[0:v]", "")
        out = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=0x4D4D4D:s=64x64:d=0.1", "-vf",
                              "format=yuv420p," + f + ",format=rgb24", "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True).stdout
        r = out[64 * 32 * 3 + 96]
        assert abs(r - int(0x4D * 0.65)) <= 4  # antes (brightness -0.22) dava ~22

    def test_etapa_do_escurecer_usa_multiplicacao(self, tmp_path):
        et, png = dp_fundos.etapas_destaque("escurecer", "#000000", 1.0, 1.0, 3.0, 640, 360, str(tmp_path))
        assert png is None and "contrast=" in et[0] and "brightness='-" not in et[0]

    def test_vinheta_nao_escurece_o_centro(self, tmp_path):
        et, png = dp_fundos.etapas_destaque("vinheta", "#000000", 1.0, 1.0, 3.0, 640, 360, str(tmp_path))
        from PIL import Image
        im = Image.open(png)
        assert im.getpixel((320, 180))[3] == 0 and im.getpixel((0, 0))[3] > 150


class TestCenas:
    def test_fundo_do_template_fica_com_a_cor_dele(self):
        tid = "C30_SEPTO_VIVO"
        pal = {"primaria": "#FFD60A"}
        nativo = cenas_dp.fundos_do_template(tid)[0]
        assert cenas_dp.fundo_tom(tid, nativo, None, pal) is None
        assert cenas_dp.fundo_tom(tid, nativo, "#123456", pal) == "#123456"
        assert cenas_dp.fundo_tom(tid, "grade", None, pal) == "#FFD60A"

    def test_take_dentro_de_cena_nao_ganha_entrada(self, tmp_path, monkeypatch):
        import video_assembler as V
        from video_assembler import VideoSegment
        segs = [VideoSegment(start=0, end=2, provider="pexels", query="a", entrada="slide_left"),
                VideoSegment(start=2, end=4, provider="pexels", query="b", entrada="slide_left")]
        chamados = []
        import dp_visual
        monkeypatch.setattr(dp_visual, "pos_processar_clipe", lambda *a, **k: chamados.append(a[0]) or False)
        V._aplicar_gestos(segs, ["x0.mp4", "x1.mp4"], [2, 2], [("none", 0), ("none", 0)], {0: 1, 1: 1}, 640, 360,
                          str(tmp_path), str(tmp_path), 1, em_cena={0, 1})
        assert chamados == []


class TestFixacaoEDiagnostico:
    def _job(self, A, job_id, tmp_path):
        os.makedirs(A._job_dir(job_id), exist_ok=True)
        segs = [{"start": 0.0, "end": 3.0, "provider": "pexels", "query": "nova busca", "media_type": "video", "override_source": None}]
        A._JOBS[job_id] = {"job_id": job_id, "status": "pronto_para_editar", "created_at": 1.0, "total_duration": 3.0,
                           "pending_segments": segs, "segment_previews": [{"index": 0, "ok": True, "result_url": "https://www.pexels.com/video/x-123456/",
                                                                           "provider": "pexels", "query": "busca antiga", "video_preview_url": "https://cdn/x.mp4"}],
                           "overlays": [], "cutaway_suggestions": [], "media_library": []}
        return A._JOBS[job_id]

    def test_motivo_de_nao_fixar_fica_registrado(self, tmp_path):
        import app as A
        from video_assembler import VideoSegment
        job = self._job(A, "diag-fix", tmp_path)
        segs = A._fixar_midias_da_previa(job, [VideoSegment(start=0, end=3, provider="pexels", query="nova busca")])
        assert segs[0].override_source is None
        assert "busca mudou" in job["fixacao_previa"][0]["motivo"]

    def test_relatorio_aponta_fonte_quebra_e_clipe(self, tmp_path):
        import app as A
        import diagnostico_export
        job = self._job(A, "diag-rel", tmp_path)
        jd = A._job_dir("diag-rel")
        clipe = _video(str(tmp_path / "clipe.mp4"))
        final = _video(str(tmp_path / "final.mp4"), cor="0x202020")  # bem mais escuro que o clipe
        job["video_segments"] = job["pending_segments"]
        job["destaques"] = [{"id": "h1", "estilo": "glow_01", "texto": "Built on purpose", "fonte": "playfair", "maiusculas": False, "start": 0.5, "end": 2.5}]
        job["fixacao_previa"] = [{"trecho": 1, "fixado": False, "motivo": "a busca mudou depois da prévia", "video_previa": "https://cdn/x.mp4"}]
        json.dump({"trechos": [{"trecho": 1, "inicio": 0, "fim": 3, "origem": {"modo": "busca_nova", "kind": "video", "arquivos": [clipe]},
                                "clipe_normalizado": clipe, "corta_quadros_inicio": 0}],
                   "pedacos": [{"pedaco": 1, "esperado": 3.0, "real": 3.0}], "duracao_narracao": 3.0, "grupos_cena": [], "config": {}},
                  open(os.path.join(jd, "montagem_relatorio.json"), "w"))
        foto = {"t": 1.5, "trecho": 1, "filtro_css": "", "destaques": [{"id": "h1", "estilo": "glow_01", "texto": "Built on purpose",
                "familia": "Georgia", "fonte_carregada": False, "tamanho_rel": 0.12, "linhas": ["Built on purpose"], "rect": [0.3, 0.4, 0.4, 0.2],
                "fundo": {"id": "nenhum", "intensidade": 1}}]}
        json.dump({"fotos": [foto], "trechos": [{"trecho": 1, "url_na_telinha": "https://cdn/x.mp4", "query": "busca antiga"}]},
                  open(os.path.join(jd, "previa_snapshot.json"), "w"))
        txt = open(diagnostico_export.gerar("diag-rel", job, jd, final), encoding="utf-8").read()
        assert "FONTE DIFERENTE" in txt and "NÃO estava carregada" in txt
        assert "Quebra de linha diferente" in txt
        assert "TROCADO" in txt
        assert "MAIS ESCURO" in txt

    def test_rota_de_download(self, tmp_path):
        import app as A
        A.app.config["TESTING"] = True
        c = A.app.test_client()
        self._job(A, "diag-rota", tmp_path)
        assert c.get("/job/diag-rota/download-diagnostico").status_code == 404
        with open(os.path.join(A._job_dir("diag-rota"), "diagnostico_export.txt"), "w", encoding="utf-8") as f:
            f.write("DIAGNÓSTICO teste")
        r = c.get("/job/diag-rota/download-diagnostico?ver=1")
        assert r.status_code == 200 and "DIAGNÓSTICO teste" in r.get_data(as_text=True)
