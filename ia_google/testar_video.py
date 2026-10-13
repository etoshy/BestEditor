"""
Testa a análise de vídeos do YouTube e mede se os TEMPOS que a IA dá estão certos,
comparando com transcrições reais (pasta transcricoes/, formato "m:ss texto" por linha).

    python testar_video.py                      # os 2 vídeos de teste
    python testar_video.py --url LINK [--url LINK2]
    python testar_video.py --rapido             # só resumo + momentos + perguntas

Se algo falhar, cria falhas_video_AAAAMMDD-HHMM/ (HTML, print, JSON e RELATORIO.txt) e o .zip para enviar.
Se tudo der certo, só mostra o placar.
IMPORTANTE: feche o app.py antes (os dois usam o mesmo perfil do navegador).
"""
import argparse
import json
import re
import sys
import time
import traceback
import zipfile
from pathlib import Path

from ia_google import GoogleIA, classificar_erro
from youtube import AnalisadorYouTube, formatar_tempo, para_segundos, id_do_video

BASE = Path(__file__).resolve().parent
PASTA_TRANSCRICOES = BASE / "transcricoes"

VIDEOS_PADRAO = ["https://www.youtube.com/watch?v=ZENXID79hHw", "https://www.youtube.com/watch?v=EFmnPEtx04g"]

# Casos com resposta conhecida, por transcrição (nome do arquivo sem .txt).
# momentos: (o que procurar, início esperado (s), fim esperado (s))
# perguntas: (pergunta, palavras que devem aparecer na resposta — basta uma)
CASOS = {
    "kungfu_panda_oogway": {
        "momentos": [
            ("a frase 'ontem é história, o amanhã é um mistério, mas o hoje é uma dádiva'", 382, 394),
            ("Tai Lung dizendo que apodreceu na prisão por 20 anos", 283, 296),
            ("a explicação da pedra no caminho da água", 414, 424),
            ("a parte sobre o javali que usava máquinas", 226, 271),
            ("a coruja que foi presa numa gaiola", 162, 208),
        ],
        "perguntas": [
            ("Por quantos anos Tai Lung ficou preso?", ["20", "vinte"]),
            ("Como se chama o melhor amigo de Oogway que ele precisou enfrentar?", ["kai"]),
            ("O que significa o conceito taoísta citado no vídeo?", ["não ação", "não-ação", "nao acao", "não agir", "wu wei"]),
        ],
    },
    "manipulacao_com_dados": {
        "momentos": [
            ("a história dos aviões da Segunda Guerra e do viés de sobrevivência", 288, 395),
            ("o caso da universidade de Berkeley e o paradoxo de Simpson", 621, 691),
            ("o caso de Sally Clark", 1179, 1274),
            ("o experimento da roleta sobre ancoragem", 131, 162),
            ("o alerta sobre pílulas anticoncepcionais e trombose", 476, 552),
        ],
        "perguntas": [
            ("Com as pílulas antigas e com as novas, quantas mulheres tinham trombose?", ["7 mil", "sete mil", "7.000", "7000"]),
            ("Qual estatístico analisou os dados de admissão de Berkeley?", ["bickel", "bikel"]),
            ("Quem percebeu que a blindagem dos aviões devia ir onde não havia buracos?", ["wald"]),
        ],
    },
}
TOLERANCIA = 25  # segundos de folga para considerar um momento certo


# ---------------------------------------------------------------- transcrições
def ler_transcricao(caminho):
    linhas = []
    for l in Path(caminho).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*((?:\d+:)?\d{1,2}:\d{2})\s+(.*)", l)
        if m:
            linhas.append((para_segundos(m.group(1)), m.group(2)))
    return linhas


PARADAS = set("para com que uma isso esse essa como mais pelo pela ainda quando onde aquele aquela você ele ela eles "
               "elas tudo todo toda muito também então depois antes sobre entre porque está estava foram seria".split())


def palavras(t):
    return {w for w in re.findall(r"[a-záéíóúâêôãõçà]{4,}", (t or "").lower()) if w not in PARADAS}


def texto_janela(tr, ini, fim, folga=TOLERANCIA):
    return " ".join(t for s, t in tr if ini - folga <= s <= fim + folga)


def melhor_lugar(tr, texto, largura=12):
    """Onde na transcrição o texto mais aparece: (segundo, fração de palavras encontradas).
    Empate: fica com a linha que, sozinha, tem mais palavras da frase."""
    alvo = palavras(texto)
    if not alvo:
        return None, 0
    melhor, nota_melhor = (None, 0), -1
    for s, linha in tr:
        achadas = len(alvo & palavras(texto_janela(tr, s, s + largura, 0))) / len(alvo)
        nota = achadas + 0.01 * len(alvo & palavras(linha))
        if nota > nota_melhor:
            melhor, nota_melhor = (s, achadas), nota
    return melhor


def escolher_transcricao(resumo_txt, transcricoes):
    """Qual transcrição combina com o resumo da IA."""
    alvo = palavras(resumo_txt)
    notas = {n: len(alvo & palavras(" ".join(t for _, t in tr))) for n, tr in transcricoes.items()}
    if not notas:
        return None
    nome = max(notas, key=notas.get)
    return nome if notas[nome] >= 5 else None


# ---------------------------------------------------------------- verificações
def checar_basico(r, tarefa, duracao_tr):
    p = []
    if not r.get("formato_respeitado"):
        p.append("SEM_JSON: a IA não respondeu no formato JSON esperado")
    if r.get("aviso") and "não conseguiu acessar" in r["aviso"]:
        p.append("SEM_ACESSO: a IA disse que não conseguiu acessar o vídeo")
    for prob in r.get("problemas_tempo", []):
        p.append("TEMPO_INVALIDO: " + prob)
    if duracao_tr:
        def varrer(o):
            if isinstance(o, dict):
                for k in ("inicio_seg", "fim_seg", "tempo_seg"):
                    if o.get(k) is not None and o[k] > duracao_tr + 15:
                        p.append(f"TEMPO_FORA_DO_VIDEO: {formatar_tempo(o[k])} (o vídeo tem ~{formatar_tempo(duracao_tr)})")
                for v in o.values():
                    varrer(v)
            elif isinstance(o, list):
                for v in o:
                    varrer(v)
        varrer(r.get("dados"))
    d = r.get("dados") or {}
    obrig = {"resumo": "topicos", "capitulos": "capitulos", "cortes": "cortes", "citacoes": "citacoes",
             "fatos": "afirmacoes", "quiz": "perguntas", "momentos": "momentos"}
    if r.get("formato_respeitado") and tarefa in obrig and not d.get(obrig[tarefa]):
        p.append(f"LISTA_VAZIA: '{obrig[tarefa]}' veio vazio")
    if tarefa == "capitulos" and d.get("capitulos"):
        inis = [c.get("inicio_seg") for c in d["capitulos"] if c.get("inicio_seg") is not None]
        if inis and inis[0] > 30:
            p.append(f"CAPITULOS: o primeiro capítulo começa em {formatar_tempo(inis[0])} (deveria ser 0:00)")
        if inis != sorted(inis):
            p.append("CAPITULOS: tempos fora de ordem")
    return p


def checar_citacoes(r, tr):
    """Para cada item com frase + tempo, confere se a frase está perto do tempo dado (na transcrição)."""
    p, ok, total = [], 0, 0
    def itens(o):
        if isinstance(o, dict):
            if any(k in o for k in ("inicio_seg", "tempo_seg")):
                yield o
            for v in o.values():
                yield from itens(v)
        elif isinstance(o, list):
            for v in o:
                yield from itens(v)
    for it in itens(r.get("dados") or {}):
        frase = it.get("citacao") or it.get("texto") or it.get("gancho")
        if not frase or len(palavras(frase)) < 3:
            continue
        ini = it.get("inicio_seg", it.get("tempo_seg"))
        fim = it.get("fim_seg") or ini
        total += 1
        aqui = len(palavras(frase) & palavras(texto_janela(tr, ini, fim))) / len(palavras(frase))
        if aqui >= 0.4:
            ok += 1
            continue
        onde, quanto = melhor_lugar(tr, frase)
        if quanto >= 0.6 and onde is not None and abs(onde - ini) > TOLERANCIA:
            p.append(f"TEMPO_ERRADO: “{frase[:70]}” — IA disse {formatar_tempo(ini)}, na transcrição está em ~{formatar_tempo(onde)}")
        else:
            ok += 1  # frase parafraseada / não verificável: não conta como erro
    return p, ok, total


def checar_momentos(r, esperado_ini, esperado_fim):
    ms = (r.get("dados") or {}).get("momentos") or []
    if not ms:
        return [f"MOMENTO_NAO_ENCONTRADO: esperado {formatar_tempo(esperado_ini)}–{formatar_tempo(esperado_fim)}"], False
    for m in ms:
        a = m.get("inicio_seg")
        b = m.get("fim_seg") if m.get("fim_seg") is not None else a
        if a is None:
            continue
        if a <= esperado_fim + TOLERANCIA and b >= esperado_ini - TOLERANCIA:
            return [], True
    dados = ", ".join(f"{formatar_tempo(m.get('inicio_seg'))}–{formatar_tempo(m.get('fim_seg'))}" for m in ms)
    return [f"MOMENTO_ERRADO: IA disse {dados}; o certo é {formatar_tempo(esperado_ini)}–{formatar_tempo(esperado_fim)}"], False


def checar_pergunta(r, chaves):
    texto = " ".join([r.get("resposta_objetiva") or "", r.get("markdown") or ""]).lower()
    if any(c.lower() in texto for c in chaves):
        return [], True
    return [f"RESPOSTA_ERRADA: esperava encontrar {' ou '.join(chaves)} na resposta"], False


# ---------------------------------------------------------------- execução
def slug(t):
    t = re.sub(r"[^a-z0-9]+", "-", t.lower().encode("ascii", "ignore").decode())
    return t.strip("-")[:35] or "x"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", help="link de vídeo (pode repetir)")
    ap.add_argument("--rapido", action="store_true", help="só resumo, momentos e perguntas")
    ap.add_argument("--pausa", type=float, default=5)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--invisivel", action="store_true")
    a = ap.parse_args()

    urls = a.url or VIDEOS_PADRAO
    transcricoes = {p.stem: ler_transcricao(p) for p in sorted(PASTA_TRANSCRICOES.glob("*.txt"))}
    pasta = BASE / f"falhas_video_{time.strftime('%Y%m%d-%H%M')}"
    falhas, placar, n = [], {}, 0
    inicio = time.time()

    ia = GoogleIA(headless=a.invisivel, timeout_resposta=a.timeout, interativo=False, espera_captcha=0,
                  log=lambda msg, nivel="info": print(f"      · {msg}") if nivel in ("aviso", "erro") or "aptcha" in msg else None)
    try:
        ia.abrir()
    except Exception as e:
        err = classificar_erro(e)
        print(f"❌ [{err.codigo}] {err.mensagem}\n   {err.dica}")
        sys.exit(1)
    yt = AnalisadorYouTube(ia)

    def pontuar(chave, acertou):
        t = placar.setdefault(chave, [0, 0])
        t[0] += int(acertou)
        t[1] += 1

    def rodar(url, tarefa, consulta, verificar, rotulo):
        nonlocal n
        n += 1
        nome = f"{n:02d}_{id_do_video(url)}_{tarefa}_{slug(consulta or tarefa)}"
        print(f"[{n}] {rotulo}")
        t0 = time.time()
        try:
            r = yt.executar(url, tarefa, consulta)
            problemas = verificar(r)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            err = classificar_erro(e)
            r, problemas = None, [f"ERRO {err.codigo}: {err.mensagem}"]
            tb = traceback.format_exc()[-2500:]
        else:
            tb = ""
        if problemas:
            print(f"   ⚠️  ({time.time() - t0:.0f}s)")
            for p in problemas:
                print(f"      - {p}")
            pasta.mkdir(exist_ok=True)
            arqs = ia.salvar_print(pasta / nome)
            if r is not None:
                (pasta / f"{nome}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
                arqs["json"] = str(pasta / f"{nome}.json")
            falhas.append({"nome": nome, "url": url, "tarefa": tarefa, "consulta": consulta, "problemas": problemas,
                           "arquivos": [Path(x).name for x in arqs.values()], "erro": tb})
        else:
            print(f"   ✅ ok ({time.time() - t0:.0f}s)")
        time.sleep(a.pausa)
        return r

    try:
        for url in urls:
            print(f"\n🎬 {url}")
            tr, nome_tr = [], None
            # 1) resumo -> descobre qual transcrição é deste vídeo
            r = rodar(url, "resumo", "", lambda r: checar_basico(r, "resumo", None), "Resumo")
            if r:
                nome_tr = escolher_transcricao(json.dumps(r.get("dados"), ensure_ascii=False), transcricoes)
                tr = transcricoes.get(nome_tr, [])
                print(f"   (transcrição usada para conferir: {nome_tr or 'nenhuma'})")
            dur = tr[-1][0] + 10 if tr else None
            casos = CASOS.get(nome_tr, {})

            for desc, ei, ef in casos.get("momentos", []):
                def v(r, ei=ei, ef=ef):
                    p = checar_basico(r, "momentos", dur)
                    pm, acertou = checar_momentos(r, ei, ef)
                    pontuar("momentos certos", acertou)
                    return p + pm
                rodar(url, "momentos", desc, v, f"Momentos: {desc}")

            for perg, chaves in casos.get("perguntas", []):
                def v(r, chaves=chaves):
                    p = checar_basico(r, "pergunta", dur)
                    pp, acertou = checar_pergunta(r, chaves)
                    pontuar("perguntas certas", acertou)
                    return p + pp
                rodar(url, "pergunta", perg, v, f"Pergunta: {perg}")

            if a.rapido:
                continue
            for tarefa in ("capitulos", "cortes", "citacoes", "fatos", "quiz"):
                def v(r, tarefa=tarefa):
                    p = checar_basico(r, tarefa, dur)
                    if tr:
                        pc, ok, total = checar_citacoes(r, tr)
                        if total:
                            t = placar.setdefault("frases no tempo certo", [0, 0])
                            t[0] += ok
                            t[1] += total
                        p += pc
                    return p
                rodar(url, tarefa, "", v, tarefa.capitalize())
    except KeyboardInterrupt:
        print("\n⏹  Interrompido.")
    finally:
        ia.fechar()

    dur_total = (time.time() - inicio) / 60
    print("\n" + "=" * 60)
    print("PLACAR DE PRECISÃO:")
    for k, (acertos, total) in placar.items():
        print(f"   {k}: {acertos}/{total} ({acertos / total:.0%})" if total else f"   {k}: -")
    if not falhas:
        print(f"\n✅ Tudo certo! {n} análises sem problemas ({dur_total:.1f} min). Nenhum arquivo gerado.")
        return

    contagem = {}
    for f in falhas:
        for p in f["problemas"]:
            cod = p.split(":")[0].replace("ERRO ", "")
            contagem[cod] = contagem.get(cod, 0) + 1
    linhas = ["RELATÓRIO — análise de vídeos do YouTube", f"Data: {time.strftime('%Y-%m-%d %H:%M')}  Duração: {dur_total:.1f} min",
              f"Análises: {n}   Com problema: {len(falhas)}", "", "PLACAR DE PRECISÃO:"]
    linhas += [f"  {k}: {a_}/{t_}" for k, (a_, t_) in placar.items()]
    linhas += ["", "RESUMO POR TIPO DE PROBLEMA:"] + [f"  {q:3d}x  {c}" for c, q in sorted(contagem.items(), key=lambda x: -x[1])]
    linhas.append("")
    for f in falhas:
        linhas += ["-" * 70, f"TESTE: {f['nome']}", f"Vídeo: {f['url']}", f"Tarefa: {f['tarefa']}   Consulta: {f['consulta']}",
                   "Problemas:", *[f"  - {p}" for p in f["problemas"]], "Arquivos:  " + ", ".join(f["arquivos"])]
        if f["erro"]:
            linhas += ["Traceback:", f["erro"]]
        linhas.append("")
    (pasta / "RELATORIO.txt").write_text("\n".join(linhas), encoding="utf-8")
    zip_path = pasta.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arq in sorted(pasta.iterdir()):
            z.write(arq, f"{pasta.name}/{arq.name}")
    print(f"\n⚠️  {len(falhas)} de {n} análises com problema.")
    for c, q in sorted(contagem.items(), key=lambda x: -x[1]):
        print(f"   {q}x {c}")
    print(f"\n📦 Mande este arquivo: {zip_path}")


if __name__ == "__main__":
    main()
