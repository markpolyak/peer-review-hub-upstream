# peer-review-hub

## Структура репозитория

```
.github/workflows/
    assign_reviewer.yml   # триггер: PR opened
    check_review.yml      # триггер: review submitted
    nightly_reminder.yml  # напоминания раз в сутки
scripts/
    assign.py             # алгоритм назначения рецензентов
    check_completion.py   # проверка выполнения рецензии
    remind.py             # рассылка напоминаний
    report.py             # сводка для преподавателя
state/
    hw2.json              # создаётся автоматически
reviews/
    {login}/theory.md     # студент пушит сюда
```

## Первоначальная настройка

### 1. Secrets репозитория

| Secret | Значение |
|--------|----------|
| `GH_TOKEN` | PAT с правами `repo`, `write:org` |
| `ORG_NAME` | Название организации |

### 2. Labels (создать вручную один раз)

```bash
gh label create "peer-review-complete" --color "0075ca" --repo org/peer-review-hub
```

### 3. Добавить студентов в репо

```bash
python scripts/add_students_to_hub.py
```

(Скрипт ищет все репо `hw2-*` в организации и добавляет владельцев в Team)

## Workflow студента

1. Скопировать теоретическую часть в `reviews/{github_login}/theory.md`
2. Запушить в ветку `{github_login}/hw2`
3. Открыть PR: `{github_login}/hw2 → main`
4. Бот назначит рецензента и напишет комментарий
5. Проверить 2 чужие работы (откликнуться на назначение в PR)

## Отчёт для преподавателя

```bash
git pull
python scripts/report.py --hw hw2
```

## Параметры

В `assign.py`:
- `MAX_REVIEWS_PER_STUDENT = 4` — максимум исходящих рецензий

В `check_completion.py` и `remind.py`:
- `MIN_COMMENTS_REQUIRED = 2` — минимум inline-комментариев

В `nightly_reminder.yml`:
- `REMINDER_DAYS: "3"` — через сколько дней напомнить
