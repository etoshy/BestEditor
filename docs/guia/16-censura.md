# 16 · Censura (blur, pixelado, tarja, bip)

No Estúdio, use o botão **🙈 Censura** ou dê duplo clique na faixa **Censura**. Depois arraste a área no monitor.

| Tipo | O que faz |
|---|---|
| `blur` | desfoque (rosto, placa, documento) |
| `pixel` | mosaico |
| `tarja` | tarja sólida com cor e rótulo opcional ("CENSURADO") |
| `bip` | silencia a fala e os efeitos, e toca o "piiii" (volume e tom ajustáveis) |
| `mudo` | só silencia |

Outras opções:

- formas: retângulo ou **elipse**;
- intensidade de 1 a 10;
- **tela inteira**;
- **"a área desliza"**: do ponto inicial ao final, para acompanhar algo que se mexe.

A censura de imagem é aplicada **antes** dos textos, destaques e gráficos, que continuam legíveis por cima.

## Com código: um tipo novo

Exemplo: "olhos" (uma tarja fina na altura dos olhos).

1. Em `dp_censura.py`, acrescente em `TIPOS_VIDEO` (ou em `TIPOS_AUDIO`, se for de som).
2. Desenhe em `montar_filtro()`. A área já vem recortada (`crop`, com o deslizar e a máscara de elipse prontos);
   você só escreve o `efeito` aplicado no recorte, ao lado de `blur` (`gblur`) e `pixel` (reduz e amplia).
   Para algo desenhado por cima, como a tarja, crie um PNG (veja `_png_tarja`).
   O áudio fica em `filtro_audio()`.
3. Em `normalizar()`, trate as opções novas (cor, rótulo…), se tiver.
4. Prévia em `templates/estudio.html → desenharCzMonitor()`.
5. `pytest test_v82_censura.py`.
