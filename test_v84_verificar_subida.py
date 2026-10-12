"""v84_63 — subir o projeto pro GitHub sem dados obtidos nem nada sensível (verificar_antes_de_subir.py + .gitignore)."""
import os
import shutil
import subprocess

import pytest

import verificar_antes_de_subir as v

AQUI = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("sem git")
    shutil.copy(os.path.join(AQUI, ".gitignore"), tmp_path / ".gitignore")
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.email", "dono@exemplo.com"], check=True)
    return tmp_path


def _add(*arquivos):
    subprocess.run(["git", "add", "-A"], check=True)
    if arquivos:
        subprocess.run(["git", "add", "-f", *arquivos], check=True)


def _escreve(caminho, texto="x"):
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)


def test_gitignore_deixa_de_fora_o_que_e_pessoal(repo):
    pessoais = ["site_config.json", "ia_config.json", "ia_uso.json", "youtube_cookies.json", "cookies_youtube.txt",
                "flow_dados/perfis/sessao.json", "toolkit/googleflow/sessao--conta.json", "jobs/abc/state.json",
                "outputs/v.mp4", "dossies/p/projeto.json", "analises_canal/x/analise.json", "niche_miner/data/biblioteca.db",
                "toolkit/tts/models/perfis_de_voz/eu.wav", "conversas/c.json", "vendas/v.json", ".env", "video.mp4"]
    codigo = ["app.py", "niche_miner/app.py", "toolkit/googleflow/flow_falso_teste/index.html", "yt_cookies.py", ".env.example"]
    for a in pessoais + codigo:
        _escreve(a)
    _add()
    rastreados = set(subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split())
    assert not rastreados & set(pessoais), rastreados & set(pessoais)
    assert set(codigo) <= rastreados


def test_acha_arquivo_pessoal_chave_e_email(repo, capsys):
    _escreve("app.py", "print('ok')\n")
    _escreve("config_local.py", "CHAVE = 'sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'\nDONO = 'dono@exemplo.com'\n")
    _escreve("jobs/x/state.json", "{}")
    _escreve("testes_fake.py", "CHAVE = 'AIzaFakeChaveDeTeste1234567890abcdefg'\n")  # chave falsa de teste: não acusa
    _add("jobs/x/state.json")
    assert v.main([]) == 1
    out = capsys.readouterr().out
    assert "jobs/x/state.json" in out and "chave da Anthropic: sk-ant-a…" in out and "o seu e-mail" in out
    assert "ABCDEFGHIJ" not in out and "testes_fake.py" not in out  # nunca mostra a chave inteira
    v.main(["--corrigir"])
    capsys.readouterr()
    rastreados = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout
    assert "jobs/x/state.json" not in rastreados and os.path.exists("jobs/x/state.json")  # continua no PC


def test_tudo_limpo_passa(repo, capsys):
    _escreve("app.py", "print('ok')\n")
    _add()
    assert v.main([]) == 0
    assert "✅" in capsys.readouterr().out


def test_instala_o_gancho_do_commit(repo):
    v.instalar_gancho()
    with open(".git/hooks/pre-commit", encoding="utf-8") as f:
        assert "verificar_antes_de_subir.py" in f.read()


def test_o_proprio_projeto_esta_limpo():
    """Nenhum arquivo do código que vai pro GitHub tem chave de verdade ou cookie."""
    arquivos = []
    for raiz, pastas, nomes in os.walk(AQUI):
        rel = os.path.relpath(raiz, AQUI).replace("\\", "/")
        if any(rel == p.rstrip("/") or rel.startswith(p) for p in v.PASTAS_PESSOAIS) or "__pycache__" in rel or rel.startswith(".git"):
            pastas[:] = []
            continue
        arquivos += [os.path.join(raiz, n) for n in nomes]
    _p, conteudo, grandes = v.conferir(arquivos)
    assert not conteudo and not grandes, (conteudo, grandes)
