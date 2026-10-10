# -*- coding: utf-8 -*-
"""临时脚本：烧录 GV58CG 最低版本 -> 释放COM/关闭烧录工具/重开串口 -> 下发上报命令 -> 加载 Achange_at.ini 逐条下发命令"""
import os
import re
import sys
import time
import subprocess

import serial
import serial.tools.list_ports

PROJECT = "GV58CG"
LOCAL_PATH = r"E:\AutoTest\FOTA\GV58CG"
AT_CMD = "AT+GTQSS=gv58cg,unicom,,,3,,1,60.174.225.173,30001,,0,,10,0,0,0,0.0.0.0,0.0.0.0,0,FFFF$"
TOOL = "Queclink_Multi_Firmware_Upgrade_Tool.exe"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AT_INI = os.path.join(SCRIPT_DIR, "Achange_at.ini")

# 烧录工具与等待超时
UPGRADE_TOOL = (
    r"E:\AutoTest\FOTA\Queclink_Multi_Firmware_Upgrade_Tool_2.10"
    r"\Queclink_Multi_Firmware_Upgrade_Tool.exe"
)
FLASH_START_TIMEOUT = 120
FLASH_TIMEOUT = 240

# 上报服务器/端口默认值(仅当命令使用 {server}/{port} 占位时生效)
REPORT_CONFIG = {
    "server": "60.174.225.173",
    "port": "30001",
}


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


def reopen_serial_port(ser, timeout=60):
    """关闭旧串口，等待调制解调器串口重新出现并打开，返回新串口或 None。"""
    if ser is not None:
        try:
            ser.close()
        except Exception:
            pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        new_ser = open_serial_port()
        if new_ser is not None:
            return new_ser
        time.sleep(2)
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
    """读取串口缓冲区全部数据并解码去空白；异常时返回 None(表示串口掉线)。"""
    try:
        return ser.readall().decode(errors="replace").strip()
    except Exception as e:
        print(f"[串口] 读取失败: {e}")
        return None


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
    """用本地烧录工具刷入指定版本的完整包，返回重新打开的串口。"""
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

    tool_name = "Queclink_Multi_Firmware_Upgrade_Tool.exe"
    print(f"[烧录] 开始刷入 {version}: {zip_file}")
    subprocess.run(["taskkill", "/F", "/IM", tool_name, "/T"], capture_output=True)
    subprocess.Popen([UPGRADE_TOOL, zip_file])

    # 1) 等设备进入下载模式(出现 Download 口)
    _wait_until(lambda: bool(_download_ports()), FLASH_START_TIMEOUT, "等待设备进入下载模式")
    # 2) 等烧录完成：下载口消失且调制解调器口重新出现(设备已重启)
    _wait_until(lambda: not _download_ports() and bool(_modem_ports()),
                FLASH_TIMEOUT, "等待烧录完成并重启")

    subprocess.run(["taskkill", "/F", "/IM", tool_name, "/T"], capture_output=True)
    time.sleep(10)   # 设备刚重启，留一点时间稳定

    serial_port = open_serial_port()
    if serial_port is None:
        print("[烧录] 烧录后未找到串口")
    return serial_port


def load_at_commands(ini_path):
    """逐行读取 AT 命令文件，跳过空行与 # / ; 注释行，返回命令列表。"""
    cmds = []
    if not os.path.isfile(ini_path):
        print(f"[FAIL] 未找到 AT 命令文件: {ini_path}")
        return cmds
    with open(ini_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            cmds.append(line)
    return cmds


def send_at_commands(ser, cmds, server, port):
    """逐条下发 AT 命令；串口掉线时自动重开串口并重试，返回(可能重开后的)串口。"""
    for template in cmds:
        try:
            cmd = template.format(server=server, port=port)
        except (KeyError, IndexError, ValueError):
            cmd = template   # 命令未使用占位符或含非法花括号时原样下发

        if ser is None or not ser.is_open:
            ser = reopen_serial_port(ser)

        print(f"[INFO] 下发 AT 命令: {cmd}")
        if not send_at(ser, cmd):
            print("[INFO] 发送失败，重开串口后重试...")
            ser = reopen_serial_port(ser)
            if ser is None or not send_at(ser, cmd):
                print(f"[FAIL] 重试仍失败，跳过: {cmd}")
                continue

        time.sleep(3)
        recv = read_all(ser)
        if recv is None:
            print("[INFO] 读取失败(串口掉线)，重开串口供后续命令使用...")
            ser = reopen_serial_port(ser)
        print(f"[RESULT] Recv: {recv if recv is not None else ''}")
    return ser


def main():
    project_file_name, storage = get_storage(PROJECT)
    found = discover_versions(LOCAL_PATH, project_file_name, storage)
    if not found:
        print("[FAIL] 未发现固件压缩包")
        return 1
    versions = sorted({v for _, v in found}, key=version_sort_key)
    lowest = versions[0]
    print(f"[INFO] 发现版本: {versions}")
    print(f"[INFO] 最低版本: {lowest}")

    # 1) 烧录最低版本(内部会释放COM、启动烧录工具、完成后关闭工具并重开COM)
    ser = open_serial_port()
    if ser is None:
        print("[FAIL] 未找到调制解调器串口")
        return 1
    print("[INFO] 开始烧录最低版本...")
    ser = flash_version(project_file_name, lowest, storage, LOCAL_PATH, ser)

    # 2) 显式释放 COM 口、关闭烧录工具
    if ser is not None and ser.is_open:
        try:
            ser.close()
        except Exception:
            pass
    subprocess.run(["taskkill", "/F", "/IM", TOOL, "/T"], capture_output=True)
    time.sleep(2)

    # 2.5) 等待 10s 后，尝试开关一次 COM 口
    time.sleep(10)
    try:
        ser_tmp = open_serial_port()
        if ser_tmp is not None:
            print(f"[INFO] 开关 COM 口: 已打开 {ser_tmp.port}，随即关闭")
            if ser_tmp.is_open:
                ser_tmp.close()
        else:
            print("[WARN] 开关 COM 口: 未找到串口")
    except Exception as e:
        print(f"[WARN] 开关 COM 口异常: {e}")

    # 3) 重新打开 COM 口连接
    ser = open_serial_port()
    if ser is None:
        print("[FAIL] 重开串口失败")
        return 1
    print(f"[INFO] 串口已重开: {ser.port}")
    time.sleep(10)

    # 4) 下发上报配置命令
    print(f"[INFO] 下发上报命令: {AT_CMD}")
    send_at(ser, AT_CMD)
    time.sleep(6)
    recv = read_all(ser)
    print(f"[RESULT] Recv: {recv}")

    # 上报命令可能触发设备重启/串口掉线，关闭旧串口并等待串口重新出现后再继续
    ser = reopen_serial_port(ser)
    if ser is None:
        print("[FAIL] 上报后串口重开失败")
        return 1
    print(f"[INFO] 上报后串口已重开: {ser.port}")

    # 5) 上报之后：从本地加载 Achange_at.ini 逐条下发命令
    cmds = load_at_commands(AT_INI)
    if not cmds:
        print(f"[FAIL] AT 命令文件为空或不存在: {AT_INI}")
    else:
        print(f"[INFO] 从 {AT_INI} 读取到 {len(cmds)} 条 AT 命令")
        ser = send_at_commands(ser, cmds, REPORT_CONFIG["server"], REPORT_CONFIG["port"])

    if ser is not None and ser.is_open:
        ser.close()
    print("[DONE] 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
