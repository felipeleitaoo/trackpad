# iPad Trackpad

Transforme um iPad (mesmo um bem antigo) em **trackpad, teclado e segunda tela touch** para o seu PC com Windows. Nada para instalar no iPad: ele só abre uma página no Safari.

> Projeto feito em uma tarde de domingo, em parceria com o Claude (Anthropic).

## O que faz

- **Trackpad completo:** mover, clicar, clique direito (2 dedos), rolar, zoom por pinça e arrastar.
- **Botões Esquerdo/Direito** na tela, como os de um touchpad físico.
- **Teclado:** usa o teclado do iPad (com acentos) e tem barra com Esc, Tab, Ctrl, Alt, setas, Del, Enter, Copiar, Colar, F1-F12, Home, End, PgUp e PgDn.
- **Espelho da tela:** mostra o PC no iPad e o toque vira clique onde você encosta, com o ponteiro real do Windows desenhado (seta, redimensionar, texto, mão).
- **Vários monitores:** o botão **Tela** alterna entre eles. Com um monitor virtual, o iPad funciona como segunda tela estendida.

## Requisitos

- Windows 10 ou 11
- Python 3.7+
- iPad e PC na mesma rede Wi-Fi
- Para o espelho: `pillow` e `mss`

```bash
python -m pip install -r requirements.txt
```

## Como usar

1. Rode `python trackpad.py` (ou dê dois cliques em `trackpad.bat`. Recomendo criar atalho para area de trabalho).
2. No Safari do iPad, abra o endereço que aparece no terminal.
3. Opcional: **Compartilhar > Adicionar à Tela de Início** para abrir em tela cheia.

Na primeira execução, o Windows pode pedir permissão de rede para o Python. Permita em **Redes particulares**.

### Gestos

| Gesto | Ação |
|---|---|
| 1 dedo arrastando | mover o cursor |
| toque com 1 dedo | clique esquerdo (2 toques = duplo clique) |
| toque com 2 dedos | clique direito |
| 2 dedos arrastando | rolar |
| pinça com 2 dedos | zoom (Ctrl + roda do mouse) |
| toque e, logo depois, toque e arraste | arrastar |
| segurar **Esquerdo** + arrastar com outro dedo | arrastar/selecionar |

## Usar como segunda tela (estendida)

O script espelha monitores que já existem no Windows. Para ter uma segunda tela, crie um monitor virtual:

1. Instale o [Virtual Display Driver](https://github.com/VirtualDrivers/Virtual-Display-Driver) (projeto de terceiros; confira a página antes de instalar, pois é um driver).
2. Em **Configurações > Sistema > Tela**, escolha **Estender estas telas**.
3. Ajuste a resolução do monitor virtual para a do seu iPad (por exemplo 2360x1640) e a taxa para 60 Hz.
4. No iPad, toque em **Espelho** e depois em **Tela** até chegar ao monitor virtual.

## Ajustes

No topo do `trackpad.py`: `PORTA`, `SENSIBILIDADE`, `ROLAGEM_NATURAL`, `SENS_ROLAGEM`, `PASSO_ZOOM`, `TELA`, `QUALIDADE` (JPEG), `FPS_MAX`, `DESENHAR_CURSOR` e `ESCALA_CURSOR`.

## Segurança (leia)

Este programa **controla o mouse e o teclado do seu PC** por HTTP, sem criptografia.

- Use **somente em rede local confiável**. Nunca exponha a porta à internet (sem port forwarding, sem túnel público).
- O endereço contém um código (`?k=...`) que funciona como senha. Ele fica salvo em `trackpad_token.txt`, que **não deve ser compartilhado nem enviado ao Git**. Para gerar outro, apague o arquivo e reinicie.
- A tecla Windows e combinações como Ctrl+Alt+Del ficam de fora de propósito.
- Pare o programa com `Ctrl+C` quando não estiver usando.

## Limitações

- Só Windows.
- O espelho envia um JPEG por requisição, então a fluidez depende do Wi-Fi e da resolução. Reduza `QUALIDADE` ou a resolução do monitor virtual se ficar lento.
- O cursor de "ocupado" aparece parado, sem animação.

## Licença

MIT. Veja o arquivo `LICENSE`.