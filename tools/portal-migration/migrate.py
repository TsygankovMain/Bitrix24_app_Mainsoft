#!/usr/bin/env python3
"""Переносит копию августа со смарт-процессов mainsoft.bitrix24.ru на nfr-mainsoft.

Три слоя: компании -> проекты -> списания часов. Каждый слой пишет таблицу
соответствия old->new в JSON рядом со скриптом, поэтому повторный запуск
не создаёт дубли, а дозаливает недостающее.

Источник (mainsoft):  СП 1164 «Метки часов», 1300 «Проекты», компании (4).
Приёмник (nfr):       СП 1100 «Учет трудозатрат (App)», 1102 «Проекты (App)».

Сотрудников исходного портала на приёмнике нет (совпал один из 55), поэтому
23 автора списаний детерминированно раскладываются по существующим
пользователям nfr. Таблица — в user_map_effective.json.

    python3 migrate.py companies|projects|items|check
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ['B24_MAINSOFT_WEBHOOK'].rstrip('/')
DST = os.environ['B24_WEBHOOK'].rstrip('/')

SRC_TIMESHEET, SRC_PROJECT = 1164, 1300
DST_TIMESHEET, DST_PROJECT = 1100, 1102

# поле «дата отражения» в исходном СП
F_DATE = 'ufCrm87_1764446274'


def call(base, method, payload, tries=4):
    """REST-вызов POST-JSON. Битрикс изредка отвечает 500 на ровном месте —
    поэтому ретраи с паузой, а не падение всей заливки на одной записи."""
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(
            f'{base}/{method}.json',
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            if 'error' in d and d.get('error'):
                last = d.get('error_description') or d.get('error')
                # ошибка бизнес-логики не лечится повтором
                if 'QUERY_LIMIT' not in str(last).upper():
                    raise RuntimeError(f'{method}: {last}')
            return d
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
        except urllib.error.URLError as e:
            last = str(e.reason)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f'{method}: не удалось после {tries} попыток ({last})')


def load(name, default):
    p = os.path.join(HERE, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def save(name, data):
    with open(os.path.join(HERE, name), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def users_map():
    """old user id -> nfr user id. Детерминированно и стабильно между запусками."""
    cached = load('user_map_effective.json', None)
    if cached:
        return cached

    items = load('august_source.json', [])
    src_ids = sorted({str(i.get('ufCrm87_1761919601')) for i in items if i.get('ufCrm87_1761919601')})

    dst = []
    start = 0
    while True:
        d = call(DST, 'user.get', {'FILTER': {'ACTIVE': True}, 'start': start})
        res = d.get('result', [])
        dst += res
        if not d.get('next') or not res:
            break
        start = d['next']
    pool = sorted(str(u['ID']) for u in dst)

    mapping = {old: pool[idx % len(pool)] for idx, old in enumerate(src_ids)}
    save('user_map_effective.json', mapping)
    print(f'сотрудников исходных: {len(src_ids)}, пользователей nfr: {len(pool)}')
    return mapping


def migrate_companies():
    companies = load('august_companies.json', [])
    done = load('map_companies.json', {})

    # что уже есть на приёмнике — сверяем по названию, чтобы не плодить копии
    existing, start = {}, 0
    while True:
        d = call(DST, 'crm.item.list', {'entityTypeId': 4, 'select': ['id', 'title'], 'start': start})
        res = d.get('result', {}).get('items', [])
        for c in res:
            existing.setdefault((c.get('title') or '').strip().lower(), str(c['id']))
        if not d.get('next') or not res:
            break
        start = d['next']

    created = reused = 0
    for c in companies:
        old = str(c['id'])
        if old in done:
            continue
        title = (c.get('title') or '').strip()
        found = existing.get(title.lower())
        if found:
            done[old] = found
            reused += 1
            continue
        d = call(DST, 'crm.item.add', {'entityTypeId': 4, 'fields': {'title': title}})
        done[old] = str(d['result']['item']['id'])
        created += 1
    save('map_companies.json', done)
    print(f'компании: создано {created}, переиспользовано {reused}, всего в карте {len(done)}')


def migrate_projects():
    projects = load('august_projects.json', [])
    companies = load('map_companies.json', {})
    umap = users_map()
    done = load('map_projects.json', {})

    created = 0
    for p in projects:
        old = str(p['id'])
        if old in done:
            continue
        fields = {
            'title': p.get('title') or f'Проект {old}',
            'ufCrm46HourlyRate': p.get('ufCrm213HourlyRate') or 0,
            'ufCrm46ProjectHoursBudget': p.get('ufCrm213ProjectHoursBudget') or 0,
            'ufCrm46IsArchived': p.get('ufCrm213IsArchived') or 'N',
            'ufCrm46IsSupport': p.get('ufCrm213IsSupport') or 'N',
        }
        if p.get('ufCrm213BitrixGroupId'):
            fields['ufCrm46BitrixGroupId'] = int(p['ufCrm213BitrixGroupId'])
        if p.get('companyId') and str(p['companyId']) in companies:
            fields['companyId'] = int(companies[str(p['companyId'])])
        if p.get('assignedById') and str(p['assignedById']) in umap:
            fields['assignedById'] = int(umap[str(p['assignedById'])])
        d = call(DST, 'crm.item.add', {'entityTypeId': DST_PROJECT, 'fields': fields})
        done[old] = str(d['result']['item']['id'])
        created += 1
    save('map_projects.json', done)
    print(f'проекты: создано {created}, всего в карте {len(done)}')


def as_list(value):
    if value is None or value == '':
        return None
    return value if isinstance(value, list) else [value]


def migrate_items():
    items = load('august_source.json', [])
    projects = load('map_projects.json', {})
    umap = users_map()
    done = load('map_items.json', {})

    created = 0
    for n, it in enumerate(items, 1):
        old = str(it['id'])
        if old in done:
            continue
        emp = umap.get(str(it.get('ufCrm87_1761919601')))
        fields = {
            'title': it.get('title') or f'Списание {old}',
            'ufCrm44Hours': float(it.get('ufCrm87_1761919617') or 0),
            'ufCrm44NonBillable': float(it.get('ufCrm87_1762023633') or 0),
            'ufCrm44Description': it.get('ufCrm87_1762026149771') or '',
            'ufCrm44IsBillable': it.get('ufCrm87_1763717129') or 'N',
            'ufCrm44TaskName': it.get('ufCrm87_1764361585') or '',
            'ufCrm44Project': it.get('ufCrm87_1764265641') or '',
            'ufCrm44OurInn': str(it.get('ufCrm87_1769624604091') or it.get('ufCrm87OurInn') or ''),
            'ufCrm44ClientInn': str(it.get('ufCrm87_1769624613999') or ''),
        }
        if it.get(F_DATE):
            fields['ufCrm44Date'] = it[F_DATE]
        if emp:
            fields['ufCrm44Employee'] = int(emp)
            fields['assignedById'] = int(emp)
        for src_key, dst_key in (('ufCrm87_1761919581', 'ufCrm44TaskId'),
                                 ('ufCrm87_1764265626', 'ufCrm44ProjectId')):
            if it.get(src_key):
                try:
                    fields[dst_key] = int(it[src_key])
                except (TypeError, ValueError):
                    pass
        for src_key, dst_key in (('ufCrm87_1764191110', 'ufCrm44HierIds'),
                                 ('ufCrm87_1764191133', 'ufCrm44HierTitles')):
            v = as_list(it.get(src_key))
            if v:
                fields[dst_key] = [str(x) for x in v]
        new_project = projects.get(str(it.get('parentId1300')))
        if new_project:
            fields['parentId1102'] = int(new_project)
            fields['ufCrm44ProjectItemId'] = int(new_project)

        d = call(DST, 'crm.item.add', {'entityTypeId': DST_TIMESHEET, 'fields': fields})
        done[old] = str(d['result']['item']['id'])
        created += 1
        if created % 50 == 0:
            save('map_items.json', done)
            print(f'  перенесено {created} (обработано {n} из {len(items)})', flush=True)
    save('map_items.json', done)
    print(f'списания: создано {created}, всего в карте {len(done)}')


def check():
    """Сверка по факту, а не по кодам ответов: количество и сумма часов."""
    items = load('august_source.json', [])
    src_hours = sum(float(i.get('ufCrm87_1761919617') or 0) for i in items)

    got, start = [], 0
    while True:
        d = call(DST, 'crm.item.list', {'entityTypeId': DST_TIMESHEET,
                                        'select': ['id', 'ufCrm44Hours', 'ufCrm44Date',
                                                   'ufCrm44Employee', 'parentId1102'],
                                        'start': start})
        res = d.get('result', {}).get('items', [])
        got += res
        if not d.get('next') or not res:
            break
        start = d['next']

    dst_hours = sum(float(i.get('ufCrm44Hours') or 0) for i in got)
    no_project = sum(1 for i in got if not i.get('parentId1102'))
    no_emp = sum(1 for i in got if not i.get('ufCrm44Employee'))

    print(f'источник: записей {len(items)}, часов {src_hours:.1f}')
    print(f'приёмник: записей {len(got)}, часов {dst_hours:.1f}')
    print(f'без проекта: {no_project} | без сотрудника: {no_emp}')
    print('СХОДИТСЯ' if len(got) == len(items) and abs(src_hours - dst_hours) < 0.01
          else 'РАСХОЖДЕНИЕ')


if __name__ == '__main__':
    step = sys.argv[1] if len(sys.argv) > 1 else ''
    {'companies': migrate_companies, 'projects': migrate_projects,
     'items': migrate_items, 'check': check}.get(step, lambda: print(__doc__))()
