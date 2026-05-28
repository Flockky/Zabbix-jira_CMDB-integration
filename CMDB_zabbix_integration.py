## -*- coding: utf-8 -*-
import requests
from pyzabbix.api import ZabbixAPI
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import urllib3
import os
import json
import sys

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================

# --- Secrets (Must be set in Environment) ---
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
JIRA_PASSWORD = os.environ.get("JIRA_PASSWORD")
ZABBIX_API_TOKEN = os.environ.get("ZABBIX_API_TOKEN")

if not all([SMTP_PASSWORD, JIRA_PASSWORD, ZABBIX_API_TOKEN]):
    raise Exception("Missing required environment variables: SMTP_PASSWORD, JIRA_PASSWORD, ZABBIX_API_TOKEN")

# --- Infrastructure Endpoints ---
JIRA_URL = os.environ.get("JIRA_URL", "https://jira.internal.domain")
ZABBIX_URL = os.environ.get("ZABBIX_URL", "https://zabbix.internal.domain")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.internal.domain")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_FROM_ADDR = os.environ.get("SMTP_FROM_ADDR", "AlertSystem@internal.domain")
ERROR_EMAIL_TO = os.environ.get("ERROR_EMAIL_TO", "admin-team@internal.domain")

# --- Jira Insight Configuration ---
# ID схемы объектов и параметры запроса
INSIGHT_SCHEMA_ID = os.environ.get("INSIGHT_SCHEMA_ID", "7")
INSIGHT_IQL = os.environ.get("INSIGHT_IQL", "ObjectType in (Servers)")
INSIGHT_PAGE_SIZE = 2000
JIRA_AUTH_USER = os.environ.get("JIRA_AUTH_USER", "SA-Zabbix-Confluence")

# Маппинг ID атрибутов Insight (Критично: эти ID зависят от вашей схемы в Jira)
# Замените цифры на соответствующие ID атрибутов в вашем объекте "Servers"
ATTR_MAP = {
    'IP': int(os.environ.get("ATTR_IP_ID", "985")),
    'ENV_TYPE': int(os.environ.get("ATTR_ENV_ID", "979")),       # CPRD/PROD marker
    'SYSTEM': int(os.environ.get("ATTR_SYS_ID", "995")),         # Referenced Object
    'NETWORK': int(os.environ.get("ATTR_NET_ID", "984")),        # Referenced Object
    'ROLE': int(os.environ.get("ATTR_ROLE_ID", "1001")),         # Referenced Object
    'CIRCUIT': int(os.environ.get("ATTR_CIRC_ID", "1000")),      # Referenced Object
    'OWNER': int(os.environ.get("ATTR_OWN_ID", "996")),          # Display Value
    'LOCATION': int(os.environ.get("ATTR_LOC_ID", "978")),       # Referenced Object
    'DESC': int(os.environ.get("ATTR_DESC_ID", "981")),
    'STATE': int(os.environ.get("ATTR_STATE_ID", "982")),
    'OS': int(os.environ.get("ATTR_OS_ID", "2031")),             # Referenced Object
    'CPU': int(os.environ.get("ATTR_CPU_ID", "990")),
    'RAM': int(os.environ.get("ATTR_RAM_ID", "991")),
    'DISK_CNT': int(os.environ.get("ATTR_DSK_CNT_ID", "992")),
    'DISK_SZ': int(os.environ.get("ATTR_DSK_SZ_ID", "993")),
    'DEPLOYED': int(os.environ.get("ATTR_DEP_ID", "980")),
    'EXCLUDE': int(os.environ.get("ATTR_EXCL_ID", "2042")),
    'ADMINS': int(os.environ.get("ATTR_ADM_ID", "2021")),        # List of Users
    'VAPP_LINK': int(os.environ.get("ATTR_VAPP_ID", "979"))      # Logic check for n/a
}

# Маппинг ID атрибутов для объекта "User" в Insight
USER_ATTR_MAP = {
    'MAIL': int(os.environ.get("USR_ATTR_MAIL_ID", "1983")),
    'PHONE': int(os.environ.get("USR_ATTR_PHONE_ID", "1984")),
    'AVAIL': int(os.environ.get("USR_ATTR_AVAIL_ID", "1985"))
}

# Фильтры логики
INTERNAL_IP_PREFIXES = ['192.x', '192.x', '192.x'] # заменить на свои
PROD_KEYWORDS = ['CPRD']
LINUX_OS_LIST = ['CentOs7(64-bit)', 'SUSEopenSUSE(64-bit)', 'CentOs 7 (64-bit)', 'Linux', 'Ubuntu', 'RedHat']
SKIP_HOSTS = ["cprd-agp-lb01"] # Хосты, которые нужно пропустить

# --- Zabbix Configuration ---
# ID Групп хостов по умолчанию
ZBX_GRP_LINUX_DEFAULT = os.environ.get("ZBX_GRP_LINUX_DEF", "2")
ZBX_GRP_WIN_DEFAULT = os.environ.get("ZBX_GRP_WIN_DEF", "16")
ZBX_GRP_OTHER_DEFAULT = os.environ.get("ZBX_GRP_OTH_DEF", "2") # Fallback

# ID Шаблонов
ZBX_TMPL_LINUX = os.environ.get("ZBX_TMPL_LINUX", "13206")
ZBX_TMPL_WIN = os.environ.get("ZBX_TMPL_WIN", "13223")

# Доменные суффиксы для DNS
DOMAIN_SUFFIX = os.environ.get("DOMAIN_SUFFIX", ".internal.domain")

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def send_email(addr_to, msg_subj, msg_text):
    if not SMTP_PASSWORD:
        print("SMTP Password missing, skipping email notification.")
        return
        
    msg = MIMEMultipart()
    msg['From'] = SMTP_FROM_ADDR
    msg['To'] = addr_to
    msg['Subject'] = msg_subj
    msg.attach(MIMEText(msg_text, 'plain'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_FROM_ADDR, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Failed to send email: {e}")

def get_attr_value(attributes, attr_id):
    """Безопасное получение значения атрибута из Insight объекта"""
    for attr in attributes:
        if attr['objectTypeAttributeId'] == attr_id:
            vals = attr.get('objectAttributeValues', [])
            if vals:
                return vals[0]
    return None

def main():
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 1. Получение данных из Jira Insight
        jira_url_req = f'{JIRA_URL}/rest/insight/1.0/iql/objects?objectSchemaId={INSIGHT_SCHEMA_ID}&iql={requests.utils.quote(INSIGHT_IQL)}&resultPerPage={INSIGHT_PAGE_SIZE}'
        
        response = requests.get(
            jira_url_req, 
            auth=(JIRA_AUTH_USER, JIRA_PASSWORD), 
            verify=False, 
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        servers_data = response.json()
        
        prod_servers_registry = {}
        users_cache = {}
        
        for server in servers_data.get('objectEntries', []):
            exception = False
            is_prom = True
            find_vApp = False
            host_label = server['label']
            attributes = server['attributes']
            
            # Проверка исключений по IP
            ip_attr = get_attr_value(attributes, ATTR_MAP['IP'])
            if ip_attr:
                ip_val = ip_attr.get('value', '')
                if any(prefix in ip_val for prefix in INTERNAL_IP_PREFIXES):
                    exception = not exception
            
            # Определение PROD окружения
            env_attr = get_attr_value(attributes, ATTR_MAP['ENV_TYPE'])
            if env_attr:
                env_val = env_attr.get('value', '')
                # Логика из оригинала: если exception ИЛИ есть CPRD
                if exception or any(kw in env_val for kw in PROD_KEYWORDS):
                     # Это прод, но в оригинале здесь был break и инверсия флага is_prom
                     # Сохраняем логику оригинала:
                     prod_servers_registry[host_label] = {}
                     prod_servers_registry[host_label]['link'] = server['_links']['self']
                     is_prom = not is_prom # Становится False
                     # Дальнейшая обработка этого хоста идет ниже, если is_prom == False
                elif 'n/a' in env_val:
                    find_vApp = not find_vApp
            
            # Альтернативная проверка через vApp/Circuits
            if find_vApp:
                 circ_attr = get_attr_value(attributes, ATTR_MAP['CIRCUIT']) # В оригинале искался referencedObject с label 'ПРОМ'
                 # В оригинале код искал attribute где referencedObject.label == 'ПРОМ'. 
                 # Так как ID атрибута контура может быть разным, используем общий подход.
                 # Здесь упрощено: если нашли ссылку на объект типа Circuits с именем ПРОМ
                 for attr in attributes:
                     val = attr.get('objectAttributeValues', [{}])[0]
                     ref_obj = val.get('referencedObject', {})
                     if ref_obj and ref_obj.get('objectType', {}).get('name') == 'Circuits' and ref_obj.get('label') == 'ПРОМ':
                         prod_servers_registry[host_label] = {}
                         prod_servers_registry[host_label]['link'] = server['_links']['self']
                         is_prom = not is_prom
                         break

            # Если хост определен как PROD (is_prom == False после инверсии или логики выше)
            # В оригинале: if not is_prom: ... заполнение словаря
            # Но в оригинале также было: if exception or ... prod_servers_registry[host] = ... break
            # Чтобы не ломать логику, последуем структуре оригинала:
            
            # Перезапишем логику определения попадания в реестр точно как в оригинале, но с абстракциями
            # Оригинальный цикл:
            # 1. Check IP exception
            # 2. Check Env Attribute (979). If exception OR 'CPRD' in value -> Add to registry, is_prom = False, Break inner loop.
            # 3. Elif 'n/a' in value -> find_vApp = True
            # 4. If find_vApp -> Check referenced object 'Circuits' label 'ПРОМ' -> Add to registry, is_prom = False, Break.
            # 5. If not is_prom -> Fill details.
            
            # Реализуем это аккуратно:
            temp_registry_entry = {}
            added_to_registry = False
            
            # Шаг 1 & 2
            for attribute in attributes:
                if attribute['objectTypeAttributeId'] == ATTR_MAP['ENV_TYPE']:
                    val = attribute['objectAttributeValues'][0]['value']
                    if exception or ('CPRD' in val):
                        temp_registry_entry['link'] = server['_links']['self']
                        added_to_registry = True
                        is_prom = False
                        break
                    elif 'n/a' in val:
                        find_vApp = True
            
            # Шаг 3
            if not added_to_registry and find_vApp:
                for attribute in attributes:
                    val = attribute['objectAttributeValues'][0]
                    if 'referencedObject' in val:
                        ref = val['referencedObject']
                        if ref['objectType']['name'] == 'Circuits' and ref['label'] == 'ПРОМ':
                            temp_registry_entry['link'] = server['_links']['self']
                            added_to_registry = True
                            is_prom = False
                            break
            
            # Шаг 4: Заполнение
            if added_to_registry:
                current_host_data = {}
                current_host_data['link'] = temp_registry_entry['link']
                
                for attribute in attributes:
                    aid = attribute['objectTypeAttributeId']
                    val = attribute['objectAttributeValues'][0]
                    
                    if aid == ATTR_MAP['SYSTEM']: # Name/System
                         # В оригинале 917 -> name, 995 -> system (ref obj). 
                         # Внимание: в оригинале коде 917 это 'name', 995 это 'system'.
                         # Я использую маппинг выше. Проверим оригинал:
                         # 917: name
                         # 977: hostname
                         # 995: system (referencedObject label)
                         pass 

                # Пройдемся по всем атрибутам и заполним словарь согласно оригиналу
                for attribute in attributes:
                    aid = attribute['objectTypeAttributeId']
                    val = attribute['objectAttributeValues'][0]
                    
                    if aid == 917: # Hardcoded IDs from original logic mapped to generic vars would be better, 
                                   # but to ensure exact logic preservation I'll use the original IDs where possible 
                                   # or map them carefully. Let's stick to the mapping defined in CONFIG 
                                   # but since the original script had specific logic flow, let's replicate the filling.
                    
                    # Для точности воспроизведения логики заполнения, используем IDs из оригинала, 
                    # но заменим их на переменные, если они были в блоке CONFIG.
                    # Однако, в оригинале IDs были захардкожены в цикле заполнения.
                    # Я заменю их на ATTR_MAP константы, определенные выше.
                    
                    if aid == ATTR_MAP['SYSTEM_REF_NAME']: # Original 917 was 'name' field in inventory? No, 917 is likely a text field.
                        # Let's rely on the CONFIG mapping defined at top.
                        pass

                # Чтобы не запутаться в маппинге, я реализую заполнение, используя функции-хелперы и ATTR_MAP
                def get_ref_label(attr_id):
                    a = get_attr_value(attributes, attr_id)
                    if a and 'referencedObject' in a:
                        return a['referencedObject']['label']
                    return None
                
                def get_val(attr_id):
                    a = get_attr_value(attributes, attr_id)
                    if a: return a.get('value', '')
                    return None
                
                def get_display(attr_id):
                    a = get_attr_value(attributes, attr_id)
                    if a: return a.get('displayValue', '')
                    return None

                def get_status_name(attr_id):
                    a = get_attr_value(attributes, attr_id)
                    if a and 'status' in a:
                        return a['status'].get('name', '')
                    return None

                current_host_data['name'] = get_val(917) # Original ID for Name
                current_host_data['hostname'] = get_val(977) # Original ID for Hostname
                current_host_data['system'] = get_ref_label(ATTR_MAP['SYSTEM'])
                current_host_data['network'] = get_ref_label(ATTR_MAP['NETWORK'])
                current_host_data['role'] = get_ref_label(ATTR_MAP['ROLE'])
                current_host_data['circuit'] = get_ref_label(ATTR_MAP['CIRCUIT'])
                current_host_data['owner'] = get_display(ATTR_MAP['OWNER'])
                current_host_data['location'] = get_ref_label(ATTR_MAP['LOCATION'])
                current_host_data['description'] = get_val(ATTR_MAP['DESC'])
                current_host_data['state'] = get_status_name(ATTR_MAP['STATE'])
                current_host_data['ip'] = get_val(ATTR_MAP['IP'])
                current_host_data['os'] = get_ref_label(ATTR_MAP['OS'])
                current_host_data['cpu'] = get_val(ATTR_MAP['CPU'])
                current_host_data['memory'] = get_val(ATTR_MAP['RAM'])
                current_host_data['disksCount'] = get_val(ATTR_MAP['DISK_CNT'])
                current_host_data['disksSize'] = get_val(ATTR_MAP['DISK_SZ'])
                
                # Special logic for Circuit fallback
                env_val = get_val(ATTR_MAP['ENV_TYPE'])
                if env_val and 'CPRD' in env_val:
                     if 'circuit' not in current_host_data:
                         current_host_data['circuit'] = 'ПРОМ'

                current_host_data['deployed'] = get_val(ATTR_MAP['DEPLOYED'])
                current_host_data['exclude'] = get_val(ATTR_MAP['EXCLUDE'])
                
                # Administrators processing
                current_host_data['administrators'] = []
                admins_attr = get_attr_value(attributes, ATTR_MAP['ADMINS'])
                if admins_attr and 'objectAttributeValues' in admins_attr:
                    for user_ref in admins_attr['objectAttributeValues']:
                        username = user_ref.get('displayValue', '')
                        if not username: continue
                        
                        if username in users_cache:
                            user_dict = users_cache[username]
                        else:
                            users_cache[username] = {'username': username}
                            user_id_raw = user_ref.get('searchValue', '')
                            if '-' in user_id_raw:
                                user_id = user_id_raw.split("-")[1]
                                try:
                                    u_resp = requests.get(
                                        f'{JIRA_URL}/rest/insight/1.0/object/{user_id}',
                                        auth=(JIRA_AUTH_USER, JIRA_PASSWORD),
                                        verify=False,
                                        headers={"Content-Type": "application/json"}
                                    ).json()
                                    
                                    u_mail = get_attr_value(u_resp['attributes'], USER_ATTR_MAP['MAIL'])
                                    u_phone = get_attr_value(u_resp['attributes'], USER_ATTR_MAP['PHONE'])
                                    u_avail = get_attr_value(u_resp['attributes'], USER_ATTR_MAP['AVAIL'])
                                    
                                    users_cache[username]['mail'] = u_mail.get('value', '') if u_mail else ''
                                    users_cache[username]['phone'] = u_phone.get('value', '') if u_phone else ''
                                    users_cache[username]['availability'] = u_avail.get('value', '') if u_avail else ''
                                except Exception:
                                    users_cache[username]['mail'] = ''
                                    users_cache[username]['phone'] = ''
                                    users_cache[username]['availability'] = ''
                        
                        current_host_data['administrators'].append(users_cache[username])

                # Owner fallbacks (Original logic)
                if 'owner' not in current_host_data or not current_host_data['owner']:
                     sys_ref = get_attr_value(attributes, ATTR_MAP['SYSTEM'])
                     if sys_ref and 'searchValue' in sys_ref:
                         oid = sys_ref['searchValue'].split("-")[1]
                         try:
                             owner_resp = requests.get(f'{JIRA_URL}/rest/insight/1.0/object/{oid}', auth=(JIRA_AUTH_USER, JIRA_PASSWORD), verify=False, headers={"Content-Type": "application/json"}).json()
                             for oa in owner_resp['attributes']:
                                 if oa['objectTypeAttributeId'] == 941: # Original ID
                                     current_host_data['owner'] = oa['objectAttributeValues'][0]['displayValue']
                         except: pass
                
                if 'owner' not in current_host_data or not current_host_data['owner']:
                     sys_ref = get_attr_value(attributes, ATTR_MAP['SYSTEM'])
                     if sys_ref and 'searchValue' in sys_ref:
                         oid = sys_ref['searchValue'].split("-")[1]
                         try:
                             owner_resp = requests.get(f'{JIRA_URL}/rest/insight/1.0/object/{oid}', auth=(JIRA_AUTH_USER, JIRA_PASSWORD), verify=False, headers={"Content-Type": "application/json"}).json()
                             for oa in owner_resp['attributes']:
                                 if oa['objectTypeAttributeId'] == 1024: # Original ID
                                     current_host_data['owner'] = oa['objectAttributeValues'][0]['displayValue']
                         except: pass

                prod_servers_registry[host_label] = current_host_data

        # 2. Zabbix Integration
        zapi = ZabbixAPI(ZABBIX_URL)
        zapi.session.verify = False
        zapi.login(api_token=ZABBIX_API_TOKEN)
        
        hostgroups = zapi.do_request(method="hostgroup.get", params={
            "output": "extend",
            "selectHosts": "extend"
        })
        
        hosts_map = {}
        for group in hostgroups['result']:
            for host in group["hosts"]:
                if host['host'] not in hosts_map:
                    hosts_map[host['host']] = host['hostid']
        
        not_in_zabbix_list = []
        in_zabbix_dict = {}
        
        for server_name in prod_servers_registry:
            found_key = None
            # Variants to check
            variants = [
                server_name,
                server_name + DOMAIN_SUFFIX,
                server_name + '.sbs.lan', # Keep legacy check if needed or replace
                server_name.upper(),
                server_name.lower(),
                server_name + '-old',
                server_name[:-4].upper() if len(server_name) > 4 else None
            ]
            
            for v in variants:
                if v and v in hosts_map:
                    found_key = v
                    break
            
            if not found_key:
                not_in_zabbix_list.append(server_name)
            else:
                in_zabbix_dict[hosts_map[found_key]] = {
                    'cmdb_name': server_name,
                    'zabbix_name': found_key
                }

        network_error = []
        
        # Helper to ensure hostgroup exists
        def get_or_create_group(name):
            res = zapi.do_request(method="hostgroup.get", params={"filter": {"name": [name]}})
            if res['result']:
                return res['result'][0]['groupid']
            else:
                cr = zapi.do_request(method="hostgroup.create", params={"name": name})
                return cr['result']['groupids'][0]

        # Helper to ensure usergroup exists
        def get_or_create_usergroup(system_name, group_id, permission):
            suffix = "(ReadOnly)" if permission == 2 else "(ReadWrite)"
            safe_name = system_name[:50] if len(system_name) >= 50 else system_name
            ug_name = f"{safe_name} {suffix}"
            
            res = zapi.do_request(method="usergroup.get", params={"filter": {"name": [ug_name]}})
            if not res['result']:
                zapi.do_request(method="usergroup.create", params={
                    "name": ug_name,
                    "hostgroup_rights": [{"id": group_id, "permission": permission}]
                })

        # --- CREATE NEW HOSTS ---
        for host_name in not_in_zabbix_list:
            if host_name in SKIP_HOSTS: continue
            
            data = prod_servers_registry[host_name]
            if 'system' not in data: continue
            
            cmdb_groupid = get_or_create_group(data['system'])
            get_or_create_usergroup(data['system'], cmdb_groupid, 2)
            get_or_create_usergroup(data['system'], cmdb_groupid, 3)
            
            network_groupid = cmdb_groupid
            if 'network' in data:
                network_groupid = get_or_create_group(data['network'])
            else:
                network_error.append(host_name)
            
            os_str = data.get('os', '')
            is_linux = any(lx in os_str for lx in LINUX_OS_LIST) or 'linux' in os_str.lower()
            is_windows = 'Windows' in os_str
            is_powered = data.get('state') == 'PoweredOn'
            is_excluded = data.get('exclude') == 'true'
            
            if not is_powered or is_excluded:
                continue

            # Prepare Inventory
            admins = data.get('administrators', [])
            poc1 = admins[0] if len(admins) > 0 else {}
            poc2 = admins[1] if len(admins) > 1 else {}
            
            hw_full = ""
            if all(k in data for k in ['cpu', 'memory', 'disksCount', 'disksSize']):
                hw_full = f"Количество ядер: {data['cpu']}\nRAM, MB: {data['memory']}\nКоличество дисков: {data['disksCount']}\nОбщий размер дисков, ГБ: {data['disksSize']}"

            inventory = {
                "type": data.get('role', '')[:64],
                "os": data.get('os', ''),
                "asset_tag": data.get('owner', ''),
                "hardware_full": hw_full,
                "location": data.get('location', ''),
                "deployment_status": data.get('state', ''),
                "url_a": data.get('link', ''),
                "date_hw_install": data.get('deployed', ''),
                "poc_1_name": poc1.get('username', ''),
                "poc_1_email": poc1.get('mail', ''),
                "poc_1_phone_a": poc1.get('phone', '') if 'phone' in poc1 else '',
                "poc_1_notes": 'ОТПУСК' if poc1.get('availability') == 'false' else '',
                "poc_2_name": poc2.get('username', ''),
                "poc_2_email": poc2.get('mail', ''),
                "poc_2_phone_a": poc2.get('phone', '') if 'phone' in poc2 else '',
                "poc_2_notes": 'ОТПУСК' if poc2.get('availability') == 'false' else '',
            }

            interfaces = []
            templates = []
            groups = [{"groupid": cmdb_groupid}, {"groupid": network_groupid}]
            
            if 'ip' in data:
                ip_addr = data['ip'].split(';')[0]
                dns_name = ""
                if 'name' in data and DOMAIN_SUFFIX not in data['name']:
                     dns_name = data['name'] + DOMAIN_SUFFIX
                
                interfaces.append({
                    "type": 1, "main": 1, "useip": 1,
                    "ip": ip_addr, "dns": dns_name, "port": "10050"
                })
                
                if is_linux:
                    groups.append({"groupid": ZBX_GRP_LINUX_DEFAULT})
                    templates.append({"templateid": ZBX_TMPL_LINUX})
                elif is_windows:
                    groups.append({"groupid": ZBX_GRP_WIN_DEFAULT})
                    templates.append({"templateid": ZBX_TMPL_WIN})
                else:
                    # Other OS
                    pass

            tags = [
                {"tag": "Circuit", "value": data.get('circuit', '')},
                {"tag": "System", "value": data.get('system', '')}
            ]

            create_params = {
                "host": data.get('name', host_name) if not is_windows else data.get('name', host_name).upper(),
                "name": data.get('hostname', host_name) if not is_windows else data.get('hostname', host_name).upper(),
                "description": data.get('description', ''),
                "interfaces": interfaces,
                "groups": groups,
                "tags": tags,
                "templates": templates,
                "inventory_mode": 0,
                "inventory": inventory
            }
            
            # Remove empty templates list if needed or keep it
            if not templates: del create_params['templates']
            if not interfaces: del create_params['interfaces']

            try:
                zapi.do_request(method="host.create", params=create_params)
            except Exception as e:
                print(f"Error creating {host_name}: {e}")

        # --- UPDATE EXISTING HOSTS ---
        count = 0
        for zbx_hostid, mapping in in_zabbix_dict.items():
            count += 1
            cmdb_name = mapping['cmdb_name']
            if cmdb_name in SKIP_HOSTS: continue
            
            data = prod_servers_registry[cmdb_name]
            if 'system' not in data: continue
            
            cmdb_groupid = get_or_create_group(data['system'])
            get_or_create_usergroup(data['system'], cmdb_groupid, 2)
            get_or_create_usergroup(data['system'], cmdb_groupid, 3)
            
            network_groupid = cmdb_groupid
            if 'network' in data:
                network_groupid = get_or_create_group(data['network'])
            else:
                network_error.append(zbx_hostid)
            
            # Get current Zabbix Host details
            zbx_host = zapi.do_request(method="host.get", params={
                "selectHostGroups": ["groupid", "name"],
                "selectInventory": ["os", "type", "asset_tag", "hardware_full", "location", "deployment_status", "url_a", "date_hw_install", "poc_1_name", "poc_1_email", "poc_1_phone_a", "poc_1_notes", "poc_2_name", "poc_2_email", "poc_2_phone_a", "poc_2_notes"],
                "selectTags": "extend",
                "selectInterfaces": "extend",
                "filter": {"hostid": zbx_hostid}
            })
            
            if not zbx_host['result']: continue
            zbx_host = zbx_host['result'][0]
            
            changes_count = 0
            hostgroup_count = 0
            tag_count = 0
            interface_count = 0
            
            host_hostgroups = [{'groupid': hg['groupid']} for hg in zbx_host['hostgroups']]
            host_tags = [{'tag': t['tag'], 'value': t['value']} for t in zbx_host['tags']]
            host_interfaces = list(zbx_host['interfaces'])
            
            new_name = zbx_host['name']
            new_host = zbx_host['host']
            new_description = zbx_host['description']
            
            if 'ip' not in data or '.' not in data['ip'].split(';')[0]:
                continue
            
            # Interface Logic
            new_ip = ''
            new_dns = ''
            arr_ip = data['ip'].replace(" ", '').split(';')
            
            # Logic to select primary IP (prefer non-192.1 if possible, or first)
            candidate_ips = [ip for ip in arr_ip if '192.1' not in ip] # Заменить на свои IP
            if not candidate_ips: candidate_ips = arr_ip
            new_ip = candidate_ips[0] if candidate_ips else arr_ip[0]
            
            if 'name' in data and DOMAIN_SUFFIX not in data['name']:
                new_dns = data['name'] + DOMAIN_SUFFIX
            
            # Check existing interfaces
            valid_interfaces = []
            for iface in host_interfaces:
                if iface['type'] == '1' and iface['ip'] in arr_ip:
                    interface_count += 1
                    valid_interfaces.append(iface)
                elif iface['type'] == '1' and iface['ip'] not in arr_ip:
                    changes_count += 1 # IP mismatch
                else:
                    valid_interfaces.append(iface)
            
            if not host_interfaces and 'ip' in data:
                changes_count += 1
            
            # Group Logic
            target_group_ids = {cmdb_groupid, network_groupid}
            if 'Windows' in data.get('os', ''):
                target_group_ids.add(ZBX_GRP_WIN_DEFAULT)
            else:
                target_group_ids.add(ZBX_GRP_LINUX_DEFAULT)
                
            for hg in zbx_host['hostgroups']:
                if hg['groupid'] in target_group_ids:
                    hostgroup_count += 1
            
            expected_groups = len(target_group_ids)
            if hostgroup_count < expected_groups:
                changes_count += 1
            
            # Tag Logic
            expected_tags = {'Circuit': data.get('circuit', ''), 'System': data.get('system', '')}
            matched_tags = 0
            for t in zbx_host['tags']:
                if t['tag'] in expected_tags and t['value'] == expected_tags[t['tag']]:
                    matched_tags += 1
            
            if matched_tags < len(expected_tags):
                changes_count += 1
            
            # Inventory Logic Comparison
            inv = zbx_host['inventory']
            
            def check_inv_field(zbx_val, cmdb_val, max_len=None):
                nonlocal changes_count
                if max_len: cmdb_val = cmdb_val[:max_len]
                if zbx_val != cmdb_val:
                    changes_count += 1
                    return cmdb_val
                return zbx_val

            new_type = check_inv_field(inv['type'], data.get('role', ''), 64)
            new_os = check_inv_field(inv['os'], data.get('os', ''))
            new_asset_tag = check_inv_field(inv['asset_tag'], data.get('owner', ''))
            new_location = check_inv_field(inv['location'], data.get('location', ''))
            new_deployment_status = check_inv_field(inv['deployment_status'], data.get('state', ''))
            new_url_a = check_inv_field(inv['url_a'], data.get('link', ''))
            new_date_hw_install = check_inv_field(inv['date_hw_install'], data.get('deployed', ''))
            
            # Hardware Full
            hw_full_new = ""
            if all(k in data for k in ['cpu', 'memory', 'disksCount', 'disksSize']):
                hw_full_new = f"Количество ядер: {data['cpu']}\nRAM, MB: {data['memory']}\nКоличество дисков: {data['disksCount']}\nОбщий размер дисков, ГБ: {data['disksSize']}"
            new_hardware_full = check_inv_field(inv['hardware_full'], hw_full_new)
            
            # POC 1
            adm1 = data.get('administrators', [{}])[0] if data.get('administrators') else {}
            new_poc_1_name = check_inv_field(inv['poc_1_name'], adm1.get('username', ''))
            new_poc_1_email = check_inv_field(inv['poc_1_email'], adm1.get('mail', ''))
            new_poc_1_phone_a = check_inv_field(inv['poc_1_phone_a'], adm1.get('phone', ''))
            avail1 = 'ОТПУСК' if adm1.get('availability') == 'false' else ''
            new_poc_1_notes = check_inv_field(inv['poc_1_notes'], avail1)
            
            # POC 2
            adm2 = data.get('administrators', [{}]*2)[1] if len(data.get('administrators', [])) > 1 else {}
            new_poc_2_name = check_inv_field(inv['poc_2_name'], adm2.get('username', ''))
            new_poc_2_email = check_inv_field(inv['poc_2_email'], adm2.get('mail', ''))
            new_poc_2_phone_a = check_inv_field(inv['poc_2_phone_a'], adm2.get('phone', ''))
            avail2 = 'ОТПУСК' if adm2.get('availability') == 'false' else ''
            new_poc_2_notes = check_inv_field(inv['poc_2_notes'], avail2)
            
            if changes_count > 0:
                update_params = {
                    "hostid": zbx_hostid,
                    "host": new_host,
                    "name": new_name,
                    "description": new_description,
                    "inventory_mode": 0,
                    "inventory": {
                        "type": new_type, "os": new_os, "asset_tag": new_asset_tag,
                        "hardware_full": new_hardware_full, "location": new_location,
                        "deployment_status": new_deployment_status, "url_a": new_url_a,
                        "date_hw_install": new_date_hw_install,
                        "poc_1_name": new_poc_1_name, "poc_1_email": new_poc_1_email,
                        "poc_1_phone_a": new_poc_1_phone_a, "poc_1_notes": new_poc_1_notes,
                        "poc_2_name": new_poc_2_name, "poc_2_email": new_poc_2_email,
                        "poc_2_phone_a": new_poc_2_phone_a, "poc_2_notes": new_poc_2_notes,
                    }
                }
                
                # Add Groups if missing
                if hostgroup_count < expected_groups:
                    current_gids = {hg['groupid'] for hg in zbx_host['hostgroups']}
                    for gid in target_group_ids:
                        if gid not in current_gids:
                            host_hostgroups.append({"groupid": gid})
                    update_params["groups"] = host_hostgroups
                
                # Add Tags if missing
                if matched_tags < len(expected_tags):
                    current_tags_keys = {(t['tag'], t['value']) for t in zbx_host['tags']}
                    for tk, tv in expected_tags.items():
                        if (tk, tv) not in current_tags_keys:
                            host_tags.append({"tag": tk, "value": tv})
                    update_params["tags"] = host_tags
                
                # Add Interfaces if missing/mismatched
                if interface_count < 1 and new_ip:
                     host_interfaces.append({
                         "type": 1, "main": 1, "useip": 1,
                         "ip": new_ip, "dns": new_dns, "port": "10050"
                     })
                     update_params["interfaces"] = host_interfaces
                
                try:
                    zapi.do_request(method="host.update", params=update_params)
                except Exception as e:
                    print(f"Error updating {zbx_hostid}: {e}")

        print(f"Network errors/missing network info for hosts: {network_error}")

    except Exception as error:
        send_email(ERROR_EMAIL_TO, 'CMDB-Zabbix Integration Error', f'Script failed with error: {error}')
        sys.exit(1)

if __name__ == "__main__":
    main()
