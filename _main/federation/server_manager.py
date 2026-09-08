"""Desktop interface for an expandable list of Moodle HTTP(S) servers."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import uuid

from moodle_check import CheckResult, check_moodle, load_addresses, save_addresses

ROOT = Path(__file__).resolve().parent
ADDRESS_FILE = ROOT / 'servers.local.json'


class CheckWorkers:
    def __init__(self):
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.closed = threading.Event()
        for number in range(6):
            threading.Thread(target=self.run, name=f'moodle-check-{number}', daemon=True).start()

    def run(self):
        while not self.closed.is_set():
            try:
                row_id, generation, address = self.jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                result = check_moodle(address)
            except Exception:
                result = CheckResult('unreachable', 'Не удалось выполнить проверку.', address)
            self.results.put((row_id, generation, result))
            self.jobs.task_done()


class ServerRow:
    def __init__(self, app, address):
        self.app = app
        self.id = uuid.uuid4().hex
        self.generation = 0
        self.busy = False
        self.frame = ttk.Frame(app.rows_frame, padding=(12, 10), style='Card.TFrame')
        self.frame.pack(fill='x', padx=4, pady=5)
        self.frame.columnconfigure(1, weight=1)
        self.number = ttk.Label(self.frame, width=4, style='Card.TLabel')
        self.number.grid(row=0, column=0, sticky='w')
        self.address = tk.StringVar(value=address)
        self.entry = ttk.Entry(self.frame, textvariable=self.address, font=('Segoe UI', 11))
        self.entry.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        self.entry.bind('<Return>', lambda event: app.check(self))
        self.check_button = ttk.Button(self.frame, text='Проверить', command=lambda: app.check(self))
        self.check_button.grid(row=0, column=2, padx=(0, 8))
        ttk.Button(self.frame, text='Удалить', command=lambda: app.remove(self)).grid(row=0, column=3)
        self.status = ttk.Label(self.frame, text='Не проверен', style='Card.TLabel')
        self.status.grid(row=1, column=1, columnspan=3, sticky='w', pady=(7, 0))
        self.detail = ttk.Label(self.frame, text='', style='Card.TLabel', foreground='#64748b')
        self.detail.grid(row=2, column=1, columnspan=3, sticky='w', pady=(3, 0))
        self.address.trace_add('write', self.changed)

    def changed(self, *_):
        self.generation += 1
        self.busy = False
        self.check_button.state(['!disabled'])
        self.status.configure(text='Адрес изменён — требуется проверка', foreground='#64748b')
        self.detail.configure(text='')
        self.app.summary.set('Есть изменения. Сохраните список, чтобы открыть его в следующий раз.')


class ServerManager:
    def __init__(self, root, storage=ADDRESS_FILE, workers=None):
        self.root = root
        self.storage = storage
        self.workers = workers or CheckWorkers()
        self.rows = {}
        self.closed = False
        root.title('Moodle — серверы сети')
        root.geometry('1040x640')
        root.minsize(800, 420)
        style = ttk.Style(root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('TFrame', background='#f1f5f9')
        style.configure('TLabel', background='#f1f5f9', foreground='#0f172a')
        style.configure('Card.TFrame', background='white')
        style.configure('Card.TLabel', background='white')
        style.configure('TButton', padding=(12, 7))
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Серверы Moodle', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
        ttk.Label(outer, text='Введите IP или HTTP(S)-адрес. Добавляйте столько серверов, сколько нужно.').pack(anchor='w', pady=(6, 4))
        ttk.Label(outer, text='Например: 192.168.1.50  •  http://10.40.0.10:8080  •  https://moodle.example/learning',
                  foreground='#64748b').pack(anchor='w')
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill='x', pady=16)
        self.add_button = ttk.Button(toolbar, text='+ Добавить сервер', command=lambda: self.add('', focus=True))
        self.add_button.pack(side='left')
        self.check_all_button = ttk.Button(toolbar, text='Проверить все', command=self.check_all)
        self.check_all_button.pack(side='left', padx=8)
        ttk.Button(toolbar, text='Сохранить список', command=self.save).pack(side='left')
        self.count = ttk.Label(toolbar)
        self.count.pack(side='right')
        container = ttk.Frame(outer)
        container.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(container, highlightthickness=0, background='#f1f5f9')
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.rows_frame = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor='nw')
        self.rows_frame.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.resize_rows(event.width, window))
        root.bind('<MouseWheel>', self.scroll)
        root.bind('<Button-4>', lambda event: self.canvas.yview_scroll(-1, 'units'))
        root.bind('<Button-5>', lambda event: self.canvas.yview_scroll(1, 'units'))
        self.summary = tk.StringVar(value='Готово к проверке. Проверяется доступность с этого компьютера.')
        ttk.Label(outer, textvariable=self.summary, wraplength=960).pack(fill='x', pady=(12, 4))
        ttk.Label(outer, text='Признаки Moodle не подтверждают исправность входа или точную версию. Проверка не меняет настройки серверов.',
                  foreground='#64748b', wraplength=960).pack(fill='x')
        try:
            addresses = load_addresses(storage)
        except (OSError, ValueError) as exc:
            addresses = []
            self.summary.set(f'Не удалось прочитать список: {exc}. Файл не изменён.')
        for address in addresses or ['']:
            self.add(address)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = root.after(100, self.poll)

    def resize_rows(self, width, window):
        self.canvas.itemconfigure(window, width=width)
        for row in self.rows.values():
            row.status.configure(wraplength=max(400, width - 90))
            row.detail.configure(wraplength=max(400, width - 90))

    def scroll(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

    def add(self, address='', focus=False):
        row = ServerRow(self, address)
        self.rows[row.id] = row
        self.renumber()
        if focus:
            self.root.update_idletasks()
            self.canvas.yview_moveto(1)
            row.entry.focus_set()
            self.summary.set('Строка добавлена. Введите адрес сервера.')
        return row

    def remove(self, row):
        self.rows.pop(row.id, None)
        row.frame.destroy()
        self.renumber()
        self.summary.set('Строка удалена. Нажмите «Сохранить список», чтобы сохранить изменения.')

    def renumber(self):
        for number, row in enumerate(self.rows.values(), 1):
            row.number.configure(text=f'{number}.')
        self.count.configure(text=f'Серверов: {len(self.rows)}')

    def check(self, row):
        if row.busy:
            return
        row.generation += 1
        row.busy = True
        row.check_button.state(['disabled'])
        row.status.configure(text='Проверка… (до 6 одновременно)', foreground='#2563eb')
        row.detail.configure(text='')
        self.workers.jobs.put((row.id, row.generation, row.address.get()))
        self.summary.set('Проверки идут в фоне. Можно добавлять и редактировать строки.')

    def check_all(self):
        for row in self.rows.values():
            if row.address.get().strip():
                self.check(row)

    def poll(self):
        while True:
            try:
                row_id, generation, result = self.workers.results.get_nowait()
            except queue.Empty:
                break
            row = self.rows.get(row_id)
            # Edited and deleted rows must never receive stale network results.
            if row is None or row.generation != generation:
                continue
            row.busy = False
            row.check_button.state(['!disabled'])
            color = '#15803d' if result.kind == 'moodle' else '#a16207' if result.kind in ('unknown', 'restricted') else '#b91c1c'
            row.status.configure(text=result.message, foreground=color)
            row.detail.configure(text=f'{result.url}  •  {result.elapsed_ms} мс')
            pending = sum(item.busy for item in self.rows.values())
            self.summary.set(f'Ожидают результата: {pending}' if pending else 'Проверки завершены. Список можно сохранить.')
        if not self.closed:
            self.poll_id = self.root.after(100, self.poll)

    def save(self):
        try:
            count = save_addresses(self.storage, [row.address.get() for row in self.rows.values()])
        except (OSError, ValueError) as exc:
            messagebox.showerror('Список не сохранён', str(exc), parent=self.root)
            return
        self.summary.set(f'Сохранено серверов: {count}. Файл: {self.storage.name}')

    def close(self):
        self.closed = True
        self.workers.closed.set()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def main():
    root = tk.Tk()
    ServerManager(root)
    root.mainloop()


if __name__ == '__main__':
    main()
