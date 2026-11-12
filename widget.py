import ctypes
import datetime
import queue
import threading
import time
import tkinter as tk
import webbrowser
from ctypes import wintypes
from tkinter import messagebox

from quota import login, login_status, read_limits, windows

REFRESH_SECONDS = 60
WIDTH = 220
ROW_HEIGHT = 23
EDGE_GAP = 24
PEEK = 6
BACKGROUND = '#101920'
MUTED = '#8499a2'


class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


def monitor_bounds(x, y):
    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    monitor = user32.MonitorFromPoint(POINT(x, y), 2)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError()
    rect = info.rcMonitor
    return rect.left, rect.top, rect.right, rect.bottom


def nearest_edge(x, y, width, height, bounds):
    left, top, right, bottom = bounds
    distances = {'left': max(0, x-left), 'right': max(0, right-x-width),
                 'top': max(0, y-top), 'bottom': max(0, bottom-y-height)}
    edge = min(distances, key=distances.get)
    return edge if distances[edge] <= EDGE_GAP else None


def segment_color(index, count):
    t = index / max(1, count - 1)
    colors = [(255, 83, 112), (255, 177, 66), (242, 224, 89),
              (79, 218, 165), (78, 170, 245), (169, 111, 239)]
    position = t * (len(colors) - 1)
    i = min(int(position), len(colors) - 2)
    return '#%02x%02x%02x' % tuple(
        round(a + (b-a) * (position-i)) for a, b in zip(colors[i], colors[i+1]))


class Widget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Codex 限额')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.9)
        self.root.geometry('+100+100')
        self.root.configure(bg=BACKGROUND)
        self.messages = queue.Queue()
        self.loading = False
        self.login_prompted = False
        self.logging_in = False
        self.next_refresh = None
        self.rows = []
        self.status = '正在读取…'
        self.drag = None
        self.drag_start = None
        self.edge = None
        self.bounds = None
        self.collapsed = False
        self.last_inside = time.monotonic()
        self.menu_open = False
        self.animation = None

        self.canvas = tk.Canvas(self.root, width=WIDTH, height=70, bg=BACKGROUND,
                                highlightthickness=0, cursor='fleur')
        self.canvas.pack()
        self.menu = tk.Menu(self.root, tearoff=False)
        opacity = tk.Menu(self.menu, tearoff=False)
        self.opacity = tk.IntVar(value=90)
        for percent in (40, 50, 60, 70, 80, 90, 100):
            opacity.add_radiobutton(label=f'{percent}%', variable=self.opacity, value=percent,
                                    command=self.set_opacity)
        self.opacity_menu = opacity
        self.canvas.bind('<ButtonPress-1>', self.start_drag)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.end_drag)
        self.canvas.bind('<Button-3>', self.show_menu)
        self.canvas.tag_bind('chatgpt_link', '<Enter>', lambda event: self.canvas.config(cursor='hand2'))
        self.canvas.tag_bind('chatgpt_link', '<Leave>', lambda event: self.canvas.config(cursor='fleur'))
        self.draw()
        self.refresh()
        self.root.after(200, self.check_messages)
        self.root.after(150, self.check_edge)

    def set_opacity(self):
        self.root.attributes('-alpha', self.opacity.get() / 100)

    def position(self, x, y):
        # Tk interprets negative geometry as a right/bottom offset; use screen coordinates.
        user32 = ctypes.windll.user32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, 0x0015)

    def start_drag(self, event):
        if self.animation is not None:
            self.root.after_cancel(self.animation)
            self.animation = None
        self.drag = (event.x_root - self.root.winfo_rootx(), event.y_root - self.root.winfo_rooty())
        self.drag_start = (event.x_root, event.y_root, event.x, event.y)

    def move(self, event):
        if self.drag:
            if (self.drag_start and abs(event.x_root - self.drag_start[0]) < 4
                    and abs(event.y_root - self.drag_start[1]) < 4):
                return
            self.edge = None
            self.collapsed = False
            self.position(event.x_root - self.drag[0], event.y_root - self.drag[1])

    def end_drag(self, event):
        self.drag = None
        if self.drag_start:
            start_x, start_y, local_x, local_y = self.drag_start
            self.drag_start = None
            if (21 <= local_x <= 70 and 0 <= local_y <= 24
                    and abs(event.x_root - start_x) < 4 and abs(event.y_root - start_y) < 4):
                webbrowser.open('https://chatgpt.com/')
                return
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        width, height = self.root.winfo_width(), self.root.winfo_height()
        self.bounds = monitor_bounds(event.x_root, event.y_root)
        self.edge = nearest_edge(x, y, width, height, self.bounds)
        if self.edge:
            self.snap(False)
            self.last_inside = time.monotonic()

    def snap(self, collapse):
        if not self.edge or not self.bounds:
            return
        left, top, right, bottom = self.bounds
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        width, height = self.root.winfo_width(), self.root.winfo_height()
        if self.edge == 'left':
            x = left - width + PEEK if collapse else left
            y = max(top, min(y, bottom-height))
        elif self.edge == 'right':
            x = right - PEEK if collapse else right - width
            y = max(top, min(y, bottom-height))
        elif self.edge == 'top':
            y = top - height + PEEK if collapse else top
            x = max(left, min(x, right-width))
        else:
            y = bottom - PEEK if collapse else bottom-height
            x = max(left, min(x, right-width))
        if self.animation is not None:
            self.root.after_cancel(self.animation)
        start_x, start_y = self.root.winfo_rootx(), self.root.winfo_rooty()
        started = time.monotonic()
        self.collapsed = collapse

        def animate():
            progress = min(1, (time.monotonic() - started) / 0.22)
            eased = 1 - (1 - progress) ** 3
            self.position(start_x + (x-start_x)*eased, start_y + (y-start_y)*eased)
            self.animation = self.root.after(16, animate) if progress < 1 else None

        animate()

    def check_edge(self):
        if self.edge and not self.drag and not self.menu_open:
            px, py = self.root.winfo_pointerxy()
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            inside = x <= px < x+self.root.winfo_width() and y <= py < y+self.root.winfo_height()
            if inside:
                self.last_inside = time.monotonic()
                if self.collapsed:
                    self.snap(False)
            elif not self.collapsed and time.monotonic()-self.last_inside > 0.8:
                self.snap(True)
        self.root.after(150, self.check_edge)

    def show_menu(self, event):
        self.menu_open = True
        self.menu.delete(0, 'end')
        for label, window in self.rows:
            mins = window.get('windowDurationMins')
            reset = window.get('resetsAt')
            reset_text = datetime.datetime.fromtimestamp(reset).strftime('%m-%d %H:%M') if reset else '未知'
            self.menu.add_command(label=f'{label} · {mins or "?"}分钟  重置 {reset_text}', state='disabled')
        if self.rows:
            self.menu.add_separator()
        self.menu.add_command(label='立即刷新', command=self.refresh)
        self.menu.add_command(label='登录 ChatGPT', command=self.start_login)
        self.menu.add_cascade(label='不透明度', menu=self.opacity_menu)
        self.menu.add_separator()
        self.menu.add_command(label='退出', command=self.root.destroy)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
            self.menu_open = False
            self.last_inside = time.monotonic()

    def draw(self):
        canvas = self.canvas
        canvas.delete('all')
        height = 27 + max(1, len(self.rows)) * ROW_HEIGHT
        canvas.config(height=height)
        self.root.update_idletasks()
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        region = gdi32.CreateRoundRectRgn(0, 0, WIDTH + 1, height + 1, 14, 14)
        if not user32.SetWindowRgn(hwnd, region, True):
            gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
            gdi32.DeleteObject(region)
        canvas.create_polygon(0, 7, 0, height-7, 7, height-1, WIDTH-7, height-1,
                              WIDTH-1, height-7, WIDTH-1, 7, WIDTH-7, 0, 7, 0,
                              smooth=True, fill='', outline='#30454a')
        canvas.create_oval(9, 9, 15, 15, fill='#70e1be', outline='')
        canvas.create_text(21, 12, text='CODEX', fill='#e6f3f0', font=('Segoe UI', 9, 'bold'),
                           anchor='w', tags='chatgpt_link')
        canvas.create_text(WIDTH-9, 12, text=self.status, fill=MUTED, font=('Microsoft YaHei UI', 7), anchor='e')
        for index, (label, window) in enumerate(self.rows):
            y = 29 + index * ROW_HEIGHT
            remaining = max(0, min(100, 100 - window['usedPercent']))
            mins = window.get('windowDurationMins')
            duration = f'{mins // 60}h' if mins and mins % 60 == 0 else f'{mins}m' if mins else '?'
            canvas.create_text(10, y+5, text=duration, fill='#b4c8c7', font=('Segoe UI', 8), anchor='w')
            count = 20
            active = round(remaining * count / 100)
            for cell in range(count):
                x = 46 + cell * 6
                color = segment_color(cell, count) if cell < active else '#263a3c'
                canvas.create_line(x+2, y+2, x+2, y+8, fill=color, width=4, capstyle='round')
            canvas.create_text(WIDTH-9, y+5, text=f'{remaining:g}%', fill='#d7eee3',
                               font=('Segoe UI', 9, 'bold'), anchor='e')

    def refresh(self):
        if self.loading or self.logging_in:
            return
        if self.next_refresh is not None:
            self.root.after_cancel(self.next_refresh)
            self.next_refresh = None
        self.loading = True
        self.status = '更新中'
        self.draw()

        def worker():
            try:
                if not login_status():
                    self.messages.put(('needs_login', None))
                else:
                    self.messages.put(('result', read_limits()))
            except Exception as exc:
                self.messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start_login(self):
        if self.logging_in:
            return
        self.logging_in = True
        self.status = '等待浏览器登录'
        self.draw()

        def worker():
            try:
                login()
                self.messages.put(('login_complete', None))
            except Exception as exc:
                self.messages.put(('login_error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def check_messages(self):
        try:
            kind, value = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.loading = False
            if kind == 'needs_login':
                self.status = '请登录 ChatGPT'
                if not self.login_prompted:
                    self.login_prompted = True
                    if messagebox.askyesno('登录 ChatGPT', '首次使用需要在浏览器登录 ChatGPT。现在登录吗？', parent=self.root):
                        self.start_login()
            elif kind == 'login_complete':
                self.logging_in = False
                self.refresh()
                self.root.after(200, self.check_messages)
                return
            elif kind == 'login_error':
                self.logging_in = False
                self.status = '登录失败，请右键重试'
            elif kind == 'error':
                self.status = '更新失败'
            else:
                self.rows = windows(value)
                self.status = (datetime.datetime.now().strftime('%H:%M') if self.rows else '没有限额数据')
            self.draw()
            self.root.update_idletasks()
            if self.edge:
                self.snap(self.collapsed)
            self.next_refresh = self.root.after(REFRESH_SECONDS * 1000, self.refresh)
        self.root.after(200, self.check_messages)


if __name__ == '__main__':
    Widget().root.mainloop()

