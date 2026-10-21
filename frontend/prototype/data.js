// Демо-данные прототипа. Синтетика по мотивам golden dataset (docs/quality/golden-dataset-plan.md).
window.RDDH = {
  employee: { name: "Анна Смирнова", company: "ООО «Пример»" },
  period: { label: "Октябрь 2026", deadline: "31.10.2026", daysLeft: 5 },

  statuses: {
    draft: { label: "Черновик", cls: "b-gray" },
    processing: { label: "Распознаётся", cls: "b-info" },
    recognized: { label: "Проверьте поля", cls: "b-warn" },
    submitted: { label: "Отправлен", cls: "b-info" },
    in_review: { label: "У бухгалтера", cls: "b-warn" },
    approved: { label: "Одобрен", cls: "b-ok" },
    rejected: { label: "Отклонён", cls: "b-bad" },
    in_registry: { label: "В реестре", cls: "b-ok" },
    reimbursed: { label: "Компенсирован", cls: "b-ok" },
    no_receipt: { label: "Без чека", cls: "b-gray" },
  },

  expenses: [
    { id: 101, icon: "🎓", merchant: "Языковой центр «Лингва»", category: "Обучение / Английский язык", amount: 12000, date: "03.10", status: "in_registry", source: "Фото" },
    { id: 102, icon: "🏋️", merchant: "Спорт-Лайф", raw: "СПОРТЛАЙФ МСК", category: "Здоровье и спорт / Фитнес", amount: 3000, date: "07.10", status: "in_review", source: "PDF",
      reason: "Разовое занятие вместо абонемента — политика компенсирует только абонементы от 1 месяца" },
    { id: 103, icon: "🍽️", merchant: "Ресторан «Пушкин»", category: "Питание / Рестораны", amount: 4200, date: "09.10", status: "rejected", source: "Фото",
      reason: "Категория «Питание» не входит в программу компенсации на развитие и спорт" },
    { id: 104, icon: "📚", merchant: "Ozon", category: "Обучение / Профессиональная литература", amount: 1200, date: "12.10", status: "recognized", source: "Фото" },
    { id: 105, icon: "🧾", merchant: "Чек загружен", category: "распознаём, обычно до 5 секунд", amount: null, date: "14.10", status: "processing", source: "PDF" },
  ],

  review: {
    merchant_raw: "ООО \"ИНТЕРНЕТ РЕШЕНИЯ\"",
    merchant: "Ozon",
    date: "12.10.2026 18:42",
    total: 1600,
    payment: "Карта",
    category: "Обучение / Профессиональная литература",
    confidence: 0.71,
    items: [
      { name: "Учебник «English Grammar in Use»", amount: 1200, category: "Обучение / Профессиональная литература", ok: true },
      { name: "Кружка керамическая", amount: 400, category: "Прочее", ok: false },
    ],
    lowField: "total",
  },

  statusLog: [
    { at: "07.10 19:05", text: "Чек загружен (PDF)", actor: "Вы", state: "done" },
    { at: "07.10 19:05", text: "Распознан за 3,4 с, категория «Фитнес»", actor: "Система", state: "done" },
    { at: "07.10 19:06", text: "Отправлен на компенсацию", actor: "Вы", state: "done" },
    { at: "07.10 19:06", text: "Помечен спорным: разовое занятие, а не абонемент", actor: "Система", state: "done" },
    { at: "ожидается", text: "Решение бухгалтера — срок до 14.10", actor: "Бухгалтер", state: "pending" },
  ],

  queue: [
    { id: 102, employee: "Анна Смирнова", merchant: "Спорт-Лайф", raw: "СПОРТЛАЙФ МСК", amount: 3000, category: "Здоровье и спорт / Фитнес", confidence: 0.64,
      reason: "Разовое занятие вместо абонемента", basis: "Политика п. 2.3: только абонементы от 1 месяца", waiting: "1 д." },
    { id: 117, employee: "Игорь Петров", merchant: "Спорт-Лайф", raw: "ООО Спорт-Лайф", amount: 4500, category: "Фитнес + Массаж", confidence: 0.58,
      reason: "Смешанный чек: абонемент 3 000 ₽ и массаж 1 500 ₽", basis: "Массаж не входит в политику", waiting: "2 д." },
    { id: 121, employee: "Мария Ким", merchant: "—", raw: "нечитаемо", amount: 24000, category: "Здоровье и спорт / Фитнес", confidence: 0.41,
      reason: "Низкая уверенность OCR: продавец не распознан", basis: "Скан без текстового слоя", waiting: "3 д." },
    { id: 126, employee: "Олег Савин", merchant: "Skyeng", raw: "SKYENG LLC", amount: 9800, category: "Обучение / Английский язык", confidence: 0.83,
      reason: "Повторная загрузка: похожий чек 01.10 на ту же сумму", basis: "Дубль по сумме и продавцу, ФН/ФД отсутствуют", waiting: "1 д." },
  ],

  registry: {
    period: "01.10.2026 — 31.10.2026",
    included: [
      { employee: "Анна Смирнова", merchant: "Языковой центр «Лингва»", category: "Английский язык", amount: 12000 },
      { employee: "Игорь Петров", merchant: "Спорт-Лайф", category: "Фитнес (абонемент)", amount: 3000 },
      { employee: "Мария Ким", merchant: "World Class", category: "Фитнес", amount: 24000 },
      { employee: "Олег Савин", merchant: "Skyeng", category: "Английский язык", amount: 9800 },
    ],
    excluded: [
      { employee: "Анна Смирнова", merchant: "Ресторан «Пушкин»", amount: 4200, reason: "Вне политики: питание" },
      { employee: "Игорь Петров", merchant: "Спорт-Лайф", amount: 1500, reason: "Массаж не компенсируется (позиция смешанного чека)" },
    ],
  },
};

window.rub = (v) => (v == null ? "—" : v.toLocaleString("ru-RU") + " ₽");
