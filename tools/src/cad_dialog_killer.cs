// cad_dialog_killer.cs — 检测并关闭 AutoCAD 弹出的模态对话框（避免阻塞 MCP）。
// 用法: cad_dialog_killer.exe <pid> [--watch] [--interval-ms 1000] [--timeout-s 60]
//
// --watch   持续监听并关闭对话框；否则只扫描一次后退出。
// 对话框判定: 可见的顶层 #32770（标准对话框）。对含 Button(Id=1=IDOK/Id=2=IDCANCEL)
// 的对话框发送 WM_COMMAND 模拟点击；对无按钮的对话框发送 WM_CLOSE。
// 关闭方式由 --strategy 控制: click(默认)/close/message 组合。
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

class KillDialog {
    delegate bool EnumProc(IntPtr h, IntPtr l);

    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lp);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr lp);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern int GetDlgCtrlID(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr SendMessageW(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern bool PostMessageW(IntPtr h, uint m, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr h);

    const uint WM_COMMAND = 0x0111;
    const uint WM_CLOSE = 0x0010;
    const uint BM_CLICK = 0x00F5;
    const int IDOK = 1;
    const int IDCANCEL = 2;

    static string _cls(IntPtr h) {
        var c = new StringBuilder(128); GetClassName(h, c, 128); return c.ToString();
    }
    static string _txt(IntPtr h) {
        var t = new StringBuilder(256); GetWindowText(h, t, 256); return t.ToString();
    }

    // 向对话框发送按钮点击（WM_COMMAND + BM_CLICK）。
    // alert 对话框的"确定"按钮是 IDCANCEL(2)（AutoCAD 实测），而非 IDOK(1)，
    // 故优先 IDOK，无则点击任意 Button。
    static void ClickButton(IntPtr dlg) {
        IntPtr target = IntPtr.Zero;
        EnumChildWindows(dlg, (h, l) => {
            string cls = _cls(h);
            if (cls == "Button" || cls == "Edit" || cls == "Static" && false) {
                int id = GetDlgCtrlID(h);
                if (id == IDOK) {
                    target = h;
                    return false; // 找到 IDOK，停止
                }
                if (id == IDCANCEL && target == IntPtr.Zero)
                    target = h;
            }
            return true;
        }, IntPtr.Zero);
        // 仍无 IDOK/IDCANCEL：点第一个 Button
        if (target == IntPtr.Zero) {
            EnumChildWindows(dlg, (h, l) => {
                if (_cls(h) == "Button") { target = h; return false; }
                return true;
            }, IntPtr.Zero);
        }
        if (target != IntPtr.Zero) {
            SendMessageW(target, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
            PostMessageW(target, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
        }
    }

    // 关闭单个可见对话框；返回是否处理了
    static bool CloseDialog(IntPtr h) {
        string cls = _cls(h);
        string title = _txt(h);
        if (cls != "#32770" || !IsWindowVisible(h))
            return false;

        bool hasButton = false;
        EnumChildWindows(h, (ch, l) => {
            if (_cls(ch) == "Button") { hasButton = true; return false; }
            return true;
        }, IntPtr.Zero);

        if (hasButton) {
            ClickButton(h);
        } else {
            // 无按钮：发 WM_CLOSE / 尝试 DestroyWindow
            PostMessageW(h, WM_COMMAND, (IntPtr)IDOK, IntPtr.Zero);
            PostMessageW(h, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
        }
        Console.WriteLine("closed dialog: h={0} cls={1} title={2}", h, cls, title);
        return true;
    }

    static int Scan(uint pid, string strategy) {
        int closed = 0;
        EnumWindows((h, l) => {
            uint p;
            GetWindowThreadProcessId(h, out p);
            if (p == pid && IsWindowVisible(h)) {
                string cls = _cls(h);
                if (cls == "#32770") {
                    if (strategy == "close") {
                        PostMessageW(h, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
                    } else if (strategy == "destroy") {
                        DestroyWindow(h);
                    } else { // click (default)
                        CloseDialog(h);
                    }
                    closed++;
                }
            }
            return true;
        }, IntPtr.Zero);
        return closed;
    }

    static int Main(string[] args) {
        if (args.Length < 1) {
            Console.Error.WriteLine("usage: cad_dialog_killer.exe <pid> [--watch] [--interval-ms 1000] [--timeout-s 60] [--strategy click|close|destroy]");
            return 2;
        }
        uint pid;
        if (!uint.TryParse(args[0], out pid)) {
            Console.Error.WriteLine("bad pid: " + args[0]);
            return 2;
        }
        bool watch = false;
        int intervalMs = 1000;
        int timeoutS = 60;
        string strategy = "click";
        for (int i = 1; i < args.Length; i++) {
            if (args[i] == "--watch") watch = true;
            else if (args[i] == "--interval-ms" && i + 1 < args.Length) intervalMs = int.Parse(args[++i]);
            else if (args[i] == "--timeout-s" && i + 1 < args.Length) timeoutS = int.Parse(args[++i]);
            else if (args[i] == "--strategy" && i + 1 < args.Length) strategy = args[++i];
        }
        if (!watch) {
            int closed = Scan(pid, strategy);
            Console.WriteLine("scanned: closed={0}", closed);
            return closed > 0 ? 0 : 1;
        }
        DateTime end = DateTime.Now.AddSeconds(timeoutS);
        int total = 0;
        while (DateTime.Now < end) {
            total += Scan(pid, strategy);
            Thread.Sleep(intervalMs);
        }
        Console.WriteLine("watch done: closed={0}", total);
        return 0;
    }
}
