// Сборка витринных картинок для карточки в Маркете Битрикс24.
// Запуск:  node build.mjs [папка_со_скриншотами] [папка_для_результата]
// По умолчанию скриншоты берутся из ../.. (2026-10/), результат кладётся в .. (showcase/).
// Экран приложения — только исходные PNG: их кадрируем и масштабируем, ничего не дорисовываем.
import { createRequire } from 'module';
import { fileURLToPath, pathToFileURL } from 'url';
import path from 'path';
import fs from 'fs';
import os from 'os';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright-core')); }
catch { ({ chromium } = require('/root/node_modules/playwright-core')); }

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.resolve(process.argv[2] || path.join(HERE, '..', '..'));
const OUT = path.resolve(process.argv[3] || path.join(HERE, '..'));
const W = 1920, H = 1080; // предел Маркета: не больше 1920×1080

const SRC = { // исходные размеры в пикселях
  '01-task-tab.png': [3200, 1058], '02-task-split.png': [3200, 2354], '03-home.png': [2880, 1870],
  '04-project-board.png': [3360, 2160], '05-project-card.png': [920, 2160],
  '06-report-project-task.png': [2880, 1474], '07-report-revenue-leakage.png': [2880, 2600],
  '08-report-focus.png': [2880, 2280], '09-month-closing.png': [2880, 1144], '10-pro.png': [2880, 2572],
};

// win: x,y,w,h — окно на холсте (h вместе с шапкой окна); scale — экранных px на px исходника;
// ox, oy — смещение кадра в px исходника; bar — подпись в шапке окна (false — без шапки).
const A_WIN = { x: 800, y: 110, w: 1300, h: 1100 };
const B_WIN = { x: 96, y: 400, w: 1728 };

const slides = [
  { file: '01-cover.png', layout: 'a', cover: true,
    kicker: 'Приложение для Битрикс24',
    title: 'Учёт трудозатрат и&nbsp;ресурсов',
    sub: 'Рабочее время и деньги по проектам — прямо в задачах Битрикс24',
    tags: ['Вкладка в задаче', 'Доска проектов', 'Отчёты', 'Excel и 1С'],
    wins: [{ ...A_WIN, src: '03-home.png', scale: 0.56, bar: 'Главная' }] },

  { file: '02-task-tab.png', layout: 'b',
    kicker: 'Вкладка в задаче',
    title: 'Часы списываются прямо в&nbsp;задаче',
    sub: 'Не покидая карточку задачи. Такая же вкладка — в рабочей группе',
    wins: [{ ...B_WIN, y: 380, h: 611, src: '01-task-tab.png', scale: 0.54, bar: 'Задача · Учет времени' }] },

  { file: '03-project-board.png', layout: 'b', logo: false, textW: 1230,
    kicker: 'Доска проектов',
    title: 'Все проекты на&nbsp;одном экране',
    sub: 'В карточке проекта — бюджет, ставка, клиент и юрлицо',
    wins: [
      { ...B_WIN, h: 800, src: '04-project-board.png', scale: 1728 / 3360, bar: 'Проекты · Канбан' },
      { x: 1412, y: 44, w: 424, h: 995, src: '05-project-card.png', scale: 424 / 920, bar: false, front: true },
    ] },

  { file: '04-revenue-leakage.png', layout: 'a',
    kicker: 'Отчёт «Потери выручки»',
    title: 'Видно, где теряется выручка',
    sub: 'Где команда теряет оплачиваемые часы — по проектам и сотрудникам',
    wins: [{ ...A_WIN, src: '07-report-revenue-leakage.png', scale: 0.56, oy: 118, bar: 'Отчёты · Потери выручки' }] },

  { file: '05-report-project-task.png', layout: 'b',
    kicker: 'Отчёт «Учёт по проектам и задачам»',
    title: 'Проект → задача → подзадача',
    sub: 'Часы суммируются снизу вверх: всего, учтено и не учтено на каждом уровне',
    wins: [{ x: 154, y: 350, w: 1612, h: 800, src: '06-report-project-task.png', scale: 1612 / 2880, oy: 140, bar: 'Отчёты · Учёт по проектам и задачам' }] },

  { file: '06-month-closing.png', layout: 'b',
    kicker: 'Закрытие месяца',
    title: 'Закрытый месяц не&nbsp;меняется',
    sub: 'После закрытия периода записи в нём нельзя добавить или изменить',
    wins: [{ ...B_WIN, y: 356, h: 800, src: '09-month-closing.png', scale: 0.6, bar: 'Контроль · Закрытие месяца' }] },

  { file: '07-task-split.png', layout: 'a',
    kicker: 'Разделение записи',
    title: 'Одна запись — на&nbsp;несколько',
    sub: 'Отделите оплачиваемые часы от внутренних, не выходя из задачи',
    wins: [{ ...A_WIN, src: '02-task-split.png', scale: 0.56, ox: 36, oy: 396, bar: 'Задача · Правка записи' }] },

  { file: '08-pro.png', layout: 'a',
    kicker: 'Тариф Pro',
    title: 'Счета, БДДС и&nbsp;роли — в&nbsp;Pro',
    sub: 'Для компаний, которые выставляют клиентам счета по часам',
    list: ['Счета и акты — в CRM вашего портала', 'БДДС по проектам — факт и прогноз', 'Роли и права — настраиваются таблицей'],
    note: 'Подключается отдельно · заявка в приложении',
    wins: [{ ...A_WIN, src: '10-pro.png', scale: 0.56, oy: 118, bar: 'Заявка на Pro' }] },
];

const BAR = 40;
const rel = (from, to) => path.relative(from, to).split(path.sep).map(encodeURIComponent).join('/');

function winHtml(w, dir) {
  const [sw] = SRC[w.src];
  const bar = w.bar === false ? 0 : BAR;
  const img = `<img src="${rel(dir, path.join(SHOTS, w.src))}" style="width:${(sw * w.scale).toFixed(2)}px;left:${(-(w.ox || 0) * w.scale).toFixed(2)}px;top:${(-(w.oy || 0) * w.scale).toFixed(2)}px">`;
  return `<div class="win${w.front ? ' win--front' : ''}" style="left:${w.x}px;top:${w.y}px;width:${w.w}px;height:${w.h}px">
  ${bar ? `<div class="win__bar"><i></i><i></i><i></i><span>${w.bar}</span></div>` : ''}
  <div class="win__body" style="height:${w.h - bar}px">${img}</div>
</div>`;
}

function page(s, dir) {
  const logo = rel(dir, path.join(HERE, 'logo-white.png'));
  return `<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>${s.file}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=block" rel="stylesheet">
<link rel="stylesheet" href="${rel(dir, path.join(HERE, 'style.css'))}">
</head>
<body class="l-${s.layout}${s.cover ? ' is-cover' : ''}">
<div class="bg"></div><div class="orbit"></div>
${s.logo === false ? '' : `<img class="logo" src="${logo}" alt="Mainsoft">`}
<div class="text"${s.textW ? ` style="width:${s.textW}px"` : ''}>
  <div class="kicker">${s.kicker}</div>
  <h1>${s.title}</h1>
  <p class="sub">${s.sub}</p>
  ${s.list ? `<ul class="list">${s.list.map(t => `<li>${t}</li>`).join('')}</ul>` : ''}
  ${s.note ? `<p class="note">${s.note}</p>` : ''}
  ${s.tags ? `<div class="tags">${s.tags.map(t => `<span>${t}</span>`).join('')}</div>` : ''}
</div>
${s.wins.map(w => winHtml(w, dir)).join('\n')}
</body></html>`;
}

const exe = fs.readdirSync(path.join(os.homedir(), '.cache/ms-playwright'))
  .filter(d => d.startsWith('chromium_headless_shell-')).sort().pop();
const browser = await chromium.launch({
  executablePath: path.join(os.homedir(), '.cache/ms-playwright', exe, 'chrome-headless-shell-linux64/chrome-headless-shell'),
});
const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
fs.mkdirSync(OUT, { recursive: true });
const only = process.argv[4];
for (const s of slides) {
  if (only && !s.file.includes(only)) continue;
  const html = path.join(HERE, s.file.replace('.png', '.html'));
  fs.writeFileSync(html, page(s, HERE));
  const p = await ctx.newPage();
  await p.goto(pathToFileURL(html).href, { waitUntil: 'networkidle' });
  await p.evaluate(() => document.fonts.ready);
  const check = await p.evaluate(async () => {
    await Promise.all([...document.images].map(i => i.decode().catch(() => {})));
    return {
      onest: document.fonts.check('400 34px Onest', 'Учёт'), mono: document.fonts.check('500 20px "JetBrains Mono"', 'Учёт'),
      imgs: [...document.images].every(i => i.naturalWidth > 0),
      textBottom: Math.round(document.querySelector('.text').getBoundingClientRect().bottom),
      textRight: Math.round(Math.max(...[...document.querySelectorAll('.text > *')].map(e => { const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect().right; }))),
    };
  });
  await p.screenshot({ path: path.join(OUT, s.file), type: 'png' });
  console.log(s.file, JSON.stringify(check));
  if (!check.onest || !check.mono || !check.imgs) { console.error('ОШИБКА: шрифты или картинки не загрузились'); process.exitCode = 1; }
  await p.close();
}
await browser.close();
