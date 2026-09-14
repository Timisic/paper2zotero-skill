"""Windows account setup with native text fields and asynchronous checks."""
from __future__ import annotations

import argparse
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

import agent_installation
import configure
import setup_connection as connection

TITLE = '论文工具配置 · Windows 图形向导 v2'
AGENTS = {'Claude Code': 'claude-code', 'Codex': 'codex', 'Pi': 'pi'}
PAGES = ('准备工具', '连接 Zotero', '启用全文阅读', '检查结果')


class Wizard:
    def __init__(self, root: tk.Tk, *, agent='auto', demo=False, group=False, ready_file=None):
        self.root, self.demo, self.group = root, demo, group
        self.agent = agent
        self.page = 0
        self.busy = False
        self.work = queue.Queue()
        self.ready_file = ready_file
        self.prepared = False
        self.connected = set()
        self.controls = []
        self.root.title(TITLE + (' · 演示' if demo else ''))
        self.root.geometry('880x690')
        self.root.minsize(780, 660)
        self.root.configure(bg='#f4f6fa')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 11), background='#f4f6fa')
        style.configure('TButton', padding=(14, 9))
        style.configure('Primary.TButton', background='#2459ce', foreground='white')
        style.map('Primary.TButton', background=[('disabled', '#b6c2dc'), ('active', '#1748b5')])
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 21, 'bold'), foreground='#18243a')
        style.configure('Muted.TLabel', foreground='#58677e')
        style.configure('TEntry', padding=9)
        outer = ttk.Frame(root, padding=28)
        outer.pack(fill='both', expand=True)
        self.step = ttk.Label(outer, style='Muted.TLabel')
        self.step.pack(anchor='w')
        self.heading = ttk.Label(outer, style='Title.TLabel')
        self.heading.pack(anchor='w', pady=(8, 15))
        self.body = ttk.Frame(outer)
        self.body.pack(fill='both', expand=True)
        self.progress = ttk.Progressbar(outer, mode='indeterminate')
        self.progress.pack(fill='x', pady=(10, 5))
        self.status = tk.StringVar()
        self.status_label = ttk.Label(outer, textvariable=self.status, wraplength=790, foreground='#2459ce')
        self.status_label.pack(fill='x', pady=(5, 12))
        self.footer = ttk.Frame(outer)
        self.footer.pack(fill='x')
        self.root.after(100, self.poll)
        self.render()
        self.root.after_idle(self.ready)

    def ready(self):
        if self.ready_file:
            Path(self.ready_file).write_text('ready\n', encoding='utf-8')

    def label(self, text, **kw):
        item = ttk.Label(self.body, text=text, wraplength=790, **kw)
        item.pack(anchor='w', pady=(0, 12))
        return item

    def button(self, parent, text, command, primary=False):
        widget = ttk.Button(parent, text=text, command=command,
                            style='Primary.TButton' if primary else 'TButton')
        self.controls.append(widget)
        return widget

    def render(self):
        for frame in (self.body, self.footer):
            for child in frame.winfo_children():
                child.destroy()
        self.controls = []
        self.status.set('演示模式：不会连接服务、安装工具或保存授权码。' if self.demo else '')
        self.step.configure(text='  →  '.join(f'{i + 1}. {name}' for i, name in enumerate(PAGES)))
        self.heading.configure(text=f'{self.page + 1}/4  {PAGES[self.page]}')
        if self.page == 0:
            self.label('配置一次，以后直接让 AI 帮你找论文、整理阅读笔记。')
            self.label('选择你使用的 AI 助手。接下来只需要复制网页上的授权码，无需输入命令或查找个人文库 ID。', style='Muted.TLabel')
            names = dict(AGENTS)
            if self.agent == 'all':
                names['全部助手'] = 'all'
            selected = next((label for label, value in names.items() if value == self.agent), '')
            if not selected:
                detected = agent_installation.selected_roots('auto') if not self.demo else []
                matches = [label for label, value in names.items()
                           if agent_installation.agent_roots().get(value) in detected]
                selected = matches[0] if len(matches) == 1 else ''
            self.agent_choice = ttk.Combobox(self.body, values=list(names), state='readonly', width=27)
            self.agent_choice.set(selected)
            self.agent_choice.pack(anchor='w', pady=(5, 20))
            self.controls.append(self.agent_choice)
            self.label('授权码只保存在本机。输入默认隐藏，验证成功后才保存。你可以随时关闭窗口，之后继续。', style='Muted.TLabel')
            def prepare():
                chosen = names.get(self.agent_choice.get())
                if not chosen:
                    self.status.set('请先选择你使用的 AI 助手。')
                    return
                self.agent = chosen
                self.run(lambda: None if self.demo else connection.prepare(chosen), self.prepared_next,
                         '正在准备工具和安装文件，请稍候……')
            self.button(self.footer, '开始配置', prepare, True).pack(side='right')
        elif self.page in (1, 2):
            self.account_page('zotero' if self.page == 1 else 'mineru')
        else:
            self.result_page()
        if self.page:
            self.button(self.footer, '上一步', lambda: self.goto(self.page - 1)).pack(side='left')

    def prepared_next(self, _):
        self.prepared = True
        self.goto(1)

    def goto(self, page):
        if not self.busy:
            self.page = page
            self.render()

    def account_page(self, service):
        zotero = service == 'zotero'
        url = 'https://www.zotero.org/settings/keys' if zotero else 'https://mineru.net/apiManage/token'
        self.label('Zotero 用来保存论文和笔记。' if zotero else 'MinerU 将 PDF 转成便于阅读的文字。配置时不会上传论文。')
        self.label('① 打开网页，登录后创建授权码。' +
                   (' 请勾选 Library access、Notes access 和 Write access。' if zotero else ' 在 API 管理页面创建 Token。'))
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=(0, 10))
        self.button(row, '打开授权页面', lambda: self.open_page(url)).pack(side='left')
        link = ttk.Entry(row, width=49)
        link.insert(0, url)
        link.configure(state='readonly')
        link.pack(side='left', fill='x', expand=True, padx=(12, 0))
        self.label('② 复制完整授权码，点击“粘贴”或在输入框按 Ctrl+V。')
        self.key = tk.StringVar()
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=(0, 6))
        entry = ttk.Entry(row, textvariable=self.key, show='●', width=45)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda _: self.verify(service))
        self.controls.append(entry)
        self.button(row, '粘贴', self.paste).pack(side='left', padx=(10, 0))
        self.input_note = tk.StringVar(value='尚未输入授权码。')
        ttk.Label(self.body, textvariable=self.input_note, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        self.key.trace_add('write', lambda *_: self.input_note.set(
            '已收到输入，点击“验证并保存”继续。' if self.key.get() else '尚未输入授权码。'))
        if not self.demo and connection.existing_key(service):
            self.input_note.set('已有保存的授权。输入框留空可验证已有授权，粘贴新码可替换。')
        self.group_entry = None
        if zotero and self.group:
            self.label('群组文库 ID（数字）：')
            self.group_entry = ttk.Entry(self.body, width=25)
            self.group_entry.pack(anchor='w')
            self.controls.append(self.group_entry)
        elif zotero:
            self.label('个人文库会自动识别，无需填写文库 ID。', style='Muted.TLabel')
        if self.demo:
            self.button(self.body, '复制示例授权码', self.copy_demo).pack(anchor='w', pady=8)
        self.button(self.footer, '验证并保存' if not self.demo else '模拟验证',
                    lambda: self.verify(service), True).pack(side='right')
        self.button(self.footer, '下一步' if service in self.connected else '暂时跳过',
                    lambda: self.goto(self.page + 1)).pack(side='right', padx=10)
        self.root.after_idle(entry.focus_set)

    def paste(self):
        try:
            self.key.set(self.root.clipboard_get().strip())
            self.status.set('已粘贴。请点击“验证并保存”。')
        except tk.TclError:
            self.status.set('剪贴板里没有文字，请先在网页上复制完整授权码。')

    def copy_demo(self):
        self.root.clipboard_clear()
        self.root.clipboard_append('demo-authorization-for-paste-test')
        self.status.set('示例已复制。现在点击输入框按 Ctrl+V，或点击“粘贴”。')

    def open_page(self, url):
        if self.demo:
            self.status.set('演示模式不打开账号网页。可复制示例授权码体验输入。')
            return
        try:
            connection.open_page(url)
            self.status.set('已请求系统打开浏览器。若没有看到网页，可复制上方网址打开。')
        except (OSError, ValueError):
            self.status.set('浏览器未能打开。请复制上方网址，在浏览器地址栏打开。')

    def verify(self, service):
        if self.busy:
            return
        value = self.key.get()
        if not value and not self.demo:
            value = connection.existing_key(service)
        group_id = self.group_entry.get().strip() if self.group_entry else ''
        def job():
            key = connection.normalize_key(value)
            if self.demo:
                return {'ZOTERO_API_KEY': key, 'ZOTERO_LIBRARY_ID': '12345678', 'ZOTERO_LIBRARY_TYPE': 'user'} if service == 'zotero' else {'MINERU_TOKEN': key}
            return connection.connect(service, key, group_id=group_id, group=self.group)
        def complete(values):
            # Save only after a successful result is accepted by the live UI.
            # Closing the window during a request therefore cannot save later.
            if not self.demo:
                try:
                    configure.save_many(values)
                except Exception:
                    self.status.set('连接成功，但本机保存未完成。请重试；原有配置已保留。')
                    return
            self.connected.add(service)
            self.render()
            prefix = '模拟连接成功（没有保存）' if self.demo else '连接成功，已安全保存'
            self.status.set(prefix + (f'。已自动识别文库 {values["ZOTERO_LIBRARY_ID"]}。点击“下一步”继续。'
                                      if service == 'zotero' else '。点击“下一步”继续。'))
        self.run(job, complete, '正在连接并检查授权，请稍候……')

    def result_page(self):
        self.label('点击检查，确认工具和账号是否已就绪。未完成的项目可以返回对应步骤继续配置。')
        self.results = ttk.Frame(self.body)
        self.results.pack(fill='both', expand=True)
        def complete(report):
            for child in self.results.winfo_children():
                child.destroy()
            for record in report['items']:
                ttk.Label(self.results, text=('✓ ' if record['ok'] else '○ ') + record['name'],
                          foreground='#197247' if record['ok'] else '#9b6515').pack(anchor='w', pady=5)
            self.status.set('检查通过，可以开始使用。' if report['ready'] else '部分项目尚未完成。返回对应步骤继续即可，已保存内容会保留。')
        def check():
            self.run(lambda: {'ready': len(self.connected) == 2, 'items': [
                {'name': '工具与助手（演示）', 'ok': self.prepared},
                {'name': 'Zotero（演示）', 'ok': 'zotero' in self.connected},
                {'name': '全文阅读（演示）', 'ok': 'mineru' in self.connected}]} if self.demo else connection.check(self.agent),
                complete, '正在检查工具和服务，可能需要几十秒……')
        self.button(self.footer, '检查配置', check, True).pack(side='right')
        self.button(self.footer, '完成并关闭', self.root.destroy).pack(side='right', padx=10)
        paths = [] if self.demo else agent_installation.installed_paths(agent=self.agent)
        if paths:
            self.label('如需更换总结要求，可修改：\n' + str(Path(paths[0]) / 'references/paper-summary.md') +
                       '\n保留 “## Save and continue” 及其后的保存说明。', style='Muted.TLabel')

    def run(self, job, complete, message):
        if self.busy:
            return
        self.busy = True
        self.status.set(message)
        self.restore = [(widget, str(widget.cget('state'))) for widget in self.controls]
        for widget, _ in self.restore:
            widget.configure(state='disabled')
        self.progress.start(12)
        def worker():
            try:
                result = job()
                self.work.put((complete, result, None))
            except (Exception, SystemExit) as error:
                message = str(error) if isinstance(error, ValueError) else '操作暂未完成，请重试。已保存的设置会保留。'
                self.work.put((None, None, message))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            complete, result, error = self.work.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            for widget, state in self.restore:
                widget.configure(state=state)
            if error:
                self.status.set(error)
            else:
                complete(result)
        self.root.after(100, self.poll)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent', default='auto', choices=agent_installation.CHOICES)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--group', action='store_true')
    parser.add_argument('--ready-file')
    args = parser.parse_args()
    root = tk.Tk()
    Wizard(root, agent=args.agent, demo=args.demo, group=args.group, ready_file=args.ready_file)
    root.mainloop()


if __name__ == '__main__':
    main()
