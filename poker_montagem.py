"""
poker_montagem.py — 🎞 monta o vídeo final do roteiro, sozinho (v84_277)
=======================================================================

Roteiro (poker_doc) → vídeo pronto pra subir:
  1. 🎙 cada fala vira áudio no gerador de voz do site (a mesma voz do 🎙 Gerar voz), guardado em cache;
  2. 🎬 cada bloco de narração ganha a sua peça (poker_graficos: título, cartão do jogador, linha do tempo, gráfico,
     citação, número, a sua foto com Ken Burns — ou o seu vídeo) com a duração exata da fala;
  3. 🃏 cada mão: a mesa aparece enquanto o narrador conta o "antes", a mão anda enquanto ele narra "durante"
     (a velocidade se ajusta pra fala caber), 🧠 a estratégia aparece num cartão e o "depois" fica sobre a mesa final;
  4. 🔊 os sons da mesa entram embaixo da voz; 🎵 trilha opcional (poker/sons/musica.mp3 ou a do roteiro) abaixa
     sozinha quando o narrador fala;
  5. tudo emendado num MP4 + a legenda .srt (cada fala com o tempo certo).
Cada pedaço fica em cache: mudou um bloco, só ele é refeito.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

import poker_doc as PD
import poker_graficos as PG
import poker_mesa as PM
import poker_render as PR

PAUSA = 0.35   # respiro entre as falas
EXT_VIDEO = (".mp4", ".mov", ".webm", ".mkv")


class MontagemErro(PM.PokerErro):
    pass


def _rodar(cmd: List[str], timeout: int = 900) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise MontagemErro("ffmpeg: " + (r.stderr or "")[-400:])
    return r


def duracao(arq: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arq], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _h(*partes: Any) -> str:
    return hashlib.sha1(json.dumps(partes, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:14]


def pasta(base: str, did: str) -> str:
    p = os.path.join(PD._pasta(base), f"{did}_montagem")
    os.makedirs(p, exist_ok=True)
    return p


def pasta_midia(base: str, did: str) -> str:
    p = os.path.join(PD._pasta(base), f"{did}_midia")
    os.makedirs(p, exist_ok=True)
    return p


def frases_legenda(texto: str, ini: float, dur: float) -> List[Tuple[float, float, str]]:
    """A fala em pedaços de legenda (por frase, ~ proporcional ao tamanho)."""
    partes = [x.strip() for x in re.split(r"(?<=[.!?…])\s+", texto or "") if x.strip()]
    if not partes:
        return []
    tot = sum(len(x) for x in partes) or 1
    out, t = [], ini
    for x in partes:
        d = dur * len(x) / tot
        out.append((t, t + d, x))
        t += d
    return out


def _srt(itens: List[Tuple[float, float, str]]) -> str:
    def ts(v: float) -> str:
        ms = int(round(v * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{k}\n{ts(a)} --> {ts(b)}\n{t}\n" for k, (a, b, t) in enumerate(itens, 1))


class Montador:
    def __init__(self, base: str, did: str, op: Dict[str, Any], tts: Callable[..., Any], voz: Dict[str, Any],
                 limpar: Callable[[str, str], str] = lambda t, m: t, on_log: Callable[[str], None] = lambda _m: None,
                 parar: Callable[[], bool] = lambda: False, pasta_avatares: str = "", pasta_personagens: str = "",
                 musica: str = "", gravar_pagina: Optional[Callable[..., Any]] = None,
                 kwargs_voz: Optional[Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any]]]] = None):
        self.base, self.did = base, did
        self.ritmo = str((op or {}).get("ritmo_pecas") or "normal")   # ⏱ tempo mínimo das peças: rapido · normal · calmo
        self.op = PR.normalizar(op)
        self.W, self.H = PR.TAMANHOS[self.op["formato"]]
        self.fps = int(self.op["fps"])
        self.tts, self.voz, self.limpar = tts, voz, limpar
        self.log, self.parar = on_log, parar
        self.pa, self.pp, self.musica = pasta_avatares, pasta_personagens, musica
        self.dir = pasta(base, did)
        self.gp = gravar_pagina or PR.gravar_pagina
        self.fontes = "file://" + os.path.join(PR.AQUI, "assets", "fonts", "dp").replace("\\", "/")
        self.legendas: List[Tuple[float, float, str]] = []
        self.kv = kwargs_voz

    # ---------------------------------------------------------------- voz
    def fala(self, texto: str) -> Tuple[str, float]:
        texto = " ".join(str(texto or "").split())
        if not texto:
            return "", 0.0
        if self.kv:
            motor, kw = self.kv(self.voz)
        else:
            import multivoz
            motor, kw = multivoz.kwargs_da_voz(self.voz)
        arq = os.path.join(self.dir, "voz_" + _h(texto, self.voz) + ".wav")
        if not os.path.isfile(arq):
            bruto = arq + ".bruto.wav"
            for tentativa in range(3):
                try:
                    self.tts(motor, self.limpar(texto, motor), bruto, **kw)
                    if os.path.isfile(bruto) and os.path.getsize(bruto) > 1000:
                        break
                except Exception:  # noqa: BLE001
                    if tentativa == 2:
                        raise
            if not os.path.isfile(bruto):
                raise MontagemErro("o gerador de voz não gerou o áudio")
            _rodar(["ffmpeg", "-v", "error", "-y", "-i", bruto, "-af",
                    "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.3:stop_threshold=-45dB",
                    "-ar", "48000", "-ac", "2", arq])
            os.remove(bruto)
        return arq, duracao(arq)

    # ---------------------------------------------------------------- pedaços de vídeo
    def _com_audio(self, video: str, falas: List[Tuple[str, float]], dur: float, saida: str, sfx: Optional[str] = None,
                   sfx_atraso: float = 0.0) -> str:
        """Junta o vídeo (sem som) com as falas nos instantes certos (+ os sons da mesa, mais baixos)."""
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fc, mix, k = [], ["[1:a]"], 2
        for arq, t0 in falas:
            if not arq:
                continue
            cmd += ["-i", arq]
            ms = int(t0 * 1000)
            fc.append(f"[{k}:a]adelay={ms}|{ms},volume=1.0[f{k}]")
            mix.append(f"[f{k}]")
            k += 1
        if sfx and os.path.isfile(sfx):
            cmd += ["-i", sfx]
            ms = int(max(0.0, sfx_atraso) * 1000)
            fc.append(f"[{k}:a]adelay={ms}|{ms},volume=0.45[s{k}]")
            mix.append(f"[s{k}]")
            k += 1
        fc.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0[a]")
        cmd += ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", saida]
        try:
            _rodar(cmd)
        except MontagemErro:
            _rodar([x.replace(":normalize=0", "") for x in cmd])
        return saida

    def _imagem_parada(self, png: str, dur: float, saida: str) -> str:
        _rodar(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", png, "-t", f"{dur:.3f}", "-r", str(self.fps),
                "-vf", f"scale={self.W}:{self.H},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", saida])
        return saida

    def _video_do_usuario(self, arq: str, dur: float, saida: str) -> str:
        _rodar(["ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", arq, "-t", f"{dur:.3f}", "-an", "-r", str(self.fps),
                "-vf", f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", saida])
        return saida

    def nomes_conhecidos(self) -> List[str]:
        """Os jogadores que aparecem no roteiro (das mãos e dos cartões) — pra achar a foto de quem o narrador cita."""
        if getattr(self, "_nomes", None) is None:
            nomes: List[str] = []
            for b in PD.carregar(self.base, self.did).get("blocos") or []:
                if b["tipo"] == "mao":
                    try:
                        nomes += [j.get("nome") or "" for j in PM.ler(b["mao"]["mao"]).get("jogadores") or []]
                    except PM.PokerErro:
                        pass
                elif (b.get("grafico") or {}).get("tipo") == "jogador":
                    nomes.append(b["grafico"].get("titulo") or "")
            self._nomes = [n for n in dict.fromkeys(nomes) if n.strip()]
        return self._nomes

    def foto_citada(self, texto: str) -> str:
        """📷 a foto de um jogador citado no texto (pelo nome ou sobrenome), se você enviou a foto dele."""
        import poker_rotas as R
        sl = "_" + R.slug(texto) + "_"
        for nome in self.nomes_conhecidos():
            partes = [R.slug(nome)] + [R.slug(p) for p in nome.split() if len(p) >= 4]
            if any(p and f"_{p}_" in sl for p in partes):
                a = R.avatar_de(self.base, nome)
                if a and os.path.isfile(os.path.join(self.pa, a)):
                    return os.path.join(self.pa, a)
        if self.pa and os.path.isdir(self.pa):   # foto enviada com o nome de alguém que não está nas mãos
            for f in sorted(os.listdir(self.pa)):
                stem = os.path.splitext(f)[0]
                if len(stem) >= 4 and f"_{stem}_" in sl:
                    return os.path.join(self.pa, f)
        return ""

    def peca(self, g: Dict[str, Any], dur: float, frase: str, saida: str, foto_jogador: str = "") -> str:
        import poker_rotas as R
        g = PG.normalizar(g)
        midia = os.path.join(pasta_midia(self.base, self.did), g["arquivo"]) if g.get("arquivo") else ""
        if foto_jogador and not (midia and os.path.isfile(midia)):   # sem dados/peça: a foto de quem está sendo citado
            g, midia = dict(g, tipo="midia", texto=g.get("texto") or frase), foto_jogador
        if midia and os.path.isfile(midia) and midia.lower().endswith(EXT_VIDEO):
            return self._video_do_usuario(midia, dur, saida)
        foto = ""
        if g["tipo"] == "jogador" and g["titulo"]:
            a = R.avatar_de(self.base, g["titulo"])
            foto = os.path.join(self.pa, a) if a else ""
        if g["tipo"] == "midia" and not (midia and os.path.isfile(midia)):
            g = dict(g, tipo="")   # ainda sem a foto: entra a frase
        url = lambda c: ("file://" + c.replace("\\", "/")) if c and os.path.isfile(c) else ""  # noqa: E731
        html = PG.pagina(g, self.op, dur, self.fontes, url(foto), url(midia), frase)
        tmp = os.path.join(os.path.dirname(saida), "_tmp_" + _h(saida))
        os.makedirs(tmp, exist_ok=True)
        try:
            self.gp(html, self.W, self.H, self.fps, dur, saida, self.log, self.parar, tmp, "🎬 peça", 20)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return saida

    # ---------------------------------------------------------------- blocos
    def bloco_narracao(self, b: Dict[str, Any], k: int, t0: float) -> Tuple[str, float]:
        arq, d = self.fala(b["texto"])
        frase = re.split(r"(?<=[.!?])\s", b["texto"] or "")[0][:200]
        dur = max(d + PAUSA * 2, PG.tempo_minimo(b.get("grafico") or {}, frase, self.ritmo))   # a peça fica o tempo de ler
        g0 = PG.normalizar(b.get("grafico") or {})
        foto_c = self.foto_citada(b["texto"]) if g0["tipo"] in ("", "midia") and not g0.get("arquivo") else ""
        chave = _h("narr", b.get("texto"), b.get("grafico"), self.op, self.voz, d, dur, foto_c)
        saida = os.path.join(self.dir, f"b{k:03d}_{chave}.mp4")
        ini = PAUSA + min(0.6, max(0.0, dur - d - PAUSA * 2) / 2)   # sobrou tempo: a peça entra e o narrador começa logo depois
        if not os.path.isfile(saida):
            v = self.peca(b.get("grafico") or {}, dur, frase, saida + ".v.mp4", foto_c)
            self._com_audio(v, [(arq, ini)], dur, saida)
            os.remove(v)
        self.legendas += frases_legenda(b["texto"], t0 + ini, d)
        return saida, dur

    def bloco_mao(self, b: Dict[str, Any], k: int, t0: float) -> List[Tuple[str, float]]:
        m = b["mao"]
        fa, da = self.fala(m.get("contexto_antes"))
        fb, db = self.fala(b.get("texto"))
        fc, dc = self.fala(m.get("estrategia"))
        fd, dd = self.fala(m.get("contexto_depois"))
        nat = PM.simular(m["mao"], 1.0, "shorts" if self.op["estilo"] == "shorts" else "", self.op["pov"], self.op.get("estrategia", False))
        intro = nat["eventos"][0]["dur"]
        jogo_nat = nat["duracao"] - intro
        alvo = max(db + 1.2, jogo_nat * 0.65)       # a mão anda no ritmo da fala do "durante"
        vel = max(0.5, min(1.6, jogo_nat / max(1.0, alvo)))
        dados = PM.simular(m["mao"], vel, "shorts" if self.op["estilo"] == "shorts" else "", self.op["pov"], self.op.get("estrategia", False))
        import poker_rotas as R
        for j in dados["jogadores"]:
            j["avatar"] = R.avatar_de(self.base, j["nome"], j.get("avatar") or "")
        intro = dados["eventos"][0]["dur"]
        jogo = dados["duracao"] - intro
        pre = max(intro, (da + PAUSA * 2) if fa else intro)   # a mesa parada enquanto ele conta o "antes"
        dur_v = pre + jogo + 0.6 + max(0.0, db - jogo)
        chave = _h("mao", m, b.get("texto"), self.op, self.voz, da, db)
        saida = os.path.join(self.dir, f"b{k:03d}_{chave}.mp4")
        png = saida + ".final.png"
        pedacos: List[Tuple[str, float]] = []
        if not (os.path.isfile(saida) and os.path.isfile(png)):
            tmp = os.path.join(self.dir, "_tmp_" + chave)
            os.makedirs(tmp, exist_ok=True)
            av_url = (lambda a: ("file://" + os.path.join(self.pa, os.path.basename(a)).replace("\\", "/")) if a else "")
            if self.op.get("modo") == "3d":
                import poker_3d as P3
                pers = (lambda n: ("file://" + os.path.join(self.pp, R.personagem_arquivo(self.pp, n)).replace("\\", "/"))
                        if self.pp and R.personagem_arquivo(self.pp, n) else "")
                html = P3.pagina(dados, self.op, self.fontes, pers, "gravar")
            else:
                html = PR.pagina(dados, self.op, self.fontes, av_url, "gravar")
            fim = dados["duracao"]
            tempo = lambda vt: min(intro - 0.02, vt) if vt < pre else min(fim, intro + (vt - pre))  # noqa: E731  (a mesa espera antes de dar as cartas)
            v = os.path.join(tmp, "v.mp4")
            self.gp(html, self.W, self.H, self.fps, dur_v, v, self.log, self.parar, tmp, f"🃏 {m.get('titulo', 'mão')[:30]}",
                    23 if self.op.get("modo") == "3d" else 18, tempo, png)
            sfx = PR.trilha_sons(dados, os.path.join(tmp, "sfx.wav"), tmp, self.op.get("estilo") == "shorts") if self.op.get("sons") else None
            self._com_audio(v, [(fa, PAUSA), (fb, pre + 0.3)], dur_v, saida, sfx, pre - intro)
            shutil.rmtree(tmp, ignore_errors=True)
        pedacos.append((saida, dur_v))
        if fa:
            self.legendas += frases_legenda(m.get("contexto_antes"), t0 + PAUSA, da)
        if fb:
            self.legendas += frases_legenda(b.get("texto"), t0 + pre + 0.3, db)
        t = t0 + dur_v
        if fc:   # 🧠 o que aprender: um cartão com a estratégia
            dur = max(dc + PAUSA * 2, PG.tempo_minimo({"tipo": "citacao", "texto": m["estrategia"]}, "", self.ritmo))
            s2 = os.path.join(self.dir, f"b{k:03d}c_{_h('estr', m.get('estrategia'), self.op, self.voz, dur)}.mp4")
            if not os.path.isfile(s2):
                v = self.peca({"tipo": "citacao", "texto": m["estrategia"], "autor": "🧠 o que aprender"}, dur, "", s2 + ".v.mp4")
                self._com_audio(v, [(fc, PAUSA)], dur, s2)
                os.remove(v)
            pedacos.append((s2, dur))
            self.legendas += frases_legenda(m.get("estrategia"), t + PAUSA, dc)
            t += dur
        if fd:   # o "depois" em cima da mesa final
            dur = dd + PAUSA * 2
            s3 = os.path.join(self.dir, f"b{k:03d}d_{_h('dep', m.get('contexto_depois'), chave, self.voz)}.mp4")
            if not os.path.isfile(s3):
                v = self._imagem_parada(png, dur, s3 + ".v.mp4")
                self._com_audio(v, [(fd, PAUSA)], dur, s3)
                os.remove(v)
            pedacos.append((s3, dur))
            self.legendas += frases_legenda(m.get("contexto_depois"), t + PAUSA, dd)
        return pedacos

    # ---------------------------------------------------------------- tudo
    def montar(self, saida: str) -> Dict[str, Any]:
        d = PD.carregar(self.base, self.did)
        blocos = d.get("blocos") or []
        if not blocos:
            raise MontagemErro("O roteiro está vazio — ✍ escreva ou adicione blocos antes de montar.")
        ruins = [b["mao"]["titulo"] for b in blocos if b["tipo"] == "mao" and not (b.get("validacao") or {}).get("ok")]
        if ruins:
            raise MontagemErro("Conserte as mãos que não rodam no motor: " + ", ".join(ruins))
        pedacos: List[Tuple[str, float]] = []
        t = 0.0
        for k, b in enumerate(blocos):
            if self.parar():
                raise MontagemErro("⏹ parado por você")
            self.log(f"🎞 bloco {k + 1}/{len(blocos)} — {'🃏 ' + b['mao']['titulo'] if b['tipo'] == 'mao' else '🎙 narração'}")
            if b["tipo"] == "mao":
                ps = self.bloco_mao(b, k, t)
            else:
                ps = [self.bloco_narracao(b, k, t)] if (b.get("texto") or "").strip() else []
            for arq, dur in ps:
                pedacos.append((arq, dur))
                t += dur
        self.log("📦 emendando tudo…")
        lista = os.path.join(self.dir, "lista.txt")
        with open(lista, "w", encoding="utf-8") as f:
            f.writelines(f"file '{os.path.abspath(a).replace(chr(92), '/')}'\n" for a, _d in pedacos)
        junto = os.path.join(self.dir, "_junto.mp4")
        try:
            _rodar(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", junto])
        except MontagemErro:
            _rodar(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-c:a", "aac", "-b:a", "192k", junto])
        musica = self.musica if self.musica and os.path.isfile(self.musica) else ""
        if musica:   # 🎵 trilha embaixo, abaixando sozinha quando o narrador fala (sidechain)
            self.log("🎵 colocando a trilha…")
            _rodar(["ffmpeg", "-v", "error", "-y", "-i", junto, "-stream_loop", "-1", "-i", musica, "-filter_complex",
                    "[1:a]volume=0.22,aresample=48000[m];[0:a]asplit=2[v][sc];[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[md];"
                    "[v][md]amix=inputs=2:duration=first:normalize=0[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-movflags", "+faststart", saida])
        else:
            _rodar(["ffmpeg", "-v", "error", "-y", "-i", junto, "-c", "copy", "-movflags", "+faststart", saida])
        os.remove(junto)
        srt = saida[:-4] + ".srt"
        with open(srt, "w", encoding="utf-8") as f:
            f.write(_srt(self.legendas))
        return {"video": os.path.basename(saida), "srt": os.path.basename(srt), "duracao": round(t, 2), "pedacos": len(pedacos)}
