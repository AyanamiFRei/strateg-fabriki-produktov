---
name: after-decision
description: Сопровождение после решения — запись решений с основаниями, обязательства с ролями и сроками, условия пересмотра; пересмотр выводов при новых данных с пересчётом и «было → стало». Используй после принятия рекомендации, при новых данных или вопросе «что решать сейчас».
---
# Сопровождение и пересмотр (stage `after`)

**Знания:** `kb/methods/F-decision-support.md` (F1–F6).

## Записать решение
1. Файл `projects/<p>/decisions/D-new.json`:
```json
{"question":"Запускать ли пилот к концу Q1?","options":["O01","O02","O03","O04"],"chosen":"O02",
 "rejected":{"O03":"дороже, выборки не хватит"},"basis":["K03","F05","A07"],"key_assumptions":["A07"],
 "expect":{"metric":"…","from":0.12,"to":0.09,"by":"2027-06-30"},
 "kill":[{"signal":"жалобы на списания","threshold":"> 0,5% групп","action":"стоп пилота","owner":"руководитель продукта"}],
 "revisit":[{"type":"date","at":"2027-04-15"},{"type":"metric","key":"pilot.recruit_week","op":"<","value":60},
            {"type":"claim","ids":["A07"]}],"due":"2027-03-31","approver":"руководитель направления"}
```
   Синтетика [Y] в `basis` запрещена (код 2).
2. `python st.py decide new projects/<p>/decisions/D-new.json` → покажи человеку → `decide accept D01 --note "<его слова>"`.
3. Обязательства: `python st.py decide commit --what "…" --owner "роль" --due 2027-02-15 --decision D01`.
4. `python st.py decide list` → `decisions/DECISIONS.md`. «Что решать сейчас»: `python st.py decide due`.

## Пересмотр при новых данных
1. Новый файл → `source add --file` (или `--note`). Изменённые величины — строки с `"supersedes":"F12"` (новая цитата!)
   или новые факты; опровергнутое — `claim retract`.
2. `python st.py impact --ids <изменённые>` → отчёт IMPACT: пересчитанные [K] «было → стало», утверждения на пересмотр,
   разделы для переписывания, затронутые решения (статус `revisiting`, код 3).
3. Перепиши только затронутые разделы, `python st.py check all`.
4. Пользователю: что **изменилось**, что **подтвердилось**, меняется ли рекомендация. Решение — за человеком:
   `decide confirm D01 --note` (в силе) или `decide supersede D01 <новый.json>` → `decide accept`.
Принятое решение никогда не редактируется задним числом.

Метрики после запуска: `python st.py decide observe <ключ> --value <число>` — триггеры проверяются сразу.
