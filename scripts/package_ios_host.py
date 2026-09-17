"""打包「设备端一键启动」精简包，分发给要在自己电脑上插 iPhone 的同事。

背景：scripts/ 目录里有很多开发/诊断用的脚本，但真正跑「一键启动」只需要
8 个文件。手工挑容易漏，这个脚本按依赖关系自动挑，并生成 zip。

用法（在工作区根目录）：
    python scripts/package_ios_host.py

产物：dist/TestHub-iOS-Host.zip（含一个使用说明 README.txt）

依赖关系（改脚本时请同步维护这两个清单）：
    ios_wda_host.bat -> ios_find_exe.ps1
                        ios_detect_udid.ps1   (内部再调 ios_find_exe.ps1)
                        ios_detect_lan_ip.ps1
                        ios_detect_wda.ps1
                        ios_release_ports.ps1
                        ios_register_device.ps1
                        ios_resolve_server.ps1
    ios_device_stop.bat -> ios_detect_udid.ps1 / ios_register_device.ps1
    ios_diag.bat -> ios_diag.ps1  (只读自检，排障用，建议一起带)
"""
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, 'dist')
OUT_ZIP = os.path.join(OUT_DIR, 'TestHub-iOS-Host.zip')

# 运行「一键启动」必需
REQUIRED = [
    'ios_wda_host.bat',
    'ios_find_exe.ps1',
    'ios_detect_udid.ps1',
    'ios_detect_lan_ip.ps1',
    'ios_detect_wda.ps1',
    'ios_release_ports.ps1',
    'ios_register_device.ps1',
    'ios_resolve_server.ps1',
]

# 强烈建议一起带上：出问题时排障用，且是只读的
RECOMMENDED = [
    'ios_device_stop.bat',
    'ios_diag.bat',
    'ios_diag.ps1',
]

README = """\
========================================================
 TestHub - iPhone 接入包（设备端）
========================================================

这个包里是什么
--------------
一组 Windows 脚本，作用是把插在这台电脑上的 iPhone 通过
WebDriverAgent 暴露给 TestHub 服务器，并自动把设备注册上去。
全程不需要装 Xcode，也不需要改平台代码。

运行前提（缺一不可）
--------------------
 1. Windows 10/11，且是【64 位】
 2. 一台 iPhone，系统版本 >= 17.4
    （iOS 17.0 ~ 17.3 不支持，请勿尝试）
 3. 一台能连到 TestHub 服务器的电脑，与服务器在同一局域网
 4. go-ios（ios.exe）已安装，版本 >= 1.3.2

开始之前：装两样东西
--------------------
[A] go-ios
    在【管理员 PowerShell】里执行：
        winget install --id danielpaulus.go-ios-agent -e
    装完若提示找不到 ios 命令，把安装目录里的 ios.exe 放到：
        C:\\tools\\go-ios\\ios.exe
    或者在本包同级创建文件（内容填 ios.exe 的完整路径）：
        %USERPROFILE%\\.testhub\\ios_exe.txt

[B] Apple 证书（这一步最容易被忽略，漏了后面必然失败）
    没有这两张证书时，挂载 Developer Disk Image 会报
        SEC_E_UNTRUSTED_ROOT
    而【浏览器能打开 gs.apple.com 并不能证明没问题】—— Chrome 会自己
    去补证书链，命令行不会。

    用 Win+R 打开 certmgr.msc（当前用户）或 certlm.msc（本机），导入：
        Apple Server Authentication CA  ->  中间证书颁发机构
        Apple Root CA                  ->  受信任的根证书颁发机构

    两张证书可在 https://www.apple.com/certificateauthority/ 下载。

怎么用
------
 1. 用【数据线】把 iPhone 插到这台电脑上
    - 手机要【解锁】
    - 屏幕弹出「要信任此电脑吗？」时点【信任】
 2. 右键 ios_wda_host.bat -> 以【管理员身份运行】
    （必须管理员，隧道的建立需要提权）
 3. 首次运行会问一次 TestHub 服务器地址，例如：
        http://192.168.8.75:18000
    输入后回车，之后会记住。正常情况下脚本能自动探测到，不必手输。
 4. 等待，直到看到：
        [SUCCESS] WDA is ready
        ... Registered device on TestHub
 5. 脚本会开 3 个黑窗口，名字分别是
        iOS-Tunnel / iOS-WDA / iOS-Forward
    【三个都不能关】，关掉任何一个设备就掉线。
 6. 去 TestHub -> 设备管理，应该能看到这台设备，状态为「在线」。

收工时
------
 双击 ios_device_stop.bat，它会清理端口占用并把设备在平台上置为离线。

出问题怎么办
------------
 先双击 ios_diag.bat（只读，不会改任何东西），它会逐项检查：
    Apple 证书 / go-ios 版本 / DDI 缓存 / 设备识别 /
    端口占用 / WDA 是否响应 / 能否连上 TestHub 服务器
 把它的输出整段发出来，比描述现象有用得多。

 常见现象速查：
   - 一直没反应            -> 多数是证书缺失，看 ios_diag 第 0 节
   - SEC_E_UNTRUSTED_ROOT  -> 上面 [B] 的两张证书没装好
   - could not find
     identity for ApBoardId -> devimages 目录里有旧镜像，把它移走重跑
   - deviceList:[]         -> USB 会话断了，【拔插数据线】才能恢复
   - register failed       -> 服务器地址不对或后端没起，看 ios_diag 第 5 节
   - 手机侧没反应          -> 确认手机已解锁、已点「信任此电脑」

需要装到这台电脑上的东西，只有 go-ios 和两张证书。
其他文件（TC、Node、Appium 等）都在 TestHub 服务器上，这里不需要。

========================================================
"""


def collect():
    missing = []
    files = []
    for name in REQUIRED:
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            files.append((name, p))
        else:
            missing.append(name)
    for name in RECOMMENDED:
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            files.append((name, p))
    return files, missing


def main():
    files, missing = collect()
    if missing:
        print('ABORT - these required files are missing:')
        for m in missing:
            print('  ' + m)
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    with zipfile.ZipFile(OUT_ZIP, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, path in files:
            z.write(path, name)
        z.writestr('README.txt', README)

    print('Created: %s' % OUT_ZIP)
    print('Contents (%d files + README.txt):' % len(files))
    for name, path in files:
        tag = 'required' if name in REQUIRED else 'recommended'
        print('  %-28s %-12s %d bytes' % (name, tag, os.path.getsize(path)))
    print()
    print('Tell the other person: unzip anywhere (e.g. Desktop), then')
    print('right-click ios_wda_host.bat -> Run as administrator.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
