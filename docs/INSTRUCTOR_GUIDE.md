# Инструкция для преподавателя

## Содержание
1. [Архитектура системы](#1-архитектура-системы)
2. [Структура репозитория peer-review-hub](#2-структура-репозитория-peer-review-hub)
3. [Принятые архитектурные решения](#3-принятые-архитектурные-решения)
4. [Первоначальная настройка](#4-первоначальная-настройка)
5. [Настройка токенов](#5-настройка-токенов)
6. [Настройка репозитория peer-review-hub](#6-настройка-репозитория-peer-review-hub)
7. [Настройка защиты веток](#7-настройка-защиты-веток)
8. [Настройка GitHub Classroom](#8-настройка-github-classroom)
9. [Мониторинг и обслуживание](#9-мониторинг-и-обслуживание)

---

## 1. Архитектура системы

### Общая схема

```
GitHub Organization
├── peer-review-hub/              # центральный репо для peer review
│   ├── .github/workflows/
│   │   ├── assign_reviewer.yml   # триггер: PR opened/synchronize → назначить рецензента
│   │   ├── check_review.yml      # триггер: review submitted → проверить выполнение
│   │   ├── nightly_reminder.yml  # ежедневно: напомнить опоздавшим рецензентам
│   │   ├── add_students.yml      # ежедневно: добавить новых студентов в Team
│   │   └── report.yml            # ручной запуск сводки статусов (workflow_dispatch)
│   ├── scripts/
│   │   ├── assign.py             # алгоритм назначения рецензентов
│   │   ├── check_completion.py   # проверка выполнения рецензии
│   │   ├── remind.py             # рассылка напоминаний
│   │   ├── report.py             # сводка статусов для преподавателя
│   │   └── add_students_to_hub.py # добавление студентов в Team
│   ├── state/
│   │   ├── hw2.json              # создаётся автоматически при первом PR
│   │   └── hw3.json              # отдельный файл на каждое ДЗ
│   └── reviews/
│       ├── alice/theory.md       # студент пушит сюда теоретическую часть
│       └── bob/theory.md
│
├── hw2-alice/                    # GitHub Classroom: индивидуальные репо студентов
├── hw2-bob/                      # код и тесты живут здесь, не в peer-review-hub
└── ...
```

### Поток событий

```
1. Ежедневный workflow add_students.yml
   → находит всех Outside Collaborators организации
   → добавляет новых в Team peer-review-students
   → Team имеет write доступ к peer-review-hub

2. Студент пушит theory.md в ветку {login}/hw2 в peer-review-hub
   → открывает PR: {login}/hw2 → main

3. assign_reviewer.yml запускается при opened и synchronize:
   → на opened: валидирует имя ветки, путь к файлу, логин автора; мягко проверяет заголовок PR
   → на synchronize: если PR уже обработан (рецензент назначен) — тихий no-op
   → выбирает рецензента (алгоритм без A↔B)
   → назначает через GitHub API (requested_reviewers)
   → постит комментарий с инструкцией
   → обновляет state/hw*.json

4. Рецензент оставляет formal review + минимум 2 inline-комментария

5. check_review.yml запускается:
   → проверяет наличие formal review и количество комментариев
   → если требования не выполнены: постит комментарий с объяснением, что не хватает
   → если выполнены: обновляет счётчики в state, постит подтверждение
   → если автор получил 2 рецензии: ставит лейбл peer-review-complete
     (PR остаётся открытым — преподаватель закрывает вручную)

6. nightly_reminder.yml:
   → для каждой пары (рецензент, автор) где рецензия не засчитана:
     · первое напоминание — через N дней после назначения рецензента
     · повторные — раз в N дней (cooldown, дата записывается в last_reminded_at)
   → постит напоминание в PR автора
```

---

## 2. Структура репозитория peer-review-hub

```
peer-review-hub/
├── .github/
│   ├── pull_request_template.md      # шаблон для PR студентов
│   └── workflows/
│       ├── assign_reviewer.yml
│       ├── check_review.yml
│       ├── nightly_reminder.yml
│       ├── add_students.yml
│       └── report.yml
├── scripts/
│   ├── assign.py
│   ├── check_completion.py
│   ├── remind.py
│   ├── report.py
│   └── add_students_to_hub.py
├── state/                            # создаётся автоматически
│   └── hw2.json
├── reviews/                          # студенты пушат сюда
│   └── {login}/theory.md
├── STUDENT_GUIDE.md                  # инструкция для студентов
└── INSTRUCTOR_GUIDE.md               # этот файл
```

### Формат state/hw2.json

```json
{
  "students": {
    "alice": {
      "pr_url": "https://github.com/org/peer-review-hub/pull/1",
      "pr_number": 1,
      "submitted_at": "2024-03-01T10:00:00Z",
      "reviewers_assigned": ["bob", "charlie"],
      "reviewer_assigned_at": {
        "bob": "2024-03-01T10:05:00Z",
        "charlie": "2024-03-02T09:00:00Z"
      },
      "reviews_received": 2,
      "received_completed_at": "2024-03-05T11:45:00Z",
      "reviewing": ["bob"],
      "reviews_given": 2,
      "given_completed_at": "2024-03-04T15:30:00Z",
      "completed": true
    }
  },
  "pending": [],
  "counted_reviews": ["bob->alice", "charlie->alice"],
  "last_reminded_at": {
    "charlie->alice": "2024-03-04T08:00:00Z"
  }
}
```

Поля объекта студента:

| Поле | Тип | Описание |
|------|-----|----------|
| `pr_url` | string\|null | URL открытого PR |
| `pr_number` | int\|null | Номер PR |
| `submitted_at` | ISO string | Когда PR был обработан системой |
| `reviewers_assigned` | list[str] | Логины назначенных рецензентов |
| `reviewer_assigned_at` | dict[str, ISO] | Когда каждый рецензент был назначен |
| `reviews_received` | int | Сколько рецензий получено |
| `received_completed_at` | ISO string | Когда получена 2-я засчитанная рецензия |
| `reviewing` | list[str] | Кого этот студент рецензирует (назначено) |
| `reviews_given` | int | Сколько рецензий засчитано |
| `given_completed_at` | ISO string | Когда засчитана 2-я выданная рецензия |
| `completed` | bool | Получил ≥ 2 рецензий на свою работу (используется remind.py) |

Поля верхнего уровня:

| Поле | Описание |
|------|----------|
| `pending` | Студенты, ждущие назначения рецензента |
| `counted_reviews` | Засчитанные рецензии в формате `"reviewer->author"` |
| `last_reminded_at` | Дата последнего напоминания для пары `"reviewer->author"` |

---

## 3. Принятые архитектурные решения

### Единый репозиторий для peer review

Peer review проводится в отдельном репозитории `peer-review-hub`, а не в индивидуальных репозиториях студентов. Это позволяет:
- сохранить приватность кода (Classroom-репо остаются приватными)
- централизованно хранить state назначений
- использовать единые workflows

Компромисс: все студенты видят PR друг друга (теоретическую часть). Это было признано приемлемым — код по-прежнему скрыт.

### PR не мерджатся и не закрываются ботом

PR в `peer-review-hub` служат только площадкой для рецензирования. После получения двух рецензий бот ставит лейбл `peer-review-complete` и постит итоговый комментарий — PR при этом **остаётся открытым**. Преподаватель закрывает его вручную. Ветка `main` остаётся пустой. Это избавляет от конфликтов при повторной сдаче того же студента в следующем ДЗ (файл `reviews/alice/theory.md` существует только в ветке, не в main).

### State хранится в JSON в самом репо

Состояние назначений (кто кому назначен, сколько рецензий получено) хранится в `state/hw*.json` и коммитится ботом после каждого события. Отдельный файл на каждое ДЗ — `hw2.json`, `hw3.json` и т.д. Создаётся автоматически при первом PR по данному ДЗ.

### Защита от race condition через concurrency

Все три workflow, которые пишут в `state/` (`assign_reviewer`, `check_review`, `nightly_reminder`), используют `concurrency: group: state-write, cancel-in-progress: false`. Это встроенный мьютекс GitHub Actions — одновременно выполняется только один job записи, остальные ждут в очереди. При дедлайне с несколькими одновременными PR последний будет ждать ~2-3 минуты — приемлемо.

### Алгоритм назначения без A↔B

При выборе рецензента для студента A исключаются:
- сам A
- студенты, которые уже назначены рецензировать A (предотвращение взаимного рецензирования)
- студенты с максимальной нагрузкой (MAX_REVIEWS_PER_STUDENT = 4)
- студенты, ещё не открывшие свой PR

Среди оставшихся выбирается тот, у кого меньше всего **назначенных** (ещё не завершённых) рецензий — первичный критерий. При равной назначенной нагрузке предпочтение отдаётся тому, у кого меньше уже **засчитанных** рецензий. Если подходящих нет — студент попадает в `pending` и получает рецензента автоматически когда следующий студент откроет PR.

### Добавление студентов в Team через ежедневный scheduled workflow

GitHub Classroom добавляет студентов как Outside Collaborators, а не Members организации. Outside Collaborators не получают доступ через Base permissions — нужно явное добавление в Team. Решение: `add_students.yml` запускается раз в день, находит всех Outside Collaborators и добавляет их в Team `peer-review-students`. Максимальная задержка — 24 часа. Стоимость: ~1 минута Actions в день (~30 минут в месяц).

### Валидация PR перед назначением рецензента

Перед назначением рецензента workflow проверяет несколько условий — жёсткие и мягкое:

**Жёсткие проверки** (при нарушении workflow останавливается, рецензент не назначается):
1. Имя ветки начинается с реального логина (`github.actor`)
2. HW-часть ветки строго соответствует формату `hw<число>` (защита от обхода через `hw2-v2`, `hw2-final`)
3. Файл лежит в `reviews/{github.actor}/`

Студент должен исправить ошибку и запушить изменения — workflow перезапустится автоматически (триггер `synchronize`).

**Мягкая проверка** (только при первом открытии PR, не блокирует):
4. Заголовок PR соответствует формату `hw2: alice` — при несоответствии бот оставляет подсказку-комментарий, но назначение рецензента продолжается.

### Расход GitHub Actions минут

Основные источники расхода в `peer-review-hub`:
- `add_students.yml`: ~1 мин/день = ~30 мин/месяц
- `nightly_reminder.yml`: ~1 мин/день = ~30 мин/месяц
- `assign_reviewer.yml`: ~1 мин на каждый открытый PR
- `check_review.yml`: ~1 мин на каждый submitted review
- `report.yml`: ~1 мин на каждый ручной запуск

При 60 студентах и 7 ДЗ: ~60 PR + ~120 reviews = ~180 минут на семестр из `peer-review-hub`. Основной расход — workflows в индивидуальных Classroom-репо (тесты при каждом пуше).

---

## 4. Первоначальная настройка

### Порядок действий

1. Создать Team `peer-review-students` в организации
2. Создать PAT (см. раздел 5)
3. Создать репозиторий `peer-review-hub` и загрузить файлы
4. Добавить secrets в `peer-review-hub` (см. раздел 5)
5. Настроить защиту веток (см. раздел 7)
6. Настроить общие параметры репозитория (см. раздел 6)
7. Создать label `peer-review-complete`
8. Добавить `COORDINATOR_TOKEN` secret в шаблон Classroom-задания

### Создание Team peer-review-students

1. Перейдите в организацию → **Teams** → **New team**
2. Team name: `peer-review-students`
3. Visibility: **Visible**
4. Нажмите **Create team**
5. Перейдите в **Repositories** → **Add repository** → выберите `peer-review-hub`
6. Установите роль: **Write**

### Создание label

```bash
gh label create "peer-review-complete" --color "0075ca" --repo org/peer-review-hub
```

---

## 5. Настройка токенов

### Какие токены нужны

Системе нужен один Personal Access Token (PAT) с правами на управление организацией. Он используется под именем `GH_TOKEN` в `peer-review-hub` — для workflows назначения рецензентов.

### Создание PAT

1. Перейдите в GitHub → **Settings** (ваш профиль, не организации) → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Нажмите **Generate new token (classic)**
3. Note: `peer-review-bot`
4. Expiration: установите на срок курса + запас (например, 6 месяцев)
5. Выберите scopes:
   - `repo` (полный доступ к репозиториям)
   - `write:org` (управление командами организации)
   - `read:org`
6. Нажмите **Generate token**
7. **Сразу скопируйте токен** — он показывается только один раз

### Добавление токена в peer-review-hub

1. Перейдите в `peer-review-hub` → **Settings** → **Secrets and variables** → **Actions**
2. Нажмите **New repository secret**
3. Добавьте два secrets:

| Name | Value |
|------|-------|
| `GH_TOKEN` | ваш PAT |
| `ORG_NAME` | название организации (например, `my-university-org`) |

### Ротация токена

PAT имеет срок действия. За неделю до истечения GitHub пришлёт уведомление на email. Алгоритм обновления:
1. Создать новый PAT с теми же правами
2. Обновить secret `GH_TOKEN` в `peer-review-hub`
3. Обновить secret `COORDINATOR_TOKEN` в шаблоне Classroom
4. Удалить старый PAT

---

## 6. Настройка репозитория peer-review-hub

### General settings

Перейдите в **Settings** → **General**:

**Features** — отключите лишнее чтобы не путать студентов:
- [ ] Wikis — отключить
- [ ] Issues — отключить (всё общение идёт через PR-комментарии)
- [ ] Projects — отключить
- [ ] Discussions — отключить

**Pull Requests:**
- [ ] Allow merge commits — отключить
- [x] Allow squash merging — оставить (на случай если понадобится смерджить)
- [ ] Allow rebase merging — отключить
- [x] Automatically delete head branches — включить (ветки удаляются после закрытия PR)

**Forking:**
- [ ] Allow forking — **отключить**

> Форки не работают с текущей архитектурой: workflow в форке не запустится без одобрения мейнтейнера (защита GitHub от злоупотреблений).

---

## 7. Настройка защиты веток

### Защита ветки main

Запрещает студентам пушить напрямую в `main`.

1. Перейдите в **Settings** → **Rules** → **Rulesets** → **New ruleset** → **New branch ruleset**
2. Настройки:

| Параметр | Значение |
|---|---|
| Ruleset name | `Protect main` |
| Enforcement status | `Active` |
| Bypass list | `Organization admins` |
| Target branches | `Include default branch` |

3. Rules — включите:
   - [x] **Restrict deletions**
   - [x] **Restrict updates** (запрещает прямой push)
   - [x] **Block force pushes**
   - [ ] Require a pull request — **не включать** (бот закрывает PR без merge, required reviews заблокируют это)

4. Нажмите **Create**

### Почему нельзя ограничить пуш в чужую ветку

GitHub Rulesets не поддерживают правило вида "alice может пушить только в ветки `alice/*`". Это ограничение платформы. Защита реализована на уровне workflow: `assign_reviewer.yml` проверяет что `github.actor` совпадает с префиксом ветки и отклоняет PR если это не так.

---

## 8. Настройка GitHub Classroom

### Задание для peer review (групповой вариант)

Если вы хотите использовать GitHub Classroom для автоматического предоставления доступа к `peer-review-hub`:

1. Создайте новое задание → **Group assignment**
2. Maximum teams: `1`
3. Maximum members per team: без ограничений
4. Repository: выберите `peer-review-hub` как шаблон

> ⚠️ Classroom создаст **новый** репозиторий из шаблона, а не использует существующий `peer-review-hub`. Этот подход не подходит если вы хотите единый репозиторий для всех студентов. Используйте вместо этого ежедневный `add_students.yml`.

### Рекомендуемый подход: add_students.yml

Студенты добавляются автоматически через ежедневный scheduled workflow без каких-либо действий с их стороны. Максимальная задержка — 24 часа с момента принятия любого Classroom-задания.

### Добавление COORDINATOR_TOKEN в шаблон задания

Если в шаблоне Classroom-задания есть workflow требующий токен:

1. Перейдите в шаблонный репозиторий задания
2. **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
3. Добавьте `COORDINATOR_TOKEN` и `ORG_NAME`

---

## 9. Мониторинг и обслуживание

### Сводка статусов студентов

**Вариант 1: прямо в GitHub Actions (рекомендуется)**

1. Перейдите в `peer-review-hub` → **Actions** → **Peer Review Report**
2. Нажмите **Run workflow**
3. При желании укажите конкретное ДЗ в поле `hw` (например `hw2`); оставьте пустым — будут выведены все ДЗ
4. После завершения откройте запуск → вкладка **Summary** — там таблица в Markdown

`GH_TOKEN` и `HUB_REPO` подставляются автоматически из secrets репозитория.

**Вариант 2: локально**

```bash
cd peer-review-hub
git pull
GH_TOKEN=<ваш_токен> HUB_REPO=<org>/peer-review-hub python scripts/report.py --hw hw2
# или без --hw — все ДЗ из state/
GH_TOKEN=<ваш_токен> HUB_REPO=<org>/peer-review-hub python scripts/report.py
```

`GH_TOKEN` и `HUB_REPO` опциональны — нужны только для восстановления исторических дат через GitHub API (студенты, завершившие peer review до добавления date-tracking). Без них скрипт работает, но колонка Complete показывает `✓` вместо даты.

> ⚠️ `HUB_REPO` должен быть в формате `org/repo` (например `itmo-nn-2026/peer-review-hub`), не просто `org`. При неверном формате скрипт выведет предупреждение и отключит API fallback.

Вывод:
```
Login                Submitted    Rev.received   Rev.given   Waiting   Complete
-------------------------------------------------------------------------------
alice                2026-03-01   2/2            2/2                   2026-03-05
bob                  2026-03-02   1/2            1/2         wait
charlie              2026-03-01   0/2            2/2
```

Столбцы:
- **Submitted** — дата открытия PR (`submitted_at` из state)
- **Rev.received** — сколько рецензий получено на работу студента
- **Rev.given** — сколько рецензий студент сделал сам
- **Waiting** — `wait` если студент ожидает назначения второго рецензента
- **Complete** — дата когда выполнены оба условия зачёта (получил 2 + сделал 2), иначе пусто

### Ручной запуск add_students

Если студент не может открыть PR (нет доступа к репо):

1. Перейдите в `peer-review-hub` → **Actions** → **Add Students to Peer Review Hub**
2. Нажмите **Run workflow**

### Проверка упавших workflows

При race condition или временном сбое GitHub workflow упадёт с ошибкой. Перейдите в **Actions**, найдите упавший запуск, нажмите **Re-run failed jobs**.

### Напоминание: ротация PAT

Поставьте напоминание в календарь за 2 недели до истечения токена. GitHub также пришлёт email-уведомление.
