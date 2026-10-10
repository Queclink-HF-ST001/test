import os
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from base64 import b64encode
import serial.tools.list_ports
import serial
import openpyxl
import datetime
import shutil


thread_exit=None
filename = ""
# 创建一个全局变量，用于控制线程退出
log_exit_flag = False

project_file_name=""

def open_serial_port():
    for port in serial.tools.list_ports.comports():
        if "ASR" in port.description or "Queclink" in port.description:
            try:
                ser = serial.Serial(port.device, 115200, timeout=1)
                return ser
            except serial.SerialException as e:
                print(f"Error opening serial port {port.device}: {e}")
    return None

class AuthHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        global file_path
        super().__init__(*args, directory=os.path.dirname(file_path), **kwargs)

    def do_HEAD(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Test"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_AUTHHEAD(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Test"')
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        if self.headers.get('Authorization') is None:
            self.do_HEAD()
            self.wfile.write(b'no auth header received')
        elif self.headers.get('Authorization') == 'Basic ' + b64encode(b"admin:admin").decode():
            return SimpleHTTPRequestHandler.do_GET(self)
        else:
            self.do_AUTHHEAD()
            self.wfile.write(b'not authenticated')


def create_http_server(file_path, port):
    httpd = HTTPServer(('0.0.0.0', port), AuthHandler)
    print(f"serving {file_path} at http://60.174.225.173:{port}/{os.path.basename(file_path)}")
    httpd.daemon_threads = True
    httpd_thread = threading.Thread(target=httpd.serve_forever)
    httpd_thread.start()
    return httpd, httpd_thread

def user_input_thread(httpd):
    global thread_exit
    while True:
        if thread_exit == '300':
            httpd.shutdown()
            httpd.server_close()
            print("HTTP server stopped.")
            break
        time.sleep(2)


def dowload_file(project_name,stroge_size):
    # 定义 FTP 路径
    ftp_path = f"ftp://192.168.10.108/SW_RD/Firmware/Standard/{project_name}/BB/"

    # 打开 Excel 文件
    workbook = openpyxl.load_workbook(f'{project_name}_FOTA_UPGRADE_VERSION.xlsx')

    # 选择第一个工作表
    worksheet = workbook['Sheet1']

    # 遍历每一行
    for row_number in range(2, worksheet.max_row + 1):
        # 获取 START_VERSION 和 END_VERSION 列的值
        start_version = worksheet.cell(row=row_number, column=2).value
        end_version = worksheet.cell(row=row_number, column=3).value

        # 如果 START_VERSION 或者 END_VERSION 为空，则打印行号、列号并提示
        if not start_version or not end_version:
            print(f"Please enter a version number for row {row_number}, column {1 if not start_version else 2}.")
        else:
            # 将 start_version 和 end_version 转换为字符串类型
            start_version = str(start_version)
            end_version = str(end_version)

            # 截取 start_version 和 end_version 的前6位
            start_version_file = start_version[:6]
            end_version_file = end_version[:6]
            # 拼接 FTP 路径和文件名
            start_version_ftp = ftp_path + start_version_file
            end_version_ftp = ftp_path + end_version_file

            # 打印 START_VERSION 和 END_VERSION 列的值以及截取后的文件名和 FTP 路径
            print("Start version:", start_version, "End version:", end_version)
            print("Start version file:", start_version_file, "End version file:", end_version_file)
            print("Start version FTP:", start_version_ftp, "End version FTP:", end_version_ftp)

            # 判断文件是否存在，如果不存在则下载
            if not os.path.exists(f"E:\AutoTest\FOTA\{project_name}\{project_file_name}{start_version}{stroge_size}.zip"):
                print(f"curl -u hfsw31:evan@123 -O {start_version_ftp}/{project_file_name}{start_version}{stroge_size}.zip")
                #os.system(f"curl -u hfsw31:evan@123 -O {start_version_ftp}/{project_name}{start_version}{stroge_size}.zip")
                os.system(f"curl -u hfsw31:evan@123 -o E:/AutoTest/FOTA/GV350CEU/{project_file_name}{start_version}{stroge_size}.zip {start_version_ftp}/{project_file_name}{start_version}{stroge_size}.zip")
            if not os.path.exists(f"E:\AutoTest\FOTA\{project_name}\{project_file_name}{end_version}{stroge_size}.zip"):
                print(f"curl -u hfsw31:evan@123 -O {start_version_ftp}/{project_file_name}{start_version}{stroge_size}.zip")
                #os.system(f"curl -u hfsw31:evan@123 -O {end_version_ftp}/{project_name}{end_version}{stroge_size}.zip")
                os.system(f"curl -u hfsw31:evan@123 -o E:/AutoTest/FOTA/GV350CEU/{project_file_name}{end_version}{stroge_size}.zip {start_version_ftp}/{project_file_name}{end_version}{stroge_size}.zip")
    # 关闭 Excel 文件
    workbook.close()
    

def Diff_Package(project_name,stroge_size):
    global project_file_name
    # 打开 Excel 文件
    workbook = openpyxl.load_workbook(f'{project_name}_FOTA_UPGRADE_VERSION.xlsx')
    # 选择第一个工作表
    worksheet = workbook['Sheet1']
    # 遍历每一行
    for row_number in range(2, worksheet.max_row + 1):
        # 获取 START_VERSION 和 END_VERSION 列的值
        start_version = worksheet.cell(row=row_number, column=2).value
        end_version = worksheet.cell(row=row_number, column=3).value
   
        # 如果 START_VERSION 或者 END_VERSION 为空，则打印行号、列号并提示
        if not start_version or not end_version:
            print(f"Please enter a version number for row {row_number}, column {1 if not start_version else 2}.")
        else:
            # 将 start_version 和 end_version 转换为字符串类型
            start_version = str(start_version)
            end_version = str(end_version)

            # 截取 start_version 和 end_version 的前6位
            start_version_file = start_version[:6]
            end_version_file = end_version[:6]
            # 拼接 FTP 路径和文件名

            print("Start version:", start_version, "End version:", end_version)
            # 解压当前路径下的文件{project_name}{start_version}{stroge_size}.zip
            if not os.path.exists(f"E:\AutoTest\FOTA\{project_name}\{project_file_name}{start_version}{stroge_size}"):
                print(f"unzip -o E:\\AutoTest\\FOTA\\{project_name}\\{project_file_name}{start_version}{stroge_size}.zip -d E:\\AutoTest\\FOTA\\{project_file_name}\\{project_name}{start_version}{stroge_size}")
                os.system(f"unzip -o E:\\AutoTest\\FOTA\\{project_name}\\{project_file_name}{start_version}{stroge_size}.zip -d E:\\AutoTest\\FOTA\\{project_file_name}\\{project_name}{start_version}{stroge_size}")
            else:
                print(f"E:\\AutoTest\\FOTA\\{project_file_name}\\{project_name}{start_version}{stroge_size} 已经存在，跳过unzip")
            
            if not os.path.exists(f"E:\AutoTest\FOTA\{project_name}\{project_file_name}{end_version}{stroge_size}"):
                print(f"unzip -o E:\\AutoTest\\FOTA\\{project_name}\\{project_file_name}{end_version}{stroge_size}.zip  -d E:\\AutoTest\\FOTA\\{project_file_name}\\{project_name}{end_version}{stroge_size}")                
                os.system(f"unzip -o E:\\AutoTest\\FOTA\\{project_name}\\{project_file_name}{end_version}{stroge_size}.zip  -d E:\\AutoTest\\FOTA\\{project_file_name}\\{project_name}{end_version}{stroge_size}")
            else:
                print(f"E:\\AutoTest\\FOTA\\{project_file_name}\\{project_name}{end_version}{stroge_size} 已经存在，跳过unzip")            
            # 执行 adiff.exe
            print("**************************Diff Start*********************************************")
            if not os.path.exists(f"E:\\AutoTest\\FOTA\\{project_name}_{start_version}TO{end_version}.bin"):
                os.system(f"E:\\FOTA\\ota_diff\\adiff.exe -p  E:\\AutoTest\\FOTA\\{project_name}\\{project_file_name}{start_version}{stroge_size}\\system.img   E:\\AutoTest\\FOTA\\{project_name}\\{project_file_name}{end_version}{stroge_size}\\system.img  E:\\AutoTest\\FOTA\\{project_name}_{start_version}TO{end_version}.bin")
            else:
                print(f"E:\\AutoTest\\FOTA\\{project_name}_{start_version}TO{end_version}.bin 已经存在，跳过Diff")    
            print("**************************Diff End*********************************************")
    # 关闭 Excel 文件
    workbook.close()

#写入串口AT 命令
def write_serial(serial_port, write_string):
    serial_port.write(write_string.encode()+b'\r\n')
    print("write serial:{}".format(write_string))

def check_version(serial_port, write_string, SW_VERSION):
    print("write serial:{}".format(write_string))
    serial_port.write(write_string.encode() + b'\r\n')
    read_msg = serial_port.readall()
    print('Readdata: {}'.format(read_msg))
    if SW_VERSION in format(read_msg):
        return "PASS"
    else:
        return "FAIL"
def check_version_after_delay(lock, serial_port, VERSION_CHECK, start_version,end_version, workbook,worksheet, row_number, RESULTS_COLUMN):
    global thread_exit
    global filename  # 声明filename为全局变量
    with lock:
        print("FOTA 升级成功版本检查开始::::::::::::::::::::::::::::::::::::::::::::::")
        check_result = check_version(serial_port, VERSION_CHECK, end_version)
        print("FOTA 升级成功版本检查：{}".format(check_result))
        with open(filename, 'a') as file:  # 使用追加模式打开文件
            file.write(f"************FOTA 升级结束，升级结果:{check_result}，升级前版本：{start_version}，升级后版本：{end_version}************\n")
        file.close()
        worksheet.cell(row=row_number, column=RESULTS_COLUMN).value = check_result
        workbook.save(f'{project_name}_FOTA_UPGRADE_VERSION.xlsx')
        thread_exit = "300"
        print("thread_exit ==300 设置成功")
     
def log_write(serial_port, LOG_CMD):
    global log_exit_flag
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    serial_port.write(LOG_CMD.encode() + b'\r\n')
    with open('log.txt', 'a') as file:
        while not log_exit_flag:
            read_msg = serial_port.readall().decode().strip()
            file.write(f"[{timestamp}]:{read_msg} + '\n'")
 
def parameter_write(serial_port, parameter_file,number):
    global filename  # 声明filename为全局变量
    CMD_ATE = "ATE0"  #关闭回显
    try:
        if serial_port is None:
            raise ValueError("Error: serial port is not open")
        
        workbook = openpyxl.load_workbook(parameter_file)
        write_worksheet = workbook['Write_Cmd']
        read_worksheet = workbook['Read_Cmd']
        write_command_column = next((col[0].column for col in write_worksheet.iter_cols() if col[0].value == 'Command'), None)
        serial_port.write(CMD_ATE.encode() + b'\r\n')
        read_msg = serial_port.readall().decode().strip()
        
        if write_command_column is None:
            print("Error: Command column not found")
            return
        
        with open(filename, 'a') as file:
            file.write(f"**************parameter_write start times:{number}*****************\n")
            for row in write_worksheet.iter_rows(min_row=2, values_only=True):
                command = row[write_command_column - 1]
                if command == 'Sleep':
                    time.sleep(1)
                    continue
                print(f"write serial: {command}")
                serial_port.write(command.encode() + b'\r\n')
                read_msg = serial_port.readall().decode().strip()
                read_msg = read_msg.replace('\r\n', '')
                print(f"Readdata: {read_msg}")
                
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                file.write(f"[{timestamp}]:Send {command}\n")
                file.write(f"[{timestamp}]:Recv {read_msg}\n")
                read_msg=""
        file.close()
    except Exception as e:
        print(f"Error: {e}")

def parameter_read(serial_port, parameter_file,number):
    global filename  # 声明filename为全局变量
    CMD_ATE = "ATE0"
    try:
        print(f"********************************Read Start{number}*************************************")
        if serial_port is None:
            raise ValueError("Error: serial port is not open")
        workbook = openpyxl.load_workbook(parameter_file)
        read_worksheet = workbook['Read_Cmd']
        readsheet_command_column = next((col[0].column for col in read_worksheet.iter_cols() if col[0].value == 'Command'), None)
        readsheet_compare_column = next((col[0].column for col in read_worksheet.iter_cols() if col[0].value == 'Compare'), None)
        serial_port.write(CMD_ATE.encode() + b'\r\n')
        if readsheet_command_column is None:
            raise ValueError("Error: Command column not found")
        if readsheet_compare_column is None:
            raise ValueError("Error: Compare column not found")
        actual_max_row = 0
        for row in read_worksheet.iter_rows():
            if all(cell.value is None for cell in row):
                # 如果这一行所有单元格的值都是 None，则认为这一行是空行
                continue
            actual_max_row += 1
        print(f"实际行数：{actual_max_row}")
        read_msg = serial_port.readall().decode().strip()
        print(f"read_msg: {read_msg}")
        print(f"read_msg length: {len(read_msg)}")
        read_msg = ""
        with open(filename, 'a') as file:  # 使用追加模式打开文件
            file.write(f"**************parameter_read start times:{number}*****************\n")
            for row in range(2, actual_max_row + 1):
                read_msg= ""
                command = read_worksheet.cell(row=row, column=readsheet_command_column).value
                compare = read_worksheet.cell(row=row, column=readsheet_compare_column).value
                if command == 'Sleep':
                    time.sleep(1)
                    continue
                print(f"write serial: {command}")
                serial_port.write(command.encode() + b'\r\n')
                read_msg = serial_port.readall().decode().strip()
                print(f"read_msg: {read_msg}")
                print(f"read_msg length: {len(read_msg)}")
                read_msg = read_msg.replace('\r\n', '')
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                compare_result = True  # 初始化比较结果为True
                file.write(f"[{timestamp}]:Send {command}\n")
                file.write(f"[{timestamp}]:Recv {read_msg}\n")
                if compare:
                    read_msg_list = read_msg.split(',')
                    compare_list = compare.split(',')
                    for i in range(len(compare_list) - 1):
                        if '{Protocol}' in compare_list[i] or '{IMEI}' in compare_list[i]:
                            continue
                        if read_msg_list[i] != compare_list[i]:
                            print(f"read_msg_list:{read_msg_list[i]} compare_list:{compare_list[i]}")
                            file.write(f"read_msg_list:{read_msg_list[i]} compare_list:{compare_list[i]}\n")
                            #print("Fail")
                            compare_result = False  # 存在失败的比较，将比较结果设置为False
                        else:
                            print(f"read_msg_list:{read_msg_list[i]} compare_list:{compare_list[i]}")
                            #print("PASS")
                # 将command和read_msg写入文件
                if compare_result:
                    file.write(f"[{timestamp}]: Compare Result: PASS\n")
                    print(f"[{timestamp}]: Compare Result: PASS\n")
                else:
                    file.write(f"[{timestamp}]: Compare Result: FAIL\n")
                    print(f"[{timestamp}]: Compare Result: FAIL\n")
        file.close()
        #serial_port.close()
    except Exception as e:
        print(f"Error: {e}")
        
def OTA_UPGTADE(project_name,stroge_size,serial_port,number):
    global file_path
    global thread_exit
    VERSION_CHECK = "AT+CSUB"
    RESET_CMD = "AT+MCUCMD=14"
    LOG_CMD="AT+LOGCFG=1,2,3,UPD,COMM"
    FOTA_PATH = "E:\\AutoTest\\FOTA\\"
    port = 10075
    parameter_file = f'{project_name}_CMD_CHECK.xlsx'
    # 打开 Excel 文件
    workbook = openpyxl.load_workbook(f'{project_name}_FOTA_UPGRADE_VERSION.xlsx')
    # 选择第一个工作表
    worksheet = workbook['Sheet1']
    # 遍历每一行
    for row_number, (start_version, end_version, _) in enumerate(worksheet.iter_rows(min_row=2, min_col=2, max_col=4, values_only=True), start=2):
        # Create a lock object
        lock = threading.Lock()
        thread_exit="200" 
        # 获取 START_VERSION 和 END_VERSION 列的值
        start_version = worksheet.cell(row=row_number, column=2).value
        end_version = worksheet.cell(row=row_number, column=3).value
        RESULTS_COLUMN = 4  # Define the column number for the RESULTS column
        # 如果 START_VERSION 或者 END_VERSION 为空，则打印行号、列号并提示
        if not start_version or not end_version:
            print(f"Please enter a version number for row {row_number}, column {1 if not start_version else 2}.")
        else:
            # 将 start_version 和 end_version 转换为字符串类型
            start_version = str(start_version)
            end_version = str(end_version)
            print("Start version:", start_version, "End version:", end_version)
            
            check_result=check_version(serial_port, VERSION_CHECK,start_version)
            print(check_result)
            if check_result == "FAIL":
                serial_port.close()
                os.system(f"taskkill /F /IM  Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0.exe  /T")
                os.system(f"start  E:\\AutoTest\\FOTA\\Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0\\Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0.exe    E:\\AutoTest\\FOTA\\{project_name}\\{project_name}{start_version}{stroge_size}.zip")
                time.sleep(100)
                os.system(f"taskkill /F /IM  Queclink_Multi_Fw_Upgrade_Tool_Script_V1.0.exe  /T")
                print("")
                #机器重启后重新打开端口
                serial_port = open_serial_port()
                if serial_port:
                    print(f"Serial port {serial_port.name} opened successfully")
                else:
                    print("No suitable serial port found.")
                    sys.exit(1)

            #升级之前写入参数,读出参数保存
            parameter_write(serial_port,parameter_file,number)
            parameter_read(serial_port,parameter_file,number)
            
            #write_serial(serial_port,RESET_CMD)
            #time.sleep(40)
            FOTA_FILE_NAME = f"{project_name}_{start_version}TO{end_version}.bin"
            if project_file_name == "GV58CEU":
                FOTA_AT_CMD = f"AT+GTUPD={project_name.lower()},0,3,10,0,admin,admin,http://60.174.225.173:{port}/{{}},,0,,,,3,0,0,0001$".format(FOTA_FILE_NAME)
            else:
                FOTA_AT_CMD = f"AT+GTUPD={project_name.lower()},0,3,10,0,admin,admin,http://60.174.225.173:{port}/{{}},,0,1,,0001$".format(FOTA_FILE_NAME)
            
            #文件写入fota 下发命令
            file_path = os.path.join(FOTA_PATH, FOTA_FILE_NAME)
            print(file_path)
            #创建线程，创建HTTP 链接

            if os.path.isfile(file_path):
                print('文件存在')
            else:
                print('文件不存在')
            httpd, httpd_thread = create_http_server(file_path, port)
            thread_exit_control = threading.Thread(target=user_input_thread, args=(httpd,))
            thread_exit_control.start()
            #FOTA log
            #log_thread = threading.Thread(target=log_write, args=(serial_port, LOG_CMD))
            #log_thread.start()
            print("FOTA AT CMD::::::::{}".format(FOTA_AT_CMD))
            with open(filename, 'a') as file:  # 使用追加模式打开文件
                file.write(f"************FOTA 开始升级开始 :{FOTA_AT_CMD}************\n")
            file.close()
            write_serial(serial_port,FOTA_AT_CMD)
            read_msg = serial_port.readall()
            print('Readdata: {}'.format(read_msg))  
            # Define the check_version_after_delay function, passing in the lock object
            # Create the timer, passing in the lock object
            timer = threading.Timer(400, check_version_after_delay, args=(lock, serial_port, VERSION_CHECK, start_version,end_version,workbook,worksheet, row_number, RESULTS_COLUMN))
            timer.start()
            '''
            #log 退出
            log_exit_flag = True
            # 等待线程结束
            log_thread.join()
            '''
            thread_exit_control.join()
            httpd_thread.join()
            if check_result == "PASS":
                print("升级成功")
            parameter_read(serial_port,parameter_file,number)
            print("**************************OTA_UPGTADE End*********************************************")
    # 关闭 Excel 文件
    workbook.close()
    serial_port.close()
    
if __name__ == '__main__':
    # 获取终端输入参数，参数1：项目名称，例如GV350CEU，参数2：OTA 升级次数
    CMD_ATE1="ATE1"
    project_name = sys.argv[1].upper()
    project_file_name = sys.argv[1].upper()
    folder_path = r'E:\AutoTest\FOTA'
    if not os.path.exists(os.path.join(folder_path, f'{project_name}LOG')):
        os.makedirs(os.path.join(folder_path, f'{project_name}LOG'))
        print("文件夹创建成功！")
    else:
        print("文件夹已存在，无需创建。")

    number = int(sys.argv[2])     
    if project_name in ["GV58CEU", "GV350CEU", "GV355CEU", "GV305CEU", "GB100CG", "GV50CG", "GV300CAN"]:
        stroge_size = "M128"
    if project_name in ["GV300CEU_TZA"]:
        project_file_name ="GV300CEU"
        stroge_size = "M128_XMC_TZA"
    elif project_name in ["GV310LAU", "GV58LAU"]:
        stroge_size = "M1024_WBD"
    elif project_name == "GV350CEU_MOB":
        stroge_size = "M1024_MOB"
    elif project_name == "GL33":
        stroge_size = "N32"
    else:
        stroge_size = "M128"

    dowload_file(project_name, stroge_size)
    Diff_Package(project_name, stroge_size)
    # 创建参数文件
    now = datetime.datetime.now()
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
    filename = f"E:\AutoTest\FOTA\{project_name}LOG\{project_name}_parameter{timestamp}.txt"
    while number > 0:
        # 判断串口是否存在
        serial_port = open_serial_port()
        if serial_port:
            print(f"Serial port {serial_port.name} opened successfully")
        else:
            print("No suitable serial port found.")
            sys.exit(1)
        OTA_UPGTADE(project_name, stroge_size, serial_port, number)
        number -= 1
    serial_port.write(CMD_ATE1.encode()+b'\r\n')

    


























