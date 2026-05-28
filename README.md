# CMDB to Zabbix Auto-Provisioning & Sync

Скрипт для автоматической синхронизации инфраструктуры между **Jira Insight (CMDB)** и **Zabbix**.

## 📋 Описание

Инструмент выполняет двунаправленную задачу по поддержанию актуальности мониторинга:
1.  **Auto-Provisioning:** Автоматически создает новые хосты в Zabbix на основе данных из CMDB (Jira Insight).
2.  **Sync & Enrichment:** Обновляет существующие хосты в Zabbix (инвентарь, теги, группы, интерфейсы), если данные в CMDB изменились.

Скрипт ориентирован на выделение **PROD/CPRD** окружений и игнорирует тестовые/временные сервера, основываясь на атрибутах объектов в Insight.

### Ключевые возможности:
*   **Умный фильтр PROD:** Определяет боевые сервера по атрибутам `Environment Type`, `Circuits` или внутренним IP-адресам.
*   **Обогащение инвентаря:** Заполняет поля Zabbix Inventory (HW specs, POC contacts, Location, OS) данными из Jira.
*   **Управление доступом:** Автоматически создает User Groups в Zabbix с правами Read/Write на основе системных групп из CMDB.
*   **Контактная информация:** Подтягивает email и телефоны администраторов сервера из объектов `User` в Jira для быстрой связи при алертах.
*   **Обработка исключений:** Пропускает хосты в списке `SKIP_HOSTS` и выключенные/исключенные сервера.

## 🏗 Архитектура и Логика работы

1.  **Fetch:** Скрипт забирает список объектов типа `Servers` из Jira Insight через IQL запрос.
2.  **Filter:** Итерируется по серверам, определяя принадлежность к PROD:
    *   Если IP входит во внутренние подсети (`192.x.x.x` и др.) -> **PROD**.
    *   Если атрибут `Environment` содержит `CPRD` -> **PROD**.
    *   Если атрибут `Environment` равен `n/a`, но связан с контуром `ПРОМ` -> **PROD**.
3.  **Enrich:** Для PROD-серверов собирает полные данные (CPU, RAM, Disk, Admins, Owner).
4.  **Match:** Сравнивает список серверов с хостами в Zabbix (по имени, FQDN, alias).
5.  **Action:**
    *   **New Host:** Создает хост, назначает шаблоны (Linux/Windows), группы, теги и заполняет инвентарь.
    *   **Existing Host:** Сравнивает текущее состояние в Zabbix с данными из CMDB. Если есть расхождения (IP, теги, инвентарь, группы) -> обновляет хост.

## ⚙️ Требования

*   Python 3.6+
*   Библиотеки:
    ```bash
    pip install requests pyzabbix
    ```
*   Доступ к API Jira (Insight/Object schema) и Zabbix API.

## 🔐 Настройка переменных окружения

Скрипт **не хранит** пароли в коде. Все чувствительные данные передаются через переменные окружения (например, в GitLab CI/CD Variables).

### Обязательные переменные

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `JIRA_URL` | URL вашего Jira сервера | `https://jira.company.com` |
| `JIRA_AUTH_USER` | Пользователь для доступа к Insight API | `sa-zabbix-bot` |
| `JIRA_PASSWORD` | Пароль или API Token пользователя Jira | `secret_jira_pass` |
| `ZABBIX_URL` | URL вашего Zabbix сервера | `https://zabbix.company.com` |
| `ZABBIX_API_TOKEN` | API Token для Zabbix (пользователь с правами Admin) | `a1b2c3d4...` |
| `SMTP_SERVER` | Адрес SMTP сервера для уведомлений об ошибках | `smtp.company.com` |
| `SMTP_FROM_ADDR` | Email отправителя уведомлений | `zabbix-alerts@company.com` |
| `SMTP_PASSWORD` | Пароль от ящика отправителя | `secret_smtp_pass` |
| `ERROR_EMAIL_TO` | Email для получения отчетов об ошибках | `admin-team@company.com` |

### Переменные конфигурации Insight (ID Атрибутов)

Эти ID зависят от вашей конкретной схемы объектов в Jira Insight. Их нужно узнать в настройках Object Schema.

| Переменная | Значение по умолчанию | Описание атрибута в Jira |
| :--- | :--- | :--- |
| `INSIGHT_SCHEMA_ID` | `7` | ID схемы объектов |
| `ATTR_IP_ID` | `985` | IP Address |
| `ATTR_ENV_ID` | `979` | Environment Type (Prod/Dev) |
| `ATTR_SYS_ID` | `995` | System (Referenced Object) |
| `ATTR_NET_ID` | `984` | Network Segment (Referenced Object) |
| `ATTR_ROLE_ID` | `1001` | Server Role (Referenced Object) |
| `ATTR_CIRC_ID` | `1000` | Circuit/Contour (Referenced Object) |
| `ATTR_OWN_ID` | `996` | Owner (Display Value) |
| `ATTR_LOC_ID` | `978` | Location (Referenced Object) |
| `ATTR_DESC_ID` | `981` | Description |
| `ATTR_STATE_ID` | `982` | State (PoweredOn/Off) |
| `ATTR_OS_ID` | `2031` | Operating System (Referenced Object) |
| `ATTR_CPU_ID` | `990` | CPU Cores |
| `ATTR_RAM_ID` | `991` | RAM (MB) |
| `ATTR_DSK_CNT_ID` | `992` | Disk Count |
| `ATTR_DSK_SZ_ID` | `993` | Total Disk Size (GB) |
| `ATTR_DEP_ID` | `980` | Deployment Date |
| `ATTR_EXCL_ID` | `2042` | Exclude from Monitoring flag |
| `ATTR_ADM_ID` | `2021` | Administrators (List of Users) |
| `USR_ATTR_MAIL_ID` | `1983` | User Email (в объекте User) |
| `USR_ATTR_PHONE_ID` | `1984` | User Phone (в объекте User) |
| `USR_ATTR_AVAIL_ID` | `1985` | User Availability (Vacation flag) |

### Переменные конфигурации Zabbix

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `ZBX_GRP_LINUX_DEF` | `2` | ID группы "Linux servers" |
| `ZBX_GRP_WIN_DEF` | `16` | ID группы "Windows servers" |
| `ZBX_TMPL_LINUX` | `13206` | ID шаблона для Linux (например, Template OS Linux) |
| `ZBX_TMPL_WIN` | `13223` | ID шаблона для Windows (например, Template OS Windows) |
| `DOMAIN_SUFFIX` | `.internal.domain` | Суффикс для формирования FQDN |

## 🚀 Запуск

### Локально

1.  Экспортируйте переменные окружения:
    ```bash
    export JIRA_PASSWORD="your_password"
    export ZABBIX_API_TOKEN="your_token"
    # ... остальные переменные
    ```
2.  Запустите скрипт:
    ```bash
    python3 cmdb_zabbix_sync.py
    ```

### GitLab CI/CD

Пример конфига `.gitlab-ci.yml`:

```yaml
stages:
  - sync

cmdb_sync_job:
  stage: sync
  tags:
    - your-runner-tag
  script:
    - pip install requests pyzabbix
    - python3 cmdb_zabbix_sync.py
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      when: always
```

Не забудьте добавить все переменные из раздела **Настройка переменных окружения** в Settings > CI/CD > Variables вашего проекта.

## ⚠️ Важные нюансы

1.  **ID Атрибутов:** Если вы развернете скрипт на новой инсталляции Jira Insight, вам **обязательно** нужно заменить ID атрибутов в переменных окружения на те, что используются в вашей схеме. Не совпадение ID приведет к тому, что скрипт не увидит данные (IP, OS и т.д.).
2.  **Производительность:** При первом запуске на большой базе (тысячи серверов) скрипт может работать долго из-за дополнительных запросов к API Jira для получения деталей пользователей (Admins). В коде реализован кэш пользователей (`users_cache`) для оптимизации.
3.  **Безопасность:** Скрипт отключает проверку SSL сертификатов (`verify=False`) для внутренних ресурсов. Убедитесь, что это допустимо в вашей политике безопасности, или настройте корректные CA-сертификаты на раннере.
4.  **Создание групп:** Скрипт автоматически создает Host Groups и User Groups в Zabbix, если они отсутствуют. Имена групп берутся из атрибута `System` в Jira.

## 🛠 Troubleshooting

*   **Ошибка `Missing required environment variables`:** Проверьте, что все секретные переменные переданы в окружение.
*   **Хосты не создаются:** Проверьте логи на наличие `Network errors`. Часто причина в отсутствии атрибута `Network` у сервера в Jira или в том, что сервер помечен как `Exclude` или `PoweredOff`.
*   **Неверные данные в инвентаре:** Убедитесь, что ID атрибутов (`ATTR_...`) соответствуют вашей схеме Insight.
