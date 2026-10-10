# -*- coding: utf-8 -*-
"""
FOTA 自动化测试脚本 v2（多版本收敛测试）

流程：
    1) 本地目录扫描所有软件版本压缩包
    2) 用本地工具 adiff.exe 制作「每个源版本 -> 目标版本(最大版本)」的差分包
    3) 用本地烧录工具刷入某个源版本，配置上报
    4) 下发 AT+GTUPD 进行「该源版本 -> 目标版本」的差分包升级
    5) 升级成功后检查版本

用法：
    python Fota_Test_v2.py [项目名] [升级轮数] --fw-path <本地固件目录> \
        [--diff-out <差分包输出目录>] [--report-server <上报服务器IP/域名>] [--report-port <上报端口>] \
        [--report-cmd <上报AT命令，可多次>] [--fota-cmd <FOTA命令模板>] \
        [--udp-port <本地UDP验证端口>]

示例：
    python Fota_Test_v2.py GV58CG 1 --fw-path E:\\AutoTest\\FOTA\\GV58CG \
        --report-cmd "AT+GTBSI={server},{port}" --diff-out E:\\AutoTest\\FOTA\\diff
"""

import os
import sys
import re
import time
import socket
import threading
import subprocess
import datetime
import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from base64 import b64encode

import serial
import serial.tools.list_ports


# =============================================================================
# 常量与配置
# =============================================================================
FOTA_DIR = r"E:\AutoTest\FOTA"
HTTP_SERVER_IP = "60.174.225.173"   # 设备访问的 HTTP 服务器地址
HTTP_PORT = 30005
DIFF_TOOL = r"E:\FOTA\ota_diff\adiff.exe"
UPGRADE_TOOL = (
    r"E:\AutoTest\FOTA\Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0"
    r"\Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0.exe"
)
FLASH_START_TIMEOUT = 120   # 等待设备进入下载模式的超时(秒)
FLASH_TIMEOUT = 240         # 等待烧录完成并重启的超时(秒)
FOTA_WAIT = 400             # FOTA 差分包升级的等待时间(秒)
DIFF_OUTPUT_DIR = os.path.join(FOTA_DIR, "diff")   # 差分包输出目录(可用 --diff-out 覆盖)

# AT 命令
CMD_ATE_ON = "ATE1"           # 打开回显
CMD_VERSION = "AT+CSUB"       # 查询版本

# -----------------------------------------------------------------------------
# 上报配置 —— 请按实际项目填写
# -----------------------------------------------------------------------------
REPORT_CONFIG = {
    "server": "qlinkhf.f3322.org",   # 上报服务器域名(命令内已内嵌，此字段仅当 cmd 用 {server}/{port} 占位时才生效)
    "port": "30001",                 # 上报端口
    # 配置上报的 AT 命令，可用 {server}/{port} 占位；支持字符串或字符串列表(多条命令依次下发)
    "cmd": "AT+GTQSS=gv58cg,unicom,,,3,,2,qlinkhf.f3322.org,30001,,,,10,0,0,0,0.0.0.0,0.0.0.0,FFFF$",
    "udp_port": None,                # 可选：本地 UDP 监听端口，验证设备确实上报(None=不验证)
    "timeout": 60,                   # 等待上报数据的超时时间(秒)
}

# FOTA 升级命令模板(为空时用内置默认)；可用 {project}/{url} 占位
FOTA_CMD_TEMPLATE = ""


def get_storage(project_name):
    """根据项目名返回 (project_file_name, storage_size)。"""
    project_name = project_name.upper()

    if project_name == "GV300CEU_TZA":
        return "GV300CEU", "M128_XMC_TZA"
    if project_name in ("GV310LAU", "GV58LAU"):
        return project_name, "M1024_WBD"
    if project_name == "GV350CEU_MOB":
        return project_name, "M1024_MOB"
    if project_name == "GL33":
        return project_name, "N32"
    return project_name, "M128"


# =============================================================================
# 串口
# =============================================================================
def _is_modem_port(port):
    """调制解调器/AT 口：描述含 Queclink/ASR，且不是下载/启动口。"""
    desc = port.description
    if "Download" in desc or "Boot" in desc:
        return False
    return "Queclink" in desc or "ASR" in desc


def _download_ports():
    """当前处于下载模式的串口列表(描述含 Download)。"""
    return [p for p in serial.tools.list_ports.comports() if "Download" in p.description]


def _modem_ports():
    """当前可用的调制解调器/AT 串口列表。"""
    return [p for p in serial.tools.list_ports.comports() if _is_modem_port(p)]


def open_serial_port():
    """扫描串口，返回调制解调器(AT 口)，跳过下载/启动口。"""
    for port in _modem_ports():
        try:
            return serial.Serial(port.device, 115200, timeout=1)
        except serial.SerialException as e:
            print(f"Error opening serial port {port.device}: {e}")
    return None


def send_at(ser, cmd):
    """发送一条 AT 命令；失败返回 False(不抛异常)。"""
    if ser is None:
        print(f"[串口] 串口未打开，无法发送: {cmd}")
        return False
    try:
        ser.write(cmd.encode() + b"\r\n")
        print(f"write serial: {cmd}")
        return True
    except Exception as e:
        print(f"[串口] 发送失败: {cmd} -> {e}")
        return False


def read_all(ser):
    """读取串口缓冲区全部数据并解码去空白；异常时返回空串(不抛异常)。"""
    try:
        return ser.readall().decode(errors="replace").strip()
    except Exception as e:
        print(f"[串口] 读取失败: {e}")
        return ""


# =============================================================================
# HTTP 服务器(提供差分包下载，Basic 认证 admin:admin)
# =============================================================================
current_bin_path = ""   # AuthHandler 需要访问的全局变量


class AuthHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(current_bin_path), **kwargs)

    def _auth_head(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Test"')
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        if self.headers.get("Authorization") is None:
            self._auth_head()
            self.wfile.write(b"no auth header received")
        elif self.headers.get("Authorization") == "Basic " + b64encode(b"admin:admin").decode():
            SimpleHTTPRequestHandler.do_GET(self)
        else:
            self._auth_head()
            self.wfile.write(b"not authenticated")


def create_http_server(file_path, port):
    global current_bin_path
    current_bin_path = file_path
    httpd = HTTPServer(("0.0.0.0", port), AuthHandler)
    httpd.daemon_threads = True
    print(f"serving {file_path} at http://{HTTP_SERVER_IP}:{port}/{os.path.basename(file_path)}")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


# =============================================================================
# 步骤1：本地目录扫描版本
# =============================================================================
def discover_versions(local_path, project_file_name, storage):
    """扫描本地目录，返回 [(文件名, 版本号), ...]，按版本排序。"""
    result = []
    pattern = re.compile(re.escape(project_file_name) + r"(\S+?)" + re.escape(storage) + r"\.zip$")
    if not os.path.isdir(local_path):
        print(f"[获取版本] 本地固件目录不存在: {local_path}")
        return result
    for name in os.listdir(local_path):
        m = pattern.search(name)
        if m:
            result.append((name, m.group(1)))
    result.sort(key=lambda x: version_sort_key(x[1]))
    return result


def version_sort_key(v):
    """版本排序键：优先按数字段数值排序，纯字符串回退字典序。"""
    parts = re.findall(r"\d+", v)
    if parts:
        return (0, tuple(int(p) for p in parts), v)
    return (1, (), v)


def locate_fw_zip(local_path, project_file_name, version, storage):
    """在本地目录中定位指定版本的固件 zip 文件。"""
    target = f"{project_file_name}{version}{storage}.zip"
    path = os.path.normpath(os.path.join(local_path, target))
    return path if os.path.isfile(path) else None


# =============================================================================
# 步骤2：制作差分包(源版本 -> 目标版本)
# =============================================================================
def make_diff(project_name, project_file_name, start_version, end_version, storage, local_path, diff_dir):
    """解压本地固件并调用 adiff.exe 生成差分包，输出到 diff_dir，返回差分包路径。"""
    os.makedirs(diff_dir, exist_ok=True)
    bin_path = os.path.join(diff_dir, f"{project_name}_{start_version}TO{end_version}.bin")
    if os.path.exists(bin_path):
        print(f"[Diff] {bin_path} 已存在，跳过生成")
        return bin_path

    work_dir = os.path.join(FOTA_DIR, project_name)
    os.makedirs(work_dir, exist_ok=True)

    unzipped = {}
    for ver in (start_version, end_version):
        zip_file = locate_fw_zip(local_path, project_file_name, ver, storage)
        if zip_file is None:
            print(f"[Diff] 本地目录中未找到固件: {project_file_name}{ver}{storage}.zip")
            return None
        target_dir = os.path.join(work_dir, f"{project_file_name}{ver}{storage}")
        if not os.path.exists(os.path.join(target_dir, "system.img")):
            print(f"[Diff] unzip {zip_file} -> {target_dir}")
            subprocess.run(["unzip", "-o", zip_file, "-d", target_dir])
        unzipped[ver] = target_dir

    start_img = os.path.join(unzipped[start_version], "system.img")
    end_img = os.path.join(unzipped[end_version], "system.img")
    if not os.path.exists(start_img) or not os.path.exists(end_img):
        print(f"[Diff] 缺少 system.img: {start_img} / {end_img}")
        return None

    print(f"[Diff] ************************** Diff Start {start_version}->{end_version} **************************")
    ret = subprocess.run([DIFF_TOOL, "-p", start_img, end_img, bin_path])
    print("[Diff] ************************** Diff End **************************")
    if ret.returncode != 0 or not os.path.exists(bin_path):
        print(f"[Diff] 差分包生成失败: {bin_path}")
        return None
    return bin_path


# =============================================================================
# 步骤3：烧录源版本 / 配置上报 / 配置参数
# =============================================================================
def _wait_until(condition, timeout, desc):
    """轮询等待条件成立，每 2s 检查一次；超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(2)
    print(f"[烧录] 超时({timeout}s): {desc}")
    return False


def flash_version(project_file_name, version, storage, local_path, serial_port=None):
    """用本地烧录工具刷入指定版本的完整包，返回重新打开的串口。

    通过「下载口出现 -> 下载口消失且调制解调器口回来」判断烧录已完成并重启，
    而不是固定等待后再 taskkill(固定等待会过早中断烧录，使设备停在下载模式)。
    """
    zip_file = locate_fw_zip(local_path, project_file_name, version, storage)
    if zip_file is None:
        print(f"[烧录] 未找到完整包 {project_file_name}{version}{storage}.zip")
        return serial_port

    # 释放串口，烧录工具才能占用 COM 口
    if serial_port is not None:
        try:
            serial_port.close()
        except Exception:
            pass

    tool_name = "Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0.exe"
    print(f"[烧录] 开始刷入 {version}: {zip_file}")
    subprocess.run(["taskkill", "/F", "/IM", tool_name, "/T"], capture_output=True)
    subprocess.Popen([UPGRADE_TOOL, zip_file])

    # 1) 等设备进入下载模式(出现 Download 口)
    _wait_until(lambda: bool(_download_ports()), FLASH_START_TIMEOUT, "等待设备进入下载模式")
    # 2) 等烧录完成：下载口消失且调制解调器口重新出现(设备已重启)
    _wait_until(lambda: not _download_ports() and bool(_modem_ports()),
                FLASH_TIMEOUT, "等待烧录完成并重启")

    subprocess.run(["taskkill", "/F", "/IM", tool_name, "/T"], capture_output=True)
    time.sleep(5)   # 设备刚重启，留一点时间稳定

    serial_port = open_serial_port()
    if serial_port is None:
        print("[烧录] 烧录后未找到串口")
    return serial_port


class UdpReportListener(threading.Thread):
    """本地 UDP 监听，用于验证设备上报数据。"""

    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.received = []
        self._stop = threading.Event()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.settimeout(1)

    def run(self):
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
                self.received.append((addr, data))
                print(f"[上报] 收到 {addr} 数据: {data[:100]!r}")
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self):
        self._stop.set()
        try:
            self.sock.close()
        except OSError:
            pass


def configure_report(serial_port, logfile):
    """配置上报：用固定服务器(IP/域名)+端口填充上报命令并下发，可选 UDP 验证。"""
    server = REPORT_CONFIG.get("server")
    port = REPORT_CONFIG.get("port")
    raw = REPORT_CONFIG.get("cmd")
    if not raw:
        print("[上报] 未配置 REPORT_CONFIG['cmd']，跳过上报")
        return

    cmds = raw if isinstance(raw, list) else [raw]
    listener = None
    if REPORT_CONFIG.get("udp_port"):
        listener = UdpReportListener(REPORT_CONFIG["udp_port"])
        listener.start()
        print(f"[上报] 本地 UDP 监听已启动: 0.0.0.0:{REPORT_CONFIG['udp_port']}")

    with open(logfile, "a", encoding="utf-8") as f:
        f.write("************** 配置上报 开始 *****************\n")
        for template in cmds:
            try:
                cmd = template.format(server=server, port=port)
            except (KeyError, IndexError):
                cmd = template  # 未使用占位符时原样下发
            send_at(serial_port, cmd)
            recv = read_all(serial_port)
            f.write(f"[上报]:Send {cmd}\n[上报]:Recv {recv}\n")

    if listener:
        time.sleep(REPORT_CONFIG.get("timeout", 60))
        listener.stop()
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(f"[上报] 共收到 {len(listener.received)} 条上报数据\n")
        print(f"[上报] 验证: {'PASS' if listener.received else 'FAIL'} (收到 {len(listener.received)} 条)")


# =============================================================================
# 步骤4：FOTA 差分包升级
# =============================================================================
def check_version(serial_port, expected_version):
    send_at(serial_port, CMD_VERSION)
    recv = read_all(serial_port)
    print(f"[版本检查] Readdata: {recv}")
    return "PASS" if expected_version in recv else "FAIL"


def build_fota_cmd(project_name, project_file_name, url):
    """构造 FOTA 升级 AT 命令；FOTA_CMD_TEMPLATE 非空时用自定义模板。"""
    if FOTA_CMD_TEMPLATE:
        return FOTA_CMD_TEMPLATE.format(project=project_name.lower(), url=url)
    if project_file_name == "GV58CEU":
        return f"AT+GTUPD={project_name.lower()},0,3,10,0,admin,admin,{url},,0,,,,3,0,0,0001$"
    return f"AT+GTUPD={project_name.lower()},0,3,10,0,admin,admin,{url},,0,1,,0001$"


def ota_upgrade(project_name, project_file_name, serial_port, src_version, target_version, diff_dir, logfile):
    """下发 AT+GTUPD，用差分包把设备从 src_version 升级到 target_version，返回 (版本检查结果, 新串口)。"""
    bin_path = os.path.join(diff_dir, f"{project_name}_{src_version}TO{target_version}.bin")
    if not os.path.exists(bin_path):
        print(f"[升级] 差分包不存在: {bin_path}")
        return "FAIL", serial_port

    url = f"http://{HTTP_SERVER_IP}:{HTTP_PORT}/{os.path.basename(bin_path)}"
    fota_cmd = build_fota_cmd(project_name, project_file_name, url)

    httpd, httpd_thread = create_http_server(bin_path, HTTP_PORT)

    with open(logfile, "a", encoding="utf-8") as f:
        f.write(f"************ FOTA 开始升级: {fota_cmd} ************\n")
    send_at(serial_port, fota_cmd)
    print(f"[升级] Readdata: {read_all(serial_port)}")

    time.sleep(FOTA_WAIT)

    # FOTA 后设备会重启，串口会掉线，重新打开再检查版本
    if serial_port is not None:
        try:
            serial_port.close()
        except Exception:
            pass
    serial_port = open_serial_port()
    result = check_version(serial_port, target_version) if serial_port else "FAIL"

    with open(logfile, "a", encoding="utf-8") as f:
        f.write(f"************ FOTA 升级结束，结果:{result}，升级前:{src_version}，升级后:{target_version} ************\n")

    httpd.shutdown()
    httpd.server_close()
    httpd_thread.join(timeout=5)
    return result, serial_port


# =============================================================================
# 主流程
# =============================================================================
def run(project_name, count, local_path, diff_dir):
    project_name = project_name.upper()
    local_path = os.path.normpath(local_path)
    diff_dir = os.path.normpath(diff_dir)
    project_file_name, storage = get_storage(project_name)

    log_dir = os.path.join(FOTA_DIR, f"{project_name}LOG")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M")
    logfile = os.path.join(log_dir, f"{project_name}_parameter{ts}.txt")

    # 步骤1：扫描本地目录所有版本
    found = discover_versions(local_path, project_file_name, storage)
    if not found:
        print("[获取版本] 本地目录中未找到固件压缩包")
        sys.exit(1)
    versions = sorted({v for _, v in found}, key=version_sort_key)
    print(f"[获取版本] 发现版本: {versions}")
    if len(versions) < 2:
        print("[获取版本] 至少需要两个版本才能升级")
        sys.exit(1)
    target_version = versions[-1]          # 目标版本 = 最大版本
    source_versions = [v for v in versions if v != target_version]
    print(f"[获取版本] 目标版本(最大): {target_version}")
    print(f"[获取版本] 源版本: {source_versions}")

    # 步骤2：制作每个源版本 -> 目标版本 的差分包
    for src in source_versions:
        make_diff(project_name, project_file_name, src, target_version, storage, local_path, diff_dir)

    # 步骤3-5：逐版本 烧录 -> 配置上报/参数 -> FOTA升级 -> 参数检查
    serial_port = open_serial_port()
    if serial_port is None:
        print("No suitable serial port found.")
        sys.exit(1)

    try:
        for number in range(1, count + 1):
            for src in source_versions:
                print(f"\n========== 第 {number} 轮: {src} -> {target_version} ==========")

                # 步骤3：烧录源版本
                serial_port = flash_version(project_file_name, src, storage, local_path, serial_port)
                if serial_port is None:
                    print(f"[烧录] {src} 刷入失败，跳过该版本")
                    continue

                # 步骤3：配置上报
                configure_report(serial_port, logfile)

                # 步骤4：FOTA 差分包升级
                result, serial_port = ota_upgrade(project_name, project_file_name, serial_port,
                                                  src, target_version, diff_dir, logfile)
                print(f"[完成] {src}->{target_version} 版本检查:{result}")
    finally:
        if serial_port and serial_port.is_open:
            send_at(serial_port, CMD_ATE_ON)
            serial_port.close()


def main():
    parser = argparse.ArgumentParser(description="FOTA 自动化测试 v2(多版本收敛)")
    parser.add_argument("project", nargs="?", default="GV58CG", help="项目名称，默认 GV58CG")
    parser.add_argument("count", nargs="?", type=int, default=1, help="OTA 升级轮数，默认 1")
    parser.add_argument("--fw-path", required=True, help="本地固件目录(含各版本 zip)")
    parser.add_argument("--diff-out", default=DIFF_OUTPUT_DIR, help="差分包输出目录")
    parser.add_argument("--report-server", default=None, help="固定上报服务器 IP/域名")
    parser.add_argument("--report-port", default=None, help="固定上报端口")
    parser.add_argument("--report-cmd", action="append", default=None,
                        help="上报 AT 命令，可多次传入；支持 {server}/{port} 占位")
    parser.add_argument("--fota-cmd", default=None, help="FOTA 升级命令模板，支持 {project}/{url} 占位")
    parser.add_argument("--udp-port", type=int, default=None, help="本地 UDP 上报验证端口(可选)")
    args = parser.parse_args()

    if args.report_server:
        REPORT_CONFIG["server"] = args.report_server
    if args.report_port:
        REPORT_CONFIG["port"] = args.report_port
    if args.report_cmd:
        REPORT_CONFIG["cmd"] = args.report_cmd
    if args.fota_cmd:
        global FOTA_CMD_TEMPLATE
        FOTA_CMD_TEMPLATE = args.fota_cmd
    if args.udp_port:
        REPORT_CONFIG["udp_port"] = args.udp_port

    run(args.project, args.count, args.fw_path, args.diff_out)


if __name__ == "__main__":
    main()
