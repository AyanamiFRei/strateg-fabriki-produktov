#!/usr/bin/env bash
# Сценарий «пришли данные Q1»: копия демо-проекта, новая выгрузка аналитика опровергает A04 (0,2 → 0,1).
# Показывает: регистрацию нового источника, исправление допущения, impact «было → стало», статус D01 = revisiting.
set -e
cd "$(dirname "$0")/../.."
PY=${PY:-python3}
rm -rf projects/demo-q1-data
cp -r projects/demo-family projects/demo-q1-data
cat > projects/demo-q1-data/materials/inbox/q1-logs.txt <<'TXT'
Выгрузка аналитика за 3 месяца Q1 (учебные данные сценария).
Доля подходящих групп, у которых впервые возник случай низкого остатка участника, составила 10 % в месяц.
TXT
$PY st.py --project demo-q1-data resume | grep -E "НОВЫЕ ДАННЫЕ|Стадия"
$PY st.py --project demo-q1-data source add --file projects/demo-q1-data/materials/inbox/q1-logs.txt --title "Выгрузка аналитика Q1" --reliability high --why "журналы оператора"
mv projects/demo-q1-data/materials/inbox/q1-logs.txt projects/demo-q1-data/materials/
cat > projects/demo-q1-data/inbox/q1.jsonl <<'JSON'
{"kind":"assumption","supersedes":"A04","change":"данные Q1: фактическая доля первых случаев 10 % в месяц","text":"Вероятность первого случая низкого остатка у подходящей группы в месяц — по данным Q1","key":"pool.first_case_rate","value":{"num":0.1,"unit":"доля в месяц"},"test":"подтверждено выгрузкой Q1 (S07)","confidence":"moderate"}
JSON
$PY st.py --project demo-q1-data claim import
$PY st.py --project demo-q1-data impact --ids A04 || true
$PY st.py --project demo-q1-data check all || true
