# 07 · Legendas (bloco e karaokê)

Aba **📝 Legendas** do Estúdio. A legenda usa o `.srt` do zip (o tempo de cada palavra é estimado dentro do bloco)
ou as palavras do Whisper.

| Tipo | Estilos de fábrica |
|---|---|
| Bloco | Seguir texto (`seguir`), Caixa (`caixa`), Contorno forte (`contorno`), Cinema (`cinema`), Faixa colorida (`faixa`) |
| Karaokê | Clássico (`classico`), Destaque (`destaque`), Pop (`pop`), Palavra única (`palavra_unica`), Preenchimento (`preenchimento`) |

## Sem programar: o que já dá para mudar

Antes de criar um estilo, veja se as opções resolvem:

- fonte (qualquer uma das fontes DP, inclusive as suas — ver [12](12-fontes.md));
- tamanho;
- posição (base, meio, topo);
- palavras por linha;
- maiúsculas;
- contorno;
- cor do texto e cor da palavra ativa (ou a da paleta);
- "Legenda sob templates/destaques": Automático, Manter ou Ocultar.

Uma configuração de legenda pode ser guardada numa **Direção sua** (aba 🎨 Direção → ＋ Nova → eixo Legenda, que leva
a config atual da aba Legendas). Assim você reaplica o "seu estilo" em qualquer projeto com um clique.

## Com código: um estilo novo

Exemplo: um karaokê "sublinha", em que a palavra falada ganha um traço embaixo.

1. **`dp_legendas.py → ESTILOS`**: `{"id": "sublinha", "nome": "Sublinha", "tipo": "karaoke"}`.
2. **`dp_legendas.py → gerar_ass()`**: no `for` dos estilos karaokê (o bloco de `classico`/`pop`), acrescente o caso:
   ```python
   elif estilo == "sublinha":
       partes.append(f"{{\\u1\\1c{_c(cor_ativa)}}}{esc(tx)}{{\\u0\\1c{branco}}}{sep}")
   ```
   Tags ASS úteis:
   - `\1c&HBBGGRR&` (cor)
   - `\fscx`/`\fscy` (escala)
   - `\t(t0,t1,…)` (animar)
   - `\kf` (preenchimento)
   - `\bord` (contorno)
   - `\blur`
   - `\u1` (sublinhado)
   - `\p1` (desenho vetorial)
3. **Prévia**, em `templates/estudio.html`:
   - `amostraLeg(id)` desenha o quadradinho da galeria;
   - `desenharLegenda(t)` desenha a legenda no monitor. Inclua o id na lista `kara` e o estilo da palavra ativa.
4. Teste com `pytest test_cores_legendas.py test_legendas.py` e monte um vídeo curto: o `<job>_legendado.mp4` tem
   que bater com o monitor.

O `.srt` gerado no **Gerador de voz** é outra coisa (`legendas.py`: modos `legenda`, `palavra`, `tempo`) e não tem
estilo, só texto e tempo.
