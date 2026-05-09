import sys
import os
import json
import requests
import sqlite3
import threading
import random
import time
import re
import string
import secrets
import configparser
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QFrame, QSplitter, QGroupBox, QFormLayout, QCheckBox, QRadioButton, QTextEdit, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor, QAction, QCursor
from PyQt6.QtGui import QClipboard

from google.cloud import compute_v1
from google.api_core.exceptions import GoogleAPIError

# =============================================================================
# 全局常量配置
# =============================================================================
DEFAULT_MACHINE_TYPE = "e2-micro"
DEFAULT_IMAGE_FAMILY = "projects/ubuntu-os-cloud/global/images/family/ubuntu-minimal-2204-lts"
DEFAULT_DISK_TYPE = "pd-standard"
DEFAULT_DISK_SIZE_GB = 30
DEFAULT_NETWORK = "global/networks/default"
DEFAULT_SUBNET = "regions/{region}/subnetworks/default"
NETWORK_TIER = "STANDARD"
MAX_WORKERS = 3
DELETE_TIMEOUT = 300

FREE_REGIONS = {
    "us-central1 (爱荷华)": "us-central1",
    "us-east1 (南卡罗来纳)": "us-east1",
    "us-west1 (俄勒冈)": "us-west1"
}

PAID_REGIONS = {
    # 美国 (US)
    "us-central2 (达拉斯)": "us-central2", "us-east2 (俄亥俄)": "us-east2",
    "us-east3 (南卡罗来纳)": "us-east3", "us-east4 (北弗吉尼亚)": "us-east4",
    "us-east5 (俄亥俄)": "us-east5", "us-west2 (洛杉矶)": "us-west2",
    "us-west3 (盐湖城)": "us-west3", "us-west4 (拉斯维加斯)": "us-west4",
    "us-south1 (德克萨斯)": "us-south1",
    # 亚洲 (Asia)
    "asia-east1 (台湾)": "asia-east1", "asia-east2 (香港)": "asia-east2",
    "asia-northeast1 (东京)": "asia-northeast1", "asia-northeast2 (大阪)": "asia-northeast2",
    "asia-northeast3 (首尔)": "asia-northeast3", "asia-south1 (孟买)": "asia-south1",
    "asia-south2 (德里)": "asia-south2", "asia-southeast1 (新加坡)": "asia-southeast1",
    "asia-southeast2 (雅加达)": "asia-southeast2",
    # 欧洲 (Europe)
    "europe-west1 (比利时)": "europe-west1", "europe-west2 (伦敦)": "europe-west2",
    "europe-west3 (法兰克福)": "europe-west3", "europe-west4 (荷兰)": "europe-west4",
    "europe-west6 (苏黎世)": "europe-west6", "europe-west8 (米兰)": "europe-west8",
    "europe-west9 (巴黎)": "europe-west9", "europe-west10 (柏林)": "europe-west10",
    "europe-west12 (都灵)": "europe-west12", "europe-central2 (华沙)": "europe-central2",
    "europe-north1 (芬兰)": "europe-north1", "europe-southwest1 (马德里)": "europe-southwest1",
    # 其他 (Others)
    "australia-southeast1 (悉尼)": "australia-southeast1", "australia-southeast2 (墨尔本)": "australia-southeast2",
    "me-central1 (多哈)": "me-central1", "me-central2 (利雅得)": "me-central2",
    "me-west1 (特拉维夫)": "me-west1", "southamerica-east1 (圣保罗)": "southamerica-east1",
    "southamerica-west1 (圣地亚哥)": "southamerica-west1",
    "northamerica-northeast1 (蒙特利尔)": "northamerica-northeast1",
    "northamerica-northeast2 (多伦多)": "northamerica-northeast2",
}

ZONE_OPTIONS = {
    "us-central1": ["us-central1-a", "us-central1-b", "us-central1-c", "us-central1-f"],
    "us-east1": ["us-east1-b", "us-east1-c", "us-east1-d"],
    "us-west1": ["us-west1-a", "us-west1-b", "us-west1-c"]
}

# 合法代理正则校验
PROXY_REGEX = re.compile(r'^(\d{1,3}\.){3}\d{1,3}:\d{1,5}(:.*){0,2}$')

SUPPORTED_PROXY_FORMATS = [
    "http:IP:PORT:USER:PASS",
    "https:IP:PORT:USER:PASS",
    "socks:IP:PORT:USER:PASS",
    "socks5:IP:PORT:USER:PASS",
    "http://USER:PASS@IP:PORT",
    "https://USER:PASS@IP:PORT",
    "socks://USER:PASS@IP:PORT",
    "socks5://USER:PASS@IP:PORT"
]


def proxy_formats_help_text():
    return "支持的代理格式：\n" + "\n".join(SUPPORTED_PROXY_FORMATS)


def parse_proxy_input(proxy_text, fallback_proxy_type=None, require_protocol=False):
    proxy_text = (proxy_text or "").strip()
    if not proxy_text:
        return {'ok': True, 'empty': True, 'proxy_type': fallback_proxy_type or 'HTTPS', 'proxy_url': ''}

    lower = proxy_text.lower()
    protocol = None
    rest = proxy_text

    scheme_map = {
        'socks5://': 'SOCKS5',
        'socks://': 'SOCKS5',
        'http://': 'HTTPS',
        'https://': 'HTTPS',
        'socks5:': 'SOCKS5',
        'socks:': 'SOCKS5',
        'http:': 'HTTPS',
        'https:': 'HTTPS',
    }

    for prefix, mapped_type in scheme_map.items():
        if lower.startswith(prefix):
            protocol = mapped_type
            rest = proxy_text[len(prefix):]
            break

    if '@' in rest:
        user_pass, host_port = rest.rsplit('@', 1)
        host_parts = host_port.split(':')
        if len(host_parts) < 2 or not host_parts[0] or not host_parts[1]:
            return {'ok': False, 'error': f"无法识别代理类型或地址\n{proxy_formats_help_text()}"}
        ip = host_parts[0].strip()
        port = host_parts[1].strip()
        up_parts = user_pass.split(':')
        if not up_parts or not up_parts[0]:
            return {'ok': False, 'error': f"无法识别代理账号信息\n{proxy_formats_help_text()}"}
        user = up_parts[0].strip()
        password = ':'.join(up_parts[1:]).strip() if len(up_parts) > 1 else ''
    else:
        parts = rest.split(':')
        if protocol is None:
            if require_protocol:
                return {'ok': False, 'error': f"无法识别代理类型，请在代理信息中带上协议前缀\n{proxy_formats_help_text()}"}
            protocol = fallback_proxy_type or 'HTTPS'
        if len(parts) < 4:
            return {'ok': False, 'error': f"代理格式不正确\n{proxy_formats_help_text()}"}
        ip = parts[0].strip()
        port = parts[1].strip()
        user = parts[2].strip()
        password = ':'.join(parts[3:]).strip()

    if not ip or not port or not user:
        return {'ok': False, 'error': f"代理信息不完整\n{proxy_formats_help_text()}"}

    proxy_type = protocol or fallback_proxy_type or 'HTTPS'
    scheme = 'socks5' if proxy_type == 'SOCKS5' else 'http'
    proxy_url = f"{scheme}://{user}:{password}@{ip}:{port}"
    return {
        'ok': True,
        'empty': False,
        'proxy_type': proxy_type,
        'proxy_url': proxy_url,
        'ip': ip,
        'port': port,
        'user': user,
        'password': password,
        'normalized_input': proxy_text
    }


# =============================================================================
# 配置管理器
# =============================================================================
class ConfigManager:
    def __init__(self):
        self.config_dir = os.path.join(os.environ.get('APPDATA'), 'XiaoLong')
        self.json_file = os.path.join(self.config_dir, 'nezha_config.json')
        self.ini_file = os.path.join(self.config_dir, 'GCP_Manager_v3.4.ini')
        self.config = configparser.ConfigParser()
        os.makedirs(self.config_dir, exist_ok=True)

    def load_json(self):
        if os.path.exists(self.json_file):
            try:
                with open(self.json_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_json(self, data):
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_layout(self):
        if os.path.exists(self.ini_file):
            try:
                self.config.read(self.ini_file, encoding='utf-8')
            except:
                pass

    def save_layout(self, data):
        self.config['Layout'] = data
        with open(self.ini_file, 'w', encoding='utf-8') as f:
            self.config.write(f)


# =============================================================================
# 哪吒监控API（100%适配你的面板：{"success":true,"data":[...]}）
# =============================================================================
class NezhaAPI:
    def __init__(self, panel_url, jwt_token):
        self.panel_url = panel_url.rstrip('/')  # 自动去除结尾/
        self.jwt_token = self._parse_token(jwt_token)
        # 会话配置（防卡死）
        self.session = requests.Session()
        self.session.timeout = 15
        self.session.headers = {
            "Cookie": f"nz-jwt={self.jwt_token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }

    def _parse_token(self, token_input):
        """解析Token：自动去掉nz-jwt=前缀"""
        if not token_input:
            return ""
        token = token_input.strip()
        return token.split('nz-jwt=')[-1].split(';')[0].strip() if 'nz-jwt=' in token else token

    def get_server_list(self):
        """修复布尔值判断，精准解析你的面板JSON"""
        try:
            # 发送请求
            resp = self.session.get(f"{self.panel_url}/api/v1/server")
            resp.encoding = 'utf-8'

            # 校验状态码
            if resp.status_code != 200:
                return False, f"面板接口返回错误：{resp.status_code}"

            # 解析JSON（你的面板是标准JSON）
            data = resp.json()

            # 修复核心问题：兼容success的布尔值类型（True/true）
            success_flag = data.get('success')
            # 同时兼容Python布尔值True和JSON字符串"true"
            if isinstance(data, dict) and (success_flag is True or success_flag == "true"):
                server_list = data.get('data', [])
                return True, server_list
            else:
                return False, f"面板返回success字段异常：{success_flag}"

        except requests.exceptions.ConnectionError:
            return False, "无法连接面板，请检查地址/网络"
        except requests.exceptions.Timeout:
            return False, "面板响应超时（15秒）"
        except json.JSONDecodeError:
            return False, "面板返回非标准JSON格式"
        except Exception as e:
            return False, f"未知错误：{str(e)}"


class NezhaFetcher(QThread):
    finished = pyqtSignal(dict, str)

    def __init__(self, panel_url, jwt_token):
        super().__init__()
        self.panel_url = panel_url
        self.jwt_token = jwt_token

    def run(self):
        """精准提取：geoip.ip.ipv4_addr → name 映射"""
        try:
            api = NezhaAPI(self.panel_url, self.jwt_token)
            success, server_list = api.get_server_list()

            if not success:
                self.finished.emit({}, str(server_list))
                return

            # 构建IP-名称映射（完全匹配你的面板字段）
            ip_name_map = {}
            for server in server_list:
                # 提取IP：固定路径 geoip → ip → ipv4_addr
                ipv4 = server.get('geoip', {}).get('ip', {}).get('ipv4_addr', '').strip()
                # 提取名称：固定字段 name
                name = server.get('name', '未知服务器').strip()

                # 只保留有效IP
                if ipv4 and re.match(r'^(\d{1,3}\.){3}\d{1,3}$', ipv4):
                    ip_name_map[ipv4] = name

            # 输出调试信息（方便你核对）
            print(f"✅ 匹配到{len(ip_name_map)}台服务器：{ip_name_map}")
            self.finished.emit(ip_name_map, "OK")

        except Exception as e:
            self.finished.emit({}, f"解析失败：{str(e)}")


# =============================================================================
# 数据库（线程安全）
# =============================================================================
class AccountDB:
    def __init__(self, db_path="accounts.db"):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_table()

    def create_table(self):
        with self.lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT, project_id TEXT, key_path TEXT,
                    proxy TEXT DEFAULT '', proxy_type TEXT DEFAULT 'HTTPS'
                )
            """)
            self.conn.commit()

    def add_account(self, email, project_id, key_path, proxy='', proxy_type='HTTPS'):
        with self.lock:
            self.conn.execute(
                "INSERT INTO accounts VALUES (NULL,?,?,?,?,?)",
                (email, project_id, key_path, proxy, proxy_type)
            )
            self.conn.commit()

    def delete_account(self, acc_id):
        with self.lock:
            self.conn.execute("DELETE FROM accounts WHERE id=?", (acc_id,))
            self.conn.commit()

    def update_account(self, acc_id, proxy=None, proxy_type=None):
        with self.lock:
            if proxy is not None:
                self.conn.execute("UPDATE accounts SET proxy=? WHERE id=?", (proxy, acc_id))
            if proxy_type is not None:
                self.conn.execute("UPDATE accounts SET proxy_type=? WHERE id=?", (proxy_type, acc_id))
            self.conn.commit()

    def get_all(self):
        with self.lock:
            return self.conn.execute("SELECT * FROM accounts").fetchall()

    def get_by_id(self, acc_id):
        with self.lock:
            return self.conn.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()


# =============================================================================
# 代理上下文管理器（修复：非法代理自动跳过）
# =============================================================================
class ProxyEnvContext:
    def __init__(self, proxy_url):
        self.proxy_url = proxy_url
        self.old = {}

    def __enter__(self):
        # 空代理/非法代理 直接不启用
        if not self.proxy_url or len(self.proxy_url) < 5:
            return self
        self.old = {
            'HTTP_PROXY': os.environ.get('HTTP_PROXY'),
            'HTTPS_PROXY': os.environ.get('HTTPS_PROXY'),
            'ALL_PROXY': os.environ.get('ALL_PROXY')
        }
        os.environ['HTTP_PROXY'] = self.proxy_url
        os.environ['HTTPS_PROXY'] = self.proxy_url
        if self.proxy_url.startswith('socks'):
            os.environ['ALL_PROXY'] = self.proxy_url
        return self

    def __exit__(self, *args):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# =============================================================================
# GCP核心服务（修复：代理强校验，非法代理自动忽略）
# =============================================================================
class GCPService:
    def __init__(self, key_path, project_id, email, proxy='', proxy_type='HTTPS'):
        self.key_path = key_path
        self.project_id = project_id
        self.email = email
        self.proxy_url = self._parse_proxy_safe(proxy, proxy_type)
        self.instance_client = compute_v1.InstancesClient.from_service_account_json(key_path)
        self.firewall_client = compute_v1.FirewallsClient.from_service_account_json(key_path)
        self.project_client = compute_v1.ProjectsClient.from_service_account_json(key_path)

    # 安全解析代理：统一复用全局解析逻辑
    def _parse_proxy_safe(self, proxy, proxy_type):
        parsed = parse_proxy_input(proxy, fallback_proxy_type=proxy_type, require_protocol=False)
        return parsed.get('proxy_url', '') if parsed.get('ok') else ""

    def _with_proxy(self, func):
        with ProxyEnvContext(self.proxy_url):
            return func()

    def add_ssh_key(self, pub_key):
        def run():
            meta = self.project_client.get(project=self.project_id).common_instance_metadata
            key_line = f"root:{pub_key.strip()}"
            ssh_item = next((i for i in meta.items if i.key.lower() == "ssh-keys"), None)
            if not ssh_item:
                meta.items.append(compute_v1.Items(key="ssh-keys", value=key_line))
            elif key_line not in ssh_item.value:
                ssh_item.value += "\n" + key_line
            self.project_client.set_common_instance_metadata(project=self.project_id, metadata_resource=meta).result()
            return True

        try:
            return self._with_proxy(run), "公钥注入成功"
        except Exception as e:
            return False, str(e)

    def create_instance(self, zone, name, startup_script=""):
        def run():
            disk = compute_v1.AttachedDisk(
                boot=True, auto_delete=True,
                initialize_params=compute_v1.AttachedDiskInitializeParams(
                    source_image=DEFAULT_IMAGE_FAMILY, disk_size_gb=DEFAULT_DISK_SIZE_GB,
                    disk_type=f"zones/{zone}/diskTypes/{DEFAULT_DISK_TYPE}"
                )
            )
            nic = compute_v1.NetworkInterface(
                network=DEFAULT_NETWORK, subnetwork=DEFAULT_SUBNET.format(region=zone.rsplit('-', 1)[0]),
                access_configs=[compute_v1.AccessConfig(network_tier=NETWORK_TIER)]
            )
            instance = compute_v1.Instance(
                name=name, machine_type=f"zones/{zone}/machineTypes/{DEFAULT_MACHINE_TYPE}",
                disks=[disk], network_interfaces=[nic]
            )
            if startup_script:
                instance.metadata = compute_v1.Metadata(items=[
                    compute_v1.Items(key="startup-script", value=startup_script)
                ])
            self.instance_client.insert(project=self.project_id, zone=zone, instance_resource=instance).result()
            ip = self.instance_client.get(project=self.project_id, zone=zone, instance=name).network_interfaces[
                0].access_configs[0].nat_i_p
            return True, (ip, zone)

        try:
            return self._with_proxy(run)
        except Exception as e:
            return False, "资源耗尽" if "resource_pool_exhausted" in str(e).lower() else str(e)

    def delete_instance(self, zone, name):
        return self._operate(
            lambda: self.instance_client.delete(project=self.project_id, zone=zone.replace('zones/', ''),
                                                instance=name).result(), "删除")

    def start_instance(self, zone, name):
        return self._operate(
            lambda: self.instance_client.start(project=self.project_id, zone=zone.replace('zones/', ''),
                                               instance=name).result(), "启动")

    def stop_instance(self, zone, name):
        return self._operate(lambda: self.instance_client.stop(project=self.project_id, zone=zone.replace('zones/', ''),
                                                               instance=name).result(), "停止")

    def reset_instance(self, zone, name):
        return self._operate(
            lambda: self.instance_client.reset(project=self.project_id, zone=zone.replace('zones/', ''),
                                               instance=name).result(), "重启")

    def _operate(self, func, act):
        try:
            self._with_proxy(func)
            return True, f"{act}成功"
        except Exception as e:
            return False, f"{act}失败：{str(e)}"

    def list_instances(self):
        def run():
            res = []
            for zone, resp in self.instance_client.aggregated_list(project=self.project_id):
                if resp.instances:
                    for inst in resp.instances:
                        if inst.network_interfaces and inst.network_interfaces[0].access_configs:
                            res.append({
                                'name': inst.name,
                                'ip': inst.network_interfaces[0].access_configs[0].nat_i_p,
                                'zone': zone
                            })
            return res

        return self._with_proxy(run)

    def create_open_firewall_rules(self):
        def make_allow_all():
            allow_all = compute_v1.Allowed()
            allow_all.I_p_protocol = "all"
            return allow_all

        def build_ingress_firewall():
            return compute_v1.Firewall(
                name="allow-all-ingress",
                network=DEFAULT_NETWORK,
                direction="INGRESS",
                priority=1000,
                source_ranges=["0.0.0.0/0"],
                allowed=[make_allow_all()]
            )

        def build_egress_firewall():
            return compute_v1.Firewall(
                name="allow-all-egress",
                network=DEFAULT_NETWORK,
                direction="EGRESS",
                priority=1000,
                destination_ranges=["0.0.0.0/0"],
                allowed=[make_allow_all()]
            )

        def upsert_firewall(rule_name, firewall):
            try:
                self.firewall_client.insert(project=self.project_id, firewall_resource=firewall).result()
                return True, f"{rule_name} 创建成功"
            except Exception as e:
                err = str(e)
                if "already exists" not in err.lower():
                    return False, f"{rule_name} 创建失败：{err}"

                try:
                    self.firewall_client.update(
                        project=self.project_id,
                        firewall=rule_name,
                        firewall_resource=firewall
                    ).result()
                    return True, f"{rule_name} 已存在，已按全开放规则更新"
                except Exception as update_err:
                    return False, f"{rule_name} 已存在但更新失败：{str(update_err)}"

        def run():
            ingress_ok, ingress_msg = upsert_firewall("allow-all-ingress", build_ingress_firewall())
            egress_ok, egress_msg = upsert_firewall("allow-all-egress", build_egress_firewall())

            if ingress_ok and egress_ok:
                return True, f"入站+出站全开放防火墙配置完成 | {ingress_msg} | {egress_msg}"

            return False, f"防火墙配置未完全成功 | {ingress_msg} | {egress_msg}"

        try:
            return self._with_proxy(run)
        except Exception as e:
            return False, f"防火墙创建失败：{str(e)}"


# =============================================================================
# 异步线程
# =============================================================================
class InstanceLoader(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, gcp):
        super().__init__()
        self.gcp = gcp

    def run(self):
        try:
            self.finished.emit(self.gcp.list_instances())
        except Exception as e:
            self.error.emit(str(e))


class InstanceOperator(QThread):
    log = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, gcp, instances, action):
        super().__init__()
        self.gcp = gcp
        self.instances = instances
        self.action = action

    def run(self):
        act_map = {
            'delete': self.gcp.delete_instance,
            'start': self.gcp.start_instance,
            'stop': self.gcp.stop_instance,
            'reset': self.gcp.reset_instance
        }
        func = act_map[self.action]
        action_names = {
            'delete': '删除',
            'start': '启动',
            'stop': '停止',
            'reset': '重启'
        }
        action_name = action_names.get(self.action, self.action)
        for idx, inst in enumerate(self.instances, 1):
            success, msg = func(inst['zone'], inst['name'])
            prefix = '✅' if success else '❌'
            self.log.emit(f"{prefix} 第{idx}台{action_name}{'成功' if success else '失败'} | {inst['name']} | {msg}")
        self.finished.emit()


# =============================================================================
# 主GUI
# =============================================================================
class GCPManagerApp(QMainWindow):
    log_signal = pyqtSignal(str)
    create_btn_signal = pyqtSignal(bool)
    firewall_btn_signal = pyqtSignal(bool)
    refresh_instances_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GCP批量管理工具v3.4 - Root密码模式版 - 渔夫出品 - Telegram：@yufu220")
        self.resize(1250, 880)

        self.config = ConfigManager()
        self.config_file = self.config.ini_file  # 布局配置文件路径
        self.db = AccountDB()
        self.ssh_public_key = ""
        self.ssh_key_filename = "未选择公钥"
        self.current_json_path = None
        self.nezha_ip_map = {}
        self.current_instances = []
        self.instance_password_cache = {}

        self.log_signal.connect(self.append_log)
        self.init_ui()
        self.create_btn_signal.connect(self.create_btn.setEnabled)
        self.firewall_btn_signal.connect(self.firewall_btn.setEnabled)
        self.refresh_instances_signal.connect(self.query_instances)
        self.load_layout_config()
        self.load_nezha_config()
        self.log_signal.emit("✅ 工具启动成功 | v3.4 - Root密码模式 + 保持3.3功能")

    def apply_227_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #f5f7fb;
                color: #222;
                font-size: 13px;
            }
            QFrame {
                background: white;
                border: 1px solid #ddd;
                border-radius: 8px;
            }
            QGroupBox {
                background: white;
                border: 1px solid #ddd;
                border-radius: 8px;
                margin-top: 10px;
                font-weight: bold;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLabel {
                background: transparent;
                border: none;
            }
            QLineEdit, QComboBox {
                background: white;
                border: 1px solid #cfd8dc;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #4c8bf5;
            }
            QTableWidget {
                background: white;
                border: 1px solid #d9d9d9;
                gridline-color: #eceff1;
                selection-background-color: #dbeafe;
                selection-color: #111;
            }
            QHeaderView::section {
                background: #f3f4f6;
                border: none;
                border-bottom: 1px solid #d9d9d9;
                padding: 6px;
                font-weight: bold;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #d0d7de;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: #f3f4f6;
            }
            QPushButton:disabled {
                color: #9aa0a6;
                background: #f1f3f4;
            }
            QTextEdit {
                background-color: #0d1117;
                color: #00ffaa;
                border: 1px solid #1f2937;
                border-radius: 8px;
                font-family: Consolas;
                font-size: 13px;
            }
        """)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.init_account_panel()
        self.init_instance_panel()
        self.init_bottom_panel()

        self.v_splitter.addWidget(self.h_splitter)
        main_layout.addWidget(self.v_splitter)
        self.refresh_account_table()
        self.apply_227_style()

    def init_account_panel(self):
        widget = QFrame()
        widget.setStyleSheet("background: white; border: 1px solid #ddd; border-radius: 8px;")
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("<b>👤 账号管理</b>"))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索账号/项目/代理")
        self.search_edit.textChanged.connect(self.filter_accounts)
        layout.addWidget(self.search_edit)

        row = QHBoxLayout()
        self.email_edit = QLineEdit(placeholderText="邮箱")
        self.key_btn = QPushButton("选择JSON密钥")
        self.key_btn.clicked.connect(self.select_json)
        self.proxy_edit = QLineEdit(placeholderText="无需代理留空 | 格式：IP:Port:User:Pass")
        self.proxy_edit.textChanged.connect(self.auto_detect_proxy_type)
        self.proxy_type = QComboBox()
        self.proxy_type.addItems(["HTTPS", "SOCKS5"])
        self.add_btn = QPushButton("添加账号")
        self.add_btn.clicked.connect(self.add_account)
        row.addWidget(self.email_edit, 2)
        row.addWidget(self.key_btn)
        row.addWidget(QLabel("代理:"))
        row.addWidget(self.proxy_edit)
        row.addWidget(self.proxy_type)
        row.addWidget(self.add_btn)
        layout.addLayout(row)

        self.account_table = QTableWidget(0, 6)
        self.account_table.setHorizontalHeaderLabels(["选择", "ID", "邮箱", "ProjectID", "代理", "协议"])
        self.account_table.setColumnHidden(1, True)
        self.account_table.itemChanged.connect(self.on_account_edit)
        self.account_table.cellDoubleClicked.connect(self.on_account_table_double_click)
        layout.addWidget(self.account_table)

        self.query_btn = QPushButton("查询选中账号实例")
        self.query_btn.setFixedHeight(45)
        self.query_btn.clicked.connect(self.query_instances)
        layout.addWidget(self.query_btn)

        self.firewall_btn = QPushButton("🔥 一键全开防火墙")
        self.firewall_btn.setFixedHeight(45)
        self.firewall_btn.setStyleSheet("background-color: #ff6b35; color: white; font-weight: bold; font-size: 14px;")
        self.firewall_btn.clicked.connect(self.open_firewall)
        layout.addWidget(self.firewall_btn)

        row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选/反选")
        self.select_all_btn.clicked.connect(self.toggle_select_all)
        self.batch_import_btn = QPushButton("📂 批量导入JSON")
        self.batch_import_btn.clicked.connect(self.batch_import)
        self.del_account_btn = QPushButton("删除选中账号")
        self.del_account_btn.clicked.connect(self.delete_selected_account)
        row.addWidget(self.select_all_btn)
        row.addWidget(self.batch_import_btn)
        row.addStretch()
        row.addWidget(self.del_account_btn)
        layout.addLayout(row)

        self.h_splitter.addWidget(widget)

    def init_instance_panel(self):
        frame = QFrame()
        frame.setStyleSheet("background: white; border: 1px solid #ddd; border-radius: 8px;")
        layout = QVBoxLayout(frame)
        layout.addWidget(QLabel("<b>📋 实例列表</b>"))

        group = QGroupBox("哪吒监控配置")
        form = QFormLayout(group)
        self.nezha_url = QLineEdit(placeholderText="面板地址（如：https://nezha.example.com）")
        self.nezha_token = QLineEdit(placeholderText="Token")
        form.addRow("面板地址:", self.nezha_url)
        form.addRow("Token:", self.nezha_token)

        btn_row = QHBoxLayout()
        self.nezha_save = QPushButton("保存配置")
        self.nezha_save.clicked.connect(self.save_nezha)
        self.nezha_refresh = QPushButton("刷新数据")
        self.nezha_refresh.clicked.connect(self.fetch_nezha)
        self.nezha_test = QPushButton("测试连接")
        self.nezha_test.clicked.connect(self.test_nezha)
        btn_row.addWidget(self.nezha_save)
        btn_row.addWidget(self.nezha_refresh)
        btn_row.addWidget(self.nezha_test)
        form.addRow("", btn_row)
        layout.addWidget(group)

        self.instances_table = QTableWidget(0, 5)
        self.instances_table.verticalHeader().setDefaultSectionSize(22)
        self.instances_table.setHorizontalHeaderLabels(["实例名称", "IP", "可用区", "监控名称", "Root密码"])
        self.instances_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.instances_table.cellDoubleClicked.connect(self.on_instance_table_double_click)
        layout.addWidget(self.instances_table)

        self.instance_status = QLabel("等待查询...")
        layout.addWidget(self.instance_status)

        btn_row = QHBoxLayout()
        self.del_inst_btn = QPushButton("🗑️ 删除实例")
        self.del_inst_btn.setStyleSheet("background-color: #ea4335; color: white; font-weight: bold; padding: 8px;")
        self.start_inst_btn = QPushButton("▶️ 启动实例")
        self.start_inst_btn.setStyleSheet("background-color: #4caf50; color: white; font-weight: bold; padding: 8px;")
        self.stop_inst_btn = QPushButton("⏹️ 停止实例")
        self.stop_inst_btn.setStyleSheet("background-color: #607d8b; color: white; font-weight: bold; padding: 8px;")
        self.reset_inst_btn = QPushButton("🔄 重启实例")
        self.reset_inst_btn.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold; padding: 8px;")
        self.del_inst_btn.clicked.connect(lambda: self.operate_instances('delete'))
        self.start_inst_btn.clicked.connect(lambda: self.operate_instances('start'))
        self.stop_inst_btn.clicked.connect(lambda: self.operate_instances('stop'))
        self.reset_inst_btn.clicked.connect(lambda: self.operate_instances('reset'))
        for btn in [self.del_inst_btn, self.start_inst_btn, self.stop_inst_btn, self.reset_inst_btn]:
            btn.setEnabled(False)
        btn_row.addWidget(self.del_inst_btn)
        btn_row.addWidget(self.start_inst_btn)
        btn_row.addWidget(self.stop_inst_btn)
        btn_row.addWidget(self.reset_inst_btn)
        layout.addLayout(btn_row)

        self.h_splitter.addWidget(frame)
        self.h_splitter.setStretchFactor(0, 1)
        self.h_splitter.setStretchFactor(1, 2)

    def init_bottom_panel(self):
        frame = QFrame()
        frame.setStyleSheet("background: white; border: 1px solid #ddd; border-radius: 8px;")
        layout = QVBoxLayout(frame)
        layout.addWidget(QLabel("<b>🚀 批量创建实例</b>"))

        region_row = QHBoxLayout()
        self.free_radio = QRadioButton("🆓 免费区", checked=True)
        self.paid_radio = QRadioButton("💰 付费区")
        self.free_radio.toggled.connect(self.update_regions)
        self.region_box = QComboBox()
        self.count_edit = QLineEdit("1", placeholderText="数量")
        self.pubkey_btn = QPushButton("上传SSH公钥")
        self.pubkey_btn.clicked.connect(self.upload_pubkey)
        self.pubkey_label = QLabel("未选择公钥")
        self.pubkey_label.setStyleSheet("color: #0066cc; font-weight: bold;")
        self.create_btn = QPushButton("开始部署")
        self.create_btn.setStyleSheet("background-color: #34a853; color: white; font-size: 15px; padding: 12px; font-weight: bold;")
        self.create_btn.clicked.connect(self.start_create)

        region_row.addWidget(self.free_radio)
        region_row.addWidget(self.paid_radio)
        region_row.addWidget(QLabel("区域:"))
        region_row.addWidget(self.region_box)
        region_row.addWidget(QLabel("数量:"))
        region_row.addWidget(self.count_edit)
        region_row.addWidget(self.pubkey_btn)
        region_row.addWidget(self.pubkey_label)
        region_row.addWidget(self.create_btn)
        layout.addLayout(region_row)

        root_row = QHBoxLayout()
        self.normal_login_radio = QRadioButton("SSH密钥模式", checked=True)
        self.root_login_radio = QRadioButton("Root密码模式")
        self.login_mode_group = QButtonGroup(self)
        self.login_mode_group.addButton(self.normal_login_radio)
        self.login_mode_group.addButton(self.root_login_radio)

        self.custom_password_radio = QRadioButton("用户自定义密码", checked=True)
        self.random_password_radio = QRadioButton("自动随机密码")
        self.password_mode_group = QButtonGroup(self)
        self.password_mode_group.addButton(self.custom_password_radio)
        self.password_mode_group.addButton(self.random_password_radio)

        self.root_password_edit = QLineEdit()
        self.root_password_edit.setPlaceholderText("Root自定义密码")
        self.root_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.root_login_radio.toggled.connect(self.update_root_mode_ui)
        self.custom_password_radio.toggled.connect(self.update_root_mode_ui)
        self.random_password_radio.toggled.connect(self.update_root_mode_ui)

        root_row.addWidget(QLabel("登录模式:"))
        root_row.addWidget(self.normal_login_radio)
        root_row.addWidget(self.root_login_radio)
        root_row.addSpacing(12)
        root_row.addWidget(self.custom_password_radio)
        root_row.addWidget(self.random_password_radio)
        root_row.addWidget(self.root_password_edit, 1)
        layout.addLayout(root_row)

        self.log_area = QTextEdit(readOnly=True)
        self.log_area.setStyleSheet("background-color: #0d1117; color: #00ffaa; font-family: Consolas; font-size: 13px;")
        layout.addWidget(self.log_area)

        self.v_splitter.addWidget(frame)
        self.v_splitter.setStretchFactor(0, 4)
        self.v_splitter.setStretchFactor(1, 6)
        self.update_regions()
        self.update_root_mode_ui()

    def auto_detect_proxy_type(self, text):
        parsed = parse_proxy_input(text, fallback_proxy_type=self.proxy_type.currentText(), require_protocol=False)
        if parsed.get('ok') and not parsed.get('empty'):
            self.proxy_type.setCurrentText(parsed.get('proxy_type', 'HTTPS'))

    def upload_pubkey(self):
        path, _ = QFileDialog.getOpenFileName()
        if path:
            with open(path, 'r', encoding='utf-8') as f:
                self.ssh_public_key = f.read().strip()
            self.pubkey_label.setText(os.path.basename(path))
            self.log_signal.emit("✅ SSH公钥加载成功")

    def select_json(self):
        path, _ = QFileDialog.getOpenFileName(filter="JSON (*.json)")
        if path:
            self.current_json_path = path
            self.key_btn.setText(os.path.basename(path))
            self.email_edit.setText(os.path.splitext(os.path.basename(path))[0])

    def load_project_id_from_json(self, json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        project_id = data.get('project_id', '').strip()
        if not project_id:
            raise ValueError("JSON密钥中缺少 project_id")
        return project_id

    def add_account(self):
        if not self.email_edit.text() or not self.current_json_path:
            QMessageBox.warning(self, "提示", "请填写邮箱并选择JSON密钥")
            return
        try:
            project_id = self.load_project_id_from_json(self.current_json_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取JSON密钥失败：{e}")
            return

        proxy_text = self.proxy_edit.text().strip()
        parsed_proxy = parse_proxy_input(proxy_text, fallback_proxy_type=self.proxy_type.currentText(), require_protocol=bool(proxy_text))
        if not parsed_proxy.get('ok'):
            QMessageBox.warning(self, "代理格式错误", parsed_proxy.get('error', proxy_formats_help_text()))
            self.log_signal.emit(f"❌ 新增账号时代理格式无法识别\n{parsed_proxy.get('error', proxy_formats_help_text())}")
            return

        if not parsed_proxy.get('empty'):
            self.proxy_type.setCurrentText(parsed_proxy.get('proxy_type', 'HTTPS'))

        self.db.add_account(
            self.email_edit.text(), project_id, self.current_json_path,
            proxy_text, parsed_proxy.get('proxy_type', self.proxy_type.currentText())
        )
        self.refresh_account_table()
        self.log_signal.emit("✅ 账号添加成功")

    def refresh_account_table(self):
        self.account_table.setRowCount(0)
        self._is_refreshing = True  # 标记刷新中
        for acc in self.db.get_all():
            row = self.account_table.rowCount()
            self.account_table.insertRow(row)
            self.account_table.setCellWidget(row, 0, QCheckBox())
            # 修正映射关系：ID(0), Email(1), Project ID(2), Proxy(4), ProxyType(5)
            # 跳过 key_path 列（索引3）
            mapping = [acc[0], acc[1], acc[2], acc[4], acc[5]]
            for col, val in enumerate(mapping, 1):
                self.account_table.setItem(row, col, QTableWidgetItem(str(val)))
        self._is_refreshing = False

    def emit_account_proxy_status(self, account, gcp, action_label):
        account_label = account[1] if isinstance(account, tuple) else account.get('email', '未知账号')
        if gcp.proxy_url:
            proto = "SOCKS5" if gcp.proxy_url.startswith('socks5') else "HTTP"
            self.log_signal.emit(f"[{account_label}] 🌐 {action_label} | 使用代理 [{proto}]：{gcp.proxy_url}")
        else:
            self.log_signal.emit(f"[{account_label}] 🌐 {action_label} | 未使用代理，直连 GCP")

    def query_instances(self):
        acc = self.get_selected_account()
        if not acc:
            QMessageBox.warning(self, "提示", "请选择账号")
            return
        self.instance_status.setText("查询中...")
        self.query_btn.setEnabled(False)
        gcp = GCPService(acc[3], acc[2], acc[1], acc[4], acc[5])
        self.emit_account_proxy_status(acc, gcp, "查询实例")
        self.loader = InstanceLoader(gcp)
        self.loader.finished.connect(self.update_instance_table)
        self.loader.finished.connect(lambda _: self.query_btn.setEnabled(True))
        self.loader.error.connect(self.on_query_error)
        self.loader.start()

    def update_instance_table(self, instances):
        self.current_instances = instances
        self.instances_table.setRowCount(0)
        for inst in instances:
            row = self.instances_table.rowCount()
            self.instances_table.insertRow(row)
            name = inst.get('name', '')
            self.instances_table.setItem(row, 0, QTableWidgetItem(name))
            self.instances_table.setItem(row, 1, QTableWidgetItem(inst.get('ip', '')))
            self.instances_table.setItem(row, 2, QTableWidgetItem(inst.get('zone', '')))
            # 精准匹配哪吒面板的IP-名称
            monitor_name = self.nezha_ip_map.get(inst.get('ip', ''), '未配置')
            self.instances_table.setItem(row, 3, QTableWidgetItem(monitor_name))
            self.instances_table.setItem(row, 4, QTableWidgetItem(self.instance_password_cache.get(name, '')))
        self.instance_status.setText(f"查询完成：{len(instances)}台实例")
        self.log_signal.emit(f"✅ 查询完成：{len(instances)}台实例")
        self.query_btn.setEnabled(True)
        for btn in [self.del_inst_btn, self.start_inst_btn, self.stop_inst_btn, self.reset_inst_btn]:
            btn.setEnabled(len(instances) > 0)

    def on_query_error(self, error_text):
        self.instance_status.setText("查询失败")
        self.query_btn.setEnabled(True)
        self.log_signal.emit(f"❌ 查询失败：{error_text}")

    def on_instance_table_double_click(self, row, col):
        if col == 1:
            ip_item = self.instances_table.item(row, 1)
            if ip_item and ip_item.text():
                QApplication.clipboard().setText(ip_item.text())
                self.log_signal.emit(f"✅ IP {ip_item.text()} 已复制")
        elif col == 4:
            pwd_item = self.instances_table.item(row, 4)
            if pwd_item and pwd_item.text():
                QApplication.clipboard().setText(pwd_item.text())
                self.log_signal.emit(f"✅ Root密码 已复制")

    def operate_instances(self, action):
        selected = self.get_selected_instances()
        if not selected:
            QMessageBox.warning(self, "提示", "请选择实例")
            return
        
        # 二次确认弹窗
        action_names = {
            'delete': '删除',
            'start': '启动',
            'stop': '停止',
            'reset': '重启'
        }
        action_name = action_names.get(action, action)
        instance_names = ', '.join([s['name'] for s in selected[:3]])
        if len(selected) > 3:
            instance_names += f' 等{len(selected)}台'
        
        reply = QMessageBox.question(
            self, 
            f"确认{action_name}", 
            f"确认{action_name}以下 {len(selected)} 台实例？\n\n{instance_names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.log_signal.emit(f"{action_name}中：共 {len(selected)} 台实例...")
        
        acc = self.get_selected_account()
        gcp = GCPService(acc[3], acc[2], acc[1], acc[4], acc[5])
        self.emit_account_proxy_status(acc, gcp, f"{action_name}实例")
        self.operator = InstanceOperator(gcp, selected, action)
        self.operator.log.connect(self.log_signal.emit)
        self.operator.finished.connect(lambda: self.log_signal.emit("🔄 实例操作完成，正在自动刷新实例列表..."))
        self.operator.finished.connect(self.query_instances)
        self.operator.start()

    def is_root_password_mode(self):
        return self.root_login_radio.isChecked()

    def update_root_mode_ui(self):
        root_mode = self.root_login_radio.isChecked()
        self.custom_password_radio.setEnabled(root_mode)
        self.random_password_radio.setEnabled(root_mode)
        self.root_password_edit.setEnabled(root_mode and self.custom_password_radio.isChecked())
        if not root_mode:
            self.root_password_edit.setEnabled(False)

    def generate_random_root_password(self, length=16):
        alphabet = string.ascii_letters + string.digits + '@#_-+='
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def build_root_startup_script(self, root_password):
        safe_password = root_password.replace("'", "'\"'\"'")
        return f"""#!/bin/bash
set -euxo pipefail
mkdir -p /root
LOG_FILE=/root/gcp_root_mode.log
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[INFO] starting root password mode setup"
export DEBIAN_FRONTEND=noninteractive

echo 'root:{safe_password}' | chpasswd
passwd -u root || true

if [ -f /etc/ssh/sshd_config ]; then
  sed -i 's/^\\s*#\\?\\s*PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config || true
  sed -i 's/^\\s*#\\?\\s*PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config || true
  sed -i 's/^\\s*#\\?\\s*KbdInteractiveAuthentication.*/KbdInteractiveAuthentication yes/g' /etc/ssh/sshd_config || true
  sed -i 's/^\\s*#\\?\\s*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication yes/g' /etc/ssh/sshd_config || true
  grep -q '^PermitRootLogin yes$' /etc/ssh/sshd_config || echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config
  grep -q '^PasswordAuthentication yes$' /etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config
  grep -q '^KbdInteractiveAuthentication yes$' /etc/ssh/sshd_config || echo 'KbdInteractiveAuthentication yes' >> /etc/ssh/sshd_config
  grep -q '^ChallengeResponseAuthentication yes$' /etc/ssh/sshd_config || echo 'ChallengeResponseAuthentication yes' >> /etc/ssh/sshd_config
fi

rm -rf /etc/ssh/sshd_config.d/* /etc/ssh/ssh_config.d/* || true

mkdir -p /etc/ssh/sshd_config.d /etc/ssh/ssh_config.d
cat >/etc/ssh/sshd_config.d/99-root-password.conf <<'EOF'
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication yes
ChallengeResponseAuthentication yes
UsePAM yes
EOF

sshd -t || sshd -T || true
systemctl restart ssh || systemctl restart sshd || service ssh restart || service sshd restart || true
sleep 2

echo "[INFO] root password mode setup finished"
touch /root/.gcp_root_mode_ok
"""

    def start_create(self):
        accounts = [acc for i, acc in enumerate(self.db.get_all()) if self.account_table.cellWidget(i, 0).isChecked()]
        if not accounts:
            QMessageBox.warning(self, "提示", "请选择账号")
            return
        count = int(self.count_edit.text()) if self.count_edit.text().isdigit() else 1
        if count <= 0:
            QMessageBox.warning(self, "提示", "创建数量必须大于 0")
            return

        root_mode = self.is_root_password_mode()
        custom_password_mode = self.custom_password_radio.isChecked()
        custom_root_password = self.root_password_edit.text().strip()
        if root_mode and custom_password_mode and not custom_root_password:
            QMessageBox.warning(self, "提示", "请选择 Root密码模式后，请填写自定义密码")
            return

        create_config = {
            'root_mode': root_mode,
            'custom_password_mode': custom_password_mode,
            'custom_root_password': custom_root_password,
            'use_free_regions': self.free_radio.isChecked(),
            'selected_region_text': self.region_box.currentText().strip(),
        }

        self.create_btn_signal.emit(False)
        self.log_signal.emit("=== 开始批量部署 ===")

        def worker():
            try:
                for acc in accounts:
                    try:
                        self.process_account(acc, count, create_config)
                    except Exception as e:
                        self.log_signal.emit(f"[{acc[1]}] ❌ 处理账号时发生未捕获异常：{e}")
                self.log_signal.emit("=== 全部部署完成 ===")
            finally:
                self.create_btn_signal.emit(True)
                self.log_signal.emit("🔄 批量部署完成，正在自动刷新实例列表...")
                self.refresh_instances_signal.emit()

        threading.Thread(target=worker, daemon=True).start()

    def get_region_zones(self, region):
        zones = ZONE_OPTIONS.get(region, [])
        if not zones:
            zones = [f"{region}-{s}" for s in ['a', 'b', 'c', 'd']]
        return zones

    def robust_create_instance(self, gcp, primary_region, instance_name, tried_zones, candidate_regions, startup_script=""):
        ordered_regions = [primary_region] + [r for r in candidate_regions if r != primary_region]
        if len(ordered_regions) > 1:
            remaining = ordered_regions[1:]
            random.shuffle(remaining)
            ordered_regions = [ordered_regions[0]] + remaining

        for region in ordered_regions:
            region_zones = [z for z in self.get_region_zones(region) if z not in tried_zones]
            random.shuffle(region_zones)
            for zone in region_zones:
                success, result = gcp.create_instance(zone, instance_name, startup_script=startup_script)
                if success:
                    return True, result
                if str(result) != "资源耗尽":
                    return False, result
                tried_zones.add(zone)

        return False, "所有可用区资源耗尽"

    def process_account(self, acc, count, create_config):
        gcp = GCPService(acc[3], acc[2], acc[1], acc[4], acc[5])
        self.emit_account_proxy_status(acc, gcp, "批量创建实例")
        if self.ssh_public_key:
            ssh_ok, ssh_msg = gcp.add_ssh_key(self.ssh_public_key)
            self.log_signal.emit(f"[{acc[1]}] {ssh_msg if ssh_ok else '公钥注入失败：' + ssh_msg}")

        root_mode = create_config.get('root_mode', False)
        custom_password_mode = create_config.get('custom_password_mode', True)
        custom_root_password = create_config.get('custom_root_password', '')
        pool = FREE_REGIONS if create_config.get('use_free_regions', True) else PAID_REGIONS
        pool_regions = list(pool.values())
        selected_region_text = create_config.get('selected_region_text', '').strip()
        selected_region = pool.get(selected_region_text)

        try:
            instances = gcp.list_instances()
            region_count = defaultdict(int)
            for inst in instances:
                zone = inst['zone']
                region = zone.lstrip('zones/').rsplit('-', 1)[0]
                if region in pool_regions:
                    region_count[region] += 1
        except Exception as e:
            self.log_signal.emit(f"[{acc[1]}] ❌ 实例清点失败：{e}")
            return

        def calc_available_regions():
            return [r for r in pool_regions if region_count[r] < 4]

        available_regions = calc_available_regions()
        if not available_regions:
            self.log_signal.emit(f"[{acc[1]}] ❌ 当前模式下所有区域配额已满，跳过该账号")
            return

        self.log_signal.emit(f"[{acc[1]}] 📊 当前配额: {dict(region_count)} | 可用区域: {len(available_regions)} 个 | 开始创建 {count} 台...")

        created = 0
        for i in range(1, count + 1):
            available_regions = calc_available_regions()
            if not available_regions:
                self.log_signal.emit(f"[{acc[1]}] ⚠️ 可用区域已无剩余配额，停止创建 (已建 {created} 台)")
                break

            if selected_region_text == "随机选择 (Random)" or not selected_region:
                region = random.choice(available_regions)
                candidate_regions = available_regions[:]
            else:
                if selected_region in available_regions:
                    region = selected_region
                    candidate_regions = [selected_region]
                else:
                    self.log_signal.emit(f"[{acc[1]}] ⚠️ 指定区域 {selected_region} 已满额，改为在当前池可用区域中随机创建")
                    region = random.choice(available_regions)
                    candidate_regions = available_regions[:]

            name = f"vm-{acc[0]}-{i}-{random.randint(1000, 9999)}"
            tried_zones = set()
            root_password = ""
            password_display = ""
            password_log_part = ""
            startup_script = ""
            if root_mode:
                if custom_password_mode:
                    root_password = custom_root_password
                    password_display = "用户自定义"
                    password_log_part = "密码模式：用户自定义"
                else:
                    root_password = self.generate_random_root_password()
                    password_display = root_password
                    password_log_part = f"Root密码：{root_password}"
                startup_script = self.build_root_startup_script(root_password)

            success, res = self.robust_create_instance(gcp, region, name, tried_zones, candidate_regions, startup_script=startup_script)
            if success:
                ip, zone = res
                region_name = zone.rsplit('-', 1)[0]
                if region_name in pool_regions:
                    region_count[region_name] += 1
                if root_mode:
                    self.instance_password_cache[name] = password_display
                created += 1
                if root_mode:
                    self.log_signal.emit(f"[{acc[1]}] ✅ 第{i}台创建成功 | 区域：{region_name} ({zone}) | IP：{ip} | 登录：root | {password_log_part}")
                else:
                    self.log_signal.emit(f"[{acc[1]}] ✅ 第{i}台创建成功 | 区域：{region_name} ({zone}) | IP：{ip}")
            else:
                self.log_signal.emit(f"[{acc[1]}] ❌ 第{i}台创建失败：{res}")
            time.sleep(2)

        self.log_signal.emit(f"[{acc[1]}] 📈 创建完成：{created}/{count} 台成功")

    def get_selected_account(self):
        for i in range(self.account_table.rowCount()):
            checkbox = self.account_table.cellWidget(i, 0)
            id_item = self.account_table.item(i, 1)
            if checkbox and checkbox.isChecked() and id_item:
                return self.db.get_by_id(id_item.text())
        return None

    def get_selected_instances(self):
        instances = []
        for r in self.instances_table.selectionModel().selectedRows():
            name_item = self.instances_table.item(r.row(), 0)
            ip_item = self.instances_table.item(r.row(), 1)
            zone_item = self.instances_table.item(r.row(), 2)
            if not (name_item and ip_item and zone_item):
                continue
            instances.append({
                'name': name_item.text(),
                'zone': zone_item.text(),
                'ip': ip_item.text()
            })
        return instances

    def append_log(self, msg):
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_area.append(f"[{timestamp}] {msg}")

    def load_nezha_config(self):
        data = self.config.load_json()
        self.nezha_url.setText(data.get('url', ''))
        self.nezha_token.setText(data.get('token', ''))
        if self.nezha_url.text() and self.nezha_token.text():
            self.fetch_nezha()

    def save_nezha(self):
        self.config.save_json({'url': self.nezha_url.text(), 'token': self.nezha_token.text()})
        self.log_signal.emit("✅ 哪吒配置保存成功")
        self.fetch_nezha()

    def fetch_nezha(self):
        if not self.nezha_url.text() or not self.nezha_token.text():
            return
        self.fetcher = NezhaFetcher(self.nezha_url.text(), self.nezha_token.text())
        self.fetcher.finished.connect(self.on_nezha_fetch_finished)
        self.fetcher.start()

    def on_nezha_fetch_finished(self, mapping, status):
        self.nezha_ip_map = mapping
        if status != "OK":
            self.log_signal.emit(f"⚠️ 哪吒数据刷新异常：{status}")
        if self.current_instances:
            self.update_instance_table(self.current_instances)

    def open_firewall(self):
        acc = self.get_selected_account()
        if not acc:
            QMessageBox.warning(self, "提示", "请选择账号")
            return

        self.firewall_btn_signal.emit(False)
        self.log_signal.emit(f"[{acc[1]}] 开始配置全开放防火墙...")

        def worker():
            try:
                gcp = GCPService(acc[3], acc[2], acc[1], acc[4], acc[5])
                self.emit_account_proxy_status(acc, gcp, "配置全开放防火墙")
                success, msg = gcp.create_open_firewall_rules()
                prefix = "✅" if success else "❌"
                self.log_signal.emit(f"[{acc[1]}] {prefix} {msg}")
            except Exception as e:
                self.log_signal.emit(f"[{acc[1]}] ❌ 防火墙处理异常：{e}")
            finally:
                self.firewall_btn_signal.emit(True)

        threading.Thread(target=worker, daemon=True).start()

    def load_layout_config(self):
        self.config.load_layout()
        if self.config.config.has_section('Layout'):
            data = self.config.config['Layout']
            try:
                w = int(data.get('width', 1250))
                h = int(data.get('height', 880))
                self.resize(w, h)
                
                # Splitter sizes
                if data.get('v_splitter'):
                    v_raw = data.get('v_splitter', '')
                    v_sizes = [int(x) for x in v_raw.split('|') if x]
                    if v_sizes:
                        self.v_splitter.setSizes(v_sizes)
                if data.get('h_splitter'):
                    h_raw = data.get('h_splitter', '')
                    h_sizes = [int(x) for x in h_raw.split('|') if x]
                    if h_sizes:
                        self.h_splitter.setSizes(h_sizes)
                
                # Column widths - account table
                if data.get('account_col_widths'):
                    widths = [int(x) for x in data.get('account_col_widths').split('|')]
                    for i, w in enumerate(widths):
                        if i < self.account_table.columnCount():
                            self.account_table.setColumnWidth(i, w)
                
                # Column widths - instances table
                if data.get('instances_col_widths'):
                    inst_widths = [int(x) for x in data.get('instances_col_widths').split('|')]
                    for i, w in enumerate(inst_widths):
                        if i < self.instances_table.columnCount():
                            self.instances_table.setColumnWidth(i, w)
                
                # Row height
                if data.get('row_height'):
                    rh = int(data.get('row_height', 22))
                    self.account_table.verticalHeader().setDefaultSectionSize(rh)
                    self.instances_table.verticalHeader().setDefaultSectionSize(rh)
                    self.log_signal.emit(f"[布局] 已加载记忆: 行高 {rh}px")
                    
                self.log_signal.emit("[布局] 布局加载成功")
            except Exception as e:
                self.log_signal.emit(f"[布局] 加载异常: {e}")

    def closeEvent(self, event):
        try:
            # 收集账号表格每一列的宽度
            col_widths = []
            for i in range(self.account_table.columnCount()):
                col_widths.append(str(self.account_table.columnWidth(i)))
            widths_str = '|'.join(col_widths)
            
            # 收集实例表格每一列的宽度
            inst_col_widths = []
            for i in range(self.instances_table.columnCount()):
                inst_col_widths.append(str(self.instances_table.columnWidth(i)))
            inst_widths_str = '|'.join(inst_col_widths)
            
            self.config.save_layout({
                'width': self.width(),
                'height': self.height(),
                'v_splitter': '|'.join(map(str, self.v_splitter.sizes())),
                'h_splitter': '|'.join(map(str, self.h_splitter.sizes())),
                'account_col_widths': widths_str,
                'instances_col_widths': inst_widths_str
            })
            self.log_signal.emit("[布局] 布局已保存")
        except Exception as e:
            self.log_signal.emit(f"[布局] 保存失败: {e}")
        event.accept()

    def update_regions(self):
        self.region_box.clear()
        regions = FREE_REGIONS if self.free_radio.isChecked() else PAID_REGIONS
        self.region_box.addItems(list(regions.keys()) + ["随机选择 (Random)"])

    def filter_accounts(self, text):
        keyword = text.lower()
        for i in range(self.account_table.rowCount()):
            values = []
            for j in range(2, 6):
                item = self.account_table.item(i, j)
                values.append(item.text().lower() if item else '')
            match = any(keyword in value for value in values)
            self.account_table.setRowHidden(i, not match)

    def on_account_table_double_click(self, row, col):
        if col == 4:
            proxy_item = self.account_table.item(row, 4)
            if proxy_item and proxy_item.text():
                QApplication.clipboard().setText(proxy_item.text())
                self.log_signal.emit(f"✅ 代理 {proxy_item.text()} 已复制")
        elif col == 2:
            email_item = self.account_table.item(row, 2)
            if email_item and email_item.text():
                QApplication.clipboard().setText(email_item.text())
                self.log_signal.emit(f"✅ 邮箱 {email_item.text()} 已复制")
        elif col == 3:
            project_item = self.account_table.item(row, 3)
            if project_item and project_item.text():
                QApplication.clipboard().setText(project_item.text())
                self.log_signal.emit(f"✅ ProjectID {project_item.text()} 已复制")

    def toggle_select_all(self):
        if self.account_table.rowCount() == 0:
            return
        state = not self.account_table.cellWidget(0, 0).isChecked()
        for i in range(self.account_table.rowCount()):
            self.account_table.cellWidget(i, 0).setChecked(state)

    def delete_selected_account(self):
        deleted = 0
        for i in range(self.account_table.rowCount() - 1, -1, -1):
            checkbox = self.account_table.cellWidget(i, 0)
            id_item = self.account_table.item(i, 1)
            if checkbox and checkbox.isChecked() and id_item:
                self.db.delete_account(id_item.text())
                deleted += 1
        self.refresh_account_table()
        if deleted:
            self.log_signal.emit(f"🗑️ 已删除 {deleted} 个账号")

    def on_account_edit(self, item):
        # 避免在刷新表格时触发死循环
        if not hasattr(self, '_is_refreshing') or not self._is_refreshing:
            row = item.row()
            col = item.column()
            id_item = self.account_table.item(row, 1)
            if not id_item:
                return
            acc_id = id_item.text()
            
            if col == 4:  # 代理列
                proxy_text = item.text().strip()
                previous_type_item = self.account_table.item(row, 5)
                previous_type = previous_type_item.text().strip() if previous_type_item else 'HTTPS'
                parsed_proxy = parse_proxy_input(proxy_text, fallback_proxy_type=previous_type, require_protocol=bool(proxy_text))

                if not parsed_proxy.get('ok'):
                    QMessageBox.warning(self, "代理格式错误", parsed_proxy.get('error', proxy_formats_help_text()))
                    self.log_signal.emit(f"❌ 账号代理格式无法识别\n{parsed_proxy.get('error', proxy_formats_help_text())}")
                    self.account_table.blockSignals(True)
                    try:
                        item.setText('')
                    finally:
                        self.account_table.blockSignals(False)
                    self.db.update_account(acc_id, proxy='')
                    return

                new_type = parsed_proxy.get('proxy_type', previous_type)
                
                # 更新数据库（代理和协议类型同时更新）
                self.db.update_account(acc_id, proxy=proxy_text, proxy_type=new_type)
                
                # 更新协议列显示（临时屏蔽信号以防递归）
                self.account_table.blockSignals(True)
                try:
                    type_item = self.account_table.item(row, 5)
                    if type_item:
                        type_item.setText(new_type)
                finally:
                    self.account_table.blockSignals(False)
                
            elif col == 5:  # 协议列
                proxy_type = item.text().strip()
                self.db.update_account(acc_id, proxy_type=proxy_type)

    def batch_import(self):
        folder = QFileDialog.getExistingDirectory()
        if not folder:
            return

        count = 0
        skipped = 0
        existing_paths = {str(acc[3]).lower() for acc in self.db.get_all()}

        for f in os.listdir(folder):
            if not f.endswith('.json'):
                continue
            path = os.path.join(folder, f)
            if path.lower() in existing_paths:
                skipped += 1
                continue
            try:
                pid = self.load_project_id_from_json(path)
                self.db.add_account(os.path.splitext(f)[0], pid, path)
                existing_paths.add(path.lower())
                count += 1
            except Exception as e:
                skipped += 1
                self.log_signal.emit(f"⚠️ 跳过 {f}：{e}")

        self.refresh_account_table()
        self.log_signal.emit(f"✅ 批量导入完成：新增 {count} 个，跳过 {skipped} 个")

    def test_nezha(self):
        """修复测试连接，适配真实面板结构"""
        if not self.nezha_url.text() or not self.nezha_token.text():
            QMessageBox.warning(self, "提示", "请填写面板地址和Token！")
            return

        try:
            api = NezhaAPI(self.nezha_url.text(), self.nezha_token.text())
            success, res = api.get_server_list()
            if success:
                # 显示正确的服务器数量（你的面板有7台）
                QMessageBox.information(self, "成功", f"连接成功！服务器数量：{len(res)}")
                # 自动刷新IP-名称映射
                self.fetch_nezha()
            else:
                QMessageBox.critical(self, "失败", f"连接失败：{res}")
        except Exception as e:
            QMessageBox.critical(self, "严重错误", f"测试连接时出错：{str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GCPManagerApp()
    window.show()
    sys.exit(app.exec())