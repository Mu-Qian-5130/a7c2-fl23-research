"""Custom LUT/DCP offline GUI. Executes only existing offline looktool commands."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog,messagebox,ttk

BASE=Path(__file__).resolve().parent
ACTIONS={
    '检查 DCP / CUBE':('inspect',['source']),
    '查看栏位计划':('plan',['project']),
    '核对 ST 绑定文件':('check-bindings',['project','bindings']),
    '拟合机内色表':('fit',['project','output']),
    '生成色表更新清单':('prepare-transition',['candidate','ap','cp','bindings','output'])}
LABELS={'source':'DCP / CUBE 文件','project':'项目 JSON','bindings':'ST 绑定 JSON',
        'candidate':'候选文件夹','ap':'原始 appFw.so','cp':'原始 cpapp-b.bin','output':'新的输出目录'}

def build_arguments(action,values,layout='full7-v4'):
    if action not in ACTIONS:raise ValueError('请选择支持的离线操作。')
    command,fields=ACTIONS[action]
    missing=[LABELS[k] for k in fields if not values.get(k,'').strip()]
    if missing:raise ValueError('请填写：'+'、'.join(missing))
    result=[command]+[values[k].strip() for k in fields]
    if command=='prepare-transition':
        if layout not in ['full7-v4','three-preview-v2']:raise ValueError('不支持的来源布局。')
        result+=['--layout',layout]
    return result

def main(root=None):
    if root is None:root=tk.Tk()
    root.title('A7C II · 自定义 LUT / DCP');root.geometry('820x720');root.minsize(740,680)
    q=queue.Queue();running=[False];variables={key:tk.StringVar() for key in LABELS}
    action=tk.StringVar(value=next(iter(ACTIONS)));layout=tk.StringVar(value='full7-v4')
    wrap=ttk.Frame(root,padding=20);wrap.pack(fill='both',expand=True)
    ttk.Label(wrap,text='自定义 LUT / DCP',font=('Microsoft YaHei UI',21,'bold')).pack(anchor='w')
    ttk.Label(wrap,text='离线生成候选与补丁清单，不连接或写入相机。\n完整机内安装仍需名称、设置及设备集成；拟合前请准备量测校准。',wraplength=760).pack(anchor='w',pady=(5,12))
    controls=[];picker=ttk.Combobox(wrap,textvariable=action,values=list(ACTIONS),state='readonly');picker.pack(fill='x');controls.append(picker)
    fields=ttk.Frame(wrap);fields.pack(fill='x',pady=10)
    layoutrow=ttk.Frame(wrap)
    ttk.Label(layoutrow,text='精确来源布局：').pack(side='left')
    layoutpicker=ttk.Combobox(layoutrow,textvariable=layout,values=['full7-v4','three-preview-v2'],state='readonly');layoutpicker.pack(side='left');controls.append(layoutpicker)
    status=tk.StringVar(value='先检查参考文件或查看项目计划。')
    def browse(key):
        if key=='candidate':value=filedialog.askdirectory()
        elif key=='output':
            parent=filedialog.askdirectory(title='选择父目录；输出会使用下面的新子目录')
            value=str(Path(parent)/'candidate-v1') if parent else ''
        else:
            filters=[('JSON','*.json'),('All','*.*')] if key in ['project','bindings'] else [('DCP / CUBE','*.dcp *.cube'),('All','*.*')] if key=='source' else [('All','*.*')]
            value=filedialog.askopenfilename(filetypes=filters)
        if value:variables[key].set(value)
    def render(*_):
        for child in fields.winfo_children():child.destroy()
        del controls[2:]
        for key in ACTIONS[action.get()][1]:
            ttk.Label(fields,text=LABELS[key]).pack(anchor='w')
            row=ttk.Frame(fields);row.pack(fill='x',pady=(2,6))
            entry=ttk.Entry(row,textvariable=variables[key]);entry.pack(side='left',fill='x',expand=True)
            button=ttk.Button(row,text='选择',command=lambda k=key:browse(k));button.pack(side='left',padx=(6,0));controls.extend([entry,button])
        if ACTIONS[action.get()][0]=='prepare-transition':layoutrow.pack(fill='x',after=fields)
        else:layoutrow.pack_forget()
    picker.bind('<<ComboboxSelected>>',render);render()
    log=tk.Text(wrap,height=6,state='disabled',wrap='word');log.pack(side='bottom',fill='both',expand=True,pady=(8,0))
    ttk.Label(wrap,textvariable=status,wraplength=760).pack(anchor='w')
    def run():
        if running[0]:return
        try:args=build_arguments(action.get(),{k:v.get() for k,v in variables.items()},layout.get())
        except ValueError as exc:messagebox.showinfo('检查输入',str(exc));return
        running[0]=True;status.set('正在离线处理；原文件和相机均不会被写入。')
        button.configure(state='disabled')
        for control in controls:control.configure(state='disabled')
        def worker():
            try:
                env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
                flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                with subprocess.Popen([sys.executable,'-u','-m','looktool']+args,cwd=BASE,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=flags) as process:
                    for line in process.stdout:q.put(('log',line))
                    q.put(('done',process.wait()))
            except Exception as exc:q.put(('log',str(exc)+'\n'));q.put(('done',1))
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(wrap,text='执行离线操作',command=run);button.pack(anchor='w',pady=8)
    def tick():
        try:
            while True:
                kind,value=q.get_nowait()
                if kind=='log':log.configure(state='normal');log.insert('end',value);log.see('end');log.configure(state='disabled')
                else:
                    running[0]=False;button.configure(state='normal')
                    for control in controls:control.configure(state='readonly' if isinstance(control,ttk.Combobox) else 'normal')
                    status.set('离线处理完成。候选或清单不代表已经安装到相机。' if value==0 else '已停止；请检查日志与输入，不会自动重试。')
        except queue.Empty:pass
        root.after(100,tick)
    def close():
        if running[0]:messagebox.showinfo('处理中','请等离线任务结束，保留结果。')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);tick();root.mainloop()
if __name__=='__main__':main()
