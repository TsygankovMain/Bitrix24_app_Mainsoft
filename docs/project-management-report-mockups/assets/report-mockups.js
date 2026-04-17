const TODAY = new Date('2026-04-05T10:00:00');

const projects = [
  {
    id: 'PR-101',
    name: 'РетроФарм B2B Portal',
    company: 'РетроФарм',
    curator: 'Анна Жукова',
    stage: 'В работе',
    support: false,
    budgetHours: 420,
    spentHours: 368,
    hourlyRate: 2400,
    lastWriteoffDays: 2,
    startDate: '2026-02-03',
    endDate: '2026-04-22',
    recent7DaysHours: 30,
    recent28DaysHours: 118,
    recent90DaysHours: 312,
    companyBound: true,
    legalEntity: 'ООО Мэйнсофт',
    ourLegalEntity: 'ООО Мэйнсофт'
  },
  {
    id: 'PR-102',
    name: 'СТК Cabinet Migration',
    company: 'СТК',
    curator: 'Мария Ильина',
    stage: 'В работе',
    support: false,
    budgetHours: 280,
    spentHours: 259,
    hourlyRate: 2200,
    lastWriteoffDays: 5,
    startDate: '2026-01-20',
    endDate: '2026-04-18',
    recent7DaysHours: 26,
    recent28DaysHours: 92,
    recent90DaysHours: 244,
    companyBound: true,
    legalEntity: 'ООО Мэйнсофт',
    ourLegalEntity: 'ООО Мэйнсофт'
  },
  {
    id: 'PR-103',
    name: 'АвтоЛайн BI Layer',
    company: 'АвтоЛайн',
    curator: 'Егор Смирнов',
    stage: 'В работе',
    support: false,
    budgetHours: 310,
    spentHours: 348,
    hourlyRate: 2600,
    lastWriteoffDays: 1,
    startDate: '2025-12-15',
    endDate: '2026-04-12',
    recent7DaysHours: 34,
    recent28DaysHours: 131,
    recent90DaysHours: 286,
    companyBound: true,
    legalEntity: 'АО Mainsoft Delivery',
    ourLegalEntity: 'АО Mainsoft Delivery'
  },
  {
    id: 'PR-104',
    name: 'БелМед CRM Rollout',
    company: 'БелМед',
    curator: 'Мария Ильина',
    stage: 'Нет списаний 1 месяц',
    support: false,
    budgetHours: 360,
    spentHours: 142,
    hourlyRate: 2300,
    lastWriteoffDays: 41,
    startDate: '2025-11-11',
    endDate: '2026-03-20',
    recent7DaysHours: 0,
    recent28DaysHours: 6,
    recent90DaysHours: 88,
    companyBound: true,
    legalEntity: 'ООО Мэйнсофт',
    ourLegalEntity: 'ООО Мэйнсофт'
  },
  {
    id: 'PR-105',
    name: 'Орбита Contract Hub',
    company: 'Орбита',
    curator: 'Павел Котов',
    stage: 'Нет списаний 3 месяца',
    support: false,
    budgetHours: 190,
    spentHours: 74,
    hourlyRate: 2100,
    lastWriteoffDays: 97,
    startDate: '2025-08-10',
    endDate: '2026-02-28',
    recent7DaysHours: 0,
    recent28DaysHours: 0,
    recent90DaysHours: 12,
    companyBound: true,
    legalEntity: 'ООО Мэйнсофт',
    ourLegalEntity: 'ООО Мэйнсофт'
  },
  {
    id: 'PR-106',
    name: 'Вектор HR Cabinet',
    company: '',
    curator: 'Анна Жукова',
    stage: 'В просчете',
    support: false,
    budgetHours: null,
    spentHours: 18,
    hourlyRate: 0,
    lastWriteoffDays: 9,
    startDate: '2026-03-01',
    endDate: '2026-04-30',
    recent7DaysHours: 4,
    recent28DaysHours: 18,
    recent90DaysHours: 18,
    companyBound: false,
    legalEntity: '',
    ourLegalEntity: ''
  },
  {
    id: 'PR-107',
    name: 'Сфера Analytics Layer',
    company: 'Сфера',
    curator: '',
    stage: 'Новый',
    support: false,
    budgetHours: 260,
    spentHours: 0,
    hourlyRate: 2500,
    lastWriteoffDays: 0,
    startDate: '2026-04-01',
    endDate: '2026-06-10',
    recent7DaysHours: 0,
    recent28DaysHours: 0,
    recent90DaysHours: 0,
    companyBound: true,
    legalEntity: 'ООО Мэйнсофт',
    ourLegalEntity: 'ООО Мэйнсофт'
  },
  {
    id: 'PR-108',
    name: 'Лидер Mobile Cabinet',
    company: 'Лидер Доставка',
    curator: 'Егор Смирнов',
    stage: 'В работе',
    support: false,
    budgetHours: 520,
    spentHours: 392,
    hourlyRate: 2350,
    lastWriteoffDays: 1,
    startDate: '2026-01-17',
    endDate: '2026-05-08',
    recent7DaysHours: 29,
    recent28DaysHours: 101,
    recent90DaysHours: 332,
    companyBound: true,
    legalEntity: 'АО Mainsoft Delivery',
    ourLegalEntity: 'АО Mainsoft Delivery'
  },
  {
    id: 'PR-109',
    name: 'North Tech Support',
    company: 'North Tech',
    curator: 'Павел Котов',
    stage: 'В работе',
    support: true,
    budgetHours: null,
    spentHours: 144,
    hourlyRate: 1900,
    lastWriteoffDays: 3,
    startDate: '2025-10-01',
    endDate: '2026-12-31',
    recent7DaysHours: 11,
    recent28DaysHours: 37,
    recent90DaysHours: 126,
    companyBound: true,
    legalEntity: 'Сервисный контур',
    ourLegalEntity: 'Сервисный контур'
  },
  {
    id: 'PR-110',
    name: 'ПраймИнвест Support Flow',
    company: 'ПраймИнвест',
    curator: 'Анна Жукова',
    stage: 'В работе',
    support: true,
    budgetHours: null,
    spentHours: 96,
    hourlyRate: 1850,
    lastWriteoffDays: 6,
    startDate: '2025-12-01',
    endDate: '2026-09-30',
    recent7DaysHours: 8,
    recent28DaysHours: 31,
    recent90DaysHours: 94,
    companyBound: true,
    legalEntity: 'Сервисный контур',
    ourLegalEntity: 'Сервисный контур'
  },
  {
    id: 'PR-111',
    name: 'Альфа Retail Replatform',
    company: 'Альфа Retail',
    curator: 'Мария Ильина',
    stage: 'В работе',
    support: false,
    budgetHours: 640,
    spentHours: 548,
    hourlyRate: 2450,
    lastWriteoffDays: 12,
    startDate: '2025-12-05',
    endDate: '2026-04-30',
    recent7DaysHours: 20,
    recent28DaysHours: 76,
    recent90DaysHours: 238,
    companyBound: true,
    legalEntity: '',
    ourLegalEntity: ''
  },
  {
    id: 'PR-112',
    name: 'Дельта Docs Portal',
    company: 'Дельта',
    curator: 'Павел Котов',
    stage: 'Успех',
    support: false,
    budgetHours: 220,
    spentHours: 214,
    hourlyRate: 2250,
    lastWriteoffDays: 18,
    startDate: '2025-10-07',
    endDate: '2026-03-01',
    recent7DaysHours: 0,
    recent28DaysHours: 8,
    recent90DaysHours: 56,
    companyBound: true,
    legalEntity: 'ООО Мэйнсофт',
    ourLegalEntity: 'ООО Мэйнсофт'
  }
];

function diffDays(from, to) {
  return Math.round((to - from) / 86400000);
}

function parseDate(value) {
  if (!value) return null;
  return new Date(`${value}T00:00:00`);
}

function formatNumber(value) {
  return new Intl.NumberFormat('ru-RU').format(Number(value || 0));
}

function formatHours(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${formatNumber(Math.round(Number(value)))} ч`;
}

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${formatNumber(Math.round(Number(value)))} ₽`;
}

function formatMoneyRate(value) {
  if (value === null || value === undefined || Number(value) <= 0) return '—';
  return `${formatNumber(Math.round(Number(value)))} ₽/ч`;
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0))}%`;
}

function formatDate(value) {
  const parsed = parseDate(value);
  if (!parsed) return '—';
  return new Intl.DateTimeFormat('ru-RU').format(parsed);
}

function getRecentHours(project, periodKey) {
  return Number(project[periodKey] || 0);
}

function getBurnRatio(project) {
  if (project.support || !project.budgetHours) return null;
  return project.spentHours / project.budgetHours;
}

function getRemainingHours(project) {
  if (project.support || !project.budgetHours) return null;
  return project.budgetHours - project.spentHours;
}

function getSpentValue(project) {
  return project.spentHours * Number(project.hourlyRate || 0);
}

function getBudgetValue(project) {
  if (project.support || !project.budgetHours || !project.hourlyRate) return null;
  return project.budgetHours * project.hourlyRate;
}

function getRemainingValue(project) {
  const remaining = getRemainingHours(project);
  if (remaining === null || !project.hourlyRate) return null;
  return remaining * project.hourlyRate;
}

function getForecastDays(project, periodKey) {
  if (project.support) return null;
  const remaining = getRemainingHours(project);
  if (remaining === null) return null;
  const periodHours = getRecentHours(project, periodKey);
  const daysWindow = periodKey === 'recent7DaysHours' ? 7 : periodKey === 'recent28DaysHours' ? 28 : 90;
  if (periodHours <= 0) return null;
  return Math.round((remaining / periodHours) * daysWindow);
}

function getProjectedExhaustDate(project, periodKey) {
  const forecastDays = getForecastDays(project, periodKey);
  if (forecastDays === null) return null;
  const date = new Date(TODAY);
  date.setDate(date.getDate() + forecastDays);
  return date;
}

function getDeadlineDelta(project) {
  const end = parseDate(project.endDate);
  if (!end) return null;
  return diffDays(TODAY, end);
}

function getRiskBreakdown(project) {
  const reasons = [];
  let score = 0;

  if (project.lastWriteoffDays >= 90) {
    score += 45;
    reasons.push('90+ дней без списаний');
  } else if (project.lastWriteoffDays >= 30) {
    score += 30;
    reasons.push('30+ дней без списаний');
  } else if (project.lastWriteoffDays >= 14) {
    score += 12;
    reasons.push('слабая активность по списаниям');
  }

  const deadlineDelta = getDeadlineDelta(project);
  if (deadlineDelta !== null && deadlineDelta < 0 && !['Успех', 'Провал'].includes(project.stage)) {
    score += 20;
    reasons.push('дедлайн уже прошел');
  } else if (deadlineDelta !== null && deadlineDelta <= 14 && !['Успех', 'Провал'].includes(project.stage)) {
    score += 10;
    reasons.push('дедлайн ближе 14 дней');
  }

  const burnRatio = getBurnRatio(project);
  if (burnRatio !== null && burnRatio > 1.05) {
    score += 28;
    reasons.push('перерасход проектного объема');
  } else if (burnRatio !== null && burnRatio >= 0.85) {
    score += 14;
    reasons.push('освоено 85%+ бюджета');
  }

  if (!project.support && !project.budgetHours) {
    score += 15;
    reasons.push('не задан проектный объем');
  }
  if (Number(project.hourlyRate || 0) <= 0) {
    score += 12;
    reasons.push('не задана ставка часа');
  }
  if (!project.companyBound) {
    score += 8;
    reasons.push('не привязана компания');
  }
  if (!project.curator) {
    score += 10;
    reasons.push('не назначен куратор');
  }
  if (!project.ourLegalEntity) {
    score += 8;
    reasons.push('не задано юрлицо');
  }
  if (project.stage === 'В просчете' && project.spentHours > 10) {
    score += 8;
    reasons.push('идут часы без перехода в работу');
  }

  let level = 'Низкий';
  if (score >= 60) level = 'Высокий';
  else if (score >= 30) level = 'Средний';

  return { score, level, reasons, deadlineDelta, burnRatio };
}

function getRiskClass(level) {
  if (level === 'Высокий') return 'danger';
  if (level === 'Средний') return 'warning';
  return 'success';
}

function buildCuratorStats(list, periodKey) {
  const map = new Map();

  list.forEach((project) => {
    const key = project.curator || 'Без куратора';
    if (!map.has(key)) {
      map.set(key, {
        curator: key,
        projectCount: 0,
        activeProjects: 0,
        supportProjects: 0,
        totalBudgetHours: 0,
        spentHours: 0,
        weightedRisk: 0,
        highRiskCount: 0,
        inactiveCount: 0,
        deadlinePressure: 0,
        missingDataCount: 0,
        forecastValue: 0,
        projects: []
      });
    }

    const row = map.get(key);
    const risk = getRiskBreakdown(project);
    row.projectCount += 1;
    if (!['Успех', 'Провал'].includes(project.stage)) row.activeProjects += 1;
    if (project.support) row.supportProjects += 1;
    row.totalBudgetHours += Number(project.budgetHours || 0);
    row.spentHours += Number(project.spentHours || 0);
    row.weightedRisk += risk.score;
    if (risk.level === 'Высокий') row.highRiskCount += 1;
    if (project.lastWriteoffDays >= 30) row.inactiveCount += 1;
    if (risk.deadlineDelta !== null && risk.deadlineDelta <= 14 && !['Успех', 'Провал'].includes(project.stage)) row.deadlinePressure += 1;
    if (!project.companyBound || !project.curator || !project.ourLegalEntity || (!project.support && !project.budgetHours) || Number(project.hourlyRate || 0) <= 0) row.missingDataCount += 1;
    row.forecastValue += Number(getRemainingValue(project) || 0);
    row.projects.push({ ...project, risk });
  });

  return Array.from(map.values()).map((row) => ({
    ...row,
    avgRisk: row.projectCount ? Math.round(row.weightedRisk / row.projectCount) : 0,
    burnShare: row.totalBudgetHours ? row.spentHours / row.totalBudgetHours : null,
    recentLoad: row.projects.reduce((sum, project) => sum + getRecentHours(project, periodKey), 0),
  })).sort((a, b) => (b.avgRisk - a.avgRisk) || (b.projectCount - a.projectCount));
}

window.ProjectReportMockData = {
  TODAY,
  projects,
  formatNumber,
  formatHours,
  formatMoney,
  formatMoneyRate,
  formatPercent,
  formatDate,
  getRiskBreakdown,
  getRiskClass,
  getBurnRatio,
  getRemainingHours,
  getSpentValue,
  getBudgetValue,
  getRemainingValue,
  getForecastDays,
  getProjectedExhaustDate,
  getDeadlineDelta,
  getRecentHours,
  buildCuratorStats,
};
