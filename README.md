# 寻道大千二维码登录客户端

## Windows 桌面版

已打包的程序位于：

```text
dist\XundaoLogin.exe
```

双击后程序会自动读取 EXE 同目录的 `config.json`。首次使用点击“登录设置”，填写最新的 `x-game-token-pcweb` 并保存；随后二维码会显示在窗口中，使用支付宝扫码即可。

需要重新生成 EXE 时运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
```

扫码成功后的完整响应保存在 `dist\login-output\login-success.json`。
轮询中的最新响应会写入 `dist\login-output\login-last-response.json`。服务端返回 `USER_NOT_LOGIN` 时表示仍在等待扫码，程序会继续轮询，不会终止登录。

## 本地调试

在源码目录启动 GUI，终端会保留 Python 异常信息：

```powershell
powershell -ExecutionPolicy Bypass -File .\run-dev.ps1
```

也可以直接运行：

```powershell
py -3 .\xundao_login_app.py
```

使用 VS Code 打开本目录后，在代码行号左侧设置断点，按 `F5` 并选择“调试扫码登录窗口”。网络登录逻辑主要位于 `xundao_login_app.py` 的 `_login_worker` 方法。

该脚本复现以下浏览器流程：

1. 调用 `getLoginToken` 获取二维码 URL 和一次性登录 token。
2. 保存二维码图片并默认打开支付宝跳转链接。
3. 周期调用 `loginForPc`，直到成功、失败、二维码过期或超时。
4. 将接口响应保存到 `login-output/`，供后续分析游戏启动和资源接口。

## 安装

在本目录打开 PowerShell：

```powershell
py -3 -m pip install -r .\requirements.txt
```

## 运行

打开同目录的 `config.json`，填入最新请求中的 `x-game-token-pcweb`：

```json
{
  "pcToken": "这里填写最新值",
  "ctoken": "bigfish_ctoken_1ab4ieaf3e"
}
```

然后直接运行：

```powershell
py -3 .\xundao_qr_login.py
```

也可以通过环境变量或 `--pc-token`、`--ctoken` 参数临时覆盖配置文件。优先级为命令行参数、环境变量、配置文件：

```powershell
$env:XUNDAO_PC_TOKEN = '<当前的 x-game-token-pcweb>'
$env:XUNDAO_CTOKEN = '<当前的 ctoken>'
py -3 .\xundao_qr_login.py
```

常用参数：

```powershell
py -3 .\xundao_qr_login.py --interval 2 --max-wait 300 --no-browser
```

`x-game-token-pcweb` 是带 `userId` 的认证凭据，不应提交到 Git、日志或聊天记录。你已经公开过的值建议立即作废并重新获取。`ctoken` 也应以当前浏览器请求里的新值为准。

## 后续资源分析

登录成功后先保留 `login-output/login-success.json`。下一步需要浏览器开发者工具中“扫码成功之后”的首批请求，尤其是：

- 游戏启动/角色区服接口的 URL、请求体和响应；
- 新增的 Cookie、Authorization 或游戏侧 token；
- HTML/JS 入口地址及静态资源域名；
- WebSocket 地址和握手参数（如果存在）。

不要直接猜测 JWT 签名密钥；这里的二维码 token 是服务端签发的一次性会话标识，本地客户端只负责原样传递。
