#!/usr/bin/env python3
"""
iPad como trackpad para o Windows (via Safari, sem instalar nada no iPad).

Como usar:
  1. Rode este arquivo no PC (python trackpad.py) ou de dois cliques em iniciar_trackpad.bat
  2. No Safari do iPad, abra o endereco que aparece na tela.
  3. Opcional: Compartilhar > "Adicionar a Tela de Inicio" para abrir em tela cheia.

Gestos:
  1 dedo arrastando ........ mover o cursor
  toque com 1 dedo ......... clique esquerdo (dois toques rapidos = duplo clique)
  toque com 2 dedos ........ clique direito
  2 dedos arrastando ....... rolar (vertical)
  pinca com 2 dedos ........ zoom (Ctrl + roda do mouse)
  toque e, logo em seguida, toque e arraste ... arrastar (segura o botao esquerdo)
  botoes Esquerdo / Direito (embaixo) ... como os botoes fisicos de um touchpad; segure o
                             Esquerdo e arraste com outro dedo no pad para arrastar/selecionar
  botao "Teclado" .......... abre o teclado do iPad e digita no PC (com acentos);
                             a barra tem Esc, Tab, Ctrl, Alt, setas, Del, Enter, Copiar e Colar;
                             "F1-F12" abre mais teclas (F1 a F12, Shift, Home, End, PgUp, PgDn)
  botao "Espelho" .......... mostra a tela do PC no iPad; ai o toque vira clique onde voce
                             encosta. Precisa de: python -m pip install pillow mss
                             ("Ocultar" esconde a barra; o botao redondo no canto traz de volta)
  botao "Tela" ............. alterna entre os monitores do PC (ex.: um monitor virtual,
                             que funciona como segunda tela estendida)

Nao precisa instalar nada alem do Python 3.7+ (e Pillow + mss para o espelho). Parar: Ctrl+C.
"""
import ctypes
import io
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# ----------------------------- AJUSTES ------------------------------------
PORTA = 8765
SENSIBILIDADE = 1.8        # velocidade do cursor (maior = mais rapido)
ROLAGEM_NATURAL = True     # True: dedos para baixo = conteudo desce (como no iPad)
SENS_ROLAGEM = 1.0         # velocidade da rolagem
PASSO_ZOOM = 14            # pixels de pinca para cada "clique" de zoom
TELA = 1                   # monitor que o espelho mostra ao abrir: 1 = principal, 2, 3... (a lista
                           # aparece ao iniciar; no iPad o botao "Tela" troca) ou "todas"
QUALIDADE = 60             # qualidade do JPEG do espelho (1-95; menor = mais rapido)
FPS_MAX = 15               # limite de quadros por segundo do espelho
DESENHAR_CURSOR = True     # desenha o ponteiro do mouse na imagem do espelho
ESCALA_CURSOR = 1.5        # tamanho do ponteiro no espelho (1.0 = tamanho original do Windows)
# --------------------------------------------------------------------------

DIR = os.path.dirname(os.path.abspath(__file__))
ARQ_TOKEN = os.path.join(DIR, "trackpad_token.txt")

# ---------------------- controle do mouse (Windows) ------------------------
WINDOWS = sys.platform == "win32"

MOVE, LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP, WHEEL = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0800
VK_CONTROL, KEYUP = 0x11, 0x0002

if WINDOWS:
    _u = ctypes.windll.user32
    try:  # coordenadas em pixels reais (sem escala do Windows), para o espelho bater com o clique
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _u.SetProcessDPIAware()
        except Exception:
            pass

    def _me(flags, dx=0, dy=0, data=0):
        _u.mouse_event(flags, dx & 0xFFFFFFFF, dy & 0xFFFFFFFF, data & 0xFFFFFFFF, 0)

    def _ctrl(baixo):
        _u.keybd_event(VK_CONTROL, 0, 0 if baixo else KEYUP, 0)
else:  # modo de teste fora do Windows: so imprime
    def _me(flags, dx=0, dy=0, data=0):
        print("mouse_event flags=%#x dx=%d dy=%d data=%d" % (flags, dx, dy, data))

    def _ctrl(baixo):
        print("ctrl", "down" if baixo else "up")


def mover(dx, dy):
    if dx or dy:
        _me(MOVE, dx, dy)


def rolar(n):
    if n:
        _me(WHEEL, 0, 0, n)


def zoom(n):
    if n:
        _ctrl(True)
        _me(WHEEL, 0, 0, n * 120)
        _ctrl(False)


def acao(nome):
    if nome == "c":
        _me(LEFTDOWN); _me(LEFTUP)
    elif nome == "r":
        _me(RIGHTDOWN); _me(RIGHTUP)
    elif nome == "d":
        _me(LEFTDOWN)
    elif nome == "u":
        _me(LEFTUP)
    elif nome == "rd":
        _me(RIGHTDOWN)
    elif nome == "ru":
        _me(RIGHTUP)


# ----------------------------- espelho da tela ------------------------------
try:
    from PIL import Image, ImageDraw, ImageGrab
    TEM_PIL = True
except ImportError:
    TEM_PIL = False

try:  # captura confiavel de qualquer monitor (inclusive monitor virtual)
    import mss
    TEM_MSS = True
except ImportError:
    TEM_MSS = False

_trava = threading.Lock()
_cache = {"t": 0.0, "chave": None, "dados": b""}


def listar_monitores():
    """[(esquerda, topo, largura, altura), ...] com o monitor principal primeiro."""
    if not WINDOWS:  # modo de teste
        return [(0, 0, 1920, 1080), (1920, 0, 1280, 1024)]

    class _RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

    tipo_cb = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.POINTER(_RECT), ctypes.c_void_p)
    achados = []

    def _cb(hmon, hdc, rc, lp):
        r = rc.contents
        achados.append((r.l, r.t, r.r - r.l, r.b - r.t))
        return 1

    cb = tipo_cb(_cb)
    _u.EnumDisplayMonitors(None, None, cb, 0)
    if not achados:
        achados.append((0, 0, _u.GetSystemMetrics(0), _u.GetSystemMetrics(1)))
    achados.sort(key=lambda m: (not (m[0] == 0 and m[1] == 0), m[0], m[1]))
    return achados


def retangulo_tela(n=None):
    """(esquerda, topo, largura, altura) do monitor n (1 = principal). Sem n, usa TELA."""
    if n is None:
        n = TELA
    if n == "todas" and WINDOWS:
        return (_u.GetSystemMetrics(76), _u.GetSystemMetrics(77),
                _u.GetSystemMetrics(78), _u.GetSystemMetrics(79))
    mons = listar_monitores()
    n = n if isinstance(n, int) else 1
    return mons[max(1, min(n, len(mons))) - 1]


def mover_abs(ax, ay, n=None):
    """ax, ay: posicao em 0..10000 dentro da imagem espelhada do monitor n."""
    e, t, larg, alt = retangulo_tela(n)
    x = e + int(max(0, min(10000, ax)) / 10000.0 * (larg - 1))
    y = t + int(max(0, min(10000, ay)) / 10000.0 * (alt - 1))
    if WINDOWS:
        _u.SetCursorPos(x, y)
    else:
        print("cursor em %d,%d" % (x, y))


if WINDOWS:
    class _PT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _CURSORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                    ("hCursor", ctypes.c_void_p), ("ptScreenPos", _PT)]

    class _ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", ctypes.c_int), ("xHotspot", ctypes.c_uint32),
                    ("yHotspot", ctypes.c_uint32), ("hbmMask", ctypes.c_void_p),
                    ("hbmColor", ctypes.c_void_p)]

    class _BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long),
                    ("bmHeight", ctypes.c_long), ("bmWidthBytes", ctypes.c_long),
                    ("bmPlanes", ctypes.c_ushort), ("bmBitsPixel", ctypes.c_ushort),
                    ("bmBits", ctypes.c_void_p)]

    class _BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_ushort),
                    ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPels", ctypes.c_long),
                    ("biYPels", ctypes.c_long), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    _g = ctypes.windll.gdi32
    _vp, _ci_ = ctypes.c_void_p, ctypes.c_int
    _u.GetCursorInfo.argtypes = [ctypes.POINTER(_CURSORINFO)]
    _u.GetIconInfo.argtypes = [_vp, ctypes.POINTER(_ICONINFO)]
    _u.DrawIconEx.argtypes = [_vp, _ci_, _ci_, _vp, _ci_, _ci_, ctypes.c_uint, _vp, ctypes.c_uint]
    _u.GetDC.restype, _u.GetDC.argtypes = _vp, [_vp]
    _u.ReleaseDC.argtypes = [_vp, _vp]
    _g.CreateCompatibleDC.restype, _g.CreateCompatibleDC.argtypes = _vp, [_vp]
    _g.CreateDIBSection.restype = _vp
    _g.CreateDIBSection.argtypes = [_vp, _vp, ctypes.c_uint, ctypes.POINTER(_vp), _vp, ctypes.c_uint32]
    _g.SelectObject.restype, _g.SelectObject.argtypes = _vp, [_vp, _vp]
    _g.DeleteObject.argtypes = [_vp]
    _g.DeleteDC.argtypes = [_vp]
    _g.GetObjectW.argtypes = [_vp, _ci_, _vp]

    def pos_cursor():
        p = _PT()
        _u.GetCursorPos(ctypes.byref(p))
        return p.x, p.y

    def _tamanho_cursor(info):
        """Largura e altura do cursor a partir das bitmaps do ICONINFO."""
        bm = _BITMAP()
        if info.hbmColor:
            _g.GetObjectW(info.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm))
            return bm.bmWidth, bm.bmHeight
        _g.GetObjectW(info.hbmMask, ctypes.sizeof(bm), ctypes.byref(bm))  # mono: mascara AND+XOR
        return bm.bmWidth, bm.bmHeight // 2

    def _renderizar(hcur, w, h):
        """Desenha o cursor sobre fundo preto e fundo branco e devolve os dois BGRA brutos."""
        hdc0 = _u.GetDC(None)
        mem = _g.CreateCompatibleDC(hdc0)
        bmi = _BMIH(ctypes.sizeof(_BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bmp = _g.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        antigo = _g.SelectObject(mem, bmp)
        saidas = []
        try:
            for fundo in (0x00, 0xFF):
                ctypes.memset(bits, fundo, w * h * 4)
                _u.DrawIconEx(mem, 0, 0, hcur, w, h, 0, None, 3)   # 3 = DI_NORMAL
                saidas.append(ctypes.string_at(bits, w * h * 4))
        finally:
            _g.SelectObject(mem, antigo)
            _g.DeleteObject(bmp)
            _g.DeleteDC(mem)
            _u.ReleaseDC(None, hdc0)
        return saidas[0], saidas[1]

    _cur_cache = {}

    def _montar_cursor(hcur):
        info = _ICONINFO()
        _u.GetIconInfo(hcur, ctypes.byref(info))
        try:
            w, h = _tamanho_cursor(info)
            hx, hy = info.xHotspot, info.yHotspot
        finally:
            if info.hbmMask:
                _g.DeleteObject(info.hbmMask)
            if info.hbmColor:
                _g.DeleteObject(info.hbmColor)
        if not (0 < w <= 512 and 0 < h <= 512):
            w = h = 32
        preto, branco = _renderizar(hcur, w, h)
        return _compor_rgba(preto, branco, w, h), hx, hy

    def cursor_atual():
        """(x, y, imagem RGBA, hotspot_x, hotspot_y) do ponteiro real, ou None se oculto."""
        ci = _CURSORINFO()
        ci.cbSize = ctypes.sizeof(ci)
        if not _u.GetCursorInfo(ctypes.byref(ci)) or not (ci.flags & 1) or not ci.hCursor:
            return None
        h = ci.hCursor
        if h not in _cur_cache:
            if len(_cur_cache) > 64:
                _cur_cache.clear()
            _cur_cache[h] = _montar_cursor(h)
        img, hx, hy = _cur_cache[h]
        return ci.ptScreenPos.x, ci.ptScreenPos.y, img, hx, hy
else:
    def pos_cursor():
        return 200, 150

    def cursor_atual():
        return None


def _compor_rgba(preto, branco, w, h):
    """Recupera a transparencia do cursor comparando o desenho sobre preto e sobre branco."""
    out = bytearray(w * h * 4)
    for i in range(0, w * h * 4, 4):
        b0, g0, r0 = preto[i], preto[i + 1], preto[i + 2]
        b1, g1, r1 = branco[i], branco[i + 1], branco[i + 2]
        dif = ((r1 - r0) + (g1 - g0) + (b1 - b0)) // 3
        a = 255 - max(0, min(255, dif))
        if a > 0:
            out[i] = min(255, r0 * 255 // a)
            out[i + 1] = min(255, g0 * 255 // a)
            out[i + 2] = min(255, b0 * 255 // a)
            out[i + 3] = a
    return Image.frombytes("RGBA", (w, h), bytes(out))


def _desenhar_seta(img, e, t, esc):
    """Seta simples, usada se nao der para pegar o ponteiro real do Windows."""
    cx, cy = pos_cursor()
    x, y = int((cx - e) * esc), int((cy - t) * esc)
    if x < 0 or y < 0 or x >= img.width or y >= img.height:
        return
    s = max(18, img.height // 38)
    forma = [(0, 0), (0, 0.85), (0.22, 0.66), (0.38, 1.0), (0.52, 0.93), (0.37, 0.6), (0.65, 0.6)]
    pts = [(x + px * s, y + py * s) for px, py in forma]
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=(255, 255, 255))
    d.line(pts + [pts[0]], fill=(0, 0, 0), width=2)


def desenhar_cursor(img, e, t, esc):
    """Desenha o ponteiro real do Windows (seta, redimensionar, texto, mao...) na imagem."""
    try:
        c = cursor_atual() if WINDOWS else None
    except Exception:
        c = None
    if c is None:
        if not WINDOWS:
            _desenhar_seta(img, e, t, esc)
        return
    cx, cy, cur, hx, hy = c
    k = ESCALA_CURSOR
    if k != 1.0:
        nova = (max(1, int(cur.width * k)), max(1, int(cur.height * k)))
        cur = cur.resize(nova, getattr(Image, "Resampling", Image).BILINEAR)
    x = int((cx - e) * esc - hx * k)
    y = int((cy - t) * esc - hy * k)
    img.paste(cur, (x, y), cur)


def _capturar(n, e, t, larg, alt):
    """Imagem PIL do monitor n. Usa mss (coordenadas absolutas) e, sem ele, o ImageGrab."""
    todas = (TELA if n is None else n) == "todas"
    if TEM_MSS:
        with mss.mss() as sct:
            if todas:
                area = sct.monitors[0]
            else:
                area = {"left": e, "top": t, "width": larg, "height": alt}
            s = sct.grab(area)
            return Image.frombytes("RGB", s.size, s.bgra, "raw", "BGRX")
    if todas:
        return ImageGrab.grab(all_screens=True)
    if e == 0 and t == 0:
        return ImageGrab.grab()
    return ImageGrab.grab(bbox=(e, t, e + larg, t + alt), all_screens=True)


def quadro(caixa_w, caixa_h, n=None):
    """JPEG do monitor n, reduzido para caber na caixa (largura x altura) do iPad."""
    chave = (caixa_w, caixa_h, n)
    with _trava:
        if _cache["chave"] == chave and time.time() - _cache["t"] < 1.0 / FPS_MAX:
            return _cache["dados"]
        e, t, larg, alt = retangulo_tela(n)
        if WINDOWS:
            img = _capturar(n, e, t, larg, alt)
        else:
            img = Image.new("RGB", (larg, alt), (30, 90, 160))
        img = img.convert("RGB")
        esc = min(caixa_w / float(img.width), caixa_h / float(img.height), 1.0)
        if esc < 1.0:
            nova = (max(1, int(img.width * esc)), max(1, int(img.height * esc)))
            img = img.resize(nova, getattr(Image, "Resampling", Image).BILINEAR)
        if DESENHAR_CURSOR:
            desenhar_cursor(img, e, t, esc)
        saida = io.BytesIO()
        img.save(saida, "JPEG", quality=QUALIDADE)
        _cache.update(t=time.time(), chave=chave, dados=saida.getvalue())
        return _cache["dados"]


# ----------------------------- teclado -------------------------------------
KEYEVENTF_EXTENDED, KEYEVENTF_UNICODE = 0x0001, 0x0004
VK = {"back": 0x08, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "space": 0x20,
      "pgup": 0x21, "pgdn": 0x22, "end": 0x23, "home": 0x24,
      "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "del": 0x2E}
VK.update({"f%d" % i: 0x6F + i for i in range(1, 13)})   # F1..F12
ESTENDIDAS = {"pgup", "pgdn", "end", "home", "left", "up", "right", "down", "del"}
# So Ctrl, Alt e Shift. A tecla Windows fica de fora de proposito (menos risco se alguem
# achar o endereco do trackpad).
MODS = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}

if WINDOWS:
    class _KI(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class _MI(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("mi", _MI)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    _u.VkKeyScanW.restype = ctypes.c_short
    _u.VkKeyScanW.argtypes = [ctypes.c_wchar]

    def _unicode(unidade):
        for fl in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYUP):
            i = _INPUT(type=1, u=_U(ki=_KI(0, unidade, fl, 0, 0)))
            _u.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))

    def _vk_de(ch):
        r = _u.VkKeyScanW(ch)
        return None if r == -1 else (r & 0xFF)

    def _kb(vk, baixo, ext=False):
        fl = (KEYEVENTF_EXTENDED if ext else 0) | (0 if baixo else KEYUP)
        _u.keybd_event(vk, 0, fl, 0)
else:  # modo de teste fora do Windows
    def _unicode(unidade):
        print("unicode %#x" % unidade)

    def _vk_de(ch):
        return ord(ch.upper())

    def _kb(vk, baixo, ext=False):
        print("key vk=%#x %s" % (vk, "down" if baixo else "up"))


def digitar(texto):
    for ch in texto:
        if ch in "\r\n":
            tecla("enter")
        elif ch == "\t":
            tecla("tab")
        elif ord(ch) >= 32:
            dados = ch.encode("utf-16-le", "ignore")
            for i in range(0, len(dados), 2):
                _unicode(dados[i] | (dados[i + 1] << 8))


def tecla(combo):
    """Ex.: 'enter', 'left', 'ctrl+c', 'ctrl+alt+del' nao existe (so ctrl/alt/shift)."""
    combo = combo.lower()
    if combo.endswith("+"):                      # ex.: ctrl++
        nome, mods = "+", [m for m in combo[:-1].split("+") if m]
    else:
        partes = combo.split("+")
        nome, mods = partes[-1], partes[:-1]
    if any(m not in MODS for m in mods):
        return
    if nome in VK:
        vk, ext = VK[nome], nome in ESTENDIDAS
    elif len(nome) == 1:
        vk, ext = _vk_de(nome), False
        if vk is None:
            digitar(nome)
            return
    else:
        return
    for m in mods:
        _kb(MODS[m], True)
    _kb(vk, True, ext)
    _kb(vk, False, ext)
    for m in reversed(mods):
        _kb(MODS[m], False)


def inteiro(q, chave, limite):
    try:
        v = int(q.get(chave, ["0"])[0])
    except ValueError:
        return 0
    return max(-limite, min(limite, v))


def aplicar(q):
    if "ax" in q and "ay" in q:
        mover_abs(inteiro(q, "ax", 10000), inteiro(q, "ay", 10000), inteiro(q, "mon", 20) or None)
    mover(inteiro(q, "dx", 400), inteiro(q, "dy", 400))
    rolar(inteiro(q, "sc", 2000))
    zoom(inteiro(q, "zm", 10))
    for e in q.get("e", [""])[0].split(","):
        acao(e)
    kb = q.get("kb", [""])[0]
    if kb:
        try:
            itens = json.loads(kb)
        except ValueError:
            itens = []
        if isinstance(itens, list):
            for it in itens[:100]:
                if not isinstance(it, dict):
                    continue
                if isinstance(it.get("t"), str):
                    digitar(it["t"][:200])
                elif isinstance(it.get("k"), str):
                    tecla(it["k"][:30])


# ----------------------------- pagina web ---------------------------------
PAGINA = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black">
<title>Trackpad</title>
<style>
html,body{margin:0;height:100%;background:#151515;color:#5a5a5a;font-family:-apple-system,Helvetica,Arial,sans-serif;
overflow:hidden;-webkit-user-select:none;-webkit-touch-callout:none;-webkit-tap-highlight-color:rgba(0,0,0,0)}
#pad{position:absolute;top:0;left:0;right:0;bottom:0}
#dica{position:absolute;left:0;right:0;bottom:100px;text-align:center;font-size:15px;line-height:1.6;pointer-events:none}
#barra{position:absolute;top:0;left:0;right:0;z-index:5;padding:6px 8px;background:#1d1d1d;border-bottom:1px solid #2c2c2c}
#barra button{margin:3px;min-width:52px;height:44px;padding:0 10px;border:1px solid #3a3a3a;border-radius:8px;
background:#262626;color:#d0d0d0;font-size:16px;-webkit-appearance:none}
#barra button.on{background:#2f6fed;border-color:#2f6fed;color:#fff}
#estado{float:right;margin:16px 6px 0 0;font-size:13px;color:#6a6a6a}
#entrada{position:fixed;top:70px;left:8px;width:1px;height:1px;opacity:0;border:0;padding:0;font-size:16px}
#tela{position:absolute;top:50%;left:50%;-webkit-transform:translate(-50%,-50%);transform:translate(-50%,-50%);display:none;background:#000}
#pad{z-index:1}
#extra{display:none}
#btns{position:absolute;left:0;right:0;bottom:0;z-index:5;display:flex;box-sizing:border-box;padding:8px 8px 14px}
.mb{flex:1;margin:0 4px;height:64px;line-height:64px;text-align:center;border:1px solid #3a3a3a;border-radius:12px;
background:#262626;color:#d0d0d0;font-size:17px}
.mb.on{background:#2f6fed;border-color:#2f6fed;color:#fff}
#btns.esp .mb{opacity:.5}
#mini{position:absolute;top:6px;right:6px;z-index:6;display:none;width:44px;height:44px;padding:0;border:1px solid #3a3a3a;
border-radius:22px;background:rgba(30,30,30,.75);color:#ddd;font-size:18px;-webkit-appearance:none}
</style></head><body>
<canvas id="tela"></canvas>
<div id="pad"></div>
<button id="mini">&#9776;</button>
<div id="btns"><div class="mb" id="bL">Esquerdo</div><div class="mb" id="bR">Direito</div></div>
<div id="barra">
<button id="bEsp">Espelho</button><button id="bTela">Tela 1</button><button id="bTec">Teclado</button><button id="bExt">F1-F12</button>
<button id="bEsc">Esc</button><button id="bTab">Tab</button>
<button id="bCtrl">Ctrl</button><button id="bAlt">Alt</button>
<button id="bEsq">&larr;</button><button id="bCima">&uarr;</button><button id="bBaixo">&darr;</button><button id="bDir">&rarr;</button>
<button id="bDel">Del</button><button id="bEnt">Enter</button>
<button id="bCop">Copiar</button><button id="bCol">Colar</button><button id="bOcul">Ocultar</button>
<span id="estado">conectando...</span>
<div id="extra">
<button data-k="f1">F1</button><button data-k="f2">F2</button><button data-k="f3">F3</button><button data-k="f4">F4</button>
<button data-k="f5">F5</button><button data-k="f6">F6</button><button data-k="f7">F7</button><button data-k="f8">F8</button>
<button data-k="f9">F9</button><button data-k="f10">F10</button><button data-k="f11">F11</button><button data-k="f12">F12</button>
<button data-k="home">Home</button><button data-k="end">End</button><button data-k="pgup">PgUp</button><button data-k="pgdn">PgDn</button>
<button id="bShift">Shift</button>
</div>
</div>
<textarea id="entrada" autocapitalize="off" autocorrect="off" autocomplete="off" spellcheck="false"> </textarea>
<div id="dica">1 dedo: mover &middot; toque: clique &middot; 2 dedos: rolar / zoom<br>
toque com 2 dedos: botao direito &middot; toque e arraste logo depois: arrastar<br>
botao Teclado: abre o teclado do iPad</div>
<script>
var K="__TOKEN__", SENS=__SENS__, SENSR=__SENSR__, NATURAL=__NAT__, STEP=__STEP__;
var pdx=0, pdy=0, psc=0, pzm=0, evs=[], kbq=[], busy=false, pax=null, pay=null, espelho=false, rodando=false, mon=0, nmon=1;
var estado=document.getElementById("estado");

function flush(){
  if(busy) return;
  var dx=Math.round(pdx), dy=Math.round(pdy), sc=Math.round(psc*4), zm=pzm;
  if(!dx && !dy && !sc && !zm && !evs.length && !kbq.length && pax===null) return;
  pdx-=dx; pdy-=dy; psc=0; pzm=0;
  var e=evs.join(","); evs=[];
  var kb=kbq.length ? "&kb="+encodeURIComponent(JSON.stringify(kbq)) : ""; kbq=[];
  var ab=(pax!==null) ? "&ax="+pax+"&ay="+pay+"&mon="+mon : ""; pax=null; pay=null;
  var url="/m?k="+K+ab+"&dx="+dx+"&dy="+dy+"&sc="+sc+"&zm="+zm+"&e="+e+kb+"&t="+(+new Date());
  busy=true;
  var x=new XMLHttpRequest();
  x.open("GET",url,true);
  x.timeout=1000;
  x.onreadystatechange=function(){
    if(x.readyState===4){ busy=false; estado.textContent = x.status===200 ? "conectado" : "sem conexao"; }
  };
  x.ontimeout=function(){ busy=false; estado.textContent="sem conexao"; };
  x.send();
}
setInterval(flush, 16);

var t0=0, maxN=0, moved=0, lastTap=0, dragging=false, last=null, zacc=0;

function info(e){
  var t=e.targetTouches, n=t.length, x=0, y=0, d=0, i;
  for(i=0;i<n;i++){ x+=t[i].clientX; y+=t[i].clientY; }
  if(n){ x/=n; y/=n; }
  if(n>=2){ var a=t[0].clientX-t[1].clientX, b=t[0].clientY-t[1].clientY; d=Math.sqrt(a*a+b*b); }
  return {n:n,x:x,y:y,d:d};
}

function inicio(e){
  e.preventDefault();
  var s=info(e);
  if(s.n===1){
    t0=+new Date(); maxN=1; moved=0; zacc=0;
    dragging = (t0-lastTap) < 300;
    if(espelho) absMove(e.targetTouches[0]);
    if(dragging) evs.push("d");
  } else if(s.n>maxN){ maxN=s.n; }
  last=s;
}

function mover(e){
  e.preventDefault();
  var s=info(e);
  if(last && last.n===s.n && s.n>0){
    var dx=s.x-last.x, dy=s.y-last.y;
    moved+=Math.abs(dx)+Math.abs(dy);
    if(s.n===1){
      if(espelho){ absMove(e.targetTouches[0]); }
      else { pdx+=dx*SENS; pdy+=dy*SENS; }
    } else {
      var dd=s.d-last.d;
      if(Math.abs(dd)>Math.abs(dy)*1.5 && Math.abs(dd)>1){
        zacc+=dd;
        while(zacc>=STEP){ pzm++; zacc-=STEP; }
        while(zacc<=-STEP){ pzm--; zacc+=STEP; }
      } else {
        psc += dy*(NATURAL?1:-1)*SENSR;
      }
    }
  }
  last=s;
}

function fim(e){
  e.preventDefault();
  if(e.targetTouches.length===0){
    var dur=(+new Date())-t0;
    if(dragging){ evs.push("u"); dragging=false; }
    else if(moved<12 && dur<300){
      if(maxN===1){ evs.push("c"); lastTap=+new Date(); }
      else if(maxN===2){ evs.push("r"); }
    }
    last=null; zacc=0; maxN=0;
  } else {
    last=info(e);
  }
}

/* ---------------- botoes esquerdo / direito ---------------- */
function ligarBotao(id, dn, up){
  var el=document.getElementById(id), ativo=false;
  function d(e){ e.preventDefault(); if(ativo) return; ativo=true; el.className="mb on"; evs.push(dn); }
  function u(e){ e.preventDefault(); if(!ativo || e.targetTouches.length>0) return; ativo=false; el.className="mb"; evs.push(up); }
  el.addEventListener("touchstart",d,false);
  el.addEventListener("touchend",u,false);
  el.addEventListener("touchcancel",u,false);
}
ligarBotao("bL","d","u");
ligarBotao("bR","rd","ru");

/* ---------------- teclado ---------------- */
var SENT=" ", mods={ctrl:false,alt:false,shift:false};
var ent=document.getElementById("entrada");

function marcar(){
  document.getElementById("bCtrl").className = mods.ctrl ? "on" : "";
  document.getElementById("bAlt").className = mods.alt ? "on" : "";
  document.getElementById("bShift").className = mods.shift ? "on" : "";
  document.getElementById("bTec").className = (document.activeElement===ent) ? "on" : "";
}
function pushTexto(s){
  var l=kbq[kbq.length-1];
  if(l && l.t!==undefined) l.t+=s; else kbq.push({t:s});
}
function pushTecla(nome){
  var m=[]; if(mods.ctrl) m.push("ctrl"); if(mods.alt) m.push("alt"); if(mods.shift) m.push("shift"); m.push(nome);
  kbq.push({k:m.join("+")});
  mods.ctrl=false; mods.alt=false; mods.shift=false; marcar();
}
function temMods(){ return mods.ctrl || mods.alt || mods.shift; }

/* O campo invisivel sempre guarda um espaco "sentinela". Se o valor ficar vazio,
   foi um Backspace; se tiver mais coisa depois do espaco, e texto digitado. */
ent.addEventListener("input", function(){
  var v=ent.value;
  if(v.length===0){ pushTecla("back"); }
  else {
    var s = (v.charAt(0)===SENT) ? v.substring(1) : v, i, c;
    for(i=0;i<s.length;i++){
      c=s.charAt(i);
      if(c==="\\n" || c==="\\r"){ pushTecla("enter"); }
      else if(temMods()){ pushTecla(c.toLowerCase()); }
      else { pushTexto(c); }
    }
  }
  ent.value=SENT;
}, false);
ent.addEventListener("focus", marcar, false);
ent.addEventListener("blur", marcar, false);

function botao(id, fn){ document.getElementById(id).addEventListener("click", fn, false); }
botao("bTec", function(){
  if(document.activeElement===ent){ ent.blur(); }
  else { ent.value=SENT; ent.focus(); }
  marcar();
});
botao("bEsc", function(){ pushTecla("esc"); });
botao("bTab", function(){ pushTecla("tab"); });
botao("bDel", function(){ pushTecla("del"); });
botao("bEnt", function(){ pushTecla("enter"); });
botao("bEsq", function(){ pushTecla("left"); });
botao("bCima", function(){ pushTecla("up"); });
botao("bBaixo", function(){ pushTecla("down"); });
botao("bDir", function(){ pushTecla("right"); });
botao("bCtrl", function(){ mods.ctrl=!mods.ctrl; marcar(); });
botao("bAlt", function(){ mods.alt=!mods.alt; marcar(); });
botao("bCop", function(){ kbq.push({k:"ctrl+c"}); });
botao("bCol", function(){ kbq.push({k:"ctrl+v"}); });
botao("bShift", function(){ mods.shift=!mods.shift; marcar(); });

var extras=document.getElementById("extra").getElementsByTagName("button");
for(var xi=0; xi<extras.length; xi++){
  (function(b){
    var k=b.getAttribute("data-k");
    if(k) b.addEventListener("click", function(){ pushTecla(k); }, false);
  })(extras[xi]);
}
botao("bExt", function(){
  var ex=document.getElementById("extra");
  var abrir = ex.style.display!=="block";
  ex.style.display = abrir ? "block" : "none";
  document.getElementById("bExt").className = abrir ? "on" : "";
});

/* ---------------- espelho da tela ---------------- */
var cv=document.getElementById("tela"), cx=cv.getContext("2d"), buf=new Image();
var barra=document.getElementById("barra"), mini=document.getElementById("mini");

function absMove(t){
  var r=cv.getBoundingClientRect();
  if(!r.width || !r.height) return;
  var fx=(t.clientX-r.left)/r.width, fy=(t.clientY-r.top)/r.height;
  pax=Math.round(Math.max(0,Math.min(1,fx))*10000);
  pay=Math.round(Math.max(0,Math.min(1,fy))*10000);
}

function pedir(){
  if(!espelho){ rodando=false; return; }
  rodando=true;
  buf.onload=function(){
    if(cv.width!==buf.naturalWidth || cv.height!==buf.naturalHeight){
      cv.width=buf.naturalWidth; cv.height=buf.naturalHeight;
      cv.style.width=buf.naturalWidth+"px"; cv.style.height=buf.naturalHeight+"px";
    }
    cx.drawImage(buf,0,0);
    setTimeout(pedir,25);
  };
  buf.onerror=function(){ estado.textContent="sem imagem (veja o console do PC)"; setTimeout(pedir,1500); };
  buf.src="/f?k="+K+"&mon="+mon+"&w="+window.innerWidth+"&h="+window.innerHeight+"&t="+(+new Date());
}

/* Descobre quantos monitores o PC tem; o botao "Tela" alterna entre eles. */
var bTela=document.getElementById("bTela");
function rotulo(){ bTela.textContent = "Tela " + (mon||1) + (nmon>1 ? "/"+nmon : ""); }
(function(){
  var x=new XMLHttpRequest();
  x.open("GET","/i?k="+K,true);
  x.onreadystatechange=function(){
    if(x.readyState===4 && x.status===200){
      try{
        var d=JSON.parse(x.responseText);
        nmon=d.monitores.length; mon=d.padrao; if(mon>nmon) mon=1;
        rotulo();
      }catch(err){}
    }
  };
  x.send();
})();
bTela.addEventListener("click", function(){ mon=((mon||1) % nmon)+1; rotulo(); }, false);

botao("bEsp", function(){
  espelho=!espelho;
  cv.style.display = espelho ? "block" : "none";
  document.getElementById("dica").style.display = espelho ? "none" : "block";
  document.getElementById("bEsp").className = espelho ? "on" : "";
  document.getElementById("btns").className = espelho ? "esp" : "";
  if(espelho && !rodando) pedir();
});
var btns=document.getElementById("btns");
botao("bOcul", function(){ barra.style.display="none"; btns.style.display="none"; mini.style.display="block"; });
mini.addEventListener("click", function(){ barra.style.display="block"; btns.style.display="flex"; mini.style.display="none"; }, false);

var pad=document.getElementById("pad");
pad.addEventListener("touchstart",inicio,false);
pad.addEventListener("touchmove",mover,false);
pad.addEventListener("touchend",fim,false);
pad.addEventListener("touchcancel",fim,false);
document.addEventListener("touchmove",function(e){e.preventDefault();},false);
document.addEventListener("gesturestart",function(e){e.preventDefault();},false);
</script></body></html>
"""


def montar_pagina(token):
    return (PAGINA
            .replace("__TOKEN__", token)
            .replace("__SENSR__", str(SENS_ROLAGEM))
            .replace("__SENS__", str(SENSIBILIDADE))
            .replace("__NAT__", "true" if ROLAGEM_NATURAL else "false")
            .replace("__STEP__", str(PASSO_ZOOM))).encode("utf-8")


def carregar_token():
    """Mantem o mesmo codigo entre execucoes, para o favorito do iPad continuar valendo."""
    try:
        with open(ARQ_TOKEN, "r") as f:
            t = f.read().strip()
            if t:
                return t
    except OSError:
        pass
    t = secrets.token_urlsafe(9)
    try:
        with open(ARQ_TOKEN, "w") as f:
            f.write(t)
    except OSError:
        pass
    return t


TOKEN = carregar_token()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _enviar(self, codigo, corpo=b"", tipo="text/plain; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        k = q.get("k", [""])[0]
        if not secrets.compare_digest(k.encode("utf-8"), TOKEN.encode("utf-8")):
            return self._enviar(403, b"acesso negado")
        if u.path == "/":
            return self._enviar(200, montar_pagina(TOKEN), "text/html; charset=utf-8")
        if u.path == "/m":
            aplicar(q)
            return self._enviar(200, b"ok")
        if u.path == "/i":
            info = {"monitores": [[m[2], m[3]] for m in listar_monitores()],
                    "padrao": TELA if isinstance(TELA, int) else 1}
            return self._enviar(200, json.dumps(info).encode("utf-8"), "application/json")
        if u.path == "/f":
            if not TEM_PIL:
                return self._enviar(501, b"instale o Pillow: python -m pip install pillow")
            try:
                dados = quadro(max(200, inteiro(q, "w", 3000)), max(200, inteiro(q, "h", 3000)),
                               inteiro(q, "mon", 20) or None)
            except Exception as erro:
                print("Erro ao capturar a tela: %r" % (erro,))
                return self._enviar(500, str(erro).encode("utf-8", "ignore"))
            return self._enviar(200, dados, "image/jpeg")
        self._enviar(404, b"")


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


def main():
    try:
        servidor = ThreadingHTTPServer(("0.0.0.0", PORTA), Handler)
    except OSError as e:
        print("Nao consegui abrir a porta %d: %s" % (PORTA, e))
        sys.exit(1)
    print("=" * 60)
    print(" Trackpad do iPad no ar")
    print(" No Safari do iPad (mesma rede Wi-Fi), abra:")
    print()
    print("     http://%s:%d/?k=%s" % (ip_local(), PORTA, TOKEN))
    print()
    print(" Esse endereco e o 'senha': nao compartilhe com ninguem.")
    print(" Para parar: Ctrl+C")
    print(" Espelho da tela: " + ("disponivel" if TEM_PIL
          else "INDISPONIVEL. Rode: python -m pip install pillow mss"))
    if TEM_PIL and not TEM_MSS:
        print(" Aviso: 'mss' nao instalado; monitores extras podem ficar pretos.")
        print("        Rode: python -m pip install mss")
    for i, m in enumerate(listar_monitores(), 1):
        print("   monitor %d: %dx%d  (posicao %d,%d)%s"
              % (i, m[2], m[3], m[0], m[1], "  (principal)" if i == 1 else ""))
    print("=" * 60)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()