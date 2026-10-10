"""
Teste offline da lógica de otimização de recursos do run_batch.py e do
browser_session.py — sem precisar de um Chrome de verdade instalado
(usa um driver/sessão falsos pra verificar o comportamento).
"""
import json
import os
import shutil

import browser_session
import run_batch


def test_low_resource_flags():
    captured = {}

    class FakeDriver:
        def __init__(self, options=None):
            captured["arguments"] = list(options.arguments)
            captured["prefs"] = options.experimental_options.get("prefs", {})

        def execute_cdp_cmd(self, *a, **k):
            pass

    original_chrome = browser_session.webdriver.Chrome
    browser_session.webdriver.Chrome = FakeDriver
    try:
        browser_session.ChromeSession(headless=True, download_dir="/tmp/lr_off")
        assert "--blink-settings=imagesEnabled=false" not in captured["arguments"]
        assert "profile.managed_default_content_settings.images" not in captured["prefs"]
        print("OK: low_resource=False (padrão) não muda nada do comportamento anterior.")

        browser_session.ChromeSession(headless=True, download_dir="/tmp/lr_on", low_resource=True)
        for flag in (
            "--disable-extensions", "--disable-background-networking", "--disable-sync",
            "--disable-translate", "--mute-audio", "--disable-software-rasterizer",
            "--blink-settings=imagesEnabled=false",
        ):
            assert flag in captured["arguments"], f"faltou a flag {flag}"
        assert captured["prefs"].get("profile.managed_default_content_settings.images") == 2
        print("OK: low_resource=True aplica todas as flags de economia de recurso.")
    finally:
        browser_session.webdriver.Chrome = original_chrome


def test_shared_session_creates_only_one_browser():
    sessions_created = []

    class FakeSession:
        def __init__(self, **kwargs):
            sessions_created.append(kwargs)
        def close(self):
            pass

    class FakeVideo:
        def __init__(self, id):
            self.id = id
        def to_dict(self):
            return {"id": self.id, "title": f"T{self.id}", "description": "d"}

    class FakeClient:
        def __init__(self, session=None, delay=0.0):
            self.session = session
        def search_all(self, max_pages=1, **kwargs):
            return [FakeVideo("v0")]
        def download_video(self, video, output_dir):
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, "v0.mp4")
            open(path, "w").close()
            return path

    original_session_cls = run_batch.ChromeSession
    original_clients = dict(run_batch._CLIENT_CLASSES)
    run_batch.ChromeSession = FakeSession
    for name in run_batch._CLIENT_CLASSES:
        run_batch._CLIENT_CLASSES[name] = FakeClient

    config_path = "/tmp/test_optim_config.json"
    manifest_path = "/tmp/test_optim_manifest.json"
    out_root = "/tmp/test_optim_videos"
    for p in (config_path, manifest_path):
        if os.path.exists(p):
            os.remove(p)
    if os.path.exists(out_root):
        shutil.rmtree(out_root)

    try:
        # --- com shared_session: true -> só 1 sessão para 3 provedores ---
        cfg_shared = {
            "browser": {"headless": True, "shared_session": True, "low_resource": True, "download_dir": "/tmp/x"},
            "downloads": {
                "enabled": True, "max_workers": 3, "per_provider_workers": 1, "skip_existing": True,
                "retries": 1, "retry_backoff_seconds": 0, "manifest": manifest_path,
                "output_dir": out_root, "write_metadata": False, "embed_ffmpeg_metadata": False,
            },
            "providers": {
                "pexels": {"enabled": True, "query": "dog", "max_pages": 1, "download_count": 1},
                "pixabay": {"enabled": True, "query": "dog", "max_pages": 1, "download_count": 1},
                "magnific": {"enabled": True, "query": "dog", "only_free": True, "max_pages": 1, "download_count": 1},
                "mixkit": {"enabled": False},
                "vistacreate": {"enabled": False},
            },
        }
        with open(config_path, "w") as f:
            json.dump(cfg_shared, f)

        summary = run_batch.run_batch(config_path=config_path)
        assert len(sessions_created) == 1, f"esperava 1 sessão compartilhada, criou {len(sessions_created)}"
        assert summary["downloads"]["ok"] == 3
        print("OK: shared_session=True cria apenas 1 navegador para múltiplos provedores.")

        # --- sem shared_session (padrão) -> 1 sessão por provedor ---
        sessions_created.clear()
        if os.path.exists(manifest_path):
            os.remove(manifest_path)
        if os.path.exists(out_root):
            shutil.rmtree(out_root)

        cfg_default = json.loads(json.dumps(cfg_shared))
        cfg_default["browser"]["shared_session"] = False
        with open(config_path, "w") as f:
            json.dump(cfg_default, f)

        run_batch.run_batch(config_path=config_path)
        assert len(sessions_created) == 3, f"esperava 3 sessões (uma por provedor), criou {len(sessions_created)}"
        print("OK: sem shared_session, comportamento anterior preservado (1 navegador por provedor).")

    finally:
        run_batch.ChromeSession = original_session_cls
        run_batch._CLIENT_CLASSES.clear()
        run_batch._CLIENT_CLASSES.update(original_clients)
        for p in (config_path, manifest_path):
            if os.path.exists(p):
                os.remove(p)
        if os.path.exists(out_root):
            shutil.rmtree(out_root)


if __name__ == "__main__":
    test_low_resource_flags()
    test_shared_session_creates_only_one_browser()
    print("\nTodos os testes de otimização de recursos passaram.")
