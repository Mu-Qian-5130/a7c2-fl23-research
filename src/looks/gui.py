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
    '1. 检查 DCP / CUBE':('inspect',['source']),
    '2. 查看 ST 栏位计划':('plan',['project']),
    '3. 核对 ST 绑定文件':('check-bindings',['project','bindings']),
    '4. 根据量测生成校准':('calibrate',['patches','response','output']),
    '5. 拟合机内色表':('fit',['project','output']),
    '6. 生成更新与还原清单':('prepare-transition',['candidate','ap','cp','bindings','output'])}
LABELS={'source':'DCP / CUBE 文件','project':'项目 JSON','bindings':'ST 绑定 JSON',
        'patches':'已对齐的 RAW / ST 色块 NPZ','response':'已量测的 ISP 响应 JSON',
        'candidate':'候选文件夹','ap':'原始 appFw.so','cp':'原始 cpapp-b.bin','output':'新的输出目录'}
HELP={
    'inspect':'输入参考 DCP / CUBE，输出规格与哈希到下方日志。不会转换色表。',
    'plan':'读取已有项目 JSON，显示所选栏位及 ST 要求。此处不编辑项目，也不更改相机栏位。',
    'check-bindings':'核对项目与 ST 绑定 JSON 是否一致。绑定 JSON 是电脑端声明，不会读取相机实际设置。',
    'calibrate':'输入事先量测的色块 NPZ 和 ISP 响应 JSON，生成新的校准 JSON。不会自动拍摄、解码 RAW 或量测相机。',
    'fit':'项目 JSON 必须指向第 4 步生成或已有的真实校准文件。输出新目录，内含 candidate.json 和所选栏位色表。',
    'prepare-transition':'输入第 5 步候选、精确匹配的 AP / CP 和绑定 JSON，生成 forward.private.json / reverse.private.json。不会刷写相机。'}


def output_name(action):
    return {'calibrate':'calibration-v1.json','fit':'candidate-v1','prepare-transition':'transition-v1'}[ACTIONS[action][0]]


def field_label(action,key):
    return '新的校准 JSON 文件' if key=='output' and ACTIONS[action][0]=='calibrate' else LABELS[key]

def build_arguments(action,values,layout='full7-v4'):
    if action not in ACTIONS:raise ValueError('请选择支持的离线操作。')
    command,fields=ACTIONS[action]
    missing=[field_label(action,k) for k in fields if not values.get(k,'').strip()]
    if missing:raise ValueError('请填写：'+'、'.join(missing))
    result=[command]+[values[k].strip() for k in fields]
    if command=='prepare-transition':
        if layout not in ['full7-v4','three-preview-v2']:raise ValueError('不支持的来源布局。')
        result+=['--layout',layout]
    return result

def main(root=None):
    if root is None:root=tk.Tk()
    root.title('A7C II · 自定义 LUT / DCP');root.geometry('860x790');root.minsize(760,740)
    q=queue.Queue();running=[False];variables={key:tk.StringVar() for key in LABELS}
    outputs={command:tk.StringVar() for command in ['calibrate','fit','prepare-transition']}
    action=tk.StringVar(value=next(iter(ACTIONS)));layout=tk.StringVar(value='full7-v4')
    def variable(key):return outputs[ACTIONS[action.get()][0]] if key=='output' else variables[key]
    wrap=ttk.Frame(root,padding=20);wrap.pack(fill='both',expand=True)
    ttk.Label(wrap,text='自定义 LUT / DCP',font=('Microsoft YaHei UI',21,'bold')).pack(anchor='w')
    ttk.Label(wrap,text='六步对应下方操作菜单；全部离线，不连接或写入相机。\n先准备项目、绑定文件和量测数据；完整机内安装仍需独立集成。',wraplength=760).pack(anchor='w',pady=(5,12))
    controls=[];picker=ttk.Combobox(wrap,textvariable=action,values=list(ACTIONS),state='readonly');picker.pack(fill='x');controls.append(picker)
    helptext=tk.StringVar();ttk.Label(wrap,textvariable=helptext,wraplength=760).pack(anchor='w',pady=(8,0))
    fields=ttk.Frame(wrap);fields.pack(fill='x',pady=10)
    layoutrow=ttk.Frame(wrap)
    ttk.Label(layoutrow,text='精确来源布局：').pack(side='left')
    layoutpicker=ttk.Combobox(layoutrow,textvariable=layout,values=['full7-v4','three-preview-v2'],state='readonly');layoutpicker.pack(side='left');controls.append(layoutpicker)
    status=tk.StringVar(value='按需执行对应步骤；已有有效校准时可复用。')
    def browse(key):
        if key=='candidate':value=filedialog.askdirectory()
        elif key=='output':
            if ACTIONS[action.get()][0]=='calibrate':
                value=filedialog.asksaveasfilename(title='选择新的校准 JSON 文件',initialfile=output_name(action.get()),defaultextension='.json',filetypes=[('JSON','*.json'),('All','*.*')])
            else:
                parent=filedialog.askdirectory(title='选择父目录；输出会使用新的子目录')
                value=str(Path(parent)/output_name(action.get())) if parent else ''
        else:
            filters=[('JSON','*.json'),('All','*.*')] if key in ['project','bindings','response'] else [('NPZ','*.npz'),('All','*.*')] if key=='patches' else [('DCP / CUBE','*.dcp *.cube'),('All','*.*')] if key=='source' else [('All','*.*')]
            value=filedialog.askopenfilename(filetypes=filters)
        if value:variable(key).set(value)
    def render(*_):
        for child in fields.winfo_children():child.destroy()
        del controls[2:]
        command=ACTIONS[action.get()][0];helptext.set(HELP[command])
        for key in ACTIONS[action.get()][1]:
            ttk.Label(fields,text=field_label(action.get(),key)).pack(anchor='w')
            row=ttk.Frame(fields);row.pack(fill='x',pady=(2,6))
            entry=ttk.Entry(row,textvariable=variable(key));entry.pack(side='left',fill='x',expand=True)
            button=ttk.Button(row,text='选择',command=lambda k=key:browse(k));button.pack(side='left',padx=(6,0));controls.extend([entry,button])
        if ACTIONS[action.get()][0]=='prepare-transition':layoutrow.pack(fill='x',after=fields)
        else:layoutrow.pack_forget()
    picker.bind('<<ComboboxSelected>>',render);render()
    log=tk.Text(wrap,height=6,state='disabled',wrap='word');log.pack(side='bottom',fill='both',expand=True,pady=(8,0))
    ttk.Label(wrap,textvariable=status,wraplength=760).pack(anchor='w')
    def run():
        if running[0]:return
        try:args=build_arguments(action.get(),{k:variable(k).get() for k in ACTIONS[action.get()][1]},layout.get())
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
