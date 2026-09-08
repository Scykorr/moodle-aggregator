"""
Moodle Offline Configurator — GUI for LAN IP / wwwroot and core stack settings.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


APP_TITLE = "Moodle Configurator"
ENV_KEYS = [
    "MOODLE_WWWROOT",
    "MOODLE_HTTP_PORT",
    "MOODLE_SITE_FULLNAME",
    "MOODLE_SITE_SHORTNAME",
    "MOODLE_ADMIN_USER",
    "MOODLE_ADMIN_PASSWORD",
    "MOODLE_ADMIN_EMAIL",
    "MOODLE_LANG",
    "MOODLE_DATABASE_NAME",
    "MOODLE_DATABASE_USER",
    "MOODLE_DATABASE_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
]


def app_base_dir() -> Path:
    """Project root: next to exe (dist/) go up, or configurator/ parent when running as script."""
    if getattr(sys, "frozen", False):
        # MoodleConfigurator.exe expected in project/configurator/dist or project root
        exe_dir = Path(sys.executable).resolve().parent
        for candidate in (exe_dir, exe_dir.parent, exe_dir.parent.parent):
            if (candidate / "docker-compose.yml").exists():
                return candidate
        return exe_dir
    return Path(__file__).resolve().parent.parent


def run_cmd(args: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "Timeout"


def list_local_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # Fallback: UDP trick to find primary outbound interface IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127.") and ip not in ips:
            ips.insert(0, ip)
    except OSError:
        pass
    if not ips:
        ips = ["127.0.0.1"]
    return ips


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


def write_env(path: Path, updates: dict[str, str]) -> None:
    existing_lines: list[str] = []
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()
    else:
        example = path.with_name(".env.example")
        if example.exists():
            existing_lines = example.read_text(encoding="utf-8").splitlines()

    keys_done: set[str] = set()
    out: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                keys_done.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in keys_done:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_wwwroot(host: str, port: str) -> str:
    host = host.strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        base = host
    else:
        base = f"http://{host}"
    # Strip existing port then apply
    base = re.sub(r":\d+$", "", base)
    port = port.strip() or "80"
    if port == "80":
        return base
    return f"{base}:{port}"


class ConfiguratorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x640")
        self.minsize(640, 560)
        self.root_dir = app_base_dir()
        self.env_path = self.root_dir / ".env"
        self._busy = False

        self._build_ui()
        self.reload_from_env()
        self.refresh_status()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Каталог проекта:").grid(row=0, column=0, sticky="w", **pad)
        self.lbl_root = ttk.Label(frm, text=str(self.root_dir), foreground="#333")
        self.lbl_root.grid(row=0, column=1, columnspan=2, sticky="w", **pad)

        ttk.Separator(frm).grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(frm, text="IP / хост (LAN):").grid(row=2, column=0, sticky="w", **pad)
        self.cmb_ip = ttk.Combobox(frm, values=list_local_ips(), width=40)
        self.cmb_ip.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Обновить IP", command=self._refresh_ips).grid(row=2, column=2, **pad)

        ttk.Label(frm, text="HTTP-порт:").grid(row=3, column=0, sticky="w", **pad)
        self.ent_port = ttk.Entry(frm, width=12)
        self.ent_port.grid(row=3, column=1, sticky="w", **pad)

        ttk.Label(frm, text="wwwroot (URL):").grid(row=4, column=0, sticky="w", **pad)
        self.ent_wwwroot = ttk.Entry(frm)
        self.ent_wwwroot.grid(row=4, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Button(frm, text="Собрать URL из IP+порт", command=self._fill_wwwroot).grid(
            row=5, column=1, sticky="w", **pad
        )

        ttk.Separator(frm).grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(frm, text="Полное имя сайта:").grid(row=7, column=0, sticky="w", **pad)
        self.ent_fullname = ttk.Entry(frm)
        self.ent_fullname.grid(row=7, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Label(frm, text="Короткое имя:").grid(row=8, column=0, sticky="w", **pad)
        self.ent_shortname = ttk.Entry(frm)
        self.ent_shortname.grid(row=8, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="Язык (lang):").grid(row=9, column=0, sticky="w", **pad)
        self.ent_lang = ttk.Entry(frm, width=12)
        self.ent_lang.grid(row=9, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Админ (логин):").grid(row=10, column=0, sticky="w", **pad)
        self.ent_admin = ttk.Entry(frm)
        self.ent_admin.grid(row=10, column=1, sticky="ew", **pad)

        ttk.Label(frm, text="Пароль админа:").grid(row=11, column=0, sticky="w", **pad)
        self.ent_admin_pass = ttk.Entry(frm, show="*")
        self.ent_admin_pass.grid(row=11, column=1, sticky="ew", **pad)
        self.var_show_pass = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm, text="Показать", variable=self.var_show_pass, command=self._toggle_pass
        ).grid(row=11, column=2, sticky="w", **pad)

        ttk.Label(frm, text="Email админа:").grid(row=12, column=0, sticky="w", **pad)
        self.ent_email = ttk.Entry(frm)
        self.ent_email.grid(row=12, column=1, columnspan=2, sticky="ew", **pad)

        ttk.Separator(frm).grid(row=13, column=0, columnspan=3, sticky="ew", pady=8)

        btns = ttk.Frame(frm)
        btns.grid(row=14, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Button(btns, text="Применить и перезапустить", command=self.apply_and_restart).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Только сохранить .env", command=self.save_env_only).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Старт", command=lambda: self._compose(["up", "-d"])).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Стоп", command=lambda: self._compose(["stop"])).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Обновить статус", command=self.refresh_status).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Сменить пароль админа", command=self.reset_admin_password).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Label(frm, text="Статус:").grid(row=15, column=0, sticky="nw", **pad)
        self.txt_status = tk.Text(frm, height=12, wrap=tk.WORD)
        self.txt_status.grid(row=15, column=1, columnspan=2, sticky="nsew", **pad)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(15, weight=1)

        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w").pack(
            fill=tk.X, side=tk.BOTTOM
        )

    def _toggle_pass(self) -> None:
        self.ent_admin_pass.configure(show="" if self.var_show_pass.get() else "*")

    def _refresh_ips(self) -> None:
        ips = list_local_ips()
        self.cmb_ip["values"] = ips
        if ips and not self.cmb_ip.get():
            self.cmb_ip.set(ips[0])

    def _fill_wwwroot(self) -> None:
        host = self.cmb_ip.get().strip() or "localhost"
        port = self.ent_port.get().strip() or "80"
        self.ent_wwwroot.delete(0, tk.END)
        self.ent_wwwroot.insert(0, build_wwwroot(host, port))

    def reload_from_env(self) -> None:
        env = parse_env(self.env_path)
        if not env and (self.root_dir / ".env.example").exists():
            env = parse_env(self.root_dir / ".env.example")

        www = env.get("MOODLE_WWWROOT", "http://localhost")
        port = env.get("MOODLE_HTTP_PORT", "80")
        self.ent_port.delete(0, tk.END)
        self.ent_port.insert(0, port)
        self.ent_wwwroot.delete(0, tk.END)
        self.ent_wwwroot.insert(0, www)

        m = re.match(r"https?://([^/:]+)", www)
        if m:
            host = m.group(1)
            ips = list_local_ips()
            if host not in ips:
                ips = [host] + ips
            self.cmb_ip["values"] = ips
            self.cmb_ip.set(host)
        else:
            self._refresh_ips()

        for widget, key, default in [
            (self.ent_fullname, "MOODLE_SITE_FULLNAME", "Moodle LMS"),
            (self.ent_shortname, "MOODLE_SITE_SHORTNAME", "Moodle"),
            (self.ent_lang, "MOODLE_LANG", "ru"),
            (self.ent_admin, "MOODLE_ADMIN_USER", "admin"),
            (self.ent_admin_pass, "MOODLE_ADMIN_PASSWORD", "Admin123!"),
            (self.ent_email, "MOODLE_ADMIN_EMAIL", "admin@example.com"),
        ]:
            widget.delete(0, tk.END)
            widget.insert(0, env.get(key, default))

    def collect_updates(self) -> dict[str, str]:
        www = self.ent_wwwroot.get().strip()
        if not www:
            host = self.cmb_ip.get().strip() or "localhost"
            www = build_wwwroot(host, self.ent_port.get().strip() or "80")
        return {
            "MOODLE_WWWROOT": www.rstrip("/"),
            "MOODLE_HTTP_PORT": self.ent_port.get().strip() or "80",
            "MOODLE_SITE_FULLNAME": self.ent_fullname.get().strip() or "Moodle LMS",
            "MOODLE_SITE_SHORTNAME": self.ent_shortname.get().strip() or "Moodle",
            "MOODLE_LANG": self.ent_lang.get().strip() or "ru",
            "MOODLE_ADMIN_USER": self.ent_admin.get().strip() or "admin",
            "MOODLE_ADMIN_PASSWORD": self.ent_admin_pass.get().strip() or "Admin123!",
            "MOODLE_ADMIN_EMAIL": self.ent_email.get().strip() or "admin@example.com",
        }

    def save_env_only(self) -> None:
        try:
            write_env(self.env_path, self.collect_updates())
            messagebox.showinfo(APP_TITLE, f"Сохранено: {self.env_path}")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, str(exc))

    def _set_log(self, text: str) -> None:
        self.txt_status.delete("1.0", tk.END)
        self.txt_status.insert(tk.END, text)

    def _append_log(self, text: str) -> None:
        self.txt_status.insert(tk.END, text + "\n")
        self.txt_status.see(tk.END)

    def _run_async(self, title: str, fn) -> None:
        if self._busy:
            messagebox.showwarning(APP_TITLE, "Дождитесь завершения текущей операции.")
            return
        self._busy = True
        self.status_var.set(title)

        def worker() -> None:
            try:
                fn()
            finally:
                self._busy = False
                self.after(0, lambda: self.status_var.set("Готово"))

        threading.Thread(target=worker, daemon=True).start()

    def _compose(self, args: list[str], timeout: int = 300) -> None:
        def job() -> None:
            code, out, err = run_cmd(["docker", "compose", *args], self.root_dir, timeout=timeout)
            msg = f"$ docker compose {' '.join(args)}\nexit={code}\n{out}\n{err}"
            self.after(0, lambda: self._set_log(msg))
            self.after(0, self.refresh_status)

        self._run_async("Docker...", job)

    def apply_and_restart(self) -> None:
        updates = self.collect_updates()
        try:
            write_env(self.env_path, updates)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        def job() -> None:
            lines = [f"Saved {self.env_path}", f"wwwroot={updates['MOODLE_WWWROOT']}"]
            # Recreate moodle so env wwwroot is applied; keep volumes
            for args in (
                ["up", "-d", "--force-recreate", "moodle"],
                ["up", "-d"],
            ):
                code, out, err = run_cmd(
                    ["docker", "compose", *args], self.root_dir, timeout=600
                )
                lines.append(f"$ docker compose {' '.join(args)} -> {code}")
                if out:
                    lines.append(out)
                if err:
                    lines.append(err)
                if code != 0:
                    break
            else:
                # Extra: set wwwroot inside running container config.php
                code, out, err = run_cmd(
                    [
                        "docker",
                        "exec",
                        "moodle_app",
                        "php",
                        "-r",
                        (
                            "$f='/var/www/html/config.php';"
                            "$c=file_get_contents($f);"
                            "$c=preg_replace('/\\$CFG->wwwroot\\s*=\\s*[\"\\'].*?[\"\\'];/',"
                            "'$CFG->wwwroot   = ' . var_export(getenv('MOODLE_WWWROOT')?:'http://localhost', true) . ';',$c,1);"
                            "file_put_contents($f,$c); echo 'ok';"
                        ),
                    ],
                    self.root_dir,
                    timeout=60,
                )
                lines.append(f"update config.php -> {code} {out} {err}")
                run_cmd(
                    ["docker", "exec", "moodle_app", "php", "admin/cli/purge_caches.php"],
                    self.root_dir,
                    timeout=120,
                )
            self.after(0, lambda: self._set_log("\n".join(lines)))
            self.after(0, self.refresh_status)
            self.after(
                0,
                lambda: messagebox.showinfo(
                    APP_TITLE,
                    "Параметры применены.\nОткройте URL wwwroot с других ПК в локальной сети.",
                ),
            )

        self._run_async("Применение...", job)

    def reset_admin_password(self) -> None:
        user = self.ent_admin.get().strip() or "admin"
        password = self.ent_admin_pass.get().strip()
        if not password:
            messagebox.showerror(APP_TITLE, "Укажите новый пароль.")
            return

        def job() -> None:
            # Moodle CLI: php admin/cli/reset_password.php --username=... --password=... --ignore-password-policy
            code, out, err = run_cmd(
                [
                    "docker",
                    "exec",
                    "-i",
                    "moodle_app",
                    "php",
                    "admin/cli/reset_password.php",
                    f"--username={user}",
                    f"--password={password}",
                    "--ignore-password-policy",
                ],
                self.root_dir,
                timeout=120,
            )
            msg = f"reset_password exit={code}\n{out}\n{err}"
            self.after(0, lambda: self._set_log(msg))
            if code == 0:
                write_env(self.env_path, {"MOODLE_ADMIN_PASSWORD": password})
                self.after(0, lambda: messagebox.showinfo(APP_TITLE, "Пароль обновлён."))
            else:
                self.after(0, lambda: messagebox.showerror(APP_TITLE, "Не удалось сменить пароль.\nКонтейнер запущен?"))

        self._run_async("Смена пароля...", job)

    def refresh_status(self) -> None:
        def job() -> None:
            parts = [f"Project: {self.root_dir}", f"Env: {self.env_path}"]
            code, out, err = run_cmd(["docker", "compose", "ps"], self.root_dir, timeout=60)
            parts.append("--- docker compose ps ---")
            parts.append(out or err or f"exit {code}")
            code2, out2, err2 = run_cmd(
                ["docker", "inspect", "-f", "{{.State.Status}}", "moodle_app"],
                self.root_dir,
                timeout=30,
            )
            if code2 == 0:
                parts.append(f"moodle_app: {out2}")
            env = parse_env(self.env_path)
            parts.append(f"Current wwwroot: {env.get('MOODLE_WWWROOT', '-')}")
            parts.append(f"Port: {env.get('MOODLE_HTTP_PORT', '80')}")
            self.after(0, lambda: self._set_log("\n".join(parts)))

        self._run_async("Статус...", job)


def main() -> None:
    # Ensure working directory for relative docker compose
    base = app_base_dir()
    os.chdir(base)
    app = ConfiguratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
