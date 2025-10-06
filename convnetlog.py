import sys
import pathlib
import re
import xml.etree.ElementTree as et
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QTextEdit, QPushButton, QFileDialog, QLabel,
    QFrame, QMessageBox, QHeaderView, QListWidget, QListWidgetItem
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette

class ConvertWorker(QThread):
    log = pyqtSignal(str)       # 更新底部日志窗口的信息
    finished_all = pyqtSignal() # 全部完成

    def __init__(self, devices, save_path, parent=None):
        super().__init__(parent)
        self.devices = devices
        self.save_path = save_path
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            for device in self.devices:
                if self._stopped:
                    break
                try:
                    path = pathlib.Path(device["path"])
                    cmds_result_path = path.parent.joinpath("cmdsResult", "network")
                    if cmds_result_path.exists():
                        for p in cmds_result_path.iterdir():
                            if re.fullmatch(r"ssh_\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}_[-0-9a-zA-Z_]*\.xml", p.name):
                                self.log.emit(f"转换文件: {p.name}")
                                tree = et.parse(p)
                                root = tree.getroot()
                                # 构建父节点映射
                                parent_map = {c: pa for pa in root.iter() for c in pa}
                                file_name = pathlib.Path(self.save_path).joinpath(f"{device['name']}.log")
                                with open(file_name, "w", encoding="utf-8") as f:
                                    for cmd_elem in root.findall(".//command"):
                                        if cmd_elem.text:
                                            echo_text = ""
                                            parent = parent_map.get(cmd_elem)
                                            if parent is not None:
                                                children = list(parent)
                                                for idx, child in enumerate(children):
                                                    if child == cmd_elem and idx + 1 < len(children):
                                                        next_elem = children[idx + 1]
                                                        if next_elem.tag == "echo":
                                                            echo_text = next_elem.text.strip() if next_elem.text else ""
                                                            echo_list = echo_text.split("\n")
                                                            f.write(f"#\n<{device['name']}>{cmd_elem.text}\n")
                                                            for line in echo_list[1:len(echo_list) - 1]:
                                                                f.write(f"{line}\n")
                except Exception as e:
                    self.log.emit(f"转换文件格式时出错: {str(e)}")
        finally:
            self.finished_all.emit()

class NetLogHiveGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.device_list = []
        self.current_device = None
        self.current_device_commands = {}
        self.save_log_path = ""
        self.init_ui()
        self._centered = False
        self._convert_thread = None
        
    def init_ui(self):
        self.setWindowTitle("H3C标杆神器网络日志查看转换工具")
        self.setGeometry(100, 100, 1400, 900)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 顶部工具栏
        self.create_toolbar(main_layout)
        
        # 主要内容区域 - 使用QSplitter实现可调整大小的布局
        self.content_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.content_splitter, 1)  # 设置拉伸因子为1，占据剩余空间
        
        # 左侧设备列表
        self.create_device_list(self.content_splitter)
        
        # 中间命令列表
        self.create_command_list(self.content_splitter)
        
        # 右侧结果显示
        self.create_result_display(self.content_splitter)
        
        # 底部日志窗口
        self.create_log_window(main_layout)
        
        # 设置分割器的初始大小比例
        self.content_splitter.setSizes([400, 300, 700])
        
        # 设置分割器手柄样式
        self.content_splitter.setHandleWidth(3)
        self.content_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #cccccc;
                border: 1px solid #999999;
            }
            QSplitter::handle:hover {
                background-color: #aaaaaa;
            }
        """)
        
        # 设置窗口最小大小
        self.setMinimumSize(800, 600)
        
        # 连接窗口大小变化信号
        self.resizeEvent = self.on_resize_event
        
    def _keep_selection_visible(self, widget):
        """让列表/表格在失去焦点时仍保持选中高亮"""
        pal = widget.palette()
        pal.setBrush(QPalette.Inactive, QPalette.Highlight, pal.brush(QPalette.Active, QPalette.Highlight))
        pal.setBrush(QPalette.Inactive, QPalette.HighlightedText, pal.brush(QPalette.Active, QPalette.HighlightedText))
        pal.setBrush(QPalette.Disabled, QPalette.Highlight, pal.brush(QPalette.Active, QPalette.Highlight))
        pal.setBrush(QPalette.Disabled, QPalette.HighlightedText, pal.brush(QPalette.Active, QPalette.HighlightedText))
        widget.setPalette(pal)
        
    def create_toolbar(self, main_layout):
        """创建顶部工具栏"""
        toolbar_layout = QHBoxLayout()
        
        # 路径选择
        path_label = QLabel("采集日志路径:")
        self.path_display = QLabel("未选择路径")
        self.path_display.setStyleSheet("border: 1px solid #ccc; padding: 5px; background: #f9f9f9;")
        self.path_display.setMinimumWidth(400)
        
        self.select_h3clog_path_btn = QPushButton("选择路径")
        self.select_h3clog_path_btn.clicked.connect(self.select_h3clog_path)
        
        # 格式转换按钮
        self.convert_format_btn = QPushButton("格式转换")
        self.convert_format_btn.clicked.connect(self.convert_format)
        self.convert_format_btn.setEnabled(False)
        
        toolbar_layout.addWidget(path_label)
        toolbar_layout.addWidget(self.path_display)
        toolbar_layout.addWidget(self.select_h3clog_path_btn)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.convert_format_btn)
        
        main_layout.addLayout(toolbar_layout)
        
    def create_device_list(self, content_layout):
        """创建左侧设备列表"""
        device_frame = QFrame()
        device_frame.setFrameStyle(QFrame.Box)
        device_layout = QVBoxLayout(device_frame)
        
        device_title = QLabel("设备列表")
        device_title.setFont(QFont("Arial", 11, QFont.Bold))
        device_layout.addWidget(device_title)
        
        # 使用QTableWidget替代QListWidget
        self.device_table = QTableWidget()
        self.device_table.setColumnCount(4)
        self.device_table.setHorizontalHeaderLabels(["设备名称", "IP地址", "SN号", "状态"])
        
        # 设置表格属性
        self.device_table.setSelectionBehavior(QTableWidget.SelectRows)  # 整行选择
        self.device_table.setAlternatingRowColors(True)  # 交替行颜色
        self.device_table.setSortingEnabled(True)  # 启用排序
        
        # 让失焦后仍保持高亮
        self._keep_selection_visible(self.device_table)
        
        # 设置列宽
        header = self.device_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # 设备名称列自适应内容宽度
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # IP地址列自适应内容
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # SN号列自适应内容
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # 状态列自适应内容
        
        # 启用列宽调整
        header.setStretchLastSection(False)  # 禁用最后一列自动拉伸
        header.setSectionsMovable(False)     # 禁用列移动
        header.setSectionsClickable(True)    # 启用列头点击排序
        
        # 连接信号
        self.device_table.itemClicked.connect(self.on_device_selected)
        
        device_layout.addWidget(self.device_table)
        
        # 添加到分割器，设置拉伸因子为1
        content_layout.addWidget(device_frame)
        
    def create_command_list(self, content_layout):
        """创建中间命令列表"""
        command_frame = QFrame()
        command_frame.setFrameStyle(QFrame.Box)
        command_layout = QVBoxLayout(command_frame)
        
        command_title = QLabel("命令列表")
        command_title.setFont(QFont("Arial", 11, QFont.Bold))
        command_layout.addWidget(command_title)
        
        self.command_list_widget = QListWidget()
        # 让失焦后仍保持高亮
        self._keep_selection_visible(self.command_list_widget)
        self.command_list_widget.itemClicked.connect(self.on_command_selected)
        command_layout.addWidget(self.command_list_widget)
        
        # 添加到分割器
        content_layout.addWidget(command_frame)
        
    def create_result_display(self, content_layout):
        """创建右侧结果显示"""
        result_frame = QFrame()
        result_frame.setFrameStyle(QFrame.Box)
        result_layout = QVBoxLayout(result_frame)
        
        result_title = QLabel("执行结果")
        result_title.setFont(QFont("Arial", 11, QFont.Bold))
        result_layout.addWidget(result_title)
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)
        
        # 添加到分割器
        content_layout.addWidget(result_frame)
        
    def create_log_window(self, main_layout):
        """创建底部运行信息窗口"""
        log_frame = QFrame()
        log_frame.setFrameStyle(QFrame.Box)
        log_layout = QVBoxLayout(log_frame)
        
        log_title = QLabel("运行信息窗口")
        log_title.setFont(QFont("Arial", 11, QFont.Bold))
        log_layout.addWidget(log_title)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        
        main_layout.addWidget(log_frame)
        
    def parse_path(self, dirname):
        """解析路径获取设备列表"""
        path = pathlib.Path(dirname)
        for p in path.iterdir():
            if p.is_dir():
                if re.fullmatch(r"BrainCollect", p.name):
                    # 获取所有子目录及其日期时间
                    subdirs = [d for d in p.iterdir() if d.is_dir() and re.fullmatch(r"result_\d{18}", d.name)]
                    latest_dir = None
                    latest_dt = None
                    for d in subdirs:
                        dt_str = d.name[7:20]  # 第8到20个字符（索引7到19）
                        try:
                            dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
                            if latest_dt is None or dt > latest_dt:
                                latest_dt = dt
                                latest_dir = d
                        except Exception as e:
                            continue
                    if latest_dir:
                        # 只遍历最新子目录
                        self.parse_path(str(latest_dir))
                    continue  # 不再递归BrainCollect本身
                else:
                    self.parse_path(p)
            else:
                # 匹配cmd_info_*.xml文件
                if re.fullmatch(r"cmd_info_\d{14}\.xml", p.name):
                    try:
                        tree = et.parse(p)
                        root = tree.getroot()
                        for device in root.findall("device"):
                            name_elem = device.find("name")
                            ip_elem = device.find("ip")
                            sn_elem = device.find("sn")
                            state_elem = device.find("state")
                            
                            # 检查元素是否存在且不为None
                            if (name_elem is not None and name_elem.text and
                                ip_elem is not None and ip_elem.text and
                                sn_elem is not None and sn_elem.text and
                                state_elem is not None and state_elem.text):
                                
                                # 保存唯一设备信息
                                device_info = {}
                                device_info["name"] = name_elem.text.strip()
                                device_info["ip"] = ip_elem.text.strip()
                                device_info["sn"] = sn_elem.text.strip()
                                device_info["state"] = state_elem.text.strip()
                                device_info["path"] = str(p.resolve())
                                
                                # 检查是否已存在相同设备（避免重复）
                                existing_device = None
                                for existing in self.device_list:
                                    if (existing["name"] == device_info["name"] and 
                                        existing["ip"] == device_info["ip"] and 
                                        existing["sn"] == device_info["sn"]):
                                        existing_device = existing
                                        break
                                
                                if existing_device is None:
                                    self.device_list.append(device_info)
                                    self.log_message(f"发现设备: {device_info['name']} - {device_info['ip']} - {device_info['sn']} - {device_info['state']}")
                                else:
                                    self.log_message(f"设备已存在，跳过: {device_info['name']} - {device_info['ip']}")
                                    
                    except Exception as e:
                        self.log_message(f"解析文件 {p} 时出错: {e}")

    def select_h3clog_path(self):
        """选择采集日志文件路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "采集日志文件目录")
        if dir_path:
            self.path_display.setText(dir_path)
            self.log_message(f"已选择采集日志文件路径: {dir_path}")
            
            # 解析路径获取设备列表
            try:
                # 清空设备列表
                self.device_list.clear()
                
                # 调用parse_path函数
                self.parse_path(dir_path)
                
                # 更新设备列表显示
                self.update_device_list()
                self.convert_format_btn.setEnabled(True)
                self.log_message(f"成功解析路径，发现 {len(self.device_list)} 个设备")
            except Exception as e:
                self.log_message(f"解析路径时出错: {str(e)}")
                
    def update_device_list(self):
        """更新设备列表显示"""
        # 暂时禁用排序以避免更新时的排序问题
        self.device_table.setSortingEnabled(False)
        
        # 清空表格
        self.device_table.setRowCount(0)
        
        # 添加设备数据
        for row, device in enumerate(self.device_list):
            self.device_table.insertRow(row)
            
            # 创建设备名称项
            name_item = QTableWidgetItem(device['name'])
            name_item.setData(Qt.UserRole, device)  # 存储设备数据
            
            # 创建IP地址项
            ip_item = QTableWidgetItem(device['ip'])
            
            # 创建SN号项
            sn_item = QTableWidgetItem(device['sn'])
            
            # 创建状态项
            state_item = QTableWidgetItem(device['state'])
            
            # 设置单元格内容
            self.device_table.setItem(row, 0, name_item)
            self.device_table.setItem(row, 1, ip_item)
            self.device_table.setItem(row, 2, sn_item)
            self.device_table.setItem(row, 3, state_item)
            
            # 如果状态不是"成功"，设置整行红色字体
            if device['state'] != "成功":
                for col in range(4):
                    item = self.device_table.item(row, col)
                    if item:
                        item.setForeground(QColor(255, 0, 0))
                  
        # 重新启用排序
        self.device_table.setSortingEnabled(True)
        
        # 调整列宽以适应内容
        self.device_table.resizeColumnsToContents()
        
                    
    def on_device_selected(self, item):
        """设备选择事件"""
        # 获取选中的行
        row = item.row()
        # 从第一列获取设备数据
        device_item = self.device_table.item(row, 0)
        if device_item:
            device = device_item.data(Qt.UserRole)
            self.current_device = device
            self.log_message(f"已选择设备: {device['name']}")
            
            # 更新命令列表
            self.update_command_list(device)
            # 清空结果列表
            self.result_text.setText("")
        
    def update_command_list(self, device):
        """更新命令列表"""
        self.command_list_widget.clear()
        
        try:
            # 解析设备的结果文件获取命令列表
            commands = self.get_device_commands(device)
            self.current_device_commands = commands
            
            for cmd in commands:
                item = QListWidgetItem(cmd)
                self.command_list_widget.addItem(item)
                
        except Exception as e:
            self.log_message(f"获取设备命令列表时出错: {str(e)}")
            
    def get_device_commands(self, device):
        """获取设备的命令列表"""
        commands = []
        try:
            path = pathlib.Path(device['path'])
            cmds_result_path = path.parent.joinpath("cmdsResult", "network")
            
            if cmds_result_path.exists():
                for p in cmds_result_path.iterdir():
                    if re.fullmatch(r"ssh_\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}_[-0-9a-zA-Z_]*\.xml", p.name):
                        tree = et.parse(p)
                        root = tree.getroot()
                        for cmd_elem in root.findall(".//command"):
                            if cmd_elem.text and cmd_elem.text not in commands:
                                commands.append(cmd_elem.text)
        except Exception as e:
            self.log_message(f"解析设备命令时出错: {str(e)}")
            
        return commands
        
    def on_command_selected(self, item):
        """命令选择事件"""
        if not self.current_device:
            return
            
        command = item.text()
        self.log_message(f"已选择命令: {command}")
        
        # 显示命令执行结果
        self.display_command_result(command)
        
    def display_command_result(self, command):
        """显示命令执行结果"""
        try:
            result = ""
            path = pathlib.Path(self.current_device['path'])
            cmds_result_path = path.parent.joinpath("cmdsResult", "network")
            
            if cmds_result_path.exists():
                for p in cmds_result_path.iterdir():
                    if re.fullmatch(r"ssh_\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}_[-0-9a-zA-Z_]*\.xml", p.name):
                        tree = et.parse(p)
                        root = tree.getroot()
                        
                        # 构建父节点映射
                        parent_map = {c: p for p in root.iter() for c in p}
                        
                        for cmd_elem in root.findall(".//command"):
                            if cmd_elem.text and cmd_elem.text == command:
                                # 查找紧跟的echo标签
                                echo_text = ""
                                parent = parent_map.get(cmd_elem)
                                if parent is not None:
                                    children = list(parent)
                                    for idx, child in enumerate(children):
                                        if child == cmd_elem and idx + 1 < len(children):
                                            next_elem = children[idx + 1]
                                            if next_elem.tag == "echo":
                                                echo_text = next_elem.text.strip() if next_elem.text else ""
                                                break
                                
                                result += f"命令: {command}\n"
                                result += f"执行结果:\n{echo_text}\n"
                                result += "-" * 50 + "\n"
                                                                
            if result:
                self.result_text.setText(result)
            else:
                self.result_text.setText("未找到该命令的执行结果")
                
        except Exception as e:
            self.log_message(f"显示命令结果时出错: {str(e)}")
            self.result_text.setText(f"显示结果时出错: {str(e)}")
    
    def save_commands_result(self, device):
        try:
            path = pathlib.Path(device["path"])
            cmds_result_path = path.parent.joinpath("cmdsResult", "network")
            
            if cmds_result_path.exists():
                for p in cmds_result_path.iterdir():
                    if re.fullmatch(r"ssh_\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}_[-0-9a-zA-Z_]*\.xml", p.name):
                        self.log_message(f"转换文件: {p.name}")
                        tree = et.parse(p)
                        root = tree.getroot()
                        # 构建父节点映射
                        parent_map = {c: p for p in root.iter() for c in p}
                        file_name = pathlib.Path(self.save_log_path).joinpath(f"{device['name']}.log")
                        f = open(file_name, "w", encoding="utf-8")
                        for cmd_elem in root.findall(".//command"):
                            if cmd_elem.text:
                                 # 查找紧跟的echo标签
                                echo_text = ""
                                parent = parent_map.get(cmd_elem)
                                if parent is not None:
                                    children = list(parent)
                                    for idx, child in enumerate(children):
                                        if child == cmd_elem and idx + 1 < len(children):
                                            next_elem = children[idx + 1]
                                            if next_elem.tag == "echo":
                                                echo_text = next_elem.text.strip() if next_elem.text else ""
                                                echo_list = echo_text.split("\n")
                                                f.write(f"#\n<{device['name']}>{cmd_elem.text}\n")
                                                for line in echo_list[1:len(echo_list) - 1]:
                                                    f.write(f"{line}\n")
                        f.close()
        except Exception as e:
            self.log_message(f"转换文件格式时出错: {str(e)}")
        

        
    def convert_format(self):
        """格式转换"""
        if not self.device_list:
            QMessageBox.warning(self, "警告", "请先选择日志文件保存路径")
            return
            
        """选择格式转换后的日志文件路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择日志文件保存目录")
        if dir_path:
            self.log_message(f"已选择日志文件保存路径: {dir_path}")
            self.save_log_path = dir_path
            # 禁用按钮防止重复点击
            self.convert_format_btn.setEnabled(False)
            
            # 启动后台线程
            self._convert_thread = ConvertWorker(self.device_list.copy(), self.save_log_path)
            self._convert_thread.log.connect(self.log_message)
            self._convert_thread.finished_all.connect(self.on_convert_finished)
            self._convert_thread.start()
        
      
    def on_convert_finished(self):
        self.convert_format_btn.setEnabled(True)
        self.log_message("所有日志文件格式转换完成")
        self._convert_thread = None
        
    def log_message(self, message):
        """添加日志消息（带时间戳和异常详细信息）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 如果是异常对象，自动补充traceback
        if isinstance(message, Exception):
            import traceback
            details = traceback.format_exc()
            log_entry = f"[{timestamp}] 错误: {str(message)}\n{details}"
        else:
            log_entry = f"[{timestamp}] {message}"
        self.log_text.append(log_entry)
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    
    def on_resize_event(self, event):
        """窗口大小变化事件处理"""
        # 调用父类的resizeEvent
        super().resizeEvent(event)
        
        # 获取新的窗口大小
        new_size = event.size()
        window_height = new_size.height()
        
        # 计算日志窗口的最大高度（窗口高度的三分之一）
        max_log_height = int(window_height / 3)
        
        # 调整日志窗口高度
        if hasattr(self, 'log_text'):
            current_height = self.log_text.height()
            if current_height > max_log_height:
                self.log_text.setFixedHeight(max_log_height)
        
        # 更新分割器大小比例
        if hasattr(self, 'content_splitter'):
            # 保持设备列表、命令列表、结果窗口的相对比例
            total_width = new_size.width()
            device_width = int(total_width * 0.25)  # 25%
            command_width = int(total_width * 0.25)  # 25%
            result_width = total_width - device_width - command_width - 6  # 减去分割器手柄宽度
            
            self.content_splitter.setSizes([device_width, command_width, result_width])

    def center_on_screen(self):
        """首次显示时，将窗口移动到当前屏幕中心"""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_centered', False):
            self.center_on_screen()
            self._centered = True

def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    # 创建主窗口
    window = NetLogHiveGUI()
    window.show()
    
    # 运行应用程序
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()