"""Windows account setup with native text fields and asynchronous checks."""
from __future__ import annotations

import argparse
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any

import agent_installation
import setup_connection as connection

TITLE = '论文工具配置 · Windows 图形向导 v2'
AGENTS = {'Claude Code': 'claude-code', 'Codex': 'codex', 'Pi': 'pi'}


class Wizard:
    def __init__(self, root: tk.Tk, *, agent='auto', group=None, ready_file=None, advanced=False):
        self.root = root
        self.group, self.saved_group_id = connection.library_target(group)
        self.agent = agent
        self.page = len(self.page_titles()) - 1 if advanced else 0
        self.extra_inputs: dict[str, tk.StringVar] = {}
        self.busy = False
        self.work: queue.Queue[tuple[Any, Any, str | None]] = queue.Queue()
        self.ready_file = ready_file
        self.connected: set[str] = set()
        self.controls: list[tk.Widget] = []
        self.root.title(TITLE)
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
        self.step = ttk.Label(outer, style='Muted.TLabel', wraplength=790)
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

    def basic_services(self) -> tuple[str, ...]:
        if self.group:
            return (*connection.BASIC_SERVICES, 'zotero')
        return connection.BASIC_SERVICES

    def page_titles(self) -> tuple[str, ...]:
        names = tuple(connection.SERVICES[name][0] for name in self.basic_services())
        return ('准备工具', *names, '检查结果', '更多配置')

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
        self.root.unbind('<MouseWheel>')
        self.status.set('')
        titles = self.page_titles()
        basic = self.basic_services()
        self.step.configure(text='  →  '.join(f'{i + 1}. {name}' for i, name in enumerate(titles)))
        self.heading.configure(text='更多配置 · MinerU（可选）' if self.page == len(titles) - 1 else f'{self.page + 1}/{len(titles)}  {titles[self.page]}')
        if self.page == 0:
            self.label('配置一次，以后直接让 AI 帮你找论文、整理阅读笔记。')
            self.label('选择你使用的 AI 助手。接下来只需检查本机 Zotero，无需输入命令或授权码。', style='Muted.TLabel')
            names = dict(AGENTS)
            if self.agent == 'all':
                names['全部助手'] = 'all'
            selected = next((label for label, value in names.items() if value == self.agent), '')
            if not selected:
                detected = agent_installation.selected_roots('auto')
                matches = [label for label, value in names.items()
                           if agent_installation.agent_roots().get(value) in detected]
                selected = matches[0] if len(matches) == 1 else ''
            self.agent_choice = ttk.Combobox(self.body, values=list(names), state='readonly', width=27)
            self.agent_choice.set(selected)
            self.agent_choice.pack(anchor='w', pady=(5, 20))
            self.controls.append(self.agent_choice)
            self.label('你可以随时关闭窗口，之后继续。', style='Muted.TLabel')
            def prepare():
                chosen = names.get(self.agent_choice.get())
                if not chosen:
                    self.status.set('请先选择你使用的 AI 助手。')
                    return
                self.agent = chosen
                self.run(lambda: connection.prepare(chosen), self.prepared_next,
                         '正在准备工具和安装文件，请稍候……')
            self.button(self.footer, '开始配置', prepare, True).pack(side='right')
        elif 1 <= self.page <= len(basic):
            self.account_page(basic[self.page - 1])
        elif self.page == len(titles) - 2:
            self.result_page()
        else:
            self.advanced_page()
        if self.page:
            self.button(self.footer, '上一步', lambda: self.goto(self.page - 1)).pack(side='left')

    def prepared_next(self, _):
        self.goto(1)

    def goto(self, page):
        if not self.busy:
            self.page = page
            self.render()

    def account_page(self, service):
        if not connection.SERVICES[service][2]:
            self.local_page(service)
            return
        zotero = service == 'zotero'
        _, url, _, instructions = connection.SERVICES[service]
        self.label(instructions)
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=(0, 10))
        self.button(row, '打开授权页面', lambda: self.open_page(url)).pack(side='left')
        link = ttk.Entry(row, width=49)
        link.insert(0, url)
        link.configure(state='readonly')
        link.pack(side='left', fill='x', expand=True, padx=(12, 0))
        self.label('复制完整授权码，点击“粘贴”或在输入框按 Ctrl+V。')
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
        if connection.existing_key(service):
            self.input_note.set('已有保存的授权。输入框留空可验证已有授权，粘贴新码可替换。')
        self.group_entry = None
        if zotero and self.group:
            self.label('群组文库 ID（数字）：')
            self.group_entry = ttk.Entry(self.body, width=25)
            self.group_entry.insert(0, self.saved_group_id)
            self.group_entry.pack(anchor='w')
            self.controls.append(self.group_entry)
        elif zotero:
            self.label('个人文库会自动识别，无需填写文库 ID。', style='Muted.TLabel')
        self.button(self.footer, '验证并保存', lambda: self.verify(service), True).pack(side='right')
        self.button(self.footer, '下一步' if service in self.connected else '暂时跳过',
                    lambda: self.goto(self.page + 1)).pack(side='right', padx=10)
        self.root.after_idle(entry.focus_set)

    def local_page(self, service):
        self.label(connection.SERVICES[service][3])

        def complete(values):
            try:
                connection.save_account(values)
            except Exception:
                self.status.set('检查通过，但保存未完成，请重试。')
                return
            self.connected.add(service)
            self.render()
            self.status.set('本机 Zotero 可以写入，已保存。点击“下一步”继续。')

        def check():
            self.run(lambda: connection.accept(service), complete, '正在检查本机 Zotero，请稍候……')

        self.button(self.body, '检查本机 Zotero', check, True).pack(anchor='w', pady=(0, 10))

        def skip():
            self.goto(self.page + 1)
            self.status.set('跳过后，检查结果里这一项仍会待完成。')

        self.button(self.footer, '下一步' if service in self.connected else '暂时跳过', skip).pack(side='right', padx=10)

    def paste(self):
        try:
            self.key.set(self.root.clipboard_get().strip())
            self.status.set('已粘贴。请点击“验证并保存”。')
        except tk.TclError:
            self.status.set('剪贴板里没有文字，请先在网页上复制完整授权码。')

    def open_page(self, url):
        try:
            connection.open_page(url)
            self.status.set('已请求系统打开浏览器。若没有看到网页，可复制上方网址打开。')
        except (OSError, ValueError):
            self.status.set('浏览器未能打开。请复制上方网址，在浏览器地址栏打开。')

    def verify(self, service):
        if self.busy:
            return
        value = self.key.get()
        if not value:
            value = connection.existing_key(service)
        group_id = self.group_entry.get().strip() if self.group_entry else ''
        def job():
            return connection.accept(service, connection.normalize_key(value), group_id=group_id, group=self.group)
        def complete(values):
            # Save only after a successful result is accepted by the live UI.
            # Closing the window during a request therefore cannot save later.
            try:
                connection.save_account(values)
            except Exception:
                self.status.set('连接成功，但本机保存未完成。请重试；原有配置已保留。')
                return
            self.connected.add(service)
            if service == 'zotero' and self.group:
                self.saved_group_id = values['ZOTERO_LIBRARY_ID']
            self.render()
            self.status.set('连接成功，已安全保存' + (f'。已自动识别文库 {values["ZOTERO_LIBRARY_ID"]}。点击“下一步”继续。'
                                      if service == 'zotero' else '。点击“下一步”继续。'))
        self.run(job, complete, '正在连接并检查授权，请稍候……')

    def result_page(self):
        self.label('点击检查，确认工具和账号是否已就绪。未完成的项目可以返回对应步骤继续配置。')
        self.label('PDF 默认用本机 markitdown 转换。有 MinerU Token 或自建 MinerU 服务时，可在更多配置里填写；也可以直接开始使用。', style='Muted.TLabel')
        self.button(self.body, '更多配置（可选）', lambda: self.goto(len(self.page_titles()) - 1)).pack(anchor='w', pady=(0, 10))
        result_frame = ttk.Frame(self.body)
        result_frame.pack(fill='both', expand=True)
        self.results = tk.Text(result_frame, height=7, wrap='word', state='disabled',
                               font=('Microsoft YaHei UI', 10), bg='#f4f6fa', relief='flat')
        scrollbar = ttk.Scrollbar(result_frame, command=self.results.yview)
        scrollbar.pack(side='right', fill='y')
        self.results.configure(yscrollcommand=scrollbar.set)
        self.results.pack(side='left', fill='both', expand=True)
        def complete(report):
            self.results.configure(state='normal')
            self.results.delete('1.0', 'end')
            self.results.tag_configure('ok', foreground='#197247')
            self.results.tag_configure('missing', foreground='#9b6515')
            for record in report['items']:
                line = ('✓ ' if record['ok'] else '○ ') + record['name'] + ('（可选）' if record.get('optional') else '')
                if not record['ok'] and record.get('action'):
                    line += '：' + record['action']
                self.results.insert('end', line + '\n', 'ok' if record['ok'] else 'missing')
            self.results.configure(state='disabled')
            self.status.set('检查通过，可以开始使用。' if report['ready'] else '部分项目尚未完成。返回对应步骤继续即可，已保存内容会保留。')
        def check():
            self.run(lambda: connection.check(self.agent, group=bool(self.group)), complete, '正在检查工具和服务，可能需要几十秒……')
        self.button(self.footer, '检查配置', check, True).pack(side='right')
        self.button(self.footer, '完成并关闭', self.root.destroy).pack(side='right', padx=10)
        paths = agent_installation.installed_paths(agent=self.agent)
        if paths:
            self.label('如需更换总结要求，可修改：\n' + str(Path(paths[0]) / 'references/paper-summary.md') +
                       '\n保留 “## Save and continue” 及其后的保存说明。', style='Muted.TLabel')

    def advanced_page(self):
        self.label('二选一即可：MinerU 云端 Token，或自建 MinerU 地址。留空保留已有设置。', style='Muted.TLabel')
        canvas = tk.Canvas(self.body, highlightthickness=0, bg='#f4f6fa')
        scrollbar = ttk.Scrollbar(self.body, command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        cards = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=cards, anchor='nw')
        cards.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        def scroll(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        # Window-local binding: it also handles the wheel over a card's children.
        self.root.bind('<MouseWheel>', scroll)
        self.extra_inputs = {}
        self.extra_actions = {}
        for service in connection.EXTRA_SERVICES:
            title, url, _, instructions = connection.SERVICES[service]
            card = ttk.LabelFrame(cards, text=title, padding=12)
            card.pack(fill='x', pady=(0, 14), padx=(0, 8))
            ttk.Label(card, text=instructions, wraplength=690).pack(anchor='w', pady=(0, 8))
            row = ttk.Frame(card)
            row.pack(fill='x', pady=(0, 8))
            self.button(row, '打开说明 / 申请页面', lambda url=url: self.open_page(url)).pack(side='left')
            link = ttk.Entry(row)
            link.insert(0, url)
            link.configure(state='readonly')
            link.pack(side='left', fill='x', expand=True, padx=(10, 0))
            value = tk.StringVar()
            self.extra_inputs[service] = value
            row = ttk.Frame(card)
            row.pack(fill='x', pady=(0, 8))
            entry = ttk.Entry(row, textvariable=value, show='' if service == 'mineru_api' else '●')
            entry.pack(side='left', fill='x', expand=True)
            self.controls.append(entry)
            def paste(value=value):
                try:
                    value.set(self.root.clipboard_get().strip())
                except tk.TclError:
                    self.status.set('剪贴板没有文字，请先复制 Token 或服务地址。')
            self.button(row, '粘贴', paste).pack(side='left', padx=(10, 0))
            note = tk.StringVar(value='留空保留已有设置。')
            value.trace_add('write', lambda *_, value=value, note=note: note.set(
                '已收到输入，点击本项“验证并保存”。' if value.get() else '留空保留已有设置。'))
            if connection.extra_value(service):
                note.set('已有设置；留空保留，粘贴新内容可替换。')
            ttk.Label(card, textvariable=note, style='Muted.TLabel').pack(anchor='w')
            def save(service=service, value=value):
                if not value.get().strip():
                    self.status.set('没有填写新内容，已有设置未改变。')
                    return
                def complete(values):
                    try:
                        connection.save_account(values)
                    except Exception:
                        self.status.set('验证通过，但保存未完成，请重试；原有设置已保留。')
                        return
                    value.set('')
                    self.status.set(connection.SERVICES[service][0] + '：已验证并保存。')
                self.run(lambda: connection.accept(service, value.get()), complete, '正在验证，请稍候……')
            button = self.button(card, '验证并保存', save, True)
            button.pack(anchor='e', pady=(8, 0))
            self.extra_actions[service] = button
        self.button(self.footer, '完成并关闭', self.root.destroy).pack(side='right', padx=10)

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
    parser.add_argument('--group', action='store_true', default=None)
    parser.add_argument('--advanced', action='store_true')
    parser.add_argument('--ready-file')
    args = parser.parse_args()
    root = tk.Tk()
    Wizard(root, agent=args.agent, group=args.group, ready_file=args.ready_file, advanced=args.advanced)
    root.mainloop()


if __name__ == '__main__':
    main()
