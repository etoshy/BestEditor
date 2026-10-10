import os, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["VOICE_GENERATOR_DESATIVAR_ISOLAMENTO"] = "1"
import app as flaskapp
import tts.voice_generator as vg_mod

class FakeModeloTurbo:
    sr = 24000
    chamadas = []
    def generate(self, texto, **kwargs):
        FakeModeloTurbo.chamadas.append({"texto": texto, **kwargs})
        return "wav_falso"

def fake_salvar(wav, output_path, sample_rate):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=duration=1", output_path], capture_output=True, check=True)

if __name__ == "__main__":
    vg_mod.chatterbox_turbo_load = lambda **kw: FakeModeloTurbo()
    vg_mod._salvar_audio_chatterbox = fake_salvar
    client = flaskapp.app.test_client()
    r = client.post("/gerar-voz/gerar", data={
        "texto": "Hi there [chuckle], how can I help you today?", "engine": "chatterbox_turbo",
    })
    job_id = r.get_json()["job_id"]
    deadline = time.time() + 15
    while time.time() < deadline:
        st = client.get(f"/gerar-voz/status/{job_id}").get_json()
        if st.get("pronto"):
            break
        time.sleep(0.2)
    assert st["erro"] is None, st["erro"]
    assert st["resultado"]["audio_url"]
    assert st["resultado"]["engine"] == "chatterbox_turbo"
    assert "[chuckle]" in FakeModeloTurbo.chamadas[0]["texto"]
    print("OK: rota completa /gerar-voz/gerar com engine=chatterbox_turbo funciona, tags preservadas")
