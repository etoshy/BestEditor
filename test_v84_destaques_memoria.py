"""v84_113 — muitos destaques num vídeo longo estouravam a memória do ffmpeg ("Cannot allocate memory"): agora refaz
em lotes de fundos (e cai pela metade se ainda faltar), com os textos no último passe."""
import subprocess

import dp_destaques as dd


def _base(tmp_path, d=6):
    base = tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:d={d}:r=30", "-f", "lavfi", "-i", f"sine=d={d}",
                    "-pix_fmt", "yuv420p", "-shortest", str(base)], check=True)
    return str(base)


def _ds(n, d=6.0):
    fundos = ["faixas", "vinheta", "grade", "gradiente", "linhas", "ondas", "desfoque", "escurecer"]
    passo = d / n
    return [{"estilo": "selo_ano", "start": round(k * passo, 2), "end": round(k * passo + passo * 0.8, 2), "texto": f"T{k}",
             "fundo": fundos[k % len(fundos)], "fundo_cor": f"#{(k * 37) % 256:02X}40{(k * 91) % 256:02X}"} for k in range(n)]


def _dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip())


def test_sem_memoria_refaz_em_lotes_cada_vez_menores(tmp_path, monkeypatch):
    base = _base(tmp_path)
    chamadas = []
    real = dd._passe_destaques

    def falso(video_in, video_out, ent, etapas, ass, work_dir, nome, dur, poupar=False):
        n_png = len(etapas)  # v84_117: os fundos com imagem viram UMA faixa — conta as etapas do grafo
        chamadas.append((nome, n_png, bool(ass)))
        if (nome == "" or n_png > 3) and etapas:  # o passe único e lotes "grandes" estouram
            return subprocess.CompletedProcess([], 1, "", "[fc#0] Error while filtering: Cannot allocate memory")
        return real(video_in, video_out, ent, etapas, ass, work_dir, nome, dur, poupar)
    monkeypatch.setattr(dd, "_passe_destaques", falso)
    out = dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), _ds(12), 320, 180, str(tmp_path / "w"))
    assert abs(_dur(out) - 6.0) < 0.15
    assert chamadas[0][0] == "" and chamadas[-1][0] == "_textos" and chamadas[-1][2]
    lotes = [n for nome, n, _a in chamadas if nome.startswith("_lote")]
    assert lotes[0] > 3 and all(n <= 3 for n in lotes[-2:])  # tentou lote grande, estourou, caiu pela metade até caber
    assert not list((tmp_path / "w").glob("_destaques_lote*.mp4"))  # temporários apagados


def test_outro_erro_nao_vira_lote(tmp_path, monkeypatch):
    base = _base(tmp_path, 2)
    monkeypatch.setattr(dd, "_passe_destaques", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "Invalid argument"))
    try:
        dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), _ds(2, 2.0), 320, 180, str(tmp_path / "w"))
        raise AssertionError("devia falhar")
    except RuntimeError as exc:
        assert "Invalid argument" in str(exc) and "lote" not in str(exc)


def test_lote_forcado_gera_o_mesmo_video(tmp_path):
    base = _base(tmp_path)
    out = dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), _ds(6), 320, 180, str(tmp_path / "w"), lote=2)
    assert abs(_dur(out) - 6.0) < 0.15
    assert dd._sem_memoria("Task finished with error code: -12 (Cannot allocate memory)", 1) and not dd._sem_memoria("x", 1)


def test_muitas_imagens_ja_vai_direto_em_lotes(tmp_path, monkeypatch):
    base = _base(tmp_path)
    nomes = []
    real = dd._passe_destaques
    monkeypatch.setattr(dd, "_passe_destaques", lambda *a, **k: nomes.append(a[6]) or real(*a, **k))
    monkeypatch.setattr(dd, "MAX_IMAGENS_PASSE_UNICO", 0)
    dd.aplicar_destaques(base, str(tmp_path / "o.mp4"), _ds(10), 320, 180, str(tmp_path / "w"))
    assert "" not in nomes and nomes[0] == "_lote1" and nomes[-1] == "_textos"
